"""Round 20.

r20a  the corpus forms that had no probe of their own (TEST [d16],AW, TEST [BW+d16],AW, TEST word
      [BW+d16],imm16, POP [BW+IX+d16]) and NEG per EA mode, in the lead frame and as the four
      probe programs
r20b  the "second instance" family: ADD mem,imm with a displacement behind predecessors that
      leave four or five bytes held; EXT / INS r,imm4 behind two short instructions; CVTBD
      behind three-byte instructions; SET1 behind bus cycles; SHL r,imm8; OUTM in a row
r20l  LEA with d16 / direct against PUSH, OUT imm8 and OUT DW neighbours and both markers
r20t  a transfer at a flush target (its displacement word under a fetch of the new stream):
      JMP short (the control), JMP near, CALL near, JMP far, CALL far
"""

from .gen import BODY_AT, M1I, M1P, NOP, RI, RR, SLOW, q
from .gen_r8 import w16
from .gen_r9 import probe
from .gen_r11 import with_regs

CLC, CBW, INC, PUSH, OUT22 = [0xF8], [0x98], [0x43], [0x50], [0xE6, 0x22]
LEADS = (("i", INC), ("c", CBW), ("n", NOP), ("k", CLC))


def leads(tag, name, code, pre=()):
    p = [q(c, "setup") for c in pre]
    return [(f"{tag}-{name}-{pn}", p + [q(pc, "prev"), q(code, name)]) for pn, pc in LEADS]


FA = {"testd": [0x85, 0x06, 0x00, 0x0C], "testbwd16": [0x85, 0x87, 0x10, 0x02],
      "testi16": [0xF7, 0x87, 0x10, 0x02, 0x34, 0x12], "testi8": [0xF7, 0x47, 0x10, 0x34, 0x12],
      "testix": [0xF7, 0x06, 0x00, 0x0C, 0x34, 0x12],
      "negd16": [0xF7, 0x9F, 0x10, 0x02], "negd8": [0xF7, 0x5F, 0x10], "negdir": [0xF7, 0x1E, 0x00, 0x0C],
      "negbw": [0xF7, 0x1F], "notd16": [0xF7, 0x97, 0x10, 0x02], "incd16": [0xFF, 0x87, 0x10, 0x02]}
POPS = {"popx16": [0x8F, 0x80, 0x10, 0x02], "popd16": [0x8F, 0x87, 0x10, 0x02], "popx8": [0x8F, 0x40, 0x10]}


def round20a():
    v = []
    for name, code in FA.items():
        v += leads("fl", name, code)
        if name != "negd16":
            v += probe(f"f-{name}", code)
    for name, code in POPS.items():
        v += leads("fl", name, code, pre=[PUSH])
        v += probe(f"f-{name}", code, pre=[PUSH, PUSH])
    for pn, pcs in (("ri", [RI]), ("rr", [RR]), ("nn", [NOP, NOP]), ("ii", [INC, INC]), ("o", [OUT22])):
        v.append((f"fp-negd16-{pn}", [q(c, "prev") for c in pcs] + [q(FA["negd16"], "negd16")]))
    return v


MI = {"addi8x": [0x83, 0x06, 0x00, 0x0C, 0x01], "addi816": [0x83, 0x87, 0x10, 0x02, 0x01],
      "addiw16": [0x81, 0x87, 0x10, 0x02, 0x34, 0x12], "addiwx": [0x81, 0x06, 0x00, 0x0C, 0x34, 0x12]}
P2 = {"ri": [RI], "rr": [RR], "mi8": [[0xB3, 0x00]], "nn": [NOP, NOP], "ii": [INC, INC],
      "ni": [NOP, INC], "p": [PUSH], "nx": None, "3": None, "xn": None}
EXI = {"exti": [0x0F, 0x3B, 0xC3, 0x07], "insi": [0x0F, 0x39, 0xC3, 0x07], "ext": [0x0F, 0x33, 0xC3]}
PE = {"ii": [INC, INC], "ni": [NOP, INC], "kn": [CLC, NOP], "in": [INC, NOP], "nnn": [NOP] * 3,
      "nnnn": [NOP] * 4, "rn": [RR, NOP], "kkk": [CLC] * 3}
PC = {"ri": [RI], "rc": [[0xB9, 0x34, 0x12]], "ai": [[0x05, 0x00, 0x00]], "m8": [[0xB3, 0x00]],
      "a83": [[0x83, 0xC3, 0x00]], "rr": [RR], "rin": [RI, NOP], "nri": [NOP, RI], "rii": [RI, INC]}
