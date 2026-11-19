"""F2 part 2: the traps and the remaining opcodes (docs/v35s-function-plan.md, stage F2).

Directed programs measured on the socketed uPD70337 and run unchanged on the core v2 RTL in
simulation, as validation/v35s/onchip.py's F1 set (that module's run_one is used).

    PYTHONPATH=host/src:. uv run --with pyusb python -m validation.v35s.traps socket [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.traps sim [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.traps gate [NAME ...]
    PYTHONPATH=host/src:. python3 -m validation.v35s.traps show NAME [--ref socket]
    PYTHONPATH=host/src:. python3 -m validation.v35s.traps emit

Every program shares one frame: the vector table points every vector n at a stub (0000:3000h +
12n) that records n and enters a logging handler (0000:3800h). The handler records the trap's
frame and the registers at the trap in a log entry (0000:8100h + 32k: the vector, the test, the
pushed PC, PS and PSW, the handler's PSW, SP after the pushes, AW CW DW BW BP IX IY DS0 DS1) and
returns through RETI to the test's continuation (the frame's PC and PS rewritten), or, when the
test's re-execute flag is set, to the pushed PC with BRKI set in the pushed PSW. A test sets the
registers to known values (Test.regs), the PSW, runs its bytes followed by a NOP sled, and at the
continuation stores every register and the PSW in its slot (0000:9000h + 32k: AW CW DW BW SP BP
IX IY DS0 DS1 SS PSW). The data areas A000h and B000h are preloaded with a pattern and read back.

Receipts: validation/v35s/receipts/f2-<name>-<backend>.json (--tag adds a suffix); the
undefined-opcode series (one short program per opcode, item 4) is one receipt per series,
f2-undef_<series>-<backend>.json, holding one record per program.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

from .onchip import Program, run_one

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS_DIR = ROOT / "validation/v35s/programs"
RECEIPTS = ROOT / "validation/v35s/receipts"

LOG = 0x8000            # count (word), vector (byte at 8002h), test (8004h), continuation (8006h),
                        # the re-execute flag (8008h); entries at 8100h + 32k
SLOTS = 0x9000          # the continuation's register slots, 32 bytes per test
DATA0 = 0xA000          # DS0 = 0A00h
DATA1 = 0xB000          # DS1 = 0B00h
STUBS = 0x3000
HANDLER = 0x3800
REGS = {"AW": 0x1234, "CW": 0x0003, "DW": 0x0024, "BW": 0x0010, "BP": 0x0020, "IX": 0x0030,
        "IY": 0x0040}
DS0, DS1 = 0x0A00, 0x0B00
SP0 = 0x7F00
PSW0 = 0x0002           # the PSW a test starts from (POP PSW: bits 11-0)

HANDLER_SRC = """\
    PUSH PSW
    PUSH AW
    PUSH BW
    PUSH BP
    PUSH IX
    MOV BP, SP
    DB 2Eh
    MOV IX, [8000h]
    MOV BW, IX
    INC BW
    DB 2Eh
    MOV [8000h], BW
    SHL IX, 1
    SHL IX, 1
    SHL IX, 1
    SHL IX, 1
    SHL IX, 1
    ADD IX, 8100h
    DB 2Eh
    MOV AL, [8002h]
    DB 2Eh
    MOV [IX], AL
    DB 2Eh
    MOV AW, [8004h]
    DB 2Eh
    MOV [IX+2], AW
    MOV AW, [BP+10]
    DB 2Eh
    MOV [IX+4], AW
    MOV AW, [BP+12]
    DB 2Eh
    MOV [IX+6], AW
    MOV AW, [BP+14]
    DB 2Eh
    MOV [IX+8], AW
    MOV AW, [BP+8]
    DB 2Eh
    MOV [IX+10], AW
    LDEA AW, [BP+10]
    DB 2Eh
    MOV [IX+12], AW
    MOV AW, [BP+6]
    DB 2Eh
    MOV [IX+14], AW
    DB 2Eh
    MOV [IX+16], CW
    DB 2Eh
    MOV [IX+18], DW
    MOV AW, [BP+4]
    DB 2Eh
    MOV [IX+20], AW
    MOV AW, [BP+2]
    DB 2Eh
    MOV [IX+22], AW
    MOV AW, [BP+0]
    DB 2Eh
    MOV [IX+24], AW
    DB 2Eh
    MOV [IX+26], IY
    MOV AW, DS0
    DB 2Eh
    MOV [IX+28], AW
    MOV AW, DS1
    DB 2Eh
    MOV [IX+30], AW
    CMP BW, 40h
    BGE runaway
    DB 2Eh
    TEST byte [8008h], 1
    BNZ rexec
    DB 2Eh
    MOV AW, [8006h]
    MOV [BP+10], AW
    MOV word [BP+12], 0000h
    BR hout
rexec:
    OR word [BP+14], 0002h
hout:
    POP IX
    POP BP
    POP BW
    POP AW
    POP PSW
    RETI
runaway:
    MOV AW, 0002h
    PUSH AW
    POP PSW
    MOV DW, 0FF02h
    OUT DW, AL
    HALT
rspin:
    BR rspin
