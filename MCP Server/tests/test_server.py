"""Exercise the MCP tools with an injected fake controller (no MCP client, no
network). Confirms the tools are registered/callable and drive the controller."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_mcp import server as srv  # noqa: E402
from edidio_mcp.controller import EdidioController  # noqa: E402


class FakeClient:
    def __init__(self):
        self.calls = []
        self.connected = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    def __getattr__(self, name):
        async def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return method


def inject():
    fake = FakeClient()
    srv._controller = EdidioController("10.0.0.1", client=fake)
    return fake


def run(coro):
    return asyncio.run(coro)


def test_set_light_level_tool():
    fake = inject()
    result = run(srv.set_light_level(1, 5, 200))
    assert "level 200" in result
    assert fake.calls[-1][0] == "set_dali_arc_level"


def test_recall_scene_tool():
    fake = inject()
    result = run(srv.recall_scene(1, 3))
    assert "scene 3" in result
    assert fake.calls[-1][0] == "recall_dali_scene"


def test_run_spektra_tool():
    fake = inject()
    result = run(srv.run_spektra(1, "sequence", 0, "start"))
    assert "zone 1" in result
    assert fake.calls[-1][0] == "send_spektra_control"


def test_tool_error_is_reported_not_raised():
    # No controller + no EDIDIO_HOST -> tool returns an error string, not a crash.
    srv._controller = None
    os.environ.pop("EDIDIO_HOST", None)
    result = run(srv.turn_light_on(1, 5))
    assert result.startswith("Error:")


def test_server_has_registered_tools():
    # The MCPServer should have our tools registered.
    assert srv.server is not None
    assert callable(srv.set_light_level)
    assert callable(srv.discover_controllers)
