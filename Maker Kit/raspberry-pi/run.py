#!/usr/bin/env python3
"""eDIDIO Raspberry Pi GPIO bridge runner.

Reads config.yaml, sets up a gpiozero Button per pin, and fires the mapped
eDIDIO action on each press. Run on a Raspberry Pi:

    python run.py --config config.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import yaml

from edidio_gpio import ConfigError, Controller, build_pin_map


def load(path):
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


async def run(raw):
    ctrl_cfg = raw.get("controller", {}) or {}
    host = ctrl_cfg.get("host")
    if not host:
        raise ConfigError("controller.host is required")
    controller = Controller(host, int(ctrl_cfg.get("port", 23)), use_tls=bool(ctrl_cfg.get("use_tls", False)))
    pin_map = build_pin_map(raw.get("pins", []) or [])

    await controller.connect()

    # Import gpiozero only here so the module/tests run on non-Pi machines.
    from gpiozero import Button

    loop = asyncio.get_running_loop()
    buttons = []
    for pin, binding in pin_map.items():
        btn = Button(pin, pull_up=binding.pull_up)

        def make_handler(b):
            def handler():
                logging.info("GPIO %s (%s) pressed => %s", b.pin, b.name, b.action)
                asyncio.run_coroutine_threadsafe(controller.execute(b.intent()), loop)
            return handler

        btn.when_pressed = make_handler(binding)
        buttons.append(btn)

    logging.info("GPIO bridge running: %d pins -> eDIDIO %s. Ctrl-C to stop.", len(buttons), host)
    try:
        await asyncio.Event().wait()
    finally:
        await controller.disconnect()


def main() -> int:
    ap = argparse.ArgumentParser(description="eDIDIO Raspberry Pi GPIO bridge")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(message)s")
    try:
        raw = load(args.config)
    except ConfigError as err:
        print(f"Configuration error: {err}", file=sys.stderr)
        return 2
    try:
        asyncio.run(run(raw))
    except KeyboardInterrupt:
        print("\nShutting down.")
    except ConfigError as err:
        print(f"Configuration error: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
