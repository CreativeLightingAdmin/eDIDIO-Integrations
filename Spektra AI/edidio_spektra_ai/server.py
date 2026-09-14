"""Spektra AI MCP server.

Tools for an AI assistant to discover/connect to an eDIDIO controller, inspect it
(zones, existing sequences/themes/alarms, DMX cache, capabilities), and **author**
sequences / themes / schedules with a preview -> confirm safety flow. The
capability guide is exposed as an MCP resource so the model reasons with accurate
enums, ranges and limits.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime

from mcp.server.mcpserver import MCPServer

from .authoring import (
    SpecError,
    compile_calendar,
    compile_schedule,
    compile_sequence,
    compile_theme,
)
from .capability_guide import build_guide
from .controller import SpektraController, summarize_discovery
from . import dali, event_log, notify, sync
from .spektra_diff import diff, format_diff
from .spektra_file import SpektraFileError, load_spektra, summarize
from .spektra_validate import format_issues, validate

_LOGGER = logging.getLogger(__name__)

server = MCPServer(
    name="Spektra AI",
    instructions=(
        "Author and control Control Freak eDIDIO SpektraPlus lighting. You can "
        "find controllers on the network and connect, inspect zones/sequences/"
        "themes/schedules, and CREATE sequences, themes and schedules from natural "
        "language. Authoring writes persistent config, so create_* tools return a "
        "preview and a token; call confirm(token) to actually write. Read the "
        "'edidio://capability-guide' resource for the exact animation types, enums, "
        "colour format and limits, and read a zone with get_zone_details before "
        "authoring so colours match its channels-per-light."
    ),
)

_controller = SpektraController()
_pending: dict[str, dict] = {}  # token -> {"messages": [...], "preview": str}
_log_channel = notify.LogChannel()  # shared safe channel for in-process notifications


def _new_token(messages, preview, on_success=None):
    token = secrets.token_hex(4)
    _pending[token] = {"messages": messages, "preview": preview,
                       "on_success": on_success}
    return token


async def _do(action, ok):
    try:
        await action()
        return ok
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Spektra AI tool error: %s", err)
        return f"Error: {err}"


# --- capability guide resource ---------------------------------------------

@server.resource("edidio://capability-guide")
def capability_guide() -> str:
    """The eDIDIO SpektraPlus capability guide (animation types, enums, limits)."""
    return build_guide()


# --- discovery / connection -------------------------------------------------

@server.tool()
async def discover_controllers() -> str:
    """Find eDIDIO controllers on the local network (UDP broadcast)."""
    try:
        devices = summarize_discovery(_controller.discover())
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    if not devices:
        return "No eDIDIO controllers found on the local network."
    lines = [f"- {d['name']} at {d['ip']} (MAC {d['mac']}, TLS {d['tls']}, lines: {d['lines']})"
             for d in devices]
    return "Found controllers:\n" + "\n".join(lines)


@server.tool()
async def connect_controller(host: str, port: int = 23, use_tls: bool = False) -> str:
    """Connect to an eDIDIO controller by IP/hostname (port 23 TCP, 443 TLS)."""
    return await _do(lambda: _controller.connect(host, port, use_tls),
                     f"Connected to {host}.")


@server.tool()
async def connection_status() -> str:
    """Report whether Spektra AI is connected, and to which controller."""
    return f"Connected to {_controller.host}." if _controller.connected else "Not connected."


# --- read / inspect ---------------------------------------------------------

@server.tool()
async def get_zone_details(zone: int) -> str:
    """Read a zone's configuration (protocol, channels-per-light, fixtures). Use
    this before authoring so colours match the zone's channel count."""
    try:
        return str(await _controller.read_zone(zone))
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"


@server.tool()
async def list_zones() -> str:
    """Show the configured zones (protocol, channels-per-light, fixtures)."""
    try:
        zones = await _controller.list_zones()
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    if not zones:
        return "No zones are configured."
    return "Zones:\n" + "\n".join(
        f"- zone {z['zone']}: protocol {z['protocol']}, "
        f"{z['number_of_lights']} light(s) x {z['channels_per_light']} channel(s)"
        for z in zones)


