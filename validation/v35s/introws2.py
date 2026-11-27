"""The rows DESIGN-INT3.md sections 2 and 3 asked for (2026-11-26; read in build/overseer/int-rows2/ROWS-INT2.md):
the "fetch pending" term of the interrupt controller's bus cycle (A) and HALT (B: H1, H2, and HALT entered
under HLDRQ with the queue empty). A sibling of introws.py (lattice.py's frame, phase.py's receipts and
comparison; passage.py's frame for the INT pin).

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.introws2 socket --socket-fitted [NAME ...] [--tag=-2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.introws2 sim [NAME ...] [--trace] [--whole] [--tag=T]
                               (WO52: without --trace / --whole the B.2 sets run as sim1)
    PYTHONPATH=host/src:. python3 -m validation.v35s.introws2 sim1 [NAME ...]        (B.2: one window a run, bounded)
    PYTHONPATH=host/src:. python3 -m validation.v35s.introws2 repeat [NAME ...]      (socket / socket-2)
    PYTHONPATH=host/src:. python3 -m validation.v35s.introws2 gate [NAME ...] [--tag=T] [-v]
                               (WO52, the gate: socket / sim per set, the B.2 sets window by window against
                               sim1 runs; one line a set and a total)
    PYTHONPATH=host/src:. python3 -m validation.v35s.introws2 read [NAME ...] [--ref socket] [-v]
    PYTHONPATH=host/src:. python3 -m validation.v35s.introws2 emit

A. IE 1; mark 1 ; a store of TMIC0's IF at level lv (the controller asks for its cycle 21 + 2 lv clocks after
the mark's write) ; a lead ; the instruction under test ; a train. Every window has a twin behind it in which
the store leaves IF 0 (nothing asked: the fetches' own clocks).

    f5_le_ymi / ya8 / ya6 / yfi   f5_ld_y's frame (the read in block 1, its wait the odd clock, then X; level
                               1 .. 5: the ask 7 clocks in front of the fetch X's bytes want to 1 behind);
                               X = MOV BW,imm16 / ADD BW,imm8 (83 /0) / ADD BW,imm16 (81 /0) / INC BW (FF /0)
    f5_le_y*1, f5_le_y*2       the same behind one prefix (DS1:) and two (DS1: PS:)
    f5_le_rmi / ra8 / ra6 / rfi   one level (7: the ask at 35): a lead, ROL BP,n (n 1 .. 6: two clocks a count), X,
                               an INC train
    f5_le_ni / nn              the lead, ROL BP,n, an INC / a NOP train: the landed core holds six bytes under
                               the ROL (f5_ld_r's frame)
    f5_le_pi / pn, qi / qn     the same with leads of one and three bytes: seven and five held under the ROL
    f5_le_wn / wq              a prefixed store (MOV SS:[m],AW) between the ROL and the INC train
    f5_le_ti / tn              f5_lc_sj's / sn's frame at level 7 with a INC AW and b NOP between the store and
                               the jump (the flush 0 .. 12 clocks later against the ask: the queue's fill)

B. HALT.

    f5_le_h1s  H1: mark 1, EI, a sled of s clocks, TM0's start, n NOPs, HALT x 3 (s 0 .. 7, n 0 .. 3)
    f5_le_h1r  H1: the start in front of EI; EI, the sled, MOV AW,AW (a register instruction), n NOPs, HALT x 3
    f5_le_h2a / h2b   H2: passage.py's f5_pa_i_halt at its shortest sleds (0 / 1), the INT pin's rise swept by half
               clocks over 16 clocks inside HALT
    f5_le_bV   HALT entered under HLDRQ: the event, mark 1, a sled of s = 0 .. 15 clocks, a short jump to HALT
               (the queue flushed: HALT is the last byte fetched), HLDRQ high for 6 clocks from a fixed delay
               behind the event (at s = 8 from 2 clocks in front of HALT's pop). V:
                   oi / on   HALT at an odd address (the target fetch brings HALT alone); INTP0 (IE 1) / NMI
                             40 clocks behind HLDRQ's fall
                   ei / en   the target word is NOP ; HALT
                   or / er   the twins of oi / ei: no HLDRQ
                   oj / om   oi / on with the request 3 clocks behind HLDRQ's rise (inside the hold)
                   ol        oi with HLDRQ high for 20 clocks
               `sim1` runs each window as a program of its own (f5_le_bV.s) with a bounded length: a core
               that stands in HALT for ever loses only that window.

C. (2026-11-27; read in build/overseer/int-rows3/ROWS-INT3.md) Rows for DESIGN-INT4's questions, in A's frames
(every window with its twin; `sim`, `gate`, `read` as the A sets):

    f5_lf_yK[1]  f5_ld_y's frame with X = K, [1] behind DS1:      f5_lf_nK / pK   X behind ROL BP,n at level 7 (the
                 landed core holds six / seven bytes under the ROL)
                 K: p8 PUSH imm8, p6 PUSH imm16, tb TEST r8,imm8 (F6 /0), tw TEST r16,imm16 (F7 /0), xi EXT r8,imm4
                 (0F 3B): the operand bytes popped on the routine's fourth word or later (asked from when);
                 m8 MOV r8,imm8, lf MOV AH,PSW, cb CVTBW, mr MOV r,r, pw PUSH r: the instruction behind the prefix
                 / the ROL taking 0, 1, 2 bytes on its first word, at lengths 1, 2, 3
    f5_lf_tV     f5_le_ti's frame (the fetch chained behind a displaced one) with the EU's work at the target varied:
                 tc INC CL train, tm MOV AW,AW train, tw MOV CW,imm16 train, ta / tb DS1: PS: ADD BW,imm16 / imm8
                 train, tp DS1: INC AW train, tr ROL BP,8 then INC, to / tj an odd target with a NOP / INC train;
                 tq / t8 / tk PUSH imm16 / PUSH imm8 / PUSH AW trains (the writes show the EU's clock in the asked
                 window); tt / tu TEST r16,imm16 / r8,imm8 trains (the immediate released late in the routine)

D. (2026-11-27; read in build/overseer/int-rows4/ROWS-INT4.md) Rows for DESIGN-TAKE's questions 3 .. 5:

    f5_lg_aNN    HALT's entry: the event, mark 1, a sled of s = 0 .. 3 clocks (a block-1 read, ROL BP,8 + s//2), the
                 instruction X in front of HALT (G_X: two X a program, 16 windows each), HALT ; NOP, mark 2. The request
                 is the NMI pin, its edge G_BASE + j clocks (j 0 .. 3) behind the landed core's pop of HALT at s = 0
                 (G_POP: the pilot's table), so the take's clock reads the loop's phase. f5_lg_a18: HALT ; HALT with
                 two edges; a19: DS1: HALT; a20 .. a25: more register instructions; a26 .. a31: a short jump to an
                 even / odd target and 1 .. 6 INC AW in front of HALT; a32 .. a39: sixteen X again with one wait on
                 every cycle of block 0. `read`: per window the take against the core's
                 pop, the edge and the last bus cycle (needs `sim NAME --trace` for the pop).
    f5_le_bnr / bmr   the twins of f5_le_bon / ben without HLDRQ (the same events, sleds and NMI clocks)
    f5_lg_h2n / h2o   H2: f5_le_h2a / h2b with a NOP train in HALT's place (the same sleds and edges)
    f5_lg_h2m / h2q   f5_le_h2a / h2b with INTP0's request flag set and masked (EXIC0 C7h)
    f5_lg_h2e / h2f   INT standing with IE 0; a sled of s = 0 .. 15 clocks, EI, HALT (h2e; a second entry is an NMI
                 170 clocks later: a window that took INT in front of HALT does not stand for good) / EI, a NOP train
    f5_lg_h2x / h2y   f5_le_h2a's frame with the INT edge a clock a window from 20 clocks in front of the core's pop of
                 HALT to 11 behind it (h2x: -20 .. -5, h2y: -4 .. 11), each window with the later NMI
    f5_lg_h2z    the same 32 edges with a NOP train in HALT's place
    f5_lg_h2p    a request control store (TMIC1: the scan's restart), a sled of x = 0 .. 15 clocks, then f5_le_h2a's
                 window with the edge at two clocks: the controller's round at every position against HALT
    f5_lg_h2g    INT standing with IE 0; f5_le_h2a's sled, EI, ROL BP,n (n 1 .. 16), HALT (with the later NMI): is the
                 first take out of HALT counted from HALT's entry or from IE's rise
    f5_lg_n2x / n2y / n2z   f5_lg_h2x / h2y / h2z with the NMI pin as the request (the later NMI a second pulse)

Receipts: validation/v35s/receipts/f5-<name>-<backend>.json.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

from . import lattice as la
from . import onchip_t as oc
from . import passage as pa
from . import phase as ph
from .wtc import CLK

LV = 7
ASK = 21 + 2 * LV               # ROWS-INT 1: the cycle is asked for 21 + 2 lv clocks behind mark 1's write
IF1, IF0 = 0x80 | LV, 0x00 | LV
BR0 = ("rawb", (0xEB, 0x00), "BR short $+2   ; the queue flushed")
RD = ("rawb", (0x8A, 0x27), "MOV AH, [BW]   ; block 1: its wait is the odd clock")
INCA = ("rawb", (0x40,), "INC AW   ; the other byte parity")


# a train's instruction by kind (rows 3: all but inc / nop)
TRAINS = {"inc": ([0x40], "INC AW"), "nop": ([0x90], "NOP"), "icl": ([0xFE, 0xC1], "INC CL"),
          "mrr": ([0x8B, 0xC0], "MOV AW, AW"), "mcw": ([0xB9, 0x00, 0x00], "MOV CW, 0000h"),
          "a62": ([0x26, 0x2E, 0x81, 0xC3, 0x00, 0x00], "DS1: PS: ADD BW, 0000h"),
          "a82": ([0x26, 0x2E, 0x83, 0xC3, 0x00], "DS1: PS: ADD BW, 0"), "pfx": ([0x26, 0x40], "DS1: INC AW"),
          "pi6": ([0x68, 0x34, 0x12], "PUSH 1234h"), "pi8": ([0x6A, 0x12], "PUSH 12h"), "paw": ([0x50], "PUSH AW"),
          "tiw": ([0xF7, 0xC1, 0x00, 0x00], "TEST CW, 0000h"), "tib": ([0xF6, 0xC1, 0x00], "TEST CL, 0")}


def emit(a, ops, meta):
    """lattice.emit_ops with: train kind n (INC AW / NOP, meta first), brh kind (a short jump to HALT at an odd
    address / to NOP ; HALT at an even one; then NOP NOP)."""
    for op in ops:
        if op[0] == "train":
            meta.setdefault("first", len(a.b))
            for _ in range(op[2]):
                a.op(*TRAINS[op[1]])
        elif op[0] == "bro":
            # (rows 3) a short jump to an odd address: the target fetch brings one byte
            skip = 0 if (len(a.b) + 2) & 1 else 1
            a.op([0xEB, skip], f"BR short $+{2 + skip}   ; the queue flushed, the target odd")
            if skip:
                a.op([0x90], "NOP   ; skipped")
        elif op[0] == "brh":
            at = len(a.b) + 2
            if op[1] == "o":
                skip = 0 if at & 1 else 1
            else:
                skip = 1 if at & 1 else 0
            a.op([0xEB, skip], f"BR short $+{2 + skip}   ; the queue flushed")
            if skip:
                a.op([0x90], "NOP   ; skipped")
            if op[1] == "e":
                a.op([0x90], "NOP   ; the target word's first byte")
            meta.setdefault("halts", []).append(len(a.b))
            a.op([0xF4], "HALT")
            a.op([0x90], "NOP")
            a.op([0x90], "NOP")
        else:
            la.emit_ops(a, (op,), meta)


def xwindow(series, n, ops, frame=la, **kw):
    win = frame.window(series, n, (), **kw)
    tail = win.body

    def body(a):
        emit(a, ops, win.meta)
        tail(a)
    win.body = body
    return win


# ------------------------------------------------------------------ A
X = {"mi": ((0xBB, 0x00, 0xF8), "MOV BW, 0F800h"), "a8": ((0x83, 0xC3, 0x00), "ADD BW, 0   ; 83 /0 ib"),
     "a6": ((0x81, 0xC3, 0x00, 0x00), "ADD BW, 0000h   ; 81 /0 iw"), "fi": ((0xFF, 0xC3), "INC BW   ; FF /0")}
PFX = {0: (), 1: (0x26,), 2: (0x26, 0x2E)}
PAD1 = ("rawb", (0x40,), "INC AW   ; the lead: two clocks")
PAD3 = ("rawb", (0x90,), "NOP   ; the lead: three clocks")
HEAD = (("ei",), ("fil", 1), ("mark", 1))
WS = ((0x36, 0xA3, 0xA0, 0x0D), "MOV SS:[0DA0h], AW   ; a prefixed store")


# the leads in front of ROL BP,n, (INC AW, NOP) counts, by what the landed core holds under the ROL: n six bytes
# (f5_ld_r's), p seven, q five; the two leads of a kind put the train's first fetch on the two clock parities
LEADS = {"n": ((0, 0), (2, 0)), "p": ((1, 0), (0, 1)), "q": ((3, 0), (2, 1))}


def set_r(series, train, leads, x=None, nr=(1, 2, 3, 4, 5, 6), pre=()):
    """mark 1, the store, a lead, ROL BP,n (the long instruction: the queue full or one short), X, the train."""
    out = []
    for j, (na, nb) in enumerate(leads):
        for n in nr:
            for tw, if_ in ((0, IF1), (1, IF0)):
                ops = (HEAD + (("st", 0xFF9C, if_),) + (PAD1,) * na + (PAD3,) * nb + (("rol", n),)
                       + ((("rawb",) + x,) if x else ()) + (("train", train, 40),))
                out.append(xwindow(series, len(out), ops, pre=pre, ic={}, lv=LV, rn=n, wt=j, tw=tw, ld=f"{na}i{nb}n"))
    return out


def set_y(series, x, lvs=(1, 2, 3, 4, 5), pre=()):
    """f5_ld_y's frame: mark 1, the store at level lv, the read in block 1 (its wait the odd clock), X, an INC train."""
    out = []
    for lv in lvs:
        for w in (0, 1):
            for tw, if_ in ((0, 0x80 | lv), (1, lv)):
                ops = HEAD + (("st", 0xFF9C, if_), RD, ("rawb",) + x, ("train", "inc", 40))
                out.append(xwindow(series, len(out), ops, pre=pre, odd=w, ic={}, lv=lv, rn=lv, wt=w, tw=tw))
    return out


