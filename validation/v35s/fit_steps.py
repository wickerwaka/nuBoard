"""Fit EU step costs to the per-placement instruction costs of a corpus entry.

    python -m validation.v35s.fit_steps [--entry a6-timing] [--passes 2] [--range 4]

Coordinate descent: for each step name in costs.COSTS that the target
instructions or the baseline spend, try the current value plus or minus up to --range clocks
and keep the value with the smallest total |model - silicon| cost over the
forms that use it (both placements). Bus-unit parameters are not touched.
Prints the changed values as a costs.py fragment.
"""

from __future__ import annotations

import argparse
import copy
from collections import defaultdict

from .corpus import load
from .fit import case_from_json, pages
from .fit_costs import span
from .model.costs import COSTS
from .model.machine import Machine
from .runner import Transaction
from .timing import build

BUS_KEYS = {"decode_bytes", "decode_refill", "decode_ahead", "decode_rate", "prepop", "prepop_end", "preload_penalty", "queue_bytes", "ripe_delay", "fetch_sample", "idle_fetch_delay", "opcode_pop",
            "queue_words", "word_load", "fetch_data_delay", "end_hide", "mid_hide",
            "io_recovery", "write_posted", "write_post_clocks", "eu_after_read",
            "eu_after_write", "reset_first_fetch_states", "reset_first_refresh_states",
            "refresh_tick_offset", "internal_access", "ramen_write", "mul_negate",
            "div_negate_dividend", "div_negate_quotient", "shift_per_bit", "shift_nonzero"}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entry", default="a6-timing")
    parser.add_argument("--passes", type=int, default=2)
    parser.add_argument("--range", type=int, default=4)
    args = parser.parse_args()
    data = load(args.entry)
    settings = data["settings"]
    images = {}

    def run(case, costs, record=False):
        k = (case.name, case.odd)
        if k not in images:
            images[k] = pages(build(case, settings)[0])
        machine = Machine(copy.deepcopy(images[k]), costs=costs)
        if record:
            machine.steps_used = set()
        machine.run(60_000)
        return span(machine.trace), machine.steps_used

    base, forms = {}, []
    for r in data["runs"]:
        case = case_from_json(r["case"])
        si = span([Transaction(**t) for t in r["socket_trace"]])
        if case.name.startswith("(baseline"):
            base[case.odd] = (case, si)
        elif si is not None and not case.stubs:
            forms.append((case, si))
    costs = dict(COSTS)
    base_steps = set()
    for odd, (case, _) in base.items():
        base_steps |= run(case, costs, True)[1]
    users = defaultdict(list)
    for i, (case, _) in enumerate(forms):
        _, used = run(case, costs, True)
        for name in used:
            users[name].append(i)
    for name in base_steps:
        users[name] = list(range(len(forms)))

    def error(costs, idx):
        # A step the baseline spends shifts every window: it may move only
        # while the baseline windows stay exact.
        mb = {odd: run(case, costs)[0] for odd, (case, _) in base.items()}
        total = sum(1000 for odd, (_, si) in base.items() if mb[odd] != si)
        for i in idx:
            case, si = forms[i]
            mo = run(case, costs)[0]
            if mo is None:
                total += 1000
                continue
            total += abs((mo - mb[case.odd]) - (si - base[case.odd][1])) // 8
        return total

    changed = {}
    for _ in range(args.passes):
        for name in sorted(users, key=lambda n: -len(users[n])):
            if name in BUS_KEYS or name not in costs:
                continue
            idx = users[name]
            best = (error(costs, idx), costs[name])
            for delta in range(-args.range, args.range + 1):
                value = costs[name] + delta
                if delta == 0 or value < 0:
                    continue
                trial = dict(costs, **{name: value})
                err = error(trial, idx)
                if err < best[0]:
                    best = (err, value)
            if best[1] != costs[name]:
                changed[name] = best[1]
                costs[name] = best[1]
            print(f"{name:<20} {costs[name]:>4}  error {best[0]} over {len(idx)} runs", flush=True)
    print("\n# changed:")
    for name, value in sorted(changed.items()):
        print(f'    "{name}": {value},')


if __name__ == "__main__":
    main()
