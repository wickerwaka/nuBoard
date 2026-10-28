"""Per-clock state statistics of the fitted chain model over the corpus (HDL plan, Phase A2).

    python -m validation.v35s.chains.statestats [--family F0 ...] [--jobs N] [--out PATH]

Simulates every modelled run (families.FAMILIES less families.UNMODELLED) under the fitted
Config (fit.json) with a clock log, which turns the quiet-clock fast-forward off, and reduces
the state at the end of every clock to, per state variable: the values seen with their
counts, the minimum and maximum, the number of distinct values and (integer variables) a
histogram summary, with the run that first reached each extreme.

Two sources per clock. The keys of Machine._clock_row (prefix "row."), and every attribute
the machines hold, read from the machine objects by a Machine subclass (prefix "bus.",
"queue.", "decoder.", "eu.", "refresh.", and "eu.req." / "eu.own." / "eu.queued0." for the
bus unit's request slot and the requests behind it). Nothing in sim/ is edited: the worker
swaps machine.Machine for the subclass while it simulates.

Clock-valued variables (a clock number: "the last clock X happened", "no issue before
clock N", "resume on clock N") are reported as an offset from the clock the row describes
(value - t), clipped below at -STALE ("stale": further back than any rule compares): their
widths in RTL are those of the offset, not of an absolute clock. A fetch-count target (the
take sync's int value) is reported against queue.completed, an address against the chain
base. Variables that are logs (eu.trace, bus.cycles, refresh.served), constants of the run
(the configuration, the code) or object references are skipped or reduced to presence.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import sys
import time
from collections import Counter
from contextlib import contextmanager

from .families import FAMILIES, UNMODELLED

STALE = 256                  # a clock offset below -STALE is reported as -STALE ("stale")
INF = 1 << 30                # float("inf") (an OUT's latch held until its cycle ends)

# Clock-valued attributes, by machine (reported as value - t)
TIME = {
    "bus": {"last_end", "last_fetch_end", "last_io_end", "last_cpu_end"},
    "queue": {"requested_at", "arrived_t", "removed_t", "b2b_at", "disp_t", "io_held",
              "after_refresh", "lost_start", "lost_eval", "lost_after", "read_t", "ir_t",
              "take_t", "start_t", "abort_end", "abort_t", "retry_at", "shift_until",
              "mate_t", "nop_held", "latch_in_t", "qport_t", "io_run_at", "t4_at"},
    "decoder": {"ready_at", "ea_end"},
    "eu": {"resume", "since_t", "latch_until", "reg_latch_t", "start_at", "wb_until",
           "done_t", "latch_wait", "wlatch_until", "start_clock", "fetch_start", "halt_t",
           "halt_defer", "clk_end", "clk_start", "hold_from", "hold_end", "exec_t", "port_t",
           "dfloor_at"},
    "refresh": {"enable_at", "due", "pending"},
    "req": {"posted", "done_at", "ready_since", "not_before", "lift_t", "free_held",
            "grp_held"},
}
# Attributes that are logs, run constants or references (not state the RTL holds per clock)
SKIP = {
    "bus": {"cycles", "waits_mem", "waits_io", "min_gap", "sfr_cycle", "refresh_whole"},
    "queue": {"cfg", "code", "base", "decoder", "eu", "skip_before", "snap", "fetch_len",
              "peak"},
    "decoder": {"cfg", "queue"},
    "eu": {"cfg", "code", "base", "regs", "decoder", "bus", "trace", "origin", "refresh",
           "ls_shift"},
    "refresh": {"cfg", "bus", "served", "writes", "timer"},
    "req": set(),
}
ROW_TIME = {"requested_at", "resume", "clk_start", "clk_end"}


def _row(t: int, row: dict, m) -> dict:
    """The reduced values of one clock row: {name: hashable value}."""
    out = {}
    for k, v in row.items():
        if k == "t":
            continue
        name = "row." + k
        if k in ROW_TIME:
            out[name] = _off(v, t)
        elif k == "step":
            out[name] = None if v is None else v[0]
        elif k == "req":
            out["row.req.kind"] = None if v is None else v[0]
            out["row.req.count"] = None if v is None else v[1]
            out["row.req.setup"] = None if v is None else v[2]
        elif k == "sync":
            out[name] = _sync(v, m)
        elif k == "pc":
            out[name] = v - m.eu.origin if isinstance(v, int) else v
        elif k == "bus":
            out[name] = v
        else:
            out[name] = v
    return out


def _off(v, t: int):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, float):
        if math.isinf(v):
            return "inf"
        v = int(v)
    d = v - t
    return max(d, -STALE)


def _sync(v, m):
    if isinstance(v, int) and not isinstance(v, bool):
        return ("fetches", v - m.queue.completed)      # target against the delivered count
    return v


def _value(machine: str, k: str, v, t: int, m):
    """Reduce one attribute value; None to skip it."""
    if k in TIME.get(machine, ()):
        return _off(v, t)
    if isinstance(v, (bool, str)) or v is None:
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return "inf" if math.isinf(v) else v
    return _MISSING


_MISSING = object()


def machine_state(m, t: int) -> dict:
    """Every state attribute of the machines at the end of clock t, reduced."""
    from .sim.arbiter import Request
    from .sim.bus import Cycle
    out = {}
    q, d, eu, bus = m.queue, m.decoder, m.eu, m.bus
    base = m.base - len(m.tail)
    for name, obj in (("bus", bus), ("queue", q), ("decoder", d), ("eu", eu),
                      ("refresh", m.refresh)):
        if obj is None:
            continue
        skip = SKIP[name]
        for k, v in vars(obj).items():
            if k in skip or k.startswith("_"):
                continue
            key = f"{name}.{k}"
            if isinstance(v, Request):
                if k in ("req", "own"):
                    if k == "own":
                        out["eu.own_is_req"] = v is eu.req
                        if v is eu.req:
                            out[key] = True
                            continue
                    _request(out, key, v, t)
                continue
            if isinstance(v, Cycle):
                out[key] = v.kind
                if k == "current":
                    busy = v.start <= t <= v.end
                    out["bus.current.pos"] = t - v.start if busy else None
                    out["bus.current.length"] = v.length if busy else None
                continue
            if name == "eu" and k == "own" and v is None:
                out[key] = None
                out["eu.own_is_req"] = False
                continue
            if k == "sync":
                out[key] = _sync(v, m)
                continue
            if name == "decoder" and k in ("ir", "modrm_addr"):
                out[key] = None if v is None else "held"
                continue
            if name == "queue" and k == "fetch_addr":
                out[key] = v - (base & ~1)
                continue
            if name == "queue" and k == "bytes":
                out["queue.bytes.len"] = len(v)
                out["queue.bytes.unusable"] = sum(1 for _, u in v if u > t)
                continue
            if name == "queue" and k == "words":
                out["queue.words.len"] = len(v)
                out["queue.words.released"] = sum(1 for _, r in v.values() if r)
                continue
            if name == "eu" and k == "pc":
                out[key] = v - eu.origin
                continue
            if name == "eu" and k == "steps":
                out["eu.steps.len"] = len(v)
                continue
            if name == "eu" and k == "queued":
                out["eu.queued.len"] = len(v)
                if v:
                    _request(out, "eu.queued0", v[0], t)
                continue
            if name == "eu" and k in ("hold_done", "pop_ref"):
                out[key] = None if v is None else "set"
                continue
            if name == "eu" and k == "port_held":
                out["eu.port_held.len"] = len(v)
                continue
            if name == "refresh" and k == "write_at":
                out[key] = None if v is None else _off(v[0], t)
                continue
            if name == "eu" and k == "stalled":
                out[key] = v
                continue
            if isinstance(v, (list, tuple, set, dict)):
                out[key + ".len"] = len(v)
                continue
            r = _value(name, k, v, t, m)
            if r is not _MISSING:
                out[key] = r
    return out


def _request(out: dict, key: str, r, t: int):
    out[key] = True
    for k, v in vars(r).items():
        name = f"{key}.{k}"
        if k == "cycles":
            out[name + ".len"] = len(v)
            out[name + ".kind"] = v[0][0] if v else None
        elif k == "issued":
            out[name + ".len"] = len(v)
        elif k == "xeu":
            out[name + ".len"] = None if v is None else len(v)
        else:
            r2 = _value("req", k, v, t, None)
            if r2 is not _MISSING:
                out[name] = r2


class Stats:
    """{variable: Counter(value)} and, per variable, the run first reaching each extreme."""

    def __init__(self):
        self.values: dict[str, Counter] = {}
        self.where: dict[str, dict] = {}     # var -> {"min": (v, run), "max": (v, run)}
        self.clocks = 0
        self.runs = 0
        self.exact = 0
        self.errors: list = []
        self.per_family: dict = {}
        self.reads: dict = {}                # family -> Counter(field: runs reading it)

    def add_clock(self, vals: dict, run_id: str):
        self.clocks += 1
        V = self.values
        for k, v in vals.items():
            c = V.get(k)
            if c is None:
                c = V[k] = Counter()
            c[v] += 1

    def finish_run(self, run_id: str):
        """Record the extremes this run reached (after its clocks were added to a fresh
        per-run Stats, merged by merge())."""
        for k, c in self.values.items():
            ints = [v for v in c if isinstance(v, int) and not isinstance(v, bool)]
            if ints:
                self.where[k] = {"min": (min(ints), run_id), "max": (max(ints), run_id)}

    def merge(self, other: "Stats"):
        for k, c in other.values.items():
            self.values.setdefault(k, Counter()).update(c)
        for k, w in other.where.items():
            mine = self.where.get(k)
            if mine is None:
                self.where[k] = dict(w)
                continue
            if w["min"][0] < mine["min"][0]:
                mine["min"] = w["min"]
            if w["max"][0] > mine["max"][0]:
                mine["max"] = w["max"]
        self.clocks += other.clocks
        self.runs += other.runs
        self.exact += other.exact
        self.errors += other.errors
        for f, n in other.per_family.items():
            a = self.per_family.setdefault(f, [0, 0, 0])
            for i in range(3):
                a[i] += n[i]
        for f, c in other.reads.items():
            self.reads.setdefault(f, Counter()).update(c)


class _Sink:
    """The clock log Machine.run appends to: reduces each row at once (nothing kept)."""

    def __init__(self, stats: Stats, run_id: str):
        self.stats, self.run_id = stats, run_id

    def append(self, vals: dict):
        self.stats.add_clock(vals, self.run_id)


def _stat_machine_class():
    from .sim.machine import Machine

    class StatMachine(Machine):
        """Machine whose clock rows carry every machine attribute, reduced."""

        def _clock_row(self, t: int) -> dict:
            row = super()._clock_row(t)
            vals = _row(t, row, self)
            vals.update(machine_state(self, t))
            return vals

    return StatMachine


_STAT_MACHINE = None


@contextmanager
def _patched():
    """machine.run_record builds machine.Machine: swap in StatMachine while simulating."""
    global _STAT_MACHINE
    from .sim import machine
    if _STAT_MACHINE is None:
        _STAT_MACHINE = _stat_machine_class()
    old = machine.Machine
    machine.Machine = _STAT_MACHINE
    try:
        yield
    finally:
        machine.Machine = old


def run_stats(rec: dict, cfg=None) -> Stats:
    """Simulate one silicon run record under cfg (default: the fitted Config) with the
    reducer as its clock log; returns its Stats (one run)."""
    from .fit import recording
    from .normalize import normalize
    from .score import score
    from .sim.config import Config
    from .sim.machine import refresh_anchor, simulate_normalized
    cfg = recording(cfg or Config.fitted())     # notes the structural fields the run reads
    s = normalize(rec)
    st = Stats()
    st.runs = 1
    fam = s.chain.family
    st.per_family[fam] = [1, 0, 0]
    sink = _Sink(st, s.run_id)
    try:
        with _patched():
            n = simulate_normalized(s.chain, cfg, s.chain_base, clock_log=sink,
                                    refresh=refresh_anchor(s))
    except Exception as e:          # the scorer counts such a run as a miss
        st.errors.append((s.run_id, f"{type(e).__name__}: {e}"))
        st.per_family[fam][2] = 1
        st.finish_run(s.run_id)
        return st
    if score(s, n).exact:
        st.exact = 1
        st.per_family[fam][1] = 1
    st.reads[fam] = Counter(set(cfg._reads))
    st.finish_run(s.run_id)
    return st


# Pool ------------------------------------------------------------------------------------

_CACHE: dict = {}


def _runs(family: str, waits: int) -> list:
    from .normalize import load_runs
    key = (family, waits)
    if key not in _CACHE:
        _CACHE.clear()               # one corpus entry at a time per worker (memory)
        try:
            _CACHE[key] = (load_runs(family) if family == "F0w"
                           else load_runs(family, (waits,)))
        except FileNotFoundError:
            _CACHE[key] = []
    return _CACHE[key]


def _task(args) -> Stats:
    family, waits, shard, nshards = args
    from .sim.config import Config
    cfg = Config.fitted()
    total = Stats()
    for rec in _runs(family, waits)[shard::nshards]:
        total.merge(run_stats(rec, cfg))
    return total


def tasks(families, shards: int = 4) -> list:
    out = []
    for f in families:
        for w in ((-1,) if f == "F0w" else (0, 1, 2)):
            out += [(f, w, i, shards) for i in range(shards)]
    return out


def collect(families, jobs: int = 8, shards: int = 4, progress=None) -> Stats:
    total = Stats()
    ts = tasks(families, shards)
    if jobs <= 1:
        for k, a in enumerate(ts):
            total.merge(_task(a))
            if progress:
                progress(k + 1, len(ts), total)
        return total
    with mp.get_context("fork").Pool(jobs, maxtasksperchild=8) as pool:
        for k, st in enumerate(pool.imap_unordered(_task, ts)):
            total.merge(st)
            if progress:
                progress(k + 1, len(ts), total)
    return total


# Summary ---------------------------------------------------------------------------------

def _machine_of(var: str) -> str:
    if var.startswith("row."):
        return "row"
    return var.split(".", 1)[0]


def _is_time(var: str) -> bool:
    parts = var.split(".")
    if var.startswith("row."):
        return parts[1] in ROW_TIME
    if parts[0] == "eu" and len(parts) >= 3 and parts[1] in ("req", "own", "queued0"):
        return parts[2] in TIME["req"]
    return parts[0] in TIME and len(parts) == 2 and parts[1] in TIME[parts[0]] or \
        var == "refresh.write_at"


def _key(v):
    return (0, v) if isinstance(v, bool) else (1, v) if isinstance(v, (int, float)) else (
        2, "") if v is None else (3, str(v))


def summarize(st: Stats) -> dict:
    out = {"runs": st.runs, "clocks": st.clocks, "exact": st.exact,
           "errors": st.errors[:50], "n_errors": len(st.errors),
           "per_family": st.per_family,
           "field_reads": {f: dict(sorted(c.items())) for f, c in sorted(st.reads.items())},
           "vars": {}}
    for var in sorted(st.values):
        c = st.values[var]
        total = sum(c.values())
        ints = Counter({v: n for v, n in c.items()
                        if isinstance(v, int) and not isinstance(v, bool)})
        other = {v: n for v, n in c.items() if v not in ints or isinstance(v, bool)}
        rec = {"machine": _machine_of(var), "kind": "clock offset" if _is_time(var) else
               "int" if ints and not other.keys() - {None} else
               "flag" if set(c) <= {True, False, None} else "enum" if not ints else "mixed",
               "rows": total, "distinct": len(c)}
        if ints:
            n = sum(ints.values())
            vs = sorted(ints)
            acc, pct = 0, {}
            marks = (0.5, 0.9, 0.99, 0.999)
            for v in vs:
                acc += ints[v]
                for p in marks:
                    if p not in pct and acc >= p * n:
                        pct[p] = v
            rec.update(min=vs[0], max=vs[-1], int_rows=n,
                       p50=pct[0.5], p90=pct[0.9], p99=pct[0.99], p999=pct[0.999],
                       stale=ints.get(-STALE, 0) if _is_time(var) else None,
                       min_run=st.where.get(var, {}).get("min", (None, None))[1],
                       max_run=st.where.get(var, {}).get("max", (None, None))[1])
            if len(vs) <= 40:
                rec["hist"] = {str(v): ints[v] for v in vs}
            else:
                # coarse histogram: 16 equal-width buckets over the range
                lo, hi = vs[0], vs[-1]
                width = max(1, math.ceil((hi - lo + 1) / 16))
                h = Counter()
                for v in vs:
                    h[lo + (v - lo) // width * width] += ints[v]
                rec["hist"] = {f"{b}..{b + width - 1}": h[b] for b in sorted(h)}
        if other:
            rec["values"] = {str(v): n for v, n in sorted(other.items(), key=lambda x: _key(x[0]))}
        out["vars"][var] = rec
    return out


def table(summary: dict) -> str:
    lines = [f"runs {summary['runs']}  clocks {summary['clocks']}  exact {summary['exact']}  "
             f"errors {summary['n_errors']}", "",
             f"{'variable':<34} {'kind':<12} {'dist':>5} {'min':>6} {'max':>6} {'p50':>5} "
             f"{'p99':>5} {'p999':>5}  values / max run"]
    machine = None
    for var, r in summary["vars"].items():
        if r["machine"] != machine:
            machine = r["machine"]
            lines.append(f"-- {machine}")
        if "min" in r:
            vals = r.get("values")
            extra = (" " + ",".join(f"{k}:{v}" for k, v in list(vals.items())[:6])) if vals else ""
            lines.append(f"{var:<34} {r['kind']:<12} {r['distinct']:>5} {r['min']:>6} "
                         f"{r['max']:>6} {r['p50']:>5} {r['p99']:>5} {r['p999']:>5}  "
                         f"{r['max_run']}{extra}")
        else:
            vals = ", ".join(f"{k}:{v}" for k, v in list(r["values"].items())[:10])
            more = " ..." if len(r["values"]) > 10 else ""
            lines.append(f"{var:<34} {r['kind']:<12} {r['distinct']:>5} {'':>6} {'':>6} "
                         f"{'':>5} {'':>5} {'':>5}  {vals}{more}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m validation.v35s.chains.statestats",
                                description=__doc__.split("\n\n")[0])
    p.add_argument("--family", nargs="+", default=None,
                   help="families (default: every modelled family)")
    p.add_argument("--jobs", type=int, default=min(8, mp.cpu_count()))
    p.add_argument("--shards", type=int, default=4, help="tasks per corpus entry")
    p.add_argument("--out", default=None, help="write the summary as JSON here")
    args = p.parse_args(argv)
    fams = args.family or [f for f in FAMILIES if f not in UNMODELLED]
    bad = [f for f in fams if f in UNMODELLED or f not in FAMILIES]
    if bad:
        raise SystemExit(f"not a modelled family: {bad}")
    t0 = time.time()

    def progress(k, n, st):
        print(f"\r{k}/{n} tasks, {st.runs} runs, {st.clocks} clocks, "
              f"{time.time() - t0:.0f} s", end="", file=sys.stderr, flush=True)

    st = collect(fams, args.jobs, args.shards, progress)
    print(file=sys.stderr)
    s = summarize(st)
    s["families"] = fams
    s["wall_s"] = round(time.time() - t0, 1)
    print(table(s))
    print(f"\nwall {s['wall_s']} s")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(s, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
