#!/usr/bin/env python3
"""eDIDIO Generative AI Moods.

Turn a text prompt into a lighting scene via an LLM.

    python run.py "cosy autumn evening"
    python run.py --provider anthropic "cyberpunk neon city"
    python run.py --dry-run "calm ocean"        # print the palette, don't send

Config (controller + output lines) comes from config.yaml.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import yaml

from edidio_genai.dispatcher import EdidioDispatcher
from edidio_genai.mood import mood_to_intents
from edidio_genai.palette import PaletteError
from edidio_genai.provider import get_provider


def load_config(path):
    p = Path(path)
    raw = {}
    if p.exists():
        with p.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    return raw


async def send(controller, intents):
    dispatcher = EdidioDispatcher(
        controller["host"], int(controller.get("port", 23)),
        use_tls=bool(controller.get("use_tls", False)))
    await dispatcher.start()
    for intent in intents:
        dispatcher.submit(intent)
    # give the worker a moment to flush, then stop
    await asyncio.sleep(0.5)
    await dispatcher.stop()


def main() -> int:
    ap = argparse.ArgumentParser(description="eDIDIO Generative AI Moods")
    ap.add_argument("description", help="the mood / scene, e.g. 'cosy autumn evening'")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--provider", help="override provider (demo | anthropic)")
    ap.add_argument("--dry-run", action="store_true", help="print the palette; don't send")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    raw = load_config(args.config)
    lines = raw.get("lines") or [2]
    provider_name = args.provider or raw.get("provider", "demo")

    try:
        provider = get_provider(provider_name)
        palette, intents = mood_to_intents(args.description, provider, lines)
    except (PaletteError, ValueError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    except Exception as err:  # noqa: BLE001 - e.g. missing anthropic / API key
        print(f"Provider error: {err}", file=sys.stderr)
        return 1

    print(f"Palette for '{args.description}': {', '.join(palette)}")
    for i in intents:
        print(f"  line {i['line']} -> rgb {i['rgb']}")

    if args.dry_run:
        return 0
    controller = raw.get("controller")
    if not controller or not controller.get("host"):
        print("No controller.host in config; use --dry-run or set config.yaml.", file=sys.stderr)
        return 2
    asyncio.run(send(controller, intents))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
