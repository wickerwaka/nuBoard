"""Used values per field and co-occurrence of field groups in the present ROM. Read-only.
usage (repo root): PYTHONPATH=host/src:. python3 <this> """
import collections, itertools
from validation.v35s.chains import uasm
p = uasm.assemble(); F = uasm.FIELDS
names = {}
for t, (w, vals) in uasm.ENUMS.items(): names[t] = {v: k for k, v in vals.items()}
def nm(f, v):
    t = uasm.FIELD_TYPE[f]
    return names[t].get(v, str(v)) if t in names else str(v)
W = [(r, w) for r, w in p.words]
print("words", len(W))
for f, t, w in F:
    if t == "addr": continue
    c = collections.Counter(x.fields.get(f, 0) for r, x in W)
    print(f"{f:6} w{w} used {len(c):2}: " + " ".join(f"{nm(f, v)}={n}" for v, n in sorted(c.items(), key=lambda kv: -kv[1])))
def combos(fs, label, top=80):
    c = collections.Counter(tuple(x.fields.get(f, 0) for f in fs) for r, x in W)
    print(f"\n[{label}] {fs}: {len(c)} distinct combinations")
    for k, n in sorted(c.items(), key=lambda kv: -kv[1])[:top]:
        print(f"   {n:5}  " + " ".join(nm(f, v) for f, v in zip(fs, k)))
    return c
combos(["seq", "cond"], "sequencing")
combos(["e", "f", "nb", "bi", "vk", "ro", "rl", "flush"], "kind bits")
combos(["e", "f", "nb", "bi", "vk", "ro", "rl", "flush", "pop"], "kind bits + pop")
combos(["pfx", "susp", "halt", "ist", "flush"], "rare")
combos(["ea", "bus", "seg"], "bus")
combos(["bus", "seg"], "bus seg")
combos(["ra", "rb"], "ra rb")
combos(["wr", "ws"], "wr ws")
combos(["d1", "s1"], "mv1")
combos(["d2", "s2"], "mv2")
combos(["d1", "s1", "d2", "s2"], "mv1 mv2")
combos(["alu", "ax", "ay", "wf"], "alu", 200)
combos(["ax", "ay"], "ax ay")
combos(["cnt"], "cnt")
combos(["wid"], "wid")
combos(["pop"], "pop")
# vk with tgt
print("\nvk words with tgt:", collections.Counter((x.fields.get("tgt",0), x.fields.get("seq",0), x.fields.get("bi",0), x.fields.get("rl",0)) for r, x in W if x.fields.get("vk")))
G = {"regrd": ["ra", "rb"], "regwr": ["wr", "ws"], "mv1": ["d1", "s1"], "mv2": ["d2", "s2"],
     "alu": ["alu", "ax", "ay", "wf"], "bus": ["ea", "bus", "seg"], "pop": ["pop"], "rel": ["rl", "ro"],
     "tgt": ["tgt"], "seq": ["seq", "cond"], "cnt": ["cnt"], "kind": ["e", "f", "nb", "bi", "vk", "flush"],
     "rare": ["pfx", "susp", "halt", "ist"], "wid": ["wid"]}
U = collections.Counter(frozenset(g for g, fs in G.items() if any(x.fields.get(f, 0) for f in fs)) for r, x in W)
print("\ngroup-use combinations:", len(U))
for u, n in U.most_common(70): print(f"   {n:5}  {' '.join(sorted(u))}")
print("\npairwise co-occurrence of groups (words using both):")
gs = list(G)
print("        " + " ".join(f"{g:>6}" for g in gs))
for a in gs:
    print(f"{a:7} " + " ".join(f"{sum(n for u, n in U.items() if a in u and b in u):6}" for b in gs))
