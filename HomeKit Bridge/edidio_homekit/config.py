"""Load and validate the HomeKit bridge YAML configuration."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .specs import ConfigError, build_specs

_PIN_RE = re.compile(r"^\d{3}-\d{2}-\d{3}$")


class HomeKitConfig:
    def __init__(self, raw: dict):
        self.name = raw.get("name", "eDIDIO")
        self.pincode = str(raw.get("pincode", "031-45-154"))
        if not _PIN_RE.match(self.pincode):
            raise ConfigError("homekit.pincode must look like 031-45-154")
        self.port = int(raw.get("port", 51826))
        self.persist_file = raw.get("persist_file", "edidio_homekit.state")


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
        self.homekit = HomeKitConfig(raw.get("homekit", {}) or {})
        self.controller = ControllerConfig(raw.get("controller", {}) or {})
        self.specs = build_specs(raw.get("accessories", []) or [])


def load_config(path: str | Path) -> BridgeConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return BridgeConfig(raw)
