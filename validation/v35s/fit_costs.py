"""Per-placement instruction costs: the model against silicon.

    python -m validation.v35s.fit_costs [--entry a6-timing] [--case SUBSTRING ...] [--all]

For each corpus run the model's window (marker to marker) minus its empty
window at the same placement is the model's cost, exactly as timing.analyse
computes silicon's. Prints the forms whose even or odd cost differs, then a
tally. This scores the EU and queue model independently of where in the
window the cycles fall, which fit.py checks.
"""

from __future__ import annotations

import argparse
from collections import Counter

from .corpus import load
from .fit import case_from_json, run_model
from .runner import Transaction
from .timing import markers


def span(trace):
    found = markers(trace)
    return None if len(found) < 2 else found[1].start - found[0].start


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entry", default="a6-timing")
    parser.add_argument("--case", nargs="*")
    parser.add_argument("--all", action="store_true", help="print matching forms too")
    args = parser.parse_args()
    data = load(args.entry)
    settings = dict(data.get("settings") or {"prc": 0x4C, "wtc": 0, "rfm": 0xEC})
    tpc = data.get("ticks_per_clock", 8)
    base_model, base_si = {}, {}
    rows = {}
    for run in data["runs"]:
        case = case_from_json(run["case"])
        is_base = case.name.startswith("(baseline")
        if not is_base and args.case and not any(s.lower() in case.name.lower() for s in args.case):
            continue
        si = span([Transaction(**t) for t in run["socket_trace"]])
        try:
            mo = span(run_model(case, settings).trace)
        except Exception as exc:
            mo = None
        if is_base:
            base_model[case.odd], base_si[case.odd] = mo, si
            continue
        key = case.group or case.name
        rows.setdefault(key, {})["odd" if case.odd and case.group else "even"] = (si, mo)
    tally = Counter()
    for key, places in rows.items():
        cells, bad = [], False
        for place in ("even", "odd"):
            if place not in places:
                continue
            si, mo = places[place]
            odd = place == "odd"
            s = None if si is None or base_si.get(odd) is None else (si - base_si[odd]) / tpc
            m = None if mo is None or base_model.get(odd) is None else (mo - base_model[odd]) / tpc
            delta = None if s is None or m is None else m - s
            tally["-" if delta is None else f"{delta:+g}"] += 1
            bad |= delta != 0
            cells.append(f"{place} si {s if s is not None else '-':>5} mo {m if m is not None else '-':>5}")
        if bad or args.all:
            print(f"{key[:48]:<48} " + "   ".join(cells))
    print("\nmodel - silicon cost per placement: "
          + " ".join(f"{k}:{v}" for k, v in sorted(tally.items(), key=lambda kv: kv[0])))


if __name__ == "__main__":
    main()
