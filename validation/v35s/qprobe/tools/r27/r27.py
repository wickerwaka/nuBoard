"""r27.py ROUND [SUBJECT] [-v]: the refresh maps. A program is run with refresh off (-nat) and on (-rf, every 64 clocks).
Window = OUT 22h's I/O cycle to the marker's (OUT 20h). D0 / D = its length in clocks off / on; stretch = D - D0.
Per refresh cycle in the window: d = clocks from its start (/REFRQ low as the lane records it, rounded down to a clock)
to the marker's cycle start. The subject's boundary clock in the -nat run is the model's (model_m, a ruler; used only when
the model reproduces the -nat run exactly): dE clocks before the marker. A refresh's place is given as
i = dE - d + stretch: the clock of the subject (1 = its first word) on which the refresh cycle starts, counted in
the subject's own unstretched clocks; i <= 0 is the lead (the long shift, count k: its last clock is i = 0).
Output: for the runs with exactly one refresh in the window, per i the stretches seen (and how many runs)."""
import sys, json, re, collections, math
sys.path[:0] = ["host/src", ".", "build/qp"]
from pathlib import Path
from validation.v35s.qprobe import read, model_m as M

argv = sys.argv[1:]; flags = {a for a in argv if a.startswith("-")}; argv = [a for a in argv if a not in flags]
runs = {}
for rnd in argv[0].split(","):          # ROUND may be several, comma-separated: their runs are pooled per subject
    for p in sorted(Path("build/validation/v35s/qprobe/socket").glob(f"QP{rnd}-w*.json")):
        for r in json.loads(p.read_text())["runs"]:
            runs[r["chain"]["id"]] = r


GUARD = 16        # a refresh this many clocks or fewer in front of OUT 22h counts as in the window (it can move the lead)


def marks(run):
    t = run["socket_trace"]
    k = next(i for i, x in enumerate(t) if x["flags"] & 2 and x["address"] & 0xFFFF == 0x21)
    t0 = t[k]["start"]
    o22 = next(x["start"] for x in t[k:] if x["flags"] & 2 and x["address"] & 0xFFFF == 0x22)
    o20 = next(x["start"] for x in t[k:] if x["flags"] & 2 and x["address"] & 0xFFFF == 0x20)
    rf = [(x["start"], x["end"] - x["start"]) for x in t[k:] if x["flags"] & 4 and o22 - 8 * GUARD < x["start"] < o20]
    return t0, o22, o20, rf


def d_e(run):
    """clocks from the subject's boundary to the marker's cycle start in the -nat run, by the model; None if the model
    does not reproduce the run"""
    si = [(c, k, (wh if k in "FO" else None)) for c, k, wh in read.events(run)]
    log = []
    mo = M.simulate(run, M.DEFAULT, log=log)
    cut = lambda ev: ev[:next(i for i, e in enumerate(ev) if e[1] == "O" and e[2] == 0x20) + 1]
    mo = cut(mo); si = cut(si)[-len(mo):]
    if si != mo:
        return None
    es = [(t, txt) for t, txt in log if re.match(r"E\d+ ", txt)]
    ke = next(i for i, (t, txt) in enumerate(es) if " E7@" in txt)
    return mo[-1][0] - es[ke - 1][0], es[ke][0] - es[ke - 1][0]


tab = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
multi = collections.defaultdict(list)
info = collections.defaultdict(collections.Counter)
for cid, nat in runs.items():
    m = re.match(r"QP\w+?-(k\d+\w*?)-([a-z0-9]+)-nat-p([EO])-w(\d)$", cid)
    if not m:
        continue
    lead, subj, p, w = m.groups()
    if argv[1:] and subj not in argv[1:]:
        continue
    try:
        de = d_e(nat)
    except Exception as e:
        de = None
    info[subj]["programs"] += 1
    if de is None:
        info[subj]["-nat not model-exact (no place)"] += 1
        continue
    dE, ln = de
    info[subj][f"boundary to marker {dE}, to next boundary {ln}"] += 1
    t0, a0, b0, _ = marks(nat)
    for tag in ("rf", "rg"):
        on = runs.get(cid.replace("-nat-", f"-{tag}-"))
        if on is None:
            continue
        t1, a1, b1, rf = marks(on)
        D0, D = (b0 - a0) / 8, (b1 - a1) / 8
        st = D - D0
        ds = [(b1 - s_) / 8 for s_, n in rf]
        places = [dE - math.ceil(d) + st for d in ds]
        if "-v" in flags:
            print(f"{cid:34} {tag} D0={D0:g} D={D:g} stretch={st:+g} d={['%g' % d for d in ds]} len={[n for s_, n in rf]} i={places}")
        info[subj][f"{tag}: {len(rf)} refresh in the window"] += 1
        if len(rf) == 1:
            tab[subj][int(places[0])][st] += 1
        elif len(rf) == 0:
            info[subj][f"{tag}: none, stretch {st:+g}"] += 1
        else:
            multi[subj].append((places, st, ds, dE))
for subj in info:
    t = tab[subj]
    print(f"{subj}: " + "; ".join(f"{k} x{v}" for k, v in info[subj].items()))
    # two refreshes: the earlier one's stretch from the single-refresh table (1 where it has no entry), the rest is
    # the later one's (runs whose earlier refresh has no single measured value are not used); its place i = dE - d + its own stretch
    two = collections.defaultdict(collections.Counter)
    odd = 0
    for places, st, ds, dE in multi[subj]:
        if len(places) != 2:
            odd += 1; continue
        i1 = int(places[0])
        if not t.get(i1) or len(t[i1]) != 1:
            odd += 1; continue          # the earlier refresh's own stretch is not measured alone: not used
        s1 = next(iter(t[i1]))
        s2 = st - s1
        two[int(dE - math.ceil(ds[1]) + s2)][s2] += 1
    rows = []
    for i in sorted(set(t) | set(two)):
        a_ = ", ".join(f"{s_:+g} (x{n})" if "-n" in flags else f"{s_:+g}" for s_, n in sorted(t[i].items())) if t.get(i) else "-"
        b_ = ", ".join(f"{s_:+g} (x{n})" if "-n" in flags else f"{s_:+g}" for s_, n in sorted(two[i].items())) if two.get(i) else "-"
        rows.append((i, a_, b_))
    k = 0
    while k < len(rows):            # runs of consecutive places with the same reading on one line
        j = k
        while "-n" not in flags and j + 1 < len(rows) and rows[j + 1][1:] == rows[k][1:] and rows[j + 1][0] == rows[j][0] + 1:
            j += 1
        print(f"   i = {rows[k][0]:4}" + (f" .. {rows[j][0]:4}" if j > k else "        ") + f": alone {rows[k][1]:10} second of two {rows[k][2]}")
        if j + 1 < len(rows) and rows[j + 1][0] > rows[j][0] + 1 and rows[j][0] >= -6:
            a_, b_ = rows[j][0] + 1, rows[j + 1][0] - 1
            print(f"   i = {a_:4}" + (f" .. {b_:4}" if b_ > a_ else "        ") + ": no refresh cycle starts here")
        k = j + 1
    print(f"   ({odd} runs with three refresh cycles, or an earlier refresh not measured alone, not used)")
