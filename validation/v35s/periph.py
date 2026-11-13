"""F4 part A: the ports, the time base, the timers (docs/v35s-function-plan.md, stage F4).

Directed programs measured on the socketed uPD70337 and run unchanged on the core v2 RTL in
simulation, in validation/v35s/intr.py's frame (its Test, handler, log and slots):

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.periph socket [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.periph sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.periph gate [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.periph show NAME [--ref socket]
    PYTHONPATH=host/src:. python3 -m validation.v35s.periph emit

Besides intr.py's receipt fields a run here keeps the output pin records (`pins`: [tick,
vector] in order) and the ticks of the interrupt stubs' first store (`stubs`: [tick, vector]):
the stub's store is the entry's first write, a fixed number of clocks after the take, so the
differences of successive ticks are the period of the source that raised it, in 30 ns ticks
(a CPU clock is 32 ticks at the reset clock fX/8, x_half 2).

The gate (`gate`): the write and I/O sequence, the result regions and the pin vector sequence
equal (ticks ignored), and, per test that names a period (Test.period), the stub tick
differences after the first equal on both within `PERIOD_TOL` ticks.

Receipts: validation/v35s/receipts/f4-<name>-<backend>.json (--tag adds a suffix).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

from . import intr
from .intr import (LOG, PSW0, PSW_IE, STUBS, Test, _h, ev, level, make_program, sfr_rd, sfr_wr,
                   wait)

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS_DIR = ROOT / "validation/v35s/programs"
RECEIPTS = ROOT / "validation/v35s/receipts"

CLK = 32                # ticks per CPU clock at fX/8 (x_half 2)
PERIOD_TOL = 16 * CLK   # a stub period: silicon takes an interrupt in HALT on a 16-clock grid (README "F4")

SFR = dict(intr.SFR, P0=0x00, PM0=0x01, PMC0=0x02, P1=0x08, P2=0x10, PM2=0x11, PMC2=0x12,
           PT=0x38, PMT=0x3B, TM0=0x80, TM0H=0x81, MD0=0x82, MD0H=0x83, TM1=0x88, TM1H=0x89,
           MD1=0x8A, MD1H=0x8B, TMC0=0x90, TMC1=0x91, PRC=0xEB, RFM=0xE1, WTC=0xE8)


def sfr_ww(name, val):
    """A word store to a 16-bit SFR through DS1 (F000h)."""
    return f"    DB 26h\n    MOV word [0FF{SFR[name]:02X}h], {_h(val, 4)}\n"


def sfr_wrd(name, at):
    """A 16-bit SFR's word into PS:at (AW clobbered)."""
    return f"    DB 26h\n    MOV AW, [0FF{SFR[name]:02X}h]\n    DB 2Eh\n    MOV [{_h(at, 4)}], AW\n"


def srd(name, at):
    """An SFR byte into PS:at with intr.SFR's names extended."""
    return f"    DB 26h\n    MOV AL, [0FF{SFR[name]:02X}h]\n    DB 2Eh\n    MOV [{_h(at, 4)}], AL\n"


def swr(name, val):
    return f"    DB 26h\n    MOV byte [0FF{SFR[name]:02X}h], {_h(val)}\n"


def marker(modes):
    """The bank-mode marker (FF10h): two bits per bank, T2 R2 R0 T0 (0 H, 1 Z, 2 D)."""
    return (f"    PUSH AW\n    PUSH DW\n    MOV DW, 0FF10h\n    MOV AW, {_h(modes, 4)}\n"
            "    OUT DW, AW\n    POP DW\n    POP AW\n")


def modes(t2=0, r2=0, r0=0, t0=0):
    return t2 | r2 << 2 | r0 << 4 | t0 << 6


def halts(n):
    """n HALTs (the first labelled by test_source; the others not, by their indentation)."""
    return "    HALT\n    NOP\n    NOP\n" + "   HALT\n    NOP\n    NOP\n" * (n - 1)


class PTest(Test):
    """intr.Test with `period`: the gate compares the tick differences of the test's successive
    stub stores after its first (every vector)."""

    def __init__(self, *a, period=False, **k):
        k.setdefault("jitter", True)
        super().__init__(*a, **k)
        self.period = bool(period)


# ------------------------------------------------------------------ the fast stubs
# The logging handler takes ~1,750 clocks at fX/8; a timer's period is shorter. A program with
# `fast` vectors sends them to a short stub instead: the store of n at 8002h (the tick), a count
# at 8040h + n, FINT, RETI (no log entry).
FAST = 0x3600
COUNTS = 0x8040


