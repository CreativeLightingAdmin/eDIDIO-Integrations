"""Load and validate the OSC bridge YAML configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from .oscmap import ConfigError, build_address_map


class OSCConfig:
    def __init__(self, raw: dict):
        self.host = raw.get("host", "0.0.0.0")
        self.port = int(raw.get("port", 8000))


class ControllerConfig:
    def __init__(self, raw: dict):
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
        self.osc = OSCConfig(raw.get("osc", {}) or {})
        self.controller = ControllerConfig(raw.get("controller", {}) or {})
        self.address_map = build_address_map(raw.get("addresses", []) or [])


def load_config(path: str | Path) -> BridgeConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return BridgeConfig(raw)
