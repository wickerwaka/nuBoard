"""F4p: the order of service among macro service, DMA, NMI and the maskable interrupt
(docs/v35s-function-plan.md, stage F4; the core README's "F4p").

Directed programs measured on the socketed uPD70337 and run unchanged on the core v2 RTL in
simulation, in validation/v35s/dma.py's frame (periph.py's run, receipts and gate; intr.py's
Test, slots, handler and fast stubs; the DMA's source-page reads kept in the write sequence):

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.prio socket [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.prio sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.prio gate [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.prio show NAME [--ref socket]
    PYTHONPATH=host/src:. python3 -m validation.v35s.prio emit

Every result is an order: which macro-service transfer (an SFR-to-memory byte written at the
channel's buffer, D080h + 10h x the channel), which DMA transfer (its destination write or its
source read at F0xxh), which handler (the stub's store of its vector at 8002h) and which marker
(a CPU byte store, `dma.cw`) comes first in the write sequence. No result is a clock count.

Requests are made pending together before the point where service is decided by one of:
  - one store that sets two IC registers' IF bits (a word store across adjacent registers);
  - schedule entries that move two or more input pins at the same tick (INTP0-2, DMARQ0/1, NMI)
    while the CPU is held where it decides nothing (a chain of segment prefixes: `PFX`);
  - a level in service (ISPR) or the NMI handler holding the requests (where silicon holds them).

Receipts: validation/v35s/receipts/f4-<name>-<backend>.json (--tag adds a suffix).
"""

from __future__ import annotations

import argparse
import sys

from . import dma, periph, serial
from .intr import PSW_IE, ev, wait
from .periph import PTest, _prog
from .serial import _fix, rd, swr
from .dma import ON0, OFF0, PINS, blk_w, cw, cws, mask_rng, rq

h = periph._h
SFR = dma.SFR
SFR.update(WTC=0xE8)
serial.SFR.update(SFR)

BUF = 0xD080            # the macro-service buffers: BUF + 10h x the channel
SRCS = {                # source -> (IC register, macro-service mode register, vector)
    "P0": ("EXIC0", "EMS0", 24), "P1": ("EXIC1", "EMS1", 25), "P2": ("EXIC2", "EMS2", 26),
    "SR0": ("SRIC0", "SRMS0", 13), "ST0": ("STIC0", "STMS0", 14),
    "SR1": ("SRIC1", "SRMS1", 17), "ST1": ("STIC1", "STMS1", 18),
    "TU0": ("TMIC0", "TMMS0", 28), "TU1": ("TMIC1", "TMMS1", 29), "TU2": ("TMIC2", "TMMS2", 30),
}


def ms_set(src, ch, msc=3, ic=0x27):
    """`src` in macro service on channel ch (SFR BRG1 -> memory at BUF + 10h ch, bytes, MSC
    msc); its IC register = ic (default: MS 1, MK 0, IF 0, PR 7)."""
    icr, msr, _ = SRCS[src]
    return (serial.chan(ch, msc, 0x7A, 0x00, BUF + 0x10 * ch) + swr(msr, 0x10 | ch)
            + swr(icr, ic))


def msc_rd(ch, k, i):
    """The channel's MSC into RES + 20h k + i."""
    return (f"    DB 26h\n    MOV AL, [{h(0xFE00 + 8 * ch, 4)}]\n"
            f"    DB 2Eh\n    MOV [{h(dma.RES + 0x20 * k + i, 4)}], AL\n")


def wst(name, val):
    """A word store at an SFR offset (two adjacent byte registers in one store)."""
    return f"    DB 26h\n    MOV word [0FF{SFR[name]:02X}h], {h(val, 4)}\n"


def pfx(n):
    """A chain of n PS prefixes (the instruction that follows carries them)."""
    out = ""
    while n > 0:
        m = min(n, 16)
        out += "    DB " + ", ".join(["2Eh"] * m) + "\n"
        n -= m
    return out


def act_skip_nmi(tag="an"):
    """An action: FINT unless the vector is NMI's."""
    return f"    DB 2Eh\n    CMP byte [8002h], 2\n    BE {tag}{{k}}\n    FINT\n{tag}{{k}}:\n"


def edges(ev_, pins, delay, hold=2000):
    """One schedule entry moving several pins at once: INTPn / NMI low (falling edges),
    DMARQn high, for `hold` ticks."""
    lv = {p: (1 if p.startswith("DMARQ") else 0) for p in pins}
    return {"event": ev_, "delay": delay, "hold": hold, "levels": lv}


BRG = swr("BRG1", 0x5A)
CLR = swr("BRG1", 0x00)