def fast_area(vectors):
    ivt = bytearray(intr.vector_area()[0x0000])
    code = bytearray()
    for i, n in enumerate(vectors):
        at = FAST + 16 * i
        ivt[4 * n:4 * n + 2] = at.to_bytes(2, "little")
        c = 0x8040 + n
        code += bytes([0x2E, 0xC6, 0x06, 0x02, 0x80, n, 0x2E, 0xFE, 0x06, c & 0xFF, c >> 8,
                       0x0F, 0x92, 0xCF, 0x90, 0x90])
    return {0x0000: bytes(ivt), FAST: bytes(code)}


# ------------------------------------------------------------------ the ports
P0_IN = 0xA5            # the host's P0 levels (register 8Ch) while T2 is H


def init_test():
    """The first test: refresh off (RFM ECh, as the corpus)."""
    return PTest("init", jitter=False, code=swr("RFM", 0xEC))


def port_tests():
    T = [init_test()]
    # reads at reset: the ports as inputs (P0 the host's levels, P1 the inputs, P2 low, PT)
    T.append(PTest("in_reset", jitter=False, code=(
        srd("P0", "{S}") + srd("P1", "{S}+1") + srd("P2", "{S}+2") + srd("PT", "{S}+3")
        + "    DB 26h\n    MOV AW, [0FF00h]\n    DB 2Eh\n    MOV [{S}+4], AW\n"
        + "    DB 26h\n    MOV AW, [0FF08h]\n    DB 2Eh\n    MOV [{S}+6], AW\n"
        + "    DB 26h\n    MOV AW, [0FF10h]\n    DB 2Eh\n    MOV [{S}+8], AW\n"
        + "    DB 26h\n    MOV AW, [0FF38h]\n    DB 2Eh\n    MOV [{S}+10], AW\n")))
    # the inputs changed by the schedule: INTP0 / INTP2 low, INT high, DMARQ1 and HLDRQ high
    lv = {"INTP0": 0, "INTP2": 0, "INT": 1, "DMARQ1": 1, "HLDRQ": 1}
    T.append(PTest("in_levels", jitter=False,
                   pre=ev("E0") + wait(30, "a"),
                   code=(srd("P1", "{S}") + srd("P2", "{S}+1") + ev("E1") + wait(30, "b")
                         + srd("P1", "{S}+2") + srd("P2", "{S}+3")),
                   stim=[{"event": "E0", "delay": 100, "levels": lv},
                         {"event": "E1", "delay": 100,
                          "levels": {k: 1 - v for k, v in lv.items()}}]))
    # P0 as an output: the latch preloaded, the bank released, PM0 00h, the bank claimed; the
    # latch rewritten (pin records); read back; then PM0 FFh and the bank back to H
    T.append(PTest("p0_out", jitter=False, code=(
        swr("P0", 0x5A) + marker(modes(t2=1)) + swr("PM0", 0x00) + marker(modes(t2=2))
        + srd("P0", "{S}") + swr("P0", 0xA5) + srd("P0", "{S}+1") + swr("P0", 0x0F)
        + srd("P0", "{S}+2") + swr("P0", 0xF0) + srd("P0", "{S}+3")
        + "    DB 26h\n    MOV word [0FF00h], 003Ch\n" + srd("P0", "{S}+4")
        + swr("PM0", 0xFF) + marker(modes(t2=1)) + marker(modes(t2=0))
        + srd("P0", "{S}+5") + swr("P0", 0x11) + srd("P0", "{S}+6"))))
    # P1: P14-P17 outputs (T0 and R2 claimed; P13 the /INTAK output so it is driven)
    T.append(PTest("p1_out", jitter=False, code=(
        swr("P1", 0x00) + marker(modes(r2=1, t0=1)) + swr("PMC1", 0x08) + swr("PM1", 0x0F)
        + marker(modes(r2=2, t0=2))
        + srd("P1", "{S}") + swr("P1", 0xF0) + srd("P1", "{S}+1") + swr("P1", 0x50)
        + srd("P1", "{S}+2") + swr("P1", 0xA0) + srd("P1", "{S}+3") + swr("P1", 0x00)
        + srd("P1", "{S}+4")
        + swr("PM1", 0xFF) + swr("PMC1", 0x00) + marker(modes(r2=1, t0=1)) + marker(modes())
        + srd("P1", "{S}+5"))))
    # P2: P21 P22 P24 P25 P26 outputs (R0 claimed; P20 P23 P27 stay inputs: B2 drives them)
    T.append(PTest("p2_out", jitter=False, code=(
        swr("P2", 0x00) + marker(modes(r0=1)) + swr("PM2", 0x89) + marker(modes(r0=2))
        + srd("P2", "{S}") + swr("P2", 0xFF) + srd("P2", "{S}+1") + swr("P2", 0x24)
        + srd("P2", "{S}+2") + swr("P2", 0x52) + srd("P2", "{S}+3") + swr("P2", 0x00)
        + srd("P2", "{S}+4")
        + swr("PM2", 0xFF) + marker(modes(r0=1)) + marker(modes()) + srd("P2", "{S}+5"))))
    # PT with every PMT threshold (the board holds PT0-7 low, VTH = VDD)
    code = ""
    for n in range(16):
        code += swr("PMT", n) + srd("PT", f"{{S}}+{n}")
    T.append(PTest("pt", jitter=False, code=code))
    return T


    return T


