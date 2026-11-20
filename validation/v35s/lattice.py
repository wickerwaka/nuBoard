"""F5: the take lattice (the f5_la_* program set): what the 16-clock lattice of a maskable
request's takes is locked to and what restarts it, the 18-clock period under IE 0, the pin's
two delays; on the socketed uPD70337 and on the core v2 RTL in simulation. A sibling of
validation/v35s/phase.py (its frame, receipts, stitching and comparison).

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.lattice socket --socket-fitted [NAME ...] [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.lattice sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.lattice report [NAME ...] [--ref socket] [-v]
    PYTHONPATH=host/src:. python3 -m validation.v35s.lattice summary [NAME ...] [--ref socket|sim]
    PYTHONPATH=host/src:. python3 -m validation.v35s.lattice repeat [NAME ...]      (socket / socket-2)
    PYTHONPATH=host/src:. python3 -m validation.v35s.lattice gate [NAME ...]        (socket / sim)
    PYTHONPATH=host/src:. python3 -m validation.v35s.lattice emit

A window is a list of operations (`emit_ops`) between the markers; every vector a window uses
is pointed at one of the program's handler variants by the window's setup. Time marks: the
stores of `mark` (00D80h + 2j), TOUT on P15 (the timer's start and count-outs), the vector
reads (00060h INTP0, 00070h TM0, 00074h TM1, 00078h TM2, 0007Ch the time base), the pushes.
The instruments: HALT (a take out of HALT is not quantised by instruction boundaries) and a
train of INC AW behind a one-clock sled.

    f5_la_a    HALT: EI, then TM0's start; EI's place and the start's swept (the first take is
               rigid to EI, the later ones to the handler's RETI)
    f5_la_b    the handler lengthened in front of FINT and in front of RETI
    f5_la_e    between two takes: DI ; EI, FINT, a P0 store, a request control store, an internal
               RAM store, EI and POP PSW with IE 1, DI ; POP PSW raising IE
    f5_la_g    TM0's level 0 to 7; TM0 and TM1 together
    f5_la_c    a request control store against EI with nothing pending; HALT with IE 0
    f5_la_t    the INC train as the instrument
    f5_la_s    a store of IF 1 with IE 1 by level; DI against the lattice
    f5_la_kN   IE 0, requests pending (PEND N), EI swept over 40 clocks, an INC train
    f5_la_wN   the same with HALT in place of EI (the release's clock)
    f5_la_h7 / h0   the INTP0 edge against the lattice in HALT, level 7 / 0
    f5_la_p / q     INTP0's / TM0's request flag read against the edge / the count-out

Receipts: validation/v35s/receipts/f5-<name>-<backend>.json.

Measured on the uPD70337 (2026-11-20, two equal captures of each): the takes' 16-clock lattice
is the level scan's round counted from its last restart; IE rising (EI, POP PSW, RETI) and a
store to a request control register restart it, nothing else does (not the timer's start, a
count-out, the take, FINT, DI, another SFR store, HALT); level L is examined 2 L clocks after
the restart; with IE 0 every level holding an unmasked request gets two more clocks (the
round 18, 20, 22, 24 for one to four levels) and HALT is released there; IE rising in such a
slot's first clock takes its request at once, in its second does not restart; the INTP0 pin
and TM0 share the lattice, and the pin's flag and its take are the same 3 to 5 clocks behind a
count-out's.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

from . import onchip_t as oc
from . import phase as ph
from .wtc import Asm, CLK

CODE, STACK_TOP = oc.CODE, oc.STACK_TOP
MARK = 0x0D80
HBASE = 0x0C10
VEC = {"se0": 0x30, "se1": 0x40, "p0": 0x60, "p1": 0x64, "p2": 0x68, "tm0": 0x70, "tm1": 0x74, "tm2": 0x78, "tb": 0x7C}
IC = {"se0": 0xFF6C, "se1": 0xFF7C, "p0": 0xFF4C, "p1": 0xFF4D, "p2": 0xFF4E, "tm0": 0xFF9C, "tm1": 0xFF9D, "tm2": 0xFF9E,
      "tb": 0xFFEC}
DS0V, BWV = 0x3000, 0xF800


def emit_ops(a, ops, meta=None):
    """ops: tuples. sled s (a block-1 read, its wait the window's odd clock, and ROL BP 8 + s//2),
    rol n (ROL BP,n: 2 clocks a count), mark j, ei, di, nop n, halt n (HALT ; NOP, n times), inc n,
    fint, reti, st off val (a byte store through DS1), stw off val, ev n (the event port), rd off
    (MOV AL,DS1:[off] ; PUSH AW), rep0 (REP MOVBKW with CW 0), pushw / popw (PUSH AW / POP AW),
    poppsw v (PUSH imm via AW ; POP PSW)."""
    for op in ops:
        k = op[0]
        if k == "sled":
            a.op([0x8A, 0x27], "MOV AH, [BW]   ; block 1: the sled's odd clock is its wait")
            oc.roli(a, 8 + op[1] // 2)
        elif k == "rol":
            if op[1]:
                oc.roli(a, op[1])
        elif k == "mark":
            o = MARK + 2 * op[1]
            a.op([0x36, 0xA3, o & 0xFF, o >> 8], f"MOV SS:[{o:04X}h], AW   ; mark {op[1]}")
        elif k == "ei":
            if meta is not None:
                meta.setdefault("ei", len(a.b))
            a.op([0xFB], "EI")
        elif k == "di":
            a.op([0xFA], "DI")
        elif k == "nop":
            a.nop(op[1])
        elif k == "halt":
            for _ in range(op[1]):
                if meta is not None:
                    meta.setdefault("halts", []).append(len(a.b))
                a.op([0xF4], "HALT")
                a.op([0x90], "NOP")
        elif k == "inc":
            if meta is not None:
                meta.setdefault("first", len(a.b))
            for _ in range(op[1]):
                a.op([0x40], "INC AW")
        elif k == "fint":
            a.op([0x0F, 0x92], "FINT")
        elif k == "reti":
            a.op([0xCF], "RETI")
        elif k == "st":
            oc.es_store(a, op[1], op[2])
        elif k == "stw":
            oc.es_store(a, op[1], op[2], word=True)
        elif k == "ev":
            a.op([0x52], "PUSH DW")
            ph.event(a, op[1])
            a.op([0x5A], "POP DW")
        elif k == "rd":
            a.op([0x26, 0xA0, op[1] & 0xFF, op[1] >> 8], f"MOV AL, DS1:[{op[1]:04X}h]")
            a.op([0x50], "PUSH AW")
        elif k == "rep0":
            a.op([0xF3, 0xA5], "REP MOVBKW   ; CW = 0")
        elif k == "pushw":
            a.op([0x50], "PUSH AW")
        elif k == "popw":
            a.op([0x58], "POP AW")
        elif k == "poppsw":
            a.mov_r("AW", op[1])
            a.op([0x50], "PUSH AW")
            a.op([0x9D], "POP PSW")
        elif k == "fil":
            oc.fil(a, op[1])
        else:
            raise ValueError(op)


H_PLAIN = (("fint",), ("reti",))


class Window(oc.Window):
    pass


def window(series, n, ops, pre=(), odd=0, md0=66, md1=None, hand=None, ic=None, note="", **kw):
    """pre: operations in the setup (before the begin marker, after the timers' registers and
    the request control stores); ops: the window; odd: block 1's wait (the sleds' odd clock);
    md0 / md1: MD0 = TM0, MD1 = TM1; hand: {source: handler ops} (default FINT ; RETI); ic:
    {source: the request control byte stored in the setup} (default tm0 07h)."""
    meta = dict(series=series, form=note or series, target=f"md0 {md0}", seg="-", shape="la", n=n)
    meta.update(kw)
    hand = dict(hand or {})
    ic = dict({"tm0": 0x07} if ic is None else ic)
    win = Window(meta, None, None)
    win.hand = hand

    def setup(a):
        oc.wtc0(a)
        oc.es_store(a, 0xFF90, 0x00)
        oc.es_store(a, 0xFF91, 0x00)
        oc.es_store(a, 0xFF82, md0, word=True)
        oc.es_store(a, 0xFF80, md0, word=True)
        if md1 is not None:
            oc.es_store(a, 0xFF8A, md1, word=True)
            oc.es_store(a, 0xFF88, md1, word=True)
        oc.seg(a, "DS0", DS0V)
        a.mov_r("BW", BWV)
        a.mov_r("SP", STACK_TOP)
        a.mov_r("BP", 0)
        a.mov_r("CW", 0)
        for src in VEC:
            at = win.addr[hand.get(src, H_PLAIN)]
            a.op([0x36, 0xC7, 0x06, VEC[src], 0x00, at & 0xFF, at >> 8],
                 f"MOV word SS:[{VEC[src]:04X}h], {at:04X}h   ; {src}'s handler")
        for src, v in ic.items():
            oc.es_store(a, IC[src], v)
        ph.wtc1(a, odd)
        emit_ops(a, pre)
        a.mov_r("AW", 1)

    def body(a):
        emit_ops(a, ops, meta)
        a.op([0xFA], "DI")
        oc.es_store(a, 0xFF90, 0x00)
        oc.es_store(a, 0xFF91, 0x00)
        for src in IC:
            oc.es_store(a, IC[src], 0x47)
        ph.wtc1(a, 0)
    win.setup, win.body = setup, body
    return win


class Program(ph.Program):
    """phase.Program with the windows' handler variants laid out from 00C10h."""

    def build(self):
        if self._built:
            return self._built
        addr, blob = {H_PLAIN: ph.HANDLER}, bytearray()
        for w in self.windows:
            for h in w.hand.values():
                if h not in addr:
                    a = Asm(HBASE + len(blob))
                    emit_ops(a, h)
                    addr[h] = HBASE + len(blob)
                    blob += a.finish()
            w.addr = addr
        if HBASE + len(blob) > MARK:
            raise ValueError(f"{self.name}: {len(blob)} bytes of handlers")
        b = super().build()
        page = bytearray(b["segments"][0])
        page[HBASE:HBASE + len(blob)] = blob
        b["segments"][0] = bytes(page)
        b["text"] += bytes(blob)
        return b


