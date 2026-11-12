"""The register-bank and SFR dump routine for V35S programs, and its reader.

A program writes `DUMPSTATE` (optionally `DUMPSTATE P0, PM0, INTM`) on a line
of its own; validation.v35s.asm expands it to `routine(...)` below. The
routine copies the eight register banks (IDB:E00-EFF) and the listed SFRs to
external memory, where the runner reads both lanes and names the values:

    00800-008FF  the banks: bank n at 0800 + 20h * n, in the data book's
                 layout (BANK_LAYOUT); the bank in use holds the caller's
                 registers as they were at DUMPSTATE
    00900-009FF  SFR at IDB:F00 + offset -> 00900 + offset, listed SFRs only
                 (the others stay as the program left them, normally zero)
    00A00        IDB (read at FFFFFh)
    00A02-00A0D  the caller's AW, CW, IX, IY, DS0, DS1 (the routine's scratch)
    00A0E        the caller's PSW

Requirements and effects: PS must be 0000 (the routine addresses its region
through a PS: override, as a program loaded by runner.reset_image runs), and
SS:SP must point at writable memory: PUSH PSW writes the two bytes below SP.
Every register and the PSW are restored on exit; the stack bytes below SP
are left changed. DW, BW, BP and SP are never touched.

The data book is the 1991 V-Series book (docs/v35s-differences.md cites the
lines): bank layout L104042-104106, PSW RB2-0 in bits 14:12 L104124-104255,
SFR map Table 6 L108620-109375.
"""

from __future__ import annotations

import struct

DUMP_BASE = 0x00800
BANKS = DUMP_BASE              # 256 bytes
SFRS = DUMP_BASE + 0x100       # 256 bytes, by SFR offset
META = DUMP_BASE + 0x200       # IDB, saved registers, PSW
DUMP_LENGTH = 0x210

# Offset of each register in a 32-byte bank ([DB] L104042-104106).
BANK_LAYOUT = {
    "VECTOR_PC": 0x02, "PSW_SAVE": 0x04, "PC_SAVE": 0x06, "DS0": 0x08, "SS": 0x0A,
    "PS": 0x0C, "DS1": 0x0E, "IY": 0x10, "IX": 0x12, "BP": 0x14, "SP": 0x16,
    "BW": 0x18, "DW": 0x1A, "CW": 0x1C, "AW": 0x1E,
}

# The SFR page (offset from IDB:F00, [DB] Table 6). Word registers name
# their low byte; TM0/TM1/MD0/MD1 and WTC are 16 bits wide.
SFR = {
    "P0": 0x00, "PM0": 0x01, "PMC0": 0x02, "P1": 0x08, "PM1": 0x09, "PMC1": 0x0A,
    "P2": 0x10, "PM2": 0x11, "PMC2": 0x12, "PT": 0x38, "PMT": 0x3B,
    "INTM": 0x40, "EMS0": 0x44, "EMS1": 0x45, "EMS2": 0x46,
    "EXIC0": 0x4C, "EXIC1": 0x4D, "EXIC2": 0x4E,
    "RXB0": 0x60, "TXB0": 0x62, "SRMS0": 0x65, "STMS0": 0x66, "SCM0": 0x68,
    "SCC0": 0x69, "BRG0": 0x6A, "SCE0": 0x6B, "SEIC0": 0x6C, "SRIC0": 0x6D,
    "STIC0": 0x6E,
    "RXB1": 0x70, "TXB1": 0x72, "SRMS1": 0x75, "STMS1": 0x76, "SCM1": 0x78,
    "SCC1": 0x79, "BRG1": 0x7A, "SCE1": 0x7B, "SEIC1": 0x7C, "SRIC1": 0x7D,
    "STIC1": 0x7E,
    "TM0": 0x80, "MD0": 0x82, "TM1": 0x88, "MD1": 0x8A, "TMC0": 0x90, "TMC1": 0x91,
    "TMMS0": 0x94, "TMMS1": 0x95, "TMMS2": 0x96, "TMIC0": 0x9C, "TMIC1": 0x9D,
    "TMIC2": 0x9E,
    "DMAC0": 0xA0, "DMAM0": 0xA1, "DMAC1": 0xA2, "DMAM1": 0xA3, "DIC0": 0xAC, "DIC1": 0xAD,
    "STBC": 0xE0, "RFM": 0xE1, "WTC": 0xE8, "FLAG": 0xEA, "PRC": 0xEB, "TBIC": 0xEC,
    "ISPR": 0xFC, "IDB": 0xFF,
}
WORD_SFRS = {"TM0", "MD0", "TM1", "MD1", "WTC"}

# The default list: configuration and interrupt-control registers whose read
# has no side effect and does not depend on when it lands. Receive buffers,
# timer counts and the serial status registers are left for a program to
# list explicitly.
DEFAULT_SFRS = (
    "PM0", "PMC0", "PM1", "PMC1", "PM2", "PMC2", "PMT",
    "INTM", "EMS0", "EMS1", "EMS2", "EXIC0", "EXIC1", "EXIC2",
    "SCM0", "SCC0", "BRG0", "SEIC0", "SRIC0", "STIC0",
    "SCM1", "SCC1", "BRG1", "SEIC1", "SRIC1", "STIC1",
    "MD0", "MD1", "TMC0", "TMC1", "TMMS0", "TMMS1", "TMMS2", "TMIC0", "TMIC1", "TMIC2",
    "DMAM0", "DMAM1", "DMAC0", "DMAC1", "DIC0", "DIC1",
    "STBC", "RFM", "WTC", "FLAG", "PRC", "TBIC", "ISPR", "IDB",
)