# ------------------------------------------------------------------ the timers, the time base
def tm_stop():
    return swr("TMC0", 0x00) + swr("TMC1", 0x00)


def tm_tests():
    T = [init_test()]
    # TM0 interval, SCLK/6, MD0 99: TMIC0 (vector 28) at each count-out
    T.append(PTest("tm0_i6", period=True, psw=PSW_IE,
                   pre=tm_stop() + sfr_ww("MD0", 99) + sfr_ww("TM0", 99) + swr("TMIC0", 0x07)
                   + swr("TMC0", 0x80),
                   code=halts(6) + tm_stop()))
    # TM0 interval, SCLK/128, MD0 9
    T.append(PTest("tm0_i128", period=True, psw=PSW_IE,
                   pre=tm_stop() + sfr_ww("MD0", 9) + sfr_ww("TM0", 9) + swr("TMIC0", 0x07)
                   + swr("TMC0", 0xC0),
                   code=halts(5) + tm_stop()))
    # TM0 interval, MD0 changed while running (the reload takes the new value)
    T.append(PTest("tm0_md", period=True, psw=PSW_IE,
                   pre=tm_stop() + sfr_ww("MD0", 99) + sfr_ww("TM0", 99) + swr("TMIC0", 0x07)
                   + swr("TMC0", 0x80),
                   code=halts(2) + sfr_ww("MD0", 49) + halts(4) + tm_stop()))
    # TM0 one-shot: TM0 50 at SCLK/12 (TS0), MD0 120 at SCLK/12 (MS0): vectors 28 and 29
    T.append(PTest("tm0_os", period=True, psw=PSW_IE,
                   pre=tm_stop() + sfr_ww("MD0", 120) + sfr_ww("TM0", 50) + swr("TMIC0", 0x07)
                   + swr("TMIC1", 0x07) + swr("TMC0", 0xA1),
                   code=halts(2) + wait(80, "a") + sfr_wrd("TM0", "{S}") + sfr_wrd("MD0", "{S}+2")
                   + srd("TMC0", "{S}+4") + srd("TMIC0", "{S}+5") + srd("TMIC1", "{S}+6")
                   + tm_stop()))
    # one-shot at SCLK/128: TM0 5 (TCLK0 1), MD0 9 (MCLK 1)
    T.append(PTest("tm0_os128", period=True, psw=PSW_IE,
                   pre=tm_stop() + sfr_ww("MD0", 9) + sfr_ww("TM0", 5) + swr("TMIC0", 0x07)
                   + swr("TMIC1", 0x07) + swr("TMC0", 0xF1),
                   code=halts(2) + wait(80, "a") + sfr_wrd("TM0", "{S}") + sfr_wrd("MD0", "{S}+2")
                   + srd("TMC0", "{S}+4") + tm_stop()))
    # one-shot: TM0 only (TS0), then MD0 only (MS0)
    T.append(PTest("tm0_os1", period=False, psw=PSW_IE,
                   pre=tm_stop() + sfr_ww("MD0", 30) + sfr_ww("TM0", 20) + swr("TMIC0", 0x07)
                   + swr("TMIC1", 0x07) + swr("TMC0", 0x81),
                   code=halts(1) + wait(30, "a") + srd("TMC0", "{S}") + sfr_wrd("MD0", "{S}+2")
                   + swr("TMC0", 0x21) + halts(1) + wait(30, "b") + srd("TMC0", "{S}+1")
                   + sfr_wrd("TM0", "{S}+4") + srd("TMIC0", "{S}+6") + srd("TMIC1", "{S}+7")
                   + tm_stop()))
    # TM1 interval, SCLK/6, MD1 99: TMIC1 (vector 29; TMIC2 masked, its IF read after)
    T.append(PTest("tm1_i6", period=True, psw=PSW_IE,
                   pre=tm_stop() + sfr_ww("MD1", 99) + sfr_ww("TM1", 99) + swr("TMIC1", 0x07)
                   + swr("TMIC2", 0x47) + swr("TMC1", 0x80),
                   code=halts(6) + tm_stop() + srd("TMIC2", "{S}")))
    # TM1 interval, SCLK/128, MD1 9: TMIC2 (vector 30; TMIC1 masked, its IF read after)
    T.append(PTest("tm1_i128", period=True, psw=PSW_IE,
                   pre=tm_stop() + sfr_ww("MD1", 9) + sfr_ww("TM1", 9) + swr("TMIC1", 0x47)
                   + swr("TMIC2", 0x07) + swr("TMC1", 0xC0),
                   code=halts(5) + tm_stop() + srd("TMIC1", "{S}")))
    # both timers: TM0 /6 MD0 149, TM1 /6 MD1 99 (TMIC2 masked)
    T.append(PTest("tm01", period=True, psw=PSW_IE,
                   pre=tm_stop() + sfr_ww("MD0", 149) + sfr_ww("TM0", 149) + sfr_ww("MD1", 99)
                   + sfr_ww("TM1", 99) + swr("TMIC0", 0x07) + swr("TMIC1", 0x07)
                   + swr("TMC1", 0x80) + swr("TMC0", 0x80),
                   code=halts(10) + tm_stop()))
    # the registers stopped: written, read back by word and byte
    T.append(PTest("tm_regs", jitter=False,
                   code=tm_stop() + sfr_ww("TM0", 0x1234) + sfr_ww("MD0", 0x5678)
                   + sfr_ww("TM1", 0x9ABC) + sfr_ww("MD1", 0xDEF0)
                   + sfr_wrd("TM0", "{S}") + sfr_wrd("MD0", "{S}+2") + sfr_wrd("TM1", "{S}+4")
                   + sfr_wrd("MD1", "{S}+6") + srd("TM0", "{S}+8") + srd("MD0", "{S}+9")
                   + srd("TMC0", "{S}+10") + srd("TMC1", "{S}+11")))
    # a stopped timer keeps its count: started, stopped, read twice (the difference 0; ran 1)
    T.append(PTest("tm_hold", jitter=False,
                   code=tm_stop() + sfr_ww("TM0", 0x8000) + sfr_ww("MD0", 0x8000)
                   + swr("TMC0", 0x80) + wait(10, "a") + swr("TMC0", 0x00)
                   + "    DB 26h\n    MOV BW, [0FF80h]\n" + wait(10, "b") + "    DB 26h\n    MOV AW, [0FF80h]\n"
                   + "    SUB AW, BW\n    DB 2Eh\n    MOV [{S}], AW\n    MOV CL, 0\n    CMP BW, 8000h\n"
                   + "    BE th{k}\n    MOV CL, 1\nth{k}:\n    DB 2Eh\n    MOV [{S}+2], CL\n    MOV BW, 0010h\n"
                   # (F4d) the flags from the stored difference (0 when the stopped count held),
                   # not from CMP BW: the slot's PSW was the parity of the raw count, a timed value
                   + "    TEST AW, AW\n"))
    return T


