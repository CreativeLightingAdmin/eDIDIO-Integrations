"""Write a functionality statement (what the lighting control does, in plain English)
from a ``.spektra`` project - a file, or one pulled live from a controller.

The reverse of building a project from a functionality statement: profiles and
what switches them, schedules, inputs, sensors, DALI inputs, lists, logic, outputs,
zones and the Spektra content, per controller. Only configured items are listed
(blank slots are skipped). Output is Markdown.
"""

from __future__ import annotations

from . import commands

NO_COMMAND = commands.NO_COMMAND
_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_REPEAT = {0: "once", 1: "daily", 2: "on working days", 3: "weekly", 4: "monthly"}
_ASTRO = {1: "sunrise", 2: "sunset"}
_LINE_TYPES = {0: "empty", 1: "DALI", 2: "DMX output", 3: "DMX input", 4: "auto"}
_LIST_STATES = {0: "runs when started", 1: "enabled", 2: "loops",
                3: "loops in random order", 4: "random, each step once",
                5: "random, each step once, looping"}
_LOGIC_SOURCES = {0: "the DALI level of", 1: "the state of", 2: "whether this list is running:",
                  3: "occupancy on", 4: "DMX present on", 5: "the weekday",
                  6: "the month", 7: "whether this alarm is scheduled:",
                  8: "any DALI device error", 9: "the device error flags"}
_COMPARE = {0: "<", 1: "<=", 2: "=", 3: ">", 4: ">=", 5: "!=", 6: "OR", 7: "AND", 8: "XOR"}
_MODELS = {"4P": "4-pole", "6P": "6-pole", "9P": "9-pole", "AD": "ADDICT"}


def _active(cmd) -> bool:
    return bool(cmd) and cmd.get("commandtype", NO_COMMAND) != NO_COMMAND


def _do(cmd) -> str:
    return commands.describe(cmd)


def _name(item, default):
    n = (item or {}).get("name") or ""
    return n if n and n != default else default


def _days(mask: int) -> str:
    if not mask or mask == 0x7F:
        return "every day"
    if mask == 0x1F:
        return "Monday to Friday"
    if mask == 0x60:
        return "weekends"
    return ", ".join(d for i, d in enumerate(_DAYS) if mask & (1 << i))


def _months(mask: int) -> str:
    if not mask or mask == 0xFFF:
        return ""
    return " in " + ", ".join(m for i, m in enumerate(_MONTHS) if mask & (1 << i))


def _when(ev: dict) -> str:
    astro = ev.get("type", 0)
    t = (ev.get("time") or "00:00:00")[:5]
    if astro in _ASTRO:
        if t in ("00:00", ""):
            return f"at {_ASTRO[astro]}"
        return f"{t} {'before' if ev.get('offsetBefore') else 'after'} {_ASTRO[astro]}"
    return f"at {t}"


def _profile_name(i: int, names: dict) -> str:
    n = (names.get("profiles") or [None] * (i + 1))
    label = n[i] if i < len(n) and n[i] and n[i] != f"Profile {i + 1}" else ""
    return f"Profile {i + 1}" + (f" ({label})" if label else "")


def _alias(names: dict, kind: str, i: int, default: str) -> str:
    arr = names.get(kind) or []
    n = arr[i] if i < len(arr) else ""
    return f"{default} ({n})" if n and n != default else default


def _group_by_profile(per_profile: list, key, render) -> list:
    """Items that are the same on every profile are written once ('all profiles');
    the rest are listed per profile."""
    out = []
    n = len(per_profile)
    indices = sorted({key(it) for prof in per_profile for it in prof})
    for idx in indices:
        versions = [next((it for it in prof if key(it) == idx), None) for prof in per_profile]
        texts = [render(v) if v else None for v in versions]
        if n > 1 and all(t == texts[0] for t in texts) and texts[0]:
            out.append((idx, "all profiles", texts[0]))
        else:
            for p, t in enumerate(texts):
                if t:
                    out.append((idx, f"Profile {p + 1}", t))
    return out


