"""F1: on-chip memory and the SFR page as data (docs/v35s-function-plan.md, stage F1).

Directed programs measured on the socketed uPD70337 and run unchanged on the core v2 RTL in
simulation. Each program writes what it saw to external memory (the result pages) with plain
stores, so a run is compared by its write and I/O sequence and its result pages, timing ignored.

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.onchip socket [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.onchip sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.onchip compare [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.onchip table          # the SFR table
    PYTHONPATH=host/src:. python3 -m validation.v35s.onchip emit           # write programs/f1_*.s

socket runs the programs on the board (the socket lane), sim on the v35 core in the model lane
of the direct harness (build/fpga/v35s/verilator-direct-v35/Vv35s_harness, as the chains replay
runs it; V35_SIM_BINARY overrides). Receipts: validation/v35s/receipts/f1-<name>-<backend>.json
(--tag adds a suffix: a second socket run is f1-<name>-socket-2.json).

Every program starts the same way: the interrupt vector table is preloaded (vector n points to a
stub at 0000:0080+4n that loads n into AL and jumps to a handler at 0000:0103, which writes the
vector and the top of the stack to 0000:7E00 and reports a failure on marker port FF02h), so an
unexpected interrupt or trap ends the run visibly. Programs end with OUT FF00h (pass) and HALT.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS_DIR = ROOT / "validation/v35s/programs"
RECEIPTS = ROOT / "validation/v35s/receipts"

# ------------------------------------------------------------------ the SFR map (data book Table 6)
# offset -> (symbol, R/W in the book, book reset value or None when "undefined")
SFR = {
    0x00: ("P0", "R/W", None), 0x01: ("PM0", "W", 0xFF), 0x02: ("PMC0", "W", 0x00),
    0x08: ("P1", "R/W", None), 0x09: ("PM1", "W", 0xFF), 0x0A: ("PMC1", "W", 0x00),
    0x10: ("P2", "R/W", None), 0x11: ("PM2", "W", 0xFF), 0x12: ("PMC2", "W", 0x00),
    0x38: ("PT", "R", None), 0x3B: ("PMT", "R/W", 0x00),
    0x40: ("INTM", "R/W", 0x00), 0x44: ("EMS0", "R/W", None), 0x45: ("EMS1", "R/W", None),
    0x46: ("EMS2", "R/W", None), 0x4C: ("EXIC0", "R/W", 0x47), 0x4D: ("EXIC1", "R/W", 0x47),
    0x4E: ("EXIC2", "R/W", 0x47),
    0x60: ("RxB0", "R", None), 0x62: ("TxB0", "W", None), 0x65: ("SRMS0", "R/W", None),
    0x66: ("STMS0", "R/W", None), 0x68: ("SCM0", "R/W", 0x00), 0x69: ("SCC0", "R/W", 0x00),
    0x6A: ("BRG0", "R/W", 0x00), 0x6B: ("SCE0", "R", 0x00), 0x6C: ("SEIC0", "R/W", 0x47),
    0x6D: ("SRIC0", "R/W", 0x47), 0x6E: ("STIC0", "R/W", 0x47),
    0x70: ("RxB1", "R", None), 0x72: ("TxB1", "W", None), 0x75: ("SRMS1", "R/W", None),
    0x76: ("STMS1", "R/W", None), 0x78: ("SCM1", "R/W", 0x00), 0x79: ("SCC1", "R/W", 0x00),
    0x7A: ("BRG1", "R/W", 0x00), 0x7B: ("SCE1", "R", 0x00), 0x7C: ("SEIC1", "R/W", 0x47),
    0x7D: ("SRIC1", "R/W", 0x47), 0x7E: ("STIC1", "R/W", 0x47),
    0x80: ("TM0", "R/W", None), 0x81: ("TM0H", "R/W", None),
    0x82: ("MD0", "R/W", None), 0x83: ("MD0H", "R/W", None),
    0x88: ("TM1", "R/W", None), 0x89: ("TM1H", "R/W", None),
    0x8A: ("MD1", "R/W", None), 0x8B: ("MD1H", "R/W", None),
    0x90: ("TMC0", "R/W", 0x00), 0x91: ("TMC1", "R/W", 0x00),
    0x94: ("TMMS0", "R/W", None), 0x95: ("TMMS1", "R/W", None), 0x96: ("TMMS2", "R/W", None),
    0x9C: ("TMIC0", "R/W", 0x47), 0x9D: ("TMIC1", "R/W", 0x47), 0x9E: ("TMIC2", "R/W", 0x47),
    0xA0: ("DMAC0", "R/W", None), 0xA1: ("DMAM0", "R/W", 0x00), 0xA2: ("DMAC1", "R/W", None),
    0xA3: ("DMAM1", "R/W", 0x00), 0xAC: ("DIC0", "R/W", 0x47), 0xAD: ("DIC1", "R/W", 0x47),
    0xE0: ("STBC", "R/W", None), 0xE1: ("RFM", "R/W", 0xFC), 0xE8: ("WTC", "R/W", 0xFF),
    0xE9: ("WTCH", "R/W", 0xFF), 0xEA: ("FLAG", "R/W", 0x00), 0xEB: ("PRC", "R/W", 0x4E),
    0xEC: ("TBIC", "R/W", 0x47), 0xFC: ("ISPR", "R", None), 0xFF: ("IDB", "R/W", 0xFF),
}
IC_REGS = {0x4C, 0x4D, 0x4E, 0x6C, 0x6D, 0x6E, 0x7C, 0x7D, 0x7E, 0x9C, 0x9D, 0x9E, 0xAC, 0xAD,
           0xEC}
# never written by the sweep: the port modes (an output against a host-driven bank: the harness
# safety rules), STBC (bits can only be set: STOP / HALT), IDB (moves the page: f1_idb)
NO_WRITE = {0x01, 0x02, 0x09, 0x0A, 0x11, 0x12, 0xE0, 0xFF}
PATTERNS = (0x00, 0xFF, 0x55, 0xAA)
WORD_REGS = (0x80, 0x82, 0x88, 0x8A, 0xE8)
WORD_PATTERNS = (0x0000, 0xFFFF, 0x5555, 0xAAAA)


def sweep_value(offset: int, pattern: int) -> int:
    """The byte the sweep writes for `pattern` at `offset` (the safe substitutions)."""
    if offset == 0xEB:                  # PRC: PCK 11 is reserved
        return 0xFE if pattern == 0xFF else pattern
    if offset == 0xE1:                  # RFM: RFEN 0 with RFLV 0 holds /REFRQ low, and RFT 1 /
        # RFW 1 refresh stopped the lane: refresh on only as FF (RFW 3), otherwise off, RFLV 1
        return pattern if pattern == 0xFF else (pattern & 0xEF) | 0x80
    if offset in (0xA1, 0xA3):          # DMAM: EDMA (bit 3) and TDMA (bit 2) kept 0
        return pattern & 0xF3
    if offset in IC_REGS and pattern == 0xAA:   # IF set with MK clear: a request
        return 0xEA
    return pattern


# ------------------------------------------------------------------ the image's fixed parts
RES = 0x8000            # the result pages (DS0 = 0800h in the sweep: offsets 0000-3FFF)
HANDLER = 0x103
TRAPLOG = 0x7E00

PRELUDE = """\
    BR main
