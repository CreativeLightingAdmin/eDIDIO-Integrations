"""MCP tools for live operations, diagnostics, device settings and live authoring
of lists / inputs / outputs / logic. Registered on the shared ``server`` (imported
by server.py). Reads and transient actions run at once; anything the controller
stores goes through preview -> confirm(token), like the rest of Spektra AI.

Indices in every tool are 0-based (as the controller and the .spektra file use
them); replies also show the 1-based name a person sees ("List 3 (index 2)").
"""

from __future__ import annotations

import ipaddress
import json

from edidio_control_py._v2 import eDS10_v2_pb2 as pb

from . import commands, event_log, ops, spektra_map
from .server import _controller, _new_token, server

_LOGIC_SOURCES = {v.name.lower(): v.number for v in pb.LogicType.DESCRIPTOR.values}
_LOGIC_COMPARE = {v.name.lower(): v.number for v in pb.LogicComparisonType.DESCRIPTOR.values}
_LOGIC_SOURCE_NAME = {v: k for k, v in _LOGIC_SOURCES.items()}
_LOGIC_COMPARE_NAME = {v: k for k, v in _LOGIC_COMPARE.items()}
_COMPARE_SYMBOLS = {"<": "less_than", "<=": "less_than_or_equals", "==": "equals",
                    "=": "equals", ">": "more_than", ">=": "more_than_or_equals",
                    "!=": "not_equal"}
_INPUT_MODES = {"momentary": 0, "latching": 1, "momentary_disabled": 128,
                "latching_disabled": 129}
_INPUT_MODE_NAME = {v: k for k, v in _INPUT_MODES.items()}
_OUTPUT_MODES = {"momentary": 2, "latching": 3}


def _err(err) -> str:
    return f"Error: {err}"


async def _connect(host: str, port: int, use_tls: bool):
    if host and not (_controller.connected and _controller.host == host):
        await _controller.connect(host, port, use_tls)
    _controller._require()


def _json(text, what):
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{what} must be JSON: {err}") from None


def _seconds(v) -> int:
    """5, '5', '5s', '2m', '1h', '1h30m' -> seconds (list steps hold up to 65535 s)."""
    if isinstance(v, (int, float)):
        secs = int(v)
    else:
        s, secs, num = str(v).strip().lower(), 0, ""
        for ch in s:
            if ch.isdigit() or ch == ".":
                num += ch
            elif ch in "hms" and num:
                secs += int(float(num) * {"h": 3600, "m": 60, "s": 1}[ch])
                num = ""
            elif ch != " ":
                raise ValueError(f"bad duration {v!r} (use 30, '30s', '5m', '1h30m')")
        if num:
            secs += int(float(num))
    if not 0 <= secs <= 65535:
        raise ValueError(f"a list step waits 0-65535 s (18 h 12 m); got {secs}")
    return secs


async def _save_after(messages: list) -> list:
    """Every stored change ends with DEVICE_SAVE (the controller acks it once saved)."""
    return messages + [spektra_map.device_save_message(_controller._next_id())]


# --- diagnostics -------------------------------------------------------------------

@server.tool()
async def health_check(host: str = "", port: int = 23, use_tls: bool = False) -> str:
    """One-call health report for the connected controller (eDIDIO or ADDICT):
    temperature, clock/NTP/backup battery, Ethernet link and errors, task stacks,
    DALI bus power / shorts / gear counts per line, Wi-Fi (ADDICT), running lists,
    and recent restarts, crashes and watchdog resets from the device log. Read-only."""
    try:
        await _connect(host, port, use_tls)
        return ops.format_health(await ops.health(_controller))
    except Exception as err:  # noqa: BLE001
        return _err(err)


@server.tool()
async def get_diagnostics(kind: str) -> str:
    """Raw diagnostic readout. kind: device_status, config_status, time, ethernet,
    memory, dali_status, storage, wifi_status, wifi_diagnostics, wifi_settings,
    dmx_timing, dmx_properties, dali_rx_tolerance, dali_tx_half_bit_time, ntp, lines,
    network, system, logging, link, crash, counters, connections. (Use
    run_line_diagnostics for the line probe.) Read-only."""
    try:
        _controller._require()
        if kind == "crash":
            data = await ops.crash_log(_controller)
        elif kind == "counters":
            data = await ops.counters(_controller)
        elif kind == "connections":
            data = await ops.connections(_controller)
            for c in data.get("connections", []):
                try:
                    import base64
                    c["ip"] = str(ipaddress.IPv4Address(base64.b64decode(c.pop("ip_bytes"))))
                except Exception:  # noqa: BLE001
                    pass
        elif kind in ops.DIAGNOSTICS and kind != "line":
            data = await ops.admin_get(_controller, ops.DIAGNOSTICS[kind])
        else:
            return f"Unknown kind '{kind}'. Known: {', '.join(sorted(ops.DIAGNOSTICS))}, crash, counters, connections."
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if data.get("unsupported"):
        return f"This controller does not report '{kind}'."
    return json.dumps(data, indent=1, default=str)


@server.tool()
async def run_line_diagnostics() -> str:
    """Probe every line: the daughterboard found vs the configured line type, with an
    OK / FAULTY / EMPTY / MISCONFIGURED verdict. NOTE: briefly perturbs each line (a
    DALI half-bit pulse, a DMX receive window) - run on demand, not in a loop."""
    try:
        _controller._require()
        data = await ops.line_diagnostics(_controller)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if data.get("unsupported"):
        return "This controller has no line diagnostics."
    return json.dumps(data, indent=1, default=str)


@server.tool()
async def device_log(last: int = 50, start: int = -1, kinds: str = "") -> str:
    """Read the controller's own event log (restarts and their cause, crashes,
    watchdog resets, network link, NTP, and - when logging is on - every trigger
    with its source (input/list/sensor/schedule/network) and Spektra start/stop).
    `last` entries (newest), or `last` from `start`. `kinds` filters, comma-separated:
    boot, trigger, spektra, schedule, ntp, net, user, crash. Read-only."""
    try:
        _controller._require()
        res = await ops.read_log(_controller, last=max(1, min(last, 2000)),
                                 start=None if start < 0 else start)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    entries = res["entries"]
    if kinds:
        want = {k.strip().lower() for k in kinds.split(",")}
        entries = [e for e in entries if any(w in e["type"].lower() for w in want)]
    head = (f"Device log: {res['count']} entries stored, logging '{res['categories']}'. "
            f"Showing {len(entries)}.")
    from .device_log import format_entries
    return head + "\n" + (format_entries(entries) or "  (none)")


@server.tool()
async def diagnose_controller_log(last: int = 500) -> str:
    """'Lights won't turn off' (or 'what turned this on?') straight from the
    controller: reads the last `last` device-log entries and reconstructs DALI arc
    on/off per line + group/address, reporting anything left on and what triggered it.
    Needs trigger logging on (see preview_logging). Read-only."""
    try:
        _controller._require()
        res = await ops.read_log(_controller, last=max(1, min(last, 2000)))
    except Exception as err:  # noqa: BLE001
        return _err(err)
    from .device_log import to_log_events
    events = to_log_events(res["entries"])
    note = ""
    if "trigger" not in res["categories"]:
        note = ("\nNOTE: trigger logging is off on this controller, so triggers are not "
                "recorded. Turn it on with preview_logging('trigger,spektra').")
    if not events:
        return f"No trigger entries in the last {len(res['entries'])} log entries.{note}"
    return event_log.analyze_stuck_on(events) + note


@server.tool()
async def preview_logging(categories: str) -> str:
    """Choose what the controller logs: 'trigger', 'spektra', 'trigger,spektra' or
    'none' (restarts, network and clock events are always logged). Returns a token;
    confirm(token) applies it."""
    try:
        _controller._require()
        names = [c.strip().lower() for c in categories.split(",") if c.strip()]
        if names != ["none"] and not all(c in ("trigger", "spektra") for c in names):
            return "categories: 'trigger', 'spektra', 'trigger,spektra' or 'none'."
        from .v2 import admin, frame
        msg = frame(admin(_controller._next_id(), "SET", "SYSTEM_LOGGING",
                          data=pb.PayloadMessage(string_data=",".join(names))))
        cur = await ops.logging_state(_controller)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    token = _new_token([msg], f"logging -> {','.join(names)}")
    return (f"PREVIEW - logging is '{cur['categories']}', would become "
            f"'{','.join(names)}'.\nCall confirm(token=\"{token}\") to apply.")


@server.tool()
async def preview_clear_device_log() -> str:
    """Erase the controller's event log (cannot be undone). Returns a token."""
    try:
        cur = await ops.logging_state(_controller)
        from .v2 import admin, frame
        msg = frame(admin(_controller._next_id(), "RESET", "SYSTEM_LOGGING"))
    except Exception as err:  # noqa: BLE001
        return _err(err)
    token = _new_token([msg], "clear device log")
    return (f"PREVIEW - would ERASE all {cur['count']} log entries (no undo). Read them "
            f"first with device_log if you need them.\nCall confirm(token=\"{token}\").")


# --- live state ----------------------------------------------------------------

@server.tool()
async def live_state() -> str:
    """What the controller is doing right now: active profile, physical inputs that
    are closed, lists running, the active alarm, sensor light states, burn-ins.
    Read-only."""
    try:
        _controller._require()
        counts = await _controller.read_system_counts()
        ins = await ops.input_state(_controller)
        cs = await ops.config_status(_controller)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    lines = [f"Active profile: {counts.get('active', 0) + 1} (index {counts.get('active', 0)})"]
    if not ins.get("unsupported"):
        act = ins["active"]
        lines.append("Inputs closed (LOW/active): "
                     + (", ".join(f"Input {i + 1}" for i in act) if act else "none")
                     + f" of {ins['count']}")
    if not cs.get("unsupported"):
        running = [i for i, v in enumerate(cs.get("list_status", [])) if v]
        lines.append("Lists running: " + (", ".join(
            f"List {i + 1} (index {i})" for i in running) if running else "none"))
        alarm = cs.get("alarm_status", 255)
        lines.append("Next/active alarm: " + ("none" if alarm == 255 else f"Schedule {alarm + 1}"))
        occ = [i for i, v in enumerate(cs.get("sensor_status", [])) if v]
        if occ:
            lines.append("Sensors not idle: " + ", ".join(
                f"Sensor {i + 1}={cs['sensor_status'][i]}" for i in occ))
        burn = [i for i, v in enumerate(cs.get("burn_in_status", [])) if v]
        if burn:
            lines.append("Burn-ins active: " + ", ".join(f"Burn-in {i + 1}" for i in burn))
    return "\n".join(lines)


@server.tool()
async def sensor_states() -> str:
    """Live state of every DALI sensor: occupancy/motion state, timer remaining,
    lux, daylight-harvest setpoint and last commanded arc, cooperative-group role.
    Read-only."""
    try:
        _controller._require()
        rows = await ops.sensor_states(_controller)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    busy = [r for r in rows if any(r.get(k) for k in ("timer", "light_state",
                                                      "motion_sensor_state", "last_lux"))]
    if not busy:
        return f"{len(rows)} sensor slot(s), all idle (no timer, no motion, no lux)."
    out = [f"{len(busy)} of {len(rows)} sensor(s) active:"]
    for r in busy:
        out.append(f"  Sensor {r['index'] + 1}: light_state {r['light_state']}, motion "
                   f"{r['motion_sensor_state']}, timer {r['timer']} s, lux {r['last_lux']}, "
                   f"setpoint {r['light_setpoint']}, arc {r['last_commanded_arc']}"
                   + (" [harvest master]" if r.get("is_group_master") else ""))
    return "\n".join(out)


@server.tool()
async def dali_levels(line: int, addresses: str = "") -> str:
    """What every DALI fitting on a line is doing NOW: actual arc level (0-254), on/off,
    fading, and faults (lamp failure, gear failure, limit error). Uses the controller's
    status cache to find gear, then queries each address; pass addresses ('0-3,9') to
    query specific ones. Read-only."""
    try:
        _controller._require()
        from .server import _parse_addresses
        addrs = _parse_addresses(addresses) if addresses.strip() else None
        rows = await ops.dali_levels(_controller, line, addrs)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if not rows:
        return (f"No gear in line {line}'s status cache. Try dali_scan, or pass "
                "addresses explicitly.")
    out = [f"DALI line {line}: {sum(r['present'] for r in rows)} fitting(s) answered"]
    for r in rows:
        if not r["present"]:
            out.append(f"  address {r['address']}: NO REPLY (cached status "
                       f"0x{r['cached_status']:02X}) - missing, unpowered or faulty")
            continue
        state = ("fading" if r["fading"] else "on" if r["on"] else "off")
        bits = [f"level {r['level']}" if r["level"] is not None else "level ?", state]
        if r["faults"]:
            bits.append("FAULT: " + ", ".join(r["faults"]))
        if r["power_cycle_seen"]:
            bits.append("power cycled since last command")
        out.append(f"  address {r['address']}: " + ", ".join(bits))
    return "\n".join(out)


# --- transient actions -----------------------------------------------------------

