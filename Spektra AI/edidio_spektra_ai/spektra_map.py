"""Map eDIDIO protobuf messages -> SpektraPlus ``.spektra`` JSON dicts.

This mirrors the *reverse* mappers in ``SpektraPlus/src/helpers/messageMappings.ts``
(``mapPb*ToEdidio*``) so a live config pulled off a controller lands in exactly the
field names/units the app uses — the point being to reuse SpektraPlus's mapping, not
reinvent it. Kept as pure functions over protobuf messages for easy testing.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb
from edidio_control_py import EdidioClient

# --- small enums mirrored from SpektraPlus/shared/src/constants.ts ---
_TIME_MS, _TIME_S, _TIME_MIN, _TIME_HR = 0, 1, 2, 3
_DIR_FORWARD, _DIR_REVERSE, _DIR_CYCLE = 0, 1, 2

# LightType (constants.ts) inferred from a channel's hex colour.
_LIGHT_BY_HEX = {
    "#FF0000": 0, "#00FF00": 1, "#0000FF": 2, "#FFD580": 3, "#AAD6FF": 4,
    "#FFBF00": 5, "#808080": 6, "#000000": 8,
}
_LIGHT_CUSTOM = 7


def decode_date(encoded: int) -> str:
    """Decode a packed device date int -> 'YYYY-MM-DD' (messageMappings.decodeDate)."""
    year = 2000 + ((encoded >> 24) & 0xFF)
    month = ((encoded >> 16) & 0xFF)
    day = (encoded >> 8) & 0xFF
    return f"{year:04d}-{month:02d}-{day:02d}"


def decode_time(encoded: int) -> str:
    """Decode a packed device time int -> 'HH:MM:SS' (messageMappings.decodeTime)."""
    hours = (encoded >> 16) & 0xFF
    minutes = (encoded >> 8) & 0xFF
    seconds = encoded & 0xFF
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def number_to_hex(num: int) -> str:
    return "#" + format(num & 0xFFFFFF, "06X")


def infer_light_type(hex_colour: str) -> int:
    return _LIGHT_BY_HEX.get(hex_colour.upper(), _LIGHT_CUSTOM)


def _num(value):
    """Return an int when the value is whole, else the float (matches JSON output)."""
    return int(value) if float(value).is_integer() else value


def find_fade_time_best_fit(fade_by_10ms: int) -> tuple:
    """Pick the most natural (value, unit) for a fade time (no existing-unit hint)."""
    ms = (fade_by_10ms or 0) * 10
    if ms >= 3600000:
        if ms % 3600000 == 0:
            return (_num(ms / 3600000), _TIME_HR)
        return (_num(ms / 60000), _TIME_MIN)
    if ms >= 60000:
        if ms % 60000 == 0:
            return (_num(ms / 60000), _TIME_MIN)
        return (_num(ms / 1000), _TIME_S)
    if ms >= 1000:
        if ms % 1000 == 0:
            return (_num(ms / 1000), _TIME_S)
        return (_num(ms), _TIME_MS)
    return (_num(ms), _TIME_MS)


def _map_time_unit(unit: int) -> int:
    return {0: _TIME_MS, 1: _TIME_S, 2: _TIME_MIN}.get(unit, _TIME_S)


def _colour(pb_colour) -> dict:
    vals = list(pb_colour.channel_value) if pb_colour and pb_colour.channel_value else []
    return {"channelValues": vals}


# --- public mappers (pb message -> .spektra dict) ---

def trigger_to_dict(pb) -> dict:
    """TriggerMessage -> EdidioTrigger command dict."""
    NO_COMMAND = 254
    if pb is None or getattr(pb, "type", NO_COMMAND) == NO_COMMAND:
        return {"commandtype": NO_COMMAND, "zone": 0, "linemask": 0,
                "target": 0, "value": 0, "query": 0}
    return {"commandtype": pb.type, "zone": pb.zone, "linemask": pb.line_mask,
            "target": pb.target_index, "value": pb.value, "query": pb.query_index}


def schedule_to_dict(pb) -> dict:
    """AlarmMessage -> EdidioSchedule dict."""
    def event(trigger, astro, tstruct, offset_before):
        return {
            "command": trigger_to_dict(trigger),
            "type": astro or 0,
            "date": decode_date(getattr(tstruct, "date", 0) if tstruct else 0),
            "time": decode_time(getattr(tstruct, "time", 0) if tstruct else 0),
            "offsetBefore": offset_before,
        }

    return {
        "name": f"Schedule {pb.index + 1}",
        "index": pb.index,
        "IsEnabled": pb.enabled,
        "repeat": pb.repeat or 0,
        "monthsMask": pb.repeat_month_bitmask or 0,
        "weekdaysMask": pb.repeat_day_bitmask or 0,
        "yearly": pb.yearly,
        "startEvent": event(pb.start_trigger, pb.astro_start,
                            pb.start_time, pb.start_offset_is_before),
        "endEvent": event(pb.end_trigger, pb.astro_end,
                          pb.end_time, pb.end_offset_is_before),
        "endEventIsActive": _end_active(pb),
        "error": None,
    }


def _end_active(pb) -> bool:
    date = getattr(pb.end_time, "date", 0) or 0
    time = getattr(pb.end_time, "time", 0) or 0
    end_hours = (time >> 16) & 0xFF
    disabled = (date == 0 and time == 0) or end_hours > 24
    return not disabled


def sequence_to_dict(pb) -> dict:
    """SpektraSequenceConfigMessage -> EdidioSequenceData dict."""
    direction = _DIR_FORWARD
    if pb.is_reverse_direction:
        direction = _DIR_REVERSE
    if pb.is_cycle_direction:
        direction = _DIR_CYCLE

    fade_time, fade_unit = find_fade_time_best_fit(pb.fade_time_by_10ms or 0)

    randomised = [i for i in range(32) if (pb.random_types_mask or 0) & (1 << i)]

    return {
        "name": pb.title or f"Sequence {pb.index + 1}",
        "index": pb.index,
        "backgroundColour": {"channelValues": list(pb.args) if pb.args else []},
        "colours": [_colour(c) for c in pb.colours],
        "fadeTime": fade_time,
        "fadeTimeUnit": fade_unit,
        "hasRandomColourOrder": pb.has_random_colour_order,
        "isRandom": bool(pb.is_randomised_type),
        "randomisedSequenceTypes": randomised,
        "scheduledDates": [],
        "direction": direction,
        "range": pb.range or 0,
        "sequenceType": pb.type,
        "timePerColour": pb.time_per_colour or 0,
        "timePerColourUnit": _map_time_unit(pb.time_per_colour_unit or 1),
        "timePerStep": pb.time_per_step or 0,
        "timePerStepUnit": _map_time_unit(pb.time_per_step_unit or 1),
        "transitionType": pb.transition or 0,
        "presetSequenceID": None,
        "uuid": str(_uuid.uuid4()),   # app render key; transient in the sync hash
    }


def theme_to_dict(pb) -> dict:
    """SpektraThemeConfigMessage -> EdidioThemeData dict."""
    return {
        "name": pb.title or f"Theme {pb.index + 1}",
        "index": pb.index,
        "colours": [_colour(c) for c in pb.colours],
        "scheduledDates": [],
        "uuid": str(_uuid.uuid4()),   # app render key; transient in the sync hash
    }


# --- forward mappers (.spektra dict -> protobuf message frame bytes) ----------
# Mirror messageMappings.ts mapEdidio*ToPb* so a file pushes back faithfully.

_UNIT_TO_MS = {_TIME_MS: 1, _TIME_S: 1000, _TIME_MIN: 60000, _TIME_HR: 3600000}


def get_fade_time_by_10ms(fade_time, unit) -> int:
    """Inverse of find_fade_time_best_fit: (value, unit) -> integer 10ms units."""
    ms = (fade_time or 0) * _UNIT_TO_MS.get(unit, 1)
    return round(ms / 10)


def cap_value(v, is_dali: bool) -> int:
    """Clamp a channel value to 254 on DALI devices (255 = MASK); DMX allows 255."""
    v = int(v)
    return min(v, 254) if is_dali else v


def _colours_list(colours, is_dali: bool) -> list:
    return [[cap_value(x, is_dali) for x in (c.get("channelValues") or [])]
            for c in (colours or [])]


def sequence_to_message(seq: dict, message_id: int, is_dali: bool = False) -> bytes:
    """EdidioSequenceData dict -> SpektraSequenceConfigMessage frame."""
    mask = 0
    for t in seq.get("randomisedSequenceTypes") or []:
        mask |= 1 << int(t)
    bg = (seq.get("backgroundColour") or {}).get("channelValues") or []
    args = [cap_value(bg[i], is_dali) if i < len(bg) else 0 for i in range(5)]
    direction = seq.get("direction", 0)
    return EdidioClient.create_spektra_sequence_message(
        message_id,
        index=int(seq["index"]),
        seq_type=int(seq.get("sequenceType", 0)),
        colours=_colours_list(seq.get("colours"), is_dali),
        transition=int(seq.get("transitionType", 0)),
        fade_time_by_10ms=get_fade_time_by_10ms(seq.get("fadeTime", 0),
                                                seq.get("fadeTimeUnit", 0)),
        time_per_colour=int(seq.get("timePerColour", 0)),
        time_per_colour_unit=int(seq.get("timePerColourUnit", 0)),
        time_per_step=int(seq.get("timePerStep", 0)),
        time_per_step_unit=int(seq.get("timePerStepUnit", 0)),
        range=int(seq.get("range", 0)),
        is_randomised_type=1 if seq.get("isRandom") else 0,
        random_types_mask=mask,
        is_reverse_direction=1 if direction == _DIR_REVERSE else 0,
        is_cycle_direction=1 if direction == _DIR_CYCLE else 0,
        title=str(seq.get("name", "")),
        has_random_colour_order=bool(seq.get("hasRandomColourOrder", False)),
        args=args,
    )


def theme_to_message(theme: dict, message_id: int, is_dali: bool = False) -> bytes:
    """EdidioThemeData dict -> SpektraThemeConfigMessage frame."""
    return EdidioClient.create_spektra_theme_message(
        message_id,
        index=int(theme["index"]),
        colours=_colours_list(theme.get("colours"), is_dali),
        title=str(theme.get("name", "")),
    )


def encode_date(date_string: str) -> int:
    """'YYYY-MM-DD' -> packed device date int (inverse of decode_date; 0 if invalid).
    Packs year-2000, month, day, ISO weekday (Mon=1..Sun=7), mirroring encodeDate."""
    try:
        d = datetime.strptime(date_string, "%Y-%m-%d")
    except (ValueError, TypeError):
        return 0
    enc = ((d.year - 2000) & 0xFF) << 24
    enc |= (d.month & 0xFF) << 16
    enc |= (d.day & 0xFF) << 8
    enc |= d.isoweekday() & 0xFF          # Mon=1 .. Sun=7
    return enc


def encode_time(time_string: str) -> int:
    """'HH:MM:SS' -> packed device time int (inverse of decode_time; 0 if invalid)."""
    parts = str(time_string).split(":")
    if len(parts) != 3:
        return 0
    try:
        h, m, s = (int(p) for p in parts)
    except ValueError:
        return 0
    return ((h & 0xFF) << 16) | ((m & 0xFF) << 8) | (s & 0xFF)


def hex_to_number(hex_colour: str) -> int:
    return int(str(hex_colour).lstrip("#"), 16)


def _trigger_params(cmd: dict) -> dict:
    """.spektra command dict -> the proto-field keys create_alarm_message expects."""
    cmd = cmd or {}
    return {
        "type": cmd.get("commandtype", 254),
        "zone": cmd.get("zone", 0),
        "line_mask": cmd.get("linemask", 0),
        "target_index": cmd.get("target", 0),
        "value": cmd.get("value", 0),
        "query_index": cmd.get("query", 0),
    }


def schedule_to_message(sched: dict, message_id: int, is_dali: bool = False) -> bytes:
    """EdidioSchedule dict -> AlarmMessage frame (mirrors mapEdidioScheduleToPbAlarm)."""
    start = sched.get("startEvent") or {}
    end = sched.get("endEvent") or {}
    end_active = sched.get("endEventIsActive", False)
    no_command = {"type": 254}
    return EdidioClient.create_alarm_message(
        message_id,
        index=int(sched["index"]),
        enabled=bool(sched.get("IsEnabled", False)),
        repeat=int(sched.get("repeat", 0)),
        repeat_day_bitmask=int(sched.get("weekdaysMask", 0)),
        repeat_month_bitmask=int(sched.get("monthsMask", 0)),
        yearly=bool(sched.get("yearly", False)),
        start_trigger=_trigger_params(start.get("command")),
        astro_start=int(start.get("type", 0)),
        start_date=encode_date(start.get("date", "")),
        start_time=encode_time(start.get("time", "")),
        start_offset_is_before=bool(start.get("offsetBefore", False)),
        end_trigger=_trigger_params(end.get("command")) if end_active else no_command,
        astro_end=int(end.get("type", 0)),
        end_date=encode_date(end.get("date", "")),
        end_time=encode_time(end.get("time", "")),
        end_offset_is_before=bool(end.get("offsetBefore", False)),
    )


def _frame(message_id: int, **field) -> bytes:
    """Serialise + frame an EdidioMessage (0xCD + 2-byte length), for messages the
    engine has no dedicated builder for (e.g. zone settings)."""
    body = pb.EdidioMessage(message_id=message_id, **field).SerializeToString()
    length = len(body)
    return bytes([0xCD, (length >> 8) & 0xFF, length & 0xFF]) + body


def zone_to_message(zone: dict, message_id: int, is_dali: bool = False) -> bytes:
    """EdidioZoneData dict -> SpektraSettingMessage frame (mirrors
    mapEdidioZoneDataToPbSpektraSettings). No engine builder exists, so framed here."""
    settings = pb.SpektraSettingMessage(
        zone=int(zone["index"]),
        start_address=int(zone.get("startAddress", 0)),
        line_or_universe_mask=int(zone.get("linemask", 0)),
        protocol=int(zone.get("protocol", 0)),
        number_of_lights=int(zone.get("numLights", 0)),
        channels_per_light=int(zone.get("numChannels", 0)),
        channel_colours=[hex_to_number(c) for c in zone.get("channelColours", [])],
        unscheduled_behaviour=int(zone.get("unscheduledBehaviourType", 0)),
        line_addressing=int(zone.get("multiLineAddressing", 0)),
        zone_scale_factor=zone.get("scaleFactor", 1.0),
    )
    return _frame(message_id, spektra_settings=settings)


# --- per-profile I/O, logic, lists (reverse: pb -> dict) ---------------------

_LATCHING_OUTPUT = 3            # TriggerOperationType.LATCHING_OUTPUT
_LATCHING_OUTPUT_TRIGGER_TIME = 255


def _canon_output_time(type_: int, trigger_time: int) -> int:
    """Latching outputs ignore the pulse timer -> canonical value (gpioLayout.ts)."""
    return _LATCHING_OUTPUT_TRIGGER_TIME if type_ == _LATCHING_OUTPUT else trigger_time


def input_to_dict(pb) -> dict:
    """IOInputMessage -> EdidioInput dict."""
    return {
        "name": f"Input {pb.index + 1}", "index": pb.index, "type": pb.button_state,
        "shortLowAction": trigger_to_dict(pb.short_press),
        "longHighAction": trigger_to_dict(pb.long_press), "error": None,
    }


def output_to_dict(pb) -> dict:
    """IOOutputMessage -> EdidioOutput dict."""
    type_ = pb.type
    return {
        "name": f"Output {pb.index + 1}", "index": pb.index,
        "initiallyHigh": bool(pb.initial_level),
        "triggerTime": _canon_output_time(type_, pb.time_trigger_is_active or 0),
        "type": type_,
    }


def logic_to_dict(pb, index: int | None = None) -> dict:
    """LogicMessage -> EdidioLogicAction dict."""
    idx = index if index is not None else pb.index
    return {
        "name": f"Logic {idx + 1}",
        "comparisonObject": trigger_to_dict(pb.comparison_object),
        "comparisonType": pb.comparison_type, "comparisonValue": pb.comparison_value,
        "isEnabled": True, "index": idx,
        "trueAction": trigger_to_dict(pb.actionA),
        "falseAction": trigger_to_dict(pb.actionB), "error": None,
    }


def duration_and_unit(seconds: int) -> tuple:
    """Split a seconds value into (duration, ListStepTimeUnit) for the UI display
    fields, choosing the largest whole unit ('Hours'/'Minutes'/'Seconds')."""
    if seconds and seconds % 3600 == 0:
        return seconds // 3600, "Hours"
    if seconds and seconds % 60 == 0:
        return seconds // 60, "Minutes"
    return seconds, "Seconds"


def list_step_to_dict(pb, index: int = 0) -> dict:
    """ListStepMessage -> EdidioListStep dict. The app needs index + duration/timeUnit
    (UI display) alongside time_until_next (seconds); omitting them hides the step."""
    secs = pb.time_seconds
    duration, unit = duration_and_unit(secs)
    return {"index": getattr(pb, "step_index", index),
            "action": trigger_to_dict(pb.action),
            "duration": duration, "timeUnit": unit, "time_until_next": secs}


def list_to_dict(pb) -> dict:
    """ListMessage -> EdidioList dict (first-block steps; extended steps not fetched)."""
    state = pb.list_state
    steps = [list_step_to_dict(s, i) for i, s in enumerate(pb.step)]
    return {
        "name": f"List {pb.list_index + 1}", "index": pb.list_index,
        "loop_on_startup": state in (0x02, 0x03, 0x05), "state": state,
        "steps": steps, "totalStepCount": pb.total_step_count or len(steps),
        "isShow": 0x10 <= state <= 0x12, "scheduledDates": [], "error": None,
    }


# --- per-profile I/O, logic, lists (forward: dict -> frame) ------------------

def _pb_trigger(cmd: dict):
    cmd = cmd or {}
    return pb.TriggerMessage(
        type=cmd.get("commandtype", 254), zone=cmd.get("zone", 0),
        line_mask=cmd.get("linemask", 0), target_index=cmd.get("target", 0),
        value=cmd.get("value", 0), query_index=cmd.get("query", 0))


def inputs_to_message(profile: int, inputs: list, message_id: int) -> bytes:
    """[EdidioInput] for one profile -> InputMultiMessage frame."""
    items = [pb.IOInputMessage(
        index=int(i["index"]), button_state=int(i.get("type", 0)),
        short_press=_pb_trigger(i.get("shortLowAction")),
        long_press=_pb_trigger(i.get("longHighAction"))) for i in inputs]
    return _frame(message_id, inputs=pb.InputMultiMessage(profile=profile, inputs=items))


def outputs_to_message(profile: int, outputs: list, message_id: int) -> bytes:
    """[EdidioOutput] for one profile -> OutputMultiMessage frame."""
    items = [pb.IOOutputMessage(
        index=int(o["index"]),
        initial_level=1 if o.get("initiallyHigh") else 0,
        time_trigger_is_active=_canon_output_time(int(o.get("type", 0)),
                                                  int(o.get("triggerTime", 0))),
        type=int(o.get("type", 0))) for o in outputs]
    return _frame(message_id, outputs=pb.OutputMultiMessage(profile=profile, outputs=items))


def logic_to_message(logic_list: list, message_id: int) -> bytes:
    """[EdidioLogicAction] -> LogicMultiMessage frame."""
    items = [pb.LogicMessage(
        index=int(g["index"]),
        comparison_object=_pb_trigger(g.get("comparisonObject")),
        comparison_type=int(g.get("comparisonType", 0)),
        comparison_value=int(g.get("comparisonValue", 0)),
        enabled=True,
        actionA=_pb_trigger(g.get("trueAction")),
        actionB=_pb_trigger(g.get("falseAction"))) for g in logic_list]
    return _frame(message_id, logic_message=pb.LogicMultiMessage(logic=items))


def list_to_message(lst: dict, message_id: int, is_dali: bool = False) -> bytes:
    """EdidioList dict -> ListMessage frame."""
    steps = [pb.ListStepMessage(step_index=n,
                                time_seconds=int(s.get("time_until_next", 0)),
                                action=_pb_trigger(s.get("action")))
             for n, s in enumerate(lst.get("steps") or [])]
    return _frame(message_id, list=pb.ListMessage(
        list_index=int(lst["index"]), list_state=int(lst.get("state", 0)),
        total_step_count=len(steps), step=steps))


# --- sensors + DALI inputs (line/version helpers) ---------------------------

def dali_line_mask_to_number(mask) -> int:
    """Single-bit line bitmask (1/2/4/8) -> 1-based line number (1..4); 0 if none."""
    mask = int(mask or 0)
    return mask.bit_length() if mask > 0 else 0    # 1->1, 2->2, 4->3, 8->4


def line_number_to_mask(n) -> int:
    n = int(n or 0)
    return 1 << (n - 1) if n >= 1 else 0


def _ver_tuple(s) -> list:
    parts = [int(x) for x in str(s).split(".") if x.isdigit()]
    return parts + [0] * (3 - len(parts))


def version_gte(version, threshold) -> bool:
    return _ver_tuple(version) >= _ver_tuple(threshold)


# Firmware at/above this understands Phase-3 directional (coop) sensor grouping.
COOP_GROUPING_FIRMWARE = "1.3.0"


def sensor_to_dict(pb) -> dict:
    """SensorMessage -> EdidioSensor dict (mirrors mapPbSensorToEdidioSensor; the
    app-only `identifier` uuid is omitted so pulls are deterministic)."""
    grouped = [i for i in range(32) if (pb.motion_sensors or 0) & (1 << i)]
    return {
        "index": pb.index, "name": f"Sensor {pb.index + 1}",
        "line": dali_line_mask_to_number(pb.sensor_dali_line or 0),
        "address": pb.sensor_address or 0,
        "setPoint": pb.light_setpoint or 0,
        "controlLineMask": pb.control_dali_line or 0,      # raw mask (may be multi-bit)
        "controlGroup": pb.control_group or 0,
        "addressQuery": pb.address_query or 0,
        "inactivityTimer": pb.timeout_values or 0,          # minutes
        "warningTimer": pb.warning_values or 0,             # seconds
        "disableTimer": pb.disable_values or 0,             # seconds
        "prgBtnOne": None, "prgBtnTwo": None,
        "motionOnly": bool(pb.motion_only),
        "detectionTrigger": trigger_to_dict(pb.detection_trigger),
        "warningTrigger": trigger_to_dict(pb.warning_trigger),
        "idleTrigger": trigger_to_dict(pb.idle_trigger),
        "groupedWithIndexes": grouped,                      # legacy grouping (< 1.3.0)
        # Phase 3 fields exist only on newer protobufs; default when absent.
        "coopGroup": getattr(pb, "coop_group", 0) or 0,
        "coopLeader": bool(getattr(pb, "coop_leader", False)),
        "error": None,
    }


def sensor_to_message(sensor: dict, profile: int, message_id: int,
                      supports_coop: bool = False) -> bytes:
    """EdidioSensor dict -> SensorMessage frame. Firmware-gated grouping: legacy
    motion_sensors bitmask (< 1.3.0) vs coop_group/coop_leader (>= 1.3.0)."""
    motion_mask = 0
    if not supports_coop:
        for idx in sensor.get("groupedWithIndexes") or []:
            if 0 <= idx < 32:
                motion_mask |= 1 << idx
    kwargs = dict(
        profile=profile, index=int(sensor["index"]),
        sensor_address=int(sensor.get("address", 0)),
        sensor_dali_line=line_number_to_mask(sensor.get("line", 0)),
        address_query=int(sensor.get("addressQuery", 0)),
        control_dali_line=int(sensor.get("controlLineMask", 0)),
        control_group=int(sensor.get("controlGroup", 0)),
        light_setpoint=int(sensor.get("setPoint", 0)), warning_setpoint=0,
        motion_only=1 if sensor.get("motionOnly") else 0,
        timeout_values=int(sensor.get("inactivityTimer", 0)),
        warning_values=int(sensor.get("warningTimer", 0)),
        disable_values=int(sensor.get("disableTimer", 0)),
        input_1_pm=0, input_2_pm=0, sensor_states=0,
        motion_sensors=motion_mask & 0xFFFFFFFF, lux_sensors=0, off_flag=0,
        is_programmed=True,
        detection_trigger=_pb_trigger(sensor.get("detectionTrigger")),
        warning_trigger=_pb_trigger(sensor.get("warningTrigger")),
        idle_trigger=_pb_trigger(sensor.get("idleTrigger")),
    )
    # Phase-3 coop fields only exist on newer protobufs — set only if present.
    fields = pb.SensorMessage.DESCRIPTOR.fields_by_name
    if "coop_group" in fields:
        kwargs["coop_group"] = int(sensor.get("coopGroup", 0)) if supports_coop else 0
    if "coop_leader" in fields:
        kwargs["coop_leader"] = 1 if (supports_coop and sensor.get("coopLeader")) else 0
    return _frame(message_id, sensor=pb.SensorMessage(**kwargs))


def daliinput_to_dict(pb) -> dict:
    """DALIInputMessage -> EdidioDALIInput dict (identifier uuid omitted)."""
    return {
        "name": f"DALI Input {pb.index + 1}", "index": pb.index,
        "type": pb.button_state, "address": pb.address or 0,
        "instance": pb.instance or 0,
        "line": dali_line_mask_to_number(pb.dali_line or 0), "isActive": True,
        "shortOrLowAction": trigger_to_dict(pb.short_press),
        "longOrHighAction": trigger_to_dict(pb.long_press), "error": None,
    }


def daliinputs_to_message(profile: int, inputs: list, message_id: int) -> bytes:
    """[EdidioDALIInput] for one profile -> DALIInputMultiMessage frame."""
    items = [pb.DALIInputMessage(
        index=int(i["index"]), address=int(i.get("address", 0)),
        dali_line=line_number_to_mask(i.get("line", 0)),
        button_state=int(i.get("type", 0)),
        short_press=_pb_trigger(i.get("shortOrLowAction")),
        long_press=_pb_trigger(i.get("longOrHighAction")),
        instance=int(i.get("instance", 0))) for i in inputs]
    return _frame(message_id, inputs_dali=pb.DALIInputMultiMessage(
        profile=profile, input_index_offset=0, inputs=items))


# --- device info: diagnostics -> supportedFeatures, network -> network dict ----

def diag_to_supported_features(diag) -> dict:
    """DiagnosticSystemInfoResponse -> EdidioSupportedFeatures dict (mirrors
    mapPbDiagInfoToSupportedFeatures). Drives the SpektraPlus UI."""
    g = lambda name: getattr(diag, name, 0) or 0  # noqa: E731
    return {
        "inputs": g("input_count"), "outputs": g("output_count"),
        "irCodes": g("ir_count"), "listSteps": g("list_step_count"),
        "lists": g("list_count"), "sensors": 40,  # not in protocol; app hardcodes 40
        "alarms": g("alarm_count"), "burnIns": g("burnin_count"),
        "lines": g("line_count"), "profiles": g("profile_count"),
        "presetCodeBlocks": g("preset_code_count"), "userLevels": g("user_level_count"),
        "controlTranslations": g("dmx_to_dali_count"), "logicObjects": g("logic_count"),
        "daliInputs": g("input_dali_count"), "zones": g("spektra_zone_count"),
        "sequences": g("spektra_seq_count"), "sequence_steps": g("spektra_seq_step_count"),
        "themes": g("spektra_theme_count"), "shows": 0,
        "staticColours": g("spektra_static_count"), "colourChannels": 0,
        "coloursPerSequence": 0, "coloursPerTheme": 0,
    }


def network_to_dict(pb, *, current_ip="", mac="", device_name="", tls=False) -> dict:
    """AdminNetworkPropertiesMessage -> EdidioNetworkProperties dict
    (mirrors mapPbNetworkToEdidioNetwork)."""
    g = lambda name, d="": getattr(pb, name, d) or d  # noqa: E731
    return {
        "ip": current_ip, "staticIp": g("IP"), "mac": g("MAC") or mac,
        "isConnected": True, "deviceName": device_name or "eDIDIO_S10",
        "connectionProtocol": "TLS" if tls else "TCP",
        "dhcpEnabled": bool(getattr(pb, "DHCP", False)),
        "gateway": g("gateway"), "subnet": g("subnet"),
        "dnsPrimary": g("DNS_Primary") or "8.8.8.8",
        "dnsSecondary": g("DNS_Secondary") or "8.8.4.4",
        "ntpServerIp": g("NTPServer"), "ntpEnabled": bool(getattr(pb, "NTP", False)),
        "ntpTimeout": getattr(pb, "NTPTimeout", 0) or 0,
    }


# --- persistence / profile / clear helpers ----------------------------------
# Zones and sensor-clears are RAM-only until an explicit save (see SyncService.ts /
# ZonesAdapter / SensorsAdapter). These build the messages that persist them.

def zone_save_message(message_id: int) -> bytes:
    """SpektraControl SETTINGS SAVE — persists zone writes to flash (ZonesAdapter)."""
    return EdidioClient.create_spektra_control_message(
        message_id, pb.SpektraTargetType.SETTINGS, 0, 0, pb.SpektraActionType.SAVE)


def device_save_message(message_id: int) -> bytes:
    """External DEVICE_SAVE trigger — the sensor RESET handler doesn't config_save()."""
    return _frame(message_id, external_trigger=pb.ExternalTriggerMessage(
        trigger=pb.TriggerMessage(type=pb.TriggerType.DEVICE_SAVE)))


