"""F5: phase from reset (the f5_ph_* program set): where the interrupt request's path, the timer
registers' divide-by-six grid and the timers' count clocks sit against the reset release and
the first fetch at FFFF0h, on the socketed uPD70337 and on the core v2 RTL in simulation.

Every tick in a receipt counts from the reset release (the harness's run tick 0, an X1 falling
edge). A trace longer than 2,048 records is taken in several runs; each rerun overlaps the
records held and is shifted onto them (aligned stitching: the median difference over the
overlap; the largest residual is kept in the receipt). The absolute clock of an event is
(its tick - the FFFF0h fetch's start tick) / 32 in that stitched trace.

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.phase socket --socket-fitted [NAME ...] [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.phase sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.phase report [NAME ...] [--ref socket] [-v]
    PYTHONPATH=host/src:. python3 -m validation.v35s.phase repeat [NAME ...]      (socket / socket-2)
    PYTHONPATH=host/src:. python3 -m validation.v35s.phase gate [NAME ...]        (socket / sim)
    PYTHONPATH=host/src:. python3 -m validation.v35s.phase emit
    ... phase resets [--backend sim] [--socket-fitted] [--tag -2]     (f5_ph_r, 64 resets)
    ... phase resets report [--backend sim] [--tag -2]
    ... phase intr [--backend sim] [--socket-fitted] [--tag -2]       (intr.py's f5_si_edge, timed)
    ... phase intr report [--backend sim] [--tag -2]
    ... phase socket f5_ph_e --delays 3676:8 --tag=-d3676             (the edge's delays; then
        report f5_ph_e --tag=-d3676, gate f5_ph_e --ref socket-d3676 --cand sim-d3676)

    f5_ph_a    a request set by a store (EXIC0 IF, IE 0), then EI behind a sled swept one clock
               at a time: the sled between the store and EI (x), in front of the store (y),
               level 0 (x0); the take's boundary and clock
    f5_ph_b    the same with the request from the INTP0 pin (the event port), sled between (x)
    f5_ph_c    the pin request: sled in front (y); EI then REP MOVBKW with CW 0 (f5_si_edge's
               shape) behind the sled (r)
    f5_ph_e    the INTP0 edge against the request flag: EXIC0 masked and read six times, the
               edge's delay swept by the schedule (--delays BASE:STEP); f5_ph_e1 the same with
               the prelude one clock longer
    f5_ph_g    the timer grid against reset: TMC0 byte stores swept with the external twin,
               TOUT at /6, /12 (one-shot) and /128, refresh off from the prelude; f5_ph_g1 the
               RFM store first of all; f5_ph_g2 refresh left on to the end; f5_ph_g3 refresh
               off after twelve fillers
    f5_ph_t    TM0's request (TMIC0) with IE 1 in an INC train: the take against the count-out
               (TOUT), EI's place swept
    f5_ph_s    f5_si_edge's movbkw_n0 (EI ; REP MOVBKW 0 behind POP PSW / POP AW) with a sled
    f5_ph_d    DI (NOP, CLC, nothing) at a far jump's target in front of a store
    f5_ph_r    the reset: a short program taken many times (`resets`: the FFFF0h fetch's tick
               over repeated resets and reset-hold lengths)
    si_edge    intr.py's f5_si_edge kept as a timed trace (`intr` action; the head only)

Receipts: validation/v35s/receipts/f5-<name>-<backend>.json.

Measured on the uPD70337 (2026-11-19, two equal captures of each): the FFFF0h fetch starts 25
CPU clocks after the first clock boundary after the release (804 to 832 ticks: the chip's clock
divider is not reset), the RTL's too; a timer register's cycle ends at 0 mod 6 clocks from that
boundary under every prelude and with refresh running, TOUT's /6 count edges at 2.5 mod 6, the
one-shot's /12 count-out at 8.5 mod 12, the /128 count-outs on /12 edges (132, 132, 120 clocks
apart); with a request pending the take after EI is at one clock whatever the absolute phase
(50 clocks after the anchor at level 7, 37 at level 0), but for two phases in 18 clocks of the
distance from the request control store; the INTP0 edge detector's two-clock lattice follows
the store in front of it, not reset. The RTL at 0c76faa passes the request through two
registers on a toggle from reset (`ph`): its take alternates with the absolute parity.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import statistics
import sys
from pathlib import Path

from . import onchip_t as oc
from .wtc import Asm, CLK, FLAG_PIN, FLAG_REFRESH, pat

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS_DIR = ROOT / "validation/v35s/programs"
RECEIPTS = ROOT / "validation/v35s/receipts"

ORG, CODE, CODE_PAGES, STACK_TOP = oc.ORG, oc.CODE, oc.CODE_PAGES, oc.STACK_TOP
ON, OFF = oc.ON, oc.OFF
M_BEGIN, M_END = oc.M_BEGIN, oc.M_END
HANDLER = 0x0C00                # FINT ; RETI (every vector)
ANCHOR = 0xF800                 # DS0 3000h: the data byte at 3F800h (block 1)
EXIC0, TMIC0 = 0xFF4C, 0xFF9C
CAPTURE, OVERLAP = 2048, 64
P15 = oc.P15
PORT_EVENT = 0xFF12
NINC = 12


def wtc1(a, w):
    """WTC for block 1 (20000h-3FFFFh: the data page 3F000h): w waits; every other block 0."""
    oc.es_store(a, 0xFFE8, w << 2, word=True)


def sled(a, s):
    """A read in block 1 (MOV AH,[BW]: DS0 3000h; its cycle one clock longer when the window's
    WTC gives block 1 a wait, `wtc1(a, s & 1)` in the setup), then ROL BP by 8 + s // 2 (2 clocks
    a count): s clocks more than sled(0). The long rotate is last, so the queue is full and the
    bus idle after every length. (Register-only instructions of different lengths do not serve:
    CLC / CBW / NOP are absorbed by the fetches, and CVTDB / CVTBD differ by 1 or 2 clocks by
    their surroundings, on silicon as in the RTL.)"""
    a.op([0x8A, 0x27], "MOV AH, [BW]   ; block 1: the sled's odd clock is its wait")
    oc.roli(a, 8 + s // 2)


def event(a, n):
    a.mov_r("DW", PORT_EVENT)
    a.op([0xB0, n], f"MOV AL, {n:02X}h")
    a.op([0xEE], f"OUT DW, AL   ; event {n}")


class Window(oc.Window):
    pass


# ------------------------------------------------------------------ A: EI against a pending request
def ei_window(series, s, src="sw", pr=7, nxt="inc", where="x", ev=None):
    """The request (a store of IF, or the INTP0 edge 200 ticks after the event), the begin
    marker, two fillers, the sled, the anchor store (PUSH AW: its write cycle at 00EFEh is the
    window's clock reference: a PUSH AW, block 0), EI, the next instruction, INC AW x 12, DI. where x: the sled is
    between the request and EI; y: sled(0) there and the swept sled in front of the request."""
    meta = dict(series=series, form=nxt, target=f"{src} pr{pr}", seg=where, shape="ei", n=s)

    def setup(a):
        oc.seg(a, "DS0", OFF)
        oc.seg(a, "DS1", ON)
        a.mov_r("BW", ANCHOR)
        a.mov_r("SP", STACK_TOP)
        a.mov_r("CW", 0)
        a.mov_r("IX", 0xF000)
        a.mov_r("IY", 0xF100)
        wtc1(a, s & 1)
        oc.fil(a)
        if where == "y":
            sled(a, s)
            wtc1(a, 0)
        if src == "sw":
            oc.es_store(a, EXIC0, 0x80 | pr)
        else:
            oc.es_store(a, EXIC0, pr)
            event(a, ev)

    def body(a):
        a.mov_r("AW", 1)
        oc.fil(a, 2)
        sled(a, s if where == "x" else 0)
        a.op([0x50], "PUSH AW   ; the anchor")
        meta["ei"] = len(a.b)
        a.op([0xFB], "EI")
        if nxt == "rep0":
            a.op([0xF3, 0xA5], "REP MOVBKW   ; CW = 0")
        meta["first"] = len(a.b)
        for _ in range(NINC):
            a.op([0x40], "INC AW")
        a.op([0xFA], "DI")
    return Window(meta, setup, body)


def se_window(s, ev):
    """intr.py f5_si_edge's movbkw_n0 instruction for instruction (the request store, the event
    between PUSH AW / PUSH DW and POP DW / POP AW, the DBNZ wait, DS1 reloaded, POP PSW with
    IE 0, POP AW, EI, REP MOVBKW with CW 0, INC AW), with the sled between the wait and the DS1
    reload. D: from the event's PUSH AW write to the POP AW read in front of EI."""
    meta = dict(series="se", form="rep0", target="pin pr7", seg="x", shape="se", n=s)

    def setup(a):
        oc.seg(a, "DS0", OFF)
        oc.seg(a, "DS1", ON)
        a.mov_r("BW", ANCHOR)
        a.mov_r("SP", STACK_TOP)
        a.mov_r("CW", 0)
        a.mov_r("IX", 0xF000)
        a.mov_r("IY", 0xF100)
        # the reset WTC as in intr.py's programs (two waits everywhere); block 1 one wait or two
        oc.es_store(a, 0xFFE8, 0xFFFF if s & 1 else 0xFFF7, word=True)
        oc.fil(a)

    def body(a):
        oc.es_store(a, EXIC0, 0x07)
        a.op([0x50], "PUSH AW")
        a.op([0x52], "PUSH DW")
        event(a, ev)
        a.op([0x5A], "POP DW")
        a.op([0x58], "POP AW")
        a.op([0x51], "PUSH CW")
        a.mov_r("CW", 20)
        a.op([0xE2, 0xFE], "DBNZ $")
        a.op([0x59], "POP CW")
        sled(a, s)
        a.op([0x50], "PUSH AW")
        a.mov_r("AW", 0x0B00)
        a.mov_sr("DS1")
        a.op([0x58], "POP AW")
        a.op([0x50], "PUSH AW")
        a.mov_r("AW", 0x0002)
        a.op([0x50], "PUSH AW")
        a.op([0x9D], "POP PSW")
        a.op([0x58], "POP AW")
        meta["ei"] = len(a.b)
        a.op([0xFB], "EI")
        a.op([0xF3, 0xA5], "REP MOVBKW   ; CW = 0")
        meta["first"] = len(a.b)
        for _ in range(NINC):
            a.op([0x40], "INC AW")
        a.op([0xFA], "DI")
    return Window(meta, setup, body)


