"""Live authoring: lists, inputs/outputs, logic, DMX-to-DALI translations, burn-ins and the zone editor."""

from __future__ import annotations

from .. import commands, spektra_map
from ..server import _controller, _new_token, server
from .common import _LOGIC_SOURCES, _LOGIC_COMPARE, _LOGIC_SOURCE_NAME, _LOGIC_COMPARE_NAME, _COMPARE_SYMBOLS, _INPUT_MODES, _INPUT_MODE_NAME, _OUTPUT_MODES, _err, _connect, _json, _seconds, _save_after  # noqa: F401

# --- live authoring: lists ------------------------------------------------------------

def _describe_list(lst: dict) -> str:
    state = spektra_map.LIST_STATES.get(lst.get("state", 0), lst.get("state"))
    head = (f"List {lst['index'] + 1} (index {lst['index']}): {len(lst['steps'])} step(s), "
            f"{state}{', show' if lst.get('isShow') else ''}")
    rows = [f"    {s['index'] + 1:>3}. {commands.describe(s['action'])}; then wait "
            f"{s['time_until_next']} s" for s in lst["steps"]]
    return "\n".join([head] + rows)


@server.tool()
async def list_lists(include_empty: bool = False) -> str:
    """Every list on the controller with its steps described in English (all steps,
    including those past 32). Read-only."""
    try:
        counts = await _controller.read_system_counts()
        lists = await _controller.pull_lists(counts["lists"])
    except Exception as err:  # noqa: BLE001
        return _err(err)
    shown = [x for x in lists if include_empty or x["steps"]]
    if not shown:
        return f"All {len(lists)} lists are empty."
    return "\n".join(_describe_list(x) for x in shown) + (
        f"\n({len(lists) - len(shown)} empty list(s) not shown.)" if not include_empty else "")


_LIST_STATE_IDS = {v.replace(" ", "_"): k for k, v in spektra_map.LIST_STATES.items()}


@server.tool()
async def preview_list(index: int, steps: str, state: str = "disabled",
                       show: bool = False) -> str:
    """Write a list (a timed sequence of commands) to the controller. index is
    0-based (List 1 = 0). steps: JSON array of {"command": {...}, "wait": "5s"} -
    the wait is the time AFTER this step before the next (seconds, or "30s", "5m",
    "1h"; max 65535 s). Up to 255 steps. state: disabled (runs only when started -
    the usual), enabled, looping, random_loop, random_withdrawn, random_withdrawn_loop.
    Writing List 1 (index 0) erases every list on the controller, so the others are
    rewritten with it automatically. Returns a token; confirm(token) writes + saves.
    Example step: {"command": {"do": "dali_arc", "line": 1, "group": 0, "level": 254},
    "wait": "30m"}"""
    try:
        counts = await _controller.read_system_counts()
        if not 0 <= index < counts["lists"]:
            return f"index {index} is outside 0-{counts['lists'] - 1}."
        if state not in _LIST_STATE_IDS:
            return f"state: one of {', '.join(_LIST_STATE_IDS)}."
        raw = _json(steps, "steps")
        new_steps = []
        for n, st in enumerate(raw):
            cmd = commands.build(st.get("command", st.get("do") and st))
            secs = _seconds(st.get("wait", 0))
            dur, unit = spektra_map.duration_and_unit(secs)
            new_steps.append({"index": n, "action": cmd, "duration": dur, "timeUnit": unit,
                              "time_until_next": secs})
        new = {"index": index, "name": f"List {index + 1}", "state": _LIST_STATE_IDS[state],
               "isShow": show, "steps": new_steps, "loop_on_startup": False}
        live = await _controller.pull_lists(counts["lists"])
        order = spektra_map.lists_write_order([new], live)
        msgs = []
        for item in order:
            msgs.extend(spektra_map.list_to_messages(item, _controller._next_id))
        msgs = await _save_after(msgs)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    old = next((x for x in live if x["index"] == index), None)
    extra = [x["index"] for x in order if x["index"] != index]
    body = _describe_list(new)
    note = (f"\nAlso rewrites lists {', '.join(str(i + 1) for i in extra)} unchanged "
            "(writing List 1 erases every list)." if extra else "")
    was = f"was: {len(old['steps'])} step(s)" if old else "was: empty"
    token = _new_token(msgs, body)
    return (f"PREVIEW ({was}):\n{body}{note}\nNothing written yet. "
            f"Call confirm(token=\"{token}\") to write and save.")


