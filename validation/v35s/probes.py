"""Phase-1 case suites for the timing window in timing.py.

Each suite returns timing.Case objects. A form whose target has an odd
length runs at both placements (timing.analyse takes the mean); an
even-length form reads exactly at one placement, so it runs once.

    regs       M3  the same operation through different register paths
    ea         M4  every mod/rm memory form, odd addresses, segment prefixes
    data       M5  data-dependent forms: MUL/DIV operands, shift counts,
                   REP counts, PREPARE levels, bit-field widths, BCD
    iram       M8  data access to internal RAM and SFRs, registers seen as
                   RAM, IDB relocation (run again with --prc 0C for RAMEN = 0)
    psw        M9  PSW masks, BRKI trap, LAHF/SAHF, RETI with RB
    undefined  M9  0F holes, FPO escapes, BRKN; every vector reports itself
    ext, mul, banks, undefined2   Phase 1 follow-ups: EXT/INS offset x width,
               a denser signed-multiply grid, forms in every register bank,
               and what drives the undefined 0F read-modify-write
    release, held, tail, eu, follow   Phase 2 queue probes; eu times the
               EU with an OUT after k instructions of a train, follow puts
               each follower after a one-word leader, stall puts a bus
               cycle or a long instruction into a train; regform runs
               every register-form ModR/M instruction at both placements

Functional cases dump values with OUT 22h,AW; trap stubs report on port 24h
(timing.TRAP_PORT). Both show up in each run's io list.
"""

from __future__ import annotations

from .asm import assemble
from .timing import Case

DUMP = [0xE7, 0x22]          # OUT 22h, AW

# Data addresses inside the image's 0x0800-0x0FFF fill (DS0 = SS = 0).
EA_REGS = {"BW": 0x0840, "BP": 0x0860, "IX": 0x0100, "IY": 0x0200}


def _length(target: str) -> int:
    return len(assemble(target.format(seg="1000", next="1234"), org=0x100))


def form(suite, name, code, regs=None, ram=None, vector=None, stubs=False, both=False):
    """Cases for one form. code is a byte list or assembly text."""
    target = code if isinstance(code, str) else "    DB " + ", ".join(f"0x{b:02X}" for b in code)
    length = _length(target)
    placements = (False, True) if length & 1 or both else (False,)
    return [Case(name=name, target=target, regs=dict(regs or {}), ram=dict(ram or {}), odd=odd,
                 vector=vector, stubs=stubs, group=name, suite=suite, form=name)
            for odd in placements]


# --- M3: register paths ---------------------------------------------------

def regs_cases():
    rows = [
        ("INC AW (40)", [0x40]), ("INC AW (FF /0)", [0xFF, 0xC0]), ("INC AL (FE /0)", [0xFE, 0xC0]),
        ("INC AH (FE /0)", [0xFE, 0xC4]), ("INC CW (41)", [0x41]), ("INC IY (47)", [0x47]),
        ("INC CW (FF /0)", [0xFF, 0xC1]), ("DEC AW (48)", [0x48]), ("DEC AW (FF /1)", [0xFF, 0xC8]),
        ("PUSH AW (50)", [0x50]), ("PUSH AW (FF /6)", [0xFF, 0xF0]),
        ("POP AW (58)", [0x58]), ("POP AW (8F /0)", [0x8F, 0xC0]),
        ("PUSH DS0", [0x1E]), ("POP DS1", [0x07]),
        ("XCH AW,CW (91)", [0x91]), ("XCH AW,CW (87 rm=AW)", [0x87, 0xC8]),
        ("XCH CW,AW (87 rm=CW)", [0x87, 0xC1]), ("XCH AL,CL (86)", [0x86, 0xC1]),
        ("MOV AW,CW (8B)", [0x8B, 0xC1]), ("MOV CW,AW (89)", [0x89, 0xC1]),
        ("MOV AL,CL (8A)", [0x8A, 0xC1]), ("MOV AH,CH (8A)", [0x8A, 0xE5]),
        ("MOV AL,CH (8A)", [0x8A, 0xC5]), ("MOV IY,IX (8B)", [0x8B, 0xFE]),
        ("MOV AW,SP (8B)", [0x8B, 0xC4]),
        ("MOV AW,imm (B8)", [0xB8, 0x34, 0x12]), ("MOV AW,imm (C7)", [0xC7, 0xC0, 0x34, 0x12]),
        ("MOV CW,imm (B9)", [0xB9, 0x34, 0x12]),
        ("MOV AL,imm (B0)", [0xB0, 0x12]), ("MOV AL,imm (C6)", [0xC6, 0xC0, 0x12]),
        ("MOV BH,imm (B7)", [0xB7, 0x12]),
        ("ADD AL,imm (04)", [0x04, 0x12]), ("ADD AL,imm (80)", [0x80, 0xC0, 0x12]),
        ("ADD AW,imm (05)", [0x05, 0x34, 0x12]), ("ADD AW,imm (81)", [0x81, 0xC0, 0x34, 0x12]),
        ("ADD AW,imm8 (83)", [0x83, 0xC0, 0x12]), ("ADD CW,imm (81)", [0x81, 0xC1, 0x34, 0x12]),
        ("ADD CW,imm8 (83)", [0x83, 0xC1, 0x12]),
        ("ADD AW,CW (03)", [0x03, 0xC1]), ("ADD AW,CW (01)", [0x01, 0xC8]),
        ("ADD AL,CL (02)", [0x02, 0xC1]), ("ADD AH,CH (02)", [0x02, 0xE5]),
        ("CMP AW,CW (3B)", [0x3B, 0xC1]), ("CMP AL,imm (3C)", [0x3C, 0x12]),
        ("TEST AW,CW (85)", [0x85, 0xC1]), ("TEST AL,CL (84)", [0x84, 0xC1]),
        ("TEST AL,imm (A8)", [0xA8, 0x12]), ("TEST AL,imm (F6)", [0xF6, 0xC0, 0x12]),
        ("TEST AW,imm (A9)", [0xA9, 0x34, 0x12]), ("TEST AW,imm (F7)", [0xF7, 0xC0, 0x34, 0x12]),
        ("NOT AW", [0xF7, 0xD0]), ("NEG AW", [0xF7, 0xD8]), ("NOT AL", [0xF6, 0xD0]),
        ("MOV AW,DS0 (8C)", [0x8C, 0xD8]), ("MOV AW,SS (8C)", [0x8C, 0xD0]),
        ("MOV DS1,AW (8E)", [0x8E, 0xC0]), ("MOV DS0,AW (8E)", [0x8E, 0xD8]),
        ("LDEA AW,[BW]", [0x8D, 0x07]), ("LDEA AW,[BW+IX+disp8]", [0x8D, 0x40, 0x10]),
        ("CVTBW", [0x98]), ("CVTWL", [0x99]), ("CLR1 CY", [0xF8]), ("NOT1 CY", [0xF5]),
        ("NOP NOP", [0x90, 0x90]),
    ]
    regs = {"AW": 0x0012, "CW": 0x0034, "SP": 0x0F00}
    cases = []
    for name, code in rows:
        cases += form("regs", name, code, regs)
    return cases


