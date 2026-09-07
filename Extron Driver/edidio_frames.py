"""Pure-Python eDIDIO protocol frame encoder — zero dependencies.

Produces byte-identical output to the ``edidio_control_py`` library, but without
requiring the ``protobuf`` runtime, ``asyncio``, or any C extension. This makes
it safe to run inside constrained embedded Python environments such as Extron
ControlScript (and reusable for AMX Muse).

Wire format: every frame is ``0xCD`` + a 2-byte big-endian length + a serialized
``EdidioMessage`` protobuf. Only the handful of fields needed for lighting
control are encoded, by hand, using the protobuf wire format.

The exact field numbers, wire types and zero-value emission rules below were
extracted from the eDIDIO ``.proto`` and validated byte-for-byte against
``edidio_control_py`` (see tests/test_frames.py).
"""

# --- EdidioMessage field numbers ---
_F_MESSAGE_ID = 1
_F_DALI = 18
_F_DMX = 20
_F_EXTERNAL_TRIGGER = 21
_F_SPEKTRA_CONTROL = 27

# --- DALIMessage field numbers ---
_D_LINE_MASK = 1
_D_ADDRESS = 2
_D_COMMAND = 5
_D_CUSTOM_COMMAND = 6
_D_ARG = 9

# --- DMXMessage field numbers ---
_X_ZONE = 1
_X_UNIVERSE_MASK = 2
_X_CHANNEL = 3
_X_REPEAT = 4
_X_LEVEL = 5
_X_FADE = 6

# --- SpektraControlMessage field numbers ---
_S_TYPE = 1
_S_ZONE = 2
_S_INDEX = 3
_S_ACTION = 4

# --- ExternalTriggerMessage / TriggerMessage field numbers ---
_E_TRIGGER = 1
_T_TYPE = 1
_T_ZONE = 2
_T_LINE_MASK = 3

# --- Enums ---
DALI_ARC_LEVEL = 0
DALI_GROUP_ARC_LEVEL = 2
DALI_BROADCAST_SCENE = 3
DALI_SCENE_ON_GROUP = 4

# DALI addressing: 0-63 individual, 64-79 group (address = 64 + group), 80
# broadcast. Scenes are recalled with the standard DALI "GO TO SCENE X" command
# (0x10 + scene) sent to the target address.
DALI_GROUP_ADDRESS_BASE = 64
DALI_BROADCAST_ADDRESS = 80
DALI_GO_TO_SCENE_COMMAND_BASE = 0x10

# Standard DALI commands (subset).
DALI_OFF = 0
DALI_FADE_UP = 1
DALI_FADE_DOWN = 2
DALI_STEP_UP = 3
DALI_STEP_DOWN = 4
DALI_MAX_LEVEL = 5
DALI_MIN_LEVEL = 6
DALI_RECALL_LAST_ACTIVE_LEVEL = 10
DALI_IDENTIFY_DEVICE = 37

SPEKTRA_SEQUENCE = 1
SPEKTRA_THEME = 2
SPEKTRA_STATIC = 3
SPEKTRA_START = 0
SPEKTRA_STOP = 1
SPEKTRA_PAUSE = 2
TRIGGER_SPEKTRA_STOP_SEQ = 13

DALI_ARC_LEVEL_MAX = 254

_NAMED_COMMANDS = {
    "off": DALI_OFF,
    "on": DALI_MAX_LEVEL,
    "max": DALI_MAX_LEVEL,
    "min": DALI_MIN_LEVEL,
    "fade_up": DALI_FADE_UP,
    "fade_down": DALI_FADE_DOWN,
    "step_up": DALI_STEP_UP,
    "step_down": DALI_STEP_DOWN,
    "recall_last": DALI_RECALL_LAST_ACTIVE_LEVEL,
    "identify": DALI_IDENTIFY_DEVICE,
}


# --------------------------------------------------------------------------
# Low-level protobuf wire encoding
# --------------------------------------------------------------------------

def _varint(value):
    """Encode an unsigned integer as a protobuf base-128 varint."""
    if value < 0:
        raise ValueError("varint cannot encode a negative value")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def _tag(field, wire_type):
    return _varint((field << 3) | wire_type)


def _uint(field, value, always=False):
    """A varint (uint32/enum) field. Omitted when zero unless ``always`` — matching
    proto3 scalar behaviour vs. explicitly-set optional fields."""
    if value == 0 and not always:
        return b""
    return _tag(field, 0) + _varint(value)


def _packed_uint(field, values):
    """A packed repeated uint32 field (wire type 2)."""
    body = b"".join(_varint(v) for v in values)
    return _tag(field, 2) + _varint(len(body)) + body


def _embed(field, body):
    """A length-delimited embedded message field."""
    return _tag(field, 2) + _varint(len(body)) + body


def _frame(edidio_body):
    """Wrap a serialized EdidioMessage with the 0xCD + 2-byte length header."""
    length = len(edidio_body)
    return bytes([0xCD, (length >> 8) & 0xFF, length & 0xFF]) + edidio_body


