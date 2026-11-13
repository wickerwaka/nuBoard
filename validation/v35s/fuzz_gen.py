"""F5: the random-instruction program generator (docs/v35s-function-plan.md, stage F5).

A program is a list of abstract items, each (kind, seed). `materialize` walks the list with a
model of what the generator knows about the machine (the registers whose values it set, the
segment registers, SP, DIR, the register bank, the stack it pushed) and turns each item into
bytes, inserting the setup instructions an item needs (an address register loaded so a memory
operand lands in its window, a count loaded before REP, a valid segment). Removing items and
materializing again gives a program that still respects every constraint, which is how a
failing program is shrunk.

The memory map (linear; PS = 0 except inside far-called bodies and after a far BR):

    00000-003FF  the vector table: vector n -> 0000:0400 + 6n
    00400-009FF  the stubs: INC byte SS:[7E00 + n]; RETI (vector 7: BR to the FPO handler)
    00A00-00AFF  the FPO handler (adds the escape's length, SS:[7F00], to the pushed PC)
    01000-03FFF  the program's code
    04000-04FFF  the external data window (preloaded with a seeded pattern)
    06000-06FFF  the stack page (SS = 0000 throughout; SP kept in 6100-6FF0)
    07000-070FF  the bank initialisation table (banks 0-6 copied at the start)
    07E00-07EFF  the per-vector counts (one byte each)
    07F00        the FPO escape's length
    0C000-0C0FF  the eight register banks copied at the end; 0C100-0C1FF the SFRs dumped
    FFE00-FFEFF  internal RAM = the register banks (IDB FFh); FFF00-FFFFF the SFR page

Observation: after every K fuzzed instructions PUSH PSW and PUSH of the registers the last K
instructions wrote (every fourth time PUSH R, DS0, DS1), then MOV SP back: the pushes are
external writes, so the trace carries every observation. At the end the banks and a list of
SFRs are copied out and OUT FF00h passes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

R16 = ["AW", "CW", "DW", "BW", "SP", "BP", "IX", "IY"]
R8 = ["AL", "CL", "DL", "BL", "AH", "CH", "DH", "BH"]
SREG = ["DS1", "PS", "SS", "DS0"]
SEGPFX = {"DS1": 0x26, "PS": 0x2E, "SS": 0x36, "DS0": 0x3E}
AW, CW, DW, BW, SP, BP, IX, IY = range(8)
ALU = ["ADD", "OR", "ADDC", "SUBC", "AND", "SUB", "XOR", "CMP"]
SHF = ["ROL", "ROR", "ROLC", "RORC", "SHL", "SHR", None, "SHRA"]
G3 = ["TEST", None, "NOT", "NEG", "MULU", "MUL", "DIVU", "DIV"]
CC = ["BV", "BNV", "BC", "BNC", "BE", "BNE", "BNH", "BH", "BN", "BP", "BPE", "BPO", "BLT", "BGE",
      "BLE", "BGT"]
# rm -> (base, index, default segment)
EA_REGS = {0: (BW, IX, "DS0"), 1: (BW, IY, "DS0"), 2: (BP, IX, "SS"), 3: (BP, IY, "SS"),
           4: (IX, None, "DS0"), 5: (IY, None, "DS0"), 6: (BP, None, "SS"), 7: (BW, None, "DS0")}
EA_TXT = {0: "BW+IX", 1: "BW+IY", 2: "BP+IX", 3: "BP+IY", 4: "IX", 5: "IY", 6: "BP", 7: "BW"}

# ------------------------------------------------------------------ the map
IVT, STUBS, FPOH = 0x0000, 0x0400, 0x0A00
CODE, CODE_END = 0x1000, 0x4000
DATA_LO, DATA_HI = 0x4000, 0x5000
STK_PAGE = 0x6000
SP_LO, SP_HI = 0x6100, 0x6FF0
INIT_TBL = 0x7000
CNT = 0x7E00
FPOLEN = 0x7F00
DUMP = 0xC000
IRAM = 0xFFE00
SFRB = 0xFFF00
HARNESS_PORTS = range(0xFF00, 0xFF20)
PAGES = (0x00, 0x01, 0x02, 0x03, 0x04, 0x06, 0x07, 0x0C, 0xFF)

# bank slots (data book layout, dump.BANK_LAYOUT)
SLOT = {"VPC": 0x02, "PSWS": 0x04, "PCS": 0x06, "DS0": 0x08, "SS": 0x0A, "PS": 0x0C, "DS1": 0x0E,
        "IY": 0x10, "IX": 0x12, "BP": 0x14, "SP": 0x16, "BW": 0x18, "DW": 0x1A, "CW": 0x1C,
        "AW": 0x1E}
SLOT_OF_R16 = {AW: 0x1E, CW: 0x1C, DW: 0x1A, BW: 0x18, SP: 0x16, BP: 0x14, IX: 0x12, IY: 0x10}
# the current bank's bytes an operand may touch: the general registers but SP, DS0, DS1 and
# the three save slots (never PS: README F1 "PS", never SS / SP: the stack)
CUR_OK = (set(range(0x00, 0x0A)) | set(range(0x0E, 0x16)) | set(range(0x18, 0x20)))

# SFRs a random operand may touch (storage with no side effect but FLAG -> PSW F0 / F1):
# EMS0-2, TMMS0-2, FLAG by byte or word (both bytes listed); MD0 / MD1 by word only
SFR_BYTE = (0x44, 0x45, 0x46, 0x94, 0x95, 0x96, 0xEA)
SFR_WORD = (0x44, 0x45, 0x94, 0x95, 0x82, 0x8A)
# the SFRs the plain layers dump (each by byte; MD0 / MD1 by word)
DUMP_SFR_PLAIN = (0x44, 0x45, 0x46, 0x94, 0x95, 0x96, 0xEA, 0xFC)
DUMP_SFR_WORD = (0x82, 0x8A)

PS_CHOICES = (0x0000, 0x0010, 0x0080, 0x00F0)
SEG_EXT = (0x0400, 0x0300, 0x03F0, 0x0380, 0x0200, 0x0000, 0x0010, 0x0123, 0x03FF)
SEG_ONCHIP = (0xFFE0, 0xF000, 0xFF00, 0xFE00)


def hx(v, n=4):
    return f"{v:0{n}X}h"


# ------------------------------------------------------------------ the state model
@dataclass
class State:
    reg: list = field(default_factory=lambda: [None] * 16)    # byte knowledge: reg*2 + hi
    seg: dict = field(default_factory=lambda: {"DS1": None, "PS": 0, "SS": 0, "DS0": None})
    dir: int | None = 0
    rb: int = 7
    banks: dict = field(default_factory=dict)       # bank -> {slot offset: byte or None}
    stack: dict = field(default_factory=dict)       # address -> known byte (pushed by the program)
    dirty: set = field(default_factory=set)          # 16-bit regs / sregs written since the last observation
    ie: int = 0
    brk: int = 0

    def get16(self, r):
        lo, hi = self.reg[2 * r], self.reg[2 * r + 1]
        return None if lo is None or hi is None else lo | hi << 8

    def get8(self, r8):
        r, h = r8 & 3, r8 >> 2
        return self.reg[2 * r + h]

    def set16(self, r, v, dirty=True):
        self.reg[2 * r] = None if v is None else v & 0xFF
        self.reg[2 * r + 1] = None if v is None else (v >> 8) & 0xFF
        if dirty:
            self.dirty.add(R16[r])

    def set8(self, r8, v, dirty=True):
        r, h = r8 & 3, r8 >> 2
        self.reg[2 * r + h] = None if v is None else v & 0xFF
        if dirty:
            self.dirty.add(R16[r])

    @property
    def sp(self):
        return self.get16(SP)

    def copy(self):
        s = State()
        s.reg = list(self.reg)
        s.seg = dict(self.seg)
        s.dir, s.rb, s.ie, s.brk = self.dir, self.rb, self.ie, self.brk
        s.banks = {b: dict(v) for b, v in self.banks.items()}
        s.stack = dict(self.stack)
        s.dirty = set(self.dirty)
        return s

    def merge(self, other):
        """The state after a join: what both paths agree on."""
        for i in range(16):
            if self.reg[i] != other.reg[i]:
                self.reg[i] = None
        for k in self.seg:
            if self.seg[k] != other.seg[k]:
                self.seg[k] = None
        if self.dir != other.dir:
            self.dir = None
        for b in set(self.banks) | set(other.banks):
            x, y = self.banks.get(b, {}), other.banks.get(b, {})
            self.banks[b] = {o: x.get(o) for o in range(32) if x.get(o) == y.get(o)}
        self.stack = {a: v for a, v in self.stack.items() if other.stack.get(a) == v}
        self.dirty |= other.dirty
        if self.ie != other.ie:
            self.ie = None


# ------------------------------------------------------------------ the builder
@dataclass
class Ins:
    addr: int
    data: bytearray
    text: str
    tag: str            # fuzz / setup / obs / frame / junk
    key: str = ""       # the coverage key of a fuzzed instruction
    maybe: bool = False  # in a conditionally skipped block
    times: int = 1       # executions (a loop body: the count)


class Builder:
    def __init__(self, base):
        self.base = base
        self.pc = base
        self.code = bytearray()
        self.ins: list[Ins] = []
        self.labels = {}
        self.fix = []        # (code offset, kind, label, end address, ps)
        self.maybe = 0
        self.times = 1
        self.n = 0

    def label(self, name=None):
        if name is None:
            self.n += 1
            name = f"L{self.n}"
        return name

    def place(self, name):
        self.labels[name] = self.pc

    def emit(self, data, text, tag="fuzz", key=""):
        data = bytearray(data)
        i = Ins(self.pc, data, text, tag, key, self.maybe > 0, self.times)
        self.ins.append(i)
        self.code += data
        self.pc += len(data)
        return i

    def fixup(self, ins, at, kind, label, ps=0):
        """Patch ins.data[at] (rel8 / rel16 from the instruction's end, or abs16 = the label's
        offset from ps)."""
        self.fix.append((ins, at, kind, label, ps))

    def resolve(self):
        for ins, at, kind, label, ps in self.fix:
            t = self.labels[label]
            end = ins.addr + len(ins.data)
            if kind == "rel8":
                d = t - end
                if not -128 <= d <= 127:
                    raise ValueError(f"rel8 out of range at {ins.addr:05X}: {d}")
                v = bytes([d & 0xFF])
            elif kind == "rel16":
                v = ((t - end) & 0xFFFF).to_bytes(2, "little")
            else:
                v = ((t - 16 * ps) & 0xFFFF).to_bytes(2, "little")
            ins.data[at:at + len(v)] = v
            off = ins.addr - self.base
            self.code[off + at:off + at + len(v)] = v
        return bytes(self.code)


class Retry(Exception):
    pass


@dataclass
class Mem:
    mod: int
    rm: int
    disp: bytes
    pfx: bytes          # the segment override (or b"")
    lin: int
    size: int
    region: str         # ext / iram / sfr
    seg: str
    text: str

    def modrm(self, reg):
        return bytes([self.mod << 6 | (reg & 7) << 3 | self.rm])

    @property
    def mode(self):
        if self.mod == 0 and self.rm == 6:
            return "dir"
        return ("m00", "d8", "d16")[self.mod]


# ------------------------------------------------------------------ the generator proper
class Gen:
    """Materializes items with a State and a Builder."""

    def __init__(self, layer, opts=None):
        self.layer = layer
        self.opts = dict(opts or {})
        self.b = Builder(CODE)
        self.st = State()
        self.reserved = set()          # registers an enclosing construct needs kept
        self.ctx = []                  # enclosing constructs: "skip", "loop", "sub"
        self.cov = {}
        self.obs_n = 0
        self.fuzz_since = 0
        self.r = random.Random(0)

    # -------------------------------------------------------------- emit helpers
    def setup(self, data, text):
        self.b.emit(data, text, "setup")

    def mov16(self, r, v):
        v &= 0xFFFF
        self.setup(bytes([0xB8 + r]) + v.to_bytes(2, "little"), f"MOV {R16[r]}, {hx(v)}")
        self.st.set16(r, v, dirty=False)
        if r == SP:
            self.st.stack = {}

    def mov8(self, r8, v):
        self.setup(bytes([0xB0 + r8, v & 0xFF]), f"MOV {R8[r8]}, {hx(v & 0xFF, 2)}")
        self.st.set8(r8, v, dirty=False)

    def push_known(self, v):
        """Stack shadow for a pushed word."""
        sp = self.st.sp
        sp = (sp - 2) & 0xFFFF
        self.st.set16(SP, sp, dirty=False)
        if v is None:
            self.st.stack.pop(sp, None)
            self.st.stack.pop(sp + 1, None)
        else:
            self.st.stack[sp] = v & 0xFF
            self.st.stack[sp + 1] = (v >> 8) & 0xFF

    def pop_known(self):
        sp = self.st.sp
        lo, hi = self.st.stack.get(sp), self.st.stack.get(sp + 1)
        self.st.set16(SP, sp + 2, dirty=False)
        return None if lo is None or hi is None else lo | hi << 8

    def need_room(self, push=2, pop=0):
        sp = self.st.sp
        if sp is None or sp - push - 40 < SP_LO or sp + pop > SP_HI:
            raise Retry("stack")

    def load_seg(self, sreg, v):
        """PUSH imm16; POP sreg (no general register touched)."""
        self.need_room()
        self.setup(b"\x68" + v.to_bytes(2, "little"), f"PUSH {hx(v)}")
        pop = {"DS1": 0x07, "SS": 0x17, "DS0": 0x1F}[sreg]
        self.setup(bytes([pop]), f"POP {sreg}")
        self.st.seg[sreg] = v

    def rnd_seg_for(self, lin, size, onchip):
        if onchip:
            cands = [s for s in SEG_ONCHIP if 0 <= lin - 16 * s <= 0x10000 - size]
        else:
            cands = [s for s in SEG_EXT if 0 <= lin - 16 * s <= 0x10000 - size]
        if not cands or self.r.random() < 0.3:
            lo = max(0, (lin + size - 0x10000 + 15) // 16)
            hi = lin // 16
            return self.r.randint(lo, hi)
        return self.r.choice(cands)

    def key(self, *parts):
        return "|".join(str(p) for p in parts)

    def fz(self, data, text, key, wr16=(), wr8=(), unk16=()):
        """Emit a fuzzed instruction and record its writes."""
        i = self.b.emit(data, text, "fuzz", key)
        for r in wr16:
            self.st.set16(r, None)
        for r in wr8:
            self.st.set8(r, None)
        self.cov[key] = self.cov.get(key, 0) + (0 if i.maybe else i.times)
        self.cov["?" + key] = self.cov.get("?" + key, 0) + (1 if i.maybe else 0)
        self.fuzz_since += 1
        return i

    # -------------------------------------------------------------- memory operands
    def pick_iram(self, size, write):
        st = self.st
        for _ in range(20):
            b = self.r.randrange(8)
            off = self.r.randrange(0x20 - size + 1) if self.r.random() < 0.8 else self.r.randrange(0x1F)
            lin = IRAM + 0x20 * b + off
            if lin + size > IRAM + 0x100:
                continue
            ok = True
            for k in range(size):
                bb, oo = divmod(off + k, 0x20)
                bb += b
                if bb == st.rb and oo not in CUR_OK:
                    ok = False
                if self.layer in ("b", "c") and bb != st.rb and oo in (2, 3, 0x0A, 0x0B, 0x0C, 0x0D, 0x16, 0x17):
                    # keep the other banks' SS / PS / SP / vector PC as the generator set them
                    ok = ok and not write
                if bb == self.opts.get("protect_bank"):
                    ok = False
            if ok:
                return lin
        raise Retry("iram")

    def pick_sfr(self, size):
        return SFRB + self.r.choice(SFR_BYTE if size == 1 else SFR_WORD)

    def mem(self, size, write=True, onchip=True, sfr=True, region=None, lin=None, exclude=()):
        """A memory operand of `size` bytes (setup instructions emitted as needed)."""
        st = self.st
        if lin is None:
            x = self.r.random()
            if region is None:
                pi = self.opts.get("p_iram", 0.12) if onchip else 0
                ps_ = self.opts.get("p_sfr", 0.06) if (onchip and sfr) else 0
                region = "iram" if x < pi else "sfr" if x < pi + ps_ else "ext"
            if region == "iram":
                lin = self.pick_iram(size, write)
            elif region == "sfr":
                lin = self.pick_sfr(size)
            else:
                lin = self.r.randrange(DATA_LO, DATA_HI - size + 1)
        else:
            region = "iram" if IRAM <= lin < SFRB else "sfr" if lin >= SFRB else "ext"
        oc = region != "ext"
        for _ in range(12):
            mod = self.r.choice((0, 0, 1, 1, 2))
            rm = self.r.randrange(8)
            if mod == 0 and rm == 6 and self.r.random() < 0.5:
                rm = self.r.randrange(8)
            direct = mod == 0 and rm == 6
            base, idx, dseg = EA_REGS[rm]
            if direct:
                base = idx = None
                dseg = "DS0"
            need = [r for r in (base, idx) if r is not None]
            if any(r in self.reserved or r in exclude for r in need if st.get16(r) is None):
                continue
            # the segment
            valid = [s for s in SREG if st.seg[s] is not None
                     and 0 <= lin - 16 * st.seg[s] <= 0x10000 - size]
            if valid and self.r.random() < 0.85:
                seg = dseg if dseg in valid and self.r.random() < 0.6 else self.r.choice(valid)
            else:
                seg = dseg if dseg in ("DS0", "DS1") and self.r.random() < 0.6 else \
                    self.r.choice(("DS0", "DS1"))
                if self.ctx and seg in self.reserved:
                    continue
                self.load_seg(seg, self.rnd_seg_for(lin, size, oc))
            off = lin - 16 * st.seg[seg]
            pfx = b"" if seg == dseg else bytes([SEGPFX[seg]])
            if not pfx and self.r.random() < 0.05:
                pfx = bytes([SEGPFX[seg]])          # a redundant override
            if direct:
                disp = off.to_bytes(2, "little")
                return Mem(mod, rm, disp, pfx, lin, size, region, seg,
                           f"{seg}:[{hx(off)}]")
            vals = [st.get16(r) for r in need]
            dv = None
            if all(v is not None for v in vals):
                want = (off - sum(vals)) & 0xFFFF
                if mod == 0 and want == 0:
                    dv = 0
                elif mod == 1 and (want < 0x80 or want >= 0xFF80):
                    dv = want
                elif mod == 2:
                    dv = want
            if dv is None:
                free = [r for r in need if r not in self.reserved and r not in exclude]
                if not free:
                    continue
                dv = 0 if mod == 0 else self.r.randrange(-128, 128) & 0xFFFF if mod == 1 \
                    else self.r.randrange(0x10000)
                setr = self.r.choice([r for r in free if st.get16(r) is None] or free)
                for r in need:
                    if r != setr and st.get16(r) is None:
                        self.mov16(r, self.r.randrange(0x10000))
                rest = sum(st.get16(r) for r in need if r != setr)
                self.mov16(setr, off - dv - rest)
            disp = b"" if mod == 0 else bytes([dv & 0xFF]) if mod == 1 else dv.to_bytes(2, "little")
            d = "" if mod == 0 else f"+{hx(dv & 0xFF, 2) if mod == 1 else hx(dv)}"
            return Mem(mod, rm, disp, pfx, lin, size, region, seg,
                       f"{seg}:[{EA_TXT[rm]}{d}]")
        raise Retry("mem")

    def wrote_mem(self, m):
        """An on-chip write to the current bank's slots changes the register."""
        if m.region != "iram":
            return
        st = self.st
        for k in range(m.size):
            a = m.lin + k - IRAM
            b, o = divmod(a, 0x20)
            if b == st.rb:
                for r, s in SLOT_OF_R16.items():
                    if o in (s, s + 1):
                        st.set16(r, None)
                if o in (0x08, 0x09):
                    st.seg["DS0"] = None
                    st.dirty.add("DS0")
                if o in (0x0E, 0x0F):
                    st.seg["DS1"] = None
                    st.dirty.add("DS1")
                if o < 8:
                    st.banks.setdefault(b, {})[o] = None
            else:
                st.banks.setdefault(b, {})[o] = None

    # -------------------------------------------------------------- the register banks (layer b)
    LIVE_SLOTS = {"AW": AW, "CW": CW, "DW": DW, "BW": BW, "SP": SP, "BP": BP, "IX": IX, "IY": IY}

    def save_live(self):
        """The current bank's slots from the live registers (the model)."""
        st = self.st
        bk = st.banks.setdefault(st.rb, {})
        for name, r in self.LIVE_SLOTS.items():
            o = SLOT[name]
            bk[o], bk[o + 1] = st.reg[2 * r], st.reg[2 * r + 1]
        for s in ("DS0", "SS", "PS", "DS1"):
            v = st.seg[s]
            o = SLOT[s]
            bk[o] = None if v is None else v & 0xFF
            bk[o + 1] = None if v is None else v >> 8

    def bank_word(self, b, slot):
        bk = self.st.banks.get(b, {})
        lo, hi = bk.get(slot), bk.get(slot + 1)
        return None if lo is None or hi is None else lo | hi << 8

    def load_live(self, b):
        """Switch the model to bank b (its slots become the live registers)."""
        st = self.st
        st.rb = b
        for name, r in self.LIVE_SLOTS.items():
            st.set16(r, self.bank_word(b, SLOT[name]))
        for s in ("DS0", "SS", "PS", "DS1"):
            st.seg[s] = self.bank_word(b, SLOT[s])
            st.dirty.add(s)
        st.stack = {}

    def onchip_seg(self, lin):
        """A segment register (DS0 / DS1) holding a value that reaches `lin`; loaded if none."""
        st = self.st
        for s in ("DS1", "DS0"):
            v = st.seg[s]
            if v is not None and 0 <= lin - 16 * v <= 0xFFFE and s not in self.reserved:
                return s
        s = "DS1" if "DS1" not in self.reserved else "DS0"
        self.load_seg(s, 0xFFE0)
        return s

    def bank_set(self, b, slot, v):
        """MOV word to bank b's slot (setup), unless the model already holds v."""
        if self.bank_word(b, slot) == v & 0xFFFF:
            return
        lin = IRAM + 0x20 * b + slot
        s = self.onchip_seg(lin)
        off = lin - 16 * self.st.seg[s]
        pfx = b"" if s == "DS0" else bytes([SEGPFX[s]])
        self.setup(pfx + b"\xC7\x06" + off.to_bytes(2, "little") + (v & 0xFFFF).to_bytes(2, "little"),
                   f"MOV {s}:[{hx(off)}], {hx(v & 0xFFFF)} (bank {b} slot {slot:02X}h)")
        bk = self.st.banks.setdefault(b, {})
        bk[slot], bk[slot + 1] = v & 0xFF, (v >> 8) & 0xFF

    def ready_bank(self, b, ps):
        """Bank b usable as a target: SS 0, PS ps, SP in the window."""
        assert b != self.st.rb
        self.bank_set(b, SLOT["SS"], 0)
        self.bank_set(b, SLOT["PS"], ps)
        sp = self.bank_word(b, SLOT["SP"])
        if sp is None or not SP_LO + 0x100 <= sp <= SP_HI - 0x40:
            self.bank_set(b, SLOT["SP"], self.r.randrange(0x6400, 0x6F00) & ~1)

    def known_reg(self, b_val, avoid=()):
        """A 16-bit register (not SP) loaded with a value whose low three bits are b_val."""
        r = self.r.choice([x for x in (AW, CW, DW, BW, BP, IX, IY) if x not in self.reserved and x not in avoid])
        v = self.st.get16(r)
        if v is None or v & 7 != b_val:
            self.mov16(r, (self.r.randrange(0x2000) << 3) | b_val)
        return r

    def f_bank(self):
        st = self.st
        if self.ctx or self.reserved:
            raise Retry("ctx")
        kind = self.r.choice(("tsksw", "brkcs", "brkcs", "retrbi", "movspa", "movspb", "reti", "fint"))
        b = self.b
        ps = st.seg["PS"]
        cur = st.rb
        if ps is None:
            raise Retry("ps")
        if kind == "fint":
            self.fz(b"\x0F\x92", "FINT", self.key("FINT", "", "", "", ""))
            return
        if kind in ("tsksw", "retrbi", "reti"):
            # one way: continue at the next instruction in bank t
            t = self.r.choice([x for x in range(8) if x != cur])
            n = t if kind != "tsksw" or self.r.random() < 0.7 else self.r.randrange(8)
            self.ready_bank(t, ps)
            v = self.psw_value() | (t << 12) | 0x8000
            lab = b.label()
            if kind == "reti":
                self.need_room(8)
                self.setup(b"\x68" + v.to_bytes(2, "little"), f"PUSH {hx(v)}")
                self.setup(b"\x0E", "PUSH PS")
                i = b.emit(b"\x68\0\0", "PUSH target", "setup")
                b.fixup(i, 1, "abs", lab, ps)
                self.fz(b"\xCF", "RETI", self.key("RETI", "bank", "", "", ""))
                # README F1: the frame's SP + 6 lands in the old bank; PS in the new bank's slot
                st.set16(SP, st.sp + 6)
                self.save_live()
            else:
                src = n if kind == "tsksw" else cur
                if src == cur and kind == "tsksw":
                    raise Retry("self")
                # the PC save and PSW save of the source bank (a pair of on-chip stores)
                lin = IRAM + 0x20 * src + SLOT["PCS"]
                s = self.onchip_seg(lin)
                off = lin - 16 * st.seg[s]
                pfx = b"" if s == "DS0" else bytes([SEGPFX[s]])
                i = b.emit(pfx + b"\xC7\x06" + off.to_bytes(2, "little") + b"\0\0",
                           f"MOV {s}:[{hx(off)}], target (bank {src} PC save)", "setup")
                b.fixup(i, len(i.data) - 2, "abs", lab, ps)
                self.bank_set(src, SLOT["PSWS"], v)
                st.banks.setdefault(src, {})[SLOT["PCS"]] = None
                st.banks[src][SLOT["PCS"] + 1] = None
                if kind == "tsksw":
                    r = self.known_reg(n)
                    self.fz(bytes([0x0F, 0x94, 0xF8 | r]), f"TSKSW {R16[r]}", self.key("TSKSW", "", "", "", ""))
                    self.save_live()
                    for o in (SLOT["PCS"], SLOT["PCS"] + 1, SLOT["PSWS"], SLOT["PSWS"] + 1):
                        st.banks[cur][o] = None
                else:
                    self.fz(b"\x0F\x91", "RETRBI", self.key("RETRBI", "oneway", "", "", ""))
                    self.save_live()
            b.place(lab)
            self.load_live(t)
            if kind == "reti":
                st.seg["PS"] = ps
                bk = st.banks.setdefault(t, {})
                bk[SLOT["PS"]], bk[SLOT["PS"] + 1] = ps & 0xFF, ps >> 8
            st.dir = (v >> 10) & 1
            st.ie = (v >> 9) & 1
            return
        if kind == "brkcs":
            n = self.r.randrange(8)
            sub, over = b.label(), b.label()
            if n != cur:
                self.ready_bank(n, ps)
            lin = IRAM + 0x20 * n + SLOT["VPC"]
            s = self.onchip_seg(lin)
            off = lin - 16 * st.seg[s]
            pfx = b"" if s == "DS0" else bytes([SEGPFX[s]])
            i = b.emit(pfx + b"\xC7\x06" + off.to_bytes(2, "little") + b"\0\0",
                       f"MOV {s}:[{hx(off)}], sub (bank {n} vector PC)", "setup")
            b.fixup(i, len(i.data) - 2, "abs", sub, ps)
            st.banks.setdefault(n, {})[SLOT["VPC"]] = None
            st.banks[n][SLOT["VPC"] + 1] = None
            r = self.known_reg(n)
            self.fz(bytes([0x0F, 0x2D, 0xF8 | r]), f"BRKCS {R16[r]}", self.key("BRKCS", "", "", "", ""))
            j = b.emit(b"\xE9\0\0", "BR over", "setup")
            b.fixup(j, 1, "rel16", over)
            b.place(sub)
            self.save_live()
            outer = self.st.copy()
            self.load_live(n)
            dir0, ie0 = st.dir, st.ie
            st.ie = 0
            self.ctx.append("sub")
            try:
                self.inner(self.r.randint(0, 4))
            finally:
                self.ctx.pop()
            if st.sp is None or st.seg["PS"] != ps or st.seg["SS"] != 0:
                raise Retry("bank body")
            self.fz(b"\x0F\x91", "RETRBI", self.key("RETRBI", "brkcs", "", "", ""))
            self.save_live()
            inner_banks = {k: dict(v) for k, v in st.banks.items()}
            for o in (SLOT["PSWS"], SLOT["PSWS"] + 1, SLOT["PCS"], SLOT["PCS"] + 1):
                inner_banks[n][o] = None
            if n == cur:
                # the same bank: the body's registers are the caller's now
                self.load_live(cur)
                st.banks = inner_banks
                st.dir, st.ie = dir0, ie0
            else:
                self.st = outer
                outer.banks = inner_banks
                self.load_live(cur)
                self.st.dir, self.st.ie = dir0, ie0
            b.place(over)
            return
        if kind == "movspa":
            m = self.r.choice([x for x in range(8) if x != cur])
            self.ready_bank(m, ps)
            self.bank_set(cur, SLOT["PSWS"], self.psw_value() | (m << 12) | 0x8000)
            self.fz(b"\x0F\x25", "MOVSPA", self.key("MOVSPA", "", "", "", ""))
            st.set16(SP, self.bank_word(m, SLOT["SP"]))
            st.seg["SS"] = 0
            st.stack = {}
            return
        if kind == "movspb":
            n = self.r.choice([x for x in range(8) if x != cur])
            r = self.known_reg(n)
            self.fz(bytes([0x0F, 0x95, 0xF8 | r]), f"MOVSPB {R16[r]}", self.key("MOVSPB", "", "", "", ""))
            bk = st.banks.setdefault(n, {})
            sp = st.sp
            bk[SLOT["SP"]], bk[SLOT["SP"] + 1] = sp & 0xFF, sp >> 8
            bk[SLOT["SS"]], bk[SLOT["SS"] + 1] = 0, 0

    # -------------------------------------------------------------- operand helpers
    def rm_operand(self, size, write=True, reg_ok=True, mem_ok=True, sp_ok=False, **kw):
        """Either a register (mod 11) or a memory operand. Returns (Mem or None, reg, text)."""
        if reg_ok and (not mem_ok or self.r.random() < 0.5):
            if size == 1:
                r = self.r.randrange(8)
                if write and (r & 3) in self.reserved:
                    raise Retry("rsv")
                return None, r, R8[r]
            choices = [r for r in range(8) if (r != SP or sp_ok)
                       and not (write and r in self.reserved)]
            r = self.r.choice(choices)
            return None, r, R16[r]
        m = self.mem(size, write=write, **kw)
        return m, None, m.text

    def modrm_bytes(self, m, rmreg, reg):
        if m is None:
            return bytes([0xC0 | (reg & 7) << 3 | rmreg])
        return m.modrm(reg) + m.disp

    def rnd_pfx(self, allow_rep=True, allow_lock=True):
        p = b""
        if allow_lock and self.r.random() < 0.03:
            p += b"\xF0"
        if allow_rep and self.r.random() < 0.03:
            p += bytes([self.r.choice((0xF3, 0xF2, 0x64, 0x65))])
        return p

    def reg_write(self, size, r):
        if size == 1:
            self.st.set8(r, None)
        else:
            self.st.set16(r, None)

    def sp_guard(self, size, rmreg, m):
        return m is None and size == 2 and rmreg == SP

    # -------------------------------------------------------------- the forms
    def f_alu(self):
        op = self.r.randrange(8)
        w = self.r.randrange(2)
        size = 1 + w
        kind = self.r.choice(("rm,r", "r,rm", "acc,imm", "rm,imm", "rm,imm"))
        pfx = self.rnd_pfx()
        wr = op != 7
        if kind == "rm,r":
            m, rr, t = self.rm_operand(size, write=wr)
            reg = self.r.randrange(8)
            if size == 2 and reg == SP and m is None and rr == SP:
                raise Retry("sp")
            if m is None and size == 2 and rr == SP:
                raise Retry("sp")
            data = (m.pfx if m else b"") + pfx + bytes([op * 8 + w]) + self.modrm_bytes(m, rr, reg)
            regn = (R8 if size == 1 else R16)[reg]
            self.fz(data, f"{ALU[op]} {t}, {regn}", self.key(ALU[op], "rm,r", m.mode if m else "reg",
                                                            "bw"[w], m.region if m else ""))
            if wr:
                if m:
                    self.wrote_mem(m)
                else:
                    self.reg_write(size, rr)
        elif kind == "r,rm":
            reg = self.r.randrange(8)
            if size == 2 and reg == SP and wr:
                raise Retry("sp")
            if wr and (reg & (3 if size == 1 else 7)) in self.reserved:
                raise Retry("rsv")
            m, rr, t = self.rm_operand(size, write=False, sp_ok=True)
            data = (m.pfx if m else b"") + pfx + bytes([op * 8 + 2 + w]) + self.modrm_bytes(m, rr, reg)
            regn = (R8 if size == 1 else R16)[reg]
            self.fz(data, f"{ALU[op]} {regn}, {t}", self.key(ALU[op], "r,rm", m.mode if m else "reg",
                                                            "bw"[w], m.region if m else ""))
            if wr:
                self.reg_write(size, reg)
        elif kind == "acc,imm":
            if wr and AW in self.reserved:
                raise Retry("rsv")
            imm = self.r.randrange(256 if w == 0 else 0x10000)
            data = pfx + bytes([op * 8 + 4 + w]) + imm.to_bytes(size, "little")
            self.fz(data, f"{ALU[op]} {'AL' if w == 0 else 'AW'}, {hx(imm, 2 * size)}",
                    self.key(ALU[op], "acc,imm", "", "bw"[w], ""))
            if wr:
                if w:
                    self.st.set16(AW, None)
                else:
                    self.st.set8(0, None)
        else:
            sub = self.r.choice((0x81, 0x83)) if w else self.r.choice((0x80, 0x80, 0x82))
            # ADD / SUB SP, imm: SP tracked
            if w == 1 and op in (0, 5) and self.r.random() < 0.05 and not self.ctx:
                imm = self.r.randrange(-8, 9)
                sp = self.st.sp
                nsp = sp + imm if op == 0 else sp - imm
                if not SP_LO + 64 <= nsp <= SP_HI:
                    raise Retry("sp")
                data = bytes([0x83, 0xC0 | op << 3 | SP, imm & 0xFF])
                self.fz(data, f"{ALU[op]} SP, {imm}", self.key(ALU[op], "rm,imm83", "reg", "w", "SP"))
                self.st.set16(SP, nsp)
                self.st.stack = {}
                return
            m, rr, t = self.rm_operand(size, write=wr)
            if m is None and size == 2 and rr == SP:
                raise Retry("sp")
            isz = 2 if sub == 0x81 else 1
            imm = self.r.randrange(256 ** isz)
            data = (m.pfx if m else b"") + pfx + bytes([sub]) + self.modrm_bytes(m, rr, op) + \
                imm.to_bytes(isz, "little")
            self.fz(data, f"{ALU[op]} {t}, {hx(imm, 2 * isz)}",
                    self.key(ALU[op], f"rm,imm{sub:02X}", m.mode if m else "reg", "bw"[w],
                             m.region if m else ""))
            if wr:
                if m:
                    self.wrote_mem(m)
                else:
                    self.reg_write(size, rr)

    def f_test(self):
        w = self.r.randrange(2)
        size = 1 + w
        kind = self.r.choice(("rm,r", "acc,imm", "rm,imm"))
        pfx = self.rnd_pfx()
        if kind == "rm,r":
            m, rr, t = self.rm_operand(size, write=False, sp_ok=True)
            reg = self.r.randrange(8)
            data = (m.pfx if m else b"") + pfx + bytes([0x84 + w]) + self.modrm_bytes(m, rr, reg)
            self.fz(data, f"TEST {t}, {(R8 if w == 0 else R16)[reg]}",
                    self.key("TEST", "rm,r", m.mode if m else "reg", "bw"[w], m.region if m else ""))
        elif kind == "acc,imm":
            imm = self.r.randrange(256 ** size)
            self.fz(pfx + bytes([0xA8 + w]) + imm.to_bytes(size, "little"), f"TEST acc, {hx(imm)}",
                    self.key("TEST", "acc,imm", "", "bw"[w], ""))
        else:
            m, rr, t = self.rm_operand(size, write=False, sp_ok=True)
            imm = self.r.randrange(256 ** size)
            data = (m.pfx if m else b"") + pfx + bytes([0xF6 + w]) + self.modrm_bytes(m, rr, 0) + \
                imm.to_bytes(size, "little")
            self.fz(data, f"TEST {t}, {hx(imm)}", self.key("TEST", "rm,imm", m.mode if m else "reg",
                                                          "bw"[w], m.region if m else ""))

    def f_xch(self):
        w = self.r.randrange(2)
        size = 1 + w
        if w and self.r.random() < 0.3:
            r = self.r.choice([1, 2, 3, 5, 6, 7])
            if r in self.reserved or AW in self.reserved:
                raise Retry("rsv")
            self.fz(bytes([0x90 + r]), f"XCH AW, {R16[r]}", self.key("XCH", "AW,r", "", "w", ""))
            a, b_ = self.st.get16(AW), self.st.get16(r)
            self.st.set16(AW, b_)
            self.st.set16(r, a)
            return
        m, rr, t = self.rm_operand(size, write=True)
        reg = self.r.randrange(8)
        if size == 2 and (reg == SP or (m is None and rr == SP)):
            raise Retry("sp")
        if (reg & (3 if size == 1 else 7)) in self.reserved:
            raise Retry("rsv")
        data = (m.pfx if m else b"") + self.rnd_pfx() + bytes([0x86 + w]) + self.modrm_bytes(m, rr, reg)
        self.fz(data, f"XCH {t}, {(R8 if w == 0 else R16)[reg]}",
                self.key("XCH", "rm,r", m.mode if m else "reg", "bw"[w], m.region if m else ""))
        self.reg_write(size, reg)
        if m:
            self.wrote_mem(m)
        else:
            self.reg_write(size, rr)

    def f_mov(self):
        w = self.r.randrange(2)
        size = 1 + w
        kind = self.r.choice(("rm,r", "r,rm", "r,imm", "rm,imm", "moffs"))
        if kind == "rm,r":
            m, rr, t = self.rm_operand(size, write=True)
            reg = self.r.randrange(8)
            if m is None and size == 2 and rr == SP:
                raise Retry("sp")
            data = (m.pfx if m else b"") + self.rnd_pfx() + bytes([0x88 + w]) + self.modrm_bytes(m, rr, reg)
            self.fz(data, f"MOV {t}, {(R8 if w == 0 else R16)[reg]}",
                    self.key("MOV", "rm,r", m.mode if m else "reg", "bw"[w], m.region if m else ""))
            if m:
                self.wrote_mem(m)
            else:
                v = self.st.get8(reg) if size == 1 else self.st.get16(reg)
                if size == 1:
                    self.st.set8(rr, v)
                else:
                    self.st.set16(rr, v)
        elif kind == "r,rm":
            reg = self.r.randrange(8)
            if size == 2 and reg == SP:
                raise Retry("sp")
            if (reg & (3 if size == 1 else 7)) in self.reserved:
                raise Retry("rsv")
            m, rr, t = self.rm_operand(size, write=False, sp_ok=True)
            data = (m.pfx if m else b"") + self.rnd_pfx() + bytes([0x8A + w]) + self.modrm_bytes(m, rr, reg)
            self.fz(data, f"MOV {(R8 if w == 0 else R16)[reg]}, {t}",
                    self.key("MOV", "r,rm", m.mode if m else "reg", "bw"[w], m.region if m else ""))
            v = None
            if m is None:
                v = self.st.get8(rr) if size == 1 else self.st.get16(rr)
            if size == 1:
                self.st.set8(reg, v)
            else:
                self.st.set16(reg, v)
        elif kind == "r,imm":
            reg = self.r.randrange(8)
            if size == 2 and reg == SP:
                raise Retry("sp")
            if (reg & (3 if size == 1 else 7)) in self.reserved:
                raise Retry("rsv")
            imm = self.r.randrange(256 ** size)
            self.fz(bytes([0xB0 + 8 * w + reg]) + imm.to_bytes(size, "little"),
                    f"MOV {(R8 if w == 0 else R16)[reg]}, {hx(imm)}", self.key("MOV", "r,imm", "", "bw"[w], ""))
            if size == 1:
                self.st.set8(reg, imm)
            else:
                self.st.set16(reg, imm)
        elif kind == "rm,imm":
            m, rr, t = self.rm_operand(size, write=True)
            if m is None and size == 2 and rr == SP:
                raise Retry("sp")
            imm = self.r.randrange(256 ** size)
            regf = 0 if self.r.random() < 0.9 else self.r.randrange(1, 8)     # /1-/7 aliases (F2b)
            data = (m.pfx if m else b"") + bytes([0xC6 + w]) + self.modrm_bytes(m, rr, regf) + \
                imm.to_bytes(size, "little")
            self.fz(data, f"MOV {t}, {hx(imm)}", self.key("MOV", f"rm,imm/{regf}" if regf else "rm,imm",
                                                         m.mode if m else "reg", "bw"[w], m.region if m else ""))
            if m:
                self.wrote_mem(m)
            elif size == 1:
                self.st.set8(rr, imm)
            else:
                self.st.set16(rr, imm)
        else:
            store = self.r.randrange(2)
            if not store and AW in self.reserved:
                raise Retry("rsv")
            # the direct form: mod 0 rm 6's addressing, A0-A3
            for _ in range(10):
                m = self.mem(size, write=bool(store))
                if m.mod == 0 and m.rm == 6:
                    break
            else:
                raise Retry("moffs")
            data = m.pfx + bytes([0xA0 + 2 * store + w]) + m.disp
            acc = "AL" if w == 0 else "AW"
            self.fz(data, f"MOV {m.text + ', ' + acc if store else acc + ', ' + m.text}",
                    self.key("MOV", "moffs" + ("st" if store else "ld"), "dir", "bw"[w], m.region))
            if store:
                self.wrote_mem(m)
            elif w:
                self.st.set16(AW, None)
            else:
                self.st.set8(0, None)

    def f_movseg(self):
        kind = self.r.choice(("rm,s", "s,rm", "s,rm"))
        if kind == "rm,s":
            s = self.r.randrange(4)
            m, rr, t = self.rm_operand(2, write=True)
            if m is None and rr == SP:
                raise Retry("sp")
            data = (m.pfx if m else b"") + b"\x8C" + self.modrm_bytes(m, rr, s)
            self.fz(data, f"MOV {t}, {SREG[s]}", self.key("MOV", "rm,sreg", m.mode if m else "reg",
                                                          "w", m.region if m else ""))
            if m:
                self.wrote_mem(m)
            else:
                self.st.set16(rr, self.st.seg[SREG[s]])
            return
        s = self.r.choice((0, 2, 3))
        name = SREG[s]
        if name in self.reserved:
            raise Retry("rsv")
        val = 0 if name == "SS" else self.r.choice(SEG_EXT + SEG_ONCHIP)
        if self.r.random() < 0.5:
            # from a register holding a valid value
            r = self.r.choice([0, 1, 2, 3, 5, 6, 7])
            if r in self.reserved:
                raise Retry("rsv")
            if self.st.get16(r) != val:
                self.mov16(r, val)
            data = b"\x8E" + bytes([0xC0 | s << 3 | r])
            self.fz(data, f"MOV {name}, {R16[r]}", self.key("MOV", "sreg,rm", "reg", "w", name))
        else:
            m = self.mem(2, write=False, onchip=False)
            data = m.pfx + b"\xC7" + m.modrm(0) + m.disp + val.to_bytes(2, "little")
            self.b.emit(data, f"MOV {m.text}, {hx(val)}", "setup")
            self.wrote_mem(m)
            data = m.pfx + b"\x8E" + m.modrm(s) + m.disp
            self.fz(data, f"MOV {name}, {m.text}", self.key("MOV", "sreg,rm", m.mode, "w", m.region + name))
        self.st.seg[name] = val
        self.st.dirty.add(name)

    def f_ldea(self):
        reg = self.r.choice([0, 1, 2, 3, 5, 6, 7])
        if reg in self.reserved:
            raise Retry("rsv")
        m = self.mem(2, write=False)
        # LDEA's result is the offset: known when every address register is
        data = m.pfx + b"\x8D" + m.modrm(reg) + m.disp
        self.fz(data, f"LDEA {R16[reg]}, {m.text}", self.key("LDEA", "r,m", m.mode, "w", ""))
        self.st.set16(reg, (m.lin - 16 * self.st.seg[m.seg]) & 0xFFFF)

    def f_lds(self):
        op = self.r.choice((0xC4, 0xC5))
        sname = "DS1" if op == 0xC4 else "DS0"
        reg = self.r.choice([0, 1, 2, 3, 5, 6, 7])
        if reg in self.reserved or sname in self.reserved:
            raise Retry("rsv")
        m = self.mem(4, write=False, onchip=False)
        seg = None
        if self.r.random() < 0.7:
            seg = self.r.choice(SEG_EXT + SEG_ONCHIP)
            m2 = Mem(m.mod, m.rm, m.disp, m.pfx, m.lin, 4, m.region, m.seg, m.text)
            # the segment word at EA + 2: a store through the same EA with disp + 2 is awkward;
            # write the four bytes by a MOV to the direct address instead
            off = m.lin + 2 - 16 * self.st.seg[m.seg]
            data = bytes([SEGPFX[m.seg], 0xC7, 0x06]) + off.to_bytes(2, "little") + seg.to_bytes(2, "little")
            self.b.emit(data, f"MOV {m.seg}:[{hx(off)}], {hx(seg)}", "setup")
            del m2
        data = m.pfx + bytes([op]) + m.modrm(reg) + m.disp
        self.fz(data, f"MOV {sname}, {R16[reg]}, {m.text}", self.key("LDS" if op == 0xC5 else "LES", "r,m",
                                                                   m.mode, "w", ""))
        self.st.set16(reg, None)
        self.st.seg[sname] = seg
        self.st.dirty.add(sname)

    def f_incdec(self):
        kind = self.r.choice(("r16", "rm8", "rm16"))
        dec = self.r.randrange(2)
        if kind == "r16":
            r = self.r.randrange(8)
            if r in self.reserved:
                raise Retry("rsv")
            if r == SP:
                if self.ctx:
                    raise Retry("sp")
                nsp = self.st.sp + (-1 if dec else 1)
                if not SP_LO + 64 <= nsp <= SP_HI:
                    raise Retry("sp")
            self.fz(bytes([0x40 + 8 * dec + r]), f"{'DEC' if dec else 'INC'} {R16[r]}",
                    self.key("DEC" if dec else "INC", "r16", "", "w", "SP" if r == SP else ""))
            v = self.st.get16(r)
            self.st.set16(r, None if v is None else v + (-1 if dec else 1))
            if r == SP:
                self.st.stack = {}
            return
        w = kind == "rm16"
        size = 1 + w
        m, rr, t = self.rm_operand(size, write=True)
        if m is None and size == 2 and rr == SP:
            raise Retry("sp")
        data = (m.pfx if m else b"") + self.rnd_pfx() + bytes([0xFE + w]) + self.modrm_bytes(m, rr, dec)
        self.fz(data, f"{'DEC' if dec else 'INC'} {t}",
                self.key("DEC" if dec else "INC", "rm", m.mode if m else "reg", "bw"[w], m.region if m else ""))
        if m:
            self.wrote_mem(m)
        else:
            self.reg_write(size, rr)

    def f_grp3(self):
        op = self.r.choice((2, 3, 4, 5, 6, 7, 4, 5, 6, 7))
        w = self.r.randrange(2)
        size = 1 + w
        if op >= 4 and (AW in self.reserved or (w and DW in self.reserved)):
            raise Retry("rsv")
        m, rr, t = self.rm_operand(size, write=op in (2, 3), sp_ok=op >= 4)
        if op in (2, 3) and m is None and size == 2 and rr == SP:
            raise Retry("sp")
        data = (m.pfx if m else b"") + self.rnd_pfx() + bytes([0xF6 + w]) + self.modrm_bytes(m, rr, op)
        self.fz(data, f"{G3[op]} {t}", self.key(G3[op], "rm", m.mode if m else "reg", "bw"[w],
                                               m.region if m else ""))
        if op in (2, 3):
            if m:
                self.wrote_mem(m)
            else:
                self.reg_write(size, rr)
        else:
            self.st.set16(AW, None)
            if w:
                self.st.set16(DW, None)

    def f_mul3(self):
        op = self.r.choice((0x69, 0x6B))
        reg = self.r.choice([0, 1, 2, 3, 5, 6, 7])
        if reg in self.reserved:
            raise Retry("rsv")
        m, rr, t = self.rm_operand(2, write=False, sp_ok=True)
        isz = 2 if op == 0x69 else 1
        imm = self.r.randrange(256 ** isz)
        data = (m.pfx if m else b"") + bytes([op]) + self.modrm_bytes(m, rr, reg) + imm.to_bytes(isz, "little")
        self.fz(data, f"MUL {R16[reg]}, {t}, {hx(imm)}", self.key("MUL3", f"{op:02X}", m.mode if m else "reg",
                                                                 "w", m.region if m else ""))
        self.st.set16(reg, None)

    def f_shift(self):
        op = self.r.choice((0, 1, 2, 3, 4, 5, 7))
        w = self.r.randrange(2)
        size = 1 + w
        how = self.r.choice(("1", "CL", "imm"))
        m, rr, t = self.rm_operand(size, write=True)
        if m is None and size == 2 and rr == SP:
            raise Retry("sp")
        if how == "1":
            opc, imm, tx = 0xD0 + w, b"", "1"
        elif how == "CL":
            opc, imm, tx = 0xD2 + w, b"", "CL"
            if self.r.random() < 0.5 and CW not in self.reserved:
                v = self.r.choice((0, 1, 7, 8, 9, 15, 16, 17, 31, 32, 33, 64, 255,
                                   self.r.randrange(256)))
                self.mov8(1, v)
        else:
            v = self.r.choice((0, 1, 2, 7, 8, 9, 15, 16, 17, 31, 32, 33, 65, 255, self.r.randrange(256)))
            opc, imm, tx = 0xC0 + w, bytes([v]), hx(v, 2)
        data = (m.pfx if m else b"") + self.rnd_pfx() + bytes([opc]) + self.modrm_bytes(m, rr, op) + imm
        self.fz(data, f"{SHF[op]} {t}, {tx}", self.key(SHF[op], how, m.mode if m else "reg", "bw"[w],
                                                      m.region if m else ""))
        if m:
            self.wrote_mem(m)
        else:
            self.reg_write(size, rr)

    def f_misc1(self):
        """One-byte register forms: CVTBW CVTWL, the adjusts, the flag ops, NOP, LAHF."""
        op = self.r.choice((0x98, 0x99, 0x27, 0x2F, 0x37, 0x3F, 0xF5, 0xF8, 0xF9, 0xFC, 0xFD,
                            0x90, 0x9F, 0xFA, 0xFB, 0xD4, 0xD5))
        names = {0x98: "CVTBW", 0x99: "CVTWL", 0x27: "ADJ4A", 0x2F: "ADJ4S", 0x37: "ADJBA",
                 0x3F: "ADJBS", 0xF5: "NOT1 CY", 0xF8: "CLR1 CY", 0xF9: "SET1 CY", 0xFC: "CLR1 DIR",
                 0xFD: "SET1 DIR", 0x90: "NOP", 0x9F: "MOV AH,PSW", 0xFA: "DI", 0xFB: "EI",
                 0xD4: "CVTBD", 0xD5: "CVTDB"}
        wr = {0x98: [AW], 0x99: [DW], 0x27: [AW], 0x2F: [AW], 0x37: [AW], 0x3F: [AW], 0x9F: [AW],
              0xD4: [AW], 0xD5: [AW]}.get(op, [])
        if any(r in self.reserved for r in wr):
            raise Retry("rsv")
        if op in (0xFA, 0xFB) and self.layer == "c" and self.opts.get("keep_ie"):
            raise Retry("ie")
        if op in (0xFC, 0xFD) and "DIR" in self.reserved:
            raise Retry("rsv")
        data = bytes([op])
        if op in (0xD4, 0xD5):
            v = self.r.choice((10, 10, 16, 7, 1, 255, self.r.randrange(1, 256), 0 if op == 0xD5 else 10))
            if op == 0xD4 and self.r.random() < 0.04:
                v = 0
            data += bytes([v])
        if op == 0x99 and self.st.get16(AW) is not None:
            pass
        self.fz(self.rnd_pfx(allow_rep=op not in (0xFA, 0xFB)) + data, names[op],
                self.key(names[op], "", "", "", ""))
        if op == 0x98:
            lo = self.st.get8(0)
            self.st.set8(4, None if lo is None else (0xFF if lo & 0x80 else 0))
        elif op == 0x99:
            a = self.st.get16(AW)
            self.st.set16(DW, None if a is None else (0xFFFF if a & 0x8000 else 0))
        elif op == 0x9F:
            self.st.set8(4, None)
        elif op in (0x27, 0x2F):
            self.st.set8(0, None)
        elif op in (0x37, 0x3F, 0xD4, 0xD5):
            self.st.set16(AW, None)
        elif op == 0xFC:
            self.st.dir = 0
        elif op == 0xFD:
            self.st.dir = 1
        elif op == 0xFA:
            self.st.ie = 0
        elif op == 0xFB:
            self.st.ie = 1

    def f_sahf(self):
        if AW in self.reserved:
            raise Retry("rsv")
        v = (self.r.randrange(256) | 0x02)
        self.mov8(4, v)
        self.fz(b"\x9E", "MOV PSW, AH", self.key("MOV PSW,AH", "", "", "", ""))

    def psw_value(self):
        v = self.r.randrange(0x1000) | 0x0002          # BRKI 1
        v &= ~0x0100                                   # BRK 0
        if self.layer == "c" and self.opts.get("keep_ie"):
            v |= 0x0200
        elif self.r.random() < 0.5:
            v &= ~0x0200
        return v

    def f_pushpop(self):
        kind = self.r.choice(("r", "r", "imm16", "imm8", "sreg", "rm", "pusha", "psw", "poprm",
                              "popsreg", "pushsp"))
        st = self.st
        if kind == "r":
            self.need_room(2, 2)
            r = self.r.choice([0, 1, 2, 3, 5, 6, 7])
            self.fz(bytes([0x50 + r]), f"PUSH {R16[r]}", self.key("PUSH", "r16", "", "w", ""))
            self.push_known(st.get16(r))
            if self.r.random() < 0.6:
                r2 = self.r.choice([0, 1, 2, 3, 5, 6, 7])
                if r2 in self.reserved:
                    raise Retry("rsv")
                self.fz(bytes([0x58 + r2]), f"POP {R16[r2]}", self.key("POP", "r16", "", "w", ""))
                st.set16(r2, self.pop_known())
        elif kind == "pushsp":
            self.need_room(2)
            if self.r.random() < 0.5:
                self.fz(b"\x54", "PUSH SP", self.key("PUSH", "r16", "", "w", "SP"))
                self.push_known((st.sp - 2) & 0xFFFF)
            else:
                self.fz(b"\xFF\xF4", "PUSH SP (FF /6)", self.key("PUSH", "rm", "reg", "w", "SP"))
                self.push_known(st.sp)
        elif kind in ("imm16", "imm8"):
            self.need_room()
            if kind == "imm16":
                v = self.r.randrange(0x10000)
                self.fz(b"\x68" + v.to_bytes(2, "little"), f"PUSH {hx(v)}", self.key("PUSH", "imm16", "", "w", ""))
            else:
                v8 = self.r.randrange(256)
                v = v8 | (0xFF00 if v8 & 0x80 else 0)
                self.fz(bytes([0x6A, v8]), f"PUSH {hx(v8, 2)}", self.key("PUSH", "imm8", "", "w", ""))
            self.push_known(v)
        elif kind == "sreg":
            self.need_room()
            s = self.r.randrange(4)
            self.fz(bytes([0x06 + 8 * s]), f"PUSH {SREG[s]}", self.key("PUSH", "sreg", "", "w", SREG[s]))
            self.push_known(st.seg[SREG[s]])
        elif kind == "popsreg":
            s = self.r.choice((0, 2, 3))
            name = SREG[s]
            if name in self.reserved:
                raise Retry("rsv")
            self.need_room(2, 2)
            val = 0 if name == "SS" else self.r.choice(SEG_EXT + SEG_ONCHIP)
            sp = st.sp
            if st.stack.get(sp) is None or (st.stack.get(sp) | st.stack.get(sp + 1, 0) << 8) != val \
                    or st.stack.get(sp + 1) is None:
                self.setup(b"\x68" + val.to_bytes(2, "little"), f"PUSH {hx(val)}")
                self.push_known(val)
            self.fz(bytes([0x07 + 8 * s]), f"POP {name}", self.key("POP", "sreg", "", "w", name))
            st.seg[name] = self.pop_known()
            st.dirty.add(name)
        elif kind == "rm":
            self.need_room()
            m, rr, t = self.rm_operand(2, write=False, sp_ok=False)
            data = (m.pfx if m else b"") + b"\xFF" + self.modrm_bytes(m, rr, 6)
            self.fz(data, f"PUSH {t}", self.key("PUSH", "rm", m.mode if m else "reg", "w", m.region if m else ""))
            self.push_known(None if m else st.get16(rr))
        elif kind == "poprm":
            self.need_room(2, 2)
            m, rr, t = self.rm_operand(2, write=True)
            if m is None and rr == SP:
                raise Retry("sp")
            regf = 0 if self.r.random() < 0.9 else self.r.randrange(1, 8)
            data = (m.pfx if m else b"") + b"\x8F" + self.modrm_bytes(m, rr, regf)
            self.fz(data, f"POP {t}", self.key("POP", f"rm/{regf}" if regf else "rm", m.mode if m else "reg",
                                               "w", m.region if m else ""))
            v = self.pop_known()
            if m:
                self.wrote_mem(m)
            else:
                st.set16(rr, v)
        elif kind == "pusha":
            self.need_room(16, 16)
            if any(r in self.reserved for r in range(8)):
                raise Retry("rsv")
            sp0 = st.sp
            self.fz(b"\x60", "PUSH R", self.key("PUSH R", "", "", "", ""))
            vals = [st.get16(r) for r in range(8)]
            vals[SP] = sp0
            for v in vals:
                self.push_known(v)
            if self.r.random() < 0.7:
                self.fz(b"\x61", "POP R", self.key("POP R", "", "", "", ""))
                for r in (IY, IX, BP, None, BW, DW, CW, AW):
                    v = self.pop_known()
                    if r is not None:
                        st.set16(r, v)
        else:
            self.need_room(4, 4)
            self.fz(b"\x9C", "PUSH PSW", self.key("PUSH PSW", "", "", "", ""))
            self.push_known(None)
            if self.r.random() < 0.5:
                # POP PSW of the value just pushed (the machine's own PSW)
                self.fz(b"\x9D", "POP PSW", self.key("POP PSW", "pushed", "", "", ""))
                self.pop_known()
            else:
                self.pop_known()
                # drop the pushed word through a POP into memory
                m = self.mem(2, write=True, onchip=False)
                self.b.emit(m.pfx + b"\x8F" + m.modrm(0) + m.disp, f"POP {m.text}", "setup")
                v = self.psw_value()
                self.setup(b"\x68" + v.to_bytes(2, "little"), f"PUSH {hx(v)}")
                self.fz(b"\x9D", "POP PSW", self.key("POP PSW", "imm", "", "", ""))
                st.dir = (v >> 10) & 1
                st.ie = (v >> 9) & 1

    def f_str(self):
        op = self.r.choice((0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF,
                            0x6C, 0x6D, 0x6E, 0x6F))
        names = {0xA4: "MOVBKB", 0xA5: "MOVBKW", 0xA6: "CMPBKB", 0xA7: "CMPBKW", 0xAA: "STMB",
                 0xAB: "STMW", 0xAC: "LDMB", 0xAD: "LDMW", 0xAE: "CMPMB", 0xAF: "CMPMW",
                 0x6C: "INMB", 0x6D: "INMW", 0x6E: "OUTMB", 0x6F: "OUTMW"}
        w = op & 1
        size = 1 + w
        src = op in (0xA4, 0xA5, 0xA6, 0xA7, 0xAC, 0xAD, 0x6E, 0x6F)
        dst = op in (0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB, 0xAE, 0xAF, 0x6C, 0x6D)
        need = {IX, IY, CW, DW} & ({IX} if src else set()) | ({IY} if dst else set())
        rep = self.r.random() < 0.6
        if rep:
            need |= {CW}
        if op in (0x6C, 0x6D, 0x6E, 0x6F):
            need |= {DW}
        if any(r in self.reserved for r in need) or "DIR" in self.reserved:
            raise Retry("rsv")
        st = self.st
        n = self.r.choice((0, 1, 1, 2, 3, 4, 5, 8)) if rep else 1
        if st.dir is None:
            self.setup(b"\xFC" if self.r.random() < 0.6 else b"\xFD", "CLR1/SET1 DIR")
            st.dir = 0 if self.b.code[-1] == 0xFC else 1
        d = -1 if st.dir else 1
        span = max(n, 1) * size
        segpfx = b""
        if src:
            # source DS0:IX (an override allowed)
            lo = DATA_LO + (span if d < 0 else 0)
            hi = DATA_HI - (span if d > 0 else size)
            lin = self.r.randrange(lo, hi)
            sname = "DS0"
            if self.r.random() < 0.25:
                sname = self.r.choice(("DS1", "PS", "SS", "DS0"))
            sv = st.seg[sname]
            if sv is None or not 0 <= lin - 16 * sv <= 0x10000 - span - 2:
                if sname in ("PS", "SS") or sname in self.reserved:
                    sname = "DS0"
                sv = st.seg[sname]
                if sv is None or not 0 <= lin - 16 * sv <= 0x10000 - span - 2:
                    if sname in self.reserved:
                        raise Retry("rsv")
                    self.load_seg(sname, self.rnd_seg_for(lin, span + 2, False))
                    sv = st.seg[sname]
            if sname != "DS0":
                segpfx = bytes([SEGPFX[sname]])
            self.mov16(IX, lin - 16 * sv)
        if dst:
            lo = DATA_LO + (span if d < 0 else 0)
            hi = DATA_HI - (span if d > 0 else size)
            lin = self.r.randrange(lo, hi)
            sv = st.seg["DS1"]
            if sv is None or not 0 <= lin - 16 * sv <= 0x10000 - span - 2:
                if "DS1" in self.reserved:
                    raise Retry("rsv")
                self.load_seg("DS1", self.rnd_seg_for(lin, span + 2, False))
                sv = st.seg["DS1"]
            self.mov16(IY, lin - 16 * sv)
        if op in (0x6C, 0x6D, 0x6E, 0x6F):
            port = self.r.randrange(0x10000)
            while port in HARNESS_PORTS or port + 1 in HARNESS_PORTS:
                port = self.r.randrange(0x10000)
            self.mov16(DW, port)
        if rep:
            self.mov16(CW, n)
        rp = b""
        if rep:
            rp = bytes([self.r.choice((0xF3, 0xF3, 0xF2, 0x65, 0x64))])
        lock = b"\xF0" if self.r.random() < 0.03 else b""
        data = lock + segpfx + rp + bytes([op])
        self.fz(data, f"{['', 'REP? '][rep]}{names[op]}", self.key(names[op], f"rep{rp.hex()}" if rep else "", "",
                                                                  "bw"[w], "seg" if segpfx else ""))
        for r in (IX, IY, CW):
            if r == CW and not rep:
                continue
            if (r == IX and src) or (r == IY and dst) or r == CW:
                st.set16(r, None)
        if op in (0xAC, 0xAD):
            if w:
                st.set16(AW, None)
            else:
                st.set8(0, None)

    def f_trans(self):
        if AW in self.reserved or BW in self.reserved:
            raise Retry("rsv")
        st = self.st
        al = st.get8(0)
        if al is None:
            self.mov8(0, self.r.randrange(256))
            al = st.get8(0)
        lin = self.r.randrange(DATA_LO, DATA_HI)
        sname = "DS0" if self.r.random() < 0.8 else self.r.choice(("DS1", "SS", "PS"))
        sv = st.seg[sname]
        if sv is None or not 0 <= lin - 16 * sv <= 0xFFFF:
            sname = "DS0"
            if "DS0" in self.reserved:
                raise Retry("rsv")
            self.load_seg("DS0", self.rnd_seg_for(lin, 1, False))
            sv = st.seg["DS0"]
        self.mov16(BW, (lin - 16 * sv - al) & 0xFFFF)
        pfx = b"" if sname == "DS0" else bytes([SEGPFX[sname]])
        self.fz(pfx + b"\xD7", "TRANS", self.key("TRANS", "", "", "b", sname))
        st.set8(0, None)

    def io_port(self):
        p = self.r.randrange(0x10000)
        while p in HARNESS_PORTS or p + 1 in HARNESS_PORTS:
            p = self.r.randrange(0x10000)
        return p

    def f_io(self):
        op = self.r.choice((0xE4, 0xE5, 0xE6, 0xE7, 0xEC, 0xED, 0xEE, 0xEF))
        w = op & 1
        inn = op in (0xE4, 0xE5, 0xEC, 0xED)
        if inn and AW in self.reserved:
            raise Retry("rsv")
        if op >= 0xEC:
            if DW in self.reserved:
                raise Retry("rsv")
            self.mov16(DW, self.io_port())
            data = bytes([op])
            t = "DW"
        else:
            data = bytes([op, self.r.randrange(256)])
            t = hx(data[1], 2)
        self.fz(self.rnd_pfx(allow_rep=False) + data, f"{'IN' if inn else 'OUT'} {t}",
                self.key("IN" if inn else "OUT", "DW" if op >= 0xEC else "imm8", "", "bw"[w], ""))
        if inn:
            if w:
                self.st.set16(AW, None)
            else:
                self.st.set8(0, None)

    def f_chkind(self):
        reg = self.r.choice([0, 1, 2, 3, 5, 6, 7])
        m = self.mem(4, write=False, onchip=False)
        if self.r.random() < 0.5:
            # bounds around the register, either side
            pass
        data = m.pfx + b"\x62" + m.modrm(reg) + m.disp
        self.fz(data, f"CHKIND {R16[reg]}, {m.text}", self.key("CHKIND", "r,m", m.mode, "w", ""))

    def f_brk(self):
        kind = self.r.choice(("CC", "CD", "CE", "63"))
        self.need_room(8)
        if kind == "CC":
            data, t = b"\xCC", "BRK 3"
        elif kind == "CE":
            data, t = b"\xCE", "BRKV"
        else:
            v = self.r.randrange(256)
            while v in (2, 7, 0x40, 0x41):     # the FPO handler; the layer c handlers' counts
                v = self.r.randrange(256)
            data, t = bytes([int(kind, 16), v]), f"{'BRK' if kind == 'CD' else 'BRKN'} {hx(v, 2)}"
        self.fz(data, t, self.key(t.split()[0], "", "", "", ""))

    def f_fpo(self):
        self.need_room(8)
        op = self.r.choice(list(range(0xD8, 0xE0)) + [0x66, 0x67])
        pfx = self.rnd_pfx()
        if op in (0x66, 0x67):
            body = bytes([op])
            t = f"FPO2 {op:02X}"
            modt = ""
        else:
            if self.r.random() < 0.5:
                body = bytes([op, 0xC0 | self.r.randrange(64)])
                modt = "reg"
            else:
                m = self.mem(2, write=False, onchip=False)
                body = m.pfx + bytes([op]) + m.modrm(self.r.randrange(8)) + m.disp
                modt = m.mode
            t = f"FPO1 {op:02X}"
        data = pfx + body
        self.setup(bytes([0x36, 0xC6, 0x06]) + FPOLEN.to_bytes(2, "little") + bytes([len(data)]),
                   f"MOV byte SS:[{hx(FPOLEN)}], {len(data)}")
        self.fz(data, t, self.key("FPO", f"{op:02X}" if op in (0x66, 0x67) else "D8-DF", modt, "", ""))

    def f_page(self):
        kind = self.r.choice(("bit", "bit", "bit", "bcd", "rot4", "ins", "ext", "fint"))
        st = self.st
        if kind == "bit":
            op = self.r.choice((0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A,
                                0x1B, 0x1C, 0x1D, 0x1E, 0x1F))
            names = ["TEST1", "TEST1", "CLR1", "CLR1", "SET1", "SET1", "NOT1", "NOT1"]
            nm = names[op & 7]
            w = op & 1
            size = 1 + w
            m, rr, t = self.rm_operand(size, write=nm != "TEST1")
            if m is None and size == 2 and rr == SP and nm != "TEST1":
                raise Retry("sp")
            imm = b""
            if op >= 0x18:
                imm = bytes([self.r.randrange(256) if self.r.random() < 0.3 else
                             self.r.randrange(8 * size)])
            elif self.r.random() < 0.5 and CW not in self.reserved:
                self.mov8(1, self.r.randrange(256))
            data = (m.pfx if m else b"") + bytes([0x0F, op]) + self.modrm_bytes(m, rr, 0) + imm
            self.fz(data, f"{nm} {t}, {'CL' if op < 0x18 else hx(imm[0], 2)}",
                    self.key(nm, "CL" if op < 0x18 else "imm", m.mode if m else "reg", "bw"[w],
                             m.region if m else ""))
            if nm != "TEST1":
                if m:
                    self.wrote_mem(m)
                else:
                    self.reg_write(size, rr)
        elif kind == "bcd":
            op = self.r.choice((0x20, 0x22, 0x26))
            nm = {0x20: "ADD4S", 0x22: "SUB4S", 0x26: "CMP4S"}[op]
            if any(r in self.reserved for r in (CW, IX, IY)):
                raise Retry("rsv")
            n = self.r.choice((1, 2, 3, 4, 5, 7, 8, 16))
            nb = (n + 1) // 2 + 1
            for idx, sname in ((IX, "DS0"), (IY, "DS1")):
                lin = self.r.randrange(DATA_LO, DATA_HI - nb - 2)
                sv = st.seg[sname]
                if sv is None or not 0 <= lin - 16 * sv <= 0xFFFF - nb - 2:
                    self.load_seg(sname, self.rnd_seg_for(lin, nb + 2, False))
                    sv = st.seg[sname]
                self.mov16(idx, lin - 16 * sv)
            self.mov8(1, n)
            self.fz(bytes([0x0F, op]), nm, self.key(nm, "", "", "", ""))
            st.set16(CW, None)
            st.set16(IX, None)
            st.set16(IY, None)
        elif kind == "rot4":
            op = self.r.choice((0x28, 0x2A))
            if AW in self.reserved:
                raise Retry("rsv")
            m, rr, t = self.rm_operand(1, write=True)
            data = (m.pfx if m else b"") + bytes([0x0F, op]) + self.modrm_bytes(m, rr, 0)
            nm = "ROL4" if op == 0x28 else "ROR4"
            self.fz(data, f"{nm} {t}", self.key(nm, "", m.mode if m else "reg", "b", m.region if m else ""))
            st.set8(0, None)
            if m:
                self.wrote_mem(m)
            else:
                st.set8(rr, None)
        elif kind in ("ins", "ext"):
            ins = kind == "ins"
            ptr, sname = (IY, "DS1") if ins else (IX, "DS0")
            if ptr in self.reserved or AW in self.reserved:
                raise Retry("rsv")
            lin = self.r.randrange(DATA_LO, DATA_HI - 6)
            sv = st.seg[sname]
            pfx = b""
            if not ins and self.r.random() < 0.2:
                for s2 in ("DS1", "SS", "PS"):
                    if st.seg[s2] is not None and 0 <= lin - 16 * st.seg[s2] <= 0xFFF0:
                        sname, sv, pfx = s2, st.seg[s2], bytes([SEGPFX[s2]])
                        break
            if sv is None or not 0 <= lin - 16 * sv <= 0xFFF0:
                self.load_seg(sname, self.rnd_seg_for(lin, 6, False))
                sv = st.seg[sname]
            self.mov16(ptr, lin - 16 * sv)
            offr = self.r.randrange(8)
            if (offr & 3) in self.reserved:
                raise Retry("rsv")
            # the book's ranges (0-15 each); silicon stalls on some bytes beyond them (f5x)
            self.mov8(offr, self.r.randrange(16))
            if self.r.random() < 0.5:
                op = 0x31 if ins else 0x33
                wr_ = self.r.randrange(8)
                if (wr_ & 3) in self.reserved:
                    raise Retry("rsv")
                if wr_ != offr:
                    self.mov8(wr_, self.r.randrange(16))
                data = pfx + bytes([0x0F, op, 0xC0 | wr_ << 3 | offr])
                t = f"{'INS' if ins else 'EXT'} {R8[offr]}, {R8[wr_]}"
                form = "r,r"
            else:
                op = 0x39 if ins else 0x3B
                imm = self.r.randrange(16)
                data = pfx + bytes([0x0F, op, 0xC0 | offr, imm])
                t = f"{'INS' if ins else 'EXT'} {R8[offr]}, {imm}"
                form = "r,imm"
            self.fz(data, t, self.key("INS" if ins else "EXT", form, "reg", "", ""))
            st.set16(ptr, None)
            st.set8(offr, None)
            if not ins:
                st.set16(AW, None)
        else:
            self.fz(b"\x0F\x92", "FINT", self.key("FINT", "", "", "", ""))

    # -------------------------------------------------------------- control transfers
    PLAIN = ("f_alu", "f_alu", "f_test", "f_xch", "f_mov", "f_mov", "f_incdec", "f_grp3",
             "f_shift", "f_misc1", "f_mul3", "f_page", "f_ldea", "f_io")

    def inner(self, n, kinds=None):
        for _ in range(n):
            self.one(self.r.choice(kinds or self.PLAIN), tries=8)

    def f_jcc(self):
        """Bcc / BCWZ / BTCLR forward over a short block."""
        kind = self.r.choice(("cc", "cc", "cc", "bcwz", "btclr", "br8", "br16"))
        b = self.b
        end = b.label()
        before = self.st.copy()
        if kind in ("br8", "br16"):
            if kind == "br8":
                i = self.fz(b"\xEB\x00", "BR short", self.key("BR", "short", "", "", ""))
                b.fixup(i, 1, "rel8", end)
            else:
                i = self.fz(b"\xE9\x00\x00", "BR near", self.key("BR", "near", "", "", ""))
                b.fixup(i, 1, "rel16", end)
            junk = bytes(self.r.randrange(256) for _ in range(self.r.randrange(4)))
            if junk:
                b.emit(junk, "junk", "junk")
            b.place(end)
            return
        if kind == "cc":
            c = self.r.randrange(16)
            i = self.fz(bytes([0x70 + c, 0]), f"{CC[c]}", self.key("Bcc", CC[c], "", "", ""))
        elif kind == "bcwz":
            i = self.fz(b"\xE3\x00", "BCWZ", self.key("BCWZ", "", "", "", ""))
        else:
            off = self.r.choice(SFR_BYTE)
            bit = self.r.randrange(8) if self.r.random() < 0.9 else self.r.randrange(256)
            i = self.fz(bytes([0x0F, 0x9C, off, bit, 0]), f"BTCLR {hx(off, 2)}, {bit}",
                        self.key("BTCLR", "", "", "", ""))
            b.fixup(i, 4, "rel8", end)
            i = None
        if i is not None:
            b.fixup(i, 1, "rel8", end)
        self.ctx.append("skip")
        b.maybe += 1
        try:
            self.inner(self.r.randint(0, 3))
        finally:
            b.maybe -= 1
            self.ctx.pop()
        b.place(end)
        self.st.merge(before)

    def f_loop(self):
        st = self.st
        if CW in self.reserved:
            raise Retry("rsv")
        op = self.r.choice((0xE2, 0xE2, 0xE1, 0xE0))
        n = self.r.choice((1, 2, 3, 4))
        self.mov16(CW, n)
        b = self.b
        top = b.label()
        b.place(top)
        before = st.copy()
        saved = set(self.reserved)
        self.reserved |= {CW, BW, BP, IX, IY, "DIR", "DS0", "DS1", "SS"}
        self.ctx.append("loop")
        b.times = n
        start = len(b.ins)
        try:
            self.inner(self.r.randint(1, 3))
        finally:
            self.ctx.pop()
            b.times = 1
            self.reserved = saved
        # a register written in the body and used by a later iteration's address: refuse
        body = b.ins[start:]
        if any(i.tag == "setup" for i in body):
            raise Retry("loop setup")
        nm = {0xE2: "DBNZ", 0xE1: "DBNZE", 0xE0: "DBNZNE"}[op]
        i = self.fz(bytes([op, 0]), nm, self.key(nm, "", "", "", ""))
        b.fixup(i, 1, "rel8", top)
        st.merge(before)
        st.set16(CW, None)

    def f_call(self):
        """CALL to a body placed after a BR, the body ending in RET / RETF."""
        st = self.st
        kind = self.r.choice(("rel", "rel", "reg", "mem", "far", "farmem"))
        far = kind in ("far", "farmem")
        b = self.b
        sub, over = b.label(), b.label()
        self.need_room(12)
        ps0 = st.seg["PS"]
        if ps0 is None:
            raise Retry("ps")
        nps = self.r.choice(PS_CHOICES) if far else ps0
        if kind == "rel":
            i = self.fz(b"\xE8\x00\x00", "CALL near", self.key("CALL", "rel16", "", "", ""))
            b.fixup(i, 1, "rel16", sub)
        elif kind == "reg":
            r = self.r.choice([0, 1, 2, 3, 5, 6, 7])
            if r in self.reserved:
                raise Retry("rsv")
            i = b.emit(bytes([0xB8 + r, 0, 0]), f"MOV {R16[r]}, sub", "setup")
            b.fixup(i, 1, "abs", sub, ps0)
            st.set16(r, None, dirty=False)
            self.fz(bytes([0xFF, 0xD0 | r]), f"CALL {R16[r]}", self.key("CALL", "rm", "reg", "w", ""))
        elif kind == "mem":
            m = self.mem(2, write=False, onchip=False)
            i = b.emit(m.pfx + b"\xC7" + m.modrm(0) + m.disp + b"\0\0", f"MOV {m.text}, sub", "setup")
            b.fixup(i, len(i.data) - 2, "abs", sub, ps0)
            self.wrote_mem(m)
            self.fz(m.pfx + b"\xFF" + m.modrm(2) + m.disp, f"CALL {m.text}",
                    self.key("CALL", "rm", m.mode, "w", m.region))
        elif kind == "far":
            i = self.fz(b"\x9A\0\0" + nps.to_bytes(2, "little"), f"CALL {hx(nps)}:sub",
                        self.key("CALL", "far", "", "", ""))
            b.fixup(i, 1, "abs", sub, nps)
        else:
            m = self.mem(4, write=False, onchip=False)
            off = m.lin - 16 * st.seg[m.seg]
            i = b.emit(bytes([SEGPFX[m.seg], 0xC7, 0x06]) + off.to_bytes(2, "little") + b"\0\0",
                       f"MOV {m.seg}:[{hx(off)}], sub", "setup")
            b.fixup(i, 5, "abs", sub, nps)
            b.emit(bytes([SEGPFX[m.seg], 0xC7, 0x06]) + (off + 2).to_bytes(2, "little") +
                   nps.to_bytes(2, "little"), f"MOV {m.seg}:[{hx(off + 2)}], {hx(nps)}", "setup")
            self.fz(m.pfx + b"\xFF" + m.modrm(3) + m.disp, f"CALL far {m.text}",
                    self.key("CALL", "farmem", m.mode, "", ""))
        sp_call = st.sp
        self.push_known(ps0 if far else None)
        if far:
            self.push_known(None)
        # after the return: BR over the body
        j = b.emit(b"\xE9\0\0", "BR over", "setup")
        b.fixup(j, 1, "rel16", over)
        b.place(sub)
        st.seg["PS"] = nps
        saved = set(self.reserved)
        self.reserved |= {"SPN"}
        self.ctx.append("sub")
        try:
            self.inner(self.r.randint(0, 3))
        finally:
            self.ctx.pop()
            self.reserved = saved
        if st.sp != (sp_call - (4 if far else 2)) & 0xFFFF:
            raise Retry("sub sp")
        extra = 0
        if self.r.random() < 0.3:
            extra = self.r.choice((0, 2, 4, 1))
            if sp_call + extra > SP_HI:
                extra = 0
        if far:
            data = b"\xCB" if not extra and self.r.random() < 0.7 else b"\xCA" + extra.to_bytes(2, "little")
        else:
            data = b"\xC3" if not extra and self.r.random() < 0.7 else b"\xC2" + extra.to_bytes(2, "little")
        self.fz(data, ("RETF" if far else "RET") + (f" {extra}" if len(data) > 1 else ""),
                self.key("RET", ("far" if far else "near") + ("imm" if len(data) > 1 else ""), "", "", ""))
        st.set16(SP, (sp_call + extra) & 0xFFFF, dirty=False)
        st.stack = {a: v for a, v in st.stack.items() if a >= st.sp}
        st.seg["PS"] = ps0
        b.place(over)

    def f_br(self):
        """BR rm / BR far / BR far mem to the next instruction (PS may change)."""
        st = self.st
        b = self.b
        kind = self.r.choice(("reg", "mem", "far", "farmem"))
        ps0 = st.seg["PS"]
        if ps0 is None:
            raise Retry("ps")
        t = b.label()
        nps = self.r.choice(PS_CHOICES) if kind.startswith("far") else ps0
        if self.ctx:
            nps = ps0           # inside a construct PS stays (the body's own PS)
        if kind == "reg":
            r = self.r.choice([0, 1, 2, 3, 5, 6, 7])
            if r in self.reserved:
                raise Retry("rsv")
            i = b.emit(bytes([0xB8 + r, 0, 0]), f"MOV {R16[r]}, target", "setup")
            b.fixup(i, 1, "abs", t, ps0)
            st.set16(r, None, dirty=False)
            self.fz(bytes([0xFF, 0xE0 | r]), f"BR {R16[r]}", self.key("BR", "rm", "reg", "w", ""))
        elif kind == "mem":
            m = self.mem(2, write=False, onchip=False)
            i = b.emit(m.pfx + b"\xC7" + m.modrm(0) + m.disp + b"\0\0", f"MOV {m.text}, target", "setup")
            b.fixup(i, len(i.data) - 2, "abs", t, ps0)
            self.wrote_mem(m)
            self.fz(m.pfx + b"\xFF" + m.modrm(4) + m.disp, f"BR {m.text}", self.key("BR", "rm", m.mode, "w", m.region))
        elif kind == "far":
            i = self.fz(b"\xEA\0\0" + nps.to_bytes(2, "little"), f"BR {hx(nps)}:target",
                        self.key("BR", "far", "", "", ""))
            b.fixup(i, 1, "abs", t, nps)
        else:
            m = self.mem(4, write=False, onchip=False)
            off = m.lin - 16 * st.seg[m.seg]
            i = b.emit(bytes([SEGPFX[m.seg], 0xC7, 0x06]) + off.to_bytes(2, "little") + b"\0\0",
                       f"MOV {m.seg}:[{hx(off)}], target", "setup")
            b.fixup(i, 5, "abs", t, nps)
            b.emit(bytes([SEGPFX[m.seg], 0xC7, 0x06]) + (off + 2).to_bytes(2, "little") +
                   nps.to_bytes(2, "little"), f"MOV {m.seg}:[{hx(off + 2)}], {hx(nps)}", "setup")
            self.fz(m.pfx + b"\xFF" + m.modrm(5) + m.disp, f"BR far {m.text}", self.key("BR", "farmem", m.mode, "", ""))
        if self.r.random() < 0.5:
            b.emit(bytes(self.r.randrange(256) for _ in range(self.r.randint(1, 3))), "junk", "junk")
        b.place(t)
        st.seg["PS"] = nps

    def f_prepare(self):
        st = self.st
        if BP in self.reserved or self.ctx:
            raise Retry("rsv")
        lvl = self.r.choice((0, 1, 1, 2, 3, 4, 7, 33))
        size = self.r.choice((0, 2, 4, 6, 1, 8))
        eff = lvl & 31
        need = 2 * (eff + 1) + size + 8
        self.need_room(need + 40, 0)
        if st.get16(BP) is None or not SP_LO + 2 * eff + 4 <= st.get16(BP) <= SP_HI:
            self.mov16(BP, self.r.randrange(SP_LO + 2 * eff + 8, SP_HI) & ~1)
        sp0 = st.sp
        self.fz(b"\xC8" + size.to_bytes(2, "little") + bytes([lvl]), f"PREPARE {size}, {lvl}",
                self.key("PREPARE", f"lvl{min(eff, 3)}", "", "", ""))
        frame = sp0 - 2
        old_bp = st.get16(BP)
        st.stack = {}
        st.set16(BP, frame)
        st.set16(SP, frame - (2 * eff if eff else 0) - size)
        if self.r.random() < 0.6:
            self.fz(b"\xC9", "DISPOSE", self.key("DISPOSE", "", "", "", ""))
            st.set16(SP, frame + 2)
            st.set16(BP, old_bp)

    def f_retiw(self):
        """RETI one-way: PUSH the PSW, PS and the next PC, RETI."""
        st = self.st
        b = self.b
        self.need_room(8)
        ps0 = st.seg["PS"]
        v = self.psw_value() | (st.rb << 12) | 0x8000
        self.setup(b"\x68" + v.to_bytes(2, "little"), f"PUSH {hx(v)}")
        self.setup(b"\x0E", "PUSH PS")
        t = b.label()
        i = b.emit(b"\x68\0\0", "PUSH target", "setup")
        b.fixup(i, 1, "abs", t, ps0)
        self.fz(b"\xCF", "RETI", self.key("RETI", "", "", "", ""))
        b.place(t)
        st.dir = (v >> 10) & 1
        st.ie = (v >> 9) & 1

    # -------------------------------------------------------------- items
    def one(self, name, tries=6):
        """Materialize one form, retrying the random choices if a constraint refuses."""
        for _ in range(tries):
            snap = (self.st.copy(), len(self.b.ins), len(self.b.code), self.b.pc, len(self.b.fix),
                    dict(self.b.labels), dict(self.cov), self.fuzz_since)
            try:
                getattr(self, name)()
                return True
            except Retry:
                st, n, c, pc, nf, lab, cov, fs = snap
                # in place: an enclosing construct holds a reference to this object
                self.st.__dict__.update(st.__dict__)
                del self.b.ins[n:]
                del self.b.code[c:]
                self.b.pc = pc
                del self.b.fix[nf:]
                self.b.labels = lab
                self.cov = cov
                self.fuzz_since = fs
        return False

    def observe(self, full=False):
        st = self.st
        sp = st.sp
        regs = [r for r in (AW, CW, DW, BW, BP, IX, IY) if R16[r] in st.dirty]
        segs = [s for s in ("DS1", "DS0") if s in st.dirty]
        if full:
            self.b.emit(b"\x9C\x60\x1E\x06", "OBS PUSH PSW, R, DS0, DS1", "obs")
        else:
            data = b"\x9C" + bytes(0x50 + r for r in regs) + bytes({"DS1": 0x06, "DS0": 0x1E}[s] for s in segs)
            self.b.emit(data, "OBS PUSH PSW " + " ".join([R16[r] for r in regs] + segs), "obs")
        self.b.emit(b"\xBC" + sp.to_bytes(2, "little"), f"OBS MOV SP, {hx(sp)}", "obs")
        st.dirty = set()
        self.fuzz_since = 0
        self.obs_n += 1


