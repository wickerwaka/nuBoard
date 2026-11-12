"""F3 part B: the register banks and the instructions around them (docs/v35s-function-plan.md,
stage F3; fpga/v35s/core/v35/README.md "F3 (part B)").

Directed programs measured on the socketed uPD70337 and run unchanged on the core v2 RTL in
simulation, in validation/v35s/intr.py's pattern (its runner, receipts and gate):

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.banks socket [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.banks sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.banks gate [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.banks show NAME [--ref socket]
    PYTHONPATH=host/src:. python3 -m validation.v35s.banks emit

f3_bins (the bank instructions BRKCS, TSKSW, MOVSPA, MOVSPB, RETRBI) and f3_bsw (the
bank-switch entry: ENCS = 1) run in bank 7 and reload banks 0-6 from a table (TABLE) at each
case; a case's code takes a snapshot (`snap`: the live AW CW IX IY BW DW BP DS0 DS1 PSW SS SP,
ISPR and six IC registers, then the eight banks copied from IDB:E00, 0120h bytes at SNAP +
120h x n) where it lands and again after its return. Vectored entries (the catch: every vector
0-63 to intr.py's stubs and logging handler) are logged as in intr.py. f3_brkn (BRKN) and f3_int
(INT / INTAK, the R2 bank handed to the CPU through FF10h) are intr.py Test programs; f3_brks
(BRKS: the secure mode entered, an NMI scheduled during BRKS ends it) is measured only and run
on the socket on its own. Receipts validation/v35s/receipts/f3-<name>-<backend>.json.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys

from . import intr
from .intr import (ABS, CHAIN, HANDLER, LOG, PSW0, PSW_IE, STUBS, Test, _h, ev, level, pulse,
                   sfr_rd, sfr_wr, wait, WAIT)
from .onchip import Program

TABLE = 0x6000          # banks 0-6 as each case starts (0E0h bytes)
SNAP = 0x4000           # snapshots, 120h bytes each
NSNAP = 20
SP7 = 0x7EF0            # bank 7's stack: SS 0001h, SP 7EF0h (linear 7F00h)
FFE0 = 0xFFE0           # DS0 = FFE0h: the internal RAM at 0000h-00FFh, the SFRs at 0100h-01FFh

SLOT = {"VPC": 0x02, "PSWS": 0x04, "PCS": 0x06, "DS0": 0x08, "SS": 0x0A, "PS": 0x0C,
        "DS1": 0x0E, "IY": 0x10, "IX": 0x12, "BP": 0x14, "SP": 0x16, "BW": 0x18, "DW": 0x1A,
        "CW": 0x1C, "AW": 0x1E}
# the snapshot's extras (at +100h)
EXTRA = {"AW": 0, "CW": 2, "IX": 4, "IY": 6, "DS0": 8, "DS1": 10, "PSW": 12, "SS": 14, "SP": 16,
         "BW": 26, "DW": 28, "BP": 30}
EXTRA_B = {"ISPR": (18, 0x1FC), "EXIC0": (19, 0x14C), "EXIC1": (20, 0x14D), "EXIC2": (21, 0x14E),
           "TMIC0": (22, 0x19C), "TBIC": (23, 0x1EC), "SEIC0": (24, 0x16C)}


def bank_table() -> bytes:
    """Banks 0-6: VPC and PC save at `lost` (patched by the program), the PSW save 8002h + RB n,
    DS0 0A00h, SS n, PS 0, DS1 0B00h, SP 7000h + 100h n, the word registers n:slot."""
    out = bytearray()
    for n in range(7):
        b = bytearray(32)

        def put(slot, v):
            b[slot:slot + 2] = (v & 0xFFFF).to_bytes(2, "little")
        put(0, 0x1111 * n)
        put(SLOT["PSWS"], 0x8002 | n << 12)
        put(SLOT["DS0"], 0x0A00)
        put(SLOT["SS"], n)
        put(SLOT["PS"], 0)
        put(SLOT["DS1"], 0x0B00)
        put(SLOT["SP"], 0x7000 + 0x100 * n)
        for r in ("IY", "IX", "BP", "BW", "DW", "CW", "AW"):
            put(SLOT[r], n << 8 | SLOT[r])
        out += b
    return bytes(out)


def cs(ins):
    return "    DB 2Eh\n    " + ins + "\n"


def snap(n, c=0):
    """The snapshot n (code running with PS = c): the registers, ISPR and IC bytes, the banks.
    Every register and the PSW restored (the copy runs through DS0 DS1 CW IX IY AW)."""
    if n >= NSNAP:
        raise ValueError("snapshot number")
    D = SNAP + 0x120 * n
    E = D + 0x100 - 16 * c

    def a(off):
        return _h(E + off, 4)
    L = [f"; snapshot {n}\n"]
    for r in ("AW", "CW", "IX", "IY", "BW", "DW", "BP"):
        L.append(cs(f"MOV [{a(EXTRA[r])}], {r}"))
    L.append("    MOV AW, DS0\n" + cs(f"MOV [{a(8)}], AW"))
    L.append("    MOV AW, DS1\n" + cs(f"MOV [{a(10)}], AW"))
    L.append("    PUSH PSW\n    POP AW\n" + cs(f"MOV [{a(12)}], AW"))
    L.append("    MOV AW, SS\n" + cs(f"MOV [{a(14)}], AW"))
    L.append(cs(f"MOV [{a(16)}], SP"))
    L.append(f"    MOV AW, {_h(FFE0, 4)}\n    MOV DS0, AW\n")
    for nm, (off, sfr) in EXTRA_B.items():
        L.append(f"    MOV AL, [{_h(sfr, 4)}]\n" + cs(f"MOV [{a(off)}], AL"))
    L.append(cs(f"MOV byte [{a(25)}], {_h(n)}"))
    L.append(f"""\
    XOR AW, AW
    MOV DS1, AW
    XOR IX, IX
    MOV IY, {_h(D, 4)}
    MOV CW, 0080h
    CLR1 DIR
    REP
    MOVBKW
