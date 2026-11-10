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
    resv        the reservation raised
    pop         a queue byte popped into MODRM IL IH DL DH
    e f         E (the next opcode popped; exactly one word follows) and F (wait for the datum)
    cnt         the loop counter's load (RB IL BITS LEN)
    seq         jmp=L  jc=COND:L  jnc=COND:L  call=L  ret  loop=L  dispm  (the word after E is
                the dispatch, DISP, set by the assembler)
    pfx flush halt trap

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
OUT_FILES = tuple(f"v35_urom_b{b}.hex" for b in range(BANKS)) + ("v35_udecode_tbl.svh",)
UADDR_W = int(re.search(r"localparam\s+int\s+UADDR_W\s*=\s*(\d+)", PKG.read_text()).group(1))

# the enum prefix and the field names of the word (read from the package)
PREFIX = {"v35_rsel_e": "RS_", "v35_wid_e": "WD_", "v35_src_e": "SR_", "v35_mvd_e": "MD_",
          "v35_alu_e": "AL_", "v35_ea_e": "EA_", "v35_bus_e": "BQ_", "v35_seg_e": "SG_",
          "v35_pop_e": "PP_", "v35_cnt_e": "CN_", "v35_seq_e": "SQ_", "v35_cond_e": "CD_"}


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
# the immediate bytes of a form without a ModR/M byte
IMM_PLAIN = {**{o: 1 for o in _ranges("04,0C,14,1C,24,2C,34,3C,6A,70-7F,A8,B0-B7,CD,D4,D5,"
                                      "E0-E7,EB,63")},
             **{o: 2 for o in _ranges("05,0D,15,1D,25,2D,35,3D,68,A0-A3,A9,B8-BF,C2,CA,E8,"
                                      "E9")},
             0xC8: 3, 0xEA: 4, 0x9A: 4}
SEG_PREFIX = {0x26: 0, 0x2E: 1, 0x36: 2, 0x3E: 3}      # the sreg: 0 DS1, 1 PS, 2 SS, 3 DS0
FLAG_OP = {0xF8: 0, 0xF9: 1, 0xF5: 2, 0xFA: 3, 0xFB: 4, 0xFC: 5, 0xFD: 6}
# the 0F page (the second byte): ModR/M present, immediate bytes after it
PAGE1_MODRM = set(_ranges("10-1F,28,2A,31,33,39,3B,2D,94,95"))
PAGE1_IMM = {**{o: 1 for o in _ranges("18-1F,39,3B,FF")}, 0x9C: 3}


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
         "len": IMM_PLAIN.get(op, 0)}
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
    elif op in (0xEA, 0x9A):
        f["w"] = 1
        f["immw"] = 1
    if op in SEG_PREFIX:
        f["seg"] = 4 | SEG_PREFIX[op]
    if op == 0x0F:
        f["len"] = 1                     # the page's second byte
    return f


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


SEQ_FIELDS = {"jmp", "jc", "jnc", "call", "loop"}
FLAGS = {"wf", "resv", "e", "f", "pfx", "flush", "halt", "trap", "ret", "dispm"}


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
            if k in SEQ_FIELDS:
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
                fields["seq"] = enum_value("v35_seq_e", "dispm")
            elif k in FLAGS and FIELD_TYPE.get(k) == "bit":
                fields[k] = 1
            else:
                raise UasmError(f"{path}:{ln}: unknown flag {tok!r}")
    if fields.get("ea") == enum_value("v35_ea_e", "bi") and fields.get("bus"):
        raise UasmError(f"{path}:{ln}: the EA's add posts (the request reads the address "
                        "register a word later)")
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
        if nxt.fields.get("pop") or nxt.fields.get("bus") or nxt.fields.get("e") \
                or nxt.fields.get("f") or nxt.fields.get("seq"):
            raise UasmError(f"{r.path}:{nxt.line}: the word after E pops, posts, waits or "
                            "sequences")
        nxt.fields["seq"] = enum_value("v35_seq_e", "disp")
        nxt.post_e = True
        i += 2
    es = [k for k, w in enumerate(r.words) if w.fields.get("e")]
    if es:
        last = max(es)
        if last + 2 < len(r.words) and not any(w.label for w in r.words[last + 2:]):
            raise UasmError(f"{r.path}:{r.words[last + 2].line}: a word after the post-E word "
                            "that nothing reaches")


@dataclass
class Program:
    routines: list
    words: list
    labels: dict
    cells1: dict          # opcode -> routine name (first level, no ModR/M)
    cells2: dict          # (opcode, modrm or second byte) -> routine name

    def routine(self, name: str):
        return next(r for r in self.routines if r.name == name)


