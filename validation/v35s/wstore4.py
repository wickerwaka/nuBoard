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
    y0, ya, yb, yc
            the data in block 1 (20100h up, WTC field 3: 2 waits and READY, PMC1 bit 7), the code and the stack in
            block 0 at 0 waits or 1 wait; READY low from a block-1 cycle's /MREQ fall for 0 (y0: READY stays
            high), 10 (ya), 15 (yb) and 18.5 (yc) CPU clocks (harness version 3: registers C2h / C4h / C6h, read
            and write cycles of block 1). Shapes: REP STMW (CW 6); REP MOVBKW from block 0 (CW 4);
            `26 89 07 ; 26 89 57 02` three times; the same pair in a DBNZ loop of three; MOV [IX],AW ; CMP [IX],AW
            twice (DS0 in block 1); MOV DS1:[BW],AW four times; MOV DS1:[BW],AW ; PUSH AW twice. Each followed by
            INC AW x 6.
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


class Program(ph.Program):
    """phase's frame with the READY block's page loaded and the /MREQ-timed READY setting (`m`)."""
    m = None

    def build(self):
        if not self._built:
            b = super().build()
            b["segments"][0x20000] = bytes(pat(0x20000 | o) for o in range(0x1000))
        return self._built


def programs():
    progs = {}
    for r in (1, 0):
        name = f"{PFX}_b_r{r}"
        progs[name] = Program(name, [bwindow(y, l, al, r, f) for y, l, al, f in B_WINS],
                              f"group b: byte stores at odd addresses and short followers with PRC = {PRCV[r]:02X}h")
    for r in (1, 0):
        name = f"{PFX}_r_r{r}"
        progs[name] = Program(name, [bwindow(y, l, al, r, f, w) for y, l, al, f, w in R_WINS],
                              f"group r: REP STM / REP MOVBK by count, block 0 at 0, 1 and 2 waits, with PRC = {PRCV[r]:02X}h")
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
        for g in a.names or ["b", "r"] + list(READY):
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
