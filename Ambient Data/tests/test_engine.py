"""Engine tests: dedup + rate-limit + correct dispatch, with fakes."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_ambient.engine import Engine  # noqa: E402
from edidio_ambient.mappings import build_mapping  # noqa: E402


class FakeDispatcher:
    def __init__(self):
        self.intents = []

    def submit(self, intent):
        self.intents.append(intent)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_gradient_dispatches_colour():
    disp = FakeDispatcher()
    clock = FakeClock()
    m = build_mapping({"type": "gradient", "line": 2, "min": 0, "max": 100, "colors": ["#00FF00", "#FF0000"]})
    e = Engine(m, disp, min_interval=1.0, clock=clock)
    e.on_value(0)
    assert disp.intents[-1] == {"kind": "dmx_color", "line": 2, "rgb": [0, 255, 0]}


def test_dedup_skips_identical():
    disp = FakeDispatcher()
    clock = FakeClock()
    m = build_mapping({"type": "threshold", "bands": [
        {"min": 0, "action": {"kind": "dali_scene", "line": 1, "scene": 1}},
        {"min": 50, "action": {"kind": "dali_scene", "line": 1, "scene": 2}},
    ]})
    e = Engine(m, disp, min_interval=0.0, clock=clock)
    e.on_value(10)   # band 1
    e.on_value(20)   # still band 1 -> deduped
    e.on_value(60)   # band 2
    assert [i["scene"] for i in disp.intents] == [1, 2]


def test_rate_limit():
    disp = FakeDispatcher()
    clock = FakeClock()
    m = build_mapping({"type": "gradient", "line": 2, "min": 0, "max": 100, "colors": ["#000000", "#FFFFFF"]})
    e = Engine(m, disp, min_interval=5.0, clock=clock)
    e.on_value(0)     # sent at t=0
    clock.t = 1.0
    e.on_value(50)    # within interval -> dropped
    assert len(disp.intents) == 1
    clock.t = 6.0
    e.on_value(100)   # interval passed -> sent
    assert len(disp.intents) == 2


def test_event_mapping_refires_no_dedup():
    disp = FakeDispatcher()
    m = build_mapping({"type": "event", "events": {
        "safety_car": {"kind": "dmx_color", "line": 2, "rgb": [255, 140, 0]},
    }})
    e = Engine(m, disp, min_interval=0.0, clock=FakeClock())
    e.on_value("safety_car")
    e.on_value("safety_car")  # same event again -> should re-fire (dedup off)
    assert len(disp.intents) == 2


def test_none_intent_skipped():
    disp = FakeDispatcher()
    m = build_mapping({"type": "threshold", "bands": [
        {"min": 50, "action": {"kind": "dali_scene", "line": 1, "scene": 1}},
    ]})
    e = Engine(m, disp, min_interval=0.0, clock=FakeClock())
    e.on_value(10)  # below all bands -> None
    assert disp.intents == []
