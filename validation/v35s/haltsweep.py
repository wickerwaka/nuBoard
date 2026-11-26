"""(WO50, item 8) HALT's loop against a request named around HALT's pop: a simulation-only sweep (no socket
receipts, not a gate set). Every test must leave HALT and reach its end: a request landing so that the loop's
take test says yes while the dispatch takes nothing would hold the core at `halt redisp` for ever (the
prefetcher is stopped in HALT): build/overseer/int-design2/DESIGN-INT2.md section 5.1.

    PYTHONPATH=host/src:. python3 -m validation.v35s.haltsweep sim [NAME ...] [--tag=-x]
    PYTHONPATH=host/src:. python3 -m validation.v35s.haltsweep check [NAME ...] [--tag=-x]

check: per program, every test's end marker written (the test numbers reached, the 55h marker of each test
behind its HALT) and the run passed; prints one line a program and the tests that did not complete; exit 1 if
any did not.

    f5_hs_tmSx        TMIC0's IF stored (unmasked, level 7) through DS1, then a sled (n = 0 .. 16 NOPs; S = p, or m:
                      a two-byte MOV in front, the other parity), HALT; x = 1 IE 1 (the take, vector 28), 0 IE 0
    f5_hs_ipNx        INTP0's edge at a swept delay behind the event's OUT (16-tick steps, 24 a program, four
                      programs: 0 .. 1,535 ticks), six NOPs and HALT behind the OUT; x = 1 IE 1, 0 IE 0
    f5_hs_dmNNx       (twelve programs of eight) a DMA request (channel 1, I/O to memory, one transfer, DIC1 unmasked) by DMARQ1's edge at
                      the same swept delays; the transfer's end raises DIC1, which takes (IE 1) or releases (IE 0)
"""

from __future__ import annotations

import argparse
import sys

from . import dma, periph, serial
from .intr import PSW_IE, ev
from .periph import PTest, _prog
from .serial import rd, swr

PSW0 = 0x0002
STEP, PER, PARTS = 16, 24, 4    # ticks a step (half a clock), tests a program (the result area holds 29), programs
SLED_NOPS = 6


# A backup wake: TM1 at /128 with MD1 24 (about 3,000 clocks), TMIC1 unmasked at level 7 (vector 29). With IE 1 a
# request taken before HALT executes leaves the HALT with nothing pending (silicon would stay there too); the
# backup ends that HALT. It cannot end the fault this sweep looks for: a word that waits for a fetch in HALT
# is not released by a request.
BACKUP = (periph.sfr_ww("MD1", 24) + periph.sfr_ww("TM1", 24) + swr("TMIC1", 0x07) + swr("TMC1", 0xC0))
UNDO = swr("TMC1", 0x00) + swr("TMIC1", 0x47) + swr("TMIC2", 0x47)


def _end(k, vec):
    return UNDO + dma.cw(k, 0, 0x55) + serial.cnt_rd(vec, k, 1)


def tm_tests(ie, pre):
    T = [periph.init_test()]
    if True:
        for n in range(0, 17):
            t = PTest(f"tm_{'m' if pre else 'p'}{n}", jitter=False, psw=PSW_IE if ie else PSW0)
            t.codef = (lambda pre, n: lambda k: (serial.cnt_clr(28) + BACKUP + swr("TMIC0", 0x87) + pre
                                                + "    NOP\n" * n + "    HALT\n    NOP\n    NOP\n"
                                                + _end(k, 28) + swr("TMIC0", 0x47)))(pre, n)
            T.append(t)
    return serial._fix(T)


def ip_tests(ie, part):
    T = [periph.init_test()]
    for j in range(PER):
        d = STEP * (PER * part + j)
        t = PTest(f"ip_d{d}", jitter=False, psw=PSW_IE if ie else PSW0,
                  stim=[{"event": "E0", "delay": d, "hold": 600, "levels": {"INTP0": 0}}])
        t.codef = lambda k: (serial.cnt_clr(24) + BACKUP + swr("EXIC0", 0x07) + ev("E0") + "    NOP\n" * SLED_NOPS
                             + "    HALT\n    NOP\n    NOP\n" + _end(k, 24) + swr("EXIC0", 0x47))
        T.append(t)
    return serial._fix(T)


