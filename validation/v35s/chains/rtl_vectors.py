"""D1, D2 and the core v2's function benches: the functional reference's vectors for the RTL.

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --regfile --family F0 F23 \\
        [--keep DIR] [--show N]
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --fn --family F0 F3 F23

--regfile: the families' instruction forms (the starts of their chains as the functional
reference, funcref.py, walks them), every distinct encoding of those on random register files
and memory, the 24 ModR/M memory modes and random operands on every ALU form, (S6) each as a
single-instruction test on the core v2's whole-core bench (fpga/v35s/v35_core2_tb.sv,
fpga/v35s/build_core2_tb.sh), its register file, PSW, segment registers, next PS:IP, memory and
I/O writes compared with the reference's: see "D1, D2" and "(S6, core v2) The whole-core
function bench" below. sst.py --rtl runs SingleStepTests through the same bench (check_sst).

--fn: (S3) the --regfile vectors that are one function application on registers, as V35FN-1
lines for the function bench (fpga/v35s/v35_rf_tb.sv on v35_fn_pkg, fpga/v35s/build_rf_tb.sh):
see "(S3, core v2) The function bench" below.

The first RTL attempt's benches (the chain core's bus unit, queue, EU and whole-core vectors from
the frozen model, --queue / --joint / --eu / --joint3 / --core and the default bus-unit mode)
were retired with that core (docs/v35s-core-v2.md, S7).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


# D1, D2: the register file, the EA adder and the ALU ----------------------------------------
#
# --regfile's vectors, an instruction at a time (regfile_vectors): every instruction start of the
# families' chains as the functional reference (funcref.py) walks them (walk), every distinct
# encoding of those again on random register files and memory (random), the 24 ModR/M memory
# modes on the forms that compute an address (modes), and random operands (edge values among
# them) on every ALU form the decoder knows: the 00-3F block, the 80-83 group, TEST, XCH, the
# shift group with its counts, NOT / NEG / MULU / MUL / DIVU / DIV, INC / DEC, the 70-7F
# conditions and DBNZ on random PSWs (alu). The expected values are the functional reference's.
# (S6) check_regfile runs them as single instructions on the core v2's whole-core bench (below);
# --fn derives the function bench's lines from them; sst.py --rtl runs SingleStepTests through
# the whole-core bench. Each vector is still built as the retired chain core's unit bench took
# it (a V35RF-3 line: the register file in the RTL's representation, FFIELDS, before and after).
#
#     PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --regfile --family F0 ...

# the register file (the V35RF-3 lines' fields), MSB first
FFIELDS = (
    ("aw", 16), ("cw", 16), ("dw", 16), ("bw", 16), ("sp", 16), ("bp", 16), ("ix", 16),
    ("iy", 16),              # the word registers (REG16 order)
    ("ps", 16), ("ss", 16), ("ds0", 16), ("ds1", 16),   # (D2) the segment registers
    ("psw", 16),             # (D2) the PSW (the V35 layout)
    ("pfx", 3),              # the segment prefix the next instruction carries: 4 + its sreg
)


def rf_of(regs: dict) -> dict:
    """(D2) the register file in the RTL's representation (FFIELDS) of a functional
    reference's snapshot (funcref.Cpu.snapshot)."""
    from .funcref import REG16, SREG
    f = {n.lower(): regs[n] & 0xFFFF for n in REG16 + ("PS", "SS", "DS0", "DS1", "PSW")}
    f["pfx"] = 0 if regs.get("pfx") is None else 4 | regs["pfx"]
    assert SREG == ("DS1", "PS", "SS", "DS0")
    return f


RFFORMAT = "V35RF-3"         # (WP79) the record carries a bit field's cost
RK = {"read": 1, "write": 2, "io_read": 3, "io_write": 4}       # V35_RK_*
EDGES = (0x0000, 0x0001, 0x0002, 0x007F, 0x0080, 0x00FF, 0x0100, 0x7FFF, 0x8000, 0x8001,
         0xFFFE, 0xFFFF)
SHIFT_COUNTS = (0, 1, 2, 7, 8, 9, 15, 16, 17, 18, 31, 32, 33, 255)


def func_ok(code: bytes) -> bool:
    """(D2) the old core's v35_eu_pkg v35_func_ok: the forms whose function it built (the rest
    raised V35_EE_FUNC): not F6/F7 /1, FF /2-/5 /7, the register forms of F6/F7 /2 /3, FF, 8F
    and C6/C7, 8F /1-7, MOV PS,r/m (8E /1), PREPARE with a level."""
    o, m = code[0], code[1]
    mod, reg = m >> 6, (m >> 3) & 7
    if o in (0xF6, 0xF7) and (reg == 1 or (mod == 3 and reg in (2, 3))):
        return False
    if o == 0xFF and (reg in (2, 3, 4, 5, 7) or mod == 3):
        return False
    if o == 0x8F and (mod == 3 or reg != 0):
        return False
    if o in (0xC6, 0xC7) and mod == 3:
        return False
    if o == 0x8E and reg & 3 == 1:
        return False
    return not (o == 0xC8 and code[3] != 0)


def rtl_decodes(code: bytes) -> bool:
    """(D2) eu_decode knows the opcode (op.ok), for the vector generators (the bench checks
    the RTL's own): the catalog's opcodes and the 70-7F conditions; (WP79) the 0F page and the
    register miscellany."""
    o, m = code[0], code[1]
    mod, reg = m >> 6, (m >> 3) & 7
    if o == 0x0F:                       # (WP79) the bit fields: a register operand only
        if m in (0x31, 0x33, 0x39, 0x3B):
            return code[2] >> 6 == 3
        return 0x10 <= m <= 0x1F or m in (0x20, 0x22, 0x26, 0x28, 0x2A)
    if 0x40 <= o <= 0x4F or o in (0xF5, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0x98, 0x99, 0x27,
                                  0x2F, 0x37, 0x3F, 0xD4, 0xD5, 0x69, 0x6B):
        return True
    if o == 0xFE:
        return reg in (0, 1)
    if o in (0x26, 0x2E, 0x36, 0x3E, 0x90, 0x92, 0xF4, 0x50, 0x58, 0x59, 0x05, 0xA8, 0xA9, 0xA1,
             0xA3, 0xEB, 0xE2, 0xE9, 0xE8, 0xC3, 0x68, 0x6A, 0x60, 0x61, 0xC8, 0xC9, 0x06, 0x0E,
             0x16, 0x1E, 0x07, 0x17, 0x1F, 0xD7):
        return True
    if 0xB0 <= o <= 0xBF or 0xE4 <= o <= 0xE7 or 0xEC <= o <= 0xEF or 0x70 <= o <= 0x7F:
        return True
    if o < 0x40 and o & 7 < 4:
        return True
    if 0x84 <= o <= 0x8F:
        return not (o == 0x8D and mod == 3)
    if o in (0x81, 0x83, 0xC6, 0xC7, 0xC1, 0xD0, 0xD1, 0xD3, 0xF7, 0xFF):
        return True
    return o == 0xF6 and reg != 0


