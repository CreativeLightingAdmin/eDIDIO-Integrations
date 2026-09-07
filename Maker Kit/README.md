# eDIDIO Maker Kit

DIY / embedded ways to control Control Freak **eDIDIO** lighting — for custom
installations, interactive art, prototypes, education and one-off wall panels.

> **Target:** Makers, installers, educators, prototypers.

Two kits:

| Kit | Platform | Use |
|-----|----------|-----|
| **`arduino/`** | Arduino / ESP32 / ESP8266 (C++) | microcontroller drives lighting from GPIO buttons/sensors, over Wi-Fi/Ethernet |
| **`raspberry-pi/`** | Raspberry Pi (Python) | GPIO buttons/switches/PIR → lighting via `edidio_control_py` |

Both send the **same byte-verified eDIDIO frames** as every other integration.

---

## arduino/ — Arduino / ESP32 / ESP8266

A **zero-dependency C++ encoder** (`EdidioFrames.h` / `.cpp`) that builds eDIDIO
frames into a plain `uint8_t` buffer — no STL, no dynamic allocation, suitable
for microcontrollers. This is the **8th byte-identical eDIDIO encoder**, verified
by compiling and running the real C++ against the shared reference frames.

`EdidioLighting.ino` is an ESP32 example: a button recalls a scene, a PIR sensor
turns a group on, over Wi-Fi/TCP to the controller (port 23) with a keep-alive.

**Install:** copy the `EdidioLighting/` folder into your Arduino `libraries/` (or
open the `.ino`), select your board, set Wi-Fi + controller details, and flash.
For a wired Arduino, swap `WiFiClient` for `EthernetClient`.

**Verify the encoder (host, needs g++):**

```bash
cd arduino/_test
g++ -std=c++11 -I../EdidioLighting test_frames.cpp ../EdidioLighting/EdidioFrames.cpp -o test_frames
./test_frames        # (./test_frames.exe on Windows)
```

Asserts every frame byte-for-byte against the reference hexes.

### API (namespace `edidio`)

Each builder writes into your buffer and returns the length:

```cpp
uint8_t buf[64];
size_t n = edidio::daliArcLevel(buf, sizeof(buf), msgId, edidio::lineMask(1), 5, 254);
client.write(buf, n);
```

`daliArcLevel`, `daliGroupArcLevel`, `daliCommand`, `daliBroadcastScene`,
`daliSceneOnGroup`, `dmxLevel`, `spektraControl`, `spektraStop`, plus
`edidio::lineMask(line)` and `edidio::KEEP_ALIVE`.

---

## raspberry-pi/ — Raspberry Pi GPIO

Map GPIO pins (buttons, switches, PIR sensors) to eDIDIO actions in `config.yaml`.

```bash
cd raspberry-pi
python -m pip install -r requirements.txt
python -m pip install -e ../../../edidio_control_py   # dev: shared engine
cp config.example.yaml config.yaml                    # set controller + pins
python run.py --config config.yaml
```

Each pin binds an action fired on press: `scene` (line, scene), `on`/`off`
(line, address), `group_level` (line, group, level), `spektra` (zone, index).
`pull_up: false` suits an active-high input like a PIR.

> **YAML tip:** quote `action: "on"` — a bare `on` is a YAML boolean (`true`).
> The example does this; the tests guard against it.

**Test (no Pi, no eDIDIO):**

```bash
cd raspberry-pi
python -m pytest -q
```

The pin→intent map and the controller (with a fake client) are pure/injectable,
so all logic is tested off-device. On a Pi, `gpiozero` handles the real pins; you
may also need a pin-factory backend (`RPi.GPIO` / `lgpio`).

---

## License

MIT
