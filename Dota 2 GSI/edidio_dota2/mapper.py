"""Dota 2 GSI -> eDIDIO lighting intents.

Pure (no HTTP/network), unit tested with recorded-style payloads. A Dota 2 GSI
payload looks like:

  {
    "hero":   {"health_percent": 80, "mana_percent": 60, "alive": true,
               "respawn_seconds": 0},
    "map":    {"game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS",
               "daytime": true, "clock_time": 320},
    "player": {"kills": 3, ...}
  }

Behaviour (configurable):
  * health_percent -> DMX colour along a gradient (100% green .. 0% red)
  * death (alive true->false)   -> a death action, fired once
  * respawn (false->true)       -> a respawn action, fired once
  * daytime change (optional)   -> day/night ambience scenes

Discrete events fire on the transition edge only.
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


def _extract(payload):
    hero = payload.get("hero") or {}
    mp = payload.get("map") or {}
    return {
        "health": hero.get("health_percent"),
        "alive": hero.get("alive"),
        "daytime": mp.get("daytime"),
        "game_state": mp.get("game_state"),
    }


class Dota2Mapper:
    def __init__(self, cfg: dict):
        cfg = cfg or {}
        h = cfg.get("health", {}) or {}
        self.health_enabled = bool(h.get("enabled", True))
        self.health_line = int(h.get("line", 2))
        self.health_colors = [_hex_to_rgb(c) for c in h.get("colors", ["#FF0000", "#FFFF00", "#00FF00"])]

        d = cfg.get("death", {}) or {}
        self.death_enabled = bool(d.get("enabled", True))
        self.death_action = d.get("action", {"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]})

        r = cfg.get("respawn", {}) or {}
        self.respawn_enabled = bool(r.get("enabled", True))
        self.respawn_action = r.get("action", {"kind": "dmx_color", "line": 2, "rgb": [0, 255, 0]})

        dn = cfg.get("daynight", {}) or {}
        self.daynight_enabled = bool(dn.get("enabled", False))
        self.day_action = dn.get("day_action")
        self.night_action = dn.get("night_action")

        self._prev = {"alive": None, "daytime": None}
        self._last_health_rgb = None

    def process(self, payload: dict) -> list:
        s = _extract(payload)
        intents = []

        # death / respawn edges
        if s["alive"] is not None and self._prev["alive"] is not None:
            if self.death_enabled and self._prev["alive"] and not s["alive"]:
                intents.append(dict(self.death_action))
            elif self.respawn_enabled and not self._prev["alive"] and s["alive"]:
                intents.append(dict(self.respawn_action))

        # day/night ambience edges
        if self.daynight_enabled and s["daytime"] is not None and self._prev["daytime"] is not None:
            if s["daytime"] and not self._prev["daytime"] and self.day_action:
                intents.append(dict(self.day_action))
            elif not s["daytime"] and self._prev["daytime"] and self.night_action:
                intents.append(dict(self.night_action))

        # health colour (only when it changes, and only if no edge event this tick)
        if self.health_enabled and isinstance(s["health"], int) and s["alive"] and not intents:
            rgb = gradient_rgb(_clamp(s["health"], 0, 100) / 100.0, self.health_colors)
            if rgb != self._last_health_rgb:
                intents.append({"kind": "dmx_color", "line": self.health_line, "rgb": rgb})
                self._last_health_rgb = rgb

        self._prev = {"alive": s["alive"], "daytime": s["daytime"]}
        return intents