def _rf_text(regs: dict) -> str:
    f = rf_of(regs)
    return " ".join(str(f[n]) for n, _ in FFIELDS)


def rf_vector(before: dict, code6: bytes, pc: int, org: int, st, after: dict | None, *,
              mutate: int = 0, bad: bool = False, trap: bool = False, nxt: int | None = None,
              wdata: list | None = None) -> str:
    """One V35RF-2 line: the register file before (a funcref snapshot), the instruction's six
    bytes at code offset pc (code_org org), the functional reference's start st (the record,
    the cycles in order: a read's delivered word, a write's datum, or wdata's), the register
    file after (a snapshot), the next offset (default: st's target or pc + its length), the
    trap. bad: a form whose function the RTL does not build (only obad is compared)."""
    head = f"V {_rf_text(before)} {code6.hex()} {pc} {org} {mutate}"
    if bad:
        return f"{head} 0 0 0 0 0 0 0 0 1 0 0 {_rf_text(before)} 0"
    ret = code6[0] == 0xC3
    rec = (st.ea, st.port, st.sr, st.sw, st.count, int(st.taken),
           0 if ret or not st.taken else st.target, bf_cost_of(before, code6))
    if nxt is None:
        nxt = st.target if st.taken else (pc + st.length) & 0xFFFF
    cyc, req, odd, wi = [], None, 0, 0
    for c in st.cycles:
        if c.req != req:
            req, odd = c.req, c.addr & 1
        if c.kind.endswith("write"):
            d = wdata[wi] if wdata is not None else c.data
            wi += 1
        else:
            d = c.rdata
        split = c.w2 and odd and not c.kind.startswith("io")
        cyc.append(f"{RK[c.kind]} {int(c.w2)} {odd} {int(split and not c.last)} {int(c.last)} "
                   f"{d & 0xFFFF}")
    tail = _rf_text(after if after is not None else before)
    return (f"{head} {' '.join(map(str, rec))} 0 {nxt & 0xFFFF} {len(cyc)}"
            + "".join(" " + x for x in cyc) + f" {tail} {int(trap)}")


def bf_cost_of(regs: dict, code6: bytes) -> int:
    """(WP79) a bit field's cost (frozen templates.bf_cost of its offset and width registers,
    whole) from the register file before it (a funcref snapshot), 0 for any other form."""
    if code6[0] != 0x0F or code6[1] not in (0x31, 0x33, 0x39, 0x3B):
        return 0
    from .funcref import REG8
    from .sim.frozen.templates import BF_OPS, bf_cost
    r8 = lambda k: (regs[REG8[k][0]] >> REG8[k][1]) & 0xFF
    m = code6[2]
    width = code6[3] if code6[1] & 8 else r8((m >> 3) & 7)
    return bf_cost(BF_OPS[code6[1]], r8(m & 7), width)


def single_step(regs: dict, code6: bytes, mem: bytearray, pc: int, io_word: int | None = None):
    """(the Start, the register file after, trap) of the functional reference on one
    instruction at PS:pc (its bytes placed there) from regs (a snapshot) and mem."""
    from . import funcref
    cpu = funcref.Cpu(regs, mem, funcref.IO_WORD if io_word is None else io_word, 0)
    cpu.pfx = regs.get("pfx")
    base = regs["PS"] << 4
    for i, b in enumerate(code6 + b"\x90\x90"):
        mem[(base + ((pc + i) & 0xFFFF)) & 0xFFFFF] = b
    try:
        st = cpu.step(pc)
    except funcref.Trap as e:
        return e.start, None, True
    return st, cpu.snapshot(), False


def _random_regs(rnd) -> dict:
    from .funcref import REG16, SREG
    regs = {n: (rnd.choice(EDGES) if rnd.random() < 0.2 else rnd.randrange(1 << 16))
            for n in REG16 + SREG}
    # (F3) BRK clear: with it set the V35 takes the single step (vector 1) after the instruction
    regs["PSW"] = rnd.randrange(1 << 16) & ~0x0100
    regs["pfx"] = rnd.choice((None, None, None, 0, 1, 2, 3))
    return regs


def _case(rnd, base_mem: bytes, code6: bytes, regs: dict | None = None, pc: int | None = None,
          mutate: int = 0, operand: int | None = None):
    """A random-state vector of code6 and (S6) its whole-core test (c2_case): (line, C2Test), or
    None (outside the old RTL's decode or the reference's). operand: the memory operand's word
    (else the random memory's)."""
    from . import funcref
    if not rtl_decodes(code6):
        return None
    regs = dict(regs) if regs is not None else _random_regs(rnd)
    pc = rnd.randrange(0, 0xFFF0) if pc is None else pc
    mem = bytearray(base_mem)
    one = (0x05, 0xA8, 0xA9, 0x98, 0x99, 0x27, 0x2F, 0x37, 0x3F, 0xD4, 0xD5, 0xF5, 0xF8, 0xF9, 0xFA,
           0xFB, 0xFC, 0xFD)            # (WP79) no ModR/M byte
    page = code6[0] == 0x0F             # (WP79) the 0F page: the ModR/M byte the third
    if (operand is not None and code6[0] not in one and code6[0] & 0xF0 not in (0x70, 0x40)
            and not (page and code6[1] in (0x20, 0x22, 0x26, 0x31, 0x33, 0x39, 0x3B))):
        cpu = funcref.Cpu(regs, mem, funcref.IO_WORD, 0)
        cpu.cur = regs.get("pfx")
        mod, _, _, off, sb, _ = cpu.modrm(code6, 2 if page else 1)
        if mod != 3:
            for i in range(2):
                mem[(sb + ((off + i) & 0xFFFF)) & 0xFFFFF] = (operand >> (8 * i)) & 0xFF
    if not func_ok(code6):
        # (the old core's V35_EE_FUNC forms: only its error flag was compared; S6 runs them)
        try:
            st, after, trap = single_step(regs, code6, bytearray(mem), pc)
            test = c2_case(regs, code6, pc, st, after, trap, kind="old V35_EE_FUNC")
        except funcref.NotModelled:
            test = c2_case(regs, code6, pc, None, None, False, kind="reference not modelled")
        return rf_vector(regs, code6, pc, 0, None, None, mutate=mutate, bad=True), test
    try:
        st, after, trap = single_step(regs, code6, mem, pc)
    except funcref.NotModelled:
        return None
    return (rf_vector(regs, code6, pc, 0, st, after, mutate=mutate, trap=trap),
            c2_case(regs, code6, pc, st, after, trap))


