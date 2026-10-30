"""Normalise a recorded chain run: ticks to clocks, classification, alignment.

Plan, "Analysis pipeline" steps 1-2. One run record (acquire.py's JSON) becomes
a `Normalized`: the bus cycles from the first fetch of the chain onward as
`Event`s in CPU clocks, with clock 0 at the start of the fetch of the word that
holds the chain's first byte. The absolute tick phase differs from run to run
(reset lands on either half of a clock), so nothing here uses `start % 8`
except to assert that, within one run, every cycle after clock 0 starts on the
same phase.

Conventions (all in CPU clocks, relative to clock 0):

- `Event.clock` is the cycle's first clock; `Event.length` is
  (end - start) // 8 + 1 (3 / 4 / 5 at 0 / 1 / 2 waits); `Event.end` is
  clock + length - 1, the clock of the trace's `end` tick (T3/TW last clock).
- An *idle gap* is a run of at least IDLE_MIN clocks with no bus cycle at all,
  between `prev.end` and `next.clock`. IDLE_MIN separates the long-shift idle
  (60+ clocks) from the few free clocks a full queue leaves between fetches
  (up to 6 observed in F0/F1).
- Data, stack and I/O cycles are predicted per instruction by
  `expected_accesses` (forms + a tracked SP, starting at 0F00h). A memory cycle
  below 1000h is a stack cycle when it lies inside the tracked stack range
  (`stack_range`, bounded by STACK_BOUND), else a data cycle. The observed
  non-fetch cycles must equal the expected ones (kind, address) in program
  order; each then carries its instruction's index. Markers are matched to
  their expected cycle (OUT port 20h+i, PUSH at the tracked SP, store at
  0C00h) in chain order.
- `t_fill` is the `end` clock of the last fetch before the first idle gap that
  follows the fetch of the first LS's last byte.
- (WP40) `pre`: the prelude's tail before clock 0, every cycle from the prelude's
  POP PSW stack read (the first read at 0EFEh) on, clocks relative to clock 0; kept
  out of `events` (score.pre_aligned compares it).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .blocks import MARKER_PORT_BASE
from .forms import (DEFAULT_REGS, DIRECT, F24_COMPARES, F32_BCD, F32_BITFIELD, F33_FLAGS, FORMS,
                    IO_PORT, STACK_CLASSES, STRING_FORMS, UNMODELLED_STRING_FORMS)

# (WP74) every string form the walk expands: F24's (the simulator's) and F33's REPC / REPNC
WALK_STRING_FORMS = {**STRING_FORMS, **UNMODELLED_STRING_FORMS}
# (WP74) forms the walk (_StringState) expands itself: the string forms, F32's BCD strings and
# bit fields (their addresses and counts come from the walked registers)
WALK_FORMS = frozenset(WALK_STRING_FORMS) | frozenset(F32_BCD) | frozenset(F32_BITFIELD)
# (WP74) forms that change none of the walked registers or memory: the flag forms
WALK_NEUTRAL = frozenset(F33_FLAGS) | {"nop"}
from .types import CODE_BASE, TICKS_PER_CLOCK, Chain, refresh_any

FLAG_READ = 1 << 0
FLAG_IO = 1 << 1
FLAG_REFRESH = 1 << 2
FLAG_NUBE = 1 << 3          # /UBE high: the upper byte is NOT enabled
FLAG_UNMAPPED = 1 << 4
FLAG_MARKER = 1 << 5
FLAG_A9 = 1 << 6
FLAG_STROBE = 1 << 7

CODE_END = CODE_BASE + 0x1000
DATA_END = 0x1000
STACK_BOUND = (0x0E00, 0x0F10)      # sanity bound on the tracked stack range
STORE_MARKER_ADDR = 0x0C00
END_PORT = 0xFF00
BASE_LENGTH = 3                     # clocks of a zero-wait bus cycle
REFRESH_EARLY_TICKS = 1             # refresh starts are recorded one tick early
PRE_MARKER = -1                     # (WP24) Event.marker_id of the prelude marker's cycle
PRE_STACK = (0x0EFE, 0x0F00)        # (WP40) the prelude's stack: PUSH 0002h / POP PSW at 0EFEh
IDLE_MIN = 12                       # free clocks that make an idle gap
LONG_IDLE = 40                      # free clocks of a long-shift idle (LS runs ~70)

KINDS = ("fetch", "data_read", "data_write", "stack_read", "stack_write",
         "io_read", "io_write", "refresh")
KIND_CHAR = {"fetch": "F", "data_read": "R", "data_write": "W", "stack_read": "r",
             "stack_write": "w", "io_read": "i", "io_write": "I", "refresh": "X"}


class NormalizeError(AssertionError):
    pass


@dataclass
class Event:
    clock: int
    kind: str
    addr: int
    width: str                      # "word" | "lo" | "hi"
    length: int
    data: int
    instr_index: int | None = None
    byte_range: tuple | None = None     # chain offsets [lo, hi) of the fetched bytes
    marker_id: int | None = None

    @property
    def end(self) -> int:
        return self.clock + self.length - 1

    @property
    def char(self) -> str:
        return KIND_CHAR[self.kind]


@dataclass
class Normalized:
    run_id: str
    chain: Chain
    chain_base: int
    events: list[Event]
    phase: int                      # start % 8 of every cycle after clock 0
    t0_tick: int                    # absolute tick of clock 0
    t_fill: int | None
    fill_index: int | None          # index in events of the fetch that ends at t_fill
    ls_fetch_index: int | None      # fetch holding the first LS's last byte
    t_markers: dict                 # marker_id -> clock
    t_end: int | None               # the END block's OUT DW,AL (port FF00h)
    wait_clocks: dict               # kind -> sorted observed (length - 3)
    expected_accesses: dict = field(default_factory=dict)   # instr index -> [Access]
    stack_range: tuple = (0, 0)     # tracked [lo, hi) of the stack cycles
    access_mismatch: dict | None = None
    checks: list[str] = field(default_factory=list)   # failed soft checks
    # (WP24, F18) the prelude marker's cycle (Chain.prelude_marker), clock relative to clock
    # 0 (negative when it ran before the chain's first fetch); after clock 0 it is in events
    # with marker_id PRE_MARKER (it occupies the bus, so it closes an idle gap) and is left
    # out of the expected-access match (it is the prelude's)
    t_pre_marker: int | None = None
    # (WP40) the prelude's tail before clock 0: every bus cycle from the prelude's POP PSW
    # stack read (its only stack read before the register loads, at PRE_STACK) up to clock 0,
    # as Events with clocks relative to clock 0 (negative); empty when the trace has no such
    # read before clock 0 (a model run that does not run the prelude's tail). Not in events:
    # nothing that reads events, t_fill or the markers sees it (score.pre_aligned does)
    pre: list = field(default_factory=list)

    def idle_gaps(self, after: int = -1) -> list[tuple[int, int]]:
        """(index of the last event before, index of the first event after) per gap."""
        return idle_gaps(self.events, after)


# Loading ---------------------------------------------------------------------

def corpus_name(family: str, waits: int) -> str:
    return f"chains-{family}" if waits < 0 else f"chains-{family}-w{waits}"


def load_runs(family: str, waits=(0, 1, 2), files=None) -> list[dict]:
    """Run records of one family: from the corpus by default, else from `files`."""
    import json
    from pathlib import Path

    if files:
        runs = []
        for path in files:
            data = json.loads(Path(path).read_text())
            runs += [r for r in data["runs"] if r["chain"]["family"] == family
                     and (r["chain"]["waits"] < 0 or r["chain"]["waits"] in waits)]
        return runs
    from .. import corpus

    names = [corpus_name(family, -1)] if family == "F0w" else [
        corpus_name(family, w) for w in waits]
    entries = corpus.manifest()["entries"]
    runs = []
    for name in names:
        if name in entries:
            runs += corpus.load(name)["runs"]
    if not runs:
        raise FileNotFoundError(f"no corpus entries for {family} (looked for {names})")
    return runs


# Classification --------------------------------------------------------------

def width_of(addr: int, flags: int) -> str:
    nube = bool(flags & FLAG_NUBE)
    if addr & 1:
        if nube:
            raise NormalizeError(f"odd address {addr:05X} with /UBE high")
        return "hi"
    return "lo" if nube else "word"


def kind_of(addr: int, flags: int, stack_range: tuple = (0, 0)) -> str:
    """Event kind; `stack_range` [lo, hi) is the chain's tracked stack (see stack_range)."""
    if flags & FLAG_REFRESH:
        return "refresh"
    read = bool(flags & FLAG_READ)
    if flags & FLAG_IO:
        return "io_read" if read else "io_write"
    if CODE_BASE <= addr < CODE_END:
        if not read:
            raise NormalizeError(f"write into the code page at {addr:05X}")
        return "fetch"
    if addr < DATA_END:
        stack = stack_range[0] <= addr < stack_range[1]
        return ("stack_" if stack else "data_") + ("read" if read else "write")
    raise NormalizeError(f"unclassified bus cycle at {addr:05X} flags {flags:02X}")


