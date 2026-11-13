"""(D2) The functional reference: the chain's instructions executed with real data.

The frozen model (sim/frozen/) fixes when every step happens; its register effects
(templates.execute) are the timing abstraction: every memory read returns the data fill, Z is
set by CMP r16,r16 alone, the segment registers are never written. This module executes the
same instruction stream with nuV30's semantics (build/deps/nuV30/docs/facts/instructions.json,
undefined_flags.md: the flags silicon writes where the manual says undefined) and the V35's
programmer's model (docs/v35s-differences.md: the PSW's bit layout, MD/RB/BRKI/F0/F1 untouched
by the ALU), against a real memory: the image (the prelude and the chain at 10000h, the vector
table's zeros below 400h, the 90h data fill at 800h-0FFFh, the prelude's PUSH 0002h at 0EFEh;
any other byte reads 90h, the benches' default) written by the chain's own stores, and an I/O
space whose reads return IO_WORD (0000h: what the board's ports answer, silicon's traces).

What it gives (chain_run): every instruction start in program order (a segment prefix is a
start of its own, as in the model) with the register file before it and the quantities the
timing depends on (the memory operand's linear address, the port, the stack read / write
offsets, the shift count, a transfer's decision and target, a string form's element count),
and every data bus cycle in order with its datum (a write's, on the bus lanes as silicon drives
them: an odd byte on D15-8 with D7-0 zero, an odd word as two byte cycles, the low byte on the
first's high lane) and, for a read, the word the bus delivers (the aligned memory word, the I/O
word). `agree` walks the frozen model's own decode/execute in lockstep and asserts that every
quantity the timing depends on is the frozen model's: where they differ, the frozen model's
timing was computed from a value silicon does not have (a finding). The RTL's benches compare
its register file, PSW and data against this module (rtl_vectors.py, D2).

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.funcref --family F0 F14 ... [--silicon]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from .types import CODE_BASE, CODE_SEGMENT

REG16 = ("AW", "CW", "DW", "BW", "SP", "BP", "IX", "IY")
REG8 = (("AW", 0), ("CW", 0), ("DW", 0), ("BW", 0), ("AW", 8), ("CW", 8), ("DW", 8), ("BW", 8))
SREG = ("DS1", "PS", "SS", "DS0")             # the sreg field: 00 DS1, 01 PS, 10 SS, 11 DS0
PREFIX_SREG = {0x26: 0, 0x2E: 1, 0x36: 2, 0x3E: 3}
REP_PREFIXES = (0xF2, 0xF3, 0x64, 0x65)      # (WP77) 64 REPNC, 65 REPC (templates.REP_PREFIXES)
CY_PREFIXES = (0x64, 0x65)                  # (WP77) ... the compare's exit from the carry
# (WP79, F33) the flag forms: (PSW bit, clr | set | not)
ONE_FLAG = {0xF8: (0, "clr"), 0xF9: (0, "set"), 0xF5: (0, "not"), 0xFA: (9, "clr"),
            0xFB: (9, "set"), 0xFC: (10, "clr"), 0xFD: (10, "set")}
SFR_PAGE = 0xFFF00
IO_WORD = 0x0000                    # the board's I/O reads (silicon: IN from 40h reads 0000h)
PSW_INIT = 0xF002                   # reset F002 (MD 1, RB 7, BRKI 1); POP PSW 0002h keeps 15-12
PRELUDE_STACK = 0x0EFE              # the prelude's PUSH 0002h / POP PSW word (image.PSW)

# PSW bits (the V35 layout)
CY, BRKI, P, F0, AC, F1, Z, S, BRK, IE, DIR, V = 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11
ARITH = (1 << CY) | (1 << P) | (1 << AC) | (1 << Z) | (1 << S) | (1 << V)


class NotModelled(RuntimeError):
    """A form the functional reference does not execute (or the RTL does not build)."""


class Trap(RuntimeError):
    """A divide error: the trap condition (the trap sequence itself is a later item)."""


# ---------------------------------------------------------------------------------- the ALU

def _bits(w: int) -> int:
    return 8 * w


def _mask(w: int) -> int:
    return (1 << _bits(w)) - 1


def _msb(w: int) -> int:
    return 1 << (_bits(w) - 1)


def parity(v: int) -> int:
    return int(bin(v & 0xFF).count("1") % 2 == 0)


def _put(psw: int, bit: int, v) -> int:
    return (psw | (1 << bit)) if v else (psw & ~(1 << bit))


def _szp(psw: int, r: int, w: int) -> int:
    psw = _put(psw, S, r & _msb(w))
    psw = _put(psw, Z, (r & _mask(w)) == 0)
    return _put(psw, P, parity(r))


def flag(psw: int, bit: int) -> int:
    return (psw >> bit) & 1


# (F5) the V20 suite's undefined flags: the rules this reference had before F5 measured the V35
# (receipts f5-f5x-*): logic ops / shifts / TEST1 / CVTBD clearing AC, MUL's flags of the low
# half added to itself, DIV's unsigned pre-check flags, EXT / INS's subtract, CVTDB by ten, INS
# stepping the offset register before AW is read. sst.py sets it for the V20 class V20_UNDEF.
V20_UNDEF = False


def alu(op: int, a: int, b: int, w: int, psw: int) -> tuple[int, int]:
    """The 8 ALU operations of the 00-3F block and the 80-83 group (bits 5:3 / reg field):
    ADD OR ADC SBB AND SUB XOR CMP. (result, psw); CMP's result is the difference."""
    m, msb = _mask(w), _msb(w)
    a, b = a & m, b & m
    if op in (0, 2):                                    # ADD, ADC
        r = a + b + (flag(psw, CY) if op == 2 else 0)
        psw = _put(psw, CY, r > m)
        psw = _put(psw, V, (a ^ r) & (b ^ r) & msb)
        psw = _put(psw, AC, (a ^ b ^ r) & 0x10)
    elif op in (3, 5, 7):                               # SBB, SUB, CMP
        r = a - b - (flag(psw, CY) if op == 3 else 0)
        psw = _put(psw, CY, r < 0)
        psw = _put(psw, V, (a ^ b) & (a ^ r) & msb)
        psw = _put(psw, AC, (a ^ b ^ r) & 0x10)
    else:                                               # OR, AND, XOR: CY V cleared, AC kept
        r = a | b if op == 1 else a & b if op == 4 else a ^ b   # (F5: silicon, receipts f5-f5x-*)
        psw &= ~((1 << CY) | (1 << V) | ((1 << AC) if V20_UNDEF else 0))
    r &= m
    return r, _szp(psw, r, w)


def incdec(dec: bool, a: int, w: int, psw: int) -> tuple[int, int]:
    """INC / DEC: ADD / SUB 1 with CY unchanged."""
    cy = flag(psw, CY)
    r, psw = alu(5 if dec else 0, a, 1, w, psw)
    return r, _put(psw, CY, cy)


def neg(a: int, w: int, psw: int) -> tuple[int, int]:
    return alu(5, 0, a, w, psw)                         # CY: the operand was not 0


def shift(op: int, a: int, n: int, w: int, psw: int) -> tuple[int, int]:
    """The shift group (D0-D3, C0/C1; reg field): ROL ROR ROLC RORC SHL SHR (6: SHL's
    undocumented alias) SHRA, by n (the full count, no masking: shift_count_mask=cl8), one
    bit at a time. A count of 0 changes nothing. CY is the last bit out; V by the final state
    (undefined_flags.md, the shift-V law): left ops MSB(result) ^ CY, right ops the result's
    two top bits; the shifts set S Z P and clear AC, the rotates leave them."""
    if n == 0:
        return a, psw
    m, msb, nb = _mask(w), _msb(w), _bits(w)
    a &= m
    cy = flag(psw, CY)
    for _ in range(n):
        if op == 0:                                     # ROL
            cy = int(bool(a & msb))
            a = ((a << 1) | cy) & m
        elif op == 1:                                   # ROR
            cy = a & 1
            a = (a >> 1) | (cy << (nb - 1))
        elif op == 2:                                   # ROLC
            c = int(bool(a & msb))
            a = ((a << 1) | cy) & m
            cy = c
        elif op == 3:                                   # RORC
            c = a & 1
            a = (a >> 1) | (cy << (nb - 1))
            cy = c
        elif op in (4, 6):                              # SHL
            cy = int(bool(a & msb))
            a = (a << 1) & m
        elif op == 5:                                   # SHR
            cy = a & 1
            a >>= 1
        else:                                           # SHRA
            cy = a & 1
            a = (a >> 1) | (a & msb)
    psw = _put(psw, CY, cy)
    if op in (0, 2, 4, 6):
        psw = _put(psw, V, bool(a & msb) != bool(cy))
    else:
        psw = _put(psw, V, bool(a & msb) != bool(a & (msb >> 1)))
    if op >= 4:
        psw = _szp(psw, a, w) & ~((1 << AC) if V20_UNDEF else 0)    # AC kept (F5: silicon)
    return a, psw


def _sx(v: int, w: int) -> int:
    v &= _mask(w)
    return v - (1 << _bits(w)) if v & _msb(w) else v


