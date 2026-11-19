"""r27two.py: stdin = `r27.py ROUND -v`. The runs with two refresh cycles in the window whose first one starts at an odd
place inside the lead's shift loop (-(2k + 4) .. -7: such a refresh costs exactly one clock, Q140): the second one's
stretch = the window's stretch - 1 and its place = dE - ceil(d) + that. Prints place: stretch x runs."""
import sys, re, collections, math
t = collections.defaultdict(collections.Counter); skipped = 0
for l in sys.stdin:
    if " rg " not in l and " rf " not in l:
        continue
    k = int(re.search(r"-k(\d+)", l).group(1))
    m = re.search(r"D0=(\S+) D=(\S+) stretch=([+-]\d+) d=\[(.*?)\] len=\[(.*?)\] i=\[(.*?)\]", l)
    ds = [float(x.strip(" '")) for x in m.group(4).split(",") if x.strip()]
    st = int(m.group(3)); ii = [float(x) for x in m.group(6).split(",") if x.strip()]
    if len(ds) != 2:
        continue
    i1 = int(ii[0]); dE = round(ii[0] + math.ceil(ds[0]) - st)
    if not (-(2 * k + 4) <= i1 <= -7 and i1 % 2):
        skipped += 1; continue
    s2 = st - 1
    t[dE - math.ceil(ds[1]) + s2][s2] += 1
print(" | ".join(f"{i}:" + ",".join(f"{s:+d}x{n}" for s, n in sorted(t[i].items())) for i in sorted(t)))
print("not used (the first refresh not in the shift loop):", skipped)
