"""Per routine: ROM words, acting words, hold slots by kind, clocks spent in dly (static, all
paths summed: every word once, every dly call's clocks once). Read-only.
usage: PYTHONPATH=host/src:. python3 routine_holds.py [regex of routine names | --src file.uasm]"""
import collections, re, sys
from validation.v35s.chains import uasm
p = uasm.assemble(share=False)
sq = {v: k[3:] for k, v in uasm.ENUMS["v35_seq_e"][1].items()}
G = {"regrd": ["ra", "rb"], "regwr": ["wr", "ws"], "mv1": ["d1", "s1"], "mv2": ["d2", "s2"],
     "alu": ["alu", "ax", "ay", "wf"], "bus": ["ea", "bus", "seg"], "queue": ["pop", "rl", "ro"],
     "seq": ["seq", "cond", "tgt"], "cnt": ["cnt"], "kind": ["e", "f", "nb", "bi", "vk", "flush"],
     "rare": ["pfx", "susp", "halt", "ist"], "wid": ["wid"]}
DP = [f for g in ("regrd", "mv1", "mv2", "alu", "regwr", "bus", "cnt") for f in G[g]] + ["pop"]
dly = p.routine("dly"); d0 = dly.base
pat = re.compile(sys.argv[1]) if len(sys.argv) > 1 else re.compile(".")
tot = collections.Counter()
print(f"{'routine':14} {'words':>5} {'act':>4} {'kind':>4} {'seq':>4} {'call':>4} {'empty':>5} {'dlyck':>5} {'holds':>5} {'clocks':>6}  dly calls")
for r in p.routines:
    if r.name == "dly" or not pat.search(r.name): continue
    c = collections.Counter(); calls = []
    for w in r.words:
        f = w.fields; s = sq[f.get("seq", 0)]; t = f.get("tgt", 0)
        hold = not any(f.get(x, 0) for x in DP)
        isdly = s == "CALL" and d0 <= t < d0 + 24
        if isdly: c["dlyck"] += d0 + 24 - t; calls.append(d0 + 24 - t)
        if not hold: c["act"] += 1
        elif any(f.get(x, 0) for x in G["kind"] + G["queue"]): c["kind"] += 1
        elif isdly: c["call"] += 1
        elif any(f.get(x, 0) for x in G["seq"]): c["seq"] += 1
        else: c["empty"] += 1
    n = len(r.words); holds = n - c["act"] + c["dlyck"]
    print(f"{r.name:14} {n:5} {c['act']:4} {c['kind']:4} {c['seq']:4} {c['call']:4} {c['empty']:5} {c['dlyck']:5} {holds:5} {n + c['dlyck']:6}  {calls}")
    tot.update(c); tot["words"] += n; tot["holds"] += holds
print("total", dict(tot))
