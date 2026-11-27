"""The readers of introws2.py's receipts (`introws2 read`).

A (f5_le_ programs with twins): per pair of windows, clocks from mark 1's write: the ask (35 at level 7), the
twin's fetch starts (nothing asked), the asked window's, the first fetch that moved and by how much, the vector
read; with `build/tr/NAME.{trace,qdbg}` (introws2 sim NAME --trace) the landed core's releases in front of the
fetch: `clock relative to T : bytes held after it`.

B: H1 through lattice.report; H2 and the HLDRQ sets as a timeline from mark 1 (the pins' edges, the bus cycles,
the take).
"""

from __future__ import annotations

import os

from . import lattice as la
from . import onchip_t as oc
from . import phase as ph
from .wtc import CLK

MARK1 = la.MARK + 2


def rows_of(w):
    return [(kind, r) for kind, r in w["rows"] if kind != "pin"]


def take_row(rows, mi):
    return next((i for i, (kind, r) in enumerate(rows) if i > mi and kind == "mr" and r[1] < 0x80), None)


def fetches(w, span=70):
    """(the fetch starts in clocks behind mark 1's write up to the vector read or `span`, the vector read, the
    pushed PC)."""
    rows = rows_of(w)
    mi = next(i for i, (kind, r) in enumerate(rows) if kind == "mw" and r[1] == MARK1)
    tm = rows[mi][1][0]
    vi = take_row(rows, mi)
    end = len(rows) if vi is None else vi
    f = [round((r[0] - tm) / CLK) for kind, r in rows[mi + 1:end] if kind in ("fetch", "mr", "mw")
         and (r[0] - tm) / CLK <= span]
    v = None if vi is None else round((rows[vi][1][0] - tm) / CLK)
    pcs = [x for kd, x in rows[vi:vi + 6] if kd == "mw"] if vi is not None else []
    return f, v, (pcs[2][2] if len(pcs) > 2 else None)


class CoreTrace:
    """build/tr/NAME.trace / .qdbg / .idbg of the landed core: per window (the k-th write at mark 1) the releases
    (clock from the mark, bytes held after) and the clock the controller's count first stands at 5 (the ask)."""

    def __init__(self, name):
        base = f"build/tr/{name}"
        self.ok = all(os.path.exists(base + e) for e in (".trace", ".qdbg", ".idbg"))
        if not self.ok:
            return
        lines = open(base + ".trace").read().split("\n")
        end = next((i for i, l in enumerate(lines) if i > 0 and l.startswith("# reset")), len(lines))
        self.t0 = [int(l.split()[0]) for l in lines[:end] if f"X:write:{MARK1:05x}" in l]
        self.q, last = {}, -1
        for l in open(base + ".qdbg"):
            r = l.split()
            if len(r) > 19 and r[0] == "q":
                t = int(r[1])
                if t < last:
                    break                       # the next run of the stitched trace
                last = t
                self.q[t] = (int(r[11]), int(r[19]), int(r[13]), int(r[17]))      # occ, rls, req, go
        self.c = {}
        for l in open(base + ".idbg"):
            f = l.split()
            if f and f[0].isdigit():
                d = dict(x.split("=") for x in f[1:] if "=" in x)
                if d.get("h") == "1" and d.get("d") == "5":
                    self.c.setdefault(int(f[0]), 5)

    def releases(self, k, lo, hi):
        t0 = self.t0[k]
        return [(t - t0, self.q[t][0], self.q[t][1]) for t in range(t0 + lo, t0 + hi + 1) if t in self.q and self.q[t][1]]

    def occ(self, k, c):
        q = self.q.get(self.t0[k] + c)
        return None if q is None else q[0]

    def ask(self, k):
        t0 = self.t0[k]
        return next((t - t0 for t in sorted(self.c) if t0 <= t <= t0 + 80), None)


