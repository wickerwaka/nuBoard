"""C1: the bus unit's scripted request stream from the frozen model, and its RTL bench.

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --family F0 F0w \\
        [--ids ...] [--jobs 8] [--keep DIR] [--show N]

For each corpus run of the families (the silicon record read through `normalize` as score.py
does: the chain, its base and its refresh anchor), the frozen model (sim/frozen/) runs the
chain with a clock log; the log's append is wrapped so that, at the end of every model clock
(where Machine._clock_row is taken), the bus unit's state, the stamps it keeps and the EU's
data latch are copied. Nothing in the model changes: the Machine is built as
frozen machine.run_record builds it, and its trace is checked against run_record's.

From that the vector file holds, per model clock t: the bus cycle the arbiter started on t
(kind, address, width, data, the disp_io extension, whether a read's datum fills the data
latch), the EU's other data-latch fills on t, an RFM write taking effect on t; and the
expected values: the window signals before and after the choice (the frozen BusUnit's own
methods on the state of the end of t-1 and of t), the delivery on t, and the bus unit's
registered state at the end of t in the A2 representations (v35_biu.sv's state bundle).
Then the cycle list, for the pin check. The bench (fpga/v35s/v35_biu_tb.sv and
v35_biu_tb.cpp, built by fpga/v35s/build_biu_tb.sh into build/fpga/v35s/biu-tb/) feeds the
requests at their clocks and checks all of it on every clock, the strobe edges included,
and prints the cycles the RTL ran; this driver compares those with the model's (start,
length, kind, address, width, data, delivery clock) and scores the RTL's trace (as
trace rows through `normalize`) against silicon and the model, as `score --rtl` would.

C2, the queue (--queue; --joint with the bus unit): see "C2: the queue" below. The queue
bench (fpga/v35s/v35_queue_tb.sv and .cpp, fpga/v35s/build_queue_tb.sh, binary in
build/fpga/v35s/queue-tb/) runs v35_queue.sv on the recorded ops and checks its state after
the delivery, after every op and at the end of every clock, and every read; --joint runs it
beside v35_biu.sv with the fetches the RTL queue's own and checks the bus unit as above.

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --queue --family F0 F2 F9 F11
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --joint --family F0 F2 F9 F11

C3, the decoder and the EU (--eu; --joint3 with the RTL queue and bus unit, the arbiter
scripted); C4, the whole core with the arbiter in RTL (--core: v35_chain_core.sv, its bench
fpga/v35s/v35_core_tb.sv and .cpp, fpga/v35s/build_core_tb.sh, binary in build/fpga/v35s/core-tb/):
see "C3" and "C4" below.

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --core --family F4 F5 F6 F7 F10

C5, refresh (--core): the refresh controller (v35_refresh.sv) in the core and the refresh's rules
in the arbiter and the EU; refresh-on runs record the controller's state after phase R and at the
end of every clock (RefreshRecorder), the EU's refresh touches and the arbiter's bus history (format
V35ARB-2). --eu and --joint3 (the scripted-arbiter benches) still run refresh-off chains only.

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --core --family F8 F13 F17 F18

D1, the register file and the EA adder (in the EU): every start's operand record is the RTL's,
compared at every start. D2, the function (vectors V35EU-3): the register file, the PSW, the
segment registers and the data are nuV30's; the benches compare the register file before every
start and every EU cycle's datum with the functional reference's (funcref.py), serve the reads
from a memory the EU's own writes update, and leave the state rows' functional fields out.
--regfile runs the register file's unit bench (fpga/v35s/build_rf_tb.sh) on the families' forms
and every ALU form; sst.py --rtl runs SingleStepTests through it: see "D1, D2" below.

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --regfile --family F0 F23

(WP75) The fortieth fit's mechanisms (xfer_abort=word: the abort op's val and the queue's xfer;
cond_gap=own; burst_count=dw; lea_io=recover; lea_room=ir: the EU's lea_ea op; prepare_sync=run;
imm_latch=wait) and, E3, the string forms: a REP form's step list is the frozen model's flat list
(e_k), its element loop expanded by the EU from rtlgen's compact template, the addresses from
IX / IY by the element, the element count from CW and a compare's exit from the RTL's own data
(x_sn, x_sc: not in the state rows, checked at the next start against the walk's, the P line's
last three fields); str_hold=hold is the EU's str_held op. No run is outside the RTL. The
whole corpus, 33 lists (F32 and F33 are generator-only):

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --core --family F0 F0w \
        F1 F2 F3 F4 F5 F6 F7 F8 F9 F10 F11 F12 F13 F14 F15 F16 F17 F18 F19 F20 F21 F22 F23 F24 \
        F25 F26 F27 F28 F29 F30 F31
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BENCH = ROOT / "build" / "fpga" / "v35s" / "biu-tb" / "Vv35_biu_tb"
KINDS = ("none", "fetch", "read", "write", "io_read", "io_write", "refresh")
BWIDTHS = ("word", "lo", "hi")
FORMAT = "V35BIU-1"

# per-clock columns (the bench reads them in this order)
COLUMNS = (
    "t", "has_row",
    "start", "kind", "addr", "width", "data", "ext", "latch",
    "fill", "rfm_load", "rfm_value", "data_in",
    "busy", "free", "in_wait", "finf", "fprev", "fsince", "io_win", "wl_busy",
    "busy_x", "free_x", "in_wait_x", "finf_x", "fprev_x", "fsince_x", "io_win_x", "wl_busy_x",
    "done", "dkind", "daddr", "dwidth", "ddata",
    "valid", "skind", "pos", "len", "sext", "sint", "slatch", "saddr", "swidth", "sdata",
    "gap", "sfsince", "io_tail", "wl", "rlen",
)


@dataclass
class Snap:
    current: object
    last_end: int
    last_fetch_end: int
    last_io_end: int
    refresh_length: int
    wlatch_until: int


class _Log(list):
    """Machine.clock_log: each row appended at the end of a clock, with a copy of the bus
    unit's state and the EU's data latch at that moment (and the queue recorder's end of
    the clock, C2)."""

    def __init__(self, machine, queue_rec=None, eu_rec=None, arb_rec=None, ref_rec=None):
        super().__init__()
        self.m = machine
        self.rec = queue_rec
        self.eu_rec = eu_rec        # (C3) the decoder/EU recorder, after the queue's
        self.arb_rec = arb_rec      # (C4) the arbiter's recorder, after the EU's
        self.ref_rec = ref_rec      # (C5) the refresh controller's recorder, after the arbiter's
        self.snaps: list[Snap] = []

    def append(self, row):
        super().append(row)
        b = self.m.bus
        self.snaps.append(Snap(b.current, b.last_end, b.last_fetch_end, b.last_io_end,
                               b.refresh_length, self.m.eu.wlatch_until))
        if self.rec is not None:
            self.rec.row()
        if self.eu_rec is not None:
            self.eu_rec.row()
        if self.arb_rec is not None:
            self.arb_rec.row()
        if self.ref_rec is not None:
            self.ref_rec.row()


def run_model(chain, cfg, chain_base: int):
    """(Machine, _Log, cycles) of the frozen model on chain, built as frozen
    machine.run_record builds it (refresh on: _prelude_run's phase)."""
    from .sim.frozen import machine as fm
    from .types import refresh_any
    phase = None
    if refresh_any(chain):
        phase = (64 - fm.POP_COUNTER[(chain.rfm, chain.wtc)]) % 128
    m = fm.Machine(chain, cfg, chain_base, phase, 0)
    log = _Log(m)
    m.clock_log = log
    cycles = m.run()
    ref = fm.run_record(chain, cfg, chain_base, None, phase, 0)["socket_trace"]
    if fm.trace_rows(cycles) != ref:
        raise RuntimeError(f"{chain.id}: the logged run differs from run_record's")
    return m, log, cycles


def _bus_at(snap: Snap, mem: int, io: int):
    from .sim.frozen.bus import BusUnit
    b = BusUnit(mem, io, 0, snap.refresh_length)
    b.current, b.last_end = snap.current, snap.last_end
    b.last_fetch_end, b.last_io_end = snap.last_fetch_end, snap.last_io_end
    return b


def vectors(chain, cfg, chain_base: int, run=None) -> tuple[str, list]:
    """(the vector file's text, the model's cycles). run: (Machine, _Log, cycles) of a run
    already made (run_model's, or run_queue_model's for the joint bench)."""
    from .sim.frozen.bus import SFR_PAGE
    from .sim.frozen.machine import waits_of
    from .types import refresh_length
    m, log, cycles = run if run is not None else run_model(chain, cfg, chain_base)
    mem, io = waits_of(chain)
    G, R, WL = cfg.min_gap, cfg.io_recover, cfg.wlatch
    eu = m.eu
    init = Snap(None, -10, -10, -10, refresh_length(chain.rfm), 0)
    snaps = log.snaps
    T = len(snaps)
    by_start = {}
    for c in cycles:
        if c.start in by_start:
            raise RuntimeError(f"{chain.id}: two cycles start on {c.start}")
        by_start[c.start] = c
    by_end = {c.end: c for c in cycles}

    def latch_of(c):
        return int(c.owner is eu and c.kind in ("read", "io_read"))

    def since(b, t):
        return 0 if b.fetch_inflight(t) else min(15, t - b.last_fetch_end)   # (WP75) 4 bits

    lines = [f"{FORMAT} {chain.id} {chain.wtc:04x} {chain.rfm:02x} {T + 1} {len(cycles)}"]
    for t in range(T + 1):
        prev = snaps[t - 1] if t else init
        row = snaps[t] if t < T else None
        v = dict.fromkeys(COLUMNS, 0)
        v["t"], v["has_row"] = t, int(row is not None)
        c = by_start.get(t)
        if c is not None:
            if row is None:
                raise RuntimeError(f"{chain.id}: a start on the clock without a row")
            ext = row.last_end == c.end + 1
            if ext and c.kind.startswith("io") and row.last_io_end != c.end + 1:
                raise RuntimeError(f"{chain.id}: last_end moved without last_io_end at {t}")
            if not ext and row.last_end != c.end:
                raise RuntimeError(f"{chain.id}: last_end {row.last_end} at {t}")
            v.update(start=1, kind=KINDS.index(c.kind), addr=c.addr, width=BWIDTHS.index(c.width),
                     data=c.data & 0xFFFF, ext=int(ext), latch=latch_of(c))
        d = by_end.get(t - 1)
        if d is not None:
            v.update(done=1, dkind=KINDS.index(d.kind), daddr=d.addr,
                     dwidth=BWIDTHS.index(d.width), ddata=-1)
            internal = d.kind == "write" and d.addr >= SFR_PAGE
            if d.kind in ("fetch", "read", "io_read") and not internal:
                dv = getattr(d, "rdata", d.data)    # (D2) an EU read's: the delivered word
                v["data_in"] = dv & 0xFFFF
                v["ddata"] = dv & 0xFFFF
        # the data latch: the bus unit's own fills (an EU read's delivery, a write's issue)
        fill_c = d is not None and latch_of(d)
        own = fill_c or (c is not None and c.kind == "write")
        wl_c = max(prev.wlatch_until, t + WL) if fill_c else prev.wlatch_until
        if row is not None:
            want = max(prev.wlatch_until, t + WL) if own else prev.wlatch_until
            if row.wlatch_until != want:
                if row.wlatch_until != max(prev.wlatch_until, t + WL):
                    raise RuntimeError(f"{chain.id}: the data latch at {t} is "
                                       f"{row.wlatch_until}, no fill explains it")
                v["fill"] = 1
            if row.refresh_length != prev.refresh_length:
                v.update(rfm_load=1, rfm_value=(row.refresh_length - 3) << 2)
        b = _bus_at(prev, mem, io)
        v.update(busy=int(b.busy(t)), free=int(b.free(t)), in_wait=int(b.in_wait(t)),
                 finf=int(b.fetch_inflight(t)), fprev=int(b.last_fetch_end == t - 1),
                 fsince=since(b, t), io_win=int(t <= b.last_io_end + R),
                 wl_busy=int(t < wl_c))
        if row is not None:
            a = _bus_at(row, mem, io)
            v.update(busy_x=int(a.busy(t)), free_x=int(a.free(t)), in_wait_x=int(a.in_wait(t)),
                     finf_x=int(a.fetch_inflight(t)), fprev_x=int(a.last_fetch_end == t - 1),
                     fsince_x=since(a, t), io_win_x=int(t <= a.last_io_end + R),
                     wl_busy_x=int(t < row.wlatch_until))
            cur = row.current
            if cur is not None:
                if not cur.start <= t <= cur.end:
                    raise RuntimeError(f"{chain.id}: bus.current does not cover {t}")
                v.update(valid=1, skind=KINDS.index(cur.kind), pos=t - cur.start, len=cur.length,
                         sext=int(row.last_end == cur.end + 1),
                         sint=int(cur.kind == "write" and cur.addr >= SFR_PAGE),
                         slatch=latch_of(cur), saddr=cur.addr, swidth=BWIDTHS.index(cur.width),
                         sdata=cur.data & 0xFFFF)
            top = max(t, cur.end) if cur is not None else t
            io_top = max(t, cur.end) if cur is not None and cur.kind.startswith("io") else t
            v.update(gap=max(0, row.last_end + G - top), sfsince=since(a, t),
                     io_tail=max(0, row.last_io_end + R - io_top),
                     wl=max(0, row.wlatch_until - t), rlen=row.refresh_length)
        lines.append(" ".join(str(v[k]) for k in COLUMNS))
    for c in cycles:
        internal = int(c.kind == "write" and c.addr >= SFR_PAGE)
        lines.append(f"C {c.start} {c.end} {KINDS.index(c.kind)} {c.addr} "
                     f"{BWIDTHS.index(c.width)} {c.data & 0xFFFF} {internal}")
    return "\n".join(lines) + "\n", cycles


# The bench ---------------------------------------------------------------------------------

@dataclass
class Result:
    run_id: str
    cycles: int = 0                 # the model's
    rtl_cycles: int = 0             # the RTL's
    exact_cycles: int = 0           # start, length, kind, address, width, data equal
    deliveries: int = 0             # delivery clocks equal (end + 1)
    clocks: int = 0
    signal_bad: int = 0             # per-clock window signals / delivery checks failed
    state_bad: int = 0              # per-clock state-bundle fields failed
    pin_bad: int = 0                # strobe / pin checks failed
    first: str = ""                 # the bench's first failure
    rtl_exact: bool | None = None   # the RTL trace scored against silicon
    model_exact: bool | None = None  # the model against silicon
    rtl_model_exact: bool | None = None
    error: str = ""
    not_modelled: str = ""          # (WP68) a run outside the RTL (string forms)

    @property
    def ok(self) -> bool:
        return (not self.error and not self.not_modelled and self.cycles == self.rtl_cycles == self.exact_cycles
                == self.deliveries and not (self.signal_bad or self.state_bad or self.pin_bad))


def parse_bench(text: str) -> dict:
    out = {"cyc": [], "del": [], "fail": [], "summary": {}}
    for line in text.splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == "CYC":
            out["cyc"].append(tuple(int(x) for x in p[1:]))
        elif p[0] == "DEL":
            out["del"].append(tuple(int(x) for x in p[1:]))
        elif p[0] == "FAIL":
            out["fail"].append(line)
        elif p[0] == "SUMMARY":
            out["summary"] = {k: int(v) for k, v in (x.split("=") for x in p[1:])}
    return out


def rtl_trace(cyc: list) -> list:
    """The RTL's cycles as trace rows (frozen machine.trace_rows on equivalent Cycles)."""
    from .sim.frozen.bus import Cycle
    from .sim.frozen.machine import trace_rows
    return trace_rows([Cycle(KINDS[k], addr, BWIDTHS[w], s, n, data)
                       for s, n, k, addr, w, data in cyc])


def check_run(rec: dict, cfg, keep: Path | None = None) -> Result:
    from .normalize import normalize
    from .score import model_one, relabel_refresh, score
    from .sim.frozen.machine import refresh_anchor
    s = normalize(rec)
    res = Result(s.run_id)
    try:
        text, cycles = vectors(s.chain, cfg, s.chain_base)
    except NotModelled as e:
        res.not_modelled = str(e)
        return res
    except Exception as e:      # noqa: BLE001
        res.error = f"vectors: {type(e).__name__}: {e}"
        return res
    res.cycles = len(cycles)
    with tempfile.TemporaryDirectory() as tmp:
        path = (keep / f"{s.run_id}.vec") if keep is not None else Path(tmp) / "run.vec"
        path.write_text(text)
        p = subprocess.run([str(BENCH), str(path)], capture_output=True, text=True, cwd=ROOT)
    if keep is not None:
        (keep / f"{s.run_id}.out").write_text(p.stdout + p.stderr)
    b = parse_bench(p.stdout)
    if p.returncode not in (0, 1) or not b["summary"]:
        res.error = f"bench exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}"
        return res
    sm = b["summary"]
    res.clocks, res.signal_bad = sm.get("clocks", 0), sm.get("signal_bad", 0)
    res.state_bad, res.pin_bad = sm.get("state_bad", 0), sm.get("pin_bad", 0)
    res.first = b["fail"][0] if b["fail"] else ""
    res.rtl_cycles = len(b["cyc"])
    model = [(c.start, c.length, KINDS.index(c.kind), c.addr, BWIDTHS.index(c.width),
              c.data & 0xFFFF) for c in cycles]
    res.exact_cycles = sum(1 for x, y in zip(model, b["cyc"]) if x == y)
    dels = {t for t, _ in b["del"]}
    res.deliveries = sum(1 for c in cycles if c.end + 1 in dels)
    # three-way: the RTL's trace through normalize, against silicon and the model
    try:
        rrec = {"chain": rec["chain"], "chain_base": s.chain_base, "complete": True,
                "socket_trace": rtl_trace(b["cyc"])}
        n = normalize(rrec, strict=False)
        anchor = refresh_anchor(s, events=False)
        relabel_refresh(n, anchor[1] if anchor is not None else 0)
        _, mn, msc = model_one(s, cfg)
        res.model_exact = msc.exact
        res.rtl_exact = score(s, n).exact
        res.rtl_model_exact = score(mn, n).exact if mn is not None else False
    except Exception as e:      # noqa: BLE001
        res.error = f"score: {type(e).__name__}: {e}"
    return res


# C2: the queue -------------------------------------------------------------------------------
#
# The frozen Queue is driven by four machines inside a clock, in an order fixed by the code
# (Machine.run's phases, the EU's step loop, the arbiter's choice): the bus unit's delivery,
# the EU's starts, takes, flag re-evaluations and stores, the decoder's takes and IR loads, the
# arbiter's reads and writes, the post-issue pass. The queue's run is recorded as it happens
# (QueueRecorder: the Queue instance's class is swapped for a subclass whose methods and
# attribute stores log the calls the other machines make, then do exactly what the frozen
# methods do), each clock as: the delivery (phase C, and the aborted cycle's end, A), the ops
# in model order, the end of the clock (phase E). An op is one queue method the others call
# (take, commit, issue, abort, wants_fetch, room, ...) or one store site of theirs (the EU's
# `q.flag = q.room(t) >= 2` after a retry, the arbiter's refresh drop, ...), with the decoder's
# and the EU's state the queue reads at that moment. After every op the queue's state is taken
# in the A2 representations (QFIELDS), so the bench checks the RTL op by op.

QBENCH = ROOT / "build" / "fpga" / "v35s" / "queue-tb" / "Vv35_queue_tb"
QFORMAT = "V35QUEUE-1"
NSLOT = 16                   # ops per clock the RTL chains (v35_queue.sv NSLOT)

# op codes (v35_queue.sv V35_QOP_*), in this order
QOPS = ("nop", "take", "commit", "irload", "start", "flush", "disp", "halt", "eval",
        "shift_end", "retry_end", "retry_set", "reraise", "shift_set", "shift_hold",
        "drop_retry", "want", "asked", "requesting", "room", "triple", "stored", "avail",
        "issue", "abort", "drop", "beat", "lost_eval", "lost_halt", "lost_after", "redate",
        "io_held_clr", "io_held_set", "t4", "nop_hold", "gdisp", "lea_ea", "str_held",
        "str_raise")                                # (WP77) str_fetch=hold, CW = 0
READ_OPS = frozenset(("want", "asked", "requesting", "room", "triple", "stored", "avail"))
PURE_READS = frozenset(("room", "triple", "stored", "avail"))

# The queue's state in the A2 representations (v35_queue.sv's v35_qstate_t, in declaration
# order, MSB first): (name, bits). Stamps are flags for `== t` (and `== t-1`), offsets from
# the clock for the ones ahead, an age for requested_at.
QFIELDS = (
    ("count", 4),            # len(bytes): stored bytes plus the latched one (inside a clock
                             # up to 8: a word delivered into six, taken from that clock)
    ("data", 64),            # the bytes, head in the low byte (8 x 8)
    ("unc", 2),              # len(uncommitted): taken, not yet committed (take_commit=at_end)
    ("latched", 1),          # word_latch=byte_d: the delivered word's second byte waits
    ("latch_full", 1),       # ... behind a full queue
    ("flag", 1),             # the request flag
    ("rq_valid", 1),         # requested_at is set
    ("rq_age", 7),           # t - requested_at (saturating at 127)
    ("inflight", 1),
    ("fetch_addr", 20),      # the prefetch pointer (linear)
    ("ab_valid", 1),         # an aborted cycle runs (abort_end)
    ("ab_left", 2),          # abort_end - t
    ("ab_this", 1),          # abort_t == start_t (this instruction started on it)
    ("ab_now", 1),           # abort_t == t
    ("retry", 1),
    ("retry_loop", 1),
    ("abort_ref", 1),
    ("rt_valid", 1),         # retry_at is set
    ("rt_off", 10),          # retry_at - t (signed)
    ("shift_held", 1),
    ("sh_valid", 1),         # shift_until is set
    ("sh_off", 10),          # shift_until - t (signed)
    ("nop_held", 1),         # nop_held set and no start since
    ("io_held", 1),          # io_held set
    ("io_started", 1),       # ... and an instruction started since
    ("slot_fetch", 1),
    ("slot_word", 1),
    ("ar_pend", 1),          # after_refresh >= t
    ("ar_off", 3),           # after_refresh - t (while pending)
    ("ar_fetch", 1),         # after_refresh == the last issued fetch's start
    ("beat_eval", 1),
    ("refresh_beaten", 1),
    ("dropped", 1),
    ("drop_hold", 1),
    ("lost_start", 1),       # lost_start is set (compared t > lost_start on later clocks)
    ("lost_eval", 1),        # lost_eval == t
    ("la_valid", 1),         # lost_after is set
    ("la_off", 2),           # lost_after - t
    ("io_run_now", 1),       # io_run_at == t
    ("io_run_next", 1),      # io_run_at == t + 1
    ("t4_now", 1),           # t4_at == t
    ("t4_next", 1),          # t4_at == t + 1
    ("b2b_now", 1),          # b2b_at == t
    ("b2b_next", 1),         # b2b_at == t + 1
    ("halted", 1),
    ("discard", 1),          # the word in flight is dropped on arrival (a flush)
    ("fh_valid", 1),         # flush_held is set
    ("fh_off", 4),           # max(0, flush_held - t)
    ("gd_valid", 1),         # gdisp_until is set (grp_disp=hold; the arbiter reads t < it)
    ("gd_off", 2),           # max(0, gdisp_until - t)
    ("xfer", 1),             # (WP72) xfer_abort: a transfer's aborted cycle runs
    ("le_valid", 1),         # (WP72) lea_room=ir: lea_ea is set ...
    ("le_off", 2),           # ... max(0, lea_ea's end - t)
    ("sd_valid", 1),         # (E3) str_hold=hold: str_held is set ...
    ("sd_off", 4),           # ... max(0, str_held - t) (WP77: xfetch clocks) ...
    ("sd_inf", 1),           # ... (WP77) str_fetch=hold: str_held is infinite (none from here)
    ("sr_valid", 1),         # (WP77) str_fetch=hold: str_raise is set ...
    ("sr_off", 3),           # ... max(0, str_raise - t)
    ("ox_valid", 1),         # (WP77) xfer_odd=idle: odd_xfer is set ...
    ("ox_now", 1),           # ... == t
    ("ox_fed", 1),           # ... past it: a fetch was on the bus on that clock (odd_fed)
    ("arrived_now", 1),      # arrived_t == t
    ("removed_now", 1),      # removed_t == t
    ("ir_now", 1),           # ir_t == t
    ("qport_now", 1),        # qport_t == t
    ("disp_now", 1),         # disp_t == t
    ("mate_now", 1),         # mate_t == t
    ("take_now", 1),         # take_t == t
    ("take_prev", 1),        # take_t == t - 1
    ("start_now", 1),        # start_t == t
    ("latch_in_now", 1),     # latch_in_t == t
    ("starts", 2),           # instructions started, saturating at 3 (triple reads > 2)
)
QSTATE_W = sum(w for _, w in QFIELDS)
# the decoder's and the EU's state an op reads (v35_queue.sv v35_qsnap_t, MSB first)
DSNAP = ("ir", "need0", "ir_hold", "ea", "imm16")


def _bits(v: int, w: int) -> int:
    return v & ((1 << w) - 1)


def qstate(m, t: int) -> dict:
    """The frozen queue's state on clock t in the A2 representations (QFIELDS)."""
    q, eu, bus = m.queue, m.eu, m.bus
    data = 0
    for i, (a, _) in enumerate(q.bytes):
        data |= q.byte_at(a) << (8 * i)
    fetches = [c for c in bus.cycles if c.kind == "fetch"]
    last_fetch = fetches[-1].start if fetches else None
    ar = q.after_refresh
    s = {
        "count": len(q.bytes), "data": data, "unc": len(q.uncommitted),
        "latched": q.latched, "latch_full": int(q.latch_full), "flag": int(q.flag),
        "rq_valid": int(q.requested_at is not None),
        "rq_age": 0 if q.requested_at is None else min(127, t - q.requested_at),
        "inflight": int(q.inflight), "fetch_addr": q.fetch_addr,
        "ab_valid": int(q.abort_end is not None),
        "ab_left": 0 if q.abort_end is None else q.abort_end - t,
        "ab_this": int(q.abort_t is not None and q.abort_t == q.start_t),
        "ab_now": int(q.abort_t == t),
        "retry": int(q.retry), "retry_loop": int(q.retry_loop), "abort_ref": int(q.abort_ref),
        "rt_valid": int(q.retry_at is not None),
        "rt_off": 0 if q.retry_at is None else q.retry_at - t,
        "shift_held": int(q.shift_held), "sh_valid": int(q.shift_until is not None),
        "sh_off": 0 if q.shift_until is None else q.shift_until - t,
        "nop_held": int(q.nop_held is not None
                        and not (q.start_t is not None and q.start_t > q.nop_held)),
        "io_held": int(q.io_held is not None),
        "io_started": int(q.io_held is not None and q.start_t is not None
                          and q.start_t > q.io_held),
        "slot_fetch": int(q.slot_fetch), "slot_word": int(q.slot_word),
        "ar_pend": int(ar is not None and ar >= t),
        "ar_off": ar - t if ar is not None and ar >= t else 0,
        "ar_fetch": int(ar is not None and ar == last_fetch),
        "beat_eval": int(q.beat_eval), "refresh_beaten": int(q.refresh_beaten),
        "dropped": int(q.dropped), "drop_hold": int(q.drop_hold),
        "lost_start": int(q.lost_start is not None), "lost_eval": int(q.lost_eval == t),
        "la_valid": int(q.lost_after is not None),
        "la_off": 0 if q.lost_after is None else q.lost_after - t,
        "io_run_now": int(q.io_run_at == t), "io_run_next": int(q.io_run_at == t + 1),
        "t4_now": int(q.t4_at == t), "t4_next": int(q.t4_at == t + 1),
        "b2b_now": int(q.b2b_at == t), "b2b_next": int(q.b2b_at == t + 1),
        "halted": int(q.halted), "discard": int(q.discard),
        "fh_valid": int(q.flush_held is not None),
        "fh_off": 0 if q.flush_held is None else max(0, q.flush_held - t),
        "gd_valid": int(q.gdisp_until is not None),
        "gd_off": 0 if q.gdisp_until is None else max(0, q.gdisp_until - t),
        "xfer": int(bool(q.xfer_abort)),
        "le_valid": int(q.lea_ea is not None),
        "le_off": 0 if q.lea_ea is None else max(0, q.lea_ea[1] - t),
        "sd_valid": int(q.str_held is not None),
        "sd_off": (0 if q.str_held is None or q.str_held == float("inf")
                   else max(0, q.str_held - t)),
        "sd_inf": int(q.str_held == float("inf")),
        "sr_valid": int(q.str_raise is not None),
        "sr_off": 0 if q.str_raise is None else max(0, q.str_raise - t),
        "ox_valid": int(q.odd_xfer is not None),
        "ox_now": int(q.odd_xfer == t),
        "ox_fed": int(q.odd_xfer is not None and t > q.odd_xfer and _odd_fed(q, bus)),
        "arrived_now": int(q.arrived_t == t), "removed_now": int(q.removed_t == t),
        "ir_now": int(q.ir_t == t), "qport_now": int(q.qport_t == t),
        "disp_now": int(q.disp_t == t), "mate_now": int(q.mate_t == t),
        "take_now": int(q.take_t == t), "take_prev": int(q.take_t == t - 1),
        "start_now": int(q.start_t == t), "latch_in_now": int(q.latch_in_t == t),
        "starts": min(3, q.starts),
    }
    for k, w in QFIELDS:
        v = s[k]
        if not (-(1 << (w - 1)) <= v < (1 << w)):
            raise RuntimeError(f"{m.chain.id}: queue {k}={v} at {t} does not fit {w} bits")
    if len(q.bytes) > 8 or q.latched > 1 or len(q.uncommitted) > 3:
        raise RuntimeError(f"{m.chain.id}: queue storage out of range at {t}")
    return s


def _odd_fed(q, bus) -> bool:
    """(WP77) xfer_odd=idle: queue._odd_fed's value, without computing it into the queue: a
    fetch on the bus (in flight, or issued) on the odd-address transfer's start clock (the RTL
    keeps it from the end of that clock: in flight, not an aborted cycle)."""
    if q.odd_fed is not None:
        return q.odd_fed
    s = q.odd_xfer
    return any(c.kind == "fetch" and c.start <= s <= c.end for c in bus.cycles[-3:])


def qstate_text(s: dict) -> str:
    return " ".join(str(_bits(s[k], w)) for k, w in QFIELDS)


def dsnap(m, t: int) -> int:
    """The decoder's and the EU's state the queue reads (DSNAP, bit 0 first)."""
    d, eu = m.decoder, m.eu
    bits = (d.ir is not None, d.need == 0, bool(d.ir_hold),
            d.ea_end is not None and t < d.ea_end,
            getattr(eu, "cls", None) == "imm" and eu.imm_bytes == 2)
    return sum(int(b) << i for i, b in enumerate(bits))


@dataclass
class QOp:
    code: str
    a: int = 0
    b: int = 0
    val: int = 0
    snap: int = 0
    rd: int | None = None       # a read's (or a take's byte) expected value
    state: dict | None = None   # the queue's state after it
    events: list | None = None  # the model's events (calls and stores) it stands for
    phase: str = ""             # (C3) the phase of the model clock it is in (EURecorder)


@dataclass
class QClock:
    t: int
    c_done: int = 0             # phase C: a cycle ended on t-1
    c_fetch: int = 0
    c_refresh: int = 0
    c_odd: int = 0
    c_data: int = 0
    c_snap: int = 0
    c_state: dict | None = None  # after C and A
    ops: list | None = None
    e_fetch_end: int = 0        # phase E: a fetch's last clock is t
    e_io: int = 0               # the EU runs an IN or OUT (cls), not halted, its I/O to come
    e_out: int = 0              # ... an OUT
    e_snap: int = 0
    e_state: dict | None = None  # the end of the clock (the row)


_QMETHODS = ("take", "commit", "commit_one", "wants_fetch", "asked", "requesting", "room",
             "counted", "free", "triple", "stored", "available", "issue", "abort", "flush",
             "arrive", "retry_after", "abort_done", "end_clock", "_evaluates", "latch_blocks",
             "occupancy", "refill_target", "check", "begin_clock", "_raised", "_io_form",
             "_taking", "_nop_held", "_imm16", "_latched_now", "_port_busy", "preload")
_READ_NAMES = {"wants_fetch": "want", "asked": "asked", "requesting": "requesting",
               "room": "room", "free": "room", "counted": "room", "triple": "triple",
               "stored": "stored", "available": "avail"}


# (WP75) none since the fortieth fit's catch-up: xfer_abort is the abort op's val, lea_ea and
# str_held are the EU's ops
DEAD_QUEUE_STORES = frozenset()


class QueueRecorder:
    """Records the frozen queue's calls and stores per clock (the module comment above)."""

    def __init__(self, m, merge: bool = True):
        self.m = m
        self.merge = merge          # (C3: False) keep a read repeated with nothing between
        self.phase_of = None        # (C3) the EU recorder's phase, stamped on each op
        self.on_call = None         # (C3) told of every call the others make (name, args, result)
        self.on_end = None          # (C3) told when phase E begins (end_clock is called)
        self.t = 0
        self.depth = 0
        self.clocks: list[QClock] = []
        self.clock = QClock(0, ops=[])
        self.cur: QOp | None = None
        q = m.queue
        base = type(q)
        ns = {n: self._wrap(base, n) for n in _QMETHODS}
        rec = self

        def setattr_(obj, k, v):
            if rec.depth == 0 and k not in DEAD_QUEUE_STORES:
                rec._event(("set", k, v, sys._getframe(1).f_code.co_name))
            object.__setattr__(obj, k, v)
        ns["__setattr__"] = setattr_
        q.__class__ = type("RecordedQueue", (base,), ns)

    def _wrap(self, base, name):
        orig = getattr(base, name)
        rec = self

        def w(obj, *a, **k):
            if rec.depth:
                return orig(obj, *a, **k)
            caller = sys._getframe(1).f_code.co_name
            ev = ["call", name, (a, k), caller, None]
            if name == "end_clock":
                rec.end_inputs()
            elif caller != "_clock_row":            # the row's reads, after the clock
                rec._event(ev)
            rec.depth += 1
            try:
                r = orig(obj, *a, **k)
            finally:
                rec.depth -= 1
            ev[4] = r
            if rec.on_call is not None and caller != "_clock_row":
                rec.on_call(name, a, k, r)
            return r
        return w

    # the stream of events -> ops
    def _finish(self):
        """The current op is complete: the queue's state now is its state after."""
        if self.cur is not None:
            self._close(self.cur)
            self.cur.state = qstate(self.m, self.t)
            self.cur = None

    def _event(self, ev):
        m, t, ck = self.m, self.t, self.clock
        if ev[0] == "call" and ev[1] in ("arrive", "retry_after", "abort_done"):
            if ck.ops or self.cur is not None:
                raise RuntimeError(f"{m.chain.id}: {ev[1]} after the clock's ops at {t}")
            if ev[1] == "arrive":
                ck.c_fetch = 1
            elif ev[1] == "retry_after":
                ck.c_refresh = int(ev[2][0][1:2] == ("refresh",) or ev[2][1].get("kind") == "refresh")
            ck.c_snap = dsnap(m, t)     # (WP72) abort_done too: xfer_abort's room
            return
        if ck.c_state is None:
            ck.c_state = qstate(m, t)
        cur = self.cur
        if cur is not None and self._continues(cur, ev):
            cur.events.append(ev)
            return
        if (ev[0] == "set" and ev[1] == "flag" and cur is not None and cur.code == "room"
                and len(cur.events) == 1 and cur.events[0][3] == ev[3] != "_refresh"):
            cur.code = "eval"                        # q.flag = q.room(t) >= 2
            cur.events.append(ev)
            return
        self._finish()
        op = self._start(ev)
        if op is None:
            raise RuntimeError(f"{m.chain.id}: queue event {ev[:2]} from {ev[-1] if ev[0] == 'set' else ev[3]} "
                               f"at {t} starts no op")
        op.snap = dsnap(m, t)
        op.events = [ev]
        if self.phase_of is not None:
            op.phase = self.phase_of()
        self.cur = op
        ck.ops.append(op)

    def _start(self, ev):
        t = self.t
        if ev[0] == "call":
            name, (a, k), caller = ev[1], ev[2], ev[3]
            if name == "take":
                return QOp("irload" if caller == "load_ir" else "take")
            if name == "commit" and caller == "commit":
                return QOp("commit")
            if name == "issue":
                return QOp("issue", a=int(bool(k.get("mem_waiting", a[1] if len(a) > 1 else False))))
            if name == "abort":
                return QOp("abort")
            if name == "flush":
                return QOp("flush", val=a[1])
            if name in _READ_NAMES:
                return QOp(_READ_NAMES[name])
            return None
        _, attr, v, caller = ev
        simple = {"disp_t": "disp", "halted": "halt", "t4_at": "t4", "nop_held": "nop_hold"}
        if attr in simple:
            return QOp(simple[attr])
        if attr == "start_t":
            return QOp("start")
        if attr == "shift_until":
            return QOp("shift_end") if v is None else QOp("shift_set", val=v - t)
        if attr == "retry_at":
            return QOp("retry_end") if v is None else QOp("retry_set", val=v - t)
        if attr == "dropped" and v is False:
            return QOp("reraise")
        if attr == "flag" and v is False:
            return QOp("drop_retry")                 # or drop: decided by what follows
        if attr == "shift_held" and v is True:
            return QOp("shift_hold")
        if attr == "lost_start" and v is None:
            return QOp("lost_eval")                  # or lost_halt
        if attr == "lost_after" and v is None:
            return QOp("lost_after")
        if attr == "requested_at" and v == t:
            return QOp("redate")                     # or io_held_set
        if attr == "io_held" and v is None:
            return QOp("io_held_clr")
        if attr == "after_refresh" and caller == "_refresh":
            return QOp("beat", val=v - t)
        if attr == "gdisp_until" and caller == "tick" and v is not None:
            return QOp("gdisp", val=v - t)          # (WP61) grp_disp=hold
        if attr == "lea_ea" and caller == "tick" and v is not None and v[0] == t:
            return QOp("lea_ea", val=v[1] - t)      # (WP72) lea_room=ir
        if attr == "str_held" and caller == "tick" and v == float("inf"):
            return QOp("str_held", a=1)             # (WP77) str_fetch=hold: none from here
        if attr == "str_held" and caller == "tick" and v is not None:
            return QOp("str_held", val=v - t)       # (E3) str_hold=hold; (WP77) str_fetch
        if attr == "str_raise" and caller == "tick" and v is not None:
            return QOp("str_raise", val=v - t)      # (WP77) str_fetch=hold, CW = 0
        return None

    def _continues(self, op: QOp, ev) -> bool:
        """Whether ev is part of op (the stores and calls of one site)."""
        names = [(e[0], e[1]) for e in op.events]
        key = (ev[0], ev[1])
        c = op.code
        if c in READ_OPS:
            return False
        if c == "take":
            return key in (("set", "take_t"), ("set", "mate_t"), ("call", "commit_one")) \
                and key not in names
        if c == "irload":
            return (key == ("set", "ir_t") and len(names) == 1) or (
                key == ("call", "commit") and ev[3] == "load_ir" and len(names) == 2)
        if c == "start":
            return key in (("set", "starts"), ("set", "flush_held"), ("set", "odd_xfer"),
                           ("set", "odd_fed")) and key not in names
        if c in ("shift_end", "retry_end", "reraise"):
            return key in (("set", "shift_held"), ("set", "retry"), ("call", "room"),
                           ("set", "flag")) and key not in names and ("set", "flag") not in names
        if c == "issue":
            return key == ("set", "slot_fetch") and key not in names
        if c == "abort":
            return key in (("set", "abort_ref"), ("set", "retry_loop"),
                           ("set", "xfer_abort")) and key not in names
        if c in ("drop_retry", "drop"):
            return key in (("set", "requested_at"), ("set", "retry"), ("set", "retry_loop"),
                           ("set", "abort_t"), ("set", "dropped"), ("set", "drop_hold"),
                           ("set", "lost_start")) and (key not in names or key == ("set", "drop_hold"))
        if c == "lost_eval":
            return key in (("set", "lost_eval"), ("set", "lost_after")) and len(names) == 1
        if c == "lost_after":
            return key in (("set", "lost_eval"), ("set", "after_refresh")) and key not in names
        if c == "redate":
            return key == ("set", "io_held") and len(names) == 1
        if c == "beat":
            return key in (("call", "_evaluates"), ("set", "beat_eval"), ("set", "refresh_beaten"),
                           ("set", "after_refresh"))
        return False

    def _close(self, op: QOp):
        """Settle the op's code and arguments from its events; check the pattern."""
        t, m = self.t, self.m
        ev = op.events
        sets = {e[1]: e[2] for e in ev if e[0] == "set"}
        names = [(e[0], e[1]) for e in ev]
        bad = False
        if op.code == "eval":
            op.rd = None
            bad = ev[1][2] != (ev[0][4] >= 2)
        elif op.code in READ_OPS:
            r = ev[0][4]
            if ev[0][1] == "counted":
                r = 6 - r
            op.rd = int(r)
        elif op.code in ("take", "irload"):
            q = m.queue
            # the byte taken: the take returned its address
            op.rd = q.byte_at(ev[0][4])
            if op.code == "take":
                op.a = int(("call", "commit_one") in names)
                op.b = int("mate_t" in sets)
                bad = ("set", "take_t") not in names
            else:
                bad = len(ev) != 3
        elif op.code == "start":
            bad = "starts" not in sets
            if "flush_held" in sets:
                op.a, op.val = 1, sets["flush_held"] - t
            if "odd_xfer" in sets:              # (WP77) xfer_odd=idle: b
                op.b = 1
                bad = bad or sets["odd_xfer"] != t or sets.get("odd_fed", 0) is not None
        elif op.code in ("shift_end", "retry_end", "reraise"):
            need = {"shift_end": ("shift_held", "flag"), "retry_end": (),
                    "reraise": ("flag",)}[op.code]
            bad = any(k not in sets for k in need) or (
                op.code == "retry_end" and ("retry" in sets) != ("flag" in sets))
        elif op.code == "issue":
            op.b = int(sets.get("slot_fetch", False) is True)
        elif op.code == "abort":
            op.a = int(bool(sets.get("retry_loop", False)))
            op.b = int(sets.get("abort_ref", False) is True)
            op.val = int(sets.get("xfer_abort", False) is True)   # (WP72) xfer_abort=word
        elif op.code in ("drop_retry", "drop"):
            if "dropped" in sets:
                op.code = "drop"
                op.a = int(bool(sets["drop_hold"]))
                bad = sets.get("requested_at", 0) is not None or (
                    ("lost_start" in sets) == bool(op.a))
            else:
                op.a = int(bool(sets.get("retry_loop")))
                op.b = int(sets.get("abort_t") == t)
                bad = not (sets.get("retry") is True and "abort_t" in sets
                           and sets.get("requested_at", 0) is None)
        elif op.code == "lost_eval":
            if "lost_after" in sets:
                op.code = "lost_halt"
                op.val = sets["lost_after"] - t
            else:
                bad = sets.get("lost_eval") != t
        elif op.code == "lost_after":
            bad = sets.get("lost_eval") != t or sets.get("after_refresh") != t
        elif op.code == "redate":
            if "io_held" in sets:
                op.code = "io_held_set"
                bad = sets["io_held"] != t
        elif op.code == "beat":
            op.a = int(sets.get("refresh_beaten") is False)
            bad = "beat_eval" not in sets or "refresh_beaten" not in sets or (
                op.a and sets.get("after_refresh", 0) is not None)
        elif op.code == "t4":
            bad = sets["t4_at"] != t + 1
        elif op.code == "nop_hold":
            bad = sets["nop_held"] != t
        elif op.code == "disp":
            bad = sets["disp_t"] != t
        elif op.code == "gdisp":
            bad = not 0 <= op.val < 4
        elif op.code == "lea_ea":
            bad = not 0 < op.val < 4
        elif op.code == "str_held":
            bad = not (op.a or 0 < op.val < 16)
        elif op.code == "str_raise":
            bad = not 0 < op.val < 8
        if bad:
            raise RuntimeError(f"{m.chain.id}: queue op {op.code} at {t}: unexpected events "
                               f"{[(e[0], e[1]) for e in ev]}")

    def end_inputs(self):
        """Phase E's inputs, as end_clock is called (the ops are over)."""
        m, t, ck = self.m, self.t, self.clock
        self._finish()
        if ck.c_state is None:
            ck.c_state = qstate(m, t)
        if self.on_end is not None:
            self.on_end()
        c = m.bus.current
        ck.e_fetch_end = int(c is not None and c.kind == "fetch" and c.end == t)
        eu = m.eu
        r = eu.req
        cls = getattr(eu, "cls", None)
        req_open = not (r is not None and r.cycles and r.issued) and not (
            r is not None and not r.cycles)
        ck.e_io = int(not eu.halted and cls in ("out", "in") and req_open)
        ck.e_out = int(cls == "out")
        ck.e_snap = dsnap(m, t)

    def row(self):
        """The end of clock t (Machine.clock_log's append)."""
        m, t, ck = self.m, self.t, self.clock
        ck.e_state = qstate(m, t)
        merged = []
        for op in ck.ops:
            p = merged[-1] if merged else None
            if (self.merge and p is not None and op.code in READ_OPS and op.code == p.code
                    and op.snap == p.snap and op.rd == p.rd and op.state == p.state):
                continue                    # the same read again: nothing changed between
            merged.append(op)
        ck.ops = merged
        self.clocks.append(ck)
        self.t = t + 1
        self.clock = QClock(self.t, ops=[])


def run_queue_model(chain, cfg, chain_base: int, merge: bool = True):
    """(Machine, _Log, QueueRecorder, cycles): the frozen model as run_model builds it, with
    the queue's calls recorded; its trace checked against run_record's."""
    from .sim.frozen import machine as fm
    from .types import refresh_any
    phase = None
    if refresh_any(chain):
        phase = (64 - fm.POP_COUNTER[(chain.rfm, chain.wtc)]) % 128
    m = fm.Machine(chain, cfg, chain_base, phase, 0)
    init = (len(m.queue.bytes), [m.queue.byte_at(a) for a, _ in m.queue.bytes],
            m.queue.fetch_addr)
    rec = QueueRecorder(m, merge)
    log = _Log(m, rec)
    m.clock_log = log
    cycles = m.run()
    ref = fm.run_record(chain, cfg, chain_base, None, phase, 0)["socket_trace"]
    if fm.trace_rows(cycles) != ref:
        raise RuntimeError(f"{chain.id}: the logged run differs from run_record's")
    return m, log, rec, cycles, init


def queue_vectors(chain, cfg, chain_base: int, biu: bool = False, run=None,
                  nslot: int = NSLOT):
    """(the queue bench's vector file, the model's cycles, and with biu the bus unit's
    vector file of the same run, for the joint bench). run: run_queue_model's result (C3:
    an unmerged recording); nslot: the op chain's length the file is for."""
    m, log, rec, cycles, init = run if run is not None else run_queue_model(chain, cfg,
                                                                           chain_base)
    by_end = {c.end: c for c in cycles}
    clocks = rec.clocks
    count, data, faddr = init
    q = m.queue
    lines = [f"{QFORMAT} {chain.id} {len(clocks)} {nslot} {count} "
             f"{sum(b << (8 * i) for i, b in enumerate(data))} {faddr}",
             f"M {q.base} {bytes(q.code).hex()}",
             "F " + " ".join(f"{k}:{w}" for k, w in QFIELDS)]
    for ck in clocks:
        if len(ck.ops) > nslot:
            raise RuntimeError(f"{chain.id}: {len(ck.ops)} queue ops on clock {ck.t} "
                               f"(the RTL chains {nslot})")
        d = by_end.get(ck.t - 1)
        if d is not None:
            ck.c_done = 1
            ck.c_odd = d.addr & 1
            ck.c_data = d.data & 0xFFFF
            if (ck.c_fetch, ck.c_refresh) != (int(d.kind == "fetch"), int(d.kind == "refresh")):
                raise RuntimeError(f"{chain.id}: delivery at {ck.t} does not match the queue's")
        elif ck.c_fetch or ck.c_refresh:
            raise RuntimeError(f"{chain.id}: a queue delivery at {ck.t} without a cycle")
        lines.append(f"K {ck.t} {ck.c_done} {ck.c_fetch} {ck.c_refresh} {ck.c_odd} {ck.c_data} "
                     f"{ck.c_snap} {ck.e_fetch_end} {ck.e_io} {ck.e_out} {ck.e_snap} "
                     f"{len(ck.ops)}")
        lines.append("S " + qstate_text(ck.c_state))
        for op in ck.ops:
            rd = -1 if op.rd is None else _bits(op.rd, 8)
            lines.append(f"O {QOPS.index(op.code)} {op.a} {op.b} {_bits(op.val, 20)} {op.snap} {rd}")
            lines.append("S " + qstate_text(op.state))
        lines.append("S " + qstate_text(ck.e_state))
    text = "\n".join(lines) + "\n"
    if biu:
        return text, cycles, vectors(chain, cfg, chain_base, (m, log, cycles))[0]
    return text, cycles


# The queue bench ---------------------------------------------------------------------------

@dataclass
class QResult:
    run_id: str
    joint: bool = False
    clocks: int = 0
    ops: int = 0
    state_bad: int = 0              # states (after C/A, an op, the end, registered) differing
    rd_bad: int = 0                 # an op's read differing
    error_bad: int = 0              # the RTL's storage check fired
    gate_bad: int = 0               # joint: a fetch issued without the RTL queue's request
    signal_bad: int = 0             # joint: the bus unit's per-clock signals
    biu_state_bad: int = 0          # joint: the bus unit's state bundle
    cycles: int = 0                 # joint: the model's cycles ...
    rtl_cycles: int = 0             # ... the RTL's ...
    exact_cycles: int = 0           # ... equal (start, length, kind, address, width, data)
    first: str = ""
    error: str = ""
    not_modelled: str = ""          # (WP68) a run outside the RTL (string forms)

    @property
    def ok(self) -> bool:
        bad = (self.state_bad or self.rd_bad or self.error_bad or self.gate_bad
               or self.signal_bad or self.biu_state_bad)
        cyc = not self.joint or self.cycles == self.rtl_cycles == self.exact_cycles
        return not self.error and not self.not_modelled and not bad and cyc and self.clocks > 0


def check_queue_run(rec: dict, cfg, keep: Path | None = None, joint: bool = False) -> QResult:
    from .normalize import normalize
    s = normalize(rec)
    res = QResult(s.run_id, joint)
    try:
        out = queue_vectors(s.chain, cfg, s.chain_base, biu=joint)
    except NotModelled as e:
        res.not_modelled = str(e)
        return res
    except Exception as e:      # noqa: BLE001
        res.error = f"vectors: {type(e).__name__}: {e}"
        return res
    text, cycles = out[0], out[1]
    with tempfile.TemporaryDirectory() as tmp:
        d = keep if keep is not None else Path(tmp)
        qpath = d / f"{s.run_id}.qvec"
        qpath.write_text(text)
        args = [str(QBENCH), str(qpath)]
        if joint:
            bpath = d / f"{s.run_id}.vec"
            bpath.write_text(out[2])
            args.append(str(bpath))
        p = subprocess.run(args, capture_output=True, text=True, cwd=ROOT)
    if keep is not None:
        (keep / f"{s.run_id}.{'joint' if joint else 'queue'}.out").write_text(p.stdout + p.stderr)
    b = parse_bench(p.stdout)
    if p.returncode not in (0, 1) or not b["summary"]:
        res.error = f"bench exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}"
        return res
    sm = b["summary"]
    for k in ("clocks", "ops", "state_bad", "rd_bad", "error_bad", "gate_bad", "signal_bad",
              "biu_state_bad"):
        setattr(res, k, sm.get(k, 0))
    res.first = b["fail"][0] if b["fail"] else ""
    if joint:
        res.cycles = len(cycles)
        res.rtl_cycles = len(b["cyc"])
        model = [(c.start, c.length, KINDS.index(c.kind), c.addr, BWIDTHS.index(c.width),
                  c.data & 0xFFFF) for c in cycles]
        res.exact_cycles = sum(1 for x, y in zip(model, b["cyc"]) if x == y)
    return res



# C3: the decoder and the EU ------------------------------------------------------------------
#
# The frozen Decoder and EU are one RTL module (v35_eu.sv, the decoder's state and methods in
# v35_decoder.sv): phases T (eu.tick), L (decoder.load_ir), P (Machine.run's post-issue pass:
# the second tick and IR load, io_ir_hold, io_take=unit, port_issue, nop_hold) and E's
# latch_start. Everything else the model does to them in a clock comes from outside and is
# recorded (EURecorder: the EU's, the decoder's and each Request's class swapped for a logging
# subclass, the frozen machine module's `arbitrate` and the EU module's `execute` wrapped; the
# model's code is not changed): phase C's delivery of an EU read (eu.complete), the arbiter's
# touches in X (eu.issue, issue_nowrite, fetch_start, the abort's sync, a request's free_need
# and not_before; the request's setup count and the arbiter's own fields are C4's and only
# read), and, per instruction start, the operand record (D1: the RTL computes it, from its own
# register file and the code; the benches compare) and (D2) the register file before it, the
# functional reference's (funcref.py; the state rows carry the register file, FFIELDS, but its
# fields are left out of their comparison). A store
# or call from outside that is none of these raises (NotModelled); with refresh on (--core only,
# C5) also the refresh's touches (eu.refresh_cost's effects, the give-back, halt_defer). What the EU and the decoder read from the queue between their ops is the queue's state
# before each op (the C2 representation), from the recording (--eu) or the RTL queue (--joint3);
# from the bus unit, its state before and after the arbiter's choice.

EBENCH = ROOT / "build" / "fpga" / "v35s" / "eu-tb" / "Vv35_eu_tb"
EFORMAT = "V35EU-4"           # (E3) the P lines carry the string form's elements
NQ = 16                      # the EU's queue ops per phase (T and L; P) (v35_eu.sv NQ)
NXOP = 6                     # the arbiter's touches on the EU per clock (v35_eu.sv NXOP)
JSLOT = 40                   # the joint bench's queue op chain: T, L, X and P ops
CLS_NONE = 63                # no instruction yet (eu.cls unset)

# the arbiter's touches on the EU (v35_eu.sv V35_XOP_*), in this order
XOPS = ("nop", "issue", "nowrite", "fetch_start", "sync_one", "free0", "not_before",
        # (C5) the refresh's: a refresh cycle starts (val: its length | the EU's hold << 3), the
        # slot's setup += val (refresh_cost's extensions, refresh_post's give-back), its
        # beat_ext = val, eu.halt_defer = t + val
        "refresh", "setup", "beat", "halt_defer")
XOP_W = 12                   # a touch's word: 4-bit code, 8-bit val (v35_eu_pkg V35_XOP_W)
CLK_TAGS = (None, "exec", "loop", "tail", "loop_odd", "mexit", "shift")   # eu.clk_tag (CT_*)

# The state in the A2 representations (v35_eu.sv: v35_dec_t, v35_eus_t, v35_req_t; the bundle
# v35_est_t is {d, e, r[2], r[1], r[0]}, MSB first). Offsets are clipped at 0 (a stamp at or
# before the clock), ages saturate.
DFIELDS = (
    ("ir_v", 1),             # decoder.ir holds an opcode ...
    ("ir_addr", 20),         # ... from this address
    ("taddr", 20),           # the address of the next byte the decoder takes (its own count)
    ("need", 3),             # operand bytes still to take
    ("nx", 2),               # the class's nx
    ("ra_off", 2),           # ready_at - t
    ("ir_hold", 1),          # ir_load=disp_data
    ("ea_off", 2),           # ea_end - t (ea_ir_room: t < ea_end)
    ("modrm_next", 1),       # the next byte taken is a ModR/M
    ("mate_next", 1),        # the next byte taken is the ModR/M's odd word-mate (modrm_mate)
    ("imm_reg", 1),          # a register form with an immediate
    ("stopped", 1),          # HALT stopped the loader
)
EUFIELDS = (
    ("pc", 16),              # eu.pc: the code offset (the tail's first byte 0)
    ("cls", 6),              # the running instruction's class (V35_CLS_*; CLS_NONE before one)
    ("tmpl", 8),             # its template (v35_step)
    ("wbs", 1),              # the wbsync step before it (v35_wbsync)
    ("count", 9),            # its shift count (a template's per-count clocks)
    ("ins", 1),              # a port relatch inserted the slot and post steps ...
    ("ins_at", 4),           # ... at this step
    ("k", 18),               # the step cursor (E3: a REP string form's flat index)
    ("res", 10),             # resume - t
    ("left", 3),             # bytes left in the current take
    ("nw_v", 1),             # left_nw is set ...
    ("nw", 3),               # ... clocks left in a nowait step
    ("taken", 3),
    ("op_len", 3),
    ("imm_bytes", 2),
    ("disp", 2),
    ("modrm", 1),
    ("mem", 1),
    ("unit", 1),
    ("fixed", 1),
    ("grp_form", 1),         # a group opcode's form (grp_disp)
    ("refill", 1),           # refill_start: a flush's refill gates the next start
    ("route", 2),
    ("floor_n", 4),          # imm_count's floor from the start
    ("df_v", 1),             # dfloor_at is set ...
    ("df_off", 3),           # ... dfloor_at - t
    ("wb", 2),               # the running instruction's write-back clocks
    ("wbu", 2),              # wb_until - t (the previous one's)
    ("done_v", 1),           # done_t is set ...
    ("done_age", 2),         # ... t - done_t (saturating)
    ("sync", 2),             # the take sync: none, a count, defer
    ("owed", 2),             # the count: fetches still to be delivered (sync - completed)
    ("start_age", 4),        # t - start_clock (saturating at 15)
    ("fs_now", 1),           # fetch_start == t
    ("fs_this", 1),          # fetch_start == start_clock
    ("halted", 1),
    ("halt_now", 1),         # halt_t == t
    ("sa_off", 5),           # start_at - t (POP PSW's clocks), signed, clipped at -16
    ("exec_v", 1),           # unit_hold: exec_t is set ...
    ("exec_age", 2),         # ... t - exec_t (saturating at 3)
    ("exec_par", 1),         # ... and its parity
    ("hd_fetch", 1),         # hold_done is the fetch on the bus
    ("unit_early", 1),
    ("reg_early", 1),
    ("shift_latched", 1),
    ("lu_held", 1),          # latch_until is infinite (an OUT's I/O posted)
    ("lu_off", 3),           # latch_until - t
    ("latch_wait_now", 1),   # latch_wait == t
    ("port_now", 1),         # port_t == t ...
    ("port_held", 3),        # ... the requests it relatched (slot, queued 0, queued 1)
    ("own", 2),              # the request the instruction waits on: none, slot, q0, q1
    ("ea", 20),              # the instruction's operands (the register file's, Phase D)
    ("port", 16),
    ("sr", 16),              # stack read address
    ("sw", 16),              # stack write address
    ("tgt", 16),             # a taken transfer's target (a code offset)
    # (C5) the refresh's
    ("prev_cls", 6),         # refresh_beat_b2b: the class of the instruction before
    ("sfr", 8),              # eu.sfr: the SFR store's value (the RFM write)
    ("rmw", 1),              # refresh_rmw_loop: rmw_loop is set (a memory shift RMW)
    ("rmw_cl", 1),           # refresh_grpcl: rmw_cl is set (... by CL)
    ("clk_tag", 3),          # CLK_TAGS
    ("cs_now", 1),           # clk_start == t
    ("clk_seam", 1),
    ("ce_off", 11),          # clk_end - t, clipped at -1 (two's complement)
    ("res_past", 1),         # resume < t
    ("hv", 1),               # hold_end is set ...
    ("h_off", 3),            # ... max(0, hold_end - t) ...
    ("h_past", 1),           # ... hold_end < t
    ("hf_now", 1),           # hold_from == t
    ("hd_v", 1),             # halt_defer is set ...
    ("hd_off", 3),           # ... max(0, halt_defer - t) ...
    ("hd_past", 1),          # ... halt_defer < t
    ("halt_prev", 1),        # halt_t == t - 1
    ("pr_cand", 1),          # pop_refresh=stall: the last cycle a refresh started before
                             # start_at, not pop_ref ...
    ("pr_now", 1),           # ... the last cycle a refresh started on t ...
    ("pr_len", 3),           # ... the last refresh's length
    # (WP77) the forty-first fit's
    ("sreg", 2),             # sreg_store, sreg_io: the running form's Op.sreg (1 load, 2 store)
    ("lea_split", 1),        # lea_disp=split: the running LDEA's d16 ends on a word's low half
    ("nw_tv", 1),            # str_io_setup=run: nw_t is set ...
    ("nw_age", 3),           # ... t - nw_t, the nowait step's first clock (saturating at 7)
    ("nw_ran", 1),           # ... nw_run is set (the wait clock it counted)
    ("ls_split", 1),         # str_split=floor: the last data step ran two cycles (last_issued)
    ("ls_age", 3),           # ... t - its second's start (saturating at 7)
)
RFIELDS = (
    ("valid", 1),
    ("kind", 3),             # rtlgen.REQ_KINDS
    ("w2", 1),               # a word
    ("ncyc", 2),             # cycles still to issue
    ("issued", 2),           # cycles issued
    ("addr", 20),            # the address (an I/O's port)
    ("setup", 7),
    ("free_v", 1),           # free_need is set ...
    ("free", 5),             # ... its value
    ("lead", 2),
    ("nowait", 1),
    ("cls", 6),              # the posting class
    ("free_bus", 1),
    ("whole", 1),
    ("through", 7),
    ("free_orig", 5),
    ("imm1", 1),
    ("detached", 1),
    ("port", 1),
    ("moved", 1),
    ("dw_moved", 1),
    ("floor_hold", 1),
    ("gdisp", 1),            # grp_disp=hold's read
    ("nb_off", 4),           # not_before - t
    ("da_v", 1),             # done_at is set ...
    ("da_off", 3),           # ... done_at - t ...
    ("da_past", 1),          # ... done_at < t
    ("grpcl", 2),            # (C5) refresh_grpcl: a memory shift's read: its CL clocks
    ("beat_ext", 3),         # (C5) refresh_post=post_beat: the hold's clocks
    ("sreg_held", 1),        # (WP77) sreg_io=hold: a MOV sreg,r/m decoded behind it
    ("sreg", 1),             # (WP77) sreg_store=own: MOV r/m,sreg's write
    ("li_age", 3),           # (WP77) t - its last issued cycle's start (saturating at 7)
)
# (D1, D2) the register file (v35_eu.sv v35_rf_t), MSB first
FFIELDS = (
    ("aw", 16), ("cw", 16), ("dw", 16), ("bw", 16), ("sp", 16), ("bp", 16), ("ix", 16),
    ("iy", 16),              # the word registers (REG16 order)
    ("ps", 16), ("ss", 16), ("ds0", 16), ("ds1", 16),   # (D2) the segment registers
    ("psw", 16),             # (D2) the PSW (the V35 layout)
    ("pfx", 3),              # the segment prefix the next instruction carries: 4 + its sreg
)
# (D2) the running instruction's functional context (v35_fx_t)
XFIELDS = (("code", 48), ("wd", 16), ("md", 16), ("rk", 3), ("wk", 3),
           # (E3) a string form: its elements (the RTL's, from its CW and its data), whether a
           # compare's condition ended it, IX and IY at its start, the source's segment
           ("sn", 16), ("sc", 1), ("six", 16), ("siy", 16), ("sseg", 16))
EFIELDS = (tuple((f"d_{n}", w) for n, w in DFIELDS) + tuple((f"e_{n}", w) for n, w in EUFIELDS)
           + tuple((f"f_{n}", w) for n, w in FFIELDS) + tuple((f"x_{n}", w) for n, w in XFIELDS)
           + tuple((f"r{i}_{n}", w) for i in (2, 1, 0) for n, w in RFIELDS))
ESTATE_W = sum(w for _, w in EFIELDS)
# (D2) the functional fields of the state rows: the register file and the context change at the
# points the RTL's function applies the data (a start, a read's delivery, a write's issue), not
# at the frozen model's (templates.execute at the start); the benches leave them out of the state
# rows and compare the register file at every start, every EU cycle's datum and the end against
# the functional reference (funcref.py)
FUNC_PREFIXES = ("f_", "x_")
# the queue's state the EU and the decoder read (QFIELDS names, v35_eu.sv v35_qview_t)
QVIEW = ("count", "latched", "flag", "rq_valid", "rq_age", "inflight", "ab_valid", "ab_left",
         "ab_this", "retry", "retry_loop", "rt_valid", "rt_off", "shift_held", "sh_valid",
         "sh_off", "dropped", "drop_hold", "b2b_now", "arrived_now", "take_now", "take_prev",
         "ir_now", "latch_in_now")
# the bus unit's state the EU reads (before and after the arbiter's choice; v35_bview_t)
BVIEW = (("kind", 3), ("pos", 3), ("len", 3), ("free", 1), ("finf", 1), ("in_wait", 1),
         ("fprev", 1), ("wl", 1), ("fsince", 4), ("flen3", 1),
         ("run", 1))         # (WP77) the last two cycles but refreshes fetches back to back
# an instruction's operand record (D1: the RTL's register file and EA adder compute it; the
# bench compares), then (D2) the register file before the instruction (FFIELDS, the functional
# reference's)
OPFIELDS = ("offset", "code", "ea", "port", "sr", "sw", "count", "taken", "target", "fmt",
            "tmpl")


def rf_of(regs: dict) -> dict:
    """(D2) the register file in the RTL's representation (FFIELDS) of a functional
    reference's snapshot (funcref.Cpu.snapshot)."""
    from .funcref import REG16, SREG
    f = {n.lower(): regs[n] & 0xFFFF for n in REG16 + ("PS", "SS", "DS0", "DS1", "PSW")}
    f["pfx"] = 0 if regs.get("pfx") is None else 4 | regs["pfx"]
    assert SREG == ("DS1", "PS", "SS", "DS0")
    return f


class NotModelled(RuntimeError):
    """A run a bench does not cover (--eu/--joint3: refresh on; any: an unclassified store)."""


_FROZEN_DIR = str(Path(__file__).resolve().parent / "sim" / "frozen") + "/"
_TMPL_CACHE: dict = {}


def _templates(cfg):
    key = repr(cfg)                 # the fit's value (a Config is rebuilt per run)
    if key not in _TMPL_CACHE:
        from . import rtlgen
        order, sel, _ = rtlgen.templates(cfg)
        _TMPL_CACHE.clear()
        _TMPL_CACHE[key] = (order, sel, rtlgen.rtl_classes(cfg))   # (WP77) the built
    return _TMPL_CACHE[key]


def _caller_file(depth: int = 2) -> str:
    fn = sys._getframe(depth).f_code.co_filename
    return fn[len(_FROZEN_DIR):] if fn.startswith(_FROZEN_DIR) else fn


@dataclass
class OpRec:
    offset: int
    code: bytes
    ea: int
    port: int
    sr: int
    sw: int
    count: int
    taken: int
    target: int
    fmt: int
    tmpl: int
    rf: dict | None = None          # (D2) the register file before it (FFIELDS, funcref's)
    tgt: int = 0                    # (D2) the transfer's target (RET's: the stack read's, which
                                    # the record leaves 0)
    string: tuple = (0, 0, 0)       # (E3) a string form: (1, the elements it runs, whether a
                                    # compare's condition ended it), the walk's (funcref's)

    def text(self) -> str:
        return (f"P {self.offset} {self.code.hex()} {self.ea} {self.port} {self.sr} {self.sw} "
                f"{self.count} {self.taken} {self.target} {self.fmt} {self.tmpl} "
                + " ".join(str(self.rf[n]) for n, _ in FFIELDS)
                + " " + " ".join(str(v) for v in self.string))


@dataclass
class EClock:
    t: int
    c_eu: int = 0               # phase C: an EU cycle was delivered (eu.complete) ...
    c_read: int = 0             # ... a read
    fetch_done: int = 0         # queue.completed counted one (C or A)
    bus_t: tuple = ()           # BVIEW before the choice (phase T)
    bus_p: tuple = ()           # ... after it (phase P)
    x: tuple = (0, 0, 0, 0)     # the cycle the arbiter started: valid, kind, the EU's, length
    counts: tuple = (0, 0, 0)   # the requests' setup counts (the arbiter's), at T ...
    counts_p: tuple = (0, 0, 0)  # ... and at P
    latch_in: int = 0           # queue.latch_in_t == t after phase E (latch_start)
    states: dict | None = None  # phase -> estate: c, t, l, x, p, e
    tl: list | None = None      # the T and L queue ops (QOp) ...
    n_t: int = 0                # ... of which the first n_t are T's
    xq: list | None = None      # the arbiter's queue ops (X)
    p: list | None = None       # the P ops
    qv_tl: list | None = None   # the queue's state before each T/L op and after the last
    qv_p: list | None = None    # ... each P op (the first: after X)
    xops: list | None = None    # the arbiter's touches on the EU: (code, val)


class EURecorder:
    """Records the decoder's and the EU's run per clock (the section comment above)."""

    def __init__(self, m, qrec, refresh: bool = False, fref=None):
        if m.refresh is not None and not refresh:
            raise NotModelled("refresh on (the scripted-arbiter benches; --core models it)")
        self.m, self.qrec = m, qrec
        self.fref = fref            # (D2) the functional reference's run (funcref.Run)
        self.ret_pending = False    # (D2) a RET's target waits for its stack read
        self.refresh = m.refresh is not None    # (C5) the refresh templates and rules
        self.cfg = m.cfg
        self.tmpls, self.sel, self.classes = _templates(m.cfg)
        self.t = 0
        self.phase = "C"
        self.clock = EClock(0, states={}, xops=[])
        self.clocks: list[EClock] = []
        self.opnds: list[OpRec] = []
        self.cur: OpRec | None = None
        self.taddr = m.queue.bytes[0][0]
        self.completed = m.queue.completed
        self.x_cycle = None
        self.arb = None             # (C4) the ArbiterRecorder: classifies the arbiter's own stores
        qrec.phase_of = lambda: self.phase
        qrec.on_call = self._queue_call
        qrec.on_end = self._end_ops
        self._swap()
        self.init = estate(m, -1, self)

    # the swaps -----------------------------------------------------------------------------
    def _swap(self):
        m, rec = self.m, self
        eu_base, d_base = type(m.eu), type(m.decoder)

        def eu_setattr(obj, k, v):
            f = _caller_file()
            if f not in ("eu.py", "decoder.py"):
                rec._external("eu", k, v, f)
            object.__setattr__(obj, k, v)

        def tick(obj, t):
            if rec.phase != "C":
                return eu_base.tick(obj, t)
            rec._begin(t)
            rec.phase = "T"
            r = eu_base.tick(obj, t)
            rec.clock.states["t"] = estate(m, t, rec)
            rec.phase = "L0"
            return r

        def complete(obj, c, t):
            if rec.phase != "C":
                raise NotModelled(f"eu.complete outside phase C at {t}")
            rec.clock.c_eu = 1
            rec.clock.c_read = int(c.kind.endswith("read"))
            r = eu_base.complete(obj, c, t)
            req = obj.own if obj.own is not None else obj.req
            if (rec.ret_pending and obj.cls == "ret" and req is not None and c in req.issued
                    and not req.cycles and c is req.issued[-1]):
                rec.ret_pending = False         # (D2) RET's target: the read's datum
            return r

        def issue(obj, t, bus):
            c = eu_base.issue(obj, t, bus)
            if rec.phase != "X":
                raise NotModelled(f"eu.issue outside phase X at {t}")
            rec.clock.xops.append(("issue", c.length))
            return c

        def issue_nowrite(obj, t, bus, queue):
            c = eu_base.issue_nowrite(obj, t, bus, queue)
            if rec.phase != "X":
                raise NotModelled(f"eu.issue_nowrite outside phase X at {t}")
            rec.clock.xops.append(("nowrite", c.length if c is not None else 0))
            return c

        def post(obj, t, kind, addr, width, setup, *a, **k):
            r = eu_base._post(obj, t, kind, addr, width, setup, *a, **k)
            r.__class__ = _recorded_request()
            object.__setattr__(r, "_rec", rec)
            object.__setattr__(r, "_kind0", kind)
            object.__setattr__(r, "_addr0", addr)
            object.__setattr__(r, "_w2", width == 2)
            return r

        def refresh_cost(obj, t, length=5):
            # (C5) the arbiter's call into the EU when a refresh starts: its effects are touches
            # (the slot's setup extension and beat_ext, the EU's hold), in this order
            if rec.phase != "X":
                raise NotModelled(f"eu.refresh_cost outside phase X at {t}")
            r = obj.req
            before = (r.setup, r.beat_ext) if r is not None else None
            out = eu_base.refresh_cost(obj, t, length)
            if r is not None:
                if r.setup != before[0]:
                    rec.clock.xops.append(("setup", r.setup - before[0]))
                if r.beat_ext != before[1]:
                    rec.clock.xops.append(("beat", r.beat_ext))
            hold = obj.hold_from == t and obj.hold_end == t + length - 1
            rec.clock.xops.append(("refresh", length | (int(hold) << 3)))
            return out

        ns = {"__setattr__": eu_setattr, "tick": tick, "complete": complete, "issue": issue,
              "issue_nowrite": issue_nowrite, "_post": post, "refresh_cost": refresh_cost}
        m.eu.__class__ = type("RecordedEU", (eu_base,), ns)

        def d_setattr(obj, k, v):
            f = _caller_file()
            if f not in ("eu.py", "decoder.py"):
                rec._external("decoder", k, v, f)
            object.__setattr__(obj, k, v)

        def load_ir(obj, t):
            if rec.phase != "L0":
                return d_base.load_ir(obj, t)
            rec.phase = "L"
            r = d_base.load_ir(obj, t)
            rec.clock.states["l"] = estate(m, t, rec)
            rec.phase = "L1"
            return r

        m.decoder.__class__ = type("RecordedDecoder", (d_base,), {"__setattr__": d_setattr,
                                                                  "load_ir": load_ir})

    def _external(self, who, k, v, f):
        """A store into the EU, the decoder or a request from another machine's code."""
        t = self.t
        if f == "machine.py":
            if who == "eu" and k in ("retick", "resume", "since_start") or (
                    who == "decoder" and k == "ir_hold") or (who == "req" and k == "not_before"):
                return                          # phase P / E: the RTL's own (port_issue too)
        elif f == "arbiter.py" and self.phase == "X":
            if who == "eu" and k == "fetch_start":
                if v != t:
                    raise NotModelled(f"eu.fetch_start = {v} at {t}")
                self.clock.xops.append(("fetch_start", 0))
                return
            if who == "eu" and k == "sync":
                if v != self.m.queue.completed + 1:
                    raise NotModelled(f"eu.sync = {v} at {t}")
                self.clock.xops.append(("sync_one", 0))
                return
            if who == "eu" and k == "refresh_beat":
                return                          # (C5) refresh_cost's argument (eu.refresh_beat)
            if who == "eu" and k == "halt_defer":
                if v is None or not 0 < v - t < 8:
                    raise NotModelled(f"eu.halt_defer = {v} at {t}")
                self.clock.xops.append(("halt_defer", v - t))   # (C5) refresh_halt=status
                return
            if who == "req" and k in ("count", "ready_since", "lift_t", "free_held", "grp_held",
                                      "xeu", "eu_halted", "sreg_ok", "sreg_at"):
                if self.arb is not None:
                    self.arb.store(k, v, t)     # (C4) the arbiter's own, classified there
                return                          # the arbiter's own (C4)
        raise NotModelled(f"{f} writes {who}.{k} = {v!r} in phase {self.phase} at {t}")

    def _req_set(self, r, k, v):
        f = _caller_file(3)
        if f in ("eu.py", "decoder.py"):
            return
        t, eu = self.t, self.m.eu
        if f == "arbiter.py" and self.phase == "X" and k in ("free_need", "not_before", "setup",
                                                             "beat_ext"):
            if r is not eu.req:
                raise NotModelled(f"the arbiter writes a queued request's {k} at {t}")
            if k == "free_need":
                if v != 0:
                    raise NotModelled(f"free_need = {v} at {t}")
                self.clock.xops.append(("free0", 0))
            elif k == "not_before":
                self.clock.xops.append(("not_before", v - t))
            elif k == "setup":                  # (C5) refresh_post=post_beat's give-back
                self.clock.xops.append(("setup", v - r.setup))
            else:
                if v != 0:
                    raise NotModelled(f"the arbiter sets beat_ext = {v} at {t}")
                self.clock.xops.append(("beat", 0))
            return
        self._external("req", k, v, f)

    # the queue's calls (QueueRecorder.on_call) ---------------------------------------------
    def _queue_call(self, name, a, k, r):
        if name == "take":
            self.taddr = r + 1
        elif name == "flush":
            self.taddr = a[1]

    # phases ----------------------------------------------------------------------------------
    def _begin(self, t: int):
        """Phase T begins (the first tick): the state after phase C."""
        m, ck = self.m, self.clock
        ck.states["c"] = estate(m, t, self)
        ck.fetch_done = m.queue.completed - self.completed
        if ck.fetch_done not in (0, 1):
            raise NotModelled(f"{ck.fetch_done} fetches completed at {t}")
        ck.bus_t = bview(m, t)
        ck.counts = _counts(m.eu)

    def arbitrate(self, orig, t, cfg, bus, queue, eu):
        if self.phase not in ("L1",):
            raise NotModelled(f"arbitrate in phase {self.phase} at {t}")
        self.phase = "X"
        c = orig(t, cfg, bus, queue, eu)
        ck = self.clock
        if len(ck.xops) > NXOP:
            raise NotModelled(f"{len(ck.xops)} arbiter touches on the EU at {t}")
        if c is not None:
            ck.x = (1, KINDS.index(c.kind), int(c.owner is eu), c.length)
        ck.states["x"] = estate(self.m, t, self)
        ck.bus_p = bview(self.m, t)
        ck.counts_p = _counts(eu)
        self.phase = "P"
        return c

    def _end_ops(self):
        if self.phase != "P":
            raise NotModelled(f"end_clock in phase {self.phase} at {self.t}")
        self.clock.states["p"] = estate(self.m, self.t, self)
        self.phase = "E"

    def row(self):
        """The end of clock t (after the queue recorder's row)."""
        m, t, ck = self.m, self.t, self.clock
        if self.phase != "E":
            raise NotModelled(f"the clock's row in phase {self.phase} at {t}")
        q = m.queue
        ck.states["e"] = estate(m, t, self)
        ck.latch_in = int(q.latch_in_t == t)
        qk = self.qrec.clocks[-1]
        if qk.t != t:
            raise RuntimeError(f"{m.chain.id}: the queue recorder is at clock {qk.t}, not {t}")
        ops = qk.ops
        phases = [o.phase for o in ops]
        order = {"T": 0, "L": 1, "X": 2, "P": 3}
        if any(p not in order for p in phases) or [order[p] for p in phases] != sorted(
                order[p] for p in phases):
            raise NotModelled(f"queue ops out of phase order at {t}: {phases}")
        ck.tl = [o for o in ops if o.phase in "TL"]
        ck.xq = [o for o in ops if o.phase == "X"]
        ck.p = [o for o in ops if o.phase == "P"]
        ck.n_t = sum(1 for o in ops if o.phase == "T")
        if len(ck.tl) > NQ or len(ck.p) > NQ:
            raise NotModelled(f"{len(ck.tl)} T/L and {len(ck.p)} P queue ops at {t} "
                              f"(the RTL holds {NQ})")
        states = [qk.c_state] + [o.state for o in ops]
        ck.qv_tl = [qview(s) for s in states[:len(ck.tl) + 1]]
        a = len(ck.tl) + len(ck.xq)
        ck.qv_p = [qview(s) for s in states[a:a + len(ck.p) + 1]]
        self.clocks.append(ck)
        self.completed = q.completed
        self.t = t + 1
        self.clock = EClock(self.t, states={}, xops=[])
        self.phase = "C"

    # the operand record of each start (eu.execute's op, after _start's own changes) -------
    def started(self, op):
        """(D2) the start's operand record: the functional reference's start (in order) gives
        the quantities, which must be the frozen model's (else the model's timing was computed
        from a value silicon does not have), and the register file before it; the format and
        the template are the model's. RET's target is the stack read's: the RTL has it at the
        read's delivery (0 in the record, and in the state rows until then)."""
        from . import funcref, rtlgen
        m = self.m
        cz = rtlgen.has_count(op) and op.count == 0
        key = tuple(rtlgen.fmt_of(op, self.cfg, cz, self.refresh)[n] for n, _ in rtlgen.FMT_FIELDS)
        if key not in self.sel:
            raise NotModelled(f"no template in the include for {op.cls} at {op.offset}")
        code = bytes(m.eu.code[op.offset:op.offset + 6]).ljust(6, b"\x90")
        i = len(self.opnds)
        if i >= len(self.fref.starts):
            raise RuntimeError(f"{m.chain.id}: start {i} past the functional reference's "
                               f"{len(self.fref.starts)}")
        st = self.fref.starts[i]
        q, qf = funcref.quantities(st), funcref.quantities_frozen(op)
        if st.pc != op.offset or q != qf:
            raise RuntimeError(f"{m.chain.id}: start {i} at {op.offset}: the functional "
                               f"reference's {st.pc} {q} is not the model's {qf}")
        ret = op.cls == "ret"
        r = OpRec(op.offset, code, st.ea, st.port, st.sr, st.sw, st.count, int(st.taken),
                  0 if ret else st.target, rtlgen.pack_fmt(key, self.classes), self.sel[key],
                  rf_of(st.regs), st.target if st.taken else 0,
                  (1, st.string[4], int(st.string[5])) if st.string is not None else (0, 0, 0))
        self.opnds.append(r)
        self.cur = r
        self.ret_pending = ret


_REQ_CLASS: list = []


def _recorded_request():
    """The class a posted Request is given (EURecorder._swap's post): its stores from outside
    the EU are classified (EURecorder._req_set)."""
    if not _REQ_CLASS:
        from .sim.frozen.arbiter import Request

        def setattr_(obj, k, v):
            rec = obj.__dict__.get("_rec")
            if rec is not None and not k.startswith("_"):
                rec._req_set(obj, k, v)
            object.__setattr__(obj, k, v)
        _REQ_CLASS.append(type("RecordedRequest", (Request,), {"__setattr__": setattr_}))
    return _REQ_CLASS[0]


def _counts(eu) -> tuple:
    return tuple(min(127, r.count) if r is not None else 0
                 for r in ([eu.req] + list(eu.queued) + [None, None])[:3])


def bview(m, t: int) -> tuple:
    """The bus unit's state the EU reads on t (BVIEW): the cycle on the bus, its position and
    length, free, a fetch in flight, a wait state, a fetch's delivery clock, the data latch,
    the clocks since the last fetch's end (C1's fetch_since), a fetch of 3 clocks."""
    b = m.bus
    cur = b.current if b.busy(t) else None
    since = 0 if b.fetch_inflight(t) else min(15, t - b.last_fetch_end)
    return (KINDS.index(cur.kind) if cur else 0, t - cur.start if cur else 0,
            cur.length if cur else 0, int(b.free(t)), int(b.fetch_inflight(t)),
            int(b.in_wait(t)), int(b.last_fetch_end == t - 1), int(t < m.eu.wlatch_until),
            since, int(b.length("fetch") == 3), _fetch_run(b))


def _fetch_run(b) -> int:
    """(WP77) str_io_setup=run: the last two cycles that are not refreshes are fetches back to
    back (the arbiter's ARFIELDS run): with the last a fetch, the model's _run_wait's cycles."""
    cs = []
    for c in reversed(b.cycles):
        if c.kind != "refresh":
            cs.insert(0, c)
            if len(cs) == 2:
                break
    return int(len(cs) >= 2 and cs[-1].kind == "fetch" and cs[-2].kind == "fetch"
               and cs[-2].end == cs[-1].start - 1)


def qview(s: dict) -> tuple:
    return tuple(s[k] for k in QVIEW)


def qview_text(v: tuple) -> str:
    w = dict(QFIELDS)
    return " ".join(str(_bits(x, w[k])) for k, x in zip(QVIEW, v))


def estate(m, t: int, rec) -> dict:
    """The decoder's and the EU's state on clock t in the A2 representations (EFIELDS)."""
    d, eu, q, bus = m.decoder, m.eu, m.queue, m.bus
    s = {}
    s["d_ir_v"] = int(d.ir is not None)
    s["d_ir_addr"] = d.ir or 0
    s["d_taddr"] = rec.taddr
    s["d_need"] = d.need
    s["d_nx"] = d.nx
    s["d_ra_off"] = max(0, d.ready_at - t)
    s["d_ir_hold"] = int(bool(d.ir_hold))
    s["d_ea_off"] = max(0, d.ea_end - t) if d.ea_end is not None else 0
    s["d_modrm_next"] = int(d.modrm_next)
    s["d_mate_next"] = int(d.modrm_addr is not None and d.modrm_addr % 2 == 0
                           and rec.taddr == d.modrm_addr + 1)
    s["d_imm_reg"] = int(bool(d.imm_reg))
    s["d_stopped"] = int(d.stopped)
    op = rec.cur
    s["e_pc"] = eu.pc
    cls = getattr(eu, "cls", None)
    s["e_cls"] = rec.classes.index(cls) if cls is not None else CLS_NONE
    s["e_tmpl"] = op.tmpl if op else 0
    s["e_wbs"] = int(bool(eu.steps) and eu.steps[0] == ("wbsync",))
    s["e_count"] = op.count if op else 0
    ins = [i for i, st in enumerate(eu.steps) if st == ("slot",)]
    if len(ins) > 1:
        raise NotModelled(f"two port relatches in one instruction at {t}")
    s["e_ins"] = int(bool(ins))
    s["e_ins_at"] = ins[0] if ins else 0
    s["e_k"] = eu.k
    s["e_res"] = max(0, eu.resume - t)
    s["e_left"] = eu.left
    s["e_nw_v"] = int(eu.left_nw is not None)
    s["e_nw"] = eu.left_nw or 0
    s["e_taken"] = eu.taken
    s["e_op_len"] = eu.op_len
    s["e_imm_bytes"] = eu.imm_bytes
    s["e_disp"] = eu.disp
    s["e_modrm"] = int(eu.modrm)
    s["e_mem"] = int(bool(getattr(eu, "mem", False)))
    s["e_unit"] = int(bool(getattr(eu, "unit", False)))
    s["e_fixed"] = int(bool(eu.fixed))
    s["e_grp_form"] = int(bool(eu.grp_form))
    s["e_refill"] = int(bool(eu.refill))
    s["e_route"] = eu.route
    s["e_floor_n"] = getattr(eu, "floor_n", 0)
    dfa = getattr(eu, "dfloor_at", None)
    s["e_df_v"] = int(dfa is not None)
    s["e_df_off"] = max(0, dfa - t) if dfa is not None else 0
    s["e_wb"] = eu.wb
    s["e_wbu"] = max(0, eu.wb_until - t)
    s["e_done_v"] = int(eu.done_t is not None)
    s["e_done_age"] = min(3, t - eu.done_t) if eu.done_t is not None else 0
    sy = eu.sync
    if sy is None:
        s["e_sync"], s["e_owed"] = 0, 0
    elif sy == "defer":
        s["e_sync"], s["e_owed"] = 2, 0
    else:
        s["e_sync"], s["e_owed"] = 1, max(0, sy - q.completed)
    s["e_start_age"] = min(15, t - eu.start_clock)
    s["e_fs_now"] = int(eu.fetch_start == t)
    s["e_fs_this"] = int(eu.fetch_start is not None and eu.fetch_start == eu.start_clock)
    s["e_halted"] = int(eu.halted)
    s["e_halt_now"] = int(eu.halt_t == t)
    s["e_sa_off"] = _bits(max(-16, eu.start_at - t), 5)
    s["e_exec_v"] = int(eu.exec_t is not None)
    s["e_exec_age"] = min(3, t - eu.exec_t) if eu.exec_t is not None else 0
    s["e_exec_par"] = (t - eu.exec_t) & 1 if eu.exec_t is not None else 0
    cur = bus.current if bus.busy(t) else None
    s["e_hd_fetch"] = int(cur is not None and eu.hold_done is cur)
    s["e_unit_early"] = int(bool(getattr(eu, "unit_early", False)))
    s["e_reg_early"] = int(bool(eu.reg_early))
    s["e_shift_latched"] = int(bool(getattr(eu, "shift_latched", False)))
    lu = eu.latch_until
    s["e_lu_held"] = int(lu == float("inf"))
    s["e_lu_off"] = 0 if lu == float("inf") else max(0, int(lu) - t)
    s["e_latch_wait_now"] = int(eu.latch_wait == t)
    slots = ([eu.req] + list(eu.queued) + [None, None])[:3]
    if len(eu.queued) > 2:
        raise NotModelled(f"{len(eu.queued)} queued requests at {t}")
    s["e_port_now"] = int(eu.port_t == t)
    s["e_port_held"] = sum(1 << i for i, r in enumerate(slots)
                           if r is not None and eu.port_t == t
                           and any(r is h for h in eu.port_held))
    own = [i for i, r in enumerate(slots) if r is not None and r is eu.own]
    if eu.own is not None and not own:
        raise NotModelled(f"eu.own is neither the slot nor a queued request at {t}")
    s["e_own"] = own[0] + 1 if own else 0
    s["e_ea"] = op.ea if op else 0
    s["e_port"] = op.port if op else 0
    s["e_sr"] = op.sr if op else 0
    s["e_sw"] = op.sw if op else 0
    s["e_tgt"] = op.tgt if op and not rec.ret_pending else 0
    rf = op.rf if op else rf_of(rec.fref.init)
    for k, v in rf.items():
        s["f_" + k] = v                 # (D2) the register file before the instruction's start
    for k, _ in XFIELDS:
        s["x_" + k] = 0                 # (D2) the functional context (not compared)
    # (C5) the refresh's
    pc = getattr(eu, "prev_cls", None)
    s["e_prev_cls"] = rec.classes.index(pc) if pc is not None else CLS_NONE
    s["e_sfr"] = eu.sfr or 0
    s["e_rmw"] = int(bool(eu.rmw_loop))
    s["e_rmw_cl"] = int(bool(getattr(eu, "rmw_cl", 0)))
    if eu.clk_tag not in CLK_TAGS:
        raise NotModelled(f"clk_tag {eu.clk_tag!r} at {t}")
    s["e_clk_tag"] = CLK_TAGS.index(eu.clk_tag)
    s["e_cs_now"] = int(eu.clk_start == t)
    s["e_clk_seam"] = int(bool(eu.clk_seam))
    s["e_ce_off"] = _bits(max(-1, eu.clk_end - t), 11)
    s["e_res_past"] = int(eu.resume < t)
    he = eu.hold_end
    s["e_hv"] = int(he is not None)
    s["e_h_off"] = max(0, he - t) if he is not None else 0
    s["e_h_past"] = int(he is not None and he < t)
    s["e_hf_now"] = int(eu.hold_from == t)
    hd = eu.halt_defer
    s["e_hd_v"] = int(hd is not None)
    s["e_hd_off"] = max(0, hd - t) if hd is not None else 0
    s["e_hd_past"] = int(hd is not None and hd < t)
    s["e_halt_prev"] = int(eu.halt_t is not None and eu.halt_t == t - 1)
    last = bus.cycles[-1] if bus.cycles else None
    lref = next((c for c in reversed(bus.cycles) if c.kind == "refresh"), None)
    s["e_pr_cand"] = int(last is not None and last.kind == "refresh" and last.start < eu.start_at
                         and last is not eu.pop_ref)
    s["e_pr_now"] = int(last is not None and last.kind == "refresh" and last.start == t)
    s["e_pr_len"] = lref.length if lref is not None else 0
    # (WP77)
    s["e_sreg"] = {None: 0, "load": 1, "store": 2}[eu.sreg]
    s["e_lea_split"] = int(bool(eu.lea_split))
    s["e_nw_tv"] = int(eu.nw_t is not None)
    s["e_nw_age"] = min(7, t - eu.nw_t) if eu.nw_t is not None else 0
    s["e_nw_ran"] = int(eu.nw_run is not None)
    li = eu.last_issued
    s["e_ls_split"] = int(len(li) > 1)
    s["e_ls_age"] = min(7, t - li[-1].start) if len(li) > 1 else 0
    from .rtlgen import REQ_KINDS
    for i, r in enumerate(slots):
        p = f"r{i}_"
        if r is None:
            for n, _ in RFIELDS:
                s[p + n] = 0
            continue
        s[p + "valid"] = 1
        s[p + "kind"] = REQ_KINDS.index(r._kind0)
        s[p + "w2"] = int(r._w2)
        s[p + "ncyc"] = len(r.cycles)
        s[p + "issued"] = len(r.issued)
        s[p + "addr"] = r._addr0
        s[p + "setup"] = r.setup
        s[p + "free_v"] = int(r.free_need is not None)
        s[p + "free"] = r.free_need or 0
        s[p + "lead"] = r.lead
        s[p + "nowait"] = int(r.nowait)
        s[p + "cls"] = rec.classes.index(r.cls) if r.cls else CLS_NONE
        s[p + "free_bus"] = int(r.free_bus)
        s[p + "whole"] = int(r.whole)
        s[p + "through"] = r.through
        s[p + "free_orig"] = r.free_orig
        s[p + "imm1"] = int(bool(r.imm1))
        s[p + "detached"] = int(r.detached)
        s[p + "port"] = int(r.port)
        s[p + "moved"] = int(r.moved)
        s[p + "dw_moved"] = int(r.dw_moved)
        s[p + "floor_hold"] = int(r.floor_hold)
        s[p + "gdisp"] = int(r.gdisp)
        s[p + "nb_off"] = max(0, r.not_before - t)
        s[p + "da_v"] = int(r.done_at is not None)
        s[p + "da_off"] = max(0, r.done_at - t) if r.done_at is not None else 0
        s[p + "da_past"] = int(r.done_at is not None and r.done_at < t)
        s[p + "grpcl"] = r.grpcl
        s[p + "beat_ext"] = r.beat_ext
        s[p + "sreg_held"] = int(r.sreg_held)
        s[p + "sreg"] = int(r.sreg)
        s[p + "li_age"] = min(7, t - r.issued[-1].start) if r.issued else 0
    for k, w in EFIELDS:
        v = s[k]
        if not 0 <= v < (1 << w):
            raise RuntimeError(f"{m.chain.id}: EU {k}={v} at {t} does not fit {w} bits")
    return s


def estate_text(s: dict) -> str:
    return " ".join(str(s[k]) for k, _ in EFIELDS)


def run_eu_model(chain, cfg, chain_base: int, arb: bool = False):
    """(Machine, _Log, QueueRecorder (unmerged), EURecorder, cycles, the queue's start): the
    frozen model as run_model builds it with the queue's, the decoder's and the EU's run
    recorded; its trace checked against run_record's. arb (C4): the arbiter's run recorded too
    (ArbiterRecorder, as the EURecorder's .arb). (D2) The functional reference runs the chain
    first (the EURecorder's fref): every start's record is checked against it, and the EU's
    cycles take its data after the run (functional_cycles)."""
    from . import funcref
    from .sim.frozen import eu as feu
    from .sim.frozen import machine as fm
    from .types import refresh_any
    phase = None
    if refresh_any(chain):
        if not arb:
            raise NotModelled("refresh on (the scripted-arbiter benches; --core models it)")
        phase = (64 - fm.POP_COUNTER[(chain.rfm, chain.wtc)]) % 128   # machine._prelude_run
    try:
        fref = funcref.chain_run(chain, chain_base)
    except funcref.NotModelled as e:
        raise NotModelled(f"functional reference: {e}") from e
    if fref.trap:
        raise NotModelled(f"a divide error (its trap sequence: later): {fref.trap}")
    m = fm.Machine(chain, cfg, chain_base, phase, 0)
    init = (len(m.queue.bytes), [m.queue.byte_at(a) for a, _ in m.queue.bytes],
            m.queue.fetch_addr)
    qrec = QueueRecorder(m, merge=False)
    erec = EURecorder(m, qrec, refresh=arb, fref=fref)
    arec = ArbiterRecorder(m, erec) if arb else None
    rrec = RefreshRecorder(m, erec) if arb and m.refresh is not None else None
    if arec is not None:
        arec.ref = rrec
    log = _Log(m, qrec, erec, arec, rrec)
    m.clock_log = log
    orig_arb, orig_exec = fm.arbitrate, feu.execute
    if arec is None:
        fm.arbitrate = lambda *a: erec.arbitrate(orig_arb, *a)
    else:
        fm.arbitrate = lambda *a: arec.arbitrate(lambda *b: erec.arbitrate(orig_arb, *b), *a)

    def execute(op, code, regs):
        erec.started(op)
        return orig_exec(op, code, regs)
    feu.execute = execute
    try:
        cycles = m.run()
    finally:
        fm.arbitrate, feu.execute = orig_arb, orig_exec
    ref = fm.run_record(chain, cfg, chain_base, None, phase, 0)["socket_trace"]
    if fm.trace_rows(cycles) != ref:
        raise RuntimeError(f"{chain.id}: the logged run differs from run_record's")
    if len(erec.opnds) != len(fref.starts):
        raise RuntimeError(f"{chain.id}: {len(erec.opnds)} starts, the functional reference's "
                           f"{len(fref.starts)}")
    functional_cycles(chain, m, cycles, fref)
    return m, log, qrec, erec, cycles, init


def functional_cycles(chain, m, cycles, fref):
    """(D2) The EU's cycles with the functional reference's data: each EU cycle (in order) is
    the reference's (kind, address, lanes), and takes its datum (`data`: a write's on its lanes,
    0 on a read: what the RTL drives) and, a read, the word the bus delivers (`rdata`: the
    aligned memory word, the I/O word). The model's data (AW at the issue) are the timing
    abstraction's; the run's trace was checked before."""
    mine = [c for c in cycles if c.owner is m.eu]
    if len(mine) != len(fref.cycles):
        raise RuntimeError(f"{chain.id}: {len(mine)} EU cycles, the functional reference's "
                           f"{len(fref.cycles)}")
    for i, (c, f) in enumerate(zip(mine, fref.cycles)):
        if (c.kind, c.addr, c.width) != (f.kind, f.addr, f.width):
            raise RuntimeError(f"{chain.id}: EU cycle {i} {c.kind} {c.addr:05X} {c.width}, the "
                               f"functional reference's {f.kind} {f.addr:05X} {f.width}")
        c.data = f.data
        if f.kind.endswith("read"):
            c.rdata = f.rdata


def _bv_text(v: tuple) -> str:
    return " ".join(str(x) for x in v)


def eu_vectors(chain, cfg, chain_base: int, joint: bool = False, run=None):
    """(the EU bench's vector file, the model's cycles, the EU recorder; with joint also the
    queue's (unmerged, JSLOT ops) and the bus unit's vector files of the same run). run:
    run_eu_model's result (C4: with the arbiter recorded)."""
    if run is None:
        run = run_eu_model(chain, cfg, chain_base)
    m, log, qrec, erec, cycles, init = run
    lines = [f"{EFORMAT} {chain.id} {len(erec.clocks)} {NQ} {NXOP} {len(erec.opnds)} "
             f"{m.queue.base} {erec.fref.code_org}",
             "F " + " ".join(f"{k}:{w}" for k, w in EFIELDS),
             "Q " + " ".join(f"{k}:{dict(QFIELDS)[k]}" for k in QVIEW),
             "I " + estate_text(erec.init),
             "C " + bytes(m.eu.code).hex(),    # (D1) the code at the base: the code window's
             # (D2) the memory besides the 90h default (the functional reference's image)
             f"N {len(erec.fref.mem_init)}" + "".join(f" {a} {b.hex()}"
                                                       for a, b in erec.fref.mem_init)]
    lines += [o.text() for o in erec.opnds]
    for ck in erec.clocks:
        lines.append(f"K {ck.t} {ck.c_eu} {ck.c_read} {ck.fetch_done} {' '.join(map(str, ck.x))} "
                     f"{' '.join(map(str, ck.counts))} {' '.join(map(str, ck.counts_p))} "
                     f"{ck.latch_in} {len(ck.tl)} {ck.n_t} "
                     f"{len(ck.xq)} {len(ck.p)} {len(ck.xops)}")
        lines.append(f"B {_bv_text(ck.bus_t)} {_bv_text(ck.bus_p)}")
        lines.append("S " + estate_text(ck.states["c"]))
        for op, v in zip(ck.tl, ck.qv_tl):
            rd = -1 if op.rd is None else _bits(op.rd, 8)
            lines.append(f"O {QOPS.index(op.code)} {op.a} {op.b} {_bits(op.val, 20)} {op.snap} "
                         f"{rd} {qview_text(v)}")
        lines.append("V " + qview_text(ck.qv_tl[-1]))
        lines.append("S " + estate_text(ck.states["t"]))
        lines.append("S " + estate_text(ck.states["l"]))
        for code, val in ck.xops:
            lines.append(f"X {XOPS.index(code)} {_bits(val, 8)}")
        lines.append("S " + estate_text(ck.states["x"]))
        for op, v in zip(ck.p, ck.qv_p):
            rd = -1 if op.rd is None else _bits(op.rd, 8)
            lines.append(f"O {QOPS.index(op.code)} {op.a} {op.b} {_bits(op.val, 20)} {op.snap} "
                         f"{rd} {qview_text(v)}")
        lines.append("V " + qview_text(ck.qv_p[-1]))
        lines.append("S " + estate_text(ck.states["p"]))
        lines.append("S " + estate_text(ck.states["e"]))
    for c in cycles:
        if c.owner is m.eu:     # (D2) with the datum the EU drives (the functional reference's)
            lines.append(f"D {c.start} {KINDS.index(c.kind)} {c.addr} {BWIDTHS.index(c.width)} "
                         f"{c.data & 0xFFFF}")
    text = "\n".join(lines) + "\n"
    if not joint:
        return text, cycles, erec
    qtext = queue_vectors(chain, cfg, chain_base, run=(m, log, qrec, cycles, init),
                          nslot=JSLOT)[0]
    btext = vectors(chain, cfg, chain_base, (m, log, cycles))[0]
    return text, cycles, erec, qtext, btext


# The EU bench ------------------------------------------------------------------------------

@dataclass
class EResult:
    run_id: str
    joint: bool = False
    clocks: int = 0
    ops: int = 0
    state_bad: int = 0              # EU states (after C, T, L, X, P, the end, registered) differing
    op_bad: int = 0                 # the EU's queue ops differing (count, code, arguments, snapshot)
    err_bad: int = 0                # the RTL flagged a case it does not cover
    dcyc_bad: int = 0               # the EU's data cycle on an issue differing
    q_state_bad: int = 0            # joint: the queue's states
    q_rd_bad: int = 0               # joint: the queue's reads
    gate_bad: int = 0               # joint: a fetch issued without the RTL queue's request
    signal_bad: int = 0             # joint: the bus unit's signals
    biu_state_bad: int = 0          # joint: the bus unit's state
    settle_bad: int = 0             # joint: a clock that did not settle
    opnd_bad: int = 0               # (D1) a start's operand record or register file differing
    cycles: int = 0                 # the model's cycles ...
    rtl_cycles: int = 0             # ... the RTL's (joint: the bus unit's; --eu: the EU's data
    exact_cycles: int = 0           # cycles in the model's stream) ... equal
    starts: int = 0
    rtl_exact: bool | None = None
    model_exact: bool | None = None
    rtl_model_exact: bool | None = None
    first: str = ""
    error: str = ""
    not_modelled: str = ""

    @property
    def ok(self) -> bool:
        bad = (self.state_bad or self.op_bad or self.err_bad or self.dcyc_bad or self.q_state_bad
               or self.q_rd_bad or self.gate_bad or self.signal_bad or self.biu_state_bad
               or self.settle_bad or self.opnd_bad)
        return (not self.error and not self.not_modelled and not bad and self.clocks > 0
                and self.cycles == self.rtl_cycles == self.exact_cycles)


def check_eu_run(rec: dict, cfg, keep: Path | None = None, joint: bool = False) -> EResult:
    from .normalize import normalize
    from .score import model_one, relabel_refresh, score
    from .sim.frozen.machine import refresh_anchor
    s = normalize(rec)
    res = EResult(s.run_id, joint)
    try:
        out = eu_vectors(s.chain, cfg, s.chain_base, joint=joint)
    except NotModelled as e:
        res.not_modelled = str(e)
        return res
    except Exception as e:      # noqa: BLE001
        res.error = f"vectors: {type(e).__name__}: {e}"
        return res
    text, cycles, erec = out[0], out[1], out[2]
    res.starts = len(erec.opnds)
    with tempfile.TemporaryDirectory() as tmp:
        d = keep if keep is not None else Path(tmp)
        epath = d / f"{s.run_id}.evec"
        epath.write_text(text)
        args = [str(EBENCH), str(epath)]
        if joint:
            qpath, bpath = d / f"{s.run_id}.j.qvec", d / f"{s.run_id}.j.vec"
            qpath.write_text(out[3])
            bpath.write_text(out[4])
            args += [str(qpath), str(bpath)]
        p = subprocess.run(args, capture_output=True, text=True, cwd=ROOT)
    if keep is not None:
        (keep / f"{s.run_id}.{'joint3' if joint else 'eu'}.out").write_text(p.stdout + p.stderr)
    sm, cyc, dc, fails = {}, [], {}, []
    for line in p.stdout.splitlines():
        f = line.split()
        if not f:
            continue
        if f[0] == "SUMMARY":
            sm = {k: int(v) for k, v in (x.split("=") for x in f[1:])}
        elif f[0] == "CYC":
            cyc.append(tuple(int(x) for x in f[1:]))
        elif f[0] == "DCYC":
            dc[int(f[1])] = tuple(int(x) for x in f[2:])
        elif f[0] == "FAIL":
            fails.append(line)
    if p.returncode not in (0, 1) or not sm:
        res.error = f"bench exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}"
        return res
    for k in ("clocks", "ops", "state_bad", "op_bad", "err_bad", "dcyc_bad", "q_state_bad",
              "q_rd_bad", "gate_bad", "signal_bad", "biu_state_bad", "settle_bad", "opnd_bad"):
        setattr(res, k, sm.get(k, 0))
    res.first = fails[0] if fails else ""
    model = [(c.start, c.length, KINDS.index(c.kind), c.addr, BWIDTHS.index(c.width),
              c.data & 0xFFFF) for c in cycles]
    if joint:
        rtl = cyc
    else:
        # the model's stream with the EU's data cycles as the RTL issued them
        rtl = []
        for c, mrow in zip(cycles, model):
            if c.owner is not None and c.kind != "fetch" and c.kind != "refresh" and c.start in dc:
                k, a, w = dc[c.start]
                rtl.append((c.start, c.length, k, a, w, c.data & 0xFFFF))
            else:
                rtl.append(mrow)
    res.cycles = len(model)
    res.rtl_cycles = len(rtl)
    res.exact_cycles = sum(1 for x, y in zip(model, rtl) if x == y)
    try:
        rrec = {"chain": rec["chain"], "chain_base": s.chain_base, "complete": True,
                "socket_trace": rtl_trace(rtl)}
        n = normalize(rrec, strict=False)
        anchor = refresh_anchor(s, events=False)
        relabel_refresh(n, anchor[1] if anchor is not None else 0)
        _, mn, msc = model_one(s, cfg)
        res.model_exact = msc.exact
        res.rtl_exact = score(s, n).exact
        res.rtl_model_exact = score(mn, n).exact if mn is not None else False
    except Exception as e:      # noqa: BLE001
        res.error = f"score: {type(e).__name__}: {e}"
    return res


def _report_eu(f, rs, show, joint) -> int:
    nm = [r for r in rs if r.not_modelled]
    run = [r for r in rs if not r.not_modelled]
    ok = sum(r.ok for r in run)
    tot = {k: sum(getattr(r, k) for r in run) for k in (
        "clocks", "ops", "state_bad", "op_bad", "err_bad", "dcyc_bad", "q_state_bad",
        "q_rd_bad", "gate_bad", "signal_bad", "biu_state_bad", "settle_bad", "cycles",
        "exact_cycles", "starts", "opnd_bad")}
    me = sum(bool(r.model_exact) for r in run)
    re_ = sum(bool(r.rtl_exact) for r in run)
    rm = sum(bool(r.rtl_model_exact) for r in run)
    line = (f"{f:<5} {len(rs):>5} runs  {ok} exact against the model ({len(nm)} not modelled)  "
            f"clocks {tot['clocks']} starts {tot['starts']} ops {tot['ops']} (state fails "
            f"{tot['state_bad']}, op fails {tot['op_bad']}, RTL errors {tot['err_bad']}, data "
            f"cycle fails {tot['dcyc_bad']}, operand record fails {tot['opnd_bad']})  cycles "
            f"{tot['exact_cycles']}/{tot['cycles']}")
    if joint:
        line += (f" (queue state fails {tot['q_state_bad']}, queue read fails {tot['q_rd_bad']}, "
                 f"ungated fetches {tot['gate_bad']}, "
                 f"bus signal fails {tot['signal_bad']}, bus state fails {tot['biu_state_bad']}, "
                 f"unsettled {tot['settle_bad']})")
    line += f"  vs silicon: model-exact {me}, RTL-exact {re_}, RTL = model {rm}"
    print(line)
    bad = [r for r in run if not r.ok]
    for r in bad[:show]:
        print(f"    {r.run_id}: {r.error or r.first or 'cycles differ'}")
    reasons: dict = {}
    for r in nm:
        reasons[r.not_modelled.split(" at ")[0][:90]] = reasons.get(
            r.not_modelled.split(" at ")[0][:90], 0) + 1
    for k, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:show]:
        print(f"    not modelled ({n}): {k}")
    return len(bad)


