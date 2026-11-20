"""WO30 v2: a sim-only assertion bench for the fetch's WTC field when PS moves without a flush.

`MOV PS, r16` (8E /1) loads PS and the core v2 queue is not redirected (rtl_vectors' "8E: MOV
PS,r/m (the queue not redirected)"): the next fetch is granted at the new PS with the old pfp,
in the tick after PS's load. With a WTC whose fields differ between the old and the new block,
that fetch must take the new block's field. The program runs at 0000:0100 (block 0) and loads PS
7F00h (the fetches then at 7F1xxh, block 3); the image at 7F100h is a copy of the one at 00100h,
so the run is the same whichever copy a byte came from (the second MOV PS reloads 7F00h).

No socket capture: the expectation is the measured rule itself (validation/v35s/wtc.py, f4_wtc_f:
a fetch takes the field of its own address's block), checked on every fetch row of the trace,
plus `+v35_chk` silent (the bus unit's grant against its address's field).

    PYTHONPATH=host/src:. python3 -m validation.v35s.wtc_ps [--binary PATH]

Exit status 0 when every case holds.
"""

from __future__ import annotations

import argparse
import os
import sys

CLK = 32                    # ticks per CPU clock (x_half 2, the reset fX/8)
FLAG_READ, FLAG_IO, FLAG_REFRESH, FLAG_STROBE = 1, 2, 4, 1 << 7
NEW_PS = 0x7F00


def program(wtc: int) -> bytes:
    code = bytes([
        0xB8, 0x00, 0xF0,                           # MOV AW, F000h
        0x8E, 0xD8,                                 # MOV DS0, AW
        0xC7, 0x06, 0xE8, 0xFF, wtc & 0xFF, wtc >> 8,   # MOV word [FFE8h], wtc (WTC)
        0xB8, NEW_PS & 0xFF, NEW_PS >> 8,           # MOV AW, 7F00h
        0x8E, 0xC8,                                 # MOV PS, AW: no flush
    ]) + bytes([0x90] * 24) + bytes([               # NOP sled (fetched at the new PS)
        0xBA, 0x00, 0xFF,                           # MOV DW, FF00h
        0xEE,                                       # OUT DW, AL (the run's end)
        0xF4,                                       # HALT
        0xEB, 0xFE,                                 # BR $
    ])
    return code


def field_waits(wtc: int, addr: int) -> int:
    f = (wtc >> (2 * min(addr >> 17, 6))) & 3
    return 2 if f == 3 else f


def run_case(wtc: int) -> tuple[bool, str]:
    from .secure import RES, SP0, run_bench
    code = program(wtc)
    reset = bytes([0xEA, 0x00, 0x01, 0x00, 0x00])        # JMP FAR 0000:0100
    segments = {0x00100: code, (NEW_PS << 4) + 0x100: code, 0xFFFF0: reset}
    pages = sorted({0x00, (NEW_PS << 4) >> 12, 0xFF, RES >> 12, (SP0 - 2) >> 12})   # (secure's run reads RES and the stack)
    r = run_bench(segments, pages, None, False, limit=200_000)
    bad, fetches, new_block = [], 0, 0
    store_seen = False
    for row in r["trace"]:
        f = row["flags"]
        if f & (FLAG_REFRESH | FLAG_IO) or not f & FLAG_STROBE or not f & FLAG_READ:
            continue
        a = row["address"]
        if not (0x100 <= a < 0x100 + len(code) + 8 or (NEW_PS << 4) <= a < (NEW_PS << 4) + 0x200):
            continue                                # the reset fetches (before the WTC store)
        waits = round((row["end"] - row["start"] - 1) / CLK) - 2
        if a >= NEW_PS << 4:
            new_block += 1
        # the fetches before the WTC store's effect run under the reset WTC (FFFFh: 2 waits);
        # judge the rows from the first one at the new PS on, and the block-0 rows after it
        if a >= NEW_PS << 4:
            store_seen = True
        if not store_seen:
            continue
        fetches += 1
        if waits != field_waits(wtc, a):
            bad.append(f"{a:05X} waits {waits} (field {field_waits(wtc, a)})")
    ok = r["passed"] and not r["chk"] and not bad and new_block > 0
    return ok, (f"WTC {wtc:04X}h: passed {r['passed']} fetches judged {fetches} "
                f"(at the new PS {new_block}) wrong {len(bad)} chk {len(r['chk'])}"
                + (f" first: {bad[0]}" if bad else "") + (f" {r['chk'][0]}" if r["chk"] else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--binary", help="another build of the v35 simulation (V35_SIM_BINARY)")
    args = ap.parse_args(argv)
    if args.binary:
        os.environ["V35_SIM_BINARY"] = args.binary
    ok_all = True
    for wtc in (0x0080, 0x00C0, 0x0002, 0xFF3F):
        ok, line = run_case(wtc)
        ok_all &= ok
        print(("PASS " if ok else "FAIL ") + line, flush=True)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