@server.tool()
async def list_sequences() -> str:
    """Show the sequences stored on the controller (index, title, animation type)."""
    try:
        seqs = await _controller.list_sequences()
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    if not seqs:
        return "No sequences are stored."
    return "Sequences:\n" + "\n".join(
        f"- [{s['index']}] {s['title'] or '(untitled)'} - type {s['type']}, "
        f"{s['colours']} colour(s)" for s in seqs)


@server.tool()
async def list_themes() -> str:
    """Show the themes (static colour palettes) stored on the controller."""
    try:
        themes = await _controller.list_themes()
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    if not themes:
        return "No themes are stored."
    return "Themes:\n" + "\n".join(
        f"- [{t['index']}] {t['title'] or '(untitled)'} - {t['colours']} colour(s)"
        for t in themes)


@server.tool()
async def list_alarms() -> str:
    """List the schedules (alarms) currently stored on the controller."""
    try:
        return str(await _controller.read_alarms())
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"


@server.tool()
async def clear_schedule(index: int) -> str:
    """Disable and clear a schedule (alarm) slot (0-8), freeing it for reuse. Use
    this to remove a schedule or make room for a one-off."""
    try:
        ack = await _controller.clear_schedule(index)
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    return _fmt_ack(f"Cleared schedule {index}", ack)


@server.tool()
async def get_calendar() -> str:
    """Show the SpektraCalendar: which sequence/theme is assigned to each day."""
    try:
        days = await _controller.read_calendar()
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    if not days:
        return "No calendar assignments are set."
    return "Calendar assignments:\n" + "\n".join(
        f"- day {d['day_index'] + 1}: {d['kind']} {d['target_index']}" for d in days)


@server.tool()
async def whats_playing() -> str:
    """Show what each zone is currently playing right now (live state from the
    controller): which sequence/theme, and how far through it is."""
    try:
        live = await _controller.read_live()
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    if not live:
        return "Nothing is currently playing on any zone."
    return "Currently playing:\n" + "\n".join(
        f"- zone {p['zone']}: {p['state']} {p['kind']} {p['index']} "
        f"\"{p['title'] or '(untitled)'}\" (step {p['step']})" for p in live)


@server.tool()
async def whats_scheduled_next() -> str:
    """Work out the next schedule (alarm) that will fire, and when."""
    try:
        result = await _controller.whats_next()
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    if result.get("next") is None:
        return result.get("message", "Nothing is scheduled.")
    return f"Next: {result['next']} - fires in {result['in']} (at {result['when']})."


@server.tool()
async def get_time() -> str:
    """Read the controller's clock and compare it to this computer's time. Use this
    when the schedules seem to fire at the wrong time. If it's off, offer to fix it
    with set_time."""
    try:
        info = await _controller.get_device_time()
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    if "error" in info:
        return f"Couldn't read the controller time: {info['error']}"
    drift = info["drift_seconds"]
    mins = abs(drift) // 60
    if abs(drift) < 60:
        off = "in sync with this computer"
    else:
        direction = "behind" if drift > 0 else "ahead of"
        off = f"about {mins} min {direction} this computer"
    return (f"Controller time: {info['device']}\nThis computer: {info['computer']}\n"
            f"The controller is {off}. Ask me to set the controller's time to fix it.")


@server.tool()
async def set_time(iso: str = "") -> str:
    """Set the controller's clock. Defaults to this computer's local time; or pass
    an ISO string "YYYY-MM-DD HH:MM:SS". This changes the device RTC — confirm with
    the user before calling."""
    try:
        when = datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return f'Could not parse "{iso}". Use "YYYY-MM-DD HH:MM:SS".'
    try:
        res = await _controller.set_device_time(when)
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    return _fmt_ack(f"Set controller time to {res['set_to']}", res["ack"])


@server.tool()
async def device_capabilities() -> str:
    """Query the controller's supported counts (sequences/themes/alarms/zones)."""
    try:
        return str(await _controller.read_capabilities())
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"


@server.tool()
async def query_dmx_cache(line: int, page: int = 0) -> str:
    """Read the current cached DMX levels for a universe/line (64 per page)."""
    try:
        return str(await _controller.read_dmx_cache(line, page))
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"


# --- authoring: preview -> confirm -----------------------------------------

