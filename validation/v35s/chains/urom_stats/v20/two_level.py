"""Two-level storage after tail sharing and hold counts: distinct payloads (the word without
its sequencing fields and hold count). Read-only.
usage: PYTHONPATH=host/src:.:<this dir> python3 two_level.py"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import depth_stats as Dp
for label, hold, ign in (("T", False, ()), ("T + H", True, ()), ("T + H + S(wid alu regs seg)", True, ("wid", "alu", "ra", "rb", "wr", "seg"))):
    nodes, idx = Dp.build(hold, False, drop_dly=hold); c, ncls, extra = Dp.minimise(nodes, idx, ign)
    rep = {}
    for k, nd in enumerate(nodes): rep.setdefault(c[k], k)
    pay = set(tuple((a, v) for a, v in sorted(nodes[k]["f"].items()) if a not in ("seq", "cond", "tgt")) for k in rep.values())
    b = math.ceil(math.log2(len(pay)))
    w1 = b + 4 + 3 + 11
    print(f"{label:30} words {ncls + extra:5}  distinct payloads {len(pay):4} -> index {b} bits; first level {w1} bits (index + seq 4 + cond 3 + target 11, a hold count in the target's bits); "
          f"storage {(ncls + extra) * w1 / 1000:.0f} + {len(pay) * 77 / 1000:.0f} = {((ncls + extra) * w1 + len(pay) * 77) / 1000:.0f} kbit")
