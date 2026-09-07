"""Tests for the KSP telemetry -> lighting mapper."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_ksp.mapper import KspMapper  # noqa: E402


def test_throttle_brightness():
    m = KspMapper({"fuel": {"enabled": False}, "throttle": {"line": 1, "group": 0}})
    assert m.process({"throttle": 1.0}) == [{"kind": "dali_group_level", "line": 1, "group": 0, "level": 254}]
    assert m.process({"throttle": 0.5}) == [{"kind": "dali_group_level", "line": 1, "group": 0, "level": 127}]
    # unchanged -> nothing
    assert m.process({"throttle": 0.5}) == []


def test_fuel_gauge():
    m = KspMapper({"throttle": {"enabled": False},
                   "fuel": {"line": 2, "colors": ["#FF0000", "#00FF00"]}})
    assert m.process({"fuel": 1.0}) == [{"kind": "dmx_color", "line": 2, "rgb": [0, 255, 0]}]
    assert m.process({"fuel": 0.0}) == [{"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]}]


def test_abort_edge():
    m = KspMapper({"throttle": {"enabled": False}, "fuel": {"enabled": False},
                   "abort": {"action": {"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]}}})
    m.process({"abort": False})  # prime
    assert m.process({"abort": True}) == [{"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]}]
    assert m.process({"abort": True}) == []  # no repeat


def test_stage_change():
    m = KspMapper({"throttle": {"enabled": False}, "fuel": {"enabled": False},
                   "stage": {"action": {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 0, "action": "START"}}})
    m.process({"stage": 3})  # prime
    out = m.process({"stage": 2})
    assert out and out[0]["kind"] == "spektra"
    assert m.process({"stage": 2}) == []


def test_situation_event():
    m = KspMapper({"throttle": {"enabled": False}, "fuel": {"enabled": False},
                   "situations": {"orbiting": {"kind": "dali_scene", "line": 1, "scene": 5}}})
    assert m.process({"situation": "flying"}) == []      # unmapped
    assert m.process({"situation": "orbiting"}) == [{"kind": "dali_scene", "line": 1, "scene": 5}]
    assert m.process({"situation": "orbiting"}) == []    # no repeat


def test_missing_fields_safe():
    m = KspMapper({})
    assert isinstance(m.process({}), list)
