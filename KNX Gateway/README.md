# eDIDIO KNX Gateway

A middleware service that bridges a **KNX** installation to Control Freak
**eDIDIO** lighting. It connects to the KNX bus over **KNXnet/IP**, listens for
group-address telegrams, and translates them into eDIDIO commands (DALI levels,
groups, scene recall).

> **Target:** Commercial & European building automation — the dominant standard
> where eDIDIO otherwise has no direct story.
> **Tech:** Python + `xknx`, wrapping the shared `edidio_control_py` engine.

## No KNX certification needed

KNX is an **open** standard (ISO/IEC 14543-3 / EN 50090). This gateway is a
standard **KNXnet/IP client** — the same approach Home Assistant's KNX
integration uses, via the open-source `xknx` library. It connects to the
customer's existing **KNXnet/IP router/interface** (present in any KNX-IP
installation); it is **not** a native bus device and needs no ETS programming of
its own and no KNX Association membership. (Using the "KNX Certified" logo or
making eDIDIO a native ETS-programmable TP device are separate, optional steps.)

## How it works

```
KNX bus  ──group telegram──▶  KNXnet/IP router  ──▶  KNX Gateway  ──eDIDIO protobuf/TCP──▶  eDIDIO ──▶ fixtures
                                                          │
                                                          └─ group-address map (config.yaml)
```

- The KNX integrator assigns **group addresses** in ETS (as normal). You map each
  one to an eDIDIO action in `config.yaml` — just like the Modbus register map.
- Telegrams are decoded by their **DPT** (datapoint type) and converted to
  lighting *intents*, sent over a persistent, auto-reconnecting connection.

## Setup

```bash
cd "KNX Gateway"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py   # dev: shared engine

cp config.example.yaml config.yaml   # then edit
python run.py --config config.yaml
```

Requires **Python >= 3.9** and access to the KNX bus via KNXnet/IP. On Windows
use `py -3`.

## Configuration (`config.yaml`)

### `knx`
| Key | Description |
|-----|-------------|
| `connection` | `automatic` (discover a gateway), `tunnelling` (to `gateway_ip`), or `routing` (multicast) |
| `gateway_ip`, `gateway_port` | KNXnet/IP router/interface (tunnelling); port default `3671` |

### `controller`
| Key | Default | Description |
|-----|---------|-------------|
| `host` | *(required)* | eDIDIO IP/hostname |
| `port` | `23` | `23` = plain TCP, `443` = TLS |
| `use_tls` | `false` | Connect over TLS |

### `group_addresses`
Each entry maps a KNX group address to an eDIDIO action. `dpt` tells the gateway
how to read the telegram value:

| `dpt` | KNX DPT | Value → |
|-------|---------|---------|
| `switch` | 1.001 | on/off |
| `scaling` | 5.001 | 0–100 % dimming → arc level 0–254 |
| `scene_number` | 17.001 | scene index → recall that scene (0–15) |

| `action` | Fields | Valid `dpt` |
|----------|--------|-------------|
| `dali_level` | `line`, `dali_address` | `scaling`, `switch` |
| `dali_group_level` | `line`, `group` | `scaling`, `switch` |
| `dali_scene` | `line` [, `group`] | `switch` (needs fixed `scene`), `scene_number` (scene from telegram) |

(`ga` is the KNX group address, e.g. `1/1/1`; `dali_address` is the DALI short
address, kept distinct to avoid confusion.)

## Testing

### Automated (no KNX bus, no hardware)

```bash
python -m pytest -q
```

- `test_group_map.py` — DPT→level/scene conversions and config validation
  (including KNX group-address range checks).
- `test_bridge.py` — feeds **constructed xknx telegrams** (DPTArray/DPTBinary,
  GroupValueWrite/Read) through the bridge with a fake dispatcher, asserting the
  correct intents (and that reads / unmapped GAs / out-of-range scenes are
  ignored).

### Live, without any KNX hardware — the sender tool

`tools/send_telegram.py` injects a KNX telegram so you can verify the gateway
end-to-end with **no KNX bus, router, or actuators**. Run the gateway in
**routing** mode (multicast) and fire telegrams at your mapped group addresses:

```bash
# terminal 1 — gateway in routing mode
python run.py --config config.yaml          # set knx.connection: routing

# terminal 2 — send telegrams
python tools/send_telegram.py --ga 1/1/1 --dpt scaling --value 80     # 80% dim
python tools/send_telegram.py --ga 1/1/2 --dpt switch  --value on
python tools/send_telegram.py --ga 3/2/1 --dpt scene_number --value 3
```

The gateway logs the conversion (`GA 1/1/1 (Kitchen dimming) = 204 => dali_level`)
and, with a controller connected, the fixture responds. Routing uses KNXnet/IP
multicast (`224.0.23.12`), so two software endpoints on the same LAN see each
other — no gateway/router required. (For tunnelling, add
`--connection tunnelling --gateway-ip <router>`.)

> **Scene numbers:** the tool sends DPT 17.001 like a real KNX device — `--value 3`
> puts wire byte `2` on the bus (DPT 17.001 is 1-based in ETS, 0-based on the
> wire), so the gateway recalls eDIDIO **scene 2**. Keep this offset in mind when
> mapping ETS scene numbers.

### With ETS / a real KNX tool

Point `controller.host` anywhere and watch the log. From ETS or any KNX group
monitor, send a value to a mapped group address; the gateway logs the conversion.
Add a real controller to see the fixture respond.

## Project layout

```
KNX Gateway/
├── run.py                     # entry point (CLI)
├── config.example.yaml        # annotated sample config
├── requirements.txt
├── edidio_knx/
│   ├── config.py              # YAML load + validation
│   ├── group_map.py           # GA + DPT + action -> intent (pure)
│   ├── bridge.py              # telegram -> intent routing (testable)
│   ├── dispatcher.py          # async worker wrapping edidio_control_py
│   └── knx_runner.py          # xknx (KNXnet/IP) wiring
├── tools/
│   └── send_telegram.py       # inject a KNX telegram to test without hardware
└── tests/
```

## Notes

- Same architecture as the Modbus and MQTT gateways (config map → dispatcher →
  `edidio_control_py`); the KNX-specific part is the `xknx` wiring + DPT decoding.
- Command-oriented (KNX → eDIDIO). Reflecting eDIDIO state back onto KNX status
  group addresses is a possible future enhancement.

## License

MIT
