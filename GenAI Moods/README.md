# eDIDIO Generative AI Moods

Describe a mood — *"cosy autumn evening"*, *"cyberpunk neon city"*, *"calm
ocean"* — and an LLM turns it into a colour palette that's pushed to Control Freak
**eDIDIO** lighting. Natural-language scene design.

> **Target:** AI / experiential / demos.
> **Tech:** Python; a pluggable LLM provider (Claude, or an offline demo),
> wrapping `edidio_control_py`. Sibling to the **MCP Server** (that lets an AI
> *drive* eDIDIO; this uses an AI to *design a scene*).

## How it works

```
"cosy autumn evening"  →  LLM  →  {"palette": ["#8C3B0F", ...]}  →  DMX colours  →  eDIDIO
```

The LLM is asked for **strict JSON** (a palette of hex colours); the parser is
robust to code fences / stray prose, and falls back to scraping hex codes. The
palette is then distributed across your configured DMX lines.

## Quick start

Works out of the box with the **demo provider** (offline keyword palettes — no
API key):

```bash
cd "GenAI Moods"
python -m pip install -r requirements.txt
python -m pip install -e ../../edidio_control_py
cp config.example.yaml config.yaml            # set controller.host + lines

python run.py --dry-run "a cosy autumn evening"     # print the palette
python run.py "cyberpunk neon city"                 # send it to the controller
```

## Using Claude

Set the provider and an API key for real, open-ended prompts:

```bash
python -m pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...      # ($env:ANTHROPIC_API_KEY on Windows)
python run.py --provider anthropic "the calm before a thunderstorm at dusk"
```

(Set `provider: anthropic` in `config.yaml` to make it the default; optional
`EDIDIO_GENAI_MODEL` to pick a model.)

## Config (`config.yaml`)

| Key | Description |
|-----|-------------|
| `provider` | `demo` (offline) or `anthropic` |
| `lines` | DMX line(s) to paint; palette cycles/truncates to fit |
| `controller` | `host`, `port`, `use_tls` |

## Testing

```bash
python -m pytest -q
```

`test_palette.py` covers palette **parsing** (clean JSON, fenced JSON, bare
arrays, hex-scraped-from-prose, error cases), palette → intent **mapping** (single
and multi-line cycling), and the end-to-end **mood → intents** flow using the
demo provider and an **injected fake provider** — so everything is verified with
no API key, no network and no controller.

## Files

```
GenAI Moods/
├── run.py                 # CLI: prompt -> LLM -> palette -> dispatch
├── config.example.yaml
├── edidio_genai/
│   ├── palette.py         # prompt, parse, map (pure, tested)
│   ├── provider.py        # demo + anthropic providers (injectable)
│   ├── mood.py            # orchestration
│   └── dispatcher.py      # async worker (with dmx_color) wrapping edidio_control_py
└── tests/
```

## Notes

- The **demo provider** is deterministic keyword→palette — handy for offline demos
  and tests. The **Claude provider** handles arbitrary prompts.
- Image prompts (a photo → palette) are a natural extension: send the image to a
  multimodal model in `anthropic_provider` and parse the same JSON palette.
- Ties into the MCP server nicely: an assistant could call a "set mood" tool that
  runs this.

## License

MIT
