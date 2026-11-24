"""F5: store timing with internal RAM disabled, the rule (the f5_wt_* program set; build/overseer/wstore2).
One instruction Y behind a lead that sets the queue's state, at both code alignments, followed by a read
(MOV AW,[0890h]) and INC AW x 6; every window twice, in twin programs whose bytes differ in the PRC value
alone: `_r1` (PRC 4Eh, RAMEN 1) and `_r0` (PRC 0Eh, RAMEN 0). Code, stack and data in block 0; refresh off.

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.wstore2 socket --socket-fitted [NAME ...] [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore2 sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore2 repeat [NAME ...]      (socket / socket-2)
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore2 gate [NAME ...] [-v]   (socket / sim, whole windows)
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore2 pair [GROUP ...] [--ref socket] [-v]
                                                    (a window's cycles at RAMEN 1 | RAMEN 0, clocks after the marker)
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore2 emit

Groups (programs f5_wt_<group>_r1 / _r0):
    c       the plain stores over twelve leads: MOV [IX],AW ; PUSH AW ; STMW ; MOV [d16],AW (A3) ;
            MOV word [IX],imm16 ; MOV byte [IX],imm8
    s, t    other forms over four leads: stores, read-modify-write, XCH, PUSH / POP mem, CALL, BRK, PUSH R,
            strings, OUT / IN, reads, compares
    x       a word at an odd address, the internal RAM range and an SFR through DS1, and PRC stored in the
            window (both directions)
    w1, w2  seven forms over six leads with block 0 at 1 and 2 waits

Leads: f0 .. f3 (ROL BP,16 then 0 .. 3 NOPs: the queue full), j0 .. j4 (BR $+2 then NOPs: the queue
emptied), pu (ROL ; PUSH BW), sb (ROL ; MOV [BW],AW), rd (ROL ; MOV BP,[BW]).
Receipts: validation/v35s/receipts/f5-<name>-<backend>.json.
"""

from __future__ import annotations

import argparse
import sys

from . import onchip_t as oc
from . import phase as ph
from .wtc import FLAG_IO, FLAG_PIN, FLAG_READ, FLAG_REFRESH, FLAG_STROBE

CODE, STACK_TOP, HANDLER = oc.CODE, oc.STACK_TOP, ph.HANDLER
SRC, DST, DIR, BWV, FOL = 0x0800, 0x0900, 0x0810, 0x0880, 0x0890
PRCV = {1: 0x4E, 0: 0x0E}
CLK = 32
PFX = "f5_wt"

_FIL = ("fil",)
_NOP = ([0x90], "NOP   ; lead")
_BR = ([0xEB, 0x00], "BR $+2   ; lead: the queue emptied")
LEADS = dict(
    [(f"f{k}", (_FIL,) + (_NOP,) * k) for k in range(4)]
    + [(f"j{k}", (_BR,) + (_NOP,) * k) for k in range(5)]
    + [("pu", (_FIL, ([0x53], "PUSH BW   ; lead"))),
       ("sb", (_FIL, ([0x89, 0x07], "MOV [BW], AW   ; lead"))),
       ("rd", (_FIL, ([0x8B, 0x2F], "MOV BP, [BW]   ; lead")))])
GRID_C = tuple(LEADS)
GRID_S = ("f0", "f1", "j0", "j2")
GRID_W = ("f0", "f1", "j0", "j2", "pu", "sb")