def tout_tests():
    T = [init_test()]
    # TOUT on P15 (PMC1 bit 5; R2 claimed, P13 the /INTAK output): interval /6, MD0 99
    on = (marker(modes(r2=1)) + swr("PM1", 0x9F) + swr("PMC1", 0x28) + marker(modes(r2=2)))
    off = swr("PMC1", 0x00) + swr("PM1", 0xFF) + marker(modes(r2=1)) + marker(modes())
    run = sfr_ww("MD0", 99) + sfr_ww("TM0", 99) + swr("TMIC0", 0x07)
    for nm, tmc in (("alv1", 0x8C), ("alv0", 0x88), ("ent0", 0x84)):
        T.append(PTest(f"tout_{nm}", period=True, psw=PSW_IE,
                       pre=tm_stop() + swr("P1", 0x00) + on + run + swr("TMC0", tmc),
                       code=halts(5) + tm_stop() + wait(4, "z") + off))
    # ALV written while running (after 3 count-outs), stopped after 2 more (an odd total)
    T.append(PTest("tout_flip", period=False, psw=PSW_IE,
                   pre=tm_stop() + swr("P1", 0x00) + on + run + swr("TMC0", 0x8C),
                   code=halts(3) + swr("TMC0", 0x88) + halts(2) + swr("TMC0", 0x08)
                   + wait(4, "a") + swr("TMC0", 0x0C) + wait(4, "b") + swr("TMC0", 0x00)
                   + wait(4, "c") + off))
    # one-shot with TOUT (TM0 50, MD0 120 at SCLK/12; ENT0 1)
    T.append(PTest("tout_os", period=True, psw=PSW_IE,
                   pre=tm_stop() + swr("P1", 0x00) + on + sfr_ww("MD0", 120) + sfr_ww("TM0", 50)
                   + swr("TMIC0", 0x07) + swr("TMIC1", 0x07) + swr("TMC0", 0xA9),
                   code=halts(2) + wait(40, "a") + tm_stop() + wait(4, "z") + off))
    # TM0 below MD0 at the start (TM0 20, MD0 99), then TMC0 rewritten (80h -> 88h) mid-period
    T.append(PTest("tout_rs", period=False, psw=PSW_IE,
                   pre=tm_stop() + swr("P1", 0x00) + on + sfr_ww("MD0", 99) + sfr_ww("TM0", 20)
                   + swr("TMIC0", 0x07) + swr("TMC0", 0x88),
                   code=halts(2) + wait(6, "a") + swr("TMC0", 0x88) + halts(2) + tm_stop()
                   + wait(4, "z") + off))
    # the stop with ENT0 1 after two count-outs, a second start, a stop after one
    T.append(PTest("tout_h1", period=False, psw=PSW_IE,
                   pre=tm_stop() + swr("P1", 0x00) + on + run + swr("TMC0", 0x88),
                   code=halts(2) + swr("TMC0", 0x08) + wait(6, "a") + swr("TMC0", 0x88)
                   + halts(1) + swr("TMC0", 0x00) + wait(6, "b") + off))
    # ENT0 cleared while running (88h -> 80h), a count-out, the stop with ENT0 0
    T.append(PTest("tout_h2", period=False, psw=PSW_IE,
                   pre=tm_stop() + swr("P1", 0x00) + on + run + swr("TMC0", 0x88),
                   code=halts(1) + swr("TMC0", 0x80) + halts(1) + swr("TMC0", 0x00)
                   + wait(6, "b") + off))
    # ENT0 and ALV written with the timer stopped (the level the pin takes)
    T.append(PTest("tout_ent", jitter=False,
                   pre=tm_stop() + swr("P1", 0x00) + on,
                   code=swr("TMC0", 0x0C) + wait(4, "a") + swr("TMC0", 0x08) + wait(4, "b")
                   + swr("TMC0", 0x04) + wait(4, "c") + swr("TMC0", 0x00) + wait(4, "d") + off))
    return T


