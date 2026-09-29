# eDIDIO Bitfocus Companion Module

A [Bitfocus Companion](https://bitfocus.io/companion) module for controlling
Control Freak **eDIDIO** lighting from Stream Deck / Companion surfaces — big in
live events, broadcast and AV control rooms.

> **Target:** Live events / broadcast / AV.
> **Tech:** Node module (`@companion-module/base`) that sends **byte-verified
> eDIDIO frames directly over TCP/TLS** — no gateway required.

## Actions

| Action | Options |
|--------|---------|
| DALI: Set level | line, address, level |
| DALI: Set group level | line, group, level |
| DALI: Command | line, address, command (off/on/max/min/fade…) |
| DALI: Recall scene | line, scene, group (blank = broadcast) |
| DMX: Colour | line, `#RRGGBB` |
| SpektraPlus: Control | zone, type, index, action |
| SpektraPlus: Stop (and off) | zone |

**Config:** controller IP, port (23 TCP / 443 TLS), TLS on/off, live feedback
on/off. The module shows its connection status and keeps the socket alive
automatically.

## Feedbacks & variables (firmware 1.4.0+)

The module subscribes to the controller's live event stream, so buttons reflect
the **real** state — including changes from wall panels, schedules or SpektraPlus.

| Feedback | Options | True when |
|---|---|---|
| DALI: Light state | line, target (address/group/broadcast), id, when (on / off / level at least N) | the last level seen on the bus matches |
| SpektraPlus: Playing | zone, index (blank = any) | a sequence/theme is running in the zone |

Variables are created as targets are first seen:

| Variable | Value |
|---|---|
| `$(edidio:level_l1_a5)` | line 1, address 5 level (0–254, or `on` when unknown) |
| `$(edidio:level_l1_g3)` / `$(edidio:level_l1_bc)` | group 3 / broadcast |
| `$(edidio:spektra_z0)` | index playing on zone 0 (blank when stopped) |
| `$(edidio:last_input)` | last input pressed |

## Install (development)

Companion loads "dev" modules from a folder you point it at:

```bash
cd "Companion Module"
npm install
```

In Companion: **Settings → Developer modules path →** select this folder's
parent, then add a connection for **Control Freak: eDIDIO** and set the
controller IP. Map buttons to the actions above.

## Testing

```bash
npm test        # node --test
```

`test/actions.test.js` verifies every action builds the correct eDIDIO frame
(byte-for-byte against the shared encoder) and that the action definitions expose
working callbacks. The Companion runtime glue in `main.js` (status, config) needs
Companion itself to exercise — the tested part is the action→frame logic, which
is the module's real work.

## Files

```
Companion Module/
├── main.js                # Companion InstanceBase (config, actions, status)
├── companion/manifest.json
├── src/
│   ├── actions.js         # action defs + buildFrame (pure, tested)
│   ├── connection.js      # TCP/TLS + keep-alive + reconnect
│   └── edidio_frames.js   # zero-dependency byte-verified encoder
└── test/
```

## License

MIT
