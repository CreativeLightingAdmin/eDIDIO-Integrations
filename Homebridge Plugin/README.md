# homebridge-edidio

A **Homebridge** plugin that brings Control Freak **eDIDIO** lighting into Apple
Home: DALI short addresses and groups appear as dimmable lightbulbs, stored DALI
scenes as momentary switches.

> **Target:** households/installers already running Homebridge (Raspberry Pi,
> NAS, Docker). For a standalone bridge without Homebridge, see `HomeKit Bridge/`.
> **Tech:** Node.js dynamic platform plugin; talks straight to the controller over
> TCP/TLS with the byte-verified JS encoder — no gateway needed.

## Features

- **Lights** — On/Off + Brightness for a DALI short address or group.
- **Scenes** — recall a stored scene (broadcast or on a group) from a switch that
  flips back off after a second.
- **Live state** (firmware 1.4.0+) — the plugin subscribes to the controller's
  event stream, so changes from wall panels, schedules, SpektraPlus or other apps
  show up in Apple Home. Turn off with `liveFeedback: false`.
- Keep-alive + automatic reconnect (with resubscribe).

## Install

From the Homebridge UI, search **homebridge-edidio** once published — or locally:

```bash
cd "Homebridge Plugin"
npm link            # or: sudo npm install -g .
```

## Configuration

Configure from the Homebridge UI (the form is generated from `config.schema.json`),
or in `config.json`:

```json
{
  "platforms": [
    {
      "platform": "EdidioPlatform",
      "name": "eDIDIO",
      "host": "192.168.1.50",
      "port": 23,
      "useTLS": false,
      "liveFeedback": true,
      "lights": [
        { "name": "Kitchen", "line": 1, "address": 5 },
        { "name": "Living Room", "line": 1, "group": 0 }
      ],
      "scenes": [
        { "name": "Movie", "line": 1, "scene": 3 },
        { "name": "Welcome", "line": 1, "group": 4, "scene": 1 }
      ]
    }
  ]
}
```

Each light sets exactly one of `address` (0-63) or `group` (0-15). Accessories are
keyed by controller + target, so renaming one keeps its HomeKit identity; removing
it from the config removes it from Home.

## Tests

```bash
npm test
```

A fake Homebridge API and a fake connection cover config validation, HomeKit
writes → frames (asserted byte-for-byte against the shared encoder), live bus
events → characteristic updates, and accessory cache handling.

## Shared code

`lib/edidio_frames.js`, `lib/eventStream.js` and `lib/connection.js` are vendored
from the repo's `shared/` folder — edit them there and run
`python tools/sync_vendored.py`.

## License

MIT