def _schedules(ed, names) -> list:
    rows = []
    for s in sorted(ed.get("schedules") or [], key=lambda x: x.get("index", 0)):
        if not s.get("IsEnabled"):
            continue
        st, en = s.get("startEvent") or {}, s.get("endEvent") or {}
        if not _active(st.get("command")):
            continue
        name = _alias(names, "schedules", s["index"], f"Schedule {s['index'] + 1}")
        line = (f"- **{name}**: {_when(st)}, {_REPEAT.get(s.get('repeat', 0), 'repeating')}"
                f" ({_days(s.get('weekdaysMask', 0))}{_months(s.get('monthsMask', 0))}): "
                f"{_do(st.get('command'))}")
        if s.get("endEventIsActive") and _active(en.get("command")):
            line += f"; then {_when(en)}: {_do(en.get('command'))}"
        if s.get("repeat", 0) == 0 and st.get("date") and not st["date"].startswith("2000-00"):
            line += f" (on {st['date']})"
        rows.append(line)
    return rows


def _profile_switches(ed) -> list:
    """Where profiles are changed from: schedules, lists, inputs, logic."""
    found = []
    for s in ed.get("schedules") or []:
        c = (s.get("startEvent") or {}).get("command") or {}
        if s.get("IsEnabled") and c.get("commandtype") == 30:
            found.append(f"Schedule {s['index'] + 1} {_when(s['startEvent'])} "
                         f"({_days(s.get('weekdaysMask', 0))}) -> Profile {c.get('target', 0) + 1}")
    for lst in ed.get("lists") or []:
        for st in lst.get("steps") or []:
            c = st.get("action") or {}
            if c.get("commandtype") == 30:
                found.append(f"List {lst['index'] + 1} step {st.get('index', 0) + 1} -> "
                             f"Profile {c.get('target', 0) + 1}")
    for p, prof in enumerate(ed.get("profiles") or []):
        for i in prof.get("inputs") or []:
            for k in ("shortLowAction", "longHighAction"):
                c = i.get(k) or {}
                if c.get("commandtype") == 30:
                    found.append(f"Input {i['index'] + 1} (profile {p + 1}) -> "
                                 f"Profile {c.get('target', 0) + 1}")
    return found


def _input_text(i: dict) -> str | None:
    t = i.get("type", 0)
    a, b = i.get("shortLowAction"), i.get("longHighAction")
    if not (_active(a) or _active(b)):
        return None
    disabled = " (disabled)" if t in (128, 129) else ""
    if t in (1, 129):
        parts = []
        if _active(a):
            parts.append(f"when closed: {_do(a)}")
        if _active(b):
            parts.append(f"when opened: {_do(b)}")
        return "latching contact" + disabled + " - " + "; ".join(parts)
    parts = []
    if _active(a):
        parts.append(f"short press: {_do(a)}")
    if _active(b):
        parts.append(f"long press (repeats while held): {_do(b)}")
    return "push button" + disabled + " - " + "; ".join(parts)


def _sensor_text(s: dict) -> str:
    tgt = commands._dali_tgt(s.get("controlGroup", 0))
    lines = commands._lines(s.get("controlLineMask", 0))
    mode = ("" if s.get("motionOnly") else
            f"; daylight harvesting to setpoint {s.get('setPoint')}")
    coop = ""
    if s.get("coopGroup"):
        coop = (f"; shares lights with co-op group {s['coopGroup']} as a "
                f"{'Leader' if s.get('coopLeader') else 'Follower'}")
    acts = []
    for label, k in (("on detection", "detectionTrigger"), ("at the warning", "warningTrigger"),
                     ("when idle", "idleTrigger")):
        if _active(s.get(k)):
            acts.append(f"{label}: {_do(s[k])}")
    return (f"DALI-2 sensor at line {s.get('line')} address {s.get('address')} controls "
            f"{tgt} {lines}. Held {s.get('inactivityTimer')} min after the last movement, "
            f"then a {s.get('warningTimer')} s warning, then idle (re-arms after "
            f"{s.get('disableTimer')} s){mode}{coop}. " + "; ".join(acts) + ".")


