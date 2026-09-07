"""Tests for the CS2 GSI -> lighting mapper, using recorded-style payloads."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_cs2.mapper import Cs2Mapper, gradient_rgb  # noqa: E402


def payload(health=100, flashed=0, bomb=None, phase="live"):
    return {
        "player": {"state": {"health": health, "flashed": flashed}, "activity": "playing"},
        "round": {"phase": phase, "bomb": bomb},
    }


def test_health_gradient_colour():
    m = Cs2Mapper({"health": {"line": 2, "colors": ["#FF0000", "#00FF00"]}})
    out = m.process(payload(health=100))
    assert out == [{"kind": "dmx_color", "line": 2, "rgb": [0, 255, 0]}]  # full health = green
    out = m.process(payload(health=0, flashed=0))
    assert out == [{"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]}]  # dead-ish = red


def test_health_only_emits_on_change():
    m = Cs2Mapper({"health": {"line": 2, "colors": ["#FF0000", "#00FF00"]}})
    m.process(payload(health=100))
    # same health again -> no new intent
    assert m.process(payload(health=100)) == []


def test_flashbang_rising_edge():
    m = Cs2Mapper({"flash": {"line": 2, "threshold": 100, "color": "#FFFFFF"}})
    assert m.process(payload(flashed=0)) != []      # (health colour on first payload)
    out = m.process(payload(flashed=200))           # flashed! -> white
    assert {"kind": "dmx_color", "line": 2, "rgb": [255, 255, 255]} in out
    # still flashed -> no repeat white
    out2 = m.process(payload(flashed=180))
    assert {"kind": "dmx_color", "line": 2, "rgb": [255, 255, 255]} not in out2


def test_bomb_planted_fires_once():
    m = Cs2Mapper({"bomb": {"action": {"kind": "dali_scene", "line": 1, "scene": 5}}})
    m.process(payload(bomb=None))
    out = m.process(payload(bomb="planted"))
    assert {"kind": "dali_scene", "line": 1, "scene": 5} in out
    # still planted -> no repeat
    assert {"kind": "dali_scene", "line": 1, "scene": 5} not in m.process(payload(bomb="planted"))


def test_death_action():
    m = Cs2Mapper({
        "health": {"enabled": False},
        "death": {"enabled": True, "action": {"kind": "dali_scene", "line": 1, "scene": 0}},
    })
    m.process(payload(health=40))
    out = m.process(payload(health=0))
    assert out == [{"kind": "dali_scene", "line": 1, "scene": 0}]


def test_missing_fields_are_safe():
    m = Cs2Mapper({})
    # empty / partial payloads must not raise
    assert isinstance(m.process({}), list)
    assert isinstance(m.process({"player": {}}), list)


def test_gradient_helper():
    assert gradient_rgb(0, [[255, 0, 0], [0, 255, 0]]) == [255, 0, 0]
    assert gradient_rgb(1, [[255, 0, 0], [0, 255, 0]]) == [0, 255, 0]


def test_flash_takes_priority_over_health_same_payload():
    m = Cs2Mapper({
        "health": {"line": 2, "colors": ["#FF0000", "#00FF00"]},
        "flash": {"line": 2, "threshold": 100, "color": "#FFFFFF"},
    })
    m.process(payload(health=100, flashed=0))
    out = m.process(payload(health=100, flashed=200))
    # only the white flash fires this payload (health colour suppressed)
    assert out == [{"kind": "dmx_color", "line": 2, "rgb": [255, 255, 255]}]