S1W, S1B, T1W = [0x0F, 0x15, 0xC0], [0x0F, 0x14, 0xC0], [0x0F, 0x11, 0xC0]
PS1 = {"o": [OUT22], "ow": [[0xE7, 0x22]], "p": [PUSH], "st": [[0xA3, 0x00, 0x0C]], "in": [[0xE4, 0x40]],
       "on": [OUT22, NOP], "no": [NOP, OUT22], "oo": [OUT22, OUT22], "ld": [[0xA1, 0x00, 0x0C]]}


def round20b():
    v = []
    for name, code in MI.items():
        x = lambda: q(code, name)
        for pn, pcs in P2.items():
            if pn == "nx":
                body = [q(NOP, "nop"), x(), x()]
            elif pn == "3":
                body = [x(), x(), x()]
            elif pn == "xn":
                body = [x(), q(NOP, "nop"), x()]
            else:
                body = [q(c, "prev") for c in pcs] + [x()]
            if (name, pn) not in (("addi8x", "3"), ("addi8x", "xn")):
                v.append((f"m-{name}-{pn}", body))
    for name, code in EXI.items():
        for pn, pcs in PE.items():
            v.append((f"e-{name}-{pn}", [q(c, "prev") for c in pcs] + [q(code, name), q(SLOW, "slow")]))
    for pn, pcs in PC.items():
        v.append((f"c-cvtbd-{pn}", [q(c, "prev") for c in pcs] + [q([0xD4, 0x0A], "cvtbd"), q(SLOW, "slow")]))
    for pn, pcs in PS1.items():
        v.append((f"s-s1w-{pn}", [q(c, "prev") for c in pcs] + [q(S1W, "s1w")]))
    v.append(("s-s1b-o", [q(OUT22, "prev"), q(S1B, "s1b")]))
    v.append(("s-t1w-o", [q(OUT22, "prev"), q(T1W, "t1w")]))
    v.append(("s-s1w3-o", [q([0xB1, 0x03], "mov_cl"), q(OUT22, "prev"), q(S1W, "s1w")]))
    v.append(("s-s1wi-o", [q(OUT22, "prev"), q([0x0F, 0x1D, 0xC0, 0x03], "s1wi")]))
    for n in (1, 4, 8):
        sh = [0xC1, 0xE0, n]
        for pn, pcs in (("i", [INC]), ("c", [CBW]), ("k", [CLC]), ("nn", [NOP, NOP])):
            v.append((f"h-shli{n}-{pn}", [q(c, "prev") for c in pcs] + [q(sh, "shli"), q(SLOW, "slow")]))
        v.append((f"h-shli{n}-xn", [q(sh, "shli"), q(NOP, "nop"), q(SLOW, "slow")]))
        v.append((f"h-shli{n}-mi", ([q(sh, "shli")], M1I)))
        v.append((f"h-shli{n}-nmi", ([q(NOP, "nop"), q(sh, "shli")], M1I)))
        v.append((f"h-shli{n}-mp", ([q(sh, "shli")], M1P)))
        v.append((f"h-shli{n}-nmp", ([q(NOP, "nop"), q(sh, "shli")], M1P)))
    om = []
    for name, op in (("outmb", 0x6E), ("outmw", 0x6F)):
        x = lambda: q([op], name)
        om += [(f"o-{name}-3", [x(), x(), x()]), (f"o-{name}-nx", [q(NOP, "nop"), x(), x()]),
               (f"o-{name}-xn", [x(), q(NOP, "nop"), x()]), (f"o-{name}-ix", [q(INC, "inc"), x(), x()]),
               (f"o-{name}-xs", [x(), x(), q(SLOW, "slow")])]
    v += with_regs(om, {"DW": 0x0022}, M1I)
    return v


LEA = {"bwd16": [0x8D, 0x87, 0x10, 0x02], "dir": [0x8D, 0x06, 0x00, 0x0C], "bpd16": [0x8D, 0x86, 0x10, 0x02],
       "bwd8": [0x8D, 0x47, 0x10]}


