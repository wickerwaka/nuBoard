"""t27.py ROUND [SUBSTR...] [--src socket|sim] [-v] [-d]: operand dependence of round 27's programs. Runs are grouped by
(lead, form, alignment, waits); within a group the programs differ in operand values only (the same bytes counts).
Per group: the number of distinct event strips (clock, kind, address; M0 = 0, to the marker's own cycle), and per
distinct strip the marker's clock relative to the group's earliest and the operands that give it. -d: the marker's
data (AW) per run as well. -v: the strips."""
import sys, json, re, collections
sys.path[:0] = ["host/src", "."]
from pathlib import Path
from validation.v35s.qprobe import read


def load(src, rnd):
    runs = {}
    for p in sorted(Path(f"build/validation/v35s/qprobe/{src}").glob(f"QP{rnd}-w*.json")):
        for r in json.loads(p.read_text())["runs"]:
            runs[r["chain"]["id"]] = r
    return runs


def cut(ev):
    out = []
    for e in ev:
        out.append(e)
        if e[1] == "O" and e[2] == 0x20:
            break
    return out


def m1data(run):
    return next((x["data"] for x in run["socket_trace"] if x["flags"] & 2 and x["address"] & 0xFFFF == 0x20), None)


def groups(runs, subs=()):
    g = collections.defaultdict(dict)
    for cid, run in runs.items():
        m = re.match(r"QP\w+?-([a-z0-9]+)-([a-z0-9]+)-(.*)-p([EO])-w(\d)$", cid)
        lead, form, ops, p, w = m.groups()
        if subs and not any(s in cid for s in subs):
            continue
        g[(form, lead, p, int(w))][ops] = run
    return g


if __name__ == "__main__":
    argv = sys.argv[1:]
    src = "socket"
    if "--src" in argv:
        k = argv.index("--src"); src = argv[k + 1]; del argv[k:k + 2]
    flags = {a for a in argv if a.startswith("-")}; argv = [a for a in argv if a not in flags]
    rnd, subs = argv[0], argv[1:]
    runs = load(src, rnd)
    summ = collections.defaultdict(lambda: collections.defaultdict(set))
    for key, progs in sorted(groups(runs, subs).items()):
        strips = collections.defaultdict(list)
        for ops, run in progs.items():
            strips[tuple(cut(read.events(run)))].append(ops)
        t0 = min(s[-1][0] for s in strips)
        print(f"{key[0]:8} {key[1]} p{key[2]} w{key[3]}: {len(progs)} programs, {len(strips)} strips; marker at {t0}")
        for s, ops in sorted(strips.items(), key=lambda x: x[0][-1][0]):
            d = s[-1][0] - t0
            for o_ in ops:
                summ[key[0]][o_].add(d)
            if len(strips) > 1:
                print(f"    +{d}: {' '.join(ops)}")
            if "-v" in flags:
                print("      ", read.strip([e for e in s if e[0] > t0 - 70]))
        if "-d" in flags:
            print("    data:", " ".join(f"{o_}={m1data(r):04X}" for o_, r in progs.items()))
    print()
    print("per form and operands: the marker's delay over the group's earliest, over all leads / alignments / waits")
    for form, d in summ.items():
        by = collections.defaultdict(list)
        for ops, ds in d.items():
            by[tuple(sorted(ds))].append(ops)
        for ds, ops in sorted(by.items()):
            print(f"  {form:8} +{'/'.join(map(str, ds))}: {' '.join(ops)}")
