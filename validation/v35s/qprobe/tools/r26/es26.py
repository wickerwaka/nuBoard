"""es26.py SIMDIR FAMILY: the INT-step families: the pushed return offset (body-relative) per edge, silicon against the RTL's
sim run of the same id; rows where they differ."""
import sys, json, re, collections
sys.path[:0] = ["host/src", "."]
from pathlib import Path
from validation.v35s.qprobe import read
def pushed(run):
    b = read.body_addr(run) - 0x10000
    tr = run["socket_trace"]
    m0 = next(x["start"] for x in tr if x["flags"] & 2 and not x["flags"] & 1 and x["address"] & 0xFFFF == 0x21)
    stk = [x for x in tr if not x["flags"] & 0x207 and x["start"] > m0 and 0x0EF0 <= x["address"] < 0x0F00]
    return stk[2]["data"] - b if len(stk) >= 3 else None
sim = {}
for p in sorted(Path(sys.argv[1]).glob(f"{sys.argv[2]}-w0.json")):
    for r in json.loads(p.read_text())["runs"]: sim[r["chain"]["id"]] = r
rows = collections.defaultdict(dict); n = d = 0
for p in sorted(Path("build/validation/v35s/qprobe/socket").glob(f"{sys.argv[2]}-w0.json")):
    for r in json.loads(p.read_text())["runs"]:
        cid = r["chain"]["id"]
        if cid not in sim: continue
        name, e, par = re.match(r"QPr26[ej]-(\S+)-e(\d+)-p([EO])", cid).groups()
        a, b = pushed(r), pushed(sim[cid]); n += 1; d += a != b
        rows[(name, par)][int(e)] = (a, b)
for k, v in sorted(rows.items()):
    dif = [f"e{e}: si +{a} rtl +{b}" for e, (a, b) in sorted(v.items()) if a != b]
    print(k[0], "p" + k[1], f"{len(v) - len(dif)}/{len(v)} the same instruction pushed;", "; ".join(dif))
print(n - d, "/", n)
