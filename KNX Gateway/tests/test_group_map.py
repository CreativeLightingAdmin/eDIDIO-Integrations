"""Unit tests for the KNX group-address map (value -> intent)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_knx.group_map import ConfigError, GroupTarget, build_group_map  # noqa: E402


def test_scaling_to_level():
    t = GroupTarget({"ga": "1/1/1", "action": "dali_level", "dpt": "scaling", "line": 1, "dali_address": 5})
    assert t.intent(255) == {"kind": "dali_level", "line": 1, "address": 5, "level": 254}
    assert t.intent(0)["level"] == 0
    assert t.intent(128)["level"] == 127  # round(128*254/255)


def test_switch_level():
    t = GroupTarget({"ga": "1/1/2", "action": "dali_level", "dpt": "switch", "line": 1, "dali_address": 5})
    assert t.intent(1)["level"] == 254
    assert t.intent(0)["level"] == 0


def test_group_scaling():
    t = GroupTarget({"ga": "2/1/1", "action": "dali_group_level", "dpt": "scaling", "line": 1, "group": 0})
    assert t.intent(255) == {"kind": "dali_group_level", "line": 1, "group": 0, "level": 254}


def test_scene_switch_trigger():
    t = GroupTarget({"ga": "3/1/1", "action": "dali_scene", "dpt": "switch", "line": 1, "scene": 3})
    assert t.intent(1) == {"kind": "dali_scene", "line": 1, "scene": 3}
    assert t.intent(0) is None  # off on a trigger GA is ignored


def test_scene_switch_on_group():
    t = GroupTarget({"ga": "3/1/2", "action": "dali_scene", "dpt": "switch", "line": 1, "scene": 2, "group": 4})
    assert t.intent(1) == {"kind": "dali_scene", "line": 1, "scene": 2, "group": 4}


def test_scene_number_from_telegram():
    t = GroupTarget({"ga": "3/2/1", "action": "dali_scene", "dpt": "scene_number", "line": 1})
    assert t.intent(3) == {"kind": "dali_scene", "line": 1, "scene": 3}
    assert t.intent(99) is None  # out of eDIDIO scene range -> ignored


# --- validation ---

def test_invalid_ga():
    with pytest.raises(ConfigError):
        GroupTarget({"ga": "not-a-ga", "action": "dali_scene", "dpt": "switch", "line": 1, "scene": 1})


def test_ga_out_of_range():
    # middle group max is 7 in KNX 3-level addressing
    with pytest.raises(ConfigError):
        GroupTarget({"ga": "9/9/9", "action": "dali_scene", "dpt": "switch", "line": 1, "scene": 1})


def test_bad_dpt_for_action():
    with pytest.raises(ConfigError):
        GroupTarget({"ga": "1/1/1", "action": "dali_scene", "dpt": "scaling", "line": 1})


def test_switch_scene_requires_fixed_scene():
    with pytest.raises(ConfigError):
        GroupTarget({"ga": "1/1/1", "action": "dali_scene", "dpt": "switch", "line": 1})  # no scene


def test_level_requires_address():
    with pytest.raises(ConfigError):
        GroupTarget({"ga": "1/1/1", "action": "dali_level", "dpt": "scaling", "line": 1})  # no dali_address


def test_duplicate_ga_rejected():
    with pytest.raises(ConfigError):
        build_group_map([
            {"ga": "1/1/1", "action": "dali_scene", "dpt": "switch", "line": 1, "scene": 1},
            {"ga": "1/1/1", "action": "dali_scene", "dpt": "switch", "line": 1, "scene": 2},
        ])


def test_empty_map_rejected():
    with pytest.raises(ConfigError):
        build_group_map([])
