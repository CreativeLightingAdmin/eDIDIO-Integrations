#!/usr/bin/env python3
"""eDIDIO MQTT Bridge entry point.

Usage:
    python run.py [--config config.yaml] [--log-level INFO]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from edidio_mqtt.config import load_config
from edidio_mqtt.entities import ConfigError
from edidio_mqtt.mqtt_runner import run


def main() -> int:
    parser = argparse.ArgumentParser(description="eDIDIO MQTT Bridge")
    parser.add_argument("--config", default="config.yaml", help="path to YAML config (default: config.yaml)")
    parser.add_argument("--log-level", default="INFO", help="logging level (default: INFO)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

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
