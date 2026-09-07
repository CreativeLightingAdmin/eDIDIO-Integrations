"""KNX bridge tests: feed constructed xknx telegrams through the bridge and
assert the correct eDIDIO intents are dispatched. No KNX bus, no eDIDIO.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xknx.dpt import DPTArray, DPTBinary  # noqa: E402
from xknx.telegram import Telegram  # noqa: E402
from xknx.telegram.address import GroupAddress  # noqa: E402
from xknx.telegram.apci import GroupValueRead, GroupValueWrite  # noqa: E402

from edidio_knx.bridge import KnxBridge  # noqa: E402
from edidio_knx.config import GatewayConfig  # noqa: E402


class FakeDispatcher:
    def __init__(self):
        self.intents = []

    def submit(self, intent):
        self.intents.append(intent)


RAW = {
    "knx": {"connection": "tunnelling", "gateway_ip": "10.0.0.100"},
    "controller": {"host": "10.0.0.1", "port": 23},
    "group_addresses": [
        {"ga": "1/1/1", "action": "dali_level", "dpt": "scaling", "line": 1, "dali_address": 5},
        {"ga": "1/1/2", "action": "dali_level", "dpt": "switch", "line": 1, "dali_address": 5},
        {"ga": "2/1/1", "action": "dali_group_level", "dpt": "scaling", "line": 1, "group": 0},
        {"ga": "3/1/1", "action": "dali_scene", "dpt": "switch", "line": 1, "scene": 3},
        {"ga": "3/2/1", "action": "dali_scene", "dpt": "scene_number", "line": 1},
    ],
}


def make():
    cfg = GatewayConfig(RAW)
    disp = FakeDispatcher()
    return KnxBridge(cfg, disp), disp


def write(ga, value):
    return Telegram(destination_address=GroupAddress(ga), payload=GroupValueWrite(value))


def test_group_addresses_listed():
    bridge, _ = make()
    assert set(bridge.group_addresses()) == {"1/1/1", "1/1/2", "2/1/1", "3/1/1", "3/2/1"}


def test_scaling_dim():
    bridge, disp = make()
    bridge.handle_telegram(write("1/1/1", DPTArray((255,))))
    assert disp.intents[-1] == {"kind": "dali_level", "line": 1, "address": 5, "level": 254}


def test_switch_on_off():
    bridge, disp = make()
    bridge.handle_telegram(write("1/1/2", DPTBinary(1)))
    assert disp.intents[-1]["level"] == 254
    bridge.handle_telegram(write("1/1/2", DPTBinary(0)))
    assert disp.intents[-1]["level"] == 0


def test_group_dim():
    bridge, disp = make()
    bridge.handle_telegram(write("2/1/1", DPTArray((128,))))
    assert disp.intents[-1] == {"kind": "dali_group_level", "line": 1, "group": 0, "level": 127}


def test_scene_trigger():
    bridge, disp = make()
    bridge.handle_telegram(write("3/1/1", DPTBinary(1)))
    assert disp.intents[-1] == {"kind": "dali_scene", "line": 1, "scene": 3}
    # "off" on a trigger GA produces nothing
    n = len(disp.intents)
    bridge.handle_telegram(write("3/1/1", DPTBinary(0)))
    assert len(disp.intents) == n


def test_scene_number():
    bridge, disp = make()
    bridge.handle_telegram(write("3/2/1", DPTArray((5,))))
    assert disp.intents[-1] == {"kind": "dali_scene", "line": 1, "scene": 5}
    # out-of-range scene index ignored
    n = len(disp.intents)
    bridge.handle_telegram(write("3/2/1", DPTArray((99,))))
    assert len(disp.intents) == n


def test_unmapped_ga_ignored():
    bridge, disp = make()
    bridge.handle_telegram(write("7/7/7", DPTBinary(1)))  # valid GA, not in map
    assert disp.intents == []


def test_group_read_ignored():
    bridge, disp = make()
    # A GroupValueRead on a mapped GA must not trigger an action.
    bridge.handle_telegram(Telegram(destination_address=GroupAddress("1/1/2"), payload=GroupValueRead()))
    assert disp.intents == []
