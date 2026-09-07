"""Transport-agnostic OSC routing.

Maps an incoming OSC (address, args) to an eDIDIO intent and submits it to the
dispatcher. Independent of python-osc so it is unit testable with a fake
dispatcher; the server wires python-osc handlers to ``handle``.
"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)


class OSCBridge:
    def __init__(self, config, dispatcher):
        self.config = config
        self.dispatcher = dispatcher
        self._targets = config.address_map  # {osc_address: OSCTarget}

    def addresses(self):
        return list(self._targets.keys())

    def handle(self, address: str, args) -> None:
        target = self._targets.get(address)
        if target is None:
            _LOGGER.debug("OSC message on unmapped address %s ignored", address)
            return
        try:
            intent = target.intent(tuple(args))
        except Exception as err:  # noqa: BLE001 - a bad message must not kill the bridge
            _LOGGER.error("Error mapping OSC %s %r: %s", address, args, err)
            return
        if intent is None:
            _LOGGER.debug("OSC %s %r produced no action", address, args)
            return
        _LOGGER.info("OSC %s %r => %s", address, args, intent["kind"])
        self.dispatcher.submit(intent)
