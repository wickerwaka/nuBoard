"""Our word against the V20's word shape: transfers per word, the three word types, the
target field. Read-only.  usage: PYTHONPATH=host/src:. python3 format_stats.py"""
import collections, math
from validation.v35s.chains import uasm
p = uasm.assemble(share=False); F = uasm.FIELDS
E = {k: {v: n for n, v in d.items()} for k, (w, d) in uasm.ENUMS.items()}
SR = E["v35_src_e"]; SQ = E["v35_seq_e"]
W = [x for r, x in p.words]; n = len(W)
RT = [r for r, x in p.words]
g = lambda x, k: x.fields.get(k, 0)
def transfers(x):
    """V20-style transfers the word needs: each move, the register write, each ALU operand that
    is not already a temporary (the V20's ALU reads tmpa / tmpb / tmpc only)."""
    t = 0
    if g(x, "d1"): t += 1
    if g(x, "d2"): t += 1
    if g(x, "wr"): t += 1
    if g(x, "alu"):
        for k in ("ax", "ay"):
            s = SR[g(x, k)]
            if s in ("SR_RA", "SR_RB", "SR_IMM", "SR_IMM8", "SR_OPR", "SR_PSW", "SR_VEC", "SR_DISP", "SR_ADDR", "SR_PC", "SR_SIG"): t += 1
    return t
c = collections.Counter(transfers(x) for x in W)
print("V20-style transfers per word:", sorted(c.items()))
print("  words needing more than two:", sum(v for k, v in c.items() if k > 2))
# the three types
def tA(x): return bool(g(x, "alu") or g(x, "cnt"))
def tJ(x): return SQ[g(x, "seq")] not in ("SQ_NEXT", "SQ_DISP", "SQ_RET", "SQ_TRAP")
def tB(x): return bool(g(x, "bus") or g(x, "seg") or g(x, "ea") or g(x, "pfx") or g(x, "susp") or g(x, "flush") or g(x, "halt") or g(x, "vk") or g(x, "ist"))
c = collections.Counter((tA(x), tJ(x), tB(x)) for x in W)
print("word types (ALU, jump with target, bus/control):")
for k, v in sorted(c.items(), key=lambda kv: -kv[1]): print(f"  {v:5}  {'+'.join(nm for nm, on in zip(('ALU','JMP','BUS'), k) if on) or '(none)'}")
print("  words using two or three types:", sum(v for k, v in c.items() if sum(k) > 1))
dly = p.routine("dly"); d0 = dly.base
isdly = lambda x: SQ[g(x, "seq")] == "SQ_CALL" and d0 <= g(x, "tgt") < d0 + 24
c2 = collections.Counter((tA(x), tJ(x) and not isdly(x), tB(x)) for x in W)
print("  ... not counting calls into the shared delay as jumps:", sum(v for k, v in c2.items() if sum(k) > 1), dict((('+'.join(nm for nm, on in zip(('ALU','JMP','BUS'), k) if on)), v) for k, v in c2.items() if sum(k) > 1))
# targets
base = {}; a = 0
for r in p.routines:
    for k in range(len(r.words)): base[r.base + k] = r
loc = far = 0; dist = []; fart = collections.Counter(); kinds = collections.Counter()
for i, x in enumerate(W):
    if not tJ(x): continue
    t = g(x, "tgt"); kinds[SQ[g(x, "seq")]] += 1
    if isdly(x): kinds["(call into dly)"] += 1; continue
    if base.get(t) is RT[i]: loc += 1; dist.append(t - i)
    else: far += 1; fart[t] += 1
print("jump-type words:", dict(kinds))
print(f"targets (not dly): inside the routine {loc}, in another routine {far} ({len(fart)} distinct far targets -> {math.ceil(math.log2(max(2,len(fart))))} bits as an index)")
for b in (3, 4, 5, 6):
    lim = 1 << (b - 1)
    print(f"   local jumps reachable with a {b}-bit signed displacement: {sum(1 for d in dist if -lim <= d < lim)} of {loc}")
print("   distinct targets overall:", len(set(g(x, 'tgt') for x in W if tJ(x))))
# register read used only for the EA add
print("ea=BI words:", sum(1 for x in W if E['v35_ea_e'][g(x,'ea')] == 'EA_BI'), " displacement pops:", sum(1 for x in W if E['v35_pop_e'][g(x,'pop')] in ('PP_DL','PP_DH')),
      " immediate pops:", sum(1 for x in W if E['v35_pop_e'][g(x,'pop')] in ('PP_IL','PP_IH')), " other pops:", sum(1 for x in W if E['v35_pop_e'][g(x,'pop')] in ('PP_MODRM','PP_PORT','PP_RD')))
# release against pop
pw = [x for x in W if g(x, "pop")]; 
print("pop words:", len(pw), " of them releasing on the same word (rl 1/2):", sum(1 for x in pw if g(x, "rl") in (1, 2)), " rl=x:", sum(1 for x in pw if g(x,'rl')==3), " no release:", sum(1 for x in pw if not g(x,'rl')))
print("words with rl 1/2 and no pop:", sum(1 for x in W if g(x, 'rl') in (1, 2) and not g(x, 'pop')), " rl=x words:", sum(1 for x in W if g(x,'rl')==3), " ro words:", sum(1 for x in W if g(x,'ro')), " e words:", sum(1 for x in W if g(x,'e')), " ro without e:", sum(1 for x in W if g(x,'ro') and not g(x,'e')), " e without ro:", sum(1 for x in W if g(x,'e') and not g(x,'ro')))
# bits under a typed word with the present encodings
GW = {nme: w for nme, t, w in F}
com = ["ra","rb","wr","ws","wid","d1","s1","d2","s2","pop","e","f","nb","ro","rl","bi","wf"]
A = ["alu","ax","ay","cnt"]; J = ["seq","cond","tgt"]; B = ["ea","bus","seg","pfx","susp","flush","halt","vk","ist"]
print("present encodings: common", sum(GW[k] for k in com), "ALU payload", sum(GW[k] for k in A), "jump payload", sum(GW[k] for k in J), "bus payload", sum(GW[k] for k in B))
# DISP words
dw = [x for x in W if SQ[g(x, "seq")] == "SQ_DISP"]
DP = ("ra","rb","wr","ws","d1","s1","d2","s2","alu","ax","ay","wf","ea","bus","seg","cnt","pop")
print("DISP (post-E) words:", len(dw), " with no act at all:", sum(1 for x in dw if not any(g(x, k) for k in DP)), " wholly empty but seq:", sum(1 for x in dw if not any(v for k, v in x.fields.items() if k != 'seq')))
