"""F5: internal RAM disabled, the forms the plain-store rule does not cover (the f5_wu_* program set;
build/overseer/wstore3). wstore2's frame: a lead, one instruction Y, MOV AW,[0890h], INC AW x 6, every
window in twin programs whose bytes differ in the PRC value alone (`_r1` 4Eh, `_r0` 0Eh).

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.wstore3 socket --socket-fitted [NAME ...] [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore3 sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore3 repeat | gate [-v] | emit

Groups (programs f5_wu_<group>_r1 / _r0), four leads (f0 f1 j0 j2) x two alignments:
    k       transfers and the stack: CALL near / far / register / memory, RET near / far / imm, RETI, BRK 3,
            BRK imm8, BRKV, POP R, POP PSW, POP sreg, PREPARE 8,0 / 8,1, DISPOSE, PUSH PSW / sreg / imm16 / imm8
    i       an immediate to memory: MOV m,imm in every EA form, ADD / CMP / TEST m,imm
    q       compares and strings: CMP m,r byte / word, TEST m,r, CMPBK, CMPM, REPNE CMPBKW / CMPM, MOVBK,
            REP MOVBKB, LDM, and RMW controls
    o       on-chip targets: SFR stores, reads, RMW and compares through DS1; the stack in FFE00h-FFEFFh
            (SS = F000h: internal RAM at RAMEN 1, the external page at RAMEN 0)
    v1      a spot check at 1 wait in block 0
Receipts: validation/v35s/receipts/f5-<name>-<backend>.json.
"""

from __future__ import annotations

import argparse
import sys

from . import onchip_t as oc
from . import phase as ph
from . import wstore2 as ws

CODE, STACK_TOP = oc.CODE, oc.STACK_TOP
SRC, DST, DIR, BWV, FOL = ws.SRC, ws.DST, ws.DIR, ws.BWV, ws.FOL
PRCV, LEADS, _FIL = ws.PRCV, ws.LEADS, ws._FIL
PTR = BWV + 8
PFX = "f5_wu"
D = [DIR & 0xFF, DIR >> 8]
P = [PTR & 0xFF, PTR >> 8]
_w = lambda v: [v & 0xFF, v >> 8]                         # noqa: E731

