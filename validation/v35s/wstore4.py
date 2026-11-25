"""F5: store timing with internal RAM disabled, the consumer's shapes (the f5_wv_* program set;
build/overseer/ramen-design). Twin programs whose bytes differ in the PRC value alone: `_r1` (PRC 4Eh, RAMEN 1)
and `_r0` (PRC 0Eh, RAMEN 0). Refresh off.

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.wstore4 socket --socket-fitted [NAME ...] [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore4 sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore4 repeat [NAME ...]      (socket / socket-2)
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore4 gate [NAME ...] [-v]   (socket / sim, whole windows)
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore4 pair [GROUP ...] [--ref socket]
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore4 emit

Groups (programs f5_wv_<group>_r1 / _r0):
    b       0 waits, code, stack and data in block 0 (wstore2's frame): byte stores at odd and even addresses
            (MOV [IX],AL with IX odd, A2 even / odd, STMB with IY odd, MOV [IX+3],AL, MOV byte [IX],imm8 and INC
            byte [IX] with IX odd) behind four leads, followed by MOV AW,[0890h] ; INC AW x 6; and four plain stores
            (MOV [IX],AW ; PUSH AW ; A3 ; MOV [IX],AL) followed by short instructions instead of the read (INC AW
            x 7; NOP x 3 ; INC x 4; MOV CW,AW x 2 ; INC x 4; the store again ; INC x 6) behind two leads
    r       REP STMW with CW 1, 2, 5, REP STMB with CW 3, REP MOVBKW with CW 1, 3 and REP MOVBKB with CW 3, code,
            stack and data in block 0 at 0, 1 and 2 waits, two leads, followed by MOV AW,[0890h] ; INC AW x 6
    c       wstore3's frames where rounds 1 to 3 have no data: CALL near / reg / mem / far, RETI, RET far, POP R,
            BRK 3 and PREPARE 8,1 at 1 and 2 waits behind f0, j0, pu, sb and at 0 waits behind pu, sb; PUSH R at 1
            and 2 waits
    d       BRK 3, BRKV, PREPARE 8,0 and 8,1 at 0 waits behind every lead f0 .. f3, j0 .. j4
    y0, ya, yb, yc
            the data in block 1 (20100h up, WTC field 3: 2 waits and READY, PMC1 bit 7), the code and the stack in
            block 0 at 0 waits or 1 wait; READY low from a block-1 cycle's /MREQ fall for 0 (y0: READY stays
            high), 10 (ya), 15 (yb) and 18.5 (yc) CPU clocks (harness version 3: registers C2h / C4h / C6h, read
            and write cycles of block 1). Shapes: REP STMW (CW 6); REP MOVBKW from block 0 (CW 4);
            `26 89 07 ; 26 89 57 02` three times; the same pair in a DBNZ loop of three; MOV [IX],AW ; CMP [IX],AW
            twice (DS0 in block 1); MOV DS1:[BW],AW four times; MOV DS1:[BW],AW ; PUSH AW twice. Each followed by
            INC AW x 6.
    e       (round 5) the REP compares ending on their condition and on the count: REPE / REPNE CMPBKW and REPE /
            REPNE CMPMW with CW 4 over arrays the window's setup writes, ending on the first, second or third
            element (e0 / e1 / e2) or on the count (ex: CW 3, the condition never met), and REPE CMPBKB / REPNE
            CMPMB ending on the third byte, at 0, 1 and 2 waits behind f0 and j0
    f       (round 5) CALL near, CALL far and PUSH AW behind a store lead whose block has its own waits: the lead
            is `26 89 07` (MOV DS1:[BW],AW) with DS1 = 2000h (block 1 at 0, 1, 2 waits: leads t0 t1 t2) or DS1 = 0
            (block 0, the code's and the stack's block: lead s0), the code and the stack at 0, 1 and 2 waits
    i       (round 5) group f's leads in front of instructions with operand bytes: MOV BW,imm16, MOV BL,imm8, ADD AW,imm16,
            PUSH imm16, BR near, BR short, the code at 0 and 2 waits
    g       (round 5) PREPARE 8,L for L = 0 .. 4 at 0, 1 and 2 waits behind f0, j0, pu, sb
    sn, s0 .. sa  (round 6, RAMEN 1 only) code fetches stretched by READY: ROL BP,16 (its sixth word is a commit
            word) behind f0 .. f3, j0, j1, then MOV DS1:[BW],AW into block 1 at 0 waits; sn: the code at 0, 1, 2 waits
            without READY; s0 .. sa: the code at 2 waits and READY, READY low 0, 2, 3, 4, 5, 6, 7, 8, 10 clocks from
            /MREQ's fall of a block-0 cycle
    t02 .. t14  (round 7, RAMEN 1 only) groups s's window with READY low 1.0, 1.5 .. 7.0 clocks (tNN: NN half
            clocks): the four windows whose commit word meets a chained fetch (f0 al1, f1 al0, f2 al1, f3 al0) and
            two controls (f0 al0, j0 al0)
    u1 .. u8  (round 8, RAMEN 1 only) groups y's shapes sc (MOV [IX],AW ; CMP [IX],AW twice) and rm (REP MOVBKW)
            with the data in block 1 at 2 waits and READY, READY low 1, 2, 3, 4, 5, 6, 8 clocks from /MREQ's fall of
            a block-1 cycle: a data read whose F waits for the datum under a swept READY
    ha, hc  (round 5) the REP STM / REP MOVBK exit with a fetch running: the code in block 0 at 2 waits and READY
            (READY low 10 (ha) or 12.5 (hc) clocks from /MREQ's fall of a block-0 cycle), the destination in
            block 1 at 0 waits (DS1 = 2000h); REP STMW CW 1 / 2, REP STMB CW 1, REP MOVBKW CW 1 / 2 behind f0 and
            j0 .. j4
Receipts: validation/v35s/receipts/f5-<name>-<backend>.json.
"""