def change_profile_message(message_id: int, profile: int) -> bytes:
    """Switch the device's active profile (EEPROM swap; needed before a sensor RESET)."""
    return _frame(message_id, change_profile=pb.ChangeProfileMessage(profile=profile))


def reset_sensors_message(message_id: int) -> bytes:
    """Admin RESET DALI_SENSORS — un-programs all sensor slots on the ACTIVE profile."""
    return _frame(message_id, admin_message=pb.AdminMessage(
        command=pb.AdminCommandType.RESET, target=pb.AdminPropertyType.DALI_SENSORS))


def zone_to_dict(pb) -> dict:
    """SpektraSettingMessage -> EdidioZoneData dict."""
    num_channels = pb.channels_per_light or 0
    if pb.channel_colours and len(pb.channel_colours) == num_channels:
        channel_colours = [number_to_hex(c) for c in pb.channel_colours]
    else:
        channel_colours = ["#FFFFFF"] * num_channels
    return {
        "index": pb.zone,
        "alias": f"Zone {pb.zone + 1}",
        "linemask": pb.line_or_universe_mask or 0,
        "numChannels": num_channels,
        "numLights": pb.number_of_lights or 0,
        "channelTypes": [infer_light_type(c) for c in channel_colours],
        "channelColours": channel_colours,
        "protocol": pb.protocol or 0,
        "startAddress": pb.start_address or 0,
        "unscheduledBehaviourType": pb.unscheduled_behaviour or 0,
        "scaleFactor": pb.zone_scale_factor or 1.0,
        "multiLineAddressing": pb.line_addressing or 0,
        "daligroupoffset": None,
    }