def round20l():
    v = []
    for name, code in LEA.items():
        x = lambda: q(code, "lea_" + name)
        n = lambda: q(NOP, "nop")
        for mn, m1 in (("mp", M1P), ("mi", M1I), ("md", None)):
            v.append((f"l-{name}-a-{mn}", ([x()], m1)))
            v.append((f"l-{name}-nb-{mn}", ([n(), x()], m1)))
            v.append((f"l-{name}-na-{mn}", ([x(), n()], m1)))
            v.append((f"l-{name}-pb-{mn}", ([q(PUSH, "push"), x()], m1)))
            v.append((f"l-{name}-ob-{mn}", ([q(OUT22, "out22"), x()], m1)))
            v.append((f"l-{name}-onb-{mn}", ([q(OUT22, "out22"), n(), x()], m1)))
            v.append((f"l-{name}-pnb-{mn}", ([q(PUSH, "push"), n(), x()], m1)))
            v.append((f"l-{name}-pa-{mn}", ([x(), q(PUSH, "push")], m1)))
            v.append((f"l-{name}-2-{mn}", ([x(), x()], m1)))
    return v


def round20t():
    """X at a flush target. `a` = the body's offset in PS; far targets are computed from it."""
    v = []
    J0, J1 = [0xEB, 0x00], [0xEB, 0x01]

    def tx(kind, a):
        """The transfer at offset a, to the byte behind itself."""
        if kind == "js":
            return [0xEB, 0x00]
        if kind == "jn":
            return [0xE9, 0x00, 0x00]
        if kind == "cn":
            return [0xE8, 0x00, 0x00]
        if kind == "jf":
            return [0xEA] + w16(a + 5) + [0x00, 0x10]
        return [0x9A] + w16(a + 5) + [0x00, 0x10]

    lead = {"j0": [J0], "j1": [J1, NOP], "oj0": [OUT22, J0], "j0n": [J0, NOP], "nj0": [NOP, J0],
            "j0nn": [J0, NOP, NOP], "0": [], "n": [NOP]}
    for kind in ("js", "jn", "cn", "jf", "cf"):
        for ln, pcs in lead.items():
            def body(parity, kind=kind, pcs=pcs):
                a = BODY_AT[parity] + sum(len(c) for c in pcs)
                return [q(c, "lead") for c in pcs] + [q(tx(kind, a), kind), q(NOP, "nop")]
            v.append((f"t-{kind}-{ln}", body))

        def twice(parity, kind=kind):
            a = BODY_AT[parity]
            c1 = tx(kind, a)
            return [q(c1, kind), q(tx(kind, a + len(c1)), kind), q(NOP, "nop")]
        v.append((f"t-{kind}-2", twice))
    return v


ROUNDS = {"r20a": round20a, "r20b": round20b, "r20l": round20l, "r20t": round20t}


# ---- interrupts: NMI's event words in DIVU, the strings and REP (the edge stepped across the
# train, as round 19's nsweep), and INT / NMI stepped across the entry into HALT.
from .gen_r15 import HND, INT_STIM, handler, int_pre, run
from .gen_r17 import nmi_pre, pulse
from .gen_r18 import edge, tickw

SIX, SIY = [0xBE, 0x00, 0x0C], [0xBF, 0x00, 0x0D]
NT20 = {"div8": ([NOP] * 3 + [[0xF6, 0xF7]] + [NOP] * 10, (76, 126, 4)),
        "movs": ([SIX, SIY] + [[0xA4]] * 10, (88, 124, 4)),
        "stos": ([SIY] + [[0xAA]] * 12, (84, 114, 4)),
        "lods": ([SIX] + [[0xAC]] * 12, (84, 114, 4)),
        "rmovs": ([SIX, SIY, [0xB9, 0x06, 0x00], [0xF3, 0xA4]] + [NOP] * 10, (88, 168, 8)),
        "rstos": ([SIY, [0xB9, 0x08, 0x00], [0xF3, 0xAA]] + [NOP] * 10, (84, 150, 8)),
        "rlods": ([SIX, [0xB9, 0x08, 0x00], [0xF3, 0xAC]] + [NOP] * 10, (84, 150, 8)),
        "divs": ([NOP] * 3 + [[0xF6, 0xFF]] + [NOP] * 10, (76, 144, 8))}


def nsweep20(train):
    body, (lo, hi, step) = NT20[train]
    v = []
    for d in list(range(tickw(lo, 0), tickw(hi, 0), step)) + [2000]:
        pre, st, post = edge("nmi", d)
        v.append(run(f"n-{train}0-nmi-d{d}", pre, body, st, post, 0))
    return v


def halt20():
    v = []
    for kind in ("int", "nmi"):
        for d in list(range(tickw(74, 0), tickw(104, 0), 4)):
            pre, st, post = edge(kind, d)
            v.append(run(f"h-halt-{kind}-d{d}", pre, [NOP] * 4 + [[0xF4]], st, post, 0))
    return v


ROUNDS.update({f"r20n{t}": (lambda t=t: nsweep20(t)) for t in NT20})
ROUNDS["r20h"] = halt20
