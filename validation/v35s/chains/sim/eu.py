"""Execution unit: runs one instruction's class template a micro-step per clock.

Instruction start: with opcode_take=prefetch the opcode comes from the
decoder's IR (no clock of its own); with opcode_take=start the first step is
an opcode take (one clock, or none with opcode_overlap=1). start_sync=inflight
holds the start while a fetch issued on an earlier clock is still on the bus.
A step of k clocks started at t occupies t..t+k-1; the next starts at t+k. A
take step stalls while bytes are missing; with take_sync=operand the step
after an operand take waits for a clock with no fetch in flight (take_sync=
operand), or until the fetches refilling the room the queue has on the clock
after the take have been delivered (take_sync=room), or until the fetches in
flight or requested on the take clock are delivered, sampled before
(take_sync=pending) or after (pending_end) that clock's bus choice; a request
counted that way that lapses (nothing in flight and no room for a word, which
no take can change while the EU waits) ends the wait. A data step
posts a Request to the arbiter and waits: a write until it has been issued
(continue the next clock), a read until its data is usable.

The bus unit has one request slot (`req`, what the arbiter sees). With
io_release=post an OUT posts its I/O into the slot and goes on (a detached
request): later requests queue behind it (`queued`) and move into the slot,
counting their setup from that clock, when it issues; the instruction that
posted one waits on its own request (`own`). While an OUT's I/O waits:
port_latch=relatch makes a port byte taken meanwhile hold that I/O until
relatch clocks after the take, and an IN/OUT whose port byte was taken then
waits for the latch (the end of that I/O cycle) before it posts its own;
io_interlock keeps register-only instructions from starting before the I/O
issues; imm_latch keeps data immediates from being taken before its cycle
ends. io_post=start counts an I/O request's setup from the instruction's
start (templates.py).

Data latch (sixth fit, wlatch): a datum occupies the bus unit's data latch for
wlatch clocks from the clock it enters it: a memory write from its issue, read
data (memory or I/O, wlatch_src=write_imm_read) from its delivery, the last
immediate byte of a form without a memory operand (wlatch_imm=reg) from its
take. An I/O instruction of wlatch_cls (port: the forms with a port byte) does
not start while it is busy; `latch_wait` tells the arbiter it is waiting
(wlatch_hold: it holds fetches meanwhile).
"""

from __future__ import annotations

from .arbiter import Request, io_step, io_stepped
from .templates import (BCD_CLASSES, BF_CLASSES, STRING_CLASSES, _dest_route, base_class, decode,
                        ea_class, execute, grp_class, refresh_hold_steps, steps)
from .queue import QUEUE_BYTES
from ..types import CODE_BASE

END_PORT = 0xFF00
SFR_PAGE = 0xFFF00          # (WP23) the on-chip SFR page (IDB FFh): no external bus cycle
SHIFT_CLASSES = ("shift_cl", "shift_imm")   # the shift unit's classes (refresh_eu)
# (WP55) the control-transfer classes (F23): branch_reg treats them as register-only forms
TRANSFER_CLASSES = ("branch_short", "branch_near", "dbnz", "call", "ret")
# (WP91, F37) the memory-indirect transfers: group forms (FF /2-/5) with a memory operand
XFER_MEM = ("call_mem", "br_mem", "call_far_mem", "branch_far_mem")
# io_interlock: register-only classes that do not start while an OUT's I/O waits in the slot
INTERLOCK = {"none": (), "reg": ("reg", "imm", "shift_imm", "shift_cl", "mul"),
             "reg_pfx": ("reg", "imm", "shift_imm", "shift_cl", "mul", "prefix")}