from __future__ import annotations

import argparse
import sys

from . import onchip_t as oc
from . import phase as ph
from . import wstore2 as w2
from .wtc import pat

CODE, STACK_TOP = oc.CODE, oc.STACK_TOP
SRC, DST, DIR, BWV, FOL = w2.SRC, w2.DST, w2.DIR, w2.BWV, w2.FOL
PRCV = w2.PRCV
PFX = "f5_wv"
D1SEG, D1OFF = 0x2000, 0x0100          # the READY block's data: 20100h
CLK = 32

D = [DIR & 0xFF, DIR >> 8]
DO = [(DIR + 1) & 0xFF, (DIR + 1) >> 8]
YS = {
    "sbo": ([0x88, 0x04], "MOV [IX], AL   ; IX odd", {"ix": SRC + 1}),
    "a2": ([0xA2] + D, f"MOV [{DIR:04X}h], AL   ; A2, even", {}),
    "a2o": ([0xA2] + DO, f"MOV [{DIR + 1:04X}h], AL   ; A2, odd", {}),
    "tbo": ([0xAA], "STMB   ; IY odd", {"iy": DST + 1}),
    "sb3": ([0x88, 0x44, 0x03], "MOV [IX+3], AL   ; odd", {}),
    "ibo": ([0xC6, 0x04, 0x12], "MOV byte [IX], 12h   ; IX odd", {"ix": SRC + 1}),
    "nbo": ([0xFE, 0x04], "INC byte [IX]   ; IX odd", {"ix": SRC + 1}),
    "sw": ([0x89, 0x04], "MOV [IX], AW", {}),
    "pu": ([0x50], "PUSH AW", {}),
    "a3": ([0xA3] + D, f"MOV [{DIR:04X}h], AW   ; A3", {}),
    "sb": ([0x88, 0x04], "MOV [IX], AL", {}),
    # group r: the REP string stores by count
    "rs1": ([0xF3, 0xAB], "REP STMW   ; CW 1", {"cw": 1}),
    "rs2": ([0xF3, 0xAB], "REP STMW   ; CW 2", {"cw": 2}),
    "rs5": ([0xF3, 0xAB], "REP STMW   ; CW 5", {"cw": 5}),
    "rb3": ([0xF3, 0xAA], "REP STMB   ; CW 3", {"cw": 3}),
    "rm1": ([0xF3, 0xA5], "REP MOVBKW   ; CW 1", {"cw": 1}),
    "rm3": ([0xF3, 0xA5], "REP MOVBKW   ; CW 3", {"cw": 3}),
    "rv3": ([0xF3, 0xA4], "REP MOVBKB   ; CW 3", {"cw": 3}),
}
INC = ([0x40], "INC AW")
FOLS = {
    "rd": [([0xA1, FOL & 0xFF, FOL >> 8], f"MOV AW, [{FOL:04X}h]   ; the follower")] + [INC] * 6,
    "in": [INC] * 7,
    "np": [([0x90], "NOP")] * 3 + [INC] * 4,
    "mr": [([0x8B, 0xC8], "MOV CW, AW")] * 2 + [INC] * 4,
    "st": None,                         # the store again, then INC x 6
}
GRID_S = w2.GRID_S
B_WINS = ([(y, l, al, "rd") for y in ("sbo", "a2", "a2o", "tbo", "sb3", "ibo", "nbo") for l in GRID_S for al in (0, 1)]
          + [(y, l, al, f) for y in ("sw", "pu", "a3", "sb") for f in ("in", "np", "mr", "st")
             for l in ("f0", "j0") for al in (0, 1)])

