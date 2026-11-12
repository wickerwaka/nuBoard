"""F4 part B: the serial channels and macro service (docs/v35s-function-plan.md, stage F4).

Directed programs measured on the socketed uPD70337 and run unchanged on the core v2 RTL in
simulation, in validation/v35s/periph.py's frame (intr.py's Test, slots and handler; periph's
run, receipts, pin records and gate):

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.serial socket [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.serial sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.serial gate [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.serial show NAME [--ref socket]
    PYTHONPATH=host/src:. python3 -m validation.v35s.serial emit

Transmit is observed on the pin records (TxD0 / TxD1, bits 24 / 25: always visible); receive is
fed from the schedule's RxD streams (runner.load_stimulus). The programs poll the IC registers'
IF bits with the sources masked (MK 1), so they wait for an event whatever clock it lands on, and
record what they read in the result region RES (RES + 0x20 k for test k).

Receipts: validation/v35s/receipts/f4-<name>-<backend>.json (--tag adds a suffix).
"""

from __future__ import annotations

import argparse
import sys

from . import periph
from .intr import PSW_IE, ev, pulse, wait
from .periph import CLK, PTest, _prog
from .runner import REST_LEVELS, INPUTS

RES = 0xC000            # the programs' result region: 0x20 bytes per test
SFR = dict(periph.SFR, RxB0=0x60, TxB0=0x62, SRMS0=0x65, STMS0=0x66, SCM0=0x68, SCC0=0x69,
           BRG0=0x6A, SCE0=0x6B, SEIC0=0x6C, SRIC0=0x6D, STIC0=0x6E,
           RxB1=0x70, TxB1=0x72, SRMS1=0x75, STMS1=0x76, SCM1=0x78, SCC1=0x79,
           BRG1=0x7A, SCE1=0x7B, SEIC1=0x7C, SRIC1=0x7D, STIC1=0x7E,
           EMS0=0x44, EMS1=0x45, EMS2=0x46, TMMS0=0x94, TMMS1=0x95, TMMS2=0x96)
CTS_LOW = REST_LEVELS & ~(1 << INPUTS["CTS0"] | 1 << INPUTS["CTS1"])


def _o(name):
    return f"0FF{SFR[name]:02X}h"


def swr(name, val):
    return f"    DB 26h\n    MOV byte [{_o(name)}], {periph._h(val)}\n"


def rd(name, k, i, mask=None):
    """An SFR byte (AND mask) into RES + 0x20 k + i (AL clobbered)."""
    m = "" if mask is None else f"    AND AL, {periph._h(mask)}\n"
    return (f"    DB 26h\n    MOV AL, [{_o(name)}]\n{m}    DB 2Eh\n"
            f"    MOV [{periph._h(RES + 0x20 * k + i, 4)}], AL\n")


def poll(name, tag, n=3000, name2=None):
    """Wait (at most n iterations, ~20 clocks each) for IF (bit 7) of `name` (or of `name2`)."""
    t = f"{tag}_{{k}}"
    s = f"    PUSH CW\n    PUSH AW\n    MOV CW, {n}\npl_{t}:\n    DB 26h\n    MOV AL, [{_o(name)}]\n"
    if name2:
        s += f"    DB 26h\n    OR AL, [{_o(name2)}]\n"
    s += f"    TEST AL, 80h\n    BNZ pd_{t}\n    DBNZ pl_{t}\npd_{t}:\n    POP AW\n    POP CW\n"
    return s


def frame(byte, bits=8, parity=None, stop=1, stop_val=1, bad_parity=False):
    """One asynchronous frame as RxD levels: start, LSB-first data, parity ('even', 'odd',
    'zero', 'one'), stop bits (stop_val 0: a framing error)."""
    data = [(byte >> i) & 1 for i in range(bits)]
    out = [0] + data
    if parity is not None:
        p = {"even": sum(data) & 1, "odd": 1 - (sum(data) & 1), "zero": 0, "one": 1}[parity]
        out.append(p ^ int(bad_parity))
    return out + [stop_val] * stop + ([1] * (stop - 1) if stop_val == 0 else [])


def idle(n):
    return [1] * n