# name: (bytes or a function of the next instruction's offset, text, options)
# options: frame (pushed in the setup: psw ps ds0 nxt r, or a number), bp ("nxt" or a number), mem (the word
# at PTR <- the next instruction's offset), ss, sp, ds1, cw, vset (V set in the setup)
YS = {
    # ---- k: transfers and the stack
    "cn": ([0xE8, 0x00, 0x00], "CALL $+3", {}),
    "cf": (lambda n: [0x9A] + _w(n) + _w(CODE >> 4), "CALL far next", {}),
    "cr": ([0xFF, 0xD5], "CALL BP", {"bp": "nxt"}),
    "cm": ([0xFF, 0x16] + P, f"CALL word [{PTR:04X}h]", {"mem": 1}),
    "rn": ([0xC3], "RET", {"frame": ("nxt",)}),
    "rf": ([0xCB], "RET far", {"frame": ("ps", "nxt")}),
    "ri": ([0xC2, 0x02, 0x00], "RET 2", {"frame": (0, "nxt")}),
    "rt": ([0xCF], "RETI", {"frame": ("psw", "ps", "nxt")}),
    "bk": ([0xCC], "BRK 3   ; FINT ; RETI", {}),
    "bi": ([0xCD, 0x10], "BRK 16   ; FINT ; RETI", {}),
    "bv": ([0xCE], "BRKV   ; V set", {"vset": 1}),
    "or": ([0x61], "POP R", {"frame": ("r",)}),
    "of": ([0x9D], "POP PSW", {"frame": ("psw",)}),
    "os": ([0x1F], "POP DS0", {"frame": ("ds0",)}),
    "p0": ([0xC8, 0x08, 0x00, 0x00], "PREPARE 8, 0", {"bp": 0x0EF0}),
    "p1": ([0xC8, 0x08, 0x00, 0x01], "PREPARE 8, 1", {"bp": 0x0EF0}),
    "di": ([0xC9], "DISPOSE", {"bp": 0x0EF0}),
    "uf": ([0x9C], "PUSH PSW", {}),
    "us": ([0x1E], "PUSH DS0", {}),
    "ui": ([0x68, 0x34, 0x12], "PUSH 1234h", {}),
    "u8": ([0x6A, 0x12], "PUSH 12h", {}),
    "pu": ([0x50], "PUSH AW   ; control", {}),
    # ---- i: an immediate to memory
    "w0": ([0xC7, 0x04, 0x34, 0x12], "MOV word [IX], 1234h", {}),
    "w8": ([0xC7, 0x44, 0x02, 0x34, 0x12], "MOV word [IX+2], 1234h", {}),
    "w6": ([0xC7, 0x84, 0x02, 0x00, 0x34, 0x12], "MOV word [IX+0002h], 1234h", {}),
    "wx": ([0xC7, 0x00, 0x34, 0x12], "MOV word [BW+IX], 1234h", {}),
    "wd": ([0xC7, 0x06] + D + [0x34, 0x12], f"MOV word [{DIR:04X}h], 1234h", {}),
    "b0": ([0xC6, 0x04, 0x12], "MOV byte [IX], 12h", {}),
    "b8": ([0xC6, 0x44, 0x02, 0x12], "MOV byte [IX+2], 12h", {}),
    "bd": ([0xC6, 0x06] + D + [0x12], f"MOV byte [{DIR:04X}h], 12h", {}),
    "aw": ([0x81, 0x04, 0x34, 0x12], "ADD word [IX], 1234h", {}),
    "as": ([0x83, 0x04, 0x12], "ADD word [IX], 12h   ; sign-extended", {}),
    "ab": ([0x80, 0x04, 0x12], "ADD byte [IX], 12h", {}),
    "cw": ([0x81, 0x3C, 0x34, 0x12], "CMP word [IX], 1234h", {}),
    "cb": ([0x80, 0x3C, 0x12], "CMP byte [IX], 12h", {}),
    "tw": ([0xF7, 0x04, 0x34, 0x12], "TEST word [IX], 1234h", {}),
    "sw": ([0x89, 0x04], "MOV [IX], AW   ; control", {}),
    # ---- q: compares and strings
    "mr": ([0x39, 0x04], "CMP [IX], AW", {}),
    "mb": ([0x38, 0x04], "CMP [IX], AL", {}),
    "rm": ([0x3B, 0x04], "CMP AW, [IX]", {}),
    "te": ([0x85, 0x04], "TEST [IX], AW", {}),
    "kw": ([0xA7], "CMPBKW", {}),
    "kb": ([0xA6], "CMPBKB", {}),
    "sm": ([0xAF], "CMPMW", {}),
    "rk": ([0xF2, 0xA7], "REPNE CMPBKW   ; CW 4", {"cw": 4}),
    "rs": ([0xF2, 0xAF], "REPNE CMPMW   ; CW 4", {"cw": 4}),
    "mw": ([0xA5], "MOVBKW", {}),
    "mv": ([0xA4], "MOVBKB", {}),
    "rv": ([0xF3, 0xA4], "REP MOVBKB   ; CW 4", {"cw": 4}),
    "rl": ([0xF3, 0xAD], "REP LDMW   ; CW 4", {"cw": 4}),
    "ad": ([0x01, 0x04], "ADD [IX], AW   ; control", {}),
    "xc": ([0x87, 0x04], "XCH AW, [IX]   ; control", {}),
    "ld": ([0x8B, 0x04], "MOV AW, [IX]   ; control", {}),
    # ---- o: on-chip targets through DS1 = F000h; the stack in the internal RAM range
    "fs": ([0x26, 0xA2, 0x00, 0xFF], "MOV DS1:[FF00h], AL   ; P0's latch", {"ds1": oc.ON}),
    "fm": ([0x26, 0x88, 0x06, 0x00, 0xFF], "MOV DS1:[FF00h], AL   ; ModR/M", {"ds1": oc.ON}),
    "fi": ([0x26, 0xC6, 0x06, 0x00, 0xFF, 0x00], "MOV byte DS1:[FF00h], 00h", {"ds1": oc.ON}),
    "fr": ([0x26, 0xA0, 0x00, 0xFF], "MOV AL, DS1:[FF00h]", {"ds1": oc.ON}),
    "fn": ([0x26, 0xFE, 0x06, 0x00, 0xFF], "INC byte DS1:[FF00h]", {"ds1": oc.ON}),
    "fc": ([0x26, 0x38, 0x06, 0x00, 0xFF], "CMP DS1:[FF00h], AL", {"ds1": oc.ON}),
    "ew": ([0x26, 0xA3, 0x40, 0xFE], "MOV DS1:[FE40h], AW   ; internal RAM range", {"ds1": oc.ON}),
    "ec": ([0x26, 0x39, 0x06, 0x40, 0xFE], "CMP DS1:[FE40h], AW   ; internal RAM range", {"ds1": oc.ON}),
    "en": ([0x26, 0xFF, 0x06, 0x40, 0xFE], "INC word DS1:[FE40h]   ; internal RAM range", {"ds1": oc.ON}),
    "su": ([0x50], "PUSH AW   ; SS:SP = FFE7Eh", {"ss": oc.ON, "sp": 0xFE80}),
    "so": ([0x58], "POP AW   ; SS:SP = FFE70h", {"ss": oc.ON, "sp": 0xFE70}),
    "sc": ([0xE8, 0x00, 0x00], "CALL $+3   ; SS:SP = FFE7Eh", {"ss": oc.ON, "sp": 0xFE80}),
    "sr": ([0xC3], "RET   ; SS:SP in FFE00h-FFEFFh", {"ss": oc.ON, "sp": 0xFE80, "frame": ("nxt",)}),
}