ES = [0x26]
PAIR = [(ES + [0x89, 0x07], "MOV DS1:[BW], AW"), (ES + [0x89, 0x57, 0x02], "MOV DS1:[BW+2], DW   ; DW is the frame's marker port")]
SHAPES = {
    "rs": ([([0xF3, 0xAB], "REP STMW   ; CW 6")], {"cw": 6}),
    "rm": ([([0xF3, 0xA5], "REP MOVBKW   ; CW 4, the source in block 0")], {"cw": 4}),
    "pr": (PAIR * 3, {}),
    "pl": (PAIR + [([0x83, 0xC3, 0x04], "ADD BW, 4"), ([0xE2, 0xF4], "DBNZ $-10   ; three times")], {"cw": 3}),
    "sc": ([([0x89, 0x04], "MOV [IX], AW"), ([0x39, 0x04], "CMP [IX], AW")] * 2, {"ds0": D1SEG, "ix": D1OFF}),
    "ss": ([PAIR[0]] * 4, {}),
    "sp": ([PAIR[0], ([0x50], "PUSH AW")] * 2, {}),
}
READY = {"y0": None, "ya": 10.0, "yb": 15.0, "yc": 18.5}      # READY low, CPU clocks from /MREQ's fall
Y_WINS = [(s, l, al, wc) for s in SHAPES for wc in (0, 1) for l in ("f0", "j0") for al in (0, 1)]


def _lead(a, lead, al, ins):
    n = sum(3 if x == w2._FIL else len(x[0]) for x in w2.LEADS[lead])
    if (len(a.b) + n & 1) != al:
        a.nop()
    for x in w2.LEADS[lead]:
        if x == w2._FIL:
            ins.append((CODE + len(a.b), "L", "ROL BP, 16"))
            oc.fil(a)
        else:
            ins.append((CODE + len(a.b), "L", x[1].split("   ;")[0]))
            a.op(x[0], x[1])


R_WINS = [(y, l, al, "rd", w) for y in ("rs1", "rs2", "rs5", "rb3", "rm1", "rm3", "rv3") for w in (0, 1, 2)
          for l in ("f0", "j0") for al in (0, 1)]


def bwindow(y, lead, al, r, fol, w=0):
    yb, yt, opt = YS[y]
    meta = dict(y=f"{y}.{fol}" if fol != "rd" else y, lead=lead, al=al, r=r, w=w, sp=None)

    def setup(a):
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFEB, PRCV[r])
        oc.es_store(a, 0xFFE8, w, word=True)
        oc.seg(a, "DS1", 0)
        a.mov_r("SP", STACK_TOP)
        a.mov_r("IX", opt.get("ix", SRC))
        a.mov_r("IY", opt.get("iy", DST))
        a.mov_r("BW", BWV)
        a.mov_r("CW", opt.get("cw", 1))
        a.op([0xFC], "CLR1 DIR")

    def body(a):
        ins = []
        _lead(a, lead, al, ins)
        ins.append((CODE + len(a.b), "Y", yt.split("   ;")[0]))
        a.op(yb, yt + "   ; Y")
        for bs, text in (FOLS[fol] or [(yb, yt + "   ; Y again")] + [INC] * 6):
            ins.append((CODE + len(a.b), "F", text.split("   ;")[0]))
            a.op(bs, text)
        ins.append((CODE + len(a.b), "T", "ROL BP, 16"))
        oc.fil(a)
        meta["ins"] = ins
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFE8, 0, word=True)
        oc.es_store(a, 0xFFEB, PRCV[1])
        a.mov_r("AW", 0)
    return ph.Window(meta, setup, body)


