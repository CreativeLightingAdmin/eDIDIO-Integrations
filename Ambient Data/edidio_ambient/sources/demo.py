"""Demo source: emits values with no external dependencies.

Useful for trying the engine and for testing. Either replays a fixed `values`
list (once, or repeating) or generates a smooth sine wave between `min` and
`max`. Great for demoing a gradient without an API key.
"""

from __future__ import annotations

import asyncio
import math


class DemoSource:
    def __init__(self, cfg: dict):
        self.name = cfg.get("name", "demo")
        self.interval = float(cfg.get("interval", 1.0))
        self.values = cfg.get("values")  # optional explicit list
        self.repeat = bool(cfg.get("repeat", True))
        self.min = float(cfg.get("min", 0.0))
        self.max = float(cfg.get("max", 100.0))
        self.period = float(cfg.get("period", 20.0))  # sine period (s)

    async def run(self, emit):
        if self.values:
            while True:
                for v in self.values:
                    emit(v)
                    await asyncio.sleep(self.interval)
                if not self.repeat:
                    return
        else:
            t = 0.0
            while True:
                # sine sweep between min and max
                frac = (math.sin(2 * math.pi * t / self.period) + 1) / 2
                emit(self.min + frac * (self.max - self.min))
                t += self.interval
                await asyncio.sleep(self.interval)
