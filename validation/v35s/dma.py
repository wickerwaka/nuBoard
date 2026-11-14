"""F4 part C: DMA, bus hold, READY, STBC / STOP (docs/v35s-function-plan.md, stage F4).

Directed programs measured on the socketed uPD70337 and run unchanged on the core v2 RTL in
simulation, in validation/v35s/periph.py's frame (intr.py's Test, slots and handler; periph's
run, receipts, pin records and gate; serial.py's helpers):

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.dma socket [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.dma sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.dma gate [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.dma show NAME [--ref socket]
    PYTHONPATH=host/src:. python3 -m validation.v35s.dma emit

The gated program is f4_dma (README "F4 (part C)"): the channel block written through DS1 = F000h,
the channel started by TDMA or by DMARQ edges from the schedule, markers (`cws`: one CPU byte store
an instruction) and wait loops; the source page F000h's reads are kept in the write sequence in
their places (`_with_dma_reads`), so where each transfer lands is compared by sequence. The gate
masks the data of I/O-to-memory transfers (`Test.mask`: the device's, not the CPU's) and settles
the pin records over 8 ticks. Measured only (gate False): f4_dmx, f4_dmi, f4_dm2, f4_dm3 (the
exploration that led f4_dma; f4_dmx / f4_dmi were taken before blk_w stored SARH before DARH, so
their receipts' program hashes differ from the emitted text by that order alone), f4_hx (bus hold,
STBC, STOP) and f4_rdy (READY and WTC: the harness's READY hold, register 0Ah, is 160 ticks for it).
`--trace` keeps every trace record in the receipt.

Receipts: validation/v35s/receipts/f4-<name>-<backend>.json (--tag adds a suffix).
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

from . import periph, serial
from .intr import PSW_IE, ev, pulse, wait
from .periph import PTest, _prog
from .serial import _fix, rd, swr

RES = serial.RES                 # 0xC000: 0x20 bytes per test
SRC = 0xE000                     # the DMA source page (preloaded)
DST = 0xF000                     # the DMA destination page (preloaded)
SFR = dict(serial.SFR, DMAC0=0xA0, DMAM0=0xA1, DMAC1=0xA2, DMAM1=0xA3, DIC0=0xAC, DIC1=0xAD,
           STBC=0xE0)
serial.SFR.update(SFR)


def blk_w(ch, sar, dar, sarh, darh, tc):
    """The DMA channel block at IDB:E00 + 8 ch, through DS1 = F000h: +0 SAR, +2 DAR, +4 DARH,
    +5 SARH, +6 TC (f4_dmx: the source address is SARH at +5)."""
    a = 0xFE00 + 8 * ch
    h = periph._h
    return (f"    DB 26h\n    MOV word [{h(a, 4)}], {h(sar, 4)}\n"
            f"    DB 26h\n    MOV word [{h(a + 2, 4)}], {h(dar, 4)}\n"
            f"    DB 26h\n    MOV byte [{h(a + 5, 4)}], {h(sarh)}\n"
            f"    DB 26h\n    MOV byte [{h(a + 4, 4)}], {h(darh)}\n"
            f"    DB 26h\n    MOV word [{h(a + 6, 4)}], {h(tc, 4)}\n")


def blk_rd(ch, k, i):
    return serial.chan_rd(ch, k, i)


def explore_tests():
    T = [periph.init_test()]
    # the reset values of the DMA SFRs
    t = PTest("regs", jitter=False)
    t.codef = lambda k: (rd("DMAC0", k, 0) + rd("DMAM0", k, 1) + rd("DMAC1", k, 2) + rd("DMAM1", k, 3)
                         + rd("DIC0", k, 4) + rd("DIC1", k, 5) + rd("STBC", k, 6))
    T.append(t)
    # burst, memory to memory, channel 0, software trigger, 4 bytes, both incremented
    t = PTest("burst0", jitter=False)
    t.codef = lambda k: (swr("DIC0", 0x47) + blk_w(0, 0x0010, 0x0020, 0x0F, 0x0E, 4)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0x8C) + wait(30, "a")
                         + blk_rd(0, k, 0) + rd("DMAC0", k, 8) + rd("DMAM0", k, 9) + rd("DIC0", k, 10)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47))
    T.append(t)
    # single step, memory to memory, channel 1, software trigger, 3 bytes, INC AW between
    t = PTest("step1", jitter=False)
    t.codef = lambda k: (swr("DIC1", 0x47) + blk_w(1, 0x0040, 0x0050, 0x0F, 0x0E, 3)
                         + swr("DMAC1", 0x11) + swr("DMAM1", 0x0C) + "    INC AW\n" * 8
                         + wait(30, "a") + blk_rd(1, k, 0) + rd("DMAC1", k, 8) + rd("DMAM1", k, 9)
                         + rd("DIC1", k, 10) + swr("DMAM1", 0x00) + swr("DIC1", 0x47))
    T.append(t)
    # burst, words, source incremented, destination decremented
    t = PTest("burstw", jitter=False)
    t.codef = lambda k: (swr("DIC0", 0x47) + blk_w(0, 0x0080, 0x00A0, 0x0F, 0x0E, 3)
                         + swr("DMAC0", 0x21) + swr("DMAM0", 0x9C) + wait(30, "a")
                         + blk_rd(0, k, 0) + rd("DMAC0", k, 8) + rd("DMAM0", k, 9) + rd("DIC0", k, 10)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47))
    T.append(t)
    return _fix(T)


def io_tests():
    T = [periph.init_test()]
    on = (periph.marker(periph.modes(r0=1)) + swr("PMC2", 0x7F) + periph.marker(periph.modes(r0=2)))
    off = swr("PMC2", 0x00) + periph.marker(periph.modes(r0=1)) + periph.marker(periph.modes())
    # single transfer, I/O to memory, channel 0, DMARQ0 pulses
    t = PTest("io_in0", jitter=False,
              stim=[{"event": "E0", "delay": 2000, "hold": 400, "levels": {"DMARQ0": 1}},
                    {"event": "E1", "delay": 2000, "hold": 400, "levels": {"DMARQ0": 1}},
                    {"event": "E2", "delay": 2000, "hold": 400, "levels": {"DMARQ0": 1}}])
    t.codef = lambda k: (swr("DIC0", 0x47) + on + blk_w(0, 0x0010, 0x0030, 0x0F, 0x0E, 3)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0xA8)
                         + ev("E0") + wait(40, "a") + blk_rd(0, k, 0)
                         + ev("E1") + wait(40, "b") + ev("E2") + wait(40, "c")
                         + blk_rd(0, k, 8) + rd("DMAM0", k, 16) + rd("DIC0", k, 17)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47) + off)
    T.append(t)
    # single transfer, memory to I/O, channel 1, DMARQ1 pulses
    t = PTest("io_out1", jitter=False,
              stim=[{"event": "E0", "delay": 2000, "hold": 400, "levels": {"DMARQ1": 1}},
                    {"event": "E1", "delay": 2000, "hold": 400, "levels": {"DMARQ1": 1}}])
    t.codef = lambda k: (swr("DIC1", 0x47) + on + blk_w(1, 0x0060, 0x0070, 0x0F, 0x0E, 2)
                         + swr("DMAC1", 0x11) + swr("DMAM1", 0xC8)
                         + ev("E0") + wait(40, "a") + blk_rd(1, k, 0)
                         + ev("E1") + wait(40, "b")
                         + blk_rd(1, k, 8) + rd("DMAM1", k, 16) + rd("DIC1", k, 17)
                         + swr("DMAM1", 0x00) + swr("DIC1", 0x47) + off)
    T.append(t)
    # demand release, I/O to memory, channel 0: DMARQ0 high for ~3 transfers' worth
    t = PTest("io_dem0", jitter=False,
              stim=[{"event": "E0", "delay": 2000, "hold": 1200, "levels": {"DMARQ0": 1}}])
    t.codef = lambda k: (swr("DIC0", 0x47) + on + blk_w(0, 0x0090, 0x00B0, 0x0F, 0x0E, 8)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0x28)
                         + ev("E0") + wait(60, "a") + blk_rd(0, k, 0) + rd("DMAM0", k, 8)
                         + rd("DIC0", k, 9) + swr("DMAM0", 0x00) + swr("DIC0", 0x47) + off)
    T.append(t)
    return _fix(T)


def cw(k, n, v):
    """A CPU write (a marker in the write sequence): byte v at RES + 0x20 k + 0x18 + n."""
    return f"    DB 2Eh\n    MOV byte [{periph._h(RES + 0x20 * k + 0x18 + n, 4)}], {periph._h(v)}\n"


def cws(k, n):
    return "".join(cw(k, i, 0xA0 + i) for i in range(n))


ON0 = (periph.marker(periph.modes(r0=1)) + swr("PMC2", 0x7F) + periph.marker(periph.modes(r0=2)))
OFF0 = swr("PMC2", 0x00) + periph.marker(periph.modes(r0=1)) + periph.marker(periph.modes())


def rq(ev_, ch, delay=2000, hold=400):
    return {"event": ev_, "delay": delay, "hold": hold, "levels": {f"DMARQ{ch}": 1}}


def x2_tests():
    T = [periph.init_test()]
    # single step, memory to memory, TDMA: CPU writes after the store (where each transfer lands)
    t = PTest("step_w", jitter=False)
    t.codef = lambda k: (swr("DIC0", 0x47) + blk_w(0, 0x0010, 0x0020, 0x0F, 0x0E, 4)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0x0C) + cws(k, 8)
                         + blk_rd(0, k, 0) + rd("DMAM0", k, 8) + rd("DIC0", k, 9)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47))
    T.append(t)
    # burst, TDMA, then CPU writes
    t = PTest("burst_w", jitter=False)
    t.codef = lambda k: (swr("DIC0", 0x47) + blk_w(0, 0x0030, 0x0040, 0x0F, 0x0E, 3)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0x8C) + cws(k, 6)
                         + blk_rd(0, k, 0) + rd("DMAM0", k, 8) + rd("DIC0", k, 9)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47))
    T.append(t)
    # burst, memory to memory, started by DMARQ0 (no TDMA); SARH 0E + SAR 1020h (F020h?)
    t = PTest("burst_rq", jitter=False, stim=[rq("E0", 0)])
    t.codef = lambda k: (swr("DIC0", 0x47) + blk_w(0, 0x1020, 0x1060, 0x0E, 0x0D, 3)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0x88) + ev("E0") + wait(60, "a")
                         + blk_rd(0, k, 0) + rd("DMAM0", k, 8) + rd("DIC0", k, 9)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47))
    T.append(t)
    # single step started by DMARQ1, channel 1, CPU writes in a loop meanwhile
    t = PTest("step_rq", jitter=False, stim=[rq("E0", 1, delay=200)])
    t.codef = lambda k: (swr("DIC1", 0x47) + blk_w(1, 0x0070, 0x0080, 0x0F, 0x0E, 3)
                         + swr("DMAC1", 0x11) + swr("DMAM1", 0x08) + ev("E0") + wait(20, "a")
                         + cws(k, 8) + blk_rd(1, k, 0) + rd("DMAM1", k, 8) + rd("DIC1", k, 9)
                         + swr("DMAM1", 0x00) + swr("DIC1", 0x47))
    T.append(t)
    # demand release, I/O to memory, DMARQ0 high ~400 clocks, CPU writes meanwhile
    t = PTest("dem_w", jitter=False, stim=[rq("E0", 0, delay=100, hold=12800)])
    t.codef = lambda k: (swr("DIC0", 0x47) + ON0 + blk_w(0, 0x0090, 0x00A0, 0x0F, 0x0E, 6)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0x28) + ev("E0") + cws(k, 8)
                         + wait(60, "a") + blk_rd(0, k, 0) + rd("DMAM0", k, 8) + rd("DIC0", k, 9)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47) + OFF0)
    T.append(t)
    # single transfer in HALT: channel 1 I/O to memory, two DMARQ1 pulses, DIC1 (vector 21) wakes
    t = PTest("halt_io", jitter=False, psw=PSW_IE,
              stim=[rq("E0", 1, delay=12000), {"event": None, "delay": 4000, "hold": 400,
                                              "levels": {"DMARQ1": 1}}])
    t.codef = lambda k: (serial.cnt_clr(21) + swr("DIC1", 0x07) + ON0
                         + blk_w(1, 0x00B0, 0x00C0, 0x0F, 0x0E, 2)
                         + swr("DMAC1", 0x11) + swr("DMAM1", 0xA8) + ev("E0")
                         + "    HALT\n    NOP\n    NOP\n" + cw(k, 0, 0x55)
                         + blk_rd(1, k, 0) + rd("DMAM1", k, 8) + rd("DIC1", k, 9)
                         + serial.cnt_rd(21, k, 10)
                         + swr("DMAM1", 0x00) + swr("DIC1", 0x47) + OFF0)
    T.append(t)
    # word I/O to memory (W 1), single transfer, two pulses
    t = PTest("io_w", jitter=False, stim=[rq("E0", 0), rq("E1", 0)])
    t.codef = lambda k: (swr("DIC0", 0x47) + ON0 + blk_w(0, 0x00D0, 0x00E0, 0x0F, 0x0E, 2)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0xB8) + ev("E0") + wait(40, "a")
                         + ev("E1") + wait(40, "b")
                         + blk_rd(0, k, 0) + rd("DMAM0", k, 8) + rd("DIC0", k, 9)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47) + OFF0)
    T.append(t)
    # both channels requested together (burst, memory to memory): which goes first
    t = PTest("both", jitter=False,
              stim=[{"event": "E0", "delay": 2000, "hold": 400, "levels": {"DMARQ0": 1, "DMARQ1": 1}}])
    t.codef = lambda k: (swr("DIC0", 0x47) + swr("DIC1", 0x47)
                         + blk_w(0, 0x0000, 0x0000, 0x0F, 0x0D, 3)
                         + blk_w(1, 0x0010, 0x0010, 0x0F, 0x0D, 3)
                         + swr("DMAC0", 0x11) + swr("DMAC1", 0x11)
                         + swr("DMAM0", 0x88) + swr("DMAM1", 0x88) + ev("E0") + wait(60, "a")
                         + blk_rd(0, k, 0) + blk_rd(1, k, 8) + rd("DMAM0", k, 16) + rd("DMAM1", k, 17)
                         + swr("DMAM0", 0x00) + swr("DMAM1", 0x00)
                         + swr("DIC0", 0x47) + swr("DIC1", 0x47))
    T.append(t)
    return _fix(T)


def x3_tests():
    T = [periph.init_test()]
    # TC / DMAAK in the memory-to-memory modes (R0 claimed): burst ch0 3, single step ch1 2
    t = PTest("m2m_pins", jitter=False)
    t.codef = lambda k: (swr("DIC0", 0x47) + swr("DIC1", 0x47) + ON0
                         + blk_w(0, 0x0000, 0x0000, 0x0F, 0x0D, 3)
                         + blk_w(1, 0x0010, 0x0010, 0x0F, 0x0D, 2) + swr("DMAC0", 0x11)
                         + swr("DMAC1", 0x11) + swr("DMAM0", 0x8C) + wait(30, "a")
                         + swr("DMAM1", 0x0C) + wait(30, "b")
                         + blk_rd(0, k, 0) + blk_rd(1, k, 8) + OFF0)
    T.append(t)
    # demand release: DMARQ0 high ~50 clocks (TC 6), then again ~50 clocks, then long
    t = PTest("dem_stop", jitter=False,
              stim=[rq("E0", 0, delay=2000, hold=1600), rq("E1", 0, delay=2000, hold=1600),
                    rq("E2", 0, delay=2000, hold=12000)])
    t.codef = lambda k: (swr("DIC0", 0x47) + ON0 + blk_w(0, 0x0000, 0x0020, 0x0F, 0x0D, 6)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0x28) + ev("E0") + wait(40, "a")
                         + blk_rd(0, k, 0) + ev("E1") + wait(40, "b") + blk_rd(0, k, 8)
                         + ev("E2") + wait(60, "c") + blk_rd(0, k, 16) + rd("DMAM0", k, 24)
                         + swr("DMAM0", 0x00) + OFF0)
    T.append(t)
    # single transfer with DMARQ1 already high when EDMA is set; then it falls and rises
    t = PTest("io_lvl", jitter=False,
              stim=[{"event": "E0", "delay": 100, "levels": {"DMARQ1": 1}},
                    {"event": "E1", "delay": 100, "levels": {"DMARQ1": 0}},
                    {"event": "E2", "delay": 100, "levels": {"DMARQ1": 1}},
                    {"event": "E3", "delay": 100, "levels": {"DMARQ1": 0}}])
    t.codef = lambda k: (swr("DIC1", 0x47) + ON0 + blk_w(1, 0x0000, 0x0040, 0x0F, 0x0D, 4)
                         + swr("DMAC1", 0x11) + ev("E0") + wait(20, "a") + swr("DMAM1", 0xA8)
                         + wait(40, "b") + blk_rd(1, k, 0) + ev("E1") + wait(20, "c")
                         + ev("E2") + wait(40, "d") + blk_rd(1, k, 8) + ev("E3") + wait(20, "e")
                         + swr("DMAM1", 0x00) + OFF0)
    T.append(t)
    # a TDMA store in the I/O single-transfer mode; then EDMA cleared mid single step (TC 6)
    t = PTest("tdma_io", jitter=False)
    t.codef = lambda k: (swr("DIC0", 0x47) + ON0 + blk_w(0, 0x0000, 0x0060, 0x0F, 0x0D, 4)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0xAC) + wait(30, "a")
                         + blk_rd(0, k, 0) + blk_w(0, 0x0000, 0x0070, 0x0F, 0x0D, 6)
                         + swr("DMAM0", 0x0C) + cws(k, 2) + swr("DMAM0", 0x00) + cws(k, 4)
                         + blk_rd(0, k, 8) + rd("DMAM0", k, 16) + OFF0)
    T.append(t)
    return _fix(T)


PINS = ["DMAAK0", "TC0", "DMAAK1", "TC1", "HLDAK"]


def pages():
    return {0xD000: bytes((0x80 + i) & 0xFF for i in range(0x100)),
            SRC: bytes((0x40 + i) & 0xFF for i in range(0x100)),
            DST: bytes((0xC0 + i) & 0xFF for i in range(0x100))}


# ------------------------------------------------------------------ the gated set
DD = 0xD000             # the destinations (0D000h: DARH 0Dh), the sources F000h (SARH 0Fh)


def mask_rng(t, a, n):
    """Bytes the gate masks (the data of an I/O-to-memory transfer: the device's, not the CPU's;
    on the board nobody drives the bus, the socket's writes carry the keepers' level)."""
    t.mask = set(getattr(t, "mask", set())) | set(range(a, a + n))
    return t


def dma_tests():
    T = [periph.init_test()]
    # the reset values (DMAM 00h, DIC 47h)
    t = PTest("regs", jitter=False)
    t.codef = lambda k: (rd("DMAM0", k, 0) + rd("DMAM1", k, 1) + rd("DIC0", k, 2) + rd("DIC1", k, 3))
    T.append(t)
    # single step, memory to memory, TDMA, channel 0: one CPU write, one transfer, alternately
    t = PTest("step_w", jitter=False)
    t.codef = lambda k: (swr("DIC0", 0x47) + ON0 + blk_w(0, 0x0010, 0x0010, 0x0F, 0x0D, 4)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0x0C) + cws(k, 8)
                         + blk_rd(0, k, 0) + rd("DMAM0", k, 8) + rd("DIC0", k, 9)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47) + OFF0)
    T.append(t)
    # burst, TDMA, channel 1: the transfers back to back after one CPU write
    t = PTest("burst_w", jitter=False)
    t.codef = lambda k: (swr("DIC1", 0x47) + ON0 + blk_w(1, 0x0020, 0x0020, 0x0F, 0x0D, 3)
                         + swr("DMAC1", 0x11) + swr("DMAM1", 0x8C) + cws(k, 6)
                         + blk_rd(1, k, 0) + rd("DMAM1", k, 8) + rd("DIC1", k, 9)
                         + swr("DMAM1", 0x00) + swr("DIC1", 0x47) + OFF0)
    T.append(t)
    # burst of words, SAR incremented, DAR decremented
    t = PTest("burst_wd", jitter=False)
    t.codef = lambda k: (swr("DIC0", 0x47) + blk_w(0, 0x0030, 0x0046, 0x0F, 0x0D, 3)
                         + swr("DMAC0", 0x21) + swr("DMAM0", 0x9C) + cws(k, 4)
                         + blk_rd(0, k, 0) + rd("DMAM0", k, 8) + rd("DIC0", k, 9)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47))
    T.append(t)
    # SARH x 1000h + SAR (0Eh, 1050h: F050h), DARH 0Ch + DAR 1050h (D050h); single step with
    # SAR decremented, DAR fixed (PS 10, PD 11)
    t = PTest("addr", jitter=False)
    t.codef = lambda k: (swr("DIC0", 0x47) + blk_w(0, 0x1050, 0x1050, 0x0E, 0x0C, 3)
                         + swr("DMAC0", 0x32) + swr("DMAM0", 0x0C) + cws(k, 6)
                         + blk_rd(0, k, 0) + rd("DMAM0", k, 8) + rd("DIC0", k, 9)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47))
    T.append(t)
    # single transfer, I/O to memory, channel 0: three DMARQ0 edges (each inside a wait loop)
    t = mask_rng(PTest("io_in", jitter=False, stim=[rq("E0", 0), rq("E1", 0), rq("E2", 0)]),
                 DD + 0x60, 3)
    t.codef = lambda k: (swr("DIC0", 0x47) + ON0 + blk_w(0, 0x0070, 0x0060, 0x0F, 0x0D, 3)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0xA8)
                         + ev("E0") + wait(40, "a") + blk_rd(0, k, 0)
                         + ev("E1") + wait(40, "b") + ev("E2") + wait(40, "c")
                         + blk_rd(0, k, 8) + rd("DMAM0", k, 16) + rd("DIC0", k, 17)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47) + OFF0)
    T.append(t)
    # single transfer, memory to I/O, channel 1: two DMARQ1 edges
    t = PTest("io_out", jitter=False, stim=[rq("E0", 1), rq("E1", 1)])
    t.codef = lambda k: (swr("DIC1", 0x47) + ON0 + blk_w(1, 0x0080, 0x0080, 0x0F, 0x0D, 2)
                         + swr("DMAC1", 0x11) + swr("DMAM1", 0xC8)
                         + ev("E0") + wait(40, "a") + blk_rd(1, k, 0)
                         + ev("E1") + wait(40, "b")
                         + blk_rd(1, k, 8) + rd("DMAM1", k, 16) + rd("DIC1", k, 17)
                         + swr("DMAM1", 0x00) + swr("DIC1", 0x47) + OFF0)
    T.append(t)
    # demand release, I/O to memory: DMARQ0 high ~400 clocks, TC 6 (all six back to back)
    t = mask_rng(PTest("demand", jitter=False, stim=[rq("E0", 0, delay=100, hold=12800)]),
                 DD + 0x90, 6)
    t.codef = lambda k: (swr("DIC0", 0x47) + ON0 + blk_w(0, 0x0090, 0x0090, 0x0F, 0x0D, 6)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0x28) + ev("E0") + wait(40, "a")
                         + cws(k, 4) + wait(40, "b") + blk_rd(0, k, 0) + rd("DMAM0", k, 8)
                         + rd("DIC0", k, 9) + swr("DMAM0", 0x00) + swr("DIC0", 0x47) + OFF0)
    T.append(t)
    # single transfer in HALT (channel 1, I/O to memory, two edges); DIC1 (vector 21) wakes it
    t = mask_rng(PTest("halt", jitter=False, psw=PSW_IE,
                       stim=[rq("E0", 1, delay=12000),
                             {"event": None, "delay": 4000, "hold": 400, "levels": {"DMARQ1": 1}}]),
                 DD + 0xB0, 2)
    t.codef = lambda k: (serial.cnt_clr(21) + swr("DIC1", 0x07) + ON0
                         + blk_w(1, 0x00B0, 0x00B0, 0x0F, 0x0D, 2)
                         + swr("DMAC1", 0x11) + swr("DMAM1", 0xA8) + ev("E0")
                         + "    HALT\n    NOP\n    NOP\n" + cw(k, 0, 0x55)
                         + blk_rd(1, k, 0) + rd("DMAM1", k, 8) + rd("DIC1", k, 9)
                         + serial.cnt_rd(21, k, 10)
                         + swr("DMAM1", 0x00) + swr("DIC1", 0x47) + OFF0)
    T.append(t)
    # words, I/O to memory, two edges (DAR + 2 each)
    t = mask_rng(PTest("io_word", jitter=False, stim=[rq("E0", 0), rq("E1", 0)]), DD + 0xC0, 4)
    t.codef = lambda k: (swr("DIC0", 0x47) + ON0 + blk_w(0, 0x00C0, 0x00C0, 0x0F, 0x0D, 2)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0xB8) + ev("E0") + wait(40, "a")
                         + ev("E1") + wait(40, "b")
                         + blk_rd(0, k, 0) + rd("DMAM0", k, 8) + rd("DIC0", k, 9)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47) + OFF0)
    T.append(t)
    # DMARQ does not start the memory-to-memory modes (burst ch0, single step ch1)
    t = PTest("rq_m2m", jitter=False,
              stim=[{"event": "E0", "delay": 2000, "hold": 400, "levels": {"DMARQ0": 1, "DMARQ1": 1}}])
    t.codef = lambda k: (blk_w(0, 0x00D0, 0x00D0, 0x0F, 0x0D, 2)
                         + blk_w(1, 0x00D8, 0x00D8, 0x0F, 0x0D, 2) + swr("DMAC0", 0x11)
                         + swr("DMAC1", 0x11) + swr("DMAM0", 0x88) + swr("DMAM1", 0x08)
                         + ev("E0") + wait(60, "a") + blk_rd(0, k, 0) + blk_rd(1, k, 8)
                         + rd("DMAM0", k, 16) + rd("DMAM1", k, 17)
                         + swr("DMAM0", 0x00) + swr("DMAM1", 0x00))
    T.append(t)
    # single transfer: DMARQ1 high before EDMA's store (no transfer); a fall and a rise (one)
    t = mask_rng(PTest("io_lvl", jitter=False,
                       stim=[{"event": "E0", "delay": 100, "levels": {"DMARQ1": 1}},
                             {"event": "E1", "delay": 100, "levels": {"DMARQ1": 0}},
                             {"event": "E2", "delay": 100, "levels": {"DMARQ1": 1}},
                             {"event": "E3", "delay": 100, "levels": {"DMARQ1": 0}}]),
                 DD + 0xE0, 2)
    t.codef = lambda k: (swr("DIC1", 0x47) + ON0 + blk_w(1, 0x00E0, 0x00E0, 0x0F, 0x0D, 4)
                         + swr("DMAC1", 0x11) + ev("E0") + wait(20, "a") + swr("DMAM1", 0xA8)
                         + wait(40, "b") + blk_rd(1, k, 0) + ev("E1") + wait(20, "c")
                         + ev("E2") + wait(40, "d") + blk_rd(1, k, 8) + ev("E3") + wait(20, "e")
                         + swr("DMAM1", 0x00) + OFF0)
    T.append(t)
    # TDMA in the single-transfer mode (no transfer); EDMA cleared in a single step (TC 6): the
    # transfer the store's start saw still runs after it
    t = PTest("tdma", jitter=False)
    t.codef = lambda k: (swr("DIC0", 0x47) + ON0 + blk_w(0, 0x00F0, 0x00F0, 0x0F, 0x0D, 4)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0xAC) + wait(30, "a")
                         + blk_rd(0, k, 0) + blk_w(0, 0x00F0, 0x00F0, 0x0F, 0x0D, 6)
                         + swr("DMAM0", 0x0C) + cws(k, 2) + swr("DMAM0", 0x00) + cws(k, 4)
                         + blk_rd(0, k, 8) + rd("DMAM0", k, 16) + OFF0)
    T.append(t)
    # the count's end as an interrupt: burst, DIC0 unmasked with IE 1 (vector 20)
    t = PTest("dic", jitter=False, psw=PSW_IE)
    t.codef = lambda k: (serial.cnt_clr(20) + swr("DIC0", 0x07) + blk_w(0, 0x0040, 0x00A0, 0x0F, 0x0D, 2)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0x8C) + cws(k, 4)
                         + blk_rd(0, k, 0) + rd("DMAM0", k, 8) + rd("DIC0", k, 9)
                         + serial.cnt_rd(20, k, 10) + swr("DMAM0", 0x00) + swr("DIC0", 0x47))
    T.append(t)
    return _fix(T)


# ------------------------------------------------------------------ (F5f) requests inside a REP string
# A macro service or a DMA request raised just before (or during) a long REP string: does silicon
# serve it between the string's elements, or at the next instruction's start (after the string)?
# The string runs with DS1 = 0B00h (its destination B040h-: DATA1, compared) and DS0 = 0A00h (its
# source, the pattern); the request is raised by a store through SS = F000h (SS: [FFxxh], the SFR
# page) placed right before the string, so the string is the instruction after the store; the
# write sequence carries the string's element writes, the DMA's reads at F0xxh and its writes at
# D0xxh, and the macro service's memory write, in their places.
def _sstr(ops, n, store="", ix=0x0000, iy=0x0040, aw=0x1234, dw=0x0100, psw=None, ds0=None,
          post=""):
    """The string `ops` (prefix + opcode bytes) with CW n, after `store` (an SFR store through
    SS: F000h, the instruction before the string); `post` right after the string (SS still
    F000h: PS-prefixed stores only); the registers, DS0, DS1 and SS restored. `ds0`: the
    string's source segment (FFE0h: internal RAM)."""
    h = periph._h
    s = (("    PUSH DS0\n" if ds0 is not None else "")
         + "    PUSH DS1\n    PUSH CW\n    PUSH IX\n    PUSH IY\n    PUSH AW\n    PUSH BW\n"
         "    PUSH DW\n    MOV AW, 0B00h\n    MOV DS1, AW\n"
         + (f"    MOV AW, {h(ds0, 4)}\n    MOV DS0, AW\n" if ds0 is not None else "") +
         f"    MOV CW, {h(n, 4)}\n    MOV IX, {h(ix, 4)}\n    MOV IY, {h(iy, 4)}\n"
         f"    MOV DW, {h(dw, 4)}\n    MOV AW, {h(aw, 4)}\n")
    if psw is not None:
        s += f"    MOV BW, {h(psw, 4)}\n    PUSH BW\n    POP PSW\n"
    s += "    MOV BW, 0F000h\n    MOV SS, BW\n" + store
    s += "    DB " + ", ".join(h(b) for b in ops) + "\n" + post
    s += ("    XOR BW, BW\n    MOV SS, BW\n    MOV BW, 0002h\n    PUSH BW\n    POP PSW\n"
          "    POP DW\n    POP BW\n    POP AW\n    POP IY\n    POP IX\n    POP CW\n    POP DS1\n"
          + ("    POP DS0\n" if ds0 is not None else ""))
    return s


