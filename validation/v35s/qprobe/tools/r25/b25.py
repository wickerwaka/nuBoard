"""b25.py [SUBSTR...] [K=V...] [-m] [-t]: family r25b. Per run: the events from the lead's EU cycle to M1's OUT as offsets
from the lead's cycle start (silicon; and the model's when it differs). -m: misses only. -t: table of exact counts
(rows lead+pad, columns form)."""
import sys, json, re, collections
sys.path[:0] = ["host/src", ".", "build/qp"]
from pathlib import Path
from validation.v35s.qprobe import read, model_m as M
import cmp22
argv = sys.argv[1:]
flags = {a for a in argv if a.startswith("-") and len(a) == 2}; argv = [a for a in argv if a not in flags]
ids = [a for a in argv if "=" not in a]; o = M.options([a for a in argv if "=" in a])
runs = {}
for p in sorted(Path("build/validation/v35s/qprobe/socket").glob("QPr25b-w[012].json")):
    for r in json.loads(p.read_text())["runs"]:
        runs[r["chain"]["id"]] = r
def pat(ev):
    k0 = next((i for i, e in enumerate(ev) if e[1] in "OWR"), 0)
    t0 = ev[k0][0]
    return " ".join(f"{k}{c - t0}" for c, k, wh in ev[k0:])
tab = collections.defaultdict(lambda: [0, 0]); n = ok = 0
for cid, run in runs.items():
    if not all(s in cid for s in ids): continue
    try:
        a, m = cmp22.compare(run, o)
    except Exception as e:
        a, m = M.silicon(run, o), []
    n += 1; ok += a == m
    lp, form, par, w = re.match(r"QPr25b-(\w+)-(\w+)-p([EO])-w(\d)", cid).groups()
    tab[(lp, form)][0] += a == m; tab[(lp, form)][1] += 1
    if "-t" in flags or ("-m" in flags and a == m): continue
    print(f"{lp:3} {form:6} p{par} w{w} {'=' if a == m else 'X'} {pat(a)}" + ("" if a == m else f"\n{'':19} {pat(m) if m else 'ERR'}"))
if "-t" in flags:
    forms = list(dict.fromkeys(f for _, f in tab)); lps = list(dict.fromkeys(l for l, _ in tab))
    print("     " + " ".join(f"{f:>6}" for f in forms))
    for l in lps:
        print(f"{l:4} " + " ".join(f"{tab[(l, f)][0]:>4}/{tab[(l, f)][1]}" for f in forms))
print(ok, "/", n)