PADS = ((0, 0), (1, 0), (0, 1), (2, 0), (1, 1), (0, 2), (2, 1), (1, 2), (0, 3), (2, 2), (1, 3), (0, 4))


def set_t(series, train, br=(BR0,), head=()):
    """head (rows 3): instructions at the jump's target in front of the train; br: the jump."""
    out = []
    for na, nb in PADS:
        for tw, if_ in ((0, IF1), (1, IF0)):
            ops = HEAD + (("st", 0xFF9C, if_),) + (PAD1,) * na + (PAD3,) * nb + br + head + (("train", train, 40),)
            out.append(xwindow(series, len(out), ops, ic={}, lv=LV, rn=na, wt=nb, tw=tw))
    return out


def a_programs():
    progs = []
    for key, (bs, text) in X.items():
        for np in (0, 1, 2):
            pt = "".join({0x26: "DS1: ", 0x2E: "PS: "}[p] for p in PFX[np])
            name = f"f5_le_y{key}" + (str(np) if np else "")
            progs.append(la.prog(name, set_y("y" + key + str(np), (PFX[np] + bs, pt + text)),
                                 f"the controller's cycle against the fetch {pt}{text.split('   ;')[0]} wants, by level"))
        progs.append(la.prog("f5_le_r" + key, set_r("r" + key, "inc", LEADS["n"], x=(bs, text)),
                             f"the same behind ROL BP,n at level {LV}: {text.split('   ;')[0]}"))
    for par in "npq":
        for train in ("inc", "nop"):
            name = par + train[0]
            progs.append(la.prog("f5_le_" + name, set_r(name, train, LEADS[par]),
                                 f"the controller's cycle against the {train.upper()} train's first fetch behind ROL "
                                 f"BP,n (leads {par})"))
    for par in "nq":
        progs.append(la.prog("f5_le_w" + par, set_r("w" + par, "inc", LEADS[par], x=WS),
                             f"a prefixed store behind ROL BP,n (leads {par}), INC train"))
    for name, train in (("ti", "inc"), ("tn", "nop")):
        progs.append(la.prog("f5_le_" + name, set_t(name, train),
                             f"a stored IF at level {LV}, a pad, a short jump, {train.upper()} train"))
    return {p.name: p for p in progs}


