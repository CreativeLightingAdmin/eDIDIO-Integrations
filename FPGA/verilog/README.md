# eDIDIO Verilog/VHDL IP Core (concept + pre-built frames)

A hardware **packet streamer**: store pre-formatted eDIDIO TCP frames in Block
RAM and push them out via the Ethernet MAC when a **hardware pin** triggers (e.g.
a machine-vision exposure signal, a sensor edge, a HIL event) — lighting that
reacts in true hardware time, no soft-processor in the path.

> **Status:** design + a frame-generator (below). The synthesizable HDL itself
> needs an FPGA/simulator to verify, so it's provided as a documented core to
> implement against your MAC/board; the **frame bytes it streams are
> byte-verified** here.

## How it works

```
 pin trigger ──▶ FSM ──▶ read frame bytes from Block RAM ──▶ Ethernet MAC (TCP) ──▶ eDIDIO
```

1. **Pre-compute the frames** you need (scene recall, blackout, a colour) as raw
   bytes — using any eDIDIO encoder in this repo. The pure-C encoder
   (`../edidio-c/`) or the Tcl encoder (`../../Tcl Bridge/`) are handy for
   generating a `$readmemh` init file.
2. **Initialise Block RAM** with those bytes (one frame per region).
3. On a pin edge, an FSM streams the selected frame's bytes to your MAC's TX
   path (with the TCP/IP framing your MAC/stack provides — a hard TCP offload, or
   a pre-established connection whose payload you inject).

## Generating the Block-RAM init (`$readmemh`)

Any encoder gives you the exact bytes. Example with the Tcl encoder:

```tcl
source "../../Tcl Bridge/edidio_frames.tcl"
set frame [edidio::dali_broadcast_scene 1 [edidio::line_mask 1] 3]
binary scan $frame H* hex
# split hex into byte-per-line for a .mem file:
foreach {a b} [split $hex ""] { puts "$a$b" }
```

or the C encoder — call `edidio_dali_broadcast_scene(...)` and print the buffer as
hex. The reference frame for "recall scene 3 on line 1" (message id 1) is:

```
CD 00 0B 08 01 92 01 06 08 01 30 03 48 03
```

(These are the raw eDIDIO application-layer bytes; your MAC/stack adds the
Ethernet/IP/TCP headers, or you inject them as the TCP payload of a pre-opened
connection.)

## Design notes / core interface (to implement)

A minimal core (`edidio_streamer`) would expose:

| Port | Dir | Purpose |
|------|-----|---------|
| `clk`, `rst` | in | clock / reset |
| `trigger` | in | pin edge that fires a send |
| `frame_sel[N]` | in | which stored frame to stream |
| `tx_data[7:0]` | out | byte stream to the MAC TX |
| `tx_valid` | out | byte valid |
| `tx_last` | out | end-of-frame |
| `busy` | out | streaming in progress |

- Frame lengths are stored alongside the bytes (or derived from the 0xCD length
  header at offset 1–2), so the FSM knows when to assert `tx_last`.
- Debounce `trigger`; ignore new triggers while `busy`.
- The 2-byte length header is big-endian; the payload follows verbatim.

## Why this repo can't fully test it

Synthesizable HDL needs an FPGA toolchain + board (or a simulator like Verilator/
ModelSim) to verify end-to-end. What **is** verified here is the hard part —
the exact eDIDIO frame bytes the core must stream — via the C and Tcl encoders'
byte-equality tests. Build the FSM against your MAC and load the verified frames.

## See also
- `../edidio-c/` — pure-C encoder (generate init data, or run on a soft CPU).
- `../../Tcl Bridge/` — Tcl encoder (generate `$readmemh` init files).
