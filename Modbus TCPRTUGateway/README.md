# eDIDIO Modbus TCP/RTU Gateway

A middleware service that exposes a **Modbus** (TCP or RTU) holding-register
interface for controlling Control Freak **eDIDIO** lighting. A BMS, PLC or SCADA
system writes standard Modbus registers on this gateway, and each mapped
register is translated into an eDIDIO lighting command (DALI levels, groups,
scene recall, SpektraPlus sequences/themes) over the controller's TCP/TLS
protobuf protocol.

> **Target:** Industrial BMS / building automation (Siemens, Schneider, Niagara,
> Distech, etc.).
> **Tech:** Python + `pymodbus`, wrapping the shared `edidio_control_py` engine.

## How it works

```
BMS / PLC  ──Modbus write (FC6/FC16)──▶  Gateway  ──eDIDIO protobuf over TCP/TLS──▶  eDIDIO ──▶ DALI/DMX fixtures
             holding registers 4xxxx        │
                                            └─ register map (config.yaml) resolves each
                                               register to a lighting command
```

- The gateway runs a Modbus **server** (slave). Your BMS is the Modbus **client**
  (master) and writes holding registers.
- Each write is looked up in a **register map** and converted to a normalized
  lighting *intent*, which an async worker sends to the controller over a
  persistent, auto-reconnecting connection (keep-alive handled by
  `edidio_control_py`).
- The value written to a register is the command parameter (a level, a scene
  number, an effect index) — see [Register actions](#register-actions).

## Setup

```bash
cd "Modbus TCPRTUGateway"
python -m pip install -r requirements.txt
# During development, install the shared engine in editable mode:
python -m pip install -e ../../edidio_control_py

cp config.example.yaml config.yaml   # then edit config.yaml
python run.py --config config.yaml
```

Requires **Python >= 3.9**. On Windows use `py -3` in place of `python`.

> **Port note:** the example uses TCP port `5020` so it runs without elevated
> privileges. The standard Modbus port is `502`, which requires admin/root.

## Configuration (`config.yaml`)

Three sections — see `config.example.yaml` for a complete annotated file.

### `server` — the Modbus interface this gateway exposes

| Key | Applies | Description |
|-----|---------|-------------|
| `type` | both | `tcp` or `rtu` |
| `unit_id` | both | Modbus unit/slave id (default `1`) |
| `host`, `port` | tcp | Bind address and TCP port |
| `port`, `baudrate`, `parity`, `stopbits`, `bytesize` | rtu | Serial device (e.g. `COM3`, `/dev/ttyUSB0`) and line settings |

### `controller` — the eDIDIO to drive

| Key | Default | Description |
|-----|---------|-------------|
| `host` | *(required)* | Controller IP/hostname |
| `port` | `23` | `23` = plain TCP, `443` = TLS |
| `use_tls` | `false` | Connect over TLS |
| `timeout` | `5.0` | Network timeout (s) |

### `registers` — the register map

Each entry maps a **1-based holding register** to an action:

```yaml
registers:
  - register: 1                 # holding register 40001 (PDU address 0)
    name: "Zone 1 level"        # label for logs
    action: dali_group_level
    line: 1
    group: 0
```

`register: 1` == Modbus holding register **40001** == PDU address **0**.
(Register N == 4000N == PDU address N-1.)

## Register actions

The **value written** to a register is the command parameter; its meaning
depends on `action`:

| `action` | Config fields | Value written means |
|----------|---------------|---------------------|
| `dali_level` | `line`, `address` | Arc level `0`–`254` (clamped) |
| `dali_group_level` | `line`, `group` | Arc level `0`–`254` (clamped) |
| `dali_onoff` | `line`, `address` | `0` = off, `>0` = on (max level) |
| `dali_group_onoff` | `line`, `group` | `0` = off, `>0` = on (max level) |
| `dali_scene` | `line`, `group` *(optional)* | Scene `0`–`15` (broadcast, or on group) |
| `dali_command` | `line`, `address` | Raw DALI command code `0`–`255` |
| `spektra_sequence` | `zone` | `0` = stop, `N` = start sequence index `N-1` |
| `spektra_theme` | `zone` | `0` = stop, `N` = start theme index `N-1` |
| `spektra_static` | `zone` | `0` = stop, `N` = start static index `N-1` |

`line` is `1`–`4` (physical daughter-board slot). Out-of-range values for
scene/command are ignored (and logged); level values are clamped.

## Running

```bash
python run.py --config config.yaml --log-level INFO
```

The gateway logs each register write and the command it dispatched, e.g.:

```
INFO  edidio_modbus.datastore: Register 1 (Zone 1 level) <- 200 => dali_group_level
INFO  edidio_modbus.dispatcher: Dispatched {'kind': 'dali_group_level', 'line': 1, 'group': 0, 'level': 200}
```

## Testing without hardware

The command conversion is fully testable without an eDIDIO controller.

**1. Automated tests** (unit + a real Modbus round-trip with a stub controller):

```bash
python -m pytest -q
```

**2. With Modbus Poll / a Modbus master:**
Point Modbus Poll at the gateway (`127.0.0.1`, port `5020`, unit `1`), write a
holding register (e.g. 40001 = `200`), and watch the gateway log convert it to a
lighting command. Add a real `controller.host` to see the fixture respond.

**3. With the bundled `pymodbus` client (quick check):**

```python
import asyncio
from pymodbus.client import AsyncModbusTcpClient

async def main():
    client = AsyncModbusTcpClient("127.0.0.1", port=5020)
    await client.connect()
    await client.write_register(0, 200, slave=1)   # 40001 -> value 200
    client.close()

asyncio.run(main())
```

**Verification:** change a register value in your Modbus master; confirm the
gateway logs the corresponding conversion, and (with a controller connected) the
lighting state changes.

## Project layout

```
Modbus TCPRTUGateway/
├── run.py                    # entry point (CLI)
├── config.example.yaml       # annotated sample config
├── requirements.txt
├── edidio_modbus/
│   ├── config.py             # YAML load + validation
│   ├── registers.py          # register map + value->intent translation (pure)
│   ├── dispatcher.py         # async worker owning the EdidioClient
│   ├── datastore.py          # write-hooked holding-register datablock
│   └── server.py             # Modbus server wiring
└── tests/                    # unit tests + Modbus round-trip integration test
```

## Notes

- **`pymodbus` is pinned to 3.8.6.** It provides the stable classic datastore
  hook (`ModbusSequentialDataBlock.setValues`). pymodbus 3.15+ deprecated that in
  favour of an in-flux `SimData`/`SimDevice` API; revisit the pin once that
  stabilises.
- Holding registers are 16-bit (`0`–`65535`), which comfortably covers all
  lighting parameters used here.
- Reads return the last written value; this gateway is command-oriented (it does
  not poll live fixture state back into registers — a possible future addition).

## License

MIT