# --- live authoring: inputs / outputs ---------------------------------------------------

def _describe_input(i: dict) -> str:
    mode = _INPUT_MODE_NAME.get(i.get("type", 0), f"type {i.get('type')}")
    a, b = ("short press", "long press") if "momentary" in mode else ("closed (LOW)", "opened (HIGH)")
    return (f"  Input {i['index'] + 1} (index {i['index']}) [{mode}]: {a} -> "
            f"{commands.describe(i.get('shortLowAction'))}; {b} -> "
            f"{commands.describe(i.get('longHighAction'))}")


def _describe_output(o: dict) -> str:
    mode = "latching" if o.get("type") == 3 else "momentary"
    return (f"  Output {o['index'] + 1} (index {o['index']}) [{mode}], starts "
            f"{'HIGH' if o.get('initiallyHigh') else 'LOW'}"
            + (f", pulse {o.get('triggerTime')}" if mode == "momentary" else ""))


@server.tool()
async def list_io(profile: int = -1) -> str:
    """Physical inputs and outputs per profile with what each does (0-based profile;
    -1 = the active profile). Read-only."""
    try:
        counts = await _controller.read_system_counts()
        p = counts["active"] if profile < 0 else profile
        ins = await _controller.pull_inputs(p)
        outs = await _controller.pull_outputs(p)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return "\n".join([f"Profile {p + 1} (index {p}) - inputs:"] + [_describe_input(i) for i in ins]
                     + ["Outputs:"] + [_describe_output(o) for o in outs])


def _profiles(spec: str, count: int, active: int) -> list:
    if spec in ("all", "*"):
        return list(range(count))
    if spec in ("", "active"):
        return [active]
    out = [int(x) for x in spec.split(",") if x.strip()]
    for p in out:
        if not 0 <= p < count:
            raise ValueError(f"profile {p} is outside 0-{count - 1}")
    return out


@server.tool()
async def preview_input(index: int, mode: str, on_low: str = "", on_high: str = "",
                        profiles: str = "all") -> str:
    """Configure a physical input. index 0-based (Input 1 = 0). mode: momentary
    (on_low = SHORT press action, on_high = LONG press, repeating while held) or
    latching (on_low = when the contact CLOSES to ground, on_high = when it OPENS) -
    e.g. a PE cell, a key switch, a fire relay. Add '_disabled' to keep it configured
    but ignored. on_low / on_high: command JSON (see command_reference), empty =
    no command. profiles: 'all', 'active' or '0,2'. Returns a token."""
    try:
        if mode not in _INPUT_MODES:
            return f"mode: one of {', '.join(_INPUT_MODES)}."
        low = commands.build(_json(on_low, "on_low") if on_low.strip() else None)
        high = commands.build(_json(on_high, "on_high") if on_high.strip() else None)
        counts = await _controller.read_system_counts()
        targets = _profiles(profiles, counts["profiles"], counts["active"])
        msgs, lines = [], []
        for p in targets:
            ins = await _controller.pull_inputs(p)
            if not 0 <= index < len(ins):
                return f"index {index} is outside 0-{len(ins) - 1}."
            new = dict(ins[index], type=_INPUT_MODES[mode], shortLowAction=low,
                       longHighAction=high)
            if new == ins[index]:
                continue
            old = ins[index]
            ins = [new if i["index"] == index else i for i in ins]
            msgs.append(spektra_map.inputs_to_message(p, ins, _controller._next_id()))
            lines.append(f"Profile {p + 1}:\n  was:{_describe_input(old)[1:]}\n"
                         f"  now:{_describe_input(new)[1:]}")
        if not msgs:
            return "No change: the input already does that on those profiles."
        msgs = await _save_after(msgs)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    token = _new_token(msgs, "\n".join(lines))
    return ("PREVIEW:\n" + "\n".join(lines)
            + f"\nCall confirm(token=\"{token}\") to write and save.")


