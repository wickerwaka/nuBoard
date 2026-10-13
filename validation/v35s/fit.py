"""Run the Python cycle model on corpus cases and compare with silicon.

    python -m validation.v35s.fit [--entry a6-timing] [--case SUBSTRING ...] [--show N]

For each run in a corpus entry made by timing.py, the case's image is
rebuilt, the model runs it from reset, and the two traces are compared over
the measurement window (first marker to second marker), relative to the
first marker: every bus cycle's kind, address, data and start tick. A run
matches when the windows are identical. The report lists the mismatches
with the first differing cycle, and a tally.
"""

from __future__ import annotations

import argparse
from collections import Counter

from .corpus import load
from .model.machine import Machine
from .runner import FLAG_IO, FLAG_READ, FLAG_REFRESH, FLAG_STROBE, Transaction
from .timing import Case, build, markers

KEY_FLAGS = FLAG_IO | FLAG_READ | FLAG_REFRESH | FLAG_STROBE


def pages(image):
    memory = {}
    for base, data in image.items():
        for offset, value in enumerate(data):
            address = base + offset
            page = memory.setdefault(address >> 12, bytearray(4096))
            page[address & 0xFFF] = value
    return memory


def case_from_json(record: dict) -> Case:
    """A Case from a corpus run; JSON turned the byte-address keys of ram into strings."""
    case = Case(**record)
    case.ram = {(int(k) if isinstance(k, str) and k.isdigit() else k): v
                for k, v in case.ram.items()}
    return case


def run_model(case: Case, settings: dict, x_half=2, max_clocks=60_000):
    image, target_offset, next_offset, code = build(case, settings)
    machine = Machine(pages(image), x_half=x_half)
    machine.run(max_clocks)
    return machine


def window(trace):
    found = markers(trace)
    if len(found) < 2:
        return None
    origin = found[0].start
    return [(t.start - origin, t.flags & KEY_FLAGS,
             None if t.flags & FLAG_REFRESH else t.address,
             None if t.flags & FLAG_REFRESH else t.data)
            for t in trace if found[0].start <= t.start <= found[1].start]


def describe(row, tpc):
    if row is None:
        return "-"
    start, flags, address, data = row
    kind = Transaction(0, 0, flags, 0, 0, 0).kind
    where = "" if address is None else f" {address:05x}:{data:04x}"
    return f"{start / tpc:g} {kind}{where}"


def compare(silicon, model):
    if silicon is None or model is None:
        return "no window", None
    for i, (a, b) in enumerate(zip(silicon, model)):
        if a != b:
            return "differs", i
    if len(silicon) != len(model):
        return "length", min(len(silicon), len(model))
    return "match", None


def prefetch_rows(case: Case, trace, target_offset):
    """The rows prefetch.py reports: cycles between the markers, in clocks
    from the read of the jump's target word."""
    from .prefetch import describe as describe_rows
    found = markers(trace)
    if len(found) != 2:
        return None
    inside = [t for t in trace if found[0].start <= t.start <= found[1].start]
    first = next((t for t in inside if t.flags & FLAG_READ and not t.flags & FLAG_IO
                  and t.address - 0x10000 >= target_offset + 2), inside[0])
    return [(r["clock"], r["kind"], r["address"]) for r in describe_rows(inside, first.start, 0x10000)]


def fit_prefetch(entry: str, names=None, show=True):
    """Compare the prefetch scenarios of a prefetch.py corpus entry."""
    from .prefetch import SCENARIOS
    data = load(entry)
    settings = dict(data.get("settings") or {"prc": 0x4C, "wtc": 0, "rfm": 0xEC})
    tally = Counter()
    for name, recorded in data["scenarios"].items():
        if names and name not in names:
            continue
        body, odd = SCENARIOS[name]
        case = Case(name=name, target=body, odd=odd,
                    regs={"BW": 0x0800, "IX": 0x0801, "CW": 5, "AW": 7, "DW": 0x1234})
        image, target_offset, _, _ = build(case, settings)
        machine = Machine(pages(image))
        machine.run(60_000)
        model = prefetch_rows(case, machine.trace, target_offset)
        silicon = [(r["clock"], r["kind"], r["address"]) for r in recorded["socket"]]
        verdict, index = compare(silicon, model)
        tally[verdict] += 1
        if show and verdict != "match":
            print(f"== {name}: {verdict}")
            lo = max(0, (index or 0) - 2)
            for i in range(lo, (index or 0) + 4):
                a = silicon[i] if i < len(silicon) else None
                b = model[i] if model and i < len(model) else None
                print(f"   {'  ' if a == b else '!!'} si {a!s:<28} model {b}")
    return tally


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entry", default="a6-timing")
    parser.add_argument("--case", nargs="*")
    parser.add_argument("--show", type=int, default=20, help="mismatches to print in detail")
    parser.add_argument("--context", type=int, default=3)
    parser.add_argument("--prefetch", help="compare a prefetch.py corpus entry instead")
    args = parser.parse_args()
    if args.prefetch:
        tally = fit_prefetch(args.prefetch, args.case)
        print("\n" + ", ".join(f"{k} {v}" for k, v in tally.most_common()))
        return
    data = load(args.entry)
    settings = dict(data.get("settings") or {"prc": 0x4C, "wtc": 0, "rfm": 0xEC})
    tpc = data.get("ticks_per_clock", 8)
    tally = Counter()
    deltas = Counter()
    cycles = [0, 0]
    shown = 0
    for run in data["runs"]:
        case = case_from_json(run["case"])
        if args.case and not any(s.lower() in case.name.lower() for s in args.case):
            continue
        silicon = window([Transaction(**t) for t in run["socket_trace"]])
        try:
            machine = run_model(case, settings)
            model = window(machine.trace)
            error = None
        except Exception as exc:          # a model gap, reported per case
            model, error = None, f"{type(exc).__name__}: {exc}"
        verdict, index = compare(silicon, model)
        if error:
            verdict = "error"
        tally[verdict] += 1
        if silicon and model:
            deltas[(model[-1][0] - silicon[-1][0]) // tpc] += 1
            cycles[0] += sum(1 for a, b in zip(silicon, model) if a == b)
            cycles[1] += len(silicon)
        if verdict != "match" and shown < args.show:
            shown += 1
            place = "odd" if case.odd else "even"
            print(f"== {case.name} ({place}): {verdict}" + (f" {error}" if error else ""))
            if index is not None:
                lo = max(0, index - args.context)
                for i in range(lo, index + args.context + 1):
                    a = silicon[i] if silicon and i < len(silicon) else None
                    b = model[i] if model and i < len(model) else None
                    mark = "  " if a == b else "!!"
                    print(f"   {mark} {i:3} si {describe(a, tpc):<34} model {describe(b, tpc)}")
            elif silicon is not None and model is not None:
                pass
    print("\n" + ", ".join(f"{k} {v}" for k, v in tally.most_common()))
    if cycles[1]:
        exact = deltas.get(0, 0)
        print(f"window length exact in {exact} of {sum(deltas.values())} runs; "
              f"cycles matching in place {cycles[0]} of {cycles[1]} "
              f"({100 * cycles[0] / cycles[1]:.1f}%)")
        print("model - silicon window (clocks): "
              + " ".join(f"{k:+d}:{v}" for k, v in sorted(deltas.items())))


if __name__ == "__main__":
    main()
