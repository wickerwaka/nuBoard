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

    def __init__(self, machine, queue_rec=None, eu_rec=None):
        super().__init__()
        self.m = machine
        self.rec = queue_rec
        self.eu_rec = eu_rec        # (C3) the decoder/EU recorder, after the queue's
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
        return 0 if b.fetch_inflight(t) else min(7, t - b.last_fetch_end)

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
                v["data_in"] = d.data & 0xFFFF
                v["ddata"] = d.data & 0xFFFF
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

    @property
    def ok(self) -> bool:
        return (not self.error and self.cycles == self.rtl_cycles == self.exact_cycles
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
        "io_held_clr", "io_held_set", "t4", "nop_hold", "gdisp")
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
            if rec.depth == 0:
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
            if ev[1] != "abort_done":
                ck.c_snap = dsnap(m, t)
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
            return key in (("set", "starts"), ("set", "flush_held")) and key not in names
        if c in ("shift_end", "retry_end", "reraise"):
            return key in (("set", "shift_held"), ("set", "retry"), ("call", "room"),
                           ("set", "flag")) and key not in names and ("set", "flag") not in names
        if c == "issue":
            return key == ("set", "slot_fetch") and key not in names
        if c == "abort":
            return key in (("set", "abort_ref"), ("set", "retry_loop")) and key not in names
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

    @property
    def ok(self) -> bool:
        bad = (self.state_bad or self.rd_bad or self.error_bad or self.gate_bad
               or self.signal_bad or self.biu_state_bad)
        cyc = not self.joint or self.cycles == self.rtl_cycles == self.exact_cycles
        return not self.error and not bad and cyc and self.clocks > 0


def check_queue_run(rec: dict, cfg, keep: Path | None = None, joint: bool = False) -> QResult:
    from .normalize import normalize
    s = normalize(rec)
    res = QResult(s.run_id, joint)
    try:
        out = queue_vectors(s.chain, cfg, s.chain_base, biu=joint)
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
# read), and, per instruction start, the operands the register file gives (the effective
# address, the port, the stack addresses, the shift count, a transfer's target: Phase D's
# register file and EA adder; the RTL decodes the format from the instruction's bytes). A store
# or call from outside that is none of these raises (NotModelled), as does a refresh-on run
# (C5). What the EU and the decoder read from the queue between their ops is the queue's state
# before each op (the C2 representation), from the recording (--eu) or the RTL queue (--joint3);
# from the bus unit, its state before and after the arbiter's choice.

EBENCH = ROOT / "build" / "fpga" / "v35s" / "eu-tb" / "Vv35_eu_tb"
EFORMAT = "V35EU-1"
NQ = 16                      # the EU's queue ops per phase (T and L; P) (v35_eu.sv NQ)
NXOP = 4                     # the arbiter's touches on the EU per clock (v35_eu.sv NXOP)
JSLOT = 40                   # the joint bench's queue op chain: T, L, X and P ops
CLS_NONE = 63                # no instruction yet (eu.cls unset)

# the arbiter's touches on the EU (v35_eu.sv V35_XOP_*), in this order
XOPS = ("nop", "issue", "nowrite", "fetch_start", "sync_one", "free0", "not_before")

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
    ("k", 4),                # the step cursor
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
    ("sa_off", 4),           # start_at - t (POP PSW's clocks)
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
)
EFIELDS = (tuple((f"d_{n}", w) for n, w in DFIELDS) + tuple((f"e_{n}", w) for n, w in EUFIELDS)
           + tuple((f"r{i}_{n}", w) for i in (2, 1, 0) for n, w in RFIELDS))
ESTATE_W = sum(w for _, w in EFIELDS)
# the queue's state the EU and the decoder read (QFIELDS names, v35_eu.sv v35_qview_t)
QVIEW = ("count", "latched", "flag", "rq_valid", "rq_age", "inflight", "ab_valid", "ab_left",
         "ab_this", "retry", "retry_loop", "rt_valid", "rt_off", "shift_held", "sh_valid",
         "sh_off", "dropped", "drop_hold", "b2b_now", "arrived_now", "take_now", "take_prev",
         "ir_now", "latch_in_now")
# the bus unit's state the EU reads (before and after the arbiter's choice; v35_bview_t)
BVIEW = (("kind", 3), ("pos", 3), ("len", 3), ("free", 1), ("finf", 1), ("in_wait", 1),
         ("fprev", 1), ("wl", 1), ("fsince", 3), ("flen3", 1))
# an instruction's operand record (the register file's values; the RTL decodes the bytes)
OPFIELDS = ("offset", "code", "ea", "port", "sr", "sw", "count", "taken", "target", "fmt",
            "tmpl")


class NotModelled(RuntimeError):
    """A run the C3 bench does not cover (refresh on, a touch C4/C5 owns)."""


_FROZEN_DIR = str(Path(__file__).resolve().parent / "sim" / "frozen") + "/"
_TMPL_CACHE: dict = {}