# C4: the arbiter and the core ---------------------------------------------------------------
#
# The arbiter (v35_arbiter.sv) is a function of the four machines' state on each clock plus the
# request records' fields it owns: the setup count, the post's clock, ready_since, lift_t,
# free_held, grp_held (the record's other fields are the EU's, C3's RFIELDS), and the bus history
# it reads (_fetch_run's last two cycles, grp_io_hold's last I/O start). ArbiterRecorder wraps the
# frozen machine module's `arbitrate` (around the EU recorder's wrap; the model is not changed):
# after the choice and at the end of every clock it takes those fields in the RTL's
# representation (ARFIELDS: flags for "== t", an age for the post, by the EU's request
# positions), and every store the arbiter makes into a request is classified here (the EU
# recorder hands them over): a count, a stamp set to the clock, the refresh-only eu_halted; any
# other raises (NotModelled), as does a take sync below the completed count at a choice (the RTL
# keeps only the fetches still owed). The core bench (fpga/v35s/v35_core_tb.sv and .cpp,
# fpga/v35s/build_core_tb.sh, binary in build/fpga/v35s/core-tb/) runs v35_chain_core.sv from the
# start state, the operand records and the EU's write data (Phase D) with its memory served from
# the image, and checks every machine after every phase of every clock against the model (the
# EU's, the queue's, the bus unit's and the arbiter's vectors of the same run) and the cycles.

