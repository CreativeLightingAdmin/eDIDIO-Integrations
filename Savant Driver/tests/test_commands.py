"""Tests for the Savant command payload builder.

Assert the exact bytes against the reference frames (message_id = 7 to match the
shared reference hexes), plus the escaped/hex formatting helpers.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from commands import build_command, to_hex, to_savant_escaped  # noqa: E402

MID = 7

REFERENCE = {
    "arc": "cd000e080792010908011005300048c801",
    "group": "cd000e0807920109080110433000488001",
    "cmd_off": "cd000b0807920106080128004800",
    "bscene": "cd000b0807920106080110502813",
    "gscene": "cd000b0807920106080110442813",
    "dmx": "cd00140807a2010f08ff0110021801200a2a04ff010000",
    "spektra": "cd000b0807da0106080110011802",
    "spektra_stop": "cd000e0807aa01090a07080d100118ff01",
}


def test_dali_level():
    assert build_command("dali_level", mid=MID, line=1, address=5, level=200).hex() == REFERENCE["arc"]


def test_group_level():
    assert build_command("dali_group_level", mid=MID, line=1, group=3, level=128).hex() == REFERENCE["group"]


def test_dali_off():
    assert build_command("dali_off", mid=MID, line=1, address=0).hex() == REFERENCE["cmd_off"]


def test_scene_broadcast():
    assert build_command("dali_scene", mid=MID, line=1, scene=3).hex() == REFERENCE["bscene"]


def test_scene_on_group():
    assert build_command("dali_scene", mid=MID, line=1, scene=3, group=4).hex() == REFERENCE["gscene"]


def test_dmx_color():
    # #FF0000 with 10 fixtures on line 2 (universe mask 2)
    assert build_command("dmx_color", mid=MID, line=2, hex="FF0000", fixtures=10).hex() == REFERENCE["dmx"]


def test_spektra():
    assert build_command("spektra", mid=MID, zone=1, type="sequence", index=2, action="start").hex() == REFERENCE["spektra"]


def test_spektra_stop():
    assert build_command("spektra_stop", mid=MID, zone=1).hex() == REFERENCE["spektra_stop"]


def test_unknown_action():
    import pytest
    with pytest.raises(ValueError):
        build_command("teleport", line=1)


def test_hex_formatting():
    payload = build_command("dali_scene", mid=MID, line=1, scene=3)
    assert to_hex(payload) == "CD 00 0B 08 07 92 01 06 08 01 10 50 28 13"
    assert to_savant_escaped(payload) == "\\xCD\\x00\\x0B\\x08\\x07\\x92\\x01\\x06\\x08\\x01\\x10\\x50\\x28\\x13"