@server.tool()
async def preview_output(index: int, mode: str = "latching", initially_high: bool = False,
                         pulse: int = 0, profiles: str = "all") -> str:
    """Configure a physical output (relay / open collector). index 0-based. mode:
    latching (stays HIGH/LOW until told: output_high/output_low/output_toggle) or
    momentary (output_trigger pulses it for `pulse` - the controller's
    time_trigger_is_active units). initially_high: level at start-up. Returns a token."""
    try:
        if mode not in _OUTPUT_MODES:
            return "mode: latching or momentary."
        counts = await _controller.read_system_counts()
        targets = _profiles(profiles, counts["profiles"], counts["active"])
        msgs, lines = [], []
        for p in targets:
            outs = await _controller.pull_outputs(p)
            if not 0 <= index < len(outs):
                return f"index {index} is outside 0-{len(outs) - 1}."
            new = dict(outs[index], type=_OUTPUT_MODES[mode], initiallyHigh=initially_high,
                       triggerTime=pulse)
            new["triggerTime"] = spektra_map._canon_output_time(new["type"], pulse)
            if new == outs[index]:
                continue
            outs = [new if o["index"] == index else o for o in outs]
            msgs.append(spektra_map.outputs_to_message(p, outs, _controller._next_id()))
            lines.append(f"Profile {p + 1}:{_describe_output(new)[1:]}")
        if not msgs:
            return "No change."
        msgs = await _save_after(msgs)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    token = _new_token(msgs, "\n".join(lines))
    return "PREVIEW:\n" + "\n".join(lines) + f"\nCall confirm(token=\"{token}\")."


# --- live authoring: logic -----------------------------------------------------------

def _describe_logic(g: dict) -> str:
    src = g.get("comparisonObject") or {}
    kind = _LOGIC_SOURCE_NAME.get(src.get("commandtype"), f"source {src.get('commandtype')}")
    cmp_ = _LOGIC_COMPARE_NAME.get(g.get("comparisonType"), g.get("comparisonType"))
    tgt = src.get("target", 0)
    where = {"dali_level": f"DALI {commands._dali_tgt(tgt)} {commands._lines(src.get('linemask', 0))}",
             "input_state": f"Input {tgt + 1}", "list_running": f"List {tgt + 1}",
             "occupancy_detected": f"Sensor {tgt + 1}",
             "alarm_scheduled": f"Schedule {tgt}"}.get(kind, f"target {tgt}")
    return (f"  Logic {g['index'] + 1} (index {g['index']}): if {kind} [{where}] {cmp_} "
            f"{g.get('comparisonValue')} -> {commands.describe(g.get('trueAction'))}; "
            f"else -> {commands.describe(g.get('falseAction'))}")


@server.tool()
async def list_logic() -> str:
    """Every logic rule (if <source> <compare> <value> then A else B). Read-only."""
    try:
        rules = await _controller.pull_logic()
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return "\n".join(_describe_logic(g) for g in rules) or "No logic rules."


@server.tool()
async def preview_logic(index: int, source: str, compare: str, value: int,
                        if_true: str = "", if_false: str = "") -> str:
    """Write logic rule `index` (0-based). A rule is evaluated when something runs it
    ({"do":"logic","logic":N} from an input, list step or schedule).
    source JSON: {"type": "dali_level", "line": 1, "address"|"group": n} |
    {"type": "input_state", "input": 0} | {"type": "list_running", "list": 0} |
    {"type": "occupancy_detected", "sensor": 0} | {"type": "dmx_present", "line": n} |
    {"type": "cal_weekday"} (1=Mon..7=Sun) | {"type": "cal_month"} (1-12) |
    {"type": "alarm_scheduled", "schedule": n} | {"type": "dali_cache_status"} |
    {"type": "has_error", "mask": bits}. All indices 0-based.
    compare: < <= == > >= != or bit_or / bit_and / bit_xor.
    if_true / if_false: command JSON (empty = none). Returns a token."""
    try:
        src = _json(source, "source")
        kind = str(src.get("type", "")).lower()
        if kind not in _LOGIC_SOURCES:
            return f"source type: one of {', '.join(_LOGIC_SOURCES)}."
        cmp_key = _COMPARE_SYMBOLS.get(compare.strip(), compare.strip().lower())
        if cmp_key not in _LOGIC_COMPARE:
            return f"compare: one of {', '.join(_COMPARE_SYMBOLS)} or {', '.join(_LOGIC_COMPARE)}."
        obj = commands.empty()
        obj["commandtype"] = _LOGIC_SOURCES[kind]
        if kind == "dali_level":
            obj["linemask"] = commands.linemask(src)
            obj["target"] = commands.dali_target({**src, "do": "logic source"})
        elif kind in ("dmx_present",):
            obj["linemask"] = commands.linemask(src)
        else:
            for key in ("input", "list", "sensor", "schedule", "mask"):
                if key in src:
                    obj["target"] = int(src[key])
        rules = await _controller.pull_logic()
        if not 0 <= index < len(rules):
            return f"index {index} is outside 0-{len(rules) - 1}."
        new = dict(rules[index], comparisonObject=obj, comparisonType=_LOGIC_COMPARE[cmp_key],
                   comparisonValue=int(value), isEnabled=True,
                   trueAction=commands.build(_json(if_true, "if_true") if if_true.strip() else None),
                   falseAction=commands.build(_json(if_false, "if_false") if if_false.strip() else None))
        rules = [new if g["index"] == index else g for g in rules]
        msgs = await _save_after([spektra_map.logic_to_message(rules, _controller._next_id())])
    except Exception as err:  # noqa: BLE001
        return _err(err)
    body = _describe_logic(new)
    token = _new_token(msgs, body)
    return f"PREVIEW:\n{body}\nCall confirm(token=\"{token}\") to write and save."


