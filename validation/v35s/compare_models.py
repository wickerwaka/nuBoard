"""Score the queue models side by side on the silicon corpus.

    python -m validation.v35s.compare_models [--profiles iwr consume] [--costs JSON]

Each profile (costs.PROFILES, selected with V35S_PROFILE) runs in its own
process and is scored on:
  windows   - a6-timing measurement windows: exact, length exact, cycles in place
  costs     - per-placement instruction costs exact; odd-minus-even exact
  refill    - the first fetch of the word after the target's word (A6, even
              placement): the observation that separates the two models
  probes    - p2-release whole windows; p2-release and p2-held prefetch lists
              (word 58h to past the target, aligned on the 58h fetch) exact
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
            # Aligned on the runway fetch of word 10058h, so the opening
            # marker's phase does not count: the target and tail only.
            def aligned(rows):
                start = next((r[0] for r in rows if r[2] == 0x10058), None)
                return None if start is None else [(r[0] - start,) + r[1:] for r in rows if r[0] >= start]
            sa, ma = aligned(si), aligned(mo)
            if sa and ma:
                stats["aligned"] += len(sa)
                stats["aligned_in_place"] += sum(1 for a, b in zip(sa, ma) if a == b)
                stats["aligned_exact"] += sa == ma
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
    release = load("p2-release")
    for run in release["runs"]:
        case = case_from_json(run["case"])
        si = window([Transaction(**t) for t in run["socket_trace"]])
        mo = window(run_model(case, release["settings"]).trace)
        stats["release_runs"] += 1
        if si and mo:
            start = lambda rows: next((r[0] for r in rows if r[2] == 0x10058), 0)
            sa = [(r[0] - start(si),) + r[1:] for r in si if r[0] >= start(si)]
            ma = [(r[0] - start(mo),) + r[1:] for r in mo if r[0] >= start(mo)]
            stats["release_exact"] += sa == ma
            stats["release_cycles"] += len(sa)
            stats["release_in_place"] += sum(1 for a, b in zip(sa, ma) if a == b)
    # Probe fetch lists: the prefetches from word 58h to just past the
    # target, aligned on the 58h fetch, exact.
    def fetch_list(trace, hi):
        found = markers(trace)
        rows = [(t.start // 8, t.address - 0x10000) for t in trace
                if found[0].start <= t.start <= found[1].start and t.kind == "mem-read"
                and 0x58 <= t.address - 0x10000 <= hi]
        return [(c - rows[0][0], a) for c, a in rows] if rows else None
    for entry, key in (("p2-release", "release_fetch"), ("p2-held", "held_fetch")):
        probe = load(entry)
        for run in probe["runs"]:
            hi = run["next_offset"] + 8
            si = fetch_list([Transaction(**t) for t in run["socket_trace"]], hi)
            mo = fetch_list(run_model(case_from_json(run["case"]), probe["settings"]).trace, hi)
            stats[key + "_runs"] += 1
            stats[key + "_exact"] += si == mo
    tally = fit_prefetch("m-prefetch-w0", show=False)
    stats["prefetch_exact"] = tally.get("match", 0)
    stats["prefetch_scenarios"] = sum(tally.values())
    print(json.dumps(stats))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profiles", nargs="*", default=["iwr", "consume"])
    parser.add_argument("--costs", default="{}", help="extra V35S_COSTS overrides for every profile")
    parser.add_argument("--variant", nargs="*", default=[],
                        help="NAME=costs.json: score the iwr profile with these overrides as NAME")
    parser.add_argument("--score", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.score:
        score()
        return
    results = {}
    runs = [(p, p, args.costs) for p in args.profiles]
    for spec in args.variant:
        name, path = spec.split("=", 1)
        with open(path) as f:
            runs.append((name, "iwr", f.read()))
    args.profiles = [name for name, _, _ in runs]
    for name, profile, costs in runs:
        env = dict(os.environ, V35S_PROFILE=profile, V35S_COSTS=costs)
        out = subprocess.run([sys.executable, "-m", "validation.v35s.compare_models", "--score"],
                             env=env, capture_output=True, text=True, check=True).stdout
        results[name] = json.loads(out.strip().splitlines()[-1])
    rows = [
        ("windows exact", "exact", "runs"),
        ("window length exact", "length_exact", "runs"),
        ("cycles in place", "cycles_in_place", "cycles"),
        ("aligned windows exact", "aligned_exact", "runs"),
        ("aligned cycles in place", "aligned_in_place", "aligned"),
        ("placement costs exact", "cost_exact", "cost_runs"),
        ("odd-minus-even exact", "diff_exact", "diff_forms"),
        ("refill fetch exact", "refill_exact", "refill_runs"),
        ("release probe exact", "release_exact", "release_runs"),
        ("release cycles in place", "release_in_place", "release_cycles"),
        ("release fetch lists exact", "release_fetch_exact", "release_fetch_runs"),
        ("held fetch lists exact", "held_fetch_exact", "held_fetch_runs"),
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
