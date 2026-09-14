"""Tests for the live event stream: register message, decoding, buffering."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb  # noqa: E402

from edidio_spektra_ai import event_stream as es  # noqa: E402


def _decode_frame(frame):
    assert frame[0] == 0xCD
    m = pb.EdidioMessage()
    m.ParseFromString(frame[3:])
    return m


def test_build_register_sets_filter_fields():
    frame = es.build_register_message(1, ["inputs", "sensors", "triggers"])
    m = _decode_frame(frame)
    assert m.event.event == pb.EventType.REGISTER
    f = m.event.filter
    assert f.input and f.dali_sensor and f.trigger_message
    assert not f.dmx_stream_changed


def test_decode_sensor_event():
    ev = pb.EventMessage(event=pb.EventType.SENSOR_EVENT,
                         sensor=pb.DALISensorEvent(index=2, line=1, address=5,
                                                   motion_state=3, lux_level=120))
    d = es.decode_event(ev)
    assert d["kind"] == "sensor" and d["index"] == 2
    assert d["motion"] == "MOTION_OCCUPANCY" and d["lux_level"] == 120


def test_decode_trigger_event():
    ev = pb.EventMessage(event=pb.EventType.TRIGGER_EVENT,
                         trigger=pb.TriggerEvent(type=pb.TriggerType.SPEKTRA_START_SEQ,
                                                 zone=1, line_mask=2, target_address=3,
                                                 value=254))
    d = es.decode_event(ev)
    assert d["kind"] == "trigger" and d["type"] == "SPEKTRA_START_SEQ"
    assert d["zone"] == 1 and d["target"] == 3


# --- a fake client that feeds pre-canned frames into the read loop ---

class _FakeClient:
    def __init__(self, frames):
        self._frames = list(frames)
        self.sent = []
        self.connected = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def send_protobuf_message(self, frame):
        self.sent.append(frame)

    async def _receive_framed(self):
        # Mirrors the real client: returns the message BODY (header already stripped).
        if self._frames:
            return self._frames.pop(0)
        await asyncio.sleep(3600)  # block until cancelled once drained


def _event_body(ev):
    return pb.EdidioMessage(message_id=1, event=ev).SerializeToString()


def test_stream_buffers_and_polls_events():
    async def run():
        ack = pb.EdidioMessage(
            message_id=1, ack=pb.AckMessage(payload=pb.AckMessageType.SUCCESS)
        ).SerializeToString()
        s1 = _event_body(pb.EventMessage(event=pb.EventType.SENSOR_EVENT,
                                         sensor=pb.DALISensorEvent(index=0, motion_state=3)))
        s2 = _event_body(pb.EventMessage(event=pb.EventType.INPUT_EVENT,
                                         inputs=pb.InputStateResponse(input_mask=4)))
        frames = [ack, s1, s2]
        stream = es.EventStream("x", client_factory=lambda: _FakeClient(frames),
                                use_v2=False)  # this test feeds legacy EventMessage frames
        await stream.start(["inputs", "sensors"])
        for _ in range(50):
            await asyncio.sleep(0.01)
            if stream.last_seq >= 2:
                break
        evs = stream.recent()
        assert len(evs) == 2
        assert evs[0]["kind"] == "sensor" and evs[1]["kind"] == "input"
        # since_seq filtering
        assert len(stream.recent(since_seq=1)) == 1
        assert stream.recent(since_seq=1)[0]["seq"] == 2
        await stream.stop()
        assert not stream.running
    asyncio.run(run())


def test_recent_before_start_is_empty():
    s = es.EventStream("x", client_factory=lambda: _FakeClient([]))
    assert s.recent() == [] and s.last_seq == 0 and not s.running
