"""CLKOUT on P07 (work order 34): the core v2's CLKOUT in simulation against the socket.

Three parts:

  A  the scope receipts that already carry CLKOUT (ready.py's rdy_s8 / rdy_s2 and rdy_ms8 /
     ms4 / ms2: CLKOUT on P07 at fX/8, fX/4, fX/2; validation/v35s/receipts/rdy-*-socket*-scope
     .json). Every run of those programs is simulated with the scope on the model lane; per probe
     cycle, CLKOUT's edges (ticks from the tick /MREQ's fall is seen, in [-clk, 3 clk)) against
     the socket's, the period and the duty.
  B  stop_probe.py's two references (HALT, STOP: 0F 9E) at fX/2 after the characterize prelude:
     CLKOUT after the last bus cycle (silicon: build/validation/v35s/stop_probe.json, quoted in
     STOP_PROBE below).
  C  new programs, simulated and AWAITING A SOCKET CAPTURE (`socket` runs them on the board):
       clk_en8 / clk_en2  the PMC0 store that selects CLKOUT and the one that deselects it, with
                          the P07 latch at 1 and at 0, and with PM07 = 1 (fX/8, fX/2)
       clk_pck            PRC.PCK changed with CLKOUT out: 8->4, 4->2, 2->8, 8->2, 2->4, 4->8
       clk_halt           HALT at fX/2 and its release by NMI
       clk_stop           STOP at fX/2 and its release by NMI (the 2^19-clock settling count)
     Each store sits a fixed sled after an anchor (OUT FE40h k): the receipts keep every edge of
     CLKOUT and the bus strobes, so the place of the first CLKOUT edge after the store, and of the
     period change, can be read against the anchor's /MREQ fall.

  D  (work order 34s) the socket follow-ups written after C's first capture: one PCK change a
     run at several sleds, the same store with no change, STOP at each PCK and at several sleds,
     NMI's place against the stop and the restart (`dprograms`; `socket D`, `sim D`, or names).
     Receipts clk-followup-<backend>.json; read by build/overseer/wo34s/*.py. Not gated.

C's five programs have socket receipts (clk-<name>-socket{,-2}.json, 2026-11-20); the gate's
part C now compares them (clk_halt EQUAL; the others DIFFER: build/overseer/wo34s/RESULTS.md).

The core moves CLKOUT on the fabric tick its bus pins move on (v35_sfr.sv, "work order 34");
silicon's CLKOUT leads its bus pins by one scope tick at every PCK (A's receipts: CLKOUT falls at
-1 from /MREQ's fall, rises 1 tick before a write's R/W falls). That tick is the parts' output
delays under a 30 ns sample, not a clock: the comparison adds OFFSET = 1 to silicon's CLKOUT
ticks and requires equality.

    PYTHONPATH=host/src:. python3 -m validation.v35s.clkout sim [A|B|C ...] [--jobs 3]
    PYTHONPATH=host/src:. python3 -m validation.v35s.clkout summary
    PYTHONPATH=host/src:. python3 -m validation.v35s.clkout gate
    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.clkout socket --socket-fitted [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.clkout emit

Receipts: validation/v35s/receipts/clk-<name>-<backend>.json.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from . import ready
from .wtc import Asm, base_image, ORG, STACK_TOP, M_BEGIN, M_END

ROOT = Path(__file__).resolve().parents[2]
RECEIPTS = ROOT / "validation/v35s/receipts"
PROGRAMS_DIR = ROOT / "validation/v35s/programs"
OFFSET = 1                      # silicon's CLKOUT edge leads its bus pins' by one scope tick
SIGS = ("clkout", "mreq_n", "mstb_n", "iostb_n", "rw", "refrq_n")
A_PROGS = ("rdy_s8", "rdy_s2", "rdy_ms8", "rdy_ms4", "rdy_ms2")
M_BANK, M_EVENT, M_SUB = 0xFF10, 0xFF12, 0xFE44

# stop_probe.py's receipt (build/validation/v35s/stop_probe.json, 2026-10-12, harness build 2,
# image sha256 da17e2e0...): fX/2, x_half 2 (8 ticks a clock), RFM FCh. The last bus cycle's
# start tick (the lane's), the CLKOUT edges after it, the last CLKOUT edge's tick; the capture
# ran to its end in HALT (not complete: CLKOUT never stopped), was complete in STOP
STOP_PROBE = {
    "F4": dict(last_bus_tick=9968, edges_after=8975, last_clkout=45865, complete=False),
    "0F 9E": dict(last_bus_tick=9968, edges_after=25, last_clkout=10065, complete=False),
}


def receipt_path(name, backend):
    return RECEIPTS / f"clk-{name}-{backend}.json"


def load(name, backend):
    p = receipt_path(name, backend)
    return json.loads(p.read_text()) if p.exists() else None


def save(name, backend, rec):
    receipt_path(name, backend).write_text(json.dumps(rec, separators=(",", ":")) + "\n")


def stamp(text):
    return dict(date=datetime.datetime.now().isoformat(timespec="seconds"),
                program_sha256=hashlib.sha256(text).hexdigest())


def _sim():
    from .traps import _sim as sim
    return sim()


# ------------------------------------------------------------------ A: the READY scope programs
def a_prog(name):
    return ready.programs()[name] if name.startswith("rdy_s") else ready.mprograms()[name]


def a_keys(name):
    prog = a_prog(name)
    if isinstance(prog, ready.MProgram):
        return [(k, 0, 2, (d, h, ready.M_TRIG, ready.M_BLOCKS)) for k, d, h in prog.mruns()]
    return [(ready.run_key(n, x), n, x, None) for n, x in prog.runs()]


def a_slim(res, clk):
    """A scope_one result reduced to what CLKOUT needs: per cycle its kind, the strobe's and
    R/W's edges and CLKOUT's edges in [-clk, 3 clk) from /MREQ's fall."""
    out = []
    for cy in res["cycles"]:
        if "error" in cy:
            out.append(dict(error=cy["error"]))
            continue
        out.append(dict(kind=cy["kind"], address=cy["address"], length=cy["length"],
                        stb_fall=cy["stb_fall"], rw_fall=cy["rw_fall"],
                        rise=[t for t in cy["clk_rise"] if -clk <= t < 3 * clk],
                        fall=[t for t in cy["clk_fall"] if -clk <= t < 3 * clk]))
    return dict(passed=res["passed"], capture=res["capture"], cycles=out)


