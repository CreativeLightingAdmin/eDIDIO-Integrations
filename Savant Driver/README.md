# eDIDIO Savant Driver

Tools and command payloads for integrating Control Freak **eDIDIO** lighting into
**Savant** home automation — DALI, DMX and SpektraPlus over TCP.

> **Target:** High-end residential (Savant).
> **Status:** Command generator + verified payloads, ready to drop into a Savant
> profile.

## How Savant integration works (and what needs the Savant tools)

Savant integrates third-party devices via **profiles** built in **RacePoint
Blueprint** with the **Savant Profiler**. A profile defines a component and its
**commands**, where each command sends a defined data string to the device over
a TCP connection.

- **What this repo provides (no Savant tools needed):** the **exact byte payloads**
  for every eDIDIO lighting command, generated from the byte-verified
  `edidio_frames.py` encoder (`generate_commands.py` / `commands.py`). Paste these
  into your profile's command data fields.
- **What requires the Savant environment:** building and deploying the actual
  **`.profile`** needs **RacePoint Blueprint + the Savant Profiler** and a Savant
  dealer account; the profile is then added to the Blueprint config and deployed
  to a Savant host. See the
  [Component Profile Tool & Profiler reference](https://sav-documentation.s3.amazonaws.com/Product%20Reference%20Guides/CPTandProfilerSoftware_RefGuide.pdf).

## Generating command payloads

```bash
cd "Savant Driver"

# A ready-to-paste reference set of common commands for a line:
python generate_commands.py table --line 1

# Individual commands:
python generate_commands.py scene --line 1 --scene 3
python generate_commands.py dali-level --line 1 --address 5 --level 254
python generate_commands.py dali-group-level --line 1 --group 0 --level 127
python generate_commands.py dali-off --line 1 --address 5
python generate_commands.py dmx-color --line 2 --hex FF0000
python generate_commands.py spektra --zone 1 --type sequence --index 0 --action start
```

Each prints two formats:

```
Scene 3
  hex     : CD 00 0B 08 01 92 01 06 08 01 30 03 48 03
  escaped : \xCD\x00\x0B\x08\x01\x92\x01\x06\x08\x01\x30\x03\x48\x03
```

Use whichever your profile's command data field expects (space-separated hex or a
`\xNN` escaped byte string).

## Building the profile (in Blueprint / Profiler)

1. Create a new **generic TCP** component/profile for the controller;
   connection is **TCP, port 23** (or 443 for TLS-capable units).
2. Add a **command** for each action (e.g. "Scene 3", "All On", "All Off",
   "Group 0 50%") and paste the generated payload as its send data.
3. For a **heartbeat**, add a repeating command that sends `FF F6` (`\xFF\xF6`).
4. Map the commands to Savant services / UI buttons, then deploy to the host and
   test.

**Dynamic dimming:** a fixed command carries a fixed level (the second-to-last
byte of a `dali-level` payload is the arc level 0–254). To drive a slider, use a
Savant request **parameter** substituted into that byte position, or define
stepped commands (0 %, 25 %, 50 %, 75 %, 100 %) — see `dali-level` output for the
exact byte layout.

## Testing

```bash
python -m pytest -q
```

`test_commands.py` asserts the generated payloads byte-for-byte against the shared
reference frames (the same oracle used by every eDIDIO encoder), plus the hex /
escaped formatting.

## Files

```
Savant Driver/
├── generate_commands.py   # CLI: emit command payloads for the Profiler
├── commands.py            # action -> bytes + formatting (reuses edidio_frames)
├── edidio_frames.py       # zero-dependency eDIDIO frame encoder (byte-verified)
└── tests/
```

## Notes

- The payloads use a fixed message id (default `1`, `--mid` to change) since
  profile commands are static; the controller does not require monotonic ids for
  basic control.
- When a real project lands, the command core here plugs straight into the
  profile; only the Blueprint/Profiler packaging + on-host validation remain.

## License

MIT
