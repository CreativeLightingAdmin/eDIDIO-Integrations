"""DALI-2 control devices (IEC 62386-103: sensors, push buttons, rotaries) over the
controller's 24-bit frame passthrough.

Frame layout (as SpektraPlus builds it): ``((address << 1) | 1) << 16 | instance << 8
| opcode``. Device-level commands/queries use instance byte 0xFE; instance-level ones
use the instance number (0..N-1). Configuration commands are "send twice" and most
take a value from DTR0 (or DTR2:DTR1:DTR0), which is set first with a special
command. Replies are one byte.
"""

from __future__ import annotations

from edidio_control_py._v2 import eDS10_v2_pb2 as pb

from . import v2

DEVICE = 0xFE           # instance byte for device-level commands
BROADCAST = 0x7F        # address byte for broadcast to all devices (0x7F << 1 | 1 = 0xFF)

INSTANCE_TYPES = {0: "generic", 1: "push button", 2: "absolute input (rotary/slider)",
                  3: "occupancy (motion) sensor", 4: "light sensor"}

# IEC 62386-103 device queries / instance queries (opcodes)
Q_DEVICE_STATUS = 0x30
Q_INPUT_DEVICE_ERROR = 0x32
Q_VERSION = 0x34
Q_INSTANCES = 0x35
Q_OPERATING_MODE = 0x3E
Q_DEVICE_GROUPS = (0x41, 0x42, 0x43, 0x44)
Q_CAPABILITIES = 0x46
Q_APP_CONTROLLER_ENABLED = 0x3D
Q_INSTANCE_TYPE = 0x80
Q_RESOLUTION = 0x81
Q_INSTANCE_ERROR = 0x82
Q_INSTANCE_STATUS = 0x83
Q_EVENT_PRIORITY = 0x84
Q_INSTANCE_ENABLED = 0x86
Q_PRIMARY_GROUP = 0x88
Q_EVENT_SCHEME = 0x8B
Q_INPUT_VALUE = 0x8C
Q_INPUT_VALUE_LATCH = 0x8D
Q_EVENT_FILTER = (0x90, 0x91, 0x92)

# Instance/device commands
C_IDENTIFY = 0x00
C_ENABLE_INSTANCE = 0x62
C_DISABLE_INSTANCE = 0x63
C_SET_EVENT_SCHEME = 0x67
C_SET_EVENT_FILTER = 0x68
# Occupancy sensor (IEC 62386-303) instance commands, value in DTR0
C_MOTION_SET_HOLD_TIMER = 0x21       # DTR0 x 10 s
C_MOTION_SET_REPORT_TIMER = 0x22     # DTR0 x 1 s
C_MOTION_SET_DEADTIME_TIMER = 0x23   # DTR0 x 50 ms
C_MOTION_CANCEL_HOLD_TIMER = 0x24
# Light sensor (IEC 62386-304) instance commands, value in DTR0
C_LIGHT_SET_REPORT_TIMER = 0x30      # DTR0 x 1 s
C_LIGHT_SET_HYSTERESIS = 0x31        # DTR0 %
C_LIGHT_SET_DEADTIME_TIMER = 0x32    # DTR0 x 50 ms
C_LIGHT_SET_HYSTERESIS_MIN = 0x33    # DTR0 lux units

# 24-bit special commands (address byte 0xC1), IEC 62386-103 table 22
_SPECIAL = 0xC1
_DTR0, _DTR1, _DTR2 = 0x30, 0x31, 0x32

EVENT_SCHEMES = {0: "instance addressing", 1: "device addressing",
                 2: "device/instance addressing", 3: "device group", 4: "instance group"}

MOTION_VALUES = {0x00: "vacant, no movement", 0x55: "vacant, movement",
                 0xAA: "occupied, no movement", 0xFF: "occupied, movement"}

_RECEIVED = {pb.DALIRXStatusFlag.Value(n) for n in ("RECEIVED_8_BIT_FRAME",)
             if n in pb.DALIRXStatusFlag.keys()}


def frame(address: int, instance: int, opcode: int) -> int:
    return (((address << 1) | 1) << 16) | (instance << 8) | opcode


def special(cmd: int, value: int) -> int:
    return (_SPECIAL << 16) | (cmd << 8) | (value & 0xFF)


def _line_mask(line: int) -> int:
    return 1 << (line - 1)


async def _send(ctrl, line: int, value: int, *, reply: bool, twice: bool = False):
    field = {"frame_24_bit_reply": value} if reply else {"frame_24_bit": value}
    msg = pb.DALIMessage(line_mask=_line_mask(line), send_twice=twice, **field)
    return await v2.request(ctrl._require(),
                            pb.EdidioMessage(message_id=ctrl._next_id(), dali_message=msg))


async def query(ctrl, line: int, address: int, instance: int, opcode: int):
    """One 24-bit query -> the reply byte, or None (no reply). These queries use no
    DTR, so a timeout is simply asked again once."""
    from edidio_control_py.exceptions import EDIDIOTimeoutError
    try:
        r = await _send(ctrl, line, frame(address, instance, opcode), reply=True)
    except EDIDIOTimeoutError:
        r = await _send(ctrl, line, frame(address, instance, opcode), reply=True)
    if r.WhichOneof("payload") != "dali_query":
        return None
    q = r.dali_query
    if q.dali_flag not in _RECEIVED:
        return None
    return q.response_data.uint_data


