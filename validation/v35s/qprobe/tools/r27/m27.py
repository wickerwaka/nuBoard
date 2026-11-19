"""m27.py ROUND...: the reading model (model_m, cmp22.compare's cut) on the operand rounds: exact runs per form, and for the
misses the marker's clock silicon - model per operand pair. The model's subject length (boundary to boundary, from its log)
per form is printed for the exact runs of the `q` lead: the base length the operand terms add to."""
import sys, json, re, collections
sys.path[:0] = ["host/src", ".", "build/qp", "validation/v35s/qprobe/tools/r27"]
from validation.v35s.qprobe import read, model_m as M
import cmp22, t27
for rnd in sys.argv[1:]:
    runs = t27.load("socket", rnd)
    res = collections.defaultdict(lambda: [0, 0, collections.defaultdict(set), collections.Counter()])
    for (form, lead, p, w), progs in t27.groups(runs).items():
        for ops, run in progs.items():
            r = res[form]
            try:
                a, m = cmp22.compare(run)
            except Exception as e:
                r[1] += 1; r[2][ops].add("ERR " + repr(e)[:30]); continue
            r[1] += 1
            if a == m:
                r[0] += 1
                log = []
                M.simulate(run, M.DEFAULT, log=log)
                es = [(t, txt) for t, txt in log if re.match(r"E\d+ ", txt)]
                ke = next(i for i, (t, txt) in enumerate(es) if " E7@" in txt)
                if lead == "q":
                    r[3][es[ke][0] - es[ke - 1][0]] += 1
            else:
                r[2][ops].add(a[-1][0] - m[-1][0] if a and m else "?")
    for form, (ok, n, miss, ln) in res.items():
        by = collections.defaultdict(list)
        for ops, ds in miss.items():
            by[tuple(sorted(map(str, ds)))].append(ops)
        print(f"{rnd} {form:8} model-exact {ok}/{n}; boundary to boundary behind the long shift: {dict(ln)}")
        for ds, ops in sorted(by.items()):
            print(f"      marker silicon - model {'/'.join(ds)}: {' '.join(ops)}")
