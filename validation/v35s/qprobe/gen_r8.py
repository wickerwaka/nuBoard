"""Round 8: the unread forms, one variable at a time (same frame as rounds 1-7).

fl-*   flushes: what sets the distance from the flush to the target's fetch (JMP near, JMP
       r16, CALL near / far, RET, RETF, IRET, LOOP, JCXZ, INT 3), each followed by 0 / 1 NOP
ld-*   leads: X after INC (2 clocks) / CBW (3) / NOP (4); identical traces = a lead of 3+
t-*    trains of the ModR/M forms whose shape is unread (TEST r,r, INC r8, TEST1, ROL4,
       prefix + MOV r,r, XCH r,r); em3-* the same forms after MOV r16,imm16 (two bytes held)
ea-*   MOV AW,[ea] for the EA modes not measured directly; es-* two stores; rw-* the
       read-modify-write and store-immediate forms
si-*   SHL AW,imm8 by 1 / 2 / 8; st-* string forms; jo-* a taken Jcc to an odd target
"""

from .gen import BODY_AT, INC, NOP, RI, RR, q, train

PUSHI2 = [0x68, 0x02, 0x00]


def w16(v):
    return [v & 0xFF, (v >> 8) & 0xFF]


def at_body(fn):
    """A body that needs its own address: fn(offset of the body's first byte in PS)."""
    return lambda parity: fn(BODY_AT[parity])


def flushes():
    v = []
    for n in (0, 1):
        tail = train(NOP, "nop", n)
        v.append((f"fl-jn-{n}", [q([0xE9, 0x00, 0x00], "jn")] + tail))
        v.append((f"fl-jn1-{n}", [q([0xE9, 0x01, 0x00], "jn"), q(NOP, "skip")] + tail))
        v.append((f"fl-jr-{n}", at_body(lambda a, t=tail: [q([0xBB] + w16(a + 5), "mov_bw"),
                                                           q([0xFF, 0xE3], "jr")] + t)))
        v.append((f"fl-call-{n}", [q([0xE8, 0x00, 0x00], "call")] + tail))
        v.append((f"fl-callf-{n}", at_body(lambda a, t=tail: [
            q([0x9A] + w16(a + 5) + [0x00, 0x10], "callf")] + t)))
        v.append((f"fl-ret-{n}", at_body(lambda a, t=tail: [
            q([0x68] + w16(a + 4), "pushi"), q([0xC3], "ret")] + t)))
        v.append((f"fl-retf-{n}", at_body(lambda a, t=tail: [
            q([0x68, 0x00, 0x10], "pushi"), q([0x68] + w16(a + 7), "pushi"),
            q([0xCB], "retf")] + t)))
        # fl-iret (PUSH 0002h ; PUSH PS ; PUSH IP ; RETI) was acquired once and REMOVED: on
        # silicon it runs away (repeated trap frames into unmapped memory, 2,048 cycles, FAIL),
        # in simulation it passes. RETI restores the PSW's register-bank bits, POP PSW (the
        # prelude's) evidently does not on silicon: the program lands in another bank. The
        # first traces are kept in the receipts as evidence; do not re-run it on the socket.
        v.append((f"fl-loop-{n}", [q([0xE2, 0x00], "loop")] + tail))
        v.append((f"fl-jcxz-{n}", [q([0xE3, 0x00], "jcxz")] + tail))
        v.append((f"fl-int3-{n}", at_body(lambda a, t=tail: [
            q([0xC7, 0x06, 0x0C, 0x00] + w16(a + 13), "vec_ip"),
            q([0xC7, 0x06, 0x0E, 0x00, 0x00, 0x10], "vec_ps"), q([0xCC], "int3")] + t)))
        v.append((f"jo-{n}", [q([0x74, 0x01], "jz"), q(NOP, "skip")] + tail))
    return v


