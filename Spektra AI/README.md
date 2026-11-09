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
> **Tech:** Python MCP SDK + `edidio_control_py` engine (≥ 0.5.0, which provides
> the v2 event stream).
>
> Only need to *operate* lights (levels, scenes, effects) with no configuration
> writes? The control-only **[MCP Server (Lite)](../MCP%20Server/)** is a smaller,
> fixed tool surface.

## What it can do

**Discover / connect / inspect** (read-only, freely callable)
- `discover_controllers`, `connect_controller`, `connection_status`.
- `get_zone_details`, `list_zones`, `list_sequences`, `list_themes`, `list_alarms`,
  `get_calendar`, `whats_playing`, `whats_scheduled_next`, `get_time`,
  `device_capabilities`, `query_dmx_cache`.

**Author with a safety net** — every create is **preview → confirm**
- `preview_sequence` / `preview_theme` / `preview_schedule` / `preview_calendar`
  return a human preview **and a token**; nothing is written until `confirm(token)`.
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

**DALI** (Phase 4) — commission and configure control gear
- `dali_scan` (find gear + status), `dali_set_level`, `dali_identify` (blink),
  `dali_set_colour` (DT8 colour temperature / RGBWAF).
- `set_dali_line` (set a line to DALI + reboot), `commission_dali` (robust multi-pass
  addressing + memory-bank grouping into physical fixtures, with an expected-count
  report).
- `dali_add_to_group`, `dali_set_scenes`, `dali_set_fade_time`, `dali_query_groups`,
  `dali_recall_scene`.

**Live events + out-of-band notifications**
- `start_watching` / `recent_events` / `stop_watching` — subscribe to the controller's
  real-time event stream (inputs, sensors, DALI bus frames, triggers) on a dedicated
  connection. Auto-selects the firmware's event API (v2 `EventStreamMessage` on
  fw ≥ 1.4.0, legacy `EventMessage` below).
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

**SD card** (models with a card) — `sd_overview` (space, and each log folder's
state and size), `sd_list_files`, `sd_read_file`, `sd_download` (binary logs too),
`sd_search` (find lines in the newest log files, e.g. when an input fired, or
`ERROR`).

**Settings, names, Wi-Fi** — `get_device_settings` / `preview_device_settings` (name,
project, location, UTC offset, daylight saving, DALI polling and timing),
`get_names` / `preview_names` (names stored on the controller), `wifi_status` /
`preview_wifi_settings` (ADDICT V3).

**Capability guide** — MCP resource `edidio://capability-guide`, auto-generated from
the live protobuf descriptors so it never drifts from the firmware.

## Safety model

- **Persistent writes are preview → confirm.** The preview shows exactly what will be
  written (and a token); `confirm(token)` performs the write and reports the
  controller's acknowledgement.
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

## Testing

```bash
python -m pytest -q     # 196 tests, no controller required
```

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
│   ├── server.py            # MCP tools + capability-guide resource + preview/confirm
│   ├── tools_live.py        # MCP tools: health, log, live state/actions, settings, lists/IO/logic
│   ├── ops.py               # live operations in the current protocol (diagnostics, log, Wi-Fi, ...)
│   ├── v2.py                # requests/acks in the current proto (RejectReason, new messages)
│   ├── commands.py          # friendly command JSON <-> trigger dicts (mirrors SpektraPlus)
│   ├── device_log.py        # decode the controller's system log (mirrors SpektraPlus)
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
├── tools/build_alma.py      # example: generate a project from a functionality statement
├── CAPABILITY_GUIDE.md      # generated snapshot of the guide
└── tests/                   # 196 tests (stub clients + real-file fixtures)
```

### Fidelity notes (mirroring SpektraPlus)

- `.spektra` per-item field shapes follow `SpektraPlus/shared/src/types.ts`
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
