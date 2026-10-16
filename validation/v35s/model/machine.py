"""Clocked V35S model: bus unit, prefetch queue, refresh and clock divider.

The machine runs in CPU clocks. Each clock it advances the bus cycle in
progress, then lets the bus unit start a new cycle (EU data request, then
refresh, then a fetch), then advances the execution unit (`eu.py`), which
is a generator yielding timing requests:

    ("clocks", n)          busy for n clocks
    ("byte",)              take the next byte from the queue (waits for it)
    ("read", space, address, width)   data read; resumes with the value
    ("write", space, address, width, value)
    ("flush", linear)      discard the queue; fetching restarts at linear
    ("halt",)              stop the EU (bus unit, refresh keep running)

Bus cycles come out as runner.Transaction records with lane-compatible
ticks, flags and data, so `compare_traces` and the timing probes read them
unchanged. Every number that is a fit to silicon lives in `costs.COSTS`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..runner import (FLAG_IO, FLAG_READ, FLAG_REFRESH, FLAG_STROBE, FLAG_UBE_N, FLAG_UNMAPPED,
                      FLAG_MARKER, Transaction)
from .costs import COSTS
from .eu import EU
from .length import length

MARKER_PORT = 0x20
PASS_PORT = 0xFF00
FAIL_PORT = 0xFF02


@dataclass
class Cycle:
    kind: str                 # fetch, read, write, refresh
    space: str                # mem, io
    address: int
    width: int                # 1 or 2 (bytes on the bus)
    value: int = 0            # write data
    start: int = 0            # clock of B1
    length: int = 3           # states
    data: int = 0
    owner: str = "biu"        # biu (fetch), eu, refresh
    start_tick: int = 0
    not_before: int = 0       # clock the bus unit may start it


@dataclass
class Machine:
    memory: dict                     # page number -> bytearray(4096); unmapped reads 0
    x_half: int = 2
    costs: dict = field(default_factory=lambda: dict(COSTS))

    def __post_init__(self):
        self.clock = 0
        self.tick = 0
        self.iram = bytearray(256)
        self.sfr = bytearray(256)
        self.sfr[0xEB] = 0x4E          # PRC: fX/8, RAMEN, TB
        self.sfr[0xE8] = 0xFF          # WTC FFFF: 2 waits + READY everywhere
        self.sfr[0xE9] = 0xFF
        self.sfr[0xE1] = 0xFC          # RFM: refresh on, RFW 2? (reset FCh), RFT 0
        self.sfr[0xFF] = 0xFF          # IDB
        self.queue = []                # (linear address, byte, clock it reaches the EU)
        self.iwr = []                  # the EU's instruction word register: (linear, byte) left
        self.iwr_ready = 0             # clock its current word can be read
        self.preloaded = False         # the register's word was loaded ahead (pre-pop)
        self.iwr_held = False          # operand_hold: the register's word keeps its queue slot
        self.last_load_preload = False # the register's last load was a pre-load
        self.decoded = []              # decode stage: (linear, byte, clock usable) taken ahead of execution
        self.decode_filling = False    # decode stage: refilling up to decode_bytes
        self.insn_start = None         # linear address of the current instruction's opcode
        self.decode_to = None          # decode_mode "ahead": decode bytes below this address
        self.burst = False             # classed decoder: taking words ahead
        self.dec_next = 0xFFFF0        # classed decoder: next instruction start it has not begun
        self.dec_open = 0xFFFF0        # end of the last instruction it began
        self.dec_open_class = "simple"
        self.dec_cur_end = None        # end of the instruction executing (or waited for)
        self.dec_waited = None         # start of the instruction the EU last waited for
        self._last_was_boundary = True # the next byte the EU takes is an opcode
        self.routine = None            # the EU, for its current routine key
        self.end_discount = 0          # clocks the last routine hides of the next opcode load
        self.suspended = False         # prefetch stopped by a decided transfer until its flush
        self.fetch_grant_at = None     # EU-issued fetch request: clock it reaches the bus unit
        self.fetch_credits = self.costs["queue_words"]  # fetches the bus unit may still start
        self.fetch_asked = None        # "ask": the opcode request already signalled
        self.last_word = None          # consumption model: word of the last byte taken
        self._penalty_paid = False
        self.fetch_linear = 0xFFFF0    # next prefetch address
        self.fetch_latch = False       # byte model: fetch eligibility sampled in the running cycle
        self.idle_eligible = None      # byte model: clock the idle bus unit found room for a fetch
        self.cycle: Cycle | None = None
        self.bus_idle_until = 0
        self.pending: Cycle | None = None     # EU request not yet on the bus
        self.trace: list[Transaction] = []
        self.refresh_due = 0
        self.refresh_row = 0
        self.eu = EU(self)
        self.result = None             # pass / fail from the result port
        self.log = None                # set to [] to record (clock, pc, opcode) per instruction
        self.fetch_end = None          # clock the latest code fetch ended
        self.burst_left = 0            # fetch_burst "count": fetches left in this burst
        self.burst_go = False          # fetch_burst "latch": the running fetch's sample found room
        self.loads = None              # set to [] to record (clock, word address) per word load
        self.last_take = None          # (clock, was an opcode) of the last byte taken from the word register
        self.keys = None               # set to {} to record pc -> routine key
        self.steps_used = None         # set to set() to record the step names spent
        self.halted = False
        self._eu_wait = 0
        self._eu_request = None
        self._eu_value = None
        self._reset_hold = self.costs["reset_first_fetch_states"]
        self.refresh_due = self.costs["reset_first_refresh_states"]
        self._gen = self.eu.run()

    # -- clocking ---------------------------------------------------------

    @property
    def ticks_per_clock(self):
        pck = self.sfr[0xEB] & 3
        return 2 * self.x_half * {0: 2, 1: 4, 2: 8}.get(pck, 8)

    def wait_states(self, space, address):
        wtc = self.sfr[0xE8] | (self.sfr[0xE9] << 8)
        if space == "io":
            code = (wtc >> 14) & 3
        else:
            code = (wtc >> (2 * (address >> 17))) & 3 if address < 0xE0000 else (wtc >> 14) & 3
        return min(code, 2)

    # -- memory -----------------------------------------------------------

    def mem_read8(self, linear):
        page = self.memory.get(linear >> 12)
        return page[linear & 0xFFF] if page is not None else 0

    def mem_write8(self, linear, value):
        page = self.memory.get(linear >> 12)
        if page is not None:
            page[linear & 0xFFF] = value & 0xFF

    def mapped(self, linear):
        return (linear >> 12) in self.memory

    # -- bus unit ---------------------------------------------------------

    def _queue_words(self):
        """Word slots in use: queued words plus a fetch in flight. In the
        consumption model a word stays while any of its bytes is unconsumed;
        in the word-register model it leaves when moved to the register. In
        the two-word model the register holds the current word and the next,
        so a word holds its slot until its last byte is consumed."""
        words = {q[0] >> 1 for q in self.queue}
        if self.costs["queue_model"] == "two_word" or (
                self.costs.get("decode_bytes") and self.costs.get("slot_release") == "taken"):
            words.update(b[0] >> 1 for b in self.iwr)
        if self.costs.get("shared_store"):
            # The register and the decoded bytes share the queue's word slots.
            words.update(b[0] >> 1 for b in self.iwr)
            words.update(b[0] >> 1 for b in self.decoded)
        if self.iwr_held and self.iwr:
            # A word loaded for an operand byte frees its slot only when its
            # last byte is taken.
            words.update(b[0] >> 1 for b in self.iwr)
        if self.cycle is not None and self.cycle.kind == "fetch":
            words.add(self.cycle.address >> 1)
        return len(words)

    def _start(self, cycle: Cycle):
        waits = 0 if cycle.kind == "refresh" else self.wait_states(cycle.space, cycle.address)
        if cycle.kind == "refresh":
            waits = min((self.sfr[0xE1] >> 2) & 3, 2)
        cycle.length = 3 + waits
        cycle.start = self.clock
        cycle.start_tick = self.tick
        self.cycle = cycle

    def _finish(self, cycle: Cycle):
        tpc = self.ticks_per_clock
        flags = FLAG_STROBE
        address = cycle.address
        data = 0
        if cycle.kind == "refresh":
            flags = FLAG_REFRESH
            address = (self.refresh_row & 0x1FF) << 9
            self.refresh_row += 1
            begin = cycle.start_tick + self.costs["refresh_tick_offset"] * tpc // 8
        else:
            begin = cycle.start_tick + tpc // 2
            if cycle.space == "io":
                flags |= FLAG_IO
            if cycle.kind in ("fetch", "fetch-discard", "read"):
                flags |= FLAG_READ
            ube = cycle.width == 2 or address & 1
            if not ube:
                flags |= FLAG_UBE_N
            if cycle.space == "mem" and not self.mapped(address):
                flags |= FLAG_UNMAPPED
            if cycle.kind in ("fetch", "fetch-discard", "read"):
                if cycle.space == "io":
                    data = 0
                else:
                    word = address & ~1
                    data = self.mem_read8(word) | (self.mem_read8(word + 1) << 8)
                cycle.data = data
            else:
                value = cycle.value
                if cycle.space == "mem":
                    if cycle.width == 2:
                        self.mem_write8(address, value)
                        self.mem_write8(address + 1, value >> 8)
                        data = value & 0xFFFF
                    else:
                        self.mem_write8(address, value)
                        data = (value & 0xFF) << (8 if address & 1 else 0)
                else:
                    data = value & (0xFFFF if cycle.width == 2 else 0xFF)
                    if cycle.width == 1 and address & 1:
                        data = (value & 0xFF) << 8
                    if address == MARKER_PORT:
                        flags |= FLAG_MARKER
                    if address == PASS_PORT:
                        self.result = 1
                    elif address == FAIL_PORT:
                        self.result = 2
        states = cycle.length - 1
        end = begin + states * tpc + (1 if cycle.kind == "write" else 0)
        self.trace.append(Transaction(begin, address, flags, data, 0, end))
        if cycle.kind == "fetch":
            ready = self.clock + self.costs["fetch_data_delay"]
            if self.costs["queue_model"] == "byte":
                ready = self.clock + self.costs["ripe_delay"]
            if cycle.width == 2:
                self.queue.append((cycle.address, data & 0xFF, ready))
                self.queue.append((cycle.address + 1, data >> 8, ready))
            else:
                byte = (data >> 8) if cycle.address & 1 else data & 0xFF
                self.queue.append((cycle.address, byte, ready))
        elif cycle.owner == "eu":
            if cycle.kind == "read":
                width = cycle.width
                value = (data >> 8) & 0xFF if (width == 1 and cycle.address & 1) else \
                    (data & 0xFF if width == 1 else data)
                self._eu_value = value
            self._eu_request = None
            self._eu_wait = self.costs["eu_after_read" if cycle.kind == "read"
                                       else "eu_after_write"]

    def _queue_bytes(self):
        """Byte model: bytes queued plus the bytes of a fetch in flight."""
        n = len(self.queue)
        if self.cycle is not None and self.cycle.kind == "fetch":
            n += self.cycle.width
        return n

    def _queue_limit(self):
        """Word slots, one more (queue_words_waited) when code fetches have wait states."""
        extra = self.costs.get("queue_words_waited", 0)
        if extra and self.wait_states("mem", self.fetch_linear):
            return self.costs["queue_words"] + extra
        return self.costs["queue_words"]

    def _fetch_room(self):
        if self.costs["queue_model"] == "byte":
            return self._queue_bytes() <= self.costs["queue_bytes"] - 2
        return self._queue_words() < self._queue_limit()

    def _bus_byte(self):
        """V30-style bus unit: while a cycle runs, whether the next cycle is
        a fetch is sampled once, fetch_sample clocks before its last clock,
        and latched; an idle bus unit checks for room every clock and starts
        a fetch idle_fetch_delay clocks after it first finds it."""
        if (self.fetch_grant_at is not None and self.clock >= self.fetch_grant_at
                and self.costs["fetch_grant"] == "idle" and (self.cycle is not None
                                                             or self.clock < self.bus_idle_until)):
            self.fetch_grant_at = None     # a request that finds the bus busy is lost
        if self.cycle is not None:
            last = self.cycle.start + self.cycle.length - 1
            if self.clock == last - self.costs["fetch_sample"]:
                self.fetch_latch = self._fetch_room() and not self.halted and not self.suspended
            if self.clock >= last:
                cycle, self.cycle = self.cycle, None
                if cycle.space == "io":
                    self.bus_idle_until = self.clock + 1 + self._io_recovery(cycle)
                self._finish(cycle)
            return
        if self.clock < self.bus_idle_until:
            self.idle_eligible = None
            return
        latch, self.fetch_latch = self.fetch_latch, False
        if self.pending is not None:
            if self.clock < self.pending.not_before:
                return
            cycle, self.pending = self.pending, None
            self._start(cycle)
            return
        if self._refresh_wanted():
            self._start(Cycle("refresh", "mem", 0, 2, owner="refresh"))
            self.refresh_due = self.clock + self._refresh_period()
            return
        if self._reset_hold > 0 or self.halted or self.suspended:
            self.idle_eligible = None
            return
        if not latch:
            if not self._fetch_room():
                self.idle_eligible = None
                return
            if self.idle_eligible is None:
                self.idle_eligible = self.clock
            if self.clock - self.idle_eligible < self.costs["idle_fetch_delay"]:
                return
            if self.costs["fetch_request"] and (self.queue or self.iwr):
                # An idle bus unit starts fetching only on an EU request.
                if self.fetch_grant_at is None or self.clock < self.fetch_grant_at:
                    return
        self.fetch_grant_at = None
        self.idle_eligible = None
        linear = self.fetch_linear
        width = 1 if linear & 1 else 2
        self._start(Cycle("fetch", "mem", linear, width))
        self.fetch_linear = (linear + width) & 0xFFFFF

    def _bus(self):
        if self.costs["queue_model"] == "byte" or self.costs.get("fetch_latch"):
            self._bus_byte()
            return
        if (self.fetch_grant_at is not None and self.clock >= self.fetch_grant_at
                and self.costs["fetch_grant"] == "idle" and self.cycle is not None):
            self.fetch_grant_at = None     # a request that finds the bus busy is lost
        if self.cycle is not None:
            if (self.cycle.kind == "fetch" and self.clock - self.cycle.start + 1
                    == self.cycle.length - self.costs.get("burst_sample", 0)):
                # fetch_burst "latch": whether a burst goes on is sampled here.
                self.burst_go = self._queue_words() < self._queue_limit()
            if self.clock - self.cycle.start + 1 >= self.cycle.length:
                cycle, self.cycle = self.cycle, None
                if cycle.space == "io":
                    self.bus_idle_until = self.clock + 1 + self._io_recovery(cycle)
                if cycle.kind == "fetch":
                    self.fetch_end = self.clock
                self._finish(cycle)
            return
        if self.clock < self.bus_idle_until:
            return
        if self.pending is not None:
            if self.clock < self.pending.not_before:
                return
            cycle, self.pending = self.pending, None
            self._start(cycle)
            return
        if self._refresh_wanted():
            self._start(Cycle("refresh", "mem", 0, 2, owner="refresh"))
            self.refresh_due = self.clock + self._refresh_period()
            return
        if self._reset_hold > 0:
            return
        if self.halted or self.suspended:
            return
        linear = self.fetch_linear
        width = 1 if linear & 1 else 2
        if self.costs["fetch_request"]:
            # The bus unit fetches only on an EU request: each one grants as
            # many fetches as there are free slots when it arrives.
            if self.fetch_grant_at is not None and self.clock >= self.fetch_grant_at:
                self.fetch_grant_at = None
                if self.costs["fetch_grant"] in ("idle", "free"):
                    self.fetch_credits = self.costs["queue_words"] - self._queue_words()
                elif self.costs["fetch_grant"] == "until_full":
                    self.fetch_credits = 1
                elif self.costs["fetch_grant"] == "one":
                    self.fetch_credits = max(self.fetch_credits, 1)
                elif isinstance(self.costs["fetch_grant"], int):
                    self.fetch_credits = max(self.fetch_credits, self.costs["fetch_grant"])
                else:
                    self.fetch_credits = self.costs["queue_words"] - self._queue_words()
            if not self.queue and not self.iwr:
                # An empty queue: the EU is waiting on it (reset, a flush).
                self.fetch_credits = max(self.fetch_credits, 1)
                if self.costs.get("empty_grant") == "free":
                    self.fetch_credits = self.costs["queue_words"] - self._queue_words()
            if self.fetch_credits <= 0:
                return
            if self._queue_words() < self._queue_limit():
                if self.costs["fetch_grant"] == "until_full":
                    # Fetch freely until the queue fills; then wait for a request.
                    if self._queue_words() + 1 >= self.costs["queue_words"]:
                        self.fetch_credits = 0
                    self._start(Cycle("fetch", "mem", linear, width))
                    self.fetch_linear = (linear + width) & 0xFFFFF
                    return
                self.fetch_credits -= 1
                self._start(Cycle("fetch", "mem", linear, width))
                self.fetch_linear = (linear + width) & 0xFFFFF
            return
        free = self._queue_limit() - self._queue_words()
        start = self.costs.get("fetch_start_free")
        if start and free > 0:
            # An idle bus unit waits for this many free slots, then fetches
            # back to back while any slot is free (fetch_burst "run") or as
            # many as were free when it started ("count").
            if isinstance(start, (list, tuple)):
                start = start[min(len(start) - 1, self.wait_states("mem", linear))]
            burst = self.costs.get("fetch_burst")
            if self.fetch_end == self.clock - 1 and (burst == "run" or (burst == "count" and self.burst_left > 0)
                                                      or (burst == "latch" and self.burst_go)):
                self.burst_left -= 1
            elif free < start:
                return
            else:
                self.burst_left = free - 1
        if free > 0:
            self._start(Cycle("fetch", "mem", linear, width))
            self.fetch_linear = (linear + width) & 0xFFFFF

    def _io_recovery(self, cycle):
        """Idle clocks after an I/O cycle; io_recovery_waited, when set, if it had wait states."""
        waited = self.costs.get("io_recovery_waited")
        if waited is not None and self.wait_states("io", cycle.address):
            return waited
        return self.costs["io_recovery"]

    def _per_wait(self, value):
        """A {"1": ..., "2": ...} value: the entry for the running code fetch's wait states."""
        if isinstance(value, dict):
            cycle = self.cycle
            waits = cycle.length - 3 if cycle is not None and cycle.kind == "fetch" else 0
            return value.get(str(waits), value.get(waits))
        return value

    def _load_blocked(self):
        """load_block: the EU cannot load a word while a fetch with wait states
        runs: "cycle" through the whole cycle, "waits" during its wait states,
        "wait1" on its first wait state only; [a, b] from its clock a to b
        clocks before its end. (The cycle has ended by the EU's turn on its
        last clock.)"""
        mode = self._per_wait(self.costs.get("load_block"))
        cycle = self.cycle
        if not mode or cycle is None or cycle.kind != "fetch" or cycle.length <= 3:
            return False
        k = self.clock - cycle.start
        if isinstance(mode, (list, tuple)):
            return mode[0] <= k <= cycle.length - 1 - mode[1]
        if mode == "cycle":
            return True
        if mode == "waits":
            return k >= 2
        return k == 2

    def _load_unblock(self):
        """The first clock load_block lets the EU load during the running fetch."""
        mode, cycle = self._per_wait(self.costs.get("load_block")), self.cycle
        if isinstance(mode, (list, tuple)):
            return cycle.start + cycle.length - mode[1]
        return cycle.start + (3 if mode == "wait1" else cycle.length - 1)

    def _request_fetch(self):
        """The EU asks the bus unit for fetches. With fetch_dry_words set it asks
        only when the queue holds that many words or fewer (in flight included)."""
        dry = self.costs.get("fetch_dry_words")
        if dry is not None and self._queue_words() > dry:
            return
        self.fetch_grant_at = self.clock + self.costs["fetch_request_delay"]

    def _refresh_period(self):
        return 16 << (self.sfr[0xE1] & 3)

    def _refresh_wanted(self):
        return self.sfr[0xE1] & 0x10 and self.clock >= self.refresh_due

    # -- execution unit ---------------------------------------------------

    def _decode(self):
        """The decode stage takes instruction bytes from the word register
        ahead of execution, one per clock: it starts refilling when it holds
        decode_refill bytes or fewer and stops at decode_bytes. In
        decode_mode "ahead" it instead takes bytes up to decode_to, which the
        EU's requests set (see _decode_request)."""
        if self.costs.get("decode_mode") == "ahead":
            nxt = self.iwr[0][0] if self.iwr else (self.queue[0][0] if self.queue else None)
            if nxt is None or self.decode_to is None or nxt >= self.decode_to:
                return
        else:
            if len(self.decoded) <= self.costs["decode_refill"]:
                self.decode_filling = True
            if not self.decode_filling or self.halted:
                return
            if len(self.decoded) >= self.costs["decode_bytes"]:
                self.decode_filling = False
                return
        if not self.iwr:
            if not self.queue or self.queue[0][2] > self.clock:
                return
            word = self.queue[0][0] >> 1
            while self.queue and self.queue[0][0] >> 1 == word:
                linear, value, _ = self.queue.pop(0)
                self.iwr.append((linear, value))
            self.iwr_ready = self.clock + self.costs["word_load"]
            if self.loads is not None:
                self.loads.append((self.clock, (word << 1) & 0xFFFF))
            return
        if self.clock < self.iwr_ready:
            return
        linear, value = self.iwr.pop(0)
        self.decoded.append((linear, value, self.clock))
        if self.costs.get("decode_mode") == "ahead":
            # decode_rate bytes a clock, within the register's word.
            for _ in range(self.costs.get("decode_rate", 1) - 1):
                if not self.iwr or self.iwr[0][0] >= self.decode_to:
                    break
                linear, value = self.iwr.pop(0)
                self.decoded.append((linear, value, self.clock))
            return
        if len(self.decoded) >= self.costs["decode_bytes"]:
            self.decode_filling = False

    # -- classed decoder (decode_mode "classed") -------------------------

    def _insn_class(self, start):
        """'io', 'simple' or 'complex' for the instruction at a linear address."""
        n, op = 0, self.mem_read8(start)
        while op in (0x26, 0x2E, 0x36, 0x3E, 0xF0, 0xF2, 0xF3, 0x64, 0x65) and n < 15:
            n += 1
            op = self.mem_read8(start + n)
        if op in self.costs["decode_io"]:
            return "io"
        key = op
        if op == 0x0F:
            key = 0x0F00 | self.mem_read8(start + n + 1)
        if key in self.costs["decode_simple"]:
            from .length import _TABLE
            modrm = _TABLE.get(op, (False, 0))[0] if op != 0x0F else True
            if not modrm or self.mem_read8(start + n + (2 if op == 0x0F else 1)) >= 0xC0:
                return "simple"
        return "complex"

    def _take_word(self, load=None):
        """Move the queue's head word to the decoded store: its slot frees
        now, its bytes are usable word_load clocks later."""
        word = self.queue[0][0] >> 1
        ready = self.clock + (self.costs["word_load"] if load is None else load)
        while self.queue and self.queue[0][0] >> 1 == word:
            linear, value, _ = self.queue.pop(0)
            self.decoded.append((linear, value, ready))
        if self.loads is not None:
            self.loads.append((self.clock, (word << 1) & 0xFFFF))
        end = self.decoded[-1][0] + 1
        # Instructions the new bytes begin.
        while self.dec_next < end:
            start = self.dec_next
            self.dec_open = start + length(self.mem_read8, start)
            self.dec_open_class = self._insn_class(start)
            self.dec_next = self.dec_open
            if self.dec_open_class != "simple" and start != self.dec_waited:
                self.burst = False

    def _decode_classed(self, demand=False):
        """One clock of the classed decoder. It takes a word when the EU
        waits for a byte it does not hold (demand), to finish an instruction
        whose opcode it holds, or in a burst: an opcode wait for a simple
        instruction starts one, which takes words until decode_cap bytes
        past the executing instruction are held or a non-simple instruction
        is taken. An I/O instruction is taken only on demand."""
        if not self.queue or self.queue[0][2] > self.clock or self.halted:
            return
        head = self.queue[0][0]
        held_end = self.decoded[-1][0] + 1 if self.decoded else head
        if demand:
            # As the word register's load: the routine may hide a clock of it.
            load = self.costs["word_load"]
            if self._last_was_boundary:
                load -= self.end_discount
            elif self.routine is not None and self.routine.hides_mid_load():
                load -= 1
            self._take_word(load)
            self.preloaded = False
            return
        current_end = self.dec_cur_end if self.dec_cur_end is not None else head
        if (current_end <= head < self.dec_open and self.dec_open_class != "io"
                and held_end - current_end < self.costs["decode_finish_cap"]):
            self._take_word()                      # finish an instruction already begun
            return
        if not self.burst:
            return
        if head >= self.dec_next and self._insn_class(self.dec_next) == "io":
            self.burst = False
            return
        if held_end - current_end >= self.costs["decode_cap"]:
            self.burst = False
            return
        self._take_word()

    def _decode_request(self):
        """The EU waits for a byte the decode stage does not hold: it decodes
        up to it, and on an opcode wait decode_ahead whole instructions
        further unless the opcode is in decode_skip."""
        nxt = self.iwr[0][0] if self.iwr else (self.queue[0][0] if self.queue else None)
        if nxt is None:
            return
        end = nxt + 1
        if (self._last_was_boundary and not self.iwr
                and self.mem_read8(nxt) not in self.costs["decode_skip"]):
            end = nxt
            for _ in range(1 + self.costs["decode_ahead"]):
                end += length(self.mem_read8, end)
        if self.decode_to is None or end > self.decode_to or nxt >= self.decode_to:
            self.decode_to = end
        self._decode()

    def _eu(self):
        if self.costs.get("decode_mode") == "classed":
            self._decode_classed()
        elif self.costs.get("decode_bytes"):
            self._decode()
        if self._eu_wait:
            self._eu_wait -= 1
            return
        while True:
            request = self._eu_request
            if request is None:
                try:
                    request = self._gen.send(self._eu_value)
                except StopIteration:
                    self.halted = True
                    return
                self._eu_value = None
                self._eu_request = request
            op = request[0]
            if op == "clocks":
                self._eu_request = None
                if request[1] > 0:
                    self._eu_wait = request[1] - 1
                    return
                continue
            if op == "byte" and self.costs["queue_model"] == "consume":
                if not self.queue or self.queue[0][2] > self.clock:
                    return
                linear = self.queue[0][0]
                if self.costs["word_load"] and linear >> 1 != self.last_word and not self._penalty_paid:
                    # Reading into a new word costs a decode stall.
                    load = self.costs["word_load"]
                    if self._last_was_boundary:
                        load -= self.end_discount
                    elif self.routine is not None and self.routine.hides_mid_load():
                        load -= 1
                    self._penalty_paid = True
                    if load > 0:
                        self._eu_wait = load - 1
                        return
                linear, value, _ = self.queue.pop(0)
                self.last_word = linear >> 1
                self._penalty_paid = False
                self._eu_value = value
                self._eu_request = None
                continue
            if op == "byte" and self.costs["queue_model"] == "byte":
                # Pop one byte once it is ripe.
                if not self.queue or self.queue[0][2] > self.clock:
                    return
                linear, value, _ = self.queue.pop(0)
                if self.loads is not None and not linear & 1:
                    self.loads.append((self.clock, linear & 0xFFFF))
                self._eu_value = value
                self._eu_request = None
                continue
            if op == "preload" and self.costs["queue_model"] in ("byte", "consume"):
                self._eu_request = None
                continue
            if op in ("byte", "preload") and self.costs.get("decode_mode") == "classed":
                if op == "preload":
                    # A pre-pop emptied the store: the next word loads at once.
                    if not self.decoded and self.queue and self.queue[0][2] <= self.clock:
                        start = self.queue[0][0]
                        self._take_word()
                        self.preloaded = True
                        if self.costs.get("decode_preload_burst") and start >= (self.dec_cur_end or 0):
                            self.dec_waited = start
                            self.burst = self._insn_class(start) == "simple"
                if op == "byte":
                    if not self.decoded:
                        if self._last_was_boundary and self.queue:
                            start = self.queue[0][0]
                            self.dec_waited = start
                            self.dec_cur_end = start + length(self.mem_read8, start)
                            self.burst = self._insn_class(start) == "simple"
                        self._decode_classed(demand=True)
                        return
                    if self.decoded[0][2] > self.clock:
                        return
                    if self.preloaded and not self.decoded[0][0] & 1 and self.costs["preload_penalty"]:
                        # The first byte of a word loaded ahead costs the EU a clock.
                        self.preloaded = False
                        self.decoded[0] = self.decoded[0][:2] + (self.clock + self.costs["preload_penalty"],)
                        return
                    self.preloaded = False
                    linear, value, _ = self.decoded.pop(0)
                    if self._last_was_boundary:
                        self.insn_start = linear
                        self.dec_cur_end = linear + length(self.mem_read8, linear)
                    self._eu_value = value
                self._eu_request = None
                continue
            if op in ("byte", "preload") and self.costs.get("decode_bytes"):
                if op == "byte" and not self.decoded and self.costs.get("decode_mode") == "ahead":
                    self._decode_request()
                if op == "byte":
                    if not self.decoded or self.decoded[0][2] > self.clock:
                        return
                    linear, value, _ = self.decoded.pop(0)
                    if self._last_was_boundary:
                        self.insn_start = linear
                    self._eu_value = value
                self._eu_request = None
                continue
            if op in ("byte", "preload"):
                if (op == "byte" and self._last_was_boundary and self.costs["fetch_request"] == "ask"
                        and self.fetch_asked is not request):
                    # The EU asks for its next opcode.
                    self.fetch_asked = request
                    self._request_fetch()
                if (op == "preload" and not self.iwr and self.last_load_preload
                        and self.costs.get("preload_alternate")):
                    # A pre-load does not follow another: the next word waits for a demand.
                    self._eu_request = None
                    continue
                if not self.iwr:
                    # Load the queue's head word into the instruction word
                    # register: its slot frees now, its bytes can be read
                    # word_load clocks later.
                    unblock = None
                    if self._load_blocked():
                        if self.costs.get("load_defer"):
                            # The word leaves its slot now; its bytes wait out the block.
                            unblock = self._load_unblock()
                    if unblock is None and self._load_blocked():
                        if op == "preload":
                            self._eu_request = None
                            continue
                        return
                    if not self.queue or self.queue[0][2] > self.clock:
                        if op == "preload":
                            self._eu_request = None
                            continue
                        return
                    word = self.queue[0][0] >> 1
                    while self.queue and self.queue[0][0] >> 1 == word:
                        linear, value, _ = self.queue.pop(0)
                        self.iwr.append((linear, value))
                    load = self.costs["word_load"]
                    if self._last_was_boundary:
                        load -= self.end_discount
                    elif self.routine is not None and self.routine.hides_mid_load():
                        load -= 1
                    extra = self.costs.get("load_wait_extra")
                    busy = self._per_wait(self.costs.get("load_busy_extra"))
                    if busy and self.cycle is not None and self.cycle.kind == "fetch" and self.cycle.length > 3:
                        load += busy               # a load made while a waited fetch runs
                    if op == "preload" and self.costs.get("load_wait_demand"):
                        extra = 0                  # load_wait_demand: a pre-load does not pay it
                    if isinstance(extra, dict):
                        # Clocks added to a word load per code wait setting.
                        waits = self.wait_states("mem", self.iwr[0][0])
                        load += extra.get(str(waits), extra.get(waits, 0)) if waits else 0
                    elif extra:
                        # Waited code memory slows the word load past a wait-state threshold.
                        load += extra * max(0, self.wait_states("mem", self.iwr[0][0])
                                            - self.costs.get("load_wait_free", 1))
                    self.iwr_ready = (unblock if unblock is not None else self.clock) + load
                    hold = self.costs.get("operand_hold")
                    self.iwr_held = (op == "byte" and not self._last_was_boundary and bool(hold)
                                     and (hold == 1 or not request[1])
                                     and (hold != "modrm_r" or self.iwr[0][1] >> 6 == 3))
                    self.last_load_preload = op == "preload"
                    if self.loads is not None:
                        self.loads.append((self.clock, (word << 1) & 0xFFFF))
                    if self.costs["fetch_request"] == "load" or (
                            self.costs["fetch_request"] == "demand" and op == "byte"):
                        self._request_fetch()
                    self.preloaded = op == "preload"
                if op == "preload":
                    self._eu_request = None
                    continue
                if self.clock < self.iwr_ready:
                    return
                take = self.costs.get("take_block")
                if take and op == "byte" and (take == "all" or not self._last_was_boundary) and self._load_blocked():
                    return
                if self.preloaded and not self.iwr[0][0] & 1 and self.costs["preload_penalty"]:
                    # The first byte of a word loaded ahead costs the EU a clock.
                    self.preloaded = False
                    self.iwr_ready = self.clock + self.costs["preload_penalty"]
                    return
                self.preloaded = False
                linear, value = self.iwr.pop(0)
                self.last_take = (self.clock, self._last_was_boundary)
                mode = self.costs["fetch_request"]
                if (mode == "take" or (mode == "opcode" and self._last_was_boundary)
                        or (mode == "word_end" and not self.iwr)
                        or (mode == "opcode_end" and self._last_was_boundary and not self.iwr)):
                    self._request_fetch()
                self._eu_value = value
                self._eu_request = None
                continue
            if op in ("read", "write"):
                if self.pending is None and (self.cycle is None or self.cycle.owner not in ("eu", "posted")
                                             or op == "write"):
                    _, space, address, width, *rest = request
                    self.pending = Cycle(op, space, address, width, rest[0] if rest else 0,
                                         owner="eu")
                    if op == "write" and self.costs["write_posted"]:
                        self.pending.owner = "posted"
                        self.pending.not_before = self.clock + self.costs["post_start_delay"]
                        self._eu_request = None
                        self._eu_wait = self.costs["write_post_clocks"]
                        if self._eu_wait:
                            self._eu_wait -= 1
                            return
                        continue
                    self._eu_request = ("busy",)
                return
            if op == "busy":
                return
            if op == "flush":
                self.queue.clear()
                self.iwr.clear()
                self.last_load_preload = False
                self.decoded.clear()
                self.decode_to = None
                self.burst = False
                self.dec_next = self.dec_open = request[1]
                self.dec_cur_end = None
                self.suspended = False
                self.last_word = None
                self.fetch_linear = request[1]
                self._eu_request = None
                if self.cycle is not None and self.cycle.kind == "fetch":
                    self.cycle.kind = "fetch-discard"
                continue
            if op == "suspend":
                self.suspended = True
                self._eu_request = None
                continue
            if op == "opcode":
                self._last_was_boundary = True
                self._eu_request = None
                continue
            if op == "boundary":
                self._last_was_boundary = False
                self._eu_request = None
                continue
            if op == "halt":
                self.halted = True
                return
            raise ValueError(f"unknown EU request {request}")

    def step(self):
        self.clock += 1
        self.tick += self.ticks_per_clock
        if self._reset_hold > 0:
            self._reset_hold -= 1
        self._bus()
        if not self.halted:
            self._eu()

    def run(self, max_clocks=200_000):
        while self.result is None and self.clock < max_clocks:
            self.step()
        return self.result
