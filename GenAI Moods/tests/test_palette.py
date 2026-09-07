"""Tests for palette parsing, mapping, and the mood orchestration (canned LLM)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_genai.mood import mood_to_intents  # noqa: E402
from edidio_genai.palette import (  # noqa: E402
    PaletteError,
    palette_to_intents,
    parse_palette,
)
from edidio_genai.provider import demo_provider  # noqa: E402


# --- parsing (robust to LLM formatting) ---

def test_parse_clean_json():
    assert parse_palette('{"palette": ["#FF0000", "#00FF00"]}') == ["#FF0000", "#00FF00"]


def test_parse_fenced_json():
    text = "Here you go:\n```json\n{\"palette\": [\"#123456\"]}\n```\nEnjoy!"
    assert parse_palette(text) == ["#123456"]


def test_parse_bare_array():
    assert parse_palette('["#abcdef", "#012345"]') == ["#ABCDEF", "#012345"]


def test_parse_scrapes_hex_from_prose():
    text = "I'd suggest a warm #8C3B0F with accents of #E0A458."
    assert parse_palette(text) == ["#8C3B0F", "#E0A458"]


def test_parse_empty_raises():
    with pytest.raises(PaletteError):
        parse_palette("")


def test_parse_no_colours_raises():
    with pytest.raises(PaletteError):
        parse_palette("sorry, I can't help with that")


# --- palette -> intents ---

def test_palette_to_intents_one_line():
    intents = palette_to_intents(["#FF0000", "#00FF00"], [2])
    assert intents == [{"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]}]


def test_palette_to_intents_multi_line_cycles():
    intents = palette_to_intents(["#FF0000", "#00FF00"], [1, 2, 3])
    assert [i["rgb"] for i in intents] == [[255, 0, 0], [0, 255, 0], [255, 0, 0]]


def test_palette_to_intents_no_lines_raises():
    with pytest.raises(PaletteError):
        palette_to_intents(["#FF0000"], [])


# --- end-to-end with the demo provider ---

def test_mood_demo_autumn():
    palette, intents = mood_to_intents("a cosy autumn evening", demo_provider, [2])
    assert palette[0] == "#8C3B0F"
    assert intents[0] == {"kind": "dmx_color", "line": 2, "rgb": [140, 59, 15]}


def test_mood_demo_cyberpunk_multi_line():
    palette, intents = mood_to_intents("cyberpunk neon city", demo_provider, [1, 2])
    assert len(intents) == 2
    assert intents[0]["kind"] == "dmx_color"


def test_mood_with_injected_provider():
    fake = lambda system, user: '{"palette": ["#010203"]}'  # noqa: E731
    palette, intents = mood_to_intents("anything", fake, [4])
    assert palette == ["#010203"]
    assert intents == [{"kind": "dmx_color", "line": 4, "rgb": [1, 2, 3]}]
