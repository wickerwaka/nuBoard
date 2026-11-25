"""F5: the RAMEN 1 leftovers (the f5_wx_* program set; build/overseer/r1-left). wstore3's frame (a lead, one
instruction Y, MOV AW,[0890h], INC AW x 6, the filler) with PRC = 4Eh, refresh off, code, stack and data in
block 0.

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.r1left socket --socket-fitted [NAME ...] [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.r1left sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.r1left repeat | gate [-v] | emit | rfm

Groups (programs f5_wx_<group>_r1):
    a       BRKV with V set behind a full queue (leads g0 .. g3: the filler, INC CH from 7Fh, 0 .. 3 NOPs) and
            behind the emptied queue (j0 .. j4), BRKV with V clear behind the same leads, at 0 waits; both at 1
            and 2 waits behind g0 and j0; BRK 3 behind g0 .. g3 as the control
    b       instructions that release operand bytes behind the emptied queue (j0 j1 j2) and f0: PREPARE 8,0 /
            8,1, MOV BW,imm16, ADD AW,imm16, MOV BL,imm8, PUSH imm16, BR near, TEST BW,imm16, ADD BW,imm16
            (seven bytes held when the release comes: does a fetch start on the releasing clock?)
    c       far transfers that change PS (the target the same linear address in segment 0FFFh, so a fetch of
            the old stream issued with the new PS shows 10h lower): BR far, CALL far, RET far, RET far imm16,
            RETI, BR far [mem], CALL far [mem]; each window ends with BR far back to segment 1000h
    e       RET far imm16 within the segment (the corpus's shape) behind f0 .. f3, j0 .. j4, sb, rd, and at 1
            and 2 waits behind f0, j0
    d       BRKCS BW (bank 5, its vector PC a RETRBI stub behind the window) at 0, 1 and 2 waits
    q0 .. q15  (one short program each) the prelude's RFM store behind twelve fillers and ROL BP,k: the
            refresh timer's phase against the store swept (refresh is on until the store; the simulation
            does not serve refresh)
Receipts: validation/v35s/receipts/f5-<name>-<backend>.json.
"""

from __future__ import annotations

import argparse
import sys

from . import onchip_t as oc
from . import phase as ph
from . import wstore2 as w2

CODE, STACK_TOP = oc.CODE, oc.STACK_TOP
SRC, DST, DIR, BWV, FOL = w2.SRC, w2.DST, w2.DIR, w2.BWV, w2.FOL
PTR = BWV + 8
PFX = "f5_wx"
SEG = CODE >> 4                 # 1000h
ALT = SEG - 1                   # 0FFFh: the same linear address at offset + 10h
BANK = 5
BANK_BASE = 0xFE00 + 0x20 * BANK    # DS1 = F000h
SLOT = {"VPC": 0x02, "DS0": 0x08, "SS": 0x0A, "PS": 0x0C, "DS1": 0x0E, "SP": 0x16}
_FIL = w2._FIL
_w = lambda v: [v & 0xFF, v >> 8 & 0xFF]                         # noqa: E731
P = _w(PTR)

_NOP = ([0x90], "NOP   ; lead")
_INCCH = ([0xFE, 0xC5], "INC CH   ; lead: sets V from 7Fh, clears it from 00h")
LEADS = dict(w2.LEADS)
LEADS.update({f"g{k}": (_FIL, _INCCH) + (_NOP,) * k for k in range(4)})

# name: (bytes or a function of the next instruction's offset in segment 1000h, text, options)
# options: v (1: V set / 0: V clear when Y starts), bp, frame (pushed in the setup: psw, a number, "nxt" the
# follower's offset, "nxta" the follower's offset in segment 0FFFh), mem (the far pointer at PTR), alt (Y leaves
# PS 0FFFh: BR far back at the window's end), bank (bank 5's slots set up, a RETRBI stub behind the window)
YS = {
    "bv": ([0xCE], "BRKV   ; V set", {"v": 1}),
    "bn": ([0xCE], "BRKV   ; V clear", {"v": 0}),
    "bk": ([0xCC], "BRK 3   ; FINT ; RETI", {"v": 1}),
    "l0": ([0xC8, 0x08, 0x00, 0x00], "PREPARE 8, 0", {"bp": 0x0EF0}),
    "l1": ([0xC8, 0x08, 0x00, 0x01], "PREPARE 8, 1", {"bp": 0x0EF0}),
    "mi": ([0xBB, 0x34, 0x12], "MOV BW, 1234h", {}),
    "ai": ([0x05, 0x34, 0x12], "ADD AW, 1234h", {}),
    "ib": ([0xB3, 0x12], "MOV BL, 12h", {}),
    "ui": ([0x68, 0x34, 0x12], "PUSH 1234h", {}),
    "jn": ([0xE9, 0x00, 0x00], "BR near $+3", {}),
    "tw": ([0xF7, 0xC3, 0x34, 0x12], "TEST BW, 1234h", {}),
    "aw": ([0x81, 0xC3, 0x34, 0x12], "ADD BW, 1234h", {}),
    "jf": (lambda n: [0xEA] + _w(n + 0x10) + _w(ALT), f"BR far {ALT:04X}h:next", {"alt": 1}),
    "cf": (lambda n: [0x9A] + _w(n + 0x10) + _w(ALT), f"CALL far {ALT:04X}h:next", {"alt": 1}),
    "rf": ([0xCB], "RET far", {"alt": 1, "frame": (ALT, "nxta")}),
    "ri": ([0xCA, 0x02, 0x00], "RET far 2", {"alt": 1, "frame": (0, ALT, "nxta")}),
    "rt": ([0xCF], "RETI", {"alt": 1, "frame": ("psw", ALT, "nxta")}),
    "jm": ([0xFF, 0x2E] + P, f"BR far [{PTR:04X}h]", {"alt": 1, "mem": 1}),
    "cm": ([0xFF, 0x1E] + P, f"CALL far [{PTR:04X}h]", {"alt": 1, "mem": 1}),
    "rs": ([0xCA, 0x02, 0x00], "RET far 2   ; within the segment", {"frame": (0, SEG, "nxt")}),
    "bc": ([0x0F, 0x2D, 0xFB], f"BRKCS BW   ; bank {BANK}: RETRBI", {"bank": 1}),
}


