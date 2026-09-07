"""python-osc wiring: receive OSC over UDP and route to the dispatcher."""

from __future__ import annotations

import asyncio
import logging

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer

from .bridge import OSCBridge
from .dispatcher import EdidioDispatcher

_LOGGER = logging.getLogger(__name__)


def build_osc_dispatcher(bridge: OSCBridge) -> Dispatcher:
    """A python-osc Dispatcher that routes every message through the bridge."""
    disp = Dispatcher()
    disp.set_default_handler(lambda address, *args: bridge.handle(address, args))
    return disp


async def run(config) -> None:
    """Start the dispatcher and OSC server; block until cancelled."""
    ctrl = config.controller
    dispatcher = EdidioDispatcher(ctrl.host, ctrl.port, use_tls=ctrl.use_tls, timeout=ctrl.timeout)
    await dispatcher.start()

    bridge = OSCBridge(config, dispatcher)
    disp = build_osc_dispatcher(bridge)

    server = AsyncIOOSCUDPServer(
        (config.osc.host, config.osc.port), disp, asyncio.get_running_loop()
    )
    transport, _protocol = await server.create_serve_endpoint()
    _LOGGER.info(
        "OSC bridge listening on %s:%s -> eDIDIO %s:%s | %d addresses mapped",
        config.osc.host, config.osc.port, ctrl.host, ctrl.port, len(bridge.addresses()),
    )

    try:
        await asyncio.Event().wait()
    finally:
        transport.close()
        await dispatcher.stop()
