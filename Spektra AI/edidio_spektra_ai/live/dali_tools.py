"""DALI-2 control devices and sensors, DALI devices and channel order, DALI-2 commissioning, and DALI gear settings and scene levels."""

from __future__ import annotations

from edidio_control_py._v2 import eDS10_v2_pb2 as pb
from .. import commands, ops, spektra_map
from ..server import _controller, _new_token, server
from .common import _LOGIC_SOURCES, _LOGIC_COMPARE, _LOGIC_SOURCE_NAME, _LOGIC_COMPARE_NAME, _COMPARE_SYMBOLS, _INPUT_MODES, _INPUT_MODE_NAME, _OUTPUT_MODES, _err, _connect, _json, _seconds, _save_after  # noqa: F401
from .programming import _dali_targets, _profiles

# --- DALI-2 control devices and sensors ---------------------------------------------

@server.tool()
async def dali2_scan(line: int, addresses: str = "0-63") -> str:
    """Find DALI-2 control devices (sensors, push buttons, rotaries) on a line - they
    use their own 24-bit address space, separate from the lights. Read-only."""
    from .. import dali24
    from ..server import _parse_addresses
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
    from .. import dali24
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
        from ..v2 import ack_summary
        r = await ops.request(_controller, sensor_command=pb.SensorCommandMessage(
            index=index, type=pb.SensorCommandType.Value(names[action.lower()])))
        ack = ack_summary(r)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return f"Sensor {index + 1}: {action} sent." if ack["ok"] else f"Refused: {ack}"


# --- DALI devices / channel order -----------------------------------------------------

async def _dali_unit_infos(line: int, addresses=None) -> list:
    from .. import dali_units
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
    from .. import dali_units
    from ..server import _parse_addresses
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
    from .. import dali_units
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
    from ..server import _pending
    _pending[token]["runner"] = run
    return (f"PREVIEW - device {dev['device_id']} ({len(dev['channels'])} channels) on line "
            f"{line}: {target}\n{plan}\nThis WRITES DALI short addresses. "
            f"Call confirm(token=\"{token}\") to re-address.")


# --- DALI-2 commissioning and instance settings --------------------------------------

@server.tool()
async def preview_dali2_readdress(line: int, from_address: int, to_address: int) -> str:
    """Give a DALI-2 control device (sensor, push button) a new short address. If
    to_address is in use the two devices swap. Sensor slots and DALI inputs that
    point at the old address are NOT changed - update them too (the preview lists
    them). Returns a token; confirm moves it and checks it answers at the new address."""
    from .. import dali24, dali_units
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
    from ..server import _pending
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
        from ..v2 import ack_summary
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
    from .. import dali24
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
    from ..server import _pending
    _pending[token]["runner"] = run
    return f"PREVIEW:\n{body}\nCall confirm(token=\"{token}\")."


# --- DALI gear settings and scene levels ------------------------------------------------

async def _gear_targets(line: int, spec: str) -> tuple:
    """'0-3' / 'g2' / 'all' -> (command targets, addresses to read back)."""
    targets = [255 if t == 80 else t for t in _dali_targets(spec)]
    readback = []
    for t in targets:
        if t <= 63:
            readback.append(t)
        else:
            present = [d["address"] for d in await _controller.dali_scan(line)]
            if t == 255:
                readback += present
            else:
                readback += [a for a in present
                             if (t - 64) in await _controller.dali_query_groups(line, a)]
    return targets, sorted(set(readback))


@server.tool()
async def dali_gear_settings(line: int, addresses: str = "") -> str:
    """Each DALI fitting's stored settings: actual, min, max and physical-min levels,
    power-on and system-failure levels, fade time and rate, extended fade.
    addresses: '0-3' (default: every fitting on the line). Read-only."""
    from .. import dali_gear as g
    from ..server import _parse_addresses
    try:
        addrs = (_parse_addresses(addresses) if addresses.strip()
                 else [d["address"] for d in await _controller.dali_scan(line)])
        rows = [f"DALI line {line}:"]
        for a in addrs:
            s = await g.read_settings(_controller, line, a)
            rows.append(
                f"  address {a}: level {s.get('actual_level')}, min {s.get('min_level')} "
                f"(physical {s.get('physical_min')}), max {s.get('max_level')}, power-on "
                f"{g.describe_level(s.get('power_on_level'))}, system failure "
                f"{g.describe_level(s.get('system_failure_level'))}, fade "
                f"{s.get('fade_time_s')} s (code {s.get('fade_time_code')}), rate "
                f"{s.get('fade_rate_steps_s')} steps/s, extended fade {s.get('extended_fade_s')} s")
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return "\n".join(rows) if len(rows) > 1 else f"No DALI gear on line {line}."