def mul(signed: bool, a: int, b: int, w: int, psw: int) -> tuple[int, int]:
    """MULU / MUL: the double-width product. CY = V = the high half is not the extension of
    the low half (zero / sign). MULU leaves S Z AC P. MUL multiplies the magnitudes (S Z AC P
    left) and, when the signs differ, negates the product: S Z AC P are the flags of the low
    half's negation, 0 - the magnitude's low half (F5: silicon, f5x, 1,308 cases)."""
    nb = _bits(w)
    if signed:
        p = (_sx(a, w) * _sx(b, w)) & ((1 << (2 * nb)) - 1)
        lo = p & _mask(w)
        ext = (p >> nb) != (_mask(w) if lo & _msb(w) else 0)
        if V20_UNDEF:
            _, f = alu(0, lo, lo, w, psw)
            psw = (psw & ~((1 << S) | (1 << Z) | (1 << AC) | (1 << P))) | (
                f & ((1 << S) | (1 << Z) | (1 << AC) | (1 << P)))
        elif (_sx(a, w) < 0) != (_sx(b, w) < 0):
            mag = abs(_sx(a, w) * _sx(b, w)) & _mask(w)
            _, f = alu(5, 0, mag, w, psw)
            psw = (psw & ~((1 << S) | (1 << Z) | (1 << AC) | (1 << P))) | (
                f & ((1 << S) | (1 << Z) | (1 << AC) | (1 << P)))
    else:
        p = (a & _mask(w)) * (b & _mask(w))
        ext = (p >> nb) != 0
    psw = _put(_put(psw, CY, ext), V, ext)
    return p, psw


def div(signed: bool, num: int, d: int, w: int, psw: int) -> tuple[int, int, int, bool]:
    """DIVU / DIV of the double-width num by d: (quotient, remainder, psw, trap).
    DIVU: the flags of the overflow pre-check SUB(num_high, d), all six; it traps when that
    compare does not borrow (d = 0 included). DIV: the magnitudes' pre-check SUB(|num|_high,
    |d|) traps and leaves its flags; else the unsigned quotient's S Z P with CY AC V cleared,
    a quotient out of range (symmetric: -2^(n-1) traps too) trapping with those; quotient and
    remainder truncate toward zero, the remainder takes the dividend's sign
    (undefined_flags.md, Campaign 3). (F5: silicon, f5x) a divide that completes leaves S Z P
    of the remainder's magnitude, AC the pre-check's nibble borrow (|num|_high's low digit <
    |d|'s), CY and V cleared, for DIVU and DIV alike, and so does a signed quotient out of
    range (F5b) before it traps; the pre-check's trap keeps its SUB's flags."""
    nb, m = _bits(w), _mask(w)
    d &= m
    if not signed:
        hi = num >> nb
        _, psw = alu(5, hi, d, w, psw)
        if hi >= d:
            return 0, 0, psw, True
        if not V20_UNDEF:
            psw = _done(psw, hi, d, num % d, w)
        return num // d, num % d, psw, False
    sn = num - (1 << (2 * nb)) if num & (1 << (2 * nb - 1)) else num
    sd = _sx(d, w)
    an, ad = abs(sn), abs(sd)
    hi = (an >> nb) & m
    if ad == 0 or hi >= ad:
        _, psw = alu(5, hi, ad, w, psw)
        return 0, 0, psw, True
    q, r = an // ad, an % ad
    if V20_UNDEF:
        psw &= ~((1 << CY) | (1 << AC) | (1 << V))
        psw = _szp(psw, q, w)
        if q > (1 << (nb - 1)) - 1:
            return 0, 0, psw, True
    elif q > (1 << (nb - 1)) - 1:
        # (F5b: silicon, f5x divovf, 83 cases) out of range after the steps: the completing
        # divide's flags
        return 0, 0, _done(psw, hi, ad, r, w), True
    if (sn < 0) != (sd < 0):
        q = -q
    if not V20_UNDEF:
        psw = _done(psw, hi, ad, r, w)
    if sn < 0:
        r = -r
    return q & m, r & m, psw, False


def _done(psw: int, hi: int, d: int, rem: int, w: int) -> int:
    """(F5) the flags of a divide that completes: S Z P of |rem|, AC the pre-check's nibble
    borrow, CY V cleared."""
    psw = _szp(psw & ~((1 << CY) | (1 << V)), rem, w)
    return _put(psw, AC, (hi & 0xF) < (d & 0xF))


def bcd_add8(a: int, b: int, cin: int) -> tuple[int, int, int]:
    """(WP79, F32) ADD4S's byte step, a = the destination byte, b = the source byte: (carry,
    the byte's zero term for Z, the byte written). nuV30's law (docs/facts/undefined_flags.md,
    the 0F20 tranche; sw/oracle_4s_predicate.py bcd_add8): a nibble-serial adder whose high
    digit's adjust decision sees one carry rail (two carries landing on a 9 leave the digit Ah
    unadjusted); the carry out is that decision (the V20 suite: 2,000 of 2,000 tests, where the
    oracle's binary byte carry fails 1,930); Z accumulates over the V30 stage (the 9-bit raw
    sum zero), which the V20 suite cannot tell from the V20's pre-adjust stage."""
    lo = (a & 0xF) + (b & 0xF) + cin
    c1 = (lo >> 4) & 1
    dlo0 = lo & 0xF
    c2 = int(dlo0 > 9)
    dlo = (dlo0 + 6) & 0xF if (c1 or c2) else dlo0
    hi = ((a >> 4) & 0xF) + ((b >> 4) & 0xF) + c1 + c2
    dhi0 = hi & 0xF
    fire = int(((a >> 4) & 0xF) + ((b >> 4) & 0xF) + (c1 | c2) > 9)
    dhi = (dhi0 + 6) & 0xF if fire else dhi0
    return fire, int(a + b + cin == 0), ((dhi << 4) | dlo) & 0xFF


def bcd_sub8(a: int, b: int, bin_: int) -> tuple[int, int, int]:
    """(WP79, F32) SUB4S / CMP4S's byte step (a - b - borrow): (borrow, the zero term, the
    byte). nuV30's law (sw/oracle_4s_predicate.py bcd_sub8; Z the V30 stage: {dec, dlo} = 0);
    the borrow out is the high digit's adjust decision, as ADD4S's carry (the V20 suite)."""
    lo = ((a & 0xF) - (b & 0xF) - bin_) & 0x1F
    c1 = (lo >> 4) & 1
    dlo0 = lo & 0xF
    c2 = int(dlo0 > 9)
    fl = c1 or c2
    dlo = (dlo0 - 6) & 0xF if fl else dlo0
    wrapb = int(bool(fl) and dlo0 < 6)
    hi = (((a >> 4) & 0xF) - ((b >> 4) & 0xF) - c1 - wrapb) & 0x1F
    dhi0 = hi & 0xF
    dec = (((a >> 4) & 0xF) - ((b >> 4) & 0xF) - c1) & 0x1F
    fire = int(bool((dec >> 4) & 1) or dec > 9 or ((dec & 0xF) == 9 and c2 and not c1))
    dhi = (dhi0 - 6) & 0xF if fire else dhi0
    return fire, int((dec & 0xF) == 0 and dlo == 0), ((dhi << 4) | dlo) & 0xFF


def cond(cc: int, psw: int) -> bool:
    """Bcond's 16 conditions (the 70-7F row's low nibble)."""
    f = lambda b: bool(flag(psw, b))
    t = (f(V), f(CY), f(Z), f(CY) or f(Z), f(S), f(P), f(S) != f(V),
         (f(S) != f(V)) or f(Z))[cc >> 1]
    return t != bool(cc & 1)


# ---------------------------------------------------------------------------------- a cycle

@dataclass
class Cycle:
    kind: str                   # read | write | io_read | io_write
    addr: int                   # linear address or port
    width: str                  # word | lo | hi (the bus lanes)
    data: int = 0               # the datum the EU drives (a write's, lane-placed; 0 on a read)
    rdata: int = 0              # a read: the word the bus delivers (the aligned memory word)
    req: int = 0                # the request (one EU data step) within the instruction
    last: bool = True           # the request's last cycle
    w2: bool = False            # the request is a word


@dataclass
class Start:
    """One instruction start (a prefix is one)."""
    ip: int                     # its offset in PS
    pc: int                     # its code offset (ip - code_org)
    code: bytes                 # the instruction's bytes (6, NOPs past its end)
    length: int
    regs: dict                  # the register file before it (REG16, SREG, PSW, pfx)
    ea: int = 0                 # the memory operand's linear address (0: none)
    port: int = 0
    sr: int = 0                 # the stack read's offset (SP; DISPOSE: BP)
    sw: int = 0                 # the stack write's offset (SP - 2)
    count: int = 0              # the shift count (the full byte)
    taken: bool = False
    target: int = 0             # a taken transfer's code offset
    halt: bool = False
    cycles: list = field(default_factory=list)
    trap: bool = False
    string: tuple | None = None   # a string form: (rep, ix, iy, port, elements, cond)


# ---------------------------------------------------------------------------------- the CPU

