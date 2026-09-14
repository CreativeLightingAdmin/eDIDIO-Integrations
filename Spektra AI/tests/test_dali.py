"""Tests for DALI Phase 4: message encodings and response decoders."""

import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb  # noqa: E402

from edidio_spektra_ai import dali  # noqa: E402


def _decode(frame):
    assert frame[0] == 0xCD
    m = pb.EdidioMessage()
    m.ParseFromString(frame[3:])
    return m


def _ids():
    return itertools.count(1).__next__


def test_line_mask():
    assert [dali.line_mask(n) for n in (1, 2, 3, 4)] == [1, 2, 4, 8]


def test_query_message_encoding():
    m = _decode(dali.query_message(1, 2, 5, pb.DALIQueryType.DALI_QUERY_STATUS))
    assert m.dali_message.line_mask == 2 and m.dali_message.address == 5
    assert m.dali_message.query == pb.DALIQueryType.DALI_QUERY_STATUS


def test_decode_query_responded_vs_not():
    reply = pb.EdidioMessage(dali_query=pb.DALIQueryResponse(
        dali_flag=pb.DALIRXStatusFlag.RECEIVED_8_BIT_FRAME,
        response_data=pb.PayloadMessage(uint_data=0x04)))
    d = dali.decode_query(reply)
    assert d["responded"] and d["data"] == 0x04

    absent = pb.EdidioMessage(dali_query=pb.DALIQueryResponse(
        dali_flag=pb.DALIRXStatusFlag.NO_RECEIVED_FRAME))
    assert dali.decode_query(absent)["responded"] is False


def test_decode_status_bits():
    s = dali.decode_status(0x04 | 0x02)   # lamp_on + lamp_failure
    assert s["lamp_on"] and s["lamp_failure"]
    assert not s["gear_failure"] and not s["missing_short_address"]


def test_arc_message():
    m = _decode(dali.arc_message(1, 1, 3, 200))
    assert m.dali_message.custom_command == pb.CustomDALICommandType.DALI_ARC_LEVEL
    assert m.dali_message.arg == 200 and m.dali_message.address == 3


def test_colour_temperature_sequence():
    msgs = dali.colour_temperature_messages(_ids(), 1, 0, 370)
    decoded = [_decode(f).dali_message for f in msgs]
    assert decoded[0].type8 == pb.Type8CommandType.SET_TEMP_COLOUR_TEMPERATURE
    assert list(decoded[0].dtr.dtr) == [370 & 0xFF, (370 >> 8) & 0xFF]
    assert decoded[1].type8 == pb.Type8CommandType.ACTIVATE


def test_rgbwaf_sequence_order():
    msgs = dali.rgbwaf_messages(_ids(), 2, 4, [255, 0, 0], [0, 0, 0], 254)
    d = [_decode(f).dali_message for f in msgs]
    assert d[0].type8 == pb.Type8CommandType.SET_TEMP_RGBWAF_CONTROL
    assert list(d[0].dtr.dtr) == [0x80]
    assert d[1].type8 == pb.Type8CommandType.SET_TEMP_RGB_DIMLEVEL
    assert list(d[1].dtr.dtr) == [255, 0, 0]
    assert d[2].type8 == pb.Type8CommandType.SET_TEMP_WAF_DIMLEVEL
    assert d[3].custom_command == pb.CustomDALICommandType.DALI_ARC_LEVEL and d[3].arg == 254
    assert d[4].type8 == pb.Type8CommandType.ACTIVATE


def test_addressing_start_and_continue():
    start = _decode(dali.addressing_message(1, 1, initialisation=True, readdress=True))
    assert start.dali_addressing_message.initialisation is True
    assert start.dali_addressing_message.type == pb.DALIAddressingType.READDRESS_ALL
    cont = _decode(dali.addressing_message(2, 1, initialisation=False))
    assert cont.dali_addressing_message.initialisation is False
    assert cont.dali_addressing_message.type == pb.DALIAddressingType.ADDRESS_NEW


def test_decode_addressing_states():
    ok = pb.EdidioMessage(dali_addressing_message=pb.DALIAddressingMessage(
        error=pb.DALIAddressingError.NO_ERROR, index=7))
    r = dali.decode_addressing(ok)
    assert r["ok"] and not r["finished"] and r["addressed"] == 7

    done = pb.EdidioMessage(dali_addressing_message=pb.DALIAddressingMessage(
        error=pb.DALIAddressingError.NO_NEW_DEVICE))
    assert dali.decode_addressing(done)["finished"] is True

    bad = pb.EdidioMessage(dali_addressing_message=pb.DALIAddressingMessage(
        error=pb.DALIAddressingError.SEARCH))
    assert dali.decode_addressing(bad)["ok"] is False


def test_remapping_message():
    m = _decode(dali.remapping_message(1, 1, 5, 9))
    assert m.dali_remapping_message.from_address == 5
    assert m.dali_remapping_message.to_address == 9


def test_dtr_frame_encoding():
    m = _decode(dali.dtr_frame(1, 2, dali._DTR1_OPCODE, 0))   # DTR1 = bank 0
    assert m.dali_message.frame_16_bit == (0xC3 << 8) | 0
    m2 = _decode(dali.dtr_frame(1, 2, dali._DTR0_OPCODE, 0x09))  # DTR0 = loc 0x09
    assert m2.dali_message.frame_16_bit == (0xA3 << 8) | 0x09


def test_commission_report_match_and_grouping():
    groups = [{"serial": "AA", "channels": [0, 1, 2, 3, 4, 5]},
              {"serial": "BB", "channels": [6, 7, 8, 9]}]
    report = dali.format_commission_report(10, groups, expected_channels=10,
                                           expected_devices=2)
    assert "Addressed 10" in report and "Expected 10 - OK" in report
    assert "device 1 (serial AA): 6 channel" in report
    assert "device 2 (serial BB): 4 channel" in report


def test_fade_time_to_code():
    assert dali.fade_time_to_code(2.8) == 5      # 2.83s
    assert dali.fade_time_to_code(2.0) == 4
    assert dali.fade_time_to_code(0.0) == 0


def test_add_to_group_frame():
    # address 3 add to group 4: high byte = (3<<1)|1 = 7, low byte = 0x60+4 = 0x64
    f = dali.add_to_group_frame16(3, 4)
    m = _decode(dali.config_message(1, 2, f))
    assert m.dali_message.frame_16_bit == (((3 << 1) | 1) << 8) | 0x64


def test_store_scene_frame_addressed_and_broadcast():
    assert dali.store_scene_frame16(5, 3) == (((5 << 1) | 1) << 8) | 0x43
    assert dali.store_scene_frame16(0, 3, broadcast=True) == (0xFF << 8) | 0x43


def test_set_fade_time_and_dtr0_frames():
    assert dali.set_fade_time_frame16(0, broadcast=True) == (0xFF << 8) | 0x2E
    assert dali.dtr0_set_frame16(50) == (0xA3 << 8) | 50


def test_commission_report_flags_mismatch_and_duplicate_serial():
    # 16 channels but only 2 serial groups while 3 devices expected (duplicate serials)
    groups = [{"serial": "DUP", "channels": list(range(12))},
              {"serial": "X", "channels": [12, 13, 14, 15]}]
    report = dali.format_commission_report(16, groups, expected_channels=20,
                                           expected_devices=3)
    assert "Expected 20 - MISMATCH" in report
    assert "still be unaddressed" in report
    assert "expected 3 physical device" in report and "identify" in report
