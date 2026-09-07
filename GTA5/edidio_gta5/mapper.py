"""GTA V game state -> eDIDIO lighting intents.

Pure (no HTTP/network), unit tested with recorded-style payloads. The ScriptHookV
mod POSTs JSON like:

  {
    "wanted": 3,          # wanted level 0-5 (stars)
    "health": 80,         # 0-100
    "in_vehicle": true,
    "event": "wasted"     # optional one-shot: "wasted" | "busted" | null
  }

Behaviour (configurable):
  * wanted level -> a police "siren" action per star tier (fires on change).
    Tier 0 clears to a normal scene; tiers 1-5 escalate (e.g. run a red/blue
    strobe sequence, or a colour). Best paired with a SpektraPlus sequence that
    actually alternates red/blue on the controller.
  * health -> DMX colour gradient (full green .. low red), when not in a wanted
    state and no event.
  * event "wasted"/"busted" -> a one-shot flash.
"""

from __future__ import annotations


class ConfigError(ValueError):
    pass


def _hex_to_rgb(value):
    text = str(value).lstrip("#").strip()
    if len(text) != 6:
        raise ConfigError(f"colour must be #RRGGBB, got {value!r}")
    return [int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)]


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _lerp(a, b, t):
    return round(a + (b - a) * t)


def gradient_rgb(t, colors):
    t = _clamp(t, 0.0, 1.0)
    n = len(colors)
    if n == 1:
        return list(colors[0])
    seg = t * (n - 1)
    i = int(seg)
    if i >= n - 1:
        return list(colors[-1])
    frac = seg - i
    c0, c1 = colors[i], colors[i + 1]
    return [_lerp(c0[0], c1[0], frac), _lerp(c0[1], c1[1], frac), _lerp(c0[2], c1[2], frac)]


# Default per-star actions: 0 = clear (scene 1), 1-5 escalate a police strobe.
_DEFAULT_WANTED = {
    0: {"kind": "dali_scene", "line": 1, "scene": 1},
    1: {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 0, "action": "START"},
    2: {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 0, "action": "START"},
    3: {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 0, "action": "START"},
    4: {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 1, "action": "START"},
    5: {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 1, "action": "START"},
}


class Gta5Mapper:
    def __init__(self, cfg: dict):
        cfg = cfg or {}
        w = cfg.get("wanted", {}) or {}
        self.wanted_enabled = bool(w.get("enabled", True))
        # actions: {0: {...}, 1: {...}, ...} keyed by star count (ints or str keys)
        actions = w.get("actions")
        if actions:
            self.wanted_actions = {int(k): v for k, v in actions.items()}
        else:
            self.wanted_actions = dict(_DEFAULT_WANTED)

        h = cfg.get("health", {}) or {}
        self.health_enabled = bool(h.get("enabled", True))
        self.health_line = int(h.get("line", 2))
        self.health_colors = [_hex_to_rgb(c) for c in h.get("colors", ["#FF0000", "#FFFF00", "#00FF00"])]

        ev = cfg.get("events", {}) or {}
        self.events = {str(k): v for k, v in ev.items()} or {
            "wasted": {"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]},
            "busted": {"kind": "dmx_color", "line": 2, "rgb": [0, 0, 255]},
        }

        self._prev = {"wanted": None, "health_rgb": None, "event": None}

    def process(self, state: dict) -> list:
        intents = []

        # one-shot events (wasted/busted) fire once per occurrence
        event = state.get("event")
        if event and event != self._prev["event"]:
            action = self.events.get(str(event))
            if action:
                intents.append(dict(action))
        self._prev["event"] = event or None

        # wanted level -> per-star action, on change
        wanted = state.get("wanted")
        if self.wanted_enabled and isinstance(wanted, int) and wanted != self._prev["wanted"]:
            action = self.wanted_actions.get(_clamp(wanted, 0, 5))
            if action and not intents:
                intents.append(dict(action))
            self._prev["wanted"] = wanted

        # health -> colour, only when calm (no wanted level) and nothing else fired
        health = state.get("health")
        calm = not wanted  # 0 or None
        if self.health_enabled and isinstance(health, int) and calm and not intents:
            rgb = gradient_rgb(_clamp(health, 0, 100) / 100.0, self.health_colors)
            if rgb != self._prev["health_rgb"]:
                intents.append({"kind": "dmx_color", "line": self.health_line, "rgb": rgb})
                self._prev["health_rgb"] = rgb

        return intents
