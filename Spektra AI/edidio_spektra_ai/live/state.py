"""Live state, transient actions, live colour and notifications."""

from __future__ import annotations

from .. import commands, ops
from ..server import _controller, server
from .common import _LOGIC_SOURCES, _LOGIC_COMPARE, _LOGIC_SOURCE_NAME, _LOGIC_COMPARE_NAME, _COMPARE_SYMBOLS, _INPUT_MODES, _INPUT_MODE_NAME, _OUTPUT_MODES, _err, _connect, _json, _seconds, _save_after  # noqa: F401

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
        from ..server import _parse_addresses
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
        "  dt8_colour_temp {line, target, kelvin 1000-20000} (stored as mirek/4, so the "
        "Kelvin is rounded; the reply shows what is sent)\n"
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
    from .. import notify
    from ..server import _log_channel
    try:
        cond = notify.preset_condition(event, index)
        _controller._require()
        ev = _controller._events
        if ev is None or not ev.running or len(ev.categories) < 6:
            await _controller.start_events(("trigger", "inputs", "dali", "sensors", "schedule",
                                            "lists", "config", "network", "event"))
        chan = notify.make_channel(channel, log_channel=_log_channel, webhook_url=webhook_url)
    except Exception as err:  # noqa: BLE001
        from ..server import _slots_hint
        return _err(err) + _slots_hint(err)
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
    colours while designing sequences and themes. colour: a name - 'red', 'warm
    white', 'amber' (lights that channel), 'orange', 'pink' (mixed from red/green/blue),
    'red+white', 'off' - or '#RRGGBB' (mapped onto the zone's red/green/blue channels)
    or one level per channel, '255,0,0,128' (0-255; DALI channels cap at 254). stop_playback stops a sequence/theme running on the
    zone first (it would overwrite the colour). dali_group (DALI zones, 0-15): send
    channel n to DALI group dali_group+n instead of per address - one frame per
    channel however many lights (each channel's gear must be in its group).
    Transient: nothing is stored. DMX, DALI, and DALI DT8 RGBWAF and xy zones."""
    from .. import colour as _colour
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
