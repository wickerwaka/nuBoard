"""Round 14.

r14a  the small not-probed forms: shifts on memory by imm8 / CL, 80-group byte forms on memory,
      LDS / LES, MOV mem,sreg / MOV sreg,mem, PUSH imm8, CVTWL, MUL r,m,imm (operand stored
      before M0)
r14n* interrupts: INTP0 across RMW trains with idle gaps, XCH mem, INC mem and BUSLOCK loads;
      NMI across XCH AW,BW and NOP NOP CLC trains; INTP0 into HALT one clock at a time; two and
      three maskable pins on one grid point and one grid point apart; NMI stepped across an
      INTP0 acknowledge and its handler; the INT pin with INTAK answered by the harness
"""

from ..chains import blocks
from .gen import M1I, NOP, SLOW, q
from .gen_r9 import probe
from .gen_r12 import K

CLC = [0xF8]
SFR_IC = {"intp0": (0x4C, 0x60), "intp1": (0x4D, 0x64), "intp2": (0x4E, 0x68)}
PIN = {"nmi": "NMI", "intp0": "INTP0", "intp1": "INTP1", "intp2": "INTP2", "int": "INT"}
HANDLER = [q([0xE6, 0x23] + list(blocks.END), "handler")]
HANDLER_LONG = [q([0xE6, 0x23, 0xB1, 0x1F, 0xD3, 0xE5] + list(blocks.END), "handler")]


def round14a():
    v = []
    forms = {"shmi": [0xC1, 0x27, 0x04], "shmbi": [0xC0, 0x27, 0x04],
             "addmb": [0x80, 0x07, 0x01], "ormb": [0x80, 0x0F, 0x80], "cmpmb": [0x80, 0x3F, 0x01],
             "lds": [0xC5, 0x07], "les": [0xC4, 0x07], "movms": [0x8C, 0x1F],
             "movsm": [0x8E, 0x07], "pushi8": [0x6A, 0x12]}
    for name, code in forms.items():
        v += probe(name, code)
    v += probe("cvtwl", [0x99], m1=M1I)         # CVTWL writes DW: the marker as OUT imm8
    v += probe("shmcl", [0xD3, 0x27], pre=[[0xB1, 0x03]])
    v += probe("shmbcl", [0xD2, 0x27], pre=[[0xB1, 0x03]])
    pre = {"_pre": [q([0xC7, 0x07, 0x03, 0x00], "st_imm")]}
    for name, code in {"mi16m": [0x69, 0x07, 0x34, 0x12], "mi8m": [0x6B, 0x07, 0x12]}.items():
        for vn, body in probe(name, code):
            v.append((vn, (body, None, pre)))
    return v


def round14b():
    """Shifts on memory at other counts (the count loop: 2 words a count?)."""
    v = []
    for n in (1, 8):
        v += probe(f"shmi{n}", [0xC1, 0x27, n])
        v += probe(f"shmcl{n}", [0xD3, 0x27], pre=[[0xB1, n]])
    return v


def _setup(srcs):
    s = []
    for src in srcs:
        if src == "nmi":
            s += [q([0xC7, 0x06, 0x08, 0x00, 0x00, 0x00], "vec"),
                  q([0xC7, 0x06, 0x0A, 0x00, 0x00, 0x10], "vec_ps")]
        elif src == "int":
            s += [q([0xC7, 0x06, 0x00, 0x01, 0x00, 0x00], "vec"),
                  q([0xC7, 0x06, 0x02, 0x01, 0x00, 0x10], "vec_ps")]
        else:
            ic, vec = SFR_IC[src]
            s += [q([0xC7, 0x06, vec, 0x00, 0x00, 0x00], "vec"),
                  q([0xC7, 0x06, vec + 2, 0x00, 0x00, 0x10], "vec_ps")]
    ics = [SFR_IC[x][0] for x in srcs if x in SFR_IC]
    if ics:
        s += [q([0xB8, 0x00, 0xF0], "mov_aw"), q([0x8E, 0xC0], "mov_ds1")]
        s += [q([0x26, 0xC6, 0x06, ic, 0xFF, 0x07], "exic") for ic in ics]
        s += [q([0xB8, 0x00, 0x00], "mov_aw"), q([0x8E, 0xC0], "mov_ds1")]
    s += [q([0xBA, 0x12, 0xFF], "mov_dw"), q([0xB0, 0x01], "mov_al")]
    if any(x != "nmi" for x in srcs):
        s.append(q([0xFB], "ei"))
    s += [q([0xEE], "event"), q([0xBA, 0x20, 0x00], "mov_dw")]
    if sum(len(i.code) for i in s) & 1:
        s.insert(0, q(NOP, "nop"))
    return s