def walk_vectors(chain, chain_base: int) -> list[tuple]:
    """(D2) every instruction start of the chain as the functional reference walks it (the
    prelude's tail first, as Machine; the taken transfers followed; a string form skipped):
    [(the vector, the six bytes, the code offset, (S6) its whole-core test)]."""
    from . import funcref
    run = funcref.chain_run(chain, chain_base)
    out = []
    for i, st in enumerate(run.starts):
        if not rtl_decodes(st.code):
            continue
        after = run.starts[i + 1].regs if i + 1 < len(run.starts) else run.final
        nxt = None
        if st.taken:                    # (chain_run made the target a code offset)
            nxt = (st.target + run.code_org) & 0xFFFF
        out.append((rf_vector(st.regs, st.code, st.pc, run.code_org, st, after,
                              bad=not func_ok(st.code)), st.code, st.pc,
                    c2_case(st.regs, st.code, st.ip, st, after, False, nxt=nxt,
                            kind="pass" if func_ok(st.code) else "old V35_EE_FUNC")))
    return out


# (S6) the --regfile forms whose decode is not the reference's (sst.py's DECODE_DIVERGENCE and
# MOV PS: 8E with the reg field's PS loads PS, the V20 then fetches from the new PS; the RTL's
# queue goes on at its linear address, no flush: the data book does not define PS as MOV's
# destination)
def code_divergence(code: bytes) -> str | None:
    """The DECODE_DIVERGENCE kind of an instruction's bytes (no prefix), or None."""
    o, m = code[0], code[1]
    if m < 0xC0 and (o, (m >> 3) & 7) in ((0xF6, 1), (0xF7, 1), (0xFF, 7)):
        return DECODE_DIVERGENCE[{0xF6: "F6.1", 0xF7: "F7.1", 0xFF: "FF.7"}[o]]
    if o == 0x8E and (m >> 3) & 3 == 1:
        return "8E: MOV PS,r/m (the queue not redirected)"
    return None


def c2_case(regs: dict, code6: bytes, ip: int, st, after: dict | None, trap: bool,
            nxt: int | None = None, kind: str = "pass") -> C2Test:
    """(S6) the whole-core test of one --regfile vector: the register file before (a funcref
    snapshot; a pending segment prefix becomes the prefix byte before the instruction, a start
    of its own), the code's six bytes at PS:ip, the bytes the reference's reads delivered (the
    aligned words), the register file after, the next IP (default: the target, or ip + the
    length), the bytes written, the I/O writes; st None (a form the reference does not model):
    the state before as the expected one (only a trap_nop passes it)."""
    pfx = regs.get("pfx")
    code, start, n = bytes(code6), ip, 1
    if pfx is not None:
        code, start, n = bytes([0x26 + 8 * pfx]) + code, (ip - 1) & 0xFFFF, 2
    base = (regs["PS"] & 0xFFFF) << 4
    ram = {}
    for i, b in enumerate(code):
        ram[(base + ((start + i) & 0xFFFF)) & 0xFFFFF] = b
    regs_in = {k: regs[k] for k in C2REGS}
    kind = code_divergence(code6) or kind
    if io_trap(code, regs["PSW"]):
        kind = IOT_KIND
    elif (regs["PSW"] >> 8) & 1:
        kind = STEP_KIND
    # (MX1) the prefix byte is the bench's (the reference holds a pending prefix as state, not
    # as a byte in its memory): an operand read that covers it reads the byte here and the
    # reference's memory there (a random register file's EA on the instruction's own address)
    pa = (base + start) & 0xFFFFF
    if st is not None and pfx is not None and any(
            c.kind == "read" and pa in (c.addr, (c.addr + 1) & 0xFFFFF) for c in st.cycles):
        kind = PFX_OVERLAP
    if st is not None and any(c.kind in ("read", "write") and c.addr >= 0xFFE00
                              for c in st.cycles):
        kind = "on-chip page"           # (the internal RAM and SFRs: not on the pins)
    if st is None:
        return C2Test("", n, regs_in, start, ram, dict(regs_in), (ip + 1) & 0xFFFF, {}, None,
                      2000, kind, len(code), IO_WORD_REF)
    fin = {}
    for c in st.cycles:
        if c.kind == "read":
            a = c.addr & 0xFFFFE
            ram.setdefault(a, c.rdata & 0xFF)
            ram.setdefault(a + 1, (c.rdata >> 8) & 0xFF)
        elif c.kind == "write":
            if c.width == "word":
                fin[c.addr] = c.data & 0xFF
                fin[(c.addr + 1) & 0xFFFFF] = (c.data >> 8) & 0xFF
            else:
                fin[c.addr] = (c.data >> 8 if c.width == "hi" else c.data) & 0xFF
    if trap:
        return C2Test("", n, regs_in, start, ram, None, limit=c2_limit([st]), kind="trap",
                      clen=n - 1 + st.length, ioword=IO_WORD_REF)
    if nxt is None:
        nxt = st.target if st.taken else (ip + st.length) & 0xFFFF
    return C2Test("", n, regs_in, start, ram, {k: after[k] for k in C2REGS}, nxt, fin,
                  c2_io([st]), c2_limit([st]), kind, n - 1 + st.length, IO_WORD_REF)


PFX_OVERLAP = "an operand read covers the bench's prefix byte"
SEG_WRAP = "reference: an odd word across the segment's end (V35 linear + 1, the suite's V20 wraps)"
# (F2b) an I/O form (IN OUT INM OUTM, behind any prefixes) run with PSW.BRKI 0: the V35 traps to
# vector 19 (silicon, validation/v35s/traps.py f2_iot); the reference (the V20's) does the I/O.
# Counted apart, not compared (the trap is gated by traps.py against the socket)
IOT_KIND = "the I/O trap (BRKI 0)"
# (F3) a vector run with PSW.BRK set: the V35 takes the single step (vector 1) after the
# instruction (silicon, validation/v35s/intr.py f3_step); the reference does not. Counted apart,
# not compared (the step is gated by intr.py against the socket)
STEP_KIND = "the single step (BRK 1)"


def io_trap(code: bytes, psw: int) -> bool:
    n = 0
    while n < len(code) - 1 and code[n] in (0x26, 0x2E, 0x36, 0x3E, 0xF2, 0xF3, 0x64, 0x65, 0xF0):
        n += 1
    op = code[n]
    return not (psw >> 1) & 1 and (0xE4 <= op <= 0xE7 or 0xEC <= op <= 0xEF or 0x6C <= op <= 0x6F)


EA_FORMS = (bytes([0x8B]), bytes([0x89]), bytes([0x8D]), bytes([0xC7]), bytes([0x01]),
            bytes([0xFF]), bytes([0x8F]), bytes([0xF7]), bytes([0x81]))