def brief_a(name, ref, progs):
    """One line a lead: per window `ask - T : .` (nothing moved in front of the take), `H` (the fetch due at T
    starts at T + 2: the cycle took its slot), or the cycle that moved; then the landed core's releases."""
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        rows = read_a(name, ref, progs)
    ct = CoreTrace(name)
    by = {}
    for i, (m, T, ask, mv, v) in enumerate(rows):
        code = "." if mv is None else "H" if mv[0] == T and mv[1] == T + 2 else f"[{mv[0]}>{mv[1]}]"
        rl = ""
        if ct.ok and T is not None:
            rl = " ".join(f"{c - T:+d}:{o}" + (f"x{n}" if n > 1 else "") for c, o, n in ct.releases(2 * i + 1, T - 8, T + 1))
        key = m.get("ld", "") if "ld" in m else f"w{m['wt']}"
        by.setdefault(key, []).append((ask - T if T is not None else 99, code, rl, T, v))
    for key, v in by.items():
        v.sort()
        rls = sorted({x[2] for x in v}, key=lambda r: -sum(x[2] == r for x in v))
        print(f"{name[6:]:5s} {key:5s} " + " ".join(f"{d:+d}:{c}" for d, c, _, _, _ in v) + "  || core: " + "  /  ".join(rls[:2]))


def read_a(name, ref, progs, verbose=False):
    p = progs[name]
    W = oc.windows(ph.load(name, ref), p)[0]
    S = oc.windows(ph.load(name, "sim"), p)[0] if ref != "sim" and ph.receipt_path(name, "sim").exists() else None
    ct = CoreTrace(name)
    ask = 21 + 2 * p.windows[0].meta["lv"]
    print(f"{name} [{ref}]: clocks from mark 1's write; the ask {ask}; T: the twin's first fetch at or behind "
          f"ask - 1 (ask = T: the fetch is due on the ask clock)")
    print("  rn wt | T    ask-T | the twin's fetches (from T - 9) | asked: the first cycle that moved | V    | "
          "the core's releases, clock - T : held after" + ("" if ct.ok else " (no core trace)"))
    out = []
    for k in range(0, len(p.windows), 2):
        m = p.windows[k].meta
        ask = 21 + 2 * m["lv"]
        fr, v, pc = fetches(W[k])
        ft, _, _ = fetches(W[k + 1])
        T = next((x for x in ft if x >= ask - 1), None)
        if T is not None and T == ask - 1:
            # a fetch that starts one clock in front of the ask is running at the ask: the next one is T
            T2 = next((x for x in ft if x > T), None)
            run = T
        else:
            run = next((x for x in reversed(ft) if x < ask and x + 3 > ask), None)
        mv = next(((x, y) for x, y in zip(ft, fr) if x != y), None)
        if mv is None and len(fr) < len(ft) and v is not None:
            moved = "none in front of the take"
        elif mv is None:
            moved = "none"
        else:
            moved = f"{mv[0]} > {mv[1]} ({mv[1] - mv[0]:+d})"
        core = ""
        if ct.ok and T is not None:
            rl = ct.releases(k + 1, ask - 10, T + 1)
            core = " ".join(f"{c - T:+d}:{o}" + (f"x{n}" if n > 1 else "") for c, o, n in rl)
            ca = ct.ask(k)
            core += (" | held at ask-2 .. ask+1 " + " ".join(str(ct.occ(k + 1, ask + i)) for i in (-2, -1, 0, 1))
                     + ("" if ca == ask else f" | THE CORE ASKS AT {ca}"))
        sim = ""
        if S is not None:
            st = fetches(S[k + 1])[0]
            if st[:len(ft)] != ft[:len(st)]:
                sim = "  TWIN: the core's fetches differ: " + " ".join(map(str, [x for x in st if x >= (T or ask) - 9][:8]))
        tw = " ".join(str(x) for x in ft if T is not None and T - 9 <= x <= T + 12)
        print(f"  {m['rn']:2d} {m['wt']:2d} {m.get('ld', ''):5s}| {ask} {T if T is not None else '-':>3} {ask - T if T is not None else 0:+3d}   | "
              f"{tw:34s} | {moved:26s} | {v if v is not None else '-':>4} | {core}{sim}"
              + (f" | cycle running at the ask from {run}" if run is not None else ""))
        if verbose:
            print(f"        asked: {' '.join(map(str, fr))}  pc {pc}")
        out.append((m, T, ask, mv, v))
    return out


def all_windows(rec, prog):
    """oc.windows, and the window the trace ends in (a run that stood still): its T is None."""
    end = prog.build()["code_end"]
    out, cur = {}, None
    for row in rec["trace"]:
        kind = oc.kind_of(row, end)
        if kind == "iow" and row[1] == oc.M_BEGIN:
            cur = dict(k=row[2], t0=row[0], open=row, rows=[], T=None)
            out[cur["k"]] = cur
            continue
        if kind == "iow" and row[1] == oc.M_END and cur is not None:
            cur.update(t1=row[0], T=row[0] - cur["t0"])
            cur = None
            continue
        if cur is not None:
            cur["rows"].append((kind, row))
    return out