""")
    L.append(cs(f"MOV AW, [{a(8)}]") + "    MOV DS0, AW\n")
    L.append(cs(f"MOV AW, [{a(10)}]") + "    MOV DS1, AW\n")
    for r in ("CW", "IX", "IY"):
        L.append(cs(f"MOV {r}, [{a(EXTRA[r])}]"))
    L.append(cs(f"PUSH word [{a(12)}]") + "    POP PSW\n")
    L.append(cs(f"MOV AW, [{a(0)}]"))
    return "".join(L)


def bank_slot(n, slot):
    """The offset (DS0 = FFE0h) of bank n's slot."""
    return _h(0x20 * n + SLOT[slot], 4)


def movw(addr, value):
    """MOV word [addr], value (DS0); a string value is a label, optionally "label-N" (resolved
    after assembly: the assembler takes no label immediates)."""
    if not isinstance(value, str):
        return f"    MOV word [{_h(addr, 4)}], {_h(value, 4)}\n"
    return (f"    DB 0C7h, 06h, {_h(addr & 0xFF)}, {_h(addr >> 8)}\n"
            f"    DW @{value.replace(' ', '')}@\n")


def set_slot(n, slot, value):
    return movw(0x20 * n + SLOT[slot], value)


def resolve(src):
    """The @label[-N]@ words of `src` replaced by their values (two assemblies)."""
    import re
    pat = re.compile(r"@([A-Za-z_][A-Za-z0-9_]*)(?:-(\w+))?@")
    dummy = pat.sub("0", src)
    labels = intr.labels_of(type("P", (), {"source": dummy})())

    def val(m):
        b = m.group(2)
        sub = 0 if b is None else int(b) if b.isdigit() else labels[b]
        return _h((labels[m.group(1)] - sub) & 0xFFFF, 4)
    return pat.sub(val, src)


_JN = [0]


def jmp(label):
    """A near BR (E9 rel16) to `label` (the assembler's BR is short only)."""
    _JN[0] += 1
    return f"    DB 0E9h\n    DW @{label}-jn{_JN[0]}@\njn{_JN[0]}:\n"


def case_head(k, title):
    """Banks 0-6 from the table, bank 7's slots and registers, DS0 = FFE0h (IE 0)."""
    return f"""\
; ---- case {k}: {title}
case{k}:
    DI
    XOR AW, AW
    MOV DS0, AW
    MOV AW, {_h(FFE0, 4)}
    MOV DS1, AW
    MOV IX, {_h(TABLE, 4)}
    XOR IY, IY
    MOV CW, 0070h
    CLR1 DIR
    REP
    MOVBKW
    MOV AW, {_h(FFE0, 4)}
    MOV DS0, AW
    MOV AW, 0B00h
    MOV DS1, AW
    MOV AW, 0001h
    MOV SS, AW
    MOV SP, {_h(SP7, 4)}
    MOV word [00E0h], 7777h
""" + movw(0xE2, "lost") + movw(0xE4, 0xF002) + movw(0xE6, "lost") + "".join(
        movw(0x20 * n + 2, "lost") + movw(0x20 * n + 6, "lost") for n in range(7)) + """\
    MOV CW, 7701h
    MOV DW, 7702h
    MOV BW, 7703h
    MOV BP, 7705h
    MOV IX, 7706h
    MOV IY, 7707h
    MOV AW, 7700h
"""


def set_psw(v):
    return f"    PUSH AW\n    MOV AW, {_h(v, 4)}\n    PUSH AW\n    POP PSW\n    POP AW\n"


