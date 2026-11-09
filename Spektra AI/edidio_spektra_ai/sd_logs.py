"""Decode the controller's binary SD-card logs: DALI bus logs (logs/dali/DAL_*.BIN)
and structured event logs (logs/events/EVT_*.BIN).

File layout (little-endian):
  header, 12 bytes: magic "EDIO" (0x4544494F), format version, line, protocol
                    (0 DALI, 1 DMX, 2 events), reserved, RTC start (seconds since
                    2000-01-01, controller local time)
  DALI entry, 12 bytes:  ms since start u32, line u8 (0xFF = system), direction u8
                         (0 TX, 1 RX, 0xFF meta), frame type u8, status u8, frame u32
  event entry, 39 bytes: type u8, length u8, then a payload starting with ms since
                         start u32 and type-specific fields
Entry time = RTC start + ms, in the controller's local time.
"""

from __future__ import annotations

import datetime as _dt
import struct

from . import dali_names as N

MAGIC = 0x4544494F
HEADER_SIZE = 12
DALI_ENTRY = 12
EVENT_ENTRY = 39
PROTOCOLS = {0: "DALI", 1: "DMX", 2: "events"}
_EPOCH = _dt.datetime(2000, 1, 1)

# --- DALI --------------------------------------------------------------------------

TX_STATUS = {0: "SUCCESS", 240: "NO_ECHO", 241: "BUSY", 242: "TIMEOUT", 243: "ERROR",
             244: "PARTIAL", 245: "COLLISION", 246: "ATTEMPT",
             1: "NO_ECHO", 2: "BUSY", 3: "TIMEOUT", 4: "ERROR", 5: "PARTIAL",
             6: "COLLISION", 7: "ATTEMPT"}
TX_ERRORS = {"NO_ECHO", "TIMEOUT", "ERROR", "PARTIAL", "COLLISION"}
RX_ERRORS = {2: "no reply", 6: "partial frame", 254: "error sending", 255: "error receiving"}
RX_TO_TX = {3: 0, 4: 1, 5: 2}            # RX frame type -> 8/16/24-bit

COMMANDS = dict(N.DALI_COMMANDS)
for _i in range(16):
    COMMANDS.update({0x10 + _i: f"GO_TO_SCENE_{_i}", 0x40 + _i: f"STORE_DTR_AS_SCENE_{_i}",
                     0x50 + _i: f"REMOVE_FROM_SCENE_{_i}", 0x60 + _i: f"ADD_TO_GROUP_{_i}",
                     0x70 + _i: f"REMOVE_FROM_GROUP_{_i}", 0xB0 + _i: f"QUERY_SCENE_{_i}",
                     0xE0 + _i: f"QUERY_APP_EXTEND_{_i}"})

_EVENT_SCHEMES = {(0, 0, 0): "device", (0, 0, 1): "device+instance",
                  (1, 0, 0): "device group", (1, 0, 1): "instance",
                  (1, 1, 0): "instance group"}


def describe_8(frame: int) -> str:
    v = frame & 0xFF
    return "reply YES (0xFF)" if v == 0xFF else f"reply {v} (0x{v:02X})"


def describe_16(frame: int) -> str:
    a, d = (frame >> 8) & 0xFF, frame & 0xFF
    cmd = COMMANDS.get(d, f"CMD_0x{d:02X}")
    if a in (0xFE, 0xFF):
        return f"broadcast {cmd}" if a & 1 else f"broadcast arc {d}"
    if a >= 0xA0 and a & 1:
        return f"{N.DALI_SPECIAL_COMMANDS.get(a, f'SPECIAL_0x{a:02X}')} {d}"
    who = f"group {(a >> 1) & 0x0F}" if a & 0x80 else f"address {(a >> 1) & 0x3F}"
    return f"{who} {cmd}" if a & 1 else f"{who} arc {d}"


def _instance(b: int) -> str:
    fixed = {0xFF: "all instances", 0xFE: "device", 0xFD: "feature broadcast",
             0xFC: "device feature"}
    if b in fixed:
        return fixed[b]
    kind = {0x00: "instance", 0x20: "feature instance", 0x60: "feature type",
            0x80: "instance group", 0xA0: "feature group", 0xC0: "type"}.get(b & 0xE0)
    return f"{kind} {b & 0x1F}" if kind else f"instance 0x{b:02X}"


