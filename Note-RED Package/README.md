# node-red-contrib-edidio

Node-RED nodes for controlling Control Freak **eDIDIO** lighting controllers
(DALI, DMX and SpektraPlus) over TCP/TLS. Drop the nodes onto your flow, point
them at a controller, and drive lighting from any Node-RED event — dashboards,
schedules, MQTT, HTTP, home automation, IoT sensors.

> **Target:** System integrators, low-code / IoT automation.

## Nodes

| Node | Purpose |
|------|---------|
| **edidio-controller** (config) | A shared, auto-reconnecting connection to one controller. |
| **edidio-dali** | DALI: set level, group level, on/off, standard commands, scene recall. |
| **edidio-dmx** | DMX: raw channel levels, or paint an RGB colour across a line. |
| **edidio-spektra** | SpektraPlus: start/stop/pause sequences, themes and static scenes. |

Every action node shows the controller connection state (green dot = connected)
and passes `msg` through with `msg.payload.sent = true` on success.

## Install

From your Node-RED user directory (`~/.node-red`):

```bash
npm install node-red-contrib-edidio
```

Or use **Manage palette → Install** in the Node-RED editor and search for
`node-red-contrib-edidio`. Restart Node-RED and the **eDIDIO** category appears
in the palette.

### Local install (development)

```bash
cd "Note-RED Package"
npm install
# then, from your Node-RED user dir:
npm install /path/to/Note-RED\ Package
```

## Quick start

1. Drag an **edidio-dali** node onto the canvas.
2. Click it, add a new **edidio-controller** and enter your controller's IP.
3. Set Action = *Set level*, Line = 1, Address = 5, Level = 254.
4. Wire an **inject** node in front and a **debug** node after; deploy and click
   inject — the fixture goes to full and the debug shows `{ sent: true }`.

An importable example is in `examples/basic-flow.json` (Node-RED: **Import →
Examples → node-red-contrib-edidio**).

## Dynamic control via `msg.payload`

Configured fields are **defaults**; matching `msg.payload` fields override them,
so one node can be driven dynamically:

```json
// into an edidio-dali node (Action: Set level)
{ "address": 9, "level": 128 }

// into an edidio-dmx node (Action: RGB colour)
{ "hex": "#00FF88", "line": 2 }

// into an edidio-spektra node
{ "type": "theme", "index": 3, "action": "start", "zone": 1 }
```

### Payload fields by node

**edidio-dali** — `action` (`level`, `group_level`, `onoff`, `group_onoff`,
`command`, `scene`), `line` (1-4), `address` (0-63), `group` (0-15), `level`
(0-254), `scene` (0-15), `value` (on/off), `command` (name or code), `arg`.

Named commands: `off, on, max, min, fade_up, fade_down, step_up, step_down,
recall_last, identify`.

**edidio-dmx** — `action` (`color`, `level`), `line`, `hex` (`#RRGGBB`),
`fixtures`, `levels` (array or comma string 0-255), `channel`, `repeat`, `zone`,
`fadeMs`.

**edidio-spektra** — `type` (`sequence`, `theme`, `static`), `zone`, `index`,
`action` (`start`, `stop`, `pause`, `stop_off`).

## Concepts

- **Line** (1-4): a physical daughter-board slot (DALI or DMX).
- **Address** (0-63): a DALI short address · **Group/Scene** (0-15).
- **Zone**: a SpektraPlus zone for sequences/themes.

## Testing without hardware

Run the node unit tests (they load each node and decode the exact protobuf frame
it produces, using a stub connection — no controller needed):

```bash
npm test
```

To test against a real controller, run Node-RED locally (`node-red`), import the
example flow, set your controller IP, and click the inject nodes while watching
the fixtures and each node's status dot.

## How it works

The nodes embed the same eDIDIO protocol engine used by the REST gateway and the
Discord bot (`lib/`): protobuf message building, framing (`0xCD` + length +
payload), UDP discovery, and a TCP/TLS connection with keep-alive and automatic
reconnect. The config node owns one connection; action nodes send through it.

```
Node-RED msg ──▶ edidio-dali/dmx/spektra ──build frame──▶ edidio-controller ──TCP/TLS──▶ eDIDIO ──▶ fixtures
```

## License

MIT
