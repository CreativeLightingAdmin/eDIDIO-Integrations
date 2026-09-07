# eDIDIO Kerbal Space Program

Fly Kerbals, light your room. Drives Control Freak **eDIDIO** lighting from
**KSP** vessel telemetry — throttle → brightness, fuel → a green-to-red gauge,
staging → a burst, abort → red flash, and flight-situation scenes.

> **Target:** Gaming / experiential. Part of the game-state family.
> **Tech:** Python; telemetry via **kRPC**, wrapping `edidio_control_py`.

## How it works

```
KSP + kRPC mod  ──telemetry (kRPC)──▶  bridge (poll + map)  ──eDIDIO TCP──▶  fixtures
```

The bridge polls the active vessel and maps telemetry to lighting each tick.

## Setup

1. In KSP, install the **kRPC** mod and start its server.
2. Run the bridge:

```bash
cd "Kerbal Space Program"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py
cp config.example.yaml config.yaml        # set controller.host + krpc.host
python run.py --config config.yaml
```

## Effects (`config.yaml -> ksp`)

| Effect | From | Config |
|--------|------|--------|
| `throttle` | throttle 0-1 → group brightness | `line`, `group` |
| `fuel` | LiquidFuel fraction → gauge colour | `line`, `colors` |
| `abort` | abort action pressed → flash | `action` |
| `stage` | stage change → burst | `action` |
| `situations` | flight situation (pre_launch/orbiting/landed…) → scene | map of `situation: action` |

## Testing

```bash
python -m pytest -q
```

`test_mapper.py` verifies the telemetry → lighting mapping (throttle/fuel emit on
change; abort/stage/situation fire on their edge) with sampled telemetry dicts —
**no KSP, no kRPC, no controller**. The live link (`run.py`) needs the kRPC mod +
the `krpc` package.

## Files

```
Kerbal Space Program/
├── run.py                 # kRPC poll loop -> mapper -> dispatcher
├── config.example.yaml
├── edidio_ksp/  (mapper.py [pure, tested], dispatcher.py)
└── tests/
```

## Notes

- Telemetry field names follow kRPC; adjust `read_telemetry` in `run.py` if you
  poll different fields or use Telemachus instead.

## License

MIT
