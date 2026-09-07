#!/usr/bin/env python3
"""eDIDIO Dota 2 GSI bridge.  python run.py [--config config.yaml]"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from edidio_dota2.config import load_config
from edidio_dota2.mapper import ConfigError
from edidio_dota2.server import run


def main() -> int:
    ap = argparse.ArgumentParser(description="eDIDIO Dota 2 GSI bridge")
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