def irqx(name, srcs, body, rs, entries, w=0, handler=HANDLER, extra_stim=None):
    """entries(d) -> the schedule entries for the first edge's delay d (ticks)."""
    out = []
    for r in rs:
        d = 8 * (r + K[w] - 20)
        stim = {"entries": entries(d)}
        if extra_stim:
            stim.update(extra_stim)
        extra = {"_pre": _setup(srcs), "_post": handler, "_stim": stim, "_waits": (w,)}
        out.append((f"{name}-v{w}-d{d}", ([q(c, "x") for c in body], None, extra)))
    return out


def one(pin, hold=400):
    return lambda d: [{"event": 1, "delay": d, "hold": hold, "levels": {pin: 0}}]


RMW = [0x01, 0x07]
TR = {"g1": [RMW, NOP] * 4, "g2": [RMW, NOP, NOP] * 4, "g4": [RMW, NOP, NOP, NOP, NOP] * 3,
      "xch": [[0x87, 0x07]] * 4 + [NOP], "inc": [[0xFF, 0x07]] * 4 + [NOP],
      "lock": [[0xF0, 0x8B, 0x07]] * 5 + [NOP], "lockrmw": [[0xF0, 0x01, 0x07]] * 4 + [NOP]}
# second batch: the same question with the phase against the 16-clock grid moving
INCM = [0xFF, 0x07]
XCHM = [0x87, 0x07]
TR.update({"incn": [INCM, NOP] * 4, "incc": [INCM, CLC] * 4, "xchn": [XCHM, NOP] * 4,
           "xchc": [XCHM, CLC] * 4, "ldn": [[0x8B, 0x07], NOP] * 6, "stn": [[0x89, 0x07], NOP] * 6,
           "rmwc": [RMW, CLC] * 4, "addmn": [[0x03, 0x07], NOP] * 6,
           "rmwd8n": [[0x01, 0x47, 0x02], NOP] * 4})
NT = {"xchg": [[0x93]] * 12, "nnc": [NOP, NOP, CLC] * 5}
NOPS = [NOP] * 14


# fourth batch: which instructions open the window ADD [BW],AW opens (X, NOP trains)
CLS = {"cadd8": [0x00, 0x07], "csub": [0x29, 0x07], "cand": [0x21, 0x07], "cxor": [0x31, 0x07],
       "cadc": [0x11, 0x07], "ccmp": [0x39, 0x07], "ctest": [0x85, 0x07], "caddi": [0x83, 0x07, 0x01],
       "cnot": [0xF7, 0x17], "cshl": [0xD1, 0x27], "cmov": [0x89, 0x07], "cor": [0x09, 0x07]}


