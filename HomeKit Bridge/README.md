# eDIDIO HomeKit Bridge

Exposes Control Freak **eDIDIO** lighting as native **Apple HomeKit** accessories
— lights and scenes — for local Siri and iOS Home app control. Runs on your
network with **no cloud**, built on HAP-python and the shared `edidio_control_py`
engine.

> **Target:** High-end residential & smart home (pairs naturally with the RTI /
> Control4 segment; gives Siri for free).
> **Tech:** Python + HAP-python, wrapping `edidio_control_py`.

## How it works

```
iOS Home app / Siri  ──HAP (local)──▶  HomeKit Bridge  ──eDIDIO protobuf/TCP──▶  eDIDIO ──▶ fixtures
```

- Each configured accessory (a DALI address, a group, or a stored scene) becomes
  a HomeKit **lightbulb** or **scene switch** under one **eDIDIO** bridge device.
- HomeKit characteristic changes (On, Brightness) are converted to lighting
  *intents* and sent over a persistent, auto-reconnecting connection.
- Everything is local — HomeKit does not route lighting through the cloud.

## Setup

```bash
cd "HomeKit Bridge"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py   # dev: shared engine

cp config.example.yaml config.yaml   # then edit
python run.py --config config.yaml
```

Requires **Python >= 3.9**. On Windows use `py -3`. The host running the bridge
must be reachable by your iOS device (same LAN, mDNS/Bonjour allowed).

### Pairing

On start, the bridge prints its pairing code (default `031-45-154`):

```
Enter this code in your HomeKit app on your iOS device: 031-45-154
```

In the iOS **Home** app: **Add Accessory → More options… →** select **eDIDIO →**
enter the code. Your lights and scenes appear under the eDIDIO device. (Install
`HAP-python[QRCode]` to also print a scannable QR code.)

## Configuration (`config.yaml`)

### `homekit`
| Key | Default | Description |
|-----|---------|-------------|
| `name` | `eDIDIO` | Bridge name shown in Home |
| `pincode` | `031-45-154` | Pairing code (`XXX-XX-XXX`) |
| `port` | `51826` | HAP TCP port |
| `persist_file` | `edidio_homekit.state` | Stores the pairing — keep it, don't commit |

### `controller`
| Key | Default | Description |
|-----|---------|-------------|
| `host` | *(required)* | eDIDIO IP/hostname |
| `port` | `23` | `23` = plain TCP, `443` = TLS |
| `use_tls` | `false` | Connect over TLS |

### `accessories`
| `type` | Fields | HomeKit |
|--------|--------|---------|
| `light` | `line` + (`address` **or** `group`) | Lightbulb (On + Brightness 0–100 % → arc 0–254) |
| `scene` | `line`, `scene` [, `group`] | Momentary switch that recalls the scene |

**Line** is the physical daughter-board slot (1–4).

## Testing

### Automated (no pairing, no hardware)

```bash
python -m pytest -q
```

- `test_specs.py` — brightness→arc conversion, address/group/scene intents, and
  config validation.
- `test_accessories.py` — builds **real HAP accessories** with an offline driver
  and fires HomeKit characteristic writes (`client_update_value`), asserting the
  correct intents reach the dispatcher (no mDNS, no controller).

### Live

Run the bridge and pair with the Home app. Toggling a light, dragging its
brightness, or tapping a scene should change the fixtures. Siri (“Hey Siri, turn
on the Kitchen”) works once paired. Point `controller.host` at a real eDIDIO to
see fixtures respond; a wrong/offline controller is non-fatal (the bridge stays
paired and retries).

> **Re-pairing:** delete the `*.state` file to reset pairing (you'll then add the
> bridge again in Home).

## Project layout

```
HomeKit Bridge/
├── run.py                     # entry point (CLI)
├── config.example.yaml        # annotated sample config
├── requirements.txt
├── edidio_homekit/
│   ├── config.py              # YAML load + validation
│   ├── specs.py               # accessory specs -> intents (pure)
│   ├── accessories.py         # HAP Lightbulb/Switch accessories
│   ├── bridge.py              # the eDIDIO bridge accessory (owns the dispatcher)
│   ├── dispatcher.py          # async worker wrapping edidio_control_py
│   └── runner.py              # AccessoryDriver wiring
└── tests/
```

## Notes

- HomeKit runs locally and gives **Siri** without any cloud service — the most
  cost-effective voice option for eDIDIO.
- Command-oriented: brightness/on-off state is driven from HomeKit; the bridge
  doesn't yet poll live fixture state back into HomeKit.
- Same dispatcher/engine as the Modbus, MQTT and KNX gateways.

## License

MIT
