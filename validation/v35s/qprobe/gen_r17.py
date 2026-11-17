"""Round 17.

r17a  LEA per EA mode (spec 12's shape was read from LEA AW,[BW] alone): twelve modes, each in
      the round-8 lead frame (INC / CBW / NOP / CLC ; LEA) and as the four probe programs
r17n / r17p / r17i   NMI, INTP0 (level 7), INT across the NOP train with the edge stepped a
      quarter clock at a time (the pin's sampling instant and lattice, side by side)
r17nr / r17pr        the same with the rising edge selected (INTM 05h), the pin pulled low 25
      clocks earlier and released at the stepped tick
r17wn / r17wp        NMI / INTP0 pulses 0.25 to 4 clocks wide at 16 quarter-clock positions
r17wi                INT high for 0.5 to 3 clocks at half-clock positions across the NOP train
r17f  the request flag read by the program: INTP0 masked, MOV AL,[EXIC0] ; MOV [BW],AL five
      times, the edge stepped half a clock at a time (pin to flag, no scan, no EU)
r17b  ADD / CMP word mem,imm16 with d8 / d16 / direct and ADD mem,imm8 with d16, lead and probe frames
r17h  NMI and INT into HALT, the edge stepped a quarter clock at a time
"""

from .gen import NOP, q
from .gen_r9 import probe
from .gen_r14 import CLC, sfr_b
from .gen_r15 import (DS1F, HND, INT_STIM, event_tail, handler, int_pre, p0_pre, run, tail_code,
                      vec)

LEA = {"bw": [0x8D, 0x07], "bwix": [0x8D, 0x00], "bpiy": [0x8D, 0x03], "ix": [0x8D, 0x04],
       "bwd8": [0x8D, 0x47, 0x10], "bpd8": [0x8D, 0x46, 0x10], "bwixd8": [0x8D, 0x40, 0x10],
       "ixd8": [0x8D, 0x44, 0x10], "bwd16": [0x8D, 0x87, 0x10, 0x02],
       "bpd16": [0x8D, 0x86, 0x10, 0x02], "bwixd16": [0x8D, 0x80, 0x10, 0x02],
       "dir": [0x8D, 0x06, 0x00, 0x0C]}


def round17a():
    v = []
    for name, code in LEA.items():
        for pn, pc in (("i", [0x43]), ("c", [0x98]), ("n", NOP), ("k", CLC)):
            v.append((f"ll-{name}-{pn}", [q(pc, "prev"), q(code, "lea_" + name)]))
        v += probe(f"le-{name}", code)
    return v


DS1Z = [q([0xB8, 0x00, 0x00], "mov_aw"), q([0x8E, 0xC0], "mov_ds1")]
NOPS = [NOP] * 14


def tick(e):
    """The schedule delay (ticks) that puts the edge at clock e from M0 (W = 0 frames)."""
    return int(round(8 * (e + 15.5)))


def nmi_pre(rising=False):
    s = vec(0x08)
    if rising:
        s += DS1F + [sfr_b(0x40, 0x05)] + DS1Z
    return s + event_tail(ei=False)


def p0r_pre():
    return vec(0x60) + DS1F + [sfr_b(0x40, 0x05), sfr_b(0x4C, 0x07)] + DS1Z + event_tail()


def pulse(pin, d, hold=400, level=0):
    return {"entries": [{"event": 1, "delay": d, "hold": hold, "levels": {pin: level}}]}


def fine(kind, lo, hi, step=2, rising=False):
    v = []
    for d in range(tick(lo), tick(hi), step):
        if kind == "nmi":
            pre, st = nmi_pre(rising), pulse("NMI", d - 200, 200) if rising else pulse("NMI", d)
        elif kind == "intp0":
            pre = p0r_pre() if rising else p0_pre()
            st = pulse("INTP0", d - 200, 200) if rising else pulse("INTP0", d)
        else:
            pre, st = int_pre(), dict(INT_STIM, entries=[{"event": 1, "delay": d, "hold": 0,
                                                          "levels": {"INT": 1}}])
        post = handler() if kind == "int" else HND
        v.append(run(f"f-{kind}{'r' if rising else ''}-d{d}", pre, NOPS, st, post))
    return v


