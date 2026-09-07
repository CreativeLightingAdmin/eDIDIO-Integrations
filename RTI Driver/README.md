# eDIDIO RTI Driver (Integration Designer 11)

A JavaScript driver for **RTI Integration Designer 11** to control Control Freak
**eDIDIO** lighting — DALI, DMX and SpektraPlus — with two-way connection
feedback, built for RTI's JavaScript Driver Development Kit (DDK).

> **Target:** High-end residential, boutique commercial.

## Design

RTI control processors run a **constrained JavaScript engine** (no npm, no
protobuf runtime), so this driver ships a **zero-dependency** frame encoder,
`src/edidio_frames.js`, that hand-builds the eDIDIO protobuf frames. It is
verified **byte-for-byte** against `edidio_control_py` (and matches the
Python/Extron/AMX encoders exactly).

```
RTI Driver/
├── src/
│   ├── edidio_frames.js         # zero-dependency eDIDIO frame encoder
│   ├── driver.js                # platform-independent driver logic (tested)
│   └── rti-binding.example.js   # example glue to RTI's DDK runtime
├── test/                        # Node byte-equality + driver logic tests
└── package.json
```

The lighting logic lives in `driver.js` as an `EdidioDriver` class that takes a
small injected `host` ({ `send`, `setVariable`, `log` }). This keeps all
behaviour unit-testable off-device; the RTI-specific wiring is a thin adapter.

## Building the `.rtidriver` in Integration Designer 11

1. In the DDK, create a new **two-way TCP/IP** driver. Set the connection to the
   controller IP, **port 23** (or 443 for TLS-capable units).
2. Add `edidio_frames.js` and `driver.js` to the driver script (include/concatenate
   them), then paste the adapter from `rti-binding.example.js` and replace the
   placeholder calls (`send`, `setVariable`, `log`, connection events, timer)
   with your DDK's actual runtime APIs.
3. Define these **driver commands** (map each to the `cmd*` functions):

   | Command | Args | Function |
   |---------|------|----------|
   | Set Level | line, address, level | `cmdSetLevel` |
   | Set Group Level | line, group, level | `cmdSetGroupLevel` |
   | Light On | line, address | `cmdOn` |
   | Light Off | line, address | `cmdOff` |
   | Recall Scene | line, scene | `cmdRecallScene` |
   | Recall Scene On Group | line, group, scene | `cmdRecallSceneOnGroup` |
   | DMX Colour | line, hex | `cmdDmxColor` |
   | Spektra | zone, target, index, action | `cmdSpektra` |
   | Spektra Stop | zone | `cmdSpektraStop` |

4. Define a **driver variable** `ConnectionStatus` (string) — the driver sets it
   to `Connected` / `Disconnected` for two-way feedback on your touchpanels.
5. Add a repeating timer (~7 s) calling `onTimerTick()` for the keep-alive.
6. Build/export the `.rtidriver` package.

## Control reference

`EdidioDriver` methods (called by the `cmd*` hooks):

- `setLevel(line, address, level)` — DALI address 0-63 to arc level 0-254.
- `setGroupLevel(line, group, level)` — DALI group 0-15 to arc level.
- `on(line, address)` / `off(line, address)`.
- `recallScene(line, scene, group?)` — broadcast, or on a group.
- `dmxColor(line, hex, fixtures?, zone?, fadeMs?)` — RGB `#RRGGBB` across a line.
- `dmxLevels(line, levels, channel?, repeat?, zone?, fadeMs?)` — raw channels.
- `spektra(zone, target, index, action)` — `sequence`/`theme`/`static`, `start`/`stop`/`pause`.
- `spektraStop(zone)` — stop and turn output off.
- `onConnect()` / `onDisconnect()` / `onData(bytes)` / `keepAlive()` — lifecycle.

**Line** is the physical daughter-board slot (1-4).

## Two-way feedback

The driver mirrors link state into the `ConnectionStatus` variable on
connect/disconnect, and stamps `LastActivity` when any bytes are received. This
control-focused driver does not yet decode the controller's protobuf status
responses into per-fixture levels — that's a future enhancement; the `onData`
hook is where it would go.

## Testing

### Off-device (this repo)

```bash
cd "RTI Driver"
node --test
```

The suite checks every frame byte-for-byte against the reference implementation
and drives `EdidioDriver` through a fake host, asserting each command's frame,
keep-alive gating, and connection-state feedback.

### In Integration Designer 11

Build a test interface, launch the **RTI Virtual Panel** emulator on your PC,
bind buttons to the driver commands, and point the driver at an eDIDIO on your
LAN. Moving a brightness slider or pressing a scene button should change the
lighting and update the `ConnectionStatus` feedback on the virtual panel.

## License

MIT