def _a_job(args):
    name, key, n, x, m = args
    from .traps import _stim
    prog = a_prog(name)
    transport, harness = _sim()
    try:
        _stim(harness, prog)
        res = ready.scope_one(harness, prog, "model", n, x, m=m, full=False)
        return key, a_slim(res, prog.clk)
    finally:
        transport.close()


def a_sim(names, jobs):
    from multiprocessing import Pool
    with Pool(jobs) as pool:
        for name in names:
            prog = a_prog(name)
            runs = dict(pool.map(_a_job, [(name, k, n, x, m) for k, n, x, m in a_keys(name)]))
            save(name, "sim", dict(program=name, clk_ticks=prog.clk, backend="sim",
                                   ticks="from the tick /MREQ's fall is seen; 30 ns",
                                   runs=runs, **stamp(prog.build()["text"])))
            bad = [k for k, r in runs.items() if not r["passed"] or r["capture"] != "complete"]
            print(f"{name}: {len(runs)} runs simulated; not passed / capture incomplete: {bad or 'none'}",
                  flush=True)


def a_socket(name, tag):
    """The socket's cycles from ready.py's scope receipt, reduced as a_slim."""
    rec = ready.load(name, f"socket{tag}-scope")
    clk = rec["clk_ticks"]
    return rec, {k: a_slim(r, clk) for k, r in rec["runs"].items()}


def a_shape(cy, clk):
    """(CLKOUT's falls and rises from /MREQ's fall, period, high time)."""
    rise, fall = cy["rise"], cy["fall"]
    per = sorted({b - a for a, b in zip(rise, rise[1:])} | {b - a for a, b in zip(fall, fall[1:])})
    high = sorted({next((f for f in fall if f > r), None) - r for r in rise
                   if next((f for f in fall if f > r), None) is not None})
    return fall, rise, per, high


def a_table(name, backend):
    """Per program and cycle kind: CLKOUT's edges against the bus pins (ticks from /MREQ's fall)."""
    prog = a_prog(name)
    clk = prog.clk
    if backend.startswith("socket"):
        rec, runs = a_socket(name, backend[len("socket"):])
    else:
        rec = load(name, backend)
        if rec is None:
            print(f"{name} [{backend}]: no receipt")
            return
        runs = rec["runs"]
    rows = Counter()
    for r in runs.values():
        for cy in r["cycles"]:
            if "error" in cy:
                continue
            fall, rise, per, high = a_shape(cy, clk)
            rows[(cy["kind"], tuple(fall), tuple(rise), tuple(per), tuple(high), cy["stb_fall"],
                  cy["rw_fall"])] += 1
    print(f"{name} [{backend}] a clock {clk} ticks; ticks from /MREQ's fall as seen; {len(runs)} runs")
    print("    cycles  kind  CLKOUT falls          CLKOUT rises          period  high  strobe falls  R/W falls")
    for (kind, fall, rise, per, high, sf, rf), c in sorted(rows.items(), key=lambda x: (x[0][0], -x[1])):
        print(f"    {c:>6}  {kind:<4}  {str(list(fall)):<20}  {str(list(rise)):<20}  {str(list(per)):<6}  "
              f"{str(list(high)):<4}  {sf:>12}  {'' if rf is None else rf:>9}")