handler:                ; 0103h: AL = the vector (from the stub)
    MOV BL, AL
    XOR AW, AW
    MOV DS0, AW
    MOV [7E00h], BL
    MOV BP, SP
    MOV AW, [BP]
    MOV [7E02h], AW
    MOV AW, [BP+2]
    MOV [7E04h], AW
    MOV AW, [BP+4]
    MOV [7E06h], AW
    MOV [7E08h], SP
    MOV AH, 02h         ; BRKI = 1: the OUT below does not trap
    MOV PSW, AH
    MOV DW, 0FF02h
    OUT DW, AL
    HALT
hspin:
    BR hspin
main:
    XOR AW, AW
    MOV SS, AW
    MOV SP, 7FFEh
"""

EPILOGUE = """\
    MOV DW, 0FF00h
    OUT DW, AL
    HALT
done:
    BR done
"""


def ivt_segment() -> bytes:
    """Vectors 0..31 -> 0000:0080+4n; stub n = MOV AL,n; BR short handler."""
    out = bytearray()
    for n in range(32):
        out += (0x80 + 4 * n).to_bytes(2, "little") + b"\x00\x00"
    for n in range(32):
        rel = HANDLER - (0x80 + 4 * n + 4)
        out += bytes([0xB0, n, 0xEB, rel & 0xFF])
    return bytes(out)


# ------------------------------------------------------------------ the programs
class Program:
    def __init__(self, name, source, data=None, results=(), extra_pages=(), gate=True, note=""):
        self.name = name
        self.source = source
        self.data = dict(data or {})        # address -> bytes, preloaded
        self.results = list(results)        # (address, length) read back
        self.extra_pages = tuple(extra_pages)
        self.gate = gate                    # part of the RTL gate
        self.note = note

    def image(self):
        from .asm import assemble
        code = assemble(self.source, org=0x100)
        segments = {0x0000: ivt_segment(), 0x100: code,
                    0xFFFF0: bytes([0xEA, 0x00, 0x01, 0x00, 0x00])}
        segments.update(self.data)
        pages = set(self.extra_pages) | {address >> 12 for address, _ in self.results}
        pages |= {(a + n - 1) >> 12 for a, n in self.results}
        return code, segments, sorted(pages)


def sfr_program(name, offsets, words=False, note=""):
    """The page through DS1 = F000h (prefix 26h; IDB FFh), the results by DS0 = 0800h stores:
    the page at reset as bytes (0000h) and words (0100h); per swept offset 8 bytes at 0200h +
    8 * offset (the value before, the four read-backs); the 16-bit registers by word (0A00h);
    the page after the sweep (0B00h)."""
    lines = [PRELUDE + "    DI\n"]
    lines.append("    MOV AW, 0F000h\n    MOV DS1, AW\n    MOV AW, 0800h\n    MOV DS0, AW")
    # reset pass: loads through DS1 (prefix 26h), stores to DS0:[IY] by MOV [IY], AL; INC IY
    lines.append("    MOV IY, 0000h")
    for o in range(256):
        lines.append(f"    DB 26h\n    MOV AL, [0FF{o:02X}h]\n    MOV [IY], AL\n    INC IY")
    for o in range(0, 256, 2):
        lines.append(f"    DB 26h\n    MOV AW, [0FF{o:02X}h]\n    MOV [IY], AW\n    INC IY\n    INC IY")
    # the sweep: per offset 8 bytes at 0200h + 8 * offset: the value before, the four reads
    for o in offsets:
        base = 0x200 + 8 * o
        lines.append(f"    ; {o:02X} {SFR.get(o, ('-',))[0]}")
        lines.append(f"    DB 26h\n    MOV AL, [0FF{o:02X}h]\n    MOV [{base:04X}h], AL\n    MOV AH, AL")
        for k, p in enumerate(PATTERNS):
            v = sweep_value(o, p)
            lines.append(f"    DB 26h\n    MOV byte [0FF{o:02X}h], {v:02X}h\n"
                         f"    DB 26h\n    MOV AL, [0FF{o:02X}h]\n    MOV [{base + 1 + k:04X}h], AL")
        lines.append(f"    DB 26h\n    MOV [0FF{o:02X}h], AH")
    if words:
        # the 16-bit registers by word: 10 bytes each at 0A00h + 16 * k
        for k, o in enumerate(WORD_REGS):
            base = 0xA00 + 16 * k
            lines.append(f"    ; word {o:02X} {SFR[o][0]}")
            lines.append(f"    DB 26h\n    MOV AW, [0FF{o:02X}h]\n    MOV [{base:04X}h], AW\n    MOV CW, AW")
            for j, p in enumerate(WORD_PATTERNS):
                lines.append(f"    DB 26h\n    MOV word [0FF{o:02X}h], {p:04X}h\n"
                             f"    DB 26h\n    MOV AW, [0FF{o:02X}h]\n    MOV [{base + 2 + 2 * j:04X}h], AW")
            lines.append(f"    DB 26h\n    MOV [0FF{o:02X}h], CW")
    # the page again after the sweep (restored values; live registers), at 0B00h
    lines.append("    MOV IY, 0B00h")
    for o in range(256):
        lines.append(f"    DB 26h\n    MOV AL, [0FF{o:02X}h]\n    MOV [IY], AL\n    INC IY")
    lines.append(EPILOGUE)
    return Program(name, "\n".join(lines) + "\n", results=[(RES, 0xC00), (TRAPLOG, 0x10)],
                   note=note)


def documented_writable():
    return [o for o in sorted(SFR) if o not in NO_WRITE]


def undocumented():
    return [o for o in range(256) if o not in SFR]


# bank 7's slots +00..+07 (reserved, vector PC, PSW save, PC save) are not registers: preset so
# that a dump reads defined values (silicon's internal RAM powers up random)
BANK7_PRESET = """\
    DB 26h
    MOV word [0FEE0h], 0E1E0h
    DB 26h
    MOV word [0FEE2h], 0E3E2h
    DB 26h
    MOV word [0FEE4h], 0E5E4h
    DB 26h
    MOV word [0FEE6h], 0E7E6h"""


# ---- internal RAM as data, the registers' aliasing ---------------------------------------
def iram_program():
    """Banks 0-6 (E00-EDF) as memory, byte and word, even and odd; bank 7's registers at their
    slots both ways; the segment registers' slots (DS0, SS, DS1) written as memory then used.
    DS1 = F000h reaches the page (prefix 26h); results by DS0 = 0800h (0000h-0BFFh)."""
    L = [PRELUDE + "    DI\n"]
    L.append("    MOV AW, 0F000h\n    MOV DS1, AW\n    MOV AW, 0800h\n    MOV DS0, AW")
    L.append(BANK7_PRESET)
    # 1. bytes: E00+o <- (o * 7 + 31h); read back bytes at 0000h
    L.append("""\
    MOV BW, 0FE00h
    MOV AL, 31h
    MOV CW, 00E0h