class Cpu:
    """The programmer's model and the memory. `pfx`: the segment prefix the next instruction
    carries (the sreg index, None without)."""

    v20_digits = False              # (WP79) ROL4 / ROR4's AL as the V20 leaves it (sst.py)
    v20_flags = False               # (S6) POP PSW / RETI / SAHF's fixed bits as the V20's (sst.py)

    def __init__(self, regs: dict, mem: bytearray, io_word: int = IO_WORD, code_org: int = 0):
        self.r = {n: regs.get(n, 0) & 0xFFFF for n in REG16 + SREG}
        self.psw = regs.get("PSW", PSW_INIT) & 0xFFFF
        self.pfx = None
        self.cur = None             # the prefix the running instruction carries
        self.discard = False        # the read running is discarded (POP R's SP word)
        self.mem = mem
        self.io_word = io_word
        self.code_org = code_org
        self.cyc: list[Cycle] = []
        self.nreq = 0

    def snapshot(self) -> dict:
        d = dict(self.r)
        d["PSW"] = self.psw
        d["pfx"] = self.pfx
        return d

    # registers
    def r8(self, k: int) -> int:
        name, sh = REG8[k]
        return (self.r[name] >> sh) & 0xFF

    def set8(self, k: int, v: int):
        name, sh = REG8[k]
        self.r[name] = (self.r[name] & ~(0xFF << sh) & 0xFFFF) | ((v & 0xFF) << sh)

    def reg(self, k: int, w: int) -> int:
        return self.r[REG16[k]] if w == 2 else self.r8(k)

    def setreg(self, k: int, w: int, v: int):
        if w == 2:
            self.r[REG16[k]] = v & 0xFFFF
        else:
            self.set8(k, v)

    def seg(self, i: int) -> int:
        return self.r[SREG[i]] << 4

    # the bus
    def _lin(self, base: int, off: int) -> int:
        return (base + (off & 0xFFFF)) & 0xFFFFF

    def _word_at(self, lin: int) -> int:
        a = lin & ~1
        return self.mem[a] | (self.mem[(a + 1) & 0xFFFFF] << 8)

    def read(self, base: int, off: int, w: int) -> int:
        lin = self._lin(base, off)
        req = self.nreq
        self.nreq += 1
        if w == 2 and lin & 1:
            lin2 = self._lin(base, off + 1)
            self.cyc.append(Cycle("read", lin, "hi", 0, self._word_at(lin), req, False, True))
            self.cyc.append(Cycle("read", lin2, "lo", 0, self._word_at(lin2), req, True, True))
            return self.mem[lin] | (self.mem[lin2] << 8)
        width = "word" if w == 2 else "hi" if lin & 1 else "lo"
        self.cyc.append(Cycle("read", lin, width, 0, self._word_at(lin), req, True, w == 2))
        return self.mem[lin] | (self.mem[(lin + 1) & 0xFFFFF] << 8 if w == 2 else 0)

    def write(self, base: int, off: int, w: int, v: int):
        lin = self._lin(base, off)
        req = self.nreq
        self.nreq += 1
        lo, hi = v & 0xFF, (v >> 8) & 0xFF
        if w == 2 and lin & 1:
            lin2 = self._lin(base, off + 1)
            self.cyc.append(Cycle("write", lin, "hi", lo << 8, 0, req, False, True))
            self.cyc.append(Cycle("write", lin2, "lo", hi, 0, req, True, True))
            self._store(lin, lo)
            self._store(lin2, hi)
            return
        if w == 2:
            self.cyc.append(Cycle("write", lin, "word", v & 0xFFFF, 0, req, True, True))
            self._store(lin, lo)
            self._store(lin + 1, hi)
        else:
            self.cyc.append(Cycle("write", lin, "hi" if lin & 1 else "lo",
                                  lo << 8 if lin & 1 else lo, 0, req, True, False))
            self._store(lin, lo)

    def _store(self, lin: int, b: int):
        lin &= 0xFFFFF
        if lin < SFR_PAGE:          # the SFR page is on-chip (the RFM store), not memory
            self.mem[lin] = b

    def io_in(self, port: int, w: int) -> int:
        req = self.nreq
        self.nreq += 1
        if w == 2 and port & 1:
            # (F5b: silicon, f5r io) a word at an odd port: two byte cycles, the port on the
            # high lane, then port + 1 on the low (as a memory word)
            p2 = (port + 1) & 0xFFFF
            self.cyc.append(Cycle("io_read", port, "hi", 0, self.io_word, req, False, True))
            self.cyc.append(Cycle("io_read", p2, "lo", 0, self.io_word, req, True, True))
            return ((self.io_word >> 8) & 0xFF) | ((self.io_word & 0xFF) << 8)
        width = "word" if w == 2 else "hi" if port & 1 else "lo"
        self.cyc.append(Cycle("io_read", port, width, 0, self.io_word, req, True, w == 2))
        if w == 2:
            return self.io_word
        return (self.io_word >> 8 if port & 1 else self.io_word) & 0xFF

    def io_out(self, port: int, w: int, v: int):
        req = self.nreq
        self.nreq += 1
        if w == 2 and port & 1:
            # (F5b) a word at an odd port: the pair (the low byte on the high lane first)
            p2 = (port + 1) & 0xFFFF
            self.cyc.append(Cycle("io_write", port, "hi", (v & 0xFF) << 8, 0, req, False, True))
            self.cyc.append(Cycle("io_write", p2, "lo", (v >> 8) & 0xFF, 0, req, True, True))
        elif w == 2:
            self.cyc.append(Cycle("io_write", port, "word", v & 0xFFFF, 0, req, True, True))
        else:
            self.cyc.append(Cycle("io_write", port, "hi" if port & 1 else "lo",
                                  (v & 0xFF) << 8 if port & 1 else v & 0xFF, 0, req, True,
                                  False))

    # the stack
    def push(self, v: int):
        self.r["SP"] = (self.r["SP"] - 2) & 0xFFFF
        self.write(self.seg(2), self.r["SP"], 2, v)

    def pop(self) -> int:
        v = self.read(self.seg(2), self.r["SP"], 2)
        self.r["SP"] = (self.r["SP"] + 2) & 0xFFFF
        return v

    # ------------------------------------------------------------------ one instruction
    def fetch_code(self, ip: int, n: int = 6) -> bytes:
        base = self.seg(1)
        return bytes(self.mem[self._lin(base, ip + i)] for i in range(n))

    def modrm(self, code: bytes, k: int):
        """(mod, reg, rm, offset, segment base, bytes after the opcode incl. displacement);
        offset None for a register operand. The default segment: SS for the BP-based modes,
        DS0 otherwise; a prefix overrides."""
        m = code[k]
        mod, reg, rm = m >> 6, (m >> 3) & 7, m & 7
        if mod == 3:
            return mod, reg, rm, None, 0, 1
        if mod == 0 and rm == 6:
            off, n, bp = code[k + 1] | (code[k + 2] << 8), 3, False
        else:
            base = (("BW", "IX"), ("BW", "IY"), ("BP", "IX"), ("BP", "IY"), ("IX",), ("IY",),
                    ("BP",), ("BW",))[rm]
            disp, n = 0, 1
            if mod == 1:
                disp, n = _sx(code[k + 1], 1), 2
            elif mod == 2:
                disp, n = code[k + 1] | (code[k + 2] << 8), 3
            off = (sum(self.r[x] for x in base) + disp) & 0xFFFF
            bp = "BP" in base
        s = self.cur if self.cur is not None else (2 if bp else 3)
        return mod, reg, rm, off, self.seg(s), n

    def data_seg(self) -> int:
        return self.seg(self.cur if self.cur is not None else 3)

    def step(self, ip: int, strings: dict | None = None) -> Start:
        """Execute the instruction at ip (its offset in PS)."""
        code = self.fetch_code(ip, 8)
        st = Start(ip, (ip - self.code_org) & 0xFFFF, code[:6], 1, self.snapshot())
        self.cyc, self.nreq = [], 0
        self.cur, self.pfx = self.pfx, None
        try:
            self._exec(st, code, self.cur, strings)
        except Trap as e:
            e.start = st
            raise
        finally:
            if st.ea:
                st.ea &= 0xFFFFF
            st.cycles = self.cyc
        return st

    def _rm_read(self, mod, rm, off, base, w):
        return self.reg(rm, w) if mod == 3 else self.read(base, off, w)

    def _rm_write(self, mod, rm, off, base, w, v):
        if mod == 3:
            self.setreg(rm, w, v)
        else:
            self.write(base, off, w, v)

    def _exec(self, st: Start, code: bytes, pfx, strings):
        o = code[0]
        r = self.r
        imm16 = lambda k: code[k] | (code[k + 1] << 8)
        if o in PREFIX_SREG:
            self.pfx = PREFIX_SREG[o]
            return
        if o in REP_PREFIXES or o in (0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE,
                                      0xAF, 0x6C, 0x6D, 0x6E, 0x6F):
            self._string(st, code, pfx, strings)
            return
        if o == 0x90:
            return
        if o == 0x0F:
            self._page0f(st, code, pfx)                 # (WP79, F32) the 0F page
            return
        if o in ONE_FLAG:                               # (WP79, F33) the flag forms
            bit, how = ONE_FLAG[o]
            v = (0 if how == "clr" else 1 if how == "set" else 1 - flag(self.psw, bit))
            self.psw = _put(self.psw, bit, v)
            return
        if o in (0x27, 0x2F, 0x37, 0x3F):               # (WP79, F33) the adjusts
            self._adjust(o)
            return
        if o == 0x98:                                   # (WP79) CVTBW
            r["AW"] = _sx(r["AW"], 1) & 0xFFFF
            return
        if o == 0x99:                                   # (WP79) CVTWL
            r["DW"] = 0xFFFF if r["AW"] & 0x8000 else 0
            return
        if o in (0xD4, 0xD5):                           # (WP79) CVTBD / CVTDB imm8
            st.length = 2
            self._convert(o, code[1])
            return
        if o == 0xF4:
            st.halt = True
            return
        if 0x91 <= o <= 0x97:
            k = REG16[o - 0x90]
            r["AW"], r[k] = r[k], r["AW"]
            return
        if 0x40 <= o <= 0x4F:
            k = REG16[o & 7]
            r[k], self.psw = incdec(o >= 0x48, r[k], 2, self.psw)
            return
        if 0x50 <= o <= 0x57:                           # PUSH r16 (SP: the decremented SP)
            st.sw = (r["SP"] - 2) & 0xFFFF
            v = st.sw if o == 0x54 else r[REG16[o & 7]]
            self.push(v)
            return
        if 0x58 <= o <= 0x5F:
            st.sr = r["SP"]
            v = self.pop()
            r[REG16[o & 7]] = v
            return
        if 0xB0 <= o <= 0xB7:
            st.length = 2
            self.set8(o - 0xB0, code[1])
            return
        if 0xB8 <= o <= 0xBF:
            st.length = 3
            r[REG16[o - 0xB8]] = imm16(1)
            return
        if o < 0x40 and o & 7 in (4, 5):                # ALU acc,imm
            w = 1 + (o & 1)
            st.length = 1 + w
            b = code[1] if w == 1 else imm16(1)
            res, self.psw = alu((o >> 3) & 7, self.reg(0, w), b, w, self.psw)
            if (o >> 3) & 7 != 7:
                self.setreg(0, w, res)
            return
        if o in (0xA8, 0xA9):                           # TEST acc,imm
            w = 1 + (o & 1)
            st.length = 1 + w
            _, self.psw = alu(4, self.reg(0, w), code[1] if w == 1 else imm16(1), w, self.psw)
            return
        if 0xA0 <= o <= 0xA3:                           # MOV acc <-> [disp16]
            w = 1 + (o & 1)
            st.length = 3
            base, off = self.data_seg(), imm16(1)
            st.ea = base + off
            if o < 0xA2:
                self.setreg(0, w, self.read(base, off, w))
            else:
                self.write(base, off, w, self.reg(0, w))
            return
        if o in (0xE4, 0xE5, 0xE6, 0xE7, 0xEC, 0xED, 0xEE, 0xEF):
            w = 1 + (o & 1)
            port = code[1] if o < 0xE8 else r["DW"]
            st.length = 2 if o < 0xE8 else 1
            st.port = port
            if o & 2:
                self.io_out(port, w, self.reg(0, w))
            else:
                self.setreg(0, w, self.io_in(port, w))
            return
        if 0x70 <= o <= 0x7F or o in (0xEB, 0xE2):
            st.length = 2
            if o == 0xE2:
                r["CW"] = (r["CW"] - 1) & 0xFFFF
                tk = r["CW"] != 0
            else:
                tk = o == 0xEB or cond(o & 0xF, self.psw)
            if tk:
                st.taken = True
                st.target = (st.ip + 2 + _sx(code[1], 1)) & 0xFFFF
            return
        if o in (0xE8, 0xE9):
            st.length = 3
            st.taken = True
            st.target = (st.ip + 3 + imm16(1)) & 0xFFFF
            if o == 0xE8:
                st.sw = (r["SP"] - 2) & 0xFFFF
                self.push((st.ip + 3) & 0xFFFF)
            return
        if o == 0xC3:
            st.sr = r["SP"]
            st.taken = True
            st.target = self.pop()
            return
        if o in (0x68, 0x6A):
            st.length = 3 if o == 0x68 else 2
            st.sw = (r["SP"] - 2) & 0xFFFF
            self.push(imm16(1) if o == 0x68 else _sx(code[1], 1) & 0xFFFF)
            return
        if o == 0x60:                                   # PUSH R
            st.sw = (r["SP"] - 2) & 0xFFFF
            sp0 = r["SP"]
            for k in REG16:
                self.push(sp0 if k == "SP" else r[k])
            return
        if o == 0x61:                                   # POP R (SP's word read and discarded)
            st.sr = r["SP"]
            for k in reversed(REG16):
                self.discard = k == "SP"
                v = self.pop()
                self.discard = False
                if k != "SP":
                    r[k] = v
            return
        if o == 0xC8:                                   # PREPARE imm16,imm8
            # (F5b: silicon, f5x prepare) the level byte whole (not mod 32): BP pushed, the
            # level - 1 words at SS:[BP - 2], [BP - 4], ... pushed, then the frame pointer
            st.length = 4
            st.sw = (r["SP"] - 2) & 0xFFFF
            bp = r["BP"]
            self.push(bp)
            frame = r["SP"]
            for _ in range(1, code[3]):
                bp = (bp - 2) & 0xFFFF
                self.push(self.read(self.seg(2), bp, 2))
            if code[3]:
                self.push(frame)
            r["BP"] = frame
            r["SP"] = (r["SP"] - imm16(1)) & 0xFFFF
            return
        if o == 0xC9:                                   # DISPOSE
            st.sr = r["BP"]
            r["SP"] = r["BP"]
            r["BP"] = self.pop()
            return
        if o in (0x06, 0x0E, 0x16, 0x1E):               # PUSH sreg
            st.sw = (r["SP"] - 2) & 0xFFFF
            self.push(r[SREG[(o >> 3) & 3]])
            return
        if o in (0x07, 0x17, 0x1F):                     # POP sreg
            st.sr = r["SP"]
            r[SREG[(o >> 3) & 3]] = self.pop()
            return
        if o == 0xD7:                                   # XLAT
            base, off = self.data_seg(), (r["BW"] + (r["AW"] & 0xFF)) & 0xFFFF
            st.ea = base + off
            self.set8(0, self.read(base, off, 1))
            return
        if self._xfer_misc(st, code, o):                # (S6) F35-F37, F39, F40's gaps
            return
        self._modrm_form(st, code, o)

    def _flags_loaded(self, v: int) -> int:
        """(S6) the PSW as POP PSW / RETI / SAHF leave it from the word v (its bits 11-0; MD and
        RB stay: the V35's, the chain prelude's POP PSW 0002h keeps RB 7). The V20 forces its fixed
        bits (1 = 1, 3 = 5 = 0: the V35's BRKI, F0, F1): v20_flags (sst.py's V20 class)."""
        psw = (self.psw & 0xF000) | (v & 0x0FFF)
        if self.v20_flags:
            psw = (psw & ~((1 << F0) | (1 << F1))) | (1 << BRKI)
        return psw

    def _xfer_misc(self, st: Start, code: bytes, o: int) -> bool:
        """(S6) the forms the corpus's F35-F37, F39 and F40 run that the reference lacked: BCWZ
        (E3), DBNZE / DBNZNE (E1 / E0), BR / CALL far (EA / 9A), RET imm16 / far / far imm16 (C2 /
        CB / CA), RETI (CF), BRK 3 / BRK imm8 (CC / CD), PUSH PSW / POP PSW (9C / 9D), SAHF / LAHF
        (9E / 9F), LES / LDS (C4 / C5: DS1 / DS0), BUSLOCK (F0, no effect: a start of its own, as
        the frozen model's), the bus cycles in the V35's order (templates.py: BRK reads the
        vector's offset, pushes the PSW, reads its segment, pushes PS and the return offset;
        CALL far pushes PS, then the return offset). True when o is one of them."""
        r = self.r
        imm16 = lambda k: code[k] | (code[k + 1] << 8)
        if o == 0xF0:
            return True
        if o in (0xE0, 0xE1, 0xE3):                     # DBNZNE / DBNZE / BCWZ disp8
            st.length = 2
            if o == 0xE3:
                tk = r["CW"] == 0
            else:
                r["CW"] = (r["CW"] - 1) & 0xFFFF
                tk = r["CW"] != 0 and bool(flag(self.psw, Z)) == (o == 0xE1)
            if tk:
                st.taken = True
                st.target = (st.ip + 2 + _sx(code[1], 1)) & 0xFFFF
            return True
        if o in (0xEA, 0x9A):                           # BR far / CALL far offset16 segment16
            st.length = 5
            if o == 0x9A:
                st.sw = (r["SP"] - 2) & 0xFFFF
                self.push(r["PS"])
                self.push((st.ip + 5) & 0xFFFF)
            r["PS"] = imm16(3)
            st.taken = True
            st.target = imm16(1)
            return True
        if o in (0xC2, 0xCA, 0xCB, 0xCF):               # RET imm16 / far imm16 / far, RETI
            st.length = 3 if o in (0xC2, 0xCA) else 1
            st.sr = r["SP"]
            ip = self.pop()
            if o != 0xC2:
                r["PS"] = self.pop()
            if o == 0xCF:
                self.psw = self._flags_loaded(self.pop())
            if o in (0xC2, 0xCA):
                r["SP"] = (r["SP"] + imm16(1)) & 0xFFFF
            st.taken = True
            st.target = ip
            return True
        if o in (0xCC, 0xCD):                           # BRK 3 / BRK imm8
            n = 3 if o == 0xCC else code[1]
            st.length = 1 if o == 0xCC else 2
            st.sw = (r["SP"] - 2) & 0xFFFF
            ip = self.read(0, 4 * n, 2)
            self.push(self.psw)
            self.psw &= ~((1 << IE) | (1 << BRK))
            ps = self.read(0, 4 * n + 2, 2)
            self.push(r["PS"])
            self.push((st.ip + st.length) & 0xFFFF)
            r["PS"] = ps
            st.taken = True
            st.target = ip
            return True
        if o == 0x9C:                                   # PUSH PSW
            st.sw = (r["SP"] - 2) & 0xFFFF
            self.push(self.psw)
            return True
        if o == 0x9D:                                   # POP PSW
            st.sr = r["SP"]
            self.psw = self._flags_loaded(self.pop())
            return True
        if o == 0x9E:                                   # SAHF: the PSW's low byte from AH
            self.psw = self._flags_loaded((self.psw & 0x0F00) | (r["AW"] >> 8))
            return True
        if o == 0x9F:                                   # LAHF: AH from the PSW's low byte
            r["AW"] = (r["AW"] & 0xFF) | ((self.psw & 0xFF) << 8)
            return True
        if o in (0xC4, 0xC5):                           # LES / LDS r16,m32
            mod, reg, rm, off, base, n = self.modrm(code, 1)
            if mod == 3:
                raise NotModelled(f"opcode {o:02X} with a register operand")
            st.length = 1 + n
            st.ea = base + off
            v = self.read(base, off, 2)
            r[SREG[0 if o == 0xC4 else 3]] = self.read(base, off + 2, 2)
            r[REG16[reg]] = v
            return True
        return False

    def _modrm_form(self, st: Start, code: bytes, o: int):
        r = self.r
        mod, reg, rm, off, base, n = self.modrm(code, 1)
        mem = mod != 3
        st.length = 1 + n
        if mem:
            st.ea = base + off
        w = 1 + (o & 1)
        if o < 0x40 and o & 7 < 4:                      # ALU r/m,reg / reg,r/m
            op = (o >> 3) & 7
            if o & 2:
                a, b = self.reg(reg, w), self._rm_read(mod, rm, off, base, w)
                res, self.psw = alu(op, a, b, w, self.psw)
                if op != 7:
                    self.setreg(reg, w, res)
            else:
                a, b = self._rm_read(mod, rm, off, base, w), self.reg(reg, w)
                res, self.psw = alu(op, a, b, w, self.psw)
                if op != 7:
                    self._rm_write(mod, rm, off, base, w, res)
            return
        if o in (0x84, 0x85):                           # TEST
            _, self.psw = alu(4, self._rm_read(mod, rm, off, base, w), self.reg(reg, w), w,
                              self.psw)
            return
        if o in (0x86, 0x87):                           # XCH
            v = self._rm_read(mod, rm, off, base, w)
            self._rm_write(mod, rm, off, base, w, self.reg(reg, w))
            self.setreg(reg, w, v)
            return
        if 0x88 <= o <= 0x8B:                           # MOV
            if o & 2:
                self.setreg(reg, w, self._rm_read(mod, rm, off, base, w))
            else:
                self._rm_write(mod, rm, off, base, w, self.reg(reg, w))
            return
        if o == 0x8C:                                   # MOV r/m16,sreg
            self._rm_write(mod, rm, off, base, 2, r[SREG[reg & 3]])
            return
        if o == 0x8D:                                   # LDEA
            if not mem:
                raise NotModelled("LDEA with a register operand")
            r[REG16[reg]] = off
            return
        if o == 0x8E:                                   # MOV sreg,r/m16
            r[SREG[reg & 3]] = self._rm_read(mod, rm, off, base, 2)
            return
        if o == 0x8F:                                   # POP r/m16
            if reg != 0:
                raise NotModelled(f"8F /{reg}")
            st.sr = r["SP"]
            v = self.pop()
            if mem:     # the EA from the registers before the pop (SP is not a base)
                self.write(base, off, 2, v)
            else:
                r[REG16[rm]] = v
            return
        if 0x80 <= o <= 0x83:                           # the immediate group
            w = 1 + (o & 1)
            k = 1 + n
            b = _sx(code[k], 1) & 0xFFFF if o == 0x83 else code[k] if w == 1 else (
                code[k] | (code[k + 1] << 8))
            st.length += 1 if o != 0x81 else 2
            a = self._rm_read(mod, rm, off, base, w)
            res, self.psw = alu(reg, a, b, w, self.psw)
            if reg != 7:
                self._rm_write(mod, rm, off, base, w, res)
            return
        if o in (0xC6, 0xC7):                           # MOV r/m,imm (the reg field ignored:
            k = 1 + n                                   # the V20's, SingleStepTests)
            st.length += w
            self._rm_write(mod, rm, off, base, w, code[k] if w == 1 else
                           code[k] | (code[k + 1] << 8))
            return
        if o in (0xC0, 0xC1, 0xD0, 0xD1, 0xD2, 0xD3):   # the shift group
            if o in (0xC0, 0xC1):
                cnt = code[1 + n]
                st.length += 1
            elif o in (0xD0, 0xD1):
                cnt = 1
            else:
                cnt = r["CW"] & 0xFF
            st.count = cnt
            a = self._rm_read(mod, rm, off, base, w)
            res, self.psw = shift(reg, a, cnt, w, self.psw)
            if cnt or V20_UNDEF or mod == 3:
                # (F5b: silicon, the fuzz) a memory operand shifted by a zero count is read, not
                # written back
                self._rm_write(mod, rm, off, base, w, res)
            return
        if o in (0xF6, 0xF7):
            if reg in (0, 1):                           # TEST r/m,imm (1: its alias)
                k = 1 + n
                st.length += w
                b = code[k] if w == 1 else code[k] | (code[k + 1] << 8)
                _, self.psw = alu(4, self._rm_read(mod, rm, off, base, w), b, w, self.psw)
                return
            a = self._rm_read(mod, rm, off, base, w)
            if reg == 2:
                self._rm_write(mod, rm, off, base, w, ~a)
            elif reg == 3:
                res, self.psw = neg(a, w, self.psw)
                self._rm_write(mod, rm, off, base, w, res)
            elif reg in (4, 5):
                p, self.psw = mul(reg == 5, self.reg(0, w), a, w, self.psw)
                if w == 1:
                    r["AW"] = p & 0xFFFF
                else:
                    r["AW"], r["DW"] = p & 0xFFFF, (p >> 16) & 0xFFFF
            else:
                num = r["AW"] if w == 1 else (r["DW"] << 16) | r["AW"]
                q, rem, self.psw, trap = div(reg == 7, num, a, w, self.psw)
                if trap:
                    st.trap = True
                    raise Trap(f"divide error at {st.ip:04X}")
                if w == 1:
                    r["AW"] = (rem << 8) | q
                else:
                    r["AW"], r["DW"] = q, rem
            return
        if o in (0x69, 0x6B):                           # (WP79, F33) MUL r16,r/m16,imm
            k = 1 + n
            if o == 0x69:
                imm = code[k] | (code[k + 1] << 8)
                st.length += 2
            else:
                imm = _sx(code[k], 1) & 0xFFFF
                st.length += 1
            a = self._rm_read(mod, rm, off, base, 2)
            p, self.psw = mul(True, a, imm, 2, self.psw)
            r[REG16[reg]] = p & 0xFFFF
            return
        if o in (0xFE, 0xFF):
            if reg in (0, 1):
                a = self._rm_read(mod, rm, off, base, w)
                res, self.psw = incdec(reg == 1, a, w, self.psw)
                self._rm_write(mod, rm, off, base, w, res)
                return
            if o == 0xFF and reg == 6:                  # PUSH r/m16 (SP: the decremented SP)
                st.sw = (r["SP"] - 2) & 0xFFFF
                v = st.sw if mod == 3 and rm == 4 else self._rm_read(mod, rm, off, base, 2)
                self.push(v)
                return
            # (S6) CALL / BR near r/m16 (FF /2, /4: the register or the word at the EA), CALL /
            # BR far [m] (/3, /5: the pointer's offset, then its segment); CALL pushes (far: PS,
            # then) the return offset
            if o == 0xFF and (reg in (2, 4) or (reg in (3, 5) and mem)):
                ip = self._rm_read(mod, rm, off, base, 2)
                if reg in (3, 5):
                    ps = self.read(base, off + 2, 2)
                if reg in (2, 3):
                    st.sw = (r["SP"] - 2) & 0xFFFF
                    if reg == 3:
                        self.push(r["PS"])
                    self.push((st.ip + st.length) & 0xFFFF)
                if reg in (3, 5):
                    r["PS"] = ps
                st.taken = True
                st.target = ip
                return
            raise NotModelled(f"{o:02X} /{reg}")
        raise NotModelled(f"opcode {o:02X}")

    def _adjust(self, o: int):
        """(WP79, F33) ADJ4A (27, DAA), ADJ4S (2F, DAS), ADJBA (37, AAA), ADJBS (3F, AAS), as the
        V20 suite has them (10,000 of 10,000 tests each): the flags are the ALU's for AL plus /
        minus the correction (S Z P V AC of that byte add / subtract), then CY and AC the
        adjust decisions. ADJ4A / ADJ4S: the low digit corrected (6) when it exceeds 9 or AC is
        set, the high (60h) when CY is set or AL exceeds 99h, or 9Fh with AC set; ADJBA / ADJBS:
        AL + / - 6 and AH + / - 1 when the low digit exceeds 9 or AC is set, AL's high digit
        cleared."""
        r, psw = self.r, self.psw
        al, cf, af = r["AW"] & 0xFF, flag(psw, CY), flag(psw, AC)
        sub = o in (0x2F, 0x3F)
        if o in (0x27, 0x2F):
            lo = (al & 0xF) > 9 or af
            hi = bool(cf) or al > (0x9F if af else 0x99)
            res, psw = alu(5 if sub else 0, al, (6 if lo else 0) | (0x60 if hi else 0), 1, psw)
            r["AW"] = (r["AW"] & 0xFF00) | res
            self.psw = _put(_put(psw, CY, hi), AC, lo)
            return
        adj = (al & 0xF) > 9 or af
        _, psw = alu(5 if sub else 0, al, 6 if adj else 0, 1, psw)
        ah = (r["AW"] >> 8) + ((-1 if sub else 1) if adj else 0)
        al = (al + ((-6 if sub else 6) if adj else 0)) & 0x0F     # no carry into AH
        r["AW"] = ((ah & 0xFF) << 8) | al
        self.psw = _put(_put(psw, CY, adj), AC, adj)

    def _convert(self, o: int, imm: int):
        """(WP79, F33) CVTBD (D4 imm8, AAM: AH = AL / imm, AL = AL % imm) and CVTDB (D5 imm8,
        AAD: AL = AH * imm + AL, AH = 0)."""
        r = self.r
        al, ah = r["AW"] & 0xFF, (r["AW"] >> 8) & 0xFF
        if o == 0xD4:
            # by 0: no trap, AH = FFh and AL kept (the V20 suite)
            q, m = divmod(al, imm) if imm else (0xFF, al)
            r["AW"] = ((q & 0xFF) << 8) | m
            psw = _szp(self.psw, m, 1)
            self.psw = psw & ~((1 << CY) | (1 << V) | ((1 << AC) if V20_UNDEF else 0))
            return
        # CVTDB multiplies by the byte (F5: silicon, f5x; the V20 suite multiplies by 10)
        res, self.psw = alu(0, (ah * (10 if V20_UNDEF else imm)) & 0xFF, al, 1, self.psw)
        r["AW"] = res

    def _page0f(self, st: Start, code: bytes, pfx):
        """(WP79, F32) the 0F page: the bit ops TEST1 / CLR1 / SET1 / NOT1 (10-1F: bits 2:1 the
        operation, bit 0 the width, bit 3 an imm index after the operand, else CL; the index
        modulo the width), the packed BCD strings ADD4S / SUB4S / CMP4S (20 / 22 / 26: (CL + 1)
        / 2 byte pairs, the source byte at DS0:IX + i (a prefix's segment) read before the
        destination's at DS1:IY + i, the result written back), the digit rotates ROL4 / ROR4
        (28 / 2A: the byte operand and AL's low digit), the bit fields INS / EXT (31 / 39, 33 /
        3B: the offset register in ModR/M bits 2:0, the width - 1 in the register of bits 5:3
        or the imm4 byte; the field in the words at DS1:IY (INS) / DS0:IX (EXT), a prefix's for
        EXT; the offset register and the pointer stepped)."""
        r = self.r
        s = code[1]
        if s in (0x20, 0x22, 0x26):
            st.length = 2
            n = ((r["CW"] & 0xFF) + 1) // 2
            src, dst = self.seg(pfx if pfx is not None else 3), self.seg(0)
            ix, iy = r["IX"], r["IY"]
            carry, z = 0, 1
            last = None
            for i in range(n):
                b = self.read(src, ix + i, 1)
                a = self.read(dst, iy + i, 1)
                cin = carry
                carry, zt, res = (bcd_add8 if s == 0x20 else bcd_sub8)(a, b, carry)
                z &= zt if V20_UNDEF else int(res == 0)
                last = (a, b, cin, res)
                if s != 0x26:
                    self.write(dst, iy + i, 1, res)
            psw = self.psw
            if V20_UNDEF:
                fl = ((CY, carry), (Z, z), (V, 0), (S, carry), (AC, carry), (P, z))
            else:
                # (F5b: silicon, f5x bcd4s, 220 cases) the last byte step's flags: CY its carry,
                # Z every byte written zero, S P the last byte's, AC its low digit's adjust
                # decision, V the adjust's overflow (the binary sum's bit 7 0 and the byte's 1 for
                # an add, the reverse for a subtract); no byte pair: the cleared state
                a, b, cin, res = last if last else (0, 0, 0, 0)
                if s == 0x20:
                    lo = (a & 15) + (b & 15) + cin
                    ac = int(lo > 9)
                    s7 = ((a + b + cin) >> 7) & 1
                    v = int(not s7 and res >> 7 & 1)
                else:
                    lo = (a & 15) - (b & 15) - cin
                    ac = int(lo < 0 or (lo & 15) > 9)
                    s7 = ((a - b - cin) >> 7) & 1
                    v = int(s7 and not res >> 7 & 1)
                if not last:
                    ac = v = 0
                fl = ((CY, carry), (Z, z), (V, v), (S, res >> 7 & 1), (AC, ac),
                      (P, int(bin(res).count("1") % 2 == 0)))
            for bit, v in fl:
                psw = _put(psw, bit, v)
            self.psw = psw
            st.string = (None, ix, iy, 0, n, False)
            return
        if not (0x10 <= s <= 0x1F or s in (0x28, 0x2A, 0x31, 0x33, 0x39, 0x3B)):
            raise NotModelled(f"opcode 0F {s:02X}")
        mod, reg, rm, off, base, n = self.modrm(code, 2)
        mem = mod != 3
        st.length = 2 + n
        if mem:
            st.ea = base + off
        if 0x10 <= s <= 0x1F:
            w = 1 + (s & 1)
            if s & 8:
                idx = code[2 + n]
                st.length += 1
            else:
                idx = r["CW"] & 0xFF
            m = 1 << (idx & (8 * w - 1))
            a = self._rm_read(mod, rm, off, base, w)
            op = (s >> 1) & 3
            if op == 0:                                 # TEST1: S Z P of the masked value
                t = a & m
                psw = _szp(self.psw, t, w)
                self.psw = psw & ~((1 << CY) | (1 << V) | ((1 << AC) if V20_UNDEF else 0))
                return
            v = a & ~m if op == 1 else a | m if op == 2 else a ^ m
            self._rm_write(mod, rm, off, base, w, v & _mask(w))
            return
        if s in (0x28, 0x2A):                           # ROL4 / ROR4
            a = self._rm_read(mod, rm, off, base, 1)
            al = r["AW"] & 0xFF
            # AL's low digit takes the operand's high (ROL4) / low (ROR4) digit, its high digit
            # kept: the data book's, and the V35's (F32-out-rol4_dl-k2: the second ROL4 DL
            # leaves AL = 08h, which the OUT after it writes). The V20 differs (the V20 suite):
            # ROL4 leaves AL = AL << 4 | the operand's high digit, ROR4 AL = the operand
            # (V20_DIGITS, sst.py's V20 class)
            if s == 0x28:
                v, al = ((a << 4) | (al & 0xF)) & 0xFF, (al & 0xF0) | (a >> 4)
                if self.v20_digits:
                    al = ((r["AW"] << 4) | (a >> 4)) & 0xFF
            else:
                v, al = ((al & 0xF) << 4) | (a >> 4), (al & 0xF0) | (a & 0xF)
                if self.v20_digits:
                    al = a
            if V20_UNDEF:
                self._rm_write(mod, rm, off, base, 1, v)
                self.set8(0, al)
            else:
                # (F5b: silicon, f5r rot4al) AL first, then the operand: ROL4 / ROR4 AL keeps
                # the operand's result
                self.set8(0, al)
                self._rm_write(mod, rm, off, base, 1, v)
            return
        if mem:
            raise NotModelled(f"0F {s:02X} with a memory operand")
        offset = self.r8(rm)
        if s & 8:
            width = code[3]
            st.length += 1
        else:
            width = self.r8(reg)
        o4, w4 = offset & 15, width & 15
        cross = offset + width >= 16                    # the model's: the registers whole
        fm = (1 << (w4 + 1)) - 1
        if s in (0x33, 0x3B):                           # EXT
            src = self.seg(pfx if pfx is not None else 3)
            lo = self.read(src, r["IX"], 2)
            hi = self.read(src, r["IX"] + 2, 2) if cross else 0
            v = (((hi << 16) | lo) >> o4) & fm
            r["AW"] = v
            # the flags: none (F5: the V35 leaves the PSW, f5x 220 cases; the V20 suite has
            # SUB(15, offset + width) at byte width, 20,000 of 20,000)
            if V20_UNDEF:
                _, self.psw = alu(5, 15, (offset + width) & 0xFF, 1, self.psw)
            ptr = "IX"
        else:                                           # INS
            dst = self.seg(0)
            # (F5b: silicon, f5r insal) AW is read before the offset register is stepped (an
            # INS whose offset is AL or AH inserts AW's bits as they were); the V20 suite steps
            # first and inserts the stepped value
            aw = r["AW"]
            if V20_UNDEF:
                self.set8(rm, (o4 + w4 + 1) & 15)
                aw = r["AW"]
            field = (aw & fm) << o4
            mask = fm << o4
            lo = self.read(dst, r["IY"], 2)
            self.write(dst, r["IY"], 2, ((lo & ~mask) | field) & 0xFFFF)
            if cross:
                hi = self.read(dst, r["IY"] + 2, 2)
                self.write(dst, r["IY"] + 2, 2, ((hi & ~(mask >> 16)) | (field >> 16)) & 0xFFFF)
            # the flags: none (F5: the V35, f5x; the V20 suite: SUB(15, offset + width + 1))
            if V20_UNDEF:
                _, self.psw = alu(5, 15, (offset + width + 1) & 0xFF, 1, self.psw)
            ptr = "IY"
        new = o4 + w4 + 1
        self.set8(rm, new & 15)
        if s in (0x33, 0x3B) and not V20_UNDEF:
            r["AW"] = v         # (F5b: silicon, f5r extal) the offset register first, then AW
        if new >= 16:
            r[ptr] = (r[ptr] + 2) & 0xFFFF

    def _string(self, st: Start, code: bytes, pfx, strings):
        """(F24) the string forms with or without a REP prefix: elements while CW is not 0
        (with a prefix), a REPE / REPNE compare stopping on its condition; a REP compare that
        ran an element reads one element more (the overrun, F24 silicon). DIR steps the
        addresses (+ / - the width)."""
        r = self.r
        rep, k = None, 0
        if code[0] in REP_PREFIXES:
            rep, k = code[0], 1
        o = code[k]
        st.length = k + 1
        if o & 0xFE not in (0xA4, 0xA6, 0xAA, 0xAC, 0xAE, 0x6C, 0x6E):
            raise NotModelled(f"REP before {o:02X}")
        w = 1 + (o & 1)
        step = -w if flag(self.psw, DIR) else w
        src = self.seg(pfx if pfx is not None else 3)
        dst = self.seg(0)
        cmp_ = o & 0xFE in (0xA6, 0xAE)
        ix0, iy0, n, ended = r["IX"], r["IY"], 0, False

        def element(i, overrun=False):
            ix, iy = (r["IX"] + i * step) & 0xFFFF, (r["IY"] + i * step) & 0xFFFF
            b = o & 0xFE
            # (S6) the overrun element's reads are discarded (sst.py: the V20 does not make
            # them, its suite need not list their bytes)
            self.discard = overrun
            if b == 0xA4:
                v = self.read(src, ix, w)
                if not overrun:
                    self.write(dst, iy, w, v)
            elif b == 0xA6:                             # the destination read first
                d = self.read(dst, iy, w)
                s = self.read(src, ix, w)
                if not overrun:
                    _, self.psw = alu(7, s, d, w, self.psw)
            elif b == 0xAA:
                self.write(dst, iy, w, self.reg(0, w))
            elif b == 0xAC:
                v = self.read(src, ix, w)
                self.setreg(0, w, v)
            elif b == 0xAE:
                d = self.read(dst, iy, w)
                if not overrun:
                    _, self.psw = alu(7, self.reg(0, w), d, w, self.psw)
            elif b == 0x6C:
                v = self.io_in(r["DW"], w)
                self.write(dst, iy, w, v)
            else:
                v = self.read(src, ix, w)
                self.io_out(r["DW"], w, v)
            self.discard = False

        if rep is None:
            element(0)
            n = 1
        else:
            while r["CW"] != 0:
                element(n)
                n += 1
                r["CW"] = (r["CW"] - 1) & 0xFFFF
                # REPE / REPNE: Z; (WP77) REPC / REPNC: the carry (V20 / V35: 65 repeats
                # while CY is set, 64 while it is clear)
                f = flag(self.psw, CY) if rep in CY_PREFIXES else flag(self.psw, Z)
                if cmp_ and bool(f) != (rep in (0xF3, 0x65)):
                    ended = True
                    break
            if cmp_ and n:
                element(n, overrun=True)
        uses_ix = o & 0xFE in (0xA4, 0xA6, 0xAC, 0x6E)
        uses_iy = o & 0xFE in (0xA4, 0xA6, 0xAA, 0xAE, 0x6C)
        if uses_ix:
            r["IX"] = (r["IX"] + n * step) & 0xFFFF
        if uses_iy:
            r["IY"] = (r["IY"] + n * step) & 0xFFFF
        st.port = r["DW"] if o & 0xFE in (0x6C, 0x6E) else 0
        st.string = (rep, ix0, iy0, st.port, n, ended)


