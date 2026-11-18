"""Width of a typed word on our ROM: a tag selects one of N layouts; a layout is a set of field
groups; a word fits a layout that holds all the groups it uses. Greedy choice of layouts.
Measured on the ROM after tail sharing and hold counts (T + H), calls into the shared delay
being a hold count (group `hold`). Read-only.
usage: PYTHONPATH=host/src:.:<this dir> python3 width_stats.py"""
import collections, math, sys, os, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import depth_stats as Dp
from validation.v35s.chains import uasm
F = uasm.FIELDS; GWF = {n: w for n, t, w in F}
G = {"regrd": ["ra", "rb"], "regwr": ["wr", "ws"], "mv1": ["d1", "s1"], "mv2": ["d2", "s2"],
     "alu": ["alu", "ax", "ay", "wf"], "bus": ["ea", "bus", "seg"], "queue": ["pop", "rl", "ro"],
     "seq": ["seq", "cond", "tgt"], "cnt": ["cnt"], "kind": ["e", "f", "nb", "bi", "vk", "flush", "nb_last"],
     "rare": ["pfx", "susp", "halt", "ist"], "wid": ["wid"]}
nodes, idx = Dp.build(True, False, drop_dly=True); c, ncls, extra = Dp.minimise(nodes, idx)
rep = {}
for k, nd in enumerate(nodes): rep.setdefault(c[k], k)
# every word after sharing: its own fields, plus a jump where sharing needs one (worst case: all
# but one predecessor of a shared word jump) -- taken from jumps_after_sharing's count, here the
# words are measured as they are and the forced jumps reported apart
# the jumps tail sharing forces: of the words that run on into a shared word, one falls through
# (the widest) and the others carry a jump (FORCED=0 leaves them out)
SQn = Dp.SQ; pos = {nd["i"]: k for k, nd in enumerate(nodes)}; preds = collections.defaultdict(list)
for cl, k in rep.items():
    f = nodes[k]["f"]; s_ = SQn[f.get("seq", 0)]
    if s_ == "NEXT" and k + 1 < len(nodes): preds[c[k + 1]].append(k)
forced = 0
if os.environ.get("FORCED", "1") == "1":
    for scl, ks in preds.items():
        ks = sorted(ks, key=lambda k: -len(nodes[k]["f"]))
        for k in ks[1:]: nodes[k]["f"]["seq"] = 1; forced += 1
print("jumps forced by tail sharing, added to the words:", forced)
Wd = [nodes[k] for k in rep.values()]; n = len(Wd)
def groups(nd):
    u = set(g for g, fs in G.items() if any(nd["f"].get(f, 0) for f in fs))
    if nd["hold"]: u.add("hold")
    return frozenset(u)
# dictionary sizes per group on this ROM
dic = {}
for g, fs in G.items():
    vals = set(tuple(nd["f"].get(f, 0) for f in fs) for nd in Wd)
    dic[g] = max(1, math.ceil(math.log2(len(vals)))) if len(vals) > 1 else 0
hv = set(nd["hold"] for nd in Wd); dic["hold"] = math.ceil(math.log2(len(hv)))
if os.environ.get("RAWSEQ"): dic["seq"] = 18      # the jump target kept as an address (no table on the next-address path)
plain = {g: sum(GWF.get(f, 1) for f in fs) for g, fs in G.items()}; plain["hold"] = 5
plain["seq"] = 4 + 3 + 11
print("words", n, " group widths as fields:", plain); print(" as indices into per-group tables:", dic, " (hold values:", len(hv), ")")
U = collections.Counter(groups(nd) for nd in Wd)
for name, gw in (("fields as they are", plain), ("per-group tables", dic)):
    bits = sorted(sum(gw[g] for g in u) for u in U.elements())
    print(f"\n[{name}] bits of the groups a word uses: median {bits[n//2]}, p90 {bits[n*9//10]}, p99 {bits[n*99//100]}, max {bits[-1]}")
    for lim in (24, 26, 29, 32, 36, 37, 40): print(f"   words over {lim} bits: {sum(1 for b in bits if b > lim)}")
    for tagbits, pay in ((3, 29), (3, 33), (3, 37), (4, 28), (4, 36)):
        nl = 1 << tagbits
        # greedy: candidate layouts = unions of the used combinations that fit the payload
        cands = set(u for u in U if sum(gw[g] for g in u) <= pay)
        grown = set(cands)
        for a, b in itertools.combinations(sorted(cands, key=lambda u: -U[u])[:60], 2):
            u = a | b
            if sum(gw[g] for g in u) <= pay: grown.add(u)
        left = dict(U); chosen = []
        for _ in range(nl):
            best = max(grown, key=lambda L: sum(v for u, v in left.items() if u <= L), default=None)
            if best is None: break
            got = sum(v for u, v in left.items() if u <= best)
            if not got: break
            chosen.append((best, got)); left = {u: v for u, v in left.items() if not u <= best}
        miss = sum(left.values())
        print(f"   tag {tagbits} + payload {pay} = {tagbits + pay} bits, {nl} layouts: {miss} words fit none ({miss * 100 / n:.1f} %)")
        if (tagbits, pay) in ((3, 29), (3, 37)):
            for L, got in chosen: print(f"        {got:5}  {' '.join(sorted(L))}  ({sum(gw[g] for g in L)} bits)")
