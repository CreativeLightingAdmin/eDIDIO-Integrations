"""Authoring compiler: turn a validated spec (the dict an LLM fills) into eDIDIO
messages + a human-readable preview.

Pure (uses only the ``edidio_control_py`` builders, no network), so the whole
spec -> messages path is unit tested. Three spec kinds:

  sequence_spec  -> [sequence message]
  theme_spec     -> [theme message]
  schedule_spec  -> [ (optional inline sequence/theme message,) alarm message ]

Each ``compile_*`` returns ``(messages, preview)`` where messages is a list of
framed byte messages to send (in order) and preview is a Markdown summary for
the confirm step. Validation raises ``SpecError`` with a clear message.
"""

from __future__ import annotations

from datetime import date

from edidio_control_py import (
    ALARM_MAX_INDEX,
    SPEKTRA_COLOURS_MAX,
    SPEKTRA_MIN_MS_PER_STEP,
    SPEKTRA_SEQUENCE_MAX_INDEX,
    SPEKTRA_THEME_MAX_INDEX,
    AlarmAstroType,
    AlarmRepeatType,
    EdidioClient,
    SpektraTargetType,
    SpektraTransitionType,
    TriggerType,
)

from . import commands
from .sync import device_sequence_title, device_theme_title

# Name -> value maps so the LLM can pass friendly strings.
SEQUENCE_TYPE_NAMES = {
    "blend": 0, "simple_chase": 1, "shadow_chase": 2, "comet": 3, "rotate": 4,
    "twinkle": 5, "build_up": 6, "crash": 7, "fireworks": 8, "fire": 9,
    "ramp_up": 10, "ramp_down": 11, "static": 12, "radial_rotate": 13,
    "radial_build": 14, "particle_cannon": 15,
}
# Which fields each type uses (firmware colour_sequences.c; the same table as
# SpektraPlus's sequenceFields.ts TYPE_BEHAVIOUR).
COLOUR_TIMER_TYPES = {1, 2, 3, 5, 8, 9, 15}     # colour from the colour timer
RANGE_TYPES = {1, 2, 3, 6, 7, 14, 15}           # repeat over blocks of `range` lights
BACKGROUND_TYPES = {1, 2, 3, 6, 8, 10, 11, 14, 15}
DIRECTION_TYPES = {0, 1, 2, 3, 4, 6, 10, 11, 13, 14, 15}   # honour reverse / cycle
RANDOM_ORDER_TYPES = {0, 1, 2, 3, 5, 8, 9, 10, 11, 15}     # honour random colour order
COMET_TYPES = {3}                                # args[3] = comet tail length
# With random types on, the firmware picks a new type this often, by step unit
# (sequence_handle_step: 60 / 600 / 3600 / 7200 s).
RANDOM_TYPE_PERIOD = {0: "1 minute", 1: "10 minutes", 2: "1 hour", 3: "2 hours"}
DEFAULT_TIME_PER_COLOUR_MS = 2000               # SpektraPlus's preset value
SEQUENCE_TYPE_LABELS = {v: k for k, v in SEQUENCE_TYPE_NAMES.items()}
TRANSITION_NAMES = {"blend": SpektraTransitionType.BLEND, "snap": SpektraTransitionType.SNAP,
                    "fade_to_black": SpektraTransitionType.FADE_TO_BLACK}
TIME_UNIT_NAMES = {"ms": 0, "milliseconds": 0, "s": 1, "sec": 1, "seconds": 1,
                   "min": 2, "minutes": 2, "hr": 3, "hours": 3}
REPEAT_NAMES = {
    "none": AlarmRepeatType.ALARM_NO_REPEAT, "once": AlarmRepeatType.ALARM_NO_REPEAT,
    "daily": AlarmRepeatType.ALARM_REPEAT_DAILY,
    "workday": AlarmRepeatType.ALARM_REPEAT_WORK_DAY,
    "weekdays": AlarmRepeatType.ALARM_REPEAT_WORK_DAY,
    "weekly": AlarmRepeatType.ALARM_REPEAT_WEEKLY,
    "monthly": AlarmRepeatType.ALARM_REPEAT_MONTHLY,
}
ASTRO_NAMES = {"none": AlarmAstroType.ALARM_NO_ASTRO, "sunrise": AlarmAstroType.ALARM_SUNRUSE,
               "sunset": AlarmAstroType.ALARM_SUNSET}


