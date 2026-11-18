"""Size of the generated tables X and Y as LUT4 logic: an estimate, not a synthesis run.
Each output bit is decomposed on the address bits from the top (Shannon); a cofactor of four
address bits is one LUT4, a two-way select between different cofactors is one LUT4; equal
sub-functions are shared across outputs; constants are free. The codes are taken as the
generator assigns them (not optimised). Depth = the select levels + 1.
usage: python3 -B table_cost.py > table_cost.txt"""
import lib, layout
import fit_shared as FS
def est(rows, nbits, obits):
    """rows: list of 2^nbits ints"""
    memo = {}; cnt = {"leaf": 0, "mux": 0}; depth = 0
    def node(vec, lvl):
        if all(v == vec[0] for v in vec): return ("c", vec[0]), 0
        if vec in memo: return memo[vec]
        if len(vec) <= 16:
            cnt["leaf"] += 1; memo[vec] = (("l", len(memo)), 1); return memo[vec]
        h = len(vec) // 2; a, da = node(vec[:h], lvl + 1); b, db = node(vec[h:], lvl + 1)
        if a == b: memo[vec] = (a, da); return memo[vec]
        cnt["mux"] += 1; memo[vec] = (("m", len(memo)), max(da, db) + 1); return memo[vec]
    for o in range(obits):
        vec = tuple((r >> o) & 1 for r in rows)
        _, d = node(vec, 0); depth = max(depth, d)
    return cnt["leaf"], cnt["mux"], depth
def pack(p, names):
    v = 0
    for a, x in zip(names, p or [0] * len(names)): v = (v << layout.FW[a]) | x
    return v
def report(name, ws):
    L = layout.Layout(ws)
    xr = [pack(p, layout.XF) for p in L.X.tab[0]]
    yr = [pack(p, layout.YF) for k in (0, 1) for p in L.Y.tab[k]]
    lx = est(xr, 8, layout.XBITS); ly = est(yr, 9, layout.YBITS)
    print(f"{name}: X 256 x {layout.XBITS} ({L.X.used} entries used): {lx[0]} + {lx[1]} = {lx[0] + lx[1]} LUT4, depth {lx[2]};  Y 512 x {layout.YBITS} ({L.Y.used} used): {ly[0]} + {ly[1]} = {ly[0] + ly[1]} LUT4, depth {ly[2]};  both {sum(lx[:2]) + sum(ly[:2])} LUT4")
if __name__ == "__main__":
    pass  # (fit_shared applies way out (a) on import)
    report("present ROM", lib.flat(lib.present()))
    import io, contextlib
    for nm, h in (("after tail sharing", False), ("after tail sharing + hold counts", True)):
        with contextlib.redirect_stdout(io.StringIO()): chains, ws, bad, L = FS.run(nm, h)
        report(nm + " and the ways out", ws)