# --- M4: effective addresses ----------------------------------------------

def _ea_bytes(mod, rm):
    disp = {0: [0x34, 0x12] if rm == 6 else [], 1: [0x10], 2: [0x10, 0x01]}[mod]
    if mod == 0 and rm == 6:
        disp = [0x80, 0x08]
    return disp


RM = ("BW+IX", "BW+IY", "BP+IX", "BP+IY", "IX", "IY", "BP", "BW")


def ea_cases():
    cases = []
    ops = (("MOV AW,", 0x8B), ("MOV AL,", 0x8A), ("MOV store AW", 0x89), ("LDEA AW,", 0x8D),
           ("ADD AW,", 0x03), ("ADD store AW", 0x01))
    for label, opcode in ops:
        for mod in (0, 1, 2):
            for rm in range(8):
                text = "disp16" if mod == 0 and rm == 6 else RM[rm] + ("", "+d8", "+d16")[mod]
                code = [opcode, (mod << 6) | rm] + _ea_bytes(mod, rm)
                cases += form("ea", f"{label}[{text}]", code, EA_REGS)
    # Odd addresses: disp8 0x11 and disp16 0x0111 make every operand odd.
    for label, opcode in (("MOV AW,", 0x8B), ("MOV store AW", 0x89), ("ADD store AW", 0x01),
                          ("MOV AL,", 0x8A)):
        for rm in (0, 4, 7):
            cases += form("ea", f"{label}[{RM[rm]}+d8 odd]", [opcode, 0x40 | rm, 0x11], EA_REGS)
        cases += form("ea", f"{label}[disp16 odd]", [opcode, 0x06, 0x81, 0x08], EA_REGS)
    for prefix, seg in ((0x26, "DS1"), (0x2E, "PS"), (0x36, "SS"), (0x3E, "DS0")):
        cases += form("ea", f"{seg}: MOV AW,[BW]", [prefix, 0x8B, 0x07], EA_REGS)
        cases += form("ea", f"{seg}: MOV store AW,[BW]", [prefix, 0x89, 0x07], EA_REGS)
    cases += form("ea", "DS1: SS: MOV AW,[BW]", [0x26, 0x36, 0x8B, 0x07], EA_REGS)
    cases += form("ea", "MOV AW,[BW] (no prefix)", [0x8B, 0x07], EA_REGS)
    return cases


# --- M5: data-dependent forms ---------------------------------------------

