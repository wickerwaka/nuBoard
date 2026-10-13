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
        self._last_was_boundary = True # the next byte the EU takes is an opcode
        self.routine = None            # the EU, for its current routine key
        self.end_discount = 0          # clocks the last routine hides of the next opcode load
        self.suspended = False         # prefetch stopped by a decided transfer until its flush
        self.last_word = None          # consumption model: word of the last byte taken
        self._penalty_paid = False
        self.fetch_linear = 0xFFFF0    # next prefetch address
        self.cycle: Cycle | None = None
        self.bus_idle_until = 0
        self.pending: Cycle | None = None     # EU request not yet on the bus
        self.trace: list[Transaction] = []
        self.refresh_due = 0
        self.refresh_row = 0
        self.eu = EU(self)
        self.result = None             # pass / fail from the result port
        self.log = None                # set to [] to record (clock, pc, opcode) per instruction
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
        if self.costs["queue_model"] == "two_word":
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

    def _bus(self):
        if self.cycle is not None:
            if self.clock - self.cycle.start + 1 >= self.cycle.length:
                cycle, self.cycle = self.cycle, None
                if cycle.space == "io":
                    self.bus_idle_until = self.clock + 1 + self.costs["io_recovery"]
                self._finish(cycle)
            return
        if self.clock < self.bus_idle_until:
            return
        if self.pending is not None:
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
        if self._queue_words() < self.costs["queue_words"]:
            self._start(Cycle("fetch", "mem", linear, width))
            self.fetch_linear = (linear + width) & 0xFFFFF

    def _refresh_period(self):
        return 16 << (self.sfr[0xE1] & 3)

    def _refresh_wanted(self):
        return self.sfr[0xE1] & 0x10 and self.clock >= self.refresh_due

    # -- execution unit ---------------------------------------------------

    def _eu(self):
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
            if op in ("byte", "preload"):
                if not self.iwr:
                    # Load the queue's head word into the instruction word
                    # register: its slot frees now, its bytes can be read
                    # word_load clocks later.
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
                    self.iwr_ready = self.clock + load
                if op == "preload":
                    self._eu_request = None
                    continue
                if self.clock < self.iwr_ready:
                    return
                linear, value = self.iwr.pop(0)
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
