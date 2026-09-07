# eDIDIO Dota 2 Game State Integration

Make your room lighting react to **Dota 2**: the colour tracks your hero's health
(green -> red), a red flash on death, green on respawn, and optional day/night
ambience. Built on Valve's native **Game State Integration** — no mods.

> **Target:** Gaming / streaming. Second of the game-state family (see CS2 GSI).
> **Tech:** Python (stdlib HTTP server) receiving GSI POSTs, wrapping
> `edidio_control_py`.

## Setup

```bash
cd "Dota 2 GSI"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py
cp config.example.yaml config.yaml            # set controller.host + effects
python run.py --config config.yaml
```

Then copy **`gamestate_integration_edidio.cfg`** into Dota 2's GSI config folder:

```
…/Steam/steamapps/common/dota 2 beta/game/dota/cfg/gamestate_integration/
```

It points Dota 2 at `http://127.0.0.1:3001` (match `server` in `config.yaml`).
Restart Dota 2 and play.

## Effects (`config.yaml -> dota2`)

| Effect | Fires | Config |
|--------|-------|--------|
| `health` | continuously; hero health% colour on a DMX line | `line`, `colors` |
| `death` | once when your hero dies | `action` |
| `respawn` | once when your hero respawns | `action` |
| `daynight` | on the in-game day/night flip (optional) | `day_action`, `night_action` |

Any `action` is a lighting intent (`dmx_color` / `dali_scene` / `spektra` / ...).

## Testing

```bash
python -m pytest -q
```

- `test_mapper.py` — health gradient (emits on change), death/respawn edges (no
  repeat), day/night, missing-field safety.
- `test_server.py` — POSTs real GSI payloads to the actual HTTP handler.

No Dota 2 or controller needed. Live: run the bridge + install the cfg, point
`controller.host` at a controller, and play.

## Files

```
Dota 2 GSI/
├── run.py
├── config.example.yaml
├── gamestate_integration_edidio.cfg   # install into Dota 2's GSI cfg folder
├── edidio_dota2/  (mapper.py, server.py, config.py, dispatcher.py)
└── tests/
```

## License

MIT
