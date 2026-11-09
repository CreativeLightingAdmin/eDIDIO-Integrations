"""Offline tests for commands, device-log decoding, health findings, v2 acks and the
push identity check (no controller: stubs and synthetic protobuf messages)."""

import asyncio

import pytest
from edidio_control_py._v2 import eDS10_v2_pb2 as pb

from edidio_spektra_ai import commands, device_log, ops, v2
from edidio_spektra_ai.controller import SpektraController
from edidio_spektra_ai.spektra_file import SpektraProject


# --- commands ------------------------------------------------------------------

@pytest.mark.parametrize("spec,expect", [
    ({"do": "dali_arc", "line": 1, "group": 0, "level": 254},
     {"commandtype": 0, "linemask": 1, "target": 64, "value": 254}),
    ({"do": "dali_off", "line": 2, "broadcast": True},
     {"commandtype": 1, "linemask": 2, "target": 80, "value": 0}),
    ({"do": "dali_max", "line": 1, "address": 3, "override": True},
     {"commandtype": 55, "target": 3, "value": 5}),
    ({"do": "dali_scene", "lines": [1, 3], "group": 2, "scene": 4},
     {"commandtype": 1, "linemask": 5, "target": 66, "value": 20}),
    ({"do": "list_start", "list": 4}, {"commandtype": 9, "target": 4}),
    ({"do": "sequence", "sequence": 2, "zone": 1}, {"commandtype": 12, "target": 2, "zone": 1}),
    ({"do": "dmx", "line": 2, "channel": 300, "level": 9},
     {"commandtype": 3, "target": 44, "linemask": 2, "value": 9}),
    ({"do": "dmx_broadcast", "line": 1, "level": 63},
     {"commandtype": 6, "zone": 254, "target": 254, "linemask": 1, "value": 63}),
    ({"do": "output_high", "output": 1}, {"commandtype": 27, "target": 1}),
    ({"do": "profile", "profile": 2}, {"commandtype": 30, "target": 2}),
])
def test_build_matches_spektraplus_wire_shape(spec, expect):
    out = commands.build(spec)
    for k, v in expect.items():
        assert out[k] == v, (k, out)


def test_build_rejects_bad_specs():
    for bad in ({"do": "dali_arc", "line": 1, "group": 0},            # no level
                {"do": "dali_arc", "line": 9, "group": 0, "level": 1},  # bad line
                {"do": "dali_off", "line": 1},                         # no target
                {"do": "nonsense"}):
        with pytest.raises(commands.CommandError):
            commands.build(bad)


def test_describe_round_trips_names():
    assert commands.describe(commands.build('{"do":"dali_scene","line":1,"broadcast":true,'
                                            '"scene":0}')) == "DALI scene 0 -> broadcast line 1"
    assert commands.describe({"commandtype": 254}) == "no command"
    assert "List 3 (index 2)" in commands.describe({"commandtype": 9, "target": 2})


# --- device log ------------------------------------------------------------------

def _boot(day, flags):
    return pb.SystemLogMessage(time_since_boot=0, boot=pb.SystemLogBoot(
        timeclock=pb.TimeClockMessage(date=(26 << 16) | (11 << 8) | day,
                                      time=(9 << 16) | (31 << 8) | 14), flags=flags))


def test_decode_boot_trigger_and_wall_times():
    trig = pb.SystemLogMessage(time_since_boot=65, trigger=pb.SystemLogTrigger(
        source=5, trigger=pb.TriggerMessage(type=0, line_mask=1, target_index=64, value=254)))
    wd = pb.SystemLogMessage(time_since_boot=0)        # packet-less record after a boot
    entries = device_log.decode_entries([_boot(9, 0x21 << 8), trig,
                                         _boot(10, (0x04 << 8)), wd])
    assert entries[0]["summary"] == "Boot - Power-on, Reset pin"
    assert entries[1]["summary"].startswith("List: DALI arc 254 -> group 0 line 1")
    assert entries[1]["time"].strftime("%H:%M:%S") == "09:32:19"     # anchor + 65 s
    assert entries[2]["severity"] == "warning"                       # watchdog cause
    assert entries[3]["type"] == "Watchdog Reset"
    events = device_log.to_log_events(entries)
    assert events[0].action == "DALI Arc" and events[0].fields == {"line": 1, "group": 0,
                                                                   "value": 254}


def test_old_firmware_boot_flags_have_no_summary():
    e = device_log.decode_entries([_boot(9, 0x02)])[0]
    assert e["summary"] == "Boot - Settings reset to defaults"


# --- v2 acks ------------------------------------------------------------------------

def test_ack_summary_names_reject_reason():
    msg = pb.EdidioMessage(message_id=1, ack=pb.AckMessage(
        payload=pb.AckMessageType.INVALID_PARAMS, detail=pb.RejectReason.SENSOR_BAD_LINE))
    assert v2.ack_summary(msg) == {"ok": False, "code": "INVALID_PARAMS",
                                   "reason": "SENSOR_BAD_LINE"}
    ok = pb.EdidioMessage(message_id=1, ack=pb.AckMessage(payload=pb.AckMessageType.SUCCESS))
    assert v2.ack_summary(ok) == {"ok": True, "code": "SUCCESS"}


# --- health findings ---------------------------------------------------------------