CBENCH = ROOT / "build" / "fpga" / "v35s" / "core-tb" / "Vv35_core_tb"
AFORMAT = "V35ARB-2"         # (C5) with the refresh controller's state and its start
NXQ = 8                      # the arbiter's queue ops per clock (v35_arbiter.sv NXQ)

# the arbiter's state (v35_arbiter.sv v35_ast_t: q[2..0], then the bus history; MSB first)
ARQFIELDS = (
    ("count", 7),            # setup clocks counted
    ("p_age", 8),            # t - posted (saturating at 255)
    ("rs_v", 1),             # ready_since is set ...
    ("rs_now", 1),           # ... == t
    ("lift_v", 1),           # lift_t is set ...
    ("lift_now", 1),         # ... == t
    ("fh_now", 1),           # free_held == t
    ("gh_now", 1),           # grp_held == t
    ("xeu", 3),              # (C5) dw_view=eu: t, t-1, t-2 in req.xeu (bit 0: t)
    ("so_v", 1),             # (WP77) sreg_store=own: sreg_ok is set ...
    ("so_now", 1),           # ... == t
    ("sa_v", 1),             # (WP77) sreg_io=hold: sreg_at is set
)
ARFIELDS = (tuple((f"q{i}_{n}", w) for i in (2, 1, 0) for n, w in ARQFIELDS)
            + (("run", 1), ("io_v", 1), ("io_age", 4),
               # (C5) the bus history the refresh's rules read
               ("early_on", 1),      # refresh_sync=run: the cycle last started is bus.early
               ("early_ok", 1),      # bus.early_ok
               ("early_n", 3),       # bus.early_n (saturating at 7)
               ("after_ref", 1),     # the cycle last started began right after a refresh's end
               ("lc_age", 8),        # t - the last cycle's end (0 while it covers t; sat 255)
               ("rf_v", 1),          # a refresh has started ...
               ("rf_n", 2),          # ... cycles started after the last one (saturating at 3)
               ("rf_age", 8)))       # ... t - its end (0 while it covers t; saturating at 255)
