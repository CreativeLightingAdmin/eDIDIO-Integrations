"""RDM (ANSI E1.20) over a controller DMX output line: discovery, GET/SET of the
standard parameters (device info, labels, DMX start address, personality,
identify), decoded the way SpektraPlus decodes them.

The line must be a DMX OUTPUT (not DMX-In). ``universe_mask`` is the line's bit
(line 1 -> 1, line 3 -> 4). Discovery can take several seconds, so the client's
timeout is raised while it runs.
"""

from __future__ import annotations

from edidio_control_py._v2 import eDS10_v2_pb2 as pb

from . import v2

GET, SET = 0x20, 0x30
PID_SUPPORTED_PARAMETERS = 0x0050
PID_DEVICE_INFO = 0x0060
PID_DEVICE_MODEL_DESCRIPTION = 0x0080
PID_MANUFACTURER_LABEL = 0x0081
PID_DEVICE_LABEL = 0x0082
PID_SOFTWARE_VERSION_LABEL = 0x00C0
PID_DMX_PERSONALITY = 0x00E0
PID_DMX_PERSONALITY_DESCRIPTION = 0x00E1
PID_DMX_START_ADDRESS = 0x00F0
PID_IDENTIFY_DEVICE = 0x1000
PID_LAMP_HOURS = 0x0401
PID_DEVICE_HOURS = 0x0400

PID_NAMES = {0x0050: "SUPPORTED_PARAMETERS", 0x0051: "PARAMETER_DESCRIPTION",
             0x0060: "DEVICE_INFO", 0x0080: "DEVICE_MODEL_DESCRIPTION",
             0x0081: "MANUFACTURER_LABEL", 0x0082: "DEVICE_LABEL", 0x0090: "FACTORY_DEFAULTS",
             0x00C0: "SOFTWARE_VERSION_LABEL", 0x00E0: "DMX_PERSONALITY",
             0x00E1: "DMX_PERSONALITY_DESCRIPTION", 0x00F0: "DMX_START_ADDRESS",
             0x0200: "SENSOR_DEFINITION", 0x0201: "SENSOR_VALUE", 0x0400: "DEVICE_HOURS",
             0x0401: "LAMP_HOURS", 0x1000: "IDENTIFY_DEVICE", 0x1010: "RESET_DEVICE"}


def line_mask(line: int) -> int:
    return 1 << (line - 1)


def uid_text(uid: int) -> str:
    return f"{(uid >> 32) & 0xFFFF:04X}:{uid & 0xFFFFFFFF:08X}"


def parse_uid(text) -> int:
    if isinstance(text, int):
        return text
    return int(str(text).replace(":", "").replace("-", "").strip(), 16)


async def discover(ctrl, line: int, *, timeout: float = 30.0) -> dict:
    """Find RDM responders on a DMX output line (up to 128 per pass; follows isNext)."""
    client = ctrl._require()
    old = getattr(client, "_timeout", None)
    client._timeout = max(timeout, old or 0)
    uids, err, is_next = [], 0, False
    try:
        for _ in range(8):
            r = await v2.request(client, pb.EdidioMessage(
                message_id=ctrl._next_id(),
                rdm_discovery=pb.RDMDiscoveryMessage(universe_mask=line_mask(line),
                                                     isNext=is_next)))
            if r.WhichOneof("payload") != "rdm_discovery_reply":
                raise RuntimeError(f"RDM discovery refused: {v2.ack_summary(r)}")
            d = r.rdm_discovery_reply
            err = d.error_code
            uids += [u for u in d.uid if u not in uids]
            if len(d.uid) < 128 or err:
                break
            is_next = True
    finally:
        if old is not None:
            client._timeout = old
    return {"line": line, "uids": uids, "error_code": err}