# ------------------------------------------------------------------ exploration (measured only)
def x1_tests():
    """Macro service: simultaneous sources by word stores; against ISPR, NMI, a prefix chain,
    a DMA burst; the completion's vector and ISPR."""
    T = [periph.init_test()]

    def w2(name, a, b, at, val, psw=0x0002, note=""):
        t = PTest(name, jitter=False, psw=psw, note=note)
        t.codef = lambda k: (BRG + ms_set(a, 2, ic=0x47) + ms_set(b, 3, ic=0x47) + wst(at, val)
                             + cws(k, 4) + rd(SRCS[a][0], k, 0) + rd(SRCS[b][0], k, 1)
                             + msc_rd(2, k, 2) + msc_rd(3, k, 3) + CLR)
        return t
    T += [
        w2("w_p01", "P0", "P1", "EXIC0", 0xA7A7),
        w2("w_p12", "P1", "P2", "EXIC1", 0xA7A7),
        w2("w_tu01", "TU0", "TU1", "TMIC0", 0xA7A7),
        w2("w_tu12", "TU1", "TU2", "TMIC1", 0xA7A7),
        w2("w_s0", "SR0", "ST0", "SRIC0", 0xA7A7),
        w2("w_s1", "SR1", "ST1", "SRIC1", 0xA7A7),
        # a vectored request (MS 0) and a macro service at once, IE 1
        w2("w_p0v_p1m", "P0", "P1", "EXIC0", 0xA787, psw=PSW_IE),
        w2("w_p0m_p1v", "P0", "P1", "EXIC0", 0x87A7, psw=PSW_IE),
    ]

    # ISPR: a vectored handler (INTP0) in service, a macro service requested inside it
    def isp(name, vec_ic, ms_ic, note=""):
        t = PTest(name, jitter=False, psw=PSW_IE, note=note,
                  action=("    DB 2Eh\n    CMP byte [8002h], 18h\n    BNE ia{k}\n"
                          + swr("TMIC0", ms_ic) + "{CW3}" + "    FINT\n" + "{CW2}"
                          + "    RET\nia{k}:\n    FINT\n"))
        act = t.action

        def code(k):
            t.action = act.replace("{CW3}", cws(k, 3)).replace(
                "{CW2}", cw(k, 3, 0xB3) + cw(k, 4, 0xB4))
            return (BRG + ms_set("TU0", 5, ic=0x47) + swr("EXIC0", vec_ic) + "    NOP\n" * 4
                    + cw(k, 5, 0xB5) + msc_rd(5, k, 0) + rd("TMIC0", k, 1) + CLR)
        t.codef = code
        return t
    T += [
        isp("is_hi", 0x80, 0xA7, note="INTP0 at 0 in service, TU0 at 7 in macro service"),
        isp("is_lo", 0x87, 0xA0, note="INTP0 at 7 in service, TU0 at 0"),
        isp("is_eq", 0x83, 0xA3, note="both at 3"),
    ]
    # NMI's handler: a macro service requested inside it
    t = PTest("nmi_ms", jitter=True, stim=[{"event": "E0", "delay": 12000, "hold": 2000,
                                             "levels": {"NMI": 0}}],
              action=("    DB 2Eh\n    CMP byte [8002h], 2\n    BNE nm{k}\n" + intr_nmi_skip()
                      + swr("TMIC0", 0xA7) + "{CW3}" + "    RET\nnm{k}:\n    FINT\n"))
    act = t.action

    def c_nmi(k, t=t, act=act):
        t.action = act.replace("{CW3}", cws(k, 3))
        return (BRG + ms_set("TU0", 5, ic=0x47) + ev("E0") + "    HALT\n    NOP\n    NOP\n"
                + cw(k, 4, 0xB4) + msc_rd(5, k, 0) + rd("TMIC0", k, 1) + CLR)
    t.codef = c_nmi
    T.append(t)

    # a prefix chain: INTP0's edge (macro service) lands inside it
    t = PTest("pfx_ms", jitter=False, stim=[{"event": "E0", "delay": 6000, "hold": 2000,
                                              "levels": {"INTP0": 0}}])
    t.codef = lambda k: (BRG + ms_set("P0", 2) + ev("E0") + cw(k, 0, 0xA0) + pfx(320)
                         + cw(k, 1, 0xA1) + cw(k, 2, 0xA2) + msc_rd(2, k, 0) + rd("EXIC0", k, 1)
                         + CLR)
    T.append(t)
    # a DMA burst (channel 0, memory to memory, 32 bytes): INTP0's edge lands inside it
    t = PTest("burst_ms", jitter=False, stim=[{"event": "E0", "delay": 4000, "hold": 2000,
                                                "levels": {"INTP0": 0}}])
    t.codef = lambda k: (BRG + ms_set("P0", 2) + swr("DIC0", 0x47)
                         + blk_w(0, 0x0000, 0x0000, 0x0F, 0x0D, 32) + swr("DMAC0", 0x11)
                         + ev("E0") + swr("DMAM0", 0x8C) + cws(k, 4) + msc_rd(2, k, 0)
                         + rd("EXIC0", k, 1) + rd("DMAM0", k, 2) + swr("DMAM0", 0x00) + CLR)
    T.append(t)
    # the count's end: MSC 1, IE 1: the vectored request (TU0 at 3): ISPR in the handler
    t = PTest("end_isp", jitter=False, psw=PSW_IE)
    t.codef = lambda k: (BRG + ms_set("TU0", 5, msc=1, ic=0x47) + swr("TMIC0", 0xA3)
                         + "    NOP\n" * 4 + cws(k, 2) + msc_rd(5, k, 0) + rd("TMIC0", k, 1)
                         + rd("ISPR", k, 2) + CLR)
    T.append(t)
    # with IE 1: the completion's vectored request against the other macro service
    t = PTest("end_vs_ms_ie", jitter=False, psw=PSW_IE)
    t.codef = lambda k: (BRG + ms_set("P0", 2, msc=1, ic=0x47) + ms_set("P1", 3, ic=0x47)
                         + wst("EXIC0", 0xA7A7) + cws(k, 4) + rd("EXIC0", k, 0)
                         + rd("EXIC1", k, 1) + msc_rd(2, k, 2) + msc_rd(3, k, 3) + CLR)
    T.append(t)
    # the count's end with IE 0 while another macro service is requested: P0 (MSC 1) and P1 by
    # one store; then EI
    t = PTest("end_vs_ms", jitter=False)
    t.codef = lambda k: (BRG + ms_set("P0", 2, msc=1, ic=0x47) + ms_set("P1", 3, ic=0x47)
                         + wst("EXIC0", 0xA7A7) + cws(k, 2) + rd("EXIC0", k, 0)
                         + rd("EXIC1", k, 1) + "    EI\n" + "    NOP\n" * 4 + cws(k, 2)
                         + "    DI\n" + msc_rd(2, k, 2) + msc_rd(3, k, 3) + CLR)
    T.append(t)
    return _fix(T)


