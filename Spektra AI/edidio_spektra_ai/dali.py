"""DALI commissioning, query and colour control (Phase 4).

Message builders + response decoders for talking to DALI control gear directly:
scan a line for present devices, query status/type, set arc levels, identify (blink) a
fixture, set DT8 colour (colour temperature, RGBWAF, xy), and run the addressing
(commissioning) sequence. Builders mirror SpektraPlus's DALI helpers
(``src/helpers/networkWriteMessages.ts``); decoders read the ``DALIQueryResponse`` the
firmware returns. DALI short addresses are 0-63.

Commissioning WRITES device addresses, so its tools go through preview -> confirm.
Verified offline against the protobuf; live verification needs a connected DALI line
(the reference bench is DMX-only).
"""

from __future__ import annotations

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb
from edidio_control_py import EdidioClient

from .spektra_map import _frame

# RX status flags that mean a device actually replied (vs. silence / error).
_RECEIVED_FLAGS = {
    pb.DALIRXStatusFlag.RECEIVED_8_BIT_FRAME,
    pb.DALIRXStatusFlag.RECEIVED_16_BIT_FRAME,
    pb.DALIRXStatusFlag.RECEIVED_24_BIT_FRAME,
}
_NO_FRAME = pb.DALIRXStatusFlag.NO_RECEIVED_FRAME

# DALI status byte bits (DALIStatusType) for decoding QUERY_STATUS.
_STATUS_BITS = [
    (0x01, "gear_failure"), (0x02, "lamp_failure"), (0x04, "lamp_on"),
    (0x08, "limit_error"), (0x10, "fade_running"), (0x20, "reset_state"),
    (0x40, "missing_short_address"), (0x80, "power_cycle_seen"),
]

MAX_SHORT_ADDRESS = 63


def line_mask(line: int) -> int:
    """1-based line number -> firmware line bitmask (1->1, 2->2, 3->4, 4->8)."""
    return 1 << (line - 1)


# --- read-only: query / scan ------------------------------------------------

def query_message(message_id: int, line: int, address: int, query: int,
                  arg: int | None = None) -> bytes:
    return EdidioClient.create_dali_message(
        message_id, line_mask(line), address, query=query,
        **({"arg": arg} if arg is not None else {}))


def decode_query(reply) -> dict:
    """Decode an EdidioMessage reply to a DALI query into a compact dict. The returned
    byte value lives in ``response_data.uint_data`` (per SpektraPlus's DALI helpers)."""
    if reply.WhichOneof("payload") != "dali_query":
        return {"responded": False, "raw": reply.WhichOneof("payload")}
    q = reply.dali_query
    flag = q.dali_flag
    return {"responded": flag in _RECEIVED_FLAGS,
            "flag": pb.DALIRXStatusFlag.Name(flag),
            "data": q.response_data.uint_data,
            "status_flags": list(q.status_flags.flags)}


def decode_status(data: int) -> dict:
    """Decode a DALI QUERY_STATUS byte into named flags."""
    return {name: bool(data & bit) for bit, name in _STATUS_BITS}


# --- control: levels + identify ---------------------------------------------

def dt8_control_message(message_id: int, line: int, address: int, type8: int,
                        dtr: list | None = None) -> bytes:
    """A single DT8 (Type 8) DALI message with an optional DTR payload (byte list)."""
    kwargs = {"type8": type8}
    if dtr is not None:
        kwargs["dtr"] = list(dtr)   # engine wraps this into a DTRPayloadMessage
    return EdidioClient.create_dali_message(message_id, line_mask(line), address, **kwargs)


def arc_message(message_id: int, line: int, address: int, level: int) -> bytes:
    """Set a DALI arc (brightness) level 0-254 via the custom ARC_LEVEL command."""
    return EdidioClient.create_dali_message(
        message_id, line_mask(line), address,
        custom_command=pb.CustomDALICommandType.DALI_ARC_LEVEL, arg=level)


# --- DT8 colour (mirror SpektraPlus DT8 sequences) --------------------------

def colour_temperature_messages(mid_fn, line: int, address: int, mirek: int) -> list:
    """DT8 Tc: set temp colour temperature (mirek, 16-bit little-endian) then ACTIVATE."""
    return [
        dt8_control_message(mid_fn(), line, address,
                            pb.Type8CommandType.SET_TEMP_COLOUR_TEMPERATURE,
                            dtr=[mirek & 0xFF, (mirek >> 8) & 0xFF]),
        dt8_control_message(mid_fn(), line, address, pb.Type8CommandType.ACTIVATE),
    ]