def ss_wr(name, val):
    """An SFR byte store through SS (= F000h inside _sstr)."""
    return f"    DB 36h\n    MOV byte [0FF{SFR[name]:02X}h], {periph._h(val)}\n"


MOVW, MOVB, STMW, OUTMW, INMW, CMPW = [0xF3, 0xA5], [0xF3, 0xA4], [0xF3, 0xAB], [0xF3, 0x6F], \
    [0xF3, 0x6D], [0xF3, 0xA7]


def sdma_tests():
    """(F5f) DMA memory to memory started by TDMA right before a REP string (single step and
    burst): where the transfers land among the elements."""
    T = [periph.init_test()]

    def dm(name, mode, ops, n=16, tc=4, ch=0, dmac=0x11, **kw):
        t = PTest(name, jitter=False)
        c = str(ch)
        t.codef = lambda k: (swr("DIC" + c, 0x47) + blk_w(ch, 0x0010 + 0x10 * k, 0x0010 + 0x10 * k,
                                                          0x0F, 0x0D, tc)
                             + swr("DMAC" + c, dmac)
                             + _sstr(ops, n, store=ss_wr("DMAM" + c, mode), **kw)
                             + cws(k, 4) + blk_rd(ch, k, 0) + rd("DMAM" + c, k, 8)
                             + rd("DIC" + c, k, 9) + swr("DMAM" + c, 0x00) + swr("DIC" + c, 0x47))
        return t
    T += [
        dm("st_movw", 0x0C, MOVW),                  # single step, REP MOVBKW 16
        dm("bu_movw", 0x8C, MOVW),                  # burst, REP MOVBKW 16
        dm("st_movb", 0x0C, MOVB),                  # single step, REP MOVBKB 16
        dm("st_stmw", 0x0C, STMW),                  # single step, REP STMW 16
        dm("bu_stmw", 0x8C, STMW, ch=1),            # burst ch1, REP STMW 16
        dm("st_outmw", 0x0C, OUTMW, n=8),           # single step, REP OUTMW 8 (port 0100h)
        dm("st_inmw", 0x0C, INMW, n=8),             # single step, REP INMW 8 (into B040h)
        dm("st_movw_n2", 0x0C, MOVW, n=2),          # single step, REP MOVBKW 2
        dm("st_movw_tc8", 0x0C, MOVW, n=4, tc=8),   # single step TC 8 over a 4-element string
    ]
    return _fix(T)


