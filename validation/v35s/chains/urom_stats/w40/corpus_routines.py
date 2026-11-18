"""Which routines the corpus enters: every instruction of every chain run in
build/validation/v35s/corpus/chains-*.json (its `instrs[].code`), mapped by its opcode
(prefixes skipped; REP and 0F pages; the ModR/M byte) to the routine of its decode cell.
Case-type files (p2-*, no instruction list) are not counted. Read-only.
usage: python3 -B corpus_routines.py > corpus_routines.txt"""
import collections, glob, json, sys
import lib
P = lib.P; U = lib.uasm
SEG = set(U.SEG_PREFIX); REP = set(U.REP_XC)
def routine(code):
    b = list(bytes.fromhex(code)); i = 0; rep = None
    while i < len(b) and (b[i] in SEG or b[i] in REP or b[i] == 0xF0):
        if b[i] in REP: rep = b[i]
        i += 1
    if i >= len(b): return None
    op = b[i]; nx = b[i + 1] if i + 1 < len(b) else None
    if rep is not None and (rep, op) in P.cells2: return P.cells2[(rep, op)]
    if op == 0x0F and nx is not None: return P.cells2.get((0x0F, nx))
    if op in P.cells1: return P.cells1[op]
    if nx is not None: return P.cells2.get((op, nx))
    return None
runs = collections.Counter(); files = 0; nrun = 0
for f in sorted(glob.glob("build/validation/v35s/corpus/chains-*.json")):
    try: d = json.load(open(f))
    except Exception: continue
    files += 1
    for r in d.get("runs", []):
        c = r.get("chain") or {}; seen = set(); nrun += 1
        for ins in c.get("instrs", []):
            if ins.get("role") in ("pad", "end"): continue
            try: nm = routine(ins.get("code", ""))
            except Exception: nm = None
            if nm: seen.add(nm)
        for nm in seen: runs[nm] += 1
print(f"chain files {files}, runs {nrun}; routines entered by an instruction of a run: {len(runs)} of {len(P.routines)}")
for nm, n in sorted(runs.items(), key=lambda kv: -kv[1]): print(f"{n:6}  {nm}")
