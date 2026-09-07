# eDIDIO Extron ControlScript Driver

An Extron **ControlScript** (Global Scripter) module for controlling Control
Freak **eDIDIO** lighting from Extron control processors — DALI, DMX and
SpektraPlus, over the controller's native TCP/TLS protocol.

> **Target:** Corporate, government and higher-education AV.
> **Tech:** Python for Extron ControlScript, using `EthernetClientInterface`.

## Why a pure-Python frame encoder?

Extron control processors run a **constrained** embedded Python: no `pip`, no
C-extensions, so the `edidio_control_py` library (which needs the `protobuf`
runtime and `asyncio`) can't run there. This driver therefore ships a
**zero-dependency** frame encoder, `edidio_frames.py`, that hand-builds the
eDIDIO protobuf frames.

`edidio_frames.py` is verified **byte-for-byte** against `edidio_control_py`
(see `tests/test_frames.py`), so it produces exactly the same wire data — it just
does it without any dependencies.

## Files

```
Extron Driver/
├── edidio_frames.py      # zero-dependency eDIDIO frame encoder (the core)
├── edidio_extron.py      # ControlScript driver: EdidioController + control API
├── extronlib_stub/       # minimal extronlib stand-in for OFF-DEVICE testing only
├── tests/                # byte-equality + driver logic tests
└── requirements-dev.txt  # test-only deps (the driver has none)
```

## Using it in ControlScript Studio

1. Add `edidio_frames.py` and `edidio_extron.py` to your ControlScript project.
   (Do **not** add `extronlib_stub/` — the device provides the real `extronlib`.)
2. Create a controller and wire it to your UI:

```python
from extronlib import event
from extronlib.ui import Button
from extronlib.device import UIDevice

from edidio_extron import EdidioController

tp = UIDevice("TouchPanel")
lights = EdidioController("192.168.1.50")   # plain TCP (port 23)
lights.connect()

btn_on = Button(tp, 1)
btn_scene = Button(tp, 2)

@event(btn_on, "Pressed")
def _(button, state):
    lights.set_level(line=1, address=5, level=254)   # address 5 to full

@event(btn_scene, "Pressed")
def _(button, state):
    lights.recall_scene(line=1, scene=3)             # recall scene 3
```

For a TLS controller, use `EdidioController("192.168.1.50", port=443, protocol="SSL")`.

## Control API (`EdidioController`)

| Method | Description |
|--------|-------------|
| `connect(timeout=5)` / `disconnect()` | Open/close the connection; connect starts the keep-alive heartbeat. |
| `set_level(line, address, level)` | DALI address (0-63) to arc level (0-254). |
| `set_group_level(line, group, level)` | DALI group (0-15) to arc level. |
| `on(line, address)` / `off(line, address)` | Turn an address on (max) / off. |
| `command(line, address, cmd, arg=0)` | Named/numeric DALI command (`off, on, max, min, fade_up, fade_down, step_up, step_down, recall_last, identify`). |
| `recall_scene(line, scene, group=None)` | Recall a scene — broadcast on the line, or on a group. |
| `dmx_levels(line, levels, channel=1, repeat=1, zone=0, fade_ms=0)` | Write raw DMX channel levels (0-255). |
| `dmx_color(line, hex, fixtures=None, zone=0xFF, fade_ms=0)` | Paint an RGB `#RRGGBB` colour across a line. |
| `spektra(zone, target, index, action)` | SpektraPlus `sequence`/`theme`/`static`, `start`/`stop`/`pause`. |
| `spektra_stop(zone)` | Stop playback and turn the output off. |

- **Line** is the physical daughter-board slot (1-4).
- The controller sends a keep-alive heartbeat every 7 s (configurable via
  `keepalive_seconds`) and assigns rolling message IDs automatically.

## Testing

### Off-device (this repo, no hardware)

The bundled `extronlib_stub/` lets the driver run on a PC so its logic — and the
exact frames it emits — can be unit-tested:

```bash
cd "Extron Driver"
python -m pip install -r requirements-dev.txt
python -m pip install -e ../../edidio_control_py   # optional: enables live byte comparison
python -m pytest -q
```

The suite (1) checks every frame byte-for-byte against `edidio_control_py`, and
(2) drives `EdidioController` through the stub, asserting connect, each control
method's frame, keep-alive and disconnect.

### In ControlScript Studio's virtual runtime

Load the module in Studio's built-in Python virtual runtime, point
`EdidioController` at an eDIDIO on your LAN, and call methods from the debug
console (e.g. `lights.set_level(1, 5, 254)`) — watch the fixture respond and the
console for send confirmation.

### On the device

Deploy to the processor, connect, and trigger a scene from a touch panel or the
diagnostic console; verify the lighting responds.

## License

MIT
