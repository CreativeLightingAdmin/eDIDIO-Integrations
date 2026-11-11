"""SD card browsing, log decoding and the background event recorder."""

from __future__ import annotations

from .. import ops
from ..server import _controller, server
from .common import _LOGIC_SOURCES, _LOGIC_COMPARE, _LOGIC_SOURCE_NAME, _LOGIC_COMPARE_NAME, _COMPARE_SYMBOLS, _INPUT_MODES, _INPUT_MODE_NAME, _OUTPUT_MODES, _err, _connect, _json, _seconds, _save_after  # noqa: F401

# --- SD card ---------------------------------------------------------------------------

def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def _newest(entries: list) -> list:
    return sorted(entries, key=lambda e: (e["modified"], e["name"]), reverse=True)


async def _log_order(names: list) -> tuple:
    """(names newest first, note). Uses the firmware's rotation index
    (logs/LOGMETA.DAT) when it can be read - file numbers wrap at 10000 and dates
    follow the controller clock. The note says if the file the firmware says it is
    writing does not exist (that category has stopped reaching the card)."""
    from .. import sd_logs
    prefix = names[0].split("_")[0].upper() if names else ""
    current, note = None, ""
    try:
        meta = sd_logs.parse_logmeta(
            (await ops.sd_read(_controller, sd_logs.LOGMETA_PATH))["data"])
        current = (meta.get(prefix) or {}).get("current")
    except Exception:  # noqa: BLE001
        pass
    if current is not None and not any(sd_logs._number(n) == current for n in names):
        note = (f"NOTE: the controller says it is writing {prefix}_{current:04d}, but that "
                "file is not on the card - nothing newer than the file below was logged.\n")
    return sd_logs.latest_first(names, current), note


@server.tool()
async def sd_overview() -> str:
    """The controller's SD card: free/total space, and each log category's folder,
    whether it is recording, its size budget and how much it holds. Read-only."""
    try:
        _controller._require()
        space = await ops.sd_space(_controller)
        pol = await ops.sd_policy(_controller)
    except ops.Unsupported as err:
        return str(err)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if space["status"] != "SD_OK":
        what = {"SD_NOT_MOUNTED": "no card mounted (none inserted, or it failed to mount)"}
        head = (f"SD card: {what.get(space['status'], space['status'])}. Nothing is being "
                "logged to the card; the folder settings below apply once one is mounted.")
    elif space["capacity_known"]:
        head = (f"SD card: {_human(space['free_bytes'])} free of "
                f"{_human(space['total_bytes'])}.")
    else:
        head = ("SD card: mounted, but the controller reports 0 of 0 bytes - its capacity "
                "was not measured (a known firmware issue), so free space is UNKNOWN, not full.")
    rows = [head, "Log folders:"]
    used = 0
    for e in pol.get("entries", []):
        used += e["current_disk_bytes"]
        on = {True: "recording", False: "off", None: "?"}[e["enabled"]]
        rows.append(f"  {e['directory']:<13} {e['prefix']}_nnnn.{e['extension']}  {on:<9} "
                    f"{_human(e['current_disk_bytes']):>9}  (budget {e['budget_permille'] / 10:.0f}%,"
                    f" files up to {e['max_file_size_kb']} KB)")
    rows.append(f"Logs total: {_human(used)}. Text logs (.LOG) can be read with sd_read_file; "
                ".BIN logs (DALI bus, events) are decoded by sd_read_log.")
    return "\n".join(rows)


@server.tool()
async def sd_list_files(path: str = "logs", newest: int = 20, match: str = "",
                        refresh: bool = False) -> str:
    """List an SD card folder (e.g. 'logs', 'logs/trig', 'logs/sys'), newest first by
    file date. `newest` = how many to show (0 = all); `match` filters names
    (case-insensitive). A big log folder takes ~2 s per 100 files to list; the
    listing is then reused for 2 minutes (refresh=True re-reads it). File dates come
    from the controller clock, so a clock that was once wrong gives odd dates - the
    file number (TRG_0963) is the order the controller wrote them in. Read-only."""
    try:
        _controller._require()
        res = await ops.sd_list(_controller, path, fresh=refresh)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    ents = [e for e in res["entries"] if match.lower() in e["name"].lower()]
    shown = _newest(ents)[:newest] if newest else _newest(ents)
    rows = [f"{res['path'] or '/'}: {len(ents)} entr{'y' if len(ents) == 1 else 'ies'}"
            + (f", newest {len(shown)}:" if newest and len(ents) > len(shown) else ":")]
    for e in shown:
        kind = "<dir>" if e["is_dir"] else _human(e["size"])
        rows.append(f"  {e['modified'] or '(no date)':<19}  {kind:>9}  {e['name']}")
    return "\n".join(rows)


