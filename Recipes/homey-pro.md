# eDIDIO via Homey Pro

[Homey Pro](https://homey.app) integrates eDIDIO through the gateways in this
repo — **no custom Homey app required**. Two paths; MQTT is the smoother one for
two-way lights, HTTP is simplest for one-shot actions/flows.

## Prerequisite

Run the relevant gateway (MQTT Bridge or REST Gateway), pointed at your
controller. See each gateway's README.

## Path A — MQTT (recommended)

Homey Pro has the community **MQTT Client** + **MQTT Hub / MQTT Device** apps.

1. Run the **MQTT Bridge** (`../MQTT Bridge/`) against the same broker Homey uses.
   Its Home Assistant discovery also helps other tools, but for Homey you bind
   topics directly.
2. In Homey, install **MQTT Client** (connect to your broker) and **MQTT Device**.
3. Create MQTT Devices bound to the bridge topics (base topic `edidio`):
   - a **light**: set topic `edidio/kitchen/set` (`ON`/`OFF`), state topic
     `edidio/kitchen/state`, and dim command `edidio/kitchen/brightness/set`
     (`0-254`).
   - a **scene** button: publish `edidio/movie/set` = `ON`.
4. Use those devices in Homey **Flows** and the dashboard.

## Path B — HTTP from a Flow

Homey Pro's **Logic** / **HTTP request** flow cards (or the community *HTTP
request* app) can POST to the **REST Gateway** (`../Rest API Gateway/`):

- **Then** card → HTTP POST
  - URL: `http://<gateway>:8080/api/v1/dali/scene`
  - Headers: `Content-Type: application/json` (+ `X-API-Key` if set)
  - Body: `{"line":1,"scene":3}`

Example flow: *"When I say 'movie time' (Homey voice / a button) → POST recall
scene 3."*

## Which to choose

| | MQTT (A) | HTTP (B) |
|--|---------|----------|
| Two-way state (dim/on-off in the Homey UI) | ✓ | one-way |
| Setup | broker + MQTT apps | just a flow card |
| Best for | lights you want as Homey devices | scene/flow triggers |

## Native Homey app (future)

A dedicated **Homey app** (Homey SDK v3, Node.js — Homey Pro runs apps locally)
could expose eDIDIO zones/scenes as native Homey devices with pairing, reusing
the JS protocol engine (as the Node-RED/Companion integrations do). Worth doing if
there's demand for a one-tap install; the MQTT/HTTP recipe delivers the
functionality today with no app-store submission.
