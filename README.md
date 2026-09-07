# eDIDIO 3rd-Party Integrations

A collection of integrations, drivers, gateways and bridges that connect the
Control Freak **eDIDIO** lighting controller (DALI, DMX, SpektraPlus) to a wide
range of third-party platforms — from professional AV control systems and
building automation to smart home, streaming, AI, game engines and DIY.

> **Status:** ~40 integrations + recipes, **500+ automated tests across 34
> suites, all green** (`run-all-tests.ps1` / `.sh`). Most are fully built and
> tested here; a few are recipes (reusing gateways) or logic cores awaiting
> vendor-tool packaging (noted per item).

## How it all fits together

Two shared **engines** and a family of **byte-identical frame encoders** back
everything, so behaviour is consistent everywhere:

- **`edidio_control_py`** — the async Python client (in `../edidio_control_py`),
  base for all Python gateways/drivers. **0.4.0** adds *authoring* builders
  (create sequences/themes/schedules) used by Spektra AI.
- **JS protocol engine** — vendored into the Node integrations (message builder,
  framing, connection with keep-alive/reconnect).
- **Ten byte-identical encoders** — the same eDIDIO wire frames implemented in
  Python (protobuf + pure), JavaScript, Lua, NetLinx, C#, C++, **C**, **Tcl**,
  and a Savant payload generator — **all validated against the same reference
  frames**, so a command that works in one integration produces identical bytes
  in every other. See **[ENCODERS.md](ENCODERS.md)**.

Most Python gateways/bridges share one architecture: **config map → pure mapping
module (unit-tested) → async dispatcher → `edidio_control_py`**. The four
game-state bridges (CS2, Dota 2, KSP, GTA5) and the ambient-data engine reuse it
directly, which is why new sources are quick to add and testable without hardware.

- **[ENCODERS.md](ENCODERS.md)** — the ten encoders + reference frames.
- **`run-all-tests.ps1` / `run-all-tests.sh`** — run every suite at once.

## Integrations

### Professional AV control
| Integration | Folder | Notes |
|-------------|--------|-------|
| Extron ControlScript | `Extron Driver/` | Python driver + pure encoder |
| AMX (NetLinx + Muse) | `AMX Driver/` | `.axi` module + Muse Python |
| RTI (Integration Designer) | `RTI Driver/` | JS DDK driver core |
| Savant | `Savant Driver/` | command-payload generator for Profiler |
| ELAN g! | `ELAN Driver/` | Lua driver core |
| Bitfocus Companion | `Companion Module/` | Stream Deck / live-events surface |
| Stream Deck | `Stream Deck Plugin/` | button control via REST gateway |

### Gateways & building automation
| Integration | Folder | Notes |
|-------------|--------|-------|
| REST API Gateway | `Rest API Gateway/` | HTTP/JSON → eDIDIO (the hub many others use) |
| Modbus TCP/RTU | `Modbus TCPRTUGateway/` | BMS/PLC register map |
| KNX | `KNX Gateway/` | KNXnet/IP group addresses (+ test sender) |
| Node-RED | `Note-RED Package/` | `node-red-contrib-edidio` nodes |
| Docker | `Docker/` | containerised Python gateways + compose |

### Smart home & IoT
| Integration | Folder | Notes |
|-------------|--------|-------|
| MQTT Bridge | `MQTT Bridge/` | + Home Assistant auto-discovery |
| Apple HomeKit | `HomeKit Bridge/` | local Siri + Home app |
| Matter | `Matter/` | recipe → Alexa+Google+Apple+SmartThings |
| SmartThings Edge | `SmartThings Edge/` | on-hub Lua driver |

### AI
| Integration | Folder | Notes |
|-------------|--------|-------|
| **Spektra AI** | `Spektra AI/` | MCP server that **authors** sequences/themes/schedules from natural language (preview→confirm) |
| MCP Server | `MCP Server/` | MCP server to *trigger* lighting (levels/scenes/Spektra) |
| Generative AI Moods | `GenAI Moods/` | text prompt → LLM colour palette → lighting |

