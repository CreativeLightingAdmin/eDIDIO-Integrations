"""Async command dispatcher.

Owns a persistent ``EdidioClient`` (keep-alive + auto-reconnect handled by the
library) and drains a queue of normalized intents, translating each into the
matching high-level ``edidio_control_py`` call. A background worker decouples the
synchronous Modbus write callback from the async network I/O.
"""

from __future__ import annotations

import asyncio
import logging

from edidio_control_py import (
    EdidioClient,
    SpektraActionType,
    SpektraTargetType,
)
from edidio_control_py.exceptions import EDIDIOConnectionError

from .registers import line_mask

_LOGGER = logging.getLogger(__name__)

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
    """Queues eDIDIO intents and executes them against a controller."""

    def __init__(self, host: str, port: int, *, use_tls: bool = False, timeout: float = 5.0):
        self._client = EdidioClient(host, port, timeout=timeout, use_tls=use_tls)
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._message_id = 0
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        """Connect (best-effort) and start the worker task."""
        self._loop = asyncio.get_running_loop()
        try:
            await self._client.connect()
        except EDIDIOConnectionError as err:
            # Non-fatal: the library reconnects on the next send.
            _LOGGER.warning("Initial controller connect failed (will retry on demand): %s", err)
        self._worker = asyncio.create_task(self._run(), name="edidio-dispatcher")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None
        await self._client.disconnect()

    def submit(self, intent: dict) -> None:
        """Enqueue an intent from any thread (safe from the Modbus callback)."""
        if self._loop is None:
            _LOGGER.error("Dispatcher not started; dropping intent %s", intent)
            return
        # call_soon_threadsafe covers the RTU case where pymodbus may call back
        # from a serial thread; for TCP it's the same loop and still correct.
        self._loop.call_soon_threadsafe(self._queue.put_nowait, intent)

    def _next_id(self) -> int:
        self._message_id = (self._message_id + 1) & 0xFFFFFF
        return self._message_id

    async def _run(self) -> None:
        _LOGGER.info("Dispatcher worker started")
        while True:
            intent = await self._queue.get()
            try:
                await self._execute(intent)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - never let one bad command kill the worker
                _LOGGER.error("Failed to execute intent %s: %s", intent, err)
            finally:
                self._queue.task_done()

    async def _execute(self, intent: dict) -> None:
        kind = intent.get("kind")
        mid = self._next_id()

        if kind == "dali_level":
            await self._client.set_dali_arc_level(
                mid, line_mask(intent["line"]), intent["address"], intent["level"]
            )
        elif kind == "dali_group_level":
            await self._client.set_dali_group_arc_level(
                mid, line_mask(intent["line"]), intent["group"], intent["level"]
            )
        elif kind == "dali_scene":
            if intent.get("group") is None:
                await self._client.recall_dali_scene(mid, line_mask(intent["line"]), intent["scene"])
            else:
                await self._client.recall_dali_scene_on_group(
                    mid, line_mask(intent["line"]), intent["group"], intent["scene"]
                )
        elif kind == "dali_command":
            await self._client.send_dali_command(
                mid, line_mask(intent["line"]), intent["address"], intent["command"]
            )
        elif kind == "spektra":
            await self._client.send_spektra_control(
                mid,
                _SPEKTRA_TARGET[intent["type"]],
                intent["zone"],
                intent["index"],
                _SPEKTRA_ACTION[intent["action"]],
            )
        elif kind == "spektra_stop":
            await self._client.send_spektra_stop(mid, intent["zone"])
        else:
            _LOGGER.error("Unknown intent kind: %s", kind)
            return

        _LOGGER.info("Dispatched %s", intent)