@server.tool()
async def command_reference() -> str:
    """The action vocabulary for run_command and every authoring tool (list steps,
    input/output/logic actions), with examples."""
    return (
        "A command is JSON with 'do' plus its fields. Lines are physical 1-8; every "
        "index is 0-based (List 1 = list 0).\n"
        "DALI target: address 0-63 | group 0-15 | broadcast: true. Add override: true "
        "for the sensor-overriding variant.\n"
        "  dali_arc {line, group|address|broadcast, level 0-254}\n"
        "  dali_off | dali_max | dali_min | dali_fade_up | dali_fade_down | dali_step_up | "
        "dali_step_down {line, target}\n"
        "  dali_scene {line, target, scene 0-15}\n"
        "  dali_toggle | dali_min_max_toggle | dali_fade_long_press | dali_fade_up_with_min "
        "{line, target[, query address]}\n"
        "  dmx {line, channel 1-512, level} | dmx_broadcast {line, level} or {zone, level}\n"
        "  sequence {sequence, zone} | sequence_stop {zone} | theme {theme, zone} | "
        "spektra_schedule {zone} | spektra_pause {zone} | spektra_resume {zone} | "
        "spektra_intensity {zone, level}\n"
        "  list_start | list_start_looping | list_stop {list}\n"
        "  profile {profile} | logic {logic} | schedule_enable | schedule_disable {schedule}\n"
        "  output_high | output_low | output_toggle | output_trigger {output}\n"
        "  input_enable | input_disable {input}\n"
        "  sensor_mute | sensor_unmute | sensor_override | sensor_resume | sensor_disable {sensor}\n"
        "  device_save | none\n"
        "Raw: {commandtype, zone, linemask, target, value, query} passes through.\n"
        'Examples: {"do":"dali_arc","line":1,"group":0,"level":254}  '
        '{"do":"dali_scene","line":1,"broadcast":true,"scene":2}  '
        '{"do":"list_start","list":0}')


@server.tool()
async def run_command(command: str) -> str:
    """Run one command on the controller RIGHT NOW, exactly as an input or list
    would (e.g. turn a group on, recall a scene, start a list, set an output, change
    profile). Transient - nothing is stored. See command_reference for the JSON."""
    try:
        _controller._require()
        cmd = commands.build(_json(command, "command"))
        ack = await ops.run_trigger(_controller, cmd)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    what = commands.describe(cmd)
    if ack["ok"]:
        return f"Done: {what}."
    return f"Refused: {what} -> {ack['code']}" + (f" ({ack['reason']})" if ack.get("reason") else "")


@server.tool()
async def change_profile(profile: int) -> str:
    """Switch the active profile now (0-based: Profile 1 = 0). Inputs, outputs,
    sensors and DALI inputs follow the profile."""
    try:
        _controller._require()
        ack = await ops.change_profile(_controller, profile)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return (f"Profile {profile + 1} (index {profile}) is active." if ack["ok"]
            else f"Refused: {ack}")


# --- device settings / Wi-Fi / names ---------------------------------------------

@server.tool()
async def get_device_settings() -> str:
    """The controller's settings: name, project, location and UTC offset, daylight
    saving, network, NTP, line types, DALI polling/timing, DMX timing, logging. Read-only."""
    try:
        _controller._require()
        return json.dumps(await ops.settings(_controller), indent=1, default=str)
    except Exception as err:  # noqa: BLE001
        return _err(err)


@server.tool()
async def preview_device_settings(settings: str) -> str:
    """Change simple controller settings. `settings` is JSON with any of:
    device_name (<= 31 bytes), project_name, latitude, longitude, utc_offset (hours),
    daylight_savings (true/false), dali_polling (true/false: monitor gear and lamp
    failures), dali_rx_tolerance, dali_tx_half_bit_time. Returns a token; confirm(token)
    writes them and saves."""
    try:
        _controller._require()
        wanted = _json(settings, "settings")
        current = await ops.settings(_controller)
        msgs, lines = [], []
        for key, value in wanted.items():
            msgs.append(ops.setting_message(_controller, key, value))
            was = current.get(key, (current.get("system") or {}).get(key, "?"))
            lines.append(f"  - {key}: {was!r} -> {value!r}")
        msgs = await _save_after(msgs)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    token = _new_token(msgs, "\n".join(lines))
    return ("PREVIEW - would change:\n" + "\n".join(lines)
            + f"\nCall confirm(token=\"{token}\") to write.")


@server.tool()
async def wifi_status() -> str:
    """ADDICT V3 Wi-Fi: mode, station network + IP + signal (RSSI), the device's own
    access point (SSID, clients), both MACs, co-processor health. Read-only."""
    try:
        _controller._require()
        w = await ops.wifi(_controller)
    except ops.Unsupported as err:
        return str(err)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    s, st, d = w["settings"], w["status"], w["diagnostics"]
    return "\n".join([
        f"Mode {s.get('mode', '').replace('WIFI_MODE_', '')}, running {st.get('running')}",
        f"Station: {st.get('station_state', '').replace('WIFI_STATION_', '')} on "
        f"'{st.get('station_ssid')}' ip {st.get('station_ip')} mac {st.get('station_mac')}, "
        f"RSSI {d.get('station_rssi')} dBm ch {d.get('station_channel')} bssid {d.get('station_bssid')}",
        f"Access point: '{st.get('ap_ssid')}' ip {st.get('ap_ip')} mac {st.get('ap_mac')} "
        f"ch {s.get('ap_channel')}, {st.get('ap_clients')} client(s)",
        f"Co-processor {d.get('coprocessor_version')}; restarts {d.get('coprocessor_restarts')}, "
        f"resets {d.get('coprocessor_resets')}, station disconnects {d.get('station_disconnects')}, "
        f"join failures {d.get('station_join_failures')}; TCP clients "
        f"{d.get('tcp_clients')}/{d.get('tcp_clients_max')}",
    ])


@server.tool()
async def preview_wifi_settings(mode: str, station_ssid: str = "",
                                station_password: str = "", keep_password: bool = True,
                                ap_channel: int = 0) -> str:
    """ADDICT V3: set Wi-Fi mode ('ap' = access point only, 'ap_station' = access point
    + join a network), the station network and the access-point channel (1-13, 0
    keeps it; in ap_station mode the access point runs on the station's channel - one
    radio - so a new channel is stored but only used in ap mode). keep_password=True keeps the stored station password. The device
    replies, then reconnects its Wi-Fi: if you are connected over that Wi-Fi the link
    drops for a few seconds (and for good if the new network is wrong - the access
    point stays up as a way back in). Returns a token."""
    try:
        cur = await ops.wifi(_controller)
        msg = ops.wifi_settings_message(
            _controller, mode=mode, station_ssid=station_ssid,
            station_password=None if keep_password else station_password,
            ap_channel=ap_channel)
    except ops.Unsupported as err:
        return str(err)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    s = cur["settings"]
    token = _new_token([msg], "wifi settings")
    return (f"PREVIEW - Wi-Fi {s.get('mode')} '{s.get('station_ssid')}' ch {s.get('ap_channel')}"
            f" -> {mode} '{station_ssid}' ch {ap_channel or 'unchanged'}"
            f"{'' if keep_password else ' (new password)'}.\nThe link may drop while "
            f"it reconnects. Call confirm(token=\"{token}\") to apply.")


@server.tool()
async def get_names(kind: str) -> str:
    """Names stored ON the controller (shown on its display and to other clients) for
    profiles, inputs, outputs, lists, sensors, dali_inputs or schedules. Read-only."""
    try:
        _controller._require()
        names = await ops.aliases(_controller, kind)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return "\n".join(f"  {i} ({kind[:-1].title()} {i + 1}): {n}" for i, n in enumerate(names))


@server.tool()
async def preview_names(kind: str, names: str) -> str:
    """Set names stored on the controller. kind: profiles, inputs, outputs, lists,
    sensors, dali_inputs, schedules. names: JSON list in index order, or an object
    {"0": "Foyer", "3": "Kitchen"} to change only some. Returns a token."""
    try:
        _controller._require()
        cur = await ops.aliases(_controller, kind)
        given = _json(names, "names")
        new = list(cur)
        if isinstance(given, dict):
            for k, v in given.items():
                i = int(k)
                if not 0 <= i < len(new):
                    return f"Index {i} is outside 0-{len(new) - 1}."
                new[i] = str(v)
        else:
            new = [str(x) for x in given][:len(cur)] + cur[len(given):]
        msgs = await _save_after([ops.aliases_message(_controller, kind, new)])
    except Exception as err:  # noqa: BLE001
        return _err(err)
    diff = [f"  {i}: '{a}' -> '{b}'" for i, (a, b) in enumerate(zip(cur, new)) if a != b]
    if not diff:
        return "No change."
    token = _new_token(msgs, "\n".join(diff))
    return f"PREVIEW - {kind} names:\n" + "\n".join(diff) + f"\nCall confirm(token=\"{token}\")."


# --- live authoring: lists ------------------------------------------------------------

def _describe_list(lst: dict) -> str:
    state = spektra_map.LIST_STATES.get(lst.get("state", 0), lst.get("state"))
    head = (f"List {lst['index'] + 1} (index {lst['index']}): {len(lst['steps'])} step(s), "
            f"{state}{', show' if lst.get('isShow') else ''}")
    rows = [f"    {s['index'] + 1:>3}. {commands.describe(s['action'])}; then wait "
            f"{s['time_until_next']} s" for s in lst["steps"]]
    return "\n".join([head] + rows)


@server.tool()
async def list_lists(include_empty: bool = False) -> str:
    """Every list on the controller with its steps described in English (all steps,
    including those past 32). Read-only."""
    try:
        counts = await _controller.read_system_counts()
        lists = await _controller.pull_lists(counts["lists"])
    except Exception as err:  # noqa: BLE001
        return _err(err)
    shown = [x for x in lists if include_empty or x["steps"]]
    if not shown:
        return f"All {len(lists)} lists are empty."
    return "\n".join(_describe_list(x) for x in shown) + (
        f"\n({len(lists) - len(shown)} empty list(s) not shown.)" if not include_empty else "")


_LIST_STATE_IDS = {v.replace(" ", "_"): k for k, v in spektra_map.LIST_STATES.items()}


@server.tool()
async def preview_list(index: int, steps: str, state: str = "disabled",
                       show: bool = False) -> str:
    """Write a list (a timed sequence of commands) to the controller. index is
    0-based (List 1 = 0). steps: JSON array of {"command": {...}, "wait": "5s"} -
    the wait is the time AFTER this step before the next (seconds, or "30s", "5m",
    "1h"; max 65535 s). Up to 255 steps. state: disabled (runs only when started -
    the usual), enabled, looping, random_loop, random_withdrawn, random_withdrawn_loop.
    Writing List 1 (index 0) erases every list on the controller, so the others are
    rewritten with it automatically. Returns a token; confirm(token) writes + saves.
    Example step: {"command": {"do": "dali_arc", "line": 1, "group": 0, "level": 254},
    "wait": "30m"}"""
    try:
        counts = await _controller.read_system_counts()
        if not 0 <= index < counts["lists"]:
            return f"index {index} is outside 0-{counts['lists'] - 1}."
        if state not in _LIST_STATE_IDS:
            return f"state: one of {', '.join(_LIST_STATE_IDS)}."
        raw = _json(steps, "steps")
        new_steps = []
        for n, st in enumerate(raw):
            cmd = commands.build(st.get("command", st.get("do") and st))
            secs = _seconds(st.get("wait", 0))
            dur, unit = spektra_map.duration_and_unit(secs)
            new_steps.append({"index": n, "action": cmd, "duration": dur, "timeUnit": unit,
                              "time_until_next": secs})
        new = {"index": index, "name": f"List {index + 1}", "state": _LIST_STATE_IDS[state],
               "isShow": show, "steps": new_steps, "loop_on_startup": False}
        live = await _controller.pull_lists(counts["lists"])
        order = spektra_map.lists_write_order([new], live)
        msgs = []
        for item in order:
            msgs.extend(spektra_map.list_to_messages(item, _controller._next_id))
        msgs = await _save_after(msgs)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    old = next((x for x in live if x["index"] == index), None)
    extra = [x["index"] for x in order if x["index"] != index]
    body = _describe_list(new)
    note = (f"\nAlso rewrites lists {', '.join(str(i + 1) for i in extra)} unchanged "
            "(writing List 1 erases every list)." if extra else "")
    was = f"was: {len(old['steps'])} step(s)" if old else "was: empty"
    token = _new_token(msgs, body)
    return (f"PREVIEW ({was}):\n{body}{note}\nNothing written yet. "
            f"Call confirm(token=\"{token}\") to write and save.")


# --- live authoring: inputs / outputs ---------------------------------------------------

def _describe_input(i: dict) -> str:
    mode = _INPUT_MODE_NAME.get(i.get("type", 0), f"type {i.get('type')}")
    a, b = ("short press", "long press") if "momentary" in mode else ("closed (LOW)", "opened (HIGH)")
    return (f"  Input {i['index'] + 1} (index {i['index']}) [{mode}]: {a} -> "
            f"{commands.describe(i.get('shortLowAction'))}; {b} -> "
            f"{commands.describe(i.get('longHighAction'))}")


