"""Transport-agnostic KNX routing.

Maps KNX group addresses to eDIDIO targets, extracts the value from an incoming
xknx telegram, and submits the resulting intent to the dispatcher. The telegram
decoding depends on xknx types (installed), but the mapping is delegated to the
pure ``group_map`` module, so behaviour is unit testable with constructed
telegrams and a fake dispatcher.
"""

from __future__ import annotations

import logging

from xknx.dpt import DPTArray, DPTBinary
from xknx.telegram.apci import GroupValueWrite

_LOGGER = logging.getLogger(__name__)


def extract_value(telegram):
    """Return an integer value from a GroupValueWrite telegram, or None.

    DPTBinary -> its int (0/1); DPTArray -> its first byte. Other APCIs
    (GroupValueRead/Response) are ignored.
    """
    payload = telegram.payload
    if not isinstance(payload, GroupValueWrite):
        return None
    value = payload.value
    if isinstance(value, DPTBinary):
        return int(value.value)
    if isinstance(value, DPTArray):
        raw = value.value
        return int(raw[0]) if raw else 0
    return None


class KnxBridge:
    def __init__(self, config, dispatcher):
        self.config = config
        self.dispatcher = dispatcher
        self._targets = config.group_map  # {ga_str: GroupTarget}

    def group_addresses(self) -> list[str]:
        return list(self._targets.keys())

    def handle_telegram(self, telegram) -> None:
        ga = str(telegram.destination_address)
        target = self._targets.get(ga)
        if target is None:
            _LOGGER.debug("Telegram on unmapped GA %s ignored", ga)
            return
        value = extract_value(telegram)
        if value is None:
            _LOGGER.debug("Telegram on %s is not a group-write; ignored", ga)
            return
        try:
            intent = target.intent(value)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Error mapping GA %s value %r: %s", ga, value, err)
            return
        if intent is None:
            _LOGGER.debug("GA %s (%s) value %r produced no action", ga, target.name, value)
            return
        _LOGGER.info("GA %s (%s) = %r => %s", ga, target.name, value, intent["kind"])
        self.dispatcher.submit(intent)
