"""The interrupt-path row sets the design note still wanted (2026-11-25, DESIGN-INT.md section 7; read in
build/overseer/int-rows/ROWS-INT.md): P6a, P6b, R2a, P10a, R3a, P11a. A sibling of intprobe.py (its frames,
receipts and comparison); the CLKOUT runs use clkout.py's follow-up frame and scope receipts.

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.introws socket --socket-fitted [NAME ...] [--tag=-2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.introws sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.introws repeat [NAME ...]      (socket / socket-2)
    PYTHONPATH=host/src:. python3 -m validation.v35s.introws gate [NAME ...]        (socket / sim)
    PYTHONPATH=host/src:. python3 -m validation.v35s.introws read [NAME ...] [--cand sim]
    PYTHONPATH=host/src:. python3 -m validation.v35s.introws emit

    f5_ld_d    P6a: f5_lc_sj's frame with DIVU BW in place of the jump (the queue full, nothing flushed, no
               fetch wanted while the divide runs); level 1 .. 7, two sleds
    f5_ld_e    P6a: the same with DIVU BW ; DIVU BW (one fetch slot between the two)
    f5_ld_x    P6a: the store, then a sled of x clocks (a block-1 read and a long ROL: the queue full), the
               INC train; level 1 3 5 7, x 0 .. 5: the fetch slot behind the ROL moves a clock at a time
    f5_ld_r    P6a: the store, ROL BP,n with n 2 4 6 8 10 (2 clocks a count: the quiet bus ends before the take
               is due), the INC train; level 1 .. 7
    f5_ld_y    P6a (a follow-up of the same session): f5_ld_x's frame at level 1 .. 7, x 0 .. 3: the request
               one, two and three clocks in front of the fetch that the ROL's pops want
    f5_ld_s    P6a (follow-up): f5_ld_r's frame with INC AW in front of the ROL, n 1 2 3: the other parity of the
               request against the INC train's first fetch
    f5_ld_w1   P6b: f5_lc_sj with one wait on block 0 (the code, the stack, the vectors); level 0 .. 7, 4 sleds
    f5_ld_w2   P6b: the same with two waits
    f4_oe_o    R2a: OUT (imm8 byte, imm8 word, an odd port's word, DW) at 1, 2, 3 I/O waits followed by MOV AL,imm8
               / MOV AW,imm16 / ADD AL,imm8 / PUSH AW / MOV word [m],imm16 / MOV byte [m],imm8 / CVTBD, both alignments
    f4_oe_m    R2a (follow-up): OUT (byte, word, an odd port's word) at 1, 2 I/O waits followed by MULU BL / MULU BW /
               MUL BL / DIVU BL / MUL AW,BW,imm8 / SHL AL,imm8 / CVTDB / CVTBD: is the datum the multiplier / the divisor
    f5_ld_pa   P10a: f5_lc_pa (a request control store, a sled of 0 / 1 clocks, the INTP0 edge, six reads of
               EXIC0) with the edge's delay 388 .. 448 ticks in steps of 4 (f5_lc_pa's j 4.25 .. 8)
    f5_ld_pb   P10a: the same behind DI ; EI
    f5_ld_pc   P10a: f5_ld_pa's frame, the delay 448 .. 688 in steps of 16 (the other parity's threshold)
    f5_ld_pd   P10a: f5_ld_pb's frame, the same delays
    f4_oe_k    P11a: REP STMW / REP MOVBKW with CW 1, 2, 3 (and 0) at even and odd IX / IY, alone and with a store
               behind; CW 8 with a register instruction and a store behind, both alignments; CW 1 2 3 at 1 wait
    clk_sa<p>_<x>   R3a: CLKOUT on P07 at fX/p (2, 8): a request control store (the scan's restart), a sled of
               x = 0 .. 3 clocks, STOP. No release: the run ends at its limit
    clk_sr2_<x>     R3a: fX/2, IE 0: TM0's request stored at level 7, a sled of x = 0 .. 17 clocks, STOP (released
               by the request: whether CLKOUT stops, and for how long, against the controller's round)
    Receipts of the clk_ runs: validation/v35s/receipts/clk-r3a-<backend>.json ({"runs": {name: record}}).
"""

