"""F5: socket rows for the bus-idle word that pops and releases nothing (the f5_wz_* program set;
build/overseer/dpop-design, build/overseer/dpop-rows). Captured twice on 2026-11-25 (receipts
validation/v35s/receipts/f5-f5_wz_*-socket.json / -socket-2.json, equal).
r1left's frame and its `jm` / `cm` subjects (BR far [d16], CALL far [d16]) behind leads that separate the two
conditions the rows on file (f5_wy_m) confound: the count the fetch ending on the routine's third word was
started with (four: by the line; five: the continuation) and the place of the popped byte in its fetched word
(the low byte or the high byte).

    PYTHONPATH=host/src:. python3 -m validation.v35s.dpop sim [NAME ...] [--tag -x]
    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.dpop socket --socket-fitted [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.dpop gate | repeat | emit

Leads (each at both alignments, 0 / 1 / 2 waits):
    f0 .. f3, j0 .. j3      f5_wy_m's (the control: 96 windows on file)
    m0 .. m3                the filler, MOV BW,imm16 (three bytes released on one clock), 0 .. 3 NOPs
    b0 .. b3                BR $+2, MOV BL,imm8, 0 .. 3 NOPs
    i0 .. i3                the filler, INC BW x 2, MOV BL,imm8, 0 .. 3 NOPs
Programs f5_wz_n_r1 (BR far [d16]) and f5_wz_o_r1 (CALL far [d16]).
"""

from __future__ import annotations

import argparse
import sys

from . import phase as ph
from . import r1left as r1
from . import wstore2 as w2

PFX = "f5_wz"
_NOP = ([0x90], "NOP   ; lead")
_MI = ([0xBB, 0x05, 0x00], "MOV BW, 0005h   ; lead")
_IB = ([0xB3, 0x05], "MOV BL, 05h   ; lead")
_INC = ([0x43], "INC BW   ; lead")
_BR = ([0xEB, 0x00], "BR $+2   ; lead: the queue emptied")
r1.LEADS.update({f"m{k}": (w2._FIL, _MI) + (_NOP,) * k for k in range(4)})
r1.LEADS.update({f"b{k}": (_BR, _IB) + (_NOP,) * k for k in range(4)})
r1.LEADS.update({f"i{k}": (w2._FIL, _INC, _INC, _IB) + (_NOP,) * k for k in range(4)})
LEADS = [f"{c}{k}" for c in "mbi" for k in range(4)]


def programs():
    progs = {}
    for g, y in (("n", "jm"), ("o", "cm")):
        name = f"{PFX}_{g}_r1"
        progs[name] = ph.Program(name, [r1.window(y, l, al, w) for w in (0, 1, 2) for l in LEADS for al in (0, 1)],
                                 f"group {g} (proposed): {r1.YS[y][1]} behind leads that separate the count from the "
                                 f"popped byte's place, PRC = 4Eh")
    return progs


windows, fmt, cell, kind_of, compare = w2.windows, w2.fmt, w2.cell, w2.kind_of, w2.compare


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
            ok &= compare(n, ref, cand, progs, verbose=a.verbose)
        return 0 if ok else 1
    else:
        ph.emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
