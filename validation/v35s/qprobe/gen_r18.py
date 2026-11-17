"""Round 18: the EU side of interrupt recognition.

r18t<train><w>  INT and NMI side by side, the edge stepped half a clock at a time, across
      trains at W = 1 / 2 (nop, inc), a train with another fetch period (mov r8,imm8;
      mov r16,imm16), a train with a bus cycle per instruction (mov aw,[bw]), behind a long
      instruction (MULU BW; SHL AW,CL with CL = 31: a microcode loop), behind a jump (one
      JMP $+2 in a NOP train; a chain of them: the queue empty at every pop)
r18w  NMI low for 14 / 15 / 16 ticks at 16 eighth-clock positions (the schedule's resolution)
r18f  INTP0 unmasked, IE = 0: the request flag read and stored twice, EI, six more reads; the
      edge stepped a clock at a time (the flag and the scan's answer in one frame)
r18s  the request set by a store t clocks after EI (t by NOP / CBW / CLC pads), with a control
      whose store goes to RAM (the write cycle's clock on the pins)
"""

from .gen import NOP, SLOW, q
from .gen_r12 import K
from .gen_r14 import CLC, EI, sfr_b
from .gen_r15 import DS1F, HND, INT_STIM, event_tail, handler, int_pre, pad_even, run, vec
from .gen_r17 import DS1Z, nmi_pre, pulse

CBW, INC, JMP0 = [0x98], [0x43], [0xEB, 0x00]
MULU16, MOVI8, MOVI16, LD = [0xF7, 0xE3], [0xB3, 0x55], [0xBB, 0x34, 0x12], [0x8B, 0x07]
TRAINS = {"nop": [NOP] * 16, "inc": [INC] * 40, "cbw": [CBW] * 24, "mi8": [MOVI8] * 20,
          "mi16": [MOVI16] * 16, "ld": [LD] * 12,
          "mul": [NOP] * 3 + [MULU16] + [NOP] * 10, "shl": [NOP] * 3 + [list(SLOW)] + [NOP] * 10,
          "jmp": [NOP] * 3 + [JMP0] + [NOP] * 10, "jch": [NOP] + [JMP0] * 8 + [NOP] * 6,
          "mm": [INC, NOP, CBW, MOVI16, INC, INC, NOP, MOVI8, CBW, CBW, INC, NOP, MOVI16, INC,
                 CBW, NOP, NOP, INC, MOVI8, NOP, NOP, NOP]}


def tickw(e, w=0):
    return int(round(8 * (e + 15.5 + K[w] - 94)))


def edge(kind, d):
    if kind == "nmi":
        return nmi_pre(), pulse("NMI", d), HND
    return int_pre(), dict(INT_STIM, entries=[{"event": 1, "delay": d, "hold": 0,
                                               "levels": {"INT": 1}}]), handler()


def sweep(train, w, lo, hi, step=4, kinds=("int", "nmi")):
    v = []
    for kind in kinds:
        for d in list(range(tickw(lo, w), tickw(hi, w), step)) + ([2000] if lo < 100 else []):
            pre, st, post = edge(kind, d)
            v.append(run(f"t-{train}{w}-{kind}-d{d}", pre, TRAINS[train], st, post, w))
    return v


def widths():
    v = []
    for h in (14, 15, 16):
        for d in range(tickw(60), tickw(62), 1):
            v.append(run(f"w-nmi8-h{h}-d{d}", nmi_pre(), [NOP] * 14, pulse("NMI", d, h), HND))
    return v


RD = [[0x26, 0xA0, 0x4C, 0xFF], [0x88, 0x07]]


def flag_ei():
    v = []
    pre = vec(0x60) + DS1F + [sfr_b(0x4C, 0x07)] + event_tail(ei=False)
    for pn, pad in (("a", []), ("b", [CBW])):
        for d in range(tickw(84), tickw(160), 8):
            v.append(run(f"g-fei{pn}-intp0-d{d + 4}", pre, RD * 2 + pad + [EI] + RD * 6,
                         pulse("INTP0", d + 4), HND))
    return v