def tb_tests(long=False):
    T = [init_test()]
    # the time base (PRC TB; PCK fX/8, RAMEN 1): TBIC (vector 31)
    for tb, n in (((2, 3),) if long else ((0, 12), (1, 4))):
        T.append(PTest(f"tb{tb}", period=True, psw=PSW_IE,
                       pre=swr("PRC", 0x42 | tb << 2) + swr("TBIC", 0x07),
                       code=halts(n) + swr("TBIC", 0x47) + swr("PRC", 0x4E)))
    return T


def _prog(name, tests, pins=(), gate=True, note="", p0=0, fast=()):
    prog = make_program(name, tests, note=note, gate=gate,
                        extra=fast_area(fast) if fast else None)
    if pins:
        prog.stim = dict(prog.stim or {"entries": []}, pins=list(pins))
    prog.results.append((COUNTS, 0x20))
    prog.p0 = p0
    return prog


PORT_PINS = ["P00", "P01", "P02", "P03", "P04", "P05", "P06", "P07", "P13", "P14", "P15", "P16",
             "P17", "P21", "P22", "P24", "P25", "P26"]
TV = (28, 29, 30, 31)


def programs():
    return {
        "f4_port": _prog("f4_port", port_tests(), pins=PORT_PINS, p0=P0_IN,
                         note="P0 P1 P2 PT as inputs and outputs"),
        "f4_tm": _prog("f4_tm", tm_tests(), fast=TV,
                       note="TM0 / TM1: interval, one-shot, registers"),
        "f4_tout": _prog("f4_tout", tout_tests(), pins=["P13", "P15"], fast=TV,
                         note="TOUT on P15"),
        "f4_tb": _prog("f4_tb", tb_tests(), fast=TV, note="the time base, 2^10 and 2^13"),
        "f4_tbl": _prog("f4_tbl", tb_tests(True), fast=TV, gate=False,
                        note="measured only: the time base at 2^16"),
    }


