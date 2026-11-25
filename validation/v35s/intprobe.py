"""The interrupt-path design probes (2026-11-25, build/overseer/int-design/DESIGN-INT.md): socket rows
for the controller's two bus clocks and the take's boundary by level (P6 / P7), the timer flag's read
(P12), INTP0's sampler against the scan's restarts (P10) and REP strings at odd addresses (P11).
Siblings of validation/v35s/lattice.py (its frame, receipts and comparison) and onchip_t.py.

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.intprobe socket --socket-fitted [NAME ...] [--tag=-2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.intprobe sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.intprobe repeat [NAME ...]      (socket / socket-2)
    PYTHONPATH=host/src:. python3 -m validation.v35s.intprobe gate [NAME ...]        (socket / sim)
    PYTHONPATH=host/src:. python3 -m validation.v35s.intprobe emit

    f5_lc_sj   IE 1, a short jump (the queue flushed: the prefetcher runs through the whole passage), a
               stored IF at level 0 .. 7, an INC train; 6 sleds in front of the store
    f5_lc_sn   the same with a NOP train
    f5_lc_kN   lattice k's frame (IE 0, TM0's IF stored at level N, a sled, EI, an INC train), N 1 2 4 5 6
    f5_lc_q    lattice q's frame (TMIC0 masked, the start, a sled, six reads of TMIC0) at MD0 8 and 10
    f5_lc_pa   EXIC0 masked; a request control store (TMIC1), a sled of 0 .. 3 clocks, the INTP0 edge at 8
               half-clock delays, six reads of EXIC0
    f5_lc_pb   the same with DI ; EI in place of the store (the scan's restart is IE's rise)
    f4_od_o    OUT (imm8 byte, imm8 word, an odd port's word, DW) followed by CVTBD / CVTDB / NOP at both
               alignments, the I/O field at 0 and 2 waits: the write's datum and its clocks (R2)
    f4_od_k    REP strings on external memory at odd addresses: REP STMW (IY odd), REP MOVBKW with IX odd,
               IY odd, both (at 0, 1, 2 waits), and a store behind the string at both alignments
"""

from __future__ import annotations

import argparse
import sys

from . import lattice as la
from . import onchip_t as oc
from . import phase as ph

BR0 = ("rawb", (0xEB, 0x00), "BR short $+2   ; the queue flushed")


def set_sj(train):
    out = []
    for lv in range(8):
        for s in range(6):
            out.append(la.window("s" + train[0], lv * 8 + s,
                                 (("ei",), ("fil", 1), ("sled", s), ("mark", 1), ("st", 0xFF9C, 0x80 | lv), BR0,
                                  (train, 40)), odd=s & 1, ic={}, lv=lv, sl=s))
    return out


def set_kl(lv):
    pend = (("st", 0xFF9C, 0x80 | lv),)
    return [la.window(f"k{lv}", x, pend + (("sled", x), ("mark", 1), ("ei",), ("inc", 60)), odd=x & 1, ic={})
            for x in range(20)]


def set_q2():
    return [la.window("q", k * 12 + s, (la.START, ("sled", s)) + (("rd", 0xFF9C),) * 6, odd=s & 1, md0=md,
                      ic={"tm0": 0x47}, sl=s) for k, md in enumerate((8, 10)) for s in range(12)]


def pin_set2(series, lead, base=320, step=16):
    """lead: the operations that restart the scan; then a sled of a clocks (even a only moves by 2: the odd
    clock is block 1's wait), the event, six reads of EXIC0."""
    wins, ent = [], []
    for a in range(4):
        for j in range(8):
            k = a * 8 + j
            wins.append(la.window(series, k, lead + (("sled", a), ("mark", 1), ("ev", k + 1)) + (("rd", 0xFF4C),) * 6,
                                  odd=a & 1, ic={"p0": 0x47, "tm0": 0x47}, a=a, j=j))
            ent.append(dict(event=k + 1, delay=base + step * j, hold=600, levels={"INTP0": 0}))
    return wins, ent


def la_programs():
    progs = [la.prog("f5_lc_sj", set_sj("inc"), "a stored IF by level behind a short jump, INC train"),
             la.prog("f5_lc_sn", set_sj("nop"), "a stored IF by level behind a short jump, NOP train")]
    for lv in (1, 2, 4, 5, 6):
        progs.append(la.prog(f"f5_lc_k{lv}", set_kl(lv), f"IE 0, TM0 pending at level {lv}: EI swept"))
    progs.append(la.prog("f5_lc_q", set_q2(), "TM0's flag read against the count-out, the start moved"))
    for series, lead, note in (("pa", (("st", 0xFF9D, 0x47),), "a request control store"),
                               ("pb", (("di",), ("ei",)), "DI ; EI")):
        wins, ent = pin_set2(series, lead)
        progs.append(la.prog("f5_lc_" + series, wins, "INTP0's flag read against the edge behind " + note, entries=ent))
    return {p.name: p for p in progs}


# ------------------------------------------------------------------ strings at odd addresses
ON, OFF = oc.ON, oc.OFF
SRC, DST = 0xFE40, 0xFE60
STORE = ([0xA3, 0x70, 0xFE], "MOV [FE70h], AW   ; the store behind the string")


