"""Helpers and tables shared by the live tool modules."""

from __future__ import annotations

import json

from edidio_control_py._v2 import eDS10_v2_pb2 as pb

from .. import ops, spektra_map
from ..server import _controller

_LOGIC_SOURCES = {v.name.lower(): v.number for v in pb.LogicType.DESCRIPTOR.values}
_LOGIC_COMPARE = {v.name.lower(): v.number for v in pb.LogicComparisonType.DESCRIPTOR.values}
_LOGIC_SOURCE_NAME = {v: k for k, v in _LOGIC_SOURCES.items()}
_LOGIC_COMPARE_NAME = {v: k for k, v in _LOGIC_COMPARE.items()}
_COMPARE_SYMBOLS = {"<": "less_than", "<=": "less_than_or_equals", "==": "equals",
                    "=": "equals", ">": "more_than", ">=": "more_than_or_equals",
                    "!=": "not_equal"}
_INPUT_MODES = {"momentary": 0, "latching": 1, "momentary_disabled": 128,
                "latching_disabled": 129}
_INPUT_MODE_NAME = {v: k for k, v in _INPUT_MODES.items()}
_OUTPUT_MODES = {"momentary": 2, "latching": 3}


def _err(err) -> str:
    if isinstance(err, ops.Unsupported):
        return f"Not supported by this controller: {err}."
    return f"Error: {err}"


async def _connect(host: str, port: int, use_tls: bool):
    if host and not (_controller.connected and _controller.host == host):
        await _controller.connect(host, port, use_tls)
    _controller._require()


def _json(text, what):
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{what} must be JSON: {err}") from None


def _seconds(v) -> int:
    """5, '5', '5s', '2m', '1h', '1h30m' -> seconds (list steps hold up to 65535 s)."""
    if isinstance(v, (int, float)):
        secs = int(v)
    else:
        s, secs, num = str(v).strip().lower(), 0, ""
        for ch in s:
            if ch.isdigit() or ch == ".":
                num += ch
            elif ch in "hms" and num:
                secs += int(float(num) * {"h": 3600, "m": 60, "s": 1}[ch])
                num = ""
            elif ch != " ":
                raise ValueError(f"bad duration {v!r} (use 30, '30s', '5m', '1h30m')")
        if num:
            secs += int(float(num))
    if not 0 <= secs <= 65535:
        raise ValueError(f"a list step waits 0-65535 s (18 h 12 m); got {secs}")
    return secs


async def _save_after(messages: list) -> list:
    """Every stored change ends with DEVICE_SAVE (the controller acks it once saved)."""
    return messages + [spektra_map.device_save_message(_controller._next_id())]
