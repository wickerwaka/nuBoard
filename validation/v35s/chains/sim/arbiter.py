"""Arbiter: picks the next bus cycle when the bus is free.

An EU data request (`Request`) is posted with a setup count: it becomes
issuable after `setup` counted clocks (with a class `setup_free` of f, only
the last f of them have to be fetch-free; the rest count on every clock), counted after this clock's choice
(data_while_fetch=wait counts only clocks with no fetch in flight, including
one started this clock; queue counts every clock). hold_fetch: while
a request is posted, fetch requests do not go to the bus. With both an
issuable request and a fetch request on a free bus, `arbiter` decides:
data_wins; fetch_wins_le_q (fetch while queue bytes <= arbiter_q); fifo (the
earlier request); settled (data, except when the data request became issuable
and the fetch request was raised on this same clock: then the fetch); b2b
(as settled, and also right after a fetch whose last clock left the request
raised: the bus unit runs that fetch back to back, queue.py); b2b_run (as b2b,
and also a fetch requested on the delivery clock of the fetch that just ended). hold_run: a
posted request does not hold a fetch that starts on the clock right after a
fetch ended (the bus unit is still in its fetch run); after an idle clock or
a data cycle it does. The second half of an atomic odd-word pair always goes
next; with odd_split=separate it arbitrates like a new request.

I/O (fifth fit): an I/O request's setup counts per io_count (nowait: every
clock on which no memory cycle is in a wait state). Its class `lead` is the
last part of the setup: from the clock the hold lifts (the lead's first
clock) the bus unit has committed to the I/O; a fetch already requested
when the I/O was posted may run on that first clock, any other fetch waits
for the issue (io_hold). With io_hold=posted an I/O request holds fetches on
every clock after the one it was posted on whatever the queue holds, except
(posted_b2b) a fetch the bus unit committed to back to back. `not_before`
(port_latch) delays its issue. io_recover: a memory data request is not
issuable, and holds fetches like one in its setup, until io_recover clocks
after an I/O cycle's last clock. A halted EU raises no fetch.

Sixth fit: wlatch_hold: on a clock an I/O instruction waits at its start for
the data latch (eu.py), no fetch starts (True) or none while the queue holds
more than hold_q bytes (le_q). grp_free_bus: a group form's grp setup clocks
(templates.py) count on no clock of an I/O cycle or its recovery, and its
grp_free clocks only on an idle bus: the group's extra clocks run once the
request could otherwise issue.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Request:
    cycles: list                 # [(kind, addr, width)] still to issue
    setup: int
    posted: int
    atomic: bool = True
    count: int = 0
    issued: list = field(default_factory=list)   # Cycle objects
    done_at: int | None = None   # clock the EU may continue
    ready_since: int | None = None  # first clock the request was issuable at a choice
    free_need: int | None = None    # last setup clocks that must be fetch-free (None: all)
    lead: int = 0                   # last setup clocks during which the request no longer holds fetches
    nowait: bool = False            # io_count=nowait: setup counts every clock but a memory wait state
    not_before: int = 0             # no issue before this clock (port_latch relatch)
    sreg_held: bool = False         # (WP76) sreg_io=hold: a MOV sreg,r/m decoded behind it
    sreg: bool = False              # (WP76) sreg_store=own: MOV r/m,sreg's write
    sreg_ok: int | None = None      # (WP76) ... the first clock of its current issuable run
    sreg_at: int | None = None      # (WP76) sreg_io: the clock its setup first counted out
    lift_t: int | None = None       # first clock of the lead (the hold lifted)
    detached: bool = False          # io_release=post: the instruction that posted it has gone on
    port: bool = False              # an I/O request of a form with a port byte
    cls: str = ""                   # instruction class that posted it
    free_bus: bool = False          # grp_free_bus: the free clocks need an idle bus and no I/O recovery
    recover: int = 0                # io_recover (for free_bus)
    moved: bool = False             # (WP22) moved into the slot when the I/O ahead issued
    dw_moved: bool = False          # (WP25) a DW-form I/O request that moved in so
    free_held: int | None = None    # (WP29) free_hold: the clock a delivery-clock fetch was held
    grp_held: int | None = None     # (WP33) grp_io_hold: the last clock it held a fetch
    free_orig: int = 0              # (WP29) free_idle: the fetch-free clocks as posted
    floor_hold: bool = False        # (WP29) disp_floor=posted: floored after its post, its
                                    # floor extends its setup and holds fetches as the setup does
    whole: bool = False             # (WP20) pop_read_hold=queue: its hold compares the whole
                                    # queue with hold_q (hold_count=queue for this request)
    through: int = 0                # (WP30) rmw_alu=through: setup clocks that count with a
                                    # fetch in flight (an RMW write's ALU clocks)
    xeu: set | None = None          # (WP35) dw_view=eu: the setup clocks not counted, as the EU sees them
    grpcl: int = 0                  # (WP37) refresh_grpcl=step: a memory shift's read: its CL clocks
    io_stall: bool = False          # (WP58) refresh_io_stall=step: an I/O request
    eu_halted: bool = False         # (WP58) the EU is in HALT (arbitrate sets it every clock)
    beat_ext: int = 0               # (WP58) refresh_post=post_beat: the hold's clocks
    step_restart: str = "max"       # (WP85) io_step_restart (an I/O request, refresh on)
    lead_step: str = "block"        # (WP85) refresh_lead_step (an I/O request, refresh on)
    gdisp: bool = False             # (WP61) grp_disp=hold: a group RMW form's read after its
                                    # two-byte displacement
    dwlike: bool = False            # (WP70) str_count=dw: a string form's request, counted as a
                                    # DW-form I/O request's (nowait, dw_count)
    imm1: bool = False              # (WP43) imm1_first: the first data request of a memory form
                                    # with a one-byte immediate (83 /x, C6 /0)
    run_wait: bool = False          # (WP86) page_run: a committed fetch's wait clocks do not count
    pfree: int | None = None        # (WP81) page_mem=fixed: a 0F memory form's read, its setup
                                    # all fetch-free clocks since the end of the last fetch but
                                    # one committed back to back after the form's start (here)
    restart: bool = False           # (WP107) call_far_post=take: a fetch that runs in its
                                    # fetch-free clocks (free_run) restarts them after its end

    def page_free(self, bus, t: int) -> bool:
        """(WP81) page_mem=fixed: t counts toward the read's setup unless a fetch is on the bus
        that the bus unit did not commit back to back after the form's start (pfree); such a
        fetch restarts the count."""
        cur = bus.current
        if (cur is not None and cur.kind == "fetch" and cur.start <= t <= cur.end
                and not (cur.b2b and cur.start > self.pfree)):
            self.count = 0
            return False
        if (self.run_wait and cur is not None and cur.kind == "fetch" and cur.start <= t <= cur.end
                and bus.in_wait(t)):
            return False                # (WP86) page_run: a committed fetch's wait clocks
        return True

    def counts(self, fetch_inflight: bool, mode: str, bus=None, t: int | None = None) -> bool:
        """Whether this clock counts toward setup (data_while_fetch mode; io_count=nowait)."""
        if self.pfree is not None and bus is not None and t is not None:
            return self.page_free(bus, t)       # (WP81) page_mem / bf_read=fixed
        if self.nowait:
            if (self.io_stall and not self.eu_halted and bus is not None
                    and bus.current is not None and bus.current.kind == "refresh"
                    and t == bus.current.end and (self.setup - self.count - 1) % 2 == 0):
                return False            # (WP58) refresh_io_stall=step: nor its last clock when
                                        # that would end on one of the I/O's steps
            return bus is None or not bus.in_wait(t)
        need = self.setup if self.free_need is None else min(self.free_need, self.setup)
        if self.free_bus and bus is not None and t is not None:
            if self.gdisp:
                # (WP61) grp_disp=hold: its group clocks count through a fetch (an I/O cycle
                # and its recovery still stop them)
                return not ((bus.busy(t) and bus.current.kind.startswith("io"))
                            or t <= bus.last_io_end + self.recover)
            # a group form's clocks: none during an I/O cycle or its recovery; the free
            # ones on an idle bus only
            io = (bus.busy(t) and bus.current.kind.startswith("io")) or (
                t <= bus.last_io_end + self.recover)
            if io:
                return False
            if self.grpcl and bus.busy(t) and bus.current.kind == "refresh":
                # (WP37) refresh_grpcl: a refresh is not a fetch; one that started before
                # the post holds the EU at the post (the count starts after it)
                return bus.current.start >= self.posted
            return not bus.busy(t) or self.count < self.setup - need
        if mode == "queue" or not fetch_inflight:
            return True
        return self.count < max(self.setup - need, self.through)

    def ready(self) -> bool:
        return self.count >= self.setup

    def holding(self) -> bool:
        """Still in the part of its setup that holds fetches (hold_fetch)."""
        return self.count < self.setup - self.lead


def arbitrate(t: int, cfg, bus, queue, eu):
    """Start the next bus cycle at t, if any; count setup clocks of a waiting request.

    data_while_fetch=wait_before counts the clock before the choice (a fetch
    starting this clock does not stop the count); wait and queue count after it.
    """
    req = eu.req
    if req is not None:
        req.eu_halted = eu.halted       # (WP58) refresh_io_stall
    # halt_status: the clock HALT starts is the bus unit's (the halt status); no setup counts
    halting = (eu.halt_t == t or eu.halt_defer == t) and cfg.halt_status
    if (req is not None and req.pfree is not None and req.cycles and not req.issued
            and req.ready()):
        # (WP81) page_mem / bf_read=fixed: a fetch that runs before the ready read issues
        # restarts its count as well (the setup is counted after the last fetch's end)
        req.page_free(bus, t)
    base = req.count if req is not None else 0
    counted = False
    if (not halting and cfg.data_while_fetch == "wait_before" and req is not None and req.cycles
            and not req.issued and not req.ready()
            and req.counts(bus.fetch_inflight(t), "wait", bus, t)):
        req.count += 1
        counted = True
    c = _choose(t, cfg, bus, queue, eu)
    new = eu.req
    if (not halting and cfg.data_while_fetch == "wait_before" and new is not None
            and new is not req and new.cycles and not new.issued and not new.ready()
            and new.counts(False, "wait", bus, t)):
        new.count += 1          # handed the bus slot on this clock's choice: counts as posted before it
    if (not halting and cfg.data_while_fetch != "wait_before" and new is not None
            and new.cycles and not new.issued and not new.ready()):
        if new.counts(bus.fetch_inflight(t), cfg.data_while_fetch, bus, t):
            new.count += 1
    if (c is not None and cfg.disp_io == "extend" and c.kind.startswith("io")
            and queue.disp_t == t and getattr(eu, "mem", False) and getattr(eu, "disp", 0)):
        # (WP30) disp_io: the running form took its displacement on this I/O issue clock: the
        # bus unit holds the I/O a clock longer (nothing starts on the clock after its last,
        # its recovery counts from there)
        bus.last_io_end = bus.last_end = c.end + 1
    if c is not None and cfg.dw_count != "all":
        if c.kind == "fetch" and eu.start_clock == t:
            eu.fetch_start = t
        if (new is not None and new.cycles and (new.cycles[0][0].startswith("io") or new.dwlike)
                and not new.port and not new.issued and new.posted == t and new.count
                and (c.kind == "fetch" and eu.start_clock == t or cfg.dw_count == "bus")):
            new.count -= 1              # a DW form's first clock is taken by the cycle starting
        elif (cfg.dw_count_b2b and c.kind == "fetch" and new is req and new is not None
              and new.cycles and (new.cycles[0][0].startswith("io") or new.dwlike)
              and not new.port
              and not new.issued and new.posted < t and counted and not new.dw_moved
              and queue.b2b_at == t):
            new.count -= 1              # (WP26) dw_count_b2b: a back-to-back fetch starting
    if (cfg.dw_view == "eu" and eu.refresh is not None and new is not None and new.cycles
            and not new.issued
            and new.cycles[0][0].startswith("io") and new.nowait and new.posted <= t):
        _eu_view(t, bus, new, base if new is req else 0, halting)
    return c


def _eu_view(t: int, bus, r, base: int, halting: bool):
    """(WP35) dw_view=eu: refresh_sync=run's early fetch run is 2 clocks earlier for the EU, and
    so for the count of an I/O request it posted: a setup clock that a fetch of the run (its
    issue clock, a wait state) keeps from counting is the clock 2 earlier as the EU counts;
    one that falls before the post, or on a clock already not counted, costs nothing."""
    if r.xeu is None:
        r.xeu = set()
    if r.count > base or r.count >= r.setup:
        return                          # counted (or ready)
    cur = bus.current if bus.busy(t) else None
    run = (cur is not None and cur is bus.early and cur.kind == "fetch"
           and (cur.start == t or bus.in_wait(t)))
    if not run:
        r.xeu.add(t)
        return
    added = 0
    if halting:
        r.xeu.add(t)
        added += 1
    if t - 2 >= r.posted and t - 2 not in r.xeu:
        r.xeu.add(t - 2)
        added += 1
    r.count += 1 - added


def io_stepped(r, eu) -> bool:
    """(WP58) an I/O request still to issue, posted while the EU runs (not in HALT): the
    requests the I/O's steps (io_step) apply to."""
    return (r is not None and bool(r.cycles) and not r.issued
            and r.cycles[0][0].startswith("io") and not eu.halted)