def data_cases():
    cases = []
    byte_a = (0x00, 0x01, 0x7F, 0x80, 0xFF)
    byte_b = (0x00, 0x01, 0x02, 0x0F, 0x55, 0x80, 0xAA, 0xFF)
    for name, modrm in (("MULU CL", 0xE1), ("MUL CL", 0xE9)):
        for a in byte_a:
            for b in byte_b:
                cases += form("data", f"{name} [AL={a:02X} CL={b:02X}]", [0xF6, modrm],
                              {"AW": a, "CW": b})
    word_a = (0x0000, 0x0001, 0x7FFF, 0x8000, 0xFFFF)
    word_b = (0x0000, 0x0001, 0x00FF, 0x5555, 0x8000, 0xAAAA, 0xFFFF)
    for name, modrm in (("MULU CW", 0xE1), ("MUL CW", 0xE9)):
        for a in word_a:
            for b in word_b:
                cases += form("data", f"{name} [AW={a:04X} CW={b:04X}]", [0xF7, modrm],
                              {"AW": a, "CW": b})
    for a, b in ((0x0000, 0x0000), (0x0001, 0x0003), (0xFFFF, 0x7F), (0x7FFF, 0x80)):
        cases += form("data", f"MUL AW,CW,imm8 [CW={a:04X} imm={b:02X}]", [0x6B, 0xC1, b],
                      {"CW": a})
    divu8 = ((0x0000, 0x01), (0x0001, 0x01), (0x00FF, 0x01), (0x00FF, 0xFF), (0xFE01, 0xFF),
             (0x7F00, 0x80), (0x1234, 0x56), (0x0100, 0x02), (0x0005, 0x07), (0x1000, 0x01))
    div8 = ((0x0000, 0x01), (0x0064, 0x07), (0xFF9C, 0x07), (0x0064, 0xF9), (0xFF9C, 0xF9),
            (0x7F00, 0xFF), (0x0005, 0x07), (0x4000, 0x01))
    for name, modrm, pairs in (("DIVU CL", 0xF1, divu8), ("DIV CL", 0xF9, div8)):
        for a, b in pairs:
            cases += form("data", f"{name} [AW={a:04X} CL={b:02X}]", [0xF6, modrm],
                          {"AW": a, "CW": b, "SP": 0x0F00}, stubs=True)
    divu16 = ((0x0000, 0x0001, 0x0001), (0x0000, 0xFFFF, 0xFFFF), (0x7FFF, 0xFFFF, 0x8000),
              (0x1234, 0x5678, 0x9ABC), (0x0000, 0x0005, 0x0007), (0xFFFE, 0x0001, 0xFFFF),
              (0x0001, 0x0000, 0x0001))
    div16 = ((0x0000, 0x0064, 0x0007), (0xFFFF, 0xFF9C, 0x0007), (0x0000, 0x0064, 0xFFF9),
             (0xFFFF, 0xFF9C, 0xFFF9), (0x3FFF, 0xFFFF, 0x7FFF), (0x0000, 0x0005, 0x0007),
             (0x4000, 0x0000, 0x0001))
    for name, modrm, rows in (("DIVU CW", 0xF1, divu16), ("DIV CW", 0xF9, div16)):
        for d, a, b in rows:
            cases += form("data", f"{name} [DW:AW={d:04X}{a:04X} CW={b:04X}]", [0xF7, modrm],
                          {"DW": d, "AW": a, "CW": b, "SP": 0x0F00}, stubs=True)
    counts = list(range(0, 18)) + [31, 32, 33, 0xFF]
    for n in counts:
        cases += form("data", f"SHL AW,CL [CL={n}]", [0xD3, 0xE0], {"CW": n, "AW": 0x1234})
        cases += form("data", f"SHL AW,imm {n}", [0xC1, 0xE0, n], {"AW": 0x1234})
    for n in range(0, 10):
        cases += form("data", f"SHL AL,CL [CL={n}]", [0xD2, 0xE0], {"CW": n, "AW": 0x1234})
    for name, modrm in (("SAR AW,CL", 0xF8), ("RCL AW,CL", 0xD0), ("ROR AW,CL", 0xC8)):
        for n in (0, 1, 8, 16, 17):
            cases += form("data", f"{name} [CL={n}]", [0xD3, modrm], {"CW": n, "AW": 0x1234})
    for n in (1, 2, 3):
        cases += form("data", f"SHL [BW],{n} (mem word)", [0xC1, 0x27, n], {"BW": 0x0840})
    cases += form("data", "SHL [BW],CL [CL=3] (mem word)", [0xD3, 0x27], {"BW": 0x0840, "CW": 3})
    strings = {"IX": 0x0800, "IY": 0x0A00, "DS0": 0, "DS1": 0, "AW": 0x9090}
    reps = (("REP MOVBKW", [0xF3, 0xA5]), ("REP MOVBKB", [0xF3, 0xA4]),
            ("REP STMW", [0xF3, 0xAB]), ("REP LDMW", [0xF3, 0xAD]),
            ("REPE CMPBKW", [0xF3, 0xA7]), ("REPE CMPMW", [0xF3, 0xAF]))
    for name, code in reps:
        for n in (0, 1, 2, 3, 8):
            cases += form("data", f"{name} [CW={n}]", code, dict(strings, CW=n))
    for n in (1, 2, 8):
        cases += form("data", f"REP MOVBKW odd [CW={n}]", [0xF3, 0xA5],
                      dict(strings, CW=n, IX=0x0801, IY=0x0A01))
        cases += form("data", f"REP MOVBKW odd-src [CW={n}]", [0xF3, 0xA5],
                      dict(strings, CW=n, IX=0x0801))
    for name, code in (("MOVBKW", [0xA5]), ("STMW", [0xAB]), ("LDMW", [0xAD]),
                       ("CMPBKW", [0xA7]), ("MOVBKB", [0xA4])):
        cases += form("data", f"{name} (single)", code, strings)
    for level in range(0, 6):
        cases += form("data", f"PREPARE 8,{level}", [0xC8, 0x08, 0x00, level],
                      {"BP": 0x0E00, "SP": 0x0F00})
    cases += form("data", "DISPOSE", [0xC9], {"BP": 0x0E00, "SP": 0x0E00},
                  {"word:0x0E00": 0x0E80})
    field = {"IX": 0x0800, "IY": 0x0A00, "DS0": 0, "DS1": 0}
    for width in (0, 1, 3, 7, 8, 15):
        cases += form("data", f"EXT AL,{width} [AL=0]", [0x0F, 0x3B, 0xC0, width],
                      dict(field, AW=0))
        cases += form("data", f"EXT AL,{width} [AL=12]", [0x0F, 0x3B, 0xC0, width],
                      dict(field, AW=12))
        cases += form("data", f"INS AL,{width} [AL=0]", [0x0F, 0x39, 0xC0, width],
                      dict(field, AW=0))
        cases += form("data", f"INS AL,{width} [AL=12]", [0x0F, 0x39, 0xC0, width],
                      dict(field, AW=12))
    bcd = {"IX": 0x0800, "IY": 0x0A00, "DS0": 0, "DS1": 0}
    for name, code in (("ADD4S", [0x0F, 0x20]), ("SUB4S", [0x0F, 0x22]), ("CMP4S", [0x0F, 0x26])):
        for n in (1, 2, 3, 4, 8):
            cases += form("data", f"{name} [CL={n}]", code, dict(bcd, CW=n))
    cases += form("data", "ROL4 AL", [0x0F, 0x28, 0xC0], {"AW": 0x0012})
    cases += form("data", "ROR4 AL", [0x0F, 0x2A, 0xC0], {"AW": 0x0012})
    cases += form("data", "ROL4 [BW]", [0x0F, 0x28, 0x07], {"AW": 0x0012, "BW": 0x0840})
    for value in (0x00, 0x09, 0x63, 0xFF):
        cases += form("data", f"CVTBD [AL={value:02X}]", [0xD4, 0x0A], {"AW": value})
        cases += form("data", f"CVTDB [AW={value:04X}]", [0xD5, 0x0A], {"AW": value | 0x0900})
    for value, psw in ((0x09, 0), (0x0A, 0), (0x9A, 0), (0x09, 0x0011)):
        cases += form("data", f"ADJBA [AL={value:02X} PSW={psw:04X}]", [0x37],
                      {"AW": value, "PSW": psw})
        cases += form("data", f"ADJ4A [AL={value:02X} PSW={psw:04X}]", [0x27],
                      {"AW": value, "PSW": psw})
    for bit in (0, 3, 7):
        cases += form("data", f"TEST1 AL,{bit}", [0x0F, 0x18, 0xC0, bit], {"AW": 0x55})
        cases += form("data", f"SET1 AL,CL [CL={bit}]", [0x0F, 0x14, 0xC0], {"AW": 0x55, "CW": bit})
    for bit in (0, 8, 15):
        cases += form("data", f"NOT1 AW,{bit}", [0x0F, 0x1F, 0xC0, bit], {"AW": 0x55})
    return cases


# --- M8: internal RAM and SFRs --------------------------------------------