# The caller's registers the routine uses, and their slots in META.
_SAVED = (("AW", 0x02), ("CW", 0x04), ("IX", 0x06), ("IY", 0x08), ("DS0", 0x0A),
          ("DS1", 0x0C))


def _sfr_bytes(names):
    offsets = []
    for name in names:
        key = name.strip().upper()
        if key not in SFR:
            raise ValueError(f"unknown SFR {name!r}")
        offsets.append(SFR[key])
        if key in WORD_SFRS:
            offsets.append(SFR[key] + 1)
    return sorted(set(offsets))


def routine(sfrs=DEFAULT_SFRS) -> str:
    """NEC-syntax source of the dump routine (no labels, no branches)."""
    ps = "    DB 2Eh                 ; PS: override"
    lines = ["; ---- DUMPSTATE (validation/v35s/dump.py)"]
    for register, slot in _SAVED:
        lines += [ps, f"    MOV [{META + slot:04X}h], {register}"]
    lines += [
        "    PUSH PSW",
        "    POP AW",
        ps, f"    MOV [{META + 0x0E:04X}h], AW",
        "    MOV AW, 0FFFFh",
        "    MOV DS0, AW",
        "    MOV AL, [000Fh]        ; IDB at FFFFFh",
        ps, f"    MOV [{META:04X}h], AL",
        "    MOV AH, AL",
        "    MOV AL, 0",
        "    MOV DS0, AW            ; DS0:0E00 = IDB:E00",
        "    XOR AW, AW",
        "    MOV DS1, AW",
        "    MOV IX, 0E00h",
        f"    MOV IY, {BANKS:04X}h",
        "    MOV CW, 0080h",
        "    CLR1 DIR",
        "    REP",
        "    MOVBKW                 ; the eight banks",
    ]
    for offset in _sfr_bytes(sfrs):
        lines += [f"    MOV AL, [{0xF00 + offset:04X}h]", ps,
                  f"    MOV [{SFRS + offset:04X}h], AL"]
    # The bank in use holds the routine's scratch: put the caller's back.
    lines += [
        ps, f"    MOV AW, [{META + 0x0E:04X}h]",
        "    MOV CL, 7",
        "    SHR AW, CL",
        "    AND AW, 00E0h          ; RB * 20h",
        f"    ADD AW, {BANKS:04X}h",
        "    MOV IX, AW",
    ]
    for register, slot in _SAVED:
        lines += [ps, f"    MOV AW, [{META + slot:04X}h]", ps,
                  f"    MOV [IX+{BANK_LAYOUT[register]:02X}h], AW"]
    for register, slot in reversed(_SAVED):
        lines += [ps, f"    MOV {register}, [{META + slot:04X}h]"]
    lines += [ps, f"    PUSH word [{META + 0x0E:04X}h]", "    POP PSW",
              "; ---- end DUMPSTATE"]
    return "\n".join(lines) + "\n"


def decode(raw: bytes, sfrs=DEFAULT_SFRS) -> dict:
    """Name a dump region (DUMP_LENGTH bytes read from DUMP_BASE)."""
    if len(raw) < DUMP_LENGTH:
        raise ValueError("short dump region")
    banks = []
    for bank in range(8):
        base = bank * 0x20
        banks.append({name: struct.unpack_from("<H", raw, base + offset)[0]
                      for name, offset in BANK_LAYOUT.items()})
    named = {}
    for name in sfrs:
        key = name.strip().upper()
        offset = 0x100 + SFR[key]
        named[key] = (struct.unpack_from("<H", raw, offset)[0] if key in WORD_SFRS
                      else raw[offset])
    psw = struct.unpack_from("<H", raw, 0x20E)[0]
    return {"banks": banks, "sfr": named, "idb": raw[0x200], "psw": psw,
            "bank": (psw >> 12) & 7,
            "saved": {register: struct.unpack_from("<H", raw, 0x200 + slot)[0]
                      for register, slot in _SAVED}}


def read(harness, lane: str, sfrs=DEFAULT_SFRS) -> dict:
    """Read and name one lane's dump after a run."""
    return decode(harness.read_memory(lane, DUMP_BASE, DUMP_LENGTH), sfrs)


def differences(left: dict, right: dict) -> list[str]:
    """Named fields that differ between two decoded dumps."""
    out = []
    for bank, (a, b) in enumerate(zip(left["banks"], right["banks"])):
        out += [f"bank{bank}.{name}" for name in a if a[name] != b[name]]
    out += [f"sfr.{name}" for name in left["sfr"] if left["sfr"][name] != right["sfr"].get(name)]
    out += [name for name in ("idb", "psw") if left[name] != right[name]]
    return out
