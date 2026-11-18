"""Word populations for the 40-bit layout study. Read-only on the repository.

  P0   the present ROM, as assembled (2,848 words, one chain per routine)
  PT   the ROM after tail sharing (docs/v35s-urom-v20-techniques.md technique 1), laid out:
       every shared word stored once; a word that runs on into a shared word either sits in
       front of it (fall-through) or carries a jump to it
  PH   tail sharing with hold counts (technique 2): the empty clocks behind a word folded into
       a count on it, the shared delay routine gone

Sharing classes are those of urom_stats/v20/depth_stats.py (build, minimise); the layout pass
here adds what that script only counts: which predecessor falls through, which words get a
jump, and the copies needed where a word that cannot jump (a conditional, a call, a loop) must
be followed by a shared word that already has a predecessor in front of it.
"""
import collections, os, sys
ROOT = "/home/wickerwaka/src/nuBoard"
sys.dont_write_bytecode = True
sys.path[:0] = [ROOT, ROOT + "/host/src", ROOT + "/validation/v35s/chains/urom_stats/v20"]
os.chdir(ROOT)
from validation.v35s.chains import uasm
import depth_stats as Dp

P = Dp.p
SQ = Dp.SQ
SEQV = {v: k for k, v in SQ.items()}
ENUM_NAME = {}
for t, (w, vals) in uasm.ENUMS.items(): ENUM_NAME[t] = {v: k.split("_", 1)[1] for k, v in vals.items()}
def fname(f, v):
    t = uasm.FIELD_TYPE.get(f)
    return ENUM_NAME[t].get(v, str(v)) if t in ENUM_NAME else str(v)
HAS_TGT = ("JMP", "JC", "JNC", "CALL", "LOOP", "EAC", "TKI")
HARD = ("JC", "JNC", "CALL", "LOOP", "EAC", "TKI", "TRAP")      # must be followed by the next word
W0, R0 = Dp.W0, Dp.R0

A_EDITS = (("rep_stm", 1, "move"), ("rep_cmpbk", 1, "drop"), ("rep_cmpm", 1, "drop"))
def apply_a_edits():
    """Way out (a) as three source edits, applied to the assembled program in memory only:
    rep_stm+1's act (AW into the write datum) moves to the empty word behind it; rep_cmpbk+1
    and rep_cmpm+1 lose the address load that the words before and behind them also make."""
    for name, k, how in A_EDITS:
        r = P.routine(name); w = r.words[k]; n = r.words[k + 1]
        keys = [a for a in ("ra", "rb", "wid", "d1", "s1") if w.fields.get(a)]
        if how == "move":
            assert not any(v for a, v in n.fields.items() if a != "nb"), (name, n.fields)
            for a in keys: n.fields[a] = w.fields[a]
        else:
            assert all(n.fields.get(a) == w.fields[a] for a in keys) and all(r.words[k - 1].fields.get(a) == w.fields[a] for a in ("d1",)), name
        for a in keys: w.fields.pop(a)

def show(f, hold=0):
    out = []
    for name, t, w in uasm.FIELDS:
        v = f.get(name, 0)
        if not v: continue
        if name == "tgt": out.append(f"tgt={v}" if isinstance(v, int) else f"tgt={v}")
        elif t == "bit": out.append(name)
        else: out.append(f"{name}={fname(name, v)}")
    if hold: out.append(f"hold={hold}")
    return " ".join(out) or "(empty)"

class Word:
    __slots__ = ("f", "hold", "members", "routines", "forced", "copy", "addr", "line", "kind", "cls", "ftc", "jtc", "note")
    def __init__(s, f, hold=0, members=(), forced=False, copy=False):
        s.f = dict(f); s.hold = hold; s.members = list(members); s.forced = forced; s.copy = copy
        s.routines = sorted(set(R0[i].name for i in s.members)); s.addr = None; s.kind = None; s.cls = None; s.ftc = None; s.jtc = None; s.note = ''
    def seq(s): return SQ[s.f.get("seq", 0)]
    def has_tgt(s): return s.seq() in HAS_TGT
    def where(s):
        r = s.routines
        i = s.members[0]
        return f"{R0[i].name}+{i - R0[i].base}" + (f" (+{len(r) - 1} routines)" if len(r) > 1 else "")

def present():
    chains = []
    for r in P.routines:
        ch = []
        for k, x in enumerate(r.words):
            ch.append(Word({a: v for a, v in x.fields.items() if v}, 0, [r.base + k]))
        chains.append(ch)
    return chains