def io_step(r, bus, t: int, issue: bool = False) -> bool:
    """(WP58) the I/O's steps: whether t is one of the clocks a posted I/O request's sequencer
    is at a step on, every second clock back from the issue its setup gives: from the clock
    setup - 5 after the post (four clocks before an unhindered issue: the third after a port
    form's post, the second after a DW form's), restarted on the clock after any bus cycle
    that ran during the setup (a fetch, a refresh); the post clock is one as well.
    refresh_io_step: a pending refresh starts only on a step; io_step_issue (issue): after a
    refresh in the setup, the instruction waiting for its I/O sees it issue only on a step."""
    p = r.posted
    if t == p and not issue:
        return True
    if issue and not any(c.kind == "refresh" and c.end >= p for c in bus.cycles[-3:]):
        return True                     # no refresh in the setup: the count alone
    s = p + max(0, r.setup - 5)
    for c in reversed(bus.cycles):
        if c.start < t and c.end >= p:
            # (WP85) io_step_restart=last: the restart whatever its clock
            s = max(s, c.end + 1) if r.step_restart == "max" else c.end + 1
            break
        if c.end < p:
            break
    return t >= s and (t - s) % 2 == 0


def _winner(t: int, cfg, bus, queue, req, fetch_want) -> str | None:
    """Which of an issuable data request and a fetch request _choose would start on t."""
    if req is not None and fetch_want:
        return "fetch" if _fetch_first(t, cfg, bus, queue, req) else "data"
    return "data" if req is not None else "fetch" if fetch_want else None


