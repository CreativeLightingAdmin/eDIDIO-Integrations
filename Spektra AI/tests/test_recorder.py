"""Background event recorder: files, status, read-back and descriptions (no controller)."""

import asyncio
import datetime as dt
import json
import time

from edidio_spektra_ai import recorder as R


class FakeStream:
    def __init__(self, on_event):
        self.on_event, self.running, self.connected, self.reconnects = on_event, True, True, 0

    async def stop(self):
        self.running = False


def make(tmp_path):
    rec = R.Recorder("10.0.0.9", 23, False, "bench", tmp_path / "bench", keep_days=2)
    rec.folder.mkdir(parents=True)
    return rec


def test_write_and_read_back(tmp_path):
    rec = make(tmp_path)
    rec.note("recording started")
    rec.write({"kind": "input", "index": 2, "press": 0, "at": 1.0,
               "action": {"type": 0, "target": 64, "value": 254}})
    rec.write({"kind": "dali", "line": 0, "direction": 0, "frame_type": 1, "status": 245,
               "frame": 0xFE80})
    rec.write({"kind": "sensor", "index": 0, "motion": 1, "light": 0, "lux": 300})
    assert rec.count == 3
    lines = R.day_file(rec.folder, dt.date.today()).read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[1])
    assert first["host"] == "10.0.0.9" and "at" not in first and "t" in first
    events, total = R.read_events(rec.folder, last=10)
    assert total == 4
    text = [R.describe(e) for e in events]
    assert text[0] == "[recorder] recording started"
    assert text[1].startswith("input 3 press 0 -> ") and "target 64 value 254" in text[1]
    assert text[2] == "DALI L1 TX !! broadcast arc 128 [COLLISION]"
    assert text[3] == "sensor 1: motion 1, light 0, lux 300"
    assert R.read_events(rec.folder, errors_only=True)[1] == 1
    assert R.read_events(rec.folder, kind="sensor,input")[1] == 2
    assert R.read_events(rec.folder, text="collision")[1] == 1
    ev, tot = R.read_events(rec.folder, last=2)
    assert tot == 4 and len(ev) == 2 and ev[-1]["kind"] == "sensor"
    future = dt.datetime.now() + dt.timedelta(hours=1)
    assert R.read_events(rec.folder, since=future)[1] == 0


def test_status_and_listing(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEKTRA_AI_RECORDINGS", str(tmp_path))
    rec = make(tmp_path)
    rec.state = "recording"
    rec.write({"kind": "boot", "reset_cause": 0x04, "causes": ["watchdog"]})
    rec.write_status()
    st = R.read_status(rec.folder)
    assert st["alive"] and st["events"] == 1 and st["host"] == "10.0.0.9"
    (rec.folder / "status.json").write_text(json.dumps(dict(st, heartbeat=time.time() - 99)))
    assert not R.read_status(rec.folder)["alive"]
    [r] = R.list_recorders()
    assert r["name"] == "bench" and r["files"] == 1
    assert R.is_error(json.loads(R.day_file(rec.folder, dt.date.today())
                                 .read_text().splitlines()[0]))


def test_prune(tmp_path):
    rec = make(tmp_path)
    old = R.day_file(rec.folder, dt.date.today() - dt.timedelta(days=5))
    old.write_text("{}\n")
    keep = R.day_file(rec.folder, dt.date.today())
    keep.write_text("{}\n")
    rec.prune()
    assert not old.exists() and keep.exists()


def test_run_loop_stops_on_request(tmp_path, monkeypatch):
    rec = make(tmp_path)
    monkeypatch.setattr(R, "HEARTBEAT", 0.05)

    async def fake_open():
        rec.firmware = "1.6.3"
        return FakeStream(rec._on_event)
    rec._open_stream = fake_open

    async def go():
        task = asyncio.ensure_future(rec.run())
        await asyncio.sleep(0.2)
        await rec._stream.on_event({"kind": "net", "event_name": "TCP_CONNECT"})
        rec._stream.connected = False
        await asyncio.sleep(0.2)
        (rec.folder / "stop").write_text("stop")
        await asyncio.wait_for(task, 5)
    asyncio.run(go())
    notes = [R.describe(e) for e in R.read_events(rec.folder, kind="recorder")[0]]
    assert notes[0].startswith("[recorder] recording started")
    assert "[recorder] connected (firmware 1.6.3)" in notes
    assert "[recorder] connection lost - reconnecting" in notes
    assert notes[-1] == "[recorder] recording stopped"
    assert R.read_status(rec.folder)["state"] == "stopped"
    assert R.read_events(rec.folder, kind="net")[1] == 1


def test_safe_name():
    assert R.safe_name("192.168.1.5") == "192.168.1.5"
    assert R.safe_name("Plant room / A") == "Plant_room_A"