def odd_window(op, ix, iy, n=8, wait=0, follow=None, align=0):
    code = {"stm": 0xAB, "mov": 0xA5}[op]
    text = {"stm": "STMW", "mov": "MOVBKW"}[op]

    def setup(a):
        oc.seg(a, "DS1", ON)
        oc.es_store(a, 0xFFE8, wait << 2, word=True)       # WTC: block 1 (the data page) at `wait`
        oc.seg(a, "DS0", OFF)
        oc.seg(a, "DS1", OFF)
        a.mov_r("IX", ix)
        a.mov_r("IY", iy)
        a.mov_r("CW", n)
        a.mov_r("SP", oc.STACK_TOP)
        a.op([0xFC], "CLR1 DIR")

    def body(a):
        a.mov_r("AW", 0x1234)
        oc.fil(a, 2)
        a.nop(align)
        a.op([0xF3, code], "REP " + text)
        if follow:
            a.op(*follow)
        oc.fil(a)
    return oc.Window(dict(form="rep" + op + "w", target=f"{ix:04X}/{iy:04X}", seg=f"w{wait}",
                          shape="st" + str(align) if follow else "rep", n=n), setup, body)


def odd_set():
    out = [oc.control_window("iso", 1)]
    for iy in (DST, DST + 1):
        out.append(odd_window("stm", SRC, iy))
    for ix, iy in ((SRC, DST), (SRC + 1, DST), (SRC, DST + 1), (SRC + 1, DST + 1)):
        for wait in (0, 1, 2):
            out.append(odd_window("mov", ix, iy, wait=wait))
    for ix, iy in ((SRC, DST), (SRC + 1, DST + 1)):
        for align in (0, 1):
            out.append(odd_window("mov", ix, iy, follow=STORE, align=align))
    for iy in (DST, DST + 1):
        for align in (0, 1):
            out.append(odd_window("stm", SRC, iy, follow=STORE, align=align))
    out.append(odd_window("mov", SRC, DST))        # WTC back to 0 for the frame's end
    return out


OUTS = {"e6": ([0xE6, 0x80], "OUT 80h, AL"), "e7": ([0xE7, 0x80], "OUT 80h, AW"),
        "e7o": ([0xE7, 0x81], "OUT 81h, AW   ; odd: two byte cycles"), "ef": ([0xEF], "OUT DW, AW   ; DW = 0083h")}
FOLLOW = {"cvtbd": ([0xD4, 0x85], "CVTBD 85h"), "cvtdb": ([0xD5, 0x07], "CVTDB 07h"), "nop": ([0x90, 0x90], "NOP ; NOP")}


def out_window(out, fol, align, wait):
    def setup(a):
        oc.seg(a, "DS1", ON)
        oc.es_store(a, 0xFFE8, wait << 14, word=True)      # WTC: the I/O field at `wait`
        oc.std_setup(OFF)(a)

    def body(a):
        a.mov_r("AW", 0x1234)
        if out == "ef":
            a.mov_r("DW", 0x0083)
        oc.fil(a, 2)
        a.nop(align)
        a.op(*OUTS[out])
        a.op(*FOLLOW[fol])
        oc.fil(a)
        if out == "ef":
            a.mov_r("DW", oc.M_BEGIN)
    return oc.Window(dict(form=out, target=fol, seg=f"w{wait}", shape="out", n=align), setup, body)


def out_set():
    out = [out_window(o, f, al, w) for w in (0, 2) for o in OUTS for f in FOLLOW for al in (0, 1)]

    def setup(a):
        oc.seg(a, "DS1", ON)
        oc.es_store(a, 0xFFE8, 0, word=True)
        oc.std_setup(OFF)(a)
    out.append(oc.Window(dict(form="none", target="-", seg="w0", shape="iso", n=0), setup, lambda a: oc.fil(a)))
    return out


def oc_programs():
    return {"f4_od_k": oc.Program("f4_od_k", odd_set(), "REP strings at odd addresses on external memory",
                                  init=oc.ram_fill),
            "f4_od_o": oc.Program("f4_od_o", out_set(), "OUT followed by CVTBD / CVTDB / NOP: the write's datum and clocks")}


def programs():
    return {**la_programs(), **oc_programs()}


def load(name, backend):
    return (oc if name.startswith("f4_") else ph).load(name, backend)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "repeat", "gate", "emit", "summary"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--socket-fitted", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    lp, op = la_programs(), oc_programs()
    names = a.names or list(lp) + list(op)
    ln, on = [n for n in names if n in lp], [n for n in names if n in op]
    if a.action == "socket" and not a.socket_fitted:
        p.error("the socket action needs --socket-fitted")
    if a.action in ("socket", "sim"):
        if ln:
            ph.run_set(ln, a.action, a.tag, lp)
        if on:
            oc.run_set(on, a.action, a.tag, op)
        return 0
    if a.action == "summary":
        for n in ln:
            la.summary(n, a.ref + a.tag, lp)
        return 0
    if a.action in ("repeat", "gate"):
        ok = True
        cand = "socket-2" if a.action == "repeat" else a.cand
        for n in ln:
            ok &= ph.compare(n, a.ref, cand, lp, verbose=a.verbose)
        for n in on:
            ok &= oc.compare(n, a.ref, cand, op, verbose=a.verbose)
        return 0 if ok else 1
    for progs in (lp, op):
        if progs is lp:
            ph.emit({n: lp[n] for n in ln})
        else:
            oc.emit({n: op[n] for n in on})
    return 0


if __name__ == "__main__":
    sys.exit(main())
