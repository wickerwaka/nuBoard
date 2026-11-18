"""How many hold slots would the pieces of split microwords fill at a 40-bit word?

A hold slot = a clock with no datapath, bus or pop act: a pacing-only ROM word, or a clock
spent in the shared delay routine `dly` (a `call=dly+k` word stands for 24 - k such clocks).
A word is split when its used field groups exceed the payload (scenario W), or when it holds
more than one datapath operation (scenario O), or more than one primitive step (scenario P).
Pieces that may move (register read, move, ALU, register write) look for a hold slot in the
same straight-line segment of the routine, within D clocks, with room for them."""
import collections, sys
from validation.v35s.chains import uasm
p = uasm.assemble(); F = uasm.FIELDS
sq = {v: k[3:] for k, v in uasm.ENUMS["v35_seq_e"][1].items()}
G = {"regrd": ["ra", "rb"], "regwr": ["wr", "ws"], "mv1": ["d1", "s1"], "mv2": ["d2", "s2"],
     "alu": ["alu", "ax", "ay", "wf"], "bus": ["ea", "bus", "seg"], "queue": ["pop", "rl", "ro"],
     "seq": ["seq", "cond", "tgt"], "cnt": ["cnt"], "kind": ["e", "f", "nb", "bi", "vk", "flush"],
     "rare": ["pfx", "susp", "halt", "ist"], "wid": ["wid"]}
GW = {g: sum(w for n, t, w in F if n in fs) for g, fs in G.items()}
MOV = ("regrd", "mv1", "mv2", "alu", "regwr")          # may move to a neighbouring clock
DP = [f for g in MOV + ("bus", "cnt") for f in G[g]] + ["pop"]
TAG = 3; B = int(sys.argv[1]) if len(sys.argv) > 1 else 40; PAY = B - TAG
dly = p.routine("dly"); d0 = dly.base
tg = set()
for r, w in p.words:
    if sq[w.fields.get("seq", 0)] not in ("NEXT",) and not (d0 <= w.fields.get("tgt", 0) < d0 + 24):
        tg.add(w.fields.get("tgt", 0))
def used(w): return [g for g, fs in G.items() if any(w.fields.get(f, 0) for f in fs)]
def bits(gs): return sum(GW[g] for g in gs)
def prims(w):
    f = w.fields
    return [x for x in (("ra", f.get("ra", 0)), ("rb", f.get("rb", 0)), ("mv1", f.get("d1", 0) or f.get("s1", 0)),
            ("mv2", f.get("d2", 0) or f.get("s2", 0)), ("alu", f.get("alu", 0) or f.get("ax", 0) or f.get("ay", 0)),
            ("wr", f.get("wr", 0) or f.get("ws", 0))) if x[1]]
# the clock sequence of every routine, cut into straight-line segments
segs = []; nwords = 0; tot_hold = collections.Counter()
for r in p.routines:
    if r.name == "dly": continue
    seg = []
    for k, w in enumerate(r.words):
        a = r.base + k
        if a in tg and seg: segs.append(seg); seg = []
        s = sq[w.fields.get("seq", 0)]; t = w.fields.get("tgt", 0)
        gs = used(w); hold = not any(w.fields.get(f, 0) for f in DP)
        seg.append(dict(w=w, gs=gs, hold=hold, free=PAY - bits(gs), r=r.name, virt=False))
        if hold: tot_hold["pacing-only word" + (" (kind bits)" if set(gs) & {"kind", "queue"} else " (a call into dly)" if s == "CALL" and d0 <= t < d0 + 24 else " (sequencing only)" if "seq" in gs else " (empty)")] += 1
        if s == "CALL" and d0 <= t < d0 + 24:
            for _ in range(d0 + 24 - t):
                seg.append(dict(w=None, gs=[], hold=True, free=PAY, r=r.name, virt=True)); tot_hold["clock inside dly"] += 1
        elif s != "NEXT":
            segs.append(seg); seg = []
    if seg: segs.append(seg)
allc = [c for s in segs for c in s]
H = sum(1 for c in allc if c["hold"])
print(f"word {B} bits = tag {TAG} + payload {PAY}")
print(f"clocks along the routines: {len(allc)}; hold slots: {H}"); 
for k, v in tot_hold.most_common(): print(f"   {v:5}  {k}")
def run(name, pieces_of):
    """pieces_of(cell) -> (list of piece bit sizes that must leave the word, unsplittable?)"""
    dem = sum(len(pieces_of(c)[0]) for c in allc if not c["virt"]); src = sum(1 for c in allc if not c["virt"] and pieces_of(c)[0])
    stuck = sum(1 for c in allc if not c["virt"] and pieces_of(c)[1])
    print(f"\n{name}: {src} words shed {dem} pieces; {stuck} words still too wide after shedding")
    for D in (1, 2, 4, 99):
        placed = 0; newc = 0
        for s in segs:
            free = [c["free"] if c["hold"] else -1 for c in s]
            for i, c in enumerate(s):
                if c["virt"]: continue
                for pb in pieces_of(c)[0]:
                    best = None
                    for d in range(1, D + 1):
                        for j in (i - d, i + d):
                            if 0 <= j < len(s) and free[j] >= pb: best = j; break
                        if best is not None: break
                    if best is None: newc += 1
                    else: free[best] = -1; placed += 1
        print(f"   within {D if D < 99 else 'any'} clock(s) in the segment: {placed} pieces fill a hold slot ({placed * 100 // H}% of the hold slots), {newc} need a new clock")
def W(c):
    gs = c["gs"]; over = bits(gs) - PAY; out = []
    for g in sorted((g for g in gs if g in MOV), key=lambda g: -GW[g]):
        if over <= 0: break
        out.append(GW[g] + (GW["wid"] if "wid" in gs else 0)); over -= GW[g]
    return out, over > 0
def O(c):
    m = [g for g in c["gs"] if g in MOV]
    return [GW[g] + GW["wid"] for g in m[1:]], False
def P(c):
    m = prims(c["w"])
    return [12] * max(0, len(m) - 1), False
run("W: split only what does not fit the payload", W)
run("O: one datapath operation per word (register read / move / second move / ALU / register write)", O)
run("P: one primitive step per word (each register read, each move, the ALU, the write apart)", P)