def describe_24(frame: int) -> str:
    b0, b1, b2 = (frame >> 16) & 0xFF, (frame >> 8) & 0xFF, frame & 0xFF
    if b0 == 0xC1:
        return f"{N.DALI_24_SPECIAL_COMMANDS.get(b2, f'SPECIAL_0x{b2:02X}')} {b1}"
    if not b0 & 1:                                       # event frame from a sensor/button
        return _describe_event_frame(frame)
    if b0 == 0xFF:
        who = "broadcast"
    elif b0 == 0xFD:
        who = "broadcast unaddressed"
    else:
        who = (f"device group {(b0 >> 1) & 0x3F}" if b0 & 0x80
               else f"device {(b0 >> 1) & 0x3F}")
    table = N.DALI_24_DEVICE_COMMANDS if b1 == 0xFE else N.DALI_24_INSTANCE_COMMANDS
    return f"{who} {_instance(b1)} {table.get(b2, f'CMD_0x{b2:02X}')}"


def _describe_event_frame(frame: int) -> str:
    key = ((frame >> 23) & 1, (frame >> 22) & 1, (frame >> 15) & 1)
    scheme = _EVENT_SCHEMES.get(key, "unknown")
    info, itype = frame & 0x3FF, (frame >> 10) & 0x1F
    tname = N.DALI_INSTANCE_TYPES.get(itype, f"type {itype}").lower()
    if scheme == "device":
        who = f"device {(frame >> 17) & 0x3F} ({tname})"
    elif scheme == "device+instance":
        who = f"device {(frame >> 17) & 0x3F} instance {(frame >> 10) & 0x1F}"
    elif scheme == "device group":
        who = f"device group {(frame >> 17) & 0x1F}"
    elif scheme == "instance":
        who = f"{tname} instance {(frame >> 16) & 0x3F}"
    elif scheme == "instance group":
        who = f"{tname} instance group {(frame >> 16) & 0x1F}"
    else:
        return f"event 0x{frame:06X}"
    typed = scheme in ("device", "instance", "instance group")      # bits 14-10 = type
    if itype == 3 and typed:                                          # motion (IEC 62386-303)
        bits = [n for b, n in ((1, "movement"), (2, "occupied"), (4, "repeat")) if info & b]
        what = ("+".join(bits) if bits else "vacant/idle") + f" (info 0x{info:03X})"
    elif itype == 4 and typed:                                        # light (IEC 62386-304)
        what = f"illuminance {info}"
    else:
        what = f"info 0x{info:03X}"
    return f"EVENT {who}: {what}"


def decode_dali_entry(raw: bytes) -> dict:
    # ms is signed: an entry can be logged just before the header's RTC second.
    ms, line, direction, ftype, status, frame = struct.unpack("<iBBBBI", raw[:DALI_ENTRY])
    e = {"ms": ms, "line": None if line == 0xFF else line + 1, "frame": frame,
         "error": False}
    if direction == 0xFF:
        e["dir"] = "META"
        e["text"] = (f"{frame} entries not logged (logger overflow)" if ftype == 0
                     else "log file rotated" if ftype == 1 else f"meta {ftype} {frame}")
        e["error"] = ftype == 0 and frame > 0
        return e
    if direction == 0:
        e["dir"] = "TX"
        st = TX_STATUS.get(status, f"STATUS_{status}")
        width = ftype
        e["status"] = st
        e["error"] = st in TX_ERRORS
    else:
        e["dir"] = "RX"
        if ftype in RX_ERRORS:
            e["error"] = ftype != 2              # no reply is normal for a 'no' answer
            e["text"] = RX_ERRORS[ftype] + (f" ({status} bits: 0x{frame & 0xFFFFFF:06X})"
                                             if ftype == 6 and status else "")
            return e
        width = RX_TO_TX.get(ftype, -1)
    if width == 0:
        e["text"] = describe_8(frame)
    elif width == 1:
        e["text"] = describe_16(frame)
    elif width == 2:
        e["text"] = describe_24(frame)
    else:
        e["text"] = f"frame type {ftype} 0x{frame:08X}"
    if e["dir"] == "TX" and e["status"] != "SUCCESS":
        e["text"] += f" [{e['status']}]"
    return e


