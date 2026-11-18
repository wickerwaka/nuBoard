"""Layout L40 on the ROM after tail sharing (PT) and after tail sharing with hold counts (PH).

The layout pass gives the fall-through place in front of a shared word to the predecessor
that could not carry a jump. What still does not fit is cleared by the assembler-only ways
out (no executed clock added or removed; each adds stored words only):
  U  un-share: the word keeps running on; the shared word behind it is copied (and the copy
     jumps on), up to a word that can carry the jump
  S  shed the hold count: the word's count goes to an empty word behind it (the hold's first
     clock becomes that word); a count over 16 keeps 16 and passes the rest on
  C  a call into the shared delay moves to an empty word behind the word (the delay's first
     clock becomes that word)                      [PT only: PH has no delay routine]
Left over ("native"): conditional words with a register read, a target and a payload.
usage: python3 -B fit_shared.py     (TKI=1: with the take-entry codes)"""
import collections, os, sys, lib, layout
from lib import SQ, SEQV
layout.TKI_CODES = os.environ.get("TKI", "1") == "1"
if os.environ.get("A", "1") == "1": lib.apply_a_edits()
def rank(f, hold):
    reg = layout.is_reg(f); x = layout.nz(layout.xp(f)); y = layout.nz(layout.yp(f)); h = bool(hold or f.get("nb_last"))
    return (4 if layout.is_vec(f) or (layout.kw(f) and f.get("e")) else 3 if reg and (x or y) else 3 if reg and h else 2 if h and (x or y) else 2 if x and y else 1 if x or y else 0, len(f))
def run(name, hold, verbose=True):
    chains, st = lib.shared(hold, wide_with_jump=rank)
    mk, kind, ft = st["mk"], st["kind"], st["ft"]
    dly = set(range(lib.Dp.d0, lib.Dp.d0 + 24))
    log = collections.Counter(); added = collections.Counter(); native = []
    base_words = sum(len(c) for c in chains)
    for rnd in range(4):
        ws = lib.flat(chains); L = layout.Layout(ws); changed = False
        if rnd == 0:
            first = collections.Counter()
            for w in ws:
                r = L.fit(w)
                if r: first[("forced jump: " if w.forced else "") + r] += 1
        native = []
        for ch in chains:
            i = 0
            while i < len(ch):
                w = ch[i]; r = L.fit(w)
                if not r: i += 1; continue
                sq = w.seq()
                if layout.held(w):                 # S
                    keep = 16 if r == "hold count over 16" else 0
                    e = lib.Word({}, max(0, w.hold - keep - 1), w.members, copy=True); e.kind = w.kind; e.cls = w.cls; e.ftc = w.ftc; e.note = "S"
                    if w.f.get("nb_last"):
                        if e.hold: e.f["nb_last"] = 1
                        else: e.f["nb"] = 1
                    if sq == "JMP": e.f["seq"] = w.f.pop("seq"); e.f["tgt"] = w.f.pop("tgt"); e.forced = w.forced; w.forced = False
                    w.hold = keep; w.f.pop("nb_last", None); w.kind = "x"
                    ch.insert(i + 1, e); log["S shed the hold count"] += 1; added["S"] += 1; changed = True; continue
                if sq == "JMP" and w.kind == "n":   # U
                    x = w.ftc; w.f.pop("seq"); w.f.pop("tgt", None); w.kind = "x"; w.forced = False
                    new = []
                    while True:
                        if kind[x] == "n":
                            t = mk(x, jump_to=ft[x], copy=True); t.forced = True; t.note = "U"
                            if not L.fit(t) or len(new) > 6: new.append(t); break
                            t = mk(x, copy=True); t.kind = "x"; t.note = "U"; new.append(t); x = ft[x]; continue
                        t = mk(x, copy=True); t.note = "U"; new.append(t)
                        if kind[x] == "e": break
                        x = ft[x]
                    ch[i + 1:i + 1] = new; log["U un-shared"] += 1; added["U"] += len(new); changed = True; continue
                if sq == "CALL" and isinstance(w.f.get("tgt"), tuple) and any(m in dly for m in st["proto"][w.f["tgt"][1]].members):   # C
                    t = st["proto"][w.f["tgt"][1]]
                    e = lib.Word({}, 0, w.members, copy=True); e.kind = "h"; e.note = "C"
                    if t.seq() != "RET": e.f["seq"] = SEQV["CALL"]; e.f["tgt"] = ("cls", t.ftc)
                    else: e.kind = "x"
                    w.f.pop("seq"); w.f.pop("tgt"); w.kind = "x"
                    ch.insert(i + 1, e); log["C the delay call moved to an empty word behind"] += 1; added["C"] += 1; changed = True; continue
                native.append((w, r)); i += 1
        if not changed: break
    ws = lib.flat(chains); L = layout.Layout(ws)
    # addresses, then every word encoded and decoded
    a = 0; at = {}
    for ch in chains:
        for w in ch:
            w.addr = a; a += 1
            if not w.copy and w.cls is not None: at[w.cls] = w.addr
    assert all(st["proto"][c].members for c in at)
    for w in ws:
        t = w.f.get("tgt")
        if isinstance(t, tuple): w.f["tgt"] = at[t[1]]
    L = layout.Layout(ws)
    ok = 0; bad = []
    for w in ws:
        r = L.fit(w)
        if r: bad.append((w, r)); continue
        layout.check_roundtrip(L, w); ok += 1
    print(f"\n== {name}: {base_words} words after sharing; before the ways out {sum(first.values())} do not fit:")
    for r, n in first.most_common(): print(f"      {n:4}  {r}")
    print(f"   ways out applied: {dict(log)}; stored words added: {dict(added)} = {sum(added.values())}")
    print(f"   final: {len(ws)} words ({'under' if len(ws) <= 2048 else 'OVER'} 2,048); encoded and decoded back: {ok}; do not fit: {len(bad)}")
    for D in (L.X, L.Y): print(f"   table {D.name}: {D.distinct} distinct payloads, {D.used} entries used of {D.size * D.ncls}; lost to full pages {dict(D.lost)}")
    print("   words by form:", dict(collections.Counter(layout.context(w) for w in ws)))
    hj = sum(1 for w in ws if layout.held(w) and w.seq() == "JMP")
    kwf = [w for w in ws if layout.KW_MEMBERS.intersection(w.members)]
    print(f"   arming words of an unarmed write: {len(kwf)}, in form N with the early KW bit: {sum(1 for w in kwf if layout.context(w) == 'N' and L.early(L.encode(w))['kw'])}")
    print(f"   words with a target: {sum(1 for w in ws if layout.has_tgt(w.f))}; jumps forced by sharing {sum(1 for w in ws if w.forced)}; hold words {sum(1 for w in ws if layout.held(w))} (hold with a jump {hj})")
    for w, r in bad:
        print(f"   NOT FITTING {w.where()} [{r}]: {lib.show({k: v for k, v in w.f.items() if k != 'tgt'}, w.hold)}  routines: {', '.join(w.routines[:6])}")
    return chains, ws, bad, L
if __name__ == "__main__":
    print("take-entry codes (TKI0 / TKI1):", "on" if layout.TKI_CODES else "off", "; way out (a), the three source edits:", "on" if os.environ.get("A", "1") == "1" else "off")
    run("PT (tail sharing)", False)
    run("PH (tail sharing + hold counts)", True)