def init(a):
    oc.ports_on(a)
    oc.ports_tout(a)


def prog(name, wins, note, entries=None):
    return Program(name, wins, note, init=init, fini=oc.ports_off, pins=["P15"], entries=entries)


START = ("st", 0xFF90, 0x8C)        # TM0 interval at /6, TOUT enabled (the pin falls at the start)


# ------------------------------------------------------------------ the series
def set_a():
    """HALT instrument, the first take and two more: mark, sled s, EI, ROL u, the start, HALT x 3.
    s moves EI against the grid (6 phases); u moves the start by whole grid periods."""
    out = []
    for u in range(0, 24, 3):
        for s in range(6):
            out.append(window("a", s, (("mark", 0), ("sled", s), ("mark", 1), ("ei",), ("rol", u), START,
                                       ("halt", 3)), odd=s & 1, u=u))
    return out


def hwin(series, n, ops, **kw):
    return window(series, n, (("mark", 1), ("ei",), START) + tuple(ops), **kw)


def set_b():
    """HALT x 4 with the handler lengthened: b1 ROL d ; FINT ; RETI, b2 FINT ; ROL d ; RETI."""
    out = []
    for d in range(0, 9):
        out.append(hwin("b1", d, (("halt", 4),), hand={"tm0": (("rol", d), ("fint",), ("reti",))}))
    for d in range(1, 9):
        out.append(hwin("b2", d, (("halt", 4),), hand={"tm0": (("fint",), ("rol", d), ("reti",))}))
    return out


