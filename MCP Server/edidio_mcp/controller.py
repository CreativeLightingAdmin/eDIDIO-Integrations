"""Thin async wrapper over ``edidio_control_py`` for the MCP tools.

Turns high-level intents (set level, recall scene, Spektra…) into
``EdidioClient`` calls, assigning rolling message ids. A ``client`` can be
injected for testing, so the wrapper is verifiable without a controller.
"""

from __future__ import annotations

from edidio_control_py import (
    DALICommandType,
    EdidioClient,
    SpektraActionType,
    SpektraTargetType,
)

_SPEKTRA_TARGET = {
    "sequence": SpektraTargetType.SEQUENCE,
    "theme": SpektraTargetType.THEME,
    "static": SpektraTargetType.STATIC,
}
_SPEKTRA_ACTION = {
    "start": SpektraActionType.START,
    "stop": SpektraActionType.STOP,
    "pause": SpektraActionType.PAUSE,
}

DALI_ARC_LEVEL_MAX = 254


def line_mask(line: int) -> int:
    """1-based physical line (1-4) -> single-bit line mask."""
    return 1 << (line - 1)


def _clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


def _parse_hex(value: str):
    text = str(value).lstrip("#").strip()
    if len(text) != 6:
        raise ValueError("colour must be #RRGGBB")
    return [int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)]


class EdidioController:
    def __init__(self, host, port=23, *, use_tls=False, timeout=5.0, client=None):
        self._client = client or EdidioClient(host, port, timeout=timeout, use_tls=use_tls)
        self.host = host
        self.port = port
        self._mid = 0

    def _next_id(self) -> int:
        self._mid = (self._mid + 1) & 0xFFFFFF
        return self._mid

    @property
    def connected(self) -> bool:
        return self._client.connected

    async def connect(self):
        await self._client.connect()

    async def disconnect(self):
        await self._client.disconnect()

    # --- control ---
    async def set_level(self, line, address, level):
        await self._client.set_dali_arc_level(
            self._next_id(), line_mask(line), address, _clamp(level, 0, DALI_ARC_LEVEL_MAX)
        )

    async def set_group_level(self, line, group, level):
        await self._client.set_dali_group_arc_level(
            self._next_id(), line_mask(line), group, _clamp(level, 0, DALI_ARC_LEVEL_MAX)
        )

    async def turn_on(self, line, address):
        await self._client.send_dali_command(
            self._next_id(), line_mask(line), address, DALICommandType.DALI_MAX_LEVEL
        )

    async def turn_off(self, line, address):
        await self._client.send_dali_command(
            self._next_id(), line_mask(line), address, DALICommandType.DALI_OFF
        )

    async def recall_scene(self, line, scene, group=None):
        if group is None:
            await self._client.recall_dali_scene(self._next_id(), line_mask(line), scene)
        else:
            await self._client.recall_dali_scene_on_group(
                self._next_id(), line_mask(line), group, scene
            )

    async def dmx_color(self, line, hex, fixtures=None):
        rgb = _parse_hex(hex)
        if fixtures is None:
            fixtures = 512 // len(rgb)
        # Send a compact frame (one RGB triplet + a repeat count) that the
        # controller expands across the whole universe, instead of an explicit
        # per-channel level list.
        frame = EdidioClient.create_dmx_message(self._next_id(), 0xFF, line_mask(line), 1, fixtures, rgb)
        await self._client.send_protobuf_message(frame)

    async def spektra(self, zone, target="sequence", index=0, action="start"):
        t = _SPEKTRA_TARGET.get(str(target).lower())
        a = _SPEKTRA_ACTION.get(str(action).lower())
        if t is None:
            raise ValueError(f"unknown Spektra target: {target}")
        if a is None:
            raise ValueError(f"unknown Spektra action: {action}")
        await self._client.send_spektra_control(self._next_id(), t, zone, index, a)

    async def spektra_stop(self, zone):
        await self._client.send_spektra_stop(self._next_id(), zone)
