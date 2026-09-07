# eDIDIO + Matter

Expose Control Freak **eDIDIO** lighting to **Matter** — the cross-ecosystem
smart-home standard — so a **single integration reaches Amazon Alexa, Google
Home, Apple Home and Samsung SmartThings at once**.

> **Target:** Smart home / convergence.
> **Status:** Working **recipe** using tested components (no new eDIDIO code). A
> native Matter *device* bridge is a heavier future option — see the end and the
> honest note about why.

## The recommended path (works today)

Matter lets a **bridge** expose existing devices to every Matter controller. The
most reliable, zero-extra-code bridge is **Home Assistant**, which eDIDIO already
reaches via the **MQTT Bridge** (with Home Assistant auto-discovery). HA then
exports those lights/scenes to Matter — one QR code pairs them into Alexa,
Google, Apple and SmartThings.

```
eDIDIO ──▶ MQTT Bridge (HA auto-discovery) ──▶ Home Assistant ──▶ Matter bridge ──▶ Alexa / Google / Apple / SmartThings
         (../MQTT Bridge/)                     entities appear     one pairing      all four ecosystems
```

### 1. Get eDIDIO into Home Assistant

Run the **MQTT Bridge** against HA's broker — your eDIDIO lights and scenes
appear automatically as HA entities (no HA YAML). See `../MQTT Bridge/README.md`;
`mqtt.yaml` here is a ready config (edit `controller.host` and the broker).

> Alternative: the native **Home Assistant** integration
> (`home-assistant-control-freak-edidio`) also brings eDIDIO into HA.

### 2. Export the HA entities to Matter

Two common options:

- **Home Assistant Matter Hub** (community add-on
  [`t0bst4r/home-assistant-matter-hub`](https://github.com/t0bst4r/home-assistant-matter-hub)):
  select which HA entities (your eDIDIO lights/scenes) to expose as Matter
  devices; it publishes a Matter bridge with a pairing code.
- Or any HA-based Matter exporter that turns HA entities into a Matter bridge.

### 3. Pair with your ecosystem(s)

Add the Matter bridge in **Alexa / Google Home / Apple Home / SmartThings** using
its pairing code/QR. Matter is multi-admin, so the **same bridge can be paired to
several ecosystems at once**. Your eDIDIO lights and scenes now respond to all of
them (and their voice assistants).

### Result

*"Alexa, turn on the kitchen lights", "Hey Google, set the lounge to 40%", "Siri,
run the dinner scene"* — all driving eDIDIO, through one bridge.

## Why not a native eDIDIO Matter device?

A native Matter **device/bridge** (eDIDIO advertising itself directly on Matter,
no Home Assistant) would be the purest option, but building it honestly requires:

- the **Matter SDK (connectedhomeip / "chip")** device-side stack — a large
  C++/build-toolchain effort (the pure-Python Matter tooling is **controller**-side,
  for *controlling* Matter devices, not *being* one);
- Matter **commissioning** (Thread/Wi-Fi, PASE/CASE, certificates); and
- for shipping with the logo, **Matter certification** (CSA membership + fees).

That's a dedicated project, not a quick win — and until it's built and tested it
would do more harm than good (the same reasoning as the Savant/ELAN native
drivers). The HA-bridge recipe above delivers the **full four-ecosystem outcome
today** with components that are already tested here, so it's the right first
step. The native device bridge can follow if a customer specifically needs
Home-Assistant-free Matter.

## Files

```
Matter/
├── README.md      # this recipe
└── mqtt.yaml      # MQTT bridge config to feed Home Assistant (edit + run in ../MQTT Bridge/)
```

## License

MIT