from __future__ import annotations

import argparse
import json
import sys

from . import intprobe as ip
from . import lattice as la
from . import onchip_t as oc
from . import phase as ph
from .wtc import CLK

DW0 = ("rawb", (0xBA, 0x00, 0x00), "MOV DW, 0000h   ; the dividend's high word")
DWM = ("rawb", (0xBA, oc.M_BEGIN & 0xFF, oc.M_BEGIN >> 8), "MOV DW, FE40h   ; the marker's port again")
DIVU = ("rawb", (0xF7, 0xF3), "DIVU BW   ; BW = F800h: the queue full, no fetch wanted")


# ------------------------------------------------------------------ P6a / P6b
def set_div(ndiv):
    out = []
    for lv in range(1, 8):
        for s in (0, 1):
            out.append(la.window("d" + str(ndiv), (lv - 1) * 2 + s,
                                 (DW0, ("ei",), ("fil", 1), ("sled", s), ("mark", 1), ("st", 0xFF9C, 0x80 | lv))
                                 + (DIVU,) * ndiv + (("inc", 60), DWM), odd=s & 1, ic={}, lv=lv, sl=s))
    return out


def set_x():
    out = []
    for i, lv in enumerate((1, 3, 5, 7)):
        for x in range(6):
            out.append(la.window("x", i * 6 + x, (("ei",), ("fil", 1), ("mark", 1), ("st", 0xFF9C, 0x80 | lv),
                                                  ("sled", x), ("inc", 60)), odd=x & 1, ic={}, lv=lv, sl=x))
    return out


def set_r():
    out = []
    for i, n in enumerate((2, 4, 6, 8, 10)):
        for lv in range(1, 8):
            out.append(la.window("r", i * 7 + lv - 1, (("ei",), ("fil", 1), ("mark", 1), ("st", 0xFF9C, 0x80 | lv),
                                                       ("rol", n), ("inc", 60)), ic={}, lv=lv, sl=n))
    return out


def set_y():
    out = []
    for lv in range(1, 8):
        for x in range(4):
            out.append(la.window("y", (lv - 1) * 4 + x, (("ei",), ("fil", 1), ("mark", 1), ("st", 0xFF9C, 0x80 | lv),
                                                         ("sled", x), ("inc", 60)), odd=x & 1, ic={}, lv=lv, sl=x))
    return out


def set_s():
    out = []
    for i, n in enumerate((1, 2, 3)):
        for lv in range(1, 8):
            out.append(la.window("s", i * 7 + lv - 1, (("ei",), ("fil", 1), ("mark", 1), ("st", 0xFF9C, 0x80 | lv),
                                                       ("rawb", (0x40,), "INC AW   ; the odd clock"), ("rol", n),
                                                       ("inc", 60)), ic={}, lv=lv, sl=n))
    return out


def set_wait(w):
    out = []
    for lv in range(8):
        for s in range(4):
            out.append(la.window(f"w{w}", lv * 4 + s,
                                 (("ei",), ("fil", 1), ("sled", s), ("mark", 1), ("st", 0xFF9C, 0x80 | lv), ip.BR0,
                                  ("inc", 40)), pre=(("stw", 0xFFE8, (s & 1) << 2 | w),), odd=s & 1, ic={}, lv=lv,
                                 sl=s, wt=w))
    return out


# ------------------------------------------------------------------ P10a
def pin_set3(series, lead, delays):
    wins, ent = [], []
    for a in (0, 1):
        for d in delays:
            k = len(wins)
            wins.append(la.window(series, k, lead + (("sled", a), ("mark", 1), ("ev", k + 1)) + (("rd", 0xFF4C),) * 6,
                                  odd=a & 1, ic={"p0": 0x47, "tm0": 0x47}, a=a, j=d))
            ent.append(dict(event=k + 1, delay=d, hold=600, levels={"INTP0": 0}))
    return wins, ent


