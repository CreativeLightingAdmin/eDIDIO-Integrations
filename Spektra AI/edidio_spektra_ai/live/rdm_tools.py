"""RDM discovery and device settings."""

from __future__ import annotations

from ..server import _controller, _new_token, server
from .common import _LOGIC_SOURCES, _LOGIC_COMPARE, _LOGIC_SOURCE_NAME, _LOGIC_COMPARE_NAME, _COMPARE_SYMBOLS, _INPUT_MODES, _INPUT_MODE_NAME, _OUTPUT_MODES, _err, _connect, _json, _seconds, _save_after  # noqa: F401

# --- RDM ------------------------------------------------------------------------------

@server.tool()
async def rdm_discover(line: int, details: bool = True) -> str:
    """Find RDM fixtures on a DMX OUTPUT line (1-based) and, by default, read each
    one's manufacturer, model, label, DMX start address, footprint and personalities.
    The line must be a DMX output (preview_line_types to change it). Read-only."""
    from .. import rdm
    try:
        _controller._require()
        found = await rdm.discover(_controller, line)
        if not found["uids"]:
            extra = f" (error code {found['error_code']})" if found["error_code"] else ""
            return f"No RDM fixtures answered on line {line}{extra}."
        rows = [f"{len(found['uids'])} RDM fixture(s) on line {line}:"]
        for uid in found["uids"]:
            rows.append(rdm.describe(await rdm.details(_controller, line, uid)) if details
                        else f"  {rdm.uid_text(uid)}")
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return "\n".join(rows)


@server.tool()
async def rdm_get(line: int, uid: str, pid: int, data: str = "") -> str:
    """Raw RDM GET of any parameter (pid number, e.g. 0x0060 = 96 DEVICE_INFO).
    data: optional comma-separated bytes for the request. Returns the reply bytes.
    Read-only."""
    from .. import rdm
    try:
        _controller._require()
        payload = bytes(int(x, 0) for x in data.split(",") if x.strip())
        r = await rdm.request(_controller, line, rdm.parse_uid(uid), pid, data=payload)
    except Exception as err:  # noqa: BLE001
        return _err(err)
    name = rdm.PID_NAMES.get(pid, f"PID 0x{pid:04X}")
    if not r["ok"]:
        return f"{name}: no answer ({r['error']})."
    b = r["data"]
    text = "".join(chr(x) if 32 <= x < 127 else "." for x in b)
    return f"{name}: {len(b)} byte(s) {b.hex(' ')}  '{text}'"


@server.tool()
async def rdm_identify(line: int, uid: str, on: bool = True) -> str:
    """Make an RDM fixture identify itself (flash) - or stop. Transient."""
    from .. import rdm
    try:
        _controller._require()
        r = await rdm.request(_controller, line, rdm.parse_uid(uid), rdm.PID_IDENTIFY_DEVICE,
                              set_=True, data=bytes([1 if on else 0]))
    except Exception as err:  # noqa: BLE001
        return _err(err)
    return (f"Identify {'on' if on else 'off'} for {uid}." if r["ok"]
            else f"No answer from {uid}: {r['error']}")


@server.tool()
async def preview_rdm_set(line: int, uid: str, start_address: int = 0,
                          personality: int = 0, label: str = "") -> str:
    """Change an RDM fixture: DMX start_address (1-512), personality (its mode number,
    see rdm_discover), and/or label (up to 32 characters). Only the values you give
    are changed. Returns a token; confirm(token) sends them and reads them back."""
    from .. import rdm
    try:
        _controller._require()
        u = rdm.parse_uid(uid)
        cur = await rdm.details(_controller, line, u)
        if cur.get("error"):
            return f"{uid} does not answer on line {line}."
        sets, lines = [], []
        if start_address:
            if not 1 <= start_address <= 512:
                return "start_address is 1-512."
            fp = cur.get("footprint") or 1
            if start_address + fp - 1 > 512:
                return f"Start {start_address} + footprint {fp} runs past channel 512."
            sets.append((rdm.PID_DMX_START_ADDRESS, start_address.to_bytes(2, "big")))
            lines.append(f"  DMX start address: {cur.get('start_address')} -> {start_address}")
        if personality:
            ids = [p["id"] for p in cur.get("personalities", [])]
            if ids and personality not in ids:
                return f"personality: one of {ids}."
            sets.append((rdm.PID_DMX_PERSONALITY, bytes([personality])))
            name = next((p["name"] for p in cur.get("personalities", [])
                         if p["id"] == personality), "?")
            lines.append(f"  personality: {cur.get('personality')} -> {personality} ({name})")
        if label:
            if len(label.encode("utf-8")) > 32:
                return "An RDM label is at most 32 bytes."
            sets.append((rdm.PID_DEVICE_LABEL, label.encode("utf-8")))
            lines.append(f"  label: '{cur.get('label', '')}' -> '{label}'")
        if not sets:
            return "Nothing to change: give start_address, personality and/or label."
    except Exception as err:  # noqa: BLE001
        return _err(err)

    async def run():
        out = []
        for pid, data in sets:
            r = await rdm.request(_controller, line, u, pid, set_=True, data=data)
            out.append(f"{rdm.PID_NAMES.get(pid, pid)}: {'sent' if r['ok'] else r['error']}")
        after = await rdm.details(_controller, line, u)
        return "Done. " + "; ".join(out) + "\nNow:\n" + rdm.describe(after)

    token = _new_token([], "\n".join(lines))
    from ..server import _pending
    _pending[token]["runner"] = run
    return (f"PREVIEW for {cur.get('manufacturer', '')} {cur.get('model', '')} {uid}:\n"
            + "\n".join(lines) + f"\nCall confirm(token=\"{token}\") to send.")
