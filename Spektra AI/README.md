# Spektra AI

An **MCP server that lets an AI assistant _author_ lighting** on a Control Freak
**eDIDIO** controller — not just trigger existing scenes. Describe what you want
in plain language and Spektra AI creates and saves **sequences**, **themes** and
**schedules**:

> *"Find eDIDIOs on the network."* → *"Connect to 192.168.1.50."* → *"Make a
> red-yellow-green rotate on zone 1 and schedule it to run at 5 PM every day."*

> **Target:** AI / next-gen control (the SpektraPlus authoring surface).
> **Tech:** Python MCP SDK + `edidio_control_py` 0.4.0 authoring builders.
> Named for the SpektraPlus feature set it drives.

## What it can do

- **Discover & connect** — `discover_controllers`, `connect_controller`,
  `connection_status`.
- **Inspect** (read-only, freely callable) — `get_zone_details` (protocol +
  channels-per-light, so colours match), `list_zones`, `list_sequences`,
  `list_themes`, `list_alarms`, `get_calendar` (whole year), `whats_playing` (live
  per-zone playback), `whats_scheduled_next`, `get_time` (controller clock vs this
  computer), `device_capabilities`, `query_dmx_cache`. Ask *"show me the zones"*,
  *"what's playing right now?"*, *"is the controller's clock right?"*.
- **Device clock** — `get_time` / `set_time` read and set the controller's RTC
  (set defaults to this computer's local time). Fixes schedules firing at the
  wrong time.
- **Calendar-driven schedules** — for time-of-day playback of the calendar, use
  two schedules: a `start_calendar` (Start Calendar Event) and a `stop_sequence`.
  `repeat: daily`/`weekdays` fills the day bitmask automatically.
- **Author with a safety net** — `preview_sequence` / `preview_theme` /
  `preview_schedule` / `preview_calendar` return a human preview **and a token**;
  nothing is written until you call `confirm(token)`. `preview_calendar` assigns a
  sequence/theme to specific days of the year (day numbers or ISO dates).
- **Live playback** — `play_sequence(zone, index)` / `play_theme(zone, index)` run
  a stored sequence/theme on a zone **right now**; `stop_zone(zone)` stops it. (A
  zone only shows output if it's patched to a line — check `list_zones` first.)
- **One-off control** — `send_dali`, `send_dmx`.
- **Capability guide** — exposed as the MCP resource `edidio://capability-guide`
  (animation types, enums, colour format, limits), **auto-generated from the live
  protocol descriptors** so it never drifts from the firmware.

## Safety model

Authoring writes **persistent configuration** to the controller. Every `create`
is a two-step **preview → confirm**: the preview shows exactly what will be
written (and returns a token); `confirm(token)` performs the write and reports the
controller's acknowledgement. The guide encourages reading existing slots and the
target zone first, so the model doesn't overwrite work or mismatch channel counts.

## Setup

```bash
cd "Spektra AI"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py   # dev: shared engine (0.4.0)
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
      "cwd": "F:\\My Documents\\GitHub\\eDIDIO_3rd_Party\\Spektra AI"
    }
  }
}
```

Restart Claude Desktop; the Spektra AI tools + the capability guide appear.
Discovery/connection are tools, so you connect at runtime (no fixed host).

## Example session

> **You:** Find eDIDIOs on the network.
> **AI:** *(calls `discover_controllers`)* Found "Foyer" at 192.168.1.50…
> **You:** Connect to it, then make a red→yellow→green rotate on zone 1 and run it
> at 5 PM daily.
> **AI:** *(connects; reads zone 1 → 3 channels; `preview_schedule` with an inline
> rotate sequence)* PREVIEW: Sequence 7 "RYG" type rotate, 3 colours…; Schedule 0:
> at 17:00, daily, run sequence 7 on zone 1. Confirm?
> **You:** Yes.
> **AI:** *(`confirm`)* Done. Controller responses: [SUCCESS, SUCCESS].

## Testing

```bash
python -m pytest -q
```

- `test_capability_guide.py` — the guide is generated from live descriptors and
  contains the key messages/enums/limits.
- `test_authoring.py` — the compiler turns specs into the correct eDIDIO messages
  (decoded + asserted), including *"5 PM daily → sequence N"* and the inline
  *author-then-schedule* case, plus validation errors.
- `test_server.py` — the MCP tools with a **stub client**: preview→confirm flow,
  zone/DMX read parsing, bad-token and not-connected handling, and the guide
  resource. (This caught a real bug: the shipped `AckMessage` has no `detail`
  field.)

Everything is verified with **no controller**. Live authoring is a hardware step
(via an MCP client) — the previews mean you can see exactly what will be written
first.

## Architecture

```
Spektra AI/
├── edidio_spektra_ai/
│   ├── server.py            # MCP tools + capability-guide resource + preview/confirm
│   ├── controller.py        # dynamic connect + authoring/read via request()
│   ├── authoring.py         # spec -> eDIDIO messages + preview (pure, tested)
│   ├── capability_guide.py  # guide generated from protobuf descriptors
│   └── discovery.py         # LAN discovery
├── CAPABILITY_GUIDE.md      # generated snapshot of the guide
└── tests/
```

Built on `edidio_control_py` **0.4.0**, which adds the authoring builders
(`create_spektra_sequence_message`, `create_spektra_theme_message`,
`create_alarm_message`) + read/query builders + a `request()` response decoder.

## Scope

Covers **sequences, themes and schedules (alarms)** — the most-changed
SpektraPlus features. Shows and calendar authoring are out of scope this round
(the builders/pattern extend to them cleanly when needed).

## License

MIT
