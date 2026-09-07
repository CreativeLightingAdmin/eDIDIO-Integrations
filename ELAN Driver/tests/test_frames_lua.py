"""Execute the ELAN pure-Lua encoder (via lupa) and assert byte-identical frames.

This runs the ACTUAL Lua module in a real Lua interpreter, so it verifies the
Lua that ships to ELAN — not a reimplementation. Reference hexes captured from
edidio_control_py 0.3.0 (message_id=7), the same oracle used by every encoder.
"""

import os

import pytest

lupa = pytest.importorskip("lupa")

LUA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "edidio_frames.lua")

MID = 7

REFERENCE = {
    "arc": "cd000e080792010908011005300048c801",
    "group": "cd000e0807920109080110433000488001",
    "cmd": "cd000d08079201080802100a28054800",
    "cmd_off": "cd000b0807920106080128004800",
    "bscene": "cd000b0807920106080110502813",
    "gscene": "cd000b0807920106080110442813",
    "dmx": "cd00140807a2010f08ff0110021801200a2a04ff010000",
    "dmx_fade": "cd00120807a2010d1001180120012a030a141e3032",
    "spektra": "cd000b0807da0106080110011802",
    "spektra_stop": "cd000e0807aa01090a07080d100118ff01",
}


@pytest.fixture(scope="module")
def M():
    # latin-1 gives a 1:1 byte<->char mapping so binary Lua strings (containing
    # bytes like 0xCD) round-trip without a UTF-8 decode error.
    lua = lupa.LuaRuntime(encoding="latin-1", unpack_returned_tuples=True)
    with open(LUA_FILE, "rb") as fh:
        code = fh.read()  # pass source as bytes so lupa doesn't re-encode it
    module = lua.execute(code)  # the file ends with `return M`
    return lua, module


def as_bytes(lua_str):
    """lupa (encoding='latin-1') returns Lua strings as latin-1 str; -> bytes."""
    if isinstance(lua_str, bytes):
        return lua_str
    return lua_str.encode("latin-1")


def h(lua_str):
    return as_bytes(lua_str).hex()


def test_arc(M):
    lua, m = M
    assert h(m.dali_arc_level(MID, 1, 5, 200)) == REFERENCE["arc"]


def test_group(M):
    lua, m = M
    assert h(m.dali_group_arc_level(MID, 1, 3, 128)) == REFERENCE["group"]


def test_command(M):
    lua, m = M
    assert h(m.dali_command(MID, 2, 10, m.DALI_MAX_LEVEL)) == REFERENCE["cmd"]


def test_command_off_named(M):
    lua, m = M
    assert h(m.dali_command(MID, 1, 0, "off")) == REFERENCE["cmd_off"]


def test_broadcast_scene(M):
    lua, m = M
    assert h(m.dali_broadcast_scene(MID, 1, 3)) == REFERENCE["bscene"]


def test_scene_on_group(M):
    lua, m = M
    assert h(m.dali_scene_on_group(MID, 1, 4, 3)) == REFERENCE["gscene"]


def test_dmx(M):
    lua, m = M
    levels = lua.table_from([255, 0, 0])
    assert h(m.dmx_level(MID, 255, 2, 1, 10, levels, 0)) == REFERENCE["dmx"]


def test_dmx_fade(M):
    lua, m = M
    levels = lua.table_from([10, 20, 30])
    assert h(m.dmx_level(MID, 0, 1, 1, 1, levels, 50)) == REFERENCE["dmx_fade"]


def test_spektra(M):
    lua, m = M
    assert h(m.spektra_control(MID, m.SPEKTRA_SEQUENCE, 1, 2, m.SPEKTRA_START)) == REFERENCE["spektra"]


def test_spektra_stop(M):
    lua, m = M
    assert h(m.spektra_stop(MID, 1, 0xFF)) == REFERENCE["spektra_stop"]


def test_line_mask(M):
    lua, m = M
    assert m.line_mask(1) == 1
    assert m.line_mask(4) == 8


def test_arc_clamps(M):
    lua, m = M
    assert h(m.dali_arc_level(MID, 1, 5, 999)) == h(m.dali_arc_level(MID, 1, 5, 254))