# ------------------------------------------------------------------ item kinds by layer
WEIGHTS = {
    "f_alu": 18, "f_test": 3, "f_xch": 3, "f_mov": 12, "f_movseg": 3, "f_ldea": 2, "f_lds": 2,
    "f_incdec": 5, "f_grp3": 8, "f_mul3": 2, "f_shift": 8, "f_misc1": 7, "f_sahf": 1,
    "f_pushpop": 7, "f_str": 6, "f_trans": 1, "f_io": 2, "f_chkind": 1, "f_brk": 2, "f_fpo": 1,
    "f_page": 6, "f_jcc": 5, "f_loop": 2, "f_call": 3, "f_br": 2, "f_prepare": 1, "f_retiw": 1,
}


def draw_items(seed, n, weights=None):
    r = random.Random(seed)
    w = weights or WEIGHTS
    names = list(w)
    ws = [w[k] for k in names]
    return [(r.choices(names, ws)[0], r.randrange(1 << 30)) for _ in range(n)]


# ------------------------------------------------------------------ the program frame
def stub_bytes():
    out = bytearray()
    for v in range(256):
        a = STUBS + 6 * v
        if v == 7:
            rel = (FPOH - (a + 3)) & 0xFFFF
            out += b"\xE9" + rel.to_bytes(2, "little") + b"\x90\x90\x90"
        else:
            out += b"\x36\xFE\x06" + (CNT + v).to_bytes(2, "little") + b"\xCF"
    return bytes(out)