def ywindow(shape, lead, al, r, wc):
    seq, opt = SHAPES[shape]
    meta = dict(y=shape, lead=lead, al=al, r=r, w=wc, sp=None)

    def setup(a):
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFEB, PRCV[r])
        oc.es_store(a, 0xFF0A, 0x80)                         # PMC1 bit 7: P17 is READY
        oc.es_store(a, 0xFFE8, 0x000C | wc, word=True)       # block 1: field 3 (2 waits and READY); block 0: wc
        oc.seg(a, "DS1", D1SEG)
        if "ds0" in opt:
            oc.seg(a, "DS0", opt["ds0"])
        a.mov_r("SP", STACK_TOP)
        a.mov_r("IX", opt.get("ix", SRC))
        a.mov_r("IY", D1OFF)
        a.mov_r("BW", D1OFF)
        a.mov_r("CW", opt.get("cw", 1))
        a.op([0xFC], "CLR1 DIR")

    def body(a):
        ins = []
        _lead(a, lead, al, ins)
        for bs, text in seq:
            ins.append((CODE + len(a.b), "Y", text.split("   ;")[0]))
            a.op(bs, text)
        for i in range(6):
            ins.append((CODE + len(a.b), "F", "INC AW"))
            a.op(*INC)
        ins.append((CODE + len(a.b), "T", "ROL BP, 16"))
        oc.fil(a)
        meta["ins"] = ins
        if "ds0" in opt:
            oc.seg(a, "DS0", 0)
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFE8, 0, word=True)
        oc.es_store(a, 0xFF0A, 0x00)
        oc.es_store(a, 0xFFEB, PRCV[1])
        a.mov_r("AW", 0)
    return ph.Window(meta, setup, body)


# ------------------------------------------------------------------ round 5: groups e, f, g, h
_w16 = lambda v: [v & 0xFF, v >> 8]                         # noqa: E731
U, V = 0x1111, 0x2222
XLEADS = dict(w2.LEADS)
_SL = (ES + [0x89, 0x07], "MOV DS1:[BW], AW   ; lead")
XLEADS.update({k: (w2._FIL, _SL) for k in ("s0", "t0", "t1", "t2")})
# name: (bytes or a function of the next instruction's offset, text, options: cw, bp, prep)
XS = {
    "cn": ([0xE8, 0x00, 0x00], "CALL $+3", {}),
    "cf": (lambda n: [0x9A] + _w16(n) + _w16(CODE >> 4), "CALL far next", {}),
    "pu": ([0x50], "PUSH AW", {}),
    "es": (ES + [0x89, 0x07], "MOV DS1:[BW], AW", {}),
    "mi": ([0xBB, 0x34, 0x12], "MOV BW, 1234h", {}),
    "ib": ([0xB3, 0x12], "MOV BL, 12h", {}),
    "ai": ([0x05, 0x34, 0x12], "ADD AW, 1234h", {}),
    "ui": ([0x68, 0x34, 0x12], "PUSH 1234h", {}),
    "bn": ([0xE9, 0x00, 0x00], "BR near $+3", {}),
    "bs": ([0xEB, 0x00], "BR short $+2", {}),
    "rs1": ([0xF3, 0xAB], "REP STMW   ; CW 1", {"cw": 1}),
    "rs2": ([0xF3, 0xAB], "REP STMW   ; CW 2", {"cw": 2}),
    "rb1": ([0xF3, 0xAA], "REP STMB   ; CW 1", {"cw": 1}),
    "rm1": ([0xF3, 0xA5], "REP MOVBKW   ; CW 1", {"cw": 1}),
    "rm2": ([0xF3, 0xA5], "REP MOVBKW   ; CW 2", {"cw": 2}),
}
for _l in range(5):
    XS[f"l{_l}"] = ([0xC8, 0x08, 0x00, _l], f"PREPARE 8, {_l}", {"bp": 0x0EF0})
# the REP compares: (the opcode bytes, text, block compare?, the condition met on equal?)
_RC = {"ek": ([0xF3, 0xA7], "REPE CMPBKW", True, False), "nk": ([0xF2, 0xA7], "REPNE CMPBKW", True, True),
       "es": ([0xF3, 0xAF], "REPE CMPMW", False, False), "ns": ([0xF2, 0xAF], "REPNE CMPMW", False, True),
       "eb": ([0xF3, 0xA6], "REPE CMPBKB", True, False), "nb": ([0xF2, 0xAE], "REPNE CMPMB", False, True)}
