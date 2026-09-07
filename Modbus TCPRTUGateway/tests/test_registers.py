"""Unit tests for register validation and value->intent translation."""

import pytest

from edidio_modbus.registers import (
    ConfigError,
    RegisterEntry,
    build_register_map,
    line_mask,
)


def test_line_mask():
    assert line_mask(1) == 0b0001
    assert line_mask(2) == 0b0010
    assert line_mask(4) == 0b1000


def test_dali_level_clamps():
    e = RegisterEntry({"register": 3, "action": "dali_level", "line": 1, "address": 5})
    assert e.intent(127) == {"kind": "dali_level", "line": 1, "address": 5, "level": 127}
    assert e.intent(999)["level"] == 254  # clamped
    assert e.intent(-4)["level"] == 0


def test_group_level():
    e = RegisterEntry({"register": 1, "action": "dali_group_level", "line": 2, "group": 0})
    assert e.intent(200) == {"kind": "dali_group_level", "line": 2, "group": 0, "level": 200}


def test_onoff_maps_to_level():
    e = RegisterEntry({"register": 4, "action": "dali_onoff", "line": 1, "address": 7})
    assert e.intent(0)["level"] == 0
    assert e.intent(1)["level"] == 254
    assert e.intent(55)["level"] == 254


def test_group_onoff():
    e = RegisterEntry({"register": 4, "action": "dali_group_onoff", "line": 1, "group": 2})
    assert e.intent(0) == {"kind": "dali_group_level", "line": 1, "group": 2, "level": 0}
    assert e.intent(9)["level"] == 254


def test_scene_broadcast_and_group():
    broadcast = RegisterEntry({"register": 2, "action": "dali_scene", "line": 1})
    assert broadcast.intent(3) == {"kind": "dali_scene", "line": 1, "scene": 3}
    assert broadcast.intent(99) is None  # out of scene range

    ongroup = RegisterEntry({"register": 11, "action": "dali_scene", "line": 1, "group": 4})
    assert ongroup.intent(3) == {"kind": "dali_scene", "line": 1, "scene": 3, "group": 4}


def test_dali_command():
    e = RegisterEntry({"register": 5, "action": "dali_command", "line": 1, "address": 0})
    assert e.intent(5) == {"kind": "dali_command", "line": 1, "address": 0, "command": 5}
    assert e.intent(300) is None


def test_spektra_sequence_start_and_stop():
    e = RegisterEntry({"register": 10, "action": "spektra_sequence", "zone": 1})
    assert e.intent(0) == {"kind": "spektra_stop", "zone": 1}
    assert e.intent(1) == {
        "kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 0, "action": "START",
    }
    assert e.intent(5)["index"] == 4


def test_spektra_theme_and_static_types():
    theme = RegisterEntry({"register": 12, "action": "spektra_theme", "zone": 2})
    assert theme.intent(2)["type"] == "THEME"
    static = RegisterEntry({"register": 13, "action": "spektra_static", "zone": 2})
    assert static.intent(2)["type"] == "STATIC"


# --- validation errors ---

def test_unknown_action():
    with pytest.raises(ConfigError):
        RegisterEntry({"register": 1, "action": "teleport", "line": 1})


def test_missing_required_field():
    with pytest.raises(ConfigError):
        RegisterEntry({"register": 1, "action": "dali_level", "line": 1})  # no address


def test_out_of_range_field():
    with pytest.raises(ConfigError):
        RegisterEntry({"register": 1, "action": "dali_level", "line": 9, "address": 0})


def test_duplicate_register_rejected():
    with pytest.raises(ConfigError):
        build_register_map([
            {"register": 1, "action": "dali_scene", "line": 1},
            {"register": 1, "action": "dali_scene", "line": 2},
        ])


def test_empty_map_rejected():
    with pytest.raises(ConfigError):
        build_register_map([])
