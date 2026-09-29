"""Live event stream — now provided by ``edidio_control_py.events`` (0.5.0).

The engine owns the dedicated push connection, v2/legacy subscribe, decoding and
reconnect/resubscribe. This module keeps Spektra AI's historical names.
"""

from edidio_control_py.events import (  # noqa: F401
    DEFAULT_CATEGORIES,
    EventStream,
)
from edidio_control_py.events import LEGACY_CATEGORY_FIELDS as CATEGORY_FIELDS  # noqa: F401
from edidio_control_py.events import build_legacy_register as build_register_message  # noqa: F401
from edidio_control_py.events import decode_legacy as decode_event  # noqa: F401
