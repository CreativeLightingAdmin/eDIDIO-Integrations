"""Async controller wrapper for Spektra AI.

Owns a single, dynamically-connectable ``EdidioClient`` (find/connect by IP or
discovered name), assigns message ids, and exposes send + request/response
helpers used by the authoring and read tools. An ``client_factory`` is injectable
so the whole thing is testable with a stub client (no network).
"""

from __future__ import annotations

import asyncio
import ssl
from datetime import datetime

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb
from edidio_control_py import (
    AckMessageType,
    DiagnosticMessageType,
    EdidioClient,
    ReadType,
    SpektraTargetType,
)

from . import dali, discovery, spektra_map, v2
from .event_stream import DEFAULT_CATEGORIES, EventStream
from .notify import NotificationManager
from .scheduling import next_scheduled, parse_calendar_overview

# Documented slot counts (the device also reports exact counts via diagnostics).
SEQUENCE_SCAN = 144  # sequence slots when the controller does not report them
THEME_SCAN = 10      # firmware spektra_theme_count (confirmed via diag on 1.5.3)
ZONE_SCAN = 10
CALENDAR_PAGES = 5   # 5 pages x 90 days covers the 366-day year


def legacy_tls_context() -> "ssl.SSLContext":
    """TLS for eDIDIO controllers: TLS 1.2 only, the fleet's RSA-1024 certificate
    accepted (OpenSSL security level 0), no hostname or chain check. The device cert
    binds to the device's own ID, not an address, so there is no name to verify
    (SpektraPlus connects the same way). A default context fails the handshake
    (SSLV3_ALERT_HANDSHAKE_FAILURE)."""
    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=0")
    except ssl.SSLError:  # a build without security levels still has the suites
        pass
    return ctx


def _default_factory(host, port, use_tls):
    return EdidioClient(host, port, use_tls=use_tls,
                        ssl_context=legacy_tls_context() if use_tls else None)


CONNECT_ATTEMPTS = 3   # an ADDICT on Wi-Fi sometimes misses the first SYN