# ------------------------------------------------------------------ running
def receipt_path(name, backend):
    return RECEIPTS / f"f4-{name}-{backend}.json"


def save(rec, name, backend):
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    receipt_path(name, backend).write_text(json.dumps(rec, indent=1) + "\n")


def load(name, backend):
    return json.loads(receipt_path(name, backend).read_text())


def run_one(harness, prog, lane, limit=40_000_000):
    """onchip.run_one with the pin records and the stubs' store ticks kept."""
    from .onchip import _io_reads, _write_sequence
    from .runner import FLAG_IO, FLAG_PIN, FLAG_READ, FLAG_STROBE
    code, segments, pages = prog.image()
    harness.load(segments, pages)
    mode = "socket" if lane == "socket" else "model"
    result = harness.run(mode, limit)
    trace = list(result[f"{lane}_trace"])
    replay = []
    total = result[f"{lane}_total"]
    for start in range(2048, total, 2048):
        harness.load(segments, pages)
        window = harness.run(mode, limit, capture_start=start)
        for field in ("total", "signature"):
            if window[f"{lane}_{field}"] != result[f"{lane}_{field}"]:
                replay.append(f"{field} changed at window {start}")
        trace.extend(window[f"{lane}_trace"])
    regions = {f"{a:05X}": harness.read_memory(lane, a, n).hex() for a, n in prog.results}
    pins = [[t["start"], (t["address"] & 0xFFFF) | (t["data"] << 16)] for t in trace
            if t["flags"] & FLAG_PIN]
    # the stub's store: MOV CS:[8002h], n (LOG + 2); the test's number: CS:[8004h] (LOG + 4)
    stubs, k = [], -1
    for t in trace:
        if t["flags"] & FLAG_STROBE and not t["flags"] & (FLAG_READ | FLAG_IO):
            if t["address"] == LOG + 4:
                k = t["data"]
            elif t["address"] == LOG + 2:
                stubs.append([t["start"], t["data"] & 0xFF, k])
    tests = [[t["start"], t["data"]] for t in trace
             if t["flags"] & FLAG_STROBE and not t["flags"] & (FLAG_READ | FLAG_IO)
             and t["address"] == LOG + 4]
    return {
        "program": prog.name, "note": prog.note, "gate": prog.gate,
        "program_sha256": hashlib.sha256(code).hexdigest(),
        "passed": result["passed"], "status": result["status"], "timeout": result["timeout"],
        "total": total, "markers": result["markers"], "last_marker": result["last_marker"],
        "writes": _write_sequence(trace), "io_reads": _io_reads(trace), "regions": regions,
        "pins": pins, "stubs": stubs, "tests": tests, "replay": replay,
        "stimulus": result.get("stimulus"),
        "trace_tail": [[t["address"], t["data"], t["flags"]] for t in trace[-24:]],
    }


def _stim(harness, prog):
    from .traps import _stim as stim
    stim(harness, prog)
    harness.debug.write16(0x8C, getattr(prog, "p0", 0))


def run_set(names, backend, tag="", progs=None, limit=40_000_000):
    from .traps import _board, _close_board, _sim
    progs = progs or programs()
    lane = "socket" if backend == "socket" else "model"
    if backend == "socket":
        transport, harness = _board()
    try:
        for name in names:
            if backend != "socket":
                transport, harness = _sim()
            try:
                _stim(harness, progs[name])
                rec = run_one(harness, progs[name], lane, limit=limit)
            finally:
                if backend != "socket":
                    transport.close()
            rec.update(backend=backend, date=datetime.datetime.now().isoformat(timespec="seconds"),
                       stim=progs[name].stim, levels=progs[name].levels, p0=progs[name].p0)
            if backend == "socket":
                rec.update(cpu="uPD70337L-8", x_half=2)
            else:
                rec.update(core="v35", binary=os.environ.get(
                    "V35_SIM_BINARY", "build/fpga/v35s/verilator-direct-v35"))
            save(rec, name, backend + tag)
            print(f"{name}: {backend} {'PASS' if rec['passed'] else 'FAIL'} "
                  f"status=0x{rec['status']:04x} writes={len(rec['writes'])} total={rec['total']}"
                  f" pins={len(rec['pins'])} stubs={len(rec['stubs'])}", flush=True)
    finally:
        if backend == "socket":
            _close_board(transport, harness)


