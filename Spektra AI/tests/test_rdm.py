"""RDM (ANSI E1.20): UIDs, DEVICE_INFO parsing, and details/describe (requests replaced)."""
import asyncio

import pytest

from edidio_spektra_ai import rdm as R


def test_uid_text_and_parse_round_trip():
    uid = 0x4C55_0001_E240
    assert R.uid_text(uid) == "4C55:0001E240"           # manufacturer : device
    assert R.parse_uid("4C55:0001E240") == uid
    assert R.parse_uid("4c55-0001e240") == uid and R.parse_uid(uid) == uid


def test_line_mask():
    assert [R.line_mask(n) for n in (1, 2, 4)] == [1, 2, 8]


DEVICE_INFO = bytes([0x01, 0x00,  0x12, 0x34,  0x05, 0x09,  0, 0, 1, 2,  0x00, 0x08,
                     2, 3,  0x00, 0x2A,  0x00, 0x00,  0])


def test_parse_device_info():
    d = R.parse_device_info(DEVICE_INFO)
    assert d == {"rdm_version": 0x0100, "model_id": 0x1234, "category": 0x0509,
                 "software_version": 0x0102, "footprint": 8, "personality": 2,
                 "personality_count": 3, "start_address": 42, "sub_devices": 0, "sensors": 0}
    assert R.parse_device_info(DEVICE_INFO[:18]) == {}     # short reply


def test_details_and_describe(monkeypatch):
    replies = {R.PID_DEVICE_INFO: DEVICE_INFO,
               R.PID_MANUFACTURER_LABEL: b"Acme\x00junk", R.PID_DEVICE_MODEL_DESCRIPTION: b"Par 64",
               R.PID_DEVICE_LABEL: b"Stage left", R.PID_SOFTWARE_VERSION_LABEL: b"v1.2",
               R.PID_SUPPORTED_PARAMETERS: bytes([0x00, 0xF0, 0x10, 0x00])}

    async def fake_request(ctrl, line, uid, pid, *, set_=False, data=b""):
        if pid == R.PID_DMX_PERSONALITY_DESCRIPTION:
            n = data[0]
            return {"ok": True, "data": bytes([n, 0, 4 * n]) + f"Mode {n}".encode()}
        return {"ok": pid in replies, "data": replies.get(pid, b""), "error": "timeout"}
    monkeypatch.setattr(R, "request", fake_request)
    d = asyncio.run(R.details(None, 2, 0x4C550001E240))
    assert d["manufacturer"] == "Acme" and d["label"] == "Stage left"      # NUL-terminated
    assert d["supported_pids"] == [R.PID_DMX_START_ADDRESS, R.PID_IDENTIFY_DEVICE]
    assert [p["name"] for p in d["personalities"]] == ["Mode 1", "Mode 2", "Mode 3"]
    text = R.describe(d)
    assert "Acme Par 64 'Stage left' - DMX start 42, footprint 8 ch, personality 2/3" in text
    assert "     *2: Mode 2 (8 ch)" in text                 # the current personality


@pytest.mark.parametrize("addr", [0, 0xFFFF])
def test_unpatched_start_address(addr):
    d = dict(R.parse_device_info(DEVICE_INFO), uid="X", start_address=addr)
    assert "DMX start unpatched" in R.describe(d)


def test_describe_no_answer():
    assert "no answer to DEVICE_INFO (timeout)" in R.describe({"uid": "X", "error": "timeout"})
