"""Load and validate the ambient engine YAML configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from .mappings import ConfigError, build_mapping
from .sources import build_source


class ControllerConfig:
    def __init__(self, raw: dict):
        self.host = raw.get("host")
        if not self.host:
            raise ConfigError("controller.host is required")
        self.port = int(raw.get("port", 23))
        self.use_tls = bool(raw.get("use_tls", False))
        self.timeout = float(raw.get("timeout", 5.0))


class AmbientConfig:
    def __init__(self, raw: dict):
        if not isinstance(raw, dict):
            raise ConfigError("config root must be a mapping")
        self.controller = ControllerConfig(raw.get("controller", {}) or {})
        self.source = build_source(raw.get("source", {}) or {})
        self.mapping = build_mapping(raw.get("mapping", {}) or {})
        self.min_interval = float(raw.get("min_interval", 0.5))


def load_config(path: str | Path) -> AmbientConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return AmbientConfig(raw)
