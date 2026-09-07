# eDIDIO Integration Test Harness

One tool to validate the whole integration stack against a **real eDIDIO
controller**. Both gateways ultimately send the same protobuf frames to the
device, so this harness checks each layer independently:

| Layer | What it proves |
|-------|----------------|
| `library` | The controller + protocol work directly via `edidio_control_py`. If this fails, the gateways can't work either — start here. |
| `modbus` | The Modbus gateway converts register writes into lighting commands. |
| `rest` | The REST gateway routes HTTP requests to the controller. |
| `discover` | Controllers are reachable on the LAN (UDP broadcast). |
| `all` | A one-shot connectivity sweep across the above. |

**Safe by default:** every command only connects / reads unless you pass
`--actuate`. Actuation always requires an explicit target (`--address`,
`--group`, or `--scene`) so nothing is ever guessed.

## Setup

```bash
cd "Test Harness"
python -m pip install -r requirements.txt
# dev: use the local library + match the Modbus gateway's pin
python -m pip install -e ../../edidio_control_py
```

On Windows use `py -3` instead of `python`.

## Quick start

```bash
# 1. Find the controller on the network
python harness.py discover

# 2. Prove the device works directly (read-only: connect + keep-alive)
python harness.py library --host 192.168.1.50

# 3. Actuate: blink DALI address 5 on line 1 (max, hold, then off)
python harness.py library --host 192.168.1.50 --actuate --line 1 --address 5 --blink

# 4. Or let discovery pick the device and recall a scene
python harness.py library --discover --actuate --line 1 --scene 3
```

## Testing each layer

### Library (direct control)

```bash
python harness.py library --host 192.168.1.50 [--tls] [--port 443]
python harness.py library --discover                       # auto-select first found
python harness.py library --host IP --actuate --line 1 --address 5 --level 200
python harness.py library --host IP --actuate --line 1 --group 0 --blink --hold 2
python harness.py library --host IP --actuate --line 1 --scene 3
```

`--tls` uses port 443 (or pass `--port`). With `--discover`, the device's
advertised TLS capability and line-type map are read automatically.

### Modbus gateway

Start the gateway first (`Modbus TCPRTUGateway/`), configured with your
controller IP, then:

```bash
python harness.py modbus --host 127.0.0.1 --port 5020            # connect + read register 1
python harness.py modbus --host 127.0.0.1 --port 5020 --actuate --register 1 --value 200
```

The harness writes the holding register; the **gateway log** shows the
conversion (e.g. `Register 1 <- 200 => dali_group_level`) and the fixture
responds. `--register` is the 1-based number (40001 => `1`).

### REST gateway

Start the gateway first (`Rest API Gateway/`), then:

```bash
python harness.py rest --url http://localhost:8080 [--api-key KEY]
python harness.py rest --url http://localhost:8080 --api-key KEY \
    --actuate --controller 192.168.1.50 --line 1 --group 0 --level 200
python harness.py rest --url http://localhost:8080 --actuate --controller IP --line 1 --scene 3
```

`--controller` targets a specific device; omit it to use the gateway's default
(`EDIDIO_IP`). The harness maps the target to the right endpoint
(`/dali/level`, `/dali/group/level`, or `/dali/scene`).

### Connectivity sweep

```bash
python harness.py all --host 192.168.1.50 \
    --url http://localhost:8080 --mb-host 127.0.0.1 --mb-port 5020
```

Runs discovery, a read-only library connect, a REST health/discovery check, and
a Modbus read — a fast "is everything wired up?" pass. Add `--actuate` +a target
to also exercise control through the library.

## Target reference

| Flag | Range | Notes |
|------|-------|-------|
| `--line` | 1–4 | Physical daughter-board slot (required for any actuation) |
| `--address` | 0–63 | DALI short address |
| `--group` | 0–15 | DALI group |
| `--scene` | 0–15 | Scene to recall (broadcast, or on `--group`) |
| `--level` | 0–254 | Arc level (default 254) |
| `--blink` | — | Library only: after setting a level, wait `--hold`s then set 0 |

Precedence when several are given: **scene > address > group**.

## Recommended first-run flow with new hardware

1. `discover` — confirm the device is found and note its line-type map.
2. `library --host <ip>` — confirm connect works (read-only).
3. `library --host <ip> --actuate --line <L> --address <A> --blink` — confirm you
   can visibly control a known fitting.
4. Start each gateway and repeat control through `modbus` / `rest`.

If step 2 fails, it's the device/network — not the gateways.

## Files

```
Test Harness/
├── harness.py       # the CLI (discover / library / modbus / rest / all)
├── discovery.py     # UDP discovery (Python port of the JS engine's probe)
├── requirements.txt
└── README.md
```

## Notes

- Discovery assumes a `/24` subnet when probing (the common case on lighting
  LANs). If a device isn't found, pass its IP with `--host` instead.
- `discovery.py` is standalone (`python discovery.py`) and is a useful basis for
  adding UDP discovery to the Python-based drivers later.