def _preview(compile_fn, spec):
    try:
        messages, preview = compile_fn(spec)
    except SpecError as err:
        return f"Invalid spec: {err}"
    token = _new_token(messages, preview)
    return (f"PREVIEW (nothing written yet):\n{preview}\n\n"
            f"Call confirm(token=\"{token}\") to write this to the controller.")


@server.tool()
async def preview_sequence(spec: dict) -> str:
    """Preview a sequence to author. spec: {index, type (e.g. 'rotate'), colours
    [[r,g,b],...], title, time_per_step_ms, fade_ms}. fade_ms cross-fades between
    steps (0 = snap; must be <= time_per_step_ms). Returns a preview + confirm token."""
    return _preview(compile_sequence, spec)


@server.tool()
async def preview_theme(spec: dict) -> str:
    """Preview a theme to author. spec: {index, colours [[r,g,b],...], title}."""
    return _preview(compile_theme, spec)


@server.tool()
async def preview_schedule(spec: dict) -> str:
    """Preview a schedule. spec: {index, time "HH:MM" OR astro 'sunset'/'sunrise'
    with optional offset "H:MM" (negative = before, e.g. "-0:30"), repeat
    'daily'/'weekdays'/..., optional months [1-12], and either trigger
    {type,zone,target_index} or an inline 'sequence'/'theme'. trigger type can be
    'start_calendar' (Start Calendar Event), 'start_sequence', 'theme',
    'stop_sequence'. Returns a preview + confirm token."""
    return _preview(compile_schedule, spec)


@server.tool()
async def preview_calendar(spec: dict) -> str:
    """Preview assigning a sequence/theme to calendar days. spec: {kind
    'sequence'/'theme', index, days [day-numbers 1-366 or dates 'YYYY-MM-DD'],
    override?}. Returns a preview + confirm token."""
    return _preview(compile_calendar, spec)


@server.tool()
async def confirm(token: str) -> str:
    """Write a previewed sequence/theme/schedule to the controller. Requires the
    token from a preview_* tool. Returns the controller's acknowledgement(s)."""
    pending = _pending.pop(token, None)
    if pending is None:
        return "Unknown or already-used token. Generate a fresh preview first."
    # Special action: DALI commissioning runs a multi-step addressing loop.
    if pending.get("dali_commission"):
        try:
            res = await pending["dali_commission"]()
        except Exception as err:  # noqa: BLE001
            return f"Error during commissioning: {err}"
        if res.get("ok"):
            return (f"Commissioning done: addressed {res['addressed']} device(s) "
                    f"at {res.get('addresses', [])}.")
        return f"Commissioning failed after {res.get('addressed', 0)}: {res.get('error')}"
    try:
        acks = await _controller.send_and_ack(pending["messages"])
    except Exception as err:  # noqa: BLE001
        return f"Error writing to controller: {err}"
    ok = all(a.get("ok") for a in acks)
    note = ""
    if ok and pending.get("on_success"):
        try:
            note = pending["on_success"]() or ""
        except Exception as err:  # noqa: BLE001 — a write succeeded; ledger is best-effort
            note = f" (sync ledger not updated: {err})"
    return (("Done. " if ok else "Completed with issues. ")
            + f"Controller responses: {acks}" + note)


# --- live playback on a zone ------------------------------------------------

def _fmt_ack(label, ack):
    ok = ack.get("ok")
    return f"{label}: {ack.get('code')}." if ok else f"{label} failed: {ack.get('code')}."


@server.tool()
async def play_sequence(zone: int, index: int) -> str:
    """Start a stored sequence playing on a zone RIGHT NOW (live, no schedule).
    Use list_sequences to find the index. This is the 'run it now' command."""
    try:
        ack = await _controller.play_sequence(zone, index)
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    return _fmt_ack(f"Playing sequence {index} on zone {zone}", ack)


@server.tool()
async def play_theme(zone: int, index: int) -> str:
    """Apply a stored theme on a zone RIGHT NOW (live). Use list_themes for the index."""
    try:
        ack = await _controller.play_theme(zone, index)
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    return _fmt_ack(f"Applied theme {index} on zone {zone}", ack)


@server.tool()
async def stop_zone(zone: int) -> str:
    """Stop SpektraPlus playback on a zone and turn its output off."""
    try:
        ack = await _controller.stop_zone(zone)
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    return _fmt_ack(f"Stopped zone {zone}", ack)


