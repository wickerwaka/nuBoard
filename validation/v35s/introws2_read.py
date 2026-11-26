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


def main(a, progs, names):
    for n in names:
        if n.startswith("f5_le_h1"):
            la.report(n, a.ref + a.tag, progs, a.verbose)
        elif n.startswith("f5_le_h2") or n.startswith("f5_le_b"):
            read_b(n, a.ref + a.tag, progs, a.verbose)
        elif a.brief:
            brief_a(n, a.ref + a.tag, progs)
        else:
            read_a(n, a.ref + a.tag, progs, a.verbose)
    return 0
