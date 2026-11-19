"""f27.py [--src socket|sim]: function check of rounds 27a/b/d/e (the marker's data is AW; the memory forms' write) against
arithmetic done here, and ROR4 - ROL4 per (form, lead, alignment, waits)."""
import sys, re, json, collections
sys.path[:0] = ["host/src", ".", "validation/v35s/qprobe/tools/r27"]
from validation.v35s.qprobe import read
import t27
src = sys.argv[sys.argv.index("--src") + 1] if "--src" in sys.argv else "socket"


def s(x, bits):
    x &= (1 << bits) - 1
    return x - (1 << bits) if x >> (bits - 1) else x


def sv(tok):
    return (-1 if tok[0] == "m" else 1) * int(tok[1:], 16)


def expect(form, ops):
    """(AW at the marker or None, memory byte written or None)"""
    o = ops.split("-")
    if form[:4] in ("rol4", "ror4"):
        a, b = int(o[0], 16), int(o[1], 16)
        if form[:4] == "rol4":
            al, m = (a & 0xF0) | (b >> 4), ((b << 4) & 0xF0) | (a & 0x0F)
        else:
            al, m = (a & 0xF0) | (b & 0x0F), ((a << 4) & 0xF0) | (b >> 4)
        return 0x5A00 | al, (m if form[4] == "m" else None)
    if form in ("mulu8", "mul8"):
        a, b = int(o[0], 16), int(o[1], 16)
        return ((a * b) if form == "mulu8" else s(a, 8) * s(b, 8)) & 0xFFFF, None
    if form in ("mulu16", "mul16"):
        a, b = int(o[0], 16), int(o[1], 16)
        return ((a * b) if form == "mulu16" else s(a, 16) * s(b, 16)) & 0xFFFF, None
    if form == "divu16":
        d, a, b = (int(x, 16) for x in o)
        return ((d << 16 | a) // b) & 0xFFFF, None
    if form == "divu8":
        a, b = int(o[0], 16), int(o[1], 16)
        return ((a % b) << 8 | (a // b)) & 0xFFFF, None
    if form in ("div16", "div16m", "div8"):
        n, d = sv(o[0]), sv(o[1])
        q = abs(n) // abs(d) * (1 if (n < 0) == (d < 0) else -1)
        r = n - q * d
        return (q & 0xFFFF if form != "div8" else ((r & 0xFF) << 8 | (q & 0xFF))), None
    return None, None


bad = n = 0
diff = collections.defaultdict(dict)
for rnd in ("r27a", "r27b", "r27d", "r27e"):
    runs = t27.load(src, rnd)
    for (form, lead, p, w), progs in t27.groups(runs).items():
        for ops, run in progs.items():
            aw, m = expect(form, ops)
            got = t27.m1data(run)
            wr = [x["data"] & 0xFF for x in run["socket_trace"] if not x["flags"] & 7 and x["address"] == 0x800]
            n += 1
            if aw != got or (m is not None and (not wr or wr[-1] != m)):
                bad += 1
                print("FUNCTION", run["chain"]["id"], f"AW {got:04X} expected {aw:04X}", wr[-1:] , m)
            if form[:4] in ("rol4", "ror4"):
                diff[(form[4], lead, p, w, ops)][form[:4]] = t27.cut(read.events(run))[-1][0]
c = collections.Counter(v["ror4"] - v["rol4"] for v in diff.values() if len(v) == 2)
print(n, "runs,", bad, "with a wrong result; ROR4 - ROL4 (marker clocks):", dict(c))