def leads():
    v = []
    forms = {"movrs": ([], [0x8C, 0xD8]), "pushs": ([], [0x1E]),
             "pops": ([[0x1E]], [0x1F]), "indw": ([], [0xEC]), "test1": ([], [0x0F, 0x10, 0xC0]),
             "movs": ([], [0xA4]), "xlat": ([], [0xD7]), "pushf": ([], [0x9C]),
             "lea": ([], [0x8D, 0x07]), "pushr": ([], [0x50]), "popr": ([[0x50]], [0x58]),
             "lbw": ([], [0x8B, 0x07]), "ret": (None, None), "int3": (None, None)}
    for name, (setup, code) in forms.items():
        for pn, pc in (("i", INC), ("c", [0x98]), ("n", NOP)):
            if name == "ret":
                body = at_body(lambda a, pc=pc: [q([0x68] + w16(a + 5), "pushi"), q(pc, "prev"),
                                                 q([0xC3], "ret")])
            elif name == "int3":
                body = at_body(lambda a, pc=pc: [
                    q([0xC7, 0x06, 0x0C, 0x00] + w16(a + 14), "vec_ip"),
                    q([0xC7, 0x06, 0x0E, 0x00, 0x00, 0x10], "vec_ps"), q(pc, "prev"),
                    q([0xCC], "int3")])
            else:
                body = [q(s, "setup") for s in setup] + [q(pc, "prev"), q(code, name)]
            v.append((f"ld-{name}-{pn}", body))
    return v


def modrm_forms():
    v = []
    forms = {"test": [0x84, 0xC3], "incb": [0xFE, 0xC3], "test1": [0x0F, 0x10, 0xC0],
             "rol4": [0x0F, 0x28, 0xC0], "pfxrr": [0x26, 0x8B, 0xC3], "xch": [0x86, 0xC3],
             "cmprr": [0x3B, 0xC3], "notr": [0xF7, 0xD3]}
    for name, code in forms.items():
        v += [(f"t-{name}-{n}", train(code, name, n)) for n in (1, 2, 3)]
        v.append((f"em3-{name}", [q(RI, "ri"), q(code, name)] + train(NOP, "nop", 2)))
    return v


def memory():
    v = []
    ea = {"m01": [0x01], "m02": [0x02], "m03": [0x03], "m04": [0x04], "m05": [0x05],
          "m40": [0x40, 0x10], "m42": [0x42, 0x10], "m44": [0x44, 0x10], "m46": [0x46, 0x10],
          "m80": [0x80, 0x00, 0x02], "m86": [0x86, 0x00, 0x01]}
    for name, tail in ea.items():
        v += [(f"ea-{name}-{n}", train([0x8B] + tail, name, n)) for n in (1, 2)]
    v += [(f"es-m00-{n}", train([0x89, 0x00], "s00", n)) for n in (1, 2)]
    v += [(f"es-m46-{n}", train([0x89, 0x46, 0x10], "s46", n)) for n in (1, 2)]
    rw = {"add8": [0x01, 0x47, 0x10], "incm": [0xFF, 0x07], "addi": [0x83, 0x07, 0x01],
          "movi": [0xC7, 0x07, 0x34, 0x12], "addm": [0x03, 0x07], "cmpm": [0x3B, 0x07],
          "add": [0x01, 0x07]}
    for name, code in rw.items():
        v += [(f"rw-{name}-{n}", train(code, name, n)) for n in (1, 2)]
    return v


def others():
    v = []
    for c in (1, 2, 8):
        v.append((f"si-{c}", [q([0xC1, 0xE0, c], "shli")]))
        v.append((f"si-{c}n", [q(NOP, "nop"), q([0xC1, 0xE0, c], "shli")]))
    v += [(f"st-movs-{n}", train([0xA4], "movs", n)) for n in (1, 2)]
    v += [(f"st-stos-{n}", train([0xAA], "stos", n)) for n in (1, 2)]
    v += [(f"st-lods-{n}", train([0xAC], "lods", n)) for n in (1, 2)]
    v.append(("st-rep3", [q([0xB9, 0x03, 0x00], "mov_cw"), q([0xF3, 0xA4], "rep_movs")]))
    v.append(("st-rep0", [q([0xF3, 0xA4], "rep_movs")]))
    return v


def round8():
    return flushes() + leads() + modrm_forms() + memory() + others()


ROUNDS = {"r8": round8}