# ------------------------------------------------------------------ transmit
def tx_test(name, ch, scm, scc, brg, data, k_note="", end_wait=80, extra=""):
    c = str(ch)
    T = PTest(name, jitter=False, note=k_note)

    def code(k):
        s = (swr("STIC" + c, 0x47) + swr("SCM" + c, 0x00) + swr("SCC" + c, scc)
             + swr("BRG" + c, brg) + rd("STIC" + c, k, 0) + swr("SCM" + c, scm)
             + wait(2, "e") + rd("STIC" + c, k, 1) + swr("STIC" + c, 0x47))
        for i, b in enumerate(data):
            s += (swr("TxB" + c, b) + poll("STIC" + c, f"t{i}") + rd("STIC" + c, k, 2 + i)
                  + swr("STIC" + c, 0x47))
        s += wait(end_wait, "z") + extra + rd("SCE" + c, k, 12) + rd("SCM" + c, k, 13)
        s += rd("STIC" + c, k, 14) + swr("SCM" + c, 0x00)
        return s
    T.codef = code
    return T


def _fix(tests):
    """Resolve the tests' code generators (they need their own number for RES)."""
    for k, t in enumerate(tests):
        if hasattr(t, "codef"):
            t.code = t.codef(k)
    return tests


def stx_tests():
    T = [periph.init_test()]
    # channel 0, 8 data bits, no parity, 1 stop (SCM 89h), SCLK/2 x BRG 32: two bytes back to back
    T.append(tx_test("tx_8n1", 0, 0x89, 0x00, 32, [0xA3, 0x3C]))
    # 7 data bits, even parity, 2 stop bits (B5h)
    T.append(tx_test("tx_7e2", 0, 0xB5, 0x00, 32, [0xA3]))
    # 8 data bits, odd parity (A9h)
    T.append(tx_test("tx_8o1", 0, 0xA9, 0x00, 32, [0x81]))
    # the "0 parity" setting (99h)
    T.append(tx_test("tx_8z1", 0, 0x99, 0x00, 32, [0xFF]))
    # another prescale: SCLK/16 x BRG 5 (SCC 3)
    T.append(tx_test("tx_p3", 0, 0x89, 0x03, 5, [0x96]))
    # SCLK/4 x BRG 13 (SCC 1)
    T.append(tx_test("tx_p1", 0, 0x89, 0x01, 13, [0x69]))
    # channel 1, 8N1, SCLK/2 x 40
    T.append(tx_test("tx1_8n1", 1, 0x89, 0x00, 40, [0x5C, 0xC5]))
    # the transmitter disabled (TxRDY 0) a few bits into a character
    t = PTest("tx_dis", jitter=False)
    t.codef = lambda k: (swr("STIC0", 0x47) + swr("SCC0", 0) + swr("BRG0", 32) + swr("SCM0", 0x89)
                         + swr("TxB0", 0x0F) + wait(12, "a") + swr("SCM0", 0x09)
                         + wait(60, "b") + rd("STIC0", k, 0) + rd("SCE0", k, 1)
                         + swr("TxB0", 0x55) + wait(60, "c") + rd("STIC0", k, 2)
                         + swr("SCM0", 0x89) + wait(80, "d") + rd("STIC0", k, 3)
                         + swr("SCM0", 0x00))
    T.append(t)
    # CTS0 (rest low here): raised before a byte is written, lowered later; raised mid-character
    t = PTest("tx_cts", jitter=False,
              stim=[{"event": "E0", "delay": 100, "levels": {"CTS0": 1}},
                    {"event": "E1", "delay": 100, "levels": {"CTS0": 0}},
                    {"event": "E2", "delay": 6000, "levels": {"CTS0": 1}},
                    {"event": "E3", "delay": 100, "levels": {"CTS0": 0}}])
    t.codef = lambda k: (swr("STIC0", 0x47) + swr("SCC0", 0) + swr("BRG0", 32) + swr("SCM0", 0x89)
                         + wait(2, "a") + rd("STIC0", k, 0) + swr("STIC0", 0x47)
                         + ev("E0") + wait(4, "b") + swr("TxB0", 0xC3) + wait(60, "c")
                         + rd("STIC0", k, 1) + ev("E1") + poll("STIC0", "d") + rd("STIC0", k, 2)
                         + swr("STIC0", 0x47) + wait(60, "e")
                         + ev("E2") + swr("TxB0", 0x5A) + wait(4, "f") + swr("TxB0", 0xA5)
                         + wait(80, "g") + rd("STIC0", k, 3) + ev("E3") + wait(80, "h")
                         + rd("STIC0", k, 4) + swr("SCM0", 0x00))
    T.append(t)
    return _fix(T)


# ------------------------------------------------------------------ receive
BT0 = 64 * CLK          # channel 0: SCLK/2 x BRG 32 (if a bit is BRG x 2^(n+1) clocks)
BT1 = 96 * CLK          # channel 1: SCLK/16 x BRG 6