def _describe_output(o: dict) -> str:
    mode = "latching" if o.get("type") == 3 else "momentary"
    return (f"  Output {o['index'] + 1} (index {o['index']}) [{mode}], starts "
            f"{'HIGH' if o.get('initiallyHigh') else 'LOW'}"
            + (f", pulse {o.get('triggerTime')}" if mode == "momentary" else ""))


@server.tool()
async def list_io(profile: int = -1) -> str:
    """Physical inputs and outputs per profile with what each does (0-based profile;
    -1 = the active profile). Read-only."""
    try:
        counts = await _controller.read_system_counts()
        p = counts["active"] if profile < 0 else profile
        ins = await _controller.pull_inputs(p)
        outs = await _controller.pull_outputs(p)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return "\n".join([f"Profile {p + 1} (index {p}) - inputs:"] + [_describe_input(i) for i in ins]
                     + ["Outputs:"] + [_describe_output(o) for o in outs])


def _profiles(spec: str, count: int, active: int) -> list:
    if spec in ("all", "*"):
        return list(range(count))
    if spec in ("", "active"):
        return [active]
    out = [int(x) for x in spec.split(",") if x.strip()]
    for p in out:
        if not 0 <= p < count:
            raise ValueError(f"profile {p} is outside 0-{count - 1}")
    return out


@server.tool()
async def preview_input(index: int, mode: str, on_low: str = "", on_high: str = "",
                        profiles: str = "all") -> str:
    """Configure a physical input. index 0-based (Input 1 = 0). mode: momentary
    (on_low = SHORT press action, on_high = LONG press, repeating while held) or
    latching (on_low = when the contact CLOSES to ground, on_high = when it OPENS) -
    e.g. a PE cell, a key switch, a fire relay. Add '_disabled' to keep it configured
    but ignored. on_low / on_high: command JSON (see command_reference), empty =
    no command. profiles: 'all', 'active' or '0,2'. Returns a token."""
    try:
        if mode not in _INPUT_MODES:
            return f"mode: one of {', '.join(_INPUT_MODES)}."
        low = commands.build(_json(on_low, "on_low") if on_low.strip() else None)
        high = commands.build(_json(on_high, "on_high") if on_high.strip() else None)
        counts = await _controller.read_system_counts()
        targets = _profiles(profiles, counts["profiles"], counts["active"])
        msgs, lines = [], []
        for p in targets:
            ins = await _controller.pull_inputs(p)
            if not 0 <= index < len(ins):
                return f"index {index} is outside 0-{len(ins) - 1}."
            new = dict(ins[index], type=_INPUT_MODES[mode], shortLowAction=low,
                       longHighAction=high)
            if new == ins[index]:
                continue
            old = ins[index]
            ins = [new if i["index"] == index else i for i in ins]
            msgs.append(spektra_map.inputs_to_message(p, ins, _controller._next_id()))
            lines.append(f"Profile {p + 1}:\n  was:{_describe_input(old)[1:]}\n"
                         f"  now:{_describe_input(new)[1:]}")
        if not msgs:
            return "No change: the input already does that on those profiles."
        msgs = await _save_after(msgs)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    token = _new_token(msgs, "\n".join(lines))
    return ("PREVIEW:\n" + "\n".join(lines)
            + f"\nCall confirm(token=\"{token}\") to write and save.")


@server.tool()
async def preview_output(index: int, mode: str = "latching", initially_high: bool = False,
                         pulse: int = 0, profiles: str = "all") -> str:
    """Configure a physical output (relay / open collector). index 0-based. mode:
    latching (stays HIGH/LOW until told: output_high/output_low/output_toggle) or
    momentary (output_trigger pulses it for `pulse` - the controller's
    time_trigger_is_active units). initially_high: level at start-up. Returns a token."""
    try:
        if mode not in _OUTPUT_MODES:
            return "mode: latching or momentary."
        counts = await _controller.read_system_counts()
        targets = _profiles(profiles, counts["profiles"], counts["active"])
        msgs, lines = [], []
        for p in targets:
            outs = await _controller.pull_outputs(p)
            if not 0 <= index < len(outs):
                return f"index {index} is outside 0-{len(outs) - 1}."
            new = dict(outs[index], type=_OUTPUT_MODES[mode], initiallyHigh=initially_high,
                       triggerTime=pulse)
            new["triggerTime"] = spektra_map._canon_output_time(new["type"], pulse)
            if new == outs[index]:
                continue
            outs = [new if o["index"] == index else o for o in outs]
            msgs.append(spektra_map.outputs_to_message(p, outs, _controller._next_id()))
            lines.append(f"Profile {p + 1}:{_describe_output(new)[1:]}")
        if not msgs:
            return "No change."
        msgs = await _save_after(msgs)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    token = _new_token(msgs, "\n".join(lines))
    return "PREVIEW:\n" + "\n".join(lines) + f"\nCall confirm(token=\"{token}\")."


# --- live authoring: logic -----------------------------------------------------------

def _describe_logic(g: dict) -> str:
    src = g.get("comparisonObject") or {}
    kind = _LOGIC_SOURCE_NAME.get(src.get("commandtype"), f"source {src.get('commandtype')}")
    cmp_ = _LOGIC_COMPARE_NAME.get(g.get("comparisonType"), g.get("comparisonType"))
    tgt = src.get("target", 0)
    where = {"dali_level": f"DALI {commands._dali_tgt(tgt)} {commands._lines(src.get('linemask', 0))}",
             "input_state": f"Input {tgt + 1}", "list_running": f"List {tgt + 1}",
             "occupancy_detected": f"Sensor {tgt + 1}",
             "alarm_scheduled": f"Schedule {tgt}"}.get(kind, f"target {tgt}")
    return (f"  Logic {g['index'] + 1} (index {g['index']}): if {kind} [{where}] {cmp_} "
            f"{g.get('comparisonValue')} -> {commands.describe(g.get('trueAction'))}; "
            f"else -> {commands.describe(g.get('falseAction'))}")


@server.tool()
async def list_logic() -> str:
    """Every logic rule (if <source> <compare> <value> then A else B). Read-only."""
    try:
        rules = await _controller.pull_logic()
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return "\n".join(_describe_logic(g) for g in rules) or "No logic rules."


@server.tool()
async def preview_logic(index: int, source: str, compare: str, value: int,
                        if_true: str = "", if_false: str = "") -> str:
    """Write logic rule `index` (0-based). A rule is evaluated when something runs it
    ({"do":"logic","logic":N} from an input, list step or schedule).
    source JSON: {"type": "dali_level", "line": 1, "address"|"group": n} |
    {"type": "input_state", "input": 0} | {"type": "list_running", "list": 0} |
    {"type": "occupancy_detected", "sensor": 0} | {"type": "dmx_present", "line": n} |
    {"type": "cal_weekday"} (1=Mon..7=Sun) | {"type": "cal_month"} (1-12) |
    {"type": "alarm_scheduled", "schedule": n} | {"type": "dali_cache_status"} |
    {"type": "has_error", "mask": bits}. All indices 0-based.
    compare: < <= == > >= != or bit_or / bit_and / bit_xor.
    if_true / if_false: command JSON (empty = none). Returns a token."""
    try:
        src = _json(source, "source")
        kind = str(src.get("type", "")).lower()
        if kind not in _LOGIC_SOURCES:
            return f"source type: one of {', '.join(_LOGIC_SOURCES)}."
        cmp_key = _COMPARE_SYMBOLS.get(compare.strip(), compare.strip().lower())
        if cmp_key not in _LOGIC_COMPARE:
            return f"compare: one of {', '.join(_COMPARE_SYMBOLS)} or {', '.join(_LOGIC_COMPARE)}."
        obj = commands.empty()
        obj["commandtype"] = _LOGIC_SOURCES[kind]
        if kind == "dali_level":
            obj["linemask"] = commands.linemask(src)
            obj["target"] = commands.dali_target({**src, "do": "logic source"})
        elif kind in ("dmx_present",):
            obj["linemask"] = commands.linemask(src)
        else:
            for key in ("input", "list", "sensor", "schedule", "mask"):
                if key in src:
                    obj["target"] = int(src[key])
        rules = await _controller.pull_logic()
        if not 0 <= index < len(rules):
            return f"index {index} is outside 0-{len(rules) - 1}."
        new = dict(rules[index], comparisonObject=obj, comparisonType=_LOGIC_COMPARE[cmp_key],
                   comparisonValue=int(value), isEnabled=True,
                   trueAction=commands.build(_json(if_true, "if_true") if if_true.strip() else None),
                   falseAction=commands.build(_json(if_false, "if_false") if if_false.strip() else None))
        rules = [new if g["index"] == index else g for g in rules]
        msgs = await _save_after([spektra_map.logic_to_message(rules, _controller._next_id())])
    except Exception as err:  # noqa: BLE001
        return _err(err)
    body = _describe_logic(new)
    token = _new_token(msgs, body)
    return f"PREVIEW:\n{body}\nCall confirm(token=\"{token}\") to write and save."


# --- SD card ---------------------------------------------------------------------------

def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def _newest(entries: list) -> list:
    return sorted(entries, key=lambda e: (e["modified"], e["name"]), reverse=True)


@server.tool()
async def sd_overview() -> str:
    """The controller's SD card: free/total space, and each log category's folder,
    whether it is recording, its size budget and how much it holds. Read-only."""
    try:
        _controller._require()
        space = await ops.sd_space(_controller)
        pol = await ops.sd_policy(_controller)
    except ops.Unsupported as err:
        return str(err)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if space["capacity_known"]:
        head = (f"SD card: {_human(space['free_bytes'])} free of "
                f"{_human(space['total_bytes'])}.")
    else:
        head = ("SD card: mounted, but the controller reports 0 of 0 bytes - its capacity "
                "was not measured (a known firmware issue), so free space is UNKNOWN, not full.")
    rows = [head, "Log folders:"]
    used = 0
    for e in pol.get("entries", []):
        used += e["current_disk_bytes"]
        on = {True: "recording", False: "off", None: "?"}[e["enabled"]]
        rows.append(f"  {e['directory']:<13} {e['prefix']}_nnnn.{e['extension']}  {on:<9} "
                    f"{_human(e['current_disk_bytes']):>9}  (budget {e['budget_permille'] / 10:.0f}%,"
                    f" files up to {e['max_file_size_kb']} KB)")
    rows.append(f"Logs total: {_human(used)}. Text logs (.LOG) can be read with sd_read_file; "
                ".BIN logs are binary (download them with sd_download).")
    return "\n".join(rows)


@server.tool()
async def sd_list_files(path: str = "logs", newest: int = 20, match: str = "",
                        refresh: bool = False) -> str:
    """List an SD card folder (e.g. 'logs', 'logs/trig', 'logs/sys'), newest first by
    file date. `newest` = how many to show (0 = all); `match` filters names
    (case-insensitive). A big log folder takes ~2 s per 100 files to list; the
    listing is then reused for 2 minutes (refresh=True re-reads it). File dates come
    from the controller clock, so a clock that was once wrong gives odd dates - the
    file number (TRG_0963) is the order the controller wrote them in. Read-only."""
    try:
        _controller._require()
        res = await ops.sd_list(_controller, path, fresh=refresh)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    ents = [e for e in res["entries"] if match.lower() in e["name"].lower()]
    shown = _newest(ents)[:newest] if newest else _newest(ents)
    rows = [f"{res['path'] or '/'}: {len(ents)} entr{'y' if len(ents) == 1 else 'ies'}"
            + (f", newest {len(shown)}:" if newest and len(ents) > len(shown) else ":")]
    for e in shown:
        kind = "<dir>" if e["is_dir"] else _human(e["size"])
        rows.append(f"  {e['modified'] or '(no date)':<19}  {kind:>9}  {e['name']}")
    return "\n".join(rows)


@server.tool()
async def sd_read_file(path: str, tail_kb: int = 8, offset: int = -1, length: int = 0) -> str:
    """Read a text file from the SD card, e.g. 'logs/trig/TRG_0005.LOG'. By default the
    last `tail_kb` KB (the newest lines); or give `offset` (and `length`) in bytes.
    Read-only. For binary .BIN files use sd_download."""
    try:
        _controller._require()
        if offset < 0:
            head = await ops.sd_read(_controller, path, offset=0, length=1)
            size = head["file_size"]
            start = max(0, size - max(1, tail_kb) * 1024)
            res = await ops.sd_read(_controller, path, offset=start)
        else:
            res = await ops.sd_read(_controller, path, offset=offset, length=length)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    data = res["data"]
    if b"\x00" in data[:256]:
        return (f"{res['path']} looks binary ({res['file_size']} bytes). Use sd_download "
                "to save it.")
    text = data.decode("utf-8", errors="replace")
    if res["offset"] > 0 and "\n" in text:
        text = text.split("\n", 1)[1]           # drop the partial first line
    return (f"{res['path']} ({_human(res['file_size'])}), bytes {res['offset']}-"
            f"{res['offset'] + len(data)}:\n{text}")