def intr_nmi_skip():
    from .intr import nmi_skip
    return nmi_skip()


def x2_tests(gated=False):
    """DMA: both channels at once; a burst against a request on the other channel; TC with 0
    and 1 waits."""
    T = [periph.init_test()]
    DD = 0xD000
    # single transfer, I/O to memory, both channels: DMARQ0 and DMARQ1 rise at the same tick
    t = mask_rng(PTest("rq_in", jitter=False,
                       stim=[edges("E0", ["DMARQ0", "DMARQ1"], 2000, 400),
                             edges("E1", ["DMARQ0", "DMARQ1"], 2000, 400)]), DD, 0x40)
    t.codef = lambda k: (ON0 + blk_w(0, 0, 0x0000, 0x0F, 0x0D, 4) + blk_w(1, 0, 0x0020, 0x0F, 0x0D, 4)
                         + swr("DMAC0", 0x11) + swr("DMAC1", 0x11) + swr("DMAM0", 0xA8)
                         + swr("DMAM1", 0xA8) + ev("E0") + wait(40, "a") + ev("E1")
                         + wait(40, "b") + swr("DMAM0", 0x00) + swr("DMAM1", 0x00) + OFF0)
    T.append(t)
    # single transfer, memory to I/O, both channels (the source reads at F000h- / F020h-)
    t = PTest("rq_out", jitter=False, stim=[edges("E0", ["DMARQ0", "DMARQ1"], 2000, 400),
                                             edges("E1", ["DMARQ0", "DMARQ1"], 2000, 400)])
    t.codef = lambda k: (ON0 + blk_w(0, 0x0000, 0, 0x0F, 0x0D, 4) + blk_w(1, 0x0020, 0, 0x0F, 0x0D, 4)
                         + swr("DMAC0", 0x11) + swr("DMAC1", 0x11) + swr("DMAM0", 0xC8)
                         + swr("DMAM1", 0xC8) + ev("E0") + wait(40, "a") + ev("E1")
                         + wait(40, "b") + swr("DMAM0", 0x00) + swr("DMAM1", 0x00) + OFF0)
    T.append(t)
    # demand release, I/O to memory, both channels: DMARQ0 and DMARQ1 high together
    t = mask_rng(PTest("dem", jitter=False,
                       stim=[edges("E0", ["DMARQ0", "DMARQ1"], 2000, 6000)]), DD, 0x40)
    t.codef = lambda k: (ON0 + blk_w(0, 0, 0x0000, 0x0F, 0x0D, 6) + blk_w(1, 0, 0x0020, 0x0F, 0x0D, 6)
                         + swr("DMAC0", 0x11) + swr("DMAC1", 0x11) + swr("DMAM0", 0x28)
                         + swr("DMAM1", 0x28) + ev("E0") + wait(60, "a")
                         + blk_rd2(k) + swr("DMAM0", 0x00) + swr("DMAM1", 0x00) + OFF0)
    if not gated:          # demand release: how many transfers fit in the pulse is the clocks'
        T.append(t)

    # memory to memory, both channels started by TDMA (one after the other)
    def mm(name, first, second, tc0=4, tc1=4, n=10):
        t = PTest(name, jitter=False)
        st = {0: lambda m: swr("DMAM0", m), 1: lambda m: swr("DMAM1", m)}
        t.codef = lambda k: (blk_w(0, 0x0000, 0x0040, 0x0F, 0x0D, tc0)
                             + blk_w(1, 0x0020, 0x0060, 0x0F, 0x0D, tc1)
                             + swr("DMAC0", 0x11) + swr("DMAC1", 0x11)
                             + st[first[0]](first[1]) + st[second[0]](second[1]) + cws(k, n)
                             + blk_rd2(k) + swr("DMAM0", 0x00) + swr("DMAM1", 0x00))
        return t
    T += [
        mm("ss_01", (0, 0x0C), (1, 0x0C)),          # single step both, ch0 started first
        mm("ss_10", (1, 0x0C), (0, 0x0C)),          # ch1 first
        mm("bu_01", (0, 0x8C), (1, 0x8C)),          # burst both, ch0 first
        mm("bu_10", (1, 0x8C), (0, 0x8C)),          # burst both, ch1 first
        mm("ss1_bu0", (1, 0x0C), (0, 0x8C), tc1=6),   # ch1 single step running, ch0 burst
        mm("ss0_bu1", (0, 0x0C), (1, 0x8C), tc0=6),   # ch0 single step running, ch1 burst
    ]
    # a burst on one channel (32 bytes) and a DMARQ edge for the other (single transfer)
    for b, o in ((0, 1), (1, 0)):
        t = mask_rng(PTest(f"bu{b}_rq{o}", jitter=False,
                           stim=[edges("E0", [f"DMARQ{o}"], 4000, 400)]), DD + 0xE0, 4)
        t.codef = (lambda b, o: lambda k: (
            ON0 + blk_w(b, 0x0000, 0x0000, 0x0F, 0x0D, 32) + blk_w(o, 0, 0x00E0, 0x0F, 0x0D, 2)
            + swr("DMAC0", 0x11) + swr("DMAC1", 0x11) + swr(f"DMAM{o}", 0xA8) + ev("E0")
            + swr(f"DMAM{b}", 0x8C) + cws(k, 4) + blk_rd2(k)
            + swr("DMAM0", 0x00) + swr("DMAM1", 0x00) + OFF0))(b, o)
        T.append(t)
    # TC with 0 and 1 programmed waits (WTC), burst of 2 on channel 0 and on channel 1
    for wtc, nm in ((0x0000, "tc_w0"), (0x5555, "tc_w1"), (0xAAAA, "tc_w2")):
        t = PTest(nm, jitter=False)
        t.codef = (lambda wtc: lambda k: (
            ON0 + blk_w(0, 0x0000, 0x00C0, 0x0F, 0x0D, 2) + blk_w(1, 0x0010, 0x00D0, 0x0F, 0x0D, 2)
            + swr("DMAC0", 0x11) + swr("DMAC1", 0x11) + periph.sfr_ww("WTC", wtc)
            + swr("DMAM0", 0x8C) + cws(k, 2) + swr("DMAM1", 0x8C) + cws(k, 2)
            + periph.sfr_ww("WTC", 0xFFFF) + swr("DMAM0", 0x00) + swr("DMAM1", 0x00) + OFF0))(wtc)
        T.append(t)
    return _fix(T)


