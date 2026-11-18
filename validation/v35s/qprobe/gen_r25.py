"""Round 25.

r25a  a word at an odd address (two byte cycles back to back) and what stands behind the pair:
      stores / loads / read-modify-writes through BW = 0801h with nine followers, the same behind
      a flush, PUSH / POP with SP odd, the string forms single (and four REP forms) with IX, IY or
      both odd, follower none / NOP. Marker OUT imm8.
r25b  stores against the fetch chain, one variable at a time: nine store forms (no displacement,
      d8, d16, direct, the accumulator form, a prefixed d8, a register datum, two immediates)
      behind three EU cycles (OUT imm8, PUSH, a load) and six pads (none, CLC, CBW, NOP, CLC CLC,
      NOP NOP), and each form alone behind a long shift (queue full, bus idle).
r25c  the string forms single at even pointers behind six leads (PUSH, PUSH CLC, OUT, OUT CLC,
      OUT NOP, a store): where their bus-idle word is.
r25d  ADD4S / SUB4S / CMP4S with something other than MOV CL,imm8 directly in front (NOP, CLC,
      PUSH, OUT, a prefix, itself two and three times); ADJ4A / ADJ4S one, two and three times
      over four AL / flag settings, follower NOP.
"""

from .gen import M1I, SLOW, q

PUSH, OUT22, POP, CLC, CBW, NOPL, INC = [0x50], [0xE6, 0x22], [0x58], [0xF8], [0x98], [0x90], [0x43]
LDACC, SACC, RI16 = [0xA1, 0x00, 0x0C], [0xA3, 0x00, 0x0C], [0xB8, 0x34, 0x12]
ODD = {"BW": 0x0801}
PTR = {"iy": {"IX": 0x0A40, "IY": 0x0C41}, "ix": {"IX": 0x0A41, "IY": 0x0C40},
       "xy": {"IX": 0x0A41, "IY": 0x0C41}, "ev": {"IX": 0x0A40, "IY": 0x0C40}}
STR = {"movbk": [0xA5], "cmpbk": [0xA7], "stm": [0xAB], "ldm": [0xAD], "cmpm": [0xAF], "inm": [0x6D]}


def _p(name, codes, regs=None):
    r = dict(regs or {})
    return (name, ([q(c, f"i{k}") for k, c in enumerate(codes)], M1I, r))


def round25a():
    v = []
    st, ld = [0x89, 0x07], [0x8B, 0x07]
    fol = {"0": [], "nop": [NOPL], "inc": [[0x42]], "clc": [CLC], "ri": [RI16], "ld": [LDACC],
           "st2": [SACC], "push": [PUSH], "out": [OUT22], "x2": [st]}
    v += [_p(f"so-{n}", [st] + f, ODD) for n, f in fol.items()]
    v += [_p(f"lo-{n}", [ld] + fol[n], ODD) for n in ("0", "nop", "st2", "out")]
    v += [_p("rmw-0", [[0x01, 0x07]], ODD), _p("rmw-nop", [[0x01, 0x07], NOPL], ODD),
          _p("incm-0", [[0xFF, 0x07]], ODD), _p("sti-0", [[0xC7, 0x07, 0x34, 0x12]], ODD),
          _p("sti-nop", [[0xC7, 0x07, 0x34, 0x12], NOPL], ODD), _p("xch-0", [[0x87, 0x07]], ODD),
          _p("j-so", [[0xEB, 0x00], st], ODD), _p("j-lo", [[0xEB, 0x00], ld], ODD)]
    sp = {"SP": 0x0F01}
    v += [_p("sp-push", [PUSH], sp), _p("sp-push-nop", [PUSH, NOPL], sp), _p("sp-push-pop", [PUSH, POP], sp)]
    for op, ps in (("movbk", ("iy", "ix", "xy")), ("cmpbk", ("iy", "ix", "xy")), ("stm", ("iy",)),
                   ("ldm", ("ix",)), ("cmpm", ("iy",)), ("inm", ("iy",))):
        for pn in ps:
            regs = {**PTR[pn], **({"DW": 0x0040} if op == "inm" else {})}
            v += [_p(f"{op}-{pn}-0", [STR[op]], regs), _p(f"{op}-{pn}-nop", [STR[op], NOPL], regs)]
    for op, pn in (("movbk", "iy"), ("stm", "iy"), ("ldm", "ix"), ("cmpbk", "ix")):
        v.append(_p(f"rep2-{op}-{pn}", [[0xB9, 0x02, 0x00], [0xF3] + STR[op], [0x42]], PTR[pn]))
    return v


