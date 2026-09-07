#!/usr/bin/env python3
"""Send a KNX group telegram — the "Modbus Poll for KNX".

Injects a GroupValueWrite telegram onto the KNX bus so you can verify the eDIDIO
KNX Gateway live WITHOUT any KNX hardware. Run the gateway (ideally in
`connection: routing` mode) and fire telegrams at your mapped group addresses;
watch the gateway log convert them (and, with a controller connected, the
fixture respond).

Uses KNXnet/IP **routing** (multicast 224.0.23.12) by default, which needs no
gateway/router — two software endpoints on the same LAN see each other. Use
`--connection tunnelling --gateway-ip <router>` to go via a KNXnet/IP router.

Examples
--------
  # 80% dim on 1/1/1
  python tools/send_telegram.py --ga 1/1/1 --dpt scaling --value 80
  # switch on 1/1/2
  python tools/send_telegram.py --ga 1/1/2 --dpt switch --value on
  # recall scene 3 selector on 3/2/1
  python tools/send_telegram.py --ga 3/2/1 --dpt scene_number --value 3
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from xknx import XKNX
from xknx.io import ConnectionConfig, ConnectionType
from xknx.tools import group_value_write

# Maps the gateway's dpt names -> (xknx value_type, value parser).
_DPT = {
    "switch": ("switch", lambda v: _parse_bool(v)),
    "scaling": ("percent", lambda v: _clamp_int(v, 0, 100)),      # DPT 5.001, 0-100 %
    "scene_number": ("scene_number", lambda v: _clamp_int(v, 0, 63)),  # DPT 17.001
}


def _parse_bool(v: str) -> bool:
    return str(v).strip().lower() in ("on", "1", "true", "yes", "y")


def _clamp_int(v, lo, hi) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        raise SystemExit(f"value must be a number between {lo} and {hi}")
    return max(lo, min(hi, n))


def _connection_config(args) -> ConnectionConfig:
    if args.connection in ("tunnelling", "tunneling"):
        if not args.gateway_ip:
            raise SystemExit("--gateway-ip is required for tunnelling")
        return ConnectionConfig(
            connection_type=ConnectionType.TUNNELING,
            gateway_ip=args.gateway_ip,
            gateway_port=args.gateway_port,
        )
    return ConnectionConfig(connection_type=ConnectionType.ROUTING)


async def _send(args) -> int:
    value_type, parse = _DPT[args.dpt]
    value = parse(args.value)

    xknx = XKNX(connection_config=_connection_config(args))
    await xknx.start()
    try:
        group_value_write(xknx, args.ga, value, value_type=value_type)
        # Let the outgoing telegram queue flush before we disconnect.
        await xknx.telegrams.join()
        await asyncio.sleep(0.3)
    finally:
        await xknx.stop()

    print(f"Sent {args.dpt} = {value!r} ({value_type}) to group address {args.ga}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a KNX group telegram to test the eDIDIO KNX Gateway")
    ap.add_argument("--ga", required=True, help="KNX group address, e.g. 1/1/1")
    ap.add_argument("--dpt", required=True, choices=sorted(_DPT), help="datapoint type")
    ap.add_argument("--value", required=True, help="switch: on/off | scaling: 0-100 | scene_number: 0-63")
    ap.add_argument("--connection", default="routing", choices=["routing", "tunnelling", "tunneling"],
                    help="KNXnet/IP mode (default: routing / multicast, no hardware needed)")
    ap.add_argument("--gateway-ip", help="KNXnet/IP router IP (tunnelling)")
    ap.add_argument("--gateway-port", type=int, default=3671)
    args = ap.parse_args()

    try:
        return asyncio.run(_send(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
