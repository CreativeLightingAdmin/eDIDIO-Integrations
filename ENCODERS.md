# eDIDIO Frame Encoders

The eDIDIO wire protocol is Protocol Buffers over TCP, framed as
`0xCD` + a 2-byte big-endian length + a serialized `EdidioMessage`. Because
different integrations run in very different environments — full Python, browser
JS, embedded C, an FPGA soft-CPU, a Vivado Tcl console, a Crestron/Unity C#
runtime — this repo ships the **same encoder implemented ten ways**, each
hand-verified to produce **byte-identical** output.

The guarantee: **a command that works in one integration produces exactly the
same bytes in every other.** So a bug can only live in an integration's transport
or glue, never in the frame content — which is why the live hardware steps are so
low-risk.

## The ten encoders

| # | Language | Where | Used by | Verified |
|---|----------|-------|---------|----------|
| 1 | Python (protobuf) | `../edidio_control_py` (`EdidioClient.create_*`) | the Python library + every Python gateway/bridge | pytest round-trip (`tests/test_messages.py`, `test_authoring.py`) — build → serialize → parse |
| 2 | Pure Python | `Extron Driver/edidio_frames.py` | Extron, AMX Muse | pytest vs the 10 reference frames **and** the live library |
| 3 | NetLinx | `AMX Driver/netlinx/eDIDIO.axi` | AMX NetLinx masters | a Python mirror (`_netlinx_mirror.py`) of the exact byte math, tested vs the references |
| 4 | Pure JavaScript | `RTI Driver/src/edidio_frames.js` | RTI, and vendored into REST/Node-RED/Companion/Stream Deck/Twitch/Telegram/OBS | `node --test` vs the references |
| 5 | Pure Lua | `ELAN Driver/edidio_frames.lua` | ELAN g!, SmartThings Edge | executed in **real Lua** via `lupa` and asserted vs the references |
| 6 | Savant generator | `Savant Driver/commands.py` | Savant profiles (emits paste-ready byte payloads) | pytest vs the references |
| 7 | C# | `Unity Package/Runtime/EdidioFrames.cs` | Unity; reusable for Crestron SIMPL#/AMX/RTI-C# | `dotnet test` (xUnit) vs the references |
| 8 | C++ | `Maker Kit/arduino/EdidioLighting/EdidioFrames.{h,cpp}` | Arduino / ESP32 / ESP8266 | host `g++` build vs the references |
| 9 | C | `FPGA/edidio-c/edidio_frames.{h,c}` | MicroBlaze / Nios V / RISC-V soft-CPUs (Vitis/Quartus) | host `gcc` build vs the references |
| 10 | Tcl | `Tcl Bridge/edidio_frames.tcl` | Vivado / Quartus Tcl consoles | `tclsh` vs the references |

> The JS integrations that need the *full* protocol (not just the lighting
> subset) — the REST Gateway, Node-RED nodes, Discord bot — use the
> **generated `google-protobuf` `eDS10_ProtocolBuffer_pb.js`** rather than a
> hand-rolled encoder. That's the compiler's output from the same `.proto`, so it
> is authoritative by construction; encoders 4–10 are the hand-rolled subset for
> constrained runtimes.

## The reference frames (the oracle)

Every hand-rolled encoder is asserted against these exact hex frames, captured
from `edidio_control_py` (encoder #1) with **message_id = 7**.

> **DALI group / broadcast / scene encoding (hardware-verified).** DALI targets are
> selected through the `address` field: **0–63 individual, 64–79 group
> (address = 64 + group), 80 broadcast**; a scene is recalled with the standard DALI
> **GO TO SCENE X** command (`0x10 + scene`) sent to the target address. The
> `group`, `bscene`, and `gscene` reference frames below use these encodings.

| Name | Command | Hex |
|------|---------|-----|
| `arc` | DALI arc level, line 1, addr 5, level 200 | `cd000e080792010908011005300048c801` |
| `group` | DALI group arc level, line 1, group 3, level 128 (arc @ addr 64+group=67) | `cd000e0807920109080110433000488001` |
| `cmd` | DALI command MAX_LEVEL, line 2, addr 10 | `cd000d08079201080802100a28054800` |
| `cmd_off` | DALI command OFF, line 1, addr 0 | `cd000b0807920106080128004800` |
| `bscene` | DALI broadcast scene 3, line 1 (GO TO SCENE 3 @ broadcast addr 80) | `cd000b0807920106080110502813` |
| `gscene` | DALI scene 3 on group 4, line 1 (GO TO SCENE 3 @ addr 64+group=68) | `cd000b0807920106080110442813` |
| `dmx` | DMX zone 255, universe 2, ch 1, ×10, RGB red | `cd00140807a2010f08ff0110021801200a2a04ff010000` |
| `dmx_fade` | DMX ch 1, levels 10/20/30, fade 500 ms | `cd00120807a2010d1001180120012a030a141e3032` |
| `spektra` | Spektra sequence 2 start, zone 1 | `cd000b0807da0106080110011802` |
| `spektra_stop` | Spektra stop external trigger, zone 1 | `cd000e0807aa01090a07080d100118ff01` |

## Verifying them all

The repo-wide runner compiles/runs every encoder's test:

```powershell
pwsh ./run-all-tests.ps1        # Windows (handles py -3 + the msys2 toolchain)
```
```bash
./run-all-tests.sh              # macOS/Linux
```

Each encoder folder can also be tested on its own — see its README (e.g.
`cd "FPGA/edidio-c/test" && gcc -std=c99 -I.. test_frames.c ../edidio_frames.c -o t && ./t`).

## Adding an 11th

To port the encoder to a new language: implement the protobuf varint + the tiny
set of message builders, then assert against the reference frames above before
anything else. That "reference-frames-first" rule is what keeps all ten in
lockstep.