ASTATE_W = sum(w for _, w in ARFIELDS)


def astate(m, t: int) -> dict:
    """The arbiter's state on clock t in the RTL's representation (ARFIELDS)."""
    eu, bus = m.eu, m.bus
    slots = ([eu.req] + list(eu.queued) + [None, None])[:3]
    s = {}
    for i, r in enumerate(slots):
        p = f"q{i}_"
        if r is None:
            for n, _ in ARQFIELDS:
                s[p + n] = 0
            continue
        if not 0 <= r.count < 128:
            raise NotModelled(f"a setup count of {r.count} at {t}")
        s[p + "count"] = r.count
        s[p + "p_age"] = min(255, t - r.posted)
        s[p + "rs_v"] = int(r.ready_since is not None)
        s[p + "rs_now"] = int(r.ready_since == t)
        s[p + "lift_v"] = int(r.lift_t is not None)
        s[p + "lift_now"] = int(r.lift_t == t)
        s[p + "fh_now"] = int(r.free_held == t)
        s[p + "gh_now"] = int(r.grp_held == t)
        x = r.xeu or set()
        s[p + "xeu"] = sum(1 << i for i in range(3) if t - i in x)
        s[p + "so_v"] = int(r.sreg_ok is not None)
        s[p + "so_now"] = int(r.sreg_ok == t)
        s[p + "sa_v"] = int(r.sreg_at is not None)
    cyc = bus.cycles
    last = cyc[-1] if cyc else None
    s["early_on"] = int(bus.early is not None and bus.early is last)
    s["early_ok"] = int(bool(bus.early_ok))
    s["early_n"] = min(7, bus.early_n)
    s["after_ref"] = int(len(cyc) >= 2 and cyc[-2].kind == "refresh"
                         and cyc[-2].end == cyc[-1].start - 1)
    s["lc_age"] = max(0, min(255, t - last.end)) if last is not None else 0
    k = next((i for i in range(len(cyc) - 1, -1, -1) if cyc[i].kind == "refresh"), None)
    s["rf_v"] = int(k is not None)
    s["rf_n"] = min(3, len(cyc) - 1 - k) if k is not None else 0
    s["rf_age"] = max(0, min(255, t - cyc[k].end)) if k is not None else 0
    cs = [c for c in bus.cycles if c.kind != "refresh"]
    s["run"] = int(len(cs) >= 2 and cs[-1].kind == "fetch" and cs[-2].kind == "fetch"
                   and cs[-2].end == cs[-1].start - 1)
    ios = [c for c in bus.cycles if c.kind.startswith("io")]
    s["io_v"] = int(bool(ios))
    s["io_age"] = min(15, t - ios[-1].start) if ios else 0
    for k, w in ARFIELDS:
        if not 0 <= s[k] < (1 << w):
            raise RuntimeError(f"{m.chain.id}: arbiter {k}={s[k]} at {t} does not fit {w} bits")
    return s


