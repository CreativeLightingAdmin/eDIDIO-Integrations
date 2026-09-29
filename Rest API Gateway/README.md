# eDIDIO REST API Gateway

A lightweight middleware service that exposes a standard **HTTP/JSON REST API**
for controlling Control Freak **eDIDIO** lighting controllers. It translates
ordinary HTTP requests into the eDIDIO TCP/TLS Protocol-Buffer wire format
(DALI, DMX and SpektraPlus), so any system that can make an HTTP call — web
apps, digital signage, IT automation, BMS front-ends — can drive lighting
without speaking the binary protocol.

> **Target:** IT systems, web apps, digital signage.
> **Tech:** Node.js + Express, wrapping the shared eDIDIO JS protocol engine.

## How it works

```
HTTP client  ──JSON──▶  REST Gateway  ──0xCD + protobuf over TCP/TLS──▶  eDIDIO controller ──▶ DALI / DMX fixtures
```

- The gateway keeps a **warm, auto-reconnecting socket per controller** (pooled
  by IP) with a keep-alive heartbeat, so requests are low-latency.
- Controllers can be discovered on the LAN via UDP broadcast, addressed by IP
  per-request, or fixed with a default IP in `.env`.
- Wire framing, DALI/DMX/Spektra message building, discovery and connection
  management are the same modules proven in the eDIDIO Discord bot
  (`src/edidio/`).

## Setup

```bash
cd "Rest API Gateway"
npm install
cp .env.example .env      # then edit .env
npm start                 # or: npm run dev  (auto-restart on change)
```

Requires **Node.js >= 18**.

### Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | HTTP listen port |
| `HOST` | `0.0.0.0` | HTTP bind address |
| `EDIDIO_API_KEY` | *(empty)* | Full-control key (see [Auth](#authentication)). **Required** unless `HOST` is loopback. |
| `EDIDIO_READ_API_KEY` | *(empty)* | Optional read-only key: `GET` only (status, state, live events) |
| `EDIDIO_ALLOW_UNAUTHENTICATED` | `false` | Allow running with no key on a non-loopback `HOST` (trusted, isolated networks only) |
| `EDIDIO_EVENTS` | `true` | Subscribe each controller to its live event stream (firmware ≥ 1.4.0) for `/state` + `/events` |
| `EDIDIO_EVENT_CATEGORIES` | `dali,inputs,sensors,triggers` | Event categories to subscribe to |
| `EDIDIO_IP` | *(empty)* | Default controller IP; lets requests omit `controller` |
| `EDIDIO_PORT` | `23` | Plain-TCP controller port |
| `EDIDIO_TLS_PORT` | `443` | TLS controller port |
| `EDIDIO_USE_TLS` | `false` | Use TLS by default |
| `HEARTBEAT_MS` | `7000` | Keep-alive interval per controller socket |

## Authentication

Every `/api/**` request must include a key as either:

- `X-API-Key: <key>` header, **or**
- `Authorization: Bearer <key>` header, **or**
- `?api_key=<key>` — **GET requests only**, for browser `EventSource` clients
  that can't set headers (prefer headers elsewhere: query strings end up in logs).

Two keys:

| Key | Grants |
|---|---|
| `EDIDIO_API_KEY` | everything |
| `EDIDIO_READ_API_KEY` | `GET`/`HEAD` only — dashboards, status displays, `/events`. Writes return `403`. |

Keys are compared in constant time. `/health` is always open.

**Fail-closed:** with no key configured, the gateway **refuses to start** unless
`HOST` is loopback (`127.0.0.1`/`::1`/`localhost`) or
`EDIDIO_ALLOW_UNAUTHENTICATED=true` is set explicitly.

## Addressing a controller

Every control request targets one controller, resolved in this order:

1. `controller` field in the JSON body (or `?controller=` query param), else
2. `EDIDIO_IP` from `.env`.

Optional per-request overrides: `useTLS` (bool), `port` (number). The first
request to a new IP opens a pooled connection automatically (a quick UDP
discovery probe fills in the controller's line-type map and TLS capability when
possible).

## Concepts

- **Line** (`1`–`4`): a physical daughter-board slot, each either DALI or DMX.
- **Address** (`0`–`63`): a DALI short address.
- **Group** / **Scene** (`0`–`15`): DALI groups and stored scenes.
- **Arc level** (`0`–`254`): DALI brightness.
- **Zone**: a logical SpektraPlus zone (used for sequences/themes and DMX zone).

The gateway validates a line against its known type where discovery provided one
(e.g. a DALI command to a DMX line returns `409`).

---

## API reference

Base path: `/api/v1`. All responses are JSON with an `ok` boolean; errors add an
`error` message (and sometimes `details`).

### Discovery & connections

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/discover` | UDP-broadcast probe for controllers on the LAN |
| `GET` | `/controllers` | List pooled connections and their state |
| `POST` | `/controllers` | Open/replace a connection — body `{ ip, useTLS?, port? }` |
| `GET` | `/controllers/:ip` | Status of one pooled connection |
| `DELETE` | `/controllers/:ip` | Close and stop reconnecting |

### Live state & events (firmware ≥ 1.4.0)

Each pooled connection subscribes to the controller's event stream, so the
gateway knows the **real** light levels — including changes made by wall panels,
schedules, SpektraPlus or other gateways, not only its own commands.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/controllers/:ip/state` | Levels seen on the bus: `{ levels: { "line:address": level } }` |
| `GET` | `/controllers/:ip/events` | **Server-Sent Events** stream: `snapshot`, then `state` and `event` |

`address` uses eDIDIO addressing (0–63 short, `64 + g` group, `80` broadcast);
`level` is `null` when the frame didn't state one (e.g. RECALL MIN). A `state`
event carries the change plus `touched` (every target it updated):

```
event: state
data: {"line":1,"address":5,"target":"address","level":200,"command":"arc","scene":null,"touched":[{"line":1,"address":5,"level":200}]}
```

Browser example (read-only key):

```js
const es = new EventSource('/api/v1/controllers/192.168.1.50/events?api_key=READ_KEY')
es.addEventListener('state', (e) => console.log(JSON.parse(e.data)))
```

### DALI

| Method | Path | Body |
|--------|------|------|
| `POST` | `/dali/level` | `{ line, address, level, controller? }` |
| `POST` | `/dali/group/level` | `{ line, group, level, controller? }` |
| `POST` | `/dali/command` | `{ line, address, command, arg?, controller? }` |
| `POST` | `/dali/scene` | `{ line, scene, group?, controller? }` |

`command` accepts a friendly name or a raw integer code. Known names:
`off`, `on`, `max`, `min`, `fade_up`, `fade_down`, `step_up`, `step_down`,
`step_down_off`, `on_step_up`, `recall_last`, `identify`.

`/dali/scene` broadcasts the scene across the line, or targets a group when
`group` is supplied.

### DMX

| Method | Path | Body |
|--------|------|------|
| `POST` | `/dmx/level` | `{ line, levels[], channel?=1, repeat?=1, zone?=0, fadeMs?, controller? }` |
| `POST` | `/dmx/color` | `{ line, hex, fixtures?, zone?=255, fadeMs?, controller? }` |

`levels` is an array of `0`–`255` channel values written from `channel`;
`repeat` tiles the pattern across the universe. `/dmx/color` paints an RGB
`#RRGGBB` colour across `fixtures` RGB fixtures (default: fill the universe).

### SpektraPlus (sequences / themes / scenes)

| Method | Path | Body |
|--------|------|------|
| `POST` | `/spektra` | `{ zone, type, index, action, controller? }` |
| `POST` | `/spektra/stop` | `{ zone, controller? }` |

`type`: `sequence` \| `theme` \| `static`. `action`: `start` \| `stop` \| `pause`.
`/spektra/stop` halts playback **and** turns the output off, matching the
SpektraPlus app.

### Responses & status codes

- `200` success · `202` connection opened but still pending
- `400` invalid/missing field · `401` bad API key · `403` read-only key used for a write
- `404` unknown route/controller
- `409` wrong line type for the command
- `503` target controller not currently connected (gateway is retrying)

---

## Examples (cURL)

Assuming `EDIDIO_API_KEY=secret` and a controller at `192.168.1.50`.

```bash
# Discover controllers on the LAN
curl -H "X-API-Key: secret" http://localhost:8080/api/v1/discover

# Set DALI address 3 on line 1 to 50% (arc level 127)
curl -X POST http://localhost:8080/api/v1/dali/level \
  -H "X-API-Key: secret" -H "Content-Type: application/json" \
  -d '{"controller":"192.168.1.50","line":1,"address":3,"level":127}'

# Turn a light off (named command)
curl -X POST http://localhost:8080/api/v1/dali/command \
  -H "X-API-Key: secret" -H "Content-Type: application/json" \
  -d '{"controller":"192.168.1.50","line":1,"address":3,"command":"off"}'

# Recall DALI scene 3 across line 1
curl -X POST http://localhost:8080/api/v1/dali/scene \
  -H "X-API-Key: secret" -H "Content-Type: application/json" \
  -d '{"controller":"192.168.1.50","line":1,"scene":3}'

# Paint DMX line 2 red
curl -X POST http://localhost:8080/api/v1/dmx/color \
  -H "X-API-Key: secret" -H "Content-Type: application/json" \
  -d '{"controller":"192.168.1.50","line":2,"hex":"#FF0000"}'

# Start SpektraPlus sequence 0 on zone 1
curl -X POST http://localhost:8080/api/v1/spektra \
  -H "X-API-Key: secret" -H "Content-Type: application/json" \
  -d '{"controller":"192.168.1.50","zone":1,"type":"sequence","index":0,"action":"start"}'
```

Setting a default `EDIDIO_IP` in `.env` lets you drop the `controller` field
entirely.

## Testing without hardware

- **Automated:** `npm test` — API-key rules, the fail-closed startup guard, and
  live state/SSE against a fake controller socket fed real event-stream frames.
- **Boot check:** `npm start`, then `curl http://localhost:8080/health` → `200`.
- **Validation:** POST malformed bodies (out-of-range `line`, missing `level`)
  and confirm `400` with a helpful message — no controller needed.
- **With a controller on your LAN:** run `GET /api/v1/discover` to confirm the
  unit is found, then send a `/dali/level` and watch the fixture change; the API
  returns `200 OK` on a successful write.
- **Postman:** import the endpoints above; set an `X-API-Key` header at the
  collection level.

## Project layout

```
Rest API Gateway/
├── src/
│   ├── server.js              # Express entry point
│   ├── config.js              # .env-driven configuration
│   ├── connectionManager.js   # IP-keyed pool of controller sockets
│   ├── middleware/            # API-key auth + error handling
│   ├── routes/                # controllers, events, dali, dmx, spektra + helpers
│   └── edidio/                # protocol engine (protobuf, builders, discovery,
│                              #   event stream)
├── test/                      # node --test
├── .env.example
└── package.json
```

The `src/edidio/` engine (protobuf definitions, message builders, discovery,
connection with keep-alive/reconnect) is shared with the eDIDIO Discord bot and
mirrors the SpektraPlus wire protocol. `messageBuilder.js`,
`eDS10_ProtocolBuffer_pb.js` and `eventStream.js` are vendored from the repo's
`shared/js-engine/` — edit them there and run `python tools/sync_vendored.py`.

## License

MIT
