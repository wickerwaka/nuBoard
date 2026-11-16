"""Round 6: the rules read for OUT imm8 and for what follows an EU bus cycle (model_e6.py),
tested where they were not read from. Ports written: 22h / 23h (20h, 21h the markers); read: 40h.

ga  the fetch that gives way to a boundary on the clock after an EU cycle: XCH AW,BW in place
    of NOP (the same four words), and CBW (the boundary a clock earlier, on the cycle's last)
gb  OUT imm8 right after an EU cycle (a second OUT imm8, after PUSH), and as the marker behind
    a pending fetch chain: its lead and its request word against the cycle before it
gc  PUSH and IN imm8 behind the same chains: which instructions' words wait for the bus unit's
    setup slot (OUT DW's first and request words do) and which for the pin cycle
gd  the led opcode's boundary against a back-to-back fetch at four held (read from MOV r16,imm16
    then OUT imm8 at an even address, w0 only): other alignments, IN imm8, OUT imm8,AW
ge  OUT DW,AL behind other pending chains (two MOV r,r; after PUSH)
gf  the long shift's fourth word after a memory EU cycle and behind MOV r,r
"""

from __future__ import annotations

from .gen import INC, M1I, M1P, NOP, RI, RI8, RR, SLOW, q

OUT22 = bytes([0xE6, 0x22])
OUT23 = bytes([0xE6, 0x23])
OUTW22 = bytes([0xE7, 0x22])
IN40 = bytes([0xE4, 0x40])
XCH = bytes([0x93])
CBW = bytes([0x98])
PUSH = bytes([0x50])


def seq(*codes):
    return [q(c, "g") for c in codes]


def round6():
    v = []
    v.append(("ga-x", seq(OUT22, XCH)))
    v.append(("ga-xs", seq(OUT22, XCH, SLOW)))
    v.append(("ga-cn", seq(OUT22, CBW, NOP)))
    v.append(("ga-cs", seq(OUT22, CBW, SLOW)))
    v.append(("ga-ci", seq(OUT22, CBW, INC)))

    v.append(("gb-0", seq(OUT22, OUT23)))
    v.append(("gb-n", seq(OUT22, NOP, OUT23)))
    v.append(("gb-i", seq(OUT22, INC, OUT23)))
    v.append(("gb-ii", seq(OUT22, INC, INC, OUT23)))
    v.append(("gb-r", seq(OUT22, RR, OUT23)))
    v.append(("gb-c", seq(OUT22, CBW, OUT23)))
    v.append(("gb-p", seq(PUSH, OUT23)))
    v.append(("gb-pi", seq(PUSH, INC, OUT23)))
    v.append(("gb-pn", seq(PUSH, NOP, OUT23)))
    v.append(("gb-0s", seq(OUT22, OUT23, SLOW)))
    v.append(("gb-0m", (seq(OUT22), M1I)))
    v.append(("gb-nm", (seq(OUT22, NOP), M1I)))
    v.append(("gb-rm", (seq(OUT22, RR), M1I)))
    v.append(("gb-irm", (seq(OUT22, INC, RR), M1I)))

    v.append(("gc-0p", (seq(OUT22), M1P)))
    v.append(("gc-ip", (seq(OUT22, INC), M1P)))
    v.append(("gc-np", (seq(OUT22, NOP), M1P)))
    v.append(("gc-rp", (seq(OUT22, RR), M1P)))
    v.append(("gc-irp", (seq(OUT22, INC, RR), M1P)))
    v.append(("gc-in", seq(OUT22, IN40)))
    v.append(("gc-iin", seq(OUT22, INC, IN40)))
    v.append(("gc-nin", seq(OUT22, NOP, IN40)))
    v.append(("gc-rin", seq(OUT22, RR, IN40)))

    v.append(("gd-in", seq(RI, IN40)))
    v.append(("gd-ow", seq(RI, OUTW22)))
    v.append(("gd-io", seq(INC, RI, OUT22)))
    v.append(("gd-iio", seq(INC, INC, RI, OUT22)))
    v.append(("gd-rio", seq(RI, RI, OUT22)))
    v.append(("gd-m8", seq(RI8, OUT22)))

    v.append(("ge-rr2", seq(OUT22, RR, RR)))
    v.append(("ge-rrn", seq(OUT22, RR, NOP)))
    v.append(("ge-rri", seq(OUT22, RR, INC)))
    v.append(("ge-prr", seq(PUSH, RR)))
    v.append(("ge-prr2", seq(PUSH, RR, RR)))
    v.append(("ge-pn", seq(PUSH, NOP)))
    v.append(("ge-pnn", seq(PUSH, NOP, NOP)))
    v.append(("ge-pc", seq(PUSH, CBW)))

    v.append(("gf-p", seq(PUSH, SLOW)))
    v.append(("gf-pi", seq(PUSH, INC, SLOW)))
    v.append(("gf-pn", seq(PUSH, NOP, SLOW)))
    v.append(("gf-pr", seq(PUSH, RR, SLOW)))
    v.append(("gf-or", seq(OUT22, RR, SLOW)))
    v.append(("gf-oc", seq(OUT22, CBW, SLOW)))
    return v


ROUNDS = {"r6": round6}
