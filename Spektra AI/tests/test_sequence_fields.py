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
    assert "`blend` does not use time_per_colour_ms" in preview


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


@pytest.mark.parametrize("ms,value,unit", [
    (65535, 65535, 0),            # still fits as milliseconds
    (70000, 70, 1),               # bench: 70000 ms was refused by 1.6.3 (16-bit field)
    (120000, 120, 1),             # 2 min step
    (300000, 300, 1),             # 5 min colour
    (90 * 60_000, 5400, 1),       # 90 min still fits in seconds
    (24 * 3_600_000, 1440, 2),    # 24 h -> minutes
])
def test_long_times_pick_a_unit_that_fits(ms, value, unit):
    raw, preview = seq(time_per_step_ms=ms, time_per_colour_ms=ms)
    assert (raw.time_per_step, raw.time_per_step_unit) == (value, unit)
    assert (raw.time_per_colour, raw.time_per_colour_unit) == (value, unit)
    assert "16-bit" not in preview                  # exact: nothing was rounded


def test_long_time_that_must_round_says_so():
    raw, preview = seq(time_per_step_ms=70_400)
    assert (raw.time_per_step, raw.time_per_step_unit) == (70, 1)
    assert "becomes 70 s = 70000ms" in preview


def test_time_beyond_the_largest_unit_rejected():
    with pytest.raises(SpecError):
        seq(time_per_step_ms=70_000 * 3_600_000)


def test_fade_to_black_is_flagged_as_blend():
    """Bench: fade_to_black dips no lower than blend; the firmware has no fade-to-black."""
    raw, preview = seq(type="blend", transition="fade_to_black", fade_ms=1000)
    assert raw.transition == 2
    assert "not implemented" in preview


def test_random_colour_order_is_written():
    raw, preview = seq(type="blend", random_colour_order=True)
    assert raw.has_random_colour_order is True
    assert "random colour order" in preview and "NOTE" not in preview


def test_random_colour_order_noted_for_types_that_ignore_it():
    _, preview = seq(type="rotate", random_colour_order=True)
    assert "does not use random colour order" in preview


def test_random_types_list_sets_the_mask():
    raw, preview = seq(random_types=["simple_chase", "rotate", "radial_build"])
    assert raw.is_randomised_type == 1
    assert raw.random_types_mask == (1 << 1) | (1 << 4) | (1 << 14)    # 0x4012, as the bench
    assert "random type from simple_chase, rotate, radial_build, changing every 1 minute" in preview


def test_random_types_any_is_an_empty_mask():
    raw, preview = seq(random_types="any", time_per_step_ms=2000)
    assert raw.is_randomised_type == 1 and raw.random_types_mask == 0
    assert "any type" in preview


def test_random_type_period_follows_the_step_unit():
    _, preview = seq(random_types="any", time_per_step_ms=120_000)     # stored in seconds
    assert "changing every 10 minutes" in preview


def test_random_pool_decides_the_unused_field_notes():
    """Blend ignores range, but a random pool that includes a chase uses it."""
    _, preview = seq(type="blend", range=4, random_types=["blend", "simple_chase"])
    assert "range" in preview and "NOTE" not in preview
    _, preview = seq(type="blend", range=4, random_types=["blend", "rotate"])
    assert "none of the random types use range" in preview


def test_comet_tail_goes_in_args_3_with_the_background():
    raw, preview = seq(type="comet", comet_tail=6, background=[0, 0, 20])
    assert list(raw.args)[:5] == [0, 0, 20, 6, 0]
    assert "comet tail 6" in preview and "NOTE" not in preview
    raw, _ = seq(type="comet", comet_tail=5)
    assert list(raw.args)[:4] == [0, 0, 0, 5]


def test_comet_tail_noted_for_other_types():
    _, preview = seq(type="blend", comet_tail=4)
    assert "comet_tail (comet only)" in preview


@pytest.mark.parametrize("bad", [{"comet_tail": 0}, {"comet_tail": 255},
                                 {"random_types": ["nope"]}, {"random_types": "chase"},
                                 {"reverse": True, "cycle": True}])
def test_bad_new_fields_rejected(bad):
    with pytest.raises(SpecError):
        seq(**bad)


def test_direction_noted_for_types_that_ignore_it():
    _, preview = seq(type="twinkle", cycle=True)
    assert "does not use direction" in preview


def test_every_property_survives_read_then_write():
    raw, _ = seq(type="comet", title="All", range=6, background=[1, 2, 3], comet_tail=7,
                 cycle=True, random_colour_order=True, random_types=["comet", "fire"],
                 transition="snap", fade_ms=300, time_per_step_ms=90_000,
                 time_per_colour_ms=4000)
    back = decode(M.sequence_to_message(M.sequence_to_dict(raw), 1, False))
    for f in FIELDS + ("has_random_colour_order", "is_randomised_type", "random_types_mask"):
        assert getattr(back, f) == getattr(raw, f), f
    assert list(back.args)[:4] == list(raw.args)[:4] == [1, 2, 3, 7]


def test_list_line_shows_random_settings():
    line = _sequence_line({"index": 1, "title": "R", "type": 0, "colours": 4, "time_per_step": 400,
                           "time_per_step_unit": 0, "time_per_colour": 0, "time_per_colour_unit": 0,
                           "fade_ms": 0, "range": 0, "direction": "", "random_colour_order": True,
                           "random_types": 0x4012})
    assert line.endswith("random colour order, random type from simple_chase, rotate, radial_build")
