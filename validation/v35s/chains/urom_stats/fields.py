import math, collections, sys
from validation.v35s.chains import uasm
p = uasm.assemble(share=False)
F = uasm.FIELDS
W = [(r, w) for r, w in p.words]
n = len(W)
print("words", n, "bits", uasm.WORD_BITS, "UADDR_W", uasm.UADDR_W, "routines", len(p.routines))
packed = [uasm.pack(w.fields) for r, w in W]
print("distinct whole words", len(set(packed)))
addr = [f for f, t, _ in F if t == "addr"]
print("addr fields", addr)
def ent(vals):
    c = collections.Counter(vals); t = sum(c.values())
    return -sum(v/t*math.log2(v/t) for v in c.values())
tot = 0
print(f"{'field':10} {'type':14} w  distinct  nonzero%  need  entropy")
for name, t, w in F:
    vals = [x.fields.get(name, 0) for r, x in W]
    d = len(set(vals)); nz = sum(1 for v in vals if v) * 100 // n
    need = max(1, math.ceil(math.log2(d))) if d > 1 else 0
    tot += need
    print(f"{name:10} {t:14} {w:2} {d:6} {nz:8}%  {need:3}  {ent(vals):.2f}")
print("sum of per-field minimal widths", tot)
# words with the addr fields removed
na = [tuple(x.fields.get(f, 0) for f, t, _ in F if t != "addr") for r, x in W]
print("distinct non-address parts", len(set(na)), "-> index bits", math.ceil(math.log2(len(set(na)))))
# all-zero non-addr words (pure delay)
z = sum(1 for v in na if not any(v)); print("words with empty non-address part", z)
# OPEN words
print("open words", sum(1 for r, x in W if x.open))
# routine size distribution
sz = sorted(((len(r.words), r.name) for r in p.routines), reverse=True)
print("largest routines", sz[:25])
print("routines by file:")
c = collections.Counter(); 
for r in p.routines: c[r.path.split('/')[-1]] += len(r.words)
print(dict(c))
# duplicated straight-line tails: count words that are identical (whole word incl. targets) to another word and whose successor chain is identical
# suffix sharing estimate: sequences of words until a word with jmp/ret/e ... approximate by hashing chains of k
for k in (2, 3, 4, 6, 8):
    seqs = collections.Counter(tuple(packed[i:i+k]) for i in range(n - k + 1))
    dup = sum(v - 1 for v in seqs.values() if v > 1)
    print(f"repeated windows of {k} identical consecutive words: {dup}")
# run-length of identical consecutive words
runs = 0; i = 0
while i < n:
    j = i
    while j + 1 < n and packed[j+1] == packed[i]: j += 1
    if j > i: runs += j - i
    i = j + 1
print("words that repeat their predecessor exactly", runs)
