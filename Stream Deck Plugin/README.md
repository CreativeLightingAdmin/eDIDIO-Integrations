# eDIDIO Stream Deck Plugin

An Elgato **Stream Deck** plugin that fires Control Freak **eDIDIO** lighting
commands from physical buttons — recall scenes, set levels, colours and
SpektraPlus effects with one press. Great for AV operators, control rooms and
streamers.

> **Target:** AV operators / live / streaming.
> **Tech:** Stream Deck plugin (HTML/JS) that calls the **eDIDIO REST API
> Gateway** — so the gateway does the protocol work.

## Prerequisite

The **REST API Gateway** must be running and reachable from the machine with the
Stream Deck (set its `EDIDIO_IP`, and an API key if you want auth). See
`../Rest API Gateway/README.md`.

## Install

1. Copy the `com.creativelighting.edidio.sdPlugin` folder into your Stream Deck
   plugins directory, or double-click a packaged `.streamDeckPlugin`:
   - **Windows:** `%APPDATA%\Elgato\StreamDeck\Plugins\`
   - **macOS:** `~/Library/Application Support/com.elgato.StreamDeck/Plugins/`
2. Restart the Stream Deck app. Drag the **eDIDIO → eDIDIO Command** action onto
   a key.
3. In the button's settings (Property Inspector), set the **Gateway URL**
   (e.g. `http://192.168.1.100:8080`), optional **API key** / **Controller IP**,
   then pick a **Command** and its parameters.

> Add PNG icons under `com.creativelighting.edidio.sdPlugin/icons/`
> (`plugin`, `action`, `key`, `category`) to brand the plugin; the code works
> without them.

## Commands

| Command | Calls |
|---------|-------|
| Recall scene | `POST /api/v1/dali/scene` |
| Set level (address) | `POST /api/v1/dali/level` |
| Set level (group) | `POST /api/v1/dali/group/level` |
| Light on / off | `POST /api/v1/dali/command` |
| DMX colour | `POST /api/v1/dmx/color` |
| SpektraPlus | `POST /api/v1/spektra` |

On press the button shows a checkmark on success, or an alert if the gateway
call fails.

## Testing

```bash
node --test        # request-mapping tests
```

`test/request.test.js` verifies the settings→REST-request mapping (endpoint,
headers, body) for every command. The Stream Deck WebSocket glue (`app.js`,
`pi.js`) needs the Stream Deck app to run — the tested part is the request
building, which is the plugin's real logic.

## Files

```
Stream Deck Plugin/
├── com.creativelighting.edidio.sdPlugin/
│   ├── manifest.json      # plugin + action definitions
│   ├── index.html         # headless plugin page
│   ├── app.js             # Stream Deck WebSocket glue → fetch to the gateway
│   ├── request.js         # settings -> REST request (pure, tested)
│   ├── pi.html / pi.js    # property inspector (button settings)
│   └── icons/             # (add your PNGs here)
└── test/
```

## License

MIT
