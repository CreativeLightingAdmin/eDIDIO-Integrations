"""Tests for the added sources (iss, countdown, f1, webhook) and event mapping."""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_ambient.mappings import build_mapping  # noqa: E402
from edidio_ambient.sources.countdown import CountdownSource, parse_iso  # noqa: E402
from edidio_ambient.sources.f1 import F1RaceControlSource, label_for  # noqa: E402
from edidio_ambient.sources.iss import IssOverheadSource, haversine_km  # noqa: E402
from edidio_ambient.sources.webhook import extract_emission  # noqa: E402


# --- ISS ---

def test_haversine_known_distance():
    # London to Paris ~344 km.
    d = haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
    assert 330 < d < 360


def test_iss_proximity_far_and_near():
    home = {"type": "iss_overhead", "lat": 51.5, "lon": -0.13, "radius_km": 500}
    # ISS on the far side of the planet -> proximity 0.
    far = IssOverheadSource(home, fetch_fn=lambda: {"iss_position": {"latitude": -40, "longitude": 170}})
    assert far.read_once() == 0.0
    # ISS right overhead -> proximity ~ radius.
    near = IssOverheadSource(home, fetch_fn=lambda: {"iss_position": {"latitude": 51.5, "longitude": -0.13}})
    assert near.read_once() > 490


# --- countdown ---

def test_parse_iso_z():
    dt = parse_iso("2030-01-01T12:00:00Z")
    assert dt.tzinfo is not None


def test_countdown_intensity_rises():
    now = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    cfg = {"type": "countdown", "url": "http://x", "json_path": "net", "window_s": 120}
    # T-90s -> outside... actually within 120 window: intensity = 120 - 90 = 30
    src = CountdownSource(cfg,
                          fetch_fn=lambda: {"net": (now + timedelta(seconds=90)).isoformat()},
                          clock=lambda: now)
    assert src.read_once() == 30.0
    # T-10s -> intensity 110
    src2 = CountdownSource(cfg,
                           fetch_fn=lambda: {"net": (now + timedelta(seconds=10)).isoformat()},
                           clock=lambda: now)
    assert src2.read_once() == 110.0
    # Far out (T-1h) -> clamped to 0
    src3 = CountdownSource(cfg,
                           fetch_fn=lambda: {"net": (now + timedelta(hours=1)).isoformat()},
                           clock=lambda: now)
    assert src3.read_once() == 0.0


# --- F1 ---

def test_f1_label_derivation():
    assert label_for({"category": "SafetyCar", "message": "SAFETY CAR DEPLOYED"}) == "safety_car"
    assert label_for({"category": "SafetyCar", "message": "VIRTUAL SAFETY CAR DEPLOYED"}) == "virtual_safety_car"
    assert label_for({"flag": "YELLOW"}) == "yellow"
    assert label_for({"flag": "DOUBLE YELLOW"}) == "double_yellow"
    assert label_for({"flag": "CHEQUERED"}) == "chequered"
    assert label_for({"category": "Drs"}) is None


def test_f1_emits_only_new_messages():
    history = [{"date": "t1", "flag": "GREEN"}]
    src = F1RaceControlSource({"type": "f1_racecontrol"}, fetch_fn=lambda: list(history))
    # First poll primes history, emits nothing (don't replay the race so far).
    assert src.poll() == []
    # A new safety-car message appears.
    history.append({"date": "t2", "category": "SafetyCar", "message": "SAFETY CAR DEPLOYED"})
    assert src.poll() == ["safety_car"]
    # No change -> nothing.
    assert src.poll() == []


# --- webhook extraction ---

def test_webhook_numeric_extraction():
    assert extract_emission({"metric": {"value": 42.5}}, "metric.value", None) == 42.5


def test_webhook_label_extraction():
    assert extract_emission({"event": "combat_start"}, None, "event") == "combat_start"


def test_webhook_bare_trigger():
    assert extract_emission({}, None, None) == 1.0


# --- event mapping ---

def test_event_mapping():
    m = build_mapping({"type": "event", "events": {
        "safety_car": {"kind": "dmx_color", "line": 2, "rgb": [255, 140, 0]},
        "green": {"kind": "dali_scene", "line": 1, "scene": 1},
    }})
    assert m.dedup is False
    assert m.intent("safety_car") == {"kind": "dmx_color", "line": 2, "rgb": [255, 140, 0]}
    assert m.intent("green") == {"kind": "dali_scene", "line": 1, "scene": 1}
    assert m.intent("unknown") is None
