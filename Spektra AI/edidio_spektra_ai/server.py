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


def _new_token(messages, preview):
    token = secrets.token_hex(4)
    _pending[token] = {"messages": messages, "preview": preview}
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
    try:
        acks = await _controller.send_and_ack(pending["messages"])
    except Exception as err:  # noqa: BLE001
        return f"Error writing to controller: {err}"
    ok = all(a.get("ok") for a in acks)
    return (("Done. " if ok else "Completed with issues. ")
            + f"Controller responses: {acks}")


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


def main():
    logging.basicConfig(level=logging.INFO)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
