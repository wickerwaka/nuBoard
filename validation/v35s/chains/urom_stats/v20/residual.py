"""What is left after tail sharing + hold counts (T + H): by kind of word, by class, by the
by-mode routines; and the request-word pattern. Read-only.
usage: PYTHONPATH=host/src:.:<this dir> python3 residual.py"""
import collections, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import depth_stats as Dp, class_table as CT
from validation.v35s.chains import uasm
SQ = Dp.SQ; DP = Dp.DP; R0 = Dp.R0; W0 = Dp.W0
def kind(f, hold=0):
    if any(f.get(a) for a in DP): return "acting"
    ks = tuple(k for k in ("e","f","bi","rl","ro","nb","flush","vk","susp","pfx","halt","ist") if f.get(k))
    if ks: return "waiting (" + " ".join(k + ("=x" if k == "rl" and f["rl"] == 3 else "=n" if k == "rl" else "") for k in ks) + ")"
    if "seq" in f: return "sequencing only (" + SQ[f["seq"]] + ")"
    return "empty"
for label, hold in (("T", False), ("T + H", True)):
    nodes, idx = Dp.build(hold, False, drop_dly=hold); c, ncls, extra = Dp.minimise(nodes, idx)
    seen = {}; 
    for k, nd in enumerate(nodes): seen.setdefault(c[k], []).append(k)
    kc = collections.Counter(); cc = collections.Counter(); mv = 0; memf = 0
    for cl, ks in seen.items():
        nd = nodes[ks[0]]; kc[kind(nd["f"])] += 1
        rs = [R0[nodes[k]["i"]] for k in ks]
        cc[collections.Counter(CT.rclass(r) for r in rs).most_common(1)[0][0]] += 1
        if all(CT.is_modevariant(r) for r in rs): mv += 1
        if all(CT.is_mem(r) for r in rs): memf += 1
    print(f"\n== after {label}: {ncls} distinct words")
    big = collections.Counter()
    for k, v in kc.items(): big[k.split(" (")[0]] += v
    print("  by kind:", dict(big))
    for k, v in kc.most_common(22): print(f"     {v:4}  {k}")
    print("  by class:", cc.most_common())
    print("  words used only by by-mode routines (mod=m00/m01/m10):", mv, "; only by memory-form routines:", memf)
# request word pattern on the ROM as built
E = {k: {v: n for n, v in d.items()} for k, (w, d) in uasm.ENUMS.items()}
pat = collections.Counter(); between_p = between_a = 0; npat = 0
for i, x in enumerate(W0):
    if x.fields.get("rl", 0) != 3: continue
    if x.fields.get("bus", 0): pat["post on the request word itself"] += 1; continue
    j = i + 1; s = []
    while j < len(W0) and R0[j] is R0[i] and j - i <= 6 and not W0[j].fields.get("bus", 0) and Dp.sq(W0[j]) in ("NEXT",):
        f = {k: v for k, v in W0[j].fields.items() if v}
        s.append("." if not f else "a" if any(f.get(a) for a in DP) else "w"); j += 1
    if j < len(W0) and W0[j].fields.get("bus", 0) and R0[j] is R0[i]:
        pat["".join(s) + ">" + E["v35_bus_e"][W0[j].fields["bus"]][3:]] += 1; npat += 1
        between_p += sum(1 for t in s if t in ".w"); between_a += s.count("a")
    else: pat["(no post found in line: " + "".join(s) + ")"] += 1
print("\nrequest words (rl=x):", sum(pat.values()))
print("  between the request word and the post ('.' empty, 'w' waiting, 'a' acting):")
for k, v in pat.most_common(30): print(f"     {v:4}  {k}")
print(f"  patterns with a post: {npat}; words between that only pace: {between_p}; that act: {between_a}")
