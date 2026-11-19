"""Class by class: the V20's ROM words against ours. Read-only.
usage: PYTHONPATH=host/src:.:<this dir> python3 class_table.py"""
import collections, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v20_stats as V
from validation.v35s.chains import uasm
p = uasm.assemble(share=False)
sq = {v: k[3:] for k, v in uasm.ENUMS["v35_seq_e"][1].items()}
DP = ("ra","rb","wr","ws","d1","s1","d2","s2","alu","ax","ay","wf","ea","bus","seg","cnt","pop")
KIND = ("e","f","nb","bi","vk","flush","pop","rl","ro")
dly = p.routine("dly"); d0 = dly.base
NAMED = {"dly":"shared delay","sxt":"shared delay","str_b":"shared delay","rep_z":"strings","rep_brk":"strings",
 "bsw":"V35 only","msv":"V35 only","dmv":"V35 only","dm_q":"V35 only","intr":"V35 only","iot":"V35 only",
 "si_first":"V35 only","si_cmp":"V35 only","bf_pass":"0F bit fields","ext_xq_body":"0F bit fields",
 "adjb_ei_tail":"adjust / convert","reset":"misc","trap":"misc","trapm":"misc","trap0f":"misc","trap0fm":"misc"}
def rclass(r):
    h = r.head
    if r.name in NAMED: return NAMED[r.name]
    if r.path == "ea.uasm": return "EA heads"
    if "op" not in h: return "misc"
    ops = uasm._ranges(h["op"]); page = h.get("page")
    reg = None
    if "reg" in h: reg = uasm._ranges(h["reg"])[0]
    c = collections.Counter(V.klass(page, o, reg) for o in ops)
    return c.most_common(1)[0][0]
def is_modevariant(r): return r.head.get("mod") in ("m00", "m01", "m10")
def is_mem(r): return r.head.get("mod") in ("mem", "m00", "m01", "m10")
def main():
    per = collections.defaultdict(collections.Counter)
    for r in p.routines:
        k = rclass(r); c = per[k]; c["routines"] += 1; c["words"] += len(r.words)
        if is_modevariant(r): c["modevar"] += len(r.words); c["modevar_r"] += 1
        if is_mem(r): c["memwords"] += len(r.words)
        for w in r.words:
            f = w.fields; s = sq[f.get("seq", 0)]; t = f.get("tgt", 0)
            act = any(f.get(x, 0) for x in DP)
            isdly = s == "CALL" and d0 <= t < d0 + 24
            if isdly: c["dlyck"] += d0 + 24 - t
            if act: c["act"] += 1
            elif any(f.get(x, 0) for x in KIND): c["kind"] += 1
            elif isdly: c["call"] += 1
            elif s != "NEXT": c["seq"] += 1
            else: c["empty"] += 1
    B = V.parse(); v20 = collections.defaultdict(lambda: [0, 0])
    for b in B:
        k = V.block_class(b); v20[k][0] += 4; v20[k][1] += sum(1 for w in b["words"] if not V.wparse(w)["empty"])
    keys = sorted(set(per) | set(v20), key=lambda k: -per[k]["words"])
    print(f"{'class':26} {'V20rows':>7} {'V20used':>7} | {'ours':>5} {'rout':>4} {'act':>4} {'kind':>4} {'seq':>4} {'call':>4} {'empty':>5} {'dlyck':>5} | {'memform':>7} {'by-mode':>7} {'ratio':>5}")
    T = collections.Counter()
    for k in keys:
        c = per[k]; a, u = v20[k]
        ratio = f"{c['words']/u:5.1f}" if u and c["words"] else "    -"
        print(f"{k:26} {a:7} {u:7} | {c['words']:5} {c['routines']:4} {c['act']:4} {c['kind']:4} {c['seq']:4} {c['call']:4} {c['empty']:5} {c['dlyck']:5} | {c['memwords']:7} {c['modevar']:7} {ratio}")
        T.update(c); T["v20a"] += a; T["v20u"] += u
    print(f"{'total':26} {T['v20a']:7} {T['v20u']:7} | {T['words']:5} {T['routines']:4} {T['act']:4} {T['kind']:4} {T['seq']:4} {T['call']:4} {T['empty']:5} {T['dlyck']:5} | {T['memwords']:7} {T['modevar']:7}")
    if "-v" in sys.argv:
        for r in p.routines: print(rclass(r), r.name)

if __name__ == '__main__':
    main()