def timeline(w, ent, verbose=False, pins=()):
    """A window from mark 1 (clocks behind its write): the scheduled edges (the event record's end + delay + 4;
    a chained entry + 10 behind its predecessor's last change), /HLDAK's, TOUT's and /INTAK's records, the bus
    cycles; without -v from 12 clocks in front of the first scheduled edge to the handler's first fetch."""
    rows = w["rows"]
    mi = next((i for i, (kind, r) in enumerate(rows) if kind == "mw" and r[1] == MARK1), None)
    if mi is None:
        return "no mark"
    tm = rows[mi][1][0]
    c = lambda t: f"{(t - tm) / CLK:.2f}".rstrip("0").rstrip(".")
    ev = next((r for kind, r in rows if kind != "pin" and r[3] & 0x100), None)
    out, first = [], None
    if ev is not None and ent:
        t = None
        for e in ent:
            if e["event"] is not None:
                t = ev[4] + e["delay"] + 4
            else:
                t += e["delay"] + 10
            first = t if first is None else first
            lv = ",".join(f"{n}={v}" for n, v in e["levels"].items()) or "-"
            out.append((t, f"[{lv}]@{c(t)}"))
            if e["hold"]:
                t += e["hold"]
                out.append((t, f"[/{lv}]@{c(t)}"))
    pv = lambda r: [r[2] >> 6 & 1, r[1] >> 13 & 1, r[1] >> 11 & 1]      # P26 /HLDAK, P15 TOUT, P13 /INTAK
    last = [1 if "P26" in pins else None, None, 1 if "P13" in pins else None]
    for kind, r in rows[:mi]:
        if kind == "pin":
            last = [v if x is not None else None for v, x in zip(pv(r), last[:1] + [0] + last[2:])]
    stop = None
    for kind, r in rows[mi:]:
        if kind == "pin":
            lv = pv(r)
            for nm, a, b in zip(("HLDAK", "TOUT", "INTAK"), last, lv):
                if a is not None and a != b:
                    out.append((r[0], f"{nm}{'^' if b else 'v'}@{c(r[0])}"))
            last = [v if x is not None else None for v, x in zip(lv, last)]
            continue
        if stop is None and kind == "fetch" and (r[1] & 0xFFF00) == 0x00C00:
            stop = r[0]
        nm = {"fetch": "f", "mr": "r", "mw": "w", "iow": "o", "ior": "i"}.get(kind, kind)
        out.append((r[0], f"{nm}{r[1] & 0xFFFFF:05X}@{c(r[0])}" + (f"+{oc.waits_of(r)}w" if oc.waits_of(r) else "")))
    out.sort(key=lambda x: x[0])
    if not verbose:
        lo = tm if first is None else first - 12 * CLK
        out = [x for x in out if x[0] >= lo and (stop is None or x[0] <= stop)]
    return " ".join(s for _, s in out) + ("" if w["T"] is not None else "  << THE RUN ENDS HERE (stands still)")


def read_b(name, ref, progs, verbose=False):
    p = progs[name]
    ent = (p.stim or {}).get("entries") or []
    per = len(ent) // len(p.windows) if ent else 0
    if ref.startswith("sim1"):
        from . import introws2 as r2
        runs = ph.load(name, ref)["runs"]
        print(f"{name} [{ref}]: one window a run; standing still: "
              + (" ".join(s for s in runs if runs[s]["timeout"]) or "none"))
        for s, rec in runs.items():
            p1 = r2.one(f"{name}.{s}")
            W = all_windows(rec, p1)
            print(f"  s{s} timeout={rec['timeout']}: " + (timeline(W[0], p1.stim["entries"], verbose, p1.stim["pins"]) if 0 in W else "no window"))
        return
    rec = ph.load(name, ref)
    W = all_windows(rec, p)
    print(f"{name} [{ref}]: passed {rec['passed']} timeout {rec['timeout']} windows "
          f"{sum(w['T'] is not None for w in W.values())} of {len(p.windows)}")
    for k, w in enumerate(p.windows):
        m = w.meta
        tag = " ".join(f"{x}={m[x]}" for x in ("sl", "a", "j", "nn") if x in m)
        if k not in W:
            print(f"  w{k} {tag}: not reached")
            continue
        print(f"  w{k} {tag}: " + timeline(W[k], ent[per * k:per * (k + 1)], verbose, p.stim["pins"]))


