"""DALI control-gear settings (IEC 62386-102): power-on, system-failure, min/max and
physical-min levels, fade time and rate, extended fade - and the 16 scene levels.
Read back with queries; written as DTR0 + "store DTR as ..." sent twice.

Targets: a short address 0-63, a group (64+g) or broadcast (255).
"""

from __future__ import annotations

import asyncio

from edidio_control_py._v2 import eDS10_v2_pb2 as pb

from . import v2

MASK = 255
PACE = 0.04                       # seconds between config frames (bus speed)

# Queries (address byte, opcode) - each answers one byte.
Q = {"actual_level": 0xA0, "max_level": 0xA1, "min_level": 0xA2, "power_on_level": 0xA3,
     "system_failure_level": 0xA4, "fade": 0xA5, "physical_min": 0x9A,
     "extended_fade": 0xA8}
Q_SCENE_BASE = 0xB0               # + scene 0-15; 255 = not in the scene

# "Store DTR0 as ..." configuration commands (sent twice).
STORE = {"max_level": 0x2A, "min_level": 0x2B, "system_failure_level": 0x2C,
         "power_on_level": 0x2D, "fade_time": 0x2E, "fade_rate": 0x2F,
         "extended_fade": 0x30}
STORE_SCENE_BASE, REMOVE_SCENE_BASE = 0x40, 0x50

# Fade time codes (s) and fade rate codes (steps/s), IEC 62386-102 tables.
FADE_TIME = {0: 0.0, 1: 0.7, 2: 1.0, 3: 1.4, 4: 2.0, 5: 2.8, 6: 4.0, 7: 5.7, 8: 8.0,
             9: 11.3, 10: 16.0, 11: 22.6, 12: 32.0, 13: 45.3, 14: 64.0, 15: 90.5}
FADE_RATE = {1: 358, 2: 253, 3: 179, 4: 127, 5: 89.4, 6: 63.3, 7: 44.7, 8: 31.6,
             9: 22.4, 10: 15.8, 11: 11.2, 12: 7.9, 13: 5.6, 14: 4.0, 15: 2.8}
_EXT_MULT = {0: 0.0, 1: 0.1, 2: 1.0, 3: 10.0, 4: 60.0}   # seconds per base step


def target_byte(target: int, *, query: bool = False) -> int:
    """0-63 short address, 64-79 group, 255 broadcast -> the command address byte."""
    if 0 <= target <= 63:
        return (target << 1) | 1
    if 64 <= target <= 79:
        return 0x80 | ((target - 64) << 1) | 1
    if target == 255 and not query:
        return 0xFF
    raise ValueError("target: address 0-63, group 64-79" + ("" if query else " or broadcast 255"))


def extended_fade_code(seconds: float) -> int:
    """Seconds -> extended fade byte (base 1-16 x multiplier); 0 = off."""
    if seconds <= 0:
        return 0
    best = None
    for m, unit in _EXT_MULT.items():
        if not unit:
            continue
        for base in range(1, 17):
            err = abs(base * unit - seconds)
            if best is None or err < best[0]:
                best = (err, (m << 4) | (base - 1))
    return best[1]


def extended_fade_seconds(code: int) -> float:
    m, base = (code >> 4) & 0x07, (code & 0x0F) + 1
    return round(base * _EXT_MULT.get(m, 0), 2)


def nearest_code(table: dict, value: float) -> int:
    return min(table, key=lambda k: abs(table[k] - value))


async def _frame(ctrl, line, frame16, reply):
    field = {"frame_16_bit_reply": frame16} if reply else {"frame_16_bit": frame16}
    r = await v2.request(ctrl._require(), pb.EdidioMessage(
        message_id=ctrl._next_id(),
        dali_message=pb.DALIMessage(line_mask=1 << (line - 1), **field)))
    if not reply:
        return None
    if r.WhichOneof("payload") != "dali_query":
        return None
    q = r.dali_query
    if q.dali_flag != pb.DALIRXStatusFlag.RECEIVED_8_BIT_FRAME:
        return None
    return q.response_data.uint_data


async def query(ctrl, line: int, address: int, opcode: int, retries: int = 3):
    for _ in range(retries + 1):
        v = await _frame(ctrl, line, (target_byte(address, query=True) << 8) | opcode, True)
        if v is not None:
            return v
    return None


async def store(ctrl, line: int, target: int, opcode: int, value: int | None) -> None:
    """DTR0 = value (if given), then the configuration command twice (paced)."""
    if value is not None:
        await _frame(ctrl, line, 0xA300 | (value & 0xFF), False)
        await asyncio.sleep(PACE)
    frame = (target_byte(target) << 8) | opcode
    for _ in range(2):
        await _frame(ctrl, line, frame, False)
        await asyncio.sleep(PACE)


async def read_settings(ctrl, line: int, address: int) -> dict:
    raw = {k: await query(ctrl, line, address, op) for k, op in Q.items()}
    out = {k: raw[k] for k in ("actual_level", "max_level", "min_level", "physical_min",
                               "power_on_level", "system_failure_level")}
    fade = raw.get("fade")
    if fade is not None:
        out["fade_time_code"], out["fade_rate_code"] = fade >> 4, fade & 0x0F
        out["fade_time_s"] = FADE_TIME.get(fade >> 4)
        out["fade_rate_steps_s"] = FADE_RATE.get(fade & 0x0F)
    if raw.get("extended_fade") is not None:
        out["extended_fade_s"] = extended_fade_seconds(raw["extended_fade"])
    return out


async def read_scenes(ctrl, line: int, address: int) -> list:
    """Scene 0-15 levels; None = not in the scene (255) or no reply."""
    out = []
    for s in range(16):
        v = await query(ctrl, line, address, Q_SCENE_BASE + s)
        out.append(None if v in (None, MASK) else v)
    return out


def describe_level(v) -> str:
    if v is None:
        return "?"
    return "last level" if v == MASK else str(v)
