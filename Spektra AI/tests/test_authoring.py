"""Tests for the pure authoring compiler (spec -> messages + preview)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb  # noqa: E402
from edidio_control_py import EdidioClient, TriggerType  # noqa: E402

from edidio_spektra_ai.authoring import (  # noqa: E402
    SpecError,
    compile_schedule,
    compile_sequence,
    compile_theme,
)


def decode(frame):
    assert frame[0] == 0xCD
    msg = pb.EdidioMessage()
    msg.ParseFromString(frame[3:])
    return msg


# --- sequences ---

def test_rotate_rgb_sequence():
    spec = {"index": 5, "type": "rotate", "title": "RYG Rotate",
            "colours": [[255, 0, 0], [255, 255, 0], [0, 255, 0]], "time_per_step_ms": 500}
    messages, preview = compile_sequence(spec)
    assert len(messages) == 1
    seq = decode(messages[0]).spektra_sequence
    assert seq.index == 5
    assert seq.type == 4  # ROTATE
    assert [list(c.channel_value) for c in seq.colours] == [[255, 0, 0], [255, 255, 0], [0, 255, 0]]
    assert seq.time_per_step == 500
    assert "rotate" in preview and "Sequence 5" in preview


def test_sequence_step_below_minimum_rejected():
    with pytest.raises(SpecError):
        compile_sequence({"index": 0, "type": "rotate", "colours": [[0, 0, 0]], "time_per_step_ms": 10})


def test_sequence_bad_index():
    with pytest.raises(SpecError):
        compile_sequence({"index": 200, "type": "rotate", "colours": [[0, 0, 0]]})


def test_sequence_bad_colour():
    with pytest.raises(SpecError):
        compile_sequence({"index": 0, "colours": [[300, 0, 0]]})
    with pytest.raises(SpecError):
        compile_sequence({"index": 0, "colours": [[255, 0, 0], [0, 0]]})  # inconsistent channels


def test_sequence_unknown_type():
    with pytest.raises(SpecError):
        compile_sequence({"index": 0, "type": "disco", "colours": [[0, 0, 0]]})


# --- themes ---

def test_theme():
    messages, preview = compile_theme({"index": 2, "title": "Ocean", "colours": [[0, 60, 120], [0, 120, 160]]})
    theme = decode(messages[0]).spektra_theme
    assert theme.index == 2
    assert theme.title == "Ocean"
    assert "Theme 2" in preview


# --- schedules ---

def test_schedule_5pm_daily_targeting_existing_sequence():
    spec = {"index": 2, "time": "17:00", "repeat": "daily",
            "trigger": {"type": "start_sequence", "zone": 1, "target_index": 5}}
    messages, preview = compile_schedule(spec)
    assert len(messages) == 1
    alarm = decode(messages[0]).alarm
    assert alarm.index == 2
    assert alarm.start_time.time == EdidioClient.pack_time(17, 0, 0)
    assert alarm.start_trigger.type == TriggerType.SPEKTRA_START_SEQ
    assert alarm.start_trigger.target_index == 5
    assert alarm.start_trigger.zone == 1
    # daily must fill BOTH bitmasks (all 7 days, all 12 months) or the app shows "Once"
    assert alarm.repeat_day_bitmask == 0x7F
    assert alarm.repeat_month_bitmask == 0xFFF
    assert "17:00" in preview and "daily" in preview


def test_schedule_calendar_event_and_month_selection():
    # "Start Calendar Event" trigger + only some months
    spec = {"index": 0, "time": "17:00", "repeat": "daily", "zone": 0,
            "trigger": {"type": "start_calendar"}, "months": [9, 12]}
    alarm = decode(compile_schedule(spec)[0][0]).alarm
    assert alarm.start_trigger.type == TriggerType.SPEKTRA_SCHEDULE
    assert alarm.repeat_month_bitmask == (1 << 8) | (1 << 11)  # Sep + Dec


def test_scheduled_inline_sequence_authors_then_targets():
    """'make a rotate and run it 5PM daily' -> 2 messages: save seq, then alarm."""
    spec = {"index": 0, "time": "17:00", "repeat": "daily", "zone": 1,
            "sequence": {"index": 7, "type": "rotate",
                         "colours": [[255, 0, 0], [255, 255, 0], [0, 255, 0]],
                         "title": "RYG", "time_per_step_ms": 500}}
    messages, preview = compile_schedule(spec)
    assert len(messages) == 2
    seq = decode(messages[0]).spektra_sequence
    alarm = decode(messages[1]).alarm
    assert seq.index == 7 and seq.type == 4
    assert alarm.start_trigger.type == TriggerType.SPEKTRA_START_SEQ
    assert alarm.start_trigger.target_index == 7   # targets the just-authored sequence
    assert alarm.start_trigger.zone == 1
    assert "Sequence 7" in preview and "Schedule 0" in preview


def test_schedule_sunset():
    spec = {"index": 1, "astro": "sunset", "repeat": "daily",
            "trigger": {"type": "theme", "zone": 0, "target_index": 1}}
    messages, preview = compile_schedule(spec)
    alarm = decode(messages[0]).alarm
    assert alarm.astro_start == 2  # ALARM_SUNSET
    assert alarm.start_trigger.type == TriggerType.SPEKTRA_THEME
    assert "sunset" in preview


def test_schedule_sunset_plus_one_hour():
    spec = {"index": 0, "astro": "sunset", "offset": "1:00", "repeat": "daily",
            "trigger": {"type": "start_calendar", "zone": 0}}
    messages, preview = compile_schedule(spec)
    alarm = decode(messages[0]).alarm
    assert alarm.astro_start == 2  # ALARM_SUNSET
    assert alarm.start_time.time == EdidioClient.pack_time(1, 0, 0)  # 1h offset amount
    assert alarm.start_offset_is_before is False
    assert "sunset +01:00" in preview


def test_schedule_sunrise_minus_30_before():
    spec = {"index": 1, "astro": "sunrise", "offset": "-0:30", "repeat": "daily",
            "trigger": {"type": "start_calendar", "zone": 0}}
    alarm = decode(compile_schedule(spec)[0][0]).alarm
    assert alarm.start_time.time == EdidioClient.pack_time(0, 30, 0)
    assert alarm.start_offset_is_before is True


def test_schedule_workday_with_days():
    spec = {"index": 3, "time": "08:30", "repeat": "workday",
            "trigger": {"type": "start_sequence", "target_index": 2}}
    messages, _ = compile_schedule(spec)
    alarm = decode(messages[0]).alarm
    assert alarm.repeat == 2  # WORK_DAY


def test_schedule_needs_time_or_astro():
    with pytest.raises(SpecError):
        compile_schedule({"index": 0, "trigger": {"type": "start_sequence", "target_index": 1}})


def test_schedule_bad_time():
    with pytest.raises(SpecError):
        compile_schedule({"index": 0, "time": "25:99", "trigger": {"type": "start_sequence", "target_index": 1}})