def blk_rd2(k):
    """Both DMA channel blocks' TC words into RES + 20h k + 8 / + 10."""
    return (f"    DB 26h\n    MOV AW, [0FE06h]\n    DB 2Eh\n    MOV [{h(dma.RES + 0x20 * k + 8, 4)}], AW\n"
            f"    DB 26h\n    MOV AW, [0FE0Eh]\n    DB 2Eh\n    MOV [{h(dma.RES + 0x20 * k + 10, 4)}], AW\n")


def x3_tests():
    """NMI, macro service, DMA and the maskable interrupt pending together inside a prefix
    chain (the pins moved at one tick), and at a REP string's take point."""
    T = [periph.init_test()]
    DD = 0xD000

    def all4(name, pins, rep=False, psw=PSW_IE, n=320, ms="P0", vec="EXIC1"):
        t = mask_rng(PTest(name, jitter=False, psw=psw, action=act_skip_nmi(),
                           stim=[edges("E0", pins, 6000, 2000)]), DD, 0x10)

        def code(k):
            body = pfx(n) + ("    DB 0F3h, 0A5h\n" if rep else "    NOP\n")
            s = (BRG + ms_set(ms, 2) + swr(vec, 0x07) + ON0
                 + blk_w(0, 0, 0x0000, 0x0F, 0x0D, 2) + swr("DMAC0", 0x11) + swr("DMAM0", 0xA8))
            if rep:
                s += ("    PUSH DS1\n    PUSH CW\n    PUSH IX\n    PUSH IY\n    MOV AW, 0B00h\n"
                      "    MOV DS1, AW\n    MOV CW, 0010h\n    XOR IX, IX\n    MOV IY, 0040h\n")
            s += ev("E0") + cw(k, 0, 0xA0) + body
            if rep:
                s += "    POP IY\n    POP IX\n    POP CW\n    POP DS1\n"
            s += (cw(k, 1, 0xA1) + cw(k, 2, 0xA2) + msc_rd(2, k, 0) + rd("EXIC0", k, 1)
                  + rd("EXIC1", k, 2) + swr("DMAM0", 0x00) + OFF0 + CLR)
            return s
        t.codef = code
        return t
    T += [
        all4("a_all", ["NMI", "INTP0", "INTP1", "DMARQ0"]),
        all4("a_ms_dma", ["INTP0", "DMARQ0"]),
        all4("a_nmi_ms", ["NMI", "INTP0"]),
        all4("a_nmi_dma", ["NMI", "DMARQ0"]),
        all4("a_ms_int", ["INTP0", "INTP1"]),
        all4("a_dma_int", ["DMARQ0", "INTP1"]),
        all4("a_int_ms", ["INTP0", "INTP1"], ms="P1", vec="EXIC0"),
        all4("a_nmi_int", ["NMI", "INTP1"]),
        all4("r_all", ["NMI", "INTP0", "INTP1", "DMARQ0"], rep=True),
        all4("r_ms_dma", ["INTP0", "DMARQ0"], rep=True),
        all4("r_ms_int", ["INTP0", "INTP1"], rep=True),
        all4("r_int_ms", ["INTP0", "INTP1"], rep=True, ms="P1", vec="EXIC0"),
        all4("r_dma_int", ["DMARQ0", "INTP1"], rep=True),
    ]
    return _fix(T)


ABS = "    MULU CL\n" * 4      # an absorber (no write): the services decided before it land in it


