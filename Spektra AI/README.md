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
> **Tech:** Python MCP SDK + `edidio_control_py` engine + a namespaced copy of the
> current eDS10 protobuf for the v2 event stream.

## What it can do

**Discover / connect / inspect** (read-only, freely callable)
- `discover_controllers`, `connect_controller`, `connection_status`.
- `get_zone_details`, `list_zones`, `list_sequences`, `list_themes`, `list_alarms`,
  `get_calendar`, `whats_playing`, `whats_scheduled_next`, `get_time`,
  `device_capabilities`, `query_dmx_cache`.

**Author with a safety net** — every create is **preview → confirm**
- `preview_sequence` / `preview_theme` / `preview_schedule` / `preview_calendar`
  return a human preview **and a token**; nothing is written until `confirm(token)`.

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

**Diagnostics** — `parse_event_log`, `diagnose_stuck_on` (parse exported event logs
and reconstruct DALI on/off to find "lights won't turn off").

**Capability guide** — MCP resource `edidio://capability-guide`, auto-generated from
the live protobuf descriptors so it never drifts from the firmware.

## Safety model

- **Persistent writes are preview → confirm.** The preview shows exactly what will be
  written (and a token); `confirm(token)` performs the write and reports the
  controller's acknowledgement.
- **Transient control is immediate** (dim / play / stop / one-off DALI).
- **DALI commissioning is destructive** (writes device addresses) and gated behind
  `preview_dali_commission` → `confirm`.
- **Pull/push is diff-based** — a push only writes sections that differ, and the
  sync ledger + hashing detect out-of-band device changes (DESYNCED) rather than
  silently overwriting.

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
python -m pytest -q     # 156 tests, no controller required
```

Everything is verified with **no controller** (stub clients + real-file fixtures).
Live behaviour (pull/push, commissioning, event stream, notifications) has also been
verified against real hardware.

## Architecture

```
Spektra AI/
├── edidio_spektra_ai/
│   ├── server.py            # MCP tools + capability-guide resource + preview/confirm
│   ├── controller.py        # dynamic connect; reads/writes/commissioning/events
│   ├── authoring.py         # spec -> eDIDIO messages + preview (pure, tested)
│   ├── spektra_file.py      # load/save/summarize .spektra (legacy + v3)
│   ├── spektra_map.py       # .spektra <-> protobuf mappers (mirror SpektraPlus)
│   ├── spektra_validate.py  # validate config vs protocol enums/limits
│   ├── spektra_diff.py      # section-aware structural diff
│   ├── sync.py              # hash-based sync detection + v3 syncData ledger
│   ├── dali.py              # DALI query/commission/groups/scenes/fade/DT8
│   ├── event_stream.py      # live event subscription (firmware-gated)
│   ├── event_stream_v2.py   # EventStreamMessage (tag 77) encode/decode
│   ├── event_log.py         # parse exported event logs + stuck-on diagnosis
│   ├── notify.py            # out-of-band notifications (log/webhook/email)
│   ├── capability_guide.py  # guide generated from protobuf descriptors
│   ├── discovery.py         # LAN discovery
│   ├── templates/           # bundled controller template (device skeleton)
│   └── _v2/                 # namespaced current-proto module (event stream v2)
├── tools/build_alma.py      # example: generate a project from a functionality statement
├── CAPABILITY_GUIDE.md      # generated snapshot of the guide
└── tests/                   # 156 tests (stub clients + real-file fixtures)
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
- The v2 event proto is compiled to `_v2/eDS10_v2_pb2.py` (package `edidiov2`) from the
  current `.proto` so it coexists with the engine's older protobuf. Regenerate with
  `protoc --python_out=edidio_spektra_ai/_v2 --proto_path=edidio_spektra_ai/_v2 eDS10_v2.proto`.

## License

MIT
