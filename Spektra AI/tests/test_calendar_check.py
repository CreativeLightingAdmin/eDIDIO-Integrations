"""Calendar check: dates -> slots (leap years), names, mismatch ranges."""

from datetime import date

import pytest

from edidio_spektra_ai import calendar_check as cc

NAMES = {"sequence": {0: "Default", 3: "Christmas Lights"}, "theme": {1: "Warm White"}}


def test_slots_follow_the_year():
    assert cc.slot(date(2026, 3, 1)) == 59 and cc.slot(date(2028, 3, 1)) == 60
    assert len(cc.expand_dates("12-30..01-02", 2026)) == 4       # wraps the new year
    assert cc.expand_dates(["12-25", "2026-12-24"], 2026)[0] == date(2026, 12, 24)


def test_compare_reports_mismatch_ranges_and_names():
    xmas = [cc.slot(d) for d in cc.expand_dates("12-01..12-26", 2026)]
    actual = [{"day_index": s, "kind": "sequence", "target_index": 3} for s in xmas[:-2]]
    actual.append({"day_index": xmas[-2], "kind": "theme", "target_index": 1})
    actual.append({"day_index": 0, "kind": "sequence", "target_index": 0})
    res = cc.compare(actual, [{"dates": "12-01..12-26", "sequence": "christmas"}],
                     NAMES, 2026, strict=True)
    text = cc.format_report(res, 2026)
    assert "2 of 26 day(s) differ" in text
    assert "25 Dec: theme 2 'Warm White'" in text and "26 Dec: nothing" in text
    assert "01 Jan: sequence 1 'Default'" in text                  # strict extra


def test_unknown_name_is_an_error():
    with pytest.raises(ValueError):
        cc.compare([], [{"dates": "01-01", "sequence": "Nope"}], NAMES, 2026)