# ---------------------------------------------------------------------------------- a chain

@dataclass
class Run:
    starts: list                # Start per instruction start, in order
    cycles: list                # every data cycle, in order (Cycle)
    init: dict                  # the register file at the start (Cpu.snapshot)
    final: dict                 # ... after the last instruction (HALT)
    code_org: int               # the IP of the code's offset 0 (the prelude tail's first byte)
    mem_init: list              # [(linear address, bytes)]: the memory besides the 90h default
    trap: str = ""


MAX_STARTS = 20000


def chain_memory(chain, chain_base: int) -> tuple[bytearray, list]:
    """The image as memory (90h where the image has nothing) and its non-default runs."""
    from .image import VECTOR_TABLE, prelude, reset_vector
    head = prelude(chain.regs, chain.wtc, chain.rfm, chain.prc,
                   getattr(chain, "prelude_marker", None))
    if CODE_BASE + len(head) != chain_base:
        raise RuntimeError(f"{chain.id}: chain base {chain_base:05X}, the prelude ends at "
                           f"{CODE_BASE + len(head):05X}")
    mem = bytearray(b"\x90") * (1 << 20)
    runs = [(0, bytes(VECTOR_TABLE)), (PRELUDE_STACK, bytes([0x02, 0x00])),
            (CODE_BASE, head + chain.code), (0xFFFF0, reset_vector(CODE_BASE, CODE_SEGMENT))]
    for a, data in runs:
        mem[a:a + len(data)] = data
    return mem, runs


