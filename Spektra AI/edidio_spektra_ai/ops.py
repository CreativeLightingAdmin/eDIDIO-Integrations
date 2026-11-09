"""Live operations in the current protocol: health and diagnostics, the device log,
live state (inputs, lists, sensors, DALI status), actions (run a trigger, change
profile), device settings, ADDICT Wi-Fi and the controller's stored names.

Every function takes a connected ``SpektraController``. Reads are side-effect free
unless their docstring says otherwise (LINE_DIAGNOSTICS briefly perturbs lines).
A property the device does not have answers UNEXPECTED_TYPE; callers get
``{"unsupported": True}`` for it, so one call works on an eDIDIO and an ADDICT.
"""

from __future__ import annotations

from datetime import datetime

from edidio_control_py._v2 import eDS10_v2_pb2 as pb

from . import commands, device_log, v2

# Admin GETs a health check reads, and the payload arm each answers with.
_HEALTH_READS = ("CONTROLLER_LINES", "DEVICE_STATUS", "TIME_DIAGNOSTICS", "ETHERNET_DIAGNOSTICS",
                 "MEMORY_DIAGNOSTICS", "DALI_STATUS", "STORAGE_DIAGNOSTICS",
                 "CONFIG_STATUS", "WIFI_STATUS", "WIFI_DIAGNOSTICS")
DIAGNOSTICS = {
    "device_status": "DEVICE_STATUS", "config_status": "CONFIG_STATUS",
    "time": "TIME_DIAGNOSTICS", "ethernet": "ETHERNET_DIAGNOSTICS",
    "memory": "MEMORY_DIAGNOSTICS", "dali_status": "DALI_STATUS",
    "storage": "STORAGE_DIAGNOSTICS", "wifi_status": "WIFI_STATUS",
    "wifi_diagnostics": "WIFI_DIAGNOSTICS", "wifi_settings": "WIFI_SETTINGS",
    "line": "LINE_DIAGNOSTICS", "dmx_timing": "DMX_TIMING", "dmx_properties": "DMX_PROPERTIES",
    "dali_rx_tolerance": "DALI_RX_TOLERANCE", "dali_tx_half_bit_time": "DALI_TX_HALF_BIT_TIME",
    "ntp": "NTP_DETAILS", "lines": "CONTROLLER_LINES", "network": "NETWORK_PROPERTIES",
    "system": "SYSTEM_PROPERTIES", "logging": "SYSTEM_LOGGING", "link": "LINK",
}


class Unsupported(Exception):
    pass


async def admin_get(ctrl, target: str, **payload) -> dict:
    """GET one admin property -> its payload as a dict ({'unsupported': True} when the
    device does not have it)."""
    r = await ctrl.read_admin(target, "GET", **payload)
    if r.WhichOneof("payload") == "ack":
        ack = v2.ack_summary(r)
        if ack["code"] in ("UNEXPECTED_TYPE", "UNEXPECTED_CASE"):
            return {"unsupported": True}
        return {"error": ack}
    am = r.admin_message
    arm = am.WhichOneof("payload")
    if arm is None:
        return {}
    return v2.to_dict(getattr(am, arm))


async def admin_set(ctrl, target: str, **payload) -> dict:
    """SET one admin property -> ack summary (with the RejectReason on a refusal)."""
    return v2.ack_summary(await ctrl.read_admin(target, "SET", **payload))


async def request(ctrl, **field) -> "pb.EdidioMessage":
    return await v2.request(ctrl._require(), pb.EdidioMessage(message_id=ctrl._next_id(), **field))


# --- health ------------------------------------------------------------------