# ------------------------------------------------------------------ B.1
def set_h1(reg):
    out = []
    for n in range(4):
        for s in range(8):
            if reg:
                ops = (la.START, ("mark", 1), ("ei",), ("sled", s), ("rawb", (0x8B, 0xC0), "MOV AW, AW   ; no store"),
                       ("nop", n), ("halt", 3))
            else:
                ops = (("mark", 1), ("ei",), ("sled", s), la.START, ("nop", n), ("halt", 3))
            out.append(la.window("h1r" if reg else "h1s", len(out), ops, odd=s & 1, sl=s, nn=n))
    return out


H2_BASE = 59 + 14               # passage N_CLK["halt"] + 14 clocks: the first edge well inside HALT


def set_h2(a):
    wins, ent = [], []
    for a in (a,):
        for j in range(32):
            k = len(wins)
            ops = ((("ev", k + 1), ("mark", 1), ("dw0",), ("sl", a)) + pa.train("halt"))
            wins.append(pa.window("h2", k, ops, pre=(("ei",),), odd=a & 1, kind="halt", a=a, j=j))
            ent.append(dict(event=k + 1, delay=H2_BASE * 32 - 4 + 16 * j, hold=0, levels={"INT": 1}))
    return wins, ent


# ------------------------------------------------------------------ B.2
R0_Z, R0_D, R2_D = 1 << 4, 2 << 4, 2 << 2
HB_DELAY = 79 * CLK + 11         # ticks behind the event record: at s = 8 the rise is 1.5 clocks behind the target fetch's start (the pilot)
HB_LATE, HB_IN = 40 * CLK, 3 * CLK
# target, the request's pin, its place, HLDRQ's length in clocks (0: no HLDRQ)
BV = {"oi": ("o", "INTP0", "late", 6), "on": ("o", "NMI", "late", 6), "ei": ("e", "INTP0", "late", 6),
      "en": ("e", "NMI", "late", 6), "or": ("o", "INTP0", "late", 0), "er": ("e", "INTP0", "late", 0),
      "oj": ("o", "INTP0", "in", 6), "om": ("o", "NMI", "in", 6), "ol": ("o", "INTP0", "late", 20),
      # (rows 4) the twins of on / en without HLDRQ
      "nr": ("o", "NMI", "late", 0), "mr": ("e", "NMI", "late", 0)}

# om: at s = 12 the NMI is taken in front of HALT (its fetch starts on the edge's clock): HALT then stands for good.
# Captured once with 16 sleds (2026-11-26: window 12's pushed PC is HALT's own address); the program has 12
NSLED = {"om": 12}


def hb_init(a):
    la.init(a)
    oc.mode_marker(a, R2_D | R0_Z)
    oc.es_store(a, 0xFF12, 0xC0)        # PMC2: P27 HLDRQ, P26 /HLDAK
    oc.mode_marker(a, R2_D | R0_D)


def hb_fini(a):
    oc.seg(a, "DS1", oc.ON)
    oc.es_store(a, 0xFF12, 0x00)
    oc.mode_marker(a, R2_D | R0_Z)
    oc.mode_marker(a, R2_D)
    oc.ports_off(a)


def hb_entries(v, ev):
    tgt, pin, when, hold = BV[v]
    rq = {pin: 0}
    hl = {"HLDRQ": 1} if hold else {}
    if when == "late":
        return [dict(event=ev, delay=HB_DELAY, hold=(hold or 6) * CLK, levels=hl),
                dict(event=None, delay=HB_LATE - 10, hold=600, levels=rq)]
    # the second entry is a pulse on both pins: the request falls 3 clocks into the hold, and both return together
    return [dict(event=ev, delay=HB_DELAY, hold=0, levels=hl),
            dict(event=None, delay=HB_IN - 10, hold=hold * CLK - HB_IN, levels=dict(rq, **hl))]


def hb_window(v, s, k):
    tgt, pin, when, hold = BV[v]
    ops = (("ev", k + 1), ("mark", 1), ("sled", s), ("brh", tgt), ("mark", 2), ("train", "inc", 8))
    return xwindow("b" + v, k, ops, pre=(("ei",),), odd=s & 1, ic={"p0": 0x07, "tm0": 0x47}, sl=s)


def hb_prog(v, only=None):
    wins, ent = [], []
    for s in (range(NSLED.get(v, 16)) if only is None else (only,)):
        k = len(wins)
        wins.append(hb_window(v, s, k))
        ent += hb_entries(v, k + 1)
    tgt, pin, when, hold = BV[v]
    name = f"f5_le_b{v}" + ("" if only is None else f".{only}")
    return la.Program(name, wins, f"HALT at a jump's target ({'odd: alone' if tgt == 'o' else 'NOP ; HALT'}) "
                      + ("under HLDRQ" if hold else "(no HLDRQ)") + f", {pin} "
                      + ("40 clocks behind the hold" if when == "late" else "inside the hold"),
                      init=hb_init, fini=hb_fini, pins=["P15", "P26"], entries=ent)


def b_programs():
    progs = [la.prog("f5_le_h1s", set_h1(False), "H1: EI, a sled, TM0's start, n NOPs, HALT"),
             la.prog("f5_le_h1r", set_h1(True), "H1: TM0's start, EI, a sled, MOV AW,AW, n NOPs, HALT")]
    for a in (0, 1):
        wins, ent = set_h2(a)
        progs.append(pa.prog(f"f5_le_h2{'ab'[a]}", wins, f"H2: the INT pin's rise by half clocks inside HALT, sled {a}",
                             entries=ent, intak=True))
    progs += [hb_prog(v) for v in BV]
    return {p.name: p for p in progs}


