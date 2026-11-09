"""Friendly command specs <-> eDIDIO trigger dicts ({commandtype, zone, linemask,
target, value, query}, the shape every input, list step, schedule, logic action and
sensor action uses in a ``.spektra`` file and on the wire).

Uses the same wire encoding as SpektraPlus's command editor:

- DALI targets: short address 0-63, group 64+g (0-15), broadcast 80.
- Lines are the physical line numbers 1-8 -> ``linemask`` bit (line - 1).
- DALI commands use TriggerType 1 (or 55 for the override variant) with the DALI
  command byte in ``value``: OFF 0, UP(fade up) 1, DOWN(fade down) 2, STEP_UP 3,
  STEP_DOWN 4, MAX 5, MIN 6; scene n = 16 + n.
- Spektra sequence/theme/schedule/pause and DMX zone fades carry the zone in
  ``zone`` (the app shows it as the value); RESUME carries it in ``zone`` too.
- DT8 colour temperature (TriggerType 47) stores mirek / 4 in ``value`` (one byte);
  the controller multiplies by 4 and sends the full 16-bit mirek to the gear.
- Every index (list, input, output, sensor, schedule, logic, sequence, theme,
  profile, zone) is 0-based, as the firmware uses it. Show users index + 1.
"""

from __future__ import annotations

import json

NO_COMMAND = 254
DALI_BROADCAST = 80
GROUP_BASE = 64

# DALI command byte for each friendly DALI action (TriggerType 1 / 55 value).
_DALI_CMD = {"off": 0, "fade_up": 1, "fade_down": 2, "step_up": 3, "step_down": 4,
             "max": 5, "min": 6}
_DALI_CMD_NAME = {0: "OFF", 1: "FADE UP", 2: "FADE DOWN", 3: "STEP UP", 4: "STEP DOWN",
                  5: "MAX", 6: "MIN", 7: "STEP DOWN AND OFF", 8: "ON AND STEP UP"}

# friendly name -> (TriggerType code, target kind, uses zone-as-value)
_SIMPLE = {
    "list_start": (9, "list"), "list_start_looping": (10, "list"), "list_stop": (11, "list"),
    "profile": (30, "profile"),
    "logic": (48, "logic"),
    "schedule_enable": (49, "schedule"), "schedule_disable": (50, "schedule"),
    "burnin_start": (20, "burnin"), "burnin_stop": (19, "burnin"),
    "input_enable": (23, "input"), "input_disable": (24, "input"),
    "output_toggle": (26, "output"), "output_high": (27, "output"),
    "output_low": (28, "output"), "output_trigger": (29, "output"),
    "sensor_override": (51, "sensor"), "sensor_disable": (52, "sensor"),
    "sensor_resume": (53, "sensor"), "sensor_mute": (68, "sensor"),
    "sensor_unmute": (69, "sensor"),
    "device_save": (38, None), "preset_code": (33, "preset"),
}
_SPEKTRA_ZONE = {  # code, target kind (sequence/theme index or none)
    "sequence": (12, "sequence"), "sequence_stop": (13, None), "theme": (14, "theme"),
    "spektra_schedule": (16, None), "spektra_pause": (35, None),
    "dmx_zone_fade_up": (63, None), "dmx_zone_fade_down": (64, None),
}
_DALI_TOGGLES = {"dali_toggle": (21, 57), "dali_min_max_toggle": (22, 58),
                 "dali_fade_long_press": (31, 61), "dali_fade_up_with_min": (8, 56)}

DT8_COLOUR_TEMP = 47
KELVIN_RANGE = (1000, 20000)


def kelvin_to_value(kelvin: int) -> int:
    """Kelvin -> the stored TriggerType 47 value (mirek / 4, 1-255)."""
    return max(1, min(255, round(1_000_000 / kelvin / 4)))


def value_to_kelvin(value: int) -> int:
    """Stored TriggerType 47 value -> the Kelvin the controller sends (0 if none)."""
    return round(1_000_000 / (value * 4)) if value > 0 else 0


ACTIONS = sorted(["none", "dali_arc", "dali_scene", "dmx", "dmx_broadcast", "dt8_colour_temp",
                  "spektra_resume", "spektra_intensity", "user_level_recall",
                  *[f"dali_{k}" for k in _DALI_CMD], *_SIMPLE, *_SPEKTRA_ZONE, *_DALI_TOGGLES])


class CommandError(ValueError):
    pass


def empty() -> dict:
    return {"commandtype": NO_COMMAND, "zone": 0, "linemask": 0, "target": 0,
            "value": 0, "query": 0}


