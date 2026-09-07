"""Auto-generate a distilled eDIDIO capability guide for the LLM.

Rather than dumping the raw .proto or firmware at the model, we introspect the
protobuf descriptors (so field names/numbers/enums stay in sync with the shipped
protocol) and combine them with curated domain notes (what the animation types
mean, timing rules, colour format, limits, ack codes). The result is a concise
Markdown guide exposed to the LLM as an MCP resource.

``build_guide()`` returns the Markdown string; the module can also be run to
write ``CAPABILITY_GUIDE.md``.
"""

from __future__ import annotations

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb

# Curated, human-authored domain knowledge that the raw proto doesn't carry.
SEQUENCE_TYPES = {
    0: "BLEND — smooth cross-fade between colours",
    1: "SIMPLE_CHASE — a block of colour runs along the fixtures",
    2: "SHADOW_CHASE — a dark gap runs along a lit line",
    3: "COMET — a bright head with a fading tail",
    4: "ROTATE — colours rotate around the fixtures (classic 'rotate' effect)",
    5: "TWINKLE — random sparkle",
    6: "BUILD_UP — fixtures fill up one by one",
    7: "CRASH — fixtures empty out",
    8: "FIREWORKS — bursts",
    9: "FIRE — flickering fire effect",
    10: "RAMP_UP — brightness ramps up",
    11: "RAMP_DOWN — brightness ramps down",
    12: "STATIC — all fixtures hold the colour(s)",
    13: "RADIAL_ROTATE — rotate from a centre point",
    14: "RADIAL_BUILD — build from a centre point",
    15: "PARTICLE_CANNON — particles fired along the line",
}

TIME_UNITS = {0: "milliseconds", 1: "seconds", 2: "minutes", 3: "hours"}

NOTES = """\
## How to author

**Sequences** (`create_sequence` / `preview_sequence`): pick a `type` (see the
Animation types table), give 1–20 `colours` (each an array of channel values
0–255, whose length must match the target zone's channels-per-light — read the
zone first with `get_zone_details`), and set timing. `time_per_step` controls the
animation speed (min 50 ms); `time_per_colour` controls how long each colour
shows; each has a matching `_unit` (0=ms,1=s,2=min,3=hr). `transition` blends
(0), snaps (1), or fades to black (2). Sequences auto-save to flash on the
device. Index 0–143.

**Themes** (`create_theme`): a static palette of 1–20 `colours` on an index
0–15. Colours repeat across fixtures if there are fewer colours than lights.

**Schedules** (`create_schedule`): an alarm with a `start_time` and a
`start_trigger`. To run sequence N at 5 PM daily: start_time = 17:00,
repeat = DAILY, trigger type = SPEKTRA_START_SEQ, target_index = N, zone = the
zone. Use SUNRISE/SUNSET astro types (with a before/after offset) for
astronomical schedules. Alarm index 0–8.

**Scheduled sequence** ("make a rotate and run it at 5 PM"): author the sequence
first (it saves), then create a schedule whose trigger targets that sequence
index. `preview_schedule` can do both in one preview.

**Calendar** (`preview_calendar`): assign a sequence or theme to specific days of
the year. Give `kind` ('sequence' or 'theme'), the `index` to run, and `days` (a
list of day numbers 1–366 and/or ISO dates like '2026-12-25'). Set `override:
true` to force it over the normal schedule. Read the current assignments any time
with `get_calendar`.

## Live playback (run something on a zone RIGHT NOW)
To play a stored sequence/theme immediately (not on a schedule), use
`play_sequence(zone, index)` / `play_theme(zone, index)`; `stop_zone(zone)` stops
playback and turns the output off. This is transient (no preview/confirm needed).
NOTE: a zone only produces physical output if it is patched to a line/universe
(its `line_or_universe_mask` is non-zero) — check with `list_zones` first, or the
command will succeed but nothing will be visible.

## Schedules & calendar  (READ THIS before scheduling seasonal content)
A schedule (alarm) fires an action at a time of day. The calendar decides WHICH
sequence/theme runs on WHICH day of the year.

**For any date-ranged or seasonal request** ("Christmas in December", "this week",
"over the holidays"), use the CALENDAR for the dates and keep the SCHEDULES daily:
  1. Author the sequence/theme.
  2. `preview_calendar` to assign it to those days (day numbers or ISO dates).
  3. Create DAILY start/stop schedules (repeat=daily, ALL months) where the START
     action is `start_calendar` (Start Calendar Event — plays whatever the calendar
     has for today) and the STOP action is `stop_sequence`.
Do NOT restrict the schedule's month/day bitmask to the season, and do NOT use a
`start_sequence` trigger tied to one sequence — that bypasses the calendar. Only
narrow a schedule's own days/months if the user explicitly wants the SCHEDULE
itself limited (e.g. "only on weekdays").

For `repeat: daily`/`weekdays` the day + month bitmasks are filled automatically
(else the controller shows the alarm as "Once"). Times can be "HH:MM" or an astro
event (`sunrise`/`sunset`) with an optional `offset` ("2:00" after, "-0:30"
before).

## Device clock
`get_time` reads the controller's RTC and compares it to this computer; `set_time`
sets it (defaults to this computer's local time). If schedules fire at the wrong
time, check `get_time` first.

## Reading / queries (no writes)
- `list_zones`, `list_sequences`, `list_themes` — what's configured on the device.
- `whats_playing` — the LIVE state: which sequence/theme each zone is playing now.
- `list_alarms`, `get_calendar` — the schedules and the full-year calendar.
- `whats_scheduled_next` — computes the soonest alarm that will fire and when.
- `get_time` — the controller's clock vs this computer's.

Note: zones have NO name/title on the controller (only a number + electrical
config); any friendly zone names live in the SpektraPlus app's project file.
Sequences and themes DO have a `title`.

## Colour format
Colours are **per-channel arrays of 0–255**, e.g. RGB `[255,0,0]` = red, RGBW
`[255,0,0,0]`. The number of channels must match the zone (`channels_per_light`).
Read the zone with `get_zone_details` if unsure.

## Safety
Authoring writes **persistent config**. Every create returns a preview + a token;
nothing is written until you call `confirm(token)`. Read existing slots
(`list_sequences`/`list_themes`/`list_alarms`) first to avoid overwriting.
"""


