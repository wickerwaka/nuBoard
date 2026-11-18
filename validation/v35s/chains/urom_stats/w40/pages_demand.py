"""Demand on the short-code pages of layout L40 per form, and the RET / TRAP words.\nusage: python3 -B pages_demand.py > pages_demand.txt"""
import collections, lib, layout
for name, ws in (("P0", lib.flat(lib.present())), ("PT", lib.flat(lib.shared(False)[0])), ("PH", lib.flat(lib.shared(True)[0]))):
    for c in ("R", "RH", "NT", "NH"):
        v = [w for w in ws if layout.context(w) == c and layout.nz(layout.xp(w.f)) and (layout.nz(layout.yp(w.f)) or c in ("NT", "RH"))]
        vy = [w for w in ws if layout.context(w) == c and layout.nz(layout.yp(w.f)) and (layout.nz(layout.xp(w.f)) or c in ("NT", "RH"))]
        xs = set(layout.xp(w.f) for w in v); y0 = set(layout.yp(w.f) for w in vy if not layout.posts(w.f)); y1 = set(layout.yp(w.f) for w in vy if layout.posts(w.f))
        print(f"{name} {c:3}: words needing a short X {len(v):4} (distinct {len(xs):3}); short Y {len(vy):4} (distinct no-post {len(y0):3}, post {len(y1):3})")
    r = [w for w in ws if layout.sq(w.f) in ("RET", "TRAP")]
    print("   RET/TRAP words:", collections.Counter((layout.sq(w.f), layout.context(w), layout.nz(layout.xp(w.f)), layout.nz(layout.yp(w.f))) for w in r))