D = [DIR & 0xFF, DIR >> 8]
# name: (bytes, text, options: ix, sp, ds1, cw)
YS = {
    # plain stores
    "sw": ([0x89, 0x04], "MOV [IX], AW", {}),
    "pu": ([0x50], "PUSH AW", {}),
    "tw": ([0xAB], "STMW", {}),
    "a3": ([0xA3] + D, f"MOV [{DIR:04X}h], AW   ; A3", {}),
    "iw": ([0xC7, 0x04, 0x34, 0x12], "MOV word [IX], 1234h", {}),
    "ib": ([0xC6, 0x04, 0x12], "MOV byte [IX], 12h", {}),
    "sb": ([0x88, 0x04], "MOV [IX], AL", {}),
    "sd": ([0x89, 0x44, 0x02], "MOV [IX+2], AW", {}),
    "sx": ([0x89, 0x16] + D, f"MOV [{DIR:04X}h], DW   ; 89 16", {}),
    "jw": ([0xC7, 0x06] + D + [0x34, 0x12], f"MOV word [{DIR:04X}h], 1234h", {}),
    "jb": ([0xC6, 0x06] + D + [0x12], f"MOV byte [{DIR:04X}h], 12h", {}),
    "tb": ([0xAA], "STMB", {}),
    # read-modify-write, exchange, stack
    "ad": ([0x01, 0x04], "ADD [IX], AW", {}),
    "nw": ([0xFF, 0x04], "INC word [IX]", {}),
    "nb": ([0xFE, 0x04], "INC byte [IX]", {}),
    "h1": ([0xD1, 0x24], "SHL word [IX], 1", {}),
    "h4": ([0xC1, 0x24, 0x04], "SHL word [IX], 4", {}),
    "no": ([0xF7, 0x14], "NOT word [IX]", {}),
    "xc": ([0x87, 0x04], "XCH AW, [IX]", {}),
    "pm": ([0xFF, 0x34], "PUSH word [IX]", {}),
    "om": ([0x8F, 0x04], "POP word [IX]", {}),
    "ca": ([0xE8, 0x00, 0x00], "CALL $+3", {}),
    "bk": ([0xCC], "BRK 3   ; FINT ; RETI", {}),
    "pr": ([0x60], "PUSH R", {}),
    # strings, I/O
    "mw": ([0xA5], "MOVBKW", {}),
    "rm": ([0xF3, 0xA5], "REP MOVBKW   ; CW 4", {"cw": 4}),
    "rs": ([0xF3, 0xAB], "REP STMW   ; CW 4", {"cw": 4}),
    "ow": ([0xE7, 0x80], "OUT 80h, AW", {}),
    "ob": ([0xE6, 0x80], "OUT 80h, AL", {}),
    "in": ([0xE5, 0x80], "IN AW, 80h", {}),
    # reads and compares (nothing stored)
    "rw": ([0x8B, 0x04], "MOV AW, [IX]", {}),
    "a1": ([0xA1] + D, f"MOV AW, [{DIR:04X}h]   ; A1", {}),
    "po": ([0x58], "POP AW", {}),
    "lw": ([0xAD], "LDMW", {}),
    "ar": ([0x03, 0x04], "ADD AW, [IX]", {}),
    "cm": ([0x39, 0x04], "CMP [IX], AW", {}),
    "cr": ([0x3B, 0x04], "CMP AW, [IX]", {}),
    "te": ([0x85, 0x04], "TEST [IX], AW", {}),
    "cw": ([0xA7], "CMPBKW", {}),
    "nn": ([0x90], "NOP   ; Y: nothing", {}),
    # a word at an odd address (two byte cycles)
    "swo": ([0x89, 0x04], "MOV [IX], AW   ; IX odd", {"ix": SRC + 1}),
    "puo": ([0x50], "PUSH AW   ; SP odd", {"sp": STACK_TOP - 1}),
    "two": ([0xAB], "STMW   ; IY odd", {"iy": DST + 1}),
    "rwo": ([0x8B, 0x04], "MOV AW, [IX]   ; IX odd", {"ix": SRC + 1}),
    # the internal RAM range and an SFR through DS1 = F000h
    "ew": ([0x26, 0xA3, 0x40, 0xFE], "MOV DS1:[FE40h], AW   ; internal RAM range", {"ds1": oc.ON}),
    "er": ([0x26, 0xA1, 0x40, 0xFE], "MOV AW, DS1:[FE40h]   ; internal RAM range", {"ds1": oc.ON}),
    "ei": ([0x26, 0xC7, 0x06, 0x40, 0xFE, 0x34, 0x12], "MOV word DS1:[FE40h], 1234h", {"ds1": oc.ON}),
    "fw": ([0x26, 0xA2, 0x00, 0xFF], "MOV DS1:[FF00h], AL   ; P0's latch", {"ds1": oc.ON}),
    "fr": ([0x26, 0xA0, 0x00, 0xFF], "MOV AL, DS1:[FF00h]   ; P0", {"ds1": oc.ON}),
    "xw": ([0x36, 0xA3] + D, f"MOV SS:[{DIR:04X}h], AW   ; external, prefixed", {}),
}
SW = ([0x89, 0x04], "MOV [IX], AW")