# INC byte SS:[7E07]; PUSH BP; MOV BP,SP; PUSH AW; MOV AL,SS:[7F00]; MOV AH,0; ADD [BP+2],AW;
# POP AW; POP BP; RETI
FPO_HANDLER = bytes.fromhex("36FE06077E" "55" "8BEC" "50" "36A0007F" "B400" "014602" "58" "5D" "CF")


def low_page():
    img = bytearray(0x1000)
    for v in range(256):
        img[4 * v:4 * v + 4] = (STUBS + 6 * v).to_bytes(2, "little") + b"\0\0"
    img[STUBS:STUBS + 0x600] = stub_bytes()
    img[FPOH:FPOH + len(FPO_HANDLER)] = FPO_HANDLER
    return bytes(img)


@dataclass
class Built:
    name: str
    layer: str
    seed: int
    items: list
    code: bytes
    ins: list
    segments: dict
    pages: list
    results: list
    cov: dict
    rb_end: int
    mask: set            # result-region addresses the gate ignores
    stim: dict | None = None
    levels: int = 0x1E1F
    note: str = ""
    gate: bool = True
    limit: int = 6_000_000
    meta: dict = field(default_factory=dict)

    # the onchip.Program interface (run_one)
    def image(self):
        return self.code, self.segments, self.pages

    @property
    def source(self):
        return listing(self.ins)


