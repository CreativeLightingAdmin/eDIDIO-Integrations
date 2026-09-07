"""Entity model: MQTT command topics, Home Assistant discovery configs, and
payload -> eDIDIO intent translation.

Kept free of any MQTT/network/protobuf dependency so it can be unit tested in
isolation. The bridge wires these to the broker and dispatcher.

Intents use the same vocabulary as the other gateways:
  {"kind": "dali_level", "line", "address", "level"}
  {"kind": "dali_group_level", "line", "group", "level"}
  {"kind": "dali_scene", "line", "scene" [, "group"]}
"""

from __future__ import annotations

DALI_ARC_LEVEL_MAX = 254


class ConfigError(ValueError):
    """Raised when an entity config is invalid."""


class BridgeContext:
    """Shared naming/topic context for all entities."""

    def __init__(self, base_topic: str, discovery_prefix: str, controller_id: str):
        self.base = base_topic.rstrip("/")
        self.discovery_prefix = discovery_prefix.rstrip("/")
        self.controller_id = controller_id
        self.device_id = f"edidio_{controller_id}"
        self.availability_topic = f"{self.base}/availability"

    def device_block(self) -> dict:
        return {
            "identifiers": [self.device_id],
            "name": f"eDIDIO {self.controller_id}",
            "manufacturer": "Control Freak",
            "model": "eDIDIO",
        }


def _require_int(cfg: dict, key: str, lo: int, hi: int, *, required=True, default=None):
    if key not in cfg or cfg[key] is None:
        if required:
            raise ConfigError(f"entity '{cfg.get('id')}': missing '{key}'")
        return default
    val = cfg[key]
    if not isinstance(val, int) or isinstance(val, bool):
        raise ConfigError(f"entity '{cfg.get('id')}': '{key}' must be an integer")
    if not (lo <= val <= hi):
        raise ConfigError(f"entity '{cfg.get('id')}': '{key}'={val} out of range {lo}-{hi}")
    return val


def _clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


class Entity:
    def __init__(self, cfg: dict):
        self.id = cfg.get("id")
        if not self.id:
            raise ConfigError("entity is missing 'id'")
        self.name = cfg.get("name", self.id)
        self.line = _require_int(cfg, "line", 1, 4)

    def unique_id(self, ctx: BridgeContext) -> str:
        return f"{ctx.device_id}_{self.id}"

    # Subclasses implement these.
    def command_topics(self, ctx: BridgeContext) -> list[str]:
        raise NotImplementedError

    def discovery(self, ctx: BridgeContext):
        """Return (discovery_topic, config_dict) or None."""
        raise NotImplementedError

    def handle(self, topic: str, payload: str, ctx: BridgeContext):
        """Return (intent_or_None, [(state_topic, payload, retain), ...])."""
        raise NotImplementedError


class LightEntity(Entity):
    """A DALI address or group presented as a Home Assistant light."""

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

    def _t(self, ctx, suffix):
        return f"{ctx.base}/{self.id}/{suffix}"

    def command_topics(self, ctx):
        return [self._t(ctx, "set"), self._t(ctx, "brightness/set")]

    def discovery(self, ctx):
        topic = f"{ctx.discovery_prefix}/light/{ctx.device_id}/{self.id}/config"
        config = {
            "name": self.name,
            "unique_id": self.unique_id(ctx),
            "command_topic": self._t(ctx, "set"),
            "state_topic": self._t(ctx, "state"),
            "payload_on": "ON",
            "payload_off": "OFF",
            "brightness_command_topic": self._t(ctx, "brightness/set"),
            "brightness_state_topic": self._t(ctx, "brightness"),
            "brightness_scale": DALI_ARC_LEVEL_MAX,
            "availability_topic": ctx.availability_topic,
            "device": ctx.device_block(),
        }
        return topic, config

    def _intent(self, level):
        if self.address is not None:
            return {"kind": "dali_level", "line": self.line, "address": self.address, "level": level}
        return {"kind": "dali_group_level", "line": self.line, "group": self.group, "level": level}

    def handle(self, topic, payload, ctx):
        set_topic = self._t(ctx, "set")
        bri_topic = self._t(ctx, "brightness/set")
        state_topic = self._t(ctx, "state")
        bri_state = self._t(ctx, "brightness")
        payload = str(payload).strip()

        if topic == bri_topic:
            level = _clamp(_to_int(payload), 0, DALI_ARC_LEVEL_MAX)
            state = "ON" if level > 0 else "OFF"
            return self._intent(level), [
                (bri_state, str(level), True),
                (state_topic, state, True),
            ]

        if topic == set_topic:
            on = payload.upper() == "ON" or payload not in ("OFF", "0", "")
            level = DALI_ARC_LEVEL_MAX if on else 0
            states = [(state_topic, "ON" if on else "OFF", True)]
            if on:
                states.append((bri_state, str(DALI_ARC_LEVEL_MAX), True))
            return self._intent(level), states

        return None, []


class SceneEntity(Entity):
    """A stored DALI scene presented as a Home Assistant scene (stateless)."""

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.scene = _require_int(cfg, "scene", 0, 15)
        self.group = _require_int(cfg, "group", 0, 15, required=False, default=None)

    def _t(self, ctx, suffix):
        return f"{ctx.base}/{self.id}/{suffix}"

    def command_topics(self, ctx):
        return [self._t(ctx, "set")]

    def discovery(self, ctx):
        topic = f"{ctx.discovery_prefix}/scene/{ctx.device_id}/{self.id}/config"
        config = {
            "name": self.name,
            "unique_id": self.unique_id(ctx),
            "command_topic": self._t(ctx, "set"),
            "payload_on": "ON",
            "availability_topic": ctx.availability_topic,
            "device": ctx.device_block(),
        }
        return topic, config

    def handle(self, topic, payload, ctx):
        if topic != self._t(ctx, "set"):
            return None, []
        intent = {"kind": "dali_scene", "line": self.line, "scene": self.scene}
        if self.group is not None:
            intent["group"] = self.group
        return intent, []


_TYPES = {"light": LightEntity, "scene": SceneEntity}


def build_entities(entities_cfg: list) -> list:
    if not entities_cfg:
        raise ConfigError("config has no entities defined")
    seen = set()
    result = []
    for cfg in entities_cfg:
        etype = cfg.get("type")
        if etype not in _TYPES:
            raise ConfigError(
                f"entity '{cfg.get('id')}': unknown type '{etype}'. Known: {', '.join(sorted(_TYPES))}"
            )
        entity = _TYPES[etype](cfg)
        if entity.id in seen:
            raise ConfigError(f"duplicate entity id '{entity.id}'")
        seen.add(entity.id)
        result.append(entity)
    return result


def _to_int(payload):
    try:
        return int(float(payload))
    except (TypeError, ValueError):
        return 0
