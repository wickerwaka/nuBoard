"""F5: back-to-back memory stores at 0 waits, refresh off (the f5_ws_* program set): the steady-state
clocks per operation of long runs of one store form, on the socketed uPD70337 and on the core v2 RTL in
simulation (build/overseer/wstore). phase.py's frame (windows between the markers, receipts, stitching).

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.wstore socket --socket-fitted [NAME ...] [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore repeat [NAME ...]      (socket / socket-2)
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore gate [NAME ...] [-v]   (socket / sim, whole windows)
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore table [NAME ...] [--ref sim] [-v]
    PYTHONPATH=host/src:. python3 -m validation.v35s.wstore emit

    f5_ws_a     ROL BP,16 (queue full, bus idle) ; the form x 16 ; ROL BP,16, the first copy at an even and
                at an odd address; code and data in block 0 (DS0 = DS1 = SS = 0), WTC 0, RFM ECh
    f5_ws_r     the same with REP STMW / STMB / MOVBKW / LDMW, CW 16 (and LDMW with CW 64)
    f5_ws_l     the other team's loop: four blocks of (the form x 16 ; INC CW ; CMP BP,[BW] ; BE next), each
                at a multiple of 16, the branch taken into the next block (a taken short branch backwards or
                forwards empties the queue alike): the loop's period is block k's first data cycle to block
                k + 1's
    f5_ws_p4c, f5_ws_p0c, f5_ws_p0e    four forms, straight and looped, with PRC = 4Ch (fX/2, RAMEN 1),
                0Ch (fX/2, RAMEN 0: the other team's value) and 0Eh (fX/8, RAMEN 0) for the window's body;
                the harness's own programs leave PRC at its reset value 4Eh (fX/8, RAMEN 1)
    f5_ws_a0, f5_ws_r0, f5_ws_l0       a, r and l with PRC = 0Eh (RAMEN 0, the reset clock) in the body

Receipts: validation/v35s/receipts/f5-<name>-<backend>.json.
"""

from __future__ import annotations

import argparse
import sys

from . import onchip_t as oc
from . import phase as ph

CODE, STACK_TOP = oc.CODE, oc.STACK_TOP
SRC, DST, DIR, CMPW = 0x0800, 0x0900, 0x0810, 0x0880
N = 16

# name: (bytes, text, the data cycles of one copy: kinds in order)
FORMS = {
    "sw": ([0x89, 0x04], "MOV [IX], AW", ("mw",)),
    "sb": ([0x88, 0x04], "MOV [IX], AL", ("mw",)),
    "pu": ([0x50], "PUSH AW", ("mw",)),
    "tw": ([0xAB], "STMW", ("mw",)),
    "tb": ([0xAA], "STMB", ("mw",)),
    "sd": ([0x89, 0x44, 0x02], "MOV [IX+2], AW", ("mw",)),
    "a3": ([0xA3, DIR & 0xFF, DIR >> 8], f"MOV [{DIR:04X}h], AW   ; A3", ("mw",)),
    "sx": ([0x89, 0x16, DIR & 0xFF, DIR >> 8], f"MOV [{DIR:04X}h], DW   ; 89 16", ("mw",)),
    "si": ([0xC7, 0x04, 0x34, 0x12], "MOV word [IX], 1234h", ("mw",)),
    "rw": ([0x8B, 0x04], "MOV AW, [IX]   ; control", ("mr",)),
    "lw": ([0xAD], "LDMW   ; control", ("mr",)),
}
REPS = {
    "rtw": ([0xF3, 0xAB], "REP STMW", ("mw",), 16),
    "rtb": ([0xF3, 0xAA], "REP STMB", ("mw",), 16),
    "rmw": ([0xF3, 0xA5], "REP MOVBKW", ("mr", "mw"), 16),
    "rlw": ([0xF3, 0xAD], "REP LDMW", ("mr",), 16),
    "rl64": ([0xF3, 0xAD], "REP LDMW", ("mr",), 64),
}
PRC_REST = 0x4E


def _setup(prc, cw=N):
    def setup(a):
        oc.seg(a, "DS1", oc.ON)
        if prc is not None:
            oc.es_store(a, 0xFFEB, prc)
        oc.seg(a, "DS1", 0)
        a.mov_r("SP", STACK_TOP)
        a.mov_r("IX", SRC)
        a.mov_r("IY", DST)
        a.mov_r("BW", CMPW)
        a.op([0x8B, 0x2F], "MOV BP, [BW]")
        a.mov_r("CW", cw)
        a.op([0xFC], "CLR1 DIR")
    return setup