# --- individual control -----------------------------------------------------

@server.tool()
async def send_dali(line: int, address: int, level: int) -> str:
    """Send a one-off DALI arc level (0-254) to an address on a line (not zone-based)."""
    return await _do(lambda: _controller.send_dali(1 << (line - 1), address, level),
                     f"Set line {line} address {address} to {level}.")


@server.tool()
async def send_dmx(line: int, channel: int, levels: list) -> str:
    """Send one-off DMX levels (list of 0-255) starting at a channel on a line."""
    return await _do(lambda: _controller.send_dmx(1 << (line - 1), channel, levels),
                     f"Set line {line} DMX from channel {channel}: {levels}.")


# --- offline .spektra project files + event logs (no controller needed) ------

def _read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


@server.tool()
async def summarize_spektra(path: str) -> str:
    """Summarise a SpektraPlus .spektra project FILE (offline, no controller): per-
    eDIDIO config counts (sequences/themes/schedules/lists/logic/zones and per-profile
    inputs/sensors/…) and its sync state. Reads both legacy and current (v3) files."""
    try:
        return summarize(load_spektra(path))
    except SpektraFileError as err:
        return f"Error: {err}"


@server.tool()
async def validate_spektra(path: str) -> str:
    """Validate a .spektra FILE against protocol enums and firmware limits (offline).
    Flags indices out of range, colour values out of 0-255, oversized colour sets,
    over-length titles, and any embedded command with an unknown TriggerType."""
    try:
        return format_issues(validate(load_spektra(path)))
    except SpektraFileError as err:
        return f"Error: {err}"


@server.tool()
async def diff_spektra(path_a: str, path_b: str) -> str:
    """Structural diff between two .spektra FILES (a = old, b = new): what was added,
    removed or changed per eDIDIO / section / slot. Offline. Useful for 'what changed
    between these two saves?' and for previewing a delta before syncing."""
    try:
        return format_diff(diff(load_spektra(path_a), load_spektra(path_b)))
    except SpektraFileError as err:
        return f"Error: {err}"


@server.tool()
async def migrate_spektra_to_v3(path: str, out_path: str = "") -> str:
    """Read a (possibly legacy) .spektra FILE, migrate its sync metadata to the current
    v3 format, and save. Config sections and unknown fields are preserved. Writes to
    out_path, or overwrites the input if out_path is omitted. Offline."""
    try:
        proj = load_spektra(path)
        changed = proj.migrate_to_v3()
        dest = proj.save(out_path or path)
        prefix = "Migrated to v3 and saved" if changed else "Already current; saved"
        return f"{prefix} to {dest}."
    except SpektraFileError as err:
        return f"Error: {err}"


@server.tool()
async def pull_spektra_file(host: str, out_path: str, port: int = 23,
                           use_tls: bool = False) -> str:
    """Pull a CONNECTED controller's live Spektra config into a .spektra FILE, then
    summarise it. Connects to `host` if not already connected. Reads sequences,
    themes, zones and schedules and writes a v3 .spektra to `out_path` — so the
    offline summarize/validate/diff tools work on a live device. (Profiles/lists/
    logic are not pulled yet.)"""
    from .spektra_file import SpektraProject
    try:
        if not (_controller.connected and _controller.host == host):
            await _controller.connect(host, port, use_tls)
        raw = await _controller.pull_project()
    except Exception as err:  # noqa: BLE001
        return f"Error pulling from {host}: {err}"
    try:
        proj = SpektraProject(raw=raw)
        dest = proj.save(out_path)
    except Exception as err:  # noqa: BLE001
        return f"Pulled, but failed to save: {err}"
    return f"Pulled live config from {host} to {dest}.\n\n{summarize(proj)}"


