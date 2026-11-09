# Spektra AI - compatibility and status

What Spektra AI works with, what each feature needs, what has been verified on real
hardware, and what is still to do.

## Software it depends on

| Component | Version | Why |
|---|---|---|
| Python | 3.10+ | |
| `edidio_control_py` | **0.5.1+** | Protocol 1.3.2 (Wi-Fi, DALI bus power, slot manifest, storage diagnostics) and the full event-stream decoding (list, schedule, config, boot events). 0.5.0 is missing these. |
| `mcp` | 2.0+ | MCP server SDK |
| `protobuf` | 5.29.2+ | Runtime for the engine's generated messages |
| eDIDIO protocol | 1.3.2 | Built into the engine's `_v2` module |
| SpektraPlus file format | v3 (reads older files and migrates them) | `.spektra` projects |
| SpektraPlus sync hash | 1.3.0 | Byte-for-byte parity, pinned by `tests/test_sync_parity.py` |

## Controllers

| Device | Status |
|---|---|
| eDIDIO S10 6-pole, firmware 1.6.3 | Verified live, over TLS (port 443) and plain TCP (port 23) |
| eDIDIO S10, firmware 1.5.7 | Verified live (pull, push, sync, event stream) |
| eDIDIO S10 4-pole / 9-pole | Expected to work (slot counts come from the controller); not tested on hardware |
| ADDICT V3, firmware 3.9.3 | Verified live for what it supports: discovery, health, Wi-Fi status and settings (read and write), DALI status, device status, memory, crash log, connections, DMX timing. It has no configuration, device log, clock, line types or inputs, and the tools say so. |

## Features that depend on firmware

| Feature | Needs | Without it |
|---|---|---|
| Live event stream (v2), `notify_when` and the background recorder | 1.4.0+ | Older than 1.2.0: legacy event registration (fewer event types). 1.2.0-1.3.x: no event stream |
| Fast sequence/theme reads (slot manifest) | 1.6.0+ | Every slot is read (slower, same result) |
| Refused values come back with a reason | 1.6.3 | Older firmware may store a truncated value and report success |
| Device log categories (`preview_logging`) | 1.6.3 | Log reads still work |
| Restart cause and crash records in the device log | 1.6.3 | Boot entries show the start flags only |
| Lists of 255 steps | 1.6.3 | The last block of a 255-step list is refused |
| Controller names up to 31 bytes | 1.6.3 | 15 bytes |
| Sensor cooperative groups (Leader/Follower) | 1.3.0+ | The legacy grouping mask is used |
| Wi-Fi tools | ADDICT V3 | Not available on eDIDIO |
| Storage diagnostics | Firmware built with protocol 1.3.2 | 1.6.3 (protocol 1.3.1) reports "not supported" |
| SD card tools | Models with an SD card | Not available |

## Verified on hardware

- Connecting (TCP and the eDIDIO TLS certificate), discovery, reboot and reconnect.
- `.spektra` pull, push (only the connected controller, only what changed, ends with a
  save) and SpektraPlus-compatible sync for all 12 sections.
- Live authoring: lists (including list 1 rewriting the others), latching and
  momentary inputs, outputs, logic, schedules with any command, sensors, DMX-to-DALI
  translations, burn-ins, zones, names, device/network/clock settings, line types.
- Health check, diagnostics, device log, SD card listing/reading/search, and
  decoding of the binary DALI bus logs (DAL_*.BIN) and event logs (EVT_*.BIN).
- Background event recorder: kept recording after the launching process exited,
  captured DALI frames, sensor events and connections, and stopped on request.
- Live state, `run_command`, profile changes, live colour on DMX and DALI zones,
  per address and by DALI group, and DALI DT8 RGBWAF and xy zones (levels and DT8
  colour values read back from the fittings, frames seen on the bus).
- DALI: commissioning (re-address all, and new gear only), groups, scenes (store,
  remove, read back, recall), gear settings (power-on, system failure, min/max, fade
  time/rate, extended fade - written and read back), fade,
  levels and status, memory bank 0, multi-channel driver re-addressing into channel
  order. DT8: colour features, RGBWAF, colour temperature (incl. clamping to the
  driver's range) and xy (incl. the out-of-range flag), all read back.
- DALI-2: device scan and inspection, re-addressing (24-bit swap), duplicate check,
  instance enable/settings, occupancy and daylight harvesting with a real sensor.
- RDM: discovery, details, identify, start address and label.
- Notifications from live events (list started, config changed).
- Functionality statement from a live controller and from a file (identical).
- Changed-slot detection from the slot manifest checksums; DMX timing and line
  settings writes.

## Not yet verified on hardware

- A network change **with** restart to a new IP or to DHCP (writes without restart
  verified).
- DALI-2 push buttons and other input devices (none available; the configuration
  side is covered by the file push).
- RDM personality change (start address and label verified).
- 4-pole and 9-pole models.

## Behaviour to know (not faults)

- A DT8 driver moves an xy point that is outside its gamut to the nearest colour it
  can make and sets "xy out of range" (colour temperature outside its range is
  clamped the same way). SpektraPlus's xy conversion uses very wide primaries, so
  pure green or blue in a DT8 xy zone is usually out of range on real drivers.
  `dali_dt8_info` shows the flag and the point the driver used.

- On an ADDICT in access point + station mode, the access point runs on the
  station's channel (one radio): a different access-point channel is stored and
  read back, but only used in access-point-only mode.

## Firmware issues found (to report)

- **255 on DALI Spektra zones:** the controller's Spektra engine sends a stored 255
  as the DALI arc level when playing a theme or sequence. 255 is DALI "no change", so
  that channel does not move. Only the "all lights" path clamps it to 254.
  `preview_zone` warns about stored items that use 255.
- **DALI level cache:** in 1.6.3 it is only ever written with 0 (on OFF), so it never
  shows real levels. `dali_levels` queries each fitting instead.
- **SD capacity:** the controller answers SD_OK with 0 of 0 bytes when it has not
  measured the card. The protocol defines SD_CAPACITY_UNKNOWN for that.
  `sd_overview` reports the space as unknown.
- **Event log stops reaching the SD card:** on the bench unit, `logs/LOGMETA.DAT`
  says the controller is writing EVT_1576, but that file was never created. The
  last event file is from weeks earlier, while the category still reports
  "recording". The DALI and text logs are still being written. `sd_read_log` and
  `sd_search` warn when the current file is missing.

## Still to do

- DALI-2 push-button authoring on the controller (a live `preview_dali_input`; today
  DALI inputs are written through a `.spektra` push).
- Live colour for zones that continue across lines.
- Spreadsheet import/export of inputs, schedules, lists and sensors.
- User accounts and roles (login secrets per role).
- Link settings writes (controller-to-controller UDP link: enable, type, mask,
  netmask - readable through `get_device_settings`).
- SD card writes and deletes.

## Out of scope

- Firmware updates.
- Device provisioning and decommissioning (security identity).
- IR codes (deprecated) and user levels (no protocol support).
