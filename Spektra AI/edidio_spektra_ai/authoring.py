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
    SPEKTRA_TITLE_MAX_LEN,
    AlarmAstroType,
    AlarmRepeatType,
    EdidioClient,
    SpektraTargetType,
    SpektraTransitionType,
    TriggerType,
)

# Name -> value maps so the LLM can pass friendly strings.
SEQUENCE_TYPE_NAMES = {
    "blend": 0, "simple_chase": 1, "shadow_chase": 2, "comet": 3, "rotate": 4,
    "twinkle": 5, "build_up": 6, "crash": 7, "fireworks": 8, "fire": 9,
    "ramp_up": 10, "ramp_down": 11, "static": 12, "radial_rotate": 13,
    "radial_build": 14, "particle_cannon": 15,
}
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

def compile_sequence(spec: dict, *, message_id: int = 1):
    index = int(spec.get("index", 0))
    if not (0 <= index <= SPEKTRA_SEQUENCE_MAX_INDEX):
        raise SpecError(f"sequence index {index} out of range 0-{SPEKTRA_SEQUENCE_MAX_INDEX}")
    seq_type = _enum(SEQUENCE_TYPE_NAMES, spec.get("type", "rotate"), "sequence type")
    colours = _colours(spec.get("colours"))
    transition = _enum(TRANSITION_NAMES, spec.get("transition", "blend"), "transition")
    title = str(spec.get("title", ""))[:SPEKTRA_TITLE_MAX_LEN]

    step_ms = int(spec.get("time_per_step_ms", spec.get("step_ms", 500)))
    if step_ms and step_ms < SPEKTRA_MIN_MS_PER_STEP:
        raise SpecError(f"time_per_step_ms {step_ms} is below the {SPEKTRA_MIN_MS_PER_STEP}ms minimum")
    colour_ms = int(spec.get("time_per_colour_ms", 0))

    # Fade/cross-fade time between steps (0 = instant/snap). Stored on the device
    # in 10ms units, so we round to the nearest 10ms.
    fade_ms = int(spec.get("fade_ms", spec.get("fade_time_ms", 0)))
    if fade_ms < 0:
        raise SpecError("fade_ms must be >= 0")
    if fade_ms and step_ms and fade_ms > step_ms:
        raise SpecError(f"fade_ms {fade_ms} exceeds time_per_step_ms {step_ms}; "
                        "the fade must fit within a step")
    fade_by_10ms = round(fade_ms / 10)

    frame = EdidioClient.create_spektra_sequence_message(
        message_id, index=index, seq_type=seq_type, colours=colours,
        transition=transition,
        time_per_step=step_ms, time_per_step_unit=0,
        time_per_colour=colour_ms, time_per_colour_unit=0,
        fade_time_by_10ms=fade_by_10ms,
        title=title,
        is_reverse_direction=1 if spec.get("reverse") else 0,
        is_cycle_direction=1 if spec.get("cycle") else 0,
    )
    type_name = next((k for k, v in SEQUENCE_TYPE_NAMES.items() if v == seq_type), seq_type)
    fade_txt = f"{fade_ms}ms fade" if fade_ms else "no fade (snap)"
    preview = (
        f"**Sequence {index}** \"{title or '(untitled)'}\" - type `{type_name}`, "
        f"{len(colours)} colour(s): {_colour_names(colours)}; step {step_ms}ms; "
        f"{fade_txt}; transition {spec.get('transition', 'blend')}. "
        "Saves to the controller."
    )
    return [frame], preview


# --- themes ----------------------------------------------------------------

def compile_theme(spec: dict, *, message_id: int = 1):
    index = int(spec.get("index", 0))
    if not (0 <= index <= SPEKTRA_THEME_MAX_INDEX):
        raise SpecError(f"theme index {index} out of range 0-{SPEKTRA_THEME_MAX_INDEX}")
    colours = _colours(spec.get("colours"))
    title = str(spec.get("title", ""))[:SPEKTRA_TITLE_MAX_LEN]
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
    `astro` ("sunrise"/"sunset"). The action is `trigger` (type/zone/target_index)
    OR an inline `sequence`/`theme` to author-and-target in one go."""
    index = int(spec.get("index", 0))
    if not (0 <= index <= ALARM_MAX_INDEX):
        raise SpecError(f"schedule index {index} out of range 0-{ALARM_MAX_INDEX}")

    messages = []
    preview_bits = []

    # Optional inline sequence/theme to author first, then target it.
    trigger = dict(spec.get("trigger") or {})
    if "sequence" in spec:
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
    end_time = 0
    end_trigger = dict(spec.get("end_trigger") or {})
    end_str = spec.get("end_time")
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
    preview_bits.append(
        f"**Schedule {index}**: at {when}{window}, repeat {repeat_name}, "
        f"run {_trigger_desc(trigger)} on zone {trigger['zone']}"
        + (f" then stop at {end_str}" if end_str else "") + "."
    )
    return messages, "\n".join(preview_bits)


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