def window(y, lead, al, w=0):
    yb, yt, opt = YS[y]
    meta = dict(y=y, lead=lead, al=al, r=1, w=w, sp=None)
    fix = []                            # (position of a 16-bit field, kind)

    def imm(a, kind, text):
        a.op([0xB8, 0, 0], text)
        fix.append((len(a.b) - 2, kind))

    def setup(a):
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFEB, w2.PRCV[1])
        oc.es_store(a, 0xFFE8, w, word=True)
        if "bank" in opt:
            for s, v in (("PS", SEG), ("SS", 0), ("DS0", 0), ("DS1", 0), ("SP", 0x0E00)):
                oc.es_store(a, BANK_BASE + SLOT[s], v, word=True)
            a.op([0x26, 0xC7, 0x06] + _w(BANK_BASE + SLOT["VPC"]) + [0, 0],
                 f"MOV word DS1:[{BANK_BASE + SLOT['VPC']:04X}h], the stub's offset   ; bank {BANK}'s vector PC")
            fix.append((len(a.b) - 2, "stub"))
        oc.seg(a, "DS1", 0)
        a.mov_r("SP", STACK_TOP)
        a.mov_r("IX", SRC)
        a.mov_r("IY", DST)
        a.mov_r("BW", BANK if "bank" in opt else BWV)
        a.mov_r("CW", (0x7F01 if opt.get("v") else 0x0001) if lead.startswith("g") else 1)
        a.op([0xFC], "CLR1 DIR")
        for f in opt.get("frame", ()):
            if f == "psw":
                a.op([0x9C], "PUSH PSW")
            elif f in ("nxt", "nxta"):
                imm(a, f, "MOV AW, the follower's offset" + (f" in segment {ALT:04X}h" if f == "nxta" else ""))
                a.op([0x50], "PUSH AW")
            else:
                a.mov_r("AW", f)
                a.op([0x50], "PUSH AW")
        if "bp" in opt:
            a.mov_r("BP", opt["bp"])
        if "mem" in opt:
            imm(a, "nxta", f"MOV AW, the follower's offset in segment {ALT:04X}h")
            a.op([0xA3] + P, f"MOV [{PTR:04X}h], AW")
            a.mov_r("AW", ALT)
            a.op([0xA3] + _w(PTR + 2), f"MOV [{PTR + 2:04X}h], AW")
        if "v" in opt and not lead.startswith("g"):     # (behind a g lead the lead's INC CH decides V)
            a.op([0xB0, 0x7F if opt["v"] else 0x00], f"MOV AL, {'7F' if opt['v'] else '00'}h")
            a.op([0xFE, 0xC0], "INC AL   ; V " + ("set" if opt["v"] else "clear"))

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
        bs = yb(len(a.b) + len(yb(0))) if callable(yb) else yb
        put(bs, yt + "   ; Y", "Y")
        nx = len(a.b)
        put([0xA1, FOL & 0xFF, FOL >> 8], f"MOV AW, [{FOL:04X}h]   ; the follower", "F")
        for i in range(6):
            put([0x40], "INC AW", "I")
        ins.append((CODE + len(a.b), "T", "ROL BP, 16"))
        oc.fil(a)
        if "alt" in opt:
            put([0xEA] + _w(len(a.b) + 5) + _w(SEG), f"BR far {SEG:04X}h:next   ; back", "B")
        stub = 0
        if "bank" in opt:
            if not len(a.b) & 1:
                a.nop()                 # the stub at an even address
            put([0xEB, 0x02], "BR $+4   ; over the stub", "B")
            stub = len(a.b)
            put([0x0F, 0x91], "RETRBI   ; the stub: bank 5's vector PC", "R")
        for pos, kind in fix:
            a.b[pos:pos + 2] = bytes(_w({"nxt": nx, "nxta": nx + 0x10, "stub": stub}[kind]))
        meta["ins"] = ins
        a.op([0xFA], "DI")
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFE8, 0, word=True)
        oc.es_store(a, 0xFFEB, w2.PRCV[1])
        a.mov_r("AW", 0)
    return ph.Window(meta, setup, body)