def alu_codes(rnd) -> list[bytes]:
    """(D2) one encoding of every ALU form the decoder knows, each operand kind (a register,
    [BW], [BP+d8] in SS, a direct address), with random registers and immediates (the shift
    counts from SHIFT_COUNTS)."""
    mems = (0x07, 0x46, 0x06)           # [BW], [BP+d8], direct

    def modrm(reg, kind):
        if kind == "r":
            return bytes([0xC0 | reg << 3 | rnd.randrange(8)])
        m = rnd.choice(mems)
        return bytes([m | reg << 3]) + bytes(rnd.randrange(256) for _ in range(
            1 if m == 0x46 else 2 if m == 0x06 else 0))

    def imm(n):
        v = rnd.choice(EDGES) if rnd.random() < 0.5 else rnd.randrange(1 << 16)
        return v.to_bytes(2, "little")[:n]

    out = []
    for kind in ("r", "m"):
        for op in range(8):
            for k in range(4):
                out.append(bytes([op * 8 + k]) + modrm(rnd.randrange(8), kind))
        for reg in range(8):
            out.append(bytes([0x81]) + modrm(reg, kind) + imm(2))
            out.append(bytes([0x83]) + modrm(reg, kind) + imm(1))
            out.append(bytes([0xC1]) + modrm(reg, kind) + bytes([rnd.choice(SHIFT_COUNTS)]))
            out.append(bytes([0xD1]) + modrm(reg, kind))
            out.append(bytes([0xD0]) + modrm(reg, kind))
            out.append(bytes([0xD3]) + modrm(reg, kind))
            if reg >= 2 or kind == "r":
                out.append(bytes([0xF6]) + modrm(reg, kind) + (imm(1) if reg < 2 else b""))
            out.append(bytes([0xF7]) + modrm(reg, kind) + (imm(2) if reg < 2 else b""))
            if reg < 2:
                out.append(bytes([0xFF]) + modrm(reg, kind))
        for o in (0x84, 0x85, 0x86, 0x87, 0x8C, 0x8E):
            out.append(bytes([o]) + modrm(rnd.randrange(8), kind))
    # (WP79) the 0F page: the bit ops (CL and imm index, byte and word), the digit rotates, the BCD
    # strings, the bit fields (reg and imm4 width); the register miscellany
    for kind in ("r", "m"):
        for sb in range(0x10, 0x20):
            out.append(bytes([0x0F, sb]) + modrm(rnd.randrange(8), kind)
                       + (bytes([rnd.randrange(256)]) if sb & 8 else b""))
        for sb in (0x28, 0x2A):
            out.append(bytes([0x0F, sb]) + modrm(rnd.randrange(8), kind))
        out.append(bytes([0xFE]) + modrm(rnd.randrange(2), kind))
        out.append(bytes([0x69]) + modrm(rnd.randrange(8), kind) + imm(2))
        out.append(bytes([0x6B]) + modrm(rnd.randrange(8), kind) + imm(1))
    for sb in (0x31, 0x33, 0x39, 0x3B):
        out.append(bytes([0x0F, sb]) + modrm(rnd.randrange(8), "r")
                   + (bytes([rnd.randrange(256)]) if sb & 8 else b""))
    out += [bytes([0x0F, sb]) for sb in (0x20, 0x22, 0x26)]
    out += [bytes([o]) for o in (0x98, 0x99, 0x27, 0x2F, 0x37, 0x3F, 0xF5, 0xF8, 0xF9, 0xFA, 0xFB,
                                 0xFC, 0xFD)] + [bytes([0x40 + k]) for k in range(16)]
    out += [bytes([0xD4]) + imm(1), bytes([0xD5]) + imm(1)]
    out += [bytes([0x05]) + imm(2), bytes([0xA8]) + imm(1), bytes([0xA9]) + imm(2), b"\x92"]
    out += [bytes([0x70 + k, rnd.randrange(256)]) for k in range(16)]
    out += [bytes([0xE2, rnd.randrange(256)])]
    return [(c + bytes(rnd.randrange(256) for _ in range(6)))[:6] for c in out]


def regfile_vectors(families, seed: int = 71, per_code: int = 3, per_alu: int = 64,
                    mutate: int = 0, tests: list | None = None) -> tuple[str, dict]:
    """The V35RF-2 vector file over the families' chains (see the section comment) and its
    counts (walk, random, modes, alu); (S6) tests: a list the vectors' whole-core tests
    (C2Test, their ids the vector's number) are appended to."""
    import random

    from .funcref import CODE_SEGMENT, SREG
    from .normalize import load_runs, normalize
    rnd = random.Random(seed)
    base_mem = rnd.randbytes(1 << 20)
    lines, seen, codes = [], set(), {}
    counts = {"walk": 0, "random": 0, "modes": 0, "alu": 0}

    def add(case, kind):
        if case is None:
            return
        line, test = case
        if line not in seen:
            seen.add(line)
            lines.append(line)
            counts[kind] += 1
            if tests is not None:
                test.tid = str(len(lines) - 1)
                tests.append(test)

    chains = set()
    for f in families:
        for rec in load_runs(f):
            s = normalize(rec)
            ch = s.chain
            key = (bytes(ch.code), tuple(sorted(ch.regs.items())),
                   getattr(ch, "prelude_marker", None), s.chain_base)
            if key in chains:
                continue
            chains.add(key)
            for line, six, k, test in walk_vectors(ch, s.chain_base):
                add((line, test), "walk")
                codes.setdefault(six, k)
    for six in sorted(codes):
        for _ in range(per_code):
            add(_case(rnd, base_mem, six), "random")
    for head in EA_FORMS:
        for mod in range(3):
            for rm in range(8):
                for reg in range(8):
                    if head[0] in (0xC7, 0x8F, 0x81) and reg:
                        continue                # /0 forms
                    if head[0] == 0xFF and reg != 6 or head[0] == 0xF7 and reg not in (4, 6):
                        continue                # PUSH r/m, MULU / DIVU
                    tail = bytes(rnd.randrange(256) for _ in range(4))
                    six = (head + bytes([mod << 6 | reg << 3 | rm]) + tail)[:6]
                    add(_case(rnd, base_mem, six), "modes")
    for _ in range(per_alu):
        for six in alu_codes(rnd):
            operand = rnd.choice(EDGES) if rnd.random() < 0.5 else rnd.randrange(1 << 16)
            regs = _random_regs(rnd)
            for r in ("AW", "DW", "CW"):
                if rnd.random() < 0.4:
                    regs[r] = rnd.choice(EDGES)
            if rnd.random() < 0.5:
                regs["PS"] = CODE_SEGMENT
                regs.update({n: 0 for n in SREG if n != "PS"})
            add(_case(rnd, base_mem, six, regs, operand=operand), "alu")
    text = "\n".join(lines) + "\n"
    if mutate:
        text = "\n".join(_mutated(ln, mutate) for ln in lines) + "\n"
    return f"{RFFORMAT} {len(lines)}\n" + text, counts