def _refresh(t: int, cfg, bus, queue, eu, req, fetch_want):
    """A refresh request is pending on a free bus: start the refresh cycle unless the cycle
    that would otherwise start goes first (refresh_data, refresh_fetch, refresh_b2b)."""
    w = _winner(t, cfg, bus, queue, req, fetch_want)
    if (cfg.refresh_halt == "status" and eu.halted and eu.halt_t is not None
            and t == eu.halt_t + 1 and eu.halt_defer is None):
        return None                      # (WP34) refresh_halt: the halt status's second clock
    r = eu.req
    step_lead = (cfg.refresh_step_lead == "step" and cfg.refresh_io_step == "own"
                 and cfg.refresh_lead == "closed" and r is not None and r.port and r.detached
                 and r.lead and r.count == r.setup - r.lead and fetch_want
                 and io_stepped(r, eu) and io_step(r, bus, t))
    if (cfg.refresh_lead == "closed" and r is not None and r.cycles and not r.issued
            and r.cycles[0][0].startswith("io") and r.lead
            and r.setup - r.lead <= r.count < r.setup
            and not (cfg.refresh_lead_port == "last" and r.port and r.count < r.setup - 1
                     and not fetch_want)
            and not step_lead
            and not (r.lead_step == "step" and r.detached and io_stepped(r, eu)
                     and io_step(r, bus, t))):  # (WP85) refresh_lead_step: a step takes it
        return None                      # (WP34) refresh_lead: committed to the I/O; (WP41)
                                         # refresh_lead_port: a port form's on its last clock only
                                         # (on its first unless an older fetch runs there)
    if (cfg.refresh_relatch == "issue" and r is not None and r.cycles and not r.issued
            and r.cycles[0][0].startswith("io") and r.ready() and t < r.not_before):
        return None                      # (WP61) refresh_relatch: on the relatched I/O's issue
    if (cfg.refresh_io_step in ("step", "own") and io_stepped(r, eu) and r.count < r.setup
            and not io_step(r, bus, t)):
        return None                      # (WP58) refresh_io_step: on the I/O's steps only
    if cfg.refresh_wlatch == "hold" and eu.latch_wait == t:
        return None                      # (WP41) refresh_wlatch: as a fetch, while the I/O form
                                         # waits at its start for the data latch
    # (WP58) refresh_io_step=own: beside an OUT (its request detached) the I/O's step takes the
    # refresh whatever the EU's own state (refresh_ok)
    if not (cfg.refresh_io_step == "own" and io_stepped(r, eu) and r.count < r.setup
            and r.detached) and not eu.refresh_ok(t, w):
        return None
    if step_lead:
        fetch_want = False               # (WP61) refresh_step_lead: the fetch is the lead's
    if w == "data" and cfg.refresh_data == "data":
        return None
    if w == "fetch" and (cfg.refresh_fetch == "fetch"
                         or cfg.refresh_b2b and queue.b2b_at == t):
        return None
    if (cfg.refresh_abort == "abort" and fetch_want and cfg.abort_fetch
            and queue.triple(t) and queue.room(t) == 2 and not queue.inflight):
        # (WP36) refresh_abort: the request the bus unit answers with an aborted cycle on a
        # free bus (abort_fetch: an instruction's start, operand take and IR load on one
        # clock, room for exactly a word) is aborted as there while the refresh runs
        queue.abort(t)
        queue.abort_ref = cfg.refresh_abort_retry == "next"   # (WP37) refresh_abort_retry
        queue.retry_loop = (cfg.abort_unit == "loop" and eu.start_clock == t
                            and (getattr(eu, "unit", False) and eu.cls in ("mul", "div")
                                 or eu.cls in ("shift_cl", "shift_imm") and not eu.mem
                                 or cfg.abort_reg and eu.cls in ("mul", "div")
                                 and not eu.mem))
        fetch_want = False
    if (fetch_want and cfg.refresh_drop_post == "hold" and r is not None and r.cycles
            and not r.issued and r.cycles[0][0].startswith("io") and r.posted == t
            and eu.start_clock < t and cfg.refresh_drop and queue.requested_at == t
            and queue.latched and queue.room(t) % 2):
        # (WP41) refresh_drop_post: on the clock an IN or OUT posts its I/O after its start, the
        # request refresh_drop would lose stays raised as one no younger than the I/O (the posted
        # I/O holds it to its lead's first clock), not a request the refresh beat
        fetch_want = False
    if (fetch_want and cfg.refresh_drop and queue.requested_at == t
            and (cfg.refresh_drop_on == "any" or queue.arrived_t == t)
            and (cfg.refresh_drop_on != "odd" or queue.latched and queue.room(t) % 2
                 or cfg.refresh_drop_unit == "unit" and queue.arrived_t == t
                 and queue.room(t) == 2 and eu.in_loop(t)
                 and t < eu.resume and eu.resume == eu.clk_end)):
        queue.flag = False               # the beaten request is dropped until the queue changes
        queue.requested_at = None
        queue.dropped = True             # (eu.py: a take sync counting it stops waiting)
        # (WP23) refresh_reraise=unit: only a count loop running when the request is lost
        # holds it to its exit; otherwise the queue raises it again on its next change
        queue.drop_hold = cfg.refresh_reraise != "unit" or eu.in_loop(t)
        if (cfg.refresh_drop_unit == "unit" and queue.drop_hold and eu.clk_tag == "exec"
                and t < eu.resume and eu.resume == eu.clk_end):
            # (WP38) refresh_drop_unit: lost in the shift's exec, before its count loop
            queue.drop_hold = False
        if cfg.refresh_lost == "start" and not queue.drop_hold:
            queue.lost_start = t             # (WP35) raised again on the next instruction start
    refresh = eu.refresh
    c = bus.start(t, "refresh", 0, "word", owner=refresh)
    # (WP34) refresh_sync=run: the beaten fetch is the one the EU's take sync counts
    bus.early_ok = (cfg.refresh_sync == "run" and fetch_want and not queue.dropped
                    and isinstance(eu.sync, int)
                    and eu.sync > queue.completed + queue.inflight)
    if fetch_want and not queue.dropped:
        queue.after_refresh = c.end + 1      # refresh_after=fetch_next
        queue.beat_eval = queue._evaluates(t)   # (WP40) refresh_reissue
        if not eu.halted:
            queue.refresh_beaten = True      # (WP23) halt_refresh
        elif cfg.halt_refresh == "run_drop":
            queue.refresh_beaten = False     # (WP34) beaten in HALT: the request is gone
            queue.after_refresh = None
    refresh.start(t, c.length)
    eu.refresh_beat = bool(fetch_want)       # (WP37) refresh_post: a fetch request beaten
    eu.refresh_cost(t, c.length)
    if cfg.refresh_halt == "status" and eu.halted and eu.halt_t == t:
        eu.halt_defer = c.end + 1            # (WP34) the halt status follows the refresh
    return c


