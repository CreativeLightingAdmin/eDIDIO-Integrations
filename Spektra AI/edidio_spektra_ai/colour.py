"""Set a Spektra zone to a colour right now (live, nothing stored), the way the
SpektraPlus colour page does it.

- DMX zone: one DMXMessage for the whole zone (channel 0xFFFF = every light in the
  zone); the controller repeats the channel levels across the zone's lights.
- DALI zone: an arc level per channel - on group addresses when the zone uses DALI
  group addressing (``daligroupoffset``), otherwise on each light's addresses
  (light n starts at startAddress + n x channels).
- DALI DT8 zones: one address (or group) per light, colour staged then ACTIVATE -
  RGBWAF dimlevels, or (xy zones) the channels mixed into one CIE xy point as
  SpektraPlus does. Zones that continue across lines are not handled yet.
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
    if proto == PROTOCOL_DT8_RGBWAF:
        return dt8_messages(zone, levels, next_id)
    if proto == PROTOCOL_DT8_XY:
        return dt8_xy_messages(zone, levels, next_id)
    if proto != PROTOCOL_DALI:
        raise ValueError(f"unknown zone protocol {proto}")
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


# --- DALI DT8 (IEC 62386-209) -------------------------------------------------------

PROTOCOL_DT8_RGBWAF, PROTOCOL_DT8_XY = 2, 3


def dt8_messages(zone: dict, levels: list, next_id) -> list:
    """RGBWAF zone: per light (one address each, or one group), stage RGB and WAF
    (all three DTRs every time, so nothing is left over from the RGB step), set the
    arc level to the brightest channel, then ACTIVATE - the order SpektraPlus and the
    controller's own Spektra engine use."""
    from .v2 import frame
    lines = int(zone.get("linemask") or 0)
    vals = [min(int(v), 254) for v in levels] + [0] * 6
    rgb, waf = vals[0:3], vals[3:6]
    arc = max(vals[:int(zone.get("numChannels") or 0)] or [0])
    group = zone.get("daligroupoffset")
    if isinstance(group, int) and 0 <= group <= 15:
        targets = [0x40 + group]
    else:
        start = int(zone.get("startAddress") or 0)
        targets = [start + i for i in range(int(zone.get("numLights") or 0)) if start + i <= 63]

    def msg(**kw):
        return frame(pb.EdidioMessage(message_id=next_id(),
                                      dali_message=pb.DALIMessage(line_mask=lines, **kw)))
    out = []
    for a in targets:
        out.append(msg(address=a, type8=pb.Type8CommandType.SET_TEMP_RGB_DIMLEVEL,
                       dtr=pb.DTRPayloadMessage(dtr=rgb)))
        out.append(msg(address=a, type8=pb.Type8CommandType.SET_TEMP_WAF_DIMLEVEL,
                       dtr=pb.DTRPayloadMessage(dtr=waf)))
        out.append(msg(address=a, custom_command=pb.CustomDALICommandType.DALI_ARC_LEVEL,
                       arg=arc))
        out.append(msg(address=a, type8=pb.Type8CommandType.ACTIVATE))
    return out


# DT8 application-extended queries (ENABLE DEVICE TYPE 8 must precede each one).
_ENABLE_DT8 = 0xC108
_Q_COLOUR_STATUS, _Q_COLOUR_TYPE_FEATURES, _Q_COLOUR_VALUE = 0xF8, 0xF9, 0xFA
_LIVE_RGBWAF = (9, 10, 11, 12, 13, 14)       # QUERY COLOUR VALUE selectors (active colour)


async def _f16(ctrl, line, frame16, reply):
    from .v2 import request
    field = {"frame_16_bit_reply": frame16} if reply else {"frame_16_bit": frame16}
    r = await request(ctrl._require(), pb.EdidioMessage(
        message_id=ctrl._next_id(),
        dali_message=pb.DALIMessage(line_mask=1 << (line - 1), **field)))
    if not reply or r.WhichOneof("payload") != "dali_query":
        return None
    q = r.dali_query
    if q.dali_flag != pb.DALIRXStatusFlag.RECEIVED_8_BIT_FRAME:
        return None
    return q.response_data.uint_data