def _clamp(value, lo, hi):
    return max(lo, min(hi, int(value)))


# --------------------------------------------------------------------------
# Message builders (mirror edidio_control_py's create_* helpers)
# --------------------------------------------------------------------------

def _dali(message_id, line_mask, address, *, command=None, custom_command=None, arg=None):
    body = _uint(_D_LINE_MASK, line_mask)
    body += _uint(_D_ADDRESS, address)
    if command is not None:
        body += _uint(_D_COMMAND, command, always=True)
    if custom_command is not None:
        body += _uint(_D_CUSTOM_COMMAND, custom_command, always=True)
    if arg is not None:
        body += _uint(_D_ARG, arg, always=True)
    edidio = _uint(_F_MESSAGE_ID, message_id) + _embed(_F_DALI, body)
    return _frame(edidio)


def dali_arc_level(message_id, line_mask, address, level):
    """Set a single DALI address to an arc level (0-254)."""
    return _dali(message_id, line_mask, address,
                 custom_command=DALI_ARC_LEVEL, arg=_clamp(level, 0, DALI_ARC_LEVEL_MAX))


def dali_group_arc_level(message_id, line_mask, group, level):
    """Set a whole DALI group to an arc level (0-254).

    Encoded as DALI_ARC_LEVEL to the group address (64 + group)."""
    return _dali(message_id, line_mask, DALI_GROUP_ADDRESS_BASE + group,
                 custom_command=DALI_ARC_LEVEL, arg=_clamp(level, 0, DALI_ARC_LEVEL_MAX))


def dali_command(message_id, line_mask, address, command, arg=0):
    """Send a standard DALI command. ``command`` may be an int code or a name
    (off, on, max, min, fade_up, fade_down, step_up, step_down, recall_last,
    identify)."""
    if isinstance(command, str):
        key = command.lower()
        if key not in _NAMED_COMMANDS:
            raise ValueError("unknown DALI command: %s" % command)
        command = _NAMED_COMMANDS[key]
    return _dali(message_id, line_mask, address, command=command, arg=arg)


def dali_broadcast_scene(message_id, line_mask, scene):
    """Recall a stored scene across all fittings on the line(s).

    Encoded as the raw DALI "GO TO SCENE X" command (0x10 + scene) to broadcast
    address 80."""
    return _dali(message_id, line_mask, DALI_BROADCAST_ADDRESS,
                 command=DALI_GO_TO_SCENE_COMMAND_BASE + scene)


def dali_scene_on_group(message_id, line_mask, group, scene):
    """Recall a stored scene on a specific group.

    Encoded as the raw DALI "GO TO SCENE X" command (0x10 + scene) to the group
    address (64 + group)."""
    return _dali(message_id, line_mask, DALI_GROUP_ADDRESS_BASE + group,
                 command=DALI_GO_TO_SCENE_COMMAND_BASE + scene)


def dmx_level(message_id, zone, universe_mask, channel, repeat, levels, fade_time_by_10ms=0):
    """Write DMX channel levels. ``levels`` is a list of 0-255 values written from
    ``channel``, tiled ``repeat`` times."""
    clamped = [_clamp(v, 0, 255) for v in levels]
    body = _uint(_X_ZONE, zone)
    body += _uint(_X_UNIVERSE_MASK, universe_mask)
    body += _uint(_X_CHANNEL, channel)
    body += _uint(_X_REPEAT, repeat)
    body += _packed_uint(_X_LEVEL, clamped)
    body += _uint(_X_FADE, fade_time_by_10ms)
    edidio = _uint(_F_MESSAGE_ID, message_id) + _embed(_F_DMX, body)
    return _frame(edidio)


def spektra_control(message_id, spektra_type, zone, index, action):
    """Start/stop/pause a SpektraPlus sequence, theme, or static scene."""
    body = _uint(_S_TYPE, spektra_type)
    body += _uint(_S_ZONE, zone)
    body += _uint(_S_INDEX, index)
    body += _uint(_S_ACTION, action)
    edidio = _uint(_F_MESSAGE_ID, message_id) + _embed(_F_SPEKTRA_CONTROL, body)
    return _frame(edidio)


def spektra_stop(message_id, zone, line_mask=0xFF):
    """Stop SpektraPlus playback on a zone and turn the output off."""
    trigger = _uint(_T_TYPE, TRIGGER_SPEKTRA_STOP_SEQ)
    trigger += _uint(_T_ZONE, zone)
    trigger += _uint(_T_LINE_MASK, line_mask)
    external = _embed(_E_TRIGGER, trigger)
    edidio = _uint(_F_MESSAGE_ID, message_id) + _embed(_F_EXTERNAL_TRIGGER, external)
    return _frame(edidio)


# Keep-alive / "Are You There" heartbeat frame.
KEEP_ALIVE = bytes([0xFF, 0xF6])


def line_mask(line):
    """1-based physical line number (1-4) -> single-bit line mask."""
    return 1 << (line - 1)
