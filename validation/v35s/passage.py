"""F5: the request's passage to the instruction boundary (the f5_pa_* program set): what the
clocks between the interrupt controller's offer slot and the take are made of, on the socketed
uPD70337 and on the core v2 RTL in simulation. A sibling of validation/v35s/lattice.py (its
frame through phase.py: windows between the markers, receipts, stitching, comparison).

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.passage socket --socket-fitted [NAME ...] [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.passage sim [NAME ...] [--tag -wo33]
    PYTHONPATH=host/src:. python3 -m validation.v35s.passage summary [NAME ...] [--ref socket|sim] [-v]
    PYTHONPATH=host/src:. python3 -m validation.v35s.passage cut [NAME ...] [--ref sim]      (the earliest take by boundary)
    PYTHONPATH=host/src:. python3 -m validation.v35s.passage hold [NAME ...]                 (bus cycles in front of the take against the twin)
    PYTHONPATH=host/src:. python3 -m validation.v35s.passage repeat [NAME ...]      (socket / socket-2)
    PYTHONPATH=host/src:. python3 -m validation.v35s.passage gate [NAME ...] [--cand sim]
    PYTHONPATH=host/src:. python3 -m validation.v35s.passage takes [NAME ...] [--cand sim]
    PYTHONPATH=host/src:. python3 -m validation.v35s.passage emit
    PYTHONPATH=host/src:. python3 -m validation.v35s.passage pe [pe_] [--ref sim] [-v]   (the fifth set: f5_pe_*)
    PYTHONPATH=host/src:. python3 -m validation.v35s.passage pf [pf_ | pe_h4] [--ref sim] [-v]   (the sixth set: f5_pf_*)

Series (one program a kind of instruction X; `_r` the twin in which nothing is taken: the
request masked or the pin not pulsed; `_b` the twin with BRK 3 behind X: a boundary whose
vector read is on the pins):

    (X jsh: BR $+2 ; ROL BP,CL: the queue emptied, its refill's fetches run through a long shift)
    c_X     the boundary's cut-off for a controller request: TM0 counts out (TOUT) into the
            scan round a request control store (TMIC1) started, the slot at a fixed clock from
            that store; X behind a one-clock sled swept across it
    n_X     the same for the NMI pin (no scan): the edge a fixed delay after the event, the sled
            swept
    i_X     the same for the INT pin (PMC1 bit 4; the acknowledge on /INTAK, P13)
    q_*     IE 0, a request pending in its slots (period 18); IE raised by EI, POP PSW or RETI
            behind a sled of 40 clocks: where IE rises against the datum's read, and the clocks
            from the slot's first clock to the take
    e_*     INT standing with IE 0; EI, POP PSW or RETI, then X: the instructions run before
            the acknowledge
    *_k4, *_k2   the processor clock at fX/4 and fX/2 (PRC)
    pe_HOWwb     (the fifth set) q with two requests pending, the worse level w on TM0 and the better b
            on INTP0: IE's rise swept across both slots of the round of 20 (which vector, at which clock)
    pe_h1 .. h4  four levels pending; a real handler (FINT in it), its RETI swept across the slots
    pf_a .. c    (the sixth set) pe_h4 with f3_prio's handler tail (FINT ; RET ; DEC ; five POPs ; POP PSW ;
            RETI, about 200 clocks) between FINT and the RETI's rise: the sled behind FINT (a), in front of
            FINT (b), in front of POP PSW (c)

Time marks: the stores of `mark` (00D80h + 2j), TOUT on P15, /INTAK on P13, the vector reads,
the pushes (the third is the PC: it names the boundary), the scheduled edge (the event's record
+ delay + 4 ticks). Receipts: validation/v35s/receipts/f5-<name>-<backend>.json.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys

from . import lattice as la
from . import onchip_t as oc
from . import phase as ph
from .wtc import Asm

CODE, STACK_TOP = oc.CODE, oc.STACK_TOP
MARK, HBASE = la.MARK, la.HBASE
VEC = dict(la.VEC, nmi=0x08, brk=0x0C, int=0x2C)
IC = la.IC
P13, P15 = 1 << 11, 1 << 13
INT_VEC = 0x0B
VEC_RD = dict(VEC, dma0=0x50)           # the reading side: DIC0's vector (20) too (the fourth set)
LDS_AT = 0x0D00
PRC = {8: 0x4E, 4: 0x4D, 2: 0x4C}       # RAMEN 1, the time base as at reset, PCK fX/8, /4, /2

# X: (bytes, text) of one instruction of the kind; i counts the copies in the window
KINDS = {
    "inc": lambda i: ([0x40], "INC AW"),
    "nop": lambda i: ([0x90], "NOP"),
    "cbw": lambda i: ([0x98], "CVTBW"),
    "mul": lambda i: ([0xF7, 0xE6], "MULU IX   ; IX = 1"),
    "div": lambda i: ([0xF7, 0xF6], "DIVU IX   ; IX = 1, DW = 0"),
    "shcl": lambda i: ([0xD3, 0xC5], "ROL BP, CL"),
    "wr": lambda i: ([0x36, 0xA3, (MARK + 32 + 2 * i) & 0xFF, (MARK + 32 + 2 * i) >> 8],
                     f"MOV SS:[{MARK + 32 + 2 * i:04X}h], AW"),
    "push": lambda i: ([0x50], "PUSH AW"),
    "rd": lambda i: ([0x36, 0xA1, LDS_AT & 0xFF, LDS_AT >> 8], f"MOV AW, SS:[{LDS_AT:04X}h]"),
    "lds": lambda i: ([0x36, 0xAD], "LDMW SS:   ; one element"),
    "repl": lambda i: ([0x36, 0xF3, 0xAD], "REP LDMW SS:   ; CW elements"),
    "brk": lambda i: ([0xCC], "BRK 3"),
    "halt": lambda i: ([0xF4], "HALT"),
    # the third set: a store into block 2 (DS1 4000h: its waits are WTC's field 2), an OUT (the I/O
    # field), XCH AW,BW (NOP's routine with another register), BR $+2 alone
    "ws": lambda i: ([0x26, 0xA3, 0x00, 0x0D], "MOV DS1:[0D00h], AW   ; DS1 4000h: block 2"),
    "out": lambda i: ([0xE7, 0x80], "OUT 80h, AW"),
    "xch": lambda i: ([0x93], "XCH AW, BW"),
    "br": lambda i: ([0xEB, 0x00], "BR $+2"),
    "sfr": lambda i: oc.form("pimb", 0xFF00, 0),      # an on-chip store (P0's latch)
}
for _k, _b in (("ws1", "ws"), ("ws2", "ws"), ("out2", "out")):
    KINDS[_k] = KINDS[_b]
# the fourth set: stores of one form (a prefixed MOV byte m, imm8) to the timer unit's registers (the
# six-clock grid), the DMA registers, internal RAM, and to external memory (`wi`: f4_dma's `cw`)
KINDS.update({
    "tmc": lambda i: oc.form("pimb", 0xFF91, 0),        # TMC1
    "tmc0": lambda i: oc.form("pimb", 0xFF90, 0),       # TMC0
    "md": lambda i: oc.form("pimb", 0xFF8A, 0x63),      # MD1's low byte
    "md0": lambda i: oc.form("pimb", 0xFF82, 0x63),     # MD0's low byte
    "mdw": lambda i: oc.form("pimw", 0xFF8A, 0x0063),   # MD1, a word: two byte cycles
    "dmam": lambda i: oc.form("pimb", 0xFFA1, 0),       # DMAM0
    "dmac": lambda i: oc.form("pimb", 0xFFA0, 0x11),    # DMAC0
    "dblk": lambda i: oc.form("pimb", 0xFE0C, 0),       # channel 1's block (internal RAM)
    "wi": lambda i: ([0x36, 0xC6, 0x06, (MARK + 32 + 2 * i) & 0xFF, (MARK + 32 + 2 * i) >> 8, 0x00],
                     f"MOV byte SS:[{MARK + 32 + 2 * i:04X}h], 00h"),
})


def emit_ops(a, ops, meta=None):
    """lattice.emit_ops with: sl s (MOV AH,[BW], its wait the odd clock, and ROL BP 1 + s//2: a
    sled from its shortest), x kind n (n instructions of the kind), dw0 (XOR DW,DW), cw n, retif v
    (a frame PSW v / PS / the next offset pushed, mark j, RETI), pushv v (MOV AW,v ; PUSH AW),
    popf (POP PSW), k name (nothing: the meta's label of the next instruction)."""
    for op in ops:
        k = op[0]
        if k == "sl":
            a.op([0x8A, 0x27], "MOV AH, [BW]   ; block 1: the sled's odd clock is its wait")
            oc.roli(a, 1 + op[1] // 2)
        elif k == "x":
            for i in range(op[2]):
                if meta is not None:
                    meta.setdefault("x", []).append(len(a.b))
                if op[1] == "jsh":
                    a.op([0xEB, 0x00], "BR $+2   ; the queue emptied: the fetches run through the shift")
                    a.op([0xD3, 0xC5], "ROL BP, CL")
                    continue
                if op[1] == "jwr":
                    a.op([0xEB, 0x00], "BR $+2   ; the queue emptied: the store's bytes arrive as it runs")
                    a.op(*KINDS["wr"](i))
                    continue
                a.op(*KINDS[op[1]](i))
                if op[1] == "halt":
                    a.op([0x90], "NOP")
        elif k == "dw0":
            a.op([0x33, 0xD2], "XOR DW, DW")
        elif k == "ds1":
            a.mov_r("AW", op[1])
            a.mov_sr("DS1")
            a.mov_r("AW", 1)
        elif k == "cw":
            a.mov_r("CW", op[1])
        elif k == "pushv":
            a.mov_r("AW", op[1])
            a.op([0x50], "PUSH AW")
        elif k == "popf":
            a.op([0x9D], "POP PSW")
        elif k == "retif":
            a.mov_r("AW", op[1])
            a.op([0x50], "PUSH AW")
            a.op([0x0E], "PUSH PS")
            t = len(a.b) + 3 + 1 + 4 + 1
            a.mov_r("AW", t)
            a.op([0x50], "PUSH AW")
            o = MARK + 2 * op[2]
            a.op([0x36, 0xA3, o & 0xFF, o >> 8], f"MOV SS:[{o:04X}h], AW   ; mark {op[2]}")
            a.op([0xCF], "RETI")
            assert len(a.b) == t
        else:
            la.emit_ops(a, [op], meta)


H_PLAIN = la.H_PLAIN
H_STOP = (("st", 0xFF90, 0x00), ("fint",), ("reti",))       # TM0 stopped: one request a window


def window(series, n, ops, pre=(), odd=0, md0=66, hand=None, ic=None, ix=1, cw=0, clk=8, wt=0, note="", **kw):
    """lattice.window with IX, CW and the processor clock (PRC) set in the setup, DW and PRC put
    back at the end; wt: more WTC fields (block 1's is the sled's); meta["ins"]: the body's
    instructions (offset, text)."""
    meta = dict(series=series, form=note or series, target=f"md0 {md0}", seg="-", shape="pa", n=n)
    meta.update(kw)
    hand = dict(hand or {})
    ic = dict(ic or {})
    win = la.Window(meta, None, None)
    win.hand = hand

    def setup(a):
        oc.wtc0(a)
        oc.es_store(a, 0xFF90, 0x00)
        oc.es_store(a, 0xFF91, 0x00)
        oc.es_store(a, 0xFF82, md0, word=True)
        oc.es_store(a, 0xFF80, md0, word=True)
        oc.seg(a, "DS0", la.DS0V)
        a.mov_r("BW", la.BWV)
        a.mov_r("SP", STACK_TOP)
        a.mov_r("BP", 0)
        a.mov_r("CW", cw)
        a.mov_r("IX", ix)
        for src in VEC:
            at = win.addr[hand.get(src, H_PLAIN)]
            a.op([0x36, 0xC7, 0x06, VEC[src], 0x00, at & 0xFF, at >> 8],
                 f"MOV word SS:[{VEC[src]:04X}h], {at:04X}h   ; {src}'s handler")
        for src, v in ic.items():
            oc.es_store(a, IC[src], v)
        oc.es_store(a, 0xFFE8, odd << 2 | wt, word=True)
        if clk != 8:
            oc.es_store(a, 0xFFEB, PRC[clk])
        emit_ops(a, pre)
        a.mov_r("AW", 1)

    def body(a):
        at, nl = len(a.b), len(a.lines)
        emit_ops(a, ops, meta)
        ins = []
        for bs, text in a.lines[nl:]:
            if bs:
                ins.append((at, text.split("   ;")[0]))
                at += len(bs)
        meta["ins"] = ins
        a.op([0xFA], "DI")
        if clk != 8:
            oc.es_store(a, 0xFFEB, PRC[8])
        oc.es_store(a, 0xFF90, 0x00)
        oc.es_store(a, 0xFF91, 0x00)
        for src in IC:
            oc.es_store(a, IC[src], 0x47)
        ph.wtc1(a, 0)
        a.mov_r("DW", oc.M_BEGIN)
    win.setup, win.body = setup, body
    return win


def init(a):
    oc.ports_on(a)
    oc.es_store(a, 0xFF0A, 0x38)        # PMC1: TOUT on P15, INT enabled, /INTAK on P13


def prog(name, wins, note, entries=None, intak=False, clk=8):
    p = la.Program(name, wins, note, init=init, fini=oc.ports_off, pins=["P13", "P15"], entries=entries)
    if intak:
        p.stim["intak_vector"] = INT_VEC
        p.stim["int_release"] = True
    p.clk = clk
    return p


# ------------------------------------------------------------------ the series
START = la.START
LONG = ("mul", "div", "shcl", "repl")
# per kind: the instruction's operands (window keywords)
KW = {"shcl": dict(cw=12), "jsh": dict(cw=20), "repl": dict(cw=6, ix=LDS_AT), "lds": dict(ix=LDS_AT),
      "ws1": dict(wt=1 << 4), "ws2": dict(wt=2 << 4), "out2": dict(wt=2 << 14)}
NS = 36
# c: TM0's count (MD0) by kind: the count-out (TOUT) falls in the middle of the 16 clocks in front
# of the scan round whose level-0 slot is about 14 clocks in front of X's end at the middle of the
# sweep (the request control store's restart is about 12 clocks after mark 1's write; pilot run)
C_MD = dict(inc=23, nop=23, cbw=23, halt=23, wr=25, push=25, rd=25, lds=25, mul=28, shcl=28, div=31, repl=39, jsh=25,
            out=25, out2=25, tmc=25, sfr=25, wi=25)
# n / i: the edge's delay after the event's record in clocks, by kind: the edge 16 clocks in front
# of where mark 2 is written at the middle of the sweep (pilot run: mark 1 is 18 clocks behind the
# event's record, mark 2 at the sled's s = 16 is 57 / 66 / 88 / 91 / 149 behind mark 1)
N_CLK = dict(jsh=65, inc=59, halt=59, wr=68, mul=90, shcl=93, repl=151)


def train(kind, brk=False):
    return ((("x", kind, 1),) + ((("x", "brk", 1),) if brk else ())
            + (("mark", 2), ("mark", 3), ("inc", 12)))


def set_c(kind, lv=0, masked=False, brk=False, clk=8, md=None, ns=NS):
    md, f = md or C_MD[kind], 2
    out = []
    for s in (range(0, 8) if brk else range(ns)):
        ops = ((("ei",), START, ("mark", 0), ("fil", f), ("mark", 1), ("st", 0xFF9D, 0x47), ("dw0",),
                ("sl", s)) + train(kind, brk))
        out.append(window("c", s, ops, odd=s & 1, md0=md, hand={"tm0": H_STOP},
                          ic={"tm0": 0x40 | lv if masked or brk else lv}, clk=clk, kind=kind, lv=lv,
                          **KW.get(kind, {})))
    return out


def set_pin(series, kind, pin, pulsed=True, brk=False, clk=8, half=0, ns=32):
    """The event, mark 1, the sled, X: the pin's edge N_TUNE[kind] (+ half) ticks after the event."""
    out, ent = [], []
    for s in (range(0, 8) if brk else range(ns)):
        ops = ((("ev", s + 1), ("mark", 1), ("dw0",), ("sl", s)) + train(kind, brk))
        out.append(window(series, s, ops, pre=(("ei",),), odd=s & 1, clk=clk, kind=kind,
                          **KW.get(kind, {})))
        if pulsed and not brk:
            d = N_CLK[kind] * 4 * clk - 4 + half
            ent.append(dict(event=s + 1, delay=d, hold=600, levels={"NMI": 0}) if pin == "NMI" else
                       dict(event=s + 1, delay=d, hold=0, levels={"INT": 1}))
    return out, ent


QP = {"0": 0x80, "7": 0x87}
RAISE = {
    "ei": (("mark", 1), ("ei",)),
    "pop": (("pushv", 0xF202), ("mark", 1), ("popf",)),
    "reti": (("retif", 0xF202, 1),),
}


def set_q(how, lv, n=40):
    """IE 0: TMIC0's IF stored 1 at level lv (the slots: period 18), a sled of x clocks, then IE
    raised (EI behind mark 1; POP PSW behind mark 1; RETI behind mark 1), 40 INC AW."""
    return [window("q", x, (("st", 0xFF9C, QP[lv]), ("sled", x)) + RAISE[how] + (("inc", 40),),
                   odd=x & 1, how=how, lv=int(lv)) for x in range(n)]


def set_e(how):
    """INT raised with IE 0 (the event; two fillers), IE raised, then a train of X; by kind and sled."""
    out, ent = [], []
    for kind in ("inc", "nop", "wr", "mul", "cbw", "push", "rd", "shcl"):
        for s in range(4):
            j = len(out) + 1
            ops = ((("ev", j), ("fil", 2), ("dw0",), ("sl", s)) + RAISE[how] + (("x", kind, 4), ("mark", 2), ("inc", 8)))
            out.append(window("e", s, ops, odd=s & 1, how=how, kind=kind, **KW.get(kind, {})))
            ent.append(dict(event=j, delay=200, hold=0, levels={"INT": 1}))
    return out, ent


# HALT: the windows whose request is not taken in front of the HALT (a taken one leaves it standing)
H_NS = dict(c=18, n=24, i=20)
C_KINDS = ("inc", "nop", "cbw", "wr", "push", "rd", "lds", "repl", "mul", "div", "shcl", "halt", "jsh")
N_KINDS = ("inc", "wr", "mul", "shcl", "repl", "halt", "jsh")
I_KINDS = ("inc", "wr", "mul", "halt", "jsh")
K_KINDS = ("wr", "mul")


def programs():
    progs = []
    for kind in C_KINDS:
        progs.append(prog(f"f5_pa_c_{kind}", set_c(kind, ns=H_NS["c"] if kind == "halt" else NS), f"TM0's request against {kind}'s boundary, the sled swept"))
        if kind != "halt":
            progs.append(prog(f"f5_pa_c_{kind}_r", set_c(kind, masked=True), "the twin: the request masked"))
            progs.append(prog(f"f5_pa_c_{kind}_b", set_c(kind, brk=True), "the twin: BRK 3 behind X, the request masked"))
    for kind in ("wr", "mul"):
        progs.append(prog(f"f5_pa_c7_{kind}", set_c(kind, lv=7), f"the same at level 7 ({kind})"))
    for series, pin, kinds in (("n", "NMI", N_KINDS), ("i", "INT", I_KINDS)):
        for kind in kinds:
            for sfx, kw in (("", {}), ("_h", dict(half=16)), ("_r", dict(pulsed=False))):
                if (sfx == "_h" and kind not in ("wr", "mul")) or (sfx == "_r" and kind == "halt"):
                    continue
                if kind == "halt":
                    kw = dict(kw, ns=H_NS[series])
                wins, ent = set_pin(series, kind, pin, **kw)
                progs.append(prog(f"f5_pa_{series}_{kind}{sfx}", wins, f"the {pin} pin against {kind}'s boundary"
                                  + (" (the twin: no edge)" if sfx == "_r" else ", half a clock later" if sfx else ""),
                                  entries=ent, intak=pin == "INT"))
    for how, lv in (("ei", "0"), ("ei", "7"), ("pop", "0"), ("pop", "7"), ("reti", "0"), ("reti", "7")):
        progs.append(prog(f"f5_pa_q_{how}{lv}", set_q(how, lv),
                          f"IE 0, TM0 pending at level {lv}: IE raised by {how}, the sled swept"))
    for how in RAISE:
        wins, ent = set_e(how)
        progs.append(prog(f"f5_pa_e_{how}", wins, f"INT standing with IE 0: {how}, then X", entries=ent, intak=True))
    for clk in (4, 2):
        for kind in K_KINDS:
            progs.append(prog(f"f5_pa_c_{kind}_k{clk}", set_c(kind, clk=clk), f"c_{kind} at fX/{clk}", clk=clk))
            progs.append(prog(f"f5_pa_c_{kind}_k{clk}_r", set_c(kind, clk=clk, masked=True), "its twin", clk=clk))
            for sfx, kw in (("", {}), ("_r", dict(pulsed=False))):
                wins, ent = set_pin("n", kind, "NMI", clk=clk, **kw)
                progs.append(prog(f"f5_pa_n_{kind}_k{clk}{sfx}", wins, f"n_{kind} at fX/{clk}", entries=ent, clk=clk))
    return {p.name: p for p in progs}


# ------------------------------------------------------------------ the second set (what the line is)
PSW0 = 0xF002                       # IE 0
E2M1 = 18                           # mark 1's write after the event's record (clocks; the n series)


def ent_int(ev, clocks, ticks=0, hold=0):
    return dict(event=ev, delay=clocks * 32 - 4 + ticks, hold=hold, levels={"INT": 1})


def set_v(lv, n=32):
    """Test 1: TM0's request (level lv) in the scan round a TMIC1 store started, an INC train; INT's
    edge swept a clock a window across the request's clock."""
    out, ent = [], []
    for j in range(n):
        ops = (("ei",), ("ev", j + 1), START, ("mark", 0), ("fil", 2), ("mark", 1), ("st", 0xFF9D, 0x47),
               ("dw0",), ("x", "inc", 60))
        out.append(window("v", j, ops, md0=23, hand={"tm0": H_STOP}, ic={"tm0": lv}, lv=lv))
        ent.append(ent_int(j + 1, V_BASE + j))
    return out, ent


V_BASE = 158                        # the edge after the event (pilot: mark 1 is 129 behind the event)


def set_d(src, how, n=32):
    """Test 2: IE cleared (DI, or POP PSW with IE 0) behind the sled, the request's clock fixed: INT's
    edge (src i) or TM0's count-out into its slot (src c). Then mark 2, mark 3, EI, six NOP (a
    request that was held is taken there)."""
    out, ent = [], []
    clr = (("di",),) if how == "di" else (("popf",),)
    tail = clr + (("mark", 2), ("mark", 3), ("ei",), ("nop", 6))
    pv = (("pushv", PSW0),) if how == "pf" else ()
    for s in range(n):
        if src == "i":
            ops = pv + (("ev", s + 1), ("mark", 1), ("dw0",), ("sl", s)) + tail
            out.append(window("d", s, ops, pre=(("ei",),), odd=s & 1, how=how, src=src))
            ent.append(ent_int(s + 1, E2M1 + 44))
        else:
            ops = pv + (("ei",), START, ("mark", 0), ("fil", 2), ("mark", 1), ("st", 0xFF9D, 0x47),
                        ("dw0",), ("sl", s)) + tail
            out.append(window("d", s, ops, odd=s & 1, md0=23, hand={"tm0": H_STOP}, ic={"tm0": 0},
                              how=how, src=src))
    return out, ent


H_RETI = (("reti",),)               # no FINT: the level stays in service


def set_f(isp=3, rq=3, n=40):
    """Test 3: level 3 in service (INTP0's request taken in the setup, its handler RETI alone);
    TM0's IF stored 1 at level 3 (blocked), a sled of x clocks, mark 1, FINT, 40 INC AW; FINT again
    at the end."""
    out = []
    for x in range(n):
        ops = (("st", 0xFF9C, 0x80 | rq), ("sled", x), ("mark", 1), ("fint",), ("inc", 40), ("fint",))
        out.append(window("f", x, ops, pre=(("ei",), ("st", 0xFF4C, 0x80 | isp), ("nop", 12)), odd=x & 1,
                          hand={"p0": H_RETI}, how="fint", lv=rq))
    return out


def set_pw(pin, widths):
    """(i) a pulse of the pin `w` ticks wide against an INC train (sled 16)."""
    out, ent = [], []
    for j, w in enumerate(widths):
        ops = (("ev", j + 1), ("mark", 1), ("dw0",), ("sl", 16), ("x", "inc", 40))
        out.append(window("w", j, ops, pre=(("ei",),), w=w))
        ent.append(dict(event=j + 1, delay=(E2M1 + 30) * 32 - 4, hold=w,
                        levels={"INT": 1} if pin == "INT" else {"NMI": 0}))
    return out, ent


GAPS = [(a, g) for a in (2, 4, 6, 8) for g in (1, 2, 4)]


def set_gap():
    """(i) INT high for a clocks, low for g, then high for good (a chained entry), an INC train."""
    out, ent = [], []
    for j, (a, g) in enumerate(GAPS):
        ops = (("ev", j + 1), ("mark", 1), ("dw0",), ("sl", 16), ("x", "inc", 40))
        out.append(window("g", j, ops, pre=(("ei",),), a=a, g=g))
        ent.append(dict(event=j + 1, delay=(E2M1 + 30) * 32 - 4, hold=a * 32, levels={"INT": 1}))
        ent.append(dict(event=None, delay=g * 32 - 10, hold=0, levels={"INT": 1}))
    return out, ent


def set_lat(pin, step, n=32):
    """(ii) the scan's phase fixed by a TMIC1 store; the pin's edge swept `step` ticks a window into
    a standing HALT."""
    out, ent = [], []
    for j in range(n):
        ops = (("st", 0xFF9D, 0x47), ("ev", j + 1), ("mark", 1), ("x", "halt", 1), ("mark", 2))
        out.append(window("l", j, ops, pre=(("ei",),), step=step))
        ent.append(dict(event=j + 1, delay=(E2M1 + 40) * 32 - 4 + step * j, hold=0 if pin == "INT" else 600,
                        levels={"INT": 1} if pin == "INT" else {"NMI": 0}))
    return out, ent


def set_k(n=32):
    """An INT pulse 4 clocks wide at the d series' clock, DI behind the sled, marks, EI, eight NOP:
    is the request DI stopped still there after EI."""
    out, ent = [], []
    for j in range(n):
        ops = (("ev", j + 1), ("mark", 1), ("dw0",), ("sl", j), ("di",), ("mark", 2), ("mark", 3), ("ei",), ("nop", 8))
        out.append(window("k", j, ops, pre=(("ei",),), odd=j & 1))
        ent.append(ent_int(j + 1, E2M1 + 44, hold=128))
    return out, ent


def set_z():
    """IE 0: an INT pulse of w clocks 20 clocks behind mark 1, two fillers, EI, eight NOP."""
    out, ent = [], []
    for j, w in enumerate((2, 4, 8, 16, 1000)):
        ops = (("ev", j + 1), ("mark", 1), ("fil", 2), ("mark", 2), ("ei",), ("nop", 8))
        out.append(window("z", j, ops, w=w * 32))
        ent.append(ent_int(j + 1, E2M1 + 20, hold=0 if w == 1000 else w * 32))
    return out, ent


def programs2():
    progs = []
    for lv in (0, 7):
        wins, ent = set_v(lv)
        progs.append(prog(f"f5_pb_v{lv}", wins, f"INT's edge swept across TM0's request at level {lv}",
                          entries=ent, intak=True))
    for src in "ic":
        for how in ("di", "pf"):
            wins, ent = set_d(src, how)
            progs.append(prog(f"f5_pb_d_{src}_{how}", wins, f"IE cleared by {how} inside the passage ({src})",
                              entries=ent, intak=True))
    progs.append(prog("f5_pb_f", set_f(), "FINT releasing a request blocked by the level in service"))
    for isp, rq in ((5, 5), (3, 7), (1, 1), (0, 7)):
        progs.append(prog(f"f5_pb_f_{isp}{rq}", set_f(isp, rq), f"FINT: level {isp} in service, the request at level {rq}"))
    wins, ent = set_k()
    progs.append(prog("f5_pb_k_i", wins, "an INT pulse of 4 clocks, then DI behind the sled, then EI", entries=ent, intak=True))
    wins, ent = set_z()
    progs.append(prog("f5_pb_z_i", wins, "an INT pulse with IE 0, EI 80 clocks later", entries=ent, intak=True))
    wins, ent = set_pw("INT", [32 * k for k in range(1, 25)])
    progs.append(prog("f5_pb_w_i", wins, "an INT pulse of 1 to 24 clocks", entries=ent, intak=True))
    wins, ent = set_pw("NMI", [4, 8, 12, 16, 20, 24, 28, 32, 40, 48, 64, 96, 128, 192, 256, 600])
    progs.append(prog("f5_pb_w_n", wins, "an NMI pulse of 4 to 600 ticks", entries=ent))
    wins, ent = set_gap()
    p = prog("f5_pb_g_i", wins, "INT raised, dropped and raised again", entries=ent, intak=True)
    progs.append(p)
    for pin in ("INT", "NMI"):
        for step, sfx in ((32, ""), (4, "t")):
            wins, ent = set_lat(pin, step)
            progs.append(prog(f"f5_pb_l_{pin[0].lower()}{sfx}", wins,
                              f"the {pin} edge into a standing HALT, {step} ticks a window, the scan's phase fixed",
                              entries=ent, intak=pin == "INT"))
    return {p.name: p for p in progs}


def rows2(name, backend, progs):
    """Per window: n, the take's source, the instruction not executed, the pushed PSW, the first
    activity and the vector read after mark 1, the edge and TOUT's count-out after mark 1, the first
    activity after the edge."""
    prog = progs[name]
    c = cl(prog)
    rec = ph.load(name, backend)
    ev = events(rec, prog)
    print(f"{name} [{backend}] {'PASS' if rec['passed'] else 'FAIL'} total {rec['total']} {len(ev)}/{len(prog.windows)} windows")
    for k in sorted(ev):
        e, m = ev[k], ev[k]["meta"]
        m1 = e["marks"].get(1)
        extra = " ".join(f"{x}={m[x]}" for x in ("w", "a", "g", "how", "src", "lv", "step") if x in m)
        if m1 is None:
            print(f"  n{m['n']:2d} {extra}: no mark 1")
            continue
        f = lambda t: "-" if t is None else ph.fmt((t - m1) / c)
        tk = e["take"]
        C = e["tout"][1] if len(e["tout"]) > 1 else None
        m2 = e["marks"].get(2)
        print(f"  n{m['n']:2d} {extra}: " + ("no take" if not tk else
              f"{tk[0]} in front of {lt(e['lab'])[:26]:26s} psw {e['psw'] if e['psw'] is None else format(e['psw'], '04X')} "
              f"first {f(tk[3])} V {f(tk[1])}")
              + f" | edge {f(e['edge'])} C {f(C)} m2 {f(m2)}"
              + (f" | first-edge {ph.fmt((tk[3] - e['edge']) / c)}" if tk and e["edge"] is not None else "")
              + (f" | takes {e['ntake']}" if e["ntake"] != 1 else ""))


# ------------------------------------------------------------------ reading
def events(rec, prog):
    """Per window: t0, T, marks {j: tick}, tout [tick of each P15 change], intak [tick of each
    /INTAK fall], edge (the scheduled edge's tick), take (source, the vector read's tick, pushed
    PC, the first acknowledge activity's tick: /INTAK's fall for INT), lab (the instruction the
    pushed PC names: its index from X, its text), wr {address: tick} of X's stores, meta."""
    wins, _ = oc.windows(rec, prog)
    inv = {v: k for k, v in VEC_RD.items()}
    ent = {e["event"]: e for e in (rec.get("stim") or {}).get("entries") or [] if e.get("event") is not None}
    out = {}
    for k, w in wins.items():
        m = prog.windows[k].meta
        e = dict(t0=w["t0"], T=w["T"], marks={}, tout=[], intak=[], edge=None, take=None, lab=None, wr={},
                 meta=m, rd=[], psw=None, ntake=0)
        pv = None
        rows = w["rows"]
        for i, (kind, r) in enumerate(rows):
            if kind == "pin":
                if pv is not None:
                    if (r[1] ^ pv) & P15:
                        e["tout"].append(r[0])
                    if pv & P13 and not r[1] & P13:
                        e["intak"].append(r[0])
                else:
                    e["tout"].append(r[0]) if not r[1] & P15 else None
                    if not r[1] & P13:
                        e["intak"].append(r[0])
                pv = r[1]
            elif kind == "mw" and MARK <= r[1] < MARK + 32:
                e["marks"].setdefault((r[1] - MARK) // 2, r[0])
            elif kind == "mw" and MARK + 32 <= r[1] < 0xE00:
                e["wr"].setdefault(r[1], r[0])
            elif kind == "mr" and r[1] in inv and e["take"] is not None:
                e["ntake"] += 1
            elif kind == "mr" and r[1] in inv and e["take"] is None:
                e["ntake"] += 1
                pushes = [x for kd, x in rows[i + 1:i + 8] if kd == "mw"][:3]
                pc = pushes[2][2] if len(pushes) > 2 else None
                src = inv[r[1]]
                first = r[0]
                if src == "int":
                    first = max([x for x in e["intak"] if x < r[0]][-2:-1] or [r[0]])
                e["take"] = (src, r[0], pc, first)
                e["psw"] = pushes[0][2] if pushes else None
            elif kind == "mr" and 0xE00 <= r[1] < STACK_TOP:
                e["rd"].append((r[1], r[0]))
            elif r[3] & 0x100 and r[2] & 0xFF in ent and e["edge"] is None:
                e["edge"] = r[4] + ent[r[2] & 0xFF]["delay"] + 4
        if e["take"] and e["take"][2] is not None:
            e["lab"] = label(m, e["take"][2])
        out[k] = e
    return out


def label(m, pc):
    ins = m["ins"]
    x0 = m.get("x", [None])[0]
    i0 = next((i for i, (o, _) in enumerate(ins) if o == x0), None)
    for i, (o, text) in enumerate(ins):
        if o == pc:
            return (None if i0 is None else i - i0, text)
    return (None, f"pc {pc:04X}")


def cl(prog):
    return 4 * getattr(prog, "clk", 8)


def fc(t, c):
    return ph.fmt(t / c)


def twin(name, backend, progs, sfx):
    """The twin's events (None if there is no receipt)."""
    base = name[:-2] if name.endswith("_h") else name
    tn = base + sfx
    if tn not in progs or not ph.receipt_path(tn, backend).exists():
        return None
    return events(ph.load(tn, backend), progs[tn])


def table(name, backend, progs):
    """Per window a dict of clocks: s, lab, V (the vector read less mark 1), F (the first
    acknowledge activity less mark 1), M2 / M3 (the twin's marks less its mark 1), W (the twin's
    first X store less mark 1), E (the edge less mark 1), C (TOUT's count-out less mark 1), ..."""
    prog = progs[name]
    c = cl(prog)
    ev = events(ph.load(name, backend), prog)
    tw = twin(name, backend, progs, "_r") or {}
    rows = []
    for k in sorted(ev):
        e, m = ev[k], ev[k]["meta"]
        m1 = e["marks"].get(1)
        r = dict(k=k, s=m["n"], lab=e["lab"], m=m, e=e)
        if m1 is None:
            rows.append(r)
            continue
        if e["take"]:
            r["src"], r["V"], r["F"] = e["take"][0], (e["take"][1] - m1) / c, (e["take"][3] - m1) / c
        if e["edge"] is not None:
            r["E"] = (e["edge"] - m1) / c
        if len(e["tout"]) > 1:
            r["C"] = (e["tout"][1] - m1) / c
        if e["tout"]:
            r["S"] = (e["tout"][0] - m1) / c
        t = tw.get(k)
        if t and 1 in t["marks"]:
            for j in (2, 3):
                if j in t["marks"]:
                    r[f"M{j}"] = (t["marks"][j] - t["marks"][1]) / c
            if t["wr"]:
                r["W"] = (min(t["wr"].values()) - t["marks"][1]) / c
        for j in (2, 3):
            if j in e["marks"]:
                r[f"m{j}"] = (e["marks"][j] - m1) / c
        rows.append(r)
    return rows


def g(r, key, c=None):
    v = r.get(key)
    return "-" if v is None else ph.fmt(v)


def summary(name, backend, progs, verbose=False):
    prog = progs[name]
    rec = ph.load(name, backend)
    ok = rec["program_sha256"] == hashlib.sha256(prog.build()["text"]).hexdigest()
    rows = table(name, backend, progs)
    print(f"{name} [{backend}] {'PASS' if rec['passed'] else 'FAIL'} total {rec['total']} "
          f"{len(rows)}/{len(prog.windows)} windows" + ("" if ok else "  (THE RECEIPT IS OF ANOTHER VERSION)"))
    series = prog.windows[0].meta["series"]
    if series in ("c", "n", "i"):
        ref = "E" if series != "c" else None
        if verbose:
            print("   s | take at (instructions from X: text) | V-m1 | first-m1 | twin M2 M3 W | "
                  + ("edge-m1 | M2-edge" if ref else "C-m1 start-m1") + " | V-M2 V-M3 | own m2")
            for r in rows:
                lab = r["lab"]
                tail = (f"{g(r, 'E')} | {ph.fmt(r['M2'] - r['E']) if 'M2' in r and 'E' in r else '-'}" if ref
                        else f"{g(r, 'C')} {g(r, 'S')}")
                d2 = ph.fmt(r["V"] - r["M2"]) if "V" in r and "M2" in r else "-"
                d3 = ph.fmt(r["V"] - r["M3"]) if "V" in r and "M3" in r else "-"
                print(f"  {r['s']:2d} | {lt(lab):34s} | {g(r, 'V'):>6s} | "
                      f"{g(r, 'F'):>6s} | {g(r, 'M2')} {g(r, 'M3')} {g(r, 'W')} | {tail} | {d2} {d3} | {g(r, 'm2')}")
        # by the boundary taken: the sled lengths, the vector read against the twin's mark behind it
        by = collections.OrderedDict()
        for r in rows:
            by.setdefault(r["lab"], []).append(r)
        for lab, rs in by.items():
            ss = [r["s"] for r in rs]
            line = f"  taken in front of {lt(lab):30s} s {rng(ss)}"
            if lab and "V" in rs[0]:
                if "M2" in rs[0]:
                    line += " | V-M2 " + vals(r["V"] - r["M2"] for r in rs if "M2" in r)
                    line += " | F-M2 " + vals(r["F"] - r["M2"] for r in rs if "M2" in r)
                    line += " | M2-m1 " + span(r["M2"] for r in rs if "M2" in r)
                if ref:
                    line += " | V-edge " + span(r["V"] - r["E"] for r in rs if "E" in r)
                    if "M2" in rs[0]:
                        line += " | M2-edge " + span(r["M2"] - r["E"] for r in rs if "M2" in r and "E" in r)
                else:
                    line += " | V-m1 " + span(r["V"] for r in rs)
                    line += " | C-m1 " + span(r["C"] for r in rs if "C" in r)
            print(line)
    elif series == "q":
        by = collections.OrderedDict()
        for r in rows:
            e, m = r["e"], r["m"]
            n = None if not r["lab"] else r["lab"][0] if r["lab"][0] is not None else r["lab"][1]
            if e["take"] and e["take"][2] is not None:
                n = e["take"][2] - m["first"]
            # the PSW word's read: the last stack read in front of the take
            rd = [t for a, t in e["rd"] if e["take"] and t < e["take"][1]]
            m1 = e["marks"].get(1)
            c = cl(prog)
            key = (r.get("src"), g(r, "V"), n, ph.fmt((e["take"][1] - rd[-1]) / c) if rd and e["take"] else "-",
                   ph.fmt((rd[-1] - m1) / c) if rd and m1 else "-")
            by.setdefault(key, []).append(r["s"])
        print("  source : vector read less mark 1 / INCs run / less the last stack read (the PSW word's) "
              "/ that read less mark 1 : the sled lengths")
        for key, ss in sorted(by.items(), key=lambda kv: -len(kv[1])):
            print(f"    {key[0]}: {key[1]} / n{key[2]} / {key[3]} / {key[4]} : x {' '.join(map(str, ss))}")
    elif series == "e":
        print("  kind s : take in front of (instructions from the first X) | first /INTAK less mark 1 | vector "
              "read less mark 1 | less the last stack read | own marks 2")
        for r in rows:
            e, m, c = r["e"], r["m"], cl(prog)
            rd = [t for a, t in e["rd"] if e["take"] and t < e["take"][3]]
            print(f"    {m['kind']:5s} {r['s']} : {lt(r['lab']):28s} | "
                  f"{g(r, 'F'):>6s} | {g(r, 'V'):>6s} | "
                  f"{ph.fmt((e['take'][3] - rd[-1]) / c) if rd else '-':>6s} | {g(r, 'm2')} | wr "
                  + " ".join(ph.fmt((t - e['marks'][1]) / c) for a, t in sorted(e["wr"].items()) if 1 in e["marks"]))


def lt(lab):
    if not lab:
        return "no take"
    return (f"X{lab[0]:+d} " if lab[0] is not None else "") + lab[1]


def rng(ss):
    out, i = [], 0
    ss = sorted(ss)
    while i < len(ss):
        j = i
        while j + 1 < len(ss) and ss[j + 1] == ss[j] + 1:
            j += 1
        out.append(str(ss[i]) if i == j else f"{ss[i]}..{ss[j]}")
        i = j + 1
    return ",".join(out)


def vals(it):
    cn = collections.Counter(round(v * 2) / 2 for v in it)
    return " ".join(f"{ph.fmt(v)}x{n}" for v, n in sorted(cn.items())) or "-"


def span(it):
    v = list(it)
    return "-" if not v else ph.fmt(min(v)) if max(v) - min(v) < 0.01 else f"{ph.fmt(min(v))}..{ph.fmt(max(v))}"


def takes(name, ref, cand, progs):
    """Socket against a simulation by what a window's take is: the boundary (pushed PC) and the
    vector read's clock after mark 1."""
    a, b = table(name, ref, progs), table(name, cand, progs)
    same = pc = 0
    diff = []
    for x, y in zip(a, b):
        p = x["lab"] == y["lab"]
        v = p and abs(x.get("V", 0) - y.get("V", 0)) < 0.6
        pc += p
        same += v
        if not v:
            diff.append(f"s{x['s']}:{'-' if not x['lab'] else x['lab'][0]}@{g(x, 'V')}/"
                        f"{'-' if not y['lab'] else y['lab'][0]}@{g(y, 'V')}")
    print(f"{name}: {ref} / {cand}: boundary equal {pc} of {len(a)}, boundary and clock {same}"
          + ("" if not diff else " | " + " ".join(diff[:40])))
    return same == len(a)


def cut(name, backend, progs):
    """Per boundary taken in the sweep (named by the instruction not executed): the shortest sled
    that takes there and the earliest first acknowledge activity and vector read, in clocks after
    the pin's edge (n, i) or after mark 1 (c: also mod 16, the scan's round)."""
    rows = table(name, backend, progs)
    ser = progs[name].windows[0].meta["series"]
    by = collections.OrderedDict()
    for r in rows:
        if "V" in r:
            ref = r.get("E", 0.0)
            by.setdefault(lt(r["lab"]), []).append((r["F"] - ref, r["V"] - ref, r["s"]))
    cells = []
    for lab, v in by.items():
        f, V, _ = min(v)
        s0 = min(x[2] for x in v)
        if len(v) == len(rows) or s0 == 0:          # no threshold inside the sweep
            continue
        cells.append(f"{lab[:26]}: s>={s0} first {ph.fmt(f)} V {ph.fmt(V)}"
                     + (f" (mod 16: {ph.fmt(V % 16)})" if ser == "c" else ""))
    print(f"{name[6:]:12s} [{backend}] " + " | ".join(cells))


def hold(name, backend, progs, lo=-16):
    """Per window: the bus cycles in front of the take against the twin's (the same program with
    nothing taken), in clocks from b* = the earliest first activity in the program less 15 (less 4
    for /INTAK): '=' the same up to two clocks in front of the boundary taken, '#' not (the
    twin's line follows); '+' a cycle of the stream starts from there on (silicon: 0 to 3 windows a program)."""
    prog = progs[name]
    c = cl(prog)
    rec = ph.load(name, backend)
    w, _ = oc.windows(rec, prog)
    ev = events(rec, prog)
    tn = name + "_r"
    trec = ph.load(tn, backend)
    tw, _ = oc.windows(trec, progs[tn])
    tev = events(trec, progs[tn])
    firsts = [(e["take"][3] - e["marks"][1]) / c for e in ev.values() if e["take"] and 1 in e["marks"]]
    intp = any(e["take"] and e["take"][0] == "int" for e in ev.values())
    back = 4 if intp else 15
    bs = min(firsts) - back
    print(f"{name} [{backend}]: b* = {ph.fmt(bs)} clocks after mark 1 (the earliest first activity {ph.fmt(min(firsts))})")
    for k in sorted(ev):
        e, t = ev[k], tev.get(k)
        if not e["take"] or t is None or 1 not in t["marks"]:
            continue
        m1, tm1 = e["marks"][1], t["marks"][1]
        V = (e["take"][3] - m1) / c - bs
        A = [(kind[0] + f"{r[1] & 0xFFF:03X}", round((r[0] - m1) / c - bs)) for kind, r in w[k]["rows"] if kind != "pin"]
        B = [(kind[0] + f"{r[1] & 0xFFF:03X}", round((r[0] - tm1) / c - bs)) for kind, r in tw[k]["rows"] if kind != "pin"]
        A = [x for x in A if lo <= x[1] < V]
        B = [x for x in B if lo <= x[1] < V + 4]
        cutb = V - back - 2
        same = [x for x in A if x[1] < cutb] == [x for x in B if x[1] < cutb]
        late = any(x[1] >= cutb for x in A)         # a cycle started from the boundary - 2 on
        f = lambda L: " ".join(f"{n}@{t:+d}" for n, t in L)
        print(f"  s{k:2d} boundary {V - back:+3.0f} ({lt(e['lab'])[:20]:20s}) {'=' if same else '#'}{'+' if late else ' '} {f(A)}")
        if not same:
            print(f"  {'':40s} twin: {f(B)}")


# ------------------------------------------------------------------ the third set (f5_pc_*)
# Q1: what the controller's clocks behind a slot are; Q2: where an instruction samples the request.
WS_SEG = 0x4000
ON = oc.ON
# x: per kind (INT back, NMI back): the sweep starts that many clocks in front of the twin's mark 2
# write (the pilot f5_pc_t: PC_M2, ticks from the event's record to that write) and runs 16 clocks
X_KINDS = ("inc", "nop", "cbw", "xch", "mul", "push", "wr", "ws", "ws1", "ws2", "out", "out2", "br", "jwr",
           "div", "shcl", "rd", "sfr")
X_BACK = {"br": (24, 28)}
PC_M2 = {'inc': 2400, 'nop': 2464, 'cbw': 2432, 'xch': 2464, 'mul': 3392, 'push': 2624, 'wr': 2688, 'ws': 2688, 'ws1': 2720,
         'ws2': 2752, 'out': 2752, 'out2': 2784, 'br': 3040, 'jwr': 3424, 'div': 3648, 'shcl': 3488, 'rd': 2752, 'sfr': 2688}      # the socket's pilot (f5_pc_t)
PC_STEP = 16


class Program3(la.Program):
    """lattice.Program with the page at 40000h mapped (the block-2 store's target)."""

    def build(self):
        if self._built:
            return self._built
        b = super().build()
        b["segments"].setdefault(WS_SEG << 4, bytes(0x1000))
        return b


def prog3(name, wins, note, entries=None, intak=False):
    p = Program3(name, wins, note, init=init, fini=oc.ports_off, pins=["P13", "P15"], entries=entries)
    if intak:
        p.stim["intak_vector"] = INT_VEC
        p.stim["int_release"] = True
    p.clk = 8
    return p


def x_ops(kind, ev):
    ds = kind.startswith("ws")
    return (((("ds1", WS_SEG),) if ds else ()) + (("ev", ev), ("mark", 1), ("dw0",), ("sl", 16)) + train(kind)
            + ((("ds1", ON),) if ds else ()))


def set_x(pin, kind, n=32):
    """The event, mark 1, a sled of 16, X, mark 2, mark 3, an INC train: the pin's edge swept half a
    clock a window across X's boundaries; the last window is the twin (no edge)."""
    out, ent = [], []
    back = X_BACK.get(kind, (28, 32))[pin == "NMI"]
    for j in range(n + 1):
        out.append(window("x", j, x_ops(kind, j + 1), pre=(("ei",),), kind=kind, twin=j == n, **KW.get(kind, {})))
        if j < n:
            d = PC_M2.get(kind, 84 * 32) - back * 32 + PC_STEP * j - 4
            ent.append(dict(event=j + 1, delay=d, hold=600, levels={"NMI": 0}) if pin == "NMI" else
                       dict(event=j + 1, delay=d, hold=0, levels={"INT": 1}))
    return out, ent


def set_t():
    """The pilot: the twins of every x kind (no edge)."""
    return [window("x", j, x_ops(kind, j + 1), pre=(("ei",),), kind=kind, twin=True, **KW.get(kind, {}))
            for j, kind in enumerate(X_KINDS)]


H_BASE = 162


def set_h(lt, lp, n=32):
    """TM0's request at level lt in the round a TMIC1 store started (f5_pb_v's frame), an INC train;
    INTP0's falling edge (level lp) swept a clock a window across TM0's slot and its clocks."""
    out, ent = [], []
    for j in range(n):
        ops = (("ei",), ("ev", j + 1), START, ("mark", 0), ("fil", 2), ("mark", 1), ("st", 0xFF9D, 0x47),
               ("dw0",), ("x", "inc", 60))
        out.append(window("h", j, ops, md0=23, hand={"tm0": H_STOP}, ic={"tm0": lt, "p0": lp}, lv=lt, lp=lp))
        ent.append(dict(event=j + 1, delay=(H_BASE + j) * 32 - 4, hold=600, levels={"INTP0": 0}))
    return out, ent


def set_m(val, lv=0, n=36):
    """TM0's request (level lv) found in its slot (f5_pa_c_wr's frame, the count 25); behind the sled
    a store of `val` to TMIC0 (the mask set, the flag cleared, or the request as it stands), two
    marks, an INC train."""
    out = []
    for s in range(n):
        ops = (("ei",), START, ("mark", 0), ("fil", 2), ("mark", 1), ("st", 0xFF9D, 0x47), ("dw0",), ("sl", s),
               ("st", 0xFF9C, val), ("mark", 2), ("mark", 3), ("inc", 12))
        out.append(window("m", s, ops, odd=s & 1, md0=25, hand={"tm0": H_STOP}, ic={"tm0": lv}, lv=lv, val=val))
    return out


S_GROUPS = (("a", (0xFF9D, 0x47), False), ("b", (0xFF9D, 0x47), True), ("c", (0xFF4C, 0x85), False),
            ("d", (0xFF4C, 0xC5), False))


def set_s(lv=2, lo=8, hi=32):
    """f5_pa_c_inc at level 2, by group: a plain; b level 5 in service (INTP0's request taken in the
    setup, its handler RETI alone); c the restart store sets INTP0's request at level 5 (a second
    level pending); d the same masked."""
    out = []
    for g, rst, isp in S_GROUPS:
        for s in range(lo, hi):
            ops = ((("ei",), START, ("mark", 0), ("fil", 2), ("mark", 1), ("st",) + rst, ("dw0",), ("sl", s))
                   + train("inc") + ((("fint",),) if isp else ()))
            pre = (("ei",), ("st", 0xFF4C, 0x85), ("nop", 12)) if isp else ()
            out.append(window("s", s, ops, pre=pre, odd=s & 1, md0=23,
                              hand={"tm0": H_STOP, **({"p0": H_RETI} if isp else {})}, ic={"tm0": lv}, lv=lv, g=g))
    return out


def set_o(n=18):
    """IE 0: TMIC0's IF stored 1 at level 0 (a slot every 18 clocks; nothing can be taken), a sled of
    x clocks, mark 1, 60 INC AW (a fetch chain); the second half the same with the request masked:
    does the controller's bus hold come with every slot or only with a request on its way."""
    return [window("o", x, (("st", 0xFF9C, v), ("sled", x), ("mark", 1), ("inc", 60)), odd=x & 1, val=v)
            for v in (0x80, 0xC0) for x in range(n)]


def pc_o(name, backend, progs):
    """Per sled length: the fetches of the INC train (clocks after mark 1) where the pending half
    differs from the masked half."""
    prog = progs[name]
    wins, _ = oc.windows(ph.load(name, backend), prog)
    n = len(prog.windows) // 2
    print(f"{name} [{backend}]")
    for x in range(n):
        f = []
        for k in (x, x + n):
            rows = wins[k]["rows"]
            m1 = next(r[0] for kind, r in rows if kind == "mw" and r[1] == MARK + 2)
            f.append([(r[0] - m1) // 32 for kind, r in rows if kind == "fetch" and r[0] > m1])
        d = [(a, b) for a, b in zip(*f) if a != b]
        print(f"  x{x:2d}: {len(f[0])} / {len(f[1])} fetches; " + ("equal" if not d and len(f[0]) == len(f[1]) else
              "pending/masked " + " ".join(f"{a}/{b}" for a, b in d[:12])) + f" | end {(wins[x]['T'] - wins[x + n]['T']) / 32:+.0f}")


def programs3():
    progs = [prog3("f5_pc_t", set_t(), "the pilot: the twin of every x kind")]
    for pin in ("INT", "NMI"):
        for kind in X_KINDS:
            wins, ent = set_x(pin, kind)
            progs.append(prog3(f"f5_pc_{pin[0].lower()}_{kind}", wins,
                               f"the {pin} edge swept half a clock a window across {kind}'s boundaries",
                               entries=ent, intak=pin == "INT"))
    for kind in ("out", "out2"):
        progs.append(prog3(f"f5_pc_c_{kind}", set_c(kind), f"TM0's request against {kind}'s boundary, the sled swept"))
        progs.append(prog3(f"f5_pc_c_{kind}_r", set_c(kind, masked=True), "the twin: the request masked"))
    for lt_, lp in ((7, 0), (0, 7), (7, 3)):
        wins, ent = set_h(lt_, lp)
        progs.append(prog3(f"f5_pc_h{lt_}{lp}", wins, f"TM0's request at level {lt_} in its slot, INTP0's edge "
                           f"(level {lp}) swept across it", entries=ent))
    for name, val in (("mk", 0xC0), ("if", 0x00), ("id", 0x80), ("pr", 0x87)):
        progs.append(prog3(f"f5_pc_m_{name}", set_m(val), f"a store of {val:02X}h to TMIC0 swept across its request's clocks"))
    progs.append(prog3("f5_pc_o", set_o(), "IE 0, a request pending or masked: the fetch chain of an INC train"))
    progs.append(prog3("f5_pc_s", set_s(), "TM0 at level 2: plain, level 5 in service, a second level pending, the same masked"))
    return {p.name: p for p in progs}


def events3(rec, prog):
    """events() with, per window: takes [(source, the vector read's tick, pushed PC, the first
    acknowledge activity's tick)], dw [(kind, address, start, end)] of the data writes behind mark 1
    (the marks and the pushes of a take left out)."""
    ev = events(rec, prog)
    wins, _ = oc.windows(rec, prog)
    inv = {v: k for k, v in VEC_RD.items()}
    for k, e in ev.items():
        rows = wins[k]["rows"]
        m1 = e["marks"].get(1, 0)
        takes, dw, skip = [], [], set()
        for i, (kind, r) in enumerate(rows):
            if kind == "mr" and r[1] in inv:
                ps = [(j, x) for j, (kd, x) in enumerate(rows[i + 1:i + 8], i + 1) if kd == "mw"][:3]
                skip.update(j for j, _ in ps)
                first = r[0]
                if inv[r[1]] == "int":
                    first = max([x for x in e["intak"] if x < r[0]][-2:-1] or [r[0]])
                takes.append((inv[r[1]], r[0], ps[2][1][2] if len(ps) > 2 else None, first))
        for i, (kind, r) in enumerate(rows):
            if kind in ("mw", "iow") and r[0] > m1 and i not in skip and not MARK <= r[1] < MARK + 32 \
                    and not r[3] & 0x100:
                dw.append((kind, r[1], r[0], r[4]))
        e["takes"], e["dw"] = takes, dw
    return ev


def pilot(backend, progs):
    """PC_M2 from the pilot's receipt: per kind the ticks from the event's record to mark 2's write."""
    prog = progs["f5_pc_t"]
    rec = ph.load("f5_pc_t", backend)
    wins, _ = oc.windows(rec, prog)
    out = {}
    for k, w in wins.items():
        evr = next(r for kind, r in w["rows"] if r[3] & 0x100)
        m2 = next(r for kind, r in w["rows"] if kind == "mw" and r[1] == MARK + 4)
        out[prog.windows[k].meta["kind"]] = m2[0] - evr[4]
    print("PC_M2 =", out)
    print("  clocks:", {k: v / 32 for k, v in out.items()})


def q(t):
    return ph.fmt(t / 32)


def pc_x(name, backend, progs, brief=False):
    """An x program (brief: one line, per boundary the latest edge against M2 and We and the first
    activity less it): the twin's X write (start, end) and mark 2 write after mark 1; per boundary
    taken (the instruction not executed): the edges that take there (after mark 1), the latest
    against the twin's mark 2 write (M2) and against X's write's end (We), the first acknowledge
    activity and the vector read less that edge, the vector read less M2; '!': the bus cycles in
    front of the take are not where the twin has them."""
    prog = progs[name]
    rec = ph.load(name, backend)
    ev = events3(rec, prog)
    wins, _ = oc.windows(rec, prog)
    tk = max(ev)
    tw = ev[tk]
    tm1 = tw["marks"][1]
    M2 = tw["marks"][2] - tm1
    xw = [d for d in tw["dw"] if d[2] - tm1 < M2]
    We = xw[-1][3] - tm1 if xw else None
    tf = [(kind, r[0] - tm1) for kind, r in wins[tk]["rows"] if kind != "pin" and r[0] > tm1]
    if not brief:
        print(f"{name[6:]:10s} [{backend}] twin: X write " + (f"{q(xw[-1][2] - tm1)}..{q(We)}" if xw else "-")
              + f", M2 {q(M2)}, M3 {q(tw['marks'][3] - tm1)} after mark 1" + ("; the twin takes!" if tw["takes"] else ""))
    by = collections.OrderedDict()
    for k in sorted(ev):
        e = ev[k]
        if k == tk or e["edge"] is None:
            continue
        m1 = e["marks"][1]
        t = e["takes"][0] if e["takes"] else None
        lab = lt(label(e["meta"], t[2])) if t and t[2] is not None else "no take"
        own = [(kind, r[0] - m1) for kind, r in wins[k]["rows"] if kind != "pin" and r[0] > m1
               and (t is None or r[0] < t[3] - 6 * 32)]
        dis = own != tf[:len(own)]
        by.setdefault(lab, []).append((e["edge"] - m1, None if not t else t[3] - e["edge"],
                                       None if not t else t[1] - e["edge"], None if not t else t[1] - m1, dis,
                                       len(e["takes"])))
    if brief:
        last = max(x[0] for v in by.values() for x in v)
        cells = [f"{lab.split(' ')[0] if lab[0] == 'X' else lab[:8]}: M2{q(max(v)[0] - M2)}"
                 + (f" We{q(max(v)[0] - We)}" if We is not None else "")
                 + (f" F{q(max(v)[1])}" if max(v)[1] is not None else "")
                 + ("" if max(v)[0] < last else " (the sweep's end)") for lab, v in by.items()]
        print(f"{name[6:]:10s} [{backend:11s}] X write " + (f"{q(xw[-1][2] - tm1)}..{q(We)}" if xw else "-")
              + f" M2 {q(M2)} | " + " | ".join(cells))
        return
    for lab, v in by.items():
        E, F, V, Vm, dis, nt = max(v)
        line = (f"    {lab[:30]:30s} edges {q(min(v)[0])}..{q(E)} ({len(v)}) | latest: M2{q(E - M2)}"
                + (f" We{q(E - We):>6s}" if We is not None else ""))
        if F is not None:
            line += f" | first-edge {q(F)} V-edge {q(V)} V-M2 {q(Vm - M2)}"
        nd = sum(1 for x in v if x[4])
        print(line + (f" | ! {nd} differ from the twin" if nd else "") + (" | takes " + str(sorted({x[5] for x in v}))))


def pc_rows(name, backend, progs):
    """Per window: the sweep's value, the takes (source@vector read less mark 1: the instruction not
    executed), the edge, TOUT's count-out and the window's own marks 2 and 3 less mark 1."""
    prog = progs[name]
    ev = events3(ph.load(name, backend), prog)
    print(f"{name} [{backend}]")
    for k in sorted(ev):
        e, m = ev[k], ev[k]["meta"]
        m1 = e["marks"].get(1)
        if m1 is None:
            print(f"  n{m['n']}: no mark 1")
            continue
        f = lambda t: "-" if t is None else q(t - m1)
        tk = " ".join(f"{s}@{f(v)}:{lt(label(m, pc))[:22] if pc is not None else '?'}" for s, v, pc, _ in e["takes"][:3])
        print(f"  {m.get('g', '')}n{m['n']:2d} | {tk or 'no take':60s} | edge {f(e['edge'])} C {f(e['tout'][1] if len(e['tout']) > 1 else None)}"
              f" m2 {f(e['marks'].get(2))} m3 {f(e['marks'].get(3))}")



# ------------------------------------------------------------------ the fourth set (f5_pd_*)
# Where the look is for a store to a register on the timer unit's six-clock grid (its on-chip cycle
# ends on a free-running grid: 0 to 5 clocks of wait by the store's phase), and what a DMA end is as
# a source. Every window starts with a store to TMC1 (`SYNC`: its cycle ends on the grid, so the
# window's phase on the grid is the sled's length alone, in every program).
SYNC = ("st", 0xFF91, 0x00)
P_KINDS = ("sfr", "wi", "tmc", "tmc0", "md", "md0", "mdw", "dmam", "dmac", "dblk")       # the pilot's
P_NP = 12
G_KINDS = (("sfr", range(6)), ("tmc", range(6)), ("md", range(6)), ("wi", (0, 3)), ("dmam", (0, 3)))
PD_BACK = (32, 36)                  # INT, NMI: the sweep's start in clocks in front of the twin's mark 2
PD_M2 = {'sfr:0': 2688, 'sfr:1': 2720, 'sfr:2': 2752, 'sfr:3': 2784, 'sfr:4': 2816, 'sfr:5': 2848, 'wi:0': 2688,
         'wi:1': 2720, 'wi:2': 2752, 'wi:3': 2784, 'wi:4': 2816, 'wi:5': 2848, 'tmc:0': 2784, 'tmc:1': 2784, 'tmc:2':
         2784, 'tmc:3': 2976, 'tmc:4': 2976, 'tmc:5': 2976, 'md:0': 2784, 'md:1': 2784, 'md:2': 2784, 'md:3': 2976,
         'md:4': 2976, 'md:5': 2976, 'dmam:0': 2688, 'dmam:1': 2720, 'dmam:2': 2752, 'dmam:3': 2784, 'dmam:4': 2816,
         'dmam:5': 2848}      # the socket's pilot (f5_pd_t): kind:phase -> ticks from the event to mark 2
DMA_PAGE = 0x40                     # SARH / DARH: the page 40000h (Program3 maps it)
D_PRE = (("stw", 0xFE00, 0x0100), ("stw", 0xFE02, 0x0200), ("st", 0xFE05, DMA_PAGE), ("st", 0xFE04, DMA_PAGE),
         ("stw", 0xFE06, 2), ("st", 0xFFA0, 0x11))
D_END = (("st", 0xFFA1, 0x00), ("st", 0xFFAC, 0x47))
D_KINDS = ("wi", "wi2", "tmc")       # wi2: every cycle of block 0 at two waits, as f4_dma runs
KINDS["wi2"] = KINDS["wi"]
KW["wi2"] = dict(wt=2)


def x4_ops(kind, ev, p):
    return (SYNC, ("ev", ev), ("mark", 1), ("dw0",), ("sl", 16 + p)) + train(kind)


def set_t4():
    """The pilot: the twin (no edge) of every kind at twelve sled lengths (two turns of the grid)."""
    return [window("x", j, x4_ops(kind, j + 1, p), pre=(("ei",),), odd=p & 1, kind=kind, p=p, twin=True)
            for j, (kind, p) in enumerate((k, p) for k in P_KINDS for p in range(P_NP))]


def set_x4(pin, kind, p, n=32):
    """set_x behind the grid's synchronising store with the sled 16 + p: the edge half a clock a
    window over 16 clocks from PD_BACK clocks in front of the twin's mark 2; the last is the twin."""
    out, ent = [], []
    back = PD_BACK[pin == "NMI"]
    for j in range(n + 1):
        out.append(window("x", j, x4_ops(kind, j + 1, p), pre=(("ei",),), odd=p & 1, kind=kind, p=p, twin=j == n))
        if j < n:
            d = PD_M2.get(f"{kind}:{p}", 90 * 32) - back * 32 + PC_STEP * j - 4
            ent.append(dict(event=j + 1, delay=d, hold=600, levels={"NMI": 0}) if pin == "NMI" else
                       dict(event=j + 1, delay=d, hold=0, levels={"INT": 1}))
    return out, ent


def set_c4(kind, masked=False, ns=NS):
    """set_c (TM0's count-out into its slot, the sled swept) behind the synchronising store."""
    out = []
    for s in range(ns):
        ops = ((SYNC, ("ei",), START, ("mark", 0), ("fil", 2), ("mark", 1), ("st", 0xFF9D, 0x47), ("dw0",),
                ("sl", s)) + train(kind))
        out.append(window("c", s, ops, odd=s & 1, md0=C_MD[kind], hand={"tm0": H_STOP},
                          ic={"tm0": 0x40 if masked else 0}, kind=kind, lv=0))
    return out


def set_dd(kind, lv=0, masked=False, ns=32):
    """A DMA end as the source, in f4_dma dic's frame: DIC0's store at level lv (the scan's restart),
    the sled, mark 1, the DMAM0 store (TDMA: channel 0, a burst of two bytes inside the page 40000h),
    X twice (dic's cw 0 and cw 1), mark 2, mark 3, an INC train. The sled moves the scan's slots
    against the transfer, a clock a window over two rounds."""
    out = []
    for s in range(ns):
        ops = ((SYNC, ("ei",), ("st", 0xFFAC, (0x40 if masked else 0) | lv), ("sl", s), ("mark", 1),
                ("st", 0xFFA1, 0x8C), ("x", kind, 2), ("mark", 2), ("mark", 3), ("inc", 16)) + D_END)
        out.append(window("d", s, ops, pre=D_PRE, odd=s & 1, kind=kind, lv=lv, **KW.get(kind, {})))
    return out


PE_BACK = (36, 40)                  # INT, NMI
PE_M2 = {'wi': 4096, 'wi2': 5344}      # the socket's pilot (f5_pd_u): kind -> ticks from the event to mark 2


def e4_ops(kind, ev):
    return ((SYNC, ("ei",), ("st", 0xFFAC, 0x40), ("ev", ev), ("sl", 0), ("mark", 1), ("st", 0xFFA1, 0x8C), ("x", kind, 2),
             ("mark", 2), ("mark", 3), ("inc", 16)) + D_END)


def set_e4(pin, kind, n=32):
    """The d series' twin (DIC0 masked: the burst runs, nothing is requested) with a pin's edge swept
    half a clock a window across the second X's end: where the store behind the burst looks, in the
    bus conditions of f4_dma dic (wi2) and with no wait (wi). The last window is the twin."""
    out, ent = [], []
    back = PE_BACK[pin == "NMI"]
    for j in range(n + 1):
        out.append(window("e4", j, e4_ops(kind, j + 1), pre=D_PRE, kind=kind, twin=j == n, **KW.get(kind, {})))
        if j < n:
            d = PE_M2.get(kind, 110 * 32) - back * 32 + PC_STEP * j - 4
            ent.append(dict(event=j + 1, delay=d, hold=600, levels={"NMI": 0}) if pin == "NMI" else
                       dict(event=j + 1, delay=d, hold=0, levels={"INT": 1}))
    return out, ent


def pilot_e(backend, progs):
    """PE_M2 from the pilot's receipt (f5_pd_u)."""
    prog = progs["f5_pd_u"]
    wins, _ = oc.windows(ph.load("f5_pd_u", backend), prog)
    out = {}
    for k, w in sorted(wins.items()):
        evr = next(r for kind, r in w["rows"] if r[3] & 0x100)
        m1 = next(r for kind, r in w["rows"] if kind == "mw" and r[1] == MARK + 2)
        m2 = next(r for kind, r in w["rows"] if kind == "mw" and r[1] == MARK + 4)
        out[prog.windows[k].meta["kind"]] = m2[0] - evr[4]
        print(f"  {prog.windows[k].meta['kind']}: mark 1 {q(m1[0] - evr[4])} after the event, mark 2 {q(m2[0] - m1[0])} after mark 1")
    print("PE_M2 =", out)


def set_dl(lv, n=32):
    """The DMA end against the scan: the sled between DIC0's store (the restart) and the DMAM0 store
    swept a clock a window, an INC train behind it."""
    return [window("dl", r, (SYNC, ("ei",), ("st", 0xFFAC, lv), ("sl", r), ("mark", 1), ("st", 0xFFA1, 0x8C),
                             ("inc", 60)) + D_END, pre=D_PRE, odd=r & 1, lv=lv) for r in range(n)]


def programs4():
    progs = [prog3("f5_pd_t", set_t4(), "the pilot: the twin of every kind at twelve phases of the grid")]
    for pin in ("INT", "NMI"):
        for kind, phases in G_KINDS:
            for p in phases:
                wins, ent = set_x4(pin, kind, p)
                progs.append(prog3(f"f5_pd_{pin[0].lower()}_{kind}_p{p}", wins,
                                   f"the {pin} edge swept half a clock a window across {kind}'s end, the sled 16 + {p}",
                                   entries=ent, intak=pin == "INT"))
    for kind in ("tmc", "sfr"):
        progs.append(prog3(f"f5_pd_c_{kind}", set_c4(kind), f"TM0's request against {kind}'s boundary, the sled swept"))
        progs.append(prog3(f"f5_pd_c_{kind}_r", set_c4(kind, masked=True), "the twin: the request masked"))
    for kind in D_KINDS:
        progs.append(prog3(f"f5_pd_d_{kind}", set_dd(kind), f"a DMA end's request against {kind}'s boundary, the sled swept"))
        progs.append(prog3(f"f5_pd_d_{kind}_r", set_dd(kind, masked=True), "the twin: DIC0 masked"))
    for lv in (0, 7):
        progs.append(prog3(f"f5_pd_dl{lv}", set_dl(lv), f"a DMA end at level {lv} against the scan: its start swept"))
    progs.append(prog3("f5_pd_u", [window("e4", j, e4_ops(kind, j + 1), pre=D_PRE, kind=kind, twin=True, **KW.get(kind, {}))
                                   for j, kind in enumerate(("wi", "wi2"))], "the e series' pilot"))
    for pin in ("INT", "NMI"):
        for kind in ("wi", "wi2"):
            wins, ent = set_e4(pin, kind)
            progs.append(prog3(f"f5_pd_e_{pin[0].lower()}_{kind}", wins,
                               f"the {pin} edge swept across the store behind a DMA burst ({kind})",
                               entries=ent, intak=pin == "INT"))
    return {p.name: p for p in progs}


# ------------------------------------------------------------------ the fifth set (IE's rise in a worse level's slot)
PE_SRC = {"tm0": 0xFF9C, "p0": 0xFF4C, "se0": 0xFF6C, "se1": 0xFF7C}
PE_PAIRS = ((6, 3), (7, 0), (3, 2))
PE_H = (("st", 0xFF6C, 0x80), ("st", 0xFF7C, 0x83), ("st", 0xFF4C, 0x85), ("st", 0xFF9C, 0x86))


def set_pe(how, w, b, swap=False, n=40):
    """IE 0: two requests stored (B's first, then W's: the worse level W on TM0, the better B on INTP0;
    swap: the sources exchanged), a sled of x clocks, IE raised (RAISE: EI, POP PSW or RETI behind
    mark 1), 60 INC AW. The round is 20 clocks (two slots): the sled covers two."""
    sw, sb = ("p0", "tm0") if swap else ("tm0", "p0")
    pend = (("st", PE_SRC[sb], 0x80 | b), ("st", PE_SRC[sw], 0x80 | w))
    return [window("pe", x, pend + (("sled", x),) + RAISE[how] + (("inc", 60),), odd=x & 1, how=how, w=w, b=b,
                   sw=sw, sb=sb) for x in range(n)]


def set_peh(late, lead=None, n=40):
    """f3_prio grp_levels' shape: IE 0, four requests stored (SER0 0, SER1 3, INTP0 5, TM0 6), mark 1,
    EI, an INC train. SER0's handler: a sled of d clocks, FINT, RETI (h1, h3) or FINT, the sled, RETI
    (h2, h4). h3 / h4 (lead 6: a sled of six clocks in front of mark 1): EI rises outside every slot,
    SER0 is taken first and its handler's RETI raises IE with levels 3, 5 and 6 pending, swept against
    their slots. h1 / h2 (no lead): EI rises in level 5's slot, INTP0 is taken first, then SER1, then
    SER0: the swept RETI has TM0 (level 6) alone behind it."""
    out = []
    for d in range(n):
        h = ((("fint",), ("sled", d), ("reti",)) if late else (("sled", d), ("fint",), ("reti",)))
        out.append(window("peh", d, PE_H + ((("sled", lead),) if lead is not None else ()) + (("mark", 1), ("ei",), ("inc", 100)),
                          odd=d & 1, hand={"se0": h}, late=int(late)))
    return out


def programs5():
    progs = []
    for w, b in PE_PAIRS:
        for how in RAISE:
            progs.append(prog(f"f5_pe_{how}{w}{b}", set_pe(how, w, b),
                              f"IE 0, TM0 at level {w} and INTP0 at level {b} pending: IE raised by {how}, the sled swept"))
    progs.append(prog("f5_pe_reti63s", set_pe("reti", 6, 3, swap=True),
                      "the same with the sources exchanged (INTP0 at level 6, TM0 at level 3): RETI"))
    progs.append(prog("f5_pe_h1", set_peh(False), "four levels pending, SER0's handler: a sled, FINT, RETI"))
    progs.append(prog("f5_pe_h2", set_peh(True), "four levels pending, SER0's handler: FINT, a sled, RETI"))
    progs.append(prog("f5_pe_h3", set_peh(False, lead=6), "the same, SER0 taken first: its handler a sled, FINT, RETI"))
    progs.append(prog("f5_pe_h4", set_peh(True, lead=6), "the same, SER0 taken first: its handler FINT, a sled, RETI"))
    progs.append(prog("f5_pe_pop32s", set_pe("pop", 3, 2, swap=True),
                      "pop32 with the sources exchanged (INTP0 at level 3, TM0 at level 2)"))
    return {p.name: p for p in progs}


def events5(rec, prog):
    """Per window: marks {j: tick}, takes [(source, the vector read's tick, pushed PC, the last stack
    read in front of it or None)], meta."""
    wins, _ = oc.windows(rec, prog)
    inv = {v: k for k, v in VEC_RD.items()}
    out = {}
    for k, w in wins.items():
        e = dict(t0=w["t0"], marks={}, takes=[], meta=prog.windows[k].meta)
        rows, rd = w["rows"], None
        for i, (kind, r) in enumerate(rows):
            if kind == "mw" and MARK <= r[1] < MARK + 32:
                e["marks"].setdefault((r[1] - MARK) // 2, r[0])
            elif kind == "mr" and r[1] in inv:
                pushes = [x for kd, x in rows[i + 1:i + 8] if kd == "mw"][:3]
                e["takes"].append((inv[r[1]], r[0], pushes[2][2] if len(pushes) > 2 else None, rd))
            elif kind == "mr" and 0xE00 <= r[1] < STACK_TOP:
                rd = r[0]
        out[k] = e
    return out


def pe_cells(e, c=32):
    """A window's takes as text. pe: source:vector read less mark 1/INCs run[/less the PSW word's read
    for the first]. peh: the first as pe; the later ones source:vector read less the PSW word's read
    of the RETI in front of it/INCs run."""
    m, m1, cells = e["meta"], e["marks"].get(1), []
    for i, (src, t, pc, rd) in enumerate(e["takes"]):
        n = "?" if pc is None else pc - m["first"]
        if i == 0 or m["series"] == "pe":
            s = f"{src}:{ph.fmt((t - m1) / c)}/n{n}"
            if i == 0 and rd is not None and rd > m1 - 40 * c and m["series"] == "pe" and m["how"] != "ei":
                s += f"/{ph.fmt((t - rd) / c)}"
        else:
            s = f"{src}:{ph.fmt((t - rd) / c)}/n{n}"
        cells.append(s)
    return " ".join(cells) or "no take"


def pe_rows(name, backend, progs, verbose=False):
    """The fifth set: the takes' signature and the sled lengths that give it; -v: every window."""
    prog = progs[name]
    rec = ph.load(name, backend)
    ok = rec["program_sha256"] == hashlib.sha256(prog.build()["text"]).hexdigest()
    ev = events5(rec, prog)
    print(f"{name} [{backend}] {'PASS' if rec['passed'] else 'FAIL'} total {rec['total']} "
          f"{len(ev)}/{len(prog.windows)} windows" + ("" if ok else "  (THE RECEIPT IS OF ANOTHER VERSION)"))
    by = collections.OrderedDict()
    for k in sorted(ev):
        e = ev[k]
        e2 = dict(e, takes=e["takes"][:2 if e["meta"]["series"] == "pe" else None])
        by.setdefault(pe_cells(e2), []).append(e["meta"]["n"])
        if verbose:
            print(f"    x {e['meta']['n']:2d}: {pe_cells(e)}")
    for sig, xs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print(f"  {sig:44s} x {' '.join(map(str, xs)) if len(xs) < 14 else f'{len(xs)} windows: ' + rng(xs)}")


# ------------------------------------------------------------------ the sixth set: a long tail behind FINT
PF_BYTE, PF_PTR, PF_PTR2 = 0x0DF0, 0x0DF4, 0x0DF8      # the DEC's byte, the routines' addresses (SS 0)
# f3_prio's handler from its CALL on (intr.py HANDLER_SRC): the routine (FINT ; RET) called through a
# word, DEC byte, five POPs, POP PSW (IE 0 in the pushed word), RETI. Every routine is of an even
# length (the fillers), so FINT is fetched at an even address behind the CALL, as f3_prio's
PF_TAIL = (("pushes",), ("calli", PF_PTR), ("decb", PF_BYTE), ("pops",), ("popf",), ("reti",), ("nop", 1))
PF_TAIL_C = (("pushes",), ("calli", PF_PTR), ("decb", PF_BYTE), ("pops",), ("calli", PF_PTR2), ("popf",), ("reti",))
PF_ROUND = 22                       # the round with levels 3, 5 and 6 requesting, IE 0, nothing in service


def set_pf(kind, n=40):
    """f5_pe_h4's frame (SER0 0, SER1 3, INTP0 5, TM0 6 stored, a sled of 6, mark 1, EI, 100 INC AW; SER0
    taken first) with f3_prio's handler tail in SER0's handler: PUSH PSW and five registers, CALL word
    (the routine), DEC byte, five POPs, POP PSW, RETI. The routine, per window (the sled of d clocks):
    a  FINT ; sled d ; RET        the whole tail behind the sled: the RETI's rise about 200 clocks behind FINT
    b  sled d ; FINT ; RET        the control (pe_h3's): the sled in front of FINT
    c  FINT ; RET, and a second routine (sled d ; RET) called in front of POP PSW: the sled at the tail's end
    The handler is one copy; the windows' setups store their routines' addresses."""
    out = []
    for d in range(n):
        if kind == "a":
            hand = {"se0": PF_TAIL, "act": (("fint",), ("sled", d), ("ret",))}
        elif kind == "b":
            hand = {"se0": PF_TAIL, "act": (("sled", d), ("fint",), ("ret",))}
        else:
            hand = {"se0": PF_TAIL_C, "act": (("fint",), ("ret",), ("nop", 1)), "act2": (("sled", d), ("ret",))}
        out.append(pf_win(d, hand, d & 1, kind=kind))
    return out


def pf_win(n, hand, odd, **kw):
    win = window("pf", n, PE_H + (("sled", 6), ("mark", 1), ("ei",), ("inc", 100)), odd=odd, hand=hand, **kw)

    def setup(a, s0=win.setup):
        s0(a)
        for ptr, key in ((PF_PTR, "act"), (PF_PTR2, "act2")):
            if key in win.hand:
                at = win.addr[win.hand[key]]
                a.op([0x36, 0xC7, 0x06, ptr & 0xFF, ptr >> 8, at & 0xFF, at >> 8],
                     f"MOV word SS:[{ptr:04X}h], {at:04X}h   ; the handler's routine")
        if "act2" not in win.hand:
            a.nop()                 # the body at pe_h4's parity
    win.setup = setup
    return win


# f5_pf_x: the routine's content swept instead of a sled (X ; RET at the CALL's target), the handler's
# own FINT behind the CALL: the clocks from the routine's first fetch to RET's stack read with X = FINT
# (level 0 in service: f3_prio's routine) against instructions of known length
PF_TAIL_X = (("pushes",), ("calli", PF_PTR), ("fint",), ("decb", PF_BYTE), ("pops",), ("popf",), ("reti",), ("nop", 1))
PF_X = (("fint", (("fint",),)), ("nop2", (("nop", 2),)), ("di2", (("di",), ("di",))), ("rol1", (("rol", 1),)),
        ("rol2", (("rol", 2),)), ("fint2", (("fint",), ("fint",))), ("nopfint", (("nop", 2), ("fint",))),
        ("fintnop", (("fint",), ("nop", 2))), ("none", ()), ("nop1", (("nop", 1),)), ("nop3", (("nop", 3),)),
        ("nop4", (("nop", 4),)), ("nop4fint", (("nop", 4), ("fint",))), ("fintnop4", (("fint",), ("nop", 4))))


def set_pfx():
    out = []
    for i, (name, x) in enumerate(PF_X):
        a = Asm(0)
        la.emit_ops(a, x + (("ret",),))
        act = x + (("ret",),) + ((("nop", 1),) if len(a.finish()) & 1 else ())
        out.append(pf_win(i, {"se0": PF_TAIL_X, "act": act}, 0, kind="x", x=name))
    return out


def programs6():
    progs = [prog("f5_pf_a", set_pf("a"), "pe_h4 with f3_prio's handler tail behind FINT: FINT ; sled ; RET ; DEC ; POPs ; RETI"),
             prog("f5_pf_b", set_pf("b"), "the same, the sled in front of FINT (the control)"),
             prog("f5_pf_c", set_pf("c"), "the same, the sled at the tail's end (in front of POP PSW ; RETI)"),
             prog("f5_pf_x", set_pfx(), "the same, the routine X ; RET: FINT against instructions of known length")]
    return {p.name: p for p in progs}


def pf_fint(win):
    """The address of the first word of SER0's handler's routine in a pf window (FINT's word in a, c and
    x fint; the sled's in b), of SER0's handler in a peh window (FINT's word in pe_h2 / h4)."""
    return win.addr[win.hand["act" if win.meta["series"] == "pf" else "se0"]]


def events6(rec, prog):
    """events5 with `fint`: the start of the first fetch at pf_fint's address behind the first take;
    `ret`: the first stack read behind it (RET's in the pf programs, the RETI's first in pe_h*); `psw`:
    the PSW word's read of SER0's RETI (the last stack read in front of the second take); `bus`: the
    window's bus records (kind, row)."""
    wins, _ = oc.windows(rec, prog)
    ev = events5(rec, prog)
    for k, e in ev.items():
        fa, t1 = pf_fint(prog.windows[k]), e["takes"][0][1] if e["takes"] else None
        rows = wins[k]["rows"]
        e["fint"] = next((r[0] for kind, r in rows if kind == "fetch" and r[1] == fa and t1 is not None and r[0] > t1), None)
        e["ret"] = next((r[0] for kind, r in rows if kind == "mr" and 0xE00 <= r[1] < STACK_TOP
                         and e["fint"] is not None and r[0] > e["fint"]), None)
        e["psw"] = e["takes"][1][3] if len(e["takes"]) > 1 else None
        e["bus"] = [(kind, r) for kind, r in rows if kind not in ("pin", "idle")]
    return ev


def pf_cells(e, c=32):
    """A window's takes behind the first: (D, R, text). D: the PSW word's read of SER0's RETI less the
    routine's first fetch, R: less RET's stack read, in clocks; text: source:vector read less the PSW
    word's read in front of it/INCs run."""
    cells = []
    for i, (src, t, pc, rd) in enumerate(e["takes"]):
        n = "?" if pc is None else pc - e["meta"]["first"]
        if i:
            cells.append(f"{src}:{ph.fmt((t - rd) / c)}/n{n}")
    dd = None if e["fint"] is None or e["psw"] is None else (e["psw"] - e["fint"]) / c
    rr = None if e["ret"] is None or e["psw"] is None else (e["psw"] - e["ret"]) / c
    return dd, rr, " ".join(cells) or "no take"


def pf_rows(name, backend, progs, verbose=False):
    """The sixth set (and pe_h1 .. h4): per window the distance D from the routine's first fetch (FINT's)
    to the RETI's PSW word read and the takes behind it; then the takes' signature by D modulo the round
    (PF_ROUND). f5_pf_x: per X the clocks from the routine's first fetch to RET's stack read."""
    prog = progs[name]
    rec = ph.load(name, backend)
    ok = rec["program_sha256"] == hashlib.sha256(prog.build()["text"]).hexdigest()
    ev = events6(rec, prog)
    print(f"{name} [{backend}] {'PASS' if rec['passed'] else 'FAIL'} total {rec['total']} "
          f"{len(ev)}/{len(prog.windows)} windows" + ("" if ok else "  (THE RECEIPT IS OF ANOTHER VERSION)"))
    f = lambda v: "-" if v is None else ph.fmt(v)
    if prog.windows[0].meta.get("kind") == "x":
        for k in sorted(ev):
            e = ev[k]
            dd, rr, sig = pf_cells(e)
            print(f"    {e['meta']['x']:9s} fetch to RET's read {f(None if dd is None or rr is None else dd - rr):>3s}, "
                  f"RET's read to the PSW word's {f(rr):>4s}, D {f(dd):>4s}  {sig}")
        return
    by, bym = collections.OrderedDict(), {}
    for k in sorted(ev):
        e = ev[k]
        dd, rr, sig = pf_cells(e)
        by.setdefault(sig, []).append((e["meta"]["n"], dd))
        if dd is not None:
            bym.setdefault(dd % PF_ROUND, []).append((e["meta"]["n"], dd, sig))
        if verbose:
            print(f"    d {e['meta']['n']:2d}: D {f(dd):>4s} R {f(rr):>4s}  {sig}")
    for sig, xs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        ds = sorted({x[1] for x in xs if x[1] is not None})
        print(f"  {sig:44s} d {rng([x[0] for x in xs])}: D "
              + (" ".join(ph.fmt(x) for x in ds) if len(ds) < 12 else ph.fmt(ds[0]) + " .. " + ph.fmt(ds[-1])))
    print(f"  by D mod {PF_ROUND} (the windows not of the first signature):")
    first = max(by.items(), key=lambda kv: len(kv[1]))[0]
    for m in sorted(bym):
        sigs = collections.OrderedDict()
        for n, dd, sig in bym[m]:
            if sig != first:
                sigs.setdefault(sig, []).append(ph.fmt(dd))
        if sigs:
            print(f"    {ph.fmt(m):>5s}: " + "; ".join(f"{sg} (D {' '.join(v)})" for sg, v in sigs.items()))


def pilot4(backend, progs):
    """PD_M2 from the pilot's receipt, and per kind the clocks from mark 1's write to mark 2's by phase."""
    prog = progs["f5_pd_t"]
    wins, _ = oc.windows(ph.load("f5_pd_t", backend), prog)
    out, tab = {}, collections.OrderedDict()
    for k, w in sorted(wins.items()):
        m = prog.windows[k].meta
        evr = next(r for kind, r in w["rows"] if r[3] & 0x100)
        m1 = next(r for kind, r in w["rows"] if kind == "mw" and r[1] == MARK + 2)
        m2 = next(r for kind, r in w["rows"] if kind == "mw" and r[1] == MARK + 4)
        out[f"{m['kind']}:{m['p']}"] = m2[0] - evr[4]
        tab.setdefault(m["kind"], []).append(((m2[0] - m1[0]) / 32, (m1[0] - evr[4]) / 32))
    print("PD_M2 =", out)
    print("  kind: mark 2 less mark 1 by phase 0..11 (clocks) | mark 1 less the event")
    for kind, v in tab.items():
        print(f"  {kind:5s}: " + " ".join(f"{ph.fmt(a):>5s}" for a, _ in v) + " | " + " ".join(sorted({ph.fmt(b) for _, b in v})))


def x_cuts(name, backend, progs):
    """An x program's twin and cut-offs in ticks after mark 1: (M2, X's write (start, end) or None,
    {boundary index: (the earliest edge, the latest edge, the first activity less the latest edge,
    the vector read less it)}, the sweep's first and last edge)."""
    prog = progs[name]
    ev = events3(ph.load(name, backend), prog)
    tk = max(ev)
    tw = ev[tk]
    tm1 = tw["marks"][1]
    M2 = tw["marks"][2] - tm1
    xw = [d for d in tw["dw"] if d[2] - tm1 < M2]
    by, edges = {}, []
    for k in sorted(ev):
        e = ev[k]
        if k == tk or e["edge"] is None or 1 not in e["marks"]:
            continue
        m1 = e["marks"][1]
        t = e["takes"][0] if e["takes"] else None
        lab = label(e["meta"], t[2])[0] if t and t[2] is not None else None
        edges.append(e["edge"] - m1)
        by.setdefault(lab, []).append((e["edge"] - m1, None if not t else t[3] - e["edge"], None if not t else t[1] - e["edge"]))
    cuts = {lab: (min(v)[0], max(v)[0], max(v)[1], max(v)[2]) for lab, v in by.items()}
    return M2, (xw[-1][2] - tm1, xw[-1][3] - tm1) if xw else None, cuts, (min(edges), max(edges)) if edges else None


def pd_x(backend, progs):
    """The fourth set's x programs in one table. Per pin, kind and phase p: L = X's length (the
    control's 11 + this twin's mark 2 less the control's at the same p: 11 + the grid's wait); the
    latest edge taken at X's end (E1) against the twin's mark 2, against X's dispatch D (the control's
    mark 2 less 21) and against the next dispatch B (mark 2 less 10); the latest edge taken in front
    of X (E0) against D where the sweep reaches it. '>': the cut-off is at the sweep's end."""
    f = lambda v: "-" if v is None else q(v)
    for pin in "in":
        ctl = {}
        for p in range(6):
            n = f"f5_pd_{pin}_sfr_p{p}"
            if ph.receipt_path(n, backend).exists():
                ctl[p] = x_cuts(n, backend, progs)[0]
        print(f"[{backend}] {'INT' if pin == 'i' else 'NMI'}: kind p | twin M2-m1 | L | E1-M2 | E1-D | B-E1 | E0-D | "
              "first-E1 V-E1 | the sweep (edge-M2); the edges by the boundary taken")
        for kind, phases in G_KINDS:
            for p in phases:
                n = f"f5_pd_{pin}_{kind}_p{p}"
                if not ph.receipt_path(n, backend).exists():
                    continue
                M2, xw, cuts, sw = x_cuts(n, backend, progs)
                if sw is None:
                    print(f"  {kind:5s} {p} | {q(M2):>5s} | no edge recorded")
                    continue
                D = None if p not in ctl else ctl[p] - 21 * 32
                L = None if D is None else (M2 - 10 * 32 - D)
                c1, c0 = cuts.get(1), cuts.get(0)
                flag = ">" if c1 and c1[1] == sw[1] else ""
                print(f"  {kind:5s} {p} | {q(M2):>5s} | {f(L):>4s} | {f(c1 and c1[1] - M2):>6s}{flag:1s} | "
                      f"{f(None if not c1 or D is None else c1[1] - D):>5s} | {f(c1 and M2 - 320 - c1[1]):>5s} | "
                      f"{f(None if not c0 or D is None else c0[1] - D):>5s} | {f(c1 and c1[2]):>5s} {f(c1 and c1[3]):>5s} | "
                      f"{q(sw[0] - M2)}..{q(sw[1] - M2)}; "
                      + " ".join(f"{'none' if lab is None else 'X%+d' % lab}:{q(v[0] - M2)}..{q(v[1] - M2)}"
                                 for lab, v in sorted(cuts.items(), key=lambda kv: kv[1][0]))
                      + (f" | X write {q(xw[0])}..{q(xw[1])}" if xw else ""))


def pd_rows(name, backend, progs):
    """A d / dl program by window: the sweep's value, the DMA's last write (start..end), the takes
    (source@vector read: the instruction not executed), the vector read less the DMA's end, the
    window's own X write and mark 2, the twin's (the `_r` program's same window); clocks after
    mark 1's write."""
    prog = progs[name]
    ev = events3(ph.load(name, backend), prog)
    tn = name + "_r"
    tw = events3(ph.load(tn, backend), progs[tn]) if tn in progs and ph.receipt_path(tn, backend).exists() else {}
    print(f"{name} [{backend}]")
    for k in sorted(ev):
        e, m = ev[k], ev[k]["meta"]
        m1 = e["marks"].get(1)
        if m1 is None:
            print(f"  n{m['n']}: no mark 1")
            continue
        f = lambda t: "-" if t is None else q(t - m1)
        dma = [d for d in e["dw"] if d[1] >= 0x40000]
        de = dma[-1][3] if dma else None
        xw = [d for d in e["dw"] if d[1] < 0x40000]
        tk = " ".join(f"{s}@{f(v)}:{lt(label(m, pc))[:24] if pc is not None else '?'}" for s, v, pc, _ in e["takes"][:2])
        line = (f"  n{m['n']:2d} | DMA {f(dma[-1][2]) if dma else '-'}..{f(de)} ({len(dma)}) | {tk or 'no take':44s} | "
                f"V-DMA {q(e['takes'][0][1] - de) if e['takes'] and de else '-':>5s} | own X {f(xw[0][2]) if xw else '-'} m2 {f(e['marks'].get(2))}")
        t = tw.get(k)
        if t and 1 in t["marks"]:
            g_ = lambda x: "-" if x is None else q(x - t["marks"][1])
            txw = [d for d in t["dw"] if d[1] < 0x40000]
            tdma = [d for d in t["dw"] if d[1] >= 0x40000]
            line += (f" | twin: DMA ..{g_(tdma[-1][3]) if tdma else '-'} X {g_(txw[0][2]) if txw else '-'} M2 {g_(t['marks'].get(2))}"
                     + (f" | V-M2 {q(e['takes'][0][1] - m1 - (t['marks'][2] - t['marks'][1]))}" if e["takes"] and 2 in t["marks"] else ""))
        print(line)


def emit(progs):
    for name, p in progs.items():
        (ph.PROGRAMS_DIR / f"{name}.s").write_text(p.source())
        b = p.build()
        if p.stim:
            (ph.PROGRAMS_DIR / f"{name}.stim.json").write_text(json.dumps(p.stim, indent=1) + "\n")
        print(f"{name}: {len(b['text'])} bytes, {len(p.windows)} windows, {len(b['segments'])} pages")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "summary", "rows", "cut", "hold", "repeat", "gate", "takes", "emit", "list", "pilot", "pc", "pcrows", "pcb", "pco", "pilot4", "pilote", "pdx", "pd", "pe", "pf"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--socket-fitted", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    progs = programs()
    progs.update(programs2())
    progs.update(programs3())
    progs.update(programs4())
    progs.update(programs5())
    progs.update(programs6())
    names = []
    for n in a.names or list(progs):
        names += [x for x in progs if x == n or x == "f5_pa_" + n] or [x for x in progs if x.startswith("f5_pa_" + n) or x.startswith("f5_" + n)]
    if a.action == "socket":
        if not a.socket_fitted:
            p.error("the socket action needs --socket-fitted")
        ph.run_set(names, "socket", a.tag, progs)
    elif a.action == "sim":
        ph.run_set(names, "sim", a.tag, progs)
    elif a.action == "rows":
        for n in names:
            rows2(n, a.ref + a.tag, progs)
    elif a.action == "summary":
        for n in names:
            summary(n, a.ref + a.tag, progs, a.verbose)
    elif a.action in ("cut", "hold"):
        for n in names:
            if ph.receipt_path(n, a.ref + a.tag).exists() and (a.action == "cut" or (
                    n + "_r" in progs and ph.receipt_path(n + "_r", a.ref + a.tag).exists())):
                (cut if a.action == "cut" else hold)(n, a.ref + a.tag, progs)
    elif a.action in ("repeat", "gate"):
        ok = True
        for n in names:
            ok &= ph.compare(n, a.ref, "socket-2" if a.action == "repeat" else a.cand, progs, verbose=a.verbose)
        return 0 if ok else 1
    elif a.action == "takes":
        ok = True
        for n in names:
            ok &= takes(n, a.ref, a.cand, progs)
        return 0 if ok else 1
    elif a.action == "pilot":
        pilot(a.ref + a.tag, progs)
    elif a.action == "pilot4":
        pilot4(a.ref + a.tag, progs)
    elif a.action == "pilote":
        pilot_e(a.ref + a.tag, progs)
    elif a.action == "pdx":
        pd_x(a.ref + a.tag, progs)
    elif a.action == "pd":
        for n in names:
            if ph.receipt_path(n, a.ref + a.tag).exists() and progs[n].windows[0].meta["series"] in ("d", "dl"):
                pd_rows(n, a.ref + a.tag, progs)
    elif a.action == "pe":
        for n in names:
            if ph.receipt_path(n, a.ref + a.tag).exists() and progs[n].windows[0].meta["series"] in ("pe", "peh"):
                pe_rows(n, a.ref + a.tag, progs, a.verbose)
    elif a.action == "pf":
        for n in names:
            if ph.receipt_path(n, a.ref + a.tag).exists() and progs[n].windows[0].meta["series"] in ("pf", "peh"):
                pf_rows(n, a.ref + a.tag, progs, a.verbose)
    elif a.action == "pco":
        pc_o("f5_pc_o", a.ref + a.tag, progs)
    elif a.action == "pcb":
        for n in names:
            if ph.receipt_path(n, a.ref + a.tag).exists() and progs[n].windows[0].meta["series"] == "x" \
                    and len(progs[n].windows) > 20:
                pc_x(n, a.ref + a.tag, progs, brief=True)
    elif a.action in ("pc", "pcrows"):
        for n in names:
            if ph.receipt_path(n, a.ref + a.tag).exists():
                (pc_x if a.action == "pc" else pc_rows)(n, a.ref + a.tag, progs)
    elif a.action == "list":
        for n in names:
            print(n, len(progs[n].windows), progs[n].note)
    else:
        emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
