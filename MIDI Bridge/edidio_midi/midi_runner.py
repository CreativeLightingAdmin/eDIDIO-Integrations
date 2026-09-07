"""mido input wiring: receive MIDI and route to the dispatcher."""

from __future__ import annotations

import asyncio
import logging

import mido

from .bridge import MidiBridge
from .dispatcher import EdidioDispatcher

_LOGGER = logging.getLogger(__name__)


def list_ports() -> list[str]:
    return mido.get_input_names()


def _resolve_port(requested):
    ports = mido.get_input_names()
    if not ports:
        raise RuntimeError("No MIDI input ports found. Connect a device (or a virtual port).")
    if not requested:
        return ports[0]
    for p in ports:
        if requested.lower() in p.lower():
            return p
    raise RuntimeError(f"No MIDI input matching '{requested}'. Available: {', '.join(ports)}")


async def run(config, port_override=None) -> None:
    """Start the dispatcher and open the MIDI input; block until cancelled."""
    ctrl = config.controller
    dispatcher = EdidioDispatcher(ctrl.host, ctrl.port, use_tls=ctrl.use_tls, timeout=ctrl.timeout)
    await dispatcher.start()

    bridge = MidiBridge(config, dispatcher)
    port_name = _resolve_port(port_override or config.midi.port)
    loop = asyncio.get_running_loop()

    # mido delivers messages on its own thread; hop back to the loop-safe submit
    # inside the bridge (the dispatcher's submit is already thread-safe).
    def on_message(msg):
        bridge.handle(msg)

    _LOGGER.info(
        "MIDI bridge listening on '%s' -> eDIDIO %s:%s | %d bindings",
        port_name, ctrl.host, ctrl.port, len(bridge.events()),
    )
    inport = mido.open_input(port_name, callback=on_message)
    try:
        await asyncio.Event().wait()
    finally:
        inport.close()
        await dispatcher.stop()
