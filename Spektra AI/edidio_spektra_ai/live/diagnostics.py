"""Diagnostics, the functionality statement, calendar check and changed-slot detection."""

from __future__ import annotations

import ipaddress
import json
from edidio_control_py._v2 import eDS10_v2_pb2 as pb
from .. import event_log, ops
from ..server import _controller, _new_token, server
from .common import _LOGIC_SOURCES, _LOGIC_COMPARE, _LOGIC_SOURCE_NAME, _LOGIC_COMPARE_NAME, _COMPARE_SYMBOLS, _INPUT_MODES, _INPUT_MODE_NAME, _OUTPUT_MODES, _err, _connect, _json, _seconds, _save_after  # noqa: F401

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
    from ..device_log import format_entries
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
    from ..device_log import to_log_events
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
        from ..v2 import admin, frame
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
        from ..v2 import admin, frame
        msg = frame(admin(_controller._next_id(), "RESET", "SYSTEM_LOGGING"))
    except Exception as err:  # noqa: BLE001
        return _err(err)
    token = _new_token([msg], "clear device log")
    return (f"PREVIEW - would ERASE all {cur['count']} log entries (no undo). Read them "
            f"first with device_log if you need them.\nCall confirm(token=\"{token}\").")


# --- functionality statement ----------------------------------------------------------

@server.tool()
async def functionality_statement(path: str = "", out_path: str = "", title: str = "") -> str:
    """Write a functionality statement - what the lighting control does, in plain
    English: profiles and what switches them, schedules, inputs, sensors, DALI-2
    inputs, lists, logic, outputs, colour zones and Spektra content. From the
    CONNECTED controller (path empty; also uses the names stored on it - takes about
    a minute to read everything) or from a .spektra file (path). out_path saves it
    as Markdown. Read-only."""
    from .. import statement
    from ..spektra_file import load_spektra
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

    from .. import calendar_check
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
