"""i26.py [v]: family r26i (EI in the body, INTP0 at level 7 pending with IE = 0). Per train and parity, per lead: the
vector read's first clock A (from M0), the instruction pushed (index in the train behind EI), A less the pad's clocks
(k leads), and for the load train the masked twin's first reads (the train's clocks without the interrupt)."""
import sys, json, re, collections
sys.path[:0] = ["host/src", "."]
from pathlib import Path
from validation.v35s.qprobe import read
V = len(sys.argv) > 1
runs = {}
for path in sorted(Path("build/validation/v35s/qprobe/socket").glob("QPr26i-w0.json")):
    runs.update({r["chain"]["id"]: r for r in json.loads(path.read_text())["runs"]})
def key(cid):
    tn, ln, tag, par = re.match(r"QPr26i-(\w+)-(\w+)-([um])-p([EO])", cid).groups()
    return tn, par, (0, int(ln[1:])) if re.fullmatch(r"k\d+", ln) else (1, ln)
for cid in sorted(runs, key=key):
    if "-u-" not in cid: continue
    r = runs[cid]; tn, par, lk = key(cid)
    ev = read.events(r)
    A = next((t for t, k, wh in ev if k == "R" and wh == 0x60), None)
    pcw = [x for x in r["socket_trace"] if not x["flags"] & 0x207 and x["address"] == 0xEFA]
    ins = [i for i in r["chain"]["instrs"] if i["form"] == "x"]
    base = r["chain_base"] - 0x10000
    idx = next((n for n, i in enumerate(ins) if pcw and base + i["offset"] == pcw[-1]["data"]), None)
    ei = next(n for n, i in enumerate(ins) if i["code"] == "fb")
    k = lk[1] if lk[0] == 0 else None
    fs = [t for t, kk, wh in ev if kk == "F" and 76 < t < (A or 200)]
    extra = ""
    m = runs.get(cid.replace("-u-", "-m-"))
    if m:
        em = read.events(m)
        rd = [t for t, kk, wh in em if kk == "R" and wh == 0x800][:8]
        ru = [t for t, kk, wh in ev if kk == "R" and wh == 0x800 and t < A]
        extra = f" twin reads {rd} run {ru}"
    print(f"{tn} p{par} {str(lk[1]):>3}: A {A} A-k {A - k if k is not None and A else ''} pushed #{idx - ei if idx is not None else None} (behind EI){extra}" + (f" F {fs}" if V else ""))
