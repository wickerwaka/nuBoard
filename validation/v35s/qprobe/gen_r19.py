"""Round 19.

r19n<train><w>  NMI alone, the edge stepped half a clock, across trains that move an EU bus
      cycle against the pop (MOV AW,[BW] at W = 1 / 2, with other EA modes, with 1 to 3 NOPs
      between, stores, PUSH / POP, read-modify-write) and behind shifts of several counts and
      MULU byte / word: where is the sampling event of NMI's second stage
"""

from .gen import NOP, SLOW, q
from .gen_r14 import CLC, EI, sfr_b, sfr_w
from .gen_r15 import DS1F, HND, INT_STIM, event_tail, handler, int_pre, p0_pre, pad_even, run, vec
from .gen_r17 import DS1Z, nmi_pre, pulse
from .gen_r18 import CBW, INC, JMP0, LD, MOVI8, MOVI16, MULU16, edge, tickw

LD8, LDD, LBI, ST = [0x8B, 0x47, 0x10], [0x8B, 0x06, 0x00, 0x0C], [0x8B, 0x00], [0x89, 0x07]
PUSH, POP, RMW, MULU8 = [0x50], [0x58], [0x01, 0x07], [0xF6, 0xE3]


def shl(n):
    return [[0xB1, n]] + [NOP] * 3 + [list(SLOW)] + [NOP] * 10


NT = {"ld": [LD] * 12, "ld8": [LD8] * 10, "ldd": [LDD] * 10, "lbi": [LBI] * 10,
      "ln1": [LD, NOP] * 8, "ln2": [LD, NOP, NOP] * 6, "ln3": [LD, NOP, NOP, NOP] * 5,
      "st": [ST] * 12, "push": [PUSH] * 12, "pop": [POP] * 12, "pq": [PUSH, POP] * 7,
      "rmw": [RMW] * 8, "mul8": [NOP] * 3 + [MULU8] + [NOP] * 10,
      "sn": [ST, NOP] * 8, "pn": [PUSH, NOP] * 8,
      **{f"sh{n}": shl(n) for n in (0, 1, 2, 3, 4, 6, 9)}}
# (train, w): (lo, hi, step) edge window in clocks from M0
NW = {("ld", 1): (88, 116, 4), ("ld", 2): (88, 120, 4), ("ld8", 0): (88, 114, 4), ("ldd", 0): (88, 114, 4),
      ("lbi", 0): (88, 114, 4), ("ln1", 0): (86, 116, 4), ("ln2", 0): (86, 124, 4), ("ln3", 0): (86, 128, 4),
      ("st", 0): (86, 112, 4), ("push", 0): (86, 112, 4), ("pop", 0): (86, 112, 4), ("pq", 0): (86, 116, 4),
      ("rmw", 0): (86, 124, 4), ("mul8", 0): (78, 112, 4), ("sn", 0): (86, 116, 4), ("pn", 0): (86, 116, 4),
      ("st", 2): (88, 120, 4), ("ld", 0): (86, 98, 2),
      **{(f"sh{n}", 0): (76, 108 + 2 * n, 4) for n in (0, 1, 2, 3, 4, 6, 9)}}


def nsweep(train, w, lo, hi, step, kind="nmi"):
    v = []
    for d in list(range(tickw(lo, w), tickw(hi, w), step)) + [2000]:
        pre, st, post = edge(kind, d)
        v.append(run(f"n-{train}{w}-{kind}-d{d}", pre, NT[train], st, post, w))
    return v


ROUNDS = {f"r19n{t}{w}": (lambda t=t, w=w: nsweep(t, w, *NW[t, w])) for t, w in NW}


# ---- item 1b: do INTP0 and a timer request go through NMI's second stage?  The request is
# made early (one scan round, a fixed clock at the loader); the train is moved against it by
# pads of 0 to 13 clocks.  NMI and INT in the same frame are the two controls.
from .gen_r15 import one, tail_code
from .gen_r18 import PADS
from .gen_r17 import tick

PT = {"nop": [NOP] * 16, "ld": [LD] * 12, "mi8": [MOVI8] * 16}
TSTART = [0x26, 0xC6, 0x06, 0x90, 0xFF, 0x80]


