"""F4: the timing of instructions that access on-chip locations (the f4_oc_* program set).

An access to the internal RAM (IDB:E00-EFF), the SFR page (IDB:F00-FFF) or FFFFFh makes no bus
cycle: only the fetches around it and the markers are on the pins. Each program is a list of
windows; a window is opened by OUT FE40h (AW = its number) and closed by OUT FE42h, and its body
starts from a full queue and an idle bus (a register-only filler, ROL BP,16, before the first
instruction under test). Every on-chip window has a twin with the same code bytes at the same
code addresses whose data segment is 3000h instead of F000h: the same offsets then address the
external page 3Fxxxh at 0 waits, where the data cycles are on the pins. The on-chip cost of an
instruction is read as the difference between the twins, and as the difference between windows
that repeat the unit N and 2N (or 2 and 6) times.

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.onchip_t socket --socket-fitted [NAME ...] [--tag -2]
    PYTHONPATH=host/src:. python3 -m validation.v35s.onchip_t sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.onchip_t report [NAME ...] [--ref socket] [-v]
    PYTHONPATH=host/src:. python3 -m validation.v35s.onchip_t repeat [NAME ...]     (socket / socket-2)
    PYTHONPATH=host/src:. python3 -m validation.v35s.onchip_t gate [NAME ...]       (socket / sim)
    PYTHONPATH=host/src:. python3 -m validation.v35s.onchip_t emit

    f4_oc_a   the instruction forms on the internal RAM (a plain bank's bytes, the current bank's
              IY slot) and FFFFFh: isolated (filler between) and in runs
    f4_oc_s   the same on SFRs: P0, TMC0, RFM (bytes), WTC (word)
    f4_oc_k   strings: REP LDM / STM / MOVBK, byte and word, 8 and 16 elements, source and
              destination on and off the chip; single LDM / STM / MOVBK
    f4_oc_t   the timer registers (MD0, TM0, MD1, TMC0) against P0 and the external twin, the
              instruction's start swept over twelve delays (every phase of six clocks)
    f4_oc_v   the SFR page surveyed: every offset read by byte, every even offset by word, the
              safe offsets stored; one delay each
    f4_oc_e   where a store takes effect: WTC (the waits of the fetches after it), P1 (the P15
              pin), TMC0 (TOUT's first edge)

Receipts: validation/v35s/receipts/f4-<name>-<backend>.json (the whole trace kept).

Measured on the uPD70337 (2026-11-19, two equal captures): an on-chip access holds the bus for
the 3 clocks of an external cycle at 0 waits, so every form costs what its twin costs and the
fetches sit on the same ticks; a word in the SFR page is two byte cycles (low address first, 3
clocks more); a byte cycle on a timer-unit register (FF80h-83h, 88h-8Bh, 90h, 91h) is stretched
by 1 to 6 clocks to end on a free-running divide-by-six of the CPU clock (TOUT's count clock);
a store lands in its cycle's first clock (P1's pin half a clock after the cycle's start). The
gate against the core v2 simulation DIFFERs until that is built.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

from .wtc import Asm, CLK, FLAG_IO, FLAG_PIN, FLAG_READ, FLAG_REFRESH, FLAG_STROBE, pat

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS_DIR = ROOT / "validation/v35s/programs"
RECEIPTS = ROOT / "validation/v35s/receipts"

ORG = 0x100
CODE = 0x10000                  # the windows' code: PS 1000h, offset 0000h up (block 0)
CODE_PAGES = 12
STACK_TOP = 0x0F00
ON, OFF = 0xF000, 0x3000        # the data segment: on-chip, or the external page 3Fxxxh
M_BEGIN, M_END, M_MODE = 0xFE40, 0xFE42, 0xFF10
CAPTURE, OVERLAP = 2048, 48      # records a run returns; records a rerun repeats
P15 = 1 << 13                   # the pin vector's bit (runner.PINS)

# targets: offset, width (1 byte / 2 word), a value whose store changes nothing that matters
TARGETS = {
    "ram": (0xFE40, 2, 0x1234),     # internal RAM, bank 2's bytes (not the bank in use)
    "cur": (0xFEF0, 2, 0x1234),     # internal RAM, the bank in use (7): IY's slot
    "idb": (0xFFFF, 1, None),       # FFFFFh (read only here: a store would move the page)
    "p0": (0xFF00, 1, 0x00),        # P0's latch (the port stays an input)
    "p1": (0xFF08, 1, 0x00),
    "tmc0": (0xFF90, 1, 0x00),
    "rfm": (0xFFE1, 1, 0xEC),
    "wtc": (0xFFE8, 2, 0x0000),
    "md0": (0xFF82, 2, 0x0063),
    "tm0": (0xFF80, 2, 0x0063),
    "md1": (0xFF8A, 2, 0x0063),
}


def form(name, off, val=0):
    """(bytes, text) of an instruction form at DS0:off (pimw: through DS1)."""
    lo, hi = off & 0xFF, off >> 8
    v0, v1 = (val or 0) & 0xFF, (val or 0) >> 8
    t = f"[{off:04X}h]"
    return {
        "rdb": ([0xA0, lo, hi], f"MOV AL, {t}"),
        "rdw": ([0xA1, lo, hi], f"MOV AW, {t}"),
        "wrb": ([0xA2, lo, hi], f"MOV {t}, AL"),
        "wrw": ([0xA3, lo, hi], f"MOV {t}, AW"),
        "mrb": ([0x8A, 0x2E, lo, hi], f"MOV CH, {t}"),
        "mrw": ([0x8B, 0x2E, lo, hi], f"MOV BP, {t}"),
        "mwb": ([0x88, 0x06, lo, hi], f"MOV {t}, AL   ; ModRM"),
        "mww": ([0x89, 0x06, lo, hi], f"MOV {t}, AW   ; ModRM"),
        "imb": ([0xC6, 0x06, lo, hi, v0], f"MOV byte {t}, {v0:02X}h"),
        "imw": ([0xC7, 0x06, lo, hi, v0, v1], f"MOV word {t}, {val or 0:04X}h"),
        "pimw": ([0x26, 0xC7, 0x06, lo, hi, v0, v1], f"MOV word DS1:{t}, {val or 0:04X}h"),
        "pimb": ([0x26, 0xC6, 0x06, lo, hi, v0], f"MOV byte DS1:{t}, {v0:02X}h"),
        "prdb": ([0x26, 0xA0, lo, hi], f"MOV AL, DS1:{t}"),
        "pwrb": ([0x26, 0xA2, lo, hi], f"MOV DS1:{t}, AL"),
        "addb": ([0x00, 0x1E, lo, hi], f"ADD {t}, BL   ; BL = 0"),
        "addw": ([0x01, 0x1E, lo, hi], f"ADD {t}, BW   ; BW = 0"),
        "incb": ([0xFE, 0x06, lo, hi], f"INC byte {t}"),
        "incw": ([0xFF, 0x06, lo, hi], f"INC word {t}"),
        "pushm": ([0xFF, 0x36, lo, hi], f"PUSH word {t}"),
        "rdbx": ([0x8A, 0x07], f"MOV AL, [BW]   ; BW = {off:04X}h"),
        "wrbx": ([0x88, 0x07], f"MOV [BW], AL   ; BW = {off:04X}h"),
        "wruse": ([0xA3, lo, hi, 0x8B, 0xEF, 0x55], f"MOV {t}, AW / MOV BP, IY / PUSH BP"),
    }[name]


FIL = ([0xC1, 0xC5, 0x10], "ROL BP, 16   ; filler: the queue fills, the bus idles")


def fil(a, n=1):
    for _ in range(n):
        a.op(*FIL)


def roli(a, k):
    a.op([0xC1, 0xC5, k], f"ROL BP, {k}   ; the sweep's delay")


def seg(a, s, v):
    a.mov_r("AW", v)
    a.mov_sr(s)


def es_store(a, off, v, word=False):
    """A store through DS1 with the prefix (DS1 must be F000h for an SFR)."""
    a.op(*form("pimw" if word else "pimb", off, v))


class Window:
    def __init__(self, meta, setup, body):
        self.meta, self.setup, self.body = meta, setup, body


def std_setup(s, bw=0, ds1=None):
    def f(a):
        seg(a, "DS0", s)
        seg(a, "DS1", s if ds1 is None else ds1)
        a.mov_r("BW", bw)
        a.mov_r("SP", STACK_TOP)
    return f


def unit_window(fname, target, s, shape, n):
    """iso: fil fil (F fil) x n; run: fil fil F x n fil; raw: F x n straight after the marker
    (f4_wtc_x's windows: the queue as the OUT left it)."""
    off, width, val = TARGETS[target]
    bs, text = form(fname, off, val)

    def body(a):
        if shape != "raw":
            a.mov_r("AW", val or 0)
            fil(a, 2)
        for _ in range(n):
            a.op(bs, text)
            if shape == "iso":
                fil(a)
        if shape == "run":
            fil(a)
    return Window(dict(form=fname, target=target, seg="on" if s == ON else "off", shape=shape, n=n),
                  std_setup(s, bw=off if fname.endswith("x") else 0), body)


def control_window(shape, n):
    """The filler alone, as often as a unit window of n has it."""
    def body(a):
        a.mov_r("AW", 0)
        fil(a, 2 + (n if shape == "iso" else 1))
    return Window(dict(form="none", target="-", seg="-", shape=shape, n=n), std_setup(OFF), body)


def unit_set(pairs, raw=()):
    out = [control_window(sh, n) for sh, n in (("iso", 2), ("iso", 6), ("run", 4))]
    for fname, target in pairs:
        for s in (ON, OFF):
            for shape, n in (("iso", 2), ("iso", 6), ("run", 4), ("run", 8)):
                out.append(unit_window(fname, target, s, shape, n))
    for fname, target in raw:
        for s in (ON, OFF):
            for n in (4, 8):
                out.append(unit_window(fname, target, s, "raw", n))
    return out


RAW = (("prdb", "ram"), ("pwrb", "ram"), ("rdb", "ram"), ("wrb", "ram"), ("prdb", "idb"))


A_PAIRS = ([(f, "ram") for f in ("rdb", "rdw", "wrb", "wrw", "mrb", "mrw", "mwb", "mww", "imb",
                                 "imw", "pimw", "addb", "addw", "incb", "incw", "pushm", "rdbx",
                                 "wrbx", "prdb", "pwrb", "pimb")]
           + [(f, "cur") for f in ("rdw", "wrw", "addw", "wruse")] + [("rdb", "idb"), ("mrb", "idb")])
S_PAIRS = ([(f, "p0") for f in ("rdb", "rdw", "wrb", "imb", "addb", "incb", "pushm", "prdb", "pwrb",
                                 "pimb")]
           + [(f, "wtc") for f in ("rdw", "wrw", "mrw", "mww", "imw", "pimw", "addw", "rdb")]
           + [(f, "rfm") for f in ("rdb", "wrb", "imb")] + [(f, "tmc0") for f in ("rdb", "wrb")])


# ------------------------------------------------------------------ strings
def string_window(op, word, n, src, dst, ix=0xFE40, iy=0xFE60, rep=True, units=1):
    code = {"ldm": 0xAC, "stm": 0xAA, "mov": 0xA4}[op] + (1 if word else 0)
    text = {"ldm": "LDM", "stm": "STM", "mov": "MOVBK"}[op] + ("W" if word else "B")

    def setup(a):
        seg(a, "DS0", src)
        seg(a, "DS1", dst)
        a.mov_r("IX", ix)
        a.mov_r("IY", iy)
        a.mov_r("CW", n)
        a.mov_r("SP", STACK_TOP)
        a.op([0xFC], "CLR1 DIR")

    def body(a):
        a.mov_r("AW", 0x1234)
        fil(a, 2)
        for _ in range(units):
            a.op(([0xF3] if rep else []) + [code], ("REP " if rep else "") + text)
            fil(a)
    nm = lambda s: "on" if s == ON else "off"       # noqa: E731
    return Window(dict(form=("rep" if rep else "one") + op + ("w" if word else "b"),
                       target=f"{ix:04X}", seg=(nm(src) if op == "ldm" else nm(dst) if op == "stm"
                                                else nm(src) + ">" + nm(dst)),
                       shape="rep" if rep else "iso", n=n if rep else units), setup, body)


def string_set():
    out = [control_window("iso", 1), control_window("iso", 2), control_window("iso", 6)]
    for word in (False, True):
        for n in (8, 16):
            for s in (ON, OFF):
                out.append(string_window("ldm", word, n, s, s))
                out.append(string_window("stm", word, n, s, s))
            for s, d in ((ON, ON), (ON, OFF), (OFF, ON), (OFF, OFF)):
                out.append(string_window("mov", word, n, s, d))
    for n in (8, 16):                               # odd words: two byte accesses each
        for s in (ON, OFF):
            out.append(string_window("ldm", True, n, s, s, ix=0xFE41))
            out.append(string_window("mov", True, n, s, s, ix=0xFE41, iy=0xFE61))
    for op in ("ldm", "stm", "mov"):
        for s in (ON, OFF):
            for units in (2, 6):
                out.append(string_window(op, False, 1, s, s, rep=False, units=units))
    return out


# ------------------------------------------------------------------ the timer registers' sweep
STEPS = 12      # a step's delay: ROL BP by 1 + step % 6, and a NOP on the steps 6..11


def sweep_window(fname, target, s, k, off=None, val=None, ref=False, name=None, lead=0, wtc=0,
                 pre=()):
    """fil, the step's delay, `lead` NOPs (the queue starved: fetches run up to the access), the
    access, fil. wtc: WTC for the window (field 0: the code's fetches); pre: byte stores to SFRs
    before it (offset, value)."""
    o, width, v = TARGETS[target] if off is None else (off, 1, val)
    bs, text = form(fname, o, v)

    def setup(a):
        if wtc or pre:
            seg(a, "DS1", ON)
            for po, pv in pre:
                es_store(a, 0xFF00 + po, pv)
            if wtc:
                es_store(a, 0xFFE8, wtc, word=True)
        std_setup(s)(a)

    def body(a):
        a.mov_r("AW", v or 0)
        fil(a)
        roli(a, 1 + k % 6)
        a.nop(k // 6 % 2)
        a.nop(lead)
        a.op(bs, text)
        fil(a)
    return Window(dict(form=fname, target=name or target, seg="on" if s == ON else "off",
                       shape="sweep", n=k, ref=ref), setup, body)


T_KINDS = (("wrb", "tmc0"), ("rdb", "tmc0"), ("imb", "tmc0"), ("addb", "tmc0"), ("wrb", "md0"),
           ("rdb", "md0"), ("wrw", "md0"), ("rdw", "md0"), ("imw", "md0"), ("addw", "md0"),
           ("pushm", "md0"), ("wrw", "tm0"), ("wrw", "md1"), ("rdb", "p0"))


def sweep_set():
    out = [sweep_window(f, t, s, k, ref=(f, t) == T_KINDS[0])
           for f, t in T_KINDS for k in range(STEPS) for s in (ON, OFF)]
    # the access behind running fetches (2, 3, 5 NOPs before it)
    for lead in (2, 3, 5):
        out += [sweep_window("wrb", "tmc0", s, k, name=f"tmc0 lead{lead}", lead=lead)
                for k in range(STEPS) for s in (ON, OFF)]
    # the timers' clock selects and a running timer: MD0's byte store (ignored) under TMC0 / TMC1
    # 40h (/128, stopped), TMC0 80h (TM0 running at /6), TMC0 C0h (running at /128)
    for nm, pre in (("md0 /128", ((0x90, 0x40), (0x91, 0x40))), ("md0 run/6", ((0x90, 0x80), (0x91, 0x00))),
                    ("md0 run/128", ((0x90, 0xC0),))):
        out += [sweep_window("wrb", "md0", s, k, name=nm, pre=pre)
                for k in range(STEPS) for s in (ON, OFF)]
    # the code's fetches at two waits (WTC 0002h): the access waits for the bus behind a 5-clock
    # fetch; the last windows of the program (the epilogue restores WTC)
    for lead in (0, 2, 3):
        out += [sweep_window("wrb", "tmc0", s, k, name=f"tmc0 2w lead{lead}", lead=lead, wtc=0x0002,
                             pre=((0x90, 0x00),))
                for k in range(STEPS) for s in (ON, OFF)]
    return out


def timers_off(a):
    seg(a, "DS1", ON)
    es_store(a, 0xFF90, 0x00)
    es_store(a, 0xFF91, 0x00)


# ------------------------------------------------------------------ the SFR page's survey
# byte stores that change nothing that matters: offset -> value (never PM / PMC, STBC, PRC, FLAG,
# TxB, IDB)
SAFE_STORES = {0x00: 0x00, 0x08: 0x00, 0x10: 0x00, 0x3B: 0x00, 0x40: 0x00, 0x44: 0x00, 0x45: 0x00,
               0x46: 0x00, 0x4C: 0x47, 0x4D: 0x47, 0x4E: 0x47, 0x65: 0x00, 0x66: 0x00, 0x68: 0x00,
               0x69: 0x00, 0x6A: 0x00, 0x6C: 0x47, 0x6D: 0x47, 0x6E: 0x47, 0x75: 0x00, 0x76: 0x00,
               0x78: 0x00, 0x79: 0x00, 0x7A: 0x00, 0x7C: 0x47, 0x7D: 0x47, 0x7E: 0x47, 0x80: 0x00,
               0x81: 0x00, 0x82: 0x00, 0x83: 0x00, 0x88: 0x00, 0x89: 0x00, 0x8A: 0x00, 0x8B: 0x00,
               0x90: 0x00, 0x91: 0x00, 0x94: 0x00, 0x95: 0x00, 0x96: 0x00, 0x9C: 0x47, 0x9D: 0x47,
               0x9E: 0x47, 0xA0: 0x00, 0xA1: 0x00, 0xA2: 0x00, 0xA3: 0x00, 0xAC: 0x47, 0xAD: 0x47,
               0xE1: 0xEC, 0xE8: 0x00, 0xE9: 0x00, 0xEC: 0x47}


def survey_set():
    """Every offset of the SFR page read by byte, every even offset by word, the safe offsets
    stored by byte; one step each (the step walks with the offset), with the twin; and the
    reference (a byte store to TMC0 at every step)."""
    out = [sweep_window("wrb", "tmc0", s, k, ref=True) for k in range(STEPS) for s in (ON, OFF)]
    for fname, offs in (("rdb", range(256)), ("rdw", range(0, 256, 2)), ("wrb", sorted(SAFE_STORES))):
        for i, o in enumerate(offs):
            for s in (ON, OFF):
                out.append(sweep_window(fname, f"{0xFF00 + o:04X}", s, (i + o // 16) % STEPS,
                                        off=0xFF00 + o, val=SAFE_STORES.get(o, 0)))
    # FF80h-FF9Fh at two more steps each (the offsets whose delay depends on the phase)
    for fname, offs in (("rdb", range(0x80, 0xA0)), ("rdw", range(0x80, 0xA0, 2)),
                        ("wrb", [o for o in sorted(SAFE_STORES) if 0x80 <= o < 0xA0])):
        for i, o in enumerate(offs):
            for d in (1, 6):
                for s in (ON, OFF):
                    out.append(sweep_window(fname, f"{0xFF00 + o:04X}", s,
                                            (i + o // 16 + d) % STEPS, off=0xFF00 + o,
                                            val=SAFE_STORES.get(o, 0)))
    return out


# ------------------------------------------------------------------ where a store takes effect
def wtc_window(before, store, j, s, pfx):
    def setup(a):
        seg(a, "DS1", ON)
        es_store(a, 0xFFE8, before, word=True)
        std_setup(s)(a)

    def body(a):
        a.mov_r("AW", store)
        fil(a)
        a.nop(j)
        a.op(*form("pimw" if pfx else "imw", 0xFFE8, store))
        a.nop(16)
    return Window(dict(form="pimw" if pfx else "imw", target=f"wtc {before:04X}>{store:04X}",
                       seg="on" if s == ON else "off", shape="eff", n=j), setup, body)


def wtc0(a):
    seg(a, "DS1", ON)
    es_store(a, 0xFFE8, 0x0000, word=True)


def wtcb_window(store, j, s, hi=False):
    """A byte store to WTC's low byte (field 0: the code's block) or high byte, then NOPs."""
    def setup(a):
        seg(a, "DS1", ON)
        es_store(a, 0xFFE8, 0x0002 if store == 0 else 0x0000, word=True)
        std_setup(s)(a)

    def body(a):
        a.mov_r("AW", store)
        fil(a)
        a.nop(j)
        a.op(*form("wrb", 0xFFE9 if hi else 0xFFE8, 0))
        a.nop(16)
    return Window(dict(form="wrb", target=f"wtc {'high' if hi else 'low'} byte {store:02X}h",
                       seg="on" if s == ON else "off", shape="eff", n=j), setup, body)


def p1_window(level, j, s, iso=False):
    """One byte store to P1 (P15: bit 5) from AL, among NOPs (the queue starved) or fillers."""
    def setup(a):
        wtc0(a)
        std_setup(s)(a)

    def body(a):
        a.mov_r("AW", 0x20 if level else 0x00)
        fil(a, 2 if iso else 1)
        a.nop(j)
        a.op(*form("wrb", 0xFF08, 0))
        if iso:
            fil(a)
        else:
            a.nop(12)
    return Window(dict(form="wrb", target=f"p1 {'20h' if level else '00h'}{' iso' if iso else ''}",
                       seg="on" if s == ON else "off", shape="eff", n=j), setup, body)


def tout_window(k, md, tmc=0x8C, word=False):
    """TM0 interval at /6 from MD0 = md, TOUT on P15: the start (TMC0 8Ch: ALV 1, so the pin
    falls when the store lands), a few count-outs, the stop."""
    def setup(a):
        wtc0(a)
        es_store(a, 0xFF90, 0x00)
        es_store(a, 0xFF82, md, word=True)
        es_store(a, 0xFF80, md, word=True)
        std_setup(ON)(a)

    def body(a):
        a.mov_r("AW", tmc)
        fil(a)
        roli(a, 1 + k % 6)
        a.nop(k // 6 % 2)
        a.op(*form("wrw" if word else "wrb", 0xFF90, 0))
        fil(a, 4)
        a.op(*form("imb", 0xFF90, 0x00))
        fil(a)
    return Window(dict(form="wrw" if word else "wrb", target=f"tmc0 {tmc:02X}h md0 {md}", seg="on",
                       shape="tout", n=k), setup, body)


def effect_set():
    out = []
    for before, store in ((0x0000, 0x0002), (0x0002, 0x0000), (0xFFFF, 0x0000)):
        for pfx in (False, True):
            for j in range(4):
                for s in (ON, OFF):
                    out.append(wtc_window(before, store, j, s, pfx))
    for store in (0x02, 0x00):
        for j in range(4):
            for s in (ON, OFF):
                out.append(wtcb_window(store, j, s))
    for j in range(2):
        for s in (ON, OFF):
            out.append(wtcb_window(0x80, j, s, hi=True))
    for j in range(4):
        for level in (1, 0):
            for s in (ON, OFF):
                out.append(p1_window(level, j, s))
    for level in (1, 0):
        for s in (ON, OFF):
            out.append(p1_window(level, 0, s, iso=True))
    return out


def ram_fill(a):
    """The internal RAM bytes the strings read (FFE40h-FFE7Fh), so the copies out are the same
    in every run."""
    seg(a, "DS1", ON)
    a.mov_r("IY", 0xFE40)
    a.mov_r("CW", 0x40)
    a.mov_r("AW", 0x5AA5)
    a.op([0xFC], "CLR1 DIR")
    a.op([0xF3, 0xAA], "REP STMB")


def mode_marker(a, modes):
    a.mov_r("DW", M_MODE)
    a.mov_r("AW", modes)
    a.op([0xEF], f"OUT DW, AW   ; bank modes {modes:04X}h")


def ports_on(a):
    """periph.py's TOUT hand-over: R2 released, P15 / P16 outputs, P13 the /INTAK output, R2
    claimed. PMC1 08h: P15 is the port latch's bit."""
    seg(a, "DS1", ON)
    es_store(a, 0xFF08, 0x00)
    mode_marker(a, 1 << 2)
    es_store(a, 0xFF09, 0x9F)
    es_store(a, 0xFF0A, 0x08)
    mode_marker(a, 2 << 2)


def ports_tout(a):
    seg(a, "DS1", ON)
    es_store(a, 0xFF0A, 0x28)


def ports_off(a):
    seg(a, "DS1", ON)
    es_store(a, 0xFF90, 0x00)
    es_store(a, 0xFF0A, 0x00)
    es_store(a, 0xFF09, 0xFF)
    mode_marker(a, 1 << 2)
    mode_marker(a, 0)


# ------------------------------------------------------------------ programs
class Program:
    def __init__(self, name, windows, note="", init=None, fini=None, pins=None, mid=None):
        self.name, self.windows, self.note = name, windows, note
        self.init, self.fini, self.mid = init, fini, mid or {}
        self.stim = {"entries": [], "pins": list(pins)} if pins else None
        self.ready = 0
        self._built = None

    def build(self):
        if self._built:
            return self._built
        mem = {}
        for p in (0x00, 0x3F, 0xFF):
            for o in range(0x1000):
                mem[p << 12 | o] = pat(p << 12 | o)
        m = Asm(ORG)
        m.op([0xFA], "DI")
        m.mov_r("AW", 0)
        m.mov_sr("SS")
        m.mov_r("SP", STACK_TOP)
        m.mov_sr("DS0")
        seg(m, "DS1", ON)
        es_store(m, 0xFFE1, 0xEC)                   # refresh off, as the corpus
        es_store(m, 0xFFE8, 0x0000, word=True)      # the prelude's WTC store (reset FFFFh)
        if self.init:
            self.init(m)
        m.op([0xEA, 0x00, 0x00, CODE >> 4 & 0xFF, CODE >> 12], f"BR FAR {CODE >> 4:04X}h:0000h")
        head = m.finish()
        a = Asm(0)
        for k, w in enumerate(self.windows):
            if k in self.mid:
                self.mid[k](a)
            if len(a.b) & 1:
                a.nop()                 # every window starts at an even address
            a.lines.append((b"", f"; ---- window {k}: " + " ".join(f"{x}={y}" for x, y in w.meta.items())))
            w.setup(a)
            a.mov_r("DW", M_BEGIN)
            a.mov_r("AW", k)
            a.op([0xEF], "OUT DW, AW")
            w.body(a)
            a.op([0x42], "INC DW")
            a.op([0x42], "INC DW")
            a.op([0xEF], "OUT DW, AW")
        seg(a, "DS1", ON)
        es_store(a, 0xFFE8, 0x0000, word=True)
        if self.fini:
            self.fini(a)
        a.mov_r("DW", 0xFF00)
        a.op([0xEE], "OUT DW, AL")
        a.op([0xF4], "HALT")
        a.op([0xEB, 0xFE], "BR $")
        text = a.finish()
        if len(text) > CODE_PAGES * 0x1000:
            raise ValueError(f"{self.name}: {len(text)} bytes of code")
        for i, v in enumerate(head):
            mem[ORG + i] = v
        for i in range((len(text) + 0x1010) >> 12 << 12):
            mem[CODE + i] = 0x90
        for i, v in enumerate(text):
            mem[CODE + i] = v
        for i, v in enumerate(bytes([0xEA, ORG & 0xFF, ORG >> 8, 0, 0])):
            mem[0xFFFF0 + i] = v
        segments = {}
        for p in sorted({x >> 12 for x in mem}):
            segments[p << 12] = bytes(mem[p << 12 | o] for o in range(0x1000))
        self._built = dict(text=head + text, head=m.lines, lines=a.lines, segments=segments,
                           code_end=CODE + len(text))
        return self._built

    def source(self):
        b = self.build()
        out = [f"; {self.name}: {self.note}",
               "; Generated by validation/v35s/onchip_t.py emit: the bytes are the generator's.",
               f"; The prelude runs at 00100h; the windows at {CODE:05X}h (PS {CODE >> 4:04X}h).",
               "; The image also maps the page 3F000h (the external twin's data) with wtc.py's fill."]
        for lines in (b["head"], [(b"", f"; ---- at {CODE:05X}h")], b["lines"]):
            for bs, text in lines:
                if not bs:
                    out.append(text)
                else:
                    out.append("    DB " + ", ".join(f"{v:02X}h" if v < 0xA0 else f"0{v:02X}h" for v in bs)
                               + f"    ; {text}")
        return "\n".join(out) + "\n"


def programs():
    eff = effect_set()
    tout = ([tout_window(k, md) for md in (4, 9) for k in range(STEPS)]
            + [tout_window(k, 4, word=True) for k in range(6)])
    progs = [
        Program("f4_oc_a", unit_set(A_PAIRS, RAW), "on-chip timing: the instruction forms on the "
                "internal RAM and FFFFFh, against the external twin"),
        Program("f4_oc_s", unit_set(S_PAIRS), "on-chip timing: the instruction forms on SFRs "
                "(P0, WTC, RFM, TMC0), against the external twin"),
        Program("f4_oc_k", string_set(), "on-chip timing: strings (REP LDM / STM / MOVBK) on "
                "and off the chip", init=ram_fill),
        Program("f4_oc_t", sweep_set(), "on-chip timing: the timer registers, the instruction's "
                "start swept over twelve delays", fini=timers_off),
        Program("f4_oc_v", survey_set(), "on-chip timing: every offset of the SFR page read by "
                "byte and by word, the safe ones stored, against the external twin"),
        Program("f4_oc_e", eff + tout, "where an SFR store takes effect: WTC (the next fetches' "
                "waits), P1 (the P15 pin), TMC0 (TOUT)", init=ports_on, fini=ports_off,
                pins=["P15"], mid={len(eff): ports_tout}),
    ]
    return {p.name: p for p in progs}


# ------------------------------------------------------------------ running
def receipt_path(name, backend):
    return RECEIPTS / f"f4-{name}-{backend}.json"


def load(name, backend):
    return json.loads(receipt_path(name, backend).read_text())


def run_one(harness, prog, lane, limit=60_000_000):
    b = prog.build()
    mode = "socket" if lane == "socket" else "model"
    harness.load(b["segments"])
    result = harness.run(mode, limit)
    trace = [dict(t) for t in result[f"{lane}_trace"]]
    total, replay = result[f"{lane}_total"], []
    # Later parts of the trace come from reruns, whose ticks are offset by a few ticks (the
    # reset's phase against the CPU clock): each rerun overlaps the rows already held by
    # OVERLAP records and is shifted so the overlapping starts agree.
    for start in range(CAPTURE - OVERLAP, total, CAPTURE - OVERLAP):
        harness.load(b["segments"])
        window = harness.run(mode, limit, capture_start=start)
        if window[f"{lane}_total"] != total:
            replay.append(f"total changed at window {start}")
        part = [dict(t) for t in window[f"{lane}_trace"]]
        shift = trace[start]["start"] - part[0]["start"]
        for t in part:
            t["start"] += shift
            t["end"] += shift
        for x, y in zip(trace[start:], part):
            if (x["start"], x["address"], x["data"], x["flags"]) != (
                    y["start"], y["address"], y["data"], y["flags"]):
                replay.append(f"overlap differs at record {start}")
                break
        trace.extend(part[len(trace) - start:])
    rows = [[t["start"], t["address"], t["data"], t["flags"], t["end"], t["strobe"]] for t in trace]
    return {
        "program": prog.name, "note": prog.note,
        "program_sha256": hashlib.sha256(b["text"]).hexdigest(),
        "image_sha256": hashlib.sha256(json.dumps(
            {f"{a:05X}": d.hex() for a, d in sorted(b["segments"].items())}).encode()).hexdigest(),
        "passed": result["passed"], "status": result["status"], "timeout": result["timeout"],
        "total": total, "signature": result[f"{lane}_signature"], "replay": replay, "trace": rows,
    }


def run_set(names, backend, tag, progs):
    from .traps import _board, _close_board, _sim, _stim
    lane = "socket" if backend == "socket" else "model"
    if backend == "socket":
        transport, harness = _board()
    try:
        for name in names:
            prog = progs[name]
            if backend != "socket":
                transport, harness = _sim()
            try:
                _stim(harness, prog)
                rec = run_one(harness, prog, lane)
            finally:
                if backend != "socket":
                    transport.close()
            rec.update(backend=backend, date=datetime.datetime.now().isoformat(timespec="seconds"))
            if backend == "socket":
                rec.update(cpu="uPD70337L-8", x_half=2)
            else:
                rec.update(core="v35", binary=os.environ.get(
                    "V35_SIM_BINARY", "build/fpga/v35s/verilator-direct-v35"))
            RECEIPTS.mkdir(parents=True, exist_ok=True)
            receipt_path(name, backend + tag).write_text(json.dumps(rec, separators=(",", ":")) + "\n")
            print(f"{name}: {backend}{tag} {'PASS' if rec['passed'] else 'FAIL'} "
                  f"status=0x{rec['status']:04x} total={rec['total']} records={len(rec['trace'])} "
                  f"replay={rec['replay']}", flush=True)
    finally:
        if backend == "socket":
            _close_board(transport, harness)


# ------------------------------------------------------------------ reading a trace
def kind_of(row, code_end):
    f, a = row[3], row[1]
    if f & FLAG_PIN:
        return "pin"
    if f & FLAG_REFRESH:
        return "refresh"
    if not f & FLAG_STROBE:
        return "idle"
    if f & FLAG_IO:
        return "ior" if f & FLAG_READ else "iow"
    if not f & FLAG_READ:
        return "mw"
    if CODE <= a < code_end + 0x20 or ORG <= a < 0xE00 or a >= 0xFFFF0:
        return "fetch"
    return "mr"


def waits_of(row):
    return round((row[4] - row[0] - 1) / CLK) - 2


def windows(rec, prog):
    """{k: dict(t0 = the begin marker's start tick, t1 = the end marker's start tick, T = t1 - t0,
    rows = [(kind, row)] between them, open = the begin marker's row)}; and the rows before the
    first window."""
    end = prog.build()["code_end"]
    out, head, cur = {}, [], None
    for row in rec["trace"]:
        kind = kind_of(row, end)
        if kind == "iow" and row[1] == M_BEGIN:
            cur = dict(k=row[2], t0=row[0], open=row, rows=[])
            continue
        if kind == "iow" and row[1] == M_END and cur is not None:
            cur.update(t1=row[0], T=row[0] - cur["t0"])
            out[cur["k"]] = cur
            cur = None
            continue
        if cur is not None:
            cur["rows"].append((kind, row))
        elif not out:
            head.append((kind, row))
    return out, head


def timeline(w, pins=False):
    """A window's records as text: kind, address, start in clocks after the begin marker's start,
    waits."""
    out = []
    for kind, r in w["rows"]:
        if kind == "pin":
            if pins:
                out.append(f"pin{'^' if r[1] & P15 else 'v'}@{(r[0] - w['t0']) / CLK:.2f}")
            continue
        out.append(f"{kind[0] if kind != 'fetch' else 'f'}{'' if kind == 'fetch' else kind[1:]}"
                   f"{r[1] & 0xFFF:03X}@{(r[0] - w['t0']) / CLK:.0f}"
                   + (f"+{waits_of(r)}w" if waits_of(r) else ""))
    return " ".join(out)


def clocks(t):
    return f"{t / CLK:.2f}".rstrip("0").rstrip(".")


def table(name, backend, progs, verbose=False):
    """Per (form, target, shape): the windows' lengths in ticks (on-chip and the twin) and the
    unit's cost in clocks: (T[n2] - T[n1]) / (n2 - n1)."""
    prog = progs[name]
    rec = load(name, backend)
    wins, head = windows(rec, prog)
    print(f"{name} [{backend}]: {'PASS' if rec['passed'] else 'FAIL'} total {rec['total']}, "
          f"{len(wins)}/{len(prog.windows)} windows, replay {rec['replay']}")
    groups = {}
    for k, w in enumerate(prog.windows):
        m = w.meta
        if k in wins:
            groups.setdefault((m["form"], m["target"], m["shape"]), {})[(m["seg"], m["n"])] = (k, wins[k])
    for (f, t, sh), g in groups.items():
        segs = sorted({s for s, n in g})
        ns = sorted({n for s, n in g})
        line = f"  {f:9s} {t:16s} {sh:5s}"
        for s in segs:
            ts = [g[(s, n)][1]["T"] for n in ns if (s, n) in g]
            line += f" | {s}: " + " ".join(f"n{n}={g[(s, n)][1]['T']}" for n in ns if (s, n) in g)
            if len(ts) >= 2 and sh in ("iso", "run", "rep"):
                line += f" unit {clocks((ts[-1] - ts[0]) / (ns[-1] - ns[0]))}"
        if len(segs) == 2 and all((s, n) in g for s in segs for n in ns):
            line += " | on-off " + " ".join(clocks(g[(segs[1], n)][1]["T"] - g[(segs[0], n)][1]["T"])
                                             for n in ns)
        print(line)
        if verbose:
            for (s, n), (k, w) in sorted(g.items()):
                print(f"      w{k} {s} n{n}: {timeline(w, pins=True)}")
    return wins


def sweep_rows(prog, wins):
    """Per sweep window pair (on-chip, twin): (form, target, step, phase, D, ref). D: the on-chip
    window's length less the twin's, in ticks. phase: the CPU clock, modulo 6, on which the
    access's bus cycle starts (the twin's first data cycle, placed in the on-chip window: the two
    are the same up to there), counted in the receipt's own ticks."""
    pair = {}
    for k, w in enumerate(prog.windows):
        m = w.meta
        if m["shape"] == "sweep" and k in wins:
            pair.setdefault((m["form"], m["target"], m["n"], m.get("ref", False)), {})[m["seg"]] = wins[k]
    out = []
    for (f, t, n, ref), d in pair.items():
        if "on" not in d or "off" not in d:
            continue
        data = [r[0] - d["off"]["t0"] for kind, r in d["off"]["rows"] if kind in ("mr", "mw")]
        a = d["on"]["t0"] + data[0]
        out.append((f, t, n, a // CLK % 6, d["on"]["T"] - d["off"]["T"], ref))
    return out


def sync_origin(rows):
    """The phase c at which the reference (a byte store to TMC0) waits one clock: its delay is
    ((c - phase) mod 6) + 1 at every step, or None when the reference does not behave so."""
    ref = [(ph, d) for f, t, n, ph, d, r in rows if r]
    for c in range(6):
        if ref and all(d == (((c - ph) % 6) + 1) * CLK for ph, d in ref):
            return c
    return None


def sweep_report(name, backend, progs):
    """f4_oc_t / f4_oc_v: every access's delay against the twin, by the phase of the free-running
    divide-by-six; the accesses grouped by what the delay is."""
    prog = progs[name]
    wins, _ = windows(load(name, backend), prog)
    rows = sweep_rows(prog, wins)
    c = sync_origin(rows)
    print(f"  sweep [{backend}]: reference wrb tmc0, delay ((c - phase) mod 6) + 1 clocks with c = {c}")
    by = {}
    for f, t, n, ph, d, r in rows:
        by.setdefault((f, t), []).append((ph, d))
    classes = {}
    for (f, t), v in by.items():
        flat = {clocks(d) for ph, d in v}
        saw = set() if c is None else {clocks(d - (((c - ph) % 6) + 1) * CLK) for ph, d in v}
        if flat == {"0"}:
            desc = "as the twin"
        elif len(saw) == 1 and len({ph for ph, d in v}) >= 2:
            desc = f"twin + wait(1..6) + {saw.pop()}"
        elif len(flat) == 1:
            desc = f"twin + {flat.pop()}"
        else:
            desc = "delay by phase " + " ".join(
                f"{ph}:{'/'.join(sorted({clocks(d) for q, d in v if q == ph}))}"
                for ph in sorted({q for q, d in v}))
        classes.setdefault((f, desc), []).append((t, len(v), len({ph for ph, d in v})))
    for (f, desc), ts in sorted(classes.items()):
        names = " ".join(t for t, n, k in ts)
        print(f"    {f:5s} {desc}: {len(ts)} targets ({min(k for t, n, k in ts)}..{max(k for t, n, k in ts)} "
              f"phases each): {names}")


def effect_report(name, backend, progs):
    prog = progs[name]
    wins, head = windows(load(name, backend), prog)
    print(f"  effect [{backend}]:")
    for k, w in enumerate(prog.windows):
        if k not in wins:
            continue
        m = w.meta
        print(f"    w{k} {m['form']} {m['target']} {m['seg']} j{m['n']} T={wins[k]['T']}: "
              f"{timeline(wins[k], pins=True)}")


def head_report(name, backend, progs):
    """The prelude: the fetches around the WTC store at reset WTC FFFFh."""
    prog = progs[name]
    wins, head = windows(load(name, backend), prog)
    t0 = head[0][1][0]
    print(f"  prelude [{backend}]: " + " ".join(
        f"{kind[0]}{r[1] & 0xFFF:03X}@{(r[0] - t0) / CLK:.0f}+{waits_of(r)}w" for kind, r in head
        if kind != "pin"))


def report(name, backend, progs, verbose=False):
    table(name, backend, progs, verbose)
    head_report(name, backend, progs)
    if name in ("f4_oc_t", "f4_oc_v"):
        sweep_report(name, backend, progs)
    if name == "f4_oc_e":
        effect_report(name, backend, progs)


# ------------------------------------------------------------------ comparing two receipts
def norm_window(w):
    """A window's comparable form: its length and every record (kind, address, data unless a
    read, start after the begin marker, waits); pin records by level and tick."""
    out = [("T", w["T"])]
    for kind, r in w["rows"]:
        if kind == "pin":
            out.append(("pin", r[1] & P15, r[0] - w["t0"]))
        else:
            out.append((kind, r[1], r[2] if kind in ("mw", "iow", "fetch") else 0,
                        r[0] - w["t0"], waits_of(r)))
    return out


def near(x, y, tol):
    """Two normalised windows equal with every tick within tol."""
    if len(x) != len(y):
        return False
    for p, q in zip(x, y):
        if p[0] != q[0] or len(p) != len(q):
            return False
        for i, (u, v) in enumerate(zip(p[1:], q[1:])):
            tick = (p[0] == "T") or (p[0] == "pin" and i == 1) or (p[0] not in ("T", "pin") and i == 2)
            if (abs(u - v) > tol) if tick else (u != v):
                return False
    return True


def compare(name, ref, cand, progs, tol=1, pin_tol=4, verbose=False):
    """Window by window: EQUAL when the records are the same and every tick is within tol (the
    lane's sampling: +/- 1 tick; pin records +/- pin_tol)."""
    prog = progs[name]
    a, b = load(name, ref), load(name, cand)
    if a["program_sha256"] != b["program_sha256"] or a["image_sha256"] != b["image_sha256"]:
        print(f"{name}: the receipts are of different programs")
        return False
    wa, _ = windows(a, prog)
    wb, _ = windows(b, prog)
    diff, tdiff = [], 0
    for k, w in enumerate(prog.windows):
        if k not in wa or k not in wb:
            diff.append((k, "missing"))
            continue
        x, y = norm_window(wa[k]), norm_window(wb[k])
        xb, yb = [p for p in x if p[0] != "pin"], [p for p in y if p[0] != "pin"]
        xp, yp = [p for p in x if p[0] == "pin"], [p for p in y if p[0] == "pin"]
        if not near(xb, yb, tol) or not near(xp, yp, pin_tol):
            dt = wb[k]["T"] - wa[k]["T"]
            tdiff += abs(dt) > tol
            diff.append((k, f"T {wa[k]['T']} / {wb[k]['T']} ({clocks(dt)} clocks)"
                         + ("" if abs(dt) > tol else "; same length, records differ")))
    print(f"{name}: {ref} / {cand}: {'EQUAL' if not diff else 'DIFFER'} "
          f"({len(prog.windows) - len(diff)} of {len(prog.windows)} windows equal; "
          f"{tdiff} differ in length; passed {a['passed']} / {b['passed']})")
    for k, why in diff[:None if verbose else 6]:
        m = prog.windows[k].meta
        print(f"  w{k} {m['form']} {m['target']} {m['seg']} {m['shape']} n{m['n']}: {why}")
    return not diff


def emit(progs):
    for name, prog in progs.items():
        (PROGRAMS_DIR / f"{name}.s").write_text(prog.source())
        b = prog.build()
        print(f"{name}: {len(b['text'])} bytes, {len(prog.windows)} windows, {len(b['segments'])} pages")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "report", "repeat", "gate", "emit"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--socket-fitted", action="store_true",
                   help="accepted for the board rule's spelling (the socket action needs it)")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args()
    progs = programs()
    names = a.names or list(progs)
    if a.action == "socket":
        if not a.socket_fitted:
            p.error("the socket action needs --socket-fitted")
        run_set(names, "socket", a.tag, progs)
    elif a.action == "sim":
        run_set(names, "sim", a.tag, progs)
    elif a.action == "report":
        for n in names:
            report(n, a.ref + a.tag, progs, a.verbose)
    elif a.action == "repeat":
        ok = True
        for n in names:
            ok &= compare(n, "socket", "socket-2", progs, verbose=a.verbose)
        return 0 if ok else 1
    elif a.action == "gate":
        ok = True
        for n in names:
            ok &= compare(n, a.ref, a.cand, progs, verbose=a.verbose)
        return 0 if ok else 1
    else:
        emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