# --- events --------------------------------------------------------------------------

EVENT_TYPES = {1: "input", 2: "sensor", 3: "list", 4: "schedule", 5: "config", 6: "boot",
               7: "network", 8: "spektra", 0xFF: "meta"}
GPIO_PRESS = {0: "short press", 1: "long press", 2: "latched low", 3: "latched high"}
DALI_PRESS = {0: "short press", 1: "long press", 2: "pressed", 3: "released", 4: "rotary"}
SENSOR_TRANSITIONS = {1: "occupied", 2: "warning", 3: "off (vacant)",
                      4: "re-enabled", 5: "light level", 6: "override"}
CONFIG_SOURCES = {0: "network", 1: "BACnet", 2: "device menu", 3: "profile change",
                  4: "internal"}
CONFIG_WHAT = {0: "inputs", 1: "outputs", 2: "IR", 3: "sensors", 5: "lists",
               7: "schedules", 8: "burn-ins", 9: "project", 13: "lists (extended)",
               14: "logic", 15: "DALI inputs", 17: "Spektra sequence", 18: "Spektra theme",
               19: "Spektra settings", 20: "Spektra calendar"}
RESET_BITS = {0: "power-on", 1: "software", 2: "watchdog", 3: "window watchdog",
              4: "low power", 5: "reset pin"}
NET_EVENTS = {0: "link up", 1: "link down", 2: "TCP connect", 3: "TCP disconnect",
              4: "TLS connect", 5: "TLS disconnect", 6: "TCP keep-alive",
              7: "TLS keep-alive", 8: "TCP keep-alive (legacy)",
              9: "TLS keep-alive (legacy)"}
NET_REASONS = {1: "timeout", 2: "reset", 3: "closed", 4: "stream end", 5: "send failed",
               6: "TLS handshake", 7: "TLS init", 8: "setup failed", 9: "link down",
               10: "no route", 11: "not connected", 12: "no free slot",
               13: "task failed", 255: "other"}
SPEKTRA_ACTIONS = {1: "start", 2: "stop", 3: "pause"}
SPEKTRA_TARGETS = {1: "sequence", 2: "theme"}
_DROP_KINDS = ["input", "sensor", "list", "schedule", "config", "boot", "network",
               "spektra"]


def _trigger(t: int, target: int, value: int) -> str:
    from .device_log import TRIGGER_NAMES
    return f"{TRIGGER_NAMES.get(t, f'TRIGGER_{t}')} target {target} value {value}"


def _ip(b: bytes) -> str:
    return ".".join(str(x) for x in b[:4])


def _mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b[:6])


