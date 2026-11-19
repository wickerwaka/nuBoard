"""cal27.py DIR [SUBSTR]: per run of r27cal, the lengths (ticks, strobe fall to rise as the lane records it) of the fetches
behind M0, the ticks between successive back-to-back fetch starts (the cycle), and the I/O cycles' lengths."""
import json, glob, collections, sys
for p in sorted(glob.glob(sys.argv[1] + "/QPr27*.json")):
    for r in json.load(open(p))["runs"]:
        cid = r["chain"]["id"]
        if len(sys.argv) > 2 and sys.argv[2] not in cid: continue
        t = r["socket_trace"]
        k = [i for i, x in enumerate(t) if x["flags"] & 2 and x["address"] & 0xffff == 0x21][0]
        f = [x for x in t[k + 1:] if x["flags"] & 1 and not x["flags"] & 6]
        L = collections.Counter(x["end"] - x["start"] for x in f)
        gaps = collections.Counter(b["start"] - a["start"] for a, b in zip(f, f[1:]))
        io = [x["end"] - x["start"] for x in t[k:] if x["flags"] & 2]
        print(f"{cid:34} {r['passed']} prc={r['chain']['prc']:02X} strobe {dict(L)} min gap {min(gaps)} io {io}")
