"""Write the ROM after tail sharing + hold counts and the ways out, packed in layout L40:
rom_ph.lst (address, the 40-bit word, the form, the fields, the routines that share the word)
and tables_ph.txt (the generated X and Y tables). The same for tail sharing alone (rom_pt.lst).
usage: python3 -B dump_rom.py"""
import io, contextlib, lib, layout
import fit_shared as FS
OUT = "/tmp/claude-1000/-home-wickerwaka-src-nuBoard/b9107762-85c1-4fee-8904-bf25a28b914c/scratchpad/v2/urom-w40/"
for tag, nm, h in (("pt", "PT", False), ("ph", "PH", True)):
    with contextlib.redirect_stdout(io.StringIO()): chains, ws, bad, L = FS.run(nm, h)
    with open(OUT + f"rom_{tag}.lst", "w") as o:
        for w in ws:
            v = L.encode(w); f, hold, nbl = L.decode(v)
            o.write(f"{w.addr:04d} {v:010x} {layout.context(w):3} {'*' if w.copy else ' '}{w.note or ' '} {lib.show(w.f, w.hold)}{' nb_last' if w.f.get('nb_last') else ''}   ; {', '.join(w.routines[:4])}{' ...' if len(w.routines) > 4 else ''}\n")
    with open(OUT + f"tables_{tag}.txt", "w") as o:
        for D, names in ((L.X, layout.XF), (L.Y, layout.YF)):
            for k in range(D.ncls):
                o.write(f"table {D.name}{' half ' + str(k) + (' (posts)' if k else ' (no post)') if D.ncls > 1 else ''}: pages {D.pages}\n")
                for q, p in enumerate(D.tab[k]):
                    if p: o.write(f"  {q:3}  " + lib.show(dict(zip(names, p))) + "\n")
    print(tag, len(ws), "words written")