DM_PER, DM_PARTS = 8, 12      # the DMA programs are long (the trace is read in windows): eight tests a program


def dm_tests(ie, part):
    T = [periph.init_test()]
    for j in range(DM_PER):
        d = STEP * (DM_PER * part + j)
        t = dma.mask_rng(PTest(f"dm_d{d}", jitter=False, psw=PSW_IE if ie else PSW0,
                               stim=[dma.rq("E0", 1, delay=d, hold=400)]), dma.DD + 0xB0, 2)
        t.codef = lambda k: (serial.cnt_clr(21) + BACKUP + swr("DIC1", 0x07) + dma.ON0
                             + dma.blk_w(1, 0x00B0, 0x00B0, 0x0F, 0x0D, 1)
                             + swr("DMAC1", 0x11) + swr("DMAM1", 0xA8) + ev("E0") + "    NOP\n" * SLED_NOPS
                             + "    HALT\n    NOP\n    NOP\n" + _end(k, 21) + rd("DMAM1", k, 8)
                             + swr("DMAM1", 0x00) + swr("DIC1", 0x47) + dma.OFF0)
        T.append(t)
    return serial._fix(T)


def programs():
    progs = {}
    for ie in (1, 0):
        for sh, pre in (("p", ""), ("m", "    MOV AL, AL\n")):
            progs[f"f5_hs_tm{sh}{ie}"] = _prog(f"f5_hs_tm{sh}{ie}", tm_tests(ie, pre), fast=(28, 29), gate=False,
                                               note=f"TMIC0's IF stored, a sled, HALT; IE {ie}")
        for part in range(PARTS):
            progs[f"f5_hs_ip{part}{ie}"] = _prog(f"f5_hs_ip{part}{ie}", ip_tests(ie, part), fast=(24, 29), gate=False,
                                                 note=f"INTP0's edge swept against HALT's pop; IE {ie}")
        for part in range(DM_PARTS):
            p = _prog(f"f5_hs_dm{part:02d}{ie}", dm_tests(ie, part), pins=dma.PINS, fast=(21, 29), gate=False,
                      note=f"a DMA request swept against HALT's pop; IE {ie}")
            p.data.update(dma.pages())
            progs[p.name] = p
    for p in progs.values():
        p.results.append((serial.RES, 0x20 * len(p.tests)))
    return progs


def check(names, backend, progs):
    """A program is complete when its run ends inside the limit (no timeout: the program's end reached, so no
    test stood in HALT for good). Each test's end marker (55h at RES + 20h k + 18h) is listed as well, from the
    write sequence or the result region (a long program's trace is read in windows and a DMA program's windows
    can differ in timing, so the markers are a cross-check, not the test)."""
    ok = True
    for n in names:
        rec = periph.load(n, backend)
        nt = len(progs[n].tests)
        reg = bytes.fromhex(rec["regions"][f"{serial.RES:05X}"])
        wr = {w[0] for w in rec["writes"] if w[1] == 0x55}
        miss = [progs[n].tests[k].name for k in range(1, nt)
                if reg[0x20 * k + 0x18] != 0x55 and serial.RES + 0x20 * k + 0x18 not in wr]
        good = not rec["timeout"]
        ok &= good
        print(f"{n}: {'COMPLETE' if good else 'STUCK'} timeout={rec['timeout']} markers {nt - 1 - len(miss)} of "
              f"{nt - 1}" + (f" (not seen: {' '.join(miss)})" if miss else ""))
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("sim", "check"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    a = p.parse_args()
    progs = programs()
    names = a.names or list(progs)
    if a.action == "sim":
        dma._with_dma_reads()
        periph.run_set(names, "sim", a.tag, progs)
        return 0
    return 0 if check(names, "sim" + a.tag, progs) else 1


if __name__ == "__main__":
    sys.exit(main())
