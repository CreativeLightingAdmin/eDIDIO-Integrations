# eDIDIO SpektraPlus - Capability Guide

Reference for authoring SpektraPlus **sequences**, **themes** and **schedules (alarms)** on a Control Freak eDIDIO controller. Generated from the live protobuf descriptors + curated notes, so field names and enum values match the device.

## Limits

- Sequences: index 0-143; up to 20 colours; title kept to 23 UTF-8 bytes (longer is cut on push); min 50 ms per step
- Themes: index 0-15; up to 20 colours; title kept to 27 UTF-8 bytes
- Schedules (alarms): index 0-8 (user)
- Lists: up to 255 steps; each step waits 0-65535 s before the next. Writing List 1 erases every list (Spektra AI rewrites the others for you)
- Firmware 1.6.3 refuses values it cannot store (INVALID_PARAMS + reason) instead of truncating them
- Zones: 0-9 (pre-configured; read details with `get_zone_details`)
- Colour channel values: 0-255

The device also reports exact counts via `device_capabilities`.

## Animation types (`type`)

- `0` - BLEND - smooth cross-fade between colours
- `1` - SIMPLE_CHASE - a block of colour runs along the fixtures
- `2` - SHADOW_CHASE - a dark gap runs along a lit line
- `3` - COMET - a bright head with a fading tail
- `4` - ROTATE - colours rotate around the fixtures (classic 'rotate' effect)
- `5` - TWINKLE - random sparkle
- `6` - BUILD_UP - fixtures fill up one by one
- `7` - CRASH - fixtures empty out
- `8` - FIREWORKS - bursts
- `9` - FIRE - flickering fire effect
- `10` - RAMP_UP - brightness ramps up
- `11` - RAMP_DOWN - brightness ramps down
- `12` - STATIC - all fixtures hold the colour(s)
- `13` - RADIAL_ROTATE - rotate from a centre point
- `14` - RADIAL_BUILD - build from a centre point
- `15` - PARTICLE_CANNON - particles fired along the line

## Timing units

- `0` - milliseconds
- `1` - seconds
- `2` - minutes
- `3` - hours

## Key message fields (from the protocol)

- **SpektraSequenceConfigMessage**: index#1, type#2, transition#3, fade_time_by_10ms#4, time_per_colour#5, time_per_colour_unit#6, time_per_step#7, time_per_step_unit#8, range#9, colour#10, is_randomised_type#11, random_types_mask#12, is_reverse_direction#13, is_cycle_direction#14, title#15, has_random_colour_order#16, colours#17, args#18
- **SpektraThemeConfigMessage**: index#1, colour#2, title#3, colours#4
- **AlarmMessage**: index#1, enabled#2, start_time#3, end_time#4, start_trigger#5, end_trigger#6, astro_start#7, astro_end#8, repeat#9, repeat_day_bitmask#10, repeat_month_bitmask#11, yearly#12, start_offset_is_before#13, end_offset_is_before#14
- **TriggerMessage**: type#1, zone#2, line_mask#3, target_index#4, value#5, query_index#6
- **SpektraSettingMessage** (zone): zone#1, start_address#2, line_or_universe_mask#3, protocol#4, number_of_lights#5, channels_per_light#6, channel_colours#7, unscheduled_behaviour#8, channel_mapping#9, line_addressing#10, zone_scale_factor#11

### Transition types

- `BLEND` = 0
- `SNAP` = 1
- `FADE_TO_BLACK` = 2

### Alarm repeat types

- `ALARM_NO_REPEAT` = 0
- `ALARM_REPEAT_DAILY` = 1
- `ALARM_REPEAT_WORK_DAY` = 2
- `ALARM_REPEAT_WEEKLY` = 3
- `ALARM_REPEAT_MONTHLY` = 4

### Alarm astro types

- `ALARM_NO_ASTRO` = 0
- `ALARM_SUNRUSE` = 1
- `ALARM_SUNSET` = 2

### Trigger types (schedules - subset)

- `SPEKTRA_START_SEQ` = 12
- `SPEKTRA_STOP_SEQ` = 13
- `SPEKTRA_THEME` = 14
- `SPEKTRA_STATIC` = 15
- `SPEKTRA_SCHEDULE` = 16
- `ALARM_ENABLE` = 49
- `ALARM_DISABLE` = 50
- `SPEKTRA_INTENSITY` = 70

