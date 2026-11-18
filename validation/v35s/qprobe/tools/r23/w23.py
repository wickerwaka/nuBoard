"""w23.py round... : on which word is the request read?  INT runs (kind=int): per train and
alignment, the lead interval (lo, hi] in clocks from the pin edge that puts the replaced
instruction's anchor first at or after e + lead, for three anchors: N = the pop (the N word
executing, model notation), E = the boundary word that makes the popped opcode the running
instruction (the last word of the routine), N+1.  One machine = one lead for every train.
kind=intp0 / nmi (vectored): the same for the anchor of the replaced pop behind the occupation
(h + 5 <= anchor), c from the lattice (intp0: L = 2 / 3, e + 10.2) or e + 8.875 (nmi)."""
import json, sys, collections, math
from pathlib import Path
from validation.v35s.qprobe import model_m, read
kw = dict(x.split("=") for x in sys.argv[1:] if "=" in x)
KIND = kw.get("kind", "int")
res = collections.defaultdict(lambda: {a: [-99.0, 99.0, 0] for a in ("N", "E")})
for rnd in [x for x in sys.argv[1:] if "=" not in x]:
    for path in sorted(Path("build/validation/v35s/qprobe/socket").glob(f"QP{rnd}-w*.json")):
        for r in json.loads(path.read_text())["runs"]:
            cid = r["chain"]["id"]
            if f"-{KIND}-" not in cid or "-d2000-" in cid:
                continue
            o = model_m.options([]); o["NLOG"] = []; o["WLOG"] = []
            try:
                evm = model_m.simulate(r, o)
            except Exception:
                continue
            w = r["chain"]["waits"]
            base = read.body_addr(r) - 0x10000
            xs = [i for i in r["chain"]["instrs"] if i["form"] == "x"]
            first = r["chain_base"] - 0x10000 + xs[0]["offset"]
            pops = sorted((t, base + a - first) for t, a in o["NLOG"])
            lasts = sorted(t for t, at, ip, acts, stall, last in o["WLOG"] if last and not stall)
            anc = {"N": pops, "E": [(next((x for x in lasts if x >= t), 999), a) for t, a in pops]}
            recs = r["socket_trace"]
            t0 = next(x for x in recs if x["address"] == 0x21 and not x["flags"] & 1)["start"]
            evp = next(x for x in recs if (x["address"] & 0xFFFF) == 0xFF12 and not x["flags"] & 1)
            e = (evp["end"] + 4 + r["chain"]["knobs"]["stim"]["entries"][0]["delay"] - t0) / 8
            d = [x for x in recs if x["start"] > t0 and not x["flags"] & 0x200]
            pc = None
            for k, x in enumerate(d):
                if x["flags"] & 1 and x["address"] < 0x400 and x["address"] % 4 == 0 and (x["start"] - t0) / 8 > 70:
                    wr = [y for y in d[k + 1:k + 8] if not y["flags"] & 1 and y["address"] < 0x10000]
                    pc = wr[2]["data"] - first if len(wr) >= 3 else None
                    break
            if pc is None or pc < 0:
                continue
            code = xs[min(len(xs) - 1, max(0, [i for i, x in enumerate(xs) if x["offset"] - xs[0]["offset"] == pc][0] if any(x["offset"] - xs[0]["offset"] == pc for x in xs) else 0))]["code"]
            key = (rnd, cid.split("-")[1] if rnd.startswith("r19") or rnd.startswith("r17") else "", w, r["chain"]["parity"][0])
            for a, lst in anc.items():
                i = next((i for i, (t, ad) in enumerate(lst) if ad == pc), None)
                if i is None or i == 0:
                    continue
                st = res[key][a]
                st[1] = min(st[1], lst[i][0] - e); st[0] = max(st[0], lst[i - 1][0] - e); st[2] += 1
for key in sorted(res):
    print(*key, " ".join(f"{a}: ({v[0]:.3f}, {v[1]:.3f}] {'ok' if v[0] < v[1] else 'NO single lead'} n={v[2]}" for a, v in res[key].items()))