# ------------------------------------------------------------------ rows 3 (ROWS-INT3)
# X by key: the bytes, the text. The core's routine in words from its dispatch S (urom/*.uasm), as the sets need it:
#   p8  `S . . P`: the immediate's pop and release on the fourth word        p6  the pops on the fourth and fifth
#   tb  the ModR/M byte released on S by the loader, the pop on the fifth word, E the sixth; tw: the fifth and sixth
#   xi  the page byte released on the E in front, the second byte on S (the routine's first word pops the ModR/M
#       byte), the ModR/M byte released on the third word, the imm4 popped on the fourth and released on the
#       read's datum word
#   m8  `S . P E`: the pop on the third word (the word behind the first is in front of the first pop)
#   lf  E on S (the next opcode taken on the first word)     cb  the next opcode released on S, E a word later
#   mr  the ModR/M byte and the next opcode on S             pw  nothing taken until E, six words behind S
X3 = {"p8": ((0x6A, 0x12), "PUSH 12h   ; 6A ib"), "p6": ((0x68, 0x34, 0x12), "PUSH 1234h   ; 68 iw"),
      "tb": ((0xF6, 0xC1, 0x00), "TEST CL, 0   ; F6 /0 ib"), "tw": ((0xF7, 0xC1, 0x00, 0x00), "TEST CW, 0000h   ; F7 /0 iw"),
      "xi": ((0x0F, 0x3B, 0xC1, 0x07), "EXT CL, 7   ; 0F 3B /0 ib"),
      "m8": ((0xB1, 0x00), "MOV CL, 0   ; B1 ib"),
      "lf": ((0x9F,), "MOV AH, PSW"), "cb": ((0x98,), "CVTBW"), "mr": ((0x8B, 0xC0), "MOV AW, AW   ; 8B /r"),
      "pw": ((0x50,), "PUSH AW")}
# EXT's word is read at DS0:IX: block 1's page; the NOP keeps the window's code on the other sets' byte parity (the
# queue holds one byte fewer under the read / the ROL on the other parity)
PRE3 = {"xi": (("rawb", (0xBE, 0x00, 0xF8), "MOV IX, 0F800h   ; EXT's word: block 1"),
               ("rawb", (0x90,), "NOP   ; parity"))}
# A (the operand bytes: asked from when) and C (the instruction behind a prefix / a ROL: what the run follows):
# (key, prefixes, levels) in f5_ld_y's frame; (lead, key) behind ROL BP,n at level 7
Y3 = (("p8", 0, (1, 2, 3, 4, 5, 6, 7)), ("p8", 1, (1, 2, 3, 4, 5)), ("p6", 0, (1, 2, 3, 4, 5)),
      ("tb", 0, (1, 2, 3, 4, 5)), ("tb", 1, (1, 2, 3, 4, 5, 6, 7)), ("tw", 0, (1, 2, 3, 4, 5, 6)),
      ("xi", 0, (1, 2, 3, 4, 5)), ("m8", 0, (1, 2, 3, 4, 5)), ("m8", 1, (1, 2, 3, 4, 5)),
      ("lf", 1, (1, 2, 3, 4, 5)), ("cb", 1, (1, 2, 3, 4, 5)), ("mr", 1, (1, 2, 3, 4, 5)),
      ("pw", 1, (1, 2, 3, 4, 5, 6, 7)))
R3 = (("n", "p8"), ("n", "p6"), ("p", "tb"), ("p", "tw"), ("p", "xi"), ("n", "m8"), ("n", "lf"), ("n", "cb"),
      ("n", "mr"), ("n", "pw"))
# B (the fetch chained behind a displaced one): f5_le_ti's frame (the ask on the first .. fourth fetch behind the
# flush by the pad) with the EU's work at the target varied
T3 = {"tc": (dict(train="icl"), "INC CL train (two bytes, four clocks: a ModR/M form)"),
      "tm": (dict(train="mrr"), "MOV AW,AW train (two bytes, two clocks: the EU waits for bytes)"),
      "tw": (dict(train="mcw"), "MOV CW,imm16 train (three bytes released at once)"),
      "ta": (dict(train="a62"), "DS1: PS: ADD BW,imm16 train (f5_le_ya62's instruction)"),
      "tb": (dict(train="a82"), "DS1: PS: ADD BW,imm8 train"),
      "tp": (dict(train="pfx"), "DS1: INC AW train"),
      "tr": (dict(train="inc", head=(("rol", 8),)), "ROL BP,8 at the target (no release while the queue fills), INC train"),
      "to": (dict(train="nop", br=(("bro",),)), "the target odd (its fetch brings one byte), NOP train"),
      "tj": (dict(train="inc", br=(("bro",),)), "the target odd, INC train"),
      # the EU's clock on the pins: every instruction of the train ends in a write
      "tq": (dict(train="pi6"), "PUSH imm16 train (the write shows the EU's clock)"),
      "t8": (dict(train="pi8"), "PUSH imm8 train"), "tk": (dict(train="paw"), "PUSH AW train"),
      # the immediate released six / five words behind the dispatch: the chain clock is in front of the pops
      "tt": (dict(train="tiw"), "TEST r16,imm16 (F7 /0) train"), "tu": (dict(train="tib"), "TEST r8,imm8 (F6 /0) train")}


def c_programs():
    progs = []
    for key, np, lvs in Y3:
        bs, text = X3[key]
        pt = "".join({0x26: "DS1: ", 0x2E: "PS: "}[q] for q in PFX[np])
        progs.append(la.prog(f"f5_lf_y{key}{np or ''}",
                             set_y(f"y{key}{np}", (PFX[np] + bs, pt + text), lvs=lvs, pre=PRE3.get(key, ())),
                             f"the controller's cycle against the fetch {pt}{text.split('   ;')[0]} wants, by level"))
    for par, key in R3:
        bs, text = X3[key]
        progs.append(la.prog(f"f5_lf_{par}{key}", set_r(par + key, "inc", LEADS[par], x=(bs, text), pre=PRE3.get(key, ())),
                             f"behind ROL BP,n (leads {par}) at level {LV}: {text.split('   ;')[0]}"))
    for name, (kw, note) in T3.items():
        progs.append(la.prog("f5_lf_" + name, set_t(name, **kw),
                             f"a stored IF at level {LV}, a pad, a short jump: {note}"))
    return {q.name: q for q in progs}


# ------------------------------------------------------------------ rows 4 (ROWS-INT4)
# (a) HALT's entry. X by key: (operations in front of the sled, X, operations behind HALT ; NOP, text, window keywords)
G_WR = ("rawb", (0x36, 0xA3, 0xA0, 0x0D), "MOV SS:[0DA0h], AW")
G_CONT = 0x0D60                 # pfx: the word holding the offset behind HALT
G_HCONT = (("rawb", (0x55,), "PUSH BP"), ("rawb", (0x8B, 0xEC), "MOV BP, SP"),
           ("rawb", (0x36, 0xA1, G_CONT & 0xFF, G_CONT >> 8), f"MOV AW, SS:[{G_CONT:04X}h]"),
           ("rawb", (0x89, 0x46, 0x02), "MOV [BP+2], AW   ; the frame's PC: behind HALT"),
           ("rawb", (0x5D,), "POP BP"), ("fint",), ("reti",))
