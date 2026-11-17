"""Round 13.

r13a  fw-*   the fetch behind a write: a store (MOV [BW],imm16 / MOV [BW],AW / PUSH) behind a
             pad, followed by MOV r,imm16 / MOV r8,imm8 / NOP / MOV r,r / CLC / nothing
      dz-*   DBNZE / DBNZNE behind the long shift, two NOPs, CMP (Z = 1), INC (Z = 0); CW = 1
      cmi16, the mem,imm bit forms, REPC / REPNC
      xc-*   EXT / INS across a word boundary
      tj-*   the transfer residue: JMP / CALL r16 with BW loaded before M0 or 1 / 2 NOPs ahead,
             BRK imm8 and INT 3 with the vectors stored before M0, CALL far behind pads, far
             forms through memory, RETI (PSW F002h pushed: MD = 1)
r13n* interrupts: NMI across other trains (CBW, MOV r,r, NOP/CLC alternating, MOV r8,imm8) and
      NOP / CLC at W = 2 (the fetch phase against the train); INTP0 across RMW / load / store
      trains with three pulse widths; HALT release; NMI and INTP0 together
"""

from ..chains import blocks
from .gen import BODY_AT, M1I, NOP, RR, SLOW, q, train
from .gen_r8 import w16
from .gen_r9 import probe
from .gen_r12 import HANDLER, K

CLC = [0xF8]


def round13a():
    v = []
    stores = {"c7": [0xC7, 0x07, 0x34, 0x12], "mv": [0x89, 0x07], "pu": [0x50]}
    pads = {"0": [], "c": [CLC], "n": [NOP], "nn": [NOP, NOP]}
    fols = {"ri": [0xB8, 0x34, 0x12], "i8": [0xB3, 0x00], "nop": NOP, "rr": RR, "clc": CLC,
            "m": None}
    for sn, sc in stores.items():
        for pn, pad in pads.items():
            for fn, fc in fols.items():
                if sn != "c7" and (pn not in ("0", "n") or fn not in ("ri", "rr")):
                    continue
                body = [q(c, "pad") for c in pad] + [q(sc, "store")]
                if fc is not None:
                    body.append(q(fc, "fol"))
                v.append((f"fw-{sn}-{pn}-{fn}", body))
    preds = {"ls": [], "nop2": [NOP, NOP], "cmp": [[0x3B, 0xC0]], "inc": [[0x43]]}
    for pn, codes in preds.items():
        for bn, bc in {"dbnzne": [0xE0, 0x00], "dbnze": [0xE1, 0x00]}.items():
            v.append((f"dz-{pn}-{bn}", [q(c, "pred") for c in codes] + [q(bc, bn), q(NOP, "nop")]))
    for bn, bc in {"dbnzne": [0xE0, 0x00], "dbnze": [0xE1, 0x00]}.items():
        v.append((f"dz-cw1-{bn}", [q([0xB9, 0x01, 0x00], "pred"), q(bc, bn), q(NOP, "nop")]))
    forms = {"cmi16": [0x81, 0x3F, 0x34, 0x12], "cmi16d": [0x81, 0x7F, 0x10, 0x34, 0x12],
             "c1mi": [0x0F, 0x1A, 0x07, 0x03], "n1mi": [0x0F, 0x1E, 0x07, 0x03],
             "t1wmi": [0x0F, 0x19, 0x07, 0x03], "s1wmi": [0x0F, 0x1D, 0x07, 0x03]}
    for name, code in forms.items():
        v += probe(name, code)
    for n in (1, 2, 3):
        for name, code in {"repc-cmpbk": [0x65, 0xA6], "repnc-cmpbk": [0x64, 0xA6],
                           "repc-cmpm": [0x65, 0xAE], "repnc-cmpm": [0x64, 0xAE]}.items():
            cw = q([0xB9, n, 0x00], "mov_cw")
            v.append((f"{name}{n}-a", [cw, q(code, name)]))
            v.append((f"{name}{n}-s", [cw, q(code, name), q(SLOW, "slow")]))
    for off, n in ((1, 16), (5, 16), (9, 8), (9, 12), (9, 16), (12, 5), (12, 8), (12, 12),
                   (12, 16), (15, 2), (15, 8), (15, 16)):
        pre = {"_pre": [q([0xB3, off], "mov_bl")]}
        v.append((f"xc-ext-o{off}-n{n}", ([q([0x0F, 0x3B, 0xC3, n - 1], "exti")], None, pre)))
        v.append((f"xc-ins-o{off}-n{n}", ([q([0x0F, 0x39, 0xC3, n - 1], "insi")], None, pre)))

    def with_pre(fn, pre_len):
        """A body that needs its own address with `pre_len` bytes placed before M0."""
        return lambda parity: fn(BODY_AT[parity] + pre_len)

    for n in (0, 1):
        t = train(NOP, "nop", n)
        for name, op in (("jr", [0xFF, 0xE3]), ("callr", [0xFF, 0xD3])):
            v.append((f"tj-{name}-ls-{n}", with_pre(lambda a, t=t, op=op, name=name: (
                [q(op, name)] + t, None,
                {"_pre": [q(NOP, "nop"), q([0xBB] + w16(a + 2), "mov_bw")]}), 4)))
            for k in (1, 2):
                v.append((f"tj-{name}-n{k}-{n}", with_pre(lambda a, t=t, op=op, name=name, k=k: (
                    [q([0xBB] + w16(a + 5 + k), "mov_bw")] + train(NOP, "nop", k)
                    + [q(op, name)] + t), 0)))
        vec = lambda a, at: [q([0xC7, 0x06, at & 0xFF, at >> 8] + w16(a), "vec_ip"),
                             q([0xC7, 0x06, (at + 2) & 0xFF, (at + 2) >> 8, 0x00, 0x10],
                               "vec_ps")]
        v.append((f"tj-brk-{n}", with_pre(lambda a, t=t: (
            [q([0xCD, 0x40], "brk")] + t, None, {"_pre": vec(a + 2, 0x100)}), 12)))
        v.append((f"tj-int3-{n}", with_pre(lambda a, t=t: (
            [q([0xCC], "int3")] + t, None, {"_pre": vec(a + 1, 0x0C)}), 12)))
        for pn, pad in {"c": [CLC], "n": [NOP], "nn": [NOP, NOP]}.items():
            v.append((f"tj-callf-{pn}-{n}", with_pre(lambda a, t=t, pad=pad: (
                [q(c, "pad") for c in pad]
                + [q([0x9A] + w16(a + len(pad) + 5) + [0x00, 0x10], "callf")] + t), 0)))
        v.append((f"tj-jmpfm-{n}", with_pre(lambda a, t=t: (
            [q([0xFF, 0x2E, 0x00, 0x0C], "jmpfm")] + t, None, {"_pre": vec(a + 4, 0xC00)}), 12)))
        v.append((f"tj-callfm-{n}", with_pre(lambda a, t=t: (
            [q([0xFF, 0x1E, 0x00, 0x0C], "callfm")] + t, None, {"_pre": vec(a + 4, 0xC00)}), 12)))
        v.append((f"tj-reti-{n}", with_pre(lambda a, t=t: (
            [q([0x68, 0x02, 0xF0], "pushi"), q([0x68, 0x00, 0x10], "pushi"),
             q([0x68] + w16(a + 10), "pushi"), q([0xCF], "reti")] + t), 0)))
    return v