PROLOGUE = """\
    DI
    XOR AW, AW
    MOV SS, AW
    MOV SP, 7F00h
    DB 2Eh
    MOV word [8000h], 0
    DB 2Eh
    MOV word [8004h], 0FFFFh
    DB 2Eh, 0C7h, 06h, 06h, 80h
    DW actf
    DB 2Eh
    MOV byte [8008h], 0
    BR main
actf:
    FINT
    RET
lost:
    MOV DW, 0FF02h
    OUT DW, AL
    HALT
    BR lost
main:
"""

EPILOGUE = """\
    NOP
    MOV DW, 0FF00h
    OUT DW, AL
    HALT
done:
    BR done
"""

BRKCS = {"AW": "0F8h", "CW": "0F9h", "DW": "0FAh", "BW": "0FBh", "SP": "0FCh", "BP": "0FDh",
         "IX": "0FEh", "IY": "0FFh"}


def brkcs(r):
    return f"    DB 0Fh, 2Dh, {BRKCS[r]}\n"


def tsksw(r):
    return f"    DB 0Fh, 94h, {BRKCS[r]}\n"


def movspb(r):
    return f"    DB 0Fh, 95h, {BRKCS[r]}\n"


MOVSPA = "    DB 0Fh, 25h\n"
RETRBI = "    DB 0Fh, 91h\n"
FINT = "    DB 0Fh, 92h\n"
PSW_T = 0x0ECF          # IE DIR V S Z F0 P BRKI CY set, BRK clear


def vectors64() -> dict:
    """intr.py's vector area for vectors 0-63 (stubs at 3000h + 12n, the logging handler)."""
    area = intr.vector_area()
    ivt = bytearray(area[0x0000])
    stubs = bytearray(area[STUBS])
    for n in range(32, 64):
        at = STUBS + 12 * n
        rel = HANDLER - (at + 9)
        ivt += at.to_bytes(2, "little") + b"\x00\x00"
        stubs += bytes([0x2E, 0xC6, 0x06, 0x02, 0x80, n, 0xE9, rel & 0xFF, (rel >> 8) & 0xFF,
                        0x90, 0x90, 0x90])
    area[0x0000] = bytes(ivt)
    area[STUBS] = bytes(stubs)
    return area


class Case:
    def __init__(self, name, src, snaps, note=""):
        self.name = name
        self.src = src
        self.snaps = snaps          # the snapshot numbers and what each shows
        self.note = note


def bank_program(name, cases, note="", gate=True):
    src = resolve(PROLOGUE + "".join(c.src for c in cases) + EPILOGUE)
    data = vectors64()
    data[TABLE] = bank_table()
    data[0xA000] = intr.pattern(0xA000)
    nsnap = 1 + max(s for c in cases for s in c.snaps)
    prog = Program(name, src, data=data,
                   results=[(LOG, 0x10), (LOG + 0x100, 0x400), (SNAP, 0x120 * nsnap)],
                   gate=gate, note=note, extra_pages=(0x7,))
    prog.cases = cases
    prog.tests = []
    prog.levels = None
    prog.stim = None
    from .runner import REST_LEVELS
    prog.levels = REST_LEVELS
    return prog


# ------------------------------------------------------------------ f3_bins
def all_slots(slot, label):
    """The slot of every bank (0-7) set to a label (wherever the instruction lands)."""
    return "".join(set_slot(n, slot, label) for n in range(8))