def listing(ins):
    out = []
    for i in ins:
        mark = {"fuzz": " ", "setup": "s", "obs": "o", "frame": "f", "junk": "j"}[i.tag]
        if i.maybe:
            mark += "?"
        out.append(f"{i.addr:05X} {mark:2s} {i.data.hex(' '):30s} {i.text}")
    return "\n".join(out) + "\n"


def bank_table(r):
    """Banks 0-6 at the start: random bytes, SS 0, PS 0, SP in the stack window."""
    t = bytearray(r.randrange(256) for _ in range(0xE0))
    for b in range(7):
        base = 0x20 * b
        t[base + 0x0A:base + 0x0E] = bytes(4)
        sp = r.randrange(0x6400, 0x6F00) & ~1
        t[base + 0x16:base + 0x18] = sp.to_bytes(2, "little")
        for o in (0x08, 0x0E):
            t[base + o:base + o + 2] = r.choice(SEG_EXT).to_bytes(2, "little")
    return bytes(t)


def prologue(g, r, table):
    st = g.st
    sp0 = r.randrange(0x6400, 0x6F00) & ~1 if r.random() < 0.8 else r.randrange(0x6400, 0x6F00)
    g.setup(b"\xB8\0\0", "MOV AW, 0")
    g.setup(b"\x8E\xD0", "MOV SS, AW")
    g.setup(b"\xBC" + sp0.to_bytes(2, "little"), f"MOV SP, {hx(sp0)}")
    g.setup(b"\xB8" + (INIT_TBL >> 4).to_bytes(2, "little"), "MOV AW, 0700h")
    g.setup(b"\x8E\xD8", "MOV DS0, AW")
    g.setup(b"\xBE\0\0", "MOV IX, 0")
    g.setup(b"\xB8\xE0\xFF", "MOV AW, 0FFE0h")
    g.setup(b"\x8E\xC0", "MOV DS1, AW")
    g.setup(b"\xBF\0\0", "MOV IY, 0")
    g.setup(b"\xB9\x70\x00", "MOV CW, 70h")
    g.setup(b"\xFC\xF3\xA5", "CLR1 DIR; REP MOVBKW (banks 0-6)")
    for o in (0x00, 0x02, 0x04, 0x06):
        v = r.randrange(0x10000)
        g.setup(b"\x26\xC7\x06" + (0xE0 + o).to_bytes(2, "little") + v.to_bytes(2, "little"),
                f"MOV DS1:[{hx(0xE0 + o)}], {hx(v)}")
    st.set16(SP, sp0, dirty=False)
    for bb in range(7):
        st.banks[bb] = {o: table[0x20 * bb + o] for o in range(0x20)}
    for rr in (AW, CW, DW, BW, BP, IX, IY):
        g.mov16(rr, r.randrange(0x10000))
    for s in ("DS0", "DS1"):
        g.load_seg(s, r.choice(SEG_EXT))
    v = g.psw_value()
    g.setup(b"\x68" + v.to_bytes(2, "little"), f"PUSH {hx(v)}")
    g.setup(b"\x9D", "POP PSW")
    st.dir = (v >> 10) & 1
    st.ie = (v >> 9) & 1
    st.stack = {}
    g.observe(full=True)


