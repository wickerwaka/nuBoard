"""sc26.py SIMDIR [SUBSTR..]: the RTL's sim runs in SIMDIR against the socket runs of the same id: identical from the fill
to M1's cycle or the first difference (silicon | rtl), clocks from M0."""
import sys, json
sys.path[:0] = ["host/src", ".", "build/qp"]
from pathlib import Path
from validation.v35s.qprobe import read
ids = sys.argv[2:]
sim = {}
for p in sorted(Path(sys.argv[1]).glob("*.json")):
    for r in json.loads(p.read_text())["runs"]: sim[r["chain"]["id"]] = r
fams = {c.split("-")[0] for c in sim}
soc = {}
for f in fams:
    for p in sorted(Path("build/validation/v35s/qprobe/socket").glob(f"{f}-w*.json")):
        for r in json.loads(p.read_text())["runs"]: soc[r["chain"]["id"]] = r
n = ok = 0
for cid, r in sim.items():
    if cid not in soc or (ids and not any(s in cid for s in ids)): continue
    tr = "socket_trace" if "socket_trace" in r and r["socket_trace"] else "model_trace"
    try:
        a = read.window(soc[cid], read.events(soc[cid])); b = read.window(r, read.events(r, trace=tr))
    except Exception as e:
        print(cid, "ERR", repr(e)[:80]); continue
    n += 1; ok += a == b
    if a != b:
        k = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        print(cid, "X at", k, "| si", read.strip(a[max(0, k - 2):k + 3]), "| rtl", read.strip(b[max(0, k - 2):k + 3]))
print(ok, "/", n, "identical from the fill to M1")
