"""Tests for the event-log parser and stuck-on diagnosis."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_spektra_ai.event_log import (  # noqa: E402
    analyze_stuck_on, parse_log, summarize_log,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_log.txt")


def _events():
    with open(FIXTURE, encoding="utf-8") as fh:
        return parse_log(fh.read())


def test_parse_counts_and_types():
    events = _events()
    # 5 records: 1 UserStart + 4 Triggers (header line ignored)
    assert len(events) == 5
    types = {e.event_type for e in events}
    assert "UserStart" in types and "Trigger" in types


def test_details_parsed_into_fields():
    events = _events()
    arcs = [e for e in events if e.action == "DALI Arc"]
    assert len(arcs) == 3
    first = arcs[0]
    assert first.source == "INPUTS"
    assert first.fields == {"line": 1, "group": 0, "value": 254}


def test_start_list_details():
    events = _events()
    starts = [e for e in events if e.action == "Start List"]
    assert starts and starts[0].fields.get("list") == 4
    assert starts[0].fields.get("line") is None


def test_summarize_reports_sources():
    text = summarize_log(_events())
    assert "INPUTS" in text and "LIST" in text
    assert "events" in text


def test_analyze_stuck_on_flags_unmatched_on():
    report = analyze_stuck_on(_events())
    # Line 1 group 0 was set to 254 and never turned off -> stuck.
    assert "Line 1 group 0" in report
    # Line 2 group 1 went on (254) then off (0) -> not stuck.
    assert "Line 2 group 1" not in report
    assert "1 of 2" in report  # 1 stuck of 2 targets


def test_analyze_no_output_events():
    events = parse_log("12:00:01 2026-01-01:\n   [UserStart]\n   { 'Logging Level': '3' }\n")
    assert "nothing to analyse" in analyze_stuck_on(events)
