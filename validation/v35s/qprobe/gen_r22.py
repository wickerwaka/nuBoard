"""Round 22.

r22a  X directly behind OUT imm8 (the corpus's unread state, Q99): 101 forms, chosen so that the
      words of X that fall on the I/O cycle's last clock and on the clock after it differ (a
      request, a bus-idle word, a pop, a plain word), marker OUT imm8.
r22b  the same forms behind OUT imm8 ; INC BW (X's words one clock... two clocks later against the
      I/O cycle: its first word on the cycle's last clock).
r22c  the same forms behind PUSH AW (a memory write in the I/O cycle's place; X's first word on
      the clock after the cycle).
r22d  35 of the forms behind seven more leads (OUT ; CBW, OUT imm8,AW, IN imm8, NOP ; OUT,
      INC ; OUT, a store, POP).
"""

from .gen import M1I, NOP, q

PUSH, OUT22, POP, IN40, SACC, INC, CBW = [0x50], [0xE6, 0x22], [0x58], [0xE4, 0x40], [0xA3, 0x00, 0x0C], [0x43], [0x98]
D8, D16, DIR = [0x10], [0x10, 0x02], [0x00, 0x0C]


def _forms():
    f = {}
    for m in (0x00, 0x01, 0x02, 0x04, 0x05, 0x07):
        f[f"ld{m:02x}"] = [0x8B, m]
    for m in (0x40, 0x44, 0x46, 0x47):
        f[f"ld{m:02x}"] = [0x8B, m] + D8
    for m in (0x80, 0x81, 0x83, 0x84, 0x86, 0x87):
        f[f"ld{m:02x}"] = [0x8B, m] + D16
    f["ld06"] = [0x8B, 0x06] + DIR
    for m, d in ((0x00, []), (0x07, []), (0x40, D8), (0x47, D8), (0x80, D16), (0x87, D16), (0x06, DIR)):
        f[f"lea{m:02x}"] = [0x8D, m] + d
        f[f"st{m:02x}"] = [0x89, m] + d
    for m, d in ((0x00, []), (0x07, []), (0x40, D8), (0x47, D8), (0x80, D16), (0x87, D16)):
        f[f"rmw{m:02x}"] = [0x01, m] + d
    for m, d in ((0x00, []), (0x07, []), (0x80, D16)):
        f[f"cmp{m:02x}"] = [0x3B, m] + d
    f.update(ai16=[0x81, 0xC2, 0x34, 0x12], ai8=[0x83, 0xC2, 0x01], ai8b=[0x80, 0xC3, 0x01],
             ci16=[0x81, 0xFA, 0x34, 0x12], ti16=[0xF7, 0xC3, 0x34, 0x12], ti8=[0xF6, 0xC3, 0x01])
    f.update(addim07=[0x83, 0x07, 0x01], addim00=[0x83, 0x00, 0x01], addim40=[0x83, 0x40, 0x10, 0x01],
             addim80=[0x83, 0x80, 0x10, 0x02, 0x01], addiw07=[0x81, 0x07, 0x34, 0x12],
             addiw00=[0x81, 0x00, 0x34, 0x12], stim07=[0xC7, 0x07, 0x34, 0x12], stim00=[0xC7, 0x00, 0x34, 0x12],
             stim40=[0xC7, 0x40, 0x10, 0x34, 0x12], stim80=[0xC7, 0x80, 0x10, 0x02, 0x34, 0x12],
             stimb=[0xC6, 0x07, 0x12], cmpim=[0x83, 0x3F, 0x01])
    f.update(popm07=[0x8F, 0x07], popm00=[0x8F, 0x00], popm47=[0x8F, 0x47, 0x10], pushm07=[0xFF, 0x37],
             pushm00=[0xFF, 0x30])
    f.update(notm=[0xF7, 0x17], notr=[0xF7, 0xD3], incb=[0xFE, 0xC3], incm=[0xFF, 0x07], shl1=[0xD1, 0xE0],
             shlm1=[0xD1, 0x27], testrr=[0x84, 0xC3], testm=[0x85, 0x07], xchrr=[0x86, 0xC3], xchm=[0x87, 0x07],
             rr=[0x8B, 0xC3], cmprr=[0x3B, 0xC0], movsr=[0x8C, 0xD8], mulu=[0xF7, 0xE0])
    f.update(cvtwl=[0x99], indw=[0xEC], cbw=[0x98], nop=[0x90], inc=[0x43], ri=[0xB8, 0x34, 0x12],
             ri8=[0xB0, 0x12], addi=[0x05, 0x34, 0x12], addal=[0x04, 0x12], ldacc=[0xA1, 0x00, 0x0C],
             stacc=[0xA3, 0x00, 0x0C], push=[0x50], pop=[0x58], pushf=[0x9C], xlat=[0xD7], lods=[0xAD],
             stos=[0xAB], in8=[0xE4, 0x40], out8=[0xE6, 0x23], lahf=[0x9F], clc=[0xF8], adj4=[0x27], di=[0xFA])
    f.update(t1r=[0x0F, 0x11, 0xC0], t1ri=[0x0F, 0x19, 0xC0, 0x03], t1m=[0x0F, 0x11, 0x07], rol4=[0x0F, 0x28, 0xC2])
    return f


FORMS22 = _forms()
SUB = ["ld07", "ld00", "ld47", "ld87", "ld80", "ld06", "lea87", "lea80", "st07", "st80", "rmw07", "rmw80",
       "ai16", "ai8", "ti16", "addim07", "addiw07", "stim07", "stim80", "popm07", "pushm07", "incm", "mulu",
       "shl1", "testrr", "rr", "cvtwl", "indw", "ri", "nop", "ldacc", "push", "t1r", "rol4", "addim80"]


def _fam(tag, lead, names=None):
    def gen():
        v = []
        for name in (names or FORMS22):
            v.append((f"{tag}-{name}", ([q(c, "lead") for c in lead] + [q(FORMS22[name], name)], M1I)))
        return v
    return gen


EXTRA = {"shli8": [0xC1, 0xE0, 0x08], "s1m": [0x0F, 0x15, 0x07]}
SUBD = SUB + ["t1m", "shli8", "s1m", "popm47", "ci16"]
CLC = [0xF8]


def round22d():
    """40 forms behind nine more leads: OUT ; CBW and OUT ; CLC (X's words three and two clocks
    later against the I/O cycle), CLC ; OUT and NOP ; OUT (the bytes held when the I/O cycle
    ends), OUT imm8,AW, OUT DW (DW = 22h), IN imm8, a store, POP."""
    from .gen_r11 import with_regs
    forms = {**FORMS22, **EXTRA}
    v = []
    for tag, lead in (("oc", [OUT22, CBW]), ("ok", [OUT22, CLC]), ("ko", [CLC, OUT22]), ("no", [NOP, OUT22]),
                      ("e7", [[0xE7, 0x22]]), ("in", [IN40]), ("st", [SACC]), ("pop", [POP])):
        for name in SUBD:
            v.append((f"{tag}-{name}", ([q(c, "lead") for c in lead] + [q(forms[name], name)], M1I)))
    odw = [(f"odw-{name}", ([q([0xEE], "lead"), q(forms[name], name)], M1I)) for name in SUBD if name != "indw"]
    return v + with_regs(odw, {"DW": 0x0022})


ROUNDS = {"r22a": _fam("o", [OUT22]), "r22b": _fam("oi", [OUT22, INC]), "r22c": _fam("p", [PUSH]),
          "r22d": round22d}