async def _dt8_query(ctrl, line, address, opcode, selector=None, attempts=3):
    """DTR0 = selector (if any), ENABLE DT8, query. A timeout repeats the whole
    sequence, so the gear's DTR0 and DT8 state are set again before the query."""
    from edidio_control_py.exceptions import EDIDIOTimeoutError
    for n in range(attempts):
        try:
            if selector is not None:
                await _f16(ctrl, line, 0xA300 | selector, reply=False)   # DTR0 = selector
            await _f16(ctrl, line, _ENABLE_DT8, reply=False)
            return await _f16(ctrl, line, ((address << 1) | 1) << 8 | opcode, reply=True)
        except EDIDIOTimeoutError:
            if n == attempts - 1:
                raise
    return None


_Q_CONTENT_DTR0 = 0x98
# QUERY COLOUR VALUE selectors (IEC 62386-209): active x, y, Tc; Tc limits.
_SEL_X, _SEL_Y, _SEL_TC = 0, 1, 2
_SEL_TC_COOLEST, _SEL_TC_PHYS_COOLEST, _SEL_TC_WARMEST, _SEL_TC_PHYS_WARMEST = 128, 129, 130, 131


async def _dt8_query16(ctrl, line, address, selector):
    """A 16-bit colour value: MSB in the reply, LSB left in DTR0. 0xFFFF = MASK."""
    msb = await _dt8_query(ctrl, line, address, _Q_COLOUR_VALUE, selector)
    if msb is None:
        return None
    from edidio_control_py.exceptions import EDIDIOTimeoutError
    try:
        lsb = await _f16(ctrl, line, ((address << 1) | 1) << 8 | _Q_CONTENT_DTR0, reply=True)
    except EDIDIOTimeoutError:                    # DTR0 may be gone: redo the pair
        msb = await _dt8_query(ctrl, line, address, _Q_COLOUR_VALUE, selector)
        lsb = await _f16(ctrl, line, ((address << 1) | 1) << 8 | _Q_CONTENT_DTR0,
                         reply=True) if msb is not None else None
    if lsb is None:
        return None
    v = (msb << 8) | lsb
    return None if v == 0xFFFF else v


def mirek_to_kelvin(m):
    return round(1_000_000 / m) if m else None


async def dt8_info(ctrl, line: int, address: int) -> dict:
    """What a DT8 driver supports, which colour mode is active, and its live colour."""
    feat = await _dt8_query(ctrl, line, address, _Q_COLOUR_TYPE_FEATURES)
    status = await _dt8_query(ctrl, line, address, _Q_COLOUR_STATUS)
    out = {"address": address, "features_raw": feat, "status_raw": status}
    if feat is not None:
        out["supports"] = [n for bit, n in ((0x01, "xy"), (0x02, "colour temperature"))
                           if feat & bit]
        if (feat >> 2) & 0x07:
            out["supports"].append(f"{(feat >> 2) & 0x07} primaries")
        if (feat >> 5) & 0x07:
            out["supports"].append(f"RGBWAF with {(feat >> 5) & 0x07} channels")
        out["rgbwaf_channels"] = (feat >> 5) & 0x07
    if status is not None:
        out["flags"] = [n for bit, n in ((0x01, "xy out of range (the driver moved it into its gamut)"),
                                         (0x02, "colour temperature out of range (clamped)"),
                                         (0x04, "auto-calibration running"),
                                         (0x08, "auto-calibration succeeded")) if status & bit]
        out["active"] = ("RGBWAF" if status & 0x80 else "colour temperature" if status & 0x20
                         else "xy" if status & 0x10 else "primary N" if status & 0x40 else "none")
    if feat is not None and feat & 0x02:          # colour temperature capable
        out["tc_mirek"] = await _dt8_query16(ctrl, line, address, _SEL_TC)
        lim = {}
        for key, sel in (("coolest", _SEL_TC_COOLEST), ("warmest", _SEL_TC_WARMEST),
                         ("physical_coolest", _SEL_TC_PHYS_COOLEST),
                         ("physical_warmest", _SEL_TC_PHYS_WARMEST)):
            lim[key] = await _dt8_query16(ctrl, line, address, sel)
        out["tc_limits_mirek"] = lim
    if feat is not None and feat & 0x01:          # xy capable
        x = await _dt8_query16(ctrl, line, address, _SEL_X)
        y = await _dt8_query16(ctrl, line, address, _SEL_Y)
        out["xy"] = None if x is None or y is None else (round(x / 65536, 4), round(y / 65536, 4))
    n = out.get("rgbwaf_channels") or 0
    if n:
        out["rgbwaf"] = [await _dt8_query(ctrl, line, address, _Q_COLOUR_VALUE, s)
                         for s in _LIVE_RGBWAF[:n]]
    out["level"] = await _f16(ctrl, line, ((address << 1) | 1) << 8 | 0xA0, reply=True)
    return out


