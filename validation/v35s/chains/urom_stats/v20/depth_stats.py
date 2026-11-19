"""Depth estimates for our ROM under the V20's sharing techniques, alone and stacked. Read-only.
usage: PYTHONPATH=host/src:. python3 depth_stats.py

Steps (each an option; the table at the end stacks them):
  T  tail sharing: words with the same fields and the same continuation stored once (D1)
  H  a hold count on a word: the empty clocks after a word (empty words, calls into the shared
     delay) fold into a count on the word before; the shared delay routine goes
  K  run length on identical waiting words (the same kind bits, no act) -- reported apart
  S  steering: the named fields are taken from the instruction (ignored when comparing words)
  P  head sharing: routines whose first words are identical share them (the decode table names
     the head and the body; the head returns), counted on what T leaves unshared
"""
import collections, sys, os
from validation.v35s.chains import uasm
p = uasm.assemble(share=False); F = uasm.FIELDS
SQ = {v: k[3:] for k, v in uasm.ENUMS["v35_seq_e"][1].items()}
DP = ("ra","rb","wr","ws","d1","s1","d2","s2","alu","ax","ay","wf","ea","bus","seg","cnt","pop")
dly = p.routine("dly"); d0 = dly.base
NBFOLD = os.environ.get("NBFOLD", "1") == "1"
W0 = [x for r, x in p.words]; R0 = [r for r, x in p.words]; N0 = len(W0)
def sq(x): return SQ[x.fields.get("seq", 0)]
def isdly(x): return sq(x) == "CALL" and d0 <= x.fields.get("tgt", 0) < d0 + 24
def dlyk(x): return d0 + 24 - x.fields["tgt"]
targets = set(x.fields.get("tgt", 0) for x in W0 if sq(x) not in ("NEXT", "DISP", "RET", "TRAP") and not isdly(x)) | set(r.base for r in p.routines)

def build(hold=False, runlen=False, drop_dly=False):
    """-> list of nodes: dict(i=orig index, f=fields (no seq/tgt for dly calls when hold), hold=n, rep=n)"""
    nodes = []; idx = {}
    for i, x in enumerate(W0):
        if drop_dly and R0[i].name == "dly": continue
        f = {k: v for k, v in x.fields.items() if v}
        h = 0
        if hold and isdly(x):
            h = dlyk(x); f.pop("seq"); f.pop("tgt")
        act = any(f.get(k, 0) for k in DP)
        # nothing at all: an empty clock. A word whose only bit is the assembler's derived
        # look-ahead mark (nb on a non-E word: "the next word is a bus-idle word") is empty too:
        # the mark then belongs to the hold's last clock (NBFOLD=0 turns this off)
        nbonly = NBFOLD and set(f) == {"nb"}
        empty = not f or nbonly
        prev = nodes[-1] if nodes else None
        can = prev is not None and i not in targets and R0[prev["i"]] is R0[i] and "seq" not in prev["f"] and not prev["f"].get("e")
        if hold and can and empty:
            prev["hold"] += 1 + h; idx[i] = None
            if nbonly: prev["f"]["nb_last"] = 1
            continue
        if runlen and can and not act and "seq" not in f and f == prev["f"] and prev["hold"] == 0 and not h:
            prev["rep"] += 1; idx[i] = None; continue
        idx[i] = len(nodes); nodes.append(dict(i=i, f=f, hold=h, rep=0))
    return nodes, idx

def minimise(nodes, idx, ign=()):
    n = len(nodes); ign = set(ign) | {"tgt", "seq"}
    pos = {nd["i"]: k for k, nd in enumerate(nodes)}
    def succ(k):
        nd = nodes[k]; f = nd["f"]; s = SQ[f.get("seq", 0)]; t = f.get("tgt", 0)
        nx = k + 1
        if s == "NEXT": return ("n", [nx])
        if s == "JMP": return ("j", [pos.get(t, -1)])
        if s in ("JC", "JNC", "LOOP", "CALL", "EAC", "TKI"): return (s, [pos.get(t, -1), nx])
        return (s, [])
    key0 = [(tuple((k, v) for k, v in sorted(nd["f"].items()) if k not in ign), nd["hold"], nd["rep"]) for nd in nodes]
    cls = {}; c = [cls.setdefault(k, len(cls)) for k in key0]
    while True:
        sig = []
        for k in range(n):
            kind, ss = succ(k)
            kk = "n" if kind in ("n", "j") else kind
            if kind in ("DISP", "DISPM", "RET", "TRAP"): tail = (kind, nodes[k]["f"].get("tgt", 0) if kind != "RET" else 0)
            else: tail = (kk,) + tuple(c[s] if 0 <= s < n else -1 for s in ss)
            sig.append((c[k], tail))
        m = {}; c2 = [m.setdefault(s, len(m)) for s in sig]
        if len(m) == len(set(c)): break
        c = c2
    need = collections.defaultdict(set)
    for k in range(n):
        kind, ss = succ(k)
        if kind not in ("n", "j") and ss and k + 1 < n and (k + 1) in ss: need[c[k + 1]].add(c[k])
    extra = sum(max(0, len(v) - 1) for v in need.values())
    return c, len(set(c)), extra

