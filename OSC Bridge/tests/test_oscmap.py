"""Unit tests for the OSC address map (address + args -> intent)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_osc.oscmap import (  # noqa: E402
    ConfigError,
    OSCTarget,
    build_address_map,
    level_from_arg,
)


def test_level_from_arg_float_normalized():
    assert level_from_arg(1.0) == 254
    assert level_from_arg(0.0) == 0
    assert level_from_arg(0.5) == 127


def test_level_from_arg_int_raw():
    assert level_from_arg(200) == 200
    assert level_from_arg(999) == 254  # clamped


def test_dali_level_target():
    t = OSCTarget({"address": "/k/level", "action": "dali_level", "line": 1, "address_dali": 5})
    assert t.intent((0.5,)) == {"kind": "dali_level", "line": 1, "address": 5, "level": 127}


def test_group_level_target():
    t = OSCTarget({"address": "/g/level", "action": "dali_group_level", "line": 1, "group": 0})
    assert t.intent((1.0,)) == {"kind": "dali_group_level", "line": 1, "group": 0, "level": 254}


def test_scene_trigger_and_release():
    t = OSCTarget({"address": "/scene/m", "action": "dali_scene", "line": 1, "scene": 3})
    assert t.intent((1,)) == {"kind": "dali_scene", "line": 1, "scene": 3}
    assert t.intent(()) == {"kind": "dali_scene", "line": 1, "scene": 3}  # bang / no args
    assert t.intent((0,)) is None  # button release does not fire


def test_scene_on_group():
    t = OSCTarget({"address": "/scene/w", "action": "dali_scene", "line": 1, "scene": 1, "group": 4})
    assert t.intent((1,)) == {"kind": "dali_scene", "line": 1, "scene": 1, "group": 4}


def test_spektra_target():
    t = OSCTarget({
        "address": "/seq/start", "action": "spektra", "zone": 1,
        "type": "sequence", "index": 2, "spektra_action": "start",
    })
    assert t.intent((1,)) == {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 2, "action": "START"}
    assert t.intent((0,)) is None


def test_spektra_stop_target():
    t = OSCTarget({"address": "/seq/stop", "action": "spektra_stop", "zone": 1})
    assert t.intent((1,)) == {"kind": "spektra_stop", "zone": 1}


# --- validation ---

def test_invalid_address():
    with pytest.raises(ConfigError):
        OSCTarget({"address": "no-slash", "action": "dali_scene", "line": 1, "scene": 1})


def test_unknown_action():
    with pytest.raises(ConfigError):
        OSCTarget({"address": "/x", "action": "nope", "line": 1})


def test_dali_level_requires_address_dali():
    with pytest.raises(ConfigError):
        OSCTarget({"address": "/x", "action": "dali_level", "line": 1})


def test_duplicate_address():
    with pytest.raises(ConfigError):
        build_address_map([
            {"address": "/x", "action": "dali_scene", "line": 1, "scene": 1},
            {"address": "/x", "action": "dali_scene", "line": 1, "scene": 2},
        ])
