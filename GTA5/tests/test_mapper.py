"""Tests for the GTA V state -> lighting mapper."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_gta5.mapper import Gta5Mapper  # noqa: E402


def test_wanted_escalation_fires_on_change():
    m = Gta5Mapper({"health": {"enabled": False}, "wanted": {"actions": {
        0: {"kind": "dali_scene", "line": 1, "scene": 1},
        1: {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 0, "action": "START"},
        3: {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 1, "action": "START"},
    }}})
    # gain a star
    out = m.process({"wanted": 1})
    assert out == [{"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 0, "action": "START"}]
    # same level -> no repeat
    assert m.process({"wanted": 1}) == []
    # escalate to 3
    out = m.process({"wanted": 3})
    assert out[0]["index"] == 1
    # cleared -> scene 1
    assert m.process({"wanted": 0}) == [{"kind": "dali_scene", "line": 1, "scene": 1}]


def test_wanted_clamped():
    m = Gta5Mapper({"health": {"enabled": False}})
    out = m.process({"wanted": 5})   # default tier 5 exists
    assert out and out[0]["kind"] == "spektra"


def test_wanted_suppresses_health_colour():
    m = Gta5Mapper({"wanted": {"enabled": True},
                    "health": {"line": 2, "colors": ["#FF0000", "#00FF00"]}})
    # Under a wanted level, the siren action fires and the health colour is
    # suppressed (siren takes the room).
    out = m.process({"wanted": 2, "health": 50})
    assert out[0]["kind"] == "spektra"
    assert all(i["kind"] != "dmx_color" for i in out)


def test_health_gradient_when_calm():
    m = Gta5Mapper({"wanted": {"enabled": False},
                    "health": {"line": 2, "colors": ["#FF0000", "#00FF00"]}})
    assert m.process({"health": 100}) == [{"kind": "dmx_color", "line": 2, "rgb": [0, 255, 0]}]
    assert m.process({"health": 0}) == [{"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]}]


def test_events_wasted_busted():
    m = Gta5Mapper({"wanted": {"enabled": False}, "health": {"enabled": False},
                    "events": {"wasted": {"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]},
                               "busted": {"kind": "dmx_color", "line": 2, "rgb": [0, 0, 255]}}})
    assert m.process({"event": "wasted"}) == [{"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]}]
    # same event still set -> no repeat
    assert m.process({"event": "wasted"}) == []
    # cleared then busted
    m.process({"event": None})
    assert m.process({"event": "busted"}) == [{"kind": "dmx_color", "line": 2, "rgb": [0, 0, 255]}]


def test_missing_fields_safe():
    m = Gta5Mapper({})
    assert isinstance(m.process({}), list)
