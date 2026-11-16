"""Read qprobe traces: bus events in CPU clocks from M0, fetch addresses relative to the body.

    python3 -m validation.v35s.qprobe.read strips [--src socket|sim] [--id S ...] [--waits ..]
    python3 -m validation.v35s.qprobe.read cmp    [--id ...]     socket against sim

An event is (clock, kind, where): kind F a fetch (where = the word's address minus the body's
first byte), R / W a memory read / write, O an I/O write (where = the port), I an I/O read.
Clock 0 is M0's I/O cycle start (the lane's `start` tick / 8).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "build/validation/v35s/qprobe"
TPC = 8
F_READ, F_IO, F_REFRESH = 1, 2, 4


def load(src="socket", root=OUT):
    runs = {}
    for path in sorted((Path(root) / src).glob("*.json")):
        for run in json.loads(path.read_text())["runs"]:
            runs[run["chain"]["id"]] = run
    return runs


def body_addr(run):
    """Linear address of the first body byte (after the first LS)."""
    for i in run["chain"]["instrs"]:
        if i["role"] == "ls":
            return run["chain_base"] + i["offset"] + len(i["code"]) // 2
    raise ValueError


def events(run, anchor="m0", trace="socket_trace"):
    """[(clock, kind, where, length)] from the anchor on (clock 0 = the anchor's start)."""
    b = body_addr(run)
    code_lo = 0x10000
    ev = []
    for x in run[trace]:
        f = x["flags"]
        if f & F_REFRESH:
            continue
        a = x["address"]
        if f & F_IO:
            kind, where = ("I" if f & F_READ else "O"), a & 0xFFFF
        elif f & F_READ and code_lo <= a < code_lo + 0x1000:
            kind, where = "F", a - b
        else:
            kind, where = ("R" if f & F_READ else "W"), a
        ev.append((x["start"], kind, where, x["end"] - x["start"]))
    if anchor == "m0":
        k = next(i for i, e in enumerate(ev) if e[1] == "O" and e[2] == 0x21)
    else:
        raise ValueError(anchor)
    t0 = ev[k][0]
    out = []
    for t, kind, where, n in ev[k:]:
        c = (t - t0) / TPC
        if abs(c - round(c)) > 0.2:
            raise ValueError(f"{run['chain']['id']}: event at {c} clocks")
        out.append((round(c), kind, where))
    return out


def strip(ev, rel=0):
    parts = []
    for c, kind, where in ev:
        if kind == "F":
            parts.append(f"{c - rel}:{where:+d}")
        elif kind == "O":
            parts.append(f"{c - rel}:O{where:02X}")
        else:
            parts.append(f"{c - rel}:{kind}{where:X}")
    return " ".join(parts)


def m1(ev):
    return next(c for c, kind, where in ev if kind == "O" and where == 0x20)


def select(runs, ids=None, waits=None, parity=None):
    for cid, run in runs.items():
        if ids and not any(s in cid for s in ids):
            continue
        if waits is not None and run["chain"]["waits"] not in waits:
            continue
        if parity and run["chain"]["parity"] not in parity:
            continue
        yield cid, run


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("strips", "cmp"))
    ap.add_argument("--src", default="socket")
    ap.add_argument("--sim", default="sim")
    ap.add_argument("--id", nargs="+", dest="ids")
    ap.add_argument("--waits", nargs="+", type=int)
    ap.add_argument("--parity", nargs="+")
    ap.add_argument("--root", type=Path, default=OUT)
    ap.add_argument("-v", action="store_true")
    args = ap.parse_args(argv)
    runs = load(args.src, args.root)
    if args.cmd == "strips":
        for cid, run in select(runs, args.ids, args.waits, args.parity):
            print(f"{cid:<24} {strip(events(run))}")
        return 0
    sim = load(args.sim, args.root)
    n = same = same_w = 0
    rows = []
    groups = {}
    for cid, run in select(runs, args.ids, args.waits, args.parity):
        if cid not in sim:
            continue
        a, b = events(run), events(sim[cid])
        n += 1
        wa, wb = window(run, a), window(run, b)
        eq_w = wa == wb
        same_w += eq_w
        g = cid.split("-")[0][2:] + ":" + cid.split("-")[1]
        groups.setdefault(g, [0, 0, 0])
        groups[g][2] += 1
        groups[g][1] += eq_w
        if a == b:
            same += 1
            groups[g][0] += 1
            rows.append((cid, "=", ""))
            continue
        k = next((i for i, (x, y) in enumerate(zip(wa, wb)) if x != y), None)
        if k is None:
            k = min(len(wa), len(wb)) - 1
        tag = "w=" if eq_w else f"{k}/{len(wa)}"
        text = "" if eq_w else f"si {strip(wa[max(k - 1, 0):k + 3])} | rtl {strip(wb[max(k - 1, 0):k + 3])}"
        rows.append((cid, tag, text))
    for cid, tag, text in rows:
        if args.v or tag not in ("=", "w="):
            print(f"{cid:<24} {tag:<7} {text}")
    print(" ".join(f"{g}:{x}/{y}/{z}" for g, (x, y, z) in groups.items()))
    print(f"{same} / {n} identical from M0 on; {same_w} / {n} identical from the fill to M1 "
          f"(aligned at the first event after the fill)")
    return 0


def window(run, ev):
    """Events after the fill's idle gap up to M1 (the first write to port 20h, or the first
    memory write when M1 is a PUSH), clocks from the first of them."""
    m1 = next(bytes.fromhex(i["code"]) for i in run["chain"]["instrs"] if i["form"] == "M1")
    out = []
    for c, kind, where in ev:
        if c < 40:
            continue
        out.append((c, kind, where))
        if (kind == "W") if m1[0] == 0x50 else (kind == "O" and where == 0x20):
            break
    if not out:
        return out
    t0 = out[0][0]
    return [(c - t0, kind, where) for c, kind, where in out]


if __name__ == "__main__":
    sys.exit(main())