def window(y, lead, al, r, w=0):
    yb, yt, opt = YS[y]
    meta = dict(y=y, lead=lead, al=al, r=r, w=w, sp=None)
    fix = []

    def nxt_imm(a, text):
        a.op([0xB8, 0, 0], text)
        fix.append(len(a.b) - 2)

    def setup(a):
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFEB, PRCV[r])
        oc.es_store(a, 0xFFE8, w, word=True)
        oc.seg(a, "DS1", opt.get("ds1", 0))
        if "ss" in opt:
            oc.seg(a, "SS", opt["ss"])
        a.mov_r("SP", opt.get("sp", STACK_TOP))
        a.mov_r("IX", SRC)
        a.mov_r("IY", DST)
        a.mov_r("BW", 0 if y == "wx" else ws.BWV)
        a.mov_r("CW", opt.get("cw", 1))
        a.op([0xFC], "CLR1 DIR")
        for f in opt.get("frame", ()):
            if f == "psw":
                a.op([0x9C], "PUSH PSW")
            elif f == "ps":
                a.op([0x0E], "PUSH PS")
            elif f == "ds0":
                a.op([0x1E], "PUSH DS0")
            elif f == "r":
                a.op([0x60], "PUSH R")
            elif f == "nxt":
                nxt_imm(a, "MOV AW, the follower's offset")
                a.op([0x50], "PUSH AW")
            else:
                a.mov_r("AW", f)
                a.op([0x50], "PUSH AW")
        if opt.get("bp") == "nxt":
            nxt_imm(a, "MOV AW, the follower's offset")
            a.op([0x8B, 0xE8], "MOV BP, AW")
        elif "bp" in opt:
            a.mov_r("BP", opt["bp"])
        if "mem" in opt:
            nxt_imm(a, "MOV AW, the follower's offset")
            a.op([0xA3] + P, f"MOV [{PTR:04X}h], AW")
        if "vset" in opt:
            a.op([0xB0, 0x7F], "MOV AL, 7Fh")
            a.op([0xFE, 0xC0], "INC AL   ; V set")

    def body(a):
        n = sum(3 if x == _FIL else len(x[0]) for x in LEADS[lead])
        if (len(a.b) + n & 1) != al:
            a.nop()
        ins = []

        def put(bs, text, tag):
            ins.append((CODE + len(a.b), tag, text.split("   ;")[0]))
            a.op(bs, text)
        for x in LEADS[lead]:
            if x == _FIL:
                ins.append((CODE + len(a.b), "L", "ROL BP, 16"))
                oc.fil(a)
            else:
                put(x[0], x[1], "L")
        if callable(yb):
            bs = yb(len(a.b) + len(yb(0)))
        else:
            bs = yb
        put(bs, yt + "   ; Y", "Y")
        nx = len(a.b)
        for i in fix:
            a.b[i:i + 2] = bytes(_w(nx))
        put([0xA1, FOL & 0xFF, FOL >> 8], f"MOV AW, [{FOL:04X}h]   ; the follower", "F")
        for i in range(6):
            put([0x40], "INC AW", "I")
        ins.append((CODE + len(a.b), "T", "ROL BP, 16"))
        oc.fil(a)
        meta["ins"] = ins
        a.op([0xFA], "DI")
        if "ss" in opt:
            oc.seg(a, "SS", 0)
            a.mov_r("SP", STACK_TOP)
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFE8, 0, word=True)
        oc.es_store(a, 0xFFEB, PRCV[1])
        a.mov_r("AW", 0)
    return ph.Window(meta, setup, body)


