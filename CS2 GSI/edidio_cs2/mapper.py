"""CS2 Game State Integration -> eDIDIO lighting intents.

Pure (no HTTP / network / protobuf), so it is exhaustively unit tested with
recorded GSI payloads. The server feeds each payload to ``Cs2Mapper.process`` and
dispatches the returned intents.

CS2 posts a JSON payload on every state change, e.g.:

  {
    "player": { "state": { "health": 100, "flashed": 0, "burning": 0 },
                "activity": "playing" },
    "round":  { "phase": "live", "bomb": "planted" }
  }

Lighting behaviour (all configurable/toggleable):
  * health  -> DMX colour along a gradient (100% green … 0% red)
  * flashed -> a white DMX flash when the flash amount rises past a threshold
  * bomb    -> a "planted" action (scene or red), fired once on plant
  * death   -> an optional action when health hits 0

Discrete events (flash, bomb, death) fire on the RISING EDGE only, so they don't
repeat while the state persists.
"""

from __future__ import annotations


class ConfigError(ValueError):
    pass


def _hex_to_rgb(value: str):
    text = str(value).lstrip("#").strip()
    if len(text) != 6:
        raise ConfigError(f"colour must be #RRGGBB, got {value!r}")
    return [int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)]


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _lerp(a, b, t):
    return round(a + (b - a) * t)


def gradient_rgb(t, colors):
    """Interpolate t in [0,1] across a list of [r,g,b] stops."""
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


def _extract_state(payload: dict) -> dict:
    """Pull the fields we care about from a GSI payload (robust to missing keys)."""
    player = payload.get("player") or {}
    state = player.get("state") or {}
    rnd = payload.get("round") or {}
    return {
        "health": state.get("health"),
        "flashed": state.get("flashed", 0) or 0,
        "bomb": rnd.get("bomb"),
        "phase": rnd.get("phase"),
        "activity": player.get("activity"),
    }


class Cs2Mapper:
    def __init__(self, cfg: dict):
        cfg = cfg or {}
        h = cfg.get("health", {}) or {}
        self.health_enabled = bool(h.get("enabled", True))
        self.health_line = int(h.get("line", 2))
        self.health_colors = [_hex_to_rgb(c) for c in h.get("colors", ["#FF0000", "#FFFF00", "#00FF00"])]

        f = cfg.get("flash", {}) or {}
        self.flash_enabled = bool(f.get("enabled", True))
        self.flash_line = int(f.get("line", 2))
        self.flash_threshold = int(f.get("threshold", 100))
        self.flash_rgb = _hex_to_rgb(f.get("color", "#FFFFFF"))

        b = cfg.get("bomb", {}) or {}
        self.bomb_enabled = bool(b.get("enabled", True))
        self.bomb_action = b.get("action", {"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]})

        d = cfg.get("death", {}) or {}
        self.death_enabled = bool(d.get("enabled", False))
        self.death_action = d.get("action")

        self._prev = {"flashed": 0, "bomb": None, "health": None}
        self._last_health_rgb = None

    def process(self, payload: dict) -> list:
        """Return a list of intents to dispatch for this GSI payload."""
        s = _extract_state(payload)
        intents = []

        # --- flashbang: rising edge past the threshold ---
        if self.flash_enabled:
            if s["flashed"] >= self.flash_threshold and self._prev["flashed"] < self.flash_threshold:
                intents.append({"kind": "dmx_color", "line": self.flash_line, "rgb": list(self.flash_rgb)})

        # --- bomb planted: fire once on transition to 'planted' ---
        if self.bomb_enabled:
            if s["bomb"] == "planted" and self._prev["bomb"] != "planted":
                intents.append(dict(self.bomb_action))

        # --- death: health -> 0 ---
        if self.death_enabled and self.death_action:
            if s["health"] == 0 and (self._prev["health"] or 0) > 0:
                intents.append(dict(self.death_action))

        # --- health colour: continuous, only when the colour changes ---
        if self.health_enabled and isinstance(s["health"], int):
            # Don't override a just-fired flash/bomb colour in the same payload.
            if not intents:
                rgb = gradient_rgb(_clamp(s["health"], 0, 100) / 100.0, self.health_colors)
                if rgb != self._last_health_rgb:
                    intents.append({"kind": "dmx_color", "line": self.health_line, "rgb": rgb})
                    self._last_health_rgb = rgb

        self._prev = {"flashed": s["flashed"], "bomb": s["bomb"], "health": s["health"]}
        return intents