def decode_event_entry(raw: bytes) -> dict | None:
    etype, length = raw[0], raw[1]
    if etype == 0 and not any(raw):
        return None                                   # unused (zero-filled) slot
    p = raw[2:]
    ms = struct.unpack_from("<i", p, 0)[0]          # signed, as for DALI entries
    kind = EVENT_TYPES.get(etype, f"type 0x{etype:02X}")
    e = {"ms": ms, "kind": kind, "error": False}
    if etype == 1:
        idx, src, press, t, tgt, val, mask = p[4:11]
        names = DALI_PRESS if src == 15 else GPIO_PRESS
        e["index"] = idx
        e["text"] = (f"input {idx} ({'DALI' if src == 15 else 'GPIO'}) "
                     f"{names.get(press, f'press {press}')} -> {_trigger(t, tgt, val)}"
                     f" lines 0x{mask:02X}")
    elif etype == 2:
        idx, tr, light, motion = p[4:8]
        lux = struct.unpack_from("<H", p, 8)[0]
        e["index"] = idx
        e["text"] = (f"sensor {idx} {SENSOR_TRANSITIONS.get(tr, f'transition {tr}')} "
                     f"(light state {light}, motion {motion}, lux {lux})")
    elif etype == 3:
        idx, step, state, t, tgt, val = p[4:10]
        e["index"] = idx
        e["text"] = (f"list {idx + 1} step {step + 1} (state {state}) -> "
                     f"{_trigger(t, tgt, val)}")
    elif etype == 4:
        alarm, is_end, t, tgt, val, mask = p[4:10]
        e["index"] = alarm
        e["text"] = (f"schedule {alarm} {'end' if is_end else 'start'} -> "
                     f"{_trigger(t, tgt, val)} lines 0x{mask:02X}")
    elif etype == 5:
        rt, item, src, profile = p[4:8]
        ip, port, mac = _ip(p[8:12]), struct.unpack_from("<H", p, 12)[0], _mac(p[14:20])
        what = CONFIG_WHAT.get(rt, f"type {rt}")
        item_s = "all" if item == 0xFF else str(item)
        how = CONFIG_SOURCES.get(src, f"source {src}")
        if src == 3 and rt == 9:
            e["text"] = f"profile switched to {item_s}"
        else:
            by = f" by {ip}:{port}" if src == 0 and ip != "0.0.0.0" else ""
            e["text"] = f"{what} (item {item_s}) changed via {how}{by} [profile {profile}]"
        e["mac"] = mac
    elif etype == 6:
        cause, profile = p[4], p[5]
        causes = [n for b, n in RESET_BITS.items() if cause & (1 << b)] or [f"0x{cause:02X}"]
        e["text"] = f"boot ({', '.join(causes)}) [profile {profile}]"
        e["error"] = bool(cause & 0x0C)              # watchdog resets
    elif etype == 7:
        ev = p[4]
        ip, port, mac = _ip(p[5:9]), struct.unpack_from("<H", p, 9)[0], _mac(p[11:17])
        reason = p[17]
        rs = NET_REASONS.get(reason, f"reason 0x{reason:02X}") if reason else ""
        rejected = ev in (2, 4) and reason != 0
        e["text"] = (f"{NET_EVENTS.get(ev, f'net event {ev}')} {ip}:{port}"
                     + ("" if mac == "00:00:00:00:00:00" else f" ({mac})")
                     + (f" REJECTED ({rs})" if rejected else f" ({rs})" if rs else ""))
        e["error"] = rejected
    elif etype == 8:
        zone, action, target, index = p[4:8]
        e["text"] = (f"Spektra zone {zone}: {SPEKTRA_ACTIONS.get(action, f'action {action}')} "
                     f"{SPEKTRA_TARGETS.get(target, f'target {target}')} {index}")
    elif etype == 0xFF:
        sub = p[4]
        if sub == 0:
            n = 8 if length >= 33 else 7
            drops = {k: struct.unpack_from("<I", p, 5 + i * 4)[0]
                     for i, k in enumerate(_DROP_KINDS[:n]) if 5 + i * 4 + 4 <= len(p)}
            total = sum(drops.values())
            busy = ", ".join(f"{k} {v}" for k, v in drops.items() if v)
            e["text"] = f"{total} events not logged" + (f" ({busy})" if busy else "")
            e["error"] = total > 0
        else:
            e["text"] = "log file rotated" if sub == 1 else f"meta {sub}"
    else:
        e["text"] = f"unknown event type 0x{etype:02X}: {p[4:12].hex(' ')}"
    return e


# --- files ---------------------------------------------------------------------------

def parse_header(data: bytes) -> dict:
    if len(data) < HEADER_SIZE:
        raise ValueError("file too short for a log header")
    magic, ver, line, proto, _r, start = struct.unpack("<IBBBBI", data[:HEADER_SIZE])
    if magic != MAGIC:
        raise ValueError(f"not an eDIDIO binary log (magic 0x{magic:08X})")
    return {"version": ver, "line": line + 1 if line != 0xFF else None,
            "protocol": PROTOCOLS.get(proto, f"protocol {proto}"), "protocol_id": proto,
            "rtc_start": start, "start": _EPOCH + _dt.timedelta(seconds=start)}


LOG_INDEX_MAX = 10000        # file numbers wrap modulo this
LOGMETA_PATH = "logs/LOGMETA.DAT"
LOGMETA_MAGIC = 0x4C524F54   # "LROT"
# LOGMETA.DAT category order -> file prefix.
LOGMETA_PREFIXES = ["SYS", "TRG", "INP", "DAL", "SEN", "SCH", "LST", "CFG", "NET", "SDC",
                    "EVT"]