b_wr:
    DB 26h
    MOV [BW], AL
    ADD AL, 07h
    INC BW
    DBNZ b_wr
    MOV BW, 0FE00h
    MOV IY, 0000h
    MOV CW, 00E0h
b_rd:
    DB 26h
    MOV AL, [BW]
    MOV [IY], AL
    INC BW
    INC IY
    DBNZ b_rd""")
    # 2. words at even addresses: E00+2k <- 0A55Ah xor (k * 0103h); read words at odd addresses
    #    (0100h..), bytes (0200h..)
    L.append("""\
    MOV BW, 0FE00h
    MOV DW, 0A55Ah
    MOV CW, 0070h
w_wr:
    DB 26h
    MOV [BW], DW
    ADD DW, 0103h
    INC BW
    INC BW
    DBNZ w_wr
    MOV BW, 0FE01h
    MOV IY, 0100h
    MOV CW, 006Fh
w_rdo:
    DB 26h
    MOV AW, [BW]
    MOV [IY], AW
    INC BW
    INC BW
    INC IY
    INC IY
    DBNZ w_rdo
    MOV BW, 0FE00h
    MOV IY, 0200h
    MOV CW, 00E0h
w_rdb:
    DB 26h
    MOV AL, [BW]
    MOV [IY], AL
    INC BW
    INC IY
    DBNZ w_rdb""")
    # 3. words at odd addresses: E01+2k <- 1357h + k * 0F1Fh; bytes back (0300h..)
    L.append("""\
    MOV BW, 0FE01h
    MOV DW, 1357h
    MOV CW, 006Fh
o_wr:
    DB 26h
    MOV [BW], DW
    ADD DW, 0F1Fh
    INC BW
    INC BW
    DBNZ o_wr
    MOV BW, 0FE00h
    MOV IY, 0300h
    MOV CW, 00E0h
o_rd:
    DB 26h
    MOV AL, [BW]
    MOV [IY], AL
    INC BW
    INC IY
    DBNZ o_rd""")
    # 4. bank 7: each register written, its slot read (0400h..), and the slot written, the
    #    register read (0440h..). Slots (bank 7 at EE0): AW FE CW FC DW FA BW F8 SP F6 BP F4
    #    IX F2 IY F0; DS1 EE DS0 E8 SS EA PS EC
    L.append("""\
    MOV AW, 1111h
    MOV CW, 2222h
    MOV DW, 3333h
    MOV BW, 4444h
    MOV BP, 6666h
    MOV IX, 7777h
    MOV IY, 8888h
    DB 26h
    MOV AW, [0FEFEh]
    MOV [0400h], AW
    DB 26h
    MOV AW, [0FEFCh]
    MOV [0402h], AW
    DB 26h
    MOV AW, [0FEFAh]
    MOV [0404h], AW
    DB 26h
    MOV AW, [0FEF8h]
    MOV [0406h], AW
    DB 26h
    MOV AW, [0FEF6h]
    MOV [0408h], AW
    DB 26h
    MOV AW, [0FEF4h]
    MOV [040Ah], AW
    DB 26h
    MOV AW, [0FEF2h]
    MOV [040Ch], AW
    DB 26h
    MOV AW, [0FEF0h]
    MOV [040Eh], AW
    DB 26h
    MOV AW, [0FEEEh]
    MOV [0410h], AW
    DB 26h
    MOV AW, [0FEECh]
    MOV [0412h], AW
    DB 26h
    MOV AW, [0FEEAh]
    MOV [0414h], AW
    DB 26h
    MOV AW, [0FEE8h]
    MOV [0416h], AW
    DB 26h
    MOV AL, [0FEFFh]
    MOV [0418h], AL
    DB 26h
    MOV AL, [0FEFDh]
    MOV [0419h], AL
    DB 26h
    MOV AW, [0FEFDh]
    MOV [041Ah], AW
    ; the slots written, the registers read
    DB 26h
    MOV word [0FEFCh], 0A1A2h
    MOV [0440h], CW
    DB 26h
    MOV word [0FEFAh], 0B1B2h
    MOV [0442h], DW
    DB 26h
    MOV word [0FEF8h], 0C1C2h
    MOV [0444h], BW
    DB 26h
    MOV word [0FEF4h], 0D1D2h
    MOV [0446h], BP
    DB 26h
    MOV word [0FEF2h], 0E1E2h
    MOV [0448h], IX
    DB 26h
    MOV word [0FEF0h], 0F1F2h
    MOV [044Ah], IY
    DB 26h
    MOV word [0FEFEh], 9192h
    MOV [044Ch], AW
    DB 26h
    MOV byte [0FEFCh], 5Ah
    MOV [044Eh], CW
    DB 26h
    MOV byte [0FEFBh], 6Bh
    MOV [0450h], DW
    MOV AW, SP
    DB 26h
    MOV word [0FEF6h], 0FF0h
    MOV [0452h], SP
    MOV SP, AW
    ; an odd word across two registers' slots: AH and CL
    DB 26h
    MOV word [0FEFDh], 7C7Dh
    MOV [0454h], AW
    MOV [0456h], CW""")
    # 5. the segment registers' slots written as memory, then the register read and used
    #    DS0 (EE8) <- 0900h: MOV AW,DS0 and a read of DS0:[0F00h] (8F00h holds 11h, 9F00h 22h)
    L.append("""\
    DB 26h
    MOV word [0FEE8h], 0900h
    MOV AW, DS0
    MOV CL, [0F00h]
    MOV BW, 0800h
    MOV DS0, BW
    MOV [0460h], AW
    MOV [0462h], CL
    ; SS (EEA) <- 0010h: MOV AW,SS and a read of SS:[6F00h] (06F00h holds 33h, 07000h 44h)
    DB 26h
    MOV word [0FEEAh], 0010h
    MOV AW, SS
    DB 36h
    MOV CL, [6F00h]
    XOR BW, BW
    MOV SS, BW
    MOV [0464h], AW
    MOV [0466h], CL
    ; DS1 (EEE) <- 1000h: MOV AW,DS1 and a read of DS1:[0F00h] (10F00h holds 55h)
    DB 26h
    MOV word [0FEEEh], 1000h
    MOV AW, DS1
    DB 26h
    MOV CL, [0F00h]
    MOV BW, 0F000h
    MOV DS1, BW
    MOV [0468h], AW
    MOV [046Ah], CL
    ; PS (EEC) <- 0010h: execution lands at +100h if PS moves (two copies of the sled)
    DB 0EAh, 00h, 20h, 00h, 00h  ; BR far 0000:2000h""")
    L.append("ps_back:")
    L.append("    MOV AW, PS\n    MOV [0474h], AW")
    L.append("    ; PS <- 0010h, then a near branch (BR $+2): the refill's PS\n"
             "    DB 0EAh, 00h, 22h, 00h, 00h  ; BR far 0000:2200h")
    L.append("ps_back2:")
    L.append("    MOV AW, PS\n    MOV [047Ah], AW")
    # 6. the whole page as it stands (bank 7 and all), 0500h..05FFh
    L.append("""\
    MOV BW, 0FE00h
    MOV IY, 0500h
    MOV CW, 0100h