def init_regs(chain) -> dict:
    """The register file at the model's clock 0 (the EU's presets: chain.regs, the segments
    besides; PS the code segment, the PSW after the prelude's POP PSW)."""
    regs = {n: chain.regs.get(n, 0) for n in REG16 + ("DS0", "DS1", "SS")}
    regs["PS"] = CODE_SEGMENT
    regs["PSW"] = PSW_INIT
    return regs


def chain_run(chain, chain_base: int, io_word: int = IO_WORD) -> Run:
    """The chain from the prelude's tail (the model's first instruction, prelude_tail=segs)
    to its HALT."""
    from .image import prelude_tail
    tail = prelude_tail(chain, True)
    code_org = chain_base - len(tail) - CODE_BASE
    mem, runs = chain_memory(chain, chain_base)
    regs = init_regs(chain)
    cpu = Cpu(regs, mem, io_word, code_org)
    init = cpu.snapshot()
    starts, cycles = [], []
    ip = code_org
    trap = ""
    for _ in range(MAX_STARTS):
        try:
            st = cpu.step(ip)
        except Trap as e:
            trap = str(e)
            break
        starts.append(st)
        cycles += st.cycles
        if st.halt:
            break
        ip = st.target if st.taken else (ip + st.length) & 0xFFFF
    else:
        raise RuntimeError(f"{chain.id}: no HALT in {MAX_STARTS} starts")
    for st in starts:
        if st.taken:
            st.target = (st.target - code_org) & 0xFFFF      # a code offset
    return Run(starts, cycles, init, cpu.snapshot(), code_org, runs, trap)


