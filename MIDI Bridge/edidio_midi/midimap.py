"""MIDI map: validates config and turns a MIDI event into an eDIDIO *intent*.

Pure (no mido / network dependency) so it is unit testable. The bridge decodes an
incoming mido message to a simple key and value and calls ``.intent(value)``.

Event keys (channel is 0-15):
  "note:<channel>:<note>"   note_on (velocity>0) fires; note_off / velocity 0 optional
  "cc:<channel>:<control>"  control_change; value 0-127
  "pc:<channel>:<program>"  program_change (trigger)

Value handling for level actions:
  * note velocity 0-127  -> scaled to arc 0-254
  * CC value 0-127       -> scaled to arc 0-254 (typical fader)
Scenes / Spektra fire on a trigger (note_on velocity>0, CC value>0, or PC).
"""

from __future__ import annotations

DALI_ARC_LEVEL_MAX = 254

_ACTIONS = {"dali_level", "dali_group_level", "dali_scene", "spektra", "spektra_stop"}


class ConfigError(ValueError):
    """Raised when a MIDI map entry is invalid."""


def _require_int(cfg, key, lo, hi, *, required=True, default=None):
    if key not in cfg or cfg[key] is None:
        if required:
            raise ConfigError(f"binding '{cfg.get('event')}': missing '{key}'")
        return default
    val = cfg[key]
    if not isinstance(val, int) or isinstance(val, bool):
        raise ConfigError(f"binding '{cfg.get('event')}': '{key}' must be an integer")
    if not (lo <= val <= hi):
        raise ConfigError(f"binding '{cfg.get('event')}': '{key}'={val} out of range {lo}-{hi}")
    return val


def midi_to_arc(value: int) -> int:
    """MIDI 0-127 -> DALI arc level 0-254."""
    value = max(0, min(127, int(value)))
    return round(value * DALI_ARC_LEVEL_MAX / 127)


def event_key(msg_type: str, channel: int, number: int) -> str:
    """Build the map key for a decoded MIDI message."""
    if msg_type in ("note_on", "note_off"):
        return f"note:{channel}:{number}"
    if msg_type == "control_change":
        return f"cc:{channel}:{number}"
    if msg_type == "program_change":
        return f"pc:{channel}:{number}"
    return ""


class Binding:
    def __init__(self, cfg: dict):
        self.event = cfg.get("event")
        if not self.event or not isinstance(self.event, str):
            raise ConfigError(f"binding is missing 'event' key: {cfg}")
        parts = self.event.split(":")
        if len(parts) != 3 or parts[0] not in ("note", "cc", "pc"):
            raise ConfigError(f"invalid event '{self.event}' (expected note:ch:n / cc:ch:n / pc:ch:n)")
        self.kind = parts[0]
        self.name = cfg.get("name", self.event)
        self.action = cfg.get("action")
        if self.action not in _ACTIONS:
            raise ConfigError(f"binding '{self.event}': unknown action '{self.action}'. Known: {', '.join(sorted(_ACTIONS))}")

        if self.action == "dali_level":
            self.line = _require_int(cfg, "line", 1, 4)
            self.address = _require_int(cfg, "address", 0, 63)
        elif self.action == "dali_group_level":
            self.line = _require_int(cfg, "line", 1, 4)
            self.group = _require_int(cfg, "group", 0, 15)
        elif self.action == "dali_scene":
            self.line = _require_int(cfg, "line", 1, 4)
            self.scene = _require_int(cfg, "scene", 0, 15)
            self.group = _require_int(cfg, "group", 0, 15, required=False, default=None)
        elif self.action == "spektra":
            self.zone = _require_int(cfg, "zone", 0, 255)
            self.index = _require_int(cfg, "index", 0, 65535, required=False, default=0)
        elif self.action == "spektra_stop":
            self.zone = _require_int(cfg, "zone", 0, 255)

    def intent(self, value: int):
        """Translate a MIDI value (velocity / CC value / program) to an intent.

        For level actions the value maps to brightness. For trigger actions a
        value of 0 (note-off / fader-zero) is ignored so a button release doesn't
        re-fire. Returns None when nothing should happen.
        """
        a = self.action
        if a in ("dali_level", "dali_group_level"):
            level = midi_to_arc(value)
            if a == "dali_level":
                return {"kind": "dali_level", "line": self.line, "address": self.address, "level": level}
            return {"kind": "dali_group_level", "line": self.line, "group": self.group, "level": level}

        # Trigger actions: ignore zero (note-off / release).
        if value <= 0:
            return None
        if a == "dali_scene":
            intent = {"kind": "dali_scene", "line": self.line, "scene": self.scene}
            if self.group is not None:
                intent["group"] = self.group
            return intent
        if a == "spektra":
            return {"kind": "spektra", "type": "SEQUENCE", "zone": self.zone, "index": self.index, "action": "START"}
        if a == "spektra_stop":
            return {"kind": "spektra_stop", "zone": self.zone}
        return None


def build_midi_map(entries: list) -> dict:
    """Build a {event_key: Binding} map, rejecting duplicates."""
    if not entries:
        raise ConfigError("config has no bindings defined")
    result = {}
    for cfg in entries:
        binding = Binding(cfg)
        if binding.event in result:
            raise ConfigError(f"duplicate binding for {binding.event}")
        result[binding.event] = binding
    return result