def astate_text(s: dict) -> str:
    return " ".join(str(s[k]) for k, _ in ARFIELDS)


@dataclass
class AClock:
    t: int
    ext: int = 0                # disp_io=extend on this clock's cycle
    s_x: dict | None = None     # after the choice (X)
    s_e: dict | None = None     # at the end of the clock


class ArbiterRecorder:
    """Records the arbiter's own state per clock and classifies its stores (the section comment
    above)."""

    def __init__(self, m, erec):
        self.m, self.erec = m, erec
        erec.arb = self
        self.clocks: list[AClock] = []
        self.cur: AClock | None = None
        self.stores: dict = {}      # the classified stores, by kind (for the report and tests)
        self.ref = None             # (C5) the RefreshRecorder (refresh-on runs)

    def arbitrate(self, inner, t, cfg, bus, queue, eu):
        if isinstance(eu.sync, int) and eu.sync < queue.completed:
            raise NotModelled(f"the take sync {eu.sync} below the completed count "
                              f"{queue.completed} at {t}")
        c = inner(t, cfg, bus, queue, eu)
        ext = int(c is not None and bus.last_end == c.end + 1)
        self.cur = AClock(t, ext, astate(self.m, t))
        return c

    def store(self, k, v, t):
        """A store of the arbiter's into a request (phase X): its own fields only."""
        m = self.m
        if k == "count":
            if not (isinstance(v, int) and 0 <= v < 128):
                raise NotModelled(f"the arbiter sets a count of {v!r} at {t}")
        elif k in ("ready_since", "lift_t", "free_held", "grp_held", "sreg_at"):
            if v != t:
                raise NotModelled(f"the arbiter sets {k} = {v!r} at {t}")
        elif k == "sreg_ok":                # (WP77) sreg_store=own: set to t or cleared
            if v is not None and v != t:
                raise NotModelled(f"the arbiter sets sreg_ok = {v!r} at {t}")
        elif k == "eu_halted":
            if v != m.eu.halted:
                raise NotModelled(f"eu_halted = {v!r} at {t}")
            # (C5) refresh_io_stall reads it: the RTL reads the EU's halted for the slot's
            # request (stored every clock) and False for one just moved in (never stored)
        elif k == "xeu":
            if v != set():
                raise NotModelled(f"the arbiter sets xeu = {v!r} at {t}")
            # (C5) dw_view=eu: the set's adds are the arbiter's state (ARFIELDS' xeu)
        else:
            raise NotModelled(f"the arbiter writes req.{k} = {v!r} at {t}")
        self.stores[k] = self.stores.get(k, 0) + 1

    def row(self):
        t = self.erec.t - 1         # the EU recorder's row has moved on
        if self.cur is None or self.cur.t != t:
            raise NotModelled(f"no arbitration recorded for clock {t}")
        self.cur.s_e = astate(self.m, t)
        self.clocks.append(self.cur)
        self.cur = None