# With IDB = FFh and DS0 = F000h, offsets FE00-FEFF are internal RAM and
# FF00-FFFF the SFRs. Bank 7 (the reset bank) sits at FEE0: AW at FEFE,
# CW at FEFC, DS0 at FEE8.
IRAM = {"DS0": 0xF000, "AW": 0x1234, "CW": 0x5678, "BW": 0xFE00}


def iram_cases():
    cases = []
    timing = (
        ("MOV AW,[FE00] internal", [0x8B, 0x06, 0x00, 0xFE]),
        ("MOV AW,[FE01] internal odd", [0x8B, 0x06, 0x01, 0xFE]),
        ("MOV AL,[FE00] internal", [0x8A, 0x06, 0x00, 0xFE]),
        ("MOV store AW,[FE00] internal", [0x89, 0x06, 0x00, 0xFE]),
        ("MOV store AW,[FE01] internal odd", [0x89, 0x06, 0x01, 0xFE]),
        ("MOV store AL,[FE00] internal", [0x88, 0x06, 0x00, 0xFE]),
        ("ADD store AW,[FE00] internal", [0x01, 0x06, 0x00, 0xFE]),
        ("MOV AW,[BW] internal", [0x8B, 0x07]),
        ("MOV AW,[FD00] external", [0x8B, 0x06, 0x00, 0xFD]),
        ("MOV store AW,[FD00] external", [0x89, 0x06, 0x00, 0xFD]),
        ("MOV AL,[FFEB] PRC", [0x8A, 0x06, 0xEB, 0xFF]),
        ("MOV AW,[FFE8] WTC", [0x8B, 0x06, 0xE8, 0xFF]),
        ("MOV AL,[FFFF] IDB", [0x8A, 0x06, 0xFF, 0xFF]),
        ("MOV store AL,[FFE1] RFM", [0xC6, 0x06, 0xE1, 0xFF, 0xEC]),
        ("MOV AL,[FF00] P0", [0x8A, 0x06, 0x00, 0xFF]),
        ("MOV AL,[FF80] reserved", [0x8A, 0x06, 0x80, 0xFF]),
    )
    for name, code in timing:
        cases += form("iram", name, code, IRAM, stubs=True)
    # Registers as RAM: read and write bank 7 through data addresses.
    functional = (
        ("read AW as RAM [FEFE]", [0x8B, 0x16, 0xFE, 0xFE, 0x8B, 0xC2] + DUMP),   # MOV DW,[FEFE]; MOV AW,DW
        ("read CW as RAM [FEFC]", [0x8B, 0x06, 0xFC, 0xFE] + DUMP),
        ("read DS0 as RAM [FEE8]", [0x8B, 0x06, 0xE8, 0xFE] + DUMP),
        ("write CW as RAM [FEFC]", [0xC7, 0x06, 0xFC, 0xFE, 0x5A, 0xA5, 0x8B, 0xC1] + DUMP),
        ("write CL as RAM [FEFC]", [0xC6, 0x06, 0xFC, 0xFE, 0x5A, 0x8B, 0xC1] + DUMP),
        ("write then read RAM [FE40]", [0xC7, 0x06, 0x40, 0xFE, 0x22, 0x11,
                                        0x8B, 0x06, 0x40, 0xFE] + DUMP),
        ("IDB read at FFFFF", [0xA0, 0xFF, 0xFF, 0x32, 0xE4] + DUMP),         # MOV AL,[FFFF]; XOR AH,AH
        # Relocate IDB to 20h: FFE00 should go external, 20E00 internal.
        ("IDB=20 then [F000:FE00]", [0xC6, 0x06, 0xFF, 0xFF, 0x20,
                                     0x8B, 0x06, 0x00, 0xFE] + DUMP),
        ("IDB=20 then [2000:0E00]", [0xC6, 0x06, 0xFF, 0xFF, 0x20, 0xB8, 0x00, 0x20, 0x8E, 0xD8,
                                     0x8B, 0x06, 0x00, 0x0E] + DUMP),
        ("IDB=20 then [F000:FFFF]", [0xC6, 0x06, 0xFF, 0xFF, 0x20,
                                     0xA0, 0xFF, 0xFF, 0x32, 0xE4] + DUMP),
        ("IDB=20 then [2000:0FFF]", [0xC6, 0x06, 0xFF, 0xFF, 0x20, 0xB8, 0x00, 0x20, 0x8E, 0xD8,
                                     0xA0, 0xFF, 0x0F, 0x32, 0xE4] + DUMP),
    )
    for name, code in functional:
        cases += form("iram", name, code, IRAM, stubs=True)
    return cases


# --- M9: PSW and undefined opcodes ----------------------------------------

def _psw_probe(value):
    # PUSH imm; POP PSW; PUSH PSW; POP CW; PUSH F002h; POP PSW; MOV AW,CW; OUT
    return ([0x68] + list(value.to_bytes(2, "little")) + [0x9D, 0x9C, 0x59]
            + [0x68, 0x02, 0xF0, 0x9D, 0x8B, 0xC1] + DUMP)