def _beat_late(t: int, cfg, queue, eu) -> bool:
    """(WP61) refresh_beat_b2b: the decoder's state on the beaten fetch's delivery clock t (no
    IR load on t) that delays the fetch committed back to back: an operand take (take, imm);
    (imm) an immediate form (class imm, a register form with an immediate) running with operand
    bytes outstanding that did not start on t, or a form of another class starting on t right
    after one."""
    if queue.take_t == t:
        return True
    if cfg.refresh_beat_b2b != "imm":
        return False
    cls = getattr(eu, "cls", None)
    if eu.start_clock == t:
        return eu.prev_cls == "imm" and cls != "imm"
    return cls == "imm" and queue.decoder.need > 0


def _fetch_first(t: int, cfg, bus, queue, req) -> bool:
    """With an issuable data request and a fetch request on a free bus: the fetch first."""
    if cfg.arbiter == "fetch_wins_le_q":
        return queue.occupancy() <= cfg.arbiter_q
    if cfg.arbiter == "settled":
        return req.ready_since == t and queue.requested_at == t and not req.issued
    if cfg.arbiter == "b2b":
        if (cfg.imm1_first == "hold" and req.imm1 and queue.b2b_at != t
                and bus.last_fetch_end == t - 1 and not _fetch_run(bus, t)
                and queue.counted(t) > cfg.hold_q):
            # (WP43) imm1_first: a one-byte-immediate form's first data request, issuable on
            # the delivery clock of a fetch that was not a run's, goes before the fetch
            # requested there while the queue counts more than hold_q bytes (as its setup
            # held fetches)
            return False
        return not req.issued and (queue.b2b_at == t or (
            req.ready_since == t and queue.requested_at == t))
    if cfg.arbiter == "b2b_run":
        return not req.issued and (queue.b2b_at == t or (
            req.ready_since == t and queue.requested_at == t) or (
            queue.requested_at == t and bus.last_fetch_end == t - 1))
    if cfg.arbiter == "age":
        return (not req.issued and queue.requested_at is not None
                and queue.requested_at <= req.ready_since)
    if cfg.arbiter == "fifo":
        return queue.requested_at is not None and queue.requested_at < req.posted
    return False


