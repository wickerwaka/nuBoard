"""The words of the present ROM that do not fit L40 (no way out applied: 20), and what clears
each one after tail sharing (PT) and after tail sharing with hold counts (PH).
usage: python3 -B resolve.py > resolve.txt"""
import collections, io, contextlib, re, lib, layout
layout.TKI_CODES = False
ws0 = lib.flat(lib.present()); L0 = layout.Layout(ws0)
bad = [(w.members[0], L0.fit(w), dict(w.f)) for w in ws0 if L0.fit(w)]
layout.TKI_CODES = True
import fit_shared as FS            # applies way out (a) (three source edits)
cov = {}
try:
    for line in open("/tmp/claude-1000/-home-wickerwaka-src-nuBoard/b9107762-85c1-4fee-8904-bf25a28b914c/scratchpad/v2/urom-w40/corpus_routines.txt"):
        m = re.match(r"\s*(\d+)\s+(\w+)$", line)
        if m: cov[m.group(2)] = int(m.group(1))
except OSError: pass
res = {}
for nm, h in (("PT", False), ("PH", True)):
    with contextlib.redirect_stdout(io.StringIO()): chains, ws, b, L = FS.run(nm, h)
    for ch in chains:
        for k, w in enumerate(ch):
            if w.copy: continue
            nxt = ch[k + 1] if k + 1 < len(ch) else None
            for i in w.members:
                how = []
                q = w.seq()
                if q == "TKI": how.append("d: take-entry code")
                if nxt is not None and nxt.note == "U": how.append("U: runs on into a copy of the shared word (+%d)" % sum(1 for x in ch[k + 1:k + 8] if x.note == "U" and x.copy))
                if nxt is not None and nxt.note == "S": how.append("S: count on an empty word behind (+1)")
                if nxt is not None and nxt.note == "C": how.append("a: the delay call on an empty word behind (+1)")
                if w.hold: how.append(f"hold count {w.hold} in the word (form {layout.context(w)})")
                res[(nm, i)] = (layout.context(w), q, how)
edits = {(lib.P.routine(n).base + k): how for n, k, how in lib.A_EDITS}
print(f"{'word':16} {'runs':>5}  conflict / way out")
tally = collections.Counter()
for i, r, f in bad:
    R = lib.R0[i]; nm = f"{R.name}+{i - R.base}"
    print(f"{nm:16} {cov.get(R.name, 0):5}  {lib.show({k: v for k, v in f.items() if k != 'tgt'})}   [{r.split(':')[0]}]")
    for p in ("PT", "PH"):
        c, q, how = res[(p, i)]
        if i in edits: how = ["a: the act " + ("moved to the empty word behind" if edits[i] == "move" else "dropped (the words before and behind make the same load)")] + how
        if not how: how = ["placement: the word falls through into its successor (its jump is gone)" if q == "NEXT" else f"fits as form {c}"]
        print(f"{'':24}{p}: {'; '.join(how)}")
        if p == "PH": tally[how[0].split(':')[0]] += 1
print("\nfirst way out per word (PH):", dict(tally))
print("runs = corpus chain runs with an instruction that enters the routine (corpus_routines.py); 0: not entered by a corpus instruction (brkcs: BRKCS; si_first: a REP string's interrupt entry)")
