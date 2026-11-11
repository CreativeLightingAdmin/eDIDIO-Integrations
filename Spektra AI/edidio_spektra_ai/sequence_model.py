"""A model of the controller's sequence engine (as measured on eDIDIO firmware),
for the dry run in preview_sequence and for the bench check (tools/sequence_bench.py),
which compares it with the DMX level cache of a real controller.

It ports the step handlers and the two timers as the firmware runs them:

- Each tick runs the colour timer, then the step timer. Both start at 0, so on the
  first tick colour_index already moves 0 -> 1: types that draw with colour_index
  (chases, comet, particle cannon) start on the SECOND colour.
- Each step lasts time_per_step + fade, each colour time_per_colour + fade.
- handle_index: forward, reverse, or cycle (bounce; each end is held for two steps).
- Range: 0 = the whole zone; above the zone's light count it is capped.

A frame is one symbol per fixture: "1".."9","A".."K" = colour 1..20, "." = off,
"b" = the background colour, "*" = two colours mixed (crash), "?" = random level.
Twinkle, fireworks and fire are random by design: their frames show which colour
is used, not where. Random colour order and random types are not predicted.
"""
from __future__ import annotations

from dataclasses import dataclass, field

OFF, BG, MIX, RANDOM = ".", "b", "*", "?"
_SYMBOLS = "123456789ABCDEFGHIJK"
RANDOM_TYPES = {5, 8, 9}            # twinkle, fireworks, fire
COLOUR_INDEX_TYPES = {1, 2, 3, 15}  # draw with colour_index (the colour timer)
STEP_TYPES = {0, 4, 10, 11, 13}     # draw with step_index
LAP_TYPES = {6, 7, 14}              # draw with colour_range (one colour per pass)
DEFAULT_COMET_TAIL, CRASH_TAIL = 3, 2


def sym(colour_index: int) -> str:
    return _SYMBOLS[colour_index] if 0 <= colour_index < len(_SYMBOLS) else "?"


@dataclass
class Sequence:
    type: int
    colours: int                      # how many colours
    step_ms: int = 500
    colour_ms: int = 2000
    fade_ms: int = 0
    range: int = 0
    reverse: bool = False
    cycle: bool = False
    background: list = field(default_factory=list)   # args[0..2]; any non-zero = "b"
    comet_tail: int = 0               # args[3]; 0 = default (3)
    random_colour_order: bool = False
    random_types: bool = False

    @classmethod
    def from_pb(cls, s) -> "Sequence":
        """From a SpektraSequenceConfigMessage (the stored sequence)."""
        unit = {0: 1, 1: 1000, 2: 60_000, 3: 3_600_000}
        args = list(s.args) + [0] * 5
        return cls(type=s.type, colours=len(s.colours),
                   step_ms=s.time_per_step * unit.get(s.time_per_step_unit, 1000),
                   colour_ms=s.time_per_colour * unit.get(s.time_per_colour_unit, 1000),
                   fade_ms=0 if s.transition == 1 else s.fade_time_by_10ms * 10,  # snap
                   range=s.range, reverse=bool(s.is_reverse_direction),
                   cycle=bool(s.is_cycle_direction),
                   background=[0 if v == 255 else v for v in args[:3]],
                   comet_tail=args[3], random_colour_order=bool(s.has_random_colour_order),
                   random_types=bool(s.is_randomised_type))


