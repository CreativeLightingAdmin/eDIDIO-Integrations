"""Assert the NetLinx algorithm mirror produces the known-good reference frames.

If these pass, the byte math transcribed into eDIDIO.axi is correct.
Reference hexes captured from edidio_control_py 0.3.0 (message_id=7).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _netlinx_mirror as m  # noqa: E402

MID = 7

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


def test_arc():
    assert m.dali_arc_level(MID, 1, 5, 200).hex() == REFERENCE["arc"]


def test_group():
    assert m.dali_group_arc_level(MID, 1, 3, 128).hex() == REFERENCE["group"]


def test_cmd():
    assert m.dali_command(MID, 2, 10, 5).hex() == REFERENCE["cmd"]


def test_cmd_off():
    assert m.dali_command(MID, 1, 0, 0).hex() == REFERENCE["cmd_off"]


def test_bscene():
    assert m.dali_broadcast_scene(MID, 1, 3).hex() == REFERENCE["bscene"]


def test_gscene():
    assert m.dali_scene_on_group(MID, 1, 4, 3).hex() == REFERENCE["gscene"]


def test_dmx():
    assert m.dmx_level(MID, 255, 2, 1, 10, [255, 0, 0]).hex() == REFERENCE["dmx"]


def test_dmx_fade():
    assert m.dmx_level(MID, 0, 1, 1, 1, [10, 20, 30], fade=50).hex() == REFERENCE["dmx_fade"]


def test_spektra():
    assert m.spektra_control(MID, 1, 1, 2, 0).hex() == REFERENCE["spektra"]


def test_spektra_stop():
    assert m.spektra_stop(MID, 1, 0xFF).hex() == REFERENCE["spektra_stop"]
