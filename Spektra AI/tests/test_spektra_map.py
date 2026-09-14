"""Tests for the protobuf -> .spektra mappers (spektra_map).

Uses lightweight stand-in objects (SimpleNamespace) for the protobuf messages: the
mappers only read attributes, so this exercises the mapping logic without building
real protobufs. Real protobuf field fidelity is covered by the live pull smoke test.
"""

import os
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb  # noqa: E402

from edidio_spektra_ai import spektra_map as m  # noqa: E402


def _decode(frame):
    assert frame[0] == 0xCD
    msg = pb.EdidioMessage()
    msg.ParseFromString(frame[3:])
    return msg


def test_decode_date_and_time():
    packed_date = (25 << 24) | (10 << 16) | (15 << 8) | 3   # 2025-10-15
    assert m.decode_date(packed_date) == "2025-10-15"
    packed_time = (7 << 16) | (0 << 8) | 0                   # 07:00:00
    assert m.decode_time(packed_time) == "07:00:00"


def test_number_to_hex_and_light_type():
    assert m.number_to_hex(0xFF0000) == "#FF0000"
    assert m.infer_light_type("#00ff00") == 1          # GREEN
    assert m.infer_light_type("#123456") == 7          # CUSTOM (unknown)


def test_fade_time_best_fit():
    assert m.find_fade_time_best_fit(100) == (1, 1)     # 1000ms -> 1 second
    assert m.find_fade_time_best_fit(50) == (500, 0)    # 500ms -> 500 ms
    assert m.find_fade_time_best_fit(6000) == (1, 2)    # 60000ms -> 1 minute


def test_trigger_no_command_default():
    assert m.trigger_to_dict(None)["commandtype"] == 254
    assert m.trigger_to_dict(NS(type=254))["commandtype"] == 254


def test_trigger_maps_fields():
    pb = NS(type=12, zone=1, line_mask=2, target_index=3, value=4, query_index=5)
    assert m.trigger_to_dict(pb) == {"commandtype": 12, "zone": 1, "linemask": 2,
                                     "target": 3, "value": 4, "query": 5}


def _seq(**over):
    base = dict(index=0, title="Seq", type=4, transition=0, fade_time_by_10ms=100,
                time_per_colour=2000, time_per_colour_unit=1, time_per_step=500,
                time_per_step_unit=1, range=0, is_randomised_type=False,
                random_types_mask=0b101, is_reverse_direction=True,
                is_cycle_direction=False, has_random_colour_order=False,
                args=[0, 0, 0], colours=[NS(channel_value=[255, 0, 0])])
    base.update(over)
    return NS(**base)


def test_sequence_mapping():
    d = m.sequence_to_dict(_seq())
    assert d["name"] == "Seq" and d["index"] == 0 and d["sequenceType"] == 4
    assert d["direction"] == 1                          # reverse
    assert d["fadeTime"] == 1 and d["fadeTimeUnit"] == 1
    assert d["colours"] == [{"channelValues": [255, 0, 0]}]
    assert d["backgroundColour"] == {"channelValues": [0, 0, 0]}
    assert d["randomisedSequenceTypes"] == [0, 2]       # bits 0 and 2 set


def test_sequence_cycle_direction_wins():
    d = m.sequence_to_dict(_seq(is_reverse_direction=True, is_cycle_direction=True))
    assert d["direction"] == 2                          # cycle


def test_theme_mapping():
    pb = NS(index=1, title="", colours=[NS(channel_value=[0, 254, 0])])
    d = m.theme_to_dict(pb)
    assert d["name"] == "Theme 2"                       # falls back to index+1
    assert d["colours"] == [{"channelValues": [0, 254, 0]}]