def _health_findings(r: dict) -> list:
    """Turn raw diagnostics into (level, text) findings. Thresholds are deliberately
    conservative: only things a technician would act on."""
    out = []
    ds = r.get("DEVICE_STATUS") or {}
    if ds.get("temperature") is not None and not ds.get("unsupported"):
        t = ds["temperature"]
        out.append(("warn" if t >= 60 else "ok", f"board temperature {t:.1f} C"))
    td = r.get("TIME_DIAGNOSTICS") or {}
    if td and not td.get("unsupported"):
        if td.get("vbat_low"):
            out.append(("warn", f"backup battery low ({td.get('vbat_voltage', 0):.0f} mV): "
                                "the clock and saved levels will not survive a power cut"))
        if not td.get("rtc_ever_been_set"):
            out.append(("warn", "the clock has never been set: schedules will not run on time"))
        if td.get("ntp_enabled_in_config"):
            fails, ok = td.get("ntp_sync_failure_count", 0), td.get("ntp_sync_success_count", 0)
            err = td.get("last_ntp_error", "")
            lvl = "ok" if err in ("NTP Success", "") else "warn"
            out.append((lvl, f"NTP {err or 'no attempt yet'} ({ok} ok / {fails} failed); "
                             f"last correction {td.get('last_ntp_correction_seconds', 0)} s"))
        else:
            out.append(("info", "NTP is off: the clock drifts unless it is set by hand"))
        now = td.get("rtc_unix_epoch_now")
        if now:
            # rtc_unix_epoch_now counts seconds since 2000-01-01 in the controller's
            # LOCAL time; compare with this computer's local clock on the same base.
            import calendar as _cal
            import time as _t
            pc_local = _cal.timegm(_t.localtime()) - 946684800
            skew = int(now - pc_local)
            if abs(skew) >= 120:
                out.append(("info", f"controller clock is {abs(skew) // 60} min "
                                    f"{'ahead of' if skew > 0 else 'behind'} this computer"
                                    " (a different time zone / daylight saving, or drift)"))
        if td.get("dst_enabled_in_config") is False:
            out.append(("info", "daylight saving is off in the controller"))
    eth = r.get("ETHERNET_DIAGNOSTICS") or {}
    if eth and not eth.get("unsupported"):
        link = eth.get("link_state", "")
        crc = sum(b.get("crc_count", 0) for b in eth.get("buckets", []))
        lvl = "ok" if link == "ETH_LINK_UP" and not crc else "warn"
        out.append((lvl, f"ethernet {link.replace('ETH_LINK_', '').lower()} "
                         f"{eth.get('link_speed_mbps', '?')} Mb/s "
                         f"{eth.get('duplex_mode', '').replace('ETH_DUPLEX_', '').lower()}"
                         f", {eth.get('link_up_count', 0)} link-up(s) since boot"
                         + (f", {crc} CRC errors in the last hour" if crc else "")))
    mem = r.get("MEMORY_DIAGNOSTICS") or {}
    tight = [t for t in mem.get("tasks", []) if t.get("stack_hwm_bytes", 1 << 30) < 64]
    if tight:
        out.append(("warn", "task stacks nearly full: "
                    + ", ".join(f"{t['name']} ({t['stack_hwm_bytes']} B free)" for t in tight)))
    dali = r.get("DALI_STATUS") or {}
    line_types = (r.get("CONTROLLER_LINES") or {}).get("lines")
    if dali and not dali.get("unsupported"):
        polling = dali.get("polling_active")
        for ln in dali.get("lines", []):
            n = ln.get("line_index", 0) + 1
            if line_types and n <= len(line_types) and line_types[n - 1] != "LINE_DALI":
                continue      # not a DALI line on this controller
            bp = ln.get("bus_power", "DALI_BUS_POWER_UNKNOWN").replace("DALI_BUS_POWER_", "")
            bits = [f"bus power {bp.lower()}"]
            lvl = "ok"
            if ln.get("bus_power_error") or bp in ("NONE", "SHORT", "LOW"):
                lvl = "warn"
            if ln.get("short_count"):
                bits.append(f"{ln['short_count']} short(s)")
                lvl = "warn"
            if ln.get("dual_supply_count"):
                bits.append(f"{ln['dual_supply_count']} dual-supply event(s)")
                lvl = "warn"
            if polling:
                bits.append(f"{ln.get('device_count', 0)} gear online, "
                            f"{ln.get('fault_count', 0)} faulty")
                if ln.get("fault_count"):
                    lvl = "warn"
            if bp != "UNKNOWN" or polling:
                out.append((lvl, f"DALI line {n}: " + ", ".join(bits)))
        if not polling:
            out.append(("info", "DALI status polling is off, so gear counts and lamp "
                                "failures are not monitored (set_dali_polling to turn it on)"))
    st = r.get("STORAGE_DIAGNOSTICS") or {}
    if st and not st.get("unsupported"):
        out.append(("info", "storage: " + ", ".join(f"{k}={v}" for k, v in list(st.items())[:6])))
    wifi = r.get("WIFI_STATUS") or {}
    if wifi and not wifi.get("unsupported"):
        wd = r.get("WIFI_DIAGNOSTICS") or {}
        rssi = wd.get("station_rssi")
        lvl = "ok" if wifi.get("station_state") == "WIFI_STATION_GOT_IP" and (rssi or -50) > -75 else "warn"
        out.append((lvl, f"Wi-Fi {wifi.get('station_state', '').replace('WIFI_STATION_', '').lower()}"
                         f" on '{wifi.get('station_ssid', '')}'"
                         + (f", RSSI {rssi} dBm" if rssi is not None else "")
                         + f"; access point '{wifi.get('ap_ssid', '')}' ({wifi.get('ap_clients', 0)} client(s))"))
        if wd.get("coprocessor_restarts") or wd.get("station_disconnects"):
            out.append(("warn", f"Wi-Fi co-processor restarts {wd.get('coprocessor_restarts', 0)}, "
                                f"station disconnects {wd.get('station_disconnects', 0)}"))
    cs = r.get("CONFIG_STATUS") or {}
    running = [i for i, v in enumerate(cs.get("list_status", [])) if v]
    if running:
        out.append(("info", "lists running: " + ", ".join(f"List {i + 1}" for i in running)))
    return out


