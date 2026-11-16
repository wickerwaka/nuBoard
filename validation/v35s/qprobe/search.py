"""Search a routine's shape (its length and the words of its pops, NXT and bus-idle wait)
against the silicon traces of the tests that contain it.

    python3 -m validation.v35s.qprobe.search RI ri- [--len 3 8] [--acts PPN] [--b]
"""

from __future__ import annotations

import argparse
import itertools
import sys

from . import model, read


def specs(acts, lo, hi, with_b):
    for n in range(lo, hi + 1):
        for pos in itertools.combinations_with_replacement(range(n), len(acts)):
            bs = [None] + (list(range(n)) if with_b else [])
            for b in bs:
                w = [set() for _ in range(n)]
                for a, p in zip(acts, pos):
                    if a in w[p]:
                        w[p] = w[p] | {a + "2"}
                    else:
                        w[p] = w[p] | {a}
                if b is not None:
                    w[b] = w[b] | {"B"}
                yield w


def show(w):
    return " ".join("".join(sorted(x)) or "." for x in w)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("key")
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--len", nargs=2, type=int, default=[2, 8])
    ap.add_argument("--acts", default="PPN")
    ap.add_argument("--b", action="store_true")
    ap.add_argument("--opt", nargs="+", default=[])
    ap.add_argument("--src", default="socket")
    args = ap.parse_args(argv)
    o = model.options(args.opt)
    runs = [r for _, r in read.select(read.load(args.src), args.ids)]
    res = []
    for w in specs(args.acts, args.len[0], args.len[1], args.b):
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
    for ok, s in res[:12]:
        print(f"{ok:4d} / {len(runs)}  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
