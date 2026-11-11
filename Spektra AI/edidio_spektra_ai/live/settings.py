"""Device, network and clock settings, Wi-Fi and names, line types, DMX timing."""

from __future__ import annotations

import ipaddress
import json
from edidio_control_py._v2 import eDS10_v2_pb2 as pb
from .. import ops, spektra_map
from ..server import _controller, _new_token, server
from .common import _LOGIC_SOURCES, _LOGIC_COMPARE, _LOGIC_SOURCE_NAME, _LOGIC_COMPARE_NAME, _COMPARE_SYMBOLS, _INPUT_MODES, _INPUT_MODE_NAME, _OUTPUT_MODES, _err, _connect, _json, _seconds, _save_after  # noqa: F401

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
    from ..server import _pending
    _pending[token]["runner"] = run
    return ("PREVIEW:\n" + "\n".join(diff)
            + ("\nThe controller will REBOOT (about 30 s offline)." if reboot else "")
            + f"\nCall confirm(token=\"{token}\") to apply.")


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
        from ..v2 import frame as _frame_v2
        frame = _frame_v2(
            pb.EdidioMessage(message_id=_controller._next_id(), admin_message=pb.AdminMessage(
                command=pb.AdminCommandType.SET,
                target=pb.AdminPropertyType.NETWORK_PROPERTIES, network_properties=new)))
    except Exception as err:  # noqa: BLE001
        return _err(err)

    async def run():
        from ..v2 import ack_summary
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
            from .. import discovery
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
    from ..server import _pending
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
    from ..v2 import admin, frame
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
        from ..v2 import ack_summary
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
    from ..v2 import admin, frame
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
    from .. import colour as _colour
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
        from ..colour import mirek_to_kelvin
        rows.append(f"  colour temperature now: {mirek_to_kelvin(i['tc_mirek'])} K "
                    f"({i['tc_mirek']} mirek)")
    lim = i.get("tc_limits_mirek") or {}
    if lim.get("warmest") and lim.get("coolest"):
        from ..colour import mirek_to_kelvin
        rows.append(f"  colour temperature range: {mirek_to_kelvin(lim['warmest'])} K - "
                    f"{mirek_to_kelvin(lim['coolest'])} K")
    if i.get("xy"):
        rows.append(f"  xy now: x {i['xy'][0]}, y {i['xy'][1]}")
    if i.get("rgbwaf"):
        names = ["red", "green", "blue", "white", "amber", "free"]
        rows.append("  RGBWAF now: " + ", ".join(f"{n} {v}" for n, v in zip(names, i["rgbwaf"])))
    return "\n".join(rows)
