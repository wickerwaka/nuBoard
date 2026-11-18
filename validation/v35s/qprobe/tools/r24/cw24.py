"""cw24.py RUN_ID... [K=V ...] [-w N] [-a]: corpus runs (exact ids; the family is the id's first field): the chain,
silicon's and the model's events (run clocks) and the model's word log for N clocks around the first
divergence (-a: from the first marker)."""
import sys, json, importlib.util
sys.path[:0] = ["host/src", "."]
T = "/home/wickerwaka/src/nuBoard/validation/v35s/qprobe/tools/corpus_model.py"
spec = importlib.util.spec_from_file_location("cm", T); cm = importlib.util.module_from_spec(spec); spec.loader.exec_module(cm)
from validation.v35s.chains.normalize import load_runs, normalize
M = cm.model_m
OFF = json.load(open("/tmp/claude-1000/-home-wickerwaka-src-nuBoard/b9107762-85c1-4fee-8904-bf25a28b914c/scratchpad/tools/out/offsets.json"))
_cache = {}
def get(rid):
    fam = rid.split("-")[0]
    if fam not in _cache:
        _cache[fam] = {r["chain"]["id"]: r for r in load_runs(fam, (0, 1, 2))}
    return _cache[fam][rid]
def both(r, o):
    ch = r["chain"]; s = normalize(r); si, _ = cm.silicon_events(s)
    d = OFF.get(cm.group_of(ch), 0); body = r["chain_base"] + cm.ls_end(ch)
    oo = dict(o); oo["WLOG"] = []
    mo, blog, hist = cm.model_events(r, oo, d, si[-1][0] - d + 40, body)
    return si, mo, oo["WLOG"], d, blog, hist
def fm(ev, base):
    return " ".join(f"{c}:{format(wh - base, '+d') if k == 'F' else k}" for c, k, wh in ev)
if __name__ == "__main__":
    argv = sys.argv[1:]; n = 14; allw = False
    if "-w" in argv:
        k = argv.index("-w"); n = int(argv[k + 1]); del argv[k:k + 2]
    if "-a" in argv:
        argv.remove("-a"); allw = True
    key = None
    if "-k" in argv:
        k = argv.index("-k"); key = argv[k + 1]; del argv[k:k + 2]
    ids = [a for a in argv if "=" not in a]
    o = M.options([a for a in argv if "=" in a])
    for rid in ids:
        r = get(rid); ch = r["chain"]
        si, mo, wl, d, blog, hist = both(r, o)
        base = r["chain_base"] + cm.ls_end(ch)
        fd = cm.first_div(si, mo)
        print(rid, "=" if fd is None else "X " + fd[3], "|", " ".join(f"{i['form']}:{i['code']}" for i in ch["instrs"])[:400])
        k = fd[0] if fd else len(si)
        lo = max(0, k - 6)
        print("  si", fm(si[lo:k + 4], base)); print("  mo", fm(mo[lo:k + 4], base))
        c = (si[k][0] if k < len(si) else mo[k][0]) if fd else si[-1][0]
        if key:
            c = next((t + d + n - 4 for t, at, ip, acts, stall, is_last in wl if f"{ip}{acts}" == key), c)
            print("  SI", fm([e for e in si if c - n - 8 <= e[0] <= c + 12], base)); print("  MO", fm([e for e in mo if c - n - 8 <= e[0] <= c + 12], base))
        s = []
        for t, at, ip, acts, stall, is_last in wl:
            if (c - n <= t + d <= c + 3) or allw:
                s.append(f"{t + d}:{ip}{acts or '.'}{'*' if stall else ''}{'|' if is_last and not stall else ''}q{hist.get(t)}")
        print("  wl", " ".join(s)[:1500])
