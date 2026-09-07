"""AMX Muse driver tests using an injected transport (no socket, no device)."""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import edidio_frames as f  # noqa: E402
from edidio_muse import EdidioController  # noqa: E402

MID1 = 1


class FakeTransport:
    def __init__(self):
        self.sent = []

    def send(self, frame):
        self.sent.append(bytes(frame))


def make():
    t = FakeTransport()
    # keepalive disabled so tests don't spawn timer threads.
    c = EdidioController("192.168.1.50", keepalive_seconds=0, transport=t)
    c.connect()
    return c, t


def test_connect():
    c, _ = make()
    assert c.connected is True


def test_set_level():
    c, t = make()
    c.set_level(1, 5, 200)
    assert t.sent[-1] == f.dali_arc_level(MID1, f.line_mask(1), 5, 200)


def test_group_level():
    c, t = make()
    c.set_group_level(1, 3, 128)
    assert t.sent[-1] == f.dali_group_arc_level(MID1, f.line_mask(1), 3, 128)


def test_on_off():
    c, t = make()
    c.on(2, 10)
    assert t.sent[-1] == f.dali_command(MID1, f.line_mask(2), 10, "on")
    c.off(2, 10)
    assert t.sent[-1] == f.dali_command(2, f.line_mask(2), 10, "off")


def test_scene():
    c, t = make()
    c.recall_scene(1, 3)
    assert t.sent[-1] == f.dali_broadcast_scene(MID1, f.line_mask(1), 3)
    c.recall_scene(1, 3, group=4)
    assert t.sent[-1] == f.dali_scene_on_group(2, f.line_mask(1), 4, 3)


def test_dmx_color():
    c, t = make()
    c.dmx_color(2, "#FF0000", fixtures=10)
    assert t.sent[-1] == f.dmx_level(MID1, 0xFF, f.line_mask(2), 1, 10, [255, 0, 0])


def test_dmx_levels():
    c, t = make()
    c.dmx_levels(2, [10, 20, 30], channel=5, repeat=2)
    assert t.sent[-1] == f.dmx_level(MID1, 0, f.line_mask(2), 5, 2, [10, 20, 30])


def test_spektra():
    c, t = make()
    c.spektra(1, "sequence", 2, "start")
    assert t.sent[-1] == f.spektra_control(MID1, f.SPEKTRA_SEQUENCE, 1, 2, f.SPEKTRA_START)


def test_spektra_stop():
    c, t = make()
    c.spektra_stop(1)
    assert t.sent[-1] == f.spektra_stop(MID1, 1)


def test_keepalive_tick_sends_heartbeat():
    c, t = make()
    c._connected = True
    n = len(t.sent)
    # Call the tick directly (keepalive timer disabled in tests).
    c._keepalive_seconds = 0  # prevent reschedule
    c._keepalive_tick()
    assert t.sent[-1] == f.KEEP_ALIVE
    assert len(t.sent) == n + 1


def test_disconnect():
    c, _ = make()
    c.disconnect()
    assert c.connected is False


def test_real_socket_roundtrip():
    """A real loopback socket proves the socket path actually transmits bytes."""
    import socket
    import threading

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    received = []

    def accept():
        conn, _ = srv.accept()
        data = conn.recv(1024)
        received.append(data)
        conn.close()

    th = threading.Thread(target=accept)
    th.start()

    c = EdidioController("127.0.0.1", port=port, keepalive_seconds=0)
    c.connect()
    c.set_level(1, 5, 200)
    th.join(timeout=2)
    c.disconnect()
    srv.close()

    assert received and received[0] == f.dali_arc_level(MID1, f.line_mask(1), 5, 200)
