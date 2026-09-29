"""Per-controller collection: health polling + live event stream.

Each :class:`ControllerCollector` owns two things:

* a request/response :class:`EdidioClient`, polled for ``DIAGNOSTIC_SYSTEM_INFO``
  (reachability, firmware/hardware, configuration counts, active profile), and
* an :class:`EventStream` (firmware >= 1.4.0) that feeds a :class:`LevelTracker`
  (DALI levels seen on the bus) and per-kind event counters.

:meth:`families` turns the current state into metric families for
:mod:`exposition`. Clients are injectable so tests run without a controller.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter

from edidio_control_py import DiagnosticMessageType, EdidioClient
from edidio_control_py.events import EventStream
from edidio_control_py.exceptions import EDIDIOConnectionError
from edidio_control_py.state import LevelTracker, dali_change

_LOGGER = logging.getLogger(__name__)

# DiagnosticSystemInfoResponse field -> `kind` label on edidio_config_count.
COUNT_FIELDS = {
    "spektra_seq_count": "sequences",
    "spektra_theme_count": "themes",
    "spektra_static_count": "statics",
    "spektra_zone_count": "zones",
    "list_count": "lists",
    "alarm_count": "schedules",
    "input_count": "inputs",
    "output_count": "outputs",
    "ir_count": "ir",
    "logic_count": "logic",
    "profile_count": "profiles",
    "line_count": "lines",
    "input_dali_count": "dali_inputs",
}


def _target(address: int) -> str:
    if address == 80:
        return "broadcast"
    return "group" if address >= 64 else "address"


class ControllerCollector:
    def __init__(self, name: str, host: str, port: int = 23, *, use_tls: bool = False,
                 timeout: float = 5.0, events: bool = True,
                 client: EdidioClient | None = None, event_stream: EventStream | None = None):
        self.name = name
        self.host = host
        self._client = client or EdidioClient(host, port, timeout=timeout, use_tls=use_tls)
        self._events = None
        if events:
            self._events = event_stream or EventStream(host, port, use_tls)
            self._events.on_event = self._on_event
        self._mid = 0
        self.up = 0
        self.info: dict = {}
        self.counts: dict = {}
        self.active_profile: int | None = None
        self.poll_seconds = 0.0
        self.polls_failed = 0
        self.levels = LevelTracker()
        self.event_counts: Counter = Counter()
        self.last_event_ts: float | None = None
        self.stream_up = 0

    def _next_id(self) -> int:
        self._mid = (self._mid + 1) & 0xFFFFFF
        return self._mid

    async def start(self) -> None:
        if self._events is None:
            return
        try:
            await self._events.start(["dali", "inputs", "sensors", "triggers"])
            self.stream_up = 1
        except EDIDIOConnectionError as err:
            _LOGGER.warning("[%s] event stream unavailable: %s", self.name, err)

    async def stop(self) -> None:
        if self._events is not None:
            await self._events.stop()
        await self._client.disconnect()

    async def _on_event(self, event: dict) -> None:
        self.stream_up = 1
        self.event_counts[event.get("kind", "unknown")] += 1
        self.last_event_ts = time.time()
        change = dali_change(event)
        if change is not None and not (change.level is None and change.command == "scene"):
            self.levels.apply(change)

    async def poll(self) -> None:
        """Read system info; sets ``up`` and the health fields."""
        started = time.monotonic()
        try:
            await self._client.connect()
            reply = await self._client.request(EdidioClient.create_diagnostic_message(
                self._next_id(), DiagnosticMessageType.DIAGNOSTIC_SYSTEM_INFO))
            which = reply.WhichOneof("payload")
            if which != "diag_system":
                raise EDIDIOConnectionError(f"unexpected reply: {which}")
            d = reply.diag_system
            self.info = {"firmware": d.firmware, "hardware": d.hardware,
                         "proto_version": d.proto_version, "vendor_id": d.vendor_id}
            self.counts = {kind: getattr(d, field) for field, kind in COUNT_FIELDS.items()}
            self.active_profile = d.selected_profile
            self.up = 1
        except (EDIDIOConnectionError, asyncio.TimeoutError, OSError) as err:
            _LOGGER.warning("[%s] poll failed: %s", self.name, err)
            self.up = 0
            self.polls_failed += 1
            await self._client.disconnect()
        finally:
            self.poll_seconds = time.monotonic() - started
        if self._events is not None:
            self.stream_up = int(self._events.connected)

    def families(self) -> list:
        c = {"controller": self.name}
        fams = [
            ("edidio_up", "gauge", "1 if the last health poll succeeded.", [(c, self.up)]),
            ("edidio_poll_duration_seconds", "gauge", "Duration of the last health poll.",
             [(c, self.poll_seconds)]),
            ("edidio_poll_failures_total", "counter", "Failed health polls.",
             [(c, self.polls_failed)]),
        ]
        if self.info:
            fams.append(("edidio_info", "gauge", "Controller identity (value is always 1).",
                         [({**c, **{k: str(v) for k, v in self.info.items()}}, 1)]))
        if self.active_profile is not None:
            fams.append(("edidio_active_profile", "gauge", "Currently selected profile index.",
                         [(c, self.active_profile)]))
        fams.append(("edidio_config_count", "gauge",
                     "Configured capacity reported by the controller, by kind.",
                     [({**c, "kind": k}, v) for k, v in sorted(self.counts.items())]))
        if self._events is not None:
            fams.append(("edidio_event_stream_up", "gauge",
                         "1 if the live event stream is connected.", [(c, self.stream_up)]))
            fams.append(("edidio_event_stream_reconnects_total", "counter",
                         "Event stream reconnects.", [(c, self._events.reconnects)]))
            fams.append(("edidio_events_total", "counter", "Events received, by kind.",
                         [({**c, "kind": k}, v) for k, v in sorted(self.event_counts.items())]))
            if self.last_event_ts is not None:
                fams.append(("edidio_last_event_timestamp_seconds", "gauge",
                             "Unix time of the last event received.", [(c, self.last_event_ts)]))
            levels = []
            for (line, address), level in sorted(self.levels.snapshot().items()):
                if level is None:
                    continue
                labels = {**c, "line": line, "target": _target(address),
                          "address": address - 64 if 64 <= address < 80 else address}
                levels.append((labels, level))
            fams.append(("edidio_dali_level", "gauge",
                         "Last DALI arc level (0-254) seen on the bus. address is the "
                         "short address, or the group number when target=group.", levels))
        return fams
