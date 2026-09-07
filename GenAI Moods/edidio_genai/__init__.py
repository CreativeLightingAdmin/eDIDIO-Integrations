"""eDIDIO Generative AI Moods.

Turn a natural-language (or image) prompt into a lighting scene: an LLM returns a
colour palette, which is pushed to eDIDIO as DMX colours. *"cosy autumn evening"*,
*"cyberpunk neon"*, *"calm ocean"* → the room becomes it.

The LLM call is abstracted behind a provider function, so the palette parsing and
mapping are fully testable with canned responses (no API key, no network).
"""

__version__ = "1.0.0"