def epilogue(g, sfr_bytes=DUMP_SFR_PLAIN, sfr_words=DUMP_SFR_WORD):
    g.observe(full=True)

    def e(d, t):
        g.b.emit(d, t, "obs")
    e(b"\xB8\xE0\xFF\x8E\xD8\xBE\0\0", "MOV AW,0FFE0h; MOV DS0,AW; MOV IX,0")
    e(b"\xB8" + (DUMP >> 4).to_bytes(2, "little") + b"\x8E\xC0\xBF\0\0", "MOV AW,0C00h; MOV DS1,AW; MOV IY,0")
    e(b"\xB9\x80\x00\xFC\xF3\xA5", "MOV CW,80h; CLR1 DIR; REP MOVBKW (the banks)")
    for o in sfr_bytes:
        # TBIC's IF (bit 7) is the time base's, live since reset: masked by AND
        e(b"\xA0" + (0x100 + o).to_bytes(2, "little") + (b"\x24\x7F" if o == 0xEC else b"")
          + b"\x36\xA2" + (DUMP + 0x100 + o).to_bytes(2, "little"), f"SFR {o:02X}h by byte")
    for o in sfr_words:
        e(b"\xA1" + (0x100 + o).to_bytes(2, "little") + b"\x36\xA3" + (DUMP + 0x100 + o).to_bytes(2, "little"),
          f"SFR {o:02X}h by word")
    e(b"\xBA\x00\xFF\xEE\xF4\xEB\xFE", "MOV DW,0FF00h; OUT DW,AL; HALT; BR $")