def di_window(first, wtc):
    """The reset jump's shape without refresh: BR FAR to an even address, there `first` (DI, NOP,
    CLC or nothing) and f5_si_edge's first store (a prefixed MOV word mem,imm16; here SS:[0D80h]);
    the fetches at the reset WTC (two waits) or at none."""
    name, bs = first
    meta = dict(series="d", form=name, target=f"wtc {wtc:04X}", seg="-", shape="di", n=0)

    def setup(a):
        oc.seg(a, "DS1", ON)
        a.mov_r("SP", STACK_TOP)
        oc.es_store(a, 0xFFE8, wtc, word=True)
        oc.fil(a)

    def body(a):
        oc.fil(a)
        if not len(a.b) & 1:
            a.nop()
        t = len(a.b) + 5
        a.op([0xEA, t & 0xFF, t >> 8, CODE >> 4 & 0xFF, CODE >> 12], "BR FAR $+5")
        meta["target"] = f"wtc {wtc:04X} target {t:04X}"
        meta["tgt"] = t
        if bs:
            a.op(bs, name)
        a.op([0x36, 0xC7, 0x06, 0x80, 0x0D, 0x34, 0x12], "MOV word SS:[0D80h], 1234h")
        oc.fil(a, 2)
        oc.es_store(a, 0xFFE8, 0x0000, word=True)
    return Window(meta, setup, body)


def di_report(rec, prog):
    wins, _ = oc.windows(rec, prog)
    print("  series d: the instruction at the far jump's target | WTC | the store's write less the "
          "target's first fetch (clocks) | the fetches between (clocks after it)")
    for k, w in enumerate(prog.windows):
        if w.meta["shape"] != "di" or k not in wins:
            continue
        rows = [r for kind, r in wins[k]["rows"] if kind != "pin"]
        i0 = next(i for i, r in enumerate(rows) if r[1] == CODE + w.meta["tgt"])
        iw = next(i for i, r in enumerate(rows) if r[1] == 0x0D80 and not r[3] & 1)
        print(f"    {w.meta['form']:5s} {w.meta['target']:22s} | {fmt((rows[iw][0] - rows[i0][0]) / CLK):>5s} | "
              + " ".join(f"{r[1] & 0xFFF:03X}@{fmt((r[0] - rows[i0][0]) / CLK)}" for r in rows[i0:iw + 3]))


def se_rows(rec, prog):
    wins, _ = oc.windows(rec, prog)
    out = []
    for k, w in enumerate(prog.windows):
        if w.meta["shape"] != "se" or k not in wins:
            continue
        rows = [r for kind, r in wins[k]["rows"] if kind != "pin"]
        out.append(dict(m=w.meta, **se_decode(rows, STACK_TOP, w.meta["first"])))
    return out