def _int(spec, key, lo, hi, default=None):
    v = spec.get(key, default)
    if v is None:
        raise CommandError(f"'{spec.get('do')}' needs '{key}'")
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise CommandError(f"'{key}' must be a number, got {v!r}") from None
    if not lo <= v <= hi:
        raise CommandError(f"'{key}' {v} is outside {lo}-{hi}")
    return v


def linemask(spec) -> int:
    lines = spec.get("lines", spec.get("line"))
    if lines is None:
        raise CommandError(f"'{spec.get('do')}' needs 'line' (1-8) or 'lines'")
    if isinstance(lines, (int, str)):
        lines = [lines]
    mask = 0
    for ln in lines:
        ln = int(ln)
        if not 1 <= ln <= 8:
            raise CommandError(f"line {ln} is outside 1-8")
        mask |= 1 << (ln - 1)
    return mask


def dali_target(spec) -> int:
    if spec.get("broadcast"):
        return DALI_BROADCAST
    if "group" in spec:
        return GROUP_BASE + _int(spec, "group", 0, 15)
    if "address" in spec:
        return _int(spec, "address", 0, 63)
    raise CommandError(f"'{spec.get('do')}' needs 'address' (0-63), 'group' (0-15) "
                       "or 'broadcast': true")


def build(spec) -> dict:
    """Friendly spec (dict or JSON text) -> trigger dict. A dict that already has
    ``commandtype`` is passed through (fields filled with 0)."""
    if isinstance(spec, str):
        spec = json.loads(spec) if spec.strip().startswith("{") else {"do": spec.strip()}
    if spec is None:
        return empty()
    if "commandtype" in spec:
        out = empty()
        out.update({k: int(spec.get(k, 0)) for k in out})
        return out
    do = str(spec.get("do", "")).strip().lower()
    out = empty()
    override = bool(spec.get("override"))
    if do in ("", "none", "no_command"):
        return out
    if do == "dali_arc":
        out.update(commandtype=54 if override else 0, linemask=linemask(spec),
                   target=dali_target(spec), value=_int(spec, "level", 0, 254))
    elif do.startswith("dali_") and do[5:] in _DALI_CMD:
        out.update(commandtype=55 if override else 1, linemask=linemask(spec),
                   target=dali_target(spec), value=_DALI_CMD[do[5:]])
    elif do == "dali_scene":
        out.update(commandtype=55 if override else 1, linemask=linemask(spec),
                   target=dali_target(spec), value=16 + _int(spec, "scene", 0, 15))
    elif do in _DALI_TOGGLES:
        code, ocode = _DALI_TOGGLES[do]
        t = dali_target(spec)
        out.update(commandtype=ocode if override else code, linemask=linemask(spec), target=t,
                   query=_int(spec, "query", 0, 63, t if t <= 63 else 0))
    elif do == "dt8_colour_temp":
        k = _int(spec, "kelvin", *KELVIN_RANGE)
        out.update(commandtype=DT8_COLOUR_TEMP, linemask=linemask(spec),
                   target=dali_target(spec), value=kelvin_to_value(k))
    elif do == "user_level_recall":
        out.update(commandtype=62 if override else 41, linemask=linemask(spec),
                   target=dali_target(spec), value=_int(spec, "user_level", 0, 255))
    elif do == "dmx":
        ch = _int(spec, "channel", 1, 512)
        out.update(commandtype=2 if ch <= 256 else 3, linemask=linemask(spec),
                   target=ch if ch <= 256 else ch - 256, value=_int(spec, "level", 0, 255))
    elif do == "dmx_broadcast":
        if "zone" in spec:          # a Spektra zone: zone = target = zone index, no lines
            zone = _int(spec, "zone", 0, 253)
            out.update(commandtype=6, zone=zone, target=zone)
        else:                       # whole lines: zone = target = 254

            out.update(commandtype=6, zone=254, target=254, linemask=linemask(spec))
        out["value"] = _int(spec, "level", 0, 255)
    elif do in _SPEKTRA_ZONE:
        code, kind = _SPEKTRA_ZONE[do]
        out.update(commandtype=code, zone=_int(spec, "zone", 0, 255))
        if kind:
            out["target"] = _int(spec, kind, 0, 255)
    elif do == "spektra_resume":
        out.update(commandtype=36, zone=_int(spec, "zone", 0, 255))
    elif do == "spektra_intensity":
        out.update(commandtype=70, zone=_int(spec, "zone", 0, 255),
                   target=_int(spec, "zone", 0, 255), value=_int(spec, "level", 0, 255))
    elif do in _SIMPLE:
        code, kind = _SIMPLE[do]
        out["commandtype"] = code
        if kind:
            out["target"] = _int(spec, kind, 0, 255)
    else:
        raise CommandError(f"unknown action '{do}'. Known: {', '.join(ACTIONS)}")
    return out


