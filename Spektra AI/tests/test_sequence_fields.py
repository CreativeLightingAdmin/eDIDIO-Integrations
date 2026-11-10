"""Sequence fields that the bench suite found wrong: time units on read-back, the fade
rule, the default colour time, range/background, and the list_sequences text."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb  # noqa: E402

from edidio_spektra_ai import spektra_map as M  # noqa: E402
from edidio_spektra_ai.authoring import SpecError, compile_sequence  # noqa: E402
from edidio_spektra_ai.server import _sequence_line  # noqa: E402


def decode(frame):
    msg = pb.EdidioMessage()
    msg.ParseFromString(frame[3:])
    return msg.spektra_sequence


def seq(**kw):
    spec = {"index": 3, "type": "simple_chase", "colours": [[255, 0, 0], [0, 0, 255]],
            "time_per_step_ms": 1000}
    spec.update(kw)
    frames, preview = compile_sequence(spec)
    return decode(frames[0]), preview


FIELDS = ("type", "time_per_step", "time_per_step_unit", "time_per_colour",
          "time_per_colour_unit", "fade_time_by_10ms", "transition", "range", "title",
          "is_reverse_direction", "is_cycle_direction")


@pytest.mark.parametrize("unit", [0, 1, 2, 3])
def test_read_then_write_keeps_every_raw_field(unit):
    """A pull (sequence_to_dict) then push (sequence_to_message) must not change the
    stored sequence. `unit or 1` turned milliseconds into seconds (1000x slower), and
    hours read as seconds."""
    # Titled: an empty title reads back as "Sequence n", as in SpektraPlus.
    raw, _ = seq(range=6, background=[0, 0, 40], reverse=True, title="Units")
    raw.time_per_step_unit = unit
    raw.time_per_colour_unit = unit
    back = decode(M.sequence_to_message(M.sequence_to_dict(raw), 1, False))
    assert {f: getattr(back, f) for f in FIELDS} == {f: getattr(raw, f) for f in FIELDS}
    assert [list(c.channel_value) for c in back.colours] == [list(c.channel_value) for c in raw.colours]
    assert list(back.args)[:3] == list(raw.args)[:3]


def test_milliseconds_read_as_milliseconds():
    raw, _ = seq()
    d = M.sequence_to_dict(raw)
    assert d["timePerStepUnit"] == 0 and d["timePerColourUnit"] == 0


def test_fade_longer_than_step_is_allowed_and_described():
    """The firmware adds the fade to the step (measured: 1000 ms step + 500 ms fade =
    a 1500 ms cycle), so a fade is not limited to the step time."""
    raw, preview = seq(type="blend", fade_ms=1500)
    assert raw.fade_time_by_10ms == 150
    assert "each step lasts 2500ms (step + fade)" in preview


def test_default_colour_time_is_two_seconds():
    """0 would be stored as the firmware's 50 ms minimum: a chase flickering colours."""
    raw, preview = seq()
    assert raw.time_per_colour == 2000 and raw.time_per_colour_unit == 0
    assert "each colour 2000ms" in preview


def test_colour_time_below_minimum_rejected():
    with pytest.raises(SpecError):
        seq(time_per_colour_ms=10)


def test_colour_time_noted_as_unused_for_step_types():
    _, preview = seq(type="blend", time_per_colour_ms=5000)
    assert "has no effect" in preview


def test_range_and_background_are_written():
    raw, preview = seq(type="radial_build", range=24, background=[10, 20, 30])
    assert raw.range == 24
    assert list(raw.args)[:4] == [10, 20, 30, 0]     # args[3] (comet tail) stays default
    assert "range 24 lights" in preview and "background [10, 20, 30]" in preview


@pytest.mark.parametrize("bad", [{"range": -1}, {"range": 513}, {"background": [1, 2, 3, 4]},
                                 {"background": [255, 0, 0]}, {"background": "red"}])
def test_bad_range_or_background_rejected(bad):
    with pytest.raises(SpecError):
        seq(**bad)


def test_range_noted_as_unused_for_blend():
    _, preview = seq(type="blend", range=4)
    assert "does not use range" in preview


def test_list_line_names_the_type_and_timing():
    line = _sequence_line({"index": 35, "title": "Chase", "type": 1, "colours": 3,
                           "time_per_step": 1000, "time_per_step_unit": 0,
                           "time_per_colour": 2, "time_per_colour_unit": 1,
                           "fade_ms": 500, "range": 12, "direction": "reverse"})
    assert line == ("- [35] Chase - simple_chase, 3 colour(s), step 1 s + 500 ms fade, "
                    "colour 2 s, range 12, reverse")
    blend = _sequence_line({"index": 0, "title": "", "type": 0, "colours": 2,
                            "time_per_step": 2, "time_per_step_unit": 1, "time_per_colour": 50,
                            "time_per_colour_unit": 0, "fade_ms": 0, "range": 0, "direction": ""})
    assert blend == "- [0] (untitled) - blend, 2 colour(s), step 2 s"
