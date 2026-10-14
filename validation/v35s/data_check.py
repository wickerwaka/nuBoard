"""Do the model's data bus cycles match silicon's, timing aside?

    python -m validation.v35s.data_check [ENTRY ...]

For every run in the window between the markers, compares the sequence of
non-fetch bus cycles (memory reads and writes outside the code page, I/O
cycles) by kind, address, data and byte enables. A byte read's data is
compared on its active lane only (silicon's trace holds only that lane),
and the model-only marker and column flags are ignored.
"""

from __future__ import annotations

import sys

from .corpus import load
from .fit import case_from_json, pages
from .model.machine import Machine
from .runner import FLAG_COL_A9, FLAG_MARKER, FLAG_UBE_N, Transaction
from .timing import build, markers

CODE_PAGE = (0x10000, 0x20000)
ENTRIES = ("a6-timing", "p2-release", "p2-held", "p2-eu", "p2-follow", "p2-stall")


def data_cycles(trace):
    found = markers(trace)
    if len(found) < 2:
        return None

    def data(t):
        if t.kind == "mem-read" and (t.flags & FLAG_UBE_N or t.address & 1):
            return (t.data >> 8) & 0xFF if t.address & 1 else t.data & 0xFF
        return t.data

    return [(t.kind, t.address, data(t), t.flags & ~(FLAG_MARKER | FLAG_COL_A9)) for t in trace
            if found[0].start <= t.start <= found[1].start and t.kind not in ("refresh", "idle")
            and not (t.kind == "mem-read" and CODE_PAGE[0] <= t.address < CODE_PAGE[1])]


def main():
    entries = sys.argv[1:] or ENTRIES
    bad_total = 0
    for entry in entries:
        data = load(entry)
        ok, bad = 0, []
        for r in data["runs"]:
            case = case_from_json(r["case"])
            machine = Machine(pages(build(case, data["settings"])[0]))
            machine.run(60_000)
            if data_cycles([Transaction(**t) for t in r["socket_trace"]]) == data_cycles(machine.trace):
                ok += 1
            else:
                bad.append(f"{case.name} ({'odd' if case.odd else 'even'})")
        bad_total += len(bad)
        print(f"{entry}: {ok}/{len(data['runs'])} runs with identical data cycles")
        for name in bad:
            print("   ", name)
    sys.exit(1 if bad_total else 0)


if __name__ == "__main__":
    main()
