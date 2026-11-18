"""e26.py [SUBSTR]: family r26e (INT stepped a clock at a time). Per program and parity: for each edge e the pushed
return offset (body-relative: which pop was replaced) and the body's own write clocks; then the threshold per
instruction: the last edge that still replaces its pop (pop = e_last + 9.125 rounded up, Q75)."""
import sys, json, re, collections
sys.path[:0] = ["host/src", ".", "build/qp"]
from pathlib import Path
from validation.v35s.qprobe import read
sub = sys.argv[1] if len(sys.argv) > 1 else ""
rows = collections.defaultdict(dict)
for p in sorted(Path("build/validation/v35s/qprobe/socket").glob("QPr26[ej]-w0.json")):
    for run in json.loads(p.read_text())["runs"]:
        cid = run["chain"]["id"]
        if sub not in cid: continue
        name, e, par = re.match(r"QPr26[ej]-(\S+)-e(\d+)-p([EO])", cid).groups()
        b = read.body_addr(run) - 0x10000
        # stack writes of the interrupt: three word writes at 0EFA..0EFE (data in the trace)
        tr = [x for x in run["socket_trace"] if not x["flags"] & 0x207]
        m0 = next(x["start"] for x in run["socket_trace"] if x["flags"] & 2 and not x["flags"] & 1 and x["address"] & 0xFFFF == 0x21)
        ws = [(round((x["start"] - m0) / 8), x["address"], x["data"]) for x in run["socket_trace"]
              if not x["flags"] & 0x207 and not x["flags"] & 1 and x["start"] > m0]
        stk = [w for w in ws if 0x0EF0 <= w[1] < 0x0F00]
        own = [w for w in ws if not 0x0EF0 <= w[1] < 0x0F00][:3]
        pc = stk[2][2] - b if len(stk) >= 3 else None
        rows[(name, par)][int(e)] = (pc, [w[0] for w in own], stk[0][0] if stk else None)
for (name, par), d in sorted(rows.items()):
    print(name, "p" + par, "own writes", sorted({tuple(v[1]) for v in d.values()}))
    print("   e:pc ", " ".join(f"{e}:{v[0]}" for e, v in sorted(d.items())))
    last = {}
    for e, v in sorted(d.items()):
        last[v[0]] = e
    print("   last edge per pushed offset:", " ".join(f"+{k}:e{v}(pop<={v + 10})" for k, v in sorted(last.items(), key=lambda kv: kv[1])))