def window(y, lead, al, r, w=0, sp=None):
    """sp: the PRC-store windows: ("flip", n) Y n times, PRC stored with the other value, Y n times, PRC
    stored back, Y n times."""
    yb, yt, opt = YS[y]
    meta = dict(y=y, lead=lead, al=al, r=r, w=w, sp=sp)

    def setup(a):
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFEB, PRCV[r])
        oc.es_store(a, 0xFFE8, w, word=True)
        oc.seg(a, "DS1", opt.get("ds1", oc.ON if sp else 0))
        a.mov_r("SP", opt.get("sp", STACK_TOP))
        a.mov_r("IX", opt.get("ix", SRC))
        a.mov_r("IY", opt.get("iy", DST))
        a.mov_r("BW", BWV)
        a.mov_r("CW", opt.get("cw", 1))
        a.op([0xFC], "CLR1 DIR")

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
        if sp:
            for i in range(sp[1]):
                put(yb, yt + "   ; Y", "Y")
            put(*oc.form("pimb", 0xFFEB, PRCV[1 - r]), "P")
            for i in range(sp[1]):
                put(yb, yt + "   ; Y", "Y")
            put(*oc.form("pimb", 0xFFEB, PRCV[r]), "P")
            for i in range(sp[1]):
                put(yb, yt + "   ; Y", "Y")
        else:
            put(yb, yt + "   ; Y", "Y")
        put([0xA1, FOL & 0xFF, FOL >> 8], f"MOV AW, [{FOL:04X}h]   ; the follower", "F")
        for i in range(6):
            put([0x40], "INC AW", "I")
        ins.append((CODE + len(a.b), "T", "ROL BP, 16"))
        oc.fil(a)
        meta["ins"] = ins
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFE8, 0, word=True)
        oc.es_store(a, 0xFFEB, PRCV[1])
        a.mov_r("AW", 0)
    return ph.Window(meta, setup, body)


GROUPS = {
    "c": [(y, l, al, 0, None) for y in ("sw", "pu", "tw", "a3", "iw", "ib") for l in GRID_C for al in (0, 1)],
    "s": [(y, l, al, 0, None) for y in ("sb", "sd", "sx", "jw", "jb", "tb", "ad", "nw", "nb", "h1", "h4", "no", "xc",
                                        "pm", "om", "ca", "bk", "pr") for l in GRID_S for al in (0, 1)],
    "t": [(y, l, al, 0, None) for y in ("mw", "rm", "rs", "ow", "ob", "in", "rw", "a1", "po", "lw", "ar", "cm", "cr",
                                        "te", "cw", "nn") for l in GRID_S for al in (0, 1)],
    "x": [(y, l, al, 0, None) for y in ("swo", "puo", "two", "rwo", "ew", "er", "ei", "fw", "fr", "xw")
          for l in GRID_S for al in (0, 1)]
         + [(y, l, al, 0, ("flip", 3)) for y in ("sw", "pu", "a3") for l in ("f0", "j0") for al in (0, 1)],
    "w1": [(y, l, al, 1, None) for y in ("sw", "pu", "tw", "a3", "iw", "mw", "rw") for l in GRID_W for al in (0, 1)],
    "w2": [(y, l, al, 2, None) for y in ("sw", "pu", "tw", "a3", "iw", "mw", "rw") for l in GRID_W for al in (0, 1)],
}


def programs():
    progs = {}
    for g, wins in GROUPS.items():
        for r in (1, 0):
            name = f"f5_wt_{g}_r{r}"
            progs[name] = ph.Program(name, [window(y, l, al, r, w, sp) for y, l, al, w, sp in wins],
                                     f"group {g}: lead ; Y ; MOV AW,[{FOL:04X}h] ; INC AW x 6 with PRC = {PRCV[r]:02X}h")
    return progs


# ------------------------------------------------------------------ reading
def kind_of(row, code_end):
    f, a = row[3], row[1]
    if f & FLAG_PIN:
        return "pin"
    if f & FLAG_REFRESH:
        return "refresh"
    if not f & FLAG_STROBE:
        return "idle"
    if f & FLAG_IO:
        return "ior" if f & FLAG_READ else "iow"
    if not f & FLAG_READ:
        return "mw"
    if CODE <= a < code_end + 0x20 or HANDLER <= a < HANDLER + 0x10:
        return "fetch"
    return "mr"