def padded(src):
    v = []
    for tn, tr in PT.items():
        for k in [k for k in PADS if k <= 13]:
            body = PADS[k] + tr
            if src == "p0":
                v.append(run(f"p-{tn}-k{k}-intp0-d{tick(62)}", p0_pre(), body, one("INTP0", tick(62)), HND))
            elif src == "nmi":
                v.append(run(f"p-{tn}-k{k}-nmi-d{tick(70)}", nmi_pre(), body, pulse("NMI", tick(70)), HND))
            elif src == "int":
                st = dict(INT_STIM, entries=[{"event": 1, "delay": tick(70), "hold": 0, "levels": {"INT": 1}}])
                v.append(run(f"p-{tn}-k{k}-int-d{tick(70)}", int_pre(), body, st, handler()))
            else:
                pre = vec(0x70) + DS1F + [sfr_b(0x90, 0x00), sfr_w(0x82, 9), sfr_w(0x80, 9),
                                          sfr_b(0x9C, 0x07), q(EI, "ei")]
                v.append(run(f"p-{tn}-k{k}-tm-d0", pre, [TSTART] + body, {"entries": []}, HND))
    return v


ROUNDS.update({f"r19p{s}": (lambda s=s: padded(s)) for s in ("p0", "nmi", "int", "tm")})


# ---- item 2: what INT's seven clocks are.
DI = [0xFA]
TAIL = [tail_code() + [0xBA, 0x20, 0x00]]


def ist(d, h):
    return dict(INT_STIM, entries=[{"event": 1, "delay": d, "hold": h, "levels": {"INT": 1}}])


def di_sweep():
    """IE cleared k clocks after the edge: DI in a NOP train, the level held 30 clocks; and
    DI ... EI 16 clocks later with the pin high for 2 clocks only (is a request that entered
    with IE = 1 remembered through DI?), and with the level held."""
    v = []
    for d in range(tick(70), tick(98), 4):
        v.append(run(f"d-di-int-d{d}", int_pre(), [NOP] * 4 + [DI] + [NOP] * 10 + TAIL, ist(d, 240), handler()))
    for h in (16, 480):
        for d in range(tick(70), tick(98), 8):
            v.append(run(f"d-die{h}-int-d{d}", int_pre(), [NOP] * 4 + [DI] + [NOP] * 4 + [EI] + [NOP] * 12 + TAIL,
                         ist(d, h), handler()))
    return v


def short_sweep():
    """INT high for 2 / 3 clocks across trains whose pops are 10 clocks apart (MOV AW,[BW]) and
    inside SHL AW,CL (76 clocks): a line carrying the level shows the pulse to the loader for
    2 / 3 clocks only, a decision that stands is taken by the next pop whenever it comes."""
    v = []
    for h in (16, 24):
        for d in range(tick(76), tick(98), 4):
            v.append(run(f"s-ld{h}-int-d{d}", int_pre(), [LD] * 12 + TAIL, ist(d, h), handler()))
        for d in range(tick(96), tick(144), 64):
            v.append(run(f"s-shl{h}-int-d{d}", int_pre(), [NOP] * 3 + [list(SLOW)] + [NOP] * 10 + TAIL, ist(d, h), handler()))
    return v


ROUNDS.update({"r19d": di_sweep, "r19s": short_sweep})


def padded2(src, n=20):
    """As padded(), the request late enough to meet the train in its steady state (the first
    version's request stood at the EU while the pad itself executed: every rule fits that)."""
    v = []
    for tn, tr in PT.items():
        for k in [k for k in PADS if k <= 13]:
            body = PADS[k] + tr + tr
            if src == "p0":
                v.append(run(f"q-{tn}-k{k}-intp0-d{tick(92)}", p0_pre(), body, one("INTP0", tick(92)), HND))
            elif src == "nmi":
                v.append(run(f"q-{tn}-k{k}-nmi-d{tick(104)}", nmi_pre(), body, pulse("NMI", tick(104)), HND))
            else:
                pre = vec(0x70) + DS1F + [sfr_b(0x90, 0x00), sfr_w(0x82, n), sfr_w(0x80, n),
                                          sfr_b(0x9C, 0x07), q(EI, "ei")]
                v.append(run(f"q-{tn}-k{k}-tm{n}-d0", pre, [TSTART] + body, {"entries": []}, HND))
    return v


ROUNDS.update({"r19qnmi": lambda: padded2("nmi"), "r19qp0": lambda: padded2("p0"),
               "r19qtm": lambda: padded2("tm", 20), "r19qtn": lambda: padded2("tm", 26)})
