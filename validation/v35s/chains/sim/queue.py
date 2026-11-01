"""Prefetch queue: six bytes of physical storage, with a word-fetch request rule.

Storage. The queue holds at most QUEUE_BYTES = 6 bytes. The opcode latch (the
decoder's IR, decoder.py) is a seventh byte outside it: a byte loaded into
the IR leaves the queue. A byte the decoder has taken has left the queue's
storage, although with take_commit=at_end the request rule counts its slot
until the take step ends (occupancy). `check()` runs at the end of every
clock, after that clock's takes and delivery, and raises QueueOverflow if the
queue holds more than six bytes then; a request rule that over-fills the
queue is therefore not a model of this chip, and the fitter scores every
run it breaks as a miss.

Occupancy. `release` picks how taken bytes free room: "byte" frees each byte
as it is committed; "first" frees a fetched word's two slots when its first
byte is taken; "last" when its last byte is.

Request rule (options in sim/config.py): the room the rule sees is
6 - occupancy - 2 for a fetch in flight (an in-flight word reserves its two
slots); with room_ir=True the IR is a seventh slot the rule counts as well
(7 - occupancy - IR byte - in-flight 2), so an empty IR is room; with
room_ir="arrival" only on a word's delivery clock (the clock right after a
fetch ended, while the bus unit is still in its fetch run). A word
delivered on clock t is counted from t. request_eval: the request is
evaluated on every clock ("every_clock") or only on clocks the queue changes,
a take committed (take_commit) or a word delivered ("on_change"; an EU start
that empties the IR is not a queue change), keeping its value in between while the room
lasts. request_hold: a raised request lapses
as soon as the room is gone ("lapse") or is held until it is issued ("hold").

Back-to-back decision. On a fetch's last clock the bus unit already knows
whether it runs another fetch next: the request flag as it stands at the end
of that clock (the in-flight word counted; with request_eval=on_change the
flag is cleared when a fetch issues and raised again only on a queue change);
`b2b_at` records the clock after it. With start_sync=b2b the
EU does not start an instruction on that clock (eu.py): the bus unit is
committed to the next fetch. The fetch itself is still decided on the free
clock, from the state after that clock's takes.

A fetch is wanted when the room is >= 2 bytes (a word). `requested_at` dates
the current request for the arbiter.

Storage alternatives (each physical; the overflow assert stays):

- word_latch: a bus-side word latch. A delivered word sits in a 2-byte latch
  on its delivery clock and enters the queue at the end of that clock if the
  queue then holds at most 6 bytes with it, else it stays latched until it
  fits (the decoder may take its bytes through the latch when the queue is
  empty). The queue proper never holds more than 6 bytes; a word delivered
  while the latch is still full raises QueueOverflow. "counted": the request
  rule counts the latched bytes as queue bytes; "uncounted": it does not.
- word_latch="port": a single-ported queue. A clock on which the decoder
  reads a byte (a take or the IR load) cannot also write the queue: a word
  delivered on such a clock waits in the latch, uncounted by the request
  rule, until the end of the first clock without a read (and while the queue
  cannot take it). On a delivery clock without a read the word goes straight
  in and is counted at once.
- word_latch="byte": the same with a byte-wide write port and a one-byte
  latch: on a clock the decoder reads, the delivered word's first byte goes
  into the queue and only its second byte waits (uncounted) until the end of
  the first clock without a read. The queue proper still never exceeds 6.
- word_latch="byte_d": as byte, but the rule counts a latched byte that is
  still waiting after its delivery clock.
- latch_hold: no fetch starts while a byte delivered on an earlier clock is
  still latched and cannot go in this clock (the decoder holds the port, or
  the queue is full); the request itself stays raised.
- latch_read: which decoder clocks hold the write port: any clock a byte is
  read ("read"), only clocks a take commits or the IR loads ("commit"), or
  only clocks the IR loads ("ir").
- room_ir="idle": the IR counts as a seventh slot whenever the decoder has
  no operand bytes of the current instruction outstanding (it is not
  mid-take, so an empty IR will load from the queue); "arrival_idle": on
  those clocks and on every delivery clock (room_ir="arrival").
- room_ir="arrival_ready": as arrival_idle, but on a non-delivery clock the
  IR counts only once the loader may load it: no operand bytes outstanding
  and the class's nx clocks after the last operand take have passed.
- request_sample="before_take": the request rule sees the occupancy, IR and
  latch as they stood at the start of the clock (after the clock's delivery,
  before its takes and IR load); the clocks it is re-evaluated on are those
  of request_eval as before.
- request_eval="on_take": re-evaluated only on clocks a byte leaves the queue
  (a take commits or the IR loads); a delivery alone does not re-evaluate it.
- abort_fetch="one_word": on a clock the EU starts an instruction, takes an
  operand byte and the IR loads, a fetch request that sees room for exactly one
  word is answered by an aborted cycle of 3 clocks: nothing on the bus, nothing
  delivered, the request dropped; the EU's take sync waits for it as for a fetch.
  "retry": as one_word, and the request is raised again when the next bus cycle
  (a data cycle) ends.
- modrm_commit (decoder.py): a ModR/M byte leaves the occupancy when taken.
"""

