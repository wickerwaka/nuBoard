"""Round 15.

FF10h marker writes are allowed from this round (port bank R2 handed to the CPU exactly as
validation/v35s/banks.py INT_HEAD / INT_TAIL and periph.py's TOUT set-up do it).

r15i*  the INT pin with INTAK answered by the harness (vector 40h -> 0100h), /INTAK recorded
r15o   TOUT on P15 recorded against timer 0's request
r15c*  the class question for the held-back INTPn edge
r15g*  a timer request across the ADD [BW],AW; NOP train and across NOPs
r15l*  INTP0 at levels 2 and 5 across a NOP train
r15h   HALT behind other predecessors
r15e   EI behind a NOP at two waits, moved by CLCs
r15a   small not-probed forms
"""

from ..chains import blocks
from .gen import NOP, q
from .gen_r9 import probe
from .gen_r12 import K
from .gen_r14 import CLC, EI, RMW, sfr_b, sfr_w

END = list(blocks.END)
R2_Z, R2_D = 0x04, 0x08


def mark(v):
    return [q([0xBA, 0x10, 0xFF], "mov_dw"), q([0xB0, v], "mov_al"), q([0xEE], "marker")]


DS1F = [q([0xB8, 0x00, 0xF0], "mov_aw"), q([0x8E, 0xC0], "mov_ds1")]
# banks.py INT_HEAD: R2 released, P1 latch 0, SCM0 I/O mode, PM1 97h, PMC1 18h (INTAK, INT), R2 claimed
INT_HEAD = (mark(R2_Z) + DS1F + [sfr_b(0x08, 0x00), sfr_b(0x68, 0x04), sfr_b(0x09, 0x97),
                                 sfr_b(0x0A, 0x18)] + mark(R2_D))
# periph.py TOUT: PM1 9Fh, PMC1 28h (INTAK on P13, TOUT on P15)
TOUT_HEAD = (mark(R2_Z) + DS1F + [sfr_b(0x08, 0x00), sfr_b(0x09, 0x9F), sfr_b(0x0A, 0x28)]
             + mark(R2_D))


def tail_code(scm=True):
    """INT_TAIL as bytes: R2 released, PMC1 0, PM1 FFh, (SCM0 0), R2 back to the host."""
    c = [0xBA, 0x10, 0xFF, 0xB0, R2_Z, 0xEE, 0xB8, 0x00, 0xF0, 0x8E, 0xC0,
         0x26, 0xC6, 0x06, 0x0A, 0xFF, 0x00, 0x26, 0xC6, 0x06, 0x09, 0xFF, 0xFF]
    if scm:
        c += [0x26, 0xC6, 0x06, 0x68, 0xFF, 0x00]
    return c + [0xBA, 0x10, 0xFF, 0xB0, 0x00, 0xEE]


def handler(scm=True):
    return [q([0xE6, 0x23] + tail_code(scm) + END, "handler")]


def vec(addr):
    return [q([0xC7, 0x06, addr & 255, addr >> 8, 0x00, 0x00], "vec"),
            q([0xC7, 0x06, (addr + 2) & 255, addr >> 8, 0x00, 0x10], "vec_ps")]


def pad_even(s):
    if sum(len(i.code) for i in s) & 1:
        s.insert(0, q(NOP, "nop"))
    return s


def event_tail(ei=True):
    s = [q([0xBA, 0x12, 0xFF], "mov_dw"), q([0xB0, 0x01], "mov_al")]
    if ei:
        s.append(q(EI, "ei"))
    return s + [q([0xEE], "event"), q([0xBA, 0x20, 0x00], "mov_dw")]


def run(name, pre, body, stim, post, w=0):
    extra = {"_pre": pad_even(list(pre)), "_post": post, "_stim": stim, "_waits": (w,)}
    return (name, ([q(c, "x") for c in body], None, extra))


def dly(r, w=0):
    return 8 * (r + K[w] - 20)


INT_STIM = {"intak_vector": 0x40, "int_release": True, "pins": ["INTAK"]}


def int_pre(extra_vecs=(), ics=(), ei=True):
    s = list(INT_HEAD) + vec(0x100)
    for a in extra_vecs:
        s += vec(a)
    s += [sfr_b(a, v) for a, v in ics]
    return s + event_tail(ei)


def round15i(which):
    v = []
    up = lambda d, more=None: dict(INT_STIM, entries=[{"event": 1, "delay": d, "hold": 0,
                                                       "levels": dict({"INT": 1}, **(more or {}))}])
    if which == "nop":
        for r in range(-2, 30):
            v.append(run(f"x-int-nop-d{dly(r)}", int_pre(), [NOP] * 14, up(dly(r)), handler()))
    elif which == "halt":
        for r in range(0, 40, 2):
            v.append(run(f"x-int-halt-d{dly(r)}", int_pre(), [NOP, [0xF4]], up(dly(r)), handler()))
    elif which == "p0":
        for r in range(0, 32, 2):
            v.append(run(f"x-int-p0-d{dly(r)}", int_pre([0x60], [(0x4C, 0x07)]), [NOP] * 14,
                         up(dly(r), {"INTP0": 0}), handler()))
    elif which == "nmi":
        for r in range(0, 32, 2):
            v.append(run(f"x-int-nmi-d{dly(r)}", int_pre([0x08]), [NOP] * 14,
                         up(dly(r), {"NMI": 0}), handler()))
    elif which == "ei":
        # INT high long before; released by EI in the body, the EI moved by CLCs
        for k in range(14):
            v.append(run(f"x-int-ei-k{k}", int_pre(ei=False), [CLC] * k + [EI] + [NOP] * 14,
                         up(8), handler()))
    elif which == "eip0":
        # the same with INTP0 pending as well at level 7, 5, 2, 0: who is first
        for lv in (7, 5, 2, 0):
            for k in (0, 3):
                v.append(run(f"x-int-eip0-l{lv}-k{k}", int_pre([0x60], [(0x4C, 0x80 | lv)], ei=False),
                             [CLC] * k + [EI] + [NOP] * 14, up(8), handler()))
    return v


