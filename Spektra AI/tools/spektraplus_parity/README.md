# SpektraPlus mapper parity

`tests/test_spektraplus_parity.py` checks that Spektra AI's protobuf -> `.spektra`
mappers (`spektra_map.py`) give what SpektraPlus's own mappers give for the same
protobuf bytes. Its fixture, `tests/fixtures/parity_expected.json`, is produced by
running SpektraPlus's code.

Regenerate it when SpektraPlus changes a mapper (or the protocol changes):

1. `python tools/spektraplus_parity/make_cases.py` writes
   `tests/fixtures/parity_cases.json` (serialised protobuf cases).
2. Run SpektraPlus's mappers on those cases with the small export test kept with the
   SpektraPlus code (not in this repository); it writes `parity_expected.json`.
3. Run the test. A difference is either a Spektra AI bug (fix `spektra_map.py`) or a
   deliberate, explained difference (add it to `ALLOWED` in the test, with the reason).

Each message type gets three cases: every field at its default (`empty`, where a
TypeScript `?? x` ported as Python `or x` goes wrong), every field set (`filled`), and
high values (`max`). Lists are not covered: both apps map them from steps read
separately.
