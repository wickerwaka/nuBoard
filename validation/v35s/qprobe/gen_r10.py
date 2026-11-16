"""Round 10: the three neighbour effects of the corpus cross-tab, one variable each, the
long-shift frame as the control.

ia-P-k    INC word [BW] behind predecessor P (k NOPs between): a stack write, a plain store,
          an accumulator store, a stack read, a load, an OUT imm8, nothing (the long shift)
ib-X-P    X = SHL AW,1 / TEST r,r / INC r8 (each has a bus-idle word) behind P: OUT imm8,
          OUT DW, IN imm8, PUSH, a store, a load, nothing
ic-P-B    branch B (JZ taken, JNZ not taken, DBNZ taken / not taken) behind P: nothing, two
          NOPs, CMP AW,AW, MOV CW,imm16, MOV r,r

Round 10b (follow-ups after the first reading):
id-P-B    the branches behind a wider set of predecessors
ie-*      DBNZ not taken (CW = 1) and JCXZ taken (CW = 0) / not taken behind a few
ip-*      the corpus's own inc_m chain: the PUSH marker behind INC word [BW] and behind the
          other routines that end in a write
"""

from .gen import M1I, M1P, NOP, RR, q, train

OUT22 = [0xE6, 0x22]


def round10():
    v = []
    incm = [0xFF, 0x07]
    preds = {"push": [[0x50]], "st": [[0x89, 0x07]], "sta": [[0xA3, 0x00, 0x0C]],
             "pop": [[0x50], [0x58]], "ld": [[0x8B, 0x07]], "o8": [OUT22], "ls": []}
    for name, codes in preds.items():
        for k in (0, 1):
            v.append((f"ia-{name}-{k}", [q(c, "pred") for c in codes] + train(NOP, "nop", k)
                      + [q(incm, "incm")]))
    xs = {"shl1": [0xD1, 0xE0], "test": [0x84, 0xC3], "incb": [0xFE, 0xC3]}
    bpred = {"o8": ([OUT22], None), "odw": ([[0xBA, 0x22, 0x00], [0xEE]], M1I),
             "in8": ([[0xE4, 0x40]], None), "push": ([[0x50]], None),
             "st": ([[0x89, 0x07]], None), "ld": ([[0x8B, 0x07]], None), "ls": ([], None)}
    for xn, xc in xs.items():
        for pn, (codes, m1) in bpred.items():
            body = [q(c, "pred") for c in codes] + [q(xc, xn)]
            v.append((f"ib-{xn}-{pn}", body if m1 is None else (body, m1)))
    cpred = {"ls": [], "nop2": [NOP, NOP], "cmp": [[0x3B, 0xC0]], "movcw": [[0xB9, 0x02, 0x00]],
             "rr": [RR]}
    brs = {"jz": [0x74, 0x00], "jnz": [0x75, 0x00], "dbnz": [0xE2, 0x00]}
    for pn, codes in cpred.items():
        for bn, bc in brs.items():
            v.append((f"ic-{pn}-{bn}", [q(c, "pred") for c in codes] + [q(bc, bn), q(NOP, "nop")]))
    v.append(("ic-movcw1-dbnz", [q([0xB9, 0x01, 0x00], "pred"), q([0xE2, 0x00], "dbnz"),
                                 q(NOP, "nop")]))
    return v


def round10b():
    v = []
    preds = {"nop1": [NOP], "nop3": [NOP] * 3, "inc": [[0x43]], "cbw": [[0x98]], "clc": [[0xF8]],
             "ri8": [[0xB3, 0x00]], "addi": [[0x05, 0x00, 0x00]], "shl1": [[0xD1, 0xE0]],
             "test": [[0x84, 0xC3]], "push": [[0x50]], "st": [[0x89, 0x07]], "ld": [[0x8B, 0x07]],
             "o8": [OUT22]}
    brs = {"jz": [0x74, 0x00], "jnz": [0x75, 0x00], "dbnz": [0xE2, 0x00]}
    for pn, codes in preds.items():
        for bn, bc in brs.items():
            v.append((f"id-{pn}-{bn}", [q(c, "pred") for c in codes] + [q(bc, bn), q(NOP, "nop")]))
    v.append(("id-dbnz-dbnz", [q([0xE2, 0x00], "dbnz"), q([0xE2, 0x00], "dbnz"), q(NOP, "nop")]))
    mid = {"nop": [NOP], "nop2": [NOP, NOP], "rr": [RR], "cmp": [[0x3B, 0xC0]]}
    for mn, codes in mid.items():
        m = [q(c, "mid") for c in codes]
        v.append((f"ie-nt-{mn}", [q([0xB9, 0x01, 0x00], "pred")] + m
                  + [q([0xE2, 0x00], "dbnz"), q(NOP, "nop")]))
        v.append((f"ie-cxz-{mn}", [q([0xB9, 0x00, 0x00], "pred")] + m
                  + [q([0xE3, 0x00], "jcxz"), q(NOP, "nop")]))
        v.append((f"ie-cxn-{mn}", m + [q([0xE3, 0x00], "jcxz"), q(NOP, "nop")]))
    v.append(("ie-cxz", [q([0xB9, 0x00, 0x00], "pred"), q([0xE3, 0x00], "jcxz"), q(NOP, "nop")]))
    incm = [0xFF, 0x07]
    ip = {"incm": [incm], "push-incm": [[0x50], incm], "st": [[0x89, 0x07]],
          "st-incm": [[0x89, 0x07], incm], "nop-incm": [NOP, incm], "incm-nop": [incm, NOP],
          "incm-incm": [incm, incm], "push": [[0x50]], "xchm": [[0x87, 0x07]],
          "addm": [[0x01, 0x07]]}
    for n, codes in ip.items():
        v.append((f"ip-{n}", ([q(c, "x") for c in codes], M1P)))
    return v


ROUNDS = {"r10": round10, "r10b": round10b}