G_X = {
    "r0": ((), (), (), "nothing: ROL BP,8+ (the sled) in front of HALT", {}),
    "nop": ((), (("nop", 1),), (), "NOP", {}),
    "n2": ((), (("nop", 2),), (), "NOP ; NOP", {}),
    "n3": ((), (("nop", 3),), (), "NOP ; NOP ; NOP", {}),
    "inc": ((), (("rawb", (0x40,), "INC AW"),), (), "INC AW", {}),
    "mr": ((), (("rawb", (0x8B, 0xC0), "MOV AW, AW"),), (), "MOV AW,AW", {}),
    "cb": ((), (("rawb", (0x98,), "CVTBW"),), (), "CVTBW", {}),
    "lf": ((), (("rawb", (0x9F,), "MOV AH, PSW"),), (), "MOV AH,PSW", {}),
    "m8": ((), (("rawb", (0xB1, 0x00), "MOV CL, 0"),), (), "MOV CL,imm8", {}),
    "mcw": ((), (("rawb", (0xB9, 0x00, 0x00), "MOV CW, 0000h"),), (), "MOV CW,imm16", {}),
    "a6": ((), (("rawb", (0x81, 0xC1, 0x00, 0x00), "ADD CW, 0000h   ; 81 /0 iw"),), (), "ADD CW,imm16", {}),
    "rol1": ((), (("rol", 1),), (), "ROL BP,1", {}),
    "rol2": ((), (("rol", 2),), (), "ROL BP,2", {}),
    "rol4": ((), (("rol", 4),), (), "ROL BP,4", {}),
    "mul": ((), (("x", "mul", 1),), (), "MULU IX", {}),
    "div": ((("dw0",),), (("x", "div", 1),), (), "DIVU IX", {}),
    # the handler puts the address behind HALT in the frame's PC (the landed core pushes the prefix's address)
    "pfx": ((), (), (), "nothing; HALT behind a prefix (DS1: HALT)",
            dict(hp=0x26, lead=(("cont",),), hand={"nmi": G_HCONT})),
    "xch": ((), (("rawb", (0x93,), "XCH AW, BW"),), (), "XCH AW,BW", {}),
    "rd": ((), (("rawb", (0x36, 0xA1, 0x00, 0x0D), "MOV AW, SS:[0D00h]"),), (), "MOV AW,SS:[m] (a read)", {}),
    "pop": ((("pushw",),), (("popw",),), (), "POP AW (a read)", {}),
    "wr": ((), (G_WR,), (), "MOV SS:[m],AW (a write)", {}),
    "push": ((), (("pushw",),), (("popw",),), "PUSH AW (a write)", {}),
    "out": ((), (("rawb", (0xE7, 0x80), "OUT 80h, AW"),), (), "OUT 80h,AW", {}),
    "in": ((), (("rawb", (0xE5, 0x80), "IN AW, 80h"),), (), "IN AW,80h", {}),
    "fo": ((), (("brt", "o"),), (), "a short jump; HALT first at its target, an odd address", {}),
    "fe": ((), (("brt", "e"),), (), "a short jump; HALT first at its target, an even address", {}),
    "ei": ((), (("ei",),), (), "EI (IE 1 before)", {}),
    "di": ((), (("di",),), (), "DI", {}),
    "e0": ((), (("ei",),), (), "EI (IE 0 before)", dict(pre=())),
    "sfr": ((), (("st", 0xFF00, 0x00),), (), "MOV byte DS1:[FF00h],imm8 (P0's latch)", {}),
    "tms": ((), (la.START,), (), "MOV byte DS1:[FF90h],imm8 (TM0's start; TMIC0 masked)", dict(ic={"tm0": 0x47})),
    "ram": ((), (("st", 0xFE40, 0x00),), (), "MOV byte DS1:[FE40h],imm8 (internal RAM)", {}),
    "wi": ((), (("rawb", (0x36, 0xC6, 0x06, 0xA0, 0x0D, 0x00), "MOV byte SS:[0DA0h], 00h"),), (),
           "MOV byte SS:[m],imm8 (external)", {}),
    "jn": ((), (("brt", "e"), ("nop", 1)), (), "a short jump to NOP ; HALT (an even target)", {}),
    "ji": ((), (("brt", "e"), ("rawb", (0x40,), "INC AW")), (), "a short jump to INC AW ; HALT", {}),
    "jr": ((), (("brt", "e"), ("rol", 4)), (), "a short jump to ROL BP,4 ; HALT", {}),
    "jp": ((("pushw",),), (("brt", "e"), ("popw",)), (), "a short jump to POP AW ; HALT", {}),
    "hh": ((), (("hlt",),), (), "HALT (HALT ; HALT, two edges)", {}),
    # the second batch: more one- and two-byte register instructions (which of them carry NOP's clock)
    "xcw": ((), (("rawb", (0x91,), "XCH AW, CW"),), (), "XCH AW,CW", {}),
    "cwl": ((), (("rawb", (0x99,), "CVTWL"),), (), "CVTWL", {}),
    "sah": ((), (("rawb", (0x9E,), "MOV PSW, AH"),), (), "MOV PSW,AH", {}),
    "clc": ((), (("rawb", (0xF8,), "CLR1 CY"),), (), "CLR1 CY", {}),
    "cmc": ((), (("rawb", (0xF5,), "NOT1 CY"),), (), "NOT1 CY", {}),
    "cld": ((), (("rawb", (0xFC,), "CLR1 DIR"),), (), "CLR1 DIR", {}),
    "dec": ((), (("rawb", (0x48,), "DEC AW"),), (), "DEC AW", {}),
    "daa": ((), (("rawb", (0x27,), "ADJ4A"),), (), "ADJ4A", {}),
    "aaa": ((), (("rawb", (0x37,), "ADJBA"),), (), "ADJBA", {}),
    "add": ((), (("rawb", (0x03, 0xC0), "ADD AW, AW"),), (), "ADD AW,AW", {}),
    "icl": ((), (("rawb", (0xFE, 0xC1), "INC CL"),), (), "INC CL", {}),
    "shl": ((), (("rawb", (0xD1, 0xE0), "SHL AW, 1"),), (), "SHL AW,1", {}),
}
# the second batch: a short jump to an even / odd target, k INC AW, HALT: HALT's pop at graded places in the fill's
# fetches, the instruction in front always INC AW
for _k in range(1, 7):
    for _t in "eo":
        G_X[f"{_t}{_k}"] = ((), (("brt", _t),) + (("rawb", (0x40,), "INC AW"),) * _k, (),
                            f"a short jump to an {'even' if _t == 'e' else 'odd'} target, {_k} INC AW", {})
# the third batch: X_w is X with one wait on every cycle of block 0 (the code, the stack, the marks): a fetch is four
# clocks, so a fetch can end on the clock in front of HALT's first word behind NOP, or cover the E word's clock alone
G_WAIT = ("r0", "nop", "n2", "inc", "cb", "mr", "xch", "m8", "jn", "ji", "fo", "e2", "o2", "e3", "e4", "o6")
for _k in G_WAIT:
    _f, _x, _b, _t, _kw = G_X[_k]
    G_X[_k + "_w"] = (_f, _x, _b, _t + ", one wait in block 0", dict(_kw, wt=1))
G_PAIRS = (("r0", "nop"), ("inc", "n2"), ("mr", "cb"), ("m8", "mcw"), ("a6", "lf"), ("rol1", "rol2"), ("rol4", "mul"),
           ("div", "n3"), ("rd", "pop"), ("wr", "push"), ("out", "in"), ("fo", "fe"), ("ei", "di"), ("e0", "sfr"),
           ("tms", "ram"), ("wi", "xch"), ("jn", "ji"), ("jr", "jp"), ("hh",), ("pfx",),
           ("xcw", "cwl"), ("sah", "clc"), ("cmc", "cld"), ("dec", "daa"), ("aaa", "add"), ("icl", "shl"),
           ("e1", "o1"), ("e2", "o2"), ("e3", "o3"), ("e4", "o4"), ("e5", "o5"), ("e6", "o6"),
           ("r0_w", "nop_w"), ("n2_w", "inc_w"), ("cb_w", "mr_w"), ("xch_w", "m8_w"), ("jn_w", "ji_w"), ("fo_w", "e2_w"),
           ("o2_w", "e3_w"), ("e4_w", "o6_w"))