def a_gate(name, tag=""):
    """Every run and cycle: the sim's CLKOUT edges equal the socket's + OFFSET; the kinds and
    addresses in order equal. Returns (ok, line)."""
    prog = a_prog(name)
    sim = load(name, "sim")
    if sim is None:
        return False, f"{name}: no simulation receipt (run `clkout sim A`)"
    srec, sock = a_socket(name, tag)
    if srec["program_sha256"] != sim["program_sha256"]:
        return False, f"{name}: the receipts are of different programs"
    clk = prog.clk
    n = same = 0
    diff = []
    for key, s in sock.items():
        c = sim["runs"].get(key)
        if c is None:
            continue
        for i, (p, q) in enumerate(zip(s["cycles"], c["cycles"])):
            if "error" in p or "error" in q:
                continue
            n += 1
            lo, hi = -clk + OFFSET, 3 * clk - 1     # the window both sides cover
            ps = ([t + OFFSET for t in p["fall"] if lo <= t + OFFSET < hi],
                  [t + OFFSET for t in p["rise"] if lo <= t + OFFSET < hi])
            qs = ([t for t in q["fall"] if lo <= t < hi], [t for t in q["rise"] if lo <= t < hi])
            if (p["kind"], p["address"]) == (q["kind"], q["address"]) and ps == qs:
                same += 1
            else:
                diff.append((key, i, p["kind"], ps, qs))
        if len(s["cycles"]) != len(c["cycles"]):
            diff.append((key, -1, "cycle count", len(s["cycles"]), len(c["cycles"])))
    line = (f"{name}{tag}: {'EQUAL' if not diff and n else 'DIFFER'} ({same} of {n} probe cycles: CLKOUT's "
            f"edges = socket + {OFFSET} tick)")
    for d in diff[:4]:
        line += f"\n    run {d[0]} cycle {d[1]} {d[2]}: socket+{OFFSET} {d[3]} / sim {d[4]}"
    return not diff and n > 0, line


# ------------------------------------------------------------------ B: stop_probe's references
def b_source(opcode):
    from .characterize import program
    from .stop_probe import body
    return program(prc=0x4C, wtc=0x0000, rfm=0xFC).split("    XOR AW, AW")[0] + body(opcode)


def _b_job(opcode):
    from .asm import assemble
    from .runner import FLAG_REFRESH, Transaction, reset_image
    from .scope import Scope, edges
    from .stop_probe import LIMIT
    transport, harness = _sim()
    try:
        harness.configure(x_half=2)
        harness.load(reset_image(assemble(b_source(opcode), org=0x100)))
        scope = Scope(harness.debug)
        scope.configure("model")
        result = harness.run("model", LIMIT)
        capture = scope.download()
        trace = [Transaction(**row) for row in result["model_trace"]]
        memory = [t for t in trace if not t.flags & FLAG_REFRESH]
        last_bus = memory[-1].start if memory else 0
        clock = [(e.tick, e.value) for e in edges(capture, ["clkout"])]
        after = [(t, v) for t, v in clock if t > last_bus]
        return opcode, dict(
            opcode=opcode, passed=result["passed"], status=result["status"],
            capture_complete=capture.complete, last_bus=memory[-1].describe() if memory else None,
            last_bus_tick=last_bus, edges_after=len(after),
            last_clkout=clock[-1][0] if clock else None,
            last_level=clock[-1][1] if clock else None,
            first_after=[[t - last_bus, v] for t, v in after[:40]])
    finally:
        transport.close()


def b_sim(jobs):
    from multiprocessing import Pool
    with Pool(min(jobs, 2)) as pool:
        runs = dict(pool.map(_b_job, list(STOP_PROBE)))
    text = "".join(b_source(o) for o in STOP_PROBE).encode()
    save("stop_probe", "sim", dict(program="stop_probe", backend="sim", runs=runs, **stamp(text)))
    for o, r in runs.items():
        print(f"stop_probe {o}: last bus {r['last_bus_tick']} edges after {r['edges_after']} last CLKOUT "
              f"{r['last_clkout']} level {r['last_level']}", flush=True)


def b_report():
    """(ok for what is built, lines). HALT: CLKOUT runs on to the capture's end; STOP: silicon's
    CLKOUT stops high, its last edge a rise 97 ticks after the last bus cycle's start (25 edges)."""
    rec = load("stop_probe", "sim")
    if rec is None:
        return False, ["stop_probe: no simulation receipt (run `clkout sim B`)"]
    lines, ok = [], True
    for o, si in STOP_PROBE.items():
        r = rec["runs"][o]
        if o == "F4":
            good = r["edges_after"] > 1000 and not r["capture_complete"]
            ok &= good
            lines.append(f"HALT: socket {si['edges_after']} CLKOUT edges after the last bus cycle (to the capture's "
                         f"end); sim {r['edges_after']} (to the capture's end: {not r['capture_complete']}): "
                         f"{'EQUAL' if good else 'DIFFER'} (CLKOUT runs in HALT)")
        else:
            d = si["last_clkout"] - si["last_bus_tick"]
            good = r["edges_after"] == si["edges_after"] and r["last_clkout"] - r["last_bus_tick"] == d + OFFSET
            lines.append(f"STOP: socket CLKOUT stops after {si['edges_after']} edges, the last a rise at last bus "
                         f"+{d}; sim {r['edges_after']} edges, last at +{r['last_clkout'] - r['last_bus_tick']} level "
                         f"{r['last_level']}: {'EQUAL' if good else 'DIFFER'}"
                         + ("" if good else " (NOT BUILT: CLKOUT does not stop in STOP; rtl.md)"))
    return ok, lines


# ------------------------------------------------------------------ C: new programs (awaiting a socket capture)
NMI_STIM = {"entries": [{"event": 1, "delay": 3000, "hold": 400, "levels": {"NMI": 0}}], "pins": []}


