"""Set timing runs side by side, by case name.

    python -m validation.v35s.timing_compare BASE.json OTHER.json [OTHER2.json ...] [--all]

Each file is the output of validation.v35s.timing. Prints the socket-lane
cost of every case in each file, the difference from BASE, and a tally of
differences per file. Without --all only cases whose cost differs are listed.
Cases that dumped values (OUT 22h / the trap port) also show their I/O.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load(path: Path):
    data = json.loads(path.read_text())
    rows = {row["name"]: row for row in data["summary"]}
    io = {}
    for run in data["runs"]:
        dumps = run.get("socket_io")
        if dumps:
            io.setdefault(run["case"]["group"] or run["case"]["name"], dumps)
    return data.get("settings"), rows, io


def show(value):
    return "-" if value is None else f"{value:g}"


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    loaded = [load(path) for path in args.files]
    base = loaded[0][1]
    tallies = [Counter() for _ in loaded[1:]]
    print("settings: " + " | ".join(f"{p.stem} {s}" for p, (s, _, _) in zip(args.files, loaded)))
    print(f"{'case':<46} " + " ".join(f"{p.stem[:12]:>12}" for p in args.files))
    for name, row in base.items():
        values = [entry[1].get(name, {}).get("socket") for entry in loaded]
        deltas = [None if v is None or values[0] is None else v - values[0] for v in values[1:]]
        for tally, delta in zip(tallies, deltas):
            tally["-" if delta is None else f"{delta:+g}"] += 1
        io = [entry[2].get(name) for entry in loaded]
        differs = any(d not in (None, 0) for d in deltas) or len({json.dumps(i) for i in io}) > 1
        if args.all or differs or len(loaded) == 1:
            cells = [show(values[0])] + [f"{show(v)} ({'-' if d is None else f'{d:+g}'})"
                                         for v, d in zip(values[1:], deltas)]
            line = f"{name[:46]:<46} " + " ".join(f"{c:>12}" for c in cells)
            if any(io):
                line += "  io " + " | ".join(
                    " ".join(f"{a:x}:{d:04x}" for a, d in (i or [])) for i in io)
            print(line)
    for path, tally in zip(args.files[1:], tallies):
        print(f"\n{path.stem} - {args.files[0].stem}: "
              + ", ".join(f"{k} x{v}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