@server.tool()
async def sd_read_file(path: str, tail_kb: int = 8, offset: int = -1, length: int = 0) -> str:
    """Read a text file from the SD card, e.g. 'logs/trig/TRG_0005.LOG'. By default the
    last `tail_kb` KB (the newest lines); or give `offset` (and `length`) in bytes.
    Read-only. For binary .BIN files use sd_download."""
    try:
        _controller._require()
        if offset < 0:
            head = await ops.sd_read(_controller, path, offset=0, length=1)
            size = head["file_size"]
            start = max(0, size - max(1, tail_kb) * 1024)
            res = await ops.sd_read(_controller, path, offset=start)
        else:
            res = await ops.sd_read(_controller, path, offset=offset, length=length)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    data = res["data"]
    if path.upper().endswith(".BIN") or b"\x00" in data[:256]:
        return (f"{res['path']} is binary ({_human(res['file_size'])}). DALI and event "
                "logs (.BIN): use sd_read_log to decode them; sd_download saves the file.")
    text = data.decode("utf-8", errors="replace")
    if res["offset"] > 0 and "\n" in text:
        text = text.split("\n", 1)[1]           # drop the partial first line
    return (f"{res['path']} ({_human(res['file_size'])}), bytes {res['offset']}-"
            f"{res['offset'] + len(data)}:\n{text}")


@server.tool()
async def sd_download(path: str, out_path: str) -> str:
    """Copy a file from the controller's SD card to this computer (out_path). Works
    for binary logs (.BIN) and crash records too. Read-only on the controller."""
    try:
        _controller._require()
        res = await ops.sd_read(_controller, path)
        with open(out_path, "wb") as fh:
            fh.write(res["data"])
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return f"Saved {res['path']} ({_human(len(res['data']))}) to {out_path}."


@server.tool()
async def sd_read_log(path: str = "", last: int = 40, text: str = "",
                      errors_only: bool = False, since: str = "", until: str = "",
                      local_file: str = "") -> str:
    """Decode a binary log from the SD card: DALI bus logs ('logs/dali/DAL_0003.BIN':
    every frame sent and received, with status - collisions, timeouts, no-echo) and
    event logs ('logs/events/EVT_0002.BIN': inputs, sensors, lists, schedules,
    config changes, boots, network connections, Spektra starts/stops).
    path: a file, or a folder ('logs/dali') to read the file being written now.
    local_file: decode
    a file already on this computer instead (e.g. from sd_download or SpektraPlus).
    Shows the last `last` matching entries; filter with `text` (case-insensitive),
    `errors_only`, and `since` / `until` ('2026-11-09 14:00', controller local time).
    Errors are marked '!!'. Read-only."""
    import datetime as dt
    from .. import sd_logs
    note = ""
    try:
        def when(s):
            return dt.datetime.fromisoformat(s.strip().replace("T", " ")) if s.strip() else None
        since_t, until_t = when(since), when(until)
        if local_file:
            with open(local_file, "rb") as fh:
                data, name = fh.read(), local_file
        else:
            if not path:
                return "Give path (an SD file or folder) or local_file."
            _controller._require()
            name = path
            if not path.upper().endswith(".BIN"):
                listing = await ops.sd_list(_controller, path)
                bins, note = await _log_order([e["name"] for e in listing["entries"]
                                         if not e["is_dir"]
                                         and e["name"].upper().endswith(".BIN")])
                if not bins:
                    return f"No .BIN logs in {listing['path']}."
                name = f"{listing['path']}/{bins[0]}"
            data = (await ops.sd_read(_controller, name))["data"]
        header, entries = sd_logs.decode(data)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    picked = sd_logs.select(entries, text=text, errors_only=errors_only,
                            since=since_t, until=until_t)
    shown = picked[-max(1, last):]
    filt = " matching" if (text or errors_only or since_t or until_t) else ""
    head = note + (f"{name} ({_human(len(data))}): {sd_logs.summarise(header, entries)}.\n"
            f"{len(picked)}{filt} entries" + (f", showing the last {len(shown)}"
                                             if len(shown) < len(picked) else "") + ":")
    return head + "".join("\n  " + sd_logs.format_entry(e) for e in shown)


