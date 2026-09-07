# eDIDIO OBS Studio Integration

Automatically drive Control Freak **eDIDIO** lighting from **OBS Studio** events —
switch scenes, go live, or start recording and your room lighting follows. Great
for streamers, podcasters and AV/broadcast setups ("go live → house lights dim
and the on-air sign turns on").

> **Target:** Streaming / broadcast / AV.
> **Tech:** Node + `obs-websocket-js` (OBS WebSocket v5), reusing the eDIDIO JS
> engine. Sends frames directly over TCP/TLS — no gateway needed.

## What it reacts to

| OBS event | Example use |
|-----------|-------------|
| **Scene switch** (per scene name) | "Starting Soon" → warm scene; "Live" → blue wash; "BRB" → dim |
| **Stream start / stop** | start a SpektraPlus effect on air; stop it off air |
| **Record start / stop** | turn an on-air / recording indicator light on/off |

All mapped in `triggers.json` — no code.

## Setup

1. In **OBS**: *Tools → WebSocket Server Settings* → enable the server; note the
   **port** (default 4455) and **password**.
2. Configure and run the integration:

```bash
cd "OBS Studio"
npm install
cp .env.example .env          # set OBS_URL/OBS_PASSWORD + EDIDIO_HOST
cp src/triggers.example.json src/triggers.json   # customise (optional)
npm start
```

### `.env`
| Var | Description |
|-----|-------------|
| `OBS_URL` | e.g. `ws://127.0.0.1:4455` |
| `OBS_PASSWORD` | from OBS WebSocket settings |
| `EDIDIO_HOST` / `EDIDIO_PORT` / `EDIDIO_USE_TLS` | controller |

## Trigger map (`triggers.json`)

- **`scenes`** — OBS scene **name** (exact) → action, fired when that scene
  becomes the program (live) scene.
- **`stream`** — `onStart` / `onStop` actions.
- **`record`** — `onStart` / `onStop` actions.

Actions: `scene` (line, scene), `level` (line, address, level), `on`/`off`
(line, address), `color` (line, hex), `spektra` (zone, index),
`spektraStop` (zone).

## Testing

```bash
npm test        # node --test
```

`test/mapper.test.js` decodes the actual eDIDIO frame each OBS event produces
(scene switches, stream/record start-stop, validation) — verified **without OBS
or a controller**. Live: run OBS with WebSocket enabled, point `EDIDIO_HOST` at a
controller, and switch scenes / go live to see the fixtures respond.

## Files

```
OBS Studio/
├── index.js                   # obs-websocket glue -> mapper -> controller
├── src/
│   ├── mapper.js              # OBS event -> eDIDIO frame (pure, tested)
│   ├── config.js              # .env + triggers.json loader
│   ├── triggers.example.json  # scene/stream/record map
│   └── edidio/                # vendored protocol engine (encoder + connection)
└── test/
```

## Notes

- Uses OBS WebSocket **v5** (bundled with OBS 28+). Event names:
  `CurrentProgramSceneChanged`, `StreamStateChanged`, `RecordStateChanged`.
- Command-oriented (OBS → eDIDIO). Reflecting lighting state back into OBS is a
  possible future addition.

## License

MIT
