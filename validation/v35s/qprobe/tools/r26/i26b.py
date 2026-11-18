"""i26b.py: r26i. For every lead and parity: the masked twin (load train) through the model: exact or not, EI's words
(first word, the bus-idle third word's stall, the N word, the boundary) from the model's word log; then per train the
replaced pop P (A - 17 for INC / load, A - 19 for NOP) against EI's first word (E1), its third word executing (E3) and
its boundary (EB)."""
import sys, json, re, collections
sys.path[:0] = ["host/src", ".", "build/qp"]
from pathlib import Path
from validation.v35s.qprobe import read, model_m as M
import cmp22
runs = {}
for path in sorted(Path("build/validation/v35s/qprobe/socket").glob("QPr26i-w0.json")):
    runs.update({r["chain"]["id"]: r for r in json.loads(path.read_text())["runs"]})
def key(cid):
    tn, ln, tag, par = re.match(r"QPr26i-(\w+)-(\w+)-([um])-p([EO])", cid).groups()
    return par, (0, int(ln[1:])) if re.fullmatch(r"k\d+", ln) else (1, ln), tn
ei = {}
for cid, r in runs.items():
    if "-ld-" not in cid or "-m-" not in cid: continue
    par, lk, tn = key(cid)
    o = dict(M.DEFAULT); o["WLOG"] = []
    try:
        mo = M.simulate(r, o); si = M.silicon(r, M.DEFAULT)
    except Exception as e:
        ei[(par, lk)] = ("ERR " + repr(e)[:40],); continue
    # exact up to the 4th load read
    cut = lambda ev: [e for e in ev if e[0] < 160]
    ok = cut(si) == cut(mo)
    code = bytes.fromhex(r["code_hex"]) if "code_hex" in r else None
    # the EI routine in the word log: the instruction whose routine has 13 words and a B third word
    wl = o["WLOG"]
    # group by instruction start (at): find at whose opcode is FB
    base = r["chain_base"] - 0x10000
    ats = sorted({at for t, at, ip, acts, stall, last in wl if at is not None})
    eat = None
    for i in r["chain"]["instrs"]:
        if i["code"] == "fb": eoff = i["offset"]
    ws = [(t, ip, acts, stall, last) for t, at, ip, acts, stall, last in wl if at == eoff]
    if not ws:
        ws = [(t, ip, acts, stall, last) for t, at, ip, acts, stall, last in wl if at == eoff + base]
    e1 = ws[0][0]; e3 = max(t for t, ip, acts, stall, last in ws if ip == 2); eb = ws[-1][0]
    en = max(t for t, ip, acts, stall, last in ws if "N" in acts)
    ei[(par, lk)] = (ok, e1, e3, en, eb)
print("lead: twin exact in the model, EI first word E1, third word executes E3 (E3 - E1 - 2 = its stall), N word, boundary EB")
tab = collections.defaultdict(dict)
for cid in sorted(runs, key=key):
    if "-u-" not in cid: continue
    par, lk, tn = key(cid); r = runs[cid]
    A = next((t for t, k, wh in read.events(r) if k == "R" and wh == 0x60), None)
    tab[(par, lk)][tn] = A - (19 if tn == "nop" else 17)
for k, v in tab.items():
    e = ei.get(k)
    if not e or len(e) < 5: print(k, e); continue
    ok, e1, e3, en, eb = e
    print(f"p{k[0]} {str(k[1][1]):>3}: twin {'=' if ok else 'X'} E1 {e1} stall {e3 - e1 - 2} EB {eb} |",
          " ".join(f"{tn} P-E1 {p - e1:+d} P-EB {p - eb:+d}" for tn, p in sorted(v.items())))