def se_decode(rows, sp, first=None):
    """rows: the records from the request store to after the take. D (ticks): the first write at
    sp - 2 (the event's PUSH AW) to the last read at sp - 2 before INTP0's vector read (POP AW
    in front of EI); V - that read; the pushed PC."""
    iv = next((i for i, r in enumerate(rows) if r[1] == 0x60 and r[3] & 1 and not r[3] & 2), None)
    if iv is None:
        return dict(D=None, VR=None, pc=None, n=None)
    p0 = next(r for r in rows if r[1] == sp - 2 and not r[3] & 1)
    p1 = [r for r in rows[:iv] if r[1] == sp - 2 and r[3] & 1][-1]
    pushes = [r for r in rows[iv:iv + 6] if not r[3] & 1]
    pc = pushes[2][2] if len(pushes) >= 3 else None
    return dict(D=p1[0] - p0[0], VR=rows[iv][0] - p1[0], pc=pc,
                n=None if pc is None or first is None else pc - first)


def se_report(rec, prog):
    print("  series se (f5_si_edge's movbkw_n0 with a sled): s | D = PUSH AW write -> POP AW read "
          "(clocks; mod 18) | vector read less the POP AW read | INCs run after the empty string")
    for r in se_rows(rec, prog):
        if r["D"] is None:
            print(f"    s{r['m']['n']:2d}: no take")
            continue
        D = r["D"] / CLK
        print(f"    s{r['m']['n']:2d}: {fmt(D):>6s} ({fmt(D % 18):>5s}) | {fmt(r['VR'] / CLK):>5s} | n {r['n']}")


# ------------------------------------------------------------------ the edge against the request flag
NREAD = 6


def edge_window(j, ev):
    """EXIC0 masked (47h: the last store to a request control register before the edge), a
    filler, the sled (j % 4 clocks: the store's distance from everything after it), the event;
    then the flag read and pushed six times (C7h: seen). The only access in block 1 is the
    sled's read."""
    s = j % 4
    meta = dict(series="e", form="rd", target="exic0", seg="-", shape="edge", n=s)

    def setup(a):
        oc.seg(a, "DS0", OFF)
        oc.seg(a, "DS1", ON)
        a.mov_r("BW", ANCHOR)
        a.mov_r("SP", STACK_TOP)
        wtc1(a, s & 1)
        oc.es_store(a, EXIC0, 0x47)
        oc.fil(a)
        sled(a, s)
        event(a, ev)

    def body(a):
        oc.fil(a)
        for i in range(NREAD):
            a.op([0x26, 0xA0, EXIC0 & 0xFF, EXIC0 >> 8], "MOV AL, DS1:[FF4Ch]")
            a.op([0x50], "PUSH AW")
            if i & 1:
                a.op([0x98], "CBW")
        oc.fil(a)
    return Window(meta, setup, body)


# ------------------------------------------------------------------ TM0's request in an INC train
TRAIN = 1700


def tmr_window(s, md=66):
    meta = dict(series="t", form="tmr", target=f"md0 {md}", seg="-", shape="tmr", n=s)

    def setup(a):
        oc.wtc0(a)
        oc.es_store(a, 0xFF90, 0x00)
        oc.es_store(a, 0xFF82, md, word=True)
        oc.es_store(a, 0xFF80, md, word=True)
        oc.seg(a, "DS0", OFF)
        a.mov_r("BW", ANCHOR)
        a.mov_r("SP", STACK_TOP)
        a.mov_r("CW", 0x8C)
        oc.es_store(a, TMIC0, 0x07)
        wtc1(a, s & 1)

    def body(a):
        a.mov_r("AW", 1)
        oc.fil(a)
        sled(a, s)
        a.op([0x50], "PUSH AW   ; the anchor")
        meta["ei"] = len(a.b)
        a.op([0xFB], "EI")
        a.op([0x26, 0x88, 0x0E, 0x90, 0xFF], "MOV DS1:[FF90h], CL   ; TM0 starts (CL = 8Ch)")
        meta["first"] = len(a.b)
        for _ in range(TRAIN):
            a.op([0x40], "INC AW")
        a.op([0xFA], "DI")
        oc.es_store(a, 0xFF90, 0x00)
        oc.es_store(a, TMIC0, 0x47)
        wtc1(a, 0)
    return Window(meta, setup, body)


