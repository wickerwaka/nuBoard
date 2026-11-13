"""F5: the closing random-instruction fuzz, socket against RTL (docs/v35s-function-plan.md, F5).

Seeded random programs (validation/v35s/fuzz_gen.py) run on the socketed uPD70337 and on the
core v2 RTL in simulation; the gate is every F stage's: each program's write and I/O sequence and
its result region equal, timing ignored.

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.fuzz socket SET [--tag=-2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.fuzz sim SET [--jobs 8]
    PYTHONPATH=host/src:. python3 -m validation.v35s.fuzz gate SET [--ref socket] [--cand sim]
    PYTHONPATH=host/src:. python3 -m validation.v35s.fuzz show SET NAME [--ref socket]
    PYTHONPATH=host/src:. python3 -m validation.v35s.fuzz list SET NAME
    PYTHONPATH=host/src:. python3 -m validation.v35s.fuzz cover [SET ...]
    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.fuzz shrink SET NAME

Sets (one per scenario layer, so a failure names its layer): see SETS. A set's programs are
regenerated from their seeds (deterministic); the receipt of a set holds every program's record
(validation/v35s/receipts/f5-<set>-<backend>.json.gz: the seed, the program's sha256, the write
and I/O sequence, the I/O reads, the result regions, the record count).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import gzip
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from . import fuzz_gen as G
from . import fuzz_layers as L

ROOT = Path(__file__).resolve().parents[2]
RECEIPTS = ROOT / "validation/v35s/receipts"

SETS = L.SETS


def programs(set_name, names=None):
    out = {}
    for name, mk in L.makers(set_name):
        if names and name not in names:
            continue
        out[name] = mk()
    return out


def receipt_path(set_name, backend):
    return RECEIPTS / f"f5-{set_name}-{backend}.json.gz"


def load(set_name, backend):
    with gzip.open(receipt_path(set_name, backend), "rt") as f:
        return json.load(f)


def save(set_name, backend, data):
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    with gzip.open(receipt_path(set_name, backend), "wt") as f:
        json.dump(data, f, separators=(",", ":"))


def _stim(harness, prog):
    from .runner import REST_LEVELS, load_stimulus
    harness.debug.write16(0x8E, getattr(prog, "levels", REST_LEVELS))
    if harness.version >= 2:
        load_stimulus(harness, getattr(prog, "stim", None))


def run_prog(harness, prog, lane, attempts=4):
    """One program's record. A trace longer than one capture window is stitched from separate
    runs (onchip.run_one: one run per 2,048-record window), which is exact only when every run
    is the same execution: a window run whose total or signature differs from the first run's
    (state left by the previous program, an asynchronous take landing elsewhere: F5 finding 21)
    makes the record unstitchable. The whole program is then run again (its own end state now
    the starting state) up to `attempts` times; a record that never stitches keeps its replay
    notes and the gate refuses to compare it."""
    from .onchip import run_one
    keep = ("passed", "status", "timeout", "total", "writes", "io_reads", "regions", "replay",
            "trace_tail", "program_sha256")
    for attempt in range(1, attempts + 1):
        _stim(harness, prog)
        rec = run_one(harness, prog, lane, limit=prog.limit)
        if not rec["replay"]:
            break
    rec = {k: rec[k] for k in keep}
    rec.update(seed=prog.seed, fuzz=prog.meta.get("fuzz"), attempts=attempt)
    return rec


def _sim_one(args):
    set_name, name = args
    from .chains.acquire import sim_transport
    from .runner import Harness
    from nuboard.debug import DebugClient
    prog = programs(set_name, [name])[name]
    transport = sim_transport("v35")
    try:
        harness = Harness(DebugClient(transport.exchange), strict=False)
        harness.configure(x_half=2)
        return name, run_prog(harness, prog, "model")
    finally:
        transport.close()


def run_set(set_name, backend, tag="", names=None, jobs=8):
    progs = programs(set_name, names)
    path = receipt_path(set_name, backend + tag)
    data = {"set": set_name, "backend": backend, "programs": {}}
    if names and path.exists():
        data = load(set_name, backend + tag)
    data["date"] = datetime.datetime.now().isoformat(timespec="seconds")
    if backend == "socket":
        data.update(cpu="uPD70337L-8", x_half=2)
    else:
        data.update(core="v35", binary=os.environ.get("V35_SIM_BINARY",
                                                       "build/fpga/v35s/verilator-direct-v35"))
    t0 = time.time()
    done = 0

    def note(name, rec):
        nonlocal done
        done += 1
        data["programs"][name] = rec
        print(f"{name}: {backend} {'PASS' if rec['passed'] else 'FAIL'} status=0x{rec['status']:04x} "
              f"fuzz={rec['fuzz']} writes={len(rec['writes'])} total={rec['total']} "
              f"[{done}/{len(progs)} {time.time() - t0:.0f}s]", flush=True)

    try:
        if backend == "socket":
            from .traps import _board, _close_board
            transport, harness = _board()
            try:
                for name, prog in progs.items():
                    note(name, run_prog(harness, prog, "socket"))
            finally:
                _close_board(transport, harness)
        else:
            with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as ex:
                for name, rec in ex.map(_sim_one, [(set_name, n) for n in progs]):
                    note(name, rec)
    finally:
        data["programs"] = dict(sorted(data["programs"].items()))
        save(set_name, backend + tag, data)
    return data


# ------------------------------------------------------------------ the gate
def masked_writes(writes, ex):
    from .onchip import _masked_writes
    return _masked_writes(writes, ex)


def compare_rec(a, b, prog=None, mask=None):
    """(equal, a description of the first differences)."""
    ex = set(mask or ())
    wa = a["writes"]
    wb = b["writes"]
    if prog is not None and hasattr(prog, "write_filter"):
        wa, wb = prog.write_filter(wa), prog.write_filter(wb)
    wa, wb = masked_writes(wa, ex), masked_writes(wb, ex)
    msg = []
    if wa != wb:
        first = next((i for i, (x, y) in enumerate(zip(wa, wb)) if x != y), min(len(wa), len(wb)))
        x = wa[first] if first < len(wa) else None
        y = wb[first] if first < len(wb) else None
        f = lambda w: "-" if w is None else f"{w[0]:05X}:{w[1]:04X}/{w[2]:03X}"     # noqa: E731
        msg.append(f"writes {len(wa)}/{len(wb)} first difference at {first}: {f(x)} / {f(y)}")
    if a["io_reads"] != b["io_reads"]:
        msg.append("io_reads differ")
    diffs = []
    for key in a["regions"]:
        base = int(key, 16)
        ra, rb = bytes.fromhex(a["regions"][key]), bytes.fromhex(b["regions"].get(key, ""))
        diffs += [(base + i, ra[i], rb[i] if i < len(rb) else -1) for i in range(len(ra))
                  if base + i not in ex and (i >= len(rb) or ra[i] != rb[i])]
    if diffs:
        msg.append("result bytes differ: " + ", ".join(f"{x:05X}:{y:02X}/{z:02X}" for x, y, z in diffs[:12])
                   + (f" (+{len(diffs) - 12})" if len(diffs) > 12 else ""))
    if a["passed"] != b["passed"]:
        msg.append(f"passed {a['passed']}/{b['passed']}")
    for side, r in (("reference", a), ("candidate", b)):
        if r.get("replay"):
            msg.append(f"the {side}'s trace windows are not one execution ({r['replay'][0]})")
    return not msg, "; ".join(msg)


def gate(set_name, ref="socket", cand="sim", names=None, quiet=False):
    A, B = load(set_name, ref), load(set_name, cand)
    progs = programs(set_name, names or list(A["programs"]))
    n_eq = n_diff = n_fuzz = 0
    bad = []
    for name in sorted(progs):
        if name not in A["programs"] or name not in B["programs"]:
            print(f"{name}: missing ({ref}: {name in A['programs']}, {cand}: {name in B['programs']})")
            bad.append(name)
            n_diff += 1
            continue
        prog = progs[name]
        a, b = A["programs"][name], B["programs"][name]
        if a.get("program_sha256") != hashlib.sha256(prog.code).hexdigest():
            print(f"{name}: the receipt's program is not the generator's (regenerated differently)")
        ok, msg = compare_rec(a, b, prog, prog.mask)
        ok = ok and a["passed"]
        if ok:
            n_eq += 1
            n_fuzz += a.get("fuzz") or 0
        else:
            n_diff += 1
            bad.append(name)
        if not quiet or not ok:
            print(f"{name}: gate {'EQUAL' if ok else 'DIFFER'} writes {len(a['writes'])}"
                  + ("" if ok else f" {msg}" + ("" if a["passed"] else " (the reference did not pass)")))
    print(f"{set_name}: {ref} vs {cand}: {n_eq} EQUAL, {n_diff} DIFFER; {n_fuzz} fuzzed instructions "
          f"in the equal programs")
    return not bad, bad


# ------------------------------------------------------------------ reading
def show(set_name, name, ref="socket", cand="sim"):
    prog = programs(set_name, [name])[name]
    print(prog.source)
    try:
        a, b = load(set_name, ref)["programs"][name], load(set_name, cand)["programs"][name]
    except (FileNotFoundError, KeyError):
        return
    wa, wb = masked_writes(a["writes"], prog.mask), masked_writes(b["writes"], prog.mask)
    print(f"{ref}: total {a['total']} writes {len(wa)}; {cand}: total {b['total']} writes {len(wb)}")
    for i in range(max(len(wa), len(wb))):
        x = wa[i] if i < len(wa) else None
        y = wb[i] if i < len(wb) else None
        if x != y:
            print(f"  #{i}: {ref} {x} {cand} {y}")
    print(compare_rec(a, b, prog, prog.mask)[1])


def cover(sets):
    """Per form x mode x width: instances emitted and run (outside a skipped block, loop bodies
    counted per iteration), and the instances in conditionally skipped blocks."""
    tot = {}
    for s in sets:
        for name, prog in programs(s).items():
            for k, v in prog.cov.items():
                tot[k] = tot.get(k, 0) + v
    rows = {}
    for k, v in tot.items():
        if k.startswith("?"):
            continue
        rows[k] = (v, tot.get("?" + k, 0))
    return rows


# ------------------------------------------------------------------ triage
def full_trace_sim(prog):
    from .chains.acquire import sim_transport
    from .runner import Harness
    from nuboard.debug import DebugClient
    transport = sim_transport("v35")
    try:
        harness = Harness(DebugClient(transport.exchange), strict=False)
        harness.configure(x_half=2)
        _stim(harness, prog)
        code, segments, pages = prog.image()
        harness.load(segments, pages)
        result = harness.run("model", prog.limit)
        trace = list(result["model_trace"])
        for start in range(2048, result["model_total"], 2048):
            harness.load(segments, pages)
            trace.extend(harness.run("model", prog.limit, capture_start=start)["model_trace"])
        return trace
    finally:
        transport.close()


def first_diff(set_name, name, ref="socket", cand="sim"):
    prog = programs(set_name, [name])[name]
    a, b = load(set_name, ref)["programs"][name], load(set_name, cand)["programs"][name]
    wa, wb = masked_writes(a["writes"], prog.mask), masked_writes(b["writes"], prog.mask)
    i = next((k for k, (x, y) in enumerate(zip(wa, wb)) if x != y), None)
    if i is None and len(wa) != len(wb):
        i = min(len(wa), len(wb))
    return prog, i, wa, wb


def locate(prog, trace, nth_write):
    """The listing entry executing when the RTL made its nth write (by the code fetches)."""
    from .runner import FLAG_IO, FLAG_READ, FLAG_STROBE
    k = -1
    for idx, t in enumerate(trace):
        if t["flags"] & FLAG_STROBE and (t["flags"] & FLAG_IO or not t["flags"] & FLAG_READ):
            k += 1
            if k == nth_write:
                break
    else:
        return None, None
    fetches = [t["address"] for t in trace[max(0, idx - 12):idx]
               if t["flags"] & FLAG_READ and not t["flags"] & FLAG_IO and G.CODE <= t["address"] < G.CODE_END]
    return idx, (max(fetches) if fetches else None)


def triage(set_name, name, ref="socket", cand="sim", ctx=6):
    prog, i, wa, wb = first_diff(set_name, name, ref, cand)
    if i is None:
        print(f"{name}: writes equal")
        return
    trace = full_trace_sim(prog)
    idx, fa = locate(prog, trace, i)
    print(f"{name}: first differing write #{i}: {ref} {wa[i] if i < len(wa) else None} "
          f"{cand} {wb[i] if i < len(wb) else None}; trace record {idx}, last fetch {fa and hex(fa)}")
    if fa is None:
        return
    ins = prog.ins
    # the instruction at the fetch pointer minus the queue's reach; show the window
    pos = max((n for n, x in enumerate(ins) if x.addr <= fa - 6), default=0)
    lo = max(0, pos - ctx)
    for x in ins[lo:pos + 4]:
        mark = {"fuzz": " ", "setup": "s", "obs": "o", "frame": "f", "junk": "j"}[x.tag]
        print(f"   {x.addr:05X} {mark}{'?' if x.maybe else ' '} {x.data.hex(' '):30s} {x.text}")


def window_of(prog, fa):
    """The fuzzed instructions of the observation window that holds code address `fa`."""
    ins = prog.ins
    pos = max((n for n, x in enumerate(ins) if x.addr <= fa - 6), default=0)
    # the observation at or after pos, and the one before it
    nxt = next((n for n in range(pos, len(ins)) if ins[n].tag == "obs"), len(ins) - 1)
    prv = max((n for n in range(0, nxt) if ins[n].tag == "obs" and n < nxt
               and not (n + 1 < len(ins) and ins[n + 1].tag == "obs" and n + 1 == nxt)), default=0)
    while prv > 0 and ins[prv - 1].tag == "obs":
        prv -= 1
    return [x for x in ins[prv:nxt] if x.tag == "fuzz"]


def _triage_one(args):
    set_name, name, ref, cand = args
    try:
        prog, i, wa, wb = first_diff(set_name, name, ref, cand)
        if i is None:
            return name, "writes equal", []
        trace = full_trace_sim(prog)
        idx, fa = locate(prog, trace, i)
        head = (f"#{i} {ref} {wa[i] if i < len(wa) else None} {cand} {wb[i] if i < len(wb) else None}")
        if fa is None:
            return name, head + " (not located)", []
        return name, head, [f"{x.addr:05X} {x.data.hex()} {x.text}" + (" ?" if x.maybe else "")
                            for x in window_of(prog, fa)]
    except Exception as e:      # noqa: BLE001
        return name, f"error {e!r}", []


def triage_all(set_name, ref="socket", cand="sim", names=None, jobs=8):
    A, B = load(set_name, ref)["programs"], load(set_name, cand)["programs"]
    progs = programs(set_name, names or sorted(A))
    todo = []
    for name, prog in progs.items():
        if name in A and name in B and not compare_rec(A[name], B[name], prog, prog.mask)[0] \
                and A[name]["passed"] and B[name]["passed"]:
            todo.append((set_name, name, ref, cand))
    with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as ex:
        for name, head, win in ex.map(_triage_one, todo):
            print(f"{name}: {head}")
            for w in win:
                print(f"      {w}")


# ------------------------------------------------------------------ shrinking
def shrink(set_name, name, max_runs=200):
    """Delta-debug the program's items: keep a removal when the socket and the RTL still differ."""
    from .traps import _board, _close_board
    prog = programs(set_name, [name])[name]
    mk = L.rebuild(set_name, name)
    items = list(prog.items)
    transport, harness = _board()
    runs = 0

    def differs(its):
        nonlocal runs
        runs += 1
        p = mk(its)
        a = run_prog(harness, p, "socket")
        from .chains.acquire import sim_transport
        from .runner import Harness
        from nuboard.debug import DebugClient
        t2 = sim_transport("v35")
        try:
            h2 = Harness(DebugClient(t2.exchange), strict=False)
            h2.configure(x_half=2)
            b = run_prog(h2, p, "model")
        finally:
            t2.close()
        ok, msg = compare_rec(a, b, p, p.mask)
        return (not ok) and a["passed"], msg, p

    try:
        d, msg, p = differs(items)
        if not d:
            print("does not differ now:", msg)
            return None
        n = 2
        while len(items) >= 2 and runs < max_runs:
            chunk = max(1, len(items) // n)
            reduced = False
            for i in range(0, len(items), chunk):
                cand = items[:i] + items[i + chunk:]
                if not cand:
                    continue
                d, m2, p2 = differs(cand)
                if d:
                    items, msg, p = cand, m2, p2
                    n = max(n - 1, 2)
                    reduced = True
                    print(f"  {len(items)} items: {msg}", flush=True)
                    break
            if not reduced:
                if chunk == 1:
                    break
                n = min(len(items), 2 * n)
        print(f"shrunk to {len(items)} items in {runs} runs: {msg}")
        print(p.source)
        return items, p, msg
    finally:
        _close_board(transport, harness)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("action", choices=("socket", "sim", "gate", "show", "list", "cover", "shrink", "triage", "triage-all"))
    ap.add_argument("set", nargs="?")
    ap.add_argument("names", nargs="*")
    ap.add_argument("--tag", default="")
    ap.add_argument("--ref", default="socket")
    ap.add_argument("--cand", default="sim")
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    if a.action in ("socket", "sim"):
        run_set(a.set, a.action, a.tag, a.names or None, a.jobs)
    elif a.action == "gate":
        ok, _ = gate(a.set, a.ref, a.cand, a.names or None, quiet=True)
        return 0 if ok else 1
    elif a.action == "show":
        for n in a.names:
            show(a.set, n, a.ref, a.cand)
    elif a.action == "list":
        for n in a.names:
            print(programs(a.set, [n])[n].source)
    elif a.action == "cover":
        rows = cover([a.set] + a.names if a.set else list(SETS))
        for k in sorted(rows):
            print(f"{k:60s} {rows[k][0]:7d} {rows[k][1]:5d}")
    elif a.action == "triage-all":
        triage_all(a.set, a.ref, a.cand, a.names or None, a.jobs)
    elif a.action == "triage":
        for n in a.names:
            triage(a.set, n, a.ref, a.cand)
    elif a.action == "shrink":
        for n in a.names:
            shrink(a.set, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
