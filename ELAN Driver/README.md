# eDIDIO ELAN Driver (g!)

A **Lua** driver core for controlling Control Freak **eDIDIO** lighting from
**ELAN g!** (Nice / Core Brands) systems — DALI, DMX and SpektraPlus over
Ethernet.

> **Target:** Residential AV (ELAN g!).
> **Status:** Tested logic core, ready to wrap in an ELAN g! driver package.

## What's here (and what needs the ELAN SDK)

ELAN g! drivers are Lua. This repo provides the **tested driver logic** — the
part that's the same regardless of the ELAN environment:

- **`edidio_frames.lua`** — a zero-dependency, pure-Lua eDIDIO frame encoder. It
  uses only arithmetic (no `bit` library, no LuaSocket), so it runs in ELAN g!'s
  Lua environment and any Lua 5.1+. Verified **byte-for-byte** against
  `edidio_control_py` by executing the real Lua in tests.
- **`edidio_elan.lua`** — a clean control API (`EDIDIO` object) over the encoder,
  with byte transmission injected as a `send` function.

**Requires the ELAN environment (not in this repo):** packaging these into a
loadable **ELAN g! driver** and deploying/testing on a controller needs **ELAN
g! Tools / Configurator** and an ELAN dealer account. ELAN supports importing
custom drivers as **Ethernet** communication devices (eDIDIO uses **port 23**);
the driver's connection handler supplies the `send` function and calls
`keep_alive()` on a timer. See the [ELAN g! partner/driver resources](http://www.convergingsystems.com/inres_elan_gsystem.php)
for the g! Tools driver-import workflow.

## Control API (`edidio_elan.lua`)

```lua
local EDIDIO = require("edidio_elan")

-- `send` is your ELAN comms glue: transmit the given byte string to the
-- controller over the g! Ethernet interface (port 23).
local edidio = EDIDIO.new(function(bytes) gComms:Send(bytes) end)

edidio:set_level(1, 5, 254)        -- line 1, DALI address 5 -> full
edidio:set_group_level(1, 0, 128)  -- line 1, group 0 -> 50%
edidio:on(1, 5);  edidio:off(1, 5)
edidio:recall_scene(1, 3)          -- broadcast scene 3 on line 1
edidio:recall_scene(1, 3, 4)       -- scene 3 on group 4
edidio:dmx_color(2, 0xFF, 0x00, 0x00, 170)  -- line 2 -> red (fill universe)
edidio:spektra(1, "sequence", 0, "start")   -- zone 1, start sequence 0
edidio:spektra_stop(1)
edidio:keep_alive()                -- call ~every 7 s from a g! timer
```

| Method | Description |
|--------|-------------|
| `set_level(line, address, level)` | DALI address 0–63 → arc level 0–254 |
| `set_group_level(line, group, level)` | DALI group 0–15 → arc level |
| `on/off(line, address)` | Max / off |
| `command(line, address, cmd, arg)` | Named (`off,on,max,min,fade_up,…`) or numeric DALI command |
| `recall_scene(line, scene[, group])` | Recall a scene (broadcast or on a group) |
| `dmx_color(line, r, g, b[, fixtures])` | RGB across a DMX line |
| `dmx_levels(line, levels[, channel, rpt, zone, fade_ms])` | Raw DMX channels |
| `spektra(zone, target, index, action)` | SpektraPlus sequence/theme/static |
| `spektra_stop(zone)` | Stop and turn output off |
| `keep_alive()` | Heartbeat (call periodically) |

**Line** is the physical daughter-board slot (1–4). The module assigns rolling
message IDs automatically.

## Testing

The Lua ships to ELAN, so the tests **run the actual Lua** (via the `lupa`
embedded interpreter) — not a reimplementation:

```bash
cd "ELAN Driver"
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

- `test_frames_lua.py` — every frame from `edidio_frames.lua` byte-for-byte
  against the reference implementation.
- `test_elan_lua.py` — each `EDIDIO` control method emits the expected frame
  (an injected capture function stands in for the ELAN comms glue).

In ELAN g! Tools, import the driver, connect it to the controller IP (port 23),
and trigger actions from the g! interface / Configurator to confirm on hardware.

## Files

```
ELAN Driver/
├── edidio_frames.lua     # zero-dependency eDIDIO frame encoder (pure Lua)
├── edidio_elan.lua       # EDIDIO control API (send injected)
├── requirements-dev.txt  # test-only deps (driver has none)
└── tests/                # Lua executed via lupa
```

## License

MIT
