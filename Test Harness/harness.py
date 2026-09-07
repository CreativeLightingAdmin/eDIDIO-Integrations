#!/usr/bin/env python3
"""eDIDIO integration test harness.

One tool to validate the whole stack against a real controller:

  * library  - talk to the controller directly via edidio_control_py
  * modbus   - drive the Modbus gateway (writes holding registers)
  * rest     - drive the REST gateway (HTTP)
  * discover - find controllers on the LAN
  * all      - a connectivity sweep across the above

SAFE BY DEFAULT: every command only connects / reads unless you pass --actuate,
which is what actually changes lighting. Actuation always requires an explicit
target (address / group / scene) so nothing is guessed.

Examples
--------
  python harness.py discover
  python harness.py library --host 192.168.1.50
  python harness.py library --host 192.168.1.50 --actuate --line 1 --address 5 --blink
  python harness.py library --discover --actuate --line 1 --scene 3
  python harness.py rest --url http://localhost:8080 --api-key KEY --actuate --controller 192.168.1.50 --line 1 --group 0 --level 200
  python harness.py modbus --host 127.0.0.1 --port 5020 --actuate --register 1 --value 200
  python harness.py all --host 192.168.1.50
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

import discovery

GREEN, RED, YELL, DIM, RST = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}  [ok]{RST} {msg}")


def warn(msg: str) -> None:
    print(f"{YELL}  [!!]{RST} {msg}")


def fail(msg: str) -> None:
    print(f"{RED}  [FAIL]{RST} {msg}")


def head(msg: str) -> None:
    print(f"\n=== {msg} ===")


# --------------------------------------------------------------------------
# Target resolution (shared by the library and REST executors)
# --------------------------------------------------------------------------

def resolve_target(args) -> dict:
    """Turn --line/--address/--group/--scene/--level into a logical action.

    Precedence: scene > address > group. Raises SystemExit on an incomplete
    target so we never actuate ambiguously.
    """
    if args.scene is not None:
        if args.line is None:
            raise SystemExit("actuate scene: --line is required")
        t = {"kind": "scene", "line": args.line, "scene": args.scene}
        if args.group is not None:
            t["group"] = args.group
        return t
    if args.address is not None:
        if args.line is None:
            raise SystemExit("actuate address: --line is required")
        return {"kind": "address", "line": args.line, "address": args.address, "level": args.level}
    if args.group is not None:
        if args.line is None:
            raise SystemExit("actuate group: --line is required")
        return {"kind": "group", "line": args.line, "group": args.group, "level": args.level}
    raise SystemExit("actuate: specify a target (--scene, --address, or --group)")


def _mask(line: int) -> int:
    return 1 << (line - 1)


# --------------------------------------------------------------------------
# discover
# --------------------------------------------------------------------------

def cmd_discover(args) -> int:
    head("Discovery (UDP broadcast, port 30303)")
    devices = discovery.discover(timeout=args.timeout)
    if not devices:
        warn("No controllers replied. Check the device is powered and on this subnet.")
        return 1
    for d in devices:
        ok(f"{d.get('NAME', '?')}  IP={d.get('IP')}  MAC={d.get('MAC')}  "
           f"TLS={d.get('TLS')}  FW={d.get('FW_VER')}  "
           f"[{discovery.summarize_lines(d.get('LINES'))}]")
    return 0


def _pick_device(args):
    """Return (host, use_tls) resolving --discover / --host / --tls."""
    if getattr(args, "discover", False):
        head("Discovery")
        devices = discovery.discover(timeout=args.timeout)
        if not devices:
            fail("No controllers found to auto-select.")
            return None, None
        dev = devices[0]
        host = dev["IP"]
        use_tls = bool(dev.get("TLS"))
        ok(f"Selected {dev.get('NAME', host)} @ {host} (TLS={use_tls})")
        return host, use_tls
    if not args.host:
        fail("No --host given (and --discover not set).")
        return None, None
    return args.host, args.tls


# --------------------------------------------------------------------------
# library (direct edidio_control_py)
# --------------------------------------------------------------------------

async def _library(args) -> int:
    try:
        from edidio_control_py import EdidioClient
        from edidio_control_py.exceptions import EDIDIOConnectionError
    except ImportError:
        fail("edidio_control_py is not installed. Run: pip install -e ../../edidio_control_py")
        return 1

    host, use_tls = _pick_device(args)
    if host is None:
        return 1

    port = args.port or (443 if use_tls else 23)
    head(f"Library: connect {host}:{port} (TLS={use_tls})")
    client = EdidioClient(host, port, use_tls=use_tls, timeout=args.conn_timeout)
    try:
        await client.connect()
    except EDIDIOConnectionError as err:
        fail(f"Connect failed: {err}")
        return 1
    if not client.connected:
        fail("Connect reported not connected.")
        return 1
    ok("Connected (keep-alive running).")

    rc = 0
    if args.actuate:
        target = resolve_target(args)
        try:
            await _library_actuate(client, target, args)
        except Exception as err:  # noqa: BLE001
            fail(f"Actuation error: {err}")
            rc = 1
    else:
        warn("Read-only run (no --actuate); nothing changed.")

    await client.disconnect()
    ok("Disconnected.")
    return rc


async def _library_actuate(client, target, args) -> None:
    mid = 1
    if target["kind"] == "scene":
        if "group" in target:
            await client.recall_dali_scene_on_group(mid, _mask(target["line"]), target["group"], target["scene"])
            ok(f"Recalled scene {target['scene']} on group {target['group']} (line {target['line']}).")
        else:
            await client.recall_dali_scene(mid, _mask(target["line"]), target["scene"])
            ok(f"Recalled scene {target['scene']} across line {target['line']}.")
        return

    if target["kind"] == "address":
        await client.set_dali_arc_level(mid, _mask(target["line"]), target["address"], target["level"])
        ok(f"Set address {target['address']} (line {target['line']}) -> level {target['level']}.")
        if args.blink:
            time.sleep(args.hold)
            await client.set_dali_arc_level(mid + 1, _mask(target["line"]), target["address"], 0)
            ok(f"Blink: address {target['address']} -> off.")
        return

    if target["kind"] == "group":
        await client.set_dali_group_arc_level(mid, _mask(target["line"]), target["group"], target["level"])
        ok(f"Set group {target['group']} (line {target['line']}) -> level {target['level']}.")
        if args.blink:
            time.sleep(args.hold)
            await client.set_dali_group_arc_level(mid + 1, _mask(target["line"]), target["group"], 0)
            ok(f"Blink: group {target['group']} -> off.")


def cmd_library(args) -> int:
    return asyncio.run(_library(args))


# --------------------------------------------------------------------------
# modbus (drive the Modbus gateway)
# --------------------------------------------------------------------------

async def _modbus(args) -> int:
    try:
        from pymodbus.client import AsyncModbusTcpClient
    except ImportError:
        fail("pymodbus not installed. Run: pip install -r requirements.txt")
        return 1

    head(f"Modbus gateway: connect {args.host}:{args.port} (unit {args.unit})")
    client = AsyncModbusTcpClient(args.host, port=args.port)
    await client.connect()
    if not client.connected:
        fail(f"Could not connect to Modbus gateway at {args.host}:{args.port}. Is it running?")
        return 1
    ok("Connected to gateway.")

    rc = 0
    read_reg = args.register if args.register is not None else 1
    try:
        rr = await client.read_holding_registers(read_reg - 1, count=1, slave=args.unit)
        if rr.isError():
            warn(f"Read register {read_reg} returned: {rr}")
        else:
            ok(f"Read holding register {read_reg} = {rr.registers[0]}")
    except Exception as err:  # noqa: BLE001
        warn(f"Read failed: {err}")

    if args.actuate:
        if args.register is None or args.value is None:
            client.close()
            raise SystemExit("modbus --actuate requires --register and --value")
        head(f"Write holding register {args.register} <- {args.value}")
        wr = await client.write_register(args.register - 1, args.value, slave=args.unit)
        if wr.isError():
            fail(f"Write failed: {wr}")
            rc = 1
        else:
            ok("Write accepted. Watch the gateway log for the converted command "
               "and the fixture for the response.")
    else:
        warn("Read-only run (no --actuate); no register written.")

    client.close()
    return rc


def cmd_modbus(args) -> int:
    return asyncio.run(_modbus(args))


# --------------------------------------------------------------------------
# rest (drive the REST gateway)
# --------------------------------------------------------------------------

def cmd_rest(args) -> int:
    try:
        import requests
    except ImportError:
        fail("requests not installed. Run: pip install -r requirements.txt")
        return 1

    base = args.url.rstrip("/")
    headers = {}
    if args.api_key:
        headers["X-API-Key"] = args.api_key

    head(f"REST gateway: {base}")
    try:
        r = requests.get(f"{base}/health", timeout=5)
        if r.ok and r.json().get("ok"):
            ok(f"Health OK ({len(r.json().get('controllers', []))} pooled controller(s)).")
        else:
            fail(f"Health check returned {r.status_code}: {r.text[:200]}")
            return 1
    except requests.RequestException as err:
        fail(f"Cannot reach gateway: {err}. Is it running?")
        return 1

    try:
        r = requests.get(f"{base}/api/v1/discover", headers=headers, timeout=5)
        if r.status_code == 401:
            warn("Discovery unauthorized — pass --api-key.")
        elif r.ok:
            ok(f"Discovery via gateway found {r.json().get('count', 0)} controller(s).")
    except requests.RequestException as err:
        warn(f"Discovery call failed: {err}")

    if not args.actuate:
        warn("Read-only run (no --actuate); nothing changed.")
        return 0

    target = resolve_target(args)
    endpoint, payload = _rest_payload(target, args)
    head(f"POST {endpoint}")
    try:
        r = requests.post(f"{base}{endpoint}", json=payload, headers=headers, timeout=8)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.ok and body.get("ok"):
            ok(f"{endpoint} -> 200. Fixture should respond. Response: {body}")
            return 0
        fail(f"{endpoint} -> {r.status_code}: {body or r.text[:200]}")
        return 1
    except requests.RequestException as err:
        fail(f"Request failed: {err}")
        return 1


def _rest_payload(target, args):
    common = {}
    if args.controller:
        common["controller"] = args.controller
    if target["kind"] == "scene":
        p = {**common, "line": target["line"], "scene": target["scene"]}
        if "group" in target:
            p["group"] = target["group"]
        return "/api/v1/dali/scene", p
    if target["kind"] == "address":
        return "/api/v1/dali/level", {**common, "line": target["line"], "address": target["address"], "level": target["level"]}
    # group
    return "/api/v1/dali/group/level", {**common, "line": target["line"], "group": target["group"], "level": target["level"]}


# --------------------------------------------------------------------------
# all (connectivity sweep)
# --------------------------------------------------------------------------

def cmd_all(args) -> int:
    import types

    rc = 0
    rc |= cmd_discover(args)

    # Library connectivity (read-only unless --actuate passed through).
    if args.host or args.discover:
        rc |= cmd_library(args)
    else:
        warn("Skipping library test (no --host/--discover).")

    # Gateways are optional; report but don't fail the sweep if absent.
    head("Gateways (optional)")
    cmd_rest(args)  # uses args.url / args.api-key
    # Modbus gateway lives on its own host/port; build a dedicated arg set so the
    # controller --host isn't mistaken for the gateway host.
    mb_args = types.SimpleNamespace(
        host=args.mb_host, port=args.mb_port, unit=args.unit,
        register=None, value=None, actuate=False,
    )
    cmd_modbus(mb_args)
    return rc


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _add_target_args(p):
    p.add_argument("--actuate", action="store_true", help="actually change lighting (default: read-only)")
    p.add_argument("--line", type=int, help="DALI line 1-4")
    p.add_argument("--address", type=int, help="DALI short address 0-63")
    p.add_argument("--group", type=int, help="DALI group 0-15")
    p.add_argument("--scene", type=int, help="scene 0-15 to recall")
    p.add_argument("--level", type=int, default=254, help="arc level 0-254 (default 254)")


def main() -> int:
    ap = argparse.ArgumentParser(description="eDIDIO integration test harness")
    sub = ap.add_subparsers(dest="cmd", required=True)

    disc = sub.add_parser("discover", help="find controllers on the LAN")
    disc.add_argument("--timeout", type=float, default=2.0, help="discovery timeout (s)")

    lib = sub.add_parser("library", help="test the controller directly via edidio_control_py")
    lib.add_argument("--host", help="controller IP/hostname")
    lib.add_argument("--discover", action="store_true", help="auto-select the first discovered controller")
    lib.add_argument("--tls", action="store_true", help="use TLS (port 443)")
    lib.add_argument("--port", type=int, help="override port (default 23, or 443 with --tls)")
    lib.add_argument("--conn-timeout", type=float, default=5.0, help="connect timeout (s)")
    lib.add_argument("--timeout", type=float, default=2.0, help="discovery timeout (s), used with --discover")
    lib.add_argument("--blink", action="store_true", help="after setting a level, wait then turn off")
    lib.add_argument("--hold", type=float, default=1.5, help="blink hold time (s)")
    _add_target_args(lib)

    rst = sub.add_parser("rest", help="test the REST gateway over HTTP")
    rst.add_argument("--url", default="http://localhost:8080", help="gateway base URL")
    rst.add_argument("--api-key", help="X-API-Key if the gateway requires one")
    rst.add_argument("--controller", help="controller IP to target (else the gateway default)")
    _add_target_args(rst)

    mb = sub.add_parser("modbus", help="test the Modbus gateway (writes holding registers)")
    mb.add_argument("--host", default="127.0.0.1", help="gateway host")
    mb.add_argument("--port", type=int, default=5020, help="gateway TCP port")
    mb.add_argument("--unit", type=int, default=1, help="Modbus unit/slave id")
    mb.add_argument("--register", type=int, help="1-based holding register (40001 => 1)")
    mb.add_argument("--value", type=int, help="value to write")
    mb.add_argument("--actuate", action="store_true", help="write the register (default: read-only)")

    al = sub.add_parser("all", help="connectivity sweep across discovery, library, and both gateways")
    al.add_argument("--host", help="controller IP for the library test")
    al.add_argument("--discover", action="store_true", help="auto-select discovered controller")
    al.add_argument("--tls", action="store_true")
    al.add_argument("--port", type=int)
    al.add_argument("--conn-timeout", type=float, default=5.0)
    al.add_argument("--timeout", type=float, default=2.0, help="discovery timeout (s)")
    al.add_argument("--blink", action="store_true")
    al.add_argument("--hold", type=float, default=1.5)
    al.add_argument("--url", default="http://localhost:8080", help="REST gateway base URL")
    al.add_argument("--api-key")
    al.add_argument("--controller")
    al.add_argument("--mb-host", dest="mb_host", default="127.0.0.1", help="Modbus gateway host")
    al.add_argument("--mb-port", dest="mb_port", type=int, default=5020, help="Modbus gateway port")
    al.add_argument("--unit", type=int, default=1, help="Modbus unit id")
    _add_target_args(al)

    args = ap.parse_args()

    dispatch = {
        "discover": cmd_discover,
        "library": cmd_library,
        "rest": cmd_rest,
        "modbus": cmd_modbus,
        "all": cmd_all,
    }
    return dispatch[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
