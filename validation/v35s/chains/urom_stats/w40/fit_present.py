"""Run every word of the present ROM (P0) through layout L40: encode, decode, compare.
usage: python3 -B fit_present.py        (TKI=0: without the take-entry codes, way out d)"""
import collections, os, lib, layout
layout.TKI_CODES = os.environ.get("TKI", "1") == "1"
print("take-entry codes (TKI0 / TKI1):", "on" if layout.TKI_CODES else "off")
if os.environ.get("A") == "1": lib.apply_a_edits(); print("way out (a): the three source edits applied (lib.A_EDITS)")
ch = lib.present(); ws = lib.flat(ch)
L = layout.Layout(ws)
print(f"present ROM: {len(ws)} words in {len(ch)} routines")
for D, bits in ((L.X, layout.XBITS), (L.Y, layout.YBITS)): print(f"table {D.name}: {D.distinct} distinct payloads, {D.used} entries used of {D.size * D.ncls} ({D.percls} by half; pages duplicate some), {bits} bits an entry; lost to full pages: {dict(D.lost)}")
ctx = collections.Counter(); bad = []; kwmiss = []
for ch_ in ch:
    arm = False
    for w in ch_:
        c = layout.context(w); ctx[c] += 1
        r = L.fit(w)
        # the arming word of an unarmed write (bus=MEMWD ... the next word that loads OPRW) must carry KW
        if arm and layout.kw(w.f):
            if r or not L.early(L.encode(w))["kw"]: kwmiss.append(w)
            arm = False
        if w.f.get("bus") == lib.uasm.enum_value("v35_bus_e", "memwd"): arm = True
        if r: bad.append((w, r)); continue
        layout.check_roundtrip(L, w)
print("arming words of an unarmed write (MEMWD) without the early KW bit:", len(kwmiss))
print("words by form:", dict(ctx))
print(f"words that fit (encoded to 40 bits and decoded back to the same fields; targets taken modulo 2,048): {len(ws) - len(bad)}")
print(f"words that do not fit: {len(bad)}")
by = collections.Counter(r for w, r in bad)
for r, n in by.most_common(): print(f"   {n:3}  {r}")
print()
rt = collections.Counter()
for w, r in bad:
    i = w.members[0]; R = lib.R0[i]; x = lib.W0[i]
    rt[R.name] += 1
    print(f"{R.name}+{i - R.base} ({R.path}:{x.line})  [{r}]\n      {lib.show(w.f)}\n      ; {x.act[:110]}")
print("\nroutines with a word that does not fit:", len(rt), dict(rt))
