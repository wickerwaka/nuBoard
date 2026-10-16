"""Fit integer costs to whole-window exactness over every timing corpus.

    python -m validation.v35s.fit_window START.json OUT.json [--passes 3] [--toggle-set NAME]

Coordinate descent over the EU step values and a few bus-unit values,
starting from COSTS updated by START.json, against a6-timing and the
0-wait release, held, eu, follow, stall, regform, imm and depth corpora at
once (with --waited, also the 1- and 2-wait held, eu, follow, imm and
depth corpora). A run's error is the number of window
transactions that differ from silicon's (time, kind, address or data), plus
3 if the window length differs, plus --exact-weight unless the whole window
matches (so the fit cannot trade exact runs for fewer stray mismatches). Unlike fit_steps.py, which fits per-form
costs, this also scores where the fetches fall, so it can refit a model whose
structure moves them. A value change reruns only the runs that spend it.
--toggle-set NAME also toggles each executed opcode in and out of the cost
set NAME (decode_skip, decode_simple, prepop, ...); --keep NAME:OP pins an
opcode's membership as the start file has it. --minutes caps each pass.
--fetch-weight W adds W per code fetch whose gap from the previous fetch
(clocks and address) differs from silicon's inside the marker window, so a
fit cannot buy window error by moving the fetches off silicon's rhythm.
Writes the fitted values to OUT.json after each pass.
"""

from __future__ import annotations

import argparse
import copy
import json
import time
from multiprocessing import Pool

from .corpus import load
from .fit import case_from_json, pages, window
from .model.costs import COSTS
from .model.machine import Machine
from .runner import Transaction
from .timing import build, markers

ENTRIES = ("a6-timing", "p2-release", "p2-held", "p2-eu", "p2-follow", "p2-stall", "p2-regform", "p2-imm", "p2-depth", "p2-setup")
WAITED = ("p2-held-w1", "p2-eu-w1", "p2-follow-w1", "p2-imm-w1", "p2-depth-w1", "p2-setup-w1",
          "p2-held-w2", "p2-eu-w2", "p2-follow-w2", "p2-imm-w2", "p2-depth-w2", "p2-setup-w2")
TUNE_BUS = ["word_load", "preload_penalty", "prepop_end", "io_recovery", "write_post_clocks",
            "decode_cap", "decode_finish_cap", "load_wait_extra", "load_wait_free", "queue_words_waited", "io_recovery_waited"]
FIXED = {"queue_words", "reset_first_fetch_states", "reset_first_refresh_states", "refresh_tick_offset",
         "internal_access", "ramen_write", "write_posted", "fetch_data_delay", "queue_bytes", "ripe_delay",
         "fetch_sample", "idle_fetch_delay", "opcode_pop", "fetch_latch", "fetch_request_delay"}
SETS = ("prepop", "end_hide", "mid_hide", "decode_skip", "decode_simple", "decode_io")
RUNS = []
GROUPS = []                            # the wait setting of each run
EXACT_WEIGHT = 0
FETCH_WEIGHT = 0