def round14n(which):
    v = []
    if which in CLS:
        return irqx(f"p-{which}-intp0", ["intp0"], [CLS[which], NOP] * 4, range(10, 44), one("INTP0"))
    if which in TR:
        v += irqx(f"p-{which}-intp0", ["intp0"], TR[which], range(-2, 50), one("INTP0"))
    elif which in NT:
        v += irqx(f"n-{which}-nmi", ["nmi"], NT[which], range(-2, 28), one("NMI"))
    elif which == "halt":
        v += irqx("h-halt-intp0", ["intp0"], [NOP, [0xF4]], range(-4, 40), one("INTP0"))
    elif which == "haltj":
        # HALT entered with the queue at other fills: behind a jump, 0 / 2 / 4 / 6 NOPs between
        for k in (0, 1, 2, 3, 4, 6):
            v += irqx(f"h-haltj{k}-intp0", ["intp0"], [[0xEB, 0x00]] + [NOP] * k + [[0xF4]],
                      range(31, 55, 4), one("INTP0"))
    elif which == "prio":
        allp = ["intp0", "intp1", "intp2"]
        for tag, pins in (("01", ("INTP0", "INTP1")), ("12", ("INTP1", "INTP2")),
                          ("02", ("INTP0", "INTP2")), ("012", ("INTP0", "INTP1", "INTP2"))):
            v += irqx(f"q-same{tag}-intp", allp, NOPS, range(0, 16, 2),
                      lambda d, pins=pins: [{"event": 1, "delay": d, "hold": 400,
                                             "levels": {p: 0 for p in pins}}])
        for tag, (first, second) in (("10", ("INTP1", "INTP0")), ("21", ("INTP2", "INTP1")),
                                     ("01", ("INTP0", "INTP1"))):
            v += irqx(f"q-next{tag}-intp", allp, NOPS, range(0, 16, 2),
                      lambda d, first=first, second=second: [
                          {"event": 1, "delay": d, "hold": 0, "levels": {first: 0}},
                          {"event": None, "delay": 118, "hold": 400, "levels": {second: 0}}])
    elif which == "nest2":
        v += irqx("s-nest2-intp0nmi", ["intp0", "nmi"], NOPS, range(60, 106),
                  lambda d: [{"event": 1, "delay": 8 * (K[0] - 20), "hold": 0,
                              "levels": {"INTP0": 0}},
                             {"event": None, "delay": d - 8 * (K[0] - 20) + 46,
                              "hold": 400, "levels": {"NMI": 0}}],
                  handler=HANDLER_LONG)
    elif which == "nest":
        # INTP0 on a fixed clock, NMI stepped across its acknowledge and the handler's start
        v += irqx("s-nest-intp0nmi", ["intp0", "nmi"], NOPS, range(0, 60),
                  lambda d: [{"event": 1, "delay": 8 * (K[0] - 20), "hold": 0,
                              "levels": {"INTP0": 0}},
                             {"event": None, "delay": d - 8 * (K[0] - 20) + 46,
                              "hold": 400, "levels": {"NMI": 0}}],
                  handler=HANDLER_LONG)
    elif which == "int":
        v += irqx("x-int-int", ["int"], NOPS, range(-2, 22),
                  lambda d: [{"event": 1, "delay": d, "hold": 0, "levels": {"INT": 1}}],
                  extra_stim={"intak_vector": 0x40, "int_release": True})
    return v


# ---- requests set by software (a store of IF), released at a known instruction: no pin
IC = {"p0": (0x4C, 0x60), "p1": (0x4D, 0x64), "p2": (0x4E, 0x68), "tu0": (0x9C, 0x70)}
FINT = [0x0F, 0x92]
RETI = [0xCF]
EI = [0xFB]
INCAW = [0x40]
MULU = [0xF6, 0xE1]


def sfr_b(addr, val):
    return q([0x26, 0xC6, 0x06, addr, 0xFF, val], "exic")


def sfr_w(addr, val):
    return q([0x26, 0xC7, 0x06, addr, 0xFF, val & 255, val >> 8], "sfrw")


def _sw_pre(reqs, more=()):
    """reqs: (source, IC value, 1 | 2 = which handler) in the order stored."""
    s = []
    for src, _, h in reqs:
        vec = IC[src][1]
        s += [q([0xC7, 0x06, vec, 0x00, 0x00, 0x00], "vec" if h == 1 else "vec2"),
              q([0xC7, 0x06, vec + 2, 0x00, 0x00, 0x10], "vec_ps")]
    s += [q([0xB8, 0x00, 0xF0], "mov_aw"), q([0x8E, 0xC0], "mov_ds1")]
    s += [sfr_b(IC[src][0], v) for src, v, _ in reqs if v is not None]
    s += [q(c, "pre") for c in more]
    if sum(len(i.code) for i in s) & 1:
        s.insert(0, q(NOP, "nop"))
    return s


def _h(form, port, mid=()):
    code = [0xE6, port]
    for c in mid:
        code += c
    return q(code + FINT + RETI, form)


def sw(name, reqs, body, h1=(), h2=(), more=(), waits=None):
    extra = {"_pre": _sw_pre(reqs, more), "_post": [_h("handler", 0x23, h1), _h("handler2", 0x22, h2)]}
    if waits:
        extra["_waits"] = waits
    return (name, ([q(c, "x") for c in body], None, extra))


