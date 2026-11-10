"""The sequence model against frames recorded from a real controller (1.6.3, DMX level
cache, 12 RGBW fixtures, colours R,G,B = 1,2,3, 1000 ms steps, snap, colour time 60 s).
If the firmware's engine changes, tools/sequence_bench.py shows where."""
import pytest

from edidio_spektra_ai.sequence_model import Sequence, caveats, render, simulate

N = 12


def frames(type_, steps=4, **kw):
    kw.setdefault("colours", 3)
    kw.setdefault("step_ms", 1000)
    kw.setdefault("colour_ms", 60000)
    return [f for _, f in simulate(Sequence(type=type_, **kw), N, steps)]


# --- recorded on the bench (first frames after play, the start-up frame first) ---

def test_simple_chase_starts_on_colour_2():
    assert frames(1) == ["." * 12, "2...........", ".2..........", "..2.........",
                         "...2........"]


def test_shadow_chase():
    assert frames(2, 2) == ["." * 12, ".22222222222", "2.2222222222"]


def test_comet_default_tail_of_3():
    assert frames(3, 3) == ["." * 12, "22.........2", "222.........", ".222........"]


def test_ramp_up_steps_through_the_colours():
    assert frames(10, 3)[1:] == ["1" * 12, "2" * 12, "3" * 12]


def test_static_repeats_the_palette():
    assert frames(12, 2)[1:] == ["123123123123"] * 2


def test_rotate():
    assert frames(4, 2)[1:] == ["132132132132", "213213213213"]


def test_radial_build_fills_from_both_ends():
    f = frames(14, 6)
    assert f[1] == "1..........1" and f[6] == "111111111111"


def test_radial_build_range_6_fills_each_repeat():
    """Each repeat builds from its own two ends."""
    f = frames(14, 3, range=6)
    assert f[1:] == ["1....11....1", "11..1111..11", "111111111111"]


def test_particle_cannon_builds_up():
    assert frames(15, 3)[1:] == ["2...........", "22..........", "222........."]


def test_reverse_simple_chase_counts_down():
    assert [f.index("2") for f in frames(1, 4, reverse=True)[1:]] == [0, 11, 10, 9]


def test_cycle_holds_each_end_for_two_steps():
    """Bench (400 ms steps): 0..11, 11 held, back to 0, 0 held."""
    f = frames(1, 26, colours=1, cycle=True)[1:]
    heads = [x.index("1") for x in f]
    assert heads[:13] == list(range(12)) + [11]
    assert heads[13:25] == list(range(10, -1, -1)) + [0]


def test_comet_tail_5():
    """Bench: comet_tail 5 lit exactly 5 fixtures."""
    f = frames(3, 6, colours=1, comet_tail=5)[1:]
    assert all(x.count("1") == 5 for x in f[4:])


def test_background_shows_as_b():
    f = frames(1, 2, range=4, background=[0, 0, 40])
    assert f[1] == "2bbb2bbb2bbb"


def test_colour_timer_moves_the_chase_colour():
    """Colour time 2 s with 1 s steps: the head colour changes every 2 steps."""
    heads = [x.strip(".")[0] for x in frames(1, 6, colour_ms=2000)[1:]]
    assert heads == ["2", "2", "3", "3", "1", "1"]


def test_fade_lengthens_every_step():
    times = [t for t, _ in simulate(Sequence(type=0, colours=3, step_ms=1000, fade_ms=1500), N, 3)]
    assert times == [0, 0, 2500, 5000]


# --- caveats and rendering ---

def test_caveats_explain_what_the_model_cannot_show():
    assert any("random" in c for c in caveats(Sequence(type=5, colours=2), N))
    assert any("colour 2" in c for c in caveats(Sequence(type=1, colours=3), N))
    assert any("two steps" in c for c in caveats(Sequence(type=1, colours=1, cycle=True), N))
    assert any("middle" in c for c in caveats(Sequence(type=14, colours=1, range=5), 10))


@pytest.mark.parametrize("fw,expect", [("1.6.3", True), ("1.5.7", True), ("1.7.0", False),
                                       ("", False)])
def test_radial_build_warns_on_1_6_3_and_earlier(fw, expect):
    notes = caveats(Sequence(type=14, colours=1, range=6), N, fw)
    assert any("first repeat's mirrored half" in c for c in notes) == expect


def test_render_has_a_row_per_step_and_a_legend():
    text = render(Sequence(type=1, colours=2, step_ms=500), 8, 4,
                  colours=[[255, 0, 0], [0, 0, 255]])
    rows = text.splitlines()
    assert rows[0] == "Dry run on 8 lights (one column per fixture):"
    assert rows[1].split() == ["start", "........"]
    assert rows[2].split() == ["0s", "2......."] and rows[3].split() == ["0.5s", ".2......"]
    assert "1 = [255, 0, 0], 2 = [0, 0, 255], . = off" in text


# --- the dry run in preview_sequence ---

def test_preview_sequence_dry_run_from_lights():
    import asyncio
    from edidio_spektra_ai import server as srv
    from tests.test_server import fresh_controller
    fresh_controller()
    out = asyncio.run(srv.preview_sequence({"index": 3, "type": "simple_chase", "lights": 6,
                                            "colours": [[255, 0, 0], [0, 0, 255]],
                                            "time_per_step_ms": 500}))
    assert "Dry run on 6 lights" in out and 'confirm(token="' in out
    assert out.index("Dry run") < out.index("Call confirm")


def test_preview_sequence_dry_run_from_the_zone():
    import asyncio
    from edidio_spektra_ai import server as srv
    from tests.test_server import fresh_controller
    fresh_controller()
    asyncio.run(srv.connect_controller("10.0.0.1"))       # the stub's zones have 10 lights
    out = asyncio.run(srv.preview_sequence({"index": 3, "type": "blend", "zone": 0,
                                            "colours": [[255, 0, 0], [0, 0, 255]]}))
    assert "Dry run on 10 lights" in out
    assert asyncio.run(srv.preview_sequence({"index": 3, "type": "blend",
                                             "colours": [[255, 0, 0]]})).count("Dry run") == 0