@server.tool()
async def preview_dali_gear_settings(line: int, target: str, power_on: str = "",
                                     system_failure: str = "", min_level: int = -1,
                                     max_level: int = -1, fade_seconds: float = -1,
                                     fade_rate: float = -1,
                                     extended_fade_seconds: float = -1) -> str:
    """Change stored DALI gear settings on target ('0-3', 'g2' or 'all'):
    power_on / system_failure: a level 0-254, or 'last' (power-on: last level;
    system failure: no change); min_level / max_level 0-254 (min >= the gear's
    physical minimum, which it enforces); fade_seconds (nearest standard fade time,
    0 = use extended fade); fade_rate (steps/s, nearest standard rate);
    extended_fade_seconds (0.1 s - 16 min; used when fade time is 0). Only what you
    give changes. Returns a token; confirm writes them and reads every fitting back."""
    from .. import dali_gear as g
    try:
        targets, readback = await _gear_targets(line, target)
        plan = []

        def level(v, name):
            v = v.strip().lower()
            if v in ("last", "mask", "no change"):
                return g.MASK
            n = int(v)
            if not 0 <= n <= 254:
                raise ValueError(f"{name} is 0-254 or 'last'")
            return n
        if power_on:
            plan.append(("power_on_level", level(power_on, "power_on")))
        if system_failure:
            plan.append(("system_failure_level", level(system_failure, "system_failure")))
        for key, v in (("min_level", min_level), ("max_level", max_level)):
            if v >= 0:
                if not 1 <= v <= 254:
                    return f"{key} is 1-254."
                plan.append((key, v))
        if min_level >= 0 and max_level >= 0 and min_level > max_level:
            return "min_level must not exceed max_level."
        if fade_seconds >= 0:
            plan.append(("fade_time", g.nearest_code(g.FADE_TIME, fade_seconds)))
        if fade_rate >= 0:
            plan.append(("fade_rate", g.nearest_code(g.FADE_RATE, fade_rate)))
        if extended_fade_seconds >= 0:
            plan.append(("extended_fade", g.extended_fade_code(extended_fade_seconds)))
        if not plan:
            return "Nothing to change."
    except Exception as err:  # noqa: BLE001
        return _err(err)

    def show(k, v):
        if k == "fade_time":
            return f"fade time {g.FADE_TIME[v]} s (code {v})"
        if k == "fade_rate":
            return f"fade rate {g.FADE_RATE[v]} steps/s (code {v})"
        if k == "extended_fade":
            return f"extended fade {g.extended_fade_seconds(v)} s"
        return f"{k.replace('_', ' ')} {g.describe_level(v)}"
    body = (f"  DALI line {line}, target {target}: " + "; ".join(show(k, v) for k, v in plan)
            + f"\n  will read back addresses {readback or '(none found)'}")

    async def run():
        for t in targets:
            for k, v in plan:
                await g.store(_controller, line, t, g.STORE[k], v)
        rows = []
        for a in readback:
            s = await g.read_settings(_controller, line, a)
            bad = []
            for k, v in plan:
                got = {"fade_time": s.get("fade_time_code"), "fade_rate": s.get("fade_rate_code"),
                       "extended_fade": None}.get(k, s.get(k))
                if k == "extended_fade":
                    got = v if s.get("extended_fade_s") == g.extended_fade_seconds(v) else s.get("extended_fade_s")
                if k == "min_level" and s.get("physical_min") and v < s["physical_min"]:
                    v = s["physical_min"]            # the gear raises it to its physical minimum
                if got != v:
                    bad.append(f"{k} {got} (wanted {v})")
            rows.append(f"  address {a}: " + ("OK" if not bad else "; ".join(bad)))
        return "Written and read back:\n" + "\n".join(rows) if rows else "Written (nothing to read back)."

    token = _new_token([], body)
    from ..server import _pending
    _pending[token]["runner"] = run
    return f"PREVIEW:\n{body}\nCall confirm(token=\"{token}\") to write."


@server.tool()
async def dali_scene_levels(line: int, addresses: str = "") -> str:
    """The 16 stored DALI scene levels of each fitting ('-' = not in that scene).
    addresses: '0-3' (default: every fitting on the line). Read-only."""
    from .. import dali_gear as g
    from ..server import _parse_addresses
    try:
        addrs = (_parse_addresses(addresses) if addresses.strip()
                 else [d["address"] for d in await _controller.dali_scan(line)])
        rows = [f"DALI line {line} scenes 0-15:"]
        for a in addrs:
            sc = await g.read_scenes(_controller, line, a)
            rows.append(f"  address {a}: " + " ".join("-" if v is None else str(v) for v in sc))
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return "\n".join(rows) if len(rows) > 1 else f"No DALI gear on line {line}."


@server.tool()
async def preview_dali_scene(line: int, target: str, scene: int, level: str) -> str:
    """Store a DALI scene level in the gear: target '0-3', 'g2' or 'all'; scene 0-15;
    level 0-254, or 'remove' to take the target out of the scene. Recall it with
    dali_recall_scene or run_command dali_scene. Returns a token; confirm writes and
    reads every fitting back."""
    from .. import dali_gear as g
    try:
        if not 0 <= scene <= 15:
            return "scene is 0-15."
        remove = level.strip().lower() == "remove"
        value = None if remove else int(level)
        if value is not None and not 0 <= value <= 254:
            return "level is 0-254 or 'remove'."
        targets, readback = await _gear_targets(line, target)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    what = "remove from" if remove else f"store level {value} as"
    body = (f"  DALI line {line}, target {target}: {what} scene {scene}\n"
            f"  will read back addresses {readback or '(none found)'}")

    async def run():
        for t in targets:
            if remove:
                await g.store(_controller, line, t, g.REMOVE_SCENE_BASE + scene, None)
            else:
                await g.store(_controller, line, t, g.STORE_SCENE_BASE + scene, value)
        rows = []
        for a in readback:
            v = await g.query(_controller, line, a, g.Q_SCENE_BASE + scene)
            want = g.MASK if remove else value
            rows.append(f"  address {a}: scene {scene} = {v} " + ("OK" if v == want else f"(wanted {want})"))
        return "Written and read back:\n" + "\n".join(rows) if rows else "Written."

    token = _new_token([], body)
    from ..server import _pending
    _pending[token]["runner"] = run
    return f"PREVIEW:\n{body}\nCall confirm(token=\"{token}\") to write."
