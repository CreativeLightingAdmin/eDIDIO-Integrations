#!/usr/bin/env python3
"""eDIDIO Ambient Data engine entry point.

Usage:
    python run.py [--config config.yaml] [--log-level INFO]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from edidio_ambient.config import load_config
from edidio_ambient.dispatcher import EdidioDispatcher
from edidio_ambient.engine import Engine
from edidio_ambient.mappings import ConfigError


async def run(config):
    ctrl = config.controller
    dispatcher = EdidioDispatcher(ctrl.host, ctrl.port, use_tls=ctrl.use_tls, timeout=ctrl.timeout)
    await dispatcher.start()

    engine = Engine(config.mapping, dispatcher, min_interval=config.min_interval)
    logging.info("Ambient engine: source '%s' -> %s -> eDIDIO %s",
                 config.source.name, type(config.mapping).__name__, ctrl.host)
    try:
        await config.source.run(engine.on_value)
    finally:
        await dispatcher.stop()


def main() -> int:
    ap = argparse.ArgumentParser(description="eDIDIO Ambient Data engine")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    try:
        config = load_config(args.config)
    except ConfigError as err:
        print(f"Configuration error: {err}", file=sys.stderr)
        return 2
    try:
        asyncio.run(run(config))
    except KeyboardInterrupt:
        print("\nShutting down.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
