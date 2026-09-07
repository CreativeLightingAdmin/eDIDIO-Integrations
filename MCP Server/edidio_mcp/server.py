"""eDIDIO MCP server: expose lighting control as MCP tools.

Configured via environment variables (set by the MCP client):
  EDIDIO_HOST     controller IP/hostname (required)
  EDIDIO_PORT     23 (plain TCP, default) or 443 (TLS)
  EDIDIO_USE_TLS  true/false
"""

from __future__ import annotations

import logging
import os

from mcp.server.mcpserver import MCPServer

from . import discovery
from .controller import EdidioController

_LOGGER = logging.getLogger(__name__)

server = MCPServer(
    name="eDIDIO",
    instructions=(
        "Control Freak eDIDIO architectural lighting control. Tools drive DALI "
        "lights and groups, recall scenes, paint DMX colours, and run SpektraPlus "
        "effects. 'line' is a physical output 1-4; DALI address is 0-63; group and "
        "scene are 0-15; level is 0-254 (0=off, 254=full)."
    ),
)

_controller: EdidioController | None = None


def _bool(v) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on")


async def _get_controller() -> EdidioController:
    global _controller
    if _controller is None:
        host = os.environ.get("EDIDIO_HOST")
        if not host:
            raise RuntimeError("EDIDIO_HOST environment variable is required")
        _controller = EdidioController(
            host,
            int(os.environ.get("EDIDIO_PORT", "23")),
            use_tls=_bool(os.environ.get("EDIDIO_USE_TLS", "false")),
        )
    if not _controller.connected:
        await _controller.connect()
    return _controller


async def _do(action, ok_message):
    """Run a controller coroutine, returning a readable success/error string."""
    try:
        c = await _get_controller()
        await action(c)
        return ok_message
    except Exception as err:  # noqa: BLE001 - surface a message to the assistant
        _LOGGER.error("eDIDIO tool error: %s", err)
        return f"Error: {err}"


@server.tool()
async def set_light_level(line: int, address: int, level: int) -> str:
    """Set a single DALI light to a brightness level.

    line: physical line 1-4. address: DALI short address 0-63.
    level: 0-254 (0 = off, 254 = full).
    """
    return await _do(lambda c: c.set_level(line, address, level),
                     f"Line {line} address {address} set to level {level}.")


@server.tool()
async def set_group_level(line: int, group: int, level: int) -> str:
    """Set a DALI group (0-15) on a line to a brightness level (0-254)."""
    return await _do(lambda c: c.set_group_level(line, group, level),
                     f"Line {line} group {group} set to level {level}.")


@server.tool()
async def turn_light_on(line: int, address: int) -> str:
    """Turn a DALI light on (full brightness)."""
    return await _do(lambda c: c.turn_on(line, address),
                     f"Line {line} address {address} turned on.")


@server.tool()
async def turn_light_off(line: int, address: int) -> str:
    """Turn a DALI light off."""
    return await _do(lambda c: c.turn_off(line, address),
                     f"Line {line} address {address} turned off.")


@server.tool()
async def recall_scene(line: int, scene: int, group: int | None = None) -> str:
    """Recall a stored lighting scene (0-15) on a line, optionally on a group (0-15)."""
    where = f"group {group}" if group is not None else f"line {line}"
    return await _do(lambda c: c.recall_scene(line, scene, group),
                     f"Recalled scene {scene} on {where}.")


@server.tool()
async def set_dmx_color(line: int, hex: str) -> str:
    """Set an RGB colour (e.g. '#FF8800') across a DMX line."""
    return await _do(lambda c: c.dmx_color(line, hex),
                     f"Line {line} set to colour {hex}.")


@server.tool()
async def run_spektra(zone: int, target: str = "sequence", index: int = 0, action: str = "start") -> str:
    """Control a SpektraPlus effect on a zone.

    target: 'sequence' | 'theme' | 'static'. action: 'start' | 'stop' | 'pause'.
    """
    return await _do(lambda c: c.spektra(zone, target, index, action),
                     f"SpektraPlus {target} {index} {action} on zone {zone}.")


@server.tool()
async def stop_spektra(zone: int) -> str:
    """Stop SpektraPlus playback on a zone and turn the output off."""
    return await _do(lambda c: c.spektra_stop(zone), f"Stopped SpektraPlus on zone {zone}.")


@server.tool()
async def discover_controllers() -> str:
    """Find eDIDIO controllers on the local network (UDP broadcast)."""
    try:
        devices = discovery.discover()
    except Exception as err:  # noqa: BLE001
        return f"Error: {err}"
    if not devices:
        return "No eDIDIO controllers found on the local network."
    lines = [
        f"- {d.get('NAME', '?')} at {d.get('IP')} (MAC {d.get('MAC')}, TLS {d.get('TLS')}, "
        f"lines: {discovery.summarize_lines(d.get('LINES'))})"
        for d in devices
    ]
    return "Found controllers:\n" + "\n".join(lines)


def main():
    logging.basicConfig(level=logging.INFO)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