def rx_read(ch, k, i, tag):
    """Wait for SRIC or SEIC; then SRIC, SEIC, SCE, RxB, SCE again into RES + i...; clear both."""
    c = str(ch)
    return (poll("SRIC" + c, tag, name2="SEIC" + c) + wait(6, tag + "w")
            + rd("SRIC" + c, k, i) + rd("SEIC" + c, k, i + 1) + rd("SCE" + c, k, i + 2, 0x7F)
            + rd("RxB" + c, k, i + 3) + rd("SCE" + c, k, i + 4, 0x7F)
            + swr("SRIC" + c, 0x47) + swr("SEIC" + c, 0x47))


def srx_tests():
    T = [periph.init_test()]
    # channel 0 8N1 at 64 clocks a bit: 5A, A5; a framing error (33h, stop 0); 11h 22h 44h back
    # to back read only after all three (overrun)
    t = PTest("rx0", jitter=False, stim=[{"event": "E0", "delay": 200, "serial": [0], "levels": {}}])
    t.codef = lambda k: (swr("SRIC0", 0x47) + swr("SEIC0", 0x47) + swr("SCC0", 0) + swr("BRG0", 32)
                         + swr("SCM0", 0x49) + rd("SCE0", k, 30) + ev("E0")
                         + rx_read(0, k, 0, "a") + rx_read(0, k, 5, "b") + rx_read(0, k, 10, "c")
                         + poll("SRIC0", "d", name2="SEIC0") + wait(110, "dw")
                         + rd("SRIC0", k, 15) + rd("SEIC0", k, 16) + rd("SCE0", k, 17, 0x7F)
                         + rd("RxB0", k, 18) + rd("SCE0", k, 19, 0x7F) + rd("RxB0", k, 20)
                         + swr("SRIC0", 0x47) + swr("SEIC0", 0x47) + wait(40, "e")
                         + rd("SRIC0", k, 21) + rd("SCE0", k, 22)
                         + swr("SCM0", 0x00) + rd("SCE0", k, 31))
    T.append(t)
    # channel 1 at 96 clocks a bit: 8E1 5A good, 5B bad parity; 7O1 35h; 8 "0 parity" 81h with a 1
    t = PTest("rx1", jitter=False, stim=[{"event": "E0", "delay": 200, "serial": [1], "levels": {}}])
    t.codef = lambda k: (swr("SRIC1", 0x47) + swr("SEIC1", 0x47) + swr("SCC1", 3) + swr("BRG1", 6)
                         + swr("SCM1", 0x79) + ev("E0")
                         + rx_read(1, k, 0, "a") + rx_read(1, k, 5, "b")
                         + swr("SCM1", 0x61) + rx_read(1, k, 10, "c")
                         + swr("SCM1", 0x59) + rx_read(1, k, 15, "d")
                         + swr("SCM1", 0x00) + rd("SCE1", k, 31))
    T.append(t)
    return _fix(T)


RX0_BITS = (idle(8) + frame(0x5A) + frame(0xA5) + idle(30) + frame(0x33, stop_val=0) + idle(30)
            + frame(0x11) + frame(0x22) + frame(0x44) + idle(8))
RX1_BITS = (idle(8) + frame(0x5A, parity="even") + idle(30) + frame(0x5B, parity="even",
                                                                    bad_parity=True)
            + idle(40) + frame(0x35, bits=7, parity="odd") + idle(40)
            + frame(0x81, parity="one") + idle(8))


# ------------------------------------------------------------------ macro service
MSB = 0xD000            # the macro-service programs' memory buffers (0x40 bytes per test)
# the INTP0 edges land ~94 clocks after the event: inside the wait loop, after its PUSH (an edge
# right after the OUT put the transfer before or after that push by its clock: the first f4_ms)
MS_D = 3000


def chan(ch, msc, sfrp, schr, msp, mss=0):
    """A macro-service channel block at IDB:E00 + 8 ch (through DS1 = F000h)."""
    a = 0xFE00 + 8 * ch
    return (f"    DB 26h\n    MOV byte [{periph._h(a, 4)}], {periph._h(msc)}\n"
            f"    DB 26h\n    MOV byte [{periph._h(a + 1, 4)}], {periph._h(sfrp)}\n"
            f"    DB 26h\n    MOV byte [{periph._h(a + 2, 4)}], {periph._h(schr)}\n"
            f"    DB 26h\n    MOV byte [{periph._h(a + 3, 4)}], 00h\n"
            f"    DB 26h\n    MOV word [{periph._h(a + 4, 4)}], {periph._h(msp, 4)}\n"
            f"    DB 26h\n    MOV word [{periph._h(a + 6, 4)}], {periph._h(mss, 4)}\n")