### Ack result codes

- `DECODE_FAILED` = 0
- `INDEX_OUT_OF_BOUNDS` = 1
- `SUCCESS` = 5
- `INVALID_PARAMS` = 6
- `SLOTS_FULL` = 12
- `UNAUTHORISED` = 13
- `DEPRECATED` = 16

## Tools by task

Reads run at once; anything the controller stores is preview_* -> confirm(token)
and ends with a save. Indices are 0-based (List 1 = 0); replies show both.

- **Find / connect**: discover_controllers, connect_controller (TLS on 443),
  connection_status, device_capabilities, get_device_settings, list_zones,
  get_zone_details, query_dmx_cache.
- **Health and faults**: health_check, get_diagnostics, run_line_diagnostics,
  device_log, diagnose_controller_log (lights left on - from the controller's own
  log), preview_clear_device_log, sd_overview / sd_list_files / sd_read_file / sd_search / sd_download,
  sd_read_log (decodes the binary DALI bus and event logs: every frame, collisions,
  timeouts, sensor events; inputs, config changes, boots, connections),
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
  preview_logging, wifi_status / preview_wifi_settings (ADDICT),
  get_dmx_settings / preview_dmx_settings (timing, slots, 16-bit).
- **DALI**: dali_scan, dali_levels, commission_dali / preview_dali_commission, set_dali_line,
  dali_gear_settings / preview_dali_gear_settings (power-on, system failure, min/max,
  fade), dali_scene_levels / preview_dali_scene, dali_add_to_group,
  dali_remove_from_group, dali_set_scenes, dali_set_fade_time, dali_query_groups,
  dali_recall_scene, dali_set_level, dali_identify, dali_set_colour / dali_dt8_info (DT8),
  dali_devices / preview_dali_channel_order (multi-channel drivers in channel order).
  DALI-2 control devices: dali2_scan, dali2_device, preview_dali2_readdress,
  dali_find_duplicates, preview_dali2_instance (enable, report timer, hysteresis).
- **RDM** (DMX output line): rdm_discover, rdm_get, rdm_identify, preview_rdm_set.
- **.spektra files**: pull_spektra_file, preview_push_spektra (only the connected
  controller, only what changed), sync_status, summarize_spektra,
  validate_spektra, diff_spektra, migrate_spektra_to_v3, spektra_slot_changes
  (what changed since the last snapshot, from slot checksums).
- **Watch and notify**: start_watching / recent_events / stop_watching,
  notify_when (ready-made events), notify_on (raw conditions),
  list_notifications / clear_notifications.
- **Record while nobody is watching**: recorder_start (a background process that
  keeps logging events to disk after the chat ends), recorder_status,
  recorder_stop, recorded_events (search what it captured).

## Commands (inputs, list steps, logic, run_command)

Every trigger slot takes a command JSON: `{"do": <action>, ...}`. Lines are physical 1-8; every index (list, input, output, sensor, schedule, logic, sequence, theme, profile, zone) is 0-based - List 1 is `list: 0`. DALI target: `address` 0-63, `group` 0-15 or `broadcast: true`; add `override: true` for the sensor-overriding variant. Call the `command_reference` tool for the fields of each action.

Actions: `burnin_start`, `burnin_stop`, `dali_arc`, `dali_fade_down`, `dali_fade_long_press`, `dali_fade_up`, `dali_fade_up_with_min`, `dali_max`, `dali_min`, `dali_min_max_toggle`, `dali_off`, `dali_scene`, `dali_step_down`, `dali_step_up`, `dali_toggle`, `device_save`, `dmx`, `dmx_broadcast`, `dmx_zone_fade_down`, `dmx_zone_fade_up`, `input_disable`, `input_enable`, `list_start`, `list_start_looping`, `list_stop`, `logic`, `none`, `output_high`, `output_low`, `output_toggle`, `output_trigger`, `preset_code`, `profile`, `schedule_disable`, `schedule_enable`, `sensor_disable`, `sensor_mute`, `sensor_override`, `sensor_resume`, `sensor_unmute`, `sequence`, `sequence_stop`, `spektra_intensity`, `spektra_pause`, `spektra_resume`, `spektra_schedule`, `theme`, `user_level_recall`

