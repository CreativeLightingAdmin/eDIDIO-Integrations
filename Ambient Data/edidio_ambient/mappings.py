"""Mappings: turn a numeric value (or event) from a source into an eDIDIO intent.

Pure (no network / protobuf) so they are exhaustively unit tested. Three types
cover most ambient-data concepts:

  gradient   value in [min,max] -> RGB along a list of colour stops -> DMX colour
             (e.g. stock/crypto green→red, aurora green→purple, solar draw)
  threshold  value crosses bands -> a lighting action per band
             (e.g. VIX levels, server-health, Kp-index alert scenes)
  level      value in [min,max] -> DALI brightness 0-254 on an address/group
             (e.g. a "how busy is the network" dimmer)

Intents use the shared vocabulary, plus a `dmx_color` kind the engine's
dispatcher understands:
  {"kind": "dmx_color", "line", "rgb": [r,g,b]}
  {"kind": "dali_level" | "dali_group_level" | "dali_scene" | "spektra" | ...}
"""

from __future__ import annotations

DALI_ARC_LEVEL_MAX = 254


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


def gradient_rgb(value, lo, hi, colors):
    """Interpolate `value` (in [lo,hi]) across a list of #RRGGBB stops -> [r,g,b]."""
    if hi == lo:
        t = 0.0
    else:
        t = _clamp((value - lo) / (hi - lo), 0.0, 1.0)
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


class Mapping:
    """Base: value -> intent dict or None.

    `dedup` tells the engine whether to suppress an intent identical to the last
    one sent. True for continuous mappings (gradient/threshold/level) so a steady
    value doesn't repeat; False for `event` so each discrete event re-fires.
    """

    dedup = True

    def intent(self, value):  # pragma: no cover - interface
        raise NotImplementedError


class GradientMapping(Mapping):
    def __init__(self, cfg: dict):
        self.line = _req_int(cfg, "line", 1, 4)
        self.min = _req_num(cfg, "min")
        self.max = _req_num(cfg, "max")
        colors = cfg.get("colors")
        if not isinstance(colors, list) or len(colors) < 1:
            raise ConfigError("gradient needs a 'colors' list of at least one #RRGGBB")
        self.colors = [_hex_to_rgb(c) for c in colors]

    def intent(self, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        rgb = gradient_rgb(v, self.min, self.max, self.colors)
        return {"kind": "dmx_color", "line": self.line, "rgb": rgb}


class ThresholdMapping(Mapping):
    """Fire an action based on which band the value falls in.

    bands: a list of {min: value, action: {...}} sorted low->high. The value's
    band is the highest `min` it is >= to. The engine de-dups consecutive
    identical intents, so this naturally 'fires on band change'.
    """

    def __init__(self, cfg: dict):
        bands = cfg.get("bands")
        if not isinstance(bands, list) or not bands:
            raise ConfigError("threshold needs a 'bands' list")
        self.bands = []
        for b in bands:
            if "min" not in b or "action" not in b:
                raise ConfigError("each band needs 'min' and 'action'")
            self.bands.append((float(b["min"]), _validate_action(b["action"])))
        self.bands.sort(key=lambda x: x[0])

    def intent(self, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        chosen = None
        for threshold, action in self.bands:
            if v >= threshold:
                chosen = action
            else:
                break
        return dict(chosen) if chosen else None


class LevelMapping(Mapping):
    def __init__(self, cfg: dict):
        self.line = _req_int(cfg, "line", 1, 4)
        self.min = _req_num(cfg, "min")
        self.max = _req_num(cfg, "max")
        self.invert = bool(cfg.get("invert", False))
        has_addr = cfg.get("address") is not None
        has_group = cfg.get("group") is not None
        if has_addr == has_group:
            raise ConfigError("level mapping needs exactly one of 'address' or 'group'")
        if has_addr:
            self.address = _req_int(cfg, "address", 0, 63)
            self.group = None
        else:
            self.group = _req_int(cfg, "group", 0, 15)
            self.address = None

    def intent(self, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if self.max == self.min:
            t = 0.0
        else:
            t = _clamp((v - self.min) / (self.max - self.min), 0.0, 1.0)
        if self.invert:
            t = 1.0 - t
        level = round(t * DALI_ARC_LEVEL_MAX)
        if self.address is not None:
            return {"kind": "dali_level", "line": self.line, "address": self.address, "level": level}
        return {"kind": "dali_group_level", "line": self.line, "group": self.group, "level": level}


class EventMapping(Mapping):
    """Map a named event (string) to a lighting action.

    For categorical/discrete feeds — F1 flags ('safety_car', 'yellow'), D&D
    events ('combat_start'), alerts ('firing'), etc. Each matching event fires
    (dedup off), so the same event can recur.
    """

    dedup = False

    def __init__(self, cfg: dict):
        events = cfg.get("events")
        if not isinstance(events, dict) or not events:
            raise ConfigError("event mapping needs an 'events' map of name -> action")
        self.events = {str(k): _validate_action(v) for k, v in events.items()}

    def intent(self, value):
        key = str(value)
        action = self.events.get(key)
        return dict(action) if action else None


_TYPES = {
    "gradient": GradientMapping,
    "threshold": ThresholdMapping,
    "level": LevelMapping,
    "event": EventMapping,
}


def build_mapping(cfg: dict) -> Mapping:
    t = cfg.get("type")
    if t not in _TYPES:
        raise ConfigError(f"unknown mapping type '{t}'. Known: {', '.join(sorted(_TYPES))}")
    return _TYPES[t](cfg)


# --- action validation (for threshold bands) ---

_ACTION_KINDS = {"dali_scene", "dali_level", "dali_group_level", "dmx_color", "spektra", "spektra_stop"}


def _validate_action(action: dict) -> dict:
    if not isinstance(action, dict) or "kind" not in action:
        raise ConfigError("band action must be a dict with a 'kind'")
    if action["kind"] not in _ACTION_KINDS:
        raise ConfigError(f"unknown action kind '{action['kind']}'")
    return action


def _req_num(cfg, key):
    if key not in cfg or cfg[key] is None:
        raise ConfigError(f"missing '{key}'")
    return float(cfg[key])


def _req_int(cfg, key, lo, hi):
    if key not in cfg or cfg[key] is None:
        raise ConfigError(f"missing '{key}'")
    v = cfg[key]
    if not isinstance(v, int) or isinstance(v, bool):
        raise ConfigError(f"'{key}' must be an integer")
    if not (lo <= v <= hi):
        raise ConfigError(f"'{key}'={v} out of range {lo}-{hi}")
    return v
