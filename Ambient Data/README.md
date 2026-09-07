# eDIDIO Ambient Data Engine

Turn **any real-time data** into Control Freak **eDIDIO** lighting — a room that
shifts red→green with your crypto portfolio, pulses when the aurora is out, or
recalls scenes when your servers spike. A reusable **framework**: each concept is
just a small *source* + a *mapping* in a YAML file.

> **Target:** Ambient / experiential / dashboards / fun.
> **Tech:** Python, wrapping `edidio_control_py`. HTTP polling uses the standard
> library — no heavy deps.

```
data source (API / feed)  →  mapping (value → lighting)  →  dispatcher  →  eDIDIO
   http_poll / demo            gradient / threshold / level
```

## Concepts this covers (out of the box)

Because most "ambient data → light" ideas are the same shape, **one engine +
config** handles a long list. Every example below is a ready config in
`examples/`:

| Concept | Example config | Source | Mapping |
|---------|----------------|--------|---------|
| **Stock / Crypto / VIX ticker** | `crypto-ticker.yaml` | `http_poll` | `gradient` (red→green) |
| **Space weather / Aurora alert** | `aurora-alert.yaml` | `http_poll` | `threshold` scenes |
| **Solar & grid power sync** | `solar-grid.yaml` | `http_poll` inverter | `gradient` |
| **ISS overhead tracker** | `iss-overhead.yaml` | `iss_overhead` (geo) | `threshold` |
| **Rocket launch countdown** | `rocket-launch.yaml` | `countdown` | `threshold` (escalate) |
| **Live F1 race control** | `f1-racecontrol.yaml` | `f1_racecontrol` | `event` (flags) |
| **Server health (Prometheus)** | `server-health.yaml` | `http_poll` | `threshold` |
| **Grafana/Alertmanager alerts** | `grafana-alert.yaml` | `webhook` | `event` |
| **UniFi presence** | `unifi-presence.yaml` | `http_poll` | `level` |
| **D&D / tabletop (Foundry/Roll20)** | `dnd-encounter.yaml` | `webhook` | `event` |
| **No-API demo** | `demo-gradient.yaml` | `demo` | `gradient` |

Add another concept by pointing a source at a new feed — no engine changes.

## Quick start

```bash
cd "Ambient Data"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py   # dev: shared engine

# Try it with no API and no data feed — a sine wave sweeps a gradient:
python run.py --config examples/demo-gradient.yaml   # edit controller.host first
```

Then try the headline example:

```bash
python run.py --config examples/crypto-ticker.yaml
```

## Configuration

A config has three parts: `controller`, `source`, `mapping` (+ optional
`min_interval`). See `examples/`.

### Sources (`source.type`)

| Type | Does | Key fields |
|------|------|-----------|
| `http_poll` | GET a JSON API every `interval` s and extract a number | `url`, `json_path`, `interval`, `headers`, `scale`, `offset` |
| `webhook` | Receive HTTP POSTs; emit a number or an event label | `host`, `port`, `json_path` / `label_path`, `token` |
| `iss_overhead` | Poll the ISS position; emit *proximity* to your coords | `lat`, `lon`, `radius_km`, `interval` |
| `countdown` | Poll for an event time (ISO); emit rising *intensity* | `url`, `json_path`, `window_s`, `interval` |
| `f1_racecontrol` | Poll OpenF1; emit a flag *label* per new message | `url`, `interval` |
| `demo` | Emit a sine sweep or a fixed `values` list — no API | `interval`, `min`, `max`, `period` / `values` |

`json_path` is a dot-path with numeric list indices, e.g. `bitcoin.usd_24h_change`
or `chart.result.0.meta.regularMarketPrice`. `scale`/`offset` apply
`value*scale + offset`. The `webhook`, `iss_overhead`, `countdown` and
`f1_racecontrol` sources normalise their feed so **bigger = more intense**
(proximity, urgency) — which drops straight into gradient/threshold; the event
sources emit **labels** for the `event` mapping.

### Mappings (`mapping.type`)

| Type | Value → | Fields |
|------|---------|--------|
| `gradient` | RGB along colour stops → paint a DMX line | `line`, `min`, `max`, `colors: [#RRGGBB…]` |
| `threshold` | the band the value falls in → a lighting action | `bands: [{min, action}]` |
| `level` | brightness 0–254 on a DALI address/group | `line`, `min`, `max`, `address`/`group`, `invert` |
| `event` | a named event label → a lighting action | `events: {name: action, …}` |

A band/event `action` is any intent: `{kind: dali_scene, line, scene}`,
`{kind: spektra, …}`, `{kind: dmx_color, line, rgb}`, etc. The `event` mapping
re-fires on each event (dedup off); the numeric mappings de-dup + rate-limit.

### Safe by design

The engine **de-dups** identical consecutive intents (so a threshold fires only
on band change, and a steady value doesn't repeat) and **rate-limits** to
`min_interval` seconds — so a noisy feed can never strobe the room.

## Add a new concept

1. If it's a JSON API, you often need **no code** — just a new `http_poll` config
   (`url` + `json_path`) and a mapping. That alone covers stocks, crypto, aurora,
   solar, sports scores, ISS position fields, etc.
2. For a push feed (WebSocket, webhook, game-state), add a small **source** under
   `edidio_ambient/sources/` that calls `emit(value)` — the mapping, engine and
   dispatcher are unchanged. (`http_poll`/`demo` are ~50 lines each; copy one.)

## Testing

```bash
python -m pytest -q
```

- `test_mappings.py` — gradient interpolation, threshold bands, level (+ invert),
  and config validation.
- `test_engine.py` — de-dup, rate-limit, event re-fire, and dispatch with fakes.
- `test_sources.py` — `json_path` extraction, `http_poll` with an **injected
  fetch** (no network), scale/offset, error handling.
- `test_new_sources.py` — haversine distance + ISS proximity, countdown intensity
  maths (injected clock), F1 flag-label derivation + new-message de-dup, webhook
  value/label extraction, and the `event` mapping.

All logic is verified **without any API or eDIDIO hardware**. Live: point
`controller.host` at a controller and run an example — the demo config needs no
data feed.

## Notes on live data

- Respect API **rate limits and terms** — set a sensible `interval`. A failed or
  malformed poll is logged and skipped (never crashes, never strobes).
- Some endpoints need an **API key** — put it in `source.headers`.
- **Solar/grid** can also read inverters via the **Modbus gateway** in this repo
  and feed the ambient engine over the REST gateway, if you prefer Modbus.

## License

MIT
