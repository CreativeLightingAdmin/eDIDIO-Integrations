"""Hash-based sync detection + v3 ``syncData`` ledger.

Ports SpektraPlus's sync-hash canonicalisation pipeline so a section's
hash here matches the app's: strip transient fields -> trim trailing zeros on
channel arrays -> per-type canonicalisers -> sort index-keyed arrays -> SHA-256 of
sorted-key, JS-number-compatible JSON. Used to detect per-section SYNCED / UNSYNCED /
DESYNCED against a live controller and to write the ``ProjectState.syncData`` ledger.

Byte-parity with SpektraPlus is the intent (same algorithm); it's unverified against
the TS runtime, but a mismatch is safe — the app just re-verifies against the device.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

# --- transient fields (as SpektraPlus strips them) ---
_GLOBAL = {"error", "uuid", "identifier"}
_NESTED = {"duration", "timeUnit", "light_state", "running_flag", "enable_flag"}
_TYPE_TRANSIENT = {
    "lists": {"name", "totalStepCount", "scheduledDates", "loop_on_startup"},
    "schedules": {"name", "yearly"},
    # fadeTimeUnit is NOT transient: _canon_fade_time folds it into fadeTime (ms).
    "sequences": {"presetSequenceID", "scheduledDates"},
    "themes": {"scheduledDates"},
    "zones": {"alias", "daligroupoffset", "daligrouping", "channelTypes"},
    "logicActions": {"name", "isEnabled"},
    "inputs": {"name", "priorInputType"},
    "outputs": {"name"},
    "sensors": {"name", "prgBtnOne", "prgBtnTwo"},
    "daliInputs": {"name", "isActive"},
    "burnIns": {"name", "remaining", "enabled"},
    "controlTranslations": {"name"},
}

PROFILE_BASED = {"inputs", "outputs", "sensors", "daliInputs"}
# Sections this module can hash/sync (all with device-backed protocol support).
SYNC_SECTIONS = ("sequences", "themes", "zones", "schedules", "logicActions",
                 "lists", "inputs", "outputs", "sensors", "daliInputs",
                 "burnIns", "controlTranslations")
# The sync data type name -> where it lives in the eDIDIO dict, when they differ.
FILE_KEY = {"controlTranslations": "translations"}

_MIN_STEP_MS = 50
_MIN_ZONE_SCALE = 0.1
# Controller title storage in UTF-8 bytes: a sequence keeps 23, a theme 27. The
# wire allows 27 bytes; a longer title fails to decode and the whole write is
# refused (DECODE_FAILED).
SEQUENCE_TITLE_MAX_BYTES = 23
THEME_TITLE_MAX_BYTES = 27
NO_COMMAND = 254
_MS_PER_TIME_UNIT = {0: 1, 1: 1000, 2: 60000, 3: 3600000}
_DMX_MIN, _DMX_MAX = 1, 512


def truncate_utf8(value: str, max_bytes: int) -> str:
    """Longest code-point prefix of ``value`` whose UTF-8 fits ``max_bytes``."""
    if len(value.encode("utf-8")) <= max_bytes:
        return value
    out, used = [], 0
    for ch in value:
        size = len(ch.encode("utf-8"))
        if used + size > max_bytes:
            break
        out.append(ch)
        used += size
    return "".join(out)


def device_sequence_title(name: str) -> str:
    return truncate_utf8(name, SEQUENCE_TITLE_MAX_BYTES)


def device_theme_title(name: str) -> str:
    return truncate_utf8(name, THEME_TITLE_MAX_BYTES)


# --- pipeline steps ---------------------------------------------------------

def _strip(data, data_type, is_root=True):
    if isinstance(data, list):
        return [_strip(x, data_type, is_root) for x in data]
    if isinstance(data, dict):
        remove = set(_GLOBAL)
        if not is_root:
            remove |= _NESTED
        if is_root:
            remove |= _TYPE_TRANSIENT.get(data_type, set())
        return {k: (_strip(v, data_type, False) if isinstance(v, (dict, list)) else v)
                for k, v in data.items() if k not in remove}
    return data


def _trim_channels(data):
    if isinstance(data, list):
        return [_trim_channels(x) for x in data]
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if k == "channelValues" and isinstance(v, list) and all(
                    isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
                end = len(v)
                while end > 0 and v[end - 1] == 0:
                    end -= 1
                out[k] = v[:end]
            else:
                out[k] = _trim_channels(v)
        return out
    return data


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _js_round(x: float) -> int:
    """JS Math.round (half rounds up, toward +inf), not Python's banker's round."""
    import math
    return math.floor(x + 0.5)


def _canon_fade_time(data):
    """Fade time as SpektraPlus hashes it: fadeTime -> ms at 10 ms resolution,
    fadeTimeUnit dropped (only on the item that carries the unit)."""
    if isinstance(data, list):
        return [_canon_fade_time(x) for x in data]
    if not isinstance(data, dict) or "fadeTimeUnit" not in data:
        return data
    rest = {k: v for k, v in data.items() if k != "fadeTimeUnit"}
    factor = _MS_PER_TIME_UNIT.get(data["fadeTimeUnit"]) if _is_num(data["fadeTimeUnit"]) else None
    if _is_num(rest.get("fadeTime")) and factor is not None:
        rest["fadeTime"] = _js_round(rest["fadeTime"] * factor / 10) * 10
    return rest


def _canon_no_command(data):
    """A NO_COMMAND trigger has no target (as the controller reads it back)."""
    if isinstance(data, list):
        return [_canon_no_command(x) for x in data]
    if not isinstance(data, dict):
        return data
    if data.get("commandtype") == NO_COMMAND and not isinstance(data.get("commandtype"), bool):
        return {**data, "zone": 0, "linemask": 0, "target": 0, "value": 0, "query": 0}
    return {k: _canon_no_command(v) for k, v in data.items()}


def _canon_dmx_start(data):
    """DMX start address clamped to 1-512, as the controller stores it."""
    if isinstance(data, list):
        return [_canon_dmx_start(x) for x in data]
    if not isinstance(data, dict):
        return data
    out = {k: _canon_dmx_start(v) for k, v in data.items()}
    if _is_num(out.get("DMXStartAddress")):
        start = min(max(out["DMXStartAddress"], _DMX_MIN), _DMX_MAX)
        out["DMXStartAddress"] = start
        if _is_num(out.get("DMXEndAddress")):
            out["DMXEndAddress"] = start + max(out["DMXEndAddress"] - start, 0)
    return out


def _clamp_step(value, unit):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not isinstance(unit, (int, float)) or isinstance(unit, bool):
        return None
    if value == 0:
        return (_MIN_STEP_MS, 0)
    if unit == 0 and value < _MIN_STEP_MS:
        return (_MIN_STEP_MS, unit)
    return (value, unit)


def _canon_sequences(data):
    if isinstance(data, list):
        return [_canon_sequences(x) for x in data]
    if isinstance(data, dict):
        out = {k: _canon_sequences(v) for k, v in data.items()}
        for tv, tu in (("timePerColour", "timePerColourUnit"),
                       ("timePerStep", "timePerStepUnit")):
            if tv in out and tu in out:
                c = _clamp_step(out[tv], out[tu])
                if c:
                    out[tv], out[tu] = c
        return out
    return data


def _canon_seq_title(data):
    if isinstance(data, list):
        return [_canon_seq_title(x) for x in data]
    if isinstance(data, dict):
        return _canon_title({k: _canon_seq_title(v) for k, v in data.items()},
                            "Sequence", device_sequence_title)
    return data


def _canon_title(obj, prefix, to_device):
    # JS `typeof index === 'number'` also accepts floats.
    if isinstance(obj, dict) and isinstance(obj.get("name"), str) and _is_num(obj.get("index")):
        truncated = to_device(obj["name"])
        obj = dict(obj)
        obj["name"] = truncated if truncated else f"{prefix} {obj['index'] + 1}"
    return obj


def _canon_themes(data):
    if isinstance(data, list):
        return [_canon_themes(x) for x in data]
    if isinstance(data, dict):
        return _canon_title({k: _canon_themes(v) for k, v in data.items()}, "Theme",
                            device_theme_title)
    return data


def _canon_zones(data):
    if isinstance(data, list):
        return [_canon_zones(x) for x in data]
    if isinstance(data, dict):
        out = {k: _canon_zones(v) for k, v in data.items()}
        sf = out.get("scaleFactor")
        if isinstance(sf, (int, float)) and not isinstance(sf, bool):
            clamped = sf if _MIN_ZONE_SCALE <= sf <= 1 else 1
            out["scaleFactor"] = _js_round(clamped * 1000) / 1000
        return out
    return data


def _canon_sensors(data):
    if isinstance(data, list):
        return [_canon_sensors(x) for x in data]
    if isinstance(data, dict):
        out = {k: _canon_sensors(v) for k, v in data.items()}
        if any(k in out for k in ("groupedWithIndexes", "coopGroup", "coopLeader")):
            out["coopGroup"] = 0 if out.get("coopGroup") is None else out["coopGroup"]
            out["coopLeader"] = False if out.get("coopLeader") is None else out["coopLeader"]
            out["groupedWithIndexes"] = ([] if out.get("groupedWithIndexes") is None
                                         else out["groupedWithIndexes"])
        return out
    return data


# Per-type canonicalisers, applied in order (as SpektraPlus applies them).
_CANONICALIZERS = {
    "sequences": [_canon_fade_time, _canon_sequences, _canon_seq_title],
    "themes": [_canon_themes],
    "zones": [_canon_zones],
    "controlTranslations": [_canon_dmx_start],
    "sensors": [_canon_sensors, _canon_no_command],
    "inputs": [_canon_no_command],
    "daliInputs": [_canon_no_command],
    "lists": [_canon_no_command],
    "schedules": [_canon_no_command],
    "logicActions": [_canon_no_command],
}


def _sort_by_index(arr):
    if len(arr) < 2:
        return arr
    if all(isinstance(x, dict) and _is_num(x.get("index")) for x in arr):
        return sorted(arr, key=lambda x: x["index"])
    return arr


def _canon_order(data, data_type):
    if not isinstance(data, list):
        return data
    if data_type in PROFILE_BASED:
        return [_sort_by_index(p) if isinstance(p, list) else p for p in data]
    return _sort_by_index(data)


def canonicalize(data, data_type):
    """Full device-context-free normalisation (as SpektraPlus canonicalises)."""
    cleaned = _strip(data, data_type)
    cleaned = _trim_channels(cleaned)
    for fn in _CANONICALIZERS.get(data_type, ()):
        cleaned = fn(cleaned)
    return _canon_order(cleaned, data_type)


# --- JS-number-compatible canonical JSON + hash -----------------------------

def _js_numbers(value):
    """Match JS JSON.stringify number output: integral floats serialise as ints."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_js_numbers(v) for v in value]
    if isinstance(value, dict):
        return {k: _js_numbers(v) for k, v in value.items()}
    return value