### Streaming & messaging
| Integration | Folder | Notes |
|-------------|--------|-------|
| Twitch Bot | `Twitch Bot/` | chat / channel points / bits |
| OBS Studio | `OBS Studio/` | scene/stream/record events |
| Discord Bot | *(separate repo)* | `eDIDIBotDiscordLC` |
| Telegram Bot | `Telegram Bot/` | chat commands |
| Slack App | `Slack App/` | `/edidio` slash command |
| Microsoft Teams | `Teams App/` | @mention outgoing webhook |

### Game state (a shared bridge pattern)
| Integration | Folder | Notes |
|-------------|--------|-------|
| Counter-Strike 2 | `CS2 GSI/` | health/flash/bomb → lighting (Valve GSI) |
| Dota 2 | `Dota 2 GSI/` | hero health/death/respawn (Valve GSI) |
| Kerbal Space Program | `Kerbal Space Program/` | throttle/fuel/stage/abort (kRPC) |
| GTA V | `GTA5/` | wanted-level police siren (ScriptHookV mod) |

### Ambient data → light
| Integration | Folder | Notes |
|-------------|--------|-------|
| Ambient Data engine | `Ambient Data/` | one engine + configs: stock/crypto, aurora, ISS, rocket, F1, solar, UniFi, server-health, D&D, … |

### Show control, game engines & maker
| Integration | Folder | Notes |
|-------------|--------|-------|
| OSC Bridge | `OSC Bridge/` | QLab / TouchDesigner / consoles |
| MIDI Bridge | `MIDI Bridge/` | Launchpad / APC / faders |
| Unity | `Unity Package/` | C# package (+ C# encoder) |
| Unreal Engine | `Unreal Engine/` | recipe via OSC / REST |
| Maker Kit | `Maker Kit/` | Arduino/ESP32 C++ lib + Raspberry Pi GPIO |
| Minecraft | `Minecraft Plugin/` | in-game events → lighting |

### FPGA / embedded / industrial
| Integration | Folder | Notes |
|-------------|--------|-------|
| FPGA toolchain | `FPGA/` | dependency-free **C** encoder (soft-CPUs) + Verilog IP-core concept |
| Tcl bridge | `Tcl Bridge/` | pure **Tcl** encoder for Vivado/Quartus consoles |

### Desktop / launcher
| Integration | Folder | Notes |
|-------------|--------|-------|
| Raycast / Alfred | `Raycast Alfred/` | Mac launcher (⌘Space) lighting commands |

### Recipes & tooling
| Item | Folder | Notes |
|------|--------|-------|
| Platform recipes | `Recipes/` | Loxone, openHAB, Hubitat, Niagara, Homey Pro, IFTTT/Zapier/Make |
| Test Harness | `Test Harness/` | discover / connect / actuate against real hardware |

## Hardware verification status

Every integration has an automated test suite (~500 tests, all passing — see below).
Beyond that, the table records how far each has been **verified against a live
eDIDIO controller** (an S10, with a DMX sniffer on Line 2 and a DALI sniffer on
Line 1). Live output was confirmed two ways: reading the controller's own DMX/DALI
level cache back, **and** watching the sniffers.

Legend:
- ✅ **Fully verified on hardware** — driven end-to-end, output confirmed on the device.
- 🟡 **Partially verified** — the command path was driven to the live device and
  confirmed, but the integration's *external transport* (a physical bus, a paired
  app, a third-party cloud) needs its own hardware/account and was not exercised.
- 🧪 **Frame-verified** — produces byte-identical frames to the verified encoders
  (asserted against shared reference frames), but runs in a host we can't drive from
  a PC (FPGA board, game engine, dealer system). The bytes that reach the wire are
  proven; the host integration isn't run here.