def _dali_input_text(d: dict) -> str | None:
    a, b = d.get("shortOrLowAction"), d.get("longOrHighAction")
    if not (_active(a) or _active(b)):
        return None
    kinds = {0: "momentary", 1: "latching", 4: "rotary"}
    parts = []
    if _active(a):
        parts.append(f"short/low: {_do(a)}")
    if _active(b):
        parts.append(f"long/high: {_do(b)}")
    return (f"DALI-2 {kinds.get(d.get('type', 0), 'input')} at line {d.get('line')} address "
            f"{d.get('address')} instance {d.get('instance')} - " + "; ".join(parts))


def _list_text(lst: dict, names: dict) -> list:
    steps = [s for s in lst.get("steps") or [] if _active(s.get("action"))]
    if not steps:
        return []
    name = _alias(names, "lists", lst["index"], f"List {lst['index'] + 1}")
    rows = [f"- **{name}** ({_LIST_STATES.get(lst.get('state', 0), 'state ' + str(lst.get('state')))}"
            f"{', show' if lst.get('isShow') else ''}, {len(steps)} step(s)):"]
    for s in steps:
        wait = s.get("time_until_next", 0)
        rows.append(f"  {s.get('index', 0) + 1}. {_do(s['action'])}"
                    + (f", then wait {_dur(wait)}" if wait else ""))
    return rows


def _dur(secs: int) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return " ".join(p for p in (f"{h} h" if h else "", f"{m} min" if m else "",
                                f"{s} s" if s else "") if p) or "0 s"


def _logic_text(g: dict) -> str | None:
    src = g.get("comparisonObject") or {}
    kind = src.get("commandtype", NO_COMMAND)
    if kind == NO_COMMAND or not (_active(g.get("trueAction")) or _active(g.get("falseAction"))):
        return None
    tgt = src.get("target", 0)
    what = {0: f"{commands._dali_tgt(tgt)} {commands._lines(src.get('linemask', 0))}",
            1: f"Input {tgt + 1}", 2: f"List {tgt + 1}", 3: f"Sensor {tgt + 1}",
            4: commands._lines(src.get("linemask", 0)) or "the DMX input",
            7: f"Schedule {tgt + 1}"}.get(kind, "")
    cond = (f"{_LOGIC_SOURCES.get(kind, 'source ' + str(kind))} {what} "
            f"{_COMPARE.get(g.get('comparisonType'), '?')} {g.get('comparisonValue')}").replace("  ", " ")
    out = f"Logic {g['index'] + 1}: if {cond.strip()}, {_do(g.get('trueAction'))}"
    if _active(g.get("falseAction")):
        out += f"; otherwise {_do(g['falseAction'])}"
    return out + ". (Runs when an input, list step or schedule calls it.)"


