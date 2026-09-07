# eDIDIO Unity Package

Control Control Freak **eDIDIO** lighting from **Unity** — drive real
architectural/entertainment lighting from games, VR/AR experiences, interactive
installations, museums, theme-park attractions and **virtual production**.

> **Target:** Game engines / immersive / virtual production.
> **Tech:** Pure C# (`System.Net.Sockets`), zero dependencies. The frame encoder
> is byte-verified against every other eDIDIO integration.

## What's here

- **`Runtime/EdidioFrames.cs`** — a zero-dependency C# eDIDIO frame encoder,
  verified **byte-for-byte** against the reference implementation
  (`edidio_control_py`) via a real `dotnet test` project. This is the 7th
  byte-identical eDIDIO encoder — also reusable in Crestron SIMPL#, plain .NET,
  and any C# host.
- **`Runtime/EdidioController.cs`** — a TCP client with keep-alive + a clean
  control API (`SetLevel`, `RecallScene`, `DmxColor`, `Spektra`…).
- **`Samples~/BasicControl`** — a `MonoBehaviour` example.

## Install (Unity Package Manager)

**Option A — from a Git URL:** Window → Package Manager → **+** → *Add package
from git URL* →
`https://github.com/CreativeLightingAdmin/eDIDIO-Integrations.git?path=/Unity Package`

**Option B — local:** Package Manager → **+** → *Add package from disk* → select
this folder's `package.json`.

Then import the **Basic Control** sample from the package page.

## Usage

```csharp
using Edidio;

var lights = new EdidioController("192.168.1.50");   // port 23 default
lights.Connect();

lights.SetLevel(1, 5, 254);        // line 1, DALI address 5 -> full
lights.SetGroupLevel(1, 0, 128);   // line 1, group 0 -> 50%
lights.RecallScene(1, 3);          // recall scene 3
lights.DmxColor(2, 255, 0, 0);     // line 2 -> red
lights.Spektra(1, 0);              // zone 1, start sequence 0

lights.Disconnect();
```

Call these from any game event — collisions, timelines, UI, scoring, beat
detection, network events. See `Samples~/BasicControl/EdidioLightController.cs`.

> The controller uses blocking sockets on the calling thread. For heavy use, call
> from a background thread or wrap sends in a task; frames are tiny so occasional
> calls from `Update()` are fine.

## Control API

| Method | Description |
|--------|-------------|
| `Connect()` / `Disconnect()` | open/close; connect starts keep-alive |
| `SetLevel(line, address, level)` | DALI address 0–63 → 0–254 |
| `SetGroupLevel(line, group, level)` | DALI group 0–15 → 0–254 |
| `On/Off(line, address)` | max / off |
| `RecallScene(line, scene)` / `RecallSceneOnGroup(line, group, scene)` | recall a scene |
| `DmxColor(line, r, g, b, fixtures=170)` | RGB across a DMX line |
| `Spektra(zone, index, action)` / `SpektraStop(zone)` | SpektraPlus |

**Line** is the physical daughter-board slot (1–4).

## Testing the encoder

The encoder ships to Unity as source, so it's verified by compiling and running
the **actual C#** outside Unity:

```bash
cd "Unity Package/_test"
dotnet test
```

`FramesTests.cs` asserts every frame byte-for-byte against the shared reference
hexes. (Requires the .NET SDK; not needed to *use* the package in Unity.)

## Files

```
Unity Package/
├── package.json                 # UPM manifest
├── Runtime/
│   ├── EdidioFrames.cs          # zero-dependency byte-verified encoder
│   ├── EdidioController.cs      # TCP + keep-alive + control API
│   └── Edidio.Runtime.asmdef
├── Samples~/BasicControl/       # MonoBehaviour example
└── _test/                       # dotnet test project (byte-equality)
```

## License

MIT