# ------------------------------------------------------------------ reading
def stub_runs(rec, prog):
    """Per test: [(vector, tick)] of its stub stores (a test is entered by its number's store)."""
    out = {}
    for tick, vec, k in rec["stubs"]:
        out.setdefault(k, []).append((vec, tick))
    return out


def periods(rec, prog):
    """Per test with a period: {"d": the tick differences of its successive stub stores}."""
    runs = stub_runs(rec, prog)
    out = {}
    for k, t in enumerate(prog.tests):
        if getattr(t, "period", False):
            ticks = [tk for _, tk in runs.get(k, [])]
            out[t.name] = {"d": [b - a for a, b in zip(ticks, ticks[1:])]}
    return out


# the TOUT half-periods the f4_tout programs use, in ticks: (MD0 + 1) x 6 clocks, MD0 99
EXACT = {600 * CLK}


def settle_ticks(pins, ticks=16):
    """The ticks of settle()'s records."""
    out, last = [], None
    for i, (tk, v) in enumerate(pins):
        if i + 1 < len(pins) and pins[i + 1][0] - tk < ticks:
            continue
        if last != v:
            out.append(tk)
            last = v
    return out


def settle(pins, ticks=16):
    """The pin vectors that stood at least `ticks` (a bank's hand-over shows the bus keepers'
    level for a few ticks while the translator turns: not the CPU's)."""
    out = []
    for i, (tk, v) in enumerate(pins):
        if i + 1 < len(pins) and pins[i + 1][0] - tk < ticks:
            continue
        if not out or out[-1] != v:
            out.append(v)
    return out
def show(name, backend="socket", progs=None):
    progs = progs or programs()
    prog = progs[name]
    rec = load(name, backend)
    intr.show_rec = None
    count, entries, slots = intr.decode(rec)
    print(f"{name} ({backend}): passed {rec['passed']} status {rec['status']:04x} log {count}"
          f" pins {len(rec['pins'])} stubs {len(rec['stubs'])}")
    runs = stub_runs(rec, prog)
    for k, t in enumerate(prog.tests):
        s = slots[k] if k < len(slots) else {}
        print(f"{k:2d} {t.name:12s} scr={s.get('scratch', '')} ispr={s.get('ispr', 0):02X}"
              f" tmic0={s.get('tmic0', 0):02X} n={s.get('count', 0)}")
        r = runs.get(k, [])
        if r:
            t0 = r[0][1]
            print(f"     stubs @{t0}: " + " ".join(f"v{v}@{(tk - t0) / CLK:g}" for v, tk in r))
    for t, d in periods(rec, prog).items():
        print(f"   period {t}: " + "; ".join(
            f"v{v}: " + " ".join(f"{x / CLK:g}" for x in xs) for v, xs in d.items()))
    if rec["pins"]:
        p0 = rec["pins"][0][0]
        print(f"   pins @{p0}: " + " ".join(f"{v:08X}@{(tk - p0) / CLK:g}" for tk, v in rec["pins"]))