def bins_cases():
    C = []
    k = 0
    # BRKCS AW = 3: bank 3, then RETRBI
    C.append(Case("brkcs_aw", case_head(k, "BRKCS AW (3), RETRBI")
                  + all_slots("VPC", f"t{k}") + "    MOV AW, 0003h\n" + set_psw(PSW_T)
                  + brkcs("AW") + f"r{k}:\n" + snap(1) + jmp(f"next{k}") + f"t{k}:\n" + snap(0)
                  + RETRBI + f"next{k}:\n", (0, 1),
                  "the frame in bank 3's slots, the PSW in bank 3; RETRBI back"))
    k += 1
    # BRKCS IY = FFF5h: bank 5 (the low three bits), PS 0010h in bank 5
    C.append(Case("brkcs_iy", case_head(k, "BRKCS IY (FFF5h)")
                  + all_slots("VPC", f"t{k}")
                  + "    MOV IY, 0FFF5h\n" + set_psw(0x0022) + brkcs("IY") + f"r{k}:\n" + snap(3)
                  + jmp(f"next{k}") + f"t{k}:\n" + snap(2) + RETRBI + f"next{k}:\n", (2, 3),
                  "the register's low three bits"))
    k += 1
    # BRKCS to the bank in use
    C.append(Case("brkcs_same", case_head(k, "BRKCS AW (7): the bank in use")
                  + all_slots("VPC", f"t{k}") + "    MOV AW, 0007h\n" + set_psw(PSW_T)
                  + brkcs("AW") + f"r{k}:\n" + snap(5) + jmp(f"next{k}") + f"t{k}:\n" + snap(4)
                  + RETRBI + f"next{k}:\n", (4, 5), "bank 7 to bank 7"))
    k += 1
    # TSKSW CW = 4: bank 4's PSW save names RB 2 (which wins?), PC save t
    C.append(Case("tsksw", case_head(k, "TSKSW CW (4); bank 4's PSW save A0C3h (RB 2)")
                  + all_slots("PCS", f"t{k}") + set_slot(4, "PSWS", 0xA0C3) + "    MOV CW, 0004h\n" + set_psw(PSW_T)
                  + tsksw("CW") + f"r{k}:\n" + snap(7) + jmp(f"next{k}") + f"t{k}:\n" + snap(6)
                  + "    MOV AW, 0007h\n" + tsksw("AW") + jmp("lost") + f"next{k}:\n",
                  (6, 7), "TSKSW there and back"))
    k += 1
    # MOVSPA after BRKCS (the previous bank: bank 7, SS 0001h SP 7EF0h)
    C.append(Case("movspa", case_head(k, "BRKCS AW (3), MOVSPA, RETRBI")
                  + all_slots("VPC", f"t{k}") + "    MOV AW, 0003h\n" + set_psw(0x0002)
                  + brkcs("AW") + f"r{k}:\n" + snap(9) + jmp(f"next{k}") + f"t{k}:\n" + MOVSPA
                  + snap(8) + RETRBI + f"next{k}:\n", (8, 9), "SS and SP of the old bank"))
    k += 1
    # MOVSPA with the PSW save's RB changed to 5 (which bank is "the old one"?)
    C.append(Case("movspa_rb5", case_head(k, "BRKCS AW (3); bank 3's PSW save RB -> 5; MOVSPA")
                  + all_slots("VPC", f"t{k}") + "    MOV AW, 0003h\n" + set_psw(0x0002)
                  + brkcs("AW") + f"r{k}:\n" + snap(11) + jmp(f"next{k}") + f"t{k}:\n"
                  + "    MOV AW, 0FFE0h\n    MOV DS0, AW\n    MOV BW, [0064h]\n    MOV AW, BW\n"
                  "    AND AW, 8FFFh\n    OR AW, 5000h\n    MOV [0064h], AW\n" + MOVSPA + snap(10)
                  + "    MOV [0064h], BW\n" + RETRBI + f"next{k}:\n", (10, 11),
                  "MOVSPA's source bank: the PSW save's RB or the bank entered from"))
    k += 1
    # MOVSPB CW = 2 (no switch)
    C.append(Case("movspb", case_head(k, "MOVSPB CW (2)") + "    MOV CW, 0002h\n"
                  + movspb("CW") + snap(12), (12,), "SS and SP into bank 2"))
    k += 1
    # RETRBI with no entry: bank 7's saves name bank 6 and t
    C.append(Case("retrbi_cold", case_head(k, "RETRBI from bank 7's saves (RB 6, t)")
                  + movw(0xE6, f"t{k}") + movw(0xE4, 0xE0C3) + set_psw(0x0002)
                  + RETRBI + jmp("lost") + f"t{k}:\n" + snap(13)
                  + "    MOV AW, 0FFE0h\n    MOV DS0, AW\n"
                  + movw(0xE6, f"r{k}") + movw(0xE4, 0xF002)
                  + "    MOV AW, 0007h\n" + tsksw("AW") + jmp("lost") + f"r{k}:\n" + snap(14),
                  (13, 14), "RETRBI: PC and PSW from the bank's saves, the bank by the PSW's RB"))
    k += 1
    # TSKSW CW = 4 with bank 4's PSW save naming RB 2: whose PC save (bank 4's t, bank 2's u)?
    C.append(Case("tsksw_pc", case_head(k, "TSKSW CW (4); PC saves: bank 4 t, bank 2 u")
                  + set_slot(4, "PCS", f"t{k}") + set_slot(2, "PCS", f"u{k}")
                  + set_slot(4, "PSWS", 0xA0C3) + "    MOV CW, 0004h\n" + set_psw(PSW_T)
                  + tsksw("CW") + f"r{k}:\n" + snap(17) + jmp(f"next{k}") + f"t{k}:\n" + snap(15)
                  + "    MOV AW, 0007h\n" + tsksw("AW") + jmp("lost") + f"u{k}:\n" + snap(16)
                  + "    MOV AW, 0007h\n" + tsksw("AW") + jmp("lost") + f"next{k}:\n",
                  (15, 16, 17), "TSKSW's PC: the operand's bank's save or the PSW's RB bank's"))
    k += 1
    return C


# ------------------------------------------------------------------ f3_bsw
def ic(name, v):
    """An IC store with DS0 = FFE0h."""
    return f"    MOV byte [{_h(0x100 + intr.SFR[name], 4)}], {_h(v)}\n"


CLEAN = "    DI\n" + "".join(ic(n, 0x47) for n in intr.ICS) + FINT * 8


