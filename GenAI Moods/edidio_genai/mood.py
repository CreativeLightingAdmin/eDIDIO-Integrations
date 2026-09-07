"""Tie a prompt -> provider -> palette -> intents together (pure orchestration)."""

from __future__ import annotations

from .palette import (
    SYSTEM_PROMPT,
    build_prompt,
    palette_to_intents,
    parse_palette,
)


def mood_to_intents(description: str, provider, lines: list) -> tuple:
    """Run a mood description through the LLM provider and return
    (palette, intents). `provider` is a callable (system, user) -> str."""
    response = provider(SYSTEM_PROMPT, build_prompt(description))
    palette = parse_palette(response)
    intents = palette_to_intents(palette, lines)
    return palette, intents