# (C5) the refresh controller (v35_refresh.sv): its state per clock after phase R and at the end
# (refresh.py's Refresh in the RTL's representation), and every store into it classified by the
# method that makes it (an unclassified store raises NotModelled).
RFFIELDS = (
    ("counter", 7),          # (c0 + t) mod 128
    ("prev_v", 1),           # prev_bit is set (not on clock 0) ...
    ("prev_bit", 1),         # ... the selected counter bit on the last clock
    ("rft", 2),              # RFM.RFT
    ("on", 1),               # RFM.RFEN
    ("pending", 1),          # a request is pending
    ("wv", 1),               # an RFM write waits to take effect ...
    ("w_off", 2),            # ... at t + w_off ...
    ("w_value", 8),          # ... with this value
)
RSTATE_W = sum(w for _, w in RFFIELDS)
# the Refresh's stores, by the method that makes them (refresh.py); `served` and `writes` are
# logs (appended to, not stored), `due` and `interval` dead under refresh_counter=edge
_REFRESH_STORES = {"raise_": {"write_at", "prev_bit", "pending"},
                   "_apply": {"on", "due", "interval", "rft", "pending"},
                   "start": {"pending"}, "write": {"write_at"}}


def rstate(ref, t: int) -> dict:
    w = ref.write_at
    s = {"counter": (ref.c0 + t) % 128, "prev_v": int(ref.prev_bit is not None),
         "prev_bit": ref.prev_bit or 0, "rft": ref.rft, "on": int(bool(ref.on)),
         "pending": int(ref.pending is not None), "wv": int(w is not None),
         "w_off": w[0] - t if w is not None else 0, "w_value": w[1] if w is not None else 0}
    for k, wd in RFFIELDS:
        if not 0 <= s[k] < (1 << wd):
            raise NotModelled(f"refresh {k}={s[k]} at {t} does not fit {wd} bits")
    return s


