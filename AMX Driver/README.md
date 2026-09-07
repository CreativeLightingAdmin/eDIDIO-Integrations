# eDIDIO AMX Driver (Muse + NetLinx)

AMX integration for Control Freak **eDIDIO** lighting — DALI, DMX and
SpektraPlus — for **both** modern AMX Muse and legacy NetLinx platforms.

> **Target:** Commercial boardrooms, education, council chambers.

```
AMX Driver/
├── muse/       # AMX Muse (Python) driver
└── netlinx/    # Legacy NetLinx (.axi/.axs) module
```

Both speak the same eDIDIO wire protocol (frames verified byte-for-byte against
`edidio_control_py`), so they behave identically on the device.

---

## Muse (Python)

AMX Muse runs full CPython on Linux, so the Muse driver talks to the controller
over a standard TCP socket and reuses the zero-dependency `edidio_frames.py`
encoder — no third-party packages needed.

### Use in a Muse program

```python
from edidio_muse import EdidioController

lights = EdidioController("192.168.1.50")   # plain TCP, port 23
lights.connect()

lights.set_level(line=1, address=5, level=254)      # address 5 -> full
lights.set_group_level(line=1, group=0, level=128)  # group 0 -> 50%
lights.recall_scene(line=1, scene=3)                # recall scene 3
lights.dmx_color(line=2, hex="#FF0000")             # paint line 2 red
lights.spektra(zone=1, target="sequence", index=0, action="start")
lights.spektra_stop(zone=1)
```

Add `muse/edidio_frames.py` and `muse/edidio_muse.py` to your Muse project.

### Control API

| Method | Description |
|--------|-------------|
| `connect()` / `disconnect()` | Open/close; connect starts the keep-alive heartbeat. |
| `set_level(line, address, level)` | DALI address (0-63) → arc level (0-254). |
| `set_group_level(line, group, level)` | DALI group (0-15) → arc level. |
| `on/off(line, address)` | Turn an address on (max) / off. |
| `command(line, address, cmd, arg=0)` | Named/numeric DALI command. |
| `recall_scene(line, scene, group=None)` | Recall a scene (broadcast or on a group). |
| `dmx_levels(line, levels, channel, repeat, zone, fade_ms)` | Raw DMX channel levels. |
| `dmx_color(line, hex, fixtures, zone, fade_ms)` | RGB `#RRGGBB` across a line. |
| `spektra(zone, target, index, action)` | SpektraPlus sequence/theme/static. |
| `spektra_stop(zone)` | Stop playback and turn output off. |

### Test off-device

```bash
cd "AMX Driver/muse"
python -m pip install pytest
python -m pip install -e ../../../edidio_control_py   # optional: enables live byte comparison
python -m pytest -q
```

Tests inject a fake transport to assert the exact frames, and include a real
loopback-socket round-trip. To try against hardware, run the Muse IDE's local
debug tool, point `EdidioController` at an eDIDIO on your LAN, and call methods.

---

## NetLinx (.axi / .axs)

For legacy NetLinx masters. `eDIDIO.axi` is a self-contained include that opens a
TCP client, builds eDIDIO frames, and runs the keep-alive heartbeat.

### Use in a NetLinx program

```netlinx
#INCLUDE 'eDIDIO'

DEFINE_START
    fnEdConnect('192.168.1.50')      // opens the socket; keep-alive auto-starts

// ... from a button event:
    fnEdSetLevel(1, 5, 254)          // line 1, address 5 -> full
    fnEdSetGroupLevel(1, 0, 128)     // line 1, group 0 -> 50%
    fnEdRecallScene(1, 3)            // recall scene 3
    fnEdDmxColour(2, $FF, $00, $00, 170)   // line 2 -> red
    fnEdSpektraSequence(1, 0, ED_SPK_START)
    fnEdSpektraStop(1)
```

See `eDIDIO_Example.axs` for a complete touch-panel example.

By default the include uses virtual device `dvEDIDIO = 0:3:0` and TCP port 23
(change `ED_TCP_PORT` for TLS-capable units). Compile with **NetLinx Studio v4**.

### Available functions

`fnEdConnect(ip)`, `fnEdDisconnect()`, `fnEdSetLevel(line,addr,level)`,
`fnEdSetGroupLevel(line,group,level)`, `fnEdOn/Off(line,addr)`,
`fnEdRecallScene(line,scene)`, `fnEdRecallSceneOnGroup(line,group,scene)`,
`fnEdDmxColour(line,r,g,b,fixtures)`, `fnEdSpektraSequence(zone,index,action)`,
`fnEdSpektraStop(zone)`.

### How the frames are verified

NetLinx can't be unit-tested in this repo, so the byte-building **algorithm** was
validated separately: `netlinx/_netlinx_mirror.py` re-implements the exact
integer/byte operations used in `eDIDIO.axi` (varint via integer division by 128,
`field*8` tags, `n/256` length), and its test asserts they produce the same
known-good reference frames as `edidio_control_py`.

```bash
cd "AMX Driver/netlinx"
python -m pytest test_netlinx_mirror.py -q
```

To verify on the bench: in NetLinx Studio v4's diagnostics, enable string
notifications on `dvEDIDIO` and confirm a call such as `fnEdSetLevel(1,5,200)`
emits `CD 00 0E 08 xx 92 01 09 08 01 10 05 30 00 48 C8 01` (the `xx` message-id
byte increments per send), then confirm the fixture responds.

---

## License

MIT
