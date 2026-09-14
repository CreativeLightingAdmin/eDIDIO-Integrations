"""Tests for the .spektra structural diff."""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_spektra_ai.spektra_diff import ADDED, CHANGED, REMOVED, diff, format_diff  # noqa: E402
from edidio_spektra_ai.spektra_file import SpektraProject  # noqa: E402
from tests._projects import MAC1, make_legacy  # noqa: E402


def test_self_diff_is_empty():
    p = SpektraProject(raw=make_legacy())
    assert diff(p, p) == []
    assert "No differences" in format_diff(diff(p, p))


def test_changed_field_detected():
    a = SpektraProject(raw=make_legacy())
    b = SpektraProject(raw=copy.deepcopy(a.raw))
    b.edidio(MAC1)["themes"][0]["name"] = "New Name"
    entries = diff(a, b)
    assert any(e.change == CHANGED and e.section == "themes" and "name" in e.detail
               for e in entries)


def test_added_and_removed_items():
    a = SpektraProject(raw=make_legacy())
    b = SpektraProject(raw=copy.deepcopy(a.raw))
    b.edidio(MAC1)["sequences"].append({"name": "Seq2", "index": 1,
                                        "colours": [{"channelValues": [0, 0, 255]}]})
    entries = diff(a, b)
    assert any(e.change == ADDED and e.section == "sequences" and e.index == 1
               for e in entries)
    # reverse direction => removed
    entries_rev = diff(b, a)
    assert any(e.change == REMOVED and e.section == "sequences" and e.index == 1
               for e in entries_rev)


def test_transient_fields_ignored():
    a = SpektraProject(raw=make_legacy())
    b = SpektraProject(raw=copy.deepcopy(a.raw))
    b.edidio(MAC1)["profiles"][0]["inputs"][0]["error"] = "some transient error"
    assert diff(a, b) == []  # 'error' is transient, not a real change