class CProgram:
    def __init__(self, name, note, body, prc=None, stim=None, limit=3_000_000):
        self.name, self.note, self.body, self.prc, self.stim, self.limit = name, note, body, prc, stim, limit
        self.clk = ready.PRC_CLK[prc]
        self._built = None

    def build(self):
        if self._built:
            return self._built
        mem, code = base_image(True)
        a = Asm()
        a.op([0xFA], "DI")
        a.mov_r("AW", 0)
        a.mov_sr("SS")
        a.mov_r("SP", STACK_TOP)
        a.mov_sr("DS0")
        a.seg("DS1", 0xF000)
        a.sfr_w(0xE1, 0xEC)                 # RFM: no refresh (the core serves none)
        a.sfr_w(0xE8, 0x0000, word=True)    # WTC: no waits
        self.body(a)
        a.mov_r("DW", 0xFF00)
        a.op([0xEE], "OUT DW, AL")
        a.op([0xF4], "HALT")
        a.label("done")
        a.rel([0xEB], "done", "BR")
        if self.stim:
            a.label("nmi")
            a.out_w(M_SUB, 0x004E)
            a.op([0x83, 0xC4, 0x06], "ADD SP, 6")
            a.rel([0xE9], "cont", "BR", wide=True)
        text = a.finish()
        for i, v in enumerate(text):
            mem[ORG + i] = v
        if self.stim:
            for i, v in enumerate(a.labels["nmi"].to_bytes(2, "little") + b"\0\0"):
                mem[0x00008 + i] = v
        for i, v in enumerate(bytes([0xEA, ORG & 0xFF, ORG >> 8, 0, 0])):
            mem[0xFFFF0 + i] = v
        segments = {}
        for pg in sorted({x >> 12 for x in mem}):
            segments[pg << 12] = bytes(mem[pg << 12 | o] for o in range(0x1000))
        self._built = dict(text=text, lines=a.lines, segments=segments)
        return self._built

    def source(self):
        b = self.build()
        out = [f"; {self.name}: {self.note}",
               "; Generated by validation/v35s/clkout.py emit (work order 34); socket receipts "
               f"validation/v35s/receipts/clk-{self.name}-socket{{,-2}}.json (2026-11-20)"]
        for bs, text in b["lines"]:
            out.append(text if not bs else "    DB " + ", ".join(
                f"{v:02X}h" if v < 0xA0 else f"0{v:02X}h" for v in bs) + f"    ; {text}")
        return "\n".join(out) + "\n"


def clkout_on(a, p0=0x55):
    """CLKOUT on P07 (programs/clocks.s): T2 released, the latch and PM0, PMC0, T2 the CPU's."""
    a.out_w(M_BANK, 0x0001)
    a.sfr_w(0x00, p0)
    a.sfr_w(0x01, 0x00)
    a.sfr_w(0x02, 0x80)
    a.out_w(M_BANK, 0x0002)


def store_at(a, k, off, v, after=12):
    """Anchor k (OUT FE40h, k), four NOPs, the store, a sled."""
    a.out_w(M_BEGIN, k)
    a.nop(4)
    a.sfr_w(off, v)
    a.nop(after)


def body_en(prc):
    def body(a):
        if prc is not None:
            a.sfr_w(0xEB, prc)
        a.out_w(M_BANK, 0x0001)             # T2 released while P0 becomes an output
        a.sfr_w(0x00, 0x80)                 # the latch: P07 = 1
        a.sfr_w(0x01, 0x00)                 # PM0: outputs
        a.out_w(M_BANK, 0x0002)             # T2 the CPU's: P07 visible at the latch's 1
        a.nop(8)
        for k, (off, v, what) in enumerate([
                (0x02, 0x80, "PMC0 80h: CLKOUT selected, the latch 1"),
                (0x02, 0x00, "PMC0 00h: the port again, the latch 1"),
                (0x00, 0x00, "P0 00h: the latch's own store (the store's landing, as reference)"),
                (0x02, 0x80, "PMC0 80h: CLKOUT selected, the latch 0"),
                (0x02, 0x00, "PMC0 00h: the port again, the latch 0"),
                (0x01, 0x80, "PM0 80h: P07 an input (released)"),
                (0x02, 0x80, "PMC0 80h with PM07 = 1"),
                (0x02, 0x00, "PMC0 00h with PM07 = 1")]):
            a.lines.append((b"", f"; ---- {k}: {what}"))
            store_at(a, k, off, v)
        a.out_w(M_END, 0)
    return body


def body_pck(a):
    clkout_on(a)
    a.nop(8)
    for k, prc in enumerate([0x4D, 0x4C, 0x4E, 0x4C, 0x4D, 0x4E]):
        a.lines.append((b"", f"; ---- {k}: PRC {prc:02X}h"))
        store_at(a, k, 0xEB, prc, after=16)
    a.out_w(M_END, 0)


def body_standby(op):
    def body(a):
        clkout_on(a)
        a.sfr_w(0xEB, 0x4C)
        a.nop(8)
        a.out_w(M_BEGIN, 0)
        a.out_w(M_EVENT, 0x0001)            # the event: NMI 3000 ticks later
        a.op(op[0], op[1])
        a.nop(4)
        a.label("cont")
        a.out_w(M_END, 0)
    return body


