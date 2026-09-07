# eDIDIO SmartThings Edge Driver

A **SmartThings Edge** driver that runs **on the SmartThings hub** (locally, no
cloud) and exposes Control Freak **eDIDIO** DALI lights as SmartThings devices —
switch + dimmer — controllable from the SmartThings app, routines and voice
(Alexa/Google/Bixby via SmartThings).

> **Target:** Smart home (SmartThings).
> **Tech:** Lua Edge driver (`cosock` TCP), reusing the eDIDIO **Lua** frame
> encoder shared with the ELAN driver — no cloud, no gateway.

## What it does

Each SmartThings device maps to a DALI target on your controller (set in the
device's settings): a **line** plus an **address** (single light) or a **group**.
The **switch** and **switchLevel** (dimmer, 0–100% → arc 0–254) capabilities send
eDIDIO frames straight to the controller over the LAN.

## How it's built (and what needs the SmartThings CLI)

- **`src/edidio_frames.lua`** — the zero-dependency eDIDIO frame encoder (the same
  byte-verified Lua used by the ELAN driver).
- **`src/edidio_commands.lua`** — turns switch/level commands into frames over an
  injected socket. **Byte-verified** by running the real Lua (see Testing).
- **`src/init.lua`** — the Edge driver: SmartThings capability handlers →
  `edidio_commands` over `cosock` TCP.
- **`profiles/edidio-light.yml`** — device profile (switch + switchLevel +
  controller/line/address/group preferences).

**Packaging/deploying needs the [SmartThings CLI](https://developer.smartthings.com/docs/sdks/edge/cli-setup)**
(hub-side Lua can't be run/installed without it):

```bash
smartthings edge:drivers:package .
smartthings edge:drivers:install        # to your hub
```

Then in the SmartThings app, add a device using this driver and set the
**controller IP**, **line**, and **address** or **group** in its settings.

## Testing

The command/frame logic ships as Lua, so it's verified by running the **actual
Lua** (via the `lupa` embedded interpreter) — not a reimplementation:

```bash
python -m pip install lupa pytest
python -m pytest -q
```

`test/test_commands_lua.py` asserts every command's frame byte-for-byte against
the shared reference encoder, and the 0–100% → 0–254 dimmer scaling. (The
`init.lua` capability handlers need the SmartThings `st`/`cosock` runtime; the
tested part is the frame logic, which is the driver's real work.)

## Files

```
SmartThings Edge/
├── config.yml                  # driver package config
├── profiles/edidio-light.yml   # device profile (switch + level + prefs)
├── src/
│   ├── init.lua                # Edge driver (capability handlers -> cosock TCP)
│   ├── edidio_commands.lua     # command -> frame over injected socket (tested)
│   └── edidio_frames.lua       # zero-dependency byte-verified encoder
└── test/
```

## Notes

- Local execution (hub-side) — control works even if the internet is down.
- Command-oriented; polling live fixture state back into SmartThings is a possible
  future addition.

## License

MIT
