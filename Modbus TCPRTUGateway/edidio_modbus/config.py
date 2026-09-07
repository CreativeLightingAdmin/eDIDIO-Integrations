"""Load and validate the gateway YAML configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from .registers import ConfigError, build_register_map


class ServerConfig:
    def __init__(self, raw: dict):
        self.type = str(raw.get("type", "tcp")).lower()
        if self.type not in ("tcp", "rtu"):
            raise ConfigError(f"server.type must be 'tcp' or 'rtu', got '{self.type}'")
        self.unit_id = int(raw.get("unit_id", 1))
        if self.type == "tcp":
            self.host = raw.get("host", "0.0.0.0")
            self.port = int(raw.get("port", 502))
        else:  # rtu
            self.port = raw.get("port")  # serial device path
            if not self.port:
                raise ConfigError("server.port (serial device) is required for RTU")
            self.baudrate = int(raw.get("baudrate", 9600))
            self.parity = str(raw.get("parity", "N")).upper()
            self.stopbits = int(raw.get("stopbits", 1))
            self.bytesize = int(raw.get("bytesize", 8))


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
        self.server = ServerConfig(raw.get("server", {}) or {})
        self.controller = ControllerConfig(raw.get("controller", {}) or {})
        self.registers = build_register_map(raw.get("registers", []) or [])

    @property
    def max_register(self) -> int:
        return max(self.registers) if self.registers else 1


def load_config(path: str | Path) -> GatewayConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return GatewayConfig(raw)