@server.tool()
async def preview_push_spektra(path: str, host: str = "", port: int = 23,
                              use_tls: bool = False,
                              sections: str = "sequences,themes") -> str:
    """Preview pushing a .spektra FILE's config to a controller (file -> device).
    Connects to `host` if given (else uses the current connection), diffs the file's
    selected `sections` against the live device, and returns a preview of only the
    added/changed items PLUS a confirm token. Nothing is written until you call
    confirm(token). Safe: unchanged items are skipped. DALI channel values are
    auto-capped to 254 on DALI devices.

    `sections` is comma-separated; supported: sequences, themes, zones, schedules,
    inputs, outputs, logicActions, lists, sensors, daliInputs. Inputs/outputs/sensors/
    daliInputs write per profile (whole profile if anything differs); logicActions
    writes all logic together. (Zones change electrical/patch config — include them
    deliberately. Clearing ALL sensors from a profile isn't supported yet.)"""
    from .spektra_file import SpektraFileError, load_spektra
    try:
        proj = load_spektra(path)
        if host and not (_controller.connected and _controller.host == host):
            await _controller.connect(host, port, use_tls)
        secs = tuple(s.strip() for s in sections.split(",") if s.strip())
        messages, summary, is_dali = await _controller.build_push_messages(proj, secs)
    except SpektraFileError as err:
        return f"Error: {err}"
    except Exception as err:  # noqa: BLE001
        return f"Error building push: {err}"
    if not messages:
        return "Nothing to push: the device already matches the file for those sections."

    def _on_success():
        # After a successful push the device matches the file for these sections;
        # record them SYNCED in the file's v3 syncData ledger and save.
        for mac in proj.macs:
            sync.mark_synced(proj, mac, list(secs))
        proj.save(path)
        return f" Sync ledger updated and saved to {path}."

    token = _new_token(messages, "\n".join(summary), on_success=_on_success)
    dev = "DALI (values capped to 254)" if is_dali else "DMX"
    body = "\n".join(f"  - {s}" for s in summary)
    return (f"PREVIEW - would write {len(messages)} item(s) to {_controller.host} "
            f"[{dev}] (nothing written yet):\n{body}\n\n"
            f'Call confirm(token="{token}") to write this to the controller.')


@server.tool()
async def sync_status(path: str, host: str = "", port: int = 23,
                      use_tls: bool = False) -> str:
    """Compare a .spektra FILE against a live controller and report per-section sync
    state: SYNCED / UNSYNCED (local edits to push) / DESYNCED (device changed out-of-
    band since the file's last sync). Connects to `host` if given. Read-only — writes
    nothing to the device or the file. Use before pushing to see what will change."""
    from .spektra_file import load_spektra as _load
    try:
        proj = _load(path)
        if host and not (_controller.connected and _controller.host == host):
            await _controller.connect(host, port, use_tls)
        live = (await _controller.pull_project())["edidios"]
    except SpektraFileError as err:
        return f"Error: {err}"
    except Exception as err:  # noqa: BLE001
        return f"Error reading controller: {err}"
    return sync.format_status(sync.compute_status(proj, live))


@server.tool()
async def start_watching(host: str = "", port: int = 23, use_tls: bool = False,
                         categories: str = "") -> str:
    """Start watching a controller's LIVE events (inputs, sensors, triggers, DALI) on
    a dedicated connection. Connects to `host` if given. `categories` is optional and
    comma-separated: inputs, sensors, triggers, dali_command, dali_arc, dali_inputs,
    dmx_changed, dali_24_frame (default: inputs, sensors, triggers, dali_command).
    Events are buffered — poll them with recent_events. Read-only (never writes)."""
    from .event_stream import DEFAULT_CATEGORIES
    try:
        if host and not (_controller.connected and _controller.host == host):
            await _controller.connect(host, port, use_tls)
        cats = ([c.strip() for c in categories.split(",") if c.strip()]
                or list(DEFAULT_CATEGORIES))
        active = await _controller.start_events(cats)
    except Exception as err:  # noqa: BLE001
        return f"Error starting watch: {err}"
    return (f"Watching {_controller.host} for: {', '.join(active)}. "
            "Poll with recent_events. (Events appear only when the device is active.)")


@server.tool()
async def stop_watching() -> str:
    """Stop watching live events and close the event-stream connection."""
    try:
        await _controller.stop_events()
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    return "Stopped watching live events."