async def health(ctrl, *, log_entries: int = 64) -> dict:
    """Read every health-relevant diagnostic + the recent device log, and summarise."""
    raw = {}
    for target in _HEALTH_READS:
        try:
            raw[target] = await admin_get(ctrl, target)
        except Exception as err:  # noqa: BLE001 — one failed read must not sink the check
            raw[target] = {"error": str(err)}
    info = await ctrl.identify()
    findings = _health_findings(raw)
    recent = []
    if log_entries:
        try:
            recent = (await read_log(ctrl, last=log_entries))["entries"]
        except Exception:  # noqa: BLE001 — ADDICT has no system log
            recent = []
    restarts = [e for e in recent if e["type"] == "Boot"]
    bad = [e for e in recent if e["severity"] in ("error", "warning") and e["type"] != "Net Link"]
    for e in bad[-5:]:
        when = e["time"].strftime("%Y-%m-%d %H:%M") if e.get("time") else "?"
        findings.append(("warn", f"log #{e['index']} {when}: {e['summary']}"))
    if restarts:
        last = restarts[-1]
        when = last["time"].strftime("%Y-%m-%d %H:%M") if last.get("time") else "?"
        findings.append(("info", f"{len(restarts)} restart(s) in the last {len(recent)} log "
                                 f"entries; last {when} ({last['summary']})"))
    return {"identity": info, "findings": findings, "raw": raw}


def format_health(h: dict) -> str:
    i = h["identity"]
    lines = [f"Health of {', '.join(i.get('macs', [])) or '?'} - firmware {i.get('firmware')}, "
             f"hardware {i.get('hardware')}"]
    icon = {"ok": "OK  ", "warn": "WARN", "info": "info"}
    order = {"warn": 0, "ok": 1, "info": 2}
    for lvl, text in sorted(h["findings"], key=lambda f: order.get(f[0], 3)):
        lines.append(f"  [{icon.get(lvl, lvl)}] {text}")
    n = sum(1 for f in h["findings"] if f[0] == "warn")
    lines.append(f"{n} warning(s)." if n else "No warnings.")
    return "\n".join(lines)


# --- device log ----------------------------------------------------------------

async def logging_state(ctrl) -> dict:
    """{'count': entries stored, 'categories': 'trigger,spektra'|'trigger'|...}"""
    r = await ctrl.read_admin("SYSTEM_LOGGING")
    if r.WhichOneof("payload") != "admin_message":
        raise Unsupported(f"no system log ({v2.ack_summary(r)['code']})")
    d = r.admin_message.data
    return {"count": d.uint_data, "categories": d.string_data or "none"}


