"""Event recorder: a background process that keeps a controller's live events on disk
while no MCP session is running.

    python -m edidio_spektra_ai.recorder --host 192.168.1.50 [--tls] [--name bench]

It subscribes to the controller's event stream (firmware 1.4.0+) on its own
connection, appends every event to a JSON-lines file per day, reconnects by itself,
and keeps a status file. The MCP tools recorder_start / recorder_status /
recorder_stop / recorded_events drive it; it can also run as a service (Task
Scheduler, systemd, launchd) with the same command line.

Layout, under the recordings folder (SPEKTRA_AI_RECORDINGS, default
~/.spektra_ai/recordings):
    <name>/events-YYYY-MM-DD.jsonl   one event per line (local date)
    <name>/status.json               state, refreshed every few seconds
    <name>/recorder.log              the process's own log
    <name>/stop                      created to ask it to stop
Each line is the decoded event plus "t" (local time, ISO) and "host". Lines with
kind "recorder" mark when recording started, connected, lost the connection and
stopped, so gaps are visible.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import logging
import os
import re
import struct
import sys
import time
from pathlib import Path

ALL_CATEGORIES = ("inputs", "sensors", "triggers", "dali", "schedule", "lists", "config",
                  "network", "event")
HEARTBEAT = 5.0           # seconds between status refreshes
STALE = 30.0              # a status older than this means the recorder is not running
_LOGGER = logging.getLogger("spektra_ai.recorder")


def recordings_dir() -> Path:
    return Path(os.environ.get("SPEKTRA_AI_RECORDINGS")
                or Path.home() / ".spektra_ai" / "recordings")


def safe_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()).strip("._")
    if not n:
        raise ValueError("recorder name is empty")
    return n


def day_file(folder: Path, day: dt.date) -> Path:
    return folder / f"events-{day:%Y-%m-%d}.jsonl"


# --- status ------------------------------------------------------------------------

def read_status(folder: Path) -> dict:
    try:
        st = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    st["alive"] = (st.get("state") not in ("stopped", "failed")
                   and time.time() - st.get("heartbeat", 0) < STALE)
    return st


def list_recorders(root: Path | None = None) -> list:
    root = root or recordings_dir()
    if not root.is_dir():
        return []
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        st = read_status(d)
        files = sorted(d.glob("events-*.jsonl"))
        st.update(name=d.name, folder=str(d), files=len(files),
                  bytes=sum(f.stat().st_size for f in files),
                  first_day=files[0].stem[7:] if files else None,
                  last_day=files[-1].stem[7:] if files else None)
        out.append(st)
    return out


# --- reading back ------------------------------------------------------------------

def _trig(a) -> str:
    if not isinstance(a, dict):
        return ""
    from .device_log import TRIGGER_NAMES
    t = a.get("type")
    name = TRIGGER_NAMES.get(t, t) if isinstance(t, int) else t
    return f" -> {name} target {a.get('target')} value {a.get('value')}"


def describe(e: dict) -> str:
    """One readable line for a recorded event."""
    k = e.get("kind")
    if k == "recorder":
        return f"[recorder] {e.get('note', '')}"
    if k == "dali":
        from . import sd_logs
        line = int(e.get("line") or 0)                 # the stream's lines are 0-based
        raw = struct.pack("<iBBBBI", 0, line,
                          int(e.get("direction") or 0), int(e.get("frame_type") or 0),
                          int(e.get("status") or 0), int(e.get("frame") or 0) & 0xFFFFFFFF)
        d = sd_logs.decode_dali_entry(raw)
        return (f"DALI L{line + 1} {d['dir']} {'!! ' if d['error'] else ''}"
                f"{d['text']}")
    if k == "input":
        return f"input {e.get('index', 0) + 1} press {e.get('press')}{_trig(e.get('action'))}"
    if k == "sensor":
        return (f"sensor {e.get('index', 0) + 1}: motion {e.get('motion')}, light "
                f"{e.get('light')}, lux {e.get('lux')}")
    if k == "list":
        return (f"list {e.get('index', 0) + 1} step {e.get('step', 0) + 1} state "
                f"{e.get('state')}{_trig(e.get('action'))}")
    if k == "schedule":
        return (f"schedule {e.get('index', 0) + 1} {'end' if e.get('is_end') else 'start'}"
                f"{_trig(e.get('action'))}")
    if k == "config":
        by = f" by {e['client_ip']}" if e.get("client_ip") else ""
        return (f"config: {e.get('what')} (item {e.get('item')}) changed via "
                f"{e.get('source_name')}{by}")
    if k == "boot":
        return f"boot ({', '.join(e.get('causes') or []) or e.get('reset_cause')})"
    if k == "net":
        who = f" {e['client_ip']}:{e.get('client_port')}" if e.get("client_ip") else ""
        return f"network: {e.get('event_name')}{who}"
    if k == "spektra":
        return (f"Spektra zone {e.get('zone')}: action {e.get('action')} target "
                f"{e.get('target')} {e.get('index')}")
    if k == "command":
        return f"command from {e.get('source')} zone {e.get('zone')}{_trig(e.get('action'))}"
    if k == "text":
        return f"log: {e.get('text')}"
    rest = {x: v for x, v in e.items() if x not in ("t", "host", "seq", "at", "kind")}
    return f"{k}: {rest}"


def is_error(e: dict) -> bool:
    if e.get("kind") == "dali":
        return "!!" in describe(e)
    if e.get("kind") == "recorder":
        return "lost" in e.get("note", "") or "failed" in e.get("note", "")
    return e.get("kind") == "boot" and bool((e.get("reset_cause") or 0) & 0x0C)


def read_events(folder: Path, *, since: dt.datetime | None = None,
                until: dt.datetime | None = None, kind: str = "", text: str = "",
                errors_only: bool = False, last: int = 50) -> tuple:
    """(matching events, newest last, at most `last`; total matched)."""
    files = sorted(folder.glob("events-*.jsonl"))
    if since:
        files = [f for f in files if f.stem[7:] >= f"{since:%Y-%m-%d}"]
    if until:
        files = [f for f in files if f.stem[7:] <= f"{until:%Y-%m-%d}"]
    kinds = {k.strip().lower() for k in kind.split(",") if k.strip()}
    out, total = [], 0
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                t = e.get("t", "")
                if since and t < since.isoformat():
                    continue
                if until and t > until.isoformat():
                    continue
                if kinds and e.get("kind") not in kinds:
                    continue
                if errors_only and not is_error(e):
                    continue
                if text and text.lower() not in (t + " " + describe(e)).lower():
                    continue
                total += 1
                out.append(e)
                if len(out) > last:
                    out.pop(0)
    return out, total


def format_event(e: dict) -> str:
    return f"{e.get('t', '')[:23].replace('T', ' ')}  {describe(e)}"


# --- the recorder process -----------------------------------------------------------

class Recorder:
    def __init__(self, host: str, port: int, use_tls: bool, name: str, folder: Path,
                 categories=ALL_CATEGORIES, keep_days: int = 30):
        self.host, self.port, self.use_tls = host, port, use_tls
        self.name, self.folder = name, folder
        self.categories, self.keep_days = tuple(categories), keep_days
        self.count, self.last_event, self.state, self.error = 0, None, "starting", ""
        self.firmware, self.started = "", dt.datetime.now().isoformat(timespec="seconds")
        self.reconnects = 0
        self._stream = None
        self._was_connected = False

    # file output
    def write(self, e: dict) -> None:
        now = dt.datetime.now()
        e = {k: v for k, v in e.items() if k != "at"}
        e["t"] = now.isoformat(timespec="milliseconds")
        e["host"] = self.host
        with open(day_file(self.folder, now.date()), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(e, default=str) + "\n")
        if e.get("kind") != "recorder":
            self.count += 1
            self.last_event = e["t"]

    def note(self, text: str) -> None:
        self.write({"kind": "recorder", "note": text})

    def write_status(self) -> None:
        st = {"name": self.name, "host": self.host, "port": self.port, "tls": self.use_tls,
              "pid": os.getpid(), "state": self.state, "error": self.error,
              "firmware": self.firmware, "started": self.started, "events": self.count,
              "last_event": self.last_event, "reconnects": self.reconnects,
              "categories": list(self.categories), "heartbeat": time.time()}
        tmp = self.folder / "status.json.tmp"
        tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
        os.replace(tmp, self.folder / "status.json")

    def prune(self) -> None:
        if self.keep_days <= 0:
            return
        cut = f"{dt.date.today() - dt.timedelta(days=self.keep_days):%Y-%m-%d}"
        for f in self.folder.glob("events-*.jsonl"):
            if f.stem[7:] < cut:
                try:
                    f.unlink()
                except OSError:
                    pass

    async def _on_event(self, e: dict) -> None:
        self.write(e)

    async def _open_stream(self):
        """Check the firmware on a short control connection, then open the stream."""
        from .controller import SpektraController
        from .event_stream import EventStream
        from . import spektra_map
        ctrl = SpektraController()
        await ctrl.connect(self.host, self.port, self.use_tls)
        try:
            self.firmware = (await ctrl.read_system_counts()).get("firmware", "")
        finally:
            await ctrl.disconnect()
        if self.firmware and not spektra_map.version_gte(self.firmware, "1.4.0"):
            raise RuntimeError(f"firmware {self.firmware}: the event stream needs 1.4.0+")
        port = 443 if self.use_tls and self.port == 23 else self.port
        stream = EventStream(self.host, port, self.use_tls, on_event=self._on_event,
                             use_v2=True, reconnect_max=30.0,
                             client_factory=lambda: ctrl._factory(self.host, port,
                                                                  self.use_tls))
        await stream.start(self.categories)
        return stream

    def _stop_requested(self) -> bool:
        return (self.folder / "stop").exists()

    async def run(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        try:
            (self.folder / "stop").unlink()
        except OSError:
            pass
        self.note(f"recording started ({self.host}, {', '.join(self.categories)})")
        self.prune()
        delay, last_prune = 5.0, time.time()
        try:
            while not self._stop_requested():
                if self._stream is None or not self._stream.running:
                    self.state = "connecting"
                    self.write_status()
                    try:
                        self._stream = await self._open_stream()
                        self.state, self.error, delay = "recording", "", 5.0
                        self._was_connected = True
                        self.note(f"connected (firmware {self.firmware})")
                    except Exception as err:  # noqa: BLE001
                        self._stream = None
                        self.state, self.error = "retrying", str(err)
                        if "needs 1.4.0" in str(err):
                            self.state = "failed"
                            self.note(f"failed: {err}")
                            self.write_status()
                            return
                        _LOGGER.warning("connect failed: %s (retry in %.0fs)", err, delay)
                        await self._sleep(delay)
                        delay = min(delay * 2, 120.0)
                        continue
                connected = self._stream.connected
                if connected != self._was_connected:
                    if connected:
                        self.reconnects = self._stream.reconnects
                        self.note("connection restored")
                        self.state = "recording"
                    else:
                        self.note("connection lost - reconnecting")
                        self.state = "reconnecting"
                    self._was_connected = connected
                if time.time() - last_prune > 3600:
                    self.prune()
                    last_prune = time.time()
                self.write_status()
                await self._sleep(HEARTBEAT)
        finally:
            if self._stream is not None:
                try:
                    await self._stream.stop()
                except Exception:  # noqa: BLE001
                    pass
            self.state = "stopped" if self.state != "failed" else "failed"
            self.note("recording stopped")
            self.write_status()
            try:
                (self.folder / "stop").unlink()
            except OSError:
                pass

    async def _sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end and not self._stop_requested():
            await asyncio.sleep(min(1.0, end - time.time()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m edidio_spektra_ai.recorder",
                                 description="Record a controller's live events to disk.")
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=23)
    ap.add_argument("--tls", action="store_true", help="connect with TLS (port 443)")
    ap.add_argument("--name", default="", help="recording name (default: the host)")
    ap.add_argument("--dir", default="", help="recordings folder")
    ap.add_argument("--categories", default=",".join(ALL_CATEGORIES))
    ap.add_argument("--keep-days", type=int, default=30,
                    help="delete day files older than this (0 = keep all)")
    a = ap.parse_args(argv)
    name = safe_name(a.name or a.host)
    folder = (Path(a.dir) if a.dir else recordings_dir()) / name
    folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=folder / "recorder.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cats = [c.strip() for c in a.categories.split(",") if c.strip()]
    rec = Recorder(a.host, a.port, a.tls, name, folder, cats, a.keep_days)
    try:
        asyncio.run(rec.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