def cprograms():
    progs = [
        CProgram("clk_en8", "the PMC0 stores that select and deselect CLKOUT on P07, at fX/8", body_en(None)),
        CProgram("clk_en2", "the PMC0 stores that select and deselect CLKOUT on P07, at fX/2", body_en(0x4C), prc=0x4C),
        CProgram("clk_pck", "PRC.PCK changed with CLKOUT on P07: 8->4, 4->2, 2->8, 8->2, 2->4, 4->8", body_pck),
        CProgram("clk_halt", "HALT at fX/2 with CLKOUT on P07, released by NMI", body_standby(([0xF4], "HALT")),
                 prc=0x4C, stim=NMI_STIM),
        CProgram("clk_stop", "STOP at fX/2 with CLKOUT on P07, released by NMI (2^19 clocks)",
                 body_standby(([0x0F, 0x9E], "STOP")), prc=0x4C, stim=NMI_STIM, limit=8_000_000),
    ]
    return {p.name: p for p in progs}


C_KEEP = 40_000                 # the edges a receipt keeps


def c_run(harness, prog, lane):
    from .runner import load_stimulus, REST_LEVELS
    from .scope import Scope, edges
    harness.debug.write16(0x08, 2)
    harness.debug.write16(0x0A, 0)
    ready.set_m(harness, None)
    harness.debug.write16(0x8E, REST_LEVELS)
    if harness.version >= 2:
        load_stimulus(harness, prog.stim)
    harness.load(prog.build()["segments"])
    scope = Scope(harness.debug)
    scope.configure(lane)
    result = harness.run(lane, prog.limit)
    capture = scope.download()
    ev = edges(capture, SIGS)
    rows = [[t["start"], t["address"], t["flags"], t["end"]] for t in result[f"{lane}_trace"]]
    return dict(passed=result["passed"], status=result["status"], capture=capture.reason,
                capture_last=capture.last_tick, edges_total=len(ev),
                edges=[[e.tick, e.signal, e.value] for e in ev[:C_KEEP]], trace=rows)


def _c_job(name):
    prog = cprograms()[name]
    transport, harness = _sim()
    try:
        return name, c_run(harness, prog, "model")
    finally:
        transport.close()


def c_record(prog, res, backend):
    save(prog.name, backend, dict(program=prog.name, note=prog.note, clk_ticks=prog.clk, backend=backend,
                                  awaiting_socket=backend == "sim",
                                  ticks="scope ticks of 30 ns from the run's start", run=res,
                                  **stamp(prog.build()["text"])))
    print(f"{prog.name} [{backend}]: passed {res['passed']} capture {res['capture']} edges {res['edges_total']}",
          flush=True)


def c_sim(names, jobs):
    from multiprocessing import Pool
    progs = cprograms()
    with Pool(min(jobs, len(names))) as pool:
        for name, res in pool.map(_c_job, names):
            c_record(progs[name], res, "sim")


def c_windows(rec):
    """Per anchor (an OUT FE40h k cycle; FE42h ends the last): the anchor's /MREQ fall (scope tick)
    and every CLKOUT edge and bus strobe edge up to the next anchor, ticks from that fall."""
    run = rec["run"]
    ev = run["edges"]
    fl_io, fl_read = 2, 1
    anchors = [r for r in run["trace"] if r[2] & fl_io and not r[2] & fl_read and r[1] in (M_BEGIN, M_END)]
    out = []
    for i, r in enumerate(anchors):
        t0 = next((e[0] for e in ev if e[1] == "mreq_n" and e[2] == 0 and e[0] >= r[0] - 6), None)
        if t0 is None:
            continue
        t1 = anchors[i + 1][0] - 6 if i + 1 < len(anchors) else t0 + 200 * rec["clk_ticks"]
        win = [[e[0] - t0, e[1], e[2]] for e in ev if t0 - 2 * rec["clk_ticks"] <= e[0] < t1]
        out.append(dict(anchor=r[1], t0=t0, edges=win))
    return out


def c_summary(name, backend):
    rec = load(name, backend)
    if rec is None:
        print(f"{name} [{backend}]: no receipt")
        return
    run = rec["run"]
    clk = rec["clk_ticks"]
    print(f"{name} [{backend}]{' AWAITING A SOCKET CAPTURE' if rec.get('awaiting_socket') else ''}: {rec['note']}; "
          f"passed {run['passed']} capture {run['capture']} ({run['edges_total']} edges)")
    if name.startswith("clk_en") or name == "clk_pck":
        for k, w in enumerate(c_windows(rec)):
            ck = [(t, v) for t, s, v in w["edges"] if s == "clkout"]
            p0 = [(t, v) for t, s, v in w["edges"] if s == "clkout" and t >= 0][:6]
            per = [b[0] - a[0] for a, b in zip(ck, ck[1:]) if a[1] == 1 and b[1] == 0 or a[1] == 0 and b[1] == 1]
            strobes = [(t, s, v) for t, s, v in w["edges"] if s in ("mreq_n",) and v == 0 and t > 0]
            print(f"  anchor {k} (/MREQ of OUT {w['anchor']:04X}h at {w['t0']}): CLKOUT edges {p0} ...; "
                  f"half periods {sorted(Counter(per).items())}; next /MREQ falls {[t for t, _, _ in strobes[:4]]}")
    else:
        ev = run["edges"]
        ck = [(t, v) for t, s, v in ev if s == "clkout"]
        rows = run["trace"]
        gaps = [(a, b) for a, b in zip(ck, ck[1:]) if b[0] - a[0] > 4 * clk]
        print(f"  trace {len(rows)} records; CLKOUT {len(ck)} edges kept; gaps longer than 4 clocks: "
              f"{[(a[0], a[1], b[0] - a[0]) for a, b in gaps[:6]]}")
        if rows:
            print(f"  last records: {[(r[0], hex(r[1]), r[2]) for r in rows[-4:]]}")