async def read_log(ctrl, *, last: int = 100, start: int | None = None) -> dict:
    """Read log entries: the newest ``last`` (default) or ``last`` from ``start``.
    Reads one earlier page when it can, so the first entries have a wall clock."""
    state = await logging_state(ctrl)
    n = state["count"]
    if start is None:
        start = max(0, n - last)
    end = min(n, start + last)
    first = max(0, start - device_log.PAGE_SIZE)   # extra context for the clock anchor
    msgs = []
    pos = first
    while pos < end:
        count = min(device_log.PAGE_SIZE, end - pos)
        r = await request(ctrl, logs_read=pb.SystemLogReadMessage(
            log_start_address=pos, logs_requested=count))
        if r.WhichOneof("payload") != "logs_read":
            raise RuntimeError(f"log read refused at {pos}: {v2.ack_summary(r)}")
        msgs.extend(r.logs_read.logs)
        pos += count
    entries = [e for e in device_log.decode_entries(msgs, first) if e["index"] >= start]
    return {"count": n, "categories": state["categories"], "entries": entries}


async def set_logging(ctrl, categories: str) -> dict:
    """SET which categories are logged: 'trigger', 'spektra', 'trigger,spektra' or
    'none' (system events are always logged)."""
    names = [c.strip().lower() for c in categories.split(",") if c.strip()]
    if names != ["none"] and not all(c in device_log.LOGGING_NAMES for c in names):
        raise ValueError("categories: 'trigger', 'spektra', 'trigger,spektra' or 'none'")
    return await admin_set(ctrl, "SYSTEM_LOGGING",
                           data=pb.PayloadMessage(string_data=",".join(names)))


async def clear_log(ctrl) -> dict:
    return v2.ack_summary(await ctrl.read_admin("SYSTEM_LOGGING", "RESET"))


async def crash_log(ctrl) -> dict:
    r = await request(ctrl, crash_log=pb.CrashLogMessage())
    if r.WhichOneof("payload") != "crash_log":
        return {"unsupported": True, "ack": v2.ack_summary(r)}
    d = v2.to_dict(r.crash_log)
    for k in ("crash_data", "task_hwm_data"):
        d.pop(k, None)
    d["crash_type_name"] = device_log.CRASH_TYPES.get(d.get("crash_type", 0), "none")
    d["reset_cause_names"] = [n for b, n in device_log.RESET_CAUSES.items()
                              if d.get("reset_cause", 0) & b]
    return d


async def counters(ctrl) -> dict:
    """Lifetime counters: presses per input, starts per list, fires per schedule,
    reboots, screen time."""
    r = await request(ctrl, metadata_read=pb.SystemMetaDataReadMessage())
    if r.WhichOneof("payload") != "metadata_read":
        return {"unsupported": True, "ack": v2.ack_summary(r)}
    return v2.to_dict(r.metadata_read)


async def connections(ctrl) -> dict:
    r = await request(ctrl, connection_status=pb.ConnectionStatusMessage())
    if r.WhichOneof("payload") != "connection_status":
        return {"unsupported": True, "ack": v2.ack_summary(r)}
    return v2.to_dict(r.connection_status)


# --- live state ------------------------------------------------------------------

async def input_state(ctrl) -> dict:
    """Which physical inputs are LOW (closed / active) right now, 0-based."""
    r = await request(ctrl, input_request=pb.InputStateMessage(use_mask=True))
    if r.WhichOneof("payload") != "input_response":
        return {"unsupported": True, "ack": v2.ack_summary(r)}
    mask = r.input_response.input_mask
    # The mask is the pin level: a set bit is an open (HIGH) input, a clear bit a
    # closed one (LOW = active).
    count = await _input_count(ctrl)
    active = [i for i in range(count) if not mask & (1 << i)]
    return {"mask": mask, "count": count, "active": active,
            "inactive": [i for i in range(count) if mask & (1 << i)]}


