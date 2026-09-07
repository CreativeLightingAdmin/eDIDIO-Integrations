"""Tests for the scheduling logic (next-alarm computation, calendar parse)."""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_control_py import EdidioClient  # noqa: E402

from edidio_spektra_ai.scheduling import (  # noqa: E402
    describe_alarm,
    next_fire,
    next_scheduled,
    parse_calendar_overview,
    unpack_time,
)


def alarm(**kw):
    base = {"index": 0, "enabled": True, "start_time": EdidioClient.pack_time(17, 0, 0),
            "repeat": 1, "repeat_day_bitmask": 0, "trigger_type": 12, "target_index": 5, "zone": 1}
    base.update(kw)
    return base


def test_unpack_time_roundtrip():
    assert unpack_time(EdidioClient.pack_time(17, 30, 15)) == (17, 30, 15)


def test_next_fire_daily_later_today():
    now = datetime(2026, 1, 5, 12, 0, 0)  # noon, alarm at 17:00
    nf = next_fire(alarm(repeat=1), now)
    assert nf == datetime(2026, 1, 5, 17, 0, 0)


def test_next_fire_daily_tomorrow_if_passed():
    now = datetime(2026, 1, 5, 18, 0, 0)  # already past 17:00
    nf = next_fire(alarm(repeat=1), now)
    assert nf == datetime(2026, 1, 6, 17, 0, 0)


def test_next_fire_weekdays_skips_weekend():
    # 2026-01-03 is a Saturday; a weekdays alarm should jump to Monday the 5th.
    now = datetime(2026, 1, 3, 8, 0, 0)
    nf = next_fire(alarm(repeat=2), now)
    assert nf.weekday() == 0  # Monday
    assert nf == datetime(2026, 1, 5, 17, 0, 0)


def test_next_fire_weekly_bitmask():
    # weekly, only Wednesday (bit 2). From Monday 2026-01-05 -> Wed 2026-01-07.
    now = datetime(2026, 1, 5, 8, 0, 0)
    nf = next_fire(alarm(repeat=3, repeat_day_bitmask=1 << 2), now)
    assert nf == datetime(2026, 1, 7, 17, 0, 0)


def test_next_fire_once_future_only():
    now = datetime(2026, 1, 5, 12, 0, 0)
    assert next_fire(alarm(repeat=0), now) == datetime(2026, 1, 5, 17, 0, 0)
    # if the one-shot time already passed today, it's gone
    assert next_fire(alarm(repeat=0), datetime(2026, 1, 5, 18, 0, 0)) is None


def test_disabled_and_astro_return_none():
    now = datetime(2026, 1, 5, 12, 0, 0)
    assert next_fire(alarm(enabled=False), now) is None
    assert next_fire(alarm(astro_start=2), now) is None  # sunset


def test_next_scheduled_picks_soonest():
    now = datetime(2026, 1, 5, 12, 0, 0)
    a1 = alarm(index=0, start_time=EdidioClient.pack_time(17, 0), target_index=5)
    a2 = alarm(index=1, start_time=EdidioClient.pack_time(14, 0), target_index=9)
    result = next_scheduled([a1, a2], now)
    assert result["alarm"]["index"] == 1   # 14:00 is sooner
    assert result["when"] == datetime(2026, 1, 5, 14, 0, 0)
    assert result["in"] == "2h"
    assert "sequence 9" in result["description"]


def test_next_scheduled_empty():
    assert next_scheduled([], datetime(2026, 1, 5, 12, 0)) is None
    assert next_scheduled([alarm(enabled=False)], datetime(2026, 1, 5, 12, 0)) is None


def test_describe_alarm():
    d = describe_alarm(alarm(trigger_type=14, target_index=2, zone=0))
    assert "17:00 daily" in d and "theme 2" in d


def test_parse_calendar_overview():
    overview = {"day_offset": 0, "days": [
        {"day_index": 0, "type": 1, "target_index": 5},
        {"day_index": 1, "type": 2, "target_index": 3},
    ]}
    out = parse_calendar_overview(overview)
    assert out == [
        {"day_index": 0, "kind": "sequence", "target_index": 5},
        {"day_index": 1, "kind": "theme", "target_index": 3},
    ]
