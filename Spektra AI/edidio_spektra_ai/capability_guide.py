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

TOOLS_BY_TASK = """\
## Tools by task

Reads run at once; anything the controller stores is preview_* -> confirm(token)
and ends with a save. Indices are 0-based (List 1 = 0); replies show both.

- **Find / connect**: discover_controllers, connect_controller (TLS on 443),
  connection_status, device_capabilities, get_device_settings, list_zones,
  get_zone_details, query_dmx_cache.
- **Health and faults**: health_check, get_diagnostics, run_line_diagnostics,
  device_log, diagnose_controller_log (lights left on - from the controller's own
  log), preview_clear_device_log, sd_overview / sd_list_files / sd_read_file / sd_search / sd_download,
  parse_event_log / diagnose_stuck_on (exported files).
- **What is happening now**: live_state, sensor_states, dali_levels, whats_playing,
  whats_scheduled_next, get_time.
- **Do something now** (transient): run_command (any action - command_reference),
  change_profile, play_sequence / play_theme / stop_zone, set_zone_colour,
  send_dali / send_dmx, sensor_command, rdm_identify.
- **Author on the controller**: preview_list, preview_input (momentary or latching),
  preview_output, preview_logic, preview_sensor / preview_remove_sensor,
  preview_translation (DMX to DALI), preview_burnin, preview_schedule (any command),
  preview_sequence / preview_theme / preview_calendar, clear_schedule, preview_names,
  preview_zone (colour zones).
- **Read the configuration**: list_lists, list_io, list_logic, list_sensors,
  list_translations, list_burnins, list_sequences, list_themes, list_alarms,
  get_calendar, check_calendar (expected dates vs the calendar), get_names,
  functionality_statement (plain-English write-up).
- **Settings**: preview_device_settings, preview_network_settings,
  preview_clock_settings, ntp_sync_now, set_time, preview_line_types (reboots),
  preview_logging, wifi_status / preview_wifi_settings (ADDICT).
- **DALI**: dali_scan, dali_levels, commission_dali / preview_dali_commission, set_dali_line,
  dali_add_to_group, dali_set_scenes, dali_set_fade_time, dali_query_groups,
  dali_recall_scene, dali_set_level, dali_identify, dali_set_colour (DT8),
  dali_devices / preview_dali_channel_order (multi-channel drivers in channel order).
  DALI-2 control devices: dali2_scan, dali2_device, preview_dali2_readdress,
  dali_find_duplicates, preview_dali2_instance (enable, report timer, hysteresis).
- **RDM** (DMX output line): rdm_discover, rdm_get, rdm_identify, preview_rdm_set.
- **.spektra files**: pull_spektra_file, preview_push_spektra (only the connected
  controller, only what changed), sync_status, summarize_spektra,
  validate_spektra, diff_spektra, migrate_spektra_to_v3.
- **Watch and notify**: start_watching / recent_events / stop_watching,
  notify_when (ready-made events), notify_on (raw conditions),
  list_notifications / clear_notifications.
"""

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
        "- Sequences: index 0-143; up to 20 colours; title kept to 23 UTF-8 bytes "
        "(longer is cut on push); min 50 ms per step\n"
        "- Themes: index 0-15; up to 20 colours; title kept to 27 UTF-8 bytes\n"
        "- Schedules (alarms): index 0-8 (user)\n"
        "- Lists: up to 255 steps; each step waits 0-65535 s before the next. Writing "
        "List 1 erases every list (Spektra AI rewrites the others for you)\n"
        "- Firmware 1.6.3 refuses values it cannot store (INVALID_PARAMS + reason) "
        "instead of truncating them\n"
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

    parts.append(TOOLS_BY_TASK)
    parts.append("## Commands (inputs, list steps, logic, run_command)\n")
    from .commands import ACTIONS
    parts.append(
        'Every trigger slot takes a command JSON: `{"do": <action>, ...}`. Lines are '
        "physical 1-8; every index (list, input, output, sensor, schedule, logic, "
        "sequence, theme, profile, zone) is 0-based - List 1 is `list: 0`. DALI "
        "target: `address` 0-63, `group` 0-15 or `broadcast: true`; add "
        "`override: true` for the sensor-overriding variant. Call the "
        "`command_reference` tool for the fields of each action.\n")
    parts.append("Actions: " + ", ".join(f"`{a}`" for a in ACTIONS) + "\n")
    parts.append(
        "Latching inputs (PE cell, key switch, fire relay): `on_low` runs when the "
        "contact closes to ground, `on_high` when it opens. Momentary inputs: "
        "`on_low` = short press, `on_high` = long press (repeats while held).\n")
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
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(build_guide())
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