"""


def vector_area() -> dict:
    """The vector table (every vector to its stub) and the stubs: stub n stores n at
    PS:8002h and jumps to the handler."""
    from .asm import assemble
    ivt = bytearray()
    for n in range(32):
        ivt += (STUBS + 12 * n).to_bytes(2, "little") + b"\x00\x00"
    stubs = bytearray()
    for n in range(32):
        at = STUBS + 12 * n
        rel = HANDLER - (at + 9)
        stubs += bytes([0x2E, 0xC6, 0x06, 0x02, 0x80, n, 0xE9, rel & 0xFF, (rel >> 8) & 0xFF,
                        0x90, 0x90, 0x90])
    return {0x0000: bytes(ivt), STUBS: bytes(stubs), HANDLER: assemble(HANDLER_SRC, org=HANDLER)}


def pattern(base: int, n=0x100) -> bytes:
    return bytes(((base >> 8) * 0x11 + 7 * i + 3) & 0xFF for i in range(n))


class Test:
    """One case: registers (REGS overridden by `regs`), the PSW (POP PSW of `psw`, or SAHF of
    its low byte with `sahf`), the code (`code`: assembly; `raw`: bytes as DB), a sled of
    `sled` NOPs (or the bytes `tail`), and the re-execute flag."""

    def __init__(self, name, code="", raw=None, psw=PSW0, regs=None, sahf=False, sled=6,
                 tail=None, rexec=False, pre="", before="", note=""):
        self.name = name
        self.code = code
        self.raw = raw
        self.psw = psw
        self.regs = dict(REGS, **(regs or {}))
        self.sahf = sahf
        self.sled = sled
        self.tail = tail
        self.rexec = rexec
        self.pre = pre
        self.before = before
        self.note = note


def _db(bs) -> str:
    return "    DB " + ", ".join(f"{b:02X}h" if b < 0xA0 else f"0{b:02X}h" for b in bs) + "\n"


def test_source(k: int, t: Test) -> str:
    L = [f"; ---- test {k}: {t.name}{' (' + t.note + ')' if t.note else ''}\n"]
    L.append(f"    DB 2Eh, 0C7h, 06h, 04h, 80h\n    DW {k:04X}h\n")
    L.append(f"    DB 2Eh, 0C7h, 06h, 06h, 80h\n    DW cont{k}\n")
    L.append(f"    DB 2Eh, 0C6h, 06h, 08h, 80h, {int(t.rexec):02X}h\n")
    L.append(f"""\
    XOR AW, AW
    MOV SS, AW
    MOV SP, {SP0:04X}h
    MOV AW, {DS0:04X}h
    MOV DS0, AW
    MOV AW, {DS1:04X}h
    MOV DS1, AW
""")
    for r in ("CW", "DW", "BW", "BP", "IX", "IY"):
        L.append(f"    MOV {r}, {t.regs[r]:04X}h\n")
    L.append(t.pre)
    if t.sahf:
        L.append(f"    MOV AW, {PSW0:04X}h\n    PUSH AW\n    POP PSW\n")
        L.append(f"    MOV AH, {t.psw & 0xFF:02X}h\n    MOV AL, {t.regs['AW'] & 0xFF:02X}h\n"
                 + t.before + "    MOV PSW, AH\n")
    else:
        L.append(f"    MOV AW, {t.psw:04X}h\n    PUSH AW\n    MOV AW, {t.regs['AW']:04X}h\n"
                 "    POP PSW\n")
    if t.code:
        L.append(t.code if t.code.endswith("\n") else t.code + "\n")
    if t.raw:
        L.append(_db(t.raw))
    if t.tail is not None:
        L.append(_db(t.tail))
    elif t.sled:
        L.append(_db([0x90] * t.sled))
    s = SLOTS + 32 * k
    L.append(f"cont{k}:\n")
    for i, r in enumerate(("AW", "CW", "DW", "BW", "SP", "BP", "IX", "IY")):
        L.append(f"    DB 2Eh\n    MOV [{s + 2 * i:04X}h], {r}\n")
    L.append(f"""\
    PUSH PSW
    MOV AW, DS0
    DB 2Eh
    MOV [{s + 16:04X}h], AW
    MOV AW, DS1
    DB 2Eh
    MOV [{s + 18:04X}h], AW
    MOV AW, SS
    DB 2Eh
    MOV [{s + 20:04X}h], AW
    POP AW
    DB 2Eh
    MOV [{s + 22:04X}h], AW
    MOV AW, {PSW0:04X}h
    PUSH AW
    POP PSW
""")
    return "".join(L)


EPILOGUE = """\
    NOP
    MOV DW, 0FF00h
    OUT DW, AL
    HALT
done:
    BR done