def bsw_cases():
    C = []
    k = 0
    # INTP0 by an IF store, ENCS 1, PR 3: bank 3 (PS 0010h there)
    C.append(Case("intp0_bank3", case_head(k, "EXIC0 93h (IF ENCS PR3), EI, MULU")
                  + set_slot(3, "PS", 0x0010) + set_slot(3, "VPC", f"h{k}-256")
                  + ic("EXIC0", 0x93) + "    EI\n" + CHAIN + "    NOP\n    NOP\n" + f"b{k}:\n"
                  + snap(1) + CLEAN + jmp(f"next{k}") + f"h{k}:\n" + snap(0, c=0x10) + MOVSPA
                  + snap(2, c=0x10) + FINT + RETRBI + f"next{k}:\n", (0, 1, 2),
                  "the frame in bank 3, PS from bank 3, ISPR, MOVSPA, FINT, RETRBI"))
    k += 1
    # INTP1: EXIC1 ENCS 1 (own PR 0), EXIC0 ENCS 0 PR 5 MK 1: which mode, which bank?
    C.append(Case("intp1_own_encs", case_head(k, "EXIC0 45h, EXIC1 90h (IF ENCS PR0)")
                  + "".join(set_slot(n, "VPC", f"h{k}") for n in range(7))
                  + movw(0xE2, f"h{k}")
                  + ic("EXIC0", 0x45) + ic("EXIC1", 0x90) + "    EI\n" + CHAIN + "    NOP\n"
                  + f"b{k}:\n" + snap(4) + CLEAN + jmp(f"next{k}") + f"h{k}:\n" + snap(3) + FINT
                  + RETRBI + f"next{k}:\n", (3, 4), "the member's ENCS, the leader's PR"))
    k += 1
    # INTP1: EXIC0 ENCS 1 PR 5 MK 1, EXIC1 ENCS 0
    C.append(Case("intp1_lead_encs", case_head(k, "EXIC0 55h (ENCS PR5 MK), EXIC1 80h (IF)")
                  + "".join(set_slot(n, "VPC", f"h{k}") for n in range(7))
                  + movw(0xE2, f"h{k}")
                  + ic("EXIC0", 0x55) + ic("EXIC1", 0x80) + "    EI\n" + CHAIN + "    NOP\n"
                  + f"b{k}:\n" + snap(6) + CLEAN + jmp(f"next{k}") + f"h{k}:\n" + snap(5) + FINT
                  + RETRBI + f"next{k}:\n", (5, 6), "the leader's ENCS"))
    k += 1
    # TB (level 7): TBIC 90h (IF ENCS); the book: TB has no bank switching
    C.append(Case("tb_encs", case_head(k, "TBIC 90h (IF ENCS)")
                  + movw(0xE2, f"h{k}") + ic("TBIC", 0x90) + "    EI\n" + CHAIN
                  + "    NOP\n" + f"b{k}:\n" + snap(8) + CLEAN + jmp(f"next{k}") + f"h{k}:\n"
                  + snap(7) + FINT + RETRBI + f"next{k}:\n", (7, 8),
                  "TB with ENCS 1 (bank 7 = its level, or vectored 31)"))
    k += 1
    # TMIC0 92h (IF ENCS PR2): bank 2; inside, EI and a nested SEIC0 91h (PR1): bank 1
    C.append(Case("nest_bank", case_head(k, "TMIC0 92h; in bank 2 EI, SEIC0 91h: bank 1")
                  + set_slot(2, "VPC", f"h{k}") + set_slot(1, "VPC", f"g{k}")
                  + ic("TMIC0", 0x92) + "    EI\n" + CHAIN + "    NOP\n" + f"b{k}:\n" + snap(12)
                  + CLEAN + jmp(f"next{k}") + f"h{k}:\n" + snap(9)
                  + "    MOV AW, 0FFE0h\n    MOV DS0, AW\n" + ic("SEIC0", 0x91) + "    EI\n"
                  + CHAIN + "    NOP\n" + snap(11) + "    DI\n" + FINT + RETRBI + f"g{k}:\n"
                  + snap(10) + FINT + RETRBI + f"next{k}:\n", (9, 10, 11, 12),
                  "nesting: bank 2 then bank 1, RETRBI to bank 2, RETRBI to bank 7"))
    k += 1
    # RETI from a bank-switch handler (what does it pop?) is not run: the stack holds no frame
    return C


# ------------------------------------------------------------------ f3_brkn, f3_int, f3_brks
def test_program(name, tests, note="", gate=True, head="", tail="", spec=None, extra=None):
    """intr.make_program's frame with a head (after DI) and a tail (before the pass), the
    vectors 0-63 and the stimulus keys in `spec`."""
    prog = intr.make_program(name, tests, note=note, gate=gate, extra=extra)
    src = prog.source
    assert src.startswith("    DI\n")
    i = src.rindex(intr.EPILOGUE)
    prog.source = "    DI\n" + head + src[len("    DI\n"):i] + tail + src[i:]
    area = vectors64()
    prog.data.update({0x0000: area[0x0000], STUBS: area[STUBS]})
    prog.data.update(extra or {})
    if spec:
        prog.stim = dict(prog.stim or {}, **spec)
    return prog