class SpecError(ValueError):
    pass


def _enum(name_map, value, what):
    if isinstance(value, int):
        return value
    key = str(value).strip().lower()
    if key not in name_map:
        raise SpecError(f"unknown {what} '{value}'. Options: {', '.join(sorted(name_map))}")
    return name_map[key]


def _colours(raw):
    if not isinstance(raw, list) or not raw:
        raise SpecError("'colours' must be a non-empty list of channel arrays, e.g. [[255,0,0]]")
    if len(raw) > SPEKTRA_COLOURS_MAX:
        raise SpecError(f"too many colours ({len(raw)}); max {SPEKTRA_COLOURS_MAX}")
    out = []
    for c in raw:
        if not isinstance(c, list) or not c:
            raise SpecError(f"each colour must be a list of channel values 0-255, got {c!r}")
        vals = []
        for v in c:
            iv = int(v)
            if not (0 <= iv <= 255):
                raise SpecError(f"channel value {v} out of range 0-255")
            vals.append(iv)
        out.append(vals)
    # Warn (not error) if colours have inconsistent channel counts.
    lengths = {len(c) for c in out}
    if len(lengths) > 1:
        raise SpecError(f"all colours must have the same channel count; got {sorted(lengths)}")
    return out


def _time_ms(spec, key_ms, default=0):
    return int(spec.get(key_ms, default))


def _colour_names(colours):
    return ", ".join("[" + ",".join(str(v) for v in c) + "]" for c in colours)


# --- sequences -------------------------------------------------------------

# The controller stores step and colour times as 16-bit values with a unit
# (colour.h: uint16_t time_per_step + time_per_step_unit); 1.6.3 refuses a value
# over 65535. So a time is sent in the smallest unit it fits in.
_UNIT_MS = {0: 1, 1: 1000, 2: 60_000, 3: 3_600_000}
_UNIT_WORD = {0: "ms", 1: "s", 2: "min", 3: "h"}
_TIME_MAX = 0xFFFF


def _time_field(ms: int, what: str):
    """ms -> (value, unit, note). The note says when the time had to be rounded."""
    for unit, mult in _UNIT_MS.items():
        value = round(ms / mult)
        if value <= _TIME_MAX:
            if value * mult != ms:
                return value, unit, (f"{what} {ms} is stored in {_UNIT_WORD[unit]} "
                                     f"(16-bit field), so it becomes {value} "
                                     f"{_UNIT_WORD[unit]} = {value * mult}ms")
            return value, unit, ""
    raise SpecError(f"{what} {ms} is longer than the controller can store "
                    f"({_TIME_MAX} hours)")

