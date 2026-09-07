-- eDIDIO command layer for the SmartThings Edge driver.
--
-- Turns high-level lighting intents into framed eDIDIO messages using the shared
-- zero-dependency `edidio_frames` encoder, and sends them over a TCP socket
-- (injected, so the logic is testable off-hub). SmartThings Edge provides
-- `cosock.socket` at runtime; tests inject a fake socket that captures bytes.

local frames = require("edidio_frames")

local M = {}
M.__index = M

-- send_fn(bytes) transmits a framed message to the controller.
function M.new(send_fn)
  local self = setmetatable({}, M)
  self.send_fn = send_fn
  self.mid = 0
  return self
end

function M:_next_id()
  self.mid = (self.mid + 1) % 16777216
  return self.mid
end

function M:_send(bytes)
  if self.send_fn then self.send_fn(bytes) end
end

-- SmartThings switch/level maps to a DALI address or group on a line.
-- SmartThings level is 0-100 (%); DALI arc is 0-254.
local function pct_to_arc(pct)
  if pct < 0 then pct = 0 elseif pct > 100 then pct = 100 end
  return math.floor(pct * 254 / 100 + 0.5)
end

function M:set_level_pct(line, address, pct)
  self:_send(frames.dali_arc_level(self:_next_id(), frames.line_mask(line), address, pct_to_arc(pct)))
end

function M:set_group_level_pct(line, group, pct)
  self:_send(frames.dali_group_arc_level(self:_next_id(), frames.line_mask(line), group, pct_to_arc(pct)))
end

function M:on(line, address)
  self:_send(frames.dali_command(self:_next_id(), frames.line_mask(line), address, "on"))
end

function M:off(line, address)
  self:_send(frames.dali_command(self:_next_id(), frames.line_mask(line), address, "off"))
end

function M:recall_scene(line, scene)
  self:_send(frames.dali_broadcast_scene(self:_next_id(), frames.line_mask(line), scene))
end

M.pct_to_arc = pct_to_arc
return M
