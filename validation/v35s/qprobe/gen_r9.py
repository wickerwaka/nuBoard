"""Round 9. Every new routine X is measured four ways (probe()):

    X-a   LS ; X ; M1                 its start known (behind the long shift)
    X-s   LS ; X ; SHL AW,CL ; M1     its tail exposed (a long shift behind it: idle bus)
    X-2   LS ; X ; X ; M1             against itself
    X-n   LS ; NOP ; X ; SHL ; M1     the other queue phase

c40-*  the corpus frame of the 40 lost runs: OUT imm8 ; X ; follower, X = ADD [BW],AW or
       MOV [BW],AW (and the d8 forms), follower = OUT imm8 (the corpus marker), OUT DW, NOP,
       a long shift.
"""

from .gen import INC, M1I, NOP, RI, RR, SLOW, q, train

OUT22 = [0xE6, 0x22]


def probe(name, code, pre=(), m1=None):
    """The four programs of one routine; `pre` instructions set its operands up first."""
    p = [q(c, "setup") for c in pre]
    x = lambda: q(code, name)
    out = [(f"{name}-a", p + [x()]), (f"{name}-s", p + [x(), q(SLOW, "slow")]),
           (f"{name}-2", p + [x(), x()]), (f"{name}-n", p + [q(NOP, "nop"), x(), q(SLOW, "slow")])]
    if m1 is not None:
        out = [(n, (b, m1)) for n, b in out]
    return out


def lost40():
    v = []
    forms = {"add": [0x01, 0x07], "st": [0x89, 0x07], "add8": [0x01, 0x47, 0x10],
             "st8": [0x89, 0x47, 0x10]}
    for name, code in forms.items():
        x = lambda: q(code, name)
        v.append((f"c40-{name}-oo", ([q(OUT22, "out22"), x()], M1I)))      # the corpus frame
        v.append((f"c40-{name}-od", [q(OUT22, "out22"), x()]))             # follower OUT DW
        v.append((f"c40-{name}-on", ([q(OUT22, "out22"), x(), q(NOP, "nop")], M1I)))
        v.append((f"c40-{name}-os", [q(OUT22, "out22"), x(), q(SLOW, "slow")]))
        v.append((f"c40-{name}-lo", ([x()], M1I)))                         # behind the long shift
        v.append((f"c40-{name}-no", ([q(NOP, "nop"), x()], M1I)))
        v.append((f"c40-{name}-ono", ([q(OUT22, "out22"), q(NOP, "nop"), x()], M1I)))
    return v


def memory():
    v = []
    forms = {
        # ALU memory,imm and compare / test
        "addi8": [0x83, 0x07, 0x01], "addi16": [0x81, 0x07, 0x34, 0x12],
        "addi8d": [0x83, 0x47, 0x10, 0x01], "addi8x": [0x83, 0x06, 0x00, 0x0C, 0x01],
        "cmpi8": [0x83, 0x3F, 0x01], "testi": [0xF7, 0x07, 0x34, 0x12],
        "testm": [0x85, 0x07], "xchm": [0x87, 0x07],
        # store immediate in the other modes, and the byte form
        "stid8": [0xC7, 0x47, 0x10, 0x34, 0x12], "stix": [0xC7, 0x06, 0x00, 0x0C, 0x34, 0x12],
        "stib": [0xC6, 0x07, 0x12], "stibi": [0xC7, 0x00, 0x34, 0x12],
        "stid16": [0xC7, 0x87, 0x00, 0x02, 0x34, 0x12],
        # unary and shift on memory
        "notm": [0xF7, 0x17], "incmb": [0xFE, 0x07], "shlm1": [0xD1, 0x27], "decm": [0xFF, 0x0F],
        # PUSH / POP memory
        "pushm": [0xFF, 0x37], "pushm8": [0xFF, 0x77, 0x10], "pushmx": [0xFF, 0x36, 0x00, 0x0C],
    }
    for name, code in forms.items():
        v += probe(name, code)
    for name, code in {"popm": [0x8F, 0x07], "popm8": [0x8F, 0x47, 0x10],
                       "popmx": [0x8F, 0x06, 0x00, 0x0C]}.items():
        v += probe(name, code, pre=[[0x50], [0x50]])
    v += probe("pusha", [0x60])
    v += probe("popa", [0x61], pre=[[0x60], [0x60]], m1=M1I)      # POPA restores DW: keep imm8 M1
    v += probe("prep", [0xC8, 0x08, 0x00, 0x00])
    return v


