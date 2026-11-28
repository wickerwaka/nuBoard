"""(Work order 54) Save-state tests of the V35S core v2, simulation only.

    PYTHONPATH=host/src:. python3 -m validation.v35s.sstate corpus --base DIR [--family F ...]
        [--per N] [--all F24 F30] [--seed S] [--hold H] [--jobs J] [--out FILE] [--extra ARGS]
    PYTHONPATH=host/src:. python3 -m validation.v35s.sstate progs MODULE NAME ... --at T --every P
        [--n N] [--hold H] [--tag TAG]

corpus: transparency over the refresh-off corpus (validation/v35s/chains). For each chosen run
(per family N runs, chosen by a hash of the run id and the seed; every run of the families given
to --all) the run is replayed on the core v2's simulation with one park injected
(`+v35_ss_at=T +v35_ss_hold=H`, fpga/v35s/v35s_harness.sv) at a pseudo-random clock between the
run's fill point and its end (the hash again), held H ticks and resumed. The run must pass and
complete, and its write sequence (every memory and I/O write cycle in bus order: address, kind,
width, the datum on its lanes) must equal the un-parked run's (the --base directory: a replay of
the same binary with ss_req low, e.g. the gate's corpus run). Each run's park latency (from the
harness's `v35 ss:` line: ticks and CPU clocks) and the take it came through (a dispatch, a
string's take point, HALT) are recorded. --extra adds plusargs (e.g. `+v35_ss_every=997
+v35_ss_n=0`: repeated parks; `+v35_ss_rd=2`: the read-out check, part 2).

progs: a program set's sim (validation/v35s/<MODULE>.py's run_set) with the park plusargs, its
receipts tagged TAG (default -ss); compare them with the receipts without parks yourself (the
module's gate, or this module's `cmp`).

The simulation binary is acquire.V35_BINARY (V35_SIM_BINARY overrides). One simulation process a
run (its plusargs are the run's).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAM = ("F0 F0w F1 F2 F3 F4 F5 F6 F7 F9 F10 F11 F12 F14 F15 F16 F19 F20 F21 F22 F23 F24 F25 F26 "
       "F29 F30 F31 F32 F33 F34 F35 F36 F37 F38 F39 F40").split()
FLAG_READ, FLAG_IO, FLAG_REFRESH, FLAG_NUBE, FLAG_PIN = 1, 2, 4, 8, 1 << 9
SS_LINE = re.compile(r"v35 ss: park (\d+) requested (\d+) parked (\d+) latency (\d+) ticks (\d+) "
                     r"clocks via\s+(\w+) pc ([0-9a-f]+):([0-9a-f]+)")
RS_LINE = re.compile(r"v35 ss: resume (\d+) at (\d+)")
END_MARGIN = 40         # CPU clocks before the END block's OUT that a request may not come in
RD_LINE = re.compile(r"v35 ss: read (\S+) .*")


def _h(*parts) -> int:
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "big")


def writes(trace: list) -> list:
    """The write cycles of a trace in bus order: (address, io, lanes, datum on the lanes)."""
    out = []
    for r in trace:
        f = r["flags"]
        if f & (FLAG_READ | FLAG_REFRESH | FLAG_PIN):
            continue
        a = r["address"]
        lo = not (a & 1)
        hi = not (f & FLAG_NUBE)
        lanes = (1 if lo else 0) | (2 if hi else 0)
        d = r["data"] & ((0xFF if lo else 0) | (0xFF00 if hi else 0))
        out.append((a, bool(f & FLAG_IO), lanes, d))
    return out


def lane(plusargs: list, errpath: str):
    """A simulation process of the core v2 with these plusargs, stderr into errpath."""
    from nuboard.debug import DebugClient
    from .chains.acquire import V35_BINARY
    from .runner import Harness, SimulationTransport
    t = SimulationTransport.__new__(SimulationTransport)
    t.process = subprocess.Popen([str(V35_BINARY)] + plusargs, cwd=ROOT, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=open(errpath, "w"))
    return t, Harness(DebugClient(t.exchange))


def parse_err(text: str) -> dict:
    parks = [dict(clocks=int(m[5]), how=m[6], req=int(m[2]), pc=int(m[8], 16))
             for m in SS_LINE.finditer(text)]
    resumes = [int(m[2]) for m in RS_LINE.finditer(text)]
    chk = [ln for ln in text.splitlines() if ln.startswith("v35 chk")]
    rd = [ln for ln in text.splitlines() if ln.startswith("v35 ss: read")]
    return dict(parks=parks, resumes=resumes, chk=chk, rd=rd)


MAP_FILE = ROOT / "fpga/v35s/core/v35/v35_ss_map.tsv"
FORMAT = 0x5301


def read_map() -> list:
    rows = []
    for ln in MAP_FILE.read_text().splitlines():
        if not ln.strip() or ln.startswith("#") or ln.startswith("index"):
            continue
        i, l, w, e, el = ln.split("\t")
        rows.append((int(i, 16), int(l), int(w), e, int(el)))
    return rows


def check_readout(text: str, rows: list | None = None) -> dict:
    """(part 2) every park's read-out against the registers the harness printed beside it: each
    word the map's fields of the elements (index 000h the format, unlisted indexes 0); every
    pass the same words. {parks, words checked, problems: [...]}."""
    rows = rows or read_map()
    out = {"parks": 0, "words": 0, "problems": []}
    reads, elems = [], {}
    for ln in text.splitlines():
        if ln.startswith("v35 ss: read "):
            _, _, _, n, hx = ln.split()
            reads.append((int(n), [int(hx[4 * k:4 * k + 4], 16) for k in range(1024)]))
        elif ln.startswith("v35 ss: elem "):
            _, _, _, name, v = ln.split()
            elems[name] = int(v, 16)
        elif ln.startswith("v35 ss: resume") and reads:
            out["parks"] += 1
            want = [0] * 1024
            want[0] = FORMAT
            for i, l, w, e, el in rows:
                if e not in elems:
                    out["problems"].append(f"no register {e} printed")
                    continue
                want[i] |= ((elems[e] >> el) & ((1 << w) - 1)) << l
            for i, l, w, e, el in rows:     # the copies: each element's own bits
                if e in elems and ((elems[e] >> el) & ((1 << w) - 1)) != (want[i] >> l) & ((1 << w) - 1):
                    out["problems"].append(f"{i:03X}: {e} differs from the word's other copy")
            for n, words in reads:
                for i in range(1024):
                    out["words"] += 1
                    if words[i] != want[i]:
                        out["problems"].append(f"park {out['parks']} pass {n} {i:03X}: read "
                                               f"{words[i]:04X}, registers {want[i]:04X}")
            reads, elems = [], {}
    return out


def park_tick(base: dict, seed) -> int | None:
    """A pseudo-random tick between the run's fill point and its end (normalize's t_fill and
    t_end, CPU clocks from clock 0 at t0_tick), from the run id and the seed."""
    from .chains.normalize import normalize
    from .chains.types import TICKS_PER_CLOCK
    rid = base["chain"]["id"]
    tr = base["socket_trace"]
    try:
        n = normalize(base, strict=False)
        lo = n.t0_tick + TICKS_PER_CLOCK * (n.t_fill if n.t_fill is not None else 0)
        hi = n.t0_tick + TICKS_PER_CLOCK * (n.t_end if n.t_end is not None
                                            else (tr[-1]["start"] - n.t0_tick) // TICKS_PER_CLOCK)
    except Exception:
        lo, hi = tr[0]["start"], tr[-1]["start"]
    hi -= TICKS_PER_CLOCK * END_MARGIN     # (the END block's OUT and HALT: a request later is not taken)
    if hi <= lo:
        hi = lo + 1
    return lo + _h(seed, rid) % (hi - lo)


def run_one(item) -> dict:
    chain_json, base, seed, hold, extra, limit, fixed = item
    from .chains.acquire import run_built
    from .chains.image import build_image
    from .chains.types import Chain
    chain = Chain.from_json(chain_json)
    t = fixed if fixed is not None else park_tick(base, seed)
    fd, err = tempfile.mkstemp(prefix="ss-", suffix=".err")
    os.close(fd)
    args = ["+v35_chk", f"+v35_ss_at={t}", f"+v35_ss_hold={hold}"] + list(extra)
    tr, h = lane(args, err)
    started = time.monotonic()
    try:
        rec = run_built(h, build_image(chain), "sim", limit)
    finally:
        tr.close()
    text = Path(err).read_text()
    os.unlink(err)
    e = parse_err(text)
    ro = check_readout(text) if "v35 ss: read" in text else None
    wb, wp = writes(base["socket_trace"]), writes(rec["socket_trace"])
    first = None
    for k, (a, b) in enumerate(zip(wb, wp)):
        if a != b:
            first = (k, a, b)
            break
    if first is None and len(wb) != len(wp):
        first = (min(len(wb), len(wp)), None, None)
    return dict(id=chain.id, family=chain.family, at=t, args=args, passed=rec["passed"],
                complete=rec["complete"], base_passed=base["passed"], writes=len(wb),
                writes_park=len(wp), equal=first is None, first=first, parks=e["parks"],
                resumes=len(e["resumes"]), chk=e["chk"][:5],
                readout=None if ro is None else dict(parks=ro["parks"], words=ro["words"],
                                                    problems=ro["problems"][:10],
                                                    nproblems=len(ro["problems"])),
                elapsed=rec["elapsed_ticks"], base_elapsed=base["elapsed_ticks"],
                seconds=round(time.monotonic() - started, 3))


def load_base(base_dir: Path, families) -> dict:
    out = {}
    for p in sorted(base_dir.glob("*.json")):
        d = json.loads(p.read_text())
        for r in d.get("runs", []):
            if r["chain"]["family"] in families:
                out[r["chain"]["id"]] = r
    return out


def corpus(args) -> int:
    from .chains.acquire import select_chains
    fams = args.family or FAM
    base = load_base(Path(args.base), set(fams))
    chains = select_chains(fams, None, None, None)
    by = {}
    for c in chains:
        by.setdefault(c.family, []).append(c)
    todo = []
    for f in fams:
        cs = sorted(by.get(f, []), key=lambda c: _h(args.seed, "pick", c.id))
        if f not in (args.all or []):
            cs = cs[:args.per]
        for c in cs:
            if c.id not in base:
                print(f"{c.id}: no base run in {args.base}", flush=True)
                continue
            todo.append((c.to_json(), base[c.id], args.seed, args.hold, args.extra.split(),
                         args.limit, args.fixed))
    print(f"{len(todo)} runs, {args.jobs} jobs", flush=True)
    out = open(args.out, "w") if args.out else None
    res = []
    started = time.monotonic()
    import multiprocessing
    with multiprocessing.get_context("fork").Pool(args.jobs) as pool:
        for r in pool.imap_unordered(run_one, todo):
            res.append(r)
            if out:
                out.write(json.dumps(r) + "\n")
                out.flush()
            bad = (not r["passed"] or not r["complete"] or not r["equal"] or not r["parks"]
                   or r["chk"] or (r["readout"] or {}).get("nproblems"))
            if bad:
                print(f"  {r['id']}: {'PASS' if r['passed'] else 'FAIL'}"
                      f"{'' if r['complete'] else ' INCOMPLETE'} writes {r['writes_park']}/"
                      f"{r['writes']} {'equal' if r['equal'] else 'DIFFER ' + str(r['first'])}"
                      f" parks {len(r['parks'])} chk {len(r['chk'])} {r['readout'] and r['readout']['problems'][:3]}", flush=True)
    summarize(res, time.monotonic() - started)
    return 0


def summarize(res: list, secs: float = 0.0):
    fam = Counter(r["family"] for r in res)
    ok = Counter(r["family"] for r in res if r["passed"] and r["complete"] and r["equal"]
                 and r["parks"] and not r["chk"] and not (r.get("readout") or {}).get("nproblems"))
    print("family runs transparent")
    for f in FAM:
        if fam[f]:
            print(f"{f} {fam[f]} {ok[f]}")
    lat = [p["clocks"] for r in res for p in r["parks"]]
    how = Counter(p["how"] for r in res for p in r["parks"])
    noparks = sum(1 for r in res if not r["parks"])
    ro = [r["readout"] for r in res if r.get("readout")]
    if ro:
        print(f"read-out: {sum(x['parks'] for x in ro)} parks read, {sum(x['words'] for x in ro)} "
              f"words compared, {sum(x['nproblems'] for x in ro)} differ")
    print(f"all {len(res)} runs: transparent {sum(ok.values())}; passed "
          f"{sum(r['passed'] for r in res)}, complete {sum(r['complete'] for r in res)}, writes "
          f"equal {sum(r['equal'] for r in res)}, chk lines {sum(len(r['chk']) for r in res)}, "
          f"runs with no park {noparks}; {secs:.0f} s")
    if lat:
        lat.sort()
        print(f"parks {len(lat)} ({dict(how)}); latency in CPU clocks: max {lat[-1]}, median "
              f"{lat[len(lat) // 2]}, p99 {lat[int(len(lat) * 0.99)]}, mean "
              f"{sum(lat) / len(lat):.1f}")
        edges = [0, 10, 20, 30, 40, 50, 60, 80, 100, 150, 200, 300, 500, 1000, 2000, 5000, 10 ** 9]
        hist = Counter()
        for v in lat:
            for a, b in zip(edges, edges[1:]):
                if a <= v < b:
                    hist[(a, b)] += 1
        print("histogram: " + ", ".join(f"[{a},{b if b < 10 ** 9 else 'inf'}) {hist[(a, b)]}"
                                        for a, b in zip(edges, edges[1:]) if hist[(a, b)]))
        top = sorted(((p["clocks"], r["id"], p["how"]) for r in res for p in r["parks"]),
                     reverse=True)[:8]
        print("longest: " + "; ".join(f"{c} {i} ({h})" for c, i, h in top))


def report(args) -> int:
    res = [json.loads(ln) for ln in open(args.file)]
    summarize(res)
    return 0


def progs(args) -> int:
    import importlib
    mod = importlib.import_module(f"validation.v35s.{args.module}")
    plus = ["+v35_chk", f"+v35_ss_at={args.at}", f"+v35_ss_hold={args.hold}"]
    if args.every:
        plus += [f"+v35_ss_every={args.every}", f"+v35_ss_n={args.n}"]
    plus += args.extra.split()
    os.environ["V35_PLUSARGS"] = " ".join(plus)
    mod.run_set(args.names or list(mod.programs()), "sim", tag=args.tag)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m validation.v35s.sstate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("corpus")
    c.add_argument("--base", required=True, help="the un-parked replays (a replay --output-dir)")
    c.add_argument("--family", nargs="+")
    c.add_argument("--per", type=int, default=300)
    c.add_argument("--all", nargs="*", default=["F24", "F30"])
    c.add_argument("--seed", default="wo54")
    c.add_argument("--hold", type=int, default=40)
    c.add_argument("--jobs", type=int, default=5)
    c.add_argument("--limit", type=int, default=2_000_000)
    c.add_argument("--extra", default="")
    c.add_argument("--fixed", type=int, help="the first request at this tick in every run (with "
                   "--extra +v35_ss_every=P +v35_ss_n=0: parks all through the run)")
    c.add_argument("--out")
    r = sub.add_parser("report")
    r.add_argument("file")
    p = sub.add_parser("progs")
    p.add_argument("module")
    p.add_argument("names", nargs="*")
    p.add_argument("--at", type=int, required=True)
    p.add_argument("--every", type=int, default=0)
    p.add_argument("--n", type=int, default=0)
    p.add_argument("--hold", type=int, default=40)
    p.add_argument("--tag", default="-ss")
    p.add_argument("--extra", default="")
    a = ap.parse_args(argv)
    return {"corpus": corpus, "report": report, "progs": progs}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
