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
            _check_title(item, mac, section, out)
            _check_colours(item.get("colours"), mac, section, idx, out)
        elif section == "themes":
            _check_index(item, mac, section, THEME_MAX_INDEX, out)
            _check_title(item, mac, section, out)
            _check_colours(item.get("colours"), mac, section, idx, out)
        elif section == "schedules":
            _check_index(item, mac, section, ALARM_MAX_INDEX, out)

        for path in _COMMAND_FIELDS.get(section, ()):
            _check_command(_dig(item, path), mac, section, idx,
                           ".".join(path), out)


def validate(project: SpektraProject) -> list[Issue]:
    """Return a list of validation :class:`Issue`s (empty ⇒ clean)."""
    out: list[Issue] = []
    for mac, ed in project.iter_edidios():
        for section in DEVICE_SECTIONS:
            _validate_section(mac, section, ed.get(section), out)
        for prof in ed.get("profiles") or []:
            for section in PROFILE_SECTIONS:
                _validate_section(mac, section, prof.get(section), out)
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