# ------------------------------------------------------------------ rows 4 (ROWS-INT4)
class Pops:
    """build/tr/NAME.trace of the landed core (introws2 sim NAME --trace): per window (the k-th write at mark 1 of
    the first run) the clocks behind the mark of HALT's first word (S:u242) and of every instruction's dispatch."""

    def __init__(self, name):
        path = f"build/tr/{name}.trace"
        self.ok = os.path.exists(path)
        self.pops, self.starts, self.vec = [], [], []
        if not self.ok:
            return
        t0 = None
        with open(path) as f:
            for i, l in enumerate(f):
                if l[0] == "#":
                    if i:
                        break
                    continue
                if f"X:write:{MARK1:05x}" in l:
                    t0 = int(l.split(" ", 1)[0])
                    self.pops.append([])
                    self.starts.append([])
                    self.vec.append(None)
                elif t0 is not None and self.vec[-1] is None and ("X:read:0002c" in l or "X:read:00008" in l):
                    self.vec[-1] = int(l.split(" ", 1)[0]) - t0
                elif t0 is not None and " S:u" in l:
                    t = int(l.split(" ", 1)[0]) - t0
                    u = l.split(" S:u", 1)[1].split(":", 1)[0]
                    self.starts[-1].append((t, int(u)))
                    if u == "242":
                        self.pops[-1].append(t)


def g_window(w, ent):
    """A window's facts in clocks behind mark 1's write: the scheduled edges, the bus cycles [(clock, kind, address,
    clocks)], the takes [(vector read's clock, vector, pushed PC)], the pin records [(clock, P13, P15)]."""
    rows = rows_of(w)
    mi = next(i for i, (kind, r) in enumerate(rows) if kind == "mw" and r[1] == MARK1)
    tm = rows[mi][1][0]
    ev = next((r for kind, r in rows if r[3] & 0x100), None)
    edges, t = [], None
    for e in ent:
        t = ev[4] + e["delay"] + 4 if e["event"] is not None else t + e["delay"] + 10
        edges.append((t - tm) / CLK)
        t += e["hold"]
    cyc = [(round((r[0] - tm) / CLK), kind, r[1], oc.waits_of(r) + 3) for kind, r in rows[mi + 1:]]
    takes = []
    for i, (kind, r) in enumerate(rows):
        if i > mi and kind == "mr" and r[1] < 0x80 and not r[1] & 3:
            pcs = [x for kd, x in rows[i + 1:i + 8] if kd == "mw"]
            takes.append((round((r[0] - tm) / CLK), r[1], pcs[2][2] if len(pcs) > 2 else None))
    pins = [((r[0] - tm) / CLK, r[1] >> 11 & 1, r[1] >> 13 & 1) for kind, r in w["rows"] if kind == "pin"]
    return dict(edges=edges, cyc=cyc, takes=takes, pins=pins, tm=tm, ev=None if ev is None else ev[4])


def g_facts(name, ref, progs, base=None):
    """Per window of an (a) program: its facts and per NMI take the core's pop of HALT in front of it, the edge, the
    bus cycles from 8 clocks in front of the pop (start - pop, kind, clocks), the clocks of bus cycles between the
    pop and the vector read (busy) and the rest (idle). base: the core's own facts (g_facts of the `sim` receipt):
    behind a take that came on another clock than the core's, the core's later pops are moved by that difference
    (f5_lg_a18's second HALT)."""
    p = progs[name]
    ent = p.stim["entries"]
    per = len(ent) // len(p.windows)
    W = all_windows(ph.load(name, ref), p)
    pt = Pops(name)
    out = []
    for k, w in enumerate(p.windows):
        m = w.meta
        if k not in W or W[k]["T"] is None:
            out.append(None)
            continue
        g = g_window(W[k], ent[per * k:per * (k + 1)])
        pops = pt.pops[k] if pt.ok and k < len(pt.pops) else []
        d = dict(k=k, m=m, g=g, pops=pops, takes=[])
        shift = 0
        for v, vec, pc in g["takes"]:
            if vec != 0x08:
                continue
            pop = next((x + shift for x in reversed(pops) if x + shift < v), None)
            edge = max((e for e in g["edges"] if e < v), default=None)
            hs = m.get("halts", [])
            kind = "?" if pc is None else "d" if pc - 1 in hs else "n" if pc - 2 in hs else "h" if pc in hs else "-"
            f = dict(v=v, pc=pc, kind=kind, pop=pop, edge=edge)
            if pop is not None:
                near = [(c, kd, a, ln) for c, kd, a, ln in g["cyc"] if pop - 8 <= c < v]
                f["cyc"] = [(c - pop, kd, ln) for c, kd, a, ln in near]
                f["busy"] = sum(1 for c, kd, a, ln in near for x in range(c, c + ln) if pop <= x < v)
                last = max((c + ln for c, kd, a, ln in near), default=None)
                f["last"] = None if last is None else last - pop     # the first clock behind the last cycle
                f["idle"] = v - pop - f["busy"]
            d["takes"].append(f)
            n = len(d["takes"]) - 1
            if base is not None and base[k] is not None and n < len(base[k]["takes"]):
                shift = v - base[k]["takes"][n]["v"]
        out.append(d)
    return out


