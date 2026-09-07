# eDIDIO Telegram Bot

Control Control Freak **eDIDIO** lighting from **Telegram** — send `/scene 3` or
`/group 0 128` from your phone. Handy for facilities staff, small venues, home
users, or anyone who wants quick lighting control from a chat they already have.

> **Target:** Messaging / remote control.
> **Tech:** Node + `node-telegram-bot-api`, reusing the eDIDIO JS engine. Sends
> frames directly over TCP/TLS — no gateway needed.

## Commands

```
/scene <0-15> [line]        recall a scene
/on <addr> [line]           turn a light on
/off <addr> [line]          turn a light off
/level <addr> <0-254> [line] set a light's level
/group <0-15> <0-254> [line] set a group's level
/color <#RRGGBB> [line]     DMX colour
/seq <index> [zone]         start a SpektraPlus sequence
/help                       show commands
```

(`line` defaults to 1 for DALI, 2 for `/color`.)

## Setup

1. Create a bot with **@BotFather** on Telegram; copy its token.
2. Configure and run:

```bash
cd "Telegram Bot"
npm install
cp .env.example .env      # set TELEGRAM_TOKEN + EDIDIO_HOST (+ ALLOWED_CHAT_IDS)
npm start
```

### `.env`
| Var | Description |
|-----|-------------|
| `TELEGRAM_TOKEN` | from @BotFather |
| `EDIDIO_HOST` / `EDIDIO_PORT` / `EDIDIO_USE_TLS` | controller |
| `ALLOWED_CHAT_IDS` | comma-separated chat IDs allowed to control lights (blank = anyone) |

**Security:** set `ALLOWED_CHAT_IDS` for anything public. Message the bot and
check the logs (or use `@userinfobot`) to find your chat ID. Unauthorised chats
get a polite refusal.

## Testing

```bash
npm test        # node --test
```

`test/mapper.test.js` decodes the actual eDIDIO frame each command produces
(scene/level/group/on/off/color/seq), plus help/validation replies — verified
**without Telegram or a controller**. Live testing needs a bot token; a
controller to see fixtures respond.

## Files

```
Telegram Bot/
├── index.js              # telegram glue -> mapper -> controller (+ allowlist)
├── src/
│   ├── mapper.js         # command -> eDIDIO frame (pure, tested)
│   └── edidio/           # vendored protocol engine
└── test/
```

## License

MIT
