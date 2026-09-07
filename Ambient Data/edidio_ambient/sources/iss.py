"""ISS overhead source.

Polls the ISS position and emits a *proximity* value: 0 when the station is far,
rising as it approaches your coordinates (peaking directly overhead). Feed it to a
threshold mapping ("overhead → light show").

  proximity = max(0, radius_km - distance_km)

The fetch is injectable so the distance maths is unit tested with no network.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import urllib.request

_LOGGER = logging.getLogger(__name__)

DEFAULT_URL = "http://api.open-notify.org/iss-now.json"


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in km."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _default_fetch(url):
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


class IssOverheadSource:
    def __init__(self, cfg: dict, fetch_fn=None):
        self.name = cfg.get("name", "ISS overhead")
        if cfg.get("lat") is None or cfg.get("lon") is None:
            raise ValueError("iss_overhead source needs 'lat' and 'lon'")
        self.lat = float(cfg["lat"])
        self.lon = float(cfg["lon"])
        self.radius_km = float(cfg.get("radius_km", 500))
        self.interval = float(cfg.get("interval", 30))
        self.url = cfg.get("url", DEFAULT_URL)
        self._fetch = fetch_fn or (lambda: _default_fetch(self.url))

    def read_once(self):
        try:
            data = self._fetch()
            pos = data["iss_position"]
            dist = haversine_km(self.lat, self.lon, float(pos["latitude"]), float(pos["longitude"]))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("%s: fetch/parse failed: %s", self.name, err)
            return None
        return max(0.0, self.radius_km - dist)

    async def run(self, emit):
        while True:
            v = self.read_once()
            if v is not None:
                emit(v)
            await asyncio.sleep(self.interval)