for _n, (_b, _t, _blk, _eq) in _RC.items():
    for _k in (0, 1, 2, None):
        # the arrays: the compare's two sides (SRC, or AW = U, against DST) equal in every element (REPE) or in
        # none (REPNE), element _k the other way round: the element the instruction ends on
        XS[_n + ("x" if _k is None else str(_k))] = (
            _b, f"{_t}   ; CW {3 if _k is None else 4}, " + ("to the count" if _k is None else f"ends on element {_k}"),
            {"cw": 3 if _k is None else 4, "prep": (_blk, _eq, _k)})


def _prep(a, blk, eq, k):
    def fill(base, v):
        a.mov_r("AW", v)
        a.mov_r("IY", base)
        a.mov_r("CW", 4)
        a.op([0xF3, 0xAB], f"REP STMW   ; four words at {base:04X}h <- {v:04X}h")
    if blk:
        fill(SRC, U)
    fill(DST, V if eq else U)
    if k is not None:
        a.op([0xC7, 0x06] + _w16(DST + 2 * k) + _w16(U if eq else V),
             f"MOV word [{DST + 2 * k:04X}h], {U if eq else V:04X}h   ; the element the compare ends on")


def xwindow(y, lead, al, r, w, wl=0, ds1=0, ready=False):
    """A lead, Y, MOV AW,[0890h], INC AW x 6: block 0 at `w` waits (with `ready`: 2 waits and READY), block 1 at
    `wl`, DS1 = `ds1` in the window."""
    yb, yt, opt = XS[y]
    meta = dict(y=y, lead=lead, al=al, r=r, w=w, sp=None)

    def setup(a):
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFEB, PRCV[r])
        if ready:
            oc.es_store(a, 0xFF0A, 0x80)                     # PMC1 bit 7: P17 is READY
        oc.es_store(a, 0xFFE8, wl << 2 | (3 if ready else w), word=True)
        oc.seg(a, "DS1", 0)
        a.op([0xFC], "CLR1 DIR")
        if "prep" in opt:
            _prep(a, *opt["prep"])
        if ds1:
            oc.seg(a, "DS1", ds1)
        a.mov_r("SP", STACK_TOP)
        a.mov_r("IX", SRC)
        a.mov_r("IY", DST)
        a.mov_r("BW", BWV)
        a.mov_r("CW", opt.get("cw", 1))
        if "bp" in opt:
            a.mov_r("BP", opt["bp"])
        a.mov_r("AW", U)

    def body(a):
        ins = []
        if "prep" in opt:
            a.mov_r("AW", U)                # (the frame's marker port write in front of the body uses AW)
        n = sum(3 if x == w2._FIL else len(x[0]) for x in XLEADS[lead])
        if (len(a.b) + n & 1) != al:
            a.nop()
        for x in XLEADS[lead]:
            if x == w2._FIL:
                ins.append((CODE + len(a.b), "L", "ROL BP, 16"))
                oc.fil(a)
            else:
                ins.append((CODE + len(a.b), "L", x[1].split("   ;")[0]))
                a.op(x[0], x[1])
        bs = yb(len(a.b) + len(yb(0))) if callable(yb) else yb
        ins.append((CODE + len(a.b), "Y", yt.split("   ;")[0]))
        a.op(bs, yt + "   ; Y")
        for bs, text in FOLS["rd"]:
            ins.append((CODE + len(a.b), "F", text.split("   ;")[0]))
            a.op(bs, text)
        ins.append((CODE + len(a.b), "T", "ROL BP, 16"))
        oc.fil(a)
        meta["ins"] = ins
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFE8, 0, word=True)
        if ready:
            oc.es_store(a, 0xFF0A, 0x00)
        oc.es_store(a, 0xFFEB, PRCV[1])
        a.mov_r("AW", 0)
    return ph.Window(meta, setup, body)


E_WINS = ([(n + k, l, al, w) for n in ("ek", "nk", "es", "ns") for k in ("0", "1", "2", "x") for w in (0, 1, 2)
           for l in ("f0", "j0") for al in (0, 1)]
          + [(n + "1", l, al, w) for n in ("eb", "nb") for w in (0, 1, 2) for l in ("f0", "j0") for al in (0, 1)])