B_FORMS = {"s0": [0x89, 0x07], "s8": [0x89, 0x47, 0x10], "s16": [0x89, 0x87, 0x00, 0x02],
           "sdir": [0x89, 0x06, 0x00, 0x0C], "sacc": SACC, "ps8": [0x26, 0x89, 0x47, 0x10],
           "sr16": [0x89, 0x9F, 0x00, 0x02], "sti0": [0xC7, 0x07, 0x34, 0x12],
           "stidir": [0xC7, 0x06, 0x00, 0x0C, 0x34, 0x12]}
B_LEADS = {"o": OUT22, "p": PUSH, "l": LDACC}
B_PADS = {"0": [], "c": [CLC], "k": [CBW], "n": [NOPL], "cc": [CLC, CLC], "nn": [NOPL, NOPL]}


def round25b():
    v = [_p(f"sh-{fn}", [SLOW, fc]) for fn, fc in B_FORMS.items()]
    for ln, lc in B_LEADS.items():
        for pn, pc in B_PADS.items():
            v += [_p(f"{ln}{pn}-{fn}", [lc] + pc + [fc]) for fn, fc in B_FORMS.items()]
    return v


def round25c():
    v = []
    ops = dict(STR, movbkb=[0xA4])
    leads = {"p": [PUSH], "pc": [PUSH, CLC], "o": [OUT22], "oc": [OUT22, CLC], "on": [OUT22, NOPL], "st": [SACC]}
    for op, code in ops.items():
        regs = {**PTR["ev"], **({"DW": 0x0040} if op == "inm" else {})}
        v += [_p(f"{ln}-{op}", lc + [code], regs) for ln, lc in leads.items()]
    return v


def round25d():
    v = []
    cl2, cl4 = [0xB1, 0x02], [0xB1, 0x04]
    a, s, c = [0x0F, 0x20], [0x0F, 0x22], [0x0F, 0x26]
    r = PTR["ev"]
    v += [_p("add-c1", [cl2, a], r), _p("add-c2", [cl2, a, a], r), _p("add-c3", [cl2, a, a, a], r),
          _p("add-cn1", [cl2, NOPL, a], r), _p("add-cc1", [cl2, CLC, a], r), _p("add-cp1", [cl2, PUSH, a], r),
          _p("add-co1", [cl2, OUT22, a], r), _p("add-cpx", [cl2, [0x26] + a], r), _p("add-cn2", [cl2, NOPL, a, a], r),
          _p("add4-c2", [cl4, a, a], r), _p("sub-c2", [cl2, s, s], r), _p("sub-cn1", [cl2, NOPL, s], r),
          _p("cmp-c2", [cl2, c, c], r), _p("cmp-cn1", [cl2, NOPL, c], r), _p("cmp-co1", [cl2, OUT22, c], r)]
    vals = {"00": (0x00, 0x00), "ac": (0x09, 0x08), "cy": (0x90, 0x90), "b": (0x99, 0x99)}
    for on, op in (("a4a", [0x27]), ("a4s", [0x2F])):
        v += [_p(f"{on}-ls{k}", [op] * k + [NOPL]) for k in (1, 2, 3)]
        for vn, (x, y) in vals.items():
            pre = [[0xB0, x], [0x04, y]]
            ks = (1, 2, 3) if vn in ("00", "b") else (1,)
            v += [_p(f"{on}-{vn}{k}", pre + [op] * k + [NOPL]) for k in ks]
    return v


ROUNDS = {"r25a": round25a, "r25b": round25b, "r25c": round25c, "r25d": round25d}
