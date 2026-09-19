"""ABI-4 change records in an append-only BRAM capture buffer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import struct

SIGNAL_MASK = (1 << 52) - 1
MAX_DELTA = 4095
CAPACITY = 32768
REASONS = {0: "running", 1: "complete", 2: "overflow", 3: "capacity",
           4: "aborted", 5: "memory_fault", 6: "disabled", 7: "invalidated"}


def encode_samples(samples):
    """Reference encoder for contiguous 20 ns samples, including the final tick."""
    values = list(samples)
    output = bytearray()
    previous_tick = 0
    previous_value = None
    for tick, value in enumerate(values):
        if not 0 <= value <= SIGNAL_MASK:
            raise ValueError("sample exceeds the 52-bit signal layout")
        delta = tick - previous_tick
        if (value != previous_value or delta == MAX_DELTA or
                tick == len(values) - 1 and delta):
            output.extend(struct.pack("<Q", value | (delta << 52)))
            previous_tick = tick
            previous_value = value
    return bytes(output)


def events(raw, first_tick=0):
    """Yield (absolute tick, full signal word), without expanding idle periods."""
    if len(raw) % 8:
        raise ValueError("truncated change record")
    tick = first_tick
    for index, (record,) in enumerate(struct.iter_unpack("<Q", raw)):
        delta = record >> 52
        if (index == 0 and delta != 0) or (index != 0 and delta == 0):
            raise ValueError("invalid initial or non-increasing timestamp")
        tick += delta
        if tick > 0xFFFFFFFF:
            raise ValueError("capture timestamp overflow")
        yield tick, record & SIGNAL_MASK


@dataclass(frozen=True)
class Capture:
    lane: str
    reason: str
    first_tick: int
    last_tick: int
    missed_tick: int
    accepted: int
    committed: int
    buffer_used: int
    raw: bytes

    def __post_init__(self):
        if self.lane not in ("model", "socket"):
            raise ValueError("invalid capture lane")
        if not 0 <= self.committed <= self.accepted <= CAPACITY:
            raise ValueError("invalid capture counts")
        if len(self.raw) != self.committed * 8:
            raise ValueError("capture length does not match committed count")
        last_event = None
        for tick, _ in events(self.raw, self.first_tick):
            last_event = tick
        if last_event is not None and not self.first_tick <= last_event <= self.last_tick:
            raise ValueError("event lies outside the captured interval")
        if self.reason == "complete" and self.committed:
            if self.accepted != self.committed or last_event != self.last_tick:
                raise ValueError("complete capture has an undrained or missing terminal record")

    @property
    def complete(self):
        return self.reason == "complete" and self.accepted == self.committed

    def window(self, start=None, end=None):
        """Expand only [start,end), retaining absolute acquisition ticks."""
        start = self.first_tick if start is None else start
        end = self.last_tick + 1 if end is None else end
        if start < self.first_tick or end > self.last_tick + 1 or end < start:
            raise ValueError("window outside captured interval")
        rows = iter(events(self.raw, self.first_tick))
        current = next(rows, None)
        following = next(rows, None)
        if current is None:
            return
        for tick in range(start, end):
            while following is not None and following[0] <= tick:
                current = following
                following = next(rows, None)
            yield tick, current[1]

    def report(self):
        result = asdict(self)
        result.pop("raw")
        result.update(scope_abi=4, sample_period_ns=20,
                      storage="bram", capacity_records=CAPACITY,
                      records_hex=self.raw.hex(),
                      records_sha256=hashlib.sha256(self.raw).hexdigest(),
                      complete=self.complete)
        return result


class Scope:
    def __init__(self, debug):
        self.debug = debug
        if debug.read16(0x30) != 4:
            raise RuntimeError("BRAM capture requires scope ABI 4")

    def initialize(self):
        if (self.debug.read16(0x7C) != 15 or self.debug.read16(0x7E) != 20 or
                not self.debug.read16(0x62) & 0x10):
            raise RuntimeError("unexpected BRAM capture geometry or readiness")

    def configure(self, lane, start=0, end=0xFFFFFFFF):
        if lane not in ("model", "socket") or not 0 <= start <= end <= 0xFFFFFFFF:
            raise ValueError("invalid lane or capture interval")
        self.initialize()
        self.debug.write16(0x36, 1 if lane == "model" else 2)
        self.debug.write(0x32, struct.pack("<I", start))
        self.debug.write(0x3A, struct.pack("<I", end))

    def download(self):
        # Wait only for the observation and final BRAM-write pipeline to settle.
        self.debug.wait16(0x60, 7, 4, 1000)
        info = self.debug.read16(0x62)
        counts = struct.unpack("<6I", self.debug.read(0x64, 24))
        accepted, committed, first, last, missed, high_water = counts
        if not 0 <= committed <= accepted <= CAPACITY:
            raise RuntimeError("invalid record count reported by FPGA")
        if accepted != committed or high_water != accepted:
            raise RuntimeError("inconsistent BRAM occupancy after capture stopped")
        raw = bytearray()
        remaining = committed * 8
        for bank in range(4):
            if not remaining:
                break
            self.debug.write16(0x38, bank)
            length = min(remaining, 65536)
            raw.extend(self.debug.read(0x50000, length))
            remaining -= length
        lane = self.debug.read16(0x36)
        if lane not in (1, 2):
            raise RuntimeError("no selected capture lane")
        return Capture(
            ("model", "socket")[lane-1], REASONS[info & 15], first, last,
            missed, accepted, committed, high_water,
            bytes(raw),
        )