G_BASE = 16                     # the first edge behind the core's pop of HALT at sled 0 (clocks)
G_NS, G_NJ = 4, 4
G_E2M = 575                     # ticks from the event record's end to mark 1's write (the pilot: every window)
G_E2M_W = 671                   # the same with one wait in block 0 (the pilot)
G_PH = 15                       # the edge's tick within the clock, as f5_le_bon's (the event record's end + 32 n + 15)
# the landed core's pop of HALT (its first word) in clocks behind mark 1's write at sled 0, by X (the pilot:
# build/overseer/int-rows4/tools/pilot.py, a simulation with the edges far behind)
G_POP = {"r0": 41, "nop": 45, "inc": 43, "n2": 49, "mr": 44, "cb": 44, "m8": 47, "mcw": 48, "a6": 48, "lf": 43, "rol1": 55,
         "rol2": 57, "rol4": 61, "mul": 75, "div": 86, "n3": 53, "rd": 55, "pop": 63, "wr": 52, "push": 50, "out": 54,
         "in": 59, "fo": 58, "fe": 58, "ei": 54, "di": 45, "e0": 56, "sfr": 52, "tms": 57, "ram": 52, "wi": 52, "xch": 45,
         "jn": 65, "ji": 64, "jr": 81, "jp": 82, "hh": 41, "pfx": 45,
         "xcw": 45, "cwl": 50, "sah": 43, "clc": 43, "cmc": 43, "cld": 43, "dec": 43, "daa": 51, "aaa": 58, "add": 44,
         "icl": 47, "shl": 51, "e1": 64, "o1": 67, "e2": 67, "o2": 69, "e3": 69, "o3": 71, "e4": 71, "o4": 74, "e5": 74,
         "o5": 77, "e6": 77, "o6": 79,
         "r0_w": 45, "nop_w": 49, "n2_w": 53, "inc_w": 47, "cb_w": 48, "mr_w": 49, "xch_w": 49, "m8_w": 52, "jn_w": 72,
         "ji_w": 72, "fo_w": 64, "e2_w": 76, "o2_w": 78, "e3_w": 78, "e4_w": 80, "o6_w": 90}
G_SECOND = 160 * CLK - 600      # hh: the second edge 160 clocks behind the first (about 26 behind the second pop)


def emit_g(a, ops, meta):
    """passage.emit_ops with: hlt [prefix] (HALT, its offset in meta "halts"), brt o / e (a short jump whose target
    is the next instruction at an odd / even address)."""
    for op in ops:
        if op[0] == "hlt":
            if len(op) > 1 and op[1]:
                a.op([op[1]], "DS1:   ; a prefix in front of HALT")
            meta.setdefault("halts", []).append(len(a.b))
            a.op([0xF4], "HALT")
            if "cont" in meta:
                at = meta.pop("cont")
                a.b[at:at + 2] = len(a.b).to_bytes(2, "little")
        elif op[0] == "cont":
            a.op([0x36, 0xC7, 0x06, G_CONT & 0xFF, G_CONT >> 8, 0, 0],
                 f"MOV word SS:[{G_CONT:04X}h], the offset behind HALT")
            meta["cont"] = len(a.b) - 2
        elif op[0] == "brt":
            at = len(a.b) + 2
            skip = (0 if at & 1 else 1) if op[1] == "o" else (1 if at & 1 else 0)
            a.op([0xEB, skip], f"BR short $+{2 + skip}   ; the queue flushed, the target {'odd' if op[1] == 'o' else 'even'}")
            if skip:
                a.op([0x90], "NOP   ; skipped")
        else:
            pa.emit_ops(a, [op], meta)


def gwindow(series, n, ops, **kw):
    win = pa.window(series, n, (), **kw)
    tail = win.body

    def body(a):
        emit_g(a, ops, win.meta)
        tail(a)
    win.body = body
    return win


def g_delay(key, j):
    e2m = G_E2M_W if key.endswith("_w") else G_E2M
    return e2m + (G_POP.get(key, 120) + G_BASE + j) * CLK + G_PH - 4      # 120: a pilot's edge, far behind


def g_prog(name, keys):
    wins, ent = [], []
    for key in keys:
        front, x, back, text, kw = G_X[key]
        kw = dict(kw)
        hp = kw.pop("hp", 0)
        pre = kw.pop("pre", (("ei",),))
        lead = kw.pop("lead", ())
        for s in range(G_NS):
            for j in range(G_NJ):
                k = len(wins)
                ops = (lead + (("ev", k + 1), ("mark", 1)) + front + (("sled", s),) + x + (("hlt", hp), ("nop", 1)) + back
                       + (("mark", 2), ("inc", 8)))
                wins.append(gwindow("g" + key, k, ops, pre=pre, odd=s & 1, xk=key, sl=s, j=j, **kw))
                ent.append(dict(event=k + 1, delay=g_delay(key, j), hold=600, levels={"NMI": 0}))
                if key == "hh":
                    ent.append(dict(event=None, delay=G_SECOND - 10, hold=600, levels={"NMI": 0}))
    return pa.prog(name, wins, "HALT's entry, NMI: " + " / ".join(G_X[k][3] for k in keys), entries=ent)


# (c) H2
H2_NMI = 170                    # clocks: the later NMI behind the INT edge (a HALT entered behind INT's take is woken)
H2_TAIL = (("mark", 2), ("mark", 3)) + (("rol", 31),) * 4 + (("inc", 12),)
H2_E2M = 575                    # ticks from the event record's end to mark 1's write in f5_le_h2a's frame (the pilot)
H2_PH = 1                       # the edge's tick within the clock, as f5_le_h2a's even steps
# the landed core's pop of HALT in clocks behind mark 1's write (the pilot): f5_le_h2a's window; the same behind
# the restart's store and an even sled (h2p: an odd sled's wait makes it one more)
H2_POP = {"a": 30, "p": 33}


def h2_ent(ev, delay, nmi=0):
    e = [dict(event=ev, delay=delay, hold=0, levels={"INT": 1})]
    if nmi:
        e.append(dict(event=None, delay=nmi * CLK - 10, hold=600, levels={"NMI": 0}))
    return e


def h2_tail(halt):
    return ((("x", "halt", 1),) + H2_TAIL) if halt else (("x", "nop", 40), ("mark", 2), ("mark", 3), ("inc", 12))


def set_h2v(a, kind, pre=(("ei",),)):
    """f5_le_h2a / h2b's windows and edges with X = kind (halt / nop) and the setup's `pre`."""
    wins, ent = [], []
    for j in range(32):
        k = len(wins)
        x = pa.train("halt") if kind == "halt" else h2_tail(False)
        ops = (("ev", k + 1), ("mark", 1), ("dw0",), ("sl", a)) + x
        wins.append(pa.window("h2", k, ops, pre=pre, odd=a & 1, kind=kind, a=a, j=j))
        ent += h2_ent(k + 1, H2_BASE * 32 - 4 + 16 * j)
    return wins, ent


