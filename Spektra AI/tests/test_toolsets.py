"""Tool groups loaded on demand (SPEKTRA_AI_TOOLS=dynamic)."""

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_spektra_ai import server as S  # noqa: E402
from edidio_spektra_ai import toolsets as TS  # noqa: E402


class FakeSession:
    def __init__(self):
        self.list_changed = 0

    async def send_tool_list_changed(self):
        self.list_changed += 1


class FakeCtx:
    def __init__(self):
        self.session = FakeSession()
        self.listen = 0

    async def notify_tools_changed(self):
        self.listen += 1


@pytest.fixture
def dynamic():
    was = (TS.state.dynamic, set(TS.state.loaded))
    TS.state.dynamic, TS.state.loaded = True, {TS.ALWAYS}
    yield TS.state
    TS.state.dynamic, TS.state.loaded = was


def names():
    return {t.name for t in asyncio.run(S.server.list_tools())}


def registered():
    return {t.name for t in S.server._tool_manager.list_tools()}


def test_every_tool_in_exactly_one_group():
    tools = registered() - set(TS.META_TOOLS)
    seen = {}
    for g, spec in TS.GROUPS.items():
        for t in spec["tools"]:
            assert t not in seen, f"{t} is in both {seen[t]} and {g}"
            seen[t] = g
    assert tools - set(seen) == set(), f"tools in no group: {sorted(tools - set(seen))}"
    assert set(seen) - tools == set(), f"groups name unknown tools: {sorted(set(seen) - tools)}"


def test_default_mode_shows_everything_but_meta():
    assert not TS.state.dynamic
    shown = names()
    assert shown == registered() - set(TS.META_TOOLS)


def test_dynamic_starts_with_core_and_meta(dynamic):
    shown = names()
    assert shown == set(TS.GROUPS["core"]["tools"]) | set(TS.META_TOOLS)
    assert "dali_scan" not in shown and "connect_controller" in shown


def test_load_and_unload_change_the_list_and_notify(dynamic):
    ctx = FakeCtx()
    out = asyncio.run(S.server.call_tool("load_tools", {"group": "dali"}, ctx))
    text = out.content[0].text
    assert "is now loaded" in text
    defs = json.loads(text.split("Definitions:\n", 1)[1])
    assert {d["name"] for d in defs} == set(TS.GROUPS["dali"]["tools"])
    assert all("input_schema" in d for d in defs)
    assert "dali_scan" in names()
    assert ctx.session.list_changed == 1 and ctx.listen == 1
    again = asyncio.run(S.server.call_tool("load_tools", {"group": "dali"}, ctx))
    assert "was already" in again.content[0].text and ctx.session.list_changed == 1
    asyncio.run(S.server.call_tool("unload_tools", {"group": "dali"}, ctx))
    assert "dali_scan" not in names() and ctx.session.list_changed == 2
    bad = asyncio.run(S.server.call_tool("load_tools", {"group": "nope"}, ctx))
    assert "Unknown group" in bad.content[0].text
    core = asyncio.run(S.server.call_tool("unload_tools", {"group": "core"}, ctx))
    assert "always loaded" in core.content[0].text


def test_run_tool_loads_the_group_and_calls_it(dynamic):
    ctx = FakeCtx()
    out = asyncio.run(S.server.call_tool(
        "run_tool", {"name": "validate_spektra", "arguments": {"path": "no-such.spektra"}}, ctx))
    assert "projects" in dynamic.loaded and ctx.session.list_changed == 1
    assert out.content[0].text                       # the tool's own reply came back
    unknown = asyncio.run(S.server.call_tool("run_tool", {"name": "nope"}, ctx))
    assert "Unknown tool" in unknown.content[0].text


def test_groups_are_much_smaller_than_everything(dynamic):
    full = sum(len(json.dumps({"n": t.name, "d": t.description, "s": t.parameters}))
               for t in S.server._tool_manager.list_tools())
    core = sum(len(json.dumps({"n": t.name, "d": t.description, "s": t.input_schema}))
               for t in asyncio.run(S.server.list_tools()))
    assert core < full * 0.25
