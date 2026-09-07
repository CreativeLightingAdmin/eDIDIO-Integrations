# eDIDIO MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes
Control Freak **eDIDIO** lighting control as tools for AI assistants — so
**Claude, ChatGPT and other MCP clients can operate architectural lighting from
natural language**: *"dim the lounge to 30%", "recall the dinner scene", "run the
feature-wall sequence".*

> **Target:** AI & next-gen control / demos.
> **Tech:** Python MCP SDK (`MCPServer`) wrapping the shared `edidio_control_py`
> engine.

## Tools

| Tool | Does |
|------|------|
| `set_light_level(line, address, level)` | DALI address 0–63 → level 0–254 |
| `set_group_level(line, group, level)` | DALI group 0–15 → level |
| `turn_light_on / turn_light_off(line, address)` | full / off |
| `recall_scene(line, scene, group?)` | recall a stored scene |
| `set_dmx_color(line, hex)` | RGB `#RRGGBB` across a DMX line |
| `run_spektra(zone, target, index, action)` | SpektraPlus sequence/theme/static |
| `stop_spektra(zone)` | stop and turn off |
| `discover_controllers()` | find eDIDIO controllers on the LAN |

## Setup

```bash
cd "MCP Server"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py   # dev: shared engine
```

The server talks to a controller configured via environment variables:

| Var | Default | |
|-----|---------|--|
| `EDIDIO_HOST` | *(required)* | controller IP/hostname |
| `EDIDIO_PORT` | `23` | 23 (TCP) / 443 (TLS) |
| `EDIDIO_USE_TLS` | `false` | |

Run it directly (stdio transport):

```bash
EDIDIO_HOST=192.168.1.50 python -m edidio_mcp
```

## Use with Claude Desktop

Add to your `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "edidio": {
      "command": "python",
      "args": ["-m", "edidio_mcp"],
      "cwd": "F:\\My Documents\\GitHub\\eDIDIO_3rd_Party\\MCP Server",
      "env": {
        "EDIDIO_HOST": "192.168.1.50",
        "EDIDIO_PORT": "23"
      }
    }
  }
}
```

Restart Claude Desktop; the eDIDIO tools appear. Then just ask:
*"Turn on light 5 on line 1", "Set the living room group to 40%", "Recall scene 3".*
Works the same in any MCP client (Cursor, custom agents, etc.).

## Testing

```bash
python -m pytest -q
```

- `test_controller.py` — the wrapper maps each command to the correct
  `edidio_control_py` call (fake client, no network).
- `test_server.py` — the MCP tools are registered/callable, drive the controller,
  and report errors as strings (so the assistant gets feedback, never a crash).

Live: point `EDIDIO_HOST` at a controller, connect an MCP client, and ask it to
change the lighting.

## Files

```
MCP Server/
├── edidio_mcp/
│   ├── __main__.py        # python -m edidio_mcp
│   ├── server.py          # MCPServer + tools
│   ├── controller.py      # async wrapper over edidio_control_py (tested)
│   └── discovery.py       # LAN discovery (for discover_controllers)
├── requirements.txt
└── tests/
```

## Notes

- Tools return human-readable strings and surface errors as messages, so an
  assistant can retry or explain — connection issues never crash the server.
- Command-oriented; live fixture-state read-back is a possible future addition.

## License

MIT
