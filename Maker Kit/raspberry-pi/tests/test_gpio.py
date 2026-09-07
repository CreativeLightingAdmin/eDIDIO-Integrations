"""Tests for the Raspberry Pi GPIO pin map and controller execute (no Pi, no
eDIDIO). gpiozero is never imported here — the mapping and controller are pure /
injectable."""

import asyncio
import os
import sys

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_gpio import ConfigError, Controller, PinBinding, build_pin_map, line_mask  # noqa: E402


def test_line_mask():
    assert line_mask(1) == 1
    assert line_mask(4) == 8


def test_scene_binding():
    b = PinBinding({"pin": 17, "action": "scene", "line": 1, "scene": 1})
    assert b.intent() == {"kind": "dali_scene", "line": 1, "scene": 1}


def test_on_off_binding():
    on = PinBinding({"pin": 22, "action": "on", "line": 1, "address": 5})
    assert on.intent() == {"kind": "dali_command", "line": 1, "address": 5, "command": "on"}
    off = PinBinding({"pin": 23, "action": "off", "line": 1, "address": 5})
    assert off.intent()["command"] == "off"


def test_group_level_binding():
    b = PinBinding({"pin": 23, "action": "group_level", "line": 1, "group": 2, "level": 254})
    assert b.intent() == {"kind": "dali_group_level", "line": 1, "group": 2, "level": 254}


def test_spektra_binding():
    b = PinBinding({"pin": 24, "action": "spektra", "zone": 1, "index": 0})
    assert b.intent() == {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 0, "action": "START"}


def test_validation():
    with pytest.raises(ConfigError):
        PinBinding({"pin": 17, "action": "nope"})
    with pytest.raises(ConfigError):
        PinBinding({"pin": 17, "action": "scene", "line": 9, "scene": 1})
    with pytest.raises(ConfigError):
        build_pin_map([
            {"pin": 17, "action": "scene", "line": 1, "scene": 1},
            {"pin": 17, "action": "scene", "line": 1, "scene": 2},
        ])


def test_example_config_parses_and_on_is_string():
    """Guard the YAML `on` boolean gotcha: action must be the string 'on'."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.example.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    pin_map = build_pin_map(raw["pins"])
    on_binding = pin_map[22]
    assert on_binding.action == "on"  # not the boolean True


# --- controller execute with a fake client ---

class FakeClient:
    def __init__(self):
        self.calls = []
        self.connected = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    def __getattr__(self, name):
        async def method(*args, **kwargs):
            self.calls.append((name, args))
        return method


def test_controller_execute_scene():
    fake = FakeClient()
    ctrl = Controller("10.0.0.1", client=fake)
    asyncio.run(ctrl.execute({"kind": "dali_scene", "line": 1, "scene": 3}))
    assert fake.calls[-1][0] == "recall_dali_scene"


def test_controller_execute_group_level():
    fake = FakeClient()
    ctrl = Controller("10.0.0.1", client=fake)
    asyncio.run(ctrl.execute({"kind": "dali_group_level", "line": 1, "group": 2, "level": 254}))
    name, args = fake.calls[-1]
    assert name == "set_dali_group_arc_level"
    assert args[1:] == (line_mask(1), 2, 254)


def test_controller_execute_on_command():
    fake = FakeClient()
    ctrl = Controller("10.0.0.1", client=fake)
    asyncio.run(ctrl.execute({"kind": "dali_command", "line": 1, "address": 5, "command": "on"}))
    assert fake.calls[-1][0] == "send_dali_command"