def c_gate(name):
    """A socket capture of a C program against the simulation: per anchor, CLKOUT's edges in the
    window (socket + OFFSET) equal. None when no socket receipt exists."""
    s, c = load(name, "socket"), load(name, "sim")
    if s is None:
        return None, f"{name}: AWAITING A SOCKET CAPTURE (simulated: {'yes' if c else 'no'})"
    if c is None or s["program_sha256"] != c["program_sha256"]:
        return False, f"{name}: no simulation receipt of the same program"
    diff = []
    ws, wc = c_windows(s), c_windows(c)
    for k, (p, q) in enumerate(zip(ws, wc)):
        a = [(t + OFFSET, v) for t, sg, v in p["edges"] if sg == "clkout"]
        b = [(t, v) for t, sg, v in q["edges"] if sg == "clkout"]
        lo = max(min((t for t, _ in a), default=0), min((t for t, _ in b), default=0))
        hi = min(max((t for t, _ in a), default=0), max((t for t, _ in b), default=0))
        a = [x for x in a if lo <= x[0] <= hi]
        b = [x for x in b if lo <= x[0] <= hi]
        if a != b:
            i = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            diff.append((k, a[i:i + 3], b[i:i + 3]))
    line = f"{name}: {'EQUAL' if not diff and len(ws) == len(wc) else 'DIFFER'} ({len(ws)} / {len(wc)} anchors)"
    for k, a, b in diff[:4]:
        line += f"\n    anchor {k}: socket+{OFFSET} {a} / sim {b}"
    return not diff and len(ws) == len(wc), line


def c_socket(names, tag):
    from .traps import _board, _close_board
    progs = cprograms()
    transport, harness = _board()
    try:
        for name in names:
            c_record(progs[name], c_run(harness, progs[name], "socket"), f"socket{tag}")
    finally:
        _close_board(transport, harness)


# ------------------------------------------------------------------ D: socket follow-ups (work order 34s)
# Written after the first socket capture of C (build/overseer/wo34s/RESULTS.md):
#   clk_pk<a><b>_<s>   one PRC.PCK change a -> b (fX/a to fX/b) with CLKOUT out, the store after
#                      the sled SLEDS[s] (the store's place against the clock moved by whole
#                      clocks); clk_pck's 2 -> 4 store stopped the socket's bus, so every change is
#                      a run of its own. _x3 / _x4: the same at x_half 3 / 4 (a slower X1)
#   clk_st<p>_<s>      STOP at fX/p, the sled STOP_SLEDS[s] between the event OUT and STOP
#   clk_sn_<d>         STOP at fX/2, NMI 3000 + d ticks after the event (the restart against NMI);
#                      the run ends before the settling count does
#   clk_sl             STOP at fX/2, the scope from tick SL_START on (the settling count's end)
# One receipt per backend: clk-followup-<backend>.json, {"runs": {name: record}}.
PCK_CODE = {2: 0x4C, 4: 0x4D, 8: 0x4E}
SLEDS = [[], [([0x40], "INC AW")], [([0x93], "XCHG AW, BW")], [([0x40], "INC AW"), ([0x93], "XCHG AW, BW")],
         [([0x90], "NOP")],
         [([0xF8], "CLR1 CY")], [([0x98], "CVTBW")], [([0x40], "INC AW")] * 2, [([0xF8], "CLR1 CY")] * 3]
STOP_SLEDS = [[], [([0x90], "NOP")], [([0x90], "NOP")] * 2, [([0x40], "INC AW")], [([0x93], "XCHG AW, BW")],
              [([0x90], "NOP")] * 12, [([0x40], "INC AW"), ([0x93], "XCHG AW, BW")]]
SL_START = 4_205_000


def body_pk(a_div, b_div, sled):
    def body(a):
        if a_div != 8:
            a.sfr_w(0xEB, PCK_CODE[a_div])
        clkout_on(a)
        a.nop(8)
        a.out_w(M_BEGIN, 0)
        a.nop(4)
        for bs, text in sled:
            a.op(bs, text)
        a.sfr_w(0xEB, PCK_CODE[b_div])
        a.nop(16)
        a.out_w(M_END, 0)
    return body


def body_pq(first, seq):
    def body(a):
        if first != 8:
            a.sfr_w(0xEB, PCK_CODE[first])
        clkout_on(a)
        a.nop(8)
        for k, d in enumerate(seq):
            store_at(a, k, 0xEB, PCK_CODE[d], after=16)
        a.out_w(M_END, 0)
    return body


def body_stop(div, sled):
    def body(a):
        clkout_on(a)
        if div != 8:
            a.sfr_w(0xEB, PCK_CODE[div])
        a.nop(8)
        a.out_w(M_BEGIN, 0)
        a.out_w(M_EVENT, 0x0001)
        for bs, text in sled:
            a.op(bs, text)
        a.op([0x0F, 0x9E], "STOP")
        a.nop(4)
        a.label("cont")
        a.out_w(M_END, 0)
    return body


