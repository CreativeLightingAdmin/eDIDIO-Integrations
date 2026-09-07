# eDIDIO MQTT Bridge

A lightweight service that exposes Control Freak **eDIDIO** lighting on **MQTT** —
the lingua franca of IoT and smart home. It subscribes to command topics and
translates them into eDIDIO commands (DALI levels, groups, scenes), and can
publish **Home Assistant MQTT auto-discovery** so your lights and scenes appear
in Home Assistant automatically, with no HA YAML.

> **Target:** IoT & smart home — Home Assistant, openHAB, Node-RED, and anything
> that speaks MQTT.
> **Tech:** Python + `paho-mqtt`, wrapping the shared `edidio_control_py` engine.

## How it works

```
Home Assistant / any MQTT client
        │  publish edidio/kitchen/set = ON
        ▼
   MQTT broker ──▶  MQTT Bridge ──eDIDIO protobuf over TCP/TLS──▶  eDIDIO ──▶ fixtures
                        │
                        └─ publishes retained HA discovery configs +
                           optimistic state back to the broker
```

- Each configured **entity** (a DALI address, a group, or a stored scene) becomes
  MQTT command topics and, if discovery is on, a Home Assistant entity.
- Commands are converted to lighting *intents* and sent to the controller over a
  persistent, auto-reconnecting connection (keep-alive via `edidio_control_py`).
- The bridge is command-oriented: it echoes **optimistic state** back so HA
  reflects changes immediately (it doesn't yet poll live fixture state).

## Setup

```bash
cd "MQTT Bridge"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py   # dev: shared engine

cp config.example.yaml config.yaml   # then edit
python run.py --config config.yaml
```

Requires **Python >= 3.9** and an MQTT broker (e.g. Mosquitto, or the Home
Assistant Mosquitto add-on). On Windows use `py -3`.

## Configuration (`config.yaml`)

Three sections — see `config.example.yaml` for a full annotated file.

### `mqtt`
| Key | Default | Description |
|-----|---------|-------------|
| `host`, `port` | `127.0.0.1`, `1883` | Broker address |
| `username`, `password` | — | Optional broker auth |
| `base_topic` | `edidio` | Prefix for command/state topics |
| `discovery` | `true` | Publish Home Assistant auto-discovery |
| `discovery_prefix` | `homeassistant` | Must match HA's discovery prefix |

### `controller`
| Key | Default | Description |
|-----|---------|-------------|
| `id` | `edidio1` | Used in HA device identifiers |
| `host` | *(required)* | Controller IP/hostname |
| `port` | `23` | `23` = plain TCP, `443` = TLS |
| `use_tls` | `false` | Connect over TLS |

### `entities`
| `type` | Fields | Becomes |
|--------|--------|---------|
| `light` | `line` + (`address` **or** `group`) | HA **light** with on/off + brightness (0-254) |
| `scene` | `line`, `scene` [, `group`] | HA **scene** (stateless trigger; broadcast or on a group) |

## Topics

For an entity `id: kitchen` under `base_topic: edidio`:

| Topic | Direction | Payload |
|-------|-----------|---------|
| `edidio/kitchen/set` | in | `ON` / `OFF` |
| `edidio/kitchen/brightness/set` | in | `0`–`254` |
| `edidio/kitchen/state` | out (retained) | `ON` / `OFF` |
| `edidio/kitchen/brightness` | out (retained) | `0`–`254` |
| `edidio/availability` | out (retained) | `online` / `offline` |

Scenes use just `edidio/<id>/set` (any payload triggers the recall).

## Home Assistant auto-discovery

With `discovery: true`, on connect the bridge publishes a retained config to
`homeassistant/<component>/edidio_<id>/<entity>/config` for every entity. Home
Assistant picks these up instantly and creates the lights/scenes under one
**eDIDIO** device — no `configuration.yaml` edits. Turning a light on/off or
setting brightness in HA drives the fixture; the bridge echoes state so the HA UI
stays in sync. `availability` marks the device online/offline.

## Testing

### Automated (no broker, no hardware)

```bash
python -m pytest -q
```

- `test_entities.py` — topic generation, discovery config correctness, and
  payload→intent for lights (address/group, on/off/brightness) and scenes, plus
  config validation.
- `test_bridge.py` — simulates inbound MQTT messages through the bridge with a
  fake dispatcher/publisher, asserting the right intents are dispatched and the
  right optimistic state is published (the full path minus broker + controller).

### With a broker (no eDIDIO needed)

Point `controller.host` at anything and watch conversions:

```bash
# subscribe to everything the bridge emits
mosquitto_sub -h 127.0.0.1 -t 'edidio/#' -t 'homeassistant/#' -v
# in another terminal, send a command
mosquitto_pub -h 127.0.0.1 -t 'edidio/kitchen/set' -m 'ON'
```

You'll see the discovery configs, the availability message, and the optimistic
state echoes. The bridge log shows `edidio/kitchen/set = 'ON' => dali_level`.

### End-to-end

With a real broker + eDIDIO: add the bridge, open Home Assistant, and confirm the
eDIDIO device and its lights/scenes appear automatically; toggle them and watch
the fixtures respond.

## Project layout

```
MQTT Bridge/
├── run.py                     # entry point (CLI)
├── config.example.yaml        # annotated sample config
├── requirements.txt
├── edidio_mqtt/
│   ├── config.py              # YAML load + validation
│   ├── entities.py            # topics, HA discovery, payload->intent (pure)
│   ├── bridge.py              # transport-agnostic routing (testable)
│   ├── dispatcher.py          # async worker wrapping edidio_control_py
│   └── mqtt_runner.py         # paho-mqtt wiring
└── tests/                     # entity + bridge routing tests
```

## Notes

- Reuses the Modbus gateway's architecture (config map → dispatcher →
  `edidio_control_py`); the MQTT-specific bit is the broker wiring + HA discovery.
- Reaches openHAB, Node-RED, and most IoT platforms too — anything that can
  publish to the command topics.
- Optimistic state only (no live fixture polling yet) — a possible future
  enhancement once the controller's status responses are decoded.

## License

MIT
