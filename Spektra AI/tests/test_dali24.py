"""DALI-2 control devices (IEC 62386-103): 24-bit frame encoding, and what probe and
describe make of a device's answers (queries replaced by a table)."""
import asyncio

from edidio_spektra_ai import dali24 as D


def test_frame_encoding():
    # Address byte is (short address << 1) | 1, then the instance byte, then the opcode.
    assert D.frame(5, D.DEVICE, D.Q_INSTANCES) == (0x0B << 16) | (0xFE << 8) | 0x35
    assert D.frame(D.BROADCAST, D.DEVICE, 0x00) >> 16 == 0xFF     # broadcast to all devices
    assert D.frame(63, 2, D.Q_INSTANCE_TYPE) == (0x7F << 16) | (2 << 8) | 0x80


def test_special_command_sets_dtr():
    assert D.special(0x30, 0x1FF) == (0xC1 << 16) | (0x30 << 8) | 0xFF   # value masked to 8 bits


def _answers(table):
    async def fake_query(ctrl, line, address, instance, opcode):
        return table.get((address, instance, opcode))
    return fake_query


def test_probe_reads_device_and_instances(monkeypatch):
    t = {(7, D.DEVICE, D.Q_INSTANCES): 2, (7, D.DEVICE, D.Q_VERSION): 0x09,       # 2.1
         (7, D.DEVICE, D.Q_DEVICE_GROUPS[0]): 0b101, (7, D.DEVICE, D.Q_DEVICE_GROUPS[3]): 0x80,
         (7, D.DEVICE, D.Q_APP_CONTROLLER_ENABLED): 0xFF,
         (7, 0, D.Q_INSTANCE_TYPE): 3, (7, 0, D.Q_INSTANCE_ENABLED): 0xFF,
         (7, 0, D.Q_INPUT_VALUE): 0x55, (7, 0, D.Q_EVENT_FILTER[0]): 0x0F,
         (7, 1, D.Q_INSTANCE_TYPE): 4, (7, 1, D.Q_INPUT_VALUE): 0xFF,
         (7, 1, D.Q_INPUT_VALUE_LATCH): 0xC0, (7, 1, D.Q_INSTANCE_ERROR): 0x02}
    monkeypatch.setattr(D, "query", _answers(t))
    dev = asyncio.run(D.probe(None, 1, 7))
    assert dev["version_text"] == "2.1"
    assert dev["device_groups"] == [0, 2, 31]          # 4 query bytes -> 32 group bits
    assert dev["app_controller_enabled"] is True
    motion, light = dev["instances"]
    assert motion["type_name"] == D.INSTANCE_TYPES[3] and motion["enabled"] is True
    assert motion["motion"] == D.MOTION_VALUES[0x55] and motion["event_filter"] == 0x0F
    assert light["enabled"] is False                   # no answer to a yes/no query = NO
    assert light["light_level"] == 1023                # (0xFF << 2) | (0xC0 >> 6), capped
    text = D.describe(dev)
    assert "version 2.1, 2 instance(s), device groups [0, 2, 31]" in text
    assert "DISABLED" in text and "error 0x02" in text and "light 1023/1023" in text


def test_probe_returns_none_when_nothing_answers(monkeypatch):
    monkeypatch.setattr(D, "query", _answers({}))
    assert asyncio.run(D.probe(None, 1, 7)) is None


def test_scan_lists_answering_addresses(monkeypatch):
    monkeypatch.setattr(D, "query", _answers({(3, D.DEVICE, D.Q_INSTANCES): 1,
                                              (40, D.DEVICE, D.Q_INSTANCES): 4}))
    assert asyncio.run(D.scan(None, 2)) == [{"address": 3, "instances": 1},
                                             {"address": 40, "instances": 4}]