# ------------------------------------------------------------------ programs
class Program:
    """onchip_t's frame with a prelude by option. rf: off (the RFM store in the prelude, as
    the corpus), first (the RFM store before everything else), on (refresh never disabled),
    late (disabled after twelve fillers). pp: the prelude one clock longer (its read in block 1
    with a wait)."""

    def __init__(self, name, windows, note="", rf="off", pp=0, init=None, fini=None, pins=None,
                 mid=None, entries=None):
        self.name, self.windows, self.note = name, windows, note
        self.rf, self.pp, self.init, self.fini, self.mid = rf, pp, init, fini, mid or {}
        self.stim = None
        if pins or entries:
            self.stim = {"entries": list(entries or [])}
            if pins:
                self.stim["pins"] = list(pins)
        self.ready = 0
        self._built = None

    def build(self):
        if self._built:
            return self._built
        mem = {}
        for p in (0x00, 0x3F, 0xFF):
            for o in range(0x1000):
                mem[p << 12 | o] = pat(p << 12 | o)
        m = Asm(ORG)
        if self.rf == "first":
            oc.seg(m, "DS1", ON)
            oc.es_store(m, 0xFFE1, 0xEC)
        m.op([0xFA], "DI")
        m.mov_r("AW", 0)
        m.mov_sr("SS")
        m.mov_r("SP", STACK_TOP)
        m.mov_sr("DS0")
        oc.seg(m, "DS1", ON)
        if self.rf == "off":
            oc.es_store(m, 0xFFE1, 0xEC)
        oc.es_store(m, 0xFFE8, self.pp << 2, word=True)
        oc.seg(m, "DS0", OFF)
        m.mov_r("BW", ANCHOR)
        oc.fil(m)
        m.op([0x8A, 0x27], "MOV AH, [BW]   ; block 1: a wait when the prelude is a clock longer")
        oc.fil(m)
        oc.es_store(m, 0xFFE8, 0x0000, word=True)
        m.mov_r("AW", 0)
        m.mov_sr("DS0")
        if self.init:
            self.init(m)
        if self.rf == "late":
            oc.fil(m, 12)
            oc.seg(m, "DS1", ON)
            oc.es_store(m, 0xFFE1, 0xEC)
        m.op([0xEA, 0x00, 0x00, CODE >> 4 & 0xFF, CODE >> 12], f"BR FAR {CODE >> 4:04X}h:0000h")
        head = m.finish()
        a = Asm(0)
        for k, w in enumerate(self.windows):
            if k in self.mid:
                self.mid[k](a)
            if len(a.b) & 1:
                a.nop()
            a.lines.append((b"", f"; ---- window {k}: " + " ".join(f"{x}={y}" for x, y in w.meta.items())))
            w.setup(a)
            a.mov_r("DW", M_BEGIN)
            a.mov_r("AW", k)
            a.op([0xEF], "OUT DW, AW")
            w.body(a)
            a.op([0x42], "INC DW")
            a.op([0x42], "INC DW")
            a.op([0xEF], "OUT DW, AW")
        oc.seg(a, "DS1", ON)
        oc.es_store(a, 0xFFE8, 0x0000, word=True)
        if self.fini:
            self.fini(a)
        a.mov_r("DW", 0xFF00)
        a.op([0xEE], "OUT DW, AL")
        a.op([0xF4], "HALT")
        a.op([0xEB, 0xFE], "BR $")
        text = a.finish()
        if len(text) > CODE_PAGES * 0x1000:
            raise ValueError(f"{self.name}: {len(text)} bytes of code")
        for i, v in enumerate(head):
            mem[ORG + i] = v
        for i in range((len(text) + 0x1010) >> 12 << 12):
            mem[CODE + i] = 0x90
        for i, v in enumerate(text):
            mem[CODE + i] = v
        for i, v in enumerate(bytes([0xEA, ORG & 0xFF, ORG >> 8, 0, 0])):
            mem[0xFFFF0 + i] = v
        for n in range(32):                         # every vector to the handler
            for i, v in enumerate(bytes([HANDLER & 0xFF, HANDLER >> 8, 0, 0])):
                mem[4 * n + i] = v
        for i, v in enumerate(bytes([0x0F, 0x92, 0xCF])):
            mem[HANDLER + i] = v
        segments = {}
        for p in sorted({x >> 12 for x in mem}):
            segments[p << 12] = bytes(mem[p << 12 | o] for o in range(0x1000))
        self._built = dict(text=head + text + bytes(f"{self.rf}{self.pp}", "ascii"), head=m.lines,
                           lines=a.lines, segments=segments, code_end=CODE + len(text))
        return self._built

    def source(self):
        b = self.build()
        out = [f"; {self.name}: {self.note}",
               "; Generated by validation/v35s/phase.py emit: the bytes are the generator's.",
               f"; The prelude runs at 00100h; the windows at {CODE:05X}h (PS {CODE >> 4:04X}h).",
               f"; Every vector points at 0000:{HANDLER:04X}h (FINT ; RETI); the image maps 3F000h."]
        for lines in (b["head"], [(b"", f"; ---- at {CODE:05X}h")], b["lines"]):
            for bs, text in lines:
                if not bs:
                    out.append(text)
                else:
                    out.append("    DB " + ", ".join(f"{v:02X}h" if v < 0xA0 else f"0{v:02X}h" for v in bs)
                               + f"    ; {text}")
        return "\n".join(out) + "\n"


def pulse(ev, delay=200, hold=1200):
    return {"event": ev, "delay": delay, "hold": hold, "levels": {"INTP0": 0}}


def grid_windows():
    """TMC0 byte stores swept over twelve delays with the twin (onchip_t's reference), then TOUT:
    TM0 at /6 (MD0 4), at /128 (MD0 0: TMC0 CCh), one-shot at /12 (TM0 = MD0 = 6: TMC0 8Dh)."""
    sw = [oc.sweep_window("wrb", "tmc0", s, k, ref=True) for k in range(oc.STEPS) for s in (ON, OFF)]
    t6 = [oc.tout_window(k, 4) for k in range(0, 12, 2)]
    t128 = [tout_long(k, 0, 0xCC, 8) for k in range(0, 12, 3)]
    t12 = [tout_long(k, 6, 0x8D, 3) for k in range(12)]
    return sw, t6 + t128 + t12


