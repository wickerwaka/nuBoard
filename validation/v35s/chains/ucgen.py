"""The V35S core v2 generator: microcode rows, templates, decode and class tables (S1).

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains ucgen [--check] [--out DIR]

docs/v35s-core-v2.md ("Microcode", "Function path", Appendix B s3/s4) is the design. This
script reads the tracked fit (`sim.config.Config.fitted()`, validation/v35s/chains/fit.json) and
the live model (`sim.templates`: `decode`, `steps`), and writes under fpga/v35s/core/v35/:

- `v35_ucode.hex`      the microcode ROM, one row per line (ROW_FIELDS below, LSB first);
- `v35_ucode_tbl.svh`  the template table (template id -> first row, row count) and
                       `v35_tmpl_of(fmt, run)`: class x format bits x start-time bits -> template;
- `v35_decode_tbl.svh` the decode table: 256 native + 256 0F-page entries and the group
                       (ModR/M reg field) override table;
- `v35_class_tbl.svh`  the class table: the class integers hardwired logic reads outside rows;
- `v35_consts.svh`     the EA table, hold_q, io_b2b_q, wlatch, io_recover and the field widths;
- `v35_pkg.sv`         the package: the enums, `uc_row_t`, `v35_fmt_t`, `v35_run_t`, the
                       `v35_fmt_of(opcode, page, modrm)` and `v35_tmpl_of` functions; it
                       includes the four .svh tables.

How it works (all of it checked by test_ucgen):

1. Enumeration (as rtlgen did): every opcode x second byte (x third byte on the 0F page) through
   the live decoder under flag / CW states that give every transfer both outcomes (four, and
   all 32 flag sets for 70-7F / E0-E3); each distinct decode is a *form*. `started`
   applies what eu._start decides before it builds the template (nowrite, grp_class, the count
   byte form, the CL mask); the model's step list is `[("wbsync",)]` (when the class has one) +
   `templates.steps(op, cfg)`.
2. Symbolic sources: the form is rebuilt with sentinel operands (EA, SP, BP, IX, IY, port,
   vector, target) so every address names its source, and its step list is compared with
   lists built under perturbations (the EA table entry of the form's mode, the shift count,
   MUL's sign clocks, the bit field's cost); an integer that moves with one of them is that
   source (`nsrc`), the rest is a literal resolved from the fit.
3. Rows: one row per timed model step. Zero-time model steps fold into rows: the waits
   (`wait`, `issued`, `wbsync`, `quiet`, `slot`) become the next row's `wcond` field and the side
   effects (`fetch_hold`, `fetch_release`, `flush_from`, `held_clocks`) its `arm` field
   (`apos`: on entry, after the wait, or on leaving the row). `("take", 0)` and literal
   `("clocks", 0)` produce no row.
4. Loops: a REP string and a BCD string run one element body `n` times (`ltop` / `loop`, the
   element counter hardwired); a compare's exit and a bit field's crossing are rows with a
   `skip` condition; the relatch rows (port_latch=relatch) follow every port take, skipped when
   no detached I/O is held.
5. Templates: identical row lists are one template; `v35_tmpl_of` selects by class and the
   format bits (and the start-time bits taken / zfail / cnt0 / half / n0) each class needs
   (reduced per class to the bits that change its template).

The canonical form both sides of the inverse check are compared in (`canonical`): the step
list with `("take", 0)` and every `("clocks", 0[, tag])` removed (no-ops in eu.tick: `continue`
without a resume) and a request step's trailing default arguments dropped (eu._post's free=None,
grp / whole / restart False). The model side is `model_steps` (wbsync + templates.steps, and the
relatch insertion when a detached I/O is held); the ROM side is `expand`: the template's rows in
order, each [ENTRY arm] [wait] [PRE_OP arm] [step] [EXIT arm], skipped rows nothing, the element
loop run n times.
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import hashlib
import json
import re
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "fpga" / "v35s" / "core" / "v35"
PLA = ROOT / "fpga" / "v35s" / "core" / "ucore" / "pla3_tables.svh"
INSTR_JSON = ROOT / "build" / "deps" / "nuV30" / "docs" / "facts" / "instructions.json"
INVOCATION = "python -m validation.v35s.chains ucgen"
# (S3) the ROM is also written as four banks by row address mod 4 (v35_ucode.sv reads a window
# of four consecutive rows a clock, one row from each bank: four block RAMs with one read port)
ROM_BANKS = 4
FILES = ("v35_ucode.hex", "v35_ucode_tbl.svh", "v35_decode_tbl.svh", "v35_class_tbl.svh",
         "v35_consts.svh", "v35_pkg.sv") + tuple(f"v35_ucode_b{b}.hex" for b in range(ROM_BANKS))


class UcgenError(RuntimeError):
    pass


class NotModelled(UcgenError):
    """The decoder accepts the encoding but the template has no operand for a request (8F /0,
    C6 /0, FF /6, F6 / F7 /2-/3 with a register operand): not a form the model runs (trap_nop)."""


# --------------------------------------------------------------------------------------------
# The row format
# --------------------------------------------------------------------------------------------

# op: the row's timed action (the model's step kinds that are not folded)
OPS = ("NOP",           # no action of its own: a wait and / or a side effect alone
       "CLOCKS",        # res_cnt := n (nsrc), next row after n clocks
       "NOWAIT",        # n clocks not in a bus wait state (the model continues on the last)
       "TAKE",          # take aidx operand bytes (tag: lead / chain / word / chain_word / port)
       "DATA",          # post the request, wait for its data (read) or issue (write)
       "POST",          # post the request and go on
       "POST_IO",       # post a detached I/O request (io_release=post) and go on
       "FLUSH",         # a taken transfer's flush, gap fgap (class table)
       "FLUSH_C",       # the same, gap cfgap (cond_gap=own)
       "DECIDE",        # a not-taken transfer's wait, gap nfgap
       "HALT",
       "FROM_START",    # cvt_from=start: to imm clocks after the start (armed), else x clocks
       "SPLIT_FLOOR")   # str_split=floor: no earlier than imm clocks after the split half
# nsrc: where a CLOCKS / NOWAIT count or a request's setup comes from
NSRC = ("LIT",          # imm
        "EA",           # imm + the EA table entry of the form's mode
        "CNT",          # imm + per_shift_count x the shift count (hardwired counter)
        "UNIT",         # imm + MUL's sign clocks (mul_data=sign, from the operands)
        "BF",           # max(0, bit field cost - imm)
        "STR")          # imm + the element's setup: first (element 0), loop1 (1), loop
# asrc: a request's address; aidx the word index (address +- 2 x aidx)
ASRC = ("NONE", "EA",   # EA + 2i
        "SPW",          # SP - 2 - 2i (stack writes)
        "SPR",          # SP + 2i (stack reads)
        "BP",           # BP + 2i (DISPOSE)
        "PORT_IMM",     # the port byte
        "PORT_DW",      # DW
        "IX", "IY",     # IX + 2i, IY + 2i (bit fields)
        "VEC",          # BRK's vector 4n + 2i
        "STR_IX", "STR_IY")   # IX / IY + element x width (strings, BCD strings)
WAITS = ("NONE",
         "OWN_DONE",    # ("wait",): the own request's data / issue
         "OWN_ISSUED",  # ("issued",): the own request on the bus
         "SLOT",        # ("slot",): the slot holds no detached I/O (relatch), then latch_until
         "WB",          # ("wbsync",): the previous instruction's write-back done
         "QUIET")       # ("quiet",): no fetch on the bus or wanted
TAGS = ("NONE", "EA", "MEXEC", "LEAD", "CHAIN", "WORD", "CHAIN_WORD", "PORT")
RKINDS = ("NONE", "READ", "WRITE", "IO_READ", "IO_WRITE", "NOWRITE")
WSEL = ("FMT", "BYTE", "WORD")
I2M = ("NONE", "LIT", "SETUP_MINUS")        # the request's fetch-free clocks: x / setup - x
ARMS = ("NONE",
        "HOLD",          # ("fetch_hold", x): str_held / lift a take hold (x = 0)
        "HOLD_ROOM",     # ("fetch_hold", x, "room"): mul_imm_half=room
        "HOLD_TAKE",     # ("fetch_hold", BF_TAKE_HOLD): armed from the next take
        "HOLD_TAKE_DLV",  # ("fetch_hold", BF_TAKE_HOLD, "dlv"): cvt_hold
        "HOLD_LONG",     # ("fetch_hold", BCD_HOLD), element 0 only (bcd_fetch=hold)
        "REL",           # ("fetch_release", x)
        "REL_FOREVER",   # ("fetch_release", None)
        "REL_RAISE",     # ("fetch_release", x, "raise")
        "FLUSH_FROM",    # ("flush_from", x)
        "HELD")          # ("held_clocks", x)
ARMS_X = ("HOLD", "HOLD_ROOM", "REL", "REL_RAISE", "FLUSH_FROM", "HELD")
APOS = ("ENTRY",        # on the clock the row is entered, before its wait
        "PRE_OP",       # once the wait holds, before the action
        "EXIT")         # as the row is left (after the action; every loop iteration)
SKIPS = ("NONE",
         "COND",        # skipped when a REP compare ended on its condition
         "NCOND",       # skipped when it did not
         "NOHELD",      # skipped when the port take found no detached I/O held (relatch)
         "CROSS",       # skipped when the bit field crosses into the next word
         "NCROSS")      # skipped when it does not

# (name, bits), LSB first; v35_pkg.uc_row_t lists them MSB first
ROW_FIELDS = (("op", 5), ("tdelay", 1), ("last", 1), ("skip", 3), ("wcond", 3), ("nsrc", 3),
              ("imm", 9), ("tag", 3), ("ltop", 1), ("loop", 1), ("lastadd", 1),
              ("rkind", 3), ("asrc", 4), ("aidx", 3), ("wsel", 2), ("i2m", 2), ("x", 7),
              ("grp", 1), ("whole", 1), ("restart", 1), ("detached", 1),
              ("arm", 4), ("apos", 2), ("wb", 2))
ROW_ENUMS = {"op": OPS, "skip": SKIPS, "wcond": WAITS, "nsrc": NSRC, "tag": TAGS, "rkind": RKINDS,
             "asrc": ASRC, "wsel": WSEL, "i2m": I2M, "arm": ARMS, "apos": APOS}
ROW_BITS = sum(b for _, b in ROW_FIELDS)
ROWA_BITS = 11              # a row address: the ROM holds at most 2048 rows (test_ucgen)
TMPL_BITS = 9               # a template id: at most 512 templates (test_ucgen)
ROW_DEFAULT = {"op": "NOP", "tdelay": 0, "last": 0, "skip": "NONE", "wcond": "NONE",
               "nsrc": "LIT", "imm": 0, "tag": "NONE", "ltop": 0, "loop": 0, "lastadd": 0,
               "rkind": "NONE", "asrc": "NONE", "aidx": 0, "wsel": "FMT", "i2m": "NONE",
               "x": 0, "grp": 0, "whole": 0, "restart": 0, "detached": 0, "arm": "NONE",
               "apos": "ENTRY", "wb": 0}

STEP_OP = {"clocks": "CLOCKS", "nowait": "NOWAIT", "take": "TAKE", "data": "DATA",
           "post": "POST", "post_io": "POST_IO", "decide": "DECIDE", "halt": "HALT",
           "from_start": "FROM_START", "split_floor": "SPLIT_FLOOR"}
WAIT_STEP = {"wait": "OWN_DONE", "issued": "OWN_ISSUED", "slot": "SLOT", "wbsync": "WB",
             "quiet": "QUIET"}
ARM_STEPS = ("fetch_hold", "fetch_release", "flush_from", "held_clocks")
TAKE_TAG = {None: "NONE", "lead": "LEAD", "chain": "CHAIN", "word": "WORD",
            "chain_word": "CHAIN_WORD", "port": "PORT"}
CLOCK_TAG = {None: "NONE", "ea": "EA", "mexec": "MEXEC"}
RKIND = {"read": "READ", "write": "WRITE", "io_read": "IO_READ", "io_write": "IO_WRITE",
         "nowrite": "NOWRITE"}


def tdelay(op: str, tag: str) -> int:
    """1: the model returns after the row's action (the next row runs on a later clock: the
    clocks counted out, the take's next clock and sync); 0: the model goes on to the next step
    on the clock the row completes (a satisfied wait, a post, a lead take, the last NOWAIT
    clock, a data step's done clock)."""
    if op in ("CLOCKS", "HALT"):
        return 1
    if op == "TAKE":
        return 0 if tag == "LEAD" else 1
    return 0


def pack_row(row: dict) -> int:
    word, off = 0, 0
    for name, bits in ROW_FIELDS:
        v = row[name]
        if name in ROW_ENUMS:
            v = ROW_ENUMS[name].index(v)
        if not 0 <= v < (1 << bits):
            raise UcgenError(f"row field {name}={row[name]!r} does not fit {bits} bits: {row}")
        word |= v << off
        off += bits
    return word


def unpack_row(word: int) -> dict:
    row, off = {}, 0
    for name, bits in ROW_FIELDS:
        v = (word >> off) & ((1 << bits) - 1)
        row[name] = ROW_ENUMS[name][v] if name in ROW_ENUMS else v
        off += bits
    return row


def freeze(row: dict) -> tuple:
    return tuple(row[n] for n, _ in ROW_FIELDS)


def thaw(t: tuple) -> dict:
    return dict(zip((n for n, _ in ROW_FIELDS), t))


# --------------------------------------------------------------------------------------------
# The fit and the model
# --------------------------------------------------------------------------------------------

def _model():
    from .sim import templates as T
    from .sim import eu as E
    from .sim import queue as Q
    return T, E, Q


@lru_cache(maxsize=1)
def load_fit():
    """(Config.fitted(), md5 of fit.json)."""
    from .sim.config import FIT_PATH, Config
    return Config.fitted(), hashlib.md5(Path(FIT_PATH).read_bytes()).hexdigest()


class Regs(dict):
    """The register file the enumeration decodes with: a memory word or return address the
    chain did not store reads as a pointer into PS (the decoder would refuse the transfer)."""

    def get(self, k, d=None):
        if k.startswith("mem"):
            return 0x1000           # a far pointer's segment word must be PS (templates.CODE_SEG)
        if k.startswith("ret"):
            return 0x0010
        return super().get(k, d)


# concrete register presets (the inverse check's) and the sentinels the symbolic forms use
REAL = dict(AW=0x0005, DW=0x00E0, BW=0x0100, SP=0x0800, BP=0x0400, IX=0x0200, IY=0x0300)
SENT = dict(AW=0x0005, DW=0xD000, BW=0x0100, SP=0xB000, BP=0x5000, IX=0x1000, IY=0x3000)
S_EA, S_PORT, S_VEC, S_TARGET = 0xA000, 0xC000, 0x7000, 0xE000
BF_SENT = 4000
# flag / CW states the enumeration decodes under: both outcomes of every transfer
FLAG_STATES = ((0, 3), (1, 3), (0, 1), (0, 0))


def regs_for(z: int, cw: int, base=REAL, flags=None) -> Regs:
    r = Regs(base)
    r["CW"] = cw
    f = flags if flags is not None else {"Z": z, "CY": z, "S": z, "V": 0, "P": z}
    r.update(f)
    return r


def _code(b0: int, b1: int, b2) -> bytes:
    return bytes([b0, b1] + ([b2] if b2 is not None else []) + [0x02, 0x00, 0x00, 0x00, 0x00, 0x00])


def _flag_sets():
    out = []
    for m in range(32):
        out.append({"Z": m & 1, "CY": m >> 1 & 1, "S": m >> 2 & 1, "V": m >> 3 & 1,
                    "P": m >> 4 & 1})
    return out


@dataclasses.dataclass
class Form:
    """One decode: the bytes, its page / ModR/M position, the started Op (concrete registers)
    and the register file it was decoded under."""
    code: bytes
    page: int               # 0 native, 1 the 0F page, 2 a REP prefix + string opcode
    opcode: int             # the byte the decode table is indexed by
    modrm: int | None       # the ModR/M byte (None: the form has none)
    op: object
    regs: dict


def enumerate_forms(cfg) -> list:
    """Every distinct Op the live decoder makes of opcode x second byte (x third byte on the 0F
    page), with fixed trailing bytes, under the flag / CW states that give every transfer both
    outcomes. Deterministic order."""
    T, _, _ = _model()
    seen = {}
    flagsets = _flag_sets()
    for b0 in range(256):
        for b1 in range(256):
            for b2 in (range(256) if b0 == 0x0F else (None,)):
                code = _code(b0, b1, b2)
                states = [(z, cw, None) for z, cw in FLAG_STATES]
                if 0x70 <= b0 <= 0x7F or 0xE0 <= b0 <= 0xE3:
                    states += [(0, cw, f) for f in flagsets for cw in (1, 3)]
                for z, cw, f in states:
                    rg = regs_for(z, cw, flags=f)
                    try:
                        op = T.decode(code, 0, rg)
                    except (ValueError, KeyError, IndexError):
                        continue
                    key = (code[:op.length], op.cls, op.target is not None, op.zfail)
                    if key in seen:
                        continue
                    page = 1 if b0 == 0x0F else 2 if op.rep is not None else 0
                    opcode = b1 if page else b0
                    has_m = op.length > (1 + (1 if page else 0)) and _has_modrm_at(b0, page)
                    modrm = (b2 if page == 1 else b1) if has_m else None
                    seen[key] = Form(code[:op.length], page, opcode, modrm, op, dict(rg))
            if b0 not in _SECOND_BYTE_READ:
                break
    return list(seen.values())


@lru_cache(maxsize=None)
def _modrm_opcodes() -> tuple:
    """(native, ext): the opcodes whose length the ModR/M byte's mod / rm fields move (the
    decoder reads a ModR/M byte), found by decoding."""
    T, _, _ = _model()
    out = []
    for page in (0, 1):
        s = set()
        for o in range(256):
            for reg in range(8):
                lens = set()
                for mod in (0, 1, 2, 3):
                    m = mod << 6 | reg << 3 | (6 if mod == 0 else 0)
                    code = _code(0x0F, o, m) if page else _code(o, m, None)
                    for z, cw in FLAG_STATES:
                        try:
                            op = T.decode(code, 0, regs_for(z, cw))
                        except (ValueError, KeyError, IndexError):
                            continue
                        if op.rep is None:
                            lens.add((mod, op.length))
                d = dict(lens)
                if len(d) >= 2 and len(set(d.values())) >= 2:
                    s.add(o)
        out.append(frozenset(s))
    return tuple(out)


def _has_modrm_at(b0: int, page: int) -> bool:
    """Whether a form longer than its opcode byte(s) has a ModR/M byte: every 0F form but the BCD
    strings (two bytes: the caller's length test), no REP form, the native opcodes whose length
    the ModR/M byte moves."""
    if page == 1:
        return True
    if page == 2:
        return False
    return b0 in _modrm_opcodes()[0]


# opcodes whose decode reads the second byte (speed-up only: the others decode once)
_SECOND_BYTE_READ = frozenset(range(256)) - frozenset(
    (0x06, 0x07, 0x0E, 0x16, 0x17, 0x1E, 0x1F, 0x26, 0x2E, 0x36, 0x3E, 0x50, 0x51, 0x52, 0x53,
     0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5A, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F, 0x60, 0x61, 0x90,
     0x91, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x9C, 0x9D, 0x9E, 0x9F, 0xC3, 0xC9, 0xCC, 0xCF,
     0xD7, 0xEC, 0xED, 0xEE, 0xEF, 0xF4, 0xF5, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0x98, 0x99,
     0x27, 0x2F, 0x37, 0x3F, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4A,
     0x4B, 0x4C, 0x4D, 0x4E, 0x4F, 0xF0))


def started(op, cfg):
    """The Op as eu._start builds its template from it (eu.py:217-232): the CL mask, CMP r/m,reg
    (dest_route=slot) not writing, a non-writing form run as its group's RMW class (grp_class),
    a memory shift by an immediate count run as rmw_imm (shift_mem_imm)."""
    T, _, _ = _model()
    op = dataclasses.replace(op)
    if op.cl_count and cfg.shift_count_mask == "cl5":
        op.count &= 0x1F
    if cfg.dest_route == "slot" and op.dbit == 0 and op.cls == "load_alu" and op.ea is not None:
        op.nowrite = True
    if op.nowrite:
        op.cls = T.grp_class(op, cfg)
    if op.count_byte and op.cls == "rmw" and cfg.shift_mem_imm == "rmw_imm":
        op.cls, op.imm_bytes = "rmw_imm", 1
    return op


def lead_steps(op, cfg) -> list:
    """The steps eu._start puts before the template (eu.py:475-479): wbsync when the class's
    wbsync (wbsync0 for a form without operand bytes) is set; nothing else under
    opcode_take=prefetch."""
    name = "wbsync0" if op.length == 1 and "wbsync0" in cfg.cost.get(op.cls, {}) else "wbsync"
    if cfg.opcode_take != "prefetch":
        raise UcgenError("opcode_take=start is not built")
    return [("wbsync",)] if cfg.c(op.cls, name) else []


def model_steps(op, cfg, held_at=None) -> list:
    """The step list the EU runs for the started op: lead_steps + templates.steps. held_at
    (port_latch=relatch, eu.py:1895-1901): the step list after the EU inserted ("slot",) and
    the re-latched post behind the port take (a detached I/O held in the slot at the take)."""
    T, _, _ = _model()
    seq = lead_steps(op, cfg) + T.steps(op, cfg)
    if held_at:
        out = []
        for st in seq:
            out.append(st)
            if st[0] == "take" and len(st) > 2 and st[2] == "port" and cfg.port_latch == "relatch":
                req, detached = st[3], st[4]
                out += [("slot",), ("post_io" if detached else "post", *req)]
        seq = out
    return seq


def _trim_request(st: tuple) -> tuple:
    """A request step without its trailing default arguments (eu._post: free=None, grp=False,
    whole=False, restart=False): the same request."""
    if st[0] not in ("data", "post", "post_io"):
        return st
    st = list(st)
    while len(st) > 5 and (st[-1] is None or st[-1] is False):
        st.pop()
    return tuple(st)


def canonical(seq) -> list:
    """The canonical form of a step list: ("take", 0) and every ("clocks", 0[, tag]) removed
    (eu.tick passes both without a clock: k + 1, continue, nothing set), and a request step's
    trailing default arguments dropped (_trim_request)."""
    return [_trim_request(tuple(s)) for s in seq
            if not (s[0] == "take" and s[1] == 0) and not (s[0] == "clocks" and s[1] == 0)]


# --------------------------------------------------------------------------------------------
# Run parameters: what a form's step list depends on beyond its format
# --------------------------------------------------------------------------------------------

def is_loop(op) -> bool:
    T, _, _ = _model()
    return (op.cls in T.STRING_CLASSES and op.rep is not None) or op.cls in T.BCD_CLASSES


def has_count(op) -> bool:
    return op.cls in ("shift_imm", "shift_cl") or bool(op.shift)


def has_mneg(op) -> bool:
    return op.cls == "mul" and op.signed


def has_bf(op) -> bool:
    return op.bf is not None


def with_run(op, **kw):
    """op with run values replaced: count, mneg, n, cond, half (half_word), bfcost, cross."""
    o = dataclasses.replace(op)
    if "count" in kw:
        o.count = kw["count"]
    if "mneg" in kw:
        o.mneg = kw["mneg"]
    if "n" in kw:
        o.n = kw["n"]
    if "cond" in kw:
        o.cond = kw["cond"]
    if "half" in kw:
        o.half_word = kw["half"]
    if o.bf is not None and ("bfcost" in kw or "cross" in kw):
        off, w, cross, cost = o.bf
        o.bf = (off, w, kw.get("cross", cross), kw.get("bfcost", cost))
    return o


def symbolic(op, sent_regs: dict):
    """op with its operands as sentinels: the EA, the port (the byte or DW), the vector, the
    target; the stack addresses and IX / IY come from the sentinel register file the form was
    decoded under (sent_regs)."""
    o = dataclasses.replace(op)
    if o.ea is not None:
        o.ea = S_EA
    if o.port is not None and o.port != sent_regs["DW"]:
        o.port = S_PORT
    if o.vec is not None:
        o.vec = S_VEC
    if o.target is not None:
        o.target = S_TARGET
    return o


def addr_source(v, loop: bool, w: int):
    """A sentinel address -> (asrc, aidx)."""
    if v is None:
        raise NotModelled("a request without an address")
    if v == S_PORT:
        return "PORT_IMM", 0
    if v == SENT["DW"]:
        return "PORT_DW", 0
    for name, base, sign in (("EA", S_EA, 1), ("SPR", SENT["SP"], 1),
                             ("SPW", (SENT["SP"] - 2) & 0xFFFF, -1), ("BP", SENT["BP"], 1),
                             ("VEC", S_VEC, 1)):
        d = ((v - base) * sign) & 0xFFFF
        if d < 16 and not d % 2:
            return name, d // 2
    for name, base in (("IX", SENT["IX"]), ("IY", SENT["IY"])):
        d = (v - base) & 0xFFFF
        if d < 0x100:
            if loop:
                return "STR_" + name, d     # the element offset (index x width), checked below
            if not d % 2 and d < 16:
                return name, d // 2
    raise UcgenError(f"address {v:#x} is not a symbolic source")


def _sent_form(form: Form, cfg):
    """The form decoded under the sentinel registers (stack, IX / IY, DW), then started and
    made symbolic."""
    T, _, _ = _model()
    rg = Regs(form.regs)
    rg.update({k: v for k, v in SENT.items() if k != "AW"})
    op = started(T.decode(form.code + bytes(8), 0, rg), cfg)
    if op.cls != started(form.op, cfg).cls or op.length != form.op.length:
        raise UcgenError(f"{form.code.hex(' ')}: the sentinel decode is another form")
    return symbolic(op, rg)


# --------------------------------------------------------------------------------------------
# Step lists -> abstract steps (symbolic integers) -> rows
# --------------------------------------------------------------------------------------------

def _int_slots(st: tuple) -> list:
    """Indices of the integer-valued elements of a step tuple."""
    k = st[0]
    if k in ("clocks", "nowait", "split_floor", "flush_from", "held_clocks"):
        return [1]
    if k == "take":
        return [1] + ([3] if len(st) > 3 else [])      # 3: the port request (setup inside)
    if k in ("data", "post", "post_io"):
        return [i for i in (4, 5) if i < len(st) and isinstance(st[i], int)
                and not isinstance(st[i], bool)]
    if k == "fetch_hold":
        return [1]
    if k == "fetch_release":
        return [1] if st[1] is not None else []
    if k == "from_start":
        return [1, 2]
    return []


def _get(st, i):
    if st[0] == "take" and i == 3:
        return st[3][3]
    return st[i]


def _shape(st):
    """The step without its integers (two step lists of one shape differ only in integers)."""
    out = []
    for i, v in enumerate(st):
        if i in _int_slots(st):
            out.append("#")
        elif st[0] == "take" and i == 3:
            out.append(("#req", v[0], v[1], v[2]))
        else:
            out.append(v)
    return tuple(out)


class Sym:
    """A symbolic integer: value = base + coefficient x source (nsrc)."""
    __slots__ = ("src", "base")

    def __init__(self, src: str, base: int):
        self.src, self.base = src, base

    def __eq__(self, o):
        return isinstance(o, Sym) and (self.src, self.base) == (o.src, o.base)

    def __hash__(self):
        return hash((self.src, self.base))

    def __repr__(self):
        return f"{self.src}+{self.base}"


def _variants(op, cfg, ea_mode, ctx: dict) -> dict:
    """The perturbed step lists the symbolic integers are read from."""
    T, _, _ = _model()
    out = {"base": model_steps(with_run(op, **ctx), cfg)}
    if ea_mode is not None:
        c2 = dataclasses.replace(cfg, ea={**cfg.ea, ea_mode: cfg.ea.get(ea_mode, 0) + 64})
        out["EA"] = model_steps(with_run(op, **ctx), c2)
    if "count" in ctx:
        out["CNT1"] = model_steps(with_run(op, **{**ctx, "count": ctx["count"] + 1}), cfg)
        out["CNT2"] = model_steps(with_run(op, **{**ctx, "count": ctx["count"] + 2}), cfg)
    if "mneg" in ctx:
        out["UNIT"] = model_steps(with_run(op, **{**ctx, "mneg": ctx["mneg"] + 16}), cfg)
    if "bfcost" in ctx:
        out["BF"] = model_steps(with_run(op, **{**ctx, "bfcost": ctx["bfcost"] + 1000}), cfg)
    return out


def abstract_list(op, cfg, ea_mode, ctx: dict) -> list:
    """The form's step list with symbolic integers (Sym where a perturbation moves them), in
    canonical form (literal-zero clocks and zero takes dropped)."""
    var = _variants(op, cfg, ea_mode, ctx)
    base = var["base"]
    for name, seq in var.items():
        if len(seq) != len(base) or any(_shape(a) != _shape(b) for a, b in zip(seq, base)):
            raise UcgenError(f"{op.cls}: the step list changes shape with {name}")
    psc = cfg.per_shift_count
    out = []
    for j, st in enumerate(base):
        st = list(st)
        if st[0] == "take" and len(st) > 3:
            st[3] = list(st[3])
        for i in _int_slots(base[j]):
            v0 = _get(base[j], i)
            moved = {n: _get(var[n][j], i) - v0 for n in var if n != "base"}
            srcs = []
            if moved.get("EA"):
                if moved["EA"] != 64:
                    raise UcgenError(f"{op.cls}: step {base[j]} moves {moved['EA']} with the EA")
                srcs.append(("EA", v0 - cfg.ea.get(ea_mode, 0)))
            if moved.get("CNT1") or moved.get("CNT2"):
                if moved["CNT1"] != psc or moved["CNT2"] != 2 * psc:
                    raise UcgenError(f"{op.cls}: step {base[j]} is not per_shift_count x count")
                srcs.append(("CNT", v0 - psc * ctx["count"]))
            if moved.get("UNIT"):
                if moved["UNIT"] != 16:
                    raise UcgenError(f"{op.cls}: step {base[j]} moves {moved['UNIT']} with mneg")
                srcs.append(("UNIT", v0 - ctx["mneg"]))
            if moved.get("BF"):
                if moved["BF"] != 1000:
                    raise UcgenError(f"{op.cls}: step {base[j]} moves {moved['BF']} with the cost")
                srcs.append(("BF", ctx["bfcost"] - v0))
            if len(srcs) > 1:
                raise UcgenError(f"{op.cls}: step {base[j]} has two symbolic sources {srcs}")
            val = Sym(*srcs[0]) if srcs else v0
            if st[0] == "take" and i == 3:
                st[3][3] = val
            else:
                st[i] = val
        if st[0] == "take" and len(st) > 3:
            st[3] = tuple(st[3])
        st = tuple(st)
        if st[0] == "take" and st[1] == 0:
            continue
        if st[0] == "clocks" and st[1] == 0:
            continue                    # a literal zero (a symbolic one is a Sym)
        out.append(st)
    # (S4) a take that leaves the take sync pending (no chain / lead / port tag) followed only by
    # zero-time steps: eu.tick checks the sync before every step, so the trailing no-op step
    # holds the form's end (and so the next start) until the sync is met, where a take that is
    # the last step ends the form at once. A NOP row stands for that step (canonical: nothing).
    real = [k for k, st in enumerate(base)
            if not (st[0] in ("clocks", "take") and isinstance(st[1], int) and st[1] == 0)]
    if (real and real[-1] < len(base) - 1 and base[real[-1]][0] == "take"
            and (len(base[real[-1]]) < 3 or base[real[-1]][2] == "word")):
        out.append(("nop",))
    return out


def _nsrc(v):
    if isinstance(v, Sym):
        return v.src, v.base
    return "LIT", v


def _width_sel(width: int, fmt_w: int) -> str:
    return "FMT" if width == fmt_w else ("BYTE" if width == 1 else "WORD")


def _req_fields(row: dict, kind, addr, width, fmt_w, loop):
    row["rkind"] = RKIND[kind]
    src, idx = addr_source(addr, loop, width)
    if src.startswith("STR_"):
        if idx % width:
            raise UcgenError(f"element address offset {idx} is not a multiple of {width}")
        row["elem"] = idx // width      # the element index (checked by the loop builder)
        idx = 0
    row["asrc"], row["aidx"] = src, idx
    row["wsel"] = _width_sel(width, fmt_w)


def step_row(st: tuple, fmt_w: int, loop: bool) -> dict:
    """One timed abstract step -> its row (the fold fields left empty)."""
    k = st[0]
    row = dict(ROW_DEFAULT)
    row["op"] = STEP_OP.get(k)
    if k in ("clocks", "nowait"):
        row["nsrc"], row["imm"] = _nsrc(st[1])
        if k == "clocks" and len(st) > 2:
            row["tag"] = CLOCK_TAG[st[2]]
        elif len(st) > 2:
            raise UcgenError(f"step {st}")
    elif k == "take":
        if isinstance(st[1], Sym) or st[1] > 7:
            raise UcgenError(f"take {st}")
        row["aidx"] = st[1]
        row["tag"] = TAKE_TAG[st[2] if len(st) > 2 else None]
        if row["tag"] == "PORT":
            kind, port, width, setup = st[3]
            # aidx is the take's byte count here; the port request has no word index
            r2 = {}
            _req_fields(r2, kind, port, width, fmt_w, loop)
            row["rkind"], row["asrc"], row["wsel"] = r2["rkind"], r2["asrc"], r2["wsel"]
            row["nsrc"], row["imm"] = _nsrc(setup)
            row["detached"] = int(bool(st[4]))
    elif k in ("data", "post", "post_io"):
        kind, addr, width, setup = st[1:5]
        _req_fields(row, kind, addr, width, fmt_w, loop)
        row["nsrc"], row["imm"] = _nsrc(setup)
        if len(st) > 5 and st[5] is not None:
            free = st[5]
            if isinstance(free, Sym):
                if not (isinstance(setup, Sym) and free.src == setup.src):
                    raise UcgenError(f"free {free} does not follow setup {setup}")
                row["i2m"], row["x"] = "SETUP_MINUS", setup.base - free.base
            else:
                row["i2m"], row["x"] = "LIT", free
        if len(st) > 6:
            row["grp"] = int(bool(st[6]))
        if len(st) > 7:
            row["whole"] = int(bool(st[7]))
        if len(st) > 8:
            row["restart"] = int(bool(st[8]))
        if len(st) > 9:
            raise UcgenError(f"step {st}")
        if k == "post_io":
            row["detached"] = 1
    elif k == "flush":
        row["op"] = "FLUSH_C" if len(st) > 2 and st[2] == "cfgap" else "FLUSH"
        if st[1] != S_TARGET or (len(st) > 2 and st[2] != "cfgap") or len(st) > 3:
            raise UcgenError(f"step {st}")
    elif k in ("decide", "halt"):
        if len(st) > 1:
            raise UcgenError(f"step {st}")
    elif k == "from_start":
        row["imm"], row["x"] = st[1], st[2]
        if isinstance(st[1], Sym) or isinstance(st[2], Sym):
            raise UcgenError(f"step {st}")
    elif k == "split_floor":
        row["nsrc"], row["imm"] = _nsrc(st[1])
    else:
        raise UcgenError(f"step {st} is not a timed step")
    row["tdelay"] = tdelay(row["op"], row["tag"])
    return row


def arm_of(st: tuple) -> tuple:
    """A side-effect step -> (arm, x)."""
    T, _, _ = _model()
    k = st[0]
    if k == "fetch_hold":
        n = st[1]
        if isinstance(n, Sym):
            raise UcgenError(f"{st}: a symbolic hold")
        if n == T.BF_TAKE_HOLD:
            if len(st) > 2 and st[2] == "dlv":
                return "HOLD_TAKE_DLV", 0
            if len(st) > 2:
                raise UcgenError(f"step {st}")
            return "HOLD_TAKE", 0
        if n == T.BCD_HOLD and len(st) == 2:
            return "HOLD_LONG", 0
        if len(st) > 2 and st[2] == "room":
            return "HOLD_ROOM", n
        if len(st) > 2:
            raise UcgenError(f"step {st}")
        return "HOLD", n
    if k == "fetch_release":
        if st[1] is None and len(st) == 2:
            return "REL_FOREVER", 0
        if len(st) > 2 and st[2] == "raise":
            return "REL_RAISE", st[1]
        if len(st) > 2:
            raise UcgenError(f"step {st}")
        return "REL", st[1]
    if k == "flush_from":
        return "FLUSH_FROM", st[1]
    if k == "held_clocks":
        return "HELD", st[1]
    raise UcgenError(f"step {st} is not a side effect")


def _uses_x(row: dict) -> bool:
    return row["i2m"] != "NONE" or row["op"] == "FROM_START"


def _x_ok(row: dict, item) -> bool:
    return not (item[0] == "A" and item[1] in ARMS_X and _uses_x(row))


def _try_attach(row: dict, items: list) -> bool:
    """Fold the zero-time items (("W", wait) / ("A", arm, x)) into row, in place: one wait and
    one arm, the arm before the wait (ENTRY) or after it (PRE_OP)."""
    kinds = "".join(i[0] for i in items)
    if kinds not in ("", "A", "W", "AW", "WA") or not all(_x_ok(row, i) for i in items):
        return False
    for it in items:
        if it[0] == "W":
            row["wcond"] = it[1]
        else:
            row["arm"], row["apos"] = it[1], ("PRE_OP" if kinds == "WA" else "ENTRY")
            if it[1] in ARMS_X:
                row["x"] = it[2]
    return True


def _nop_row() -> dict:
    return dict(ROW_DEFAULT)


def fold(seq: list, fmt_w: int, strl: bool) -> list:
    """Abstract steps -> rows. Each timed step is a row; the zero-time items before it fold into
    it (a wait, an arm before or after the wait); items it cannot hold go, in order, onto the
    previous row's EXIT arm (an arm, first in line) or onto NOP rows. Items after the last
    timed step: the last row's EXIT arm, or NOP rows."""
    rows, pend = [], []

    def put(items):
        k = 0
        while k < len(items):
            it = items[k]
            if (it[0] == "A" and rows and rows[-1]["arm"] == "NONE" and _x_ok(rows[-1], it)):
                rows[-1]["arm"], rows[-1]["apos"] = it[1], "EXIT"
                if it[1] in ARMS_X:
                    rows[-1]["x"] = it[2]
                k += 1
                continue
            nop = _nop_row()
            two = items[k:k + 2]
            if len(two) == 2 and _try_attach(dict(nop), two):
                _try_attach(nop, two)
                k += 2
            else:
                if not _try_attach(nop, [it]):
                    raise UcgenError(f"cannot fold {it}")
                k += 1
            rows.append(nop)

    for st in seq:
        k = st[0]
        if k in WAIT_STEP:
            if len(st) > 1:
                raise UcgenError(f"step {st}")
            pend.append(("W", WAIT_STEP[k]))
        elif k in ARM_STEPS:
            pend.append(("A",) + arm_of(st))
        elif k == "sent":
            raise UcgenError("burst_wait=issue's sent step is not built (unused under the fit)")
        elif k == "nop":
            # (S4) the sync-holding end of a take-ended form (abstract_list): a NOP row
            put(pend)
            pend = []
            rows.append(_nop_row())
        else:
            row = step_row(st, fmt_w, strl)
            for cut in (2, 1, 0):
                if cut > len(pend):
                    continue
                trial = dict(row)
                if _try_attach(trial, pend[len(pend) - cut:]):
                    put(pend[:len(pend) - cut])
                    row = trial
                    break
            rows.append(row)
            pend = []
    put(pend)
    return rows


# --------------------------------------------------------------------------------------------
# Expansion (the inverse of fold): rows -> step tuples, given the run context
# --------------------------------------------------------------------------------------------

RKIND_STEP = {v: k for k, v in RKIND.items()}
TAKE_TAG_STEP = {v: k for k, v in TAKE_TAG.items()}
CLOCK_TAG_STEP = {v: k for k, v in CLOCK_TAG.items()}
WAIT_OF = {v: k for k, v in WAIT_STEP.items()}


def _value(nsrc: str, imm: int, ctx: dict, elem: int) -> int:
    if nsrc == "LIT":
        return imm
    if nsrc == "EA":
        return imm + ctx["eaclk"]
    if nsrc == "CNT":
        return imm + ctx["psc"] * ctx["count"]
    if nsrc == "UNIT":
        return imm + ctx["mneg"]
    if nsrc == "BF":
        return max(0, ctx["bfcost"] - imm)
    if nsrc == "STR":
        k = ctx["const"]
        return imm + (k["first"] if elem == 0 else k["loop1"] if elem == 1 else k["loop"])
    raise UcgenError(nsrc)


def _addr(row: dict, ctx: dict, elem: int, width: int):
    a, i = row["asrc"], row["aidx"]
    if a == "EA":
        return (ctx["ea"] + 2 * i) & 0xFFFF
    if a == "SPW":
        return (ctx["sp"] - 2 - 2 * i) & 0xFFFF
    if a == "SPR":
        return (ctx["sp"] + 2 * i) & 0xFFFF
    if a == "BP":
        return (ctx["bp"] + 2 * i) & 0xFFFF
    if a == "VEC":
        return (ctx["vec"] + 2 * i) & 0xFFFF
    if a == "PORT_IMM":
        return ctx["port_imm"]
    if a == "PORT_DW":
        return ctx["dw"]
    if a in ("IX", "IY"):
        return (ctx[a.lower()] + 2 * i) & 0xFFFF
    if a in ("STR_IX", "STR_IY"):
        return (ctx[a[4:].lower()] + elem * width) & 0xFFFF
    raise UcgenError(f"asrc {a}")


def _width(row: dict, ctx: dict) -> int:
    return {"FMT": ctx["w"], "BYTE": 1, "WORD": 2}[row["wsel"]]


def _arm_step(row: dict) -> tuple:
    T, _, _ = _model()
    a, x = row["arm"], row["x"]
    return {"HOLD": ("fetch_hold", x), "HOLD_ROOM": ("fetch_hold", x, "room"),
            "HOLD_TAKE": ("fetch_hold", T.BF_TAKE_HOLD),
            "HOLD_TAKE_DLV": ("fetch_hold", T.BF_TAKE_HOLD, "dlv"),
            "HOLD_LONG": ("fetch_hold", T.BCD_HOLD), "REL": ("fetch_release", x),
            "REL_FOREVER": ("fetch_release", None), "REL_RAISE": ("fetch_release", x, "raise"),
            "FLUSH_FROM": ("flush_from", x), "HELD": ("held_clocks", x)}[a]


def _main_step(row: dict, ctx: dict, elem: int, final: bool):
    op = row["op"]
    if op == "NOP":
        return None
    if op in ("CLOCKS", "NOWAIT"):
        n = _value(row["nsrc"], row["imm"], ctx, elem)
        if op == "CLOCKS" and row["tag"] != "NONE":
            return ("clocks", n, CLOCK_TAG_STEP[row["tag"]])
        return ("clocks" if op == "CLOCKS" else "nowait", n)
    if op == "TAKE":
        tag = TAKE_TAG_STEP[row["tag"]]
        if tag == "port":
            w = _width(row, ctx)
            req = (RKIND_STEP[row["rkind"]], _addr(row, ctx, elem, w), w,
                   _value(row["nsrc"], row["imm"], ctx, elem))
            return ("take", row["aidx"], "port", req, bool(row["detached"]))
        return ("take", row["aidx"]) if tag is None else ("take", row["aidx"], tag)
    if op in ("DATA", "POST", "POST_IO"):
        w = _width(row, ctx)
        setup = _value(row["nsrc"], row["imm"], ctx, elem)
        if row["lastadd"] and final and not ctx.get("cond"):
            setup += ctx["const"]["last"]
        free = (row["x"] if row["i2m"] == "LIT" else setup - row["x"]
                if row["i2m"] == "SETUP_MINUS" else None)
        st = ({"DATA": "data", "POST": "post", "POST_IO": "post_io"}[op],
              RKIND_STEP[row["rkind"]], _addr(row, ctx, elem, w), w, setup, free,
              bool(row["grp"]), bool(row["whole"]), bool(row["restart"]))
        return _trim_request(st)
    if op in ("FLUSH", "FLUSH_C"):
        return ("flush", ctx["target"]) if op == "FLUSH" else ("flush", ctx["target"], "cfgap")
    if op == "DECIDE":
        return ("decide",)
    if op == "HALT":
        return ("halt",)
    if op == "FROM_START":
        return ("from_start", row["imm"], row["x"])
    if op == "SPLIT_FLOOR":
        return ("split_floor", _value(row["nsrc"], row["imm"], ctx, elem))
    raise UcgenError(op)


def _skipped(row: dict, ctx: dict) -> bool:
    s = row["skip"]
    return bool(s == "COND" and ctx.get("cond") or s == "NCOND" and not ctx.get("cond")
                or s == "NOHELD" and not ctx.get("held") or s == "CROSS" and ctx.get("cross")
                or s == "NCROSS" and not ctx.get("cross"))


def expand(rows: list, ctx: dict) -> list:
    """The step list a template's rows stand for under ctx (the run's values: ea, sp, bp, ix,
    iy, port_imm, dw, vec, target, count, mneg, bfcost, n, cond, cross, held, w, eaclk, psc,
    const). A row is [ENTRY arm] [wait] [PRE_OP arm] [its step] [EXIT arm]; a skipped row is
    nothing. The element loop: elem counts the body's runs (HOLD_LONG on element 0 only, a
    `lastadd` row's +last on the final element); the body ends at its `loop` row and runs again
    from its `ltop` row while elem < n. The template ends after a `last` row."""
    out, i, elem, top = [], 0, 0, None
    n = ctx.get("n", 1)
    while i < len(rows):
        row = rows[i]
        if row["ltop"]:
            top = i
        if _skipped(row, ctx):
            i += 1
            continue
        pre, mid, post = [], [], []
        if row["arm"] != "NONE" and not (row["arm"] == "HOLD_LONG" and elem != 0):
            {"ENTRY": pre, "PRE_OP": mid, "EXIT": post}[row["apos"]].append(_arm_step(row))
        wait = [(WAIT_OF[row["wcond"]],)] if row["wcond"] != "NONE" else []
        st = _main_step(row, ctx, elem, elem == n - 1)
        out += pre + wait + mid + ([st] if st is not None else []) + post
        if row["loop"]:
            elem += 1
            if elem < n:
                i = top
                continue
        if row["last"]:
            break
        i += 1
    return out


# --------------------------------------------------------------------------------------------
# Templates of one form
# --------------------------------------------------------------------------------------------

def merge_skip(a: list, b: list, skip_a: str, skip_b: str) -> list:
    """Two row lists as one: the rows common to both (a longest common subsequence) kept, a's own
    rows skipped under skip_a, b's own under skip_b (a's before b's in each gap)."""
    fa, fb = [freeze(r) for r in a], [freeze(r) for r in b]
    n, m = len(fa), len(fb)
    L = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            L[i][j] = L[i + 1][j + 1] + 1 if fa[i] == fb[j] else max(L[i + 1][j], L[i][j + 1])
    out, i, j = [], 0, 0
    while i < n or j < m:
        if i < n and j < m and fa[i] == fb[j]:
            out.append(dict(a[i]))
            i, j = i + 1, j + 1
        elif i < n and (j >= m or L[i + 1][j] >= L[i][j + 1]):
            out.append({**a[i], "skip": skip_a})
            i += 1
        else:
            out.append({**b[j], "skip": skip_b})
            j += 1
    return out


def _finish(rows: list, wb: int) -> list:
    """The template's end: `last` on the final row and on a skipped alternative final row
    before it; the write-back clocks owed (wb) on every last row."""
    rows = [{k: r[k] for k, _ in ROW_FIELDS} for r in rows] or [_nop_row()]
    for r in rows:
        r["last"], r["wb"] = 0, 0
    rows[-1]["last"] = 1
    other = {"COND": "NCOND", "NCOND": "COND", "CROSS": "NCROSS", "NCROSS": "CROSS"}
    if len(rows) > 1 and rows[-1]["skip"] in other and rows[-2]["skip"] == other[rows[-1]["skip"]]:
        rows[-2]["last"] = 1
    for r in rows:
        if r["last"]:
            r["wb"] = wb
    return rows


def wb_of(op, cfg, n_pos: bool) -> int:
    """The write-back clocks the form owes its successor (eu._start 322-359): mwb for a memory
    form of a class with one, rwb for INC / DEC r8, uwb for an unprefixed string form
    (str_single_wb), xwb for a REP string that ran an element (str_exit=wb), else wb.
    lea_wb=fetch's fwb and page_fl_end's flwb are added at run time (class table)."""
    T, _, _ = _model()
    c = cfg.cost.get(op.cls, {})
    wb = cfg.c(op.cls, "mwb" if op.ea is not None and "mwb" in c else "wb")
    if op.cls == "incdec" and op.length > 1 and "rwb" in c:
        wb = cfg.c(op.cls, "rwb")
    if cfg.str_single_wb in ("wb", "index") and op.cls in T.STRING_CLASSES and op.rep is None:
        wb = cfg.c(op.cls, "uwb")
    if cfg.str_exit == "wb" and op.cls in T.STRING_CLASSES and op.rep is not None and n_pos:
        wb = cfg.c(op.cls, "xwb")
    return wb


def class_consts(cfg, cls: str) -> dict:
    """The class integers the STR source and the +last read (class table columns)."""
    c = cfg.cost.get(cls, {})
    return {"first": cfg.c(cls, "first"), "loop": cfg.c(cls, "loop"),
            "loop1": cfg.c(cls, "loop1") if "loop1" in c else cfg.c(cls, "loop"),
            "last": cfg.c(cls, "last")}


def strlike(op) -> bool:
    T, _, _ = _model()
    return op.cls in T.STRING_CLASSES or op.cls in T.BCD_CLASSES


def _elem(st):
    """The element index of a string / BCD request step (its STR address), else None."""
    if st[0] not in ("data", "post"):
        return None
    try:
        src, off = addr_source(st[2], True, st[3])
    except UcgenError:
        return None
    return off // st[3] if src.startswith("STR_") else None


def _norm_elem(E: list, e: int, k: dict) -> list:
    """An element's steps at element 0's addresses, its first request's setup as STR (less the
    STR value of element e)."""
    strv = k["first"] if e == 0 else k["loop1"] if e == 1 else k["loop"]
    out, first = [], True
    for st in E:
        if st[0] in ("data", "post") and _elem(st) is not None:
            src, off = addr_source(st[2], True, st[3])
            st = st[:2] + ((st[2] - off) & 0xFFFF,) + st[3:]
        if st[0] in ("data", "post") and first:
            st = st[:4] + (Sym("STR", st[4] - strv),) + st[5:]
            first = False
        out.append(st)
    return out


def _minus(st, v):
    s = st[4]
    return st[:4] + ((s - v) if isinstance(s, int) else Sym(s.src, s.base - v),) + st[5:]


def loop_template(op, cfg, ea_mode, fmt_w) -> list:
    """The rows of a loop form (a REP string that runs elements, a BCD string's byte pairs):
    the list for n = 4 cut into head, elements 0 .. 3 and tail; one element body (its first
    request's setup from STR, its last request +last on the final element) run n times, element
    0's own side effects (HOLD_LONG) folded into it; a compare's exit as skipped rows."""
    T, _, _ = _model()
    cyc = T.STRING_STEPS.get(op.cls) or (("read", "ix"), ("read", "iy"), ("write", "iy"))
    lead_cycles = next(i for i, (_, p) in enumerate(cyc) if p in ("ix", "iy"))
    k = class_consts(cfg, op.cls)

    def lst(n, cond=False):
        return abstract_list(with_run(op, n=n, cond=cond), cfg, ea_mode, {})

    L = lst(4)
    req = [j for j, st in enumerate(L) if st[0] in ("data", "post")]
    first = {}
    for j in req:
        e = _elem(L[j])
        if e is not None:
            first.setdefault(e, j)
    s = [req[req.index(first[e]) - lead_cycles] for e in range(4)]
    m = s[3] - s[2]
    if s[2] - s[1] != m or m < 1:
        raise UcgenError(f"{op.cls}: the elements are not of one length")
    head, E0, E2, E3, tail = L[:s[0]], L[s[0]:s[1]], L[s[2]:s[3]], L[s[3]:s[3] + m], L[s[3] + m:]
    body = _norm_elem(E2, 2, k)
    e3 = _norm_elem(E3, 3, k)
    lastj = max(j for j, st in enumerate(e3) if st[0] in ("data", "post"))
    e3[lastj] = _minus(e3[lastj], k["last"])
    if e3 != body:
        raise UcgenError(f"{op.cls}: the final element is not the body + last")
    e0 = _norm_elem(E0, 0, k)
    rest = [st for st in e0 if not (st[0] == "fetch_hold" and st[1] == T.BCD_HOLD)]
    if rest != body:
        raise UcgenError(f"{op.cls}: element 0 is not the body + HOLD_LONG")
    head_rows = fold(head, fmt_w, True)
    body_rows = fold(e0, fmt_w, True)
    lastr = max(j for j, r in enumerate(body_rows) if r["op"] in ("DATA", "POST"))
    body_rows[lastr]["lastadd"] = 1
    body_rows[0]["ltop"] = 1
    body_rows[-1]["loop"] = 1

    def tail_rows_of(t):
        # the overrun's cycles (element n) at element 0's addresses, the first STR at loop(n)
        return fold(_norm_elem(t, 4, k), fmt_w, True)

    tail_rows = tail_rows_of(tail)
    if op.cls in T.STRING_COMPARES:
        Lc = lst(4, True)
        tail_rows = merge_skip(tail_rows, tail_rows_of(Lc[s[3] + m:]), "COND", "NCOND")
    for r in head_rows + body_rows + tail_rows:
        r.pop("elem", None)
    return head_rows + body_rows + tail_rows


RUN_FIELDS = (("taken", 1), ("zfail", 1), ("cnt0", 1), ("half", 1), ("n0", 1))


def ctx_of(op, cfg, ea_mode, regs: dict, **run) -> dict:
    """The expansion context of a started op under regs (and run values)."""
    o = with_run(op, **{k: v for k, v in run.items() if k != "held"})
    return {"ea": o.ea, "sp": regs["SP"], "bp": regs["BP"], "ix": o.ix, "iy": o.iy,
            "port_imm": o.port, "dw": regs["DW"], "vec": o.vec, "target": o.target,
            "count": o.count, "mneg": o.mneg, "bfcost": o.bf[3] if o.bf else 0,
            "n": o.n if is_loop(o) else 1, "cond": o.cond, "cross": bool(o.bf and o.bf[2]),
            "held": run.get("held", False), "w": o.width,
            "eaclk": cfg.ea.get(ea_mode, 0) if ea_mode else 0, "psc": cfg.per_shift_count,
            "const": class_consts(cfg, o.cls)}


def ea_mode_of(op, cfg) -> str | None:
    """The EA table entry a ModR/M memory form's EA clocks read (templates.ea_class); None for a
    form whose mode its opcode fixes (no ModR/M: its EA clocks resolve to a literal) or no EA."""
    T, _, _ = _model()
    if op.ea is None or not op.modrm:
        return None
    return T.ea_class(op, cfg)


def _port_rows(rows: list) -> list:
    """The relatch rows (port_latch=relatch, eu.py:1895-1901) after every port take: wait for the
    slot, post the re-latched request; skipped when no detached I/O was held at the take."""
    out = []
    for r in rows:
        out.append(r)
        if r["op"] == "TAKE" and r["tag"] == "PORT":
            rel = dict(ROW_DEFAULT)
            rel.update(op="POST_IO" if r["detached"] else "POST", wcond="SLOT", skip="NOHELD",
                       rkind=r["rkind"], asrc=r["asrc"], wsel=r["wsel"], nsrc=r["nsrc"],
                       imm=r["imm"], detached=r["detached"])
            rel["tdelay"] = tdelay(rel["op"], "NONE")
            out.append(rel)
    return out


def sym_templates(sop, cfg, ea_mode) -> list:
    """[(run dict, rows)] of a sentinel op: every start-time variant (half; cnt0 for a count
    form; n0 for a loop form)."""
    fmt_w, strl = sop.width, strlike(sop)
    port = cfg.port_latch == "relatch"

    def rows_of(o, ctx):
        r = fold(abstract_list(o, cfg, ea_mode, ctx), fmt_w, strl)
        return _port_rows(r) if port else r

    out = []
    for half in (0, 1):
        o = with_run(sop, half=bool(half))
        if is_loop(o):
            for n0 in (0, 1):
                rows = rows_of(with_run(o, n=0), {}) if n0 else loop_template(o, cfg, ea_mode,
                                                                                fmt_w)
                out.append(({"half": half, "n0": n0, "cnt0": 0},
                            _finish(rows, wb_of(o, cfg, not n0))))
            continue
        if has_bf(o):
            alt = [rows_of(with_run(o, cross=c), {"bfcost": BF_SENT}) for c in (False, True)]
            rows = merge_skip(alt[0], alt[1], "CROSS", "NCROSS")
            out.append(({"half": half, "n0": 0, "cnt0": 0}, _finish(rows, wb_of(o, cfg, True))))
            continue
        ctx = {"mneg": 0} if has_mneg(o) else {}
        if has_count(o):
            r1 = _finish(rows_of(o, {**ctx, "count": 1}), wb_of(o, cfg, True))
            z = with_run(o, count=0, **ctx)
            if canonical(expand(r1, ctx_of(z, cfg, ea_mode, SENT))) == canonical(
                    model_steps(z, cfg)):
                r0 = r1
            else:
                r0 = _finish(rows_of(z, ctx), wb_of(o, cfg, True))
            out.append(({"half": half, "n0": 0, "cnt0": 0}, r1))
            out.append(({"half": half, "n0": 0, "cnt0": 1}, r0))
            continue
        out.append(({"half": half, "n0": 0, "cnt0": 0},
                    _finish(rows_of(o, ctx), wb_of(o, cfg, True))))
    return out


# --------------------------------------------------------------------------------------------
# Classes, format attributes, the decode table
# --------------------------------------------------------------------------------------------

TRAP = "trap_nop"           # class 0: an opcode / form the model has no template for


def class_list(cfg) -> list:
    return [TRAP] + sorted(cfg.cost)


EA_MODES = ("none", "base", "base_index", "disp", "base_disp", "base_index_disp", "direct",
            "base_index_disp16")


def interlocked(bcls: str, mode: str, cfg) -> bool:
    """eu.EU._interlocked: bcls is a register-only class of io_interlock mode `mode`."""
    _, E, _ = _model()
    if mode == "none":
        return False
    if bcls in E.INTERLOCK[mode]:
        return True
    if bcls == "lea" and cfg.lea_form == "reg":
        return True
    if bcls in E.TRANSFER_CLASSES and cfg.branch_reg == "reg":
        return True
    return bcls == "div" and bool(cfg.reg_div)


def _port_kind(op) -> int:
    if op.port is None:
        return 0
    return 1 if op.cls in ("in", "out") and op.length > 1 else 2


# The structural format bits (what templates.steps reads of an Op besides its class), (name,
# bits, f(started op, cfg)). All are properties of the opcode (and ModR/M reg / mod), so the
# decode table holds them.
STRUCT_ATTRS = (
    ("sgn", 1, lambda o, c: o.signed),                  # F6 / F7 /5 /7, the signed MUL / DIV
    ("grp", 1, lambda o, c: o.group),                   # a group opcode (reg field the operation)
    ("fixed_alu", 1, lambda o, c: o.fixed_alu),         # TEST 84 / 85, F6 / F7 /0
    ("shift", 1, lambda o, c: o.shift),                 # a shift on memory
    ("cl_shift", 1, lambda o, c: o.shift and o.opcode in (0xD2, 0xD3)),  # ... by CL
    ("nowrite", 1, lambda o, c: o.nowrite),             # a group / CMP form that does not write
    ("swap", 1, lambda o, c: o.swap),                   # XCH r/m with memory
    ("dbit_v", 1, lambda o, c: o.dbit is not None),     # a direction bit exists ...
    ("dbit", 1, lambda o, c: bool(o.dbit)),             # ... and its value
    ("cond", 1, lambda o, c: o.cond),                   # a condition field (70-7F)
    ("count_byte", 1, lambda o, c: o.count_byte),       # a memory shift's count is a byte
    ("cl_count", 1, lambda o, c: o.cl_count),           # the count / bit index is CL
    ("modrm_op", 1, lambda o, c: o.modrm),              # the ModR/M byte is a ModR/M (not an operand)
    ("bus", 1, lambda o, c: o.bus),                     # the memory operand has a bus cycle
    ("port", 2, lambda o, c: _port_kind(o)),            # 1 port byte, 2 DW
    ("sreg", 2, lambda o, c: {None: 0, "load": 1, "store": 2}[o.sreg]),
)


def _decode_attrs():
    T, E, Q = _model()

    def b(o):
        return T.base_class(o.cls)

    def regonly(o, c):
        return o.ea is None or (not o.bus and c.lea_form == "reg")

    def mem(o, c):
        return o.ea is not None and not (not o.bus and c.lea_form == "reg")

    return (
        # the decode attributes of docs/v35s-core-v2.md, "Rule disposition" (d)
        ("interlock", 1, lambda o, c: interlocked(b(o), c.io_interlock, c)),
        ("regonly", 1, lambda o, c: interlocked(b(o), c.io_interlock, c) and regonly(o, c)),
        ("port_io", 1, lambda o, c: o.cls in ("in", "out") and o.length > 1),
        ("one_reg", 1, lambda o, c: o.length == 1 and interlocked(b(o), "reg_pfx", c)),
        ("long1", 1, lambda o, c: o.cls in E.LONG_CLASSES),
        ("unit_reg", 1, lambda o, c: o.ea is None and b(o) in ("shift_imm", "shift_cl", "mul",
                                                               "div")),
        ("unit_mem", 1, lambda o, c: o.ea is not None and (bool(o.shift) or b(o) in (
            "mul", "div", "push_mem"))),
        ("fixed_grp", 1, lambda o, c: c.grp_ops == "fixed" and o.fixed_alu and o.ea is not None),
        ("imm16_reg", 1, lambda o, c: o.cls == "imm" and o.imm_bytes == 2),
        ("modrm_pre", 1, lambda o, c: o.cls in Q.ROOM_IR_PRE_CLASSES.get(c.room_ir_pre, ())
         and o.length > 1),
        ("far_xfer", 1, lambda o, c: o.cls in Q.FAR_ROOM_CLASSES),
        ("xfer_mem", 1, lambda o, c: o.cls in E.XFER_MEM),
        ("imm1_mem", 1, lambda o, c: o.imm_bytes == 1 and mem(o, c)),
        ("grp_rmw", 1, lambda o, c: bool(o.group) and (b(o) == "rmw" or c.xfer_mem_disp == "grp"
                                                        and o.cls in E.XFER_MEM)),
        ("page_reg", 1, lambda o, c: bool(o.page) and o.ea is None
         and (b(o) == "reg" or o.cls in T.BF_CLASSES)),
        ("page_mem", 1, lambda o, c: bool(o.page) and o.ea is not None),
        ("test1m", 1, lambda o, c: o.cls == "bit1_test"),
        ("mul_imm", 1, lambda o, c: o.cls == "mul_imm"),
        ("lea", 1, lambda o, c: o.cls == "lea"),
        ("dbnz", 1, lambda o, c: b(o) == "dbnz"),
        ("dbnz_z", 1, lambda o, c: o.cls == "dbnz_z"),
        ("xfer", 1, lambda o, c: b(o) in E.TRANSFER_CLASSES),
        ("dw_count", 1, lambda o, c: (o.cls in T.STRING_CLASSES and c.str_count == "dw")
         or (o.cls == "push_r" and c.burst_count == "dw")
         or (o.cls in T.BF_CLASSES and c.bf_count == "dw")),
        ("strop", 1, lambda o, c: o.cls in T.STRING_CLASSES),
        ("bcd", 1, lambda o, c: o.cls in T.BCD_CLASSES),
        ("bf", 1, lambda o, c: o.cls in T.BF_CLASSES),
        ("ro", 1, lambda o, c: b(o) in ("load", "load_alu")),
        ("rmw", 1, lambda o, c: b(o) == "rmw"),
        # (S3) the register class (base class reg: io_take_nx, eu.py), the one-byte forms whose
        # start on an idle bus saves a clock (one_idle, machine.py: ONE_IDLE[cfg.one_idle])
        ("breg", 1, lambda o, c: b(o) == "reg"),
        ("idle1", 1, lambda o, c: c.one_idle != "none" and o.length == 1
         and o.cls in E.ONE_IDLE[c.one_idle]),
        # (S5a) the start-time decision of a transfer (v35_run_t.taken / zfail, the template a
        # start picks from the flags and CW, templates.decode): tsel 0 always taken (or no
        # transfer), 1 the condition field (cond_taken), 2 CW counted down (DBNZ: CW - 1 != 0),
        # 3 CW zero (BCWZ); zpol: DBNZE's Z test (Z set continues; DBNZNE: Z clear)
        ("tsel", 2, lambda o, c: 1 if o.cond else 2 if b(o) == "dbnz" else
         3 if o.cls == "bcwz" else 0),
        ("zpol", 1, lambda o, c: o.cls == "dbnz_z" and o.opcode == 0xE1),
        # xshort: a short transfer (base class branch_short or dbnz: xfer_odd, xfer_nt)
        ("xshort", 1, lambda o, c: b(o) in ("branch_short", "dbnz")),
        # rot4r: ROL4 / ROR4 on a register (rot4_exec=wait)
        ("rot4r", 1, lambda o, c: o.cls in ("rol4", "ror4")),
    )


# (S3) the datapath's decode attributes: what the form does to the registers (the function
# path, docs/v35s-core-v2.md "Function path"), so the RTL selects operands and operations from
# format bits and never compares opcode bytes. Derived from the encoding (the opcode and, for a
# group opcode, the ModR/M reg field): the same register-transfer meaning the model's
# templates.execute / written give the forms they time, completed for every register form.
#   xop  the operation (XOPS); aop its sub-operation: the ALU op (ADD OR ADC SBB AND SUB XOR
#        CMP), the shift / rotate (the group's reg field), the flag form, the adjust
#   opa  the destination (or first) operand, opb the source (or second): ROLES
#   wd   a word operation (0: byte registers AL..BH)
#   nwr  the result is not written (CMP, TEST: flags only)
#   sx   the immediate byte is sign-extended to a word (83, 6A, 6B)
#   stk  the form's requests address the stack (SP is its address register)
XOPS = ("NONE", "ALU", "MOV", "XCH", "SHIFT", "MUL", "DIV", "MULI", "INC", "DEC", "NOT", "NEG",
        "LDEA", "SRLD", "SRST", "PUSH", "POP", "PUSHF", "POPF", "PUSHR", "POPR", "CVTBW",
        "CVTWL", "FLAG", "ADJ", "CVTBD", "CVTDB", "LAHF", "SAHF", "IN", "OUT", "XLAT",
        # (S5a) the transfers, the strings, the stack frame, the far pointer loads:
        #   JMP / CALL  aop the target: XFER_REL (the next IP + the displacement), XFER_FAR (the
        #               operand's offset and segment), XFER_REG (the rm register), XFER_MEM (the
        #               pointer's offset word read at the EA), XFER_MEMFAR (and its segment word)
        #   LOOP        DBNZ / DBNZE / DBNZNE: CW counted down, then XFER_REL
        #   RET         aop RET_NEAR (the offset popped; RET imm16: SP raised by the immediate),
        #               RET_FAR (offset, segment), RET_INT (RETI: offset, segment, PSW)
        #   BRK         aop the vector type (0: the operand byte's, BRK imm8)
        #   STR         aop the element's operation (STR_OPS); wd the width
        #   PREP, DISP  PREPARE imm16,0 / DISPOSE; LPTR (LES / LDS: aop the segment, 0 DS1, 3 DS0)
        "JMP", "CALL", "LOOP", "RET", "BRK", "STR", "PREP", "DISP", "LPTR",
        # (S5a) the packed BCD strings ADD4S / SUB4S / CMP4S (0F 20 / 22 / 26: aop 0 / 1 / 2);
        # the rest of the 0F page is S5b's
        "BCD")
XFER_KINDS = ("REL", "FAR", "REG", "MEM", "MEMFAR")
RET_KINDS = ("NEAR", "FAR", "INT")
BCD_OPS = {0x20: 0, 0x22: 1, 0x26: 2}                                    # ADD4S SUB4S CMP4S
STR_OPS = {0xA4: 0, 0xA6: 1, 0xAA: 2, 0xAC: 3, 0xAE: 4, 0x6C: 5, 0x6E: 6}   # MOVBK CMPBK STM LDM
                                                                            # CMPM INM OUTM
ROLES = ("NONE",
         "RF",          # the ModR/M reg field's register
         "RM",          # the ModR/M rm field's register, or the memory operand (a memory half)
         "OPR",         # the register in the opcode's bits 2:0 (40-5F, 91-97, B0-BF)
         "ACC",         # AW / AL
         "IMM",         # the immediate (sx: a sign-extended byte)
         "ONE",         # the constant 1 (D0 / D1's count)
         "CL",          # CL (D2 / D3's count)
         "SRF",         # the segment register the reg field's bits 1:0 name (8C / 8E)
         "SOP")         # the segment register the opcode's bits 4:3 name (06-1F)
FLAG_OPS = {0xF8: 0, 0xF9: 1, 0xF5: 2, 0xFA: 3, 0xFB: 4, 0xFC: 5, 0xFD: 6}   # CLC STC CMC CLI STI
ADJ_OPS = {0x27: 0, 0x2F: 1, 0x37: 2, 0x3F: 3}                                # CLD STD; ADJ4A ...
XOP_ATTRS = (("xop", 6, None), ("aop", 3, None), ("opa", 4, None), ("opb", 4, None),
             ("wd", 1, None), ("nwr", 1, None), ("sx", 1, None), ("stk", 1, None))


def _xop_of(op, form) -> dict:
    """The datapath attributes of a started form (XOP_ATTRS), from its encoding."""
    x = {"xop": "NONE", "aop": 0, "opa": "NONE", "opb": "NONE", "wd": 1, "nwr": 0, "sx": 0,
         "stk": int(bool(op.stack))}
    if form.page == 1:
        if form.opcode in BCD_OPS:          # (S5a) the BCD strings' datapath (decoded in S5b)
            x.update(xop="BCD", aop=BCD_OPS[form.opcode], wd=0)
        return _xop_int(x)                  # the rest of the 0F page: S5b's
    o = form.opcode
    reg = (form.modrm >> 3) & 7 if form.modrm is not None else 0
    mem = form.modrm is not None and form.modrm >> 6 != 3

    def put(xop, opa="NONE", opb="NONE", wd=1, aop=0, nwr=0, sx=0):
        x.update(xop=xop, opa=opa, opb=opb, wd=wd, aop=aop, nwr=nwr, sx=sx)

    if form.page == 2 or (o & 0xFE) in STR_OPS:
        # (S5a) a string form (a REP prefix's: page 2, the opcode the string byte)
        put("STR", wd=o & 1, aop=STR_OPS[o & 0xFE])
    elif 0x70 <= o <= 0x7F or o in (0xEB, 0xE9, 0xE3):
        put("JMP", aop=XFER_KINDS.index("REL"))
    elif o in (0xE0, 0xE1, 0xE2):
        put("LOOP", aop=XFER_KINDS.index("REL"))
    elif o == 0xEA:
        put("JMP", aop=XFER_KINDS.index("FAR"))
    elif o == 0xE8:
        put("CALL", aop=XFER_KINDS.index("REL"))
    elif o == 0x9A:
        put("CALL", aop=XFER_KINDS.index("FAR"))
    elif o in (0xC2, 0xC3):
        put("RET", aop=RET_KINDS.index("NEAR"))
    elif o in (0xCA, 0xCB):
        put("RET", aop=RET_KINDS.index("FAR"))
    elif o == 0xCF:
        put("RET", aop=RET_KINDS.index("INT"))
    elif o in (0xCC, 0xCD):
        put("BRK", aop=3 if o == 0xCC else 0)
    elif o == 0xFF and reg in (2, 3, 4, 5):
        kind = ("MEMFAR" if reg in (3, 5) else "MEM") if mem else "REG"
        put("CALL" if reg in (2, 3) else "JMP", opa="RM", aop=XFER_KINDS.index(kind))
    elif o == 0xC8:
        put("PREP", opb="IMM")
    elif o == 0xC9:
        put("DISP")
    elif o in (0xC4, 0xC5):
        put("LPTR", "RF", "RM", aop=0 if o == 0xC4 else 3)
    elif o < 0x40 and o & 7 < 4:
        d = bool(o & 2)
        put("ALU", "RF" if d else "RM", "RM" if d else "RF", o & 1, (o >> 3) & 7,
            int((o >> 3) & 7 == 7))
    elif o < 0x40 and o & 7 in (4, 5):
        put("ALU", "ACC", "IMM", o & 1, (o >> 3) & 7, int((o >> 3) & 7 == 7))
    elif o in (0x06, 0x0E, 0x16, 0x1E):
        put("PUSH", opb="SOP")
    elif o in (0x07, 0x17, 0x1F):
        put("POP", opa="SOP")
    elif o in ADJ_OPS:
        put("ADJ", aop=ADJ_OPS[o], wd=0)
    elif 0x40 <= o <= 0x47:
        put("INC", "OPR")
    elif 0x48 <= o <= 0x4F:
        put("DEC", "OPR")
    elif 0x50 <= o <= 0x57:
        put("PUSH", opb="OPR")
    elif 0x58 <= o <= 0x5F:
        put("POP", opa="OPR")
    elif o == 0x60:
        put("PUSHR")
    elif o == 0x61:
        put("POPR")
    elif o in (0x68, 0x6A):
        put("PUSH", opb="IMM", sx=int(o == 0x6A))
    elif o in (0x69, 0x6B):
        put("MULI", "RF", "RM", sx=int(o == 0x6B))
    elif 0x80 <= o <= 0x83:
        put("ALU", "RM", "IMM", o & 1, reg, int(reg == 7), int(o == 0x83))
    elif o in (0x84, 0x85):
        put("ALU", "RM", "RF", o & 1, 4, 1)
    elif o in (0x86, 0x87):
        put("XCH", "RF", "RM", o & 1)
    elif 0x88 <= o <= 0x8B:
        d = bool(o & 2)
        put("MOV", "RF" if d else "RM", "RM" if d else "RF", o & 1)
    elif o == 0x8C:
        put("SRST", "RM", "SRF")
    elif o == 0x8D:
        put("LDEA", "RF")
    elif o == 0x8E:
        put("SRLD", "SRF", "RM")
    elif o == 0x8F and reg == 0:
        put("POP", opa="RM")
    elif 0x91 <= o <= 0x97:
        put("XCH", "ACC", "OPR")
    elif o == 0x98:
        put("CVTBW")
    elif o == 0x99:
        put("CVTWL")
    elif o == 0x9C:
        put("PUSHF")
    elif o == 0x9D:
        put("POPF")
    elif o == 0x9E:
        put("SAHF", wd=0)
    elif o == 0x9F:
        put("LAHF", wd=0)
    elif o in (0xA0, 0xA1):
        put("MOV", "ACC", "RM", o & 1)
    elif o in (0xA2, 0xA3):
        put("MOV", "RM", "ACC", o & 1)
    elif o in (0xA8, 0xA9):
        put("ALU", "ACC", "IMM", o & 1, 4, 1)
    elif 0xB0 <= o <= 0xB7:
        put("MOV", "OPR", "IMM", 0)
    elif 0xB8 <= o <= 0xBF:
        put("MOV", "OPR", "IMM", 1)
    elif o in (0xC0, 0xC1):
        put("SHIFT", "RM", "IMM", o & 1, reg)
    elif o in (0xD0, 0xD1):
        put("SHIFT", "RM", "ONE", o & 1, reg)
    elif o in (0xD2, 0xD3):
        put("SHIFT", "RM", "CL", o & 1, reg)
    elif o in (0xC6, 0xC7) and reg == 0:
        put("MOV", "RM", "IMM", o & 1)
    elif o == 0xD4:
        put("CVTBD", opb="IMM", wd=0)
    elif o == 0xD5:
        put("CVTDB", opb="IMM", wd=0)
    elif o == 0xD7:
        put("XLAT", "ACC", "RM", 0)
    elif o in (0xE4, 0xE5, 0xEC, 0xED):
        put("IN", "ACC", wd=o & 1)
    elif o in (0xE6, 0xE7, 0xEE, 0xEF):
        put("OUT", opb="ACC", wd=o & 1)
    elif o in FLAG_OPS:
        put("FLAG", aop=FLAG_OPS[o])
    elif o in (0xF6, 0xF7):
        w = o & 1
        if reg in (0, 1):
            put("ALU", "RM", "IMM", w, 4, 1)
        elif reg == 2:
            put("NOT", "RM", wd=w)
        elif reg == 3:
            put("NEG", "RM", wd=w)
        elif reg in (4, 5):
            put("MUL", "ACC", "RM", w)
        else:
            put("DIV", "ACC", "RM", w)
    elif o in (0xFE, 0xFF) and reg in (0, 1):
        put("INC" if reg == 0 else "DEC", "RM", wd=o & 1)
    elif o == 0xFF and reg == 6:
        put("PUSH", opb="RM")
    return _xop_int(x)


def _xop_int(x: dict) -> dict:
    return {**x, "xop": XOPS.index(x["xop"]), "opa": ROLES.index(x["opa"]),
            "opb": ROLES.index(x["opb"])}


@lru_cache(maxsize=1)
def attrs() -> tuple:
    return STRUCT_ATTRS + _decode_attrs() + XOP_ATTRS


def half_fields() -> tuple:
    return (("v", 1), ("cls", 7), ("tail", 3), ("immb", 2), ("w", 1), ("mem", 1),
            ("eafix", 3)) + tuple((n, b) for n, b, _ in attrs())


def dec_fields() -> tuple:
    return (("esc", 2), ("has_modrm", 1), ("grp_v", 1), ("gidx", 5), ("seg", 3), ("repc", 2),
            ("pla_w", 1), ("pla_dir", 1), ("pla_sreg", 1), ("pla_store", 1), ("pla_byte", 1),
            ("hr", half_fields()), ("hm", half_fields()))


def grp_fields() -> tuple:
    return (("hr", half_fields()), ("hm", half_fields()))


def fmt_fields() -> tuple:
    return (("valid", 1), ("cls", 7), ("len", 3), ("page", 2), ("esc", 2), ("rep", 1),
            ("repc", 2), ("seg", 3), ("has_modrm", 1), ("md", 2), ("rfield", 3), ("rm", 3),
            ("mem", 1), ("disp", 2), ("ea_mode", 3), ("bix16", 1), ("tail", 3), ("immb", 2),
            ("w", 1), ("ccode", 4)) + tuple((n, b) for n, b, _ in attrs())


def width_of(fields) -> int:
    return sum(width_of(b) if isinstance(b, tuple) else b for _, b in fields)


def pack(fields, d: dict) -> int:
    """LSB-first packing of a (possibly nested) field list."""
    word, off = 0, 0
    for name, b in fields:
        if isinstance(b, tuple):
            v, w = pack(b, d[name]), width_of(b)
        else:
            v, w = int(d[name]), b
        if not 0 <= v < (1 << w):
            raise UcgenError(f"field {name}={v} does not fit {w} bits")
        word |= v << off
        off += w
    return word


def unpack(fields, word: int) -> dict:
    out, off = {}, 0
    for name, b in fields:
        w = width_of(b) if isinstance(b, tuple) else b
        v = (word >> off) & ((1 << w) - 1)
        out[name] = unpack(b, v) if isinstance(b, tuple) else v
        off += w
    return out


SEG_CODE = {0x26: 1, 0x2E: 2, 0x36: 3, 0x3E: 4, 0xF0: 5}   # DS1 PS SS DS0, BUSLOCK
REP_CODE = {0xF3: 0, 0xF2: 1, 0x65: 2, 0x64: 3}             # REP(E) REPNE REPC REPNC


def _disp_len(modrm) -> int:
    if modrm is None:
        return 0
    mod, rm = modrm >> 6, modrm & 7
    return 1 if mod == 1 else 2 if mod == 2 or (mod == 0 and rm == 6) else 0


def ea_mode_from(md: int, rm: int, cfg) -> str:
    """The EA table entry of a ModR/M memory operand (templates._modrm + ea_class)."""
    T, _, _ = _model()
    if md == 3:
        return "none"
    if md == 0 and rm == 6:
        mc = "direct"
    else:
        mc = T.RM[rm][1]
        if md in (1, 2):
            mc = T.DISP_CLASS[mc]
    if cfg.ea_disp16 == "own" and mc == "base_index_disp" and md == 2:
        mc = "base_index_disp16"
    if cfg.ea_direct == "base_disp" and mc == "direct":
        mc = "base_disp"
    return mc


def _half_of(op, form: Form, cfg) -> dict:
    T, _, _ = _model()
    h = {"v": 1, "cls": op.cls, "tail": op.length - 1 - (1 if form.page else 0)
         - (1 if form.modrm is not None else 0) - _disp_len(form.modrm),
         "immb": op.imm_bytes, "w": int(op.width == 2), "mem": int(op.ea is not None),
         "eafix": 0}
    if op.ea is not None and form.modrm is None:
        h["eafix"] = EA_MODES.index(T.ea_class(op, cfg) or "none")
    for name, _, f in attrs():
        if f is not None:
            h[name] = int(f(op, cfg))
    h.update(_xop_of(op, form))             # (S3) XOP_ATTRS
    return h


def _empty_half() -> dict:
    return {n: (TRAP if n == "cls" else 0) for n, _ in half_fields()}


@dataclasses.dataclass
class Tables:
    native: list            # 256 decode entries (dict), the first byte
    ext: list               # 256, the 0F page's second byte
    grp: list               # [gidx] -> [reg] -> {"hr", "hm"}
    group_ops: list         # [(page, opcode)] by gidx
    pla_diff: list          # [(page, opcode, pla has_modrm, model has_modrm)]


def _parse_pla() -> dict:
    """{(page, opcode): 14-bit PLA vector} from pla3_tables.svh (native, ext)."""
    text = PLA.read_text()
    out = {}
    for page, fn in ((0, "pla3_native"), (1, "pla3_ext")):
        body = text[text.index(f"function automatic logic [13:0] {fn}("):]
        body = body[:body.index("endfunction")]
        for m in re.finditer(r"8'h([0-9A-F]{2}): " + fn + r" = 14'h([0-9A-F]{4});", body):
            out[(page, int(m.group(1), 16))] = int(m.group(2), 16)
    return out


def build_tables(forms: list, cfg, bad: set) -> Tables:
    """The decode table from the enumerated forms: per (page, opcode[, reg of a group opcode],
    register / memory half) the started form's class, trailing operand bytes and format bits;
    a cell must be one value for every form in it. `bad`: forms (by index) the model has no
    template for (NotModelled): their cells are invalid (trap_nop)."""
    T, _, _ = _model()
    cells: dict = {}
    modrm_ops = {0: set(), 1: set()}
    for i, f in enumerate(forms):
        op = started(f.op, cfg)
        if f.modrm is not None:
            modrm_ops[min(f.page, 1)].add(f.opcode)
        if f.page != 2 and f.modrm is not None and op.disp != _disp_len(f.modrm) and op.ea is not None:
            raise UcgenError(f"{f.code.hex(' ')}: displacement {op.disp} is not the ModR/M's")
        half = "m" if f.modrm is not None and f.modrm >> 6 != 3 else "r"
        reg = (f.modrm >> 3) & 7 if f.modrm is not None else None
        key = (f.page, f.opcode, reg, half)
        val = _half_of(op, f, cfg)
        if i in bad:
            # no template: trap_nop, the decoder's length kept (the loader takes its bytes)
            val = {**_empty_half(), "tail": val["tail"]}
        old = cells.setdefault(key, val)
        if old != val:
            diff = {k: (old[k], val[k]) for k in val if old[k] != val[k]}
            raise UcgenError(f"decode cell {key} is not one value ({f.code.hex(' ')}): {diff}")
    pla = _parse_pla()
    group_ops = sorted({(p, o) for (p, o, r, h) in cells if r is not None and p == 0
                        and o in T.GROUP_OPCODES})
    grp_idx = {k: i for i, k in enumerate(group_ops)}

    def cell(p, o, r, h):
        return cells.get((p, o, r, h))

    def collapse(p, o, h):
        vals = {r: cell(p, o, r, h) for r in [None] + list(range(8)) if cell(p, o, r, h)}
        if not vals:
            return _empty_half()
        distinct = {json.dumps(v, sort_keys=True) for v in vals.values()}
        if len(distinct) > 1:
            raise UcgenError(f"opcode {p}:{o:02X} {h}: the reg field changes the form but it "
                             f"is not a group opcode")
        return next(iter(vals.values()))

    tables = []
    pla_diff = []
    for p in (0, 1):
        tbl = []
        for o in range(256):
            e = {"esc": 0, "has_modrm": int(o in modrm_ops[p]), "grp_v": 0, "gidx": 0,
                 "seg": SEG_CODE.get(o, 0) if p == 0 else 0,
                 "repc": REP_CODE.get(o, 0) if p == 0 else 0}
            if p == 0 and o == 0x0F:
                e["esc"] = 1
            if p == 0 and o in REP_CODE:
                e["esc"] = 2
            v = pla.get((p, o), 0)
            e.update(pla_w=v >> 12 & 1, pla_dir=v >> 6 & 1, pla_sreg=v >> 9 & 1,
                     pla_store=v >> 7 & 1, pla_byte=v >> 13 & 1)
            if (p, o) in grp_idx:
                e["grp_v"], e["gidx"] = 1, grp_idx[(p, o)]
                e["hr"], e["hm"] = _empty_half(), _empty_half()
            else:
                e["hr"], e["hm"] = collapse(p, o, "r"), collapse(p, o, "m")
            any_form = any(k[0] == p and k[1] == o for k in cells)
            if any_form and bool(v >> 8 & 1) != bool(e["has_modrm"]):
                pla_diff.append((p, o, v >> 8 & 1, e["has_modrm"]))
            tbl.append(e)
        tables.append(tbl)
    grp = []
    for (p, o) in group_ops:
        grp.append([{"hr": cell(p, o, r, "r") or _empty_half(),
                     "hm": cell(p, o, r, "m") or _empty_half()} for r in range(8)])
    # the REP forms: the string opcode's own entry with rep
    for (p, o, r, h), v in cells.items():
        if p == 2:
            nat = tables[0][o]["hr"]
            if {**v, "tail": 0} != {**nat, "tail": 0} or v["tail"] != 0:
                raise UcgenError(f"REP {o:02X}: not the string opcode's entry")
    return Tables(tables[0], tables[1], grp, group_ops, pla_diff)


def fmt_of(tb: Tables, cfg, opcode: int, page: int, modrm: int, classes: list) -> dict:
    """The format word of an instruction (mirrors v35_pkg::v35_fmt_of): opcode the decode
    table's index byte (page 0: the first byte; 1: the 0F page's second byte; 2: the string
    opcode after a REP prefix), modrm the ModR/M byte (ignored without one)."""
    d = tb.ext[opcode] if page == 1 else tb.native[opcode]
    hm = 0 if page == 2 else d["has_modrm"]
    md, rf, rm = ((modrm >> 6) & 3, (modrm >> 3) & 7, modrm & 7) if hm else (0, 0, 0)
    g = tb.grp[d["gidx"]][rf] if d["grp_v"] else {"hr": d["hr"], "hm": d["hm"]}
    h = g["hm"] if hm and md != 3 else g["hr"]
    if page == 2 and not h["strop"]:
        h = _empty_half()
    f = {n: 0 for n, _ in fmt_fields()}
    f.update(page=page, esc=d["esc"] if page == 0 else 0, seg=d["seg"], repc=d["repc"],
             rep=int(page == 2), has_modrm=hm, md=md, rfield=rf, rm=rm)
    f["disp"] = (1 if hm and md == 1 else 2 if hm and (md == 2 or (md == 0 and rm == 6)) else 0)
    f["len"] = 1 + int(page != 0) + hm + f["disp"] + h["tail"]
    f["valid"] = h["v"]
    f["cls"] = classes.index(h["cls"]) if isinstance(h["cls"], str) else h["cls"]
    for n in ("tail", "immb", "w", "mem"):
        f[n] = h[n]
    if h["mem"] and hm:
        f["ea_mode"] = EA_MODES.index(ea_mode_from(md, rm, cfg))
    elif h["mem"]:
        f["ea_mode"] = h["eafix"]
    f["bix16"] = int(bool(hm and md == 2 and rm < 4))
    f["ccode"] = opcode & 15 if h["cond"] else 0
    for n, _, _ in attrs():
        f[n] = h[n]
    return f


# --------------------------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------------------------

# the format bits a template may depend on, in the order the per-class reduction tries to drop
# them (the last first); the start-time bits after them
KEY_FIELDS = ("mem", "disp", "immb", "w", "rep", "sgn", "grp", "fixed_alu", "shift", "cl_shift",
              "nowrite", "swap", "dbit_v", "dbit", "cond", "count_byte", "cl_count", "modrm_op",
              "bus", "port", "sreg", "bix16", "ea_mode", "has_modrm", "page", "tail")
RUN_NAMES = tuple(n for n, _ in RUN_FIELDS)
SEL_FIELDS = KEY_FIELDS + RUN_NAMES
SEL_BITS = dict((n, b) for n, b in fmt_fields() if n in KEY_FIELDS)
SEL_BITS.update(dict(RUN_FIELDS))
TRAP_ROWS = [dict(ROW_DEFAULT, op="CLOCKS", imm=2, tdelay=1, last=1)]


@dataclasses.dataclass
class Gen:
    cfg: object
    md5: str
    classes: list
    forms: list
    bad: dict                   # {form index: reason} of the forms with no template
    tables: Tables
    sym: dict                   # {form index: [(run, rows)]}
    templates: list             # [rows] by template id (0: trap_nop)
    tmpl_base: list             # first row of each template
    rows: list                  # the ROM, every template's rows in id order
    sel: dict                   # {class id: (fields, {projection: template id})}
    tmpl_classes: dict          # {template id: sorted class names}
    examples: dict              # {template id: an example encoding}


def _sym_key(sop, ea_mode):
    d = dict(sop.__dict__)
    d["offset"] = 0
    return repr(sorted(d.items())), ea_mode


def generate(cfg=None, md5=None) -> Gen:
    if cfg is None:
        cfg, md5 = load_fit()
    classes = class_list(cfg)
    forms = enumerate_forms(cfg)
    cache, sym, bad = {}, {}, {}
    for i, f in enumerate(forms):
        try:
            sop = _sent_form(f, cfg)
            ea_mode = ea_mode_of(sop, cfg) if f.modrm is not None else None
            key = _sym_key(sop, ea_mode)
            if key not in cache:
                cache[key] = sym_templates(sop, cfg, ea_mode)
            sym[i] = cache[key]
        except NotModelled as e:
            bad[i] = str(e)
    tb = build_tables(forms, cfg, set(bad))
    entries: dict = {}
    first_ex: dict = {}
    for i, f in enumerate(forms):
        if i in bad:
            continue
        fm = fmt_of(tb, cfg, f.opcode, f.page, f.modrm or 0, classes)
        op = started(f.op, cfg)
        if fm["len"] != op.length or classes[fm["cls"]] != op.cls:
            raise UcgenError(f"{f.code.hex(' ')}: fmt says {classes[fm['cls']]} / {fm['len']}, "
                             f"the decoder {op.cls} / {op.length}")
        base_run = {"taken": int(op.target is not None), "zfail": int(bool(op.zfail))}
        for run, rows in sym[i]:
            r = {**base_run, **run}
            key = (fm["cls"],) + tuple(fm[k] for k in KEY_FIELDS) + tuple(r[k] for k in RUN_NAMES)
            fr = tuple(freeze(x) for x in rows)
            old = entries.setdefault(key, fr)
            if old != fr:
                raise UcgenError(f"{f.code.hex(' ')}: format {key} selects two templates")
            first_ex.setdefault(fr, (op.cls, f.code.hex(" ")))
    # template ids: trap_nop first, then by (class, example)
    uniq = sorted(set(entries.values()), key=lambda fr: (first_ex[fr], fr))
    trap = tuple(freeze(r) for r in TRAP_ROWS)
    order = [trap] + [fr for fr in uniq if fr != trap]
    tid = {fr: i for i, fr in enumerate(order)}
    templates = [[thaw(r) for r in fr] for fr in order]
    base, rows = [], []
    for t in templates:
        base.append(len(rows))
        rows += t
    tmpl_classes = {0: [TRAP]}
    examples = {}
    for fr, (c, ex) in first_ex.items():
        examples.setdefault(tid[fr], ex)
    examples.setdefault(0, "(none)")
    for key, fr in entries.items():
        tmpl_classes.setdefault(tid[fr], [])
        if classes[key[0]] not in tmpl_classes[tid[fr]]:
            tmpl_classes[tid[fr]].append(classes[key[0]])
    tmpl_classes = {k: sorted(v) for k, v in tmpl_classes.items()}
    sel = reduce_selection({k: tid[v] for k, v in entries.items()}, len(classes))
    return Gen(cfg, md5, classes, forms, bad, tb, sym, templates, base, rows, sel, tmpl_classes,
               examples)


def reduce_selection(entries: dict, ncls: int) -> dict:
    """Per class, the fewest format / start-time bits that still select one template for every
    enumerated format (greedy: each field dropped, last first, when the selection stays a
    function)."""
    out = {}
    for c in range(ncls):
        sub = {k[1:]: v for k, v in entries.items() if k[0] == c}
        keep = list(range(len(SEL_FIELDS)))
        for f in reversed(range(len(SEL_FIELDS))):
            trial = [k for k in keep if k != f]
            proj: dict = {}
            ok = True
            for k, v in sub.items():
                p = tuple(k[j] for j in trial)
                if proj.setdefault(p, v) != v:
                    ok = False
                    break
            if ok:
                keep = trial
        mapping = {}
        for k, v in sub.items():
            mapping[tuple(k[j] for j in keep)] = v
        out[c] = (tuple(SEL_FIELDS[j] for j in keep), dict(sorted(mapping.items())))
    return out


def tmpl_of(gen: Gen, fm: dict, run: dict) -> int:
    """The template id (mirrors v35_pkg::v35_tmpl_of); 0 (trap_nop) for a format no
    enumerated form has."""
    fields, mapping = gen.sel.get(fm["cls"], ((), {}))
    vals = {**fm, **run}
    return mapping.get(tuple(vals[n] for n in fields), 0)


# --------------------------------------------------------------------------------------------
# Checks used by test_ucgen
# --------------------------------------------------------------------------------------------

def run_variants(op, cfg):
    """The run values the inverse check expands a form under: (run dict for with_run, held)."""
    T, _, _ = _model()
    out = []
    counts = (0, 1, 2, 7, 255) if has_count(op) else (None,)
    mnegs = (0, 8, 10) if has_mneg(op) else (None,)
    if is_loop(op):
        loops = [(n, c) for n in (0, 1, 2, 3, 6)
                 for c in ((False, True) if op.cls in T.STRING_COMPARES and n else (False,))]
    else:
        loops = [(None, None)]
    bfs = ((0, 3), (3, 15), (12, 7), (0, 15), (9, 6)) if has_bf(op) else (None,)
    helds = (False, True) if cfg.port_latch == "relatch" and op.cls in ("in", "out") \
        and op.length > 1 else (False,)
    for half in (False, True):
        for cnt in counts:
            for mn in mnegs:
                for n, cond in loops:
                    for bf in bfs:
                        for held in helds:
                            r = {"half": half}
                            if cnt is not None:
                                r["count"] = cnt
                            if mn is not None:
                                r["mneg"] = mn
                            if n is not None:
                                r["n"], r["cond"] = n, cond
                            if bf is not None:
                                r["bfcost"] = T.bf_cost(op.cls, *bf)
                                r["cross"] = bf[0] + bf[1] >= 16
                            out.append((r, held))
    return out


def inverse_check(gen: Gen, limit_fail: int = 20):
    """Expand every enumerated form's template (selected through fmt_of / tmpl_of, as the RTL
    selects it) under each run variant and compare with the model's step list, both canonical.
    Returns (checks, failures)."""
    cfg = gen.cfg
    checks, fails = 0, []
    for i, f in enumerate(gen.forms):
        if i in gen.bad:
            continue
        op = started(f.op, cfg)
        fm = fmt_of(gen.tables, cfg, f.opcode, f.page, f.modrm or 0, gen.classes)
        ea_mode = ea_mode_of(op, cfg) if f.modrm is not None else None
        for run, held in run_variants(op, cfg):
            o = with_run(op, **run)
            if "n" in run:
                o.n, o.cond = run["n"], run["cond"]
            rb = {"taken": int(op.target is not None), "zfail": int(bool(op.zfail)),
                  "cnt0": int(has_count(op) and o.count == 0), "half": int(run["half"]),
                  "n0": int(is_loop(op) and o.n == 0)}
            t = tmpl_of(gen, fm, rb)
            ctx = ctx_of(o, cfg, ea_mode, f.regs, held=held)
            got = canonical(expand(gen.templates[t], ctx))
            want = canonical(model_steps(o, cfg, held_at=held))
            checks += 1
            if got != want:
                fails.append((f.code.hex(" "), op.cls, run, held, t, got, want))
                if len(fails) >= limit_fail:
                    return checks, fails
    return checks, fails


def s5_budget(gen: Gen) -> list:
    """The S5 budget check (docs/v35s-core-v2.md, "S5 budget check"): for every template a
    register-only form of an I/O-interlocked class starts (fmt regonly), the actions on its
    start clock: row 0 and every row after a row that completes on that clock (tdelay 0, no
    wait of its own: a lead take, a post). Each: (class, template, actions, fits) where fits =
    at most one take (of one byte, or a lead take), one post, one clocks load, nothing else."""
    out = {}
    for i, f in enumerate(gen.forms):
        if i in gen.bad:
            continue
        fm = fmt_of(gen.tables, gen.cfg, f.opcode, f.page, f.modrm or 0, gen.classes)
        if not fm["regonly"]:
            continue
        op = started(f.op, gen.cfg)
        for run, _ in gen.sym[i]:
            rb = {"taken": int(op.target is not None), "zfail": int(bool(op.zfail)), **run}
            t = tmpl_of(gen, fm, rb)
            out.setdefault((op.cls, t), None)
    res = []
    for (cls, t) in sorted(out):
        rows = gen.templates[t]
        acts, k = [], 0
        while k < len(rows):
            r = rows[k]
            a = r["op"]
            if a == "TAKE":
                a += f"({r['aidx']}{',' + r['tag'].lower() if r['tag'] != 'NONE' else ''})"
            if r["wcond"] != "NONE" and k:
                break                       # waits: not on the start clock
            if r["wcond"] != "NONE":
                a = f"[{r['wcond'].lower()}] " + a
            if r["arm"] != "NONE":
                a += f" +{r['arm'].lower()}"
            acts.append(a)
            done_now = r["op"] in ("POST", "POST_IO", "NOP") or (r["op"] == "TAKE"
                                                                 and r["tag"] == "LEAD")
            if not done_now or r["last"]:
                break
            k += 1
        takes = [a for a in acts if a.split(" ")[-1].startswith("TAKE") or "TAKE" in a]
        posts = [a for a in acts if "POST" in a or "DATA" in a]
        clocks = [a for a in acts if "CLOCKS" in a]
        other = [a for a in acts if a not in takes + posts + clocks and "NOP" not in a]
        one_byte = all(("(1" in a) or ",lead" in a for a in takes)
        fits = len(takes) <= 1 and len(posts) <= 1 and len(clocks) <= 1 and not other and one_byte
        res.append((cls, t, acts, fits))
    return res


# --------------------------------------------------------------------------------------------
# instructions.json: the data book's encodings, a cross-check of the trailing operand bytes
# --------------------------------------------------------------------------------------------

_FIELD_W = {"W": 1, "S": 1, "s": 1, "X": 1, "reg": 3, "reg8": 3, "reg1": 3, "reg2": 3,
            "sreg": 2, "mod": 2, "mem": 3}


def _pattern(tok: str) -> list:
    """An encoding byte string -> 8 symbols, MSB first: '0' / '1' or a field name."""
    out = []
    for t in tok.split():
        if t in _FIELD_W:
            out += [t] * _FIELD_W[t]
        else:
            out += list(t)
    if len(out) != 8:
        raise UcgenError(f"encoding byte {tok!r} is not 8 bits")
    return out


def _matches(pat: list, v: int):
    """None, or the field bindings of v under the pattern."""
    bind = {}
    for i, s in enumerate(pat):
        bit = (v >> (7 - i)) & 1
        if s in "01":
            if int(s) != bit:
                return None
        else:
            bind[s] = bind.get(s, 0) << 1 | bit
    return bind


def json_tails() -> dict:
    """{(page, opcode, half, reg or None): {trailing operand bytes}} from the data book's
    encodings (instructions.json): the bytes after the opcode (and the 0F page byte) and the
    ModR/M byte, displacements excluded; "imm8 or imm16-low" + "imm16-high" is 1 + W (1 with
    S = 1)."""
    recs = json.loads(INSTR_JSON.read_text())["instructions"]
    out: dict = {}
    for rec in recs:
        enc = list(rec["encoding"])
        page = 1 if enc[0] == "00001111" and len(enc) > 1 else 0
        if page:
            enc = enc[1:]
        p0 = _pattern(enc[0])
        rest = enc[1:]
        mod = None
        if rest and (rest[0].startswith("mod") or rest[0].startswith("11")):
            mod, rest = _pattern(rest[0]), rest[1:]
            rest = [t for t in rest if t not in ("(disp-low)", "(disp-high)")]
        for v in range(256):
            b = _matches(p0, v)
            if b is None:
                continue
            n = 0
            wide = any(t.startswith("imm8") and "imm16" in t for t in rest)
            for t in rest:
                if t == "imm16-high" and wide:
                    n += int(b.get("W", 1) == 1 and b.get("S", 0) == 0)
                else:
                    n += 1
            if mod is None:
                keys = [(page, v, "r", None)]
            else:
                half = "r" if mod[0] == "1" and mod[1] == "1" else "m"
                regbits = mod[2:5]
                regs = ([int("".join(regbits), 2)] if all(c in "01" for c in regbits)
                        else list(range(8)))
                keys = [(page, v, half, r) for r in regs]
            for k in keys:
                out.setdefault(k, set()).add(n)
    return out


def json_crosscheck(gen: Gen) -> list:
    """[(page, opcode, half, reg, model tail, data book tails)] where a valid decode cell's
    trailing bytes are not among the data book's for that encoding (or it has none)."""
    js = json_tails()
    out = []
    for page, tbl in ((0, gen.tables.native), (1, gen.tables.ext)):
        for o in range(256):
            e = tbl[o]
            if e["grp_v"]:
                cells = [(h, r, gen.tables.grp[e["gidx"]][r][f"h{h}"]) for r in range(8)
                         for h in ("r", "m")]
            else:
                cells = [(h, None, e[f"h{h}"]) for h in ("r", "m")]
            for h, r, cell in cells:
                if not cell["v"]:
                    continue
                cand = set()
                for reg in ([r] if r is not None else [None] + list(range(8))):
                    cand |= js.get((page, o, h, reg), set())
                    if h == "r":
                        cand |= js.get((page, o, "r", None), set())
                if cell["tail"] not in cand:
                    out.append((page, o, h, r, cell["tail"], sorted(cand)))
    return out


# --------------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------------

def _ident(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", s).upper()


def _bits(n: int) -> int:
    return max(1, int(n).bit_length())


CLASS_COLS = (
    # (column, f(cfg, cls)): the class integers hardwired logic reads outside the rows
    ("nx", lambda c, k: c.c(k, "nx")),
    ("nx0", lambda c, k: c.c(k, "nx0")),
    ("wb", lambda c, k: c.c(k, "wb")),
    ("mwb", lambda c, k: c.c(k, "mwb" if "mwb" in c.cost.get(k, {}) else "wb")),
    ("rwb", lambda c, k: c.c(k, "rwb" if "rwb" in c.cost.get(k, {}) else "wb")),
    ("uwb", lambda c, k: c.c(k, "uwb")),
    ("xwb", lambda c, k: c.c(k, "xwb")),
    ("flwb", lambda c, k: c.c(k, "flwb")),
    ("fwb", lambda c, k: c.c(k, "fwb")),
    ("wbsync", lambda c, k: c.c(k, "wbsync")),
    ("wbsync0", lambda c, k: c.c(k, "wbsync0" if "wbsync0" in c.cost.get(k, {}) else "wbsync")),
    ("hphase", lambda c, k: c.c(k, "hphase")),
    ("mtail", lambda c, k: c.c(k, "mtail")),
    ("mtx", lambda c, k: c.c(k, "mtx")),
    ("sidle", lambda c, k: c.c(k, "sidle")),
    ("relatch", lambda c, k: c.c(k, "relatch")),
    ("lead", lambda c, k: c.c(k, "lead")),
    ("setup_free", lambda c, k: c.c(k, "setup_free")),
    ("setup_free_v", lambda c, k: int("setup_free" in c.cost.get(k, {}))),
    ("grp_free", lambda c, k: c.c(k, "grp_free")),
    ("fsetup", lambda c, k: c.c(k, "fsetup")),
    ("ftail", lambda c, k: c.c(k, "ftail")),
    ("dfloor", lambda c, k: c.c(k, "dfloor")),
    ("istart", lambda c, k: c.c(k, "istart")),
    ("istart_v", lambda c, k: int("istart" in c.cost.get(k, {}))),
    ("fgrp", lambda c, k: c.c(k, "fgrp")),
    ("fgrp_free", lambda c, k: c.c(k, "fgrp_free")),
    ("dhold", lambda c, k: c.c(k, "dhold" if "dhold" in c.cost.get(k, {}) else "grp_free")),
    ("pdhold", lambda c, k: c.c(k, "pdhold")),
    ("hold", lambda c, k: c.c(k, "hold")),
    ("nhold", lambda c, k: c.c(k, "nhold")),
    ("chold", lambda c, k: c.c(k, "chold")),
    ("fgap", lambda c, k: c.c(k, "fgap")),
    ("nfgap", lambda c, k: c.c(k, "nfgap")),
    ("cfgap", lambda c, k: c.c(k, "cfgap")),
    ("gap", lambda c, k: c.c(k, "gap")),
    ("ugap", lambda c, k: c.c(k, "ugap")),
    ("ufree", lambda c, k: c.c(k, "ufree")),
    ("usetup", lambda c, k: c.c(k, "usetup")),
    ("usetup_v", lambda c, k: int("usetup" in c.cost.get(k, {}))),
    ("grpcl", lambda c, k: c.c(k, "grpcl")),
    # (S4) dest_route=slot's routing clocks (rmw_alu=through: through = setup - dclk - 1 for a
    # swap form's write)
    ("dclk", lambda c, k: c.c(k, "dclk")),
    ("cl", lambda c, k: c.c(k, "cl")),
    ("pre", lambda c, k: c.c(k, "pre")),
    ("pre0", lambda c, k: c.c(k, "pre0")),
    ("setup", lambda c, k: c.c(k, "setup")),
    ("first", lambda c, k: class_consts(c, k)["first"]),
    ("loop", lambda c, k: class_consts(c, k)["loop"]),
    ("loop1", lambda c, k: class_consts(c, k)["loop1"]),
    ("last", lambda c, k: class_consts(c, k)["last"]),
)


def class_table(gen: Gen) -> tuple[list, list]:
    """(columns [(name, bits)], rows [{column: value}] by class id)."""
    rows = []
    for k in gen.classes:
        rows.append({n: (0 if k == TRAP else int(f(gen.cfg, k))) for n, f in CLASS_COLS})
    cols = [(n, _bits(max(r[n] for r in rows))) for n, _ in CLASS_COLS]
    return cols, rows


def _sv_struct(name: str, fields, types: dict | None = None) -> list:
    """typedef struct packed (MSB first) from an LSB-first field list."""
    out = [f"  typedef struct packed {{"]
    for n, b in reversed(fields):
        if types and n in types:
            out.append(f"    {types[n]} {n};")
        elif isinstance(b, str):
            out.append(f"    {b} {n};")
        else:
            out.append(f"    logic{'' if b == 1 else f' [{b - 1}:0]'} {n};")
    out.append(f"  }} {name};")
    return out


ENUM_PREFIX = {"op": ("v35_op_e", "V35_OP_"), "skip": ("v35_skip_e", "V35_SKIP_"),
               "wcond": ("v35_wcond_e", "V35_WC_"), "nsrc": ("v35_nsrc_e", "V35_NSRC_"),
               "tag": ("v35_tag_e", "V35_TAG_"), "rkind": ("v35_rkind_e", "V35_RK_"),
               "asrc": ("v35_asrc_e", "V35_ASRC_"), "wsel": ("v35_wsel_e", "V35_WSEL_"),
               "i2m": ("v35_i2m_e", "V35_I2M_"), "arm": ("v35_arm_e", "V35_ARM_"),
               "apos": ("v35_apos_e", "V35_APOS_")}


def _header(gen: Gen, what: str, comment: str = "//") -> list:
    return [f"{comment} GENERATED by `{INVOCATION}` from validation/v35s/chains/fit.json "
            f"(md5 {gen.md5}); do not edit.",
            f"{comment} {what}",
            f"{comment} Design: docs/v35s-core-v2.md (Microcode, Function path, Appendix B s3/s4);"
            f" generator: validation/v35s/chains/ucgen.py; checked by test_ucgen."]


def _row_comment(r: dict) -> str:
    parts = [r["op"]]
    for n, _ in ROW_FIELDS:
        if n == "op" or r[n] == ROW_DEFAULT[n] or n == "tdelay":
            continue
        parts.append(f"{n}={r[n]}")
    return " ".join(str(p) for p in parts)


def render_hex(gen: Gen) -> str:
    lines = _header(gen, f"The microcode ROM: {len(gen.rows)} rows of {ROW_BITS} bits "
                         f"(uc_row_t, v35_pkg.sv), one per line, row 0 first.")
    lines.append("// Row layout, LSB first: " + ", ".join(f"{n} {b}" for n, b in ROW_FIELDS))
    digits = (ROW_BITS + 3) // 4
    starts = {b: t for t, b in enumerate(gen.tmpl_base)}
    for i, r in enumerate(gen.rows):
        if i in starts:
            t = starts[i]
            lines.append(f"// template {t}: {' '.join(gen.tmpl_classes.get(t, []))} "
                         f"(e.g. {gen.examples.get(t)})")
        lines.append(f"{pack_row(r):0{digits}x}  // {i}: {_row_comment(r)}")
    return "\n".join(lines) + "\n"


def render_bank_hex(gen: Gen, b: int) -> str:
    """(S3) bank b of the ROM: rows b, b + 4, b + 8 ... (row address mod 4 = b), one per line,
    padded with zero rows to the banks' common depth."""
    depth = (len(gen.rows) + ROM_BANKS - 1) // ROM_BANKS
    lines = _header(gen, f"The microcode ROM's bank {b} of {ROM_BANKS}: rows {b}, {b} + "
                         f"{ROM_BANKS}, ... (row address mod {ROM_BANKS} = {b}), {depth} lines "
                         f"of {ROW_BITS} bits (v35_ucode.hex row by row).")
    digits = (ROW_BITS + 3) // 4
    for k in range(depth):
        i = ROM_BANKS * k + b
        word = pack_row(gen.rows[i]) if i < len(gen.rows) else 0
        lines.append(f"{word:0{digits}x}  // {i}")
    return "\n".join(lines) + "\n"


def _sel_literal(fields, proj) -> str:
    bits = "".join(format(v, f"0{SEL_BITS[n]}b") for n, v in zip(fields, proj))
    return f"{len(bits)}'b{bits}"


def render_ucode_tbl(gen: Gen) -> str:
    nt = len(gen.templates)
    ab, tb = ROWA_BITS, TMPL_BITS
    lines = _header(gen, f"The template table: {nt} templates over {len(gen.rows)} rows; "
                         f"v35_tmpl_sel: class x format bits x start-time bits -> template.")
    lines += ["// `include`d by v35_pkg.sv (package scope): functions only.", ""]
    lines.append(f"  function automatic logic [{ab - 1}:0] v35_tmpl_base(input logic [{tb - 1}:0] t);")
    lines.append("    case (t)")
    for t, b in enumerate(gen.tmpl_base):
        cl = " ".join(gen.tmpl_classes.get(t, []))
        lines.append(f"      {tb}'d{t}: v35_tmpl_base = {ab}'d{b};  // {len(gen.templates[t])} rows: {cl}")
    lines.append(f"      default: v35_tmpl_base = {ab}'d0;")
    lines += ["    endcase", "  endfunction", ""]
    lines.append("  // The template a started form runs: per class, the format / start-time bits"
                 " that change it (the rest do not); an unlisted combination is trap_nop's (0).")
    lines.append(f"  function automatic logic [{tb - 1}:0] v35_tmpl_sel(input v35_fmt_t f, "
                 f"input v35_run_t r);")
    lines.append(f"    v35_tmpl_sel = {tb}'d0;")
    lines.append("    case (f.cls)")
    for c, (fields, mapping) in sorted(gen.sel.items()):
        if not mapping:
            continue
        name = f"V35_CLS_{_ident(gen.classes[c])}"
        if not fields:
            lines.append(f"      {name}: v35_tmpl_sel = {tb}'d{next(iter(mapping.values()))};")
            continue
        sel = ", ".join(f"{'r' if n in RUN_NAMES else 'f'}.{n}" for n in fields)
        lines.append(f"      {name}:")
        lines.append(f"        case ({{{sel}}})")
        for proj, t in mapping.items():
            lines.append(f"          {_sel_literal(fields, proj)}: v35_tmpl_sel = {tb}'d{t};")
        lines.append(f"          default: v35_tmpl_sel = {tb}'d0;")
        lines.append("        endcase")
    lines.append(f"      default: v35_tmpl_sel = {tb}'d0;")
    lines += ["    endcase", "  endfunction", ""]
    return "\n".join(lines)


def _half_comment(h: dict) -> str:
    if not h["v"]:
        return "-"
    on = [n for n, _, _ in attrs() if h[n]]
    return f"{h['cls']} tail{h['tail']} imm{h['immb']} {'w' if h['w'] else 'b'}" + \
        (" mem" if h["mem"] else "") + ("" if not on else " " + ",".join(on))


def _half_int(h: dict, classes: list) -> dict:
    return {**h, "cls": classes.index(h["cls"]) if isinstance(h["cls"], str) else h["cls"]}


def render_decode_tbl(gen: Gen) -> str:
    tb, classes = gen.tables, gen.classes
    dw, gw = width_of(dec_fields()), width_of(grp_fields())
    trap_ops = []
    for page, tbl in ((0, tb.native), (1, tb.ext)):
        for o in range(256):
            e = tbl[o]
            valid = e["esc"] or (any(gen.tables.grp[e["gidx"]][r][h]["v"] for r in range(8)
                                     for h in ("hr", "hm")) if e["grp_v"]
                                 else e["hr"]["v"] or e["hm"]["v"])
            if not valid:
                trap_ops.append(("0F." if page else "") + f"{o:02X}")
    lines = _header(gen, "The decode table: 256 native + 256 0F-page entries (v35_dec_t) and the "
                         "group opcodes' reg-field overrides (v35_grp_t).")
    lines.append("// Sources: the class, trailing operand bytes and format bits from the live "
                 "decoder (sim/templates.decode, the")
    lines.append("// started form as eu._start runs it); pla_* bits from fpga/v35s/core/ucore/"
                 "pla3_tables.svh; trailing bytes")
    lines.append("// cross-checked against build/deps/nuV30/docs/facts/instructions.json "
                 "(differences: fpga/v35s/core/v35/README.md).")
    lines.append(f"// trap_nop (no form the model runs: {len(trap_ops)} entries):" )
    for k in range(0, len(trap_ops), 24):
        lines.append("//   " + " ".join(trap_ops[k:k + 24]))
    bad = sorted({(gen.forms[i].code.hex(" ")[:5], gen.forms[i].op.cls) for i in gen.bad})
    lines.append("// register forms the decoder accepts but no template runs (trap_nop "
                 "halves): " + ", ".join(sorted({c for _, c in bad})))
    lines += ["// `include`d by v35_pkg.sv (package scope): functions only.", ""]
    for page, fn, tbl in ((0, "v35_dec_native", tb.native), (1, "v35_dec_ext", tb.ext)):
        lines.append(f"  function automatic v35_dec_t {fn}(input logic [7:0] op);")
        lines.append("    case (op)")
        for o in range(256):
            e = tbl[o]
            ent = {**e, "hr": _half_int(e["hr"], classes), "hm": _half_int(e["hm"], classes)}
            word = pack(dec_fields(), ent)
            com = ("esc" + str(e["esc"]) + " " if e["esc"] else "") + \
                (f"grp{e['gidx']}" if e["grp_v"] else
                 f"r: {_half_comment(e['hr'])} | m: {_half_comment(e['hm'])}")
            lines.append(f"      8'h{o:02X}: {fn} = {dw}'h{word:0{(dw + 3) // 4}x};  // {com}")
        lines.append(f"      default: {fn} = '0;")
        lines += ["    endcase", "  endfunction", ""]
    gb = _bits(max(1, len(tb.group_ops) - 1))
    lines.append(f"  function automatic v35_grp_t v35_dec_grp(input logic [4:0] gidx, "
                 f"input logic [2:0] rfield);")
    lines.append("    case ({gidx, rfield})")
    for gi, (page, o) in enumerate(tb.group_ops):
        for r in range(8):
            g = tb.grp[gi][r]
            ent = {"hr": _half_int(g["hr"], classes), "hm": _half_int(g["hm"], classes)}
            word = pack(grp_fields(), ent)
            lines.append(f"      8'b{gi:05b}{r:03b}: v35_dec_grp = {gw}'h{word:0{(gw + 3) // 4}x};"
                         f"  // {o:02X} /{r} r: {_half_comment(g['hr'])} | m: "
                         f"{_half_comment(g['hm'])}")
    lines.append("      default: v35_dec_grp = '0;")
    lines += ["    endcase", "  endfunction", ""]
    return "\n".join(lines)


def render_class_tbl(gen: Gen) -> str:
    cols, rows = class_table(gen)
    bits = sum(b for _, b in cols)
    lines = _header(gen, f"The class table: {len(gen.classes)} classes x {bits} bits "
                         f"(v35_cls_t): the class integers read outside the rows.")
    lines.append("// Effective columns: mwb / rwb / wbsync0 / dhold fall back to wb / wb / wbsync"
                 " / grp_free where the class has none")
    lines.append("// (eu._start, eu.tick); *_v: the integer exists for the class (eu reads "
                 "`name in cost[cls]`); loop1 falls back to loop.")
    lines += ["// `include`d by v35_pkg.sv (package scope).", ""]
    lines.append("  function automatic v35_cls_t v35_cls_const(input logic [6:0] cls);")
    lines.append("    case (cls)")
    for i, (k, r) in enumerate(zip(gen.classes, rows)):
        vals = ", ".join(f"{n}: {r[n]}" for n, _ in cols)
        lines.append(f"      V35_CLS_{_ident(k)}: v35_cls_const = '{{{vals}}};")
    lines.append("      default: v35_cls_const = '0;")
    lines += ["    endcase", "  endfunction", ""]
    return "\n".join(lines)


def consts(gen: Gen) -> list:
    """[(name, value, comment)] of v35_consts.svh's integer localparams."""
    cfg = gen.cfg
    out = [("V35_HOLD_Q", cfg.hold_q, "hold_fetch=le_q: a posted data request holds fetches "
                                      "while queue bytes > Q"),
           ("V35_IO_B2B_Q", cfg.io_b2b_q, "io_b2b: the bytes stored below which an I/O form waits"),
           ("V35_WLATCH", cfg.wlatch, "the data latch's clocks"),
           ("V35_IO_RECOVER", cfg.io_recover, "clocks after an I/O cycle before a memory data cycle"),
           ("V35_ARBITER_Q", cfg.arbiter_q, "arbiter fetch_wins_le_q's Q"),
           ("V35_PER_SHIFT_COUNT", cfg.per_shift_count, "CNT source: clocks per shift count"),
           ("V35_LEA_FWB", cfg.c("lea", "fwb"), "lea_wb=fetch: write-back after the fetch's end"),
           ("V35_LOAD_ALU_FGRP", cfg.c("load_alu", "fgrp"), "fixed_floor: the lookup's clocks"),
           ("V35_RMW_ALU", cfg.c("rmw", "alu"), "refresh_rmw_span (refresh, unused refresh-off)"),
           ("V35_RMW_GRPCL", cfg.c("rmw", "grpcl"), "refresh_grpcl (refresh, unused refresh-off)"),
           ("V35_SHIFT_IMM_EXEC", cfg.c("shift_imm", "exec"), "refresh_rmw_span (refresh)")]
    for m in EA_MODES:
        out.append((f"V35_EA_{_ident(m)}", cfg.ea.get(m, 0) if m != "none" else 0,
                    f"EA table: {m}"))
    out += [("V35_N_ROWS", len(gen.rows), "microcode rows"),
            ("V35_N_TMPL", len(gen.templates), "templates"),
            ("V35_N_CLS", len(gen.classes), "classes (0: trap_nop)"),
            ("V35_ROW_BITS", ROW_BITS, "uc_row_t width"),
            ("V35_ROWA_BITS", ROWA_BITS, "row address width (rows <= 2048)"),
            ("V35_TMPL_BITS", TMPL_BITS, "template id width (templates <= 512)")]
    return out


def render_consts(gen: Gen) -> str:
    lines = _header(gen, "Constants: the EA table, hold_q, io_b2b_q, wlatch, io_recover, the "
                         "cross-class integers and the generated widths.")
    lines += ["// `include`d by v35_pkg.sv (package scope).", ""]
    lines.append(f'  localparam string V35_FIT_MD5 = "{gen.md5}";')
    for n, v, c in consts(gen):
        lines.append(f"  localparam int {n} = {v};  // {c}")
    lines.append("")
    lines.append("  // The EA clocks of an EA mode (v35_fmt_t.ea_mode).")
    lines.append("  function automatic int v35_ea_clocks(input logic [2:0] mode);")
    lines.append("    case (mode)")
    for i, m in enumerate(EA_MODES):
        lines.append(f"      3'd{i}: v35_ea_clocks = V35_EA_{_ident(m)};")
    lines.append("      default: v35_ea_clocks = 0;")
    lines += ["    endcase", "  endfunction", ""]
    lines.append("  // The EA mode of a ModR/M memory operand (mod != 3) under the fit's ea_direct"
                 f" ({gen.cfg.ea_direct}) and ea_disp16 ({gen.cfg.ea_disp16}).")
    lines.append("  function automatic logic [2:0] v35_ea_mode(input logic [1:0] md, "
                 "input logic [2:0] rm);")
    lines.append("    case ({md, rm})")
    for md in range(3):
        for rm in range(8):
            m = ea_mode_from(md, rm, gen.cfg)
            lines.append(f"      5'b{md:02b}{rm:03b}: v35_ea_mode = 3'd{EA_MODES.index(m)};  // {m}")
    lines.append("      default: v35_ea_mode = 3'd0;")
    lines += ["    endcase", "  endfunction", ""]
    return "\n".join(lines)


def render_pkg(gen: Gen) -> str:
    lines = _header(gen, "v35_pkg: the microcode row, the format word, the decode / class / "
                         "template tables (included) and v35_fmt_of / v35_tmpl_of.")
    lines += ["", "package v35_pkg;", ""]
    lines.append("  // ---- row field enums (ucgen.py OPS, NSRC, ASRC, WAITS, TAGS, ...) ----")
    for field, vals in ROW_ENUMS.items():
        tname, pre = ENUM_PREFIX[field]
        b = dict(ROW_FIELDS)[field]
        body = ", ".join(f"{pre}{v} = {b}'d{i}" for i, v in enumerate(vals))
        lines.append(f"  typedef enum logic [{b - 1}:0] {{{body}}} {tname};")
    lines.append("")
    lines.append(f"  // ---- the microcode row: {ROW_BITS} bits (ROW_FIELDS, MSB first here) ----")
    types = {f: ENUM_PREFIX[f][0] for f in ROW_ENUMS}
    lines += _sv_struct("uc_row_t", ROW_FIELDS, types)
    lines.append("")
    lines.append("  // ---- classes (0: trap_nop) ----")
    for i, k in enumerate(gen.classes):
        lines.append(f"  localparam logic [6:0] V35_CLS_{_ident(k)} = 7'd{i};")
    lines.append("")
    lines.append("  // ---- (S3) the datapath's operations (v35_fmt_t.xop) and operand roles (opa, "
                 "opb): ucgen.XOPS, ROLES ----")
    xb, rb = dict((n, b) for n, b, _ in XOP_ATTRS)["xop"], dict((n, b) for n, b, _ in XOP_ATTRS)["opa"]
    for i, v in enumerate(XOPS):
        lines.append(f"  localparam logic [{xb - 1}:0] V35_XOP_{v} = {xb}'d{i};")
    for i, v in enumerate(ROLES):
        lines.append(f"  localparam logic [{rb - 1}:0] V35_ROLE_{v} = {rb}'d{i};")
    # (S5a) the sub-operations (aop) of JMP / CALL / LOOP (the target), RET, STR
    for i, v in enumerate(XFER_KINDS):
        lines.append(f"  localparam logic [2:0] V35_XK_{v} = 3'd{i};")
    for i, v in enumerate(RET_KINDS):
        lines.append(f"  localparam logic [2:0] V35_RETK_{v} = 3'd{i};")
    for v, i in sorted(STR_OPS.items(), key=lambda kv: kv[1]):
        name = ("MOVBK", "CMPBK", "STM", "LDM", "CMPM", "INM", "OUTM")[i]
        lines.append(f"  localparam logic [2:0] V35_STR_{name} = 3'd{i};   // {v:02X}")
    lines.append("")
    lines.append("  // ---- decode table entries: a register-form half (hr: mod = 3 or no ModR/M)"
                 " and a memory-form half (hm) ----")
    lines += _sv_struct("v35_half_t", half_fields())
    lines += _sv_struct("v35_dec_t", dec_fields(), {"hr": "v35_half_t", "hm": "v35_half_t"})
    lines += _sv_struct("v35_grp_t", grp_fields(), {"hr": "v35_half_t", "hm": "v35_half_t"})
    lines.append("")
    lines.append("  // ---- the format word the loader holds for the running form ----")
    lines += _sv_struct("v35_fmt_t", fmt_fields())
    lines.append("  // ---- start-time bits (template selection): taken / zfail (the transfer's "
                 "decision), cnt0 (CL count 0),")
    lines.append("  //      half (the last operand byte is the even half of its word), n0 (a REP "
                 "/ BCD string with no element) ----")
    lines += _sv_struct("v35_run_t", RUN_FIELDS)
    cols, _ = class_table(gen)
    lines.append("  // ---- the class table row ----")
    lines += _sv_struct("v35_cls_t", cols)
    lines.append("")
    for f in ("v35_consts.svh", "v35_class_tbl.svh", "v35_decode_tbl.svh", "v35_ucode_tbl.svh"):
        lines.append(f'  `include "{f}"')
    lines.append("")
    lines += _fmt_of_sv().splitlines()
    lines.append("")
    tb = TMPL_BITS
    lines.append(f"  // The template a started form runs (v35_tmpl_sel, v35_ucode_tbl.svh).")
    lines.append(f"  function automatic logic [{tb - 1}:0] v35_tmpl_of(input v35_fmt_t f, "
                 f"input v35_run_t r);")
    lines.append("    v35_tmpl_of = v35_tmpl_sel(f, r);")
    lines.append("  endfunction")
    lines += ["", "endpackage", ""]
    return "\n".join(lines)


def _fmt_of_sv() -> str:
    attr_lines = "\n".join(f"    f.{n} = h.{n};" for n, _, _ in attrs())
    return f"""  // The format word of an instruction (mirrors ucgen.fmt_of). page: 0 native (opcode
  // the first byte), 1 the 0F page (opcode the second byte), 2 a REP prefix's string form
  // (opcode the string byte; the loader merges the prefix's repc from v35_dec_native(ir)).
  // modrm: the ModR/M byte (ignored for a form without one). An escape (0F, a REP prefix)
  // decoded on page 0 reports esc with class trap_nop.
  function automatic v35_fmt_t v35_fmt_of(input logic [7:0] opcode, input logic [1:0] page,
                                          input logic [7:0] modrm);
    v35_dec_t d;
    v35_grp_t g;
    v35_half_t h;
    v35_fmt_t f;
    logic hm;
    logic [1:0] md;
    logic [2:0] rf, rm;
    d = (page == 2'd1) ? v35_dec_ext(opcode) : v35_dec_native(opcode);
    hm = (page == 2'd2) ? 1'b0 : d.has_modrm;
    md = hm ? modrm[7:6] : 2'd0;
    rf = hm ? modrm[5:3] : 3'd0;
    rm = hm ? modrm[2:0] : 3'd0;
    if (d.grp_v) g = v35_dec_grp(d.gidx, rf);
    else begin
      g.hr = d.hr;
      g.hm = d.hm;
    end
    h = (hm && md != 2'd3) ? g.hm : g.hr;
    if (page == 2'd2 && !h.strop) h = '0;
    f = '0;
    f.page = page;
    f.esc = (page == 2'd0) ? d.esc : 2'd0;
    f.seg = d.seg;
    f.repc = d.repc;
    f.rep = (page == 2'd2);
    f.has_modrm = hm;
    f.md = md;
    f.rfield = rf;
    f.rm = rm;
    f.disp = (hm && md == 2'd1) ? 2'd1
           : (hm && (md == 2'd2 || (md == 2'd0 && rm == 3'd6))) ? 2'd2 : 2'd0;
    f.len = 3'd1 + {{2'd0, page != 2'd0}} + {{2'd0, hm}} + {{1'b0, f.disp}} + h.tail;
    f.valid = h.v;
    f.cls = h.cls;
    f.tail = h.tail;
    f.immb = h.immb;
    f.w = h.w;
    f.mem = h.mem;
    f.ea_mode = (h.mem && hm) ? v35_ea_mode(md, rm) : h.mem ? h.eafix : 3'd0;
    f.bix16 = hm && md == 2'd2 && !rm[2];
    f.ccode = h.cond ? opcode[3:0] : 4'd0;
{attr_lines}
    v35_fmt_of = f;
  endfunction"""


def render_all(gen: Gen) -> dict:
    return {"v35_ucode.hex": render_hex(gen), "v35_ucode_tbl.svh": render_ucode_tbl(gen),
            "v35_decode_tbl.svh": render_decode_tbl(gen),
            "v35_class_tbl.svh": render_class_tbl(gen), "v35_consts.svh": render_consts(gen),
            "v35_pkg.sv": render_pkg(gen),
            **{f"v35_ucode_b{b}.hex": render_bank_hex(gen, b) for b in range(ROM_BANKS)}}


def write(out_dir: Path, gen: Gen | None = None) -> dict:
    gen = gen or generate()
    files = render_all(gen)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out_dir / name).write_text(text)
    return files


def check(out_dir: Path = OUT_DIR) -> int:
    """Regenerate to a temporary directory and diff against out_dir; 1 on a difference."""
    with tempfile.TemporaryDirectory() as tmp:
        files = write(Path(tmp))
        bad = 0
        for name, text in files.items():
            p = out_dir / name
            old = p.read_text() if p.exists() else ""
            if old != text:
                bad += 1
                diff = difflib.unified_diff(old.splitlines(), text.splitlines(), str(p),
                                            "regenerated", lineterm="", n=1)
                for line in list(diff)[:30]:
                    print(line)
        if bad:
            print(f"{bad} generated file(s) drifted: regenerate with {INVOCATION}")
            return 1
    print(f"{out_dir} matches the fit")
    return 0


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog=INVOCATION, description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="regenerate to a temporary directory and diff; exit 1 on a difference")
    parser.add_argument("--out", type=Path, default=OUT_DIR,
                        help=f"output directory (default {OUT_DIR.relative_to(ROOT)})")
    return parser


def main(argv=None, args=None) -> int:
    if args is None:
        args = build_parser().parse_args(argv)
    if args.check:
        return check(args.out)
    gen = generate()
    files = write(args.out, gen)
    print(f"wrote {len(files)} files to {args.out}: {len(gen.rows)} rows x {ROW_BITS} bits, "
          f"{len(gen.templates)} templates, {len(gen.classes)} classes, {len(gen.forms)} forms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
