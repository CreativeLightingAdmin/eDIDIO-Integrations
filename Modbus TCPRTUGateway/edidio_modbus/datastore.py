"""A holding-register datablock that intercepts writes.

pymodbus' ``ModbusSlaveContext`` calls ``setValues(address, values)`` on the
holding-register block whenever a client writes (function codes 6/16). The
`address` here is already 1-based (the slave context adds 1 to the PDU address),
so it maps directly to the 1-based `register` numbers in the config
(register 1 == holding register 40001 == PDU address 0).

We keep the standard read/store behaviour and, on each write, resolve the
register to an eDIDIO intent and hand it to the dispatcher.
"""

from __future__ import annotations

import logging

from pymodbus.datastore import ModbusSequentialDataBlock

from .dispatcher import EdidioDispatcher
from .registers import STATE_BLOCK_SIZE, STATE_UNKNOWN, RegisterEntry, state_register

_LOGGER = logging.getLogger(__name__)


class CommandDataBlock(ModbusSequentialDataBlock):
    """Holding-register block that fires eDIDIO commands on write."""

    def __init__(self, register_map: dict[int, RegisterEntry], dispatcher: EdidioDispatcher):
        self._map = register_map
        self._dispatcher = dispatcher
        # Base address 1 so incoming (already +1'd) addresses line up with the
        # 1-based register numbers. Size to cover the highest mapped register.
        size = max(register_map) if register_map else 1
        super().__init__(1, [0] * size)

    def setValues(self, address, values):  # noqa: N802 - pymodbus API name
        if not isinstance(values, list):
            values = [values]

        # Persist first so subsequent reads reflect the written value.
        super().setValues(address, values)

        for offset, value in enumerate(values):
            reg = address + offset
            entry = self._map.get(reg)
            if entry is None:
                _LOGGER.debug("Write to unmapped register %s (value %s) ignored", reg, value)
                continue
            intent = entry.intent(int(value))
            if intent is None:
                _LOGGER.warning(
                    "Register %s (%s): value %s is out of range for %s; ignored",
                    reg, entry.name, value, entry.action,
                )
                continue
            _LOGGER.info("Register %s (%s) <- %s => %s", reg, entry.name, value, intent["kind"])
            self._dispatcher.submit(intent)


class StateDataBlock(ModbusSequentialDataBlock):
    """Input registers mirroring the DALI levels seen on the bus (read-only, FC4).

    Filled from the live event stream by ``on_state``, so a BMS/PLC reads the
    real level — including changes made by wall panels, schedules or other apps.
    See ``registers.state_register`` for the layout.
    """

    def __init__(self):
        super().__init__(1, [STATE_UNKNOWN] * STATE_BLOCK_SIZE)

    def level(self, line: int, address: int) -> int:
        return self.getValues(state_register(line, address), 1)[0]

    async def on_state(self, change, touched) -> None:
        """Dispatcher state callback."""
        for line, address, level in touched:
            value = STATE_UNKNOWN if level is None else int(level)
            self.setValues(state_register(line, address), [value])
