"""eDIDIO Raspberry Pi GPIO bridge.

Wire buttons, switches and motion sensors to GPIO pins and drive eDIDIO lighting
— a physical wall panel or occupancy trigger with a Pi and the shared
``edidio_control_py`` engine.

The pin→action map is pure and unit tested. The GPIO layer uses ``gpiozero`` but
is injectable, so the logic runs and is tested without a Pi.
"""

from __future__ import annotations

import asyncio
import logging

from edidio_control_py import (
    DALICommandType,
    EdidioClient,
    SpektraActionType,
    SpektraTargetType,
)

_LOGGER = logging.getLogger(__name__)

DALI_ARC_LEVEL_MAX = 254


def line_mask(line: int) -> int:
    return 1 << (line - 1)


class ConfigError(ValueError):
    pass


def _require_int(cfg, key, lo, hi, *, required=True, default=None):
    if key not in cfg or cfg[key] is None:
        if required:
            raise ConfigError(f"pin {cfg.get('pin')}: missing '{key}'")
        return default
    val = cfg[key]
    if not isinstance(val, int) or isinstance(val, bool):
        raise ConfigError(f"pin {cfg.get('pin')}: '{key}' must be an integer")
    if not (lo <= val <= hi):
        raise ConfigError(f"pin {cfg.get('pin')}: '{key}'={val} out of range {lo}-{hi}")
    return val


_ACTIONS = {"scene", "on", "off", "group_level", "spektra"}


class PinBinding:
    """One GPIO pin -> action, fired when the input activates (button press)."""

    def __init__(self, cfg: dict):
        self.pin = _require_int(cfg, "pin", 0, 40)
        self.name = cfg.get("name", f"GPIO {self.pin}")
        self.pull_up = bool(cfg.get("pull_up", True))
        self.action = cfg.get("action")
        if self.action not in _ACTIONS:
            raise ConfigError(f"pin {self.pin}: unknown action '{self.action}'. Known: {', '.join(sorted(_ACTIONS))}")
        if self.action == "scene":
            self.line = _require_int(cfg, "line", 1, 4)
            self.scene = _require_int(cfg, "scene", 0, 15)
        elif self.action in ("on", "off"):
            self.line = _require_int(cfg, "line", 1, 4)
            self.address = _require_int(cfg, "address", 0, 63)
        elif self.action == "group_level":
            self.line = _require_int(cfg, "line", 1, 4)
            self.group = _require_int(cfg, "group", 0, 15)
            self.level = _require_int(cfg, "level", 0, 254)
        elif self.action == "spektra":
            self.zone = _require_int(cfg, "zone", 0, 255)
            self.index = _require_int(cfg, "index", 0, 65535, required=False, default=0)

    def intent(self) -> dict:
        a = self.action
        if a == "scene":
            return {"kind": "dali_scene", "line": self.line, "scene": self.scene}
        if a == "on":
            return {"kind": "dali_command", "line": self.line, "address": self.address, "command": "on"}
        if a == "off":
            return {"kind": "dali_command", "line": self.line, "address": self.address, "command": "off"}
        if a == "group_level":
            return {"kind": "dali_group_level", "line": self.line, "group": self.group, "level": self.level}
        if a == "spektra":
            return {"kind": "spektra", "type": "SEQUENCE", "zone": self.zone, "index": self.index, "action": "START"}
        raise ConfigError(f"unhandled action {a}")


def build_pin_map(entries: list) -> dict:
    if not entries:
        raise ConfigError("config has no pins defined")
    result = {}
    for cfg in entries:
        b = PinBinding(cfg)
        if b.pin in result:
            raise ConfigError(f"duplicate pin {b.pin}")
        result[b.pin] = b
    return result


# --- controller wrapper (async) -------------------------------------------

_NAMED = {"on": DALICommandType.DALI_MAX_LEVEL, "off": DALICommandType.DALI_OFF}
_SPEKTRA_TARGET = {"SEQUENCE": SpektraTargetType.SEQUENCE, "THEME": SpektraTargetType.THEME, "STATIC": SpektraTargetType.STATIC}
_SPEKTRA_ACTION = {"START": SpektraActionType.START, "STOP": SpektraActionType.STOP, "PAUSE": SpektraActionType.PAUSE}


class Controller:
    def __init__(self, host, port=23, *, use_tls=False, client=None):
        self._client = client or EdidioClient(host, port, use_tls=use_tls)
        self._mid = 0

    def _next(self):
        self._mid = (self._mid + 1) & 0xFFFFFF
        return self._mid

    async def connect(self):
        await self._client.connect()

    async def disconnect(self):
        await self._client.disconnect()

    async def execute(self, intent: dict):
        k = intent["kind"]
        mid = self._next()
        if k == "dali_scene":
            await self._client.recall_dali_scene(mid, line_mask(intent["line"]), intent["scene"])
        elif k == "dali_command":
            await self._client.send_dali_command(mid, line_mask(intent["line"]), intent["address"], _NAMED[intent["command"]])
        elif k == "dali_group_level":
            await self._client.set_dali_group_arc_level(mid, line_mask(intent["line"]), intent["group"], intent["level"])
        elif k == "spektra":
            await self._client.send_spektra_control(mid, _SPEKTRA_TARGET[intent["type"]], intent["zone"], intent["index"], _SPEKTRA_ACTION[intent["action"]])
        else:
            _LOGGER.error("unknown intent %s", intent)
