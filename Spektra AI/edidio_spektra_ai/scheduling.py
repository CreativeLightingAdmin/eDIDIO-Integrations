"""Scheduling logic: unpack the device's packed time, and compute *what's
scheduled next* from a list of alarms.

Pure (no protobuf/network), heavily unit tested. The controller passes plain alarm
dicts (as read from the device) in; this returns human-friendly "next fire" info.

Alarm dict shape (from controller._alarm_summary / read_alarms):
  {"index", "enabled", "start_time" (packed uint), "repeat" (enum int),
   "repeat_day_bitmask", "trigger_type", "target_index", "zone"}

Packed time layout (firmware): time = (hour << 16) | (minute << 8) | second.
Repeat enums: 0 NO_REPEAT, 1 DAILY, 2 WORK_DAY (Mon-Fri), 3 WEEKLY, 4 MONTHLY.
Weekday bitmask: bit0=Mon .. bit6=Sun.
"""

from __future__ import annotations

from datetime import datetime, timedelta

REPEAT_NAMES = {0: "once", 1: "daily", 2: "weekdays", 3: "weekly", 4: "monthly"}
_WORKDAYS = {0, 1, 2, 3, 4}  # Mon-Fri (Python weekday(): Mon=0)


def unpack_time(packed: int):
    """(hour, minute, second) from a packed TimeClock time field."""
    return ((packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF)


def _fires_on(alarm: dict, day: datetime) -> bool:
    """Does this alarm fire on the given calendar day (ignoring time-of-day)?"""
    repeat = alarm.get("repeat", 0)
    wd = day.weekday()  # Mon=0..Sun=6
    if repeat == 1:  # daily
        return True
    if repeat == 2:  # weekdays
        return wd in _WORKDAYS
    if repeat == 3:  # weekly — use the day bitmask if present, else every day
        mask = alarm.get("repeat_day_bitmask", 0)
        return bool(mask & (1 << wd)) if mask else True
    if repeat == 4:  # monthly — approximate: same behaviour daily-check handled by caller
        return True
    # NO_REPEAT (0): the caller handles one-shot via the absolute date; treat as
    # "eligible today and later" so a time later today still counts.
    return True


def next_fire(alarm: dict, now: datetime):
    """Return the next datetime this alarm fires at/after `now`, or None.

    Only time-of-day + repeat pattern are considered (astro alarms return None —
    their fire time depends on the device's location/sun calc)."""
    if not alarm.get("enabled", True):
        return None
    if alarm.get("astro_start"):  # astro (sunrise/sunset) — device computes it
        return None
    hh, mm, ss = unpack_time(int(alarm.get("start_time", 0)))
    repeat = alarm.get("repeat", 0)

    # Search up to ~40 days ahead for the next matching day+time.
    for delta in range(0, 40):
        day = (now + timedelta(days=delta)).replace(hour=hh, minute=mm, second=ss, microsecond=0)
        if day < now:
            continue
        if repeat == 0:  # once: only if it's still today/future (first eligible day)
            if delta == 0:
                return day
            return None
        if _fires_on(alarm, day):
            return day
    return None


def next_scheduled(alarms: list, now: datetime | None = None) -> dict | None:
    """Return the soonest-firing alarm + its next datetime, or None.

    Result: {"alarm": <alarm>, "when": datetime, "in": "2h 15m",
             "description": "..."} or None if nothing is (time-) schedulable."""
    now = now or datetime.now()
    best = None
    for alarm in alarms or []:
        nf = next_fire(alarm, now)
        if nf is None:
            continue
        if best is None or nf < best[1]:
            best = (alarm, nf)
    if best is None:
        return None
    alarm, when = best
    return {
        "alarm": alarm,
        "when": when,
        "in": _humanize(when - now),
        "description": describe_alarm(alarm),
    }


def describe_alarm(alarm: dict) -> str:
    hh, mm, _ = unpack_time(int(alarm.get("start_time", 0)))
    repeat = REPEAT_NAMES.get(alarm.get("repeat", 0), "once")
    target = alarm.get("target_index", 0)
    zone = alarm.get("zone", 0)
    tt = alarm.get("trigger_type")
    what = f"sequence {target}" if tt == 12 else (f"theme {target}" if tt == 14 else f"action {tt} (target {target})")
    return f"alarm {alarm.get('index', '?')}: {hh:02d}:{mm:02d} {repeat} -> {what} on zone {zone}"


def _humanize(td: timedelta) -> str:
    secs = int(td.total_seconds())
    if secs < 0:
        return "now"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m or not parts:
        parts.append(f"{m}m")
    return " ".join(parts)


# --- calendar overview parsing ---

def parse_calendar_overview(overview: dict) -> list:
    """Turn a SpektraCalendarOverview reply (day_offset + days[]) into a list of
    {day_index, kind ('sequence'|'theme'), target_index} entries."""
    out = []
    for d in overview.get("days", []):
        kind = "sequence" if d.get("type") == 1 else ("theme" if d.get("type") == 2 else str(d.get("type")))
        out.append({"day_index": d.get("day_index"), "kind": kind, "target_index": d.get("target_index")})
    return out
