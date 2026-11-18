"""i26c.py: r26i scored against "the request stands at the EU on c = X + C" for X = EI's first word (E1), the clock its
third word executes (E3), its N word (EN), its boundary (EB): the instruction pushed, predicted from the model's word
log of the same program without the interrupt (event = the first word or the N word executing at or after c; the
first N word executing at or after the event + 5 is replaced; EI's own N word is not replaceable)."""
import sys, json, re, collections
sys.path[:0] = ["host/src", ".", "build/qp"]
from pathlib import Path
from validation.v35s.qprobe import read, model_m as M
runs = {}
for path in sorted(Path("build/validation/v35s/qprobe/socket").glob("QPr26i-w0.json")):
    runs.update({r["chain"]["id"]: r for r in json.loads(path.read_text())["runs"]})
rows = []
for cid, r in runs.items():
    if "-u-" not in cid or "-ld-" in cid: continue
    o = dict(M.DEFAULT); o["WLOG"] = []
    M.simulate(r, o)
    ins = [i for i in r["chain"]["instrs"] if i["form"] == "x"]
    eidx = next(n for n, i in enumerate(ins) if i["code"] == "fb")
    eoff = ins[eidx]["offset"]
    wl = [(t, at, ip, acts, last) for t, at, ip, acts, stall, last in o["WLOG"] if not stall]
    if not any(w[1] == eoff for w in wl):
        b0 = r["chain_base"] - 0x10000
        wl = [(t, at - b0 if at is not None else None, ip, acts, last) for t, at, ip, acts, last in wl]
    ws = [w for w in wl if w[1] == eoff]
    e1 = ws[0][0]; e3 = next(t for t, at, ip, acts, last in ws if ip == 2); en = next(t for t, at, ip, acts, last in ws if "N" in acts); eb = ws[-1][0]
    offs = {i["offset"]: n for n, i in enumerate(ins)}
    # events: first words and N words of the instructions behind EI; pops: N words (instruction index popped = executing + 1)
    ev = sorted({t for t, at, ip, acts, last in wl if at in offs and offs[at] > eidx and (ip == 0 or "N" in acts)} | {e1, en})
    pops = sorted((t, offs[at] + 1) for t, at, ip, acts, last in wl if at in offs and offs[at] > eidx and "N" in acts)
    pcw = [x for x in r["socket_trace"] if not x["flags"] & 0x207 and x["address"] == 0xEFA]
    base = r["chain_base"] - 0x10000
    idx = next((n for n, i in enumerate(ins) if pcw and base + i["offset"] == pcw[-1]["data"]), None)
    rows.append((cid, dict(E1=e1, E3=e3, EN=en, EB=eb), ev, pops, idx))
def pred(c, ev, pops):
    h = next((t for t in ev if t >= c), None)
    if h is None: return None
    return next((i for t, i in pops if t >= h + 5), None)
for X in ("E1", "E3", "EN", "EB"):
    best = []
    for C in range(-4, 34):
        n = sum(pred(a[X] + C, ev, pops) == idx for cid, a, ev, pops, idx in rows)
        best.append((n, C))
    best.sort(reverse=True)
    print(X, "best (runs of", len(rows), "): ", best[:4])
C = 24
miss = [cid[7:] for cid, a, ev, pops, idx in rows if pred(a["E1"] + C, ev, pops) != idx]
print("E1 + 24 misses:", miss)