async def _input_count(ctrl) -> int:
    r = await request(ctrl, diag_message=pb.DiagnosticMessage(
        type=pb.DiagnosticMessageType.DIAGNOSTIC_SYSTEM_INFO))
    if r.WhichOneof("payload") == "diag_system":
        return r.diag_system.input_count or 0
    return 0


async def dali_status_cache(ctrl, line: int) -> list:
    """The controller's cached QUERY STATUS byte per short address (line 1-based).
    0 = nothing cached (no gear, or gear that has never reported a flag)."""
    r = await request(ctrl, diag_message=pb.DiagnosticMessage(
        type=pb.DiagnosticMessageType.DALI_STATUS_CACHE, line=line))
    if r.WhichOneof("payload") != "level_cache_response":
        raise Unsupported(f"DALI status cache: {v2.ack_summary(r)['code']}")
    return list(r.level_cache_response.levels)[:64]


async def dali_levels(ctrl, line: int, addresses=None) -> list:
    """Actual level + status of DALI gear on a line. Gear comes from the controller's
    status cache (or ``addresses``); each is then queried, because the controller's
    level cache is not maintained (1.6.3 writes it only on OFF)."""
    from . import dali
    cache = await dali_status_cache(ctrl, line)
    targets = list(addresses) if addresses else [a for a, s in enumerate(cache) if s]
    out = []
    for a in targets:
        st = await ctrl.dali_query(line, a, pb.DALIQueryType.DALI_QUERY_STATUS)
        if not st.get("responded"):
            out.append({"address": a, "present": False, "cached_status": cache[a]})
            continue
        lv = await ctrl.dali_query(line, a, pb.DALIQueryType.DALI_QUERY_ACTUAL_LEVEL)
        flags = dali.decode_status(st["data"])
        out.append({"address": a, "present": True,
                    "level": lv["data"] if lv.get("responded") else None,
                    "faults": [k for k in ("gear_failure", "lamp_failure", "limit_error")
                               if flags[k]],
                    "on": flags["lamp_on"], "fading": flags["fade_running"],
                    "power_cycle_seen": flags["power_cycle_seen"],
                    "reset_state": flags["reset_state"]})
    return out


async def config_status(ctrl) -> dict:
    """Running lists, the active alarm, per-sensor light states, burn-in states."""
    return await admin_get(ctrl, "CONFIG_STATUS")


async def sensor_states(ctrl) -> list:
    """Live state of every sensor (paginated 20 per request on firmware with paging)."""
    out, offset = [], 0
    while True:
        r = await request(ctrl, sensor_query=pb.SensorsQuery(offset=offset))
        if r.WhichOneof("payload") != "sensor_query":
            if not out:
                raise Unsupported(f"sensor query: {v2.ack_summary(r)['code']}")
            break
        page = list(r.sensor_query.sensors)
        for i, s in enumerate(page):
            d = v2.to_dict(s)
            d["index"] = r.sensor_query.offset + i
            out.append(d)
        total = r.sensor_query.total_count
        offset = r.sensor_query.offset + len(page)
        if not page or not total or offset >= total:
            break
    return out


# --- live actions ------------------------------------------------------------------

async def run_trigger(ctrl, cmd: dict) -> dict:
    """Run one trigger now, as if an input/list fired it (ExternalTriggerMessage).
    Transient: nothing is stored."""
    t = pb.TriggerMessage(type=cmd["commandtype"], zone=cmd.get("zone", 0),
                          line_mask=cmd.get("linemask", 0), target_index=cmd.get("target", 0),
                          value=cmd.get("value", 0), query_index=cmd.get("query", 0))
    return v2.ack_summary(await request(ctrl, external_trigger=pb.ExternalTriggerMessage(trigger=t)))


async def change_profile(ctrl, profile: int) -> dict:
    return v2.ack_summary(await request(ctrl, change_profile=pb.ChangeProfileMessage(profile=profile)))


async def set_dali_polling(ctrl, on: bool) -> dict:
    """POLL_ACTIVE: the controller polls its DALI gear so DALI_STATUS reports gear
    counts, lamp failures and missing devices (and logic can act on them)."""
    return await admin_set(ctrl, "POLL_ACTIVE", data=pb.PayloadMessage(uint_data=1 if on else 0))