def rgbwaf_messages(mid_fn, line: int, address: int, rgb: list, waf: list,
                    arc_level: int, send_activate: bool = True) -> list:
    """DT8 RGBWAF: control(0x80) -> RGB dimlevels -> WAF dimlevels -> arc -> ACTIVATE."""
    msgs = [
        dt8_control_message(mid_fn(), line, address,
                            pb.Type8CommandType.SET_TEMP_RGBWAF_CONTROL, dtr=[0x80]),
        dt8_control_message(mid_fn(), line, address,
                            pb.Type8CommandType.SET_TEMP_RGB_DIMLEVEL, dtr=list(rgb)),
        dt8_control_message(mid_fn(), line, address,
                            pb.Type8CommandType.SET_TEMP_WAF_DIMLEVEL, dtr=list(waf)),
        arc_message(mid_fn(), line, address, arc_level),
    ]
    if send_activate:
        msgs.append(dt8_control_message(mid_fn(), line, address,
                                        pb.Type8CommandType.ACTIVATE))
    return msgs


def xy_messages(mid_fn, line: int, address: int, x: int, y: int) -> list:
    """DT8 xy: set temp X coord, Y coord (16-bit little-endian), then ACTIVATE."""
    return [
        dt8_control_message(mid_fn(), line, address,
                            pb.Type8CommandType.SET_TEMP_X_COORD,
                            dtr=[x & 0xFF, (x >> 8) & 0xFF]),
        dt8_control_message(mid_fn(), line, address,
                            pb.Type8CommandType.SET_TEMP_Y_COORD,
                            dtr=[y & 0xFF, (y >> 8) & 0xFF]),
        dt8_control_message(mid_fn(), line, address, pb.Type8CommandType.ACTIVATE),
    ]


# --- commissioning: addressing (WRITES device addresses) --------------------

def addressing_message(message_id: int, line: int, *, initialisation: bool,
                       readdress: bool = False, is24bit: bool = False) -> bytes:
    """Start (initialisation=True) or continue (False) DALI addressing on a line.
    readdress=True clears existing addresses (READDRESS_ALL) vs. addressing only new."""
    atype = (pb.DALIAddressingType.READDRESS_ALL if readdress
             else pb.DALIAddressingType.ADDRESS_NEW)
    msg = pb.DALIAddressingMessage(
        type=atype, line_mask=line_mask(line), is24Bit=is24bit,
        initialisation=initialisation)
    return _frame(message_id, dali_addressing_message=msg)


def decode_addressing(reply) -> dict:
    """Decode a DALI addressing reply: addressed a device / finished / error."""
    if reply.WhichOneof("payload") != "dali_addressing_message":
        return {"ok": False, "finished": False,
                "error": f"unexpected reply: {reply.WhichOneof('payload')}"}
    m = reply.dali_addressing_message
    err = m.error
    if err == pb.DALIAddressingError.NO_ERROR:
        return {"ok": True, "finished": False, "addressed": m.index, "error": None}
    if err == pb.DALIAddressingError.NO_NEW_DEVICE:
        return {"ok": True, "finished": True, "error": None}
    return {"ok": False, "finished": False,
            "error": pb.DALIAddressingError.Name(err)}


# --- memory banks (device identity for grouping channels into fixtures) -----
# 16-bit DALI special-command opcodes (IEC 62386-102; see SpektraPlus daliTypes.ts).
_DTR0_OPCODE = 0xA3
_DTR1_OPCODE = 0xC3

# Bank/location of the serial number (Bank 1, 0x09-0x10) — identical across all
# control gear (channels) of one physical driver, so it groups them into fixtures.
SERIAL_BANK = 1
SERIAL_START = 0x09
SERIAL_END = 0x10


def dtr_frame(message_id: int, line: int, opcode: int, value: int) -> bytes:
    """A broadcast 16-bit special-command frame (e.g. set DTR0/DTR1) — no reply."""
    return EdidioClient.create_dali_message(
        message_id, line_mask(line), 0, frame_16_bit=((opcode << 8) | value))


def read_dtr_query_message(message_id: int, line: int, address: int) -> bytes:
    """Query a gear's DTR0/1 content (after pointing DTR1:DTR0 at a memory byte)."""
    return EdidioClient.create_dali_message(
        message_id, line_mask(line), address, query=pb.DALIQueryType.DALI_QUERY_READ_DTR_0_1)