def _enum_table(enum_type, title, subset=None):
    lines = [f"### {title}", ""]
    for v in enum_type.DESCRIPTOR.values:
        if subset and v.name not in subset:
            continue
        lines.append(f"- `{v.name}` = {v.number}")
    lines.append("")
    return "\n".join(lines)


def _fields_line(message_type):
    return ", ".join(
        f"{f.name}#{f.number}" for f in message_type.DESCRIPTOR.fields
    )


def build_guide() -> str:
    parts = []
    parts.append("# eDIDIO SpektraPlus — Capability Guide\n")
    parts.append(
        "Reference for authoring SpektraPlus **sequences**, **themes** and "
        "**schedules (alarms)** on a Control Freak eDIDIO controller. Generated "
        "from the live protobuf descriptors + curated notes, so field names and "
        "enum values match the device.\n"
    )

    parts.append("## Limits\n")
    parts.append(
        "- Sequences: index 0-143; up to 20 colours; title <= 28 chars; "
        "min 50 ms per step\n"
        "- Themes: index 0-15; up to 20 colours; title <= 28 chars\n"
        "- Schedules (alarms): index 0-8 (user)\n"
        "- Zones: 0-9 (pre-configured; read details with `get_zone_details`)\n"
        "- Colour channel values: 0-255\n\n"
        "The device also reports exact counts via `device_capabilities`.\n"
    )

    parts.append("## Animation types (`type`)\n")
    for num, desc in SEQUENCE_TYPES.items():
        parts.append(f"- `{num}` — {desc}")
    parts.append("")

    parts.append("## Timing units\n")
    for num, name in TIME_UNITS.items():
        parts.append(f"- `{num}` — {name}")
    parts.append("")

    parts.append("## Key message fields (from the protocol)\n")
    parts.append(f"- **SpektraSequenceConfigMessage**: {_fields_line(pb.SpektraSequenceConfigMessage)}")
    parts.append(f"- **SpektraThemeConfigMessage**: {_fields_line(pb.SpektraThemeConfigMessage)}")
    parts.append(f"- **AlarmMessage**: {_fields_line(pb.AlarmMessage)}")
    parts.append(f"- **TriggerMessage**: {_fields_line(pb.TriggerMessage)}")
    parts.append(f"- **SpektraSettingMessage** (zone): {_fields_line(pb.SpektraSettingMessage)}")
    parts.append("")

    parts.append(_enum_table(pb.SpektraTransitionType, "Transition types"))
    parts.append(_enum_table(pb.AlarmRepeatType, "Alarm repeat types"))
    parts.append(_enum_table(pb.AlarmAstroType, "Alarm astro types"))
    parts.append(_enum_table(
        pb.TriggerType, "Trigger types (schedules — subset)",
        subset={"SPEKTRA_START_SEQ", "SPEKTRA_STOP_SEQ", "SPEKTRA_THEME",
                "SPEKTRA_STATIC", "SPEKTRA_SCHEDULE", "SPEKTRA_INTENSITY",
                "ALARM_ENABLE", "ALARM_DISABLE"}))
    parts.append(_enum_table(
        pb.AckMessageType, "Ack result codes",
        subset={"SUCCESS", "INDEX_OUT_OF_BOUNDS", "INVALID_PARAMS", "SLOTS_FULL",
                "DEPRECATED", "UNAUTHORISED", "DECODE_FAILED"}))

    parts.append(NOTES)
    guide = "\n".join(parts)
    # Normalise fancy dashes/bullets to ASCII so the guide renders cleanly in any
    # console / MCP client regardless of encoding.
    for uni, ascii_ in (("—", "-"), ("–", "-"), ("·", "-"),
                        ("≤", "<="), ("→", "->")):
        guide = guide.replace(uni, ascii_)
    return guide


def main():
    import os
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "CAPABILITY_GUIDE.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(build_guide())
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