G_KD = {"fetch": "f", "mr": "r", "mw": "w", "iow": "o", "ior": "i"}


def read_g(name, ref, progs, verbose=False):
    """(a): per window the NMI take against the landed core's pop of HALT (build/tr/NAME.trace), the edge and the bus
    cycles; then per X the take by the edge's clock."""
    S = g_facts(name, "sim", progs) if ref.startswith("socket") and ph.receipt_path(name, "sim").exists() else None
    F = g_facts(name, ref, progs, base=S)
    print(f"{name} [{ref}]: clocks; pop: the core's first word of HALT behind mark 1's write; cycles: start - pop "
          f"(f fetch, r read, w write, i / o I/O; +n: clocks over three); V: NMI's vector read; idle: V - pop less the "
          f"clocks of bus cycles in between; last: the first clock behind the last cycle; kind d: the take straight "
          f"out of HALT")
    by = {}
    for k, d in enumerate(F):
        if d is None:
            print(f"  w{k}: missing")
            continue
        m = d["m"]
        cells = []
        for n, f in enumerate(d["takes"]):
            if f["pop"] is None:
                cells.append(f"V {f['v']} {f['kind']} (no pop: the core's trace)")
                continue
            cy = " ".join(f"{G_KD.get(kd, kd)}{c:+d}" + (f"+{ln - 3}" if ln != 3 else "") for c, kd, ln in f["cyc"])
            sim = ""
            if S is not None and S[k] is not None and n < len(S[k]["takes"]):
                sf = S[k]["takes"][n]
                if (sf["v"] - sf["pop"], sf.get("cyc")) != (f["v"] - f["pop"], f.get("cyc")):
                    sim = (f" | core: V-pop {sf['v'] - sf['pop']} {sf['kind']}"
                           + ("" if sf.get("cyc") == f.get("cyc") else " CYCLES DIFFER"))
            cells.append(f"pop {f['pop']:3d} edge-pop {f['edge'] - f['pop']:5.2f} | {cy:28s} | V-pop {f['v'] - f['pop']:2d} "
                         f"V-edge {f['v'] - f['edge']:5.2f} last {f['last']} idle {f['idle']:2d} {f['kind']}{sim}")
            by.setdefault((m["xk"], n), []).append((f["edge"] - f["pop"], f["v"] - f["pop"], f["idle"], f["last"],
                                                    f["kind"], tuple(c for c, kd, ln in f["cyc"] if c >= -3)))
        print(f"  w{k:2d} {m['xk']:4s} s{m['sl']} j{m['j']}: " + " || ".join(cells or ["no take"]))
    for (xk, n), v in by.items():
        v.sort()
        print(f"  {xk}{'' if not n else ' (take ' + str(n + 1) + ')'}: edge-pop > V-pop: "
              + " ".join(f"{e:.1f}>{x}" for e, x, _, _, _, _ in v)
              + f" | (V-pop) mod 2 {sorted({x % 2 for _, x, _, _, _, _ in v})} idle mod 2 "
              f"{sorted({i % 2 for _, _, i, _, _, _ in v})} kinds {''.join(sorted({kd for _, _, _, _, kd, _ in v}))} "
              f"cycles from pop - 3: {sorted({c for _, _, _, _, _, c in v})}")


def h_key(m):
    return (m.get("a"), m.get("sl"), m.get("rx", 0) & 1, m.get("rn"))