def heads(nodes, c, ign=()):
    """Head sharing on what tail sharing leaves: per routine, the straight run of words from the
    entry whose class has one member; a trie over their fields; the best single cut per group
    (one return register: a head does not call a head)."""
    ign = set(ign) | {"tgt", "seq"}
    size = collections.Counter(c)
    by_r = collections.defaultdict(list)
    for k, nd in enumerate(nodes): by_r[R0[nd["i"]].name].append(k)
    pre = {}
    for nm, ks in by_r.items():
        seq = []
        for k in ks:
            nd = nodes[k]
            if size[c[k]] > 1 or "seq" in nd["f"] or nd["f"].get("e"): break
            if k != ks[0] and nd["i"] in targets: break
            seq.append((tuple((a, v) for a, v in sorted(nd["f"].items()) if a not in ign), nd["hold"], nd["rep"]))
        # the body must keep at least one word to return to
        if len(seq) == len(ks): seq = seq[:-1]
        if seq: pre[nm] = seq
    def best(names, d):
        if len(names) < 2: return 0, []
        L = d
        while all(len(pre[nm]) > L for nm in names) and len(set(pre[nm][L] for nm in names)) == 1: L += 1
        a = L * (len(names) - 1)
        parts = collections.defaultdict(list)
        for nm in names:
            if len(pre[nm]) > L: parts[pre[nm][L]].append(nm)
        b = 0; bl = []
        for sub in parts.values():
            v, l = best(sub, L); b += v; bl += l
        return (a, [(L, tuple(names))]) if a >= b else (b, bl)
    first = collections.defaultdict(list)
    for nm, s in pre.items(): first[s[0]].append(nm)
    tot = 0; groups = []
    for sub in first.values():
        v, l = best(sub, 0); tot += v; groups += [g for g in l if g[0] > 0]
    return tot, groups

if __name__ == "__main__":
    print("ROM words", N0)
    rows = []
    def run(label, hold=False, runlen=False, ign=(), show=False):
        nodes, idx = build(hold, runlen, drop_dly=hold)
        c, ncls, extra = minimise(nodes, idx, ign)
        hs, groups = heads(nodes, c, ign)
        rows.append((label, len(nodes), ncls + extra, hs, ncls + extra - hs))
        if show:
            print(f"\n[{label}] head groups (words in the head x routines sharing it):")
            for L, names in sorted(groups, key=lambda g: -g[0] * (len(g[1]) - 1))[:40]:
                print(f"   {L:2} x {len(names):2}  saves {L * (len(names) - 1):3}  {' '.join(names[:9])}{' ...' if len(names) > 9 else ''}")
            print("   groups:", len(groups))
        return nodes, c
    run("as built (no sharing)")           # the minimise column is T
    run("T  tail sharing", show=True)
    run("T + S(wid alu)", ign=("wid", "alu"))
    run("T + S(wid alu regs)", ign=("wid", "alu", "ra", "rb", "wr"))
    run("T + S(wid alu regs seg)", ign=("wid", "alu", "ra", "rb", "wr", "seg"))
    nodes, c = run("T + H", hold=True, show=True)
    hc = collections.Counter(nd["hold"] for nd in nodes if nd["hold"]); print("\nhold counts on words (T + H):", sorted(hc.items()), " words carrying one:", sum(hc.values()))
    run("T + H + K", hold=True, runlen=True)
    run("T + H + S(wid alu)", hold=True, ign=("wid", "alu"))
    run("T + H + S(wid alu regs seg)", hold=True, ign=("wid", "alu", "ra", "rb", "wr", "seg"))
    run("T + H + K + S(wid alu regs seg)", hold=True, runlen=True, ign=("wid", "alu", "ra", "rb", "wr", "seg"))
    print(f"\n{'option':36} {'words in':>8} {'after T':>8} {'heads save':>10} {'T + P':>7}")
    for r in rows: print(f"{r[0]:36} {r[1]:8} {r[2]:8} {r[3]:10} {r[4]:7}")
    # what tail sharing shares: acting or pacing words
    nodes, idx = build(); c, ncls, extra = minimise(nodes, idx)
    size = collections.Counter(c); seen = set(); sv = collections.Counter()
    for k, nd in enumerate(nodes):
        kind = "acting" if any(nd["f"].get(a) for a in DP) else "post-E empty" if SQ[nd["f"].get("seq", 0)] == "DISP" else "pacing"
        if c[k] in seen: sv[kind] += 1
        seen.add(c[k])
    print("\nwords removed by tail sharing, by kind:", dict(sv))