@server.tool()
async def sd_download(path: str, out_path: str) -> str:
    """Copy a file from the controller's SD card to this computer (out_path). Works
    for binary logs (.BIN) and crash records too. Read-only on the controller."""
    try:
        _controller._require()
        res = await ops.sd_read(_controller, path)
        with open(out_path, "wb") as fh:
            fh.write(res["data"])
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return f"Saved {res['path']} ({_human(len(res['data']))}) to {out_path}."


@server.tool()
async def sd_search(folder: str, text: str, files: int = 5, max_lines: int = 60) -> str:
    """Search the newest `files` log files in an SD folder (e.g. 'logs/trig',
    'logs/sys', 'logs/sensor', 'logs/network') for lines containing `text`
    (case-insensitive). Good for 'when did input 3 fire?' or 'any errors today?'
    (text 'ERROR' / 'WARN'). Read-only."""
    try:
        _controller._require()
        listing = await ops.sd_list(_controller, folder)
        logs = [e for e in _newest(listing["entries"]) if not e["is_dir"]
                and e["name"].upper().endswith(".LOG")][:max(1, files)]
        hits = []
        for e in logs:
            res = await ops.sd_read(_controller, f"{listing['path']}/{e['name']}")
            for line in res["data"].decode("utf-8", errors="replace").splitlines():
                if text.lower() in line.lower():
                    hits.append(f"  {e['name']}: {line}")
    except Exception as err:  # noqa: BLE001
        return _err(err)
    head = (f"'{text}' in the newest {len(logs)} file(s) of {listing['path']}: "
            f"{len(hits)} line(s)")
    return head + ("\n" + "\n".join(hits[-max_lines:]) if hits else ".") + (
        f"\n(showing the last {max_lines})" if len(hits) > max_lines else "")


# --- DALI-2 control devices and sensors ---------------------------------------------

@server.tool()
async def dali2_scan(line: int, addresses: str = "0-63") -> str:
    """Find DALI-2 control devices (sensors, push buttons, rotaries) on a line - they
    use their own 24-bit address space, separate from the lights. Read-only."""
    from . import dali24
    from .server import _parse_addresses
    try:
        _controller._require()
        found = await dali24.scan(_controller, line, _parse_addresses(addresses))
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if not found:
        return f"No DALI-2 control devices answered on line {line}."
    return "\n".join([f"{len(found)} DALI-2 device(s) on line {line}:"] + [
        f"  address {d['address']}: {d['instances']} instance(s) (dali2_device for detail)"
        for d in found])


@server.tool()
async def dali2_device(line: int, address: int) -> str:
    """Everything about one DALI-2 control device: version, device groups, and per
    instance its type (push button / rotary / motion / light), enabled, errors,
    event scheme and filter, and the live value (occupied/vacant, light level).
    Read-only."""
    from . import dali24
    try:
        _controller._require()
        dev = await dali24.probe(_controller, line, address)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return dali24.describe(dev) if dev else f"Nothing answered at line {line} address {address}."


def _describe_sensor(s: dict) -> str:
    tgt = commands._dali_tgt(s.get("controlGroup", 0))
    lines = commands._lines(s.get("controlLineMask", 0)) or "no line"
    if s.get("motionOnly"):
        mode = "motion only"
    else:
        mode = (f"daylight harvesting to {s.get('setPoint')} "
                f"(seeded from address {s.get('addressQuery')})")
    coop = ""
    if s.get("coopGroup"):
        role = "Leader" if s.get("coopLeader") else "Follower"
        coop = f", co-op group {s['coopGroup']} {role}"
    return (f"  Sensor {s['index'] + 1} (index {s['index']}): DALI-2 line {s.get('line')} "
            f"address {s.get('address')} -> controls {tgt} {lines}; {mode}; occupied "
            f"{s.get('inactivityTimer')} min, warning {s.get('warningTimer')} s, dead time "
            f"{s.get('disableTimer')} s{coop}\n"
            f"      detect -> {commands.describe(s.get('detectionTrigger'))}; warning -> "
            f"{commands.describe(s.get('warningTrigger'))}; idle -> "
            f"{commands.describe(s.get('idleTrigger'))}")


@server.tool()
async def list_sensors(profile: int = -1) -> str:
    """Sensors configured on the controller for a profile (0-based; -1 = active),
    with what each controls, its timers and its actions. Read-only (reads 40 slots,
    takes a few seconds)."""
    try:
        counts = await _controller.read_system_counts()
        p = counts["active"] if profile < 0 else profile
        sensors = await _controller.pull_sensors(p)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if not sensors:
        return f"No sensors configured on profile {p + 1} (index {p})."
    return "\n".join([f"Profile {p + 1} (index {p}) sensors:"]
                     + [_describe_sensor(s) for s in sensors])


def _sensor_batch_messages(p: int, sensors: list, supports_coop: bool) -> list:
    # A write of slot 0 starts a batch: the controller un-programs every slot on the
    # profile and mutes the sensors (it unmutes them itself when the batch ends). So
    # always write the whole profile, slot 0 first.
    return [spektra_map.sensor_to_message(s, p, _controller._next_id(), supports_coop)
            for s in sorted(sensors, key=lambda x: x["index"])]


@server.tool()
async def preview_sensor(index: int, sensor_line: int, sensor_address: int,
                         control: str, occupied_minutes: int = 10,
                         warning_seconds: int = 30, dead_seconds: int = 2,
                         on_detect: str = "", on_warning: str = "", on_idle: str = "",
                         setpoint: int = 0, query_address: int = -1,
                         coop_group: int = 0, leader: bool = False,
                         profiles: str = "all") -> str:
    """Configure a DALI-2 occupancy sensor slot. index: controller sensor slot
    (0-based, 0-39). sensor_line/sensor_address: where the sensor is (dali2_scan
    finds it). control: JSON DALI target the sensor drives, e.g. {"line":1,"group":0}
    or {"line":1,"broadcast":true}. Timers: occupied (minutes, 1-1092) -> warning
    (seconds, the dimmed period) -> idle; dead_seconds = time after idle before it
    reacts again. on_detect / on_warning / on_idle: command JSON; defaults are full
    on / arc 85 / off on the control target. setpoint > 0 turns on daylight
    harvesting (query_address = one fitting in the controlled group to seed from).
    coop_group/leader: cooperative groups (several sensors sharing lights; Leaders
    keep the group on). profiles: 'all', 'active' or '0,2'. Rewrites the profile's
    whole sensor table (the controller requires it). Returns a token."""
    try:
        target = _json(control, "control")
        ctl_mask = commands.linemask(target)
        ctl_target = commands.dali_target({**target, "do": "control"})
        if not 0 <= index < 40:
            return "index is 0-39."
        if not 1 <= occupied_minutes <= 1092:
            return "occupied_minutes is 1-1092."
        if not (0 <= warning_seconds <= 65535 and 0 <= dead_seconds <= 65535):
            return "warning_seconds / dead_seconds are 0-65535."
        if not 0 <= sensor_address <= 63:
            return "sensor_address is 0-63."
        if leader and not coop_group:
            return "A Leader needs a coop_group."
        query = query_address if query_address >= 0 else (ctl_target if ctl_target <= 63 else -1)
        if setpoint and not 0 <= query <= 63:
            return ("Daylight harvesting needs query_address: one fitting (0-63) in the "
                    "controlled group.")

        def cmd_or(text, default):
            return commands.build(_json(text, "action") if text.strip() else default)

        base = {**target, "do": "dali_arc"}
        new = {
            "index": index, "name": f"Sensor {index + 1}", "line": sensor_line,
            "address": sensor_address, "setPoint": setpoint,
            "controlLineMask": ctl_mask, "controlGroup": ctl_target,
            "addressQuery": max(query, 0),
            "inactivityTimer": occupied_minutes, "warningTimer": warning_seconds,
            "disableTimer": dead_seconds, "motionOnly": setpoint == 0,
            "detectionTrigger": cmd_or(on_detect, {**base, "level": 254}),
            "warningTrigger": cmd_or(on_warning, {**base, "level": 85}),
            "idleTrigger": cmd_or(on_idle, {**target, "do": "dali_off"}),
            "groupedWithIndexes": [], "coopGroup": coop_group, "coopLeader": leader,
            "prgBtnOne": None, "prgBtnTwo": None, "error": None,
        }
        meta = await _controller.read_system_counts()
        supports_coop = spektra_map.version_gte(meta["firmware"],
                                                spektra_map.COOP_GROUPING_FIRMWARE)
        msgs, lines = [], []
        for p in _profiles(profiles, meta["profiles"], meta["active"]):
            current = await _controller.pull_sensors(p)
            clash = [s for s in current if s["index"] != index
                     and s.get("address") == sensor_address and s.get("line") == sensor_line]
            if clash:
                return (f"Profile {p + 1}: sensor slot {clash[0]['index']} already uses line "
                        f"{sensor_line} address {sensor_address} (one slot per physical sensor).")
            old = next((s for s in current if s["index"] == index), None)
            table = [s for s in current if s["index"] != index] + [new]
            msgs += _sensor_batch_messages(p, table, supports_coop)
            lines.append(f"Profile {p + 1}: {'replace' if old else 'add'} "
                         f"(profile has {len(table)} sensor(s) after)")
        msgs = await _save_after(msgs)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    body = _describe_sensor(new) + "\n" + "\n".join(lines)
    token = _new_token(msgs, body)
    return (f"PREVIEW:\n{body}\nSensors are muted briefly while the table is written. "
            f"Call confirm(token=\"{token}\") to write and save.")


@server.tool()
async def preview_remove_sensor(index: int, profiles: str = "all") -> str:
    """Remove a sensor slot (0-based) from the controller's sensor table. Returns a token."""
    try:
        meta = await _controller.read_system_counts()
        supports_coop = spektra_map.version_gte(meta["firmware"],
                                                spektra_map.COOP_GROUPING_FIRMWARE)
        msgs, lines = [], []
        for p in _profiles(profiles, meta["profiles"], meta["active"]):
            current = await _controller.pull_sensors(p)
            if not any(s["index"] == index for s in current):
                continue
            rest = [s for s in current if s["index"] != index]
            if rest:
                msgs += _sensor_batch_messages(p, rest, supports_coop)
            else:
                # Clearing a profile: RESET is scoped to the active profile.
                if p != meta["active"]:
                    msgs.append(spektra_map.change_profile_message(_controller._next_id(), p))
                msgs.append(spektra_map.reset_sensors_message(_controller._next_id()))
                msgs.append(spektra_map.device_save_message(_controller._next_id()))
                if p != meta["active"]:
                    msgs.append(spektra_map.change_profile_message(_controller._next_id(),
                                                                   meta["active"]))
            lines.append(f"Profile {p + 1}: remove Sensor {index + 1} ({len(rest)} left)")
        if not msgs:
            return f"Sensor {index + 1} (index {index}) is not configured on those profiles."
        msgs = await _save_after(msgs)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    token = _new_token(msgs, "\n".join(lines))
    return "PREVIEW:\n" + "\n".join(lines) + f"\nCall confirm(token=\"{token}\")."


@server.tool()
async def sensor_command(index: int, action: str) -> str:
    """Act on a configured sensor slot of the ACTIVE profile now: identify (flash its
    LED), mute (stop it sending), unmute, override (stop it adjusting the light until
    its occupancy times out). Transient."""
    names = {"identify": "IDENTIFY", "mute": "MUTE", "unmute": "UNMUTE", "override": "OVERRIDE"}
    if action.lower() not in names:
        return f"action: one of {', '.join(names)}."
    try:
        from .v2 import ack_summary
        r = await ops.request(_controller, sensor_command=pb.SensorCommandMessage(
            index=index, type=pb.SensorCommandType.Value(names[action.lower()])))
        ack = ack_summary(r)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return f"Sensor {index + 1}: {action} sent." if ack["ok"] else f"Refused: {ack}"


# --- line types (DALI / DMX output / DMX input / empty) -----------------------------

_LINE_TYPES = {"empty": 0, "dali": 1, "dmx": 2, "dmx_out": 2, "dmx_output": 2,
               "dmx_in": 3, "dmx_input": 3, "auto": 4}
_LINE_NAMES = {0: "empty", 1: "DALI", 2: "DMX output", 3: "DMX input", 4: "auto"}


