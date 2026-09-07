#!/usr/bin/env python3
"""Generate eDIDIO command byte payloads for a Savant device profile.

Print the exact bytes to paste into a profile command in the Savant Profiler.

Examples
--------
  python generate_commands.py dali-level --line 1 --address 5 --level 254
  python generate_commands.py dali-off --line 1 --address 5
  python generate_commands.py scene --line 1 --scene 3
  python generate_commands.py dmx-color --line 2 --hex FF0000
  python generate_commands.py spektra --zone 1 --type sequence --index 0 --action start
  python generate_commands.py table --line 1     # a reference set of common commands
"""

from __future__ import annotations

import argparse
import sys

from commands import build_command, to_hex, to_savant_escaped


def _emit(payload):
    print(f"  hex     : {to_hex(payload)}")
    print(f"  escaped : {to_savant_escaped(payload)}")


def cmd_single(action, args):
    params = {k: v for k, v in vars(args).items() if k not in ("command", "mid") and v is not None}
    payload = build_command(action, mid=args.mid, **params)
    print(f"{action} {params}")
    _emit(payload)


def cmd_table(args):
    line = args.line
    rows = [
        ("All off (broadcast scene 0)", "dali_scene", {"line": line, "scene": 0}),
        ("Scene 1", "dali_scene", {"line": line, "scene": 1}),
        ("Scene 2", "dali_scene", {"line": line, "scene": 2}),
        ("Scene 3", "dali_scene", {"line": line, "scene": 3}),
        ("Group 0 full", "dali_group_level", {"line": line, "group": 0, "level": 254}),
        ("Group 0 50%", "dali_group_level", {"line": line, "group": 0, "level": 127}),
        ("Group 0 off", "dali_group_level", {"line": line, "group": 0, "level": 0}),
    ]
    print(f"# eDIDIO command reference (line {line}, message id {args.mid})\n")
    for name, action, params in rows:
        payload = build_command(action, mid=args.mid, **params)
        print(f"{name}")
        _emit(payload)
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate eDIDIO command payloads for Savant profiles")
    ap.add_argument("--mid", type=int, default=1, help="message id embedded in the frame (default 1)")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("dali-level"); p.add_argument("--line", type=int, required=True); p.add_argument("--address", type=int, required=True); p.add_argument("--level", type=int, required=True)
    p = sub.add_parser("dali-group-level"); p.add_argument("--line", type=int, required=True); p.add_argument("--group", type=int, required=True); p.add_argument("--level", type=int, required=True)
    p = sub.add_parser("dali-on"); p.add_argument("--line", type=int, required=True); p.add_argument("--address", type=int, required=True)
    p = sub.add_parser("dali-off"); p.add_argument("--line", type=int, required=True); p.add_argument("--address", type=int, required=True)
    p = sub.add_parser("scene"); p.add_argument("--line", type=int, required=True); p.add_argument("--scene", type=int, required=True); p.add_argument("--group", type=int)
    p = sub.add_parser("dmx-color"); p.add_argument("--line", type=int, required=True); p.add_argument("--hex", required=True); p.add_argument("--fixtures", type=int)
    p = sub.add_parser("spektra"); p.add_argument("--zone", type=int, required=True); p.add_argument("--type", default="sequence"); p.add_argument("--index", type=int, default=0); p.add_argument("--action", default="start")
    p = sub.add_parser("spektra-stop"); p.add_argument("--zone", type=int, required=True)
    p = sub.add_parser("table"); p.add_argument("--line", type=int, default=1)

    args = ap.parse_args()

    action_map = {
        "dali-level": "dali_level",
        "dali-group-level": "dali_group_level",
        "dali-on": "dali_on",
        "dali-off": "dali_off",
        "scene": "dali_scene",
        "dmx-color": "dmx_color",
        "spektra": "spektra",
        "spektra-stop": "spektra_stop",
    }

    if args.command == "table":
        cmd_table(args)
    else:
        cmd_single(action_map[args.command], args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