async def line_diagnostics(ctrl) -> dict:
    """Probe each line's daughterboard vs its configured type. Briefly perturbs each
    line (a DALI half-bit pulse / a DMX receive window): run on demand only."""
    return await admin_get(ctrl, "LINE_DIAGNOSTICS")


# --- device settings ---------------------------------------------------------------

async def settings(ctrl) -> dict:
    """Name, project, location/clock, NTP, network, lines, DALI/DMX timing - whatever
    the device has."""
    out = {}
    for key, target in (("device_name", "DEVICE_NAME"), ("project_name", "PROJECT_NAME"),
                        ("system", "SYSTEM_PROPERTIES"), ("network", "NETWORK_PROPERTIES"),
                        ("ntp", "NTP_DETAILS"), ("lines", "CONTROLLER_LINES"),
                        ("dali_polling", "POLL_ACTIVE"), ("dali_rx_tolerance", "DALI_RX_TOLERANCE"),
                        ("dali_tx_half_bit_time", "DALI_TX_HALF_BIT_TIME"),
                        ("dmx_timing", "DMX_TIMING"), ("logging", "SYSTEM_LOGGING"),
                        ("link", "LINK")):
        try:
            d = await admin_get(ctrl, target)
        except Exception as err:  # noqa: BLE001
            d = {"error": str(err)}
        if d.get("unsupported"):
            continue
        if set(d) <= {"string_data", "uint_data", "int_data", "float_data", "bool_data"}:
            d = d.get("string_data") or d.get("uint_data", d.get("float_data", d))
        out[key] = d
    return out


SETTABLE = {
    "device_name": ("DEVICE_NAME", "string"),       # up to 31 bytes on 1.6.3
    "project_name": ("PROJECT_NAME", "string"),
    "latitude": ("LATITUDE", "float"), "longitude": ("LONGITUDE", "float"),
    "utc_offset": ("LOCAL_UTC_OFFSET", "float"), "daylight_savings": ("DAYLIGHT_SAVINGS", "uint"),
    "dali_polling": ("POLL_ACTIVE", "uint"),
    "dali_rx_tolerance": ("DALI_RX_TOLERANCE", "uint"),
    "dali_tx_half_bit_time": ("DALI_TX_HALF_BIT_TIME", "uint"),
}


def setting_message(ctrl, key: str, value) -> bytes:
    """Build the framed SET for one simple setting (validated against firmware limits)."""
    if key not in SETTABLE:
        raise ValueError(f"unknown setting '{key}'. Settable: {', '.join(SETTABLE)}")
    target, kind = SETTABLE[key]
    if key == "device_name" and len(str(value).encode("utf-8")) > 31:
        raise ValueError("a controller name is at most 31 bytes")
    if key == "latitude" and not -90 <= float(value) <= 90:
        raise ValueError("latitude is -90..90")
    if key == "longitude" and not -180 <= float(value) <= 180:
        raise ValueError("longitude is -180..180")
    if key == "utc_offset" and not -14 <= float(value) <= 14:
        raise ValueError("UTC offset is -14..14 hours")
    data = {"string": lambda v: pb.PayloadMessage(string_data=str(v)),
            "float": lambda v: pb.PayloadMessage(float_data=float(v)),
            "uint": lambda v: pb.PayloadMessage(uint_data=int(bool(v)) if isinstance(v, bool) else int(v))}[kind](value)
    return v2.frame(v2.admin(ctrl._next_id(), "SET", target, data=data))


# --- ADDICT Wi-Fi --------------------------------------------------------------------

async def wifi(ctrl) -> dict:
    out = {}
    for key, target in (("settings", "WIFI_SETTINGS"), ("status", "WIFI_STATUS"),
                        ("diagnostics", "WIFI_DIAGNOSTICS")):
        d = await admin_get(ctrl, target)
        if d.get("unsupported"):
            raise Unsupported("this controller has no Wi-Fi (WIFI_* is ADDICT V3 only)")
        out[key] = d
    return out