def x4_tests(reps=(False,), gated=False):
    """A DMA burst (channel 1, memory to memory, 40 bytes) as the hold: NMI, INTP0 (macro
    service), INTP1 (vectored, IE 1) and DMARQ0 (channel 0, a single transfer) moved at one tick
    inside it; after the burst an absorber, then markers. r_*: the burst started right before a
    REP LDMW (no write), so the services fall at the string's take point."""
    T = [periph.init_test()]
    DD = 0xD000

    def b(name, pins, rep=False, ms="P0", vec="EXIC1", tc=40):
        t = mask_rng(PTest(name, jitter=gated, psw=PSW_IE, action=act_skip_nmi() + (ABS if gated else ""),
                           stim=[edges("E0", pins, 4000, 2000)]), DD + 0x60, 2)

        def code(k):
            s = (BRG + ms_set(ms, 2) + swr(vec, 0x07) + ON0 + swr("DIC0", 0x47) + swr("DIC1", 0x47)
                 + blk_w(1, 0x0040, 0x0000, 0x0F, 0x0D, tc) + blk_w(0, 0, 0x0060, 0x0F, 0x0D, 2)
                 + swr("DMAC0", 0x11) + swr("DMAC1", 0x11) + swr("DMAM0", 0xA8))
            if rep:
                s += ("    PUSH CW\n    PUSH IX\n    MOV CW, 0040h\n    XOR IX, IX\n"
                      + ev("E0") + swr("DMAM1", 0x8C) + "    DB 0F3h, 0ADh\n"
                      + "    POP IX\n    POP CW\n")
            else:
                s += ev("E0") + swr("DMAM1", 0x8C) + "    NOP\n"
            s += (ABS + "    DI\n" + cws(k, 2) + msc_rd(2, k, 0) + rd("EXIC0", k, 1)
                  + rd("EXIC1", k, 2) + rd("DMAM1", k, 3) + blk_rd2(k)
                  + swr("DMAM0", 0x00) + swr("DMAM1", 0x00) + OFF0 + CLR)
            return s
        t.codef = code
        return t
    for rep in reps:
        p = "r_" if rep else "b_"
        T += [
            b(p + "nmi", ["NMI"], rep), b(p + "int", ["INTP1"], rep), b(p + "ms", ["INTP0"], rep),
            b(p + "dma", ["DMARQ0"], rep)] + ([] if gated else [
            b(p + "all", ["NMI", "INTP0", "INTP1", "DMARQ0"], rep),
            b(p + "ms_dma", ["INTP0", "DMARQ0"], rep)]) + [
            b(p + "nmi_ms", ["NMI", "INTP0"], rep),
            b(p + "nmi_dma", ["NMI", "DMARQ0"], rep), b(p + "ms_int", ["INTP0", "INTP1"], rep),
            b(p + "int_ms", ["INTP0", "INTP1"], rep, ms="P1", vec="EXIC0"),
        ] + ([] if gated else [b(p + "dma_int", ["DMARQ0", "INTP1"], rep)]) + [
            b(p + "nmi_int", ["NMI", "INTP1"], rep),
        ]
    return _fix(T)


# ------------------------------------------------------------------ the gated macro-service set
FA = "    FINT\n" + ABS           # a handler's action: FINT, then an absorber (a service released
                                # by the FINT lands in it, before any write)