class _Engine:
    def __init__(self, seq: Sequence, lights: int):
        self.s, self.n = seq, max(0, lights)
        self.k = max(1, seq.colours)
        self.step = self.direction = self.colour = self.lap = 0
        self.bg = BG if any(seq.background) else OFF
        self.frame = [OFF] * self.n
        self.cycle = seq.cycle and seq.type != 7      # crash clears the flags
        self.reverse = seq.reverse and seq.type != 7 and not self.cycle

    # --- firmware helpers ---
    def put(self, f, value):
        if 0 <= f < self.n:                           # get_fixture rejects the rest
            self.frame[f] = value

    def all(self, value):
        self.frame = [value] * self.n

    def index(self, rng):
        """handle_index(zone, range)."""
        if rng == 0:
            return
        if self.cycle:
            if self.direction == 0:
                self.step += 1
                if self.step >= rng:
                    self.direction, self.step = 1, self.step - 1
                    self.lap += 1
            elif self.step > 0:
                self.step -= 1
            else:
                self.direction, self.step = 0, 0
                self.lap += 1
        elif self.reverse:
            self.direction = 1
            if self.step > 0:
                self.step -= 1
            else:
                self.step = rng - 1
                self.lap += 1
        else:
            self.direction = 0
            self.step += 1
            if self.step >= rng:
                self.step = 0
                self.lap += 1
        if self.lap >= self.k:
            self.lap = 0

    def start(self):
        """sequence_service_background: what a type shows before its first step."""
        t = self.s.type
        if t in (1, 2, 3, 6, 8, 14, 15):
            self.all(self.bg)
        elif t in (5, 7, 9):
            self.all(OFF)

    def tick_colour(self):
        if self.k > 1:
            self.colour = (self.colour + 1) % self.k
        else:
            self.colour = 0

    def tick_step(self):
        n, k, t = self.n, self.k, self.s.type
        rng = n if self.s.range == 0 or self.s.range > n else self.s.range
        if n == 0:
            return
        rpt = n // rng
        if t == 0:                                    # blend
            self.all(sym(self.step))
            self.index(k)
        elif t == 1:                                  # simple chase
            self.all(self.bg)
            for i in range(rpt):
                self.put(self.step + rng * i, sym(self.colour))
            self.index(rng)
        elif t == 2:                                  # shadow chase
            self.all(sym(self.colour))
            for i in range(rpt):
                self.put(self.step + rng * i, self.bg)
            self.index(rng)
        elif t == 3:                                  # comet
            tail = self.s.comet_tail if 0 < self.s.comet_tail < 255 else DEFAULT_COMET_TAIL
            tail = min(tail, rng)
            for adr in self._comet(tail, rng):
                for i in range(rpt):
                    self.put(adr + rng * i, self.bg)
            self.index(rng)
            for adr in self._comet(tail, rng):
                for i in range(rpt):
                    self.put(adr + rng * i, sym(self.colour))
        elif t == 4:                                  # rotate
            self.frame = [sym((self.step - f) % k) for f in range(n)]
            self.index(k)
        elif t in RANDOM_TYPES:
            self.frame = [RANDOM for _ in range(n)] if t != 8 else self.frame
            if t == 8:                                # fireworks: pops, then background
                self.all(self.bg)
        elif t == 6:                                  # build up
            for i in range(rpt):
                self.put(self.step + rng * i, sym(self.lap))
            self.index(rng)
        elif t == 7:                                  # crash
            self._crash(rng, rpt)
        elif t == 10:                                 # ramp up: snap to bg, fade to colour
            self.all(sym(self.step))
            self.index(k)
        elif t == 11:                                 # ramp down: colour, fade to bg
            self.all(sym(self.step))
            self.index(k)
        elif t == 12:                                 # static (never advances)
            self.frame = [sym((self.step + f) % k) for f in range(n)]
        elif t == 13:                                 # radial rotate (whole zone)
            half = max(1, n // 2)
            c = self.step
            for f in range(half):
                self.put(f, sym(c))
                self.put(n - f - 1, sym(c))
                if f == half - 1 and n % 2 == 1:
                    self.put(f + 1, sym(c))
                c = (c + 1) % k
            self.index(k)
        elif t == 14:                                 # radial build, each repeat mirrored
            for i in range(rpt):
                self.put(self.step + rng * i, sym(self.lap))
                self.put(rng * i + rng - self.step - 1, sym(self.lap))
            self.index(max(2, rng) // 2)
        elif t == 15:                                 # particle cannon (speed varies)
            for i in range(rpt):
                self.put(self.step + rng * i, sym(self.colour))
            self.index(rng)
            for i in range(rpt):
                self.put(self.step + rng * i, self.bg)

    def _comet(self, tail, rng):
        out = []
        for j in range(tail):
            if self.direction == 0:
                a = self.step - j
                out.append(a + rng if a < 0 else a)
            else:
                a = self.step + j
                out.append(a - rng if a >= rng else a)
        return out

    def _crash(self, rng, rpt):
        c1, c2 = sym(self.lap), sym((self.lap + 1) % self.k)
        tail = min(CRASH_TAIL, rng)

        def draw(lit):
            meet = self.step >= rng // tail
            for j in range(tail):
                a = self.step - j
                if a < 0:
                    break
                for i in range(rpt):
                    self.put(a + rng * i, (MIX if meet else c1) if lit else OFF)
            for j in range(tail):
                b = rng - self.step + j - 1
                if b >= rng:
                    break
                for i in range(rpt):
                    self.put(b + rng * i, (MIX if meet else c2) if lit else OFF)
        draw(False)
        self.index(rng)
        draw(True)


def simulate(seq: Sequence, lights: int, steps: int = 12) -> list:
    """[(time_ms, frame)]: the start-up frame at 0, then one frame per step, as the
    firmware draws them."""
    e = _Engine(seq, lights)
    e.start()
    out = [(0, "".join(e.frame))]
    step_period = max(50, seq.step_ms) + seq.fade_ms
    colour_period = max(50, seq.colour_ms) + seq.fade_ms
    next_colour = next_step = 0
    while len(out) < steps + 1:
        t = min(next_colour, next_step)
        if next_colour == t:                          # colour timer runs first
            e.tick_colour()
            next_colour += colour_period
        if next_step == t:
            e.tick_step()
            out.append((t, "".join(e.frame)))
            next_step += step_period
    return out


def _version(text: str) -> tuple:
    """'1.6.3' -> (1, 6, 3); unknown -> a large version (no old-firmware note)."""
    import re
    nums = re.findall(r"\d+", text or "")
    return tuple(int(x) for x in nums[:3]) if nums else (999,)


def caveats(seq: Sequence, lights: int, firmware: str = "") -> list:
    """What the dry run cannot show exactly, and firmware behaviour worth knowing."""
    notes = []
    if seq.type in RANDOM_TYPES:
        notes.append("this type is random: '?' marks fixtures at a random level of the colour")
    if seq.random_colour_order:
        notes.append("random colour order: colours are shown in order here")
    if seq.random_types:
        notes.append("random types: the controller switches type now and then; "
                     "this shows the first type only")
    if seq.type == 15:
        notes.append("particle cannon speeds up and slows down (its speed is shared by all "
                     "zones and carries on from the last run); steps are shown evenly")
    if seq.type in COLOUR_INDEX_TYPES and seq.colours > 1:
        notes.append("the controller starts this type on colour 2 (its colour timer "
                     "advances once before the first step)")
    if seq.cycle and seq.type not in (7,):
        notes.append("cycle holds each end for two steps")
    rng = lights if seq.range == 0 or seq.range > lights else seq.range
    if seq.type == 14 and lights // max(rng, 1) > 1 and _version(firmware) <= (1, 6, 3):
        notes.append(f"firmware {firmware} lights only the first repeat's mirrored half")
    if seq.type == 14 and rng % 2 == 1:
        notes.append("an odd range never lights its middle fixture")
    return notes


def render(seq: Sequence, lights: int, steps: int = 12, colours: list | None = None,
           firmware: str = "") -> str:
    """The dry run as text: one line per step, then a legend and caveats."""
    rows = simulate(seq, lights, steps)
    width = max(len(f"{t / 1000:g}s") for t, _ in rows)
    lines = [f"Dry run on {lights} lights (one column per fixture):"]
    for i, (t, frame) in enumerate(rows):
        label = "start" if i == 0 else f"{t / 1000:g}s".rjust(width)
        lines.append(f"  {label:>6}  {frame}")
    if colours:
        lines.append("  " + ", ".join(f"{sym(i)} = {c}" for i, c in enumerate(colours))
                     + (", b = background" if any(seq.background) else "") + ", . = off")
    lines += [f"  Note: {n}." for n in caveats(seq, lights, firmware)]
    return "\n".join(lines)