def round15o(tmc=0x80, tag="tout"):
    """TOUT (P15) and /INTAK (P13) recorded; timer 0 interval, SCLK / 6 (TMC0 84h: TOUT enabled)."""
    v = []
    start = [0x26, 0xC6, 0x06, 0x90, 0xFF, tmc]
    stim = {"entries": [], "pins": ["P13", "P15"]}
    for n in range(3, 11):
        pre = (list(TOUT_HEAD) + vec(0x70) + [sfr_b(0x90, 0x00), sfr_w(0x82, n), sfr_w(0x80, n),
                                              sfr_b(0x9C, 0x07), q(EI, "ei")])
        v.append(run(f"t-{tag}-halt-n{n}", pre, [start, NOP, [0xF4]], stim, handler(False)))
        v.append(run(f"t-{tag}-nop-n{n}", pre, [start] + [NOP] * 40, stim, handler(False)))
    return v


HND = [q([0xE6, 0x23] + END, "handler")]


def p0_pre(level=7):
    s = vec(0x60) + DS1F + [sfr_b(0x4C, level), q([0xB8, 0x00, 0x00], "mov_aw"), q([0x8E, 0xC0], "mov_ds1")]
    return s + event_tail()


def one(pin, d):
    return {"entries": [{"event": 1, "delay": d, "hold": 400, "levels": {pin: 0}}]}


CLS = {"c81": [0x81, 0x07, 0x01, 0x00], "c80": [0x80, 0x07, 0x01], "ccmpi": [0x83, 0x3F, 0x01],
       "cdec": [0xFF, 0x0F], "cneg": [0xF7, 0x1F], "csbb": [0x19, 0x07], "ctesti": [0xF7, 0x07, 0x01, 0x00]}


def round15c(which):
    return [run(f"p-{which}-intp0-d{dly(r)}", p0_pre(), [CLS[which], NOP] * 4, one("INTP0", dly(r)), HND)
            for r in range(10, 44)]


def round15g(which):
    """Timer 0's request (count n, start moved by k CLCs) across RMW;NOP or NOPs."""
    v = []
    start = [0x26, 0xC6, 0x06, 0x90, 0xFF, 0x80]
    train = [RMW, NOP] * 8 if which == "rmw" else [NOP] * 40
    for n in range(2, 12):
        for k in (0, 1, 2):
            pre = vec(0x70) + DS1F + [sfr_b(0x90, 0x00), sfr_w(0x82, n), sfr_w(0x80, n),
                                      sfr_b(0x9C, 0x07), q(EI, "ei")]
            v.append(run(f"g-{which}-n{n}-k{k}", pre, [CLC] * k + [start] + train,
                         {"entries": []}, HND))
    return v


def round15l(level):
    return [run(f"l-lv{level}-intp0-d{dly(r)}", p0_pre(level), [NOP] * 14, one("INTP0", dly(r)), HND)
            for r in range(0, 40)]


PRED = {"clc": [CLC], "inc": [[0x40]], "movi": [[0xB8, 0x34, 0x12]], "xchg": [[0x93]],
        "nn": [NOP, NOP], "nnn": [NOP, NOP, NOP], "movcl": [[0xB1, 0x03]], "push": [[0x50]],
        "none": [], "jc": [[0xEB, 0x00], CLC], "cn": [CLC, NOP], "ld": [[0x8B, 0x07]]}


def round15h():
    v = []
    for name, pred in PRED.items():
        for r in (24, 30, 46):
            v.append(run(f"h-{name}-intp0-d{dly(r)}", p0_pre(), pred + [[0xF4]], one("INTP0", dly(r)), HND))
    return v


def round15e():
    from .gen_r14 import sw
    p0 = [("p0", 0x87, 1)]
    return [sw(f"sw-npad{k}-nop", p0, [NOP] + [CLC] * k + [EI] + [NOP] * 14, waits=(2,))
            for k in range(14)]


def round15a():
    v = []
    forms = {"cmpmr": [0x39, 0x07], "cmpmr8": [0x38, 0x07], "negd16": [0xF7, 0x9F, 0x10, 0x00],
             "inaw": [0xED], "lahf": [0x9F], "testal": [0xA8, 0x55], "xchdw": [0x92],
             "cvtbd": [0xD4, 0x0A], "adj4a": [0x27], "adjba": [0x37], "adjbs": [0x3F],
             "cmpal": [0x3C, 0x12]}
    from .gen import M1I
    for name, code in forms.items():
        v += probe(name, code, m1=M1I) if name in ("xchdw", "inaw") else probe(name, code)
    return v


ROUNDS = {"r15o": round15o, "r15p": (lambda: round15o(0x84, "tout4")), "r15q": (lambda: round15o(0x8C, "toutc")), "r15h": round15h, "r15e": round15e, "r15a": round15a,
          **{f"r15i{w}": (lambda w=w: round15i(w)) for w in ("nop", "halt", "p0", "nmi", "ei", "eip0")},
          **{f"r15c{w[1:]}": (lambda w=w: round15c(w)) for w in CLS},
          **{f"r15g{w}": (lambda w=w: round15g(w)) for w in ("rmw", "nop")},
          **{f"r15l{w}": (lambda w=w: round15l(w)) for w in (2, 5, 0)}}
