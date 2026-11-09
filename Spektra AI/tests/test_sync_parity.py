"""Byte-parity of sync.hash_section with SpektraPlus's own sync hash.

fixtures/hash_golden_spektraplus.json was produced by running the real TypeScript
sync hash over these inputs (SpektraPlus v1.3.0, 2026-11-09). Covers the
1.3.0 canonicalisers: fade time in ms, 23/27-byte UTF-8 titles, NO_COMMAND zeroing,
zone scale clamp, DMX start clamp, sensor grouping defaults, transient stripping.
Regenerate when SpektraPlus changes its hash pipeline.
"""

import json
from pathlib import Path

import pytest

from edidio_spektra_ai import sync

_GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "hash_golden_spektraplus.json")
                     .read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _GOLDEN, ids=[c["type"] for c in _GOLDEN])
def test_hash_matches_spektraplus(case):
    assert sync.hash_section(case["data"], case["type"]) == case["hash"]


def test_title_truncation_is_utf8_bytes():
    assert sync.device_sequence_title("Asthma and Allergy Awareness") == "Asthma and Allergy Awar"
    assert sync.device_theme_title("Greater Western Sydney Giants") == "Greater Western Sydney Gian"
    assert sync.truncate_utf8("Café au lait", 4) == "Caf"


def test_fade_unit_does_not_change_hash():
    a = [{"index": 0, "name": "A", "fadeTime": 1, "fadeTimeUnit": 1}]
    b = [{"index": 0, "name": "A", "fadeTime": 1000, "fadeTimeUnit": 0}]
    assert sync.hash_section(a, "sequences") == sync.hash_section(b, "sequences")


def test_mark_synced_drops_stale_item_baselines():
    from edidio_spektra_ai.spektra_file import SpektraProject
    mac = "40:D8:55:00:00:01"
    raw = {"edidios": {mac: {"sequences": [], "profiles": []}},
           "syncData": {"syncStates": {}, "itemSyncStates": {
               f"{mac}:sequences:0": {"status": "SYNCED"},
               f"{mac}:themes:0": {"status": "SYNCED"}}}}
    sync.mark_synced(SpektraProject(raw=raw), mac, ["sequences"])
    assert list(raw["syncData"]["itemSyncStates"]) == [f"{mac}:themes:0"]