def sms_tests():
    """(F5f) macro service requested by a store of EXIC0's IF (MS 1, EMS0 channel 5) right
    before a REP string: SFR (BRG1 5Ah) to memory at D080h + 10h k, or memory (the string's
    last destination element) to BRG1."""
    T = [periph.init_test()]

    def ms(name, ops, n=16, ems=0x15, msp=None, mss=0, ic=0xA7, msc=4, **kw):
        t = PTest(name, jitter=False)

        def code(k):
            buf = 0xD080 + 0x08 * k if msp is None else msp
            return (swr("EXIC0", 0x47) + swr("BRG1", 0x5A) + serial.chan(5, msc, 0x7A, 0x00, buf, mss)
                    + swr("EMS0", ems) + _sstr(ops, n, store=ss_wr("EXIC0", ic), **kw)
                    + cws(k, 4) + serial.chan_rd(5, k, 0) + rd("EXIC0", k, 8) + rd("EMS0", k, 9)
                    + rd("BRG1", k, 10) + swr("EXIC0", 0x47) + swr("BRG1", 0x00))
        t.codef = code
        return t
    T += [
        ms("sw_movw", MOVW),                        # SFR -> memory, REP MOVBKW 16
        ms("sw_stmw", STMW),                        # SFR -> memory, REP STMW 16
        ms("sw_outmw", OUTMW, n=8),                 # SFR -> memory, REP OUTMW 8
        ms("sw_movw_m2s", MOVW, ems=0x05, msp=0x005E, mss=0x0B00),   # B05Eh (the last element's
                                                    # high half... its first byte) -> BRG1
        ms("sw_movw_m2s0", MOVW, ems=0x05, msp=0x0040, mss=0x0B00),  # B040h (the first) -> BRG1
        ms("sw_movw_m2s1", MOVW, ems=0x05, msp=0x0042, mss=0x0B00),  # B042h (the second) -> BRG1
        ms("sw_movw_n2", MOVW, n=2),                # REP MOVBKW 2
        ms("sw_cmpw", CMPW, n=16),                  # REPZ CMPBKW 16 (differing data: exits at
                                                    # the first element)
    ]
    return _fix(T)