PADS = {0: [], 2: [CLC], 3: [CBW], 4: [NOP], 5: [CLC, CBW], 6: [CBW, CBW], 7: [CBW, NOP],
        8: [NOP, NOP], 9: [CBW] * 3, 10: [CBW, CBW, NOP], 11: [CBW, NOP, NOP], 12: [NOP] * 3,
        13: [CBW] * 3 + [NOP], 14: [CBW, CBW, NOP, NOP], 15: [CBW] + [NOP] * 3, 16: [NOP] * 4,
        17: [CBW] * 3 + [NOP] * 2, 18: [CBW] * 2 + [NOP] * 3, 19: [CBW] + [NOP] * 4,
        20: [NOP] * 5, 21: [CBW] * 3 + [NOP] * 3, 22: [CBW] * 2 + [NOP] * 4, 24: [NOP] * 6}


def soft():
    v = []
    for t, pad in PADS.items():
        pre = vec(0x60) + DS1F + [sfr_b(0x4C, 0x07)]
        v.append(run(f"s-set-t{t}", pre, [EI] + pad + [[0x26, 0xC6, 0x06, 0x4C, 0xFF, 0x87]] + [NOP] * 16,
                     {"entries": []}, HND))
        v.append(run(f"s-ctl-t{t}", pre + DS1Z, [EI] + pad + [[0x26, 0xC6, 0x06, 0x00, 0x0C, 0x87]] + [NOP] * 16,
                     {"entries": []}, HND))
    return v


WIN = {("nop", 1): [(64, 92)], ("nop", 2): [(62, 92)], ("inc", 1): [(64, 96)], ("inc", 2): [(62, 98)],
       ("mi8", 0): [(64, 96)], ("mi16", 0): [(64, 96)], ("ld", 0): [(64, 100)], ("mul", 0): [(64, 124)],
       ("shl", 0): [(64, 86), (138, 168)], ("jmp", 0): [(64, 106)], ("jch", 0): [(64, 112)],
       ("mm", 0): [(64, 100)], ("jch", 2): [(62, 116)], ("mm", 2): [(62, 104)]}
ROUNDS = {f"r18t{t}{w}": (lambda t=t, w=w: sum((sweep(t, w, lo, hi) for lo, hi in WIN[t, w]), [])) for t, w in WIN}
ROUNDS.update({"r18w": widths, "r18f": flag_ei, "r18s": soft})


# r18y: does Q69's "reserving request" hold for a bus-idle request word that releases no
# displacement?  ADD / CMP word [BW],imm16 (`P . . BY ...`) behind every predecessor pair.
YF = {"cmp": [0x81, 0x3F, 0x34, 0x12], "add": [0x81, 0x07, 0x34, 0x12]}
YP = {"n": [NOP], "i": [INC], "c": [CBW], "k": [CLC], "r": [MOVI16], "b": [MOVI8], "j": [JMP0],
      "l": [LD], "u": [[0x50]], "x": [[0x93]], "s": [[0x88, 0x07]], "m": [MULU16]}
# BW is kept: the INC here is INC DW (42), MOV r8 is MOV DL (B2), MOV r16 is MOV DW (BA)
YP.update(i=[[0x42]], r=[[0xBA, 0x20, 0x00]], b=[[0xB2, 0x20]], m=[[0xF7, 0xE1]])


def round18y(pairs=True):
    v = []
    for fn, f in YF.items():
        for a in [""] + list(YP):
            for b in (list(YP) if pairs else ["n"]):
                pre = (YP[a] if a else []) + YP[b]
                v.append((f"y-{fn}-{a}{b}", [q(c, "prev") for c in pre] + [q(f, fn), q(NOP, "nop")]))
    return v


ROUNDS["r18y"] = round18y


