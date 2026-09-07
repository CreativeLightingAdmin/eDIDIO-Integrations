"""Accessory specs: validate config and produce eDIDIO intents.

Pure (no HAP / network / protobuf dependency) so it is unit testable in
isolation. Accessories in ``accessories.py`` hold a spec and call these to turn
HomeKit characteristic changes into eDIDIO intents.

Intents use the shared vocabulary:
  {"kind": "dali_level", "line", "address", "level"}
  {"kind": "dali_group_level", "line", "group", "level"}
  {"kind": "dali_scene", "line", "scene" [, "group"]}
"""

from __future__ import annotations

DALI_ARC_LEVEL_MAX = 254


class ConfigError(ValueError):
    """Raised when an accessory config is invalid."""


def pct_to_arc(pct: float) -> int:
    """HomeKit brightness percent (0-100) -> DALI arc level (0-254)."""
    pct = max(0, min(100, pct))
    return round(pct * DALI_ARC_LEVEL_MAX / 100)


def _require_int(cfg, key, lo, hi, *, required=True, default=None):
    if key not in cfg or cfg[key] is None:
        if required:
            raise ConfigError(f"accessory '{cfg.get('id')}': missing '{key}'")
        return default
    val = cfg[key]
    if not isinstance(val, int) or isinstance(val, bool):
        raise ConfigError(f"accessory '{cfg.get('id')}': '{key}' must be an integer")
    if not (lo <= val <= hi):
        raise ConfigError(f"accessory '{cfg.get('id')}': '{key}'={val} out of range {lo}-{hi}")
    return val


class Spec:
    def __init__(self, cfg: dict):
        self.id = cfg.get("id")
        if not self.id:
            raise ConfigError("accessory is missing 'id'")
        self.name = cfg.get("name", self.id)
        self.line = _require_int(cfg, "line", 1, 4)


class LightSpec(Spec):
    """A DALI address or group presented as a HomeKit lightbulb."""

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        has_addr = cfg.get("address") is not None
        has_group = cfg.get("group") is not None
        if has_addr == has_group:
            raise ConfigError(f"light '{self.id}': set exactly one of 'address' or 'group'")
        if has_addr:
            self.address = _require_int(cfg, "address", 0, 63)
            self.group = None
        else:
            self.group = _require_int(cfg, "group", 0, 15)
            self.address = None

    def level_intent(self, level: int) -> dict:
        level = max(0, min(DALI_ARC_LEVEL_MAX, int(level)))
        if self.address is not None:
            return {"kind": "dali_level", "line": self.line, "address": self.address, "level": level}
        return {"kind": "dali_group_level", "line": self.line, "group": self.group, "level": level}


class SceneSpec(Spec):
    """A stored DALI scene presented as a (momentary) HomeKit switch."""

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.scene = _require_int(cfg, "scene", 0, 15)
        self.group = _require_int(cfg, "group", 0, 15, required=False, default=None)

    def intent(self) -> dict:
        intent = {"kind": "dali_scene", "line": self.line, "scene": self.scene}
        if self.group is not None:
            intent["group"] = self.group
        return intent


_TYPES = {"light": LightSpec, "scene": SceneSpec}


def build_specs(entries: list) -> list:
    if not entries:
        raise ConfigError("config has no accessories defined")
    seen = set()
    result = []
    for cfg in entries:
        atype = cfg.get("type")
        if atype not in _TYPES:
            raise ConfigError(
                f"accessory '{cfg.get('id')}': unknown type '{atype}'. Known: {', '.join(sorted(_TYPES))}"
            )
        spec = _TYPES[atype](cfg)
        if spec.id in seen:
            raise ConfigError(f"duplicate accessory id '{spec.id}'")
        seen.add(spec.id)
        result.append(spec)
    return result