def nmi_stim(delay):
    return {"entries": [{"event": 1, "delay": delay, "hold": 400, "levels": {"NMI": 0}}], "pins": []}


def dprograms():
    progs = []
    for a_div, b_div in ((8, 4), (4, 2), (2, 8), (8, 2), (2, 4), (4, 8)):
        for s, sled in enumerate(SLEDS[:5]):
            progs.append(CProgram(f"clk_pk{a_div}{b_div}_{s}", f"PCK fX/{a_div} to fX/{b_div}, sled {s}",
                                  body_pk(a_div, b_div, sled), prc=PCK_CODE[a_div], limit=400_000))
    for x in (3, 4):
        p = CProgram(f"clk_pk24_0_x{x}", f"PCK fX/2 to fX/4 at x_half {x}", body_pk(2, 4, SLEDS[0]),
                     prc=0x4C, limit=800_000)
        p.x_half = x
        progs.append(p)
    for div, sleds, limit in ((2, range(len(STOP_SLEDS)), 8_000_000), (4, (0, 5), 10_000_000),
                              (8, (0, 5), 19_000_000)):
        for s in sleds:
            progs.append(CProgram(f"clk_st{div}_{s}", f"STOP at fX/{div}, sled {s}, released by NMI",
                                  body_stop(div, STOP_SLEDS[s]), prc=PCK_CODE[div], stim=NMI_STIM, limit=limit))
    for d in range(1, 8):
        progs.append(CProgram(f"clk_sn_{d}", f"STOP at fX/2, NMI {3000 + d} ticks after the event",
                              body_stop(2, STOP_SLEDS[0]), prc=0x4C, stim=nmi_stim(3000 + d), limit=200_000))
    # second batch: the store of the value PRC already holds (no change: the bus cycles' places in
    # clocks for each sled), more sleds out of fX/2, clk_pck's last changes in one run, and NMI
    # before the clock has stopped
    for div in (2, 4, 8):
        for s, sled in enumerate(SLEDS):
            progs.append(CProgram(f"clk_pk{div}{div}_{s}", f"PRC stored with the PCK it holds (fX/{div}), sled {s}",
                                  body_pk(div, div, sled), prc=PCK_CODE[div], limit=400_000))
    for b_div in (4, 8):
        for s in range(5, len(SLEDS)):
            progs.append(CProgram(f"clk_pk2{b_div}_{s}", f"PCK fX/2 to fX/{b_div}, sled {s}",
                                  body_pk(2, b_div, SLEDS[s]), prc=0x4C, limit=400_000))
    for tag, first, seq in (("a", 8, (2, 4)), ("b", 2, (8, 2, 4)), ("c", 4, (2, 8, 2, 4)), ("d", 8, (4, 2, 8, 2, 4))):
        progs.append(CProgram(f"clk_pq_{tag}", f"PCK from fX/{first}: " + ", ".join(f"fX/{d}" for d in seq)
                              + " (clk_pck's last changes)", body_pq(first, seq), prc=PCK_CODE[first], limit=400_000))
    for d in (16, 32, 48, 64, 72, 80, 88, 104):
        progs.append(CProgram(f"clk_se_{d}", f"STOP at fX/2, NMI {d} ticks after the event (before the clock stops)",
                              body_stop(2, STOP_SLEDS[0]), prc=0x4C, stim=nmi_stim(d), limit=4_600_000))
    p = CProgram("clk_sl", f"STOP at fX/2, the scope from tick {SL_START}", body_stop(2, STOP_SLEDS[0]),
                 prc=0x4C, stim=NMI_STIM, limit=8_000_000)
    p.scope_start = SL_START
    progs.append(p)
    return {p.name: p for p in progs}


def d_run(harness, prog, lane):
    """c_run with the program's x_half and scope start; the receipt keeps X1's phase too (the
    tick of the first X1 rise at or after the first bus cycle)."""
    from .runner import load_stimulus, REST_LEVELS
    from .scope import Scope, edges
    x_half = getattr(prog, "x_half", 2)
    harness.debug.write16(0x08, x_half)
    harness.debug.write16(0x0A, 0)
    ready.set_m(harness, None)
    harness.debug.write16(0x8E, REST_LEVELS)
    if harness.version >= 2:
        load_stimulus(harness, prog.stim)
    harness.load(prog.build()["segments"])
    scope = Scope(harness.debug)
    scope.configure(lane, start=getattr(prog, "scope_start", 0))
    result = harness.run(lane, prog.limit)
    capture = scope.download()
    ev = edges(capture, SIGS + ("x1",))
    rows = [[t["start"], t["address"], t["flags"], t["end"]] for t in result[f"{lane}_trace"]]
    first = rows[0][0] if rows else 0
    x1 = next((e.tick for e in ev if e.signal == "x1" and e.value == 1 and e.tick >= first), None)
    ev = [e for e in ev if e.signal != "x1"]
    if x_half != 2:
        harness.debug.write16(0x08, 2)
    return d_slim(dict(passed=result["passed"], status=result["status"], capture=capture.reason,
                       capture_first=capture.first_tick, capture_last=capture.last_tick, x_half=x_half, x1_rise=x1,
                       edges_total=len(ev), edges=[[e.tick, e.signal, e.value] for e in ev[:C_KEEP]], trace=rows))


D_TAIL = 6000                   # the ticks of CLKOUT a follow-up receipt keeps after the last strobe edge


