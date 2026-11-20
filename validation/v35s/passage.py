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
}


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
                a.op(*KINDS[op[1]](i))
                if op[1] == "halt":
                    a.op([0x90], "NOP")
        elif k == "dw0":
            a.op([0x33, 0xD2], "XOR DW, DW")
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


def window(series, n, ops, pre=(), odd=0, md0=66, hand=None, ic=None, ix=1, cw=0, clk=8, note="", **kw):
    """lattice.window with IX, CW and the processor clock (PRC) set in the setup, DW and PRC put
    back at the end; meta["ins"]: the body's instructions (offset, text)."""
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
        ph.wtc1(a, odd)
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
KW = {"shcl": dict(cw=12), "jsh": dict(cw=20), "repl": dict(cw=6, ix=LDS_AT), "lds": dict(ix=LDS_AT)}
NS = 36
# c: TM0's count (MD0) by kind: the count-out (TOUT) falls in the middle of the 16 clocks in front
# of the scan round whose level-0 slot is about 14 clocks in front of X's end at the middle of the
# sweep (the request control store's restart is about 12 clocks after mark 1's write; pilot run)
C_MD = dict(inc=23, nop=23, cbw=23, halt=23, wr=25, push=25, rd=25, lds=25, mul=28, shcl=28, div=31, repl=39, jsh=25)
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
    inv = {v: k for k, v in VEC.items()}
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


def emit(progs):
    for name, p in progs.items():
        (ph.PROGRAMS_DIR / f"{name}.s").write_text(p.source())
        b = p.build()
        if p.stim:
            (ph.PROGRAMS_DIR / f"{name}.stim.json").write_text(json.dumps(p.stim, indent=1) + "\n")
        print(f"{name}: {len(b['text'])} bytes, {len(p.windows)} windows, {len(b['segments'])} pages")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "summary", "rows", "cut", "hold", "repeat", "gate", "takes", "emit", "list"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--socket-fitted", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    progs = programs()
    progs.update(programs2())
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
    elif a.action == "list":
        for n in names:
            print(n, len(progs[n].windows), progs[n].note)
    else:
        emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
