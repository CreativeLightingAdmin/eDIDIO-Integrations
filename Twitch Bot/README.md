# eDIDIO Twitch Bot

Let your **Twitch** chat and viewers control Control Freak **eDIDIO** lighting —
via **chat commands**, **channel-point redemptions** and **bit cheers**. Turn a
stream into an interactive lighting experience (great for IRL streams, esports
setups, charity streams, art installations).

> **Target:** Streaming / creators.
> **Tech:** Node + `tmi.js`, reusing the eDIDIO JS protocol engine (same as the
> Discord bot). Sends frames directly over TCP/TLS — no gateway needed.

## What viewers can do

- **Chat commands** (permission-gated): `!scene 3`, `!light 5 200`, `!on 5`,
  `!off 5`, `!color #FF0000`, `!seq 0`.
- **Channel-point rewards**: redeem *"Party Mode"*, *"Red Alert"*, *"Lights Out"*
  → run a sequence, flash red, blackout.
- **Bit cheers**: cheer ≥100 bits → gold wash; ≥1000 → a celebration sequence.

All of this is configurable in `commands.json` — no code changes.

## Setup

```bash
cd "Twitch Bot"
npm install
cp .env.example .env          # fill in Twitch + controller details
cp src/commands.example.json src/commands.json   # customise commands (optional)
npm start
```

### `.env`
| Var | Description |
|-----|-------------|
| `TWITCH_USERNAME` | bot account username |
| `TWITCH_OAUTH` | `oauth:...` token (get one at https://twitchapps.com/tmi/) |
| `TWITCH_CHANNEL` | channel to join |
| `EDIDIO_HOST` / `EDIDIO_PORT` / `EDIDIO_USE_TLS` | controller |
| `ANNOUNCE` | reply in chat with the result (default true) |

## Command map (`commands.json`)

Three sections — see `src/commands.example.json`:

- **`chat.commands`** — each command has a `permission`
  (`everyone` / `subscriber` / `vip` / `moderator` / `broadcaster`), an `action`,
  and `argFrom` naming which chat args fill which parameters.
- **`rewards`** — channel-point reward **title** (exact) → action.
- **`bits.tiers`** — bit thresholds (`min`) → action; the highest matching tier
  fires.

Actions: `scene` (line, scene), `level` (line, address, level), `on`/`off`
(line, address), `color` (line, hex), `spektra` (zone, index).

## Channel-point redemptions

Twitch chat (tmi.js) delivers **chat + bits** directly, so those work out of the
box. **Channel-point redemptions** come over Twitch **EventSub/PubSub**, not
chat. To wire them up, bridge redemption events to the bot and call:

```js
client.handleRewardRedemption(rewardTitle, redeemerUsername)
```

(the reward→action mapping in `commands.json`/`handleReward` is already built and
tested — you just feed it the reward title from your EventSub listener).

## Testing

```bash
npm test        # node --test
```

`test/mapper.test.js` decodes the actual eDIDIO frame produced by each event —
chat commands (with permission gating), reward redemptions, and bit tiers — so
the bot's real logic is verified **without a Twitch connection or a controller**.
Live testing needs a Twitch account/channel and (to see fixtures) a controller.

## Files

```
Twitch Bot/
├── index.js                  # tmi.js glue: chat/bits -> mapper -> controller
├── src/
│   ├── mapper.js             # event -> eDIDIO frame (pure, tested)
│   ├── config.js             # .env + commands.json loader
│   ├── commands.example.json # command / reward / bits map
│   └── edidio/               # vendored protocol engine (encoder + connection)
└── test/
```

## Safety tips for public streams

- Keep destructive/spammy commands behind `subscriber`/`moderator` permissions.
- Consider Twitch's per-command cooldowns / your own rate limits for `everyone`
  commands so chat can't strobe the room.
- Scenes and bounded levels are safer for `everyone` than raw DMX strobing.

## License

MIT