def _fetch_run(bus, t: int, prev: bool = False) -> bool:
    """(WP29) the fetch that ended at t-1 started on the clock after an earlier fetch's last
    (prev: the fetch just started on t is not counted)."""
    cs = [c for c in bus.cycles[-4:-1] if c.kind != "refresh"] if prev else [
        c for c in bus.cycles[-3:] if c.kind != "refresh"]
    return (len(cs) >= 2 and cs[-1].kind == "fetch" and cs[-1].end == t - 1
            and cs[-2].kind == "fetch" and cs[-2].end == cs[-1].start - 1)


def _page_imm_run(t: int, cfg, bus, eu) -> bool:
    """(WP94) page_imm_run=delivery: a fetch issued on the clock after the last of a fetch that
    itself issued after a 0F memory form with an immediate bit index had taken its head (its
    ModR/M byte; the immediate waits for the read), the form's read not yet issued, runs inside
    the read's fetch-free setup as one the bus unit committed to back to back does
    (page_mem=fixed)."""
    if cfg.page_imm_run != "delivery" or not getattr(eu, "page_imm", False):
        return False
    if t <= eu.start_clock or bus.last_fetch_end != t - 1:
        return False
    prev = [c for c in bus.cycles[-3:] if c.kind == "fetch" and c.end == t - 1]
    take = eu.decoder.queue.take_t
    if not prev or prev[-1].start <= eu.start_clock or take is None or prev[-1].start <= take:
        return False                    # the fetch it follows issued before the form's head
                                        # (its ModR/M byte) was taken
    r = eu.req
    return eu.page_fixed == "start" or (r is not None and r.pfree is not None
                                        and not r.issued)