def controller_statement(mac: str, ed: dict, names: dict | None = None) -> str:
    names = names or {}
    net = ed.get("network") or {}
    hw = (ed.get("hardwareVersion") or "")
    model = _MODELS.get(hw.split("-")[0], hw.split("-")[0] or "eDIDIO")
    title = net.get("deviceName") or "Controller"
    out = [f"## {title} ({mac})", "",
           f"{model} controller, firmware {ed.get('firmwareVersion') or '?'}."]
    lines = ed.get("lineTypes") or []
    if lines:
        out.append("Lines: " + ", ".join(f"{i + 1} = {_LINE_TYPES.get(t, t)}"
                                         for i, t in enumerate(lines)) + ".")
    profiles = ed.get("profiles") or []
    out += ["", "### Operating modes (profiles)", ""]
    switches = _profile_switches(ed)
    active = ed.get("activeProfile", 0)
    out.append(f"{len(profiles)} profile(s); {_profile_name(active, names)} was active when "
               "this was read. Inputs, outputs, sensors and DALI inputs can differ per profile.")
    if switches:
        out.append("Profiles are changed by: " + "; ".join(switches) + ".")
    else:
        out.append("Nothing in the configuration changes profile automatically.")

    sch = _schedules(ed, names)
    out += ["", "### Schedules", ""] + (sch or ["No schedules are enabled."])

    per = [[i for i in (p.get("inputs") or []) if _input_text(i)] for p in profiles]
    rows = _group_by_profile(per, lambda i: i["index"], _input_text)
    out += ["", "### Inputs", ""]
    out += [f"- **{_alias(names, 'inputs', idx, f'Input {idx + 1}')}** ({where}): {text}"
            for idx, where, text in rows] or ["No inputs are configured."]

    per = [p.get("sensors") or [] for p in profiles]
    rows = _group_by_profile(per, lambda s: s["index"], _sensor_text)
    out += ["", "### Occupancy and daylight sensors", ""]
    out += [f"- **{_alias(names, 'sensors', idx, f'Sensor {idx + 1}')}** ({where}): {text}"
            for idx, where, text in rows] or ["No sensors are configured."]

    per = [[d for d in (p.get("daliInputs") or []) if _dali_input_text(d)] for p in profiles]
    rows = _group_by_profile(per, lambda d: d["index"], _dali_input_text)
    if rows:
        out += ["", "### DALI-2 push buttons and inputs", ""]
        out += [f"- **{_alias(names, 'dali_inputs', idx, f'DALI input {idx + 1}')}** "
                f"({where}): {text}" for idx, where, text in rows]

    lst_rows = []
    for lst in sorted(ed.get("lists") or [], key=lambda x: x.get("index", 0)):
        lst_rows += _list_text(lst, names)
    out += ["", "### Lists (timed sequences of commands)", ""] + (lst_rows or ["No lists are programmed."])

    logic = [t for t in (_logic_text(g) for g in ed.get("logicActions") or []) if t]
    if logic:
        out += ["", "### Logic", ""] + [f"- {t}" for t in logic]

    outs = []
    for p, prof in enumerate(profiles):
        for o in prof.get("outputs") or []:
            if o.get("type") == 3 or o.get("initiallyHigh") or o.get("triggerTime"):
                mode = "latching" if o.get("type") == 3 else f"pulse {o.get('triggerTime')}"
                outs.append((o["index"], p, f"{mode}, starts {'HIGH' if o.get('initiallyHigh') else 'LOW'}"))
    used_outputs = sorted({o for o, _p, _t in outs})
    if used_outputs:
        out += ["", "### Outputs", ""]
        for idx in used_outputs:
            descs = {t for o, _p, t in outs if o == idx}
            out.append(f"- **{_alias(names, 'outputs', idx, f'Output {idx + 1}')}**: "
                       + "; ".join(sorted(descs)))

    zones = [z for z in ed.get("zones") or [] if z.get("numLights")]
    if zones:
        out += ["", "### Colour zones (Spektra)", ""]
        for z in sorted(zones, key=lambda x: x.get("index", 0)):
            proto = "DALI" if z.get("protocol") == 0 else "DMX"
            where = commands._lines(z.get("linemask", 0))
            if not where:
                place = "no line assigned"
            elif proto == "DMX":
                place = f"DMX {where} from address {z.get('startAddress')}"
            else:
                place = f"DALI {where}"
            out.append(f"- Zone {z['index'] + 1}: {z.get('numLights')} light(s) x "
                       f"{z.get('numChannels')} channel(s), {place}")
    seqs = [s.get("name") for s in ed.get("sequences") or [] if s.get("colours")]
    themes = [t.get("name") for t in ed.get("themes") or [] if t.get("colours")]
    if seqs or themes:
        out += ["", "### Spektra content", ""]
        if seqs:
            out.append(f"- {len(seqs)} sequence(s): " + ", ".join(seqs))
        if themes:
            out.append(f"- {len(themes)} theme(s): " + ", ".join(themes))
    return "\n".join(out)


def project_statement(project: dict, names_by_mac: dict | None = None,
                      title: str = "") -> str:
    """Markdown functionality statement for every controller in a project dict."""
    names_by_mac = names_by_mac or {}
    eds = project.get("edidios") or {}
    head = [f"# Functionality statement - {title or project.get('name') or 'lighting control'}",
            "", f"{len(eds)} controller(s). Generated from the controller configuration; "
            "only configured items are listed. Numbers are as shown in SpektraPlus "
            "(List 1, Input 1, ...).", "", ""]
    body = [controller_statement(mac, ed, names_by_mac.get(mac)) for mac, ed in eds.items()]
    return "\n".join(head) + "\n\n".join(body) + "\n"