async def request(ctrl, line: int, uid: int, pid: int, *, set_: bool = False,
                  data: bytes = b"") -> dict:
    """One RDM GET/SET -> {ok, data(bytes)} or {ok: False, error}."""
    msg = pb.RDMMessage(universe_mask=line_mask(line), uid=uid, pid=pid,
                        getset=SET if set_ else GET, datalength=len(data), data=list(data))
    r = await v2.request(ctrl._require(),
                         pb.EdidioMessage(message_id=ctrl._next_id(), rdm_message=msg))
    which = r.WhichOneof("payload")
    if which == "rdm_response_message":
        resp = r.rdm_response_message
        return {"ok": True, "data": bytes(b & 0xFF for b in resp.data[:resp.datalength]),
                "pid": resp.pid}
    if which == "ack":
        ack = v2.ack_summary(r)
        # A SET is answered with a plain SUCCESS ack (no RDM payload to return).
        return {"ok": True, "data": b""} if ack["ok"] else {"ok": False, "error": ack}
    return {"ok": False, "error": which}


def _text(b: bytes) -> str:
    return b.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()


def parse_device_info(b: bytes) -> dict:
    if len(b) < 19:
        return {}
    return {"rdm_version": (b[0] << 8) | b[1], "model_id": (b[2] << 8) | b[3],
            "category": (b[4] << 8) | b[5],
            "software_version": int.from_bytes(b[6:10], "big"),
            "footprint": (b[10] << 8) | b[11], "personality": b[12],
            "personality_count": b[13], "start_address": (b[14] << 8) | b[15],
            "sub_devices": (b[16] << 8) | b[17], "sensors": b[18]}


async def details(ctrl, line: int, uid: int) -> dict:
    """Device info + labels + start address + personalities of one responder."""
    out = {"uid": uid_text(uid)}
    r = await request(ctrl, line, uid, PID_DEVICE_INFO)
    if not r["ok"]:
        out["error"] = r["error"]
        return out
    out.update(parse_device_info(r["data"]))
    for key, pid in (("manufacturer", PID_MANUFACTURER_LABEL),
                     ("model", PID_DEVICE_MODEL_DESCRIPTION), ("label", PID_DEVICE_LABEL),
                     ("software", PID_SOFTWARE_VERSION_LABEL)):
        rr = await request(ctrl, line, uid, pid)
        if rr["ok"]:
            out[key] = _text(rr["data"])
    rr = await request(ctrl, line, uid, PID_SUPPORTED_PARAMETERS)
    if rr["ok"]:
        d = rr["data"]
        out["supported_pids"] = [(d[i] << 8) | d[i + 1] for i in range(0, len(d) - 1, 2)]
    pers = []
    for n in range(1, (out.get("personality_count") or 0) + 1):
        rr = await request(ctrl, line, uid, PID_DMX_PERSONALITY_DESCRIPTION, data=bytes([n]))
        if rr["ok"] and len(rr["data"]) >= 3:
            d = rr["data"]
            pers.append({"id": d[0], "footprint": (d[1] << 8) | d[2], "name": _text(d[3:])})
    out["personalities"] = pers
    return out


def describe(d: dict) -> str:
    if d.get("error"):
        return f"  {d['uid']}: no answer to DEVICE_INFO ({d['error']})"
    addr = d.get("start_address")
    addr_txt = "unpatched" if addr in (0, 0xFFFF) else str(addr)
    rows = [f"  {d['uid']}: {d.get('manufacturer', '?')} {d.get('model', '?')}"
            + (f" '{d['label']}'" if d.get("label") else "")
            + f" - DMX start {addr_txt}, footprint {d.get('footprint')} ch, personality "
              f"{d.get('personality')}/{d.get('personality_count')}"
            + (f", software {d['software']}" if d.get("software") else "")]
    for p in d.get("personalities", []):
        mark = "*" if p["id"] == d.get("personality") else " "
        rows.append(f"     {mark}{p['id']}: {p['name']} ({p['footprint']} ch)")
    return "\n".join(rows)
