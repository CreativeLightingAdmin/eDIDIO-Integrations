"""Async command dispatcher.

Owns a persistent ``EdidioClient`` (keep-alive + auto-reconnect handled by the
library) and drains a queue of normalized intents, translating each into the
matching high-level ``edidio_control_py`` call. A background worker decouples the
MQTT network-thread callbacks from the async controller I/O.

(Mirrors the Modbus gateway's dispatcher — same intent vocabulary.)
"""

from __future__ import annotations

import asyncio
import logging

from edidio_control_py import EdidioClient, SpektraActionType, SpektraTargetType
from edidio_control_py.exceptions import EDIDIOConnectionError

_LOGGER = logging.getLogger(__name__)


def line_mask(line: int) -> int:
    return 1 << (line - 1)


_SPEKTRA_TARGET = {
    "SEQUENCE": SpektraTargetType.SEQUENCE,
    "THEME": SpektraTargetType.THEME,
    "STATIC": SpektraTargetType.STATIC,
}
_SPEKTRA_ACTION = {
    "START": SpektraActionType.START,
    "STOP": SpektraActionType.STOP,
    "PAUSE": SpektraActionType.PAUSE,
}


class EdidioDispatcher:
    def __init__(self, host, port, *, use_tls=False, timeout=5.0):
        self._client = EdidioClient(host, port, timeout=timeout, use_tls=use_tls)
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker = None
        self._message_id = 0
        self._loop = None

    async def start(self):
        self._loop = asyncio.get_running_loop()
        try:
            await self._client.connect()
        except EDIDIOConnectionError as err:
            _LOGGER.warning("Initial controller connect failed (will retry on demand): %s", err)
        self._worker = asyncio.create_task(self._run(), name="edidio-dispatcher")

    async def stop(self):
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None
        await self._client.disconnect()

    def submit(self, intent: dict) -> None:
        """Enqueue an intent from any thread (safe from the MQTT callback thread)."""
        if self._loop is None:
            _LOGGER.error("Dispatcher not started; dropping intent %s", intent)
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, intent)

    def _next_id(self):
        self._message_id = (self._message_id + 1) & 0xFFFFFF
        return self._message_id

    async def _run(self):
        _LOGGER.info("Dispatcher worker started")
        while True:
            intent = await self._queue.get()
            try:
                await self._execute(intent)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Failed to execute intent %s: %s", intent, err)
            finally:
                self._queue.task_done()

    async def _execute(self, intent: dict):
        kind = intent.get("kind")
        mid = self._next_id()

        if kind == "dali_level":
            await self._client.set_dali_arc_level(mid, line_mask(intent["line"]), intent["address"], intent["level"])
        elif kind == "dali_group_level":
            await self._client.set_dali_group_arc_level(mid, line_mask(intent["line"]), intent["group"], intent["level"])
        elif kind == "dali_scene":
            if intent.get("group") is None:
                await self._client.recall_dali_scene(mid, line_mask(intent["line"]), intent["scene"])
            else:
                await self._client.recall_dali_scene_on_group(mid, line_mask(intent["line"]), intent["group"], intent["scene"])
        elif kind == "dali_command":
            await self._client.send_dali_command(mid, line_mask(intent["line"]), intent["address"], intent["command"])
        elif kind == "spektra":
            # type/action are matched case-insensitively (config uses lowercase).
            await self._client.send_spektra_control(
                mid, _SPEKTRA_TARGET[str(intent["type"]).upper()], intent["zone"],
                intent["index"], _SPEKTRA_ACTION[str(intent["action"]).upper()]
            )
        elif kind == "spektra_stop":
            await self._client.send_spektra_stop(mid, intent["zone"])
        elif kind == "dmx_color":
            # Paint an RGB colour across a DMX line: send a compact frame (one RGB
            # triplet + a repeat count) that the controller expands across the whole
            # universe, instead of an explicit per-channel level list.
            rgb = list(intent["rgb"])
            fixtures = intent.get("fixtures") or (512 // len(rgb))
            frame = EdidioClient.create_dmx_message(mid, 0xFF, line_mask(intent["line"]), 1, fixtures, rgb)
            await self._client.send_protobuf_message(frame)
        else:
            _LOGGER.error("Unknown intent kind: %s", kind)
            return

        _LOGGER.info("Dispatched %s", intent)
