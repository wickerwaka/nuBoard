"""h26.py TRAIN [v]: family r26h<TRAIN> (a DMA transfer, I/O to memory, the DMARQ0 edge stepped a clock at a time across a
train of stores, DIC0 masked). Per run: the DMA's cycles (I/O read, write at D0060h) and the train's store writes
around them, clocks from M0; the store writes' period from the latest edge (the undisturbed train); per parity the
position of the DMA write against the store write in front of it and behind it, as offsets."""
import sys, json, re, collections
sys.path[:0] = ["host/src", "."]
from pathlib import Path
from validation.v35s.qprobe import read
tr = sys.argv[1]; V = len(sys.argv) > 2
for path in sorted(Path("build/validation/v35s/qprobe/socket").glob(f"QPr26h{tr}-w0.json")):
    runs = {r["chain"]["id"]: r for r in json.loads(path.read_text())["runs"]}
    tab = collections.defaultdict(list)
    for cid, r in sorted(runs.items(), key=lambda kv: (kv[0][-5:], int(re.search(r"-e(\d+)-", kv[0]).group(1)))):
        e = int(re.search(r"-e(\d+)-", cid).group(1)); par = cid[-4]
        ev = read.events(r)
        dw = [t for t, k, wh in ev if k == "W" and 0xD000 <= wh < 0xE000]
        di = [t for t, k, wh in ev if k == "I"]
        sw = [t for t, k, wh in ev if k == "W" and wh < 0x1000 and t > 60]
        fs = [t for t, k, wh in ev if k == "F"]
        if not dw:
            print(cid, "no DMA write"); continue
        tw = dw[0]; ti = tw
        before = [t for t in sw if t < ti]; after = [t for t in sw if t > ti]
        fb = [t for t in fs if t < ti]; fa = [t for t in fs if t > tw]
        row = (e, ti, tw, ti - before[-1] if before else None, after[0] - tw if after else None,
               ti - fb[-1] if fb else None, fa[0] - tw if fa else None)
        tab[par].append(row)
        if V:
            print(cid[-14:], "I", ti, "DW", tw, "| stores", [t - ti for t in sw if -30 < t - ti < 40], "| F", [t - ti for t in fs if -12 < t - ti < 22])
    for par, rows in sorted(tab.items()):
        print(tr, "p" + par)
        print("   e: I-edge, I - last store write before, next store write - DMA write, I - last fetch, next fetch - DMA write")
        for e, ti, tw, a, b, c, d in rows:
            print(f"   e{e}: I at {ti} (e+{ti - e}), W {tw}; store before -{a}, store after +{b}; fetch before -{c}, after +{d}")
