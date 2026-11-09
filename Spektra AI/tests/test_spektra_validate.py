"""Tests for offline .spektra validation."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_spektra_ai.spektra_file import SpektraProject  # noqa: E402
from edidio_spektra_ai.spektra_validate import ERROR, WARNING, format_issues, validate  # noqa: E402
from tests._projects import make_bad, make_legacy  # noqa: E402


def test_clean_file_passes():
    issues = validate(SpektraProject(raw=make_legacy()))
    assert issues == []
    assert "passed" in format_issues(issues)


def test_bad_file_flags_expected_issues():
    issues = validate(SpektraProject(raw=make_bad()))
    msgs = [i.message for i in issues]
    # index out of range
    assert any("exceeds max 143" in m for m in msgs)
    # colour value out of range
    assert any("out of range" in m for m in msgs)
    # unknown command type
    assert any("unknown commandtype 9999" in m for m in msgs)
    # over-length title is a warning
    assert any(i.level == WARNING and "bytes; the controller keeps" in i.message
               for i in issues)
    # at least some errors present
    assert any(i.level == ERROR for i in issues)


def test_format_reports_counts():
    text = format_issues(validate(SpektraProject(raw=make_bad())))
    assert "error(s)" in text and "warning(s)" in text


def _one(section, item, profile=False, **raw):
    ed = {"profiles": [{section: [item]}]} if profile else {section: [item]}
    return validate(SpektraProject(raw={"edidios": {"40:D8:55:00:00:01": ed}, **raw}))


def test_firmware_163_limits():
    cmd = {"commandtype": 0, "zone": 0, "linemask": 1, "target": 300, "value": 0, "query": 0}
    msgs = [i.message for i in _one("inputs", {"index": 0, "type": 7, "shortLowAction": cmd},
                                    profile=True)]
    assert any("not a TriggerOperationType" in m for m in msgs)
    assert any("target = 300 does not fit" in m for m in msgs)
    seq = {"index": 0, "name": "Asthma and Allergy Awareness", "sequenceType": 16,
           "colours": [{"channelValues": [1]}]}
    msgs = [i.message for i in _one("sequences", seq)]
    assert any("28 bytes; the controller keeps 23" in m for m in msgs)
    assert any("sequenceType 16 unknown" in m for m in msgs)
    sch = {"index": 0, "IsEnabled": True, "repeat": 5,
           "startEvent": {"command": {"commandtype": 9}, "type": 0, "date": "2026-13-01",
                          "time": "07:61:00"}}
    msgs = [i.message for i in _one("schedules", sch)]
    assert any("repeat 5" in m for m in msgs) and any("date 2026-13-01" in m for m in msgs)
    assert any("07:61:00" in m for m in msgs)


def test_identity_and_old_logic_targets():
    raw = {"appVersion": "1.2.9", "edidios": {"40:D8:55:00:00:01": {
        "network": {"mac": "40:D8:55:1B:A2:99"},
        "logicActions": [{"index": 0, "isEnabled": True, "comparisonType": 2,
                          "comparisonObject": {"commandtype": 2, "target": 5}}]}}}
    msgs = [i.message for i in validate(SpektraProject(raw=raw))]
    assert any("network.mac" in m for m in msgs)
    assert any("one too high" in m for m in msgs)