def _rs(k, i, src):
    """A byte or word register into RES + 0x20 k + i through PS (= 0)."""
    return f"    DB 2Eh\n    MOV [{periph._h(RES + 0x20 * k + i, 4)}], {src}\n"


def _pb(addr, k, i):
    """The byte at linear addr (< 10000h) into RES + 0x20 k + i through PS (AL clobbered)."""
    return (f"    DB 2Eh\n    MOV AL, [{periph._h(addr, 4)}]\n" + _rs(k, i, "AL"))


def _iram_fill(n=0x10):
    """FFE0:0040h- (internal RAM) and B040h- both a copy of A000h- (n words)."""
    return ("    PUSH DS1\n    PUSH CW\n    PUSH IX\n    PUSH IY\n    MOV AW, 0FFE0h\n"
            f"    MOV DS1, AW\n    XOR IX, IX\n    MOV IY, 0040h\n    MOV CW, {periph._h(n, 4)}\n"
            "    DB 0F3h, 0A5h\n    MOV AW, 0B00h\n    MOV DS1, AW\n    XOR IX, IX\n"
            f"    MOV IY, 0040h\n    MOV CW, {periph._h(n, 4)}\n    DB 0F3h, 0A5h\n"
            "    POP IY\n    POP IX\n    POP CW\n    POP DS1\n")