def _tail(a, prc):
    oc.fil(a)
    if prc is not None:
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFEB, PRC_REST)
        a.mov_r("AW", 0)


def straight(form, al, prc=None):
    rep = form in REPS
    bs, text, kinds = (REPS if rep else FORMS)[form][:3]
    cw = REPS[form][3] if rep else N
    meta = dict(shape="s", form=form, al=al, n=1 if rep else N, cw=cw, kinds=kinds, prc=prc)

    def body(a):
        if (len(a.b) + 3 & 1) != al:
            a.nop()
        oc.fil(a)
        meta["at"] = CODE + len(a.b)
        for _ in range(meta["n"]):
            a.op(bs, text)
        _tail(a, prc)
    return ph.Window(meta, _setup(prc, cw), body)


def looped(form, prc=None, blocks=4):
    bs, text, kinds = FORMS[form]
    meta = dict(shape="l", form=form, al=0, n=N, cw=N, kinds=kinds, prc=prc, blocks=blocks)

    def pad(a, off=0):
        while (len(a.b) + off) & 15:
            a.nop()

    def body(a):
        pad(a, 3)
        oc.fil(a)
        meta["at"] = CODE + len(a.b)
        for k in range(blocks):
            for _ in range(N):
                a.op(bs, text)
            a.op([0x41], "INC CW")
            a.op([0x3B, 0x2F], "CMP BP, [BW]")
            d = -(len(a.b) + 2) & 15
            a.op([0x74, d], f"BE $+2+{d}   ; taken: the next block")
            pad(a)
        _tail(a, prc)
    return ph.Window(meta, _setup(prc), body)


def programs():
    progs = [
        ph.Program("f5_ws_a", [straight(f, al) for f in FORMS for al in (0, 1)],
                   "ROL BP,16 ; the form x 16 ; ROL BP,16: block 0 at 0 waits, refresh off"),
        ph.Program("f5_ws_r", [straight(f, al) for f in REPS for al in (0, 1)],
                   "ROL BP,16 ; REP string, CW 16 (LDMW also 64) ; ROL BP,16: block 0 at 0 waits, refresh off"),
        ph.Program("f5_ws_l", [looped(f) for f in FORMS],
                   "four blocks of (the form x 16 ; INC CW ; CMP BP,[BW] ; BE next), each at a multiple of 16"),
    ]
    for tag, prc in (("p4c", 0x4C), ("p0c", 0x0C), ("p0e", 0x0E)):
        fs = ("sw", "pu", "tw", "rw")
        progs.append(ph.Program(f"f5_ws_{tag}", [straight(f, al, prc) for f in fs for al in (0, 1)]
                                + [looped(f, prc) for f in fs],
                                f"four forms straight and looped with PRC = {prc:02X}h in the body"))
    # the whole set with RAMEN 0 at the reset clock (PRC = 0Eh): every tick comparable with a / r / l
    progs += [
        ph.Program("f5_ws_a0", [straight(f, al, 0x0E) for f in FORMS for al in (0, 1)],
                   "f5_ws_a with PRC = 0Eh (RAMEN 0) in the body"),
        ph.Program("f5_ws_r0", [straight(f, al, 0x0E) for f in REPS for al in (0, 1)],
                   "f5_ws_r with PRC = 0Eh (RAMEN 0) in the body"),
        ph.Program("f5_ws_l0", [looped(f, 0x0E) for f in FORMS],
                   "f5_ws_l with PRC = 0Eh (RAMEN 0) in the body"),
    ]
    return {p.name: p for p in progs}


# ------------------------------------------------------------------ reading
def clk_of(m):
    return 8 if m["prc"] in (0x4C, 0x0C) else 32


def data_rows(w, m):
    """The window's data cycles of the form (the looped windows' CMP read at CMPW left out)."""
    out = []
    for kind, r in w["rows"]:
        if kind == "fetch" and r[1] < 0x1000:       # onchip_t's kind_of takes a read below E00h for a fetch
            kind = "mr"
        if kind in m["kinds"] and not (kind == "mr" and r[1] == CMPW) and r[1] < 0x1000:
            out.append((kind, r))
    return out


