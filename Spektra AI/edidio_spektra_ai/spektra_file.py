"""Read/write SpektraPlus ``.spektra`` project files (offline, no controller).

A ``.spektra`` file is the JSON project document SpektraPlus saves and pushes to
eDIDIO controllers. This module loads it into a light wrapper that **preserves the
raw dict** (so unknown fields such as ``widgetPages`` and compressed rollback
history survive a round-trip), exposes the per-controller (per-MAC) config, and
normalises the two sync-state formats we see in the wild:

* **legacy** files (e.g. exported by older app builds) — no ``fileFormatVersion``;
  pending sync lives in ``controllerSynchronisationIssues.configFilesDiffer``.
* **v2/v3** files (current SpektraPlus) — ``fileFormatVersion`` + ``syncData``
  (``syncStates`` keyed ``"<MAC>:<dataType>"``, hash-based ``EmbeddedSyncState``).

The authoritative schema is ``SpektraPlus/shared/src/types.ts`` (``ProjectState``,
``Edidio*``, ``ProjectSyncData``); this mirrors it rather than re-deriving it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

# Current SpektraPlus file format (shared/src/types.ts: PROJECT_FILE_FORMAT_VERSION).
CURRENT_FILE_FORMAT_VERSION = 3

# Device-level config sections (arrays directly under each eDIDIO).
DEVICE_SECTIONS = (
    "schedules", "logicActions", "lists", "sequences", "themes", "zones",
    "burnIns", "translations",
)
# Per-profile config sections (arrays inside each profiles[] entry).
PROFILE_SECTIONS = ("inputs", "outputs", "sensors", "daliInputs", "irs", "userLevels")

# EmbeddedSyncState.status values (shared/src/types.ts).
SYNC_SYNCED = "SYNCED"
SYNC_UNSYNCED = "UNSYNCED"
SYNC_DESYNCED = "DESYNCED"
SYNC_FAILED = "SYNC_FAILED"

# Legacy configFilesDiffer status -> v3 EmbeddedSyncState.status.
_LEGACY_STATUS_MAP = {"STAGED": SYNC_UNSYNCED, "SYNCED": SYNC_SYNCED}


class SpektraFileError(Exception):
    """Raised when a .spektra file can't be parsed or is structurally invalid."""


@dataclass
class SyncEntry:
    """A normalised pending-sync record, unified across legacy and v3 files."""

    mac: str
    section: str          # data type / config section, e.g. "inputs", "lists"
    status: str           # normalised EmbeddedSyncState status
    detail: str = ""      # optional human note (timestamps, failure reason)


@dataclass
class SpektraProject:
    """A loaded ``.spektra`` project. Wraps and preserves the raw parsed dict."""

    raw: dict
    path: str | None = None
    _edidios: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if not isinstance(self.raw, dict):
            raise SpektraFileError("Top-level .spektra JSON must be an object.")
        eds = self.raw.get("edidios")
        if not isinstance(eds, dict):
            raise SpektraFileError("Missing or invalid 'edidios' map.")
        self._edidios = eds

    # --- identity / meta ---
    @property
    def name(self) -> str:
        return self.raw.get("name", "")

    @property
    def uid(self) -> str:
        return self.raw.get("uid", "")

    @property
    def app_version(self) -> str:
        return self.raw.get("appVersion", "")

    @property
    def file_format_version(self) -> int:
        """The declared format version; absent ⇒ legacy (treated as 1)."""
        return int(self.raw.get("fileFormatVersion", 1) or 1)

    @property
    def is_legacy(self) -> bool:
        return "fileFormatVersion" not in self.raw

    @property
    def macs(self) -> list[str]:
        return list(self._edidios.keys())

    def iter_edidios(self) -> Iterator[tuple[str, dict]]:
        """Yield ``(mac, edidio_dict)`` for each controller in the project."""
        yield from self._edidios.items()

    def edidio(self, mac: str) -> dict:
        try:
            return self._edidios[mac]
        except KeyError as err:
            raise SpektraFileError(f"No eDIDIO with MAC {mac} in project.") from err

    # --- sync state (unified across formats) ---
    def sync_entries(self) -> list[SyncEntry]:
        """Return pending/known sync records from whichever format the file uses.

        v3 ``syncData.syncStates`` is preferred; otherwise the legacy
        ``controllerSynchronisationIssues.configFilesDiffer`` list is read.
        """
        sync_data = self.raw.get("syncData")
        if isinstance(sync_data, dict) and isinstance(sync_data.get("syncStates"), dict):
            out = []
            for key, st in sync_data["syncStates"].items():
                mac, _, section = key.partition(":")
                out.append(SyncEntry(
                    mac=st.get("deviceMac", mac),
                    section=st.get("dataType", section),
                    status=st.get("status", SYNC_UNSYNCED),
                    detail=st.get("failureReason", "") or "",
                ))
            return out
        return self._legacy_sync_entries()

    def _legacy_sync_entries(self) -> list[SyncEntry]:
        issues = self.raw.get("controllerSynchronisationIssues")
        if not isinstance(issues, dict):
            return []
        out = []
        for d in issues.get("configFilesDiffer", []) or []:
            raw_status = d.get("status", "STAGED")
            out.append(SyncEntry(
                mac=d.get("mac", ""),
                section=d.get("key", ""),
                status=_LEGACY_STATUS_MAP.get(raw_status, SYNC_UNSYNCED),
                detail=f"last diff {d.get('last_attempt', '?')}",
            ))
        # Failure lists, if populated, are surfaced as SYNC_FAILED.
        for listname in ("failedToUpdateProjectSettings", "failedToRemoveProjectSettings"):
            for d in issues.get(listname, []) or []:
                out.append(SyncEntry(
                    mac=d.get("mac", "") if isinstance(d, dict) else "",
                    section=d.get("key", "") if isinstance(d, dict) else str(d),
                    status=SYNC_FAILED, detail=listname,
                ))
        return out

    # --- migration ---
    def migrate_to_v3(self) -> bool:
        """Migrate a legacy file's sync container to the v3 ``syncData`` shape.

        Config sections are left untouched; only sync metadata is normalised. The
        legacy ``controllerSynchronisationIssues`` block is preserved (we never drop
        unknown data). Returns True if a change was made.
        """
        if self.file_format_version >= CURRENT_FILE_FORMAT_VERSION and "syncData" in self.raw:
            return False
        states: dict[str, dict] = {}
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        for entry in self._legacy_sync_entries():
            if not entry.mac or not entry.section:
                continue
            states[f"{entry.mac}:{entry.section}"] = {
                "deviceMac": entry.mac,
                "dataType": entry.section,
                "status": entry.status,
                "lastSyncedStateHash": None,
                "lastReadStateHash": None,
                "lastSyncTimestamp": None,
                "lastReadTimestamp": None,
                "lastLocalEditTimestamp": now_ms,
            }
        self.raw["fileFormatVersion"] = CURRENT_FILE_FORMAT_VERSION
        self.raw.setdefault("syncData", {})
        self.raw["syncData"].update({
            "syncStates": states,
            "rollbackHistory": self.raw["syncData"].get("rollbackHistory", []),
            "syncQueue": self.raw["syncData"].get("syncQueue", []),
        })
        return True

    # --- persistence ---
    def to_json(self) -> str:
        """Serialise back to JSON (2-space indent, matching SpektraPlus's saves)."""
        return json.dumps(self.raw, indent=2, ensure_ascii=False)

    def save(self, path: str | None = None) -> str:
        dest = path or self.path
        if not dest:
            raise SpektraFileError("No path given to save the project to.")
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())
        self.path = dest
        return dest