def _mutated(line: str, mutate: int) -> str:
    f = line.split()
    f[18] = str(mutate)          # V, 14 register fields, code, pc, code_org, mutate
    return " ".join(f)


def check_regfile(families, keep: Path | None = None, mutate: int = 0) -> tuple[int, dict, str]:
    """(S6) (the failures, the counts, the bench's output) of the --regfile vectors as
    single-instruction tests on the core v2's whole-core bench (c2_case, run_core2): counts the
    sources (walk, random, modes, alu), "vectors", and by kind: pass, trap (a divide error: the
    trap condition), "old V35_EE_FUNC" (the forms the old bench left out: run in full),
    "reference not modelled", "trap_nop" (the RTL decodes the form as trap_nop: not compared),
    "fail". mutate is the old bench's (not used here)."""
    tests: list = []
    _, counts = regfile_vectors(families, tests=tests)
    sm, res = run_core2(tests, keep, "regfile")
    counts["vectors"] = len(tests)
    bad, lines = 0, []
    apart = set(DECODE_DIVERGENCE.values()) | {"on-chip page", PFX_OVERLAP}
    for t in tests:
        r = res.get(t.tid)
        if t.kind in ("on-chip page", IOT_KIND, STEP_KIND):
            k = t.kind
        elif r is None:
            k = "pass" if t.kind in apart or t.kind.startswith("8E:") else t.kind
        elif r[0] == "TRAPNOP":
            k = "trap_nop" if t.kind == "pass" else f"trap_nop ({t.kind})"
        elif t.kind == "reference not modelled":
            k = "reference not modelled (ran, not compared)"
        elif t.kind in apart or t.kind.startswith("8E:"):
            k = f"divergence ({t.kind})"
        else:
            k = "fail" if t.kind == "pass" else f"fail ({t.kind})"
            bad += 1
            lines.append(r[1])
        counts[k] = counts.get(k, 0) + 1
    return bad, counts, "\n".join(lines)


# (S3, core v2) The function bench: v35_fn_pkg's pure functions (fpga/v35s/v35_rf_tb.sv) ------
#
# The core v2's datapath (fpga/v35s/core/v35/v35_eu.sv) reads its operands from the register RAM
# and applies v35_fn_pkg's functions (the ALU, the shifter, the multiplier, the divider stepped,
# the adjusts, the conditions). Its bench is a pure-function check, so it cannot take the
# V35RF-3 lines (an instruction's whole register file in and out, the old package's
# v35_execute): `--fn` derives one function-level line from each --regfile vector whose form is
# one function application on registers (the register forms of the ALU, TEST, the shifts,
# MUL / DIV, INC / DEC, the adjusts, the 70-7F conditions), the expected result and PSW the
# functional reference's (funcref.py) register file after it. Format V35FN-1, a line each:
#
#   <kind> <op> <w> <sgn> <a> <b> <n> <psw> <res> <psw after> <trap>
#
# kind A ALU (op the ALU op; res the result, not compared for CMP), T TEST (the ALU's AND, the
# PSW only), I INC / DEC (op 0 / 5: the ALU with CY kept), S shift (op the group's reg field, n
# the count), M MUL (res the 32-bit product: DW:AW, AW for a byte form), D DIV (a the dividend
# DW:AW / AW, b the divisor; res {remainder, quotient}; trap the divide error), J adjust (op 0-3
# ADJ4A ADJ4S ADJBA ADJBS, a AW, res AW), C condition (op the condition code, res taken).
FNBENCH = ROOT / "build" / "fpga" / "v35s" / "fn-tb" / "Vv35_rf_tb"
FNFORMAT = "V35FN-1"


def _fn_line(f: list) -> str | None:
    """The V35FN-1 line of one V35RF-3 vector's fields (None: not one function application)."""
    names = [n for n, _ in FFIELDS]
    before = dict(zip(names, map(int, f[1:15])))
    code = bytes.fromhex(f[15])
    pc = int(f[16])
    ncyc = int(f[29])
    tail = f[30 + 6 * ncyc:]
    after = dict(zip(names, map(int, tail[:14])))
    trap = int(tail[14])
    nxt = int(f[28])
    if int(f[27]):                      # a form whose function the old bench left out
        return None
    r16 = ("aw", "cw", "dw", "bw", "sp", "bp", "ix", "iy")

    def reg(regs, k, w):
        if w:
            return regs[r16[k]]
        return (regs[r16[k & 3]] >> (8 * (k >> 2))) & 0xFF

    o, m = code[0], code[1]
    md, rf, rm = m >> 6, (m >> 3) & 7, m & 7
    pw, pa = before["psw"], after["psw"]

    def line(kind, op, w, sgn, a, b, n, res):
        return f"{kind} {op} {w} {sgn} {a} {b} {n} {pw} {res} {pa} {trap}"

    if o < 0x40 and o & 7 < 4 and md == 3:
        w, op, d = o & 1, (o >> 3) & 7, bool(o & 2)
        dst, src = (rf, rm) if d else (rm, rf)
        return line("A", op, w, 0, reg(before, dst, w), reg(before, src, w), 0,
                    reg(after, dst, w) if op != 7 else 0)
    if o < 0x40 and o & 7 in (4, 5):
        w, op = o & 1, (o >> 3) & 7
        imm = int.from_bytes(code[1:3], "little") if w else code[1]
        return line("A", op, w, 0, reg(before, 0, w), imm, 0, reg(after, 0, w) if op != 7 else 0)
    if 0x80 <= o <= 0x83 and md == 3:
        w = o & 1
        imm = (int.from_bytes(code[2:4], "little") if o == 0x81
               else (code[2] | (0xFF00 if code[2] & 0x80 else 0)) if o == 0x83 else code[2])
        return line("A", rf, w, 0, reg(before, rm, w), imm, 0,
                    reg(after, rm, w) if rf != 7 else 0)
    if o in (0x84, 0x85) and md == 3:
        w = o & 1
        return line("T", 4, w, 0, reg(before, rm, w), reg(before, rf, w), 0, 0)
    if o in (0xA8, 0xA9):
        w = o & 1
        imm = int.from_bytes(code[1:3], "little") if w else code[1]
        return line("T", 4, w, 0, reg(before, 0, w), imm, 0, 0)
    if (o in (0xC0, 0xC1) or 0xD0 <= o <= 0xD3) and md == 3:
        w = o & 1
        n = code[2] if o in (0xC0, 0xC1) else 1 if o in (0xD0, 0xD1) else before["cw"] & 0xFF
        return line("S", rf, w, 0, reg(before, rm, w), 0, n, reg(after, rm, w))
    if o in (0xF6, 0xF7) and md == 3 and rf >= 4:
        w = o & 1
        b = reg(before, rm, w)
        if rf in (4, 5):
            p = (after["dw"] << 16 | after["aw"]) if w else after["aw"]
            return line("M", 0, w, rf & 1, reg(before, 0, w), b, 0, p)
        num = (before["dw"] << 16 | before["aw"]) if w else before["aw"]
        res = 0 if trap else ((after["dw"] << 16 | after["aw"]) if w else after["aw"])
        return line("D", 0, w, rf & 1, num, b, 0, res)
    if 0x40 <= o <= 0x4F:
        k = o & 7
        return line("I", 5 if o & 8 else 0, 1, 0, reg(before, k, 1), 1, 0, reg(after, k, 1))
    if o == 0xFE and md == 3 and rf in (0, 1):
        return line("I", 5 if rf else 0, 0, 0, reg(before, rm, 0), 1, 0, reg(after, rm, 0))
    if o in (0x27, 0x2F, 0x37, 0x3F):
        return line("J", {0x27: 0, 0x2F: 1, 0x37: 2, 0x3F: 3}[o], 0, 0, before["aw"], 0, 0,
                    after["aw"])
    if 0x70 <= o <= 0x7F:
        disp = code[1] - 256 if code[1] & 0x80 else code[1]
        if disp == 0:
            return None                 # taken and not taken alike
        taken = int(nxt == (pc + 2 + disp) & 0xFFFF)
        return line("C", o & 15, 0, 0, 0, 0, 0, taken)
    return None


