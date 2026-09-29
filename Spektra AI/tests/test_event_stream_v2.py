"""Tests for Event Stream v2 (EventStreamMessage / tag 77) encode + decode."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_spektra_ai import event_stream as esmod
from edidio_spektra_ai import event_stream_v2 as v2
from edidio_control_py._v2 import eDS10_v2_pb2 as pb2


def test_categories_to_mask_includes_event_bit():
    m = v2.categories_to_mask(["dali", "inputs"])
    assert m & (1 << 3) and m & (1 << 2) and m & (1 << 10)


def test_categories_empty_is_all():
    assert v2.categories_to_mask([]) == v2.ALL_CATEGORIES_MASK


def test_describe_dali_frame_min_max():
    assert v2.describe_dali_frame(0xFF06, 4, 1) == "broadcast MIN_LEVEL"   # RX 16-bit
    assert v2.describe_dali_frame(0xFF05, 1) == "broadcast MAX_LEVEL"      # TX 16-bit


def test_build_subscribe_roundtrips():
    frame = v2.build_subscribe(category_mask=0x7FF, level_threshold=2)
    assert frame[0] == 0xCD
    m = pb2.EdidioMessage()
    m.ParseFromString(frame[3:])
    assert m.event_stream.subscribe is True
    assert m.event_stream.category_mask == 0x7FF and m.event_stream.level_threshold == 2


def test_decode_dali_event():
    msg = pb2.EdidioMessage(event_stream=pb2.EventStreamMessage(
        sequence=42, category=3,
        dali=pb2.DaliFrame(line=1, direction=1, frame_type=4, status=16, frame=0xFF06)))
    d = v2.decode(msg)
    assert d["kind"] == "dali" and d["frame"] == 0xFF06
    assert d["decoded"] == "broadcast MIN_LEVEL" and d["seq"] == 42


def test_decode_ack_returns_none():
    msg = pb2.EdidioMessage(event_stream=pb2.EventStreamMessage(ack=True))
    assert v2.decode(msg) is None


class _FakeV2Client:
    """Feeds pre-canned v2 frame bodies into the read loop (header already stripped)."""

    def __init__(self, bodies):
        self._bodies = list(bodies)

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def send_protobuf_message(self, frame):
        pass

    async def _receive_framed(self):
        if self._bodies:
            return self._bodies.pop(0)
        await asyncio.sleep(3600)


def _body(es_msg):
    return pb2.EdidioMessage(event_stream=es_msg).SerializeToString()


def test_stream_buffers_v2_events():
    async def run():
        bodies = [
            _body(pb2.EventStreamMessage(ack=True)),                       # skipped
            _body(pb2.EventStreamMessage(sequence=1, category=3,
                  dali=pb2.DaliFrame(frame=0xFF05, frame_type=4, direction=1))),
            _body(pb2.EventStreamMessage(sequence=2, category=10,
                  input=pb2.InputEvent(input_index=3, press_type=1))),
        ]
        stream = esmod.EventStream("x", client_factory=lambda: _FakeV2Client(bodies),
                                   use_v2=True)
        await stream.start(["dali", "inputs"])
        for _ in range(50):
            await asyncio.sleep(0.01)
            if stream.last_seq >= 2:
                break
        evs = stream.recent()
        assert [e["kind"] for e in evs] == ["dali", "input"]
        assert evs[0]["decoded"] == "broadcast MAX_LEVEL"
        await stream.stop()

    asyncio.run(run())
