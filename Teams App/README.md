# eDIDIO Microsoft Teams App

Control Control Freak **eDIDIO** lighting from **Microsoft Teams** — @mention the
webhook with a command ("@eDIDIO scene 3") from the channel your team uses.
Corporate/AV counterpart to the Slack app.

> **Target:** Enterprise / office / AV (Microsoft 365).
> **Tech:** Node + Express **Outgoing Webhook**, forwarding to the eDIDIO **REST
> API Gateway**. Verifies Teams' HMAC signature.

## Commands

@mention the webhook, then a command:

```
@eDIDIO scene <0-15> [line]
@eDIDIO on <addr> [line] · @eDIDIO off <addr> [line]
@eDIDIO level <addr> <0-254> [line]
@eDIDIO group <0-15> <0-254> [line]
@eDIDIO color <#RRGGBB> [line]
@eDIDIO seq <index> [zone]
@eDIDIO help
```

## Setup

1. Run the **REST API Gateway** (`../Rest API Gateway/`), reachable from this app.
2. Configure and run this app:

```bash
cd "Teams App"
npm install
cp .env.example .env      # set TEAMS_SECRET + EDIDIO_GATEWAY_URL
npm start                 # listens on :3978
```

3. Expose it publicly (reverse proxy / tunnel) so Teams can reach `/teams`.
4. In Teams: **Channel → Manage channel → Connectors → Outgoing Webhook** (or
   *Workflows/Apps* depending on tenant). Set:
   - **Callback URL**: `https://<your-host>/teams`
   - **Name**: `eDIDIO` (put the same value in `TEAMS_BOT_NAME`)
   - Copy the generated **security token** into `TEAMS_SECRET`.

### `.env`
| Var | Description |
|-----|-------------|
| `PORT` | listen port (default 3978) |
| `TEAMS_SECRET` | base64 security token from the outgoing webhook (verifies requests) |
| `TEAMS_BOT_NAME` | webhook display name (used to strip the @mention) |
| `EDIDIO_GATEWAY_URL` | e.g. `http://192.168.1.100:8080` |
| `EDIDIO_API_KEY` | REST gateway key (if set) |
| `EDIDIO_CONTROLLER` | controller IP (if the gateway has no default) |

## Security

Requests are verified with Teams' **HMAC-SHA256** scheme: Teams signs the raw body
with the base64-decoded shared secret and sends `Authorization: HMAC <sig>`; the
app recomputes and compares in constant time. Keep the gateway private / behind
its API key.

## Testing

```bash
npm test        # node --test
```

`test/teams.test.js` covers: the command → REST-request mapping (shared with the
Slack app), stripping the `@mention` from the Teams activity text, and the HMAC
verification (accepts a correctly signed body, rejects bad signatures / tampered
bodies) — all **without Teams or the gateway**.

## Files

```
Teams App/
├── index.js          # Express Outgoing Webhook endpoint -> gateway
├── src/
│   ├── mapper.js     # command text -> REST request (shared w/ Slack, tested)
│   ├── verify.js     # Teams HMAC verification (tested)
│   └── extract.js    # strip @mention from the activity text (tested)
└── test/
```

## License

MIT
