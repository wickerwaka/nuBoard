"""Fit which microcode routines hide one clock of a queue-word load.

    python -m validation.v35s.fit_hide [--entry a6-timing] [--passes 2]

A word load costs costs.word_load clocks. A routine may hide one of them:
  end_hide  - the load of the next opcode's word overlaps its last step
  mid_hide  - an operand word's load starts a clock early. Before the ModR/M
              byte is read the key is the opcode (int); after, the routine
              key ("8Bm", "F1Cr", ...).
For every A6 form measured at both placements, the odd-minus-even cost is
independent of the routine's step values, so the fit chooses, routine by
routine, the hide bits that make the model's difference equal silicon's.
Prefixed forms are left out (the prefix's own load is a separate question).
"""

from __future__ import annotations

import argparse
import copy
import itertools
from collections import defaultdict

from .corpus import load
from .fit import case_from_json, pages
from .fit_costs import span
from .model.costs import COSTS
from .model.machine import Machine
from .runner import Transaction
from .timing import build

PREFIXES = {0x26, 0x2E, 0x36, 0x3E, 0xF0, 0xF2, 0xF3, 0x64, 0x65}


class Runner:
    def __init__(self, settings):
        self.settings = settings
        self.images = {}

    def span(self, case, costs, keys=False):
        k = (case.name, case.odd)
        if k not in self.images:
            image, target, _, _ = build(case, self.settings)
            self.images[k] = (pages(image), target)
        memory, target = self.images[k]
        machine = Machine(copy.deepcopy(memory), costs=costs)
        machine.keys = {}
        machine.run(60_000)
        return span(machine.trace), machine.keys.get(target)


def opcode_of(key):
    if isinstance(key, int):
        return key
    return int(key[:-1], 16) if key[-1] in "rm" else int(key, 16)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entry", default="a6-timing")
    parser.add_argument("--passes", type=int, default=2)
    args = parser.parse_args()
    data = load(args.entry)
    runner = Runner(data["settings"])
    costs = dict(COSTS, end_hide=set(), mid_hide=set())
    forms = defaultdict(dict)
    base_cases = {}
    for run in data["runs"]:
        case = case_from_json(run["case"])
        si = span([Transaction(**t) for t in run["socket_trace"]])
        if case.name.startswith("(baseline"):
            base_cases[case.odd] = (case, si)
        elif case.group:
            code = bytes.fromhex(run["code_hex"])
            if code[run["target_offset"]] in PREFIXES:
                continue
            forms[case.group]["odd" if case.odd else "even"] = (case, si)
    forms = {k: v for k, v in forms.items() if len(v) == 2}
    _, key_of = {}, {}
    for name, places in forms.items():
        key_of[name] = runner.span(places["even"][0], costs)[1]
    by_opcode = defaultdict(list)
    for name, key in key_of.items():
        if key is not None:
            by_opcode[opcode_of(key)].append(name)

    def error(costs, names):
        base = {odd: runner.span(case, costs)[0] for odd, (case, _) in base_cases.items()}
        total = 0
        for name in names:
            (ce, se), (co, so) = forms[name]["even"], forms[name]["odd"]
            si = (so - base_cases[True][1]) - (se - base_cases[False][1])
            mo = (runner.span(co, costs)[0] - base[True]) - (runner.span(ce, costs)[0] - base[False])
            total += abs(si - mo) // 8
        return total

    for _ in range(args.passes):
        for opcode, names in sorted(by_opcode.items()):
            keys = sorted({key_of[n] for n in names}, key=str)
            options = []
            for bits in itertools.product((0, 1), repeat=2 * len(keys) + 1):
                end = {k for k, b in zip(keys, bits[:len(keys)]) if b and k != opcode}
                end |= {k for k, b in zip(keys, bits[:len(keys)]) if b and k == opcode}
                mid = {k for k, b in zip(keys, bits[len(keys):2 * len(keys)]) if b}
                if bits[-1]:
                    mid.add(opcode)
                options.append((end, mid))
            best = None
            for end, mid in options:
                trial = dict(costs, end_hide=(costs["end_hide"] - set(keys)) | end,
                             mid_hide=(costs["mid_hide"] - set(keys) - {opcode}) | mid)
                err = error(trial, names)
                if best is None or err < best[0]:
                    best = (err, trial)
            costs = best[1]
            print(f"{opcode:#06x} {keys}: error {best[0]} over {len(names)} forms", flush=True)
    fmt = lambda keys: "{" + ", ".join(sorted((f"0x{k:X}" if isinstance(k, int) else repr(k))
                                             for k in keys)) + "}"
    print(f'"end_hide": {fmt(costs["end_hide"])},')
    print(f'"mid_hide": {fmt(costs["mid_hide"])},')
    print("total error", error(costs, list(forms)))


if __name__ == "__main__":
    main()