def psw_cases():
    stack = {"SS": 0, "SP": 0x0F00}
    cases = []
    cases += form("psw", "PSW after prelude", [0x9C, 0x58] + DUMP, stack, stubs=True)
    for value in (0x0000, 0x0002, 0x0EFF, 0x8002, 0x7002, 0x0028, 0x0ED7):
        cases += form("psw", f"POP PSW {value:04X} then read", _psw_probe(value), stack, stubs=True)
    # SAHF from AH = FF and 00; LAHF.
    cases += form("psw", "SAHF FF, LAHF", [0xB4, 0xFF, 0x9E, 0x9F, 0x8A, 0xC4, 0x9C, 0x58]
                  + DUMP, stack, stubs=True)
    cases += form("psw", "SAHF 00, LAHF", [0xB4, 0x00, 0x9E, 0x9F, 0x8A, 0xC4] + DUMP,
                  stack, stubs=True)
    # BRKI = 0: the next OUT should trap to vector 19.
    cases += form("psw", "BRKI=0 then OUT", [0x68, 0x00, 0xF0, 0x9D, 0xE6, 0x26],
                  stack, stubs=True)
    cases += form("psw", "BRKI=0 then IN", [0x68, 0x00, 0xF0, 0x9D, 0xE4, 0x26],
                  stack, stubs=True)
    cases += form("psw", "BRKI=0 then OUTM", [0x68, 0x00, 0xF0, 0x9D, 0xBA, 0x26, 0x00,
                                               0xBE, 0x00, 0x08, 0x6E],
                  dict(stack, DS0=0), stubs=True)
    # RETI with a PSW selecting bank 6 and MD 1 (MD 0 would enter secure
    # mode, and silicon then runs the following opcodes through its table).
    # Bank 6's SS/SP are set first through the internal RAM (bank 6 at FEC0:
    # SS FECA, SP FED6).
    # CALL pushes the address of the dump and jumps to the RETI after it.
    reti = ([0xB8, 0x00, 0xF0, 0x8E, 0xD8,                  # MOV AW,F000h; MOV DS0,AW
             0xC7, 0x06, 0xCA, 0xFE, 0x00, 0x00,            # bank 6 SS = 0
             0xC7, 0x06, 0xD6, 0xFE, 0x00, 0x0E,            # bank 6 SP = 0E00h
             0x68, 0x02, 0xE0,                              # PUSH E002h (PSW: MD 1, RB 6)
             0x0E,                                          # PUSH PS
             0xE8, 0x0A, 0x00]                              # CALL z (pushes r)
            + [0x9C, 0x58] + DUMP                           # r: PUSH PSW; POP AW; OUT
            + [0x68, 0x02, 0xF0, 0x9D,                      # POP PSW F002h (RB kept)
               0xEB, 0x01,                                  # BR over z
               0xCF])                                       # z: RETI
    cases += form("psw", "RETI to bank 6", reti, stack, stubs=True)
    return cases


def undefined_cases():
    stack = {"SS": 0, "SP": 0x0F00, "DS0": 0, "BW": 0x0840}
    cases = []
    holes = (0x00, 0x01, 0x0F, 0x21, 0x24, 0x27, 0x30, 0x34, 0x40, 0x80, 0x90, 0x93, 0x96,
             0xA0, 0xE0, 0xFF)
    for second in holes:
        cases += form("undefined", f"0F {second:02X}", [0x0F, second, 0xC0, 0x90, 0x90, 0x90],
                      stack, stubs=True)
    for escape in (0xD8, 0xDB, 0xDF):
        cases += form("undefined", f"FPO {escape:02X} C0", [escape, 0xC0, 0x90, 0x90], stack,
                      stubs=True)
        cases += form("undefined", f"FPO {escape:02X} [BW]", [escape, 0x07, 0x90, 0x90], stack,
                      stubs=True)
    for opcode in (0x66, 0x67):
        cases += form("undefined", f"{opcode:02X} C0", [opcode, 0xC0, 0x90, 0x90], stack,
                      stubs=True)
    # F1 (BRKS) would enter secure mode with an unknown opcode table: not probed.
    cases += form("undefined", "BRKN 1Eh", [0x63, 0x1E, 0x90, 0x90], stack, stubs=True)
    cases += form("undefined", "BRK 1Eh (CD)", [0xCD, 0x1E, 0x90, 0x90], stack, stubs=True)
    cases += form("undefined", "FE /7 (undefined group)", [0xFE, 0xF8, 0x90, 0x90], stack,
                  stubs=True)
    cases += form("undefined", "8F /1 (undefined POP)", [0x8F, 0xC8, 0x90, 0x90], stack,
                  stubs=True)
    return cases


# --- Phase 1 follow-ups ---------------------------------------------------

def ext_cases():
    """EXT/INS over every bit offset (AL) and width (imm4), plus field data."""
    field = {"IX": 0x0800, "IY": 0x0A00, "DS0": 0, "DS1": 0}
    cases = []
    for name, second in (("EXT", 0x3B), ("INS", 0x39)):
        for offset in range(16):
            for width in range(16):
                cases += form("ext", f"{name} AL,{width} [AL={offset}]",
                              [0x0F, second, 0xC0, width], dict(field, AW=0x5500 | offset))
    for data in (0x0000, 0xFFFF, 0x8001):
        ram = {"word:0x0800": data, "word:0x0802": data, "word:0x0A00": data, "word:0x0A02": data}
        for width in (0, 7, 15):
            for offset in (0, 9):
                cases += form("ext", f"EXT AL,{width} [AL={offset} data={data:04X}]",
                              [0x0F, 0x3B, 0xC0, width], dict(field, AW=offset), ram)
                cases += form("ext", f"INS AL,{width} [AL={offset} data={data:04X}]",
                              [0x0F, 0x39, 0xC0, width], dict(field, AW=0x5500 | offset), ram)
    for offset, width in ((0, 0), (0, 15), (12, 7)):
        cases += form("ext", f"EXT AL,CL [AL={offset} CL={width}]", [0x0F, 0x33, 0xC1],
                      dict(field, AW=offset, CW=width))
        cases += form("ext", f"INS AL,CL [AL={offset} CL={width}]", [0x0F, 0x31, 0xC1],
                      dict(field, AW=0x5500 | offset, CW=width))
    return cases


def mul_cases():
    """Signed multiply on a denser grid around the sign and zero cases."""
    cases = []
    byte_values = (0x00, 0x01, 0x02, 0x03, 0x40, 0x7F, 0x80, 0x81, 0xC0, 0xFE, 0xFF)
    for a in byte_values:
        for b in byte_values:
            cases += form("mul", f"MUL CL [AL={a:02X} CL={b:02X}]", [0xF6, 0xE9],
                          {"AW": a, "CW": b})
    word_values = (0x0000, 0x0001, 0x0002, 0x4000, 0x7FFF, 0x8000, 0x8001, 0xC000, 0xFFFE, 0xFFFF)
    for a in word_values:
        for b in word_values:
            cases += form("mul", f"MUL CW [AW={a:04X} CW={b:04X}]", [0xF7, 0xE9],
                          {"AW": a, "CW": b})
    for a, b in ((0x80, 0x02), (0x02, 0x80), (0x80, 0x04), (0x40, 0xFE)):
        for imm in (0x02, 0x80, 0xFE):
            cases += form("mul", f"MUL AW,CW,imm8 [CW={a:04X} imm={imm:02X}]",
                          [0x6B, 0xC1, imm], {"CW": a if a < 0x80 else 0xFF00 | a})
    return cases