def rstate_text(s: dict) -> str:
    return " ".join(str(s[k]) for k, _ in RFFIELDS)


class RefreshRecorder:
    """(C5) Records the refresh controller per clock: its state after phase R (Refresh.raise_,
    between the decoder's IR load and the arbiter) and at the end of the clock; checks that
    raise_ runs in phase R, start in the arbiter's _refresh and write in the EU's issue (phase X),
    and classifies every store (_REFRESH_STORES)."""

    def __init__(self, m, erec):
        self.m, self.erec = m, erec
        ref = m.refresh
        self.init_counter = ref.c0 % 128
        self.t = 0
        self.cur_r: dict | None = None
        self.clocks: list = []          # (t, after R, end)
        self.starts = self.writes = self.applies = 0
        base = type(ref)
        rec = self

        def setattr_(obj, k, v):
            fn = sys._getframe(1).f_code.co_name
            if fn != "__init__" and k not in _REFRESH_STORES.get(fn, ()):
                raise NotModelled(f"refresh.{k} = {v!r} from {fn} at {rec.t}")
            object.__setattr__(obj, k, v)

        def raise_(obj, t):
            if rec.erec.phase != "L1" or t != rec.t:
                raise NotModelled(f"refresh.raise_ in phase {rec.erec.phase} at {t}")
            w = obj.write_at
            out = base.raise_(obj, t)
            if w is not None and obj.write_at is None:
                rec.applies += 1
            rec.cur_r = rstate(obj, t)
            return out

        def start(obj, t, length):
            if rec.erec.phase != "X" or _caller_file() != "arbiter.py":
                raise NotModelled(f"refresh.start outside the arbiter's X at {t}")
            rec.starts += 1
            return base.start(obj, t, length)

        def write(obj, value, t, c):
            if rec.erec.phase != "X" or sys._getframe(1).f_code.co_name != "issue":
                raise NotModelled(f"refresh.write outside eu.issue at {t}")
            rec.writes += 1
            return base.write(obj, value, t, c)

        ref.__class__ = type("RecordedRefresh", (base,), {
            "__setattr__": setattr_, "raise_": raise_, "start": start, "write": write})

    def row(self):
        t = self.t
        if self.cur_r is None:
            raise NotModelled(f"no refresh phase R recorded for clock {t}")
        self.clocks.append((t, self.cur_r, rstate(self.m.refresh, t)))
        self.cur_r = None
        self.t = t + 1


def core_vectors(chain, cfg, chain_base: int):
    """(the EU's, the queue's (JSLOT ops), the bus unit's and the arbiter's vector files of one
    run, the model's cycles, the EU recorder, the arbiter recorder)."""
    run = run_eu_model(chain, cfg, chain_base, arb=True)
    m, log, qrec, erec, cycles, init = run
    arec = erec.arb
    etext, _, _, qtext, btext = eu_vectors(chain, cfg, chain_base, joint=True, run=run)
    if len(arec.clocks) != len(erec.clocks):
        raise RuntimeError(f"{chain.id}: {len(arec.clocks)} arbiter clocks, "
                           f"{len(erec.clocks)} EU clocks")
    for ck in qrec.clocks:
        nx = sum(1 for o in ck.ops if o.phase == "X")
        if nx > NXQ:
            raise NotModelled(f"{nx} arbiter queue ops at {ck.t} (the RTL holds {NXQ})")
    data = [c.data & 0xFFFF for c in cycles if c.owner is m.eu]
    rrec = arec.ref
    if rrec is not None and len(rrec.clocks) != len(arec.clocks):
        raise RuntimeError(f"{chain.id}: {len(rrec.clocks)} refresh clocks, "
                           f"{len(arec.clocks)} arbiter clocks")
    lines = [f"{AFORMAT} {chain.id} {len(arec.clocks)} {len(data)} {int(rrec is not None)} "
             f"{rrec.init_counter if rrec is not None else 0}",
             "F " + " ".join(f"{k}:{w}" for k, w in ARFIELDS),
             "R " + " ".join(f"{k}:{w}" for k, w in RFFIELDS)]
    for i, ac in enumerate(arec.clocks):
        lines.append(f"K {ac.t} {ac.ext}")
        lines.append("S " + astate_text(ac.s_x))
        lines.append("S " + astate_text(ac.s_e))
        if rrec is not None:
            rt, sr, se = rrec.clocks[i]
            if rt != ac.t:
                raise RuntimeError(f"{chain.id}: refresh clock {rt} beside arbiter clock {ac.t}")
            lines.append("R " + rstate_text(sr))
            lines.append("R " + rstate_text(se))
    lines.append("W " + " ".join(map(str, data)))
    atext = "\n".join(lines) + "\n"
    return etext, qtext, btext, atext, cycles, erec, arec


@dataclass
class CResult:
    run_id: str
    clocks: int = 0
    ops: int = 0
    starts: int = 0
    state_bad: int = 0              # the EU's states
    op_bad: int = 0                 # the chain's ops (the EU's, the arbiter's) and their counts
    err_bad: int = 0                # the core's or a machine's error
    dcyc_bad: int = 0               # the EU's data cycles
    q_state_bad: int = 0            # the queue's states
    q_rd_bad: int = 0               # the queue's reads
    x_bad: int = 0                  # the arbiter's touches on the EU
    a_state_bad: int = 0            # the arbiter's state
    r_state_bad: int = 0            # (C5) the refresh controller's state
    signal_bad: int = 0             # the bus unit's signals
    biu_state_bad: int = 0          # the bus unit's state
    settle_bad: int = 0             # a clock that did not settle
    opnd_bad: int = 0               # (D1) a start's operand record or register file
    iter_total: int = 0             # settle edges over the run's clocks ...
    iter_max: int = 0               # ... the most in one clock
    iters: dict | None = None       # ... per clock: edges -> clocks
    cycles: int = 0                 # the model's cycles ...
    rtl_cycles: int = 0             # ... the core's ...
    exact_cycles: int = 0           # ... equal (start, length, kind, address, width, data)
    rtl_exact: bool | None = None
    model_exact: bool | None = None
    rtl_model_exact: bool | None = None
    first: str = ""
    error: str = ""
    not_modelled: str = ""

    BAD = ("state_bad", "op_bad", "err_bad", "dcyc_bad", "q_state_bad", "q_rd_bad", "x_bad",
           "a_state_bad", "r_state_bad", "signal_bad", "biu_state_bad", "settle_bad", "opnd_bad")

    @property
    def fails(self) -> int:
        return sum(getattr(self, k) for k in self.BAD)

    @property
    def ok(self) -> bool:
        return (not self.error and not self.not_modelled and not self.fails and self.clocks > 0
                and self.cycles == self.rtl_cycles == self.exact_cycles)


def check_core_run(rec: dict, cfg, keep: Path | None = None, mutate: int = 0,
                   chain=None) -> CResult:
    """One run through the core bench. chain (WP77): a variant of the run's chain to run in
    its place (the RTL against the frozen model only, not scored against silicon)."""
    from .normalize import normalize
    from .score import model_one, relabel_refresh, score
    from .sim.frozen.machine import refresh_anchor
    s = normalize(rec)
    res = CResult(s.run_id)
    try:
        etext, qtext, btext, atext, cycles, erec, arec = core_vectors(
            s.chain if chain is None else chain, cfg, s.chain_base)
    except NotModelled as e:
        res.not_modelled = str(e)
        return res
    except Exception as e:      # noqa: BLE001
        res.error = f"vectors: {type(e).__name__}: {e}"
        return res
    with tempfile.TemporaryDirectory() as tmp:
        d = keep if keep is not None else Path(tmp)
        paths = [d / f"{s.run_id}.c.{x}" for x in ("evec", "qvec", "vec", "avec")]
        for path, text in zip(paths, (etext, qtext, btext, atext)):
            path.write_text(text)
        args = [str(CBENCH)] + [str(x) for x in paths] + ([str(mutate)] if mutate else [])
        p = subprocess.run(args, capture_output=True, text=True, cwd=ROOT)
    if keep is not None:
        (keep / f"{s.run_id}.core.out").write_text(p.stdout + p.stderr)
    sm, cyc, fails, iters = {}, [], [], {}
    for line in p.stdout.splitlines():
        f = line.split()
        if not f:
            continue
        if f[0] == "SUMMARY":
            sm = {k: int(v) for k, v in (x.split("=") for x in f[1:])}
        elif f[0] == "CYC":
            cyc.append(tuple(int(x) for x in f[1:]))
        elif f[0] == "ITER":
            iters[int(f[1])] = int(f[2])
        elif f[0] == "FAIL":
            fails.append(line)
    if p.returncode not in (0, 1) or not sm:
        res.error = f"bench exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}"
        return res
    for k in ("clocks", "ops", "starts", "iter_total", "iter_max") + CResult.BAD:
        setattr(res, k, sm.get(k, 0))
    res.iters = iters
    res.first = fails[0] if fails else ""
    model = [(c.start, c.length, KINDS.index(c.kind), c.addr, BWIDTHS.index(c.width),
              c.data & 0xFFFF) for c in cycles]
    res.cycles, res.rtl_cycles = len(model), len(cyc)
    res.exact_cycles = sum(1 for x, y in zip(model, cyc) if x == y)
    if chain is not None:
        return res
    try:
        rrec = {"chain": rec["chain"], "chain_base": s.chain_base, "complete": True,
                "socket_trace": rtl_trace(cyc)}
        n = normalize(rrec, strict=False)
        anchor = refresh_anchor(s, events=False)
        relabel_refresh(n, anchor[1] if anchor is not None else 0)
        _, mn, msc = model_one(s, cfg)
        res.model_exact = msc.exact
        res.rtl_exact = score(s, n).exact
        res.rtl_model_exact = score(mn, n).exact if mn is not None else False
    except Exception as e:      # noqa: BLE001
        res.error = f"score: {type(e).__name__}: {e}"
    return res


def _report_core(f, rs, show) -> int:
    nm = [r for r in rs if r.not_modelled]
    run = [r for r in rs if not r.not_modelled]
    ok = sum(r.ok for r in run)
    tot = {k: sum(getattr(r, k) for r in run) for k in (
        "clocks", "ops", "starts", "cycles", "exact_cycles", "iter_total") + CResult.BAD}
    fails = sum(tot[k] for k in CResult.BAD)
    me = sum(bool(r.model_exact) for r in run)
    re_ = sum(bool(r.rtl_exact) for r in run)
    rm = sum(bool(r.rtl_model_exact) for r in run)
    imax = max((r.iter_max for r in run), default=0)
    imean = tot["iter_total"] / tot["clocks"] if tot["clocks"] else 0.0
    detail = ", ".join(f"{k[:-4]} {tot[k]}" for k in CResult.BAD if tot[k])
    print(f"{f:<5} {len(rs):>5} runs  {ok} exact against the model ({len(nm)} not modelled)  "
          f"clocks {tot['clocks']} starts {tot['starts']} ops {tot['ops']}  fails {fails}"
          f"{' (' + detail + ')' if detail else ''}  bus cycles {tot['exact_cycles']}/"
          f"{tot['cycles']}  settle edges/clock max {imax} mean {imean:.2f}  vs silicon: "
          f"model-exact {me}, RTL-exact {re_}, RTL = model {rm}")
    bad = [r for r in run if not r.ok]
    for r in bad[:show]:
        print(f"    {r.run_id}: {r.error or r.first or 'cycles differ'}")
    reasons: dict = {}
    for r in nm:
        k = r.not_modelled.split(" at ")[0][:90]
        reasons[k] = reasons.get(k, 0) + 1
    for k, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:show]:
        print(f"    not modelled ({n}): {k}")
    return len(bad)


# D1, D2: the register file, the EA adder and the ALU ----------------------------------------
#
# The EU's register file (v35_eu.sv: v35_rf_t in the state, FFIELDS) and the package functions
# that read and write it: eu_decode, v35_operands (templates.decode's operands: the record),
# v35_execute (the instruction's function at its start), v35_deliver (a read's datum and, on
# the request's last cycle, the read's effects), v35_wdata (a cycle's datum at its issue). In
# --eu, --joint3 and --core the EU computes every start's record from its own register file and
# the benches compare it with the model's (the P lines: OpRec) and (D2) the register file before
# it with the functional reference's (funcref.py); every EU cycle's datum with the reference's
# (the D lines, the W line), the memory the benches serve written by the EU's own writes. The
# unit bench (fpga/v35s/v35_rf_tb.sv and .cpp, fpga/v35s/build_rf_tb.sh, binary in
# build/fpga/v35s/rf-tb/) runs the functions alone, an instruction at a time with its cycles in
# order (regfile_vectors, V35RF-2): every instruction start of the families' chains as the
# reference walks them (walk), every distinct encoding of those again on random register files
# and memory (random), the 24 ModR/M memory modes on the forms that compute an address (modes),
# and random operands (edge values among them) on every ALU form the decoder knows: the 00-3F
# block, the 80-83 group, TEST, XCH, the shift group with its counts, NOT / NEG / MULU / MUL /
# DIVU / DIV, INC / DEC, the 70-7F conditions and DBNZ on random PSWs (alu). The expected values
# are the functional reference's; sst.py --rtl runs SingleStepTests through the same bench.
#
#     PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --regfile --family F0 ...

RFBENCH = ROOT / "build" / "fpga" / "v35s" / "rf-tb" / "Vv35_rf_tb"
RFFORMAT = "V35RF-2"
RK = {"read": 1, "write": 2, "io_read": 3, "io_write": 4}       # V35_RK_*
EDGES = (0x0000, 0x0001, 0x0002, 0x007F, 0x0080, 0x00FF, 0x0100, 0x7FFF, 0x8000, 0x8001,
         0xFFFE, 0xFFFF)
SHIFT_COUNTS = (0, 1, 2, 7, 8, 9, 15, 16, 17, 18, 31, 32, 33, 255)


def func_ok(code: bytes) -> bool:
    """(D2) v35_eu_pkg v35_func_ok: the forms whose function the RTL builds (the rest raise
    V35_EE_FUNC): not F6/F7 /1, FF /2-/5 /7, the register forms of F6/F7 /2 /3, FF, 8F and
    C6/C7, 8F /1-7, MOV PS,r/m (8E /1), PREPARE with a level."""
    o, m = code[0], code[1]
    mod, reg = m >> 6, (m >> 3) & 7
    if o in (0xF6, 0xF7) and (reg == 1 or (mod == 3 and reg in (2, 3))):
        return False
    if o == 0xFF and (reg in (2, 3, 4, 5, 7) or mod == 3):
        return False
    if o == 0x8F and (mod == 3 or reg != 0):
        return False
    if o in (0xC6, 0xC7) and mod == 3:
        return False
    if o == 0x8E and reg & 3 == 1:
        return False
    return not (o == 0xC8 and code[3] != 0)


def rtl_decodes(code: bytes) -> bool:
    """(D2) eu_decode knows the opcode (op.ok), for the vector generators (the bench checks
    the RTL's own): the catalog's opcodes and the 70-7F conditions."""
    o, m = code[0], code[1]
    mod, reg = m >> 6, (m >> 3) & 7
    if o in (0x26, 0x2E, 0x36, 0x3E, 0x90, 0x92, 0xF4, 0x50, 0x58, 0x59, 0x05, 0xA8, 0xA9, 0xA1,
             0xA3, 0xEB, 0xE2, 0xE9, 0xE8, 0xC3, 0x68, 0x6A, 0x60, 0x61, 0xC8, 0xC9, 0x06, 0x0E,
             0x16, 0x1E, 0x07, 0x17, 0x1F, 0xD7):
        return True
    if 0xB0 <= o <= 0xBF or 0xE4 <= o <= 0xE7 or 0xEC <= o <= 0xEF or 0x70 <= o <= 0x7F:
        return True
    if o < 0x40 and o & 7 < 4:
        return True
    if 0x84 <= o <= 0x8F:
        return not (o == 0x8D and mod == 3)
    if o in (0x81, 0x83, 0xC6, 0xC7, 0xC1, 0xD0, 0xD1, 0xD3, 0xF7, 0xFF):
        return True
    return o == 0xF6 and reg != 0


def _rf_text(regs: dict) -> str:
    f = rf_of(regs)
    return " ".join(str(f[n]) for n, _ in FFIELDS)


def rf_vector(before: dict, code6: bytes, pc: int, org: int, st, after: dict | None, *,
              mutate: int = 0, bad: bool = False, trap: bool = False, nxt: int | None = None,
              wdata: list | None = None) -> str:
    """One V35RF-2 line: the register file before (a funcref snapshot), the instruction's six
    bytes at code offset pc (code_org org), the functional reference's start st (the record,
    the cycles in order: a read's delivered word, a write's datum, or wdata's), the register
    file after (a snapshot), the next offset (default: st's target or pc + its length), the
    trap. bad: a form whose function the RTL does not build (only obad is compared)."""
    head = f"V {_rf_text(before)} {code6.hex()} {pc} {org} {mutate}"
    if bad:
        return f"{head} 0 0 0 0 0 0 0 1 0 0 {_rf_text(before)} 0"
    ret = code6[0] == 0xC3
    rec = (st.ea, st.port, st.sr, st.sw, st.count, int(st.taken),
           0 if ret or not st.taken else st.target)
    if nxt is None:
        nxt = st.target if st.taken else (pc + st.length) & 0xFFFF
    cyc, req, odd, wi = [], None, 0, 0
    for c in st.cycles:
        if c.req != req:
            req, odd = c.req, c.addr & 1
        if c.kind.endswith("write"):
            d = wdata[wi] if wdata is not None else c.data
            wi += 1
        else:
            d = c.rdata
        split = c.w2 and odd and not c.kind.startswith("io")
        cyc.append(f"{RK[c.kind]} {int(c.w2)} {odd} {int(split and not c.last)} {int(c.last)} "
                   f"{d & 0xFFFF}")
    tail = _rf_text(after if after is not None else before)
    return (f"{head} {' '.join(map(str, rec))} 0 {nxt & 0xFFFF} {len(cyc)}"
            + "".join(" " + x for x in cyc) + f" {tail} {int(trap)}")


def single_step(regs: dict, code6: bytes, mem: bytearray, pc: int, io_word: int | None = None):
    """(the Start, the register file after, trap) of the functional reference on one
    instruction at PS:pc (its bytes placed there) from regs (a snapshot) and mem."""
    from . import funcref
    cpu = funcref.Cpu(regs, mem, funcref.IO_WORD if io_word is None else io_word, 0)
    cpu.pfx = regs.get("pfx")
    base = regs["PS"] << 4
    for i, b in enumerate(code6 + b"\x90\x90"):
        mem[(base + ((pc + i) & 0xFFFF)) & 0xFFFFF] = b
    try:
        st = cpu.step(pc)
    except funcref.Trap as e:
        return e.start, None, True
    return st, cpu.snapshot(), False


def _random_regs(rnd) -> dict:
    from .funcref import REG16, SREG
    regs = {n: (rnd.choice(EDGES) if rnd.random() < 0.2 else rnd.randrange(1 << 16))
            for n in REG16 + SREG}
    regs["PSW"] = rnd.randrange(1 << 16)
    regs["pfx"] = rnd.choice((None, None, None, 0, 1, 2, 3))
    return regs


