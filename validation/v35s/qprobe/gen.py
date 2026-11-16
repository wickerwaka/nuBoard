"""The qprobe programs (design: the hand-back's design.md).

Frame: [PAD] M0 LS body M1 LS END, the corpus's prelude and image builder (chains.image).
M0 = OUT 21h,AL (E6 21), M1 = OUT DW,AL (EE, DW = 0020h). parity = that of the first body byte.
"""

from __future__ import annotations

from ..chains import blocks
from ..chains.families import make_chain
from ..chains.types import Instr

WAITS = (0, 1, 2)
PARITIES = ("even", "odd")
REGS = {"DW": 0x0020}

NOP = bytes([0x90])
INC = bytes([0x43])                 # INC BW
DEC = bytes([0x4B])                 # DEC BW
RR = bytes([0x8B, 0xC3])            # MOV AW,BW
RI = bytes([0xBB, 0x00, 0x08])      # MOV BW,0800h
RI8 = bytes([0xB3, 0x00])           # MOV BL,00h
SLOW = bytes([0xD3, 0xE0])          # SHL AW,CL (CL = 31 after LS)
M0 = bytes([0xE6, 0x21])
M1 = bytes([0xEE])
M1I = bytes([0xE6, 0x20])           # the marker as OUT imm8
M1P = bytes([0x50])                 # the marker as PUSH AW


def q(code, name):
    return Instr(0, bytes(code), name, "q")


def frame(body, m1=M1):
    return ([Instr(0, M0, "M0", "marker", marker_id=0), Instr(0, blocks.LS, "LS", "ls")]
            + body + [Instr(0, m1, "M1", "marker", marker_id=1),
                      Instr(0, blocks.LS, "LS2", "q"), Instr(0, blocks.END, "END", "end")])


def train(code, name, n):
    return [q(code, name) for _ in range(n)]


def jmp(k, n):
    """JMP short over k filler bytes, then NOP x n."""
    return ([q([0xEB, k], "JMP")] + [q(NOP, "skip") for _ in range(k)] + train(NOP, "nop", n))


def round1():
    v = [("base", [])]
    v += [(f"sp-{j}", train(NOP, "nop", j) + [q(SLOW, "slow")]) for j in range(7)]
    v += [(f"nop-{n}", train(NOP, "nop", n)) for n in (1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 24)]
    v += [(f"inc-{n}", train(INC, "inc", n)) for n in (2, 4, 8, 16)]
    v += [(f"rr-{n}", train(RR, "rr", n)) for n in (1, 2, 3, 4, 5, 6, 8, 12, 16)]
    v += [(f"rsp-{j}", train(RR, "rr", j) + [q(SLOW, "slow")]) for j in (1, 2, 3)]
    v += [(f"ri-{n}", train(RI, "ri", n)) for n in (1, 2, 3, 4, 5, 6, 8, 12)]
    v += [(f"j{k}-{n}", jmp(k, n)) for k in (0, 1) for n in (0, 1, 2, 3, 4, 6)]
    return v


def round2():
    """Round 2: the round-1 reading tested on programs it was not read from (mixes), the
    marker's own share (other markers, two markers), more routine shapes (one train each),
    other flushes, and the EU's own bus cycles between fetches."""
    import random
    rng = random.Random(35)
    pool = [(NOP, "nop"), (INC, "inc"), (RR, "rr"), (RI, "ri")]
    v = []
    for k in range(16):
        v.append((f"mix-{k}", [q(*rng.choice(pool)) for _ in range(10)]))
    v += [(f"e6n-{n}", (train(NOP, "nop", n), M1I)) for n in range(5)]
    v += [(f"e6r-{n}", (train(RR, "rr", n), M1I)) for n in (1, 2, 3)]
    v += [("e6i-1", (train(RI, "ri", 1), M1I))]
    v += [(f"pun-{n}", (train(NOP, "nop", n), M1P)) for n in range(5)]
    v += [(f"mm-{j}{k}", train(NOP, "nop", j) + [q(M1I[:1] + bytes([0x22]), "out22")]
           + train(NOP, "nop", k)) for j in range(3) for k in range(3)]
    shapes = {"mi8": RI8, "addrr": [0x03, 0xC3], "xchg": [0x93], "clc": [0xF8], "cbw": [0x98],
              "addi": [0x05, 0x00, 0x00], "add83": [0x83, 0xC3, 0x00], "rr8": [0x8A, 0xC3],
              "pfx": [0x26, 0x90], "shl1": [0xD1, 0xE0], "shli": [0xC1, 0xE0, 0x04]}
    for name, code in shapes.items():
        v += [(f"{name}-{n}", train(code, name, n)) for n in (1, 2, 3, 4, 6)]
    v += [(f"mul-{n}", train([0xF6, 0xE3], "mul", n)) for n in (1, 2)]
    for name, code in (("jn", [0xE9, 0x00, 0x00]), ("jz", [0x74, 0x00]), ("jnz", [0x75, 0x00])):
        v += [(f"{name}-{n}", [q(code, name)] + train(NOP, "nop", n)) for n in range(4)]
    for name, code in (("ld", [0xA1, 0x00, 0x0C]), ("st", [0xA3, 0x00, 0x0C]), ("push", [0x50]),
                       ("pop", [0x58])):
        v += [(f"{name}-{n}", train(code, name, n)) for n in (1, 2, 3)]
    return v