# Expected accesses -------------------------------------------------------------

@dataclass(frozen=True)
class Access:
    """One expected data / stack / I/O bus cycle of an instruction, in program order."""
    kind: str               # an Event kind: data_read, stack_write, io_write, ...
    addr: int
    width: str              # "word" | "lo" | "hi" (as Event.width)
    split: bool = False     # one half of an odd-address word access


def _cycles(kind, addr, nbytes):
    """Bus cycles of one operand: a word at an odd address splits in two byte cycles."""
    if nbytes == 1:
        return [Access(kind, addr, "hi" if addr & 1 else "lo")]
    if addr & 1:
        return [Access(kind, addr, "hi", True), Access(kind, addr + 1, "lo", True)]
    return [Access(kind, addr, "word")]


def _form_ea(form, regs) -> int:
    """The form's data address with this chain's registers (only BW is varied)."""
    ea = form.ea
    if form.mode and form.mode.startswith("bw"):
        ea += regs.get("BW", DEFAULT_REGS["BW"]) - DEFAULT_REGS["BW"]
    return ea & 0xFFFF


class _StringState:
    """(WP66, F24) the registers and data memory the string forms depend on, walked through
    the chain in order: AW (CMPM's operand, STM's datum), CW (the REP count), DW (INM / OUTM's
    port), IX and IY (the element addresses), DS0 / DS1 (the segments), and the bytes of data
    memory (the image's: 90h fill at 0800h-0FFFh, the zeroed vector table below 0400h; written
    by the chain's stores where the datum is known). None is unknown: a string form that needs
    an unknown value (a REP count, a port, an address, a compared operand) raises, so the
    expected accesses are never a guess. Effects of the other instructions: the fence (MOV
    CL,n ; SHL AW,CL) sets CL and shifts AW; MOV r16,imm16 (B8 AW, B9 CW, BA DW, BE IX, BF IY)
    loads; the drainers load AW / DW or add to DW; NOP and the markers change nothing; every
    other form makes all five registers unknown (only F24 chains walk this).

    (WP74) Also BW (BL, F32's bit-field offset register), MOV r8,imm8 (B0-B7: F32's MOV CL,n),
    the flag forms (WALK_NEUTRAL: no register or memory changes, F33's STC / CLC before MOV
    CW,n), F33's REPC / REPNC compares (string, by the carry) and F32's BCD strings (bcd) and
    bit fields (bitfield), which read the walked CL, IX, IY and the 8-bit offset / width
    registers."""

    LOADS = {0xB8: "AW", 0xB9: "CW", 0xBA: "DW", 0xBE: "IX", 0xBF: "IY"}

    def __init__(self, chain: Chain):
        regs = {**DEFAULT_REGS, **chain.regs}
        self.id = chain.id
        self.r = {n: regs[n] for n in ("AW", "CW", "DW", "BW", "IX", "IY", "DS0", "DS1")}
        self.mem: dict[int, int | None] = {}

    def byte(self, addr):
        if addr in self.mem:
            return self.mem[addr]
        return 0x90 if 0x0800 <= addr < 0x1000 else 0 if addr < 0x0400 else None

    def read(self, addr, width):
        got = [self.byte(addr + j) for j in range(width)]
        return None if None in got else sum(b << (8 * j) for j, b in enumerate(got))

    def write(self, addr, width, value):
        for j in range(width):
            self.mem[addr + j] = None if value is None else (value >> (8 * j)) & 0xFF

    def need(self, name, what):
        v = self.r[name]
        if v is None:
            raise NormalizeError(f"{self.id}: {what} needs {name}, which is unknown here")
        return v

    R8 = ("AW", "CW", "DW", "BW")         # AL CL DL BL (index 0-3), AH CH DH BH (4-7)

    def r8(self, i, what):
        v = self.need(self.R8[i & 3], what)
        return (v >> 8) & 0xFF if i & 4 else v & 0xFF

    def set_r8(self, i, value):
        name = self.R8[i & 3]
        v = self.r[name]
        if v is None:
            return
        self.r[name] = ((v & 0x00FF) | (value << 8)) if i & 4 else ((v & 0xFF00) | value)

    def step(self, instr, acc):
        """Apply a non-string instruction (its expected accesses acc already computed)."""
        code, r = instr.code, self.r
        if instr.role == "x" and instr.form in WALK_NEUTRAL:
            return
        if instr.role == "x" and len(code) == 2 and 0xB0 <= code[0] <= 0xB7:
            self.set_r8(code[0] & 7, code[1])            # (WP74) MOV r8,imm8
            return
        if instr.role == "ls":
            cl = code[1]
            r["CW"] = None if r["CW"] is None else (r["CW"] & 0xFF00) | cl
            r["AW"] = None if r["AW"] is None else 0 if cl >= 16 else (r["AW"] << cl) & 0xFFFF
        elif instr.role in ("drain", "x") and code[0] in self.LOADS and len(code) == 3:
            r[self.LOADS[code[0]]] = int.from_bytes(code[1:3], "little")
        elif instr.role == "drain" and code[:2] == bytes([0x81, 0xC2]):
            r["DW"] = None if r["DW"] is None else (r["DW"] + int.from_bytes(code[2:4], "little")) & 0xFFFF
        elif instr.role == "x" and code[:2] == bytes([0xC1, 0xE0]) and len(code) == 3:
            # (WP73, F30 str sep) SHL AW,imm8: AW shifted, the other registers kept
            r["AW"] = None if r["AW"] is None else (r["AW"] << code[2]) & 0xFFFF
        elif instr.role == "x" and instr.form != "nop":
            form = FORMS[instr.form]
            if form.cls != "store_imm":
                for name in ("AW", "CW", "DW", "BW", "IX", "IY"):
                    r[name] = None
            value = (int.from_bytes(code[-form.width:], "little")
                     if form.cls == "store_imm" else None)
            for a in acc:
                if a.kind.endswith("write") and not a.kind.startswith("io"):
                    self.write(a.addr, 1 if a.width != "word" else 2,
                               None if a.split or value is None else value)
            return
        # markers, the PAD, the END: a PUSH marker writes AW
        for a in acc:
            if a.kind == "stack_write":
                self.write(a.addr, 2, r["AW"])

    def string(self, form_name) -> "StringRun":
        """One string form's accesses: the elements it runs, [[Access, ...], ...], and for a
        REP compare that ran at least one element the overrun read after the last one."""
        s = WALK_STRING_FORMS[form_name]
        r, w = self.r, s.width
        what = f"{form_name} at"
        count = self.need("CW", what) if s.rep else 1
        port = self.need("DW", what) if any(p == "port" for _, p in s.steps) else None
        elements = []
        cond = False
        while count:
            ix = self.need("IX", what) if any(p == "ix" for _, p in s.steps) else None
            iy = self.need("IY", what) if any(p == "iy" for _, p in s.steps) else None
            lin_ix = ((self.need("DS0", what) << 4) + ix) & 0xFFFFF if ix is not None else None
            lin_iy = ((self.need("DS1", what) << 4) + iy) & 0xFFFFF if iy is not None else None
            acc = []
            for kind, place in s.steps:
                addr = {"ix": lin_ix, "iy": lin_iy, "port": port}[place]
                acc += _cycles(kind, addr, w)
            elements.append(acc)
            mask = 0xFF if w == 1 else 0xFFFF
            if s.op == "movbk":
                self.write(lin_iy, w, self.read(lin_ix, w))
            elif s.op == "stm":
                self.write(lin_iy, w, None if r["AW"] is None else r["AW"] & mask)
            elif s.op == "inm":
                self.write(lin_iy, w, None)         # the port's datum is not tracked
            elif s.op == "ldm":
                v = self.read(lin_ix, w)
                r["AW"] = (None if v is None or (w == 1 and r["AW"] is None)
                           else v if w == 2 else (r["AW"] & 0xFF00) | v)
            equal = carry = None
            if s.op in ("cmpbk", "cmpm"):
                a = (self.read(lin_ix, w) if s.op == "cmpbk"
                     else None if r["AW"] is None else r["AW"] & mask)
                b = self.read(lin_iy, w)
                if s.rep and (a is None or b is None):
                    raise NormalizeError(f"{self.id}: {form_name} compares an unknown value "
                                         f"(element {len(elements)})")
                equal = a == b
                carry = None if a is None or b is None else a < b      # (WP74) a - b borrows
            if ix is not None:
                r["IX"] = (ix + w) & 0xFFFF
            if iy is not None:
                r["IY"] = (iy + w) & 0xFFFF
            if not s.rep:
                break
            count = (count - 1) & 0xFFFF
            r["CW"] = count
            if ((s.rep == "repe" and not equal) or (s.rep == "repne" and equal)
                    or (s.rep == "repc" and not carry) or (s.rep == "repnc" and carry)):
                cond = True
                break
        overrun = []
        if s.rep and s.op in F24_COMPARES and elements:
            # (F24 silicon) a REP compare reads one more element at the next IX / IY after the
            # one that ends the repeat (CW reaching 0 or the condition failing), the same reads
            # in the same order; nothing is compared with them, and the walk leaves IX, IY and
            # CW where the last compared element put them (no later form of a chain reads them)
            for kind, place in s.steps:
                off = self.need(place.upper(), what)
                seg = self.need("DS0" if place == "ix" else "DS1", what)
                overrun += _cycles(kind, ((seg << 4) + off) & 0xFFFFF, w)
        return StringRun(elements, overrun, cond)

    def bcd(self, form_name) -> "StringRun":
        """(WP74, F32) ADD4S / SUB4S / CMP4S: (CL + 1) / 2 byte pairs, each the source byte at
        DS0:IX + i (DS1 behind the 26h prefix), the destination byte at DS1:IY + i, then (not
        CMP4S) the result byte back at DS1:IY + i; IX, IY and CL unchanged. (WP78) As a
        StringRun, one element per byte pair (the simulator's count, as a REP form's)."""
        code = FORMS[form_name].code
        what = f"{form_name} at"
        cl = self.r8(1, what)
        src_seg = self.need("DS1" if code[0] == 0x26 else "DS0", what)
        ix, iy, ds1 = self.need("IX", what), self.need("IY", what), self.need("DS1", what)
        elements = []
        for i in range((cl + 1) // 2):
            src = ((src_seg << 4) + ((ix + i) & 0xFFFF)) & 0xFFFFF
            dst = ((ds1 << 4) + ((iy + i) & 0xFFFF)) & 0xFFFFF
            acc = _cycles("data_read", src, 1) + _cycles("data_read", dst, 1)
            if F32_BCD[form_name] != 0x26:
                acc += _cycles("data_write", dst, 1)
                self.write(dst, 1, None)
            elements.append(acc)
        return StringRun(elements, [])

    def bitfield(self, form_name) -> list:
        """(WP74, F32) EXT / INS: the offset (the offset register's low 4 bits) and the width
        field (the width register's or the imm4's) give the field; it crosses into the next
        word when offset + width >= 16. EXT reads the word at DS0:IX (and IX + 2 when it
        crosses), loads AW (unknown here) and then the offset register; INS reads the word at
        DS1:IY and writes it back, then (when the field crosses) the word at IY + 2 (silicon,
        F32: read, write, read, write). Afterwards the offset register holds
        (offset + width + 1) & 15 and IX / IY steps by 2 when offset + width + 1 >= 16."""
        op, off_reg, wid_reg, imm = F32_BITFIELD[form_name]
        what = f"{form_name} at"
        width = (imm if imm is not None else self.r8(wid_reg, what)) & 15
        offset = self.r8(off_reg, what) & 15
        cross = offset + width >= 16
        place = "IX" if op == "ext" else "IY"
        off = self.need(place, what)
        seg = self.need("DS0" if op == "ext" else "DS1", what)
        words = [((seg << 4) + ((off + 2 * j) & 0xFFFF)) & 0xFFFFF for j in range(1 + cross)]
        acc = []
        for w in words:
            acc += _cycles("data_read", w, 2)
            if op == "ins":
                acc += _cycles("data_write", w, 2)
                self.write(w, 2, None)
        if op == "ext":
            self.r["AW"] = None             # the field (not tracked; AL / AH offsets go unknown)
        new = offset + width + 1
        self.set_r8(off_reg, new & 15)
        if new >= 16:
            self.r[place] = (off + 2) & 0xFFFF
        return acc


@dataclass(frozen=True)
class StringRun:
    """(WP66, F24) one string form's expected cycles: elements, [[Access, ...] per element
    compared / moved (the iters knob counts these)], then overrun, the REP compare's extra
    element read after the last one ([] for every other form and at CW = 0). (WP67) cond: a
    REP compare's repeat ended on its condition (REPE unequal, REPNE equal) at the last
    element, whether or not CW reached 0 there too (False: CW ran out, or no prefix)."""
    elements: list
    overrun: list
    cond: bool = False


def string_elements(chain: Chain) -> dict[int, StringRun]:
    """(WP66, F24) {instr index: StringRun} for every string form of the chain
    (expected_accesses' own walk)."""
    out: dict = {}
    expected_accesses(chain, out)
    return out


def expected_accesses(chain: Chain, elements: dict | None = None) -> dict[int, list[Access]]:
    """{instr index: [Access, ...]} for every instruction of the chain, walking the
    chain in order with a tracked SP (from chain.regs, 0F00h by default):
    push / push_mem lower SP by 2 before their write; pop / pop_mem read at SP
    then raise it by 2; the PUSH marker is a push. Data addresses are linear
    (DS0 = SS = 0). Instructions without data cycles map to [].

    (WP66) A string form (forms.STRING_FORMS, F24) expands to its elements' cycles in order,
    each element its operation's reads, writes and I/O (forms.F24_OPS), at addresses from the
    walked IX / IY (stepped upward by the width: DIR is clear) and the port DW: one element
    without a prefix; with REP, CW elements (none at CW = 0), a compare under REPE / REPNE
    stopping after the first element whose result ends the repeat, computed from the data
    the walk knows (_StringState: the image's fill and the chain's own stores). CMPBK reads
    the destination [IY] before the source [IX]; a REP compare that ran an element reads
    one element more (the overrun, F24 silicon). `elements`, when given, receives
    {instr index: StringRun} for the string forms."""
    strings = (_StringState(chain) if any(i.role == "x" and i.form in WALK_FORMS
                                          for i in chain.instrs) else None)
    sp = chain.regs.get("SP", DEFAULT_REGS["SP"])
    if getattr(chain, "prelude_marker", None) == "push":
        sp = (sp - 2) & 0xFFFF          # (WP24, F18) the prelude's last PUSH AW
    out: dict[int, list[Access]] = {}
    ports = None                # the DW forms' ports, tracked through the chain (F10)

    def push(acc):
        nonlocal sp
        sp = (sp - 2) & 0xFFFF
        acc += _cycles("stack_write", sp, 2)

    def pop(acc):
        nonlocal sp
        acc += _cycles("stack_read", sp, 2)
        sp = (sp + 2) & 0xFFFF

    for k, instr in enumerate(chain.instrs):
        acc: list[Access] = []
        if instr.role == "marker":
            kind = chain.marker_kind
            if kind == "out":
                acc.append(Access("io_write", MARKER_PORT_BASE + instr.marker_id, "lo"))
            elif kind == "push":
                push(acc)
            elif kind == "store":
                acc += _cycles("data_write", STORE_MARKER_ADDR, 2)
            else:
                raise NormalizeError(f"unknown marker kind {kind!r}")
        elif instr.role == "end":
            acc.append(Access("io_write", END_PORT, "word"))
        elif instr.role == "x" and strings is not None and instr.form in WALK_STRING_FORMS:
            run = strings.string(instr.form)
            if elements is not None:
                elements[k] = run
            acc = [a for element in run.elements for a in element] + run.overrun
        elif instr.role == "x" and strings is not None and instr.form in F32_BCD:
            run = strings.bcd(instr.form)
            if elements is not None:
                elements[k] = run           # (WP78) the BCD string's byte pairs
            acc = [a for element in run.elements for a in element]
        elif instr.role == "x" and strings is not None and instr.form in F32_BITFIELD:
            acc = strings.bitfield(instr.form)
        elif instr.role == "x":
            form = FORMS[instr.form]
            cls = form.cls
            if cls in STACK_CLASSES:
                # (WP49) PUSH R / POP R move eight words; CALL pushes, RET pops (F23, F25);
                # (WP52) the F25 stack classes: a form's writes are pushes, its reads pops
                for _ in range(form.writes):
                    push(acc)
                for _ in range(form.reads):
                    pop(acc)
            elif cls == "push_mem":
                acc += _cycles("data_read", _form_ea(form, chain.regs), form.width)
                push(acc)
            elif cls == "pop_mem":
                pop(acc)
                acc += _cycles("data_write", _form_ea(form, chain.regs), form.width)
            elif cls in ("out", "in"):
                port = IO_PORT
                if form.length == 1:
                    # a DW form addresses the DW it finds: walk the chain's registers
                    if ports is None:
                        from .sim.templates import io_ports
                        ports = io_ports(chain.code, {**DEFAULT_REGS, **chain.regs})
                    port = ports.get(instr.offset, port)
                kind = "io_write" if cls == "out" else "io_read"
                acc += _cycles(kind, port, form.width)
            else:
                ea = _form_ea(form, chain.regs) if form.reads or form.writes else None
                for _ in range(form.reads):
                    acc += _cycles("data_read", ea, form.width)
                for _ in range(form.writes):
                    acc += _cycles("data_write", ea, form.width)
        if strings is not None and not (instr.role == "x" and instr.form in WALK_FORMS):
            strings.step(instr, acc)
        out[k] = acc
    return out


def stack_range(expected: dict[int, list[Access]]) -> tuple[int, int]:
    """[lo, hi) covering every expected stack cycle; asserted inside STACK_BOUND."""
    addrs = [a.addr for accs in expected.values() for a in accs if a.kind.startswith("stack")]
    if not addrs:
        return (0, 0)
    lo, hi = min(addrs) & ~1, (max(addrs) | 1) + 1
    if lo < STACK_BOUND[0] or hi > STACK_BOUND[1]:
        raise NormalizeError(f"stack range {lo:04X}-{hi:04X} outside "
                             f"{STACK_BOUND[0]:04X}-{STACK_BOUND[1]:04X}")
    return (lo, hi)


def instr_at(chain: Chain, offset: int) -> int | None:
    for i, instr in enumerate(chain.instrs):
        if instr.offset <= offset < instr.offset + len(instr.code):
            return i
    return None


def map_fetch(chain: Chain, chain_base: int, addr: int):
    """(instr_index, byte_range) of a fetched word; None outside the chain bytes."""
    size = len(chain.code)
    lo = max(addr - chain_base, 0)
    hi = min(addr + 2 - chain_base, size)
    if lo >= hi:
        return None, None
    return instr_at(chain, lo), (lo, hi)


def idle_gaps(events: list[Event], after: int = -1,
              min_free: int = IDLE_MIN) -> list[tuple[int, int]]:
    """Gaps of at least min_free (IDLE_MIN) free clocks between events after index `after`."""
    """Refresh cycles are ignored: they neither open nor close a gap (F8 runs a
    refresh every ~15 clocks through the long-shift idle)."""
    keep = [i for i in range(max(after, 0), len(events)) if events[i].kind != "refresh"]
    gaps = []
    for i, j in zip(keep, keep[1:]):
        if events[j].clock - events[i].end - 1 >= min_free:
            gaps.append((i, j))
    return gaps


# Normalisation ---------------------------------------------------------------

def normalize(run: dict, trace_key: str = "socket_trace", strict: bool = True) -> Normalized:
    """Normalise one run record. Hard assertions raise NormalizeError when `strict`."""
    chain = Chain.from_json(run["chain"])
    chain_base = run["chain_base"]
    trace = run[trace_key]
    problems = []
    if not run.get("complete", True):
        problems.append("trace incomplete")

    expected = expected_accesses(chain)
    stack = stack_range(expected)

    first_word = chain_base & ~1
    start_at = next((k for k, row in enumerate(trace)
                     if row["address"] == first_word and row["flags"] & FLAG_READ
                     and not row["flags"] & (FLAG_IO | FLAG_REFRESH)), None)
    if start_at is None:
        raise NormalizeError(f"{chain.id}: no fetch of the first chain word {first_word:05X}")
    t0 = trace[start_at]["start"]
    phase = t0 % TICKS_PER_CLOCK

    pre_at, t_pre_marker = prelude_marker_row(chain, trace), None
    if getattr(chain, "prelude_marker", None) is not None:
        if pre_at is None:
            problems.append(f"prelude marker {chain.prelude_marker} not found")
        else:
            rel = trace[pre_at]["start"] - t0
            if rel % TICKS_PER_CLOCK:
                problems.append(f"prelude marker at tick phase {trace[pre_at]['start'] % 8}, "
                                f"not {phase}")
            t_pre_marker = rel // TICKS_PER_CLOCK

    pre: list[Event] = []
    pop_at = prelude_pop_row(trace, start_at)
    for row in trace[pop_at:start_at] if pop_at is not None else ():
        # (WP40) the prelude's tail from its POP PSW read (Normalized.pre)
        rel = row["start"] - t0
        addr, flags = row["address"], row["flags"]
        kind = kind_of(addr, flags, PRE_STACK)
        early = REFRESH_EARLY_TICKS if kind == "refresh" else 0
        if (rel + early) % TICKS_PER_CLOCK:
            problems.append(f"prelude {kind} cycle at {addr:05X} starts at tick phase "
                            f"{row['start'] % TICKS_PER_CLOCK}, not {phase}"
                            + (f" - {early}" if early else ""))
        width = "word" if kind in ("fetch", "refresh") else width_of(addr, flags)
        clock = (rel + early) // TICKS_PER_CLOCK
        pre.append(Event(clock=clock, kind=kind, addr=addr, width=width,
                         length=(row["end"] - t0) // TICKS_PER_CLOCK - clock + 1,
                         data=row["data"]))

    events: list[Event] = []
    for at, row in enumerate(trace[start_at:], start_at):
        rel = row["start"] - t0
        addr, flags = row["address"], row["flags"]
        kind = kind_of(addr, flags, stack)
        # Refresh cycles are seen one tick before the clock edge (start phase
        # = phase - 1, 33/41/49 ticks long): round their start up to the clock.
        early = REFRESH_EARLY_TICKS if kind == "refresh" else 0
        if (rel + early) % TICKS_PER_CLOCK:
            problems.append(f"{kind} cycle at {row['address']:05X} starts at tick phase "
                            f"{row['start'] % TICKS_PER_CLOCK}, not {phase}"
                            + (f" - {early}" if early else ""))
        width = "word" if kind in ("fetch", "refresh") else width_of(addr, flags)
        clock = (rel + early) // TICKS_PER_CLOCK
        ev = Event(clock=clock, kind=kind, addr=addr, width=width,
                   length=(row["end"] - t0) // TICKS_PER_CLOCK - clock + 1,
                   data=row["data"])
        if kind == "fetch":
            ev.instr_index, ev.byte_range = map_fetch(chain, chain_base, addr)
        if at == pre_at:
            ev.marker_id = PRE_MARKER   # (WP24) the prelude marker (t_pre_marker)
            if chain.prelude_marker == "push":
                ev.kind = "stack_write"
        events.append(ev)

    # Refresh is off outside F8, F13 and F17: none may appear after clock 0 with RFM.RFEN
    # clear in the prelude and in every RFM write of the chain (F17 turns it on mid-chain).
    if not refresh_any(chain) and any(e.kind == "refresh" for e in events):
        problems.append("refresh cycle with RFM off")

    # Cycle length vs the start-to-start cadence of back-to-back fetches.
    wait_clocks: dict = defaultdict(set)
    for e in events:
        wait_clocks[e.kind].add(e.length - BASE_LENGTH)
    fetches = [e for e in events if e.kind == "fetch"]
    flen = {e.length for e in fetches}
    if len(flen) != 1:
        problems.append(f"fetch lengths differ: {sorted(flen)}")
    elif len(fetches) > 1:
        cadence = min(b.clock - a.clock for a, b in zip(fetches, fetches[1:]))
        if cadence != next(iter(flen)):
            problems.append(f"fastest fetch cadence {cadence} != fetch length {flen}")
    if chain.waits >= 0 and flen and next(iter(flen)) != BASE_LENGTH + chain.waits:
        problems.append(f"fetch length {sorted(flen)} at {chain.waits} waits")

    # The fetch of the first LS's last byte, then t_fill.
    ls = next((i for i in chain.instrs if i.role == "ls"), None)
    ls_fetch = fill_index = t_fill = None
    if ls is not None:
        last = ls.offset + len(ls.code) - 1
        ls_fetch = next((k for k, e in enumerate(events) if e.kind == "fetch" and e.byte_range
                         and e.byte_range[0] <= last < e.byte_range[1]), None)
    if ls_fetch is None:
        problems.append("no fetch of the first LS's last byte")
    else:
        gaps = idle_gaps(events, ls_fetch)
        if gaps:
            before = gaps[0][0]
            fill_index = max(k for k in range(ls_fetch, before + 1)
                             if events[k].kind == "fetch")
            t_fill = events[fill_index].end
        else:
            problems.append("no idle gap after the LS fetch")

    # Data / stack / I/O cycles against the expected accesses, in program order:
    # each matched event gets the instruction index that makes it.
    want = [(k, a) for k, accs in expected.items() for a in accs]
    got = [e for e in events if e.kind not in ("fetch", "refresh")
           and e.marker_id != PRE_MARKER]
    access_mismatch = None
    if [(a.kind, a.addr) for _, a in want] == [(e.kind, e.addr) for e in got]:
        for (k, _), e in zip(want, got):
            e.instr_index = k
    else:
        access_mismatch = {"expected": [(a.kind, f"{a.addr:04X}") for _, a in want],
                           "observed": [(e.kind, f"{e.addr:04X}") for e in got]}
        problems.append("data/stack/I/O cycles differ from the expected accesses: "
                        f"expected {access_mismatch['expected']}, "
                        f"observed {access_mismatch['observed']}")

    # Markers: each marker instr's expected cycle (kind and address; for a PUSH
    # marker the tracked SP). When the program-order access match succeeded, the
    # marker's cycle is the event that match gave its instruction index (a body that
    # pushes then pops the same words writes the marker's own stack address first, so
    # matching on kind and address would take the body's push). Otherwise the first
    # unclaimed event of that kind and address after the previous marker, in chain order.
    t_markers = {}
    claimed = set()
    last_clock = -1
    for k, instr in enumerate(chain.instrs):
        if instr.role != "marker":
            continue
        mid = instr.marker_id
        first = expected[k][0]
        if access_mismatch is None:
            hit = next((j for j, e in enumerate(events) if e.instr_index == k
                        and e.kind not in ("fetch", "refresh")
                        and e.marker_id != PRE_MARKER), None)
        else:
            hit = next((j for j, e in enumerate(events) if j not in claimed
                        and e.clock > last_clock and e.kind == first.kind
                        and e.addr == first.addr), None)
        if hit is None:
            problems.append(f"marker {mid} ({chain.marker_kind}, {first.kind} at "
                            f"{first.addr:04X}) not found")
            continue
        claimed.add(hit)
        events[hit].marker_id = mid
        t_markers[mid] = events[hit].clock
        last_clock = events[hit].clock

    ends = [e.clock for e in events if e.kind == "io_write" and e.addr == END_PORT]
    if len(ends) != 1:
        problems.append(f"{len(ends)} END writes to port FF00h")
    t_end = ends[0] if ends else None

    if strict and problems:
        raise NormalizeError(f"{chain.id}: " + "; ".join(problems))
    return Normalized(run_id=chain.id, chain=chain, chain_base=chain_base, events=events,
                      phase=phase, t0_tick=t0, t_fill=t_fill, fill_index=fill_index,
                      ls_fetch_index=ls_fetch, t_markers=t_markers, t_end=t_end,
                      wait_clocks={k: sorted(v) for k, v in wait_clocks.items()},
                      expected_accesses=expected, stack_range=stack,
                      access_mismatch=access_mismatch, checks=problems,
                      t_pre_marker=t_pre_marker, pre=pre)


def prelude_pop_row(trace: list, before: int) -> int | None:
    """(WP40) the index in the raw trace of the prelude's POP PSW stack read: the first
    memory read at 0EFEh (PRE_STACK; the prelude's PUSH 0002h writes it just before) ahead
    of row `before` (clock 0). None when there is none (a model run without the tail)."""
    for k in range(before):
        row = trace[k]
        f = row["flags"]
        if (f & FLAG_READ and not f & (FLAG_IO | FLAG_REFRESH)
                and row["address"] == PRE_STACK[0]):
            return k
    return None


def prelude_marker_row(chain: Chain, trace: list) -> int | None:
    """(WP24, F18) the index in the raw trace (from reset) of the prelude marker's cycle:
    for "out" the first I/O write to port 20h; for "push" the first memory write at 0EFEh
    after the prelude's POP PSW read there (its PUSH 0002h writes 0EFEh first). None
    without a prelude marker or when it is not in the trace."""
    from .image import PRELUDE_MARKER_PORT, PRELUDE_MARKER_STACK
    kind = getattr(chain, "prelude_marker", None)
    if kind is None:
        return None
    popped = False
    for k, row in enumerate(trace):
        f = row["flags"]
        if f & FLAG_REFRESH:
            continue
        if kind == "out":
            if f & FLAG_IO and not f & FLAG_READ and row["address"] == PRELUDE_MARKER_PORT:
                return k
            continue
        if f & FLAG_IO or row["address"] != PRELUDE_MARKER_STACK:
            continue
        if f & FLAG_READ:
            popped = True
        elif popped:
            return k
    if kind == "push" and not popped:
        # the model's trace (prelude_tail=regs) has no PUSH 0002h / POP PSW: its first write
        return next((k for k, row in enumerate(trace) if row["address"] == PRELUDE_MARKER_STACK
                     and not row["flags"] & (FLAG_READ | FLAG_IO | FLAG_REFRESH)), None)
    return None
