"""Engine: wires a source to a mapping to the dispatcher.

On each value from the source it computes an intent via the mapping, then applies
two guards before dispatching so it never floods the DALI/DMX bus:

  * de-dup    — skip an intent identical to the last one sent (so threshold
                mappings 'fire on change', and a steady gradient doesn't repeat).
  * rate-limit — enforce a minimum interval between sends.

The dispatcher and mapping are injected, so the engine is unit tested with fakes.
"""

from __future__ import annotations

import logging
import time

_LOGGER = logging.getLogger(__name__)


class Engine:
    def __init__(self, mapping, dispatcher, *, min_interval=0.5, clock=time.monotonic):
        self.mapping = mapping
        self.dispatcher = dispatcher
        self.min_interval = float(min_interval)
        self._clock = clock
        self._last_intent = None
        self._last_sent = None

    def on_value(self, value):
        """Called for each source value. Returns the intent dispatched, or None."""
        intent = self.mapping.intent(value)
        if intent is None:
            return None
        if getattr(self.mapping, "dedup", True) and intent == self._last_intent:
            return None  # de-dup (skipped for event mappings)
        now = self._clock()
        if self._last_sent is not None and (now - self._last_sent) < self.min_interval:
            return None  # rate-limited
        self._last_intent = intent
        self._last_sent = now
        self.dispatcher.submit(intent)
        _LOGGER.info("%s -> %s", value, intent.get("kind"))
        return intent
