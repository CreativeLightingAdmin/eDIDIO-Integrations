"""Tool groups loaded on demand, so a chat carries only the tools it needs.

Every tool definition is sent to the model with every message, so all 126 tools cost
about 18,000 tokens per message before anything is said. With

    SPEKTRA_AI_TOOLS=dynamic

the server starts with the `core` group (connect, health, live state, play/stop,
colour, run_command, confirm) plus four small tools:

    tool_groups()          what each group covers and whether it is loaded
    load_tools(group)      add a group (also returns its tool definitions)
    unload_tools(group)    drop a group
    run_tool(name, args)   call any tool by name (loads its group if needed)

Loading a group tells the client its tool list changed (both the older
notifications/tools/list_changed message and the newer subscriptions/listen
event). A client that refreshes then shows the group's tools natively. A client
that does not still works: load_tools returns the definitions as text and
run_tool calls them. A loaded group stays loaded for the rest of the session.

The default (SPEKTRA_AI_TOOLS unset or "all") shows every tool, as before.
"""

from __future__ import annotations

import json
import logging
import os

from mcp.server.mcpserver import Context

_LOGGER = logging.getLogger(__name__)

GROUPS: dict[str, dict] = {
    "core": {
        "about": "connect and discover, health check, live state, what is playing, "
                 "play/stop sequences and themes, live colour and levels, run_command, "
                 "confirm (always loaded)",
        "tools": [
            "discover_controllers", "connect_controller", "connection_status",
            "device_capabilities", "health_check", "get_device_settings", "get_time",
            "live_state", "sensor_states", "whats_playing", "whats_scheduled_next",
            "list_zones", "get_zone_details", "list_sequences", "list_themes",
            "play_sequence", "play_theme", "stop_zone", "set_zone_colour", "send_dali",
            "send_dmx", "dali_levels", "query_dmx_cache", "run_command",
            "command_reference", "change_profile", "confirm",
        ],
    },
    "authoring": {
        "about": "create and change Spektra sequences, themes, zones, schedules, the "
                 "calendar and lists",
        "tools": [
            "preview_sequence", "preview_theme", "preview_zone", "preview_schedule",
            "list_alarms", "clear_schedule", "preview_calendar", "get_calendar",
            "check_calendar", "list_lists", "preview_list", "spektra_slot_changes",
        ],
    },
    "devices": {
        "about": "inputs, outputs, logic, sensors, DMX-to-DALI translations, burn-ins, "
                 "names, device / network / clock / Wi-Fi settings, line types, DMX "
                 "settings",
        "tools": [
            "list_io", "preview_input", "preview_output", "list_logic", "preview_logic",
            "list_sensors", "preview_sensor", "preview_remove_sensor", "sensor_command",
            "list_translations", "preview_translation", "list_burnins", "preview_burnin",
            "get_names", "preview_names", "preview_device_settings",
            "preview_network_settings", "preview_clock_settings", "ntp_sync_now",
            "set_time", "wifi_status", "preview_wifi_settings", "preview_line_types",
            "get_dmx_settings", "preview_dmx_settings",
        ],
    },
    "dali": {
        "about": "DALI scan, commissioning, addressing and channel order, groups, scenes, "
                 "gear settings, fades, DT8 colour, DALI-2 sensors and buttons, RDM",
        "tools": [
            "dali_scan", "dali_devices", "dali_set_level", "dali_identify",
            "dali_set_colour", "dali_dt8_info", "preview_dali_commission",
            "commission_dali", "set_dali_line", "preview_dali_channel_order",
            "dali_find_duplicates", "dali_add_to_group", "dali_remove_from_group",
            "dali_query_groups", "dali_set_scenes", "dali_recall_scene",
            "dali_scene_levels", "preview_dali_scene", "dali_set_fade_time",
            "dali_gear_settings", "preview_dali_gear_settings", "dali2_scan",
            "dali2_device", "preview_dali2_readdress", "preview_dali2_instance",
            "rdm_discover", "rdm_get", "rdm_identify", "preview_rdm_set",
        ],
    },
    "logs": {
        "about": "fault finding: diagnostics, the device log, SD card logs (text and "
                 "decoded DALI / event logs), live event watching, notifications, the "
                 "background recorder",
        "tools": [
            "get_diagnostics", "run_line_diagnostics", "device_log",
            "diagnose_controller_log", "preview_logging", "preview_clear_device_log",
            "sd_overview", "sd_list_files", "sd_read_file", "sd_read_log", "sd_search",
            "sd_download", "start_watching", "stop_watching", "recent_events",
            "notify_when", "notify_on", "list_notifications", "clear_notifications",
            "parse_event_log", "diagnose_stuck_on", "recorder_start", "recorder_status",
            "recorder_stop", "recorded_events",
        ],
    },
    "projects": {
        "about": ".spektra project files: pull from a controller, sync status, push, "
                 "summarise, validate, diff, migrate, functionality statement",
        "tools": [
            "pull_spektra_file", "sync_status", "preview_push_spektra",
            "summarize_spektra", "validate_spektra", "diff_spektra",
            "migrate_spektra_to_v3", "functionality_statement",
        ],
    },
}
ALWAYS = "core"
META_TOOLS = ("tool_groups", "load_tools", "unload_tools", "run_tool")

GROUP_OF = {t: g for g, spec in GROUPS.items() for t in spec["tools"]}