# ------------------------------------------------------------------ the gate
def compare_gate(names, ref="socket", cand="sim", progs=None):
    from .onchip import _masked_writes
    progs = progs or programs()
    ok_all = True
    for name in names:
        prog = progs[name]
        a, b = load(name, ref), load(name, cand)
        ex = _jitter(name, a, prog)
        wa, wb = _masked_writes(a["writes"], ex), _masked_writes(b["writes"], ex)
        diffs = []
        for key in a["regions"]:
            base = int(key, 16)
            ra, rb = bytes.fromhex(a["regions"][key]), bytes.fromhex(b["regions"].get(key, ""))
            diffs += [(base + i, ra[i], rb[i] if i < len(rb) else -1) for i in range(len(ra))
                      if base + i not in ex and (i >= len(rb) or ra[i] != rb[i])]
        pa, pb = settle(a["pins"]), settle(b["pins"])
        per_a, per_b = periods(a, prog), periods(b, prog)
        bad_per = []
        for t in per_a:
            for v in per_a[t]:
                xa, xb = per_a[t][v], per_b.get(t, {}).get(v, [])
                if len(xa) != len(xb) or any(abs(x - y) > PERIOD_TOL for x, y in zip(xa, xb)):
                    bad_per.append(f"{t} v{v} {[x / CLK for x in xa]} / {[x / CLK for x in xb]}")
        # the exact periods: every interval between successive settled pin records that is one
        # TOUT half-period on the socket (EXACT, in clocks) is the same number of ticks on both
        ia, ib = settle_ticks(a["pins"]), settle_ticks(b["pins"])
        n_ex, bad_ex = 0, []
        if pa == pb:
            for i in range(1, len(ia)):
                da, db = ia[i] - ia[i - 1], ib[i] - ib[i - 1]
                if da in EXACT:
                    n_ex += 1
                    if da != db:
                        bad_ex.append(f"#{i} {da / CLK}/{db / CLK}")
        if bad_per:
            bad_per.append(f"(tolerance {PERIOD_TOL / CLK:g} clocks)")
        ok = (wa == wb and not diffs and a["passed"] == b["passed"] and pa == pb
              and not bad_per and not bad_ex)
        ok_all &= ok
        first = next((i for i, (x, y) in enumerate(zip(wa, wb)) if x != y), None)
        print(f"{name}: gate {'EQUAL' if ok else 'DIFFER'} writes {len(wa)}/{len(wb)}"
              + ("" if first is None else
                 f" first difference at {first}: {wa[first][0]:05X} {wa[first][1]:04X} "
                 f"{wa[first][2]:03X} / {wb[first][0]:05X} {wb[first][1]:04X} {wb[first][2]:03X}")
              + f" pins {len(pa)}/{len(pb)} {'equal' if pa == pb else 'differ'}"
              + f" periods {'equal' if not bad_per else 'differ: ' + '; '.join(bad_per)}"
              + f" exact intervals {n_ex - len(bad_ex)}/{n_ex}"
              + ("" if not bad_ex else " differ: " + " ".join(bad_ex[:8]))
              + f" passed {a['passed']}/{b['passed']}"
              + ("" if not diffs else " result bytes differ: " +
                 ", ".join(f"{x:05X}:{y:02X}/{z:02X}" for x, y, z in diffs[:16])
                 + (f" (+{len(diffs) - 16})" if len(diffs) > 16 else "")))
    return ok_all


def _jitter(name, rec, prog):
    """intr.jitter_bytes for this program's tests (the stack; the jitter tests' log entries but
    their vector, depth, test, ISPR and IC bytes)."""
    ex = set(intr.STACK)
    _, entries, _ = intr.decode(rec)
    for i, e in enumerate(entries):
        if e["test"] < len(prog.tests) and prog.tests[e["test"]].jitter:
            base = LOG + 0x100 + 32 * i
            ex |= {base + j for j in range(32) if not (j < 4 or 14 <= j < 20 or 28 <= j < 30)}
    return ex


def emit(progs=None):
    for name, prog in (progs or programs()).items():
        path = PROGRAMS_DIR / f"{name}.s"
        path.write_text(f"; F4 ({prog.note}). Generated by validation/v35s/periph.py emit: the\n"
                        f"; image also preloads intr.py's vector stubs, handler and data.\n"
                        + prog.source)
        stim = PROGRAMS_DIR / f"{name}.stim.json"
        if prog.stim:
            stim.write_text(json.dumps(prog.stim, indent=1) + "\n")
        print(path)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "gate", "show", "emit", "size"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    a = p.parse_args()
    progs = programs()
    names = a.names or [n for n, prog in progs.items() if a.action == "socket" or prog.gate]
    if a.action in ("socket", "sim"):
        run_set(names, a.action, a.tag, progs)
    elif a.action == "gate":
        return 0 if compare_gate(names, a.ref, a.cand, progs) else 1
    elif a.action == "show":
        for n in names:
            show(n, a.ref, progs)
    elif a.action == "size":
        for n in names:
            code, _, _ = progs[n].image()
            print(n, f"{len(code)} bytes, {len(progs[n].tests)} tests, "
                  f"{len((progs[n].stim or {}).get('entries', []))} entries")
    else:
        emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