dump:
    DB 26h
    MOV AL, [BW]
    MOV [IY], AL
    INC BW
    INC IY
    DBNZ dump""")
    L.append(EPILOGUE)
    src = "\n".join(L) + "\n"
    from .asm import assemble
    # the PS sled: at 2000h and 2100h, identical but for the marker
    code = assemble(src, org=0x100)
    back = _label(src, "ps_back")
    back2 = _label(src, "ps_back2")

    def sled(marker, near=False, res=0x470, to=back):
        return f"""\
    DB 26h
    MOV word [0FEECh], 0010h
""" + "    NOP\n" * 12 + ("    DB 0EBh, 00h  ; BR $+2\n" if near else "    NOP\n    NOP\n") + \
            "    NOP\n" * 12 + f"""\
    MOV AW, PS
    MOV [{res:04X}h], AW
    MOV byte [{res + 2:04X}h], {marker:02X}h
    MOV AW, 0F000h
    MOV DS1, AW
    DB 0EAh, {to & 0xFF:02X}h, {to >> 8:02X}h, 00h, 00h  ; BR far 0000:back
"""
    data = {0x2000: assemble(sled(0xAA), org=0x2000), 0x2100: assemble(sled(0xBB), org=0x2100),
            0x2200: assemble(sled(0xAA, True, 0x476, back2), org=0x2200),
            0x2300: assemble(sled(0xBB, True, 0x476, back2), org=0x2300),
            0x8F00: b"\x11", 0x9F00: b"\x22", 0x6F00: b"\x33", 0x7000: b"\x44", 0x10F00: b"\x55"}
    return Program("f1_iram", src, data=data, results=[(RES, 0x600), (TRAPLOG, 0x10)],
                   extra_pages=(0x02, 0x06, 0x07, 0x09, 0x10),
                   note="banks 0-6 as memory; bank 7's registers by their slots; the segment "
                        "slots written as memory")


def _label(src, label):
    """The address of `label` in src assembled at 0100h (assembling up to it)."""
    from .asm import assemble
    head = src.split(f"\n{label}:")[0] + "\n"
    return 0x100 + len(assemble(head, org=0x100))


# ---- IDB relocation and RAMEN ----------------------------------------------------------
def idb_program():
    """RAMEN = 0 and the RAM's range; IDB relocated to 10h and 20h; FFFFF; the boundaries.
    DS1 = F000h, DS0 = 0800h (results 0000h-00FFh). Page FF's external RAM holds 0E0h + o at
    FFE00 + o and 0F0h ^ o at FFF00 + o (but the reset vector); page 10 and 20 likewise
    (10h ^ o, 20h ^ o) so an external read names its page."""
    L = [PRELUDE + "    DI\n"]
    L.append("    MOV AW, 0F000h\n    MOV DS1, AW\n    MOV AW, 0800h\n    MOV DS0, AW")
    L.append("""\
    MOV BW, 0FE00h
    MOV AW, 0C0C1h
    MOV CW, 0020h