"""


def make_program(name, tests, note="", gate=True, extra=None):
    src = "    DI\n" + "".join(test_source(k, t) for k, t in enumerate(tests)) + EPILOGUE
    data = vector_area()
    data[DATA0] = pattern(DATA0)
    data[DATA1] = pattern(DATA1)
    data.update(extra or {})
    n = len(tests)
    prog = Program(name, src, data=data,
                   results=[(LOG, 0x10), (LOG + 0x100, 0x800), (SLOTS, 32 * n),
                            (DATA0, 0x100), (DATA1, 0x100), (0x7E00, 0x200)],
                   gate=gate, note=note)
    prog.tests = tests
    return prog


# ------------------------------------------------------------------ the program sets
def iot_tests():
    """Item 1: PSW.BRKI = 0 and every I/O form."""
    B0 = 0x0000                 # POP PSW: BRKI 0
    T = []
    forms = [("in_al_imm", [0xE4, 0x22]), ("in_aw_imm", [0xE5, 0x22]),
             ("out_imm_al", [0xE6, 0x22]), ("out_imm_aw", [0xE7, 0x22]),
             ("in_al_dw", [0xEC]), ("in_aw_dw", [0xED]), ("out_dw_al", [0xEE]),
             ("out_dw_aw", [0xEF]), ("inm_b", [0x6C]), ("inm_w", [0x6D]),
             ("outm_b", [0x6E]), ("outm_w", [0x6F])]
    for nm, bs in forms:
        T.append(Test(f"brki0_{nm}", raw=bs, psw=B0))
    for nm, bs in forms:
        T.append(Test(f"brki1_{nm}", raw=bs, psw=0x0002, note="BRKI 1: no trap"))
    T += [
        Test("brki0_rep_inm_b", raw=[0xF3, 0x6C], psw=B0, note="REP INM: the prefix's PC?"),
        Test("brki0_rep_outm_w", raw=[0xF3, 0x6F], psw=B0),
        Test("brki0_rep_inm_cw0", raw=[0xF3, 0x6C], psw=B0, regs={"CW": 0}, note="no element"),
        Test("brki1_rep_inm_b", raw=[0xF3, 0x6C], psw=0x0002),
        Test("brki0_pfx_in", raw=[0x26, 0xE4, 0x22], psw=B0, note="a segment prefix first"),
        Test("brki0_pfx_outm", raw=[0x26, 0x6E], psw=B0),
        Test("brki0_pfx2_outm", raw=[0x26, 0x3E, 0x6E], psw=B0, note="two prefixes"),
        Test("brki0_rep_pfx_outm", raw=[0xF3, 0x26, 0x6E], psw=B0),
        Test("brki0_pfx_rep_outm", raw=[0x26, 0xF3, 0x6E], psw=B0),
        Test("brki0_rexec_in", raw=[0xE4, 0x22], psw=B0, rexec=True, note="re-executed"),
        Test("brki0_rexec_rep_inm", raw=[0xF3, 0x6C], psw=B0, rexec=True),
        # SAHF's BRKI (F1: one instruction late) and the reverse
        Test("sahf0_in", raw=[0xE4, 0x22], psw=0x00, sahf=True),
        Test("sahf0_nop_in", raw=[0x90, 0xE4, 0x22], psw=0x00, sahf=True),
        Test("sahf0_outm", raw=[0x6E], psw=0x00, sahf=True),
        Test("sahf0_inc_out", raw=[0x41, 0xE6, 0x22], psw=0x00, sahf=True),
        Test("sahf0_pfx_out", raw=[0x26, 0xE6, 0x22], psw=0x00, sahf=True,
             note="a prefix after SAHF"),
        Test("sahf0_movimm_out", raw=[0xB1, 0x05, 0xE6, 0x22], psw=0x00, sahf=True),
        Test("sahf0_x2_out", code="    MOV PSW, AH", raw=[0xE6, 0x22], psw=0x00, sahf=True,
             note="SAHF twice"),
        Test("popf0_sahf2_in", code="    MOV AH, 02h\n    MOV PSW, AH", raw=[0xE4, 0x22],
             psw=0x0000, note="BRKI 0 by POP PSW, SAHF 02 then IN: the late set"),
        Test("popf0_sahf2_nop_in", code="    MOV AH, 02h\n    MOV PSW, AH\n    NOP",
             raw=[0xE4, 0x22], psw=0x0000),
        Test("popf0_popf2_in", code="    MOV CW, 0002h\n    PUSH CW\n    POP PSW",
             raw=[0xE4, 0x22], psw=0x0000, regs={"CW": 0x0002}),
        Test("reti0_in", code=reti_code(0xF000), raw=[0xE4, 0x22], psw=0x0002,
             note="RETI restores BRKI 0, the target an IN"),
        Test("brki0_handler_out", raw=[0xCD, 0x13], psw=B0, note="BRK 19: the handler's PSW"),
        Test("brki0_ie_in", raw=[0xE4, 0x22], psw=0x0200, note="IE 1: the handler's PSW"),
        Test("brk19_ie", raw=[0xCD, 0x13], psw=0x0202, note="BRK 19 with IE 1"),
    ]
    for nm, bs in forms:
        T.append(Test(f"sahf0_{nm}", raw=bs, psw=0x00, sahf=True, note="SAHF 00 then at once"))
    T += [
        Test("sahf0_rep_inm", raw=[0xF3, 0x6C], psw=0x00, sahf=True),
        Test("sahf0_full_in", raw=[0xE4, 0x22], psw=0x00, sahf=True, regs={"CW": 0x0010},
             before="    ROL BW, CL\n", note="a long instruction before SAHF: the queue full"),
        Test("sahf0_flush_in", raw=[0xE4, 0x22], psw=0x00, sahf=True,
             before="    DB 0EBh, 00h\n", note="a branch before SAHF: the queue empty"),
        Test("sahf0_flush_in_dw", raw=[0xEC], psw=0x00, sahf=True,
             before="    DB 0EBh, 00h\n"),
        Test("sahf0_full_out_dw", raw=[0xEE], psw=0x00, sahf=True, regs={"CW": 0x0010},
             before="    ROL BW, CL\n"),
        Test("popf0_sahf2_outm", code="    MOV AH, 02h\n    MOV PSW, AH", raw=[0x6E],
             psw=0x0000, note="the late set before OUTM"),
        Test("popf0_sahf2_out_dw", code="    MOV AH, 02h\n    MOV PSW, AH", raw=[0xEE],
             psw=0x0000),
    ]
    return T


# Measured, not built (README "F2b"): silicon's BRKI after SAHF is not yet seen by an imm8-port
# form at once (nor by a DW form after a long instruction filled the queue), while the DW and
# string forms after a short one see it; the RTL decides at the dispatch, after SAHF's write.
# REP before a segment prefix before a string is a REP string on silicon (not built).
IOT_OPEN = {"sahf0_in", "popf0_sahf2_in", "sahf0_in_al_imm", "sahf0_in_aw_imm",
            "sahf0_out_imm_al", "sahf0_out_imm_aw", "sahf0_full_in", "sahf0_flush_in",
            "sahf0_full_out_dw", "brki0_rep_pfx_outm"}


def reti_code(psw):
    """Push a frame (PSW psw, PS 0, PC the next instruction) and RETI to it."""
    return (f"    MOV AW, {psw:04X}h\n    PUSH AW\n    XOR AW, AW\n    PUSH AW\n"
            "    CALL rtgt{n}\nrtgt{n}:\n    POP AW\n    ADD AW, 9\n    PUSH AW\n"
            "    MOV AW, 1234h\n    RETI\n")


def fpo_tests():
    """Item 2: D8-DF and 66 / 67 (vector 7)."""
    T = []
    for op in range(0xD8, 0xE0):
        T.append(Test(f"fpo_{op:02X}_reg", raw=[op, 0xC0 | (op & 7)]))
    T += [
        Test("fpo_D8_ix", raw=[0xD8, 0x04], note="mod 00 [IX]"),
        Test("fpo_DF_bwd8", raw=[0xDF, 0x47, 0x10], note="mod 01 [BW+10h]"),
        Test("fpo_D9_bwd16", raw=[0xD9, 0x87, 0x34, 0x00], note="mod 10 [BW+0034h]"),
        Test("fpo_DB_dir", raw=[0xDB, 0x06, 0x50, 0x00], note="direct [0050h]"),
        Test("fpo_DD_bp", raw=[0xDD, 0x46, 0x08], note="[BP+8]: SS"),
        Test("fpo_D8_pfx_ix", raw=[0x26, 0xD8, 0x04], note="DS1: prefix"),
        Test("fpo_D8_rep_reg", raw=[0xF3, 0xD8, 0xC0], note="REP before"),
        Test("fpo_66_reg", raw=[0x66, 0xC0]),
        Test("fpo_66_ix", raw=[0x66, 0x04]),
        Test("fpo_67_reg", raw=[0x67, 0xC7]),
        Test("fpo_67_d16", raw=[0x67, 0x87, 0x34, 0x00]),
        Test("fpo_66_pfx_d8", raw=[0x26, 0x66, 0x47, 0x10]),
        Test("fpo_DE_word_ix", raw=[0xDE, 0x05], note="[IY]"),
        Test("fpo_D8_flags", raw=[0xD8, 0xC0], psw=0x0CD7, note="flags set"),
        Test("fpo_D8_ie", raw=[0xD8, 0xC0], psw=0x0202, note="IE 1: the handler's PSW"),
        Test("fpo_DF_ie_mem", raw=[0xDF, 0x06, 0x50, 0x00], psw=0x0E02),
    ]
    return T


def chk_tests():
    """Item 3: CHKIND (62 /r mem), vector 5. Bounds at DS0:0080h (lower, upper) unless named."""
    def bounds(lo, hi, at=0x80):
        return (f"    MOV word [{at:04X}h], {lo:04X}h\n    MOV word [{at + 2:04X}h], {hi:04X}h\n")
    T = []
    for nm, aw, lo, hi in [("in", 0x0015, 0x0010, 0x0020), ("lo_edge", 0x0010, 0x0010, 0x0020),
                           ("hi_edge", 0x0020, 0x0010, 0x0020), ("below", 0x000F, 0x0010, 0x0020),
                           ("above", 0x0021, 0x0010, 0x0020),
                           ("signed_in", 0x0000, 0xFFF0, 0x0010),
                           ("signed_neg", 0xFFF8, 0xFFF0, 0x0010),
                           ("unsigned_hi", 0x8000, 0x0010, 0x0020),
                           ("inverted", 0x0015, 0x0020, 0x0010)]:
        T.append(Test(f"chk_{nm}", pre=bounds(lo, hi), raw=[0x62, 0x06, 0x80, 0x00],
                      regs={"AW": aw}, note=f"AW {aw:04X} in [{lo:04X}, {hi:04X}]"))
    T += [
        Test("chk_cw_ix", pre=bounds(0x0010, 0x0020, 0x30), raw=[0x62, 0x0C],
             regs={"CW": 0x0030}, note="CHKIND CW,[IX]: above"),
        Test("chk_bw_d8", pre=bounds(0x0000, 0x0005, 0x60), raw=[0x62, 0x5F, 0x50],
             regs={"BW": 0x0010}, note="CHKIND BW,[BW+50h]: above"),
        Test("chk_pfx", pre="    DB 26h\n    MOV word [0080h], 0010h\n"
                            "    DB 26h\n    MOV word [0082h], 0020h\n",
             raw=[0x26, 0x62, 0x06, 0x80, 0x00], regs={"AW": 0x0030},
             note="DS1: prefix, above"),
        Test("chk_flags", pre=bounds(0x0010, 0x0020), raw=[0x62, 0x06, 0x80, 0x00],
             regs={"AW": 0x0015}, psw=0x0CD7, note="flags kept?"),
        Test("chk_odd", pre="    MOV word [0081h], 0010h\n    MOV word [0083h], 0020h\n",
             raw=[0x62, 0x06, 0x81, 0x00], regs={"AW": 0x0040}, note="odd bounds, above"),
        Test("chk_ie", pre=bounds(0x0010, 0x0020), raw=[0x62, 0x06, 0x80, 0x00],
             regs={"AW": 0x0030}, psw=0x0E02, note="IE 1: the handler's PSW"),
        Test("chk_bp", pre="    DB 36h\n    MOV word [0028h], 0010h\n"
                           "    DB 36h\n    MOV word [002Ah], 0020h\n",
             raw=[0x62, 0x46, 0x08], regs={"AW": 0x0005}, note="[BP+8]: SS, below"),
    ]
    return T


def legit_tests():
    """Item 8: ModR/M register cells a V35 program can use (the 8086 forms)."""
    return [
        Test("pop_8f_reg", code="    MOV CW, 5A5Ah\n    PUSH CW", raw=[0x8F, 0xC6],
             note="POP IX by 8F /0"),
        Test("mov_c6_reg", raw=[0xC6, 0xC1, 0x77], note="MOV CL,77h by C6 /0"),
        Test("mov_c7_reg", raw=[0xC7, 0xC3, 0x55, 0xAA], note="MOV BW,AA55h by C7 /0"),
        Test("push_ff_reg", raw=[0xFF, 0xF2], note="PUSH DW by FF /6"),
        Test("push_ff_sp", raw=[0xFF, 0xF4], note="PUSH SP by FF /6"),
        Test("inc_ff_reg", raw=[0xFF, 0xC1], note="INC CW by FF /0"),
        Test("dec_ff_reg", raw=[0xFF, 0xCB]),
        Test("inc_fe_reg", raw=[0xFE, 0xC4]),
        Test("dec_fe_reg", raw=[0xFE, 0xCD]),
        Test("pop_8f_mem", code="    MOV CW, 6B6Bh\n    PUSH CW", raw=[0x8F, 0x06, 0x90, 0x00],
             note="POP [0090h]"),
        Test("push_54_sp", raw=[0x54], note="PUSH SP (54) for comparison"),
    ]


def btclr_tests():
    """Item 6: BTCLR sfr, bit, disp8 (0F 9C sfr imm3 disp8) on storage SFRs (IDB FFh: the page
    at FFF00h). The branch target skips a MOV that would mark the not-taken path."""
    T = []
    cases = [("brg0_b0_set", 0x6A, 0x55, 0), ("brg0_b1_clr", 0x6A, 0x55, 1),
             ("brg0_b7_clr", 0x6A, 0x55, 7), ("brg0_b6_set", 0x6A, 0x55, 6),
             ("tmms0_b3", 0x94, 0xFF, 3), ("tmms0_b2", 0x94, 0xFF, 2),
             ("exic0_if", 0x4C, 0xC7, 7), ("exic0_pr", 0x4C, 0x47, 0),
             ("brg0_b5_ff", 0x6A, 0xFF, 5), ("bit_hi", 0x6A, 0x01, 8 + 0)]
    for nm, sfr, val, bit in cases:
        pre = (f"    MOV AW, 0F000h\n    MOV DS1, AW\n    MOV AL, {val:02X}h\n"
               f"    DB 26h\n    MOV [0FF{sfr:02X}h], AL\n    MOV AW, 0B00h\n    MOV DS1, AW\n")
        code = f"""\
    XOR DW, DW
    DB 0Fh, 9Ch, {sfr:02X}h, {bit:02X}h, 02h
    MOV DL, 11h
    MOV DH, 22h
    MOV AW, 0F000h
    MOV DS1, AW
    DB 26h
    MOV AL, [0FF{sfr:02X}h]
    DB 26h
    MOV byte [0FF{sfr:02X}h], {0x47 if sfr == 0x4C else 0x00:02X}h
    MOV CW, 0B00h
    MOV DS1, CW