def measure(w, m):
    """dict(n, d: the clocks between successive operations' first data cycles, loop: the looped
    window's periods, steady: the mean of the later half of d / of the third block's inner d)."""
    c = clk_of(m)
    rows = data_rows(w, m)
    k0 = m["kinds"][0]
    ts = [r[0] for kind, r in rows if kind == k0]
    if not ts:
        return None
    d = [(y - x) / c for x, y in zip(ts, ts[1:])]
    if m["shape"] == "l":
        per = [(ts[N * (k + 1)] - ts[N * k]) / c for k in range(m["blocks"] - 1) if N * (k + 1) < len(ts)]
        inner = d[2 * N + N // 2:3 * N - 1]
        return dict(n=len(ts), d=d, loop=per, steady=sum(inner) / len(inner) if inner else None)
    half = d[len(d) // 2:]
    return dict(n=len(ts), d=d, loop=None, steady=sum(half) / len(half) if half else None)


def fmt(x):
    return "-" if x is None else f"{x:.2f}".rstrip("0").rstrip(".")


def table(name, backend, progs, verbose=False):
    prog = progs[name]
    rec = ph.load(name, backend)
    wins, _ = oc.windows(rec, prog)
    print(f"{name} [{backend}] {'PASS' if rec['passed'] else 'FAIL'} total {rec['total']} "
          f"{len(wins)}/{len(prog.windows)} windows replay={rec['replay']}")
    for k, pw in enumerate(prog.windows):
        m = pw.meta
        if k not in wins:
            print(f"  {k:2d} {m['shape']} {m['form']:4s} al {m['al']}: missing")
            continue
        r = measure(wins[k], m)
        if r is None:
            print(f"  {k:2d} {m['shape']} {m['form']:4s} al {m['al']}: no data cycles")
            continue
        prc = "" if m["prc"] is None else f" prc {m['prc']:02X}"
        line = (f"  {k:2d} {m['shape']} {m['form']:4s} al {m['al']}{prc} n {r['n']:3d} T {fmt(wins[k]['T'] / clk_of(m)):>7s} "
                f"steady {fmt(r['steady']):>6s}")
        if r["loop"] is not None:
            line += " loop " + " ".join(fmt(x) for x in r["loop"]) + f" (/16 {fmt(r['loop'][-1] / 16)})"
        print(line)
        if verbose or m["shape"] == "s":
            print("       d " + " ".join(fmt(x) for x in r["d"][:70]))


def compare(name, ref, cand, progs, tol=1, verbose=False):
    prog = progs[name]
    a, b = ph.load(name, ref), ph.load(name, cand)
    if a["program_sha256"] != b["program_sha256"] or a["image_sha256"] != b["image_sha256"]:
        print(f"{name}: the receipts are of different programs")
        return False
    wa, _ = oc.windows(a, prog)
    wb, _ = oc.windows(b, prog)
    diff = []
    for k, pw in enumerate(prog.windows):
        if k not in wa or k not in wb:
            diff.append((k, "missing"))
            continue
        x = [p for p in oc.norm_window(wa[k]) if p[0] != "pin"]
        y = [p for p in oc.norm_window(wb[k]) if p[0] != "pin"]
        if not oc.near(x, y, tol):
            c = clk_of(pw.meta)
            first = next((i for i, (p, q) in enumerate(zip(x[1:], y[1:])) if not oc.near([p], [q], tol)), None)
            why = f"T {wa[k]['T'] / c:.2f} / {wb[k]['T'] / c:.2f} clocks; records {len(x) - 1} / {len(y) - 1}"
            if first is not None:
                p, q = x[1 + first], y[1 + first]
                why += (f"; first at record {first}: {p[0]} {p[1]:05X} @{p[3] / c:.2f} / "
                        f"{q[0]} {q[1]:05X} @{q[3] / c:.2f}")
            diff.append((k, why))
    print(f"{name}: {ref} / {cand}: {'EQUAL' if not diff else 'DIFFER'} "
          f"({len(prog.windows) - len(diff)} of {len(prog.windows)} windows equal; passed {a['passed']} / {b['passed']})")
    for k, why in diff[:None if verbose else 8]:
        m = prog.windows[k].meta
        print(f"  w{k} {m['shape']} {m['form']} al {m['al']}: {why}")
    return not diff


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "table", "repeat", "gate", "emit"))
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
    elif a.action == "table":
        for n in names:
            table(n, a.ref + a.tag, progs, a.verbose)
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
