"""Score the queue models side by side on the silicon corpus.

    python -m validation.v35s.compare_models [--profiles iwr consume] [--costs JSON]

Each profile (costs.PROFILES, selected with V35S_PROFILE) runs in its own
process and is scored on:
  windows   - a6-timing measurement windows: exact, length exact, cycles in place
  costs     - per-placement instruction costs exact; odd-minus-even exact
  refill    - the first fetch of the word after the target's word (A6, even
              placement): the observation that separates the two models
  prefetch  - m-prefetch-w0 scenarios exact, and rows in place
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict


def score():
    from .corpus import load
    from .fit import case_from_json, compare, fit_prefetch, run_model, window
    from .fit_costs import span
    from .runner import Transaction
    from .timing import markers

    data = load("a6-timing")
    settings = data["settings"]
    stats = defaultdict(int)
    spans = {}
    for run in data["runs"]:
        case = case_from_json(run["case"])
        silicon_trace = [Transaction(**t) for t in run["socket_trace"]]
        machine = run_model(case, settings)
        si, mo = window(silicon_trace), window(machine.trace)
        stats["runs"] += 1
        if si and mo:
            stats["exact"] += si == mo
            stats["length_exact"] += si[-1][0] == mo[-1][0]
            stats["cycles"] += len(si)
            stats["cycles_in_place"] += sum(1 for a, b in zip(si, mo) if a == b)
        spans[(case.group or case.name, case.odd)] = (span(silicon_trace), span(machine.trace))
        if not case.odd and run["target_offset"] == 0x5A:
            def refill(trace):
                found = markers(trace)
                return next(((t.start - found[0].start) // 8 for t in trace
                             if t.address == 0x10060 and t.start > found[0].start), None)
            stats["refill_runs"] += 1
            stats["refill_exact"] += refill(silicon_trace) == refill(machine.trace)
    base = {odd: spans[(name, odd)] for name, odd in spans if name.startswith("(baseline")}
    per = defaultdict(dict)
    for (name, odd), (si, mo) in spans.items():
        if name.startswith("(baseline") or None in (si, mo):
            continue
        cost = ((si - base[odd][0]) // 8, (mo - base[odd][1]) // 8)
        per[name][odd] = cost
        stats["cost_runs"] += 1
        stats["cost_exact"] += cost[0] == cost[1]
    for name, places in per.items():
        if len(places) == 2:
            stats["diff_forms"] += 1
            stats["diff_exact"] += (places[True][0] - places[False][0]) == (places[True][1] - places[False][1])
    tally = fit_prefetch("m-prefetch-w0", show=False)
    stats["prefetch_exact"] = tally.get("match", 0)
    stats["prefetch_scenarios"] = sum(tally.values())
    print(json.dumps(stats))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profiles", nargs="*", default=["iwr", "consume"])
    parser.add_argument("--costs", default="{}", help="extra V35S_COSTS overrides for every profile")
    parser.add_argument("--score", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.score:
        score()
        return
    results = {}
    for profile in args.profiles:
        env = dict(os.environ, V35S_PROFILE=profile, V35S_COSTS=args.costs)
        out = subprocess.run([sys.executable, "-m", "validation.v35s.compare_models", "--score"],
                             env=env, capture_output=True, text=True, check=True).stdout
        results[profile] = json.loads(out.strip().splitlines()[-1])
    rows = [
        ("windows exact", "exact", "runs"),
        ("window length exact", "length_exact", "runs"),
        ("cycles in place", "cycles_in_place", "cycles"),
        ("placement costs exact", "cost_exact", "cost_runs"),
        ("odd-minus-even exact", "diff_exact", "diff_forms"),
        ("refill fetch exact", "refill_exact", "refill_runs"),
        ("prefetch scenarios exact", "prefetch_exact", "prefetch_scenarios"),
    ]
    print(f"{'':<26}" + "".join(f"{p:>20}" for p in args.profiles))
    for label, num, den in rows:
        cells = []
        for profile in args.profiles:
            r = results[profile]
            n, d = r.get(num, 0), r.get(den, 0)
            cells.append(f"{n}/{d} ({100 * n / d:.0f}%)" if d else "-")
        print(f"{label:<26}" + "".join(f"{c:>20}" for c in cells))


if __name__ == "__main__":
    main()
