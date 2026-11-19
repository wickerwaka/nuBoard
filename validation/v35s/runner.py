from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from nuboard.debug import CHANNEL, DebugClient
from nuboard.device import NuBoard

ROOT = Path(__file__).resolve().parents[2]
CORE_UUID = b"nuBoard-V35S-v01"
CORE_BUILD = 2
MODES = {"model": 1, "socket": 2, "both": 3}

# Trace flag bits, see fpga/v35s/v35s_lane.sv.
FLAG_READ = 1 << 0
FLAG_IO = 1 << 1
FLAG_REFRESH = 1 << 2
FLAG_UBE_N = 1 << 3
FLAG_UNMAPPED = 1 << 4
FLAG_MARKER = 1 << 5
FLAG_COL_A9 = 1 << 6
FLAG_STROBE = 1 << 7
FLAG_EVENT = 1 << 8      # an OUT to the event port FF12h
FLAG_PIN = 1 << 9        # a pin record: address = pins 15:0, data = pins 31:16

# Event port: an OUT of the event number (low byte) starts the schedule
# entries waiting for it (harness version 2, fpga/v35s/v35s_stim.sv).
PORT_EVENT = 0xFF12

# Input levels (register 0x8E and schedule masks), fpga/v35s/v35s_harness.sv.
INPUTS = {"NS": 0, "NMI": 1, "INTP0": 2, "INTP1": 3, "INTP2": 4, "INT": 5,
          "DMARQ0": 6, "DMARQ1": 7, "HLDRQ": 8, "RXD0": 9, "RXD1": 10,
          "CTS0": 11, "CTS1": 12}
# Levels at rest: N/S high, NMI and the active-low requests high, RxD idle high.
REST_LEVELS = 0x1E1F

# Output pin vector (pin records and register 0xBA), bit by name.
PINS = {**{f"P0{i}": i for i in range(8)},
        "P13": 11, "INTAK": 11, "P14": 12, "P15": 13, "TOUT": 13, "P16": 14, "SCK0": 14,
        "P17": 15, "P21": 17, "DMAAK0": 17, "P22": 18, "TC0": 18, "P24": 20, "DMAAK1": 20,
        "P25": 21, "TC1": 21, "P26": 22, "HLDAK": 22, "TXD0": 24, "TXD1": 25, "CTS0": 26}

# Bank modes for register 0x88 and marker writes: two bits per bank.
BANK_H, BANK_Z, BANK_D = 0, 1, 2


def port_modes(t2=BANK_H, r2=BANK_H, r0=BANK_H, t0=BANK_H):
    return t2 | (r2 << 2) | (r0 << 4) | (t0 << 6)


def pin_mask(*names):
    """The record mask for named output pins (PINS), or all pins with none."""
    if not names:
        names = tuple(PINS)
    mask = 0
    for name in names:
        mask |= 1 << PINS[name.upper()]
    return mask


def level_bits(**levels):
    """(mask, value) for named input levels, e.g. level_bits(INT=1, NMI=0)."""
    mask = value = 0
    for name, level in levels.items():
        bit = 1 << INPUTS[name.upper()]
        mask |= bit
        if level:
            value |= bit
    return mask, value


@dataclass
class ScheduleEntry:
    """One entry of the marker-triggered input schedule.

    event: the event number a program writes to PORT_EVENT, or None to start
    as soon as the previous entry has ended. After `delay` ticks (30 ns) the
    levels in `levels` are set; with hold > 0 they take the opposite level
    after `hold` ticks (a pulse). `serial` names RxD streams (0, 1) to start
    at the same tick.
    """
    event: int | None
    levels: dict
    delay: int = 0
    hold: int = 0
    serial: tuple = ()

    def words(self):
        if self.event is not None and not 0 <= self.event < 0xFF:
            raise ValueError("event numbers are 0-254 (255 means chained)")
        if not (0 <= self.delay < 1 << 24 and 0 <= self.hold < 1 << 24):
            raise ValueError("delay and hold are 24-bit tick counts")
        mask, value = level_bits(**self.levels)
        flags = sum(1 << (8 + channel) for channel in self.serial)
        return [(0xFF if self.event is None else self.event) | flags,
                self.delay & 0xFFFF, self.delay >> 16,
                self.hold & 0xFFFF, self.hold >> 16, mask, value, 0]