BANK_FORMS = (
    ("INC AW (40)", [0x40]), ("INC AW (FF /0)", [0xFF, 0xC0]), ("MOV AW,CW", [0x8B, 0xC1]),
    ("ADD AW,CW", [0x03, 0xC1]), ("TEST AW,CW", [0x85, 0xC1]), ("XCH AW,CW (91)", [0x91]),
    ("PUSH AW", [0x50]), ("POP AW", [0x58]), ("MOV AW,[BW]", [0x8B, 0x07]),
    ("MOV store [BW],AW", [0x89, 0x07]), ("MOV AW,DS0", [0x8C, 0xD8]),
)


def bank_cases():
    """The same forms in every register bank, plus a check of which bank runs."""
    regs = {"AW": 0x1234, "CW": 0x0034, "BW": 0x0840, "SP": 0x0F00}
    cases = []
    for bank in range(8):
        for name, code in BANK_FORMS:
            for case in form("banks", f"{name} [bank {bank}]", code, regs):
                case.bank = bank
                cases.append(case)
        # MOV DS0,F000h; MOV DW,[bank AW slot]; MOV AW,DW; OUT 22h,AW
        slot = 0xFE00 + bank * 0x20 + 0x1E
        check = ([0xB8, 0x00, 0xF0, 0x8E, 0xD8, 0x8B, 0x16, slot & 0xFF, slot >> 8, 0x8B, 0xC2]
                 + DUMP)
        for case in form("banks", f"read own AW slot [bank {bank}]", check, regs):
            case.bank = bank
            cases.append(case)
    return cases


def undefined2_cases():
    """What forms the 0F 00 read-modify-write address; 0F 80 repeated."""
    base = {"SS": 0, "SP": 0x0F00, "DS0": 0, "DS1": 0, "BW": 0x0840}
    cases = []
    variants = [("base", {})] + [(f"{reg}={value:04X}", {reg: value}) for reg, value in (
        ("AW", 0x1111), ("CW", 0x2222), ("DW", 0x3333), ("BW", 0x0444), ("BP", 0x0555),
        ("IX", 0x0666), ("IY", 0x0777), ("SP", 0x0E00), ("DS0", 0x0100), ("DS1", 0x0200),
        ("SS", 0x0010))]
    for label, regs in variants:
        cases += form("undefined2", f"0F 00 C0 [{label}]", [0x0F, 0x00, 0xC0, 0x90, 0x90, 0x90],
                      dict(base, **regs), stubs=True)
    for modrm in (0x00, 0x07, 0x06, 0xC7, 0xFF):
        cases += form("undefined2", f"0F 00 {modrm:02X}", [0x0F, 0x00, modrm, 0x90, 0x90, 0x90],
                      base, stubs=True)
    for second in (0x01, 0x27, 0x40, 0xA0):
        cases += form("undefined2", f"0F {second:02X} C0 [DW=3333]",
                      [0x0F, second, 0xC0, 0x90, 0x90, 0x90], dict(base, DW=0x3333), stubs=True)
    for attempt in range(6):
        cases += form("undefined2", f"0F 80 C0 (run {attempt})",
                      [0x0F, 0x80, 0xC0, 0x90, 0x90, 0x90], base, stubs=True)
    return cases


# --- Queue word release (docs/v35s-core-model.md) -------------------------

RELEASE_TARGETS = (
    ("CLR1 CY", [0xF8]), ("INC AW", [0x40]), ("NOP", [0x90]), ("XCH AW,CW", [0x91]),
    ("CVTBW", [0x98]), ("CVTWL", [0x99]), ("ADJ4A", [0x27]), ("ADJBA", [0x37]),
    ("PUSH AW", [0x50]), ("POP CW", [0x59]), ("LDMB", [0xAC]), ("STMB", [0xAA]),
    ("MOVBKB", [0xA4]), ("TRANS", [0xD7]),
    # 2- and 3-byte forms of similar length, for contrast
    ("SHL AW,1", [0xD1, 0xE0]), ("MULU CL", [0xF6, 0xE1]), ("ADD AW,CW", [0x03, 0xC1]),
    ("MOV CL,imm8", [0xB1, 0x12]), ("MOV CW,imm16", [0xB9, 0x34, 0x12]),
    ("SHL AW,imm 4", [0xC1, 0xE0, 0x04]),
)
RELEASE_FOLLOWERS = (
    ("then NOPs", []),
    ("then ADD AW,CW", [0x03, 0xC1]),
    ("then MOV DW,imm16", [0xBA, 0x34, 0x12]),
    ("then CVTWL", [0x99]),
)


def release_cases():
    """When does each queue word free? Targets after a saturated runway,
    at both placements, followed by different next instructions."""
    regs = {"AW": 0x0012, "CW": 0x0003, "SP": 0x0F00, "IX": 0x0800, "IY": 0x0A00,
            "BW": 0x0800, "DS0": 0, "DS1": 0}
    cases = []
    for name, code in RELEASE_TARGETS:
        for follow, tail in RELEASE_FOLLOWERS:
            cases += form("release", f"{name} {follow}", code + tail, regs, both=True)
    for first, second in (("CVTWL", "CVTWL"), ("ADJBA", "ADJBA"), ("CVTWL", "NOP"),
                          ("NOP", "CVTWL"), ("INC AW", "CVTWL"), ("CVTWL", "INC AW")):
        code = dict(RELEASE_TARGETS)[first] + dict(RELEASE_TARGETS)[second]
        cases += form("release", f"pair {first}; {second}", code, regs, both=True)
    return cases


HELD_TRAINS = (
    # name, bytes of one instruction, count
    ("NOP", [0x90], 12), ("INC AW", [0x40], 12), ("XCH AW,CW", [0x91], 12),
    ("CLR1 CY", [0xF8], 12), ("CVTWL", [0x99], 8), ("ADJBA", [0x37], 6),
    ("ADD AW,CW", [0x03, 0xC1], 8), ("MOV CL,imm8", [0xB1, 0x03], 8),
    ("SHL AW,CL", [0xD3, 0xE0], 6), ("MULU CL", [0xF6, 0xE1], 6),
    ("MOV DW,imm16", [0xBA, 0x34, 0x12], 6), ("SHL AW,imm 2", [0xC1, 0xE0, 0x02], 6),
)
HELD_PHASE_TARGETS = (("NOP", [0x90]), ("XCH AW,CW", [0x91]), ("INC AW", [0x40]),
                      ("CLR1 CY", [0xF8]), ("CVTWL", [0x99]), ("ADJBA", [0x37]))


