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
    keeps it). keep_password=True keeps the stored station password. The device
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
