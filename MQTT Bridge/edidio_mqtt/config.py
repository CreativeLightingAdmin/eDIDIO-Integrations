"""Load and validate the MQTT bridge YAML configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from .entities import BridgeContext, ConfigError, build_entities


class MqttConfig:
    def __init__(self, raw: dict):
        self.host = raw.get("host", "127.0.0.1")
        self.port = int(raw.get("port", 1883))
        self.username = raw.get("username") or None
        self.password = raw.get("password") or None
        self.client_id = raw.get("client_id", "edidio-bridge")
        self.base_topic = raw.get("base_topic", "edidio")
        self.discovery = bool(raw.get("discovery", True))
        self.discovery_prefix = raw.get("discovery_prefix", "homeassistant")


class ControllerConfig:
    def __init__(self, raw: dict):
        self.id = str(raw.get("id", "edidio1"))
        self.host = raw.get("host")
        if not self.host:
            raise ConfigError("controller.host is required")
        self.port = int(raw.get("port", 23))
        self.use_tls = bool(raw.get("use_tls", False))
        self.timeout = float(raw.get("timeout", 5.0))


class BridgeConfig:
    def __init__(self, raw: dict):
        if not isinstance(raw, dict):
            raise ConfigError("config root must be a mapping")
        self.mqtt = MqttConfig(raw.get("mqtt", {}) or {})
        self.controller = ControllerConfig(raw.get("controller", {}) or {})
        self.entities = build_entities(raw.get("entities", []) or [])
        self.context = BridgeContext(
            self.mqtt.base_topic, self.mqtt.discovery_prefix, self.controller.id
        )


def load_config(path: str | Path) -> BridgeConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return BridgeConfig(raw)