def sms_inv_tests():
    """(F5f) macro service inside a REP string, compared in function only (the element the
    service lands on is the clocks': silicon's after the first element of MOVBKW, the second of
    STMW): the service's memory side is either a read of the string's destination (DIR 0: the
    byte into BRG1 is the value before the string's write, 3Ch) or a write into the string's
    source in internal RAM (DIR 1, FFE0:00xxh: no pins; the string then carries BRG1's 5Ah on),
    so no write on the pins depends on where it lands. After the string (PS stores): CW IX IY
    AW and the flags (LAHF) at RES + 12."""
    T = [periph.init_test()]
    post = lambda k: (_rs(k, 12, "CW") + _rs(k, 14, "IX") + _rs(k, 16, "IY") + _rs(k, 18, "AW")
                      + "    DB 9Fh\n" + _rs(k, 20, "AH"))

    def ms(name, ops, n=16, ems=0x15, msp=0x005E, mss=0x0B00, mark=(), iram=False, peek=(),
           **kw):
        t = PTest(name, jitter=False)

        def code(k):
            pre = "".join(f"    DB 2Eh\n    MOV byte [{periph._h(a, 4)}], 3Ch\n" for a in mark)
            if iram:
                pre = _iram_fill() + pre
            return (swr("EXIC0", 0x47) + swr("BRG1", 0x5A) + serial.chan(5, 4, 0x7A, 0x00, msp, mss)
                    + swr("EMS0", ems) + pre
                    + _sstr(ops, n, store=ss_wr("EXIC0", 0xA7), post=post(k),
                            **(dict(ds0=0xFFE0, ix=0x0040) if iram else {}), **kw)
                    + serial.chan_rd(5, k, 0) + rd("EXIC0", k, 8) + rd("BRG1", k, 10)
                    + "".join(_pb(a, k, 22 + j) for j, a in enumerate(peek))
                    + swr("EXIC0", 0x47) + swr("BRG1", 0x00))
        t.codef = code
        return t
    T += [
        ms("m2s_movw", MOVW, ems=0x05, mark=(0xB05E,)),           # B05Eh before the write: 3Ch
        ms("m2s_movb", MOVB, ems=0x05, msp=0x004F, mark=(0xB04F,)),
        ms("m2s_stmw", STMW, ems=0x05, mark=(0xB05E,)),
        ms("m2s_inmw", INMW, ems=0x05, mark=(0xB05E,)),
        ms("m2s_movw_n2", MOVW, n=2, ems=0x05, msp=0x0042, mark=(0xB042,)),
        ms("s2m_movw", MOVW, msp=0x005E, mss=0xFFE0, iram=True, peek=(0xB05E,)),
        ms("s2m_ldmw", [0xF3, 0xAD], msp=0x005E, mss=0xFFE0, iram=True),   # AL 5Ah at the end
        ms("s2m_cmpz", CMPW, msp=0x0050, mss=0xFFE0, iram=True),     # the 9th element differs:
                                                                     # CW 7, Z 0
        ms("s2m_outmw", OUTMW, msp=0x005E, mss=0xFFE0, iram=True),   # the 16th OUT: 5Ah
        ms("s2m_movw_seg", [0x2E, 0xF3, 0x26, 0xA5], msp=0x005E, mss=0xFFE0, iram=True,
           peek=(0xB05E,)),                                          # PS: REP DS1: (source DS1)
    ]
    # the last: PS: REP DS1: MOVBKW reads DS1:IX = 0B00:0040h (not internal RAM): B05Eh's copy
    # keeps the pattern (the service's write into internal RAM is not read)
    # asynchronous: an INTP0 edge, TM0's three services (600 clocks), during REP MOVBKW 80h
    big = dict(ix=0x0000, iy=0x0000)
    t = PTest("intp_m2s", jitter=False, stim=[pulse("E0", "INTP0", delay=20000)])
    t.codef = lambda k: (swr("EXIC0", 0x47) + swr("BRG1", 0x5A) + serial.chan(5, 4, 0x7A, 0x00, 0x00FE, 0x0B00)
                         + swr("EMS0", 0x05) + swr("EXIC0", 0x27) + "    DB 2Eh\n    MOV byte [0B0FEh], 3Ch\n"
                         + ev("E0") + _sstr(MOVW, 0x80, post=post(k), **big)
                         + serial.chan_rd(5, k, 0) + rd("EXIC0", k, 8) + rd("BRG1", k, 10)
                         + swr("EXIC0", 0x47) + swr("BRG1", 0x00))
    T.append(t)
    t = PTest("tm_m2s", jitter=False)
    t.codef = lambda k: (serial.TM_RUN + serial.chan(0, 3, 0x7A, 0x00, 0x00FC, 0x0B00)
                         + swr("BRG1", 0x6B) + "    DB 2Eh\n    MOV word [0B0FCh], 3C3Ch\n"
                         + "    DB 2Eh\n    MOV byte [0B0FEh], 3Ch\n"
                         + swr("TMMS0", 0x00) + swr("TMIC0", 0x27)
                         + _sstr(MOVW, 0x80, store=ss_wr("TMC0", 0x80), post=post(k), **big)
                         + periph.tm_stop() + serial.chan_rd(0, k, 0) + rd("TMIC0", k, 8)
                         + rd("BRG1", k, 10) + swr("TMIC0", 0x47) + swr("BRG1", 0x00))
    T.append(t)
    return _fix(T)


def _iram_set(addrs, v=0x5A):
    """Bytes of internal RAM (FFE0:addr) set to v (DS1 kept)."""
    return ("    PUSH DS1\n    PUSH AW\n    MOV AW, 0FFE0h\n    MOV DS1, AW\n"
            + "".join(f"    DB 26h\n    MOV byte [{periph._h(a, 4)}], {periph._h(v)}\n" for a in addrs)
            + "    POP AW\n    POP DS1\n")


def _ext_fill(n=0x10):
    """A040h- and B040h- both a copy of E000h- (n words: 40h 41h ...)."""
    return ("    PUSH DS0\n    PUSH DS1\n    PUSH CW\n    PUSH IX\n    PUSH IY\n    MOV AW, 0E00h\n"
            "    MOV DS0, AW\n    MOV AW, 0A00h\n    MOV DS1, AW\n    XOR IX, IX\n"
            f"    MOV IY, 0040h\n    MOV CW, {periph._h(n, 4)}\n    DB 0F3h, 0A5h\n"
            "    MOV AW, 0B00h\n    MOV DS1, AW\n    XOR IX, IX\n"
            f"    MOV IY, 0040h\n    MOV CW, {periph._h(n, 4)}\n    DB 0F3h, 0A5h\n"
            "    POP IY\n    POP IX\n    POP CW\n    POP DS1\n    POP DS0\n")


def sdma_inv_tests(iram=False):
    """(F5f) DMA memory to memory inside a REP string, compared in function only (the element
    of the first transfer is the clocks': silicon's after the first element, the RTL's after
    the second, the TDMA store's request seen a clock later). The transfer writes into the
    string's source ahead of the string (F070h- -> A05Eh- etc.: the source A040h-, the
    destination B040h-), so the string carries the transferred byte on (to B040h-, or AW, or the
    OUT data, or a compare's exit) when the transfer lands inside it; the gate drops the DMA's
    cycles (the source page's reads and every write at A040h-A05Fh: `prog.drop`) from both
    write sequences, the final memory is compared. After the string (PS stores): CW IX IY AW and
    the flags (LAHF) at RES + 12. With iram (f5_sdma_iram, measured only): the source and the
    destination at FFE70h- / FFE40h- (SARH / DARH FFh), the string's source in internal RAM:
    silicon's DMA cycles there go to the pins (an external read and write; internal RAM is not
    touched), the RTL's to internal RAM."""
    T = [periph.init_test()]
    post = lambda k: (_rs(k, 12, "CW") + _rs(k, 14, "IX") + _rs(k, 16, "IY") + _rs(k, 18, "AW")
                      + "    DB 9Fh\n" + _rs(k, 20, "AH"))

    def dm(name, mode, ops, dar, tc=1, ch=0, peek=(), **kw):
        t = PTest(name, jitter=False)
        c = str(ch)

        def code(k):
            if iram:
                pre = (_iram_fill() + _iram_set(range(0x70, 0x70 + tc))
                       + blk_w(ch, 0x0E70, dar, 0xFF, 0xFF, tc))
                sx = dict(ds0=0xFFE0, ix=0x0040)
            else:
                pre = _ext_fill() + blk_w(ch, 0x0070, dar - 0x0E00, 0x0F, 0x0A, tc)
                sx = dict(ix=0x0040)
            return (swr("DIC" + c, 0x47) + pre + swr("DMAC" + c, 0x11)
                    + _sstr(ops, 16, store=ss_wr("DMAM" + c, mode), post=post(k), **sx, **kw)
                    + blk_rd(ch, k, 0) + rd("DMAM" + c, k, 8) + rd("DIC" + c, k, 9)
                    + "".join(_pb(a, k, 22 + j) for j, a in enumerate(peek))
                    + swr("DMAM" + c, 0x00) + swr("DIC" + c, 0x47))
        t.codef = code
        return t
    T += [
        dm("st_movw", 0x0C, MOVW, 0x0E5E, peek=(0xB05E, 0xB05F)),
        dm("bu_movw", 0x8C, MOVW, 0x0E5C, tc=2, peek=(0xB05C, 0xB05D)),
        dm("st_movw_tc4", 0x0C, MOVW, 0x0E56, tc=4, ch=1, peek=(0xB056, 0xB057, 0xB058, 0xB059)),
        dm("st_movb", 0x0C, MOVB, 0x0E4F, peek=(0xB04F,)),
        dm("st_ldmw", 0x0C, [0xF3, 0xAD], 0x0E5E),
        dm("st_cmpz", 0x0C, CMPW, 0x0E50),
        dm("st_outmw", 0x0C, OUTMW, 0x0E5E),
        dm("bu_seg", 0x8C, [0x26, 0xF3, 0x3E, 0xA5], 0x0E5C, tc=2, peek=(0xB05C, 0xB05D)),
    ]
    # the last: DS1: REP DS0: MOVBKW (the source DS0 = FFE0h under the last override)
    return _fix(T)


