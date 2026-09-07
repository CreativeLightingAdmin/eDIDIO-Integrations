"""Load and validate the KNX gateway YAML configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from .group_map import ConfigError, build_group_map


class KnxConfig:
    def __init__(self, raw: dict):
        self.connection = str(raw.get("connection", "automatic")).lower()
        if self.connection not in ("automatic", "tunnelling", "tunneling", "routing"):
            raise ConfigError("knx.connection must be automatic | tunnelling | routing")
        self.gateway_ip = raw.get("gateway_ip")
        self.gateway_port = int(raw.get("gateway_port", 3671))
        if self.connection in ("tunnelling", "tunneling") and not self.gateway_ip:
            raise ConfigError("knx.gateway_ip is required for tunnelling")


class ControllerConfig:
    def __init__(self, raw: dict):
        self.host = raw.get("host")
        if not self.host:
            raise ConfigError("controller.host is required")
        self.port = int(raw.get("port", 23))
        self.use_tls = bool(raw.get("use_tls", False))
        self.timeout = float(raw.get("timeout", 5.0))


class GatewayConfig:
    def __init__(self, raw: dict):
        if not isinstance(raw, dict):
            raise ConfigError("config root must be a mapping")
        self.knx = KnxConfig(raw.get("knx", {}) or {})
        self.controller = ControllerConfig(raw.get("controller", {}) or {})
        self.group_map = build_group_map(raw.get("group_addresses", []) or [])


def load_config(path: str | Path) -> GatewayConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return GatewayConfig(raw)
