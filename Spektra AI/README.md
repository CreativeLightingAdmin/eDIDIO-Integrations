# Spektra AI

An **MCP server that lets an AI assistant manage the full lifecycle** of a Control
Freak **eDIDIO** lighting controller — inspect, author, configure, commission, watch
and troubleshoot — in plain language:

> *"Find eDIDIOs on the network."* → *"Connect to 192.168.1.50."* → *"Make a
> red-yellow-green rotate on zone 1 and run it at 5 PM daily."*
> *"Pull this controller into a .spektra file."* → *"Set inputs 0–6 to Group 4, all
> DALI scenes in steps of 10, fade 2.8 s."* → *"Let me know when the foyer sensor
> goes idle."*

> **Target:** the SpektraPlus authoring/configuration surface.
> **Tech:** Python MCP SDK + `edidio_control_py` engine (≥ 0.5.1: protocol 1.3.2
> and the full event stream).
>
> **New here?** The [user guide](docs/USER_GUIDE.md) covers installing, connecting
> an AI client, the ideas behind it, worked examples, the background recorder and
> the bench test.
>
> **Compatibility, what is verified on hardware, and what is still to do:** see
> [COMPATIBILITY.md](COMPATIBILITY.md). **Every tool, grouped by task:** the
> capability guide ([CAPABILITY_GUIDE.md](CAPABILITY_GUIDE.md)), which the assistant
> also reads as the `edidio://capability-guide` resource.
>
> Only need to *operate* lights (levels, scenes, effects) with no configuration
> writes? The control-only **[MCP Server (Lite)](../MCP%20Server/)** is a smaller,
> fixed tool surface.

## What it can do

**Discover / connect / inspect** (read-only, freely callable)
- `discover_controllers`, `connect_controller`, `connection_status`.
- `get_zone_details`, `list_zones`, `list_sequences`, `list_themes`, `list_alarms`,
  `get_calendar`, `whats_playing`, `whats_scheduled_next`, `get_time`,
  `device_capabilities`, `query_dmx_cache`, `get_diagnostics`.
- Play now: `play_sequence`, `play_theme`, `stop_zone`.

**Author with a safety net** — every create is **preview → confirm**
- `preview_sequence` / `preview_theme` / `preview_schedule` / `preview_calendar`
  return a human preview **and a token**; nothing is written until `confirm(token)`.
  `clear_schedule` empties a schedule slot.
  A schedule can run any command (start a list, change profile, recall a DALI
  scene, ...) at a time or sunrise/sunset, with an optional end command.

**`.spektra` project files** — the SpektraPlus project format, offline and live
- Offline: `summarize_spektra`, `validate_spektra`, `diff_spektra`,
  `migrate_spektra_to_v3` (reads legacy + v3, preserves unknown fields).
- Live: `pull_spektra_file` reads a controller's *entire* config (all sections +
  device info) into a SpektraPlus-openable file; `preview_push_spektra` → `confirm`
  writes a file's changes back (diff-based, only what changed).
- `sync_status` — hash-based SYNCED / UNSYNCED / DESYNCED per section vs the device,
  writing the v3 `syncData` ledger (mirrors SpektraPlus's own hashing).
- Generate a project from a spec: see `tools/build_alma.py` (builds a multi-controller
  project from a functionality statement, on the bundled controller template).

**DALI** — commission and configure control gear
- `dali_scan` (find gear + status), `dali_set_level`, `dali_identify` (blink),
  `dali_set_colour` (DT8 colour temperature / RGBWAF).
- `set_dali_line` (set a line to DALI + reboot), `commission_dali` (robust multi-pass
  addressing + memory-bank grouping into physical fixtures, with an expected-count
  report).
- `dali_gear_settings` / `preview_dali_gear_settings` (power-on, system-failure,
  min/max levels, fade time/rate, extended fade; read back after),
  `dali_scene_levels` / `preview_dali_scene` (store or remove a scene level, read back).
- `dali_add_to_group`, `dali_remove_from_group`, `dali_set_scenes`, `dali_set_fade_time`, `dali_query_groups`,
  `dali_recall_scene`.

**Live events + out-of-band notifications**
- `start_watching` / `recent_events` / `stop_watching` — subscribe to the controller's
  real-time event stream (inputs, sensors, DALI bus frames, triggers) on a dedicated
  connection. Auto-selects the firmware's event API (v2 `EventStreamMessage` on
  fw ≥ 1.4.0, legacy `EventMessage` below).