# --- DALI configuration: groups, scenes, fade time --------------------------
# Config commands are raw 16-bit frames and must be sent TWICE (IEC 62386-102).
# The engine's DALIMessage has no send_twice field, so the controller sends each
# config frame twice back-to-back.
ADD_TO_GROUP_BASE = 0x60      # +group (0-15)
REMOVE_FROM_GROUP_BASE = 0x70
STORE_SCENE_BASE = 0x40       # "store DTR0 as scene N" +scene (0-15)
REMOVE_SCENE_BASE = 0x50
SET_FADE_TIME_OPCODE = 0x2E   # uses DTR0 = fade-time code
_BROADCAST_CMD = 0xFF         # broadcast command address byte

# DALI standard fade times: code -> seconds (Tf = 0.5*sqrt(2^code); code 0 = none).
FADE_TIME_SECONDS = {0: 0.0, 1: 0.71, 2: 1.0, 3: 1.41, 4: 2.0, 5: 2.83, 6: 4.0,
                     7: 5.66, 8: 8.0, 9: 11.31, 10: 16.0, 11: 22.63, 12: 32.0,
                     13: 45.25, 14: 64.0, 15: 90.51}


def fade_time_to_code(seconds: float) -> int:
    """Nearest DALI fade-time code for a duration in seconds (e.g. 2.8 -> 5)."""
    return min(FADE_TIME_SECONDS, key=lambda c: abs(FADE_TIME_SECONDS[c] - seconds))


def _addr_cmd16(address: int, opcode: int) -> int:
    """16-bit frame for an addressed command: 0AAAAAA1 opcode."""
    return (((address << 1) | 1) << 8) | opcode


def _broadcast_cmd16(opcode: int) -> int:
    return (_BROADCAST_CMD << 8) | opcode


def _dtr0_16(value: int) -> int:
    return (_DTR0_OPCODE << 8) | value


def config_message(message_id: int, line: int, frame16: int) -> bytes:
    """Wrap a raw 16-bit DALI config frame in an EdidioMessage."""
    return EdidioClient.create_dali_message(
        message_id, line_mask(line), 0, frame_16_bit=frame16)


def add_to_group_frame16(address: int, group: int) -> int:
    return _addr_cmd16(address, ADD_TO_GROUP_BASE + group)


def remove_from_group_frame16(address: int, group: int) -> int:
    return _addr_cmd16(address, REMOVE_FROM_GROUP_BASE + group)


def store_scene_frame16(address: int, scene: int, *, broadcast: bool = False) -> int:
    op = STORE_SCENE_BASE + scene
    return _broadcast_cmd16(op) if broadcast else _addr_cmd16(address, op)


def set_fade_time_frame16(address: int, *, broadcast: bool = False) -> int:
    return (_broadcast_cmd16(SET_FADE_TIME_OPCODE) if broadcast
            else _addr_cmd16(address, SET_FADE_TIME_OPCODE))


def dtr0_set_frame16(value: int) -> int:
    return _dtr0_16(value)


def format_commission_report(total_addressed: int, groups: list,
                             expected_channels: int = 0,
                             expected_devices: int = 0) -> str:
    """Human-readable commissioning report: total channels + per-fixture grouping,
    with an expected-count check and a duplicate-serial caveat where relevant."""
    lines = [f"Addressed {total_addressed} DALI control gear (channels) on the line."]
    if expected_channels:
        mark = "OK" if total_addressed == expected_channels else "MISMATCH"
        lines[0] += f" Expected {expected_channels} - {mark}."
        if total_addressed < expected_channels:
            lines.append("  Some gear may still be unaddressed - try another pass, "
                         "or check wiring/power on the missing fixtures.")
    lines.append(f"Grouped into {len(groups)} device(s) by serial number:")
    for i, g in enumerate(groups):
        n = len(g["channels"])
        lines.append(f"  - device {i + 1} (serial {g['serial']}): "
                     f"{n} channel(s) @ {g['channels']}")
    if expected_devices and len(groups) != expected_devices:
        lines.append(f"NOTE: expected {expected_devices} physical device(s) but serial "
                     f"grouping found {len(groups)}. Drivers of the same model can share "
                     "a serial (or report none) - use identify (blink) to split a group "
                     "into physical fixtures.")
    return "\n".join(lines)


def remapping_message(message_id: int, line: int, from_address: int,
                      to_address: int, is24bit: bool = False) -> bytes:
    """Move a device from one short address to another."""
    msg = pb.DALIRemappingMessage(from_address=from_address, to_address=to_address,
                                  line_mask=line_mask(line), is24Bit=is24bit)
    return _frame(message_id, dali_remapping_message=msg)