def round14s():
    p0 = [("p0", 0x87, 1)]
    v = [sw("sw-ei-nop", p0, [EI] + [NOP] * 10),
         sw("sw-ei-inc", p0, [EI] + [INCAW] * 10),
         sw("sw-ei-mul", p0, [EI] + [MULU] * 4),
         sw("sw-ei-clc", p0, [EI] + [CLC] * 10),
         sw("sw-ei-xchg", p0, [EI] + [[0x93]] * 10),
         sw("sw-nei-nop", p0, [NOP, EI] + [NOP] * 10),
         sw("sw-popf-nop", p0, [[0x9D]] + [NOP] * 10, more=[[0xBB, 0x02, 0xF2], [0x53]]),
         sw("sw-mk-nop", [("p0", 0xC7, 1)], [[0x26, 0x80, 0x26, 0x4C, 0xFF, 0xBF]] + [NOP] * 10,
            more=[EI]),
         sw("sw-two-nop", [("p0", 0x87, 1), ("p1", 0x87, 2)], [EI] + [NOP] * 12),
         sw("sw-two-inc", [("p0", 0x87, 1), ("p1", 0x87, 2)], [EI] + [INCAW] * 12),
         sw("sw-three-nop", [("p2", 0x87, 2), ("p1", 0x87, 2), ("p0", 0x87, 1)], [EI] + [NOP] * 12),
         sw("sw-tup-nop", [("p0", 0x87, 1), ("tu0", 0x87, 2)], [EI] + [NOP] * 12),
         sw("sw-lev-nop", [("p0", 0x82, 1), ("tu0", 0x85, 2)], [EI] + [NOP] * 12),
         sw("sw-nesthi-nop", [("p0", 0x85, 1), ("tu0", None, 2)], [EI] + [NOP] * 10,
            h1=[[0x26, 0xC6, 0x06, 0x9C, 0xFF, 0x82], EI] + [NOP] * 6),
         sw("sw-nesteq-nop", [("p0", 0x85, 1), ("tu0", None, 2)], [EI] + [NOP] * 10,
            h1=[[0x26, 0xC6, 0x06, 0x9C, 0xFF, 0x85], EI, NOP, NOP, FINT] + [NOP] * 6)]
    return v


def round14u():
    """The release latency against the clock: k CLCs in front of the EI (2 clocks each)."""
    p0 = [("p0", 0x87, 1)]
    return [sw(f"sw-pad{k}-nop", p0, [CLC] * k + [EI] + [NOP] * 14, waits=(0,)) for k in range(0, 14)]


def round14v():
    """The same sweep with the request at level 2 and at level 5, and timer 0's request."""
    v = []
    for lv in (2, 5, 0):
        v += [sw(f"sw-lv{lv}pad{k}-nop", [("p0", 0x80 | lv, 1)], [CLC] * k + [EI] + [NOP] * 14,
                 waits=(0,)) for k in range(0, 14)]
    v += [sw(f"sw-tupad{k}-nop", [("tu0", 0x87, 1)], [CLC] * k + [EI] + [NOP] * 14, waits=(0,))
          for k in range(0, 14)]
    return v


def round14t():
    """Timer 0 as an interval timer (SCLK / 6): the count, the pad before the start, HALT or NOPs."""
    v = []

    def tm(name, n, body):
        pre = [q([0xC7, 0x06, 0x70, 0x00, 0x00, 0x00], "vec"),
               q([0xC7, 0x06, 0x72, 0x00, 0x00, 0x10], "vec_ps"),
               q([0xB8, 0x00, 0xF0], "mov_aw"), q([0x8E, 0xC0], "mov_ds1"),
               sfr_b(0x90, 0x00), sfr_w(0x82, n), sfr_w(0x80, n), sfr_b(0x9C, 0x07), q(EI, "ei")]
        if sum(len(i.code) for i in pre) & 1:
            pre.insert(0, q(NOP, "nop"))
        extra = {"_pre": pre, "_post": HANDLER, "_waits": (0,)}
        v.append((name, ([q(c, "x") for c in body], None, extra)))

    start = [0x26, 0xC6, 0x06, 0x90, 0xFF, 0x80]
    for n in range(3, 19):
        tm(f"t-halt-n{n}", n, [start, NOP, [0xF4]])
    for k in range(1, 7):
        tm(f"t-halt-p{k}", 8, [NOP] * k + [start, NOP, [0xF4]])
    for n in (20, 21, 22, 23, 24, 25):
        tm(f"t-nop-n{n}", n, [start] + [NOP] * 60)
    return v


WHICH = tuple(TR) + tuple(NT) + tuple(CLS) + ("halt", "haltj", "prio", "nest", "nest2", "int")
ROUNDS = {"r14a": round14a, "r14b": round14b, "r14s": round14s, "r14u": round14u, "r14v": round14v, "r14t": round14t, **{f"r14n{w}": (lambda w=w: round14n(w)) for w in WHICH}}
