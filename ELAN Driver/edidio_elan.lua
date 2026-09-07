-- eDIDIO lighting control module for ELAN g! (Lua).
--
-- Provides a clean control API over the zero-dependency `edidio_frames` encoder.
-- The actual byte transmission is injected as a `send` function so the logic is
-- portable and testable; the thin ELAN comms adapter (using g!'s Ethernet
-- interface on port 23) is wired in the driver's connection handler.
--
--   local EDIDIO = require("edidio_elan")
--   local edidio = EDIDIO.new(function(bytes) gControl:Send(bytes) end)  -- ELAN glue
--   edidio:set_level(1, 5, 254)        -- line 1, address 5 to full
--   edidio:recall_scene(1, 3)          -- recall scene 3
--   edidio:dmx_color(2, 0xFF, 0, 0)    -- line 2 -> red
--   edidio:keep_alive()                -- call ~every 7 s from a g! timer

local frames = require("edidio_frames")

local EDIDIO = {}
EDIDIO.__index = EDIDIO

-- send_fn(bytes) transmits a framed message to the controller (ELAN comms glue).
function EDIDIO.new(send_fn)
  local self = setmetatable({}, EDIDIO)
  self.send_fn = send_fn
  self.mid = 0
  return self
end

function EDIDIO:_next_id()
  self.mid = (self.mid + 1) % 16777216
  return self.mid
end

function EDIDIO:_send(bytes)
  if self.send_fn then self.send_fn(bytes) end
end

-- DALI -------------------------------------------------------------------
function EDIDIO:set_level(line, address, level)
  self:_send(frames.dali_arc_level(self:_next_id(), frames.line_mask(line), address, level))
end

function EDIDIO:set_group_level(line, group, level)
  self:_send(frames.dali_group_arc_level(self:_next_id(), frames.line_mask(line), group, level))
end

function EDIDIO:on(line, address)
  self:_send(frames.dali_command(self:_next_id(), frames.line_mask(line), address, "on"))
end

function EDIDIO:off(line, address)
  self:_send(frames.dali_command(self:_next_id(), frames.line_mask(line), address, "off"))
end

function EDIDIO:command(line, address, cmd, arg)
  self:_send(frames.dali_command(self:_next_id(), frames.line_mask(line), address, cmd, arg or 0))
end

function EDIDIO:recall_scene(line, scene, group)
  if group == nil then
    self:_send(frames.dali_broadcast_scene(self:_next_id(), frames.line_mask(line), scene))
  else
    self:_send(frames.dali_scene_on_group(self:_next_id(), frames.line_mask(line), group, scene))
  end
end

-- DMX --------------------------------------------------------------------
-- Paint an RGB colour across a DMX line. `fixtures` tiles the triplet (170 fills
-- a 512-channel universe).
function EDIDIO:dmx_color(line, r, g, b, fixtures)
  fixtures = fixtures or 170
  self:_send(frames.dmx_level(self:_next_id(), 0xFF, frames.line_mask(line), 1, fixtures, {r, g, b}, 0))
end

function EDIDIO:dmx_levels(line, levels, channel, rpt, zone, fade_ms)
  self:_send(frames.dmx_level(self:_next_id(), zone or 0, frames.line_mask(line),
    channel or 1, rpt or 1, levels, math.floor((fade_ms or 0) / 10)))
end

-- SpektraPlus ------------------------------------------------------------
local SPEKTRA_TARGET = { sequence = frames.SPEKTRA_SEQUENCE, theme = frames.SPEKTRA_THEME, static = frames.SPEKTRA_STATIC }
local SPEKTRA_ACTION = { start = frames.SPEKTRA_START, stop = frames.SPEKTRA_STOP, pause = frames.SPEKTRA_PAUSE }

function EDIDIO:spektra(zone, target, index, action)
  local t = SPEKTRA_TARGET[string.lower(target or "sequence")]
  local a = SPEKTRA_ACTION[string.lower(action or "start")]
  if t == nil then error("unknown Spektra target: " .. tostring(target)) end
  if a == nil then error("unknown Spektra action: " .. tostring(action)) end
  self:_send(frames.spektra_control(self:_next_id(), t, zone, index or 0, a))
end

function EDIDIO:spektra_stop(zone)
  self:_send(frames.spektra_stop(self:_next_id(), zone, 0xFF))
end

-- Keep-alive -------------------------------------------------------------
function EDIDIO:keep_alive()
  self:_send(frames.KEEP_ALIVE)
end

return EDIDIO