@server.tool()
async def recent_events(since_seq: int = 0, limit: int = 50) -> str:
    """Return live events captured since start_watching. Pass `since_seq` (the last
    seq you saw) to get only newer events — poll this repeatedly to follow activity.
    Each event has a monotonic `seq`, a `kind` (sensor/trigger/input/dali_*), and
    decoded fields. Empty means nothing has happened on the device yet."""
    info = _controller.recent_events(since_seq, limit)
    if not info["watching"]:
        return "Not watching. Call start_watching first."
    events = info["events"]
    if not events:
        return (f"No new events (watching {', '.join(info.get('categories', []))}; "
                f"last_seq {info['last_seq']}).")
    lines = [f"{len(events)} event(s) (last_seq {info['last_seq']}):"]
    for e in events:
        detail = ", ".join(f"{k}={v}" for k, v in e.items()
                           if k not in ("seq", "at", "event", "kind"))
        lines.append(f"  [{e['seq']}] {e.get('kind', e['event'])}: {detail}")
    return "\n".join(lines)


@server.tool()
async def notify_on(condition: dict, channel: str = "log", label: str = "",
                    webhook_url: str = "", host: str = "", one_shot: bool = True) -> str:
    """Send an OUT-OF-BAND notification when a live event matches `condition` (fires
    independently of this chat). `condition` matches decoded event fields, e.g.
    {"kind":"sensor","motion":"MOTION_IDLE","index":2} = "when sensor 2 goes out of
    occupancy", or {"kind":"trigger","type":"SPEKTRA_START_SEQ"}. Channels: "log"
    (default, recorded in-process — see list_notifications/delivered), "webhook" (needs
    webhook_url; POSTs the event as JSON — sends data to an external service), "email"
    (needs SMTP env config). Starts watching if not already. `one_shot` fires once then
    disarms."""
    try:
        if host and not (_controller.connected and _controller.host == host):
            await _controller.connect(host)
        if _controller._events is None or not _controller._events.running:
            await _controller.start_events()
        chan = notify.make_channel(channel, log_channel=_log_channel,
                                   webhook_url=webhook_url)
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    n = _controller.notifications.register(condition, chan, label=label,
                                          one_shot=one_shot)
    return (f"Notification #{n.id} armed on {_controller.host} "
            f"[{channel}]: {condition}. It will fire out-of-band when matched.")


@server.tool()
async def list_notifications() -> str:
    """List armed/fired out-of-band notifications, and any 'log' channel deliveries."""
    items = _controller.notifications.list()
    lines = []
    if items:
        lines.append("Notifications:")
        for n in items:
            state = "armed" if n.armed else "disarmed"
            fired = f", fired {n.fired_count}x (last {n.last_fired})" if n.fired_count else ""
            lines.append(f"  #{n.id} [{state}] {n.channel.name}: {n.condition}"
                         f"{' - ' + n.label if n.label else ''}{fired}")
    else:
        lines.append("No notifications registered.")
    if _log_channel.delivered:
        lines.append("\nDelivered (log channel):")
        for d in _log_channel.delivered[-10:]:
            lines.append(f"  {d['at']} - {d['subject']}: {d['payload'].get('event', {})}")
    return "\n".join(lines)


@server.tool()
async def clear_notifications(notif_id: int = 0) -> str:
    """Remove a notification by id, or all of them when notif_id is 0 (the default)."""
    n = _controller.notifications.clear(notif_id or None)
    return f"Cleared {n} notification(s)."


@server.tool()
async def parse_event_log(path: str) -> str:
    """Parse an exported eDIDIO event-log FILE (.txt or a log .spektra) and summarise
    it: counts by event type and source, and the time span covered. Offline."""
    try:
        return event_log.summarize_log(event_log.parse_log(_read_text(path)))
    except OSError as err:
        return f"Error: {err}"


@server.tool()
async def diagnose_stuck_on(path: str) -> str:
    """Diagnose 'lights won't turn off' from an event-log FILE: reconstruct DALI Arc
    on/off per line + group/address and report any target left on with no matching OFF,
    with the time it was last turned on and suggested next checks. Offline."""
    try:
        return event_log.analyze_stuck_on(event_log.parse_log(_read_text(path)))
    except OSError as err:
        return f"Error: {err}"


# --- DALI commissioning / query / colour (Phase 4) --------------------------

@server.tool()
async def dali_scan(line: int) -> str:
    """Scan a DALI line (1-4) for present control gear: queries each short address
    0-63 and reports which reply, with decoded status (lamp on/failure, etc.).
    Read-only. Use this to see what's on a line before commissioning or control."""
    try:
        found = await _controller.dali_scan(line)
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    if not found:
        return f"No DALI devices replied on line {line}."
    lines = [f"{len(found)} device(s) on line {line}:"]
    for d in found:
        flags = [k for k, v in d["status"].items() if v] or ["ok"]
        lines.append(f"  - address {d['address']}: {', '.join(flags)}")
    return "\n".join(lines)


