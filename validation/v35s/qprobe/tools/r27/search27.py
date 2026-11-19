"""search27.py SUBJECT [MAXLEN]: offline search (the reading model only, nothing is run) for lead-ins that put a fetch
on a late clock of the subject: every sequence of up to MAXLEN fillers behind JMP $+2 or the long shift, both
alignments, fetch cycles of 3 .. 21 clocks. Prints, per lead, the latest clock (from the subject's boundary) on
which a fetch cycle that started inside the subject is still in flight before the next opcode's release."""
import sys, itertools, collections, re
sys.path[:0] = ["host/src", "."]
from validation.v35s.chains.families import make_chain
from validation.v35s.chains.image import build_image
from validation.v35s.qprobe import gen, gen_r27 as G, model_m as M

subj = sys.argv[1]; maxlen = int(sys.argv[2]) if len(sys.argv) > 2 else 3
loads, code, regs, awv, blv = G.S_SUBJ[subj]
POOL = {"n": [0x90], "c": [0xF8], "r": [0x8B, 0xC0], "t": [0x84, 0xC3], "2": G.bl(blv), "3": G.aw(awv),
        "a": [0x05, 0x00, 0x00], "p": [0x26, 0x8B, 0xC0], "x": [0x93, 0x93], "i": [0x45], "o": [0xE6, 0x22], "u": [0x50]}
POOL = {k: v for k, v in POOL.items() if v[0] in M.OPS or v[0] in (0x8B, 0x84, 0x26)}
best = collections.defaultdict(list)
for head, hc in (("j", [G.J0]), ("q", [G.QUIET])):
    for n in range(0, maxlen + 1):
        for seq in itertools.product(POOL, repeat=n):
            name = head + "".join(seq)
            body = [gen.q(c, "i") for c in loads + hc + [POOL[k] for k in seq] + [code]]
            for p in ("even", "odd"):
                for L in (3, 4, 5, 6, 8, 10, 12, 16, 21):
                    c = make_chain("QPs", name, {}, gen.frame(body, G.OUTW), 2, p, regs={**gen.REGS, **regs})
                    b = build_image(c)
                    run = {"chain": {**c.to_json(), "waits": L - 3}, "code_hex": b.code.hex(), "chain_base": b.chain_base}
                    log = []
                    try:
                        ev = M.simulate(run, M.DEFAULT, log=log)
                    except Exception as e:
                        continue
                    es = [(t, txt) for t, txt in log if re.match(r"E\d+ ", txt)]
                    ke = next((i for i, (t, txt) in enumerate(es) if " E7@" in txt), None)
                    if ke is None:
                        continue
                    e0, e1 = es[ke - 1][0], es[ke][0]
                    fs = [t - e0 for t, k, wh in ev if k == "F" and e0 < t < e1 - 3]
                    if fs and max(fs) >= 6:
                        best[max(fs)].append(f"{name}/p{p[0].upper()}/L{L}:{'+'.join(map(str, fs))}")
for k in sorted(best):
    print(k, len(best[k]), " ".join(best[k][:12]))
print("fillers:", " ".join(POOL))
