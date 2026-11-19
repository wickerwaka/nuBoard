"""F4: the wait control word (WTC) per 128K block, READY per block (the f4_wtc* program set).

The data book (uPD70330/332 "Programmable Wait State Generation", figures 33/34; the V25's copy
names "n = 0 thru 6"): WTC is eight 2-bit fields; field n (bits 2n+1:2n), n = 0..5, sets the
waits of the 128K memory block n (n x 20000h); field 6 the top 256K (C0000h-FFFFFh, "the top two
blocks are programmed together as one unit"); field 7 (bits 15:14) the whole I/O space. A field
is 0, 1 or 2 waits, or 3: two waits plus the READY pin (PMC1 bit 7 selects P17 as READY).

The programs are measured on the socketed uPD70337 and run unchanged on the core v2 RTL in
simulation; every bus cycle's length is read from the lane's trace record (end - start):

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.wtc socket [NAME ...] [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.wtc sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.wtc report [NAME ...] [--ref socket] [-v]
    PYTHONPATH=host/src:. python3 -m validation.v35s.wtc repeat [NAME ...]     (socket / socket-2)
    PYTHONPATH=host/src:. python3 -m validation.v35s.wtc gate [NAME ...]       (socket / sim)
    PYTHONPATH=host/src:. python3 -m validation.v35s.wtc emit

A program is a list of windows. Each window stores a WTC value (and PMC1 / RFM where the
program says), announces itself (OUT FE40h, AW = the window's number), calls the program's probe
routine and closes (OUT FE42h): the trace is cut at these markers (self-synchronising), a
window's data cycles are matched against the list the generator kept (kind and address, per
instruction), and every read whose value the image fixes is compared by the program itself
(a mismatch ends in OUT FF02h). The image maps the sixteen 4K pages each side of the seven
block boundaries plus 00000h and FF000h, so the bytes just each side of every boundary are
backed (reads checked, code executed there).

    f4_wtc_d   data reads / writes (byte, word, a word straddling the boundary) each side of
               every boundary, IN / OUT at four ports
    f4_wtc_f   code executed across every boundary (a NOP sled) and in every block (stubs)
    f4_wtc_k   stack (PUSH / POP / CALL / BRK with SS:SP in each block, straddling), strings
               with source and destination in different blocks, read-modify-write, PUSH / POP mem
    f4_wtc_m   DMA (burst, memory to memory, TDMA) between blocks and across a boundary
    f4_wtc_r   READY: the d and f probes with field 3 in one block at a time, PMC1 bit 7 set and
               clear; the harness holds READY low 160 ticks after each column strobe
    f4_wtc_r0  the same program with READY never held (register 0Ah = 0)
    f4_wtc_x   the reset default; internal RAM / SFR accesses (executed in block 1, timed
               between markers); refresh cycles under every field
    f4_wtc_w   code executed across FFFFFh -> 00000h

Receipts: validation/v35s/receipts/f4-<name>-<backend>.json (the whole trace kept).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS_DIR = ROOT / "validation/v35s/programs"
RECEIPTS = ROOT / "validation/v35s/receipts"

CLK = 32                        # ticks per CPU clock (x_half 2, PRC at its reset fX/8)
ORG = 0x100
STACK_TOP = 0x0F00              # SS 0000h: the main stack, E00h-EFFh used
RESULTS = 0x0F00
M_BEGIN, M_END, M_SUB = 0xFE40, 0xFE42, 0xFE44
BOUNDS = [k * 0x20000 for k in range(1, 8)]
READY_TICKS = 160

FLAG_READ, FLAG_IO, FLAG_REFRESH, FLAG_UBE_N = 1, 2, 4, 8
FLAG_COL_A9, FLAG_STROBE, FLAG_PIN = 1 << 6, 1 << 7, 1 << 9

R16 = {"AW": 0, "CW": 1, "DW": 2, "BW": 3, "SP": 4, "BP": 5, "IX": 6, "IY": 7}
SREG = {"DS1": 0, "PS": 1, "SS": 2, "DS0": 3}
PFX = {"DS1": 0x26, "PS": 0x2E, "SS": 0x36, "DS0": 0x3E}


def field_of(addr):
    """The data book's field of a memory address: its 128K block, the top two together."""
    return min(addr >> 17, 6)


def wtc_fields(values):
    return sum((v & 3) << (2 * i) for i, v in enumerate(values))


def walk(f, on, off):
    return wtc_fields([on if i == f else off for i in range(8)])


