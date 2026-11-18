"""cs25.py OUT.json [SUBSTR ...] [K=V ...]: every non-interrupt socket run by cmp22.compare: {id: exact}; total printed.
cs25.py -d A.json B.json: gained / lost."""
import sys, json, re, collections
sys.path[:0] = ["host/src", ".", "build/qp"]
if sys.argv[1] == "-d":
    a, b = json.load(open(sys.argv[2])), json.load(open(sys.argv[3]))
    g = [r for r in b if b[r] and not a.get(r)]; l = [r for r in b if a.get(r) and not b[r]]
    print(sum(a.values()), "/", len(a), "->", sum(b.values()), "/", len(b), "gained", len(g), "lost", len(l))
    for nm, rs in (("gained", g), ("lost", l)):
        c = collections.Counter(re.sub(r"-p[EO]-w\d", "", r)[:36] for r in rs)
        print(nm, " ".join(f"{k}:{v}" for k, v in c.most_common(30)))
    sys.exit()
from validation.v35s.qprobe import read, model_m as M
import cmp22
ids = [a for a in sys.argv[2:] if "=" not in a]; o = M.options([a for a in sys.argv[2:] if "=" in a])
res = {}
for cid, run in read.load("socket").items():
    if (ids and not any(s in cid for s in ids)) or "stim" in run["chain"]["knobs"]:
        continue
    try:
        a, m = cmp22.compare(run, o); res[cid] = a == m
    except Exception:
        res[cid] = False
json.dump(res, open(sys.argv[1], "w")); print(sum(res.values()), "/", len(res))
