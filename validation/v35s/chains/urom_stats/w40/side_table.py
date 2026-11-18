"""Way out (b): a side table read in parallel with the main ROM, addressed by the low k bits
of the microaddress; an entry carries the page it belongs to (the address's high 11 - k bits)
and a full payload (X 8 bits, Y 9 bits with POST). A wide word is one that does not fit
layout L40 before the assembler-only ways out. Measures: how many wide words, how they
cluster, and whether the chains can be placed so that no two wide words share their low k
bits (first-fit placement; padding = address holes left between chains, never executed).
usage: python3 -B side_table.py > side_table.txt"""
import collections, os, lib, layout
import fit_shared as FS
SIDE_OK = ("no payload bits", "one payload code only", "outside its")
def study(name, hold):
    chains, st = lib.shared(hold, wide_with_jump=FS.rank)
    ws = lib.flat(chains); L = layout.Layout(ws)
    wide = {}; other = collections.Counter()
    for w in ws:
        r = L.fit(w)
        if not r: continue
        if any(k in r for k in SIDE_OK) and "no room for the count" not in r: wide[id(w)] = r
        else: other[r] += 1
    print(f"\n== {name}: {len(ws)} words in {len(chains)} chains; wide words a side entry clears: {len(wide)}; not cleared by a side entry (sequencing or count conflicts): {sum(other.values())} {dict(other)}")
    per = collections.Counter(); runs = collections.Counter(); wch = []
    for ch in chains:
        pos = [i for i, w in enumerate(ch) if id(w) in wide]
        if not pos: continue
        wch.append((ch, pos)); per[len(pos)] += 1
        run = 1
        for a, b in zip(pos, pos[1:]):
            if b == a + 1: run += 1
            else: runs[run] += 1; run = 1
        runs[run] += 1
    rts = collections.Counter(r for ch in chains for w in ch if id(w) in wide for r in w.routines[:1])
    print(f"   chains with a wide word: {len(wch)} (wide words per chain -> chains: {dict(sorted(per.items()))}); runs of consecutive wide words (length -> count): {dict(sorted(runs.items()))}")
    print(f"   routines (first sharer) with a wide word: {len(rts)}; the most: {rts.most_common(6)}")
    total = len(ws)
    for k in (6, 7, 8):
        n = 1 << k
        if len(wide) > n: print(f"   k = {k}: {n} entries < {len(wide)} wide words"); continue
        used = set(); placed = []; free = []      # placed: (start, len); address space grows
        cursor = 0; ok = True; intra = 0
        for ch, pos in sorted(wch, key=lambda cp: -len(cp[1])):
            if len(set(p % n for p in pos)) < len(pos): intra += 1
            a = cursor; tries = 0
            while any(((a + p) % n) in used for p in pos):
                a += 1; tries += 1
                if tries > n: ok = False; break
            if not ok: break
            if a > cursor: free.append([cursor, a - cursor])
            for p in pos: used.add((a + p) % n)
            placed.append((a, len(ch))); cursor = a + len(ch)
        if not ok: print(f"   k = {k}: first-fit placement failed"); continue
        holes = sum(l for a, l in free)
        rest = sorted((len(ch) for ch in chains if not any(id(w) in wide for w in ch)), reverse=True)
        for l in rest:                                   # fill the holes with chains that have no wide word
            for h in free:
                if h[1] >= l: h[1] -= l; break
        pad = sum(h[1] for h in free)
        bits = (11 - k) + 8 + 9
        blk = "0 block RAMs (LUT ROM)" if k < 8 else f"{-(-n * bits // 5120)} block RAM(s) (256 x 20 mode)" if bits <= 20 else "2 block RAMs"
        print(f"   k = {k}: {n} entries x {bits} bits = {n * bits} bits, {blk}; chains with two wide words on the same low bits: {intra}; holes opened by the placement {holes}, left after filling with other chains: {pad} padding words; forced jumps: 0 (chains are moved whole)")
if __name__ == "__main__":
    print("take-entry codes on; way out (a) on (as fit_shared.py)")
    study("PT (tail sharing)", False)
    study("PH (tail sharing + hold counts)", True)
