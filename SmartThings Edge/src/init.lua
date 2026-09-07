-- eDIDIO SmartThings Edge driver.
--
-- Exposes eDIDIO DALI lights as SmartThings devices (switch + switchLevel). Each
-- device stores its controller IP and target (line + address/group) in its
-- settings/preferences; the capability handlers translate SmartThings commands
-- into eDIDIO frames over a TCP socket (cosock).
--
-- Runs on a SmartThings hub. Package + install with the SmartThings CLI
-- (`smartthings edge:drivers:package .`). See README.

local capabilities = require("st.capabilities")
local Driver = require("st.driver")
local cosock = require("cosock")
local socket = cosock.socket
local log = require("log")

local EdidioCommands = require("edidio_commands")

local EDIDIO_PORT = 23

-- Open a short-lived TCP connection to the device's controller and return an
-- EdidioCommands bound to it (nil on failure). eDIDIO accepts back-to-back
-- commands on one connection; we open per action for simplicity/robustness.
local function commands_for(device)
  local ip = device.preferences and device.preferences.controllerIp
  if not ip or ip == "" then
    log.warn("eDIDIO: no controllerIp set for " .. tostring(device.id))
    return nil, nil
  end
  local sock = socket.tcp()
  sock:settimeout(3)
  local ok, err = sock:connect(ip, EDIDIO_PORT)
  if not ok then
    log.error("eDIDIO: connect to " .. ip .. " failed: " .. tostring(err))
    return nil, nil
  end
  local cmds = EdidioCommands.new(function(bytes) sock:send(bytes) end)
  return cmds, sock
end

local function target(device)
  local p = device.preferences or {}
  return {
    line = tonumber(p.line) or 1,
    address = tonumber(p.address) or 0,
    group = tonumber(p.group),
  }
end

-- --- capability command handlers ---

local function handle_on(_, device)
  local cmds, sock = commands_for(device)
  if not cmds then return end
  local t = target(device)
  if t.group then cmds:set_group_level_pct(t.line, t.group, 100) else cmds:on(t.line, t.address) end
  sock:close()
  device:emit_event(capabilities.switch.switch.on())
end

local function handle_off(_, device)
  local cmds, sock = commands_for(device)
  if not cmds then return end
  local t = target(device)
  if t.group then cmds:set_group_level_pct(t.line, t.group, 0) else cmds:off(t.line, t.address) end
  sock:close()
  device:emit_event(capabilities.switch.switch.off())
end

local function handle_set_level(_, device, command)
  local cmds, sock = commands_for(device)
  if not cmds then return end
  local t = target(device)
  local pct = command.args.level
  if t.group then cmds:set_group_level_pct(t.line, t.group, pct) else cmds:set_level_pct(t.line, t.address, pct) end
  sock:close()
  device:emit_event(capabilities.switchLevel.level(pct))
  device:emit_event(capabilities.switch.switch(pct > 0 and "on" or "off"))
end

local edidio_driver = Driver("edidio", {
  discovery = function() end, -- devices are added manually with controller IP in settings
  capability_handlers = {
    [capabilities.switch.ID] = {
      [capabilities.switch.commands.on.NAME] = handle_on,
      [capabilities.switch.commands.off.NAME] = handle_off,
    },
    [capabilities.switchLevel.ID] = {
      [capabilities.switchLevel.commands.setLevel.NAME] = handle_set_level,
    },
  },
})

edidio_driver:run()