@server.tool()
async def sd_search(folder: str, text: str, files: int = 5, max_lines: int = 60) -> str:
    """Search the newest `files` log files in an SD folder (e.g. 'logs/trig',
    'logs/sys', 'logs/sensor', 'logs/network', and the binary 'logs/dali' and
    'logs/events', which are decoded first) for lines containing `text`
    (case-insensitive). Good for 'when did input 3 fire?', 'any errors today?'
    (text 'ERROR' / 'WARN' / '!!') or 'every frame to address 4' ('address 4 ').
    Read-only."""
    from .. import sd_logs
    note = ""
    try:
        _controller._require()
        listing = await ops.sd_list(_controller, folder)
        names, note = await _log_order([e["name"] for e in listing["entries"] if not e["is_dir"]
                                  and e["name"].upper().endswith((".LOG", ".BIN"))])
        logs = [{"name": n} for n in names[:max(1, files)]]
        hits = []
        for e in reversed(logs):                     # oldest first, newest hits last
            res = await ops.sd_read(_controller, f"{listing['path']}/{e['name']}")
            if sd_logs.is_binary_log(res["data"]):
                try:
                    _h, entries = sd_logs.decode(res["data"])
                except ValueError:
                    continue
                lines = [sd_logs.format_entry(x) for x in entries]
            else:
                lines = res["data"].decode("utf-8", errors="replace").splitlines()
            for line in lines:
                if text.lower() in line.lower():
                    hits.append(f"  {e['name']}: {line}")
    except Exception as err:  # noqa: BLE001
        return _err(err)
    head = note + (f"'{text}' in the newest {len(logs)} file(s) of {listing['path']}: "
            f"{len(hits)} line(s)")
    return head + ("\n" + "\n".join(hits[-max_lines:]) if hits else ".") + (
        f"\n(showing the last {max_lines})" if len(hits) > max_lines else "")


# --- background event recorder (keeps recording when no MCP session is running) -----

def _recorder_folder(name: str):
    from .. import recorder
    return recorder.recordings_dir() / recorder.safe_name(name)


@server.tool()
async def recorder_start(host: str = "", port: int = 23, use_tls: bool = False,
                         name: str = "", categories: str = "", keep_days: int = 30) -> str:
    """Start a BACKGROUND event recorder: a separate process that subscribes to the
    controller's live events and writes them to disk, and keeps going after this chat
    or the MCP server closes, reconnecting by itself. host: default the connected
    controller. name: the recording's name (default: the host). categories: default
    everything (inputs, sensors, triggers, dali, schedule, lists, config, network).
    keep_days: day files older than this are deleted (0 = keep all). Needs firmware
    1.4.0+. Uses one of the controller's client connections. Read-only on the
    controller. Check with recorder_status, read with recorded_events."""
    import asyncio
    import os
    import subprocess
    import sys
    from pathlib import Path
    from .. import recorder
    try:
        if not host:
            if not _controller.host:
                return "Give host, or connect to a controller first."
            host = _controller.host
            port = getattr(_controller, "port", port)
            use_tls = getattr(_controller, "use_tls", use_tls)
        folder = _recorder_folder(name or host)
        st = recorder.read_status(folder)
        if st.get("alive"):
            return (f"Recorder '{folder.name}' is already running (pid {st.get('pid')}, "
                    f"{st.get('state')}, {st.get('events')} events).")
        folder.mkdir(parents=True, exist_ok=True)
        args = [sys.executable, "-m", "edidio_spektra_ai.recorder", "--host", host,
                "--port", str(port), "--name", folder.name, "--dir", str(folder.parent),
                "--keep-days", str(keep_days)]
        if use_tls:
            args.append("--tls")
        if categories.strip():
            args += ["--categories", categories]
        env = dict(os.environ)
        pkg_root = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": open(folder / "recorder.err", "ab"), "env": env,
              "cwd": str(folder)}
        if os.name == "nt":
            kw["creationflags"] = (subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NEW_PROCESS_GROUP
                                   | subprocess.CREATE_NO_WINDOW)
        else:
            kw["start_new_session"] = True
        try:
            (folder / "status.json").unlink()
        except OSError:
            pass
        proc = subprocess.Popen(args, **kw)
        for _ in range(40):                       # up to ~20 s for the first connect
            await asyncio.sleep(0.5)
            st = recorder.read_status(folder)
            if (st.get("state") in ("recording", "failed", "retrying")
                    or proc.poll() is not None):
                break
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if proc.poll() is not None and st.get("state") != "failed":
        return (f"The recorder exited at once (code {proc.returncode}); see "
                f"{folder / 'recorder.err'}.")
    state = st.get("state", "starting")
    msg = {"recording": "recording",
           "retrying": f"not connected yet ({st.get('error')}); it keeps retrying",
           "failed": f"FAILED: {st.get('error')}"}.get(state, state)
    return (f"Recorder '{folder.name}' started (pid {proc.pid}) for {host}: {msg}.\n"
            f"Files: {folder}. Stop it with recorder_stop(name=\"{folder.name}\").")