# ---- interrupts

def _setup(src):
    s = []
    if src in ("nmi", "both"):
        s += [q([0xC7, 0x06, 0x08, 0x00, 0x00, 0x00], "vec"),
              q([0xC7, 0x06, 0x0A, 0x00, 0x00, 0x10], "vec_ps")]
    if src in ("intp0", "both"):
        s += [q([0xC7, 0x06, 0x60, 0x00, 0x00, 0x00], "vec"),
              q([0xC7, 0x06, 0x62, 0x00, 0x00, 0x10], "vec_ps"),
              q([0xB8, 0x00, 0xF0], "mov_aw"), q([0x8E, 0xC0], "mov_ds1"),
              q([0x26, 0xC6, 0x06, 0x4C, 0xFF, 0x07], "exic0"),
              q([0xB8, 0x00, 0x00], "mov_aw"), q([0x8E, 0xC0], "mov_ds1")]
    s += [q([0xBA, 0x12, 0xFF], "mov_dw"), q([0xB0, 0x01], "mov_al")]
    if src in ("intp0", "both"):
        s.append(q([0xFB], "ei"))
    s += [q([0xEE], "event"), q([0xBA, 0x20, 0x00], "mov_dw")]
    if sum(len(i.code) for i in s) & 1:
        s.insert(0, q(NOP, "nop"))
    return s


def irq(name, src, body, lo, hi, waits=(0,), hold=400, step=1):
    out = []
    levels = {"nmi": {"NMI": 0}, "intp0": {"INTP0": 0}, "both": {"NMI": 0, "INTP0": 0}}[src]
    for w in waits:
        for r in range(lo, hi, step):
            d = 8 * (r + K[w] - 20)
            stim = {"entries": [{"event": 1, "delay": d, "hold": hold, "levels": levels}]}
            extra = {"_pre": _setup(src), "_post": HANDLER, "_stim": stim, "_waits": (w,)}
            out.append((f"{name}-{src}-v{w}-h{hold}-d{d}", ([q(c, "x") for c in body], None,
                                                              extra)))
    return out


TRAINS = {"cbw": [[0x98]] * 14, "rr": [RR] * 12, "alt": [NOP, CLC] * 8, "i8": [[0xB3, 0x00]] * 8,
          "nop": [NOP] * 12, "clc": [CLC] * 20}
MEMS = {"rmw": [[0x01, 0x07]] * 4 + [NOP], "ld": [[0x8B, 0x07]] * 6 + [NOP],
        "st": [[0x89, 0x07]] * 6 + [NOP], "nop": [NOP] * 12}


def round13n(which):
    v = []
    if which in ("cbw", "rr", "alt", "i8"):
        v += irq(f"n-{which}", "nmi", TRAINS[which], -2, 28)
    elif which in ("nop2", "clc2"):
        t = which[:-1]
        v += irq(f"n-{t}", "nmi", TRAINS[t], -2, 30, waits=(2,))
    elif which in ("rmw", "ld", "st"):
        for hold in ((80, 400, 4000) if which == "rmw" else (400,)):
            v += irq(f"p-{which}", "intp0", MEMS[which], -2, 50, hold=hold)
    elif which == "pnop":
        for hold in (80, 4000):
            v += irq("p-nop", "intp0", MEMS["nop"], -2, 34, hold=hold)
    elif which == "halt":
        for src in ("nmi", "intp0"):
            v += irq("h-halt", src, [NOP, [0xF4]], -10, 40, waits=(0, 1, 2), step=10)
    elif which == "both":
        v += irq("b-nop", "both", TRAINS["nop"], 0, 16, step=2)
    return v


WHICH = ("cbw", "rr", "alt", "i8", "nop2", "clc2", "rmw", "ld", "st", "pnop", "halt", "both")
ROUNDS = {"r13a": round13a, **{f"r13n{w}": (lambda w=w: round13n(w)) for w in WHICH}}
