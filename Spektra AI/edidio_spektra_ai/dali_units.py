"""Physical DALI devices and their channels (logical units), from memory bank 0, and
putting a multi-channel device's channels in order on consecutive addresses.

A multi-channel driver (e.g. RGBW) is one physical device made of several logical
control-gear units, each with its own short address. Memory bank 0 (IEC 62386-102)
says which device each address belongs to (GTIN 0x03-0x08 + identification number
0x0B-0x12), how many units the device has (0x19) and which one this address is
(0x1A: logical index 0 = the first channel, e.g. red on an RGBW driver).

The controller's remap command swaps two addresses safely (it parks one on a free
address first), and groups/scenes live in the gear, so they move with the channel.
"""

from __future__ import annotations

from edidio_control_py._v2 import eDS10_v2_pb2 as pb

from . import v2

_GTIN = range(0x03, 0x09)
_DEVICE_ID = range(0x0B, 0x13)
_UNITS, _INDEX = 0x19, 0x1A


async def _byte(ctrl, line, address, loc, retries=3):
    for _ in range(retries):
        v = await ctrl.dali_read_memory_byte(line, address, 0, loc)
        if v is not None:
            return v
    return None


async def unit_info(ctrl, line: int, address: int) -> dict:
    """GTIN, device id, unit count and logical index of one address (None = no reply)."""
    gtin = [await _byte(ctrl, line, address, i) for i in _GTIN]
    dev = [await _byte(ctrl, line, address, i) for i in _DEVICE_ID]
    units = await _byte(ctrl, line, address, _UNITS)
    index = await _byte(ctrl, line, address, _INDEX)
    hx = (lambda bs: "".join(f"{b:02X}" for b in bs) if None not in bs else None)  # noqa: E731
    gtin_num = int.from_bytes(bytes(gtin), "big") if None not in gtin else None
    return {"address": address, "gtin": gtin_num, "device_id": hx(dev),
            "units": units if units not in (None, 0xFF) else None,
            "index": index if index not in (None, 0xFF) else None}


def group_devices(infos: list) -> list:
    """Addresses -> physical devices (same GTIN + device id), channels by index."""
    devices: dict = {}
    for i in infos:
        key = (i["gtin"], i["device_id"]) if i["device_id"] else ("?", i["address"])
        devices.setdefault(key, []).append(i)
    out = []
    for (gtin, dev_id), chans in devices.items():
        chans = sorted(chans, key=lambda c: (c["index"] is None, c["index"] or 0, c["address"]))
        out.append({"gtin": gtin, "device_id": dev_id, "units": chans[0]["units"],
                    "channels": chans})
    return sorted(out, key=lambda d: min(c["address"] for c in d["channels"]))


def plan_order(device: dict, start: int) -> list:
    """Swaps that put logical index n on address start+n. Returns [(from, to)] in
    order (each a swap, as the controller's remap does it)."""
    chans = device["channels"]
    if any(c["index"] is None for c in chans):
        raise ValueError("this device does not report logical indexes (memory bank 0x1A); "
                         "use identify to find each channel instead")
    if start + max(c["index"] for c in chans) > 63:
        raise ValueError("the channels would run past address 63")
    where = {c["index"]: c["address"] for c in chans}       # index -> current address
    swaps = []
    for idx in sorted(where):
        cur, target = where[idx], start + idx
        if cur == target:
            continue
        swaps.append((cur, target))
        other = next((k for k, a in where.items() if a == target), None)
        where[idx] = target
        if other is not None:
            where[other] = cur
    return swaps


async def remap(ctrl, line: int, frm: int, to: int, *, is24: bool = False) -> dict:
    client = ctrl._require()
    old = getattr(client, "_timeout", None)
    client._timeout = max(old or 0, 20.0)       # a swap is several queries + 3 stores
    try:
        r = await v2.request(client, pb.EdidioMessage(
            message_id=ctrl._next_id(), dali_remapping_message=pb.DALIRemappingMessage(
                from_address=frm, to_address=to, line_mask=1 << (line - 1), is24Bit=is24)))
    finally:
        if old is not None:
            client._timeout = old
    return v2.ack_summary(r)


def describe(devices: list, line: int) -> str:
    rows = [f"DALI line {line}: {len(devices)} physical device(s)"]
    for n, d in enumerate(devices, 1):
        chans = d["channels"]
        head = (f"  Device {n}: GTIN {d['gtin'] or '?'}, id {d['device_id'] or '?'}, "
                f"{d['units'] or len(chans)} channel(s)")
        if all(c["index"] is not None for c in chans):
            base = chans[0]["address"] - chans[0]["index"]
            in_order = all(c["address"] == base + c["index"] for c in chans)
            head += ("  - in channel order" if in_order else
                     "  - NOT in channel order on consecutive addresses "
                     "(preview_dali_channel_order fixes it)")
        if d["units"] and len(chans) != d["units"]:
            head += f"  - only {len(chans)} of {d['units']} channels answered"
        rows.append(head)
        for c in chans:
            idx = "?" if c["index"] is None else c["index"]
            rows.append(f"      channel index {idx}: address {c['address']}")
    return "\n".join(rows)