def chan_rd(ch, k, i):
    """The channel block's 8 bytes into RES + 0x20 k + i."""
    s = ""
    for j in range(0, 8, 2):
        s += (f"    DB 26h\n    MOV AW, [{periph._h(0xFE00 + 8 * ch + j, 4)}]\n"
              f"    DB 2Eh\n    MOV [{periph._h(RES + 0x20 * k + i + j, 4)}], AW\n")
    return s


def cnt_rd(n, k, i):
    """The fast stub's count of vector n into RES + 0x20 k + i."""
    return (f"    DB 2Eh\n    MOV AL, [{periph._h(periph.COUNTS + n, 4)}]\n"
            f"    DB 2Eh\n    MOV [{periph._h(RES + 0x20 * k + i, 4)}], AL\n")


def cnt_clr(n):
    """The fast stub's count of vector n cleared (its count in the results then depends only on
    the events the test makes)."""
    return f"    DB 2Eh\n    MOV byte [{periph._h(periph.COUNTS + n, 4)}], 00h\n"


P0_ON = (swr("P0", 0x00) + periph.marker(periph.modes(t2=1)) + swr("PM0", 0x00)
         + periph.marker(periph.modes(t2=2)))
P0_OFF = swr("PM0", 0xFF) + periph.marker(periph.modes(t2=1)) + periph.marker(periph.modes())
TM_RUN = (periph.tm_stop() + periph.sfr_ww("MD0", 99) + periph.sfr_ww("TM0", 99))


def ms_tm(name, ch, msc, sfrp, schr, mode, psw=0x0002, pins=False, n_wait=320, tmic=0x27,
          pre_x="", note=""):
    """TM0 (interval, 600 clocks) requests macro service through TMIC0 (MS 1) on channel ch:
    TMMS0 = mode; the buffer MSB + 0x40 k."""
    t = PTest(name, jitter=False, psw=psw, note=note)

    def code(k):
        buf = MSB + 0x40 * k
        return {"pre": (TM_RUN + (P0_ON if pins else "") + pre_x
                        + chan(ch, msc, sfrp, schr, buf) + swr("TMMS0", mode)
                        + swr("TMIC0", tmic) + swr("TMC0", 0x80)),
                "code": (wait(n_wait, "w") + periph.tm_stop() + chan_rd(ch, k, 0)
                         + rd("TMIC0", k, 8) + rd("TMMS0", k, 9) + cnt_rd(28, k, 10)
                         + rd("P0", k, 11) + swr("TMIC0", 0x47) + (P0_OFF if pins else ""))}
    t.msf = code
    return t


def _fix_ms(tests):
    for k, t in enumerate(tests):
        if hasattr(t, "msf"):
            c = t.msf(k)
            t.pre, t.code = c["pre"], c["code"]
            if "post" in c:         # the whole test with IE as its PSW: the code, then the reads
                t.pre, t.code = "", c["pre"] + chan_rd(5, k, 0) + swr("EXIC0", 0x47) + swr("BRG1", 0)
        elif hasattr(t, "codef"):
            t.code = t.codef(k)
    return tests