pre:
    DB 26h
    MOV [BW], AW
    ADD AW, 0202h
    INC BW
    INC BW
    DBNZ pre
    ; internal RAM at E10 / E11 <- 5AA5h; IDB at FFFFF and FFF
    DB 26h
    MOV word [0FE10h], 5AA5h
    DB 26h
    MOV AL, [0FFFFh]
    MOV [0000h], AL
    ; FFFFF as SS:000F with SS = FFFFh (independent of IDB); SS back to 0 at the end
    MOV AW, 0FFFFh
    MOV SS, AW
    DB 36h
    MOV AL, [000Fh]
    MOV [0001h], AL
    ; RAMEN = 0 (PRC 0Eh): E10 read as a word, E10 written, the AW slot read; PRC read
    MOV AW, 1234h
    DB 26h
    MOV byte [0FFEBh], 0Eh
    DB 26h
    MOV CW, [0FE10h]
    MOV [0002h], CW
    DB 26h
    MOV CW, [0FEFEh]
    MOV [0004h], CW
    DB 26h
    MOV word [0FE20h], 0C3C3h
    DB 26h
    MOV CL, [0FFEBh]
    MOV [0006h], CL
    DB 26h
    MOV CW, [0FEEEh]
    MOV [0008h], CW
    DB 26h
    MOV byte [0FFEBh], 4Eh
    DB 26h
    MOV CW, [0FE10h]
    MOV [000Ah], CW
    DB 26h
    MOV CW, [0FE20h]
    MOV [000Ch], CW
    DB 26h
    MOV CW, [0FEFEh]
    MOV [000Eh], CW
    ; IDB <- 10h by a write at FFF of the page
    DB 26h
    MOV byte [0FFFFh], 10h
    DB 36h
    MOV AL, [000Fh]
    MOV [0010h], AL
    DB 26h
    MOV CW, [0FE10h]
    MOV [0012h], CW
    DB 26h
    MOV CL, [0FFEBh]
    MOV [0014h], CL
    DB 26h
    MOV CL, [0FFFFh]
    MOV [0015h], CL
    MOV BW, 1000h
    MOV DS1, BW
    DB 26h
    MOV CW, [0E10h]
    MOV [0016h], CW
    DB 26h
    MOV CW, [0EFEh]
    MOV [0018h], CW
    DB 26h
    MOV CL, [0FEBh]
    MOV [001Ah], CL
    DB 26h
    MOV CL, [0FFFh]
    MOV [001Bh], CL
    DB 26h
    MOV word [0E30h], 6996h
    DB 26h
    MOV word [0F30h], 0000h
    MOV BW, 0F000h
    MOV DS1, BW
    DB 26h
    MOV CW, [0FE30h]
    MOV [001Ch], CW
    ; a write at FFFFF with IDB = 10h: <- 20h
    DB 36h
    MOV byte [000Fh], 20h
    DB 36h
    MOV AL, [000Fh]
    MOV [0020h], AL
    MOV BW, 1000h
    MOV DS1, BW
    DB 26h
    MOV CL, [0FFFh]
    MOV [0021h], CL
    DB 26h
    MOV CW, [0E10h]
    MOV [0022h], CW
    MOV BW, 2000h
    MOV DS1, BW
    DB 26h
    MOV CL, [0FFFh]
    MOV [0024h], CL
    DB 26h
    MOV CW, [0E10h]
    MOV [0026h], CW
    DB 26h
    MOV CW, [0E30h]
    MOV [0028h], CW
    ; back to FFh: a write at FFFFF
    DB 36h
    MOV byte [000Fh], 0FFh
    DB 36h
    MOV AL, [000Fh]
    MOV [002Ah], AL
    ; (whichever page holds IDB now: FF to both relocated FFFs, external if not)
    MOV BW, 1000h
    MOV DS1, BW
    DB 26h
    MOV byte [0FFFh], 0FFh
    MOV BW, 2000h
    MOV DS1, BW
    DB 26h
    MOV byte [0FFFh], 0FFh
    MOV BW, 0F000h
    MOV DS1, BW
    DB 26h
    MOV CW, [0FE10h]
    MOV [002Ch], CW
    DB 26h
    MOV CW, [0FE30h]
    MOV [002Eh], CW
    ; the boundaries: words at DFF (external + internal), EFF (RAM + SFR), and FFF read
    DB 26h
    MOV CW, [0FDFFh]
    MOV [0030h], CW
    DB 26h
    MOV CW, [0FEFFh]
    MOV [0032h], CW
    DB 26h
    MOV word [0FDFFh], 8182h
    DB 26h
    MOV word [0FEFFh], 9394h
    DB 26h
    MOV CW, [0FE00h]
    MOV [0034h], CW
    DB 26h
    MOV CW, [0FEFEh]
    MOV [0036h], CW
    DB 26h
    MOV CW, [0FF00h]
    MOV [0038h], CW
    DB 26h
    MOV CW, [0FDFEh]
    MOV [003Ah], CW
    ; a word at FFFFE (the page's FFE and IDB)
    DB 26h
    MOV CW, [0FFFEh]
    MOV [003Ch], CW
    XOR AW, AW
    MOV SS, AW""")
    L.append(EPILOGUE)
    pff = bytearray(0x200)
    for o in range(0x100):
        pff[o] = (0xE0 + o) & 0xFF
        pff[0x100 + o] = 0xF0 ^ o
    data = {0xFFE00: bytes(pff[:0x1F0]), 0xFFFF5: bytes(pff[0x1F5:]),
            0x10E00: bytes(((0x10 ^ o) & 0xFF) for o in range(0x200)),
            0x20E00: bytes(((0x20 ^ o) & 0xFF) for o in range(0x200)),
            0xFFD00: bytes(((0xD0 + o) & 0xFF) for o in range(0x100))}
    return Program("f1_idb", "\n".join(L) + "\n", data=data,
                   results=[(RES, 0x40), (TRAPLOG, 0x10), (0xFFDF0, 0x20), (0xFFE00, 0x40),
                            (0xFFEF0, 0x20), (0x10E00, 0x40), (0x20E00, 0x40), (0x10F20, 0x20)],
                   note="RAMEN 0; IDB 10h / 20h; FFFFF; words across DFF / EFF / FFF")


# ---- the PSW ------------------------------------------------------------------------------
def psw_program():
    """PUSH PSW at reset; POP PSW / SAHF masks; LAHF; FLAG against F0 / F1; RETI into bank 6
    and back. Results by SS-prefixed stores? No: DS0 = 0800h, results 0000h-01FFh."""
    L = [PRELUDE + "    PUSH PSW\n    POP CW\n    DI\n"
         "    MOV BW, 0B0B1h\n    MOV DW, 0D0D1h\n    MOV BP, 0B2B3h\n    MOV IX, 01A1Bh\n"
         "    MOV IY, 01C1Dh\n"]
    L.append("    MOV AW, 0800h\n    MOV DS0, AW\n    MOV AW, 0F000h\n    MOV DS1, AW")
    L.append("    MOV [0000h], CW")
    k = 2
    # POP PSW with each image, PUSH PSW back (BRKI may be 0 between: no I/O here)
    for v in (0x0000, 0x0EFF, 0xF0FF, 0x0028, 0x0C55, 0x02AA, 0xF002):
        L.append(f"    MOV AW, {v:04X}h\n    PUSH AW\n    POP PSW\n    PUSH PSW\n    POP CW\n"
                 f"    MOV [{k:04X}h], CW")
        k += 2
    # SAHF with AH = 00 FF 55 AA, then LAHF and PUSH PSW (from PSW F002)
    for v in (0x00, 0xFF, 0x55, 0xAA, 0x02):
        L.append(f"    MOV AH, {v:02X}h\n    MOV PSW, AH\n    MOV AH, 00h\n    MOV AH, PSW\n"
                 f"    PUSH PSW\n    POP CW\n    MOV [{k:04X}h], AH\n    MOV [{k + 2:04X}h], CW")
        k += 4
    # FLAG (FEA) against F0 / F1
    L.append("    ; FLAG")
    for v in (0x0028, 0x0008, 0x0020, 0x0002):
        L.append(f"    MOV AW, {v:04X}h\n    PUSH AW\n    POP PSW\n    DB 26h\n    MOV AL, [0FFEAh]\n"
                 f"    MOV [{k:04X}h], AL")
        k += 1
    for v in (0xFF, 0x00, 0x08, 0x20, 0xD7, 0x28):
        L.append(f"    DB 26h\n    MOV byte [0FFEAh], {v:02X}h\n    DB 26h\n    MOV AL, [0FFEAh]\n"
                 f"    PUSH PSW\n    POP CW\n    MOV [{k:04X}h], AL\n    MOV [{k + 1:04X}h], CW")
        k += 3
    L.append("    DB 26h\n    MOV byte [0FFEAh], 00h\n    MOV AW, 0F002h\n    PUSH AW\n    POP PSW")
    # RETI into bank 6: bank 6 at EC0: AW DE, CW DC, SP D6, SS CA, DS0 C8, DS1 CE, PS CC
    k = 0x80
    L.append("""\
    ; bank 6 preset as memory (all 16 words, then the registers' values)
    MOV BW, 0FEC0h
    MOV AW, 6160h
    MOV CW, 0010h
pre6:
    DB 26h
    MOV [BW], AW
    ADD AW, 0202h
    INC BW
    INC BW
    DBNZ pre6
""" + BANK7_PRESET + """
    DB 26h
    MOV word [0FEDEh], 6A6Ah
    DB 26h
    MOV word [0FEDCh], 6C6Ch
    DB 26h
    MOV word [0FED6h], 7D00h
    DB 26h
    MOV word [0FECAh], 0000h
    DB 26h
    MOV word [0FEC8h], 0900h
    DB 26h
    MOV word [0FECEh], 0F000h
    DB 26h
    MOV word [0FECCh], 0100h
    MOV AW, 7A7Ah
    MOV CW, 7C7Ch
    ; the frame: PSW E002 (RB 6), PS 0000, PC 3000h
    MOV BW, 0E002h
    PUSH BW
    XOR BW, BW
    PUSH BW
    MOV BW, 3000h
    PUSH BW
    RETI""")
    L.append("back7:")
    L.append("    MOV [00F0h], SP\n    MOV [00F2h], AW\n    MOV [00F4h], CW")
    L.append("""\
    PUSH PSW
    POP CW
    MOV [00F6h], CW
    MOV BW, 0FEC0h
    MOV IY, 0100h
    MOV CW, 0040h
dump:
    DB 26h
    MOV AL, [BW]
    MOV [IY], AL
    INC BW
    INC IY
    DBNZ dump""")
    L.append(EPILOGUE)
    src = "\n".join(L) + "\n"
    from .asm import assemble
    back = _label(src, "back7")
    # in bank 6 (at 3000h): the PSW image, AW, CW, SP, the segments; both banks dumped; then
    # RETI back with PSW F002 to back7
    cont = """\
    PUSH PSW
    POP BW
    MOV byte [007Fh], {marker}
    MOV [0080h], BW
    MOV [0082h], AW
    MOV [0084h], CW
    MOV [0086h], SP
    MOV AW, PS
    MOV [0088h], AW
    MOV AW, SS
    MOV [008Ah], AW
    MOV AW, DS1
    MOV [008Ch], AW
    MOV BW, 0FEC0h
    MOV IY, 0090h
    MOV CW, 0040h
d6:
    DB 26h
    MOV AL, [BW]
    MOV [IY], AL
    INC BW
    INC IY
    DBNZ d6
    MOV AW, 0E1E1h
    MOV BW, 0F002h
    PUSH BW
    XOR BW, BW
    PUSH BW
    MOV BW, {back}
    PUSH BW
    RETI
"""
    # the continuation at 0000:3000h, and a copy at 0100:3000h (4000h) for a PS from bank 6's slot
    data = {0x3000: assemble(cont.format(marker="0AAh", back=f"{back:04X}h"), org=0x3000),
            0x4000: assemble(cont.format(marker="0BBh", back=f"{back:04X}h"), org=0x3000)}
    return Program("f1_psw", src, data=data,
                   results=[(RES, 0x140), (0x9000, 0xD0), (TRAPLOG, 0x10), (0x7CF0, 0x10)],
                   extra_pages=(0x03, 0x04),
                   note="PSW at reset, POP PSW / SAHF masks, LAHF, FLAG, RETI into bank 6 and back")


# ---- BRKI = 0: IN / OUT trap to vector 19 (socket only: F2's build) ------------------------
def brki_program():
    """Vector 19 points at a handler (0000:3800h) that records the frame (PC, PS, PSW), sets
    BRKI in the saved PSW and returns, so the trapping instruction's re-execution (or not)
    shows. SAHF 00 then IN AL,22h; SAHF 00 then OUT 22h,AL; POP PSW 0000 then OUT DW,AW."""
    L = [PRELUDE + "    DI\n"]
    L.append("    MOV AW, 0800h\n    MOV DS0, AW\n    MOV word [0000h], 0000h")
    L.append("""\
    ; 1. SAHF 00 then IN at once
    MOV AL, 11h
    MOV AH, 00h
    MOV PSW, AH
    IN AL, 22h
    MOV [0010h], AL
    MOV AH, 02h
    MOV PSW, AH
    ; 2. SAHF 00, NOP, IN
    MOV AL, 12h
    MOV AH, 00h
    MOV PSW, AH
    NOP
    IN AL, 22h
    MOV [0011h], AL
    MOV AH, 02h
    MOV PSW, AH
    ; 3. SAHF 00 then OUT at once
    MOV AL, 33h
    MOV AH, 00h
    MOV PSW, AH
    OUT 22h, AL
    MOV AH, 02h
    MOV PSW, AH
    ; 4. SAHF 00, NOP, OUT
    MOV AL, 34h
    MOV AH, 00h
    MOV PSW, AH
    NOP
    OUT 22h, AL
    MOV AH, 02h
    MOV PSW, AH
    ; 5. POP PSW 0000, IN AW,DW at once
    MOV DW, 0024h
    MOV AW, 0000h
    PUSH AW
    POP PSW
    IN AW, DW
    MOV [0012h], AW
    MOV AH, 02h
    MOV PSW, AH
    ; 6. POP PSW 0000, OUT DW,AW at once
    MOV AW, 0000h
    PUSH AW
    MOV AW, 4455h
    POP PSW
    OUT DW, AW
    PUSH PSW
    POP CW
    MOV [0014h], CW""")
    L.append(EPILOGUE)
    handler = """\
    PUSH AW
    PUSH BP
    PUSH BW
    PUSH IX
    MOV BP, SP
    MOV BW, [0000h]
    MOV IX, BW
    ADD IX, IX
    ADD IX, IX
    ADD IX, IX
    ADD IX, 0020h
    MOV AW, [BP+8]
    MOV [IX], AW
    MOV AW, [BP+10]
    MOV [IX+2], AW
    MOV AW, [BP+12]
    MOV [IX+4], AW
    MOV [IX+6], SP
    INC BW
    MOV [0000h], BW
    OR word [BP+12], 0002h
    POP IX
    POP BW
    POP BP
    POP AW
    RETI
"""
    from .asm import assemble
    ivt = bytearray(ivt_segment())
    ivt[19 * 4:19 * 4 + 4] = bytes([0x00, 0x38, 0x00, 0x00])
    return Program("f1_brki", "\n".join(L) + "\n",
                   data={0x0000: bytes(ivt), 0x3800: assemble(handler, org=0x3800)},
                   results=[(RES, 0x80), (TRAPLOG, 0x10)], extra_pages=(0x03,), gate=False,
                   note="BRKI 0: IN / OUT trap to vector 19 (measured for F2; not in the F1 gate)")


def programs():
    return {
        "f1_sfr_doc": sfr_program("f1_sfr_doc", documented_writable(), words=True,
                                  note="the page at reset (bytes, words); the documented SFRs "
                                       "written 00 FF 55 AA and read back; the 16-bit ones by word"),
        "f1_sfr_undoc": sfr_program("f1_sfr_undoc", undocumented(),
                                    note="the page at reset; the undocumented offsets written "
                                         "00 FF 55 AA and read back"),
        "f1_iram": iram_program(),
        "f1_idb": idb_program(),
        "f1_psw": psw_program(),
        "f1_brki": brki_program(),
        "f1_sfr_all": sfr_all_program(),
    }



# ---- every value into the registers whose four patterns left a bit unexplained ---------------
ALL_VALUES = (0x68, 0x78, 0x90, 0x91, 0xA0, 0x40, 0x4C, 0x6C, 0xAC, 0xEC)


def sfr_all_program():
    """Each of ALL_VALUES' offsets written 00..FF (IC registers: MK kept set, so no request)
    and read back after each write: 256 bytes per register at 0000h + 100h * k (DS0 = 0800h,
    DS1 = F000h); the register restored to its value before."""
    L = [PRELUDE + "    DI\n"]
    L.append("    MOV AW, 0F000h\n    MOV DS1, AW\n    MOV AW, 0800h\n    MOV DS0, AW")
    for k, o in enumerate(ALL_VALUES):
        force = 0x40 if o in IC_REGS else 0x00
        L.append(f"""\
    ; {o:02X} {SFR[o][0]}
    DB 26h
    MOV DL, [0FF{o:02X}h]
    MOV BW, 0FF{o:02X}h
    MOV IY, {0x100 * k:04X}h
    MOV CW, 0100h
    XOR AL, AL
a{k}:
    MOV AH, AL
    OR AL, {force:02X}h
    DB 26h
    MOV [BW], AL
    DB 26h
    MOV AL, [BW]
    MOV [IY], AL
    INC IY
    MOV AL, AH
    INC AL
    DBNZ a{k}
    DB 26h
    MOV [BW], DL""")
    L.append(EPILOGUE)
    return Program("f1_sfr_all", "\n".join(L) + "\n",
                   results=[(RES, 0x100 * len(ALL_VALUES)), (TRAPLOG, 0x10)],
                   note="SCM0/1, TMC0/1, DMAC0, INTM and four IC registers written every value")

# ------------------------------------------------------------------ running
def _write_sequence(trace_rows):
    from .runner import FLAG_COL_A9, FLAG_IO, FLAG_READ, FLAG_STROBE
    return [[t["address"], t["data"], t["flags"] & ~FLAG_COL_A9] for t in trace_rows
            if t["flags"] & FLAG_STROBE and (t["flags"] & FLAG_IO or not t["flags"] & FLAG_READ)]


def _io_reads(trace_rows):
    from .runner import FLAG_IO, FLAG_READ, FLAG_STROBE
    return [[t["address"], t["data"]] for t in trace_rows
            if t["flags"] & FLAG_STROBE and t["flags"] & FLAG_IO and t["flags"] & FLAG_READ]


def run_one(harness, prog: Program, lane: str, limit=20_000_000):
    code, segments, pages = prog.image()
    harness.load(segments, pages)
    mode = "socket" if lane == "socket" else "model"
    # as Harness.run_complete, but every window is read also when the run fails (a timeout's
    # trace shows where it stopped), and a window whose total or signature differs is
    # recorded, not fatal
    result = harness.run(mode, limit)
    trace = list(result[f"{lane}_trace"])
    replay = []
    total = result[f"{lane}_total"]
    for start in range(2048, total, 2048):
        harness.load(segments, pages)
        window = harness.run(mode, limit, capture_start=start)
        for field in ("total", "signature"):
            if window[f"{lane}_{field}"] != result[f"{lane}_{field}"]:
                replay.append(f"{field} changed at window {start}: "
                              f"{result[f'{lane}_{field}']} -> {window[f'{lane}_{field}']}")
        trace.extend(window[f"{lane}_trace"])
    regions = {}
    for address, length in prog.results:
        regions[f"{address:05X}"] = harness.read_memory(lane, address, length).hex()
    # memory reads of the data area (not fetches: the V35 has no status; addresses outside the
    # code segment) are recorded too, for the on-chip / external decision
    from .runner import FLAG_IO, FLAG_READ, FLAG_STROBE
    code_end = 0x100 + len(code)
    ext_reads = [[t["address"], t["data"]] for t in trace
                 if t["flags"] & FLAG_STROBE and t["flags"] & FLAG_READ
                 and not t["flags"] & FLAG_IO
                 and not (0x100 <= t["address"] < code_end + 8)
                 and not (0xFFFF0 <= t["address"] <= 0xFFFFF)
                 and not any(a <= t["address"] < a + len(d) + 8 for a, d in segments.items()
                             if a in (0x2000, 0x2100, 0x3000, 0x3800))]
    return {
        "program": prog.name, "note": prog.note, "gate": prog.gate,
        "program_sha256": hashlib.sha256(code).hexdigest(),
        "image_sha256": hashlib.sha256(json.dumps({f"{a:05X}": d.hex() for a, d in
                                                   sorted(segments.items())}).encode()).hexdigest(),
        "passed": result["passed"], "status": result["status"],
        "timeout": result["timeout"], "total": result[f"{lane}_total"],
        "markers": result["markers"], "last_marker": result["last_marker"],
        "writes": _write_sequence(trace), "io_reads": _io_reads(trace),
        "data_reads": ext_reads, "regions": regions, "replay": replay,
        "trace_tail": [[t["address"], t["data"], t["flags"]] for t in trace[-24:]],
    }


def run_socket(names, tag=""):
    from .runner import open_board
    progs = programs()
    transport, harness, state = open_board(True)
    out = []
    try:
        harness.strict = False
        harness.configure(x_half=2)
        transport.vccb_enable()
        harness.arm()
        time.sleep(0.05)
        for name in names:
            rec = run_one(harness, progs[name], "socket")
            rec.update(backend="socket", cpu="uPD70337L-8", x_half=2,
                       date=datetime.datetime.now().isoformat(timespec="seconds"))
            save(rec, name, "socket" + tag)
            out.append(rec)
            print(f"{name}: socket {'PASS' if rec['passed'] else 'FAIL'} status=0x{rec['status']:04x} "
                  f"writes={len(rec['writes'])} total={rec['total']}", flush=True)
    finally:
        try:
            harness.arm(False)
            transport.power_off()
        finally:
            transport.close()
    return out


def run_sim(names, tag=""):
    from .chains.acquire import sim_transport
    from .runner import Harness
    from nuboard.debug import DebugClient
    progs = programs()
    out = []
    for name in names:
        transport = sim_transport("v35")
        try:
            harness = Harness(DebugClient(transport.exchange), strict=False)
            harness.configure(x_half=2)
            rec = run_one(harness, progs[name], "model")
        finally:
            transport.close()
        rec.update(backend="sim", core="v35",
                   binary=os.environ.get("V35_SIM_BINARY", "build/fpga/v35s/verilator-direct-v35"),
                   date=datetime.datetime.now().isoformat(timespec="seconds"))
        save(rec, name, "sim" + tag)
        out.append(rec)
        print(f"{name}: sim {'PASS' if rec['passed'] else 'FAIL'} status=0x{rec['status']:04x} "
              f"writes={len(rec['writes'])} total={rec['total']}", flush=True)
    return out


def receipt_path(name, backend):
    return RECEIPTS / f"f1-{name}-{backend}.json"


def save(rec, name, backend):
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    receipt_path(name, backend).write_text(json.dumps(rec, indent=1) + "\n")


def load(name, backend):
    return json.loads(receipt_path(name, backend).read_text())


def compare(names, ref="socket", cand="sim"):
    ok_all = True
    for name in names:
        a, b = load(name, ref), load(name, cand)
        same_w = a["writes"] == b["writes"]
        same_r = a["regions"] == b["regions"]
        same_io = a["io_reads"] == b["io_reads"]
        ok = same_w and same_r and a["passed"] == b["passed"]
        ok_all &= ok or not a["gate"]
        print(f"{name}: {'EQUAL' if ok else 'DIFFER'} writes {len(a['writes'])}/{len(b['writes'])}"
              f"{'' if same_w else ' (differ)'} regions {'equal' if same_r else 'differ'}"
              f" io_reads {'equal' if same_io else 'differ'}"
              f" passed {a['passed']}/{b['passed']}{'' if a['gate'] else ' (not gated)'}")
        if not same_w:
            for i, (x, y) in enumerate(zip(a["writes"], b["writes"])):
                if x != y:
                    print(f"  first write difference at {i}: {ref} {x[0]:05X} {x[1]:04X} {x[2]:03X}"
                          f" / {cand} {y[0]:05X} {y[1]:04X} {y[2]:03X}")
                    break
        for key in a["regions"]:
            ra, rb = bytes.fromhex(a["regions"][key]), bytes.fromhex(b["regions"].get(key, ""))
            diffs = [i for i in range(len(ra)) if i >= len(rb) or ra[i] != rb[i]]
            if diffs:
                base = int(key, 16)
                show = ", ".join(f"{base + i:05X}:{ra[i]:02X}/{rb[i] if i < len(rb) else -1:02X}"
                                 for i in diffs[:12])
                print(f"  region {key}: {len(diffs)} bytes differ: {show}")
    return ok_all



# ------------------------------------------------------------------ the gate's exclusions
# Bytes of the result pages that F1 does not build, each with its reason (README "F1"):
#   residue   silicon returns the internal bus's last byte (the code stream's: a timing
#             artifact): the write-only SFRs, the undocumented offsets with address bit 2 clear,
#             a byte read of a 16-bit register's high half, and the word reads that contain one
#   live      a peripheral's or a hidden register's state moving under the program (F4's): FF7,
#             FF8, FF9; TM0 / TM1 low byte and RxB0 / RxB1 (undefined at reset: kept through
#             reset on silicon, different between runs); the interrupt request flags (bit 7) of
#             STIC0 / STIC1 / TBIC once the sweep has started the transmitters and the time base
#   bus       (f1_iram) the PS sled after a near branch: the RTL's refill uses the PS flop, which
#             an on-chip write to the PS slot does not update (silicon refetches from the slot)
RESIDUE = {o for o in range(256)
           if (o in SFR and o in (0x01, 0x02, 0x09, 0x0A, 0x11, 0x12, 0x62, 0x72, 0x81, 0x83,
                                  0x89, 0x8B))
           or (o not in SFR and not o & 4 and o not in (0xF0, 0xF1))
           or o in (0xF5, 0xF6, 0xFD, 0xFE)}
LIVE = {0xF7, 0xF8, 0xF9, 0x80, 0x88, 0x60, 0x70}


def excluded(name):
    """The result-page addresses (absolute) the gate ignores for program `name`."""
    ex = set()
    if name in ("f1_sfr_doc", "f1_sfr_undoc"):
        for o in RESIDUE | LIVE:
            ex.add(RES + o)
            ex |= {RES + 0x100 + (o & ~1), RES + 0x101 + (o & ~1)}
            ex |= {RES + 0x200 + 8 * o + k for k in range(5)}
            ex.add(RES + 0xB00 + o)
        for o in (0x6E, 0x7E, 0xEC):
            ex |= {RES + 0xB00 + o, RES + 0x200 + 8 * o}
        # the 16-bit registers' word sweep: TM0 / TM1 before (undefined at reset)
        ex |= {RES + 0xA00, RES + 0xA01, RES + 0xA20, RES + 0xA21}
        # the pass marker's high lane (OUT DW,AL drives AH there): AH holds the last swept
        # offset's value before, FFE's residue
        ex.add(0xFF01)
    if name == "f1_iram":
        ex |= {RES + 0x478}
    if name == "f1_idb":
        ex |= {RES + 0x3C}          # the word at FFFFE: FFE's residue
    return ex


def _masked_writes(writes, ex):
    out = []
    for address, data, flags in writes:
        if address & 1:
            lanes = [(address, 8)]
        elif flags & 0x08:          # /UBE high: the low byte only
            lanes = [(address, 0)]
        else:
            lanes = [(address, 0), (address + 1, 8)]
        for a, sh in lanes:
            if a in ex:
                data &= ~(0xFF << sh)
        out.append([address, data, flags])
    return out


def compare_gate(names, ref="socket", cand="sim"):
    """The F1 gate: the write and I/O sequence and the result pages equal, the exclusions'
    bytes masked (excluded())."""
    ok_all = True
    for name in names:
        a, b = load(name, ref), load(name, cand)
        ex = excluded(name)
        wa, wb = _masked_writes(a["writes"], ex), _masked_writes(b["writes"], ex)
        diffs = []
        for key in a["regions"]:
            base = int(key, 16)
            ra, rb = bytes.fromhex(a["regions"][key]), bytes.fromhex(b["regions"].get(key, ""))
            diffs += [(base + i, ra[i], rb[i] if i < len(rb) else -1) for i in range(len(ra))
                      if base + i not in ex and (i >= len(rb) or ra[i] != rb[i])]
        ok = wa == wb and not diffs and a["passed"] == b["passed"]
        ok_all &= ok
        first = next((i for i, (x, y) in enumerate(zip(wa, wb)) if x != y), None)
        print(f"{name}: gate {'EQUAL' if ok else 'DIFFER'} (excluded {len(ex)} bytes) writes "
              f"{len(wa)}/{len(wb)}" + ("" if first is None else
              f" first difference at {first}: {wa[first][0]:05X} {wa[first][1]:04X} / "
              f"{wb[first][0]:05X} {wb[first][1]:04X}") +
              ("" if not diffs else " result bytes differ: " +
               ", ".join(f"{x:05X}:{y:02X}/{z:02X}" for x, y, z in diffs[:16])
               + (f" (+{len(diffs) - 16})" if len(diffs) > 16 else "")))
    return ok_all

# ------------------------------------------------------------------ the SFR table
def sfr_table(backend="socket"):
    """Per offset: the reset value (twice: both sweep programs), the four read-backs, the
    write mask (bits that read back as written over 00/FF/55/AA), the restored value."""
    doc = load("f1_sfr_doc", backend)
    und = load("f1_sfr_undoc", backend)
    rows = []
    for o in range(256):
        rec = doc if o in SFR else und
        reg = bytes.fromhex(rec["regions"][f"{RES:05X}"])
        reset = reg[o]
        reset2 = bytes.fromhex((und if o in SFR else doc)["regions"][f"{RES:05X}"])[o]
        after = reg[0xB00 + o]
        if o in NO_WRITE:
            rows.append((o, reset, reset2, None, None, None, after))
            continue
        e = reg[0x200 + 8 * o:0x200 + 8 * o + 5]
        before, reads = e[0], list(e[1:5])
        writes = [sweep_value(o, p) for p in PATTERNS]
        ones = zeros = 0
        for w, r in zip(writes, reads):
            ones |= w & r
            zeros |= ~w & ~r & 0xFF
        # a bit is writable when it followed every pattern
        mask = 0
        for bit in range(8):
            m = 1 << bit
            if all((w & m) == (r & m) for w, r in zip(writes, reads)):
                mask |= m
        rows.append((o, reset, reset2, before, reads, mask, after))
    return rows


def print_table(backend="socket"):
    rows = sfr_table(backend)
    print("| off | name | book | reset | reset (2nd run) | 00 FF 55 AA read | writable bits | after |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for o, reset, reset2, before, reads, mask, after in rows:
        name, rw, book = SFR.get(o, ("-", "-", None))
        b = "-" if book is None else f"{book:02X}"
        if reads is None:
            r, m = "(not written)", "-"
        else:
            r = " ".join(f"{x:02X}" for x in reads)
            m = f"{mask:02X}"
        print(f"| F{o:02X} | {name} {rw} | {b} | {reset:02X} | {reset2:02X} | {r} | {m} | {after:02X} |")


def emit():
    for name, prog in programs().items():
        path = PROGRAMS_DIR / f"{name}.s"
        path.write_text(f"; F1 ({prog.note}). Generated by validation/v35s/onchip.py emit: the\n"
                        f"; image also preloads the vector stubs and the data in onchip.py.\n"
                        + prog.source)
        print(path)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "compare", "gate", "table", "emit"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    a = p.parse_args()
    names = a.names or [n for n, prog in programs().items()
                        if a.action == "socket" or prog.gate]
    if a.action == "socket":
        run_socket(names, a.tag)
    elif a.action == "sim":
        run_sim(names, a.tag)
    elif a.action == "compare":
        return 0 if compare(names, a.ref, a.cand) else 1
    elif a.action == "gate":
        return 0 if compare_gate(names, a.ref, a.cand) else 1
    elif a.action == "table":
        print_table(a.ref)
    else:
        emit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
