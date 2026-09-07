"""Unit tests for the ambient mappings (value -> intent)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_ambient.mappings import (  # noqa: E402
    ConfigError,
    build_mapping,
    gradient_rgb,
)


# --- gradient interpolation ---

def test_gradient_endpoints():
    colors = [[0, 255, 0], [255, 0, 0]]  # green -> red
    assert gradient_rgb(0, 0, 100, colors) == [0, 255, 0]
    assert gradient_rgb(100, 0, 100, colors) == [255, 0, 0]


def test_gradient_midpoint():
    colors = [[0, 0, 0], [255, 255, 255]]
    assert gradient_rgb(50, 0, 100, colors) == [128, 128, 128]  # round(127.5)


def test_gradient_multi_stop():
    colors = [[0, 255, 0], [255, 255, 0], [255, 0, 0]]  # green->yellow->red
    assert gradient_rgb(0, 0, 100, colors) == [0, 255, 0]
    assert gradient_rgb(50, 0, 100, colors) == [255, 255, 0]  # exactly the yellow stop
    assert gradient_rgb(100, 0, 100, colors) == [255, 0, 0]


def test_gradient_clamps():
    colors = [[0, 255, 0], [255, 0, 0]]
    assert gradient_rgb(-50, 0, 100, colors) == [0, 255, 0]
    assert gradient_rgb(999, 0, 100, colors) == [255, 0, 0]


def test_gradient_mapping_intent():
    m = build_mapping({"type": "gradient", "line": 2, "min": -3, "max": 3,
                       "colors": ["#FF0000", "#FFFF00", "#00FF00"]})
    # value 0 (neutral) -> middle = yellow
    assert m.intent(0) == {"kind": "dmx_color", "line": 2, "rgb": [255, 255, 0]}
    # value +3 (up) -> green
    assert m.intent(3) == {"kind": "dmx_color", "line": 2, "rgb": [0, 255, 0]}
    # value -3 (down) -> red
    assert m.intent(-3) == {"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]}


def test_gradient_non_numeric_value():
    m = build_mapping({"type": "gradient", "line": 1, "min": 0, "max": 1, "colors": ["#000000"]})
    assert m.intent("not a number") is None


# --- threshold ---

def test_threshold_bands():
    m = build_mapping({"type": "threshold", "bands": [
        {"min": 0, "action": {"kind": "dali_scene", "line": 1, "scene": 1}},
        {"min": 20, "action": {"kind": "dali_scene", "line": 1, "scene": 2}},
        {"min": 50, "action": {"kind": "dali_scene", "line": 1, "scene": 3}},
    ]})
    assert m.intent(5)["scene"] == 1
    assert m.intent(20)["scene"] == 2   # boundary inclusive
    assert m.intent(35)["scene"] == 2
    assert m.intent(80)["scene"] == 3


def test_threshold_below_all_returns_none():
    m = build_mapping({"type": "threshold", "bands": [
        {"min": 10, "action": {"kind": "dali_scene", "line": 1, "scene": 1}},
    ]})
    assert m.intent(5) is None


# --- level ---

def test_level_group():
    m = build_mapping({"type": "level", "line": 1, "group": 0, "min": 0, "max": 100})
    assert m.intent(0) == {"kind": "dali_group_level", "line": 1, "group": 0, "level": 0}
    assert m.intent(100) == {"kind": "dali_group_level", "line": 1, "group": 0, "level": 254}
    assert m.intent(50)["level"] == 127


def test_level_invert():
    m = build_mapping({"type": "level", "line": 1, "address": 5, "min": 0, "max": 100, "invert": True})
    assert m.intent(0)["level"] == 254
    assert m.intent(100)["level"] == 0


# --- validation ---

def test_unknown_type():
    with pytest.raises(ConfigError):
        build_mapping({"type": "nope"})


def test_gradient_bad_color():
    with pytest.raises(ConfigError):
        build_mapping({"type": "gradient", "line": 1, "min": 0, "max": 1, "colors": ["nope"]})


def test_level_requires_one_target():
    with pytest.raises(ConfigError):
        build_mapping({"type": "level", "line": 1, "min": 0, "max": 1})
    with pytest.raises(ConfigError):
        build_mapping({"type": "level", "line": 1, "address": 5, "group": 0, "min": 0, "max": 1})


def test_threshold_bad_action():
    with pytest.raises(ConfigError):
        build_mapping({"type": "threshold", "bands": [{"min": 0, "action": {"kind": "teleport"}}]})
