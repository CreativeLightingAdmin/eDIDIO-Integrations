"""Tests for the Dota 2 GSI -> lighting mapper."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_dota2.mapper import Dota2Mapper  # noqa: E402


def payload(health=100, alive=True, daytime=True):
    return {"hero": {"health_percent": health, "alive": alive}, "map": {"daytime": daytime}}


def test_health_gradient():
    m = Dota2Mapper({"health": {"line": 2, "colors": ["#FF0000", "#00FF00"]}})
    assert m.process(payload(health=100)) == [{"kind": "dmx_color", "line": 2, "rgb": [0, 255, 0]}]
    assert m.process(payload(health=0)) == [{"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]}]


def test_health_only_on_change():
    m = Dota2Mapper({"health": {"line": 2, "colors": ["#FF0000", "#00FF00"]}})
    m.process(payload(health=50))
    assert m.process(payload(health=50)) == []


def test_death_and_respawn_edges():
    m = Dota2Mapper({
        "health": {"enabled": False},
        "death": {"action": {"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]}},
        "respawn": {"action": {"kind": "dmx_color", "line": 2, "rgb": [0, 255, 0]}},
    })
    m.process(payload(alive=True))              # prime
    out = m.process(payload(health=0, alive=False))
    assert out == [{"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]}]
    # still dead -> no repeat
    assert m.process(payload(health=0, alive=False)) == []
    # respawn
    out = m.process(payload(health=100, alive=True))
    assert {"kind": "dmx_color", "line": 2, "rgb": [0, 255, 0]} in out


def test_daynight():
    m = Dota2Mapper({
        "health": {"enabled": False},
        "daynight": {"enabled": True,
                     "day_action": {"kind": "dali_scene", "line": 1, "scene": 1},
                     "night_action": {"kind": "dali_scene", "line": 1, "scene": 2}},
    })
    m.process(payload(daytime=True))            # prime
    assert m.process(payload(daytime=False)) == [{"kind": "dali_scene", "line": 1, "scene": 2}]
    assert m.process(payload(daytime=True)) == [{"kind": "dali_scene", "line": 1, "scene": 1}]


def test_missing_fields_safe():
    m = Dota2Mapper({})
    assert isinstance(m.process({}), list)
    assert isinstance(m.process({"hero": {}}), list)


def test_dead_hero_no_health_colour():
    m = Dota2Mapper({"health": {"line": 2, "colors": ["#FF0000", "#00FF00"]}})
    # dead hero: no health colour emitted
    assert m.process(payload(health=0, alive=False)) == []
