"""Undo for confirmed writes.

Before a confirmed write is sent, the slots it overwrites are read. A config read
answers with the same protobuf message the write sends (a SpektraSequenceConfigMessage
for a sequence, an InputMultiMessage for a profile's inputs, ...), so the undo frame is
the controller's own reply re-sent under a new message id: nothing goes through the
.spektra dict, so nothing can be lost in a mapping.

Covered: sequences, themes, zones, schedules, sensors, inputs, outputs. The save frames
that follow a write (zone SAVE, DEVICE_SAVE) are repeated. Anything else (DALI gear,
lists, logic, line types, multi-step jobs) is reported as not undoable rather than
half-undone.
"""
from __future__ import annotations

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb
from edidio_control_py import EdidioClient, ReadType, SpektraTargetType

# SpektraPlus marks a deleted sequence/theme slot with this title; the firmware keeps the slot.
DELETION_MARKER_NAME = "!DELETED!"

_SAVE_KINDS = ("spektra_control", "external_trigger")


def _decode(frame: bytes):
    msg = pb.EdidioMessage()
    msg.ParseFromString(frame[3:])
    return msg


def _frame(msg) -> bytes:
    body = msg.SerializeToString()
    return bytes([0xCD, len(body) >> 8, len(body) & 0xFF]) + body


def _rewrap(kind: str, payload, message_id: int) -> bytes:
    msg = pb.EdidioMessage(message_id=message_id)
    getattr(msg, kind).CopyFrom(payload)
    return _frame(msg)


def _is_save(msg) -> bool:
    kind = msg.WhichOneof("payload")
    if kind == "spektra_control":
        return msg.spektra_control.action == pb.SpektraActionType.SAVE
    if kind == "external_trigger":
        return msg.external_trigger.trigger.type == pb.TriggerType.DEVICE_SAVE
    return False


def _label(kind: str, msg) -> str:
    p = getattr(msg, kind)
    # 1-based for people, with the 0-based index the tools take (as elsewhere).
    return {"spektra_sequence": lambda: f"sequence {p.index + 1} (index {p.index})",
            "spektra_theme": lambda: f"theme {p.index + 1} (index {p.index})",
            "spektra_settings": lambda: f"zone {p.zone + 1}",
            "alarm": lambda: f"schedule {p.index + 1} (index {p.index})",
            "sensor": lambda: f"sensor {p.index + 1} (profile {p.profile + 1})",
            "inputs": lambda: f"inputs (profile {p.profile + 1})",
            "outputs": lambda: f"outputs (profile {p.profile + 1})"}.get(kind, lambda: kind)()


async def _current(controller, kind: str, msg):
    """The controller's current copy of what `msg` overwrites, as (payload, note), or
    (None, reason) when it cannot be read back."""
    p = getattr(msg, kind)
    client = controller._require()

    async def read_device(read_type, index=0, profile=0):
        return await client.request(EdidioClient.create_read_device_message(
            controller._next_id(), read_type, index, 0, profile))

    if kind in ("spektra_sequence", "spektra_theme"):
        target = SpektraTargetType.SEQUENCE if kind == "spektra_sequence" else SpektraTargetType.THEME
        reply = await controller._read_spektra(target, p.index)
        if reply.WhichOneof("payload") == kind:
            return getattr(reply, kind), ""
        # An empty slot: undo writes SpektraPlus's deletion marker (that title, no
        # colours, defaults elsewhere), which every reader treats as an empty slot.
        return type(p)(index=p.index, title=DELETION_MARKER_NAME), \
            "was empty - undo marks it deleted"
    if kind == "spektra_settings":
        reply = await controller._read_spektra(SpektraTargetType.SETTINGS, p.zone)
        return (reply.spektra_settings, "") if reply.WhichOneof("payload") == kind else (
            None, "could not read the zone")
    if kind == "alarm":
        reply = await read_device(ReadType.ALARMS)
        which = reply.WhichOneof("payload")
        alarms = list(reply.alarms.alarm) if which == "alarms" else [reply.alarm] if which == "alarm" else []
        hit = next((a for a in alarms if a.index == p.index), None)
        return (hit, "") if hit is not None else (None, "could not read the schedule")
    if kind == "sensor":
        reply = await read_device(ReadType.SENSOR, p.index, p.profile)
        return (reply.sensor, "") if reply.WhichOneof("payload") == "sensor" else (
            None, "could not read the sensor")
    if kind in ("inputs", "outputs"):
        reply = await read_device(ReadType.INPUTS if kind == "inputs" else ReadType.OUTPUTS,
                                  0, p.profile)
        return (getattr(reply, kind), "") if reply.WhichOneof("payload") == kind else (
            None, f"could not read the {kind}")
    return None, "not undoable"


async def snapshot(controller, frames: list) -> dict:
    """Read what `frames` will overwrite. Returns {"frames": [...] | None,
    "covers": [labels], "missing": [labels + reason]}. `frames` is None when any
    config write in the batch cannot be restored (no partial undo)."""
    restore, covers, missing = [], [], []
    for frame in frames:
        msg = _decode(frame)
        kind = msg.WhichOneof("payload")
        if _is_save(msg):
            continue                                  # re-added at the end
        current, note = await _current(controller, kind, msg)
        label = _label(kind, msg)
        if current is None:
            missing.append(f"{label}: {note}")
            continue
        restore.append((kind, current))
        covers.append(f"{label}{f' ({note})' if note else ''}")
    saves = [_decode(f) for f in frames if _is_save(_decode(f))]
    if missing or not restore:
        return {"frames": None, "covers": covers, "missing": missing}
    out = [_rewrap(k, p, controller._next_id()) for k, p in restore]
    out += [_rewrap(m.WhichOneof("payload"), getattr(m, m.WhichOneof("payload")),
                    controller._next_id()) for m in saves]
    return {"frames": out, "covers": covers, "missing": missing}
