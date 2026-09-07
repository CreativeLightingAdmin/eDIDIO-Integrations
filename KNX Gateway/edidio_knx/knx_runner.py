"""xknx wiring: connect to the KNX bus and route telegrams to the dispatcher."""

from __future__ import annotations

import asyncio
import logging

from xknx import XKNX
from xknx.io import ConnectionConfig, ConnectionType

from .bridge import KnxBridge
from .dispatcher import EdidioDispatcher

_LOGGER = logging.getLogger(__name__)


def _connection_config(knx) -> ConnectionConfig:
    if knx.connection in ("tunnelling", "tunneling"):
        return ConnectionConfig(
            connection_type=ConnectionType.TUNNELING,
            gateway_ip=knx.gateway_ip,
            gateway_port=knx.gateway_port,
        )
    if knx.connection == "routing":
        return ConnectionConfig(connection_type=ConnectionType.ROUTING)
    return ConnectionConfig(connection_type=ConnectionType.AUTOMATIC)


async def run(config) -> None:
    """Start the dispatcher and KNX connection; block until cancelled."""
    ctrl = config.controller
    dispatcher = EdidioDispatcher(ctrl.host, ctrl.port, use_tls=ctrl.use_tls, timeout=ctrl.timeout)
    await dispatcher.start()

    bridge = KnxBridge(config, dispatcher)

    xknx = XKNX(connection_config=_connection_config(config.knx))

    # xknx invokes telegram-received callbacks synchronously (not awaited), so
    # this must be a plain function. bridge.handle_telegram is sync and hands the
    # intent to the dispatcher via a thread-safe queue put.
    def _on_telegram(telegram):
        bridge.handle_telegram(telegram)

    xknx.telegram_queue.register_telegram_received_cb(_on_telegram)

    _LOGGER.info(
        "Starting KNX connection (%s) -> eDIDIO %s:%s | %d group addresses mapped",
        config.knx.connection, ctrl.host, ctrl.port, len(bridge.group_addresses()),
    )
    await xknx.start()
    try:
        await asyncio.Event().wait()  # run until cancelled
    finally:
        await xknx.stop()
        await dispatcher.stop()