def ms_gate_tests(extra=False):
    """Macro service among sources and against vectored requests, ISPR, IE, NMI; every service
    decided before an absorber, so only the order of the services is in the write sequence."""
    T = [periph.init_test()]

    def w2(name, a, b, at, val, psw=0x0002):
        t = PTest(name, jitter=bool(psw & 0x200), psw=psw, action=FA)
        t.codef = lambda k: (BRG + ms_set(a, 2, ic=0x47) + ms_set(b, 3, ic=0x47) + wst(at, val)
                             + ABS + cws(k, 2) + rd(SRCS[a][0], k, 0) + rd(SRCS[b][0], k, 1)
                             + msc_rd(2, k, 2) + msc_rd(3, k, 3) + CLR)
        return t
    T += [
        # two sources in one group by one store (IE 0): the group's fixed order
        w2("w_p01", "P0", "P1", "EXIC0", 0xA7A7), w2("w_p12", "P1", "P2", "EXIC1", 0xA7A7),
        w2("w_tu01", "TU0", "TU1", "TMIC0", 0xA7A7), w2("w_tu12", "TU1", "TU2", "TMIC1", 0xA7A7),
        w2("w_s0", "SR0", "ST0", "SRIC0", 0xA7A7), w2("w_s1", "SR1", "ST1", "SRIC1", 0xA7A7),
        # a vectored request and a macro service in one group at once (IE 1): the order of the
        # sources, whatever the kind
        w2("w_p0v_p1m", "P0", "P1", "EXIC0", 0xA787, PSW_IE),
        w2("w_p0m_p1v", "P0", "P1", "EXIC0", 0x87A7, PSW_IE),
        w2("w_tu0v_tu1m", "TU0", "TU1", "TMIC0", 0xA787, PSW_IE),
        w2("w_tu0m_tu1v", "TU0", "TU1", "TMIC0", 0x87A7, PSW_IE),
    ]

    # in INTP0's handler at level 0 (every other level held by ISPR): the requests made by
    # stores, FINT releases them at once (IE 0 in the handler: a vectored winner waits for EI)
    def held(name, stores, ms=(), vec_ic=0x80, ei=True, ie_rel=False):
        t = PTest(name, jitter=True, psw=PSW_IE)

        def code(k, t=t):
            t.action = ("    DB 2Eh\n    CMP byte [8002h], 18h\n    BNE hx{k}\n"
                        + "".join(swr(r, v) for r, v in stores) + ABS + cw(k, 0, 0xA0)
                        + ("    EI\n" if ie_rel else "") + "    FINT\n" + ABS + cw(k, 1, 0xA1)
                        + ("    EI\n" + ABS + "    DI\n" if ei else "") + cw(k, 2, 0xA2)
                        + "    RET\nhx{k}:\n" + FA)
            return (BRG + "".join(ms_set(s, c, ic=0x47) for s, c in ms)
                    + swr("SEIC0", 0x47) + swr("SEIC1", 0x47) + swr("EXIC0", vec_ic) + ABS
                    + cw(k, 3, 0xA3) + "".join(msc_rd(c, k, i) for i, (s, c) in enumerate(ms))
                    + rd("ISPR", k, 6) + CLR)
        t.codef = code
        return t
    M3 = (("TU0", 4), ("SR0", 5), ("SR1", 6))
    if extra:
        # a vectored request and a macro service in two groups, released together with IE 1
        # (EI, FINT) or IE 0; within one group (TU0 / TU1) with IE 0
        T += [
            held("y_vm_ie", [("TMIC0", 0x83), ("SEIC0", 0x45), ("SRIC0", 0xA7)], (("SR0", 5),),
                 ie_rel=True),
            held("y_mv_ie", [("TMIC0", 0xA3), ("SEIC0", 0x45), ("SRIC0", 0x87)], (("TU0", 4),),
                 ie_rel=True),
            held("y_vm_eq_ie", [("TMIC0", 0x85), ("SEIC0", 0x45), ("SRIC0", 0xA7)],
                 (("SR0", 5),), ie_rel=True),
            held("y_mv_eq_ie", [("TMIC0", 0xA5), ("SEIC0", 0x45), ("SRIC0", 0x87)],
                 (("TU0", 4),), ie_rel=True),
            held("y_svm_ie", [("TMIC0", 0xA5), ("SEIC0", 0x43), ("SRIC0", 0x87)],
                 (("TU0", 4),), ie_rel=True),
            held("y_svm_di", [("TMIC0", 0xA5), ("SEIC0", 0x43), ("SRIC0", 0x87)],
                 (("TU0", 4),)),
            held("y_tu_vm_di", [("TMIC0", 0x83), ("TMIC1", 0xA7)], (("TU1", 4),)),
            held("y_tu_vm_ie", [("TMIC0", 0x83), ("TMIC1", 0xA7)], (("TU1", 4),), ie_rel=True),
            held("y_tu_mv_di", [("TMIC0", 0xA3), ("TMIC1", 0x87)], (("TU0", 4),)),
            held("y_tu_vmm_di", [("TMIC0", 0x83), ("TMIC1", 0xA7), ("TMIC2", 0xA7), ("SRIC0", 0xA7),
                                 ("SEIC0", 0x45)], (("TU1", 4), ("TU2", 5), ("SR0", 6))),
            held("y_tu_mk_di", [("TMIC0", 0xC3), ("TMIC1", 0xA7)], (("TU1", 4),)),
        ]
        return _fix(T)
    T += [
        held("x_eq", [("TMIC0", 0xA7), ("SRIC0", 0xA7), ("SRIC1", 0xA7)], M3),
        held("x_lv", [("TMIC0", 0xA6), ("SEIC0", 0x45), ("SEIC1", 0x42), ("SRIC0", 0xA7),
                      ("SRIC1", 0xA7)], M3),
        held("x_lv2", [("TMIC0", 0xA1), ("SEIC0", 0x44), ("SEIC1", 0x44), ("SRIC0", 0xA7),
                       ("SRIC1", 0xA7)], M3),
        held("x_vm", [("TMIC0", 0x83), ("SEIC0", 0x45), ("SRIC0", 0xA7)], (("SR0", 5),)),
        held("x_mv", [("TMIC0", 0xA3), ("SEIC0", 0x45), ("SRIC0", 0x87)], (("TU0", 4),)),
        # the handler at 7 / 3 / 0, the macro service (TU0) at 0 / 3 / 7: served inside the
        # handler when higher, after its FINT when equal or lower
        held("is_lo", [("TMIC0", 0xA0)], (("TU0", 4),), vec_ic=0x87, ei=False),
        held("is_eq", [("TMIC0", 0xA3)], (("TU0", 4),), vec_ic=0x83, ei=False),
        held("is_hi", [("TMIC0", 0xA7)], (("TU0", 4),), vec_ic=0x80, ei=False),
    ]
    # NMI's handler does not hold a macro service
    t = PTest("nmi_ms", jitter=True, stim=[{"event": "E0", "delay": 12000, "hold": 2000,
                                             "levels": {"NMI": 0}}])

    def c_nmi(k, t=t):
        t.action = ("    DB 2Eh\n    CMP byte [8002h], 2\n    BNE nm{k}\n" + intr_nmi_skip()
                    + swr("TMIC0", 0xA7) + ABS + cw(k, 0, 0xA0) + "    RET\nnm{k}:\n" + FA)
        return (BRG + ms_set("TU0", 5, ic=0x47) + ev("E0") + "    HALT\n    NOP\n    NOP\n" + ABS
                + cw(k, 1, 0xA1) + msc_rd(5, k, 0) + rd("TMIC0", k, 1) + CLR)
    t.codef = c_nmi
    T.append(t)
    # the count's end (MSC 1): the vectored request at the source's level (ISPR set: the log)
    t = PTest("end_isp", jitter=True, psw=PSW_IE, action=FA)
    t.codef = lambda k: (BRG + ms_set("TU0", 5, msc=1, ic=0x47) + swr("TMIC0", 0xA3) + ABS
                         + cws(k, 2) + msc_rd(5, k, 0) + rd("TMIC0", k, 1) + rd("ISPR", k, 2) + CLR)
    T.append(t)
    # the count's end of P0 and P1's request by one store: IE 1, then IE 0 (P0's vectored request
    # holds P1's macro service until EI)
    for nm, psw in (("end_ms_ie", PSW_IE), ("end_ms_di", 0x0002)):
        t = PTest(nm, jitter=True, psw=psw, action=FA)
        t.codef = lambda k: (BRG + ms_set("P0", 2, msc=1, ic=0x47) + ms_set("P1", 3, ic=0x47)
                             + wst("EXIC0", 0xA7A7) + ABS + cw(k, 0, 0xA0) + rd("EXIC0", k, 0)
                             + rd("EXIC1", k, 1) + "    EI\n" + ABS + "    DI\n" + cw(k, 1, 0xA1)
                             + msc_rd(2, k, 2) + msc_rd(3, k, 3) + CLR)
        T.append(t)
    return _fix(T)


