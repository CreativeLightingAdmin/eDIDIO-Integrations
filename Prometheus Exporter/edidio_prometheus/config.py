"""Load and validate the exporter YAML configuration."""

from __future__ import annotations

from pathlib import Path

import yaml


class ConfigError(ValueError):
    """Raised when the configuration is invalid."""


class ControllerConfig:
    def __init__(self, raw: dict):
        self.host = raw.get("host")
        if not self.host:
            raise ConfigError("each controller needs a host")
        self.name = str(raw.get("name", self.host))
        self.port = int(raw.get("port", 23))
        self.use_tls = bool(raw.get("use_tls", False))
        self.timeout = float(raw.get("timeout", 5.0))
        # Live levels + event counters from the event stream (firmware >= 1.4.0).
        self.events = bool(raw.get("events", True))


class ExporterConfig:
    def __init__(self, raw: dict):
        if not isinstance(raw, dict):
            raise ConfigError("config root must be a mapping")
        listen = raw.get("listen", {}) or {}
        self.host = listen.get("host", "0.0.0.0")
        self.port = int(listen.get("port", 9464))
        # Health polls are cached for this long so frequent scrapes don't
        # hammer the controllers.
        self.min_poll_interval = float(raw.get("min_poll_interval", 10.0))
        controllers = raw.get("controllers") or []
        if not controllers:
            raise ConfigError("config has no controllers defined")
        self.controllers = [ControllerConfig(c or {}) for c in controllers]
        names = [c.name for c in self.controllers]
        if len(names) != len(set(names)):
            raise ConfigError("controller names must be unique")


def load_config(path: str | Path) -> ExporterConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return ExporterConfig(yaml.safe_load(fh))
