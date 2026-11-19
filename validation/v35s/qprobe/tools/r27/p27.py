"""p27.py FILE: s27.py's listing (python3 s27.py ROUND > FILE) by fetch placement. For the model-exact runs only: which
fetch cycles START inside the subject (s+n: on clock n from the subject's boundary; L+n / 2L+n: n clocks after one / two
cycle lengths), whether a fetch cycle ends on the boundary clock itself (0), and the subject's boundary-to-boundary
length per cycle length L. The placement is silicon's (the pins); only the boundary clocks are the model's."""
import re, sys, collections
cur = None; pat = collections.defaultdict(lambda: collections.defaultdict(list)); tot = collections.Counter()
for line in open(sys.argv[1]):
    m = re.match(r"(\w+) (\w+) p([EO])$", line.strip())
    if m:
        cur = m.groups(); continue
    m = re.match(r"\s+L=\s*(\d+) (\S+)\s+(=|X \S+)\s+len=(\S+)\s+fetches (.*)$", line.rstrip())
    if not m:
        continue
    tot[(cur[0], m.group(3) == "=")] += 1
    if m.group(3) != "=":
        continue
    L = int(m.group(1)); ln = int(m.group(4))
    f = [tuple(map(int, re.match(r"(-?\d+)\.\.(-?\d+)", x).groups())) for x in m.group(5).split()]
    ins = [a for a, b in f if 1 <= a < ln - 4]
    late = [a for a, b in f if a >= 1 and a >= ln - L - 1 and a > 8]        # the fetch the next opcode's release starts
    ins = [a for a in ins if a not in late]
    pre = [b for a, b in f if a < 1]
    key = (cur[0], tuple(("s%+d" % a) if a <= 6 else ("L%+d" % (a - L)) for a in ins), tuple(pre), tuple(sorted(set(late))))
    pat[key][L].append(ln)
for key in sorted(pat, key=str):
    v = pat[key]
    print(f"{key[0]:7} starts inside: {' '.join(key[1]) or 'none':10} | ends on clock {'0' if key[2] else '-'} | release fetch at {key[3] and key[3][0] or '-'} | runs {sum(len(x) for x in v.values())}")
    print("          L:length  " + " ".join(f"{L}:{'/'.join(map(str, sorted(set(v[L]))))}" for L in sorted(v)))
print({f"{k[0]} {'exact' if k[1] else 'not exact'}": n for k, n in tot.items()})
