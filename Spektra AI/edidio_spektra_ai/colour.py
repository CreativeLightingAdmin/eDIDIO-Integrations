"""Set a Spektra zone to a colour right now (live, nothing stored), the way the
SpektraPlus colour page does it.

- DMX zone: one DMXMessage for the whole zone (channel 0xFFFF = every light in the
  zone); the controller repeats the channel levels across the zone's lights.
- DALI zone: an arc level per channel - on group addresses when the zone uses DALI
  group addressing (``daligroupoffset``), otherwise on each light's addresses
  (light n starts at startAddress + n x channels).
- DALI DT8 zones and zones that continue across lines are not handled here yet.
"""

from __future__ import annotations

from edidio_control_py._v2 import eDS10_v2_pb2 as pb

PROTOCOL_DALI, PROTOCOL_DMX = 0, 1
_CONSECUTIVE_LINES = 1
_PRIMARY = {"#FF0000": 0, "#00FF00": 1, "#0000FF": 2}   # channel colour -> RGB component


def parse_levels(colour, zone: dict) -> list:
    """'255,0,0' / [255,0,0] (one value per zone channel) or '#RRGGBB' (mapped onto
    the zone's red/green/blue channels; other channels 0) -> channel levels."""
    n = int(zone.get("numChannels") or 0)
    if isinstance(colour, str) and colour.strip().startswith("#"):
        h = colour.strip().lstrip("#")
        if len(h) != 6:
            raise ValueError("a hex colour is #RRGGBB")
        rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
        chans = [str(c).upper() for c in (zone.get("channelColours") or [])]
        if not any(c in _PRIMARY for c in chans):
            raise ValueError("this zone has no red/green/blue channels; give one level "
                             f"per channel ({n})")
        return [rgb[_PRIMARY[c]] if c in _PRIMARY else 0 for c in chans[:n]]
    vals = colour if isinstance(colour, list) else [v for v in str(colour).split(",") if v.strip()]
    levels = [int(v) for v in vals]
    if any(not 0 <= v <= 255 for v in levels):
        raise ValueError("channel levels are 0-255")
    if len(levels) > n:
        raise ValueError(f"the zone has {n} channel(s), got {len(levels)} levels")
    return levels + [0] * (n - len(levels))


def zone_messages(zone: dict, levels: list, next_id, *, fade_ms: int = 50) -> list:
    """Frames that put ``levels`` on every light of ``zone``."""
    from .v2 import frame
    proto = zone.get("protocol")
    n = int(zone.get("numChannels") or 0)
    lines = int(zone.get("linemask") or 0)
    if not n or not zone.get("numLights") or not lines:
        raise ValueError("the zone has no lights, channels or line set up")
    if proto == PROTOCOL_DMX:
        dmx = pb.DMXMessage(zone=int(zone["index"]), universe_mask=lines,
                            fade_time_by_10ms=max(0, round(fade_ms / 10)),
                            channel=0xFFFF, level=list(levels))
        return [frame(pb.EdidioMessage(message_id=next_id(), dmx_message=dmx))]
    if proto != PROTOCOL_DALI:
        raise ValueError("live colour on DALI DT8 zones is not supported yet")
    targets = []
    group = zone.get("daligroupoffset")
    if isinstance(group, int) and 0 <= group <= 15:
        if group + n - 1 > 15:
            raise ValueError(f"group {group} + {n} channels runs past group 15")
        targets = [(0x40 + group + ch, lines, ch) for ch in range(n)]
    else:
        if zone.get("multiLineAddressing") == _CONSECUTIVE_LINES:
            raise ValueError("zones that continue across lines are not supported yet")
        start = int(zone.get("startAddress") or 0)
        for light in range(int(zone["numLights"])):
            first = start + light * n
            if first + n - 1 > 63:
                break
            targets += [(first + ch, lines, ch) for ch in range(n)]
    out = []
    for address, mask, ch in targets:
        msg = pb.DALIMessage(line_mask=mask, address=address,
                             custom_command=pb.CustomDALICommandType.DALI_ARC_LEVEL,
                             arg=min(int(levels[ch]), 254))
        out.append(frame(pb.EdidioMessage(message_id=next_id(), dali_message=msg)))
    return out