def brkn_tests():
    return [
        Test("brkn_32", code="    DB 63h, 20h\n", psw=PSW_T, note="BRKN 20h: vector 32"),
        Test("brkn_3", code="    DB 63h, 03h\n", psw=0x0002, note="BRKN 3: vector 3"),
        Test("brkn_pfx", code="    DB 2Eh\n    DB 63h, 21h\n", psw=PSW_IE,
             note="PS: BRKN 21h: the pushed PC (the prefix's or BRKN's)"),
    ]


R2_Z, R2_D = 0x04, 0x08
INT_HEAD = (f"    MOV DW, 0FF10h\n    MOV AL, {_h(R2_Z)}\n    OUT DW, AL\n"
            "    MOV AW, 0F000h\n    MOV DS1, AW\n"
            + "    DB 26h\n    MOV byte [0FF08h], 00h\n"      # P1 latch 0
            + "    DB 26h\n    MOV byte [0FF68h], 04h\n"      # SCM0: I/O mode, RSCK out on CTS0
            + "    DB 26h\n    MOV byte [0FF09h], 97h\n"      # PM1: P13 P15 P16 outputs
            + "    DB 26h\n    MOV byte [0FF0Ah], 18h\n"      # PMC1: INTAK, INT
            + f"    MOV DW, 0FF10h\n    MOV AL, {_h(R2_D)}\n    OUT DW, AL\n")
INT_TAIL = (f"    MOV DW, 0FF10h\n    MOV AL, {_h(R2_Z)}\n    OUT DW, AL\n"
            "    MOV AW, 0F000h\n    MOV DS1, AW\n"
            + "    DB 26h\n    MOV byte [0FF0Ah], 00h\n"
            + "    DB 26h\n    MOV byte [0FF09h], 0FFh\n"
            + "    DB 26h\n    MOV byte [0FF68h], 00h\n"
            + "    MOV DW, 0FF10h\n    MOV AL, 00h\n    OUT DW, AL\n")
INT_VEC = 0x22


def int_tests():
    up = {"event": "E0", "delay": 200, "levels": {"INT": 1}}
    return [
        Test("int_rel", pre=ev("E0") + wait(WAIT, "p"), code="    EI\n" + CHAIN,
             stim=[up], note="INT high behind IE 0, EI, MULU: INTAK, vector 22h"),
        Test("int_intp0", pre=sfr_wr("EXIC0", 0x87) + ev("E0") + wait(WAIT, "p"),
             code="    EI\n" + CHAIN, stim=[up], note="INT and INTP0 (PR 7) pending: the order"),
        Test("int_intp0_hi", pre=sfr_wr("EXIC0", 0x80) + ev("E0") + wait(WAIT, "p"),
             code="    EI\n" + CHAIN, stim=[up], note="INT and INTP0 (PR 0) pending"),
        *[Test(f"int_intp0_p{pr}", pre=sfr_wr("EXIC0", 0x80 | pr) + ev("E0") + wait(WAIT, "p"),
               code="    EI\n" + CHAIN, stim=[up], note=f"INT and INTP0 (PR {pr}) pending")
          for pr in (1, 3, 6)],
        Test("int_halt", pre=ev("E0"), code="    HALT\n", psw=PSW_IE,
             stim=[dict(up, delay=intr.D_HALT)], jitter=True, note="INT in HALT, IE 1"),
        Test("int_halt_ie0", pre=ev("E0"),
             code="    HALT\n" + sfr_rd("ISPR", "{S}") + "    EI\n" + CHAIN, psw=PSW0,
             action=intr.nmi_skip("    FINT\n"),
             stim=[dict(up, delay=intr.D_HALT),
                   {"event": None, "delay": 200000, "hold": intr.HOLD, "levels": {"NMI": 0}}],
             note="INT in HALT, IE 0: released? (an NMI 6 ms later ends a stuck HALT)"),
    ]


BRKS_H = 0x3400         # BRKS's vector 33: HALT x 16 (translated on silicon)
BRKS_D = 600            # ticks: the NMI edge about 19 clocks (fX/8) into BRKS


def brks_tests():
    act = ("    MOV DW, 0FF00h\n    OUT DW, AL\nbe{k}:\n    HALT\n    BR be{k}\n")
    out = "    MOV DW, 0FF12h\n    MOV AL, {E0}\n    OUT DW, AL\n"     # the event, then BRKS at once
    return [Test("brks_nmi", code=out + "    DB 0F1h, 21h\n", psw=0x0002, action=act,
                 stim=[pulse("E0", "NMI", delay=BRKS_D)], jitter=True,
                 note="BRKS 21h, an NMI during it: the frames, the NMI handler's MD")]


