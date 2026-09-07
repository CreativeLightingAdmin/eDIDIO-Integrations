"""KSP telemetry -> eDIDIO lighting intents.

Pure (no kRPC / network), unit tested with sampled telemetry dicts. Each tick the
game loop reads telemetry and calls ``KspMapper.process(telemetry)``:

  telemetry keys (all optional; supply what your kRPC/Telemachus poll provides):
    throttle    0.0-1.0   -> brightness on a group/line
    fuel        0.0-1.0   -> green->red gauge colour (full green, empty red)
    situation   str       -> "pre_launch"/"flying"/"orbiting"/"landed"/... (event)
    stage       int       -> a stage flash on change
    abort       bool      -> red abort flash (rising edge)

Continuous values (throttle/fuel) emit only on change; discrete events fire on
their edge.
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


class KspMapper:
    def __init__(self, cfg: dict):
        cfg = cfg or {}
        th = cfg.get("throttle", {}) or {}
        self.throttle_enabled = bool(th.get("enabled", True))
        self.throttle_line = int(th.get("line", 1))
        self.throttle_group = int(th.get("group", 0))

        f = cfg.get("fuel", {}) or {}
        self.fuel_enabled = bool(f.get("enabled", True))
        self.fuel_line = int(f.get("line", 2))
        self.fuel_colors = [_hex_to_rgb(c) for c in f.get("colors", ["#FF0000", "#FFFF00", "#00FF00"])]

        a = cfg.get("abort", {}) or {}
        self.abort_enabled = bool(a.get("enabled", True))
        self.abort_action = a.get("action", {"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]})

        s = cfg.get("stage", {}) or {}
        self.stage_enabled = bool(s.get("enabled", True))
        self.stage_action = s.get("action", {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 0, "action": "START"})

        ev = cfg.get("situations", {}) or {}
        self.situations = {str(k): v for k, v in ev.items()}

        self._prev = {"throttle_level": None, "fuel_rgb": None, "stage": None,
                      "abort": None, "situation": None}

    def process(self, tel: dict) -> list:
        intents = []

        # abort edge
        abort = tel.get("abort")
        if self.abort_enabled and abort is not None and self._prev["abort"] is not None:
            if abort and not self._prev["abort"]:
                intents.append(dict(self.abort_action))
        self._prev["abort"] = abort

        # stage change
        stage = tel.get("stage")
        if self.stage_enabled and stage is not None and self._prev["stage"] is not None:
            if stage != self._prev["stage"]:
                intents.append(dict(self.stage_action))
        self._prev["stage"] = stage

        # situation event (pre_launch/flying/orbiting/landed/...)
        situation = tel.get("situation")
        if situation is not None and situation != self._prev["situation"]:
            action = self.situations.get(str(situation))
            if action:
                intents.append(dict(action))
            self._prev["situation"] = situation

        # throttle -> brightness (on change), suppressed if an event fired
        throttle = tel.get("throttle")
        if self.throttle_enabled and throttle is not None and not intents:
            level = round(_clamp(float(throttle), 0.0, 1.0) * 254)
            if level != self._prev["throttle_level"]:
                intents.append({"kind": "dali_group_level", "line": self.throttle_line,
                                "group": self.throttle_group, "level": level})
                self._prev["throttle_level"] = level

        # fuel -> gauge colour (on change)
        fuel = tel.get("fuel")
        if self.fuel_enabled and fuel is not None and not intents:
            rgb = gradient_rgb(_clamp(float(fuel), 0.0, 1.0), self.fuel_colors)
            if rgb != self._prev["fuel_rgb"]:
                intents.append({"kind": "dmx_color", "line": self.fuel_line, "rgb": rgb})
                self._prev["fuel_rgb"] = rgb

        return intents
