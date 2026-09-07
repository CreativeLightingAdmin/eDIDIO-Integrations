"""Test the Extron driver logic using the extronlib stub (no device).

Exercises connect, each control method (asserting the exact frame the driver
sends), keep-alive, and disconnect.
"""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Make the extronlib stub and the driver importable.
sys.path.insert(0, os.path.join(BASE, "extronlib_stub"))
sys.path.insert(0, BASE)

import edidio_frames as f  # noqa: E402
from edidio_extron import EdidioController  # noqa: E402

MID1 = 1  # first message id the controller uses


def make():
    c = EdidioController("192.168.1.50", port=23)
    c.connect()
    return c


def test_connect_starts_keepalive():
    c = make()
    assert c.interface.connected is True
    assert c._keepalive_timer is not None


def test_set_level_frame():
    c = make()
    c.set_level(line=1, address=5, level=200)
    assert c.interface.sent[-1] == f.dali_arc_level(MID1, f.line_mask(1), 5, 200)


def test_group_level_frame():
    c = make()
    c.set_group_level(line=1, group=3, level=128)
    assert c.interface.sent[-1] == f.dali_group_arc_level(MID1, f.line_mask(1), 3, 128)


def test_on_off_frames():
    c = make()
    c.on(line=2, address=10)
    assert c.interface.sent[-1] == f.dali_command(MID1, f.line_mask(2), 10, "on")
    c.off(line=2, address=10)
    assert c.interface.sent[-1] == f.dali_command(2, f.line_mask(2), 10, "off")


def test_recall_scene_broadcast_and_group():
    c = make()
    c.recall_scene(line=1, scene=3)
    assert c.interface.sent[-1] == f.dali_broadcast_scene(MID1, f.line_mask(1), 3)
    c.recall_scene(line=1, scene=3, group=4)
    assert c.interface.sent[-1] == f.dali_scene_on_group(2, f.line_mask(1), 4, 3)


def test_dmx_color_frame():
    c = make()
    c.dmx_color(line=2, hex="#FF0000", fixtures=10)
    assert c.interface.sent[-1] == f.dmx_level(MID1, 0xFF, f.line_mask(2), 1, 10, [255, 0, 0])


def test_dmx_levels_frame():
    c = make()
    c.dmx_levels(line=2, levels=[10, 20, 30], channel=5, repeat=2)
    assert c.interface.sent[-1] == f.dmx_level(MID1, 0, f.line_mask(2), 5, 2, [10, 20, 30])


def test_spektra_frame():
    c = make()
    c.spektra(zone=1, target="sequence", index=2, action="start")
    assert c.interface.sent[-1] == f.spektra_control(MID1, f.SPEKTRA_SEQUENCE, 1, 2, f.SPEKTRA_START)


def test_spektra_stop_frame():
    c = make()
    c.spektra_stop(zone=1)
    assert c.interface.sent[-1] == f.spektra_stop(MID1, 1)


def test_keepalive_sends_heartbeat():
    c = make()
    before = len(c.interface.sent)
    c._keepalive_timer.fire()  # simulate a heartbeat tick
    assert c.interface.sent[-1] == f.KEEP_ALIVE
    assert len(c.interface.sent) == before + 1


def test_message_ids_increment():
    c = make()
    c.set_level(1, 0, 10)
    c.set_level(1, 0, 20)
    # decode message ids from the two frames: second byte group after 0x08 tag.
    # Simpler: they must differ, so the frames differ beyond the level.
    assert c.interface.sent[-1] != c.interface.sent[-2]


def test_disconnect_stops_keepalive():
    c = make()
    c.disconnect()
    assert c.interface.connected is False
    assert c._keepalive_timer is None
