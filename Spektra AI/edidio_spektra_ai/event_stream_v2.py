"""Event Stream v2 (firmware >= 1.4.0) — now provided by ``edidio_control_py.events``.

Kept as Spektra AI's historical names for the v2 encode/decode helpers.
"""

from edidio_control_py.events import (  # noqa: F401
    ALL_CATEGORIES_MASK,
    CATEGORY_BITS,
    DEFAULT_LEVEL_THRESHOLD,
    build_subscribe,
    build_unsubscribe,
    categories_to_mask,
    describe_dali_frame,
    is_event_stream,
)
from edidio_control_py.events import decode_v2 as decode  # noqa: F401
from edidio_control_py.events import parse_v2 as parse_edidio  # noqa: F401
