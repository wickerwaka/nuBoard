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
        self.releases = []             # (clock, linear) of taken bytes not yet freed
        self.held = []                 # linear addresses of the current instruction's bytes
        self.read_words = []           # (until clock, word) the EU's read pointer still holds
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

    def _queue_space(self):
        """Bytes the queue can still accept, counting a fetch in flight."""
        self.releases = [r for r in self.releases if r[0] > self.clock]
        addresses = [q[0] for q in self.queue] + [r[1] for r in self.releases] + self.held
        if self.cycle is not None and self.cycle.kind == "fetch":
            addresses += [self.cycle.address + i for i in range(self.cycle.width)]
        if self.costs["release_words"] == 3:
            used = 2 * len({a >> 1 for a in addresses})
        elif self.costs["release_words"] == 2:
            # Word slots: every word with bytes queued or in flight, plus the
            # word holding the byte the EU took last (until it moves past it).
            words = {a >> 1 for a in addresses}
            self.read_words = [r for r in self.read_words if r[0] > self.clock]
            words.update(w for _, w in self.read_words)
            used = 2 * len(words)
        elif self.costs["release_words"]:
            used = 2 * len({a >> 1 for a in addresses})
        else:
            used = len(addresses)
        return self.costs["queue_bytes"] - used

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
        if self.halted:
            return
        linear = self.fetch_linear
        width = 1 if linear & 1 else 2
        if self._queue_space() >= self.costs["fetch_threshold"] + (width - 2):
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
            if op == "byte":
                if not self.queue or self.queue[0][2] > self.clock:
                    return
                linear, value, _ = self.queue.pop(0)
                deferred = len(request) > 1 and request[1]
                if self.costs["release_words"] == 3:
                    # Operand bytes stay in their queue word until the
                    # instruction completes; decode bytes free at once.
                    if deferred:
                        self.held.append(linear)
                    elif self.costs["free_latency"]:
                        self.releases.append((self.clock + self.costs["free_latency"], linear))
                elif self.costs["release_words"] == 2:
                    word = linear >> 1
                    keep = [r for r in self.read_words if r[1] != word]
                    # The previous word stays held for release_delay clocks.
                    self.read_words = [(min(c, self.clock + self.costs["release_delay"]), w)
                                       for c, w in keep] + [(1 << 60, word)]
                elif self.costs["release_at_boundary"]:
                    self.held.append(linear)
                elif self.costs["release_delay"]:
                    self.releases.append((self.clock + self.costs["release_delay"], linear))
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
                self.releases.clear()
                self.held.clear()
                self.read_words.clear()
                self.fetch_linear = request[1]
                self._eu_request = None
                if self.cycle is not None and self.cycle.kind == "fetch":
                    self.cycle.kind = "fetch-discard"
                continue
            if op == "boundary":
                if self.costs["release_words"] == 3:
                    lat = self.costs["free_latency"]
                    if lat:
                        self.releases += [(self.clock + lat, a) for a in self.held]
                    self.held = []
                    self._eu_request = None
                    continue
                delay = self.costs["release_delay"]
                self.releases += [(self.clock + delay, a) for a in self.held]
                self.held = []
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
