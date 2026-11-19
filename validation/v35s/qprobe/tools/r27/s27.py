"""s27.py ROUND [SUBSTR...] [--src DIR] [-v] [-m]: the stall-map runs against the reading model (model_m, as a ruler only).

Per run: the fetch cycle L in clocks (measured: the ticks between two back-to-back fetch starts over the run's
ticks per clock), the trace rescaled to 8 ticks a clock and the model run with waits = L - 3 (its pin cycle is
3 + waits; the model has no READY, a READY-held cycle is to it a cycle of L clocks). The model's strip is laid on
silicon's by its first event (the frame's start clock is not modelled for long cycles), then compared event by
event to the marker's own cycle. Columns: L; `=` exact or the marker's clock silicon - model (and the first
differing event with -v); len = the subject's boundary to the next boundary in the model; then the fetch cycles
that overlap the subject, as first..last clock counted from the subject's boundary clock (clock 0 = the boundary
word; the subject's first word is clock 1 when nothing waits).
-m: one line per (subject, lead, alignment) with the L's that are exact / not."""
import sys, json, re, collections, copy
sys.path[:0] = ["host/src", ".", "build/qp"]
from pathlib import Path
from validation.v35s.qprobe import read, model_m as M

TPC = {0x4C: 8, 0x4D: 16, 0x4E: 32}


def load(d, rnd):
    runs = {}
    for p in sorted(Path(d).glob(f"QP{rnd}-w*.json")):
        for r in json.loads(p.read_text())["runs"]:
            runs[r["chain"]["id"]] = r
    return runs


def rescale(run):
    """(run with the trace in 8-tick clocks and waits = L - 3, L, ticks per clock)"""
    tpc = TPC[run["chain"]["prc"]]
    t = run["socket_trace"]
    k = next(i for i, x in enumerate(t) if x["flags"] & 2 and x["address"] & 0xFFFF == 0x21)
    f = [x for x in t[k + 1:] if x["flags"] & 1 and not x["flags"] & 6]
    gap = min(b["start"] - a["start"] for a, b in zip(f, f[1:]))
    L = gap / tpc
    if abs(L - round(L)) > 0.2:
        raise ValueError(f"cycle of {L} clocks")
    L = round(L)
    r = copy.deepcopy(run)
    t0 = t[k]["start"]
    for x in r["socket_trace"]:
        for key in ("start", "end"):
            x[key] = t0 + (x[key] - t0) * 8 / tpc
    r["chain"]["waits"] = L - 3
    return r, L, tpc


def cut(ev):
    out = []
    for e in ev:
        out.append(e)
        if e[1] == "O" and e[2] == 0x20:
            break
    return out


def one(run, o=M.DEFAULT):
    r, L, tpc = rescale(run)
    si = cut([(c, k, (wh if k in "FO" else None)) for c, k, wh in read.events(r)])
    log = []
    mo = cut(M.simulate(r, o, log=log))
    if len(mo) > len(si):
        return L, None, None, None, None, si, mo
    si = si[len(si) - len(mo):]
    s = si[0][0] - mo[0][0]
    mo = [(c + s, k, wh) for c, k, wh in mo]
    # the subject: the instruction in front of the marker (E7 20)
    es = [(t + s, txt) for t, txt in log if re.match(r"E\d+ ", txt)]
    ke = next(i for i, (t, txt) in enumerate(es) if " E7@" in txt)
    e0, e1 = es[ke - 1][0], es[ke][0]
    fet = [(c - e0, c - e0 + L - 1) for c, k, wh in si if k == "F" and c + L - 1 >= e0 and c <= e1]
    return L, si == mo, si[-1][0] - mo[-1][0], e1 - e0, fet, si, mo


if __name__ == "__main__":
    argv = sys.argv[1:]
    src = "build/validation/v35s/qprobe/socket"
    if "--src" in argv:
        k = argv.index("--src"); src = argv[k + 1]; del argv[k:k + 2]
    flags = {a for a in argv if a.startswith("-")}; argv = [a for a in argv if a not in flags]
    runs = load(src, argv[0])
    rows = collections.defaultdict(list)
    for cid, run in runs.items():
        if argv[1:] and not all(s in cid for s in argv[1:]):
            continue
        m = re.match(r"QP\w+?-([a-z0-9]+)-([a-z0-9]+)-(\w+)-p([EO])-w(\d)$", cid)
        lead, subj, tag, p, w = m.groups()
        try:
            res = one(run)
        except Exception as e:
            print(cid, "ERR", repr(e)[:80]); continue
        rows[(subj, lead, p)].append((res[0], tag + ("" if tag != "nat" else w), res))
    n = ok = 0
    for key, v in sorted(rows.items()):
        v.sort(key=lambda x: (x[0], x[1]))
        if "-m" in flags:
            good = [f"{L}" for L, tag, r in v if r[1]]
            bad = [f"{L}({r[2]:+d})" if r[2] is not None else f"{L}(?)" for L, tag, r in v if not r[1]]
            print(f"{key[0]:7} {key[1]:4} p{key[2]}: exact at L = {' '.join(good)}" + (f"; NOT at {' '.join(bad)}" if bad else ""))
        else:
            print(f"{key[0]} {key[1]} p{key[2]}")
        for L, tag, (L_, eq, d, ln, fet, si, mo) in v:
            n += 1; ok += bool(eq)
            if "-m" in flags:
                continue
            ft = " ".join(f"{a}..{b}" for a, b in fet) if fet is not None else "?"
            print(f"   L={L:2} {tag:5} {'=' if eq else ('X ' + (format(d, '+d') if d is not None else '?')):5} len={ln}  fetches {ft}")
            if "-v" in flags and not eq:
                k = next((i for i, (x, y) in enumerate(zip(si, mo)) if x != y), 0)
                print("        si", M.fmt(si[max(0, k - 2):k + 6])); print("        mo", M.fmt(mo[max(0, k - 2):k + 6]))
    print(ok, "/", n, "exact")