def set_h2e(halt):
    """INT raised with IE 0 (the event; two fillers), mark 1, a sled, EI, HALT / a NOP train."""
    wins, ent = [], []
    for s in range(16):
        k = len(wins)
        ops = (("ev", k + 1), ("fil", 2), ("mark", 1), ("dw0",), ("sl", s), ("ei",)) + h2_tail(halt)
        wins.append(pa.window("h2e", k, ops, odd=s & 1, kind="halt" if halt else "nop", a=s, sl=s))
        ent += h2_ent(k + 1, 200, nmi=330 if halt else 0)       # the edge is 145 .. 160 clocks in front of HALT
    return wins, ent


def set_h2x(js, halt=True, pin="INT"):
    """f5_le_h2a's window; the edge j + 1 clocks (and a tick) behind the start of the core's first clock of HALT.
    pin NMI: the request is the NMI pin (the later NMI is then a second pulse)."""
    wins, ent = [], []
    for j in js:
        k = len(wins)
        ops = (("ev", k + 1), ("mark", 1), ("dw0",), ("sl", 0)) + h2_tail(halt)
        wins.append(pa.window("h2x" if pin == "INT" else "n2x", k, ops, pre=(("ei",),), kind="halt" if halt else "nop",
                              a=0, j=j))
        d = H2_E2M + (H2_POP["a"] + j + 1) * CLK + H2_PH - 4
        if pin == "INT":
            ent += h2_ent(k + 1, d, nmi=H2_NMI if halt else 0)
        else:
            ent.append(dict(event=k + 1, delay=d, hold=600, levels={"NMI": 0}))
            if halt:
                ent.append(dict(event=None, delay=H2_NMI * CLK - 600 - 10, hold=600, levels={"NMI": 0}))
    return wins, ent


def set_h2g():
    """INT raised with IE 0 (the event; two fillers), mark 1, f5_le_h2a's sled, EI, ROL BP,n (n 1 .. 16), HALT."""
    wins, ent = [], []
    for n in range(1, 17):
        k = len(wins)
        ops = (("ev", k + 1), ("fil", 2), ("mark", 1), ("dw0",), ("sl", 0), ("ei",), ("rol", n)) + h2_tail(True)
        wins.append(pa.window("h2g", k, ops, kind="halt", a=0, rn=n))
        ent += h2_ent(k + 1, 200, nmi=360)
    return wins, ent


def set_h2p():
    wins, ent = [], []
    for x in range(16):
        for j in (0, 1):
            k = len(wins)
            ops = ((("st", 0xFF9D, 0x47), ("sled", x), ("ev", k + 1), ("mark", 1), ("dw0",), ("sl", 0))
                   + pa.train("halt"))
            wins.append(pa.window("h2p", k, ops, pre=(("ei",),), odd=x & 1, kind="halt", a=0, rx=x, j=j))
            ent += h2_ent(k + 1, H2_E2M + (H2_POP["p"] + (x & 1) + 31 + j) * CLK + H2_PH - 4)
    return wins, ent


def d_programs():
    progs = [g_prog(f"f5_lg_a{i:02d}", keys) for i, keys in enumerate(G_PAIRS)]
    masked = (("ei",), ("st", 0xFF4C, 0xC7))
    for name, (wins, ent), note in (
            ("h2n", set_h2v(0, "nop"), "H2: f5_le_h2a with a NOP train in HALT's place"),
            ("h2o", set_h2v(1, "nop"), "H2: f5_le_h2b with a NOP train in HALT's place"),
            ("h2m", set_h2v(0, "halt", pre=masked), "H2: f5_le_h2a with INTP0's flag set and masked"),
            ("h2q", set_h2v(1, "halt", pre=masked), "H2: f5_le_h2b with INTP0's flag set and masked"),
            ("h2e", set_h2e(True), "H2: INT standing with IE 0; a sled, EI, HALT"),
            ("h2f", set_h2e(False), "H2: INT standing with IE 0; a sled, EI, a NOP train"),
            ("h2x", set_h2x(range(-20, -4)), "H2: the INT edge 20 .. 5 clocks in front of the core's pop of HALT"),
            ("h2y", set_h2x(range(-4, 12)), "H2: the INT edge from 4 clocks in front of the core's pop of HALT to 11 behind"),
            ("h2z", set_h2x(range(-20, 12), halt=False), "H2: the same 32 edges, a NOP train in HALT's place"),
            ("h2p", set_h2p(), "H2: the scan's restart a sled of 0 .. 15 clocks in front of f5_le_h2a's window")):
        progs.append(pa.prog("f5_lg_" + name, wins, note, entries=ent, intak=True))
    wins, ent = set_h2g()
    progs.append(pa.prog("f5_lg_h2g", wins, "H2: INT standing with IE 0; EI, ROL BP,n, HALT", entries=ent, intak=True))
    for name, (wins, ent), note in (
            ("n2x", set_h2x(range(-20, -4), pin="NMI"), "f5_lg_h2x with the NMI pin as the request"),
            ("n2y", set_h2x(range(-4, 12), pin="NMI"), "f5_lg_h2y with the NMI pin as the request"),
            ("n2z", set_h2x(range(-20, 12), halt=False, pin="NMI"), "f5_lg_h2z with the NMI pin as the request")):
        progs.append(pa.prog("f5_lg_" + name, wins, note, entries=ent))
    return {q.name: q for q in progs}


def programs():
    return {**a_programs(), **b_programs(), **c_programs(), **d_programs()}


def one(name):
    """f5_le_bV.s: window s of f5_le_bV as a program of its own."""
    v, s = name[len("f5_le_b"):].split(".")
    return hb_prog(v, int(s))


SIM1_LIMIT = 1_500_000          # ticks: a window's program ends inside 150,000
G_LIMIT = 8_000_000             # ticks: a rows-4 program ends inside 3,000,000


def sim_g(name, tag, progs, limit=G_LIMIT):
    """phase.run_set for one program on the core with the run's length bounded."""
    from .traps import _sim, _stim
    transport, harness = _sim()
    try:
        _stim(harness, progs[name])
        rec = ph.run_one(harness, progs[name], "model", limit=limit)
    finally:
        transport.close()
    ph._stamp(rec, "sim")
    ph._save(rec, name, "sim" + tag)
    print(f"{name}: sim{tag} {'PASS' if rec['passed'] else 'FAIL'} status=0x{rec['status']:04x} total={rec['total']} "
          f"records={len(rec['trace'])} timeout={rec['timeout']} replay={rec['replay']} "
          f"residual={rec['stitch_residual']}", flush=True)


def sim1(names, tag=""):
    """Every window of a B.2 program as a run of its own on the core, the run's length bounded: one receipt
    (f5-NAME-sim1.json: {"runs": {s: record}}); a run that ends on the limit has `timeout`."""
    import json
    from .traps import _sim, _stim
    for n in names:
        runs = {}
        for s in range(NSLED.get(n[len("f5_le_b"):], 16)):
            prog = one(f"{n}.{s}")
            transport, harness = _sim()
            try:
                _stim(harness, prog)
                rec = ph.run_one(harness, prog, "model", limit=SIM1_LIMIT)
            finally:
                transport.close()
            runs[str(s)] = rec
            print(f"{n}.{s}: sim1 {'PASS' if rec['passed'] else 'FAIL'} timeout={rec['timeout']} total={rec['total']}",
                  flush=True)
        ph.receipt_path(n, "sim1" + tag).write_text(json.dumps(
            dict(program=n, backend="sim1", core="v35", limit=SIM1_LIMIT, runs=runs), separators=(",", ":")) + "\n")