F_WINS = ([(y, "s0", al, w, 0, 0) for y in ("cn", "cf", "pu") for w in (0, 1, 2) for al in (0, 1)]
          + [(y, f"t{wl}", al, w, wl, D1SEG) for y in ("cn", "cf", "pu") for w in (0, 1, 2) for wl in (0, 1, 2)
             for al in (0, 1)])
I_WINS = ([(y, "s0", al, w, 0, 0) for y in ("mi", "ib", "ai", "ui", "bn", "bs") for w in (0, 2) for al in (0, 1)]
          + [(y, f"t{wl}", al, w, wl, D1SEG) for y in ("mi", "ib", "ai", "ui", "bn", "bs") for w in (0, 2) for wl in (0, 1, 2)
             for al in (0, 1)])
G_WINS = [(f"l{k}", l, al, w) for k in range(5) for w in (0, 1, 2) for l in ("f0", "j0", "pu", "sb") for al in (0, 1)]
H_WINS = [(y, l, al, 2) for y in ("rs1", "rs2", "rb1", "rm1", "rm2") for l in ("f0", "j0", "j1", "j2", "j3", "j4")
          for al in (0, 1)]
# (round 6) code fetches stretched by READY: the filler's commit word against a chained fetch
S_LEADS = ("f0", "f1", "f2", "f3", "j0", "j1")
S_WINS = [("es", l, al, 2) for l in S_LEADS for al in (0, 1)]
SN_WINS = [("es", l, al, w) for w in (0, 1, 2) for l in S_LEADS for al in (0, 1)]
SREADY = {"s0": None, "s2": 2.0, "s3": 3.0, "s4": 4.0, "s5": 5.0, "s6": 6.0, "s7": 7.0, "s8": 8.0, "sa": 10.0}
# (round 7) the READY hold in half-clock steps on the four windows whose commit word meets a chained fetch, and
# two controls
T_WINS = [("es", l, al, 2) for l, al in (("f0", 1), ("f1", 0), ("f2", 1), ("f3", 0), ("f0", 0), ("j0", 0))]
TREADY = {f"t{k:02d}": k / 2 for k in range(2, 15)}        # READY low 1.0, 1.5 .. 7.0 clocks
# (round 8) a READY-timed data read: groups y's shapes sc (store, compare: a read whose F waits for the datum) and
# rm (REP MOVBKW from block 0) with the data in block 1 at 2 waits and READY, the hold swept in whole clocks
U_WINS = [(sh, l, al, wc) for sh in ("sc", "rm") for wc in (0, 1) for l in ("f0", "j0") for al in (0, 1)]
UREADY = {"u1": 1.0, "u2": 2.0, "u3": 3.0, "u4": 4.0, "u5": 5.0, "u6": 6.0, "u8": 8.0}
HREADY = {"ha": 10.0, "hc": 12.5}       # READY low, CPU clocks from /MREQ's fall of a block-0 cycle


class Program(ph.Program):
    """phase's frame with the READY block's page loaded and the /MREQ-timed READY setting (`m`)."""
    m = None

    def build(self):
        if not self._built:
            b = super().build()
            b["segments"][0x20000] = bytes(pat(0x20000 | o) for o in range(0x1000))
        return self._built


C_Y = ("cn", "cr", "cm", "cf", "rt", "rf", "or", "bk", "p1")
C_POP = ("rt", "rf", "or")          # the forms that take a frame from the stack: no push lead in front (rd instead)
C_WINS = ([(y, "rd" if l == "pu" and y in C_POP else l, al, w) for y in C_Y for w in (1, 2)
           for l in ("f0", "j0", "pu", "sb") for al in (0, 1)]
          + [(y, "rd" if l == "pu" and y in C_POP else l, al, 0) for y in C_Y for l in ("pu", "sb") for al in (0, 1)])
CP_WINS = [("pr", l, al, w) for w in (1, 2) for l in ("f0", "j0") for al in (0, 1)]
D_WINS = [(y, l, al, 0) for y in ("bk", "bv", "p0", "p1") for l in ("f0", "f1", "f2", "f3", "j0", "j1", "j2", "j3", "j4")
          for al in (0, 1)]


