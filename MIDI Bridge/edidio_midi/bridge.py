"""Transport-agnostic MIDI routing.

Decodes a mido message to (key, value), looks up the binding, and submits the
intent to the dispatcher. The mido decoding is small and dependency-light; the
mapping is delegated to the pure ``midimap`` module, so behaviour is unit
testable with constructed mido messages and a fake dispatcher.
"""

from __future__ import annotations

import logging

from .midimap import event_key

_LOGGER = logging.getLogger(__name__)


def decode(msg):
    """Return (key, value) for a mido message, or (None, None) if unhandled.

    value = velocity (notes), CC value, or 0 for program_change (a pure trigger,
    handled by intent() treating >0 as fire — so PC uses 1).
    """
    t = getattr(msg, "type", None)
    ch = getattr(msg, "channel", 0)
    if t == "note_on":
        return event_key(t, ch, msg.note), msg.velocity
    if t == "note_off":
        return event_key("note_on", ch, msg.note), 0  # map note_off to the note key, value 0
    if t == "control_change":
        return event_key(t, ch, msg.control), msg.value
    if t == "program_change":
        return event_key(t, ch, msg.program), 1  # PC is a trigger
    return None, None


class MidiBridge:
    def __init__(self, config, dispatcher):
        self.config = config
        self.dispatcher = dispatcher
        self._bindings = config.midi_map  # {event_key: Binding}

    def events(self):
        return list(self._bindings.keys())

    def handle(self, msg) -> None:
        key, value = decode(msg)
        if key is None:
            return
        binding = self._bindings.get(key)
        if binding is None:
            _LOGGER.debug("MIDI %s (value %s) unmapped", key, value)
            return
        try:
            intent = binding.intent(value)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Error mapping %s value %s: %s", key, value, err)
            return
        if intent is None:
            return
        _LOGGER.info("MIDI %s (%s) value %s => %s", key, binding.name, value, intent["kind"])
        self.dispatcher.submit(intent)