def shared(hold, wide_with_jump=None, verbose=False):
    """-> (chains, stats). wide_with_jump(fields, hold) -> a rank: the larger, the more the word
    needs the fall-through place in front of a shared word (it cannot also carry a jump)."""
    rank = wide_with_jump or (lambda f, h: len(f) + (5 if h else 0))
    nodes, idx = Dp.build(hold, False, drop_dly=hold)
    c, ncls, extra = Dp.minimise(nodes, idx)
    n = len(nodes); pos = {nd["i"]: k for k, nd in enumerate(nodes)}
    mem = collections.defaultdict(list)
    for k in range(n): mem[c[k]].append(k)
    rep = {cl: ks[0] for cl, ks in mem.items()}
    kind = {}; ft = {}; tg = {}
    for cl, k in rep.items():
        f = nodes[k]["f"]; s = SQ[f.get("seq", 0)]
        if s in ("NEXT", "JMP"):
            kind[cl] = "n"; ft[cl] = c[k + 1] if s == "NEXT" else c[pos[f.get("tgt", 0)]]
        elif s in HARD:
            kind[cl] = "h"; ft[cl] = c[k + 1]
            if s != "TRAP": tg[cl] = c[pos[f.get("tgt", 0)]] if f.get("tgt", 0) in pos else None
        else: kind[cl] = "e"
    # the place in front of each shared word
    hp = collections.defaultdict(list); sp = collections.defaultdict(list)
    for cl in rep:
        if kind[cl] == "h": hp[ft[cl]].append(cl)
        elif kind[cl] == "n": sp[ft[cl]].append(cl)
    nxt = {}; copies = []      # cl -> the class physically behind it
    def rk(cl): return rank(nodes[rep[cl]]["f"], nodes[rep[cl]]["hold"])
    for s in set(hp) | set(sp):
        if hp[s]:
            nxt[hp[s][0]] = s
            for o in hp[s][1:]: copies.append((o, s))
        else:
            best = max(sp[s], key=lambda cl: (rk(cl), -rep[cl]))
            nxt[best] = s
    # break cycles of fall-through (a loop closed by a jump must keep one jump)
    prv = {v: k for k, v in nxt.items()}
    seen = set()
    for cl in list(nxt):
        if cl in seen: continue
        path = []; x = cl
        while x in nxt and x not in path and x not in seen: path.append(x); x = nxt[x]
        if x in path:      # a cycle: cut it at a soft word
            cyc = path[path.index(x):]
            cut = min((y for y in cyc if kind[y] == "n"), key=rk)
            del prv[nxt[cut]]; del nxt[cut]
        seen.update(path)
    prv = {v: k for k, v in nxt.items()}
    def mk(cl, jump_to=None, copy=False):
        nd = nodes[rep[cl]]; f = dict(nd["f"])
        mb = [nodes[k]["i"] for k in mem[cl]]
        if kind[cl] == "n":
            was_next = any(SQ[nodes[k]["f"].get("seq", 0)] == "NEXT" for k in mem[cl])
            f.pop("seq", None); f.pop("tgt", None)
            if jump_to is not None:
                f["seq"] = SEQV["JMP"]; f["tgt"] = ("cls", jump_to)
            w = Word(f, nd["hold"], mb, forced=(jump_to is not None and was_next), copy=copy)
            w.kind = "n"; w.cls = cl; w.ftc = ft[cl]; return w
        if cl in tg: f["tgt"] = ("cls", tg[cl])
        w = Word(f, nd["hold"], mb, copy=copy)
        w.kind = kind[cl]; w.cls = cl; w.ftc = ft.get(cl); w.jtc = tg.get(cl); return w
    chains = []; ncopy = 0
    heads = [cl for cl in rep if cl not in prv]
    for h in sorted(heads, key=lambda cl: rep[cl]):
        ch = []; x = h
        while True:
            if kind[x] == "n" and x not in nxt: ch.append(mk(x, jump_to=ft[x])); break
            ch.append(mk(x))
            if x not in nxt: break
            x = nxt[x]
        chains.append(ch)
    placed = sum(len(ch) for ch in chains)
    assert placed == len(rep), (placed, len(rep))
    # copies: a hard word whose next word is a shared word that already has a hard word in front
    by_tail = collections.defaultdict(list)
    for o, s in copies: by_tail[o].append(s)
    for ch in chains: pass
    extra_ch = []
    for o, s in copies:
        # the copy of s goes behind o: o must end its chain. o is a hard word with no nxt
        seqw = []; x = s
        while True:
            if kind[x] == "n": seqw.append(mk(x, jump_to=ft[x], copy=True)); break
            seqw.append(mk(x, copy=True))
            if kind[x] == "e": break
            x = ft[x]
        ncopy += len(seqw)
        for ch in chains:
            if ch and ch[-1].members and ch[-1].members[0] == nodes[rep[o]]["i"] and not ch[-1].copy:
                ch.extend(seqw); break
        else: raise AssertionError("copy has no place")
    proto = {cl: mk(cl) for cl in rep}        # a class's word as stored (for copies made later)
    st = dict(classes=len(rep), copies=ncopy, words=len(rep) + ncopy, chains=len(chains), minimise=(ncls, extra), proto=proto, mk=mk, kind=kind, ft=ft)
    return chains, st

def flat(chains): return [w for ch in chains for w in ch]

if __name__ == "__main__":
    for name, ch, st in (("P0 present", present(), None),) + tuple((nm,) + shared(h) for nm, h in (("PT tail sharing", False), ("PH tail sharing + hold counts", True))):
        ws = flat(ch)
        j = sum(1 for w in ws if w.seq() == "JMP"); fj = sum(1 for w in ws if w.forced)
        print(f"{name}: words {len(ws)}, chains {len(ch)}, unconditional jump words {j} (forced by sharing {fj}), words with a hold count {sum(1 for w in ws if w.hold)}, max hold {max(w.hold for w in ws)}", {k: v for k, v in (st or {}).items() if k in ("classes", "copies", "minimise")})