# ---------------------------------------------------------------------------------- agreement

def frozen_walk(chain, chain_base: int) -> list:
    """The frozen model's starts in program order (templates.decode / execute from the EU's
    presets, as the EU's _start meets them: the DS1 prefix's SFR store, the string forms'
    element counts from the chain walk): [(offset, op)]."""
    from .forms import F32_BCD
    from .image import prelude_tail
    from .normalize import WALK_STRING_FORMS, string_elements
    from .sim.frozen.bus import SFR_PAGE as FSFR
    from .sim.frozen.machine import _prefixes
    from .sim.frozen.templates import BCD_CLASSES, STRING_CLASSES, decode, execute
    tail = prelude_tail(chain, True)
    code = tail + chain.code
    regs = dict(chain.regs)
    # (S6) the code offset (in PS) of code[0], as the frozen EU keeps it (eu.py: an absolute
    # target, BR / CALL far, r16, [m], a BRK vector, is a code offset less it); code[0] here is
    # the prelude tail's first byte
    regs["code_at"] = chain_base - len(tail) - CODE_BASE
    strings = {}
    # (WP79) as the frozen machine keys them (machine.py): F33's REPC / REPNC forms
    # (WALK_STRING_FORMS) and F32's BCD strings by the 0F opcode's offset
    if any(i.role == "x" and (i.form in WALK_STRING_FORMS or i.form in F32_BCD)
           for i in chain.instrs):
        strings = {chain.instrs[k].offset + _prefixes(chain.instrs[k].code):
                   (len(sr.elements), sr.cond) for k, sr in string_elements(chain).items()}
    out, k, seg_prefix = [], 0, None
    for _ in range(MAX_STARTS):
        op = decode(code, k, regs)
        if (op.cls in STRING_CLASSES or op.cls in BCD_CLASSES) and op.offset - len(tail) in strings:
            op.n, op.cond = strings[op.offset - len(tail)]
        if (op.cls != "prefix" and seg_prefix == 0x26 and op.ea is not None
                and op.cls in ("store", "store_imm")):
            lin = ((regs.get("DS1", 0) << 4) + op.ea) & 0xFFFFF
            if lin >= FSFR:
                op.ea = lin
        out.append((k, op))
        if op.cls == "halt":
            break
        execute(op, code, regs)
        seg_prefix = op.opcode if op.cls == "prefix" else None
        k = op.target if op.target is not None else k + op.length
    return out


