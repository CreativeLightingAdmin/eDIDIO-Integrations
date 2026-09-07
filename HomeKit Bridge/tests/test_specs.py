"""Unit tests for accessory specs (config -> intents)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_homekit.specs import (  # noqa: E402
    ConfigError,
    LightSpec,
    SceneSpec,
    build_specs,
    pct_to_arc,
)


def test_pct_to_arc():
    assert pct_to_arc(100) == 254
    assert pct_to_arc(0) == 0
    assert pct_to_arc(50) == 127
    assert pct_to_arc(200) == 254  # clamped


def test_light_address_intent():
    s = LightSpec({"id": "k", "type": "light", "line": 1, "address": 5})
    assert s.level_intent(254) == {"kind": "dali_level", "line": 1, "address": 5, "level": 254}
    assert s.level_intent(999)["level"] == 254  # clamped


def test_light_group_intent():
    s = LightSpec({"id": "living", "type": "light", "line": 1, "group": 0})
    assert s.level_intent(127) == {"kind": "dali_group_level", "line": 1, "group": 0, "level": 127}


def test_scene_intent():
    s = SceneSpec({"id": "movie", "type": "scene", "line": 1, "scene": 3})
    assert s.intent() == {"kind": "dali_scene", "line": 1, "scene": 3}


def test_scene_on_group():
    s = SceneSpec({"id": "w", "type": "scene", "line": 1, "scene": 1, "group": 4})
    assert s.intent() == {"kind": "dali_scene", "line": 1, "scene": 1, "group": 4}


def test_light_requires_one_target():
    with pytest.raises(ConfigError):
        LightSpec({"id": "x", "type": "light", "line": 1})
    with pytest.raises(ConfigError):
        LightSpec({"id": "x", "type": "light", "line": 1, "address": 5, "group": 0})


def test_unknown_type():
    with pytest.raises(ConfigError):
        build_specs([{"id": "x", "type": "thermostat", "line": 1}])


def test_duplicate_id():
    with pytest.raises(ConfigError):
        build_specs([
            {"id": "a", "type": "scene", "line": 1, "scene": 1},
            {"id": "a", "type": "scene", "line": 1, "scene": 2},
        ])


def test_out_of_range():
    with pytest.raises(ConfigError):
        LightSpec({"id": "x", "type": "light", "line": 9, "address": 5})
