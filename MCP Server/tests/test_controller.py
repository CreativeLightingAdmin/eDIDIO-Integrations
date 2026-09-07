"""Verify the MCP controller wrapper maps to the right EdidioClient calls,
using a fake client that records calls (no network, no hardware)."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_control_py import DALICommandType, SpektraActionType, SpektraTargetType  # noqa: E402

from edidio_mcp.controller import EdidioController, line_mask  # noqa: E402


class FakeClient:
    def __init__(self):
        self.calls = []
        self.connected = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    def _rec(self, name):
        async def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return method

    def __getattr__(self, name):
        # Any client method call is recorded.
        if name.startswith("set_dali") or name.startswith("send_") or name.startswith("recall_") or name.startswith("set_dmx"):
            return self._rec(name)
        raise AttributeError(name)


def controller():
    return EdidioController("10.0.0.1", client=FakeClient())


def run(coro):
    return asyncio.run(coro)


def test_line_mask():
    assert line_mask(1) == 1
    assert line_mask(4) == 8


def test_set_level():
    c = controller()
    run(c.set_level(1, 5, 200))
    name, args, _ = c._client.calls[-1]
    assert name == "set_dali_arc_level"
    # (message_id, line_mask, address, level)
    assert args[1:] == (line_mask(1), 5, 200)


def test_set_level_clamps():
    c = controller()
    run(c.set_level(1, 5, 999))
    assert c._client.calls[-1][1][3] == 254


def test_group_level():
    c = controller()
    run(c.set_group_level(1, 3, 128))
    name, args, _ = c._client.calls[-1]
    assert name == "set_dali_group_arc_level"
    assert args[1:] == (line_mask(1), 3, 128)


def test_on_off():
    c = controller()
    run(c.turn_on(2, 10))
    name, args, _ = c._client.calls[-1]
    assert name == "send_dali_command"
    assert args[1:] == (line_mask(2), 10, DALICommandType.DALI_MAX_LEVEL)
    run(c.turn_off(2, 10))
    assert c._client.calls[-1][1][3] == DALICommandType.DALI_OFF


def test_recall_scene_broadcast_and_group():
    c = controller()
    run(c.recall_scene(1, 3))
    name, args, _ = c._client.calls[-1]
    assert name == "recall_dali_scene"
    assert args[1:] == (line_mask(1), 3)
    run(c.recall_scene(1, 3, group=4))
    name, args, _ = c._client.calls[-1]
    assert name == "recall_dali_scene_on_group"
    assert args[1:] == (line_mask(1), 4, 3)


def test_dmx_color():
    import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb

    c = controller()
    run(c.dmx_color(2, "#FF0000", fixtures=2))
    name, args, _ = c._client.calls[-1]
    # Now sends a framed DMX message via send_protobuf_message, using the DMX
    # `repeat` field to fill the universe with a small frame (avoids the
    # controller's large-frame drop).
    assert name == "send_protobuf_message"
    m = pb.EdidioMessage()
    m.ParseFromString(bytes(args[0])[3:])
    dmx = m.dmx_message
    assert dmx.zone == 0xFF
    assert dmx.universe_mask == line_mask(2)
    assert dmx.channel == 1
    assert dmx.repeat == 2
    assert list(dmx.level) == [255, 0, 0]


def test_spektra():
    c = controller()
    run(c.spektra(1, "sequence", 2, "start"))
    name, args, _ = c._client.calls[-1]
    assert name == "send_spektra_control"
    assert args[1] == SpektraTargetType.SEQUENCE
    assert args[2:] == (1, 2, SpektraActionType.START)


def test_spektra_stop():
    c = controller()
    run(c.spektra_stop(1))
    name, args, _ = c._client.calls[-1]
    assert name == "send_spektra_stop"
    assert args[1] == 1


def test_message_ids_increment():
    c = controller()
    run(c.set_level(1, 0, 10))
    run(c.set_level(1, 0, 10))
    assert c._client.calls[0][1][0] != c._client.calls[1][1][0]


def test_connect_disconnect():
    c = controller()
    run(c.connect())
    assert c.connected
    run(c.disconnect())
    assert not c.connected