def test_zone_mapping():
    pb = NS(zone=0, channels_per_light=3, channel_colours=[0xFF0000, 0x00FF00, 0x0000FF],
            line_or_universe_mask=1, number_of_lights=110, protocol=1, start_address=0,
            unscheduled_behaviour=0, zone_scale_factor=1.0, line_addressing=0)
    d = m.zone_to_dict(pb)
    assert d["alias"] == "Zone 1" and d["numChannels"] == 3 and d["numLights"] == 110
    assert d["channelColours"] == ["#FF0000", "#00FF00", "#0000FF"]
    assert d["channelTypes"] == [0, 1, 2]               # RED, GREEN, BLUE


def test_schedule_mapping():
    trig = NS(type=12, zone=1, line_mask=1, target_index=0, value=0, query_index=0)
    no_trig = NS(type=254)
    pb = NS(index=0, enabled=True, repeat=1, repeat_month_bitmask=4095,
            repeat_day_bitmask=31, yearly=True, astro_start=0, astro_end=0,
            start_trigger=trig, end_trigger=no_trig,
            start_time=NS(date=(25 << 24) | (10 << 16) | (15 << 8), time=(7 << 16)),
            end_time=NS(date=0, time=0),
            start_offset_is_before=True, end_offset_is_before=False)
    d = m.schedule_to_dict(pb)
    assert d["name"] == "Schedule 1" and d["IsEnabled"] is True
    assert d["startEvent"]["time"] == "07:00:00"
    assert d["startEvent"]["command"]["commandtype"] == 12
    assert d["endEventIsActive"] is False              # end date/time both 0 -> disabled


# --- forward mappers (.spektra dict -> protobuf frame) ---

def test_get_fade_time_by_10ms_inverse():
    assert m.get_fade_time_by_10ms(1, 1) == 100        # 1 second -> 100 (x10ms)
    assert m.get_fade_time_by_10ms(500, 0) == 50       # 500 ms -> 50


def test_cap_value_dali_vs_dmx():
    assert m.cap_value(255, True) == 254               # DALI caps at 254
    assert m.cap_value(255, False) == 255              # DMX allows 255


def test_theme_to_message_roundtrips_through_protobuf():
    theme = {"index": 3, "name": "Test Theme",
             "colours": [{"channelValues": [10, 20, 30]}, {"channelValues": [255, 0, 0]}]}
    frame = m.theme_to_message(theme, message_id=1, is_dali=True)
    t = _decode(frame).spektra_theme
    assert t.index == 3 and t.title == "Test Theme"
    assert [list(c.channel_value) for c in t.colours] == [[10, 20, 30], [254, 0, 0]]  # DALI cap


def test_sequence_to_message_roundtrips_through_protobuf():
    seq = {
        "index": 7, "name": "Fwd Seq", "sequenceType": 4, "transitionType": 0,
        "fadeTime": 1, "fadeTimeUnit": 1, "timePerColour": 2000, "timePerColourUnit": 1,
        "timePerStep": 500, "timePerStepUnit": 1, "range": 0, "isRandom": False,
        "randomisedSequenceTypes": [0, 2], "direction": 2, "hasRandomColourOrder": False,
        "backgroundColour": {"channelValues": [1, 2, 3]},
        "colours": [{"channelValues": [255, 0, 0]}, {"channelValues": [0, 255, 0]}],
    }
    s = _decode(m.sequence_to_message(seq, message_id=1, is_dali=False)).spektra_sequence
    assert s.index == 7 and s.title == "Fwd Seq" and s.type == 4
    assert s.fade_time_by_10ms == 100                  # 1s -> 100
    assert s.is_cycle_direction == 1 and s.is_reverse_direction == 0  # direction 2 = cycle
    assert s.random_types_mask == 0b101                # bits 0,2
    assert [list(c.channel_value) for c in s.colours] == [[255, 0, 0], [0, 255, 0]]
    assert list(s.args)[:3] == [1, 2, 3]               # background in args


def test_encode_decode_date_time_are_inverse():
    assert m.decode_date(m.encode_date("2025-10-15")) == "2025-10-15"
    assert m.decode_time(m.encode_time("07:30:45")) == "07:30:45"
    assert m.encode_date("2000-00-00") == 0            # invalid sentinel -> 0
    assert m.encode_time("00:00:00") == 0


