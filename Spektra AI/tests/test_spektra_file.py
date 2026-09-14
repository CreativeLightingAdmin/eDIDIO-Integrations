"""Tests for loading/saving/summarising .spektra project files."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_spektra_ai.spektra_file import (  # noqa: E402
    CURRENT_FILE_FORMAT_VERSION, SpektraProject, load_spektra, loads_spektra, summarize,
)
from tests._projects import MAC1, MAC2, make_legacy, make_v3  # noqa: E402


def test_load_legacy_detects_version_and_sync():
    p = SpektraProject(raw=make_legacy())
    assert p.is_legacy and p.file_format_version == 1
    assert p.macs == [MAC1]
    entries = p.sync_entries()
    assert len(entries) == 1
    assert entries[0].section == "inputs" and entries[0].status == "UNSYNCED"


def test_load_v3_reads_syncdata():
    p = SpektraProject(raw=make_v3())
    assert not p.is_legacy and p.file_format_version == 3
    entries = p.sync_entries()
    assert len(entries) == 1
    assert entries[0].mac == MAC1 and entries[0].status == "UNSYNCED"


def test_multi_edidio():
    p = SpektraProject(raw=make_legacy(macs=(MAC1, MAC2)))
    assert set(p.macs) == {MAC1, MAC2}
    assert dict(p.iter_edidios())[MAC2]["firmwareVersion"] == "1.0.86"


def test_summarize_mentions_project_and_sections():
    text = summarize(SpektraProject(raw=make_legacy()))
    assert "Fixture Legacy" in text
    assert MAC1 in text and "sequences" in text and "profiles" in text
    assert "UNSYNCED" in text


def test_roundtrip_preserves_unknown_fields(tmp_path):
    src = tmp_path / "p.spektra"
    src.write_text(json.dumps(make_legacy()), encoding="utf-8")
    p = load_spektra(str(src))
    out = tmp_path / "out.spektra"
    p.save(str(out))
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    # widgetPages is not modelled but must survive the round-trip untouched.
    assert reloaded["widgetPages"] == [{"id": "w1", "name": "Page"}]


def test_migrate_to_v3_from_legacy():
    p = SpektraProject(raw=make_legacy())
    changed = p.migrate_to_v3()
    assert changed
    assert p.raw["fileFormatVersion"] == CURRENT_FILE_FORMAT_VERSION
    states = p.raw["syncData"]["syncStates"]
    assert f"{MAC1}:inputs" in states
    assert states[f"{MAC1}:inputs"]["status"] == "UNSYNCED"
    # legacy block is preserved (we never drop data)
    assert "controllerSynchronisationIssues" in p.raw


def test_migrate_v3_noop():
    p = SpektraProject(raw=make_v3())
    assert p.migrate_to_v3() is False


def test_loads_from_string():
    p = loads_spektra(json.dumps(make_v3()))
    assert p.name == "Fixture V3"
