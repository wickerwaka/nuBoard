"""CPU-independent 16-bit debug bus carried by an FPGA mailbox application."""

from __future__ import annotations

import struct
from typing import Callable

HEADER = struct.Struct("<4sBBHI")
REPLY = struct.Struct("<HH")
# 4096-byte mailbox packet minus its 16-byte header and our 12-byte header.
MAX_TRANSFER = 4068
MAX_FILL = 65534
CHANNEL = 0x44


class DebugClient:
    def __init__(self, exchange: Callable[[bytes], bytes]):
        self.exchange = exchange

    def _command(self, op: int, address: int, length: int, data: bytes = b"") -> bytes:
        maximum = MAX_FILL if op == 3 else MAX_TRANSFER
        if address & 1 or length & 1 or not 0 < length <= maximum:
            raise ValueError(f"debug transfers must be aligned, nonempty, and at most {maximum} bytes")
        if not 0 <= address < 0x100000 or address + length > 0x100000:
            raise ValueError("debug address exceeds the 20-bit address space")
        raw = self.exchange(HEADER.pack(b"NDB1", op, 0, length, address) + data)
        if len(raw) < REPLY.size:
            raise RuntimeError("short debug reply")
        status, reserved = REPLY.unpack_from(raw)
        if reserved or status:
            raise RuntimeError(f"debug command failed (status={status}, reserved={reserved})")
        expected = 0 if op in (1, 3) else length
        if len(raw) != REPLY.size + expected:
            raise RuntimeError("debug response length mismatch")
        return raw[REPLY.size:]

    def read(self, address: int, length: int) -> bytes:
        if length <= 0 or length & 1:
            raise ValueError("read length must be a positive multiple of two")
        self._validate_range(address, length)
        return b"".join(self._command(0, address + i, min(MAX_TRANSFER, length - i))
                        for i in range(0, length, MAX_TRANSFER))

    def write(self, address: int, data: bytes) -> None:
        if not data or len(data) & 1:
            raise ValueError("write length must be a positive multiple of two")
        self._validate_range(address, len(data))
        for i in range(0, len(data), MAX_TRANSFER):
            chunk = data[i:i + MAX_TRANSFER]
            self._command(1, address + i, len(chunk), chunk)

    @staticmethod
    def _validate_range(address: int, length: int) -> None:
        # Validate the entire operation before the first exchange: a late
        # range error must not leave a partially initialized target.
        if address & 1 or address < 0 or address + length > 0x100000:
            raise ValueError("debug range must be aligned and within the 20-bit address space")

    def fill(self, address: int, length: int, value: int = 0) -> None:
        """Fill an even byte range with a repeated little-endian 16-bit word.

        Requires the build-9 debug bridge. As with WRITE, a bus error can
        leave a completed prefix; callers must abort initialization on error.
        """
        if length <= 0 or length & 1:
            raise ValueError("fill length must be a positive multiple of two")
        self._validate_range(address, length)
        pattern = struct.pack("<H", value)
        for offset in range(0, length, MAX_FILL):
            self._command(3, address + offset, min(MAX_FILL, length - offset), pattern)

    def read16(self, address: int) -> int:
        return struct.unpack("<H", self.read(address, 2))[0]

    def write16(self, address: int, value: int) -> None:
        self.write(address, struct.pack("<H", value))

    def wait16(self, address: int, mask: int, value: int, ticks: int) -> int:
        raw = self._command(2, address, 2, struct.pack("<HHI", mask, value, ticks))
        return struct.unpack("<H", raw)[0]