# --- DT8 xy zones: zone channel levels -> one CIE xy point (as SpektraPlus does) -------

# Base colour per LightType (RED, GREEN, BLUE, WARM_WHITE, COOL_WHITE, AMBER; others
# black), the same table SpektraPlus combines channels with.
_LIGHT_RGB = {0: (1, 0, 0), 1: (0, 1, 0), 2: (0, 0, 1), 3: (1.0, 0.98, 0.95),
              4: (0.95, 0.98, 1.0), 5: (1.0, 0.75, 0)}


def combined_rgb255(zone: dict, levels: list) -> tuple:
    """The zone's channel levels mixed into one RGB colour (0-255)."""
    from .spektra_map import infer_light_type
    types = zone.get("channelTypes") or [infer_light_type(c)
                                         for c in zone.get("channelColours") or []]
    r = g = b = 0.0
    for i in range(int(zone.get("numChannels") or 0)):
        base = _LIGHT_RGB.get(types[i] if i < len(types) else None, (0, 0, 0))
        k = (levels[i] if i < len(levels) else 0) / 255
        r, g, b = r + base[0] * k, g + base[1] * k, b + base[2] * k
    peak = max(r, g, b)
    if peak <= 0:
        return (0, 0, 0)
    scale = min(1.0, peak) / peak
    return tuple(max(0, min(255, round(v * scale * 255))) for v in (r, g, b))


def rgb_to_xy(r: int, g: int, b: int) -> tuple:
    """sRGB (0-255) -> CIE 1931 xy scaled to 0-65535, with SpektraPlus's matrix."""
    def lin(c):
        c /= 255.0
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92
    rl, gl, bl = lin(r), lin(g), lin(b)
    x_ = rl * 0.649926 + gl * 0.103455 + bl * 0.197109
    y_ = rl * 0.234327 + gl * 0.743075 + bl * 0.022598
    z_ = gl * 0.053077 + bl * 1.035763
    tot = x_ + y_ + z_
    if tot <= 0:
        return (0, 0)
    return (max(0, min(65535, round(x_ / tot * 65535))),
            max(0, min(65535, round(y_ / tot * 65535))))


def dt8_xy_messages(zone: dict, levels: list, next_id) -> list:
    """xy zone: per light, set temporary x and y, arc = brightest channel, ACTIVATE."""
    from .v2 import frame
    lines = int(zone.get("linemask") or 0)
    x, y = rgb_to_xy(*combined_rgb255(zone, levels))
    n = int(zone.get("numChannels") or 0)
    arc = max([min(int(v), 254) for v in levels[:n]] or [0])
    group = zone.get("daligroupoffset")
    if isinstance(group, int) and 0 <= group <= 15:
        targets = [0x40 + group]
    else:
        start = int(zone.get("startAddress") or 0)
        targets = [start + i for i in range(int(zone.get("numLights") or 0)) if start + i <= 63]

    def msg(**kw):
        return frame(pb.EdidioMessage(message_id=next_id(),
                                      dali_message=pb.DALIMessage(line_mask=lines, **kw)))
    out = []
    for a in targets:
        out.append(msg(address=a, type8=pb.Type8CommandType.SET_TEMP_X_COORD,
                       dtr=pb.DTRPayloadMessage(dtr=[x & 0xFF, x >> 8])))
        out.append(msg(address=a, type8=pb.Type8CommandType.SET_TEMP_Y_COORD,
                       dtr=pb.DTRPayloadMessage(dtr=[y & 0xFF, y >> 8])))
        out.append(msg(address=a, custom_command=pb.CustomDALICommandType.DALI_ARC_LEVEL,
                       arg=arc))
        out.append(msg(address=a, type8=pb.Type8CommandType.ACTIVATE))
    return out
