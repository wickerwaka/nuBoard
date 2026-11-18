"""p25.py FORMS(comma) [w0,w1,w2] [K=V..]: r25b runs of the forms: clocks relative to the word that pops the store's last
address byte (P; from the model's word log, valid while the model is exact up to there): q = bytes held after that
word, silicon's fetch starts and the write, the model's write; grouped by the pattern."""
import sys, json, re, collections
sys.path[:0] = ["host/src", ".", "build/qp"]
from pathlib import Path
from validation.v35s.qprobe import model_m as M
forms = sys.argv[1].split(","); ws = sys.argv[2].split(",") if len(sys.argv) > 2 and "=" not in sys.argv[2] else ["w0", "w1", "w2"]
o = M.options([a for a in sys.argv[2:] if "=" in a])
rows = collections.defaultdict(list)
for p in sorted(Path("build/validation/v35s/qprobe/socket").glob("QPr25b-w[012].json")):
    for run in json.loads(p.read_text())["runs"]:
        cid = run["chain"]["id"]
        lp, form, par, w = re.match(r"QPr25b-(\w+)-(\w+)-p([EO])-w(\d)", cid).groups()
        if form not in forms or "w" + w not in ws: continue
        oo = dict(o); oo["WLOG"] = []; hist = {}; oo["HIST"] = hist
        mo = M.simulate(run, oo); si = M.silicon(run, o)
        # the store is the last body instruction: its routine's pops
        ins = [i for i in run["chain"]["instrs"] if i["role"] == "q"]
        st_at = None
        wl = oo["WLOG"]
        # find the last word with a pop before the model's store write
        mw = [e for e in mo if e[1] == "W"]; sw = [e for e in si if e[1] == "W"]
        k = -1 if lp[0] != "p" or len(mw) < 2 else -1
        mwt, swt = mw[-1][0] if mw else None, sw[-1][0] if sw else None
        # M1's own writes do not exist (OUT marker): the last write is the store's
        pops = [(t, acts) for t, at, ip, acts, stall, last in wl if not stall and ("P" in acts) and t < mwt]
        P = pops[-1][0]
        req = [t for t, at, ip, acts, stall, last in wl if not stall and ("Y" in acts or "Z" in acts) and t < mwt][-1]
        cyc = 3 + int(w)
        fs = [c - P for c, k_, wh in si if k_ == "F" and -2 * cyc - 1 <= c - P <= 3 * cyc + 4]
        eus = [f"{k_}{c - P}" for c, k_, wh in si if k_ in "ORI" and -12 <= c - P < 0]
        key = (w, f"q{hist.get(P)}", f"Y{req - P:+d}", " ".join(eus), "F" + ",".join(map(str, fs)), f"W{swt - P:+d}", f"mo{mwt - P:+d}")
        rows[key].append(f"{lp}-{form}-{par}")
for key, v in sorted(rows.items()):
    print(" ".join(key), "|", len(v), " ".join(v)[:110])
