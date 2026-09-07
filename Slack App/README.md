# eDIDIO Slack App

Control Control Freak **eDIDIO** lighting from **Slack** with a `/edidio`
slash-command — "turn on the boardroom", "set the foyer to a scene" — from the
chat your team already lives in. Great for corporate/AV, offices and meeting
rooms.

> **Target:** Enterprise / office / AV.
> **Tech:** Node + Express, forwarding to the eDIDIO **REST API Gateway** (which
> does the protocol work). Verifies Slack's request signature.

## Commands

```
/edidio scene <0-15> [line]
/edidio on <addr> [line] · /edidio off <addr> [line]
/edidio level <addr> <0-254> [line]
/edidio group <0-15> <0-254> [line]
/edidio color <#RRGGBB> [line]
/edidio seq <index> [zone]
/edidio help
```

## Setup

1. Run the **REST API Gateway** (`../Rest API Gateway/`), reachable from this app.
2. Configure and run this app:

```bash
cd "Slack App"
npm install
cp .env.example .env      # set SLACK_SIGNING_SECRET + EDIDIO_GATEWAY_URL
npm start                 # listens on :3000
```

3. Expose it publicly (e.g. a reverse proxy or `ngrok http 3000`) so Slack can
   reach `/slack/command`.
4. In the **Slack API** dashboard → your app → **Slash Commands** → create
   `/edidio` with the Request URL `https://<your-host>/slack/command`. Copy the
   app's **Signing Secret** into `.env`.

### `.env`
| Var | Description |
|-----|-------------|
| `PORT` | listen port (default 3000) |
| `SLACK_SIGNING_SECRET` | from your Slack app (verifies requests) |
| `EDIDIO_GATEWAY_URL` | e.g. `http://192.168.1.100:8080` |
| `EDIDIO_API_KEY` | REST gateway key (if set) |
| `EDIDIO_CONTROLLER` | controller IP (if the gateway has no default) |

## Security

Requests are verified with Slack's **signing secret** (HMAC + replay window), so
only genuine Slack requests are accepted. Keep the gateway on your private
network / behind the API key.

## Testing

```bash
npm test        # node --test
```

`test/mapper.test.js` verifies the slash-text → REST-request mapping (endpoint,
headers, body) for every command, including validation and the no-key/no-controller
cases — **without Slack or the gateway**. Live: wire the slash command to a
running app + gateway and try `/edidio scene 3`.

## Files

```
Slack App/
├── index.js          # Express endpoint (Slack signature verify) -> gateway
├── src/mapper.js     # slash text -> REST request (pure, tested)
└── test/
```

## License

MIT