def quantities_frozen(op) -> dict:
    s0, s1 = op.stack if op.stack else (None, None)
    q = {"ea": op.ea or 0, "port": op.port or 0, "sr": s0 or 0, "sw": s1 or 0,
         "count": op.count, "taken": int(op.target is not None), "target": op.target or 0}
    if op.cls.startswith("str_") or op.cls.startswith("bcd4s"):     # (WP79) the BCD strings
        q["string"] = (op.rep, op.ix, op.iy, op.port or 0, op.n, bool(op.cond))
    return q


def quantities(st: Start) -> dict:
    q = {"ea": st.ea, "port": st.port, "sr": st.sr, "sw": st.sw, "count": st.count,
         "taken": int(st.taken), "target": st.target if st.taken else 0}
    if st.string is not None:
        rep, ix, iy, port, n, ended = st.string
        q["string"] = (rep, ix, iy, port, n, ended)
        q["port"] = 0 if port is None else q["port"]
    return q


def agree(chain, chain_base: int, run: Run | None = None) -> list[str]:
    """Every start's timing quantities, the functional reference's against the frozen
    model's: [disagreement text] (empty: they agree on every start)."""
    run = run if run is not None else chain_run(chain, chain_base)
    fz = frozen_walk(chain, chain_base)
    bad = []
    if len(fz) != len(run.starts) and not run.trap:
        bad.append(f"{len(run.starts)} starts, the frozen walk {len(fz)}")
    for i, ((k, op), st) in enumerate(zip(fz, run.starts)):
        if k != st.pc:
            bad.append(f"start {i}: offset {st.pc}, frozen {k}")
            break
        a, b = quantities(st), quantities_frozen(op)
        if (op.cls.startswith("str_") or op.cls.startswith("bcd4s")) and "string" in b:
            b["port"] = a["port"] = 0
            if a["string"][3] is None:
                a["string"] = a["string"][:3] + (0,) + a["string"][4:]
        diff = {x: (a.get(x), b.get(x)) for x in set(a) | set(b) if a.get(x) != b.get(x)}
        if diff:
            bad.append(f"start {i} at {k} ({st.code[:op.length].hex()}): " + ", ".join(
                f"{x} {u!r} (frozen {v!r})" for x, (u, v) in sorted(diff.items())))
    return bad


