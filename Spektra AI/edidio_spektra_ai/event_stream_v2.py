"""Event Stream v2 (firmware >= 1.4.0): EventStreamMessage / tag 77.

Newer eDIDIO firmware replaced the legacy REGISTER-based EventMessage (tag 34) with
a subscribe-based Event Stream (`EventStreamMessage`, tag 77): the client sends
``{subscribe:true, category_mask, level_threshold}`` and the device pushes a
self-describing envelope (sequence, timestamps, and a typed ``entry`` oneof:
dali/input/sensor/spektra/command/net/…). This module encodes the subscribe frames
and decodes the pushed envelopes.

The message set is compiled from the current ``.proto`` into a **namespaced** module
(``_v2/eDS10_v2_pb2``, package ``edidiov2``) so its descriptors don't collide with the
engine's older protobuf in the shared pool. Verified live on firmware 1.5.7 (captured
real DALI MIN/MAX bus frames).
"""

from __future__ import annotations

from datetime import datetime

from ._v2 import eDS10_v2_pb2 as v2

# Log category bit positions (SpektraPlus eventStreamV2.ts EVENT_CATEGORIES), plus
# aliases so legacy category names (dali_command, triggers, …) map sensibly.
CATEGORY_BITS = {
    "sys": 0, "trigger": 1, "triggers": 1, "inputs": 2, "input": 2,
    "dali": 3, "dali_command": 3, "dali_arc": 3, "dali_24_frame": 3,
    "sensors": 4, "sensor": 4, "schedule": 5, "lists": 6, "list": 6,
    "config": 7, "network": 8, "sd": 9, "event": 10,
}
# Bit for the structured-event category (InputEvent/SensorEvent/SpektraEvent/… all
# arrive here) — always included so we never miss structured pushes.
_EVENT_BIT = 1 << 10
# Everything (bits 0-10). Structured events arrive under "event" (10); raw DALI bus
# frames under "dali" (3).
ALL_CATEGORIES_MASK = 0x7FF
DEFAULT_LEVEL_THRESHOLD = 2  # 0=ERR,1=WARN,2=INFO

# A few common 16-bit DALI command frames, for readable bus decoding.
_DALI_CMD_NAMES = {0x00: "OFF", 0x05: "MAX_LEVEL", 0x06: "MIN_LEVEL",
                   0x01: "FADE_UP", 0x02: "FADE_DOWN", 0x0A: "RECALL_MAX?"}


def categories_to_mask(categories) -> int:
    """Turn friendly category names into a bitmask. Always includes the structured-
    event category (where input/sensor/spektra/command events arrive). Empty/unknown
    input falls back to all categories."""
    mask = 0
    for c in categories or []:
        bit = CATEGORY_BITS.get(c)
        if bit is not None:
            mask |= 1 << bit
    if mask == 0:
        return ALL_CATEGORIES_MASK
    return mask | _EVENT_BIT


def _frame(body: bytes) -> bytes:
    return bytes([0xCD, (len(body) >> 8) & 0xFF, len(body) & 0xFF]) + body


def build_subscribe(category_mask: int = ALL_CATEGORIES_MASK,
                    level_threshold: int = DEFAULT_LEVEL_THRESHOLD,
                    message_id: int = 1) -> bytes:
    return _frame(v2.EdidioMessage(
        message_id=message_id,
        event_stream=v2.EventStreamMessage(
            subscribe=True, category_mask=category_mask,
            level_threshold=level_threshold)).SerializeToString())


def build_unsubscribe(message_id: int = 2) -> bytes:
    return _frame(v2.EdidioMessage(
        message_id=message_id,
        event_stream=v2.EventStreamMessage(subscribe=False)).SerializeToString())


def describe_dali_frame(frame: int, frame_type: int) -> str:
    """Best-effort human description of a raw DALI frame value."""
    if frame_type == 4 or frame <= 0xFFFF:      # 16-bit frame
        addr, data = (frame >> 8) & 0xFF, frame & 0xFF
        if addr == 0xFF:                         # broadcast command
            return f"broadcast {_DALI_CMD_NAMES.get(data, hex(data))}"
        if addr == 0xFE:
            return f"broadcast DAPC level {data}"
        if addr & 0x01:                          # command to short address
            return f"addr {(addr >> 1) & 0x3F} cmd {_DALI_CMD_NAMES.get(data, hex(data))}"
        return f"addr {(addr >> 1) & 0x3F} arc {data}"
    return f"frame 0x{frame:06X}"


def _trigger_info(t) -> dict:
    """Flatten a TriggerInfo sub-message to plain scalars (JSON-friendly)."""
    return {"type": t.trigger_type, "target": t.target_index,
            "value": t.value, "line_mask": t.line_mask}


def parse_edidio(data: bytes):
    """Parse framed body bytes into a v2 EdidioMessage (or None)."""
    msg = v2.EdidioMessage()
    try:
        msg.ParseFromString(data)
    except Exception:  # noqa: BLE001
        return None
    return msg


def is_event_stream(msg) -> bool:
    return msg is not None and msg.WhichOneof("payload") == "event_stream"


def decode(msg) -> dict | None:
    """Decode a v2 EdidioMessage(event_stream) into a compact dict, or None for the
    subscribe ACK / non-events."""
    es = msg.event_stream
    if es.ack:
        return None
    base = {"seq": es.sequence, "category": es.category, "level": es.level,
            "at": datetime.now().isoformat(timespec="seconds")}
    entry = es.WhichOneof("entry")
    if entry == "dali":
        d = es.dali
        base.update(kind="dali", line=d.line, direction=d.direction,
                    frame_type=d.frame_type, status=d.status, frame=d.frame,
                    decoded=describe_dali_frame(d.frame, d.frame_type))
    elif entry == "input":
        i = es.input
        base.update(kind="input", index=i.input_index, source=i.source,
                    press=i.press_type, action=_trigger_info(i.action),
                    dali_line=i.dali_line, dali_address=i.dali_address)
    elif entry == "sensor":
        s = es.sensor
        base.update(kind="sensor", index=s.sensor_index, motion=s.motion_state,
                    light=s.light_state, lux=s.lux_value,
                    dali_line=s.dali_line, dali_address=s.dali_address)
    elif entry == "spektra":
        s = es.spektra
        base.update(kind="spektra", zone=s.zone, action=s.action,
                    target=s.target, index=s.index)
    elif entry == "command":
        cmd = es.command
        base.update(kind="command", source=cmd.source, action=_trigger_info(cmd.action),
                    zone=cmd.zone)
    elif entry == "net":
        base.update(kind="net", event=es.net.event)
    elif entry == "text":
        base.update(kind="text", text=es.text)
    else:
        base.update(kind=entry or "unknown")
    return base