P1 = wtc_fields([f % 3 for f in range(8)])          # 4924h: every field differs from its neighbours
P2 = wtc_fields([(f // 3) % 3 for f in range(8)])   # A540h: with P1 the pair names the field


def pat(addr):
    """The image's fill: a byte that differs between neighbours, pages and blocks."""
    return (addr * 7 + (addr >> 8) * 13 + (addr >> 12) * 29 + (addr >> 17) * 101 + 0x5A) & 0xFF


# ------------------------------------------------------------------ a small assembler
class Asm:
    """Machine code with a listing (emitted as DB lines with the mnemonic as the comment) and,
    per instruction, the data cycles it makes: groups of (kind, address), kinds mr mw ior iow."""

    def __init__(self, org=ORG):
        self.org, self.b, self.lines, self.labels, self.fix = org, bytearray(), [], {}, []
        self.groups = None              # the open probe routine's groups (None: not recording)

    def here(self):
        return self.org + len(self.b)

    def op(self, bs, text, cycles=None):
        self.lines.append((bytes(bs), text))
        self.b += bytes(bs)
        if cycles and self.groups is not None:
            self.groups.append((text, cycles))

    def label(self, name):
        self.labels[name] = self.here()
        self.lines.append((b"", name + ":"))

    def rel(self, opcode, label, text, wide=False):
        self.op(bytes(opcode) + bytes(2 if wide else 1), f"{text} {label}")
        self.fix.append((len(self.b), label, wide))

    def finish(self):
        for end, label, wide in self.fix:
            d = self.labels[label] - (self.org + end)
            if wide:
                self.b[end - 2:end] = (d & 0xFFFF).to_bytes(2, "little")
            else:
                if not -128 <= d <= 127:
                    raise ValueError(f"short branch to {label} out of range")
                self.b[end - 1] = d & 0xFF
        # the listing's bytes follow the fixed image
        pos, out = 0, []
        for bs, text in self.lines:
            out.append((bytes(self.b[pos:pos + len(bs)]), text))
            pos += len(bs)
        self.lines = out
        return bytes(self.b)

    # ---- instructions
    def mov_r(self, r, v):
        self.op([0xB8 + R16[r], v & 0xFF, v >> 8 & 0xFF], f"MOV {r}, {v:04X}h")

    def mov_sr(self, s, r="AW"):
        self.op([0x8E, 0xC0 | SREG[s] << 3 | R16[r]], f"MOV {s}, {r}")

    def seg(self, s, v):
        self.mov_r("AW", v)
        self.mov_sr(s)

    def sfr_w(self, off, v, word=False):
        """A store to the SFR at FFFxxh through DS1 = F000h (internal: no bus cycle)."""
        if word:
            self.op([0x26, 0xC7, 0x06, off, 0xFF, v & 0xFF, v >> 8], f"MOV word DS1:[FF{off:02X}h], {v:04X}h")
        else:
            self.op([0x26, 0xC6, 0x06, off, 0xFF, v], f"MOV byte DS1:[FF{off:02X}h], {v:02X}h")

    def out_w(self, port, v):
        self.mov_r("DW", port)
        self.mov_r("AW", v)
        self.op([0xEF], "OUT DW, AW")

    def nop(self, n=1):
        for _ in range(n):
            self.op([0x90], "NOP")


def mem_cycles(kind, addr, size):
    """The bus cycles of a `size`-byte access at linear addr: a word at an odd address is two
    byte cycles (the odd address, then the next)."""
    addr &= 0xFFFFF
    if size == 2 and addr & 1:
        return [(kind, addr), (kind, (addr + 1) & 0xFFFFF)]
    return [(kind, addr)]


class Probe:
    """Helpers that emit a data access and record its cycles. `ds0` is DS0's segment."""

    def __init__(self, a: Asm, image):
        self.a, self.image, self.ds0, self.n = a, image, 0, 0

    def set_ds0(self, seg):
        self.a.seg("DS0", seg)
        self.ds0 = seg

    def lin(self, off):
        return ((self.ds0 << 4) + off) & 0xFFFFF

    def check(self, word, value):
        a = self.a
        self.n = a.here()
        if word:
            a.op([0x3D, value & 0xFF, value >> 8], f"CMP AW, {value:04X}h")
        else:
            a.op([0x3C, value], f"CMP AL, {value:02X}h")
        a.rel([0x74], f"ok{self.n}", "BE")
        a.rel([0xE9], "fail", "BR", wide=True)
        a.label(f"ok{self.n}")

    def rd(self, off, word=False, check=True):
        lin = self.lin(off)
        self.a.op([0xA1 if word else 0xA0, off & 0xFF, off >> 8],
                  f"MOV {'AW' if word else 'AL'}, [{off:04X}h]   ; {lin:05X}",
                  mem_cycles("mr", lin, 2 if word else 1))
        if check:
            v = self.image(lin) | (self.image((lin + 1) & 0xFFFFF) << 8 if word else 0)
            self.check(word, v)

    def wr(self, off, word=False):
        lin = self.lin(off)
        self.a.op([0xA3 if word else 0xA2, off & 0xFF, off >> 8],
                  f"MOV [{off:04X}h], {'AW' if word else 'AL'}   ; {lin:05X}",
                  mem_cycles("mw", lin, 2 if word else 1))

    def io(self, port):
        a = self.a
        a.mov_r("DW", port)
        a.op([0xEE], f"OUT DW, AL   ; {port:04X}", [("iow", port)])
        a.op([0xEC], f"IN AL, DW   ; {port:04X}", [("ior", port)])
        a.op([0xEF], f"OUT DW, AW   ; {port:04X}", mem_cycles("iow", port, 2))
        a.op([0xED], f"IN AW, DW   ; {port:04X}", mem_cycles("ior", port, 2))


# ------------------------------------------------------------------ the image
def base_image(sleds=True):
    """The sixteen pages: the fill, and (sleds) per boundary B a NOP sled B-10h..B+0Fh with RETF
    at B+10h, and stubs (8 NOPs, RETF) at B-80h and B+80h."""
    pages = [0x00, 0xFF] + [p for b in BOUNDS for p in ((b >> 12) - 1, b >> 12)]
    mem = {}
    for p in pages:
        for o in range(0x1000):
            mem[p << 12 | o] = pat(p << 12 | o)
    code = []
    if sleds:
        for b in BOUNDS:
            for a in range(b - 0x10, b + 0x10):
                mem[a] = 0x90
            mem[b + 0x10] = 0xCB
            code.append((b - 0x10, b + 0x11))
            for s in (b - 0x80, b + 0x80):
                for a in range(s, s + 8):
                    mem[a] = 0x90
                mem[s + 8] = 0xCB
                code.append((s, s + 9))
    return mem, code


SEG = lambda b: (b >> 4) - 0x10         # noqa: E731  the segment whose offset 0100h is boundary b


# ------------------------------------------------------------------ the probe routines
def sub_data(a: Asm, mem):
    """Reads and writes each side of every boundary, and at 00020h / FF020h; IN / OUT."""
    p = Probe(a, lambda x: mem[x])
    p.set_ds0(0x0000)
    p.rd(0x0020)
    p.rd(0x0022, word=True)
    p.wr(0x0030)
    p.wr(0x0032, word=True)
    for b in BOUNDS:
        p.set_ds0(SEG(b))
        p.rd(0x00FE)                    # B-2
        p.rd(0x00FF)                    # B-1 (odd)
        p.rd(0x0100)                    # B
        p.rd(0x00FC, word=True)         # B-4
        p.rd(0x0102, word=True)         # B+2
        p.rd(0x00FF, word=True)         # B-1 / B: two byte cycles
        p.wr(0x00FF, word=True)         # the same word back (the image is kept)
        p.wr(0x00D0)                    # B-30h
        p.wr(0x0130)                    # B+30h
        p.wr(0x00D2, word=True)
        p.wr(0x0132, word=True)
    p.set_ds0(0xFF00)
    p.rd(0x0020)
    p.rd(0x0022, word=True)
    p.wr(0x0030)
    p.wr(0x0032, word=True)
    for port in (0x0040, 0x8000, 0xFE80, 0x0041):
        p.io(port)


def sub_fetch(a: Asm, mem):
    """Far calls to the sled across every boundary and the stubs each side of it."""
    for b in BOUNDS:
        for off in (0x00F0, 0x0080, 0x0180):
            s = SEG(b)
            a.op([0x9A, off & 0xFF, off >> 8, s & 0xFF, s >> 8], f"CALL FAR {s:04X}h:{off:04X}h")


def sub_kinds(a: Asm, mem):
    """Stack, strings, read-modify-write, PUSH / POP mem, BRK."""
    a.op([0xFC], "CLR1 DIR")
    a.op([0x8B, 0xEC], "MOV BP, SP")

    def stack(seg, sp):
        a.seg("SS", seg)
        a.mov_r("SP", sp)

    def home():
        a.mov_r("AW", 0)
        a.mov_sr("SS")
        a.op([0x8B, 0xE5], "MOV SP, BP")

    for b in BOUNDS:
        s = SEG(b)
        for sp in (0x0120, 0x00F0, 0x0101):
            stack(s, sp)
            lin = (s << 4) + sp - 2
            a.op([0x50], f"PUSH AW   ; {lin:05X}", mem_cycles("mw", lin, 2))
            a.op([0x59], f"POP CW   ; {lin:05X}", mem_cycles("mr", lin, 2))
        stack(s, 0x0140)
        lin = (s << 4) + 0x013E
        a.rel([0xE8], "kret", "CALL", wide=True)
        a.groups.append(("CALL / RET", mem_cycles("mw", lin, 2) + mem_cycles("mr", lin, 2)))
        home()
    # BRK 3 with the stack in blocks 2 and 6 (top half): the vector at 0000Ch, three pushes
    for b in (BOUNDS[1], BOUNDS[6]):
        stack(SEG(b), 0x0160)
        lin = b + 0x60
        a.op([0xCC], f"BRK 3   ; stack {lin - 6:05X}",
             [("mr", 0x0000C), ("mr", 0x0000E)] + [("mw", lin - 2 * i) for i in (1, 2, 3)]
             + [("mr", lin - 2 * i) for i in (3, 2, 1)])
        home()
    # strings: source DS0:IX in block of boundary i, destination DS1:IY in block of boundary j
    p = Probe(a, lambda x: mem[x])

    def string(i, j, ix, iy, word, rep):
        p.set_ds0(SEG(BOUNDS[i - 1]))
        a.seg("DS1", SEG(BOUNDS[j - 1]))
        a.mov_r("IX", ix)
        a.mov_r("IY", iy)
        n = rep or 1
        if rep:
            a.mov_r("CW", rep)
        src, dst = (SEG(BOUNDS[i - 1]) << 4) + ix, (SEG(BOUNDS[j - 1]) << 4) + iy
        cyc = []
        for e in range(n):
            w = 2 if word else 1
            cyc += mem_cycles("mr", src + e * w, w) + mem_cycles("mw", dst + e * w, w)
        a.op(([0xF3] if rep else []) + [0xA5 if word else 0xA4],
             f"{'REP ' if rep else ''}MOVBK{'W' if word else ''}   ; {src:05X} -> {dst:05X}", cyc)

    for i, j in ((1, 5), (6, 2), (3, 4), (7, 1)):
        string(i, j, 0x0140, 0x0150, False, 0)
        string(i, j, 0x0142, 0x0152, True, 0)
        string(i, j, 0x0144, 0x0154, False, 3)
        string(i, j, 0x0148, 0x0158, True, 2)
    string(2, 5, 0x00FE, 0x00FE, False, 4)      # bytes across both boundaries
    string(4, 7, 0x00FD, 0x00FD, True, 2)       # odd words: B-3/B-2, B-1/B
    string(3, 3, 0x00FC, 0x0100, True, 2)       # source below, destination above one boundary
    a.seg("DS1", 0xF000)
    # read-modify-write, PUSH mem, POP mem
    for i, j in ((1, 4), (5, 2), (7, 3)):
        b, sb = BOUNDS[i - 1], BOUNDS[j - 1]
        p.set_ds0(SEG(b))
        a.op([0xFE, 0x06, 0x60, 0x01], f"INC byte [0160h]   ; {b + 0x60:05X}",
             [("mr", b + 0x60), ("mw", b + 0x60)])
        a.op([0x01, 0x06, 0xFF, 0x00], f"ADD [00FFh], AW   ; {b - 1:05X}",
             mem_cycles("mr", b - 1, 2) + mem_cycles("mw", b - 1, 2))
        stack(SEG(sb), 0x0170)
        a.op([0xFF, 0x36, 0x64, 0x01], f"PUSH word [0164h]   ; {b + 0x64:05X} -> {sb + 0x6E:05X}",
             [("mr", b + 0x64), ("mw", sb + 0x6E)])
        a.op([0x8F, 0x06, 0x68, 0x01], f"POP word [0168h]   ; {sb + 0x6E:05X} -> {b + 0x68:05X}",
             [("mr", sb + 0x6E), ("mw", b + 0x68)])
        home()


def sub_dma(a: Asm, mem):
    """Two bursts (memory to memory, TDMA, channel 0, bytes): 40000h-2.. -> C0000h-2.. (both
    across a boundary) and A0040h.. -> 1FFC0h.. ; the channel block at FFE00h: SAR, DAR, DARH,
    SARH, TC. The cycles are not listed (the count is the silicon's)."""
    for sar, sarh, dar, darh in ((0x0FFE, 0x3F, 0x0FFE, 0xBF), (0x0040, 0xA0, 0x0FC0, 0x1F)):
        a.sfr_w(0xAC, 0x47)
        for off, v, word in ((0x00, sar, True), (0x02, dar, True), (0x05, sarh, False),
                             (0x04, darh, False), (0x06, 0x0004, True)):
            if word:
                a.op([0x26, 0xC7, 0x06, off, 0xFE, v & 0xFF, v >> 8], f"MOV word DS1:[FE{off:02X}h], {v:04X}h")
            else:
                a.op([0x26, 0xC6, 0x06, off, 0xFE, v], f"MOV byte DS1:[FE{off:02X}h], {v:02X}h")
        a.sfr_w(0xA0, 0x11)
        a.sfr_w(0xA1, 0x8C)
        a.mov_r("CW", 40)
        a.op([0xE2, 0xFE], "DBNZ $")
        a.sfr_w(0xA1, 0x00)


def sub_wrap(a: Asm, mem):
    a.op([0x9A, 0x05, 0x00, 0xFF, 0xFF], "CALL FAR FFFFh:0005h")


def sub_refresh(a: Asm, mem):
    a.mov_r("CW", 60)
    a.op([0xE2, 0xFE], "DBNZ $")


X_STUB = 0x20200        # f4_wtc_x: the internal-access routine, executed in block 1


def x_stub():
    """Markers (OUT FE44h, AW = n) around runs of eight internal accesses: n = 0 internal RAM
    read (FFE40h), 1 internal RAM write, 2 SFR read (WTC), 3 SFR write (MD0), 4 FFFFFh (IDB)
    read, 5 nothing (32 NOPs: the control), 6 SFR write (P0's latch; the port is an input)."""
    a = Asm(X_STUB)
    a.mov_r("DW", M_SUB)
    runs = ([0x26, 0xA0, 0x40, 0xFE], [0x26, 0xA2, 0x40, 0xFE], [0x26, 0xA0, 0xE8, 0xFF],
            [0x26, 0xA2, 0x82, 0xFF], [0x26, 0xA0, 0xFF, 0xFF], [0x90, 0x90, 0x90, 0x90],
            [0x26, 0xA2, 0x00, 0xFF])
    names = ("MOV AL, DS1:[FE40h]", "MOV DS1:[FE40h], AL", "MOV AL, DS1:[FFE8h]",
             "MOV DS1:[FF82h], AL", "MOV AL, DS1:[FFFFh]", "NOP x4", "MOV DS1:[FF00h], AL")
    for n, (bs, nm) in enumerate(zip(runs, names)):
        a.mov_r("AW", n)
        a.op([0xEF], "OUT DW, AW")
        for _ in range(8):
            a.op(bs, nm)
    a.mov_r("AW", len(runs))
    a.op([0xEF], "OUT DW, AW")
    # a REP MOVBK of 32 bytes inside the internal RAM (FFE40h -> FFE60h): no bus cycle and no
    # fetch while it runs, between markers 8 and 9 (7 .. 8 is its setup)
    a.seg("DS0", 0xF000)
    a.mov_r("IX", 0xFE40)
    a.mov_r("IY", 0xFE60)
    a.mov_r("CW", 32)
    a.op([0xFC], "CLR1 DIR")
    a.mov_r("AW", len(runs) + 1)
    a.op([0xEF], "OUT DW, AW")
    a.op([0xF3, 0xA4], "REP MOVBK   ; FFE40 -> FFE60, 32 bytes, on-chip")
    a.mov_r("AW", len(runs) + 2)
    a.op([0xEF], "OUT DW, AW")
    a.nop(4)
    a.op([0xCB], "RETF")
    return a


def sub_internal(a: Asm, mem):
    a.op([0x9A, X_STUB & 0xFF, X_STUB >> 8 & 0xFF, 0x00, X_STUB >> 16 << 4], "CALL FAR 2000h:0200h")


# ------------------------------------------------------------------ programs
class Window:
    def __init__(self, wtc, sub, pmc1=0x00, rfm=0xEC, note=""):
        self.wtc, self.sub, self.pmc1, self.rfm, self.note = wtc, sub, pmc1, rfm, note


class Program:
    def __init__(self, name, windows, note="", ready=0, sleds=True, share=None):
        self.name, self.windows, self.note, self.ready = name, windows, note, ready
        self.sleds, self.share = sleds, share
        self._built = None

    def build(self):
        if self._built:
            return self._built
        mem, code = base_image(self.sleds)
        a = Asm()
        a.op([0xFA], "DI")
        a.mov_r("AW", 0)
        a.mov_sr("SS")
        a.mov_r("SP", STACK_TOP)
        a.mov_sr("DS0")
        a.seg("DS1", 0xF000)
        # the reset state, before anything is stored: WTC and RFM into the result words (the
        # stores are bus cycles at the reset default's waits)
        a.op([0x26, 0xA1, 0xE8, 0xFF], "MOV AW, DS1:[FFE8h]   ; WTC at reset")
        a.op([0x2E, 0xA3, RESULTS & 0xFF, RESULTS >> 8], f"MOV PS:[{RESULTS:04X}h], AW")
        a.op([0x26, 0xA0, 0xE1, 0xFF], "MOV AL, DS1:[FFE1h]   ; RFM at reset")
        a.op([0x2E, 0xA2, RESULTS + 2 & 0xFF, RESULTS >> 8], f"MOV PS:[{RESULTS + 2:04X}h], AL")
        pmc1, rfm = 0x00, 0xFC
        for k, w in enumerate(self.windows):
            a.lines.append((b"", f"; ---- window {k}: WTC {w.wtc:04X}h PMC1 {w.pmc1:02X}h RFM {w.rfm:02X}h"
                                 f" {w.sub.__name__} {w.note}"))
            if w.rfm != rfm:
                a.sfr_w(0xE1, w.rfm)
                rfm = w.rfm
            if w.pmc1 != pmc1:
                a.sfr_w(0x0A, w.pmc1)
                pmc1 = w.pmc1
            a.sfr_w(0xE8, w.wtc, word=True)
            a.out_w(M_BEGIN, k)
            a.rel([0xE8], w.sub.__name__, "CALL", wide=True)
            a.out_w(M_END, k)
        a.sfr_w(0xE8, 0xFFFF, word=True)
        a.sfr_w(0x0A, 0x00)
        a.sfr_w(0xE1, 0xEC)
        a.mov_r("DW", 0xFF00)
        a.op([0xEE], "OUT DW, AL")
        a.op([0xF4], "HALT")
        a.label("done")
        a.rel([0xEB], "done", "BR")
        a.label("fail")
        a.mov_r("DW", 0xFF02)
        a.op([0xEE], "OUT DW, AL")
        a.op([0xF4], "HALT")
        a.label("fspin")
        a.rel([0xEB], "fspin", "BR")
        a.label("kret")
        a.op([0xC3], "RET")
        a.label("brk3")
        a.op([0xCF], "RETI")
        groups = {}
        for sub in dict.fromkeys(w.sub for w in self.windows):
            a.label(sub.__name__)
            a.groups = []
            sub(a, mem)
            groups[sub.__name__] = a.groups
            a.groups = None
            a.op([0xC3], "RET")
        text = a.finish()
        if ORG + len(text) > 0xE00:
            raise ValueError(f"{self.name}: {len(text)} bytes of code reach the stack")
        for i, v in enumerate(text):
            mem[ORG + i] = v
        main = [(ORG, ORG + len(text)), (0xFFFF0, 0xFFFF5)]
        for i, v in enumerate(a.labels["brk3"].to_bytes(2, "little") + b"\0\0"):
            mem[0x0000C + i] = v
        if any(w.sub is sub_internal for w in self.windows):
            xs = x_stub()
            xt = xs.finish()
            for i, v in enumerate(xt):
                mem[X_STUB + i] = v
            code.append((X_STUB, X_STUB + len(xt)))
            a.lines.append((b"", f"; the routine at {X_STUB:05X}h (CALL FAR 2000h:0200h):"))
            a.lines += [(b"", "; " + t) for _, t in xs.lines]
        if any(w.sub is sub_wrap for w in self.windows):
            for x in list(range(0xFFFF5, 0x100000)) + list(range(0x00000, 0x0000C)):
                mem[x] = 0x90
            mem[0x0000C] = 0xCB         # RETF (no BRK in this program)
            code += [(0xFFFF5, 0x100000), (0, 0x0000D)]
        for i, v in enumerate(bytes([0xEA, ORG & 0xFF, ORG >> 8, 0, 0])):
            mem[0xFFFF0 + i] = v
        segments = {}
        for p in sorted({x >> 12 for x in mem}):
            segments[p << 12] = bytes(mem[p << 12 | o] for o in range(0x1000))
        self._built = dict(text=text, lines=a.lines, segments=segments, main=main, aux=code,
                           groups=groups, labels=a.labels)
        return self._built

    def source(self):
        b = self.build()
        out = [f"; {self.name}: {self.note}",
               "; Generated by validation/v35s/wtc.py emit (python -m validation.v35s.wtc emit): the bytes",
               "; are the generator's; the image also holds the fill, the sleds and the stubs (wtc.py",
               "; base_image) in the pages each side of every 128K boundary."]
        for bs, text in b["lines"]:
            if not bs:
                out.append(text)
            else:
                out.append("    DB " + ", ".join(f"{v:02X}h" if v < 0xA0 else f"0{v:02X}h" for v in bs)
                           + f"    ; {text}")
        return "\n".join(out) + "\n"


def W(wtcs, sub, **kw):
    return [Window(w, sub, **kw) for w in wtcs]


UNIFORM = [0x0000, 0x5555, 0xAAAA, 0xFFFF]
WALK2 = [walk(f, 2, 0) for f in range(8)]
WALK1 = [walk(f, 1, 2) for f in range(8)]


def sub_all(a, mem):
    sub_data(a, mem)
    sub_fetch(a, mem)


def programs():
    rdy = (W([0xFFFF, 0xAAAA, 0x0000], sub_all, pmc1=0x80)
           + W([walk(f, 3, 2) for f in range(8)], sub_all, pmc1=0x80)
           + W([walk(f, 3, 0) for f in range(8)], sub_all, pmc1=0x80)
           + W([0xFFFF] + [walk(f, 3, 0) for f in range(8)], sub_all, pmc1=0x00))
    x = (W([0x0000] + WALK2 + [0xFFFF], sub_internal)
         + W([0x0000] + WALK2 + [0xFFFF, 0x5555, P1], sub_refresh, rfm=0xF0)
         + W([0x0000, 0x5555, walk(0, 0, 2)], sub_refresh, rfm=0xF8)
         + W([0x0000, 0xAAAA], sub_refresh, rfm=0xF4))
    progs = [
        Program("f4_wtc_d", W(UNIFORM + [P1, P2] + WALK2 + WALK1, sub_data),
                "WTC per block: data reads and writes each side of every 128K boundary, IN / OUT"),
        Program("f4_wtc_f", W(UNIFORM + [P1, P2] + WALK2 + WALK1, sub_fetch),
                "WTC per block: code executed across every boundary and in every block"),
        Program("f4_wtc_k", W([0x0000, P1, P2] + WALK2, sub_kinds),
                "WTC per block: stack, strings between blocks, read-modify-write, BRK"),
        Program("f4_wtc_m", W([0x0000, P1, P2] + WALK2[:7], sub_dma),
                "WTC per block: DMA bursts between blocks and across a boundary", sleds=False),
        Program("f4_wtc_r", rdy, "READY per block (READY held low 160 ticks after each column "
                                 "strobe): field 3 in one block at a time, PMC1 bit 7 set / clear",
                ready=READY_TICKS),
        Program("f4_wtc_r0", rdy, "f4_wtc_r's program with READY never held", share="f4_wtc_r"),
        Program("f4_wtc_x", x, "the reset default; internal RAM / SFR accesses; refresh cycles"),
        Program("f4_wtc_w", W([0x0000, P1, P2, walk(0, 2, 0), walk(6, 2, 0), walk(6, 1, 2)], sub_wrap),
                "code executed across FFFFFh -> 00000h", sleds=False),
    ]
    return {p.name: p for p in progs}


# ------------------------------------------------------------------ running
def receipt_path(name, backend):
    return RECEIPTS / f"f4-{name}-{backend}.json"


def load(name, backend):
    return json.loads(receipt_path(name, backend).read_text())


def run_one(harness, prog, lane, limit=60_000_000):
    b = prog.build()
    harness.debug.write16(0x0A, prog.ready)
    mode = "socket" if lane == "socket" else "model"
    harness.load(b["segments"])
    result = harness.run(mode, limit)
    trace = list(result[f"{lane}_trace"])
    total, replay = result[f"{lane}_total"], []
    for start in range(2048, total, 2048):
        harness.load(b["segments"])
        window = harness.run(mode, limit, capture_start=start)
        for field in ("total", "signature"):
            if window[f"{lane}_{field}"] != result[f"{lane}_{field}"]:
                replay.append(f"{field} changed at window {start}")
        trace.extend(window[f"{lane}_trace"])
    harness.debug.write16(0x0A, 0)
    rows = [[t["start"], t["address"], t["data"], t["flags"], t["end"], t["strobe"]] for t in trace]
    return {
        "program": prog.name, "note": prog.note, "ready_ticks": prog.ready,
        "program_sha256": hashlib.sha256(b["text"]).hexdigest(),
        "image_sha256": hashlib.sha256(json.dumps(
            {f"{a:05X}": d.hex() for a, d in sorted(b["segments"].items())}).encode()).hexdigest(),
        "passed": result["passed"], "status": result["status"], "timeout": result["timeout"],
        "total": total, "signature": result[f"{lane}_signature"], "replay": replay,
        "results": harness.read_memory(lane, RESULTS, 4).hex(), "trace": rows,
    }


def run_set(names, backend, tag, progs):
    from .traps import _board, _close_board, _sim, _stim
    lane = "socket" if backend == "socket" else "model"
    if backend == "socket":
        transport, harness = _board()
    try:
        for name in names:
            prog = progs[name]
            if backend != "socket":
                transport, harness = _sim()
            try:
                _stim(harness, prog)
                rec = run_one(harness, prog, lane)
            finally:
                if backend != "socket":
                    transport.close()
            rec.update(backend=backend, date=datetime.datetime.now().isoformat(timespec="seconds"))
            if backend == "socket":
                rec.update(cpu="uPD70337L-8", x_half=2)
            else:
                rec.update(core="v35", binary=os.environ.get(
                    "V35_SIM_BINARY", "build/fpga/v35s/verilator-direct-v35"))
            receipt_path(name, backend + tag).write_text(json.dumps(rec, separators=(",", ":")) + "\n")
            print(f"{name}: {backend}{tag} {'PASS' if rec['passed'] else 'FAIL'} "
                  f"status=0x{rec['status']:04x} total={rec['total']} records={len(rec['trace'])} "
                  f"replay={rec['replay']} results={rec['results']}", flush=True)
    finally:
        if backend == "socket":
            _close_board(transport, harness)


# ------------------------------------------------------------------ reading a trace
def waits_of(row):
    """A record's waits: its length is (2 + waits) clocks + 1 tick."""
    return round((row[4] - row[0] - 1) / CLK) - 2


def classify(rec, prog):
    """Per record (pin records dropped): (kind, window, row). Kinds: fetch mr mw ior iow refresh
    idle; window: None before the first begin marker, -1 between windows, else the number.
    A memory read is a fetch in the program's own text always, and in the sleds / stubs (the
    image's other code) once the window's listed data cycles have all been seen (f4_wtc_r reads
    the sleds' bytes as data before it executes them)."""
    b = prog.build()
    inr = lambda a, rs: any(lo <= a < hi + 12 for lo, hi in rs)     # noqa: E731
    out, k, left = [], None, 0
    for row in rec["trace"]:
        f = row[3]
        if f & FLAG_PIN:
            continue
        if f & FLAG_REFRESH:
            kind = "refresh"
        elif not f & FLAG_STROBE:
            kind = "idle"
        elif f & FLAG_IO:
            kind = "ior" if f & FLAG_READ else "iow"
        elif not f & FLAG_READ:
            kind = "mw"
        elif inr(row[1], b["main"]) or (left <= 0 and inr(row[1], b["aux"])):
            kind = "fetch"
        else:
            kind = "mr"
        if kind == "iow" and row[1] == M_BEGIN:
            k = row[2]
            left = (sum(len(c) for _, c in b["groups"][prog.windows[k].sub.__name__])
                    if k < len(prog.windows) else 0)
        elif kind == "iow" and row[1] == M_END:
            k = -1
        elif kind in ("mr", "mw", "ior", "iow") and not is_own(kind, row[1]):
            left -= 1
        out.append((kind, k, row))
    return out


def is_own(kind, addr):
    """The frame's own cycles (not a probe's): the main stack, the result words, the markers."""
    return ((kind in ("mr", "mw") and 0xE00 <= addr < RESULTS + 0x10)
            or (kind == "iow" and addr in (M_BEGIN, M_END, M_SUB)))


def cycles(rec, prog):
    """Per window: [(kind, address, waits, row)]; and the same before the first window."""
    wins, head = {}, []
    for kind, k, row in classify(rec, prog):
        if kind == "iow" and row[1] in (M_BEGIN, M_END):
            if row[1] == M_BEGIN:
                wins[k] = []
            continue
        item = (kind, row[1], waits_of(row), row)
        if k is None:
            head.append(item)
        elif k >= 0:
            wins[k].append(item)
    return wins, head


def match_groups(cyc, groups):
    """The window's data cycles (mr mw ior iow, in order) against the generator's groups: each
    instruction's cycles as a multiset. Returns the mismatches."""
    data = [(k, a) for k, a, w, r in cyc if k in ("mr", "mw", "ior", "iow") and not is_own(k, a)]
    bad, pos = [], 0
    for text, want in groups:
        got = data[pos:pos + len(want)]
        if Counter(got) != Counter(want):
            bad.append(f"{text}: expected {[(k, hex(a)) for k, a in want]}, "
                       f"got {[(k, hex(a)) for k, a in got]}")
        pos += len(want)
    if pos != len(data):
        bad.append(f"{len(data) - pos} data cycles beyond the list: "
                   f"{[(k, hex(a)) for k, a in data[pos:pos + 6]]}")
    return bad


def ready_extra(cycs, prog):
    """The waits a READY-governed cycle (field 3, PMC1 bit 7) has, per kind: read from the
    program's window with WTC FFFFh and PMC1 80h (the most common value of each kind)."""
    for k, w in enumerate(prog.windows):
        if w.wtc == 0xFFFF and w.pmc1 & 0x80 and k in cycs:
            by = {}
            for kind, a, n, r in cycs[k]:
                by.setdefault(kind, Counter())[n] += 1
            return {kind: c.most_common(1)[0][0] for kind, c in by.items()}, \
                   {kind: dict(c) for kind, c in by.items()}
    return {}, {}


def predict(kind, addr, w, extra, select):
    """The waits of a cycle under a selection rule. select: 'block' (the data book: memory by
    the address's block, I/O field 7) or 'field0' (memory field 0, I/O field 7)."""
    if kind in ("ior", "iow"):
        f = 7
    else:
        f = field_of(addr) if select == "block" else 0
    v = w.wtc >> (2 * f) & 3
    if v < 3:
        return v
    return extra.get(kind, 2) if w.pmc1 & 0x80 else 2


def report(name, backend, progs, verbose=False):
    prog = progs[name]
    rec = load(name, backend)
    b = prog.build()
    cycs, head = cycles(rec, prog)
    extra, spread = ready_extra(cycs, prog)
    print(f"{name} [{backend}]: {'PASS' if rec['passed'] else 'FAIL'} total {rec['total']}, "
          f"{len(cycs)}/{len(prog.windows)} windows, replay {rec['replay']}, "
          f"reset WTC/RFM words {rec['results']}")
    hw = Counter((k, w) for k, a, w, r in head)
    print(f"  before the first window (reset default FFFFh, PMC1 00h): "
          + ", ".join(f"{k} {w}w x{n}" for (k, w), n in sorted(hw.items())))
    if extra:
        print(f"  READY-governed waits by kind (window WTC FFFFh, PMC1 80h): {spread}")
    tot = {"block": [0, 0], "field0": [0, 0]}
    for k, w in enumerate(prog.windows):
        if k not in cycs:
            print(f"  window {k}: missing")
            continue
        c = cycs[k]
        bad = match_groups(c, b["groups"][w.sub.__name__]) if b["groups"][w.sub.__name__] else []
        line = f"  w{k:<2} WTC {w.wtc:04X} PMC1 {w.pmc1:02X} RFM {w.rfm:02X}:"
        res = {}
        for sel in ("block", "field0"):
            miss = [(kind, a, n, predict(kind, a, w, extra, sel)) for kind, a, n, r in c
                    if kind in ("mr", "mw", "ior", "iow", "fetch")
                    and n != predict(kind, a, w, extra, sel)]
            n_all = sum(1 for kind, a, n, r in c if kind in ("mr", "mw", "ior", "iow", "fetch"))
            res[sel] = miss
            tot[sel][0] += n_all - len(miss)
            tot[sel][1] += n_all
            line += f" {sel} {n_all - len(miss)}/{n_all}"
        ref = Counter(n for kind, a, n, r in c if kind == "refresh")
        if ref:
            line += f" refresh waits {dict(ref)}"
        if bad:
            line += f" SEQUENCE {len(bad)}"
        print(line)
        for x in bad[:4]:
            print("      " + x)
        for sel in ("block",):
            for kind, a, n, p in res[sel][:6 if not verbose else 1000]:
                print(f"      not {sel}: {kind} {a:05X} measured {n} predicted {p}")
        if verbose:
            by = {}
            for kind, a, n, r in c:
                if kind in ("mr", "mw", "fetch"):
                    by.setdefault((kind, field_of(a)), Counter())[n] += 1
                elif kind in ("ior", "iow"):
                    by.setdefault((kind, 7), Counter())[n] += 1
            print("      " + "  ".join(f"{kind}/f{f}:{dict(cn)}" for (kind, f), cn in sorted(by.items())))
    for sel in tot:
        print(f"  rule '{sel}': {tot[sel][0]} of {tot[sel][1]} cycles as predicted")
    if any(w.sub is sub_internal for w in prog.windows):
        internal_report(prog, cycs)
    return tot


def internal_report(prog, cycs):
    """f4_wtc_x: ticks from each FE44h marker's end to the next one's start, per window."""
    print("  internal accesses (ticks between the routine's markers: iRAM rd, iRAM wr, SFR rd, "
          "SFR wr MD0, FFFFFh rd, NOPs, SFR wr P0, (setup), REP MOVBK x32 on-chip) and the bus "
          "cycles between them:")
    for k, w in enumerate(prog.windows):
        if w.sub is not sub_internal or k not in cycs:
            continue
        marks = [(i, r) for i, (kind, a, n, r) in enumerate(cycs[k]) if kind == "iow" and a == M_SUB]
        gaps, between = [], []
        for (i, r), (j, s) in zip(marks, marks[1:]):
            gaps.append(s[0] - r[4])
            between.append(Counter(kind for kind, a, n, rr in cycs[k][i + 1:j] if kind != "refresh"))
        kinds = set()
        for bc in between:
            kinds |= set(bc)
        print(f"    w{k:<2} WTC {w.wtc:04X}: {gaps}  cycles between: {sorted(kinds)}; "
              f"fetches {[bc.get('fetch', 0) for bc in between]}")


# ------------------------------------------------------------------ comparing two receipts
def norm(rec, prog, strobe=False):
    """The comparable form of a trace: per non-refresh record (kind, address, data, waits,
    window) (IN data and nothing else masked); refresh cycles' waits apart."""
    rows, refresh = [], []
    for kind, k, r in classify(rec, prog):
        if kind == "refresh":
            refresh.append(waits_of(r))
            continue
        data = 0 if kind == "ior" else r[2]
        rows.append((kind, r[1], data, waits_of(r)) + ((r[5],) if strobe else ()) + (k,))
    return rows, refresh


def compare(name, ref, cand, progs, strobe=False):
    prog = progs[name]
    a, b = load(name, ref), load(name, cand)
    ra, fa = norm(a, prog, strobe)
    rb, fb = norm(b, prog, strobe)
    if a["program_sha256"] != b["program_sha256"] or a["image_sha256"] != b["image_sha256"]:
        print(f"{name}: the receipts are of different programs")
        return False
    same = ra == rb
    line = (f"{name}: {ref} / {cand}: {'EQUAL' if same else 'DIFFER'} "
            f"({len(ra)} / {len(rb)} cycles; passed {a['passed']} / {b['passed']}; "
            f"refresh cycles {len(fa)} / {len(fb)}, waits {dict(Counter(fa))} / {dict(Counter(fb))})")
    print(line)
    if not same:
        i = next((i for i, (x, y) in enumerate(zip(ra, rb)) if x != y), min(len(ra), len(rb)))
        k = (ra[i] if i < len(ra) else ra[-1])[-1]
        w = prog.windows[k] if k is not None and 0 <= k < len(prog.windows) else None
        fmt = lambda x: f"{x[0]} {x[1]:05X} data {x[2]:04X} waits {x[3]}" + (f" strobe+{x[4]}" if strobe else "")  # noqa: E731
        print(f"  first difference at cycle {i}"
              + (f", window {k} (WTC {w.wtc:04X}h PMC1 {w.pmc1:02X}h, {w.sub.__name__})" if w else
                 (" (before the first window)" if k is None else " (between windows)")) + ":")
        print(f"    {ref}: {fmt(ra[i]) if i < len(ra) else 'end'}")
        print(f"    {cand}: {fmt(rb[i]) if i < len(rb) else 'end'}")
        ndiff = sum(1 for x, y in zip(ra, rb) if x != y)
        print(f"  {ndiff} of {min(len(ra), len(rb))} aligned cycles differ")
    return same


def compare_windows(name, ref, cand, progs):
    """The gate's comparison: window by window (the trace cut at the markers, so a difference
    in one window's prefetch does not shift the next). A window is EQUAL when its data cycles
    (kind, address, data, waits; IN data masked) are the same sequence and every fetched address
    has the same waits; the first differing cycle of each differing window is printed."""
    prog = progs[name]
    a, b = load(name, ref), load(name, cand)
    if a["program_sha256"] != b["program_sha256"] or a["image_sha256"] != b["image_sha256"]:
        print(f"{name}: the receipts are of different programs")
        return False
    ca, _ = cycles(a, prog)
    cb, _ = cycles(b, prog)
    diff = []
    for k, w in enumerate(prog.windows):
        x, y = ca.get(k, []), cb.get(k, [])
        dx = [(kd, ad, 0 if kd == "ior" else r[2], n) for kd, ad, n, r in x
              if kd in ("mr", "mw", "ior", "iow")]
        dy = [(kd, ad, 0 if kd == "ior" else r[2], n) for kd, ad, n, r in y
              if kd in ("mr", "mw", "ior", "iow")]
        fx, fy = {}, {}
        for kd, ad, n, r in x:
            if kd == "fetch":
                fx.setdefault(ad, set()).add(n)
        for kd, ad, n, r in y:
            if kd == "fetch":
                fy.setdefault(ad, set()).add(n)
        why = None
        if dx != dy:
            i = next((i for i, (p, q) in enumerate(zip(dx, dy)) if p != q), min(len(dx), len(dy)))
            f = lambda v: f"{v[0]} {v[1]:05X} data {v[2]:04X} waits {v[3]}"     # noqa: E731
            why = (f"data cycle {i}: {ref} {f(dx[i]) if i < len(dx) else 'end'} / "
                   f"{cand} {f(dy[i]) if i < len(dy) else 'end'}")
        elif any(fx[ad] != fy[ad] for ad in fx.keys() & fy.keys()):
            ad = min(ad for ad in fx.keys() & fy.keys() if fx[ad] != fy[ad])
            why = f"fetch {ad:05X}: waits {ref} {sorted(fx[ad])} / {cand} {sorted(fy[ad])}"
        if why:
            diff.append((k, w, why, sum(1 for p, q in zip(dx, dy) if p != q)
                         + sum(1 for ad in fx.keys() & fy.keys() if fx[ad] != fy[ad])))
    print(f"{name}: {ref} / {cand} by window: {'EQUAL' if not diff else 'DIFFER'} "
          f"({len(prog.windows) - len(diff)} of {len(prog.windows)} windows equal)")
    for k, w, why, n in diff:
        print(f"  w{k:<2} WTC {w.wtc:04X}h PMC1 {w.pmc1:02X}h RFM {w.rfm:02X}h {w.sub.__name__}: "
              f"{n} cycles / fetch addresses differ; first: {why}")
    return not diff


def emit(progs):
    for name, prog in progs.items():
        if prog.share:
            continue
        (PROGRAMS_DIR / f"{name}.s").write_text(prog.source())
        print(f"{name}: {len(prog.build()['text'])} bytes, {len(prog.windows)} windows")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "report", "repeat", "gate", "emit", "size"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--socket-fitted", action="store_true",
                   help="accepted for the board rule's spelling (the socket action needs it)")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    progs = programs()
    names = a.names or list(progs)
    if a.action == "socket":
        if not a.socket_fitted:
            p.error("the socket action needs --socket-fitted")
        run_set(names, "socket", a.tag, progs)
    elif a.action == "sim":
        run_set(names, "sim", a.tag, progs)
    elif a.action == "report":
        for n in names:
            report(n, a.ref + a.tag, progs, a.verbose)
    elif a.action == "repeat":
        ok = True
        for n in names:
            ok &= compare(n, "socket", "socket-2", progs)
            compare(n, "socket", "socket-2", progs, strobe=True)
        return 0 if ok else 1
    elif a.action == "gate":
        ok = True
        for n in names:
            compare(n, a.ref, a.cand, progs)
            ok &= compare_windows(n, a.ref, a.cand, progs)
        return 0 if ok else 1
    elif a.action == "size":
        for n in names:
            b = progs[n].build()
            print(n, len(b["text"]), "bytes,", len(progs[n].windows), "windows,",
                  len(b["segments"]), "pages")
    else:
        emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
