"""Routine inventory: file, name, header selectors, words, acting words, dly clocks. Read-only."""
import collections, sys
from validation.v35s.chains import uasm
p = uasm.assemble()
sq = {v: k[3:] for k, v in uasm.ENUMS["v35_seq_e"][1].items()}
DP = ("ra","rb","wr","ws","d1","s1","d2","s2","alu","ax","ay","wf","ea","bus","seg","cnt","pop")
dly = p.routine("dly"); d0 = dly.base
for r in p.routines:
    act = sum(1 for w in r.words if any(w.fields.get(k,0) for k in DP))
    dck = sum(d0+24-w.fields.get("tgt",0) for w in r.words if sq[w.fields.get("seq",0)]=="CALL" and d0<=w.fields.get("tgt",0)<d0+24)
    h = r.head
    sel = " ".join(f"{k}={h[k]}" for k in ("op","mod","reg","rm","page","ea","rep") if k in h)
    print(f"{r.path:14} {r.name:18} w={len(r.words):3} act={act:3} dly={dck:3}  {sel}  book={h.get('book','')!r}")