# ---------------------------------------------------------------------------------- silicon

def silicon_cycles(rec: dict, code_len: int) -> list:
    """The data cycles of a silicon record after the prelude's POP PSW read: [(kind, address,
    data, nube)] (fetches: reads in the code's range; refreshes skipped)."""
    from .normalize import FLAG_IO, FLAG_NUBE, FLAG_READ, FLAG_REFRESH
    out, seen = [], False
    for row in rec["socket_trace"]:
        f, a = row["flags"], row["address"]
        if f & FLAG_REFRESH:
            continue
        rd, io = bool(f & FLAG_READ), bool(f & FLAG_IO)
        if not seen:
            seen = rd and not io and a == PRELUDE_STACK
            continue
        if rd and not io and CODE_BASE <= a < CODE_BASE + code_len + 0x40:
            continue
        kind = ("io_" if io else "") + ("read" if rd else "write")
        out.append((kind, a, row["data"] & 0xFFFF, bool(f & FLAG_NUBE)))
    return out


def _lanes(width: str) -> int:
    return {"word": 0xFFFF, "lo": 0x00FF, "hi": 0xFF00}[width]


def silicon_check(rec: dict, run: Run, chain) -> tuple[int, int, list]:
    """(cycles compared, equal, [mismatch text]): the reference's data cycles (the on-chip
    SFR stores left out) against silicon's, in order: kind, address and the datum on the
    cycle's lanes (a read's: the delivered word's)."""
    sil = silicon_cycles(rec, len(chain.code) + 0x200)
    mine = [c for c in run.cycles if not (c.kind == "write" and c.addr >= SFR_PAGE)]
    bad, eq = [], 0
    if len(sil) != len(mine):
        bad.append(f"{len(mine)} cycles, silicon {len(sil)}")
    for i, (c, s) in enumerate(zip(mine, sil)):
        kind, a, d, _ = s
        lanes = _lanes(c.width)
        v = c.rdata if c.kind.endswith("read") else c.data
        if kind != c.kind or a != c.addr or (d & lanes) != (v & lanes):
            bad.append(f"cycle {i}: {c.kind} {c.addr:05X} {c.width} {v & lanes:04X}, silicon "
                       f"{kind} {a:05X} {d & lanes:04X}")
        else:
            eq += 1
    return min(len(sil), len(mine)), eq, bad


# ---------------------------------------------------------------------------------- the CLI

def _work(args):
    fam, rec, silicon = args
    from .normalize import normalize
    from .types import Chain
    rid = rec["chain"]["id"]
    out = {"id": rid, "starts": 0, "bad": [], "nm": "", "trap": "", "sil": (0, 0, [])}
    try:
        s = normalize(rec)
        chain, base = s.chain, s.chain_base
    except Exception as e:                  # noqa: BLE001
        out["nm"] = f"normalize: {type(e).__name__}: {e}"
        return fam, out
    try:
        run = chain_run(chain, base)
    except NotModelled as e:
        out["nm"] = str(e)
        return fam, out
    out["starts"] = len(run.starts)
    out["trap"] = run.trap
    try:
        out["bad"] = agree(chain, base, run)
    except Exception as e:                  # noqa: BLE001
        out["bad"] = [f"frozen walk: {type(e).__name__}: {e}"]
    if silicon:
        out["sil"] = silicon_check(rec, run, chain)
    return fam, out


def agree_corpus(families, silicon: bool = False, jobs: int = 8, show: int = 0,
                 out=None) -> dict:
    """The agreement (and with silicon, the data check) over the families' corpus runs: the
    totals (runs, starts, bad: runs disagreeing, nm: not modelled, trap, scyc / seq: silicon
    cycles compared / equal, sbad: runs differing, first: the first disagreement's text);
    per family a line to out (a file) when given."""
    from multiprocessing import get_context

    from .normalize import load_runs
    tasks = [(f, rec, silicon) for f in families for rec in load_runs(f)]
    res: dict = {f: [] for f in families}
    with get_context("spawn").Pool(max(1, min(jobs, 8))) as pool:
        for fam, o in pool.imap_unordered(_work, tasks, chunksize=8):
            res[fam].append(o)
    tot = dict(runs=0, starts=0, bad=0, nm=0, trap=0, scyc=0, seq=0, sbad=0, first="")
    for f in families:
        rs = sorted(res[f], key=lambda o: o["id"])
        bad = [o for o in rs if o["bad"]]
        nm = [o for o in rs if o["nm"]]
        tr = [o for o in rs if o["trap"]]
        scyc = sum(o["sil"][0] for o in rs)
        seq = sum(o["sil"][1] for o in rs)
        sbad = [o for o in rs if o["sil"][2]]
        st = sum(o["starts"] for o in rs)
        if out is not None:
            print(f"{f:<5} {len(rs):>5} runs  starts {st}  disagree {len(bad)}  not modelled "
                  f"{len(nm)}  traps {len(tr)}" + (f"  silicon cycles {seq}/{scyc}, runs "
                                                    f"differing {len(sbad)}" if silicon else ""),
                  file=out)
            for o in bad[:show]:
                print(f"    {o['id']}: {o['bad'][0]}", file=out)
            for o in nm[:show]:
                print(f"    not modelled {o['id']}: {o['nm']}", file=out)
            for o in sbad[:show]:
                print(f"    silicon {o['id']}: {o['sil'][2][0]}", file=out)
        if not tot["first"]:
            for o in bad + nm + tr + sbad:
                tot["first"] = (f"{o['id']}: " + (o["bad"] or [o["nm"] or o["trap"]]
                                                  or o["sil"][2])[0])
                break
        for k, v in (("runs", len(rs)), ("starts", st), ("bad", len(bad)), ("nm", len(nm)),
                     ("trap", len(tr)), ("scyc", scyc), ("seq", seq), ("sbad", len(sbad))):
            tot[k] += v
    return tot


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m validation.v35s.chains.funcref",
                                description=__doc__.split("\n\n")[0])
    p.add_argument("--family", nargs="+", required=True)
    p.add_argument("--silicon", action="store_true",
                   help="also compare every data cycle's datum with the silicon record's")
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--show", type=int, default=5)
    args = p.parse_args(argv)
    tot = agree_corpus(args.family, args.silicon, args.jobs, args.show, sys.stdout)
    if len(args.family) > 1:
        print(f"all   {tot['runs']:>5} runs  starts {tot['starts']}  disagree {tot['bad']}  not "
              f"modelled {tot['nm']}  traps {tot['trap']}" + (
                  f"  silicon cycles {tot['seq']}/{tot['scyc']}, runs differing {tot['sbad']}"
                  if args.silicon else ""))
    return 1 if tot["bad"] or tot["sbad"] else 0


if __name__ == "__main__":
    sys.exit(main())