LEADS = {"a": ((("st", 0xFF9D, 0x47),), "a request control store"), "b": ((("di",), ("ei",)), "DI ; EI")}
FINE, COARSE = tuple(range(388, 452, 4)), tuple(range(448, 704, 16))


def la_programs():
    progs = [la.prog("f5_ld_d", set_div(1), "a stored IF by level behind DIVU (the queue full), INC train"),
             la.prog("f5_ld_e", set_div(2), "a stored IF by level behind DIVU ; DIVU, INC train"),
             la.prog("f5_ld_x", set_x(), "a stored IF by level, a sled swept behind it, INC train"),
             la.prog("f5_ld_r", set_r(), "a stored IF by level, ROL BP,n (n 2 .. 10) behind it, INC train"),
             la.prog("f5_ld_y", set_y(), "f5_ld_x's frame at every level, x 0 .. 3"),
             la.prog("f5_ld_s", set_s(), "f5_ld_r's frame with INC AW in front of the ROL (n 1 2 3)"),
             la.prog("f5_ld_w1", set_wait(1), "f5_lc_sj at one wait on block 0"),
             la.prog("f5_ld_w2", set_wait(2), "f5_lc_sj at two waits on block 0")]
    for sfx, lead, delays, what in (("pa", "a", FINE, "4-tick steps"), ("pb", "b", FINE, "4-tick steps"),
                                    ("pc", "a", COARSE, "448 .. 688 ticks"), ("pd", "b", COARSE, "448 .. 688 ticks")):
        wins, ent = pin_set3(sfx, LEADS[lead][0], delays)
        progs.append(la.prog("f5_ld_" + sfx, wins, f"INTP0's flag read against the edge behind {LEADS[lead][1]}: "
                             + what, entries=ent))
    return {p.name: p for p in progs}


# ------------------------------------------------------------------ R2a
FOLLOW = {"mov": ([0xB0, 0xA5], "MOV AL, 0A5h"), "movw": ([0xB8, 0xA5, 0xC3], "MOV AW, 0C3A5h"),
          "add": ([0x04, 0x5A], "ADD AL, 5Ah"), "push": ([0x50], "PUSH AW"),
          "imw": ([0xC7, 0x06, 0x70, 0xFE, 0x5A, 0xA5], "MOV word [FE70h], 0A55Ah"),
          "imb": ([0xC6, 0x06, 0x70, 0xFE, 0xC3], "MOV byte [FE70h], 0C3h"), "cvtbd": ([0xD4, 0x85], "CVTBD 85h")}


def out_window(out, fol, align, wait):
    def setup(a):
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFE8, wait << 14, word=True)      # WTC: the I/O field at `wait`
        oc.std_setup(oc.OFF)(a)

    def body(a):
        a.mov_r("AW", 0x1234)
        if out == "ef":
            a.mov_r("DW", 0x0083)
        oc.fil(a, 2)
        a.nop(align)
        a.op(*ip.OUTS[out])
        a.op(*FOLLOW[fol])
        oc.fil(a)
        if out == "ef":
            a.mov_r("DW", oc.M_BEGIN)
    return oc.Window(dict(form=out, target=fol, seg=f"w{wait}", shape="out", n=align), setup, body)


def out_set():
    out = [out_window(o, f, al, w) for w in (1, 2, 3) for o in ip.OUTS for f in FOLLOW for al in (0, 1)]

    def setup(a):
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFE8, 0, word=True)
        oc.std_setup(oc.OFF)(a)
    out.append(oc.Window(dict(form="none", target="-", seg="w0", shape="iso", n=0), setup, lambda a: oc.fil(a)))
    return out


# ------------------------------------------------------------------ P11a
SRC, DST = ip.SRC, ip.DST
ST = ([0xA3, 0x70, 0xFE], "MOV [FE70h], AW   ; the store behind")
BEHIND = {"": (), "st": (ST,), "inc": (([0x40], "INC AW   ; a register instruction behind the string"), ST),
          "mvr": (([0x8B, 0xEF], "MOV BP, IY   ; a register instruction behind the string"), ST)}


