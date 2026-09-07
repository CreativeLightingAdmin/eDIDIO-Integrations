# eDIDIO Minecraft Plugin

A **Minecraft** (Spigot/Paper) server plugin that drives real Control Freak
**eDIDIO** architectural lighting from in-game events — a fun demo, an education
piece, and genuinely useful for gaming lounges, streamer setups and interactive
exhibits. A player joins → lights welcome them; a thunderstorm rolls in → the room
goes stormy; a player dies → red alert.

> **Target:** Novelty / education / experiential.
> **Tech:** Java (Spigot/Paper API) calling the eDIDIO **REST API Gateway**.

## Features

- **Event triggers** (each toggleable in `config.yml`):
  - player **join** → recall a scene
  - player **death** → red DMX flash
  - **weather** change → storm/clear scenes
- **`/edidio` command** (permission `edidio.control`, default OP):
  `/edidio scene <0-15>` · `/edidio level <addr> <0-254>` · `/edidio color <#RRGGBB>`

All gateway calls run **asynchronously** so they never block the server tick.

## Prerequisite

Run the **REST API Gateway** (`../Rest API Gateway/`), reachable from the
Minecraft server. Set its controller IP (and API key if you use one).

## Build

```bash
cd "Minecraft Plugin"
mvn package
# -> target/eDIDIO-1.0.0.jar
```

(Requires Maven + JDK 17+ for modern Spigot; the code targets Java 11 bytecode.)

## Install

1. Copy `target/eDIDIO-1.0.0.jar` into your server's `plugins/` folder.
2. Start the server once to generate `plugins/eDIDIO/config.yml`.
3. Edit it — set `gatewayUrl`, `apiKey`, `controller`, and the scene/line mapping.
4. Reload (`/reload`) or restart.

```yaml
gatewayUrl: "http://192.168.1.100:8080"
controller: "192.168.1.50"
mapping: { line: 1, dmxLine: 2 }
events: { join: true, joinScene: 1, death: true, weather: true, stormScene: 3, clearScene: 1 }
```

## Testing

The lighting-request logic lives in `EdidioClient` (no Bukkit dependency), so it's
tested standalone against a real local HTTP server:

```bash
cd test
javac -d out ../src/main/java/au/com/creativelighting/edidio/EdidioClient.java EdidioClientTest.java
java -cp out EdidioClientTest
```

Asserts every method sends the correct endpoint, JSON body and API-key header
(including the no-controller / no-key cases) — no Minecraft, no gateway, no
controller. The plugin class (`EdidioPlugin`) needs the Spigot API, provided by
Maven at build time.

## Files

```
Minecraft Plugin/
├── pom.xml
├── src/main/java/au/com/creativelighting/edidio/
│   ├── EdidioPlugin.java   # Bukkit events + /edidio command -> async calls
│   └── EdidioClient.java   # REST gateway HTTP client (tested standalone)
├── src/main/resources/
│   ├── plugin.yml
│   └── config.yml
└── test/EdidioClientTest.java
```

## License

MIT
