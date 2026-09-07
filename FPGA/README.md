# eDIDIO FPGA Toolchain Integrations

Control Control Freak **eDIDIO** lighting from FPGA / soft-processor systems —
for machine vision, hardware-in-the-loop (HIL) test rigs, industrial automation
and instrumentation, where lighting needs to react in lockstep with hardware.

> **Target:** FPGA / embedded / industrial.

Three pieces:

| Folder | What | Verified |
|--------|------|----------|
| **`edidio-c/`** | Dependency-free **pure-C** eDIDIO frame encoder for soft processors (MicroBlaze, Nios V, RISC-V) — Xilinx Vitis / Intel Quartus | ✅ gcc host byte-test |
| **`verilog/`** | **Verilog/VHDL IP-core** design that streams pre-built frames from Block RAM on a hardware pin trigger | design + verified frames (HDL needs a board) |
| *(Tcl bridge)* | see the sibling **`../Tcl Bridge/`** — Tcl scripts for Vivado/Quartus consoles to automate lighting during HIL | ✅ tclsh byte-test |

## edidio-c/ — pure-C encoder (9th eDIDIO encoder)

Zero dependencies (just `<stdint.h>`/`<stddef.h>`), no dynamic allocation, no
protobuf runtime — builds eDIDIO frames into a caller `uint8_t` buffer. Drop
`edidio_frames.c/.h` into a Vitis / Quartus soft-CPU project (or any C target),
call a builder on a hardware event, and push the bytes over your TCP stack (lwIP
or BSD sockets — see `example_send.c`).

**Verify the encoder on a host (needs gcc):**

```bash
cd edidio-c/test
gcc -std=c99 -Wall -I.. test_frames.c ../edidio_frames.c -o test_frames && ./test_frames
```

Asserts every frame byte-for-byte against the shared reference frames (the same
oracle used by the Python/JS/Lua/C#/C++ encoders).

### API (`edidio_*`)

```c
uint8_t buf[64];
size_t n = edidio_dali_arc_level(buf, sizeof(buf), msg_id, edidio_line_mask(1), 5, 254);
send(sock, buf, n, 0);
```

`edidio_dali_arc_level`, `edidio_dali_group_arc_level`, `edidio_dali_command`,
`edidio_dali_broadcast_scene`, `edidio_dali_scene_on_group`, `edidio_dmx_level`,
`edidio_spektra_control`, `edidio_spektra_stop`, plus `edidio_line_mask()` and
`edidio_keep_alive`.

## verilog/ — hardware packet streamer

Store pre-formatted eDIDIO frames in Block RAM; an FSM streams the selected frame
to the Ethernet MAC on a pin trigger. See `verilog/README.md` for the core
interface and how to generate the `$readmemh` init data from the C/Tcl encoders.
(The synthesizable HDL needs an FPGA/simulator to verify; the frame bytes it
streams are verified here.)

## Vivado / Quartus Tcl bridge

For automating lighting scenes from inside the FPGA vendor's Tcl console during
HIL testing, see **`../Tcl Bridge/`** — a pure-Tcl encoder + socket helpers,
byte-verified with `tclsh`.

## License

MIT