@server.tool()
async def preview_line_types(changes: str, reboot: bool = True) -> str:
    """Change what a controller line is: dali, dmx (DMX output - also needed for
    RDM), dmx_in (DMX input, e.g. from a console), or empty. changes: '3=dmx' or
    '1=dali,3=dmx_in' (lines 1-based). The controller must REBOOT for it to take
    effect (about 30 s offline); confirm(token) sets the lines, reboots, waits for
    the controller and reconnects. Returns a token."""
    try:
        current = list(await _controller.read_line_types())
        if not current:
            return "This controller does not report its line types."
        new = list(current)
        for part in changes.split(","):
            if not part.strip():
                continue
            ln, _, kind = part.partition("=")
            ln, kind = int(ln), kind.strip().lower()
            if kind not in _LINE_TYPES:
                return f"line type: one of {', '.join(sorted(set(_LINE_TYPES)))}."
            if not 1 <= ln <= len(new):
                return f"line {ln} is outside 1-{len(new)} on this controller."
            new[ln - 1] = _LINE_TYPES[kind]
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if new == current:
        return "No change: the lines are already like that."
    diff = [f"  line {i + 1}: {_LINE_NAMES.get(a, a)} -> {_LINE_NAMES.get(b, b)}"
            for i, (a, b) in enumerate(zip(current, new)) if a != b]

    async def run():
        ack = await _controller.set_line_types(new)
        if not ack.get("ok"):
            return f"Refused: {ack}"
        if not reboot:
            return "Line types set. They take effect after the next reboot."
        await _controller.reboot()
        back = await _controller.wait_for_reboot()
        if not back:
            return "Line types set and reboot sent, but the controller did not come back in 2 min."
        now = await _controller.read_line_types()
        return ("Done: rebooted and reconnected. Lines now: "
                + ", ".join(f"{i + 1}={_LINE_NAMES.get(t, t)}" for i, t in enumerate(now)) + ".")

    token = _new_token([], "\n".join(diff))
    from .server import _pending
    _pending[token]["runner"] = run
    return ("PREVIEW:\n" + "\n".join(diff)
            + ("\nThe controller will REBOOT (about 30 s offline)." if reboot else "")
            + f"\nCall confirm(token=\"{token}\") to apply.")


# --- RDM ------------------------------------------------------------------------------

@server.tool()
async def rdm_discover(line: int, details: bool = True) -> str:
    """Find RDM fixtures on a DMX OUTPUT line (1-based) and, by default, read each
    one's manufacturer, model, label, DMX start address, footprint and personalities.
    The line must be a DMX output (preview_line_types to change it). Read-only."""
    from . import rdm
    try:
        _controller._require()
        found = await rdm.discover(_controller, line)
        if not found["uids"]:
            extra = f" (error code {found['error_code']})" if found["error_code"] else ""
            return f"No RDM fixtures answered on line {line}{extra}."
        rows = [f"{len(found['uids'])} RDM fixture(s) on line {line}:"]
        for uid in found["uids"]:
            rows.append(rdm.describe(await rdm.details(_controller, line, uid)) if details
                        else f"  {rdm.uid_text(uid)}")
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return "\n".join(rows)


@server.tool()
async def rdm_get(line: int, uid: str, pid: int, data: str = "") -> str:
    """Raw RDM GET of any parameter (pid number, e.g. 0x0060 = 96 DEVICE_INFO).
    data: optional comma-separated bytes for the request. Returns the reply bytes.
    Read-only."""
    from . import rdm
    try:
        _controller._require()
        payload = bytes(int(x, 0) for x in data.split(",") if x.strip())
        r = await rdm.request(_controller, line, rdm.parse_uid(uid), pid, data=payload)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    name = rdm.PID_NAMES.get(pid, f"PID 0x{pid:04X}")
    if not r["ok"]:
        return f"{name}: no answer ({r['error']})."
    b = r["data"]
    text = "".join(chr(x) if 32 <= x < 127 else "." for x in b)
    return f"{name}: {len(b)} byte(s) {b.hex(' ')}  '{text}'"


@server.tool()
async def rdm_identify(line: int, uid: str, on: bool = True) -> str:
    """Make an RDM fixture identify itself (flash) - or stop. Transient."""
    from . import rdm
    try:
        _controller._require()
        r = await rdm.request(_controller, line, rdm.parse_uid(uid), rdm.PID_IDENTIFY_DEVICE,
                              set_=True, data=bytes([1 if on else 0]))
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return (f"Identify {'on' if on else 'off'} for {uid}." if r["ok"]
            else f"No answer from {uid}: {r['error']}")


@server.tool()
async def preview_rdm_set(line: int, uid: str, start_address: int = 0,
                          personality: int = 0, label: str = "") -> str:
    """Change an RDM fixture: DMX start_address (1-512), personality (its mode number,
    see rdm_discover), and/or label (up to 32 characters). Only the values you give
    are changed. Returns a token; confirm(token) sends them and reads them back."""
    from . import rdm
    try:
        _controller._require()
        u = rdm.parse_uid(uid)
        cur = await rdm.details(_controller, line, u)
        if cur.get("error"):
            return f"{uid} does not answer on line {line}."
        sets, lines = [], []
        if start_address:
            if not 1 <= start_address <= 512:
                return "start_address is 1-512."
            fp = cur.get("footprint") or 1
            if start_address + fp - 1 > 512:
                return f"Start {start_address} + footprint {fp} runs past channel 512."
            sets.append((rdm.PID_DMX_START_ADDRESS, start_address.to_bytes(2, "big")))
            lines.append(f"  DMX start address: {cur.get('start_address')} -> {start_address}")
        if personality:
            ids = [p["id"] for p in cur.get("personalities", [])]
            if ids and personality not in ids:
                return f"personality: one of {ids}."
            sets.append((rdm.PID_DMX_PERSONALITY, bytes([personality])))
            name = next((p["name"] for p in cur.get("personalities", [])
                         if p["id"] == personality), "?")
            lines.append(f"  personality: {cur.get('personality')} -> {personality} ({name})")
        if label:
            if len(label.encode("utf-8")) > 32:
                return "An RDM label is at most 32 bytes."
            sets.append((rdm.PID_DEVICE_LABEL, label.encode("utf-8")))
            lines.append(f"  label: '{cur.get('label', '')}' -> '{label}'")
        if not sets:
            return "Nothing to change: give start_address, personality and/or label."
    except Exception as err:  # noqa: BLE001
        return _err(err)

    async def run():
        out = []
        for pid, data in sets:
            r = await rdm.request(_controller, line, u, pid, set_=True, data=data)
            out.append(f"{rdm.PID_NAMES.get(pid, pid)}: {'sent' if r['ok'] else r['error']}")
        after = await rdm.details(_controller, line, u)
        return "Done. " + "; ".join(out) + "\nNow:\n" + rdm.describe(after)

    token = _new_token([], "\n".join(lines))
    from .server import _pending
    _pending[token]["runner"] = run
    return (f"PREVIEW for {cur.get('manufacturer', '')} {cur.get('model', '')} {uid}:\n"
            + "\n".join(lines) + f"\nCall confirm(token=\"{token}\") to send.")


# --- functionality statement ----------------------------------------------------------

@server.tool()
async def functionality_statement(path: str = "", out_path: str = "", title: str = "") -> str:
    """Write a functionality statement - what the lighting control does, in plain
    English: profiles and what switches them, schedules, inputs, sensors, DALI-2
    inputs, lists, logic, outputs, colour zones and Spektra content. From the
    CONNECTED controller (path empty; also uses the names stored on it - takes about
    a minute to read everything) or from a .spektra file (path). out_path saves it
    as Markdown. Read-only."""
    from . import statement
    from .spektra_file import load_spektra
    try:
        names_by_mac = {}
        if path:
            proj = load_spektra(path).raw
        else:
            _controller._require()
            proj = await _controller.pull_project()
            names = {}
            for kind in ops.ALIAS_KINDS:
                try:
                    names[kind] = await ops.aliases(_controller, kind)
                except Exception:  # noqa: BLE001 - names are optional
                    pass
            names_by_mac = {mac: names for mac in proj["edidios"]}
        text = statement.project_statement(proj, names_by_mac, title)
        if out_path:
            with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return text + (f"\n(Saved to {out_path}.)" if out_path else "")


# --- network and clock settings --------------------------------------------------------

def _ipv4(text: str, what: str, *, blank_ok: bool = False) -> str:
    text = (text or "").strip()
    if blank_ok and not text:
        return ""
    try:
        ipaddress.IPv4Address(text)
    except ValueError:
        raise ValueError(f"{what} '{text}' is not an IPv4 address") from None
    return text


_NET_FIELDS = {"dhcp": "DHCP", "ip": "IP", "subnet": "subnet", "gateway": "gateway",
               "dns1": "DNS_Primary", "dns2": "DNS_Secondary"}


@server.tool()
async def preview_network_settings(dhcp: str = "", ip: str = "", subnet: str = "",
                                   gateway: str = "", dns1: str = "", dns2: str = "",
                                   reboot: bool = False) -> str:
    """Change the controller's network settings. Only what you give changes:
    dhcp ('on'/'off'), ip / subnet / gateway (the static address, used when DHCP is
    off), dns1 / dns2. They take effect at the next restart; reboot=True restarts now
    and reconnects (to the new static IP, or finds the controller again by MAC on
    DHCP). CAUTION: a wrong address can take the controller off the network until
    someone sets it from its display. Returns a token."""
    try:
        r = await _controller.read_admin("NETWORK_PROPERTIES")
        if r.WhichOneof("payload") != "admin_message":
            return "This controller does not report its network settings."
        cur = r.admin_message.network_properties
        new = pb.AdminNetworkPropertiesMessage()
        new.CopyFrom(cur)
        new.error = ""
        changes = []
        if dhcp:
            if dhcp.lower() not in ("on", "off", "true", "false", "1", "0"):
                return "dhcp: 'on' or 'off'."
            new.DHCP = dhcp.lower() in ("on", "true", "1")
        for key, val in (("ip", ip), ("subnet", subnet), ("gateway", gateway)):
            if val:
                setattr(new, _NET_FIELDS[key], _ipv4(val, key))
        for key, val in (("dns1", dns1), ("dns2", dns2)):
            if val:
                setattr(new, _NET_FIELDS[key], _ipv4(val, key))
        for key, field in _NET_FIELDS.items():
            a, b = getattr(cur, field), getattr(new, field)
            if a != b:
                changes.append(f"  {key}: {a} -> {b}")
        if not changes:
            return "No change."
        if not new.DHCP:
            for field in ("IP", "subnet", "gateway"):
                _ipv4(getattr(new, field), f"static {field} (needed with DHCP off)")
            net = ipaddress.IPv4Network(f"{new.IP}/{new.subnet}", strict=False)
            if ipaddress.IPv4Address(new.gateway) not in net:
                changes.append(f"  WARNING: gateway {new.gateway} is not in {net}")
        mac = cur.MAC
        from .v2 import frame as _frame_v2
        frame = _frame_v2(
            pb.EdidioMessage(message_id=_controller._next_id(), admin_message=pb.AdminMessage(
                command=pb.AdminCommandType.SET,
                target=pb.AdminPropertyType.NETWORK_PROPERTIES, network_properties=new)))
    except Exception as err:  # noqa: BLE001
        return _err(err)

    async def run():
        from .v2 import ack_summary
        ack = ack_summary(await _controller._require().request(frame))
        if not ack["ok"]:
            return f"Refused: {ack}" + (" (needs an ADMIN login)" if ack["code"] == "UNAUTHORISED" else "")
        save = await _controller.send_and_ack([spektra_map.device_save_message(_controller._next_id())])
        if not reboot:
            return f"Saved ({save[0]['code']}). The new settings apply at the next restart."
        await _controller.reboot()
        old_host = _controller.host
        if not new.DHCP and new.IP and new.IP != old_host:
            _controller.host = new.IP
        back = await _controller.wait_for_reboot()
        if not back and new.DHCP:
            from . import discovery
            for d in discovery.discover():
                if (d.get("MAC") or "").replace("-", ":").upper() == mac.upper():
                    await _controller.connect(d["IP"], _controller.port, _controller.use_tls)
                    back = _controller.connected
                    break
        where = _controller.host if back else "(not found)"
        return (f"Saved and restarted. Controller is back at {where}." if back else
                f"Saved and restart sent, but the controller did not come back at {old_host}"
                " or by discovery. Check it from its display.")

    token = _new_token([], "\n".join(changes))
    from .server import _pending
    _pending[token]["runner"] = run
    return ("PREVIEW - network settings:\n" + "\n".join(changes)
            + ("\nThe controller will RESTART to apply them." if reboot else
               "\nThey apply at the next restart.")
            + f"\nCall confirm(token=\"{token}\") to write.")


@server.tool()
async def preview_clock_settings(ntp: str = "", ntp_server: str = "",
                                 ntp_poll_hours: float = 0, utc_offset: float = 99,
                                 daylight_savings: str = "", latitude: float = 999,
                                 longitude: float = 999) -> str:
    """Change how the controller keeps time: ntp ('on'/'off'), ntp_server (host name
    or IP, < 32 chars), ntp_poll_hours (how often it re-syncs), utc_offset (hours,
    -14..14), daylight_savings ('on'/'off'), latitude/longitude (for sunrise/sunset
    schedules). Only what you give changes. Returns a token. (ntp_sync_now syncs
    immediately; set_time sets the clock from this computer.)"""
    from .v2 import admin, frame
    try:
        msgs, lines = [], []
        if ntp or ntp_server or ntp_poll_hours:
            r = await _controller.read_admin("NTP_DETAILS")
            if r.WhichOneof("payload") != "admin_message":
                return "This controller has no NTP settings."
            cur = r.admin_message.network_properties
            server_name = ntp_server or cur.NTPServer
            if not 0 < len(server_name) < 32:
                return "ntp_server must be 1-31 characters."
            on = cur.NTP if not ntp else ntp.lower() in ("on", "true", "1")
            secs = int(ntp_poll_hours * 3600) if ntp_poll_hours else cur.NTPTimeout
            if not 0 < secs <= 65535:
                return "ntp_poll_hours must be up to 18.2 hours (65535 s)."
            msgs.append(frame(admin(_controller._next_id(), "SET", "NTP_DETAILS",
                                    network_properties=pb.AdminNetworkPropertiesMessage(
                                        NTPServer=server_name, NTP=on, NTPTimeout=secs))))
            lines.append(f"  NTP: {'on' if cur.NTP else 'off'} '{cur.NTPServer}' every "
                         f"{cur.NTPTimeout / 3600:.1f} h -> {'on' if on else 'off'} "
                         f"'{server_name}' every {secs / 3600:.1f} h")
        for key, val in (("utc_offset", utc_offset if utc_offset != 99 else None),
                         ("latitude", latitude if latitude != 999 else None),
                         ("longitude", longitude if longitude != 999 else None)):
            if val is not None:
                msgs.append(ops.setting_message(_controller, key, val))
                lines.append(f"  {key} -> {val}")
        if daylight_savings:
            msgs.append(ops.setting_message(_controller, "daylight_savings",
                                            daylight_savings.lower() in ("on", "true", "1")))
            lines.append(f"  daylight saving -> {daylight_savings}")
        if not msgs:
            return "Nothing to change."
        msgs = await _save_after(msgs)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    token = _new_token(msgs, "\n".join(lines))
    return "PREVIEW - clock:\n" + "\n".join(lines) + f"\nCall confirm(token=\"{token}\")."


