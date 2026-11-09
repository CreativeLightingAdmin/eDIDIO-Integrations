# Spektra AI user guide

Spektra AI lets an AI assistant (Claude, or any client that speaks the Model
Context Protocol) work with Control Freak **eDIDIO** lighting controllers and
**ADDICT** interfaces. You ask in plain language and the assistant uses Spektra AI's
tools to read the controller, change its configuration, control lights, commission
DALI, and track down faults.

This guide covers installing it, connecting a client, the ideas behind it, and worked
examples for the common jobs. For every tool grouped by task, see the
[capability guide](../CAPABILITY_GUIDE.md). For what each firmware supports and what
has been checked on hardware, see [COMPATIBILITY.md](../COMPATIBILITY.md).

---

## Contents

1. [Install](#1-install)
2. [Connect an AI client](#2-connect-an-ai-client)
3. [Ideas to know first](#3-ideas-to-know-first)
4. [First steps with a controller](#4-first-steps-with-a-controller)
5. [Everyday jobs](#5-everyday-jobs)
6. [DALI](#6-dali)
7. [Fault finding](#7-fault-finding)
8. [Logs, events and the background recorder](#8-logs-events-and-the-background-recorder)
9. [Projects and SpektraPlus](#9-projects-and-spektraplus)
10. [The bench test](#10-the-bench-test)
11. [Troubleshooting Spektra AI itself](#11-troubleshooting-spektra-ai-itself)

---

## 1. Install

You need Python 3.10 or newer on a computer on the same network as the controllers.

```bash
cd "Spektra AI"
python -m pip install -e .
```

This installs Spektra AI and its engine (`edidio_control_py` 0.5.1 or newer) from
PyPI. If PyPI doesn't have that engine version yet, install it from its source
folder first: `python -m pip install -e path/to/edidio_control_py`.

It adds two commands, and the bench test is a script in the project:

| Command | What it is |
|---|---|
| `edidio-spektra-ai` | the MCP server (the AI client starts this for you) |
| `edidio-spektra-recorder` | the background event recorder (section 8) |
| `python tools/bench_test.py` | the bench test (section 10) |

Check it runs:

```bash
python -m edidio_spektra_ai     # starts and waits on stdin; Ctrl+C to stop
python -m pytest -q             # the unit tests, no controller needed
```

## 2. Connect an AI client

The client starts the server itself, so you only tell it the command.

**Claude Desktop** - Settings → Developer → Edit Config, then add:

```json
{
  "mcpServers": {
    "spektra-ai": {
      "command": "python",
      "args": ["-m", "edidio_spektra_ai"]
    }
  }
}
```

Use the full path to `python` if more than one is installed (for example
`C:\\Users\\you\\AppData\\Local\\Programs\\Python\\Python312\\python.exe`).
Restart Claude Desktop. The Spektra AI tools then appear in the tools menu.

**Claude Code** - from any folder:

```bash
claude mcp add spektra-ai -- python -m edidio_spektra_ai
```

**Other MCP clients** - configure a stdio server with the command
`python -m edidio_spektra_ai`.

When the server starts, the assistant is told what Spektra AI does and is pointed at
the capability guide (the `edidio://capability-guide` resource), so you don't need
to explain the tools to it.

### Smaller chats: load tools on demand

The client sends every tool's definition to the model with **every message**. All
126 Spektra AI tools come to about 18,000 tokens a message, before you've typed
anything. That uses up your allowance and fills the conversation's working space
sooner.

To start each chat with just the essentials, add an `env` entry to the server's
config:

```json
"spektra-ai": {
  "command": "python",
  "args": ["-m", "edidio_spektra_ai"],
  "env": {"SPEKTRA_AI_TOOLS": "dynamic"}
}
```

A chat then starts with the **core** group: connect, health, live state, play/stop,
live colour, `run_command` and `confirm`. That's about 2,800 tokens. When a job
needs more, the assistant loads a group itself:

- **authoring** - sequences, themes, zones, schedules, calendar, lists
- **devices** - inputs, outputs, logic, sensors, settings, network, Wi-Fi
- **dali** - commissioning, groups, scenes, gear settings, DT8, DALI-2, RDM
- **logs** - diagnostics, device and SD logs, events, notifications, recorder
- **projects** - .spektra pull, sync, push, validate, diff

> **You:** Show me the gear settings on line 1.
>
> **Assistant:** *(load_tools dali, then dali_gear_settings)* Address 0: power-on 254,
> min 1, max 254, fade 0 s…

A loaded group stays for the rest of the chat; a new chat starts again from core. If
your client doesn't show newly loaded tools straight away, the assistant calls them
through `run_tool`, which works in any client. You can also ask directly: "load the
DALI tools".

Leave the setting out (or use `all`) to have every tool in every chat.

## 3. Ideas to know first

### Reading is free; storing needs your yes

- **Reads** (settings, levels, logs, scans) run straight away and change nothing.
- **Live actions** (dim a light, play a sequence, recall a scene) run straight away
  but aren't stored: the next schedule, input or power cycle can undo them.
- **Anything the controller stores** goes through *preview → confirm*. The assistant
  calls a `preview_*` tool, which shows exactly what would be written and returns a
  token. Nothing is written until `confirm(token)` is called. A good assistant
  shows you the preview and waits for your OK.

After a stored change, the controller is told to save (`DEVICE_SAVE`), and where the
controller can be read back, Spektra AI reads it back and reports what it found.
Firmware 1.6.3 refuses values it can't store, and the reason comes back in plain
words.

### Numbers start at 1 when you talk, 0 inside

People say "List 1" and "Input 18". The protocol counts from 0. Tool replies give
both where it matters ("List 1 (index 0)"). If something lands one off, say which
you meant.

### DALI addresses, groups and broadcast

- A fitting's **short address** is 0-63.
- A **group** is 0-15. Some tools write it `g2`; trigger targets use 64 + group.
- **Broadcast** reaches every fitting on the line. You can say `all`.
- A multi-channel driver (RGBW, for example) has one short address **per channel**.

### Profiles

A controller holds several profiles (sets of inputs, sensors and so on), and one is
active. Reads default to the active profile. Say which one you mean if it matters.

### Things that surprise people

- **Writing List 1 erases every list** on the controller. Spektra AI rewrites the
  other lists with it automatically, and the preview says so.
- **Writing sensor slot 0 restarts sensor programming.** Every sensor is muted
  briefly and comes back when the batch is committed.
- **Changing line types reboots the controller.** Spektra AI waits and reconnects.
- **Commissioning DALI writes addresses into the fittings.** It is always a preview
  first, and it re-reads every address afterwards.
- **The controller's clock is local time.** If it disagrees with your computer, check
  the UTC offset and daylight saving (`health_check` reports the difference).

## 4. First steps with a controller

> **You:** Find the controllers on the network.
>
> **Assistant:** *(discover_controllers)* Two answered: an eDIDIO S10 at
> 192.168.1.50 (firmware 1.6.3) and an ADDICT at 192.168.1.60 (3.9.3).

> **You:** Connect to the eDIDIO and give me a health check.
>
> **Assistant:** *(connect_controller, health_check)* Board temperature 40 °C, NTP
> working, Ethernet up at 100 Mb/s. One warning: a watchdog reset at 11:04 today. DALI
> status polling is off, so lamp failures aren't being monitored.

Connect with TLS (port 443) when the controller requires it: "connect to
192.168.1.50 using TLS". Plain TCP uses port 23.

Good next questions:

- "What's configured on it?" - zones, sequences, themes, schedules, lists, inputs,
  sensors (`list_*` tools).
- "Write me a functionality statement." - a readable description of everything the
  controller does, suitable for handover documents (`functionality_statement`).
- "What's playing right now, and what's scheduled next?"

## 5. Everyday jobs

### Sequences, themes and schedules

> **You:** Make a slow red-amber-white rotate on zone 1, call it "Foyer warm", and run
> it at sunset every day.
>
> **Assistant:** *(preview_sequence, preview_schedule)* Preview: sequence slot 4
> "Foyer warm", 3 colours, rotate, 20 s per step; schedule 2 at sunset, daily, plays
> sequence 4 on zone 1. Confirm?
>
> **You:** Yes.

Themes (static colour sets) work the same way. Names are limited to what the
controller stores (23 bytes for a sequence, 27 for a theme); longer names are
shortened and the preview shows the result.

`check_calendar` compares the calendar against what you expect ("Christmas theme
from 1 to 26 December") and lists the differences.

### Inputs, outputs and logic

> **You:** Input 18 is a PE cell. Make it latching: closed turns group 2 on, open
> turns it off.
>
> **Assistant:** *(preview_input)* Preview: input 18 (index 17), latching; on close →
> DALI group 2 to max; on open → group 2 off. Confirm?

Outputs can be latching or momentary. Logic rules compare a state (a list running, an
input, a level) and run a command. `command_reference` lists every command the
controller understands, and `run_command` runs one now.

### Lists

Lists are step-by-step programs. "Make list 3: group 1 to 50 %, wait 10 s, group 1
off", then confirm. Remember that writing list 1 rewrites them all.

### Sensors

`list_sensors` and `sensor_states` show how sensors are set up and what they see.
`preview_sensor` sets one up (occupancy, light-level harvesting, timings).
`sensor_command` overrides, mutes or resumes one.

### Live colour

> **You:** Set zone 2 to warm orange.
>
> **Assistant:** *(set_zone_colour)* Sent. Zone 2 is DALI DT8 RGBWAF at address 0.
> The driver reports red 255, green 120, blue 0.

This works for DMX zones, DALI zones (per address or by group) and DALI DT8 zones
(RGBWAF and colour coordinates). It isn't stored. Note that DALI is slow, so DALI
Spektra sequences suit slow changes.

### Settings, network, clock, Wi-Fi

`get_device_settings` reads names, location, clock, NTP, network, line types and
DALI/DMX timing. Writing them uses `preview_device_settings`,
`preview_network_settings`, `preview_clock_settings`, `preview_line_types` and (ADDICT)
`preview_wifi_settings`. A network change can move the controller to a new address;
the preview warns you.

## 6. DALI

### Look before you touch

| Ask | Tool |
|---|---|
| "What's on line 1?" | `dali_scan` |
| "Which addresses are one physical driver?" | `dali_devices` (memory bank: GTIN, serial, channel index) |
| "What are the stored settings?" | `dali_gear_settings` (power-on, system failure, min/max, fades) |
| "Which scenes is each fitting in?" | `dali_scene_levels` |
| "What colour is the DT8 driver showing?" | `dali_dt8_info` |
| "Any DALI-2 sensors or buttons?" | `dali2_scan`, `dali2_device` |
| "Any duplicate addresses?" | `dali_find_duplicates` |

### Commissioning

> **You:** Commission line 1. There should be 4 fittings.
>
> **Assistant:** *(preview_dali_commission)* Preview: address every fitting on
> line 1 (new gear only; existing addresses kept), expecting 4 channels. Confirm?
>
> **You:** Yes.
>
> **Assistant:** Done in 1 pass: 4 fittings at addresses 0-3, each verified.

Use `readdress` to start from scratch (every fitting gets a new address). For an
RGBW driver, `preview_dali_channel_order` puts its channels on consecutive addresses
in channel order (red, green, blue, white), using the channel index from the
driver's memory bank.

### Gear settings and scenes

> **You:** Fitting 0 should come on at 40 % after a power cut and fade over about
> 3 seconds.
>
> **Assistant:** *(preview_dali_gear_settings)* Preview: address 0, power-on level
> 102, fade time 2.8 s (the nearest standard time). Confirm? I'll read it back after.

`preview_dali_scene` stores or removes a scene level, and `dali_recall_scene` plays
it. Groups: `dali_add_to_group` and `dali_remove_from_group`. All of these are read
back after writing.

### DALI-2 control devices

Sensors, push buttons and rotaries have their own address space. `dali2_scan` finds
them, `preview_dali2_readdress` moves one, and `preview_dali2_instance` sets an
instance up (event filter, scheme, enable).

### RDM (DMX)

`rdm_discover` finds RDM fittings on a DMX line, `rdm_get` reads a parameter,
`rdm_identify` flashes one, and `preview_rdm_set` sets its DMX start address.

## 7. Fault finding

Start broad, then narrow down:

1. **`health_check`** - temperature, clock and NTP, Ethernet, DALI bus power and
   shorts, restarts and watchdog resets, running lists.
2. **`run_line_diagnostics`** - probes each line.
3. **`device_log`** and **`diagnose_controller_log`** - the controller's own record
   of triggers, including "why are these lights on?".
4. **The SD card logs** (section 8) - every DALI frame and event, kept for days.
5. **The live event stream** - watch it happen.

> **You:** The foyer lights came on at 3 am. Why?
>
> **Assistant:** *(diagnose_controller_log)* At 03:02:11 schedule 5 ran "group 4 to
> max". It's an astro schedule with a sunrise offset of -3 h, which puts it at 3 am
> in winter.

> **You:** Is anything wrong on the DALI bus?
>
> **Assistant:** *(sd_read_log logs/dali, errors_only)* Since 09:31 there have been two
> receive errors (partial frames) every 5 seconds on line 1, and none before. What
> was connected around then?

## 8. Logs, events and the background recorder

### SD card logs (models with a card)

`sd_overview` shows the card and each log folder: whether it's recording, its size
budget and how much it holds.

- **Text logs** (`logs/sys`, `logs/trig`, `logs/network` and others):
  `sd_read_file` reads the end of a file, `sd_search` finds lines.
- **Binary logs**: `sd_read_log` decodes them.
  - `logs/dali` - every DALI frame sent and received, with its status
    (collision, timeout, no echo) and the command in words, including DALI-2 sensor
    events.
  - `logs/events` - inputs, sensors, lists, schedules, config changes (and which
    computer made them), boots with the reset cause, network connections, Spektra
    starts and stops.

  You can filter by text, errors only, or a time window ("since 2026-11-09 14:00").
  `local_file` decodes a log you already downloaded (with `sd_download`, or from
  SpektraPlus).

Spektra AI picks the file the controller is writing now from `logs/LOGMETA.DAT`,
because file dates follow the controller clock and file numbers wrap at 10000. If the
controller says it is writing a file that isn't on the card, the tools tell you:
that category has stopped reaching the card.

### Watching live

`start_watching` subscribes to the controller's events while the session is open, and
`recent_events` shows them. `notify_when` / `notify_on` raise a notification when
something specific happens: an input pressed, a sensor going idle, a config change, a
restart, a DALI send failing. A notification can go to the log, a webhook (which sends
the event to that service) or email.

### The background recorder

Watching stops when the chat ends. To keep a record (overnight, over a weekend, while
waiting for an intermittent fault), start the recorder:

> **You:** Record everything this controller does until I say stop. Call it "foyer".
>
> **Assistant:** *(recorder_start)* Recorder "foyer" started for 192.168.1.50:
> recording.

It is a separate process, so it keeps going after the chat or the AI client closes,
and it reconnects by itself if the controller reboots or the network drops. Later:

> **You:** Did anything fail overnight?
>
> **Assistant:** *(recorded_events foyer, errors_only, since yesterday 18:00)*
> 3 events: two DALI collisions on line 2 at 22:14, and the connection was lost from
> 02:00 to 02:03 (the controller restarted, cause software).

- `recorder_status` lists recorders, whether they're running, and how much they hold.
- `recorder_stop` stops one. Its files are kept.
- Files are in `~/.spektra_ai/recordings/<name>/`, one JSON-lines file per day.
  Set `SPEKTRA_AI_RECORDINGS` to put them elsewhere. Day files older than 30 days are
  deleted (`keep_days` changes that).
- `[recorder]` lines mark when it started, connected, lost the connection and
  stopped, so any gap is visible.
- The recorder needs firmware 1.4.0 or newer, and it uses one of the controller's
  client connections while it runs.

**As a service.** The same recorder can run without any AI client:

```bash
edidio-spektra-recorder --host 192.168.1.50 --tls --name foyer
```

- **Windows:** create a Task Scheduler task that runs this "at startup", whether or
  not a user is logged on.
- **Linux:** a systemd unit with `ExecStart=` set to this command and
  `Restart=always`.
- **macOS:** a launchd job with `RunAtLoad` and `KeepAlive`.

`recorded_events` reads its files the same way.

## 9. Projects and SpektraPlus

A `.spektra` file is a SpektraPlus project. Spektra AI reads and writes it the same
way SpektraPlus does, including its sync check:

- `pull_spektra_file` copies a controller's configuration into a file.
- `summarize_spektra`, `validate_spektra` and `diff_spektra` inspect and compare
  files.
- `sync_status` compares a file with a controller, section by section:
  - **SYNCED** - the same;
  - **UNSYNCED** - you changed the file, ready to push;
  - **DESYNCED** - the controller was changed by someone else.
- `preview_push_spektra` writes only what differs, to the controller whose MAC
  address matches the file, and refuses if the hardware model changed.

> **You:** Pull the foyer controller into foyer.spektra, change sequence 4's speed
> to 10 s a step, and push it back.
>
> **Assistant:** *(pull_spektra_file, edits the file, preview_push_spektra)* Push
> preview: 1 item differs (sequence 4); 1 write plus save. Confirm?

`spektra_slot_changes` is a fast way to see which sequences and themes changed on
the controller since the last look (firmware 1.6.0+).

## 10. The bench test

`tools/bench_test.py` runs the tools against a real controller and reports each one
as PASS, FAIL or SKIP. Use it after updating firmware, Spektra AI or the engine, or to
check a new controller model.

```bash
python tools/bench_test.py --host 192.168.1.50 --tls --report bench.md
```

**By default nothing is written.** It covers:

- the connection, settings, health and diagnostics, and the device log;
- every configuration list;
- a project pull, then validation and a sync check (a fresh pull must be SYNCED),
  then a functionality statement;
- a DALI scan, device identities, gear settings, scenes, DT8 and DALI-2 on
  `--dali-line`;
- the SD card and its decoded logs;
- the live event stream, which must show the test's own DALI query.

**`--writes`** adds two reversible writes on one fitting (`--address`, default 0),
each read back and then put back as it was:

- store a level in a scene the fitting doesn't use, then remove it;
- change the power-on level, then restore it.

The test checks that the fitting ends up exactly as it started.

Other options:

- `--dali-line 0` skips DALI.
- `--events 0` skips the event stream.
- `-v` prints more of each output.
- `--report` writes a Markdown file with every check and its full output.

The script exits with 0 when nothing failed and 1 otherwise, so it can run in a
script.

SKIP means the controller doesn't have that feature. For example, an ADDICT has no
device log, DALI status cache or SD card.

## 11. Troubleshooting Spektra AI itself

| Symptom | What to check |
|---|---|
| The tools don't appear in the client | The `python` in the client config is the one Spektra AI is installed in. Run `python -m edidio_spektra_ai` yourself to see any error. |
| Can't connect | Ping the controller. Try TLS (port 443) and plain TCP (port 23). Another app holding every client connection gives NO_SLOT in the controller's network log. |
| TLS handshake fails | Spektra AI uses the TLS 1.2 settings eDIDIO needs. Make sure nothing (a proxy, antivirus) intercepts the connection. |
| "Receive operation timed out" on an ADDICT | ADDICT on Wi-Fi sometimes leaves a request unanswered for several seconds. Reads are retried automatically; run the request again if one still fails. |
| "Not supported by this controller" | The model or firmware doesn't have the feature. See COMPATIBILITY.md. |
| Sync shows DESYNCED straight after a push | Something else changed the controller, or the push wasn't confirmed. Run `sync_status` again and look at which items differ. |
| The recorder says "retrying" | It can't reach the controller. The error says why, and it keeps trying (up to every 2 minutes). |
| Times look wrong | The controller clock is local time: check its UTC offset and daylight-saving setting (`health_check`). |
