from __future__ import annotations

import enum
import struct
from dataclasses import dataclass

MAGIC = b"NUB1"
EVENT_MAGIC = b"NUE1"
PROTOCOL = (1, 0)
MAX_PAYLOAD = 4096
HEADER = struct.Struct("<4sBBBBHHII")
EVENT = struct.Struct("<4sBBBBIIIIII")


class Kind(enum.IntEnum):
    REQUEST = 0
    RESPONSE = 1


class Opcode(enum.IntEnum):
    GET_INFO = 0x0001
    GET_STATE = 0x0002
    CONFIG_BEGIN = 0x0100
    CONFIG_DATA = 0x0101
    CONFIG_END = 0x0102
    CONFIG_ABORT = 0x0103
    FPGA_SEND = 0x0200
    FPGA_RECV = 0x0201
    LINK_STATUS = 0x0202
    VCCB_ENABLE = 0x0300
    VCCB_DISABLE = 0x0301
    POWER_OFF = 0x0302


class Status(enum.IntEnum):
    OK = 0
    VERSION = 1
    LENGTH = 2
    STATE = 3
    ARGUMENT = 4
    BUSY = 5
    TIMEOUT = 6
    CHECKSUM = 7
    LINK = 8
    CONFIGURATION = 9
    SELECTOR = 10
    INTERNAL = 11


class EventType(enum.IntEnum):
    FPGA_IRQ = 1
    STATE = 2
    CONFIG_FAILURE = 3
    VCCB_SHUTDOWN = 4
    LINK_FAULT = 5
    OVERFLOW = 6


@dataclass(frozen=True)
class Message:
    opcode: int
    sequence: int
    payload: bytes = b""
    kind: Kind = Kind.REQUEST
    status: Status = Status.OK
    flags: int = 0

    def pack(self) -> bytes:
        if len(self.payload) > MAX_PAYLOAD:
            raise ValueError("payload exceeds 4096 bytes")
        header = HEADER.pack(
            MAGIC,
            *PROTOCOL,
            int(self.kind),
            self.flags,
            int(self.opcode),
            int(self.status),
            self.sequence,
            len(self.payload),
        )
        return header + self.payload

    @classmethod
    def unpack(cls, raw: bytes) -> "Message":
        if len(raw) < HEADER.size:
            raise ValueError("short message header")
        fields = HEADER.unpack_from(raw)
        magic, major, minor, kind, flags = fields[:5]
        opcode, status, sequence, length = fields[5:]
        if magic != MAGIC:
            raise ValueError("bad message magic")
        if (major, minor) != PROTOCOL:
            raise ValueError("unsupported protocol version")
        if length > MAX_PAYLOAD or len(raw) != HEADER.size + length:
            raise ValueError("invalid payload length")
        return cls(
            opcode,
            sequence,
            raw[HEADER.size:],
            Kind(kind),
            Status(status),
            flags,
        )


@dataclass(frozen=True)
class EventRecord:
    event_type: EventType
    sequence: int
    timestamp_us: int
    argument0: int
    argument1: int
    lost: int
    flags: int = 0

    @classmethod
    def unpack(cls, raw: bytes) -> "EventRecord":
        if len(raw) != EVENT.size:
            raise ValueError("event record must be 32 bytes")
        (
            magic,
            major,
            minor,
            event_type,
            flags,
            sequence,
            timestamp,
            arg0,
            arg1,
            lost,
            reserved,
        ) = EVENT.unpack(raw)
        if magic != EVENT_MAGIC or (major, minor) != PROTOCOL or reserved:
            raise ValueError("invalid event record")
        return cls(EventType(event_type), sequence, timestamp, arg0, arg1, lost, flags)