"""
        T.append(Test(f"btclr_{nm}", pre=pre, code=code, note=f"SFR {sfr:02X} = {val:02X}, bit {bit}"))
    T.append(Test("btclr_back", pre="    MOV AW, 0F000h\n    MOV DS1, AW\n    MOV AL, 03h\n"
                                    "    DB 26h\n    MOV [0FF6Ah], AL\n",
                  code="""\
    XOR DW, DW
bk:
    INC DW
    DB 0Fh, 9Ch, 6Ah, 00h, 0FAh
    DB 0Fh, 9Ch, 6Ah, 01h, 0F5h
    DB 26h
    MOV AL, [0FF6Ah]
    MOV CW, 0B00h
    MOV DS1, CW
""", note="backward branches: DW counts the passes"))
    return T


def poll_program():
    """Item 5: POLL (9B) waits while P14 (the INT pin) is high. INT is held high at rest; the
    program reads P1 (bit 4 the pin), announces an event, POLLs, reads P1 again: the schedule
    drops INT 3,000 ticks after event 1 (so P1 bit 4 reads 0 only after POLL waited); then POLL
    with the pin low; then the pin raised (event 2) and dropped 3,000 ticks after event 3."""
    def rd(k):
        return f"    DB 26h\n    MOV AL, [0FF08h]\n    DB 2Eh\n    MOV [{0x9800 + k:04X}h], AL\n"

    def ev(n):
        return f"    MOV DW, 0FF12h\n    MOV AL, {n:02X}h\n    OUT DW, AL\n"
    pre = "    MOV AW, 0F000h\n    MOV DS1, AW\n"
    tests = [
        Test("poll_wait", pre=pre, code=rd(0) + ev(1) + "    POLL\n" + rd(1)),
        Test("poll_low", pre=pre, code=rd(2) + "    POLL\n" + rd(3)),
        Test("poll_wait2", pre=pre, code=ev(2) + "    NOP\n" * 8 + rd(4) + ev(3) + "    POLL\n"
             + rd(5) + "    POLL\n" + rd(6)),
    ]
    prog = make_program("f2_poll", tests, note="POLL on P14 (INT), the schedule moving the pin")
    prog.results.append((0x9800, 0x10))
    from .runner import INPUTS, REST_LEVELS
    prog.levels = REST_LEVELS | (1 << INPUTS["INT"])
    prog.stim = {"entries": [{"event": 1, "delay": 3000, "levels": {"INT": 0}},
                             {"event": 2, "delay": 0, "levels": {"INT": 1}},
                             {"event": 3, "delay": 3000, "levels": {"INT": 0}}]}
    return prog


# ------------------------------------------------------------------ item 4: the undefined opcodes
# One short program per case. The registers point into a landing zone (2000h-2FEFh: NOPs, then
# at LAND a routine that records the arrival and resumes at the continuation), so a transfer the
# opcode makes is caught; the memory operand [IX] (DS0:260Ch = A60Ch) holds a far pointer into the
# zone too. Pass A runs the bytes with a NOP sled (mod 10 if read as a ModR/M byte), pass B with
# AW = 0 and a sled of INC AW (40h: mod 01), so AW counts the sled bytes executed.
UREGS = {"AW": 0x2102, "CW": 0x2204, "DW": 0x2306, "BW": 0x2408, "BP": 0x250A, "IX": 0x260C,
         "IY": 0x270E}
UPSW = 0x0893           # CY AC S V set, P Z DIR clear, BRKI 1
LAND = 0x2FF0
UDS0, UDS1 = 0x0800, 0x0900


def zone() -> bytes:
    from .asm import assemble
    body = bytes([0x90]) * (LAND - 0x2000)
    land = assemble("""\
    DB 2Eh
    MOV [8010h], AW
    DB 2Eh
    MOV [8012h], SP
    DB 2Eh
    INC word [8014h]
    DB 2Eh
    BR word [8006h]