@server.tool()
async def ntp_sync_now() -> str:
    """Ask the controller to sync its clock from its NTP server now, then report the
    result (last correction, server, stratum)."""
    import asyncio
    try:
        from .v2 import ack_summary
        ack = ack_summary(await _controller.read_admin("NTP_FORCE_SYNC", "RUN"))
        if not ack["ok"]:
            return f"Refused: {ack}"
        await asyncio.sleep(4)
        td = await ops.admin_get(_controller, "TIME_DIAGNOSTICS")
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return (f"NTP sync requested. Last result: {td.get('last_ntp_error')}, correction "
            f"{td.get('last_ntp_correction_seconds')} s, stratum {td.get('last_ntp_stratum')}, "
            f"round trip {td.get('last_ntp_rtt_ms')} ms, from '{td.get('ntp_server_hostname')}'.")


# --- notifications (friendly) -------------------------------------------------------

@server.tool()
async def notify_when(event: str, index: int = -1, channel: str = "log", label: str = "",
                      webhook_url: str = "", one_shot: bool = True) -> str:
    """Send an OUT-OF-BAND notification when something happens on the controller (fires
    independently of this chat). event: input_pressed, input_short_press,
    input_long_press, input_closed, input_opened, sensor_occupied, sensor_warning,
    sensor_idle, list_started, list_step, schedule_fired, schedule_ended,
    config_changed (a config write - says what and which client; renames do not
    count), restart,
    client_connected, client_disconnected, network_link_down, spektra_started,
    spektra_stopped, dali_error (a DALI send that failed, e.g. no bus power).
    index: which one, 0-based (Input 1 = 0, List 3 = 2, Schedule 1 = 0, zone for
    spektra_*); for dali_error the line 1-4. -1 = any. Channels: log (default, kept
    in-process - see list_notifications), webhook (POSTs the event JSON to
    webhook_url - sends data to an external service), email (needs SMTP config).
    one_shot=False keeps it armed. Starts watching every event category."""
    from . import notify
    from .server import _log_channel
    try:
        cond = notify.preset_condition(event, index)
        _controller._require()
        ev = _controller._events
        if ev is None or not ev.running or len(ev.categories) < 6:
            await _controller.start_events(("trigger", "inputs", "dali", "sensors", "schedule",
                                            "lists", "config", "network", "event"))
        chan = notify.make_channel(channel, log_channel=_log_channel, webhook_url=webhook_url)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    n = _controller.notifications.register(cond, chan, label=label or event,
                                          one_shot=one_shot)
    which = "" if index < 0 else (f" line {index}" if event == "dali_error" else f" #{index + 1}")
    return (f"Notification #{n.id} armed on {_controller.host} [{channel}]: {event}{which}"
            f"{'' if one_shot else ' (repeating)'}. It fires out-of-band when it happens.")


# --- live colour ------------------------------------------------------------------------

@server.tool()
async def set_zone_colour(zone: int, colour: str, fade_ms: int = 50,
                          stop_playback: bool = True, dali_group: int = -1) -> str:
    """Set a Spektra zone (0-based; Zone 1 = 0) to a colour RIGHT NOW - for trying
    colours while designing sequences and themes. colour: '#RRGGBB' (mapped onto the
    zone's red/green/blue channels) or one level per channel, '255,0,0,128' (0-255;
    DALI channels cap at 254). stop_playback stops a sequence/theme running on the
    zone first (it would overwrite the colour). dali_group (DALI zones, 0-15): send
    channel n to DALI group dali_group+n instead of per address - one frame per
    channel however many lights (each channel's gear must be in its group).
    Transient: nothing is stored. DMX, DALI, and DALI DT8 RGBWAF and xy zones."""
    from . import colour as _colour
    try:
        zones = await _controller.pull_zones()
        z = next((x for x in zones if x.get("index") == zone), None)
        if z is None:
            return f"Zone {zone + 1} (index {zone}) is not set up on this controller."
        levels = _colour.parse_levels(colour, z)
        if dali_group >= 0:
            if z.get("protocol") not in (_colour.PROTOCOL_DALI, _colour.PROTOCOL_DT8_RGBWAF,
                                         _colour.PROTOCOL_DT8_XY):
                return "dali_group is for DALI zones."
            z = dict(z, daligroupoffset=dali_group)
        msgs = _colour.zone_messages(z, levels, _controller._next_id, fade_ms=fade_ms)
        if stop_playback:
            await _controller.stop_zone(zone)
        acks = await _controller.send_and_ack(msgs)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    bad = [a for a in acks if not a.get("ok")]
    kind = {0: "DALI", 1: "DMX", 2: "DALI DT8", 3: "DALI DT8 xy"}.get(z.get("protocol"), "DALI")
    what = (f"Zone {zone + 1}: {z.get('numLights')} light(s) x {z.get('numChannels')} "
            f"channel(s) ({kind}) set to {levels}")
    if bad:
        return f"{what} - {len(bad)} of {len(acks)} message(s) refused: {bad[0]}"
    return what + f" ({len(acks)} message(s), fade {fade_ms} ms)."


# --- DMX-to-DALI translations ---------------------------------------------------------

def _dali_targets(spec: str) -> list:
    """'0-3' (short addresses), 'g2' / 'group 2', 'all' / 'broadcast', or a mix:
    '0,1,g2' -> DALI targets (address, 64+group, 80)."""
    out = []
    for part in str(spec).replace(";", ",").split(","):
        p = part.strip().lower()
        if not p:
            continue
        if p in ("all", "broadcast"):
            out.append(80)
        elif p.startswith("g"):
            g = int(p.lstrip("group ").lstrip("g"))
            if not 0 <= g <= 15:
                raise ValueError(f"group {g} is outside 0-15")
            out.append(64 + g)
        elif "-" in p:
            a, b = (int(x) for x in p.split("-"))
            out.extend(range(a, b + 1))
        else:
            out.append(int(p))
    if any(not 0 <= t <= 80 for t in out):
        raise ValueError("DALI addresses are 0-63, groups g0-g15, or 'all'")
    return out


def _describe_translation(t: dict) -> str:
    if not t.get("isEnabled"):
        return f"  Translation {t['index'] + 1}: off"
    n = t["DMXEndAddress"] - t["DMXStartAddress"] + 1
    targets = [commands._dali_tgt(a) for a in (t.get("DALIAddresses") or [])[:n]]
    pairs = ", ".join(f"ch{t['DMXStartAddress'] + i}->{x}" for i, x in enumerate(targets))
    block = (f"; blocks inputs {[i + 1 for i in range(32) if t.get('inputMask', 0) & (1 << i)]}"
             f" while DMX is present" if t.get("blockInputs") and t.get("inputMask") else "")
    return (f"  Translation {t['index'] + 1}: DMX in on {commands._lines(t.get('lineIn', 0))} -> "
            f"DALI {commands._lines(t.get('lineOut', 0))}: {pairs}{block}")


@server.tool()
async def list_translations() -> str:
    """DMX-to-DALI translations: which DMX input channels drive which DALI addresses
    or groups (as arc levels, sampled every 0.7 s). Read-only."""
    try:
        items = await _controller.pull_translations()
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if not items:
        return "This controller has no DMX-to-DALI translation slots."
    return "\n".join(_describe_translation(t) for t in items)


@server.tool()
async def preview_translation(index: int, dmx_in_line: int = 0, dali_line: int = 0,
                              dmx_start: int = 1, dali_targets: str = "",
                              enabled: bool = True, block_inputs: str = "") -> str:
    """Set up a DMX-to-DALI translation: DMX channels from dmx_start on the DMX INPUT
    line dmx_in_line drive the DALI targets in order on dali_line (channel dmx_start ->
    first target, +1 -> second, ...). dali_targets: '0-3', 'g2', 'all' or a mix
    ('0,1,g2'); up to 64. block_inputs: input numbers ('1,2', 1-based) ignored while
    DMX is present. enabled=False switches the slot off. index 0-based. The DMX line
    must be a DMX input (preview_line_types). Returns a token."""
    try:
        items = await _controller.pull_translations()
        if not 0 <= index < len(items):
            return f"index is 0-{len(items) - 1} on this controller."
        new = dict(items[index])
        if enabled:
            targets = _dali_targets(dali_targets)
            if not targets or len(targets) > 64:
                return "Give 1-64 DALI targets."
            if not (1 <= dmx_start and dmx_start + len(targets) - 1 <= 512):
                return "The DMX channels must sit within 1-512."
            lines = await _controller.read_line_types()
            if lines and (len(lines) < dmx_in_line or lines[dmx_in_line - 1] != 3):
                return (f"Line {dmx_in_line} is not a DMX input on this controller "
                        "(set it with preview_line_types).")
            if lines and (len(lines) < dali_line or lines[dali_line - 1] != 1):
                return f"Line {dali_line} is not a DALI line on this controller."
            mask = 0
            for i in (int(x) for x in block_inputs.split(",") if x.strip()):
                mask |= 1 << (i - 1)
            new.update(isEnabled=True, lineIn=1 << (dmx_in_line - 1),
                       lineOut=1 << (dali_line - 1), DMXStartAddress=dmx_start,
                       DMXEndAddress=dmx_start + len(targets) - 1,
                       DALIAddresses=targets + [0] * (64 - len(targets)),
                       blockInputs=bool(mask), inputMask=mask)
        else:
            new["isEnabled"] = False
        table = [new if t["index"] == index else t for t in items]
        msgs = await _save_after([spektra_map.translations_to_message(table, _controller._next_id())])
    except Exception as err:  # noqa: BLE001
        return _err(err)
    body = "was:\n" + _describe_translation(items[index]) + "\nnow:\n" + _describe_translation(new)
    token = _new_token(msgs, body)
    return f"PREVIEW:\n{body}\nCall confirm(token=\"{token}\") to write and save."


# --- burn-ins ---------------------------------------------------------------------

def _describe_burnin(b: dict) -> str:
    if not b.get("duration"):
        return f"  Burn-in {b['index'] + 1}: not set up"
    st = b.get("states") or {}
    running = "counting down" if st.get("running_flag") else "paused (lights off)"
    if not b.get("remaining"):
        running = "finished"
    return (f"  Burn-in {b['index'] + 1}: holds {commands._dali_tgt(b.get('address', 0))} "
            f"{commands._lines(b.get('line_mask', 0))} at full for {b['duration'] / 60:g} h "
            f"(counts only while address {b.get('query_address')} is on); "
            f"{b.get('remaining', 0) / 60:g} h left, {running}")


@server.tool()
async def list_burnins() -> str:
    """Burn-ins (new-lamp seasoning: lights held at full for N hours) with time left
    and whether they are counting. Read-only."""
    try:
        items = await _controller.pull_burnins()
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return "\n".join(_describe_burnin(b) for b in items) or "No burn-in slots."


@server.tool()
async def preview_burnin(index: int, line: int, target: str, query_address: int,
                         hours: float) -> str:
    """Set up a burn-in: hold `target` ('5', 'g2' or 'all') on DALI `line` at full for
    `hours`; the countdown only runs while `query_address` (one fitting in it) is on.
    Start/stop it with run_command {"do":"burnin_start","burnin":N}. Writing burn-ins
    RESTARTS their countdowns. hours=0 clears the slot. index 0-based. Returns a token."""
    try:
        items = await _controller.pull_burnins()
        if not 0 <= index < len(items):
            return f"index is 0-{len(items) - 1} on this controller."
        tgt = _dali_targets(target)
        if len(tgt) != 1:
            return "Give one target: an address, a group (g2) or all."
        minutes = int(round(hours * 60))
        if not 0 <= minutes <= 65535:
            return "hours is 0-1092."
        if not 0 <= query_address <= 63:
            return "query_address is one fitting, 0-63."
        new = dict(items[index], line_mask=1 << (line - 1) if minutes else 0,
                   address=tgt[0] if minutes else 0,
                   query_address=query_address if minutes else 0, duration=minutes)
        table = [new if b["index"] == index else b for b in items]
        msgs = await _save_after([spektra_map.burnins_to_message(table, _controller._next_id())])
    except Exception as err:  # noqa: BLE001
        return _err(err)
    body = "was:\n" + _describe_burnin(items[index]) + "\nnow:\n" + _describe_burnin(
        {**new, "remaining": new["duration"]})
    token = _new_token(msgs, body)
    return (f"PREVIEW:\n{body}\nWriting burn-ins restarts every countdown. "
            f"Call confirm(token=\"{token}\").")


