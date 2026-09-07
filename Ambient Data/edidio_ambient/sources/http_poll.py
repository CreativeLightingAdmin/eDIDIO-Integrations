"""HTTP polling source: fetch a JSON API on an interval and extract a number.

Covers a huge range of ambient concepts with one source — stock/crypto prices,
aurora Kp index, solar/grid figures, sports scores — anything reachable as JSON.

Config:
  url:        the endpoint to GET
  json_path:  dot-path to the value, with numeric list indices, e.g.
              "bitcoin.usd" or "chart.result.0.meta.regularMarketPrice"
  interval:   seconds between polls (default 60; be kind to rate limits)
  headers:    optional dict of request headers (e.g. an API key)
  transform:  optional "value * k + c" style scale/offset (a, b): value*a + b

The HTTP fetch is injectable (``fetch_fn``) so the source is unit tested without
network access.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request

_LOGGER = logging.getLogger(__name__)


def extract(data, json_path: str):
    """Follow a dot-path (with numeric indices) into decoded JSON. Returns the
    value or None if the path doesn't resolve to a number."""
    cur = data
    for part in json_path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        else:
            return None
    try:
        return float(cur)
    except (TypeError, ValueError):
        return None


def _default_fetch(url, headers):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - user-configured URL
        return json.loads(resp.read().decode("utf-8"))


class HttpPollSource:
    def __init__(self, cfg: dict, fetch_fn=None):
        self.name = cfg.get("name", "http_poll")
        self.url = cfg.get("url")
        if not self.url:
            raise ValueError("http_poll source needs a 'url'")
        self.json_path = cfg.get("json_path", "")
        self.interval = float(cfg.get("interval", 60.0))
        self.headers = cfg.get("headers") or {}
        self.scale = float(cfg.get("scale", 1.0))
        self.offset = float(cfg.get("offset", 0.0))
        self._fetch = fetch_fn or (lambda: _default_fetch(self.url, self.headers))

    def read_once(self):
        """Fetch + extract a single value (or None). Separated so it's testable."""
        try:
            data = self._fetch()
        except Exception as err:  # noqa: BLE001 - a bad poll must not kill the loop
            _LOGGER.warning("%s: fetch failed: %s", self.name, err)
            return None
        value = extract(data, self.json_path) if self.json_path else _as_float(data)
        if value is None:
            _LOGGER.warning("%s: could not extract '%s'", self.name, self.json_path)
            return None
        return value * self.scale + self.offset

    async def run(self, emit):
        while True:
            value = self.read_once()
            if value is not None:
                emit(value)
            await asyncio.sleep(self.interval)


def _as_float(data):
    try:
        return float(data)
    except (TypeError, ValueError):
        return None
