# eDIDIO OSC Bridge

Control Control Freak **eDIDIO** lighting from **OSC** (Open Sound Control) —
bridging show-control and media tools (QLab, TouchDesigner, Resolume, TouchOSC,
ETC/Eos consoles, Medialon, Isadora…) to DALI/DMX/SpektraPlus.

> **Target:** Entertainment & show control — theatre, live events, experiential,
> museums. Complements eDIDIO's existing Art-Net / sACN / DMX support with a
> command/trigger layer.
> **Tech:** Python + `python-osc`, wrapping the shared `edidio_control_py` engine.

## How it works

```
QLab / TouchDesigner / TouchOSC …  ──OSC (UDP)──▶  OSC Bridge  ──eDIDIO protobuf/TCP──▶  eDIDIO ──▶ fixtures
                                                        │
                                                        └─ OSC address map (config.yaml)
```

- Each OSC **address** maps to an eDIDIO action (level, group, scene, Spektra).
- **Faders** (float `0.0`–`1.0`) map to DALI arc levels; **buttons/bangs** trigger
  scenes and Spektra playback (fire on arg `> 0`, ignore release `0`).
- Commands go to the controller over a persistent, auto-reconnecting connection.

## Setup

```bash
cd "OSC Bridge"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py   # dev: shared engine

cp config.example.yaml config.yaml   # then edit
python run.py --config config.yaml
```

Requires **Python >= 3.9**. On Windows use `py -3`.

## Configuration (`config.yaml`)

### `osc`
| Key | Default | Description |
|-----|---------|-------------|
| `host` | `0.0.0.0` | UDP bind address |
| `port` | `8000` | OSC listen port |

### `controller`
| Key | Default | Description |
|-----|---------|-------------|
| `host` | *(required)* | eDIDIO IP/hostname |
| `port` | `23` | `23` = plain TCP, `443` = TLS |
| `use_tls` | `false` | Connect over TLS |

### `addresses`
| `action` | Fields | Arg |
|----------|--------|-----|
| `dali_level` | `line`, `address_dali` | level (float 0–1 → arc, or int 0–254) |
| `dali_group_level` | `line`, `group` | level |
| `dali_scene` | `line`, `scene` [, `group`] | trigger (`>0` fires) |
| `spektra` | `zone`, `type`, `index`, `spektra_action` | trigger |
| `spektra_stop` | `zone` | trigger |

(`address_dali` is the DALI short address, kept distinct from the OSC `address`.)

## Sending OSC

From any OSC source, send to the bridge's IP:port with the configured addresses:

```
/edidio/kitchen/level  0.8      # fader -> ~80% on DALI address 5
/edidio/living/level   1.0      # group 0 to full
/edidio/scene/movie    1        # recall scene 3
/edidio/seq/start      1        # start SpektraPlus sequence 0 on zone 1
```

**QLab:** use a *Network* cue (OSC), message e.g. `/edidio/scene/movie 1`.
**TouchOSC / TouchDesigner:** map a fader to `/edidio/.../level` and buttons to the
scene/Spektra addresses.

## Testing

### Automated (no OSC source, no hardware)

```bash
python -m pytest -q
```

- `test_oscmap.py` — arg→level conversion (float/int), scene/Spektra trigger vs
  release, and config validation.
- `test_bridge.py` — routing with a fake dispatcher **plus a real UDP round-trip**:
  a `python-osc` client sends to the actual server and we assert the correct
  intents are produced (no eDIDIO needed).

### Live

Run the bridge, point an OSC source at `host:8000`, and send messages — the log
shows `OSC /edidio/scene/movie (1,) => dali_scene`. With a controller connected,
the fixtures respond.

## Project layout

```
OSC Bridge/
├── run.py                     # entry point (CLI)
├── config.example.yaml
├── requirements.txt
├── edidio_osc/
│   ├── config.py              # YAML load + validation
│   ├── oscmap.py              # address + args -> intent (pure)
│   ├── bridge.py              # routing (testable)
│   ├── dispatcher.py          # async worker wrapping edidio_control_py
│   └── osc_server.py          # python-osc (AsyncIO) wiring
└── tests/
```

## Notes

- Same architecture as the Modbus/MQTT/KNX gateways (map → dispatcher →
  `edidio_control_py`); the OSC-specific part is the `python-osc` server.
- Command-oriented (OSC → eDIDIO). OSC feedback out (e.g. to motorised faders) is
  a possible future addition.

## License

MIT
