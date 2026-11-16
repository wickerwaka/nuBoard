"""Routine-shape search with free acts: the ordered acts (operand pops, then N) keep their
order; the free acts (X, D, B, F) go on any word (D not before X).

    python3 -m validation.v35s.qprobe.search2 KEY --ids lacc- --ordered PPN --free XD --len 6 9
"""

from __future__ import annotations

import argparse
import itertools
import sys

from . import model, read


def specs(ordered, free, lo, hi):
    for n in range(lo, hi + 1):
        for pos in itertools.combinations_with_replacement(range(n), len(ordered)):
            base = [set() for _ in range(n)]
            for a, p in zip(ordered, pos):
                base[p].add(a + "2" if a in base[p] else a)
            for fp in itertools.product(range(n), repeat=len(free)):
                d = dict(zip(free, fp))
                if "D" in d and "X" in d and d["D"] <= d["X"]:
                    continue
                if "D" in d and "N" in ordered and d["D"] > pos[-1]:
                    continue
                w = [set(x) for x in base]
                for a, p in d.items():
                    w[p].add(a)
                yield w


def show(w):
    return " ".join("".join(sorted(x)) or "." for x in w)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("--ids", nargs="+", required=True)
    ap.add_argument("--ordered", default="PN")
    ap.add_argument("--free", default="")
    ap.add_argument("--len", nargs=2, type=int, default=[2, 8])
    ap.add_argument("--opt", nargs="+", default=[])
    ap.add_argument("--top", type=int, default=6)
    args = ap.parse_args(argv)
    o = model.options(args.opt)
    runs = [r for _, r in read.select(read.load("socket"), args.ids)]
    res = []
    for w in specs(args.ordered, args.free, args.len[0], args.len[1]):
        o[args.key] = w
        ok = 0
        for r in runs:
            try:
                a, m = model.compare(r, o)
            except Exception:
                a, m = 0, 1
            ok += a == m
        res.append((ok, show(w)))
    res.sort(reverse=True)
    print(f"== {args.key} {args.ids} ({len(runs)} runs)")
    for ok, s in res[:args.top]:
        print(f"{ok:4d} / {len(runs)}  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
