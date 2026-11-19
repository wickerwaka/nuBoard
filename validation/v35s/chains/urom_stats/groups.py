import math, collections
from validation.v35s.chains import uasm
p = uasm.assemble(share=False); F = uasm.FIELDS
W = [x for r, x in p.words]; n = len(W)
seqn = {v: k for k, v in uasm.ENUMS["v35_seq_e"][1].items()}
print("seq usage", collections.Counter(seqn[x.fields.get("seq", 0)] for x in W).most_common())
groups = {
 "regrd": ["ra", "rb"], "regwr": ["wr", "ws"], "mv1": ["d1", "s1"], "mv2": ["d2", "s2"],
 "alu": ["alu", "ax", "ay", "wf"], "bus": ["ea", "bus", "seg"], "queue": ["pop", "rl", "ro"],
 "seq": ["seq", "cond", "tgt"], "cnt": ["cnt"], "kind": ["e", "f", "nb", "bi", "vk", "flush"],
 "rare": ["pfx", "susp", "halt", "ist"], "wid": ["wid"]}
def used(x): return frozenset(g for g, fs in groups.items() if any(x.fields.get(f, 0) for f in fs))
c = collections.Counter(used(x) for x in W)
print("distinct group combinations", len(c))
print("groups used per word:", sorted(collections.Counter(len(u) for u in c.elements()).items()))
for g in groups: print(f"  {g:6} in {sum(v for u, v in c.items() if g in u)*100//n}% of words")
for u, v in c.most_common(25): print(f"{v:5}  {'+'.join(sorted(u)) or '(empty)'}")
# bits needed per word if each word carried only its used groups
gw = {g: sum(w for nme, t, w in F if nme in fs) for g, fs in groups.items()}
print("group widths", gw)
bits = sorted(sum(gw[g] for g in u) for u in c.elements())
print("payload bits per word: median", bits[n//2], "p90", bits[n*9//10], "p99", bits[n*99//100], "max", bits[-1])
for lim in (24, 28, 32, 36, 40, 48):
    print(f"  words whose used groups exceed {lim} bits: {sum(1 for b in bits if b > lim)}")
# distinct values per group (dictionary size if a group were a pointer into a small table)
for g, fs in groups.items():
    d = len(set(tuple(x.fields.get(f, 0) for f in fs) for x in W))
    print(f"  {g:6} {gw[g]:2} bits, {d:4} distinct combos -> {max(1,math.ceil(math.log2(d)))} bits")