def _case(rnd, base_mem: bytes, code6: bytes, regs: dict | None = None, pc: int | None = None,
          mutate: int = 0, operand: int | None = None) -> str | None:
    """A random-state vector of code6 (None: outside the RTL's decode or the reference's).
    operand: the memory operand's word (else the random memory's)."""
    from . import funcref
    if not rtl_decodes(code6):
        return None
    regs = dict(regs) if regs is not None else _random_regs(rnd)
    pc = rnd.randrange(0, 0xFFF0) if pc is None else pc
    if not func_ok(code6):
        return rf_vector(regs, code6, pc, 0, None, None, mutate=mutate, bad=True)
    mem = bytearray(base_mem)
    if operand is not None and code6[0] not in (0x05, 0xA8, 0xA9) and code6[0] & 0xF0 != 0x70:
        cpu = funcref.Cpu(regs, mem, funcref.IO_WORD, 0)
        cpu.cur = regs.get("pfx")
        mod, _, _, off, sb, _ = cpu.modrm(code6, 1)
        if mod != 3:
            for i in range(2):
                mem[(sb + ((off + i) & 0xFFFF)) & 0xFFFFF] = (operand >> (8 * i)) & 0xFF
    try:
        st, after, trap = single_step(regs, code6, mem, pc)
    except funcref.NotModelled:
        return None
    return rf_vector(regs, code6, pc, 0, st, after, mutate=mutate, trap=trap)


def walk_vectors(chain, chain_base: int) -> list[tuple[str, bytes, int]]:
    """(D2) every instruction start of the chain as the functional reference walks it (the
    prelude's tail first, as Machine; the taken transfers followed; a string form skipped):
    [(the vector, the six bytes, the code offset)]."""
    from . import funcref
    run = funcref.chain_run(chain, chain_base)
    out = []
    for i, st in enumerate(run.starts):
        if not rtl_decodes(st.code):
            continue
        after = run.starts[i + 1].regs if i + 1 < len(run.starts) else run.final
        out.append((rf_vector(st.regs, st.code, st.pc, run.code_org, st, after,
                              bad=not func_ok(st.code)), st.code, st.pc))
    return out


EA_FORMS = (bytes([0x8B]), bytes([0x89]), bytes([0x8D]), bytes([0xC7]), bytes([0x01]),
            bytes([0xFF]), bytes([0x8F]), bytes([0xF7]), bytes([0x81]))


def alu_codes(rnd) -> list[bytes]:
    """(D2) one encoding of every ALU form the decoder knows, each operand kind (a register,
    [BW], [BP+d8] in SS, a direct address), with random registers and immediates (the shift
    counts from SHIFT_COUNTS)."""
    mems = (0x07, 0x46, 0x06)           # [BW], [BP+d8], direct

    def modrm(reg, kind):
        if kind == "r":
            return bytes([0xC0 | reg << 3 | rnd.randrange(8)])
        m = rnd.choice(mems)
        return bytes([m | reg << 3]) + bytes(rnd.randrange(256) for _ in range(
            1 if m == 0x46 else 2 if m == 0x06 else 0))

    def imm(n):
        v = rnd.choice(EDGES) if rnd.random() < 0.5 else rnd.randrange(1 << 16)
        return v.to_bytes(2, "little")[:n]

    out = []
    for kind in ("r", "m"):
        for op in range(8):
            for k in range(4):
                out.append(bytes([op * 8 + k]) + modrm(rnd.randrange(8), kind))
        for reg in range(8):
            out.append(bytes([0x81]) + modrm(reg, kind) + imm(2))
            out.append(bytes([0x83]) + modrm(reg, kind) + imm(1))
            out.append(bytes([0xC1]) + modrm(reg, kind) + bytes([rnd.choice(SHIFT_COUNTS)]))
            out.append(bytes([0xD1]) + modrm(reg, kind))
            out.append(bytes([0xD0]) + modrm(reg, kind))
            out.append(bytes([0xD3]) + modrm(reg, kind))
            if reg >= 2 or kind == "r":
                out.append(bytes([0xF6]) + modrm(reg, kind) + (imm(1) if reg < 2 else b""))
            out.append(bytes([0xF7]) + modrm(reg, kind) + (imm(2) if reg < 2 else b""))
            if reg < 2:
                out.append(bytes([0xFF]) + modrm(reg, kind))
        for o in (0x84, 0x85, 0x86, 0x87, 0x8C, 0x8E):
            out.append(bytes([o]) + modrm(rnd.randrange(8), kind))
    out += [bytes([0x05]) + imm(2), bytes([0xA8]) + imm(1), bytes([0xA9]) + imm(2), b"\x92"]
    out += [bytes([0x70 + k, rnd.randrange(256)]) for k in range(16)]
    out += [bytes([0xE2, rnd.randrange(256)])]
    return [(c + bytes(rnd.randrange(256) for _ in range(6)))[:6] for c in out]


def regfile_vectors(families, seed: int = 71, per_code: int = 3, per_alu: int = 64,
                    mutate: int = 0) -> tuple[str, dict]:
    """The V35RF-2 vector file over the families' chains (see the section comment) and its
    counts (walk, random, modes, alu)."""
    import random

    from .funcref import CODE_SEGMENT, SREG
    from .normalize import load_runs, normalize
    rnd = random.Random(seed)
    base_mem = rnd.randbytes(1 << 20)
    lines, seen, codes = [], set(), {}
    counts = {"walk": 0, "random": 0, "modes": 0, "alu": 0}

    def add(line, kind):
        if line is not None and line not in seen:
            seen.add(line)
            lines.append(line)
            counts[kind] += 1

    chains = set()
    for f in families:
        for rec in load_runs(f):
            s = normalize(rec)
            ch = s.chain
            key = (bytes(ch.code), tuple(sorted(ch.regs.items())),
                   getattr(ch, "prelude_marker", None), s.chain_base)
            if key in chains:
                continue
            chains.add(key)
            for line, six, k in walk_vectors(ch, s.chain_base):
                add(line, "walk")
                codes.setdefault(six, k)
    for six in sorted(codes):
        for _ in range(per_code):
            add(_case(rnd, base_mem, six), "random")
    for head in EA_FORMS:
        for mod in range(3):
            for rm in range(8):
                for reg in range(8):
                    if head[0] in (0xC7, 0x8F, 0x81) and reg:
                        continue                # /0 forms
                    if head[0] == 0xFF and reg != 6 or head[0] == 0xF7 and reg not in (4, 6):
                        continue                # PUSH r/m, MULU / DIVU
                    tail = bytes(rnd.randrange(256) for _ in range(4))
                    six = (head + bytes([mod << 6 | reg << 3 | rm]) + tail)[:6]
                    add(_case(rnd, base_mem, six), "modes")
    for _ in range(per_alu):
        for six in alu_codes(rnd):
            operand = rnd.choice(EDGES) if rnd.random() < 0.5 else rnd.randrange(1 << 16)
            regs = _random_regs(rnd)
            for r in ("AW", "DW", "CW"):
                if rnd.random() < 0.4:
                    regs[r] = rnd.choice(EDGES)
            if rnd.random() < 0.5:
                regs["PS"] = CODE_SEGMENT
                regs.update({n: 0 for n in SREG if n != "PS"})
            add(_case(rnd, base_mem, six, regs, operand=operand), "alu")
    text = "\n".join(lines) + "\n"
    if mutate:
        text = "\n".join(_mutated(ln, mutate) for ln in lines) + "\n"
    return f"{RFFORMAT} {len(lines)}\n" + text, counts


def _mutated(line: str, mutate: int) -> str:
    f = line.split()
    f[18] = str(mutate)          # V, 14 register fields, code, pc, code_org, mutate
    return " ".join(f)


def run_rf_bench(text: str, keep: Path | None = None, name: str = "regfile") -> tuple[dict, str]:
    """(the bench's SUMMARY, its output) on a V35RF-2 vector file's text."""
    with tempfile.TemporaryDirectory() as tmp:
        d = keep if keep is not None else Path(tmp)
        path = d / f"{name}.rfvec"
        path.write_text(text)
        p = subprocess.run([str(RFBENCH), str(path)], capture_output=True, text=True, cwd=ROOT)
    sm = {}
    for line in p.stdout.splitlines():
        if line.startswith("SUMMARY"):
            sm = {k: int(v) for k, v in (x.split("=") for x in line.split()[1:])}
    if p.returncode not in (0, 1) or not sm:
        raise RuntimeError(f"bench exit {p.returncode}: {(p.stderr or p.stdout)[-300:]}")
    return sm, p.stdout


def check_regfile(families, keep: Path | None = None, mutate: int = 0) -> tuple[int, dict, str]:
    """(the bench's bad vectors, the counts, its output) of regfile_vectors on the bench."""
    text, counts = regfile_vectors(families, mutate=mutate)
    sm, out = run_rf_bench(text, keep)
    counts["vectors"] = sm["vectors"]
    return sm["bad"], counts, out


# D2: SingleStepTests through the unit bench (sst.py --rtl) ------------------------------------

def sst_file(args) -> tuple[str, dict, list]:
    """(stem, {class: tests}, [failure text]) of one SingleStepTests file on the unit bench:
    each test the RTL decodes, its prefixes and its instruction an instruction start each (the
    register file before from the functional reference's walk of the test), the reads served
    in the reference's order from the test's RAM, the expected register file, next IP and
    write data the suite's final state; the classes are sst.classify's and the reference's
    (a test the reference does not pass, or that touches the V35's on-chip page, is counted
    apart, not run)."""
    from . import funcref, sst
    stem, keep, show = args
    counts: dict = {}
    vecs, owner = [], []
    for test in sst.load(stem):
        c = sst.classify(test, stem, rtl=True)
        if c is not None:
            counts[c] = counts.get(c, 0) + 1
            continue
        fc, _, starts = sst.run_funcref(test)
        if fc not in ("pass", "trap"):
            counts[f"reference {fc}"] = counts.get(f"reference {fc}", 0) + 1
            continue
        if not all(rtl_decodes(st.code) for st in starts):
            counts["not decoded"] = counts.get("not decoded", 0) + 1
            continue
        want, wip, wram = sst.expected(test)
        init = {a: b for a, b in test["initial"]["ram"]}
        want["pfx"] = None
        kind = "trap" if fc == "trap" else "pass"
        if not func_ok(starts[-1].code):
            kind = "not functional (register form)"
        for i, st in enumerate(starts):
            last = i == len(starts) - 1
            if not last:
                after, nxt = starts[i + 1].regs, None
                vecs.append(rf_vector(st.regs, st.code, st.ip, 0, st, after))
            elif kind.startswith("not functional"):
                vecs.append(rf_vector(st.regs, st.code, st.ip, 0, None, None, bad=True))
            elif kind == "trap":
                vecs.append(rf_vector(st.regs, st.code, st.ip, 0, st, None, trap=True))
            else:
                wd = []
                for cy in st.cycles:
                    if cy.kind == "io_write":
                        wd.append(cy.data)      # the suite has no I/O data: the reference's
                    elif cy.kind == "write":
                        def byte(a, ln, cy=cy):
                            b = wram.get(a, init.get(a))
                            return (cy.data >> (8 * ln)) & 0xFF if b is None else b
                        a = cy.addr
                        wd.append(byte(a, 0) | (byte(a + 1, 1) << 8) if cy.width == "word"
                                  else byte(a, 0) if cy.width == "lo" else byte(a, 1) << 8)
                vecs.append(rf_vector(st.regs, st.code, st.ip, 0, st, want, nxt=wip, wdata=wd))
            owner.append((test["idx"], kind, test["name"]))
    sm, out = run_rf_bench(f"{RFFORMAT} {len(vecs)}\n" + "\n".join(vecs) + "\n", keep,
                           f"sst-{stem}")
    bad = {int(ln.split()[1]) for ln in out.splitlines() if ln.startswith("BAD ")}
    failed = {}
    for i, (idx, kind, name) in enumerate(owner):
        if i in bad:
            failed[idx] = (kind, name)
    results: dict = {}
    for idx, kind, name in owner:
        results[idx] = (kind, name)
    for idx, (kind, name) in results.items():
        k = f"rtl fail ({kind})" if idx in failed else kind
        counts[k] = counts.get(k, 0) + 1
    fails = [f"    {stem} #{idx} {name}" for idx, (kind, name) in list(failed.items())[:show]]
    fails += [ln for ln in out.splitlines() if ln.startswith("FAIL")][:show]
    return stem, counts, fails


def check_sst(stems, keep: Path | None = None, jobs: int = 8, show: int = 3) -> dict:
    """{stem: {class: tests}} of the unit bench over SingleStepTests files (sst_file)."""
    from multiprocessing import get_context
    if not RFBENCH.exists():
        raise SystemExit(f"error: {RFBENCH} is missing (fpga/v35s/build_rf_tb.sh)")
    if keep:
        keep.mkdir(parents=True, exist_ok=True)
    out = {}
    with get_context("spawn").Pool(max(1, min(jobs, 8))) as pool:
        for stem, counts, fails in pool.imap(sst_file, [(s, keep, show) for s in stems]):
            out[stem] = counts
            for line in fails:
                print(line)
            print(f"{stem:<5} " + "  ".join(f"{k} {v}" for k, v in sorted(counts.items())),
                  flush=True)
    return out


# The command ------------------------------------------------------------------------------

def _work(args):
    family, rec, keep, mode = args
    from .rtlgen import fit_config
    if mode == "biu":
        return family, check_run(rec, fit_config(), keep)
    if mode in ("eu", "joint3"):
        return family, check_eu_run(rec, fit_config(), keep, joint=mode == "joint3")
    if mode == "core":
        return family, check_core_run(rec, fit_config(), keep)
    return family, check_queue_run(rec, fit_config(), keep, joint=mode == "joint")


def _report_biu(f, rs, show) -> int:
    nm = [r for r in rs if r.not_modelled]
    rs = [r for r in rs if not r.not_modelled]
    ok = sum(r.ok for r in rs)
    cyc = sum(r.cycles for r in rs)
    ex = sum(r.exact_cycles for r in rs)
    dl = sum(r.deliveries for r in rs)
    clk = sum(r.clocks for r in rs)
    sig = sum(r.signal_bad for r in rs)
    st = sum(r.state_bad for r in rs)
    pin = sum(r.pin_bad for r in rs)
    me = sum(bool(r.model_exact) for r in rs)
    re_ = sum(bool(r.rtl_exact) for r in rs)
    rm = sum(bool(r.rtl_model_exact) for r in rs)
    print(f"{f:<5} {len(rs) + len(nm):>5} runs  {ok} exact against the model ({len(nm)} not "
          f"modelled)  cycles {ex}/{cyc} "
          f"deliveries {dl}/{cyc}  clocks {clk} (signal fails {sig}, state fails {st}, "
          f"pin fails {pin})  vs silicon: model-exact {me}, RTL-exact {re_}, "
          f"RTL = model {rm}")
    bad = [r for r in rs if not r.ok]
    for r in bad[:show]:
        print(f"    {r.run_id}: {r.error or r.first or 'cycles differ'} "
              f"(cycles {r.exact_cycles}/{r.cycles}, rtl {r.rtl_cycles})")
    return len(bad)


def _report_queue(f, rs, show, joint) -> int:
    nm = [r for r in rs if r.not_modelled]
    rs = [r for r in rs if not r.not_modelled]
    ok = sum(r.ok for r in rs)
    tot = {k: sum(getattr(r, k) for r in rs) for k in (
        "clocks", "ops", "state_bad", "rd_bad", "error_bad", "gate_bad", "signal_bad",
        "biu_state_bad", "cycles", "exact_cycles")}
    line = (f"{f:<5} {len(rs) + len(nm):>5} runs  {ok} exact against the model ({len(nm)} not "
            f"modelled)  clocks {tot['clocks']} "
            f"ops {tot['ops']} (state fails {tot['state_bad']}, read fails {tot['rd_bad']}, "
            f"storage errors {tot['error_bad']})")
    if joint:
        line += (f"  cycles {tot['exact_cycles']}/{tot['cycles']} (ungated fetches "
                 f"{tot['gate_bad']}, bus signal fails {tot['signal_bad']}, bus state fails "
                 f"{tot['biu_state_bad']})")
    print(line)
    bad = [r for r in rs if not r.ok]
    for r in bad[:show]:
        print(f"    {r.run_id}: {r.error or r.first or 'cycles differ'}")
    return len(bad)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m validation.v35s.chains.rtl_vectors",
                                description=__doc__.split("\n\n")[0])
    p.add_argument("--family", nargs="+", required=True)
    p.add_argument("--ids", nargs="+", help="keep run ids containing any of these")
    p.add_argument("--queue", action="store_true",
                   help="C2: the queue's bench (v35_queue.sv) instead of the bus unit's")
    p.add_argument("--joint", action="store_true",
                   help="C2: the queue and the bus unit together (the fetches the queue's)")
    p.add_argument("--eu", action="store_true",
                   help="C3: the decoder/EU bench (v35_eu.sv), its views the model's")
    p.add_argument("--joint3", action="store_true",
                   help="C3: the EU with the RTL queue and bus unit (the arbiter scripted)")
    p.add_argument("--core", action="store_true",
                   help="C4: the whole core (v35_chain_core.sv), the arbiter in RTL")
    p.add_argument("--regfile", action="store_true",
                   help="D1, D2: the register file's unit bench (v35_rf_tb.sv) on the families' "
                   "forms and every ALU form")
    p.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    p.add_argument("--keep", type=Path, help="keep the vector files and bench outputs here")
    p.add_argument("--show", type=int, default=5, help="failing runs to show per family")
    args = p.parse_args(argv)
    if args.regfile:
        if not RFBENCH.exists():
            print(f"error: {RFBENCH} is missing (fpga/v35s/build_rf_tb.sh)", file=sys.stderr)
            return 2
        if args.keep:
            args.keep.mkdir(parents=True, exist_ok=True)
        bad, counts, out = check_regfile(args.family, args.keep)
        for line in out.splitlines()[:args.show]:
            if line.startswith("FAIL"):
                print("    " + line)
        print(f"regfile {' '.join(args.family)}: {counts['vectors']} vectors (walk "
              f"{counts['walk']}, random {counts['random']}, modes {counts['modes']}, alu "
              f"{counts['alu']}), {bad} bad")
        return 1 if bad else 0
    mode = ("core" if args.core else "joint3" if args.joint3 else "eu" if args.eu
            else "joint" if args.joint else "queue" if args.queue else "biu")
    bench = {"biu": BENCH, "eu": EBENCH, "joint3": EBENCH, "core": CBENCH}.get(mode, QBENCH)
    if not bench.exists():
        script = {"biu": "build_biu_tb.sh", "eu": "build_eu_tb.sh",
                  "joint3": "build_eu_tb.sh", "core": "build_core_tb.sh"}.get(
                      mode, "build_queue_tb.sh")
        print(f"error: {bench} is missing (fpga/v35s/{script})", file=sys.stderr)
        return 2
    from multiprocessing import get_context

    from .normalize import load_runs
    if args.keep:
        args.keep.mkdir(parents=True, exist_ok=True)
    tasks = []
    for f in args.family:
        for rec in load_runs(f):
            rid = rec["chain"]["id"]
            if args.ids and not any(i in rid for i in args.ids):
                continue
            tasks.append((f, rec, args.keep, mode))
    results: dict = {f: [] for f in args.family}
    with get_context("spawn").Pool(max(1, min(args.jobs, 8))) as pool:
        for fam, res in pool.imap_unordered(_work, tasks, chunksize=4):
            results[fam].append(res)
    bad_total = 0
    for f in args.family:
        rs = sorted(results[f], key=lambda r: r.run_id)
        if mode == "biu":
            bad_total += _report_biu(f, rs, args.show)
        elif mode in ("eu", "joint3"):
            bad_total += _report_eu(f, rs, args.show, mode == "joint3")
        elif mode == "core":
            bad_total += _report_core(f, rs, args.show)
        else:
            bad_total += _report_queue(f, rs, args.show, mode == "joint")
    if len(args.family) > 1:
        allr = [r for f in args.family for r in results[f]]
        if mode in ("eu", "joint3"):
            _report_eu("all", allr, 0, mode == "joint3")
        elif mode == "core":
            _report_core("all", allr, 0)
        elif mode != "biu":
            _report_queue("all", allr, 0, mode == "joint")
    return 1 if bad_total else 0

if __name__ == "__main__":
    sys.exit(main())
