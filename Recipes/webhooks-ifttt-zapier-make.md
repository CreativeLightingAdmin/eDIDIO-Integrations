# eDIDIO via Webhooks — IFTTT / Zapier / Make

Any automation platform that can send an **HTTP request** can control eDIDIO
through the **REST API Gateway** (`../Rest API Gateway/`). No new code — just
point a webhook action at the gateway. This unlocks thousands of triggers:
schedules, location (geofence), voice assistants, buttons, weather, calendar,
email, other smart devices…

## Prerequisite

Run the **REST API Gateway**, reachable from the internet-facing automation
platform (directly, via a reverse proxy, or a tunnel like Cloudflare Tunnel).
Set an `EDIDIO_API_KEY` and (optionally) `EDIDIO_IP` default. See the gateway
README.

## The request

All actions are `POST` with a JSON body. Add header `X-API-Key: <key>` if set,
and `"controller": "<ip>"` in the body if the gateway has no default.

| Action | Endpoint | Body |
|--------|----------|------|
| Recall scene | `/api/v1/dali/scene` | `{"line":1,"scene":3}` |
| Set level | `/api/v1/dali/level` | `{"line":1,"address":5,"level":200}` |
| Group level | `/api/v1/dali/group/level` | `{"line":1,"group":0,"level":128}` |
| On / off | `/api/v1/dali/command` | `{"line":1,"address":5,"command":"on"}` |
| DMX colour | `/api/v1/dmx/color` | `{"line":2,"hex":"#FF0000"}` |
| SpektraPlus | `/api/v1/spektra` | `{"zone":1,"type":"sequence","index":0,"action":"start"}` |

## IFTTT

Use the **Webhooks** service as the *that* action:

1. Create an applet; pick any trigger (time, location, Google Assistant, a
   button widget, etc.).
2. Action → **Webhooks → Make a web request**:
   - URL: `https://<gateway>/api/v1/dali/scene`
   - Method: `POST`
   - Content Type: `application/json`
   - Body: `{"line":1,"scene":3}`
   - Additional headers: `X-API-Key: <key>`

Example: *"When I say 'Hey Google, movie time' → recall scene 3."*

## Zapier

1. New Zap; choose any trigger app.
2. Action app → **Webhooks by Zapier → POST**:
   - URL: `https://<gateway>/api/v1/dali/group/level`
   - Payload Type: **JSON**
   - Data: `line = 1`, `group = 0`, `level = 128`
   - Headers: `X-API-Key = <key>`

Example: *"When a Google Calendar event 'Presentation' starts → dim the room."*

## Make (Integromat)

1. New scenario; add any trigger module.
2. Add **HTTP → Make a request**:
   - URL: `https://<gateway>/api/v1/spektra`
   - Method: `POST`, Body type: **Raw / JSON**
   - Content: `{"zone":1,"type":"sequence","index":0,"action":"start"}`
   - Header: `X-API-Key: <key>`

Example: *"When a webhook fires from your POS/booking system → start a welcome
sequence."*

## Tips

- Test the exact request first with `curl` (see the gateway README) so you know
  the body is right before wiring the platform.
- Keep the gateway behind the API key and, ideally, an allowlist / tunnel — a
  public control endpoint should be authenticated.
- For time-of-day automations you can also use eDIDIO's own schedules; webhooks
  shine when the trigger comes from *another* service.
