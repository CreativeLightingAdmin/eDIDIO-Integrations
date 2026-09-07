# eDIDIO MIDI Bridge

Control Control Freak **eDIDIO** lighting from **MIDI** — Launchpads, APC grids,
fader banks, keyboards and DAWs. Pads trigger scenes and effects; faders dim
lights. For VJs, theatre operators, musicians and live performers who want
lighting on the same controller as everything else.

> **Target:** Entertainment / live performance.
> **Tech:** Python + `mido` / `python-rtmidi`, wrapping the shared
> `edidio_control_py` engine.

## How it works

```
MIDI controller / DAW  ──notes / CC / PC──▶  MIDI Bridge  ──eDIDIO protobuf/TCP──▶  eDIDIO ──▶ fixtures
                                                  │
                                                  └─ binding map (config.yaml)
```

- **Notes** (pads/keys) trigger scenes, effects, on/off. Velocity can set a level.
- **Control Changes** (faders/knobs) map `0–127` → brightness `0–254`.
- **Program Changes** act as triggers.

## Setup

```bash
cd "MIDI Bridge"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py   # dev: shared engine

python run.py --list                 # see your MIDI input ports
cp config.example.yaml config.yaml   # set controller.host + bindings + port
python run.py --config config.yaml
```

Requires **Python >= 3.9**. On Windows use `py -3`.

## Configuration (`config.yaml`)

### `midi`
| Key | Description |
|-----|-------------|
| `port` | MIDI input name (substring match). Blank = first available, or use `--port`. |

### `controller`
`host` (required), `port` (23/443), `use_tls`.

### `bindings`
Each binding maps an `event` to an action:

- `event`: `note:<ch>:<note>` · `cc:<ch>:<control>` · `pc:<ch>:<program>` (channel 0–15)
- `action`: `dali_level` (line, address), `dali_group_level` (line, group),
  `dali_scene` (line, scene [, group]), `spektra` (zone, index), `spektra_stop` (zone)

Level actions scale the MIDI value (velocity / CC `0–127`) to arc `0–254`.
Trigger actions (scene/Spektra) fire on note-on / value `>0` and ignore
note-off / value `0`, so a pad release doesn't re-fire.

Find your controller's note/CC numbers with `python run.py --list` then watch the
log while you press pads / move faders (each unmapped event is logged at debug).

## Testing

```bash
python -m pytest -q
```

- `test_midimap.py` — value→level scaling, note/CC/PC decoding, trigger-vs-release,
  and config validation.
- `test_bridge.py` — feeds **real `mido.Message` objects** (the same objects a
  live port delivers) through the bridge and asserts the correct intents,
  including a short "performance" sequence — all without a MIDI device or eDIDIO.

**Live MIDI test without hardware:** Windows has no native virtual MIDI, so use
[loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) to create a
virtual port, point `--port` at it, and send notes from any MIDI app. (macOS/Linux
have virtual ports built in.)

## Project layout

```
MIDI Bridge/
├── run.py                     # entry point (--list / --port / --config)
├── config.example.yaml
├── requirements.txt
├── edidio_midi/
│   ├── config.py              # YAML load + validation
│   ├── midimap.py             # event + value -> intent (pure)
│   ├── bridge.py              # mido decode + routing (testable)
│   ├── dispatcher.py          # async worker wrapping edidio_control_py
│   └── midi_runner.py         # mido input wiring
└── tests/
```

## Notes

- Same architecture as the Modbus/MQTT/KNX/OSC gateways (map → dispatcher →
  `edidio_control_py`); the MIDI-specific part is the `mido` input + decode.
- MIDI clock/timing messages are ignored — this is a control mapping, not a
  timecode/beat-sync engine (that could be a future addition).

## License

MIT
