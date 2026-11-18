"""Tail sharing against a typed (V20-shaped) word: how many words must carry a jump after
sharing, how many of those already carry an ALU or bus payload, how many distinct targets.
Read-only.  usage: PYTHONPATH=host/src:.:<this dir> python3 jumps_after_sharing.py"""
import collections, math, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import depth_stats as Dp
SQ = Dp.SQ
def typed(f): return bool(f.get("alu") or f.get("cnt") or f.get("bus") or f.get("seg") or f.get("ea") or f.get("flush") or f.get("susp") or f.get("pfx") or f.get("halt"))
for label, hold in (("as built", None), ("T", False), ("T + H", True)):
    nodes, idx = Dp.build(bool(hold), False, drop_dly=bool(hold))
    if hold is None:
        c = list(range(len(nodes)))
    else:
        c, ncls, extra = Dp.minimise(nodes, idx)
    pos = {nd["i"]: k for k, nd in enumerate(nodes)}
    preds = collections.defaultdict(set); explicit = 0; exp_typed = 0; tg = set()
    rep = {}
    for k, nd in enumerate(nodes): rep.setdefault(c[k], k)
    for cl, k in rep.items():
        f = nodes[k]["f"]; s = SQ[f.get("seq", 0)]
        if s == "NEXT" and k + 1 < len(nodes): preds[c[k + 1]].add(cl)
        elif s == "JMP": preds[c[pos[f.get("tgt", 0)]]].add(cl)
        elif s in ("JC", "JNC", "LOOP", "CALL", "EAC", "TKI"):
            explicit += 1; exp_typed += typed(f); tg.add(c[pos[f.get("tgt", 0)]] if f.get("tgt", 0) in pos else -1)
    jumps = conflicts = 0
    for scl, ps in preds.items():
        t = sum(1 for cl in ps if typed(nodes[rep[cl]]["f"]))
        jumps += len(ps) - 1
        if len(ps) > 1: tg.add(scl)
        conflicts += max(0, t - 1)
    print(f"{label:9} words {len(rep):5}: unconditional jumps needed {jumps:4} (on words with an ALU / bus payload at least {conflicts}); conditional / call / loop words {explicit} (with ALU / bus payload {exp_typed}); distinct targets {len(tg)} -> {math.ceil(math.log2(len(tg)))} bits")
