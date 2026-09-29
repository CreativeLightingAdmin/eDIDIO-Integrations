"""KNX bridge tests: feed constructed xknx telegrams through the bridge and
assert the correct eDIDIO intents are dispatched. No KNX bus, no eDIDIO.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xknx.dpt import DPTArray, DPTBinary  # noqa: E402
from xknx.telegram import Telegram  # noqa: E402
from xknx.telegram.address import GroupAddress  # noqa: E402
from xknx.telegram.apci import GroupValueRead, GroupValueResponse, GroupValueWrite  # noqa: E402

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


# --- status / feedback GAs (live DALI state -> KNX) ---

import asyncio  # noqa: E402

import pytest  # noqa: E402
from edidio_control_py.state import LevelTracker, dali_change  # noqa: E402

from edidio_knx.group_map import ConfigError  # noqa: E402

STATUS_RAW = {
    **RAW,
    "group_addresses": [
        {"ga": "1/1/1", "action": "dali_level", "dpt": "scaling", "line": 1,
         "dali_address": 5, "status_ga": "1/4/1"},
        {"ga": "1/1/2", "action": "dali_level", "dpt": "switch", "line": 1,
         "dali_address": 5, "status_ga": "1/4/2"},
        {"ga": "2/1/1", "action": "dali_group_level", "dpt": "scaling", "line": 1,
         "group": 0, "status_ga": "2/4/1"},
    ],
}


def make_status():
    sent = []
    bridge = KnxBridge(GatewayConfig(STATUS_RAW), FakeDispatcher(), send=sent.append)
    return bridge, sent


def feed(bridge, frame):
    change = dali_change({"kind": "dali", "line": 0, "frame_type": 1, "frame": frame})
    asyncio.run(bridge.on_state(change, LevelTracker().apply(change)))


def test_status_ga_written_with_matching_dpt():
    bridge, sent = make_status()
    feed(bridge, 0x0A7F)                        # addr 5 arc 127 (~50%)
    by_ga = {str(t.destination_address): t.payload for t in sent}
    assert isinstance(by_ga["1/4/1"], GroupValueWrite)
    assert by_ga["1/4/1"].value == DPTArray((128,))   # 127 * 255 / 254 = 127.5 -> 128
    assert by_ga["1/4/2"].value == DPTBinary(1)
    assert "2/4/1" not in by_ga


def test_status_unchanged_value_not_resent_and_off():
    bridge, sent = make_status()
    feed(bridge, 0x0A7F)
    n = len(sent)
    feed(bridge, 0x0A7F)
    assert len(sent) == n                       # no duplicate writes
    feed(bridge, 0x0B00)                        # addr 5 OFF
    by_ga = {str(t.destination_address): t.payload.value for t in sent[n:]}
    assert by_ga == {"1/4/1": DPTArray((0,)), "1/4/2": DPTBinary(0)}


def test_status_read_is_answered_with_last_value():
    bridge, sent = make_status()
    read = Telegram(destination_address=GroupAddress("1/4/2"), payload=GroupValueRead())
    bridge.handle_telegram(read)
    assert sent == []                           # nothing known yet
    feed(bridge, 0x0AFE)                        # addr 5 arc 254
    sent.clear()
    bridge.handle_telegram(read)
    assert len(sent) == 1 and isinstance(sent[0].payload, GroupValueResponse)
    assert sent[0].payload.value == DPTBinary(1)


def test_group_frame_updates_group_status_only():
    bridge, sent = make_status()
    feed(bridge, 0x8064)                        # group 0 arc 100
    assert [str(t.destination_address) for t in sent] == ["2/4/1"]


def test_status_ga_config_validation():
    bad = {**RAW, "group_addresses": [
        {"ga": "3/1/1", "action": "dali_scene", "dpt": "switch", "line": 1,
         "scene": 3, "status_ga": "3/4/1"}]}
    with pytest.raises(ConfigError):
        GatewayConfig(bad)
    clash = {**RAW, "group_addresses": [
        {"ga": "1/1/1", "action": "dali_level", "dpt": "scaling", "line": 1,
         "dali_address": 5, "status_ga": "1/1/1"}]}
    with pytest.raises(ConfigError):
        GatewayConfig(clash)
