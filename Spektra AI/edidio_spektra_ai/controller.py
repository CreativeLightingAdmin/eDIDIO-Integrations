"""Async controller wrapper for Spektra AI.

Owns a single, dynamically-connectable ``EdidioClient`` (find/connect by IP or
discovered name), assigns message ids, and exposes send + request/response
helpers used by the authoring and read tools. An ``client_factory`` is injectable
so the whole thing is testable with a stub client (no network).
"""

from __future__ import annotations

from datetime import datetime

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb
from edidio_control_py import (
    AckMessageType,
    DiagnosticMessageType,
    EdidioClient,
    ReadType,
    SpektraTargetType,
)

from . import discovery
from .scheduling import next_scheduled, parse_calendar_overview

# Documented slot counts (the device also reports exact counts via diagnostics).
SEQUENCE_SCAN = 32   # how many sequence slots to scan for "list sequences"
THEME_SCAN = 10      # firmware spektra_theme_count (confirmed via diag on 1.5.3)
ZONE_SCAN = 10
CALENDAR_PAGES = 5   # 5 pages x 90 days covers the 366-day year


def _default_factory(host, port, use_tls):
    return EdidioClient(host, port, use_tls=use_tls)


class SpektraController:
    def __init__(self, *, client_factory=_default_factory):
        self._factory = client_factory
        self._client = None
        self.host = None
        self._mid = 0

    # --- connection ---
    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.connected

    async def connect(self, host: str, port: int = 23, use_tls: bool = False):
        if self._client is not None:
            await self._client.disconnect()
        self._client = self._factory(host, port, use_tls)
        await self._client.connect()
        self.host = host
        return self.connected

    async def disconnect(self):
        if self._client is not None:
            await self._client.disconnect()
            self._client = None
            self.host = None

    def discover(self):
        return discovery.discover()

    def _require(self):
        if not self.connected:
            raise RuntimeError("Not connected to a controller. Use connect_controller first.")
        return self._client

    def _next_id(self):
        self._mid = (self._mid + 1) & 0xFFFFFF
        return self._mid

    # --- send framed messages (authoring) ---
    async def send_messages(self, messages: list) -> None:
        client = self._require()
        for frame in messages:
            await client.send_protobuf_message(frame)

    async def send_and_ack(self, messages: list) -> list:
        """Send messages; for each, read the reply and return a list of ack summaries."""
        client = self._require()
        acks = []
        for frame in messages:
            reply = await client.request(frame)
            acks.append(self._ack_summary(reply))
        return acks

    @staticmethod
    def _ack_summary(reply: "pb.EdidioMessage") -> dict:
        which = reply.WhichOneof("payload")
        if which == "ack":
            code = reply.ack.payload
            name = _ACK_NAMES.get(code, str(code))
            return {"ok": code == AckMessageType.SUCCESS, "code": name}
        return {"ok": True, "code": which or "no-payload"}

    # --- reads / queries ---
    async def read_zone(self, zone: int) -> dict:
        client = self._require()
        frame = EdidioClient.create_spektra_read_message(self._next_id(), SpektraTargetType.SETTINGS, zone)
        reply = await client.request(frame)
        if reply.WhichOneof("payload") == "spektra_settings":
            s = reply.spektra_settings
            return {
                "zone": s.zone, "protocol": s.protocol,
                "channels_per_light": s.channels_per_light,
                "number_of_lights": s.number_of_lights,
                "channel_colours": list(s.channel_colours),
                "start_address": s.start_address,
            }
        return {"error": self._ack_summary(reply)}

    async def read_alarms(self) -> list:
        client = self._require()
        frame = EdidioClient.create_read_device_message(self._next_id(), ReadType.ALARMS)
        reply = await client.request(frame)
        which = reply.WhichOneof("payload")
        if which == "alarms":
            return [_alarm_summary(a) for a in reply.alarms.alarm]
        if which == "alarm":
            return [_alarm_summary(reply.alarm)]
        return []

    async def clear_schedule(self, index: int) -> dict:
        """Disable and clear a schedule (alarm) slot, freeing it for reuse. Matches
        the controller's empty-slot state (disabled, NO_COMMAND trigger)."""
        client = self._require()
        frame = EdidioClient.create_alarm_message(
            self._next_id(), index=index, enabled=False,
            start_trigger={"type": pb.TriggerType.NO_COMMAND})
        reply = await client.request(frame)
        return self._ack_summary(reply)

    async def list_zones(self) -> list:
        out = []
        for z in range(ZONE_SCAN):
            details = await self.read_zone(z)
            if "error" not in details:
                out.append(details)
        return out

    async def _read_spektra(self, target_type, index):
        client = self._require()
        frame = EdidioClient.create_spektra_read_message(self._next_id(), target_type, index)
        return await client.request(frame)

    async def list_sequences(self) -> list:
        """Read each sequence slot; keep the ones that exist (title/type/colours)."""
        out = []
        for i in range(SEQUENCE_SCAN):
            reply = await self._read_spektra(SpektraTargetType.SEQUENCE, i)
            if reply.WhichOneof("payload") == "spektra_sequence":
                s = reply.spektra_sequence
                out.append({"index": s.index, "title": s.title, "type": s.type,
                            "colours": len(s.colours), "time_per_step": s.time_per_step})
            # an INDEX_OUT_OF_BOUNDS ack means an empty slot -> skip
        return out

    async def list_themes(self) -> list:
        out = []
        for i in range(THEME_SCAN):
            reply = await self._read_spektra(SpektraTargetType.THEME, i)
            if reply.WhichOneof("payload") == "spektra_theme":
                t = reply.spektra_theme
                out.append({"index": t.index, "title": t.title, "colours": len(t.colours)})
        return out

    async def read_calendar(self) -> list:
        """Read the whole year's calendar assignments. The device paginates 90 days
        per page (page number in the read index; day_offset = page * 90), so we
        loop all pages and aggregate."""
        out = []
        for page in range(CALENDAR_PAGES):
            reply = await self._read_spektra(SpektraTargetType.CALENDAR, page)
            if reply.WhichOneof("payload") != "spektra_calendar_overview":
                continue
            ov = reply.spektra_calendar_overview
            out.extend(parse_calendar_overview({
                "day_offset": ov.day_offset,
                "days": [{"day_index": d.day_index, "type": d.type, "target_index": d.target_index}
                         for d in ov.days],
            }))
        return out

    # --- device clock ---
    async def get_device_time(self) -> dict:
        """Read the controller's RTC. Returns the device datetime plus the drift
        against this computer's local clock (so the user can decide to sync)."""
        client = self._require()
        reply = await client.request(EdidioClient.create_get_device_time_message(self._next_id()))
        if reply.WhichOneof("payload") != "admin_message":
            return {"error": self._ack_summary(reply)}
        packed = reply.admin_message.device_time.time
        t, d = packed.time, packed.date
        dev = datetime(2000 + ((d >> 24) & 0xFF), (d >> 16) & 0xFF, (d >> 8) & 0xFF,
                       (t >> 16) & 0xFF, (t >> 8) & 0xFF, t & 0xFF)
        now = datetime.now()
        drift = round((now - dev).total_seconds())
        return {"device": dev.isoformat(sep=" "), "computer": now.isoformat(sep=" "),
                "drift_seconds": drift, "device_dt": dev}

    async def set_device_time(self, when: datetime | None = None) -> dict:
        """Set the controller's RTC to `when` (defaults to this computer's local
        wall-clock time)."""
        client = self._require()
        w = when or datetime.now()
        reply = await client.request(EdidioClient.create_set_device_time_message(
            self._next_id(), year=w.year % 100, month=w.month, day=w.day,
            weekday=w.isoweekday(), hour=w.hour, minute=w.minute, second=w.second))
        return {"set_to": w.isoformat(sep=" "), "ack": self._ack_summary(reply)}

    async def read_live(self) -> list:
        """What each zone is currently playing. The device returns per-zone arrays
        (type/index/step/colour/action indexed by zone); we keep the zones that
        have something loaded (type != NONE and index != 255) and look up titles.

        Field semantics (determined empirically against firmware, since STOP sets
        type=0; START sets action=1; PAUSE sets action=0 while type stays set):
          type   0 = stopped/idle, 1 = sequence, 2 = theme
          action 1 = playing, 0 = paused/halted (NOT the SpektraActionType enum)
          zone_active is unreliable on this firmware (always False) -> not used.
        """
        reply = await self._read_spektra(pb.SpektraTargetType.LIVE, 0)
        if reply.WhichOneof("payload") != "spektra_live":
            return []
        lv = reply.spektra_live

        def at(arr, i, default=0):
            return arr[i] if i < len(arr) else default

        out = []
        for zone in range(len(lv.index)):
            typ, idx = at(lv.type, zone), at(lv.index, zone, 255)
            if typ == 0 or idx == 255:
                continue  # nothing loaded on this zone (stopped/idle)
            kind = "sequence" if typ == 1 else ("theme" if typ == 2 else str(typ))
            state = "playing" if at(lv.action, zone) == 1 else "paused"
            out.append({
                "zone": zone, "kind": kind, "index": idx, "state": state,
                "step": at(lv.step_index, zone), "colour": at(lv.colour_index, zone),
            })
        # enrich with titles (one read per distinct slot)
        titles: dict = {}
        for e in out:
            key = (e["kind"], e["index"])
            if key not in titles:
                tt = pb.SpektraTargetType.SEQUENCE if e["kind"] == "sequence" else pb.SpektraTargetType.THEME
                r = await self._read_spektra(tt, e["index"])
                w = r.WhichOneof("payload")
                titles[key] = (r.spektra_sequence.title if w == "spektra_sequence"
                               else r.spektra_theme.title if w == "spektra_theme" else "")
            e["title"] = titles[key]
        return out

    async def whats_next(self) -> dict:
        """Compute the soonest-firing schedule from the device's alarms."""
        alarms = await self.read_alarms()
        result = next_scheduled(alarms)
        if result is None:
            return {"next": None, "message": "Nothing is time-scheduled (or only astro/one-shot alarms)."}
        return {"next": result["description"], "when": result["when"].isoformat(), "in": result["in"]}

    async def read_capabilities(self) -> dict:
        client = self._require()
        frame = EdidioClient.create_diagnostic_message(
            self._next_id(), DiagnosticMessageType.DIAGNOSTIC_SYSTEM_INFO)
        reply = await client.request(frame)
        which = reply.WhichOneof("payload")
        if which and which.startswith("diag"):
            return {"raw_field": which, "message": str(getattr(reply, which))}
        return {"raw": which}

    async def read_dmx_cache(self, line: int, page: int = 0) -> dict:
        client = self._require()
        frame = EdidioClient.create_diagnostic_message(
            self._next_id(), DiagnosticMessageType.DMX_LEVEL_CACHE, line=line, page=page)
        reply = await client.request(frame)
        if reply.WhichOneof("payload") == "level_cache_response":
            r = reply.level_cache_response
            # The firmware does not reliably populate the response's line/page
            # fields (they come back as uninitialised garbage on an active line),
            # so report the line/page we requested rather than r.line / r.page.
            return {"line": line, "page": page, "levels": list(r.levels)}
        return {"error": self._ack_summary(reply)}

    # --- live playback on a zone (transient, no preview needed) ---
    async def _spektra_control(self, spektra_type, zone: int, index: int, action: int) -> dict:
        client = self._require()
        frame = EdidioClient.create_spektra_control_message(
            self._next_id(), spektra_type, zone, index, action)
        reply = await client.request(frame)
        return self._ack_summary(reply)

    async def play_sequence(self, zone: int, index: int) -> dict:
        """Start a stored sequence playing on a zone right now."""
        return await self._spektra_control(
            pb.SpektraTargetType.SEQUENCE, zone, index, pb.SpektraActionType.START)

    async def play_theme(self, zone: int, index: int) -> dict:
        """Apply a stored theme on a zone right now."""
        return await self._spektra_control(
            pb.SpektraTargetType.THEME, zone, index, pb.SpektraActionType.START)

    async def pause_zone(self, zone: int, index: int = 0) -> dict:
        """Pause SpektraPlus playback on a zone (holds the current output)."""
        return await self._spektra_control(
            pb.SpektraTargetType.SEQUENCE, zone, index, pb.SpektraActionType.PAUSE)

    async def stop_zone(self, zone: int) -> dict:
        """Stop playback on a zone and turn its output off (matches the app's stop)."""
        client = self._require()
        frame = EdidioClient.create_spektra_stop_message(self._next_id(), zone)
        reply = await client.request(frame)
        return self._ack_summary(reply)

    # --- individual (non-zone) control ---
    async def send_dali(self, line_mask, address, arc_level):
        client = self._require()
        await client.set_dali_arc_level(self._next_id(), line_mask, address, arc_level)

    async def send_dmx(self, universe_mask, channel, levels):
        client = self._require()
        await client.set_dmx_level(self._next_id(), 0, universe_mask, channel, list(levels))


_ACK_NAMES = {v.number: v.name for v in pb.AckMessageType.DESCRIPTOR.values}


def _alarm_summary(a) -> dict:
    return {
        "index": a.index, "enabled": a.enabled,
        "start_time": a.start_time.time, "repeat": a.repeat,
        "repeat_day_bitmask": a.repeat_day_bitmask,
        "repeat_month_bitmask": a.repeat_month_bitmask,
        "trigger_type": a.start_trigger.type,
        "target_index": a.start_trigger.target_index,
        "zone": a.start_trigger.zone,
    }


def summarize_discovery(devices):
    return [
        {"name": d.get("NAME"), "ip": d.get("IP"), "mac": d.get("MAC"),
         "tls": d.get("TLS"), "lines": discovery.summarize_lines(d.get("LINES"))}
        for d in devices
    ]
