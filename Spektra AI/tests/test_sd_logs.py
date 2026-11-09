"""SD binary log decoding (DAL_*.BIN / EVT_*.BIN) with synthetic files."""

import datetime as dt
import struct

import pytest

from edidio_spektra_ai import sd_logs as L

START = 836_000_000          # seconds since 2000-01-01 (controller local time)


def header(proto, line=0):
    return struct.pack("<IBBBBI", L.MAGIC, 1, line, proto, 0, START)


def dali(ms, line, direction, ftype, status, frame):
    return struct.pack("<IBBBBI", ms, line, direction, ftype, status, frame)


def event(etype, fields: bytes, ms=0, length=None):
    payload = struct.pack("<I", ms) + fields
    payload = payload.ljust(37, b"\x00")
    return bytes([etype, length if length is not None else 4 + len(fields)]) + payload


def test_header_and_time():
    h = L.parse_header(header(0, line=2))
    assert h["protocol"] == "DALI" and h["line"] == 3
    assert h["start"] == dt.datetime(2000, 1, 1) + dt.timedelta(seconds=START)
    with pytest.raises(ValueError):
        L.parse_header(b"\x00" * 12)


def test_dali_frames():
    data = header(0) + b"".join([
        dali(1500, 0, 0, 1, 0, 0x0B90),         # TX address 5 QUERY_STATUS
        dali(1520, 0, 1, 3, 0, 0x00FF),         # RX 8-bit YES
        dali(1600, 0, 0, 1, 245, 0xFE80),       # TX broadcast arc 128, COLLISION
        dali(1700, 0, 1, 2, 0, 0),              # RX no reply (not an error)
        dali(1800, 0, 0, 1, 0, 0x8364),         # group 1 ADD_TO_GROUP_4
        dali(1900, 0, 0, 1, 0, 0xA3AA),         # DTR0 170
        dali(2000, 0, 0, 2, 0, 0x03FE30),       # DALI-2 device 1 device-level command
        dali(2100, 0xFF, 0xFF, 0, 0, 12),       # meta: 12 dropped
        bytes(12),                              # unused slot
    ])
    h, es = L.decode(data)
    assert len(es) == 8
    assert es[0]["dir"] == "TX" and es[0]["text"] == "address 5 QUERY_STATUS"
    assert es[0]["time"] == h["start"] + dt.timedelta(milliseconds=1500)
    assert es[1]["text"].startswith("reply YES")
    assert es[2]["error"] and "broadcast arc 128" in es[2]["text"] and "COLLISION" in es[2]["text"]
    assert not es[3]["error"] and es[3]["text"] == "no reply"
    assert es[4]["text"] == "group 1 ADD_TO_GROUP_4"
    assert es[5]["text"] == "DTR 170"
    assert es[6]["text"].startswith("device 1 device ")
    assert es[7]["dir"] == "META" and es[7]["error"] and "12 entries not logged" in es[7]["text"]
    assert "L1 TX" in L.format_entry(es[0]) and "SYS META" in L.format_entry(es[7])


def test_dali2_event_frame():
    # motion instance-type 3, instance scheme (bit23=1, bit22=0, bit15=1), info 0x003
    frame = (1 << 23) | (2 << 16) | (1 << 15) | (3 << 10) | 0x003
    assert L.describe_24(frame) == "EVENT motion instance 2: movement+occupied (info 0x003)"
    # device scheme (bit23=0, bit15=0): address 1, type 3 motion, info 0x00C
    assert L.describe_24(0x020C0C).startswith("EVENT device 1 (motion): repeat")


def test_latest_first_and_logmeta():
    names = ["EVT_0656.BIN", "EVT_1575.BIN", "EVT_0999.BIN", "EVT_9999.BIN"]
    assert L.latest_first(names)[0] == "EVT_9999.BIN"
    # numbering wrapped: current is 656, so 999 and 1575 are older, 9999 is oldest
    assert L.latest_first(names, current=656) == ["EVT_0656.BIN", "EVT_9999.BIN",
                                                  "EVT_1575.BIN", "EVT_0999.BIN"]
    import zlib
    body = struct.pack("<IBBH", L.LOGMETA_MAGIC, 3, 11, 0)
    for i in range(11):
        body += struct.pack("<HHIHH", 977 if i == 3 else 656 if i == 10 else 1, 1, 0, 5, 0)
    meta = L.parse_logmeta(body + struct.pack("<I", zlib.crc32(body)))
    assert meta["DAL"]["current"] == 977 and meta["EVT"]["current"] == 656
    assert meta["EVT"]["files"] == 5
    assert L.parse_logmeta(body + bytes(4)) == {}           # bad CRC


def test_signed_timestamp():
    data = header(0) + dali(0xFFFFF830, 0, 0, 1, 0, 0x0B90)   # -2000 ms
    h, es = L.decode(data)
    assert es[0]["time"] == h["start"] - dt.timedelta(seconds=2)


def test_events():
    data = header(2) + b"".join([
        event(1, bytes([17, 0, 3, 0, 64, 254, 1]), ms=10),      # GPIO latch high
        event(2, bytes([0, 1, 1, 1]) + struct.pack("<H", 320), ms=20),
        event(3, bytes([2, 0, 1, 0, 0, 200]), ms=30),
        event(4, bytes([4, 1, 0, 0, 0, 1]), ms=40),
        event(5, bytes([9, 3, 3, 0]) + bytes([192, 168, 1, 50]) + struct.pack("<H", 0)
              + bytes(6), ms=50),
        event(5, bytes([7, 0xFF, 0, 1]) + bytes([10, 0, 0, 2]) + struct.pack("<H", 5000)
              + bytes(6), ms=55),
        event(6, bytes([0x05, 0]), ms=60),                       # power-on + watchdog
        event(7, bytes([4, 10, 0, 0, 9]) + struct.pack("<H", 443) + bytes(6) + bytes([12]),
              ms=70),                                            # TLS connect rejected
        event(8, bytes([1, 1, 1, 3]), ms=80),
        event(0xFF, bytes([0]) + struct.pack("<8I", 0, 2, 0, 0, 0, 0, 0, 1), ms=90,
              length=33),
        bytes(39),
    ])
    h, es = L.decode(data)
    assert h["protocol"] == "events" and len(es) == 10
    t = [e["text"] for e in es]
    assert t[0].startswith("input 17 (GPIO) latched high -> ")
    assert t[1].startswith("sensor 0 occupied") and "lux 320" in t[1]
    assert t[2].startswith("list 3 step 1 (state 1)")
    assert t[3].startswith("schedule 4 end")
    assert t[4] == "profile switched to 3"
    assert t[5] == "schedules (item all) changed via network by 10.0.0.2:5000 [profile 1]"
    assert t[6] == "boot (power-on, watchdog) [profile 0]" and es[6]["error"]
    assert "REJECTED (no free slot)" in t[7] and es[7]["error"]
    assert t[8] == "Spektra zone 1: start sequence 3"
    assert t[9] == "3 events not logged (sensor 2, spektra 1)" and es[9]["error"]


def test_select_and_summary():
    data = header(0) + dali(0, 0, 0, 1, 0, 0x0B90) + dali(60_000, 0, 0, 1, 242, 0x0B90)
    h, es = L.decode(data)
    assert len(L.select(es, errors_only=True)) == 1
    assert len(L.select(es, text="timeout")) == 1
    assert len(L.select(es, since=h["start"] + dt.timedelta(seconds=30))) == 1
    assert "2 entries" in L.summarise(h, es) and "1 flagged" in L.summarise(h, es)
