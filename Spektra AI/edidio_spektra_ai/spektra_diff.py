"""Section-aware structural diff between two ``.spektra`` projects.

Compares per controller (MAC), per config section, per slot (by ``index``), and
reports what was added, removed, or changed. Used to answer "what changed between
these two saves?" and to preview a delta before syncing. Transient/noise fields
(``error``) are ignored so cosmetic churn doesn't show up as a change.
"""

from __future__ import annotations

from dataclasses import dataclass

from .spektra_file import DEVICE_SECTIONS, PROFILE_SECTIONS, SpektraProject

# Fields that carry runtime state, not config — ignored when comparing.
_TRANSIENT = {"error", "remaining", "isConnected", "state", "states"}

ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"


@dataclass
class DiffEntry:
    mac: str
    section: str           # e.g. "sequences" or "profile0.inputs"
    index: object
    change: str            # ADDED | REMOVED | CHANGED
    detail: str = ""


def _strip(item):
    """Recursively drop transient fields for a stable comparison."""
    if isinstance(item, dict):
        return {k: _strip(v) for k, v in item.items() if k not in _TRANSIENT}
    if isinstance(item, list):
        return [_strip(v) for v in item]
    return item


def _by_index(items) -> dict:
    """Map a section's array to {index: item}, falling back to position."""
    out = {}
    if not isinstance(items, list):
        return out
    for pos, item in enumerate(items):
        key = item.get("index", pos) if isinstance(item, dict) else pos
        out[key] = item
    return out


def _changed_keys(a: dict, b: dict) -> list[str]:
    keys = set(a) | set(b)
    return sorted(k for k in keys if _strip(a.get(k)) != _strip(b.get(k)))


def _diff_section(mac, section, items_a, items_b, out: list[DiffEntry]):
    a_map, b_map = _by_index(items_a), _by_index(items_b)
    for idx in sorted(set(a_map) | set(b_map), key=lambda x: (str(type(x)), x)):
        a, b = a_map.get(idx), b_map.get(idx)
        if a is None:
            out.append(DiffEntry(mac, section, idx, ADDED))
        elif b is None:
            out.append(DiffEntry(mac, section, idx, REMOVED))
        elif _strip(a) != _strip(b):
            keys = _changed_keys(a, b) if isinstance(a, dict) and isinstance(b, dict) else []
            out.append(DiffEntry(mac, section, idx, CHANGED,
                                 "fields: " + ", ".join(keys) if keys else ""))


def diff(proj_a: SpektraProject, proj_b: SpektraProject) -> list[DiffEntry]:
    """Return structural differences going from ``proj_a`` (old) to ``proj_b`` (new)."""
    out: list[DiffEntry] = []
    macs_a, macs_b = set(proj_a.macs), set(proj_b.macs)

    for mac in sorted(macs_a | macs_b):
        if mac not in macs_a:
            out.append(DiffEntry(mac, "", "", ADDED, "eDIDIO added"))
            continue
        if mac not in macs_b:
            out.append(DiffEntry(mac, "", "", REMOVED, "eDIDIO removed"))
            continue

        ed_a, ed_b = proj_a.edidio(mac), proj_b.edidio(mac)
        for section in DEVICE_SECTIONS:
            _diff_section(mac, section, ed_a.get(section), ed_b.get(section), out)

        profs_a, profs_b = ed_a.get("profiles") or [], ed_b.get("profiles") or []
        for pi in range(max(len(profs_a), len(profs_b))):
            pa = profs_a[pi] if pi < len(profs_a) else {}
            pb_ = profs_b[pi] if pi < len(profs_b) else {}
            for sub in PROFILE_SECTIONS:
                _diff_section(mac, f"profile{pi}.{sub}", pa.get(sub), pb_.get(sub), out)
    return out


def format_diff(entries: list[DiffEntry]) -> str:
    """Human-readable diff report."""
    if not entries:
        return "No differences."
    counts = {ADDED: 0, REMOVED: 0, CHANGED: 0}
    for e in entries:
        counts[e.change] += 1
    lines = [f"{counts[ADDED]} added, {counts[REMOVED]} removed, {counts[CHANGED]} changed:"]
    for e in entries:
        where = f"{e.mac} {e.section}".strip() + (f"[{e.index}]" if e.index != "" else "")
        detail = f" ({e.detail})" if e.detail else ""
        lines.append(f"  - {e.change}: {where}{detail}")
    return "\n".join(lines)