def programs():
    P = {
        "f3_bins": bank_program("f3_bins", bins_cases(),
                                note="BRKCS, TSKSW, MOVSPA, MOVSPB, RETRBI"),
        "f3_bsw": bank_program("f3_bsw", bsw_cases(), note="the bank-switch entry (ENCS 1)"),
        "f3_brkn": test_program("f3_brkn", brkn_tests(), note="BRKN"),
        "f3_int": test_program("f3_int", int_tests(), note="INT / INTAK", head=INT_HEAD,
                               tail=INT_TAIL, spec={"intak_vector": INT_VEC, "int_release": True,
                                                    "pins": ["INTAK"]}),
    }
    P["f3_brks"] = test_program("f3_brks", brks_tests(),
                                note="BRKS, the NMI during it (socket: run alone, short limit)",
                                extra={BRKS_H: bytes([0xF4] * 16)})
    ivt = bytearray(P["f3_brks"].data[0x0000])
    ivt[4 * 33:4 * 33 + 4] = BRKS_H.to_bytes(2, "little") + b"\x00\x00"
    P["f3_brks"].data[0x0000] = bytes(ivt)
    return P


# ------------------------------------------------------------------ running
def run_one(harness, prog, lane, limit=40_000_000):
    """onchip.run_one with the pin records and the bus records around them kept."""
    from .onchip import _io_reads, _write_sequence
    from .runner import FLAG_PIN, FLAG_READ, FLAG_STROBE, FLAG_IO
    code, segments, pages = prog.image()
    harness.load(segments, pages)
    mode = "socket" if lane == "socket" else "model"
    result = harness.run(mode, limit)
    trace = list(result[f"{lane}_trace"])
    total = result[f"{lane}_total"]
    replay = []
    for start in range(2048, total, 2048):
        harness.load(segments, pages)
        window = harness.run(mode, limit, capture_start=start)
        for field in ("total", "signature"):
            if window[f"{lane}_{field}"] != result[f"{lane}_{field}"]:
                replay.append(f"{field} changed at window {start}")
        trace.extend(window[f"{lane}_trace"])
    regions = {f"{a:05X}": harness.read_memory(lane, a, n).hex() for a, n in prog.results}
    pins = [i for i, t in enumerate(trace) if t["flags"] & FLAG_PIN]
    around = sorted({j for i in pins for j in range(max(0, i - 6), min(len(trace), i + 6))})
    code_end = 0x100 + len(code)
    ext_reads = [[t["address"], t["data"]] for t in trace
                 if t["flags"] & FLAG_STROBE and t["flags"] & FLAG_READ
                 and not t["flags"] & FLAG_IO and not (0x100 <= t["address"] < code_end + 8)
                 and not (0xFFFF0 <= t["address"] <= 0xFFFFF)]
    return {
        "program": prog.name, "note": prog.note, "gate": prog.gate,
        "program_sha256": hashlib.sha256(code).hexdigest(),
        "passed": result["passed"], "status": result["status"], "timeout": result["timeout"],
        "total": total, "markers": result["markers"], "last_marker": result["last_marker"],
        "writes": _write_sequence(trace), "io_reads": _io_reads(trace), "data_reads": ext_reads,
        "regions": regions, "replay": replay,
        "pin_window": [[j, trace[j]["start"], trace[j]["address"], trace[j]["data"],
                        trace[j]["flags"], trace[j]["strobe"], trace[j]["end"]] for j in around],
        "trace_tail": [[t["address"], t["data"], t["flags"]] for t in trace[-24:]],
        "stimulus": result.get("stimulus"),
    }


def run_set(names, backend, tag="", progs=None, limit=40_000_000):
    from .traps import _board, _close_board, _sim, _stim
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
                       stim=progs[name].stim, levels=progs[name].levels)
            if backend == "socket":
                rec.update(cpu="uPD70337L-8", x_half=2)
            else:
                rec.update(core="v35", binary=os.environ.get(
                    "V35_SIM_BINARY", "build/fpga/v35s/verilator-direct-v35"))
            intr.save(rec, name, backend + tag)
            print(f"{name}: {backend} {'PASS' if rec['passed'] else 'FAIL'} "
                  f"status=0x{rec['status']:04x} writes={len(rec['writes'])} total={rec['total']}",
                  flush=True)
    finally:
        if backend == "socket":
            _close_board(transport, harness)


# ------------------------------------------------------------------ reading
def _w(b, o):
    return b[o] | b[o + 1] << 8