def _choose(t: int, cfg, bus, queue, eu):
    req = eu.req if eu.req is not None and eu.req.cycles else None
    if queue.lost_start is not None and eu.start_clock == t and t > queue.lost_start:
        # (WP35) refresh_lost=start: a request lost to a refresh outside a count loop is
        # evaluated again on the next instruction's start; HALT's start leaves it to the halt
        # status's two clocks, after which it goes as a request the refresh beat (ahead of
        # a posted I/O request and its hold, refresh_after=fetch_next)
        queue.lost_start = None
        if eu.halted and cfg.halt_status and eu.halt_t == t and eu.halt_defer is None:
            queue.lost_after = t + 2
        else:
            queue.lost_eval = t
    if queue.lost_after == t:
        queue.lost_after = None
        queue.lost_eval = queue.after_refresh = t
    fetch_want = queue.wants_fetch(t) and not eu.halted     # no prefetch in the HALT state
    if (eu.halted and queue.refresh_beaten and cfg.halt_refresh != "none"
            and queue.wants_fetch(t)):
        # (WP23) halt_refresh=run: the fetches a refresh held off the bus before HALT
        # started still run once it has ended, as the queue requests them
        fetch_want = True
    in_run = cfg.hold_run and bus.last_fetch_end == t - 1    # the bus unit is still fetching
    recovering = (req is not None and not req.issued and cfg.io_recover
                  and not req.cycles[0][0].startswith("io")
                  and t <= bus.last_io_end + cfg.io_recover)
    # (WP21) free_run: a posted memory request already counting its fetch-free setup clocks
    # does not hold a fetch first requested on this clock, the delivery clock of the fetch
    # just ended (the bus unit's fetch run); its remaining clocks count through that fetch
    free_run = (cfg.free_run != "none" and req is not None and not req.issued
                and req.cycles and not req.cycles[0][0].startswith("io")
                and (cfg.free_run != "pop" or req.cls in ("pop_mem", "pop"))
                and req.free_need is not None and req.count > req.setup - req.free_need
                and (bus.last_fetch_end == t - 1 or cfg.free_run in ("any", "held"))
                and (queue.requested_at in (None, t) or cfg.free_run == "held"))
    if free_run and fetch_want:
        if req.restart:
            # (WP107) call_far_post=take: the fetch runs, the fetch-free clocks start again
            # after it
            req.count = min(req.count, req.setup - req.free_need)
        else:
            req.free_need = 0
    if (cfg.free_hold == "delivery" and req is not None and not req.issued and fetch_want
            and req.cycles and not req.cycles[0][0].startswith("io")):
        if req.free_held == t - 1:
            # (WP29) the held fetch dates from the clock its hold ends: it runs, the request's
            # free clocks counting through it, or beats the request just become issuable
            queue.requested_at = t
            if req.free_need:
                req.free_need = 0
        elif (req.free_need and req.count == req.setup - req.free_need
              and bus.last_fetch_end == t - 1 and queue.requested_at == t
              and queue.b2b_at != t and not _fetch_run(bus, t)):
            fetch_want = False          # (WP29) free_hold: held at the free clocks' eve
            req.free_held = t
    if (cfg.grp_io_hold and req is not None and not req.issued and req.free_bus
            and req.free_need and req.count >= req.setup - req.free_need and fetch_want
            and not req.cycles[0][0].startswith("io")):
        # (WP33) grp_io_hold: the request's next setup clock is a bus-free group clock; while
        # an I/O cycle or its recovery keeps it from counting, a fetch requested on or after
        # that I/O's issue clock waits; the held fetch dates from the clock the hold ends
        cur = bus.current
        ios = [x for x in bus.cycles if x.kind.startswith("io")]
        if (((cur is not None and cur.kind.startswith("io") and cur.end >= t)
                or t <= bus.last_io_end + req.recover) and ios
                and queue.requested_at is not None and queue.requested_at >= ios[-1].start):
            fetch_want = False
            req.grp_held = t
        elif req.grp_held == t - 1:
            queue.requested_at = t
    if (cfg.slot_fetch == "slot" and req is not None and not req.issued and req.moved
            and fetch_want and req.free_need and not req.free_bus and not req.ready()
            and queue.requested_at is not None and queue.requested_at < req.posted):
        # (WP22) slot_fetch=slot: a request that moved into the slot when the I/O ahead issued
        # holds a fetch requested before that until its fetch-free clocks start, then lets it
        # run and counts through it
        if req.count <= req.setup - req.free_need:
            fetch_want = False
        else:
            req.free_need = 0
    if (fetch_want and queue.b2b_at != t and queue.gdisp_until is not None
            and t < queue.gdisp_until and (queue.take_t != t or queue.room(t) < 4)):
        # (WP61) grp_disp=hold: no fetch on the group RMW form's displacement take clock or the
        # grp_free clocks after it (one committed back to back goes; on the take clock itself
        # one with room for two words left by the take goes)
        fetch_want = False
    if (req is not None and req.gdisp and not req.issued and fetch_want and queue.b2b_at != t
            and req.count <= req.setup - req.free_orig
            and (queue.requested_at is None or queue.requested_at >= req.posted)):
        # (WP61) grp_disp=hold: a fetch no older than the read waits until the read's fetch-free
        # group clocks have begun to count
        fetch_want = False
    dec = queue.decoder
    if (cfg.ea_b2b and fetch_want and queue.b2b_at == t and getattr(eu, "mem", False)
            and getattr(eu, "disp", 0) and dec is not None and dec.ea_end is not None
            and t < dec.ea_end):
        fetch_want = False              # (WP33) ea_b2b: not on an EA clock before the take
    sreg_wait = False
    if req is not None and req.sreg and not req.issued:
        # (WP76) sreg_store=own: MOV r/m,sreg's write issues only after a clock on which it
        # was issuable but for a fetch on the bus (ready, past its floor and any I/O's
        # recovery), holding fetches on that clock: the segment register's datum reaches the
        # bus unit a clock after a general register's
        if (req.ready() and t >= req.not_before and not recovering
                and (bus.free(t) or bus.fetch_inflight(t))):
            if req.sreg_ok is None:
                req.sreg_ok = t
        else:
            req.sreg_ok = None
        sreg_wait = req.sreg_ok is None or req.sreg_ok == t
        if req.sreg_ok == t:
            fetch_want = False
    if (req is not None and cfg.hold_fetch and not req.issued
            and (req.holding() or recovering or req.floor_hold and t < req.not_before)
            and not in_run and not free_run):
        io = req.cycles[0][0].startswith("io")
        if io and cfg.io_hold == "posted_b2b" and queue.b2b_at == t:
            pass                        # a back-to-back fetch the bus unit committed to goes
        elif cfg.page_run != "none" and queue.b2b_at == t and eu.page_active():
            pass                        # (WP86) page_run: so does one beside a 0F memory form
        elif cfg.hold_fetch is True or (io and cfg.io_hold != "hold_fetch" and t > req.posted) or (
                queue.counted(t) - (eu.decoder.need if cfg.hold_count == "ahead"
                                    and not req.whole else 0)
                > cfg.hold_q and not (io and cfg.hold_fetch == "mem_le_q")):
            fetch_want = False
            if io and cfg.hold_fetch == "le_q_io":
                queue.requested_at = None  # held by an I/O request: it dates from its release
    if (cfg.wb_fetch == "hold" and fetch_want and eu.start_clock == t and eu.k < len(eu.steps)
            and eu.steps[eu.k][0] == "wbsync" and t < eu.wb_until and queue.b2b_at != t
            and queue.requested_at is not None
            and (queue.requested_at < t or queue.arrived_t == t)):
        # (WP81) wb_fetch=hold: a fetch requested before it (or on a word's delivery on it)
        # does not start on the clock a form that waits for the previous one's write-back
        # (wbsync: the port-form OUT) starts while that write-back runs; one the start itself
        # raised (the IR emptied) is not held
        fetch_want = False
    if queue.io_held is not None:
        if eu.start_clock > queue.io_held or not queue.flag or queue.inflight:
            queue.io_held = None        # (WP19) io_ir_hold: released by the next start
        else:
            fetch_want = False
    if (cfg.wlatch_hold and eu.latch_wait == t and fetch_want
            and (cfg.wlatch_hold is True or queue.counted(t) > cfg.hold_q)):
        fetch_want = False              # an I/O instruction waits for the write latch
    if req is not None and not req.issued and req.lead and not req.holding():
        # the lead: the bus unit has committed to the request. A fetch already waiting on
        # the clock the hold lifts runs first; later fetch requests wait for the issue.
        cur = bus.current
        if req.lift_t is None and not (cur is not None and cur.kind == "refresh"
                                       and cur.end >= t and cfg.refresh_lift == "free"):
            req.lift_t = t                  # (WP36) refresh_lift: not on a refresh's clock
        if (eu.halted and queue.refresh_beaten and cfg.halt_refresh != "none"
                and queue.b2b_at == t):
            pass                        # (WP23) halt_refresh=run: the committed run goes on
        elif queue.io_run_at == t:
            pass                        # (WP39) refresh_io_run: the committed fetch goes
        elif t != req.lift_t or (cfg.io_hold != "hold_fetch" and (
                queue.requested_at is None or queue.requested_at > req.posted
                or cfg.dw_lift == "moved" and req.dw_moved
                and queue.requested_at == req.posted)):
            fetch_want = False          # io_hold=posted: only a fetch no younger than the I/O
        elif req.dw_moved and eu.queued and queue.counted(t) > cfg.hold_q:
            # (WP25) dw_slot=behind: with another request posted behind it, the bus unit runs
            # the I/O first unless the queue holds hold_q bytes or fewer
            fetch_want = False
    if (queue.after_refresh == t and cfg.refresh_after == "fetch_next"
            and queue.wants_fetch(t) and (not eu.halted or cfg.halt_refresh != "none")
            and (req is None or req.issued or req.cycles[0][0].startswith("io"))):
        # (WP17) a fetch request a refresh beat goes on the clock after the refresh,
        # ahead of a posted I/O request and its hold (a memory data request keeps its turn)
        fetch_want = True
        if req is not None and not req.issued:
            req = None
    if (cfg.sreg_io == "hold" and req is not None and req.sreg_at is None and not req.issued
            and req.ready()):
        # (WP76) sreg_io=hold: a MOV sreg,r/m decoded behind the OUT before its I/O's setup
        # counted out holds the I/O one clock past that clock
        req.sreg_at = t
        if req.sreg_held:
            req.not_before = max(req.not_before, t + 1)
    if sreg_wait:
        req = None
    if req is not None and not req.issued and (not req.ready() or t < req.not_before):
        req = None
    # (WP58) io_step_issue: an IN's I/O after a refresh in its setup issues on one of its steps
    if (cfg.io_step_issue == "step" and io_stepped(req, eu) and not req.detached
            and not io_step(req, bus, t, issue=True)):
        req = None
    if recovering:
        req = None                      # I/O recovery: no data cycle right after an I/O cycle
    if req is not None and req.ready_since is None:
        req.ready_since = t
    if not bus.free(t):
        return None
    if req is not None and req.issued and req.atomic:
        return eu.issue(t, bus)              # second half of an odd-word pair
    refresh = eu.refresh
    if refresh is not None and refresh.pending is not None:
        c = _refresh(t, cfg, bus, queue, eu, req, fetch_want)
        if c is not None:
            return c
    if req is not None and fetch_want:
        if _fetch_first(t, cfg, bus, queue, req):
            req = None
    if req is not None:
        if req.cycles[0][0] == "nowrite":
            room, need = queue.room(t), 1
            if cfg.slot_room == "word":
                # (WP31) slot_room=word: room for a word, a word delivered on this clock not
                # counted (the bus unit chose the slot's cycle before it was written)
                room, need = room + (2 if queue.arrived_t == t else 0), 2
            slot_fetch = fetch_want or (cfg.grp_read == "rmw_slot_any" and not queue.inflight
                                        and not eu.halted and room >= need)
            return eu.issue_nowrite(t, bus, queue if slot_fetch else None)
        return eu.issue(t, bus)
    if queue.io_abort and not queue.inflight:
        # (WP22) io_take=abort: the request dropped under an I/O issue clock was the take's;
        # the bus unit answers it with an aborted cycle on its first free clock
        queue.io_abort = False
        retry, loop, at = queue.retry, queue.retry_loop, queue.abort_t
        queue.abort(t)
        queue.retry, queue.retry_loop, queue.abort_t = retry, loop, at
        return None
    latched_abort = (cfg.abort_latched and not fetch_want and cfg.abort_fetch
                     and queue.triple(t) and queue.latched and queue.arrived_t != t
                     and (cfg.abort_latched == "any" or queue.latch_full)
                     and not queue.inflight and queue.room(t) + queue.latched == 2
                     and not eu.halted)
    if (fetch_want and cfg.abort_fetch and queue.triple(t) and _one_word(queue.room(t), cfg, eu)
            or latched_abort):
        if latched_abort and isinstance(eu.sync, int) and eu.sync == queue.completed:
            # (WP32) abort_latched: the byte still latched behind the queue is room for the
            # abort test; the take's sync, which counted no request, waits for the cycle
            eu.sync = queue.completed + 1
        queue.abort(t)                       # aborted cycle: nothing on the bus
        # (WP72) xfer_abort=word: a transfer's aborted cycle (no data cycle follows to raise the
        # request again) has it raised again on the aborted cycle's end
        queue.xfer_abort = cfg.xfer_abort == "word" and getattr(eu, "cls", None) in TRANSFERS
        # (WP21) abort_unit=loop: a memory multiply or divide, or a register shift, started
        # on it raises the request again at its count loop's exit (eu.py), not when the
        # next bus cycle ends
        queue.retry_loop = (cfg.abort_unit == "loop" and eu.start_clock == t
                            and (getattr(eu, "unit", False) and eu.cls in ("mul", "div")
                                 or eu.cls in ("shift_cl", "shift_imm") and not eu.mem
                                 or cfg.abort_reg and eu.cls in ("mul", "div")
                                 and not eu.mem))
        return None
    if (fetch_want and eu.refresh is not None and cfg.refresh_beat_t4 == "t4" and queue.b2b_at != t
            and queue.arrived_t == t and queue.latched and queue.take_t != t and queue.ir_t != t
            and len(bus.cycles) >= 2 and bus.cycles[-1].kind == "fetch"
            and bus.cycles[-1].end == t - 1 and bus.cycles[-1].end - bus.cycles[-1].start == 2
            and bus.cycles[-2].kind == "refresh" and bus.cycles[-2].end == bus.cycles[-1].start - 1
            and queue.after_refresh == bus.cycles[-1].start):
        # (WP41) refresh_beat_t4: on the delivery clock of a 3-clock fetch a refresh beat the bus
        # unit is still in that fetch: the fetch requested there is committed and starts on t+1
        queue.t4_at = t + 1
        return None
    if (fetch_want and eu.refresh is not None and cfg.refresh_beat_b2b != "none"
            and queue.b2b_at == t and queue.arrived_t == t and queue.ir_t != t
            and len(bus.cycles) >= 2 and bus.cycles[-1].kind == "fetch"
            and bus.cycles[-1].end == t - 1 and bus.cycles[-1].end - bus.cycles[-1].start == 2
            and bus.cycles[-2].kind == "refresh" and bus.cycles[-2].end == bus.cycles[-1].start - 1
            and queue.after_refresh == bus.cycles[-1].start and _beat_late(t, cfg, queue, eu)):
        # (WP61) refresh_beat_b2b: the fetch committed back to back on a beaten 3-clock fetch's
        # last clock waits a clock when on its delivery clock the IR does not load and the
        # decoder is in one of _beat_late's states
        queue.t4_at = t + 1
        return None
    if fetch_want:
        r = eu.req
        mem = bool(r is not None and r.cycles and not r.issued
                   and not r.cycles[0][0].startswith("io"))
        fresh = queue.requested_at == t and bus.last_fetch_end == t - 1
        # (WP33) free_idle_b2b: a fetch the bus unit committed to back to back
        b2b = cfg.free_idle_b2b and queue.b2b_at == t
        if mem and r.beat_ext and queue.after_refresh == t:
            r.setup -= r.beat_ext           # (WP58) refresh_post=post_beat: the beaten fetch
            r.beat_ext = 0                  # runs first, the hold is the window's (as post)
        imm_run = _page_imm_run(t, cfg, bus, eu)   # (WP94) before this fetch is the last
        addr, width, data = queue.issue(t, mem_waiting=mem)   # (WP26) request_reissue
        c = bus.start(t, "fetch", addr, width, data, owner=queue)
        c.b2b = queue.b2b_at == t or imm_run  # (WP81) page_mem: committed back to back
        if eu.refresh is not None and cfg.refresh_sync == "run":
            # (WP34) refresh_sync=run: the beaten fetch the take sync counts, and the fetches
            # back to back behind it, run 2 clocks earlier for the EU (eu.early)
            prev = bus.early
            if queue.after_refresh == t and bus.early_ok:
                bus.early = c
                bus.early_n = 1              # (WP40) refresh_sync_run: the run's fetch count
            elif prev is not None and prev.end == t - 1:
                bus.early = c
                bus.early_n += 1
        if (cfg.free_idle and mem and r.free_orig and r.free_held != t - 1
                and r.count == r.setup - r.free_orig
                and (fresh and _fetch_run(bus, t, prev=True) or b2b)):
            # (WP29) free_idle: a fetch run's delivery-clock fetch took the request's
            # fetch-free clock: an idle clock after it, the request no earlier than the next;
            # (WP33) free_idle_b2b: as does a fetch committed back to back at that eve
            r.not_before = max(r.not_before, c.end + 2)
        return c
    return None


TRANSFERS = ("branch_short", "branch_near", "dbnz", "call", "ret")   # eu.TRANSFER_CLASSES


def _one_word(room: int, cfg, eu) -> bool:
    """abort_fetch: the request sees room for exactly one word: 2 bytes; (WP72) xfer_abort=word:
    on a transfer's start, displacement take and IR load, 2 or 3 bytes (the displacement byte,
    read by the bus unit's target adder on its take clock, is still counted)."""
    return room == 2 or (cfg.xfer_abort == "word" and room == 3
                         and getattr(eu, "cls", None) in TRANSFERS)
