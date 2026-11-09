"""Validate a ``.spektra`` project against protocol enums and firmware limits.

Offline, structural validation only — it never touches a controller. Checks the
invariants that would make a config invalid or refuse to write on the device:
indices within firmware slot limits, colour channel values in range, colour counts
within limits, titles within length, and every embedded command's ``commandtype``
being a real ``TriggerType``. Command/enum values come from the live protobuf
descriptors (``edidio_control_py``) so they stay in sync with the firmware.
"""

from __future__ import annotations

from dataclasses import dataclass

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb

from .commands import kelvin_to_value
from .spektra_file import DEVICE_SECTIONS, PROFILE_SECTIONS, SpektraProject, _is_configured

# Firmware slot / value limits (see CAPABILITY_GUIDE.md; device also reports counts).
SEQUENCE_MAX_INDEX = 143
THEME_MAX_INDEX = 15
ALARM_MAX_INDEX = 8
MAX_COLOURS = 20
MAX_TITLE = 28
MIN_CHANNEL = 0
MAX_CHANNEL = 255            # DMX max; DALI caps at 254 (a mapping concern, not invalid)
MAX_CHANNELS_PER_COLOUR = 16

# Valid TriggerType numbers, straight from the protocol descriptors.
_VALID_TRIGGER_TYPES = {v.number for v in pb.TriggerType.DESCRIPTOR.values}

ERROR = "error"
WARNING = "warning"

# Config sections whose items embed command objects, and which fields hold them.
_COMMAND_FIELDS = {
    "schedules": (("startEvent", "command"), ("endEvent", "command")),
    "logicActions": (("comparisonObject",), ("trueAction",), ("falseAction",)),
    "inputs": (("shortLowAction",), ("longHighAction",)),
    "daliInputs": (("shortLowAction",), ("longHighAction",)),
    "outputs": (("action",),),
}


@dataclass
class Issue:
    mac: str
    section: str
    index: object          # int slot index, or "" when not applicable
    level: str             # ERROR | WARNING
    message: str


def _dig(item: dict, path: tuple[str, ...]):
    """Follow a nested key path; return the dict at the end or None."""
    cur = item
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _check_command(cmd, mac, section, idx, label, out: list[Issue]):
    if not isinstance(cmd, dict):
        return
    ctype = cmd.get("commandtype")
    if ctype is not None and ctype not in _VALID_TRIGGER_TYPES:
        out.append(Issue(mac, section, idx, ERROR,
                         f"{label}: unknown commandtype {ctype} (not a TriggerType)"))


def _check_colours(colours, mac, section, idx, out: list[Issue]):
    if not isinstance(colours, list):
        return
    if len(colours) > MAX_COLOURS:
        out.append(Issue(mac, section, idx, ERROR,
                         f"{len(colours)} colours exceeds max {MAX_COLOURS}"))
    for ci, colour in enumerate(colours):
        vals = (colour or {}).get("channelValues") if isinstance(colour, dict) else None
        if not isinstance(vals, list):
            continue
        if len(vals) > MAX_CHANNELS_PER_COLOUR:
            out.append(Issue(mac, section, idx, WARNING,
                             f"colour {ci} has {len(vals)} channels (>{MAX_CHANNELS_PER_COLOUR})"))
        for v in vals:
            if not isinstance(v, int) or v < MIN_CHANNEL or v > MAX_CHANNEL:
                out.append(Issue(mac, section, idx, ERROR,
                                 f"colour {ci} value {v!r} out of range {MIN_CHANNEL}-{MAX_CHANNEL}"))
                break


def _check_index(item, mac, section, max_index, out: list[Issue]):
    idx = item.get("index")
    if isinstance(idx, int) and idx > max_index:
        out.append(Issue(mac, section, idx, ERROR,
                         f"index {idx} exceeds max {max_index}"))


def _check_title(item, mac, section, out: list[Issue]):
    title = item.get("name") or item.get("title") or ""
    if isinstance(title, str) and len(title) > MAX_TITLE:
        out.append(Issue(mac, section, item.get("index", ""), WARNING,
                         f'name "{title}" exceeds {MAX_TITLE} chars'))


def _validate_section(mac, section, items, out: list[Issue]):
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict) or not _is_configured(section, item):
            continue
        idx = item.get("index", "")

        if section == "sequences":
            _check_index(item, mac, section, SEQUENCE_MAX_INDEX, out)
            _check_colours(item.get("colours"), mac, section, idx, out)
        elif section == "themes":
            _check_index(item, mac, section, THEME_MAX_INDEX, out)
            _check_colours(item.get("colours"), mac, section, idx, out)
        elif section == "schedules":
            _check_index(item, mac, section, ALARM_MAX_INDEX, out)

        for path in _COMMAND_FIELDS.get(section, ()):
            if section == "logicActions" and path == ("comparisonObject",):
                continue      # a LogicType, not a TriggerType (checked in _firmware_limits)
            _check_command(_dig(item, path), mac, section, idx,
                           ".".join(path), out)
        _firmware_limits(mac, section, item, out)