- `notify_when` — ready-made events: input pressed / closed / opened, sensor
  occupied / warning / idle, list started, schedule fired, config changed (with the
  client's IP), restart, client connected, network link down, Spektra started,
  DALI send errors.
- `recorder_start` / `recorder_status` / `recorder_stop` / `recorded_events` — a
  **background event recorder**: a separate process that keeps writing the
  controller's events (inputs, sensors, DALI frames, schedules, lists, config
  changes, connections) to daily JSON-lines files after the chat or the MCP server
  closes, and reconnects by itself. `recorded_events` searches what it captured
  (by kind, text, time, errors). The same recorder runs as a service with
  `edidio-spektra-recorder --host <ip> [--tls] [--name <name>]` (or
  `python -m edidio_spektra_ai.recorder`). Files go to `~/.spektra_ai/recordings`
  (or `SPEKTRA_AI_RECORDINGS`); day files older than `--keep-days` (30) are deleted.
- `notify_on` / `list_notifications` / `clear_notifications` — fire a notification
  (log / webhook / email) **out-of-band** when an event matches a condition
  (e.g. *"when the foyer sensor goes MOTION_IDLE"*), independent of the chat.

**Device clock / one-off control** — `get_time` / `set_time`, `send_dali`, `send_dmx`.

**Health and diagnostics** (eDIDIO and ADDICT; a property the device lacks is skipped)
- `health_check` — one report: temperature, clock / NTP / backup battery, Ethernet
  link and errors, task stacks, DALI bus power / shorts / gear online per DALI line,
  Wi-Fi (ADDICT), running lists, and recent restarts / crashes / watchdog resets.
- `get_diagnostics(kind)` — raw time, ethernet, memory, dali_status, storage,
  wifi_*, crash, counters (presses per input, list starts, schedule fires,
  reboots), connections, ... ; `run_line_diagnostics` (probes each line).
- `device_log` — the controller's own log (restart cause, crashes, NTP, link, and
  every trigger with its source when logging is on); `diagnose_controller_log` runs
  the "lights won't turn off" analysis straight on it; `preview_logging`,
  `preview_clear_device_log`.
- Offline: `parse_event_log`, `diagnose_stuck_on` (exported event-log files).

**Live state and actions** — `live_state` (profile, closed inputs, running lists,
alarm, sensors, burn-ins), `sensor_states`, `dali_levels` (actual level, on/off and
faults of every fitting on a DALI line), `run_command` (run any trigger now, as an
input or list would: DALI arc/command/scene, lists, outputs, Spektra, DMX, profile,
logic, ...), `change_profile`, `command_reference` (the action vocabulary).

**Live authoring** (preview → confirm, then DEVICE_SAVE) — straight to the controller,
no file needed
- `list_lists` / `preview_list` — timed command lists, up to 255 steps.
- `list_io` / `preview_input` (momentary short/long, or **latching** close/open - e.g.
  a PE cell or key switch, per profile) / `preview_output` (latching or pulse).
- `list_logic` / `preview_logic` — if DALI level / input / list running / occupancy /
  DMX present / weekday / month / alarm / DALI error, then A else B.

**Sensors and DALI-2 control devices** — `dali2_scan` / `dali2_device` (find sensors,
push buttons and rotaries in the 24-bit address space; per instance: type, enabled,
event scheme/filter, live occupancy and light level), `list_sensors`,
`preview_sensor` (control target, occupied / warning / dead-time timers, detect /
warning / idle actions, daylight harvesting setpoint, Leader/Follower co-op groups,
per profile), `preview_remove_sensor`, `sensor_command` (identify, mute, unmute,
override).

**DALI-2 commissioning** — `preview_dali2_readdress` (move or swap a control
device's address, checked after, and lists sensor slots still pointing at the old
one), `dali_find_duplicates`, `preview_dali2_instance` (enable an instance; report
timer, hysteresis, dead time, hold time).

