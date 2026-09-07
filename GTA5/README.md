# eDIDIO GTA V

Your room becomes a police light show when the heat is on. Drives Control Freak
**eDIDIO** lighting from **Grand Theft Auto V**: the **wanted level** throws an
escalating red/blue siren wash, health tints the room, and wasted/busted moments
flash.

> **Target:** Gaming / streaming / experiential.
> **Tech:** A Script Hook V .NET mod (in-game) POSTs game state to a Python
> bridge that maps it to eDIDIO. Part of the game-state family (CS2, Dota 2).

## Architecture

GTA V has **no native game-state export**, so a small mod reads the state and
POSTs it to the local bridge:

```
GTA V + EdidioMod (ScriptHookV .NET)  ──JSON POST──▶  bridge  ──eDIDIO TCP──▶  fixtures
                                                          │
                                                          └─ wanted -> siren, health -> colour
```

The **bridge + mapper are fully tested here** (below). Only the **mod** needs the
game to run.

## Setup

### 1. Run the bridge

```bash
cd "GTA5"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py
cp config.example.yaml config.yaml         # set controller.host + effects
python run.py --config config.yaml
```

### 2. Install the mod (`mod/EdidioMod.cs`)

Requires **Script Hook V** + **Script Hook V .NET** installed in GTA V. Build
`mod/EdidioMod.cs` into a .NET Framework 4.8 class library referencing
`ScriptHookVDotNet3.dll`, and drop the resulting `.dll` in GTA V's `scripts/`
folder. Set `BridgeUrl` (and `Token`, if you use one) at the top of the file to
match your bridge.

Load GTA V — the mod POSTs on wanted/health/vehicle changes and on wasted/busted.

## Effects (`config.yaml -> gta5`)

| Effect | From | Config |
|--------|------|--------|
| `wanted` | wanted level 0-5 → per-star action (fires on change) | `actions: {0..5}` |
| `health` | health % → colour when **not** wanted | `line`, `colors` |
| `events` | `wasted` / `busted` one-shots | map of `event: action` |

**Best siren:** point the wanted tiers at a SpektraPlus **sequence** that
alternates red/blue on the controller (author one with the Spektra AI MCP or the
app), and escalate the sequence index/speed per star.

## Testing

```bash
python -m pytest -q
```

- `test_mapper.py` — wanted escalation (fires on change, clamps, clears), health
  suppressed under a wanted level, health gradient when calm, wasted/busted
  one-shots, missing-field safety.
- `test_server.py` — POSTs game state to the actual HTTP handler.

No GTA V or controller needed for the tests; the mod is the only game-dependent
piece.

## Files

```
GTA5/
├── run.py
├── config.example.yaml
├── mod/EdidioMod.cs        # ScriptHookV .NET mod (build + drop in GTA's scripts/)
├── edidio_gta5/  (mapper.py [pure, tested], server.py, config.py, dispatcher.py)
└── tests/
```

## License

MIT