def parse_logmeta(data: bytes) -> dict:
    """logs/LOGMETA.DAT (the firmware's rotation state) -> {prefix: {current, oldest,
    files}}. Empty if it can't be read. v3: 12-byte entries with a file count; v2: 8."""
    import zlib
    if len(data) < 8 or struct.unpack_from("<I", data, 0)[0] != LOGMETA_MAGIC:
        return {}
    ver, count = data[4], data[5]
    size = {3: 12, 2: 8}.get(ver)
    if not size or len(data) < 8 + count * size + 4:
        return {}
    crc_at = 8 + count * size
    if zlib.crc32(data[:crc_at]) != struct.unpack_from("<I", data, crc_at)[0]:
        return {}
    out = {}
    for i in range(min(count, len(LOGMETA_PREFIXES))):
        cur, old = struct.unpack_from("<HH", data, 8 + i * size)
        files = (struct.unpack_from("<H", data, 8 + i * size + 8)[0] if ver == 3
                 else (cur - old) % LOG_INDEX_MAX + 1)
        out[LOGMETA_PREFIXES[i]] = {"current": cur % LOG_INDEX_MAX,
                                    "oldest": old % LOG_INDEX_MAX, "files": files}
    return out


def _number(name: str):
    import re
    m = re.search(r"(\d+)\.\w+$", name)
    return int(m.group(1)) if m else None


def latest_first(names: list, current: int | None = None) -> list:
    """Log file names newest first. With the firmware's current index (LOGMETA.DAT),
    count backwards from it, wrapping at 10000; without it, highest number first.
    File dates follow the controller clock, so they are not used."""
    def key(n):
        k = _number(n)
        if k is None:
            return (1, LOG_INDEX_MAX, n)
        return (0, (current - k) % LOG_INDEX_MAX if current is not None else -k, n)
    return sorted(names, key=key)


def is_binary_log(data: bytes) -> bool:
    return len(data) >= 4 and struct.unpack_from("<I", data, 0)[0] == MAGIC


def decode(data: bytes) -> tuple[dict, list]:
    """(header, entries). Each entry has 'time' (controller local datetime), 'text',
    'error' and type-specific fields."""
    h = parse_header(data)
    out = []
    if h["protocol_id"] == 2:
        size, fn = EVENT_ENTRY, decode_event_entry
    elif h["protocol_id"] == 0:
        size, fn = DALI_ENTRY, decode_dali_entry
    else:
        raise ValueError(f"{h['protocol']} logs are not decoded")
    for off in range(HEADER_SIZE, len(data) - size + 1, size):
        raw = data[off:off + size]
        if not any(raw):
            continue
        e = fn(raw)
        if e is None:
            continue
        e["time"] = h["start"] + _dt.timedelta(milliseconds=e["ms"])
        out.append(e)
    return h, out


def format_entry(e: dict) -> str:
    t = e["time"].strftime("%Y-%m-%d %H:%M:%S.") + f"{e['time'].microsecond // 1000:03d}"
    if "dir" in e:
        where = f"L{e['line']}" if e.get("line") else "SYS"
        head = f"{t} {where} {e['dir']:<4}"
    else:
        head = f"{t} {e['kind']:<8}"
    return f"{head} {'!! ' if e['error'] else ''}{e['text']}"


def select(entries: list, *, text: str = "", errors_only: bool = False,
           since: _dt.datetime | None = None, until: _dt.datetime | None = None) -> list:
    out = []
    for e in entries:
        if errors_only and not e["error"]:
            continue
        if since and e["time"] < since:
            continue
        if until and e["time"] > until:
            continue
        if text and text.lower() not in format_entry(e).lower():
            continue
        out.append(e)
    return out


def summarise(header: dict, entries: list) -> str:
    """One line: what the file covers and how many entries / errors."""
    if not entries:
        return f"{header['protocol']} log, no entries"
    errs = sum(1 for e in entries if e["error"])
    first, last = entries[0]["time"], entries[-1]["time"]
    line = f", line {header['line']}" if header.get("line") and header["protocol_id"] == 0 else ""
    return (f"{header['protocol']} log{line}: {len(entries)} entries, "
            f"{first:%Y-%m-%d %H:%M:%S} to {last:%Y-%m-%d %H:%M:%S}"
            + (f", {errs} flagged" if errs else ""))
