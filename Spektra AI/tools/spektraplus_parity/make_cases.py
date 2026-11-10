"""Make the protobuf cases for the SpektraPlus mapper parity test.

For each message type that both apps map to .spektra data, this writes three cases
as serialised protobuf (base64): every field at its default ("empty" - where a
`?? x` ported as `or x` goes wrong), every field set to a distinct value ("filled"),
and high values ("max": 255s, the hours unit). SpektraPlus's own mappers are then run
on the same bytes (see README.md); tests/test_spektraplus_parity.py runs Spektra AI's.

    python tools/spektraplus_parity/make_cases.py      # -> tests/fixtures/parity_cases.json
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb
from google.protobuf.descriptor import FieldDescriptor as F

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "fixtures" / "parity_cases.json"

# SpektraPlus mapper -> protobuf message, and the index the mapper takes (if any).
MAPPERS = {
    "mapPbTriggerToEdidioTrigger": ("TriggerMessage", None),
    "mapPbAlarmToEdidioSchedule": ("AlarmMessage", None),
    "mapPbSequenceToEdidioSequenceData": ("SpektraSequenceConfigMessage", None),
    "mapPbThemeToEdidioThemeData": ("SpektraThemeConfigMessage", None),
    "mapPbInputToEdidioInput": ("IOInputMessage", None),
    "mapPbOutputToEdidioOutput": ("IOOutputMessage", None),
    "mapPbLogicToEdidioLogicAction": ("LogicMessage", 2),
    "mapPbSensorToEdidioSensor": ("SensorMessage", None),     # both use pb.index
    "mapPbDaliInputToEdidioDALIInput": ("DALIInputMessage", None),
    "mapPbSpektraSettingsToEdidioZone": ("SpektraSettingMessage", None),
    "mapPbTranslationToEdidioControlTranslation": ("DMXTranslationObject", 1),
    "mapPbBurnInToEdidioBurnIn": ("BurnInMessage", 4),
}


def fill(msg, mode: str, depth: int = 0, seed: list | None = None):
    """Set every field of msg: 'filled' = small distinct values, 'max' = high ones."""
    seed = seed if seed is not None else [0]
    for f in msg.DESCRIPTOR.fields:
        seed[0] += 1
        n = seed[0]
        if f.type == F.TYPE_MESSAGE:
            if depth >= 2:
                continue
            if _repeated(f):
                for _ in range(2):
                    fill(getattr(msg, f.name).add(), mode, depth + 1, seed)
            else:
                fill(getattr(msg, f.name), mode, depth + 1, seed)
            continue
        value = _value(f, n, mode)
        if value is None:
            continue
        if _repeated(f):
            getattr(msg, f.name).extend([value, value])
        else:
            setattr(msg, f.name, value)


def _repeated(f) -> bool:
    """is_repeated where protobuf has it (label() is deprecated), label() otherwise."""
    rep = getattr(f, "is_repeated", None)
    return rep if isinstance(rep, bool) else f.label == F.LABEL_REPEATED


def _value(f, n: int, mode: str):
    hi = mode == "max"
    if f.type == F.TYPE_BOOL:
        return True
    if f.type == F.TYPE_STRING:
        return "Name" if not hi else "N" * 20
    if f.type == F.TYPE_BYTES:
        return None
    if f.type == F.TYPE_ENUM:
        values = [v.number for v in f.enum_type.values]
        return max(values) if hi else (values[1] if len(values) > 1 else values[0])
    if f.type in (F.TYPE_FLOAT, F.TYPE_DOUBLE):
        return 1.0 if hi else 0.5
    if "unit" in f.name:
        return 3 if hi else 1
    return 255 if hi else (n % 200) + 1


def main():
    cases = []
    for mapper, (cls, index) in MAPPERS.items():
        for mode in ("empty", "filled", "max"):
            msg = getattr(pb, cls)()
            if mode != "empty":
                fill(msg, mode)
            cases.append({"mapper": mapper, "message": cls, "mode": mode, "index": index,
                          "bytes": base64.b64encode(msg.SerializeToString()).decode()})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cases, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases to {OUT}")


if __name__ == "__main__":
    sys.exit(main())