def round3():
    """Round 3: the reading of rounds 1-2 tested by prediction on wider mixes (ten instruction
    kinds), and the three rules read from single cases opened one variable at a time: which
    opcode's E waits at two bytes held (after MOV r16,imm16 at pE: `em-*`), the first
    instruction after a flush (`jf*-*`), the short shift's bus-idle word (`sc*-*`)."""
    import random
    rng = random.Random(337)
    kinds = {"nop": NOP, "inc": INC, "rr": RR, "ri": RI, "mi8": RI8, "cbw": [0x98],
             "xchg": [0x93], "clc": [0xF8], "addrr": [0x03, 0xC3], "addi": [0x05, 0x00, 0x00]}
    names = sorted(kinds)
    v = []
    for k in range(24):
        v.append((f"mx-{k}", [q(kinds[n], n) for n in (rng.choice(names) for _ in range(12))]))
    firsts = {"rr": RR, "addrr": [0x03, 0xC3], "rr8": [0x8A, 0xC3], "inc": INC, "nop": NOP,
              "ri": RI, "mi8": RI8, "addi": [0x05, 0x00, 0x00], "cbw": [0x98], "out": M1}
    for n, code in firsts.items():
        v.append((f"em-{n}", [q(RI, "ri"), q(code, n)] + train(NOP, "nop", 2)))
        for k in (0, 1):
            v.append((f"jf{k}-{n}", [q([0xEB, k], "JMP")] + [q(NOP, "skip") for _ in range(k)]
                      + [q(code, n)] + train(NOP, "nop", 2)))
    for c in (1, 4, 8):
        for j in range(3):
            v.append((f"sc{c}-{j}", train(NOP, "nop", j) + [q([0xB1, c], "movcl"), q(SLOW, "shl")]))
    return v


def round4():
    """Round 4 (acquired for the next reading; results.md "The next tests" 1-3): OUT imm8
    isolated by a slow shift after each kind of predecessor; a bus-idle (B) word after an EU
    cycle; a register written by one instruction and read by the next."""
    v = []
    out22 = [0xE6, 0x22]
    prevs = {"0": [], "i": [INC], "c": [[0x98]], "n": [NOP], "ii": [INC, INC], "ni": [NOP, INC],
             "r": [RR], "w": [RI]}
    for name, codes in prevs.items():
        pre = [q(c, "prev") for c in codes]
        v.append((f"o6s-{name}", pre + [q(out22, "out22"), q(SLOW, "slow")]))
        v.append((f"o6i-{name}", pre + [q(out22, "out22"), q(INC, "inc"), q(SLOW, "slow")]))
        v.append((f"o6n-{name}", pre + [q(out22, "out22"), q(NOP, "nop"), q(SLOW, "slow")]))
    after = {"mi8": [RI8], "ri": [RI], "shc": [[0xB1, 0x02], SLOW], "rr": [RR], "nop": [NOP]}
    for name, codes in after.items():
        for j in range(4):
            tail = train(INC, "inc", j) + [q(c, name) for c in codes]
            v.append((f"bp-{name}-{j}", [q([0x50], "push")] + tail))
            v.append((f"bo-{name}-{j}", [q(out22, "out22")] + tail))
    v.append(("fw-dw", [q([0xBA, 0x20, 0x00], "mov_dw")]))
    v.append(("fw-dl", [q([0xB2, 0x20], "mov_dl")]))
    v.append(("fw-bw", [q(RI, "ri")]))
    v.append(("fw-inc-dw", [q([0x42], "inc_dw"), q([0x4A], "dec_dw")]))
    v.append(("fw-inc-bw", [q(INC, "inc"), q(DEC, "dec")]))
    return v


ROUNDS = {"r1": round1, "r2": round2, "r3": round3, "r4": round4}


def frame_of(body):
    """body: a list of Instr (framed with the default M1) or (list, m1 bytes)."""
    if isinstance(body, tuple):
        return frame(body[0], body[1])
    return frame(body)


def chains(rounds=("r1",), waits=WAITS, parities=PARITIES, ids=None):
    out = []
    for r in rounds:
        for name, body in ROUNDS[r]():
            for w in waits:
                for p in parities:
                    c = make_chain(f"QP{r}", name, {"round": r, "name": name}, frame_of(body),
                                   w, p, regs=REGS)
                    if ids and not any(s in c.id for s in ids):
                        continue
                    out.append(c)
    return out
