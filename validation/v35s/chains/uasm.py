"""The V35S core v2 microprogram assembler (MX0; docs/v35s-mechanisms.md section 4).

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.uasm [--check] [--list] [--l40]
        [--l40-report]

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

(Work order 26) the ROM is one part of 2,048 words (ROM_WORDS; a larger program fails), laid
out for the 40-bit word L40 (docs/v35s-urom-w40-layout.md) and checked against it on every
build (the L40 section below). With --l40 it also writes v35_l40_rom.hex (2,048 x 40),
v35_l40_x.hex / v35_l40_y.hex (the X / Y tables) and v35_l40.svh (the layout's constants);
--l40-report prints the packing.

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
# (work order 26) the ROM is one part of 2,048 words (v35_useq ROM_WORDS): v35_urom_b0..b2.hex.
# (qprobe round 12 to work order 25 a second, high part of 512 / 1,024 words in v35_urom_b3..b5.hex;
# work order 25's sharing left it empty and work order 26 removed it.) A larger ROM fails the build
ROM_WORDS = 2048
OUT_FILES = tuple(f"v35_urom_b{b}.hex" for b in range(BANKS)) + ("v35_udecode_tbl.svh",)
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


# ------------------------------------------------------------------ (work orders 24, 25) sharing
# The layout pass: the sources stay as written (each routine complete); the pass runs on the
# flat assembly and changes only where words sit and their sequencing fields, never what a path
# executes: every path runs the same words, field for field, clock for clock.
#
# The sequencer's next-address rule (v35_useq upc_n / raddr), which decides what is free:
#   NEXT, TRAP                   the next address (upc + 1)
#   JMP                          tgt
#   JC JNC LOOP TKI EAC          tgt or upc + 1 (EAC also the EA head from the decode, retr <- upc + 1)
#   CALL                         tgt, retr <- upc + 1
#   RET                          retr
#   DISP                         the decode's entry (or UROM_INT; the dispatch's EA-head call
#                                loads retr from the decode)
# A stalled word changes nothing (upc_n = upc, retr loads only with ex_b) and is read again.
# Nothing else in the RTL reads the sequencing field but the derived bits of DISP, DISPM, TKI
# and TRAP (v35_useq `pre`, v35_eu trap_o): CALL and RET are pure sequencing, so any word may
# carry them beside its acts; tgt is read as data only by SR_VEC (a vk word's vector).
#
# (work order 24) Tails. Every word identical to another together with its whole continuation is
# stored once (the coarsest partition: identical fields, NEXT = JMP, successors in one class,
# pairwise). A word joins a stored tail for free when its successor is reached by NEXT or JMP
# and its tgt field is not data: NEXT becomes JMP, the same clock. A word whose successor is
# upc + 1 under any other sequencing value (JC JNC LOOP TKI EAC TRAP, a call's return point, a
# vector word) needs that successor at the next address: of several such words before one
# stored word one falls into it and each other gets its own copy (and the copy's own forced
# successor in turn).
#
# (work order 25) Middles, through the one return register. A run w2 .. wk of plain words
# (NEXT / JMP, no E) that recurs with different continuations is stored once, wk carrying RET;
# at each use the word before the run, w1 (a NEXT / JMP word whose tgt is not data), becomes
# CALL to the stored run (its own acts kept) and its return point, upc + 1, holds the run's
# continuation there (a forced successor, as a call's return point always was). The executed
# words are the same in the same order. The return register is one level: retr must be dead
# at w1 and through the run in the unshared program, so no word reachable from a call target or
# an EA head before its RET (the `dly` ladders, the EA heads, every callee) is w1 or in a run,
# and no run holds a CALL, RET, EAC or dispatch. The run's words after w2 are entered from their
# predecessor alone and no run word is a label or a decode entry (the run is gone from the use
# site). A stored run may end in an existing RET tail (a callee's last words): the call then
# enters that tail. Chosen greedily by the words saved (the copies a busy return point forces
# counted), in a fixed order; the layout is then made as for tails.
#
# Addresses that mean something beyond the sequencing keep their own word: the word at
# UROM_REPP (v35_top's observation compares the address with rep_p's E word: rep_lk's and
# rep_sx's E words are the same bits) is never shared, called or stored in a run.
SHARE_DEFAULT = "full"      # "full": tails and middles; "tail": (work order 24) tails only
SHARE_MODES = ("full", "tail")
_SQ = {k[3:].lower(): v for k, v in ENUMS["v35_seq_e"][1].items()}
_SQN = {v: k for k, v in _SQ.items()}
_TGT_ADDR = {"jmp", "jc", "jnc", "call", "loop", "eac", "tki"}    # tgt is an address
_FT_FORCED = {"jc", "jnc", "call", "loop", "eac", "tki", "trap"}   # upc + 1 is a successor
_SR_VEC = ENUMS["v35_src_e"][1].get("SR_VEC")
SHARE_PINNED = ("rep_p",)        # routines whose entry word's address is read (UROM_REPP)
MID_MAX = 48                     # (work order 25) the longest middle run considered


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


class _Node:
    """A word of the layout graph: its fields without the sequencing (`f`: no seq; no tgt where
    tgt is an address), its sequencing kind `k` (JMP folded into NEXT: `ft` is then the one
    successor), `tgt` / `ft` the target and the next-address successor (node numbers), `data`
    the tgt is a vector, `first` the first flat word it holds (the order), `ordk` the order of
    its fall-through candidates (a flat word that fell through first), `src` the flat words."""
    __slots__ = ("f", "k", "tgt", "ft", "data", "pin", "first", "ordk", "src", "live", "dead",
                 "mid")

    def __init__(self, f, k, tgt, ft, data, pin, first, ordk, src):
        self.f, self.k, self.tgt, self.ft, self.data, self.pin = f, k, tgt, ft, data, pin
        self.first, self.ordk, self.src = first, ordk, src
        self.live = self.dead = False
        self.mid = None             # (work order 25) "call" / "run" / "ret": a middle share's word

    def succ(self) -> list:
        if self.k in ("next", "trap"):
            return [self.ft]
        if self.k in ("jc", "jnc", "loop", "tki", "eac", "call"):
            return [self.tgt, self.ft]
        return []

    def forced(self) -> bool:       # upc + 1 must hold the successor
        return self.k in _FT_FORCED or (self.k == "next" and self.data)

    def free(self) -> bool:         # NEXT / JMP: falls through or jumps, as the layout likes
        return self.k == "next" and not self.data

    def fkey(self) -> tuple:
        return tuple(sorted((a, v) for a, v in self.f.items() if v)), self.data


def _flat_nodes(W: list, pinned: set) -> list:
    n = len(W)
    out = []
    for i, (r, w) in enumerate(W):
        f0 = w.fields
        k = _seqk(f0)
        f = {a: v for a, v in f0.items() if a != "seq" and not (a == "tgt" and k in _TGT_ADDR)}
        tgt = ft = None
        if k == "jmp":
            k, ft = "next", f0.get("tgt", 0)
        elif k in ("next", "trap"):
            ft = i + 1
        elif k in _TGT_ADDR:
            tgt, ft = f0.get("tgt", 0), i + 1
        for s in (tgt, ft):
            if s is not None and not 0 <= s < n:
                raise UasmError(f"{r.name}: the word at {i} falls off the ROM")
        out.append(_Node(f, k, tgt, ft, _tgt_data(f0), i in pinned, i,
                         (0 if _seqk(f0) == "next" else 1, i), [i]))
    return out


def _refine(nodes: list) -> list:
    """The class of every node: two nodes are one class when their fields and kind are equal
    and their successors are one class, pairwise (the coarsest such partition)."""
    key0 = [(x.fkey(), x.k, x.first if x.pin else None) for x in nodes]
    ids = {}
    c = [ids.setdefault(k, len(ids)) for k in key0]
    while True:
        sig = [(c[i], tuple(c[s] for s in x.succ())) for i, x in enumerate(nodes)]
        ids = {}
        c2 = [ids.setdefault(s, len(ids)) for s in sig]
        if len(ids) == len(set(c)):
            return c2
        c = c2


def _quotient(nodes: list, c: list) -> tuple:
    """One node a class, numbered in the order of the first flat word each holds; returns the
    nodes and the map old node -> new node."""
    m = max(c) + 1
    mem = [[] for _ in range(m)]
    for i, x in enumerate(nodes):
        mem[c[i]].append(i)
    first = [min(nodes[i].first for i in mem[cl]) for cl in range(m)]
    order = sorted(range(m), key=lambda cl: (first[cl], cl))
    num = {cl: j for j, cl in enumerate(order)}
    out = []
    for cl in order:
        x = nodes[min(mem[cl], key=lambda i: (nodes[i].first, i))]
        y = _Node(dict(x.f), x.k, None if x.tgt is None else num[c[x.tgt]],
                  None if x.ft is None else num[c[x.ft]], x.data, x.pin, first[cl],
                  min(nodes[i].ordk for i in mem[cl]),
                  sorted(s for i in mem[cl] for s in nodes[i].src))
        y.live = any(nodes[i].live for i in mem[cl])
        y.mid = next((nodes[i].mid for i in mem[cl] if nodes[i].mid), None)
        out.append(y)
    return out, [num[c[i]] for i in range(len(nodes))]


def _live(G: list, starts) -> None:
    """(work order 25) mark every node the return register is live at: reachable from a call
    target or an EA head before a RET."""
    todo = list(starts)
    while todo:
        u = todo.pop()
        if G[u].live:
            continue
        G[u].live = True
        if G[u].k != "ret":
            todo += [s for s in G[u].succ() if s is not None]


def _share_middles(G: list, entries: set, starts: set, notgt=lambda x: False) -> tuple:
    """(work order 25) the middle shares on the class graph G (changed in place; stored runs
    appended). Returns (alias: a removed node -> the stored node holding its word, shares:
    [(m, stored nodes, [(callers, run nodes, return node)])])."""
    _live(G, starts)
    preds = {u: [] for u in range(len(G))}
    for u, x in enumerate(G):
        if x.k in _TGT_ADDR:
            preds[x.tgt].append((u, "tgt"))
        if x.ft is not None:
            preds[x.ft].append((u, "ft"))
    fk = {}

    def fid(u):
        k = G[u].fkey()
        return fk.setdefault(k, len(fk))

    def run_ok(u):
        x = G[u]
        return (not x.dead and x.k == "next" and not x.f.get("e") and not x.pin and not x.live
                and u not in entries)

    def caller_ok(u):
        x = G[u]
        return not x.dead and x.free() and not x.f.get("e") and not x.pin and not x.live \
            and not notgt(x)     # (work order 26) the call's target fits beside the word's acts

    def fin(u):
        return sum(1 for p, e in preds[u] if e == "ft" and G[p].forced())

    def chain_len(u):           # the words a copy of u brings (u and its forced successors)
        n, seen = 0, set()
        while u is not None and u not in seen:
            seen.add(u)
            n += 1
            u = G[u].ft if G[u].forced() else None
        return n

    alias, shares = {}, []
    while True:
        # the RET tails a stored run may end in: key (fields, from the run's first word) -> node
        retsuf = {}
        for z, x in enumerate(G):
            if x.dead or x.k != "ret" or not x.live:
                continue
            stack = [(z, (fid(z),))]
            while stack:
                u, key = stack.pop()
                retsuf.setdefault(key, u)
                if len(key) >= MID_MAX:
                    continue
                for p, e in sorted(preds[u], reverse=True):
                    if e == "ft" and G[p].k == "next" and G[p].live and not G[p].dead \
                            and not G[p].f.get("e"):
                        stack.append((p, (fid(p),) + key))
        # the candidate uses, by the run's fields
        groups = {}
        for c2 in range(len(G)):
            if not run_ok(c2):
                continue
            P = preds[c2]
            if not P or any(e != "ft" or not caller_ok(p) for p, e in P):
                continue
            P = sorted({p for p, _ in P})
            ch = [c2]
            while len(ch) < MID_MAX:
                nx = G[ch[-1]].ft
                if nx in ch or not run_ok(nx) or len(preds[nx]) != 1:
                    break
                ch.append(nx)
            key = ()
            for m in range(1, len(ch) + 1):
                key = key + (fid(ch[m - 1]),)
                N = G[ch[m - 1]].ft
                if N in ch[:m] or N in P:
                    continue
                groups.setdefault(key, []).append((P, ch[:m], N))
        best = None
        for key, uses in groups.items():
            m = len(key)
            j = max((t for t in range(m, 0, -1) if key[m - t:] in retsuf), default=0)
            stored = m - j
            covered, rets, removed, sel, gain = set(), set(), set(), [], 0
            for P, ch, N in uses:
                if (set(P) | set(ch)) & covered or N in removed or set(ch) & rets:
                    continue
                f0 = fin(N)
                fa = f0 - (1 if G[ch[-1]].forced() else 0) + len(P)
                g = m - chain_len(N) * (max(0, fa - 1) - max(0, f0 - 1))
                if g <= 0:
                    continue
                sel.append((P, ch, N))
                covered |= set(P) | set(ch)
                removed |= set(ch)
                rets.add(N)
                gain += g
            total = gain - stored
            if total > 0:
                cand = (total, m, -min(G[ch[0]].first for _, ch, _ in sel))
                if best is None or cand > best[0]:
                    best = (cand, key, sel, j)
        if best is None:
            break
        _, key, sel, j = best
        m = len(key)
        # the stored run: new words for key[:m - j], then the RET tail found (or RET on the last)
        S = []
        for t in range(m - j):
            x = G[sel[0][1][t]]
            y = _Node(dict(x.f), "next", None, None, x.data, False,
                      min(G[ch[t]].first for _, ch, _ in sel), None, [])
            y.ordk = (0, y.first)
            y.live, y.mid = True, "run"
            G.append(y)
            preds[len(G) - 1] = []
            S.append(len(G) - 1)
        tail = []
        if j:
            u = retsuf[key[m - j:]]
            while len(tail) < j:
                tail.append(u)
                u = G[u].ft
        else:
            G[S[-1]].k, G[S[-1]].mid = "ret", "ret"
        allw = S + tail
        for t in range(len(S)):
            if t + 1 < len(allw):
                G[S[t]].ft = allw[t + 1]
                preds[allw[t + 1]].append((S[t], "ft"))
        for P, ch, N in sel:
            for t, u in enumerate(ch):
                G[u].dead = True
                alias[u] = allw[t]
                preds[u] = []
            preds[N] = [(p, e) for p, e in preds[N] if p != ch[-1]]
            for p in P:
                x = G[p]
                x.k, x.tgt, x.ft, x.mid = "call", allw[0], N, "call"
                preds[allw[0]].append((p, "tgt"))
                preds[N].append((p, "ft"))
        shares.append((m, allw, sel))
    return alias, shares


def _layout(nodes: list, notgt=lambda x: False) -> tuple:
    """The words' addresses (work order 24's placement on a node graph): returns (seqv: the node
    at each address, node_cls: a placed node's class node (copies after the classes), outl: the
    fall-through links, addr: a class node's stored address, ucopy: (work order 26) the free nodes
    that run on into a copy of their successor). (Work order 26) a free word that cannot carry a
    jump in L40 (`notgt`) is placed in front of its successor before any other free word; where
    the place is taken it runs on into a copy (L40's way out U: stored words only)."""
    ncls = len(nodes)
    node_cls = list(range(ncls))
    inl, outl = {}, {}

    def link(a, b):
        inl[b], outl[a] = a, b

    # 1. a forced word's successor: of the classes forced into one class, the one whose first
    #    flat occurrence is earliest falls into the stored word (the source order kept)
    fpred = {}
    for cl in range(ncls):
        if nodes[cl].forced():
            fpred.setdefault(nodes[cl].ft, []).append(cl)
    for s, ps in fpred.items():
        link(min(ps, key=lambda p: nodes[p].first), s)

    # 2. the others: a copy of the successor after each, and of its own forced successor in turn
    def copy_after(pnode, cl):
        k = len(node_cls)
        node_cls.append(cl)
        link(pnode, k)
        if nodes[cl].forced() or (nodes[cl].free() and notgt(nodes[cl])):
            copy_after(k, nodes[cl].ft)

    for cl in range(ncls):
        if nodes[cl].forced() and outl.get(cl) is None:
            copy_after(cl, nodes[cl].ft)

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
    for cl in range(ncls):
        if nodes[cl].free():
            cand.setdefault(nodes[cl].ft, []).append((nodes[cl].ordk, cl))
    # ((work order 26) first the words that cannot jump, then the others: a cycle of fall-through
    # links is then cut at a word that can jump)
    for only in ((True, False) if any(notgt(x) for x in nodes) else (None,)):
        for s in sorted(cand, key=lambda s: nodes[s].first):
            if s in inl:
                continue
            for _, p in sorted(cand[s], key=lambda t: (not notgt(nodes[t[1]]), t[0])):
                if only is True and not notgt(nodes[p]):
                    continue
                if p not in outl and find(p) != find(s):
                    link(p, s)
                    par[find(s)] = find(p)
                    break

    # 3b. (work order 26) a free word that cannot jump and found no place: a copy of its
    #     successor behind it (and of the copy's own successor while the copy cannot jump either)
    ucopy = set()

    def ucopy_after(pnode, cl, depth=0):
        if depth > 64:
            raise UasmError("sharing (L40): a run of words that cannot jump has no end")
        k = len(node_cls)
        node_cls.append(cl)
        par.append(k)
        link(pnode, k)
        if nodes[cl].forced() or (nodes[cl].free() and notgt(nodes[cl])):
            ucopy_after(k, nodes[cl].ft, depth + 1)
    for cl in range(ncls):
        if nodes[cl].free() and notgt(nodes[cl]) and cl not in outl:
            ucopy.add(cl)
            ucopy_after(cl, nodes[cl].ft)

    # 4. the chains, in the order of their first words' first flat occurrence; addresses
    heads = [k for k in range(len(node_cls)) if k not in inl]
    if any(h >= ncls for h in heads):
        raise UasmError("sharing: a copy heads a chain")
    addr = {}
    seqv = []
    for h in sorted(heads, key=lambda h: (nodes[h].first, h)):
        k = h
        while k is not None:
            addr[k] = len(seqv)
            seqv.append(k)
            k = outl.get(k)
    if len(seqv) != len(node_cls):
        raise UasmError("sharing: a fall-through cycle")
    return seqv, node_cls, outl, addr, ucopy


def share_tails(flat: Program, pinned_routines=SHARE_PINNED, middles: bool = False,
                l40: bool = True, noj=frozenset()) -> Program:
    """The shared layout of a flat program (see the section's head): tails, and (middles,
    work order 25) middle runs through CALL / RET. (Work order 26, `l40`) no jump or middle call
    is given to a word that could not carry it in the 40-bit word (l40_tgt_ok; an arming word;
    the flat words in `noj`, the packer's feedback): such a word falls through, or runs on into a
    copy of its successor."""
    W = flat.words
    n = len(W)
    pinned = {flat.labels[x] for x in pinned_routines if x in flat.labels}
    bad = (arming_words(W, _succs) | set(noj)) if l40 else set()

    def notgt(x):
        return l40 and (l40_tgt_ok(x.f) is not None or any(i in bad for i in x.src))
    nodes0 = _flat_nodes(W, pinned)
    G, m1 = _quotient(nodes0, _refine(nodes0))
    fmap = m1                                   # flat word -> its node in G
    shares, alias, mcalls = [], {}, []
    G0 = G
    if middles:
        entries = {fmap[i] for i in flat.labels.values()}
        call_t = {W[i][1].fields.get("tgt", 0) for i in range(n) if _seqk(W[i][1].fields) == "call"}
        starts = {fmap[i] for i in call_t} | {fmap[flat.labels[h]] for h in EA_HEADS
                                               if h in flat.labels}
        alias, shares = _share_middles(G, entries, starts, notgt)
        G0 = G

        def fsucc(i):
            f0 = W[i][1].fields
            return f0.get("tgt", 0) if _seqk(f0) == "jmp" else i + 1
        for _, _, sel in shares:                # (caller, return point) flat words
            for P, ch, N in sel:
                for p in P:
                    for i in G[p].src:
                        s = i
                        for _ in range(len(ch) + 1):
                            s = fsucc(s)
                        mcalls.append((i, s))
        live = [u for u, x in enumerate(G) if not x.dead]
        ren = {u: j for j, u in enumerate(live)}
        G2 = []
        for u in live:
            x = G[u]
            x.tgt = None if x.tgt is None else ren[x.tgt]
            x.ft = None if x.ft is None else ren[x.ft]
            G2.append(x)
        for u in alias:                         # a stored word is ordered by the words it holds
            a = alias[u]
            G[a].first = min(G[a].first, G[u].first)
            G[a].src = G[a].src + G[u].src
        inrun = [u in alias for u in fmap]     # the flat words a stored run now holds
        fmap = [ren[alias.get(u, u)] for u in fmap]
        for x in G2:
            if x.mid == "run" or x.mid == "ret":
                x.ordk = (0, x.first)
        G, m2 = _quotient(G2, _refine(G2))
        fmap = [m2[u] for u in fmap]
    nodes = G
    ncls = len(nodes)
    seqv, node_cls, outl, addr, ucopy = _layout(nodes, notgt)

    # the words
    words = []
    for a, k in enumerate(seqv):
        cl = node_cls[k]
        x = nodes[cl]
        r, w0 = W[x.first]
        f = dict(x.f)
        f.pop("seq", None)
        nxt = outl.get(k)
        if x.free():
            f.pop("tgt", None)
            if not (nxt is not None and node_cls[nxt] == x.ft):
                f["seq"], f["tgt"] = _SQ["jmp"], addr[x.ft]
        else:
            if x.forced() and (nxt is None or node_cls[nxt] != x.ft or a + 1 >= len(seqv)
                               or seqv[a + 1] != nxt):
                raise UasmError(f"sharing: {r.name}: a forced successor not at the next address")
            if x.k != "next":
                f["seq"] = _SQ[x.k]
            if x.k in _TGT_ADDR:
                f["tgt"] = addr[x.tgt]
        words.append((r, Word(f, w0.act, w0.line, None, {}, w0.post_e, w0.open)))

    # every source word's address: at its node's stored word, or (a forced successor: the word
    # after a JC / LOOP / call / vector word, and (work order 25) a middle call's return point)
    # right after the address of the source word that forces it (a copy where it is one)
    fp = {}
    for i in range(1, n):
        j = i - 1
        x = nodes[fmap[j]]
        if _seqk(W[j][1].fields) != "jmp" and _succs(W[j][1].fields, j)[-1:] == [i] \
                and x.forced() and x.ft == fmap[i]:
            fp[i] = j
    # (work order 26) a word that cannot jump has its successor right behind it (the stored
    # word, or the copy it runs on into)
    for j in range(n):
        x = nodes[fmap[j]]
        if x.free() and notgt(x):
            f0 = W[j][1].fields
            i = f0.get("tgt", 0) if _seqk(f0) == "jmp" else j + 1
            if 0 <= i < n and fmap[i] == x.ft:
                fp.setdefault(i, j)
    for i, s in sorted(mcalls):
        if nodes[fmap[i]].k != "call" or nodes[fmap[i]].ft != fmap[s]:
            raise UasmError(f"sharing: {W[i][0].name}: a middle call's return is not its run's continuation")
        # (a flat word reached from several callers, e.g. through a source JMP into a common
        # word: the first caller places it; `where` names one address a source word is on)
        fp.setdefault(s, i)
    where = [None] * n

    def place(i):
        if where[i] is None:
            if i in fp:
                where[i] = -1                   # (a cycle guard)
                a = place(fp[i]) + 1
            else:
                a = addr[fmap[i]]
            where[i] = a
        if where[i] < 0:
            raise UasmError("sharing: a cycle of forced successors")
        return where[i]
    for i in range(n):
        place(i)
        if node_cls[seqv[where[i]]] != fmap[i]:
            raise UasmError(f"sharing: word {i} placed on another class")
    flat_k = {}
    for r in flat.routines:
        for k in range(len(r.words)):
            flat_k[r.base + k] = (r.name, k)
    owners = {}
    for i in range(n):
        owners.setdefault(where[i], []).append(flat_k[i])
    # (work order 26) a word that cannot jump runs on into a copy of its successor: the source
    # words then sit on the copy (`where` names one address a source word is on), and the stored
    # word, still entered from its other predecessors, is named by its class's source words
    named_twice = 0
    for a, k in enumerate(seqv):
        if a not in owners and ucopy:
            owners[a] = [flat_k[i] for i in nodes[node_cls[k]].src]
            named_twice += len(owners[a])
    dead = [a for a in range(len(words)) if a not in owners]
    if dead:
        raise UasmError(f"sharing: words no source word reaches: {dead[:8]} "
                        f"{[(a, seqv[a] >= ncls, nodes[node_cls[seqv[a]]].src[:4], [flat_k[i] for i in nodes[node_cls[seqv[a]]].src[:3]]) for a in dead[:8]]}")
    for a, (r, w) in enumerate(words):
        name, _ = owners[a][0]
        words[a] = (flat.routine(name), w)
    labels = {lab: addr[fmap[i]] for lab, i in flat.labels.items()}
    import dataclasses
    routines = [dataclasses.replace(r, base=labels[r.name]) for r in flat.routines]
    byname = {r.name: r for r in routines}
    words = [(byname[r.name], w) for r, w in words]
    for x in pinned:
        if len(owners[addr[fmap[x]]]) != 1 or sum(1 for k in node_cls if k == fmap[x]) != 1:
            raise UasmError(f"sharing: the pinned word {x} is shared")
    copies = {a for a, k in enumerate(seqv) if k >= ncls}
    prog = Program(routines, words, labels, flat.cells1, flat.cells2, flat.leads, flat.hlts,
                   flat=flat, where=where, owners=owners, copies=copies)
    # (work order 25) the middle shares: the calls' and the stored runs' addresses
    # (the stored runs' words: new ones, or a callee's RET tail a run ends in)
    prog.mcalls = {where[i] for i, _ in mcalls}
    prog.mruns = {where[i] for i in range(n) if inrun[i]} if middles else set()
    prog.mrets = {a for a in prog.mruns if _seqk(words[a][1].fields) == "ret"}
    prog.mshares = [{"m": m, "stored": sum(1 for u in allw if G0[u].mid in ("run", "ret")),
                     "callers": sorted(i for P, _, _ in sel for p in P for i in G0[p].src)}
                    for m, allw, sel in shares]
    prog.mcall_sites = sorted(mcalls)
    prog.share_mode = "full" if middles else "tail"
    # (work order 26) the L40 ways out in the layout: the free words that cannot jump and run on
    # into a copy of their successor (U), the words those copies add, the source words named on
    # a second address (a stored word whose source words sit on such a copy)
    prog.l40_ucopy = {addr[cl] for cl in ucopy}
    prog.l40_named_twice = named_twice
    return prog


def assemble(paths: list[Path] | None = None, share=None, l40: bool | None = None) -> Program:
    """The program: the sources assembled (assemble_flat), then laid out by `share` (default
    SHARE_DEFAULT): "full" (or True) tails and (work order 25) middles shared, "tail" (work
    order 24) tails only, False the flat layout (each routine contiguous). (Work order 26, `l40`,
    a shared layout) the layout gives no word a jump or a call it could not carry in the 40-bit
    word, and the result is packed and checked (l40_pack: `prog.l40`); a word the packer finds
    in a full table page sends its source words back to the layout as words that must not jump
    (repeated until nothing changes); a word that still does not fit fails the build."""
    flat = assemble_flat(paths)
    mode = SHARE_DEFAULT if share is None else share
    if mode is True:
        mode = "full"
    if not mode:
        flat.where = list(range(len(flat.words)))
        flat.owners = {}
        for r in flat.routines:
            for k in range(len(r.words)):
                flat.owners[r.base + k] = [(r.name, k)]
        flat.copies = set()
        flat.mcalls, flat.mrets, flat.mruns, flat.mshares, flat.mcall_sites = set(), set(), set(), [], []
        flat.share_mode = None
        return flat
    if mode not in SHARE_MODES:
        raise UasmError(f"share={mode!r} (of {SHARE_MODES}, or False)")
    if l40 is None:
        l40 = mode == "full"        # (work order 24's tail-only layout is over 2,048 words)
    if not l40:
        return share_tails(flat, middles=mode == "full", l40=False)
    noj, rounds = set(), []
    while True:
        prog = share_tails(flat, middles=mode == "full", noj=noj)
        img = l40_pack(prog, strict=False)
        rounds.append((len(prog.words), len(img.misfits)))
        new = set()
        for a, _, why in img.misfits:
            if "page" not in why and "table is full" not in why:
                continue
            for i, ad in enumerate(prog.where):
                if ad == a and _seqk(flat.words[i][1].fields) in ("next", "jmp"):
                    new.add(i)
        if not new - noj or len(rounds) > 16:
            break
        noj |= new
    prog.l40, prog.l40_noj, prog.l40_rounds = img, noj, rounds
    if img.misfits:
        raise UasmError("L40 (work order 26): words that do not fit the 40-bit word and have no "
                        "way out (the layout's placement, a copy, the take-entry codes):\n" + "\n".join(
                            f"  {a:4d} {nm}: {why}" for a, nm, why in img.misfits[:40]))
    return prog


def share_report(prog: Program) -> str:
    """Per routine: its words' addresses, which are its own and where it joins a stored tail
    (the first word stored with another routine's), (work order 25) its words that call a
    stored run; the totals per file; the stored runs (their length, address and callers)."""
    flat = prog.flat or prog
    L = []
    per_file = {}
    callers = {i for i, _ in (getattr(prog, "mcall_sites", None) or [])}
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
        calls = ""
        mc = [k for k in range(len(ad)) if (r.base + k) in callers]
        if mc:      # (work order 25) the words that call a stored run
            calls = "; calls " + ", ".join(
                f"word {k} -> {prog.words[ad[k]][1].fields['tgt']}" for k in mc)
        L.append(f"{r.name} ({r.path}:{r.line}) {len(ad)} words, {len(own)} own, "
                 f"{len(shared)} shared: {' '.join(runs)}{join}{calls}")
    L.append("")
    if prog.mshares:
        # (work order 25) the stored runs, in the order chosen
        tail = share_tails(flat, middles=False)
        saved = len(tail.words) - len(prog.words)
        L.append(f"(work order 25) middle shares: {len(prog.mshares)} stored runs, "
                 f"{len(prog.mcall_sites)} calling source words on {len(prog.mcalls)} call words; "
                 f"tails alone {len(tail.words)} words ({len(tail.copies)} copies), with the "
                 f"middles {len(prog.words)} ({len(prog.copies)} copies): {saved} saved")
        bym = {}
        for sh in prog.mshares:
            b = bym.setdefault(sh["m"], [0, 0, 0])
            b[0] += 1
            b[1] += sh["stored"]
            b[2] += len({prog.where[i] for i in sh["callers"]})
        for m in sorted(bym):
            n, st, cw = bym[m]
            L.append(f"  run of {m:2d}: {n:3d} stored ({st} new words), {cw:4d} call words")
        for x, sh in enumerate(prog.mshares):
            a = prog.where[sh["callers"][0]]
            t = prog.words[a][1].fields["tgt"]
            who = sorted({flat.name_of(i) for i in sh["callers"]})
            L.append(f"  {x:3d} run of {sh['m']} at {t} ({sh['stored']} new): called by "
                     f"{len(who)}: {' '.join(who[:8])}{' ...' if len(who) > 8 else ''}")
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


# ------------------------------------------------------------------ (work order 26) L40
# The 40-bit microword of docs/v35s-urom-w40-layout.md ("L40"), as a check-only pass behind the
# sharing layout: every stored word packed to 40 bits plus an entry of two generated tables (X:
# the ALU's fields, Y: the moves', the write's and the bus's), then decoded back through the table
# address select the w40 trial's RTL used (docs/v35s-urom-w40-trial.md) and compared with the
# 96-bit word field for field, with the early bits the sequencer reads from the ROM data before
# the word register. Hold counts are not part of it (SEQ codes 3 and 12 unused).
#
#     39..35 SEQ   sequencing and condition in one code (L40_SEQ)
#     34..26 K     e f nb bi vk ro rl[2] flush, raw
#     25..23 POP   raw          22..21 WID   raw
#     20..16 RA    a register selector (0..26), raw; 28..31: the word reads no register and
#                  P = {RA[1:0], RB} (7 bits) is payload
#     15..11 RB    a register selector, raw; or payload
#     10..0  B     SEQ >= 8: the target, or the vector number (VEC, TRAP); else payload, B[10] =
#                  POST. (Work order 26: TRAP's B is the vector too: the divide error's TRAP word
#                  reads SR_VEC; the expand stage loads tgt from B on every SEQ >= 8.)
#
#  form  (RA >= 28: N, else R; SEQ >= 8: T)
#  N   B[10] POST, B[9:2] Y (8, the half by POST), {P, B[1]} X (8), B[0] KW
#  NT  P < 48: X at 128 + P; 48..95: Y at 128 + P, half 0; 96..127: Y at 128 + P, half 1 (POST)
#  R   B[1:0] = 00: X (8) at B[9:2]; 10: B[10] POST, Y (8) at B[9:2]; B[0] = 1: B[10] POST,
#      Y (5) at 32 + B[9:5], X (4) at 16 + B[4:1]
#  RT  no payload
L40_BITS = 40
L40_XF = ("alu", "ax", "ay", "wf", "cnt")
L40_YF = ("d1", "s1", "d2", "s2", "wr", "ws", "ea", "bus", "seg", "pfx", "susp", "halt", "ist")
L40_KF = ("e", "f", "nb", "bi", "vk", "ro", "rl", "flush")
L40_POS = {"SEQ": (35, 5), "K": (26, 9), "POP": (23, 3), "WID": (21, 2), "RA": (16, 5),
           "RB": (11, 5), "B": (0, 11)}
L40_SEQ = {"NEXT": 0, "EREP": 1, "RET": 2, "HOLD": 3, "TKI0": 4, "TKI1": 5, "DISP": 6,
           "JMP": 8, "CALL": 9, "LOOP": 10, "EAC": 11, "HJMP": 12, "TRAP": 13, "VEC": 14,
           "JC": 16, "JNC": 24}
L40_ESC = 28                     # RA >= 28: no register; RA[1:0] is payload
L40_XN, L40_YN = 256, 256        # X entries; Y entries per half (two halves: POST)
# the pages (a base is an address prefix: the table address is the prefix and the code)
L40_XPAGE = {"R": (16, 16), "NT": (128, 48)}
L40_YPAGE = {"R": (32, 32), "NT": (176, 48), "NT1": (224, 32)}
_FW = {n: w for n, _, w in FIELDS}
L40_XBITS = sum(_FW[a] for a in L40_XF)
L40_YBITS = sum(_FW[a] for a in L40_YF)
_BUS_NONE = 0
_BUS_RSV = ENUMS["v35_bus_e"][1].get("BQ_RSV")
_BUS_MEMWD = ENUMS["v35_bus_e"][1].get("BQ_MEMWD")
_EA_REP = ENUMS["v35_ea_e"][1].get("EA_REP")
_MD_OPRW = ENUMS["v35_mvd_e"][1].get("MD_OPRW")
_RS_MAX = max(ENUMS["v35_rsel_e"][1].values())
_T_SEQ = ("jmp", "call", "loop", "eac", "jc", "jnc", "trap")     # B is not payload (+ VEC)


def _xp(f): return tuple(f.get(a, 0) for a in L40_XF)
def _yp(f): return tuple(f.get(a, 0) for a in L40_YF)
def _posts(f): return f.get("bus", 0) not in (_BUS_NONE, _BUS_RSV)
def _yposts(p): return p[L40_YF.index("bus")] not in (_BUS_NONE, _BUS_RSV)
def _kw(f): return f.get("d1", 0) == _MD_OPRW or f.get("d2", 0) == _MD_OPRW
def _isreg(f): return bool(f.get("ra") or f.get("rb"))
def _erep(f): return bool(f.get("e") and f.get("ea") == _EA_REP)


def l40_tgt_ok(f: dict) -> str | None:
    """(work order 26) whether a word with these fields (no sequencing) can also carry a target
    (a JMP or a middle share's CALL) in L40: None, or why not. The sharing pass asks it before it
    gives a word a jump or a call."""
    x, y = any(_xp(f)), any(_yp(f))
    if _erep(f):
        return "the E word re-entering the REP page (SEQ EREP) cannot also jump"
    if _isreg(f) and (x or y):
        return "a register read with a payload has no room for a target (form RT)"
    if x and y:
        return "X and Y payloads have no room beside a target (form NT: one code)"
    return None


def arming_words(words: list, succs) -> set:
    """The words that arm an unarmed write (bus=MEMWD: v35_eu rq_un): the first word on every
    path behind a MEMWD word that loads OPRW. Its KW bit is read early (form N only)."""
    out, seen = set(), set()
    todo = [(s, None) for i, (_, w) in enumerate(words) if w.fields.get("bus") == _BUS_MEMWD
            for s in succs(w.fields, i)]
    while todo:
        i, _ = todo.pop()
        if i in seen or not 0 <= i < len(words):
            continue
        seen.add(i)
        f = words[i][1].fields
        if _kw(f):
            out.add(i)
            continue
        todo += [(s, None) for s in succs(f, i)]
    return out


class L40Image:
    """The packed ROM: `rom` (40-bit words by address), `xtab` (L40_XN X payloads, () = none),
    `ytab` (two halves of L40_YN Y payloads), `tki` (the take entries), `forms` per address."""

    def __init__(self, prog):
        self.prog = prog
        self.rom, self.forms, self.misfits = [], [], []
        self.xtab = [None] * L40_XN
        self.ytab = [[None] * L40_YN, [None] * L40_YN]
        self.xtab[0] = ()
        self.xtab[L40_XPAGE["NT"][0]] = ()     # NT with no payload: P = 0
        self.ytab[0][0] = ()
        self.xwhere, self.ywhere = {}, {}
        self.lost = []
        self.tki = []

    # ---- the tables
    def _put(self, tab, where, p, rng):
        if any(q in rng for q in where.get(p, ())):
            return True
        for q in rng:
            if tab[q] is None:
                tab[q] = p
                where.setdefault(p, []).append(q)
                return True
        return False

    @staticmethod
    def _full(pages, size):
        """A full code's places: outside every page first (the pages' room kept for their forms)."""
        inp = {q for b, n in pages.values() for q in range(b, b + n)}
        return [q for q in range(size) if q not in inp] + sorted(inp)

    def xput(self, p, page=None):
        rng = range(*(lambda b, n: (b, b + n))(*L40_XPAGE[page])) if page else \
            self._full(L40_XPAGE, L40_XN)
        return self._put(self.xtab, self.xwhere, p, rng)

    def yput(self, p, page=None):
        h = int(_yposts(p))
        if page == "NT" and h:
            page = "NT1"
        rng = range(*(lambda b, n: (b, b + n))(*L40_YPAGE[page])) if page else \
            self._full(L40_YPAGE, L40_YN)
        return self._put(self.ytab[h], self.ywhere.setdefault(h, {}), p, rng)

    def xcode(self, p, page=None):
        if not any(p):
            return 0
        b, n = L40_XPAGE[page] if page else (0, L40_XN)
        return next((q - b for q in self.xwhere.get(p, ()) if b <= q < b + n), None)

    def ycode(self, p, page=None):
        if not any(p):
            return 0
        h = int(_yposts(p))
        if page == "NT" and h:
            page = "NT1"
        b, n = L40_YPAGE[page] if page else (0, L40_YN)
        return next((q - b for q in self.ywhere.get(h, {}).get(p, ()) if b <= q < b + n), None)

    # ---- the form of a stored word
    @staticmethod
    def seqk(f):
        return _SQN[f.get("seq", 0)]

    def is_vec(self, f):
        return _tgt_data(f)

    def target_half(self, f):
        k = self.seqk(f)
        return k in _T_SEQ or (k == "next" and self.is_vec(f))

    def form(self, f):
        return ("R" if _isreg(f) else "N") + ("T" if self.target_half(f) else "")

    def fit(self, f, arming):
        """None when the word fits, else the conflict."""
        k = self.seqk(f)
        c = self.form(f)
        x, y = _xp(f), _yp(f)
        hx, hy = any(x), any(y)
        if f.get("cond") and k not in ("jc", "jnc"):
            return "a condition without a conditional jump"
        if k == "dispm":
            return "DISPM (withdrawn)"
        if f.get("ra", 0) >= L40_ESC:
            return "a port A register selector of 28 or more (RA >= 28 is the escape)"
        if f.get("tgt", 0) >= 1 << 11:
            return "a target or vector beyond 11 bits"
        if arming and c != "N":
            return "the arming word of an unarmed write: the early KW bit is in form N only"
        if k == "tki" and self.tki.index(f.get("tgt", 0)) > 1:
            return "a third take entry (two TKI codes)"
        if self.is_vec(f) and k not in ("next", "trap"):
            return f"a vector number and the sequencing {k.upper()}"
        if _erep(f) and k != "next":
            return f"the E word re-entering the REP page (EREP) and the sequencing {k.upper()}"
        if f.get("e") and k not in ("next", "jmp"):
            return f"an E word's sequencing {k.upper()} (NEXT, EREP or JMP)"
        what = ("register read + " if _isreg(f) else "") + (
            "vector number" if self.is_vec(f) else "TRAP" if k == "trap" else
            "target" if c.endswith("T") else "")
        what = what.strip(" +")
        pl = " + ".join(n for n, h in (("X", hx), ("Y", hy)) if h)
        if c == "RT":
            return None if not (hx or hy) else f"{what} + {pl}: no payload bits (form RT)"
        if c == "NT":
            if hx and hy:
                return f"{what} + {pl}: one payload code only (form NT)"
            if hx and self.xcode(x, "NT") is None:
                return f"{what} + X: the X page of form NT is full"
            if hy and self.ycode(y, "NT") is None:
                return f"{what} + Y: the Y page of form NT is full"
            return None
        if c == "R" and hx and hy:
            if self.xcode(x, "R") is None:
                return "register read + X + Y: the X page of form R (16) is full"
            if self.ycode(y, "R") is None:
                return "register read + X + Y: the Y page of form R (32) is full"
            return None
        if hx and self.xcode(x) is None:
            return "the X table is full"
        if hy and self.ycode(y) is None:
            return "the Y table is full"
        return None

    def seq5(self, f):
        k = self.seqk(f)
        if k in ("jc", "jnc"):
            return L40_SEQ[k.upper()] | f.get("cond", 0)
        if k == "tki":
            return L40_SEQ["TKI1" if self.tki.index(f.get("tgt", 0)) else "TKI0"]
        if k == "next" and self.is_vec(f):
            return L40_SEQ["VEC"]
        if k == "next" and _erep(f):
            return L40_SEQ["EREP"]
        return L40_SEQ[k.upper()]

    def encode(self, f):
        c = self.form(f)
        x, y = _xp(f), _yp(f)
        kv = 0
        for a in L40_KF:
            kv = (kv << _FW[a]) | f.get(a, 0)
        post = int(_posts(f))
        ra, rb, b, p7 = f.get("ra", 0), f.get("rb", 0), 0, None
        if c == "N":
            xc = self.xcode(x)
            b = (post << 10) | (self.ycode(y) << 2) | ((xc & 1) << 1) | int(_kw(f))
            p7 = xc >> 1
        elif c == "NT":
            p7 = ((96 if post else 48) + self.ycode(y, "NT")) if any(y) else self.xcode(x, "NT")
            b = f.get("tgt", 0)
        elif c == "R":
            if any(x) and any(y):
                b = (post << 10) | (self.ycode(y, "R") << 5) | (self.xcode(x, "R") << 1) | 1
            elif any(y):
                b = (post << 10) | (self.ycode(y) << 2) | 2
            else:
                b = self.xcode(x) << 2
        else:                                   # RT
            b = f.get("tgt", 0)
        if p7 is not None:
            ra, rb = L40_ESC | (p7 >> 5), p7 & 31
        v = self.seq5(f)
        for val, wd in ((kv, 9), (f.get("pop", 0), 3), (f.get("wid", 0), 2), (ra, 5), (rb, 5),
                        (b, 11)):
            v = (v << wd) | val
        return v


def l40_fields(v: int) -> dict:
    """The raw fields of a 40-bit word (L40_POS)."""
    return {n: (v >> p) & ((1 << w) - 1) for n, (p, w) in L40_POS.items()}


def l40_table_addr(v: int) -> tuple:
    """(X address, Y address {half, index}) of a 40-bit word: the w40 trial's RTL address select
    (its gen/check_addr.py), without the hold forms."""
    r = l40_fields(v)
    s5, ra, rb, b = r["SEQ"], r["RA"], r["RB"], r["B"]
    esc, tf = ra >= L40_ESC, bool(s5 & 24)
    p7 = ((ra & 3) << 5) | rb
    bit = lambda n: (b >> n) & 1
    xa = ya = 0
    if esc:
        if tf:
            if p7 < 48:
                xa = 128 | p7
            else:
                ya = ((1 if p7 >= 96 else 0) << 8) | 128 | p7
        else:
            xa = (p7 << 1) | bit(1)
            ya = (bit(10) << 8) | ((b >> 2) & 255)
    elif not tf:
        if bit(0):
            xa = 16 | ((b >> 1) & 15)
            ya = (bit(10) << 8) | 32 | ((b >> 5) & 31)
        elif bit(1):
            ya = (bit(10) << 8) | ((b >> 2) & 255)
        else:
            xa = (b >> 2) & 255
    return xa, ya


def l40_early(v: int) -> dict:
    """The one-bit facts the tick-B logic reads from the raw word (no table): the dispatch, the
    take point, the REP re-entry, POST (the word posts a request), KW (the word loads OPRW: read
    for the arming word of an unarmed write)."""
    r = l40_fields(v)
    s5, ra, b = r["SEQ"], r["RA"], r["B"]
    tf, esc = s5 >= 8, ra >= L40_ESC
    return dict(disp=(s5 >> 1) == 3, tki=(s5 >> 1) == 2, erep=bool((r["K"] >> 8) & 1 and s5 & 1),
                post=(esc and (ra & 3) == 3) if tf else bool(b >> 10),
                kw=esc and s5 < 8 and s5 != L40_SEQ["HOLD"] and bool(b & 1))


def l40_unpack(v: int, img: "L40Image") -> dict:
    """(work order 26) a 40-bit word and its tables -> the 96-bit word's fields (unpack's dict):
    the expand stage. Tools read ROM fields through this or unpack."""
    r = l40_fields(v)
    s5, kv, ra, rb, b = r["SEQ"], r["K"], r["RA"], r["RB"], r["B"]
    out = {n: 0 for n, _, _ in FIELDS}
    for a in reversed(L40_KF):
        out[a] = kv & ((1 << _FW[a]) - 1)
        kv >>= _FW[a]
    out["pop"], out["wid"] = r["POP"], r["WID"]
    if s5 & 16:
        out["seq"], out["cond"] = _SQ["jnc" if s5 & 8 else "jc"], s5 & 7
        out["tgt"] = b
    else:
        n = {v_: k for k, v_ in L40_SEQ.items()}.get(s5)
        if n in (None, "HOLD", "HJMP"):
            raise UasmError(f"L40: SEQ code {s5} not used")
        if n in ("TKI0", "TKI1"):
            out["seq"], out["tgt"] = _SQ["tki"], img.tki[s5 & 1]
        elif n == "VEC":
            out["tgt"] = b
        elif n not in ("NEXT", "EREP"):
            out["seq"] = _SQ[n.lower()]
            if s5 >= 8:
                out["tgt"] = b
    if ra < L40_ESC:
        out["ra"], out["rb"] = ra, rb
    xa, ya = l40_table_addr(v)
    x = img.xtab[xa] or (0,) * len(L40_XF)
    y = img.ytab[ya >> 8][ya & 255] or (0,) * len(L40_YF)
    for a, val in zip(L40_XF, x):
        out[a] = val
    for a, val in zip(L40_YF, y):
        out[a] = val
    return out


def l40_program(prog) -> "Program":
    """(work order 26) a copy of the shared program whose words' fields are read back from the
    L40 image (l40_unpack): the ROM as the 40-bit word and its tables give it. For the tools
    that read ROM fields (romcheck --l40, the listing, test_uasm's walk)."""
    import copy
    import dataclasses
    img = prog.l40
    out = copy.copy(prog)
    out.words = [(r, dataclasses.replace(w, fields={k: v for k, v in l40_unpack(img.rom[a], img).items() if v}))
                 for a, (r, w) in enumerate(prog.words)]
    return out


def l40_pack(prog, strict: bool = True) -> L40Image:
    """The L40 image of the shared program: tables, packed words, the round trip checked. With
    `strict` a word that does not fit raises UasmError naming it; else `misfits` lists them
    ((address, routine words, reason))."""
    img = L40Image(prog)
    W = prog.words
    fs = [w.fields for _, w in W]
    for f in fs:
        if _SQN[f.get("seq", 0)] == "tki" and f.get("tgt", 0) not in img.tki:
            img.tki.append(f.get("tgt", 0))
    arm = arming_words(W, _succs)
    img.arming = arm
    # the table demand: the pages first (R with X and Y, NT), then the full codes
    need = []
    mcalls = getattr(prog, "mcalls", None) or set()
    for a, f in enumerate(fs):
        c = img.form(f)
        x, y = _xp(f), _yp(f)
        if c == "R" and any(x) and any(y):
            need.append((0, "x", x, "R"))
            need.append((0, "y", y, "R"))
        elif c == "NT" and not (any(x) and any(y)):
            # the pages go first to the words whose target the source gives (a condition, a
            # loop, a call: no way out), then to the layout's jumps and middle calls
            k = _SQN[f.get("seq", 0)]
            pri = 2 if k == "jmp" or (k == "call" and a in mcalls) else 1
            if any(x):
                need.append((pri, "x", x, "NT"))
            if any(y):
                need.append((pri, "y", y, "NT"))
    cnt = {}
    for t in need:
        cnt[t] = cnt.get(t, 0) + 1
    for (pri, t, p, page), n in sorted(cnt.items(), key=lambda kv: (kv[0][0], -kv[1], str(kv[0]))):
        if not (img.xput(p, page) if t == "x" else img.yput(p, page)):
            img.lost.append((t, page, p))
    allp = {}
    for f in fs:
        for t, p in (("x", _xp(f)), ("y", _yp(f))):
            if any(p):
                allp[(t, p)] = allp.get((t, p), 0) + 1
    for (t, p), n in sorted(allp.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        if t == "x" and not img.xwhere.get(p):
            if not img.xput(p):
                img.lost.append((t, None, p))
        elif t == "y" and not img.ywhere.get(int(_yposts(p)), {}).get(p):
            if not img.yput(p):
                img.lost.append((t, None, p))
    for a, f in enumerate(fs):
        why = img.fit(f, a in arm)
        img.forms.append(img.form(f))
        if why:
            img.misfits.append((a, prog.name_of(a), why))
            img.rom.append(0)
            continue
        v = img.encode(f)
        img.rom.append(v)
        bad = l40_check_word(img, a, f, v, a in arm)
        if bad:
            img.misfits.append((a, prog.name_of(a), "round trip: " + bad))
    if strict and img.misfits:
        raise UasmError("L40: words that do not fit and have no way out:\n" + "\n".join(
            f"  {a:4d} {nm}: {why}" for a, nm, why in img.misfits[:40]))
    return img


def l40_check_word(img, a, f, v, arming) -> str | None:
    """The 40-bit word against the 96-bit word: every field through the expand stage, and the
    early bits from the raw word (K, POP, WID, a named register, the one-bit facts)."""
    if not 0 <= v < 1 << L40_BITS:
        return "not 40 bits"
    ref = unpack(pack(f))
    got = l40_unpack(v, img)
    if not _tgt_data(f) and _SQN[f.get("seq", 0)] not in _TGT_ADDR:
        ref["tgt"] = 0                      # tgt is neither an address nor data: unread
    diff = [n for n in ref if ref[n] != got[n]]
    if diff:
        return "fields differ: " + ", ".join(f"{n} {ref[n]} -> {got[n]}" for n in diff)
    r = l40_fields(v)
    kv = 0
    for n in L40_KF:
        kv = (kv << _FW[n]) | ref[n]
    if r["K"] != kv or r["POP"] != ref["pop"] or r["WID"] != ref["wid"]:
        return "an early raw field differs"
    if _isreg(f) and (r["RA"] != ref["ra"] or r["RB"] != ref["rb"]):
        return "the early register read differs"
    e = l40_early(v)
    k = _SQN[f.get("seq", 0)]
    if e["disp"] != (k == "disp") or e["tki"] != (k == "tki") or e["erep"] != _erep(f) \
            or e["post"] != _posts(f):
        return f"an early bit differs: {e}"
    if e["kw"] and not _kw(f) or arming and not e["kw"]:
        return "the early KW bit differs"
    if f.get("e") and r["SEQ"] not in (0, 1, 8):
        return "an E word's SEQ is not NEXT, EREP or JMP"
    return None


def l40_outputs(img: L40Image) -> dict:
    """The L40 files (beside the 96-bit ones; nothing reads them yet): v35_l40_rom.hex (ROM_WORDS
    x 40), v35_l40_x.hex (256 x L40_XBITS), v35_l40_y.hex (512 x L40_YBITS: {POST half, index}),
    v35_l40.svh (the layout's constants)."""
    check_rom_size(len(img.rom))

    def packp(names, p):
        v = 0
        for a, val in zip(names, p or (0,) * len(names)):
            v = (v << _FW[a]) | val
        return v
    rom = img.rom + [0] * (ROM_WORDS - len(img.rom))
    xs = [packp(L40_XF, p) for p in img.xtab]
    ys = [packp(L40_YF, p) for h in range(2) for p in img.ytab[h]]
    out = {"v35_l40_rom.hex": "".join(f"{v:010x}\n" for v in rom),
           "v35_l40_x.hex": "".join(f"{v:0{(L40_XBITS + 3) // 4}x}\n" for v in xs),
           "v35_l40_y.hex": "".join(f"{v:0{(L40_YBITS + 3) // 4}x}\n" for v in ys)}
    L = ["// generated by validation/v35s/chains/uasm.py --l40 (work order 26): the 40-bit",
         "// microword L40 (docs/v35s-urom-w40-layout.md), its fields and codes. Nothing reads",
         "// this yet: the RTL step (v35_useq's expand stage) is the next one.",
         f"localparam int L40_BITS = {L40_BITS};",
         f"localparam int L40_WORDS = {ROM_WORDS};          // v35_l40_rom.hex"]
    for n, (p, w) in L40_POS.items():
        L.append(f"localparam int L40_{n}_LSB = {p}, L40_{n}_W = {w};")
    L.append("// K: {" + ", ".join(L40_KF) + "} (rl two bits), MSB first")
    for n, v in L40_SEQ.items():
        L.append(f"localparam logic [4:0] L40_SQ_{n} = 5'd{v};" + (
            "   // + cond" if n in ("JC", "JNC") else "   // (hold counts: unused)" if n in ("HOLD", "HJMP") else ""))
    L.append(f"localparam logic [4:0] L40_ESC = 5'd{L40_ESC};          // RA >= ESC: no register, P = {{RA[1:0], RB}}")
    for n, (b, s) in L40_XPAGE.items():
        L.append(f"localparam int L40_XPAGE_{n} = {b};      // the X address prefix; {s} entries")
    for n, (b, s) in L40_YPAGE.items():
        L.append(f"localparam int L40_YPAGE_{n} = {b};      // the Y index prefix; {s} entries")
    L.append(f"localparam int L40_XBITS = {L40_XBITS};   // v35_l40_x.hex: {{" + ", ".join(L40_XF) + "}")
    L.append(f"localparam int L40_YBITS = {L40_YBITS};   // v35_l40_y.hex: {{" + ", ".join(L40_YF) + "}")
    for k in range(2):
        t = img.tki[k] if k < len(img.tki) else 0
        L.append(f"localparam logic [UADDR_W-1:0] L40_TKI{k} = {UADDR_W}'d{t};   // take entry {k}"
                 + (f" ({img.prog.name_of(t)})" if k < len(img.tki) else " (unused)"))
    # the table entries the w40 trial's repairs compare the table address with (one-bit flops
    # beside the word: SUSP from Y; the interrupt controller's IVEC / FINT from X)
    def entries(tab, pred, w):
        return [q for q in range(len(tab)) if tab[q] and pred(dict(zip(w, tab[q])))]
    yall = img.ytab[0] + img.ytab[1]
    for nm, tab, names, pred, bits in (
            ("ysusp", yall, L40_YF, lambda d: d["susp"], 9),
            ("xivec", img.xtab, L40_XF, lambda d: d["alu"] == ENUMS["v35_alu_e"][1]["AL_IVEC"], 8),
            ("xfint", img.xtab, L40_XF, lambda d: d["alu"] == ENUMS["v35_alu_e"][1]["AL_FINT"], 8)):
        qs = entries(tab, pred, names)
        L += [f"// the {'Y' if nm[0] == 'y' else 'X'} entries with {nm[1:].upper()} ({len(qs)})",
              f"function automatic logic v35_l40_{nm}(input logic [{bits - 1}:0] a);",
              f"    case ({{{32 - bits}'d0, a}})     // (no 8-bit literal: test_v35_struct's opcode rule)"]
        if qs:
            L.append("        " + ", ".join(f"{q}" for q in qs) + f": v35_l40_{nm} = 1'b1;")
        L += [f"        default: v35_l40_{nm} = 1'b0;", "    endcase", "endfunction"]
    out["v35_l40.svh"] = "\n".join(L) + "\n"
    return out


# (work order 26) the L40 ways out written in the sources (each was a word that did not fit:
# a register read, a payload and a target in one word)
L40_SOURCE_EDITS = (
    ("rep_stm", "c5", "register read + Y + JNC", "the write datum's load (AW into OPRW) moved to "
     "c6, the head's empty word (way out a)"),
    ("rep_cmpbk", "c5", "register read + Y + JNC", "the address load dropped: c4 and c6 make the "
     "same load (way out a)"),
    ("rep_cmpm", "c5", "register read + Y + JNC", "the same (way out a)"),
    ("rep_cmpbk", "c21", "register read + Y + CALL w2", "the delay call takes its own first clock "
     "as a word (call=w1 on a word of its own)"),
    ("bcwz", "0", "register read + X + CALL w2", "the same"),
)


def l40_report(prog) -> str:
    """--l40-report: the words; the sharing layout without the L40 ways out and its misfits, each
    with the way out the L40 layout used; the final count; the tables' use; the pages' room."""
    img = prog.l40
    flat = prog.flat
    p0 = share_tails(flat, middles=prog.share_mode == "full", l40=False)
    i0 = l40_pack(p0, strict=False)
    L = [f"L40 (work order 26): the ROM as laid out for the 40-bit word, {len(img.rom)} words "
         f"(ROM {ROM_WORDS}: {ROM_WORDS - len(img.rom)} to spare)",
         "",
         f"1. The sharing layout without the L40 ways out (work order 25's, these sources): "
         f"{len(p0.words)} words; {len(p0.words) - len(i0.misfits)} fit as they stand, "
         f"{len(i0.misfits)} do not. Each, and the way out the L40 layout took:"]
    ways = {}
    for a, nm, why in i0.misfits:
        srcs = [i for i, ad in enumerate(p0.where) if ad == a]
        b = prog.where[srcs[0]]
        k = _SQN[prog.words[b][1].fields.get("seq", 0)]
        k0 = _SQN[p0.words[a][1].fields.get("seq", 0)]
        if b in prog.l40_ucopy:
            w = "U: runs on into a copy of its successor"
        elif a in p0.mcalls and b not in prog.mcalls:
            w = "no middle call on it (its run stays in line)"
        elif any(i in prog.l40_noj for i in srcs):
            w = "placement (a full NT page sent it back): falls through"
        elif k0 in ("jmp", "call") and k == "next":
            w = "placement: falls through into its successor"
        else:
            w = f"fits in the L40 layout as {img.form(prog.words[b][1].fields)} ({k})"
        ways[w] = ways.get(w, 0) + 1
        L.append(f"   {nm[:60]:60s} {why}")
        L.append(f"   {'':60s} -> {w}")
    L.append("   totals: " + "; ".join(f"{w}: {n}" for w, n in sorted(ways.items(), key=lambda t: -t[1])))
    L.append("")
    L.append("2. The ways out in the sources (each word did not fit; no clock moved):")
    for r, wd, what, how in L40_SOURCE_EDITS:
        L.append(f"   {r} {wd}: {what}: {how}")
    ntki = sum(1 for _, w in prog.words if _SQN[w.fields.get("seq", 0)] == "tki")
    L.append(f"   the take-entry codes TKI0 / TKI1: {ntki} TKI words, the take point beside a "
             f"register read and a payload; the two entries "
             f"{', '.join(prog.name_of(t) for t in img.tki)}")
    L.append("")
    L.append(f"3. The L40 layout: {len(prog.words)} words ({len(prog.words) - len(p0.words):+d} "
             f"against the layout without the ways out): {len(prog.copies)} copies "
             f"({len(p0.copies)} without), {len(prog.l40_ucopy)} words running on into a copy "
             f"(U), {len(prog.mcalls)} middle call words ({len(p0.mcalls)} without), "
             f"{len(prog.l40_noj)} source words sent back by a full page; the packer's rounds "
             f"(words, misfits) {prog.l40_rounds}")
    L.append(f"   final: {len(img.rom)} words, every one packed, decoded through the tables' "
             f"address select and compared with the 96-bit word field for field and early bit "
             f"for early bit ({len(img.misfits)} misfits); margin {ROM_WORDS - len(img.rom)} "
             f"words of {ROM_WORDS}")
    L.append("   forms: " + ", ".join(f"{c} {img.forms.count(c)}" for c in ("N", "NT", "R", "RT")))
    L.append("")
    xu = sum(1 for q in img.xtab if q)
    yu = [sum(1 for q in img.ytab[h] if q) for h in range(2)]
    L.append(f"4. Tables: X {xu} of {L40_XN} entries used ({len(img.xwhere)} distinct "
             f"payloads); Y {sum(yu)} of {2 * L40_YN} (no post {yu[0]}, post {yu[1]}; "
             f"{sum(len(v) for v in img.ywhere.values())} distinct); take entries "
             f"{len(img.tki)} of 2")
    L.append("   pages (used / size; free: how many more distinct entries the page can take):")
    rows = [("X R (X4, beside Y)", L40_XPAGE["R"], img.xtab), ("X NT", L40_XPAGE["NT"], img.xtab),
            ("Y R (Y5, beside X), no post", L40_YPAGE["R"], img.ytab[0]),
            ("Y R (Y5, beside X), post", L40_YPAGE["R"], img.ytab[1]),
            ("Y NT, no post", L40_YPAGE["NT"], img.ytab[0]),
            ("Y NT1, post", L40_YPAGE["NT1"], img.ytab[1])]
    for nm, (b, n), tab in rows:
        used = sum(1 for q in range(b, b + n) if tab[q])
        rsv = sum(1 for q in range(b, b + n) if tab[q] == ())
        L.append(f"   {nm:30s} {b:3d}..{b + n - 1:3d}: {used:3d} / {n:3d}"
                 f"{f' (+{rsv} reserved: no payload)' if rsv else ''}, {n - used - rsv:3d} free")
    L.append(f"   X full codes (N, R with X alone): {sum(1 for q in img.xtab if q is None)} of "
             f"{L40_XN} free")
    for h in range(2):
        L.append(f"   Y half {h} full codes (N, R with Y alone): "
                 f"{sum(1 for q in img.ytab[h] if q is None)} of {L40_YN} free")
    dem = {}
    for _, w in prog.words:
        f = w.fields
        c = img.form(f)
        x, y = _xp(f), _yp(f)
        if c == "R" and any(x) and any(y):
            dem.setdefault("X R", set()).add(x)
            dem.setdefault(f"Y R half {int(_yposts(y))}", set()).add(y)
        elif c == "NT" and any(x) and not any(y):
            dem.setdefault("X NT", set()).add(x)
        elif c == "NT" and any(y) and not any(x):
            dem.setdefault("Y NT" + ("1" if _yposts(y) else ""), set()).add(y)
    L.append("   distinct payloads the page forms need: " + ", ".join(
        f"{k} {len(v)}" for k, v in sorted(dem.items())))
    inh = {}
    for a, (_, w) in enumerate(prog.words):
        f = w.fields
        k = _SQN[f.get("seq", 0)]
        if img.form(f) != "NT" or k == "jmp" or (k == "call" and a in prog.mcalls):
            continue
        x, y = _xp(f), _yp(f)
        if any(x) and not any(y):
            inh.setdefault("X NT", set()).add(x)
        elif any(y) and not any(x):
            inh.setdefault("Y NT" + ("1" if _yposts(y) else ""), set()).add(y)
    L.append("   ... of them on the NT pages by a word whose target the source gives (a condition, "
             "a loop, a take point, EAC, TRAP, a vector, a delay call: no way out; the rest are the layout's "
             "jumps and calls, which fall through or run on into a copy when a page is full): "
             + ", ".join(f"{k} {len(v)}" for k, v in sorted(inh.items())))
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


def check_rom_size(n: int) -> None:
    """(work order 26) the ROM is one part of ROM_WORDS words: a larger program fails the build."""
    if n > ROM_WORDS:
        raise UasmError(f"{n} words: more than the ROM's {ROM_WORDS} (v35_useq ROM_WORDS; the high "
                        f"part was removed in work order 26)")


def outputs(prog: Program) -> dict:
    check_rom_size(len(prog.words))
    banks = [b.split() for b in rom_banks(prog)]
    out = {}
    for b in range(BANKS):
        out[f"v35_urom_b{b}.hex"] = "\n".join(banks[b]) + "\n"
    out["v35_udecode_tbl.svh"] = decode_svh(prog)
    return out


def listing(prog: Program, l40w: bool = False) -> str:
    """The ROM by address: a routine's header where its entry is, each word's bits, its label
    and act; (work order 24) a word stored for several routines lists every owner (`= name+k`),
    a copy is marked `copy`; (work order 25) a middle share's call and its stored run's words
    are marked. (Work order 26, `l40w`) the 40-bit word beside the 96-bit one."""
    flat = prog.flat or prog
    l40w = l40w and getattr(prog, "l40", None) is not None
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
        if addr in (getattr(prog, "mcalls", None) or ()):
            tag += " (calls a stored run)"
        if addr in (getattr(prog, "mruns", None) or ()):
            tag += " (stored run" + (", returns)" if addr in prog.mrets else ")")
        l40 = f"{prog.l40.rom[addr]:010x} " if l40w else ""
        L.append(f"{addr:4d} {pack(w.fields):024x} {l40}{lab + ':' if lab else '':10s} "
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


def write(prog: Program, l40: bool = False) -> None:
    out = outputs(prog)
    if l40:
        out.update(l40_outputs(prog.l40))
    for name, text in out.items():
        (V35 / name).write_text(text)


def check(prog: Program, l40: bool = False) -> list[str]:
    bad = []
    out = outputs(prog)
    if l40:
        out.update(l40_outputs(prog.l40))
    for name, text in out.items():
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
    ap.add_argument("--tail-only", action="store_true",
                    help="(work order 25) share tails only (work order 24's layout; for "
                         "comparison: the checked-in ROM shares tails and middles)")
    ap.add_argument("--l40", action="store_true",
                    help="(work order 26) also write the 40-bit ROM (v35_l40_rom.hex, 2,048 x 40), "
                         "its X / Y tables (v35_l40_x.hex, v35_l40_y.hex) and v35_l40.svh; with "
                         "--check: diff them too; with --list: the 40-bit word in the listing")
    ap.add_argument("--l40-report", action="store_true",
                    help="(work order 26) print the L40 packing: words, misfits and their ways "
                         "out, the final count, the tables' and pages' use")
    ap.add_argument("--report", action="store_true",
                    help="(work order 24) per routine: its words' addresses, its own words and "
                         "the stored tail it joins; the totals per file")
    args = ap.parse_args(argv)
    prog = assemble(share=False if args.no_share else "tail" if args.tail_only else None)
    if (args.l40 or args.l40_report) and getattr(prog, "l40", None) is None:
        raise SystemExit("--l40 / --l40-report: the L40 image is of the default layout (tails and "
                         "middles shared)")
    if args.report:
        print(share_report(prog), end="")
    if args.l40_report:
        print(l40_report(prog), end="")
    if args.list:
        print(listing(prog, l40w=args.l40), end="")
    if args.book:
        for row in book_rows(prog):
            name, form, bv, ln, diff, why, meas, path, opens = row
            ok = bv is None or ln == bv + diff
            print(f"{'ok ' if ok else 'BAD'} {name:12s} {path:3s} {form:24s} book {bv!s:>4} "
                  f"len {ln:4d} diff {diff:+d} open {opens} measured {meas}  {why[:90]}")
        ow = open_words(prog)
        print(f"OPEN words: {sum(ow.values())} in {len(ow)} routines")
    if args.check:
        bad = check(prog, l40=args.l40)
        print("uasm: up to date" if not bad else f"uasm: stale {bad}")
        return 1 if bad else 0
    write(prog, l40=args.l40)
    print(f"uasm: {len(prog.routines)} routines, {len(prog.words)} words"
          + (f" ({len(prog.flat.words)} unshared, {len(prog.copies)} copies, "
             f"{len(prog.mshares)} stored runs called from {len(prog.mcalls)} words)" if prog.flat else
             " (unshared)") + f", {WORD_BITS} bits a word")
    return 0


if __name__ == "__main__":
    sys.exit(main())
