"""Countdown source (e.g. rocket launch).

Polls an API for an event timestamp (ISO 8601) and emits an *intensity* that
rises as the event approaches, within a `window_s` window:

  intensity = clamp(window_s - seconds_until, 0, window_s)

0 far out; climbs through the final window; peaks at/after T-0. Feed a threshold
mapping (e.g. T-10s → ignition sequence). Fetch + clock are injectable for tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from datetime import datetime, timezone

_LOGGER = logging.getLogger(__name__)


def parse_iso(ts: str):
    """Parse an ISO 8601 timestamp (tolerating a trailing 'Z') to aware UTC."""
    s = str(ts).strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _extract(data, path):
    cur = data
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            return None
    return cur


def _default_fetch(url):
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


class CountdownSource:
    def __init__(self, cfg: dict, fetch_fn=None, clock=None):
        self.name = cfg.get("name", "countdown")
        self.url = cfg.get("url")
        if not self.url:
            raise ValueError("countdown source needs a 'url'")
        self.json_path = cfg.get("json_path", "")
        self.window_s = float(cfg.get("window_s", 120))
        self.interval = float(cfg.get("interval", 30))
        self._fetch = fetch_fn or (lambda: _default_fetch(self.url))
        self._now = clock or (lambda: datetime.now(timezone.utc))

    def read_once(self):
        try:
            data = self._fetch()
            ts = _extract(data, self.json_path) if self.json_path else data
            target = parse_iso(ts)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("%s: fetch/parse failed: %s", self.name, err)
            return None
        seconds_until = (target - self._now()).total_seconds()
        intensity = self.window_s - seconds_until
        return max(0.0, min(self.window_s, intensity))

    async def run(self, emit):
        while True:
            v = self.read_once()
            if v is not None:
                emit(v)
            await asyncio.sleep(self.interval)