def programs():
    from . import wstore3 as w3
    progs = {}
    for r in (1, 0):
        name = f"{PFX}_c_r{r}"
        progs[name] = Program(name, [w3.window(y, l, al, r, w) for y, l, al, w in C_WINS]
                              + [w2.window(y, l, al, r, w) for y, l, al, w in CP_WINS],
                              f"group c: CALL kinds, RETI, RET far, POP R, BRK 3, PREPARE 8,1 and PUSH R at 1 and 2 waits "
                              f"and behind store leads, with PRC = {PRCV[r]:02X}h")
        name = f"{PFX}_d_r{r}"
        progs[name] = Program(name, [w3.window(y, l, al, r, w) for y, l, al, w in D_WINS],
                              f"group d: BRK 3, BRKV, PREPARE 8,0 / 8,1 behind every lead, with PRC = {PRCV[r]:02X}h")
    for r in (1, 0):
        name = f"{PFX}_b_r{r}"
        progs[name] = Program(name, [bwindow(y, l, al, r, f) for y, l, al, f in B_WINS],
                              f"group b: byte stores at odd addresses and short followers with PRC = {PRCV[r]:02X}h")
    for r in (1, 0):
        name = f"{PFX}_r_r{r}"
        progs[name] = Program(name, [bwindow(y, l, al, r, f, w) for y, l, al, f, w in R_WINS],
                              f"group r: REP STM / REP MOVBK by count, block 0 at 0, 1 and 2 waits, with PRC = {PRCV[r]:02X}h")
    for r in (1, 0):
        name = f"{PFX}_e_r{r}"
        progs[name] = Program(name, [xwindow(y, l, al, r, w) for y, l, al, w in E_WINS],
                              f"group e: the REP compares ending on their condition and on the count at 0, 1 and 2 "
                              f"waits, with PRC = {PRCV[r]:02X}h")
        name = f"{PFX}_f_r{r}"
        progs[name] = Program(name, [xwindow(y, l, al, r, w, wl, ds1) for y, l, al, w, wl, ds1 in F_WINS],
                              f"group f: CALL near / far and PUSH AW behind a store lead in a block with its own "
                              f"waits, with PRC = {PRCV[r]:02X}h")
        name = f"{PFX}_i_r{r}"
        progs[name] = Program(name, [xwindow(y, l, al, r, w, wl, ds1) for y, l, al, w, wl, ds1 in I_WINS],
                              f"group i: instructions with operand bytes and no access of their own behind a store "
                              f"lead in a block with its own waits, with PRC = {PRCV[r]:02X}h")
        name = f"{PFX}_g_r{r}"
        progs[name] = Program(name, [xwindow(y, l, al, r, w) for y, l, al, w in G_WINS],
                              f"group g: PREPARE 8,L for L = 0 .. 4 at 0, 1 and 2 waits, with PRC = {PRCV[r]:02X}h")
    name = f"{PFX}_sn_r1"
    progs[name] = Program(name, [xwindow(y, l, al, 1, w, 0, D1SEG) for y, l, al, w in SN_WINS],
                          "group sn: the filler and MOV DS1:[BW],AW (block 1 at 0 waits), the code in block 0 at 0, 1, 2 "
                          "waits, no READY (the control of groups s0 .. sa), PRC = 4Eh")
    for g, hold in SREADY.items():
        name = f"{PFX}_{g}_r1"
        p = Program(name, [xwindow(y, l, al, 1, w, 0, D1SEG, ready=True) for y, l, al, w in S_WINS],
                    f"group {g}: the filler and MOV DS1:[BW],AW (block 1 at 0 waits), the code in block 0 at 2 waits and "
                    f"READY, READY low {hold if hold else 0} clocks from /MREQ's fall of a block-0 cycle, PRC = 4Eh")
        p.m = (0, round(hold * CLK), 3, 0x01) if hold else None
        progs[name] = p
    for g, hold in TREADY.items():
        name = f"{PFX}_{g}_r1"
        p = Program(name, [xwindow(y, l, al, 1, w, 0, D1SEG, ready=True) for y, l, al, w in T_WINS],
                    f"group {g}: groups s's window (f0 al1, f1 al0, f2 al1, f3 al0 and the controls f0 al0, j0 al0), "
                    f"READY low {hold} clocks from /MREQ's fall of a block-0 cycle, PRC = 4Eh")
        p.m = (0, round(hold * CLK), 3, 0x01)
        progs[name] = p
    for g, hold in UREADY.items():
        name = f"{PFX}_{g}_r1"
        p = Program(name, [ywindow(sh, l, al, 1, wc) for sh, l, al, wc in U_WINS],
                    f"group {g}: groups y's shapes sc and rm, the data in block 1 at 2 waits and READY, READY low "
                    f"{hold} clocks from /MREQ's fall of a block-1 cycle, PRC = 4Eh")
        p.m = (0, round(hold * CLK), 3, 0x02)
        progs[name] = p
    for g, hold in HREADY.items():
        for r in (1, 0):
            name = f"{PFX}_{g}_r{r}"
            p = Program(name, [xwindow(y, l, al, r, w, 0, D1SEG, ready=True) for y, l, al, w in H_WINS],
                        f"group {g}: REP STM / REP MOVBK with the code in block 0 at 2 waits and READY (low {hold} "
                        f"clocks from /MREQ's fall), the destination in block 1 at 0 waits, with PRC = {PRCV[r]:02X}h")
            p.m = (0, round(hold * CLK), 3, 0x01)
            progs[name] = p
    for g, hold in READY.items():
        for r in (1, 0):
            name = f"{PFX}_{g}_r{r}"
            p = Program(name, [ywindow(s, l, al, r, wc) for s, l, al, wc in Y_WINS],
                        f"group {g}: the data in block 1 at 2 waits and READY, READY low "
                        f"{hold if hold else 0} clocks from /MREQ's fall, with PRC = {PRCV[r]:02X}h")
            # (delay, hold in ticks, trigger: read and write cycles, blocks: block 1)
            p.m = (0, round(hold * CLK), 3, 0x02) if hold else None
            progs[name] = p
    return progs


