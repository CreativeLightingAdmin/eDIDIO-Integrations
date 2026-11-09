"""Compare the controller's Spektra calendar with what it should hold.

The calendar has 366 day slots and no year: on a Start Calendar Event the controller
plays the slot for today's day of the year (so from 1 March a slot is one day later
in a leap year). Expectations are therefore given as real dates in a year, turned
into slots for that year, and compared with what the controller holds.

Expected entries: {"dates": "12-01..12-26" | "2026-12-25" | ["12-24", "12-25"],
"sequence": 3 | "Christmas", "theme": ..., or "nothing": true}.
"""

from __future__ import annotations

from datetime import date, timedelta


def _parse_day(text: str, year: int) -> date:
    parts = [int(p) for p in str(text).strip().split("-")]
    if len(parts) == 3:
        return date(year, parts[1], parts[2])   # the check is for `year`
    if len(parts) == 2:
        return date(year, parts[0], parts[1])
    raise ValueError(f"date '{text}' must be MM-DD or YYYY-MM-DD")


def expand_dates(spec, year: int) -> list:
    """'12-01..12-26', '2026-12-25', or a list of those -> sorted dates in `year`.
    A range that wraps the new year ('12-26..01-02') runs to 31 Dec and from 1 Jan."""
    items = spec if isinstance(spec, list) else [spec]
    out = set()
    for item in items:
        s = str(item).strip()
        if ".." in s:
            a, b = (_parse_day(x, year) for x in s.split("..", 1))
            if b < a:      # wraps: both ends of the same calendar year
                out.update(a + timedelta(days=i) for i in range((date(year, 12, 31) - a).days + 1))
                out.update(date(year, 1, 1) + timedelta(days=i)
                           for i in range((b - date(year, 1, 1)).days + 1))
            else:
                out.update(a + timedelta(days=i) for i in range((b - a).days + 1))
        else:
            out.add(_parse_day(s, year))
    return sorted(out)


def slot(d: date) -> int:
    return d.timetuple().tm_yday - 1


def _resolve(kind: str, ref, names: dict):
    """Index from an index or a (case-insensitive, unique-prefix) name."""
    if isinstance(ref, int) or str(ref).isdigit():
        return int(ref)
    want = str(ref).strip().lower()
    table = names.get(kind) or {}
    exact = [i for i, n in table.items() if (n or "").lower() == want]
    if exact:
        return exact[0]
    loose = [i for i, n in table.items() if want in (n or "").lower()]
    if len(loose) == 1:
        return loose[0]
    raise ValueError(f"{kind} '{ref}' " + ("matches several: " + ", ".join(
        table[i] for i in loose) if loose else "not found on the controller"))


def compare(actual_days: list, expected: list, names: dict, year: int,
            *, strict: bool = False) -> dict:
    """actual_days: read_calendar() rows {day_index, kind, target_index}.
    names: {"sequence": {index: name}, "theme": {index: name}}.
    Returns {"checks": [...], "unexpected": [...]} with per-entry OK/mismatch days."""
    by_slot = {d["day_index"]: (d["kind"], d["target_index"]) for d in actual_days}

    def label(entry):
        if entry is None:
            return "nothing"
        kind, idx = entry
        n = (names.get(kind) or {}).get(idx)
        return f"{kind} {idx + 1}" + (f" '{n}'" if n else "")

    checks, covered = [], set()
    for exp in expected:
        days = expand_dates(exp.get("dates"), year)
        if exp.get("nothing"):
            want = None
        else:
            kind = "sequence" if "sequence" in exp else "theme" if "theme" in exp else None
            if kind is None:
                raise ValueError("each entry needs 'sequence', 'theme' or 'nothing': true")
            want = (kind, _resolve(kind, exp[kind], names))
        wrong = []
        for d in days:
            s = slot(d)
            covered.add(s)
            got = by_slot.get(s)
            if got != want:
                wrong.append((d, label(got)))
        checks.append({"dates": exp.get("dates"), "want": label(want), "days": len(days),
                       "wrong": wrong})
    unexpected = []
    if strict:
        start = date(year, 1, 1)
        for s, entry in sorted(by_slot.items()):
            if s not in covered and s < (366 if year % 4 == 0 else 365):
                unexpected.append((start + timedelta(days=s), label(entry)))
    return {"checks": checks, "unexpected": unexpected}


def _ranges(days: list) -> list:
    """Collapse consecutive dates with the same value into 'a..b: value' strings."""
    out, run = [], None
    for d, val in days:
        if run and val == run[2] and (d - run[1]).days == 1:
            run[1] = d
        else:
            if run:
                out.append(run)
            run = [d, d, val]
    if run:
        out.append(run)
    return [f"{a:%d %b}" + (f"-{b:%d %b}" if b != a else "") + f": {v}" for a, b, v in out]


def format_report(res: dict, year: int) -> str:
    rows = [f"Calendar check for {year}:"]
    bad = 0
    for c in res["checks"]:
        if c["wrong"]:
            bad += 1
            rows.append(f"  MISMATCH {c['dates']} should be {c['want']}: "
                        f"{len(c['wrong'])} of {c['days']} day(s) differ")
            rows += [f"      {r}" for r in _ranges(c["wrong"])]
        else:
            rows.append(f"  OK       {c['dates']}: {c['want']} on all {c['days']} day(s)")
    if res["unexpected"]:
        rows.append(f"  Also on the calendar (not in your list), {len(res['unexpected'])} day(s):")
        rows += [f"      {r}" for r in _ranges(res["unexpected"])]
    rows.append("All as expected." if not bad and not res["unexpected"]
                else f"{bad} entr{'y' if bad == 1 else 'ies'} differ.")
    return "\n".join(rows)
