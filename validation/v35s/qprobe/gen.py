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


M1W = bytes([0xEF])                 # the marker as OUT DW,AW (a word to port 20h)
BODY_AT = {"even": 0x47 + 1 + 6, "odd": 0x47 + 6}   # the body's offset in PS (prelude 47h)


def round5():
    """Round 5: the word-wide OUT; the corpus prelude's instructions behind the long shift;
    memory operands one variable at a time; other flushes (CALL / RET near, JMP far); which
    instructions hide their predecessor's tail as OUT imm8 does (`ld-*`: identical traces after
    INC / CBW / NOP mean a lead of three clocks or more); which ModR/M forms wait for three
    bytes (`em2-*`, after MOV r16,imm16 at pE)."""
    v = []
    v += [(f"ow-{n}", (train(NOP, "nop", n), M1W)) for n in range(4)]
    pushi, popf = [0x68, 0x02, 0x00], [0x9D]
    v.append(("pp-0", [q(pushi, "pushi"), q(popf, "popf")]))
    v.append(("pp-1", [q(pushi, "pushi"), q(popf, "popf"), q(NOP, "nop")]))
    v.append(("pp-2", [q(pushi, "pushi"), q(NOP, "nop"), q(popf, "popf")]))
    v.append(("pi-1", [q(pushi, "pushi")]))
    v += [(f"sr-{n}", train([0x8E, 0xD8], "mov_ds0", n)) for n in (1, 2, 3)]
    mov0 = [0xB8, 0x00, 0x00]
    v.append(("pre", [q(pushi, "pushi"), q(popf, "popf"), q(mov0, "ri"), q([0x8E, 0xD8], "sr"),
                      q(mov0, "ri"), q([0x8E, 0xC0], "sr"), q(mov0, "ri"), q([0x8E, 0xD0], "sr"),
                      q(RI, "ri"), q(RI, "ri")]))
    mem = {"lbw": [0x8B, 0x07], "ld8": [0x8B, 0x47, 0x10], "ld16": [0x8B, 0x87, 0x00, 0x02],
           "lbi": [0x8B, 0x00], "ldir": [0x8B, 0x06, 0x00, 0x0C], "lacc": [0xA1, 0x00, 0x0C],
           "sbw": [0x89, 0x07], "sd8": [0x89, 0x47, 0x10], "sdir": [0x89, 0x06, 0x00, 0x0C],
           "sacc": [0xA3, 0x00, 0x0C]}
    for name, code in mem.items():
        v += [(f"{name}-{n}", train(code, name, n)) for n in (1, 2, 3)]
    v += [(f"rmw-{n}", train([0x01, 0x07], "rmw", n)) for n in (1, 2)]
    v.append(("pq-0", [q([0x50], "push"), q([0x58], "pop")]))
    v.append(("pq-1", [q([0x50], "push"), q(NOP, "nop"), q([0x58], "pop")]))
    v.append(("pq-2", [q([0x50], "push"), q([0x50], "push"), q([0x58], "pop"), q([0x58], "pop")]))
    # CALL near to a RET three bytes on, back to a NOP, a JMP short over the RET
    v.append(("cr", [q([0xE8, 0x03, 0x00], "call"), q(NOP, "nop"), q([0xEB, 0x01], "jmp"),
                     q([0xC3], "ret")]))
    for n in range(3):
        def far(parity, n=n):
            at = BODY_AT[parity] + 5
            return [q([0xEA, at & 0xFF, at >> 8, 0x00, 0x10], "jmpfar")] + train(NOP, "nop", n)
        v.append((f"jfar-{n}", far))
    leads = {"in8": [0xE4, 0x40], "outw8": [0xE7, 0x22], "pushi": pushi, "addal": [0x04, 0x00],
             "lacc": [0xA1, 0x00, 0x0C], "sacc": [0xA3, 0x00, 0x0C], "jmp": [0xEB, 0x00],
             "jz": [0x74, 0x00], "out8": [0xE6, 0x22], "mi8": RI8}
    for name, code in leads.items():
        for pn, pc in (("i", INC), ("c", [0x98]), ("n", NOP)):
            v.append((f"ld-{name}-{pn}", [q(pc, "prev"), q(code, name)]))
    em2 = {"shl1": [0xD1, 0xE0], "incb": [0xFE, 0xC3], "mulu": [0xF6, 0xE3],
           "test1": [0x0F, 0x10, 0xC0], "pfxrr": [0x26, 0x8B, 0xC3], "sr": [0x8E, 0xD8],
           "xch": [0x86, 0xC3], "test": [0x84, 0xC3], "lbw": [0x8B, 0x07]}
    for name, code in em2.items():
        v.append((f"em2-{name}", [q(RI, "ri"), q(code, name)] + train(NOP, "nop", 2)))
    return v


ROUNDS = {"r1": round1, "r2": round2, "r3": round3, "r4": round4, "r5": round5}


def _more_rounds():
    """Rounds kept in their own files (gen_*.py beside this one, each with a ROUNDS dict)."""
    import importlib
    import pkgutil
    from pathlib import Path
    for m in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if m.name.startswith("gen_"):
            ROUNDS.update(importlib.import_module(f"{__package__}.{m.name}").ROUNDS)


def frame_of(body):
    """body: a list of Instr (framed with the default M1) or (list, m1 bytes)."""
    if isinstance(body, tuple):
        return frame(body[0], body[1] if body[1] is not None else M1)
    return frame(body)


def chains(rounds=("r1",), waits=WAITS, parities=PARITIES, ids=None):
    _more_rounds()
    out = []
    for r in rounds:
        for name, body in ROUNDS[r]():
            for w in waits:
                for p in parities:
                    b = body(p) if callable(body) else body
                    regs, extra = REGS, {}
                    if isinstance(b, tuple) and len(b) == 3:    # (round 11) (list, m1, regs)
                        regs = {**REGS, **{k: v for k, v in b[2].items() if k[0] != "_"}}
                        # (round 12) "_pre": instructions before M0, "_post": after END,
                        # "_stim": the run's schedule (runner.load_stimulus's form)
                        extra = {k: v for k, v in b[2].items() if k[0] == "_"}
                        b = b[:2]
                    if "_waits" in extra and w not in extra["_waits"]:
                        continue
                    fr = list(extra.get("_pre", [])) + frame_of(b) + list(extra.get("_post", []))
                    knobs = {"round": r, "name": name}
                    if "_stim" in extra:
                        knobs["stim"] = extra["_stim"]
                    c = make_chain(f"QP{r}", name, knobs, fr, w, p, regs=regs)
                    if any(i.form == "vec" for i in c.instrs):
                        # the handler's offset in the code segment goes into the vector store
                        from ..chains.image import build_image
                        h = next(i for i in c.instrs if i.form == "handler")
                        at = build_image(c).chain_base + h.offset - 0x10000
                        fr = [Instr(0, i.code[:4] + bytes([at & 255, at >> 8]), "vec", i.role)
                              if i.form == "vec" else i for i in fr]
                        c = make_chain(f"QP{r}", name, knobs, fr, w, p, regs=regs)
                    if ids and not any(s in c.id for s in ids):
                        continue
                    out.append(c)
    return out
