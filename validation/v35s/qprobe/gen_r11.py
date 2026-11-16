"""Round 11.

r11a  a word operand at an odd address: BW = 0801h (load, store, ADD mem,r, INC mem; the byte
      load / store as the one-cycle control), SP = 0EFFh (PUSH, POP), each four ways
r11b  the write that falls due at a fetch's end: MOV mem,imm16 with d8 / d16 / direct, the byte
      form, POP mem with d8 / direct, behind seven pads (nothing, CLC, CLC CLC, NOP, NOP NOP,
      NOP NOP NOP, a segment prefix on the instruction itself); -a: M1 next, -s: a long shift next
r11c  strings: OUTM single (the others are in round 9), REP forms with CW = 1, 2, 3
r11d  MULU / MUL / DIVU / DIV on registers with fixed operands (no divide error possible)
"""

from .gen import M1I, NOP, SLOW, q
from .gen_r9 import probe

CLC = [0xF8]
SLOW_BP = [0xD3, 0xE5]          # SHL BP,CL: a long shift that leaves AW / BW / DW alone


def with_regs(progs, regs, m1=None):
    out = []
    for name, body in progs:
        if isinstance(body, tuple):
            out.append((name, (body[0], body[1], regs)))
        else:
            out.append((name, (body, m1, regs)))
    return out


def round11a():
    v = []
    forms = {"ld": [0x8B, 0x07], "st": [0x89, 0x07], "rmw": [0x01, 0x07], "incm": [0xFF, 0x07],
             "ldb": [0x8A, 0x07], "stb": [0x88, 0x07]}
    for name, code in forms.items():
        v += with_regs(probe(f"ob-{name}", code), {"BW": 0x0801})
    v += with_regs(probe("os-push", [0x50]), {"SP": 0x0EFF})
    v += with_regs(probe("os-pop", [0x58], pre=[[0x50], [0x50]]), {"SP": 0x0EFF})
    return v


def round11b():
    v = []
    forms = {"sd8": [0xC7, 0x47, 0x10, 0x34, 0x12], "sd16": [0xC7, 0x87, 0x00, 0x02, 0x34, 0x12],
             "sdir": [0xC7, 0x06, 0x00, 0x0C, 0x34, 0x12], "sb": [0xC6, 0x07, 0x12]}
    pops = {"pd8": [0x8F, 0x47, 0x10], "pdir": [0x8F, 0x06, 0x00, 0x0C]}
    pads = {"0": [], "c": [CLC], "cc": [CLC, CLC], "n": [NOP], "nn": [NOP, NOP],
            "nnn": [NOP, NOP, NOP]}
    for name, code in forms.items():
        for pn, pad in list(pads.items()) + [("x", None)]:
            x = q(code, name) if pad is not None else q([0x26] + code, name)
            p = [q(c, "pad") for c in (pad or [])]
            v.append((f"w-{name}-{pn}-a", p + [x]))
            v.append((f"w-{name}-{pn}-s", p + [x, q(SLOW, "slow")]))
    for name, code in pops.items():
        for pn, pad in list(pads.items()) + [("x", None)]:
            x = q(code, name) if pad is not None else q([0x26] + code, name)
            p = [q([0x50], "setup")] + [q(c, "pad") for c in (pad or [])]
            v.append((f"w-{name}-{pn}-a", p + [x]))
    return v


def round11c():
    v = []
    v += with_regs(probe("outmb", [0x6E]), {"DW": 0x0022}, M1I)
    v += with_regs(probe("outmw", [0x6F]), {"DW": 0x0022}, M1I)
    reps = {"rmovb": [0xF3, 0xA4], "rmovw": [0xF3, 0xA5], "rstmb": [0xF3, 0xAA],
            "rstmw": [0xF3, 0xAB], "rldmw": [0xF3, 0xAD], "rcmpm": [0xF2, 0xAE],
            "rcmpbk": [0xF3, 0xA6], "rinm": [0xF3, 0x6C]}
    for n in (1, 2, 3):
        cw = [0xB9, n, 0x00]
        for name, code in reps.items():
            v.append((f"{name}{n}-a", [q(cw, "mov_cw"), q(code, name)]))
            v.append((f"{name}{n}-s", [q(cw, "mov_cw"), q(code, name), q(SLOW, "slow")]))
            if n < 3:
                v.append((f"{name}{n}-n", [q(cw, "mov_cw"), q(NOP, "nop"), q(code, name),
                                           q(SLOW, "slow")]))
        v += with_regs([(f"routm{n}-a", [q(cw, "mov_cw"), q([0xF3, 0x6E], "routm")]),
                        (f"routm{n}-s", [q(cw, "mov_cw"), q([0xF3, 0x6E], "routm"),
                                         q(SLOW, "slow")])], {"DW": 0x0022}, M1I)
    return v


def _md(name, code, aw, bw, dw=None):
    setup = [q([0xB8, aw & 255, aw >> 8], "mov_aw"), q([0xBB, bw & 255, bw >> 8], "mov_bw")]
    if dw is not None:
        setup.append(q([0xBA, dw & 255, dw >> 8], "mov_dw"))
    setup.append(q(SLOW_BP, "slow"))
    return (name, (setup + [q(code, "x")], M1I))


def round11d():
    v = []
    mul = [(0, 0), (1, 1), (0xFFFF, 0xFFFF), (0x5555, 0xAAAA), (0xFFFF, 1), (1, 0xFFFF)]
    for i, (a, b) in enumerate(mul):
        v.append(_md(f"mulub-{i}", [0xF6, 0xE3], a, b))
        v.append(_md(f"muluw-{i}", [0xF7, 0xE3], a, b))
        v.append(_md(f"mulb-{i}", [0xF6, 0xEB], a, b))
        v.append(_md(f"mulw-{i}", [0xF7, 0xEB], a, b))
    # quotients that fit: no divide error
    divub = [(0, 1), (1, 1), (0x00FF, 0xFF), (0x5555, 0xAA), (0xFE01, 0xFF), (0x00AA, 0x55)]
    divb = [(0, 1), (1, 1), (0xFFFF, 0xFF), (0x0555, 0x55), (0xFFFF, 0x01), (0x007F, 0xFF)]
    divuw = [(0, 1), (1, 1), (0xFFFF, 0xFFFF), (0x5555, 0xAAAA), (0xFFFF, 1), (0xAAAA, 0x5555)]
    divw = [(0, 1), (1, 1), (0x7FFF, 0xFFFF), (0x5555, 0x00AA), (0x7FFF, 1), (0x2AAA, 0x5555)]
    for i in range(6):
        v.append(_md(f"divub-{i}", [0xF6, 0xF3], *divub[i]))
        v.append(_md(f"divb-{i}", [0xF6, 0xFB], *divb[i]))
        v.append(_md(f"divuw-{i}", [0xF7, 0xF3], *divuw[i], dw=0))
        v.append(_md(f"divw-{i}", [0xF7, 0xFB], *divw[i], dw=0))
    return v


ROUNDS = {"r11a": round11a, "r11b": round11b, "r11c": round11c, "r11d": round11d}