def fn_vectors(families) -> tuple[str, dict]:
    """The V35FN-1 vector file of the families' --regfile vectors and its counts by kind."""
    text, _ = regfile_vectors(families)
    lines, counts = [], {}
    for ln in text.splitlines()[1:]:
        f = ln.split()
        if not f or f[0] != "V":
            continue
        out = _fn_line(f)
        if out is not None:
            lines.append(out)
            counts[out[0]] = counts.get(out[0], 0) + 1
    return f"{FNFORMAT} {len(lines)}\n" + "\n".join(lines) + "\n", counts


def check_fn(families, keep: Path | None = None) -> tuple[int, dict, str]:
    """(the bench's bad vectors, the counts, its output) of fn_vectors on the function bench."""
    import re
    text, counts = fn_vectors(families)
    with tempfile.TemporaryDirectory() as tmp:
        d = keep if keep is not None else Path(tmp)
        path = d / "fn.fnvec"
        path.write_text(text)
        p = subprocess.run([str(FNBENCH), str(path)], capture_output=True, text=True, cwd=ROOT)
    out = p.stdout + p.stderr
    m = re.search(r"SUMMARY vectors=(\d+) bad=(\d+)", out)
    if m is None:
        raise RuntimeError(f"function bench output:\n{out}")
    counts["vectors"] = int(m.group(1))
    return int(m.group(2)), counts, out


# (S6, core v2) The whole-core function bench (fpga/v35s/v35_core2_tb) -------------------------
#
# v35_top, the real slot module, runs one instruction per test from a preloaded state (the
# register RAM, the EU's flops, the first fetch's address: fpga/v35s/v35_core2_tb.sv / .vlt / .cpp,
# fpga/v35s/build_core2_tb.sh), its memory served by the bench from the test's bytes (any other
# byte 90h, I/O reads FFFFh), to the start of the next instruction; then its register file, PSW,
# segment registers, next PS:IP, memory writes and I/O writes are compared with the test's
# expected state (format V35SST-1, two lines a test: v35_core2_tb.cpp). Two producers:
# sst.py --rtl (SingleStepTests V20: sst_file) and --regfile (the --regfile vectors as single
# instructions: regfile_tests). A test whose instruction the RTL decodes as trap_nop (class 0,
# the unmodeled forms: template 0, CLOCKS 2, no bus) is reported as such (TRAPNOP), not compared.
# The old core's V35RF-3 unit bench (build/fpga/v35s/rf-tb/) was retired with that core (S7);
# fpga/v35s/v35_rf_tb.sv is now the function bench (--fn).

C2BENCH = Path(os.environ.get("V35_CORE2_TB", ROOT / "build" / "fpga" / "v35s" / "core2-tb"
                             / "Vv35_core2_tb"))    # (V35_CORE2_TB: another build)
C2FORMAT = "V35SST-1"
C2REGS = ("AW", "CW", "DW", "BW", "SP", "BP", "IX", "IY", "DS1", "PS", "SS", "DS0", "PSW")
C2WIDTH = {"word": 0, "lo": 1, "hi": 2}
SEG_PREFIXES = (0x26, 0x2E, 0x36, 0x3E)
IO_WORD_REF = 0x0000            # funcref.IO_WORD: the --regfile vectors' I/O reads (the board's)


@dataclass
class C2Test:
    """One V35SST-1 test: the state before (regs: C2REGS, ip, the listed memory), the starts it
    is, the state after (out: C2REGS, None for a divide error: the trap condition only), the
    memory bytes after, the I/O writes ([(port, width, data)], None: not compared)."""
    tid: str
    starts: int
    regs: dict
    ip: int
    ram: dict
    out: dict | None
    out_ip: int = 0
    fin: dict | None = None
    io: list | None = None
    limit: int = 2000
    kind: str = "pass"          # (the producer's class, not in the text)
    clen: int = 0               # the instruction's bytes from PS:ip (a fetch elsewhere: 90h)
    ioword: int = 0xFFFF        # every I/O read's word (the suite's FFFFh; the corpus's 0000h)

    def text(self) -> str:
        t = ["T", self.tid, str(self.starts), str(self.limit)]
        t += [str(self.regs[n] & 0xFFFF) for n in C2REGS] + [str(self.ip & 0xFFFF)]
        t += [str(self.clen), str(self.ioword)]
        t += [str(len(self.ram))] + [f"{a} {v}" for a, v in sorted(self.ram.items())]
        out = self.out or {n: 0 for n in C2REGS}
        fin = self.fin or {}
        e = ["E", "1" if self.out is None else "0"]
        e += [str(out[n] & 0xFFFF) for n in C2REGS] + [str(self.out_ip & 0xFFFF)]
        e += [str(len(fin))] + [f"{a} {v}" for a, v in sorted(fin.items())]
        e += [str(-1 if self.io is None else len(self.io))]
        e += [f"{p} {w} {d}" for p, w, d in (self.io or [])]
        return " ".join(t) + "\n" + " ".join(e)