STREAM = {
    "e0": (),
    "e1": (("di",), ("ei",)),
    "e2": (("fint",),),
    "e3": (("st", 0xFF00, 0x00),),          # an SFR store that is no request control register (P0's latch)
    "e4": (("st", 0xFF9D, 0x47),),          # a request control store (TMIC1, as it stands)
    "e5": (("st", 0xFE40, 0x00),),          # an internal RAM store
    "e6": (("ei",),),                       # EI with IE 1
    "e7": (("poppsw", 0xF202),),            # a PSW load with IE 1 (IE 1 before)
    "e8": (("st", 0xFF9C, 0x07),),          # the source's own request control register
    "e9": (("di",), ("poppsw", 0xF202)),    # DI, then a PSW load raising IE
}


def set_e():
    """Between the first take and the second HALT: ROL d, then X (STREAM), a mark."""
    out = []
    for name, x in STREAM.items():
        for d in ((0, 3) if name == "e0" else range(8)):
            out.append(hwin(name, d, (("halt", 1), ("rol", d)) + x + (("mark", 2), ("halt", 2))))
    return out


def set_g():
    """g: TM0's level 0 to 7, HALT x 4. f: TM0 (402 clocks) and TM1 (276) together, HALT x 10."""
    out = [hwin("g", lv, (("halt", 4),), ic={"tm0": lv}) for lv in range(8)]
    for lv in (7, 3):
        out.append(hwin("f", lv, (("st", 0xFF91, 0x80), ("halt", 10)), md1=45, ic={"tm0": lv, "tm1": lv}))
    return out


