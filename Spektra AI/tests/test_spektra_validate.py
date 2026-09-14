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
    assert any(i.level == WARNING and "exceeds 28 chars" in i.message for i in issues)
    # at least some errors present
    assert any(i.level == ERROR for i in issues)


def test_format_reports_counts():
    text = format_issues(validate(SpektraProject(raw=make_bad())))
    assert "error(s)" in text and "warning(s)" in text