def wifi_settings_message(ctrl, *, mode: str, station_ssid: str = "",
                          station_password: str | None = None, ap_channel: int = 0) -> bytes:
    """Framed WIFI_SETTINGS SET. ``station_password=None`` keeps the stored password."""
    modes = {v.name.replace("WIFI_MODE_", "").lower(): v.number
             for v in pb.WifiMode.DESCRIPTOR.values}
    m = modes.get(mode.lower().replace("wifi_mode_", ""))
    if m is None:
        raise ValueError(f"mode: one of {', '.join(modes)}")
    if ap_channel and not 1 <= ap_channel <= 13:
        raise ValueError("access point channel is 1-13 (0 keeps it)")
    ws = pb.AdminWifiSettingsMessage(mode=m, station_ssid=station_ssid,
                                     keep_station_password=station_password is None,
                                     station_password=station_password or "",
                                     ap_channel=ap_channel)
    return v2.frame(v2.admin(ctrl._next_id(), "SET", "WIFI_SETTINGS", wifi_settings=ws))


# --- names stored on the controller (DataAliases) --------------------------------

ALIAS_KINDS = ("profiles", "inputs", "outputs", "lists", "sensors", "dali_inputs", "schedules")


def _alias_class(kind: str):
    return getattr(pb, pb.DataAliases.DESCRIPTOR.fields_by_name[kind].message_type.name)


async def aliases(ctrl, kind: str) -> list:
    """The names stored on the controller for profiles/inputs/outputs/lists/sensors/
    dali_inputs/schedules (what the OLED and other clients show)."""
    if kind not in ALIAS_KINDS:
        raise ValueError(f"kind: one of {', '.join(ALIAS_KINDS)}")
    sub = _alias_class(kind)
    req = pb.DataAliases(command=pb.AliasCommandType.GET_ALIASES, **{kind: sub()})
    r = await request(ctrl, data_aliases=req)
    if r.WhichOneof("payload") != "data_aliases":
        raise Unsupported(f"aliases: {v2.ack_summary(r)['code']}")
    msg = getattr(r.data_aliases, kind)
    field = msg.DESCRIPTOR.fields[0].name
    return list(getattr(msg, field))


def aliases_message(ctrl, kind: str, names: list) -> bytes:
    if kind not in ALIAS_KINDS:
        raise ValueError(f"kind: one of {', '.join(ALIAS_KINDS)}")
    sub = _alias_class(kind)
    msg = sub()
    getattr(msg, msg.DESCRIPTOR.fields[0].name).extend(str(n) for n in names)
    req = pb.DataAliases(command=pb.AliasCommandType.SET_ALIASES, **{kind: msg})
    return v2.frame(pb.EdidioMessage(message_id=ctrl._next_id(), data_aliases=req))


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


__all__ = ["admin_get", "admin_set", "health", "format_health", "read_log", "set_logging",
           "clear_log", "crash_log", "counters", "connections", "input_state", "config_status",
           "sensor_states", "run_trigger", "change_profile", "set_dali_polling",
           "line_diagnostics", "settings", "setting_message", "wifi", "wifi_settings_message",
           "aliases", "aliases_message", "commands"]


# --- SD card (6/9-pole with a card) ---------------------------------------------------

SD_CHUNK = 512           # the device returns at most 512 bytes per read
SD_PAGE = 16             # and at most 16 directory entries per page


def fat_datetime(date: int, time: int) -> str:
    """FAT date/time -> 'YYYY-MM-DD HH:MM:SS' ('' when unset)."""
    if not date:
        return ""
    y, mo, d = 1980 + (date >> 9), (date >> 5) & 0x0F, date & 0x1F
    h, mi, s = time >> 11, (time >> 5) & 0x3F, (time & 0x1F) * 2
    return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"


def _sd_path(path: str) -> str:
    return str(path or "").strip().strip("/")   # the card takes 'logs/sys', not '/logs/sys'


def _sd_status(code: int) -> str:
    return pb.SdStatusCode.Name(code)


