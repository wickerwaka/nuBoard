"""df25.py A.jsonl B.jsonl: corpus model rows gained / lost from A to B (by family prefix), totals."""
import json, sys, collections, re
a = {json.loads(l)["run"]: json.loads(l)["exact"] for l in open(sys.argv[1])}
b = {json.loads(l)["run"]: json.loads(l)["exact"] for l in open(sys.argv[2])}
g = [r for r in b if b[r] and not a.get(r)]; l = [r for r in b if a.get(r) and not b[r]]
print("exact", sum(a.values()), "->", sum(b.values()), "gained", len(g), "lost", len(l))
for nm, rs in (("gained", g), ("lost", l)):
    c = collections.Counter(re.sub(r"-p[EO]-w\d", "", r)[:40] for r in rs)
    print(nm, " ".join(f"{k}:{v}" for k, v in c.most_common(int(sys.argv[3]) if len(sys.argv) > 3 else 12)))
