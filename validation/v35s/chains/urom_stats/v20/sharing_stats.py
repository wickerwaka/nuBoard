"""Opcodes per routine and routines per opcode, ours against the V20's. Read-only.
usage: PYTHONPATH=host/src:.:<this dir> python3 sharing_stats.py"""
import collections, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v20_stats as V
from validation.v35s.chains import uasm
p = uasm.assemble(share=False)
per_op = collections.defaultdict(set)
for op, nm in p.cells1.items(): per_op[op].add(nm)
for (op, b), nm in p.cells2.items():
    if isinstance(op, int) and op < 256: per_op[op].add(nm)
keys = set(type(k) for k in p.cells1) | set(type(k[0]) for k in p.cells2)
trap = {"trap", "trapm", "trap0f", "trap0fm"}
n_r = collections.Counter(len(v - trap) for v in per_op.values())
print("ours: first-byte opcodes with cells:", len(per_op), " key types:", keys)
print("ours: routines entered per first-byte opcode (traps apart):", sorted(n_r.items()))
top = sorted(((len(v - trap), f"{k:02X}") for k, v in per_op.items()), reverse=True)[:16]; print("   most:", top)
ops_of = collections.defaultdict(set)
for op, v in per_op.items():
    for nm in v: ops_of[nm].add(op)
c = collections.Counter(len(v) for nm, v in ops_of.items() if nm not in trap)
print("ours: first-byte opcodes served per routine:", sorted(c.items()), " routines with an opcode:", sum(c.values()))
# cells of ModR/M opcodes: how many distinct routines over the 256 ModR/M bytes
B = V.parse()
nat = [b for b in B if b["grp"] in ("00?", "000", "001") and b["step"] == "00"]
ent = collections.defaultdict(int)
for b in nat:
    for o in V.expand(b["opc"]): ent[o] += 1
grp = {0xF6: "010", 0xF7: "010", 0xFE: "011", 0xFF: "011"}
for o, g in grp.items(): ent[o] = len([b for b in B if b["grp"] == g and b["step"] == "00"])
print("V20: entry blocks per first-byte opcode:", sorted(collections.Counter(ent.values()).items()))
print("V20: entry blocks: native", len(nat), " F6/F7", len([b for b in B if b['grp']=='010' and b['step']=='00']), " FE/FF", len([b for b in B if b['grp']=='011' and b['step']=='00']), " 0F", len([b for b in B if b['grp']=='100' and b['step']=='00']), " internal", len(set(b['opc'] for b in B if b['grp']=='111')), " 8080", len([b for b in B if b['grp'] in ('101','110') and b['step']=='00']))
ours_entry = [r for r in p.routines if "op" in r.head]
print("ours: routines with an opcode header:", len(ours_entry), " without (heads, shared tails, service):", len(p.routines) - len(ours_entry))
by = collections.Counter(r.head.get("mod", "-") for r in ours_entry); print("ours: routines by mod= selector:", dict(by))