def widths(kind):
    v = []
    pin = {"nmi": "NMI", "intp0": "INTP0"}[kind]
    for h in (2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 32):
        for d in range(tick(60), tick(64), 2):
            pre = nmi_pre() if kind == "nmi" else p0_pre()
            v.append(run(f"w-{kind}-h{h}-d{d}", pre, NOPS, pulse(pin, d, h), HND))
    return v


def widths_int():
    """INT high for h ticks. A pulse that is not taken leaves the port set-up to the body's
    own copy of the hand-back sequence (gen_r15's tail_code), so every run restores R2."""
    v = []
    for h in (4, 8, 12, 16, 24):
        for d in range(tick(66), tick(76), 4):
            st = dict(INT_STIM, entries=[{"event": 1, "delay": d, "hold": h, "levels": {"INT": 1}}])
            v.append(run(f"w-int-h{h}-d{d}", int_pre(), NOPS + [tail_code() + [0xBA, 0x20, 0x00]], st, handler()))
    return v


def flag():
    v = []
    pre = vec(0x60) + DS1F + [sfr_b(0x4C, 0x47)] + event_tail(ei=False)
    body = [[0x26, 0xA0, 0x4C, 0xFF], [0x88, 0x07]] * 5
    for d in range(tick(52), tick(100), 4):
        v.append(run(f"g-flag-intp0-d{d}", pre, body, pulse("INTP0", d), HND))
    return v


def halt():
    v = []
    for d in range(tick(90), tick(94), 2):
        v.append(run(f"h-fine-nmi-d{d}", nmi_pre(), [NOP, [0xF4]], pulse("NMI", d), HND))
        st = dict(INT_STIM, entries=[{"event": 1, "delay": d, "hold": 0, "levels": {"INT": 1}}])
        v.append(run(f"h-fine-int-d{d}", int_pre(), [NOP, [0xF4]], st, handler()))
    return v


MI = {"addiw16": [0x81, 0x87, 0x10, 0x02, 0x34, 0x12], "addiwx": [0x81, 0x06, 0x00, 0x0C, 0x34, 0x12],
      "addiw8": [0x81, 0x47, 0x10, 0x34, 0x12], "cmpiw16": [0x81, 0xBF, 0x10, 0x02, 0x34, 0x12],
      "cmpiwx": [0x81, 0x3E, 0x00, 0x0C, 0x34, 0x12], "addi816": [0x83, 0x87, 0x10, 0x02, 0x01]}


def round17b():
    """The 81 / 83 group on memory with a displacement (the corpus's add_m_imm_d16 and the
    F22 d16 / direct forms had no probe of their own: the RTL cells are by analogy)."""
    v = []
    for name, code in MI.items():
        for pn, pc in (("i", [0x43]), ("c", [0x98]), ("n", NOP), ("k", CLC)):
            v.append((f"ml-{name}-{pn}", [q(pc, "prev"), q(code, name)]))
        v += probe(f"mi-{name}", code)
    return v


def flag2():
    """The flag read again with a CBW in each group (25 clocks a group: successive reads fall on
    both positions of a 2-clock lattice), the edge to 140; and two controls where the load reads
    RAM (0C00h, DS1 = 0), which shows the read cycle's clock on the pins."""
    v = []
    pre = vec(0x60) + DS1F + [sfr_b(0x4C, 0x47)] + event_tail(ei=False)
    grp = [[0x26, 0xA0, 0x4C, 0xFF], [0x88, 0x07], [0x98]]
    for d in range(tick(76), tick(140), 4):
        v.append(run(f"g-flagc-intp0-d{d}", pre, grp * 5, pulse("INTP0", d), HND))
    prc = vec(0x60) + DS1F + [sfr_b(0x4C, 0x47)] + DS1Z + event_tail(ei=False)
    ctl = [[0x26, 0xA0, 0x00, 0x0C], [0x88, 0x07]]
    v.append(run(f"g-ctl-intp0-d{tick(60)}", prc, ctl * 5, pulse("INTP0", tick(60)), HND))
    v.append(run(f"g-ctlc-intp0-d{tick(60)}", prc, (ctl + [[0x98]]) * 5, pulse("INTP0", tick(60)), HND))
    return v