def test_health_findings_flag_real_problems():
    raw = {"CONTROLLER_LINES": {"lines": ["LINE_DALI", "LINE_DMX"]},
           "DEVICE_STATUS": {"temperature": 41.0},
           "TIME_DIAGNOSTICS": {"vbat_low": True, "vbat_voltage": 2100, "rtc_ever_been_set": True,
                                "ntp_enabled_in_config": False},
           "DALI_STATUS": {"polling_active": True, "lines": [
               {"line_index": 0, "bus_power": "DALI_BUS_POWER_NONE", "short_count": 2,
                "device_count": 3, "fault_count": 1},
               {"line_index": 1, "bus_power": "DALI_BUS_POWER_UNKNOWN"}]},
           "WIFI_STATUS": {"unsupported": True}}
    f = ops._health_findings(raw)
    warns = [t for lvl, t in f if lvl == "warn"]
    assert any("backup battery low" in t for t in warns)
    assert any(t.startswith("DALI line 1") and "2 short(s)" in t for t in warns)
    assert not any("DALI line 2" in t for _l, t in f)       # line 2 is DMX


# --- push identity --------------------------------------------------------------------

class _IdentCtrl(SpektraController):
    def __init__(self, macs, hw="6P-1007-X"):
        super().__init__()
        self._ident = {"macs": macs, "firmware": "1.6.3", "hardware": hw}

    async def identify(self):
        return self._ident


def _proj(*macs, hw="6P-1007-Y"):
    return SpektraProject(raw={"edidios": {m: {"hardwareVersion": hw} for m in macs}})


def test_check_target_picks_the_connected_controller():
    ctrl = _IdentCtrl(["40:D8:55:1B:A5:8F"])
    mac, warn = asyncio.run(ctrl.check_target(_proj("40:D8:55:1B:A5:90", "40:d8:55:1b:a5:8f")))
    assert mac == "40:d8:55:1b:a5:8f" and warn == []


def test_check_target_refuses_wrong_device_and_model_change():
    with pytest.raises(ValueError, match="not in this file"):
        asyncio.run(_IdentCtrl(["40:D8:55:00:00:09"]).check_target(_proj("40:D8:55:00:00:01")))
    with pytest.raises(ValueError, match="Model changed"):
        asyncio.run(_IdentCtrl(["40:D8:55:00:00:01"], hw="4P-1").check_target(
            _proj("40:D8:55:00:00:01")))


def test_sd_helpers():
    # FAT date 23813 / time 29682 -> 2026-07-05 14:31:36 style decoding
    assert ops.fat_datetime(((2026 - 1980) << 9) | (9 << 5) | 7,
                            (9 << 11) | (48 << 5) | 16) == "2026-09-07 09:48:32"
    assert ops.fat_datetime(0, 0) == ""
    assert ops._sd_path("/logs/sys/") == "logs/sys"


def test_functionality_statement_groups_profiles_and_skips_blanks():
    from edidio_spektra_ai import statement
    mac = "40:D8:55:00:00:01"
    pc = {"commandtype": 1, "zone": 0, "linemask": 1, "target": 80, "value": 5, "query": 0}
    off = {**pc, "value": 0}
    nc = {"commandtype": 254}
    inp = {"index": 0, "type": 1, "shortLowAction": pc, "longHighAction": off}
    blank = {"index": 1, "type": 0, "shortLowAction": nc, "longHighAction": nc}
    ed = {"hardwareVersion": "6P-1007-X", "firmwareVersion": "1.6.3", "lineTypes": [1, 2],
          "network": {"deviceName": "Foyer"},
          "profiles": [{"inputs": [inp, blank]}, {"inputs": [inp, blank]}],
          "schedules": [{"index": 0, "IsEnabled": True, "repeat": 2, "weekdaysMask": 0x1F,
                         "startEvent": {"command": {"commandtype": 30, "target": 1},
                                        "type": 0, "time": "18:00:00"},
                         "endEvent": {"command": nc}}],
          "lists": [{"index": 2, "state": 0, "steps": [
              {"index": 0, "action": pc, "time_until_next": 90}]}]}
    text = statement.project_statement({"edidios": {mac: ed}}, title="Test")
    assert "**Input 1** (all profiles): latching contact - when closed: DALI MAX" in text
    assert "Input 2" not in text                                   # blank slot skipped
    assert "Schedule 1**: at 18:00, on working days (Monday to Friday)" in text
    assert "Profiles are changed by: Schedule 1 at 18:00" in text
    assert "then wait 1 min 30 s" in text


def test_zone_colour_messages():
    from edidio_spektra_ai import colour
    from edidio_control_py._v2 import eDS10_v2_pb2 as v2pb
    ids = iter(range(1, 100))
    dmx = {"index": 0, "protocol": 1, "numChannels": 3, "numLights": 5, "linemask": 2,
           "channelColours": ["#00FF00", "#FF0000", "#0000FF"]}
    assert colour.parse_levels("#FF8000", dmx) == [128, 255, 0]       # G, R, B channels
    f = colour.zone_messages(dmx, [128, 255, 0], lambda: next(ids))
    m = v2pb.EdidioMessage.FromString(f[0][3:]).dmx_message
    assert len(f) == 1 and m.channel == 0xFFFF and list(m.level) == [128, 255, 0]
    dali = {"index": 1, "protocol": 0, "numChannels": 2, "numLights": 3, "linemask": 1,
            "startAddress": 4, "daligroupoffset": None}
    f = colour.zone_messages(dali, [255, 10], lambda: next(ids))
    msgs = [v2pb.EdidioMessage.FromString(x[3:]).dali_message for x in f]
    assert [(d.address, d.arg) for d in msgs] == [(4, 254), (5, 10), (6, 254), (7, 10),
                                                 (8, 254), (9, 10)]
    grp = {**dali, "daligroupoffset": 2}
    msgs = [v2pb.EdidioMessage.FromString(x[3:]).dali_message
            for x in colour.zone_messages(grp, [1, 2], lambda: next(ids))]
    assert [d.address for d in msgs] == [66, 67]