# --- calendar check -----------------------------------------------------------------

@server.tool()
async def check_calendar(expected: str, year: int = 0, strict: bool = False) -> str:
    """Check the controller's Spektra calendar against what it should hold. expected:
    JSON list of {"dates": "12-01..12-26" | "2026-12-25" | ["12-24","12-25"],
    "sequence": 3 or "Christmas" (index 0-based, or name) | "theme": ... |
    "nothing": true}. year: the year the dates are in (default this year; from
    1 March the calendar slots shift by a day in leap years). strict=True also lists
    calendar days not in your list. Reports matches and every day that differs.
    Read-only."""
    from datetime import date as _date

    from . import calendar_check
    try:
        exp = _json(expected, "expected")
        if isinstance(exp, dict):
            exp = [exp]
        y = year or _date.today().year
        days = await _controller.read_calendar()
        names = {"sequence": {s["index"]: s.get("name") for s in await _controller.pull_sequences()},
                 "theme": {t["index"]: t.get("name") for t in await _controller.pull_themes()}}
        res = calendar_check.compare(days, exp, names, y, strict=strict)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return calendar_check.format_report(res, y)


# --- DALI devices / channel order -----------------------------------------------------

async def _dali_unit_infos(line: int, addresses=None) -> list:
    from . import dali_units
    if addresses is None:
        # A busy bus occasionally drops a reply: merge three scans so a channel is
        # not missed (a re-addressing plan must see every channel).
        found = set()
        for _ in range(3):
            found |= {d["address"] for d in await _controller.dali_scan(line)}
        addresses = sorted(found)
    return [await dali_units.unit_info(_controller, line, a) for a in addresses]


@server.tool()
async def dali_devices(line: int, addresses: str = "") -> str:
    """Physical DALI devices on a line, from each address's memory bank 0: which
    addresses belong to the same multi-channel driver (GTIN + serial), and each
    channel's logical index (0 = first channel, e.g. red on RGBW) - flags channels
    that are not on consecutive addresses in channel order. Read-only (scans the
    line unless addresses are given)."""
    from . import dali_units
    from .server import _parse_addresses
    try:
        _controller._require()
        infos = await _dali_unit_infos(line, _parse_addresses(addresses) if addresses.strip() else None)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if not infos:
        return f"No DALI gear answered on line {line}."
    return dali_units.describe(dali_units.group_devices(infos), line)


@server.tool()
async def preview_dali_channel_order(line: int, start_address: int = -1,
                                     device_id: str = "") -> str:
    """Re-address a multi-channel DALI device so its channels sit on consecutive
    addresses in channel order: logical index n -> start_address + n (e.g. RGBW:
    red 0, green 1, blue 2, white 3). start_address -1 = the device's lowest address.
    device_id picks one device when the line has several (see dali_devices). Swaps
    addresses (groups and scenes move with each channel). Returns a token; confirm
    runs the swaps and re-reads every channel's index to check."""
    from . import dali_units
    try:
        _controller._require()
        devices = dali_units.group_devices(await _dali_unit_infos(line))
        multi = [d for d in devices if len(d["channels"]) > 1]
        if device_id:
            multi = [d for d in devices if (d["device_id"] or "").upper() == device_id.upper()]
        if len(multi) != 1:
            return (f"{len(multi)} matching multi-channel device(s) on line {line}; pass "
                    "device_id (see dali_devices).")
        dev = multi[0]
        if dev["units"] and len(dev["channels"]) != dev["units"]:
            return (f"Device {dev['device_id']} reports {dev['units']} channels but only "
                    f"{len(dev['channels'])} answered; check the wiring/power and retry.")
        start = start_address if start_address >= 0 else min(c["address"] for c in dev["channels"])
        swaps = dali_units.plan_order(dev, start)
        taken = {c["address"] for d in devices if d is not dev for c in d["channels"]}
        clash = [start + c["index"] for c in dev["channels"] if start + c["index"] in taken]
        if clash:
            return (f"Addresses {clash} belong to another device; pick another start_address "
                    "or move that device first.")
    except Exception as err:  # noqa: BLE001
        return _err(err)
    plan = "\n".join(f"  swap address {a} <-> {b}" for a, b in swaps) or "  (already in order)"
    target = ", ".join(f"index {c['index']} -> {start + c['index']}"
                       for c in sorted(dev["channels"], key=lambda c: c["index"]))
    if not swaps:
        return f"Device {dev['device_id']}: channels already in order ({target})."

    async def run():
        acks = [await dali_units.remap(_controller, line, a, b) for a, b in swaps]
        infos = await _dali_unit_infos(line, [start + c["index"] for c in dev["channels"]])
        wrong = [i for i in infos if i["index"] is None or i["address"] != start + i["index"]]
        result = ", ".join(f"{i['address']}=index {i['index']}" for i in infos)
        if any(not a["ok"] for a in acks) or wrong:
            return (f"Problem: swaps {acks}; now {result}. Check with dali_devices before "
                    "using these addresses.")
        return f"Done and checked: {result}."

    token = _new_token([], plan)
    from .server import _pending
    _pending[token]["runner"] = run
    return (f"PREVIEW - device {dev['device_id']} ({len(dev['channels'])} channels) on line "
            f"{line}: {target}\n{plan}\nThis WRITES DALI short addresses. "
            f"Call confirm(token=\"{token}\") to re-address.")


# --- zone editor ---------------------------------------------------------------------

_ZONE_PROTOCOLS = {"dali": 0, "dmx": 1, "dt8": 2, "dt8_xy": 3}
_COLOUR_NAMES = {"red": "#FF0000", "green": "#00FF00", "blue": "#0000FF", "white": "#FFFFFF",
                 "warm": "#FFD580", "cool": "#AAD6FF", "amber": "#FFBF00",
                 "lime": "#BFFF00", "uv": "#8000FF"}


@server.tool()
async def preview_zone(zone: int, protocol: str, line: int, lights: int, channels: str,
                       start_address: int) -> str:
    """Create or change a Spektra colour zone (0-based; Zone 1 = 0). protocol: dali,
    dmx, dt8 (DALI DT8 RGBWAF: one address per light, channels = its colours) or
    dt8_xy (DALI DT8 colour coordinates: the channels are mixed into one xy point). line: 1-4. lights: how many fixtures. channels: the colour of each channel
    in order, e.g. 'red,green,blue,white' (also warm, cool, amber, lime, uv, or
    #RRGGBB). start_address: first DALI address / DMX channel; light n starts at
    start_address + n x channels. The controller always drives a zone per address
    (set_zone_colour can send a live colour to DALI groups instead). Zones apply after
    a save, which this includes. Returns a token."""
    try:
        zones = await _controller.pull_zones()
        old = next((z for z in zones if z.get("index") == zone), None)
        if old is None:
            return f"Zone {zone + 1} is not a zone slot on this controller."
        if protocol.lower() not in _ZONE_PROTOCOLS:
            return "protocol: dali, dmx, dt8 or dt8_xy."
        cols = []
        for c in channels.split(","):
            c = c.strip().lower()
            hexv = _COLOUR_NAMES.get(c, c.upper() if c.startswith("#") else None)
            if not hexv or len(hexv) != 7:
                return f"Unknown channel colour '{c}'."
            cols.append(hexv.upper())
        n, is_dali = len(cols), protocol.lower() in ("dali", "dt8", "dt8_xy")
        per_light = 1 if protocol.lower() in ("dt8", "dt8_xy") else n
        last = start_address + lights * per_light - 1
        if is_dali and (start_address < 0 or last > 63):
            return f"DALI addresses would run {start_address}-{last}; they must sit in 0-63."
        if not is_dali and not (1 <= start_address and last <= 512):
            return f"DMX channels would run {start_address}-{last}; they must sit in 1-512."
        new = dict(old, protocol=_ZONE_PROTOCOLS[protocol.lower()], linemask=1 << (line - 1),
                   numLights=lights, numChannels=n, channelColours=cols,
                   startAddress=start_address, multiLineAddressing=0,
                   daligroupoffset=None)
        msgs = [spektra_map.zone_to_message(new, _controller._next_id(), is_dali),
                spektra_map.zone_save_message(_controller._next_id())]
    except Exception as err:  # noqa: BLE001
        return _err(err)
    warn = ""
    if is_dali:
        # The controller's Spektra engine sends a stored 255 as a DALI arc level, which
        # is MASK ("no change"): that channel does not move. Live colour caps at 254.
        try:
            hits = [f"sequence {x['index'] + 1}" for x in await _controller.pull_sequences()
                    if any(255 in (c.get("channelValues") or []) for c in x.get("colours") or [])]
            hits += [f"theme {x['index'] + 1}" for x in await _controller.pull_themes()
                     if any(255 in (c.get("channelValues") or []) for c in x.get("colours") or [])]
        except Exception:  # noqa: BLE001 - the warning is best-effort
            hits = []
        if hits:
            warn = (f"\nNOTE: {len(hits)} stored item(s) use level 255 ({', '.join(hits[:8])}"
                    f"{', ...' if len(hits) > 8 else ''}). Played on a DALI zone, 255 is DALI "
                    "'no change', so those channels stay where they are - re-save them with "
                    "254 as the top value for DALI.")
    where = f"{'DALI addresses' if is_dali else 'DMX channels'} {start_address}-{last}"
    body = (f"  Zone {zone + 1}: {lights} light(s) x {n} channel(s) "
            f"({', '.join(channels.split(','))}), {protocol.upper()} line {line}, {where}")
    token = _new_token(msgs, body)
    return f"PREVIEW:\n{body}{warn}\nCall confirm(token=\"{token}\") to write and save."


# --- DALI-2 commissioning and instance settings --------------------------------------

@server.tool()
async def preview_dali2_readdress(line: int, from_address: int, to_address: int) -> str:
    """Give a DALI-2 control device (sensor, push button) a new short address. If
    to_address is in use the two devices swap. Sensor slots and DALI inputs that
    point at the old address are NOT changed - update them too (the preview lists
    them). Returns a token; confirm moves it and checks it answers at the new address."""
    from . import dali24, dali_units
    try:
        if not (0 <= from_address <= 63 and 0 <= to_address <= 63):
            return "Addresses are 0-63."
        n = await dali24.query(_controller, line, from_address, dali24.DEVICE, dali24.Q_INSTANCES)
        if n is None:
            return f"No DALI-2 device answers at line {line} address {from_address}."
        other = await dali24.query(_controller, line, to_address, dali24.DEVICE, dali24.Q_INSTANCES)
        meta = await _controller.read_system_counts()
        users = []
        for p in range(meta["profiles"]):
            for s in await _controller.pull_sensors(p):
                if s.get("line") == line and s.get("address") in (from_address, to_address):
                    users.append(f"sensor slot {s['index'] + 1} (profile {p + 1}) uses "
                                 f"address {s['address']}")
    except Exception as err:  # noqa: BLE001
        return _err(err)
    swap = other is not None
    body = (f"  DALI-2 line {line}: address {from_address} -> {to_address}"
            + (f" (swaps with the device already at {to_address})" if swap else ""))
    if users:
        body += "\n  Still pointing at the old address: " + "; ".join(sorted(set(users)))

    async def run():
        ack = await dali_units.remap(_controller, line, from_address, to_address, is24=True)
        if not ack["ok"]:
            return f"Refused: {ack}"
        at_new = await dali24.query(_controller, line, to_address, dali24.DEVICE, dali24.Q_INSTANCES)
        at_old = await dali24.query(_controller, line, from_address, dali24.DEVICE, dali24.Q_INSTANCES)
        ok = at_new == n and (at_old is not None) == swap
        return ((f"Done and checked: the device answers at {to_address}"
                 + (f"; the other device is now at {from_address}." if swap else
                    f"; nothing answers at {from_address}.")) if ok else
                f"Check failed: at {to_address} -> {at_new}, at {from_address} -> {at_old}.")

    token = _new_token([], body)
    from .server import _pending
    _pending[token]["runner"] = run
    return (f"PREVIEW:\n{body}\nThis WRITES a DALI-2 short address. "
            f"Call confirm(token=\"{token}\").")