INSTRUCTIONS = (
    " Tools come in groups to keep each chat small: only 'core' is loaded at the "
    "start. Before a job that needs another group, call load_tools(group): "
    "authoring (sequences, themes, zones, schedules, calendar, lists), devices "
    "(inputs, outputs, logic, sensors, settings, network, Wi-Fi), dali "
    "(commissioning, groups, scenes, gear settings, DT8, DALI-2, RDM), logs "
    "(diagnostics, device and SD logs, events, notifications, recorder), projects "
    "(.spektra pull / push / sync). tool_groups() lists them. If a loaded tool does "
    "not appear in your tool list, call it through run_tool(name, arguments) using "
    "the definitions load_tools returned."
)


class ToolSets:
    """Which groups are loaded. One stdio session per process, so one state."""

    def __init__(self, dynamic: bool):
        self.dynamic = dynamic
        self.loaded: set[str] = {ALWAYS}

    def visible(self, name: str) -> bool:
        if not self.dynamic:
            return name not in META_TOOLS
        if name in META_TOOLS:
            return True
        return GROUP_OF.get(name, ALWAYS) in self.loaded


def mode_from_env() -> bool:
    return os.environ.get("SPEKTRA_AI_TOOLS", "all").strip().lower() == "dynamic"


state = ToolSets(mode_from_env())


async def _notify_changed(ctx) -> None:
    """Tell the client the tool list changed, in both protocol generations."""
    if ctx is None:
        return
    try:
        await ctx.notify_tools_changed()            # subscriptions/listen (2026-07-28+)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("listen notify: %s", err)
    try:
        await ctx.session.send_tool_list_changed()  # notifications/tools/list_changed
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("list_changed notify: %s", err)


def install(server) -> None:
    """Filter the server's tool list by the loaded groups and add the meta tools."""
    original_list = server.list_tools
    original_call = server.call_tool

    async def list_tools():
        return [t for t in await original_list() if state.visible(t.name)]

    server.list_tools = list_tools

    async def definitions(group: str) -> list:
        names = set(GROUPS[group]["tools"])
        return [{"name": t.name, "description": t.description,
                 "input_schema": t.input_schema}
                for t in await original_list() if t.name in names]

    def check_group(group: str) -> str | None:
        if group not in GROUPS:
            return f"Unknown group '{group}'. Groups: {', '.join(GROUPS)}."
        return None

    @server.tool()
    async def tool_groups() -> str:
        """The tool groups: what each covers, how many tools, whether loaded. Load one
        with load_tools(group) before a job that needs it."""
        rows = ["Tool groups (core is always loaded):"]
        for g, spec in GROUPS.items():
            mark = "loaded" if g in state.loaded else "not loaded"
            rows.append(f"  {g} ({len(spec['tools'])} tools, {mark}): {spec['about']}")
        return "\n".join(rows)

    @server.tool()
    async def load_tools(group: str, ctx: Context = None) -> str:
        """Load a tool group for the rest of this chat: authoring, devices, dali, logs
        or projects (see tool_groups). Returns the group's tool definitions. If they
        do not appear in your tool list, call them with run_tool(name, arguments)."""
        group = group.strip().lower()
        bad = check_group(group)
        if bad:
            return bad
        was = group in state.loaded
        state.loaded.add(group)
        if not was:
            await _notify_changed(ctx)
        defs = await definitions(group)
        head = (f"Group '{group}' {'was already' if was else 'is now'} loaded "
                f"({len(defs)} tools). If they are not in your tool list yet, call them "
                "with run_tool(name, arguments). Definitions:")
        return head + "\n" + json.dumps(defs, separators=(",", ":"))

    @server.tool()
    async def unload_tools(group: str, ctx: Context = None) -> str:
        """Drop a tool group this chat no longer needs (core stays loaded)."""
        group = group.strip().lower()
        bad = check_group(group)
        if bad:
            return bad
        if group == ALWAYS:
            return "core is always loaded."
        if group not in state.loaded:
            return f"Group '{group}' is not loaded."
        state.loaded.discard(group)
        await _notify_changed(ctx)
        return f"Group '{group}' unloaded."

    @server.tool()
    async def run_tool(name: str, arguments: dict | None = None, ctx: Context = None) -> str:
        """Call any Spektra AI tool by name, with its arguments as an object. Use it
        for tools load_tools returned that are not in your tool list. Loads the
        tool's group if needed. Writes still go preview -> confirm."""
        if name in META_TOOLS:
            return f"Call {name} directly."
        group = GROUP_OF.get(name)
        if group is None:
            return f"Unknown tool '{name}' (see tool_groups / load_tools)."
        if group not in state.loaded:
            state.loaded.add(group)
            await _notify_changed(ctx)
        result = await original_call(name, arguments or {}, ctx)
        texts = [getattr(c, "text", "") for c in (getattr(result, "content", None) or [])]
        out = "\n".join(t for t in texts if t)
        if getattr(result, "is_error", False):
            return f"Error from {name}: {out}"
        return out or "(no output)"


def run_stdio(server, on_exit=None) -> None:
    """Run on stdio, advertising tools.listChanged so older-protocol clients know to
    re-read the tool list when a group is loaded. on_exit (async) runs when the
    client closes the connection, e.g. to close the controller connection cleanly."""
    import anyio
    from mcp.server.lowlevel.server import NotificationOptions
    from mcp.server.stdio import stdio_server

    low = server._lowlevel_server

    async def go():
        async with stdio_server() as (read_stream, write_stream):
            try:
                await low.run(read_stream, write_stream, low.create_initialization_options(
                    NotificationOptions(tools_changed=True)))
            finally:
                if on_exit is not None:
                    try:
                        await on_exit()
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.debug("on_exit: %s", err)
    anyio.run(go)
