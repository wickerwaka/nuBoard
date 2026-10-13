"""Silicon word-load times implied by the prefetches, against the model's.

    python -m validation.v35s.load_times p2-held 'train INC|train NOP'

Under the word-register rule a slot frees when the EU loads a word, and the
bus unit fetches 2 clocks later: a fetch of word W+6 at clock t means word W
was loaded at t-2. On the NOP runway that holds exactly. Each row prints,
per word, "word:silicon/model" load clocks from the opening marker, then the
model's opcode takes.
"""

from __future__ import annotations

import sys

from .corpus import load
from .fit import case_from_json, pages
from .model.machine import Machine
from .runner import Transaction
from .timing import build, markers


def main():
    data = load(sys.argv[1])
    patterns = sys.argv[2].split("|") if len(sys.argv) > 2 else [""]
    for run in data["runs"]:
        if not any(p in run["case"]["name"] for p in patterns):
            continue
        case = case_from_json(run["case"])
        target, after = run["target_offset"], run["next_offset"]
        machine = Machine(pages(build(case, data["settings"])[0]))
        machine.loads, machine.log = [], []
        machine.run(60_000)
        origin = markers(machine.trace)[0].start

        def clock(c):
            return (machine.tick - (machine.clock - c) * 8 - origin) // 8

        trace = [Transaction(**t) for t in run["socket_trace"]]
        found = markers(trace)
        silicon = {t.address - 0x10006: (t.start - found[0].start) // 8 - 2 for t in trace
                   if found[0].start <= t.start <= found[1].start and t.kind == "mem-read"
                   and 0x10000 <= t.address < 0x10100}
        model = {a: clock(c) for c, a in machine.loads}
        lo, hi = (target & ~1) - 2, after + 2
        rows = " ".join(f"{a:x}:{silicon.get(a, '-')}/{model.get(a, '-')}" for a in range(lo, hi, 2))
        takes = " ".join(f"{pc:x}@{clock(c)}" for c, pc, _ in machine.log if lo <= pc <= hi)
        print(f"{case.name[:26]:<26} {'odd ' if case.odd else 'even'} loads {rows}")
        print(f"{'':32}takes {takes}")


if __name__ == "__main__":
    main()