async def command(ctrl, line: int, address: int, instance: int, opcode: int, *,
                  dtr0: int | None = None, dtr1: int | None = None,
                  dtr2: int | None = None, twice: bool = True) -> list:
    """A configuration command: set the DTRs it reads, then send it twice (as
    IEC 62386-103 requires for configuration commands). Returns the acks."""
    acks = []
    for cmd, val in ((_DTR0, dtr0), (_DTR1, dtr1), (_DTR2, dtr2)):
        if val is not None:
            acks.append(v2.ack_summary(await _send(ctrl, line, special(cmd, val), reply=False)))
    acks.append(v2.ack_summary(await _send(ctrl, line, frame(address, instance, opcode),
                                           reply=False, twice=twice)))
    return acks


async def probe(ctrl, line: int, address: int) -> dict | None:
    """Everything readable about one DALI-2 control device, or None if it does not
    answer. Instances report their type, enabled state, errors, event scheme and
    filter, groups and current input value."""
    n = await query(ctrl, line, address, DEVICE, Q_INSTANCES)
    if n is None:
        return None
    dev = {"address": address, "line": line, "instances": []}
    for key, op in (("status", Q_DEVICE_STATUS), ("version", Q_VERSION),
                    ("operating_mode", Q_OPERATING_MODE), ("capabilities", Q_CAPABILITIES),
                    ("input_device_error", Q_INPUT_DEVICE_ERROR),
                    ("app_controller_enabled", Q_APP_CONTROLLER_ENABLED)):
        dev[key] = await query(ctrl, line, address, DEVICE, op)
    groups = 0
    for i, op in enumerate(Q_DEVICE_GROUPS):
        g = await query(ctrl, line, address, DEVICE, op)
        groups |= (g or 0) << (8 * i)
    dev["device_groups"] = [g for g in range(32) if groups & (1 << g)]
    dev["app_controller_enabled"] = dev["app_controller_enabled"] is not None   # yes/no
    if dev["version"] is not None:
        dev["version_text"] = f"{dev['version'] >> 2}.{dev['version'] & 3}"
    for inst in range(min(n, 32)):
        t = await query(ctrl, line, address, inst, Q_INSTANCE_TYPE)
        info = {"instance": inst, "type": t, "type_name": INSTANCE_TYPES.get(t, f"type {t}")}
        for key, op in (("enabled", Q_INSTANCE_ENABLED), ("error", Q_INSTANCE_ERROR),
                        ("status", Q_INSTANCE_STATUS), ("resolution", Q_RESOLUTION),
                        ("event_scheme", Q_EVENT_SCHEME), ("event_priority", Q_EVENT_PRIORITY),
                        ("primary_group", Q_PRIMARY_GROUP)):
            info[key] = await query(ctrl, line, address, inst, op)
        filt = 0
        for i, op in enumerate(Q_EVENT_FILTER):
            f = await query(ctrl, line, address, inst, op)
            filt |= (f or 0) << (8 * i)
        info["event_filter"] = filt
        msb = await query(ctrl, line, address, inst, Q_INPUT_VALUE)
        info["input_value"] = msb
        if t == 4 and msb is not None:            # light: 10-bit from MSB + latch
            latch = await query(ctrl, line, address, inst, Q_INPUT_VALUE_LATCH)
            info["light_level"] = min((msb << 2) | ((latch or 0) >> 6), 1023)
        if t == 3 and msb is not None:
            info["motion"] = MOTION_VALUES.get(msb, f"0x{msb:02X}")
        # DALI answers a yes/no query with 0xFF for YES and silence for NO.
        info["enabled"] = info["enabled"] is not None
        dev["instances"].append(info)
    return dev


async def scan(ctrl, line: int, addresses=range(64)) -> list:
    """Find DALI-2 control devices on a line (they answer QUERY NUMBER OF INSTANCES)."""
    found = []
    for a in addresses:
        n = await query(ctrl, line, a, DEVICE, Q_INSTANCES)
        if n is not None:
            found.append({"address": a, "instances": n})
    return found


def describe(dev: dict) -> str:
    rows = [f"DALI-2 device at line {dev['line']} address {dev['address']}: "
            f"version {dev.get('version_text', '?')}, {len(dev['instances'])} instance(s)"
            + (f", device groups {dev['device_groups']}" if dev['device_groups'] else "")
            + (" [application controller]" if dev.get("app_controller_enabled") else "")]
    for i in dev["instances"]:
        bits = [i["type_name"], "enabled" if i["enabled"] else "DISABLED"]
        if i.get("motion"):
            bits.append(f"now {i['motion']}")
        if i.get("light_level") is not None:
            bits.append(f"light {i['light_level']}/1023")
        if i.get("error"):
            bits.append(f"error 0x{i['error']:02X}")
        bits.append(f"event scheme {EVENT_SCHEMES.get(i.get('event_scheme'), i.get('event_scheme'))}")
        bits.append(f"filter 0x{i['event_filter']:06X}")
        rows.append(f"  instance {i['instance']}: " + ", ".join(bits))
    return "\n".join(rows)
