"""LLM providers: turn a prompt into text. Pluggable + injectable for testing.

  * anthropic  — Claude (needs `anthropic` + ANTHROPIC_API_KEY)
  * demo       — a built-in offline palette lookup (no key, for trying it out)

A provider is just a callable ``(system, user) -> str``. The engine only needs
that signature, so tests inject a canned function.
"""

from __future__ import annotations

import os


def demo_provider(system: str, user: str) -> str:
    """Offline provider: naive keyword → palette so the tool works with no API."""
    text = user.lower()
    table = [
        (("autumn", "fall", "cosy", "cozy", "warm"), ["#8C3B0F", "#C86B1A", "#E0A458"]),
        (("ocean", "sea", "calm", "water"), ["#023E58", "#1B6E8C", "#8FD4D9"]),
        (("cyberpunk", "neon", "synthwave"), ["#FF00A0", "#00E5FF", "#7A00FF"]),
        (("forest", "nature", "green"), ["#0B3D2E", "#2E7D32", "#A5D6A7"]),
        (("sunset", "dusk"), ["#FF5E3A", "#FF2A68", "#FFCD3C"]),
        (("fire", "lava", "hot"), ["#7F0000", "#E53935", "#FFB300"]),
    ]
    for keys, palette in table:
        if any(k in text for k in keys):
            return '{"palette": ' + str(palette).replace("'", '"') + "}"
    # default neutral warm-white-ish
    return '{"palette": ["#FFB86B", "#FFD9A0"]}'


def anthropic_provider(system: str, user: str) -> str:
    """Claude provider. Requires `pip install anthropic` and ANTHROPIC_API_KEY."""
    import anthropic  # imported lazily so the package isn't required otherwise

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    model = os.environ.get("EDIDIO_GENAI_MODEL", "claude-sonnet-4-6")
    msg = client.messages.create(
        model=model,
        max_tokens=200,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    # Concatenate text blocks.
    return "".join(getattr(b, "text", "") for b in msg.content)


def get_provider(name: str):
    name = (name or "demo").lower()
    if name == "demo":
        return demo_provider
    if name == "anthropic":
        return anthropic_provider
    raise ValueError(f"unknown provider '{name}' (known: demo, anthropic)")
