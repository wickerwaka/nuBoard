"""HyperRAM trace-buffer commands for the template FPGA image (channel 1)."""

from __future__ import annotations

import struct
import time
from dataclasses import asdict, dataclass

from .device import NuBoard, NuBoardError
from .protocol import Status

CHANNEL = 1
WORDS = 4 * 1024 * 1024          # 8 MB of 16-bit words
HARNESS_HZ = 50_000_000          # the test harness runs on the 50 MHz clock

OP_TEST = 0                      # write, then read back and check
OP_GET_RESULT = 1
OP_READ_ID = 2
OP_WRITE = 3
OP_READ = 4

PATTERNS = {"prbs": 0, "address": 1, "walking": 2, "toggle": 3}
STATUS_NAMES = {0: "ok", 1: "not ready", 2: "bad operation", 3: "timeout",
                4: "out of range"}

_COMMAND = struct.Struct("<BBxxIII")
_RESULT = struct.Struct("<BBBBHHHHIIIIHHHHHHIIII")


@dataclass
class Result:
    status: int
    operation: int
    pattern: int
    pll_locked: bool
    init_done: bool
    busy: bool
    mhz: int
    phase: int
    burst_words: int
    user_width: int
    words: int
    errors: int
    missing: int
    first_error_address: int
    first_error_expected: int
    first_error_actual: int
    error_bits: int
    id0: int
    id1: int
    buffers: int
    write_cycles: int
    read_cycles: int
    seed: int
    bursts: int

    @property
    def ok(self) -> bool:
        return self.status == 0 and self.errors == 0 and self.missing == 0

    def _rate(self, cycles: int) -> float | None:
        if not cycles:
            return None
        nbytes = 2 * self.burst_words * self.bursts
        return round(nbytes * HARNESS_HZ / cycles / 1e6, 1)

    @property
    def write_mb_per_s(self) -> float | None:
        return self._rate(self.write_cycles)

    @property
    def read_mb_per_s(self) -> float | None:
        return self._rate(self.read_cycles)

    def as_dict(self) -> dict:
        value = asdict(self)
        value["status"] = STATUS_NAMES.get(self.status, str(self.status))
        for key in ("first_error_expected", "first_error_actual",
                    "error_bits", "id0", "id1"):
            value[key] = f"0x{value[key]:04x}"
        value["first_error_address"] = f"0x{self.first_error_address:06x}"
        value["write_mb_per_s"] = self.write_mb_per_s
        value["read_mb_per_s"] = self.read_mb_per_s
        return value


def pack_command(operation: int, pattern: int = 0, seed: int = 0,
                 first_burst: int = 0, bursts: int = 0) -> bytes:
    if first_burst < 0 or bursts < 0:
        raise ValueError("burst range must not be negative")
    return _COMMAND.pack(operation, pattern, seed & 0xFFFFFFFF,
                         first_burst, bursts)


def unpack_result(payload: bytes) -> Result:
    if len(payload) != _RESULT.size:
        raise NuBoardError(Status.LENGTH,
                           f"HyperRAM reply is {len(payload)} bytes, "
                           f"expected {_RESULT.size}")
    (status, operation, pattern, flags, *rest) = _RESULT.unpack(payload)
    return Result(status, operation, pattern, bool(flags & 1),
                  bool(flags & 2), bool(flags & 4), *rest)


def command(board: NuBoard, payload: bytes, tag: int = 0x4852,
            timeout: float = 10.0) -> Result:
    """Send one command and wait for its reply packet."""

    board.fpga_send(CHANNEL, payload, tag)
    deadline = time.monotonic() + timeout
    while True:
        try:
            channel, _flags, reply_tag, data = board.fpga_recv()
        except NuBoardError as exc:
            if exc.status != Status.BUSY or time.monotonic() > deadline:
                raise
            time.sleep(0.002)
            continue
        if channel != CHANNEL or reply_tag != tag:
            raise NuBoardError(Status.LINK,
                               f"unexpected reply on channel {channel} "
                               f"tag {reply_tag:#x}")
        return unpack_result(data)


def wait_ready(board: NuBoard, timeout: float = 2.0) -> Result:
    """Read the status and ID registers, retrying until the core is ready."""

    deadline = time.monotonic() + timeout
    while True:
        result = command(board, pack_command(OP_READ_ID))
        if result.status != 1 or time.monotonic() > deadline:
            return result
        time.sleep(0.01)


def test(board: NuBoard, pattern: int = 0, seed: int = 1,
         first_burst: int = 0, bursts: int | None = None,
         operation: int = OP_TEST) -> Result:
    """Run a test pass. bursts=None covers the whole device."""

    if bursts is None:
        burst_words = wait_ready(board).burst_words
        bursts = WORDS // burst_words - first_burst
    return command(board, pack_command(operation, pattern, seed,
                                       first_burst, bursts))
