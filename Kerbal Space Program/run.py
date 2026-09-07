#!/usr/bin/env python3
"""eDIDIO Kerbal Space Program bridge.

Polls KSP telemetry via kRPC and drives eDIDIO lighting.

    python run.py [--config config.yaml]

Requires the kRPC mod in KSP + the `krpc` Python package for the LIVE link. The
mapping logic is fully tested without either (see tests/).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import yaml

from edidio_ksp.dispatcher import EdidioDispatcher
from edidio_ksp.mapper import ConfigError, KspMapper


def load(path):
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def read_telemetry(vessel, conn):
    """Sample KSP telemetry from a kRPC vessel into the mapper's dict format."""
    control = vessel.control
    resources = vessel.resources
    try:
        fuel_max = resources.max("LiquidFuel")
        fuel = (resources.amount("LiquidFuel") / fuel_max) if fuel_max else 0.0
    except Exception:  # noqa: BLE001
        fuel = None
    return {
        "throttle": control.throttle,
        "fuel": fuel,
        "stage": control.current_stage,
        "abort": control.abort,
        "situation": str(vessel.situation).split(".")[-1].lower(),
    }


async def run(raw):
    ctrl = raw.get("controller", {}) or {}
    if not ctrl.get("host"):
        raise ConfigError("controller.host is required")
    dispatcher = EdidioDispatcher(ctrl["host"], int(ctrl.get("port", 23)),
                                  use_tls=bool(ctrl.get("use_tls", False)))
    await dispatcher.start()
    mapper = KspMapper(raw.get("ksp", {}) or {})

    import krpc  # lazy: only needed for the live link
    conn = krpc.connect(name="eDIDIO", address=raw.get("krpc", {}).get("host", "127.0.0.1"))
    interval = float(raw.get("krpc", {}).get("interval", 0.5))
    logging.info("Connected to kRPC; driving eDIDIO %s", ctrl["host"])
    try:
        while True:
            vessel = conn.space_center.active_vessel
            for intent in mapper.process(read_telemetry(vessel, conn)):
                dispatcher.submit(intent)
            await asyncio.sleep(interval)
    finally:
        conn.close()
        await dispatcher.stop()


def main() -> int:
    ap = argparse.ArgumentParser(description="eDIDIO KSP bridge")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    try:
        raw = load(args.config)
    except ConfigError as err:
        print(f"Configuration error: {err}", file=sys.stderr)
        return 2
    try:
        asyncio.run(run(raw))
    except KeyboardInterrupt:
        print("\nShutting down.")
    except ImportError:
        print("The 'krpc' package is required for the live link: pip install krpc", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