# --- DMX-to-DALI translations ---------------------------------------------------------

def _dali_targets(spec: str) -> list:
    """'0-3' (short addresses), 'g2' / 'group 2', 'all' / 'broadcast', or a mix:
    '0,1,g2' -> DALI targets (address, 64+group, 80)."""
    out = []
    for part in str(spec).replace(";", ",").split(","):
        p = part.strip().lower()
        if not p:
            continue
        if p in ("all", "broadcast"):
            out.append(80)
        elif p.startswith("g"):
            g = int(p.lstrip("group ").lstrip("g"))
            if not 0 <= g <= 15:
                raise ValueError(f"group {g} is outside 0-15")
            out.append(64 + g)
        elif "-" in p:
            a, b = (int(x) for x in p.split("-"))
            out.extend(range(a, b + 1))
        else:
            out.append(int(p))
    if any(not 0 <= t <= 80 for t in out):
        raise ValueError("DALI addresses are 0-63, groups g0-g15, or 'all'")
    return out


def _describe_translation(t: dict) -> str:
    if not t.get("isEnabled"):
        return f"  Translation {t['index'] + 1}: off"
    n = t["DMXEndAddress"] - t["DMXStartAddress"] + 1
    targets = [commands._dali_tgt(a) for a in (t.get("DALIAddresses") or [])[:n]]
    pairs = ", ".join(f"ch{t['DMXStartAddress'] + i}->{x}" for i, x in enumerate(targets))
    block = (f"; blocks inputs {[i + 1 for i in range(32) if t.get('inputMask', 0) & (1 << i)]}"
             f" while DMX is present" if t.get("blockInputs") and t.get("inputMask") else "")
    return (f"  Translation {t['index'] + 1}: DMX in on {commands._lines(t.get('lineIn', 0))} -> "
            f"DALI {commands._lines(t.get('lineOut', 0))}: {pairs}{block}")


@server.tool()
async def list_translations() -> str:
    """DMX-to-DALI translations: which DMX input channels drive which DALI addresses
    or groups (as arc levels, sampled every 0.7 s). Read-only."""
    try:
        items = await _controller.pull_translations()
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if not items:
        return "This controller has no DMX-to-DALI translation slots."
    return "\n".join(_describe_translation(t) for t in items)


