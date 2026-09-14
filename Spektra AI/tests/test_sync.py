"""Tests for the hash-based sync pipeline and v3 syncData ledger."""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_spektra_ai import sync  # noqa: E402
from edidio_spektra_ai.spektra_file import SpektraProject  # noqa: E402
from tests._projects import MAC1, make_v3  # noqa: E402


def test_hash_stable_and_key_order_independent():
    a = {"b": 1, "a": 2, "c": {"y": 1, "x": 2}}
    b = {"a": 2, "c": {"x": 2, "y": 1}, "b": 1}
    assert sync._hash(a) == sync._hash(b)


def test_js_integral_float_equals_int():
    assert sync._hash({"v": 1.0}) == sync._hash({"v": 1})
    assert sync._hash({"v": 0.5}) != sync._hash({"v": 1})


def test_channel_trailing_zeros_ignored():
    short = [{"index": 0, "colours": [{"channelValues": [255, 0, 0]}]}]
    padded = [{"index": 0, "colours": [{"channelValues": [255, 0, 0, 0, 0, 0]}]}]
    assert sync.hash_section(short, "themes") == sync.hash_section(padded, "themes")


def test_title_empty_defaults_to_indexed_name():
    empty = [{"index": 0, "colours": [], "name": ""}]
    named = [{"index": 0, "colours": [], "name": "Theme 1"}]
    assert sync.hash_section(empty, "themes") == sync.hash_section(named, "themes")


def test_zone_scale_factor_out_of_range_clamps():
    a = [{"index": 0, "scaleFactor": 1.0}]
    b = [{"index": 0, "scaleFactor": 5}]      # out of range -> clamped to 1
    assert sync.hash_section(a, "zones") == sync.hash_section(b, "zones")


def test_index_order_independent():
    fwd = [{"index": 0, "colours": []}, {"index": 1, "colours": []}]
    rev = [{"index": 1, "colours": []}, {"index": 0, "colours": []}]
    assert sync.hash_section(fwd, "sequences") == sync.hash_section(rev, "sequences")


def test_transient_fields_ignored():
    a = [{"index": 0, "colours": [], "error": None, "uuid": "x"}]
    b = [{"index": 0, "colours": [], "error": "boom", "uuid": "y"}]
    assert sync.hash_section(a, "themes") == sync.hash_section(b, "themes")


def test_section_value_profile_based_is_2d():
    ed = {"profiles": [{"inputs": [{"index": 0}]}, {"inputs": [{"index": 1}]}]}
    assert sync.section_value(ed, "inputs") == [[{"index": 0}], [{"index": 1}]]
    ed2 = {"sequences": [{"index": 0}]}
    assert sync.section_value(ed2, "sequences") == [{"index": 0}]


def _live_from(project):
    return copy.deepcopy(project.raw["edidios"])


def test_compute_status_synced_then_unsynced():
    proj = SpektraProject(raw=make_v3())
    live = _live_from(proj)
    rows = {r["section"]: r["status"] for r in sync.compute_status(proj, live)}
    assert rows["themes"] == sync.SYNCED and rows["sequences"] == sync.SYNCED

    proj.edidio(MAC1)["themes"][0]["colours"][0]["channelValues"] = [1, 2, 3]
    rows = {r["section"]: r["status"] for r in sync.compute_status(proj, live)}
    assert rows["themes"] == sync.UNSYNCED


def test_mark_synced_writes_ledger_and_clears_status():
    proj = SpektraProject(raw=make_v3())
    live = _live_from(proj)
    proj.edidio(MAC1)["themes"][0]["colours"][0]["channelValues"] = [9, 9, 9]
    # simulate a push: device now matches file -> update live + mark synced
    live[MAC1]["themes"][0]["colours"][0]["channelValues"] = [9, 9, 9]
    sync.mark_synced(proj, MAC1, ["themes"])
    key = f"{MAC1}:themes"
    assert proj.raw["syncData"]["syncStates"][key]["status"] == sync.SYNCED
    rows = {r["section"]: r["status"] for r in sync.compute_status(proj, live)}
    assert rows["themes"] == sync.SYNCED


def test_desynced_when_both_moved_off_baseline():
    proj = SpektraProject(raw=make_v3())
    live = _live_from(proj)
    sync.mark_synced(proj, MAC1, ["themes"])          # baseline = current
    # device changes out-of-band AND file changes differently
    live[MAC1]["themes"][0]["colours"][0]["channelValues"] = [1, 1, 1]
    proj.edidio(MAC1)["themes"][0]["colours"][0]["channelValues"] = [2, 2, 2]
    rows = {r["section"]: r["status"] for r in sync.compute_status(proj, live)}
    assert rows["themes"] == sync.DESYNCED


def test_desynced_when_device_only_changed():
    proj = SpektraProject(raw=make_v3())
    live = _live_from(proj)
    sync.mark_synced(proj, MAC1, ["themes"])          # baseline = current
    # only the device changed; the file is still at the last-synced baseline
    live[MAC1]["themes"][0]["colours"][0]["channelValues"] = [7, 7, 7]
    rows = {r["section"]: r["status"] for r in sync.compute_status(proj, live)}
    assert rows["themes"] == sync.DESYNCED


def test_unsynced_when_local_only_changed_from_baseline():
    proj = SpektraProject(raw=make_v3())
    live = _live_from(proj)
    sync.mark_synced(proj, MAC1, ["themes"])          # baseline = current (== live)
    proj.edidio(MAC1)["themes"][0]["colours"][0]["channelValues"] = [3, 3, 3]
    rows = {r["section"]: r["status"] for r in sync.compute_status(proj, live)}
    assert rows["themes"] == sync.UNSYNCED
