"""sh24.py ROUNDIDS KEY [ACTS] [K=V...]: for routine KEY one act added to one word; scored (cmp22) on the runs of the named
socket rounds whose id holds any of the comma-separated substrings. Fast (loads only those rounds)."""
import sys
sys.path[:0] = ["host/src", ".", "build/qp"]
from validation.v35s.qprobe import read, model_m as M
import cmp22, ld20
ids = sys.argv[1].split(","); key = sys.argv[2]
acts = sys.argv[3] if len(sys.argv) > 3 and "=" not in sys.argv[3] else "B"
o0 = M.options([a for a in sys.argv[3:] if "=" in a])
runs = ld20.load(ids)
def score(o):
    n = 0
    for cid, r in runs.items():
        try:
            a, m = cmp22.compare(r, o); n += a == m
        except Exception:
            pass
    return n
base = M.words(o0[key])
print("default", score(o0), "/", len(runs), o0[key])
for a in acts:
    for i in range(len(base)):
        w = [set(x) for x in base]; w[i] = w[i] | {a}
        o = dict(o0); o[key] = [sorted(x) for x in w]
        s = score(o)
        print(f"  {a}@{i}: {s}")