# Trigger command that means "no action" (proto TriggerType.NO_COMMAND).
_NO_COMMAND = 254


def _is_configured(section: str, item: dict) -> bool:
    """Best-effort 'is this slot actually used?' test, so summaries count real
    config rather than empty/spare slots."""
    if not isinstance(item, dict):
        return False
    try:
        if section in ("sequences", "themes"):
            return bool(item.get("colours"))
        if section == "lists":
            return bool(item.get("totalStepCount") or item.get("steps"))
        if section == "schedules":
            return item.get("IsEnabled") is True
        if section == "logicActions":
            return item.get("isEnabled") is True
        if section == "burnIns":
            return item.get("enabled") is True
        if section == "inputs":
            for act in ("shortLowAction", "longHighAction"):
                cmd = item.get(act) or {}
                if cmd.get("commandtype", _NO_COMMAND) != _NO_COMMAND:
                    return True
            return False
    except Exception:  # noqa: BLE001 — summary must never crash on odd data
        return True
    return True  # sections without a cheap predicate: count as present


def _count(section: str, items: Any) -> tuple[int, int]:
    """Return (configured, total) for a section's array."""
    if not isinstance(items, list):
        return (0, 0)
    return (sum(1 for it in items if _is_configured(section, it)), len(items))


def summarize(project: SpektraProject) -> str:
    """Human-readable overview of a project: per-MAC section counts + sync state."""
    lines = [f'Project "{project.name}" (uid {project.uid or "?"}, '
             f'app {project.app_version or "?"}, format v{project.file_format_version}'
             f'{" [legacy]" if project.is_legacy else ""})',
             f"{len(project.macs)} eDIDIO(s)."]

    for mac, ed in project.iter_edidios():
        fw = ed.get("firmwareVersion", "?")
        lines.append(f"\neDIDIO {mac} (fw {fw}):")
        for section in DEVICE_SECTIONS:
            cfg, total = _count(section, ed.get(section))
            if total:
                lines.append(f"  - {section}: {cfg} configured / {total} slots")
        profiles = ed.get("profiles") or []
        if profiles:
            lines.append(f"  - profiles: {len(profiles)}")
            for i, prof in enumerate(profiles):
                bits = []
                for sub in PROFILE_SECTIONS:
                    cfg, total = _count(sub, prof.get(sub))
                    if total:
                        bits.append(f"{sub} {cfg}/{total}")
                if bits:
                    lines.append(f"      profile {i}: " + ", ".join(bits))

    sync = project.sync_entries()
    if sync:
        lines.append("\nSync state (pending/known):")
        for e in sync:
            note = f" - {e.detail}" if e.detail else ""
            lines.append(f"  - {e.mac} {e.section}: {e.status}{note}")
    else:
        lines.append("\nSync state: none recorded (in sync or not tracked).")
    return "\n".join(lines)


def load_spektra(path: str) -> SpektraProject:
    """Load a ``.spektra`` file from disk into a :class:`SpektraProject`."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError as err:
        raise SpektraFileError(f"File not found: {path}") from err
    except json.JSONDecodeError as err:
        raise SpektraFileError(f"Not valid JSON: {err}") from err
    return SpektraProject(raw=raw, path=path)


def loads_spektra(text: str) -> SpektraProject:
    """Parse a ``.spektra`` document from a string (used in tests)."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as err:
        raise SpektraFileError(f"Not valid JSON: {err}") from err
    return SpektraProject(raw=raw)