def compile_sequence(spec: dict, *, message_id: int = 1):
    index = int(spec.get("index", 0))
    if not (0 <= index <= SPEKTRA_SEQUENCE_MAX_INDEX):
        raise SpecError(f"sequence index {index} out of range 0-{SPEKTRA_SEQUENCE_MAX_INDEX}")
    seq_type = _enum(SEQUENCE_TYPE_NAMES, spec.get("type", "rotate"), "sequence type")
    colours = _colours(spec.get("colours"))
    transition = _enum(TRANSITION_NAMES, spec.get("transition", "blend"), "transition")
    title = device_sequence_title(str(spec.get("title", "")))   # kept to 23 bytes

    step_ms = int(spec.get("time_per_step_ms", spec.get("step_ms", 500)))
    if step_ms and step_ms < SPEKTRA_MIN_MS_PER_STEP:
        raise SpecError(f"time_per_step_ms {step_ms} is below the {SPEKTRA_MIN_MS_PER_STEP}ms minimum")

    # Only the colour-timer types read time_per_colour. Left at 0, the firmware uses its
    # 50 ms minimum, so a chase changes colour every 50 ms; default to SpektraPlus's 2 s.
    colour_ms = int(spec.get("time_per_colour_ms", DEFAULT_TIME_PER_COLOUR_MS))
    if colour_ms < SPEKTRA_MIN_MS_PER_STEP:
        raise SpecError(f"time_per_colour_ms {colour_ms} is below the "
                        f"{SPEKTRA_MIN_MS_PER_STEP}ms minimum")

    # Fade between steps (0 = snap), stored in 10 ms units. The firmware ADDS it to both
    # timers: each step lasts time_per_step_ms + fade_ms (fade first, then the hold).
    fade_ms = int(spec.get("fade_ms", spec.get("fade_time_ms", 0)))
    if fade_ms < 0:
        raise SpecError("fade_ms must be >= 0")
    fade_by_10ms = round(fade_ms / 10)

    # Light range: the chase/build types repeat over blocks of `range` lights (0 = the
    # whole zone; the controller caps it at the zone's light count).
    light_range = int(spec.get("range", 0))
    if not 0 <= light_range <= 512:
        raise SpecError(f"range {light_range} is outside 0-512 (0 = the whole zone)")

    # args: [0..2] background colour (the firmware reads only these 3 channels),
    # [3] comet tail length (0 = the default of 3), [4] unused.
    bg = spec.get("background")
    vals = []
    if bg is not None:
        if not isinstance(bg, list) or not 1 <= len(bg) <= 3:
            raise SpecError("'background' must be 1-3 channel values, e.g. [0,0,40] "
                            "(the controller uses the first 3 channels only)")
        vals = [int(v) for v in bg]
        if any(not 0 <= v <= 254 for v in vals):
            raise SpecError("background values must be 0-254 (255 means 'not set')")
    tail = spec.get("comet_tail")
    if tail is not None:
        tail = int(tail)
        if not 1 <= tail <= 254:
            raise SpecError(f"comet_tail {tail} is outside 1-254")
    args = None
    if bg is not None or tail is not None:
        args = (vals + [0, 0, 0])[:3] + [tail or 0, 0]

    # Direction: cycle (bounce) wins over reverse in the firmware, so ask for one.
    reverse, cycle = bool(spec.get("reverse")), bool(spec.get("cycle"))
    if reverse and cycle:
        raise SpecError("choose 'reverse' or 'cycle', not both (cycle wins on the controller)")

    # Random colour order, and random types: the controller switches to a random type
    # from the list now and then. An empty list or "any" means any type.
    random_order = bool(spec.get("random_colour_order", spec.get("random_color_order")))
    rt = spec.get("random_types")
    random_mask, random_on, pool = 0, False, {seq_type}
    if rt not in (None, False, []):
        random_on = True
        if rt in (True, "any", "all"):
            pool = set(SEQUENCE_TYPE_NAMES.values())
        else:
            if not isinstance(rt, list):
                raise SpecError("'random_types' is a list of sequence types, or \"any\"")
            pool = {_enum(SEQUENCE_TYPE_NAMES, t, "sequence type") for t in rt}
            if any(not 0 <= t < len(SEQUENCE_TYPE_NAMES) for t in pool):
                raise SpecError(f"random_types must be types 0-{len(SEQUENCE_TYPE_NAMES) - 1}")
            for t in pool:
                random_mask |= 1 << t

    step_val, step_unit, step_note = _time_field(step_ms, "time_per_step_ms")
    colour_val, colour_unit, colour_note = _time_field(colour_ms, "time_per_colour_ms")
    step_ms, colour_ms = step_val * _UNIT_MS[step_unit], colour_val * _UNIT_MS[colour_unit]

    frame = EdidioClient.create_spektra_sequence_message(
        message_id, index=index, seq_type=seq_type, colours=colours,
        transition=transition,
        time_per_step=step_val, time_per_step_unit=step_unit,
        time_per_colour=colour_val, time_per_colour_unit=colour_unit,
        fade_time_by_10ms=fade_by_10ms,
        range=light_range,
        title=title,
        is_reverse_direction=1 if reverse else 0,
        is_cycle_direction=1 if cycle else 0,
        is_randomised_type=1 if random_on else 0,
        random_types_mask=random_mask,
        has_random_colour_order=random_order,
        args=args,
    )
    type_name = next((k for k, v in SEQUENCE_TYPE_NAMES.items() if v == seq_type), seq_type)
    # With random types, a field matters if ANY type in the pool uses it.
    which = "none of the random types use" if random_on else f"`{type_name}` does not use"
    fade_txt = f"{fade_ms}ms fade" if fade_ms else "no fade (snap)"
    parts = [f"step {step_ms}ms", fade_txt]
    if fade_ms:
        parts.append(f"each step lasts {step_ms + fade_ms}ms (step + fade)")
    notes = [n for n in (step_note, colour_note) if n]
    if transition == SpektraTransitionType.FADE_TO_BLACK:
        notes.append("fade_to_black is not implemented by the controller (1.6.3): it plays "
                     "the same as blend")
    if pool & COLOUR_TIMER_TYPES:
        parts.append(f"each colour {colour_ms + fade_ms}ms")
    elif "time_per_colour_ms" in spec:
        notes.append(f"{which} time_per_colour_ms (the colours follow the steps)")
    if light_range:
        parts.append(f"range {light_range} lights")
        if not pool & RANGE_TYPES:
            notes.append(f"{which} range")
    if bg is not None:
        parts.append(f"background {vals}")
        if not pool & BACKGROUND_TYPES:
            notes.append(f"{which} the background colour")
    if tail is not None:
        parts.append(f"comet tail {tail}")
        if not pool & COMET_TYPES:
            notes.append(f"{which} comet_tail (comet only)")
    if reverse or cycle:
        parts.append("cycle (bounce)" if cycle else "reverse")
        if not pool & DIRECTION_TYPES:
            notes.append(f"{which} direction")
    if random_order:
        parts.append("random colour order")
        if not pool & RANDOM_ORDER_TYPES:
            notes.append(f"{which} random colour order")
    if random_on:
        names = "any type" if not random_mask else ", ".join(
            SEQUENCE_TYPE_LABELS[t] for t in sorted(pool))
        parts.append(f"random type from {names}, changing every "
                     f"{RANDOM_TYPE_PERIOD[step_unit]}")
    preview = (
        f"**Sequence {index}** \"{title or '(untitled)'}\" - type `{type_name}`, "
        f"{len(colours)} colour(s): {_colour_names(colours)}; {'; '.join(parts)}; "
        f"transition {spec.get('transition', 'blend')}. Saves to the controller."
        + "".join(f"\nNOTE: {n}." for n in notes)
    )
    return [frame], preview


