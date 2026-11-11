# Changelog

## 0.3.0 - 2026-11-11

### Safety
- **Previews are tied to their connection** and expire after 15 minutes: `confirm`
  refuses a preview made on another controller or an earlier connection.
- **Undo for writes:** `confirm` reads what it is about to overwrite and returns an
  undo token that puts it back exactly (sequences, themes, zones, schedules, sensors,
  inputs, outputs). `undo_last_write` shows the latest. Undo lasts 12 hours.
- **TLS certificates are remembered** per address; a different one is refused until
  accepted with `connect_controller(..., accept_new_certificate=true)`.

### Sequences
- `preview_sequence` sets every property the controller stores: range, background,
  comet tail, reverse or cycle, random colour order, random types, and the time
  units (long step and colour times are sent in s / min / h as needed).
- **Dry run:** add `zone` (or `lights`) to the spec to see the first steps, one
  character per fixture, as the controller will draw them.
- A fade is added to the step (and colour) time, as the controller does; the
  preview says how long each step lasts. The colour time defaults to 2 s.
- The preview notes settings the chosen type does not use, and fade-to-black
  playing as blend.
- `list_sequences` shows the type name, timing, range, direction and random settings.

### Commands, DALI, logs
- `dt8_colour_temp` command (Kelvin; stored as mirek / 4 as the controller expects),
  with the Kelvin shown in descriptions and a Kelvin-looking value flagged by
  `validate_spektra`.
- DALI commissioning waits up to 90 s for each addressing step, so a run is never
  left half done; `set_zone_colour` accepts colour names (`warm white`,
  `red+white`, ...).
- SD binary DALI and event logs are decoded; a background event recorder keeps
  recording when no chat is open.
- Tool groups load on demand (`SPEKTRA_AI_TOOLS=dynamic`): a chat starts with about
  2,800 tokens of tool descriptions instead of 18,000.

### Fixes
- Sequence time units read back as stored: a pull and push no longer turns
  milliseconds into seconds (or hours into seconds).
- Slots marked `!DELETED!` by SpektraPlus read as empty, as in SpektraPlus.
- Matching SpektraPlus exactly (checked by a parity test against its own mappers):
  an unset trigger reads as no command, and a DALI line mask that is not a single
  line reads as line 1.

### Tools and tests
- `tools/sequence_bench.py`: checks every sequence type against a controller's DMX
  output. `tools/bench_test.py`: end-to-end check of the tools.
- Parity test against SpektraPlus's mappers; tests for DALI-2, RDM and discovery.
- The live tools are split by topic into `edidio_spektra_ai/live/`.
- Lint (ruff) runs in CI. The server reports its version to MCP clients.

## 0.2.0 - 2026-11-09
- Catch-up to SpektraPlus 1.3.0 and firmware 1.6.3: sync-hash parity for all 12
  sections, protocol 1.3.2, 78 tools, compatibility map and public-repo packaging.