# ------------------------------------------------------------------ (WO52) the gate
# A B.2 window run on its own (sim1) sits at another place in the code than the same window of the whole program
# the socket ran: its fetch addresses and the pushed PC are compared relative to the window's HALT (meta
# "halts"), everything else as phase.compare / onchip_t.norm_window has it (records, data unless a read, ticks
# after the begin marker within 1, pins within 4), with /HLDAK's level (P26) beside P15's in the pin records. Not
# compared: the code fetches' data (past the window a prefetch reads the next window's code, or the end's) and the
# event's number (the event record's, and AW stored holding it in AL), and in the take's PSW push the status flags
# (V, S, Z, AC, P, CY: what the windows in front left).
EV_PORT = 0xFF12


def b_norm(w, halt, code_end, ev):
    out = [("T", w["T"])]
    vec = False
    for kind, r in w["rows"]:
        if kind == "pin":
            out.append(("pin", r[1] & oc.P15, r[0] - w["t0"], r[2] >> 6 & 1))
            continue
        a, d = r[1], (r[2] if kind in ("mw", "iow", "fetch") else 0)
        if kind == "mr" and a < 0x80:
            vec = True
        elif kind == "mw" and vec:
            vec, d = False, ("psw", d & ~0x08D5)     # the take's PSW push: the status flags are the history's
            out.append((kind, a, d, r[0] - w["t0"], oc.waits_of(r)))
            continue
        if kind == "fetch" and oc.CODE <= a < code_end + 0x20:
            a, d = ("code", a - oc.CODE - halt), None      # a prefetch past the window reads the next window's code
        if kind == "iow" and a == EV_PORT:
            d = None                                        # the event record's number: the window's in the program
        if kind == "mw" and d & 0xFF == ev:
            d = ("ev", d >> 8)                  # AW stored holding the event's number in AL
        elif kind == "mw" and abs(d - halt) <= 4:
            d = ("pc", d - halt)                # the pushed PC: HALT's offset or one / two behind it
        out.append((kind, a, d, r[0] - w["t0"], oc.waits_of(r)))
    return out


def gate_b(name, ref, cand, progs, verbose=False, tol=1, pin_tol=4):
    """socket window k of the whole program against sim1 run k (window 0 of the one-window program)."""
    from . import introws2_read as rd
    p = progs[name]
    a = ph.load(name, ref)
    if a["program_sha256"] != hashlib.sha256(p.build()["text"]).hexdigest():
        print(f"{name}: the {ref} receipt is of another program")
        return 0, len(p.windows), False
    runs = ph.load(name, cand)["runs"]
    wa, _ = oc.windows(a, p)
    ea = p.build()["code_end"]
    diff, still = [], 0
    for k, w in enumerate(p.windows):
        rec = runs.get(str(k))
        p1 = one(f"{name}.{k}")
        if rec is None:
            diff.append((k, "no run"))
            continue
        if rec["program_sha256"] != hashlib.sha256(p1.build()["text"]).hexdigest():
            diff.append((k, "the run is of another program"))
            continue
        if rec["timeout"] or k not in wa:
            still += bool(rec["timeout"])
            diff.append((k, "stands still (the run ends on the limit)" if rec["timeout"] else "missing"))
            continue
        wb = rd.all_windows(rec, p1).get(0)
        if wb is None or wb["T"] is None:
            diff.append((k, "the window does not end"))
            continue
        x = b_norm(wa[k], w.meta["halts"][0], ea, k + 1)
        y = b_norm(wb, p1.windows[0].meta["halts"][0], p1.build()["code_end"], 1)
        xb, yb = [q for q in x if q[0] != "pin"], [q for q in y if q[0] != "pin"]
        xp, yp = [q for q in x if q[0] == "pin"], [q for q in y if q[0] == "pin"]
        if not oc.near(xb, yb, tol) or not oc.near(xp, yp, pin_tol):
            dt = wb["T"] - wa[k]["T"]
            diff.append((k, f"T {wa[k]['T']} / {wb['T']} ({oc.clocks(dt)} clocks)"
                         + ("" if abs(dt) > tol else "; same length, records differ")))
    n = len(p.windows)
    print(f"{name}: {ref} / {cand}: {'EQUAL' if not diff else 'DIFFER'} ({n - len(diff)} of {n} windows equal; "
          f"{still} stand still; one window a run, bounded at {SIM1_LIMIT} ticks)")
    for k, why in diff[:None if verbose else 6]:
        m = p.windows[k].meta
        print(f"  w{k} {m.get('series', '')} s{m.get('sl', '')}: {why}")
    return n - len(diff), n, not diff


def gate(names, ref, cand, progs, verbose=False):
    """Every set against the socket: the B.2 sets (f5_le_b*) window by window against `sim1` receipts (one
    window a run, bounded: a window that stands still loses only itself), the others against the whole-program
    `sim` receipt (phase.compare). One line a set, then the total."""
    eq = tot = 0
    ok = True
    for n in names:
        if n.startswith("f5_le_b"):
            e, t, o = gate_b(n, ref, "sim1" + cand[len("sim"):] if cand.startswith("sim") else cand, progs, verbose)
        else:
            if not ph.receipt_path(n, cand).exists():
                print(f"{n}: no {cand} receipt")
                ok = False
                continue
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                o = ph.compare(n, ref, cand, progs, verbose=verbose)
            text = buf.getvalue()
            print(text, end="")
            import re
            m = re.search(r"\((\d+) of (\d+) windows equal", text)
            e, t = (int(m.group(1)), int(m.group(2))) if m else (0, len(progs[n].windows))
        eq, tot, ok = eq + e, tot + t, ok and o
    print(f"introws2 total: {eq} of {tot} windows equal in {len(names)} sets")
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "sim1", "repeat", "gate", "emit", "read"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--trace", action="store_true", help="sim: the core's trace / idbg / qdbg into build/tr/NAME.*")
    p.add_argument("--brief", action="store_true", help="read (A): one line a lead")
    p.add_argument("--whole", action="store_true", help="sim: the B.2 sets as whole programs (default: sim1)")
    p.add_argument("--socket-fitted", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    progs = programs()
    names = a.names or list(progs)
    if a.action == "socket":
        if not a.socket_fitted:
            p.error("the socket action needs --socket-fitted")
        ph.run_set(names, "socket", a.tag, progs)
        return 0
    if a.action == "sim":
        if not a.trace and not a.whole:
            # (WO52) the B.2 sets one window a run, bounded (a window may stand in HALT for good): sim1
            sim1([n for n in names if n.startswith("f5_le_b")], a.tag)
            names = [n for n in names if not n.startswith("f5_le_b")]
        for n in names:
            if a.trace:
                os.makedirs("build/tr", exist_ok=True)
                os.environ["V35_PLUSARGS"] = (f"+v35_trace=build/tr/{n}.trace +v35_idbg=build/tr/{n}.idbg "
                                              f"+v35_qdbg=build/tr/{n}.qdbg")
            if n.startswith("f5_lg_"):
                sim_g(n, a.tag, progs)      # (rows 4) a HALT may stand for good: the run's length bounded
            else:
                ph.run_set([n], "sim", a.tag, progs)
        return 0
    if a.action == "sim1":
        sim1([n for n in names if n.startswith("f5_le_b")], a.tag)
        return 0
    if a.action == "gate":
        return 0 if gate(names, a.ref, a.cand + a.tag, progs, verbose=a.verbose) else 1
    if a.action == "repeat":
        ok = True
        for n in names:
            ok &= ph.compare(n, a.ref, "socket-2", progs, verbose=a.verbose)
        return 0 if ok else 1
    if a.action == "emit":
        ph.emit({n: progs[n] for n in names})
        return 0
    from . import introws2_read as rd
    return rd.main(a, progs, names)


if __name__ == "__main__":
    sys.exit(main())
