"""Verify the pure-Python encoder produces byte-identical frames.

Two independent oracles:
  1. Hardcoded reference hex strings captured from edidio_control_py.
  2. A live comparison against edidio_control_py itself, when it is importable.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edidio_frames as f  # noqa: E402

MID = 7

# Reference frames captured from edidio_control_py 0.3.0 (message_id=7).
REFERENCE = {
    "arc": "cd000e080792010908011005300048c801",
    "group": "cd000e0807920109080110433000488001",
    "cmd": "cd000d08079201080802100a28054800",
    "cmd_off": "cd000b0807920106080128004800",
    "bscene": "cd000b0807920106080110502813",
    "gscene": "cd000b0807920106080110442813",
    "dmx": "cd00140807a2010f08ff0110021801200a2a04ff010000",
    "dmx_fade": "cd00120807a2010d1001180120012a030a141e3032",
    "spektra": "cd000b0807da0106080110011802",
    "spektra_stop": "cd000e0807aa01090a07080d100118ff01",
}


def h(frame):
    return frame.hex()


def test_arc_level():
    assert h(f.dali_arc_level(MID, 1, 5, 200)) == REFERENCE["arc"]


def test_group_arc_level():
    assert h(f.dali_group_arc_level(MID, 1, 3, 128)) == REFERENCE["group"]


def test_command_max():
    assert h(f.dali_command(MID, 2, 10, f.DALI_MAX_LEVEL)) == REFERENCE["cmd"]


def test_command_off_named():
    assert h(f.dali_command(MID, 1, 0, "off")) == REFERENCE["cmd_off"]


def test_broadcast_scene():
    assert h(f.dali_broadcast_scene(MID, 1, 3)) == REFERENCE["bscene"]


def test_scene_on_group():
    assert h(f.dali_scene_on_group(MID, 1, 4, 3)) == REFERENCE["gscene"]


def test_dmx():
    assert h(f.dmx_level(MID, 255, 2, 1, 10, [255, 0, 0])) == REFERENCE["dmx"]


def test_dmx_fade():
    assert h(f.dmx_level(MID, 0, 1, 1, 1, [10, 20, 30], fade_time_by_10ms=50)) == REFERENCE["dmx_fade"]


def test_spektra_control():
    assert h(f.spektra_control(MID, f.SPEKTRA_SEQUENCE, 1, 2, f.SPEKTRA_START)) == REFERENCE["spektra"]


def test_spektra_stop():
    assert h(f.spektra_stop(MID, 1, 0xFF)) == REFERENCE["spektra_stop"]


def test_arc_level_clamps():
    # level clamped to 254; frame must still be valid and match a 254 arg.
    assert f.dali_arc_level(MID, 1, 5, 999) == f.dali_arc_level(MID, 1, 5, 254)


def test_line_mask():
    assert f.line_mask(1) == 1
    assert f.line_mask(4) == 8


# --- Live comparison against edidio_control_py, if available ---

edidio = pytest.importorskip("edidio_control_py")
pb = pytest.importorskip("edidio_control_py.eDS10_ProtocolBuffer_pb2")


def test_matches_library_arc():
    lib = edidio.EdidioClient.create_dali_message(
        MID, line_mask=1, address=5, custom_command=pb.CustomDALICommandType.DALI_ARC_LEVEL, arg=[200]
    )
    assert f.dali_arc_level(MID, 1, 5, 200) == lib


def test_matches_library_dmx():
    lib = edidio.EdidioClient.create_dmx_message(
        MID, zone=255, universe_mask=2, channel=1, repeat=10, level=[255, 0, 0]
    )
    assert f.dmx_level(MID, 255, 2, 1, 10, [255, 0, 0]) == lib


def test_matches_library_spektra():
    lib = edidio.EdidioClient.create_spektra_control_message(
        MID, pb.SpektraTargetType.SEQUENCE, 1, 2, pb.SpektraActionType.START
    )
    assert f.spektra_control(MID, f.SPEKTRA_SEQUENCE, 1, 2, f.SPEKTRA_START) == lib


def test_matches_library_spektra_stop():
    lib = edidio.EdidioClient.create_spektra_stop_message(MID, zone=1, line_mask=0xFF)
    assert f.spektra_stop(MID, 1, 0xFF) == lib
