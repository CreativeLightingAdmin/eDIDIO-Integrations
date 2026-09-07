# eDIDIO Tcl Bridge

A pure-**Tcl** eDIDIO frame encoder + socket helpers — for **Vivado** and
**Quartus** Tcl consoles (and any `tclsh`). Automate lighting scenes directly from
your FPGA vendor's scripting console, e.g. to set the rig lighting during
hardware-in-the-loop (HIL) test steps.

> **Target:** FPGA / test automation.
> **Tech:** Zero-dependency Tcl. The **10th** byte-verified eDIDIO encoder.

## Use

```tcl
source edidio_frames.tcl

set sock [edidio::connect 192.168.1.50]                        ;# port 23
edidio::send $sock [edidio::dali_arc_level 1 [edidio::line_mask 1] 5 254]
edidio::send $sock [edidio::dali_broadcast_scene 2 [edidio::line_mask 1] 3]
edidio::send $sock [edidio::dmx_level 3 255 [edidio::line_mask 2] 1 170 {255 0 0}]
close $sock
```

Inside **Vivado/Quartus**, `source` the file in the Tcl console and call the
builders between test steps — e.g. set a "test running" scene before a HIL run and
a "pass/fail" colour after.

## Builders

`edidio::dali_arc_level`, `dali_group_arc_level`, `dali_command`,
`dali_broadcast_scene`, `dali_scene_on_group`, `dmx_level`, `spektra_control`,
`spektra_stop`, plus `edidio::line_mask`, `edidio::keep_alive`, and the
`edidio::connect` / `edidio::send` socket helpers.

## Testing

```bash
tclsh test/test_frames.tcl
```

Asserts every frame byte-for-byte against the shared reference frames (the same
oracle used by every eDIDIO encoder) — no controller needed. Live: `source` the
script, connect to a controller, and send.

## Generating Block-RAM init data for the Verilog core

The encoder is also handy for producing `$readmemh` init files for the FPGA
packet-streamer IP core — see `../FPGA/verilog/README.md`.

## License

MIT
