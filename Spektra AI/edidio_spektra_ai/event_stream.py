"""Live event stream: watch a controller's real-time events (inputs, sensors,
triggers, DALI frames).

The firmware pushes events to a client that has registered via an ``EventMessage``
with ``event = REGISTER`` and an ``EventFilter`` selecting categories. Events then
arrive asynchronously on that connection. Because the rest of Spektra AI is
request/response, this uses a **separate connection** with a background asyncio read
loop, so the push stream never interferes with the main command path. Events are
decoded into compact dicts and kept in a rolling buffer; MCP tools poll the buffer
(``recent_events``) rather than holding a socket open to the model.

Registration + framing verified live against a bench controller; live event emission
is device-activity dependent (physical inputs/sensors/DALI traffic).
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb
from edidio_control_py import EdidioClient

from . import event_stream_v2, spektra_map

_LOGGER = logging.getLogger(__name__)

# EventFilter fields, exposed as friendly category names for the MCP tool.
CATEGORY_FIELDS = {
    "inputs": "input",
    "dali_arc": "dali_arc_level",
    "dali_command": "dali_command",
    "sensors": "dali_sensor",
    "dali_inputs": "dali_input",
    "dmx_changed": "dmx_stream_changed",
    "dali_24_frame": "dali_24_frame",
    "triggers": "trigger_message",
}
DEFAULT_CATEGORIES = ("inputs", "sensors", "triggers", "dali")

_MOTION_STATES = {v.number: v.name for v in pb.DALIMotionSensorStates.DESCRIPTOR.values}
_TRIGGER_TYPES = {v.number: v.name for v in pb.TriggerType.DESCRIPTOR.values}


def build_register_message(message_id: int, categories) -> bytes:
    """Frame an EventMessage(REGISTER) with an EventFilter for the given categories."""
    kwargs = {}
    for cat in categories:
        field = CATEGORY_FIELDS.get(cat)
        if field:
            kwargs[field] = True
    filt = pb.EventFilter(**kwargs)
    return spektra_map._frame(
        message_id, event=pb.EventMessage(event=pb.EventType.REGISTER, filter=filt))


def decode_event(ev) -> dict | None:
    """Turn an EventMessage into a compact, human-friendly dict (or None if empty)."""
    etype = pb.EventType.Name(ev.event)
    which = ev.WhichOneof("event_data")
    base = {"event": etype, "at": datetime.now().isoformat(timespec="seconds")}

    if which == "sensor":
        s = ev.sensor
        base.update(kind="sensor", index=s.index, line=s.line, address=s.address,
                    motion=_MOTION_STATES.get(s.motion_state, s.motion_state),
                    lux_level=s.lux_level)
    elif which == "trigger":
        t = ev.trigger
        base.update(kind="trigger",
                    type=_TRIGGER_TYPES.get(t.type, t.type),
                    source=t.source, zone=t.zone, line_mask=t.line_mask,
                    target=t.target_address, value=t.value)
    elif which == "inputs":
        base.update(kind="input", input_mask=ev.inputs.input_mask,
                    inputs=list(ev.inputs.inputs))
    elif which == "dali_24_input":
        d = ev.dali_24_input
        base.update(kind="dali_input", index=d.index, line=d.line,
                    address=d.address, type=d.type, arg=d.arg)
    elif which == "dali_24_frame":
        d = ev.dali_24_frame
        base.update(kind="dali_frame", line=d.line, frame=d.frame)
    elif which == "payload":
        base.update(kind="payload")
    else:
        base.update(kind=which or "unknown")
    return base


class EventStream:
    """Owns a dedicated connection that registers for and buffers device events."""

    def __init__(self, host: str, port: int = 23, use_tls: bool = False,
                 *, buffer_size: int = 200, client_factory=None, on_event=None,
                 use_v2: bool = True):
        self._host, self._port, self._use_tls = host, port, use_tls
        self._factory = client_factory or (
            lambda: EdidioClient(host, port, use_tls=use_tls))
        self._client = None
        self._task: asyncio.Task | None = None
        self._buffer: deque = deque(maxlen=buffer_size)
        self._seq = 0
        self._categories: tuple = ()
        self._running = False
        # Optional async callback invoked for each decoded event (the notifier hook).
        self._on_event = on_event
        # Firmware >= 1.4.0 uses Event Stream v2 (EventStreamMessage, tag 77); older
        # firmware uses the legacy EventMessage REGISTER path in this module.
        self._use_v2 = use_v2

    @property
    def running(self) -> bool:
        return self._running

    @property
    def categories(self) -> tuple:
        return self._categories

    async def start(self, categories=DEFAULT_CATEGORIES):
        """Connect, subscribe for the categories, and start the background reader.
        Uses Event Stream v2 (tag 77) unless ``use_v2`` is False (legacy tag 34)."""
        if self._running:
            await self.stop()
        self._categories = tuple(categories)
        self._client = self._factory()
        await self._client.connect()
        if self._use_v2:
            mask = event_stream_v2.categories_to_mask(self._categories)
            await self._client.send_protobuf_message(event_stream_v2.build_subscribe(mask))
        else:
            await self._client.send_protobuf_message(
                build_register_message(1, self._categories))
        self._running = True
        self._task = asyncio.ensure_future(self._read_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        if self._client is not None:
            try:
                if self._use_v2:
                    await self._client.send_protobuf_message(
                        event_stream_v2.build_unsubscribe())
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    async def _read_loop(self):
        """Continuously read framed messages; buffer decoded events."""
        while self._running:
            try:
                data = await self._client._receive_framed()  # resync-capable framing
            except asyncio.CancelledError:
                break
            except Exception as err:  # noqa: BLE001 — keep the stream alive on hiccups
                if self._running:
                    _LOGGER.debug("event read error: %s", err)
                    await asyncio.sleep(0.2)
                continue
            if self._use_v2:
                msg = event_stream_v2.parse_edidio(data)
                if not event_stream_v2.is_event_stream(msg):
                    continue                   # skip subscribe ACK / non-events
                decoded = event_stream_v2.decode(msg)
            else:
                msg = pb.EdidioMessage()
                try:
                    msg.ParseFromString(data)
                except Exception:  # noqa: BLE001
                    continue
                if msg.WhichOneof("payload") != "event":
                    continue                   # skip the REGISTER ack / non-events
                decoded = decode_event(msg.event)
            if decoded is None:
                continue
            self._seq += 1
            decoded["seq"] = self._seq         # our own monotonic buffer index
            self._buffer.append(decoded)
            if self._on_event is not None:
                try:
                    await self._on_event(decoded)
                except Exception as err:  # noqa: BLE001 — a hook must not kill the reader
                    _LOGGER.debug("on_event hook error: %s", err)

    def recent(self, since_seq: int = 0, limit: int = 50) -> list:
        """Return buffered events with seq > since_seq (most recent up to limit)."""
        items = [e for e in self._buffer if e["seq"] > since_seq]
        return items[-limit:]

    @property
    def last_seq(self) -> int:
        return self._seq
