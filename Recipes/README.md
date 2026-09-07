# eDIDIO Integration Recipes

Many popular platforms already speak protocols eDIDIO supports through the
gateways in this repo — so integrating them is **configuration, not new code**.
This folder documents those recipes.

| Platform | Reach it via | Effort |
|----------|--------------|--------|
| **Loxone** | Modbus gateway (Modbus TCP) *or* REST gateway (HTTP Virtual Output) | Config only |
| **openHAB** | MQTT bridge (MQTT binding) *or* REST gateway (HTTP binding) | Config only |
| **Hubitat** | MQTT bridge *or* REST gateway (Rule Machine HTTP) | Config only |
| **Niagara / Tridium** | Modbus gateway (Modbus TCP) *or* BACnet (native) | Config only |
| **Node-RED** | native package *or* MQTT bridge | — |
| **IFTTT / Zapier / Make** | REST gateway (HTTP webhook) — see [webhooks-ifttt-zapier-make.md](webhooks-ifttt-zapier-make.md) | Config only |
| **Homey Pro** | MQTT bridge *or* REST gateway (Flow) — see [homey-pro.md](homey-pro.md) | Config only |

The recipes assume the relevant gateway from this repo is already running and
pointed at your controller (see each gateway's README).

---

## Loxone

Loxone Miniserver can drive eDIDIO two ways.

### A. Via the Modbus gateway (recommended for level/scene control)

The Miniserver (with the **Modbus TCP** extension/config) is a Modbus master; the
**eDIDIO Modbus gateway** is the slave. Map Loxone outputs to holding registers.

1. Run the **Modbus TCP/RTU Gateway** with a register map (see
   `templates/loxone-modbus.yaml` for a Loxone-friendly example).
2. In Loxone Config, add a **Modbus Server** at the gateway's IP, port `502`
   (or `5020`), unit `1`.
3. Add **Modbus Actuators** for each register (holding register, 16-bit):
   - Register `1` (40001) → *Zone brightness* (write `0–254`).
   - Register `2` (40002) → *Scene recall* (write scene `0–15`).
4. Wire Loxone blocks (e.g. a Lighting Controller / dimmer) to those actuators.

Changing a Loxone output writes the register; the gateway logs the conversion and
drives the fixture.

### B. Via the REST gateway (HTTP Virtual Output)

For event/button-style control, use a Loxone **Virtual Output**:

1. Run the **REST API Gateway** (set `EDIDIO_IP`; optionally an API key).
2. Add a **Virtual Output**, address `http://<gateway-ip>:8080`.
3. Add **Virtual Output Commands** (HTTP POST), e.g. recall scene 3:
   - Command: `/api/v1/dali/scene`
   - HTTP method: `POST`, Content-Type `application/json`
   - Body: `{"line":1,"scene":3}` (add `"controller":"<IP>"` if no default set)
   - Header (if used): `X-API-Key: <key>`

Trigger the command from any Loxone event.

---

## openHAB

openHAB reaches eDIDIO cleanly through the **MQTT bridge**.

1. Run the **MQTT Bridge** against your broker (the same one openHAB uses).
2. Install openHAB's **MQTT binding**, add a Broker Thing, then a Generic MQTT
   Thing with channels pointing at the bridge topics. See
   `templates/openhab-edidio.things` and `templates/openhab-edidio.items`.
3. Link the items to your sitemap / UI.

Example channel (a dimmable light on DALI address 5):
- command topic `edidio/kitchen/set` (`ON`/`OFF`)
- brightness command topic `edidio/kitchen/brightness/set` (`0–254`)

> Alternatively use openHAB's **HTTP binding** to POST to the REST gateway.

---

## Hubitat

- **MQTT:** run the MQTT bridge and use a Hubitat community MQTT driver/app to
  publish to `edidio/<id>/set` and `edidio/<id>/brightness/set`.
- **HTTP (simplest):** in **Rule Machine**, add an action *"Send HTTP GET/POST"*
  to the REST gateway, e.g. POST `http://<gateway>:8080/api/v1/dali/scene` with
  body `{"line":1,"scene":3}`. Trigger from any Hubitat rule/button.

---

## Niagara / Tridium (and other BMS)

Niagara speaks **Modbus** and **BACnet** natively:
- **Modbus:** add a Modbus TCP network in Niagara pointing at the eDIDIO Modbus
  gateway; map registers to points (as with Loxone above).
- **BACnet:** eDIDIO's existing BACnet/IP support integrates directly.

---

## Notes

- These recipes add **named platform support with no new eDIDIO code** — they
  reuse the Modbus / MQTT / REST gateways, which are already tested.
- Register/topic maps are examples; adjust addresses, groups and scenes to your
  project.
