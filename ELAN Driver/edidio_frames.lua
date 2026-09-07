-- Pure-Lua eDIDIO protocol frame encoder — zero dependencies.
--
-- Produces byte-identical output to the reference implementation
-- (edidio_control_py) and the other encoders (pure-Python, NetLinx, pure-JS),
-- but in portable Lua with NO external libraries (no `bit`, no LuaSocket) — so
-- it runs in the ELAN g! driver Lua environment (and any Lua 5.1+).
--
-- Wire format: 0xCD + 2-byte big-endian length + a serialized EdidioMessage.
-- Field numbers and zero-emission rules validated byte-for-byte in
-- tests/test_frames_lua.py (executed via a real Lua interpreter).
--
-- Uses only arithmetic (math.floor, %, *) so it does not depend on Lua 5.3+
-- bitwise operators or the LuaJIT `bit` library.

local M = {}

-- Enums -------------------------------------------------------------------
M.DALI_ARC_LEVEL = 0
M.DALI_GROUP_ARC_LEVEL = 2
M.DALI_BROADCAST_SCENE = 3
M.DALI_SCENE_ON_GROUP = 4
-- DALI addressing: 0-63 individual, 64-79 group (address = 64 + group), 80
-- broadcast. Scenes use the standard DALI "GO TO SCENE X" command (0x10 + scene)
-- sent to the target address.
M.DALI_GROUP_ADDRESS_BASE = 64
M.DALI_BROADCAST_ADDRESS = 80
M.DALI_GO_TO_SCENE_BASE = 16

M.DALI_OFF = 0
M.DALI_FADE_UP = 1
M.DALI_FADE_DOWN = 2
M.DALI_STEP_UP = 3
M.DALI_STEP_DOWN = 4
M.DALI_MAX_LEVEL = 5
M.DALI_MIN_LEVEL = 6
M.DALI_RECALL_LAST = 10
M.DALI_IDENTIFY = 37

M.SPEKTRA_SEQUENCE = 1
M.SPEKTRA_THEME = 2
M.SPEKTRA_STATIC = 3
M.SPEKTRA_START = 0
M.SPEKTRA_STOP = 1
M.SPEKTRA_PAUSE = 2
M.TRIGGER_SPEKTRA_STOP_SEQ = 13

M.DALI_ARC_LEVEL_MAX = 254

local NAMED_COMMANDS = {
  off = 0, on = 5, max = 5, min = 6,
  fade_up = 1, fade_down = 2, step_up = 3, step_down = 4,
  recall_last = 10, identify = 37,
}

-- Low-level protobuf wire encoding ----------------------------------------

local function varint(v)
  local s = ""
  while v >= 128 do
    s = s .. string.char((v % 128) + 128)
    v = math.floor(v / 128)
  end
  return s .. string.char(v % 128)
end

local function tag(field, wire)
  return varint(field * 8 + wire)
end

-- A varint (uint32/enum) field. Omitted when 0 unless `always`.
local function uint(field, value, always)
  if value == 0 and not always then return "" end
  return tag(field, 0) .. varint(value)
end

-- A packed repeated uint32 field.
local function packed(field, values)
  local body = ""
  for i = 1, #values do
    body = body .. varint(values[i])
  end
  return tag(field, 2) .. varint(#body) .. body
end

-- A length-delimited embedded message field.
local function embed(field, body)
  return tag(field, 2) .. varint(#body) .. body
end

-- Wrap a serialized EdidioMessage with the 0xCD + 2-byte length header.
local function frame(body)
  local n = #body
  return string.char(0xCD) .. string.char(math.floor(n / 256) % 256) .. string.char(n % 256) .. body
end

local function clamp(v, lo, hi)
  v = math.floor(v)
  if v < lo then return lo end
  if v > hi then return hi end
  return v
end

-- 1-based physical line (1-4) -> single-bit line mask (avoids bit ops).
function M.line_mask(line)
  local m = 1
  for _ = 2, line do m = m * 2 end
  return m
end

-- Message builders --------------------------------------------------------

local function dali(mid, line_mask, address, command, custom_command, arg)
  local body = uint(1, line_mask, false) .. uint(2, address, false)
  if command ~= nil then body = body .. uint(5, command, true) end
  if custom_command ~= nil then body = body .. uint(6, custom_command, true) end
  if arg ~= nil then body = body .. uint(9, arg, true) end
  return frame(uint(1, mid, false) .. embed(18, body))
end

function M.dali_arc_level(mid, line_mask, address, level)
  return dali(mid, line_mask, address, nil, M.DALI_ARC_LEVEL, clamp(level, 0, M.DALI_ARC_LEVEL_MAX))
end

function M.dali_group_arc_level(mid, line_mask, group, level)
  -- DALI_ARC_LEVEL to the group address (64 + group).
  return dali(mid, line_mask, M.DALI_GROUP_ADDRESS_BASE + group, nil, M.DALI_ARC_LEVEL, clamp(level, 0, M.DALI_ARC_LEVEL_MAX))
end

function M.dali_command(mid, line_mask, address, command, arg)
  if type(command) == "string" then
    local c = NAMED_COMMANDS[string.lower(command)]
    if c == nil then error("unknown DALI command: " .. command) end
    command = c
  end
  return dali(mid, line_mask, address, command, nil, arg or 0)
end

function M.dali_broadcast_scene(mid, line_mask, scene)
  -- Raw "GO TO SCENE X" command (0x10 + scene) to broadcast address 80.
  return dali(mid, line_mask, M.DALI_BROADCAST_ADDRESS, M.DALI_GO_TO_SCENE_BASE + scene, nil, nil)
end

function M.dali_scene_on_group(mid, line_mask, group, scene)
  -- Raw "GO TO SCENE X" command (0x10 + scene) to the group address (64 + group).
  return dali(mid, line_mask, M.DALI_GROUP_ADDRESS_BASE + group, M.DALI_GO_TO_SCENE_BASE + scene, nil, nil)
end

function M.dmx_level(mid, zone, universe_mask, channel, rpt, levels, fade_by_10ms)
  local clamped = {}
  for i = 1, #levels do clamped[i] = clamp(levels[i], 0, 255) end
  local body = uint(1, zone, false)
    .. uint(2, universe_mask, false)
    .. uint(3, channel, false)
    .. uint(4, rpt, false)
    .. packed(5, clamped)
    .. uint(6, fade_by_10ms or 0, false)
  return frame(uint(1, mid, false) .. embed(20, body))
end

function M.spektra_control(mid, spektra_type, zone, index, action)
  local body = uint(1, spektra_type, false)
    .. uint(2, zone, false)
    .. uint(3, index, false)
    .. uint(4, action, false)
  return frame(uint(1, mid, false) .. embed(27, body))
end

function M.spektra_stop(mid, zone, line_mask)
  if line_mask == nil then line_mask = 0xFF end
  local trigger = uint(1, M.TRIGGER_SPEKTRA_STOP_SEQ, false)
    .. uint(2, zone, false)
    .. uint(3, line_mask, false)
  return frame(uint(1, mid, false) .. embed(21, embed(1, trigger)))
end

-- Keep-alive / "Are You There" heartbeat frame.
M.KEEP_ALIVE = string.char(0xFF, 0xF6)

return M