# --- themes ----------------------------------------------------------------

def compile_theme(spec: dict, *, message_id: int = 1):
    index = int(spec.get("index", 0))
    if not (0 <= index <= SPEKTRA_THEME_MAX_INDEX):
        raise SpecError(f"theme index {index} out of range 0-{SPEKTRA_THEME_MAX_INDEX}")
    colours = _colours(spec.get("colours"))
    title = device_theme_title(str(spec.get("title", "")))      # kept to 27 bytes
    frame = EdidioClient.create_spektra_theme_message(
        message_id, index=index, colours=colours, title=title
    )
    preview = (
        f"**Theme {index}** \"{title or '(untitled)'}\" - "
        f"{len(colours)} colour(s): {_colour_names(colours)}. Saves to the controller."
    )
    return [frame], preview


# --- schedules -------------------------------------------------------------

_DAY_BITS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _day_bitmask(days):
    mask = 0
    for d in days or []:
        key = str(d).strip().lower()[:3]
        if key not in _DAY_BITS:
            raise SpecError(f"unknown day '{d}'")
        mask |= 1 << _DAY_BITS[key]
    return mask


def _month_bitmask(months):
    """Month numbers 1-12 -> bitmask (bit0=Jan .. bit11=Dec)."""
    mask = 0
    for m in months or []:
        mi = int(m)
        if not (1 <= mi <= 12):
            raise SpecError(f"month {m} out of range 1-12")
        mask |= 1 << (mi - 1)
    return mask


