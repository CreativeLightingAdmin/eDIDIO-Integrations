"""Register map: validates config entries and turns a written register value
into a normalized eDIDIO *intent* dict.

Kept deliberately free of any network/protobuf dependency so it can be unit
tested in isolation. The dispatcher consumes the intents produced here.
"""

from __future__ import annotations

DALI_ARC_LEVEL_MAX = 254

# action -> set of allowed config keys (besides register/name/action).
_ACTION_FIELDS = {
    "dali_level": {"line", "address"},
    "dali_group_level": {"line", "group"},
    "dali_onoff": {"line", "address"},
    "dali_group_onoff": {"line", "group"},
    "dali_scene": {"line", "group"},  # group optional
    "dali_command": {"line", "address"},
    "spektra_sequence": {"zone"},
    "spektra_theme": {"zone"},
    "spektra_static": {"zone"},
}

_SPEKTRA_TYPE = {
    "spektra_sequence": "SEQUENCE",
    "spektra_theme": "THEME",
    "spektra_static": "STATIC",
}


class ConfigError(ValueError):
    """Raised when a register map entry is invalid."""


def line_mask(line: int) -> int:
    """1-based physical line number (1-4) -> single-bit line mask."""
    return 1 << (line - 1)


def _require(entry: dict, key: str, *, lo: int, hi: int) -> int:
    if key not in entry or entry[key] is None:
        raise ConfigError(f"register {entry.get('register')}: missing '{key}'")
    val = entry[key]
    if not isinstance(val, int) or isinstance(val, bool):
        raise ConfigError(f"register {entry.get('register')}: '{key}' must be an integer")
    if not (lo <= val <= hi):
        raise ConfigError(
            f"register {entry.get('register')}: '{key}'={val} out of range {lo}-{hi}"
        )
    return val


class RegisterEntry:
    """One validated register->action mapping."""

    def __init__(self, entry: dict):
        self.register = _require(entry, "register", lo=1, hi=65535)
        self.name = entry.get("name", f"register {self.register}")
        self.action = entry.get("action")
        if self.action not in _ACTION_FIELDS:
            raise ConfigError(
                f"register {self.register}: unknown action '{self.action}'. "
                f"Known: {', '.join(sorted(_ACTION_FIELDS))}"
            )

        # Validate the fields this action needs.
        if self.action in ("dali_level", "dali_onoff", "dali_command"):
            self.line = _require(entry, "line", lo=1, hi=4)
            self.address = _require(entry, "address", lo=0, hi=63)
        elif self.action in ("dali_group_level", "dali_group_onoff"):
            self.line = _require(entry, "line", lo=1, hi=4)
            self.group = _require(entry, "group", lo=0, hi=15)
        elif self.action == "dali_scene":
            self.line = _require(entry, "line", lo=1, hi=4)
            self.group = (
                _require(entry, "group", lo=0, hi=15) if entry.get("group") is not None else None
            )
        elif self.action in _SPEKTRA_TYPE:
            self.zone = _require(entry, "zone", lo=0, hi=255)

    def intent(self, value: int) -> dict | None:
        """Translate a written register `value` into an eDIDIO intent, or None
        when the value is out of range / a no-op (logged by the caller)."""
        a = self.action

        if a in ("dali_level", "dali_group_level"):
            level = _clamp(value, 0, DALI_ARC_LEVEL_MAX)
            if a == "dali_level":
                return {"kind": "dali_level", "line": self.line, "address": self.address, "level": level}
            return {"kind": "dali_group_level", "line": self.line, "group": self.group, "level": level}

        if a in ("dali_onoff", "dali_group_onoff"):
            level = DALI_ARC_LEVEL_MAX if value > 0 else 0
            if a == "dali_onoff":
                return {"kind": "dali_level", "line": self.line, "address": self.address, "level": level}
            return {"kind": "dali_group_level", "line": self.line, "group": self.group, "level": level}

        if a == "dali_scene":
            if not (0 <= value <= 15):
                return None
            intent = {"kind": "dali_scene", "line": self.line, "scene": value}
            if self.group is not None:
                intent["group"] = self.group
            return intent

        if a == "dali_command":
            if not (0 <= value <= 255):
                return None
            return {"kind": "dali_command", "line": self.line, "address": self.address, "command": value}

        if a in _SPEKTRA_TYPE:
            if value <= 0:
                return {"kind": "spektra_stop", "zone": self.zone}
            return {
                "kind": "spektra",
                "type": _SPEKTRA_TYPE[a],
                "zone": self.zone,
                "index": value - 1,
                "action": "START",
            }

        return None  # unreachable given constructor validation


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def build_register_map(entries: list[dict]) -> dict[int, RegisterEntry]:
    """Build a {register_number: RegisterEntry} map, rejecting duplicates."""
    if not entries:
        raise ConfigError("config has no registers defined")
    result: dict[int, RegisterEntry] = {}
    for raw in entries:
        item = RegisterEntry(raw)
        if item.register in result:
            raise ConfigError(f"duplicate register number {item.register}")
        result[item.register] = item
    return result