INCS = [[0x40]] * 30


def incs():
    """INT, NMI and INTP0 across a train of INC AW (2 clocks an instruction): where each
    source's request reaches the EU, to the instruction."""
    v = []
    for d in range(tick(66), tick(90), 4):
        v.append(run(f"i-inc-nmi-d{d}", nmi_pre(), INCS, pulse("NMI", d), HND))
        st = dict(INT_STIM, entries=[{"event": 1, "delay": d, "hold": 0, "levels": {"INT": 1}}])
        v.append(run(f"i-inc-int-d{d}", int_pre(), INCS, st, handler()))
    for lo, hi in ((69, 75), (85.5, 90)):
        for d in range(tick(lo), tick(hi), 2):
            v.append(run(f"i-inc-intp0-d{d}", p0_pre(), INCS, pulse("INTP0", d), HND))
    return v


def round17d():
    """CVTBD behind five predecessors, followed by a long shift (two shapes fit round 15's 24 runs)."""
    from .gen import SLOW
    v = []
    for pn, pcs in (("i", [[0x43]]), ("c", [[0x98]]), ("n", [NOP]), ("k", [CLC]), ("nn", [NOP, NOP]),
                    ("kk", [CLC, CLC]), ("r", [[0xBB, 0x34, 0x12]])):
        v.append((f"cv-cvtbd-{pn}", [q(c, "prev") for c in pcs] + [q([0xD4, 0x0A], "cvtbd"), q(SLOW, "slow")]))
    return v


def cbws():
    """INT, NMI and INTP0 across a train of CBW (3 clocks an instruction): the thresholds step by
    3 if the EU's sample is made every clock, by 2 and 4 if it is made on the divided clock."""
    tr = [[0x98]] * 24
    v = []
    for d in range(tick(66), tick(90), 4):
        v.append(run(f"i-cbw-nmi-d{d}", nmi_pre(), tr, pulse("NMI", d), HND))
        st = dict(INT_STIM, entries=[{"event": 1, "delay": d, "hold": 0, "levels": {"INT": 1}}])
        v.append(run(f"i-cbw-int-d{d}", int_pre(), tr, st, handler()))
    for lo, hi in ((69, 75), (85.5, 90)):
        for d in range(tick(lo), tick(hi), 2):
            v.append(run(f"i-cbw-intp0-d{d}", p0_pre(), tr, pulse("INTP0", d), HND))
    return v


def int_latch():
    """Is a short INT pulse remembered? IE = 0 while INT is high for 2 / 3 / 8 clocks; EI about
    25 clocks after the pulse has gone; and the level held (hold 0) as the control."""
    from .gen_r14 import EI
    v = []
    body = [NOP] * 8 + [EI] + [NOP] * 12 + [tail_code() + [0xBA, 0x20, 0x00]]
    for h in (16, 24, 64, 0):
        for d in (tick(70), tick(70.5)):
            st = dict(INT_STIM, entries=[{"event": 1, "delay": d, "hold": h, "levels": {"INT": 1}}])
            v.append(run(f"k-intlatch-h{h}-d{d}", int_pre(ei=False), body, st, handler()))
    return v


ROUNDS = {"r17a": round17a, "r17b": round17b, "r17d": round17d, "r17r": cbws, "r17s": int_latch, "r17g": flag2, "r17q": incs,
          "r17n": lambda: fine("nmi", 68, 80), "r17p": lambda: fine("intp0", 69, 75) + fine("intp0", 85.5, 90),
          "r17i": lambda: fine("int", 66, 76),
          "r17nr": lambda: fine("nmi", 68, 80, rising=True),
          "r17pr": lambda: fine("intp0", 69, 75, rising=True) + fine("intp0", 85.5, 90, rising=True),
          "r17wn": lambda: widths("nmi"), "r17wp": lambda: widths("intp0"), "r17wi": widths_int,
          "r17f": flag, "r17h": halt}
