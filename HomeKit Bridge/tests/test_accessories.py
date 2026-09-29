"""Accessory tests: build real HAP accessories with an offline driver and fire
HomeKit characteristic writes, asserting the correct eDIDIO intents. No pairing,
no mDNS, no controller.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyhap.accessory_driver import AccessoryDriver  # noqa: E402

from edidio_homekit.accessories import LightAccessory, SceneAccessory  # noqa: E402
from edidio_homekit.specs import LightSpec, SceneSpec  # noqa: E402


class FakeDispatcher:
    def __init__(self):
        self.intents = []

    def submit(self, intent):
        self.intents.append(intent)


@pytest.fixture
def driver():
    fd, path = tempfile.mkstemp(suffix=".state")
    os.close(fd)
    d = AccessoryDriver(port=51999, persist_file=path, pincode=b"031-45-154")
    yield d
    try:
        os.remove(path)
    except OSError:
        pass


def test_light_on_off(driver):
    disp = FakeDispatcher()
    acc = LightAccessory(driver, LightSpec({"id": "k", "type": "light", "line": 1, "address": 5}), disp)
    acc.char_on.client_update_value(True)
    assert disp.intents[-1] == {"kind": "dali_level", "line": 1, "address": 5, "level": 254}
    acc.char_on.client_update_value(False)
    assert disp.intents[-1]["level"] == 0


def test_light_brightness(driver):
    disp = FakeDispatcher()
    acc = LightAccessory(driver, LightSpec({"id": "k", "type": "light", "line": 1, "address": 5}), disp)
    acc.char_brightness.client_update_value(50)
    assert disp.intents[-1] == {"kind": "dali_level", "line": 1, "address": 5, "level": 127}


def test_light_on_restores_last_brightness(driver):
    disp = FakeDispatcher()
    acc = LightAccessory(driver, LightSpec({"id": "k", "type": "light", "line": 1, "address": 5}), disp)
    acc.char_brightness.client_update_value(40)   # sets last brightness = 40%
    acc.char_on.client_update_value(True)          # On should restore ~40%
    assert disp.intents[-1]["level"] == 102        # round(40*254/100)


def test_group_light(driver):
    disp = FakeDispatcher()
    acc = LightAccessory(driver, LightSpec({"id": "living", "type": "light", "line": 1, "group": 0}), disp)
    acc.char_on.client_update_value(True)
    assert disp.intents[-1] == {"kind": "dali_group_level", "line": 1, "group": 0, "level": 254}


def test_scene_switch(driver):
    disp = FakeDispatcher()
    acc = SceneAccessory(driver, SceneSpec({"id": "movie", "type": "scene", "line": 1, "scene": 3}), disp)
    acc.char_on.client_update_value(True)
    assert disp.intents[-1] == {"kind": "dali_scene", "line": 1, "scene": 3}
    # turning "off" (or the auto-reset) produces no command
    n = len(disp.intents)
    acc.char_on.client_update_value(False)
    assert len(disp.intents) == n


def test_scene_on_group(driver):
    disp = FakeDispatcher()
    acc = SceneAccessory(driver, SceneSpec({"id": "w", "type": "scene", "line": 1, "scene": 1, "group": 4}), disp)
    acc.char_on.client_update_value(True)
    assert disp.intents[-1] == {"kind": "dali_scene", "line": 1, "scene": 1, "group": 4}



# --- live state feedback ---

def test_apply_level_reflects_bus_state_without_sending(driver):
    disp = FakeDispatcher()
    acc = LightAccessory(driver, LightSpec({"id": "k", "type": "light", "line": 1, "address": 5}), disp)
    acc.apply_level(127)
    assert acc.char_on.value is True and acc.char_brightness.value == 50
    acc.apply_level(0)
    assert acc.char_on.value is False
    assert disp.intents == []                      # feedback never echoes a command
    acc.char_on.client_update_value(True)          # On restores the observed 50%
    assert disp.intents[-1]["level"] == 127


def test_bridge_routes_state_to_matching_lights(driver):
    import asyncio

    from edidio_control_py.state import LevelTracker, dali_change

    from edidio_homekit.bridge import EdidioHomeKitBridge
    from edidio_homekit.config import BridgeConfig

    cfg = BridgeConfig({
        "homekit": {"name": "t", "port": 51999, "pincode": "031-45-154"},
        "controller": {"host": "10.0.0.1"},
        "accessories": [
            {"id": "k", "name": "Kitchen", "type": "light", "line": 1, "address": 5},
            {"id": "g", "name": "Group", "type": "light", "line": 1, "group": 2},
        ],
    })
    bridge = EdidioHomeKitBridge(driver, cfg)
    change = dali_change({"kind": "dali", "line": 0, "frame_type": 1, "frame": 0x84FE})  # group 2 arc 254
    asyncio.run(bridge.on_state(change, LevelTracker().apply(change)))
    lights = {a.display_name: a for a in bridge.accessories.values()}
    assert lights["Group"].char_on.value is True and lights["Group"].char_brightness.value == 100
    assert lights["Kitchen"].char_on.value is False
