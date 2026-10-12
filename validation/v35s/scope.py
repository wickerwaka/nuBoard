"""V35S signal layout for the shared ABI-4 scope (validation/m68000/scope.py).

Bit layout, from fpga/v35s/v35s_harness.sv:
  [15:0] data bus, [24:16] multiplexed address pins (A9/A1 .. A17/A9),
  25 A18//UBE, 26 A19, 27 A0, 28 R//W, 29 /MREQ, 30 /MSTB, 31 /IOSTB,
  32 /REFRQ, 33 X1, 34 /RESET, 35 READY, 36 harness drives data,
  39:37 lane state, 47:40 P0 (P07 = CLKOUT), 51:48 R2 pins.
Every sample is one 30 ns tick of the 33.33 MHz system clock (build 2 on;
build 1 sampled at 20 ns), taken after the scope's own two-flop synchronizer,
so absolute edges carry up to one tick of uncertainty.
"""

from __future__ import annotations

from dataclasses import dataclass

from validation.m68000.scope import Capture, events  # noqa: F401
from validation.m68000.scope import Scope as _Scope

TICK_NS = 30
TICK_REPORT = 3000   # register 7Eh: the tick in units of 10 ps


class Scope(_Scope):
    """The shared ABI-4 scope with the V35S harness's 30 ns tick."""

    def initialize(self):
        if (self.debug.read16(0x7C) != 15 or self.debug.read16(0x7E) != TICK_REPORT or
                not self.debug.read16(0x62) & 0x10):
            raise RuntimeError("unexpected BRAM capture geometry, tick or readiness")

FIELDS = {
    "data": (0, 16),
    "mux": (16, 9),
    "a18_ube": (25, 1),
    "a19": (26, 1),
    "a0": (27, 1),
    "rw": (28, 1),
    "mreq_n": (29, 1),
    "mstb_n": (30, 1),
    "iostb_n": (31, 1),
    "refrq_n": (32, 1),
    "x1": (33, 1),
    "reset_n": (34, 1),
    "ready": (35, 1),
    "drive": (36, 1),
    "lane_state": (37, 3),
    "p0": (40, 8),
    "clkout": (47, 1),
    "r2": (48, 4),
}


def decode(value: int) -> dict[str, int]:
    return {name: (value >> shift) & ((1 << width) - 1)
            for name, (shift, width) in FIELDS.items()}


@dataclass
class Edge:
    tick: int
    signal: str
    value: int


def edges(capture: Capture, signals=None, start=None, end=None):
    """Every change of the selected fields, in tick order."""
    names = list(signals or FIELDS)
    previous = None
    result = []
    for tick, value in events(capture.raw, capture.first_tick):
        if start is not None and tick < start:
            previous = decode(value)
            continue
        if end is not None and tick >= end:
            break
        fields = decode(value)
        for name in names:
            if previous is None or fields[name] != previous[name]:
                result.append(Edge(tick, name, fields[name]))
        previous = fields
    return result


def periods(capture: Capture, signal: str, level: int = 1):
    """Ticks between successive transitions of a one-bit field to level."""
    rising = [edge.tick for edge in edges(capture, [signal]) if edge.value == level]
    return [b - a for a, b in zip(rising, rising[1:])]


def waveform(capture: Capture, start: int, end: int, step: int = 1,
             signals=("x1", "clkout", "mreq_n", "mstb_n", "iostb_n", "refrq_n",
                      "rw", "ready", "drive")) -> str:
    """Text timing diagram, one row per one-bit signal and one column per step."""
    rows = {name: [] for name in signals}
    current = None
    stream = iter(events(capture.raw, capture.first_tick))
    pending = next(stream, None)
    for tick in range(start, end, step):
        while pending is not None and pending[0] <= tick:
            current = decode(pending[1])
            pending = next(stream, None)
        for name in signals:
            rows[name].append("?" if current is None else
                              "‾" if current[name] else "_")
    width = max(len(name) for name in signals)
    return "\n".join(f"{name:>{width}} {''.join(row)}" for name, row in rows.items())