class EU:
    def __init__(self, cfg, code: bytes, chain_base: int, regs: dict, decoder, bus,
                 start_offset: int):
        self.cfg, self.code, self.base = cfg, code, chain_base
        self.regs = dict(regs)
        # (WP88, F35) the code offset (in PS) of code[0]: an absolute target (BR / CALL r16, far)
        # is a chain offset less it (templates.decode)
        self.regs["code_at"] = chain_base - CODE_BASE
        self.decoder, self.bus = decoder, bus
        self.pc = start_offset
        self.steps: list = []
        self.k = 0
        self.resume = 0                 # clock the current step may continue
        self.left = 0                   # bytes left in the current take step
        self.sync = None                # pending take_sync: None | 'operand' | 'room' | target
        self.req: Request | None = None   # the request in the bus unit's slot (the arbiter's)
        self.queued: list = []          # requests posted behind a detached one (io_release=post)
        self.own: Request | None = None   # the request the current instruction waits on
        self.retick = False             # a detached request was issued this clock
        self.since_start = 0            # io_post=start: countable clocks since this instruction started
        self.since_t = 0                # (WP38) refresh_io_pre: the count's first clock
        self.latch_until: float = 0     # an OUT's I/O holds the data and port latches until here
        self.taken = 0                  # operand bytes the current instruction has taken
        self.op_len, self.imm_bytes = 1, 0
        self.disp = 0
        self.halted = False
        self.route, self.ro = 0, False  # (WP19) dest_route clocks / a read-only class
        self.reg_latch_t = None         # (WP19) last clock a register form's byte filled the latch
        self.trace: list = []           # (clock, chain offset, class) of instruction starts
        self.origin = 0                 # (WP24) prelude_tail: code offset of the chain's first byte
        self.rmw_loop = 0               # (WP24) refresh_rmw_loop: the memory shift's loop clocks
        self.started = False            # first LS waits for a full queue (machine.py)
        self.start_at = -1              # (WP40) prelude_anchor=pop: no start before this clock
        self.pop_ref = None             # (WP40) pop_refresh=stall: the refresh already counted
        self.wb_until = 0               # previous instruction's write-back ends before this clock
        self.last_issued: list = []     # (WP76) str_split: the last data step's bus cycles
        self.str_rep = False            # (WP76) a REP string form is running
        self.sreg: str | None = None    # (WP76) the running form's Op.sreg
        self.lea_split = False          # (WP76) lea_disp: the running LDEA's d16 is split
        self.nw_t: int | None = None    # (WP76) str_io_setup: the nowait step's first clock
        self.nw_run: int | None = None  # (WP76) ... the wait clock it counted
        self.wb = 0                     # write-back tail of the instruction now running
        self.page_fixed = None          # (WP81) page_mem / bf_read=fixed: the read to post
        self.done_t: int | None = None  # clock the last instruction's steps ended
        self.modrm = False              # the instruction now running has a ModR/M byte
        self.latch_wait = None          # last clock an I/O instruction waited for the write latch
        self.wlatch_until = 0           # wlatch: the data latch is busy until here
        self.start_clock = -1           # clock the running instruction started
        self.fetch_start = None         # last clock a fetch was issued on an instruction's start
        self.halt_t = None              # clock HALT started (halt_status)
        self.halt_defer = None          # (WP34) refresh_halt: the halt status after a refresh
        self.refresh = None             # the refresh controller (machine.py; RFM FCh only)
        # (WP84) the controller an RFM store writes (machine.py): the same as refresh under
        # refresh_scope=any; under live it exists for every chain while refresh is set only
        # while the EU sees RFEN (Refresh.eu_on)
        self.rfc = None
        self.ls_shift = 0               # refresh_align=phase_eu: the first LS's exec offset
        self.clk_tag = None             # tag of the last clocks step begun ("loop": a count loop)
        self.clk_end = -1               # the clock that step ends before (its resume)
        self.stalled = 0                # refresh_eu: clocks refreshes have added to this instruction
        self.clk_start = -1             # refresh_eu=hold: the clock that clocks step started
        self.clk_seam = False           # it started on the previous clocks step's end clock
        self.hold_from = None           # refresh_eu=hold: a refresh started on this clock ...
        self.hold_end = None            # ... and ends on this one: the EU waits at a boundary
        self.left_nw = None             # (WP20) clocks left in a "nowait" step
        self.exec_t = None              # (WP22) unit_hold: first clock of the exec clocks
        self.hold_done = None           # (WP22) unit_hold: the cycle that already held it
        self.reg_early = False
        self.fixed = False              # (WP31) abort_fixed: a fixed-lookup group setup form
        self.seg_prefix = None          # (WP23) the segment prefix the next instruction carries
        self.sfr = None                 # (WP23) the running instruction's SFR store value
        self.port_t = None              # (WP32) port_issue: the last port take's clock ...
        self.port_held = []             # ... and the waiting I/O requests it relatched
        self.refill = False             # (WP55) refill_start: a flush's refill gates the next start
        self.prev_cls = None            # (WP61) refresh_beat_b2b: the class of the instruction before
        self.grp_form = False           # (WP61) grp_disp: the running form is a group opcode's
        self.gdisp_cls = False          # (WP91) ... and one grp_disp reads (eu._start)
        self.zfail = False              # (WP88) the running DBNZNE / DBNZE failed its Z test
        self.strings = {}               # (WP67, F24) {chain offset: (elements, cond)} of the
                                        # string forms, from the chain walk (machine.py)

    def _in_run(self, t: int) -> bool:
        """(WP92) lea_disp=run: on t a fetch is on the bus past its issue clock, or t is the
        clock after a fetch's last (its word's delivery): a take on t is inside a refill run."""
        cur = self.bus.current
        if cur is not None and cur.kind == "fetch" and cur.start < t <= cur.end:
            return True
        return self.bus.last_fetch_end == t - 1

    def _start(self, t: int) -> bool:
        cfg = self.cfg
        if self.start_at >= 0:
            cur = self.bus.cycles[-1] if self.bus.cycles else None
            if (cfg.pop_refresh == "stall" and cur is not None and cur.kind == "refresh"
                    and cur.start < t and cur.start < self.start_at
                    and cur is not self.pop_ref):
                # (WP40) pop_refresh=stall: a refresh started inside POP PSW's clocks after
                # its read stalls them by its length less 2, as a count loop's iteration
                self.pop_ref = cur
                self.start_at += cur.length - 2
            if t < self.start_at:
                return False             # (WP40) prelude_anchor=pop: POP PSW still runs
        if not self.started:
            q = self.decoder.queue
            if q.inflight or q.arrived_t == t or q.wants_fetch(t):
                return False             # quiescent: nothing in flight or landing (machine.py)
            self.started = True
        if self.refill:
            q = self.decoder.queue
            if cfg.refill_start == "full" and (q.inflight or q.arrived_t == t
                                               or q.wants_fetch(t)):
                return False             # (WP55) refill_start=full: the refill fills the queue
            if cfg.refill_start in ("full_d", "full_io") and (q.inflight or q.wants_fetch(t)):
                return False             # (WP55) full_d: ... and may start on the delivery clock
            if (cfg.refill_start == "full_io" and q.arrived_t == t
                    and self.bus.length("fetch") == 3 and self.decoder.ir is not None
                    and decode(self.code, self.pc, self.regs).cls in ("in", "out")):
                return False             # (WP55) full_io: an IN / OUT not on a 3-clock fetch's
            self.refill = False          # delivery clock
        if cfg.start_sync != "none" and self.bus.fetch_inflight(t) and not self._early(t):
            return False
        e = self.bus.early
        if (e is not None and cfg.refresh_sync == "run" and e.end == t - 1
                and self.decoder.queue.b2b_at == t):
            return False                 # (WP34) refresh_sync=run: the run's next fetch
        if cfg.start_sync == "b2b" and self.decoder.queue.b2b_at == t:
            return False                 # the bus unit is committed to a back-to-back fetch
        if self.lea_split and self.decoder.queue.b2b_at == t:
            return False                 # (WP76) lea_disp=split: after LDEA's split d16
        if cfg.opcode_take == "prefetch" and self.decoder.ir is None:
            return False
        op = decode(self.code, self.pc, self.regs)
        if (op.cls in STRING_CLASSES or op.cls in BCD_CLASSES) and op.offset - self.origin in self.strings:
            # (WP67, F24) the elements the walk runs (a compare's exit depends on the data);
            # (WP78, F32) a BCD string's byte pairs the same way
            op.n, op.cond = self.strings[op.offset - self.origin]
        if op.cl_count and cfg.shift_count_mask == "cl5":
            op.count &= 0x1F                 # (WP57) shift_count_mask: CL masked to 5 bits
        if (cfg.dest_route == "slot" and op.dbit == 0 and op.cls == "load_alu"
                and op.ea is not None):
            op.nowrite = True            # (WP19) CMP r/m,reg: the d = 0 template, no write
        if op.nowrite:
            op.cls = grp_class(op, cfg)      # grp_read: the group's read-modify-write class
        if op.cls != "prefix" and self.seg_prefix == 0x26 and op.ea is not None and op.cls in (
                "store", "store_imm"):
            lin = ((self.regs.get("DS1", 0) << 4) + op.ea) & 0xFFFFF
            if lin >= SFR_PAGE:
                # (WP23) DS1: MOV byte [0FFE1h],imm8 with DS1 = F000h: an on-chip SFR store
                op.ea = lin
                op.sfr = self.code[op.offset + op.length - 1]
        if cfg.start_sync == "b2b_modrm" and op.modrm and self.decoder.queue.b2b_at == t:
            return False                 # a ModR/M form waits out the back-to-back fetch
        if (op.modrm and self.bus.fetch_inflight(t) and self._early(t)
                and cfg.refresh_run_modrm == "wait"):
            return False                 # (WP40) refresh_run_modrm: a ModR/M form waits it out
        regonly = op.ea is None or (not op.bus and cfg.lea_form == "reg")   # (WP52) lea_form
        # (WP78) the structure a class shares with an existing one (templates.BASE_CLASS): every
        # rule that names a class sees bcls; the costs are op.cls's own (self.ccls)
        bcls = base_class(op.cls)
        if (cfg.io_interlock != "none" and self._interlocked(bcls, cfg.io_interlock)
                and regonly and self.req is not None and self.req.detached
                and self.req.cycles and self.req.cycles[0][0] == "io_write"):
            self._sreg_hold(op)          # (WP76) sreg_io=hold
            return False                 # the ALU passes the waiting OUT's data at its issue
        cur = self.bus.current
        if (cfg.io_busy_start == "issue" and self._interlocked(bcls, cfg.io_interlock)
                and regonly and cur is not None and cur.kind == "io_write"
                and cur.start < t <= cur.end):
            return False                 # (WP20) only on the OUT's issue clock, not after it
        # the instruction that just ended keeps writing back, from this start or (wb_from=end)
        # from the clock its last step ended
        end = self.done_t if cfg.wb_from == "end" and self.done_t is not None else t
        if cfg.dw_port == "hold" and op.cls in ("out", "in") and op.length > 1:
            # (WP25) a port form waits while a DW-form I/O request waits behind another I/O or
            # the cycle ahead of it is on the bus: the port latch is that I/O's until it ends
            dw = [r for r in [self.req] + self.queued if r is not None and r.cycles
                  and not r.issued and r.cycles[0][0].startswith("io") and not r.port]
            if dw and (any(r in self.queued for r in dw) or (
                    cur is not None and cur.kind.startswith("io") and cur.start <= t <= cur.end)):
                return False
        if (cfg.wlatch and op.cls in (("out",) if cfg.wlatch_cls == "out" else ("out", "in"))
                and (cfg.wlatch_cls != "port" or op.length > 1)):
            if t < self.wlatch_until:
                self.latch_wait = t      # the arbiter sees an I/O instruction waiting (wlatch_hold)
                return False             # the bus unit's data latch is still busy
        q = self.decoder.queue
        if (cfg.io_older and (op.cls in ("out", "in") and op.length > 1
                              or cfg.io_older == "io_modrm" and op.modrm)
                and q.requested_at is not None and q.requested_at < t and not q.inflight
                and self.bus.free(t) and q.stored() < cfg.io_b2b_q):
            return False                 # (WP29) io_older: it waits out the older fetch
        if (cfg.imm_start == "wait" and op.ea is not None and op.modrm and op.imm_bytes
                and self.bus.free(t) and not q.inflight and self.bus.last_fetch_end == t - 1
                and q.stored() <= cfg.io_b2b_q):
            # (WP30) imm_start: a memory form with an immediate due on a word's delivery clock
            # with io_b2b_q bytes or fewer stored, whose start (the IR it empties counted as
            # room) raises a fetch there, waits that fetch out
            d = self.decoder
            ir, d.ir = d.ir, None
            want = q.room(t) >= 2
            d.ir = ir
            if want:
                return False
        if (cfg.io_b2b and cfg.start_sync == "b2b_modrm" and not op.modrm
                and (cfg.io_b2b == "all" or op.cls in ("out", "in"))
                and self.decoder.queue.b2b_at == t
                and self.decoder.queue.stored() < cfg.io_b2b_q):
            return False                 # (WP26) io_b2b: a shallow queue, it waits out the fetch

        self.wb_until = end + self.wb
        self.done_t = None
        # (WP19) a memory operand form may have its own write-back (mwb), as its own mexec
        self.wb = cfg.c(op.cls, "mwb" if op.ea is not None and "mwb" in cfg.cost.get(op.cls, {})
                        else "wb")
        self.str_rep = op.cls in STRING_CLASSES and op.rep is not None   # (WP76)
        self.sreg = op.sreg             # (WP76) sreg_store
        self.zfail = op.zfail           # (WP88) DBNZNE / DBNZE not taken on the Z test
        # (WP76) lea_disp=split: LDEA with a two-byte displacement whose last byte is the even
        # (low) half of a word: its successor does not start on a back-to-back fetch's issue
        # (not one started on an I/O's issue clock: its EA clocks wait out the I/O, lea_io)
        cur = self.bus.current
        self.lea_split = (cfg.lea_disp in ("split", "run") and op.cls == "lea" and op.disp == 2
                          and not (self.decoder.queue.base + op.offset + op.length - 1) & 1
                          and not (cur is not None and cur.kind.startswith("io")
                                   and cur.start == t))
        self._sreg_hold(op)             # (WP76) sreg_io=hold
        if cfg.str_exit == "wb" and op.cls in STRING_CLASSES and op.rep is not None and op.n:
            # (WP76) str_exit=wb: a REP form's exit ends xwb clocks early, its last clocks a
            # write-back that only a form waiting for one (wbsync: the port-form OUT) sees
            self.wb = cfg.c(op.cls, "xwb")
        # (WP81) page_mem=fixed: a 0F memory form's read counts its setup back to its start
        # (WP81) bf_read=fixed: a bit field's first read counts its setup from its post
        self.page_fixed = ("start" if cfg.page_mem == "fixed" and bool(op.page)
                           and op.ea is not None and bcls in ("load_alu", "rmw")
                           else "post" if cfg.bf_read == "fixed" and op.cls in BF_CLASSES
                           else None)
        self.route = _dest_route(op, cfg)   # (WP19) dest_route clocks of this instruction
        # (WP86) page_run: a 0F memory form under page_mem=fixed (and with field a bit field under
        # bf_read=fixed); page_b2b: a 0F register form
        # (TEST1 / CLR1 / SET1 / NOT1 r, ROL4 / ROR4 r)
        self.page_run = (cfg.page_run != "none" and self.page_fixed == "start"
                         or cfg.page_run == "field" and self.page_fixed == "post")
        self.page_reg = (cfg.page_b2b == "reg" and bool(op.page) and op.ea is None
                         and bcls == "reg")
        self.ro = bcls in ("load", "load_alu")
        self.prev_cls = getattr(self, "cls", None)   # (WP61) refresh_beat_b2b
        self.cls = bcls
        self.ccls = op.cls              # (WP78) the class whose integers the EU reads
        self.grp_form = bool(op.group)   # (WP61) grp_disp: a group opcode's form
        # (WP61) grp_disp=hold reads a group RMW form's two-byte displacement; (WP91)
        # xfer_mem_disp=grp: the memory-indirect transfers' too (rmw alone under none)
        self.gdisp_cls = bcls == "rmw" or (cfg.xfer_mem_disp == "grp" and op.cls in XFER_MEM)
        # (WP21) a memory form whose operation runs after the read in a unit other than the
        # ALU (the shift unit, the multiplier/divider, the stack write of PUSH r/m)
        self.unit = op.ea is not None and (op.shift or bcls in ("mul", "div", "push_mem"))
        # (WP24) refresh_rmw_loop: a memory shift's count loop (its write's setup covers it)
        self.rmw_loop = 0
        if op.ea is not None and op.shift and op.cls == "rmw":
            loop = cfg.per_shift_count * (op.count - 1)
            # (WP24) refresh_rmw_loop: the count loop's clocks, or (all) the shift unit's
            # clocks from the ALU step on (alu + shift_imm.exec + the loop)
            self.rmw_loop = loop if cfg.refresh_rmw_span == "loop" else (
                cfg.c("rmw", "alu") + cfg.c("shift_imm", "exec") + loop)
            # (WP37) refresh_rmw_shape=shift: the shift unit's clocks to go at its first
            # (the ALU clocks before it carry no boundary)
            self.rmw_top = self.rmw_loop - (cfg.c("rmw", "alu") if cfg.refresh_rmw_span == "all"
                                            else 0) - 1
        # (WP37) refresh_grpcl: a memory shift by CL's grpcl clocks (shift_cl_mem=count)
        self.rmw_cl = (cfg.c("rmw", "grpcl") if op.ea is not None and op.shift
                       and op.cls == "rmw" and cfg.shift_cl_mem == "count"
                       and op.opcode in (0xD2, 0xD3) else 0)
        self.unit_early = False
        self.exec_t = None              # (WP22) unit_hold
        self.reg_early = False          # (WP22) abort_reg: the exec began on the aborted cycle
        self.shift_latched = False      # (WP21) count_latch: this shift holds the queue port
        self.modrm = op.modrm
        self.mem = op.ea is not None and not (not op.bus and cfg.lea_form == "reg")
        self.op_len, self.imm_bytes, self.taken = op.length, op.imm_bytes, 0
        self.disp = op.disp             # (WP27) displacement bytes (sync_req=disp)
        self.dfloor_at = None           # (WP28) disp_floor
        if (cfg.ea_floor and op.ea is not None and op.modrm and not op.disp
                and op.cls != "pop_mem" and cfg.disp_floor != "none" and cfg.c(op.cls, "dfloor")):
            # (WP29) ea_floor: a mod 00 form's address step is where a displacement would be
            # taken, pre + 1 + its EA clocks after the start, whatever the take sync waits
            # for; its first data cycle no earlier than dfloor clocks after that (s + 5)
            self.dfloor_at = (t + cfg.c(op.cls, "pre") + 1 + cfg.ea.get(ea_class(op, cfg), 0)
                              + cfg.c(op.cls, "dfloor"))
        # (WP25) imm_count=start: the first data request of a memory form with an immediate
        # issues no earlier than istart + its immediate bytes clocks after the start
        self.floor_n = (cfg.c(op.cls, "istart") + op.imm_bytes
                        if cfg.imm_count == "start" and op.ea is not None and op.imm_bytes
                        and "istart" in cfg.cost.get(op.cls, {}) else 0)
        # (WP31) abort_fixed: the group setup taken because no ALU-op field names the
        # operation (grp_ops=fixed: TEST 84/85, F6/F7 /0)
        self.fixed = cfg.grp_ops == "fixed" and op.fixed_alu and op.ea is not None
        if (self.floor_n and cfg.fixed_floor and op.group and op.fixed_alu
                and cfg.grp_ops == "fixed" and cfg.grp_fixed == "test"):
            # (WP31) fixed_floor: the fixed operation's lookup runs before the group decode
            # the floor counts (fgrp clocks)
            self.floor_n += cfg.c("load_alu", "fgrp")
        self.since_start = 0
        self.since_t = t                # (WP38) refresh_io_pre: the count's first clock
        self.start_clock = t            # dw_count: the clock this instruction started
        self.stalled = 0
        # io_post=start: the clocks before an I/O form's post (its pre, or pre0 without a port byte)
        self.io_pre = cfg.c(op.cls, "pre" if op.length > 1 else "pre0")
        self.decoder.start(op.length, t, cfg.c(op.cls, "nx"), modrm=op.modrm,
                           imm_reg=bool(op.imm_bytes) and op.ea is None,   # (WP26) modrm_mate
                           page=op.page,                                   # (WP78) the 0F page
                           # (WP78) nx0: a form without operand bytes holds the IR load nx0
                           # clocks from its start (a class integer; absent = 0, at once)
                           nx0=cfg.c(op.cls, "nx0") if op.length == 1 else 0)
        # (WP28) ir_load=disp_data: a ModR/M memory form with a displacement keeps its
        # successor's opcode in the queue until its first data cycle issues (machine.py
        # clears the hold on the issue clock, the displacement's take on a delivery clock)
        self.decoder.ir_hold = (cfg.ir_load == "disp_data" and op.ea is not None
                                and op.modrm and bool(op.disp) and op.bus
                                # (WP91) xfer_mem_ir=hold: a memory-indirect transfer's
                                # successor stays out of the IR until the pointer read issues,
                                # with or without a displacement
                                or cfg.xfer_mem_ir == "hold" and op.cls in XFER_MEM)
        # (WP92) lea_slot=ea: a displaced LDEA's EA clocks follow ea_ir_room (queue.room) as a
        # displaced memory form's do, though it holds no IR load (no data cycle to end it)
        self.decoder.lea_wait = (cfg.lea_slot == "ea" and op.cls == "lea" and bool(op.disp))
        self.decoder.queue.start_t = t
        self.decoder.queue.starts += 1
        lead = [] if cfg.opcode_take == "prefetch" else [("take", 1, "opcode")]
        sync_name = ("wbsync0" if op.length == 1 and "wbsync0" in cfg.cost.get(op.cls, {})
                     else "wbsync")      # (WP16) a form without operand bytes: wbsync0
        if cfg.c(op.cls, sync_name):
            lead = [("wbsync",)] + lead
        if cfg.mul_imm_hold == "word" and op.imm_bytes and op.ea is not None:
            # (WP81) mul_imm_hold: the immediate's last byte the even half of its word
            op.half_word = not (self.decoder.queue.base + op.offset + op.length - 1) & 1
        if cfg.ret_imm_hold == "word" and op.imm_bytes and bcls == "ret":
            # (WP88) ret_imm_hold: RET imm16's immediate ends on the even half of its word
            op.half_word = not (self.decoder.queue.base + op.offset + op.length - 1) & 1
        seq = steps(op, cfg)
        if self.refresh is not None and cfg.refresh_eu == "hold":
            seq = refresh_hold_steps(op, cfg, seq)   # read only with refresh on
        self.steps = lead + seq
        if op.target is not None and cfg.flush_hold == "start":
            # (WP55) flush_hold=start: no fetch request from hold clocks after a taken
            # transfer's start to its flush (queue.wants_fetch)
            self.decoder.queue.flush_held = t + cfg.c(op.cls, "hold")
        if (op.target is not None and cfg.xfer_odd == "idle"
                and bcls in ("branch_short", "dbnz")
                and (self.decoder.queue.base + op.offset) & 1):
            # (WP76) xfer_odd=idle: a taken short jump (branch_short, dbnz: a one-byte
            # displacement, no stack cycle) whose opcode is at an odd address (its displacement
            # the even half of the next word) raises no fetch request after its start clock
            # unless a fetch was on the bus on it
            q = self.decoder.queue
            q.odd_xfer, q.odd_fed = t, None
        q = self.decoder.queue
        if q.odd_nt:
            # (WP81) xfer_nt=odd: a not-taken short transfer's hold ends at its successor's start
            q.odd_xfer = q.odd_fed = None
            q.odd_nt = False
        if (op.target is None and cfg.xfer_nt == "odd" and bcls in ("branch_short", "dbnz")
                and (q.base + op.offset) & 1):
            # (WP81) xfer_nt=odd: a short transfer not taken whose opcode is at an odd address
            # holds its fetch request as xfer_odd=idle holds a taken one's, to its end; (WP88)
            # the base class's rule (BCWZ: DBNZ's)
            q.odd_xfer, q.odd_fed, q.odd_nt, q.odd_until = t, None, bcls, None
        execute(op, self.code, self.regs)
        self.k = 0
        self.trace.append((t, op.offset - self.origin, op.cls))
        self.pc += op.length
        self.seg_prefix = op.opcode if op.cls == "prefix" else None
        self.sfr = op.sfr
        return True

    def _sreg_hold(self, op):
        """(WP76) sreg_io=hold: a MOV sreg,r/m (8E, Op.sreg "load") decoded (started, or
        waiting at the I/O interlock) while an OUT's I/O waits in the slot holds that I/O one
        clock past the clock its setup counts out (arbiter.py)."""
        r = self.req
        if (self.cfg.sreg_io == "hold" and op.sreg == "load" and r is not None and r.detached
                and r.cycles and not r.issued and r.cycles[0][0] == "io_write"
                and not r.sreg_held):
            r.sreg_held = True

    def _run_wait(self, t: int) -> bool:
        """(WP76) str_io_setup=run: a REP I/O string form's (str_in, str_out) nowait setup
        counts the first wait clock of a fetch that issued on the setup's first clock back to
        back after another fetch (the post-marker refill still running back to back)."""
        if (self.cfg.str_io_setup != "run" or self.cls not in ("str_in", "str_out")
                or self.nw_run is not None):
            return False
        cur, cyc = self.bus.current, self.bus.cycles
        if (cur is None or cur.kind != "fetch" or cur.start != self.nw_t or len(cyc) < 2
                or cyc[-1] is not cur or cyc[-2].kind != "fetch" or cyc[-2].end + 1 != cur.start):
            return False
        self.nw_run = t
        return True

    def _interlocked(self, cls: str, mode: str) -> bool:
        """cls is one of the register-only classes of mode (INTERLOCK); (WP22) reg_div: the
        register divide is one of them as the register multiply is."""
        if cls in INTERLOCK[mode]:
            return True
        if cls == "lea" and mode != "none" and self.cfg.lea_form == "reg":
            return True                 # (WP52) lea_form=reg: LDEA is a register-only form
        if (cls in TRANSFER_CLASSES and mode != "none" and self.cfg.branch_reg == "reg"):
            return True                 # (WP55) branch_reg=reg: a transfer is a register-only form
        return cls == "div" and mode != "none" and self.cfg.reg_div

    def _unit_hold(self, t: int) -> bool:
        """(WP22) unit_hold: a register shift, multiply or divide in its exec clocks waits at
        a micro-boundary (every second exec clock from the class's hphase-th) while a fetch,
        or an aborted fetch cycle, is past its second clock, until the clock after that
        cycle's last; the clocks still to run move on with it."""
        n = t - self.exec_t - self.cfg.c(self.ccls, "hphase")
        if n < 0 or n % 2:
            return False
        q = self.decoder.queue
        cur = self.bus.current
        end = None
        if cur is not None and cur.kind == "fetch" and cur.start + 2 <= t <= cur.end:
            end, key = cur.end, cur
        elif q.abort_end is not None and q.abort_end == t:
            end, key = q.abort_end, ("abort", q.abort_end)
        if end is None or key is self.hold_done or key == self.hold_done:
            return False
        self.hold_done = key
        self.resume += end + 1 - t
        if self.clk_end is not None and self.clk_end == self.resume - (end + 1 - t):
            self.clk_end = self.resume
        return True

    def _io_drop(self, t: int, q) -> bool:
        """(WP22) io_take: the instruction started on this clock, the issue clock of an I/O
        cycle, and took its last operand byte here, a register-only form, on a word's
        delivery clock with the word's second byte latched: the fetch request this clock
        raises is dropped as an aborted cycle's is, and raised again as abort_fetch=retry
        and abort_unit=loop raise it (a count loop's form at its loop's exit)."""
        cfg = self.cfg
        if cfg.io_take == "none" or self.decoder.need or not self.taken:
            return False
        if self.mem and not (cfg.io_take == "unit" and self.unit
                             and self.cls in ("mul", "div")):
            return False
        cur = self.bus.current
        if not (self.start_clock == t and cur is not None and cur.kind.startswith("io")
                and cur.start == t and q.arrived_t == t and q.latched
                and self._interlocked(self.cls, "reg")):
            return False
        loop = self.cls in ("shift_cl", "shift_imm", "mul", "div")
        q.flag = False
        q.requested_at = None
        q.retry = True
        q.retry_loop = loop and cfg.abort_unit == "loop"
        q.abort_t = t
        if cfg.io_take == "abort" and self.reg_latch_t != t and not self.mem:
            q.io_abort = True       # the take's own request: an aborted cycle once the bus frees
        return True

    def ir_waits_latch(self, t: int) -> bool:
        """(WP19) wlatch_ir: the opcode in the IR is an I/O form the busy data latch will hold
        at its start (wlatch_cls), so the bus unit is already reserved for it."""
        d = self.decoder
        if not (self.cfg.wlatch_ir and self.cfg.wlatch and d.ir is not None
                and t < self.wlatch_until and self.reg_latch_t is not None
                and self.reg_latch_t >= self.start_clock):
            return False                # only a latch the running register form filled
        if self.cfg.wlatch_ir_at == "start":
            # (WP24) the latch must still be busy when the I/O form in the IR can start: at
            # the end of the running form's own clocks still to run
            left = sum(st[1] for st in self.steps[self.k:] if st[0] == "clocks")
            if t + left >= self.wlatch_until:
                return False
        o = self.code[d.ir - self.base] if 0 <= d.ir - self.base < len(self.code) else 0x90
        cls = self.cfg.wlatch_cls
        return (o in (0xE6, 0xE7) or cls != "out" and o in (0xE4, 0xE5)
                or cls == "io" and o in (0xEC, 0xED, 0xEE, 0xEF))

    def tick(self, t: int):
        q = self.decoder.queue
        if q.shift_until is not None and q.shift_until <= t:
            q.shift_until = None            # (WP21) count_latch: the shift's last clock
            q.shift_held = False
            q.flag = q.room(t) >= 2         # the request is evaluated again
        if q.retry_at is not None and q.retry_at <= t:
            q.retry_at = None               # (WP21) abort_unit=loop: the count loop's exit
            if q.retry:
                q.retry = False
                q.flag = q.room(t) >= 2
        if self.hold_end is not None:
            if t > self.hold_end:
                self.hold_end = None
            elif t > self.hold_from and self.boundary(t, before=True):
                # refresh_eu=hold: the EU does not pass a micro-boundary while a refresh
                # it let through is on the bus; what would happen on t moves one clock on
                if t < self.resume and self.resume == self.clk_end:
                    self.clk_end = self.resume = self.resume + 1
                    if (self.cfg.refresh_retry == "end" and q.retry_at is not None
                            and q.retry_at > t and self.k == len(self.steps)):
                        q.retry_at += 1      # (WP36) refresh_retry: the end moved, the retry too
                else:
                    if (self.cfg.refresh_wb != "hold" and self.k >= len(self.steps)
                            and self.done_t is None and t >= self.resume):
                        self.done_t = t         # (WP61) refresh_wb: the steps ended on t
                    self.resume = t + 1
                self.stalled += 1
                return
        if (q.dropped and q.drop_hold and self.cfg.refresh_reraise == "unit"
                and t < self.resume and self.resume == self.clk_end):
            # (WP23) refresh_reraise=unit: the count loop raises the request a refresh took
            # from it as its last iteration starts (a multiply: mtail before its end)
            # reraise_off: clocks from the loop's end (its exit's first clock) to the clock
            # the request rises (-per_shift_count: as its last iteration starts)
            off = self.cfg.reraise_off
            if self.clk_tag in ("loop_odd", "mexit"):
                off = -self.cfg.c(self.ccls, "mtail")
            if (self.clk_tag in ("loop", "loop_odd", "mexit") and off < 0 and self.resume - t == -off
                    and (self.clk_tag != "loop_odd" or self.k == len(self.steps))
                    or self.clk_tag == "tail" and off >= 0 and t - self.clk_start >= off):
                q.dropped = False
                q.flag = q.room(t) >= 2
        if self.exec_t is not None and t < self.resume and self._unit_hold(t):
            return
        if (self.refresh is not None and self.cfg.shift_exit0 == "exit"
                and self.exec_t is not None and t == self.resume and self.resume == self.clk_end
                and self.k < len(self.steps) and self.steps[self.k][0] == "clocks"
                and len(self.steps[self.k]) > 2 and self.steps[self.k][2] in ("loop", "tail", "mexit")
                and self._unit_hold(t)):
            # (WP36) shift_exit0: the refresh template's split moves no hold point: unit_hold's
            # exec clocks are counted through a seam between its split steps as inside them
            return
        while not self.halted:
            if t < self.resume:
                return
            if self.k >= len(self.steps) and self.done_t is None:
                self.done_t = t                 # the running instruction's steps are done
                q = self.decoder.queue
                if q.odd_nt and self.cfg.xfer_nt == "odd":
                    q.odd_xfer = q.odd_fed = None   # (WP81) xfer_nt: the hold ends with it
                    q.odd_nt = False
            if self.k >= len(self.steps) and not self._start(t):
                return
            if self.sync == "operand" and self.bus.fetch_inflight(t):
                return
            if self.sync == "quiet" and (self.bus.fetch_inflight(t)
                                         or self.decoder.queue.wants_fetch(t)):
                return
            if self.sync == "defer":            # imm_landed: the fetches pending on the
                q = self.decoder.queue          # clock after the take
                self.sync = q.completed + q.inflight + int(q.asked(t))
            if self.sync == "room":             # measured on the clock after the take
                self.sync = self.decoder.queue.refill_target()
            if (isinstance(self.sync, int) and self.str_rep and self.cfg.str_start == "skip"
                    and self.decoder.queue.abort_end is not None
                    and self.decoder.queue.abort_t == self.start_clock
                    and t >= self.decoder.queue.abort_end):
                # (WP76) str_start=skip: a REP form's take sync is met on the last clock of the
                # aborted cycle that answered the request of its start clock (no word comes)
                self.sync = None
            if isinstance(self.sync, int) and self.decoder.queue.completed < self.sync:
                q = self.decoder.queue
                if q.completed + 1 == self.sync and self._early(t) and not (
                        self.cfg.refresh_sync_run == "two" and self.bus.early_n > 2) and not (
                        self.cfg.refresh_sync_reg == "delivery" and self.cls == "reg"):
                    # (WP40) refresh_sync_run=two: only on the beaten fetch and the one after
                    # it; refresh_sync_reg=delivery: not for a register form (class reg)
                    self.sync = None            # (WP34) refresh_sync=run: met 2 clocks early
                elif not q.inflight and q.abort_end is None and (
                        q.room(t) < 2 or q.dropped or self.ir_waits_latch(t)):
                    # the request the sync counted has lapsed (no room for a word, nothing
                    # in flight): with the EU waiting, no take can make room again
                    self.sync = None
                elif (self.cfg.abort_reg and q.abort_end == t and q.abort_t == self.start_clock
                      and not self.mem and self.cls in ("shift_imm", "mul", "div")
                      and self.sync == q.completed + 1):
                    # (WP22) abort_reg: a register shift, multiply or divide started on an
                    # aborted cycle runs its exec from that cycle's last clock
                    self.sync = None
                    self.reg_early = True
                else:
                    return
            if (isinstance(self.sync, int) and self.cfg.prepare_sync == "run"
                    and self.cls == "prepare" and self.decoder.queue.b2b_at == t):
                # (WP72) prepare_sync=run: the fetch committed back to back on the last clock
                # of the one PREPARE's take sync waited for is waited for too (the run)
                self.sync += 1
                return
            self.sync = None
            step = self.steps[self.k]
            kind = step[0]
            if kind == "clocks":
                cur = self.bus.current
                if (self.cfg.io_exec != "any" and step[1] and self.taken and self.mem is False
                        and (self.cfg.io_exec == "all" or self.decoder.need == 0)
                        and self._interlocked(self.cls, "reg_pfx") and cur is not None
                        and cur.kind.startswith("io") and cur.start == self.start_clock
                        and t <= cur.end):
                    # (WP21) io_exec: a register form started on an I/O cycle's issue clock
                    # runs its clocks after its operand take only once the cycle has ended
                    self.resume = cur.end + 1
                    if self.cls == "lea" and self.cfg.lea_io == "recover":
                        # (WP72) lea_io=recover: LDEA's EA clocks (its operation) use the bus
                        # unit's address adder, which the I/O cycle holds through its
                        # recovery: they run from io_recover clocks after its last
                        self.resume += self.cfg.io_recover
                    return
                self.k += 1
                if (step[1] and self.exec_t is None and self.cfg.unit_hold and not self.mem
                        and self.taken and self.decoder.need == 0
                        and self.cls in ("shift_imm", "shift_cl", "mul", "div")):
                    self.exec_t = t             # (WP22) unit_hold: the exec's first clock
                if step[1] and self.taken and self.decoder.queue.odd_nt:
                    q = self.decoder.queue
                    if q.odd_until is None:
                        # (WP81) xfer_nt=odd: the hold ends nhold clocks into the clocks after
                        # the transfer's operand take (BNE / BE: the flag test; DBNZ: CW's)
                        # (WP88) dbnz_z: not taken on the count (its Z test passed), chold
                        name = ("chold" if self.ccls == "dbnz_z" and not self.zfail
                                else "nhold")
                        q.odd_until = t + self.cfg.c(self.ccls, name)
                if step[1]:
                    if self.refresh is not None:
                        # refresh_eu=hold: a clocks step following another clocks step of
                        # the instruction on its end clock starts without a micro-boundary
                        prev = self.steps[self.k - 2][0] if self.k >= 2 else None
                        self.clk_seam = (prev == "clocks" and self.clk_end == t
                                         and self.clk_start <= t
                                         # refresh_clk_start=after_wait: also straight after
                                         # a take (no wait between)
                                         or prev == "take" and self.cfg.refresh_clk_start
                                         == "after_wait" and self.decoder.queue.take_t is not None
                                         and self.decoder.queue.take_t >= t - 1
                                         and not (self.cfg.refresh_start_seam == "start"
                                                  and t == self.start_clock))
                        self.clk_start = t
                    self.resume = t + step[1]
                    if len(step) > 2 and step[2] == "ea" and self.disp and (
                            self.mem or self.decoder.lea_wait):
                        self.decoder.ea_end = self.resume   # (WP30) ea_ir_room; (WP92) lea_slot
                    if (len(step) > 2 and step[2] == "ea" and self.cls == "lea"
                            and self.decoder.need == 0):
                        self.decoder.queue.lea_ea = (t, self.resume)   # (WP72) lea_room
                    q = self.decoder.queue
                    if (self.cfg.abort_unit == "loop" and self.cls in SHIFT_CLASSES
                            and not self.mem and self.k == len(self.steps) and q.retry
                            and q.retry_loop and q.abort_t == self.start_clock):
                        # (WP21) abort_unit=loop: a register shift started on an aborted
                        # cycle raises the dropped request as its last count iteration starts
                        q.retry_at = self.resume - self.cfg.per_shift_count
                    if (self.cls in ("mul", "div") and not self.mem and self.k == len(self.steps)
                            and (self.cfg.io_take != "none" or self.cfg.abort_reg) and q.retry
                            and q.retry_loop and q.abort_t == self.start_clock):
                        # (WP22) io_take, abort_reg: a register multiply or divide raises the
                        # request dropped at its start mtail clocks before its end
                        q.retry_at = self.resume - self.cfg.c(self.ccls, "mtail")
                    if (self.reg_early and self.cls in ("mul", "div")
                            and self.k == len(self.steps) and self.cfg.abort_reg_end == "keep"):
                        self.resume += 1    # (WP22) abort_reg: the early start keeps its end
                    if (q.retry_at is not None and q.retry_at <= t
                            and self.cfg.retry_first):
                        # (WP22) retry_first: a count loop of one iteration raises the
                        # request on its first clock, the clock the loop starts
                        q.retry_at = None
                        if q.retry:
                            q.retry = False
                            q.flag = q.room(t) >= 2
                    if q.shift_held and self.k == len(self.steps):
                        q.shift_until = self.resume - 1     # (WP21) count_latch: its last clock
                    if (len(step) > 2 and step[2] == "mexec" and not self.unit_early
                            and self.cfg.io_take == "unit" and q.retry and q.retry_loop
                            and q.abort_t == self.start_clock):
                        # (WP22) io_take=unit: a memory multiply or divide whose ModR/M take
                        # dropped the request raises it mtail clocks before its end
                        q.retry_at = self.resume - self.cfg.c(self.ccls, "mtail")
                    if (len(step) > 2 and step[2] == "mexec" and self.unit_early
                            and self.cfg.abort_unit == "loop"):
                        # (WP21) abort_unit=loop: the early read does not move the multiply's
                        # end; the aborted request is raised again mtail clocks before the
                        # end the exec would have had from the early read (WP22: mtail
                        # counted from that end, 2; the eleventh fit's 3 from the moved end)
                        q = self.decoder.queue
                        if q.retry and q.retry_loop:
                            q.retry_at = self.resume - self.cfg.c(self.ccls, "mtail")
                        self.resume += 1
                    if self.ls_shift and self.cls == "shift_cl" and len(self.trace) == 2:
                        # refresh_align=phase_eu: the first LS's exec clocks, aligned
                        self.resume = max(t, self.resume + self.ls_shift)
                        self.ls_shift = 0
                    if self.refresh is not None:
                        # refresh_eu: a shift's count loop is its template's last clocks
                        # step (templates.py), its other clocks steps the shift's own;
                        # with refresh_eu=hold the template tags its loop and exit
                        self.clk_tag = (step[2] if len(step) > 2 and step[2] in ("exec", "loop", "tail", "loop_odd", "mexit")
                                        else None if self.cls not in SHIFT_CLASSES else
                                        "loop" if self.k == len(self.steps) else "shift")
                        self.clk_end = self.resume
                        q = self.decoder.queue
                        if (self.clk_tag == "tail" and q.dropped and q.drop_hold
                                and self.cfg.shift_exit0 == "exit"
                                and self.cfg.refresh_reraise == "unit" and self.cfg.reraise_off == 0
                                and step[1] < self.cfg.shift_tail):
                            # (WP36) shift_exit0: the request a refresh took from the loop rises
                            # 2 clocks before the shift's end, as after a 3-clock exit's first
                            # clock: on a 2-clock exit's first clock
                            q.dropped = False
                            q.flag = q.room(t) >= 2
                        if (self.clk_tag == "tail" and q.dropped
                                and self.cfg.refresh_reraise == "loop_end"):
                            q.dropped = False           # (WP17) the loop's end raises a fetch
                            q.flag = q.room(t) >= 2     # request a refresh beat again
                continue
            if kind == "nowait":                 # (WP20) step[1] clocks not in a wait state
                if self.left_nw is None:
                    self.left_nw = step[1]
                    if (self.cfg.lookup_start and t == self.start_clock + 1
                            and self.fetch_start == self.start_clock):
                        # (WP31) lookup_start: a fetch issued on the start clock costs the
                        # lookup a clock
                        self.left_nw += 1
                    self.nw_t, self.nw_run = t, None
                if self.left_nw and (not self.bus.in_wait(t) or self._run_wait(t)):
                    self.left_nw -= 1
                if self.left_nw:
                    self.resume = t + 1
                    return
                self.left_nw = None
                self.k += 1
                continue
            if kind == "take":
                if step[1] == 0:
                    self.k += 1
                    continue
                if not self.left:
                    self.left = step[1]
                if (self.cfg.imm_latch == "wait" and t < self.latch_until
                        and self.taken >= self.op_len - 1 - self.imm_bytes):
                    return              # a data immediate: the data latch holds an OUT's data
                if (len(step) > 2 and step[2] == "port" and self.cfg.port_latch == "wait"
                        and self.req is not None and self.req.detached and self.req.cycles
                        and self.req.cycles[0][0].startswith("io")):
                    return              # port_latch=wait: the latch is held by the waiting I/O
                if self.cfg.late_read and self._late_read(t):
                    return              # late_read: the take and the IR load wait for the word
                if (self.cfg.sync_req == "disp" and self.mem and self.disp
                        and (self.imm_bytes or self.cfg.late_disp == "all")
                        and self.taken == 1 and self._late_fetch(t)):
                    return              # (WP27) the displacement waits for the word's delivery
                n = self.decoder.take(t, self.left, wide=len(step) > 2 and step[2] in (
                    "word", "chain_word"))
                if not n and self.decoder.queue.dropped:
                    q = self.decoder.queue      # refresh_drop: a starved decoder raises it again
                    q.dropped = False
                    q.flag = q.room(t) >= 2
                self.taken += n
                self.left -= n
                if n and self.cfg.io_take_nx and self.decoder.need == 0 and self.cls == "reg":
                    cur = self.bus.current
                    if cur is not None and cur.kind.startswith("io") and cur.start == t:
                        # (WP32) io_take_nx: a register form's last operand byte taken on
                        # an I/O cycle's issue clock: the ALU passes the OUT's data there,
                        # the form's operation and so the IR load go a clock later
                        self.decoder.ready_at += 1
                if (n and self.lea_split and self.cfg.lea_disp == "run"
                        and self.decoder.need == 0 and not self._in_run(t)):
                    # (WP92) lea_disp=run: the split d16 taken off a refill run (the bus idle
                    # before the take clock): its successor is held off no back-to-back fetch
                    self.lea_split = False
                if n and self.mem and self.disp and self.taken == self.op_len - 1 - self.imm_bytes:
                    # (WP28) the displacement's (last byte's) take
                    q = self.decoder.queue
                    q.disp_t = t                        # latch_disp
                    if q.arrived_t == t:
                        self.decoder.ir_hold = False    # ir_load: on a word's delivery clock
                    if self.cfg.disp_floor != "none" and self.cfg.c(self.ccls, "dfloor"):
                        # disp_floor: the first data cycle no earlier than dfloor clocks after
                        self._floor(t + self.cfg.c(self.ccls, "dfloor"))
                if (n and self.cfg.wlatch and self.cfg.wlatch_src != "write"
                        and self.taken >= self.op_len - 1 and (
                            self.imm_bytes and not (self.cfg.wlatch_imm != "all" and self.mem)
                            or self.cfg.wlatch_imm == "reg_last" and not self.mem
                            and self._interlocked(self.cls, "reg")
                            and not (self.cls in ("mul", "div")
                                     and self.cfg.wlatch_mul == "none"))):
                    # wlatch_src: the last immediate byte enters the data latch on its take
                    # (reg_last: the last operand byte of any register-only form)
                    self.wlatch_until = max(self.wlatch_until, t + self.cfg.wlatch)
                    self.reg_latch_t = t        # (WP19) wlatch_ir: filled by this form
                if self.left:
                    return                                  # stalled or more to take
                self.decoder.commit(t)
                q = self.decoder.queue
                if (self.cfg.count_latch and self.cls == "shift_imm" and self.imm_bytes
                        and q.arrived_t == t and q.latched
                        and q.room(t) - (q.latched if self.decoder.need == 0 else 0) < 2):
                    # (WP21) count_latch: an operand byte of a count-byte shift taken on a
                    # word's delivery clock with its second byte latched and no room for a
                    # word but that uncounted byte: no fetch until the shift's last clock
                    self.shift_latched = True
                    q.shift_held = True
                io_drop = self._io_drop(t, q)
                self.k += 1
                if len(step) > 2 and step[2] == "port":
                    self._port_take(t, step)
                    if self.cfg.port_sync == "none":
                        self.resume = t + 1             # the byte went to the port latch
                        return
                if len(step) > 2 and step[2] == "lead":
                    continue                            # alongside the next step's clocks
                if len(step) > 2 and step[2] in ("chain", "chain_word"):
                    self.resume = t + 1                 # more operand bytes follow: no sync
                    return
                opcode = len(step) > 2 and step[2] != "word"
                if opcode and self.cfg.opcode_overlap:
                    continue
                if not opcode and self.cfg.post_on_take and self._data_next():
                    continue                            # post the request on the take clock
                if not opcode and self.cfg.take_sync == "pending":
                    q = self.decoder.queue
                    held = (self.cfg.io_hold != "hold_fetch" and self.req is not None
                            and self.req.detached and self.req.cycles)
                    asked = False if io_drop else q.asked(t)   # (WP22) io_take: dropped
                    cur = self.bus.current
                    if (self.cfg.sync_io != "none" and asked and cur is not None
                            and cur.kind.startswith("io") and cur.start <= t <= cur.end
                            and (self.cfg.sync_io == "busy" or cur.start == t)
                            and (self.cfg.sync_io not in ("latch", "unit")
                                 or self.reg_latch_t == t
                                 or self.cfg.sync_io == "unit" and not self.mem
                                 and self.cls in ("mul", "div"))):
                        asked = False   # (WP20) the bus is the I/O's: a request raised
                                        # under it is not the take's fetch
                    if self.cfg.sync_req == "either" and self.imm_bytes and self.mem:
                        asked = asked and not q.inflight     # the fetch in flight, else the asked one
                    self.sync = q.completed + q.inflight + int(asked and not held)
                    if (self.cfg.grp_disp == "hold" and self.grp_form and self.mem
                            and self.disp == 2 and self.gdisp_cls and not self.imm_bytes
                            and self.taken == self.op_len - 1):
                        # (WP61) grp_disp=hold: a group RMW form's two-byte displacement: the
                        # take sync waits only for a fetch on the bus, a fetch is held for
                        # the take clock and the grp_free clocks after it (arbiter.py)
                        self.sync = q.completed + q.inflight
                        # (WP91) a class with its own dhold holds the fetch that long (the
                        # memory-indirect transfers under xfer_mem_disp=grp); rmw: grp_free
                        hold = ("dhold" if "dhold" in self.cfg.cost.get(self.ccls, {})
                                else "grp_free")
                        q.gdisp_until = t + self.cfg.c(self.ccls, hold)
                    if self.cfg.sync_req == "none" and self.imm_bytes and self.mem:
                        self.sync = None    # (WP27) the group setup counts through the fetch
                    elif self.cfg.sync_req == "disp" and self.imm_bytes and self.mem and self.disp:
                        self.sync = None    # (WP27) no sync after an immediate form's displacement
                    if (self.cfg.imm_landed and self.imm_bytes and not self.mem
                            and q.arrived_t == t and q.latched):
                        # imm_landed: a register form's last immediate byte taken on a word's
                        # delivery clock (its second byte latched): the sync counts the
                        # fetches pending on the next clock
                        self.sync = "defer"
                    if self.cfg.count_latch and self.shift_latched:
                        # (WP21) count_latch: the shift holds the queue port (no fetch until
                        # its last clock, queue.shift_held); a count byte taken on the
                        # latched delivery clock reaches the shift counter a clock later
                        self.sync = q.completed + q.inflight
                        self.resume = t + (2 if q.arrived_t == t else 1)
                        return
                elif not opcode and self.cfg.take_sync == "pending_end":
                    self.sync = "pending_end"           # resolved at the end of the clock
                elif not opcode and self.cfg.take_sync != "none":
                    self.sync = self.cfg.take_sync
                self.resume = t + 1
                return
            if kind == "data":
                if self.own is None:
                    self.own = self._submit(t, *step[1:])
                    if self.own is None:
                        return                          # the slot and its queue are full
                if self.own.done_at is None or t < self.own.done_at:
                    return
                self.last_issued = self.own.issued      # (WP76) str_split: the cycles it ran
                self._retire()
                self.k += 1
                continue
            if kind == "split_floor":            # (WP76) str_split=floor: a split last cycle's
                cyc = self.last_issued           # second half issued no fewer than step[1]
                if len(cyc) > 1 and t < cyc[-1].start + step[1]:   # clocks ago
                    self.resume = cyc[-1].start + step[1]
                    return
                self.k += 1
                continue
            if kind == "post":                   # post and go on (imm_order=after_post)
                if self.own is None:
                    self.own = self._submit(t, *step[1:])
                    if self.own is None:
                        return
                    if step[1].startswith("io") and self.k and self.steps[self.k - 1][0] == "slot":
                        self.own.port = True        # a port form re-latching its port byte
                    elif step[1].startswith("io"):
                        self._preload(self.own)
                self.k += 1
                continue
            if kind == "post_io":                # io_release=post: post and leave it to the bus unit
                r = self._submit(t, *step[1:], detached=True)
                if r is None:
                    return
                if self.k and self.steps[self.k - 1][0] == "slot":
                    r.port = True                   # a port form re-latching its port byte
                else:
                    self._preload(r)
                self.k += 1
                continue
            if kind == "slot":                   # wait until the I/O ahead has released the latch
                if self.req is not None and self.req.cycles:
                    return
                self.k += 1
                self.resume = max(t, int(self.latch_until))
                continue
            if kind == "fetch_release":          # (WP76) str_fetch=hold: no request from the
                q = self.decoder.queue           # first element's post (step[1] None) / again
                if len(step) > 2:                # CW = 0: a retried request raised step[1]
                    q.str_raise = t + step[1]    # clocks into the exit
                else:
                    q.str_held = (float("inf") if step[1] is None   # step[1] clocks after
                                  else t + step[1])  # the stream's last cycle
                self.k += 1
                continue
            if kind == "fetch_hold":             # (WP67, F24) str_hold=hold: no fetch request
                q = self.decoder.queue           # for step[1] clocks from here
                q.str_held = t + step[1]
                self.k += 1
                continue
            if kind == "quiet":                  # (WP67, F24) str_take=quiet: wait for the
                q = self.decoder.queue           # refill: no fetch on the bus or wanted
                if self.bus.fetch_inflight(t) or q.wants_fetch(t):
                    return
                self.k += 1
                continue
            if kind == "sent":                   # (WP52) burst_wait=issue: the posted word is
                if self.own is not None:         # on the bus: the EU lets it go and goes on
                    if not self.own.issued:
                        return
                    self._retire()
                self.k += 1
                continue
            if kind == "issued":                 # wait until the posted request is on the bus
                if self.own is not None and not self.own.issued:
                    return
                self.k += 1
                continue
            if kind == "wait":                   # wait for the request a post step left
                if self.own is not None:
                    if self.own.done_at is None or t < self.own.done_at:
                        return
                    self._retire()
                self.k += 1
                continue
            if kind == "wbsync":                 # wait for the previous write-back
                if t < self.wb_until:
                    self.resume = self.wb_until
                    return
                self.since_start = 0             # the instruction proper starts now
                self.since_t = t                 # (WP38) refresh_io_pre
                self.k += 1
                continue
            if kind in ("flush", "decide"):      # (WP55) a taken transfer: the queue discarded,
                gap = ("nfgap" if kind == "decide" else step[2] if len(step) > 2
                       else "fgap")              # (WP72) cond_gap=own: cfgap
                q = self.decoder.queue
                if (kind == "decide" and q.nb_at is not None
                        and q.nb_start == self.start_clock):
                    # (WP89) xfer_nt_b2b=decide: the test does not wait for the fetch the bus
                    # unit committed to back to back in it, only for those before it
                    old = [c for c in self.bus.cycles[-4:] if c.kind == "fetch"
                           and c.start < q.nb_at]
                    inflight = bool(old) and old[-1].end >= t
                    last = old[-1].end if old else -10
                elif kind == "decide" and q.odd_nt and q.odd_until is not None:
                    # (WP81) xfer_nt=odd: the test does not wait for the fetches its own
                    # release raised (on or after odd_until), only for those before it
                    old = [c for c in self.bus.cycles[-4:] if c.kind == "fetch"
                           and c.start < q.odd_until]
                    inflight = bool(old) and old[-1].end >= t
                    last = old[-1].end if old else -10
                else:
                    inflight, last = self.bus.fetch_inflight(t), self.bus.last_fetch_end
                if (kind == "decide" and self.cfg.decide_abort == "cycle"
                        and q.abort_t is not None and q.abort_t >= self.start_clock):
                    # (WP89) decide_abort=cycle: an aborted cycle that answered a request since
                    # the transfer's start counts as the fetch it stood for: the gap from its
                    # last clock
                    last = max(last, q.abort_t + 2)
                if self.cfg.flush_inflight == "wait" and (
                        inflight or t <= last + self.cfg.c(self.ccls, gap)):
                    return                       # (flush_inflight=wait: fgap clocks after the
                                                 # last fetch's end)
                if kind == "flush":              # (untaken=wait: a transfer not taken waits as
                    self._flush(t, step[1])      # its flush would, "decide")
                self.k += 1
                continue
            if kind == "halt":
                self.halt_t = t
                self.halted = True
                if self.refresh is not None:     # (WP23) halt_refresh, refresh on only
                    self.decoder.queue.halted = self.cfg.halt_refresh != "none"
                self.decoder.stopped = True
                return
            raise ValueError(kind)

    def _flush(self, t: int, target: int):
        """(WP55) the flush of a taken branch, CALL or RET: the queue and the IR emptied, the
        fetch pointer at the target (queue.flush), the EU's next instruction the target's;
        refill_start decides when that instruction may start."""
        q = self.decoder.queue
        q.flush(t, q.base + target)
        self.decoder.ir = None
        self.pc = target
        self.refill = True

    def _early(self, t: int) -> bool:
        """(WP34) refresh_sync=run: t is one of the last two clocks of a fetch of the run that
        followed a refresh which beat the fetch the take sync counted (for the EU that fetch
        has been delivered)."""
        cur = self.bus.current
        return (self.bus.early is not None and cur is self.bus.early
                and self.cfg.refresh_sync == "run" and cur.start <= t and t >= cur.end - 1)

    def in_loop(self, t: int) -> bool:
        """(WP23) refresh_reraise=unit: a count loop (the shift's, or MULU's with refresh_mul)
        is running on t."""
        cls = getattr(self, "cls", None)
        units = ("shift_cl", "shift_imm", "mul") + (("div",) if self.cfg.refresh_unit != "mul"
                                                    else ())
        if getattr(self, "mem", True) or cls not in units:
            return False
        if t < self.resume and self.resume == self.clk_end and self.clk_tag == "tail":
            return False                 # past its loop
        return self.k < len(self.steps) or t < self.resume

    def _in_clocks(self, t: int, loop: bool) -> bool:
        """A clocks step (with loop: a count loop) occupies t and is still running."""
        return (t < self.resume and self.resume == self.clk_end
                and (not loop or self.clk_tag == "loop"))

    def _after_disp(self, nxt, t: int) -> bool:
        """(WP34) refresh_disp=free: nxt, due on t, is a memory form's clocks step straight
        after its displacement's take, or the request post that follows that step."""
        k = self.k
        disp = ("take", 2, "word")
        if (nxt[0] == "clocks" and nxt[1] and k >= 1 and self.steps[k - 1] == disp
                and t == self.resume and self.decoder.queue.take_t is not None
                and self.decoder.queue.take_t >= t - 1):
            return True
        return (nxt[0] == "post" and k >= 2 and self.steps[k - 1][0] == "clocks"
                and self.steps[k - 2] == disp)

    def boundary(self, t: int, before: bool = False) -> bool:
        """refresh_eu=hold: whether t is one of the EU's micro-boundaries (before: asked at
        the start of t, ahead of the EU's step; else after it). Inside a clocks step: in a
        tagged count loop each iteration's start but the first (end-aligned, 2 clocks);
        in the loop's exit the clock refresh_tail_bound before its end; none in another
        clocks step. A clocks step's first clock is one unless the step follows another
        clocks step on its end clock (the exec into the loop, the loop into its exit).
        Every clock the EU is not in a clocks step (an instruction start, a take, a wait
        for bytes, a sync or a bus request) is one."""
        inside = t < self.resume and self.resume == self.clk_end
        if before and not inside and self.k < len(self.steps):
            nxt = self.steps[self.k]
            if self.cfg.refresh_take0 == "none" and nxt[0] == "take" and nxt[1] == 0:
                # (WP36) refresh_take0: an empty operand take is no step: the clock is the
                # one after it (a NOP's end: the next instruction's start)
                rest = self.steps[self.k + 1:]
                if all(st[0] in ("take", "clocks") and not st[1] for st in rest):
                    return True
            if self.cfg.refresh_wbsync == "seam" and nxt[0] == "wbsync":
                return False             # (WP37) refresh_wbsync: the write-back sync's clocks
            if (self.cfg.shift_exit0 == "exit" and nxt[0] == "clocks" and len(nxt) > 2
                    and nxt[2] == "tail" and nxt[1] == self.cfg.refresh_tail_bound):
                return True              # (WP36) shift_exit0: a 2-clock exit's first clock
            if (self.cfg.refresh_loop_hold == "entry" and nxt[0] == "clocks" and nxt[1]
                    and len(nxt) > 2 and nxt[2] == "loop" and self.k >= 1
                    and len(self.steps[self.k - 1]) > 2 and self.steps[self.k - 1][2] == "exec"):
                return True              # (WP38) refresh_loop_hold: the loop's first clock
            if (nxt[0] == "clocks" and nxt[1] and self.k >= 1 and t == self.resume
                    and self.steps[self.k - 1][0] == "clocks" and self.clk_end == t):
                return False             # a seamless clocks-to-clocks transition
            if (self.cfg.refresh_take_seam == "seam" and nxt[0] == "clocks" and nxt[1]
                    and self.k >= 1 and t == self.resume and self.steps[self.k - 1][0] == "take"
                    and self.k + 1 < len(self.steps) and self.steps[self.k + 1][0] == "take"
                    and self.steps[self.k + 1][1] and self.decoder.queue.take_t is not None
                    and self.decoder.queue.take_t >= t - 1):
                return False             # (WP37) refresh_take_seam: straight after a take
            if self.cfg.refresh_disp == "free" and self._after_disp(nxt, t):
                return False             # (WP34) refresh_disp: the address phase runs on
            if (self.cfg.refresh_take_latch == "hold" and nxt[0] == "take" and nxt[1]
                    and self.decoder.queue.latched
                    and len(self.decoder.queue.bytes) > QUEUE_BYTES):
                return True              # (WP39) refresh_take_latch: a byte latched behind
                                         # a full queue: the take waits for the port
            if nxt[0] == "take" and (self.cfg.refresh_hold_take == "free" or (
                    self.cfg.refresh_hold_take == "port"
                    and not (len(nxt) > 2 and nxt[2] == "port"))):
                return False             # the decoder serves takes while a refresh runs
                                         # (port: but a port byte's take posts the I/O)
            return True
        if not inside:
            return True
        left = self.resume - t
        if (self.cfg.shift_exit0 == "exit" and self.clk_tag == "tail" and not before
                and left == self.cfg.refresh_tail_bound):
            return True                  # (WP36) shift_exit0: a 2-clock exit's first clock
        if t == self.clk_start and not before:
            return not self.clk_seam
        if self.clk_tag == "loop":
            return left % 2 == 0 and t > self.clk_start
        if self.clk_tag == "loop_odd":
            return left % 2 == 1 and t > self.clk_start
        if self.clk_tag == "mexit":
            return left % 2 == 0 and t > self.clk_start    # (WP36) refresh_mul_exit
        if self.clk_tag == "exec":
            if self.cfg.refresh_exec == "every2_early":
                return left % 2 == 0 and left > 2   # (WP24) not on the loop's eve
            if self.cfg.refresh_loop_hold == "entry" and left == 2:
                return False                     # (WP38) refresh_loop_hold: the eve is none
            if self.cfg.refresh_exec == "every2_recent" and left == 2:
                # (WP24) the boundary on the loop's eve is one only within refresh_recent
                # clocks of the previous refresh cycle's start (accepting and holding);
                # with none before, or one longer ago, the exec runs into its loop
                rf = self.refresh
                starts = [b for a, b in rf.served] if rf is not None else []
                holding = self.hold_end is not None and bool(starts) and starts[-1] >= t - 5
                if self.cfg.refresh_eve == "hold" and not holding:
                    return False                 # (WP35) refresh_eve: a pending request waits
                if holding:
                    starts = starts[:-1]         # holding for the cycle now on the bus
                lim = self.cfg.refresh_recent
                if self.cfg.refresh_recent_by == "fetch":
                    lim -= self.bus.length("fetch") - 3   # (WP24) less the memory waits
                return bool(starts) and t - starts[-1] <= lim
            return left % 2 == 0 and self.cfg.refresh_exec.startswith("every2")
        if self.clk_tag == "tail":
            return left == self.cfg.refresh_tail_bound
        return False

    def _rmw_bound(self, d: int, r) -> bool:
        """(WP24) refresh_rmw_loop=loop: whether the memory shift's write setup, d clocks
        before its issue, is a micro-boundary. even: every even d. (WP37) shift: the register
        shift's shape end-aligned to the issue: the post's first clock, the count loop's
        iteration starts and the exec's every second clock before them (d = shift_tail + 2k up
        to the shift unit's first clock, rmw_top), the exit's clock refresh_tail_bound before
        the issue; none in the ALU clocks between the post and the shift unit."""
        if self.cfg.refresh_rmw_shape != "shift":
            return d % 2 == 0
        if d == r.setup - 1 or d == self.cfg.refresh_tail_bound or d == 0:
            return True                  # the post's first clock (count 1), the exit, the issue
        tail = self.cfg.shift_tail
        return tail + 2 <= d <= self.rmw_top and (d - tail) % 2 == 0

    def refresh_ok(self, t: int, other: str | None = None) -> bool:
        """refresh_accept: whether a pending refresh request may be taken on t (bus free);
        other: the cycle the bus unit would otherwise start on t ("data", "fetch", None)."""
        mode = self.cfg.refresh_accept
        if (self.cfg.refresh_wb == "free_wait" and self.k < len(self.steps)
                and self.steps[self.k][0] == "wbsync" and t < self.wb_until):
            return False                         # (WP61) refresh_wb: waiting for the write-back
        if mode == "bus":
            return True
        if mode == "boundary":
            return self.boundary(t)
        if (self.cfg.refresh_abort_wait == "run" and isinstance(self.sync, int)
                and self.decoder.queue.abort_end is not None
                and t <= self.decoder.queue.abort_end and self.k < len(self.steps)):
            return False                         # (WP37) refresh_abort_wait: the EU runs
        if (self.cfg.refresh_take == "last" and self.k < len(self.steps)
                and self.steps[self.k][0] == "take" and self.left > 0 and t >= self.resume):
            return False                         # (WP23) mid-take: bytes still to come
        if mode == "boundary_bus":               # clocks steps by their boundaries; while the
            r = self.req
            if (self.cfg.refresh_rmw_loop == "loop" and self.rmw_loop and r is not None
                    and r.cycles and not r.issued and r.cycles[0][0] == "write"
                    and 0 < r.setup - r.count <= self.rmw_loop):
                # (WP24) a memory shift's count loop, counted by its write's setup: the
                # iteration boundaries (an even number of clocks before the loop ends)
                return self._rmw_bound(r.setup - r.count, r)
            if t < self.resume and self.resume == self.clk_end:   # EU waits on a posted data
                if (self.clk_tag == "loop" and t == self.clk_start
                        and self.cfg.refresh_loop_entry in ("open", "hold")):
                    return True                  # the loop's first clock takes a request
                return self.boundary(t)          # request: when the bus unit would start a
            if other is not None:                # cycle, or on the first clock of the request's
                return True                      # fetch-free setup window; other waits: any
            r = self.req
            if r is not None and r.cycles and not r.issued and not r.detached:
                need = r.setup if r.free_need is None else min(r.free_need, r.setup)
                if self.cfg.refresh_window == "posted" and r.free_orig:
                    need = r.free_orig           # (WP61) refresh_window: the window as posted
                if r.grpcl and r.setup - r.count == r.grpcl - 1:
                    return True          # (WP37) refresh_grpcl: the CL clocks' first
                if (self.cfg.refresh_post in ("post", "post_beat") and r.posted == t
                        and r.cycles[0][0] in ("read", "write")):
                    return True          # (WP37) refresh_post: the post's first clock
                if (self.cfg.refresh_io_step in ("step", "own") and io_stepped(r, self)
                        and io_step(r, self.bus, t)):
                    return True          # (WP58) refresh_io_step: the IN's I/O on a step
                return r.count == r.setup - need + 1
            return True
        if mode == "boundary_micro":             # clocks steps by their boundaries; while the
            if t < self.resume and self.resume == self.clk_end:   # EU waits, as micro_bus
                return self.boundary(t)
            if other is not None:
                return True
            return (t - self.start_clock - self.stalled) % 2 == 1
        if self._in_clocks(t, True):            # a count loop: its iteration boundaries
            return (self.resume - t) % 2 == (1 if mode == "loop_odd" else 0)
        if mode in ("loop_even", "loop_odd") or self._in_clocks(t, False) and (
                mode != "micro_all" or self.clk_tag == "shift"):
            return True                         # any other clocks step: any clock
        # waiting (a take, a sync, a posted request, a write-back): the EU's 2-clock
        # microcycles from the instruction's start (shifted by its refresh stalls) end on
        # the odd clocks; the bus unit takes the request at once when it would otherwise
        # start a cycle of its own (micro_bus), or a data cycle (micro_data)
        if mode in ("micro_bus", "micro_all") and other is not None:
            return True
        if mode == "micro_data" and other == "data":
            return True
        return (t - self.start_clock - self.stalled) % 2 == 1

    def refresh_cost(self, t: int, length: int = 5):
        """refresh_eu: a refresh cycle of length clocks starts on t; the EU step it stalls
        ends later (the count loop by refresh_stall clocks, another stalled step by
        refresh_stall_exec); with hold, the EU waits at its next micro-boundary after t
        until the cycle's last clock has passed (tick)."""
        mode = self.cfg.refresh_eu
        r = self.req
        if (self.cfg.refresh_rmw_loop == "loop" and self.rmw_loop and r is not None
                and r.cycles and not r.issued and r.cycles[0][0] == "write"
                and 0 < r.setup - r.count <= self.rmw_loop):
            if self.cfg.refresh_rmw_shape == "shift":
                # (WP37) refresh_rmw_shape: the EU holds at its next boundary until the
                # cycle's last clock has passed
                d = r.setup - r.count
                b = next((x for x in range(d - 1, -1, -1) if self._rmw_bound(x, r)), 0)
                r.setup += max(0, length - (d - b))
            else:
                r.setup += length - 2        # (WP24) the loop waits out the cycle (hold)
            return
        if (r is not None and r.grpcl and r.cycles and not r.issued
                and 0 < r.setup - r.count):
            # (WP37) refresh_grpcl: the memory shift's read setup counts through the cycle;
            # the EU holds at its next boundary (the CL clocks' first, the issue)
            d = r.setup - r.count
            b = r.grpcl - 1 if d > r.grpcl - 1 else 0
            r.setup += max(0, length - (d - b))
            return
        if (self.cfg.refresh_post in ("post", "post_beat") and r is not None and r.cycles
                and not r.issued and not r.detached and r.cycles[0][0] in ("read", "write")
                and 0 < r.setup - r.count
                and not (t < self.resume and self.resume == self.clk_end)):
            # (WP37) refresh_post: the setup counts through the cycle; the EU holds at the
            # next boundary (the first fetch-free setup clock, the issue) until its end
            need = r.setup if r.free_need is None else min(r.free_need, r.setup)
            d = r.setup - r.count
            b = need - 1 if d > need - 1 else 0
            if not getattr(self, "refresh_beat", False):
                r.setup += max(0, length - (d - b))
            elif self.cfg.refresh_post == "post_beat":
                # (WP58) refresh_post=post_beat: the hold as without a beaten fetch, given back
                # if the beaten fetch runs ahead of the request after the refresh (arbiter.py)
                r.beat_ext = max(0, length - (d - b))
                r.setup += r.beat_ext
        if mode == "hold":
            self.hold_from, self.hold_end = t, t + length - 1
            if (self.cfg.refresh_loop_entry == "hold" and t < self.resume
                    and self.resume == self.clk_end and self.clk_start == t
                    and self.clk_tag in ("loop", "loop_odd")):
                # (WP23) refresh_loop_entry=hold: a refresh let through on a count loop's
                # first clock holds the loop there: it starts after the cycle
                self.resume += length
                self.clk_end = self.resume
                self.clk_start = t + length
                return
            if (self.cfg.refresh_start_hold != "none" and t < self.resume
                    and self.resume == self.clk_end and self.clk_start == t
                    and not self.clk_seam and self.clk_tag not in ("loop", "loop_odd")
                    and (self.cfg.refresh_start_hold == "step" or self.start_clock == t)):
                # (WP23) refresh_start_hold: the clocks step that began on the clock the
                # refresh was let through (its first clock, a micro-boundary) waits for it
                self.resume += length
                self.clk_end = self.resume
                self.clk_start = t + length
            return
        if mode == "none" or not self._in_clocks(t, False):
            return
        tag = self.clk_tag
        if mode == "loop" and tag != "loop" or mode == "shift" and tag not in ("loop", "shift"):
            return
        n = self.cfg.refresh_stall if tag == "loop" else self.cfg.refresh_stall_exec
        self.resume += n
        self.clk_end = self.resume
        self.stalled += n

    def _late_fetch(self, t: int) -> bool:
        """(WP27) a fetch is on the bus past its second clock (its wait states or last clock)."""
        cur = self.bus.current
        return cur is not None and cur.kind == "fetch" and cur.start + 2 <= t <= cur.end

    def _late_read(self, t: int) -> bool:
        """late_read: on t a fetch is past its second clock and this take is the
        instruction's last operand byte with the IR loading the next opcode on t as well."""
        cur = self.bus.current
        return (cur is not None and cur.kind == "fetch" and cur.start + 2 <= t <= cur.end
                and self.left == 1 and self.decoder.loads_after(t, 1))

    def page_active(self) -> bool:
        """(WP86) page_run: a 0F memory form (or, field, a bit field) runs and its read has not
        issued."""
        if not getattr(self, "page_run", False):
            return False
        r = self.req
        return self.page_fixed == "start" or (r is not None and r.pfree is not None
                                              and not r.issued)

    def end_clock(self, t: int):
        """take_sync=pending_end: after the clock's bus choice, wait for every fetch then
        in flight (including one issued this clock) and one more if a request is still
        raised."""
        if self.sync == "pending_end":
            q = self.decoder.queue
            self.sync = q.completed + q.inflight + int(q._raised(t))

    def _floor(self, at: int):
        """(WP28) disp_floor: the next data request issues no earlier than at; (WP29) with
        disp_floor=posted a request already posted (POP r/m's write, posted at the stack data)
        is floored at once, its floor extending its setup (it holds fetches as the setup does)."""
        self.dfloor_at = at
        r = self.req
        if (self.cfg.disp_floor == "posted" and r is not None and r.cycles and not r.issued
                and not r.detached and not r.cycles[0][0].startswith("io")):
            r.not_before = max(r.not_before, at)
            r.floor_hold = True
            self.dfloor_at = None

    def _data_next(self) -> bool:
        """The next step that takes time is a data request (zero-clock steps skipped);
        with post_on_take=write, a write request; with nomodrm, in a form without a
        ModR/M byte only."""
        if self.cfg.post_on_take == "nomodrm" and self.modrm:
            return False
        for step in self.steps[self.k:]:
            if step[0] == "clocks" and not step[1]:
                continue
            if self.cfg.post_on_take == "write":
                return step[0] == "data" and step[1].endswith("write")
            return step[0] == "data"
        return False

    def _submit(self, t, *args, detached: bool = False) -> Request | None:
        """Post a request into the bus unit's slot, or behind a detached request still
        waiting there (io_release=post: an OUT's I/O; the request moves into the slot,
        and starts counting its setup, when the one ahead of it is issued)."""
        r = self._post(t, *args)
        if (self.rmw_cl and args[0] == "read" and self.refresh is not None
                and self.cfg.refresh_grpcl == "step"):
            r.grpcl = self.rmw_cl            # (WP37) refresh_grpcl
        if getattr(self, "dfloor_at", None) is not None and not args[0].startswith("io"):
            r.not_before = max(r.not_before, self.dfloor_at)   # (WP28) disp_floor
            self.dfloor_at = None
        if getattr(self, "floor_n", 0) and not args[0].startswith("io"):
            # (WP25) imm_count=start: no issue before floor_n clocks from the start
            r.not_before = max(r.not_before, self.start_clock + self.floor_n)
            self.floor_n = 0
        q = self.decoder.queue
        if (self.cfg.abort_unit != "none" and (self.unit or self.cfg.abort_unit == "all"
                                               or self.cfg.abort_fixed and self.fixed)
                and q.abort_t == self.start_clock
                and not self.unit_early and r.setup > 0 and len(args) > 5 and args[5]
                and r.free_need is not None and r.free_need < r.setup):
            # (WP21) abort_unit: a unit form started on an aborted cycle: one group setup
            # clock ran during the aborted cycle's wait
            r.setup -= 1
            self.unit_early = True
        r.detached = detached
        if self.page_fixed and args[0] == "read":
            # (WP81) page_mem=fixed, bf_read=fixed: the read's setup clocks are all fetch-free
            # since the end of the last fetch but one the bus unit committed to back to back
            # after the form's start (page_mem) / the read's post (bf_read) (arbiter.py); a
            # 0F memory form counts them back from its post to its start
            mode, self.page_fixed = self.page_fixed, None
            r.nowait = r.dwlike = False         # not a DW-form count (bf_count)
            r.free_need = None
            if mode == "start":
                r.pfree = self.start_clock
                r.run_wait = self.cfg.page_run != "none"   # (WP86) the memory forms only
                n, c = 0, t - 1
                while c >= self.start_clock and n < r.setup and not any(
                        x.kind == "fetch" and x.start <= c <= x.end
                        and not (x.b2b and x.start > self.start_clock)
                        for x in self.bus.cycles[-6:]):
                    n, c = n + 1, c - 1
                r.count = n
            else:
                r.pfree = t - 1
        if (self.cfg.stack_wb != "none" and args[0] == "read" and t < self.wb_until
                and t == self.start_clock
                and self.cls == "ret"):     # (WP88) the base class: RET imm16, the far RETs
            # (WP81) stack_wb: a stack read posted while the previous form's write-back runs
            # (its start the clock after that form's last) is held a clock
            r.setup += 1
        if self.cfg.sreg_store == "own" and self.sreg == "store" and args[0] == "write":
            r.sreg = True                # (WP76) sreg_store=own: MOV r/m,sreg's write (arbiter)
        if (self.cfg.grp_disp == "hold" and r.free_bus and self.mem and self.disp == 2
                and self.gdisp_cls and not self.imm_bytes and args[0] in ("read", "nowrite")):
            r.gdisp = True               # (WP61) grp_disp=hold; (WP91) xfer_mem_disp=grp
        if detached and args[0] == "io_write":
            self.latch_until = float("inf")     # released when its I/O cycle ends
        if self.req is None:
            self.req = r
        elif self.req.detached or self.queued:
            self.queued.append(r)
        else:
            return None
        return r

    def _preload(self, r):
        """io_post=start: an I/O request's setup counts from the instruction's start (the
        clocks before its post that its count rule accepts), though it is posted, and
        holds fetches, only from the port take (pre0 clocks after the start without one)."""
        if self.cfg.io_post == "start" and r.cycles and r.cycles[0][0].startswith("io") \
                and self.req is r:
            r.setup += self.io_pre
            n = self.since_start
            if (n and self.cfg.dw_count != "all" and not r.port
                    and self.fetch_start == self.start_clock):
                n -= 1                          # dw_count: a fetch went out on the start clock
            r.count = min(r.setup, r.count + n)

    def _retire(self):
        if self.req is self.own:
            self.req = None
        self.own = None

    def _promote(self, t: int):
        """The detached request in the slot has been issued: the next queued one moves in."""
        self.req = None
        if self.queued:
            r = self.queued.pop(0)
            r.posted = t                        # it counts its setup from this clock
            if not r.cycles[0][0].startswith("io"):
                r.moved = True                  # (WP22) slot_fetch
            elif not r.port and self.cfg.dw_slot == "behind":
                r.dw_moved = True               # (WP25) dw_slot=behind
            self.req = r

    def _port_take(self, t: int, step):
        """A port byte taken (an IN/OUT imm form): port_latch=relatch holds an I/O still
        waiting in the slot until relatch clocks after this take; with io_release=post the
        step carries the instruction's I/O request, posted on the take clock."""
        if self.cfg.port_latch == "relatch":
            q = self.decoder.queue
            # (WP26) port_landed: a port byte taken on a word's delivery clock with the
            # word's second byte latched reaches the port latch a clock later
            late = int(self.cfg.port_landed and q.arrived_t == t and bool(q.latched))
            last = self.bus.cycles[-1] if self.bus.cycles else None
            if (last is not None and last.kind == "refresh" and last.end == t - 1
                    and self.cfg.port_refresh == "late"):
                late = 1                        # (WP85) port_refresh: the clock after a refresh
            held = []
            for r in [self.req] + self.queued:
                if (self.cfg.port_ready == "issue" and r is not None and (r.ready() or (
                        r.nowait and r.cycles and not r.issued and r.count + 1 >= r.setup
                        and self.cfg.port_ready_count == "count"))
                        and r.not_before <= t and not self.bus.busy(t)):
                    continue                    # (WP58) port_ready: it issues on this clock;
                                                # (WP85) port_ready_count: or counts out on it
                if r is not None and r.detached and r.cycles and not r.issued:
                    r.not_before = max(r.not_before, t + late + self.cfg.c(r.cls, "relatch"))
                    held.append(r)
            self.port_t, self.port_held = t, held    # (WP32) port_issue (machine.py)
        if len(step) > 3:
            req, detached = step[3], step[4]
            if (self.cfg.port_latch == "relatch" and self.req is not None
                    and self.req.detached and self.req.cycles):
                # the latch is held by the I/O waiting in the slot: the instruction waits
                # for the slot, latches its port again (relatch clocks), then posts
                kind = "post_io" if detached else "post"
                self.steps[self.k:self.k] = [("slot",), (kind, *req)]
                return
            r = self._submit(t, *req, detached=detached)
            if r is not None:
                r.port = True
                self._preload(r)
            if not detached:
                self.own = r

    def _post(self, t, kind, addr, width, setup, free=None, grp=False,
              whole=False) -> Request:
        if kind == "nowrite":
            cycles = [(kind, addr, "word")]      # grp_read=rmw_slot: a slot, not a cycle
        elif width == 2 and addr & 1 and not kind.startswith("io"):
            cycles = [(kind, addr, "hi"), (kind, addr + 1, "lo")]
        elif width == 2:
            cycles = [(kind, addr, "word")]
        else:
            cycles = [(kind, addr, "hi" if addr & 1 else "lo")]
        cls = getattr(self, "cls", "")
        cost = self.cfg.cost.get(getattr(self, "ccls", cls), {})   # (WP78) the class's own
        io = kind.startswith("io")
        # (WP70) str_count=dw: a string form's request counts as a DW-form I/O request's
        dwlike = (cls in STRING_CLASSES and self.cfg.str_count == "dw"
                  or cls == "push_r" and self.cfg.burst_count == "dw"
                  # (WP78) bf_count=dw: the bit fields the same
                  or cls in BF_CLASSES and self.cfg.bf_count == "dw")
        r = Request(cycles, setup, t, atomic=self.cfg.odd_split == "atomic",
                    free_need=cost.get("setup_free") if free is None else free,
                    lead=cost.get("lead", 0) if io else 0,
                    nowait=(io or dwlike) and self.cfg.io_count == "nowait", cls=cls,
                    free_bus=grp and self.cfg.grp_free_bus,
                    recover=self.cfg.io_recover, whole=whole)
        r.dwlike = dwlike
        # (WP58) refresh_io_stall (read with refresh on only)
        r.io_stall = io and self.refresh is not None and self.cfg.refresh_io_stall == "step"
        if io and self.refresh is not None:
            # (WP85) io_step_restart, refresh_lead_step (read with refresh on only)
            r.step_restart = self.cfg.io_step_restart
            r.lead_step = self.cfg.refresh_lead_step
        if (self.cfg.sfr_setup == "count" and kind == "write" and self.sfr is not None
                and self.cfg.sfr_cycle == "io" and addr >= SFR_PAGE):
            r.free_need = 0                      # (WP38) sfr_setup: no fetch-free clocks
        r.free_orig = min(r.free_need, r.setup) if r.free_need else 0   # (WP29) free_idle
        # (WP43) imm1_first: the first data request of a memory form with a one-byte immediate
        r.imm1 = (kind in ("read", "write") and self.imm_bytes == 1 and self.mem
                  and getattr(self, "floor_n", 0) > 0)
        if kind in ("write", "nowrite") and cls == "rmw" and not grp and self.cfg.rmw_alu == "through":
            # (WP30) rmw_alu: the ALU clocks count through a fetch; the routing clocks
            # (dest_route) and the last need a bus free of fetches; (WP31) the left-out
            # write's slot of a read-only form run as the RMW (dest_route=slot) the same
            r.through = max(0, setup - self.route - 1)
        return r

    def issue_nowrite(self, t: int, bus, queue):
        """grp_read=rmw_slot: the left-out write's slot: the bus runs a fetch in it when the
        queue wants one (queue not None); the EU goes on as after a write in that slot."""
        req = self.req
        req.cycles.pop(0)
        c = None
        if queue is not None:
            addr, width, data = queue.issue(t)
            queue.slot_fetch = self.cfg.grp_read == "rmw_slot_any"
            c = bus.start(t, "fetch", addr, width, data, owner=queue)
        if self.cfg.slot_latch and self.cfg.wlatch:
            # (WP31) slot_latch: the slot fills the data latch as the write it stands for
            self.wlatch_until = max(self.wlatch_until, t + self.cfg.wlatch)
        ww = self.cfg.write_wait
        if c is None and self.cfg.slot_idle == "eu":
            # (WP31) slot_idle=eu: no cycle in the slot, no bus cycle: the EU goes on sidle
            # clocks after the slot clock, whatever the waits
            req.done_at = t + self.cfg.c(self.ccls, "sidle")
        elif ww in ("end", "mem_end"):
            # as after a memory write in this slot: the end of a cycle of the bus's length
            req.done_at = (c.end if c is not None else t + bus.length("write") - 1) + 1
        else:
            req.done_at = t + 1
        return c

    def issue(self, t: int, bus):
        req = self.req
        kind, addr, width = req.cycles.pop(0)
        c = bus.start(t, kind, addr, width, self.regs.get("AW", 0), owner=self)
        req.issued.append(c)
        if addr >= SFR_PAGE and kind == "write" and self.rfc is not None:
            self.rfc.write(self.sfr, t, c)   # (WP23) the RFM store (refresh.py)
        if self.cfg.wlatch and (kind == "write" or kind == "io_write"
                                and self.cfg.str_io_latch == "write"
                                and req.cls in STRING_CLASSES):
            # (WP70) str_io_latch=write: a string form's I/O write's datum (the element's read
            # data) is in the data latch, held from its issue as a memory write's
            self.wlatch_until = max(self.wlatch_until, t + self.cfg.wlatch)
        if not req.cycles and req.detached:
            if kind == "io_write":
                self.latch_until = c.end + 1    # the latches are free once the cycle ends
            self.retick = True                  # a start it blocked may go on this clock
            self._promote(t)                    # nobody waits on it: the slot moves on
            return c
        if not req.cycles and not kind.endswith("read"):
            ww = self.cfg.write_wait
            if ww == "mem_end":
                req.done_at = t if kind.startswith("io") else c.end + 1
            else:
                req.done_at = c.end + 1 if ww == "end" else t + 1
        return c

    def complete(self, c, t: int):
        """A read cycle of the current request ended at t-1."""
        if not c.kind.endswith("read"):
            return                              # a write's release was set at its issue
        if self.cfg.wlatch and self.cfg.wlatch_src == "write_imm_read":
            # read data (memory or I/O) enters the data latch on its delivery clock
            # (WP19) dest_route=d0ro_latch: a routed read-only form's datum enters it
            # after the routing clocks (the result passes the ALU toward the memory side)
            late = self.route if self.cfg.dest_route == "d0ro_latch" and self.ro else 0
            self.wlatch_until = max(self.wlatch_until, t + late + self.cfg.wlatch)
        req = self.own if self.own is not None else self.req
        if req is not None and c in req.issued and not req.cycles and c is req.issued[-1]:
            req.done_at = t + self.cfg.data_ready
