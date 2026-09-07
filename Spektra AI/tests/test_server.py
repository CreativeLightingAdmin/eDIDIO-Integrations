"""Exercise the Spektra AI MCP tools with a stub EdidioClient (no network).

Covers the preview -> confirm authoring flow, read parsing, error handling and
the capability-guide resource.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb  # noqa: E402

from edidio_spektra_ai import server as srv  # noqa: E402
from edidio_spektra_ai.controller import SpektraController  # noqa: E402


class StubClient:
    """Records sent frames; replies to request() with a SUCCESS ack (or a canned
    read reply keyed by the request payload type)."""

    def __init__(self, host, port, use_tls):
        self.host = host
        self.connected = False
        self.sent = []

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def send_protobuf_message(self, frame):
        self.sent.append(bytes(frame))

    async def request(self, frame):
        self.sent.append(bytes(frame))
        req = pb.EdidioMessage()
        req.ParseFromString(frame[3:])
        which = req.WhichOneof("payload")
        reply = pb.EdidioMessage(message_id=req.message_id)
        if which == "spektra_read":
            self._reply_spektra_read(req.spektra_read, reply)
        elif which == "read_device" and req.read_device.type == pb.ReadType.ALARMS:
            a = reply.alarms.alarm.add()
            a.index, a.enabled = 0, True
            a.start_time.time = (17 << 16)  # 17:00
            a.repeat = pb.AlarmRepeatType.ALARM_REPEAT_DAILY
            a.start_trigger.type = pb.TriggerType.SPEKTRA_START_SEQ
            a.start_trigger.target_index = 5
            a.start_trigger.zone = 1
        elif which == "diag_message" and req.diag_message.type == pb.DiagnosticMessageType.DMX_LEVEL_CACHE:
            # Firmware returns garbage in line/page on an active line; our code
            # should ignore these and report the requested line/page instead.
            reply.level_cache_response.line = 0xA0000000
            reply.level_cache_response.page = 999
            reply.level_cache_response.levels.extend([255, 0, 0])
        elif which == "admin_message" and req.admin_message.command == pb.AdminCommandType.GET \
                and req.admin_message.target == pb.AdminPropertyType.DEVICE_TIME:
            am = reply.admin_message
            am.command, am.target = pb.AdminCommandType.GET, pb.AdminPropertyType.DEVICE_TIME
            # 2026-09-07 10:10:26, weekday Mon -> packed date/time
            am.device_time.time.date = (26 << 24) | (9 << 16) | (7 << 8) | 1
            am.device_time.time.time = (10 << 16) | (10 << 8) | 26
        else:
            reply.ack.payload = pb.AckMessageType.SUCCESS
        return reply

    @staticmethod
    def _reply_spektra_read(read, reply):
        rtype, index = read.type, read.index
        if rtype == pb.SpektraTargetType.SETTINGS:
            reply.spektra_settings.zone = index
            reply.spektra_settings.protocol = 1  # DMX
            reply.spektra_settings.channels_per_light = 3
            reply.spektra_settings.number_of_lights = 10
        elif rtype == pb.SpektraTargetType.SEQUENCE and index < 2:
            reply.spektra_sequence.index = index
            reply.spektra_sequence.type = 4  # ROTATE
            reply.spektra_sequence.title = f"Seq{index}"
            reply.spektra_sequence.colours.add().channel_value.extend([255, 0, 0])
        elif rtype == pb.SpektraTargetType.THEME and index < 1:
            reply.spektra_theme.index = index
            reply.spektra_theme.title = f"Theme{index}"
            reply.spektra_theme.colours.add().channel_value.extend([0, 0, 255])
        elif rtype == pb.SpektraTargetType.LIVE:
            lv = reply.spektra_live
            lv.type.extend([1, 0])       # zone 0 = sequence, zone 1 = none
            lv.index.extend([6, 255])
            lv.step_index.extend([3, 0])
            lv.colour_index.extend([2, 0])
            lv.action.extend([1, 0])     # zone 0 = playing (action 1)
            lv.zone_active.extend([False, False])
        elif rtype == pb.SpektraTargetType.CALENDAR:
            ov = reply.spektra_calendar_overview
            ov.day_offset = index * 90
            if index == 0:  # only page 0 carries an assignment in this stub
                d = ov.days.add()
                d.day_index, d.type, d.target_index = 0, 1, 5  # day 1 -> sequence 5
        else:
            reply.ack.payload = pb.AckMessageType.INDEX_OUT_OF_BOUNDS

    # unused by these tests but part of the client surface
    async def set_dali_arc_level(self, *a):
        self.sent.append(("dali", a))

    async def set_dmx_level(self, *a):
        self.sent.append(("dmx", a))


def fresh_controller():
    """Install a stub-backed controller into the server module."""
    ctrl = SpektraController(client_factory=lambda h, p, t: StubClient(h, p, t))
    srv._controller = ctrl
    srv._pending.clear()
    return ctrl


def run(coro):
    return asyncio.run(coro)


def test_capability_guide_resource():
    g = srv.capability_guide()
    assert "SpektraSequenceConfigMessage" in g and "ROTATE" in g


def test_connect_and_status():
    fresh_controller()
    assert "Connected" in run(srv.connect_controller("10.0.0.1"))
    assert "10.0.0.1" in run(srv.connection_status())


def test_preview_then_confirm_sequence():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.preview_sequence({"index": 5, "type": "rotate",
                                    "colours": [[255, 0, 0], [255, 255, 0], [0, 255, 0]],
                                    "title": "RYG", "time_per_step_ms": 500}))
    assert "PREVIEW" in out and "token" in out
    token = out.split('token="')[1].split('"')[0]
    result = run(srv.confirm(token))
    assert "Done" in result and "SUCCESS" in result
    # the frame really got sent
    assert any(isinstance(x, bytes) for x in srv._controller._client.sent)


def test_confirm_bad_token():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    assert "Unknown" in run(srv.confirm("deadbeef"))


def test_preview_scheduled_inline_sequence_two_messages():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.preview_schedule({
        "index": 0, "time": "17:00", "repeat": "daily", "zone": 1,
        "sequence": {"index": 7, "type": "rotate",
                     "colours": [[255, 0, 0], [0, 255, 0]], "title": "RG"},
    }))
    token = out.split('token="')[1].split('"')[0]
    assert srv._pending[token]["messages"].__len__() == 2  # save seq + alarm
    run(srv.confirm(token))


def test_invalid_spec_no_token():
    fresh_controller()
    out = run(srv.preview_sequence({"index": 999, "colours": [[0, 0, 0]]}))
    assert out.startswith("Invalid spec")
    assert srv._pending == {}


def test_get_zone_details_parsed():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.get_zone_details(2))
    assert "'channels_per_light': 3" in out and "'protocol': 1" in out


def test_query_dmx_cache():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.query_dmx_cache(2))
    assert "'levels': [255, 0, 0]" in out
    # line/page reflect the REQUEST, not the firmware's garbage response fields
    assert "'line': 2" in out and "'page': 0" in out


def test_tool_requires_connection():
    fresh_controller()  # not connected
    out = run(srv.get_zone_details(0))
    assert out.startswith("Error")


def test_list_zones():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.list_zones())
    assert "zone 0" in out and "3 channel(s)" in out


def test_list_sequences_keeps_only_populated():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.list_sequences())
    assert "[0] Seq0" in out and "[1] Seq1" in out
    assert "Seq2" not in out  # empty slots (INDEX_OUT_OF_BOUNDS) are skipped


def test_list_themes():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.list_themes())
    assert "[0] Theme0" in out


def test_clear_schedule():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.clear_schedule(2))
    assert "Cleared schedule 2" in out and "SUCCESS" in out
    # a disabled alarm frame for index 2 really went out
    sent = [f for f in srv._controller._client.sent if isinstance(f, bytes)]
    found = False
    for f in sent:
        m = pb.EdidioMessage(); m.ParseFromString(f[3:])
        if m.WhichOneof("payload") == "alarm" and m.alarm.index == 2 and not m.alarm.enabled:
            found = True
    assert found


def test_get_calendar():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.get_calendar())
    assert "day 1: sequence 5" in out


def test_whats_playing():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.whats_playing())
    assert "zone 0: playing sequence 6" in out
    assert "zone 1" not in out  # index 255 = nothing loaded


def test_get_time_reports_and_compares():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.get_time())
    assert "2026-09-07 10:10:26" in out and "Controller time" in out


def test_set_time_default_now():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.set_time())          # defaults to this computer's time -> SUCCESS ack
    assert "Set controller time to" in out and "SUCCESS" in out
    # an admin SET frame really went out
    sent = [f for f in srv._controller._client.sent if isinstance(f, bytes)]
    kinds = []
    for f in sent:
        m = pb.EdidioMessage(); m.ParseFromString(f[3:])
        if m.WhichOneof("payload") == "admin_message":
            kinds.append((m.admin_message.command, m.admin_message.target))
    assert (pb.AdminCommandType.SET, pb.AdminPropertyType.DEVICE_TIME) in kinds


def test_set_time_bad_iso():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    assert run(srv.set_time("not-a-date")).startswith("Could not parse")


def test_whats_scheduled_next():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.whats_scheduled_next())
    assert "sequence 5" in out and "fires in" in out


def test_sequence_fade_preview_and_encoding():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.preview_sequence({"index": 6, "type": "rotate",
                                    "colours": [[255, 0, 0], [0, 255, 0]],
                                    "title": "Fader", "time_per_step_ms": 1500,
                                    "fade_ms": 600}))
    assert "600ms fade" in out
    token = out.split('token="')[1].split('"')[0]
    frame = srv._pending[token]["messages"][0]
    m = pb.EdidioMessage(); m.ParseFromString(frame[3:])
    assert m.spektra_sequence.fade_time_by_10ms == 60  # 600ms / 10


def test_play_sequence_on_zone():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.play_sequence(1, 6))
    assert "Playing sequence 6 on zone 1" in out and "SUCCESS" in out
    # a spektra_control frame really went out
    import edidio_control_py.eDS10_ProtocolBuffer_pb2 as _pb
    sent = [f for f in srv._controller._client.sent if isinstance(f, bytes)]
    kinds = []
    for f in sent:
        m = _pb.EdidioMessage(); m.ParseFromString(f[3:]); kinds.append(m.WhichOneof("payload"))
    assert "spektra_control" in kinds


def test_play_theme_on_zone():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    assert "Applied theme 2 on zone 3" in run(srv.play_theme(3, 2))


def test_stop_zone():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    assert "Stopped zone 1" in run(srv.stop_zone(1))


def test_preview_then_confirm_calendar():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.preview_calendar({"kind": "sequence", "index": 5,
                                    "days": [1, "2026-12-25"]}))
    assert "PREVIEW" in out and "2 day(s)" in out
    token = out.split('token="')[1].split('"')[0]
    assert "Done" in run(srv.confirm(token))