def strings():
    v = []
    forms = {"movb": [0xA4], "movw": [0xA5], "cmpbk": [0xA6], "cmpm": [0xAE], "stmb": [0xAA],
             "stmw": [0xAB], "ldmb": [0xAC], "ldmw": [0xAD], "inm": [0x6C]}
    for name, code in forms.items():
        v += probe(name, code)
    for n in (0, 1, 2, 5):
        cw = [0xB9, n, 0x00]
        for name, code in {"rmovw": [0xF3, 0xA5], "rstmw": [0xF3, 0xAB], "rldmw": [0xF3, 0xAD],
                           "rcmpm": [0xF2, 0xAE], "rmovb": [0xF3, 0xA4]}.items():
            v.append((f"{name}{n}-a", [q(cw, "mov_cw"), q(code, name)]))
            v.append((f"{name}{n}-s", [q(cw, "mov_cw"), q(code, name), q(SLOW, "slow")]))
    return v


def page0f():
    v = []
    forms = {"t1cl": [0x0F, 0x10, 0xC0], "t1i": [0x0F, 0x18, 0xC0, 0x03],
             "s1cl": [0x0F, 0x14, 0xC0], "s1i": [0x0F, 0x1C, 0xC0, 0x03],
             "c1cl": [0x0F, 0x12, 0xC0], "n1cl": [0x0F, 0x16, 0xC0],
             "t1wcl": [0x0F, 0x11, 0xC0], "t1mcl": [0x0F, 0x10, 0x07],
             "s1mcl": [0x0F, 0x14, 0x07], "t1mi": [0x0F, 0x18, 0x07, 0x03],
             "rol4": [0x0F, 0x28, 0xC0], "ror4": [0x0F, 0x2A, 0xC0], "rol4m": [0x0F, 0x28, 0x07],
             "ext": [0x0F, 0x33, 0xC3], "ins": [0x0F, 0x31, 0xC3],
             "exti": [0x0F, 0x3B, 0xC3, 0x07], "insi": [0x0F, 0x39, 0xC3, 0x07]}
    for name, code in forms.items():
        v += probe(name, code)
    return v


def loops():
    v = []
    for c in (1, 2, 4, 8):
        v += probe(f"shli{c}", [0xC1, 0xE0, c])
    v += probe("shlbi4", [0xC0, 0xE0, 0x04])
    v += probe("sari4", [0xC1, 0xF8, 0x04])
    pairs = {"00": (0x00, 0x00), "ff": (0xFF, 0xFF), "5a": (0x55, 0xAA), "18": (0x01, 0x80)}
    for tag, (a, b) in pairs.items():
        pre = [[0xB0, a], [0xB3, b]]
        v += probe(f"mulu{tag}", [0xF6, 0xE3], pre=pre)[:2]
        v += probe(f"mul{tag}", [0xF6, 0xEB], pre=pre)[:2]
    for tag, (lo, hi, d) in {"a": (0x12, 0x00, 0x34), "b": (0xFF, 0x33, 0x34),
                             "c": (0x00, 0x00, 0x01)}.items():
        pre = [[0xB8, lo, hi], [0xB3, d]]
        v += probe(f"divu{tag}", [0xF6, 0xF3], pre=pre)[:2]
    v += probe("div", [0xF6, 0xFB], pre=[[0xB8, 0x12, 0x00], [0xB3, 0x34]])[:2]
    # the 16-bit forms change DW: the marker is OUT imm8
    v += probe("muluw", [0xF7, 0xE3], m1=M1I)[:2]
    v += probe("mulwi", [0x69, 0xC3, 0x34, 0x12], m1=M1I)[:2]
    v += probe("divuw", [0xF7, 0xF3], pre=[[0xB8, 0x34, 0x12]], m1=M1I)[:2]
    return v


def round9():
    return lost40() + memory() + strings() + page0f() + loops()


ROUNDS = {"r9": round9}
