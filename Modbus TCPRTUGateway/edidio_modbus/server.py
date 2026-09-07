"""Wire the Modbus server to the eDIDIO dispatcher and run it."""

from __future__ import annotations

import asyncio
import logging

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.server import StartAsyncSerialServer, StartAsyncTcpServer

from . import __version__
from .config import GatewayConfig
from .datastore import CommandDataBlock
from .dispatcher import EdidioDispatcher

_LOGGER = logging.getLogger(__name__)


def _identity() -> ModbusDeviceIdentification:
    return ModbusDeviceIdentification(
        info_name={
            "VendorName": "Control Freak",
            "ProductCode": "eDIDIO-MODBUS",
            "ProductName": "eDIDIO Modbus Gateway",
            "ModelName": "eDIDIO Modbus Gateway",
            "MajorMinorRevision": __version__,
        }
    )


def build_context(config: GatewayConfig, dispatcher: EdidioDispatcher) -> ModbusServerContext:
    """Build a single-slave server context whose holding registers fire commands."""
    hr = CommandDataBlock(config.registers, dispatcher)
    # Discrete inputs / coils / input registers are unused but must exist.
    zeros = lambda: ModbusSequentialDataBlock(1, [0])  # noqa: E731
    slave = ModbusSlaveContext(di=zeros(), co=zeros(), ir=zeros(), hr=hr)
    return ModbusServerContext(slaves={config.server.unit_id: slave}, single=False)


async def run(config: GatewayConfig) -> None:
    """Start the dispatcher and the Modbus server (blocks until cancelled)."""
    ctrl = config.controller
    dispatcher = EdidioDispatcher(
        ctrl.host, ctrl.port, use_tls=ctrl.use_tls, timeout=ctrl.timeout
    )
    await dispatcher.start()

    context = build_context(config, dispatcher)
    srv = config.server

    try:
        if srv.type == "tcp":
            _LOGGER.info(
                "Modbus TCP gateway listening on %s:%s (unit %s) -> eDIDIO %s:%s",
                srv.host, srv.port, srv.unit_id, ctrl.host, ctrl.port,
            )
            await StartAsyncTcpServer(
                context=context, identity=_identity(), address=(srv.host, srv.port)
            )
        else:  # rtu
            _LOGGER.info(
                "Modbus RTU gateway on %s @ %s baud (unit %s) -> eDIDIO %s:%s",
                srv.port, srv.baudrate, srv.unit_id, ctrl.host, ctrl.port,
            )
            await StartAsyncSerialServer(
                context=context,
                identity=_identity(),
                port=srv.port,
                baudrate=srv.baudrate,
                parity=srv.parity,
                stopbits=srv.stopbits,
                bytesize=srv.bytesize,
            )
    finally:
        await dispatcher.stop()