HEAD0F = "page1"          # the 0F page's head
TRAP1 = "trap"            # an opcode without a routine
TRAP2 = "trapm"           # a ModR/M cell without a routine
TRAP0F = "trap0f"         # a 0F form without a ModR/M byte
TRAP0FM = "trap0fm"       # ... with one
RESET = "reset"
# (MX1) the EA heads (ea.uasm): the dispatch's targets for a ModR/M memory cell with a
# displacement (or, ea=book, at mod 00 too); each returns to the routine's entry (its add)
EA_HEADS = {"eab0": "UROM_EAB0", "eab8": "UROM_EAB8", "eab16": "UROM_EAB16", "ea8": "UROM_EA8",
            "ead": "UROM_EAD"}
PATHS = ("m00", "d8", "d16", "dir")
PATH_MODRM = {"m00": 0x07, "d8": 0x47, "d16": 0x87, "dir": 0x06}     # [BW], [BW+d8], [BW+d16], [d16]
PATH_EA = {"m00": 3, "d8": 3, "d16": 4, "dir": 3}                     # the book's EA


def is_mem(r) -> bool:
    return r.head.get("mod") == "mem"


def ea_head(r, path: str) -> str | None:
    """The head the dispatch calls for routine r on path (None: the routine's entry)."""
    book = r.head.get("ea", "book") == "book"
    if path == "m00":
        return "eab0" if book else None
    if path == "d8":
        return "eab8" if book else "ea8"
    if path == "d16":
        return "eab16" if book else "ead"
    return "ead"


def modrm_path(mb: int) -> str:
    md, rm = mb >> 6, mb & 7
    if md == 0:
        return "dir" if rm == 6 else "m00"
    return {1: "d8", 2: "d16"}[md]


def assemble(paths: list[Path] | None = None) -> Program:
    paths = paths if paths is not None else sorted(UROM.glob("*.uasm"))
    routines = []
    for p in paths:
        routines += parse_file(p)
    names = [r.name for r in routines]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise UasmError(f"routines defined twice: {sorted(dup)}")
    for need in (HEAD0F, TRAP1, TRAP2, TRAP0F, TRAP0FM, RESET):
        if need not in names:
            raise UasmError(f"no routine {need!r}")
    for r in routines:
        if is_mem(r) and r.head.get("ea", "book") not in ("book", "bare"):
            raise UasmError(f"{r.path}:{r.line}: ea={r.head['ea']!r} (book or bare)")
    words, labels = [], {}
    for r in routines:
        _finish(r)
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
        mods = {"reg": [3], "mem": [0, 1, 2], "any": [0, 1, 2, 3], "m00": [0]}[h.get("mod", "any")]
        regs = _ranges(h["reg"].replace("/", "")) if "reg" in h else list(range(8))
        rms = _ranges(h["rm"]) if "rm" in h else list(range(8))
        for op in ops:
            if op in MODRM_OPS:
                for md in mods:
                    for reg in regs:
                        for rm in rms:
                            cells2.setdefault((op, md << 6 | reg << 3 | rm), []).append(r.name)
            else:
                cells1.setdefault(op, []).append(r.name)
    for k, v in list(cells1.items()) + list(cells2.items()):
        if len(v) > 1:
            raise UasmError(f"decode cell {k} claimed by {v}")
    return Program(routines, words, labels, {k: v[0] for k, v in cells1.items()},
                   {k: v[0] for k, v in cells2.items()})


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
    if op == 0x0F:
        f["entry"], f["trap"] = prog.labels[HEAD0F], 0
    elif f["has_modrm"]:
        # (the dispatch reads the second level on the ModR/M byte the E word popped)
        f["entry"], f["trap"] = prog.labels[TRAP2], 0
    elif op in prog.cells1:
        f["entry"], f["trap"] = prog.labels[prog.cells1[op]], 0
    else:
        f["entry"], f["trap"] = prog.labels[TRAP1], 1
    # the reservation at the opcode's pop: its routine's header says `resv=e`
    f["rq"] = int(op in prog.cells1 and next(r for r in prog.routines
                                             if r.name == prog.cells1[op]).head.get("resv") == "e")
    return f