_CODE_NAMES = {0: "DALI arc", 54: "DALI arc (override)", 8: "DALI fade up with min",
               21: "DALI on/off toggle", 22: "DALI min/max toggle", 31: "DALI fade (long press)",
               41: "Recall user level", 57: "DALI on/off toggle (override)",
               58: "DALI min/max toggle (override)", 61: "DALI fade long press (override)",
               62: "Recall user level (override)", 56: "DALI fade up with min (override)",
               9: "Start list", 10: "Start list (looping)", 11: "Stop list", 30: "Change profile",
               48: "Run logic", 49: "Enable schedule", 50: "Disable schedule",
               19: "Stop burn-in", 20: "Start burn-in", 23: "Enable input", 24: "Disable input",
               26: "Toggle output", 27: "Output high", 28: "Output low", 29: "Trigger output",
               51: "Override sensor", 52: "Temporarily disable sensor", 53: "Resume sensor",
               68: "Mute sensor", 69: "Unmute sensor", 38: "Save device", 33: "Preset code",
               12: "Start sequence", 13: "Stop sequence", 14: "Apply theme",
               16: "Start Spektra schedule", 35: "Pause Spektra", 36: "Resume Spektra",
               70: "Spektra intensity", 63: "DMX zone fade up", 64: "DMX zone fade down",
               2: "DMX channel", 3: "DMX channel", 6: "DMX broadcast",
               45: "DT8 warmer", 46: "DT8 cooler", 47: "DT8 colour temperature"}
_ONE_BASED = {9: "List", 10: "List", 11: "List", 30: "Profile", 48: "Logic",
              49: "Schedule", 50: "Schedule", 19: "Burn-in", 20: "Burn-in", 23: "Input",
              24: "Input", 26: "Output", 27: "Output", 28: "Output", 29: "Output",
              51: "Sensor", 52: "Sensor", 53: "Sensor", 68: "Sensor", 69: "Sensor",
              12: "Sequence", 14: "Theme"}


def _lines(mask: int) -> str:
    ln = [str(i + 1) for i in range(8) if mask & (1 << i)]
    return "line " + ",".join(ln) if ln else ""


def _dali_tgt(t: int) -> str:
    if t <= 63:
        return f"address {t}"
    if t <= 79:
        return f"group {t - GROUP_BASE}"
    return "broadcast" if t == DALI_BROADCAST else f"target {t}"


def describe(cmd: dict | None) -> str:
    """Trigger dict -> short English, 1-based names for indexed things."""
    if not cmd or cmd.get("commandtype", NO_COMMAND) == NO_COMMAND:
        return "no command"
    c, z, lm, t, v = (int(cmd.get(k, 0)) for k in ("commandtype", "zone", "linemask",
                                                 "target", "value"))
    if c in (1, 55):
        name = f"scene {v - 16}" if 16 <= v <= 31 else _DALI_CMD_NAME.get(v, f"cmd {v}")
        ov = " (override)" if c == 55 else ""
        return f"DALI {name}{ov} -> {_dali_tgt(t)} {_lines(lm)}".strip()
    if c in (0, 54):
        return f"{_CODE_NAMES[c]} {v} -> {_dali_tgt(t)} {_lines(lm)}".strip()
    if c == DT8_COLOUR_TEMP:
        k = f"{value_to_kelvin(v)} K" if 1 <= v <= 255 else "invalid"
        return f"{_CODE_NAMES[c]} {k} (value {v}) -> {_dali_tgt(t)} {_lines(lm)}".strip()
    if c in (8, 21, 22, 31, 41, 45, 46, 56, 57, 58, 61, 62):
        return f"{_CODE_NAMES[c]} -> {_dali_tgt(t)} {_lines(lm)}".strip()
    if c in (2, 3):
        return f"DMX channel {t + (256 if c == 3 else 0)} = {v} on {_lines(lm)}"
    if c == 6:
        where = _lines(lm) if z == 254 else f"zone {z + 1}"
        return f"DMX broadcast {v} on {where}"
    if c in (12, 14):
        return f"{_CODE_NAMES[c]} {_ONE_BASED[c]} {t + 1} (index {t}) on zone {z + 1}"
    if c in (13, 16, 35, 36, 63, 64):
        return f"{_CODE_NAMES[c]} on zone {z + 1}"
    if c == 70:
        return f"Spektra intensity {v} on zone {z + 1}"
    if c in _ONE_BASED:
        return f"{_CODE_NAMES[c]} {_ONE_BASED[c]} {t + 1} (index {t})"
    return _CODE_NAMES.get(c, f"commandtype {c} (zone {z}, linemask {lm}, target {t}, value {v})")
