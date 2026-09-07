# eDIDIO CS2 Game State Integration

Make your room lighting react to **Counter-Strike 2** in real time: the room
colour tracks your **health** (green → red), a **flashbang** blinds it white, and
the **bomb plant** throws a red alert. Built on Valve's native **Game State
Integration** — no game mods, no memory reading.

> **Target:** Gaming / streaming / experiential.
> **Tech:** Python (stdlib HTTP server) receiving CS2's GSI POSTs, wrapping
> `edidio_control_py`. The first of the *game-state* family.

## How it works

CS2 posts a JSON snapshot of your game state to a local HTTP endpoint whenever
anything changes. This bridge maps that state to lighting:

```
CS2  ──GSI JSON (HTTP POST)──▶  bridge  ──eDIDIO protobuf/TCP──▶  eDIDIO ──▶ fixtures
                                   │
                                   └─ health→colour, flashbang→white, bomb→red
```

Discrete events (flashbang, bomb plant, death) fire on the **rising edge**, so
they don't repeat while the state persists.

## Setup

### 1. Run the bridge

```bash
cd "CS2 GSI"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py   # dev: shared engine
cp config.example.yaml config.yaml                 # set controller.host + effects
python run.py --config config.yaml
```

### 2. Tell CS2 to send game state

Copy **`gamestate_integration_edidio.cfg`** into your CS2 config folder:

```
…/Steam/steamapps/common/Counter-Strike Global Offensive/game/csgo/cfg/
```

It points CS2 at `http://127.0.0.1:3000` (match `server` in your `config.yaml`).
Restart CS2. That's it — play a match and watch the lights.

> If you set an `auth.token` in the cfg, set the same `server.token` in
> `config.yaml`.

## Effects (`config.yaml → cs2`)

| Effect | Fires | Config |
|--------|-------|--------|
| **health** | continuously; colour on a DMX line | `line`, `colors` (100 %→last, 0 %→first) |
| **flash** | when the flash amount rises past `threshold` | `line`, `threshold`, `color` |
| **bomb** | once when the bomb is planted | `action` (any intent — DMX red, a scene, …) |
| **death** | when your health hits 0 (optional) | `action` |

Any `action` is a lighting intent: `{kind: dmx_color, line, rgb}`,
`{kind: dali_scene, line, scene}`, `{kind: spektra, …}`, etc.

## Testing

```bash
python -m pytest -q
```

- `test_mapper.py` — feeds recorded-style GSI payloads and asserts the intents:
  health gradient (emits only on change), flashbang rising-edge (no repeat), bomb
  fires once, death, missing-field safety, flash-over-health priority.
- `test_server.py` — **POSTs real GSI payloads to the actual HTTP handler** and
  checks the correct intents reach a fake dispatcher — no CS2, no controller.

Live: run the bridge + install the cfg, point `controller.host` at a controller,
and play (or hit the endpoint with `curl` using a sample payload).

## Extending to other games

This is the template for the **game-state family**: any game that emits state
(LiveSplit WebSocket, Kerbal telemetry, a Source-engine GSI title) becomes a new
bridge with the same shape — a listener + a pure state→intent mapper + the shared
dispatcher.

## Files

```
CS2 GSI/
├── run.py
├── config.example.yaml
├── gamestate_integration_edidio.cfg   # install into CS2's cfg folder
├── edidio_cs2/
│   ├── mapper.py       # GSI payload -> intents (pure, tested)
│   ├── server.py       # threaded HTTP server -> dispatcher
│   ├── config.py       # YAML load
│   └── dispatcher.py   # async worker (with dmx_color) wrapping edidio_control_py
└── tests/
```

## License

MIT