def ms_tests(modes=(0, 1, 4)):
    T = [periph.init_test()]
    # memory -> P0 (8-bit, mode 0, DIR 0) on channel 0, 4 transfers (IE 0: the macro service
    # runs; the vectored request after the count stays pending)
    T.append(ms_tm("ms_p0", 0, 4, 0x00, 0x00, 0x00, pins=True))
    # MD1 (1234h) -> memory with mode 1 (16-bit?), channel 1, 3 transfers
    T.append(ms_tm("ms_w", 1, 3, 0x8A, 0x00, 0x31, pre_x=periph.sfr_ww("MD1", 0x1234)))
    # every MSM value, SFR -> memory, MD1's low byte (34h), SCHR 34h, channel 2, 3 transfers
    # (f4_ms: a reserved MSM value, 2, hung the CPU: the reserved ones are probed one per program
    # by msr_tests)
    for m in modes:
        T.append(ms_tm(f"ms_m{m}", 2, 3, 0x8A, 0x34, m << 5 | 0x10 | 2,
                       pre_x=periph.sfr_ww("MD1", 0x1234)))
    if modes != (0, 1, 4):
        return _fix_ms(T)
    # MK 1 with MS 1: is the transfer made?
    T.append(ms_tm("ms_mk", 2, 3, 0x8A, 0x00, 0x12, tmic=0x67, pre_x=periph.sfr_ww("MD1", 0x1234)))
    # INTP0 edges (EXIC0 MS 1, EMS0 ch 5, BRG1 5Ah -> memory), MSC 2, IE 0: EXIC0 after each
    t = PTest("ms_x2", jitter=False,
              stim=[pulse("E0", "INTP0", delay=MS_D), pulse("E1", "INTP0", delay=MS_D),
                    pulse("E2", "INTP0", delay=MS_D)])

    def c_x2(k):
        buf = MSB + 0x40 * k
        s = (swr("BRG1", 0x5A) + chan(5, 2, 0x7A, 0x00, buf) + swr("EMS0", 0x15)
             + swr("EXIC0", 0x27))
        for i, e in enumerate(("E0", "E1", "E2")):
            s += ev(e) + wait(30, f"w{i}") + rd("EXIC0", k, 8 + i) + rd("EMS0", k, 11 + i)
        return {"pre": "", "code": s + chan_rd(5, k, 0) + swr("EXIC0", 0x47) + swr("BRG1", 0)}
    t.msf = c_x2
    T.append(t)
    t = PTest("ms_x3", jitter=False, psw=PSW_IE,
              stim=[pulse("E0", "INTP0", delay=MS_D), pulse("E1", "INTP0", delay=MS_D),
                    pulse("E2", "INTP0", delay=MS_D)])

    def c_x3(k):
        buf = MSB + 0x40 * k
        s = (cnt_clr(24) + swr("BRG1", 0x3C) + chan(5, 2, 0x7A, 0x00, buf) + swr("EMS0", 0x15)
             + swr("EXIC0", 0x27))
        for i, e in enumerate(("E0", "E1", "E2")):
            s += ev(e) + wait(30, f"w{i}") + rd("EXIC0", k, 8 + i) + cnt_rd(24, k, 11 + i)
        return {"pre": s, "code": "", "post": ""}
    t.msf = c_x3
    T.append(t)
    # macro service in HALT (IE 0): TM0 -> P0 on channel 0, MSC 3; the channel read after the wake
    t = PTest("ms_halt", jitter=False)

    def c_halt(k):
        buf = MSB + 0x40 * k
        return {"pre": (TM_RUN + chan(0, 3, 0x7A, 0x00, buf) + swr("BRG1", 0x6B)
                        + swr("TMMS0", 0x10) + swr("TMIC0", 0x27) + swr("TMC0", 0x80)),
                "code": ("    HALT\n    NOP\n    NOP\n" + chan_rd(0, k, 0) + rd("TMIC0", k, 8)
                         + periph.tm_stop() + rd("TMIC0", k, 9) + swr("TMIC0", 0x47)
                         + swr("BRG1", 0))}
    t.msf = c_halt
    T.append(t)
    # serial receive -> memory with mode 4 (character search?), SCHR 0Dh, channel 3, MSC 8
    t = PTest("ms_srx", jitter=False, psw=PSW_IE,
              stim=[{"event": "E0", "delay": 200, "serial": [0], "levels": {}}])

    def c_srx(k):
        buf = MSB + 0x40 * k
        return {"pre": (cnt_clr(13) + swr("SRIC0", 0x47) + swr("SEIC0", 0x47) + swr("SCC0", 0)
                        + swr("BRG0", 32)
                        + chan(3, 8, 0x60, 0x0D, buf) + swr("SRMS0", 0x93) + swr("SCM0", 0x49)
                        + swr("SRIC0", 0x27)),
                "code": (ev("E0") + wait(400, "w") + chan_rd(3, k, 0) + rd("SRIC0", k, 8)
                         + rd("SRMS0", k, 9) + cnt_rd(13, k, 10) + rd("RxB0", k, 11)
                         + rd("SCE0", k, 12) + swr("SCM0", 0x00) + swr("SRIC0", 0x47))}
    t.msf = c_srx
    T.append(t)
    # memory -> TxB0 (mode 0, DIR 0), channel 4, 3 transfers, STIC0 MS 1
    t = PTest("ms_stx", jitter=False, psw=PSW_IE)

    def c_stx(k):
        buf = MSB + 0x40 * k
        return {"pre": (cnt_clr(14) + swr("STIC0", 0x47) + swr("SCC0", 0) + swr("BRG0", 32)
                        + chan(4, 3, 0x62, 0x00, buf) + swr("STMS0", 0x04) + swr("STIC0", 0x27)
                        + swr("SCM0", 0x89)),
                "code": (wait(300, "w") + chan_rd(4, k, 0) + rd("STIC0", k, 8)
                         + rd("STMS0", k, 9) + cnt_rd(14, k, 10)
                         + swr("SCM0", 0x00) + swr("STIC0", 0x47))}
    t.msf = c_stx
    T.append(t)
    return _fix_ms(T)


MS_RX0 = idle(8) + frame(0x41) + frame(0x42) + frame(0x0D) + frame(0x43) + frame(0x44) + idle(8)


