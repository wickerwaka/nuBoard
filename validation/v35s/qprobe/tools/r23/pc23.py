"""pc23.py [kind=intp0] round... : edge-sweep families of a scanned source.  Per run: e (the edge,
clocks from M0) and the clocks c for which Q83's rule (p19.py's B) reproduces the pushed
instruction; then per alignment the lattice c = L (mod 16) and the lead X (c = the first lattice
clock >= e + X) that reproduce most runs."""
import json, sys, collections
from pathlib import Path
from validation.v35s.qprobe import model_m, read
kw = dict(x.split("=") for x in sys.argv[1:] if "=" in x)
KIND = kw.get("kind", "intp0")
for rnd in [x for x in sys.argv[1:] if "=" not in x]:
    tab = collections.defaultdict(list)
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
            if kw.get("anc") == "E":            # the boundary word behind each pop in the pop's place, dd clocks allowed for
                lasts = sorted(t for t, at, ip, acts, stall, last in o["WLOG"] if last and not stall)
                pops = [(next((x for x in lasts if x >= t), 999) - int(kw.get("dd", 0)), a) for t, a in pops]
            evs = {t for t, at, ip, acts, stall, last in o["WLOG"] if ip == 0 or "D" in acts or "N" in acts}
            cyc = [(t, k, 3 if k in "IO" else 3 + w) for t, k, wh in evm if t > 60]
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
            if pc is None:
                continue
            ok = []
            for c in range(60, 200):
                tev = min((t for t in evs if t >= c), default=None)
                if tev is None:
                    continue
                h = tev
                for T, k, ln in cyc:
                    if T < h <= T + ln - 1: h = T + ln
                for T, k, ln in cyc:
                    if T == h + 1: h = T
                if h == tev and any(t == h for t, _ in pops) and any(k == "F" and T == h for T, k, ln in cyc):
                    h += 1
                sh = dl = None
                for T, k, ln in cyc:
                    if k in "RW" and T in (h, h + 1) and T > 76: sh, dl = T, h + 2 - T
                pp = [(t + dl if sh is not None and t >= sh else t, a) for t, a in pops]
                if next((a for t, a in pp if t >= h + 5), None) == pc:
                    ok.append(c)
            tab[w, r["chain"]["parity"][0]].append((e, ok, cid))
    for key in sorted(tab):
        rows = tab[key]
        best = collections.Counter()
        for L in range(16):
            for X8 in range(0, 30 * 8):
                X = X8 / 8
                n = 0
                for e, ok, cid in rows:
                    import math
                    c0 = math.ceil(e + X)
                    c = c0 + (L - c0) % 16
                    n += c in ok
                best[L, X] = n
        top = max(best.values())
        Ls = sorted({L for (L, X), v in best.items() if v == top})
        print(f"{rnd} w{key[0]} {key[1]}: {len(rows)} runs ({sum(1 for r in rows if r[1])} with a c); lattice + lead best {top}:",
              "; ".join(f"L={L} X={min(X for (l, X), v in best.items() if v == top and l == L)}..{max(X for (l, X), v in best.items() if v == top and l == L)}" for L in Ls))
        if kw.get("v"):
            for e, ok, cid in sorted(rows):
                print("   ", cid[4:], e, (ok[0], ok[-1]) if ok else None)