def pushr(aw, cw, dw, bw, ix, iy, after="    MULU CL\n"):
    """One PUSH R through SS:SP = F000:FFA4h (SS:SP restored right after, behind MOV SS's hold): AW -> DMAC1/DMAM1 (FFA2h), CW -> DMAC0/DMAM0,
    DW -> TMIC2/-, BW -> TMIC0/TMIC1, SP -> FF9Ah (unassigned), BP -> FF98h (unassigned),
    IX -> TMMS2/-, IY -> TMMS0/TMMS1: a DMA start and a timer request in one instruction; then
    `after`, SS:SP restored."""
    return (f"    MOV AW, {h(aw, 4)}\n    MOV CW, {h(cw, 4)}\n    MOV DW, {h(dw, 4)}\n"
            f"    MOV BW, {h(bw, 4)}\n    MOV IX, {h(ix, 4)}\n    MOV IY, {h(iy, 4)}\n"
            "    MOV BP, 0F000h\n    MOV SS, BP\n    MOV SP, 0FFA4h\n    XOR BP, BP\n"
            "    DB 60h\n    MOV SS, BP\n    MOV SP, 7F00h\n" + after)


def x7_tests():
    """DMA (TDMA in DMAM0) and a timer's request (TMIC0) made by one PUSH R, an absorber after:
    which is served first."""
    T = [periph.init_test()]

    def t(name, cw, bw, psw=0x0002, after="    MULU CL\n"):
        x = PTest(name, jitter=bool(psw & 0x200), psw=psw, action=FA)
        x.codef = lambda k: (BRG + ms_set("TU0", 5, ic=0x47) + swr("DIC0", 0x47)
                             + blk_w(0, 0x0000, 0x0040, 0x0F, 0x0D, 2)
                             + pushr(0x0000, cw, 0x4747, bw, 0x0044, 0x4415, after) + ABS
                             + cws(k, 2) + msc_rd(5, k, 0) + rd("TMIC0", k, 1) + rd("DMAM0", k, 2)
                             + blk_rd2(k).split("    DB 26h\n    MOV AW, [0FE0Eh]")[0] + swr("DMAM0", 0x00) + CLR)
        return x
    T += [
        t("p_st_ms", 0x0C11, 0x47A7),               # single step, TU0 macro service
        t("p_bu_ms", 0x8C11, 0x47A7),               # burst
        t("p_st_ms_0", 0x0C11, 0x47A7, after=""),   # no absorber
        t("p_none_ms", 0x0011, 0x47A7),             # no DMA: the macro service alone
        t("p_st_none", 0x0C11, 0x4747),             # the DMA alone
    ]
    return _fix(T)


def msr_tests(m):
    """A reserved macro-service mode (MSM m) requested by a store of EXIC0's IF; an NMI 20,000
    ticks later whose handler masks EXIC0 (MS 0): does NMI recover the CPU?"""
    T = [periph.init_test()]
    t = PTest(f"msr{m}", jitter=True, stim=[{"event": "E0", "delay": 20000, "hold": 2000,
                                             "levels": {"NMI": 0}}],
              action=("    DB 2Eh\n    CMP byte [8002h], 2\n    BNE mr{k}\n" + swr("EXIC0", 0x47)
                      + "    RET\nmr{k}:\n    FINT\n"))
    t.codef = lambda k: (BRG + serial.chan(2, 3, 0x7A, 0x00, BUF + 0x20) + swr("EMS0", m << 5 | 0x12)
                         + ev("E0") + swr("EXIC0", 0xA7) + wait(200, "w") + cws(k, 2)
                         + msc_rd(2, k, 0) + rd("EXIC0", k, 1) + rd("EMS0", k, 2) + CLR)
    T.append(t)
    return _fix(T)


