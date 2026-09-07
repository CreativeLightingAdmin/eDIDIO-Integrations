"""Build eDIDIO command byte payloads for Savant device profiles.

Savant integrates third-party devices via **profiles** (built in RacePoint
Blueprint / the Savant Profiler), where each command sends a defined data string
to the device over TCP. This module turns a lighting action into the exact bytes
to paste into a profile command, reusing the byte-verified ``edidio_frames``
encoder.

Profile commands are typically static, so a fixed message id (default 1) is used.
"""

from __future__ import annotations

import edidio_frames as frames


def _parse_hex_rgb(value: str):
    text = value.lstrip("#").strip()
    if len(text) != 6:
        raise ValueError("colour must be #RRGGBB")
    return [int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)]


def build_command(kind: str, *, mid: int = 1, **params) -> bytes:
    """Return the framed byte payload for a lighting action.

    ``kind`` and params:
      dali_level        line, address, level
      dali_group_level  line, group, level
      dali_on / dali_off  line, address
      dali_scene        line, scene [, group]
      dmx_color         line, hex [, fixtures]
      spektra           zone, type, index, action
      spektra_stop      zone
    """
    line = params.get("line")
    lm = frames.line_mask(line) if line is not None else None

    if kind == "dali_level":
        return frames.dali_arc_level(mid, lm, params["address"], params["level"])
    if kind == "dali_group_level":
        return frames.dali_group_arc_level(mid, lm, params["group"], params["level"])
    if kind == "dali_on":
        return frames.dali_command(mid, lm, params["address"], "on")
    if kind == "dali_off":
        return frames.dali_command(mid, lm, params["address"], "off")
    if kind == "dali_scene":
        group = params.get("group")
        if group is None:
            return frames.dali_broadcast_scene(mid, lm, params["scene"])
        return frames.dali_scene_on_group(mid, lm, group, params["scene"])
    if kind == "dmx_color":
        rgb = _parse_hex_rgb(params["hex"])
        fixtures = params.get("fixtures") or (512 // len(rgb))
        return frames.dmx_level(mid, 0xFF, lm, 1, fixtures, rgb, 0)
    if kind == "spektra":
        target = {
            "sequence": frames.SPEKTRA_SEQUENCE,
            "theme": frames.SPEKTRA_THEME,
            "static": frames.SPEKTRA_STATIC,
        }[str(params.get("type", "sequence")).lower()]
        act = {
            "start": frames.SPEKTRA_START,
            "stop": frames.SPEKTRA_STOP,
            "pause": frames.SPEKTRA_PAUSE,
        }[str(params.get("action", "start")).lower()]
        return frames.spektra_control(mid, target, params["zone"], params.get("index", 0), act)
    if kind == "spektra_stop":
        return frames.spektra_stop(mid, params["zone"])

    raise ValueError(f"unknown action: {kind}")


def to_hex(payload: bytes, *, sep: str = " ") -> str:
    """Hex string for pasting into a profile, e.g. 'CD 00 0E ...'."""
    return sep.join(f"{b:02X}" for b in payload)


def to_savant_escaped(payload: bytes) -> str:
    r"""Backslash-x escaped string (e.g. \xCD\x00...) for profile data fields
    that take an escaped byte string."""
    return "".join(f"\\x{b:02X}" for b in payload)