from __future__ import annotations

from collections import deque

QUEUE_BYTES = 6            # physical queue storage, not a parameter
# (WP104) room_ir_pre=test: the classes whose pre clocks before the first operand take leave
# the IR counted as room (TEST r,r)
ROOM_IR_PRE_CLASSES = ("test_reg",)
WORD = 2



class QueueOverflow(RuntimeError):
    pass


class Queue:
    def __init__(self, cfg, code: bytes, chain_base: int, start_offset: int):
        self.cfg = cfg
        self.code = code
        self.base = chain_base
        self.fetch_addr = chain_base & ~1
        self.skip_before = chain_base + start_offset   # bytes before the first LS are dropped
        self.bytes: deque = deque()     # (linear address, usable clock)
        self.words: dict = {}           # word address -> [bytes remaining, released]
        self.inflight = False
        self.completed = 0              # fetches delivered so far
        self.uncommitted: list[int] = []
        self.requested_at: int | None = None   # first clock the current request was raised
        self.arrived_t: int | None = None       # clock the last word was delivered
        self.removed_t: int | None = None       # last clock the decoder removed a byte
        self.held = False                       # request_hold=hold: a raised request
        self.flag = False                       # the request flag (request_eval=on_change)
        self.decoder = None                     # set by the decoder (IR occupancy)
        self.b2b_at: int | None = None          # clock after a fetch whose last clock saw room
        self.disp_t: int | None = None          # (WP28) latch_disp: a displacement's take clock
        self.dropped = False                    # refresh_drop: a raised request a refresh beat
        self.io_held: int | None = None         # (WP19) io_ir_hold: raised on this I/O issue clock
        self.after_refresh = None               # refresh_after: the clock after a refresh that beat a request
        self.beat_eval = False                  # (WP40) refresh_reissue: it was beaten on an evaluation clock
        self.refresh_beaten = False             # (WP23) halt_refresh: a refresh beat a request before HALT
        self.drop_hold = True                   # (WP23) refresh_reraise=unit: the dropped request waits for the unit
        self.lost_start = None                  # (WP35) refresh_lost=start: the clock a request was lost
        self.lost_eval = None                   # (WP35) the start clock it is evaluated again on
        self.lost_after = None                  # (WP35) in HALT: the clock after the halt status
        self.halted = False                     # (WP23) halt_refresh: the EU is halted (eu.py)
        self.peak = 0                           # most bytes ever held at a clock's end
        self.latched = 0                        # word_latch: bytes of the last word still latched
        self.read_t: int | None = None          # last clock the decoder read a byte (port)
        self.ir_t: int | None = None            # last clock the IR loaded
        self.take_t: int | None = None          # last clock the EU took an operand byte
        self.snap: tuple | None = None          # request_sample=before_take: (t, occ, ir, latched)
        self.start_t: int | None = None         # last clock the EU started an instruction
        self.starts = 0                         # instructions started (the first LS is two)
        self.abort_end: int | None = None       # abort_fetch: last clock of an aborted cycle
        self.abort_t: int | None = None         # (WP21) first clock of the last aborted cycle
        self.retry_at: int | None = None        # (WP21) abort_unit=loop: re-raise on this clock
        self.retry = False                      # abort_fetch=retry: re-raise after the next bus cycle
        self.abort_ref = False                  # (WP37) refresh_abort_retry=next: aborted under a refresh
        self.retry_loop = False                 # (WP21) abort_unit=loop: a multiply/divide's
        self.slot_fetch = False                 # the fetch in flight runs in a left-out write's slot
        self.slot_word = False                  # the last word delivered was such a fetch's
        self.fetch_len = 3                      # a fetch's clocks (machine.py sets the waits)
        self.shift_held = False                 # (WP21) count_latch: a shift holds the port
        self.shift_until: int | None = None     # ... until the end of this clock
        self.io_abort = False                   # (WP22) io_take=abort: an aborted cycle is due
        self.mate_t: int | None = None          # (WP26) modrm_mate: the ModR/M's word-mate taken
        self.nop_held: int | None = None        # (WP32) nop_hold: held until a start after this
        self.latch_full = False                 # (WP32) the latched byte waited behind a full queue
        self.latch_in_t: int | None = None      # (WP32) the clock such a byte went into the queue
        self.qport_t: int | None = None         # (WP32) modrm_port: last clock a commit held the port
        self.eu = None                          # (WP39) refresh_io_run (machine.py sets it)
        self.io_run_at: int | None = None       # (WP39) refresh_io_run: the committed fetch's clock
        self.gdisp_until: int | None = None     # (WP61) grp_disp: no fetch before this clock
        self.t4_at: int | None = None           # (WP41) refresh_beat_t4: the committed fetch's clock
        self.discard = False                    # (WP55) the fetch in flight at a flush: its word is dropped
        self.flush_t: int | None = None         # (WP55) the clock of the last flush
        self.flush_held: int | None = None      # (WP55) flush_hold: no fetch request from this clock to the flush
        self.str_held: int | None = None        # (WP67) str_hold: no fetch request before this clock
        self.take_hold: int | None = None       # (WP94) bf_imm_hold: armed on this clock
        self.hold_from: int | None = None       # (WP94) the take that started it
        self.str_raise: int | None = None       # (WP76) str_fetch: raise a retried request on this clock
        self.xfer_abort = False                 # (WP72) xfer_abort: a transfer's aborted cycle runs
        self.lea_ea: tuple | None = None        # (WP72) lea_room: LDEA's EA clocks (first, end)
        self.odd_xfer: int | None = None        # (WP76) xfer_odd: a taken transfer at an odd address started here
        self.odd_fed: bool | None = None        # (WP76) ... a fetch was on the bus on that clock
        self.odd_nt = False                     # (WP81) xfer_nt: the hold is a not-taken transfer's
        self.odd_until: int | None = None       # (WP81) ... and ends on this clock
        self.pb_start = None                    # (WP86) page_b2b: the form it was applied for
        self.pr_start = None                    # (WP86) page_run: the form committed for
        self.nb_start = None                    # (WP89) xfer_nt_b2b: the form committed for
        self.nb_at: int | None = None           # (WP89) ... the committed fetch's issue clock
        # options read on every clock, looked up once
        self._byte_release = cfg.release == "byte"
        self._ported = cfg.word_latch in ("port", "byte", "byte_d")
        self._uncounted = cfg.word_latch in ("uncounted", "port", "byte", "byte_d")
        self._byte_d = cfg.word_latch == "byte_d"
        self._before_take = cfg.request_sample == "before_take"

    def preload(self, words: int):
        """(WP24) prelude_tail=segs: the queue holds `words` words from the fetch address on
        at clock 0 (the slow POP PSW before the segment loads leaves it full)."""
        for _ in range(words):
            a = self.fetch_addr
            kept = [b for b in (a, a + 1) if b >= self.skip_before]
            for b in kept:
                self.bytes.append((b, 0))
            self.words[a] = [len(kept), False]
            self.fetch_addr += 2
            self.completed += 1

    def byte_at(self, addr: int) -> int:
        k = addr - self.base
        return self.code[k] if 0 <= k < len(self.code) else 0x90

    # Storage ---------------------------------------------------------------

    def _imm16(self, t) -> bool:
        """(WP40) room_ir_imm=none: while a register form with a two-byte immediate (class
        imm, MOV r16,imm16) runs, room_ir's idle part (the IR as a seventh slot when the decoder
        is not mid-take) is not counted."""
        eu = self.eu
        return (self.cfg.room_ir_imm == "none" and eu is not None
                and getattr(eu, "cls", None) == "imm" and eu.imm_bytes == 2)

    def occupancy(self) -> int:
        """Slots in use: queued bytes plus taken-but-uncommitted ones (or whole words)."""
        if self._byte_release:
            return len(self.bytes) + len(self.uncommitted)
        return sum(WORD for n, released in self.words.values() if not released)

    def stored(self) -> int:
        """Bytes physically in the queue (a taken byte has left it; latched bytes are not in it)."""
        return len(self.bytes) - self.latched

    def check(self, t: int):
        latched = self.latched
        if (latched and len(self.bytes) <= QUEUE_BYTES
                and not (self._ported and self._port_busy(t))):
            if self.latch_full:
                self.latch_in_t = t             # (WP32) latch_start: it went in on t
            self.latched = latched = 0          # the latched word enters the queue
        if latched and len(self.bytes) > QUEUE_BYTES:
            self.latch_full = True              # (WP32) it waits behind a full queue
        elif not latched:
            self.latch_full = False
        n = len(self.bytes) - latched           # stored()
        if n > self.peak:
            self.peak = n
        if n > QUEUE_BYTES or latched > WORD:
            raise QueueOverflow(f"queue holds {n} bytes at clock {t}")

    def begin_clock(self, t: int):
        """After the clock's delivery, before the EU: the state request_sample=before_take sees."""
        if self.cfg.request_sample != "before_take":
            return                              # only room() reads it, and only then
        self.snap = (t, self.occupancy(), self._ir_full(), self._latched_now(t))

    def _port_busy(self, t: int | None) -> bool:
        """The decoder holds the queue's write port on t (word_latch port/byte, latch_read)."""
        if self.cfg.latch_read == "commit":
            if self.cfg.modrm_port and self.arrived_t != t:
                # (WP32) modrm_port: a ModR/M byte's commit (into the decoder's ModR/M
                # latch, modrm_commit=byte) does not hold the port for a byte latched on an
                # earlier clock
                return self.qport_t == t or self.ir_t == t
            return self.removed_t == t
        if self.cfg.latch_read == "ir":
            return self.ir_t == t
        return self.read_t == t

    def _latched_now(self, t: int | None) -> int:
        """Latched bytes the rule sees on t: with word_latch=port a word delivered on t
        is latched only if the decoder reads on t (else it went straight in)."""
        if (self._ported and self.latched and t is not None
                and self.arrived_t == t and not self._port_busy(t)):
            return 0
        if self._byte_d and t != self.arrived_t:
            return 0                            # counted (as a queue byte) after its delivery clock
        if self.slot_word and t == self.arrived_t:
            return 0                            # a slot fetch's word (grp_read): counted at once
        return self.latched

    # Fetch side ------------------------------------------------------------

    def _ir_full(self) -> bool:
        return self.decoder is not None and self.decoder.ir is not None

    def room(self, t: int | None = None) -> int:
        """Free bytes as the request rule counts them."""
        cfg = self.cfg
        occ, ir, latched = self.occupancy(), self._ir_full(), self._latched_now(t)
        if (self._before_take and self.snap is not None and t is not None
                and self.snap[0] == t):
            _, occ, ir, latched = self.snap
        used = occ + (WORD if self.inflight else 0)
        if self._uncounted and not (cfg.latch_midtake and latched and self.decoder is not None
                                    and self.decoder.need > 0) and not (
                cfg.latch_disp and latched and t is not None and self.disp_t == t):
            used -= latched                     # latch_midtake: counted while mid-take
        size = QUEUE_BYTES
        if cfg.room_ir is True or (cfg.room_ir in ("arrival", "arrival_idle", "arrival_ready")
                                   and t is not None and t == self.arrived_t) or (
                cfg.room_ir in ("idle", "arrival_idle") and self.decoder is not None
                and (self.decoder.need == 0 or self._pre_room(t)) and not self._imm16(t)) or (
                cfg.room_ir == "arrival_ready" and self.decoder is not None
                and self.decoder.need == 0 and (t is None or t >= self.decoder.ready_at)):
            if (self.decoder is not None and (self.decoder.ir_hold
                    and (self.decoder.need == 0 or cfg.ea_ir_room and t is not None
                         and self.decoder.ea_end is not None and t < self.decoder.ea_end)
                    or self.decoder.lea_wait and self.decoder.need > 0 and cfg.ea_ir_room
                    and t is not None and self.decoder.ea_end is not None
                    and t < self.decoder.ea_end)):
                # (WP28) ir_load: the IR is no seventh slot; (WP30) ea_ir_room: nor while
                # the form runs its EA clocks, before the displacement's take; (WP92)
                # lea_slot=ea: nor while a displaced LDEA runs them (it holds no IR load)
                used += ir
            elif not (cfg.room_ir_ready and not ir and self.decoder is not None and t is not None
                    and self.decoder.ready_at > t + self.fetch_len):
                size += 1                       # room_ir_ready: an IR that cannot load is no room
                used += ir
        if (cfg.lea_room == "ir" and ir and size > QUEUE_BYTES and t is not None
                and self.lea_ea is not None and self.lea_ea[0] <= t < self.lea_ea[1]):
            used -= 1           # (WP72) lea_room=ir: during LDEA's EA clocks after its last
                                # operand byte, the IR's opcode is not counted (config.py)
        if cfg.modrm_mate and t is not None and t == self.arrived_t == self.mate_t:
            used += 1           # (WP26) modrm_mate: the ModR/M's word is not free yet
        if (self.cfg.arrive_partial and t is not None and t == self.arrived_t
                and t == self.removed_t):
            used -= 1           # the delivered word's second byte is counted a clock later
        return size - used

    def _pre_room(self, t: int | None) -> bool:
        """(WP104) room_ir_pre=test: the IR counts as the seventh slot while the running TEST r,r
        (ROOM_IR_PRE_CLASSES) has taken none of its operand bytes (its pre clocks)."""
        return (self.cfg.room_ir_pre == "test" and self.decoder.fresh
                and self.decoder.cls in ROOM_IR_PRE_CLASSES)

    def counted(self, t: int | None = None) -> int:
        """Queue bytes as the request rule counts them (6 minus its room)."""
        return QUEUE_BYTES - self.room(t)

    def free(self, t: int | None = None) -> int:
        return self.room(t)

    def end_clock(self, t: int, bus):
        """End of clock t: storage check; on a fetch's last clock, the back-to-back decision."""
        self.check(t)
        c = bus.current
        if c is not None and c.kind == "fetch" and c.end == t and self._raised(t):
            self.b2b_at = t + 1
            if self.cfg.page_run != "none" and self.eu.page_active():
                self.pr_start = self.eu.start_clock     # (WP86) page_run: its one commitment
        elif (c is not None and c.kind == "fetch" and c.end == t
              and self.after_refresh == c.start and self.cfg.refresh_io_run != "none"
              and self._io_form() and self.latched == 0
              and (self.room(t) >= 0 if self.cfg.refresh_io_run == "pair"
                   else self.eu.cls == "out" and self.room(t) + self._taking() >= 1)
              and not (self.eu.req is not None and self.eu.req.posted >= c.start
                       and self.cfg.refresh_pair_post == "before")):
            # (WP85) refresh_pair_post=before: not when the OUT posted on the fetch's issue clock
            # (WP39) refresh_io_run=pair: while an IN or OUT waits for its I/O, the fetch a
            # refresh beat is followed by a second one the bus unit commits to back to back;
            # (WP58) pair_out: beside an OUT only, with a byte of room left counting the byte
            # the decoder still takes
            self.b2b_at = self.io_run_at = t + 1
        elif (c is not None and c.kind == "fetch" and c.end == t and self.cfg.page_b2b != "none"
              and self._page_b2b(t, c.start)):
            self.b2b_at = self.io_run_at = t + 1    # (WP86) page_b2b: committed back to back
        elif (c is not None and c.kind == "fetch" and c.end == t and self.cfg.page_run != "none"
              and self.eu.page_active() and self.room(t) >= WORD
              and self.pr_start != self.eu.start_clock):
            self.b2b_at = self.io_run_at = t + 1   # (WP86) page_run: evaluated on its last clock
            self.pr_start = self.eu.start_clock
        elif (c is not None and c.kind == "fetch" and c.end == t
              and self.cfg.xfer_nt_b2b == "decide" and self._nt_b2b(t)):
            self.b2b_at = self.io_run_at = self.nb_at = t + 1   # (WP89) xfer_nt_b2b
            self.nb_start = self.eu.start_clock

    def _nt_b2b(self, t: int) -> bool:
        """(WP89) xfer_nt_b2b=decide: on the last clock of a fetch while a short conditional
        transfer not taken (base class branch_short) runs its decide step (its condition
        tested), a byte of room commits the bus unit to one more fetch back to back, the latch
        taking the word's other byte; once per form, nothing latched, the queue able to hold
        the word."""
        eu = self.eu
        if (eu is None or eu.halted or getattr(eu, "cls", None) != "branch_short"
                or self.decoder is None or self.decoder.need
                or self.nb_start == eu.start_clock):
            return False
        if not (eu.k < len(eu.steps) and eu.steps[eu.k][0] == "decide"):
            return False
        if self.latched or self.room(t) < 1 or self.stored() + 2 * WORD > QUEUE_BYTES + 1:
            return False
        return True

    def _page_b2b(self, t: int, bus_start: int) -> bool:
        """(WP86) page_b2b=reg: on the last clock of a fetch that ran at a 0F register form's
        last operand take (or issued on the clock after it), the form commits the bus unit to
        one more fetch back to back with a byte of room left (the word latch takes the other),
        once per form; not when the next opcode was in the IR before that fetch issued, nor when
        the queue could not take the word before the form's clocks end."""
        eu = self.eu
        if (not getattr(eu, "page_reg", False) or eu.halted or self.decoder is None
                or self.decoder.need or self.pb_start == eu.start_clock):
            return False
        if self.latched or self.room(t) < 1 or self.take_t is None:
            return False
        if bus_start > self.take_t + 1 and not (
                self.cfg.page_b2b_win == "run" and self._after_take_fetch(bus_start)):
            return False                         # (WP94) page_b2b_win=run: or the fetch issued
                                                 # back to back after the one running at the take
        if self.decoder.ir is not None and (self.ir_t is None or self.ir_t <= bus_start):
            return False
        if self.stored() + 2 * WORD > QUEUE_BYTES + 1 and not (
                self.decoder.ir is None and eu.resume <= t):
            return False
        self.pb_start = eu.start_clock
        return True

    def _after_take_fetch(self, bus_start: int) -> bool:
        """(WP94) page_b2b_win=run: the fetch issued on bus_start followed, back to back, a fetch
        that was on the bus on the form's last operand take, the take after that fetch's issue
        clock (its wait or last clock: a take on the issue clock leaves the window as it was)."""
        bus = self.eu.bus if self.eu is not None else None
        if bus is None:
            return False
        prev = [c for c in bus.cycles[-4:] if c.kind == "fetch" and c.end == bus_start - 1]
        return bool(prev) and prev[-1].start < self.take_t <= prev[-1].end

    def _taking(self) -> int:
        """(WP58) refresh_io_run=pair_out: 1 while the decoder still has a byte to take from
        the queue (an empty IR, or operand bytes outstanding), else 0."""
        d = self.decoder
        return int(d is not None and (d.ir is None or d.need > 0))

    def _io_form(self) -> bool:
        """(WP39) the EU runs an IN or OUT whose I/O cycle has not issued."""
        eu = self.eu
        if eu is None or eu.halted or getattr(eu, "cls", None) not in ("out", "in"):
            return False
        r = eu.req
        return not (r is not None and r.cycles and r.issued) and not (
            r is not None and not r.cycles)

    def _raised(self, t: int) -> bool:
        """The request flag as it stands at the end of t (no side effects)."""
        if self._nop_held():
            return False
        if not self._evaluates(t):
            want = self.flag and self.room(t) >= WORD
        else:
            want = self.room(t) >= WORD
        return want or (self.cfg.request_hold == "hold" and self.held)

    def _evaluates(self, t: int) -> bool:
        """Whether the request flag is re-evaluated on t (request_eval)."""
        mode = self.cfg.request_eval
        if t == self.lost_eval:
            return True                  # (WP35) refresh_lost=start: the lost request
        if self.refresh_beaten and self.halted:
            return True                  # (WP23) halt_refresh=run: no takes mark changes
        if (self.cfg.room_ir_pre != "none" and t == self.start_t and self.decoder is not None
                and self._pre_room(t)):
            return True                  # (WP104) room_ir_pre: the start emptied the IR, the room
        if mode == "on_change":
            return t in (self.removed_t, self.arrived_t, 0)
        if mode == "on_take":
            return t in (self.removed_t, 0)
        return True

    def requesting(self, t: int) -> bool:
        """Whether a fetch request is raised on t (bus state aside).

        request_eval=on_change: the request flag is re-evaluated only on clocks
        the queue itself changes (a take committed, an IR load, or a word
        delivered) and on the first clock; otherwise it keeps its last value.
        """
        if self.io_run_at == t or self.t4_at == t:
            want = True                  # (WP39) refresh_io_run: committed back to back;
                                         # (WP41) refresh_beat_t4: committed a clock late
        elif self.dropped and self.cfg.refresh_reraise in ("loop_end", "unit") and self.drop_hold:
            want = False                 # (WP17) lost to a refresh until the EU raises it again
        elif not self._evaluates(t):
            want = self.flag and self.room(t) >= WORD      # a raised request still needs the room
        else:
            want = self.room(t) >= WORD
        self.flag = want
        if self.cfg.request_hold == "hold":
            self.held = self.held or want
            want = self.held
        return want

    def latch_blocks(self, t: int) -> bool:
        """latch_hold: a byte delivered before t is still latched and cannot go in on t."""
        if not (self.cfg.latch_hold and self.latched and self.arrived_t != t):
            return False
        return self._port_busy(t) or len(self.bytes) > QUEUE_BYTES

    def _nop_held(self) -> bool:
        """(WP32) nop_hold: a request kept raised on a fetch issue clock where a NOP started
        waits for the next instruction's start (start_t moves past the held clock)."""
        if self.nop_held is None:
            return False
        if self.start_t is not None and self.start_t > self.nop_held:
            self.nop_held = None
            return False
        return True

    def wants_fetch(self, t: int) -> bool:
        if self.str_raise is not None and t >= self.str_raise:
            self.str_raise = None            # (WP76) str_fetch=hold, CW = 0: the request an
            if self.retry:                   # aborted cycle left is raised again in the exit
                self.retry = False
                self.flag = self.room(t) >= WORD
        raised = self.requesting(t)          # evaluated even while a fetch is on the bus
        if (self.flush_held is not None and t >= self.flush_held
                and self.decoder is not None and self.decoder.need == 0):
            raised = False                   # (WP55) flush_hold: a taken transfer runs (its
                                             # operand bytes all taken)
        if raised and self._odd_held(t):
            raised = False                   # (WP76) xfer_odd=idle
        if raised and self.str_held is not None and t < self.str_held:
            raised = False                   # (WP67, F24) str_hold: a compare's result clocks
        if raised and self.take_hold is not None and self._take_held():
            raised = False                   # (WP94) bf_imm_hold: a half-taken width word
        if raised and self._nop_held():
            raised = False
        want = (raised and not self.inflight and not self.latch_blocks(t)
                and not self.shift_held)
        if want and self.requested_at is None:
            self.requested_at = t
        if not want and not self.inflight:
            self.requested_at = None
        return want

    def _take_held(self) -> bool:
        """(WP94) bf_imm_hold=word: from the first operand take after the hold was armed (that
        clock included) no fetch request is raised, nor a back-to-back fetch committed after it
        run; one requested before that take still runs."""
        if self.hold_from is None:
            if self.take_t is None or self.take_t < self.take_hold:
                return False
            self.hold_from = self.take_t
        return not (self.requested_at is not None and self.requested_at < self.hold_from)

    def asked(self, t: int) -> bool:
        """A request raised on t that is not yet on the bus (take_sync=pending)."""
        if self.inflight:
            return self.room(t) >= WORD or (self.cfg.request_hold == "hold" and self.held)
        return self.requesting(t) and not self._odd_held(t)

    def issue(self, t: int | None = None, mem_waiting: bool = False) -> tuple[int, str, int]:
        """A fetch goes on the bus on t. (WP26) request_reissue: on a clock the flag is
        evaluated, it is evaluated again after the issue (the in-flight word reserved);
        no_mem: not while a memory data request waits in the slot (mem_waiting)."""
        addr = self.fetch_addr
        self.inflight = True
        self.dropped = False                     # refresh_drop (arbiter.py)
        self.lost_start = None                   # (WP35) refresh_lost: the request is served
        self.held = False
        self.flag = False
        mode = self.cfg.request_reissue
        if (mode != "none" and t is not None and not (mode == "no_mem" and mem_waiting)
                and (self._evaluates(t) or t == self.after_refresh and self.beat_eval
                     and self.cfg.refresh_reissue == "keep")):
            # (WP40) refresh_reissue=keep: the fetch a refresh beat is evaluated again on its
            # issue after the refresh when the clock the refresh took the bus evaluated it
            self.flag = self.room(t) >= WORD
        self.requested_at = None
        self.fetch_addr = (addr | 1) + 1         # (WP55) after an odd target: the next word
        return addr, "word", self.byte_at(addr) | (self.byte_at(addr + 1) << 8)

    def triple(self, t: int) -> bool:
        """abort_fetch: on t the EU started an instruction, took an operand byte and the
        IR loaded (three queue reads around one clock). Never inside the first LS (its
        two instructions): their queue history is the model's stand-in for the
        prelude (machine.py)."""
        return (self.start_t == t and self.take_t == t and self.ir_t == t
                and self.starts > 2)

    def abort(self, t: int):
        """abort_fetch: the request is answered by an aborted cycle (BASE clocks, nothing on
        the bus, nothing delivered); the take sync counts it like a fetch."""
        self.inflight = True
        self.held = False
        self.flag = False
        self.requested_at = None
        self.abort_end = t + 2
        self.abort_t = t
        self.retry = self.cfg.abort_fetch == "retry"
        self.retry_loop = False
        self.abort_ref = False

    def retry_after(self, t: int, kind: str = ""):
        """abort_fetch=retry: a bus cycle ended after an aborted cycle: the request is
        raised again (it stays raised while the room lasts, request_eval=on_change).
        (WP37) refresh_abort_retry=next: a request aborted under a refresh waits for the
        end of the next cycle after that refresh (the refresh's own end does not count)."""
        if self.abort_ref and kind == "refresh":
            self.abort_ref = False
            return
        self.abort_ref = False
        if self.retry and not self.retry_loop:   # (WP21) abort_unit=loop: at the loop's exit
            self.retry = False
            self.flag = self.room(t) >= WORD

    def abort_done(self, t: int | None = None):
        self.inflight = False
        self.abort_end = None
        self.completed += 1
        if self.xfer_abort and t is not None:
            # (WP72) xfer_abort=word: a transfer's request is raised again on the aborted
            # cycle's end (no data cycle of its own follows to raise it, abort_fetch=retry)
            self.xfer_abort = False
            self.flag = self.room(t) >= WORD

    def refill_target(self) -> int:
        """Delivered-fetch count once the room present now has been refilled."""
        room = QUEUE_BYTES - self.occupancy() - (WORD if self.inflight else 0)
        words = room // WORD if room >= WORD else 0
        return self.completed + self.inflight + words

    def flush(self, t: int, addr: int):
        """(WP55) a taken transfer: the queue's bytes (and a latched byte) are discarded, the
        fetch pointer is the target's address (an odd target: a fetch at that address, its
        one byte), the word of a fetch still in flight is dropped when it arrives. A queue
        change: the request is evaluated on t (request_eval)."""
        self.bytes.clear()
        self.words.clear()
        self.uncommitted.clear()
        self.latched = 0
        self.latch_full = False
        self.discard = self.inflight and self.abort_end is None
        self.fetch_addr = addr
        self.flag = False
        self.held = False
        self.requested_at = None
        self.removed_t = t
        self.flush_t = t
        self.flush_held = None
        self.odd_xfer = self.odd_fed = None
        self.odd_nt = False

    def _odd_held(self, t: int) -> bool:
        """(WP76) xfer_odd=idle: an odd-address jump that started with no fetch on the bus
        raises no request from the clock after its start, once its operand bytes are taken."""
        return (self.odd_xfer is not None and t > self.odd_xfer
                and self.decoder.need == 0 and (self.odd_nt == "dbnz" or not self._odd_fed())
                and not (self.odd_until is not None and t >= self.odd_until))

    def _odd_fed(self) -> bool:
        """(WP76) xfer_odd: whether a fetch was on the bus (in flight, or issued) on the clock
        the odd-address transfer started (read from the clock after it on)."""
        if self.odd_fed is None:
            s = self.odd_xfer
            self.odd_fed = any(c.kind == "fetch" and c.start <= s <= c.end
                               for c in self.eu.bus.cycles[-3:])
        return self.odd_fed

    def arrive(self, addr: int, usable: int, t: int | None = None):
        self.inflight = False
        self.slot_word, self.slot_fetch = self.slot_fetch, False
        self.completed += 1
        if self.discard:
            self.discard = False                # (WP55) fetched before a flush: dropped, no
            return                              # queue change
        self.arrived_t = t
        # (WP55) a fetch at an odd address (a transfer's odd target) brings its one byte
        kept = [a for a in ((addr,) if addr & 1 else (addr, addr + 1)) if a >= self.skip_before]
        if self.cfg.word_latch != "none" and kept:
            if self.latched:
                raise QueueOverflow(f"word {addr:05X} delivered into a full latch at clock {t}")
            self.latched = 1 if self.cfg.word_latch in ("byte", "byte_d") else len(kept)
        for a in kept:
            self.bytes.append((a, usable))
        if kept:
            self.words[addr & ~1] = [len(kept), len(kept) < 2 and self.cfg.release == "first"]

    # Decoder side ----------------------------------------------------------

    def available(self, t: int) -> int:
        n = 0
        for _, usable in self.bytes:
            if usable > t:
                break
            n += 1
        return n

    def take(self, t: int) -> int:
        """Pop the next byte (caller checked available); returns its address."""
        addr, _ = self.bytes.popleft()
        self.latched = min(self.latched, len(self.bytes))   # taken through the latch
        self.read_t = t
        if self.cfg.take_commit == "at_end":
            self.uncommitted.append(addr)
        else:
            self.removed_t = t
            self._release(addr)
        return addr

    def commit(self, t: int | None = None):
        if self.uncommitted and t is not None:
            self.removed_t = t                  # the queue changes when the take commits
            self.qport_t = t                    # (WP32) a commit through the queue's port
        for addr in self.uncommitted:
            self._release(addr)
        self.uncommitted.clear()

    def commit_one(self, addr: int, t: int):
        """Commit one taken byte now (modrm_commit=byte)."""
        if addr in self.uncommitted:
            self.uncommitted.remove(addr)
            self.removed_t = t
            self._release(addr)

    def _release(self, addr: int):
        word = self.words[addr & ~1]
        word[0] -= 1
        if self.cfg.release == "first":
            word[1] = True
        elif self.cfg.release == "last" and word[0] == 0:
            word[1] = True
        if word[0] == 0:
            del self.words[addr & ~1]
