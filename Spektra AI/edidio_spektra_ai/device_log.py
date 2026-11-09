"""Read and decode the controller's own system log (EEPROM/NOR, Tag 51).

Decoded the way SpektraPlus decodes the system log:
entries are timestamped by ``time_since_boot``; BOOT / USER / NTP(at 0) entries
carry a wall clock that anchors the entries after them. From firmware 1.6.3 a BOOT
entry also packs the restart summary (reset cause, crash type, failed boot phase)
into its flags, and the log records triggers and Spektra activity by default.

The decoded trigger entries are also converted to ``event_log.LogEvent`` so the
offline "lights won't turn off" analysis runs straight on a live controller.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from edidio_control_py._v2 import eDS10_v2_pb2 as v2pb

from . import commands
from .event_log import LogEvent

PAGE_SIZE = 32          # the device returns at most 32 entries per request
ERASED_TIME = 0xFFFFFFFF

TYPE_NAMES = {0: "Boot", 1: "Net Link", 2: "NTP Sync", 3: "Trigger", 4: "Spektra",
              5: "Schedule", 6: "User", 7: "Crash", 8: "Watchdog Reset",
              9: "Crash (Extended)", 10: "Boot Failure"}
_CRASH, _WATCHDOG, _CRASH_EXT, _BOOT_ESC = 7, 8, 9, 10

START_FLAGS = {0x01: "Memory erased", 0x02: "Settings reset to defaults",
               0x04: "Spektra reset to defaults"}
RESET_CAUSES = {0x01: "Power-on", 0x02: "Software", 0x04: "Watchdog",
                0x08: "Window watchdog", 0x10: "Low power", 0x20: "Reset pin"}
CRASH_TYPES = {1: "HardFault", 2: "MemManage", 3: "BusFault", 4: "UsageFault",
               5: "Stack overflow", 6: "Watchdog", 7: "Assert"}
BOOT_PHASES = {1: "Clock", 2: "Early init", 3: "Display", 4: "Config",
               5: "GPIO/DALI/DMX", 6: "Network", 7: "SD card", 8: "Scheduler", 9: "Running"}
LOG_CATEGORIES = {0x01: "System", 0x02: "Triggers", 0x04: "Spektra"}
USER_SECTOR_START = 0x80
READ_TYPES = {0: "Input", 1: "Output", 2: "IR", 3: "Sensor", 5: "List", 7: "Schedule",
              8: "Burn-In", 9: "Project", 10: "Network", 11: "Device", 12: "Poll",
              13: "List (Extended)", 14: "Logic", 15: "DALI Input", 16: "DMX"}
SPEKTRA_TARGETS = {0: "Settings", 1: "Sequence", 2: "Theme", 3: "Static", 4: "Calendar",
                   5: "Show", 6: "Live"}
SPEKTRA_ACTIONS = {0: "Start", 1: "Stop", 2: "Pause", 3: "Save"}
TRIGGER_NAMES = {v.number: v.name for v in v2pb.TriggerType.DESCRIPTOR.values}
DALI_COMMANDS = {v.number: v.name for v in v2pb.DALICommandType.DESCRIPTOR.values}

# SYSTEM_LOGGING SET text accepts these names (firmware config_logging_text_parse).
LOGGING_NAMES = ("trigger", "spektra")


def _bits(value: int, names: dict) -> list:
    return [n for b, n in names.items() if value & b]


def log_clock(date_packed: int, time_packed: int) -> datetime | None:
    """System-log TimeClock: date = Year<<16 | Month<<8 | Day (no weekday byte),
    time = Hour<<16 | Minute<<8 | Second (top byte may hold the failed boot phase)."""
    try:
        return datetime(2000 + ((date_packed >> 16) & 0xFF), (date_packed >> 8) & 0xFF,
                        date_packed & 0xFF, (time_packed >> 16) & 0xFF,
                        (time_packed >> 8) & 0xFF, time_packed & 0xFF)
    except ValueError:
        return None


def boot_summary(flags: int, time_packed: int = 0) -> dict | None:
    """The 1.6.3 restart summary, or None (older firmware sent start flags only)."""
    s = {"start": flags & 0xFF, "cause": (flags >> 8) & 0xFF, "crash": (flags >> 16) & 0xFF,
         "watchdog": (flags >> 24) & 0xFF, "phase": (time_packed >> 24) & 0xFF}
    ok = s["start"] <= 0x07 and 0x01 <= s["cause"] <= 0x3F and s["crash"] <= 7 and s["phase"] <= 9
    return s if ok else None


def _records_after_boot(s: dict | None) -> list:
    if not s:
        return []
    out = []
    if s["phase"]:
        out.append(_BOOT_ESC)
    if s["cause"] & 0x04 and not s["crash"]:
        out.append(_WATCHDOG)
    if s["crash"]:
        out += [_CRASH, _CRASH_EXT]
    return out


def dali_target(target: int) -> str:
    if target <= 63:
        return f"Address {target}"
    if target <= 79:
        return f"Group {target - 64}"
    return "Broadcast" if target == 80 else f"Target {target}"


def lines_of(mask: int) -> list:
    return [i + 1 for i in range(8) if mask & (1 << i)]


def describe_trigger(t) -> dict:
    """A TriggerMessage -> readable fields (type name, lines, target, value)."""
    name = TRIGGER_NAMES.get(t.type, f"TRIGGER_{t.type}")
    out = {"type": name, "lines": lines_of(t.line_mask), "target": t.target_index,
           "value": t.value, "zone": t.zone}
    if name.startswith("DALI_ARC") or name.startswith("DALI_COMMAND"):
        out["target_name"] = dali_target(t.target_index)
    if name.startswith("DALI_COMMAND"):
        out["command"] = DALI_COMMANDS.get(t.value, str(t.value))
    return out


def decode_entry(msg, index: int, expected_type: int | None = None) -> dict:
    """One SystemLogMessage -> dict {index, type, time_since_boot, clock?, summary,
    severity, fields}."""
    tsb = msg.time_since_boot
    which = msg.WhichOneof("packet")
    e = {"index": index, "time_since_boot": tsb, "severity": "info", "fields": {}}
    f = e["fields"]
    if which == "boot":
        e["type"] = "Boot"
        tc = msg.boot.timeclock
        e["clock"] = log_clock(tc.date, tc.time)
        s = boot_summary(msg.boot.flags, tc.time)
        e["_records"] = _records_after_boot(s)
        if s:
            cause = ", ".join(_bits(s["cause"], RESET_CAUSES)) or "Unknown"
            f["reset_cause"] = cause
            e["summary"] = f"Boot - {cause}"
            if s["crash"]:
                f["crash"] = CRASH_TYPES.get(s["crash"], f"Type {s['crash']}")
                e["summary"] = f"Boot after crash - {f['crash']}"
                e["severity"] = "error"
            if s["phase"]:
                f["failed_boot_phase"] = BOOT_PHASES.get(s["phase"], f"Phase {s['phase']}")
                e["severity"] = "error"
            if s["cause"] & 0x04 and e["severity"] == "info":
                e["severity"] = "warning"
            start = ", ".join(_bits(s["start"], START_FLAGS))
            if start:
                f["start"] = start
        else:
            start = ", ".join(_bits(msg.boot.flags & 0x07, START_FLAGS))
            e["summary"] = f"Boot - {start}" if start else "Boot"
    elif which == "netlink":
        e["type"] = "Net Link"
        up = msg.netlink.is_linked
        e["summary"] = "Network link up" if up else "Network link down"
        e["severity"] = "info" if up else "warning"
    elif which == "ntp":
        e["type"] = "NTP Sync"
        tc = msg.ntp.timeclock
        synced = log_clock(tc.date, tc.time)
        f["synced_time"] = synced.isoformat(sep=" ") if synced else None
        if tsb == 0:                      # 1.6.3: an NTP entry at 0 re-anchors the clock
            e["clock"] = synced
        e["summary"] = f"NTP sync: {f['synced_time']}"
    elif which == "trigger":
        e["type"] = "Trigger"
        src = READ_TYPES.get(msg.trigger.source, f"Type {msg.trigger.source}")
        f["source"] = src
        f.update(describe_trigger(msg.trigger.trigger))
        t = msg.trigger.trigger
        e["summary"] = f"{src}: " + commands.describe(
            {"commandtype": t.type, "zone": t.zone, "linemask": t.line_mask,
             "target": t.target_index, "value": t.value, "query": t.query_index})
    elif which == "spektra":
        e["type"] = "Spektra"
        act = SPEKTRA_ACTIONS.get(msg.spektra.action, str(msg.spektra.action))
        typ = SPEKTRA_TARGETS.get(msg.spektra.type, str(msg.spektra.type))
        f.update(action=act, target=typ, index=msg.spektra.index)
        e["summary"] = f"Spektra: {act} {typ} #{msg.spektra.index}"
    elif which == "schedule":
        e["type"] = "Schedule"
        sc = msg.schedule
        at = f"{sc.hour:02d}:{sc.minute:02d}:{sc.second:02d}"
        f.update(schedule=sc.index, start=bool(sc.isStart), at=at)
        e["summary"] = f"Schedule #{sc.index} {'started' if sc.isStart else 'ended'} at {at}"
    elif which == "userstart":
        tc = msg.userstart.timeclock
        e["clock"] = log_clock(tc.date, tc.time)
        level = msg.userstart.flags & 0x7F
        cats = ", ".join(_bits(level, LOG_CATEGORIES)) or "None"
        f["logging"] = cats
        if msg.userstart.flags & USER_SECTOR_START:
            e["type"], e["summary"], e["severity"] = "Sector Start", "Log sector start", "debug"
        else:
            e["type"], e["summary"] = "User", f"Logging set - {cats}"
    elif tsb == ERASED_TIME:
        e.update(type="Empty Slot", summary="Empty slot", severity="debug")
    else:
        e["type"] = TYPE_NAMES.get(expected_type, "Crash/Watchdog")
        e["summary"] = (f"{e['type']} record" if expected_type is not None
                        else "Crash, watchdog or boot failure record")
        f["details"] = "Recorded on the device; the details are not sent over the network"
        e["severity"] = "warning" if expected_type == _WATCHDOG else "error"
    return e


def decode_entries(messages, start_index: int = 0) -> list:
    """Decode a run of SystemLogMessages in device order and assign wall times
    (time entries anchor; others = anchor + time_since_boot seconds)."""
    out, pending, anchor = [], [], None
    for i, msg in enumerate(messages):
        has_packet = msg.WhichOneof("packet") is not None
        expected = None if has_packet else (pending.pop(0) if pending else None)
        e = decode_entry(msg, start_index + i, expected)
        pending = e.pop("_records", []) if has_packet else pending
        if e.get("clock"):
            anchor = e["clock"]
            e["time"] = e["clock"]
        elif anchor is not None and e["time_since_boot"] != ERASED_TIME:
            e["time"] = anchor + timedelta(seconds=e["time_since_boot"])
        else:
            e["time"] = None
        e.pop("clock", None)
        out.append(e)
    return out


def to_log_events(entries: list) -> list:
    """Trigger entries -> event_log.LogEvent (DALI Arc | Line | Group | Value) so
    event_log.analyze_stuck_on can run on a live log."""
    events = []
    for e in entries:
        if e["type"] != "Trigger":
            continue
        f = e["fields"]
        fields = {}
        if f.get("lines"):
            fields["line"] = f["lines"][0]
        tname = f.get("target_name", "")
        if tname.startswith("Group"):
            fields["group"] = int(tname.split()[1])
        elif tname.startswith("Address"):
            fields["address"] = int(tname.split()[1])
        fields["value"] = f.get("value")
        action = {"DALI_ARC": "DALI Arc", "DALI_ARC_OVERRIDE": "DALI Arc"}.get(f["type"], f["type"])
        events.append(LogEvent(timestamp=e["time"], event_type="Trigger",
                               source=f.get("source", "").upper(), action=action,
                               fields=fields, raw_details=e["summary"]))
    return events


def format_entries(entries: list, *, limit: int = 0) -> str:
    rows = entries[-limit:] if limit else entries
    lines = []
    for e in rows:
        t = e["time"].strftime("%Y-%m-%d %H:%M:%S") if e.get("time") else "(no clock)        "
        mark = {"error": "!!", "warning": " !", "debug": "  "}.get(e["severity"], "  ")
        lines.append(f"{mark} #{e['index']:<5} {t}  {e['summary']}")
    return "\n".join(lines)
