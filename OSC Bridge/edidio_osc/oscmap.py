"""OSC address map: validates config and turns an OSC message into an eDIDIO
*intent*.

Pure (no python-osc / network dependency) so it is unit testable in isolation.
The bridge maps each OSC address to a target and calls ``.intent(args)``.

Value handling for level actions (OSC faders usually send a float 0.0-1.0):
  * float  -> treated as normalized 0.0-1.0  -> arc level 0-254
  * int    -> treated as a raw arc level 0-254
Scene / Spektra targets fire on a "trigger" (no args, or first arg > 0), so a
button's press (1) fires and its release (0) does not.
"""

from __future__ import annotations

DALI_ARC_LEVEL_MAX = 254

_ACTIONS = {"dali_level", "dali_group_level", "dali_scene", "spektra", "spektra_stop"}


class ConfigError(ValueError):
    """Raised when an OSC address map entry is invalid."""


def _require_int(cfg, key, lo, hi, *, required=True, default=None):
    if key not in cfg or cfg[key] is None:
        if required:
            raise ConfigError(f"address '{cfg.get('address')}': missing '{key}'")
        return default
    val = cfg[key]
    if not isinstance(val, int) or isinstance(val, bool):
        raise ConfigError(f"address '{cfg.get('address')}': '{key}' must be an integer")
    if not (lo <= val <= hi):
        raise ConfigError(f"address '{cfg.get('address')}': '{key}'={val} out of range {lo}-{hi}")
    return val


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def level_from_arg(arg) -> int:
    """Interpret an OSC argument as a DALI arc level (0-254)."""
    if isinstance(arg, bool):
        return DALI_ARC_LEVEL_MAX if arg else 0
    if isinstance(arg, float):
        return round(_clamp(arg, 0.0, 1.0) * DALI_ARC_LEVEL_MAX)
    if isinstance(arg, int):
        return _clamp(arg, 0, DALI_ARC_LEVEL_MAX)
    try:
        return _clamp(int(float(arg)), 0, DALI_ARC_LEVEL_MAX)
    except (TypeError, ValueError):
        return 0


def is_trigger(args) -> bool:
    """True if an OSC message should fire a trigger action (scene/Spektra)."""
    if not args:
        return True
    a = args[0]
    if isinstance(a, bool):
        return a
    if isinstance(a, (int, float)):
        return a > 0
    return True  # any non-empty non-numeric arg (e.g. a bang string)


class OSCTarget:
    def __init__(self, cfg: dict):
        self.address = cfg.get("address")
        if not self.address or not str(self.address).startswith("/"):
            raise ConfigError(f"invalid or missing OSC 'address': {self.address!r} (must start with '/')")
        self.name = cfg.get("name", self.address)
        self.action = cfg.get("action")
        if self.action not in _ACTIONS:
            raise ConfigError(
                f"address '{self.address}': unknown action '{self.action}'. Known: {', '.join(sorted(_ACTIONS))}"
            )

        if self.action == "dali_level":
            self.line = _require_int(cfg, "line", 1, 4)
            self.dali_address = _require_int(cfg, "address_dali", 0, 63)
        elif self.action == "dali_group_level":
            self.line = _require_int(cfg, "line", 1, 4)
            self.group = _require_int(cfg, "group", 0, 15)
        elif self.action == "dali_scene":
            self.line = _require_int(cfg, "line", 1, 4)
            self.scene = _require_int(cfg, "scene", 0, 15)
            self.group = _require_int(cfg, "group", 0, 15, required=False, default=None)
        elif self.action == "spektra":
            self.zone = _require_int(cfg, "zone", 0, 255)
            self.type = str(cfg.get("type", "sequence")).upper()
            if self.type not in ("SEQUENCE", "THEME", "STATIC"):
                raise ConfigError(f"address '{self.address}': invalid spektra type '{cfg.get('type')}'")
            self.index = _require_int(cfg, "index", 0, 65535, required=False, default=0)
            self.spektra_action = str(cfg.get("spektra_action", "start")).upper()
            if self.spektra_action not in ("START", "STOP", "PAUSE"):
                raise ConfigError(f"address '{self.address}': invalid spektra_action '{cfg.get('spektra_action')}'")
        elif self.action == "spektra_stop":
            self.zone = _require_int(cfg, "zone", 0, 255)

    def intent(self, args):
        """Translate an OSC message (tuple of args) to an intent, or None."""
        a = self.action
        if a == "dali_level":
            level = level_from_arg(args[0]) if args else 0
            return {"kind": "dali_level", "line": self.line, "address": self.dali_address, "level": level}
        if a == "dali_group_level":
            level = level_from_arg(args[0]) if args else 0
            return {"kind": "dali_group_level", "line": self.line, "group": self.group, "level": level}
        if a == "dali_scene":
            if not is_trigger(args):
                return None
            intent = {"kind": "dali_scene", "line": self.line, "scene": self.scene}
            if self.group is not None:
                intent["group"] = self.group
            return intent
        if a == "spektra":
            if not is_trigger(args):
                return None
            return {
                "kind": "spektra", "type": self.type, "zone": self.zone,
                "index": self.index, "action": self.spektra_action,
            }
        if a == "spektra_stop":
            if not is_trigger(args):
                return None
            return {"kind": "spektra_stop", "zone": self.zone}
        return None


def build_address_map(entries: list) -> dict:
    """Build a {osc_address: OSCTarget} map, rejecting duplicates."""
    if not entries:
        raise ConfigError("config has no addresses defined")
    result = {}
    for cfg in entries:
        target = OSCTarget(cfg)
        if target.address in result:
            raise ConfigError(f"duplicate OSC address {target.address}")
        result[target.address] = target
    return result