def c2_io(starts) -> list:
    """The I/O writes of the reference's starts, as the bench reads them off the pins: (port,
    width, the datum on its lanes)."""
    return [(c.addr, C2WIDTH[c.width], c.data & (0xFFFF if c.width == "word" else 0xFF
                                                if c.width == "lo" else 0xFF00))
            for st in starts for c in st.cycles if c.kind == "io_write"]


def c2_written(starts) -> set:
    """The memory bytes the reference's starts write."""
    out = set()
    for st in starts:
        for c in st.cycles:
            if c.kind == "write":
                out.add(c.addr)
                if c.width == "word":
                    out.add((c.addr + 1) & 0xFFFFF)
    return out


def c2_limit(starts) -> int:
    """A test's clock limit from its reference's bus cycles (a bit field's: its cost, from its
    registers whole, up to 2047 clocks)."""
    bf = any(st.code[:1] == b"\x0f" and st.code[1:2] in (b"\x31", b"\x33", b"\x39", b"\x3b")
             for st in starts)
    return 400 + 60 * sum(len(st.cycles) for st in starts) + (2100 if bf else 0)


def run_core2(tests: list, keep: Path | None = None, name: str = "tests") -> tuple[dict, dict]:
    """(the bench's SUMMARY, {test id: (status, text)} of the tests that are not a pass: status
    FAIL, TRAPNOP or TIMEOUT) on a list of C2Test."""
    text = f"{C2FORMAT} {len(tests)}\n" + "\n".join(t.text() for t in tests) + "\n"
    with tempfile.TemporaryDirectory() as tmp:
        d = keep if keep is not None else Path(tmp)
        path = d / f"{name}.sstvec"
        path.write_text(text)
        p = subprocess.run([str(C2BENCH), str(path)], capture_output=True, text=True, cwd=ROOT)
    sm, res = {}, {}
    for line in p.stdout.splitlines():
        f = line.split(None, 2)
        if not f:
            continue
        if f[0] == "SUMMARY":
            sm = {k: int(v) for k, v in (x.split("=") for x in line.split()[1:])}
        elif f[0] in ("FAIL", "TRAPNOP", "TIMEOUT") and len(f) >= 2:
            res[f[1].rstrip(";")] = (f[0], line)
    if p.returncode not in (0, 1) or not sm:
        raise RuntimeError(f"bench exit {p.returncode}: {(p.stderr or p.stdout)[-400:]}")
    return sm, res


_MODRM = frozenset([o for o in range(0x40) if o & 7 < 4] + [0x62, 0x63, 0x69, 0x6B]
                   + list(range(0x80, 0x90)) + [0xC0, 0xC1, 0xC4, 0xC5, 0xC6, 0xC7]
                   + list(range(0xD0, 0xD4)) + list(range(0xD8, 0xE0)) + [0xF6, 0xF7, 0xFE, 0xFF])


def trap_nop_form(test: dict, stem: str) -> str:
    """The form a trap_nop test's instruction is, for the counted-apart table: a REP prefix
    before a non-string form, or the opcode file and its operand (reg / mem)."""
    from . import funcref as fr
    b = test["bytes"]
    k = 0
    while k < len(b) and b[k] in SEG_PREFIXES + (0xF0,):
        k += 1
    if k < len(b) and b[k] in fr.REP_PREFIXES:
        return "REP before a non-string form"
    m = None
    if k + 1 < len(b) and b[k] in _MODRM:
        m = b[k + 1]
    elif b[k] == 0x0F and k + 2 < len(b):
        m = b[k + 2]
    return stem + ("" if m is None else " reg" if m >= 0xC0 else " mem")


# (S6) the forms whose decode (the frozen model's templates.decode, the generated table) is not the
# V20's: F6 / F7 /1 with a memory operand (TEST's undocumented alias on the V20, an imm8 / imm16
# after the operand) decode as the rmw class with no immediate (a read, a write of the read's
# datum, the length one or two bytes short); a test that fails there is a divergence, not a
# failure
DECODE_DIVERGENCE = {"F6.1": "F6 /1 mem: decoded rmw, no immediate",
                     "F7.1": "F7 /1 mem: decoded rmw, no immediate",
                     # FF /7 with a memory operand: the V20 pushes it (PUSH r/m's alias); the
                     # decoder's rmw form reads it and writes it back
                     "FF.7": "FF /7 mem: decoded rmw (the V20's PUSH r/m)"}


def decode_divergence(test: dict, stem: str) -> str | None:
    """The DECODE_DIVERGENCE kind of a test (its memory form), or None."""
    if stem not in DECODE_DIVERGENCE:
        return None
    b = test["bytes"]
    k = 0
    while k < len(b) and b[k] in SEG_PREFIXES + (0xF0,):
        k += 1
    return DECODE_DIVERGENCE[stem] if k + 1 < len(b) and b[k + 1] < 0xC0 else None


def sst_test(test: dict, stem: str) -> tuple[str | None, str, C2Test | None]:
    """_sst_test, the test's clen its bytes (the instruction and its prefixes)."""
    c, kind, t = _sst_test(test, stem)
    if t is not None:
        t.clen = len(test["bytes"])
    return c, kind, t


