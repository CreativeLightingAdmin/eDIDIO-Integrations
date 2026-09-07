"""Load the CS2 GSI bridge YAML configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from .mapper import ConfigError


class ServerConfig:
    def __init__(self, raw: dict):
        self.host = raw.get("host", "127.0.0.1")
        self.port = int(raw.get("port", 3000))
        # Optional token: CS2's cfg can include an auth token; if set here we check it.
        self.token = raw.get("token")


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
        self.server = ServerConfig(raw.get("server", {}) or {})
        self.controller = ControllerConfig(raw.get("controller", {}) or {})
        self.cs2 = raw.get("cs2", {}) or {}


def load_config(path: str | Path) -> BridgeConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return BridgeConfig(raw)