GRID = ("f0", "f1", "j0", "j2")
_K = ("cn", "cf", "cr", "cm", "rn", "rf", "ri", "rt", "bk", "bi", "bv", "or", "of", "os", "p0", "p1", "di", "uf", "us",
      "ui", "u8", "pu")
_I = ("w0", "w8", "w6", "wx", "wd", "b0", "b8", "bd", "aw", "as", "ab", "cw", "cb", "tw", "sw")
_Q = ("mr", "mb", "rm", "te", "kw", "kb", "sm", "rk", "rs", "mw", "mv", "rv", "rl", "ad", "xc", "ld")
_O = ("fs", "fm", "fi", "fr", "fn", "fc", "ew", "ec", "en", "su", "so", "sc", "sr")
_V = ("cn", "rn", "rt", "bk", "or", "p0", "uf", "w0", "aw", "cw", "mr", "kw", "mw", "ad", "fs", "pu")
GROUPS = {
    "k": [(y, l, al, 0) for y in _K for l in GRID for al in (0, 1)],
    "i": [(y, l, al, 0) for y in _I for l in GRID for al in (0, 1)],
    "q": [(y, l, al, 0) for y in _Q for l in GRID for al in (0, 1)],
    "o": [(y, l, al, 0) for y in _O for l in GRID for al in (0, 1)],
    "v1": [(y, l, al, 1) for y in _V for l in ("f0", "j0") for al in (0, 1)],
}


def programs():
    progs = {}
    for g, wins in GROUPS.items():
        for r in (1, 0):
            name = f"{PFX}_{g}_r{r}"
            progs[name] = ph.Program(name, [window(y, l, al, r, w) for y, l, al, w in wins],
                                     f"group {g}: lead ; Y ; MOV AW,[{FOL:04X}h] ; INC AW x 6 with PRC = {PRCV[r]:02X}h")
    return progs


windows, fmt, cell, kind_of = ws.windows, ws.fmt, ws.cell, ws.kind_of


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "repeat", "gate", "emit"))
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
        ph.run_set(names, "socket", a.tag, progs)
    elif a.action == "sim":
        ph.run_set(names, "sim", a.tag, progs)
    elif a.action in ("repeat", "gate"):
        ref, cand = ("socket", "socket-2") if a.action == "repeat" else (a.ref, a.cand)
        ok = True
        for n in names:
            ok &= ws.compare(n, ref, cand, progs, verbose=a.verbose)
        return 0 if ok else 1
    else:
        ph.emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