def test_hex_number_inverse():
    assert m.hex_to_number("#FF8000") == 0xFF8000
    assert m.number_to_hex(m.hex_to_number("#123456")) == "#123456"


def test_schedule_to_message_roundtrips_through_protobuf():
    sched = {
        "index": 8, "IsEnabled": True, "repeat": 1, "weekdaysMask": 31,
        "monthsMask": 4095, "yearly": True,
        "startEvent": {"command": {"commandtype": 12, "zone": 1, "linemask": 0,
                                   "target": 3, "value": 0, "query": 0},
                       "type": 0, "date": "2025-10-15", "time": "07:00:00",
                       "offsetBefore": True},
        "endEvent": {"command": {"commandtype": 254}, "type": 0,
                     "date": "2000-00-00", "time": "00:00:00", "offsetBefore": False},
        "endEventIsActive": False,
    }
    a = _decode(m.schedule_to_message(sched, message_id=1)).alarm
    assert a.index == 8 and a.enabled is True
    assert a.repeat_day_bitmask == 31 and a.repeat_month_bitmask == 4095
    assert a.start_trigger.type == 12 and a.start_trigger.target_index == 3
    assert a.start_time.time == (7 << 16)
    assert a.end_trigger.type == 254                    # inactive end -> NO_COMMAND


def test_zone_to_message_roundtrips_through_protobuf():
    zone = {"index": 2, "startAddress": 5, "linemask": 1, "protocol": 1,
            "numLights": 110, "numChannels": 4,
            "channelColours": ["#FF0000", "#00FF00", "#0000FF", "#FFD580"],
            "unscheduledBehaviourType": 0, "multiLineAddressing": 0, "scaleFactor": 1.0}
    s = _decode(m.zone_to_message(zone, message_id=1)).spektra_settings
    assert s.zone == 2 and s.number_of_lights == 110 and s.channels_per_light == 4
    assert s.start_address == 5 and s.protocol == 1
    assert list(s.channel_colours) == [0xFF0000, 0x00FF00, 0x0000FF, 0xFFD580]


# --- per-profile I/O, logic, lists ---

def test_input_roundtrips_through_protobuf():
    d = {"index": 0, "type": 1,
         "shortLowAction": {"commandtype": 1, "zone": 255, "linemask": 1,
                            "target": 16, "value": 5, "query": 0},
         "longHighAction": {"commandtype": 254, "zone": 0, "linemask": 0,
                            "target": 0, "value": 0, "query": 0}}
    frame = m.inputs_to_message(profile=2, inputs=[d], message_id=1)
    im = _decode(frame).inputs
    assert im.profile == 2 and len(im.inputs) == 1
    assert im.inputs[0].button_state == 1
    assert im.inputs[0].short_press.type == 1 and im.inputs[0].short_press.target_index == 16


def test_output_canonical_latching_time():
    # LATCHING_OUTPUT (type 3) -> trigger time collapses to 255
    d = m.output_to_dict(NS(index=0, type=3, initial_level=0, time_trigger_is_active=17))
    assert d["triggerTime"] == 255
    frame = m.outputs_to_message(profile=0, outputs=[d], message_id=1)
    om = _decode(frame).outputs
    assert om.outputs[0].time_trigger_is_active == 255 and om.outputs[0].type == 3


def test_logic_roundtrips_through_protobuf():
    g = {"index": 1, "comparisonObject": {"commandtype": 9, "zone": 0, "linemask": 0,
                                          "target": 1, "value": 0, "query": 0},
         "comparisonType": 2, "comparisonValue": 42,
         "trueAction": {"commandtype": 12, "zone": 1, "linemask": 0, "target": 0,
                        "value": 0, "query": 0},
         "falseAction": {"commandtype": 254}}
    lm = _decode(m.logic_to_message([g], message_id=1)).logic_message
    assert len(lm.logic) == 1
    assert lm.logic[0].comparison_type == 2 and lm.logic[0].comparison_value == 42
    assert lm.logic[0].actionA.type == 12 and lm.logic[0].actionB.type == 254