def h_facts(name, ref, progs):
    """Per window of a (c) program: the request's edge, the pop of HALT in the landed core's trace (of this window
    where the core entered HALT in front of its own take, else of a window with the same code in front of HALT),
    /INTAK's first fall, the takes [(vector read, vector, pushed PC less X's address)]; clocks behind mark 1's
    write. The request is the NMI pin in the f5_lg_n2* sets."""
    p = progs[name]
    ent = p.stim["entries"]
    per = len(ent) // len(p.windows)
    rec = ph.load(name, ref)
    W = all_windows(rec, p)
    pt = Pops(name)
    if os.path.exists(f"build/tr/{name}.nominal.trace"):
        pt = Pops(name + ".nominal")        # the core's run with the request left out (build/an/nominal.py)
    nom = {}
    if pt.ok:
        for k, w in enumerate(p.windows):
            if k < len(pt.pops) and pt.pops[k] and (pt.vec[k] is None or pt.pops[k][0] < pt.vec[k]):
                nom.setdefault(h_key(w.meta), pt.pops[k][0])
    req = 0x08 if "_n2" in name else 0x2C
    out = []
    for k, w in enumerate(p.windows):
        m = w.meta
        if k not in W:
            out.append(None)
            continue
        g = g_window(W[k], ent[per * k:per * (k + 1)])
        e = g["edges"][0]
        x0 = m.get("x", [None])[0]
        takes = [(v, vec, None if pc is None or x0 is None else pc - x0) for v, vec, pc in g["takes"]]
        out.append(dict(k=k, m=m, g=g, edge=e, pop=nom.get(h_key(m)), ended=W[k]["T"] is not None,
                        ia=next((t for t, p13, p15 in g["pins"] if t > e and not p13), None),
                        tk=next((x for x in takes if x[1] == req), None), takes=takes))
    return rec, out


def read_h(name, ref, progs, verbose=False):
    """(c): per window /INTAK's first fall and the request's vector read against the edge and against the core's pop
    of HALT."""
    rec, F = h_facts(name, ref, progs)
    print(f"{name} [{ref}]: passed {rec['passed']} timeout {rec['timeout']}; clocks behind mark 1's write: the "
          f"request's edge, the core's pop of HALT (where the request is not taken in front of it); /INTAK's first fall "
          f"(IA) and the vector read (V) less the edge and less the pop; pc: the pushed PC less X's address (X: HALT, or "
          f"the first NOP of a train); then every take of the window (i INT, n NMI)")
    f2 = lambda x: "-" if x is None else f"{x:.2f}".rstrip("0").rstrip(".")
    sub = lambda a, b: None if a is None or b is None else a - b
    for k, d in enumerate(F):
        if d is None:
            print(f"  w{k}: not reached")
            continue
        m, e, pop, ia, tk = d["m"], d["edge"], d["pop"], d["ia"], d["tk"]
        tag = " ".join(f"{x}={m[x]}" for x in ("a", "sl", "rx", "rn", "j") if x in m)
        v = tk[0] if tk else None
        line = (f"  w{k:2d} {tag}: edge {f2(e)} pop {f2(pop)} edge-pop {f2(sub(e, pop))} | IA-edge {f2(sub(ia, e))} V-edge "
                f"{f2(sub(v, e))} | IA-pop {f2(sub(ia, pop))} V-pop {f2(sub(v, pop))} | "
                + " ".join(f"{'i' if vec == 0x2C else 'n' if vec == 0x08 else '?'}@{tv}:x{'?' if pc is None else format(pc, '+d')}"
                           for tv, vec, pc in d["takes"]))
        if not d["ended"]:
            line += "  << THE RUN ENDS HERE"
        if verbose:
            line += " | " + " ".join(f"{G_KD.get(kd, kd)}{c}" for c, kd, a2, ln in d["g"]["cyc"] if c < (v or 200))
        print(line)


def main(a, progs, names):
    for n in names:
        if n.startswith("f5_lg_a"):
            read_g(n, a.ref + a.tag, progs, a.verbose)
        elif n.startswith("f5_lg_h2") or n.startswith("f5_lg_n2"):
            read_h(n, a.ref + a.tag, progs, a.verbose)
        elif n.startswith("f5_le_h1"):
            la.report(n, a.ref + a.tag, progs, a.verbose)
        elif n.startswith("f5_le_h2") or n.startswith("f5_le_b"):
            read_b(n, a.ref + a.tag, progs, a.verbose)
        elif a.brief:
            brief_a(n, a.ref + a.tag, progs)
        else:
            read_a(n, a.ref + a.tag, progs, a.verbose)
    return 0