**Multi-channel DALI drivers and zones** — `dali_devices` (addresses grouped into
physical devices from memory bank 0, with each channel's logical index),
`preview_dali_channel_order` (re-address a driver's channels into channel order,
e.g. RGBW on 0-3, checked after), `preview_zone` (colour zone editor; warns about
stored sequences/themes that use 255, which DALI treats as "no change").

**RDM** (on a DMX output line) — `rdm_discover` (fixtures with manufacturer, model,
label, start address, footprint and personalities), `rdm_identify`,
`preview_rdm_set` (start address, personality, label; read back after),
`rdm_get` (any parameter).

**Functionality statement** — `functionality_statement` writes what the lighting
control does in plain English (profiles and what switches them, schedules, inputs,
sensors, DALI-2 inputs, lists, logic, outputs, zones, Spektra content) from the
connected controller or a `.spektra` file, optionally saved as Markdown.

**DMX-to-DALI translations and burn-ins** — `list_translations` /
`preview_translation` (DMX input channels driving DALI addresses or groups, with
input blocking), `list_burnins` / `preview_burnin`; both are also in pull, push and
sync.

**Calendar check** — `check_calendar` compares the Spektra calendar with what it
should hold (dates or ranges in a year, sequence/theme by number or name) and lists
every day that differs; `strict` also lists days you did not mention.

**Live colour** — `set_zone_colour` puts a zone on a colour right now (`#RRGGBB` or
one level per channel) for trying colours while designing; DMX and DALI zones,
per address or by DALI group (`dali_group`), and DALI DT8 RGBWAF and xy zones;
`dali_set_colour` sets DT8 colour temperature (kelvin), xy or RGBWAF on a fitting, and
`dali_dt8_info` reads a DT8 driver's modes, live colour and out-of-range flags back. The controller itself always drives a
zone per address.

**Network and clock** — `preview_network_settings` (DHCP, static address, DNS;
optional restart that reconnects, by MAC on DHCP), `preview_clock_settings` (NTP,
poll period, UTC offset, daylight saving, location), `ntp_sync_now`.

**DMX settings** — `get_dmx_settings` / `preview_dmx_settings` (output timing; per
line slot count and 16-bit output; a custom slot mapping is kept).

**What changed on the controller** — `spektra_slot_changes` compares the
controller's per-slot checksums for sequences and themes with the last snapshot
(taken by the previous call or by `pull_spektra_file`; firmware 1.6.0+), without
reading every slot.

**Line types** — `preview_line_types` (DALI / DMX output / DMX input / empty per
line; reboots the controller and reconnects).

**SD card** (models with a card) — `sd_overview` (space, and each log folder's
state and size), `sd_list_files`, `sd_read_file`, `sd_download` (binary logs too),
`sd_search` (find lines in the newest log files, e.g. when an input fired, or
`ERROR`; binary logs are decoded first), `sd_read_log` (decodes the binary logs:
`logs/dali` - every DALI frame sent and received, with collisions, timeouts and
DALI-2 sensor events - and `logs/events` - inputs, sensors, lists, schedules,
config changes, boots, network connections; filter by text, errors or time; also
decodes a file already downloaded).

**Settings, names, Wi-Fi** — `get_device_settings` / `preview_device_settings` (name,
project, location, UTC offset, daylight saving, DALI polling and timing),
`get_names` / `preview_names` (names stored on the controller), `wifi_status` /
`preview_wifi_settings` (ADDICT V3).

**Capability guide** — MCP resource `edidio://capability-guide`, auto-generated from
the live protobuf descriptors so it never drifts from the firmware.

## Safety model

- **Persistent writes are preview → confirm.** The preview shows exactly what will be
  written (and a token); `confirm(token)` performs the write and reports the
  controller's acknowledgement. A preview is confirmed only on the connection it
  was made on, within 15 minutes.
- **Writes can be undone.** Before writing a sequence, theme, zone, schedule,
  sensor, inputs or outputs, `confirm` reads what it is about to overwrite and
  returns an undo token that puts it back exactly (the controller's own copy,
  re-sent). `undo_last_write` shows the most recent one. Other writes (DALI gear,
  lists, logic, line types) say they cannot be undone automatically.
- **Transient control is immediate** (dim / play / stop / one-off DALI).
- **DALI commissioning is destructive** (writes device addresses) and gated behind
  `preview_dali_commission` → `confirm`.
- **Pull/push is diff-based** — a push only writes items that differ (compared by
  the same canonical hash SpektraPlus uses), and the sync ledger + hashing detect
  out-of-band device changes (DESYNCED) rather than silently overwriting.
- **A push goes to the right controller** — only the file entry whose MAC matches the
  connected device is pushed; a changed model (reflashed 4-pole/6-pole) is refused.
- **Synced means saved** — every push and live edit ends with `DEVICE_SAVE`; the file
  is marked SYNCED only when every write and the save were acknowledged. A refused
  value (firmware 1.6.3 refuses what it cannot store) comes back with its reason.
- **Writing List 1 erases every list** on the controller (firmware behaviour), so the
  other lists are rewritten with it automatically.

## Setup

```bash
cd "Spektra AI"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py   # dev: shared engine
python -m edidio_spektra_ai                        # runs on stdio
```

### Use with Claude Desktop

Add to `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "spektra-ai": {
      "command": "python",
      "args": ["-m", "edidio_spektra_ai"],
      "cwd": "C:\\path\\to\\eDIDIO-Integrations\\Spektra AI"
    }
  }
}
```

Restart Claude Desktop; the Spektra AI tools + the capability guide appear.

### Use with Claude Code

```bash
python -m pip install -e .          # once, from this folder
claude mcp add spektra-ai -- python -m edidio_spektra_ai
```

### Load tools on demand (smaller chats)

Every tool definition goes to the model with every message: all 126 cost about
18,000 tokens a message. Set `SPEKTRA_AI_TOOLS=dynamic` and a chat starts with the
`core` group only (31 tools, about 2,800 tokens). The model loads the rest when a
job needs them, with `load_tools`:

| Group | Tools | What |
|---|---|---|
| core | 27 (+4) | connect, health, live state, play/stop, live colour, run_command, confirm |
| authoring | 12 | sequences, themes, zones, schedules, calendar, lists |
| devices | 25 | inputs, outputs, logic, sensors, translations, burn-ins, settings, network, Wi-Fi |
| dali | 29 | commissioning, groups, scenes, gear settings, DT8, DALI-2, RDM |
| logs | 25 | diagnostics, device and SD logs, events, notifications, recorder |
| projects | 8 | .spektra pull / sync / push / validate / diff, functionality statement |

- `tool_groups` lists them, `load_tools` / `unload_tools` add or drop one, and
  `run_tool` calls any tool by name.
- Loading a group tells the client its tool list changed
  (`notifications/tools/list_changed`, and the newer `subscriptions/listen` event).
- A client that doesn't refresh still works: `load_tools` returns the definitions,
  and `run_tool` calls them.
- A loaded group stays loaded for the rest of the chat.

In Claude Desktop:

```json
"spektra-ai": {
  "command": "python",
  "args": ["-m", "edidio_spektra_ai"],
  "env": {"SPEKTRA_AI_TOOLS": "dynamic"}
}
```

Without the variable (or with `all`) every tool is shown, as before.

## Testing

```bash
python -m pytest -q     # unit tests, no controller required
```

**Bench test against a real controller** (read-only unless `--writes`):

```bash
python tools/bench_test.py --host 192.168.1.50 --tls --report bench.md
python tools/bench_test.py --host 192.168.1.50 --tls --writes --address 0
```

It runs the tools and reports PASS / FAIL / SKIP for each. `--writes` adds a scene
store/remove and a power-on change/restore on one DALI fitting, each read back and
left as found. See the [user guide](docs/USER_GUIDE.md#10-the-bench-test).

**Sequence bench check** (writes; borrows one zone and one sequence slot, and puts
both back exactly):

```bash
python tools/sequence_bench.py --host 192.168.1.50 --tls --zone 3 --slot 36 --line 2
```

It makes the zone a DMX zone of 12 RGBW fixtures on the given DMX line (they will
light), then writes every sequence type and option through `preview_sequence`, and
compares the controller's DMX level cache, frame for frame, with the sequence model
(`sequence_model.py`) that the dry run in `preview_sequence` uses. Run it on each
firmware release: a change in the controller's sequence engine shows as a failure.

Everything is verified with **no controller** (stub clients + real-file fixtures).
`tests/test_sync_parity.py` pins hashes produced by SpektraPlus's own
sync hash (regenerate them when the app changes its hash pipeline). Live
behaviour (pull/push, commissioning, event stream, notifications, device log, health,
live authoring, ADDICT Wi-Fi) has also been verified against real hardware (eDIDIO
6-pole fw 1.6.3 over TLS, ADDICT V3 fw 3.9.3).

Connecting: plain TCP on port 23, or `use_tls=True` (port 443). eDIDIO TLS is TLS 1.2
with the fleet's RSA-1024 certificate, so Spektra AI uses a dedicated context for it
(as SpektraPlus does) instead of the system default, which fails the handshake.

## Architecture

```
Spektra AI/
├── edidio_spektra_ai/
│   ├── server.py            # MCP server, capability-guide resource, preview/confirm, core tools
│   ├── tools_live.py        # the other tools: health, log, live state, authoring, settings,
│   │                        #   sensors, DALI-2, RDM, SD, zones, calendar, statement, notify
│   ├── ops.py               # live operations in the current protocol (diagnostics, log, Wi-Fi, SD)
│   ├── v2.py                # requests/acks in the current proto (RejectReason, new messages)
│   ├── commands.py          # friendly command JSON <-> trigger dicts (mirrors SpektraPlus)
│   ├── device_log.py        # decode the controller's system log (mirrors SpektraPlus)
│   ├── dali24.py            # DALI-2 control devices (24-bit frames, instances)
│   ├── dali_units.py        # physical devices from memory bank 0; channel-order re-addressing
│   ├── rdm.py               # RDM discovery and parameters
│   ├── colour.py            # live zone colour (DMX and DALI)
│   ├── statement.py         # functionality statement from a project
│   ├── calendar_check.py    # Spektra calendar vs expected dates
│   ├── controller.py        # dynamic connect; reads/writes/commissioning/events
│   ├── authoring.py         # spec -> eDIDIO messages + preview (pure, tested)
│   ├── spektra_file.py      # load/save/summarize .spektra (legacy + v3)
│   ├── spektra_map.py       # .spektra <-> protobuf mappers (mirror SpektraPlus)
│   ├── spektra_validate.py  # validate config vs protocol enums/limits
│   ├── spektra_diff.py      # section-aware structural diff
│   ├── sync.py              # hash-based sync detection + v3 syncData ledger
│   ├── dali.py              # DALI query/commission/groups/scenes/fade/DT8
│   ├── event_stream.py      # live events (re-exports edidio_control_py.events)
│   ├── event_stream_v2.py   # v2 encode/decode names (re-exports the engine)
│   ├── event_log.py         # parse exported event logs + stuck-on diagnosis
│   ├── notify.py            # out-of-band notifications (log/webhook/email)
│   ├── capability_guide.py  # guide generated from protobuf descriptors
│   ├── discovery.py         # LAN discovery
│   └── templates/           # bundled controller template (device skeleton)
├── tools/build_example_project.py  # example: generate a project from a functionality statement
├── CAPABILITY_GUIDE.md      # generated snapshot of the guide (all tools by task)
├── COMPATIBILITY.md         # versions, firmware gates, verified features, to-do
└── tests/                   # 205 tests (stub clients + real-file fixtures)
```

### Fidelity notes (mirroring SpektraPlus)

- `.spektra` per-item field shapes follow SpektraPlus's own project types
  (the authoritative source) — not the on-disk template/as-built, which can carry
  legacy field names (e.g. inputs use `type`, not `isMomentaryOperation`).
- A valid file needs the full device skeleton (`supportedFeatures`, `network`,
  `dali`/`dmx`/`link`, `clock`/`location`), so pulls/generates start from the bundled
  controller template; each controller's `network.mac` must match its `edidios` key.
- Fixed-slot sections (schedules, lists, logicActions, burnIns, inputs, outputs)
  carry their full slot count (configured + disabled blanks).
- The sync hash follows SpektraPlus 1.3.0: fade time folded to
  ms, sequence titles cut to 23 UTF-8 bytes and themes to 27, NO_COMMAND triggers
  zeroed, DMX start clamp. Titles are cut the same way on push (a title over 27 bytes
  fails decode on the controller and the whole write is refused).
- Sequences and themes are read from the controller's slot manifest (firmware
  1.6.0+: only the used slots, all 144), falling back to every slot it reports.
- Lists read and write all steps (first 32 in `ListMessage`, the rest in
  `ExtendedListMessage` blocks); `state` is `list_state & 0x0F` with a separate
  `isShow`, as SpektraPlus reads it.
- After a push, stale per-item baselines (`itemSyncStates`) for the touched sections
  are dropped; SpektraPlus re-seeds them.
- The live event stream (v2 subscribe, legacy REGISTER, decode, reconnect) lives in
  the engine since `edidio_control_py` 0.5.0 (`edidio_control_py.events`, with the
  namespaced v2 proto in `edidio_control_py._v2`), so every gateway shares it.

## License

MIT