| Integration | Status | How it was verified |
|---|---|---|
| `edidio_control_py` (core) | ✅ | DMX on Line 2 + DALI (arc/command/group/broadcast/scene) on Line 1, cache read-back + sniffer |
| Test Harness | ✅ | Discovery + connect + actuate DALI/DMX on the live device |
| REST API Gateway | ✅ | `POST /dmx/*` + `/dali/*` (incl. group/scene) → device, cache + sniffer |
| Modbus Gateway | ✅ | Holding-register writes → DALI level + Spektra sequence, dispatch log + cache |
| OSC Bridge | ✅ | OSC messages → DALI level + Spektra, dispatch log + cache |
| MQTT Bridge | ✅ | Published topics via a live broker → DALI, dispatch log |
| KNX Gateway | ✅ | KNXnet/IP **routing** telegrams → DALI level + scene, dispatch log |
| CS2 GSI | ✅ | Simulated game-state JSON → health/flash/bomb colours, cache |
| Dota 2 GSI | ✅ | Simulated game-state JSON → health/death colours, cache |
| GTA5 | ✅ | Simulated events → wasted/busted colours + wanted-level siren sequence, cache |
| Ambient Data | ✅ | Offline demo source → live gradient sweep on Line 2, cache |
| GenAI Moods | ✅ | Mood prompt (offline provider) → DMX colour fill, cache |
| Spektra AI (MCP) | ✅ | Author/schedule/calendar/clock/playback tools, all confirmed live |
| MCP Server | ✅ | `dmx_color` + `recall_scene` tools → device, cache |
| Slack App | ✅ | Signed slash-command → REST gateway → DALI group/scene, sniffer |
| Teams App | ✅¹ | HMAC-signed webhook (valid accepted, invalid rejected) → REST → DALI, sniffer |
| MIDI Bridge | 🟡 | MIDI CC/note → DALI + Spektra via the live handler; physical MIDI port not run |
| HomeKit Bridge | 🟡 | Light/scene accessory specs → DALI to the device; iOS HAP pairing not run |
| Telegram Bot | 🟡 | Vendored engine frame-verified; live Telegram API token not exercised |
| Twitch Bot | 🟡 | Vendored engine frame-verified; live Twitch account not exercised |
| Companion / Stream Deck / Note-RED | 🟡 | Frame-verified; run inside their host apps (not driven from a PC here) |
| RTI / Extron / AMX / ELAN / Savant / SmartThings | 🧪 | Encoders frame-verified against shared reference frames; need dealer/host tooling |
| Unity / FPGA (C+Verilog) / Maker (Arduino, Pi) | 🧪 | Encoders frame-verified; run on their target hardware/engine |

¹ The Teams app was driven with a payload signed exactly as Microsoft's Outgoing
Webhook servers sign theirs (HMAC-SHA256), so signature verification, `@mention`
stripping, forwarding, and device output are all verified. Relaying a message from
the actual Teams client additionally requires a Microsoft 365 work/school account
(personal/free Teams can't create Outgoing Webhooks) and a public HTTPS endpoint —
that Microsoft-cloud relay hop, external to this integration, was not exercised.

> **Live testing confirmed two protocol details, applied consistently across every
> encoder:** (1) DALI groups, broadcast and scenes are addressed through the DALI
> address field (group = 64 + n, broadcast = 80) with the standard *GO TO SCENE*
> command; (2) whole-universe DMX colour fills use the DMX `repeat` field, so a
> single compact frame paints the entire universe. Both are verified on hardware.

## Running the tests

Run **everything** at once:

```powershell
pwsh ./run-all-tests.ps1        # Windows (handles the py -3 launcher + msys2 toolchain)
```
```bash
./run-all-tests.sh              # macOS/Linux
```

Or per integration (from its folder): `python -m pytest -q`, `node --test` /
`npm test`, `dotnet test` (Unity C#), `gcc`/`g++` (FPGA/Maker encoders), `tclsh`
(Tcl). Each README documents its own tests. Lua encoders (ELAN / SmartThings) run
in real Lua via the `lupa` interpreter under pytest.

Most tests need **no eDIDIO hardware** — protocol clients and stub controllers
verify the full command path. The **Test Harness** covers live verification against
a controller.

## License

MIT (per-integration; see each folder).
