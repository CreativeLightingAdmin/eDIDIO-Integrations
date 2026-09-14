"""Parse eDIDIO event-log exports and run first-pass diagnostics.

The device/app exports a human-readable event log (``.txt`` and the log ``.spektra``
variants share the same body). Each record is three lines::

    HH:MM:SS YYYY-MM-DD:
              [EventType]
              { 'Source': 'INPUTS', 'Details': 'DALI Arc | Line 1 | Group 0 | Value: 254' }

``Details`` is a pipe-delimited string: an action name followed by ``Key value`` /
``Key: value`` fields. This system drives lighting via **Lists**, so a light going
ON is a ``DALI Arc ... Value: 254`` and OFF is ``Value: 0``. :func:`analyze_stuck_on`
reconstructs on/off per (line, target) and flags anything left on — a first pass at
diagnosing "the lights won't turn off".
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import datetime

# A record starts with e.g. "13:03:52 2026-08-31:"
_TS_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})\s+(\d{4}-\d{2}-\d{2}):")
_TYPE_RE = re.compile(r"^\[(.+?)\]")

# "DALI Arc" values: full-on vs off (arc level 0-254; 254 = max on this firmware).
ON_VALUE = 254


@dataclass
class LogEvent:
    timestamp: datetime | None
    event_type: str                 # e.g. "Trigger", "UserStart"
    source: str = ""                # e.g. "INPUTS", "LIST"
    action: str = ""                # e.g. "DALI Arc", "Start List"
    fields: dict = field(default_factory=dict)   # parsed Details: line/group/value/...
    raw_details: str = ""


def _parse_details(details: str) -> tuple[str, dict]:
    """Split a Details string into (action, {key: value})."""
    parts = [p.strip() for p in details.split("|") if p.strip()]
    if not parts:
        return ("", {})
    action, fields = parts[0], {}
    for part in parts[1:]:
        if ":" in part:
            key, _, val = part.partition(":")
        else:
            key, _, val = part.partition(" ")
        key, val = key.strip().lower(), val.strip()
        if not key:
            continue
        if val.lower() in ("none", ""):
            fields[key] = None
        elif val.lstrip("-").isdigit():
            fields[key] = int(val)
        else:
            fields[key] = val
    return (action, fields)


def parse_log(text: str) -> list[LogEvent]:
    """Parse an exported event log into a list of :class:`LogEvent`."""
    events: list[LogEvent] = []
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n:
        m = _TS_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        time_s, date_s = m.group(1), m.group(2)
        try:
            ts = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            ts = None

        # Following non-empty lines: [EventType] then { ... }.
        etype, payload = "", {}
        j = i + 1
        while j < n and j <= i + 4:
            s = lines[j].strip()
            if not s:
                j += 1
                continue
            tm = _TYPE_RE.match(s)
            if tm and not etype:
                etype = tm.group(1).strip()
            elif s.startswith("{"):
                try:
                    payload = ast.literal_eval(s)
                except (ValueError, SyntaxError):
                    payload = {}
                break
            j += 1

        source = str(payload.get("Source", "")) if isinstance(payload, dict) else ""
        details = str(payload.get("Details", "")) if isinstance(payload, dict) else ""
        action, fields = _parse_details(details) if details else ("", {})
        events.append(LogEvent(timestamp=ts, event_type=etype, source=source,
                               action=action, fields=fields, raw_details=details))
        i = j + 1
    return events


def summarize_log(events: list[LogEvent]) -> str:
    """Counts by event type and source, plus the time span covered."""
    if not events:
        return "No events parsed."
    by_type: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for e in events:
        by_type[e.event_type] = by_type.get(e.event_type, 0) + 1
        if e.source:
            by_source[e.source] = by_source.get(e.source, 0) + 1
    times = [e.timestamp for e in events if e.timestamp]
    span = f"{min(times)} .. {max(times)}" if times else "unknown"
    lines = [f"{len(events)} events, span {span}.",
             "By type: " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())),
             "By source: " + ", ".join(f"{k}={v}" for k, v in sorted(by_source.items()))]
    return "\n".join(lines)


def _target_key(fields: dict) -> tuple:
    """Identify the addressed target of a DALI Arc: (line, kind, id)."""
    line = fields.get("line")
    for kind in ("group", "address"):
        if kind in fields:
            return (line, kind, fields[kind])
    return (line, "?", None)


def analyze_stuck_on(events: list[LogEvent]) -> str:
    """Reconstruct DALI Arc on/off per target; report any left on.

    First-pass "lights won't turn off": for each (line, group/address) we track the
    last arc level seen. Targets whose final level is > 0 never received an off and
    are reported with the time they were last turned on.
    """
    # target -> (last_value, last_on_time)
    last: dict[tuple, tuple[int, datetime | None]] = {}
    for e in events:
        if e.action != "DALI Arc" or "value" not in e.fields:
            continue
        val = e.fields.get("value")
        if not isinstance(val, int):
            continue
        key = _target_key(e.fields)
        prev_on = last.get(key, (0, None))[1]
        on_time = e.timestamp if val > 0 else None
        # Preserve the earliest on-time in the current on-streak.
        if val > 0 and prev_on is not None:
            on_time = prev_on
        last[key] = (val, on_time)

    stuck = [(k, val, on) for k, (val, on) in last.items() if val > 0]
    if not last:
        return "No 'DALI Arc' output events found in the log (nothing to analyse)."
    if not stuck:
        return (f"Checked {len(last)} target(s): all ended OFF "
                "(every ON had a matching OFF). No stuck-on lights detected.")

    lines = [f"Potential stuck-on: {len(stuck)} of {len(last)} target(s) ended ON "
             "(no OFF seen after the last ON):"]
    for (line, kind, tid), val, on_time in sorted(stuck, key=lambda x: str(x[0])):
        when = f", on since {on_time}" if on_time else ""
        lines.append(f"  - Line {line} {kind} {tid}: last arc level {val}{when}")
    lines.append("\nNext checks: is a sensor re-triggering occupancy, is a Logic "
                 "action holding it on, a latched input, the profile stuck, or the "
                 "ballast not responding to OFF?")
    return "\n".join(lines)