class SpektraController:
    def __init__(self, *, client_factory=_default_factory):
        self._factory = client_factory
        self._client = None
        self.host = None
        self._mid = 0
        self._events: EventStream | None = None
        self.notifications = NotificationManager()
        self._deadline_task = None

    # --- connection ---
    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.connected

    async def connect(self, host: str, port: int = 23, use_tls: bool = False):
        if self._client is not None:
            await self._client.disconnect()
        if use_tls and port == 23:
            port = 443   # TLS is served on 443; 23 is plain TCP
        last = None
        for attempt in range(CONNECT_ATTEMPTS):
            self._client = self._factory(host, port, use_tls)
            try:
                await self._client.connect()
                break
            except Exception as err:  # noqa: BLE001 — retried, then re-raised
                last = err
                if "TLS" in str(err) or attempt == CONNECT_ATTEMPTS - 1:
                    self._client = None
                    raise
                await asyncio.sleep(1.0)
        else:  # pragma: no cover
            raise last
        self.host = host
        self.port, self.use_tls = port, use_tls
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
        if hasattr(reply, "SerializeToString"):
            try:
                return v2.ack_summary(reply)   # adds the RejectReason on a refusal
            except Exception:  # noqa: BLE001 — fall back to the legacy view
                pass
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

    async def spektra_manifest(self, kind: str) -> dict | None:
        """{slot index: CRC} of the occupied SEQUENCE or THEME slots, from the slot
        manifest (firmware 1.6.0+), or None when the firmware has no manifest (older
        firmware ignores the flag and answers with slot 0 instead)."""
        from edidio_control_py._v2 import eDS10_v2_pb2 as v2pb
        out: dict = {}
        for page in range(64):
            r = await v2.request(self._require(), v2pb.EdidioMessage(
                message_id=self._next_id(), spektra_read=v2pb.SpektraReadMessage(
                    type=v2pb.SpektraTargetType.Value(kind), index=page, manifest=True)))
            if r.WhichOneof("payload") != "spektra_manifest":
                return None if page == 0 else out
            m = r.spektra_manifest
            out.update(zip(m.index, m.crc))
            if m.is_last_page or not m.slot_count:
                break
        return out

    async def spektra_slots(self, kind: str) -> list:
        """Slot indices to read: the occupied ones from the manifest, else every slot
        the controller has (sequences 144 / themes 10 on current models)."""
        man = await self.spektra_manifest(kind)
        if man is not None:
            return sorted(man)
        client = self._require()
        reply = await client.request(EdidioClient.create_diagnostic_message(
            self._next_id(), DiagnosticMessageType.DIAGNOSTIC_SYSTEM_INFO))
        which = reply.WhichOneof("payload")
        diag = getattr(reply, which) if which and which.startswith("diag") else None
        field = "spektra_seq_count" if kind == "SEQUENCE" else "spektra_theme_count"
        count = (getattr(diag, field, 0) if diag is not None else 0) or (
            SEQUENCE_SCAN if kind == "SEQUENCE" else THEME_SCAN)
        return list(range(count))

    async def list_sequences(self) -> list:
        """Read each used sequence slot (title/type/colours)."""
        out = []
        for i in await self.spektra_slots("SEQUENCE"):
            reply = await self._read_spektra(SpektraTargetType.SEQUENCE, i)
            if reply.WhichOneof("payload") == "spektra_sequence":
                s = reply.spektra_sequence
                out.append({"index": s.index, "title": s.title, "type": s.type,
                            "colours": len(s.colours), "time_per_step": s.time_per_step})
            # an INDEX_OUT_OF_BOUNDS ack means an empty slot -> skip
        return out

    async def list_themes(self) -> list:
        out = []
        for i in await self.spektra_slots("THEME"):
            reply = await self._read_spektra(SpektraTargetType.THEME, i)
            if reply.WhichOneof("payload") == "spektra_theme":
                t = reply.spektra_theme
                out.append({"index": t.index, "title": t.title, "colours": len(t.colours)})
        return out

    # --- pull live config into .spektra JSON (protobuf -> file via spektra_map) ---
    async def pull_sequences(self) -> list:
        out = []
        for i in await self.spektra_slots("SEQUENCE"):
            reply = await self._read_spektra(SpektraTargetType.SEQUENCE, i)
            if reply.WhichOneof("payload") == "spektra_sequence":
                out.append(spektra_map.sequence_to_dict(reply.spektra_sequence))
        return out

    async def pull_themes(self) -> list:
        out = []
        for i in await self.spektra_slots("THEME"):
            reply = await self._read_spektra(SpektraTargetType.THEME, i)
            if reply.WhichOneof("payload") == "spektra_theme":
                out.append(spektra_map.theme_to_dict(reply.spektra_theme))
        return out

    async def pull_zones(self) -> list:
        out = []
        for z in range(ZONE_SCAN):
            reply = await self._read_spektra(SpektraTargetType.SETTINGS, z)
            if reply.WhichOneof("payload") == "spektra_settings":
                out.append(spektra_map.zone_to_dict(reply.spektra_settings))
        return out

    async def pull_schedules(self) -> list:
        client = self._require()
        frame = EdidioClient.create_read_device_message(self._next_id(), ReadType.ALARMS)
        reply = await client.request(frame)
        which = reply.WhichOneof("payload")
        if which == "alarms":
            alarms = list(reply.alarms.alarm)
        elif which == "alarm":
            alarms = [reply.alarm]
        else:
            alarms = []
        return [spektra_map.schedule_to_dict(a) for a in alarms]

    async def _read_device(self, read_type, index=0, profile=0):
        client = self._require()
        frame = EdidioClient.create_read_device_message(
            self._next_id(), read_type, index, 0, profile)
        return await client.request(frame)

    async def read_system_counts(self) -> dict:
        """Read profile/list counts from the device diagnostics (for pull scans)."""
        client = self._require()
        reply = await client.request(EdidioClient.create_diagnostic_message(
            self._next_id(), DiagnosticMessageType.DIAGNOSTIC_SYSTEM_INFO))
        which = reply.WhichOneof("payload")
        if which and which.startswith("diag"):
            sub = getattr(reply, which)
            return {"profiles": getattr(sub, "profile_count", 0) or 0,
                    "lists": getattr(sub, "list_count", 0) or 0,
                    "firmware": getattr(sub, "firmware", "") or "",
                    "active": getattr(sub, "selected_profile", 0) or 0}
        return {"profiles": 0, "lists": 0, "firmware": "", "active": 0}

    SENSOR_SCAN = 40  # sensor slots per profile (firmware doesn't report the count)

    async def pull_sensors(self, profile: int) -> list:
        """Read programmed sensors for a profile (scan slots, keep is_programmed)."""
        out = []
        for i in range(self.SENSOR_SCAN):
            reply = await self._read_device(ReadType.SENSOR, i, profile)
            if reply.WhichOneof("payload") == "sensor" and reply.sensor.is_programmed:
                out.append(spektra_map.sensor_to_dict(reply.sensor))
        return out

    async def pull_daliinputs(self, profile: int) -> list:
        reply = await self._read_device(ReadType.DALI_INPUTS, 0, profile)
        if reply.WhichOneof("payload") == "inputs_dali":
            return [spektra_map.daliinput_to_dict(i) for i in reply.inputs_dali.inputs]
        return []

    async def pull_inputs(self, profile: int) -> list:
        reply = await self._read_device(ReadType.INPUTS, 0, profile)
        if reply.WhichOneof("payload") == "inputs":
            return [spektra_map.input_to_dict(i) for i in reply.inputs.inputs]
        return []

    async def pull_outputs(self, profile: int) -> list:
        reply = await self._read_device(ReadType.OUTPUTS, 0, profile)
        if reply.WhichOneof("payload") == "outputs":
            return [spektra_map.output_to_dict(o) for o in reply.outputs.outputs]
        return []

    async def pull_profiles(self, profile_count: int) -> list:
        out = []
        for p in range(profile_count):
            out.append({
                "inputs": await self.pull_inputs(p),
                "outputs": await self.pull_outputs(p),
                "sensors": await self.pull_sensors(p),
                "daliInputs": await self.pull_daliinputs(p),
                "irs": [], "userLevels": [],
            })
        return out

    async def pull_logic(self) -> list:
        reply = await self._read_device(ReadType.LOGIC)
        if reply.WhichOneof("payload") == "logic_message":
            return [spektra_map.logic_to_dict(g, i)
                    for i, g in enumerate(reply.logic_message.logic)]
        return []

    async def _read_v2(self, read_type: str, index: int = 0):
        from edidio_control_py._v2 import eDS10_v2_pb2 as v2pb
        return await v2.request(self._require(), v2pb.EdidioMessage(
            message_id=self._next_id(), read_device=v2pb.ReadDeviceMessage(
                type=v2pb.ReadType.Value(read_type), index=index)))

    async def pull_translations(self) -> list:
        """DMX-to-DALI translation objects (empty if the controller has none)."""
        r = await self._read_v2("DMX_TRANSLATIONS")
        if r.WhichOneof("payload") != "dmx_translator":
            return []
        return [spektra_map.translation_to_dict(o, i)
                for i, o in enumerate(r.dmx_translator.object)]

    async def pull_burnins(self) -> list:
        """Burn-ins with their live state (duration / remaining in minutes)."""
        r = await self._read_v2("BURN_IN")
        if r.WhichOneof("payload") != "burn_ins":
            return []
        return [spektra_map.burnin_to_dict(b, i) for i, b in enumerate(r.burn_ins.burnin)]

    async def pull_lists(self, list_count: int) -> list:
        """Every list with all its steps (blocks past 32 via LIST_EXTENDED)."""
        out = []
        for i in range(list_count):
            reply = await self._read_device(ReadType.LIST, i)
            if reply.WhichOneof("payload") != "list":
                continue
            base = reply.list
            total = min(base.total_step_count, spektra_map.LIST_MAX_STEPS)
            extra = []
            off = len(base.step)
            while off < total:
                ext = v2.to_v2(await self._client.request(
                    EdidioClient.create_read_device_message(
                        self._next_id(), ReadType.LIST_EXTENDED, i, off, 0)))
                if ext.WhichOneof("payload") != "list_extended" or not ext.list_extended.step:
                    break
                extra.extend(ext.list_extended.step)
                off += len(ext.list_extended.step)
            out.append(spektra_map.list_to_dict(base, extra))
        return out

    def _resolve_mac(self) -> str:
        """Find this host's MAC from LAN discovery (colon form); fallback if absent."""
        try:
            for d in discovery.discover():
                if d.get("IP") == self.host:
                    return (d.get("MAC") or "").replace("-", ":").upper()
        except Exception:  # noqa: BLE001 — discovery is best-effort here
            pass
        return f"PULLED:{self.host}"

    async def read_device_info(self) -> dict:
        """Read the device-describing fields SpektraPlus needs to build its UI:
        supportedFeatures + lineTypes + versions/vendor + activeProfile (from the
        diagnostic system info), and network (from admin). Returns a partial eDIDIO
        dict to overlay onto the controller template."""
        client = self._require()
        info: dict = {}
        reply = await client.request(EdidioClient.create_diagnostic_message(
            self._next_id(), DiagnosticMessageType.DIAGNOSTIC_SYSTEM_INFO))
        which = reply.WhichOneof("payload")
        if which and which.startswith("diag"):
            diag = getattr(reply, which)
            info["supportedFeatures"] = spektra_map.diag_to_supported_features(diag)
            info["firmwareVersion"] = getattr(diag, "firmware", "") or ""
            info["hardwareVersion"] = getattr(diag, "hardware", "") or ""
            info["vendorId"] = getattr(diag, "vendor_id", "") or ""
            info["activeProfile"] = getattr(diag, "selected_profile", 0) or 0
            lines = list(getattr(diag, "lines", []) or [])
            if lines:
                info["lineTypes"] = lines
        if "lineTypes" not in info:
            info["lineTypes"] = await self.read_line_types()
        # network (best-effort)
        try:
            nreply = await client.request(spektra_map._frame(
                self._next_id(), admin_message=pb.AdminMessage(
                    command=pb.AdminCommandType.GET,
                    target=pb.AdminPropertyType.NETWORK_PROPERTIES,
                    network_properties=pb.AdminNetworkPropertiesMessage())))
            if nreply.WhichOneof("payload") == "admin_message":
                info["network"] = spektra_map.network_to_dict(
                    nreply.admin_message.network_properties, current_ip=self.host,
                    device_name=await self.read_device_name(),
                    tls=getattr(self, "use_tls", False))
        except Exception:  # noqa: BLE001 — network read is best-effort
            pass
        return info

    async def read_admin(self, target: str, command: str = "GET", **payload):
        """Send an AdminMessage in the current protocol; returns the v2 reply."""
        return await v2.request(self._require(),
                                v2.admin(self._next_id(), command, target, **payload))

    async def read_device_name(self) -> str:
        """The controller's own name (DEVICE_NAME, up to 31 bytes on 1.6.3)."""
        try:
            r = await self.read_admin("DEVICE_NAME")
            if r.WhichOneof("payload") == "admin_message":
                return r.admin_message.data.string_data
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _load_template_edidio(self) -> dict:
        """Load the bundled controller-template eDIDIO skeleton (all UI-required
        fields present with valid defaults)."""
        import json
        import os
        path = os.path.join(os.path.dirname(__file__), "templates",
                            "controller_template.spektratpl.spektra")
        with open(path, encoding="utf-8") as fh:
            tpl = json.load(fh)
        return tpl["data"]  # exportType 'controller_template' -> data is the eDIDIO

    async def pull_project(self, mac: str | None = None) -> dict:
        """Read the device's full config and assemble a SpektraPlus-openable v3
        ``.spektra``. Starts from the bundled controller template (so every
        UI-required device field — supportedFeatures, network, dali/dmx/link,
        clock/location — is present and valid), then overlays the live device info
        and config sections."""
        self._require()
        counts = await self.read_system_counts()

        # Start from the complete template skeleton, then overlay real values.
        edidio = self._load_template_edidio()
        edidio.update(await self.read_device_info())
        edidio.update({
            "sequences": await self.pull_sequences(),
            "themes": await self.pull_themes(),
            "zones": await self.pull_zones(),
            "schedules": await self.pull_schedules(),
            "profiles": await self.pull_profiles(counts["profiles"]),
            "logicActions": await self.pull_logic(),
            "lists": await self.pull_lists(counts["lists"]),
            "translations": await self.pull_translations(),
            "burnIns": await self.pull_burnins(),
            "error": "",
        })

        mac = mac or self._resolve_mac()
        if isinstance(edidio.get("network"), dict):
            edidio["network"]["mac"] = mac
        now = int(datetime.now().timestamp() * 1000)
        raw = {
            "fileFormatVersion": 3,
            "appVersion": "spektra-ai-pull",
            "name": f"Pulled from {self.host}",
            "uid": str(now),
            "createdAt": now, "updatedAt": now, "lastOpenedAt": now,
            "notes": f"Pulled live from {self.host} by Spektra AI.",
            "colourPalette": [], "widgetPages": [],
            "targetZoneIndex": None, "targetEdidioMac": mac,
            "daliCommissioningPreferences": {
                "selectionVolume": 0.3, "turnOffWithdrawnDevices": False,
                "blockSelectionChangesInLivePreview": True,
                "livePreviewUsesMaxAndOff": True,
            },
            "syncData": {"syncStates": {}, "rollbackHistory": [], "syncQueue": []},
            "edidios": {mac: edidio},
        }
        # A fresh pull IS the device, so mark every section SYNCED in the ledger
        # (otherwise SpektraPlus shows everything UNSYNCED until it re-verifies).
        from . import sync
        from .spektra_file import SpektraProject
        sync.mark_synced(SpektraProject(raw=raw), mac, list(sync.SYNC_SECTIONS))
        return raw

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

    # --- push .spektra config to the device (file -> controller) ---
    # Indexed device sections: per-slot diff, one message per changed item.
    _INDEXED_BUILDERS = {
        "sequences": ("pull_sequences", spektra_map.sequence_to_message),
        "themes": ("pull_themes", spektra_map.theme_to_message),
        "zones": ("pull_zones", spektra_map.zone_to_message),
        "schedules": ("pull_schedules", spektra_map.schedule_to_message),
        "lists": (None, spektra_map.list_to_message),  # puller needs a count
    }
    # Per-profile sections: whole-profile Multi write when anything differs.
    _PROFILE_BUILDERS = {
        "inputs": ("pull_inputs", spektra_map.inputs_to_message),
        "outputs": ("pull_outputs", spektra_map.outputs_to_message),
    }

    async def identify(self) -> dict:
        """Who is on the other end: every MAC it answers to (discovery and network
        properties differ on an ADDICT: access point vs station), model and firmware.
        SpektraPlus checks this before every push and pull (a controller reflashed
        as another model would otherwise keep the old model in the project)."""
        client = self._require()
        macs = set()
        info = {"firmware": "", "hardware": ""}
        reply = await client.request(EdidioClient.create_diagnostic_message(
            self._next_id(), DiagnosticMessageType.DIAGNOSTIC_SYSTEM_INFO))
        which = reply.WhichOneof("payload")
        if which and which.startswith("diag"):
            diag = getattr(reply, which)
            info["firmware"] = getattr(diag, "firmware", "") or ""
            info["hardware"] = getattr(diag, "hardware", "") or ""
        try:
            nreply = await client.request(spektra_map._frame(
                self._next_id(), admin_message=pb.AdminMessage(
                    command=pb.AdminCommandType.GET,
                    target=pb.AdminPropertyType.NETWORK_PROPERTIES,
                    network_properties=pb.AdminNetworkPropertiesMessage())))
            if nreply.WhichOneof("payload") == "admin_message":
                mac = nreply.admin_message.network_properties.MAC
                if mac:
                    macs.add(_norm_mac(mac))
        except Exception:  # noqa: BLE001 - ADDICT/older firmware: discovery still works
            pass
        found = self._resolve_mac()
        if not found.startswith("PULLED:"):
            macs.add(_norm_mac(found))
        info["macs"] = sorted(macs)
        return info

    async def check_target(self, project, target_mac: str = "") -> tuple:
        """Pick the project's controller that matches the connected device.
        Returns (mac, warnings) or raises ValueError with the reason. A multi-
        controller file pushes only the controller that is actually connected."""
        ident = await self.identify()
        live = set(ident["macs"])
        file_macs = list(project.macs)
        if target_mac:
            mac = next((m for m in file_macs if _norm_mac(m) == _norm_mac(target_mac)), None)
            if mac is None:
                raise ValueError(f"{target_mac} is not a controller in this file "
                                 f"({', '.join(file_macs)}).")
        else:
            matches = [m for m in file_macs if _norm_mac(m) in live]
            if not matches:
                raise ValueError(
                    f"The connected controller ({', '.join(ident['macs']) or 'unknown MAC'}) "
                    f"is not in this file ({', '.join(file_macs)}). Connect to the right "
                    "controller, or pass target_mac to push that file entry to this one.")
            mac = matches[0]
        warnings = []
        ed = project.edidio(mac)
        f_hw, l_hw = (ed.get("hardwareVersion") or ""), ident["hardware"]
        if f_hw and l_hw and f_hw.split("-")[0] != l_hw.split("-")[0]:
            raise ValueError(
                f"Model changed: the file has {f_hw.split('-')[0]}, the controller is "
                f"{l_hw.split('-')[0]} (reflashed for another model?). Pull the controller "
                "first and re-apply the changes, so slot counts match.")
        f_fw = ed.get("firmwareVersion") or ""
        if f_fw and ident["firmware"] and f_fw != ident["firmware"]:
            warnings.append(f"firmware is now {ident['firmware']} (file says {f_fw}).")
        return mac, warnings

    @staticmethod
    def _same(section: str, a, b) -> bool:
        """Equal as SpektraPlus judges it: the canonical sync hash (ignores uuids,
        display units, trailing zero channels, NO_COMMAND leftovers, ...)."""
        from . import sync
        return sync.hash_section(a, section) == sync.hash_section(b, section)

    async def build_push_messages(self, project, sections=("sequences", "themes"),
                                  target_mac: str = ""):
        """Diff one controller of a project against the live device and build the
        messages for only what changed. Returns (messages, summary_lines, is_dali, mac).

        The controller is the file entry whose MAC matches the connected device (or
        ``target_mac``); a model change refuses the push. Items compare by the sync
        hash, so unchanged config is skipped. A DEVICE_SAVE ends every push: the
        controller confirms the save only when it is complete, and SpektraPlus shows
        Synced only after that ack."""
        from .spektra_file import _is_configured  # local import avoids a cycle

        self._require()
        mac, warnings = await self.check_target(project, target_mac)
        ed = project.edidio(mac)
        zones = await self.pull_zones()
        is_dali = any(z.get("protocol") == 0 for z in zones)
        list_count = None       # lazily fetched only if pushing lists
        meta = None             # lazily fetched only if pushing sensors

        messages, summary = [], [f"note: {w}" for w in warnings]
        zones_written = False
        restore_profile = None   # set if a sensor-clear switched the active profile
        for section in sections:
            if section in self._INDEXED_BUILDERS:
                before = len(messages)
                puller_name, builder = self._INDEXED_BUILDERS[section]
                if section == "lists":
                    if list_count is None:
                        list_count = (await self.read_system_counts())["lists"]
                    live_list = await self.pull_lists(list_count)
                elif section == "zones":
                    live_list = zones
                else:
                    live_list = await getattr(self, puller_name)()
                live = {it["index"]: it for it in live_list}
                changed = []
                for item in ed.get(section) or []:
                    if not _is_configured(section, item):
                        continue
                    idx = item.get("index")
                    if idx in live and self._same(section, [live[idx]], [item]):
                        continue
                    changed.append(item)
                if section == "lists":
                    # Writing list 0 erases every list's steps: rewrite the rest too.
                    for item in spektra_map.lists_write_order(changed, live_list):
                        idx = item.get("index")
                        why = ("update" if item in changed else
                               "rewrite (list 0 write erases all list steps)")
                        messages.extend(spektra_map.list_to_messages(item, self._next_id))
                        summary.append(f'{why} lists[{idx}] "{item.get("name", "")}" '
                                       f'({len(item.get("steps") or [])} steps)')
                    continue
                for item in changed:
                    idx = item.get("index")
                    change = "add" if idx not in live else "update"
                    messages.append(builder(item, self._next_id(), is_dali))
                    summary.append(f'{change} {section}[{idx}] "{item.get("name", "")}"')
                if section == "zones" and len(messages) > before:
                    zones_written = True   # zones are RAM-only until a SAVE

            elif section in self._PROFILE_BUILDERS:
                puller_name, builder = self._PROFILE_BUILDERS[section]
                for p, prof in enumerate(ed.get("profiles") or []):
                    file_items = prof.get(section) or []
                    if not file_items:
                        continue
                    live_items = await getattr(self, puller_name)(p)
                    if self._same(section, [live_items], [file_items]):
                        continue
                    messages.append(builder(p, file_items, self._next_id()))
                    summary.append(f"update {section} profile {p} ({len(file_items)} items)")

            elif section == "logicActions":
                file_logic = ed.get("logicActions") or []
                if file_logic and not self._same(section, await self.pull_logic(), file_logic):
                    messages.append(spektra_map.logic_to_message(file_logic, self._next_id()))
                    summary.append(f"update logicActions ({len(file_logic)} items)")

            elif section == "sensors":
                if meta is None:
                    meta = await self.read_system_counts()
                supports_coop = spektra_map.version_gte(
                    meta["firmware"], spektra_map.COOP_GROUPING_FIRMWARE)
                active = meta["active"]
                for p, prof in enumerate(ed.get("profiles") or []):
                    file_sensors = prof.get("sensors") or []
                    if self._same(section, [await self.pull_sensors(p)], [file_sensors]):
                        continue
                    if file_sensors:
                        # Program: index 0 first (firmware treats it as a batch wipe).
                        for s in sorted(file_sensors, key=lambda x: x["index"]):
                            messages.append(spektra_map.sensor_to_message(
                                s, p, self._next_id(), supports_coop))
                        summary.append(f"update sensors profile {p} ({len(file_sensors)} items)")
                    else:
                        # Clear: RESET is active-profile scoped and does not save on
                        # its own -> switch profile, RESET, DEVICE_SAVE.
                        if p != active:
                            messages.append(spektra_map.change_profile_message(
                                self._next_id(), p))
                            restore_profile = active
                        messages.append(spektra_map.reset_sensors_message(self._next_id()))
                        messages.append(spektra_map.device_save_message(self._next_id()))
                        summary.append(f"clear sensors profile {p}")

            elif section in ("controlTranslations", "burnIns"):
                key = "translations" if section == "controlTranslations" else "burnIns"
                file_items = ed.get(key) or []
                if not file_items:
                    continue
                live_items = await (self.pull_translations() if key == "translations"
                                    else self.pull_burnins())
                if self._same(section, live_items, file_items):
                    continue
                if key == "translations":
                    messages.append(spektra_map.translations_to_message(
                        file_items, self._next_id()))
                    summary.append(f"update DMX-to-DALI translations ({len(file_items)})")
                else:
                    messages.append(spektra_map.burnins_to_message(file_items, self._next_id()))
                    summary.append(f"update burn-ins ({len(file_items)}) - restarts their "
                                   "countdowns")

            elif section == "daliInputs":
                for p, prof in enumerate(ed.get("profiles") or []):
                    file_di = prof.get("daliInputs") or []
                    if not file_di:
                        continue
                    if self._same(section, [await self.pull_daliinputs(p)], [file_di]):
                        continue
                    messages.append(spektra_map.daliinputs_to_message(p, file_di, self._next_id()))
                    summary.append(f"update daliInputs profile {p} ({len(file_di)} items)")

        if any(not m.startswith("note:") for m in summary):
            # Persist RAM-only writes, undo any profile switch, then save everything.
            if zones_written:
                messages.append(spektra_map.zone_save_message(self._next_id()))
                summary.append("save zones to flash")
            if restore_profile is not None:
                messages.append(spektra_map.change_profile_message(
                    self._next_id(), restore_profile))
                summary.append(f"restore active profile {restore_profile}")
            messages.append(spektra_map.device_save_message(self._next_id()))
            summary.append("save configuration (DEVICE_SAVE)")
        return messages, summary, is_dali, mac

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

    # --- live event stream (separate connection, background reader) ---
    async def start_events(self, categories=DEFAULT_CATEGORIES, *, event_stream=None):
        """Begin watching live events on a dedicated connection to the current host.
        ``event_stream`` is injectable for tests (defaults to a real EventStream)."""
        if self.host is None:
            raise RuntimeError("Connect to a controller before watching events.")
        if self._events is not None:
            await self._events.stop()
        if event_stream is None:
            # Firmware >= 1.4.0 uses Event Stream v2 (tag 77); older uses legacy tag 34.
            fw = (await self.read_system_counts()).get("firmware", "")
            use_v2 = spektra_map.version_gte(fw, "1.4.0") if fw else True
            # A second connection, made the same way as ours (port, TLS context).
            host, port, tls = self.host, getattr(self, "port", 23), getattr(self, "use_tls", False)
            event_stream = EventStream(
                host, port, tls, on_event=self.notifications.handle_event, use_v2=use_v2,
                client_factory=lambda: self._factory(host, port, tls))
        self._events = event_stream
        await self._events.start(categories)
        if self._deadline_task is None:
            self._deadline_task = asyncio.ensure_future(self._deadline_loop())
        return self._events.categories

    async def _deadline_loop(self, interval: float = 30.0):
        """Periodically fire deadline notifications whose time passed without a match."""
        try:
            while True:
                await asyncio.sleep(interval)
                await self.notifications.check_deadlines()
        except asyncio.CancelledError:
            pass

    async def stop_events(self):
        if self._deadline_task is not None:
            self._deadline_task.cancel()
            self._deadline_task = None
        if self._events is not None:
            await self._events.stop()
            self._events = None

    def recent_events(self, since_seq: int = 0, limit: int = 50) -> dict:
        if self._events is None or not self._events.running:
            return {"watching": False, "events": [], "last_seq": 0}
        return {"watching": True, "categories": list(self._events.categories),
                "events": self._events.recent(since_seq, limit),
                "last_seq": self._events.last_seq}

    # --- controller line types + reboot (Phase 4 setup) ---
    async def read_line_types(self) -> list:
        """Read the physical line configuration (list of LineType ints; 1=DALI, 2=DMX)."""
        client = self._require()
        frame = spektra_map._frame(self._next_id(), admin_message=pb.AdminMessage(
            command=pb.AdminCommandType.GET, target=pb.AdminPropertyType.CONTROLLER_LINES,
            controller_lines=pb.AdminControllerLinesMessage()))
        reply = await client.request(frame)
        if reply.WhichOneof("payload") == "admin_message":
            return list(reply.admin_message.controller_lines.lines)
        return []

    async def set_line_types(self, lines: list) -> dict:
        """SET the whole line-type array (e.g. [2, 1] = line1 DMX, line2 DALI). A reboot
        is required for it to take effect."""
        client = self._require()
        frame = spektra_map._frame(self._next_id(), admin_message=pb.AdminMessage(
            command=pb.AdminCommandType.SET, target=pb.AdminPropertyType.CONTROLLER_LINES,
            controller_lines=pb.AdminControllerLinesMessage(lines=[int(x) for x in lines])))
        return self._ack_summary(await client.request(frame))

    async def reboot(self) -> dict:
        """Reboot the controller (RUN DEVICE_REBOOT). Needed after a line-type change."""
        client = self._require()
        frame = spektra_map._frame(self._next_id(), admin_message=pb.AdminMessage(
            command=pb.AdminCommandType.RUN, target=pb.AdminPropertyType.DEVICE_REBOOT))
        try:
            ack = self._ack_summary(await client.request(frame))
        except Exception:  # noqa: BLE001 — device may drop before acking the reboot
            ack = {"ok": True, "code": "reboot (no ack; device dropped)"}
        return ack

    async def wait_for_reboot(self, *, grace: float = 8.0, timeout: float = 120.0,
                              poll: float = 3.0) -> bool:
        """Wait out the pre-power-cycle idle, then reconnect once the device is back.
        Returns True if reconnected within the budget (mirrors deviceReboot.ts)."""
        host = self.host
        port = getattr(self, "port", None) or (self._client.port if self._client else 23)
        tls = getattr(self, "use_tls", False)   # reconnect the way we were connected
        try:
            await self._client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        self._client = None
        await asyncio.sleep(grace)
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                await self.connect(host, port, tls)
                if self.connected:
                    return True
            except Exception:  # noqa: BLE001 — still rebooting
                pass
            await asyncio.sleep(poll)
        return False

    # --- DALI commissioning / query / colour (Phase 4) ---
    async def dali_query(self, line: int, address: int, query: int, arg=None) -> dict:
        client = self._require()
        reply = await client.request(dali.query_message(self._next_id(), line, address,
                                                        query, arg))
        return dali.decode_query(reply)

    async def dali_scan(self, line: int, max_address: int = dali.MAX_SHORT_ADDRESS) -> list:
        """Scan short addresses on a line; return those whose gear replies to a status
        query, with decoded status flags. Read-only."""
        present = []
        for addr in range(max_address + 1):
            res = await self.dali_query(line, addr, pb.DALIQueryType.DALI_QUERY_STATUS)
            if res.get("responded"):
                present.append({"address": addr, "status": dali.decode_status(res["data"]),
                                "raw_status": res["data"]})
        return present

    async def dali_set_level(self, line: int, address: int, level: int) -> None:
        client = self._require()
        await client.set_dali_arc_level(self._next_id(), dali.line_mask(line), address, level)

    async def dali_identify(self, line: int, address: int, blinks: int = 3) -> None:
        """Blink a fixture (max/off) so an installer can find it physically."""
        import asyncio as _a
        for _ in range(blinks):
            await self.dali_set_level(line, address, 254)
            await _a.sleep(0.4)
            await self.dali_set_level(line, address, 0)
            await _a.sleep(0.4)

    async def _dali_send_seq(self, frames: list) -> list:
        return await self.send_and_ack(frames)

    async def dali_colour_temperature(self, line: int, address: int, mirek: int) -> list:
        return await self._dali_send_seq(
            dali.colour_temperature_messages(self._next_id, line, address, mirek))

    async def dali_rgbwaf(self, line: int, address: int, rgb: list, waf: list,
                          arc_level: int = 254) -> list:
        return await self._dali_send_seq(
            dali.rgbwaf_messages(self._next_id, line, address, rgb, waf, arc_level))

    async def _addressing_pass(self, line, *, readdress, is24bit, max_devices=64):
        """One addressing pass: START then CONTINUE until NO_NEW_DEVICE. Returns the
        list of short addresses assigned this pass (or an error)."""
        client = self._require()
        start = await client.request(dali.addressing_message(
            self._next_id(), line, initialisation=True, readdress=readdress,
            is24bit=is24bit))
        res = dali.decode_addressing(start)
        if not res["ok"]:
            return {"ok": False, "addressed": [], "error": res["error"]}
        addressed, errors = [], []
        for _ in range(max_devices):
            step = await client.request(dali.addressing_message(
                self._next_id(), line, initialisation=False, is24bit=is24bit))
            r = dali.decode_addressing(step)
            if r["finished"]:
                break
            if not r["ok"]:
                # A VERIFY/SEARCH collision is recoverable — end this pass and let a
                # later ADDRESS_NEW pass catch the stragglers, rather than aborting.
                errors.append(r["error"])
                break
            addressed.append(r.get("addressed"))
        return {"ok": True, "addressed": addressed, "error": None, "collisions": errors}

    async def dali_commission(self, line: int, *, readdress: bool = False,
                              is24bit: bool = False, passes: int = 3) -> dict:
        """Commission a DALI line over multiple passes (DALI addressing can miss gear
        on a single pass). Pass 1 uses the requested mode (READDRESS_ALL clears first);
        subsequent passes use ADDRESS_NEW to catch any gear still without an address,
        stopping early once a pass finds nothing. WRITES device addresses."""
        pass_results, empty_streak = [], 0
        for i in range(max(1, passes)):
            r = await self._addressing_pass(
                line, readdress=(readdress and i == 0), is24bit=is24bit)
            if not r["ok"] and not pass_results:
                return {"ok": False, "passes": pass_results, "error": r["error"]}
            pass_results.append(r["addressed"])
            # Stop once ADDRESS_NEW passes stop finding gear (two empties in a row,
            # to ride out a transient collision that yielded nothing that pass).
            if i > 0 and not r["addressed"]:
                empty_streak += 1
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0
        total = await self.dali_scan(line)
        return {"ok": True, "passes": pass_results,
                "total_addressed": len(total),
                "addresses": [d["address"] for d in total]}

    # Inter-frame pacing for fire-and-forget DALI config sends. Each 16-bit frame
    # needs ~15-30ms of bus time; sending a burst with no gap floods the controller's
    # DALI TX queue and stalls the link. This paces sends to bus speed.
    DALI_FRAME_PACE = 0.04  # seconds between config frames

    async def _send_config_twice(self, line: int, frame16: int) -> None:
        """Send a DALI config frame twice (spec requires two frames), paced to bus
        timing so a burst can't overflow the controller."""
        client = self._require()
        msg = dali.config_message(self._next_id(), line, frame16)
        await client.send_protobuf_message(msg)
        await asyncio.sleep(self.DALI_FRAME_PACE)
        await client.send_protobuf_message(msg)
        await asyncio.sleep(self.DALI_FRAME_PACE)

    async def _send_dtr0(self, line: int, value: int) -> None:
        client = self._require()
        await client.send_protobuf_message(
            dali.config_message(self._next_id(), line, dali.dtr0_set_frame16(value)))
        await asyncio.sleep(self.DALI_FRAME_PACE)

    async def dali_add_to_group(self, line: int, addresses: list, group: int) -> None:
        """Add each short address to DALI group (0-15). Persisted in the gear."""
        for a in addresses:
            await self._send_config_twice(line, dali.add_to_group_frame16(a, group))

    async def dali_set_scene_level(self, line: int, scene: int, level: int,
                                   addresses: list | None = None) -> None:
        """Store `level` (0-254) as DALI `scene` (0-15). Broadcasts to all gear when
        `addresses` is None, else per address. DTR0 is set first, then STORE_SCENE x2."""
        self._require()
        # DTR0 = level (broadcast special command; loads all gear's DTR0).
        await self._send_dtr0(line, level)
        if addresses is None:
            await self._send_config_twice(
                line, dali.store_scene_frame16(0, scene, broadcast=True))
        else:
            for a in addresses:
                await self._send_config_twice(line, dali.store_scene_frame16(a, scene))

    async def dali_set_all_scenes(self, line: int, step: int = 10,
                                  addresses: list | None = None) -> list:
        """Set scenes 0-15 to multiples of `step` (scene N = N*step) on all gear
        (or the given addresses). Returns the (scene, level) pairs written."""
        written = []
        for scene in range(16):
            level = min(scene * step, 254)
            await self.dali_set_scene_level(line, scene, level, addresses)
            written.append((scene, level))
        return written

    async def dali_set_fade_time(self, line: int, seconds: float,
                                 addresses: list | None = None) -> int:
        """Set the DALI fade time (nearest standard code) on all gear (or given
        addresses). Returns the code used. DTR0 = code, then SET_FADE_TIME x2."""
        self._require()
        code = dali.fade_time_to_code(seconds)
        await self._send_dtr0(line, code)
        if addresses is None:
            await self._send_config_twice(
                line, dali.set_fade_time_frame16(0, broadcast=True))
        else:
            for a in addresses:
                await self._send_config_twice(line, dali.set_fade_time_frame16(a))
        return code

    async def _query_retry(self, line: int, address: int, query: int, retries: int = 3):
        """A DALI query that retries when the gear doesn't answer — a single reply can
        be missed on a busy bus, which would otherwise look like 'no device'."""
        res = {"responded": False}
        for _ in range(retries + 1):
            res = await self.dali_query(line, address, query)
            if res.get("responded"):
                return res
        return res

    async def dali_query_groups(self, line: int, address: int) -> list:
        """Return the DALI groups (0-15) a gear belongs to (via GROUPS_0_7 / 8_15).
        Retries each query so a transient miss doesn't report false-empty membership."""
        groups = []
        for base, q in ((0, pb.DALIQueryType.DALI_QUERY_GROUPS_0_7),
                        (8, pb.DALIQueryType.DALI_QUERY_GROUPS_8_15)):
            res = await self._query_retry(line, address, q)
            if res.get("responded"):
                for bit in range(8):
                    if res["data"] & (1 << bit):
                        groups.append(base + bit)
        return groups

    async def dali_read_memory_byte(self, line: int, address: int, bank: int,
                                    loc: int) -> int | None:
        """Read one memory-bank byte from a gear (DTR1=bank, DTR0=loc, then query)."""
        client = self._require()
        await client.send_protobuf_message(
            dali.dtr_frame(self._next_id(), line, dali._DTR1_OPCODE, bank))
        await client.send_protobuf_message(
            dali.dtr_frame(self._next_id(), line, dali._DTR0_OPCODE, loc))
        r = dali.decode_query(await client.request(
            dali.read_dtr_query_message(self._next_id(), line, address)))
        return r["data"] if r["responded"] else None

    async def dali_read_serial(self, line: int, address: int, *, retries: int = 2) -> str | None:
        """Read a gear's serial (Bank 1, 0x09-0x10) as a hex string — shared across
        all channels of one physical driver, so it identifies the fixture. Retries a
        few times because a single memory read can glitch on a busy bus."""
        for _ in range(retries + 1):
            out, ok = [], True
            for loc in range(dali.SERIAL_START, dali.SERIAL_END + 1):
                b = await self.dali_read_memory_byte(line, address, dali.SERIAL_BANK, loc)
                if b is None:
                    ok = False
                    break
                out.append(b)
            if ok:
                return ":".join("%02X" % b for b in out)
        return None

    async def dali_group_devices(self, line: int) -> list:
        """Scan a line and group addressed gear into physical devices by serial number.
        Returns a list of {serial, channels:[addresses]} — the fixture view."""
        found = await self.dali_scan(line)
        groups: dict = {}
        order: list = []
        for d in found:
            addr = d["address"]
            serial = await self.dali_read_serial(line, addr) or f"unknown-{addr}"
            if serial not in groups:
                groups[serial] = []
                order.append(serial)
            groups[serial].append(addr)
        return [{"serial": s, "channels": sorted(groups[s])} for s in order]

    # --- individual (non-zone) control ---
    async def send_dali(self, line_mask, address, arc_level):
        client = self._require()
        await client.set_dali_arc_level(self._next_id(), line_mask, address, arc_level)

    async def send_dmx(self, universe_mask, channel, levels):
        client = self._require()
        await client.set_dmx_level(self._next_id(), 0, universe_mask, channel, list(levels))


_ACK_NAMES = {v.number: v.name for v in pb.AckMessageType.DESCRIPTOR.values}


def _norm_mac(mac: str) -> str:
    return (mac or "").replace("-", ":").upper()


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
