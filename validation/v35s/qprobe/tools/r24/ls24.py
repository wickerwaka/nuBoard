"""ls24.py SUBSTR...: socket runs whose id holds every substring: exact (cmp22) or first divergence, one line each."""
import sys, glob, json
sys.path[:0] = ["host/src", ".", "build/qp"]
from validation.v35s.qprobe import read, model_m as M
import cmp22
ids = [a for a in sys.argv[1:] if "=" not in a]
o = M.options([a for a in sys.argv[1:] if "=" in a])
runs = read.load("socket")
for cid, run in runs.items():
    if not all(s in cid for s in ids) or "stim" in run["chain"]["knobs"]:
        continue
    try:
        a, m = cmp22.compare(run, o)
    except Exception as e:
        print(cid, "ERR", repr(e)[:60]); continue
    if a == m:
        print(cid, "=")
    else:
        k = next((i for i, (x, y) in enumerate(zip(a, m)) if x != y), min(len(a), len(m)))
        print(cid, "X", "si", M.fmt(a[k:k+2]), "| mo", M.fmt(m[k:k+2]))