def test_list_roundtrips_through_protobuf():
    lst = {"index": 3, "state": 1,
           "steps": [{"time_until_next": 5,
                      "action": {"commandtype": 9, "zone": 0, "linemask": 1,
                                 "target": 2, "value": 254, "query": 0}}]}
    lm = _decode(m.list_to_message(lst, message_id=1)).list
    assert lm.list_index == 3 and lm.list_state == 1 and lm.total_step_count == 1
    assert lm.step[0].time_seconds == 5 and lm.step[0].action.target_index == 2


# --- sensors + DALI inputs ---

def test_dali_line_helpers_inverse():
    for n in (1, 2, 3, 4):
        assert m.dali_line_mask_to_number(m.line_number_to_mask(n)) == n
    assert m.line_number_to_mask(0) == 0 and m.dali_line_mask_to_number(0) == 0


def test_version_gte():
    assert m.version_gte("1.3.0", "1.3.0")
    assert m.version_gte("1.4.1", "1.3.0")
    assert not m.version_gte("1.0.86", "1.3.0")


def test_sensor_roundtrips_through_protobuf():
    sensor = {
        "index": 1, "line": 2, "address": 5, "setPoint": 10, "controlLineMask": 1,
        "controlGroup": 2, "addressQuery": 0, "inactivityTimer": 30, "warningTimer": 2,
        "disableTimer": 1, "motionOnly": True,
        "detectionTrigger": {"commandtype": 9, "zone": 0, "linemask": 1, "target": 3,
                             "value": 254, "query": 0},
        "warningTrigger": {"commandtype": 254}, "idleTrigger": {"commandtype": 254},
        "groupedWithIndexes": [1, 3], "coopGroup": 0, "coopLeader": False}
    s = _decode(m.sensor_to_message(sensor, profile=4, message_id=1)).sensor
    assert s.profile == 4 and s.index == 1 and s.sensor_address == 5
    assert s.sensor_dali_line == 2 and s.timeout_values == 30 and s.is_programmed
    assert s.motion_sensors == 0b1010          # legacy grouping bits 1 and 3
    assert s.detection_trigger.target_index == 3
    d = m.sensor_to_dict(s)                     # reverse back to a dict
    assert d["line"] == 2 and d["address"] == 5 and d["groupedWithIndexes"] == [1, 3]
    assert d["motionOnly"] is True and d["inactivityTimer"] == 30


def test_daliinput_roundtrips_through_protobuf():
    di = {"index": 0, "type": 1, "address": 7, "instance": 2, "line": 3,
          "shortOrLowAction": {"commandtype": 1, "zone": 0, "linemask": 4, "target": 16,
                               "value": 0, "query": 0},
          "longOrHighAction": {"commandtype": 254}}
    im = _decode(m.daliinputs_to_message(profile=3, inputs=[di], message_id=1)).inputs_dali
    assert im.profile == 3 and len(im.inputs) == 1
    assert im.inputs[0].address == 7 and im.inputs[0].dali_line == 4   # line 3 -> mask 4
    assert im.inputs[0].short_press.target_index == 16
    d = m.daliinput_to_dict(im.inputs[0])
    assert d["line"] == 3 and d["address"] == 7 and d["instance"] == 2


# --- persistence / profile / clear helpers ---

def test_zone_save_message():
    s = _decode(m.zone_save_message(1)).spektra_control
    assert s.action == pb.SpektraActionType.SAVE and s.type == pb.SpektraTargetType.SETTINGS


def test_device_save_message():
    msg = _decode(m.device_save_message(1))
    assert msg.external_trigger.trigger.type == pb.TriggerType.DEVICE_SAVE


def test_change_profile_message():
    assert _decode(m.change_profile_message(1, 3)).change_profile.profile == 3


def test_reset_sensors_message():
    a = _decode(m.reset_sensors_message(1)).admin_message
    assert a.command == pb.AdminCommandType.RESET
    assert a.target == pb.AdminPropertyType.DALI_SENSORS
