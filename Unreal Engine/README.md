# eDIDIO + Unreal Engine

Drive Control Freak **eDIDIO** lighting from **Unreal Engine** — for virtual
production, LED-volume/ICVFX stages, location-based experiences (LBE),
attractions and interactive installations.

> **Target:** Virtual production / immersive / games.
> **Status:** Recipe using existing, tested gateways — **no new eDIDIO code
> needed**. A native UE plugin is a possible future step (see the end).

There are two zero-code paths. **OSC is recommended** (lowest latency, event-driven).

---

## Path A — OSC (recommended)

Unreal ships a first-party **OSC plugin**; the **eDIDIO OSC Bridge**
(`../OSC Bridge/`) receives OSC and drives the controller.

### 1. Run the OSC bridge

```bash
cd "../OSC Bridge"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py
python run.py --config "../Unreal Engine/edidio-osc.example.yaml"   # edit controller.host first
```

`edidio-osc.example.yaml` (included here, validated against the bridge) maps
game-friendly OSC addresses to lighting actions:

| OSC address | Send | Effect |
|-------------|------|--------|
| `/edidio/house/level` | float 0.0–1.0 | dim house group |
| `/edidio/scene/menu` `/play` `/gameover` | bang/any | recall a scene |
| `/edidio/fx/red` | bang | colour scene |
| `/edidio/fx/celebrate` | bang | start a SpektraPlus sequence |

### 2. Enable OSC in Unreal

**Edit → Plugins →** enable **OSC** → restart.

### 3. Send OSC from Blueprints (or C++)

Create an OSC client and send messages on game events:

1. **Create OSC Client** — Target = the bridge host, Port = `8000`. Store the
   returned *OSC Client* reference (e.g. on your GameMode / a subsystem).
2. On an event (Begin Play, a trigger, level state), **Send OSC Message**:
   - Build an **OSC Address** = `/edidio/scene/play`
   - (Optional) add a float arg for level addresses, e.g. `0.8`
   - **Send OSC Message** → your OSC Client.

Blueprint sketch:

```
Event: Player Enters Arena
  → Make OSC Address ("/edidio/scene/play")
  → Send OSC Message (Client, Address)

Event: Health Changed (0..1)
  → Make OSC Address ("/edidio/house/level")
  → Add Float Argument (HealthNormalized)
  → Send OSC Message (Client, Address, Message)
```

C++ is equivalent via the `OSC` module (`UOSCClient`, `FOSCMessage`).

The bridge logs each hit (`OSC /edidio/scene/play (...) => dali_scene`) and, with
a controller connected, the fixtures respond.

---

## Path B — HTTP via the REST gateway

If you'd rather use HTTP, run the **REST API Gateway** (`../Rest API Gateway/`)
and call it from Unreal's **HTTP** (Blueprint *"HTTP Request"* via the
`HTTPRequest`/`VaRest`/`Web` plugins, or the C++ `FHttpModule`):

```
POST http://<gateway>:8080/api/v1/dali/scene
Content-Type: application/json
{ "line": 1, "scene": 3 }
```

Add `X-API-Key` if the gateway is secured. See the REST gateway README for all
endpoints (level, group, dmx/color, spektra).

OSC is preferred for real-time/virtual-production use (UDP, per-frame friendly);
HTTP is fine for occasional discrete cues.

---

## Which to choose

| | OSC (A) | HTTP/REST (B) |
|--|--------|----------------|
| Latency | very low (UDP) | higher (TCP/HTTP) |
| Best for | real-time, VP, per-frame | discrete cues, existing web infra |
| UE support | first-party OSC plugin | HTTP module / plugins |

## Future: native UE plugin

A native C++/Blueprint plugin (exposing eDIDIO nodes directly, using the
byte-verified frame encoding — the C# encoder in `../Unity Package/` is a ready
reference to port to C++) would remove the bridge for pure-UE shops. Worth doing
when a virtual-production customer needs an all-in-engine workflow; the recipe
above ships value today with zero new code.

## License

MIT
