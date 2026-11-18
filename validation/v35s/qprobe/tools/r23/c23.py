"""c23.py round... : load-train DMA families.  For every unmasked run: the set of clocks c (the
request standing at the EU, from M0) for which Q83's rule (event = first word or the datum word
current; the 2-clock occupation; 5 clocks; first pop) reproduces the pushed instruction, the
vector-read clock and the displaced read, the train's cycles and pops taken from the masked twin
(read at T: datum pop T + 3, last word T + 4, first word T + 5, request T + 6, T + 7 a plain word,
the datum word current from T + 8).  Prints c - tw (tw = the terminal DMA write's first clock)."""
import json, sys, collections
from pathlib import Path
from validation.v35s.qprobe import read
V = "v=1" in sys.argv
for rnd in [x for x in sys.argv[1:] if "=" not in x]:
    for path in sorted(Path("build/validation/v35s/qprobe/socket").glob(f"QP{rnd}-w*.json")):
        runs = {r["chain"]["id"]: r for r in json.loads(path.read_text())["runs"]}
        tab = collections.defaultdict(list)
        for cid, r in sorted(runs.items()):
            if "-u-" not in cid:
                continue
            m = runs[cid.replace("-u-", "-m-")]
            eu, em = read.events(r), read.events(m)
            tw = [t for t, k, wh in eu if k == "W" and 0xD000 <= wh < 0xE000][-1]
            A = next((t for t, k, wh in eu if k == "R" and wh in (0x50, 0x54) and t > tw), None)
            pcw = [x for x in r["socket_trace"] if not x["flags"] & 1 and x["address"] == 0xEFA]
            ins = [i for i in r["chain"]["instrs"] if i["form"] == "x"]
            base = r["chain_base"] - 0x10000
            idx = next((n for n, i in enumerate(ins) if base + i["offset"] == pcw[-1]["data"]), None)
            lds = [n for n, i in enumerate(ins) if i["code"] == "8b07"]
            rdm = [t for t, k, wh in em if k == "R" and wh == 0x800]
            rdu = [t for t, k, wh in eu if k == "R" and wh == 0x800 and t < A]
            pops = [(T + 3, lds[i] + 1) for i, T in enumerate(rdm)]
            cyc = [(t, k, 3) for t, k, wh in em if t > 60]
            evs = set()
            for a in rdm:                       # first word T - 5; the datum word current T - 2 .. T + 3
                evs.add(a - 5); evs.update(range(a - 2, a + 4))
            t1 = min(t for t in rdm if t > tw)  # in front of the first load behind the transfer: the DMA
            evs.update(range(tw - 10, t1 - 5))  # routine's words (not read: every clock taken as an event)
            ok = []
            for c in range(tw - 10, tw + 60):
                tev = min((t for t in evs if t >= c), default=None)
                if tev is None: continue
                h = tev
                for T, k, ln in cyc:
                    if T < h <= T + ln - 1: h = T + ln
                for T, k, ln in cyc:
                    if T == h + 1: h = T
                sh = dl = None
                for T, k, ln in cyc:
                    if k in "RW" and T in (h, h + 1): sh, dl = T, h + 2 - T
                var = [(sh, dl)]
                if sh is None:                  # a prefetch whose first clock is h or h + 1 is decided again behind the
                    for T, k, ln in cyc:        # occupation: either it starts at h + 3 and the read behind it waits for
                        if k == "F" and T in (h, h + 1):   # it, or it is not made in front of that read (both seen; which: not read)
                            nx = next((x for x in rdm if x > T), None)
                            if nx is not None and nx < h + 6:
                                var.append((nx, h + 6 - nx))
                for sh, dl in var:
                    pp = [(t + dl if sh is not None and t >= sh + 3 else t, a) for t, a in pops]
                    rp = [T + dl if sh is not None and T >= sh else T for T in rdm]
                    P = next(((t, a) for t, a in pp if t >= h + 5), None)
                    if P and P[1] == idx and P[0] + 17 == A and [T for T in rp if T < P[0]] == rdu:
                        ok.append(c); break
            par = r["chain"]["parity"][0]
            tab[par].append((tw, ok, cid[4:], A - tw))
            if V: print(cid[4:], "tw", tw, "A-tw", A - tw, "c", ok, "c-tw", [c - tw for c in ok])
        for par in sorted(tab):
            rows = tab[par]
            print(f"{rnd} {par}: {len(rows)} runs, {sum(1 for r in rows if r[1])} with a c that reproduces")
            # one lattice: c = L + 16 n, the first with c - tw >= m
            best = collections.Counter()
            for L in range(16):
                for mth in range(-4, 30):
                    n = 0
                    for tw, ok, cid, a in rows:
                        c = next(x for x in range(tw + mth, tw + mth + 16) if x % 16 == L)
                        n += c in ok
                    best[L, mth] = n
            top = max(best.values())
            print("   lattice rule c = first clock == L (mod 16) with c - tw >= m: best", top, "at (L, m) =", sorted(k for k, v in best.items() if v == top))
            fixed = collections.Counter(c - tw for tw, ok, cid, a in rows for c in ok)
            print("   fixed c - tw: best", max(fixed.values()) if fixed else 0, "of", len(rows), "at", [k for k, v in fixed.items() if v == max(fixed.values())])
