"""Round 24.

r24a  the commit word against the fetch chain behind an EU cycle (Q110): EXT / INS r,r and r,imm4
      beside ROL4 / ROR4 r, SHL r,imm8, CVTDB, TEST1 [BW],CL and ROL4 [BW], behind nine leads
      (OUT imm8 alone and with a CLC / CBW / NOP spacer: the word moved 2 / 3 / 4 clocks against
      the chain; OUT imm8,AW; PUSH; a store; IN imm8; POP), marker OUT imm8.
r24b  the boundary with two bytes held (Q111, Q112): seven instructions that end on an immediate
      (stores with an immediate, MOV / ADD r,imm16, PUSH imm16, ADD [BW],imm16) in front of nine
      followers (OUT imm8, OUT imm8,AW, IN imm8, MOV DS1,AW: the opcodes with a decode lead;
      PUSH, MOV AW,[d16], MOV AW,[BW], MOV AL,imm8, NOP: the controls), marker OUT imm8.
r24c  the opcodes with a decode lead at a flush target (Q113): JMP short + 0 / + 1, JMP near, BE
      taken, in front of OUT imm8 / OUT imm8,AW / IN imm8 / MOV DS1,AW and the controls PUSH and
      MOV AL,imm8, marker OUT imm8.
r24d  ADJBA / ADJBS / EI (the corpus rows "fetch early by 1" behind OUT at even alignment):
      behind OUT imm8, OUT imm8 ; CLC and PUSH, alone and twice, marker OUT imm8.
"""

from .gen import M1I, NOP, q

PUSH, OUT22, POP, IN40, SACC, CBW, CLC = [0x50], [0xE6, 0x22], [0x58], [0xE4, 0x40], [0xA3, 0x00, 0x0C], [0x98], [0xF8]
NOPL = [0x90]

A_FORMS = {"extr": [0x0F, 0x33, 0xF3], "exti": [0x0F, 0x3B, 0xC3, 0x07], "insr": [0x0F, 0x31, 0xF3],
           "insi": [0x0F, 0x39, 0xC3, 0x07], "rol4": [0x0F, 0x28, 0xC2], "ror4": [0x0F, 0x2A, 0xC2],
           "shli8": [0xC1, 0xE0, 0x08], "cvtdb": [0xD5, 0x0A], "t1m": [0x0F, 0x11, 0x07],
           "rol4m": [0x0F, 0x28, 0x07]}
A_LEADS = (("o", [OUT22]), ("oc", [OUT22, CLC]), ("ok", [OUT22, CBW]), ("on", [OUT22, NOPL]),
           ("e7", [[0xE7, 0x22]]), ("p", [PUSH]), ("st", [SACC]), ("in", [IN40]), ("pop", [POP]))


def round24a():
    return [(f"{tag}-{name}", ([q(c, "lead") for c in lead] + [q(code, name)], M1I))
            for tag, lead in A_LEADS for name, code in A_FORMS.items()]


B_L = {"stim07": [0xC7, 0x07, 0x34, 0x12], "stim80": [0xC7, 0x80, 0x10, 0x02, 0x34, 0x12],
       "stimb": [0xC6, 0x07, 0x12], "ri": [0xB8, 0x34, 0x12], "ai16": [0x81, 0xC2, 0x34, 0x12],
       "pushi": [0x68, 0x34, 0x12], "addiw07": [0x81, 0x07, 0x34, 0x12]}
B_F = {"out8": [0xE6, 0x23], "e7": [0xE7, 0x23], "in8": [0xE4, 0x40], "movsr": [0x8E, 0xC0],
       "push": [0x50], "ldacc": [0xA1, 0x00, 0x0C], "ld07": [0x8B, 0x07], "ri8": [0xB0, 0x12],
       "nop": [0x90]}


def round24b():
    return [(f"{ln}-{fn}", ([q(lc, ln), q(fc, fn)], M1I)) for ln, lc in B_L.items() for fn, fc in B_F.items()]


C_T = {"j0": [[0xEB, 0x00]], "j1": [[0xEB, 0x01], NOPL], "jn": [[0xE9, 0x00, 0x00]], "jz": [[0x74, 0x00]]}
C_F = ("out8", "e7", "in8", "movsr", "push", "ri8")


def round24c():
    v = []
    for tn, tc in C_T.items():
        for fn in C_F:
            body = [q(tc[0], "JMP" if tn != "jz" else "jz")] + [q(c, "skip") for c in tc[1:]] + [q(B_F[fn], fn)]
            v.append((f"{tn}-{fn}", (body, M1I)))
    return v


D_F = {"adjba": [0x37], "adjbs": [0x3F], "ei": [0xFB]}


def round24d():
    v = []
    for tag, lead in (("o", [OUT22]), ("oc", [OUT22, CLC]), ("p", [PUSH])):
        for name, code in D_F.items():
            v.append((f"{tag}-{name}", ([q(c, "lead") for c in lead] + [q(code, name)], M1I)))
            v.append((f"{tag}-{name}2", ([q(c, "lead") for c in lead] + [q(code, name), q(code, name)], M1I)))
    return v


ROUNDS = {"r24a": round24a, "r24b": round24b, "r24c": round24c, "r24d": round24d}
