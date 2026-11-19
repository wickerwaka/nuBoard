"""The V35S core v2 microprogram assembler (MX0; docs/v35s-mechanisms.md section 4).

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.uasm [--check] [--list]

Reads the routines in fpga/v35s/core/v35/urom/*.uasm and writes, beside them in
fpga/v35s/core/v35/:

- v35_urom_b0.hex .. v35_urom_b2.hex  the ROM: one microinstruction per line, $readmemh word
                                      lists, bank k the word's bits 32k+31 .. 32k (the word is
                                      v35_pkg::v35_uword_t, zero-padded to 96 bits);
- v35_udecode_tbl.svh                 the decode table: v35_udec1 (the opcode byte -> the
                                      routine's entry and the format bits), v35_udec2 (the
                                      opcode and the popped ModR/M byte, or the 0F page's second
                                      byte -> the second entry and the group's operation),
                                      v35_umodrm / v35_upage (the bytes a ModR/M byte's or the
                                      0F second byte's pop adds to the instruction's bytes still
                                      to pop), the ROM's size and the reset entry.

The word (v35_pkg::v35_uword_t) is read from fpga/v35s/core/v35/v35_pkg.sv: its enums and
its struct are the single source of the layout; this module packs by them.

The word's fields (one line of a routine is one word, one CPU clock):

    ra rb       the register RAM's read ports A / B: a register selector (RS_*: REG RM OPR DST
                SRC AW CW DW BW SP BP IX IY SREG SOPR PS SS DS0 DS1 BASE INDEX)
    wr ws       the write port: a register selector (and PSW) and its data source
    wid         the width of the word's register accesses and ALU op (FMT BYTE WORD HIGH)
    d1 s1 d2 s2 two moves into a temporary (TA TB TC), the address register (ADDR) or the write
                datum (OPRW), from a source (SR_*: ZERO RA RB TA TB TC SIG IMM IMM8 OPR PSW ONES
                DISP ADDR ONE)
    alu ax ay   the ALU operation (AL_*) and its operands; wf: the flags written (W)
    ea          the EA step (DISP: the address register from the popped displacement; BI: base
                + index + displacement)
    bus seg     a bus request on the A1 port (MEMR MEMW IOR IOW) and its segment (DEF SS DS1)
    pop         a queue byte popped into MODRM IL IH DL DH
    e f         E (the next opcode popped; exactly one word follows) and F (wait for the datum)
    cnt         the loop counter's load (RB IL BITS LEN)
    seq         jmp=L  jc=COND:L  jnc=COND:L  call=L  ret  loop=L  ((qprobe round 17) dispm
                withdrawn)  (the word after E is
                the dispatch, DISP, set by the assembler); (F5e) tki=L a REP string's take point:
                L when an interrupt is taken there, else the next word (the book check: the next)
    pfx flush halt trap
    ro rl=K bi  (qprobe rules 3 and 5) the releases: ro the next opcode released from the
                queue's occupancy (the model's N), rl=K operand bytes released (its P); bi the
                word waits while a fetch cycle started on an earlier clock runs (its last clock
                included). A routine that names no `ro` and no `rl` gets the default: every pop
                word releases its byte, every E word the next opcode, and a short transfer's
                displacement (popped by the E word with the opcode) is released by the routine's
                first word; a routine that names either states all of its releases (checked:
                one `ro` per E, the `rl` sum the pops' bytes)
                (qprobe round 6) the bus waits by the word's kind: `bi` (B, F) while a
                fetch's pin cycle started on an earlier clock runs (its last clock included);
                rl=x (X, S, A: a word that releases nothing) while the bus unit's slot is
                taken; rl=x with bi (Y, a memory request word) while a fetch started earlier
                has two clocks or more left. The word after E may post an I/O write (the
                cycle after the boundary: EU_HOLD)
    (qprobe rule 12) a routine header's lead=K: the boundary into its opcode comes no sooner
                than K clocks after the opcode's release (the decode's `lead`)
    (qprobe rule 11) a routine header's hlt=1: from its opcode's release nothing more is
                fetched and a request posted is granted a clock later (the decode's `hlt`)
    (qprobe round 22, spec 18 A3) a routine header's ml=1 (ModR/M memory cells only): the
                boundary's three-byte test behind the staged opcode counts the bytes a fetch
                delivers on its last clock (the decode's `v35_uml`, of the opcode and the ModR/M
                byte: CALL / JMP near and far through memory)

No field is a count of clocks, a class, an attribute of another instruction or of the bus
unit; the loop counter is loaded only from CL (RB), an immediate (IL), the operand's bit count
(BITS) or the instruction's remaining bytes (LEN, the trap routine).

The language (one file per routine family):

    ; a comment
    routine NAME [op=LIST] [mod=reg|mem|any] [reg=LIST] [page=0f] [ea=book|bare]
        [book="FORM" [width=byte|word]] [bookx="EXPR"] [n=K] [diff=K | diff=PATH:K,...]
        [why="..."] [measured="..."]
    [label:] field=value field=value flag ...   ; the act of the word (required)

op LIST: hex bytes and ranges (00-03,08-0B). An opcode with a ModR/M byte enters its
routine through the second level: the E word that pops the opcode pops its ModR/M byte too, and
the dispatch (DISP) reads v35_udec2 of the two registers; `mod`/`reg`/`rm` select the
second-level cells a routine takes. Every cell without a routine decodes to the
trap routines (the instruction's bytes popped by its format's length, then E).

The book check (test_uasm.BookCheck): every routine with `book=` names a form of the data
book's clock table (build/validation/v35s/v35_book_clocks.json); `length()` runs the routine
from its entry at EA = 3, W = 0 with no queue stall (a bus
cycle 3 clocks, the request granted the clock after the post, the F word and a memory write's
RAMEN hold at E waiting for the datum / the cycle's end) and counts the clocks to the successor's
first word. It must equal the book's value at n (the routine's `n`, default 4) plus the
declared `diff`, whose `why` names the mechanism or the measured V35S cost that explains it.

(MX1) The memory forms (`mod=mem`): the routine's first word is the EA's add (`ea=BI`, base +
index + the displacement into the address register). The displacement's pops are the EA heads
(ea.uasm), entered from the dispatch: the word after E of a ModR/M memory cell dispatches to the
head of its mode and loads the return register with the routine's entry (a call from the
dispatch: the V20 loader's mode branch, S_D8 / S_D16, before the routine's first row), the head
pops the displacement bytes and returns. Two sets, by the routine's header: `ea=book` (the
default: the book's EA clocks, EA 3 at mod 00 and 01 and the direct form, 4 at mod 10, each one
the pops, the add and an OPEN word where the pops and the add do not fill the book's EA; at
mod 00 one OPEN word, the second book clock a book error, docs/v35s-eu-timing.md M4) and
`ea=bare` (the pops alone: mod 00 enters the routine's add directly). The paths the book check
runs: m00 (mod 00, a register: EA 3), d8 (mod 01: EA 3), d16 (mod 10: EA 4), dir (mod 00 rm 110,
the direct address: EA 3). `diff=K` declares K on every path; `diff=m00:K,d8:K,d16:K,dir:K` per
path (a path not named: 0). A head's own `diff=` (eab0's) adds to the routine's on its path.
`bookx=` is the book's formula where its table has no row of its own (a note's formula, e.g.
the memory shift by imm8).

(qprobe round 12) `mod=m00` / `m01` / `m10` (with `rm=`): ModR/M cells of one mode that are not
memory cells: the dispatch enters the routine directly (no EA head), and the routine pops its
own displacement and releases it where the measured shape does (JMP / CALL [d16] and the far
forms, POP mem with a displacement). The opcode's second-level entry then depends on the mode:
(the dispatch reads v35_udec2 of the registered ModR/M byte whole; (qprobe round 17) no
limit on such opcodes). `trap` is the sequencing value TRAP (the
next word; the divide error's strobe). `bus=MEMWD` posts a write whose datum is armed by a later
word (K: the first that loads OPRW): v35_eu rq_un, spec 7 A2. (qprobe round 18) `bus=RSV` is
the reserving word of a request posted later in the routine (spec 13 A1 / Q69: the C7 / 81 cells'
word that releases the displacement): it posts nothing (v35_eu rq_rs, to the post; the bus unit
reads it as an announced request); it is a bus-idle word's (`bi`). (qprobe round 20) `strict`
is the strict bus-idle word (spec 16 A1): `bi` with the wait's second kind (as the commit word C),
on every bus-idle word that releases a word-wide operand (rl=2: d16, imm16, a far segment).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V35 = ROOT / "fpga" / "v35s" / "core" / "v35"
UROM = V35 / "urom"
PKG = V35 / "v35_pkg.sv"
BOOK = ROOT / "build" / "validation" / "v35s" / "v35_book_clocks.json"
BANK_BITS = 32
BANKS = 3
# (qprobe round 12) the ROM in two parts: words 0-2047 in v35_urom_b0..b2.hex (2,048 x 2 blocks), the
# words from 2048 on in v35_urom_b3..b5.hex (a 512-word part: v35_useq's rom3..rom5), so that no
# address bit drives 4,096 x 1 blocks (the sequencer's address timing)
ROM_LO = 2048
ROM_HI = 1024   # (qprobe round 20) the high part 1,024 words (512 before)
OUT_FILES = tuple(f"v35_urom_b{b}.hex" for b in range(2 * BANKS)) + ("v35_udecode_tbl.svh",)
UADDR_W = int(re.search(r"localparam\s+int\s+UADDR_W\s*=\s*(\d+)", PKG.read_text()).group(1))

# the enum prefix and the field names of the word (read from the package)
PREFIX = {"v35_rsel_e": "RS_", "v35_wid_e": "WD_", "v35_src_e": "SR_", "v35_mvd_e": "MD_",
          "v35_alu_e": "AL_", "v35_ea_e": "EA_", "v35_bus_e": "BQ_", "v35_seg_e": "SG_",
          "v35_pop_e": "PP_", "v35_cnt_e": "CN_", "v35_seq_e": "SQ_", "v35_cond_e": "CD_",
          "v35_rl_e": "RL_"}


class UasmError(RuntimeError):
    pass


# ------------------------------------------------------------------ the word's layout
def read_pkg(text: str | None = None) -> tuple[dict, list]:
    """(enums {type: {NAME: value}}, fields [(name, type, width)] MSB first) of v35_pkg.sv."""
    text = text if text is not None else PKG.read_text()
    text = re.sub(r"//[^\n]*", "", text)
    enums = {}
    for m in re.finditer(r"typedef\s+enum\s+logic\s*\[(\d+):0\]\s*\{(.*?)\}\s*(\w+)\s*;", text,
                         flags=re.S):
        vals = {}
        for n, v in re.findall(r"(\w+)\s*=\s*\d+'d(\d+)", m.group(2)):
            vals[n] = int(v)
        enums[m.group(3)] = (int(m.group(1)) + 1, vals)
    m = re.search(r"typedef\s+struct\s+packed\s*\{(.*?)\}\s*v35_uword_t\s*;", text, flags=re.S)
    if not m:
        raise UasmError("v35_pkg.sv: no v35_uword_t")
    fields = []
    for line in m.group(1).split(";"):
        line = line.strip()
        if not line:
            continue
        a = re.match(r"(\w+)\s+(\w+)$", line)
        b = re.match(r"logic\s*\[UADDR_W-1:0\]\s+(\w+)$", line)
        c = re.match(r"logic\s+(\w+)$", line)
        if b:
            fields.append((b.group(1), "addr", UADDR_W))
        elif c:
            fields.append((c.group(1), "bit", 1))
        elif a and a.group(1) in enums:
            fields.append((a.group(2), a.group(1), enums[a.group(1)][0]))
        else:
            raise UasmError(f"v35_pkg.sv: field {line!r}")
    return enums, fields


ENUMS, FIELDS = read_pkg()
WORD_BITS = sum(w for _, _, w in FIELDS)
FIELD_TYPE = {n: t for n, t, _ in FIELDS}


def enum_value(ftype: str, name: str) -> int:
    width, vals = ENUMS[ftype]
    key = PREFIX[ftype] + name.upper()
    if key not in vals:
        raise UasmError(f"{name!r} is not a {ftype} ({', '.join(vals)})")
    return vals[key]


def pack(word: dict) -> int:
    v = 0
    for name, ftype, width in FIELDS:
        x = word.get(name, 0)
        if x >= 1 << width:
            raise UasmError(f"field {name} = {x} does not fit {width} bits")
        v = (v << width) | x
    return v


def unpack(v: int) -> dict:
    out = {}
    for name, ftype, width in reversed(FIELDS):
        out[name] = v & ((1 << width) - 1)
        v >>= width
    return out


# ------------------------------------------------------------------ the opcode formats
def _ranges(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a, 16), int(b, 16) + 1))
        else:
            out.append(int(part, 16))
    return out


MODRM_OPS = set(_ranges("00-03,08-0B,10-13,18-1B,20-23,28-2B,30-33,38-3B,62,69,6B,80-8F,"
                        "C0,C1,C4-C7,D0-D3,D8-DF,F6,F7,FE,FF"))
# (F5g) D6: CLR1 r/m8 with the bit number in the ModR/M reg field (silicon, validation/v35s/d6.py
# f5_d6 / f5_d6b, both sessions): a ModR/M byte and its displacement, no immediate (so v35_umimm
# and v35_umodrm's text are unchanged); its second level carries the reg field as op3, as the
# groups' do (D6_BITREG below), the bit number the routine's mask is built from (zz_late.uasm d6clr)
D6_BITREG = 0xD6
MODRM_OPS.add(D6_BITREG)
# the immediate bytes of a form without a ModR/M byte
IMM_PLAIN = {**{o: 1 for o in _ranges("04,0C,14,1C,24,2C,34,3C,6A,70-7F,A8,B0-B7,CD,D4,D5,"
                                      "E0-E7,EB,63,F1")},
             **{o: 2 for o in _ranges("05,0D,15,1D,25,2D,35,3D,68,A0-A3,A9,B8-BF,C2,CA,E8,"
                                      "E9")},
             0xC8: 3, 0xEA: 4, 0x9A: 4}
SEG_PREFIX = {0x26: 0, 0x2E: 1, 0x36: 2, 0x3E: 3}      # the sreg: 0 DS1, 1 PS, 2 SS, 3 DS0
# (MX2) the short transfers (a one-byte displacement: Bcond, DBNZNE / DBNZE / DBNZ, BCWZ, BR
# short); the loop forms' conditions (the decode's xc: DBNZNE's NZ and DBNZE's Z (5, 4: the PSW
# condition the loop continues on), 16 SIGMA != 0 (DBNZ: CW - 1), 17 SIGMA == 0 (BCWZ: CW));
# BRK 3 / BRKV's vector numbers
SHORT_XFER = set(_ranges("70-7F,E0-E3,EB"))
XC_LOOP = {0xE0: 5, 0xE1: 4, 0xE2: 16, 0xE3: 17}
BRK_VEC = {0xCC: 3, 0xCE: 4}
FLAG_OP = {0xF8: 0, 0xF9: 1, 0xF5: 2, 0xFA: 3, 0xFB: 4, 0xFC: 5, 0xFD: 6}
# (MX3b) the adjusts' operation (v35_adjust's aop): 0 ADJ4A, 1 ADJ4S, 2 ADJBA, 3 ADJBS
ADJUST_OP = {0x27: 0, 0x2F: 1, 0x37: 2, 0x3F: 3}
# (MX4) the REP prefixes (F3 REP / REPE, F2 REPNE, 65 REPC, 64 REPNC): the E word pops the
# string opcode behind one with it (the 0F page's structure: `pg`), the dispatch reads the second
# level on it; the prefix's condition (the decode's xc: the PSW condition a REP compare goes on
# while it holds, as 70-7F's: Z 4, NZ 5, CY 2, NC 3); the string opcodes (bit 0 the width) and
# the compares (CMPBK A6 / A7, CMPM AE / AF: the group's CMP, op3 7)
REP_XC = {0xF3: 4, 0xF2: 5, 0x65: 2, 0x64: 3}
STR_OPS = set(_ranges("6C-6F,A4-A7,AA-AF"))
STR_CMP = set(_ranges("A6,A7,AE,AF"))
# the 0F page (the second byte): ModR/M present, immediate bytes after it
PAGE1_MODRM = set(_ranges("10-1F,28,2A,31,33,39,3B,2D,94,95"))
PAGE1_IMM = {**{o: 1 for o in _ranges("18-1F,39,3B,FF")}, 0x9C: 3}
# (F2b) the I/O forms: with PSW.BRKI 0 the dispatch enters the I/O trap (vector 19)
IO_OPS = set(_ranges("E4-E7,EC-EF,6C-6F"))
IOT = "iot"
INT = "intr"            # (F3) the interrupt entry: the dispatch's target when an interrupt is taken


def imm_modrm(op: int, reg: int) -> int:
    """The immediate bytes after the ModR/M byte and its displacement."""
    if op in (0x80, 0x82, 0x83, 0x6B, 0xC0, 0xC1, 0xC6):
        return 1
    if op in (0x81, 0x69, 0xC7):
        return 2
    if op == 0xF6 and reg in (0, 1):
        return 1
    if op == 0xF7 and reg in (0, 1):
        return 2
    return 0


def disp_bytes(modrm: int) -> int:
    md, rm = modrm >> 6, modrm & 7
    return {0: 2 if rm == 6 else 0, 1: 1, 2: 2, 3: 0}[md]


def fmt_of(op: int) -> dict:
    """The first level's format bits of an opcode (the encoding, not a routine's attribute)."""
    f = {"has_modrm": op in MODRM_OPS, "w": 0, "d": 0, "immw": 0, "sx": 0, "op3": 0, "seg": 0,
         "len": IMM_PLAIN.get(op, 0), "e2": 0, "xc": 0, "pg": 0, "rp": 0}
    if op < 0x40 and op & 7 < 6:
        f["w"], f["d"], f["op3"] = op & 1, (op >> 1) & 1, (op >> 3) & 7
        f["immw"] = int(op & 7 == 5)
    elif op in (0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x8B):
        f["w"], f["d"] = op & 1, (op >> 1) & 1 if op >= 0x88 else 0
    elif op in (0x8C, 0x8E, 0x8D, 0x8F, 0xC4, 0xC5, 0x62, 0x69, 0x6B):
        f["w"] = 1
        f["d"] = 1 if op == 0x8E else 0
        f["immw"] = int(op == 0x69)
        f["sx"] = int(op == 0x6B)
        if op in (0x69, 0x6B):
            f["op3"] = 5                 # (MX3b) the signed multiply (the F7 group's /5: MULI's op3 0)
    elif 0x80 <= op <= 0x83:
        f["w"] = int(op in (0x81, 0x83))
        f["immw"] = int(op == 0x81)
        f["sx"] = int(op == 0x83)
    elif 0x40 <= op <= 0x5F or 0x91 <= op <= 0x97 or op in (0x90, 0x98, 0x99, 0x68, 0x6A,
                                                             0x9C, 0x9D):
        f["w"] = 1
        f["immw"] = int(op == 0x68)
        f["sx"] = int(op == 0x6A)
        f["op3"] = (op >> 3) & 1 if 0x40 <= op <= 0x4F else 0
    elif 0xB0 <= op <= 0xBF:
        f["w"] = int(op >= 0xB8)
        f["immw"] = int(op >= 0xB8)
    elif op in (0xA8, 0xA9, 0xA0, 0xA1, 0xA2, 0xA3, 0xC6, 0xC7, 0xC0, 0xC1, 0xD0, 0xD1, 0xD2,
                0xD3, 0xE4, 0xE5, 0xE6, 0xE7, 0xEC, 0xED, 0xEE, 0xEF, 0xF6, 0xF7, 0xFE, 0xFF):
        f["w"] = op & 1
        f["immw"] = int(op in (0xA9, 0xC7, 0xF7))
    elif op in FLAG_OP:
        f["op3"] = FLAG_OP[op]
    elif op in ADJUST_OP:
        f["op3"] = ADJUST_OP[op]         # (MX3b) the adjust's operation (AL_ADJ: op3 1:0)
    elif op in (0xEA, 0x9A, 0xE8, 0xE9, 0xC2, 0xCA):
        f["w"] = 1
        f["immw"] = 1                    # (MX2) the word displacement, offset or stack adjust
    if op in SHORT_XFER:
        # (MX2) a short transfer: its displacement byte sign-extended and popped by the E word
        # with the opcode (the frozen model's take on the start clock); its condition by the
        # encoding (the PSW condition of the low nibble, or the loop forms' counter tests)
        f["w"], f["sx"], f["e2"] = 1, 1, 1
        f["xc"] = op & 0x0F if op < 0x80 else XC_LOOP.get(op, 0)
    if op in BRK_VEC:
        f["w"], f["op3"] = 1, BRK_VEC[op]    # (MX2) BRK 3 / BRKV: the vector number; BRKV's
        f["xc"] = 0                          # condition V (70's)
    if op in (0xCD, 0xC3, 0xCB, 0xCF):
        f["w"] = 1                       # (MX2) the words a break or a return moves
    if op in SEG_PREFIX:
        f["seg"] = 4 | SEG_PREFIX[op]
    if op == 0x0F:
        f["len"] = 1                     # the page's second byte
        f["pg"] = 1                      # (MX3c) popped by the E word with the opcode (into mp)
    if op in REP_XC:
        # (qprobe round 12, spec 7 A3) the REP prefix is its own two-word routine (str.uasm rep_p,
        # as a segment prefix): `rp` makes its E pop take the prefix alone (into the ModR/M
        # register as well), the dispatch reads the REP page (`pg`) at the prefix's own byte
        # (rep_p's cell), and rep_p's E word (ea=REP, F5d's mechanism) pops the string opcode
        # into the page; nothing else after the prefix belongs to it (len 0)
        f["pg"] = 1
        f["rp"] = 1
        f["xc"] = REP_XC[op]             # the compare's repeat condition
    if op in STR_OPS:
        f["w"] = op & 1                  # (MX4) the string forms' width
        f["op3"] = 7 if op in STR_CMP else 0     # the compares: CMP
    return f


def page_w(b: int) -> int:
    """(MX3c) the 0F page's operand width by the second byte (the encoding's): the bit
    operations' bit 0 (10-1F), the bit fields' word (31 33 39 3B); the BCD strings and the
    digit rotates bytes."""
    if 0x10 <= b <= 0x1F:
        return b & 1
    return int(b in (0x31, 0x33, 0x39, 0x3B))


# ------------------------------------------------------------------ parsing
@dataclass
class Word:
    fields: dict
    act: str
    line: int
    label: str | None = None
    refs: dict = field(default_factory=dict)       # tgt: label
    post_e: bool = False
    open: bool = False      # a word the measured cost needs whose act the sources do not name


@dataclass
class Routine:
    name: str
    path: str
    line: int
    head: dict
    words: list = field(default_factory=list)
    base: int = 0


SEQ_FIELDS = {"jmp", "jc", "jnc", "call", "loop", "eac", "tki"}
# (F2b) the trap vectors a word names with vec= (the data book's vector table, docs/v35s-
# differences.md section 5): CHKIND 5, the FPO escapes 7, the I/O trap 19
VECTORS = {"CHK": 5, "FPO": 7, "IOT": 19, "DIV": 0, "STEP": 1}
FLAGS = {"wf", "e", "f", "pfx", "flush", "halt", "ret", "dispm", "susp", "ist", "nb",
         "ro", "bi"}


def _tokens(s: str) -> list[str]:
    return re.findall(r'\w+="[^"]*"|\S+', s)


def parse_word(text: str, path: str, ln: int) -> Word:
    code, _, act = text.partition(";")
    act = act.strip()
    if not act:
        raise UasmError(f"{path}:{ln}: a word without a comment naming its act")
    label = None
    m = re.match(r"\s*(\w+):(?!\S)", code)
    if m:
        label = m.group(1)
        code = code[m.end():]
    fields, refs = {}, {}
    is_open = False
    for tok in code.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            k = k.lower()
            if k == "vec":
                # (F2b) the trap routines' vector by name (VECTORS): SR_VEC reads it from the
                # word's tgt field
                if v.upper() not in VECTORS:
                    raise UasmError(f"{path}:{ln}: unknown vector {v!r}")
                fields["vk"] = 1
                fields["tgt"] = VECTORS[v.upper()]
            elif k in SEQ_FIELDS:
                fields["seq"] = enum_value("v35_seq_e", k)
                if k in ("jc", "jnc"):
                    cond, _, v = v.partition(":")
                    fields["cond"] = enum_value("v35_cond_e", cond)
                refs["tgt"] = v
            elif k in FIELD_TYPE and FIELD_TYPE[k] in ENUMS:
                fields[k] = enum_value(FIELD_TYPE[k], v)
            else:
                raise UasmError(f"{path}:{ln}: unknown field {k!r}")
        else:
            k = tok.lower()
            if k == "open":
                is_open = True
            elif k == "ret":
                fields["seq"] = enum_value("v35_seq_e", "ret")
            elif k == "dispm":
                # (qprobe round 17) withdrawn: the sequencer has no DISPM source (no routine used
                # it; the second level's entry on the ROM address was the core's worst path)
                raise UasmError(f"{path}:{ln}: dispm is withdrawn (the sequencer has no DISPM source)")
            elif k == "trap":
                # (qprobe round 12) the divide error raised: the sequencing's TRAP (the next word;
                # the word's own bit freed for the ROM's twelfth address bit)
                if "seq" in fields:
                    raise UasmError(f"{path}:{ln}: trap is a sequencing value (no other seq)")
                fields["seq"] = enum_value("v35_seq_e", "trap")
            elif k == "strict":
                # (qprobe round 20, spec 16 A1, Q88 / Q89 / Q94) the strict bus-idle word: a
                # bus-idle word (bi) that releases a word-wide operand (d16, imm16, the far
                # pointer's segment: rl=2) also waits on the clock a back-to-back / chained fetch
                # starts. In the word: bi with the wait's second kind (vk), the level the commit
                # word C already waits on (v35_bus ph_nx: b2s_nx); no other bit
                fields["bi"] = 1
                fields["vk"] = 1
                fields["alt"] = 1
                fields["_strict"] = 1
            elif k == "alt":
                # (qprobe round 10) the bus wait's second kind, in the word's vk bit (read by
                # SR_VEC alone): with bi C (the commit word), with rl=x and bi V (the late
                # request word), with rl=x alone A (LAG_FIRST: not on a lagged slot's first clock)
                fields["vk"] = 1
                fields["alt"] = 1
            elif k in FLAGS and FIELD_TYPE.get(k) == "bit":
                fields[k] = 1
            else:
                raise UasmError(f"{path}:{ln}: unknown flag {tok!r}")
    if fields.pop("_strict", 0) and (fields.get("rl") != 2):
        raise UasmError(f"{path}:{ln}: strict is the bus-idle word that releases a word-wide "
                        "operand (rl=2)")
    if fields.get("bus") == enum_value("v35_bus_e", "rsv") and not fields.get("bi"):
        raise UasmError(f"{path}:{ln}: bus=RSV is a bus-idle word's (bi): the reserving word")
    if fields.get("ea") == enum_value("v35_ea_e", "bi") and fields.get("bus"):
        raise UasmError(f"{path}:{ln}: the EA's add posts (the request reads the address "
                        "register a word later)")
    if fields.get("seg") == enum_value("v35_seg_e", "nbi") and (fields.get("bus") or not fields.get("e")):
        raise UasmError(f"{path}:{ln}: seg=NBI is a fact of an E word that posts nothing")
    if fields.get("ea") == enum_value("v35_ea_e", "rep") and (fields.get("bus") or not fields.get("e")
                                                              or fields.get("seq")):
        raise UasmError(f"{path}:{ln}: ea=REP is a fact of an E word that posts nothing (F5d)")
    if fields.pop("alt", 0):
        vec = enum_value("v35_src_e", "vec")
        if not (fields.get("bi") or fields.get("rl") == RL_X) or "tgt" in fields or vec in (fields.get(k) for k in ("ws", "s1", "s2", "ax", "ay")):
            raise UasmError(f"{path}:{ln}: alt is a bus-wait word's (bi or rl=x) and shares the vk bit: "
                            "no vector, no SR_VEC source")
    if is_open and not act.startswith("OPEN"):
        raise UasmError(f"{path}:{ln}: an open word's comment must start OPEN")
    if act.startswith("OPEN") and not is_open:
        raise UasmError(f"{path}:{ln}: an OPEN comment on a word that is not open")
    return Word(fields, act, ln, label, refs, open=is_open)


def parse_file(path: Path) -> list[Routine]:
    routines = []
    cur = None
    for ln, raw in enumerate(path.read_text().splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith(";"):
            continue
        if s.startswith("routine "):
            toks = _tokens(s[len("routine "):])
            head = {}
            for t in toks[1:]:
                k, _, v = t.partition("=")
                head[k] = v.strip('"')
            cur = Routine(toks[0], path.name, ln, head)
            routines.append(cur)
            continue
        if cur is None:
            raise UasmError(f"{path.name}:{ln}: a word outside a routine")
        cur.words.append(parse_word(s, path.name, ln))
    return routines


def _finish(r: Routine) -> None:
    """The word after E: present (exactly one) or implicit; it is the dispatch (DISP)."""
    i = 0
    while i < len(r.words):
        if not r.words[i].fields.get("e"):
            i += 1
            continue
        nxt = r.words[i + 1] if i + 1 < len(r.words) else None
        if nxt is None or nxt.label is not None:
            nxt = Word({}, "the word after E: nothing left (the successor's decode)", r.words[i].line)
            r.words.insert(i + 1, nxt)
        # (qprobe round 6) it may release the opcode the E word popped (`ro`: a store's N on
        # the model's boundary word), nothing else
        if nxt.fields.get("pop") or nxt.fields.get("e") \
                or nxt.fields.get("f") or nxt.fields.get("seq") or nxt.fields.get("rl"):
            raise UasmError(f"{r.path}:{nxt.line}: the word after E pops, posts, waits, "
                            "releases operand bytes or sequences")
        # (qprobe round 6, EU_HOLD) the word after E may post an I/O write (OUT's: the cycle no
        # sooner than the clock after the routine's boundary); it never waits by `bi` (rule
        # 10's G is withdrawn) nor posts a memory or read request (E_PEND: the boundary waits
        # for a posted memory request; a read's datum needs an F word)
        if nxt.fields.get("bi") or (nxt.fields.get("bus") and nxt.fields["bus"]
                                    != enum_value("v35_bus_e", "iow")):
            raise UasmError(f"{r.path}:{nxt.line}: the word after E waits (bi) or posts other "
                            "than an I/O write")
        nxt.fields["seq"] = enum_value("v35_seq_e", "disp")
        nxt.post_e = True
        i += 2
    es = [k for k, w in enumerate(r.words) if w.fields.get("e")]
    if es:
        last = max(es)
        if last + 2 < len(r.words) and not any(w.label for w in r.words[last + 2:]):
            raise UasmError(f"{r.path}:{r.words[last + 2].line}: a word after the post-E word "
                            "that nothing reaches")


# (qprobe round 8, Q20) the ModR/M opcodes whose boundary does not wait for three bytes behind
# them (the decode's m3 0): INC r8 (FE) and NOT r16 (F7) measured after MOV r16,imm16 at pE (the
# qprobe em3-incb / em3-notr runs, 18 / 18 with the rule off, 9 / 18 with it on). F6 and FF are
# not measured and keep the wait; the shift group (D0-D3) waits (3 round-5 runs)
NO_M3 = {0xF6, 0xFE, 0xF7, 0xFF}      # (qprobe round 13, Q44) FF: JMP / CALL r16 exempt (the FF group as F6 / F7 / FE); (qprobe round 16) F6 too (the byte MUL / DIV on memory, QPr16a mq: the model reads the group without the three-bytes wait)

RL_X = 3      # (qprobe rule 9) rl=x: the request word (X), no byte released
_ALL: list = []   # (qprobe round 16) the routines being assembled (_releases_by_path's shared tails)


def _releases_by_path(r: Routine, e2: int) -> bool:
    """(qprobe round 10) a routine whose two outcomes release in different words (BCWZ: P N on
    the not-taken E word, P with the taken path's add): every path from the entry to an E word
    (or out of the routine by a jump) releases the opcode once at its E and as many operand
    bytes as it pops (plus a short transfer's displacement). The paths follow the sequence: a
    jc / jnc both ways, a jmp to its label, a call (the shared delay) to the next word."""
    seq = {enum_value("v35_seq_e", k): k for k in ("jmp", "jc", "jnc", "call", "ret", "eac")}
    at = {w.label: (r, k) for k, w in enumerate(r.words) if w.label}
    # (qprobe round 16) a jump into another routine's words (a shared tail: the displacement
    # cells of 80-83 / C7 continue in their [BW] routine) carries the counts on into it
    ext = {w.label: (x, k) for x in _ALL for k, w in enumerate(x.words) if w.label and x is not r}
    todo, seen = [(r, 0, 0, 0, 0)], set()
    while todo:
        rr, k, rl, pops, ro = todo.pop()
        if (rr.name, k, rl, pops, ro) in seen or k >= len(rr.words) or rl > 8:
            if k >= len(rr.words):
                return False
            continue
        seen.add((rr.name, k, rl, pops, ro))
        w = rr.words[k]
        if w.fields.get("rl", 0) != RL_X:
            rl += w.fields.get("rl", 0)
        pops += 1 if w.fields.get("pop") and w.fields["pop"] != PP_RD else 0
        ro += 1 if w.fields.get("ro") else 0
        if w.fields.get("e"):
            if ro != 1 or rl != pops + e2:
                return False
            continue
        kind = seq.get(w.fields.get("seq"))
        tgt = w.refs.get("tgt")
        if kind == "ret":
            return False
        if kind in ("jmp", "jc", "jnc", "eac"):
            if rr is r:
                loc = at.get(tgt) or (ext.get(tgt) if kind == "jmp" and (rl != pops + e2 or ro) else None)
            else:
                loc = ext.get(tgt) if tgt in ext else at.get(tgt)
            if loc is None:
                if rl != pops + e2 or ro:
                    return False
            else:
                todo.append((loc[0], loc[1], rl, pops, ro))
            if kind == "jmp":
                continue
        elif kind is not None and kind != "call":
            return False
        todo.append((rr, k + 1, rl, pops, ro))
    return True


# (qprobe round 22) pop=rd: no byte popped; the displacement a hold head popped released
PP_RD = enum_value("v35_pop_e", "rd")


def _releases(r: Routine) -> None:
    """(qprobe rule 3) the words' releases (`ro`, `rl`): the default unless the routine names
    them. A short transfer's displacement (the decode's e2: popped by the E word with its
    opcode) is the routine's to release; a ModR/M byte or the 0F / REP page's second byte is
    released by the loader on the first word after the dispatch (v35_loader `mra`)."""
    e2 = r.head.get("page") is None and "op" in r.head \
        and any(o in SHORT_XFER for o in _ranges(r.head["op"]))
    if r.head.get("hold") == "1":
        # (qprobe round 22) a hold head (eas*): its pops released by its caller's pop=rd word
        if any("ro" in w.fields or "rl" in w.fields or w.fields.get("pop") == PP_RD for w in r.words):
            raise UasmError(f"{r.path}:{r.line}: {r.name}: a hold head releases nothing")
        return
    pops = sum(1 for w in r.words if w.fields.get("pop") and w.fields["pop"] != PP_RD)
    es = sum(1 for w in r.words if w.fields.get("e"))
    if any("ro" in w.fields or "rl" in w.fields for w in r.words):
        ro = sum(1 for w in r.words if w.fields.get("ro"))
        rl = sum(w.fields.get("rl", 0) for w in r.words if w.fields.get("rl", 0) != RL_X)
        if (ro != es or rl != pops + int(e2)) and not _releases_by_path(r, int(e2)):
            raise UasmError(f"{r.path}:{r.line}: {r.name}: the releases ({ro} ro, rl {rl}) are "
                            f"not the pops ({es} E, {pops + int(e2)} operand bytes)")
        return
    if any(w.fields.get("pop") == PP_RD for w in r.words):
        raise UasmError(f"{r.path}:{r.line}: {r.name}: pop=rd in a routine that names no release")
    for w in r.words:
        if w.fields.get("pop"):
            w.fields["rl"] = 1
        if w.fields.get("e"):
            w.fields["ro"] = 1
    if e2 and r.words:
        w = r.words[0]
        w.fields["rl"] = w.fields.get("rl", 0) + 1


@dataclass
class Program:
    routines: list
    words: list
    labels: dict
    cells1: dict          # opcode -> routine name (first level, no ModR/M)
    cells2: dict          # (opcode, modrm or second byte) -> routine name
    leads: dict = None    # (qprobe rule 12) opcode -> the routine header's lead=
    hlts: set = None      # (qprobe rule 11) the opcodes whose routine header says hlt=1
    # (tail sharing, work order 24) the layout: `flat` the unshared program the sources assemble
    # to (None when this is it); `where` the ROM address of every source word (flat index ->
    # address); `owners` the source words each ROM address holds (address -> [(routine, k)]:
    # more than one where the word is a shared tail's); `copies` the addresses that repeat a
    # word stored elsewhere (a busy successor field forced them)
    flat: "Program" = None
    where: list = None
    owners: dict = None
    copies: set = None

    def routine(self, name: str):
        return next(r for r in self.routines if r.name == name)

    def name_of(self, addr: int) -> str:
        """The routine words a ROM address holds, `name+k` joined by `|` (every owner: a shared
        word belongs to several routines)."""
        if self.owners is None:
            r, w = self.words[addr]
            return f"{r.name}+{r.words.index(w)}"
        return "|".join(f"{n}+{k}" for n, k in self.owners.get(addr, ()))


TRAP1 = "trap"            # an opcode without a routine
TRAP2 = "trapm"           # a ModR/M cell without a routine
TRAP0F = "trap0f"         # a 0F form without a ModR/M byte
TRAP0FM = "trap0fm"       # ... with one
RESET = "reset"
# (MX1) the EA heads (ea.uasm): the dispatch's targets for a ModR/M memory cell with a
# displacement (or, ea=book, at mod 00 too); each returns to the routine's entry (its add)
EA_HEADS = {"eab0": "UROM_EAB0", "eab8": "UROM_EAB8", "eab16": "UROM_EAB16", "ea8": "UROM_EA8",
            "ead": "UROM_EAD",
            # (qprobe round 6) ea=q: the measured MOV r,mem / MOV mem,r heads, one per mode
            "eaq0": "UROM_EAQ0", "eaq8": "UROM_EAQ8", "eaq16": "UROM_EAQ16",
            # (qprobe round 10, approved) base + index + d16 (Q18): one word more
            "eaq16x": "UROM_EAQ16X",
            # (qprobe round 22) the 0F page's hold heads (ea=s: the EAC word's call): two words in
            # every mode, the displacement popped and not released (the routine's pop=rd word)
            "eas0": "UROM_EAS0", "eas8": "UROM_EAS8", "eas16": "UROM_EAS16"}
PATHS = ("m00", "d8", "d16", "dir")
RPATH = "r"               # (MX3c) a 0F routine's register path (its EAC word's jump)
# (MX2) a transfer's two paths: its condition true (taken) and false (not taken); a routine whose
# book form prints two values ("8 or 15": the smaller not taken, the larger taken) is checked on
# both, one whose header says `xc=t` on the taken path only (BRKV: the book's trap)
XPATHS = ("t", "nt")
PATH_MODRM = {"m00": 0x07, "d8": 0x47, "d16": 0x87, "dir": 0x06}     # [BW], [BW+d8], [BW+d16], [d16]
PATH_EA = {"m00": 3, "d8": 3, "d16": 4, "dir": 3}                     # the book's EA


def is_mem(r) -> bool:
    return r.head.get("mod") == "mem"


def is_pmem(r) -> bool:
    """(MX3c) a 0F routine with a memory form (`bookm=` its book form): checked on the register
    path and the four EA paths."""
    return r.head.get("page") == "0f" and "bookm" in r.head


def ea_head(r, path: str) -> str | None:
    """The head the dispatch calls for routine r on path (None: the routine's entry)."""
    book = r.head.get("ea", "book") == "book"
    if r.head.get("ea") == "q":
        return {"m00": "eaq0", "d8": "eaq8"}.get(path, "eaq16")
    if r.head.get("ea") == "s":
        return {"m00": "eas0", "d8": "eas8"}.get(path, "eas16")
    if path == "m00":
        return "eab0" if book else None
    if path == "d8":
        return "eab8" if book else "ea8"
    if path == "d16":
        return "eab16" if book else "ead"
    return "ead"


def mem_paths(r) -> tuple:
    """(qprobe round 9) the EA paths a memory routine's header claims: `paths=m00,d8,...`
    (m00: mod 00 but the direct address; d8; d16; dir), all four by default. A form whose
    routine differs by the mode (MOV mem,imm16: the modes without a displacement measured) is
    two routines on one opcode; the dispatch's entry then depends on the whole ModR/M byte."""
    if "paths" not in r.head:
        return PATHS
    ps = tuple(x for x in r.head["paths"].split(","))
    if not ps or any(x not in PATHS for x in ps):
        raise UasmError(f"{r.path}:{r.line}: paths={r.head['paths']!r} (of {PATHS})")
    return tuple(x for x in PATHS if x in ps)


def modrm_path(mb: int) -> str:
    md, rm = mb >> 6, mb & 7
    if md == 0:
        return "dir" if rm == 6 else "m00"
    return {1: "d8", 2: "d16"}[md]


def _bus_idle(f: dict) -> bool:
    """(r24) the word waits as the model's B: bi without rl=X, not a FLUSH word, and not the
    commit word C (bi with vk on rl 0 / 1); the strict word (bi vk rl=2) is one."""
    rl = f.get("rl", 0)
    return (bool(f.get("bi")) and rl != enum_value("v35_rl_e", "x") and not f.get("flush")
            and not (f.get("vk") and rl != enum_value("v35_rl_e", "2")))


def _mark_bnext(words: list) -> None:
    """(r24, model_m CH_BNEXT, results Q42's second half) nb on a word that is not an E word
    marks it "followed by a bus-idle word": a word with no bus-wait kind (no bi, rl not X, no
    FLUSH, not the dispatch) whose every static successor is a bus-idle word (_bus_idle). The
    sequencer presents it to the bus unit as the word kind's free code (v35_useq wk_bn): the
    fetch chained behind the fetch that followed a memory write is not started on the clock
    such a word executes without a release. nb keeps its own meaning on E words (no
    boundary); the successors of a RET, DISP, DISPM, EAC or TRAP word are not static (no mark).
    An explicit nb on a non-E word is an error (the bit is the assembler's there)."""
    sq = {k: enum_value("v35_seq_e", k) for k in ("next", "jmp", "jc", "jnc", "call", "loop", "tki")}
    rlx = enum_value("v35_rl_e", "x")
    for i, (r, w) in enumerate(words):
        f = w.fields
        if f.get("e"):
            continue
        if f.get("nb"):
            raise UasmError(f"{r.path}:{w.line}: nb on a word that is not an E word")
        if f.get("bi") or f.get("rl", 0) == rlx or f.get("flush"):
            continue
        seq = f.get("seq", 0)
        if seq == sq["next"]:
            succ = [i + 1]
        elif seq in (sq["jmp"], sq["call"]):
            succ = [f.get("tgt", 0)]
        elif seq in (sq["jc"], sq["jnc"], sq["loop"], sq["tki"]):
            succ = [f.get("tgt", 0), i + 1]
        else:
            continue
        if all(j < len(words) and _bus_idle(words[j][1].fields) for j in succ):
            f["nb"] = 1


def assemble_flat(paths: list[Path] | None = None) -> Program:
    """The sources assembled in order, each routine contiguous (no tail shared)."""
    paths = paths if paths is not None else sorted(UROM.glob("*.uasm"))
    routines = []
    for p in paths:
        routines += parse_file(p)
    names = [r.name for r in routines]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise UasmError(f"routines defined twice: {sorted(dup)}")
    for need in (TRAP1, TRAP2, TRAP0F, TRAP0FM, RESET):
        if need not in names:
            raise UasmError(f"no routine {need!r}")
    for r in routines:
        if is_mem(r) and r.head.get("ea", "book") not in ("book", "bare", "q"):
            raise UasmError(f"{r.path}:{r.line}: ea={r.head['ea']!r} (book, bare or q)")
        # (qprobe round 22) ea=s: the 0F page's hold heads (a page routine's EAC word)
        if r.head.get("ea") == "s" and r.head.get("page") != "0f":
            raise UasmError(f"{r.path}:{r.line}: ea=s on a routine of no 0F page")
    words, labels = [], {}
    global _ALL
    _ALL = routines
    for r in routines:
        _finish(r)
    for r in routines:
        _releases(r)
        r.base = len(words)
        labels[r.name] = r.base
        for w in r.words:
            if w.label:
                key = w.label
                if key in labels:
                    raise UasmError(f"{r.path}:{w.line}: label {key} defined twice")
                labels[key] = len(words)
            words.append((r, w))
    if len(words) > 1 << UADDR_W:
        raise UasmError(f"{len(words)} words: more than the ROM's {1 << UADDR_W}")
    if any(is_mem(r) for r in routines):
        for lab in EA_HEADS:
            if lab not in labels:
                raise UasmError(f"no EA head {lab!r} (ea.uasm)")
    for r, w in words:
        for k, v in w.refs.items():
            if v not in labels:
                raise UasmError(f"{r.path}:{w.line}: no label {v!r}")
            w.fields[k] = labels[v]
    _mark_bnext(words)
    # the decode cells
    cells1, cells2 = {}, {}
    for r in routines:
        h = r.head
        if "op" not in h:
            continue
        ops = _ranges(h["op"])
        if h.get("page") == "0f":
            for b in ops:
                cells2.setdefault((0x0F, b), []).append(r.name)
            continue
        if h.get("page") == "rep":
            # (MX4) a REP form: the string opcode under every REP prefix
            for p in REP_XC:
                for b in ops:
                    cells2.setdefault((p, b), []).append(r.name)
            continue
        mods = {"reg": [3], "mem": [0, 1, 2], "any": [0, 1, 2, 3], "m00": [0], "m01": [1], "m10": [2]}[h.get("mod", "any")]
        regs = _ranges(h["reg"].replace("/", "")) if "reg" in h else list(range(8))
        rms = _ranges(h["rm"]) if "rm" in h else list(range(8))
        paths = mem_paths(r)
        for op in ops:
            if op in MODRM_OPS:
                for md in mods:
                    for reg in regs:
                        for rm in rms:
                            mb = md << 6 | reg << 3 | rm
                            if md != 3 and modrm_path(mb) not in paths:
                                continue
                            cells2.setdefault((op, mb), []).append(r.name)
            else:
                cells1.setdefault(op, []).append(r.name)
    for k, v in list(cells1.items()) + list(cells2.items()):
        if len(v) > 1:
            raise UasmError(f"decode cell {k} claimed by {v}")
    # (qprobe rule 12) the boundary's lead: a routine header's lead=K (1 to 3) for its opcodes
    # (the opcode's decode: a ModR/M opcode's routines must agree or name none)
    leads = {}
    for r in routines:
        h = r.head
        if "lead" not in h or "op" not in h:
            continue
        k = int(h["lead"])
        if not 1 <= k <= 3 or h.get("page"):
            raise UasmError(f"{r.path}:{r.line}: lead={h['lead']} (1 to 3, a first-byte opcode)")
        for op in _ranges(h["op"]):
            if leads.get(op, k) != k:
                raise UasmError(f"{r.path}:{r.line}: opcode {op:02X} has two leads")
            leads[op] = k
    # (qprobe round 22, spec 18 A3) ml=1 only on a ModR/M opcode's memory cells
    for r in routines:
        if r.head.get("ml") not in (None, "1") or (r.head.get("ml") and (
                r.head.get("page") or not all(op in MODRM_OPS for op in _ranges(r.head.get("op", ""))))):
            raise UasmError(f"{r.path}:{r.line}: ml={r.head['ml']} (1, a ModR/M opcode's memory cells)")
    for r in routines:
        if r.head.get("ml") and any(op in leads for op in _ranges(r.head.get("op", ""))):
            raise UasmError(f"{r.path}:{r.line}: ml=1 on an opcode with a lead (the stream facts' free code)")
    # (qprobe rule 11) a routine header's hlt=1: its opcode's release stops prefetching (HALT)
    hlts = {op for r in routines if r.head.get("hlt") == "1" and "op" in r.head
            for op in _ranges(r.head["op"])}
    return Program(routines, words, labels, {k: v[0] for k, v in cells1.items()},
                   {k: v[0] for k, v in cells2.items()}, leads, hlts)


# ------------------------------------------------------------------ (work order 24) tail sharing
# The layout pass: every word identical to another together with its whole continuation is
# stored once. The sources stay as written (each routine complete); the pass runs on the flat
# assembly and changes only where words sit and, on a word whose successor is the next word by
# NEXT / JMP, whether it reaches it by falling through (NEXT) or by its target field (JMP).
#
# The sequencer's next-address rule (v35_useq upc_n / raddr), which decides what is free:
#   NEXT, TRAP                   the next address (upc + 1)
#   JMP                          tgt
#   JC JNC LOOP TKI EAC          tgt or upc + 1 (EAC also the EA head from the decode, retr <- upc + 1)
#   CALL                         tgt, retr <- upc + 1
#   RET                          retr
#   DISP                         the decode's entry (or UROM_INT; the dispatch's EA-head call
#                                loads retr from the decode)
# So a word joins a stored tail for free when its successor is reached by NEXT or JMP and its
# tgt field is not read as data (SR_VEC reads tgt as the vector on a vk word): NEXT becomes JMP,
# same clock. A word whose successor is upc + 1 under any other sequencing value (the
# conditional / loop / take-point / EAC / TRAP words, a call's return point, a vector word)
# needs that successor at the next address: of several such words before one stored tail, one
# falls into it and each other gets its own copy (and the copy's own upc + 1 successor, while
# that is again forced). Nothing else changes: no word is added to any path.
#
# Addresses that mean something beyond the sequencing keep their own word: the word at
# UROM_REPP (v35_top's observation compares the address with rep_p's E word: rep_lk's and
# rep_sx's E words are the same bits) is never shared.
SHARE_DEFAULT = True
_SQ = {k[3:].lower(): v for k, v in ENUMS["v35_seq_e"][1].items()}
_SQN = {v: k for k, v in _SQ.items()}
_TGT_ADDR = {"jmp", "jc", "jnc", "call", "loop", "eac", "tki"}    # tgt is an address
_FT_FORCED = {"jc", "jnc", "call", "loop", "eac", "tki", "trap"}   # upc + 1 is a successor
_SR_VEC = ENUMS["v35_src_e"][1].get("SR_VEC")
SHARE_PINNED = ("rep_p",)        # routines whose entry word's address is read (UROM_REPP)


def _seqk(f: dict) -> str:
    return _SQN[f.get("seq", 0)]


def _tgt_data(f: dict) -> bool:
    """The word's tgt field is read as data (the vector of an SR_VEC word), not a target."""
    return _seqk(f) not in _TGT_ADDR and ("tgt" in f or (
        f.get("vk") and _SR_VEC in (f.get(k) for k in ("ws", "s1", "s2", "ax", "ay"))))


def _succs(f: dict, i: int) -> list:
    """The static successors of the word at i (call: the callee and the return point)."""
    k = _seqk(f)
    if k == "next":
        return [i + 1]
    if k == "jmp":
        return [f.get("tgt", 0)]
    if k in ("jc", "jnc", "loop", "tki", "eac", "call"):
        return [f.get("tgt", 0), i + 1]
    if k == "trap":
        return [i + 1]
    return []           # RET, DISP (DISPM is withdrawn)


def tail_classes(words: list, pinned: set = frozenset()) -> list:
    """The class of every word: two words are one class when every field is equal (NEXT and
    JMP being the same step, a target compared by its class) and their successors are one
    class, pairwise. The coarsest such partition (refined from the fields until stable)."""
    n = len(words)
    key0 = []
    for i, (_, w) in enumerate(words):
        f = w.fields
        k = _seqk(f)
        if k == "jmp" and _tgt_data(f):
            raise UasmError(f"word {i}: a jump whose tgt is also read as data")
        items = tuple(sorted((a, v) for a, v in f.items()
                             if v and a != "seq" and not (a == "tgt" and k in _TGT_ADDR)))
        key0.append((items, "n" if k in ("next", "jmp") else k, _tgt_data(f),
                     i if i in pinned else None))
    ids = {}
    c = [ids.setdefault(k, len(ids)) for k in key0]
    while True:
        sig = [(c[i], tuple(c[s] if 0 <= s < n else -1 for s in _succs(w.fields, i)))
               for i, (_, w) in enumerate(words)]
        ids = {}
        c2 = [ids.setdefault(s, len(ids)) for s in sig]
        if len(ids) == len(set(c)):
            return c2
        c = c2


def share_tails(flat: Program, pinned_routines=SHARE_PINNED) -> Program:
    """The shared layout of a flat program (see the section's head)."""
    W = flat.words
    n = len(W)
    pinned = {flat.labels[x] for x in pinned_routines if x in flat.labels}
    c = tail_classes(W, pinned)
    ncls = max(c) + 1
    rep = [None] * ncls                         # a class's first word (flat index)
    for i in range(n):
        if rep[c[i]] is None:
            rep[c[i]] = i

    def kind(cl):
        return _seqk(W[rep[cl]][1].fields)

    def forced(cl):        # upc + 1 must hold the successor
        f = W[rep[cl]][1].fields
        return kind(cl) in _FT_FORCED or (kind(cl) == "next" and _tgt_data(f))

    def free(cl):          # NEXT / JMP: falls through or jumps, as the layout likes
        return kind(cl) in ("next", "jmp") and not forced(cl)

    def ftsucc(cl):        # the class at upc + 1 (forced) or the one step's class (free)
        i = rep[cl]
        f = W[i][1].fields
        s = f.get("tgt", 0) if kind(cl) == "jmp" else i + 1
        if not 0 <= s < n:
            raise UasmError(f"{W[i][0].name}: the word at {i} falls off the ROM")
        return c[s]

    # nodes: one per class (its stored word), then the copies; inl / outl the fall-through links
    node_cls = list(range(ncls))
    inl, outl = {}, {}

    def link(a, b):
        inl[b], outl[a] = a, b

    # 1. a forced word's successor: of the classes forced into one class, the one whose first
    #    flat occurrence is earliest falls into the stored word (the source order kept)
    fpred = {}
    for cl in range(ncls):
        if forced(cl):
            fpred.setdefault(ftsucc(cl), []).append(cl)
    for s, ps in fpred.items():
        link(min(ps, key=lambda p: rep[p]), s)

    # 2. the others: a copy of the successor after each, and of its own forced successor in turn
    def copy_after(pnode, cl):
        k = len(node_cls)
        node_cls.append(cl)
        link(pnode, k)
        if forced(cl):
            copy_after(k, ftsucc(cl))

    for cl in range(ncls):
        if forced(cl) and outl.get(cl) is None:
            copy_after(cl, ftsucc(cl))

    # 3. the free words: a stored word with no word falling into it takes one free predecessor
    #    (the one a flat word falls through to it from, earliest first; then one that jumped),
    #    the chains kept acyclic; every other free predecessor jumps
    par = list(range(len(node_cls)))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for a, b in outl.items():
        par[find(b)] = find(a)
    cand = {}
    for i in range(n):
        cl = c[i]
        if free(cl):
            s = ftsucc(cl)
            fell = _seqk(W[i][1].fields) == "next"
            cand.setdefault(s, []).append((0 if fell else 1, i, cl))
    for s in sorted(cand, key=lambda s: rep[s]):
        if s in inl:
            continue
        for _, _, p in sorted(cand[s]):
            if p not in outl and find(p) != find(s):
                link(p, s)
                par[find(s)] = find(p)
                break

    # 4. the chains, in the order of their first words' first flat occurrence; addresses
    heads = [k for k in range(len(node_cls)) if k not in inl]
    if any(h >= ncls for h in heads):
        raise UasmError("tail sharing: a copy heads a chain")
    order_key = {h: rep[h] for h in heads}      # where the chain's first word first occurs
    addr = {}
    seqv = []
    for h in sorted(heads, key=lambda h: (order_key[h], h)):
        k = h
        while k is not None:
            addr[k] = len(seqv)
            seqv.append(k)
            k = outl.get(k)
    if len(seqv) != len(node_cls):
        raise UasmError("tail sharing: a fall-through cycle")

    # 5. the words
    words = []
    for a, k in enumerate(seqv):
        cl = node_cls[k]
        r, w0 = W[rep[cl]]
        f = dict(w0.fields)
        kd = kind(cl)
        nxt = outl.get(k)
        if free(cl):
            t = ftsucc(cl)
            f.pop("tgt", None)
            if nxt is not None and node_cls[nxt] == t:
                f.pop("seq", None)
            else:
                f["seq"], f["tgt"] = _SQ["jmp"], addr[t]
        else:
            if forced(cl) and (nxt is None or node_cls[nxt] != ftsucc(cl) or addr[nxt] != a + 1):
                raise UasmError(f"tail sharing: {r.name}: a forced successor not at the next address")
            if kd in _TGT_ADDR:
                f["tgt"] = addr[c[w0.fields.get("tgt", 0)]]
        words.append((r, Word(f, w0.act, w0.line, None, {}, w0.post_e, w0.open)))

    # 6. every source word's address, the owners, the labels and entries
    where = [None] * n
    for i in range(n):
        if i and _seqk(W[i - 1][1].fields) != "jmp" and _succs(W[i - 1][1].fields, i - 1)[-1:] == [i] \
                and outl.get(seqv[where[i - 1]]) is not None:
            where[i] = where[i - 1] + 1
        else:
            where[i] = addr[c[i]]
        if node_cls[seqv[where[i]]] != c[i]:
            raise UasmError(f"tail sharing: word {i} placed on another class")
    flat_k = {}
    for r in flat.routines:
        for k in range(len(r.words)):
            flat_k[r.base + k] = (r.name, k)
    owners = {}
    for i in range(n):
        owners.setdefault(where[i], []).append(flat_k[i])
    dead = [a for a in range(len(words)) if a not in owners]
    if dead:
        raise UasmError(f"tail sharing: words no source word reaches: {dead[:8]}")
    for a, (r, w) in enumerate(words):
        name, _ = owners[a][0]
        words[a] = (flat.routine(name), w)
    labels = {lab: addr[c[i]] for lab, i in flat.labels.items()}
    import dataclasses
    routines = [dataclasses.replace(r, base=labels[r.name]) for r in flat.routines]
    byname = {r.name: r for r in routines}
    words = [(byname[r.name], w) for r, w in words]
    for x in pinned:
        if len(owners[addr[c[x]]]) != 1 or sum(1 for k in node_cls if k == c[x]) != 1:
            raise UasmError(f"tail sharing: the pinned word {x} is shared")
    copies = {a for a, k in enumerate(seqv) if k >= ncls}
    return Program(routines, words, labels, flat.cells1, flat.cells2, flat.leads, flat.hlts,
                   flat=flat, where=where, owners=owners, copies=copies)


def assemble(paths: list[Path] | None = None, share: bool | None = None) -> Program:
    """The program: the sources assembled (assemble_flat), then (share, the default
    SHARE_DEFAULT) laid out with identical tails stored once (share_tails)."""
    flat = assemble_flat(paths)
    if not (SHARE_DEFAULT if share is None else share):
        flat.where = list(range(len(flat.words)))
        flat.owners = {}
        for r in flat.routines:
            for k in range(len(r.words)):
                flat.owners[r.base + k] = [(r.name, k)]
        flat.copies = set()
        return flat
    return share_tails(flat)


def share_report(prog: Program) -> str:
    """Per routine: its words' addresses, which are its own and where it joins a stored tail
    (the first word stored with another routine's), and the totals per file."""
    flat = prog.flat or prog
    L = []
    per_file = {}
    for r in flat.routines:
        ad = [prog.where[r.base + k] for k in range(len(r.words))]
        own = [k for k, a in enumerate(ad) if len({nm for nm, _ in prog.owners[a]}) == 1]
        shared = [k for k in range(len(ad)) if k not in own]
        pf = per_file.setdefault(r.path, [0, set()])
        pf[0] += len(ad)
        pf[1].update(ad)
        runs, k = [], 0
        while k < len(ad):
            j = k
            while j + 1 < len(ad) and ad[j + 1] == ad[j] + 1 and (j + 1 in own) == (k in own):
                j += 1
            tag = "" if k in own else " shared"
            runs.append(f"{k}-{j}@{ad[k]}-{ad[j]}{tag}" if j > k else f"{k}@{ad[k]}{tag}")
            k = j + 1
        join = ""
        if shared:
            a = ad[shared[0]]
            others = sorted({f"{nm}+{kk}" for nm, kk in prog.owners[a] if nm != r.name})
            join = f"; joins at word {shared[0]} -> {a} (with {', '.join(others[:6])}" \
                   f"{', ...' if len(others) > 6 else ''})"
        L.append(f"{r.name} ({r.path}:{r.line}) {len(ad)} words, {len(own)} own, "
                 f"{len(shared)} shared: {' '.join(runs)}{join}")
    L.append("")
    stored = {}
    for r, _ in prog.words:
        stored[r.path] = stored.get(r.path, 0) + 1
    L.append(f"{'file':16s} {'words':>6s} {'addresses':>9s} {'stored':>6s}   (addresses: the "
             "file's words' addresses, a word shared across files counted in each; stored: the "
             "addresses whose first owner is the file's)")
    for p, (nw, ads) in sorted(per_file.items()):
        L.append(f"{p:16s} {nw:6d} {len(ads):9d} {stored.get(p, 0):6d}")
    L.append(f"{'all':16s} {len(flat.words):6d} {'':9s} {len(prog.words):6d}   "
             f"({len(prog.copies)} copies)")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ outputs
def rom_banks(prog: Program) -> list[str]:
    out = [[] for _ in range(BANKS)]
    for r, w in prog.words:
        v = pack(w.fields)
        for b in range(BANKS):
            out[b].append(f"{(v >> (BANK_BITS * b)) & ((1 << BANK_BITS) - 1):08x}")
    return ["\n".join(lines) + "\n" for lines in out]


def udec1(prog: Program, op: int) -> dict:
    f = fmt_of(op)
    if op == 0x0F or op in REP_XC:
        # (MX3c) the dispatch reads the second level on the second byte the E word popped
        # ((MX4) the REP prefixes': (qprobe round 12) the prefix's own byte, then the string opcode)
        f["entry"], f["trap"] = prog.labels[TRAP0F], 0
    elif f["has_modrm"]:
        # (the dispatch reads the second level on the ModR/M byte the E word popped)
        f["entry"], f["trap"] = prog.labels[TRAP2], 0
    elif op in prog.cells1:
        f["entry"], f["trap"] = prog.labels[prog.cells1[op]], 0
    else:
        f["entry"], f["trap"] = prog.labels[TRAP1], 1
    f["io"] = int(op in IO_OPS)
    f["lead"] = (prog.leads or {}).get(op, 0)       # (qprobe rule 12)
    f["hlt"] = int(op in (prog.hlts or set()))      # (qprobe rule 11)
    # (qprobe round 8, Q20 / Q9) the boundary waits for three bytes behind the staged opcode:
    # a ModR/M opcode's, except the group opcodes whose first words do not use the ModR/M byte
    f["m3"] = int(f["has_modrm"] and op not in NO_M3)
    return f


def udec2(prog: Program, op: int, b: int) -> dict:
    """The second level: (op, the popped byte) -> entry, trap, op3, (MX1) ea (a memory cell:
    the dispatch calls the EA head of the byte's mode) and eab (the book's EA heads)."""
    op3 = (b >> 3) & 7 if op in (0x80, 0x81, 0x82, 0x83, 0xC0, 0xC1, 0xD0, 0xD1, 0xD2, 0xD3,
                                 0xF6, 0xF7, 0xFE, 0xFF, D6_BITREG) else fmt_of(op)["op3"]
    if op == 0x0F:
        op3 = (b >> 1) & 7               # (MX3c) the page's operation: the second byte's bits 3:1
    if op in REP_XC:
        # (MX4) the string opcode's format: its width (bit 0) and the compares' CMP
        g = fmt_of(b)
        if (op, b) in prog.cells2:
            return {"entry": prog.labels[prog.cells2[(op, b)]], "trap": 0, "op3": g["op3"],
                    "ea": 0, "eab": 0, "eaq": 0, "w": g["w"], "io": int(b in IO_OPS)}
        return {"entry": prog.labels[TRAP0F], "trap": 1, "op3": 0, "ea": 0, "eab": 0, "eaq": 0,
                "w": 0, "io": 0}
    if (op, b) in prog.cells2:
        r = prog.routine(prog.cells2[(op, b)])
        mem = op != 0x0F and is_mem(r) and b >> 6 != 3
        # (MX3c) a 0F routine's EA heads (its EAC word's call) by its header, as a memory cell's;
        # (qprobe round 22) on the 0F page the bit selects the hold heads (ea=s; else the bare)
        eab = (mem and r.head.get("ea", "book") == "book") or (op == 0x0F and r.head.get("ea") == "s")
        eaq = mem and r.head.get("ea") == "q"       # (qprobe round 6)
        return {"entry": prog.labels[r.name], "trap": 0, "op3": op3, "ea": int(mem),
                "eab": int(eab), "eaq": int(eaq), "w": page_w(b) if op == 0x0F else 0, "io": 0}
    if op == 0x0F:
        name = TRAP0FM if b in PAGE1_MODRM else TRAP0F
        return {"entry": prog.labels[name], "trap": 1, "op3": 0, "ea": 0, "eab": 0, "eaq": 0,
                "w": 0, "io": 0}
    return {"entry": prog.labels[TRAP2], "trap": 1, "op3": op3, "ea": 0, "eab": 0, "eaq": 0,
            "w": 0, "io": 0}


def uml(prog: Program, op: int, b: int) -> int:
    """(qprobe round 22, spec 18 A3) the cell's routine counts a fetch's last-clock bytes in the
    boundary's three-byte test (header ml=1; memory cells only)."""
    if op not in MODRM_OPS or b >> 6 == 3 or (op, b) not in prog.cells2:
        return 0
    return int(prog.routine(prog.cells2[(op, b)]).head.get("ml") == "1")


def udec2_class(b: int) -> int:
    """(qprobe round 6, timing) the byte's class for the second level's entry: the first byte
    with its mode being 3 (or not) and its reg field ({mod 3 ? 11 : 00, reg, 000})."""
    return (0xC0 if b >> 6 == 3 else 0x00) | (b & 0x38)


def udec2_by_class(prog: Program, op: int) -> bool:
    """The opcode's second-level entry is a function of the byte's class alone."""
    return all(udec2(prog, op, b)["entry"] == udec2(prog, op, udec2_class(b))["entry"]
               for b in range(256))


def ulen(op: int, il: int, mb: int) -> int:
    """The bytes the trap routine pops after its counter load."""
    if op == 0x0F:
        return (disp_bytes(mb) if il in PAGE1_MODRM else 0) + PAGE1_IMM.get(il, 0)
    if op in MODRM_OPS:
        return disp_bytes(mb) + imm_modrm(op, (mb >> 3) & 7)
    return fmt_of(op)["len"]


def decode_svh(prog: Program) -> str:
    L = ["// GENERATED by `python -m validation.v35s.chains.uasm` from fpga/v35s/core/v35/urom/"
         "*.uasm; do not edit.",
         "// The decode table (MX0): v35_udec1 (the opcode byte the E word popped -> the "
         "routine's entry and the format bits),",
         "// v35_udec2 (the opcode and the byte a DISPM word pops: the ModR/M byte, the 0F "
         "page's second byte -> the second entry and",
         "// the group's operation), v35_umodrm / v35_upage (the bytes a ModR/M or a 0F "
         "second byte's pop adds to the bytes still to pop). Included by v35_pkg.sv.",
         "",
         f"    localparam int UROM_WORDS = {len(prog.words)};",
         f"    localparam logic [UADDR_W-1:0] UROM_RESET = {UADDR_W}'d{prog.labels[RESET]};",
         "    // (F2b) the I/O trap's entry: the dispatch's target for an I/O form with PSW.BRKI 0",
         f"    localparam logic [UADDR_W-1:0] UROM_IOT = {UADDR_W}'d{prog.labels[IOT]};",
         "    // (qprobe round 12) the REP prefix's own routine (the observation's start: v35_top)",
         f"    localparam logic [UADDR_W-1:0] UROM_REPP = {UADDR_W}'d{prog.labels.get('rep_p', 0)};",
         "    // (F3) the interrupt entry: the dispatch's target when the controller's request, NMI",
         "    // or the single step is taken at an instruction's start",
         f"    localparam logic [UADDR_W-1:0] UROM_INT = {UADDR_W}'d{prog.labels[INT]};",
         "    // (MX1) the EA heads: the dispatch's call targets for a ModR/M memory cell (ea.uasm)"]
    for lab, pname in EA_HEADS.items():
        L.append(f"    localparam logic [UADDR_W-1:0] {pname} = {UADDR_W}'d{prog.labels.get(lab, 0)};")
    L += ["",
         "    function automatic v35_udec_t v35_udec1(input logic [7:0] op);",
         "        v35_udec_t f;",
         "        f = '0;",
         "        case (op)"]
    for op in range(256):
        f = udec1(prog, op)
        L.append(f"            8'h{op:02X}: f = '{{{UADDR_W}'d{f['entry']}, 1'b{f['trap']}, "
                 f"1'b{int(f['has_modrm'])}, 1'b{f['w']}, 1'b{f['d']}, 1'b{f['immw']}, "
                 f"1'b{f['sx']}, 3'd{f['op3']}, 3'd{f['seg']}, 3'd{f['len']}, "
                 f"1'b{f['e2']}, 5'd{f['xc']}, 1'b{f['pg']}, 1'b{f['io']}, 2'd{f['lead']}, 1'b{f['hlt']}, "
                 f"1'b{f['m3']}, 1'b{f['rp']}}};")
    L += ["            default: f = '0;", "        endcase", "        v35_udec1 = f;",
          "    endfunction", ""]
    # the second level: one case per opcode with a ModR/M byte (and 0F), on the byte
    L += ["    function automatic v35_udecm_t v35_udec2(input logic [7:0] op, input logic [7:0] b);",
          "        v35_udecm_t f;",
          "        f = '0;",
          "        case (op)"]
    for op in sorted(MODRM_OPS | {0x0F} | set(REP_XC)):
        L.append(f"            8'h{op:02X}: begin")
        # group the 256 byte values by result
        by = {}
        for b in range(256):
            g = udec2(prog, op, b)
            by.setdefault((g["entry"], g["trap"], g["op3"], g["ea"], g["eab"], g["eaq"], g["w"],
                           g["io"]),
                          []).append(b)
        L.append("                case (b)")
        default = max(by, key=lambda k: len(by[k]))
        for k, bs in sorted(by.items()):
            if k == default:
                continue
            items = ", ".join(f"8'h{b:02X}" for b in bs)
            L.append(f"                    {items}: f = '{{{UADDR_W}'d{k[0]}, 1'b{k[1]}, "
                     f"3'd{k[2]}, 1'b{k[3]}, 1'b{k[4]}, 1'b{k[5]}, 1'b{k[6]}, 1'b{k[7]}}};")
        k = default
        L.append(f"                    default: f = '{{{UADDR_W}'d{k[0]}, 1'b{k[1]}, 3'd{k[2]}, "
                 f"1'b{k[3]}, 1'b{k[4]}, 1'b{k[5]}, 1'b{k[6]}, 1'b{k[7]}}};")
        L += ["                endcase", "            end"]
    L += [f"            default: f = '{{{UADDR_W}'d{prog.labels[TRAP2]}, 1'b1, 3'd0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0}};",
          "        endcase", "        v35_udec2 = f;", "    endfunction", ""]
    # (qprobe round 17) the second level's entry split for the sequencer's ROM address (the
    # loader's d2ent: v35_udec2_fx / v35_udec2_fe, the whole opcodes' numbers) is withdrawn with
    # the sequencer's DISPM source: the dispatch reads v35_udec2 of the registered ModR/M byte
    # alone (the loader's df), so the numbers' limit of seven is gone
    # (MX0) the loader's count of the instruction's bytes still to pop from the queue: what a
    # ModR/M byte's pop adds (its displacement and the form's immediate) and what the 0F page's
    # second byte's pop adds (its ModR/M byte and its immediate)
    # (MX5c) the two shares as the RTL reads them: v35_umdsp (the ModR/M byte's displacement
    # bytes, of the byte alone) and v35_umimm (the form's immediate bytes, of the opcode and the
    # byte's reg field being 0 or 1: mb[5:4] == 0); v35_umodrm is their sum
    L += ["    function automatic logic [2:0] v35_umdsp(input logic [7:0] mb);",
          "        v35_umdsp = mb[7:6] == 2'd1 ? 3'd1 : mb[7:6] == 2'd2 ? 3'd2"
          " : (mb[7:6] == 2'd0 && mb[2:0] == 3'd6) ? 3'd2 : 3'd0;",
          "    endfunction", "",
          "    function automatic logic [2:0] v35_umimm(input logic [7:0] op, input logic r01);",
          "        case (op)"]
    for op in sorted(MODRM_OPS):
        if op in (0xF6, 0xF7):
            n = 1 if op == 0xF6 else 2
            L.append(f"            8'h{op:02X}: v35_umimm = r01 ? 3'd{n} : 3'd0;")
        elif imm_modrm(op, 0):
            L.append(f"            8'h{op:02X}: v35_umimm = 3'd{imm_modrm(op, 0)};")
    L += ["            default: v35_umimm = 3'd0;", "        endcase", "    endfunction", "",
          "    function automatic logic [2:0] v35_umodrm(input logic [7:0] op, input logic [7:0] mb);",
          "        v35_umodrm = v35_umdsp(mb) + v35_umimm(op, mb[5:4] == 2'd0);",
          "    endfunction", "",
          "    // (qprobe round 22, spec 18 A3) the boundary's three-byte test counts the bytes a",
          "    // fetch delivers on its last clock (routine header ml=1)",
          "    function automatic logic v35_uml(input logic [7:0] op, input logic [7:0] b);",
          "        v35_uml = 1'b0;",
          "        case (op)"]
    for op in sorted(MODRM_OPS):
        bs = [b for b in range(256) if uml(prog, op, b)]
        if bs:
            L += [f"            8'h{op:02X}: case (b)",
                  f"                {', '.join(f"8'h{x:02X}" for x in bs)}: v35_uml = 1'b1;",
                  "                default: v35_uml = 1'b0;", "            endcase"]
    L += ["            default: v35_uml = 1'b0;", "        endcase", "    endfunction", "",
          "    function automatic logic [2:0] v35_upage(input logic [7:0] b);",
          "        case (b)"]
    by = {}
    for b in range(256):
        by.setdefault(int(b in PAGE1_MODRM) + PAGE1_IMM.get(b, 0), []).append(b)
    for n, bs in sorted(by.items()):
        if n:
            L.append(f"            {', '.join(f"8'h{x:02X}" for x in bs)}: v35_upage = 3'd{n};")
    L += ["            default: v35_upage = 3'd0;", "        endcase", "    endfunction", ""]
    return "\n".join(L)


def outputs(prog: Program) -> dict:
    banks = [b.split() for b in rom_banks(prog)]
    if len(prog.words) > ROM_LO + ROM_HI:
        raise UasmError(f"{len(prog.words)} words: more than the two parts' {ROM_LO + ROM_HI}")
    out = {}
    for b in range(BANKS):
        lo, hi = banks[b][:ROM_LO], banks[b][ROM_LO:]
        hi = hi + ["00000000"] * (ROM_HI - len(hi))
        out[f"v35_urom_b{b}.hex"] = "\n".join(lo) + "\n"
        out[f"v35_urom_b{b + BANKS}.hex"] = "\n".join(hi) + "\n"
    out["v35_udecode_tbl.svh"] = decode_svh(prog)
    return out


def listing(prog: Program) -> str:
    """The ROM by address: a routine's header where its entry is, each word's bits, its label
    and act; (work order 24) a word stored for several routines lists every owner (`= name+k`),
    a copy is marked `copy`."""
    flat = prog.flat or prog
    entries, labs = {}, {}
    for r in flat.routines:
        entries.setdefault(prog.labels[r.name], []).append(r)
        for k, w in enumerate(r.words):
            if w.label:
                labs.setdefault(prog.where[r.base + k], []).append(w.label)
    L = []
    for addr, (r, w) in enumerate(prog.words):
        for x in entries.get(addr, ()):
            L.append(f"; {x.name} ({x.path}:{x.line}) {x.head}")
        lab = ",".join(labs.get(addr, ()))
        own = prog.owners.get(addr, []) if prog.owners else []
        tag = (" = " + " ".join(f"{nm}+{k}" for nm, k in own)) if len(own) > 1 else ""
        if prog.copies and addr in prog.copies:
            tag += " copy"
        L.append(f"{addr:4d} {pack(w.fields):024x} {lab + ':' if lab else '':10s} "
                 f"{w.act}{tag}")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ the book check's machine
BUS_CYCLE = 3          # a bus cycle at W = 0 (v35s-bus-timing.md)


def length(prog: Program, name: str, n: int = 4, conds: dict | None = None,
           limit: int = 4000, path: str = "m00", trace: list | None = None) -> int:
    """The routine's clocks from its entry to the successor's first word at EA = 3, W = 0, no
    queue stall: one word a clock; a request posted on clock p is granted on p + 1 and done on
    p + 1 + BUS_CYCLE (the F word and a RAMEN write's E wait for it: (qprobe rule 7) in the
    RTL the on-chip store's hold only, an external write holding the dispatch to its last clock
    instead: the book check keeps the on-chip timing); the counter's loads read
    n (CL, the immediate) or the width's bit count; conditions from `conds`. A 0F routine counts the
    page head's word. (MX1) A memory routine (`mod=mem`) runs from the EA head of `path` (the
    dispatch's call, returning to the routine's entry); `trace` collects (clock, address, word)."""
    conds = dict(conds or {})
    if path in XPATHS:
        # (MX2) a transfer's path: its conditions (CD_XC, and SNZ: the loop forms' count) hold
        # (t, taken) or not (nt)
        conds.setdefault(enum_value("v35_cond_e", "xc"), path == "t")
        conds.setdefault(enum_value("v35_cond_e", "snz"), path == "t")
    r = prog.routine(name)
    t = 0
    pc = r.base
    retr = None
    # (MX3c) a 0F routine starts at its entry as any other: the E word popped the second byte
    # with the opcode (no page head word); its register path (`r`) and memory paths (the EA
    # paths) part at its EAC word
    if is_mem(r):
        h = ea_head(r, path)
        if h is not None:
            pc, retr = prog.labels[h], r.base
    cnt = 0
    # (MX4) a REP form runs its loop on CW = n: SIGMA's value tracked through the words that
    # read CW (PASS, DEC) and CW's write from SIGMA; the compare's condition holds (CW runs out)
    rep = r.head.get("page") == "rep"
    sig, cw = None, n
    if rep:
        conds.setdefault(enum_value("v35_cond_e", "xc"), True)
    done_at = None
    write_pend = False
    refill_at = None
    width = 16 if r.head.get("width", "word") == "word" else 8
    while limit:
        limit -= 1
        _, w = prog.words[pc]
        f = w.fields
        # stalls: F waits for the datum, E waits for a RAMEN write's end
        if f.get("f") and done_at is not None and t < done_at:
            t = done_at
        if f.get("e") and write_pend and done_at is not None and t < done_at:
            t = done_at
        # (MX2) after a FLUSH the E word pops the target's opcode from the refill's first fetch:
        # issued on the flush's clock, its word on the clock after its BUS_CYCLE clocks (the
        # book's transfer formulas count that fetch at W = 0; the refill's later fetches are
        # the bus unit's and not counted)
        if f.get("e") and refill_at is not None and t < refill_at:
            t = refill_at
        if f.get("flush"):
            refill_at = t + BUS_CYCLE
        if f.get("bus") and f["bus"] != enum_value("v35_bus_e", "rsv"):   # (round 18) RSV posts nothing
            if done_at is not None and t < done_at:      # one request at a time
                t = done_at
            done_at = t + 1 + BUS_CYCLE
            write_pend = f["bus"] in (enum_value("v35_bus_e", "memw"), enum_value("v35_bus_e", "memwd"))
        if trace is not None:
            trace.append((t, pc, w))
        if f.get("e"):
            return t + 2                        # E, its post-E word, then the successor
        c = f.get("cnt", 0)
        newcnt = None
        if c in (enum_value("v35_cnt_e", "rb"), enum_value("v35_cnt_e", "il"),
                 enum_value("v35_cnt_e", "clh")):
            newcnt = n                          # (MX3c) CLH: n the byte pairs
        elif c == enum_value("v35_cnt_e", "bits"):
            newcnt = width
        elif c == enum_value("v35_cnt_e", "len"):
            newcnt = 0
        seq = f.get("seq", 0)
        nxt = pc + 1
        cond_v = {enum_value("v35_cond_e", "cntz"): cnt == 0,
                  enum_value("v35_cond_e", "word"): width == 16}
        if rep and sig is not None:
            cond_v[enum_value("v35_cond_e", "snz")] = sig != 0
        cv = cond_v.get(f.get("cond", 0), conds.get(f.get("cond", 0), False))
        if rep:
            if f.get("wr") == enum_value("v35_rsel_e", "cw") and \
                    f.get("ws") == enum_value("v35_src_e", "sig") and sig is not None:
                cw = sig
            a = f.get("alu", 0)
            if a and f.get("ra") == enum_value("v35_rsel_e", "cw") and \
                    f.get("ax") == enum_value("v35_src_e", "ra") and \
                    a in (enum_value("v35_alu_e", "pass"), enum_value("v35_alu_e", "dec")):
                sig = cw - (a == enum_value("v35_alu_e", "dec"))
            elif a:
                sig = None
        if seq == enum_value("v35_seq_e", "jmp"):
            nxt = f["tgt"]
        elif seq == enum_value("v35_seq_e", "jc"):
            nxt = f["tgt"] if cv else pc + 1
        elif seq == enum_value("v35_seq_e", "jnc"):
            nxt = pc + 1 if cv else f["tgt"]
        elif seq == enum_value("v35_seq_e", "call"):
            retr, nxt = pc + 1, f["tgt"]
        elif seq == enum_value("v35_seq_e", "ret"):
            if retr is None:
                raise UasmError(f"{name}: a return with no call")
            nxt, retr = retr, None
        elif seq == enum_value("v35_seq_e", "loop"):
            cnt -= 1
            nxt = f["tgt"] if cnt != 0 else pc + 1
        elif seq == enum_value("v35_seq_e", "eac"):
            # (MX3c) a 0F form's ModR/M pop: the register path jumps; a memory path calls the
            # EA head of its mode (returning to the next word), or goes on (mod 00 bare)
            if path == "r":
                nxt = f["tgt"]
            else:
                h = ea_head(r, path)
                if h is not None:
                    retr, nxt = pc + 1, prog.labels[h]
        elif seq in (enum_value("v35_seq_e", "dispm"), enum_value("v35_seq_e", "disp")):
            raise UasmError(f"{name}: the book check reached a dispatch")
        if newcnt is not None:
            cnt = newcnt
        if f.get("halt"):
            return t + 1
        t += 1
        pc = nxt
    raise UasmError(f"{name}: no E reached")


def path_words(prog: Program, name: str, n: int = 4, path: str = "m00") -> list:
    """The words a path executes (each once per execution), for the OPEN count on it.
    (work order 24) Run on the unshared program: OPEN is a mark of the source word (a stored
    tail's word may be OPEN in one routine and a named act's clock in another); the words
    executed are the same (test_uasm.TailSharing)."""
    tr = []
    length(prog.flat or prog, name, n, path=path, trace=tr)
    return [w for _, _, w in tr]


def book_values() -> dict:
    d = json.loads(BOOK.read_text())
    return d["forms"]


def eval_book(expr: str, ea: int, n: int) -> int | None:
    expr = expr.replace("EA", str(ea))
    expr = re.sub(r"(\d)([Wn])", r"\1*\2", expr).replace("W", "0")       # 2W = 2 * 0
    expr = re.sub(r"\)([n(])", r")*\1", expr)          # (MX3c) (30 + 3W)n: a product
    if not re.fullmatch(r"[0-9+*()n ]+", expr):
        return None
    return eval(expr, {}, {"n": n})


def book_value(form: str, width: str | None, n: int, ea: int = 3) -> int | None:
    """The book's clocks for a form at EA (3, or 4 for mod 10), W = 0 (a formula in n evaluated)."""
    f = book_values()[form]
    if width and f.get(width):
        expr = f[width]["expr"]
    else:
        expr = f.get("expr")
    if expr is None:
        return None
    return eval_book(expr, ea, n)


def parse_diff(h: dict) -> dict:
    """The declared difference per path: diff=K (every path) or diff=m00:K,d8:K,... ."""
    v = h.get("diff", "0")
    every = PATHS + XPATHS + (RPATH,)
    if ":" not in v:
        return {p: int(v) for p in every}
    out = {p: 0 for p in every}
    for part in v.split(","):
        k, _, x = part.partition(":")
        if k not in every:
            raise UasmError(f"diff path {k!r} (one of {every})")
        out[k] = int(x)
    return out


def book_paths(r) -> tuple:
    """The paths the book check runs for routine r: the four EA paths of a memory routine, the
    taken / not-taken paths of a transfer whose book form prints two values (or `xc=t`: the
    taken one), else the one path m00."""
    if is_mem(r):
        return mem_paths(r)
    if is_pmem(r):
        return (RPATH,) + PATHS if "book" in r.head else PATHS
    if r.head.get("xc") == "t":
        return ("t",)
    if "book" in r.head and len(book_values().get(r.head["book"], {}).get("values_printed")
                                or ()) == 2:
        return XPATHS
    return ("m00",)


def book_rows(prog: Program) -> list[tuple]:
    """(routine, book form, book value, routine length, declared diff, why, measured, path,
    OPEN words on the path) for every routine with book= (bookx=); a memory routine has one row
    per path (m00 d8 d16 dir), its declared diff the routine's plus its EA head's."""
    out = []
    names = {x.name for x in prog.routines}
    for r in prog.routines:
        h = r.head
        if "book" not in h and "bookx" not in h and "bookm" not in h:
            continue
        n = int(h.get("n", "4"))
        diffs = parse_diff(h)
        for path in book_paths(r):
            ea = PATH_EA.get(path, 3)
            two = book_values().get(h.get("book"), {}).get("values_printed") \
                if "book" in h else None
            pm = is_pmem(r) and path in PATHS        # (MX3c) a 0F memory form: bookm=
            if pm:
                bv = book_value(h["bookm"], h.get("width"), n, ea)
            elif "bookv" in h:
                bv = int(h["bookv"]) + (ea - 3 if is_mem(r) else 0)
            elif "bookx" in h:
                bv = eval_book(h["bookx"], ea, n)
            elif path in XPATHS and two and len(two) == 2:
                bv = max(two) if path == "t" else min(two)
            else:
                bv = book_value(h["book"], h.get("width"), n, ea)
            ln = length(prog, r.name, n, path=path)
            diff = diffs[path]
            why = h.get("why", "")
            hd = ea_head(r, path) if (is_mem(r) or pm) else None
            if hd is not None and hd in names:
                hr = prog.routine(hd)
                if "diff" in hr.head:
                    diff += parse_diff(hr.head)[path]
                    why = (why + " | the EA head " + hd + ": " + hr.head.get("why", "")).strip(" |")
            opens = sum(1 for w in path_words(prog, r.name, n, path) if w.open)
            form = h["bookm"] if pm else h.get("book", h.get("bookx"))
            out.append((r.name, form, bv, ln, diff, why,
                        h.get("measured", ""),
                        path if (is_mem(r) or path in XPATHS or is_pmem(r)) else "", opens))
    return out


def open_words(prog: Program) -> dict:
    """OPEN words per routine (the agenda: a book clock no act names)."""
    return {r.name: sum(1 for w in r.words if w.open) for r in prog.routines
            if any(w.open for w in r.words)}


def write(prog: Program) -> None:
    for name, text in outputs(prog).items():
        (V35 / name).write_text(text)


def check(prog: Program) -> list[str]:
    bad = []
    for name, text in outputs(prog).items():
        p = V35 / name
        if not p.exists() or p.read_text() != text:
            bad.append(name)
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m validation.v35s.chains.uasm",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="diff, do not write")
    ap.add_argument("--list", action="store_true", help="print the ROM listing")
    ap.add_argument("--book", action="store_true", help="print the book check's table")
    ap.add_argument("--no-share", action="store_true",
                    help="(work order 24) lay the routines out unshared, each contiguous (for "
                         "comparison; the checked-in ROM is the shared one)")
    ap.add_argument("--report", action="store_true",
                    help="(work order 24) per routine: its words' addresses, its own words and "
                         "the stored tail it joins; the totals per file")
    args = ap.parse_args(argv)
    prog = assemble(share=not args.no_share)
    if args.report:
        print(share_report(prog), end="")
    if args.list:
        print(listing(prog), end="")
    if args.book:
        for row in book_rows(prog):
            name, form, bv, ln, diff, why, meas, path, opens = row
            ok = bv is None or ln == bv + diff
            print(f"{'ok ' if ok else 'BAD'} {name:12s} {path:3s} {form:24s} book {bv!s:>4} "
                  f"len {ln:4d} diff {diff:+d} open {opens} measured {meas}  {why[:90]}")
        ow = open_words(prog)
        print(f"OPEN words: {sum(ow.values())} in {len(ow)} routines")
    if args.check:
        bad = check(prog)
        print("uasm: up to date" if not bad else f"uasm: stale {bad}")
        return 1 if bad else 0
    write(prog)
    print(f"uasm: {len(prog.routines)} routines, {len(prog.words)} words"
          + (f" ({len(prog.flat.words)} unshared, {len(prog.copies)} copies)" if prog.flat else
             " (unshared)") + f", {WORD_BITS} bits a word")
    return 0


if __name__ == "__main__":
    sys.exit(main())