@server.tool()
async def preview_translation(index: int, dmx_in_line: int = 0, dali_line: int = 0,
                              dmx_start: int = 1, dali_targets: str = "",
                              enabled: bool = True, block_inputs: str = "") -> str:
    """Set up a DMX-to-DALI translation: DMX channels from dmx_start on the DMX INPUT
    line dmx_in_line drive the DALI targets in order on dali_line (channel dmx_start ->
    first target, +1 -> second, ...). dali_targets: '0-3', 'g2', 'all' or a mix
    ('0,1,g2'); up to 64. block_inputs: input numbers ('1,2', 1-based) ignored while
    DMX is present. enabled=False switches the slot off. index 0-based. The DMX line
    must be a DMX input (preview_line_types). Returns a token."""
    try:
        items = await _controller.pull_translations()
        if not 0 <= index < len(items):
            return f"index is 0-{len(items) - 1} on this controller."
        new = dict(items[index])
        if enabled:
            targets = _dali_targets(dali_targets)
            if not targets or len(targets) > 64:
                return "Give 1-64 DALI targets."
            if not (1 <= dmx_start and dmx_start + len(targets) - 1 <= 512):
                return "The DMX channels must sit within 1-512."
            lines = await _controller.read_line_types()
            if lines and (len(lines) < dmx_in_line or lines[dmx_in_line - 1] != 3):
                return (f"Line {dmx_in_line} is not a DMX input on this controller "
                        "(set it with preview_line_types).")
            if lines and (len(lines) < dali_line or lines[dali_line - 1] != 1):
                return f"Line {dali_line} is not a DALI line on this controller."
            mask = 0
            for i in (int(x) for x in block_inputs.split(",") if x.strip()):
                mask |= 1 << (i - 1)
            new.update(isEnabled=True, lineIn=1 << (dmx_in_line - 1),
                       lineOut=1 << (dali_line - 1), DMXStartAddress=dmx_start,
                       DMXEndAddress=dmx_start + len(targets) - 1,
                       DALIAddresses=targets + [0] * (64 - len(targets)),
                       blockInputs=bool(mask), inputMask=mask)
        else:
            new["isEnabled"] = False
        table = [new if t["index"] == index else t for t in items]
        msgs = await _save_after([spektra_map.translations_to_message(table, _controller._next_id())])
    except Exception as err:  # noqa: BLE001
        return _err(err)
    body = "was:\n" + _describe_translation(items[index]) + "\nnow:\n" + _describe_translation(new)
    token = _new_token(msgs, body)
    return f"PREVIEW:\n{body}\nCall confirm(token=\"{token}\") to write and save."


# --- burn-ins ---------------------------------------------------------------------

def _describe_burnin(b: dict) -> str:
    if not b.get("duration"):
        return f"  Burn-in {b['index'] + 1}: not set up"
    st = b.get("states") or {}
    running = "counting down" if st.get("running_flag") else "paused (lights off)"
    if not b.get("remaining"):
        running = "finished"
    return (f"  Burn-in {b['index'] + 1}: holds {commands._dali_tgt(b.get('address', 0))} "
            f"{commands._lines(b.get('line_mask', 0))} at full for {b['duration'] / 60:g} h "
            f"(counts only while address {b.get('query_address')} is on); "
            f"{b.get('remaining', 0) / 60:g} h left, {running}")


@server.tool()
async def list_burnins() -> str:
    """Burn-ins (new-lamp seasoning: lights held at full for N hours) with time left
    and whether they are counting. Read-only."""
    try:
        items = await _controller.pull_burnins()
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return "\n".join(_describe_burnin(b) for b in items) or "No burn-in slots."


@server.tool()
async def preview_burnin(index: int, line: int, target: str, query_address: int,
                         hours: float) -> str:
    """Set up a burn-in: hold `target` ('5', 'g2' or 'all') on DALI `line` at full for
    `hours`; the countdown only runs while `query_address` (one fitting in it) is on.
    Start/stop it with run_command {"do":"burnin_start","burnin":N}. Writing burn-ins
    RESTARTS their countdowns. hours=0 clears the slot. index 0-based. Returns a token."""
    try:
        items = await _controller.pull_burnins()
        if not 0 <= index < len(items):
            return f"index is 0-{len(items) - 1} on this controller."
        tgt = _dali_targets(target)
        if len(tgt) != 1:
            return "Give one target: an address, a group (g2) or all."
        minutes = int(round(hours * 60))
        if not 0 <= minutes <= 65535:
            return "hours is 0-1092."
        if not 0 <= query_address <= 63:
            return "query_address is one fitting, 0-63."
        new = dict(items[index], line_mask=1 << (line - 1) if minutes else 0,
                   address=tgt[0] if minutes else 0,
                   query_address=query_address if minutes else 0, duration=minutes)
        table = [new if b["index"] == index else b for b in items]
        msgs = await _save_after([spektra_map.burnins_to_message(table, _controller._next_id())])
    except Exception as err:  # noqa: BLE001
        return _err(err)
    body = "was:\n" + _describe_burnin(items[index]) + "\nnow:\n" + _describe_burnin(
        {**new, "remaining": new["duration"]})
    token = _new_token(msgs, body)
    return (f"PREVIEW:\n{body}\nWriting burn-ins restarts every countdown. "
            f"Call confirm(token=\"{token}\").")


# --- zone editor ---------------------------------------------------------------------

_ZONE_PROTOCOLS = {"dali": 0, "dmx": 1, "dt8": 2, "dt8_xy": 3}
from ..colour import CHANNEL_COLOURS as _COLOUR_NAMES   # noqa: E402  (shared with set_zone_colour)