@server.tool()
async def recorder_status() -> str:
    """Every background event recorder on this computer: running or not, controller,
    state (recording / reconnecting / retrying), events recorded since it started,
    the last event time, and how much is on disk."""
    from .. import recorder
    recs = recorder.list_recorders()
    if not recs:
        return f"No recordings in {recorder.recordings_dir()}."
    rows = [f"Recordings in {recorder.recordings_dir()}:"]
    for r in recs:
        if r.get("alive"):
            run = (f"RUNNING (pid {r.get('pid')}), {r.get('state')}"
                   + (f" - {r['error']}" if r.get("error") else "")
                   + f", {r.get('events')} events since {r.get('started')}"
                   + (f", last {r['last_event'][:19].replace('T', ' ')}"
                      if r.get("last_event") else ""))
        else:
            run = "not running" + (f" ({r.get('state')}: {r['error']})"
                                   if r.get("state") == "failed" else "")
        days = (f"{r['files']} day file(s) {r['first_day']} to {r['last_day']}, "
                f"{_human(r['bytes'])}" if r["files"] else "no events on disk")
        rows.append(f"  {r['name']}: {r.get('host', '?')} - {run}; {days}")
    return "\n".join(rows)


@server.tool()
async def recorder_stop(name: str) -> str:
    """Stop a background event recorder (it closes its connection and exits). The
    recorded events stay on disk."""
    import asyncio
    import os
    import signal
    from .. import recorder
    pid = None
    try:
        folder = _recorder_folder(name)
        st = recorder.read_status(folder)
        if not st:
            return f"No recorder named '{name}' (see recorder_status)."
        if not st.get("alive"):
            return f"Recorder '{folder.name}' is not running."
        (folder / "stop").write_text("stop", encoding="utf-8")
        for _ in range(30):
            await asyncio.sleep(0.5)
            st = recorder.read_status(folder)
            if not st.get("alive"):
                return (f"Recorder '{folder.name}' stopped ({st.get('events')} events this "
                        "run). The files are kept.")
        pid = st.get("pid")
        if pid:
            try:
                os.kill(int(pid), signal.SIGTERM)
            except OSError:
                pass
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return f"Recorder '{folder.name}' did not stop in time; its process (pid {pid}) was ended."


@server.tool()
async def recorded_events(name: str = "", last: int = 50, text: str = "", kind: str = "",
                          since: str = "", until: str = "", errors_only: bool = False) -> str:
    """Read what a background recorder captured. name: the recording (default: the
    only one). Shows the last `last` matching events. Filters: kind (comma list of
    input, sensor, dali, list, schedule, config, boot, net, spektra, command, text,
    recorder), text (case-insensitive, matches the shown line), since / until
    ('2026-11-09 14:00', this computer's local time), errors_only (failed DALI frames,
    watchdog resets, lost connections). '[recorder]' lines mark when recording
    started, stopped or lost the controller - gaps in between are not covered."""
    import datetime as dt
    from .. import recorder
    try:
        if not name:
            recs = recorder.list_recorders()
            if not recs:
                return "No recordings yet (start one with recorder_start)."
            if len(recs) > 1:
                return "Several recordings - give name: " + ", ".join(r["name"] for r in recs)
            name = recs[0]["name"]
        folder = _recorder_folder(name)
        if not folder.is_dir():
            return f"No recording named '{name}'."

        def when(s):
            return (dt.datetime.fromisoformat(s.strip().replace("T", " "))
                    if s.strip() else None)
        events, total = recorder.read_events(folder, since=when(since), until=when(until),
                                             kind=kind, text=text, errors_only=errors_only,
                                             last=max(1, last))
    except Exception as err:  # noqa: BLE001
        return _err(err)
    if not events:
        return f"No matching events in recording '{folder.name}'."
    head = (f"Recording '{folder.name}': {total} matching event(s)"
            + (f", showing the last {len(events)}" if len(events) < total else "") + ":")
    return head + "".join("\n  " + recorder.format_event(e) for e in events)