def compile_schedule(spec: dict, *, message_id: int = 1):
    """A schedule spec. Required: `index`, and either `time` ("HH:MM") or an
    `astro` ("sunrise"/"sunset"). The action is `command` (any command JSON - see
    commands.py: start a list, change profile, DALI scene, ...), `trigger`
    (type/zone/target_index), OR an inline `sequence`/`theme` to author-and-target
    in one go. `end_time` + `end_command` / `end_trigger` add an end event."""
    index = int(spec.get("index", 0))
    if not (0 <= index <= ALARM_MAX_INDEX):
        raise SpecError(f"schedule index {index} out of range 0-{ALARM_MAX_INDEX}")

    messages = []
    preview_bits = []

    # Optional inline sequence/theme to author first, then target it.
    trigger = dict(spec.get("trigger") or {})
    described = None
    if "command" in spec:
        cmd = _build_command(spec["command"])
        trigger = _cmd_to_trigger(cmd)
        described = commands.describe(cmd)
    elif "sequence" in spec:
        seq_frames, seq_preview = compile_sequence(spec["sequence"], message_id=message_id)
        messages.extend(seq_frames)
        preview_bits.append(seq_preview)
        trigger.setdefault("type", TriggerType.SPEKTRA_START_SEQ)
        trigger.setdefault("target_index", int(spec["sequence"].get("index", 0)))
        trigger.setdefault("zone", int(spec["sequence"].get("zone", spec.get("zone", 0))))
    elif "theme" in spec:
        th_frames, th_preview = compile_theme(spec["theme"], message_id=message_id)
        messages.extend(th_frames)
        preview_bits.append(th_preview)
        trigger.setdefault("type", TriggerType.SPEKTRA_THEME)
        trigger.setdefault("target_index", int(spec["theme"].get("index", 0)))
        trigger.setdefault("zone", int(spec["theme"].get("zone", spec.get("zone", 0))))

    if "type" not in trigger:
        raise SpecError("schedule needs a 'trigger' (with type/target_index) or an inline 'sequence'/'theme'")
    trigger.setdefault("zone", int(spec.get("zone", 0)))

    _resolve_trigger_type(trigger)

    # Time or astro.
    start_time = 0
    astro = _enum(ASTRO_NAMES, spec.get("astro", "none"), "astro type")
    time_str = spec.get("time")
    offset_before = bool(spec.get("offset_before", False))
    if astro == AlarmAstroType.ALARM_NO_ASTRO:
        if not time_str:
            raise SpecError("schedule needs a 'time' (\"HH:MM\") or an 'astro' (sunrise/sunset)")
        hh, mm = _parse_hhmm(time_str)
        start_time = EdidioClient.pack_time(hh, mm, 0)
    else:
        # For an astro alarm, start_time carries the OFFSET amount from the event
        # (e.g. "sunset + 1 hour" -> offset 01:00, offset_before=False).
        off = spec.get("offset")
        if off is not None:
            oh, om = _parse_offset(off)
            start_time = EdidioClient.pack_time(oh, om, 0)
        if str(spec.get("offset", "")).strip().startswith("-"):
            offset_before = True

    # Optional end time + stop action (e.g. run 17:00 - 23:00). If an end time is
    # given without an explicit end_trigger, default to stopping playback on the
    # same zone.
    # No end event = NO_COMMAND at hour 25 (an hour past 24 disables the end event;
    # SpektraPlus writes the same). Without this the engine default (type 0, 00:00)
    # would be a live end event at midnight.
    end_time = EdidioClient.pack_time(25, 0, 0)
    end_trigger = dict(spec.get("end_trigger") or {})
    end_described = None
    if "end_command" in spec:
        ecmd = _build_command(spec["end_command"])
        end_trigger = _cmd_to_trigger(ecmd)
        end_described = commands.describe(ecmd)
    end_str = spec.get("end_time")
    if end_described and not end_str:
        raise SpecError("end_command needs an end_time")
    if not end_str:
        end_trigger = {"type": commands.NO_COMMAND}
    if end_str:
        eh, em = _parse_hhmm(end_str)
        end_time = EdidioClient.pack_time(eh, em, 0)
        if "type" not in end_trigger:
            end_trigger = {"type": TriggerType.SPEKTRA_STOP_SEQ,
                           "zone": trigger["zone"],
                           "target_index": trigger.get("target_index", 0)}
        _resolve_trigger_type(end_trigger)
        end_trigger.setdefault("zone", trigger["zone"])

    repeat = _enum(REPEAT_NAMES, spec.get("repeat", "daily"), "repeat")
    day_mask = _day_bitmask(spec.get("days")) if spec.get("days") else 0
    # The controller/app derive the repeat pattern partly from the day bitmask, so
    # make it agree with the repeat enum (else a DAILY alarm shows as "Once"):
    # daily = all 7 days, weekdays = Mon-Fri.
    if not day_mask:
        if repeat == AlarmRepeatType.ALARM_REPEAT_DAILY:
            day_mask = 0x7F
        elif repeat == AlarmRepeatType.ALARM_REPEAT_WORK_DAY:
            day_mask = 0x1F

    # A repeating alarm must also select the months it runs in (bit0=Jan..bit11=Dec),
    # else it won't repeat across months. Default to every month for any repeat;
    # allow an explicit `months` list (1-12) to narrow it.
    month_mask = _month_bitmask(spec.get("months")) if spec.get("months") else 0
    if not month_mask and repeat != AlarmRepeatType.ALARM_NO_REPEAT:
        month_mask = 0xFFF  # all 12 months

    alarm_frame = EdidioClient.create_alarm_message(
        message_id, index=index, enabled=bool(spec.get("enabled", True)),
        start_time=start_time,
        start_trigger=trigger,
        end_time=end_time,
        end_trigger=end_trigger or None,
        astro_start=astro,
        start_offset_is_before=offset_before,
        repeat=repeat, repeat_day_bitmask=day_mask, repeat_month_bitmask=month_mask,
    )
    messages.append(alarm_frame)

    if astro == AlarmAstroType.ALARM_NO_ASTRO:
        when = time_str
    else:
        off = spec.get("offset")
        sign = "-" if offset_before else "+"
        when = spec.get("astro") + (f" {sign}{_parse_offset(off)[0]:02d}:{_parse_offset(off)[1]:02d}"
                                    if off is not None else "")
    repeat_name = next((k for k, v in REPEAT_NAMES.items() if v == repeat), repeat)
    window = f" until {end_str}" if end_str else ""
    action = described or f"{_trigger_desc(trigger)} on zone {trigger['zone']}"
    end_text = ""
    if end_str:
        end_text = f"; at {end_str}: {end_described or 'stop playback'}"
    preview_bits.append(
        f"**Schedule {index}** (Schedule {index + 1} in the app): at {when}{window}, "
        f"repeat {repeat_name}, run {action}{end_text}."
    )
    return messages, "\n".join(preview_bits)


