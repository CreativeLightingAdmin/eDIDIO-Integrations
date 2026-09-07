"""Prompt building + palette parsing + palette → eDIDIO intents.

Pure (no network / SDK), so it is fully unit tested with canned LLM output. The
LLM is asked to return strict JSON: a list of hex colours. We parse it robustly
(tolerating code fences / surrounding prose) and map the colours onto DMX lines.
"""

from __future__ import annotations

import json
import re

SYSTEM_PROMPT = (
    "You are a lighting designer. Given a mood or scene description, respond with "
    "ONLY a JSON object of the form {\"palette\": [\"#RRGGBB\", ...]} containing 1 to "
    "6 colours that best evoke it. No prose, no explanation, just the JSON."
)


class PaletteError(ValueError):
    pass


def build_prompt(description: str) -> str:
    return f"Mood/scene: {description}\nReturn the JSON palette."


_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")


def parse_palette(text: str) -> list:
    """Extract a list of #RRGGBB colours from an LLM response.

    Tries JSON first (optionally inside ``` fences / surrounding text); falls back
    to scraping hex codes. Returns a list of "#RRGGBB" strings.
    """
    if not text or not text.strip():
        raise PaletteError("empty LLM response")

    # 1) Try to find a JSON object with a "palette" array.
    for candidate in _json_candidates(text):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("palette"), list):
            colors = [c for c in obj["palette"] if isinstance(c, str) and _HEX_RE.fullmatch(c.strip())]
            if colors:
                return [c.strip().upper() for c in colors]
        if isinstance(obj, list):
            colors = [c for c in obj if isinstance(c, str) and _HEX_RE.fullmatch(c.strip())]
            if colors:
                return [c.strip().upper() for c in colors]

    # 2) Fallback: scrape any hex codes in the text.
    found = _HEX_RE.findall(text)
    if found:
        return [c.upper() for c in found]

    raise PaletteError("no colours found in LLM response")


def _json_candidates(text: str):
    """Yield plausible JSON substrings (fenced blocks, then the first {...}/[...])."""
    for m in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.DOTALL):
        yield m.group(1).strip()
    # first {...}
    b = text.find("{")
    e = text.rfind("}")
    if b != -1 and e > b:
        yield text[b:e + 1]
    # first [...]
    b = text.find("[")
    e = text.rfind("]")
    if b != -1 and e > b:
        yield text[b:e + 1]
    yield text.strip()


def _hex_to_rgb(value: str):
    text = value.lstrip("#")
    return [int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)]


def palette_to_intents(palette: list, lines: list) -> list:
    """Distribute palette colours across DMX `lines` → dmx_color intents.

    If there are more lines than colours, colours repeat; more colours than lines,
    extra colours are dropped (the first N colours paint the N lines).
    """
    if not palette:
        return []
    if not lines:
        raise PaletteError("no output lines configured")
    intents = []
    for i, line in enumerate(lines):
        color = palette[i % len(palette)]
        intents.append({"kind": "dmx_color", "line": int(line), "rgb": _hex_to_rgb(color)})
    return intents
