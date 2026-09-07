# eDIDIO Raycast / Alfred

Control Control Freak **eDIDIO** lighting from your Mac launcher — **Raycast** or
**Alfred** — with a keystroke: `⌘Space → eDIDIO scene 3`. Great for devs/operators
who want instant lighting control without leaving the keyboard.

> **Target:** Mac power users / developers / AV operators.
> **Tech:** Node scripts calling the eDIDIO **REST API Gateway**.

## Prerequisite

Run the **REST API Gateway** (`../Rest API Gateway/`), reachable from your Mac.
Set these env vars (in Raycast's script env, or your shell profile):

| Var | Description |
|-----|-------------|
| `EDIDIO_GATEWAY` | e.g. `http://192.168.1.100:8080` |
| `EDIDIO_API_KEY` | gateway key, if set |
| `EDIDIO_CONTROLLER` | controller IP, if the gateway has no default |
| `EDIDIO_LINE` / `EDIDIO_DMX_LINE` | default DALI / DMX line (1 / 2) |

## Commands

```
scene <n>            recall a scene
on <addr> · off <addr>
level <addr> <0-254>
group <n> <0-254>
color <#RRGGBB>
seq <index> [zone]
```

## Raycast

Raycast **Script Commands**: point Raycast at the `commands/` folder (Extensions
→ Script Commands → Add Directory). Two commands are included:

- **eDIDIO** — a dispatcher: run it and type e.g. `scene 3` or `color #FF0000`.
- **eDIDIO Scene** — takes just a scene number argument.

Add more by copying a file in `commands/` and changing the `@raycast.*` metadata
+ the args passed to `run()`.

## Alfred

Use an **Alfred Workflow** with a *Run Script* action (Language: `/usr/bin/env
node`), script:

```bash
node "/path/to/Raycast Alfred/commands/edidio.js" "{query}"
```

Wire it to a keyword (e.g. `edidio`) so `edidio scene 3` fires it. Set the
`EDIDIO_*` env vars in the workflow's environment variables.

## Testing

```bash
node --test
```

`test/edidio.test.js` verifies the arg → REST-request mapping (endpoint, headers,
body) for every command, including the no-key/no-controller and override cases —
no gateway or controller needed.

## Files

```
Raycast Alfred/
├── lib/edidio.js         # buildRequest (pure, tested) + run
├── commands/             # Raycast Script Commands (also usable from Alfred)
└── test/
```

## License

MIT