def snapshots(rec):
    raw = bytes.fromhex(rec["regions"].get(f"{SNAP:05X}", ""))
    out = []
    for n in range(len(raw) // 0x120):
        s = raw[0x120 * n:0x120 * n + 0x120]
        e = s[0x100:]
        d = {r: _w(e, o) for r, o in EXTRA.items()}
        d.update({nm: e[o] for nm, (o, _) in EXTRA_B.items()})
        d["n"] = e[25]
        d["banks"] = [{sl: _w(s, 0x20 * b + o) for sl, o in SLOT.items()} | {"R0": _w(s, 0x20 * b)}
                      for b in range(8)]
        out.append(d)
    return out


def show(name, backend="socket", progs=None):
    progs = progs or programs()
    prog = progs[name]
    rec = intr.load(name, backend)
    labels = intr.labels_of(prog)
    print(f"{name} ({backend}): passed {rec['passed']} status {rec['status']:04x}")
    if not getattr(prog, "cases", None):
        intr.show(name, backend, progs)
        for row in rec.get("pin_window", []):
            print("   ", row[0], row[1], f"{row[2]:05X} {row[3]:04X} {row[4]:03X}", row[5], row[6])
        return
    snaps = snapshots(rec)
    base = None
    for c in prog.cases:
        print(f"-- {c.name}: {c.note}")
        for n in c.snaps:
            if n >= len(snaps):
                print(f"   snap {n}: missing")
                continue
            s = snaps[n]
            rb = (s["PSW"] >> 12) & 7
            print(f"   snap {n} (mark {s['n']}): PSW={s['PSW']:04X} (RB {rb}) SS:SP={s['SS']:04X}:"
                  f"{s['SP']:04X} AW={s['AW']:04X} CW={s['CW']:04X} IY={s['IY']:04X}"
                  f" DS0={s['DS0']:04X} DS1={s['DS1']:04X} ISPR={s['ISPR']:02X}"
                  f" EXIC0-2={s['EXIC0']:02X} {s['EXIC1']:02X} {s['EXIC2']:02X}"
                  f" TMIC0={s['TMIC0']:02X} TBIC={s['TBIC']:02X} SEIC0={s['SEIC0']:02X}")
            tab = bank_table()
            for b, bk in enumerate(s["banks"]):
                ref = {sl: _w(tab, 0x20 * b + o) for sl, o in SLOT.items()} if b < 7 else {}
                ch = [sl for sl in ("VPC", "PSWS", "PCS", "PS", "SS", "SP", "DS0", "DS1", "AW",
                                    "CW", "DW", "BW", "BP", "IX", "IY") if bk[sl] != ref.get(sl)]
                if ch:
                    print(f"     bank {b}: " + " ".join(
                        f"{sl}={bk[sl]:04X}" + (f"[{intr.where(labels, bk[sl])}]"
                                                if sl in ("VPC", "PCS") else "") for sl in ch))
    regs = rec["regions"]
    log = bytes.fromhex(regs[f"{LOG + 0x100:05X}"])
    count = _w(bytes.fromhex(regs[f"{LOG:05X}"]), 0)
    for i in range(min(count, len(log) // 32)):
        e = log[32 * i:32 * i + 32]
        print(f"   log {i}: v{e[0]} pc={_w(e, 6):04X}:{_w(e, 4):04X} [{intr.where(labels, _w(e, 4))}]"
              f" psw={_w(e, 8):04X} h={_w(e, 10):04X} ispr={e[14]:02X}")


def exclude(name, ref, progs):
    """The gate's masked bytes. A snapshot's copy of the bank in use (REP MOVBKW from IDB:E00)
    reads that bank's CW slot while the string runs: silicon reads the count as it stood before
    the string (0080h) at every element, the RTL the live count (measured here, outside F3: the
    string unit's CW write-back; the snapshot's own extras hold CW before the copy)."""
    prog = progs[name]
    if getattr(prog, "cases", None):
        ex = set()
        for n, s in enumerate(snapshots(intr.load(name, ref))):
            rb = (s["PSW"] >> 12) & 7
            ex |= {SNAP + 0x120 * n + 0x20 * rb + 0x1C + j for j in range(2)}
        return ex
    return intr.jitter_bytes(name, ref, progs)


def emit(progs=None):
    for name, prog in (progs or programs()).items():
        path = intr.PROGRAMS_DIR / f"{name}.s"
        path.write_text(f"; F3 part B ({prog.note}). Generated by validation/v35s/banks.py emit:\n"
                        f"; the image also preloads the vectors, the handler and the tables.\n"
                        + prog.source)
        stim = intr.PROGRAMS_DIR / f"{name}.stim.json"
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
    names = a.names or [n for n, prog in progs.items()
                        if prog.gate and (a.action != "socket" or n != "f3_brks")]
    if a.action in ("socket", "sim"):
        run_set(names, a.action, a.tag, progs)
    elif a.action == "gate":
        return 0 if intr.compare_gate(names, a.ref, a.cand,
                                      exclude=lambda n: exclude(n, a.ref, progs)) else 1
    elif a.action == "show":
        for n in names:
            show(n, a.ref, progs)
    elif a.action == "size":
        for n in names:
            code, _, _ = progs[n].image()
            print(n, f"{len(code)} bytes")
    else:
        emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