# --- firmware 1.6.3 limits ------------------------------------------------------
# 1.6.3 refuses a value it cannot store (INVALID_PARAMS) where older firmware cut it
# and still said SUCCESS; these checks catch them before a push.
SEQUENCE_TITLE_BYTES = 23
THEME_TITLE_BYTES = 27
SEQUENCE_TYPES = 16                 # sequence types 0-15
MAX_TRANSITION = 2                  # FADE_TO_BLACK
MAX_TIME_UNIT = 3                   # ms / s / min / h
MAX_LIST_STEPS = 255
LIST_STEP_MAX_SECONDS = 65535
VALID_INPUT_TYPES = {0, 1, 2, 3, 4, 128, 129}
VALID_LIST_STATES = set(range(6))   # the show bit lives in isShow
MAX_REPEAT, MAX_ASTRO = 4, 2
_TRIGGER_KEYS = ("zone", "linemask", "target", "value", "query")


def _iter_triggers(obj, path=""):
    """Every trigger dict (has 'commandtype') inside an item, with its path."""
    if isinstance(obj, dict):
        if "commandtype" in obj:
            yield path or "command", obj
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and k != "commandtype":
                yield from _iter_triggers(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_triggers(v, f"{path}[{i}]")


def _check_trigger_fits(item, mac, section, idx, out):
    for path, cmd in _iter_triggers(item):
        for k in _TRIGGER_KEYS:
            v = cmd.get(k, 0)
            if isinstance(v, int) and not 0 <= v <= 255:
                if k == "value" and cmd.get("commandtype") == 47 and 1000 <= v <= 20000:
                    out.append(Issue(mac, section, idx, ERROR,
                                     f"{path}.value = {v} looks like Kelvin, but DT8 colour "
                                     "temperature (commandtype 47) stores mirek / 4: for "
                                     f"{v} K use {kelvin_to_value(v)}. Firmware 1.6.3 refuses "
                                     "the write; older firmware keeps only the low byte"))
                    continue
                out.append(Issue(mac, section, idx, ERROR,
                                 f"{path}.{k} = {v} does not fit the controller (0-255); "
                                 "firmware 1.6.3 refuses the write"))


def _utf8_len(text) -> int:
    return len(str(text).encode("utf-8"))


def _hms(text):
    try:
        h, m, sec = (int(x) for x in str(text).split(":"))
        return h, m, sec
    except ValueError:
        return None


def _firmware_limits(mac, section, item, out):
    idx = item.get("index", "")
    if section == "sequences":
        name = item.get("name") or ""
        if _utf8_len(name) > SEQUENCE_TITLE_BYTES:
            out.append(Issue(mac, section, idx, WARNING,
                             f'name "{name}" is {_utf8_len(name)} bytes; the controller '
                             f"keeps {SEQUENCE_TITLE_BYTES} (it is cut on push)"))
        st = item.get("sequenceType")
        if isinstance(st, int) and not 0 <= st < SEQUENCE_TYPES:
            out.append(Issue(mac, section, idx, ERROR, f"sequenceType {st} unknown (0-15)"))
        tt = item.get("transitionType")
        if isinstance(tt, int) and not 0 <= tt <= MAX_TRANSITION:
            out.append(Issue(mac, section, idx, ERROR, f"transitionType {tt} unknown (0-2)"))
        for key in ("timePerColourUnit", "timePerStepUnit", "fadeTimeUnit"):
            u = item.get(key)
            if isinstance(u, int) and not 0 <= u <= MAX_TIME_UNIT:
                out.append(Issue(mac, section, idx, ERROR, f"{key} {u} unknown (0-3)"))
        for key in ("timePerColour", "timePerStep", "range"):
            v = item.get(key)
            if isinstance(v, (int, float)) and not 0 <= v <= 65535:
                out.append(Issue(mac, section, idx, ERROR, f"{key} {v} exceeds 65535"))
        if not item.get("colours"):
            out.append(Issue(mac, section, idx, ERROR,
                             "no colours: the controller refuses it (older firmware "
                             "deleted the sequence)"))
    elif section == "themes":
        name = item.get("name") or ""
        if _utf8_len(name) > THEME_TITLE_BYTES:
            out.append(Issue(mac, section, idx, WARNING,
                             f'name "{name}" is {_utf8_len(name)} bytes; the controller '
                             f"keeps {THEME_TITLE_BYTES} (it is cut on push)"))
        if not item.get("colours"):
            out.append(Issue(mac, section, idx, ERROR, "no colours: the controller refuses it"))
    elif section == "lists":
        steps = item.get("steps") or []
        if len(steps) > MAX_LIST_STEPS:
            out.append(Issue(mac, section, idx, ERROR,
                             f"{len(steps)} steps; a list holds at most {MAX_LIST_STEPS}"))
        state = item.get("state", 0)
        if isinstance(state, int) and state not in VALID_LIST_STATES:
            out.append(Issue(mac, section, idx, ERROR, f"state {state} unknown (0-5)"))
        for st in steps:
            t = st.get("time_until_next", 0)
            if isinstance(t, (int, float)) and not 0 <= t <= LIST_STEP_MAX_SECONDS:
                out.append(Issue(mac, section, idx, ERROR,
                                 f"step {st.get('index')} waits {t} s (max {LIST_STEP_MAX_SECONDS})"))
    elif section == "schedules":
        rep_ = item.get("repeat", 0)
        if isinstance(rep_, int) and not 0 <= rep_ <= MAX_REPEAT:
            out.append(Issue(mac, section, idx, ERROR, f"repeat {rep_} unknown (0-4)"))
        if isinstance(item.get("weekdaysMask"), int) and not 0 <= item["weekdaysMask"] <= 0xFF:
            out.append(Issue(mac, section, idx, ERROR, "weekdaysMask does not fit 8 bits"))
        if isinstance(item.get("monthsMask"), int) and not 0 <= item["monthsMask"] <= 0xFFFF:
            out.append(Issue(mac, section, idx, ERROR, "monthsMask does not fit 16 bits"))
        for ev in ("startEvent", "endEvent"):
            e = item.get(ev) or {}
            astro = e.get("type", 0)
            if isinstance(astro, int) and not 0 <= astro <= MAX_ASTRO:
                out.append(Issue(mac, section, idx, ERROR, f"{ev}.type {astro} unknown (0-2)"))
            hms = _hms(e.get("time", "00:00:00"))
            if hms and (hms[1] > 59 or hms[2] > 59):
                out.append(Issue(mac, section, idx, ERROR, f"{ev}.time {e.get('time')} invalid"))
            date = str(e.get("date", ""))
            if date and not date.startswith("2000-00-00"):
                try:
                    _y, mo, d = (int(x) for x in date.split("-"))
                    if not (1 <= mo <= 12 and 1 <= d <= 31):
                        raise ValueError
                except ValueError:
                    out.append(Issue(mac, section, idx, ERROR, f"{ev}.date {date} invalid"))
    elif section == "inputs":
        t = item.get("type", 0)
        if isinstance(t, int) and t not in VALID_INPUT_TYPES:
            out.append(Issue(mac, section, idx, ERROR, f"type {t} is not a TriggerOperationType"))
    elif section == "logicActions":
        src = (item.get("comparisonObject") or {}).get("commandtype", 254)
        cmp_ = item.get("comparisonType", 0)
        if src != 254 and not (0 <= src <= 9 and 0 <= cmp_ <= 8):
            out.append(Issue(mac, section, idx, ERROR,
                             f"logic source {src} / comparison {cmp_} unknown"))
    _check_trigger_fits(item, mac, section, idx, out)


def _ver(v) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split("-")[0].split(".")[:3])
    except ValueError:
        return ()