def _templates(cfg):
    key = repr(cfg)                 # the fit's value (a Config is rebuilt per run)
    if key not in _TMPL_CACHE:
        from . import rtlgen
        order, sel, _ = rtlgen.templates(cfg)
        _TMPL_CACHE.clear()
        _TMPL_CACHE[key] = (order, sel, sorted(cfg.cost))
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

    def text(self) -> str:
        return (f"P {self.offset} {self.code.hex()} {self.ea} {self.port} {self.sr} {self.sw} "
                f"{self.count} {self.taken} {self.target} {self.fmt} {self.tmpl}")


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

    def __init__(self, m, qrec):
        if m.refresh is not None:
            raise NotModelled("refresh on (C5)")
        self.m, self.qrec = m, qrec
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
            return eu_base.complete(obj, c, t)

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

        def refused(name):
            def f(obj, *a, **k):
                raise NotModelled(f"eu.{name} (C5)")
            return f

        ns = {"__setattr__": eu_setattr, "tick": tick, "complete": complete, "issue": issue,
              "issue_nowrite": issue_nowrite, "_post": post,
              "refresh_cost": refused("refresh_cost")}
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
            if who == "req" and k in ("count", "ready_since", "lift_t", "free_held", "grp_held",
                                      "xeu", "eu_halted"):
                return                          # the arbiter's own (C4)
        raise NotModelled(f"{f} writes {who}.{k} = {v!r} in phase {self.phase} at {t}")

    def _req_set(self, r, k, v):
        f = _caller_file(3)
        if f in ("eu.py", "decoder.py"):
            return
        t, eu = self.t, self.m.eu
        if f == "arbiter.py" and self.phase == "X" and k in ("free_need", "not_before"):
            if r is not eu.req:
                raise NotModelled(f"the arbiter writes a queued request's {k} at {t}")
            if k == "free_need":
                if v != 0:
                    raise NotModelled(f"free_need = {v} at {t}")
                self.clock.xops.append(("free0", 0))
            else:
                self.clock.xops.append(("not_before", v - t))
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
        from . import rtlgen
        m = self.m
        cz = rtlgen.has_count(op) and op.count == 0
        key = tuple(rtlgen.fmt_of(op, self.cfg, cz, False)[n] for n, _ in rtlgen.FMT_FIELDS)
        if key not in self.sel:
            raise NotModelled(f"no template in the include for {op.cls} at {op.offset}")
        code = bytes(m.eu.code[op.offset:op.offset + 6]).ljust(6, b"\x90")
        s0, s1 = op.stack if op.stack else (None, None)
        r = OpRec(op.offset, code, op.ea or 0, op.port or 0, s0 or 0, s1 or 0, op.count,
                  int(op.target is not None), op.target or 0,
                  rtlgen.pack_fmt(key, self.classes), self.sel[key])
        self.opnds.append(r)
        self.cur = r


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
    since = 0 if b.fetch_inflight(t) else min(7, t - b.last_fetch_end)
    return (KINDS.index(cur.kind) if cur else 0, t - cur.start if cur else 0,
            cur.length if cur else 0, int(b.free(t)), int(b.fetch_inflight(t)),
            int(b.in_wait(t)), int(b.last_fetch_end == t - 1), int(t < m.eu.wlatch_until),
            since, int(b.length("fetch") == 3))


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
    s["e_sa_off"] = max(0, eu.start_at - t)
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
    s["e_tgt"] = op.target if op else 0
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
    for k, w in EFIELDS:
        v = s[k]
        if not 0 <= v < (1 << w):
            raise RuntimeError(f"{m.chain.id}: EU {k}={v} at {t} does not fit {w} bits")
    return s


def estate_text(s: dict) -> str:
    return " ".join(str(s[k]) for k, _ in EFIELDS)


def run_eu_model(chain, cfg, chain_base: int):
    """(Machine, _Log, QueueRecorder (unmerged), EURecorder, cycles, the queue's start): the
    frozen model as run_model builds it with the queue's, the decoder's and the EU's run
    recorded; its trace checked against run_record's."""
    from .sim.frozen import eu as feu
    from .sim.frozen import machine as fm
    from .types import refresh_any
    if refresh_any(chain):
        raise NotModelled("refresh on (C5)")
    m = fm.Machine(chain, cfg, chain_base, None, 0)
    init = (len(m.queue.bytes), [m.queue.byte_at(a) for a, _ in m.queue.bytes],
            m.queue.fetch_addr)
    qrec = QueueRecorder(m, merge=False)
    erec = EURecorder(m, qrec)
    log = _Log(m, qrec, erec)
    m.clock_log = log
    orig_arb, orig_exec = fm.arbitrate, feu.execute
    fm.arbitrate = lambda *a: erec.arbitrate(orig_arb, *a)

    def execute(op, code, regs):
        erec.started(op)
        return orig_exec(op, code, regs)
    feu.execute = execute
    try:
        cycles = m.run()
    finally:
        fm.arbitrate, feu.execute = orig_arb, orig_exec
    ref = fm.run_record(chain, cfg, chain_base, None, None, 0)["socket_trace"]
    if fm.trace_rows(cycles) != ref:
        raise RuntimeError(f"{chain.id}: the logged run differs from run_record's")
    return m, log, qrec, erec, cycles, init


