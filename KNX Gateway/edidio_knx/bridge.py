"""Transport-agnostic KNX routing.

Maps KNX group addresses to eDIDIO targets, extracts the value from an incoming
xknx telegram, and submits the resulting intent to the dispatcher. The telegram
decoding depends on xknx types (installed), but the mapping is delegated to the
pure ``group_map`` module, so behaviour is unit testable with constructed
telegrams and a fake dispatcher.

Feedback: entries with a ``status_ga`` get the level actually seen on the DALI
bus written back to KNX (``on_state``), and GroupValueRead on a status GA is
answered with the last known value — standard KNX status-object behaviour.
"""

from __future__ import annotations

import logging

from xknx.dpt import DPTArray, DPTBinary
from xknx.telegram import Telegram
from xknx.telegram.address import GroupAddress
from xknx.telegram.apci import GroupValueRead, GroupValueResponse, GroupValueWrite

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


def _dpt_payload(target, value):
    return DPTBinary(value) if target.dpt == "switch" else DPTArray((value,))


class KnxBridge:
    def __init__(self, config, dispatcher, send=None):
        self.config = config
        self.dispatcher = dispatcher
        self._targets = config.group_map  # {ga_str: GroupTarget}
        self._send = send                 # callable(Telegram): puts it on the bus
        self._status = {t.status_ga: t for t in self._targets.values() if t.status_ga}
        self._status_by_addr = {}         # (line, eDIDIO address) -> [targets]
        for t in self._status.values():
            self._status_by_addr.setdefault((t.line, t.edidio_address), []).append(t)
        self._last = {}                   # status_ga -> last value written

    def set_sender(self, send):
        self._send = send

    def status_updates(self, touched) -> list:
        """[(target, value)] for status GAs affected by ``(line, address, level)``
        changes. Values that haven't changed are skipped."""
        out = []
        for line, address, level in touched:
            for target in self._status_by_addr.get((line, address), []):
                value = target.status_value(level)
                if value is None or self._last.get(target.status_ga) == value:
                    continue
                self._last[target.status_ga] = value
                out.append((target, value))
        return out

    async def on_state(self, change, touched) -> None:
        """Dispatcher state callback: write real levels to the status GAs."""
        if change.level is None and change.command == "scene":
            return
        for target, value in self.status_updates(touched):
            self._emit(target, GroupValueWrite(_dpt_payload(target, value)))

    def _emit(self, target, payload):
        if self._send is None:
            return
        _LOGGER.info("Status %s (%s) <= %r", target.status_ga, target.name, payload.value)
        self._send(Telegram(destination_address=GroupAddress(target.status_ga), payload=payload))

    def group_addresses(self) -> list[str]:
        return list(self._targets.keys())

    def handle_telegram(self, telegram) -> None:
        ga = str(telegram.destination_address)
        status = self._status.get(ga)
        if status is not None:
            if isinstance(telegram.payload, GroupValueRead) and ga in self._last:
                self._emit(status, GroupValueResponse(_dpt_payload(status, self._last[ga])))
            return
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
