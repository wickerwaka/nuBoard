"""Round 23: the DMA-end interrupt request (DIC0) as a source.

r23t        one program (the check against f4_dma's receipt): MOV AW,[BW] train, DMARQ0 edge at 80
r23a<train> a single transfer, I/O to memory, TC 1, started by a DMARQ0 edge stepped one clock
            (60 to 96 from M0) across a steady train; DIC0 unmasked (`u`) and masked (`m`: the
            same transfer, no interrupt: the control for displaced cycles)
r23c        r23ald at six edges with the pins TC0 and DMAAK0 recorded (where the count's end shows)
r23dld      r23bld with DIC0 at level 5 (a scanned source's lattice is 4 clocks earlier, as INTP0's)
r23eld      r23bld on channel 1 (DIC1, vector 21)
r23b<train> a burst, memory to memory, TC 2, started by the TDMA store in the body; behind the
            store PADS[k] (0 to 13 clocks) then the train: the train's pops moved clock by clock
            against the terminal cycle; j CLCs in front of the store move the whole against the
            divided clock (the scan's lattice, if DIC0 is a scanned source)
"""

from ..chains import blocks
from .gen import NOP, q
from .gen_r14 import CLC, sfr_b
from .gen_r15 import DS1F, event_tail, mark, run, vec
from .gen_r17 import tick
from .gen_r18 import CBW, INC, LD, MOVI8, PADS

END = list(blocks.END)
T = {"nop": [NOP] * 56, "ld": [LD] * 34, "mi8": [MOVI8] * 44, "inc": [INC] * 70, "cbw": [CBW] * 70}


def blk(sar, dar, sarh, darh, tc, o=0):
    w = lambda a, v: q([0x26, 0xC7, 0x06, a + o, 0xFE, v & 255, v >> 8], "blk")
    b = lambda a, v: q([0x26, 0xC6, 0x06, a + o, 0xFE, v], "blk")
    return [w(0, sar), w(2, dar), b(5, sarh), b(4, darh), w(6, tc)]


def sb(addr, val):
    return [0x26, 0xC6, 0x06, addr, 0xFF, val]


def hnd(ports, ch=0):
    c = [0xE6, 0x23] + sb(0xA1 + 2 * ch, 0x00) + sb(0xAC + ch, 0x47)
    if ports:
        c += sb(0x12, 0x00) + [0xBA, 0x10, 0xFF, 0xB0, 0x10, 0xEE, 0xB0, 0x00, 0xEE]
    return [q(c + END, "handler")]


def pre_a(dic):
    return (vec(0x50) + DS1F + [sfr_b(0xAC, dic)] + mark(0x10) + [sfr_b(0x12, 0x7F)] + mark(0x20)
            + blk(0x0070, 0x0060, 0x0F, 0x0D, 1) + [sfr_b(0xA0, 0x11), sfr_b(0xA1, 0xA8)] + event_tail())


def pre_b(dic, ch=0):
    return (vec(0x50 + 4 * ch) + DS1F + [sfr_b(0xAC + ch, dic)] + blk(0x0040, 0x00A0, 0x0F, 0x0D, 2, 8 * ch)
            + [sfr_b(0xA0 + 2 * ch, 0x11)] + event_tail())


def rq(d):
    return {"entries": [{"event": 1, "delay": d, "hold": 400, "levels": {"DMARQ0": 1}}]}


def fam_a(train, es=range(60, 97)):
    v = []
    for e in es:
        for tag, dic in (("u", 0x07), ("m", 0x47)):
            v.append(run(f"a-{train}-{tag}-e{e}", pre_a(dic), T[train], rq(tick(e)), hnd(True)))
    return v


def fam_b(train, lv=7, ch=0):
    v = []
    for j in range(4):
        for k in [k for k in PADS if k <= 13]:
            for tag, dic in (("u", lv), ("m", 0x40 | lv)):
                body = [CLC] * j + [sb(0xA1 + 2 * ch, 0x8C)] + PADS[k] + T[train]
                v.append(run(f"b-{train}-{tag}-j{j}-k{k}", pre_b(dic, ch), body, {"entries": []}, hnd(False, ch)))
    return v


def fam_c():
    v = []
    for e in (62, 66, 70, 74, 78, 82):
        st = dict(rq(tick(e)), pins=["TC0", "DMAAK0"])
        v.append(run(f"c-ld-u-e{e}", pre_a(0x07), T["ld"], st, hnd(True)))
    return v


ROUNDS = {"r23t": lambda: fam_a("ld", [80]), "r23c": fam_c,
          "r23dld": lambda: fam_b("ld", 5), "r23eld": lambda: fam_b("ld", 7, 1),
          **{f"r23a{t}": (lambda t=t: fam_a(t)) for t in ("nop", "ld", "mi8")},
          **{f"r23b{t}": (lambda t=t: fam_b(t)) for t in ("nop", "ld", "inc")}}