def ms_data(tests):
    buf = bytearray()
    for k in range(len(tests)):
        buf += bytes(((0x11 * (j + 1)) & 0xFF) if j < 8 else (0x80 | j) for j in range(0x40))
    buf[0x40 * (len(tests) - 1):0x40 * (len(tests) - 1) + 3] = b"XYZ"
    return {MSB: bytes(buf)}


# ------------------------------------------------------------------ the I/O interface mode, more
R2_ON = (periph.marker(periph.modes(r2=1)) + swr("PM1", 0x9F) + swr("PMC1", 0x48)
         + periph.marker(periph.modes(r2=2)))
R2_OFF = swr("PMC1", 0x00) + swr("PM1", 0xFF) + periph.marker(periph.modes(r2=1)) + \
    periph.marker(periph.modes())
# the receive test claims R2 for /CTS0 (RSCK) and P13 only, P16 left an input (the first f4_sio:
# where PMC1 bit 6 is cleared after a reception, the RTL's SCK0 fall came before the bank's
# hand-over, the socket's not; not settled)
R2_RX = periph.marker(periph.modes(r2=1)) + swr("PMC1", 0x08) + periph.marker(periph.modes(r2=2))
R2_RXOFF = swr("PMC1", 0x00) + periph.marker(periph.modes(r2=1)) + periph.marker(periph.modes())
CK_P = 4096             # the scheduled receive clock's period on CTS0 (ticks; 128 clocks)