GL = ("g0", "g1", "g2", "g3")
JL = ("j0", "j1", "j2", "j3", "j4")
GROUPS = {
    "a": ([(y, l, al, 0) for y in ("bv", "bn") for l in GL + JL for al in (0, 1)]
          + [(y, l, al, w) for y in ("bv", "bn") for w in (1, 2) for l in ("g0", "j0") for al in (0, 1)]
          + [("bk", l, al, 0) for l in GL for al in (0, 1)]),
    "b": [(y, l, al, 0) for y in ("l0", "l1", "mi", "ai", "ib", "ui", "jn", "tw", "aw")
          for l in ("j0", "j1", "j2", "f0") for al in (0, 1)],
    "c": ([(y, l, al, 0) for y in ("jf", "cf", "rf", "ri", "rt", "jm", "cm") for l in ("f0", "f1", "j0", "j1", "j2")
           for al in (0, 1)]
          + [(y, l, al, w) for y in ("jf", "ri", "jm") for w in (1, 2) for l in ("f0", "j0") for al in (0, 1)]),
    "e": ([("rs", l, al, 0) for l in ("f0", "f1", "f2", "f3") + JL + ("sb", "rd") for al in (0, 1)]
          + [("rs", l, al, w) for w in (1, 2) for l in ("f0", "j0") for al in (0, 1)]),
    "d": [("bc", l, al, w) for w in (0, 1, 2) for l in ("f0", "f1", "j0", "j1", "j2") for al in (0, 1)],
}
NOTES = {
    "a": "BRKV taken and not taken behind full and emptied queues",
    "b": "operand releases with seven bytes held",
    "c": "far transfers that change PS",
    "e": "RET far imm16 within the segment",
    "d": "BRKCS BW into bank 5 and RETRBI",
}
NQ = 16


def programs():
    progs = {}
    for g, wins in GROUPS.items():
        name = f"{PFX}_{g}_r1"
        progs[name] = ph.Program(name, [window(y, l, al, w) for y, l, al, w in wins],
                                 f"group {g}: {NOTES[g]}, PRC = 4Eh")
    for k in range(NQ):
        name = f"{PFX}_q{k}_r1"

        def init(m, k=k):
            if k:
                oc.roli(m, k)
        progs[name] = ph.Program(name, [window("mi", "f0", 0)],
                                 f"group q: the prelude's RFM store behind twelve fillers, ROL BP,{k} in front of them "
                                 f"(the refresh timer's phase against the store)", rf="late", init=init)
    return progs


windows, fmt, cell, kind_of, compare = w2.windows, w2.fmt, w2.cell, w2.kind_of, w2.compare


def rfm(names, progs, cand="sim"):
    """Group q: the cycles around the prelude's RFM store, the socket's (refresh cycles marked R) beside the
    simulation's, clocks from the last fetch both have in front of the store instruction's first byte."""
    for n in names:
        prog = progs[n]
        b = prog.build()
        head = b["head"]
        pos, at = oc.ORG, None
        for bs, text in head:
            if "DS1:[FFE1h]" in text:
                at = pos
            pos += len(bs)
        out = []
        for be in ("socket", cand):
            try:
                rec = ph.load(n, be)
            except FileNotFoundError:
                out.append(f"  {be}: no receipt")
                continue
            rows = [r for r in rec["trace"] if kind_of(r, b["code_end"]) not in ("pin", "idle")]
            i0 = next(i for i, r in enumerate(rows) if r[1] == (at & ~1) - 4 and kind_of(r, b["code_end"]) != "refresh")
            t0 = rows[i0][0]
            cells = []
            for r in rows[i0:i0 + 14]:
                k = kind_of(r, b["code_end"])
                cells.append(("R" if k == "refresh" else f"{r[1]:03X}") + f"@{fmt((r[0] - t0) / 32)}")
                if r[1] >= at + 12 and k != "refresh":
                    break
            out.append(f"  {be:7s} " + " ".join(cells))
        print(f"{n}: the RFM store at {at:05X}h")
        print("\n".join(out))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "repeat", "gate", "emit", "rfm"))
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
    elif a.action == "rfm":
        rfm([n for n in names if "_q" in n], progs, a.cand)
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