@server.tool()
async def dali_set_level(line: int, address: int, level: int) -> str:
    """Set a DALI arc level (0-254) on a line (1-4) / short address (0-63, or 255 for
    broadcast). Immediate, transient control (not persistent config)."""
    try:
        await _controller.dali_set_level(line, address, level)
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    return f"Set line {line} address {address} to level {level}."


@server.tool()
async def dali_identify(line: int, address: int, blinks: int = 3) -> str:
    """Identify a fixture by blinking it (max/off) so an installer can spot it."""
    try:
        await _controller.dali_identify(line, address, blinks)
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    return f"Blinked line {line} address {address} {blinks} time(s)."


@server.tool()
async def dali_set_colour(line: int, address: int, mirek: int = 0,
                          rgb: list | None = None, waf: list | None = None,
                          arc_level: int = 254) -> str:
    """Set DT8 colour on a DALI fixture. Give `mirek` for colour temperature (mireds =
    1,000,000/Kelvin, e.g. 370≈2700K warm, 250=4000K, 154≈6500K cool), OR `rgb`
    ([r,g,b]) and optional `waf` ([w,a,f]) for RGBWAF. Transient control."""
    try:
        if rgb is not None:
            acks = await _controller.dali_rgbwaf(line, address, rgb, waf or [0, 0, 0],
                                                 arc_level)
        elif mirek:
            acks = await _controller.dali_colour_temperature(line, address, mirek)
        else:
            return "Provide either mirek (colour temperature) or rgb (RGBWAF)."
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    ok = all(a.get("ok") for a in acks)
    return (("Set colour. " if ok else "Completed with issues. ")
            + f"Controller responses: {acks}")


@server.tool()
async def preview_dali_commission(line: int, readdress: bool = False,
                                  is24bit: bool = False) -> str:
    """Preview DALI commissioning (addressing) on a line, then confirm to run it.
    This WRITES short addresses to control gear. `readdress`=True clears ALL existing
    addresses and re-addresses everything (destructive); the default addresses only
    NEW/unaddressed gear. Returns a confirm token; nothing runs until confirm(token)."""
    mode = ("RE-ADDRESS ALL (clears every existing short address, then re-addresses "
            "all gear)" if readdress else "address only NEW/unaddressed gear")
    preview = f"DALI commission line {line}: {mode}. {'24-bit' if is24bit else '16-bit'}."

    async def _run():
        res = await _controller.dali_commission(line, readdress=readdress,
                                                is24bit=is24bit)
        return res

    token = _new_token([], preview, on_success=None)
    _pending[token]["dali_commission"] = _run
    return (f"PREVIEW (nothing written yet):\n{preview}\n\nThis is destructive to DALI "
            f'addresses. Call confirm(token="{token}") to run commissioning.')


@server.tool()
async def set_dali_line(line: int, reboot: bool = True) -> str:
    """Configure a controller line (1-4) as DALI and (by default) reboot so it takes
    effect, waiting for the device to come back. Use before commissioning DALI gear on
    a line that's currently DMX/empty. This reboots the controller."""
    try:
        lines = await _controller.read_line_types()
        while len(lines) < line:
            lines.append(0)
        lines[line - 1] = 1  # LINE_DALI
        ack = await _controller.set_line_types(lines)
        if not ack.get("ok"):
            return f"Failed to set line {line} to DALI: {ack.get('code')}"
        if not reboot:
            return f"Line {line} set to DALI. Reboot required for it to take effect."
        await _controller.reboot()
        back = await _controller.wait_for_reboot()
        return (f"Line {line} set to DALI and controller rebooted"
                + (" - back online." if back else " - did NOT come back in time."))
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"


