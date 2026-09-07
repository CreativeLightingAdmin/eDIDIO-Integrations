"""Source base class."""

from __future__ import annotations


class Source:
    """A data source. ``run(emit)`` loops forever, calling emit(value) for each
    new reading. Subclasses implement ``run``."""

    def __init__(self, cfg: dict):
        self.name = cfg.get("name", cfg.get("type", "source"))

    async def run(self, emit):  # pragma: no cover - interface
        raise NotImplementedError