def _fetch_gaps(trace, hi):
    """(clocks since the previous fetch, offset) of each code fetch from 58h
    to hi inside the marker window."""
    found = markers(trace)
    if len(found) < 2:
        return None
    rows = [(t.start // 8, t.address - 0x10000) for t in trace
            if found[0].start <= t.start <= found[1].start and t.kind == "mem-read"
            and 0x58 <= t.address - 0x10000 <= hi]
    return [(b[0] - a[0], b[1]) for a, b in zip(rows, rows[1:])]


def _init(exact_weight=0, waited=False, fetch_weight=0):
    global EXACT_WEIGHT, FETCH_WEIGHT
    EXACT_WEIGHT, FETCH_WEIGHT = exact_weight, fetch_weight
    for entry in ENTRIES + (WAITED if waited else ()):
        data = load(entry)
        for r in data["runs"]:
            case = case_from_json(r["case"])
            trace = [Transaction(**t) for t in r["socket_trace"]]
            hi = r.get("next_offset", 0x90) + 8
            RUNS.append((pages(build(case, data["settings"])[0]), window(trace),
                         _fetch_gaps(trace, hi) if fetch_weight else None, hi))
            GROUPS.append(int(entry[-1]) if entry in WAITED else 0)


def _error(si, mo):
    if not si or not mo:
        return 100
    err = 3 * (si[-1][0] != mo[-1][0]) + abs(len(si) - len(mo))
    return err + sum(a != b for a, b in zip(si, mo)) + EXACT_WEIGHT * (si != mo)


def _run(args):
    i, costs = args
    image, si, si_gaps, hi = RUNS[i]
    m = Machine(copy.deepcopy(image), costs=costs)
    m.steps_used, m.log = set(), []
    m.run(60_000)
    err = _error(si, window(m.trace))
    if FETCH_WEIGHT and si_gaps is not None:
        mo_gaps = _fetch_gaps(m.trace, hi) or []
        err += FETCH_WEIGHT * (sum(a != b for a, b in zip(si_gaps, mo_gaps))
                               + abs(len(si_gaps) - len(mo_gaps)))
    return err, m.steps_used | {("op", op) for _, _, op in m.log}


def _costs(params):
    costs = dict(COSTS, **params)
    for key in SETS:
        if isinstance(costs.get(key), list):
            costs[key] = set(costs[key])
    return costs


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("start")
    parser.add_argument("out")
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--toggle-set", action="append", default=[])
    parser.add_argument("--keep", action="append", default=[], help="NAME:OP, e.g. decode_simple:0xB1")
    parser.add_argument("--exact-weight", type=int, default=0)
    parser.add_argument("--names", help="tune only these values (comma-separated)")
    parser.add_argument("--bus-only", action="store_true", help="tune only the bus-unit values")
    parser.add_argument("--waited", action="store_true", help="also fit the 1- and 2-wait corpora")
    parser.add_argument("--minutes", type=float, default=0, help="cap on each pass (0: none)")
    parser.add_argument("--fetch-weight", type=int, default=0,
                        help="error per code fetch gap that differs from silicon's")
    args = parser.parse_args()
    params = json.load(open(args.start))
    keep = {(k, int(v, 0)) for k, v in (a.split(":") for a in args.keep)}
    _init(args.exact_weight, args.waited, args.fetch_weight)
    pool = Pool(initializer=_init, initargs=(args.exact_weight, args.waited, args.fetch_weight))
    n = len(RUNS)
    res = pool.map(_run, [(i, _costs(params)) for i in range(n)], chunksize=8)
    errs = [r[0] for r in res]
    used = [r[1] for r in res]
    def exact():
        return " / ".join(str(sum(e == 0 for e, g in zip(errs, GROUPS) if g == w))
                          for w in sorted(set(GROUPS)))

    print("start error", sum(errs), "exact", exact(), flush=True)

    def trial(p, idx):
        out = pool.map(_run, [(i, _costs(p)) for i in idx], chunksize=4)
        return sum(o[0] for o in out) - sum(errs[i] for i in idx), out

    def accept(idx, out):
        for i, o in zip(idx, out):
            errs[i], used[i] = o

    for npass in range(args.passes):
        deadline = time.monotonic() + 60 * args.minutes if args.minutes else float("inf")
        common = {u for u in set().union(*used) if isinstance(u, str)
                  and sum(u in st for st in used) > n // 3}
        for set_name in args.toggle_set:
            for op in sorted({u[1] for st in used for u in st if isinstance(u, tuple)}):
                if (set_name, op) in keep or time.monotonic() > deadline:
                    continue
                idx = [i for i in range(n) if ("op", op) in used[i]]
                current = set(params.get(set_name, COSTS[set_name]))
                p = dict(params, **{set_name: sorted(current ^ {op}, key=str)})
                # A toggle may need a step of the same runs to move with it.
                steps = sorted({u for i in idx for u in used[i] if isinstance(u, str)} - common - FIXED)
                trials = [p] + [dict(p, **{s: params.get(s, COSTS[s]) + k}) for s in steps
                                for k in (-2, -1, 1, 2)
                                if isinstance(COSTS.get(s), int) and params.get(s, COSTS[s]) + k >= 0]
                best = None
                for t in trials:
                    d, out = trial(t, idx)
                    if d < 0 and (best is None or d < best[0]):
                        best = (d, t, out)
                if best:
                    params = best[1]
                    accept(idx, best[2])
                    moved = {k: v for k, v in params.items() if k in steps}
                    print(f"{set_name} {op} {'on' if op not in current else 'off'}: {best[0]}  {moved}  "
                          f"total {sum(errs)}", flush=True)
        names = (args.names.split(",") if args.names else TUNE_BUS if args.bus_only else
                 sorted({u for st in used for u in st if isinstance(u, str)} - FIXED) + TUNE_BUS)
        for name in names:
            base = params.get(name, COSTS.get(name))
            if base is None and name == "io_recovery_waited":
                base = params.get("io_recovery", COSTS["io_recovery"])
            if not isinstance(base, int) or isinstance(base, bool) or time.monotonic() > deadline:
                continue
            spenders = [i for i in range(n) if name in used[i]]
            idx = list(range(n)) if name in TUNE_BUS or len(spenders) > n // 3 else spenders
            best = None
            for value in range(max(0, base - 3), base + 4):
                if value != base:
                    d, out = trial(dict(params, **{name: value}), idx)
                    if d < 0 and (best is None or d < best[0]):
                        best = (d, value, out)
            if best:
                params = dict(params, **{name: best[1]})
                accept(idx, best[2])
                print(f"{name} {base} -> {best[1]}: {best[0]}  total {sum(errs)}", flush=True)
        json.dump({k: sorted(v, key=str) if isinstance(v, set) else v for k, v in params.items()},
                  open(args.out, "w"))
        print(f"pass {npass} total {sum(errs)} exact {exact()}"
              f"{' (time cap)' if time.monotonic() > deadline else ''}", flush=True)


if __name__ == "__main__":
    main()