def run_set(names, backend, tag, progs):
    """phase.run_set with the /MREQ-timed READY registers written for each program."""
    from .ready import set_m
    from .traps import _board, _close_board, _sim, _stim
    lane = "socket" if backend == "socket" else "model"
    if backend == "socket":
        transport, harness = _board()
    try:
        for name in names:
            prog = progs[name]
            if backend != "socket":
                transport, harness = _sim()
            try:
                _stim(harness, prog)
                set_m(harness, prog.m)
                rec = ph.run_one(harness, prog, lane)
                set_m(harness, None)
            finally:
                if backend != "socket":
                    transport.close()
            ph._stamp(rec, backend)
            rec["ready_m"] = list(prog.m) if prog.m else None
            ph._save(rec, name, backend + tag)
            print(f"{name}: {backend}{tag} {'PASS' if rec['passed'] else 'FAIL'} "
                  f"status=0x{rec['status']:04x} total={rec['total']} records={len(rec['trace'])} "
                  f"replay={rec['replay']} residual={rec['stitch_residual']}", flush=True)
    finally:
        if backend == "socket":
            _close_board(transport, harness)


windows, cell, fmt, compare = w2.windows, w2.cell, w2.fmt, w2.compare


def pair(group, backend, progs):
    names = [f"{PFX}_{group}_r1", f"{PFX}_{group}_r0"]
    wa, wb = (windows(ph.load(n, backend), progs[n]) for n in names)
    pw = progs[names[0]].windows
    print(f"group {group} [{backend}]: {len(wa)}/{len(pw)} and {len(wb)}/{len(pw)} windows")
    for k, p in enumerate(pw):
        m = p.meta
        head = f"{k:3d} {m['y']:6s} {m['lead']:2s} al {m['al']} w{m['w']}"
        if k not in wa or k not in wb:
            print(head + ": missing")
            continue
        a, b = w2.line(wa[k]), w2.line(wb[k])
        if a == b:
            print(f"{head} =  {a}")
        else:
            print(f"{head} r1 {a}")
            print(f"{'':{len(head)}s} r0 {b}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "pair", "repeat", "gate", "emit"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--socket-fitted", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    progs = programs()
    names = a.names or list(progs)
    if a.action == "socket":
        if not a.socket_fitted:
            p.error("the socket action needs --socket-fitted")
        run_set(names, "socket", a.tag, progs)
    elif a.action == "sim":
        run_set(names, "sim", a.tag, progs)
    elif a.action == "pair":
        for g in a.names or ["b", "r", "c", "d", "e", "f", "i", "g"] + list(HREADY) + list(READY):
            pair(g, a.ref + a.tag, progs)
    elif a.action in ("repeat", "gate"):
        ref, cand = ("socket", "socket-2") if a.action == "repeat" else (a.ref, a.cand)
        ok = True
        for n in names:
            ok &= compare(n, ref, cand, progs, verbose=a.verbose)
        return 0 if ok else 1
    else:
        ph.emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
