"""Sequence bench check: every sequence type and option, through Spektra AI's own tools,
compared with the controller's DMX level cache.

It borrows one zone and one sequence slot that you name, saves their raw contents, and
puts them back exactly at the end (also after a failure). The zone becomes a DMX zone
of --lights RGBW fixtures on --line, starting at channel 1. Use a DMX line with nothing
important on it: the fixtures there will light.

Each case is written with preview_sequence + confirm, then checked three ways:

  write   the stored sequence matches the spec (type, timing and units, range, args,
          direction, random flags)
  reread  a pull then push (sequence_to_dict -> sequence_to_message) keeps every field
  output  the DMX cache while it plays matches sequence_model: frame for frame for the
          step-driven types, colours only for the random ones; and the step time

    python tools/sequence_bench.py --host 192.168.1.50 --tls --zone 3 --line 2 --slot 36
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from edidio_control_py import EdidioClient, SpektraTargetType  # noqa: E402

from edidio_spektra_ai import server as S, spektra_map as M, tools_live as T  # noqa: E402
from edidio_spektra_ai import sequence_model as SM  # noqa: E402
from edidio_spektra_ai.undo import _rewrap  # noqa: E402

CH = 4
RGB = [[255, 0, 0, 0], [0, 255, 0, 0], [0, 0, 255, 0]]
# random, a fade-out flash, or (particle cannon) a speed that carries over between runs
COLOURS_ONLY = {"twinkle", "fireworks", "fire", "ramp_down", "particle_cannon"}

# (label, spec changes, seconds to watch)
CASES = [(t, {"type": t}, 7) for t in (
    "blend", "simple_chase", "shadow_chase", "comet", "rotate", "twinkle", "build_up",
    "crash", "fireworks", "fire", "ramp_up", "ramp_down", "static", "radial_rotate",
    "radial_build", "particle_cannon")] + [
    ("chase range 4 + background", {"type": "simple_chase", "range": 4, "background": [0, 0, 40]}, 6),
    ("radial build range 6", {"type": "radial_build", "range": 6}, 7),
    ("chase reversed", {"type": "simple_chase", "reverse": True}, 6),
    ("chase cycle (400 ms)", {"type": "simple_chase", "cycle": True, "time_per_step_ms": 400,
                              "colours": RGB[:1]}, 12),
    ("comet tail 5", {"type": "comet", "comet_tail": 5, "colours": RGB[:1]}, 6),
    ("chase colour every 2 s", {"type": "simple_chase", "time_per_colour_ms": 2000}, 8),
    ("blend 1000 + 1500 fade", {"type": "blend", "fade_ms": 1500, "transition": "blend"}, 12),
]


def tok(text):
    m = re.search(r'token="([0-9a-f]+)"', text)
    if not m:
        raise RuntimeError(text)
    return m.group(1)


def label(v, colours, background):
    """A fixture's channel levels -> the model's symbol."""
    if not any(v):
        return SM.OFF
    if background and list(v[:3]) == list(background[:3]) and not any(v[3:]):
        return SM.BG
    top = max(v)
    for i, c in enumerate(colours):
        ct = max(c) or 1
        if all(abs(a / top - b / ct) < 0.06 for a, b in zip(v, c)):
            return SM.sym(i)
    return SM.MIX


def matches(observed, model):
    """observed is a run of model frames (allowing one leading start-up frame)."""
    for skip in (0, 1):
        obs = observed[skip:]
        for o in range(len(model) - len(obs) + 1):
            if obs and model[o:o + len(obs)] == obs:
                return True
    return False


class Bench:
    def __init__(self, a):
        self.a, self.c = a, None
        self.zone, self.slot = a.zone - 1, a.slot - 1
        self.results = []

    async def frame(self, colours, background):
        levels, page = [], 0
        while len(levels) < self.a.lights * CH:
            r = await self.c.read_dmx_cache(self.a.line, page)
            levels += r["levels"]
            page += 1
        return "".join(label(levels[f * CH:f * CH + CH], colours, background)
                       for f in range(self.a.lights))

    async def raw(self, target, index, kind):
        r = await self.c._read_spektra(target, index)
        return getattr(r, kind) if r.WhichOneof("payload") == kind else None

    async def run_case(self, name, changes, seconds):
        spec = {"index": self.slot, "title": f"Bench {name}"[:23], "colours": RGB,
                "time_per_step_ms": 1000, "time_per_colour_ms": 60000, "transition": "snap"}
        spec.update(changes)
        out = await S.confirm(tok(await S.preview_sequence(spec)))
        problems = []
        if not out.startswith("Done."):
            problems.append(f"write refused: {out.splitlines()[0][:80]}")
        stored = await self.raw(SpektraTargetType.SEQUENCE, self.slot, "spektra_sequence")
        # write: the stored sequence is what compile_sequence sent
        sent_frames, _ = S.compile_sequence(spec)
        import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb
        sent = pb.EdidioMessage()
        sent.ParseFromString(sent_frames[0][3:])
        fields = ("type", "time_per_step", "time_per_step_unit", "time_per_colour",
                  "time_per_colour_unit", "fade_time_by_10ms", "transition", "range",
                  "is_reverse_direction", "is_cycle_direction", "has_random_colour_order",
                  "is_randomised_type", "random_types_mask", "title")
        diff = [f for f in fields if getattr(stored, f) != getattr(sent.spektra_sequence, f)]
        # The controller stores args it was not sent as 255 ("not set"), which reads
        # the same as what was meant: background off, default comet tail.
        sent_args = (list(sent.spektra_sequence.args) + [255] * 5)[:4]
        if list(stored.args)[:4] != sent_args:
            diff.append(f"args {list(stored.args)} (sent {list(sent.spektra_sequence.args)})")
        if diff:
            problems.append(f"stored differs: {diff}")
        # reread: pull then push keeps every field
        seen = {}
        orig = EdidioClient.create_spektra_sequence_message

        def spy(message_id, **kw):
            seen.update(kw)
            return orig(message_id, **kw)
        EdidioClient.create_spektra_sequence_message = staticmethod(spy)
        try:
            M.sequence_to_message(M.sequence_to_dict(stored), 1, False)
        finally:
            EdidioClient.create_spektra_sequence_message = orig
        back = {"seq_type": stored.type, **{f: getattr(stored, f) for f in fields if f != "type"}}
        lost = [k for k, v in back.items() if seen.get(k) != v]
        if lost:
            problems.append(f"pull/push changes {lost}")
        # output: the cache against the model
        seq = SM.Sequence.from_pb(stored)
        bg = spec.get("background")
        await S.play_sequence(self.zone, self.slot)
        obs, times, t0 = [], [], time.monotonic()
        while time.monotonic() - t0 < seconds:
            f = await self.frame(spec["colours"], bg)
            if not obs or obs[-1] != f:
                obs.append(f)
                times.append(time.monotonic() - t0)
            await asyncio.sleep(0.04)
        await S.stop_zone(self.zone)
        # Drop frames shorter than a quarter step (max 150 ms): transitions, such as ramp
        # up's snap to the background before each fade up, not steps.
        short = min(0.15, (seq.step_ms + seq.fade_ms) / 4000)
        keep = [i for i in range(len(obs))
                if i == len(obs) - 1 or times[i + 1] - times[i] >= short]
        pairs = [(obs[i], times[i]) for i in keep]
        pairs = [p for i, p in enumerate(pairs) if i == 0 or p[0] != pairs[i - 1][0]]
        obs, times = [f for f, _ in pairs], [t for _, t in pairs]
        model = [f for _, f in SM.simulate(seq, self.a.lights, 60)]
        dedup = [f for i, f in enumerate(model) if i == 0 or f != model[i - 1]]
        if spec["type"] in COLOURS_ONLY:
            allowed = {SM.sym(i) for i in range(len(spec["colours"]))} | {SM.OFF, SM.BG, SM.MIX}
            stray = sorted({ch for f in obs for ch in f} - allowed)
            if stray:
                problems.append(f"unexpected colours {stray}")
        elif spec.get("fade_ms"):
            pure = [t for f, t in zip(obs, times) if SM.MIX not in f]
            gaps = sorted(b - a for a, b in zip(pure[1:], pure[2:]))
            want = (spec["time_per_step_ms"] + spec["fade_ms"]) / 1000
            got = gaps[len(gaps) // 2] if gaps else 0
            if abs(got - want) > 0.15 * want:
                problems.append(f"period {got:.2f}s, model {want:.2f}s")
        elif not matches(obs, dedup):
            problems.append("frames differ from the model")
            problems += [f"  saw   {f}" for f in obs[:6]] + [f"  model {f}" for f in dedup[:6]]
        if spec["type"] not in COLOUR_STATIC and not spec.get("fade_ms") and len(times) > 3:
            gaps = sorted(b - a for a, b in zip(times[1:], times[2:]))
            want = (seq.step_ms + seq.fade_ms) / 1000
            got = gaps[len(gaps) // 2]
            if spec["type"] not in COLOURS_ONLY and spec["type"] != "particle_cannon" \
                    and abs(got - want) > 0.15 * want and not spec.get("cycle"):
                problems.append(f"step {got:.2f}s, expected {want:.2f}s")
        self.results.append((name, problems))
        print(f"  {'ok  ' if not problems else 'FAIL'} {name}")
        for p in problems:
            print(f"         {p}")

    async def main(self):
        a = self.a
        print(await S.connect_controller(a.host, 443 if a.tls else 23, a.tls))
        self.c = S._controller
        T._controller = self.c
        zone = await self.raw(SpektraTargetType.SETTINGS, self.zone, "spektra_settings")
        slot = await self.raw(SpektraTargetType.SEQUENCE, self.slot, "spektra_sequence")
        if zone is None:
            raise SystemExit(f"zone {a.zone} could not be read")
        print(f"Borrowing zone {a.zone} and sequence {a.slot} "
              f"({'empty' if slot is None else repr(slot.title)}); both are restored at the end.")
        try:
            out = await S.confirm(tok(await T.preview_zone(
                self.zone, "dmx", a.line, a.lights, "red,green,blue,white", 1)))
            if not out.startswith("Done"):
                raise SystemExit(out)
            only = set(a.only.split(",")) if a.only else None
            for name, changes, seconds in CASES:
                if only is None or name in only:
                    await self.run_case(name, changes, seconds)
        finally:
            await S.stop_zone(self.zone)
            frames = [_rewrap("spektra_settings", zone, self.c._next_id()),
                      M.zone_save_message(self.c._next_id())]
            if slot is not None:
                frames.append(_rewrap("spektra_sequence", slot, self.c._next_id()))
            else:
                import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb
                from edidio_spektra_ai.undo import DELETION_MARKER_NAME
                frames.append(_rewrap("spektra_sequence", pb.SpektraSequenceConfigMessage(
                    index=self.slot, title=DELETION_MARKER_NAME), self.c._next_id()))
            frames.append(M.device_save_message(self.c._next_id()))
            for f in frames:
                await self.c._require().request(f)
            z2 = await self.raw(SpektraTargetType.SETTINGS, self.zone, "spektra_settings")
            s2 = await self.raw(SpektraTargetType.SEQUENCE, self.slot, "spektra_sequence")
            same = (z2.SerializeToString() == zone.SerializeToString()
                    and (slot is None or s2.SerializeToString() == slot.SerializeToString()))
            print(f"Restored zone {a.zone} and sequence {a.slot}: "
                  f"{'identical' if same else 'DIFFERENT - check them'}")
            await self.c.disconnect()
        failed = [n for n, p in self.results if p]
        print(f"\n{len(self.results) - len(failed)}/{len(self.results)} passed"
              + (f"; failed: {', '.join(failed)}" if failed else ""))
        return 1 if failed else 0


COLOUR_STATIC = {"static"}


def parse(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--host", required=True)
    p.add_argument("--tls", action="store_true", help="TLS on 443 (else TCP 23)")
    p.add_argument("--zone", type=int, required=True, help="zone to borrow (1-based)")
    p.add_argument("--slot", type=int, required=True, help="sequence slot to borrow (1-based)")
    p.add_argument("--line", type=int, required=True, help="a DMX line (1-based)")
    p.add_argument("--lights", type=int, default=12)
    p.add_argument("--only", help="comma-separated case names")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(Bench(parse()).main()))