def sio_tests():
    T = [periph.init_test()]
    # transmit, I/O interface mode (SCM0 MD 00): TxB0 written with TxRDY, then the TSK bit;
    # SCK0 on P16 (PMC1 bit 6)
    t = PTest("io_tx", jitter=False)
    t.codef = lambda k: (swr("STIC0", 0x47) + swr("SCC0", 0) + swr("BRG0", 32) + R2_ON
                         + swr("SCM0", 0x80) + wait(2, "a") + rd("STIC0", k, 0) + swr("STIC0", 0x47)
                         + swr("TxB0", 0xA3) + wait(60, "b") + rd("STIC0", k, 1) + rd("SCM0", k, 2)
                         + swr("SCM0", 0x88) + wait(2, "c") + rd("SCM0", k, 3) + wait(60, "d")
                         + rd("STIC0", k, 4) + swr("STIC0", 0x47) + swr("TxB0", 0x5C)
                         + wait(60, "e") + rd("STIC0", k, 5) + swr("SCM0", 0x88) + wait(60, "f")
                         + rd("STIC0", k, 6) + rd("SCE0", k, 7) + swr("SCM0", 0x00) + R2_OFF)
    T.append(t)
    # receive, I/O interface mode, the internal clock (RSCK 1: out on CTS0), RxD0 low then high
    t = PTest("io_rxi", jitter=False,
              stim=[{"event": "E0", "delay": 100, "levels": {"RXD0": 0}},
                    {"event": "E1", "delay": 100, "levels": {"RXD0": 1}}])
    t.codef = lambda k: (swr("SRIC0", 0x47) + swr("SCC0", 0) + swr("BRG0", 32) + R2_RX
                         + ev("E0") + wait(4, "a") + swr("SCM0", 0x44) + wait(30, "b")
                         + rd("SRIC0", k, 0) + rd("SCE0", k, 2)
                         + swr("SCM0", 0x4C) + wait(60, "c") + rd("SRIC0", k, 3) + rd("RxB0", k, 4)
                         + rd("SCM0", k, 5) + swr("SRIC0", 0x47)
                         + ev("E1") + wait(4, "d") + swr("SCM0", 0x4C) + wait(60, "e")
                         + rd("SRIC0", k, 6) + rd("RxB0", k, 7) + rd("SCE0", k, 8)
                         + swr("SCM0", 0x00) + swr("SRIC0", 0x47) + R2_RXOFF)
    T.append(t)
    # receive, I/O interface mode, the external clock on CTS0 (RSCK 0): 8 scheduled rising edges
    # (a pulse each, 128 clocks apart) with RxD0 the stream (bit i across pulse i's low half)
    ents = [{"event": "E0", "delay": 100, "hold": CK_P // 2, "levels": {"CTS0": 0},
             "serial": [0]}]
    ents += [{"event": None, "delay": CK_P // 2 - 10, "hold": CK_P // 2, "levels": {"CTS0": 0}}
             for _ in range(7)]
    ents.append({"event": None, "delay": 1000, "levels": {"CTS0": 0}})
    t = PTest("io_rxe", jitter=False, stim=ents)
    t.codef = lambda k: (swr("SRIC0", 0x47) + swr("SCC0", 0) + swr("BRG0", 32)
                         + swr("SCM0", 0x40) + wait(4, "a") + ev("E0") + poll("SRIC0", "b")
                         + rd("SRIC0", k, 0) + rd("RxB0", k, 1) + rd("SCE0", k, 2)
                         + swr("SRIC0", 0x47) + wait(60, "c") + rd("SRIC0", k, 3)
                         + rd("RxB0", k, 4) + swr("SCM0", 0x00) + swr("SRIC0", 0x47))
    T.append(t)
    # asynchronous 8N2, two bytes back to back (the gap between them)
    T.append(tx_test("tx_8n2", 0, 0x8D, 0x00, 32, [0x00, 0xFF]))
    # the receiver's start bit: a quarter-bit low glitch on RxD1, then 77h
    t = PTest("rx_glitch", jitter=False,
              stim=[{"event": "E0", "delay": 200, "serial": [1], "levels": {}}])
    t.codef = lambda k: (swr("SRIC1", 0x47) + swr("SEIC1", 0x47) + swr("SCC1", 0) + swr("BRG1", 32)
                         + swr("SCM1", 0x49) + ev("E0") + rx_read(1, k, 0, "a")
                         + wait(60, "b") + rd("SRIC1", k, 5) + swr("SCM1", 0x00))
    T.append(t)
    return _fix(T)


def sio2_tests():
    """Measured only: what starts the I/O interface mode's internal receive clock (RxD0 low)."""
    T = [periph.init_test()]
    for name, scm, tx in (("io_ri_rd", 0x44, None), ("io_ri_tsk", 0x4C, None),
                          ("io_ri_tx", 0xC4, 0x00)):
        t = PTest(name, jitter=False)

        def c(k, scm=scm, tx=tx):
            s = (swr("SRIC0", 0x47) + swr("STIC0", 0x47) + swr("SCC0", 0) + swr("BRG0", 32) + R2_ON
                 + rd("RxB0", k, 0) + swr("SCM0", scm) + wait(30, "a") + rd("SRIC0", k, 1)
                 + rd("RxB0", k, 2))
            if tx is not None:
                s += swr("TxB0", tx)
            s += (wait(60, "b") + rd("SRIC0", k, 3) + rd("RxB0", k, 4) + rd("STIC0", k, 5)
                  + wait(60, "c") + rd("SRIC0", k, 6) + rd("RxB0", k, 7) + rd("SCM0", k, 8)
                  + swr("SCM0", 0x00) + R2_OFF)
            return s
        t.codef = c
        T.append(t)
    return _fix(T)


SIO_RX0 = [0, 1, 1, 0, 0, 1, 0, 1] + idle(4)            # A6h MSB first (or 65h LSB first)
SIO_RX1 = idle(32) + [0] + idle(120) + [b for b in frame(0x77) for _ in range(4)] + idle(32)


PINS_MS = ["P00", "P01", "P02", "P03", "P04", "P05", "P06", "P07", "TXD0"]


def programs():
    progs = {
        "f4_stx": _prog("f4_stx", stx_tests(), pins=["TXD0", "TXD1"],
                        note="serial transmit: framing, baud, CTS, TxRDY"),
        "f4_srx": _prog("f4_srx", srx_tests(), pins=["TXD0", "TXD1"],
                        note="serial receive: framing, errors, overrun"),
    }
    mt = ms_tests()
    progs["f4_ms"] = _prog("f4_ms", mt, pins=PINS_MS, fast=(13, 14, 24, 28, 29, 30, 31),
                           note="macro service: timer, serial, every mode")
    progs["f4_ms"].data.update(ms_data(mt))
    progs["f4_ms"].results.append((MSB, 0x40 * len(mt)))
    progs["f4_ms"].levels = CTS_LOW
    progs["f4_ms"].stim = dict(progs["f4_ms"].stim, rxd0={"bits": MS_RX0, "bit_time": BT0})
    for m in (2, 3, 5, 6, 7):
        mt = ms_tests((m,))
        progs[f"f4_msr{m}"] = _prog(f"f4_msr{m}", mt, pins=PINS_MS, fast=(13, 14, 24, 28, 29, 30, 31),
                                    gate=False, note=f"measured only: the reserved MSM value {m}")
        progs[f"f4_msr{m}"].data.update(ms_data(mt))
        progs[f"f4_msr{m}"].results.append((MSB, 0x40 * len(mt)))
    progs["f4_sio"] = _prog("f4_sio", sio_tests(), pins=["TXD0", "TXD1", "SCK0", "CTS0"],
                            note="serial: the I/O interface mode, 2 stop bits, a start glitch")
    progs["f4_sio"].levels = CTS_LOW
    progs["f4_sio"].stim = dict(progs["f4_sio"].stim, rxd0={"bits": SIO_RX0, "bit_time": CK_P},
                                rxd1={"bits": SIO_RX1, "bit_time": BT0 // 4})
    progs["f4_sio2"] = _prog("f4_sio2", sio2_tests(), pins=["TXD0", "SCK0", "CTS0"], gate=False,
                             note="measured only: the I/O interface mode's receive start")
    progs["f4_sio2"].levels = CTS_LOW & ~(1 << INPUTS["RXD0"])
    progs["f4_stx"].levels = CTS_LOW
    progs["f4_srx"].stim = dict(progs["f4_srx"].stim, rxd0={"bits": RX0_BITS, "bit_time": BT0},
                                rxd1={"bits": RX1_BITS, "bit_time": BT1})
    for p in progs.values():
        p.results.append((RES, 0x20 * len(p.tests)))
    return progs


def _keep_ticks():
    """periph.run_one with `wt` added: [tick, address, data] of every external write (the
    result stores give the ticks of the program's reads; SFR stores are internal cycles)."""
    from . import onchip
    seq, stash = onchip._write_sequence, {}

    def ws(rows):
        rows = list(rows)
        from .runner import FLAG_IO, FLAG_READ, FLAG_STROBE
        stash["wt"] = [[t["start"], t["address"], t["data"]] for t in rows
                       if t["flags"] & FLAG_STROBE and not t["flags"] & (FLAG_IO | FLAG_READ)]
        return seq(rows)
    onchip._write_sequence = ws
    one = periph.run_one

    def run_one(*a, **k):
        rec = one(*a, **k)
        rec["wt"] = stash.pop("wt", [])
        return rec
    periph.run_one = run_one


def _from_first_test():
    """periph.load with the pin records before the program's first test dropped: at a session's
    first program the socket's TxD pins rise at the run's start (from power-up; reset leaves them
    to the board's keepers, f4_stx against f4_sio), which is not the program's doing."""
    load = periph.load

    def ld(name, backend):
        rec = load(name, backend)
        if rec.get("tests"):
            t0 = rec["tests"][0][0]
            rec["pins"] = [p for p in rec["pins"] if p[0] >= t0]
        return rec
    periph.load = ld


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
        _keep_ticks()
        periph.run_set(names, a.action, a.tag, progs)
    elif a.action == "gate":
        _from_first_test()
        return 0 if periph.compare_gate(names, a.ref, a.cand, progs) else 1
    elif a.action == "show":
        for n in names:
            show(n, a.ref + a.tag, progs)
    elif a.action == "size":
        for n in names:
            code, _, _ = progs[n].image()
            print(n, f"{len(code)} bytes, {len(progs[n].tests)} tests")
    else:
        periph.emit(progs)
    return 0


def show(name, backend, progs):
    rec = periph.load(name, backend)
    prog = progs[name]
    print(f"{name} ({backend}): passed {rec['passed']} status {rec['status']:04x} pins {len(rec['pins'])}")
    res = bytes.fromhex(rec["regions"][f"{RES:05X}"])
    for k, t in enumerate(prog.tests):
        print(f"{k:2d} {t.name:10s} " + res[0x20 * k:0x20 * k + 0x20].hex(" "))
        if f"{MSB:05X}" in rec["regions"]:
            mb = bytes.fromhex(rec["regions"][f"{MSB:05X}"])
            print(f"   {'buf':10s} " + mb[0x40 * k:0x40 * k + 0x20].hex(" "))
    st = {}
    for tk, v, kk in rec["stubs"]:
        st.setdefault(kk, []).append(f"v{v}@{tk // CLK}")
    for kk, v in st.items():
        print(f"   stubs test {kk}: " + " ".join(v[:12]) + (f" ... ({len(v)})" if len(v) > 12 else ""))
    print(f"   markers {rec['markers'][-6:] if isinstance(rec['markers'], list) else rec['markers']}"
          f" last {rec['last_marker']}")
    if rec["pins"]:
        t0 = rec["pins"][0][0]
        last = t0
        out = []
        for tk, v in rec["pins"]:
            out.append((f"{(v >> 24) & 3:02b}" if not v & 0xFFFFFF else f"{v:08X}")
                       + f"@{(tk - t0) / CLK:g}(+{(tk - last) / CLK:g})")
            last = tk
        print("   pins (TxD1 TxD0): " + " ".join(out))


if __name__ == "__main__":
    sys.exit(main())
