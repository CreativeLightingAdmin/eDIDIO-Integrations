"""Execute the ELAN control module (edidio_elan.lua) via lupa and assert each
control method emits the expected frame (an injected capture function stands in
for the ELAN comms glue). Runs the real Lua that ships to ELAN.
"""

import os

import pytest

lupa = pytest.importorskip("lupa")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MID1 = 1  # first message id the module uses


@pytest.fixture(scope="module")
def env():
    lua = lupa.LuaRuntime(encoding="latin-1", unpack_returned_tuples=True)
    # Let `require` find the .lua modules in the driver folder.
    lua.execute(("package.path = package.path .. ';%s/?.lua'" % BASE.replace("\\", "/")).encode())
    with open(os.path.join(BASE, "edidio_frames.lua"), "rb") as fh:
        frames = lua.execute(fh.read())
    # In Lua 5.4+ require returns two values (module, loader path); parens
    # truncate to just the module.
    EDIDIO = lua.eval('(require("edidio_elan"))')
    return lua, frames, EDIDIO


def hx(s):
    return (s if isinstance(s, bytes) else s.encode("latin-1")).hex()


def build(lua, EDIDIO):
    """Create an EDIDIO instance with a capturing send function."""
    captured = []
    send = lambda b: captured.append(b if isinstance(b, bytes) else b.encode("latin-1"))
    edidio = EDIDIO.new(send)
    return edidio, captured


def inv(edidio, method, *args):
    """Call a Lua colon-method through lupa, passing `self` explicitly."""
    getattr(edidio, method)(edidio, *args)


def test_set_level(env):
    lua, frames, EDIDIO = env
    edidio, captured = build(lua, EDIDIO)
    inv(edidio, "set_level", 1, 5, 200)
    assert captured[-1].hex() == hx(frames.dali_arc_level(MID1, frames.line_mask(1), 5, 200))


def test_group_level(env):
    lua, frames, EDIDIO = env
    edidio, captured = build(lua, EDIDIO)
    inv(edidio, "set_group_level", 1, 3, 128)
    assert captured[-1].hex() == hx(frames.dali_group_arc_level(MID1, frames.line_mask(1), 3, 128))


def test_on_off(env):
    lua, frames, EDIDIO = env
    edidio, captured = build(lua, EDIDIO)
    inv(edidio, "on", 2, 10)
    assert captured[-1].hex() == hx(frames.dali_command(MID1, frames.line_mask(2), 10, "on"))
    inv(edidio, "off", 2, 10)
    assert captured[-1].hex() == hx(frames.dali_command(2, frames.line_mask(2), 10, "off"))


def test_recall_scene(env):
    lua, frames, EDIDIO = env
    edidio, captured = build(lua, EDIDIO)
    inv(edidio, "recall_scene", 1, 3)
    assert captured[-1].hex() == hx(frames.dali_broadcast_scene(MID1, frames.line_mask(1), 3))
    inv(edidio, "recall_scene", 1, 3, 4)
    assert captured[-1].hex() == hx(frames.dali_scene_on_group(2, frames.line_mask(1), 4, 3))


def test_dmx_color(env):
    lua, frames, EDIDIO = env
    edidio, captured = build(lua, EDIDIO)
    inv(edidio, "dmx_color", 2, 0xFF, 0, 0, 10)
    expected = frames.dmx_level(MID1, 0xFF, frames.line_mask(2), 1, 10, lua.table_from([0xFF, 0, 0]), 0)
    assert captured[-1].hex() == hx(expected)


def test_spektra(env):
    lua, frames, EDIDIO = env
    edidio, captured = build(lua, EDIDIO)
    inv(edidio, "spektra", 1, "sequence", 2, "start")
    assert captured[-1].hex() == hx(frames.spektra_control(MID1, frames.SPEKTRA_SEQUENCE, 1, 2, frames.SPEKTRA_START))


def test_spektra_stop(env):
    lua, frames, EDIDIO = env
    edidio, captured = build(lua, EDIDIO)
    inv(edidio, "spektra_stop", 1)
    assert captured[-1].hex() == hx(frames.spektra_stop(MID1, 1, 0xFF))


def test_keep_alive(env):
    lua, frames, EDIDIO = env
    edidio, captured = build(lua, EDIDIO)
    inv(edidio, "keep_alive")
    assert captured[-1] == b"\xff\xf6"


def test_message_ids_increment(env):
    lua, frames, EDIDIO = env
    edidio, captured = build(lua, EDIDIO)
    inv(edidio, "set_level", 1, 0, 10)
    inv(edidio, "set_level", 1, 0, 10)
    assert captured[-1] != captured[-2]
