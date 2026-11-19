import math, collections, os
IGN = set(("tgt,seq," + os.environ.get("IGN", "")).split(","))
from validation.v35s.chains import uasm
p = uasm.assemble(share=False); F = uasm.FIELDS
W = [x for r, x in p.words]; n = len(W)
SQ = uasm.ENUMS["v35_seq_e"][1]; sq = {v: k[3:] for k, v in SQ.items()}
def succ(i):
    f = W[i].fields; s = sq[f.get("seq", 0)]; t = f.get("tgt", 0)
    if s == "NEXT": return ("n", [i + 1])
    if s == "JMP": return ("j", [t])
    if s in ("JC", "JNC", "LOOP", "CALL", "EAC", "TKI"): return (s, [t, i + 1])
    return (s, [])
key0 = [tuple(v for k, v in sorted(W[i].fields.items()) if k not in IGN and v) for i in range(n)]
key0 = [tuple((k, v) for k, v in sorted(W[i].fields.items()) if k not in IGN and v) for i in range(n)]
cls = {}; c = [cls.setdefault(k, len(cls)) for k in key0]
while True:
    sig = []
    for i in range(n):
        kind, ss = succ(i)
        kk = "n" if kind in ("n", "j") else kind      # a jmp and a fall-through are the same step
        if kind in ("DISP", "DISPM", "RET", "TRAP"): tail = (kind, W[i].fields.get("tgt", 0) if kind != "RET" else 0)
        else: tail = (kk,) + tuple(c[s] if s < n else -1 for s in ss)
        sig.append((c[i], tail))
    m = {}; c2 = [m.setdefault(s, len(m)) for s in sig]
    if len(m) == len(set(c)): break
    c = c2
ncls = len(set(c)); print("words", n, "-> behaviourally distinct words (free jumps)", ncls)
# layout cost: a class reached by fall-through from words whose seq field is busy needs a copy per such predecessor class beyond one
need = collections.defaultdict(set); free = collections.defaultdict(set)
for i in range(n):
    kind, ss = succ(i)
    if kind == "n" and i + 1 < n: free[c[i + 1]].add(c[i])
    elif kind not in ("j",) and ss and i + 1 < n and (i + 1) in ss: need[c[i + 1]].add(c[i])
extra = sum(max(0, len(v) - 1) for v in need.values())
print("copies forced by a busy seq field in the predecessor:", extra, "-> about", ncls + extra, "words")
# how much of the ROM is timing-only
def timing(x):
    f = x.fields
    return not any(f.get(k, 0) for k in ("ra","rb","wr","ws","d1","s1","d2","s2","alu","ax","ay","wf","ea","bus","seg","cnt","pop"))
t = sum(1 for x in W if timing(x)); print("words with no datapath, bus or pop act (sequencing / pacing only):", t)
# call targets
tg = collections.Counter()
lab = {}
for r in p.routines:
    for k, w in enumerate(r.words): lab[r.base + k] = f"{r.name}+{k}"
for x in W:
    if sq[x.fields.get("seq", 0)] == "CALL": tg[lab.get(x.fields["tgt"], x.fields["tgt"])] += 1
print("call targets", tg.most_common(20))
print("DISP words", sum(1 for x in W if sq[x.fields.get('seq',0)] == 'DISP'))
# the per-class by file after minimization
byf = collections.defaultdict(set); k = 0
for r in p.routines:
    for w in r.words: byf[r.path.split('/')[-1]].add(c[k]); k += 1
print({f: len(v) for f, v in byf.items()})
