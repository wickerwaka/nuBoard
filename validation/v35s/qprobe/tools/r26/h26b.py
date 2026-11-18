"""h26b.py TRAIN [PAR]: r26h<TRAIN>: every run against the undisturbed train (the latest edge's run up to its transfer, and
the earliest edge's run behind it): the DMA write's first clock tw, the train's store writes and fetches as absolute
clocks; the first event that differs from the reference; per tw the range of edges."""
import sys, json, re, collections
sys.path[:0] = ["host/src", "."]
from pathlib import Path
from validation.v35s.qprobe import read
tr = sys.argv[1]
for par in (sys.argv[2:] or ["E", "O"]):
    runs = {}
    for path in sorted(Path("build/validation/v35s/qprobe/socket").glob(f"QPr26h{tr}-w0.json")):
        for r in json.loads(path.read_text())["runs"]:
            if r["chain"]["id"][-4] == par:
                runs[int(re.search(r"-e(\d+)-", r["chain"]["id"]).group(1))] = read.events(r)
    ref = [(t, k) for t, k, wh in runs[max(runs)] if k in "WF" and not (k == "W" and wh >= 0xD000)]
    by = collections.defaultdict(list)
    for e in sorted(runs):
        ev = runs[e]
        tw = next(t for t, k, wh in ev if k == "W" and wh >= 0xD000)
        me = [(t, k) for t, k, wh in ev if k in "WF" and not (k == "W" and wh >= 0xD000)]
        i = next((i for i, (a, b) in enumerate(zip(me, ref)) if a != b), None)
        lastw = max((t for t, k in me if k == "W" and 60 < t < tw), default=0); nextw = min(t for t, k in me if k == "W" and t > tw)
        lastf = max((t for t, k in me if k == "F" and t < tw), default=0); nextf = min(t for t, k in me if k == "F" and t > tw)
        by[tw].append(e)
        d = f"first diff: ref {ref[i]} run {me[i]}" if i is not None and ref[i][0] < tw + 40 else ""
        print(f"p{par} e{e}: tw {tw} (e+{tw - e}) last store W {lastw} (tw-{tw - lastw}) last F {lastf} (tw-{tw - lastf}); next F tw+{nextf - tw}, next store tw+{nextw - tw}; {d}")
    print("ref stores", [t for t, k in ref if k == "W" and 80 < t < 150])
    print("ref fetches", [t for t, k in ref if k == "F" and 80 < t < 150])
    print({tw: (min(es), max(es)) for tw, es in sorted(by.items())})
