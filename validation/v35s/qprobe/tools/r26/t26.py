"""tb25.py FAMILY [SUBSTR...] [K=V ...] [-x]: socket runs of one round-25 family: per run '=' or 'X', and for the misses
(all with -a) silicon's and the model's events from the last common event's neighbourhood. -s: summary by program."""
import sys, json, re, collections
sys.path[:0] = ["host/src", ".", "build/qp"]
from pathlib import Path
from validation.v35s.qprobe import read, model_m as M
import cmp22
argv = sys.argv[1:]
flags = {a for a in argv if a.startswith("-") and len(a) == 2}; argv = [a for a in argv if a not in flags]
fam = argv[0]; ids = [a for a in argv[1:] if "=" not in a]; o = M.options([a for a in argv[1:] if "=" in a])
runs = {}
for p in sorted(Path("build/validation/v35s/qprobe/socket").glob(f"QP{fam}-w*.json")):
    for r in json.loads(p.read_text())["runs"]:
        runs[r["chain"]["id"]] = r
n = ok = 0; by = collections.defaultdict(list)
for cid, run in runs.items():
    if ids and not any(s in cid for s in ids): continue
    try:
        a, m = cmp22.compare(run, o)
    except Exception as e:
        a, m = [], [("ERR", repr(e)[:50], None)]
    n += 1; ok += a == m
    name = re.sub(r"^QPr2[56]\w*-|-p[EO]-w\d$", "", cid)
    by[name].append((cid[-5:], a == m))
    if "-s" in flags: continue
    if a != m or "-a" in flags:
        k = next((i for i, (x, y) in enumerate(zip(a, m)) if x != y), min(len(a), len(m)))
        lo = max(0, k - (3 if "-a" not in flags else 99))
        f = lambda ev: " ".join(f"{c}:{k_}{'' if wh is None or k_ != 'F' else format(wh, '+d')}" for c, k_, wh in ev[lo:k + 5]) if ev and ev[0][0] != "ERR" else str(ev)
        print(cid, "=" if a == m else "X"); print("   si", f(a)); print("   mo", f(m))
if "-s" in flags:
    for name, v in by.items():
        bad = [x for x, e in v if not e]
        print(f"{name:18} {len(v) - len(bad)}/{len(v)}", " ".join(bad))
print(ok, "/", n)
