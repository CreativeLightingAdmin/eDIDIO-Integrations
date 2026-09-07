"""Execute the SmartThings Edge command layer (edidio_commands.lua) via lupa and
assert each method emits the expected eDIDIO frame + pct->arc scaling. Runs the
real Lua that ships to the hub; captures bytes via an injected send function.
(The init.lua capability handlers need the SmartThings `st`/`cosock` runtime, so
the tested part is the command/frame logic, which is the real work.)
"""

import os

import pytest

lupa = pytest.importorskip("lupa")

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
MID1 = 1


@pytest.fixture(scope="module")
def env():
    lua = lupa.LuaRuntime(encoding="latin-1", unpack_returned_tuples=True)
    lua.execute(("package.path = package.path .. ';%s/?.lua'" % BASE.replace("\\", "/")).encode())
    with open(os.path.join(BASE, "edidio_frames.lua"), "rb") as fh:
        frames = lua.execute(fh.read())
    Commands = lua.eval('(require("edidio_commands"))')  # parens: require returns 2 vals in Lua 5.4+
    return lua, frames, Commands


def hx(s):
    return (s if isinstance(s, bytes) else s.encode("latin-1")).hex()


def build(Commands):
    captured = []
    send = lambda b: captured.append(b if isinstance(b, bytes) else b.encode("latin-1"))
    return Commands.new(send), captured


def inv(obj, method, *args):
    getattr(obj, method)(obj, *args)


def test_pct_to_arc(env):
    lua, frames, Commands = env
    assert Commands.pct_to_arc(100) == 254
    assert Commands.pct_to_arc(0) == 0
    assert Commands.pct_to_arc(50) == 127


def test_set_level_pct(env):
    lua, frames, Commands = env
    c, captured = build(Commands)
    inv(c, "set_level_pct", 1, 5, 100)  # 100% -> 254
    assert captured[-1].hex() == hx(frames.dali_arc_level(MID1, frames.line_mask(1), 5, 254))


def test_group_level_pct(env):
    lua, frames, Commands = env
    c, captured = build(Commands)
    inv(c, "set_group_level_pct", 1, 0, 50)  # 50% -> 127
    assert captured[-1].hex() == hx(frames.dali_group_arc_level(MID1, frames.line_mask(1), 0, 127))


def test_on_off(env):
    lua, frames, Commands = env
    c, captured = build(Commands)
    inv(c, "on", 2, 10)
    assert captured[-1].hex() == hx(frames.dali_command(MID1, frames.line_mask(2), 10, "on"))
    inv(c, "off", 2, 10)
    assert captured[-1].hex() == hx(frames.dali_command(2, frames.line_mask(2), 10, "off"))


def test_recall_scene(env):
    lua, frames, Commands = env
    c, captured = build(Commands)
    inv(c, "recall_scene", 1, 3)
    assert captured[-1].hex() == hx(frames.dali_broadcast_scene(MID1, frames.line_mask(1), 3))
