"""l23.py [m=7] round... : DMA families of any train.  Per unmasked run: tw (terminal DMA write's
first clock), A (vector read), P = A - (16 + the train's words from its pop to its last word:
NOP 3, CBW 2, INC 1, MOV r8,imm8 1, MOV AW,[BW] 1), cL = the first clock == L (mod 16) at or
after tw + m (L = 2 / 3 at even / odd alignment: INTP0's level-7 lattice in this frame, pc23.py).
Prints the distributions of A - tw (a fixed path would give one value per train) and of P - cL
(Q83's rule: 5 to 12 by train), and the displaced cycles against the masked twin."""
import json, sys, collections
from pathlib import Path
from validation.v35s.qprobe import read
kw = dict(x.split("=") for x in sys.argv[1:] if "=" in x)
M = int(kw.get("m", 7)); LE = int(kw.get("L", 2))
TAIL = {"90": 19, "98": 18, "43": 17, "b355": 17, "8b07": 17}
for rnd in [x for x in sys.argv[1:] if "=" not in x]:
    for path in sorted(Path("build/validation/v35s/qprobe/socket").glob(f"QP{rnd}-w*.json")):
        runs = {r["chain"]["id"]: r for r in json.loads(path.read_text())["runs"]}
        st = collections.defaultdict(lambda: [collections.Counter(), collections.Counter(), collections.Counter(), 0, collections.Counter()])
        for cid, r in sorted(runs.items()):
            if "-u-" not in cid:
                continue
            m = runs.get(cid.replace("-u-", "-m-"))
            eu = [e for e in read.events(r)]
            em = read.events(m) if m else []
            dw = [t for t, k, wh in eu if k == "W" and 0xD000 <= wh < 0xE000]
            par = r["chain"]["parity"][0]
            s = st[par]; s[3] += 1
            A = next((t for t, k, wh in eu if k == "R" and wh in (0x50, 0x54) and dw and t > dw[-1]), None)
            if A is None:
                s[0]["none"] += 1; continue
            tw = dw[-1]
            pcw = [x for x in r["socket_trace"] if not x["flags"] & 1 and x["address"] == 0xEFA]
            ins = [i for i in r["chain"]["instrs"] if i["form"] == "x"]
            base = r["chain_base"] - 0x10000
            idx = next((n for n, i in enumerate(ins) if base + i["offset"] == pcw[-1]["data"]), None)
            prev = ins[idx - 1]["code"] if idx else "?"
            P = A - TAIL.get(prev, 17)
            L = LE if par == "e" else LE + 1
            cL = next(x for x in range(tw + M, tw + M + 16) if x % 16 == L)
            s[0][A - tw] += 1; s[1][P - cL] += 1; s[4][cL - tw] += 1
            i = next((i for i, (x, y) in enumerate(zip(eu, em)) if x != y), None)
            if i is not None and eu[i][0] < A and eu[i][1:] == em[i][1:]:
                s[2][f"{em[i][1]}@cL{em[i][0] - cL:+d}:{eu[i][0] - em[i][0]:+d}"] += 1
            if kw.get("v"):
                print(cid[4:], "tw", tw, "A-tw", A - tw, "push", idx, prev, "cL-tw", cL - tw, "P-cL", P - cL)
        for par in sorted(st):
            s = st[par]
            print(f"{rnd} {par}: {s[3]} runs; A - tw:", dict(sorted(s[0].items(), key=lambda x: str(x))), "\n    cL - tw:", dict(sorted(s[4].items())),
                  "\n    P - cL:", dict(sorted(s[1].items())), "\n    first displaced cycle (kind @ clock - cL : shift):", dict(sorted(s[2].items())))
