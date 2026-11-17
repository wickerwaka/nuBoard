"""Round 16.

r16a  forms
  ph-<pred>-<form>   the 0F page against the fetch's phase: pred ; X ; SHL AW,CL with six
                     predecessors (the fetch that pred's pops start is at a different clock of X
                     in each), X = TEST1 r,CL / TEST1 r,imm / ROL4 r / TEST1 m,CL / TEST1 m,imm /
                     SET1 m,imm / EXT r,r / EXT r,imm
  xd-<form>-{a,s,2,n} EXT / INS with the count in DH or BH (the corpus forms): DW = 0608h, so X ; X
                     runs the same length twice (the round-9 probes had the count in AL, which
                     EXT itself reloads); marker OUT imm8
  mq-<form>-{a,s,n}  MUL / DIV on memory with the operand stored before M0 (round 12's frame had
                     MOV [BW],imm16 ; MOV AW,imm16 in the body, whose fetch the model misses at
                     even alignment with waits)
  i3 / bk / cm / jm -<pred>-<n>   INT 3, BRK 40h, CALL [0C00h], JMP [0C00h] with the vector or the
                     pointer stored before M0, behind nothing / NOP / CLC / NOP NOP, n NOPs at
                     the target
  la-*               LAHF behind CLC, behind two NOPs, three times
  a3-*               ADD [d16],imm8 three times, and twice with a NOP between
r16e  the two EI outliers of round 14 (level 0 with 6 CLCs at even alignment, level 5 with 10
      CLCs at odd alignment) at all three waits, and with INC BW in place of the CLCs
"""

from .gen import BODY_AT, M1I, NOP, RR, SLOW, q, train
from .gen_r8 import w16
from .gen_r9 import probe
from .gen_r14 import EI, sw

CLC = [0xF8]
PREDS = {"n": [NOP], "c": [CLC], "cc": [CLC, CLC], "nc": [NOP, CLC], "nn": [NOP, NOP], "r": [RR]}
PH = {"t1cl": [0x0F, 0x10, 0xC0], "t1i": [0x0F, 0x18, 0xC0, 0x03], "rol4": [0x0F, 0x28, 0xC0],
      "t1mcl": [0x0F, 0x10, 0x07], "t1mi": [0x0F, 0x18, 0x07, 0x03],
      "s1mi": [0x0F, 0x1C, 0x07, 0x03], "ext": [0x0F, 0x33, 0xC3], "exti": [0x0F, 0x3B, 0xC3, 0x07]}
XD = {"ext-bl-dh": [0x0F, 0x33, 0xF3], "ext-dl-dh": [0x0F, 0x33, 0xF2],
      "ext-dl-bh": [0x0F, 0x33, 0xFA], "ins-bl-dh": [0x0F, 0x31, 0xF3],
      "ins-dl-bh": [0x0F, 0x31, 0xFA]}
MQ = {"mulub": [0xF6, 0x27], "muluw": [0xF7, 0x27], "mulb": [0xF6, 0x2F], "mulw": [0xF7, 0x2F],
      "divub": [0xF6, 0x37], "divuw": [0xF7, 0x37], "divb": [0xF6, 0x3F], "divw": [0xF7, 0x3F]}


def with_pre(fn, pre_len):
    return lambda parity: fn(BODY_AT[parity] + pre_len)


def round16a():
    v = []
    for pn, pred in PREDS.items():
        for fn, code in PH.items():
            v.append((f"ph-{pn}-{fn}", [q(c, "pred") for c in pred] + [q(code, fn), q(SLOW, "slow")]))
    for name, code in XD.items():
        for n, (b, m1) in probe(f"xd-{name}", code, m1=M1I):
            v.append((n, (b, m1, {"DW": 0x0608})))
    for name, code in MQ.items():
        ex = {"DW": 0x0000, "_pre": [q([0xC7, 0x07, 0x03, 0x00], "st_imm")]}
        aw = lambda: q([0xB8, 0x05, 0x00], "mov_aw")
        x = lambda: q(code, name)
        v.append((f"mq-{name}-a", ([aw(), x()], M1I, ex)))
        v.append((f"mq-{name}-s", ([aw(), x(), q(SLOW, "slow")], M1I, ex)))
        v.append((f"mq-{name}-n", ([aw(), q(NOP, "nop"), x(), q(SLOW, "slow")], M1I, ex)))
    vec = lambda a, at: [q([0xC7, 0x06, at & 0xFF, at >> 8] + w16(a), "vec_ip"),
                         q([0xC7, 0x06, (at + 2) & 0xFF, (at + 2) >> 8, 0x00, 0x10], "vec_ps")]
    pads = {"0": [], "n": [NOP], "c": [CLC], "nn": [NOP, NOP]}
    xs = {"i3": ([0xCC], 0x0C), "bk": ([0xCD, 0x40], 0x100), "cm": ([0xFF, 0x16, 0x00, 0x0C], 0xC00),
          "jm": ([0xFF, 0x26, 0x00, 0x0C], 0xC00)}
    for xn, (code, at) in xs.items():
        for pn, pad in pads.items():
            for n in (0, 1):
                t = train(NOP, "nop", n)
                v.append((f"{xn}-{pn}-{n}", with_pre(lambda a, t=t, pad=pad, code=code, at=at, xn=xn: (
                    [q(c, "pad") for c in pad] + [q(code, xn)] + t, None,
                    {"_pre": vec(a + len(pad) + len(code), at)}), 12)))
    lahf = lambda: q([0x9F], "lahf")
    v.append(("la-c", [q(CLC, "clc"), lahf(), q(SLOW, "slow")]))
    v.append(("la-nn", [q(NOP, "nop"), q(NOP, "nop"), lahf(), q(SLOW, "slow")]))
    v.append(("la-3", [lahf(), lahf(), lahf()]))
    add = lambda: q([0x83, 0x06, 0x00, 0x0C, 0x01], "addi8x")
    v.append(("a3-3", [add(), add(), add()]))
    v.append(("a3-n", [add(), q(NOP, "nop"), add()]))
    return v


def round16e():
    v = []
    for lv, k in ((0, 6), (5, 10)):
        req = [("p0", 0x80 | lv, 1)]
        v.append(sw(f"sw-lv{lv}pad{k}-nop", req, [CLC] * k + [EI] + [NOP] * 14))
        v.append(sw(f"sw-lv{lv}inc{k}-nop", req, [[0x43]] * k + [EI] + [NOP] * 14, waits=(0,)))
    return v


ROUNDS = {"r16a": round16a, "r16e": round16e}