def set_c():
    """c: a request control store (TMIC0 07h, nothing pending), a sled of x clocks, EI, the start,
    HALT x 2. d: IE 0: the store, ROL u, the start, HALT (released by the request, not taken),
    a mark."""
    out = [window("c", x, (("st", 0xFF9C, 0x07), ("sled", x), ("mark", 1), ("ei",), START, ("halt", 2)),
                  odd=x & 1) for x in range(36)]
    out += [window("d", u, (("st", 0xFF9C, 0x07), ("rol", u), START, ("halt", 1), ("mark", 3), ("nop", 2)))
            for u in range(0, 36, 3)]
    return out


def set_t():
    """The INC train as the instrument: EI, the start, a sled of s clocks, 380 INC AW."""
    return [hwin("t", s, (("sled", s), ("inc", 380)), odd=s & 1) for s in range(10)]


def pin_set(series, ic, base, step, tail, n=32):
    """The INTP0 edge `base + step * j` ticks after the event's cycle (the schedule), then `tail`."""
    wins = [window(series, j, (("mark", 1), ("ei",), ("ev", j + 1)) + tail, ic=ic) for j in range(n)]
    ent = [dict(event=j + 1, delay=base + step * j, hold=600, levels={"INTP0": 0}) for j in range(n)]
    return wins, ent


PEND = {
    "1": (("st", 0xFF9C, 0x87),),                                            # TM0, level 7
    "2": (("st", 0xFF4C, 0x83), ("st", 0xFF9C, 0x87)),                       # INTP0 level 3, TM0 level 7
    "3": (("st", 0xFF4C, 0x87), ("st", 0xFF9C, 0x87)),                       # both level 7
    "4": (("st", 0xFF4C, 0x83), ("st", 0xFF6C, 0x85), ("st", 0xFF9C, 0x87)),  # levels 3, 5, 7
    "5": (("st", 0xFF4C, 0xC3), ("st", 0xFF9C, 0x87)),                       # INTP0 masked with IF 1; TM0 level 7
    "6": (("st", 0xFF9C, 0x80),),                                            # TM0, level 0
    "7": (("st", 0xFF9C, 0x83),),                                            # TM0, level 3
    # four levels: TM0 1, INTP0 3, SEIC0 5, SEIC1 7
    "9": (("st", 0xFF9C, 0x81), ("st", 0xFF4C, 0x83), ("st", 0xFF6C, 0x85), ("st", 0xFF7C, 0x87)),
}
NK = 40


def set_k(name):
    """IE 0: the requests set by stores (PEND), a sled of x clocks, a mark, EI, 60 INC AW."""
    return [window("k" + name, x, PEND[name] + (("sled", x), ("mark", 1), ("ei",), ("inc", 60)),
                   odd=x & 1, ic={}) for x in range(NK)]


def set_w(name):
    """IE 0: the requests set by stores (PEND), a sled of x clocks, HALT (released, nothing
    taken), a mark."""
    return [window("w" + name, x, PEND[name] + (("sled", x), ("halt", 1), ("mark", 3), ("nop", 2)),
                   odd=x & 1, ic={}) for x in range(NK)]


def set_q():
    """TM0's request flag read by the program: TMIC0 masked, MD0 9 (60 clocks), the start, a sled
    of s clocks, six reads of TMIC0 pushed."""
    return [window("q", s, (START, ("sled", s)) + (("rd", 0xFF9C),) * 6, odd=s & 1, md0=9,
                   ic={"tm0": 0x47}) for s in range(24)]