def sasync_tests():
    """(F5f) measured only: asynchronous requests during a REP MOVBKW of 80h words (A000h ->
    B000h): TM0's macro service (600 clocks), an INTP0 edge's macro service, DMARQ0's single
    transfer (I/O to memory) and demand release."""
    T = [periph.init_test()]
    big = dict(ix=0x0000, iy=0x0000)
    t = PTest("tm_ms", jitter=False)
    t.codef = lambda k: (serial.TM_RUN + serial.chan(0, 8, 0x7A, 0x00, 0xD080) + swr("BRG1", 0x6B)
                         + swr("TMMS0", 0x10) + swr("TMIC0", 0x27)
                         + _sstr(MOVW, 0x80, store=ss_wr("TMC0", 0x80), **big)
                         + periph.tm_stop() + cws(k, 2) + serial.chan_rd(0, k, 0)
                         + rd("TMIC0", k, 8) + swr("TMIC0", 0x47) + swr("BRG1", 0x00))
    T.append(t)
    t = PTest("intp_ms", jitter=False, stim=[pulse("E0", "INTP0", delay=20000)])
    t.codef = lambda k: (swr("EXIC0", 0x47) + swr("BRG1", 0x5A) + serial.chan(5, 4, 0x7A, 0x00, 0xD0C0)
                         + swr("EMS0", 0x15) + swr("EXIC0", 0x27) + ev("E0")
                         + _sstr(MOVW, 0x80, **big) + cws(k, 2) + serial.chan_rd(5, k, 0)
                         + rd("EXIC0", k, 8) + swr("EXIC0", 0x47) + swr("BRG1", 0x00))
    T.append(t)
    t = mask_rng(PTest("io_in", jitter=False, stim=[rq("E0", 0, delay=20000)]), DD + 0x60, 3)
    t.codef = lambda k: (swr("DIC0", 0x47) + ON0 + blk_w(0, 0x0070, 0x0060, 0x0F, 0x0D, 3)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0xA8) + ev("E0")
                         + _sstr(MOVW, 0x80, **big) + cws(k, 2) + blk_rd(0, k, 0)
                         + rd("DMAM0", k, 8) + rd("DIC0", k, 9)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47) + OFF0)
    T.append(t)
    t = mask_rng(PTest("demand", jitter=False, stim=[rq("E0", 0, delay=20000, hold=3000)]),
                 DD + 0x90, 6)
    t.codef = lambda k: (swr("DIC0", 0x47) + ON0 + blk_w(0, 0x0090, 0x0090, 0x0F, 0x0D, 6)
                         + swr("DMAC0", 0x11) + swr("DMAM0", 0x28) + ev("E0")
                         + _sstr(MOVW, 0x80, **big) + cws(k, 2) + blk_rd(0, k, 0)
                         + rd("DMAM0", k, 8) + rd("DIC0", k, 9)
                         + swr("DMAM0", 0x00) + swr("DIC0", 0x47) + OFF0)
    T.append(t)
    return _fix(T)


# ------------------------------------------------------------------ hold, STOP, STBC (explore)
ONH = (periph.marker(periph.modes(r0=1)) + swr("PMC2", 0xC0) + periph.marker(periph.modes(r0=2)))


def hx_tests():
    T = [periph.init_test()]
    hrq = lambda e, d=100, h=3000: {"event": e, "delay": d, "hold": h, "levels": {"HLDRQ": 1}}
    # HLDRQ high ~94 clocks while the CPU waits in a loop (no writes), then writes
    t = PTest("h_loop", jitter=False, stim=[hrq("E0", 2000)])
    t.codef = lambda k: ONH + ev("E0") + wait(40, "a") + cws(k, 4) + OFF0
    T.append(t)
    # HLDRQ high while the CPU writes
    t = PTest("h_w", jitter=False, stim=[hrq("E0")])
    t.codef = lambda k: ONH + ev("E0") + cws(k, 8) + wait(20, "a") + OFF0
    T.append(t)
    # HLDRQ with P27 / P26 in port mode (PMC2 0)
    t = PTest("h_port", jitter=False, stim=[hrq("E0")])
    t.codef = lambda k: (periph.marker(periph.modes(r0=1)) + swr("PMC2", 0x00)
                         + periph.marker(periph.modes(r0=2)) + ev("E0") + cws(k, 8)
                         + wait(20, "a") + OFF0)
    T.append(t)
    # HLDRQ in HALT; INTP0 (vector 24) wakes it later
    t = PTest("h_halt", jitter=False, psw=PSW_IE,
              stim=[hrq("E0", 12000, 3000),
                    {"event": None, "delay": 6000, "hold": 2000, "levels": {"INTP0": 0}}])
    t.codef = lambda k: (serial.cnt_clr(24) + swr("EXIC0", 0x07) + ONH + ev("E0")
                         + "    HALT\n    NOP\n    NOP\n" + cw(k, 0, 0x55) + serial.cnt_rd(24, k, 0)
                         + swr("EXIC0", 0x47) + OFF0)
    T.append(t)
    # STBC: read, written 01h / FFh, read
    t = PTest("stbc", jitter=False)
    t.codef = lambda k: (rd("STBC", k, 0) + swr("STBC", 0x01) + rd("STBC", k, 1)
                         + swr("STBC", 0xFF) + rd("STBC", k, 2) + swr("STBC", 0x00) + rd("STBC", k, 3))
    T.append(t)
    # STOP (0F 9Eh) with IE 1, NMI (vector 2) 12000 ticks later; then a write
    t = PTest("stop", jitter=False, psw=PSW_IE,
              stim=[{"event": "E0", "delay": 12000, "hold": 2000, "levels": {"NMI": 0}}])
    t.codef = lambda k: (serial.cnt_clr(2) + ev("E0") + "    DB 0Fh, 9Eh\n    NOP\n    NOP\n"
                         + cw(k, 0, 0x66) + serial.cnt_rd(2, k, 1))
    T.append(t)
    # STOP with IE 0, then NMI
    t = PTest("stop_di", jitter=False,
              stim=[{"event": "E0", "delay": 12000, "hold": 2000, "levels": {"NMI": 0}}])
    t.codef = lambda k: (serial.cnt_clr(2) + ev("E0") + "    DB 0Fh, 9Eh\n    NOP\n    NOP\n"
                         + cw(k, 0, 0x77) + serial.cnt_rd(2, k, 1))
    T.append(t)
    # STOP with IE 1: INTP0 (unmasked) does not release it?; NMI later
    t = PTest("stop_intp", jitter=False, psw=PSW_IE,
              stim=[{"event": "E0", "delay": 12000, "hold": 2000, "levels": {"INTP0": 0}},
                    {"event": None, "delay": 12000, "hold": 2000, "levels": {"NMI": 0}}])
    t.codef = lambda k: (serial.cnt_clr(2) + serial.cnt_clr(24) + swr("EXIC0", 0x07) + ev("E0")
                         + "    DB 0Fh, 9Eh\n    NOP\n    NOP\n" + cw(k, 0, 0x88)
                         + serial.cnt_rd(2, k, 1) + serial.cnt_rd(24, k, 2) + swr("EXIC0", 0x47))
    T.append(t)
    return _fix(T)


def rdy_tests():
    T = [periph.init_test()]
    io = "    PUSH DW\n    MOV DW, 0FF40h\n    OUT DW, AL\n    IN AL, DW\n    POP DW\n"
    rdm = "    DB 2Eh\n    MOV AL, [0F010h]\n    DB 2Eh\n    MOV AW, [0F020h]\n"
    for nm, pmc1, wtc in (("rd_off", 0x00, None), ("rd_on", 0x80, None), ("rd_w2", 0x80, 0xAAAA),
                          ("rd_w1", 0x80, 0x5555), ("rd_w0", 0x80, 0x0000), ("rd_wio", 0x80, 0x3FFF)):
        t = PTest(nm, jitter=False)
        t.codef = (lambda k, pmc1=pmc1, wtc=wtc:
                   (periph.sfr_ww("WTC", wtc) if wtc is not None else "") + swr("PMC1", pmc1)
                   + cws(k, 2) + rdm + io + swr("PMC1", 0x00)
                   + (periph.sfr_ww("WTC", 0xFFFF) if wtc is not None else ""))
        T.append(t)
    return _fix(T)


# ------------------------------------------------------------------ hold, READY, STOP (gated)
def hrq(e, d=100, h=3000):
    return {"event": e, "delay": d, "hold": h, "levels": {"HLDRQ": 1}}


def hold_tests():
    """f4_hold: f4_hx's bus-hold tests as a gated set (the HLDAK pin records, the writes)."""
    T = [periph.init_test()]
    # HLDRQ high ~94 clocks while the CPU waits in a loop (no writes), then writes
    t = PTest("h_loop", jitter=False, stim=[hrq("E0", 2000)])
    t.codef = lambda k: ONH + ev("E0") + wait(40, "a") + cws(k, 4) + OFF0
    T.append(t)
    # HLDRQ high while the CPU writes
    t = PTest("h_w", jitter=False, stim=[hrq("E0")])
    t.codef = lambda k: ONH + ev("E0") + cws(k, 8) + wait(20, "a") + OFF0
    T.append(t)
    # HLDRQ with P27 in port mode, P26 /HLDAK (PMC2 40h): ignored (/HLDAK stays high; P26 is
    # driven, so its records do not depend on the board's keepers)
    t = PTest("h_port", jitter=False, stim=[hrq("E0")])
    t.codef = lambda k: (periph.marker(periph.modes(r0=1)) + swr("PMC2", 0x40)
                         + periph.marker(periph.modes(r0=2)) + ev("E0") + cws(k, 8)
                         + wait(20, "a") + OFF0)
    T.append(t)
    # HLDRQ in HALT; INTP0 (vector 24) wakes it later
    t = PTest("h_halt", jitter=False, psw=PSW_IE,
              stim=[hrq("E0", 12000, 3000),
                    {"event": None, "delay": 6000, "hold": 2000, "levels": {"INTP0": 0}}])
    t.codef = lambda k: (serial.cnt_clr(24) + swr("EXIC0", 0x07) + ONH + ev("E0")
                         + "    HALT\n    NOP\n    NOP\n" + cw(k, 0, 0x55) + serial.cnt_rd(24, k, 0)
                         + swr("EXIC0", 0x47) + OFF0)
    T.append(t)
    # HLDRQ during a burst DMA (memory to memory, TDMA, 4 transfers) and CPU writes
    t = PTest("h_dma", jitter=False, stim=[hrq("E0", 400, 2000)])
    t.codef = lambda k: (swr("DIC0", 0x47) + ONH + blk_w(0, 0x0060, 0x0060, 0x0F, 0x0D, 4)
                         + swr("DMAC0", 0x11) + ev("E0") + wait(2, "a") + swr("DMAM0", 0x8C)
                         + cws(k, 4) + wait(40, "b") + blk_rd(0, k, 0) + rd("DMAM0", k, 8)
                         + swr("DMAM0", 0x00) + OFF0)
    T.append(t)
    return _fix(T)