def programs():
    progs = {
        "f4p_msr2": _prog("f4p_msr2", msr_tests(2), gate=False,
                          note="explore: the reserved macro-service mode 010 and an NMI"),
        "f4p_msr7": _prog("f4p_msr7", msr_tests(7), gate=False,
                          note="explore: the reserved macro-service mode 111 and an NMI"),
        "f4p_x7": _prog("f4p_x7", x7_tests(), fast=(20, 21, 29, 30), gate=False,
                        note="explore: DMA and a macro service started by one PUSH R"),
        "f4p_x6": _prog("f4p_x6", ms_gate_tests(True), fast=(20, 21, 29, 30, 13, 14, 17, 18),
                        gate=False, note="explore: vectored and macro service across groups"),
        "f4p_ms": _prog("f4p_ms", ms_gate_tests(), fast=(20, 21, 29, 30, 13, 14, 17, 18),
                        note="macro service: sources, kinds, ISPR, IE, NMI (function: the order)"),
        "f4p_hb": _prog("f4p_hb", x4_tests(gated=True), pins=PINS, fast=(20, 21, 28),
                        note="NMI, macro service, DMA, INTP held by a DMA burst (the order)"),
        "f4p_hr": _prog("f4p_hr", x4_tests((True,), gated=True), pins=PINS, fast=(20, 21, 28),
                        note="as f4p_hb at a REP string's take point (the order)"),
        "f4p_dma": _prog("f4p_dma", x2_tests(gated=True), pins=PINS, fast=(20, 21),
                         note="DMA: the channels' order, bursts, TC at 0 / 1 / 2 waits"),
        "f4p_x5": _prog("f4p_x5", x4_tests((True,)), pins=PINS, fast=(20, 21, 28), gate=False,
                        note="explore: as f4p_x4 at a REP string's take point"),
        "f4p_x4": _prog("f4p_x4", x4_tests(), pins=PINS, fast=(20, 21, 28), gate=False,
                        note="explore: NMI, macro service, DMA, INTP1 held by a DMA burst"),
        "f4p_x1": _prog("f4p_x1", x1_tests(), pins=PINS, fast=(20, 21, 29, 30),
                        gate=False, note="explore: macro service against sources, ISPR, NMI, holds"),
        "f4p_x2": _prog("f4p_x2", x2_tests(), pins=PINS, fast=(20, 21), gate=False,
                        note="explore: DMA channel priority, bursts, TC with 0 / 1 waits"),
        "f4p_x3": _prog("f4p_x3", x3_tests(), pins=PINS, fast=(20, 21, 28), gate=False,
                        note="explore: NMI, macro service, DMA, INTP1 at one boundary"),
    }
    for p in progs.values():
        p.data.update(dma.pages())
        p.results += [(0xD000, 0x100), (dma.SRC, 0x100), (dma.DST, 0x100),
                      (dma.RES, 0x20 * len(p.tests))]
    return progs


def order(rec, prog):
    """Per test: the service order as tokens, from the write sequence: Mn a marker (cw n), MSc
    a macro-service transfer on channel c, Wxx / Rxx a DMA write at D0xxh / read at F0xxh, Vn a
    handler's entry (the stub's store of n)."""
    out, k = {}, None
    for a, d, f in rec["writes"]:
        if a == 0x8004:
            k = d
            continue
        if k is None or k >= len(prog.tests):
            continue
        b = d >> 8 if a & 1 else d & 0xFF
        tok = None
        base = dma.RES + 0x20 * k + 0x18
        if base <= a < base + 8:
            tok = f"M{a - base}"
        elif BUF <= a < BUF + 0x80:
            tok = f"MS{(a - BUF) >> 4}"
        elif 0xD000 <= a < 0xD080:
            tok = f"W{a & 0xFF:02X}"
        elif 0xF000 <= a < 0xF100:
            tok = f"R{a & 0xFF:02X}"
        elif a == 0x8002:
            tok = f"V{b}"
        if tok:
            out.setdefault(k, []).append(tok)
    return out


def show_order(name, backend, progs):
    rec = periph.load(name, backend)
    prog = progs[name]
    res = bytes.fromhex(rec["regions"][f"{dma.RES:05X}"])
    o = order(rec, prog)
    print(f"{name} ({backend}): passed {rec['passed']}")
    for k, t in enumerate(prog.tests):
        print(f"{k:2d} {t.name:12s} {' '.join(o.get(k, []))}")
        print(f"   {'':12s} res {res[0x20 * k:0x20 * k + 0x18].hex(' ')}")


def show_log(name, backend, progs):
    """The logging handler's entries: vector, pushed PC (by label), ISPR at entry."""
    from . import intr
    rec = periph.load(name, backend)
    prog = progs[name]
    _, entries, _ = intr.decode(rec)
    labels = intr.labels_of(prog)
    for e in entries:
        t = prog.tests[e["test"]].name if e["test"] < len(prog.tests) else "?"
        print(f"  {t:12s} v{e['vec']:<2d} d{e['depth']} pc={e['pc']:04X} [{intr.where(labels, e['pc'])}]"
              f" psw={e['psw']:04X} ispr={e['ispr']:02X} ex0={e['exic0']:02X} ex1={e['exic1']:02X}"
              f" tm0={e['tmic0']:02X}")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "gate", "show", "order", "log", "emit", "size"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--trace", action="store_true")
    a = p.parse_args()
    progs = programs()
    names = a.names or [n for n, prog in progs.items() if prog.gate]
    if a.action in ("socket", "sim"):
        dma._with_dma_reads()
        dma._ready_stim(0)
        dma._keep_trace(None if a.trace else ())
        periph.run_set(names, a.action, a.tag, progs)
    elif a.action == "gate":
        dma._gate_setup(progs)
        return 0 if periph.compare_gate(names, a.ref, a.cand, progs) else 1
    elif a.action == "show":
        for n in names:
            serial.show(n, a.ref + a.tag, progs)
    elif a.action == "log":
        for n in names:
            show_log(n, a.ref + a.tag, progs)
    elif a.action == "order":
        for n in names:
            show_order(n, a.ref + a.tag, progs)
    elif a.action == "size":
        for n in names:
            code, _, _ = progs[n].image()
            print(n, f"{len(code)} bytes, {len(progs[n].tests)} tests, "
                  f"{len((progs[n].stim or {}).get('entries', []))} entries")
    else:
        periph.emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
