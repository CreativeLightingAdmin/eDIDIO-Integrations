"""End-to-end test: a real Modbus TCP client writes holding registers on the
gateway and we assert the correct eDIDIO intents are produced.

No eDIDIO hardware is needed: the dispatcher is replaced with a capturing stub,
so we exercise the full Modbus server -> datastore -> intent path over a real
socket on localhost.
"""

import asyncio
import contextlib

import pytest
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.datastore import ModbusServerContext, ModbusSlaveContext, ModbusSequentialDataBlock

from edidio_modbus.config import GatewayConfig
from edidio_control_py.state import LevelTracker, dali_change

from edidio_modbus.datastore import CommandDataBlock, StateDataBlock
from edidio_modbus.registers import STATE_UNKNOWN, state_register
from pymodbus.server import StartAsyncTcpServer, ServerAsyncStop


class CapturingDispatcher:
    """Stands in for EdidioDispatcher; records submitted intents."""

    def __init__(self):
        self.intents = []

    def submit(self, intent):
        self.intents.append(intent)


CONFIG = GatewayConfig({
    "server": {"type": "tcp", "host": "127.0.0.1", "port": 0, "unit_id": 1},
    "controller": {"host": "10.0.0.1", "port": 23},
    "registers": [
        {"register": 1, "action": "dali_group_level", "line": 1, "group": 0},
        {"register": 2, "action": "dali_scene", "line": 1},
        {"register": 3, "action": "dali_level", "line": 1, "address": 5},
        {"register": 10, "action": "spektra_sequence", "zone": 1},
    ],
})

TEST_PORT = 15020


def _build_context(dispatcher, state=None):
    hr = CommandDataBlock(CONFIG.registers, dispatcher)
    zeros = lambda: ModbusSequentialDataBlock(1, [0])  # noqa: E731
    slave = ModbusSlaveContext(di=zeros(), co=zeros(), ir=state or zeros(), hr=hr)
    return ModbusServerContext(slaves={1: slave}, single=False)


async def _scenario():
    dispatcher = CapturingDispatcher()
    context = _build_context(dispatcher)

    server_task = asyncio.create_task(
        StartAsyncTcpServer(context=context, address=("127.0.0.1", TEST_PORT))
    )
    await asyncio.sleep(0.5)  # let the listener bind

    try:
        client = AsyncModbusTcpClient("127.0.0.1", port=TEST_PORT)
        await client.connect()
        assert client.connected, "client failed to connect to gateway"

        # Holding register 40001 (PDU 0) == config register 1: group level 200.
        await client.write_register(0, 200, slave=1)
        # 40002 == register 2: recall scene 4.
        await client.write_register(1, 4, slave=1)
        # 40003 == register 3: address 5 -> level 127.
        await client.write_register(2, 127, slave=1)
        # 40010 == register 10: spektra sequence, value 2 -> start index 1.
        await client.write_register(9, 2, slave=1)
        # 40010 value 0 -> spektra stop.
        await client.write_register(9, 0, slave=1)

        await asyncio.sleep(0.2)
        client.close()
    finally:
        await ServerAsyncStop()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            server_task.cancel()
            await server_task

    return dispatcher.intents


def test_modbus_writes_produce_intents():
    intents = asyncio.run(_scenario())
    assert {"kind": "dali_group_level", "line": 1, "group": 0, "level": 200} in intents
    assert {"kind": "dali_scene", "line": 1, "scene": 4} in intents
    assert {"kind": "dali_level", "line": 1, "address": 5, "level": 127} in intents
    assert {
        "kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 1, "action": "START",
    } in intents
    assert {"kind": "spektra_stop", "zone": 1} in intents



def test_state_register_layout():
    assert state_register(1, 0) == 1           # 30001
    assert state_register(1, 5) == 6           # 30006
    assert state_register(2, 64 + 3) == 168    # line 2 group 3 -> 30168
    assert state_register(4, 80) == 381        # line 4 broadcast


async def _state_scenario():
    state = StateDataBlock()
    context = _build_context(CapturingDispatcher(), state)
    # Live DALI frames from the event stream: addr 5 arc 200 on line 1, then a
    # broadcast OFF on line 2 (engine decoders, as the dispatcher would run them).
    tracker = LevelTracker()
    for line, frame in ((0, 0x0AC8), (1, 0xFF00)):
        change = dali_change({"kind": "dali", "line": line, "frame_type": 1, "frame": frame})
        await state.on_state(change, tracker.apply(change))

    server_task = asyncio.create_task(
        StartAsyncTcpServer(context=context, address=("127.0.0.1", TEST_PORT + 1))
    )
    await asyncio.sleep(0.5)
    try:
        client = AsyncModbusTcpClient("127.0.0.1", port=TEST_PORT + 1)
        await client.connect()
        # FC4 read of input registers 30001-30010 (PDU 0-9) and line 2 broadcast.
        line1 = (await client.read_input_registers(0, count=10, slave=1)).registers
        bcast2 = (await client.read_input_registers(state_register(2, 80) - 1, count=1, slave=1)).registers
        client.close()
    finally:
        await ServerAsyncStop()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            server_task.cancel()
            await server_task
    return line1, bcast2


def test_input_registers_mirror_live_levels():
    line1, bcast2 = asyncio.run(_state_scenario())
    assert line1[5] == 200                      # 30006 = line 1 address 5
    assert line1[0] == STATE_UNKNOWN            # never seen on the bus
    assert bcast2 == [0]