def _build_command(spec) -> dict:
    try:
        return commands.build(spec)
    except (commands.CommandError, ValueError) as err:
        raise SpecError(str(err)) from None


def _cmd_to_trigger(cmd: dict) -> dict:
    """commands.py trigger dict -> the engine's TriggerMessage dict keys."""
    return {"type": cmd["commandtype"], "zone": cmd["zone"], "line_mask": cmd["linemask"],
            "target_index": cmd["target"], "value": cmd["value"], "query_index": cmd["query"]}


def _resolve_trigger_type(trigger: dict) -> None:
    """Map a friendly trigger `type` string to a TriggerType enum in place."""
    tname = trigger.get("type")
    if isinstance(tname, str):
        friendly = {"start_sequence": TriggerType.SPEKTRA_START_SEQ,
                    "stop_sequence": TriggerType.SPEKTRA_STOP_SEQ,
                    "theme": TriggerType.SPEKTRA_THEME,
                    # "Start Calendar Event": play whatever the calendar assigns today
                    "start_calendar": TriggerType.SPEKTRA_SCHEDULE,
                    "calendar": TriggerType.SPEKTRA_SCHEDULE,
                    "calendar_event": TriggerType.SPEKTRA_SCHEDULE,
                    "start_calendar_event": TriggerType.SPEKTRA_SCHEDULE}
        resolved = friendly.get(tname.lower())
        if resolved is None:
            raise SpecError(f"unknown trigger type '{tname}'")
        trigger["type"] = resolved