@server.tool()
async def commission_dali(line: int, expected_channels: int = 0,
                          expected_devices: int = 0, readdress: bool = True) -> str:
    """Commission (address) all DALI gear on a line, then report back — the "address
    my fixtures" flow. Runs a multi-pass addressing sequence (robust to bus
    collisions), then groups the addressed channels into physical devices by serial
    number. Give `expected_channels` and/or `expected_devices` to get a match check.
    `readdress`=True (default) clears existing addresses first (clean slate).
    WRITES device addresses."""
    from . import dali as _dali
    try:
        res = await _controller.dali_commission(line, readdress=readdress, passes=8)
        if not res.get("ok"):
            return f"Commissioning failed: {res.get('error')}"
        groups = await _controller.dali_group_devices(line)
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    return _dali.format_commission_report(
        res["total_addressed"], groups, expected_channels, expected_devices)


def _parse_addresses(spec: str) -> list:
    """Parse an address spec like "0-6" or "0,3,5" or "0-6,9,12-15" into a list."""
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


@server.tool()
async def dali_add_to_group(line: int, addresses: str, group: int) -> str:
    """Add DALI short addresses to a DALI group (0-15) so they can be controlled
    together. `addresses` is a range/list spec, e.g. "0-6", "7,8,9", "0-3,10-12".
    Writes group membership to the gear (sent twice, paced). Verifies via read-back."""
    try:
        addrs = _parse_addresses(addresses)
        await _controller.dali_add_to_group(line, addrs, group)
        # Verify membership (retried queries).
        confirmed = [a for a in addrs if group in await _controller.dali_query_groups(line, a)]
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    missing = [a for a in addrs if a not in confirmed]
    msg = f"Added {confirmed} to group {group}."
    if missing:
        msg += f" NOT confirmed for {missing} (retry or check the gear)."
    return msg


@server.tool()
async def dali_set_scenes(line: int, step: int = 10, addresses: str = "") -> str:
    """Set DALI scenes 0-15 to multiples of `step` (scene N = N*step, capped at 254) on
    all gear on a line, or only `addresses` (e.g. "0-6") if given. E.g. step=10 =>
    scene 1=10 ... scene 15=150. Writes scene levels to the gear (paced)."""
    try:
        addrs = _parse_addresses(addresses) if addresses else None
        written = await _controller.dali_set_all_scenes(line, step=step, addresses=addrs)
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    where = f"addresses {addrs}" if addrs else "all gear"
    return (f"Set scenes on {where}: " + ", ".join(f"S{s}={lv}" for s, lv in written))


@server.tool()
async def dali_set_fade_time(line: int, seconds: float, addresses: str = "") -> str:
    """Set the DALI fade time to the nearest standard step for `seconds` (e.g. 2.8 ->
    2.83s) on all gear on a line, or only `addresses` if given. Writes to the gear."""
    try:
        addrs = _parse_addresses(addresses) if addresses else None
        code = await _controller.dali_set_fade_time(line, seconds, addresses=addrs)
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    from . import dali as _d
    where = f"addresses {addrs}" if addrs else "all gear"
    return f"Set fade time on {where} to code {code} ({_d.FADE_TIME_SECONDS[code]}s)."


@server.tool()
async def dali_query_groups(line: int, address: int) -> str:
    """Read which DALI groups (0-15) a gear (line 1-4, short address 0-63) belongs to.
    Read-only; retries so a busy-bus miss doesn't report false-empty."""
    try:
        groups = await _controller.dali_query_groups(line, address)
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    return (f"Line {line} address {address} is in group(s): {groups}"
            if groups else f"Line {line} address {address} is in no groups.")


@server.tool()
async def dali_recall_scene(line: int, scene: int, group: int = -1,
                            address: int = -1) -> str:
    """Recall a stored DALI scene (0-15) — on a whole group (set `group` 0-15), a single
    address (set `address`), or broadcast to the line (leave both unset). Transient."""
    try:
        if group >= 0:
            await _controller._client.recall_dali_scene_on_group(
                _controller._next_id(), dali.line_mask(line), group, scene)
            target = f"group {group}"
        elif address >= 0:
            await _controller._client.send_dali_command(
                _controller._next_id(), dali.line_mask(line), address,
                16 + scene)  # DALI_RECALL_SCENE_0 = 16
            target = f"address {address}"
        else:
            await _controller._client.recall_dali_scene(
                _controller._next_id(), dali.line_mask(line), scene)
            target = "broadcast"
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    return f"Recalled scene {scene} on {target} (line {line})."


def main():
    logging.basicConfig(level=logging.INFO)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