Latching inputs (PE cell, key switch, fire relay): `on_low` runs when the contact closes to ground, `on_high` when it opens. Momentary inputs: `on_low` = short press, `on_high` = long press (repeats while held).

## How to author

**Sequences** (`create_sequence` / `preview_sequence`): pick a `type` (see the
Animation types table), give 1-20 `colours` (each an array of channel values
0-255, whose length must match the target zone's channels-per-light - read the
zone first with `get_zone_details`), and set timing. `time_per_step` controls the
animation speed (min 50 ms); `time_per_colour` controls how long each colour
shows; each has a matching `_unit` (0=ms,1=s,2=min,3=hr). `transition` blends
(0), snaps (1), or fades to black (2). Sequences auto-save to flash on the
device. Index 0-143.

**Themes** (`create_theme`): a static palette of 1-20 `colours` on an index
0-15. Colours repeat across fixtures if there are fewer colours than lights.

**Schedules** (`create_schedule`): an alarm with a `start_time` and a
`start_trigger`. To run sequence N at 5 PM daily: start_time = 17:00,
repeat = DAILY, trigger type = SPEKTRA_START_SEQ, target_index = N, zone = the
zone. Use SUNRISE/SUNSET astro types (with a before/after offset) for
astronomical schedules. Alarm index 0-8.

**Scheduled sequence** ("make a rotate and run it at 5 PM"): author the sequence
first (it saves), then create a schedule whose trigger targets that sequence
index. `preview_schedule` can do both in one preview.

**Calendar** (`preview_calendar`): assign a sequence or theme to specific days of
the year. Give `kind` ('sequence' or 'theme'), the `index` to run, and `days` (a
list of day numbers 1-366 and/or ISO dates like '2026-12-25'). Set `override:
true` to force it over the normal schedule. Read the current assignments any time
with `get_calendar`.

## Live playback (run something on a zone RIGHT NOW)
To play a stored sequence/theme immediately (not on a schedule), use
`play_sequence(zone, index)` / `play_theme(zone, index)`; `stop_zone(zone)` stops
playback and turns the output off. This is transient (no preview/confirm needed).
NOTE: a zone only produces physical output if it is patched to a line/universe
(its `line_or_universe_mask` is non-zero) - check with `list_zones` first, or the
command will succeed but nothing will be visible.

## Schedules & calendar  (READ THIS before scheduling seasonal content)
A schedule (alarm) fires an action at a time of day. The calendar decides WHICH
sequence/theme runs on WHICH day of the year.

**For any date-ranged or seasonal request** ("Christmas in December", "this week",
"over the holidays"), use the CALENDAR for the dates and keep the SCHEDULES daily:
  1. Author the sequence/theme.
  2. `preview_calendar` to assign it to those days (day numbers or ISO dates).
  3. Create DAILY start/stop schedules (repeat=daily, ALL months) where the START
     action is `start_calendar` (Start Calendar Event - plays whatever the calendar
     has for today) and the STOP action is `stop_sequence`.
Do NOT restrict the schedule's month/day bitmask to the season, and do NOT use a
`start_sequence` trigger tied to one sequence - that bypasses the calendar. Only
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
- `list_zones`, `list_sequences`, `list_themes` - what's configured on the device.
- `whats_playing` - the LIVE state: which sequence/theme each zone is playing now.
- `list_alarms`, `get_calendar` - the schedules and the full-year calendar.
- `whats_scheduled_next` - computes the soonest alarm that will fire and when.
- `get_time` - the controller's clock vs this computer's.

Note: zones have NO name/title on the controller (only a number + electrical
config); any friendly zone names live in the SpektraPlus app's project file.
Sequences and themes DO have a `title`.

## Colour format
Colours are **per-channel arrays of 0-255**, e.g. RGB `[255,0,0]` = red, RGBW
`[255,0,0,0]`. The number of channels must match the zone (`channels_per_light`).
Read the zone with `get_zone_details` if unsure.

## Safety
Authoring writes **persistent config**. Every create returns a preview + a token;
nothing is written until you call `confirm(token)`. Read existing slots
(`list_sequences`/`list_themes`/`list_alarms`) first to avoid overwriting.