def d_slim(run):
    """A follow-up receipt keeps every edge up to D_TAIL ticks after the last strobe or R/W edge.
    The CLKOUT edges after that (a stopped bus, the settling count) are reduced to `clkout_tail`:
    the first and last dropped edge and the half periods between them (with the last kept edge)."""
    ev = run["edges"]
    last = max((e[0] for e in ev if e[1] != "clkout"), default=None)
    if last is None or "clkout_tail" in run:
        return run
    keep = [e for e in ev if e[0] <= last + D_TAIL]
    drop = ev[len(keep):]
    if drop:
        ticks = [keep[-1][0]] + [e[0] for e in drop] if keep and keep[-1][1] == "clkout" else [e[0] for e in drop]
        run["clkout_tail"] = dict(first=drop[0], last=drop[-1], edges=len(drop),
                                  half_periods=sorted(Counter(b - a for a, b in zip(ticks, ticks[1:])).items()))
        run["edges"] = keep
    return run


def d_record(prog, res, backend):
    return dict(program=prog.name, note=prog.note, clk_ticks=prog.clk * getattr(prog, "x_half", 2) // 2,
                backend=backend, run=res, **stamp(prog.build()["text"]))


def d_save(backend, recs):
    p = receipt_path("followup", backend)
    old = json.loads(p.read_text())["runs"] if p.exists() else {}
    old.update(recs)
    p.write_text(json.dumps(dict(backend=backend, ticks="scope ticks of 30 ns from the run's start",
                                 runs=old), separators=(",", ":")) + "\n")


def _d_job(name):
    prog = dprograms()[name]
    transport, harness = _sim()
    try:
        return name, d_record(prog, d_run(harness, prog, "model"), "sim")
    finally:
        transport.close()


def d_sim(names, jobs):
    from multiprocessing import Pool
    recs = {}
    with Pool(min(jobs, len(names))) as pool:
        for name, rec in pool.imap(_d_job, names):
            recs[name] = rec
            print(f"{name} [sim]: passed {rec['run']['passed']} capture {rec['run']['capture']}", flush=True)
    d_save("sim", recs)


def d_socket(names, tag):
    from .traps import _board, _close_board
    progs = dprograms()
    transport, harness = _board()
    recs = {}
    try:
        for name in names:
            rec = d_record(progs[name], d_run(harness, progs[name], "socket"), f"socket{tag}")
            recs[name] = rec
            print(f"{name} [socket{tag}]: passed {rec['run']['passed']} status {rec['run']['status']:#x} "
                  f"capture {rec['run']['capture']} edges {rec['run']['edges_total']}", flush=True)
    finally:
        _close_board(transport, harness)
        d_save(f"socket{tag}", recs)


# ------------------------------------------------------------------ main
def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("sim", "summary", "gate", "socket", "emit"))
    p.add_argument("parts", nargs="*", help="sim: A B C D or program names; socket: C program names, or D / "
                   "follow-up names (work order 34s)")
    p.add_argument("--jobs", type=int, default=3)
    p.add_argument("--tag", default="")
    p.add_argument("--socket-fitted", action="store_true")
    a = p.parse_args()
    cp = cprograms()
    if a.action == "emit":
        for name, prog in cp.items():
            (PROGRAMS_DIR / f"{name}.s").write_text(prog.source())
            if prog.stim:
                (PROGRAMS_DIR / f"{name}.stim.json").write_text(json.dumps(prog.stim, indent=1) + "\n")
            print(f"{name}: {len(prog.build()['text'])} bytes")
        return 0
    dp = dprograms()
    dnames = list(dp) if "D" in a.parts else [x for x in a.parts if x in dp]
    if a.action == "sim":
        if dnames:
            d_sim(dnames, a.jobs)
            if not [x for x in a.parts if x not in dp and x != "D"]:
                return 0
        parts = [x for x in a.parts if x not in dp and x != "D"] or ["A", "B", "C"]
        if "A" in parts or any(x in A_PROGS for x in parts):
            a_sim([x for x in parts if x in A_PROGS] or list(A_PROGS), a.jobs)
        if "B" in parts:
            b_sim(a.jobs)
        if "C" in parts or any(x in cp for x in parts):
            c_sim([x for x in parts if x in cp] or list(cp), a.jobs)
        return 0
    if a.action == "socket":
        if not a.socket_fitted:
            p.error("the socket action needs --socket-fitted")
        if dnames:
            d_socket(dnames, a.tag)
            return 0
        c_socket([x for x in a.parts if x in cp] or list(cp), a.tag)
        return 0
    if a.action == "summary":
        for name in A_PROGS:
            a_table(name, "socket")
            a_table(name, "sim")
        _, lines = b_report()
        print("\n".join(lines))
        for name in cp:
            c_summary(name, "sim")
            if load(name, "socket"):
                c_summary(name, "socket")
        return 0
    ok = True
    for name in A_PROGS:
        for tag in ("", "-2"):
            good, line = a_gate(name, tag)
            ok &= good
            print(line)
    good, lines = b_report()
    ok &= good
    print("\n".join(lines))
    for name in cp:
        good, line = c_gate(name)
        if good is not None:
            ok &= good
        print(line)
    print("clkout gate:", "PASS (what is built and has a socket receipt)" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
