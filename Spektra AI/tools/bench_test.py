"""Repeatable bench test: runs the Spektra AI tools against a real controller and
reports PASS / FAIL / SKIP for each, with the tool's output.

    python tools/bench_test.py --host 192.168.1.50 [--tls] [--dali-line 1]
        [--address 0] [--writes] [--events 10] [--report bench_report.md]

By default everything is READ-ONLY: connection, settings, configuration lists, a
project pull and sync check, health and diagnostics, the device log, DALI and
DALI-2 scans, gear settings and scenes, the SD card and its decoded logs, and the
live event stream.

--writes adds reversible writes on one DALI fitting (--address on --dali-line),
each read back and then put back as it was:
  - stores a level in a scene the fitting does not use, reads it, removes it
  - changes the power-on level, reads it, restores the original
Nothing else is written. Run it from the project folder (the one with
pyproject.toml), with the package installed or on the path.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from edidio_spektra_ai import server as S  # noqa: E402
from edidio_spektra_ai import tools_live as T  # noqa: E402

SKIP_HINTS = ("not supported", "unsupported", "no sd card", "not available",
              "needs firmware", "only on", "no dali gear", "no dali-2", "not an addict",
              "no wi-fi")


class Bench:
    def __init__(self, verbose: bool):
        self.results: list[dict] = []
        self.verbose = verbose

    async def check(self, name: str, coro, ok=None, *, skip_if=None) -> str:
        """Run one tool call. FAIL on an exception, an 'Error' reply or ok() False;
        SKIP when the controller says the feature is not there."""
        t0 = time.monotonic()
        try:
            out = await coro
            out = out if isinstance(out, str) else str(out)
            low = out.lower()
            if (skip_if and skip_if(out)) or low.startswith("not supported"):
                status = "SKIP"
            elif out.startswith("Error") or out.startswith("Error reading"):
                status = "SKIP" if any(h in low for h in SKIP_HINTS) else "FAIL"
            elif ok is not None and not ok(out):
                status = "FAIL"
            else:
                status = "PASS"
        except Exception as err:  # noqa: BLE001
            out, status = f"{type(err).__name__}: {err}", "FAIL"
        secs = time.monotonic() - t0
        self.results.append({"name": name, "status": status, "secs": secs, "out": out})
        first = out.strip().splitlines()[0] if out.strip() else ""
        print(f"  {status:<4}  {name:<38} {secs:5.1f}s  {first[:70]}")
        if self.verbose or status == "FAIL":
            for line in out.strip().splitlines()[1:12]:
                print(f"              {line[:110]}")
        return out

    def note(self, name: str, text: str, status: str = "SKIP") -> None:
        self.results.append({"name": name, "status": status, "secs": 0.0, "out": text})
        print(f"  {status:<4}  {name:<38}   -    {text[:70]}")

    def counts(self) -> dict:
        c = {"PASS": 0, "FAIL": 0, "SKIP": 0}
        for r in self.results:
            c[r["status"]] += 1
        return c


def token(text: str) -> str:
    m = re.search(r'confirm\(token="([0-9a-f]+)"\)', text)
    if not m:
        raise RuntimeError("no confirm token in the preview:\n" + text)
    return m.group(1)


async def read_only(b: Bench, a, tmp: Path) -> None:
    print("\nController")
    await b.check("connection_status", S.connection_status())
    await b.check("device_capabilities", S.device_capabilities())
    await b.check("get_device_settings", T.get_device_settings())
    await b.check("get_time", S.get_time())
    await b.check("health_check", T.health_check())
    for kind in ("device_status", "system", "lines", "counters", "connections"):
        await b.check(f"get_diagnostics {kind}", T.get_diagnostics(kind))
    await b.check("live_state", T.live_state())
    await b.check("device_log (last 20)", T.device_log(20))
    await b.check("wifi_status", T.wifi_status(),
                  skip_if=lambda o: "wi-fi" in o.lower() and "not" in o.lower()[:80])

    print("\nConfiguration")
    for name, coro in (("list_zones", S.list_zones()), ("list_sequences", S.list_sequences()),
                       ("list_themes", S.list_themes()), ("list_alarms", S.list_alarms()),
                       ("get_calendar", S.get_calendar()), ("list_lists", T.list_lists()),
                       ("list_io", T.list_io()), ("list_logic", T.list_logic()),
                       ("list_sensors", T.list_sensors()),
                       ("list_translations", T.list_translations()),
                       ("list_burnins", T.list_burnins()),
                       ("get_dmx_settings", T.get_dmx_settings()),
                       ("whats_playing", S.whats_playing()),
                       ("whats_scheduled_next", S.whats_scheduled_next())):
        await b.check(name, coro)
    await b.check("spektra_slot_changes (no update)", T.spektra_slot_changes(update=False))

    print("\nProject pull and sync")
    proj = tmp / "bench_pull.spektra"
    out = await b.check("pull_spektra_file", S.pull_spektra_file(
        a.host, str(proj), a.port, a.tls))
    if proj.exists() and not out.startswith("Error"):
        await b.check("validate_spektra", S.validate_spektra(str(proj)))
        await b.check("sync_status (fresh pull = synced)",
                      S.sync_status(str(proj), a.host, a.port, a.tls),
                      ok=lambda o: "DESYNCED" not in o and "UNSYNCED" not in o)
        await b.check("functionality_statement", T.functionality_statement(
            str(proj), str(tmp / "statement.md")))
    else:
        b.note("validate / sync / statement", "skipped: the pull failed")

    if a.dali_line:
        line = a.dali_line
        print(f"\nDALI line {line}")
        scan = await b.check("dali_scan", S.dali_scan(line))
        await b.check("dali_devices", T.dali_devices(line))
        await b.check("dali_levels", T.dali_levels(line))
        await b.check("dali_gear_settings", T.dali_gear_settings(line))
        await b.check("dali_scene_levels", T.dali_scene_levels(line))
        await b.check("dali_query_groups (address)", S.dali_query_groups(line, a.address))
        await b.check("dali_dt8_info (address)", T.dali_dt8_info(line, a.address),
                      skip_if=lambda o: "not dt8" in o.lower() or "not a dt8" in o.lower())
        await b.check("dali2_scan", T.dali2_scan(line))
        if "no " in scan.lower()[:40]:
            b.note("DALI gear", f"no gear answered on line {line}")

    print("\nSD card")
    sd = await b.check("sd_overview", T.sd_overview())
    if sd.startswith("Error") or any(h in sd.lower() for h in ("no sd", "no card mounted")):
        b.note("SD logs", "no SD card mounted")
    else:
        await b.check("sd_list_files logs/dali", T.sd_list_files("logs/dali", newest=3))
        await b.check("sd_read_log logs/dali", T.sd_read_log("logs/dali", last=5),
                      ok=lambda o: "entries" in o)
        await b.check("sd_read_log logs/events", T.sd_read_log("logs/events", last=5),
                      ok=lambda o: "entries" in o or "No .BIN" in o)
        await b.check("sd_read_file logs/sys (tail)", _sys_tail())
        await b.check("sd_search logs/sys ERROR", T.sd_search("logs/sys", "ERROR", files=1,
                                                              max_lines=5))

    if a.events > 0:
        print(f"\nEvent stream ({a.events} s)")
        out = await b.check("start_watching", S.start_watching(
            categories="inputs,sensors,triggers,dali,network"))
        if not out.startswith("Error"):
            await asyncio.sleep(1.0)              # let the subscription settle
            if a.dali_line:                       # make bus traffic we expect to see
                await S.dali_query_groups(a.dali_line, a.address)
            end = time.monotonic() + a.events
            while time.monotonic() < end:
                await asyncio.sleep(1.0)
                info = S._controller.recent_events(0, 200)
                if a.dali_line and any(e.get("kind") == "dali" for e in info["events"]):
                    break

            def seen(o):
                if "Not watching" in o:
                    return False
                return not a.dali_line or "DALI L" in o   # our own query frames
            await b.check("recent_events (own DALI query seen)", S.recent_events(0, 20),
                          ok=seen)
            await b.check("stop_watching", S.stop_watching())


async def _sys_tail() -> str:
    from edidio_spektra_ai import ops
    listing = await ops.sd_list(S._controller, "logs/sys")
    names = [e["name"] for e in listing["entries"] if e["name"].upper().endswith(".LOG")]
    if not names:
        return "No system logs on the card."
    order, _note = await T._log_order(names)
    return await T.sd_read_file(f"logs/sys/{order[0]}", tail_kb=1)


async def writes(b: Bench, a) -> None:
    from edidio_spektra_ai import dali_gear as g
    line, addr = a.dali_line, a.address
    print(f"\nReversible writes (DALI line {line}, address {addr})")
    ctrl = S._controller
    settings = await g.read_settings(ctrl, line, addr)
    if settings.get("actual_level") is None:
        b.note("writes", f"address {addr} on line {line} did not answer - nothing written")
        return

    # 1. a scene the fitting does not use
    scenes = await g.read_scenes(ctrl, line, addr)
    free = [i for i, v in enumerate(scenes) if v is None]
    if not free:
        b.note("scene store/remove", "every scene is in use - not touched")
    else:
        sc = free[-1]
        p = await b.check(f"preview_dali_scene {sc} = 123",
                          T.preview_dali_scene(line, str(addr), sc, "123"))
        await b.check("confirm (scene stored, read back)", S.confirm(token(p)),
                      ok=lambda o: "OK" in o)
        p = await b.check(f"preview_dali_scene {sc} remove",
                          T.preview_dali_scene(line, str(addr), sc, "remove"))
        await b.check("confirm (scene removed, read back)", S.confirm(token(p)),
                      ok=lambda o: "OK" in o)
        after = await g.read_scenes(ctrl, line, addr)
        b.note("scene left as found", f"scenes before {scenes}, after {after}",
               "PASS" if after == scenes else "FAIL")

    # 2. power-on level, then restore
    orig = settings.get("power_on_level")
    if orig is None:
        b.note("power-on change/restore", "power-on level did not read back")
        return
    test_level = 100 if orig != 100 else 120
    p = await b.check(f"preview_dali_gear_settings power_on {test_level}",
                      T.preview_dali_gear_settings(line, str(addr), power_on=str(test_level)))
    await b.check("confirm (power-on written, read back)", S.confirm(token(p)),
                  ok=lambda o: "OK" in o)
    back = "last" if orig == g.MASK else str(orig)
    p = await b.check(f"preview_dali_gear_settings power_on {back} (restore)",
                      T.preview_dali_gear_settings(line, str(addr), power_on=back))
    await b.check("confirm (restored, read back)", S.confirm(token(p)), ok=lambda o: "OK" in o)
    now = (await g.read_settings(ctrl, line, addr)).get("power_on_level")
    b.note("power-on left as found", f"before {orig}, after {now}",
           "PASS" if now == orig else "FAIL")


def write_report(b: Bench, a, path: Path, started: str, fw: str) -> None:
    c = b.counts()
    rows = ["# Spektra AI bench test", "",
            f"- Controller: {a.host} ({'TLS' if a.tls else 'TCP'} {a.port}), firmware {fw}",
            f"- Run: {started}, writes {'on' if a.writes else 'off'}",
            f"- Result: {c['PASS']} passed, {c['FAIL']} failed, {c['SKIP']} skipped", "",
            "| Check | Result | Time |", "|---|---|---|"]
    rows += [f"| {r['name']} | {r['status']} | {r['secs']:.1f} s |" for r in b.results]
    rows += ["", "## Output", ""]
    for r in b.results:
        out = r["out"].strip()
        if len(out) > 3000:
            out = out[:3000] + "\n... (cut)"
        rows += [f"### {r['name']} - {r['status']}", "", "```", out, "```", ""]
    path.write_text("\n".join(rows), encoding="utf-8")


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=23)
    ap.add_argument("--tls", action="store_true", help="connect with TLS (port 443)")
    ap.add_argument("--dali-line", type=int, default=1, help="DALI line to test (0 = none)")
    ap.add_argument("--address", type=int, default=0, help="DALI fitting for the writes")
    ap.add_argument("--writes", action="store_true", help="add the reversible writes")
    ap.add_argument("--events", type=int, default=10, help="seconds of event stream (0 = skip)")
    ap.add_argument("--report", default="", help="write a Markdown report here")
    ap.add_argument("-v", "--verbose", action="store_true", help="print more of each output")
    a = ap.parse_args(argv)
    if a.tls and a.port == 23:
        a.port = 443
    b = Bench(a.verbose)
    started = dt.datetime.now().isoformat(timespec="seconds")
    print(f"Spektra AI bench test - {a.host}, {started}, writes {'ON' if a.writes else 'off'}")
    out = await b.check("connect_controller", S.connect_controller(a.host, a.port, a.tls))
    fw = ""
    if out.startswith("Error"):
        print("Cannot connect - stopping.")
        return 2
    try:
        fw = (await S._controller.read_system_counts()).get("firmware", "")
    except Exception:  # noqa: BLE001
        pass
    with tempfile.TemporaryDirectory() as tmp:
        try:
            await read_only(b, a, Path(tmp))
            if a.writes and a.dali_line:
                await writes(b, a)
        finally:
            try:
                await S._controller.stop_events()
                await S._controller.disconnect()
            except Exception:  # noqa: BLE001
                pass
    c = b.counts()
    print(f"\n{c['PASS']} passed, {c['FAIL']} failed, {c['SKIP']} skipped "
          f"(firmware {fw or '?'})")
    if a.report:
        write_report(b, a, Path(a.report), started, fw)
        print(f"Report: {os.path.abspath(a.report)}")
    return 1 if c["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