def _hash(data):
    text = json.dumps(_js_numbers(data), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_section(value, data_type):
    """Hash a section's value (array, or per-profile 2-D array) after canonicalising.
    None/absent normalises to the empty array (all sync sections are array types)."""
    if value is None:
        value = []
    return _hash(canonicalize(value, data_type))


def section_value(edidio: dict, data_type: str):
    """Extract a section's value from an eDIDIO dict in the shape SpektraPlus hashes:
    a flat array for device-level types, a per-profile 2-D array for profile types."""
    if data_type in PROFILE_BASED:
        return [(prof.get(data_type) or []) for prof in (edidio.get("profiles") or [])]
    return edidio.get(FILE_KEY.get(data_type, data_type)) or []


# --- status detection + ledger ----------------------------------------------

SYNCED, UNSYNCED, DESYNCED = "SYNCED", "UNSYNCED", "DESYNCED"


def _prior_hashes(project) -> dict:
    """Read lastSyncedStateHash per 'MAC:section' from the file's existing syncData."""
    out = {}
    sd = project.raw.get("syncData")
    if isinstance(sd, dict):
        for key, st in (sd.get("syncStates") or {}).items():
            if isinstance(st, dict):
                out[key] = st.get("lastSyncedStateHash")
    return out


def compute_status(file_project, live_edidios: dict, sections=SYNC_SECTIONS) -> list:
    """Per (mac, section) status comparing file vs live, refined by the file's ledger.

    live_edidios: {mac: edidio_dict} pulled from the device.
    Returns dicts: {mac, section, status, file_hash, live_hash}.
    """
    prior = _prior_hashes(file_project)
    out = []
    for mac, ed in file_project.iter_edidios():
        live = live_edidios.get(mac, {})
        for section in sections:
            fh = hash_section(section_value(ed, section), section)
            lh = hash_section(section_value(live, section), section)
            base = prior.get(f"{mac}:{section}")
            if fh == lh:
                status = SYNCED
            elif base is None or (base == lh and base != fh):
                status = UNSYNCED          # local edits to push (device still at baseline)
            else:
                status = DESYNCED          # device changed out-of-band (and/or both moved)
            out.append({"mac": mac, "section": section, "status": status,
                        "file_hash": fh, "live_hash": lh})
    return out


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def mark_synced(project, mac: str, sections: list):
    """Record the given sections as SYNCED in the file's v3 syncData ledger, using the
    current file hash as the synced baseline (call after a successful push)."""
    project.raw.setdefault("fileFormatVersion", 3)
    sd = project.raw.setdefault("syncData", {})
    states = sd.setdefault("syncStates", {})
    sd.setdefault("rollbackHistory", [])
    sd.setdefault("syncQueue", [])
    now = _now_ms()
    ed = project.edidio(mac)
    # SpektraPlus >= 1.3.0 also keeps per-item baselines (itemSyncStates, key
    # "MAC:dataType:itemId"). After we rewrite a section they are stale and the app
    # would flag the items as conflicts. Drop them for the touched sections: an item
    # with no baseline is not judged, and the app re-seeds baselines on its next read.
    items = sd.get("itemSyncStates")
    if isinstance(items, dict):
        prefixes = tuple(f"{mac}:{section}:" for section in sections)
        for key in [k for k in items if k.startswith(prefixes)]:
            del items[key]
    for section in sections:
        h = hash_section(section_value(ed, section), section)
        states[f"{mac}:{section}"] = {
            "deviceMac": mac, "dataType": section, "status": SYNCED,
            "lastSyncedStateHash": h, "lastReadStateHash": h,
            "lastSyncTimestamp": now, "lastReadTimestamp": now,
        }


def format_status(rows: list) -> str:
    """Human-readable sync report (only sections that aren't clean, plus a summary)."""
    by_status = {SYNCED: 0, UNSYNCED: 0, DESYNCED: 0}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    lines = [f"Sync: {by_status[SYNCED]} synced, {by_status[UNSYNCED]} unsynced, "
             f"{by_status[DESYNCED]} desynced."]
    for r in rows:
        if r["status"] != SYNCED:
            lines.append(f"  - {r['mac']} {r['section']}: {r['status']}")
    if len(lines) == 1:
        lines.append("  everything in sync.")
    return "\n".join(lines)