def held_cases():
    """What releases a held fetch? Trains of one instruction at a steady
    consumption rate; 1-byte targets behind 0-3 INC AW (2 clocks each, so
    the EU's phase against the bus moves); shifts of graded length."""
    regs = {"AW": 0x0012, "CW": 0x0003, "SP": 0x0F00, "IX": 0x0800, "IY": 0x0A00,
            "BW": 0x0800, "DS0": 0, "DS1": 0}
    cases = []
    for name, code, count in HELD_TRAINS:
        cases += form("held", f"train {name} x{count}", code * count, regs, both=True)
    for name, code in HELD_PHASE_TARGETS:
        for k in range(4):
            cases += form("held", f"phase INC x{k}; {name}", [0x40] * k + code, regs, both=True)
    for cl in (0, 1, 2, 3, 5, 8):
        cases += form("held", f"SHL AW,CL={cl}", [0xD3, 0xE0], dict(regs, CW=cl), both=True)
    for n in (0, 1, 2, 4, 8):
        cases += form("held", f"SHL AW,{n} (C1)", [0xC1, 0xE0, n], regs, both=True)
    return cases


EU_TRAINS = (("NOP", [0x90], 6), ("INC AW", [0x40], 8), ("MOV CL,imm8", [0xB1, 0x03], 6),
             ("CVTWL", [0x99], 4))
BURST_TRAINS = (("MOV AL,imm8", [0xB0, 0x03]), ("ADD AL,imm8", [0x04, 0x01]),
                ("MOV CW,AW", [0x8B, 0xC8]), ("MOV CL,imm8; NOP", [0xB1, 0x03, 0x90]))


def eu_cases():
    """Where is the EU after each instruction of a train? k instructions
    then OUT 40h,AL: the I/O cycle timestamps the EU next to the fetches.
    And trains of other one-word instructions, to see whether the even
    MOV CL,imm8 train's fetch triples are particular to it."""
    regs = {"AW": 0x0012, "CW": 0x0003, "SP": 0x0F00, "IX": 0x0800, "IY": 0x0A00,
            "BW": 0x0800, "DS0": 0, "DS1": 0}
    cases = []
    for name, code, most in EU_TRAINS:
        for k in range(1, most + 1):
            cases += form("eu", f"{name} x{k}; OUT", code * k + [0xE6, 0x40], regs, both=True)
    for name, code in BURST_TRAINS:
        cases += form("eu", f"train {name} x8", code * 8, regs, both=True)
    return cases


FOLLOWERS = (("MOV CL,imm8", [0xB1, 0x03]), ("MOV AL,imm8", [0xB0, 0x03]),
             ("ADD AL,imm8", [0x04, 0x01]), ("MOV CW,AW", [0x8B, 0xC8]),
             ("ADD AW,CW", [0x03, 0xC1]), ("SHL AW,1", [0xD1, 0xE0]),
             ("NOP NOP", [0x90, 0x90]), ("INC INC", [0x40, 0x40]),
             ("CVTWL CVTWL", [0x99, 0x99]), ("OUT 40h", [0xE6, 0x40]),
             ("IN AL,40h", [0xE4, 0x40]), ("MOV AW,imm16", [0xB8, 0x34, 0x12]),
             ("XCH AW,CW", [0x91]), ("MOV CL,[BW]", [0x8A, 0x0F]),
             ("PUSH AW", [0x50]), ("BR short", [0xEB, 0x00]))
LEADERS = (("MOV CL,imm8", [0xB1, 0x03]), ("NOP NOP", [0x90, 0x90]),
           ("INC INC", [0x40, 0x40]), ("MOV CW,AW", [0x8B, 0xC8]))


def follow_cases():
    """Which next word does the EU load early? A one-word leader, then each
    follower, then OUT 40h,AL to time the EU; both placements."""
    regs = {"AW": 0x0012, "CW": 0x0003, "SP": 0x0F00, "IX": 0x0800, "IY": 0x0A00,
            "BW": 0x0800, "DS0": 0, "DS1": 0}
    cases = []
    for lead, first in LEADERS:
        for name, code in FOLLOWERS:
            cases += form("follow", f"{lead}; {name}; OUT", first + code + [0xE6, 0x40],
                          regs, both=True)
    return cases


STALLS = (("MOV AL,[BW]", [0x8A, 0x07]), ("MOV [BW],AL", [0x88, 0x07]),
          ("IN AL,40h", [0xE4, 0x40]), ("MULU CL", [0xF6, 0xE1]))


def stall_cases():
    """Do the even MOV CL triples and INC pairs restart from a stall? A
    memory read, a memory write, an I/O read or a long register-only
    instruction after k instructions of a train; both placements."""
    regs = {"AW": 0x0012, "CW": 0x0003, "SP": 0x0F00, "IX": 0x0800, "IY": 0x0A00,
            "BW": 0x0800, "DS0": 0, "DS1": 0}
    mov, inc = [0xB1, 0x03], [0x40]
    cases = form("stall", "MOV CL x6", mov * 6, regs, both=True)
    cases += form("stall", "INC AW x8", inc * 8, regs, both=True)
    for name, code in STALLS:
        for k in range(5):
            cases += form("stall", f"MOV CL x{k}; {name}; MOV CL x{6 - k}",
                          mov * k + code + mov * (6 - k), regs, both=True)
        for k in (0, 1, 2, 3):
            cases += form("stall", f"INC AW x{k}; {name}; INC AW x{8 - k}",
                          inc * k + code + inc * (8 - k), regs, both=True)
    return cases