def odd_window(op, ix, iy, n=8, wait=0, behind="", align=0):
    code = {"stm": 0xAB, "mov": 0xA5}[op]
    text = {"stm": "STMW", "mov": "MOVBKW"}[op]

    def setup(a):
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFE8, wait << 2, word=True)       # WTC: block 1 (the data page) at `wait`
        oc.seg(a, "DS0", oc.OFF)
        oc.seg(a, "DS1", oc.OFF)
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
        for f in BEHIND[behind]:
            a.op(*f)
        oc.fil(a)
    return oc.Window(dict(form="rep" + op + "w", target=f"{ix:04X}/{iy:04X}", seg=f"w{wait}",
                          shape=(behind or "rep") + str(align), n=n), setup, body)


KINDS = (("stm", SRC, DST), ("stm", SRC, DST + 1), ("mov", SRC, DST), ("mov", SRC, DST + 1),
         ("mov", SRC + 1, DST + 1), ("mov", SRC + 1, DST))


def odd_set():
    out = [oc.control_window("iso", 1)]
    for n in (1, 2, 3):
        for k in KINDS:
            out.append(odd_window(*k, n=n))
            out.append(odd_window(*k, n=n, behind="st"))
    for k in KINDS[:5]:
        for behind in ("inc", "mvr"):
            for align in (0, 1):
                out.append(odd_window(*k, behind=behind, align=align))
    for k in (KINDS[1], KINDS[3]):
        out.append(odd_window(*k, n=0, behind="st"))
        for n in (1, 2, 3):
            out.append(odd_window(*k, n=n, wait=1))
    out.append(odd_window("mov", SRC, DST))        # WTC back to 0 for the frame's end
    return out


# R2b (a follow-up of the same session): the multiply's and the divide's operand in place of an immediate
FOLLOW2 = {"mulub": ([0xF6, 0xE3], "MULU BL   ; BL = 5Ah"), "muluw": ([0xF7, 0xE3], "MULU BW   ; BW = 7B5Ah"),
           "mulb": ([0xF6, 0xEB], "MUL BL"), "divub": ([0xF6, 0xF3], "DIVU BL"),
           "mul3": ([0x6B, 0xC3, 0x85], "MUL AW, BW, 85h"), "shl": ([0xC0, 0xE0, 0x03], "SHL AL, 3"),
           "cvtdb": ([0xD5, 0x07], "CVTDB 07h"), "cvtbd": ([0xD4, 0x85], "CVTBD 85h")}


def out_window2(out, fol, align, wait):
    def setup(a):
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFE8, wait << 14, word=True)
        oc.std_setup(oc.OFF, bw=0x7B5A)(a)

    def body(a):
        a.mov_r("AW", 0x1234)
        oc.fil(a, 2)
        a.nop(align)
        a.op(*ip.OUTS[out])
        a.op(*FOLLOW2[fol])
        oc.fil(a)
        a.mov_r("DW", oc.M_BEGIN)       # MULU BW leaves DW the product's high word
    return oc.Window(dict(form=out, target=fol, seg=f"w{wait}", shape="out", n=align), setup, body)


def out_set2():
    out = [out_window2(o, f, al, w) for w in (1, 2) for o in ("e6", "e7", "e7o") for f in FOLLOW2 for al in (0, 1)]

    def setup(a):
        oc.seg(a, "DS1", oc.ON)
        oc.es_store(a, 0xFFE8, 0, word=True)
        oc.std_setup(oc.OFF)(a)
    out.append(oc.Window(dict(form="none", target="-", seg="w0", shape="iso", n=0), setup, lambda a: oc.fil(a)))
    return out


def oc_programs():
    return {"f4_oe_k": oc.Program("f4_oe_k", odd_set(), "REP strings at odd addresses: CW 1 2 3, a register "
                                  "instruction behind", init=oc.ram_fill),
            "f4_oe_m": oc.Program("f4_oe_m", out_set2(), "OUT at 1, 2 I/O waits followed by a multiply, a divide, a "
                                  "shift by an immediate, CVTDB, CVTBD: the write's datum"),
            "f4_oe_o": oc.Program("f4_oe_o", out_set(), "OUT at 1, 2, 3 I/O waits followed by an immediate load, an "
                                  "ALU immediate, PUSH, a store of an immediate: the write's datum and clocks")}