def tout_long(k, md, tmc, fils):
    def setup(a):
        oc.wtc0(a)
        oc.es_store(a, 0xFF90, 0x00)
        oc.es_store(a, 0xFF82, md, word=True)
        oc.es_store(a, 0xFF80, md, word=True)
        oc.std_setup(ON)(a)

    def body(a):
        a.mov_r("AW", tmc)
        oc.fil(a)
        oc.roli(a, 1 + k % 6)
        a.nop(k // 6 % 2)
        a.op(*oc.form("wrb", 0xFF90, 0))
        oc.fil(a, fils)
        a.op(*oc.form("imb", 0xFF90, 0x00))
        oc.fil(a)
    return Window(dict(form="wrb", target=f"tmc0 {tmc:02X}h md0 {md}", seg="on", shape="tout", n=k),
                  setup, body)


def programs():
    progs = []
    a = ([ei_window("x7", s) for s in range(48)] + [ei_window("y7", s, where="y") for s in range(24)]
         + [ei_window("x0", s, pr=0) for s in range(24)])
    progs.append(Program("f5_ph_a", a, "EI against a request set by a store of IF: the sled swept"))
    b = [ei_window("px7", s, src="pin", ev=s + 1) for s in range(32)]
    progs.append(Program("f5_ph_b", b, "EI against a request from the INTP0 pin: the sled swept",
                         entries=[pulse(s + 1) for s in range(32)]))
    c = ([ei_window("py7", s, src="pin", where="y", ev=s + 1) for s in range(16)]
         + [ei_window("pr7", s, src="pin", nxt="rep0", ev=s + 17) for s in range(16)])
    progs.append(Program("f5_ph_c", c, "the pin request: the sled in front; EI then REP MOVBKW 0",
                         entries=[pulse(s + 1) for s in range(32)]))
    progs.append(Program("f5_ph_s", [se_window(s, s + 1) for s in range(32)], "f5_si_edge's movbkw_n0 "
                         "with a sled in front of the PSW load", entries=[pulse(s + 1) for s in range(32)]))
    firsts = (("DI", [0xFA]), ("NOP", [0x90]), ("CLC", [0xF8]), ("none", []))
    progs.append(Program("f5_ph_d", [di_window(f, w) for w in (0xFFFF, 0x0000) for f in firsts],
                         "DI at a far jump's target in front of a store (the reset jump's shape, no refresh)"))
    for pp in (0, 1):
        e = [edge_window(j, j + 1) for j in range(32)]
        progs.append(Program("f5_ph_e" + ("1" if pp else ""), e, "the INTP0 edge against the "
                             "request flag (EXIC0 read six times)" + (", the prelude a clock longer" if pp else ""),
                             pp=pp, entries=[pulse(j + 1, delay=edge_delay(j, 3676, 8), hold=600) for j in range(32)]))
    for sfx, rf in (("", "off"), ("1", "first"), ("2", "on"), ("3", "late")):
        sw, tout = grid_windows()
        progs.append(Program("f5_ph_g" + sfx, sw + tout, f"the timer grid against reset: refresh {rf}",
                             rf=rf, init=oc.ports_on, fini=oc.ports_off, pins=["P15"],
                             mid={len(sw): oc.ports_tout}))
    t = [tmr_window(s) for s in range(8)]
    progs.append(Program("f5_ph_t", t, "TM0's request with IE 1 in an INC train, EI's place swept",
                         init=tmr_init, fini=oc.ports_off, pins=["P15"]))
    progs.append(Program("f5_ph_r", [ei_window("x7", 0)], "the reset and the prelude (a short program)"))
    return {p.name: p for p in progs}


def tmr_init(a):
    oc.ports_on(a)
    oc.ports_tout(a)


def edge_delay(j, base, step):
    """Windows 4m .. 4m + 3 share a delay (their sleds are 0 .. 3 clocks)."""
    return base + step * (j // 4)


# ------------------------------------------------------------------ running
def receipt_path(name, backend):
    return RECEIPTS / f"f5-{name}-{backend}.json"


def load(name, backend):
    return json.loads(receipt_path(name, backend).read_text())


def stitched(harness, reload, mode, lane, limit, upto=None):
    """The whole trace (or its first `upto` records) in the first run's ticks."""
    reload()
    result = harness.run(mode, limit)
    trace = [dict(t) for t in result[f"{lane}_trace"]]
    total, replay, resid = result[f"{lane}_total"], [], 0
    end = total if upto is None else min(total, upto)
    start = CAPTURE - OVERLAP
    while len(trace) < end:
        reload()
        window = harness.run(mode, limit, capture_start=start)
        if window[f"{lane}_total"] != total:
            replay.append(f"total changed at window {start}")
        part = [dict(t) for t in window[f"{lane}_trace"]]
        held = trace[start:]
        n = min(len(held), len(part))
        shift = int(statistics.median(x["start"] - y["start"] for x, y in zip(held[:n], part[:n])))
        for t in part:
            t["start"] += shift
            t["end"] += shift
        for x, y in zip(held[:n], part[:n]):
            if (x["address"], x["data"], x["flags"]) != (y["address"], y["data"], y["flags"]):
                replay.append(f"overlap differs at record {start}")
                break
            resid = max(resid, abs(x["start"] - y["start"]))
        if len(part) <= n:
            replay.append(f"no new records at {start}")
            break
        trace.extend(part[n:])
        start = len(trace) - OVERLAP
    rows = [[t["start"], t["address"], t["data"], t["flags"], t["end"], t["strobe"]] for t in trace[:end]]
    return result, rows, replay, resid


def run_one(harness, prog, lane, limit=80_000_000):
    b = prog.build()
    mode = "socket" if lane == "socket" else "model"
    result, rows, replay, resid = stitched(harness, lambda: harness.load(b["segments"]), mode, lane, limit)
    return {
        "program": prog.name, "note": prog.note,
        "program_sha256": hashlib.sha256(b["text"]).hexdigest(),
        "image_sha256": hashlib.sha256(json.dumps(
            {f"{a:05X}": d.hex() for a, d in sorted(b["segments"].items())}).encode()).hexdigest(),
        "passed": result["passed"], "status": result["status"], "timeout": result["timeout"],
        "total": result[f"{lane}_total"], "signature": result[f"{lane}_signature"],
        "replay": replay, "stitch_residual": resid, "stim": prog.stim, "trace": rows,
    }


def _stamp(rec, backend):
    rec.update(backend=backend, date=datetime.datetime.now().isoformat(timespec="seconds"))
    if backend == "socket":
        rec.update(cpu="uPD70337L-8", x_half=2)
    else:
        rec.update(core="v35", binary=os.environ.get("V35_SIM_BINARY", "build/fpga/v35s/verilator-direct-v35"))


def _save(rec, name, tagged):
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    receipt_path(name, tagged).write_text(json.dumps(rec, separators=(",", ":")) + "\n")


def run_set(names, backend, tag, progs, delays=None):
    from .traps import _board, _close_board, _sim, _stim
    lane = "socket" if backend == "socket" else "model"
    if backend == "socket":
        transport, harness = _board()
    try:
        for name in names:
            prog = progs[name]
            if delays and prog.stim and name.startswith("f5_ph_e"):
                for j, e in enumerate(prog.stim["entries"]):
                    e["delay"] = edge_delay(j, *delays)
            if backend != "socket":
                transport, harness = _sim()
            try:
                _stim(harness, prog)
                rec = run_one(harness, prog, lane)
            finally:
                if backend != "socket":
                    transport.close()
            _stamp(rec, backend)
            _save(rec, name, backend + tag)
            print(f"{name}: {backend}{tag} {'PASS' if rec['passed'] else 'FAIL'} "
                  f"status=0x{rec['status']:04x} total={rec['total']} records={len(rec['trace'])} "
                  f"replay={rec['replay']} residual={rec['stitch_residual']}", flush=True)
    finally:
        if backend == "socket":
            _close_board(transport, harness)


def run_resets(backend, tag, progs, n=4, holds=range(1667, 1683)):
    """f5_ph_r taken n times at each reset-hold length: the first 24 records of each run."""
    from .traps import _board, _close_board, _sim, _stim
    prog = progs["f5_ph_r"]
    b = prog.build()
    lane = "socket" if backend == "socket" else "model"
    mode = "socket" if lane == "socket" else "model"
    runs = []
    if backend == "socket":
        transport, harness = _board()
    else:
        transport, harness = _sim()
    try:
        _stim(harness, prog)
        for hold in holds:
            harness.debug.write(0x84, hold.to_bytes(4, "little"))
            for _ in range(n):
                harness.load(b["segments"])
                r = harness.run(mode, 20_000_000)
                runs.append(dict(hold=hold, passed=r["passed"], total=r[f"{lane}_total"],
                                 head=[[t["start"], t["address"], t["data"], t["flags"], t["end"], t["strobe"]]
                                       for t in r[f"{lane}_trace"][:24]]))
        harness.debug.write(0x84, (1667).to_bytes(4, "little"))
    finally:
        if backend == "socket":
            _close_board(transport, harness)
        else:
            transport.close()
    rec = dict(program="f5_ph_r", note="resets", runs=runs,
               program_sha256=hashlib.sha256(b["text"]).hexdigest())
    _stamp(rec, backend)
    _save(rec, "f5_ph_resets", backend + tag)
    print(f"resets: {backend}{tag} {len(runs)} runs, all passed {all(r['passed'] for r in runs)}")


def run_intr(backend, tag, name="f5_si_edge", upto=3 * CAPTURE):
    """intr.py's program with the trace kept (its first `upto` records)."""
    from . import intr
    from .traps import _board, _close_board, _sim, _stim
    prog = intr.programs()[name]
    code, segments, pages = prog.image()
    lane = "socket" if backend == "socket" else "model"
    mode = "socket" if lane == "socket" else "model"
    if backend == "socket":
        transport, harness = _board()
    else:
        transport, harness = _sim()
    try:
        _stim(harness, prog)
        result, rows, replay, resid = stitched(harness, lambda: harness.load(segments, pages), mode,
                                               lane, 40_000_000, upto=upto)
    finally:
        if backend == "socket":
            _close_board(transport, harness)
        else:
            transport.close()
    rec = dict(program=name, program_sha256=hashlib.sha256(code).hexdigest(), passed=result["passed"],
               total=result[f"{lane}_total"], replay=replay, stitch_residual=resid, trace=rows)
    _stamp(rec, backend)
    _save(rec, "si_edge" if name == "f5_si_edge" else name, backend + tag)
    print(f"{name}: {backend}{tag} passed {rec['passed']} total {rec['total']} kept {len(rows)} "
          f"replay {replay} residual {resid}")


# ------------------------------------------------------------------ reading
def origin(rec):
    """The FFFF0h fetch's start tick (the reset release is tick 0)."""
    for r in rec["trace"]:
        if r[1] == 0xFFFF0:
            return r[0]
    return None


def aclk(t, t0):
    return (t - t0) / CLK


def fmt(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


def head_report(rec, prog, n=14):
    t0 = origin(rec)
    end = prog.build()["code_end"]
    out, nref = [], 0
    for r in rec["trace"]:
        k = oc.kind_of(r, end)
        if k == "iow" and r[1] == M_BEGIN:
            break
        if k == "refresh":
            nref += 1
        if len(out) < n and k not in ("pin", "refresh"):
            out.append(f"{k[0]}{r[1] & 0xFFFFF:05X}@{fmt(aclk(r[0], t0))}+{oc.waits_of(r)}w")
    print(f"  reset release -> FFFF0h fetch: {t0} ticks = {fmt(t0 / CLK)} clocks; refresh cycles "
          f"before the first window: {nref}")
    print("  prelude (clocks after the FFFF0h fetch): " + " ".join(out))


def ei_rows(rec, prog):
    """Per ei window: the anchor write's start W, the first vector / stack cycle's start V, the
    pushed PC, the fetch holding EI's byte."""
    wins, _ = oc.windows(rec, prog)
    t0 = origin(rec)
    out = []
    for k, w in enumerate(prog.windows):
        m = w.meta
        if m["shape"] != "ei" or k not in wins:
            continue
        rows = wins[k]["rows"]
        W = next((r[0] for kind, r in rows if kind == "mw" and r[1] == STACK_TOP - 2), None)
        stack = [r for kind, r in rows if kind == "mw" and 0xE00 <= r[1] < STACK_TOP - 2]
        vec = [r for kind, r in rows if kind == "mr" and r[1] < 0x80]
        fei = next((r[0] for kind, r in rows if kind == "fetch" and r[1] == (CODE + m["ei"]) & ~1), None)
        V = min([r[0] for r in stack + vec], default=None)
        pc = stack[2][2] if len(stack) >= 3 else None
        out.append(dict(k=k, m=m, W=W, V=V, pc=pc, fei=fei, t0w=wins[k]["t0"], t0=t0,
                        n=None if pc is None else pc - m["first"]))
    return out


def ei_report(rec, prog, verbose=False):
    rows = ei_rows(rec, prog)
    series = []
    for r in rows:
        if r["m"]["series"] not in series:
            series.append(r["m"]["series"])
    for sname in series:
        rs = [r for r in rows if r["m"]["series"] == sname]
        print(f"  series {sname} ({rs[0]['m']['target']}, next {rs[0]['m']['form']}, sled "
              f"{rs[0]['m']['seg']}): s | W - marker | W abs clock (mod 2, 6, 16) | W - EI's fetch | "
              f"instructions run after EI | V - W clocks")
        for r in rs:
            if r["W"] is None or r["V"] is None:
                print(f"    s{r['m']['n']:2d}: no take (W {r['W']}, V {r['V']})")
                continue
            A = round(aclk(r["W"], r["t0"]))
            print(f"    s{r['m']['n']:2d}: {fmt((r['W'] - r['t0w']) / CLK):>6s} | {A:6d} ({A % 2} {A % 6} {A % 16:2d}) | "
                  f"{fmt((r['W'] - r['fei']) / CLK) if r['fei'] else '-':>5s} | n {r['n']} | {fmt((r['V'] - r['W']) / CLK)}")
        vw = sorted({round((r["V"] - r["W"]) / CLK * 2) / 2 for r in rs if r["W"] and r["V"]})
        print(f"    V - W values: {vw}; n values: {sorted({r['n'] for r in rs if r['n'] is not None})}")


def edge_report(rec, prog):
    """Per edge window: the edge's tick (the event record's end + the delay + 4, the harness's
    stated latency), the six pushed bytes; per read the threshold by the sled's parity and by
    the parity of the push's absolute clock."""
    wins, _ = oc.windows(rec, prog)
    t0 = origin(rec)
    ent = (rec.get("stim") or {}).get("entries") or []
    evs = [r for r in rec["trace"] if r[3] & 0x100]
    print("  window | sled | delay ticks | per read: push abs clock mod 2 : push start less the edge "
          "(clocks) : seen")
    seen = {}
    for k, w in enumerate(prog.windows):
        if w.meta["shape"] != "edge" or k not in wins or k >= len(evs) or k >= len(ent):
            continue
        ev = evs[k]
        e = ev[4] + ent[k]["delay"] + 4
        st = [r for kind, r in wins[k]["rows"] if kind == "mw" and 0xE00 <= r[1] < STACK_TOP]
        cells = []
        for i, r in enumerate(st):
            A = round(aclk(r[0], t0))
            lead = (r[0] - e) / CLK
            s = int(r[2] & 0x80 != 0)
            cells.append(f"{A % 2}:{lead:6.2f}:{s}")
            seen.setdefault((i, w.meta["n"] % 2, A % 2), []).append((lead, s))
        print(f"    w{k:2d} s{w.meta['n']} d{ent[k]['delay']:4d} | " + " ".join(cells))
    print("  thresholds (the push's start less the edge, clocks): read, sled parity, absolute parity: "
          "largest lead not seen / smallest lead seen")
    for (i, sp, p), v in sorted(seen.items()):
        no = [x for x, s in v if not s]
        yes = [x for x, s in v if s]
        if no and yes:
            print(f"    read {i} sled {sp} abs {p}: not seen up to {max(no):6.2f} / seen from "
                  f"{min(yes):6.2f}  ({len(v)} windows)")


def pin_edges(rec, prog):
    """{window: [tick of each P15 change]} and each window's rows."""
    wins, _ = oc.windows(rec, prog)
    return {k: [r[0] for kind, r in w["rows"] if kind == "pin"] for k, w in wins.items()}, wins


def grid_report(rec, prog):
    t0 = origin(rec)
    wins, _ = oc.windows(rec, prog)
    rows = oc.sweep_rows(prog, wins)
    c = oc.sync_origin(rows)
    print(f"  TMC0 store sweep: delay ((c - phase) mod 6) + 1 with c = {c} in the capture's own clocks "
          f"(tick // 32 mod 6); delays by step: " + " ".join(f"{n}:{fmt(d / CLK)}" for f, t, n, ph, d, r in rows))
    if c is not None and t0 is not None:
        # the access starts on clock A (tick // 32 = A); it ends at the first grid point E >= A + 4
        # with E = A + 3 + wait, wait = ((c - A) mod 6) + 1: E mod 6 = (c + 4) mod 6 in ticks // 32
        e_tick = ((c + 4) % 6) * CLK
        print(f"  grid points E (an access's end): tick = {e_tick} mod 192 from the reset release; "
              f"against the FFFF0h fetch's start: {fmt(((e_tick - t0) % 192) / CLK)} mod 6 clocks")
    edges, _ = pin_edges(rec, prog)
    for k, w in enumerate(prog.windows):
        if w.meta["shape"] != "tout" or k not in wins:
            continue
        ed = edges.get(k, [])
        tgt = w.meta["target"]
        per = 128 if "CC" in tgt else 12 if "8D" in tgt else 6
        print(f"    w{k} {tgt} step {w.meta['n']}: {len(ed)} edges; after the marker (clocks) "
              + " ".join(fmt((x - wins[k]['t0']) / CLK) for x in ed[:8])
              + f" | (tick - FFFF0h) mod {per} clocks: " + " ".join(fmt(((x - t0) % (per * CLK)) / CLK) for x in ed[:8])
              + f" | tick mod {per * CLK}: " + " ".join(str(x % (per * CLK)) for x in ed[:8]))


def tmr_report(rec, prog):
    t0 = origin(rec)
    wins, _ = oc.windows(rec, prog)
    for k, w in enumerate(prog.windows):
        if w.meta["shape"] != "tmr" or k not in wins:
            continue
        rows = wins[k]["rows"]
        W = next((r[0] for kind, r in rows if kind == "mw" and r[1] == STACK_TOP - 2), None)
        pins = [r[0] for kind, r in rows if kind == "pin"]
        vec = [r[0] for kind, r in rows if kind == "mr" and r[1] == 0x70]
        cells = []
        for v in vec:
            p = max([x for x in pins if x < v], default=None)
            cells.append(f"{fmt((v - p) / CLK) if p else '-'}/{round(aclk(v, t0)) % 16}/{round((v - W) / CLK) % 16}")
        print(f"    w{k} s{w.meta['n']}: W abs {round(aclk(W, t0))} (mod 16 {round(aclk(W, t0)) % 16}); "
              f"{len(pins)} TOUT edges, {len(vec)} takes; per take: vector read less the count-out "
              f"(clocks) / abs mod 16 / (V - W) mod 16:")
        print("       " + " ".join(cells))
        print("       TOUT edges (tick - FFFF0h) mod 6 clocks: "
              + " ".join(sorted({fmt(((x - t0) % (6 * CLK)) / CLK) for x in pins[1:]})))


def report(name, backend, progs, verbose=False):
    rec = load(name, backend)
    prog = progs[name]
    wins, _ = oc.windows(rec, prog)
    if rec["program_sha256"] != hashlib.sha256(prog.build()["text"]).hexdigest():
        print(f"{name} [{backend}]: THE RECEIPT IS OF ANOTHER VERSION OF THE PROGRAM")
    print(f"{name} [{backend}]: {'PASS' if rec['passed'] else 'FAIL'} total {rec['total']}, "
          f"{len(wins)}/{len(prog.windows)} windows, replay {rec['replay']}, stitch residual "
          f"{rec.get('stitch_residual')} ticks")
    head_report(rec, prog)
    shapes = {w.meta["shape"] for w in prog.windows}
    if "ei" in shapes:
        ei_report(rec, prog, verbose)
    if "se" in shapes:
        se_report(rec, prog)
    if "di" in shapes:
        di_report(rec, prog)
    if "edge" in shapes:
        edge_report(rec, prog)
    if "sweep" in shapes:
        grid_report(rec, prog)
    if "tmr" in shapes:
        tmr_report(rec, prog)
    if verbose:
        for k in sorted(wins):
            print(f"    w{k}: {oc.timeline(wins[k], pins=True)}")


def resets_report(backend):
    rec = load("f5_ph_resets", backend)
    by = {}
    for r in rec["runs"]:
        h = r["head"]
        f0 = next(x for x in h if x[1] == 0xFFFF0)
        rest = tuple(x[0] - f0[0] for x in h[:10])
        by.setdefault(r["hold"], []).append((f0[0], rest))
    allt = sorted(t for v in by.values() for t, _ in v)
    shapes = {rest for v in by.values() for _, rest in v}
    print(f"resets [{backend}]: {len(rec['runs'])} runs; the FFFF0h fetch's start tick after the release: "
          f"min {allt[0]} max {allt[-1]}; values " + " ".join(f"{t}x{allt.count(t)}" for t in sorted(set(allt))))
    for hold, v in sorted(by.items()):
        print(f"  hold {hold}: " + " ".join(str(t) for t, _ in v))
    print(f"  the first ten records' starts after the FFFF0h fetch: {len(shapes)} distinct shapes")
    for s in sorted(shapes)[:6]:
        print("    " + " ".join(str(x) for x in s))


def intr_report(backend, name="si_edge"):
    rec = load(name, backend)
    t0 = origin(rec)
    print(f"{name} [{backend}]: total {rec['total']} kept {len(rec['trace'])} replay {rec['replay']}; "
          f"reset release -> FFFF0h fetch {t0} ticks")
    tr = rec["trace"]
    print("  head (clocks after the FFFF0h fetch): " + " ".join(
        f"{'w' if not r[3] & 1 else 'r'}{r[1]:05X}@{fmt(aclk(r[0], t0))}" for r in tr[:16] if not r[3] & FLAG_REFRESH))
    # per test (the store of its number at 08004h): D and the take, as se_decode (SP 7F00h)
    marks = [i for i, r in enumerate(tr) if r[1] == 0x8004 and not r[3] & 1] + [len(tr)]
    for a, b in zip(marks, marks[1:]):
        rows = [r for r in tr[a:b] if not r[3] & (FLAG_PIN | FLAG_REFRESH)]
        ev = next((i for i, r in enumerate(rows) if r[3] & 0x100), None)
        if ev is None:
            continue
        d = se_decode(rows[ev - 2:], 0x7F00)
        if d["D"] is not None:
            print(f"  test {tr[a][2]}: D {fmt(d['D'] / CLK)} clocks (mod 18: {fmt(d['D'] / CLK % 18)}); vector "
                  f"read {fmt(d['VR'] / CLK)} after the POP AW read; pushed PC {d['pc']:04X}")
    # the takes: a read of 00060h (INTP0's vector) with the records before it
    for i, r in enumerate(tr):
        if r[1] == 0x60 and r[3] & 1 and not r[3] & 2:
            ctx = tr[max(0, i - 14):i + 3]
            print(f"  take at record {i}, vector read @{fmt(aclk(r[0], t0))} (abs mod 2: {round(aclk(r[0], t0)) % 2}):")
            print("    " + " ".join(
                f"{'R' if x[3] & FLAG_REFRESH else 'w' if not x[3] & 1 else 'r'}{x[1]:05X}"
                f"{'=' + format(x[2], '04X') if not x[3] & 1 else ''}@{fmt((x[0] - r[0]) / CLK)}" for x in ctx))


# ------------------------------------------------------------------ comparing
def compare(name, ref, cand, progs, tol=1, pin_tol=4, verbose=False):
    prog = progs[name]
    a, b = load(name, ref), load(name, cand)
    if a["program_sha256"] != b["program_sha256"] or a["image_sha256"] != b["image_sha256"]:
        print(f"{name}: the receipts are of different programs")
        return False
    wa, _ = oc.windows(a, prog)
    wb, _ = oc.windows(b, prog)
    diff, tdiff = [], 0
    for k, w in enumerate(prog.windows):
        if k not in wa or k not in wb:
            diff.append((k, "missing"))
            continue
        x, y = oc.norm_window(wa[k]), oc.norm_window(wb[k])
        xb, yb = [p for p in x if p[0] != "pin"], [p for p in y if p[0] != "pin"]
        xp, yp = [p for p in x if p[0] == "pin"], [p for p in y if p[0] == "pin"]
        if not oc.near(xb, yb, tol) or not oc.near(xp, yp, pin_tol):
            dt = wb[k]["T"] - wa[k]["T"]
            tdiff += abs(dt) > tol
            diff.append((k, f"T {wa[k]['T']} / {wb[k]['T']} ({oc.clocks(dt)} clocks)"
                         + ("" if abs(dt) > tol else "; same length, records differ")))
    ta, tb = origin(a), origin(b)
    print(f"{name}: {ref} / {cand}: {'EQUAL' if not diff else 'DIFFER'} "
          f"({len(prog.windows) - len(diff)} of {len(prog.windows)} windows equal; {tdiff} differ in "
          f"length; passed {a['passed']} / {b['passed']}; FFFF0h fetch at tick {ta} / {tb}; first "
          f"marker {fmt(aclk(wa[0]['t0'], ta)) if 0 in wa else '-'} / {fmt(aclk(wb[0]['t0'], tb)) if 0 in wb else '-'} "
          f"clocks after it)")
    for k, why in diff[:None if verbose else 6]:
        m = prog.windows[k].meta
        print(f"  w{k} {m.get('series', '')} {m['form']} {m['target']} {m['seg']} {m['shape']} n{m['n']}: {why}")
    return not diff


def emit(progs):
    for name, prog in progs.items():
        (PROGRAMS_DIR / f"{name}.s").write_text(prog.source())
        b = prog.build()
        if prog.stim:
            (PROGRAMS_DIR / f"{name}.stim.json").write_text(json.dumps(prog.stim, indent=1) + "\n")
        print(f"{name}: {len(b['text'])} bytes, {len(prog.windows)} windows, {len(b['segments'])} pages")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "report", "repeat", "gate", "emit", "resets",
                                      "intr"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--backend", default="socket", help="resets / intr: socket or sim")
    p.add_argument("--delays", default=None, help="f5_ph_e: BASE:STEP in ticks")
    p.add_argument("--socket-fitted", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    progs = programs()
    names = a.names or [n for n in progs if n != "f5_ph_r"]
    delays = tuple(int(x) for x in a.delays.split(":")) if a.delays else None
    if a.action == "socket" and not a.socket_fitted:
        p.error("the socket action needs --socket-fitted")
    if a.action == "socket":
        run_set(names, "socket", a.tag, progs, delays)
    elif a.action == "sim":
        run_set(names, "sim", a.tag, progs, delays)
    elif a.action == "resets":
        if a.names == ["report"]:
            resets_report(a.backend + a.tag)
        elif a.backend == "socket" and not a.socket_fitted:
            p.error("the socket needs --socket-fitted")
        else:
            run_resets(a.backend, a.tag, progs)
    elif a.action == "intr":
        if a.names == ["report"]:
            intr_report(a.backend + a.tag)
        else:
            if a.backend == "socket" and not a.socket_fitted:
                p.error("the socket needs --socket-fitted")
            run_intr(a.backend, a.tag)
    elif a.action == "report":
        for n in names:
            report(n, a.ref + a.tag, progs, a.verbose)
    elif a.action == "repeat":
        ok = True
        for n in names:
            ok &= compare(n, "socket", "socket-2", progs, verbose=a.verbose)
        return 0 if ok else 1
    elif a.action == "gate":
        ok = True
        for n in names:
            ok &= compare(n, a.ref, a.cand, progs, verbose=a.verbose)
        return 0 if ok else 1
    else:
        emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