def _project_checks(project, out):
    """Whole-file rules: problems that stop SpektraPlus opening a file correctly."""
    app = project.raw.get("appVersion", "")
    old_app = bool(_ver(app)) and _ver(app) < (1, 3, 0)
    for mac, ed in project.iter_edidios():
        net = ed.get("network") or {}
        if net.get("mac") and net["mac"].upper() != mac.upper():
            out.append(Issue(mac, "network", "", ERROR,
                             f"network.mac {net['mac']} differs from the controller key: "
                             "SpektraPlus selects controllers by network.mac"))
        if old_app:
            for g in ed.get("logicActions") or []:
                src = (g.get("comparisonObject") or {}).get("commandtype")
                if src in (1, 2, 3) and g.get("isEnabled", True):
                    out.append(Issue(mac, "logicActions", g.get("index", ""), WARNING,
                                     f"made with SpektraPlus {app}: before 1.3.0 the app saved "
                                     "Input/List/Sensor logic targets one too high - check "
                                     "this rule's target"))


def validate(project: SpektraProject) -> list[Issue]:
    """Return a list of validation :class:`Issue`s (empty ⇒ clean)."""
    out: list[Issue] = []
    for mac, ed in project.iter_edidios():
        for section in DEVICE_SECTIONS:
            _validate_section(mac, section, ed.get(section), out)
        for prof in ed.get("profiles") or []:
            for section in PROFILE_SECTIONS:
                _validate_section(mac, section, prof.get(section), out)
    _project_checks(project, out)
    return out


def format_issues(issues: list[Issue]) -> str:
    """Human-readable validation report."""
    if not issues:
        return "Validation passed: no issues found."
    errors = sum(1 for i in issues if i.level == ERROR)
    warnings = len(issues) - errors
    lines = [f"Found {errors} error(s), {warnings} warning(s):"]
    for i in issues:
        where = f"{i.mac} {i.section}" + (f"[{i.index}]" if i.index != "" else "")
        lines.append(f"  - [{i.level}] {where}: {i.message}")
    return "\n".join(lines)