@server.tool()
async def preview_zone(zone: int, protocol: str, line: int, lights: int, channels: str,
                       start_address: int) -> str:
    """Create or change a Spektra colour zone (0-based; Zone 1 = 0). protocol: dali,
    dmx, dt8 (DALI DT8 RGBWAF: one address per light, channels = its colours) or
    dt8_xy (DALI DT8 colour coordinates: the channels are mixed into one xy point). line: 1-4. lights: how many fixtures. channels: the colour of each channel
    in order, e.g. 'red,green,blue,white' (white = warm white, as SpektraPlus models
    RGBW; also warm, cool, amber, lime, uv, or #RRGGBB). start_address: first DALI address / DMX channel; light n starts at
    start_address + n x channels. The controller always drives a zone per address
    (set_zone_colour can send a live colour to DALI groups instead). Zones apply after
    a save, which this includes. Returns a token."""
    try:
        zones = await _controller.pull_zones()
        old = next((z for z in zones if z.get("index") == zone), None)
        if old is None:
            return f"Zone {zone + 1} is not a zone slot on this controller."
        if protocol.lower() not in _ZONE_PROTOCOLS:
            return "protocol: dali, dmx, dt8 or dt8_xy."
        cols = []
        for c in channels.split(","):
            c = c.strip().lower()
            hexv = _COLOUR_NAMES.get(c, c.upper() if c.startswith("#") else None)
            if not hexv or len(hexv) != 7:
                return f"Unknown channel colour '{c}'."
            cols.append(hexv.upper())
        n, is_dali = len(cols), protocol.lower() in ("dali", "dt8", "dt8_xy")
        per_light = 1 if protocol.lower() in ("dt8", "dt8_xy") else n
        last = start_address + lights * per_light - 1
        if is_dali and (start_address < 0 or last > 63):
            return f"DALI addresses would run {start_address}-{last}; they must sit in 0-63."
        if not is_dali and not (1 <= start_address and last <= 512):
            return f"DMX channels would run {start_address}-{last}; they must sit in 1-512."
        new = dict(old, protocol=_ZONE_PROTOCOLS[protocol.lower()], linemask=1 << (line - 1),
                   numLights=lights, numChannels=n, channelColours=cols,
                   startAddress=start_address, multiLineAddressing=0,
                   daligroupoffset=None)
        msgs = [spektra_map.zone_to_message(new, _controller._next_id(), is_dali),
                spektra_map.zone_save_message(_controller._next_id())]
    except Exception as err:  # noqa: BLE001
        return _err(err)
    warn = ""
    if is_dali:
        # The controller's Spektra engine sends a stored 255 as a DALI arc level, which
        # is MASK ("no change"): that channel does not move. Live colour caps at 254.
        try:
            hits = [f"sequence {x['index'] + 1}" for x in await _controller.pull_sequences()
                    if any(255 in (c.get("channelValues") or []) for c in x.get("colours") or [])]
            hits += [f"theme {x['index'] + 1}" for x in await _controller.pull_themes()
                     if any(255 in (c.get("channelValues") or []) for c in x.get("colours") or [])]
        except Exception:  # noqa: BLE001 - the warning is best-effort
            hits = []
        if protocol.lower() == "dali":
            warn += ("\nNOTE: on DALI, a sequence's blend fade only works on fittings in "
                     "DALI group 15 - the controller sends the fade time to group 15 when a "
                     "sequence starts (opt-in). Add the zone's addresses with "
                     "dali_add_to_group (group 15) if you want blends to fade.")
        if hits:
            warn += (f"\nNOTE: {len(hits)} stored item(s) use level 255 ({', '.join(hits[:8])}"
                    f"{', ...' if len(hits) > 8 else ''}). Played on a DALI zone, 255 is DALI "
                    "'no change', so those channels stay where they are - re-save them with "
                    "254 as the top value for DALI.")
    where = f"{'DALI addresses' if is_dali else 'DMX channels'} {start_address}-{last}"
    body = (f"  Zone {zone + 1}: {lights} light(s) x {n} channel(s) "
            f"({', '.join(channels.split(','))}), {protocol.upper()} line {line}, {where}")
    token = _new_token(msgs, body)
    return f"PREVIEW:\n{body}{warn}\nCall confirm(token=\"{token}\") to write and save."
