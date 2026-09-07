"""Data sources for the ambient engine.

A source produces a stream of numeric values over time and calls ``emit(value)``
for each. Add a new concept by writing a new source (WebSocket, webhook, another
API) — the mapping/engine/dispatcher stay the same.
"""

from .base import Source
from .countdown import CountdownSource
from .demo import DemoSource
from .f1 import F1RaceControlSource
from .http_poll import HttpPollSource
from .iss import IssOverheadSource
from .webhook import WebhookSource

_TYPES = {
    "demo": DemoSource,
    "http_poll": HttpPollSource,
    "iss_overhead": IssOverheadSource,
    "countdown": CountdownSource,
    "f1_racecontrol": F1RaceControlSource,
    "webhook": WebhookSource,
}


def build_source(cfg: dict) -> Source:
    t = cfg.get("type")
    if t not in _TYPES:
        raise ValueError(f"unknown source type '{t}'. Known: {', '.join(sorted(_TYPES))}")
    return _TYPES[t](cfg)