def set_s():
    """s: IE 1 and nothing pending: a mark, a store of IF 1 at level lv (the request and the
    restart at one clock), 40 INC AW. j: EI, ROL d, DI, a mark, the start, HALT (IE 0: released
    by the request on the lattice), a mark."""
    out = [window("s", lv, (("ei",), ("fil", 2), ("mark", 1), ("st", 0xFF9C, 0x80 | lv), ("inc", 40)), ic={})
           for lv in range(8)]
    out += [window("j", d, (("mark", 1), ("ei",), ("rol", d), ("di",), ("mark", 2), START, ("halt", 1),
                            ("mark", 3), ("nop", 2))) for d in range(1, 9)]
    return out


def programs():
    progs = [prog("f5_la_a", set_a(), "HALT: EI, then the timer's start; EI's place and the start's swept"),
             prog("f5_la_b", set_b(), "HALT: the handler lengthened in front of FINT and in front of RETI"),
             prog("f5_la_e", set_e(), "HALT: an instruction or a store in the stream between two takes"),
             prog("f5_la_g", set_g(), "HALT: the level; two sources"),
             prog("f5_la_c", set_c(), "a request control store against EI with nothing pending; HALT with IE 0"),
             prog("f5_la_t", set_t(), "the INC train behind a sled"),
             prog("f5_la_q", set_q(), "TM0's request flag read against the count-out"),
             prog("f5_la_s", set_s(), "a store of IF 1 with IE 1 by level; DI against the lattice")]
    for series, ic, base, step, tail, note in (
            ("h7", {"p0": 0x07, "tm0": 0x47}, 1000, 16, (("halt", 1),), "the INTP0 edge against the lattice in HALT, level 7"),
            ("h0", {"p0": 0x00, "tm0": 0x47}, 1000, 16, (("halt", 1),), "the INTP0 edge against the lattice in HALT, level 0"),
            ("p", {"p0": 0x47, "tm0": 0x47}, 320, 16, (("rd", 0xFF4C),) * 6, "INTP0's request flag read against the edge")):
        wins, ent = pin_set(series, ic, base, step, tail)
        progs.append(prog("f5_la_" + series, wins, note, entries=ent))
    for name in PEND:
        progs.append(prog("f5_la_k" + name, set_k(name), "IE 0, requests pending (PEND " + name + "): EI swept"))
        progs.append(prog("f5_la_w" + name, set_w(name), "IE 0, requests pending (PEND " + name + "): HALT swept"))
    return {p.name: p for p in progs}