# ------------------------------------------------------------------ R3a
def body_sa(div, x, pend):
    from . import clkout as ck

    def body(a):
        ck.clkout_on(a)
        if div != 8:
            a.sfr_w(0xEB, ck.PCK_CODE[div])
        a.sfr_w(0xE8, (x & 1) << 2, word=True)      # WTC: block 1's wait is the sled's odd clock
        a.seg("DS0", 0x3000)
        a.mov_r("BW", 0xF800)
        a.nop(8)
        a.out_w(ck.M_BEGIN, 0)
        if pend:
            a.sfr_w(0x9C, 0x87)                     # TMIC0: IF 1 at level 7 (IE 0): the scan's restart, a request
        else:
            a.sfr_w(0x9D, 0x47)                     # TMIC1 as it stands: the scan's restart, nothing pending
        a.op([0x8A, 0x27], "MOV AH, [BW]   ; block 1: the sled's odd clock is its wait")
        a.op([0xC1, 0xC5, 8 + x // 2], f"ROL BP, {8 + x // 2}   ; the sled")
        a.op([0x0F, 0x9E], "STOP")
        a.nop(4)
        a.label("cont")
        a.out_w(ck.M_END, 0)
    return body


def ck_programs():
    from . import clkout as ck
    progs = []
    for div in (2, 8):
        for x in range(4):
            progs.append(ck.CProgram(f"clk_sa{div}_{x}", f"STOP at fX/{div}, {x} clocks of sled behind a request "
                                     "control store, no release", body_sa(div, x, False), prc=ck.PCK_CODE[div],
                                     limit=300_000 if div == 2 else 900_000))
    for x in range(18):
        progs.append(ck.CProgram(f"clk_sr2_{x}", f"STOP at fX/2 with TM0's request pending at level 7 (IE 0), {x} "
                                 "clocks of sled behind its store", body_sa(2, x, True), prc=0x4C, limit=300_000))
    return {p.name: p for p in progs}


CK_RECEIPT = "r3a"


def ck_load(backend):
    from . import clkout as ck
    p = ck.receipt_path(CK_RECEIPT, backend)
    return json.loads(p.read_text())["runs"] if p.exists() else {}


def ck_save(backend, recs):
    from . import clkout as ck
    old = ck_load(backend)
    old.update(recs)
    ck.receipt_path(CK_RECEIPT, backend).write_text(json.dumps(
        dict(backend=backend, ticks="scope ticks of 30 ns from the run's start", runs=old), separators=(",", ":")) + "\n")


def _ck_job(name):
    from . import clkout as ck
    prog = ck_programs()[name]
    transport, harness = ck._sim()
    try:
        return name, ck.d_record(prog, ck.d_run(harness, prog, "model"), "sim")
    finally:
        transport.close()


def ck_run(names, backend, tag, jobs=4):
    from . import clkout as ck
    progs, recs = ck_programs(), {}
    if backend == "sim":
        from multiprocessing import Pool
        with Pool(min(jobs, len(names))) as pool:
            for name, rec in pool.imap(_ck_job, names):
                recs[name] = rec
                print(f"{name} [sim]: passed {rec['run']['passed']} capture {rec['run']['capture']} edges "
                      f"{rec['run']['edges_total']}", flush=True)
        ck_save("sim", recs)
        return
    from .traps import _board, _close_board
    transport, harness = _board()
    try:
        for name in names:
            rec = ck.d_record(progs[name], ck.d_run(harness, progs[name], "socket"), backend + tag)
            recs[name] = rec
            print(f"{name} [{backend}{tag}]: passed {rec['run']['passed']} status {rec['run']['status']:#x} capture "
                  f"{rec['run']['capture']} edges {rec['run']['edges_total']}", flush=True)
    finally:
        _close_board(transport, harness)
        ck_save(backend + tag, recs)


def ck_row(rec):
    """One clk_ run reduced: ticks from the anchor's /MREQ fall (the OUT FE40h cycle): the bus cycles behind the
    anchor, CLKOUT's irregular half periods (the stop: a long high), the last edge."""
    run, clk = rec["run"], rec["clk_ticks"]
    ev, tr = run["edges"], run["trace"]
    a = next((r for r in tr if r[1] == 0xFE40 and r[2] & 2), None)
    if a is None:
        return dict(error="no anchor")
    t0 = next(e[0] for e in ev if e[1] == "mreq_n" and e[2] == 0 and e[0] >= a[0] - 6)
    bus = [(e[0] - t0) for e in ev if e[1] == "mreq_n" and e[2] == 0 and e[0] > t0]
    cko = [(e[0] - t0, e[2]) for e in ev if e[1] == "clkout" and e[0] >= t0 - 4 * clk]
    tail = run.get("clkout_tail")
    odd = [(x, xv, y - x) for (x, xv), (y, yv) in zip(cko, cko[1:]) if y - x != clk // 2]
    last = (tail["last"][0] - t0, tail["last"][2]) if tail else cko[-1] if cko else None
    return dict(clk=clk, bus=bus, odd=odd, last=last, n=len(cko) + (tail["edges"] if tail else 0),
                end=run.get("capture_last", 0) - t0, passed=run["passed"])


def ck_same(x, y):
    """Two captures of a run: every bus cycle and every CLKOUT edge at the same tick from the anchor. Not compared:
    the tick the capture ends at (the run's limit against the reset's phase)."""
    def rel(rec):
        tr = rec["run"]["trace"]
        return [(r[0] - tr[0][0], r[1], r[2], r[3] - r[0]) for r in tr]
    a, b = ck_row(x), ck_row(y)
    return {k: v for k, v in a.items() if k != "end"} == {k: v for k, v in b.items() if k != "end"} and rel(x) == rel(y)


def ck_read(names, backends):
    for name in names:
        for be in backends:
            rec = ck_load(be).get(name)
            if rec is None:
                continue
            r = ck_row(rec)
            if "error" in r:
                print(f"{name} [{be}]: {r['error']}")
                continue
            c = r["clk"]
            print(f"{name} [{be}] clk {c}: bus /MREQ falls (clocks from the anchor's) "
                  + " ".join(f"{t / c:.1f}" for t in r["bus"]) + " | CLKOUT irregular: "
                  + (" ".join(f"{'high' if v else 'low'} from {t / c:.2f} for {d / c:.2f}" for t, v, d in r["odd"]) or "none")
                  + f" | last edge {r['last'][0] / c:.2f} {'rise' if r['last'][1] else 'fall'}; capture ends {r['end'] / c:.0f}")


# ------------------------------------------------------------------ reading
def _rows(w):
    return [(kind, r) for kind, r in w["rows"] if kind != "pin"]


def read_take(name, cand, progs, verbose=False):
    """Per window: the fetch starts after mark 1 (clocks from the mark's write) up to the vector read, the vector
    read and the pushed PC less the INC train's first byte; the socket's line, then the candidate's."""
    p = progs[name]
    W = {be: oc.windows(ph.load(name, be), p)[0] for be in ("socket", cand)}
    eq = 0
    for k, w in enumerate(p.windows):
        out = []
        for be in ("socket", cand):
            rows = _rows(W[be][k])
            mi = next(i for i, (kind, r) in enumerate(rows) if kind == "mw" and r[1] == 0xD82)
            tm = rows[mi][1][0]
            vi = next((i for i, (kind, r) in enumerate(rows) if i > mi and kind == "mr" and 0x30 <= r[1] <= 0x7C), None)
            if vi is None:
                out.append("no take")
                continue
            f = [f"{(r[0] - tm) / CLK:.0f}" + (f"+{oc.waits_of(r)}w" if verbose and oc.waits_of(r) else "")
                 for kind, r in rows[mi + 1:vi] if kind in ("fetch", "mr")]
            pcs = [x for kd, x in rows[vi:vi + 6] if kd == "mw"]
            out.append(f"V{(rows[vi][1][0] - tm) / CLK:.0f} n{(pcs[2][2] - w.meta['first']) & 0xFFFF} f " + " ".join(f))
        m = w.meta
        eq += out[0] == out[1]
        print(f"w{k:2d} lv{m.get('lv', '-')} s{m.get('sl', m['n'])} | {out[0]}\n{'':12s}| {out[1]}"
              f"{'' if out[0] == out[1] else '  <<'}")
    print(f"{name}: {eq} of {len(p.windows)} windows the same in these fields")


def read_flag(name, cand, progs):
    """Per window the first of the six reads of EXIC0 that shows the flag, socket / candidate, sled a by the edge's
    delay; and per sled the threshold: the last edge seen at read 1 and the first not seen there, each as (delay,
    the edge's tick after mark 1's write: the event record's tick + delay + 4, that tick modulo a clock)."""
    p = progs[name]
    tab, thr = {}, {}
    for be in ("socket", cand):
        rec = ph.load(name, be)
        ev, W = la.events(rec, p), oc.windows(rec, p)[0]
        for k, w in enumerate(p.windows):
            d = [x[2] for kind, x in W[k]["rows"] if kind == "mw" and x[1] == 0xEFE]
            first = next((i for i, v in enumerate(d) if v & 0x80), None)
            tab.setdefault((w.meta["a"], w.meta["j"]), []).append("-" if first is None else str(first))
            edge = ev[k]["evs"][0] + w.meta["j"] + 4 - ev[k]["marks"][1][0]
            thr.setdefault((be, w.meta["a"], first == 1), []).append((w.meta["j"], edge, edge % CLK))
    aa, jj = sorted({a for a, j in tab}), sorted({j for a, j in tab})
    print(f"{name}: first read showing the flag, socket / {cand} (* differ); columns: the edge's delay in ticks")
    print("a\\d  " + " ".join(f"{j:>5}" for j in jj))
    for a in aa:
        print(f"{a:3d}  " + " ".join(f"{'/'.join(tab[(a, j)]) + ('' if len(set(tab[(a, j)])) == 1 else '*'):>5}"
                                     for j in jj))
    for be in ("socket", cand):
        for a in aa:
            yes, no = thr.get((be, a, True)), thr.get((be, a, False))
            print(f"  [{be}] a{a}: last seen at read 1 {max(yes) if yes else '-'}, first not {min(no) if no else '-'}")


def read_out(name, cand, progs):
    p = progs[name]
    W = {be: oc.windows(oc.load(name, be), p)[0] for be in ("socket", cand)}
    eq = 0
    for k, w in enumerate(p.windows):
        m = w.meta
        out, dat = [], []
        for be in ("socket", cand):
            rows = _rows(W[be][k])
            t0 = W[be][k]["t0"]
            io = [i for i, (kind, r) in enumerate(rows) if kind == "iow"]
            s = [f"io{rows[i][1][1]:02X}={rows[i][1][2]:04X}@{(rows[i][1][0] - t0) / CLK:.0f}+{oc.waits_of(rows[i][1])}w"
                 for i in io]
            dat.append([rows[i][1][2] for i in io])
            a, b = (io[0], io[-1]) if io else (0, 0)
            pv = [f"{kind[0]}{r[1] & 0xFFF:03X}@{(r[0] - t0) / CLK:.0f}" for kind, r in rows[max(0, a - 2):a]]
            nx = [f"{kind[0] if kind != 'mw' else 'W'}{r[1] & 0xFFF:03X}"
                  + (f"={r[2]:04X}" if kind == "mw" else "") + f"@{(r[0] - t0) / CLK:.0f}" for kind, r in rows[b + 1:b + 4]]
            out.append(" ".join(pv) + " | " + " ".join(s) + " | " + " ".join(nx) + f" T{W[be][k]['T'] / CLK:.0f}")
        eq += out[0] == out[1]
        flag = "" if out[0] == out[1] else ("  << datum" if dat[0] != dat[1] else "  << clocks")
        print(f"w{k:3d} {m['form']:3s} {m['target']:5s} {m['seg']} a{m['n']} :: {out[0]}  ##  {out[1]}{flag}")
    print(f"{name}: {eq} of {len(p.windows)} equal in these fields")


def read_str(name, cand, progs):
    p = progs[name]
    W = {be: oc.windows(oc.load(name, be), p)[0] for be in ("socket", cand)}
    for k, w in enumerate(p.windows):
        m = w.meta
        out = []
        for be in ("socket", cand):
            rows = _rows(W[be][k])
            t0 = W[be][k]["t0"]
            data = [i for i, (kind, r) in enumerate(rows) if kind in ("mr", "mw") and (r[1] & 0xFFF) < 0xE70
                    and r[1] >= 0x3F000]
            if not data:
                out.append(f"no string cycle T{W[be][k]['T'] / CLK:.0f}")
                continue
            first, last = data[0], data[-1]
            prev = [r for kind, r in rows[:first] if kind == "fetch"][-1]
            nxt = [f"{kind[0] if kind != 'mw' else 'W'}{(r[0] - rows[last][1][0]) / CLK:.0f}" for kind, r in rows[last + 1:last + 4]]
            out.append(f"head {(rows[first][1][0] - prev[0]) / CLK:.0f} span {(rows[last][1][0] - rows[first][1][0]) / CLK:.0f} "
                       f"cycles {len(data)} behind " + " ".join(nxt) + f" T{W[be][k]['T'] / CLK:.0f}")
        print(f"w{k:2d} {m['form']:8s} {m['target']} {m['seg']} {m['shape']:5s} n{m['n']} | {out[0]} | {out[1]}"
              f"{'' if out[0] == out[1] else '   <<'}")


def programs():
    return {**la_programs(), **oc_programs()}


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "repeat", "gate", "emit", "read"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--socket-fitted", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    lp, op, cp = la_programs(), oc_programs(), ck_programs()
    names = a.names or list(lp) + list(op) + list(cp)
    ln, on, cn = ([n for n in names if n in d] for d in (lp, op, cp))
    if a.action == "socket" and not a.socket_fitted:
        p.error("the socket action needs --socket-fitted")
    if a.action in ("socket", "sim"):
        if ln:
            ph.run_set(ln, a.action, a.tag, lp)
        if on:
            oc.run_set(on, a.action, a.tag, op)
        if cn:
            ck_run(cn, a.action, a.tag)
        return 0
    if a.action in ("repeat", "gate"):
        ok = True
        cand = "socket-2" if a.action == "repeat" else a.cand
        for n in ln:
            ok &= ph.compare(n, a.ref, cand, lp, verbose=a.verbose)
        for n in on:
            ok &= oc.compare(n, a.ref, cand, op, verbose=a.verbose)
        if cn:
            x, y = ck_load(a.ref), ck_load(cand)
            bad = [n for n in cn if n not in x or n not in y or not ck_same(x[n], y[n])]
            print(f"clk_ runs: {a.ref} / {cand}: {'EQUAL' if not bad else 'DIFFER'} ({len(cn) - len(bad)} of {len(cn)} "
                  f"runs){': ' + ' '.join(bad) if bad else ''}")
            ok &= not bad
        return 0 if ok else 1
    if a.action == "read":
        for n in ln:
            (read_flag if n[6] == "p" else read_take)(n, a.cand, lp, *(() if n[6] == "p" else (a.verbose,)))
        for n in on:
            (read_str if n.endswith("_k") else read_out)(n, a.cand, op)
        if cn:
            ck_read(cn, (a.ref, a.cand))
        return 0
    ph.emit({n: lp[n] for n in ln})
    oc.emit({n: op[n] for n in on})
    from . import clkout as ck
    for n in cn:
        lines = cp[n].source().split("\n")
        lines[1] = ("; Generated by validation/v35s/introws.py emit (clkout.py's frame); socket receipts "
                    "validation/v35s/receipts/clk-r3a-socket{,-2}.json (2026-11-25)")
        (ck.PROGRAMS_DIR / f"{n}.s").write_text("\n".join(lines))
        print(f"{n}: {len(cp[n].build()['text'])} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
