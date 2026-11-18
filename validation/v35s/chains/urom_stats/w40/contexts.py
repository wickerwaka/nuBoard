"""Late payloads by context (register read or not, target or not, hold or not): words, distinct\npayloads, which of the atom groups they use. usage: python3 -B contexts.py > contexts.txt"""
import collections, lib, math
LATE = ["alu","ax","ay","wf","wr","ws","d1","s1","d2","s2","ea","bus","seg","cnt","pfx","susp","halt","ist"]
AT = {"X": ["alu","ax","ay","wf"], "M": ["d1","s1","d2","s2"], "W": ["wr","ws"], "U": ["ea","bus","seg"], "C": ["cnt","pfx","susp","halt","ist"]}
def late(w): return tuple(w.f.get(a, 0) for a in LATE)
def atoms(w): return tuple(a for a, fs in AT.items() if any(w.f.get(f, 0) for f in fs))
def usesB(w): return w.has_tgt() or (w.f.get("vk") and not w.f.get("bi") and w.f.get("rl", 0) != 3)
for name, ch in (("P0", lib.present()), ("PT", lib.shared(False)[0]), ("PH", lib.shared(True)[0])):
    ws = lib.flat(ch); print(f"\n== {name} {len(ws)}")
    ctx = collections.defaultdict(list)
    for w in ws:
        if not any(late(w)): continue
        ra, rb = bool(w.f.get("ra")), bool(w.f.get("rb"))
        reg = "AB" if ra and rb else "A" if ra else "B" if rb else "-"
        ctx[("T" if usesB(w) else "n") + ("h" if w.hold else "") + ":" + reg].append(w)
    for k in sorted(ctx):
        v = ctx[k]; d = set(late(w) for w in v); ac = collections.Counter(atoms(w) for w in v)
        print(f"  {k:6} words {len(v):4}  distinct late payloads {len(d):4}   atoms: " + ", ".join(f"{'+'.join(a)} {n}" for a, n in ac.most_common(12)))
        for a in AT:
            dd = set(tuple(w.f.get(f, 0) for f in AT[a]) for w in v if a in atoms(w))
            if dd: print(f"            {a}: {len(dd)} distinct", end="")
        print()