STOP = "    DB 0Fh, 9Eh\n    NOP\n    NOP\n"
NMI = lambda e, d=12000: {"event": e, "delay": d, "hold": 2000, "levels": {"NMI": 0}}


def stop_tests(x=False):
    """f4_stop: STBC before and after a STOP, STOP released by NMI (IE 1, IE 0), an unmasked
    INTP0 during STOP (no release), then NMI. Run last in a session (SBF stays set until the
    socket's power is switched off) and run twice: the second run (`f4_stop_r`, a reset, no power
    cycle) reads STBC as the first run's STOP left it. x: the first measurement's text (f4_stopx:
    stbc0 also stores 01h before any STOP, which set SBF)."""
    T = [periph.init_test()]
    t = PTest("stbc0", jitter=False)
    t.codef = lambda k: (rd("STBC", k, 0) + swr("STBC", 0x00) + rd("STBC", k, 1)
                         + (swr("STBC", 0x01) + rd("STBC", k, 2) if x else ""))
    T.append(t)
    t = PTest("stop", jitter=False, psw=PSW_IE, stim=[NMI("E0")])
    t.codef = lambda k: (serial.cnt_clr(2) + ev("E0") + STOP + cw(k, 0, 0x66)
                         + serial.cnt_rd(2, k, 1) + rd("STBC", k, 2))
    T.append(t)
    t = PTest("stop_di", jitter=False, stim=[NMI("E0")])
    t.codef = lambda k: (serial.cnt_clr(2) + ev("E0") + STOP + cw(k, 0, 0x77)
                         + serial.cnt_rd(2, k, 1) + rd("STBC", k, 2))
    T.append(t)
    t = PTest("stop_intp", jitter=False, psw=PSW_IE,
              stim=[{"event": "E0", "delay": 12000, "hold": 2000, "levels": {"INTP0": 0}},
                    NMI(None)])
    t.codef = lambda k: (serial.cnt_clr(2) + serial.cnt_clr(24) + swr("EXIC0", 0x07) + ev("E0")
                         + STOP + cw(k, 0, 0x88) + serial.cnt_rd(2, k, 1)
                         + serial.cnt_rd(24, k, 2) + rd("EXIC0", k, 3) + swr("EXIC0", 0x47))
    T.append(t)
    t = PTest("stbc1", jitter=False)
    t.codef = lambda k: (rd("STBC", k, 0) + swr("STBC", 0x00) + rd("STBC", k, 1)
                         + swr("STBC", 0xFF) + rd("STBC", k, 2) + swr("STBC", 0x00)
                         + rd("STBC", k, 3))
    T.append(t)
    return _fix(T)


def programs():
    progs = {
        "f4_hx": _prog("f4_hx", hx_tests(), pins=PINS, gate=False, fast=(2, 24),
                       note="explore: bus hold, STBC, STOP"),
        "f4_rdy": _prog("f4_rdy", rdy_tests(), note="READY and WTC (the cycle lengths gated)"),
        "f4_hold": _prog("f4_hold", hold_tests(), pins=PINS, fast=(24,),
                         note="bus hold: HLDRQ / HLDAK"),
        "f4_stop": _prog("f4_stop", stop_tests(), fast=(2, 24),
                         note="STBC and STOP (run last in a session, twice)"),
        "f4_stopx": _prog("f4_stopx", stop_tests(x=True), fast=(2, 24), gate=False,
                          note="explore: STBC (a 01h store before the STOPs) and STOP"),
        "f4_dma": _prog("f4_dma", dma_tests(), pins=PINS, fast=(20, 21),
                        note="DMA: the modes, the placement, the pins, HALT, DIC"),
        "f4_dmx": _prog("f4_dmx", explore_tests(), gate=False, note="explore: DMA memory to memory"),
        "f4_dmi": _prog("f4_dmi", io_tests(), pins=PINS, gate=False, note="explore: DMA I/O"),
        "f4_dm3": _prog("f4_dm3", x3_tests(), pins=PINS, gate=False,
                        note="explore: DMA pins in m2m, demand stops, levels, TDMA"),
        "f5_sdma": _prog("f5_sdma", sdma_tests(), pins=PINS, fast=(20, 21), gate=False,
                         note="(F5f) DMA started by TDMA right before a REP string"),
        "f5_sms": _prog("f5_sms", sms_tests(), pins=PINS, fast=(20, 21, 24), gate=False,
                        note="(F5f) macro service requested right before a REP string"),
        "f5_sms_inv": _prog("f5_sms_inv", sms_inv_tests(), pins=PINS, fast=(20, 21, 24, 28),
                            gate=True, note="(F5f) macro service inside a REP string: function "
                                             "only (no write on the pins depends on its element)"),
        "f5_sdma_inv": _prog("f5_sdma_inv", sdma_inv_tests(), pins=PINS, fast=(20, 21),
                             gate=True, note="(F5f) DMA inside a REP string: function only "
                                              "(the DMA's cycles dropped, the memory compared)"),
        "f5_sdma_iram": _prog("f5_sdma_iram", sdma_inv_tests(iram=True), pins=PINS,
                              fast=(20, 21), gate=False,
                              note="(F5f) measured only: DMA at FFExxh (internal RAM's page)"),
        "f5_sasync": _prog("f5_sasync", sasync_tests(), pins=PINS, fast=(20, 21, 24, 28),
                           gate=False, note="(F5f) measured only: asynchronous macro service "
                                            "and DMA requests during a long REP string"),
        "f4_dm2": _prog("f4_dm2", x2_tests(), pins=PINS, gate=False, fast=(20, 21),
                        note="explore: DMA placement, triggers, HALT, words, priority"),
    }
    progs["f5_sdma_inv"].drop = set(range(0xF000, 0xF100)) | set(range(0xA040, 0xA060))
    progs["f4_stop_r"] = progs["f4_stop"]      # its second run (a reset, no power cycle)
    progs["f4_stopx_r"] = progs["f4_stopx"]
    for p in {id(p): p for p in progs.values()}.values():
        p.data.update(pages())
        p.results += [(0xD000, 0x100), (SRC, 0x100), (DST, 0x100), (RES, 0x20 * len(p.tests))]
    return progs


def _with_dma_reads():
    """The write and I/O sequence with the memory reads at the source page (F000h-F0FFh: only the
    DMA reads there) in their places: where each transfer's read lands among the program's
    writes is compared by sequence (onchip._write_sequence, used by periph.run_one)."""
    from . import onchip
    from .runner import FLAG_IO, FLAG_READ, FLAG_STROBE
    seq = onchip._write_sequence

    def ws(rows):
        rows = list(rows)
        out = []
        for t in rows:
            if (t["flags"] & FLAG_STROBE and t["flags"] & FLAG_READ and not t["flags"] & FLAG_IO
                    and 0xF000 <= t["address"] < 0xF100):
                out.append([t["address"], t["data"], t["flags"] & 0xFBF])
            else:
                out += seq([t])
        return out
    onchip._write_sequence = ws


SETTLE = 8              # ticks: TC falls half a clock after DMAAK (16 ticks); the bank hand-over's
                        # keeper transients are 2 ticks


def _ready_stim(ticks):
    """periph's stimulus with the harness's READY hold (register 0Ah: ticks READY stays low
    after the column strobe, both lanes) for a program run."""
    st = periph._stim

    def stim(harness, prog):
        st(harness, prog)
        harness.debug.write16(0x0A, ticks if prog.name == "f4_rdy" else 0)
    periph._stim = stim


def _gate_setup(progs):
    """periph's gate with the masked bytes (Test.mask) and the shorter settle."""
    jit, st, stt = periph._jitter, periph.settle, periph.settle_ticks

    def jitter(name, rec, prog):
        ex = jit(name, rec, prog)
        for t in prog.tests:
            ex |= getattr(t, "mask", set())
        return ex
    periph._jitter = jitter
    # (F5f) a program's `drop` addresses: their writes (and the DMA's source reads) left out of
    # both write sequences (cycles whose place among the program's own is the clocks')
    load = periph.load

    def ld(name, backend):
        rec = load(name, backend)
        drop = getattr(progs.get(name), "drop", None)
        if drop:
            rec["writes"] = [w for w in rec["writes"] if w[0] not in drop]
        return rec
    periph.load = ld
    periph.settle = lambda pins, ticks=SETTLE: st(pins, ticks)
    periph.settle_ticks = lambda pins, ticks=SETTLE: stt(pins, ticks)


def _keep_trace(only=None):
    """periph.run_one with `trace` added: [tick, address, data, flags, end] of every record
    (`only`: for these programs alone)."""
    from . import onchip
    seq, stash = onchip._write_sequence, {}

    def ws(rows):
        rows = list(rows)
        stash["tr"] = [[t["start"], t["address"], t["data"], t["flags"], t["end"]] for t in rows]
        return seq(rows)
    onchip._write_sequence = ws
    one = periph.run_one

    def run_one(harness, prog, *a, **k):
        rec = one(harness, prog, *a, **k)
        tr = stash.pop("tr", [])
        if only is None or prog.name in only:
            rec["trace"] = tr
        return rec
    periph.run_one = run_one


TRACED = ("f4_rdy", "f4_hold", "f4_stop")    # the receipts keep the trace (the gate reads it)
STOP_LIMIT = 80_000_000                      # ticks: three STOPs of 2^19 clocks (32 ticks each)