def _sst_test(test: dict, stem: str) -> tuple[str | None, str, C2Test | None]:
    """(the class counted apart without the bench, or None; the test's kind; its C2Test) of one
    SingleStepTests test for the whole-core bench. The kinds: pass (the expected state the
    suite's), trap (a divide error: the trap condition only), the V20 classes (sst.V20_DIGITS,
    V20_FLAGS: the expected state the V35 reference's), "reference not modelled" (the suite's
    state, the I/O writes not compared)."""
    from . import sst
    c = sst.classify(test, stem, rtl=True)
    if c is not None:
        return c, "", None
    from . import funcref as fr
    fr.WRAP_SEEN = False
    r = sst.reference_v35_or_v20(test, stem)
    if fr.WRAP_SEEN:
        # (F5d) an odd word at offset FFFFh: the V35's second half is at the linear address + 1
        # (silicon, fuzz f5i / f5r wrapw), the suite's V20 wraps to the segment's offset 0000h
        # and lists no byte at the V35's address: counted apart
        return SEG_WRAP, "", None
    tid = str(test["idx"])
    r0 = test["initial"]["regs"]
    regs0, ip0 = {n: r0[k] for k, n in sst.REGMAP}, r0["ip"]
    ram = {a: v for a, v in test["initial"]["ram"]}
    regs = {n: regs0[n] for n in C2REGS}
    if r.cls in ("unlisted", "on-chip page", "fail"):
        return f"reference {r.cls}", "", None
    want, wip, wram = sst.expected(test)
    pre = []
    for b0 in test["bytes"]:
        if b0 not in (0x26, 0x2E, 0x36, 0x3E, 0xF0, 0xF2, 0xF3, 0x64, 0x65):
            break
        pre.append(b0)
    if r.cls == "not modelled" and any(b0 in (0xF2, 0xF3, 0x64, 0x65) for b0 in pre):
        # (F2b) a REP prefix before a non-string opcode: the V35 runs the opcode once, the prefix
        # ignored (silicon, traps.py's rep series, REP IDIV included: no quotient negation; the
        # core's rep_nx); the suite's (the V20's) state is not the V35's, and its divide error
        # enters vector 0, which the core does not build: counted apart
        return "reference not modelled: REP before a non-string opcode (V20)", "", None
    if r.cls == "not modelled":
        b = test["bytes"]
        n = 0
        while n < len(b) and b[n] in SEG_PREFIXES:
            n += 1
        return None, decode_divergence(test, stem) or "reference not modelled", C2Test(
            tid, n + 1, regs, ip0, ram, {k: want[k] for k in C2REGS}, wip, dict(wram), None, 3000)
    if r.cls == "trap":
        return None, "trap", C2Test(tid, len(r.starts), regs, ip0, ram, None,
                                    limit=c2_limit(r.starts))
    io = c2_io(r.starts)
    if r.cls == "pass":
        return None, decode_divergence(test, stem) or "pass", C2Test(
            tid, len(r.starts), regs, ip0, ram, {k: want[k] for k in C2REGS}, wip, dict(wram),
            io, c2_limit(r.starts))
    # a V20 class: the V35 reference's state after
    got = r.cpu.snapshot()
    fin = {a: r.cpu.mem[a] for a in set(ram) | c2_written(r.starts)}
    return None, r.cls, C2Test(tid, len(r.starts), regs, ip0, ram, {k: got[k] for k in C2REGS},
                               r.ip, fin, io, c2_limit(r.starts))


def sst_file(args) -> tuple[str, dict, list]:
    """(stem, {class: tests}, [failure text]) of one SingleStepTests file on the whole-core
    bench (sst_test, run_core2): the counted-apart classes (sst.classify's, the reference's),
    the kinds that ran (pass, trap, the V20 classes, reference not modelled), "trap_nop
    (<form>)" for a test the RTL decodes as trap_nop, "rtl fail (<kind>)" for a failure."""
    stem, keep, show = args
    from . import sst
    counts: dict = {}
    tests, kinds, forms = [], {}, {}
    for test in sst.load(stem):
        c, kind, t = sst_test(test, stem)
        if c is not None:
            counts[c] = counts.get(c, 0) + 1
            continue
        tests.append(t)
        kinds[t.tid] = kind
        forms[t.tid] = trap_nop_form(test, stem)
    sm, res = run_core2(tests, keep, f"sst-{stem}") if tests else ({}, {})
    fails = []
    for t in tests:
        st = res.get(t.tid)
        if st is None:
            k = "pass" if kinds[t.tid] in DECODE_DIVERGENCE.values() else kinds[t.tid]
        elif st[0] == "TRAPNOP":
            k = f"trap_nop ({forms[t.tid]})"
        else:
            k = (f"divergence ({kinds[t.tid]})" if kinds[t.tid] in DECODE_DIVERGENCE.values()
                 else f"rtl fail ({kinds[t.tid]})")
            if len(fails) < show:
                fails.append(f"    {stem} {st[1]}")
        counts[k] = counts.get(k, 0) + 1
    return stem, counts, fails


def check_sst(stems, keep: Path | None = None, jobs: int = 8, show: int = 3) -> dict:
    """{stem: {class: tests}} of the whole-core bench over SingleStepTests files (sst_file)."""
    from multiprocessing import get_context
    if not C2BENCH.exists():
        raise SystemExit(f"error: {C2BENCH} is missing (fpga/v35s/build_core2_tb.sh)")
    if keep:
        keep.mkdir(parents=True, exist_ok=True)
    out = {}
    with get_context("spawn").Pool(max(1, min(jobs, 8))) as pool:
        for stem, counts, fails in pool.imap(sst_file, [(s, keep, show) for s in stems]):
            out[stem] = counts
            for line in fails:
                print(line)
            print(f"{stem:<5} " + "  ".join(f"{k} {v}" for k, v in sorted(counts.items())),
                  flush=True)
    return out


# The command ------------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m validation.v35s.chains.rtl_vectors",
                                description=__doc__.split("\n\n")[0])
    p.add_argument("--family", nargs="+", required=True)
    p.add_argument("--regfile", action="store_true",
                   help="D1, D2: the families' forms and every ALU form; (S6) as single "
                   "instructions on the core v2's whole-core bench (v35_core2_tb.sv)")
    p.add_argument("--fn", action="store_true",
                   help="(S3, core v2) the function bench (v35_rf_tb.sv on v35_fn_pkg) on the "
                   "--regfile vectors that are one function application (format V35FN-1)")
    p.add_argument("--keep", type=Path, help="keep the vector files and bench outputs here")
    p.add_argument("--show", type=int, default=5, help="failing runs to show per family")
    args = p.parse_args(argv)
    if args.fn:
        if not FNBENCH.exists():
            print(f"error: {FNBENCH} is missing (fpga/v35s/build_rf_tb.sh)", file=sys.stderr)
            return 2
        if args.keep:
            args.keep.mkdir(parents=True, exist_ok=True)
        bad, counts, out = check_fn(args.family, args.keep)
        for line in out.splitlines()[:args.show]:
            if line.startswith("FAIL"):
                print("    " + line)
        kinds = "  ".join(f"{k} {v}" for k, v in sorted(counts.items()) if k != "vectors")
        print(f"fn {' '.join(args.family)}: {counts['vectors']} vectors ({kinds}), {bad} bad")
        return 1 if bad else 0
    if args.regfile:
        if not C2BENCH.exists():
            print(f"error: {C2BENCH} is missing (fpga/v35s/build_core2_tb.sh)", file=sys.stderr)
            return 2
        if args.keep:
            args.keep.mkdir(parents=True, exist_ok=True)
        bad, counts, out = check_regfile(args.family, args.keep)
        for line in out.splitlines()[:args.show]:
            if line.startswith("FAIL") or line.startswith("TIMEOUT"):
                print("    " + line)
        kinds = "  ".join(f"{k} {v}" for k, v in sorted(counts.items())
                          if k not in ("vectors", "walk", "random", "modes", "alu"))
        print(f"regfile {' '.join(args.family)}: {counts['vectors']} vectors (walk "
              f"{counts['walk']}, random {counts['random']}, modes {counts['modes']}, alu "
              f"{counts['alu']}) on the whole-core bench: {kinds}; {bad} bad")
        return 1 if bad else 0
    p.error("choose --fn or --regfile")
    return 2


if __name__ == "__main__":
    sys.exit(main())