def uart_bits(data: bytes, data_bits=8, parity=None, stop_bits=1, idle=1):
    """Asynchronous frames as RxD levels, first bit first: `idle` mark bits,
    then per byte a start bit, LSB-first data, optional parity ('even' or
    'odd') and stop bits."""
    bits = [1] * idle
    for byte in data:
        payload = [(byte >> index) & 1 for index in range(data_bits)]
        bits += [0] + payload
        if parity is not None:
            ones = sum(payload)
            bits.append(ones & 1 if parity == "even" else 1 - (ones & 1))
        bits += [1] * stop_bits
    return bits


class SimulationTransport:
    def __init__(self, variant="direct"):
        top = {"direct": "v35s_harness", "spi": "nuboard_v35s",
               "dual": "v35s_dual_sim"}[variant]
        self.process = subprocess.Popen(
            [str(ROOT / f"build/fpga/v35s/verilator-{variant}/V{top}")],
            # The model core loads its microcode relative to the repo root.
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

    def exchange(self, data: bytes) -> bytes:
        self.process.stdin.write(struct.pack("<I", len(data)) + data)
        self.process.stdin.flush()
        header = self.process.stdout.read(4)
        if len(header) != 4:
            raise RuntimeError("Verilator process exited without a response")
        length = struct.unpack("<I", header)[0]
        if length > 4096:
            raise RuntimeError("invalid simulator framing")
        result = self.process.stdout.read(length)
        if len(result) != length:
            raise RuntimeError("truncated simulator response")
        return result

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
        self.process.stdout.close()


@dataclass
class Transaction:
    start: int
    address: int
    flags: int
    data: int
    strobe: int
    end: int

    @classmethod
    def unpack(cls, record: bytes):
        start, low, high, data, strobe, end = struct.unpack("<IHHHHI", record)
        return cls(start, low | ((high & 15) << 16), high >> 4, data, strobe, end)

    @property
    def pins(self):
        """The pin vector of a pin record (FLAG_PIN)."""
        return (self.address & 0xFFFF) | (self.data << 16)

    @property
    def kind(self):
        if self.flags & FLAG_PIN:
            return "pins"
        if self.flags & FLAG_REFRESH:
            return "refresh"
        if not self.flags & FLAG_STROBE:
            return "idle"
        space = "io" if self.flags & FLAG_IO else "mem"
        return f"{space}-{'read' if self.flags & FLAG_READ else 'write'}"

    @property
    def functional(self):
        # Refresh addresses advance with time and are compared as timing.
        if self.flags & FLAG_REFRESH:
            return ("refresh",)
        return self.address, self.data, self.flags & ~FLAG_COL_A9

    def describe(self):
        if self.flags & FLAG_PIN:
            return f"{self.start:>9}       pins      {self.pins:08x}"
        width = ("lo" if not self.address & 1 else "") + \
                ("hi" if not self.flags & FLAG_UBE_N else "")
        return (f"{self.start:>9} +{self.end - self.start:<4} {self.kind:<9} "
                f"{self.address:05x} {self.data:04x} {width:<4} strobe+{self.strobe}")


def compare_traces(reference, candidate):
    differences = []
    timing = []
    if len(reference) != len(candidate):
        differences.append({"kind": "length", "reference": len(reference),
                            "candidate": len(candidate)})
    for index, (left, right) in enumerate(zip(reference, candidate)):
        if left.functional != right.functional:
            differences.append({"index": index, "reference": asdict(left),
                                "candidate": asdict(right)})
        if ((left.start - reference[0].start, left.end - left.start, left.strobe) !=
                (right.start - candidate[0].start, right.end - right.start, right.strobe)):
            timing.append(index)
    return {"functional_match": not differences, "differences": differences[:32],
            "timing_match": not timing and len(reference) == len(candidate),
            "timing_difference_indices": timing[:256]}


def write_sequence(trace):
    """Writes and I/O cycles in order: what a program did, whatever it fetched.

    The V35 bus has no fetch status, so reads cannot be split into fetches
    and data reads. The ordered list of writes and I/O cycles is the part of
    a trace that the prefetch policy cannot change.
    """
    return [(t.address, t.data, t.flags & ~FLAG_COL_A9) for t in trace
            if t.flags & FLAG_STROBE and (t.flags & FLAG_IO or not t.flags & FLAG_READ)]


def pin_sequence(trace):
    """The recorded output pin vectors in order (pin records only)."""
    return [t.pins for t in trace if t.flags & FLAG_PIN]


def compare_programs(reference, candidate):
    left, right = write_sequence(reference), write_sequence(candidate)
    first = next((i for i, (a, b) in enumerate(zip(left, right)) if a != b),
                 None if len(left) == len(right) else min(len(left), len(right)))
    pins_left, pins_right = pin_sequence(reference), pin_sequence(candidate)
    return {"write_sequence_match": left == right, "writes": [len(left), len(right)],
            "first_difference": first,
            "pin_sequence_match": pins_left == pins_right,
            "pin_changes": [len(pins_left), len(pins_right)]}


RESULT_REGION = (0x00400, 0x100)
# The dump routine's region (validation/v35s/dump.py).
DUMP_REGION = (0x00800, 0x210)


class Harness:
    def __init__(self, debug: DebugClient, strict: bool = True):
        """strict: a differential run passes only on identical bus traces.
        Otherwise it passes on identical write/I-O sequences (the prefetch
        policy may differ); the trace comparison is still reported."""
        self.debug = debug
        self.strict = strict
        # (work order 29) set by open_board: a harness on the board, where N/S low is refused
        self.board = False
        identity, self.version = struct.unpack("<HH", debug.read(0, 4))
        if identity != 0x7033 or self.version not in (1, 2):
            raise RuntimeError("unexpected V35S harness identity or ABI")
        self.pages = []

    def _need_stimulus(self):
        if self.version < 2:
            raise RuntimeError("the input schedule needs harness version 2 (rebuild the image)")

    def load_schedule(self, entries=(), intak_vector=None, int_release=False,
                      rxd0=None, rxd1=None):
        """Load the marker-triggered input schedule for the next runs.

        entries: ScheduleEntry list (at most 32), run in order in each lane.
        intak_vector: answer /INTAK with this byte on D7..D0 (None: no answer).
        int_release: drop INT at /INTAK's falling edge.
        rxd0 / rxd1: (bits, bit_time_ticks) streams that entries start.
        """
        self._need_stimulus()
        entries = list(entries)
        if len(entries) > 32:
            raise ValueError("the schedule holds 32 entries")
        words = [word for entry in entries for word in entry.words()]
        if words:
            self.debug.write(0x60000, struct.pack(f"<{len(words)}H", *words))
        for channel, stream in enumerate((rxd0, rxd1)):
            bits, bit_time = stream if stream is not None else ((), 2)
            bits = list(bits)
            if len(bits) > 2048 or not 2 <= bit_time <= 0xFFFF:
                raise ValueError("an RxD stream is at most 2048 bits at 2+ ticks per bit")
            if bits:
                packed = [sum(bit << index for index, bit in enumerate(bits[base:base + 16]))
                          for base in range(0, len(bits), 16)]
                self.debug.write(0x60200 + channel * 0x100,
                                 struct.pack(f"<{len(packed)}H", *packed))
            self.debug.write16(0xA4 + channel * 2, bit_time)
            self.debug.write16(0xA8 + channel * 2, len(bits))
        self.debug.write16(0xA2, 0 if intak_vector is None else intak_vector)
        self.debug.write16(0xA0, len(entries) | ((intak_vector is not None) << 8)
                           | (bool(int_release) << 9))

    def clear_schedule(self):
        if self.version >= 2:
            self.load_schedule()

    def record_pins(self, mask=0):
        """Record changes of the output pins in `mask` (pin_mask()) as trace
        records; a pin records only while its bank is CPU-driven."""
        self._need_stimulus()
        self.debug.write(0xAC, struct.pack("<I", mask))

    def configure(self, x_half=2, ready_ticks=0, reset_ticks=1_667,
                  start_ports=port_modes(), p0_levels=0, input_levels=REST_LEVELS):
        self.debug.write16(0x08, x_half)
        self.debug.write16(0x0A, ready_ticks)
        self.debug.write(0x84, struct.pack("<I", reset_ticks))
        self.debug.write16(0x88, start_ports)
        self.debug.write16(0x8C, p0_levels)
        self.debug.write16(0x8E, input_levels)

    def load_table(self, table: bytes):
        """(work order 29) Load the core v2's secure-mode translation table (256 bytes, entry
        k = the opcode the encoded byte k decodes to) through register C2h, one entry a write.
        The core never initialises it; load it between runs (a write while busy is refused).
        Simulation (model lane) only: the socket's table is in its mask."""
        if self.board:
            raise RuntimeError("the translation table is loaded in simulation only")
        table = bytes(table)
        if len(table) != 256:
            raise ValueError("the translation table is 256 bytes")
        for address, value in enumerate(table):
            self.debug.write16(0xC2, address << 8 | value)

    def _check_levels(self, mode):
        """(work order 29, the user's ruling 2026-11-19) N/S low (secure mode from reset, register
        8Eh bit 0) is for simulation's model lane only: refused on the board and on any run with
        the socket lane."""
        levels = self.debug.read16(0x8E)
        if not levels & 1 << INPUTS["NS"] and (self.board or MODES[mode] & 2):
            raise RuntimeError("N/S low (secure mode) is simulation only: refused on a socket lane")

    def arm(self, armed=True):
        self.debug.write16(0x04, 1 if armed else 0)

    def load(self, segments: dict[int, bytes], extra_pages=()):
        """Map up to sixteen 4 KiB pages of the 1 MiB space and upload them."""
        self.image = (segments, tuple(extra_pages))
        pages = set(extra_pages)
        for address, data in segments.items():
            if address < 0 or address + len(data) > 0x100000:
                raise ValueError("program segment outside the V35 address space")
            if data:
                pages.update(range(address >> 12, ((address + len(data) - 1) >> 12) + 1))
        ordered = sorted(pages)
        if any(not 0 <= page < 256 for page in ordered):
            raise ValueError("page outside the V35 address space")
        if len(ordered) > 16:
            raise ValueError("image exceeds the sixteen mapped 4 KiB pages")
        images = {page: bytearray(4096) for page in ordered}
        for address, data in segments.items():
            for offset, value in enumerate(data):
                target = address + offset
                images[target >> 12][target & 4095] = value
        mapping = [(0x8000 | ordered[slot]) if slot < len(ordered) else 0
                   for slot in range(16)]
        self.debug.write(0x40, struct.pack("<16H", *mapping))
        # Host writes initialize both lane memories. The V35 is little
        # endian like the debug words, so pages upload without swapping.
        if ordered:
            self.debug.fill(0x10000, len(ordered) * 4096)
        for slot, page in enumerate(ordered):
            words = images[page]
            nonzero = [index for index, value in enumerate(words) if value]
            if nonzero:
                first = nonzero[0] & ~1
                end = (nonzero[-1] + 2) & ~1
                self.debug.write(0x10000 + slot * 4096 + first, bytes(words[first:end]))
        self.pages = ordered

    def trace(self, lane: str):
        count = self.debug.read16(0x14 if lane == "model" else 0x16)
        if count > 2048:
            raise RuntimeError("invalid trace count")
        if not count:
            return []
        raw = self.debug.read(0x30000 if lane == "model" else 0x40000, count * 16)
        return [Transaction.unpack(raw[i:i + 16]) for i in range(0, len(raw), 16)]

    def read_memory(self, lane: str, address: int, length: int):
        result = bytearray()
        while length:
            page, offset = divmod(address, 4096)
            slot = self.pages.index(page)
            count = min(length, 4096 - offset)
            first = offset & ~1
            last = (offset + count + 1) & ~1
            base = 0x10000 if lane == "model" else 0x20000
            raw = self.debug.read(base + slot * 4096 + first, last - first)
            result.extend(raw[offset - first:offset - first + count])
            address += count
            length -= count
        return bytes(result)

    def run(self, mode="socket", limit=50_000_000, capture_start=0):
        self._check_levels(mode)
        self.debug.write(0x2A, struct.pack("<I", capture_start))
        self.debug.write(0x0C, struct.pack("<I", limit))
        self.debug.write16(4, (MODES[mode] << 8) | 2)
        # Allow for a 30 ms cold reset after arming, plus the run itself.
        status = self.debug.wait16(6, 2, 2, limit + 1_000_000)
        model = self.trace("model") if MODES[mode] & 1 else []
        socket = self.trace("socket") if MODES[mode] & 2 else []
        registers = self.debug.read(0x08, 0x22)
        extra = self.debug.read(0x88, 0x14)

        def register(address, format):
            return struct.unpack_from(format, registers, address - 0x08)[0]

        def register2(address, format):
            return struct.unpack_from(format, extra, address - 0x88)[0]

        result = {
            "status": status,
            "model_result": (status >> 2) & 3,
            "socket_result": (status >> 4) & 3,
            "timeout": bool(status & 128),
            "overflow": bool(status & 64),
            "x_half": register(0x08, "<H"),
            "ready_ticks": register(0x0A, "<H"),
            "elapsed_ticks": register(0x10, "<I"),
            "socket_pins_after_run": register(0x18, "<H"),
            "capture_start": capture_start,
            "model_total": register(0x1A, "<I"),
            "socket_total": register(0x1E, "<I"),
            "model_signature": register(0x22, "<I"),
            "socket_signature": register(0x26, "<I"),
            "port_mode_after_run": register2(0x8A, "<H"),
            "markers": register2(0x90, "<H"),
            "last_marker": register2(0x92, "<H"),
            "model_trace": [asdict(t) for t in model],
            "socket_trace": [asdict(t) for t in socket],
        }
        if self.version >= 2:
            stimulus = self.debug.read(0xB0, 0x0A)
            socket_status, model_status, events, unmatched, last = struct.unpack("<5H", stimulus)
            result["stimulus"] = {
                "socket_status": socket_status, "model_status": model_status,
                "socket_events": events & 0xFF, "model_events": events >> 8,
                "socket_unmatched": unmatched & 0xFF, "model_unmatched": unmatched >> 8,
                "socket_last_event": last & 0xFF, "model_last_event": last >> 8,
            }
        result["passed"] = not status & 192 and all(
            result[f"{lane}_result"] == 1
            for lane, bit in (("model", 1), ("socket", 2)) if MODES[mode] & bit
        )
        if mode == "both":
            result["comparison"] = compare_traces(socket, model)
            result["program_comparison"] = compare_programs(socket, model)
            if self.strict:
                result["passed"] &= result["comparison"]["functional_match"]
                result["passed"] &= result["model_total"] == result["socket_total"]
            else:
                result["passed"] &= result["program_comparison"]["write_sequence_match"]
                result["passed"] &= result["program_comparison"]["pin_sequence_match"]
        result["trace_complete"] = all(
            result[f"{lane}_total"] <= len(result[f"{lane}_trace"])
            for lane, bit in (("model", 1), ("socket", 2)) if MODES[mode] & bit
        )
        return result

    def run_complete(self, mode="socket", limit=50_000_000):
        """Replay a deterministic image until every window of the trace is read."""
        result = self.run(mode, limit)
        if not result["passed"]:
            return result
        segments, extra_pages = self.image
        lanes = [lane for lane, bit in (("model", 1), ("socket", 2)) if MODES[mode] & bit]
        total = max(result[f"{lane}_total"] for lane in lanes)
        for start in range(2048, total, 2048):
            self.load(segments, extra_pages)
            window = self.run(mode, limit, capture_start=start)
            for lane in lanes:
                for field in ("total", "signature"):
                    if window[f"{lane}_{field}"] != result[f"{lane}_{field}"]:
                        result["passed"] = False
                        result["replay_error"] = f"{lane} {field} changed at window {start}"
                        return result
                result[f"{lane}_trace"].extend(window[f"{lane}_trace"])
        if mode == "both":
            reference = [Transaction(**row) for row in result["socket_trace"]]
            candidate = [Transaction(**row) for row in result["model_trace"]]
            result["comparison"] = compare_traces(reference, candidate)
            result["program_comparison"] = compare_programs(reference, candidate)
            result["passed"] &= (result["comparison"]["functional_match"] if self.strict
                                 else result["program_comparison"]["write_sequence_match"]
                                 and result["program_comparison"]["pin_sequence_match"])
            for key, (address, length) in (("result_region_match", RESULT_REGION),
                                           ("dump_region_match", DUMP_REGION)):
                if address >> 12 in self.pages:
                    same = (self.read_memory("model", address, length) ==
                            self.read_memory("socket", address, length))
                    result["program_comparison"][key] = same
        result["trace_complete"] = True
        return result


def reset_image(code: bytes, origin=0x00100, segment=0x0000):
    """Place code at origin and a far jump to it at the FFFF0 reset vector."""
    offset = origin - (segment << 4)
    if not 0 <= offset < 0x10000:
        raise ValueError("origin is not addressable from the entry segment")
    vector = bytes([0xEA, offset & 0xFF, offset >> 8, segment & 0xFF, segment >> 8])
    return {origin: code, 0xFFFF0: vector}


def load_stimulus(harness, spec):
    """Apply a program's stimulus description (a `<program>.stim.json`
    beside it), or clear the schedule and pin recording with None.

    {"entries": [{"event": 1, "delay": 100, "hold": 0, "levels": {"INT": 1},
                  "serial": [0]}, ...],          event null = chained
     "intak_vector": 32, "int_release": true,
     "rxd0": {"uart": "55aa", "bit_time": 400, "data_bits": 8, "parity": null,
              "stop_bits": 1, "idle": 2}  or  {"bits": [1, 0, ...], "bit_time": 400},
     "pins": ["TXD0", "P00"]  or  "all"}
    """
    if spec is None:
        harness.clear_schedule()
        if harness.version >= 2:
            harness.record_pins(0)
        return
    entries = [ScheduleEntry(event=row.get("event"), levels=row.get("levels", {}),
                             delay=row.get("delay", 0), hold=row.get("hold", 0),
                             serial=tuple(row.get("serial", ())))
               for row in spec.get("entries", ())]
    streams = []
    for name in ("rxd0", "rxd1"):
        stream = spec.get(name)
        if stream is None:
            streams.append(None)
        elif "uart" in stream:
            bits = uart_bits(bytes.fromhex(stream["uart"]), stream.get("data_bits", 8),
                             stream.get("parity"), stream.get("stop_bits", 1),
                             stream.get("idle", 1))
            streams.append((bits, stream["bit_time"]))
        else:
            streams.append((stream["bits"], stream["bit_time"]))
    harness.load_schedule(entries, spec.get("intak_vector"), spec.get("int_release", False),
                          *streams)
    pins = spec.get("pins", ())
    harness.record_pins(pin_mask() if pins == "all" else pin_mask(*pins) if pins else 0)


IMAGE = ROOT / "build/fpga/v35s/outflow/v35s.hex.bin"


def open_board(socket_needed: bool, image: Path | None = IMAGE):
    """Check (configuring if needed) the board and return a Harness.

    Power-off at the end of every run also removes FPGA power, so a fresh
    session normally starts by streaming the image.
    """
    transport = NuBoard()
    state = json.loads(transport.state())
    if image is not None and (not state["link"] or state["core_uuid"] != CORE_UUID.hex()
                              or state["core_build"] != CORE_BUILD
                              or state["vccb"]):
        transport.configure(image)
        state = json.loads(transport.state())
    if not state["link"]:
        raise RuntimeError("configure the V35S harness bitstream first")
    if state["core_uuid"] != CORE_UUID.hex():
        raise RuntimeError("configured core is not the V35S harness")
    if state["core_build"] != CORE_BUILD:
        raise RuntimeError(f"runner expects V35S harness build {CORE_BUILD}")
    if socket_needed:
        if state["vccb"]:
            raise RuntimeError("start from a freshly configured harness with VCCB off")
        if state["selector_mv"] != 5000:
            raise RuntimeError("the uPD70337 requires the exclusive 5 V selector")
    harness = Harness(DebugClient(lambda data: transport.fpga_exchange(CHANNEL, data)))
    harness.board = True
    return transport, harness, state


def main():
    from .asm import assemble

    parser = argparse.ArgumentParser(description="Run V35S programs in simulation or on nuBoard")
    parser.add_argument("--backend", choices=("sim", "spi-sim", "dual-sim", "board"), default="board")
    parser.add_argument("--mode", choices=MODES, default="socket")
    parser.add_argument("--socket-fitted", action="store_true",
                        help="confirm the uPD70337 daughterboard is installed; permits DUT power")
    parser.add_argument("--x-half", type=int, default=2,
                        help="X1 half period in 30 ns ticks (default 2: X1 = 8.33 MHz, the maximum)")
    parser.add_argument("--limit", type=int, default=50_000_000)
    parser.add_argument("programs", nargs="+", type=Path,
                        help="NEC-syntax sources; code is placed at 0x00100")
    parser.add_argument("--output", type=Path, default=ROOT / "build/validation/v35s/results.json")
    parser.add_argument("--print-trace", action="store_true")
    parser.add_argument("--program-only", action="store_true",
                        help="differential runs pass on matching write/I-O sequences "
                             "rather than identical bus traces")
    args = parser.parse_args()
    if args.backend not in ("board", "dual-sim") and args.mode != "model":
        parser.error("the socket is only available with --backend board or dual-sim")
    if args.backend == "board" and args.mode != "model" and not args.socket_fitted:
        parser.error("socket modes require --socket-fitted and the installed uPD70337")
    subprocess.run([sys.executable, str(ROOT / "tools/fetch_v35s.py"), "--verify-only"],
                   check=True, stdout=subprocess.DEVNULL)

    transport = None
    reports = []
    board_state = None
    failure = None
    try:
        if args.backend == "board":
            transport, harness, board_state = open_board(args.mode != "model")
            harness.strict = not args.program_only
        else:
            variant = {"sim": "direct", "spi-sim": "spi", "dual-sim": "dual"}[args.backend]
            transport = SimulationTransport(variant)
            harness = Harness(DebugClient(transport.exchange), strict=not args.program_only)
        harness.configure(x_half=args.x_half)
        if args.mode != "model":
            if args.backend == "board":
                transport.vccb_enable()
            harness.arm()
            if args.backend == "board":
                time.sleep(0.05)
        for path in args.programs:
            source = path.read_text()
            code = assemble(source, org=0x100)
            harness.load(reset_image(code))
            stimulus = path.with_suffix(".stim.json")
            load_stimulus(harness, json.loads(stimulus.read_text()) if stimulus.exists() else None)
            result = harness.run_complete(args.mode, args.limit)
            result.update(name=path.stem, program_sha256=hashlib.sha256(code).hexdigest())
            reports.append(result)
            lane = "socket" if args.mode != "model" else "model"
            extra = ""
            if args.mode == "both":
                trace_cmp = result["comparison"]
                program_cmp = result["program_comparison"]
                extra = (f" trace={'match' if trace_cmp['functional_match'] else 'differ'}"
                         f" writes={'match' if program_cmp['write_sequence_match'] else 'differ'}"
                         f"{'' if 'result_region_match' not in program_cmp else ' results=' + ('match' if program_cmp['result_region_match'] else 'differ')}")
            print(f"{path.stem}: {'PASS' if result['passed'] else 'FAIL'} "
                  f"status=0x{result['status']:04x} "
                  f"cycles={result['model_total']}/{result['socket_total']} "
                  f"ticks={result['elapsed_ticks']}{extra}", flush=True)
            if args.print_trace:
                for row in result[f"{lane}_trace"][:200]:
                    print("  " + Transaction(**row).describe())
    except BaseException as exc:
        failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if transport is not None:
            try:
                if args.backend == "board":
                    harness_ok = "harness" in locals()
                    if harness_ok:
                        harness.arm(False)
                    transport.power_off()
            finally:
                transport.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({
            "backend": args.backend, "mode": args.mode,
            "board_state_before_run": board_state, "error": failure,
            "cpu_marking": "uPD70337L-8" if args.mode != "model" else None,
            "tests": reports,
        }, indent=2) + "\n")
    return 0 if reports and all(item["passed"] for item in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
