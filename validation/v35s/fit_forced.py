"""Fit the EU's integer costs with code fetches forced to silicon's times.

    python -m validation.v35s.fit_forced START.json OUT.json [--passes 3] [--minutes M]

The fetches and refreshes follow silicon (forced_fetch.Forced), so what is
scored is the EU alone, at every wait setting at once. A run's error is the
number of data cycles inside the marker window whose gap from the previous
data cycle differs from silicon's, plus the absolute marker-window error
(capped at 10). Coordinate descent over the step values the runs spend and
the word-load values, starting from COSTS updated by START.json; a value
change reruns only the runs that spend it. Writes the fitted values to
OUT.json after each pass.
"""

from __future__ import annotations

import argparse
import json
import time
from multiprocessing import Pool

from .corpus import load
from .fit import case_from_json, pages
from .fit_window import FIXED, SETS
from .forced_fetch import ENTRIES, Forced, silicon_cycles
from .model.costs import COSTS
from .runner import Transaction
from .timing import build, markers

TUNE = ["word_load", "load_wait_extra", "load_wait_free", "preload_penalty", "prepop_end",
        "write_post_clocks", "io_recovery"]
RUNS = []


def _init():
    for entry, waits in ENTRIES.items():
        data = load(entry)
        for r in data["runs"]:
            trace = [Transaction(**t) for t in r["socket_trace"]]
            found = markers(trace)
            if len(found) < 2:
                continue
            image = pages(build(case_from_json(r["case"]), data["settings"])[0])
            RUNS.append((waits, image, silicon_cycles(trace), (found[0].start, found[1].start)))


def _run(args):
    """(error, marker-window error, steps spent) of run i under costs."""
    i, costs = args
    _, image, si, marks = RUNS[i]
    m = Forced(image, costs=costs)
    m.steps_used, m.log = set(), []
    m.setup(si)
    try:
        m.run(60_000)
    except Exception:                 # a forced fetch the EU's flow no longer matches
        return 100, None, m.steps_used
    used = m.steps_used | {("op", op) for _, _, op in m.log}
    if not m.on:
        return 100, None, used
    idx = [k for k, t in enumerate(m.eu_ticks) if t in marks]
    if len(idx) < 2 or len(m.eu_mo) <= idx[1]:
        return 100, None, used
    a, b = idx[:2]
    window = round((m.eu_ticks[b] - m.eu_ticks[a]) / 8)
    error = (m.eu_mo[b] - m.eu_mo[a]) - window
    gaps = sum(m.eu_mo[k] - m.eu_mo[k - 1] != round((m.eu_ticks[k] - m.eu_ticks[k - 1]) / 8)
               for k in range(a + 1, b + 1))
    return gaps + min(10, abs(error)), error, used


def _costs(params):
    costs = dict(COSTS, **params)
    for key in SETS:
        if isinstance(costs.get(key), list):
            costs[key] = set(costs[key])
    return costs


def _report(res):
    for waits in (0, 1, 2):
        errs = [r[1] for r, run in zip(res, RUNS) if run[0] == waits and r[1] is not None]
        if errs:
            print(f"  {waits} waits: exact {sum(e == 0 for e in errs)}/{len(errs)}, "
                  f"mean {sum(errs) / len(errs):+.2f}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("start")
    parser.add_argument("out")
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--minutes", type=float, default=0, help="cap on each pass (0: none)")
    args = parser.parse_args()
    params = json.load(open(args.start))
    _init()
    pool = Pool(initializer=_init)
    n = len(RUNS)
    res = pool.map(_run, [(i, _costs(params)) for i in range(n)], chunksize=8)
    errs = [r[0] for r in res]
    used = [r[2] for r in res]
    print("start error", sum(errs), flush=True)
    _report(res)

    def trial(p, idx):
        out = pool.map(_run, [(i, _costs(p)) for i in idx], chunksize=4)
        return sum(o[0] for o in out) - sum(errs[i] for i in idx), out

    for npass in range(args.passes):
        deadline = time.monotonic() + 60 * args.minutes if args.minutes else float("inf")
        names = sorted({u for st in used for u in st if isinstance(u, str)} - FIXED - set(TUNE)) + TUNE
        for name in names:
            base = params.get(name, COSTS.get(name))
            if not isinstance(base, int) or isinstance(base, bool) or time.monotonic() > deadline:
                continue
            spenders = [i for i in range(n) if name in used[i]]
            idx = list(range(n)) if name in TUNE or len(spenders) > n // 3 else spenders
            best = None
            for value in range(max(0, base - 3), base + 4):
                if value != base:
                    d, out = trial(dict(params, **{name: value}), idx)
                    if d < 0 and (best is None or d < best[0]):
                        best = (d, value, out)
            if best:
                params = dict(params, **{name: best[1]})
                for i, o in zip(idx, best[2]):
                    errs[i], used[i] = o[0], o[2]
                    res[i] = o
                print(f"{name} {base} -> {best[1]}: {best[0]}  total {sum(errs)}", flush=True)
        json.dump({k: sorted(v, key=str) if isinstance(v, set) else v for k, v in params.items()},
                  open(args.out, "w"))
        print(f"pass {npass} total {sum(errs)}"
              f"{' (time cap)' if time.monotonic() > deadline else ''}", flush=True)
        _report(res)


if __name__ == "__main__":
    main()
