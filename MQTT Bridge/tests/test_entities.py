"""Unit tests for entity topics, HA discovery configs, and payload->intent."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_mqtt.entities import (  # noqa: E402
    BridgeContext,
    ConfigError,
    LightEntity,
    SceneEntity,
    build_entities,
)

CTX = BridgeContext("edidio", "homeassistant", "edidio1")


# --- light (address) ---

def test_light_address_topics():
    e = LightEntity({"id": "kitchen", "name": "Kitchen", "type": "light", "line": 1, "address": 5})
    assert set(e.command_topics(CTX)) == {"edidio/kitchen/set", "edidio/kitchen/brightness/set"}


def test_light_discovery_config():
    e = LightEntity({"id": "kitchen", "name": "Kitchen", "type": "light", "line": 1, "address": 5})
    topic, cfg = e.discovery(CTX)
    assert topic == "homeassistant/light/edidio_edidio1/kitchen/config"
    assert cfg["command_topic"] == "edidio/kitchen/set"
    assert cfg["brightness_command_topic"] == "edidio/kitchen/brightness/set"
    assert cfg["brightness_scale"] == 254
    assert cfg["unique_id"] == "edidio_edidio1_kitchen"
    assert cfg["availability_topic"] == "edidio/availability"
    assert cfg["device"]["identifiers"] == ["edidio_edidio1"]


def test_light_on_off():
    e = LightEntity({"id": "k", "type": "light", "line": 1, "address": 5})
    intent, states = e.handle("edidio/k/set", "ON", CTX)
    assert intent == {"kind": "dali_level", "line": 1, "address": 5, "level": 254}
    assert ("edidio/k/state", "ON", True) in states

    intent, states = e.handle("edidio/k/set", "OFF", CTX)
    assert intent["level"] == 0
    assert ("edidio/k/state", "OFF", True) in states


def test_light_brightness():
    e = LightEntity({"id": "k", "type": "light", "line": 1, "address": 5})
    intent, states = e.handle("edidio/k/brightness/set", "128", CTX)
    assert intent == {"kind": "dali_level", "line": 1, "address": 5, "level": 128}
    assert ("edidio/k/brightness", "128", True) in states
    assert ("edidio/k/state", "ON", True) in states


def test_light_brightness_zero_is_off_state():
    e = LightEntity({"id": "k", "type": "light", "line": 1, "address": 5})
    _, states = e.handle("edidio/k/brightness/set", "0", CTX)
    assert ("edidio/k/state", "OFF", True) in states


def test_light_brightness_clamps():
    e = LightEntity({"id": "k", "type": "light", "line": 1, "address": 5})
    intent, _ = e.handle("edidio/k/brightness/set", "999", CTX)
    assert intent["level"] == 254


# --- light (group) ---

def test_light_group_intent():
    e = LightEntity({"id": "living", "type": "light", "line": 1, "group": 0})
    intent, _ = e.handle("edidio/living/set", "ON", CTX)
    assert intent == {"kind": "dali_group_level", "line": 1, "group": 0, "level": 254}


# --- scene ---

def test_scene_discovery_and_trigger():
    e = SceneEntity({"id": "movie", "name": "Movie", "type": "scene", "line": 1, "scene": 3})
    topic, cfg = e.discovery(CTX)
    assert topic == "homeassistant/scene/edidio_edidio1/movie/config"
    assert cfg["command_topic"] == "edidio/movie/set"
    intent, states = e.handle("edidio/movie/set", "ON", CTX)
    assert intent == {"kind": "dali_scene", "line": 1, "scene": 3}
    assert states == []


def test_scene_on_group():
    e = SceneEntity({"id": "w", "type": "scene", "line": 1, "group": 4, "scene": 1})
    intent, _ = e.handle("edidio/w/set", "ON", CTX)
    assert intent == {"kind": "dali_scene", "line": 1, "scene": 1, "group": 4}


# --- validation ---

def test_light_requires_exactly_one_target():
    with pytest.raises(ConfigError):
        LightEntity({"id": "x", "type": "light", "line": 1})  # neither
    with pytest.raises(ConfigError):
        LightEntity({"id": "x", "type": "light", "line": 1, "address": 5, "group": 0})  # both


def test_unknown_type_rejected():
    with pytest.raises(ConfigError):
        build_entities([{"id": "x", "type": "fan", "line": 1}])


def test_duplicate_id_rejected():
    with pytest.raises(ConfigError):
        build_entities([
            {"id": "a", "type": "scene", "line": 1, "scene": 1},
            {"id": "a", "type": "scene", "line": 1, "scene": 2},
        ])


def test_out_of_range_rejected():
    with pytest.raises(ConfigError):
        LightEntity({"id": "x", "type": "light", "line": 9, "address": 5})
