"""WO30 v2 (WO49 form): a sim-only assertion bench for the fetch's WTC field when PS moves without a flush.

`MOV PS, r16` (8E /1) loads the EU's PS, and the fetch stream keeps its own segment until the next
flush (silicon, validation/v35s/rows339.py f5_wy_p / f5_wy_q: 24 of 24 windows continue at the old
linear addresses, a following short branch refills at the new segment; core v2's queue register
`fps` since work order 49). So between MOV PS and the next flush the EU's PS and the segment on the
address pins differ, and a fetch must take the WTC field of the block its own address (the pins')
is in, not the block the EU's PS names. After the flush the stream is at the new PS and its fetches
take that block's field.

The program runs at 0000:0100 (block 0), loads PS 7F00h (block 3: 7F1xxh), runs a NOP sled that is
still fetched at the old PS (block 0) and then BR $+2, the flush: the rest is fetched at 7F1xxh. The
image at 7F100h is a copy of the one at 00100h, so the run is the same whichever copy a byte came
from. Judged: every fetch of the sled from its ninth byte on (fetched after MOV PS and after the WTC
store has taken effect; the queue runs at most six bytes ahead), which must be at the old PS with
block 0's field ("under the new PS"), and every fetch at the new PS, with block 3's field. Before
work order 49 the core redirected the fetch to the new PS at MOV PS (the old form of this bench
judged those fetches); a core that picks a fetch's field by the EU's PS instead of the fetch's own
address fails the sled's rows; one that leaves the stream at the old PS past the flush fails the
"at the new PS" count.

No socket capture: the expectation is the measured rule itself (validation/v35s/wtc.py, f4_wtc_f:
a fetch takes the field of its own address's block), checked on every judged fetch row of the
trace, plus `+v35_chk` silent (the bus unit's grant against its address's field).

    PYTHONPATH=host/src:. python3 -m validation.v35s.wtc_ps [--binary PATH] [-v]

Exit status 0 when every case holds.
"""

from __future__ import annotations

import argparse
import os
import sys

CLK = 32                    # ticks per CPU clock (x_half 2, the reset fX/8)
FLAG_READ, FLAG_IO, FLAG_REFRESH, FLAG_STROBE = 1, 2, 4, 1 << 7
NEW_PS = 0x7F00
SLED = 24                   # NOPs between MOV PS and the flush (fetched at the old PS)


def program(wtc: int) -> bytes:
    code = bytes([
        0xB8, 0x00, 0xF0,                           # MOV AW, F000h
        0x8E, 0xD8,                                 # MOV DS0, AW
        0xC7, 0x06, 0xE8, 0xFF, wtc & 0xFF, wtc >> 8,   # MOV word [FFE8h], wtc (WTC)
        0xB8, NEW_PS & 0xFF, NEW_PS >> 8,           # MOV AW, 7F00h
        0x8E, 0xC8,                                 # MOV PS, AW: no flush (the stream keeps PS 0000h)
    ]) + bytes([0x90] * SLED) + bytes([             # NOP sled (fetched at the old PS, under the new PS)
        0xEB, 0x00,                                 # BR $+2: the flush; the stream from here at PS 7F00h
    ]) + bytes([0x90] * 8) + bytes([                # NOPs (fetched at the new PS)
        0xBA, 0x00, 0xFF,                           # MOV DW, FF00h
        0xEE,                                       # OUT DW, AL (the run's end)
        0xF4,                                       # HALT
        0xEB, 0xFE,                                 # BR $
    ])
    return code


SLED_AT = 0x100 + 16        # the sled's first byte (offset in either segment)


def field_waits(wtc: int, addr: int) -> int:
    f = (wtc >> (2 * min(addr >> 17, 6))) & 3
    return 2 if f == 3 else f


def run_case(wtc: int, verbose=False) -> tuple[bool, str]:
    from .secure import RES, SP0, run_bench
    code = program(wtc)
    reset = bytes([0xEA, 0x00, 0x01, 0x00, 0x00])        # JMP FAR 0000:0100
    segments = {0x00100: code, (NEW_PS << 4) + 0x100: code, 0xFFFF0: reset}
    pages = sorted({0x00, (NEW_PS << 4) >> 12, 0xFF, RES >> 12, (SP0 - 2) >> 12})   # (secure's run reads RES and the stack)
    r = run_bench(segments, pages, None, False, limit=200_000)
    bad, under, new_block = [], 0, 0
    flush_at = SLED_AT + SLED                       # BR $+2's offset
    for row in r["trace"]:
        f = row["flags"]
        if f & (FLAG_REFRESH | FLAG_IO) or not f & FLAG_STROBE or not f & FLAG_READ:
            continue
        a = row["address"]
        waits = round((row["end"] - row["start"] - 1) / CLK) - 2
        if (NEW_PS << 4) <= a < (NEW_PS << 4) + 0x200:
            new_block += 1                          # the stream at the new PS (behind the flush)
        elif SLED_AT + 8 <= a < 0x100 + len(code) + 8:
            under += 1                              # the old PS's stream under the new PS (to the flush and past it)
        else:
            continue                                # the reset fetches and the head (before the WTC store)
        if verbose:
            print(f"    {a:05X} start {row['start'] // CLK} waits {waits} field {field_waits(wtc, a)}")
        if waits != field_waits(wtc, a):
            bad.append(f"{a:05X} waits {waits} (field {field_waits(wtc, a)})")
    fetches = under + new_block
    ok = r["passed"] and not r["chk"] and not bad and under > 0 and new_block > 0
    return ok, (f"WTC {wtc:04X}h: passed {r['passed']} fetches judged {fetches} "
                f"(at the old PS under the new PS {under}, at the new PS {new_block}) wrong {len(bad)} "
                f"chk {len(r['chk'])}"
                + (f" first: {bad[0]}" if bad else "") + (f" {r['chk'][0]}" if r["chk"] else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--binary", help="another build of the v35 simulation (V35_SIM_BINARY)")
    ap.add_argument("-v", action="store_true", help="print every judged fetch")
    args = ap.parse_args(argv)
    if args.binary:
        os.environ["V35_SIM_BINARY"] = args.binary
    ok_all = True
    for wtc in (0x0080, 0x00C0, 0x0002, 0xFF3F):
        ok, line = run_case(wtc, args.v)
        ok_all &= ok
        print(("PASS " if ok else "FAIL ") + line, flush=True)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
