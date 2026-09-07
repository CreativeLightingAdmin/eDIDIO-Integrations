#!/usr/bin/env python3
"""eDIDIO MIDI Bridge entry point.

Usage:
    python run.py --list                       # list MIDI input ports
    python run.py [--config config.yaml] [--port "Launchpad"] [--log-level INFO]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from edidio_midi.config import load_config
from edidio_midi.midimap import ConfigError
from edidio_midi.midi_runner import list_ports, run


def main() -> int:
    parser = argparse.ArgumentParser(description="eDIDIO MIDI Bridge")
    parser.add_argument("--config", default="config.yaml", help="path to YAML config (default: config.yaml)")
    parser.add_argument("--port", help="MIDI input port name (substring); overrides config")
    parser.add_argument("--list", action="store_true", help="list MIDI input ports and exit")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    if args.list:
        ports = list_ports()
        if not ports:
            print("No MIDI input ports found.")
        else:
            print("MIDI input ports:")
            for p in ports:
                print(f"  - {p}")
        return 0

    try:
        config = load_config(args.config)
    except ConfigError as err:
        print(f"Configuration error: {err}", file=sys.stderr)
        return 2

    try:
        asyncio.run(run(config, port_override=args.port))
    except KeyboardInterrupt:
        print("\nShutting down.")
    except RuntimeError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