def windows(rec, prog):
    """{k: dict(t0, T, rows: [(kind, address, start clock after the marker, length in clocks)])}"""
    end = prog.build()["code_end"]
    out, cur = {}, None
    for row in rec["trace"]:
        kind = kind_of(row, end)
        if kind in ("pin", "idle"):
            continue
        if kind == "iow" and row[1] == oc.M_BEGIN:
            cur = dict(k=row[2], t0=row[0], rows=[])
            continue
        if kind == "iow" and oc.M_END <= row[1] <= oc.M_END + 0x20 and cur is not None:   # (above M_END: wstore3's POP R restores DW)
            cur["T"] = (row[0] - cur["t0"]) / CLK
            out[cur["k"]] = cur
            cur = None
            continue
        if cur is not None:
            cur["rows"].append((kind, row[1], (row[0] - cur["t0"]) / CLK, round((row[4] - row[0] - 1) / CLK) + 1))
    return out


def fmt(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


def cell(r):
    k = {"fetch": "f", "mr": "r", "mw": "w", "ior": "i", "iow": "o", "refresh": "R"}[r[0]]
    return f"{k}{r[1] & 0xFFF:03X}@{fmt(r[2])}"


def line(w, verbose=False):
    rows = w["rows"]
    if not verbose:                 # the setup's and the tail's fetches left out: from the first cycle past the
        rows = rows                 # marker's own to the end marker
    return " ".join(cell(r) for r in rows) + f" T{fmt(w['T'])}"


def pair(group, backend, progs, verbose=False):
    names = [f"f5_wt_{group}_r1", f"f5_wt_{group}_r0"]
    wa, wb = (windows(ph.load(n, backend), progs[n]) for n in names)
    pw = progs[names[0]].windows
    print(f"group {group} [{backend}]: {len(wa)}/{len(pw)} and {len(wb)}/{len(pw)} windows")
    for k, p in enumerate(pw):
        m = p.meta
        head = f"{k:3d} {m['y']:3s} {m['lead']:2s} al {m['al']} w{m['w']}{' flip' if m['sp'] else ''}"
        if k not in wa or k not in wb:
            print(head + ": missing")
            continue
        a, b = line(wa[k]), line(wb[k])
        if a == b:
            print(f"{head} =  {a}")
        else:
            print(f"{head} r1 {a}")
            print(f"{'':{len(head)}s} r0 {b}")


def compare(name, ref, cand, progs, verbose=False):
    prog = progs[name]
    a, b = ph.load(name, ref), ph.load(name, cand)
    if a["program_sha256"] != b["program_sha256"] or a["image_sha256"] != b["image_sha256"]:
        print(f"{name}: the receipts are of different programs")
        return False
    wa, wb = windows(a, prog), windows(b, prog)
    diff = []
    for k, pw in enumerate(prog.windows):
        if k not in wa or k not in wb:
            diff.append((k, "missing"))
        elif wa[k]["rows"] != wb[k]["rows"] or wa[k]["T"] != wb[k]["T"]:
            x, y = wa[k]["rows"], wb[k]["rows"]
            i = next((i for i, (p, q) in enumerate(zip(x, y)) if p != q), min(len(x), len(y)))
            diff.append((k, f"T {fmt(wa[k]['T'])} / {fmt(wb[k]['T'])}; first at record {i}: "
                         f"{cell(x[i]) if i < len(x) else '-'} / {cell(y[i]) if i < len(y) else '-'}"))
    print(f"{name}: {ref} / {cand}: {'EQUAL' if not diff else 'DIFFER'} "
          f"({len(prog.windows) - len(diff)} of {len(prog.windows)} windows equal; passed {a['passed']} / {b['passed']})")
    for k, why in diff[:None if verbose else 6]:
        m = prog.windows[k].meta
        print(f"  w{k} {m['y']} {m['lead']} al {m['al']} w{m['w']}: {why}")
    return not diff


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
        ph.run_set(names, "socket", a.tag, progs)
    elif a.action == "sim":
        ph.run_set(names, "sim", a.tag, progs)
    elif a.action == "pair":
        for g in a.names or list(GROUPS):
            pair(g, a.ref + a.tag, progs, a.verbose)
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
