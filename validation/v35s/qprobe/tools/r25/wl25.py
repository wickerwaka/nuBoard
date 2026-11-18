"""wl25.py RUN_ID LO HI [K=V...]: a socket run: the model's word log between model clocks LO..HI, silicon and model events."""
import sys, json
sys.path[:0] = ["host/src", ".", "build/qp"]
from pathlib import Path
from validation.v35s.qprobe import model_m as M
rid, lo, hi = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]); o = M.options(sys.argv[4:])
fam = rid.split("-")[0]
run = next(r for p in sorted(Path("build/validation/v35s/qprobe/socket").glob(f"{fam}-w*.json")) for r in json.loads(p.read_text())["runs"] if r["chain"]["id"] == rid)
oo = dict(o); oo["WLOG"] = []; hist = {}; oo["HIST"] = hist
mo = M.simulate(run, oo); si = M.silicon(run, o)
f = lambda ev: " ".join(f"{c}:{k}{'' if wh is None or k != 'F' else format(wh, '+d')}" for c, k, wh in ev if lo - 4 <= c <= hi + 8)
print("si", f(si)); print("mo", f(mo))
print("wl", " ".join(f"{t}:{ip}{acts or '.'}{'*' if stall else ''}{'|' if is_last and not stall else ''}q{hist.get(t)}" for t, at, ip, acts, stall, is_last in oo["WLOG"] if lo <= t <= hi))