@server.tool()
async def dali_find_duplicates(line: int, dali2: bool = True) -> str:
    """Look for short addresses used by more than one device on a line (DALI-2
    control devices by default; dali2=False for lights). Read-only, but it holds
    the line for a few seconds."""
    try:
        client = _controller._require()
        old = getattr(client, "_timeout", None)
        client._timeout = max(old or 0, 30.0)
        try:
            r = await ops.request(_controller, dali_identify_duplicates=pb.DALIIdentifyDuplicatesMessage(
                line_mask=1 << (line - 1), is24Bit=dali2))
        finally:
            if old is not None:
                client._timeout = old
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if r.WhichOneof("payload") != "dali_identify_duplicates":
        from .v2 import ack_summary
        return f"Refused: {ack_summary(r)}"
    dups = list(r.dali_identify_duplicates.possible_duplicates)
    if not dups:
        return f"No duplicate {'DALI-2 device' if dali2 else 'DALI gear'} addresses on line {line}."
    return (f"Possible duplicates on line {line}: "
            + ", ".join(f"address {d.address}" for d in dups)
            + ". Re-address one of each pair (commissioning) to separate them.")


@server.tool()
async def preview_dali2_instance(line: int, address: int, instance: int,
                                 enabled: str = "", report_seconds: int = -1,
                                 hysteresis_percent: int = -1, deadtime_ms: int = -1,
                                 hold_seconds: int = -1) -> str:
    """Configure one instance of a DALI-2 control device (dali2_device lists them):
    enabled ('on'/'off'), report_seconds (how often it reports while nothing
    changes; light/occupancy), hysteresis_percent (light: change needed before it
    reports), deadtime_ms (minimum gap between reports, 50 ms steps), hold_seconds
    (occupancy: hold time, 10 s steps). Only what you give changes. Returns a token."""
    from . import dali24
    try:
        t = await dali24.query(_controller, line, address, instance, dali24.Q_INSTANCE_TYPE)
        if t is None:
            return f"No instance {instance} at line {line} address {address}."
        motion, light = t == 3, t == 4
        steps = []
        if enabled:
            steps.append(("enable" if enabled.lower() in ("on", "true", "1") else "disable",
                          dali24.C_ENABLE_INSTANCE if enabled.lower() in ("on", "true", "1")
                          else dali24.C_DISABLE_INSTANCE, None))
        if report_seconds >= 0:
            if not (motion or light) or report_seconds > 255:
                return "report_seconds (0-255) is for occupancy and light instances."
            steps.append((f"report every {report_seconds} s",
                          dali24.C_LIGHT_SET_REPORT_TIMER if light else dali24.C_MOTION_SET_REPORT_TIMER,
                          report_seconds))
        if hysteresis_percent >= 0:
            if not light or hysteresis_percent > 25:
                return "hysteresis_percent (0-25) is for light instances."
            steps.append((f"hysteresis {hysteresis_percent}%", dali24.C_LIGHT_SET_HYSTERESIS,
                          hysteresis_percent))
        if deadtime_ms >= 0:
            v = round(deadtime_ms / 50)
            if not (motion or light) or v > 255:
                return "deadtime_ms (0-12750) is for occupancy and light instances."
            steps.append((f"dead time {v * 50} ms",
                          dali24.C_LIGHT_SET_DEADTIME_TIMER if light else dali24.C_MOTION_SET_DEADTIME_TIMER,
                          v))
        if hold_seconds >= 0:
            v = round(hold_seconds / 10)
            if not motion or v > 255:
                return "hold_seconds (0-2550) is for occupancy instances."
            steps.append((f"hold {v * 10} s", dali24.C_MOTION_SET_HOLD_TIMER, v))
        if not steps:
            return "Nothing to change."
    except Exception as err:  # noqa: BLE001
        return _err(err)
    body = (f"  DALI-2 line {line} address {address} instance {instance} "
            f"({dali24.INSTANCE_TYPES.get(t, t)}): " + ", ".join(s[0] for s in steps))

    async def run():
        acks = []
        for _label, op, val in steps:
            acks += await dali24.command(_controller, line, address, instance, op, dtr0=val)
        bad = [a for a in acks if not a.get("ok")]
        en = await dali24.query(_controller, line, address, instance, dali24.Q_INSTANCE_ENABLED)
        return ((f"Refused: {bad[0]}. " if bad else "Done. ")
                + f"Instance is now {'enabled' if en is not None else 'disabled'}.")

    token = _new_token([], body)
    from .server import _pending
    _pending[token]["runner"] = run
    return f"PREVIEW:\n{body}\nCall confirm(token=\"{token}\")."


# --- changed-slot detection (slot manifest checksums) ---------------------------------

def _snapshot_path():
    import os
    from pathlib import Path
    base = os.environ.get("SPEKTRA_AI_STATE") or str(Path.home() / ".spektra_ai")
    return Path(base) / "manifests.json"


def _load_snapshots() -> dict:
    p = _snapshot_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_snapshots(data: dict) -> None:
    p = _snapshot_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")


async def record_slot_snapshot() -> dict | None:
    """Take the controller's current sequence/theme manifest and store it as the
    baseline for its MAC. Returns the snapshot, or None without manifest support."""
    seq = await _controller.spektra_manifest("SEQUENCE")
    if seq is None:
        return None
    thm = await _controller.spektra_manifest("THEME") or {}
    macs = (await _controller.identify())["macs"]
    snap = {"sequences": {str(k): v for k, v in seq.items()},
            "themes": {str(k): v for k, v in thm.items()},
            "at": __import__("datetime").datetime.now().isoformat(timespec="seconds")}
    data = _load_snapshots()
    for mac in macs:
        data[mac] = snap
    _save_snapshots(data)
    return snap


def compare_snapshots(old: dict, new: dict) -> dict:
    out = {}
    for kind in ("sequences", "themes"):
        a, b = old.get(kind) or {}, new.get(kind) or {}
        out[kind] = {"added": sorted(int(k) for k in b.keys() - a.keys()),
                     "removed": sorted(int(k) for k in a.keys() - b.keys()),
                     "changed": sorted(int(k) for k in a.keys() & b.keys() if a[k] != b[k])}
    return out


@server.tool()
async def spektra_slot_changes(update: bool = True) -> str:
    """Which Spektra sequences and themes changed on the controller since the last
    snapshot (taken by the previous call, or by pull_spektra_file) - from the
    controller's per-slot checksums, without reading every slot. Needs firmware
    1.6.0+. update=True stores the current state as the new baseline. Read-only on
    the controller."""
    try:
        _controller._require()
        macs = (await _controller.identify())["macs"]
        old = next((v for m, v in _load_snapshots().items() if m in macs), None)
        seq = await _controller.spektra_manifest("SEQUENCE")
        if seq is None:
            return "This firmware has no slot manifest (needs 1.6.0+); use sync_status instead."
        thm = await _controller.spektra_manifest("THEME") or {}
        new = {"sequences": {str(k): v for k, v in seq.items()},
               "themes": {str(k): v for k, v in thm.items()}}
        if update:
            await record_slot_snapshot()
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if old is None:
        return (f"No earlier snapshot for this controller; recorded one now "
                f"({len(seq)} sequence(s), {len(thm)} theme(s)). Ask again later to see "
                "what changed.")
    diff = compare_snapshots(old, new)
    rows = [f"Changes since {old.get('at', 'the last snapshot')}:"]
    any_change = False
    for kind, d in diff.items():
        word = kind[:-1].title()
        for label in ("added", "removed", "changed"):
            if d[label]:
                any_change = True
                rows.append(f"  {kind} {label}: " + ", ".join(f"{word} {i + 1}" for i in d[label]))
    if not any_change:
        rows.append("  nothing - every sequence and theme slot is as it was.")
    return "\n".join(rows)


# --- DMX timing and line settings --------------------------------------------------------

_DMX_TIMING = {"fast": 0, "medium": 1, "slow": 2, "normal": 3}
_DMX_TIMING_NAME = {v: k for k, v in _DMX_TIMING.items()}


async def _dmx_line_props(index: int) -> dict:
    r = await _controller.read_admin("DMX_PROPERTIES", "GET",
                                     dmx_line_props=pb.AdminDMXLineParameters(line_index=index))
    if r.WhichOneof("payload") != "admin_message":
        return {}
    p = r.admin_message.dmx_line_props
    return {"line_index": p.line_index, "slots": p.output_slot_count,
            "sixteen_bit": p.use_16bit_output, "mapping": bytes(p.dmx_slot_mapping_raw)}


@server.tool()
async def get_dmx_settings() -> str:
    """DMX timing (global) and, for each DMX line, its output slot count, 16-bit
    output and whether a custom slot mapping is set. Read-only."""
    try:
        timing = await ops.admin_get(_controller, "DMX_TIMING")
        lines = await _controller.read_line_types()
        rows = [f"DMX timing: {str(timing.get('mode', '?')).replace('DMX_TIMING_', '').lower()}"]
        for i, t in enumerate(lines):
            if t in (2, 3):
                p = await _dmx_line_props(i)
                rows.append(f"  line {i + 1} ({'output' if t == 2 else 'input'}): "
                            f"{p.get('slots')} slots, {'16-bit' if p.get('sixteen_bit') else '8-bit'}"
                            + (", custom slot mapping" if p.get("mapping") else ""))
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return "\n".join(rows)


@server.tool()
async def preview_dmx_settings(timing: str = "", line: int = 0, slots: int = 0,
                               sixteen_bit: str = "") -> str:
    """Change DMX output timing (fast / medium / slow / normal - all meet the RDM
    timing spec; use slower for fixtures that miss frames) and/or one DMX line's
    output slot count (1-512) and 16-bit output ('on'/'off'; pairs adjacent slots
    as coarse/fine). line is 1-based. A custom slot mapping is kept. Returns a token."""
    from .v2 import admin, frame
    try:
        msgs, rows = [], []
        if timing:
            if timing.lower() not in _DMX_TIMING:
                return "timing: fast, medium, slow or normal."
            cur = await ops.admin_get(_controller, "DMX_TIMING")
            msgs.append(frame(admin(_controller._next_id(), "SET", "DMX_TIMING",
                                    dmx_timing_mode=pb.AdminDMXGlobalTimingConfig(
                                        mode=_DMX_TIMING[timing.lower()]))))
            rows.append(f"  timing: {str(cur.get('mode', '?')).replace('DMX_TIMING_', '').lower()}"
                        f" -> {timing.lower()}")
        if slots or sixteen_bit:
            lines = await _controller.read_line_types()
            if not 1 <= line <= len(lines) or lines[line - 1] not in (2, 3):
                return f"Line {line} is not a DMX line on this controller."
            if slots and not 1 <= slots <= 512:
                return "slots is 1-512."
            cur = await _dmx_line_props(line - 1)
            new_slots = slots or cur.get("slots") or 512
            new_16 = (sixteen_bit.lower() in ("on", "true", "1")) if sixteen_bit else cur.get("sixteen_bit", False)
            msgs.append(frame(admin(_controller._next_id(), "SET", "DMX_PROPERTIES",
                                    dmx_line_props=pb.AdminDMXLineParameters(
                                        line_index=line - 1, output_slot_count=new_slots,
                                        use_16bit_output=new_16,
                                        dmx_slot_mapping_raw=cur.get("mapping", b"")))))
            rows.append(f"  line {line}: {cur.get('slots')} slots {'16-bit' if cur.get('sixteen_bit') else '8-bit'}"
                        f" -> {new_slots} slots {'16-bit' if new_16 else '8-bit'}")
        if not msgs:
            return "Nothing to change."
        msgs = await _save_after(msgs)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    token = _new_token(msgs, "\n".join(rows))
    return "PREVIEW - DMX:\n" + "\n".join(rows) + f"\nCall confirm(token=\"{token}\")."


@server.tool()
async def dali_dt8_info(line: int, address: int) -> str:
    """A DALI DT8 (colour) driver: which colour modes it supports (RGBWAF and how many
    channels, colour temperature, xy, primaries), which mode is active, its live
    RGBWAF colour values and arc level, read back with DT8 queries. Read-only."""
    from . import colour as _colour
    try:
        _controller._require()
        i = await _colour.dt8_info(_controller, line, address)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if i.get("features_raw") is None:
        return f"Address {address} on line {line} does not answer DT8 queries (not DT8 gear?)."
    rows = [f"DT8 driver at line {line} address {address}:",
            f"  supports: {', '.join(i.get('supports') or ['?'])}",
            f"  active colour mode: {i.get('active', '?')}"
            + (f" - {'; '.join(i['flags'])}" if i.get("flags") else ""),
            f"  arc level: {i.get('level')}"]
    if i.get("tc_mirek"):
        from .colour import mirek_to_kelvin
        rows.append(f"  colour temperature now: {mirek_to_kelvin(i['tc_mirek'])} K "
                    f"({i['tc_mirek']} mirek)")
    lim = i.get("tc_limits_mirek") or {}
    if lim.get("warmest") and lim.get("coolest"):
        from .colour import mirek_to_kelvin
        rows.append(f"  colour temperature range: {mirek_to_kelvin(lim['warmest'])} K - "
                    f"{mirek_to_kelvin(lim['coolest'])} K")
    if i.get("xy"):
        rows.append(f"  xy now: x {i['xy'][0]}, y {i['xy'][1]}")
    if i.get("rgbwaf"):
        names = ["red", "green", "blue", "white", "amber", "free"]
        rows.append("  RGBWAF now: " + ", ".join(f"{n} {v}" for n, v in zip(names, i["rgbwaf"])))
    return "\n".join(rows)
