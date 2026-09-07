"""Bridge routing tests with a fake dispatcher + publisher (no broker, no device).

Simulates inbound MQTT messages and asserts the correct intents are dispatched
and the correct optimistic state is published — the full command path minus the
broker and controller.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_mqtt.bridge import Bridge  # noqa: E402
from edidio_mqtt.config import BridgeConfig  # noqa: E402


class FakeDispatcher:
    def __init__(self):
        self.intents = []

    def submit(self, intent):
        self.intents.append(intent)


RAW = {
    "mqtt": {"base_topic": "edidio", "discovery": True, "discovery_prefix": "homeassistant"},
    "controller": {"id": "edidio1", "host": "10.0.0.1", "port": 23},
    "entities": [
        {"id": "kitchen", "name": "Kitchen", "type": "light", "line": 1, "address": 5},
        {"id": "living", "name": "Living", "type": "light", "line": 1, "group": 0},
        {"id": "movie", "name": "Movie", "type": "scene", "line": 1, "scene": 3},
    ],
}


def make():
    config = BridgeConfig(RAW)
    disp = FakeDispatcher()
    published = []
    bridge = Bridge(config, disp, publisher=lambda t, p, r: published.append((t, p, r)))
    return bridge, disp, published


def test_subscriptions_cover_all_command_topics():
    bridge, _, _ = make()
    subs = set(bridge.subscriptions())
    assert "edidio/kitchen/set" in subs
    assert "edidio/kitchen/brightness/set" in subs
    assert "edidio/living/set" in subs
    assert "edidio/movie/set" in subs


def test_discovery_messages_are_retained_json():
    bridge, _, _ = make()
    msgs = bridge.discovery_messages()
    topics = [t for (t, _p, _r) in msgs]
    assert "homeassistant/light/edidio_edidio1/kitchen/config" in topics
    assert "homeassistant/scene/edidio_edidio1/movie/config" in topics
    assert all(retain is True for (_t, _p, retain) in msgs)
    # payloads are JSON strings
    import json
    for _t, payload, _r in msgs:
        json.loads(payload)


def test_light_on_dispatches_and_publishes_state():
    bridge, disp, published = make()
    bridge.handle_message("edidio/kitchen/set", "ON")
    assert disp.intents[-1] == {"kind": "dali_level", "line": 1, "address": 5, "level": 254}
    assert ("edidio/kitchen/state", "ON", True) in published


def test_brightness_dispatches_level():
    bridge, disp, published = make()
    bridge.handle_message("edidio/kitchen/brightness/set", "100")
    assert disp.intents[-1] == {"kind": "dali_level", "line": 1, "address": 5, "level": 100}
    assert ("edidio/kitchen/brightness", "100", True) in published


def test_group_light():
    bridge, disp, _ = make()
    bridge.handle_message("edidio/living/set", "ON")
    assert disp.intents[-1] == {"kind": "dali_group_level", "line": 1, "group": 0, "level": 254}


def test_scene_trigger():
    bridge, disp, _ = make()
    bridge.handle_message("edidio/movie/set", "ON")
    assert disp.intents[-1] == {"kind": "dali_scene", "line": 1, "scene": 3}


def test_unmapped_topic_ignored():
    bridge, disp, published = make()
    bridge.handle_message("edidio/nope/set", "ON")
    assert disp.intents == []
    assert published == []


def test_bad_payload_does_not_raise():
    bridge, disp, _ = make()
    # non-numeric brightness -> coerced to 0, no exception
    bridge.handle_message("edidio/kitchen/brightness/set", "banana")
    assert disp.intents[-1]["level"] == 0