def _trigger_desc(trigger):
    t = trigger.get("type")
    if t == TriggerType.SPEKTRA_START_SEQ:
        return f"sequence {trigger.get('target_index', 0)}"
    if t == TriggerType.SPEKTRA_THEME:
        return f"theme {trigger.get('target_index', 0)}"
    return f"trigger {t} (target {trigger.get('target_index', 0)})"


def _parse_hhmm(s):
    try:
        parts = str(s).strip().split(":")
        hh, mm = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        raise SpecError(f"time '{s}' must be \"HH:MM\" (24h)")
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise SpecError(f"time '{s}' out of range")
    return hh, mm


def _parse_offset(value):
    """Parse an astro offset into (hours, minutes). Accepts "H:MM"/"HH:MM", a plain
    number of minutes, or a leading '-' (before the event); magnitude only returned."""
    s = str(value).strip().lstrip("+-").strip()
    if ":" in s:
        hh, mm = s.split(":", 1)
        h, m = int(hh), int(mm)
    else:
        total = int(s)
        h, m = divmod(total, 60)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise SpecError(f"offset '{value}' out of range (max 23:59)")
    return h, m


# --- calendar --------------------------------------------------------------

_CAL_TARGET = {"sequence": SpektraTargetType.SEQUENCE, "theme": SpektraTargetType.THEME}


def _day_of_year(value) -> int:
    """Accept a 1-366 day number or an ISO 'YYYY-MM-DD' / 'MM-DD' date -> 0-based
    day-of-year index."""
    if isinstance(value, int):
        if not (1 <= value <= 366):
            raise SpecError(f"day {value} out of range 1-366")
        return value - 1
    s = str(value).strip()
    try:
        parts = [int(p) for p in s.split("-")]
        if len(parts) == 3:
            d = date(parts[0], parts[1], parts[2])
        elif len(parts) == 2:
            d = date(date.today().year, parts[0], parts[1])
        else:
            raise ValueError
    except (ValueError, TypeError):
        raise SpecError(f"date '{value}' must be a day number 1-366 or YYYY-MM-DD / MM-DD")
    return d.timetuple().tm_yday - 1


def compile_calendar(spec: dict, *, message_id: int = 1):
    """Assign a sequence/theme to specific days of the year.

    spec: {kind: 'sequence'|'theme', index, days: [day-numbers or dates],
           override?: bool}. `days` accepts 1-366 day numbers and/or ISO dates.
    """
    kind = str(spec.get("kind", "sequence")).lower()
    if kind not in _CAL_TARGET:
        raise SpecError("calendar 'kind' must be 'sequence' or 'theme'")
    index = int(spec.get("index", 0))
    limit = SPEKTRA_SEQUENCE_MAX_INDEX if kind == "sequence" else SPEKTRA_THEME_MAX_INDEX
    if not (0 <= index <= limit):
        raise SpecError(f"{kind} index {index} out of range 0-{limit}")
    raw_days = spec.get("days")
    if not isinstance(raw_days, list) or not raw_days:
        raise SpecError("calendar needs a non-empty 'days' list (day numbers 1-366 or dates)")

    days = [False] * 366
    chosen = []
    for d in raw_days:
        idx = _day_of_year(d)
        days[idx] = True
        chosen.append(idx + 1)

    frame = EdidioClient.create_spektra_calendar_message(
        message_id, _CAL_TARGET[kind], index, days, is_override=bool(spec.get("override", False)))
    preview = (f"**Calendar**: run {kind} {index} on {len(chosen)} day(s) "
               f"(day-of-year {sorted(chosen)}). "
               f"{'Override. ' if spec.get('override') else ''}Saves to the controller.")
    return [frame], preview
