"""MIDI bridge tests: feed real mido messages through the bridge and assert the
correct eDIDIO intents are dispatched (fake dispatcher; no MIDI port, no eDIDIO).

These use genuine ``mido.Message`` objects — the same objects a real input port
delivers to the callback — so the decode→map→dispatch path is fully exercised.
(A true OS-level loopback needs a virtual MIDI port, which Windows lacks natively;
loopMIDI enables it for manual live testing — see the README.)
"""

import os
import sys

import mido

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_midi.bridge import MidiBridge  # noqa: E402
from edidio_midi.config import BridgeConfig  # noqa: E402


class FakeDispatcher:
    def __init__(self):
        self.intents = []

    def submit(self, intent):
        self.intents.append(intent)


RAW = {
    "midi": {},
    "controller": {"host": "10.0.0.1", "port": 23},
    "bindings": [
        {"event": "note:0:60", "action": "dali_scene", "line": 1, "scene": 3},
        {"event": "cc:0:7", "action": "dali_group_level", "line": 1, "group": 0},
        {"event": "cc:0:8", "action": "dali_level", "line": 1, "address": 5},
        {"event": "note:0:62", "action": "spektra", "zone": 1, "index": 0},
    ],
}


def make():
    cfg = BridgeConfig(RAW)
    disp = FakeDispatcher()
    return MidiBridge(cfg, disp), disp


def test_note_triggers_scene():
    bridge, disp = make()
    bridge.handle(mido.Message("note_on", channel=0, note=60, velocity=100))
    assert disp.intents[-1] == {"kind": "dali_scene", "line": 1, "scene": 3}


def test_note_off_does_not_refire():
    bridge, disp = make()
    bridge.handle(mido.Message("note_off", channel=0, note=60, velocity=0))
    assert disp.intents == []


def test_fader_sets_group_level():
    bridge, disp = make()
    bridge.handle(mido.Message("control_change", channel=0, control=7, value=127))
    assert disp.intents[-1] == {"kind": "dali_group_level", "line": 1, "group": 0, "level": 254}


def test_fader_sets_address_level():
    bridge, disp = make()
    bridge.handle(mido.Message("control_change", channel=0, control=8, value=64))
    assert disp.intents[-1] == {"kind": "dali_level", "line": 1, "address": 5, "level": 128}


def test_note_starts_spektra():
    bridge, disp = make()
    bridge.handle(mido.Message("note_on", channel=0, note=62, velocity=100))
    assert disp.intents[-1] == {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 0, "action": "START"}


def test_unmapped_note_ignored():
    bridge, disp = make()
    bridge.handle(mido.Message("note_on", channel=0, note=99, velocity=100))
    assert disp.intents == []


def test_sequence_of_messages():
    """A short performance: blackout, fade up, effect."""
    bridge, disp = make()
    for msg in [
        mido.Message("note_on", channel=0, note=60, velocity=100),
        mido.Message("control_change", channel=0, control=7, value=100),
        mido.Message("note_on", channel=0, note=62, velocity=127),
    ]:
        bridge.handle(msg)
    kinds = [i["kind"] for i in disp.intents]
    assert kinds == ["dali_scene", "dali_group_level", "spektra"]