REGFORMS = (
    [(f"{op} AW,CW ({code:02X})", [code, 0xC1]) for op, code in
     (("ADD", 0x03), ("OR", 0x0B), ("ADDC", 0x13), ("SUBC", 0x1B), ("AND", 0x23), ("SUB", 0x2B),
      ("XOR", 0x33), ("CMP", 0x3B), ("TEST", 0x85), ("XCH", 0x87), ("MOV", 0x8B))]
    + [("ADD CW,AW (01)", [0x01, 0xC1]), ("ADD AL,CL (02)", [0x02, 0xC1]), ("MOV CW,AW (89)", [0x89, 0xC1]),
       ("MOV AL,CL (8A)", [0x8A, 0xC1]), ("XCH AL,CL (86)", [0x86, 0xC1]), ("TEST AL,CL (84)", [0x84, 0xC1]),
       ("MOV AW,DS0 (8C)", [0x8C, 0xD8]), ("MOV DS1,AW (8E)", [0x8E, 0xC0]), ("INC AW (FF /0)", [0xFF, 0xC0]),
       ("DEC AL (FE /1)", [0xFE, 0xC8]), ("PUSH AW (FF /6)", [0xFF, 0xF0]), ("POP AW (8F /0)", [0x8F, 0xC0])]
    + [(f"{op} AW,1 (D1 /{r})", [0xD1, 0xC0 | r << 3]) for r, op in
       ((0, "ROL"), (1, "ROR"), (2, "ROLC"), (3, "RORC"), (4, "SHL"), (5, "SHR"), (7, "SHRA"))]
    + [("SHL AL,1 (D0)", [0xD0, 0xE0]), ("SHL AL,CL (D2)", [0xD2, 0xE0]), ("SHR AW,CL (D3)", [0xD3, 0xE8]),
       ("SHL AW,3 (C1)", [0xC1, 0xE0, 3]), ("SHL AL,3 (C0)", [0xC0, 0xE0, 3])]
    + [(f"{op} AW (F7 /{r})", [0xF7, 0xC0 | r << 3 | 1]) for r, op in
       ((2, "NOT CW"), (3, "NEG CW"), (4, "MULU CW"), (5, "MUL CW"), (6, "DIVU CW"), (7, "DIV CW"))]
    + [(f"{op} (F6 /{r})", [0xF6, 0xC0 | r << 3 | 1]) for r, op in
       ((2, "NOT CL"), (3, "NEG CL"), (4, "MULU CL"), (5, "MUL CL"), (6, "DIVU CL"), (7, "DIV CL"))]
    + [("TEST AW,imm16 (F7 /0)", [0xF7, 0xC0, 0x34, 0x12]), ("TEST AL,imm8 (F6 /0)", [0xF6, 0xC0, 0x12]),
       ("ADD AW,imm16 (81)", [0x81, 0xC0, 0x34, 0x12]), ("ADD AW,imm8 (83)", [0x83, 0xC0, 0x12]),
       ("ADD AL,imm8 (80)", [0x80, 0xC0, 0x12]), ("CMP AW,imm8 (83 /7)", [0x83, 0xF8, 0x12]),
       ("MOV AW,imm16 (C7)", [0xC7, 0xC0, 0x34, 0x12]), ("MOV AL,imm8 (C6)", [0xC6, 0xC0, 0x12]),
       ("MUL AW,CW,imm8 (6B)", [0x6B, 0xC1, 0x03]), ("MUL AW,CW,imm16 (69)", [0x69, 0xC1, 0x03, 0x00])]
    + [(f"{op} AW,CL (0F {code:02X})", [0x0F, code, 0xC0]) for op, code in
       (("TEST1", 0x11), ("CLR1", 0x13), ("SET1", 0x15), ("NOT1", 0x17))]
    + [(f"{op} AW,3 (0F {code:02X})", [0x0F, code, 0xC0, 3]) for op, code in
       (("TEST1", 0x19), ("CLR1", 0x1B), ("SET1", 0x1D), ("NOT1", 0x1F))]
    + [("ROL4 AL (0F 28)", [0x0F, 0x28, 0xC0]), ("EXT AL,CL (0F 33)", [0x0F, 0x33, 0xC1]),
       ("INS AL,CL (0F 31)", [0x0F, 0x31, 0xC1])]
)


def regform_cases():
    """Where does each register-form ModR/M instruction release its words?
    Every form at both placements, then four NOPs: at odd placement the
    ModR/M shares a word with the next opcode, so the next fetch dates when
    that word's slot frees."""
    regs = {"AW": 0x0012, "CW": 0x0003, "DW": 0x0000, "SP": 0x0F00, "IX": 0x0800, "IY": 0x0A00,
            "BW": 0x0800, "DS0": 0, "DS1": 0}
    cases = []
    for name, code in REGFORMS:
        cases += form("regform", name, code + [0x90] * 4, regs, both=True)
    return cases


def tail_cases():
    """Calibrate the window tail: SHL AW,16 (C1 E0 10) ends every window, so
    its cost cancels out of target costs. Shifts with long counts, by
    immediate and by CL, and the count-1 form, as targets."""
    regs = {"AW": 0x0012, "CW": 0x0003, "SP": 0x0F00, "IX": 0x0800, "IY": 0x0A00,
            "BW": 0x0800, "DS0": 0, "DS1": 0}
    cases = []
    for n in (8, 12, 15, 16, 17, 24, 31):
        cases += form("tail", f"SHL AW,{n} (C1)", [0xC1, 0xE0, n], regs, both=True)
    for cl in (8, 16, 31):
        cases += form("tail", f"SHL AW,CL={cl}", [0xD3, 0xE0], dict(regs, CW=cl), both=True)
    cases += form("tail", "SHL AW,1 (D1)", [0xD1, 0xE0], regs, both=True)
    cases += form("tail", "SHL AW,1 (D1) x2", [0xD1, 0xE0] * 2, regs, both=True)
    cases += form("tail", "OUT 0x40,AL", [0xE6, 0x40], regs, both=True)
    cases += form("tail", "OUT 0x40,AL x2", [0xE6, 0x40] * 2, regs, both=True)
    cases += form("tail", "SHL AW,16 (C1); NOP", [0xC1, 0xE0, 16, 0x90], regs, both=True)
    return cases


SUITES = {
    "regs": regs_cases,
    "ea": ea_cases,
    "data": data_cases,
    "iram": iram_cases,
    "psw": psw_cases,
    "undefined": undefined_cases,
    "ext": ext_cases,
    "mul": mul_cases,
    "banks": bank_cases,
    "undefined2": undefined2_cases,
    "release": release_cases,
    "held": held_cases,
    "tail": tail_cases,
    "eu": eu_cases,
    "follow": follow_cases,
    "stall": stall_cases,
    "regform": regform_cases,
}