def run_stop(backend, tag, progs, base="f4_stop"):
    """f4_stop in a session of its own, twice: the second run (a reset, no power cycle) is saved
    as f4_stop_r (STBC as the first run's STOP left it)."""
    from .traps import _board, _close_board, _sim
    lane = "socket" if backend == "socket" else "model"
    transport, harness = _board() if backend == "socket" else _sim()
    try:
        for name in (base, base + "_r"):
            prog = progs[name]
            periph._stim(harness, prog)
            rec = periph.run_one(harness, prog, lane, limit=STOP_LIMIT)
            rec.update(program=name, backend=backend,
                       date=datetime.datetime.now().isoformat(timespec="seconds"),
                       stim=prog.stim, levels=prog.levels, p0=prog.p0)
            if backend == "socket":
                rec.update(cpu="uPD70337L-8", x_half=2)
            else:
                rec.update(core="v35", binary=os.environ.get(
                    "V35_SIM_BINARY", "build/fpga/v35s/verilator-direct-v35"))
            periph.save(rec, name, backend + tag)
            print(f"{name}: {backend} {'PASS' if rec['passed'] else 'FAIL'} "
                  f"status=0x{rec['status']:04x} writes={len(rec['writes'])} total={rec['total']}"
                  f" stubs={len(rec['stubs'])} replay={rec['replay']}", flush=True)
    finally:
        if backend == "socket":
            _close_board(transport, harness)
        else:
            transport.close()


# ------------------------------------------------------------------ the gate's timing checks
def _test_of(trace):
    """Per record: the test it belongs to (the stub's number store at LOG + 4)."""
    from .runner import FLAG_IO, FLAG_READ, FLAG_STROBE
    k, out = -1, []
    for t in trace:
        if t[3] & FLAG_STROBE and not t[3] & (FLAG_READ | FLAG_IO) and t[1] == periph.LOG + 4:
            k = t[2]
        out.append(k)
    return out


RDY_TOL = 2             # ticks: a cycle's length (the harness records at 30 ns; the I/O cycles'
                        # strobe sample differs by one tick between the socket and the RTL)


def rdy_cycles(rec):
    """f4_rdy: per test, the lengths (end - start, ticks) of its writes, I/O cycles and data reads
    (the page F000h) in order, and the set of its memory reads' lengths in clocks (the fetches)."""
    from .runner import FLAG_IO, FLAG_PIN, FLAG_READ
    tr = rec["trace"]
    seq, rset = {}, {}
    for k, t in zip(_test_of(tr), tr):
        if t[3] & FLAG_PIN or k < 0:
            continue
        ln = t[4] - t[0]
        kind = ("io" if t[3] & FLAG_IO else "m") + ("r" if t[3] & FLAG_READ else "w")
        if kind != "mr" or 0xF000 <= t[1] < 0xF100:
            seq.setdefault(k, []).append((kind, t[1], ln))
        if kind == "mr":
            rset.setdefault(k, set()).add(round(ln / periph.CLK))
    return seq, rset


def check_rdy(a, b, prog):
    sa, ra = rdy_cycles(a)
    sb, rb = rdy_cycles(b)
    bad = []
    for k in range(len(prog.tests)):
        x, y = sa.get(k, []), sb.get(k, [])
        if len(x) != len(y) or any(p[:2] != q[:2] or abs(p[2] - q[2]) > RDY_TOL
                                   for p, q in zip(x, y)):
            bad.append(f"{prog.tests[k].name}: {[(p[0], p[2]) for p in x]} / "
                       f"{[(q[0], q[2]) for q in y]}")
        if ra.get(k) != rb.get(k):
            bad.append(f"{prog.tests[k].name} read lengths {sorted(ra.get(k, []))} / "
                       f"{sorted(rb.get(k, []))}")
    n = sum(len(v) for v in sa.values())
    print(f"  f4_rdy cycle lengths ({n} cycles, tolerance {RDY_TOL} ticks): "
          + ("equal" if not bad else "differ: " + "; ".join(bad[:8])))
    return not bad


STOP_TOL = 64           # clocks: the release's distance from the test's event (the NMI's edge
                        # against the CPU clock, the handler's entry): 2^19 + ~400 on the socket


def stop_gaps(rec):
    """f4_stop: per test with a STOP, the clocks from its event record (the OUT to FF12h) to the
    first bus record after the quiet (the release)."""
    from .runner import FLAG_EVENT
    tr, out = rec["trace"], {}
    ks = _test_of(tr)
    for i in range(1, len(tr)):
        if tr[i][0] - tr[i - 1][4] > 100_000:
            ev_t = next(t[0] for t in reversed(tr[:i]) if t[3] & FLAG_EVENT)
            out[ks[i]] = (tr[i][0] - ev_t) / periph.CLK
    return out


def check_stop(a, b, prog):
    ga, gb = stop_gaps(a), stop_gaps(b)
    bad = ([k for k in ga if k not in gb or abs(ga[k] - gb[k]) > STOP_TOL]
           + [k for k in gb if k not in ga])
    print("  f4_stop release (clocks after the event): " + ", ".join(
        f"{prog.tests[k].name} {ga.get(k)}/{gb.get(k)}" for k in sorted(set(ga) | set(gb)))
          + f" (tolerance {STOP_TOL}): " + ("equal" if not bad else "differ"))
    return not bad


def hold_gaps(rec):
    """f4_hold: per HLDAK edge (the pin vector's bit 22), its level and the ticks from the bus
    record before it (its end), to the one after it (its start) and from the last event record
    (the OUT that started the test's schedule)."""
    from .runner import FLAG_EVENT, FLAG_PIN
    tr, out, lvl, ev_t = rec["trace"], [], 1, None
    for i, t in enumerate(tr):
        if t[3] & FLAG_EVENT:
            ev_t = t[0]
        if t[3] & FLAG_PIN and (t[2] >> 6) & 1 != lvl:
            lvl = (t[2] >> 6) & 1
            prv = next((u for u in reversed(tr[:i]) if not u[3] & FLAG_PIN), None)
            nxt = next((u for u in tr[i + 1:] if not u[3] & FLAG_PIN), None)
            out.append((lvl, t[0] - prv[4] if prv else None, nxt[0] - t[0] if nxt else None,
                        t[0] - ev_t if ev_t is not None else None))
    return out


HOLD_TOL = {"end": 4, "next": 4, "event": 32}
                        # ticks: an edge bound to a cycle (the hold taken as the cycle in flight
                        # ends; the bus taken back) to 4 ticks; an edge bound to HLDRQ (an
                        # asynchronous level: its phase against the CPU clock's sample) to a clock


def hold_bound(e):
    """What an HLDAK edge is bound to: a fall within 100 ticks of a cycle's end to that end (the
    hold taken when the cycle in flight ends), else to the event (the HLDRQ edge the schedule
    places after it, on an idle bus); a rise within 16 ticks of a record's end to it (a PMC2
    store), within 100 ticks of the next cycle to it (the bus taken back), else to the event."""
    lvl, after, to_next, after_ev = e
    if lvl == 0:
        return ("end", after) if after < 100 else ("event", after_ev)
    if after < 16:
        return ("end", after)
    return ("next", to_next) if to_next is not None and to_next < 100 else ("event", after_ev)


def check_hold(a, b, prog):
    """The edges bound the same way on both sides within HOLD_TOL; an edge bound differently is
    listed (a timing difference: the gate's sequences and pins carry the function)."""
    ha, hb = hold_gaps(a), hold_gaps(b)
    ba, bb = [hold_bound(e) for e in ha], [hold_bound(e) for e in hb]
    bad = len(ba) != len(bb)
    out, other = [], []
    for n, (x, y) in enumerate(zip(ba, bb)):
        if x[0] != y[0]:
            other.append(f"#{n} {x[0]} {x[1]} / {y[0]} {y[1]}")
            continue
        ok = abs(x[1] - y[1]) <= HOLD_TOL[x[0]]
        bad |= not ok
        out.append(f"{x[0]} {x[1]}/{y[1]}" + ("" if ok else " (!)"))
    print(f"  f4_hold HLDAK edges ({len(ba)}/{len(bb)}; bound to, ticks; tolerance {HOLD_TOL}): "
          + "; ".join(out) + (" differ" if bad else " equal")
          + ("" if not other else "; bound differently (timing, not gated): " + "; ".join(other)))
    return not bad


CHECKS = {"f4_rdy": check_rdy, "f4_stop": check_stop, "f4_stop_r": check_stop,
          "f4_hold": check_hold}


def gate(names, ref, cand, progs):
    ok = periph.compare_gate(names, ref, cand, progs)
    for n in names:
        if n in CHECKS:
            a, b = periph.load(n, ref), periph.load(n, cand)
            if "trace" not in a or "trace" not in b:
                print(f"  {n}: no trace in a receipt: timing not checked")
                ok = False
                continue
            ok &= CHECKS[n](a, b, progs[n])
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "gate", "show", "emit", "size"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--trace", action="store_true")
    a = p.parse_args()
    progs = programs()
    gated = [n for n, prog in progs.items() if prog.gate and not n.endswith("_r")]
    names = a.names or gated
    if a.action in ("socket", "sim"):
        _with_dma_reads()
        _ready_stim(160)
        _keep_trace(None if a.trace else TRACED)
        stops = [n for n in names if n in ("f4_stop", "f4_stopx")]
        rest = [n for n in names if n not in stops and not n.endswith("_r")]
        if rest:
            periph.run_set(rest, a.action, a.tag, progs)
        for n in stops:                 # last, each in a session of its own
            run_stop(a.action, a.tag, progs, n)
    elif a.action == "gate":
        _gate_setup(progs)
        names = names + [n + "_r" for n in names if n in ("f4_stop", "f4_stopx")
                         and n + "_r" not in names]
        return 0 if gate(names, a.ref, a.cand, progs) else 1
    elif a.action == "show":
        for n in names:
            serial.show(n, a.ref + a.tag, progs)
    elif a.action == "size":
        for n in names:
            code, _, _ = progs[n].image()
            print(n, f"{len(code)} bytes, {len(progs[n].tests)} tests")
    else:
        periph.emit({n: p_ for n, p_ in progs.items() if not n.endswith("_r")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