def build(name, layer, seed, items, opts=None, body=None):
    """Materialize `items` into a program (the prologue and K drawn from `seed`)."""
    opts = dict(opts or {})
    r = random.Random(seed)
    table = bank_table(r)
    g = Gen(layer, opts)
    g.r = random.Random(r.randrange(1 << 30))
    K = opts.get("K") or r.choice((1, 2, 2, 3, 3, 4))
    prologue(g, g.r, table)
    if body:
        body(g, items, K)
    else:
        for kind, s in items:
            g.r = random.Random(s)
            g.one(kind)
            if g.fuzz_since >= K:
                g.observe(full=g.obs_n % 4 == 3)
    sfr_b, sfr_w = opts.get("dump_sfr", (DUMP_SFR_PLAIN, DUMP_SFR_WORD))
    epilogue(g, sfr_b, sfr_w)
    code = g.b.resolve()
    if CODE + len(code) > CODE_END:
        raise ValueError(f"{name}: code too long ({len(code)} bytes)")
    pr = random.Random(seed ^ 0x5A5A)
    end = (CODE + len(code) + 0xFFF) & ~0xFFF
    segs = {
        0x00000: low_page(),
        CODE: code + b"\xF4" * (end - CODE - len(code)),
        DATA_LO: bytes(pr.randrange(256) for _ in range(DATA_HI - DATA_LO)),
        STK_PAGE: bytes(pr.randrange(256) for _ in range(0x1000)),
        INIT_TBL: table + bytes(pr.randrange(256) for _ in range(CNT - INIT_TBL - len(table)))
        + bytes(0x200),
        DUMP: bytes(0x1000),
        0xFFFF0: bytes([0xEA, CODE & 0xFF, CODE >> 8, 0x00, 0x00]),
    }
    pages = sorted({a >> 12 for a in segs if a != 0xFFFF0} | set(range(CODE >> 12, end >> 12)) | {0xFF})
    results = [(DATA_LO, DATA_HI - DATA_LO), (STK_PAGE, 0x1000), (CNT, 0x100), (DUMP, 0x200)]
    mask = {DUMP + 0x20 * g.st.rb + 0x1C, DUMP + 0x20 * g.st.rb + 0x1D}
    return Built(name, layer, seed, list(items), code, g.b.ins, segs, pages, results, g.cov,
                 g.st.rb, mask, meta={"K": K, "fuzz": sum(1 for i in g.b.ins if i.tag == "fuzz")})
