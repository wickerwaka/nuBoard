"""READY (P17) under every WTC setting, reads and writes: the rdy_* program set.

The harness's READY (register 0Ah, fpga/v35s/v35s_lane.sv): READY falls a fixed time after a
cycle's column strobe (/MSTB or /IOSTB low) is seen and rises N ticks later (or when the strobe
rises); it is high outside a strobe. One tick is 30 ns; a CPU clock is 32 ticks at the reset PRC
(fX/8), 16 at fX/4, 8 at fX/2 (x_half 2), so N sweeps READY's rising edge in 1/32, 1/16 or 1/8
clock steps. The falling edge cannot be moved (see RESULTS.md, "the harness").

A program is a list of windows; a window stores WTC and PMC1, announces itself (OUT FE40h), calls
the program's probe routine and closes (OUT FE42h). Code runs in block 0 (WTC field 0), the data
probes are in block 1 (20000h, field 1), I/O is field 7: a window names the three fields. A program
is run once per READY hold N (a "run"); a receipt keeps every run's windows (ticks relative to
the window's begin marker, identical windows stored once).

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.ready socket --socket-fitted [NAME ...] [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.ready sim [NAME ...] [--jobs 8]
    PYTHONPATH=host/src:. python3 -m validation.v35s.ready repeat [NAME ...]    (socket / socket-2)
    PYTHONPATH=host/src:. python3 -m validation.v35s.ready summary [NAME ...] [--ref socket]
    PYTHONPATH=host/src:. python3 -m validation.v35s.ready gate [NAME ...]      (socket / sim)
    PYTHONPATH=host/src:. python3 -m validation.v35s.ready emit
    ... ready edges [NAME ...] [--cand sim]          the sweep's steps side by side
    ... ready follow [NAME ...] [--cand sim]         what a stretched cycle moves (window growth)
    ... ready scope [--backend socket|sim] [--socket-fitted] ; ready scopetable [--backend ...] [-v]
    ... ready msocket / msim / msummary / mrepeat / mgate / mscopetable   READY from /MREQ's fall
    ... ready static [--backend socket|sim] [--socket-fitted] ; staticreport ; staticgate

    rdy_e8 / rdy_e4 / rdy_e2   the edge probe (one cycle of each kind) at fX/8, fX/4, fX/2, every N
    rdy_e2x                    the edge probe at fX/2 with X1 slowed (the falling edge's place moves)
    rdy_k8 / rdy_k2            every kind of access (odd words, read-modify-write, stack, strings,
                               fetch in the READY block, I/O) at chosen N
    rdy_f8 / rdy_f2            what follows a stretched cycle with no idle between (pairs of accesses)
    rdy_i8                     INTP0 landing among READY-governed reads
    rdy_r2                     refresh among READY-governed cycles (silicon only)
    rdy_s8 / rdy_s2            the scope probe: one READY window, the pins at 30 ns (action `scope`)
    rdy_m8 / m4 / m2           READY timed from /MREQ's fall (harness version 3): both edges swept
    rdy_ms8 / ms4 / ms2        the same with the scope
    rdy_x_*                    READY as a level (action `static`): see "READY as a level" below

Receipts: validation/v35s/receipts/rdy-<name>-<backend>.json.
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

from .wtc import (Asm, Probe, base_image, mem_cycles, wtc_fields, BOUNDS, SEG, ORG, STACK_TOP,
                  M_BEGIN, M_END, FLAG_READ, FLAG_IO, FLAG_REFRESH, FLAG_STROBE, FLAG_PIN)

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS_DIR = ROOT / "validation/v35s/programs"
RECEIPTS = ROOT / "validation/v35s/receipts"

B1 = BOUNDS[0]                  # 20000h: the data block (field 1)
CSEG = SEG(B1)                  # the segment whose offset 0100h is 20000h (the sled, the stubs)
DSEG = CSEG + 0x10              # the data probes' segment: offset 0100h is 20100h
D0 = B1 + 0x100
PRC_CLK = {None: 32, 0x4E: 32, 0x4D: 16, 0x4C: 8}     # ticks per CPU clock at x_half 2
M_BANK = 0xFF10


def fields(code, data, io, rest=0):
    """WTC with field 0 (the code's block), field 1 (the data block), field 7 (I/O)."""
    return wtc_fields([code, data, rest, rest, rest, rest, rest, io])


class Window:
    def __init__(self, code, data, io, pmc1=0x80, note=""):
        self.code, self.data, self.io, self.pmc1, self.note = code, data, io, pmc1, note
        self.wtc = fields(code, data, io)

    def field(self, kind, addr):
        if kind in ("ior", "iow"):
            return self.io
        return (self.wtc >> 2 * min(addr >> 17, 6)) & 3

    def name(self):
        return f"code {self.code} data {self.data} io {self.io} PMC1 {self.pmc1:02X}"


# ------------------------------------------------------------------ the probe routines
def gap(a, n=6):
    a.nop(n)


def sub_edge(a: Asm, mem):
    """One cycle of each kind in the data block, NOPs between (each starts after idle)."""
    p = Probe(a, lambda x: mem[x])
    p.set_ds0(DSEG)
    a.mov_r("DW", 0x0040)
    gap(a)
    p.rd(0x0100, check=False)
    gap(a)
    p.wr(0x0130)
    gap(a)
    p.rd(0x0102, word=True, check=False)
    gap(a)
    p.wr(0x0132, word=True)
    gap(a)
    p.rd(0x0105, word=True, check=False)        # odd: two byte cycles
    gap(a)
    p.wr(0x0135, word=True)
    gap(a)
    a.op([0xFE, 0x06, 0x60, 0x01], f"INC byte [0160h]   ; {D0 + 0x60:05X}",
         [("mr", D0 + 0x60), ("mw", D0 + 0x60)])
    gap(a)
    a.op([0xEC], "IN AL, DW   ; 0040", [("ior", 0x40)])
    gap(a)
    a.op([0xEE], "OUT DW, AL   ; 0040", [("iow", 0x40)])
    gap(a)
    a.op([0xED], "IN AW, DW   ; 0040", [("ior", 0x40)])
    gap(a)
    a.op([0xEF], "OUT DW, AW   ; 0040", [("iow", 0x40)])
    gap(a)
    s = CSEG
    a.op([0x9A, 0x80, 0x01, s & 0xFF, s >> 8], f"CALL FAR {s:04X}h:0180h   ; the stub in the data block")
    a.groups.append(("CALL FAR / RETF", [("mw", STACK_TOP - 2), ("mw", STACK_TOP - 4),
                                         ("mr", STACK_TOP - 4), ("mr", STACK_TOP - 2)]))
    a.seg("DS0", 0)


def sub_kinds(a: Asm, mem):
    """Every kind of access in the data block (and between it and block 0)."""
    p = Probe(a, lambda x: mem[x])
    p.set_ds0(DSEG)
    a.op([0xFC], "CLR1 DIR")
    a.op([0x8B, 0xEC], "MOV BP, SP")
    # back-to-back reads and writes (no NOPs), then spaced
    p.rd(0x0100, check=False)
    p.rd(0x0102, word=True, check=False)
    p.rd(0x0105, word=True, check=False)
    p.wr(0x0130)
    p.wr(0x0132, word=True)
    p.wr(0x0135, word=True)
    gap(a)
    for bs, text, cyc in (
            ([0xFE, 0x06, 0x60, 0x01], "INC byte [0160h]", [("mr", D0 + 0x60), ("mw", D0 + 0x60)]),
            ([0xFF, 0x06, 0x62, 0x01], "INC word [0162h]", [("mr", D0 + 0x62), ("mw", D0 + 0x62)]),
            ([0x01, 0x06, 0x65, 0x01], "ADD [0165h], AW",
             mem_cycles("mr", D0 + 0x65, 2) + mem_cycles("mw", D0 + 0x65, 2)),
            ([0x86, 0x06, 0x68, 0x01], "XCH AL, [0168h]", [("mr", D0 + 0x68), ("mw", D0 + 0x68)]),
            ([0x80, 0x36, 0x6A, 0x01, 0x5A], "XOR byte [016Ah], 5Ah", [("mr", D0 + 0x6A), ("mw", D0 + 0x6A)]),
            ([0x39, 0x06, 0x6C, 0x01], "CMP [016Ch], AW", [("mr", D0 + 0x6C)])):
        a.op(bs, f"{text}", cyc)
        gap(a, 3)
    # the stack in the data block: PUSH / POP (even and odd SP), CALL / RET, PUSH mem / POP mem
    for sp in (0x01C0, 0x01C5):
        a.seg("SS", DSEG)
        a.mov_r("SP", sp)
        lin = D0 + sp - 0x100 - 2
        a.op([0x50], f"PUSH AW   ; {lin:05X}", mem_cycles("mw", lin, 2))
        a.op([0x59], f"POP CW   ; {lin:05X}", mem_cycles("mr", lin, 2))
        a.op([0x9C], f"PUSH PSW   ; {lin:05X}", mem_cycles("mw", lin, 2))
        a.op([0x9D], f"POP PSW   ; {lin:05X}", mem_cycles("mr", lin, 2))
        a.op([0xFA], "DI")
    a.mov_r("SP", 0x01D0)
    lin = D0 + 0xD0 - 2
    a.rel([0xE8], "kret", "CALL", wide=True)
    a.groups.append(("CALL / RET", mem_cycles("mw", lin, 2) + mem_cycles("mr", lin, 2)))
    a.op([0xFF, 0x36, 0x70, 0x01], "PUSH word [0170h]", [("mr", D0 + 0x70), ("mw", lin)])
    a.op([0x8F, 0x06, 0x72, 0x01], "POP word [0172h]", [("mr", lin), ("mw", D0 + 0x72)])
    a.mov_r("AW", 0)
    a.mov_sr("SS")
    a.op([0x8B, 0xE5], "MOV SP, BP")
    gap(a, 3)

    # strings: (source segment, destination segment): data -> data, data -> block 0, block 0 -> data
    def string(sseg, dseg, ix, iy, word, rep):
        p.set_ds0(sseg)
        a.seg("DS1", dseg)
        a.mov_r("IX", ix)
        a.mov_r("IY", iy)
        if rep:
            a.mov_r("CW", rep)
        src, dst = (sseg << 4) + ix, (dseg << 4) + iy
        cyc, w = [], 2 if word else 1
        for e in range(rep or 1):
            cyc += mem_cycles("mr", src + e * w, w) + mem_cycles("mw", dst + e * w, w)
        a.op(([0xF3] if rep else []) + [0xA5 if word else 0xA4],
             f"{'REP ' if rep else ''}MOVBK{'W' if word else ''}   ; {src:05X} -> {dst:05X}", cyc)
        gap(a, 3)

    string(DSEG, DSEG, 0x0110, 0x0140, False, 0)
    string(DSEG, DSEG, 0x0112, 0x0142, True, 0)
    string(DSEG, DSEG, 0x0114, 0x0144, False, 4)
    string(DSEG, DSEG, 0x0118, 0x0148, True, 3)
    string(DSEG, DSEG, 0x011F, 0x014F, True, 2)          # odd words
    string(DSEG, 0x0000, 0x0120, 0x0F40, False, 3)       # read in the data block, write in block 0
    string(0x0000, DSEG, 0x0F48, 0x0150, False, 3)       # read in block 0, write in the data block
    a.seg("DS1", 0xF000)
    p.set_ds0(DSEG)
    # I/O
    for port in (0x0040, 0x0041):
        a.mov_r("DW", port)
        a.op([0xEE], f"OUT DW, AL   ; {port:04X}", [("iow", port)])
        a.op([0xEC], f"IN AL, DW   ; {port:04X}", [("ior", port)])
        a.op([0xEF], f"OUT DW, AW   ; {port:04X}", mem_cycles("iow", port, 2))
        a.op([0xED], f"IN AW, DW   ; {port:04X}", mem_cycles("ior", port, 2))
        gap(a, 3)
    a.op([0xE4, 0x44], "IN AL, 44h", [("ior", 0x44)])
    a.op([0xE6, 0x44], "OUT 44h, AL", [("iow", 0x44)])
    gap(a, 3)
    # fetch in the data block: the stub (8 NOPs, RETF) and the sled across 20000h
    s = CSEG
    for off in (0x0180, 0x00F0):
        a.op([0x9A, off & 0xFF, off >> 8, s & 0xFF, s >> 8], f"CALL FAR {s:04X}h:{off:04X}h")
        a.groups.append(("CALL FAR / RETF", [("mw", STACK_TOP - 2), ("mw", STACK_TOP - 4),
                                             ("mr", STACK_TOP - 4), ("mr", STACK_TOP - 2)]))
    # on-chip accesses between the data block's cycles (internal RAM, an SFR, IDB at FFFFFh)
    a.op([0x26, 0xA0, 0x40, 0xFE], "MOV AL, DS1:[FE40h]   ; internal RAM")
    p.rd(0x0100, check=False)
    a.op([0x26, 0xA2, 0x41, 0xFE], "MOV DS1:[FE41h], AL   ; internal RAM")
    p.wr(0x0130)
    a.op([0x26, 0xA1, 0xE8, 0xFF], "MOV AW, DS1:[FFE8h]   ; WTC")
    p.rd(0x0102, word=True, check=False)
    a.op([0x26, 0xA0, 0xFF, 0xFF], "MOV AL, DS1:[FFFFh]   ; IDB")
    gap(a, 3)
    a.seg("DS0", 0)


def sub_follow(a: Asm, mem):
    """What follows a stretched cycle with no idle between: pairs (a READY-governed cycle, then
    the next instruction's access or work), NOPs between the pairs. Block-0 targets through SS:."""
    p = Probe(a, lambda x: mem[x])
    p.set_ds0(DSEG)
    a.op([0x26, 0xC6, 0x06, 0x40, 0xFE, 0x3C], "MOV byte DS1:[FE40h], 3Ch   ; the internal RAM byte read below")
    a.mov_r("DW", 0x0040)
    OUT = ([0xEE], "OUT DW, AL   ; 0040", [("iow", 0x40)])
    IN = ([0xEC], "IN AL, DW   ; 0040", [("ior", 0x40)])
    RD = ([0xA0, 0x00, 0x01], f"MOV AL, [0100h]   ; {D0:05X}", [("mr", D0)])
    RD2 = ([0xA0, 0x02, 0x01], f"MOV AL, [0102h]   ; {D0 + 2:05X}", [("mr", D0 + 2)])
    WR = ([0xA2, 0x30, 0x01], f"MOV [0130h], AL   ; {D0 + 0x30:05X}", [("mw", D0 + 0x30)])
    W0 = ([0x36, 0xA2, 0x40, 0x0F], "MOV SS:[0F40h], AL   ; 00F40", [("mw", 0xF40)])
    R0 = ([0x36, 0xA0, 0x42, 0x0F], "MOV AL, SS:[0F42h]   ; 00F42", [("mr", 0xF42)])
    INC3 = ([0x40, 0x40, 0x40], "INC AW x3", None)
    IRD = ([0x26, 0xA0, 0x40, 0xFE], "MOV AL, DS1:[FE40h]   ; internal RAM", None)
    IWR = ([0x26, 0xA2, 0x41, 0xFE], "MOV DS1:[FE41h], AL   ; internal RAM", None)
    for seq in ((OUT, W0), (OUT, R0), (OUT, WR), (OUT, RD), (OUT, OUT), (IN, W0), (IN, OUT),
                (RD, W0), (RD, OUT), (RD, RD2), (RD, INC3, W0), (OUT, INC3, W0),
                (OUT, IRD, W0), (RD, IWR, W0), (IN, IRD, W0)):
        gap(a)
        for bs, text, cyc in seq:
            a.op(bs, text, cyc)
    gap(a)
    a.op([0xEE], "OUT DW, AL   ; 0040", [("iow", 0x40)])
    a.rel([0xE8], "kret", "CALL", wide=True)
    a.groups.append(("CALL / RET", [("mw", STACK_TOP - 4), ("mr", STACK_TOP - 4)]))
    gap(a)
    a.seg("DS0", 0)


def sub_intr(a: Asm, mem):
    """INTP0 (the schedule: event 1, the pin low I_DELAY ticks after the event's cycle) lands in
    a run of READY-governed byte reads; the handler announces itself (OUT FE44h)."""
    p = Probe(a, lambda x: mem[x])
    p.set_ds0(DSEG)
    a.sfr_w(0x4C, 0x07)                 # EXIC0: INTP0 enabled
    a.out_w(0xFF12, 0x0001)
    a.op([0xFB], "EI")
    for _ in range(I_READS):
        a.op([0xA0, 0x00, 0x01], f"MOV AL, [0100h]   ; {D0:05X}", [("mr", D0)])
    a.op([0xFA], "DI")
    a.sfr_w(0x4C, 0x47)
    a.seg("DS0", 0)


def sub_reads(a: Asm, mem):
    """A run of READY-governed byte reads and I/O writes (refresh requests fall among them)."""
    p = Probe(a, lambda x: mem[x])
    p.set_ds0(DSEG)
    a.mov_r("DW", 0x0040)
    for _ in range(12):
        a.op([0xA0, 0x00, 0x01], f"MOV AL, [0100h]   ; {D0:05X}", [("mr", D0)])
        a.op([0xEE], "OUT DW, AL   ; 0040", [("iow", 0x40)])
    gap(a, 12)
    a.seg("DS0", 0)


I_READS, I_DELAY = 40, 3000
M_SUB = 0xFE44


def sub_scope(a: Asm, mem):
    """The scope probe: a byte read, a byte write, IN, OUT, an odd word read and write, each
    after idle."""
    p = Probe(a, lambda x: mem[x])
    p.set_ds0(DSEG)
    a.mov_r("DW", 0x0040)
    gap(a)
    p.rd(0x0100, check=False)
    gap(a)
    p.wr(0x0130)
    gap(a)
    a.op([0xEC], "IN AL, DW   ; 0040", [("ior", 0x40)])
    gap(a)
    a.op([0xEE], "OUT DW, AL   ; 0040", [("iow", 0x40)])
    gap(a)
    p.rd(0x0105, word=True, check=False)
    gap(a)
    p.wr(0x0135, word=True)
    gap(a)
    a.seg("DS0", 0)


# ------------------------------------------------------------------ programs
class Program:
    def __init__(self, name, windows, sub, note="", prc=None, holds=(0,), x_halfs=(2,),
                 clkout=False, rfm=0xEC, stim=None):
        self.name, self.windows, self.sub, self.note = name, windows, sub, note
        self.rfm, self.stim = rfm, stim
        self.prc, self.holds, self.x_halfs, self.clkout = prc, list(holds), list(x_halfs), clkout
        self.clk = PRC_CLK[prc]
        self._built = None

    def runs(self):
        return [(n, x) for x in self.x_halfs for n in self.holds]

    def build(self):
        if self._built:
            return self._built
        mem, code = base_image(True)
        a = Asm()
        a.op([0xFA], "DI")
        a.mov_r("AW", 0)
        a.mov_sr("SS")
        a.mov_r("SP", STACK_TOP)
        a.mov_sr("DS0")
        a.seg("DS1", 0xF000)
        a.sfr_w(0xE1, 0xEC)                 # RFM: no refresh (self.rfm is stored in the windows)
        if self.clkout:                     # CLKOUT on P07 (programs/clocks.s: T2 Z, then D)
            a.out_w(M_BANK, 0x0001)
            a.sfr_w(0x00, 0x55)
            a.sfr_w(0x01, 0x00)
            a.sfr_w(0x02, 0x80)
            a.out_w(M_BANK, 0x0002)
        if self.prc is not None:
            a.sfr_w(0xEB, self.prc)
        pmc1 = 0x00
        for k, w in enumerate(self.windows):
            a.lines.append((b"", f"; ---- window {k}: WTC {w.wtc:04X}h PMC1 {w.pmc1:02X}h ({w.name()}) {w.note}"))
            if w.pmc1 != pmc1:
                a.sfr_w(0x0A, w.pmc1)
                pmc1 = w.pmc1
            a.sfr_w(0xE8, w.wtc, word=True)
            if self.rfm != 0xEC:
                a.sfr_w(0xE1, self.rfm)
            a.out_w(M_BEGIN, k)
            a.rel([0xE8], "probe", "CALL", wide=True)
            a.out_w(M_END, k)
            if self.rfm != 0xEC:
                a.sfr_w(0xE1, 0xEC)
        a.sfr_w(0xE8, 0xFFFF, word=True)
        a.sfr_w(0x0A, 0x00)
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
        if self.stim:
            a.label("irq")                  # INTP0 (vector 24): a marker, FINT, RETI
            a.op([0x50], "PUSH AW")
            a.op([0x52], "PUSH DW")
            a.out_w(M_SUB, 0x0049)
            a.op([0x5A], "POP DW")
            a.op([0x58], "POP AW")
            a.op([0x0F, 0x92], "FINT")
            a.op([0xCF], "RETI")
        a.label("probe")
        a.groups = []
        self.sub(a, mem)
        groups, a.groups = a.groups, None
        a.op([0xC3], "RET")
        text = a.finish()
        if ORG + len(text) > 0xE00:
            raise ValueError(f"{self.name}: {len(text)} bytes of code reach the stack")
        for i, v in enumerate(text):
            mem[ORG + i] = v
        for i, v in enumerate(bytes([0xEA, ORG & 0xFF, ORG >> 8, 0, 0])):
            mem[0xFFFF0 + i] = v
        if self.stim:
            for i, v in enumerate(a.labels["irq"].to_bytes(2, "little") + b"\0\0"):
                mem[0x00060 + i] = v
        segments = {}
        for pg in sorted({x >> 12 for x in mem}):
            segments[pg << 12] = bytes(mem[pg << 12 | o] for o in range(0x1000))
        self._built = dict(text=text, lines=a.lines, segments=segments, groups=groups,
                           code=[(ORG, ORG + len(text)), (0xFFFF0, 0xFFFF5)] + code)
        return self._built

    def source(self):
        b = self.build()
        out = [f"; {self.name}: {self.note}",
               "; Generated by validation/v35s/ready.py emit: the bytes are the generator's; the image",
               "; also holds wtc.py's fill, sleds and stubs (base_image). READY holds (register 0Ah) run: "
               + " ".join(str(n) for n in self.holds) + f"; x_half {self.x_halfs}"]
        for bs, text in b["lines"]:
            if not bs:
                out.append(text)
            else:
                out.append("    DB " + ", ".join(f"{v:02X}h" if v < 0xA0 else f"0{v:02X}h" for v in bs)
                           + f"    ; {text}")
        return "\n".join(out) + "\n"


def std_windows():
    W = Window
    return [W(0, 0, 0, note="fixed 0 waits"), W(0, 1, 1, note="fixed 1 wait"),
            W(0, 2, 2, note="fixed 2 waits"),
            W(0, 3, 3, pmc1=0x00, note="field 3, P17 not READY"),
            W(0, 3, 3, note="READY: data and I/O"),
            W(0, 3, 0, note="READY: data only"),
            W(0, 0, 3, note="READY: I/O only"),
            W(3, 0, 0, note="READY: the code's block only"),
            W(3, 3, 3, note="READY: everything"),
            W(2, 3, 3, note="READY: data and I/O, code 2 waits")]


E8 = list(range(0, 256))
E2 = list(range(0, 256))
K8 = [0, 16, 48, 80, 112, 144, 176, 208, 240, 255]       # away from every lane's edges (N = 8, 24, 25 mod 32)
K2 = [0, 5, 13, 21, 29, 45, 69, 101, 165, 253]           # (N = 0, 2 mod 8)


def programs():
    progs = [
        Program("rdy_e8", std_windows(), sub_edge, "the edge probe at fX/8 (32 ticks a clock)", holds=E8),
        Program("rdy_e4", std_windows(), sub_edge, "the edge probe at fX/4 (16 ticks a clock)",
                prc=0x4D, holds=list(range(0, 128))),
        Program("rdy_e2", std_windows(), sub_edge, "the edge probe at fX/2 (8 ticks a clock)",
                prc=0x4C, holds=E2),
        Program("rdy_e2x", std_windows()[3:6], sub_edge, "the edge probe at fX/2, X1 slowed "
                "(x_half 3, 5: 12 and 20 ticks a clock)", prc=0x4C, holds=list(range(0, 64)),
                x_halfs=(3, 5)),
        Program("rdy_k8", std_windows(), sub_kinds, "every kind of access at fX/8", holds=K8),
        Program("rdy_k2", std_windows(), sub_kinds, "every kind of access at fX/2", prc=0x4C, holds=K2),
        Program("rdy_f8", [Window(0, 0, 0), Window(0, 2, 2), Window(0, 3, 3, note="READY: data and I/O")],
                sub_follow, "what follows a stretched cycle, at fX/8", holds=K8),
        Program("rdy_f2", [Window(0, 0, 0), Window(0, 2, 2), Window(0, 3, 3, note="READY: data and I/O")],
                sub_follow, "what follows a stretched cycle, at fX/2", prc=0x4C, holds=K2),
        Program("rdy_i8", [Window(0, 2, 2), Window(0, 3, 3, note="READY: data and I/O")], sub_intr,
                "INTP0 among READY-governed reads, at fX/8", holds=K8,
                stim={"entries": [{"event": 1, "delay": I_DELAY, "hold": 2000, "levels": {"INTP0": 0}}] * 2}),
        Program("rdy_r2", [Window(0, 2, 2), Window(0, 3, 3, note="READY: data and I/O")], sub_reads,
                "refresh on (RFM F0h) among READY-governed cycles, at fX/2 (silicon only: the core "
                "v2 runs no refresh)", prc=0x4C, holds=K2, rfm=0xF0),
        Program("rdy_s8", [Window(0, 3, 3, note="READY: data and I/O")], sub_scope,
                "the scope probe at fX/8, CLKOUT on P07", holds=E8, clkout=True),
        Program("rdy_s2", [Window(0, 3, 3, note="READY: data and I/O")], sub_scope,
                "the scope probe at fX/2, CLKOUT on P07", prc=0x4C, holds=list(range(0, 80)), clkout=True),
    ]
    return {p.name: p for p in progs}


# ------------------------------------------------------------------ reading a trace
def kind_of(row, code):
    f = row[3]
    if f & FLAG_PIN:
        return "pin"
    if f & FLAG_REFRESH:
        return "refresh"
    if not f & FLAG_STROBE:
        return "idle"
    if f & FLAG_IO:
        return "ior" if f & FLAG_READ else "iow"
    if not f & FLAG_READ:
        return "mw"
    return "fetch" if any(lo <= row[1] < hi + 12 for lo, hi in code) else "mr"


def cut(rows, prog):
    """The trace cut at the markers: {window: [[kind, address, data, length, strobe offset,
    start - the begin marker's end], ...]} and the cycles before the first window likewise
    (relative to the first record)."""
    code = prog.build()["code"]
    wins, head, k, t0 = {}, [], None, rows[0][0] if rows else 0
    for row in rows:
        kind = kind_of(row, code)
        if kind == "pin":
            continue
        if kind == "iow" and row[1] == M_BEGIN:
            k, t0 = row[2], row[4]
            wins[k] = []
            continue
        if kind == "iow" and row[1] == M_END:
            if k is not None and k >= 0:
                wins[k].append(["end", row[1], row[2], row[4] - row[0], row[5], row[0] - t0])
            k = -1
            continue
        item = [kind, row[1], 0 if kind == "ior" else row[2], row[4] - row[0], row[5], row[0] - t0]
        if k is None:
            head.append(item)
        elif k >= 0:
            wins[k].append(item)
    return wins, head


def run_key(n, x):
    return f"{n}" if x == 2 else f"{n}@{x}"


def receipt_path(name, backend):
    return RECEIPTS / f"rdy-{name}-{backend}.json"


def load(name, backend):
    return json.loads(receipt_path(name, backend).read_text())


def windows_of(rec, key):
    """A run's windows from a receipt: {window: rows}."""
    run = rec["runs"][key]
    return {int(k): rec["blobs"][h] for k, h in run["wins"].items()}


def blob(store, rows):
    h = hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()[:16]
    store.setdefault(h, rows)
    return h


def set_m(harness, m):
    """The /MREQ-timed READY (harness version 3): m = (delay, hold, trigger, blocks) or None."""
    if harness.version < 3:
        if m:
            raise RuntimeError("READY from /MREQ needs harness version 3 (rebuild the image)")
        return
    d, h, trig, blocks = m or (0, 0, 0, 0xFF)
    harness.debug.write16(0xC2, (trig & 3) << 12 | d)
    harness.debug.write16(0xC4, h)
    harness.debug.write16(0xC6, blocks)


def run_one(harness, prog, lane, n, x, limit=60_000_000, m=None):
    b = prog.build()
    harness.debug.write16(0x08, x)
    harness.debug.write16(0x0A, n)
    set_m(harness, m)
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
    harness.debug.write16(0x08, 2)
    set_m(harness, None)
    rows = [[t["start"], t["address"], t["data"], t["flags"], t["end"], t["strobe"]] for t in trace]
    return dict(passed=result["passed"], status=result["status"], timeout=result["timeout"],
                total=total, replay=replay), rows


def pack(prog, results, backend):
    """results: {key: (info, rows)} -> the receipt."""
    b = prog.build()
    store, runs = {}, {}
    for key, (info, rows) in results.items():
        wins, head = cut(rows, prog)
        runs[key] = dict(info, head=blob(store, head), wins={str(k): blob(store, v) for k, v in wins.items()})
    rec = {
        "program": prog.name, "note": prog.note, "prc": prog.prc, "clk_ticks": prog.clk,
        "program_sha256": hashlib.sha256(b["text"]).hexdigest(),
        "image_sha256": hashlib.sha256(json.dumps(
            {f"{a:05X}": d.hex() for a, d in sorted(b["segments"].items())}).encode()).hexdigest(),
        "row": "kind, address, data, end - start, strobe offset, start - the begin marker's end (ticks)",
        "backend": backend, "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "runs": runs, "blobs": store,
    }
    if backend.startswith("socket"):
        rec.update(cpu="uPD70337L-8")
    else:
        rec.update(core="v35", binary=os.environ.get("V35_SIM_BINARY", "build/fpga/v35s/verilator-direct-v35"))
    return rec


def write(prog, results, backend, tag):
    rec = pack(prog, results, backend)
    receipt_path(prog.name, backend + tag).write_text(json.dumps(rec, separators=(",", ":")) + "\n")
    bad = [k for k, r in rec["runs"].items() if not r["passed"] or r["replay"]]
    print(f"{prog.name}: {backend}{tag} {len(rec['runs'])} runs, {len(rec['blobs'])} distinct windows, "
          f"not passed / replay: {bad or 'none'}", flush=True)


def _sim_job(args):
    name, n, x = args
    from .traps import _sim, _stim
    prog = programs()[name]
    transport, harness = _sim()
    try:
        _stim(harness, prog)
        return run_key(n, x), run_one(harness, prog, "model", n, x)
    finally:
        transport.close()


def run_set(names, backend, tag, progs, jobs=8, only=None):
    from .traps import _board, _close_board, _stim
    if backend == "socket":
        transport, harness = _board()
        try:
            for name in names:
                prog = progs[name]
                _stim(harness, prog)
                results = {}
                for n, x in prog.runs():
                    if only is not None and n not in only:
                        continue
                    results[run_key(n, x)] = run_one(harness, prog, "socket", n, x)
                write(prog, results, backend, tag)
        finally:
            _close_board(transport, harness)
    else:
        from multiprocessing import Pool
        with Pool(jobs) as pool:
            for name in names:
                prog = progs[name]
                todo = [(name, n, x) for n, x in prog.runs() if only is None or n in only]
                write(prog, dict(pool.map(_sim_job, todo)), backend, tag)


# ------------------------------------------------------------------ tables
DATA = ("mr", "mw", "ior", "iow")
EDGE_TICKS = 1          # compare: waits found within this many ticks of hold count as the edge


def waits(length, clk):
    return round((length - 1) / clk) - 2


def data_cycles(rows):
    return [r for r in rows if r[0] in DATA]


def steps(seq):
    """[(key, value)] in run order -> the values with the first key of each run of equal values."""
    out, last = [], object()
    for k, v in seq:
        if v != last:
            out.append((k, v))
            last = v
    return out


def sweep_table(rec, prog, x=2):
    """Per window and data cycle: the waits as a function of N. {window: [(label, steps)]}"""
    clk = prog.clk * x // 2
    out = {}
    keys = [(n, run_key(n, x)) for n in prog.holds if run_key(n, x) in rec["runs"]]
    for k, w in enumerate(prog.windows):
        per = {}
        for n, key in keys:
            rows = windows_of(rec, key).get(k)
            if rows is None:
                per.setdefault("(window missing)", []).append((n, None))
                continue
            seen = Counter()
            for r in data_cycles(rows):
                seen[(r[0], r[1])] += 1
                label = f"{r[0]} {r[1]:05X}" + (f" #{seen[(r[0], r[1])]}" if seen[(r[0], r[1])] > 1 else "")
                per.setdefault(label, []).append((n, waits(r[3], clk)))
            fw = Counter((min(r[1] >> 17, 6), waits(r[3], clk)) for r in rows if r[0] == "fetch")
            for blk in sorted({b for b, _ in fw}):
                per.setdefault(f"fetch block {blk}", []).append(
                    (n, "/".join(str(v) for (b, v), c in sorted(fw.items()) if b == blk)))
        out[k] = [(label, steps(seq)) for label, seq in per.items()]
    return out


def fmt_steps(st):
    return " ".join(f"{v}w@{k}" for k, v in st)


def summary(name, backend, progs, verbose=False):
    prog, rec = progs[name], load(name, backend)
    print(f"{name} [{backend}]: {prog.note}; {len(rec['runs'])} runs, clock {prog.clk} ticks")
    for x in prog.x_halfs:
        if len(prog.x_halfs) > 1:
            print(f" x_half {x} (clock {prog.clk * x // 2} ticks)")
        for k, rows in sweep_table(rec, prog, x).items():
            w = prog.windows[k]
            print(f"  w{k} WTC {w.wtc:04X} {w.name()} ({w.note}): waits@first N")
            groups = {}
            for label, st in rows:
                groups.setdefault(fmt_steps(st), []).append(label)
            for st, labels in groups.items():
                if verbose or len(labels) <= 4:
                    print(f"      {', '.join(labels)}: {st}")
                else:
                    kinds = Counter(lb.split()[0] for lb in labels)
                    print(f"      {', '.join(f'{k} x{c}' for k, c in kinds.items())}: {st}")


def compare(name, ref, cand, progs, exact=True, quiet=False):
    """Run by run, window by window. exact: every row equal (ticks); else the data cycles'
    (kind, address, data, waits) in order and the fetched addresses' waits."""
    prog, a, b = progs[name], load(name, ref), load(name, cand)
    if a["program_sha256"] != b["program_sha256"] or a["image_sha256"] != b["image_sha256"]:
        print(f"{name}: the receipts are of different programs")
        return False
    diff, edge, nwin = [], [], 0

    def near(n, x, k, da, db):
        """The data cycles differ in waits only, and every differing cycle of the candidate has
        the waits the reference has one tick of READY hold away (N - 1 or N + 1): the two
        differ by where the edge fell within a tick."""
        clk = prog.clk * x // 2
        sides = []
        for m in [n + d for d in range(-EDGE_TICKS, EDGE_TICKS + 1) if d]:
            kk = run_key(m, x)
            if kk in a["runs"] and str(k) in a["runs"][kk]["wins"]:
                rows = data_cycles(a["blobs"][a["runs"][kk]["wins"][str(k)]])
                sides.append([waits(r[3], clk) for r in rows])
        for i, (p, q) in enumerate(zip(da, db)):
            if p[3] != q[3] and not any(i < len(sd) and sd[i] == q[3] for sd in sides):
                return False
        return True

    for n, x in prog.runs():
        key = run_key(n, x)
        if key not in a["runs"] or key not in b["runs"]:
            continue
        clk = prog.clk * x // 2
        ra, rb = a["runs"][key], b["runs"][key]
        for k in range(len(prog.windows)):
            nwin += 1
            ha, hb = ra["wins"].get(str(k)), rb["wins"].get(str(k))
            if ha == hb and ha is not None:
                continue
            if ha is None or hb is None:
                diff.append((key, k, "window missing", "any"))
                continue
            wa, wb = a["blobs"][ha], b["blobs"][hb]
            if exact:
                i = next((i for i, (p, q) in enumerate(zip(wa, wb)) if p != q), min(len(wa), len(wb)))
                p, q = (wa[i] if i < len(wa) else None), (wb[i] if i < len(wb) else None)
                fld = "count" if p is None or q is None else \
                    ("kind", "address", "data", "length", "strobe", "start")[next(j for j in range(6) if p[j] != q[j])]
                diff.append((key, k, f"row {i}: {p} / {q}", fld))
                continue
            da = [(r[0], r[1], r[2], waits(r[3], clk)) for r in data_cycles(wa)]
            db = [(r[0], r[1], r[2], waits(r[3], clk)) for r in data_cycles(wb)]
            fa, fb = {}, {}
            for r in wa:
                if r[0] == "fetch":
                    fa.setdefault(r[1], set()).add(waits(r[3], clk))
            for r in wb:
                if r[0] == "fetch":
                    fb.setdefault(r[1], set()).add(waits(r[3], clk))
            if da != db and [v[:3] for v in da] == [v[:3] for v in db] and near(n, x, k, da, db):
                edge.append((key, k))
            elif da != db:
                i = next((i for i, (p, q) in enumerate(zip(da, db)) if p != q), min(len(da), len(db)))
                f = lambda v: f"{v[0]} {v[1]:05X} data {v[2]:04X} waits {v[3]}"     # noqa: E731
                diff.append((key, k, f"data cycle {i}: {f(da[i]) if i < len(da) else 'end'} / "
                                     f"{f(db[i]) if i < len(db) else 'end'}", "waits"))
            elif any(fa[ad] != fb[ad] for ad in fa.keys() & fb.keys()):
                ad = min(ad for ad in fa.keys() & fb.keys() if fa[ad] != fb[ad])
                diff.append((key, k, f"fetch {ad:05X}: waits {sorted(fa[ad])} / {sorted(fb[ad])}", "waits"))
    what = "to the tick" if exact else "by waits"
    print(f"{name}: {ref} / {cand} {what}: {'EQUAL' if not diff else 'DIFFER'} "
          f"({nwin - len(diff) - len(edge)} of {nwin} run-windows equal"
          + (f", {len(edge)} more within {EDGE_TICKS} tick(s) of READY's edge (N {sorted({int(k.split('@')[0]) for k, _ in edge})})"
             if edge else "")
          + f"; differing fields {dict(Counter(d[3] for d in diff))})")
    if not quiet:
        shown = Counter()
        for key, k, why, fld in diff:
            shown[k] += 1
            if shown[k] <= 3:
                print(f"  N {key} w{k} ({prog.windows[k].name()}): {why}")
        for k, c in sorted(shown.items()):
            if c > 3:
                print(f"  w{k}: {c} runs differ")
    return not diff



# ------------------------------------------------------------------ the scope probe
SCOPE_SIGNALS = ("mreq_n", "mstb_n", "iostb_n", "rw", "ready", "drive", "clkout", "data", "mux",
                 "a0", "a18_ube", "a19")
FULL_EVERY = 8          # the runs whose every edge is kept (the others: the digest only)


def scope_one(harness, prog, lane, n, x, limit=60_000_000, m=None, full=None):
    """One run with the scope on the lane: per probe cycle of window 0 the pins' edges. Ticks
    are relative to the tick /MREQ's fall is seen (the scope's own samples: every pin through
    the same two flops, READY the harness's own output register)."""
    from .scope import Scope, edges
    b = prog.build()
    harness.debug.write16(0x08, x)
    harness.debug.write16(0x0A, n)
    set_m(harness, m)
    mode = "socket" if lane == "socket" else "model"
    harness.load(b["segments"])
    scope = Scope(harness.debug)
    scope.configure(lane)
    result = harness.run(mode, limit)
    capture = scope.download()
    harness.debug.write16(0x0A, 0)
    harness.debug.write16(0x08, 2)
    set_m(harness, None)
    rows = [[t["start"], t["address"], t["data"], t["flags"], t["end"], t["strobe"]]
            for t in result[f"{lane}_trace"]]
    code = b["code"]
    clk = prog.clk * x // 2
    every = edges(capture, SCOPE_SIGNALS)
    out, inside = [], False
    for i, row in enumerate(rows):
        kind = kind_of(row, code)
        if kind == "iow" and row[1] == M_BEGIN:
            inside = True
            continue
        if kind == "iow" and row[1] == M_END:
            inside = False
        if not inside or kind not in DATA:
            continue
        lo, hi = row[0] - 2 * clk, row[4] + 3 * clk
        ev = [e for e in every if lo <= e.tick < hi]
        t0 = next((e.tick for e in ev if e.signal == "mreq_n" and e.value == 0
                   and e.tick >= row[0] - 6), None)
        if t0 is None:
            out.append(dict(kind=kind, address=row[1], error="no /MREQ fall in the capture"))
            continue
        stb = "iostb_n" if kind in ("ior", "iow") else "mstb_n"

        def first(sig, val, after=t0):
            return next((e.tick - t0 for e in ev if e.signal == sig and e.value == val
                         and e.tick >= after), None)
        sf = first(stb, 0)
        rf = first("ready", 0)
        item = dict(kind=kind, address=row[1], length=row[4] - row[0], trace_strobe=row[5],
                    stb_fall=sf, stb_rise=first(stb, 1, t0 + (sf or 0)),
                    rdy_edges=[[e.tick - t0, e.value] for e in ev if e.signal == "ready"],
                    data_edges=[e.tick - t0 for e in ev if e.signal == "data"],
                    mreq_rise=first("mreq_n", 1),
                    rdy_fall=rf, rdy_rise=first("ready", 1, t0 + (rf or 0)),
                    rw_fall=first("rw", 0, t0 - clk), rw_rise=first("rw", 1, t0 + 1),
                    clk_rise=[e.tick - t0 for e in ev if e.signal == "clkout" and e.value == 1],
                    clk_fall=[e.tick - t0 for e in ev if e.signal == "clkout" and e.value == 0],
                    next_mreq_fall=first("mreq_n", 0, t0 + 1))
        if (n % FULL_EVERY == 0) if full is None else full:
            item["edges"] = [[e.tick - t0, e.signal, e.value] for e in ev if e.signal != "clkout"]
        out.append(item)
    return dict(passed=result["passed"], status=result["status"], total=result[f"{lane}_total"],
                capture=capture.reason, records=capture.committed, cycles=out)


def _scope_job(args):
    name, n, x = args
    from .traps import _sim, _stim
    prog = programs()[name]
    transport, harness = _sim()
    try:
        _stim(harness, prog)
        return run_key(n, x), scope_one(harness, prog, "model", n, x)
    finally:
        transport.close()


def scope_set(names, backend, tag, progs, jobs=8, only=None):
    from .traps import _board, _close_board, _stim

    def save(prog, runs):
        rec = dict(program=prog.name, note=prog.note, clk_ticks=prog.clk, backend=backend,
                   program_sha256=hashlib.sha256(prog.build()["text"]).hexdigest(),
                   date=datetime.datetime.now().isoformat(timespec="seconds"),
                   ticks="relative to the tick /MREQ's fall is sampled; 30 ns", runs=runs)
        receipt_path(prog.name, f"{backend}{tag}-scope").write_text(json.dumps(rec, separators=(",", ":")) + "\n")
        bad = [k for k, r in runs.items() if not r["passed"] or r["capture"] != "complete"]
        print(f"{prog.name}: scope {backend}{tag} {len(runs)} runs, not passed / capture incomplete: "
              f"{bad or 'none'}", flush=True)

    if backend == "socket":
        transport, harness = _board()
        try:
            for name in names:
                prog = progs[name]
                _stim(harness, prog)
                save(prog, {run_key(n, x): scope_one(harness, prog, "socket", n, x)
                            for n, x in prog.runs() if only is None or n in only})
        finally:
            _close_board(transport, harness)
    else:
        from multiprocessing import Pool
        with Pool(jobs) as pool:
            for name in names:
                prog = progs[name]
                todo = [(name, n, x) for n, x in prog.runs() if only is None or n in only]
                save(prog, dict(pool.map(_scope_job, todo)))


def scope_rows(name, backend, progs):
    """Per probe cycle of the scope program: its shape at N 0 and, per length, the first N with
    it. [(index, kind, address, shape, [step, ...])]; a step: waits, N, READY's fall and rise
    from the strobe's fall, the strobe's rise from its fall, CLKOUT's edges from the strobe's
    fall, and the rise at N - 1 (which ended the cycle a clock sooner)."""
    prog = progs[name]
    rec = load(name, backend + "-scope")
    clk = prog.clk
    out = []
    ncyc = max(len(r["cycles"]) for r in rec["runs"].values())
    for c in range(ncyc):
        seq = [(n, rec["runs"][str(n)]["cycles"][c]) for n in prog.holds
               if str(n) in rec["runs"] and c < len(rec["runs"][str(n)]["cycles"])
               and "error" not in rec["runs"][str(n)]["cycles"][c]]
        if not seq:
            continue
        c0 = seq[0][1]
        sf0 = c0["stb_fall"]
        shape = dict(stb_fall=sf0, stb_rise=c0["stb_rise"], mreq_rise=c0["mreq_rise"],
                     clk_rise=[t - sf0 for t in c0["clk_rise"] if -2 * clk < t - sf0 < 4 * clk],
                     clk_fall=[t - sf0 for t in c0["clk_fall"] if -2 * clk < t - sf0 < 4 * clk])
        st, last, prev = [], None, None
        for n, cy in seq:
            w = waits(cy["length"], clk)
            if w != last or n == seq[-1][0]:
                sf = cy["stb_fall"]
                d = dict(waits=w, n=n, low=None, high=None, stb_low=cy["stb_rise"] - sf, before=None,
                         clk_rise=[t - sf for t in cy["clk_rise"] if t >= sf],
                         clk_fall=[t - sf for t in cy["clk_fall"] if t >= sf])
                if cy["rdy_fall"] is not None and cy["rdy_rise"] is not None:
                    d.update(low=cy["rdy_fall"] - sf, high=cy["rdy_rise"] - sf)
                if w != last and prev is not None and prev.get("rdy_rise") is not None \
                        and prev.get("rdy_fall") is not None:
                    d["before"] = prev["rdy_rise"] - prev["stb_fall"]
                st.append(d)
                last = w
            prev = cy
        out.append((c, c0["kind"], c0["address"], shape, st))
    return out


def scope_table(name, backend, progs, verbose=False):
    """The sampling table: READY's rising edge against the strobe's edges (and CLKOUT's)."""
    prog = progs[name]
    clk = prog.clk
    print(f"{name} [{backend}] scope: a clock is {clk} ticks ({clk * 30} ns); times in ticks of 30 ns "
          f"from the strobe's fall as the scope samples it")
    groups = {}
    for c, kind, addr, shape, st in scope_rows(name, backend, progs):
        key = json.dumps([kind, shape, st], sort_keys=True)
        groups.setdefault(key, []).append(f"{kind} {addr:05X}")
    for key, labels in groups.items():
        kind, shape, st = json.loads(key)
        print(f"  {', '.join(labels)}: strobe falls /MREQ-fall+{shape['stb_fall']}, rises +{shape['stb_rise']} at N 0"
              + (f"; CLKOUT rises at strobe-fall{[f'{t:+d}' for t in shape['clk_rise']]}, "
                 f"falls {[f'{t:+d}' for t in shape['clk_fall']]}" if shape["clk_rise"] else ""))
        for d in st:
            if d["low"] is None:
                print(f"      N {d['n']:>3}: {d['waits']} waits; READY not low; strobe low {d['stb_low']}")
                continue
            line = (f"      N {d['n']:>3}: {d['waits']} waits; READY low +{d['low']}, high +{d['high']} "
                    f"({d['high'] / clk:.2f} clk; {d['high'] - d['stb_low']:+d} from the strobe's rise); "
                    f"strobe low {d['stb_low']}")
            if d["before"] is not None:
                line += f" | at N {d['n'] - 1} READY high +{d['before']} ({d['before'] / clk:.2f} clk) ended it a clock sooner"
            if verbose and d["clk_rise"]:
                line += f" | CLKOUT rises {d['clk_rise'][:8]} falls {d['clk_fall'][:8]}"
            print(line)


# ------------------------------------------------------------------ READY as a level (rdy_x_*)
# The harness's READY is high outside a strobe. A level is made with the pin itself: T0 handed to
# the CPU (marker FF10h: Z, then D), P17 driven as a port output (P1 latch bit 7 = the level,
# PM1 bit 7 = 0), then PMC1 bit 7 = 1 makes it READY: the output is released and the pin keeps
# its level (nothing else drives it: the board's translator is turned toward the FPGA). The
# simulation's lane gives the core READY = 0 whenever T0 is not host-driven (v35s_harness.sv
# model_pins_in), so the low-level programs compare; the high-level control does not.
X_LIMIT = 3_000_000
X_NMI = {"entries": [{"event": 1, "delay": 6000, "hold": 400, "levels": {"NMI": 0}}],
         "pins": ["P17", "P14"]}


class XProgram:
    """level: the level P17 is left at; last: the access tried under WTC field 3 (None: none)."""

    def __init__(self, name, level, last, note):
        self.name, self.level, self.last, self.note = name, level, last, note
        self.stim, self.clk, self.prc = X_NMI, 32, None
        self.windows = [Window(0, 2, 2, note="fixed 2 waits, READY at the level"),
                        Window(0, 3, 3, note="the access under field 3")]
        self._built = None

    def build(self):
        if self._built:
            return self._built
        mem, code = base_image(True)
        a = Asm()
        a.op([0xFA], "DI")
        a.mov_r("AW", 0)
        a.mov_sr("SS")
        a.mov_r("SP", STACK_TOP)
        a.mov_sr("DS0")
        a.seg("DS1", 0xF000)
        a.sfr_w(0xE1, 0xEC)
        a.sfr_w(0xE8, fields(0, 2, 2), word=True)
        a.out_w(M_BANK, 0x0041)             # T0 and T2 released
        a.sfr_w(0x00, 0x55)
        a.sfr_w(0x01, 0x00)
        a.sfr_w(0x02, 0x80)                 # P07 = CLKOUT
        a.sfr_w(0x08, self.level << 7)      # P1 latch: P17 = the level, P14 = 0
        a.sfr_w(0x09, 0x6F)                 # PM1: P17 and P14 outputs
        a.out_w(M_BANK, 0x0082)             # T0 and T2 the CPU's
        a.nop(8)
        a.sfr_w(0x0A, 0x80)                 # PMC1 bit 7: P17 = READY (the output released)
        a.nop(8)
        a.op([0x26, 0xA0, 0x08, 0xFF], "MOV AL, DS1:[FF08h]   ; P1 as the CPU reads it")
        a.op([0xA2, 0x10, 0x0F], "MOV [0F10h], AL")
        a.out_w(M_BEGIN, 0)
        a.op([0x26, 0xA0, 0x40, 0xFE], "MOV AL, DS1:[FE40h]   ; internal RAM")
        a.op([0x26, 0xA2, 0x41, 0xFE], "MOV DS1:[FE41h], AL   ; internal RAM")
        a.op([0x26, 0xA1, 0xE8, 0xFF], "MOV AW, DS1:[FFE8h]   ; WTC")
        a.op([0x26, 0xA0, 0xFF, 0xFF], "MOV AL, DS1:[FFFFh]   ; IDB")
        a.op([0x26, 0xA2, 0x82, 0xFF], "MOV DS1:[FF82h], AL   ; MD0 (an SFR store)")
        pr = Probe(a, lambda x: mem[x])
        pr.set_ds0(DSEG)
        pr.rd(0x0100, check=False)
        pr.wr(0x0130)
        pr.rd(0x0105, word=True, check=False)
        pr.wr(0x0135, word=True)
        a.mov_r("DW", 0x0040)
        a.op([0xEC], "IN AL, DW   ; 0040", [("ior", 0x40)])
        a.op([0xEE], "OUT DW, AL   ; 0040", [("iow", 0x40)])
        a.seg("DS0", 0)
        a.out_w(0xFF12, 0x0001)             # the event: NMI 6000 ticks later
        a.op([0xF4], "HALT")
        a.nop(4)
        a.label("cont")
        a.out_w(M_END, 0)
        a.op([0x26, 0xA0, 0x08, 0xFF], "MOV AL, DS1:[FF08h]   ; P1 again")
        a.op([0xA2, 0x12, 0x0F], "MOV [0F12h], AL")
        a.out_w(M_BEGIN, 1)
        if self.last:
            a.seg("DS0", DSEG)
            a.mov_r("DW", 0x0040)
            a.mov_r("AW", 0xA55A)
            a.nop(8)
            a.sfr_w(0xE8, fields(0, 3, 3), word=True)
            a.nop(8)
            if self.last == "mr":
                a.op([0xA0, 0x00, 0x02], "MOV AL, [0200h]   ; 20200")
            elif self.last == "mw":
                a.op([0xA2, 0x30, 0x02], "MOV [0230h], AL   ; 20230")
            elif self.last == "mww":
                a.op([0xA3, 0x35, 0x02], "MOV [0235h], AW   ; 20235 (odd)")
            elif self.last == "ior":
                a.op([0xEC], "IN AL, DW   ; 0040")
            elif self.last == "iow":
                a.op([0xEE], "OUT DW, AL   ; 0040")
            elif self.last == "fetch":
                a.op([0x9A, 0x80, 0x01, CSEG & 0xFF, CSEG >> 8], f"CALL FAR {CSEG:04X}h:0180h")
            a.nop(8)
            a.sfr_w(0xE8, fields(0, 2, 2), word=True)
            a.seg("DS0", 0)
        a.out_w(M_END, 1)
        a.mov_r("DW", 0xFF00)
        a.op([0xEE], "OUT DW, AL")
        a.op([0xF4], "HALT")
        a.label("done")
        a.rel([0xEB], "done", "BR")
        a.label("nmi")
        a.out_w(M_SUB, 0x004E)
        a.op([0x83, 0xC4, 0x06], "ADD SP, 6")
        a.rel([0xE9], "cont", "BR", wide=True)
        text = a.finish()
        for i, v in enumerate(text):
            mem[ORG + i] = v
        for i, v in enumerate(a.labels["nmi"].to_bytes(2, "little") + b"\0\0"):
            mem[0x00008 + i] = v
        for i, v in enumerate(bytes([0xEA, ORG & 0xFF, ORG >> 8, 0, 0])):
            mem[0xFFFF0 + i] = v
        segments = {}
        for pg in sorted({x >> 12 for x in mem}):
            segments[pg << 12] = bytes(mem[pg << 12 | o] for o in range(0x1000))
        self._built = dict(text=text, lines=a.lines, segments=segments, groups=[],
                           code=[(ORG, ORG + len(text)), (0xFFFF0, 0xFFFF5)] + code)
        return self._built

    source = Program.source
    holds, x_halfs = [0], [2]


def xprograms():
    progs = [XProgram("rdy_x_hi", 1, "mw", "READY left high (the control): every access completes"),
             XProgram("rdy_x_lo", 0, None, "READY left low: on-chip, fixed-wait blocks, HALT / NMI"),
             XProgram("rdy_x_mr", 0, "mr", "READY left low, then a byte read under field 3"),
             XProgram("rdy_x_mw", 0, "mw", "READY left low, then a byte write under field 3"),
             XProgram("rdy_x_mww", 0, "mww", "READY left low, then an odd word write under field 3"),
             XProgram("rdy_x_ior", 0, "ior", "READY left low, then IN under field 3"),
             XProgram("rdy_x_iow", 0, "iow", "READY left low, then OUT under field 3"),
             XProgram("rdy_x_f", 0, "fetch", "READY left low, then a far call into a field-3 block")]
    return {p.name: p for p in progs}


def static_one(harness, prog, lane):
    """The run's trace (pin records kept), then the same run with the scope on its last
    6000 ticks before the last record's end and 9000 after."""
    from .scope import Scope, edges
    b = prog.build()
    mode = "socket" if lane == "socket" else "model"
    harness.debug.write16(0x0A, 0)
    harness.load(b["segments"])
    result = harness.run(mode, X_LIMIT)
    rows = [[t["start"], t["address"], t["data"], t["flags"], t["end"], t["strobe"]]
            for t in result[f"{lane}_trace"]]
    last = rows[-1][4] if rows else 0
    harness.load(b["segments"])
    scope = Scope(harness.debug)
    scope.configure(lane, max(0, last - 6000), last + 9000)
    again = harness.run(mode, X_LIMIT)
    capture = scope.download()
    rows2 = [[t["start"], t["address"], t["data"], t["flags"], t["end"], t["strobe"]]
             for t in again[f"{lane}_trace"]]
    ev = [[e.tick - last, e.signal, e.value] for e in edges(capture, SCOPE_SIGNALS)]
    return dict(program=prog.name, note=prog.note, passed=result["passed"], status=result["status"],
                timeout=result["timeout"], total=result[f"{lane}_total"], trace=rows,
                again_equal=[r[1:4] + [r[4] - r[0], r[5]] for r in rows] == [r[1:4] + [r[4] - r[0], r[5]] for r in rows2],
                again_last=rows2[-1][4] if rows2 else 0,
                p1_read=[harness.read_memory(lane, 0x0F10, 1).hex(), harness.read_memory(lane, 0x0F12, 1).hex()],
                scope=dict(reason=capture.reason, first=capture.first_tick - last,
                           last=capture.last_tick - last, zero="the trace's last record's end",
                           edges=ev))


def static_set(names, backend, tag):
    from .traps import _board, _close_board, _sim, _stim
    progs = xprograms()
    lane = "socket" if backend == "socket" else "model"
    if backend == "socket":
        transport, harness = _board()
    try:
        for name in names or list(progs):
            prog = progs[name]
            if backend != "socket":
                transport, harness = _sim()
            try:
                _stim(harness, prog)
                rec = static_one(harness, prog, lane)
            finally:
                if backend != "socket":
                    transport.close()
            rec.update(backend=backend, date=datetime.datetime.now().isoformat(timespec="seconds"),
                       program_sha256=hashlib.sha256(prog.build()["text"]).hexdigest())
            receipt_path(name, backend + tag).write_text(json.dumps(rec, separators=(",", ":")) + "\n")
            print(f"{name}: {backend}{tag} {'PASS' if rec['passed'] else 'no pass'} status=0x{rec['status']:04x} "
                  f"timeout={rec['timeout']} total={rec['total']} P1 read {rec['p1_read']} "
                  f"scope {rec['scope']['reason']} {len(rec['scope']['edges'])} edges, rerun equal {rec['again_equal']}",
                  flush=True)
    finally:
        if backend == "socket":
            _close_board(transport, harness)


def static_report(names, backend):
    """Per program: the pin records of P17, the windows' cycles, and the pins after the last
    completed cycle (the stalled access)."""
    progs = xprograms()
    for name in names or list(progs):
        prog = progs[name]
        rec = json.loads(receipt_path(name, backend).read_text())
        rows = rec["trace"]
        code = prog.build()["code"]
        print(f"{name} [{backend}]: {prog.note}: passed {rec['passed']} timeout {rec['timeout']} "
              f"records {rec['total']}; P1 read {rec['p1_read']}")
        pins = [(r[0], (r[1] >> 15) & 1, (r[1] >> 12) & 1) for r in rows if r[3] & FLAG_PIN]
        print(f"  pin records (tick, P17, P14): {pins}")
        wins, head = cut(rows, prog)
        for k, w in wins.items():
            print(f"  w{k}: " + " ".join(f"{r[0]}:{r[1]:05X}/{waits(r[3], 32)}w" for r in w if r[0] != "fetch")
                  + f"  [{sum(1 for r in w if r[0] == 'fetch')} fetches; ends +{w[-1][5] + w[-1][3] if w else 0}]")
        tail = rows[-4:]
        print("  last records: " + "; ".join(f"{kind_of(r, code)} {r[1]:05X} len {r[4] - r[0]}" for r in tail))
        ev = [e for e in rec["scope"]["edges"] if e[0] > 0 and e[1] not in ("clkout",)]
        print(f"  after the last record (ticks from its end; scope to +{rec['scope']['last']}): "
              + (" ".join(f"{t}:{sig}={v:X}" for t, sig, v in ev[:40]) or "no edge"))



def edges_compare(name, ref, cand, progs):
    """The sweep's steps side by side: per window and group of cycles, the first N of each
    length in both receipts and the candidate's N minus the reference's."""
    prog, a, b = progs[name], load(name, ref), load(name, cand)
    print(f"{name}: first N of each length, {ref} / {cand} (clock {prog.clk} ticks at x_half 2)")
    worst = 0
    for x in prog.x_halfs:
        ta, tb = sweep_table(a, prog, x), sweep_table(b, prog, x)
        if len(prog.x_halfs) > 1:
            print(f" x_half {x} (clock {prog.clk * x // 2} ticks)")
        for k, w in enumerate(prog.windows):
            da, db = dict(ta.get(k, [])), dict(tb.get(k, []))
            groups = {}
            for label in da:
                sa, sb = da[label], db.get(label)
                groups.setdefault((fmt_steps(sa), fmt_steps(sb) if sb else "absent"), []).append((label, sa, sb))
            lines = []
            for (fa, fb), members in groups.items():
                if fa == fb:
                    continue
                label, sa, sb = members[0]
                kinds = Counter(m[0].split()[0] for m in members)
                who = ", ".join(f"{kd} x{c}" for kd, c in kinds.items())
                if sb and [v for _, v in sa] == [v for _, v in sb]:
                    d = sorted({nb - na for (na, _), (nb, _) in zip(sa, sb)})
                    worst = max(worst, max(abs(v) for v in d))
                    lines.append(f"      {who}: same lengths, first N differs by {d} ticks ({ref}: {fa[:60]}...; {cand}: {fb[:60]}...)")
                else:
                    worst = 999
                    lines.append(f"      {who}: {ref}: {fa[:110]} | {cand}: {fb[:110]}")
            print(f"  w{k} ({w.name()}): " + ("equal" if not lines else ""))
            for ln in lines:
                print(ln)
    return worst



def follow(name, ref, cand, progs):
    """What a stretched cycle moves: per window, its length (the begin marker's end to the end
    marker's start) at each N less its length at the first N, in clocks, in both receipts.
    On the socket the growth is the extra waits of the window's READY-governed cycles and
    nothing else; a candidate whose execution unit runs on behind a stretched cycle grows less."""
    prog, a, b = progs[name], load(name, ref), load(name, cand)
    clk = prog.clk

    def ends(rec, n):
        out = {}
        for k, rows in windows_of(rec, run_key(n, 2)).items():
            e = [r for r in rows if r[0] == "end"]
            out[k] = (e[0][5] if e else None, sum(1 for r in rows if r[0] == "fetch"))
        return out

    a0, b0 = ends(a, prog.holds[0]), ends(b, prog.holds[0])
    ok = True
    print(f"{name}: window growth over N {prog.holds[0]}, clocks, {ref} / {cand} (change in the number of fetches)")
    for k in sorted(a0):
        line, bad = [], 0
        for n in prog.holds[1:]:
            ea, eb = ends(a, n), ends(b, n)
            if k not in ea or k not in eb or ea[k][0] is None or eb[k][0] is None:
                continue
            ga, gb = round((ea[k][0] - a0[k][0]) / clk), round((eb[k][0] - b0[k][0]) / clk)
            fa, fb = ea[k][1] - a0[k][1], eb[k][1] - b0[k][1]
            if ga != gb or fa != fb:
                bad += 1
                if len(line) < 5:
                    line.append(f"N {n}: {ga} / {gb} ({fa:+d} / {fb:+d})")
        ok &= not bad
        print(f"  w{k} ({prog.windows[k].name()}): "
              + ("the same at every N" if not bad else f"{bad} N differ: " + ", ".join(line)))
    return ok


def static_gate(names, ref, cand):
    """rdy_x_*: the level programs, two receipts: passed / timed out alike, the fixed window's
    data cycles (kind, address, waits) alike, the same last completed data cycle, and the
    stalled cycle's pins (which strobes are down after the last record)."""
    progs = xprograms()
    ok = True
    for name in names or [n for n in progs if n != "rdy_x_hi"]:
        prog = progs[name]
        a = json.loads(receipt_path(name, ref).read_text())
        b = json.loads(receipt_path(name, cand).read_text())
        res = []
        for rec in (a, b):
            wins, head = cut(rec["trace"], prog)
            w0 = [(r[0], r[1], waits(r[3], 32)) for r in data_cycles(wins.get(0, []))]
            low = sorted({sig for t, sig, v in rec["scope"]["edges"]
                          if t > 0 and sig in ("mreq_n", "mstb_n", "iostb_n") and v == 0}
                         - {sig for t, sig, v in rec["scope"]["edges"]
                            if t > 200 and sig in ("mreq_n", "mstb_n", "iostb_n") and v == 1})
            res.append((rec["passed"], rec["timeout"], w0, len(data_cycles(wins.get(1, []))), low))
        same = res[0] == res[1]
        ok &= same
        print(f"{name}: {ref} / {cand}: {'EQUAL' if same else 'DIFFER'} (passed {res[0][0]} / {res[1][0]}, "
              f"timed out {res[0][1]} / {res[1][1]}; strobes left low {res[0][4]} / {res[1][4]})")
    return ok



# ------------------------------------------------------------------ READY from /MREQ's fall (rdy_m*)
# Harness version 3 (registers C2h / C4h / C6h): READY low from `delay` to `delay + hold` ticks
# after a cycle's start tick, for cycles of the selected blocks; a cycle that starts inside a
# window starts none. The probe routine runs in block 2 (40200h, 0 waits, not selected), so only
# the data block's cycles (block 1) and the I/O cycles and the main program's cycles (block 0:
# the markers, the stack) start windows. A sweep is a list of (delay, hold); a run's key is
# "<sweep>:<delay>:<hold>".
M_PROBE = 0x40200
M_BLOCKS = 0x03
M_TRIG = 3                  # read and write cycles


def sub_medge(a: Asm, mem):
    """sub_edge's cycles (each after idle), then pairs with no idle between."""
    p = Probe(a, lambda x: mem[x])
    p.set_ds0(DSEG)
    a.mov_r("DW", 0x0040)
    gap(a, 8)
    p.rd(0x0100, check=False)
    gap(a, 8)
    p.wr(0x0130)
    gap(a, 8)
    p.rd(0x0102, word=True, check=False)
    gap(a, 8)
    p.wr(0x0132, word=True)
    gap(a, 8)
    p.rd(0x0105, word=True, check=False)        # odd: two byte cycles
    gap(a, 8)
    p.wr(0x0135, word=True)
    gap(a, 8)
    a.op([0xFE, 0x06, 0x60, 0x01], f"INC byte [0160h]   ; {D0 + 0x60:05X}",
         [("mr", D0 + 0x60), ("mw", D0 + 0x60)])
    gap(a, 8)
    a.op([0xEC], "IN AL, DW   ; 0040", [("ior", 0x40)])
    gap(a, 8)
    a.op([0xEE], "OUT DW, AL   ; 0040", [("iow", 0x40)])
    gap(a, 8)
    a.op([0xED], "IN AW, DW   ; 0040", [("ior", 0x40)])
    gap(a, 8)
    a.op([0xEF], "OUT DW, AW   ; 0040", [("iow", 0x40)])
    gap(a, 8)
    a.op([0x9A, 0x80, 0x01, CSEG & 0xFF, CSEG >> 8], f"CALL FAR {CSEG:04X}h:0180h   ; the stub in the data block")
    gap(a, 8)
    # pairs: read then write, write then read, read then read, write then write
    for first, second in (("r", "w"), ("w", "r"), ("r", "r"), ("w", "w")):
        for k, kind in enumerate((first, second)):
            off = 0x0170 + 0x10 * "rw".index(kind) + 2 * k + 8 * ("rw".index(first) * 2 + "rw".index(second))
            if kind == "r":
                p.rd(off, check=False)
            else:
                p.wr(off)
        gap(a, 8)
    a.seg("DS0", 0)


def sub_mscope(a: Asm, mem):
    p = Probe(a, lambda x: mem[x])
    p.set_ds0(DSEG)
    a.mov_r("DW", 0x0040)
    gap(a, 8)
    p.rd(0x0100, check=False)
    gap(a, 8)
    p.wr(0x0130)
    gap(a, 8)
    a.op([0xEC], "IN AL, DW   ; 0040", [("ior", 0x40)])
    gap(a, 8)
    a.op([0xEE], "OUT DW, AL   ; 0040", [("iow", 0x40)])
    gap(a, 8)
    p.wr(0x0135, word=True)
    gap(a, 8)
    a.seg("DS0", 0)


class MProgram(Program):
    """A program whose probe routine runs in block 2 (CALL FAR 4000h:0200h) and whose runs are
    sweeps of the /MREQ-timed READY."""

    def __init__(self, name, windows, sub, note="", prc=None, sweeps=None, clkout=False):
        super().__init__(name, windows, sub, note, prc=prc, clkout=clkout)
        self.sweeps = sweeps or {}

    def mruns(self):
        return [(f"{sw}:{d}:{h}", d, h) for sw, pts in self.sweeps.items() for d, h in pts]

    def build(self):
        if self._built:
            return self._built
        mem, code = base_image(True)
        a = Asm()
        a.op([0xFA], "DI")
        a.mov_r("AW", 0)
        a.mov_sr("SS")
        a.mov_r("SP", STACK_TOP)
        a.mov_sr("DS0")
        a.seg("DS1", 0xF000)
        a.sfr_w(0xE1, 0xEC)
        if self.clkout:
            a.out_w(M_BANK, 0x0001)
            a.sfr_w(0x00, 0x55)
            a.sfr_w(0x01, 0x00)
            a.sfr_w(0x02, 0x80)
            a.out_w(M_BANK, 0x0002)
        if self.prc is not None:
            a.sfr_w(0xEB, self.prc)
        pmc1 = 0x00
        for k, w in enumerate(self.windows):
            a.lines.append((b"", f"; ---- window {k}: WTC {w.wtc:04X}h PMC1 {w.pmc1:02X}h ({w.name()}) {w.note}"))
            if w.pmc1 != pmc1:
                a.sfr_w(0x0A, w.pmc1)
                pmc1 = w.pmc1
            a.sfr_w(0xE8, w.wtc, word=True)
            a.out_w(M_BEGIN, k)
            a.op([0x9A, M_PROBE & 0xFF, M_PROBE >> 8 & 0xFF, 0x00, M_PROBE >> 16 << 4],
                 f"CALL FAR {M_PROBE >> 16 << 12:04X}h:{M_PROBE & 0xFFFF:04X}h   ; the probe routine, in block 2")
            a.nop(8)
            a.out_w(M_END, k)
        a.sfr_w(0xE8, 0xFFFF, word=True)
        a.sfr_w(0x0A, 0x00)
        a.mov_r("DW", 0xFF00)
        a.op([0xEE], "OUT DW, AL")
        a.op([0xF4], "HALT")
        a.label("done")
        a.rel([0xEB], "done", "BR")
        text = a.finish()
        for i, v in enumerate(text):
            mem[ORG + i] = v
        for i, v in enumerate(bytes([0xEA, ORG & 0xFF, ORG >> 8, 0, 0])):
            mem[0xFFFF0 + i] = v
        pa = Asm(M_PROBE)
        pa.groups = []
        self.sub(pa, mem)
        pa.nop(8)
        pa.op([0xCB], "RETF")
        ptext = pa.finish()
        for i, v in enumerate(ptext):
            mem[M_PROBE + i] = v
        a.lines.append((b"", f"; the probe routine at {M_PROBE:05X}h:"))
        a.lines += pa.lines
        segments = {}
        for pg in sorted({x >> 12 for x in mem}):
            segments[pg << 12] = bytes(mem[pg << 12 | o] for o in range(0x1000))
        self._built = dict(text=text + ptext, lines=a.lines, segments=segments, groups=pa.groups,
                           code=[(ORG, ORG + len(text)), (0xFFFF0, 0xFFFF5),
                                 (M_PROBE, M_PROBE + len(ptext))] + code)
        return self._built


def m_sweeps(clk):
    step = max(1, clk // 8)
    return {"rise": [(0, h) for h in range(1, 5 * clk + 1)],
            "fall": [(d, clk) for d in range(0, 15 * clk // 4 + 1)],
            "pulse": [(d, 2) for d in range(0, 15 * clk // 4 + 1)],
            "carry": [(d, 2 * clk) for d in range(0, 12 * clk + 1, step)]}


def s_sweeps(clk):
    return {"rise": [(0, h) for h in range(3 * clk // 2, 7 * clk // 2 + 1)],
            "fall": [(d, clk) for d in range(3 * clk // 2, 7 * clk // 2 + 1)],
            "stall": [(0, 6 * clk)]}


def mprograms():
    win = [Window(0, 2, 2, note="fixed 2 waits"), Window(0, 3, 3, note="READY: data and I/O")]
    progs = []
    for tag, prc, clk in (("8", None, 32), ("4", 0x4D, 16), ("2", 0x4C, 8)):
        progs.append(MProgram(f"rdy_m{tag}", win, sub_medge, f"READY from /MREQ's fall: the edge "
                              f"probe at fX/{tag}", prc=prc, sweeps=m_sweeps(clk)))
        progs.append(MProgram(f"rdy_ms{tag}", win[1:], sub_mscope, f"READY from /MREQ's fall: the "
                              f"scope probe at fX/{tag}, CLKOUT on P07", prc=prc, sweeps=s_sweeps(clk),
                              clkout=True))
    return {p.name: p for p in progs}


def _m_job(args):
    name, key, d, h, scope = args
    from .traps import _sim, _stim
    prog = mprograms()[name]
    transport, harness = _sim()
    try:
        _stim(harness, prog)
        if scope:
            return key, scope_one(harness, prog, "model", 0, 2, m=(d, h, M_TRIG, M_BLOCKS), full=True)
        return key, run_one(harness, prog, "model", 0, 2, m=(d, h, M_TRIG, M_BLOCKS))
    finally:
        transport.close()


def m_run_set(names, backend, tag, jobs=8, sweeps=None):
    """Trace receipts for rdy_m8 / m4 / m2, scope receipts for rdy_ms8 / ms4 / ms2."""
    from .traps import _board, _close_board, _stim
    progs = mprograms()

    def save(prog, results):
        if prog.clkout:
            rec = dict(program=prog.name, note=prog.note, clk_ticks=prog.clk, backend=backend,
                       program_sha256=hashlib.sha256(prog.build()["text"]).hexdigest(),
                       date=datetime.datetime.now().isoformat(timespec="seconds"),
                       ticks="relative to the tick /MREQ's fall is sampled; 30 ns", runs=results)
            receipt_path(prog.name, f"{backend}{tag}-scope").write_text(json.dumps(rec, separators=(",", ":")) + "\n")
            bad = [k for k, r in results.items() if not r["passed"] or r["capture"] != "complete"]
            print(f"{prog.name}: scope {backend}{tag} {len(results)} runs, not passed / incomplete: {bad or 'none'}",
                  flush=True)
        else:
            write(prog, results, backend, tag)

    todo = {n: [(k, d, h) for k, d, h in progs[n].mruns() if sweeps is None or k.split(":")[0] in sweeps]
            for n in names or list(progs)}
    if backend == "socket":
        transport, harness = _board()
        try:
            for name, runs in todo.items():
                prog = progs[name]
                _stim(harness, prog)
                res = {}
                for key, d, h in runs:
                    m = (d, h, M_TRIG, M_BLOCKS)
                    res[key] = (scope_one(harness, prog, "socket", 0, 2, m=m, full=True) if prog.clkout
                                else run_one(harness, prog, "socket", 0, 2, m=m))
                save(prog, res)
        finally:
            _close_board(transport, harness)
    else:
        from multiprocessing import Pool
        with Pool(jobs) as pool:
            for name, runs in todo.items():
                prog = progs[name]
                save(prog, dict(pool.map(_m_job, [(name, k, d, h, prog.clkout) for k, d, h in runs])))


def m_labels(rows, clk):
    """A window's cycles named: {label: (waits, start offset, length)}; the fetches of block 1
    as one entry (the set of their waits)."""
    out, seen, fw = {}, Counter(), set()
    for r in rows:
        if r[0] in DATA:
            seen[(r[0], r[1])] += 1
            lb = f"{r[0]} {r[1]:05X}" + (f" #{seen[(r[0], r[1])]}" if seen[(r[0], r[1])] > 1 else "")
            out[lb] = (waits(r[3], clk), r[5], r[3])
        elif r[0] == "fetch" and r[1] >> 17 == 1:
            fw.add(waits(r[3], clk))
    out["fetch block 1"] = ("/".join(str(v) for v in sorted(fw)), 0, 0)
    return out


def m_table(rec, prog, sweep, k=None):
    """{label: steps} for a sweep: the waits against the swept value (hold for `rise`, delay
    otherwise), window k (default the last, the READY window)."""
    k = len(prog.windows) - 1 if k is None else k
    per = {}
    for d, h in prog.sweeps[sweep]:
        key = f"{sweep}:{d}:{h}"
        if key not in rec["runs"]:
            continue
        rows = windows_of(rec, key).get(k)
        if rows is None:
            continue
        for lb, (w, st, ln) in m_labels(rows, prog.clk).items():
            per.setdefault(lb, []).append((h if sweep == "rise" else d, w))
    return {lb: steps(seq) for lb, seq in per.items()}


def m_summary(names, backend, verbose=False):
    progs = mprograms()
    for name in names or [n for n in progs if not progs[n].clkout]:
        prog = progs[name]
        rec = load(name, backend)
        clk = prog.clk
        print(f"{name} [{backend}]: {prog.note}; a clock is {clk} ticks; READY low from delay to delay + hold "
              f"ticks after the cycle's start tick")
        for sweep in prog.sweeps:
            what = {"rise": "low from 0, the rise at `hold` swept", "fall": f"a pulse of {clk} ticks (one clock), its fall swept",
                    "pulse": "a pulse of 2 ticks, its place swept",
                    "carry": f"a pulse of {2 * clk} ticks from the first cycle's start (a pair's second cycle starts no window inside it)"}[sweep]
            print(f"  {sweep} ({what}): waits@first value")
            groups = {}
            for lb, st in m_table(rec, prog, sweep).items():
                groups.setdefault(fmt_steps(st), []).append(lb)
            for st, lbs in groups.items():
                print(f"      {', '.join(lbs) if verbose or len(lbs) <= 6 else str(len(lbs)) + ' cycles: ' + ', '.join(lbs[:6]) + ' ...'}: {st}")
        ctl = {fmt_steps(st) for sw in prog.sweeps for st in m_table(rec, prog, sw, 0).values()}
        print(f"  window 0 (fixed 2 waits), every sweep: {sorted(ctl)}")


def m_compare(names, ref, cand, quiet=False):
    """Run by run, the READY window's and the fixed window's cycles (kind, address, waits) in
    order; a run whose waits are the reference's at a swept value within EDGE_TICKS counts as
    the edge."""
    progs = mprograms()
    ok = True
    for name in names or [n for n in progs if not progs[n].clkout]:
        prog, a, b = progs[name], load(name, ref), load(name, cand)
        if a["program_sha256"] != b["program_sha256"]:
            print(f"{name}: the receipts are of different programs")
            ok = False
            continue
        for sweep, pts in prog.sweeps.items():
            same = edge = 0
            diff = []

            def cyc(rec, d, h, k):
                key = f"{sweep}:{d}:{h}"
                if key not in rec["runs"] or str(k) not in rec["runs"][key]["wins"]:
                    return None
                rows = rec["blobs"][rec["runs"][key]["wins"][str(k)]]
                return [(r[0], r[1], waits(r[3], prog.clk)) for r in rows if r[0] in DATA] + \
                       [("fetch", 0, tuple(sorted({waits(r[3], prog.clk) for r in rows
                                                   if r[0] == "fetch" and r[1] >> 17 == 1})))]

            stepv = pts[1][1] - pts[0][1] if sweep == "rise" else pts[1][0] - pts[0][0]
            for d, h in pts:
                for k in range(len(prog.windows)):
                    x, y = cyc(a, d, h, k), cyc(b, d, h, k)
                    if x is None or y is None:
                        continue
                    if x == y:
                        same += 1
                        continue
                    near = [cyc(a, d + (0 if sweep == "rise" else e * stepv), h + (e * stepv if sweep == "rise" else 0), k)
                            for e in range(-EDGE_TICKS, EDGE_TICKS + 1) if e]
                    near = [n for n in near if n is not None]
                    if [v[:2] for v in x] == [v[:2] for v in y] and all(
                            p == q or any(n[i] == q for n in near) for i, (p, q) in enumerate(zip(x, y))):
                        edge += 1
                    else:
                        i = next((i for i, (p, q) in enumerate(zip(x, y)) if p != q), 0)
                        diff.append((d, h, k, x[i], y[i]))
            ok &= not diff
            print(f"{name} {sweep}: {ref} / {cand}: {'EQUAL' if not diff else 'DIFFER'} ({same} run-windows equal, "
                  f"{edge} within {EDGE_TICKS} step(s) of an edge, {len(diff)} differ)")
            if not quiet:
                for d, h, k, p, q in diff[:4]:
                    print(f"    delay {d} hold {h} w{k}: {p} / {q}")
    return ok


def m_scope_table(names, backend):
    """Per scope program and cycle: the sweep's steps with READY's edges, the strobe's and
    CLKOUT's as ticks from /MREQ's fall."""
    progs = mprograms()
    for name in names or [n for n in progs if progs[n].clkout]:
        prog = progs[name]
        rec = load(name, backend + "-scope")
        clk = prog.clk
        print(f"{name} [{backend}] scope: a clock is {clk} ticks; ticks from the tick /MREQ's fall is seen")
        for sweep, pts in prog.sweeps.items():
            ncyc = max(len(rec["runs"][f"{sweep}:{d}:{h}"]["cycles"]) for d, h in pts)
            for c in range(ncyc):
                last, prev, lines, head = None, None, [], None
                for d, h in pts:
                    cy = rec["runs"][f"{sweep}:{d}:{h}"]["cycles"]
                    if c >= len(cy) or "error" in cy[c]:
                        continue
                    cy = cy[c]
                    w = waits(cy["length"], clk)
                    if head is None:
                        head = f"{cy['kind']} {cy['address']:05X}"
                    if w != last:
                        cf = [t for t in cy["clk_fall"] if -clk < t < 5 * clk]
                        line = (f"      delay {d} hold {h}: {w} waits; READY edges {cy['rdy_edges'][:4]}; strobe "
                                f"falls +{cy['stb_fall']} rises +{cy['stb_rise']}; CLKOUT falls {cf}")
                        if prev is not None:
                            line += f" | one step before: READY edges {prev['rdy_edges'][:4]}, {last} waits"
                        lines.append(line)
                        last = w
                    prev = cy
                print(f"  {sweep}, {head}:")
                for ln in lines:
                    print(ln)


def emit(progs):
    for name, prog in list(progs.items()) + list(xprograms().items()) + list(mprograms().items()):
        (PROGRAMS_DIR / f"{name}.s").write_text(prog.source())
        print(f"{name}: {len(prog.build()['text'])} bytes, {len(prog.windows)} windows")
        if getattr(prog, "stim", None):
            (PROGRAMS_DIR / f"{name}.stim.json").write_text(json.dumps(prog.stim, indent=1) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "summary", "repeat", "gate", "emit", "scope", "scopetable", "static", "staticreport", "staticgate", "edges", "follow",
                                     "msocket", "msim", "msummary", "mrepeat", "mgate", "mscopetable"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--backend", default="socket", help="scope: socket or sim")
    p.add_argument("--edge-ticks", type=int, default=1, help="gate / repeat: the edge allowance")
    p.add_argument("--sweeps", nargs="*", help="msocket / msim: only these sweeps")
    p.add_argument("--only", type=int, nargs="*", help="only these READY holds")
    p.add_argument("--socket-fitted", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    global EDGE_TICKS
    EDGE_TICKS = a.edge_ticks
    progs = programs()
    # the scope programs have their own actions; rdy_r2 is silicon only; rdy_i8's cycles depend
    # on where the interrupt lands (reported, not gated)
    names = a.names or [n for n in progs if not n.startswith("rdy_s") and
                        (n != "rdy_r2" or a.action in ("socket", "repeat", "emit", "summary")) and
                        (n != "rdy_i8" or a.action != "gate")]
    if a.action == "socket":
        if not a.socket_fitted:
            p.error("the socket action needs --socket-fitted")
        run_set(names, "socket", a.tag, progs, only=a.only)
    elif a.action == "sim":
        run_set(names, "sim", a.tag, progs, jobs=a.jobs, only=a.only)
    elif a.action == "scope":
        if a.backend == "socket" and not a.socket_fitted:
            p.error("the socket needs --socket-fitted")
        scope_set(a.names or ["rdy_s8", "rdy_s2"], a.backend, a.tag, progs, a.jobs, a.only)
    elif a.action == "scopetable":
        for n in a.names or ["rdy_s8", "rdy_s2"]:
            scope_table(n, a.backend + a.tag, progs, a.verbose)
    elif a.action == "static":
        if a.backend == "socket" and not a.socket_fitted:
            p.error("the socket needs --socket-fitted")
        static_set(a.names, a.backend, a.tag)
    elif a.action == "staticreport":
        static_report(a.names, a.backend + a.tag)
    elif a.action == "edges":
        for n in names:
            edges_compare(n, a.ref, a.cand, progs)
    elif a.action == "msocket":
        if not a.socket_fitted:
            p.error("the socket action needs --socket-fitted")
        m_run_set(a.names, "socket", a.tag, sweeps=a.sweeps)
    elif a.action == "msim":
        m_run_set(a.names, "sim", a.tag, a.jobs, sweeps=a.sweeps)
    elif a.action == "msummary":
        m_summary(a.names, a.ref + a.tag, a.verbose)
    elif a.action == "mrepeat":
        return 0 if m_compare(a.names, "socket", "socket-2") else 1
    elif a.action == "mgate":
        return 0 if m_compare(a.names, a.ref, a.cand) else 1
    elif a.action == "mscopetable":
        m_scope_table(a.names, a.backend + a.tag)
    elif a.action == "staticgate":
        return 0 if static_gate(a.names, a.ref, a.cand) else 1
    elif a.action == "follow":
        ok = True
        for n in a.names or ["rdy_k8", "rdy_k2", "rdy_f8", "rdy_f2"]:
            ok &= follow(n, a.ref, a.cand, progs)
        return 0 if ok else 1
    elif a.action == "summary":
        for n in names:
            summary(n, a.ref + a.tag, progs, a.verbose)
    elif a.action == "repeat":
        ok = True
        for n in names:
            ok &= compare(n, "socket", "socket-2", progs, exact=False)
            compare(n, "socket", "socket-2", progs, exact=True)
        return 0 if ok else 1
    elif a.action == "gate":
        ok = True
        for n in names:
            ok &= compare(n, a.ref, a.cand, progs, exact=False)
        return 0 if ok else 1
    else:
        emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
