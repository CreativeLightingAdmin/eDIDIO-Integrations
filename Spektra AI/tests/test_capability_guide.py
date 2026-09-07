"""The generated capability guide must contain the key messages, enums, limits."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_spektra_ai.capability_guide import build_guide  # noqa: E402


def test_guide_has_core_content():
    g = build_guide()
    # messages
    assert "SpektraSequenceConfigMessage" in g
    assert "SpektraThemeConfigMessage" in g
    assert "AlarmMessage" in g
    # animation types incl. rotate
    assert "ROTATE" in g
    # enums / triggers
    assert "SPEKTRA_START_SEQ" in g
    assert "ALARM_REPEAT_DAILY" in g
    assert "BLEND" in g and "SNAP" in g
    # limits + safety
    assert "0-143" in g
    assert "50 ms" in g or "50ms" in g
    assert "confirm(" in g
    # no fancy unicode dashes leaked through the normaliser
    assert "—" not in g and "–" not in g
    # authoring how-to
    assert "create_sequence" in g and "create_schedule" in g


def test_guide_field_numbers_from_descriptors():
    # field#number formatting proves it's generated from the live descriptors.
    g = build_guide()
    assert "index#1" in g
    assert "colours#17" in g          # sequence colours field
    assert "start_trigger#5" in g     # alarm start_trigger field