""", org=LAND)
    return body + land


def undef_program(name, raw, regs=None, sled=8, note=""):
    regs = dict(UREGS, **(regs or {}))
    seg = f"""\
    MOV AW, {UDS0:04X}h
    MOV DS0, AW
    MOV AW, {UDS1:04X}h
    MOV DS1, AW
"""
    tests = [Test(f"{name}_a", raw=raw, regs=regs, psw=UPSW, sled=sled, pre=seg),
             Test(f"{name}_b", raw=raw, regs=dict(regs, AW=0), psw=UPSW, tail=[0x40] * sled,
                  pre=seg)]
    prog = make_program(name, tests, note=note,
                        extra={0x2000: zone(), 0xA60C: bytes([0x00, 0x28, 0x00, 0x00, 0x20, 0x28,
                                                               0x00, 0x00])})
    prog.results = [(LOG, 0x20), (LOG + 0x100, 0x100), (SLOTS, 0x40), (0x7E00, 0x200),
                    (0xA600, 0x40), (0xB700, 0x40)]
    return prog


UNDEF_0F_SKIP = {0x25, 0x2D, 0x91, 0x92, 0x94, 0x95, 0x9E, 0x9C}     # F3's (bank, STOP); BTCLR
PAGE_DEFINED = set(range(0x10, 0x20)) | {0x20, 0x22, 0x26, 0x28, 0x2A, 0x31, 0x33, 0x39, 0x3B}


def undef_cases():
    """(series, name, bytes, regs, note) for every case of item 4."""
    C = []
    for b in range(256):
        if b in PAGE_DEFINED or b in UNDEF_0F_SKIP:
            continue
        C.append(("0f", f"u0f{b:02X}", [0x0F, b], None, f"0F {b:02X}"))
    C.append(("op", "uD6", [0xD6], None, "D6"))
    for op, regs_ in ((0x8F, range(1, 8)), (0xC6, range(1, 8)), (0xC7, range(1, 8)),
                      (0xFE, range(2, 8)), (0xFF, (7,))):
        for r in regs_:
            C.append(("modrm", f"u{op:02X}r{r}", [op, 0xC0 | r << 3 | 1], None,
                      f"{op:02X} /{r} reg (CW)"))
            C.append(("modrm", f"u{op:02X}m{r}", [op, 0x04 | r << 3], None, f"{op:02X} /{r} [IX]"))
    for op, nm in ((0x8D, "LDEA"), (0xC4, "LDS1"), (0xC5, "LDS0")):
        C.append(("modrm", f"u{op:02X}reg", [op, 0xC1], None, f"{nm} AW,CW (register form)"))
    C.append(("modrm", "uFFr3", [0xFF, 0xD9], None, "CALL far, register CW"))
    C.append(("modrm", "uFFr5", [0xFF, 0xE9], None, "BR far, register CW"))
    C.append(("modrm", "u62reg", [0x62, 0xC1], None, "CHKIND AW,CW (register form)"))
    rep = {"CW": 0x0003}
    for p_ in (0xF3, 0xF2, 0x64, 0x65):
        C.append(("rep", f"r{p_:02X}_40", [p_, 0x40], rep, f"{p_:02X} before INC AW, CW 3"))
    C += [("rep", "rF3_90", [0xF3, 0x90], rep, "REP NOP"),
          ("rep", "rF3_B1", [0xF3, 0xB1, 0x05], rep, "REP MOV CL,5"),
          ("rep", "rF3_01", [0xF3, 0x01, 0xC8], rep, "REP ADD AW,CW (ModR/M)"),
          ("rep", "rF3_26A4", [0xF3, 0x26, 0xA4], rep, "REP DS1: MOVBK byte"),
          ("rep", "r26_F3A4", [0x26, 0xF3, 0xA4], rep, "DS1: REP MOVBK byte"),
          ("rep", "rF3_F3A4", [0xF3, 0xF3, 0xA4], rep, "REP REP MOVBK"),
          ("rep", "rF3_0F", [0xF3, 0x0F, 0x18, 0xC0, 0x00], rep, "REP before CLR1 AL,0"),
          ("rep", "rF3_E4", [0xF3, 0xE4, 0x22], rep, "REP IN AL,22h"),
          ("rep", "rF3_F8", [0xF3, 0xF8], rep, "REP CLR1 CY"),
          ("rep", "rF3_IDIV", [0xF3, 0xF7, 0xF9], {"AW": 0x0064, "DW": 0x0000, "CW": 0x0007},
           "REP IDIV CW (100 / 7: the 8086 negates the quotient)"),
          ("rep", "r_IDIV", [0xF7, 0xF9], {"AW": 0x0064, "DW": 0x0000, "CW": 0x0007},
           "IDIV CW without REP"),
          ("rep", "rF2_IDIVn", [0xF2, 0xF7, 0xF9], {"AW": 0xFF9C, "DW": 0xFFFF, "CW": 0x0007},
           "REPNE IDIV CW (-100 / 7)")]
    return C


def undef_programs(series=None):
    out = {}
    for ser, name, raw, regs, note in undef_cases():
        if series and ser != series:
            continue
        out[name] = undef_program(name, raw, regs, note=note)
        out[name].series = ser
    return out


def programs():
    return {
        "f2_iot": make_program("f2_iot", [t for t in iot_tests() if t.name not in IOT_OPEN],
                               note="BRKI 0: every I/O form, prefixes, REP, SAHF / POP PSW / RETI"),
        "f2_iot_open": make_program("f2_iot_open", [t for t in iot_tests() if t.name in IOT_OPEN],
                                    gate=False, note="the I/O-trap cases not built: SAHF right "
                                    "before an imm8-port form or after a full queue; REP DS1:"),
        "f2_fpo": make_program("f2_fpo", fpo_tests(), note="the FPO escapes D8-DF, 66, 67"),
        "f2_chk": make_program("f2_chk", chk_tests(), note="CHKIND in range, below, above"),
        "f2_legit": make_program("f2_legit", legit_tests(),
                                 note="the 8086 register cells 8F/0 C6/0 C7/0 FF/6 FF/0-1 FE/0-1"),
        "f2_btclr": make_program("f2_btclr", btclr_tests(), note="BTCLR on storage SFRs"),
        "f2_poll": poll_program(),
    }


def _fix_labels(src: str) -> str:
    # reti_code's local labels: number them
    out, n = [], 0
    for line in src.splitlines(keepends=True):
        if "{n}" in line:
            if "CALL rtgt{n}" in line:
                n += 1
            line = line.replace("{n}", str(n))
        out.append(line)
    return "".join(out)


_orig_make = make_program


def make_program(name, tests, note="", gate=True, extra=None):    # noqa: F811
    prog = _orig_make(name, tests, note, gate, extra)
    prog.source = _fix_labels(prog.source)
    return prog


# ------------------------------------------------------------------ running
def receipt_path(name, backend):
    return RECEIPTS / f"f2-{name}-{backend}.json"


def save(rec, name, backend):
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    receipt_path(name, backend).write_text(json.dumps(rec, indent=1) + "\n")


def load(name, backend):
    return json.loads(receipt_path(name, backend).read_text())


def _board():
    from .runner import open_board
    transport, harness, state = open_board(True)
    harness.strict = False
    harness.configure(x_half=2)
    transport.vccb_enable()
    harness.arm()
    time.sleep(0.05)
    return transport, harness


def _close_board(transport, harness):
    try:
        harness.arm(False)
        transport.power_off()
    finally:
        transport.close()


def _sim():
    from .chains.acquire import sim_transport
    from .runner import Harness
    from nuboard.debug import DebugClient
    transport = sim_transport("v35")
    harness = Harness(DebugClient(transport.exchange), strict=False)
    harness.configure(x_half=2)
    # (work order 29) the program gates load the 1:1 translation table (test stimulus: the core
    # never initialises it; f3_brks stages the BRKS handler's first opcode in secure mode);
    # V35_TTAB names another (none: unloaded)
    from .secure import env_table
    table = env_table("identity")
    if table is not None:
        harness.load_table(table)
    return transport, harness


def _stim(harness, prog):
    from .runner import REST_LEVELS, load_stimulus
    harness.debug.write16(0x8E, getattr(prog, "levels", REST_LEVELS))
    if harness.version >= 2:
        load_stimulus(harness, getattr(prog, "stim", None))


def run_set(names, backend, tag="", progs=None, limit=20_000_000):
    progs = progs or programs()
    out = []
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
            rec.update(backend=backend, date=datetime.datetime.now().isoformat(timespec="seconds"))
            if backend == "socket":
                rec.update(cpu="uPD70337L-8", x_half=2)
            else:
                rec.update(core="v35", binary=os.environ.get(
                    "V35_SIM_BINARY", "build/fpga/v35s/verilator-direct-v35"))
            save(rec, name, backend + tag)
            out.append(rec)
            print(f"{name}: {backend} {'PASS' if rec['passed'] else 'FAIL'} "
                  f"status=0x{rec['status']:04x} writes={len(rec['writes'])} total={rec['total']}",
                  flush=True)
    finally:
        if backend == "socket":
            _close_board(transport, harness)
    return out


def run_undef(series, backend, tag="", names=None, limit=4_000_000):
    """Item 4's series: one program per case, each run on its own (the run limit bounds a case
    that runs away); one receipt per series with the whole bus trace of every case. The series
    stops if the socket stops answering (a run whose status shows no completion twice)."""
    from .onchip import _io_reads, _write_sequence
    progs = undef_programs(series)
    if names:
        progs = {n: p for n, p in progs.items() if n in names}
    lane = "socket" if backend == "socket" else "model"
    recs = {}
    path = receipt_path(f"undef_{series}", backend + tag)
    if path.exists():
        recs = json.loads(path.read_text()).get("cases", {})
    board = _board() if backend == "socket" else None
    dead = 0
    try:
        for name, prog in progs.items():
            transport, harness = board if board else _sim()
            try:
                code, segments, pages = prog.image()
                harness.debug.write16(0x8E, getattr(prog, "levels", 0x1E1F))
                harness.load(segments, pages)
                result = harness.run("socket" if lane == "socket" else "model", limit)
                trace = list(result[f"{lane}_trace"])
                regions = {f"{a:05X}": harness.read_memory(lane, a, n).hex()
                           for a, n in prog.results}
            finally:
                if not board:
                    transport.close()
            rec = {"program": name, "note": prog.note, "passed": result["passed"],
                   "status": result["status"], "timeout": result["timeout"],
                   "total": result[f"{lane}_total"], "writes": _write_sequence(trace),
                   "io_reads": _io_reads(trace), "regions": regions,
                   "trace": [[t["address"], t["data"], t["flags"]] for t in trace],
                   "test_at": test_addresses(prog)}
            recs[name] = rec
            print(f"{name}: {backend} {'PASS' if rec['passed'] else 'FAIL'} "
                  f"status=0x{rec['status']:04x} writes={len(rec['writes'])} "
                  f"total={rec['total']}", flush=True)
            dead = dead + 1 if not rec["passed"] and rec["total"] == 0 else 0
            if dead >= 2:
                print(f"STOP: the {backend} lane gives no trace twice running (last {name})")
                break
    finally:
        if board:
            _close_board(*board)
        RECEIPTS.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"series": series, "backend": backend,
                                    "date": datetime.datetime.now().isoformat(timespec="seconds"),
                                    "cases": recs}, indent=0) + "\n")
    return recs


# ------------------------------------------------------------------ reading a receipt
def _w(b, o):
    return b[o] | b[o + 1] << 8


def decode(rec, prog=None):
    """The log entries and the slots of a receipt, named."""
    regs = rec["regions"]
    log = bytes.fromhex(regs[f"{LOG + 0x100:05X}"])
    hdr = bytes.fromhex(regs[f"{LOG:05X}"])
    count = _w(hdr, 0)
    entries = []
    for k in range(min(count, len(log) // 32)):
        e = log[32 * k:32 * k + 32]
        entries.append({"vector": e[0], "test": _w(e, 2), "pc": _w(e, 4), "ps": _w(e, 6),
                        "psw": _w(e, 8), "hpsw": _w(e, 10), "sp": _w(e, 12),
                        **{r: _w(e, 14 + 2 * i) for i, r in
                           enumerate(("AW", "CW", "DW", "BW", "BP", "IX", "IY", "DS0", "DS1"))}})
    slots = bytes.fromhex(regs[f"{SLOTS:05X}"])
    out = []
    for k in range(len(slots) // 32):
        s = slots[32 * k:32 * k + 32]
        out.append({r: _w(s, 2 * i) for i, r in enumerate(
            ("AW", "CW", "DW", "BW", "SP", "BP", "IX", "IY", "DS0", "DS1", "SS", "PSW"))})
    return count, entries, out


def test_addresses(prog):
    """The address of each test's first raw byte (the instruction under test) and of its
    continuation: from a listing assembled twice."""
    from .asm import assemble
    res = []
    for k, t in enumerate(prog.tests):
        head = "    DI\n" + "".join(test_source(j, u) for j, u in enumerate(prog.tests[:k]))
        cur = test_source(k, t)
        cut = cur.index(_db(t.raw)) if t.raw else cur.index(f"cont{k}:")
        a = len(assemble(_fix_labels(head + cur[:cut] + f"cont{k}:\n"), org=0x100))
        res.append(0x100 + a)
    return res


def show(name, backend="socket", progs=None):
    progs = progs or programs()
    prog = progs[name]
    rec = load(name, backend)
    count, entries, slots = decode(rec)
    addrs = test_addresses(prog)
    print(f"{name} ({backend}): passed {rec['passed']} status {rec['status']:04x} traps {count}")
    by_test = {}
    for e in entries:
        by_test.setdefault(e["test"], []).append(e)
    for k, t in enumerate(prog.tests):
        s = slots[k] if k < len(slots) else {}
        line = f"{k:2d} {t.name:22s} @{addrs[k]:04X}"
        for e in by_test.get(k, []):
            line += (f" | v{e['vector']} pc={e['pc']:04X}({e['pc'] - addrs[k]:+d}) psw={e['psw']:04X}"
                     f" hpsw={e['hpsw']:04X} sp={e['sp']:04X} AW={e['AW']:04X} CW={e['CW']:04X}"
                     f" IX={e['IX']:04X} IY={e['IY']:04X}")
        line += " || " + " ".join(f"{r}={v:04X}" for r, v in s.items())
        print(line)


# ------------------------------------------------------------------ the gate
def compare_gate(names, ref="socket", cand="sim", exclude=None):
    """The write and I/O sequence and the result regions equal (the bytes in exclude(name)
    masked)."""
    from .onchip import _masked_writes
    ok_all = True
    for name in names:
        a, b = load(name, ref), load(name, cand)
        ex = exclude(name) if exclude else set()
        wa, wb = _masked_writes(a["writes"], ex), _masked_writes(b["writes"], ex)
        diffs = []
        for key in a["regions"]:
            base = int(key, 16)
            ra, rb = bytes.fromhex(a["regions"][key]), bytes.fromhex(b["regions"].get(key, ""))
            diffs += [(base + i, ra[i], rb[i] if i < len(rb) else -1) for i in range(len(ra))
                      if base + i not in ex and (i >= len(rb) or ra[i] != rb[i])]
        same_io = a["io_reads"] == b["io_reads"]
        ok = wa == wb and not diffs and a["passed"] == b["passed"]
        ok_all &= ok
        first = next((i for i, (x, y) in enumerate(zip(wa, wb)) if x != y), None)
        print(f"{name}: gate {'EQUAL' if ok else 'DIFFER'} writes {len(wa)}/{len(wb)}"
              + ("" if first is None else
                 f" first difference at {first}: {wa[first][0]:05X} {wa[first][1]:04X} "
                 f"{wa[first][2]:03X} / {wb[first][0]:05X} {wb[first][1]:04X} {wb[first][2]:03X}")
              + f" io_reads {'equal' if same_io else 'differ'} passed {a['passed']}/{b['passed']}"
              + ("" if not diffs else " result bytes differ: " +
                 ", ".join(f"{x:05X}:{y:02X}/{z:02X}" for x, y, z in diffs[:16])
                 + (f" (+{len(diffs) - 16})" if len(diffs) > 16 else "")))
    return ok_all


def emit(progs=None):
    for name, prog in (progs or programs()).items():
        path = PROGRAMS_DIR / f"{name}.s"
        path.write_text(f"; F2 ({prog.note}). Generated by validation/v35s/traps.py emit: the\n"
                        f"; image also preloads the vector stubs, the handler and the data.\n"
                        + prog.source)
        print(path)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=("socket", "sim", "gate", "show", "emit", "usocket", "usim"))
    p.add_argument("names", nargs="*")
    p.add_argument("--tag", default="")
    p.add_argument("--ref", default="socket")
    p.add_argument("--cand", default="sim")
    p.add_argument("--series", default="0f")
    a = p.parse_args()
    if a.action in ("usocket", "usim"):
        run_undef(a.series, a.action[1:], a.tag, a.names or None)
        return 0
    progs = programs()
    names = a.names or [n for n, prog in progs.items() if a.action == "socket" or prog.gate]
    if a.action in ("socket", "sim"):
        run_set(names, a.action, a.tag, progs)
    elif a.action == "gate":
        return 0 if compare_gate(names, a.ref, a.cand) else 1
    elif a.action == "show":
        for n in names:
            show(n, a.ref, progs)
    else:
        emit(progs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