# r18c: the REP compares over data that ends the loop at element k of 4 (or not at all).
# Block A (0900h, IX) is 22h bytes; block B (0A00h, IY) is 22h where the pattern says "e" and
# 33h where it says "n" (22h - 33h borrows: CY = 1).  For CMPM the accumulator is 0 behind the
# frame's long shift, so B holds 00h for "e" and 33h for "n".
RC_PAT = {0xF3: ("eeee", "neee", "enee", "eene", "eeen"), 0xF2: ("nnnn", "ennn", "nenn", "nnen", "nnne"),
          0x64: ("eeee", "enee", "eeen"), 0x65: ("nnnn", "nenn", "nnne")}
RC_PFX = {0xF3: "repe", 0xF2: "repne", 0x64: "repnc", 0x65: "repc"}
RC_OP = {"cmpbk": 0xA6, "cmpbkw": 0xA7, "cmpm": 0xAE, "cmpmw": 0xAF}


def round18c():
    v = []
    for on, op in RC_OP.items():
        for pfx, pats in RC_PAT.items():
            for pat in pats:
                eq = 0x22 if "bk" in on else 0x00
                pre = [q([0xBE, 0x00, 0x09], "mov_ix"), q([0xBF, 0x00, 0x0A], "mov_iy")]
                bs = [eq if c == "e" else 0x33 for c in pat]
                if on.endswith("w"):
                    bs = [x for x in bs for _ in (0, 1)]
                for j in range(0, len(bs), 2):
                    pre.append(q([0xC7, 0x06, j, 0x09, 0x22, 0x22], "st_a"))
                    pre.append(q([0xC7, 0x06, j, 0x0A, bs[j], bs[j + 1]], "st_b"))
                pre = pad_even(pre)
                n = 4 if on.endswith("w") else 4
                body = [q([0xB9, n, 0x00], "mov_cw"), q([pfx, op], RC_PFX[pfx] + "_" + on)]
                for sfx, more in (("a", []), ("s", [q(SLOW, "slow")])):
                    v.append((f"rc-{RC_PFX[pfx]}-{on}-{pat}-{sfx}", (body + more, None, {"_pre": list(pre)})))
    return v


ROUNDS["r18c"] = round18c


# r18j: the corpus's br_n1 neighbourhood (CALL $+5 ; JMP $+3 ; RET executed as CALL, RET, JMP:
# a transfer whose opcode is the first byte behind another transfer's flush), and JMP short
# behind an I/O cycle.
OUT22, J1, J0 = [0xE6, 0x22], [0xEB, 0x01], [0xEB, 0x00]
CRJ = [[0xE8, 0x02, 0x00], J1, [0xC3]]


def round18j():
    progs = {"callret": CRJ, "ncallret": [NOP] + CRJ, "ocallret": [OUT22] + CRJ,
             "callret2": CRJ + CRJ, "oj1": [OUT22, J1, NOP], "oj0": [OUT22, J0],
             "j1j1": [J1, NOP, J1, NOP], "j0j0": [J0, J0], "j1n": [J1, NOP, NOP], "nj1": [NOP, J1, NOP]}
    return [(f"j-{n}", [q(c, "x") for c in b]) for n, b in progs.items()]


def round18b():
    """Bit forms on a register with the bit number in CL: is the length a function of CL?"""
    v = []
    for fn, op, ns in (("s1b", 0x14, (0, 1, 2, 3, 7, 8, 15, 16, 31)), ("s1w", 0x15, (0, 1, 2, 3, 7, 8, 15, 16, 31)),
                       ("t1w", 0x11, (0, 7, 15)), ("c1w", 0x13, (0, 7, 15)), ("n1w", 0x17, (0, 7, 15))):
        for n in ns:
            v.append((f"b-{fn}-cl{n}", [q([0xB1, n], "mov_cl"), q([0x0F, op, 0xC0], fn), q(NOP, "nop")]))
    v += [("b-s1w-a", [q([0x0F, 0x15, 0xC0], "s1w")]), ("b-s1w-2", [q([0x0F, 0x15, 0xC0], "s1w")] * 2),
          ("b-s1w-o", [q(OUT22, "x"), q([0x0F, 0x15, 0xC0], "s1w")])]
    return v


ROUNDS.update({"r18j": round18j, "r18b": round18b})