# ------------------------------------------------------------------ reading
def events(rec, prog):
    """Per window: t0, marks {j: [tick]}, pins [(tick, level)], takes [(source, vector read's
    tick, pushed PSW, pushed PC)], stack reads, the event records, T."""
    wins, _ = oc.windows(rec, prog)
    inv = {v: k for k, v in VEC.items()}
    out = {}
    for k, w in wins.items():
        rows = w["rows"]
        e = dict(t0=w["t0"], T=w["T"], marks={}, pins=[], takes=[], evs=[], rd=[], meta=prog.windows[k].meta)
        for i, (kind, r) in enumerate(rows):
            if kind == "pin":
                e["pins"].append((r[0], 1 if r[1] & ph.P15 else 0))
            elif kind == "mw" and MARK <= r[1] < 0xE00:
                e["marks"].setdefault((r[1] - MARK) // 2, []).append(r[0])
            elif kind == "mr" and r[1] in inv:
                pushes = [x for kd, x in rows[i + 1:i + 8] if kd == "mw"][:3]
                e["takes"].append((inv[r[1]], r[0], pushes[0][2] if pushes else None,
                                   pushes[2][2] if len(pushes) > 2 else None))
            elif r[3] & 0x100:
                e["evs"].append(r[4])
        out[k] = e
    return out


def c(t):
    return ph.fmt(t / CLK)


def kind_of_take(m, pc):
    """d: the take straight out of HALT (the NOP's address pushed); n: after the NOP; - other."""
    hs = m.get("halts", [])
    if pc is None:
        return "?"
    return "d" if pc - 1 in hs else "n" if pc - 2 in hs else "-"


def report(name, backend, progs, verbose=False):
    rec = ph.load(name, backend)
    prog = progs[name]
    if rec["program_sha256"] != hashlib.sha256(prog.build()["text"]).hexdigest():
        print(f"{name} [{backend}]: THE RECEIPT IS OF ANOTHER VERSION OF THE PROGRAM")
    ev = events(rec, prog)
    ent = (rec.get("stim") or {}).get("entries") or []
    print(f"{name} [{backend}]: {'PASS' if rec['passed'] else 'FAIL'} total {rec['total']}, "
          f"{len(ev)}/{len(prog.windows)} windows, replay {rec['replay']}, residual {rec.get('stitch_residual')}")
    print("  per take: source kind (d straight out of HALT, n after the NOP) : vector read less the last "
          "mark, mod 16 : less the last TOUT edge (or the pin's edge) : less the last take (mod 16)")
    nev = 0
    for k in sorted(ev):
        e = ev[k]
        m = e["meta"]
        z = e["t0"]
        cells, last = [], None
        edges = []
        for t in e["evs"]:
            if nev < len(ent):
                edges.append(t + ent[nev]["delay"] + 4)
            nev += 1
        for src, t, psw, pc in e["takes"]:
            p = max([x for x, _ in e["pins"] if x < t] + [x for x in edges if x < t], default=None)
            mk = max([x for ts in e["marks"].values() for x in ts if x < t], default=None)
            d = round((t - last) / CLK) if last else None
            cells.append(f"{src}{kind_of_take(m, pc)}:"
                         f"{round((t - mk) / CLK) % 16 if mk else '-'}:{c(t - p) if p else '-'}:"
                         f"{'-' if d is None else f'{d}({d % 16})'}")
            last = t
        extra = " ".join(f"{x}={m[x]}" for x in m if x not in ("series", "form", "target", "seg", "shape",
                                                                "n", "halts", "ei", "first"))
        line = f"  w{k} {m['series']} n{m['n']} {extra}: " + " ".join(cells)
        if verbose or not e["takes"]:
            line += " | marks " + " ".join(f"m{j}@{c(t - z)}" for j, ts in sorted(e["marks"].items()) for t in ts)
            line += " | pins " + " ".join(c(t - z) for t, _ in e["pins"][:6])
            line += " | edges " + " ".join(c(t - z) for t in edges)
        print(line)


def summary(name, backend, progs):
    """The condensed figures per series (what RESULTS quotes): k series: the takes' signature
    (source: vector read less mark 1 / INCs run) and the sled lengths that give it; w series and
    d / j: the mark behind HALT in clocks after the begin marker; the pin series: the latest edge
    taken at each vector read (clocks after mark 1) and the read's threshold; q / p: the flag
    read's threshold; the others: per series the first and second takes' (kind, vector read less
    the last mark mod 16), later takes' (kinds, less the previous vector read mod 16; less the
    last PSW pop's read at 00EFEh mod 16), the range of vector read less TOUT's edge by kind."""
    import collections
    rec = ph.load(name, backend)
    prog = progs[name]
    ev = events(rec, prog)
    wins, _ = oc.windows(rec, prog)
    ent = (rec.get("stim") or {}).get("entries") or []
    print(f"{name} [{backend}]")
    S = collections.OrderedDict()
    for k in sorted(ev):
        e, m, z = ev[k], ev[k]["meta"], ev[k]["t0"]
        sr = m["series"]
        d = S.setdefault(sr, dict(sig=collections.OrderedDict(), wake=[], first=collections.Counter(),
                                  second=collections.Counter(), later=collections.Counter(),
                                  pop=collections.Counter(), vc={}, cut={}, rd=[]))
        m1 = e["marks"].get(1, [None])[0]
        edge = e["evs"][0] + ent[k]["delay"] + 4 if e["evs"] and k < len(ent) else None
        pushes = [r for kind, r in wins[k]["rows"] if kind == "mw" and 0xE00 <= r[1] < STACK_TOP]
        pops = [r[0] for kind, r in wins[k]["rows"] if kind == "mr" and r[1] == STACK_TOP - 2]
        ref = edge if edge is not None else e["pins"][1][0] if len(e["pins"]) > 1 else None
        if sr in ("q", "p") and ref is not None:
            d["rd"] += [((r[0] - ref) / CLK, r[2] >> 7 & 1) for r in pushes]
        if sr[0] == "k":
            sig = " ".join(f"{src}:{c(t - m1)}/n{pc - m['first'] if pc is not None else '?'}"
                           for src, t, psw, pc in e["takes"])
            d["sig"].setdefault(sig, []).append(m["n"])
        if 3 in e["marks"]:
            d["wake"].append(f"{m['n']}:{c(e['marks'][3][0] - z)}")
        last, lk = None, None
        for i, (src, t, psw, pc) in enumerate(e["takes"]):
            kd = kind_of_take(m, pc)
            mk = max([x for ts in e["marks"].values() for x in ts if x < t], default=None)
            pin = max([x for x, _ in e["pins"] if x < t], default=None)
            pp = max([x for x in pops if x < t], default=None)
            if i < 2 and mk is not None:
                d["first" if i == 0 else "second"][(kd, round((t - mk) / CLK) % 16)] += 1
            if last is not None:
                d["later"][(lk + kd, round((t - last) / CLK) % 16)] += 1
                if pp is not None:
                    d["pop"][(kd, round((t - pp) / CLK) % 16)] += 1
            if pin is not None:
                v = (t - pin) / CLK
                lo, hi = d["vc"].get(kd, (v, v))
                d["vc"][kd] = (min(lo, v), max(hi, v))
            if edge is not None and m1 is not None and i == 0:
                key = (round((t - m1) / CLK), kd)
                d["cut"][key] = max(d["cut"].get(key, -1e9), (edge - m1) / CLK)
            last, lk = t, kd
    f = lambda cn: " ".join(f"{a}{b}x{n}" for (a, b), n in sorted(cn.items()))
    for sr, d in S.items():
        if d["sig"]:
            for sig, xs in sorted(d["sig"].items(), key=lambda kv: -len(kv[1])):
                print(f"  {sr}: {sig or 'no take':58s} x " + (" ".join(map(str, xs)) if len(xs) < 12
                                                             else f"{len(xs)} windows"))
        elif d["wake"]:
            print(f"  {sr}: the mark behind HALT, x:clock: " + " ".join(d["wake"]))
        elif d["rd"]:
            no = [x for x, sn in d["rd"] if not sn]
            yes = [x for x, sn in d["rd"] if sn]
            below = [x for x in no if x < min(yes)]
            print(f"  {sr}: the push's start less the {'edge' if ent else 'count-out (TOUT)'}: not seen up to "
                  f"{max(below):.2f}, seen from {min(yes):.2f}")
        elif d["cut"]:
            print(f"  {sr}: vector read (clocks after mark 1, kind): the latest edge taken there (after mark 1; "
                  f"the read less it): " + " ".join(f"{v}{kd}:{x:.1f}({v - x:.1f})" for (v, kd), x in sorted(d["cut"].items())))
        else:
            print(f"  {sr}: first [{f(d['first'])}] second [{f(d['second'])}] later [{f(d['later'])}] "
                  f"after a PSW pop [{f(d['pop'])}] V-C "
                  + " ".join(f"{k}:{lo:.1f}..{hi:.1f}" for k, (lo, hi) in sorted(d["vc"].items())))


def emit(progs):
    for name, p in progs.items():
        (ph.PROGRAMS_DIR / f"{name}.s").write_text(p.source())
        b = p.build()
        if p.stim:
            (ph.PROGRAMS_DIR / f"{name}.stim.json").write_text(json.dumps(p.stim, indent=1) + "\n")
        print(f"{name}: {len(b['text'])} bytes, {len(p.windows)} windows, {len(b['segments'])} pages")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "report", "summary", "repeat", "gate", "emit"))
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
    elif a.action == "report":
        for n in names:
            report(n, a.ref + a.tag, progs, a.verbose)
    elif a.action == "summary":
        for n in names:
            summary(n, a.ref + a.tag, progs)
    elif a.action in ("repeat", "gate"):
        ok = True
        for n in names:
            ok &= ph.compare(n, a.ref, "socket-2" if a.action == "repeat" else a.cand, progs,
                             verbose=a.verbose)
        return 0 if ok else 1
    else:
        emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