async def sd_space(ctrl) -> dict:
    r = await request(ctrl, sd_file_control=pb.SdFileControlMessage(
        command=pb.SdFileControlType.SD_GET_SPACE))
    if r.WhichOneof("payload") != "sd_file_control":
        raise Unsupported(f"no SD card support ({v2.ack_summary(r)['code']})")
    d = r.sd_file_control
    out = {"status": _sd_status(d.status), "free_bytes": d.free_bytes,
           "total_bytes": d.total_bytes}
    # 0 of 0 with SD_OK means the capacity was never measured (the protocol's
    # SD_CAPACITY_UNKNOWN), not a full card.
    out["capacity_known"] = d.status == pb.SdStatusCode.SD_OK and d.total_bytes > 0
    return out


async def sd_policy(ctrl) -> dict:
    """Per-category log folders, size budgets and bytes on the card."""
    r = await request(ctrl, sd_log_policy=pb.SdLogPolicyMessage())
    if r.WhichOneof("payload") != "sd_log_policy":
        raise Unsupported(f"no SD log policy ({v2.ack_summary(r)['code']})")
    pol = v2.to_dict(r.sd_log_policy)
    r = await request(ctrl, sd_log_config=pb.SdLogConfigMessage(is_write=False))
    mask = r.sd_log_config.current_mask if r.WhichOneof("payload") == "sd_log_config" else None
    for e in pol.get("entries", []):
        e["enabled"] = None if mask is None else bool(mask & (1 << e.get("category", 0)))
        e["current_disk_bytes"] = int(e.get("current_disk_bytes", 0))
    return pol


_SD_LIST_CACHE: dict = {}      # (host, path) -> (time, result); log folders are large
SD_LIST_TTL = 120.0


async def sd_list(ctrl, path: str, *, offset: int = 0, limit: int = 0,
                  fresh: bool = False) -> dict:
    """Directory entries (name, size, modified, is_dir). limit 0 = everything. A full
    listing is cached for SD_LIST_TTL s (a 2000-file log folder takes ~35 s to list)."""
    import time
    path = _sd_path(path)
    key = (getattr(ctrl, "host", None), path)
    if not offset and not limit and not fresh:
        hit = _SD_LIST_CACHE.get(key)
        if hit and time.monotonic() - hit[0] < SD_LIST_TTL:
            return hit[1]
    out, off = [], offset
    while True:
        r = await request(ctrl, sd_dir_list=pb.SdDirListMessage(path=path, offset=off,
                                                                max_entries=SD_PAGE))
        if r.WhichOneof("payload") != "sd_dir_list":
            raise Unsupported(f"no SD card support ({v2.ack_summary(r)['code']})")
        d = r.sd_dir_list
        if d.status != pb.SdStatusCode.SD_OK:
            raise RuntimeError(f"SD list '{path}': {_sd_status(d.status)}")
        for e in d.entries:
            out.append({"name": e.name, "size": e.size, "is_dir": e.is_directory,
                        "modified": fat_datetime(e.date, e.time)})
        off += len(d.entries)
        if not d.has_more or not d.entries or (limit and len(out) >= limit):
            break
    result = {"path": path, "entries": out[:limit] if limit else out}
    if not offset and not limit:
        _SD_LIST_CACHE[key] = (time.monotonic(), result)
    return result


async def sd_read(ctrl, path: str, *, offset: int = 0, length: int = 0) -> dict:
    """Read bytes from a file (length 0 = to the end). Returns {data, file_size}."""
    path = _sd_path(path)
    buf, pos, size = bytearray(), offset, None
    while True:
        want = SD_CHUNK if not length else min(SD_CHUNK, offset + length - pos)
        if want <= 0:
            break
        r = await request(ctrl, sd_file_read=pb.SdFileReadMessage(path=path, offset=pos,
                                                                  length=want))
        if r.WhichOneof("payload") != "sd_file_read":
            raise Unsupported(f"no SD card support ({v2.ack_summary(r)['code']})")
        d = r.sd_file_read
        if d.status != pb.SdStatusCode.SD_OK:
            raise RuntimeError(f"SD read '{path}' @{pos}: {_sd_status(d.status)}")
        size = d.file_size
        buf += d.data[:d.bytes_read]
        pos += d.bytes_read
        if not d.bytes_read or pos >= size:
            break
    return {"path": path, "offset": offset, "file_size": size or 0, "data": bytes(buf)}
