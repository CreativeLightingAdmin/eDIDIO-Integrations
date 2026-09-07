"""Python mirror of the NetLinx frame-building algorithm.

This is NOT the driver — it re-implements, in Python, the exact integer/byte
operations used by eDIDIO.axi (varint via integer division by 128, tags via
field*8 + wire_type, the same zero-omission rules). Its test asserts these
produce the known-good reference frames, proving the algorithm transcribed into
NetLinx is correct before it is locked into an untestable environment.

Keep this in lockstep with eDIDIO.axi.
"""

# Field numbers / enums (mirror the .axi DEFINE_CONSTANTs).
F_MESSAGE_ID = 1
F_DALI = 18
F_DMX = 20
F_EXTERNAL_TRIGGER = 21
F_SPEKTRA_CONTROL = 27

D_LINE_MASK, D_ADDRESS, D_COMMAND, D_CUSTOM_COMMAND, D_ARG = 1, 2, 5, 6, 9
X_ZONE, X_UNIVERSE_MASK, X_CHANNEL, X_REPEAT, X_LEVEL, X_FADE = 1, 2, 3, 4, 5, 6
S_TYPE, S_ZONE, S_INDEX, S_ACTION = 1, 2, 3, 4
E_TRIGGER, T_TYPE, T_ZONE, T_LINE_MASK = 1, 1, 2, 3

DALI_ARC_LEVEL, DALI_GROUP_ARC_LEVEL, DALI_BROADCAST_SCENE, DALI_SCENE_ON_GROUP = 0, 2, 3, 4
TRIGGER_SPEKTRA_STOP_SEQ = 13


def varint(value):
    """NetLinx-style varint: repeated (v BAND $7F) with high bit, v = v / 128."""
    out = []
    v = value
    while True:
        if v >= 128:
            out.append((v & 0x7F) | 0x80)
            v = v // 128          # NetLinx: v = v / 128 (integer division)
        else:
            out.append(v & 0x7F)
            break
    return bytes(out)


def tag(field, wire_type):
    return varint(field * 8 + wire_type)   # NetLinx: field*8 (no shift operator)


def uint(field, value, always=False):
    if value == 0 and not always:
        return b""
    return tag(field, 0) + varint(value)


def packed(field, values):
    body = b"".join(varint(v) for v in values)
    return tag(field, 2) + varint(len(body)) + body


def embed(field, body):
    return tag(field, 2) + varint(len(body)) + body


def frame(edidio_body):
    n = len(edidio_body)
    return bytes([0xCD, (n // 256) & 0xFF, n & 0xFF]) + edidio_body   # NetLinx: n/256, n BAND $FF


# DALI addressing: 0-63 individual, 64-79 group (address = 64 + group), 80
# broadcast. Scenes use the standard DALI "GO TO SCENE X" command (0x10 + scene)
# sent to the target address.
GROUP_ADDRESS_BASE, BROADCAST_ADDRESS, GO_TO_SCENE_BASE = 64, 80, 0x10


def dali(mid, line_mask, address, command=None, custom_command=None, arg=None):
    body = uint(D_LINE_MASK, line_mask) + uint(D_ADDRESS, address)
    if command is not None:
        body += uint(D_COMMAND, command, always=True)
    if custom_command is not None:
        body += uint(D_CUSTOM_COMMAND, custom_command, always=True)
    if arg is not None:
        body += uint(D_ARG, arg, always=True)
    return frame(uint(F_MESSAGE_ID, mid) + embed(F_DALI, body))


def dali_arc_level(mid, line_mask, address, level):
    return dali(mid, line_mask, address, custom_command=DALI_ARC_LEVEL, arg=level)


def dali_group_arc_level(mid, line_mask, group, level):
    # DALI_ARC_LEVEL to the group address (64 + group).
    return dali(mid, line_mask, GROUP_ADDRESS_BASE + group, custom_command=DALI_ARC_LEVEL, arg=level)


def dali_command(mid, line_mask, address, command, arg=0):
    return dali(mid, line_mask, address, command=command, arg=arg)


def dali_broadcast_scene(mid, line_mask, scene):
    # Raw "GO TO SCENE X" command (0x10 + scene) to broadcast address 80.
    return dali(mid, line_mask, BROADCAST_ADDRESS, command=GO_TO_SCENE_BASE + scene)


def dali_scene_on_group(mid, line_mask, group, scene):
    # Raw "GO TO SCENE X" command (0x10 + scene) to the group address (64 + group).
    return dali(mid, line_mask, GROUP_ADDRESS_BASE + group, command=GO_TO_SCENE_BASE + scene)


def dmx_level(mid, zone, universe_mask, channel, repeat, levels, fade=0):
    body = (uint(X_ZONE, zone) + uint(X_UNIVERSE_MASK, universe_mask) +
            uint(X_CHANNEL, channel) + uint(X_REPEAT, repeat) +
            packed(X_LEVEL, levels) + uint(X_FADE, fade))
    return frame(uint(F_MESSAGE_ID, mid) + embed(F_DMX, body))


def spektra_control(mid, stype, zone, index, action):
    body = uint(S_TYPE, stype) + uint(S_ZONE, zone) + uint(S_INDEX, index) + uint(S_ACTION, action)
    return frame(uint(F_MESSAGE_ID, mid) + embed(F_SPEKTRA_CONTROL, body))


def spektra_stop(mid, zone, line_mask=0xFF):
    trigger = uint(T_TYPE, TRIGGER_SPEKTRA_STOP_SEQ) + uint(T_ZONE, zone) + uint(T_LINE_MASK, line_mask)
    return frame(uint(F_MESSAGE_ID, mid) + embed(F_EXTERNAL_TRIGGER, embed(E_TRIGGER, trigger)))
