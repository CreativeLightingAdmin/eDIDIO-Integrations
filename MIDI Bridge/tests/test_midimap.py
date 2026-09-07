"""Unit tests for the MIDI map (event + value -> intent) and the mido decoder."""

import os
import sys

import mido
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_midi.bridge import decode  # noqa: E402
from edidio_midi.midimap import (  # noqa: E402
    Binding,
    ConfigError,
    build_midi_map,
    midi_to_arc,
)


def test_midi_to_arc():
    assert midi_to_arc(127) == 254
    assert midi_to_arc(0) == 0
    assert midi_to_arc(64) == 128  # round(64*254/127)


def test_note_scene_trigger():
    b = Binding({"event": "note:0:60", "action": "dali_scene", "line": 1, "scene": 3})
    assert b.intent(100) == {"kind": "dali_scene", "line": 1, "scene": 3}
    assert b.intent(0) is None  # note-off / release does not re-fire


def test_cc_level():
    b = Binding({"event": "cc:0:7", "action": "dali_group_level", "line": 1, "group": 0})
    assert b.intent(127) == {"kind": "dali_group_level", "line": 1, "group": 0, "level": 254}
    assert b.intent(0) == {"kind": "dali_group_level", "line": 1, "group": 0, "level": 0}


def test_address_level():
    b = Binding({"event": "cc:0:8", "action": "dali_level", "line": 1, "address": 5})
    assert b.intent(64) == {"kind": "dali_level", "line": 1, "address": 5, "level": 128}


def test_scene_on_group():
    b = Binding({"event": "note:0:60", "action": "dali_scene", "line": 1, "scene": 1, "group": 4})
    assert b.intent(1) == {"kind": "dali_scene", "line": 1, "scene": 1, "group": 4}


def test_spektra():
    b = Binding({"event": "note:0:62", "action": "spektra", "zone": 1, "index": 2})
    assert b.intent(100) == {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 2, "action": "START"}
    assert b.intent(0) is None


# --- mido decoding ---

def test_decode_note_on():
    key, value = decode(mido.Message("note_on", channel=0, note=60, velocity=100))
    assert key == "note:0:60"
    assert value == 100


def test_decode_note_off_maps_to_note_key_value_zero():
    key, value = decode(mido.Message("note_off", channel=0, note=60, velocity=0))
    assert key == "note:0:60"
    assert value == 0


def test_decode_cc():
    key, value = decode(mido.Message("control_change", channel=0, control=7, value=64))
    assert key == "cc:0:7"
    assert value == 64


def test_decode_program_change_is_trigger():
    key, value = decode(mido.Message("program_change", channel=0, program=5))
    assert key == "pc:0:5"
    assert value == 1


def test_decode_unhandled():
    key, value = decode(mido.Message("pitchwheel", channel=0, pitch=0))
    assert key is None


# --- validation ---

def test_invalid_event():
    with pytest.raises(ConfigError):
        Binding({"event": "bad", "action": "dali_scene", "line": 1, "scene": 1})


def test_unknown_action():
    with pytest.raises(ConfigError):
        Binding({"event": "note:0:60", "action": "nope", "line": 1})


def test_duplicate_binding():
    with pytest.raises(ConfigError):
        build_midi_map([
            {"event": "note:0:60", "action": "dali_scene", "line": 1, "scene": 1},
            {"event": "note:0:60", "action": "dali_scene", "line": 1, "scene": 2},
        ])
