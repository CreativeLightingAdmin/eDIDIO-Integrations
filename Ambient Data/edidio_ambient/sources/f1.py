"""F1 race-control source (OpenF1).

Polls OpenF1's race_control feed and emits a **flag/event label** for each *new*
message — feed it to an `event` mapping (safety_car → orange wash, yellow → …,
green → clear, red → red, chequered → celebration).

Emits labels like: "safety_car", "virtual_safety_car", "yellow", "double_yellow",
"green", "red", "chequered". New-message detection + label derivation are pure and
tested; the fetch is injectable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request

_LOGGER = logging.getLogger(__name__)

DEFAULT_URL = "https://api.openf1.org/v1/race_control"


def label_for(msg: dict):
    """Derive an event label from an OpenF1 race_control record, or None."""
    category = (msg.get("category") or "").lower()
    message = (msg.get("message") or "").lower()
    flag = (msg.get("flag") or "").lower()

    if category == "safetycar" or "safety car" in message:
        if "virtual" in message or "vsc" in message:
            return "virtual_safety_car"
        return "safety_car"
    if flag:
        return flag.replace(" ", "_")  # green, yellow, double_yellow, red, chequered, clear
    return None


def _key(msg: dict):
    """A stable identity for de-duping messages across polls."""
    return (msg.get("date"), msg.get("message"), msg.get("flag"), msg.get("lap_number"))


def _default_fetch(url):
    with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


class F1RaceControlSource:
    def __init__(self, cfg: dict, fetch_fn=None):
        self.name = cfg.get("name", "F1 race control")
        self.url = cfg.get("url", DEFAULT_URL)
        self.interval = float(cfg.get("interval", 10))
        self._fetch = fetch_fn or (lambda: _default_fetch(self.url))
        self._seen = set()
        self._primed = False

    def poll(self):
        """Return the list of new event labels since the last poll."""
        try:
            data = self._fetch()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("%s: fetch failed: %s", self.name, err)
            return []
        if not isinstance(data, list):
            return []
        labels = []
        for msg in data:
            k = _key(msg)
            if k in self._seen:
                continue
            self._seen.add(k)
            if not self._primed:
                continue  # first poll only records history; don't replay the whole race
            lbl = label_for(msg)
            if lbl:
                labels.append(lbl)
        self._primed = True
        return labels

    async def run(self, emit):
        while True:
            for label in self.poll():
                emit(label)
            await asyncio.sleep(self.interval)
