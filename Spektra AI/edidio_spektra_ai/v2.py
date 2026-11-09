"""Requests in the current eDIDIO protocol (the engine's namespaced ``_v2`` module).

The engine's legacy ``eDS10_ProtocolBuffer_pb2`` predates most of the admin
diagnostics, the device log, Wi-Fi (ADDICT), the slot manifest and
``AckMessage.detail``. This module builds requests with the current proto and
re-reads the reply with it: ``EdidioClient.request`` parses with the legacy module
(enough to match ``message_id``) and protobuf keeps unknown fields, so serialising
that reply and parsing it as v2 recovers every field.
"""

from __future__ import annotations

from google.protobuf.json_format import MessageToDict

from edidio_control_py._v2 import eDS10_v2_pb2 as v2

ACK_NAMES = {v.number: v.name for v in v2.AckMessageType.DESCRIPTOR.values}
REJECT_NAMES = {v.number: v.name for v in v2.RejectReason.DESCRIPTOR.values}
_ERROR_ACKS = {"SUCCESS", "PARTIAL_SUCCESS"}


def frame(msg: "v2.EdidioMessage") -> bytes:
    """0xCD + 16-bit length + body, as every eDIDIO request is framed."""
    body = msg.SerializeToString()
    return bytes([0xCD, (len(body) >> 8) & 0xFF, len(body) & 0xFF]) + body


def to_v2(reply) -> "v2.EdidioMessage":
    """Re-read a reply parsed by the legacy module with the current proto."""
    out = v2.EdidioMessage()
    out.ParseFromString(reply.SerializeToString())
    return out


async def request(client, msg: "v2.EdidioMessage") -> "v2.EdidioMessage":
    return to_v2(await client.request(frame(msg)))


def admin(message_id: int, command: str, target: str, **payload) -> "v2.EdidioMessage":
    """An AdminMessage request, e.g. ``admin(1, "GET", "DALI_STATUS")``."""
    am = v2.AdminMessage(command=v2.AdminCommandType.Value(command),
                         target=v2.AdminPropertyType.Value(target), **payload)
    return v2.EdidioMessage(message_id=message_id, admin_message=am)


def ack_summary(reply) -> dict:
    """{ok, code[, reason]} for a reply; reason names the RejectReason from
    AckMessage.detail on a refused write (firmware 1.6.3 refuses values it cannot
    store instead of truncating them)."""
    msg = reply if isinstance(reply, v2.EdidioMessage) else to_v2(reply)
    which = msg.WhichOneof("payload")
    if which != "ack":
        return {"ok": True, "code": which or "no-payload"}
    code = ACK_NAMES.get(msg.ack.payload, str(msg.ack.payload))
    out = {"ok": code == "SUCCESS", "code": code}
    detail = msg.ack.detail
    if detail and code not in _ERROR_ACKS:
        out["reason"] = REJECT_NAMES.get(detail, f"reason {detail}")
    elif detail and code == "PARTIAL_SUCCESS":
        out["lines_ok_mask"] = detail
    return out


def to_dict(msg) -> dict:
    """Protobuf -> plain dict (enum names, snake_case field names, defaults kept)."""
    try:
        return MessageToDict(msg, preserving_proto_field_name=True,
                             always_print_fields_with_no_presence=True)
    except TypeError:  # protobuf < 5.26 names the option differently
        return MessageToDict(msg, preserving_proto_field_name=True,
                             including_default_value_fields=True)
