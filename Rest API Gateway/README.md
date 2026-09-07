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
| `EDIDIO_API_KEY` | *(empty)* | If set, all `/api` requests must send it (see [Auth](#authentication)). Empty disables auth. |
| `EDIDIO_IP` | *(empty)* | Default controller IP; lets requests omit `controller` |
| `EDIDIO_PORT` | `23` | Plain-TCP controller port |
| `EDIDIO_TLS_PORT` | `443` | TLS controller port |
| `EDIDIO_USE_TLS` | `false` | Use TLS by default |
| `HEARTBEAT_MS` | `7000` | Keep-alive interval per controller socket |

## Authentication

If `EDIDIO_API_KEY` is set, every `/api/**` request must include it as either:

- `X-API-Key: <key>` header, **or**
- `Authorization: Bearer <key>` header

`/health` is always open. If the key is blank, the API is unauthenticated (only
appropriate on a trusted, isolated network) and a warning is logged at startup.

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
- `400` invalid/missing field · `401` bad API key · `404` unknown route/controller
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
│   ├── routes/                # controllers, dali, dmx, spektra + shared helpers
│   └── edidio/                # protocol engine (protobuf, builders, discovery)
├── .env.example
└── package.json
```

The `src/edidio/` engine (protobuf definitions, message builders, discovery,
connection with keep-alive/reconnect) is shared with the eDIDIO Discord bot and
mirrors the SpektraPlus wire protocol.

## License

MIT