def udec2(prog: Program, op: int, b: int) -> dict:
    """The second level: (op, the popped byte) -> entry, trap, op3, (MX1) ea (a memory cell:
    the dispatch calls the EA head of the byte's mode) and eab (the book's EA heads)."""
    op3 = (b >> 3) & 7 if op in (0x80, 0x81, 0x82, 0x83, 0xC0, 0xC1, 0xD0, 0xD1, 0xD2, 0xD3,
                                 0xF6, 0xF7, 0xFE, 0xFF) else fmt_of(op)["op3"]
    if (op, b) in prog.cells2:
        r = prog.routine(prog.cells2[(op, b)])
        mem = op != 0x0F and is_mem(r) and b >> 6 != 3
        return {"entry": prog.labels[r.name], "trap": 0, "op3": op3, "ea": int(mem),
                "eab": int(mem and r.head.get("ea", "book") == "book")}
    if op == 0x0F:
        name = TRAP0FM if b in PAGE1_MODRM else TRAP0F
        return {"entry": prog.labels[name], "trap": 1, "op3": 0, "ea": 0, "eab": 0}
    return {"entry": prog.labels[TRAP2], "trap": 1, "op3": op3, "ea": 0, "eab": 0}


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
                 f"1'b{f['sx']}, 3'd{f['op3']}, 3'd{f['seg']}, 3'd{f['len']}, 1'b{f['rq']}}};")
    L += ["            default: f = '0;", "        endcase", "        v35_udec1 = f;",
          "    endfunction", ""]
    # the second level: one case per opcode with a ModR/M byte (and 0F), on the byte
    L += ["    function automatic v35_udecm_t v35_udec2(input logic [7:0] op, input logic [7:0] b);",
          "        v35_udecm_t f;",
          "        f = '0;",
          "        case (op)"]
    for op in sorted(MODRM_OPS | {0x0F}):
        L.append(f"            8'h{op:02X}: begin")
        # group the 256 byte values by result
        by = {}
        for b in range(256):
            g = udec2(prog, op, b)
            by.setdefault((g["entry"], g["trap"], g["op3"], g["ea"], g["eab"]), []).append(b)
        L.append("                case (b)")
        default = max(by, key=lambda k: len(by[k]))
        for k, bs in sorted(by.items()):
            if k == default:
                continue
            items = ", ".join(f"8'h{b:02X}" for b in bs)
            L.append(f"                    {items}: f = '{{{UADDR_W}'d{k[0]}, 1'b{k[1]}, "
                     f"3'd{k[2]}, 1'b{k[3]}, 1'b{k[4]}}};")
        k = default
        L.append(f"                    default: f = '{{{UADDR_W}'d{k[0]}, 1'b{k[1]}, 3'd{k[2]}, "
                 f"1'b{k[3]}, 1'b{k[4]}}};")
        L += ["                endcase", "            end"]
    L += [f"            default: f = '{{{UADDR_W}'d{prog.labels[TRAP2]}, 1'b1, 3'd0, 1'b0, 1'b0}};",
          "        endcase", "        v35_udec2 = f;", "    endfunction", ""]
    # (MX0) the loader's count of the instruction's bytes still to pop from the queue: what a
    # ModR/M byte's pop adds (its displacement and the form's immediate) and what the 0F page's
    # second byte's pop adds (its ModR/M byte and its immediate)
    L += ["    function automatic logic [2:0] v35_umodrm(input logic [7:0] op, input logic [7:0] mb);",
          "        logic [2:0] dsp;",
          "        dsp = mb[7:6] == 2'd1 ? 3'd1 : mb[7:6] == 2'd2 ? 3'd2"
          " : (mb[7:6] == 2'd0 && mb[2:0] == 3'd6) ? 3'd2 : 3'd0;",
          "        case (op)"]
    for op in sorted(MODRM_OPS):
        if op in (0xF6, 0xF7):
            n = 1 if op == 0xF6 else 2
            L.append(f"            8'h{op:02X}: v35_umodrm = dsp + (mb[5:4] == 2'd0 ? 3'd{n} : 3'd0);")
        elif imm_modrm(op, 0):
            L.append(f"            8'h{op:02X}: v35_umodrm = dsp + 3'd{imm_modrm(op, 0)};")
    L += ["            default: v35_umodrm = dsp;", "        endcase", "    endfunction", "",
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
    banks = rom_banks(prog)
    out = {f"v35_urom_b{b}.hex": banks[b] for b in range(BANKS)}
    out["v35_udecode_tbl.svh"] = decode_svh(prog)
    return out


def listing(prog: Program) -> str:
    L = []
    for r, w in prog.words:
        if w is r.words[0]:
            L.append(f"; {r.name} ({r.path}:{r.line}) {r.head}")
        addr = prog.words.index((r, w))
        L.append(f"{addr:4d} {pack(w.fields):022x} {w.label + ':' if w.label else '':10s} "
                 f"{w.act}")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ the book check's machine
BUS_CYCLE = 3          # a bus cycle at W = 0 (v35s-bus-timing.md)


def length(prog: Program, name: str, n: int = 4, conds: dict | None = None,
           limit: int = 4000, path: str = "m00", trace: list | None = None) -> int:
    """The routine's clocks from its entry to the successor's first word at EA = 3, W = 0, no
    queue stall: one word a clock; a request posted on clock p is granted on p + 1 and done on
    p + 1 + BUS_CYCLE (the F word and a RAMEN write's E wait for it); the counter's loads read
    n (CL, the immediate) or the width's bit count; conditions from `conds`. A 0F routine counts the
    page head's word. (MX1) A memory routine (`mod=mem`) runs from the EA head of `path` (the
    dispatch's call, returning to the routine's entry); `trace` collects (clock, address, word)."""
    conds = dict(conds or {})
    r = prog.routine(name)
    t = 0
    pc = r.base
    retr = None
    if r.head.get("page") == "0f":
        t = 1
    if is_mem(r):
        h = ea_head(r, path)
        if h is not None:
            pc, retr = prog.labels[h], r.base
    cnt = 0
    done_at = None
    write_pend = False
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
        if f.get("bus"):
            if done_at is not None and t < done_at:      # one request at a time
                t = done_at
            done_at = t + 1 + BUS_CYCLE
            write_pend = f["bus"] == enum_value("v35_bus_e", "memw")
        if trace is not None:
            trace.append((t, pc, w))
        if f.get("e"):
            return t + 2                        # E, its post-E word, then the successor
        c = f.get("cnt", 0)
        newcnt = None
        if c == enum_value("v35_cnt_e", "rb") or c == enum_value("v35_cnt_e", "il"):
            newcnt = n
        elif c == enum_value("v35_cnt_e", "bits"):
            newcnt = width
        elif c == enum_value("v35_cnt_e", "len"):
            newcnt = 0
        seq = f.get("seq", 0)
        nxt = pc + 1
        cond_v = {enum_value("v35_cond_e", "cntz"): cnt == 0,
                  enum_value("v35_cond_e", "word"): width == 16}
        cv = cond_v.get(f.get("cond", 0), conds.get(f.get("cond", 0), False))
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
    """The words a path executes (each once per execution), for the OPEN count on it."""
    tr = []
    length(prog, name, n, path=path, trace=tr)
    return [w for _, _, w in tr]


def book_values() -> dict:
    d = json.loads(BOOK.read_text())
    return d["forms"]


def eval_book(expr: str, ea: int, n: int) -> int | None:
    expr = expr.replace("EA", str(ea))
    expr = re.sub(r"(\d)([Wn])", r"\1*\2", expr).replace("W", "0")       # 2W = 2 * 0
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
    if ":" not in v:
        return {p: int(v) for p in PATHS}
    out = {p: 0 for p in PATHS}
    for part in v.split(","):
        k, _, x = part.partition(":")
        if k not in PATHS:
            raise UasmError(f"diff path {k!r} (one of {PATHS})")
        out[k] = int(x)
    return out


def book_rows(prog: Program) -> list[tuple]:
    """(routine, book form, book value, routine length, declared diff, why, measured, path,
    OPEN words on the path) for every routine with book= (bookx=); a memory routine has one row
    per path (m00 d8 d16 dir), its declared diff the routine's plus its EA head's."""
    out = []
    names = {x.name for x in prog.routines}
    for r in prog.routines:
        h = r.head
        if "book" not in h and "bookx" not in h:
            continue
        n = int(h.get("n", "4"))
        diffs = parse_diff(h)
        for path in (PATHS if is_mem(r) else ("m00",)):
            ea = PATH_EA[path]
            if "bookv" in h:
                bv = int(h["bookv"]) + (ea - 3 if is_mem(r) else 0)
            elif "bookx" in h:
                bv = eval_book(h["bookx"], ea, n)
            else:
                bv = book_value(h["book"], h.get("width"), n, ea)
            ln = length(prog, r.name, n, path=path)
            diff = diffs[path]
            why = h.get("why", "")
            hd = ea_head(r, path) if is_mem(r) else None
            if hd is not None and hd in names:
                hr = prog.routine(hd)
                if "diff" in hr.head:
                    diff += parse_diff(hr.head)[path]
                    why = (why + " | the EA head " + hd + ": " + hr.head.get("why", "")).strip(" |")
            opens = sum(1 for w in path_words(prog, r.name, n, path) if w.open)
            out.append((r.name, h.get("book", h.get("bookx")), bv, ln, diff, why,
                        h.get("measured", ""), path if is_mem(r) else "", opens))
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
    args = ap.parse_args(argv)
    prog = assemble()
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
    print(f"uasm: {len(prog.routines)} routines, {len(prog.words)} words, "
          f"{WORD_BITS} bits a word")
    return 0


if __name__ == "__main__":
    sys.exit(main())