def _bv_text(v: tuple) -> str:
    return " ".join(str(x) for x in v)


def eu_vectors(chain, cfg, chain_base: int, joint: bool = False):
    """(the EU bench's vector file, the model's cycles, the EU recorder; with joint also the
    queue's (unmerged, JSLOT ops) and the bus unit's vector files of the same run)."""
    run = run_eu_model(chain, cfg, chain_base)
    m, log, qrec, erec, cycles, init = run
    lines = [f"{EFORMAT} {chain.id} {len(erec.clocks)} {NQ} {NXOP} {len(erec.opnds)} "
             f"{m.queue.base}",
             "F " + " ".join(f"{k}:{w}" for k, w in EFIELDS),
             "Q " + " ".join(f"{k}:{dict(QFIELDS)[k]}" for k in QVIEW),
             "I " + estate_text(erec.init)]
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
        if c.owner is m.eu:
            lines.append(f"D {c.start} {KINDS.index(c.kind)} {c.addr} {BWIDTHS.index(c.width)}")
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
               or self.settle_bad)
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
              "q_rd_bad", "gate_bad", "signal_bad", "biu_state_bad", "settle_bad"):
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
        "exact_cycles", "starts")}
    me = sum(bool(r.model_exact) for r in run)
    re_ = sum(bool(r.rtl_exact) for r in run)
    rm = sum(bool(r.rtl_model_exact) for r in run)
    line = (f"{f:<5} {len(rs):>5} runs  {ok} exact against the model ({len(nm)} not modelled)  "
            f"clocks {tot['clocks']} starts {tot['starts']} ops {tot['ops']} (state fails "
            f"{tot['state_bad']}, op fails {tot['op_bad']}, RTL errors {tot['err_bad']}, data "
            f"cycle fails {tot['dcyc_bad']})  cycles {tot['exact_cycles']}/{tot['cycles']}")
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


# The command ------------------------------------------------------------------------------

def _work(args):
    family, rec, keep, mode = args
    from .sim.config import Config
    if mode == "biu":
        return family, check_run(rec, Config.fitted(), keep)
    if mode in ("eu", "joint3"):
        return family, check_eu_run(rec, Config.fitted(), keep, joint=mode == "joint3")
    return family, check_queue_run(rec, Config.fitted(), keep, joint=mode == "joint")


def _report_biu(f, rs, show) -> int:
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
    print(f"{f:<5} {len(rs):>5} runs  {ok} exact against the model  cycles {ex}/{cyc} "
          f"deliveries {dl}/{cyc}  clocks {clk} (signal fails {sig}, state fails {st}, "
          f"pin fails {pin})  vs silicon: model-exact {me}, RTL-exact {re_}, "
          f"RTL = model {rm}")
    bad = [r for r in rs if not r.ok]
    for r in bad[:show]:
        print(f"    {r.run_id}: {r.error or r.first or 'cycles differ'} "
              f"(cycles {r.exact_cycles}/{r.cycles}, rtl {r.rtl_cycles})")
    return len(bad)


def _report_queue(f, rs, show, joint) -> int:
    ok = sum(r.ok for r in rs)
    tot = {k: sum(getattr(r, k) for r in rs) for k in (
        "clocks", "ops", "state_bad", "rd_bad", "error_bad", "gate_bad", "signal_bad",
        "biu_state_bad", "cycles", "exact_cycles")}
    line = (f"{f:<5} {len(rs):>5} runs  {ok} exact against the model  clocks {tot['clocks']} "
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
    p.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    p.add_argument("--keep", type=Path, help="keep the vector files and bench outputs here")
    p.add_argument("--show", type=int, default=5, help="failing runs to show per family")
    args = p.parse_args(argv)
    mode = ("joint3" if args.joint3 else "eu" if args.eu else "joint" if args.joint
            else "queue" if args.queue else "biu")
    bench = {"biu": BENCH, "eu": EBENCH, "joint3": EBENCH}.get(mode, QBENCH)
    if not bench.exists():
        script = {"biu": "build_biu_tb.sh", "eu": "build_eu_tb.sh",
                  "joint3": "build_eu_tb.sh"}.get(mode, "build_queue_tb.sh")
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
        else:
            bad_total += _report_queue(f, rs, args.show, mode == "joint")
    if len(args.family) > 1:
        allr = [r for f in args.family for r in results[f]]
        if mode in ("eu", "joint3"):
            _report_eu("all", allr, 0, mode == "joint3")
        elif mode != "biu":
            _report_queue("all", allr, 0, mode == "joint")
    return 1 if bad_total else 0

if __name__ == "__main__":
    sys.exit(main())
