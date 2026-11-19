import collections
from validation.v35s.chains import uasm
p = uasm.assemble(share=False); W = [x for r, x in p.words]; n = len(W)
sq = {v: k[3:] for k, v in uasm.ENUMS["v35_seq_e"][1].items()}
DP = ("ra","rb","wr","ws","d1","s1","d2","s2","alu","ax","ay","wf","ea","bus","seg","cnt","pop")
tg = set(x.fields.get("tgt", 0) for x in W if sq[x.fields.get("seq",0)] != "NEXT") | set(r.base for r in p.routines)
def pace(i): return not any(W[i].fields.get(k, 0) for k in DP)
s = lambda i: sq[W[i].fields.get("seq", 0)]
fold = [i for i in range(1, n) if pace(i) and s(i) == "NEXT" and i not in tg and s(i-1) == "NEXT"]
print("pacing-only fall-through words that could fold into a predecessor's hold count:", len(fold))
kinds = collections.Counter(tuple((k, v) for k, v in sorted(W[i].fields.items()) if v and k not in ("seq","tgt")) for i in fold)
print("distinct pacing kinds among them:", len(kinds)); print(kinds.most_common(12))
# run lengths
runs = collections.Counter(); i = 0; fs = set(fold)
while i < n:
    if i in fs:
        j = i
        while j + 1 in fs: j += 1
        runs[j - i + 1] += 1; i = j + 1
    else: i += 1
print("run lengths", sorted(runs.items()))
print("call-to-dly words", sum(1 for i in range(n) if s(i) == "CALL" and pace(i)))
