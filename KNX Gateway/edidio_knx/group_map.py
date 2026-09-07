"""KNX group-address map: validates config entries and turns a decoded KNX
telegram value into a normalized eDIDIO *intent*.

Pure (no xknx / network dependency) so it can be unit tested in isolation. The
bridge decodes the raw telegram value and calls ``GroupTarget.intent(value)``.

Value normalization the bridge passes in:
  * DPT switch (1.001)        -> 0 or 1
  * DPT scaling (5.001)       -> a byte 0-255 (0-100%)
  * DPT scene number (17.001) -> a byte (scene index)

Intents use the shared vocabulary:
  {"kind": "dali_level", "line", "address", "level"}
  {"kind": "dali_group_level", "line", "group", "level"}
  {"kind": "dali_scene", "line", "scene" [, "group"]}
"""

from __future__ import annotations

DALI_ARC_LEVEL_MAX = 254

# action -> the DPTs that make sense for it.
_VALID_DPT = {
    "dali_level": {"switch", "scaling"},
    "dali_group_level": {"switch", "scaling"},
    "dali_scene": {"switch", "scene_number"},
}

class ConfigError(ValueError):
    """Raised when a group-address map entry is invalid."""


def _valid_ga(ga) -> bool:
    """A 3-level KNX group address: main 0-31 / middle 0-7 / sub 0-255."""
    parts = str(ga).split("/")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return False
    main, middle, sub = (int(p) for p in parts)
    return 0 <= main <= 31 and 0 <= middle <= 7 and 0 <= sub <= 255


def _require_int(cfg, key, lo, hi, *, required=True, default=None):
    if key not in cfg or cfg[key] is None:
        if required:
            raise ConfigError(f"GA '{cfg.get('ga')}': missing '{key}'")
        return default
    val = cfg[key]
    if not isinstance(val, int) or isinstance(val, bool):
        raise ConfigError(f"GA '{cfg.get('ga')}': '{key}' must be an integer")
    if not (lo <= val <= hi):
        raise ConfigError(f"GA '{cfg.get('ga')}': '{key}'={val} out of range {lo}-{hi}")
    return val


def _scaling_to_arc(value: int) -> int:
    """DPT 5.001 raw byte (0-255) -> DALI arc level (0-254)."""
    value = max(0, min(255, int(value)))
    return round(value * DALI_ARC_LEVEL_MAX / 255)


class GroupTarget:
    """One validated KNX group address -> eDIDIO action mapping."""

    def __init__(self, cfg: dict):
        self.ga = cfg.get("ga")
        if not self.ga or not _valid_ga(self.ga):
            raise ConfigError(
                f"invalid or missing group address 'ga': {self.ga!r} "
                f"(expected main/mid/sub, ranges 0-31 / 0-7 / 0-255)"
            )
        self.name = cfg.get("name", self.ga)
        self.action = cfg.get("action")
        if self.action not in _VALID_DPT:
            raise ConfigError(f"GA '{self.ga}': unknown action '{self.action}'. Known: {', '.join(sorted(_VALID_DPT))}")
        self.dpt = cfg.get("dpt")
        if self.dpt not in _VALID_DPT[self.action]:
            raise ConfigError(
                f"GA '{self.ga}': dpt '{self.dpt}' not valid for action '{self.action}'. "
                f"Use one of: {', '.join(sorted(_VALID_DPT[self.action]))}"
            )
        self.line = _require_int(cfg, "line", 1, 4)

        if self.action == "dali_level":
            self.dali_address = _require_int(cfg, "dali_address", 0, 63)
        elif self.action == "dali_group_level":
            self.group = _require_int(cfg, "group", 0, 15)
        elif self.action == "dali_scene":
            self.group = _require_int(cfg, "group", 0, 15, required=False, default=None)
            if self.dpt == "switch":
                # A switch-triggered scene needs a fixed scene number to recall.
                self.scene = _require_int(cfg, "scene", 0, 15)
            else:
                self.scene = None  # scene number comes from the telegram

    def intent(self, value: int):
        """Translate a decoded telegram value into an intent, or None (ignored)."""
        if self.action in ("dali_level", "dali_group_level"):
            if self.dpt == "scaling":
                level = _scaling_to_arc(value)
            else:  # switch
                level = DALI_ARC_LEVEL_MAX if value else 0
            if self.action == "dali_level":
                return {"kind": "dali_level", "line": self.line, "address": self.dali_address, "level": level}
            return {"kind": "dali_group_level", "line": self.line, "group": self.group, "level": level}

        if self.action == "dali_scene":
            if self.dpt == "switch":
                if not value:
                    return None  # ignore "off" on a scene-trigger GA
                scene = self.scene
            else:  # scene_number
                scene = int(value)
                if not (0 <= scene <= 15):
                    return None  # out of eDIDIO scene range; ignore
            intent = {"kind": "dali_scene", "line": self.line, "scene": scene}
            if self.group is not None:
                intent["group"] = self.group
            return intent

        return None


def build_group_map(entries: list) -> dict:
    """Build a {group_address_str: GroupTarget} map, rejecting duplicates."""
    if not entries:
        raise ConfigError("config has no group_addresses defined")
    result = {}
    for cfg in entries:
        target = GroupTarget(cfg)
        if target.ga in result:
            raise ConfigError(f"duplicate group address {target.ga}")
        result[target.ga] = target
    return result
