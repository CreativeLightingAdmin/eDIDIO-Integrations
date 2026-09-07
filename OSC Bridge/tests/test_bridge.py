"""OSC bridge tests: routing with a fake dispatcher, plus a REAL UDP OSC
round-trip through the python-osc server (no eDIDIO hardware).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pythonosc.osc_server import AsyncIOOSCUDPServer  # noqa: E402
from pythonosc.udp_client import SimpleUDPClient  # noqa: E402

from edidio_osc.bridge import OSCBridge  # noqa: E402
from edidio_osc.config import BridgeConfig  # noqa: E402
from edidio_osc.osc_server import build_osc_dispatcher  # noqa: E402


class FakeDispatcher:
    def __init__(self):
        self.intents = []

    def submit(self, intent):
        self.intents.append(intent)


RAW = {
    "osc": {"host": "127.0.0.1", "port": 0},
    "controller": {"host": "10.0.0.1", "port": 23},
    "addresses": [
        {"address": "/edidio/kitchen/level", "action": "dali_level", "line": 1, "address_dali": 5},
        {"address": "/edidio/living/level", "action": "dali_group_level", "line": 1, "group": 0},
        {"address": "/edidio/scene/movie", "action": "dali_scene", "line": 1, "scene": 3},
        {"address": "/edidio/seq/start", "action": "spektra", "zone": 1, "type": "sequence", "index": 0, "spektra_action": "start"},
    ],
}


def make():
    cfg = BridgeConfig(RAW)
    disp = FakeDispatcher()
    return OSCBridge(cfg, disp), disp


def test_routing_level():
    bridge, disp = make()
    bridge.handle("/edidio/kitchen/level", (0.5,))
    assert disp.intents[-1] == {"kind": "dali_level", "line": 1, "address": 5, "level": 127}


def test_routing_scene():
    bridge, disp = make()
    bridge.handle("/edidio/scene/movie", (1,))
    assert disp.intents[-1] == {"kind": "dali_scene", "line": 1, "scene": 3}


def test_routing_unmapped_ignored():
    bridge, disp = make()
    bridge.handle("/edidio/nope", (1,))
    assert disp.intents == []


def test_real_udp_roundtrip():
    """A real OSC client -> python-osc server -> bridge -> fake dispatcher."""

    async def scenario():
        cfg = BridgeConfig(RAW)
        disp = FakeDispatcher()
        bridge = OSCBridge(cfg, disp)
        osc_disp = build_osc_dispatcher(bridge)

        server = AsyncIOOSCUDPServer(("127.0.0.1", 0), osc_disp, asyncio.get_running_loop())
        transport, _protocol = await server.create_serve_endpoint()
        host, port = transport.get_extra_info("sockname")[:2]

        client = SimpleUDPClient(host, port)
        client.send_message("/edidio/living/level", 1.0)
        client.send_message("/edidio/scene/movie", 1)
        client.send_message("/edidio/seq/start", 1)
        await asyncio.sleep(0.3)
        transport.close()
        return disp.intents

    intents = asyncio.run(scenario())
    assert {"kind": "dali_group_level", "line": 1, "group": 0, "level": 254} in intents
    assert {"kind": "dali_scene", "line": 1, "scene": 3} in intents
    assert {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 0, "action": "START"} in intents
