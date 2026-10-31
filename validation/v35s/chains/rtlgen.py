"""Generate the RTL's parameter include from the tracked fit (HDL plan, Phase C).

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains rtlgen [--check] [--out PATH]

writes fpga/v35s/core/v35_chain_params.svh from validation/v35s/chains/fit.json
(sim.config.FIT_PATH) and the frozen package (sim/frozen/, the fit's structure only):

- the integer-valued structural fields that the frozen code reads (`FIT_<FIELD>`), and every
  read structural field with its value as a comment (the structure is ported by hand, a
  mechanism per field; spec, "Plain structure, parameters, harness and unread fields").
  The fields no run reads under the fit (the frozen code has no `(fit)` site for them) and
  the dead state's field `refresh_io_pre` (it only feeds `eu.since_start`) are not emitted;
- the class integers (`Config.cost`: DEFAULT_COST merged with the fit, the shape
  `Config.c(cls, name)` reads) as `V35_C_<CLS>_<NAME>`, a case function `v35_cost` and its
  presence function `v35_cost_has` (the templates and the EU test `name in cost[cls]`);
- the EA table (`Config.ea`) as `V35_EA_<MODE>` and `v35_ea`;
- the per-class step lists (frozen `templates.steps` under the fit, and the
  `refresh_hold_steps` form a refresh-on chain runs): every template the frozen decoder can
  produce, enumerated over every opcode and ModR/M byte, with the operand addresses,
  the port and the target as symbolic sources and a shift count as a per-count coefficient,
  packed one step per word (`v35_step`, `v35_tmpl_len`), and the selection from the
  instruction's format word (`v35_tmpl_sel`);
- the bus unit's constants (frozen bus.py, machine.waits_of, types.refresh_length), the
  queue's (frozen queue.py: its storage and the request rule's word, `V35_QUEUE_*`) and the
  widths of the spec's A2 state table and of the queue's representations (`V35_W_*`).

The output is deterministic (sorted, no time stamp); its header names the md5 of fit.json.
`--check` regenerates and diffs against the file (exit 1 on drift); test_rtlgen does the
same. The include holds localparams and functions only: `include it inside each module body
that needs it (it has no include guard, so every module gets its own copy).
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "fpga" / "v35s" / "core" / "v35_chain_params.svh"
FROZEN = Path(__file__).resolve().parent / "sim" / "frozen"

# Dead state under the fit (spec, "Dead state and unread fields"; decisions): read by the
# frozen code but only to feed eu.since_start, which nothing reads.
DEAD_FIELDS = frozenset({"refresh_io_pre"})

# The spec's A2 widths (docs/v35s-chain-rtl-spec.md, "Bus unit" and "The variables that
# decide widths"), with the representation the bus unit uses. Each is checked against the
# values it must hold (check_widths) by test_rtlgen.
WIDTHS = {
    # bus unit (A2, "Bus unit")
    "KIND": 3,          # current.kind: none + 6 kinds
    "POS": 3,           # current position t - start: 0 .. length-1
    "LEN": 3,           # current.length: 3 .. 5 (3 + 2 waits; refresh 3 + RFW)
    "ADDR": 20,         # current.addr
    "BWIDTH": 2,        # current.width: word / lo / hi
    "DATA": 16,         # current.data
    "FETCH_SINCE": 4,   # last_fetch_end as clocks since it (0: not yet ended, 15: 15 or more);
                        # the spec's 1 bit is `== t-1`; F23's flush reads t <= end + fgap (5),
                        # (WP72) cond_gap=own's t <= end + cfgap (8): 4 bits since fit 40
    "IO_TAIL": 3,       # last_io_end: the recovery countdown (io_recover 2 + the disp_io clock)
    "GAP": 1,           # last_end beyond the cycle's own end: the disp_io clock (+ min_gap 0)
    "REFRESH_LEN": 3,   # refresh_length: 3 .. 5
    "WLATCH": 3,        # the data latch (wlatch 4 clocks), "All fit in 3-bit counters"
    "EARLY_N": 3,       # early_n (refresh_sync=run, C5)
    # the other machines (A2, "The variables that decide widths")
    "QUEUE_BYTES": 3,   # queue.bytes 0 .. 7 (6 stored + the latched byte)
    "ROOM": 4,          # the signed room -2 .. 7
    "STEP_K": 4,        # eu.k 0 .. 14
    "COUNT_LOOP": 9,    # a count loop's clocks (C0/C1 count byte 255: 510 clocks)
    "SETUP": 7,         # a request's setup and count 0 .. 87
    "HOLD_PHASE": 3,    # the hold phases
    # the queue's representations (v35_queue.sv, C2)
    "Q_COUNT": 4,       # len(queue.bytes) inside a clock: 6 stored + a word delivered (8)
    "Q_AGE": 7,         # requested_at as the request's age, saturating (A2: 7-bit, 99 observed)
    "Q_OFF": 10,        # retry_at / shift_until - t, signed: a count loop (9 bits) and a sign
    "Q_AR_OFF": 3,      # after_refresh - t while ahead: up to a refresh's length
    "Q_FH_OFF": 4,      # flush_held - t: a transfer's hold clocks
    "Q_AB_LEFT": 2,     # abort_end - t: the aborted cycle's clocks after its first
    "Q_LA_OFF": 2,      # lost_after - t: HALT's two status clocks (arbiter, refresh_lost)
    "Q_GD_OFF": 2,      # gdisp_until - t: grp_disp=hold's clocks (rmw.grp_free)
    "Q_LE_OFF": 2,      # (WP72) lea_ea's end - t: LDEA's EA clocks (lea_room=ir)
    "Q_SD_OFF": 4,      # (E3) str_held - t: a compare's chold clocks (str_hold=hold);
                        # (WP77) str_fetch=hold's xfetch clocks after the stream's last cycle
    "Q_SR_OFF": 3,      # (WP77) str_raise - t: str_fetch=hold's zfetch clocks (CW = 0)
    # (WP79) the 0F page and the register miscellany
    "CLS": 7,           # a class id (65 classes; CLS_NONE = 127)
    "NX": 3,            # the decoder's nx (a class's nx: rol4_mem 7)
    "RA_OFF": 5,        # ready_at - t: nx, or a one-byte form's nx0 (adjust_b 16), + io_take_nx
    "BF_COST": 12,      # a bit field's cost (templates.bf_cost of the whole offset and width
                        # registers: INS 128 + 4 (255 + 255 - 16) = 2104 at most)
}

# Bus-cycle kinds and widths as the bus unit encodes them.
KINDS = ("none", "fetch", "read", "write", "io_read", "io_write", "refresh")
BWIDTHS = ("word", "lo", "hi")

# Step encoding --------------------------------------------------------------------------

STEP_OPS = ("clocks", "take", "data", "post", "post_io", "issued", "wait", "nowait", "halt",
            "decide", "flush", "wbsync", "slot",      # wbsync / slot: inserted by the EU
            "fetch_hold",                             # (E3) str_hold=hold
            "fetch_release", "split_floor")           # (WP77) str_fetch=hold, str_split=floor
STEP_TAGS = ("none", "ea", "mexec", "exec", "loop", "tail", "loop_odd", "mexit",   # clocks
             "lead", "chain", "word", "chain_word", "port",                         # take
             "cfgap",       # flush: (WP72) cond_gap=own, the class's cfgap (else fgap)
             "forever",     # fetch_release: (WP77) ("fetch_release", None): no request from here
             "raise",       # fetch_release: (WP77) CW = 0: the aborted start's request raised
                            # again n clocks in (queue.str_raise); untagged: str_held = t + n
             "bf")          # clocks: (WP79) a bit field's cost formula's clocks less n
                            # (max(0, bf_cost - span), templates._wp78_steps)
REQ_KINDS = ("none", "read", "write", "io_read", "io_write", "nowrite")
ADDR_SRC = ("none", "ea", "stack_read", "stack_write", "port", "target",
            "ix", "iy")     # (E3) a string element's source (DS0:IX) and destination (DS1:IY)

# (name, bits): the packed step word, LSB first
STEP_FIELDS = (("op", 4), ("n", 8), ("per_count", 2), ("tag", 5), ("kind", 3), ("src", 3),
               ("src_i", 3), ("width", 2), ("has_free", 1), ("free", 5), ("grp", 1),
               ("whole", 1), ("detached", 1))

# Symbolic operand values substituted into an Op before its template is built.
SENT = {"ea": 0xA000, "stack_read": 0xB000, "stack_write": 0xC000, "port": 0xD000,
        "target": 0xE000, "ix": 0x1000, "iy": 0x3000}

EA_CLASSES = ("none", "base", "base_disp", "base_index", "base_index_disp",
              "base_index_disp16", "direct", "disp")

# The format word: the Op fields frozen templates.steps reads (besides the symbolic operands
# and the count), LSB first. Two Ops with one format word build one template (checked).
FMT_FIELDS = (("cls", 7), ("length", 3), ("imm_bytes", 2), ("has_ea", 1), ("modrm", 1),
              ("disp", 2), ("width", 2), ("ea_class", 3), ("signed", 1), ("group", 1),
              ("fixed_alu", 1), ("shift", 1), ("cl", 1), ("nowrite", 1), ("swap", 1),
              ("cond", 1), ("taken", 1), ("count_zero", 1), ("refresh", 1),
              ("cross", 1))     # (WP79) a bit field crosses into the next word (Op.bf)


class RtlgenError(RuntimeError):
    pass


class NotModelled(RtlgenError):
    """The decoder accepts the encoding but its template has no operand (e.g. 8F /0 with a
    register operand: no memory address): not a form the model runs."""


def _bits(n: int) -> int:
    return max(1, int(n).bit_length())


def _ident(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", name).upper()


# The fit ---------------------------------------------------------------------------------

# (WP77) Classes the RTL does not build yet: their templates are left out of the include (as the
# string classes were before E3), and so are their class ids and integers, so the RTL's class
# numbering is the built classes' sorted order; an instruction of one of them in a chain is not
# modelled (rtl_vectors: no template in the include). (WP79) None: the 0F page and the register
# miscellany (F32 / F33, the HDL plan's Phase E items 4 and 5) are built.
UNBUILT_CLASSES: frozenset = frozenset()


def rtl_cost(cfg) -> dict:
    """(WP77) the class integers of the classes the RTL builds (cfg.cost less UNBUILT_CLASSES)."""
    return {c: d for c, d in cfg.cost.items() if c not in UNBUILT_CLASSES}


def rtl_classes(cfg) -> list:
    """(WP77) the RTL's class ids: the built classes in sorted order."""
    return sorted(rtl_cost(cfg))


def fit_config():
    """(WP77) the fit as the frozen package holds it (sim/frozen/config.py: STRUCTURE, COST,
    EA): the Config the frozen model, the include and the vectors are built from. Not
    sim.config's merge of fit.json with its DEFAULT_COST, which the model side may extend
    (classes, integers) ahead of a freeze; the frozen package is the fit's."""
    import copy

    from .sim.frozen import config as fc
    return dataclasses.replace(fc.DEFAULT, cost=copy.deepcopy(fc.COST), ea=dict(fc.EA))


def load(fit_path: Path | None = None):
    """(md5 of fit.json, Config, {field: value} of the structural fields): the frozen
    package's fit (fit_config), checked to be fit.json's (the frozen package's sha256)."""
    from .sim.config import FIT_PATH
    from .sim.frozen import config as fc
    path = Path(fit_path) if fit_path is not None else FIT_PATH
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != fc.FIT_SHA256:
        raise RtlgenError(f"{path} is not the fit the frozen package was generated from "
                          f"(sha256 {fc.FIT_SHA256[:12]}): regenerate sim/frozen (freeze)")
    cfg = fit_config()
    structure = {k: getattr(cfg, k) for k in fc.STRUCTURE}
    return hashlib.md5(raw).hexdigest(), cfg, structure


def read_fields() -> dict:
    """{field: number of `# field = value (fit)` sites} over the frozen package."""
    sites: dict = {}
    for p in sorted(FROZEN.glob("*.py")):
        for m in re.finditer(r"# (\w+) = .+? \(fit\)", p.read_text()):
            sites[m.group(1)] = sites.get(m.group(1), 0) + 1
    return sites


# Templates -------------------------------------------------------------------------------

def _regs(z: int, cw: int) -> dict:
    sp = 0x0800
    return {"AW": 0x0005, "CW": cw, "DW": 0x00E0, "BW": 0x0100, "SP": sp, "BP": 0x0400,
            "IX": 0x0200, "IY": 0x0300, "Z": z, f"ret{sp:04X}": 0x0010}


def enumerate_ops():
    """Every distinct Op the frozen decoder makes of a two-byte head (opcode, ModR/M or
    first operand byte) with fixed trailing bytes, under both flag states and both DBNZ
    outcomes. Deterministic order."""
    from .sim.frozen.templates import decode
    seen = {}
    for b0 in range(256):
        for b1 in range(256):
            # (WP79) the 0F page: the ModR/M byte is the third, every value of it
            for b2 in (range(256) if b0 == 0x0F else (None,)):
                code = (bytes([b0, b1, b2, 0x02, 0x00, 0x00, 0x00, 0x00]) if b2 is not None
                        else bytes([b0, b1, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00]))
                for z, cw in ((0, 3), (1, 3), (0, 1)):
                    try:
                        op = decode(code, 0, _regs(z, cw))
                    except (ValueError, KeyError, IndexError):
                        continue
                    k = (op.cls, op.length, op.opcode, b1 if op.length > 1 else None,
                         b2 if b0 == 0x0F and op.length > 2 else None, op.target is not None)
                    if k not in seen:
                        seen[k] = (op, code[:op.length])
            if b0 in ONE_BYTE:
                break                       # no second byte read: one pass is enough
    return list(seen.values())


# opcodes the decoder reads no second byte of (only a speed-up of enumerate_ops)
ONE_BYTE = frozenset((0x06, 0x07, 0x0E, 0x16, 0x17, 0x1E, 0x1F, 0x26, 0x2E, 0x36, 0x3E, 0x50,
                      0x58, 0x59, 0x60, 0x61, 0x90, 0x92, 0xC3, 0xC9, 0xD7, 0xEC, 0xED, 0xEE,
                      0xEF, 0xF4))


def started(op, cfg):
    """The Op as the EU's _start builds its template from it (frozen eu.py): a CMP r/m,reg
    (the d = 0 load_alu form with a memory operand) does not write (dest_route=slot), and a
    form that does not write runs its group's read-modify-write class (grp_read). Without
    this the format word the EU selects with (cls rmw / rmw_imm, nowrite) has no template."""
    from .sim.frozen.templates import grp_class
    op = dataclasses.replace(op)
    if op.dbit == 0 and op.cls == "load_alu" and op.ea is not None:
        op.nowrite = True
    if op.nowrite:
        op.cls = grp_class(op, cfg)
    return op


def string_classes() -> frozenset:
    """(WP68, F24; E3) the string forms' classes (frozen templates.STRING_OPS). Their templates
    are string_template's: the step list frozen templates._string_steps builds, with the
    element-indexed addresses as symbolic sources (ix, iy, port) and, for a REP form, the
    element loop in the compact form the EU expands (expand_string)."""
    from .sim.frozen.templates import STRING_OPS
    return frozenset(STRING_OPS.values())


# (E3) The string forms. A form without a prefix builds its step list literally (one element,
# index 0). A REP form's list depends on the element count n (CW at the start) and, for a
# compare, on whether its condition ended the repeat (cond): frozen _string_steps is
#     take 1, nowait rpre, then  n == 0: fetch_release zfetch raise, clocks zexit
#                                n > 0: fetch_release (none from here), element 0 .. n-1,
#                                       [the overrun: element n's reads], fetch_release xfetch,
#                                       [split_floor xsplit], clocks rexit (cexit when cond)
#                                       less xwb
# with each element's cycles as data steps (the first with first / loop1 / loop by its index,
# the others mid), a compare's element followed by fetch_hold, and the last cycle of the
# element that runs CW out `last` clocks later. (WP77) The compact template the include holds is
#     0 take 1, 1 nowait rpre,                     (the head, STRING_HEAD rows)
#     2 .. : the rows of n == 0 (STRING_ZERO: fetch_release raise, clocks zexit),
#     then the rows before element 0 when n > 0 (STRING_PRE: fetch_release forever),
#     then the element rows of element 0, of element 1 and of element 2 (m rows each: its
#           cycles and the hold; element i >= 2 runs element 2's rows),
#     then the tail (t rows: fetch_release xfetch and, but after a single-read element,
#           split_floor), then clocks rexit and, for a compare, clocks cexit;
# the EU's step k (k flat, the model's index) is expand_string's: element
# i = (k - HEAD - PRE) // m, the address of its cycles IX / IY + i * the width (by DIR), the
# `last` clocks the class's.

STRING_HEAD = 2                     # take 1, nowait rpre
STRING_ZERO = 2                     # (WP77) n == 0: fetch_release zfetch raise, clocks zexit
STRING_PRE = 1                      # (WP77) n > 0, before element 0: fetch_release forever
STRING_SETS = 3                     # element rows: element 0, element 1, element >= 2


def _str_abstract(raw: tuple, w: int) -> tuple[dict, int]:
    """One step of frozen _string_steps on a symbolic Op -> (its field dict, element index;
    None for a step with no element address)."""
    k = raw[0]
    if k == "data":
        kind, addr, width, setup = raw[1:5]
        if len(raw) > 5:
            raise RtlgenError(f"string step {raw!r}")
        if addr == SENT["port"]:
            src, i = "port", None           # DW: the same port for every element
        else:
            src = next((n for n in ("ix", "iy") if 0 <= (addr - SENT[n]) % 0x10000 < 0x1000),
                       None)
            if src is None or ((addr - SENT[src]) % 0x10000) % w:
                raise RtlgenError(f"string step {raw!r}: not an element address")
            i = ((addr - SENT[src]) % 0x10000) // w
        return ({"op": "data", "kind": kind, "src": src, "src_i": 0, "width": width,
                 "n": (setup, 0)}, i)
    if k in ("clocks", "nowait", "take", "fetch_hold", "split_floor") and len(raw) == 2:
        return {"op": k, "n": (raw[1], 0)}, None
    if k == "fetch_release":                # (WP77) str_fetch=hold
        if len(raw) == 2 and raw[1] is None:
            return {"op": k, "tag": "forever", "n": (0, 0)}, None
        if len(raw) == 2:
            return {"op": k, "n": (raw[1], 0)}, None
        if len(raw) == 3 and raw[2] == "raise" and raw[1] is not None:
            return {"op": k, "tag": "raise", "n": (raw[1], 0)}, None
    raise RtlgenError(f"string step {raw!r}: not a string template step")


def _str_raw(op, cfg, n: int, cond: bool) -> list:
    from .sim.frozen.templates import steps
    o = dataclasses.replace(op, ix=SENT["ix"], iy=SENT["iy"],
                            port=None if op.port is None else SENT["port"], n=n, cond=cond)
    return [_str_abstract(st, op.width) for st in steps(o, cfg)]


def _row(d: dict) -> tuple:
    return tuple(sorted(d.items()))


def is_compare(cls: str) -> bool:
    from .sim.frozen.templates import STRING_COMPARES
    return cls in STRING_COMPARES


def string_template(op, cfg) -> tuple:
    """(E3) the template of a string form: without a prefix its step list (element 0); with
    one, the compact form above. Checked: expand_string gives frozen _string_steps' list for
    every n up to 6 and both exits, element by element."""
    if op.rep is None:
        seq = _str_raw(op, cfg, 1, False)
        if any(i for _, i in seq if i is not None):
            raise RtlgenError(f"{op.cls}: an unprefixed form's element is not element 0")
        return tuple(_row(d) for d, _ in seq)
    zero = _str_raw(op, cfg, 0, False)
    four = _str_raw(op, cfg, 4, False)
    m = len(four) - len(_str_raw(op, cfg, 3, False))       # an element's rows
    first = next((j for j, (d, _) in enumerate(four) if d["op"] == "data"), None)
    if (len(zero) != STRING_HEAD + STRING_ZERO or m < 1 or first != STRING_HEAD + STRING_PRE
            or [d for d, _ in zero[:STRING_HEAD]] != [d for d, _ in four[:STRING_HEAD]]):
        raise RtlgenError(f"{op.cls}: the REP form's list is not the string template's shape")
    c = sum(1 for d, _ in four[first:first + m] if d["op"] == "data")
    ovr = c if is_compare(op.cls) else 0
    tail = len(four) - (first + 4 * m + ovr) - 1
    if tail < 0:
        raise RtlgenError(f"{op.cls}: the REP form's list is not the string template's shape")
    rows = ([d for d, _ in four[:STRING_HEAD]] + [d for d, _ in zero[STRING_HEAD:]]
            + [d for d, _ in four[STRING_HEAD:first]])
    for i in range(STRING_SETS):
        el = four[first + i * m:first + (i + 1) * m]
        if any(j not in (i, None) for _, j in el):
            raise RtlgenError(f"{op.cls}: element {i}'s rows are not element {i}'s")
        rows += [d for d, _ in el]
    rows += [d for d, _ in four[len(four) - 1 - tail:len(four) - 1]]   # the tail
    rows.append(four[-1][0])                                    # rexit
    if is_compare(op.cls):
        rows.append(_str_raw(op, cfg, 4, True)[-1][0])          # cexit
    tm = tuple(_row(d) for d in rows)
    if string_shape(tm, op.cls) != (m, c, tail):
        raise RtlgenError(f"{op.cls}: the compact template's shape does not read back")
    for n in range(7):
        for cond in ((False, True) if is_compare(op.cls) and n else (False,)):
            want = [(_row(d), i) for d, i in _str_raw(op, cfg, n, cond)]
            got = expand_string(tm, op.cls, cfg.c(op.cls, "last"), n, cond)
            got = [(r, i if dict(r)["op"] == "data" and dict(r)["src"] != "port" else None)
                   for r, i in got]
            if want != got:
                raise RtlgenError(f"{op.cls}: the compact template does not expand to "
                                  f"_string_steps at n={n} cond={cond}")
    return tm


def _str_base() -> int:
    """(WP77) the compact template's first element row."""
    return STRING_HEAD + STRING_ZERO + STRING_PRE


def string_shape(tm: tuple, cls: str) -> tuple[int, int, int]:
    """(rows per element m, data rows per element c, tail rows t) of a REP form's compact
    template: the tail's rows follow the element rows, the first of them the tail's
    fetch_release (a fetch_release row with no forever / raise tag)."""
    base = _str_base()
    ex = 2 if is_compare(cls) else 1
    body = len(tm) - base - ex                  # STRING_SETS * m + t
    for t in range(0, 3):
        if (body - t) % STRING_SETS or body - t < STRING_SETS:
            continue
        m = (body - t) // STRING_SETS
        tr = tm[base + STRING_SETS * m:base + STRING_SETS * m + t]
        if t and (dict(tr[0])["op"] != "fetch_release" or dict(tr[0]).get("tag")):
            continue
        if not t and m and dict(tm[base + STRING_SETS * m - 1])["op"] == "fetch_release":
            continue
        c = sum(1 for r in tm[base:base + m] if dict(r)["op"] == "data")
        return m, c, t
    raise RtlgenError(f"{cls}: not a compact string template")


def expand_string(tm: tuple, cls: str, last: int, n: int, cond: bool) -> list:
    """(E3) a REP form's step list from its compact template, as the EU expands it (eu_step):
    [(row, element index)]. The model's step k is the list's k-th."""
    m, c, t = string_shape(tm, cls)
    out = [(tm[j], 0) for j in range(STRING_HEAD)]
    if not n:
        return out + [(tm[STRING_HEAD + j], 0) for j in range(STRING_ZERO)]
    out += [(tm[STRING_HEAD + STRING_ZERO + j], 0) for j in range(STRING_PRE)]
    base = _str_base()
    for i in range(n):
        for j in range(m):
            d = dict(tm[base + min(i, STRING_SETS - 1) * m + j])
            if j == c - 1 and i == n - 1 and not cond and last:
                d["n"] = (d["n"][0] + last, 0)
            out.append((_row(d), i))
    if is_compare(cls):
        for j in range(c):
            out.append((tm[base + min(n, STRING_SETS - 1) * m + j], n))
    x = base + STRING_SETS * m
    out += [(tm[x + j], 0) for j in range(t)]
    return out + [(tm[x + t + (1 if cond else 0)], 0)]


# (WP79) The BCD strings (ADD4S / SUB4S / CMP4S, frozen templates._wp78_steps): pre clocks, the
# second opcode byte's take, per byte pair i a byte read at IX + i (setup first, later pairs
# loop), a byte read at IY + i (mid) and, ADD4S / SUB4S, the result written at IY + i (wmid), then
# exec clocks; n pairs, (CL + 1) / 2 from the register file (the model: the walk's). The compact
# template the include holds is
#     0 clocks pre, 1 take 1,                      (BCD_HEAD rows)
#     the rows of pair 0, the rows of pair >= 1    (m rows each, BCD_SETS sets),
#     clocks exec;
# the EU's step k (the model's flat index) is expand_bcd's: pair i = (k - BCD_HEAD) // m, the
# addresses IX / IY + i (always upward), its rows pair 0's or pair 1's.
BCD_HEAD = 2
BCD_SETS = 2


def bcd_classes() -> frozenset:
    from .sim.frozen.templates import BCD_CLASSES
    return frozenset(BCD_CLASSES)


def bf_classes() -> frozenset:
    from .sim.frozen.templates import BF_CLASSES
    return frozenset(BF_CLASSES)


def _bcd_raw(op, cfg, n: int) -> list:
    from .sim.frozen.templates import steps
    o = dataclasses.replace(op, ix=SENT["ix"], iy=SENT["iy"], n=n, cond=False)
    return [_str_abstract(st, 1) for st in steps(o, cfg)]


def bcd_template(op, cfg) -> tuple:
    """(WP79) the compact template of a BCD string (above). Checked: expand_bcd gives frozen
    _wp78_steps' list for every n up to 6, pair by pair."""
    two, three = _bcd_raw(op, cfg, 2), _bcd_raw(op, cfg, 3)
    m = len(three) - len(two)
    if m < 1 or len(two) != BCD_HEAD + BCD_SETS * m + 1:
        raise RtlgenError(f"{op.cls}: the BCD string's list is not the compact template's shape")
    tm = tuple(_row(d) for d, _ in two)
    for n in range(7):
        want = [(_row(d), i if i is not None else 0) for d, i in _bcd_raw(op, cfg, n)]
        if want != expand_bcd(tm, n):
            raise RtlgenError(f"{op.cls}: the compact template does not expand to _wp78_steps "
                              f"at n={n}")
    return tm


def bcd_shape(tm: tuple) -> int:
    """(WP79) the rows per byte pair of a BCD string's compact template."""
    return (len(tm) - BCD_HEAD - 1) // BCD_SETS


def expand_bcd(tm: tuple, n: int) -> list:
    """(WP79) a BCD string's step list from its compact template, as the EU expands it:
    [(row, pair index)]."""
    m = bcd_shape(tm)
    out = [(tm[j], 0) for j in range(BCD_HEAD)]
    for i in range(n):
        out += [(tm[BCD_HEAD + min(i, BCD_SETS - 1) * m + j], i) for j in range(m)]
    return out + [(tm[-1], 0)]


# (WP79) The bit fields (EXT, INS: frozen templates._wp78_steps): the word reads and writes at IX /
# IY (+ 2 for the next word, a symbolic source's src_i) and one clocks step whose count is the cost
# formula's (templates.bf_cost of the offset and width registers) less a class integer, max(0, ...):
# the step's tag "bf" with that integer as n; the EU computes the rest (v35_bf_cost). Whether the
# field crosses into the next word (Op.bf[2]) is the format's cross.
BF_SENT = 4000


def bf_template(op, cfg) -> tuple:
    """(WP79) the template of a bit field with the crossing op.bf[2]: frozen steps with the cost
    symbolic (the step that moves with it becomes ("clocks", tag bf, n = cost - its count))."""
    from .sim.frozen.templates import steps

    def raw(cost):
        o = dataclasses.replace(op, ix=SENT["ix"], iy=SENT["iy"],
                                bf=(op.bf[0], op.bf[1], op.bf[2], cost))
        return steps(o, cfg)
    a, b = raw(BF_SENT), raw(2 * BF_SENT)
    if len(a) != len(b):
        raise RtlgenError(f"{op.cls}: the bit field's template changes shape with its cost")
    out, moved = [], 0
    for x, y in zip(a, b):
        if x == y:
            d = abstract(x)
            for k in ("n", "free"):
                if k in d and isinstance(d[k], int) and not isinstance(d[k], bool):
                    d[k] = (d[k], 0)
        elif x[0] == "clocks" and len(x) == 2 and y[1] - x[1] == BF_SENT and 0 <= BF_SENT - x[1] < 256:
            d = {"op": "clocks", "tag": "bf", "n": (BF_SENT - x[1], 0)}
            moved += 1
        else:
            raise RtlgenError(f"{op.cls}: step {x!r} moves with the cost but not as its clocks")
        out.append(tuple(sorted(d.items())))
    if moved != 1:
        raise RtlgenError(f"{op.cls}: {moved} steps carry the bit field's cost")
    return tuple(out)


def has_count(op) -> bool:
    return op.cls in ("shift_imm", "shift_cl") or op.shift


def fmt_of(op, cfg, count_zero: bool, refresh: bool) -> dict:
    from .sim.frozen.templates import ea_class
    return {"cls": op.cls, "length": op.length, "imm_bytes": op.imm_bytes,
            "has_ea": op.ea is not None, "modrm": op.modrm, "disp": op.disp,
            "width": op.width,
            "ea_class": (ea_class(op, cfg) if op.ea is not None else None) or "none",
            "signed": op.signed, "group": op.group, "fixed_alu": op.fixed_alu,
            "shift": op.shift, "cl": op.opcode in (0xD2, 0xD3), "nowrite": op.nowrite,
            "swap": op.swap, "taken": op.target is not None,
            # (E3) a string form's cond is the walk's exit (Op.cond), not a format property;
            # (WP79) nor a BCD string's
            "cond": op.cond and op.cls not in string_classes() and op.cls not in bcd_classes(),
            "count_zero": count_zero, "refresh": refresh,
            "cross": bool(op.bf is not None and op.bf[2])}


def _symbolic(op):
    s0, s1 = op.stack if op.stack else (None, None)
    return dataclasses.replace(
        op, ea=None if op.ea is None else SENT["ea"],
        stack=() if not op.stack else (None if s0 is None else SENT["stack_read"],
                                       None if s1 is None else SENT["stack_write"]),
        port=None if op.port is None else SENT["port"],
        target=None if op.target is None else SENT["target"])


def _raw_steps(op, cfg, refresh: bool, count: int) -> list:
    from .sim.frozen.templates import refresh_hold_steps, steps
    o = dataclasses.replace(_symbolic(op), count=count)
    seq = steps(o, cfg)
    if refresh:
        seq = refresh_hold_steps(o, cfg, seq)
    return seq


def _addr(v):
    """A symbolic operand value -> (source, index)."""
    if v is None:
        raise NotModelled("a request without an address")
    for name in ("ea", "port", "target"):
        if v == SENT[name]:
            return name, 0
    if SENT["stack_read"] <= v <= SENT["stack_read"] + 14 and not (v - SENT["stack_read"]) % 2:
        return "stack_read", (v - SENT["stack_read"]) // 2
    if SENT["stack_write"] - 14 <= v <= SENT["stack_write"] and not (SENT["stack_write"] - v) % 2:
        return "stack_write", (SENT["stack_write"] - v) // 2
    for name in ("ix", "iy"):           # (WP79) a bit field's words: IX / IY + 2 * src_i
        if SENT[name] <= v <= SENT[name] + 14 and not (v - SENT[name]) % 2:
            return name, (v - SENT[name]) // 2
    raise RtlgenError(f"operand value {v:#x} is not a symbolic source")


def _req(step: dict, kind, addr, width, setup):
    step["kind"] = kind
    step["src"], step["src_i"] = _addr(addr)
    step["width"] = width
    step["n"] = setup


def abstract(raw: tuple) -> dict:
    """One raw step tuple -> its field dict (STEP_FIELDS names; n may be a count pair)."""
    s = {"op": raw[0]}
    k = raw[0]
    if k not in STEP_OPS:
        raise RtlgenError(f"unknown step {raw!r}")
    if k in ("clocks", "nowait"):
        s["n"] = raw[1]
        if len(raw) > 2:
            s["tag"] = raw[2]
        if len(raw) > 3:
            raise RtlgenError(f"step {raw!r}")
    elif k == "take":
        s["n"] = raw[1]
        if len(raw) > 2:
            s["tag"] = raw[2]
        if len(raw) > 2 and raw[2] == "port":
            kind, port, width, setup = raw[3]
            _req(s, kind, port, width, setup)
            s["detached"] = bool(raw[4])
        elif len(raw) > 3:
            raise RtlgenError(f"step {raw!r}")
    elif k in ("data", "post", "post_io"):
        _req(s, raw[1], raw[2], raw[3], raw[4])
        if len(raw) > 5 and raw[5] is not None:
            s["has_free"], s["free"] = True, raw[5]
        if len(raw) > 6:
            s["grp"] = bool(raw[6])
        if len(raw) > 7:
            s["whole"] = bool(raw[7])
        if len(raw) > 8:
            raise RtlgenError(f"step {raw!r}")
    elif k == "flush":
        s["src"], s["src_i"] = _addr(raw[1])
        if len(raw) > 2:
            if raw[2] != "cfgap" or len(raw) > 3:
                raise RtlgenError(f"step {raw!r}")
            s["tag"] = "cfgap"          # (WP72) cond_gap=own: the flush waits cfgap
    elif len(raw) > 1:
        raise RtlgenError(f"step {raw!r}")
    return s


def template(op, cfg, refresh: bool, count_zero: bool) -> tuple:
    """The abstract template of op: a tuple of step dicts frozen as sorted item tuples, each
    integer field as (base, per_count). Counts 1, 2, 3 fix the per-count coefficient (a
    shift's clocks are linear in its count); count_zero builds the count-0 form literally."""
    if not has_count(op):
        seqs = {0: _raw_steps(op, cfg, refresh, op.count)}
        counts = None
    elif count_zero:
        seqs = {0: _raw_steps(op, cfg, refresh, 0)}
        counts = None
    else:
        seqs = {c: _raw_steps(op, cfg, refresh, c) for c in (1, 2, 3, 7)}
        counts = (1, 2, 3, 7)
    first = [abstract(s) for s in seqs[counts[0] if counts else 0]]
    out = []
    for i, st in enumerate(first):
        row = {}
        for name, v in st.items():
            if isinstance(v, bool) or not isinstance(v, int) or name not in ("n", "free"):
                row[name] = v
                continue
            if counts is None:
                row[name] = (v, 0)
                continue
            vals = []
            for c in counts:
                other = abstract(seqs[c][i]) if i < len(seqs[c]) else None
                if other is None or len(seqs[c]) != len(first):
                    raise RtlgenError(f"{op.cls}: the template's shape changes with the count")
                vals.append(other[name])
            b = vals[1] - vals[0]
            base = vals[0] - b * counts[0]
            if any(vals[j] != base + b * c for j, c in enumerate(counts)):
                raise RtlgenError(f"{op.cls}: step {i} field {name} is not linear in the count")
            row[name] = (base, b)
        for c in (counts or ())[1:]:
            other = abstract(seqs[c][i])
            if {k: v for k, v in other.items() if k not in ("n", "free")} != \
                    {k: v for k, v in st.items() if k not in ("n", "free")}:
                raise RtlgenError(f"{op.cls}: step {i} changes with the count")
        out.append(tuple(sorted(row.items())))
    return tuple(out)


def templates(cfg) -> tuple[list, dict, dict]:
    """(templates in id order, {format key tuple: template id}, {template id: example
    (class, encoding hex)}) over every decodable Op, both refresh forms."""
    ids: dict = {}
    order: list = []
    sel: dict = {}
    example: dict = {}
    for op, code in enumerate_ops():
        op = started(op, cfg)
        if op.cls in UNBUILT_CLASSES:
            continue                            # (WP77) not built: no template
        variants = None
        if op.cls in bcd_classes():
            variants = [(bcd_template(op, cfg), op)]   # (WP79) refresh_hold_steps leaves it
        elif op.cls in bf_classes():
            variants = []                       # (WP79) both crossings, the cost symbolic
            for cross in (False, True):
                o = dataclasses.replace(op, bf=(0, 0, cross, BF_SENT))
                variants.append((bf_template(o, cfg), o))
        if variants is not None:
            for tm, o in variants:
                for refresh in (False, True):
                    key = tuple(fmt_of(o, cfg, False, refresh)[n] for n, _ in FMT_FIELDS)
                    if tm not in ids:
                        ids[tm] = len(order)
                        order.append(tm)
                        tags = [t for t, on in (("cross", o.bf is not None and o.bf[2]),
                                                ("refresh", refresh)) if on]
                        example[ids[tm]] = (o.cls, code.hex(" ") + "".join(f", {t}" for t in tags))
                    if key in sel and sel[key] != ids[tm]:
                        raise RtlgenError(f"format {key} builds two templates ({code.hex(' ')})")
                    sel[key] = ids[tm]
            continue
        if op.cls in string_classes():
            tm = string_template(op, cfg)       # (E3) refresh_hold_steps leaves it as it is
            for refresh in (False, True):
                key = tuple(fmt_of(op, cfg, False, refresh)[n] for n, _ in FMT_FIELDS)
                if tm not in ids:
                    ids[tm] = len(order)
                    order.append(tm)
                    example[ids[tm]] = (op.cls, code.hex(" ") + (", refresh" if refresh else ""))
                if key in sel and sel[key] != ids[tm]:
                    raise RtlgenError(f"format {key} builds two templates ({code.hex(' ')})")
                sel[key] = ids[tm]
            continue
        for refresh in (False, True):
            zs = (False, True) if has_count(op) else (False,)
            for cz in zs:
                try:
                    tm = template(op, cfg, refresh, cz)
                except NotModelled:
                    continue
                key = tuple(fmt_of(op, cfg, cz, refresh)[n] for n, _ in FMT_FIELDS)
                if tm not in ids:
                    ids[tm] = len(order)
                    order.append(tm)
                    tags = [t for t, on in (("taken", op.target is not None),
                                            ("count 0", cz), ("refresh", refresh)) if on]
                    example[ids[tm]] = (op.cls, code.hex(" ") + "".join(f", {t}" for t in tags))
                if key in sel and sel[key] != ids[tm]:
                    raise RtlgenError(f"format {dict(zip([n for n, _ in FMT_FIELDS], key))} "
                                      f"builds two templates ({code.hex(' ')})")
                sel[key] = ids[tm]
    # renumber by (class, first example) for a stable, readable order
    rank = sorted(range(len(order)), key=lambda i: (example[i][0], example[i][1],
                                                     repr(order[i])))
    new = {old: n for n, old in enumerate(rank)}
    order = [order[i] for i in rank]
    sel = {k: new[v] for k, v in sorted(sel.items(), key=lambda kv: repr(kv[0]))}
    example = {new[i]: e for i, e in example.items()}
    return order, sel, example


def pack_step(st: tuple) -> int:
    d = dict(st)
    word, off = 0, 0
    for name, bits in STEP_FIELDS:
        v = d.get(name, 0)
        if name == "op":
            v = STEP_OPS.index(v)
        elif name == "tag":
            v = STEP_TAGS.index(v) if v else 0
        elif name == "kind":
            v = REQ_KINDS.index(v) if v else 0
        elif name == "src":
            v = ADDR_SRC.index(v) if v else 0
        elif name == "n":
            v = d.get("n", (0, 0))
            v = v[0] if isinstance(v, tuple) else v
        elif name == "per_count":
            n = d.get("n", (0, 0))
            v = n[1] if isinstance(n, tuple) else 0
            f = d.get("free", (0, 0))
            if isinstance(f, tuple) and f[1]:
                raise RtlgenError("a free override depends on the count")
        elif name == "free":
            f = d.get("free", (0, 0))
            v = f[0] if isinstance(f, tuple) else f
        v = int(v)
        if v < 0 or v >= 1 << bits:
            raise RtlgenError(f"step field {name}={v} does not fit {bits} bits ({d})")
        word |= v << off
        off += bits
    return word


def pack_fmt(key: tuple, classes: list) -> int:
    """A format key (FMT_FIELDS order) as the format word; classes: the class order."""
    word, off = 0, 0
    for (name, bits), v in zip(FMT_FIELDS, key):
        if name == "cls":
            v = classes.index(v)
        elif name == "ea_class":
            v = EA_CLASSES.index(v)
        v = int(v)
        if v < 0 or v >= 1 << bits:
            raise RtlgenError(f"format field {name}={v} does not fit {bits} bits")
        word |= v << off
        off += bits
    return word


# Bus-unit constants ----------------------------------------------------------------------

def bus_constants() -> dict:
    """The frozen bus unit's constants, and the WTC/RFM field reads probed from the frozen
    code (machine.waits_of, types.refresh_length), so a change there shows here."""
    from types import SimpleNamespace

    from .sim.frozen import bus
    from .sim.frozen.machine import waits_of
    from .types import refresh_length
    for f in range(8):
        for v in range(4):
            mem, io = waits_of(SimpleNamespace(wtc=v << (2 * f)))
            if mem != (v if f == 0 else 0) or io != (v if f == 7 else 0):
                raise RtlgenError("waits_of no longer reads WTC field 0 (memory) and field 7 "
                                  "(I/O) as the bus unit's waits")
    lengths = [refresh_length(rfw << 2) for rfw in range(4)]
    for rfw in range(4):
        for other in (0x00, 0x13, 0xF3):
            if refresh_length((rfw << 2) | other) != lengths[rfw]:
                raise RtlgenError("types.refresh_length reads more than RFM.RFW")
    # (C5) RFM.RFEN and RFM.RFT as types.refresh_on / refresh_rft read them
    from .types import refresh_on, refresh_rft
    rfen = [b for b in range(8) if refresh_on(1 << b)]
    if len(rfen) != 1 or any(refresh_on(v) != bool(v >> rfen[0] & 1) for v in range(256)):
        raise RtlgenError("types.refresh_on is not one RFM bit")
    if any(refresh_rft(v) != v & 3 for v in range(256)):
        raise RtlgenError("types.refresh_rft no longer reads RFM bits 1-0")
    return {"BASE": bus.BASE, "SFR_PAGE": bus.SFR_PAGE, "REFRESH_LENGTH": bus.REFRESH_LENGTH,
            "REFRESH_LENGTHS": lengths, "RFEN_BIT": rfen[0]}


def prelude_constants() -> dict:
    """(C4) the prelude's POP PSW stack read that Machine.__init__ issues on the model's clock 0
    (prelude_anchor=pop): its address and datum (image.py), for the core's start."""
    from .image import PRELUDE_MARKER_STACK, PSW
    return {"POP_ADDR": PRELUDE_MARKER_STACK, "PSW": PSW}


def regfile_constants() -> dict:
    """(D1) the register file's constants from the frozen templates.execute: the word every
    memory read returns (the data fill, types.DATA_FILL's bytes)."""
    from .sim.frozen import templates
    return {"FILL_WORD": templates.FILL_WORD}


def queue_constants() -> dict:
    """The frozen queue's constants (queue.py): its storage and the request rule's word."""
    from .sim.frozen import queue
    return {"BYTES": queue.QUEUE_BYTES, "WORD": queue.WORD}


def check_widths(cfg, structure, tmpls) -> list[str]:
    """Problems with WIDTHS against the values they must hold (empty: none)."""
    bad = []
    bc = bus_constants()
    max_len = bc["BASE"] + 3                                  # WTC field value 3: 3 waits
    need = {"KIND": len(KINDS) - 1, "POS": max_len - 1, "LEN": max(max_len, *bc["REFRESH_LENGTHS"]),
            "BWIDTH": len(BWIDTHS) - 1, "ADDR": 0xFFFFF, "DATA": 0xFFFF,
            "FETCH_SINCE": 1 + max(cfg.c(c, n) for c in rtl_cost(cfg)
                                   for n in ("fgap", "nfgap", "cfgap")),
            "IO_TAIL": structure["io_recover"] + 1,
            "GAP": structure["min_gap"] + 1,
            "REFRESH_LEN": max(bc["REFRESH_LENGTHS"]), "WLATCH": structure["wlatch"],
            # + the EU's wbsync; (WP77) not a REP string form's compact template, whose
            # cursor is the flat index (eu.k 18 bits, E3) and whose rows reach 18
            "STEP_K": max(len(t) for t in tmpls
                          if not any(dict(r)["op"] == "fetch_release" for r in t)) + 1,
            "Q_COUNT": queue_constants()["BYTES"] + queue_constants()["WORD"],
            "Q_AR_OFF": max(bc["REFRESH_LENGTHS"]),
            "Q_FH_OFF": max(cfg.c(c, "hold") for c in rtl_cost(cfg)),
            "Q_AB_LEFT": bc["BASE"] - 1, "Q_LA_OFF": 2, "Q_GD_OFF": cfg.c("rmw", "grp_free"),
            "Q_LE_OFF": max(cfg.ea.values()) + cfg.c("lea", "exec"),
            "Q_SD_OFF": max(cfg.c(c, n) for c in rtl_cost(cfg) for n in ("chold", "xfetch")),
            "Q_SR_OFF": max(cfg.c(c, "zfetch") for c in rtl_cost(cfg)),
            # (WP79) the class ids and CLS_NONE (all ones), the decoder's nx and ready_at - t (a
            # one-byte form's nx0; io_take_nx adds a clock), the bit field's cost
            "CLS": len(rtl_classes(cfg)),
            "NX": max(cfg.c(c, "nx") for c in rtl_cost(cfg)),
            "RA_OFF": 1 + max(cfg.c(c, n) for c in rtl_cost(cfg) for n in ("nx", "nx0")),
            "BF_COST": max(_bf_cost_max())}
    for k, v in need.items():
        if v >= 1 << WIDTHS[k]:
            bad.append(f"V35_W_{k}={WIDTHS[k]} cannot hold {v}")
    # signed: an offset of a whole count loop either way
    if 1 << WIDTHS["COUNT_LOOP"] > 1 << (WIDTHS["Q_OFF"] - 1):
        bad.append(f"V35_W_Q_OFF={WIDTHS['Q_OFF']} cannot hold a count loop's clocks signed")
    return bad


def _bf_cost_max() -> list:
    """(WP79) the bit fields' costs over every offset and width register value."""
    from .sim.frozen.templates import BF_CLASSES, bf_cost
    return [bf_cost(c, o, w) for c in BF_CLASSES for o in range(256) for w in range(256)]


# Rendering -------------------------------------------------------------------------------

def _sv_int(v) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    return str(int(v))


def render(fit_path: Path | None = None) -> str:
    md5, cfg, structure = load(fit_path)
    sites = read_fields()
    read = {k for k in structure if k in sites and k not in DEAD_FIELDS}
    unread = sorted(set(structure) - read)
    classes = rtl_classes(cfg)
    cost = rtl_cost(cfg)                    # (WP77) the built classes' integers
    tmpls, sel, example = templates(cfg)
    bad = check_widths(cfg, structure, tmpls)
    if bad:
        raise RtlgenError("; ".join(bad))
    bc = bus_constants()
    L: list[str] = []
    w = L.append
    rel = "validation/v35s/chains/fit.json"
    w("// Generated by validation/v35s/chains/rtlgen.py from " + rel)
    w(f"// (md5 {md5}); do not edit.")
    w("// Regenerate: PYTHONPATH=host/src:. python3 -m validation.v35s.chains rtlgen")
    w("// Check:      PYTHONPATH=host/src:. python3 -m validation.v35s.chains rtlgen --check")
    w("//")
    w("// Localparams and functions only: `include inside each module body that needs them.")
    w("// Spec: docs/v35s-chain-rtl-spec.md (A2 widths, A4 fields); plan: docs/v35s-hdl-plan.md.")
    w("")
    w(f"localparam string V35_FIT_MD5 = \"{md5}\";")
    w("")
    # structure
    w(f"// ---- Structural fields read under the fit ({len(read)} of {len(structure)}) ----")
    w("// Enum fields are ported by hand as the mechanism the value names (no parameter);")
    w("// integer fields are parameters below. Not emitted (read by no run under the fit,")
    w("// or dead state):")
    for i in range(0, len(unread), 6):
        w("//   " + ", ".join(unread[i:i + 6]))
    for k in sorted(read):
        v = structure[k]
        if isinstance(v, bool) or not isinstance(v, int):
            w(f"//   {k} = {v!r}")
    for k in sorted(read):
        v = structure[k]
        if isinstance(v, int) and not isinstance(v, bool):
            w(f"localparam int FIT_{_ident(k)} = {v};")
    w("")
    # bus unit
    w("// ---- Bus unit (frozen bus.py, machine.waits_of, types.refresh_length) ----")
    w(f"localparam int V35_BUS_BASE = {bc['BASE']};            // B1 B2 B3")
    w("// the on-chip SFR store (sfr_cycle=io): a write at or above this, no pins")
    w(f"localparam logic [19:0] V35_SFR_PAGE = 20'h{bc['SFR_PAGE']:05X};")
    w(f"localparam int V35_REFRESH_LENGTH = {bc['REFRESH_LENGTH']};      // RFM FCh")
    w("localparam int V35_WTC_MEM_LSB = 0;    // WTC field 0: memory (block 0) and fetches")
    w("localparam int V35_WTC_IO_LSB = 14;    // WTC field 7: I/O and the SFR store")
    w("localparam int V35_DISP_IO_EXT = 1;    // disp_io=extend: last_end, last_io_end + 1")
    w("function automatic logic [2:0] v35_refresh_length(input logic [7:0] value);")
    w("    case (value[3:2])")
    for rfw, n in enumerate(bc["REFRESH_LENGTHS"]):
        w(f"        2'd{rfw}: v35_refresh_length = 3'd{n};")
    w("    endcase")
    w("endfunction")
    w("// (C5) RFM.RFEN (types.refresh_on); RFM.RFT is bits 1-0 (types.refresh_rft)")
    w("function automatic logic v35_refresh_on(input logic [7:0] value);")
    w(f"    v35_refresh_on = value[{bc['RFEN_BIT']}];")
    w("endfunction")
    pc = prelude_constants()
    w("// the prelude's POP PSW stack read, issued on the model's clock 0 (prelude_anchor=pop)")
    w(f"localparam logic [19:0] V35_PRELUDE_POP_ADDR = 20'h{pc['POP_ADDR']:05X};")
    w(f"localparam logic [15:0] V35_PRELUDE_PSW = 16'h{pc['PSW']:04X};")
    rc = regfile_constants()
    w("// (D1) the register file (frozen templates.execute): every memory read's word")
    w(f"localparam logic [15:0] V35_FILL_WORD = 16'h{rc['FILL_WORD']:04X};")
    for i, k in enumerate(KINDS):
        w(f"localparam logic [2:0] V35_K_{_ident(k)} = 3'd{i};")
    for i, k in enumerate(BWIDTHS):
        w(f"localparam logic [1:0] V35_BW_{_ident(k)} = 2'd{i};")
    w("")
    qc = queue_constants()
    w("// ---- Queue (frozen queue.py) ----")
    w(f"localparam int V35_QUEUE_BYTES = {qc['BYTES']};          // physical storage")
    w(f"localparam int V35_QUEUE_WORD = {qc['WORD']};           // the request rule's room for a fetch")
    w("")
    w("// ---- Widths (spec A2) ----")
    for k, v in WIDTHS.items():
        w(f"localparam int V35_W_{k} = {v};")
    w("")
    # classes and costs
    names = sorted({n for d in cost.values() for n in d})
    w(f"// ---- Classes ({len(classes)}) and class integers "
      f"({sum(len(d) for d in cost.values())}; Config.cost) ----")
    for i, c in enumerate(classes):
        w(f"localparam int V35_CLS_{_ident(c)} = {i};")
    w(f"localparam int V35_CLS_N = {len(classes)};")
    for i, n in enumerate(names):
        w(f"localparam int V35_CN_{_ident(n)} = {i};")
    w(f"localparam int V35_CN_N = {len(names)};")
    for c in classes:
        for n in sorted(cost[c]):
            w(f"localparam int V35_C_{_ident(c)}_{_ident(n)} = {cost[c][n]};")
    w("function automatic int v35_cost(input int cls, input int name);")
    w("    v35_cost = 0;")
    w("    case (cls)")
    for c in classes:
        if not cost[c]:
            continue
        w(f"        V35_CLS_{_ident(c)}: case (name)")
        for n in sorted(cost[c]):
            w(f"            V35_CN_{_ident(n)}: v35_cost = {cost[c][n]};")
        w("            default: v35_cost = 0;")
        w("        endcase")
    w("        default: v35_cost = 0;")
    w("    endcase")
    w("endfunction")
    w("function automatic bit v35_cost_has(input int cls, input int name);")
    w("    v35_cost_has = 1'b0;")
    w("    case (cls)")
    for c in classes:
        if not cost[c]:
            continue
        items = ", ".join(f"V35_CN_{_ident(n)}" for n in sorted(cost[c]))
        w(f"        V35_CLS_{_ident(c)}: v35_cost_has = name inside {{{items}}};")
    w("        default: v35_cost_has = 1'b0;")
    w("    endcase")
    w("endfunction")
    w("")
    # EA
    w(f"// ---- EA table ({len(cfg.ea)}; Config.ea) ----")
    for i, m in enumerate(EA_CLASSES):
        w(f"localparam int V35_EAC_{_ident(m)} = {i};")
    for m in sorted(cfg.ea):
        if m not in EA_CLASSES:
            raise RtlgenError(f"EA mode {m} has no encoding")
        w(f"localparam int V35_EA_{_ident(m)} = {cfg.ea[m]};")
    w("function automatic int v35_ea(input int mode);")
    w("    case (mode)")
    for m in sorted(cfg.ea):
        w(f"        V35_EAC_{_ident(m)}: v35_ea = {cfg.ea[m]};")
    w("        default: v35_ea = 0;")
    w("    endcase")
    w("endfunction")
    w("")
    # steps
    sw = sum(b for _, b in STEP_FIELDS)
    w(f"// ---- Step lists: {len(tmpls)} templates (frozen templates.steps under the fit, and")
    w("// refresh_hold_steps for a refresh-on chain), one packed step per word ----")
    off = 0
    for name, bits in STEP_FIELDS:
        w(f"localparam int V35_SF_{_ident(name)} = {off}, V35_SF_{_ident(name)}_W = {bits};")
        off += bits
    w(f"localparam int V35_STEP_W = {sw};")
    for i, v in enumerate(STEP_OPS):
        w(f"localparam int V35_SOP_{_ident(v)} = {i};")
    for i, v in enumerate(STEP_TAGS):
        w(f"localparam int V35_STAG_{_ident(v)} = {i};")
    for i, v in enumerate(REQ_KINDS):
        w(f"localparam int V35_RK_{_ident(v)} = {i};")
    for i, v in enumerate(ADDR_SRC):
        w(f"localparam int V35_SRC_{_ident(v)} = {i};   // src_i: stack word index (2 bytes each)"
          if v.startswith("stack") else f"localparam int V35_SRC_{_ident(v)} = {i};")
    w(f"localparam int V35_TMPL_N = {len(tmpls)};")
    tw = _bits(len(tmpls))
    w(f"localparam int V35_TMPL_W = {tw};")
    w("// a clocks/take/setup count is n + per_count * count (a shift's count)")
    w("function automatic int v35_tmpl_len(input int tmpl);")
    w("    case (tmpl)")
    for i, t in enumerate(tmpls):
        w(f"        {i}: v35_tmpl_len = {len(t)};   // {example[i][0]}: {example[i][1]}")
    w("        default: v35_tmpl_len = 0;")
    w("    endcase")
    w("endfunction")
    w(f"function automatic logic [{sw - 1}:0] v35_step(input int tmpl, input int k);")
    w(f"    v35_step = {sw}'d0;")
    w("    case (tmpl)")
    for i, t in enumerate(tmpls):
        w(f"        {i}: case (k)   // {example[i][0]}: {example[i][1]}")
        for k, st in enumerate(t):
            w(f"            {k}: v35_step = {sw}'h{pack_step(st):0{(sw + 3) // 4}X};   // "
              + _step_comment(st))
        w(f"            default: v35_step = {sw}'d0;")
        w("        endcase")
    w(f"        default: v35_step = {sw}'d0;")
    w("    endcase")
    w("endfunction")
    w("")
    # (E3) the REP string forms' compact templates (string_template, expand_string)
    reps = [(i, string_shape(t, example[i][0])) for i, t in enumerate(tmpls)
            if example[i][0] in string_classes() and len(t) > 5 and dict(t[0])["op"] == "take"]
    w("// ---- (E3) The REP string forms' compact templates (rtlgen.string_template): rows 0-1")
    w("// the head (take 1, nowait rpre), rows 2-3 the CW = 0 rows (fetch_release zfetch raise,")
    w("// clocks zexit), row 4 the rows before element 0 (fetch_release forever), then the")
    w("// element rows of element 0, element 1 and element >= 2 (m rows each: c data rows, then a")
    w("// compare's fetch_hold), then the tail (t rows: fetch_release xfetch, split_floor xsplit),")
    w("// then clocks rexit and a compare's clocks cexit; the EU expands them (expand_string) ----")
    w(f"localparam int V35_STR_HEAD = {STRING_HEAD};")
    w(f"localparam int V35_STR_ZERO = {STRING_ZERO};")
    w(f"localparam int V35_STR_PRE = {STRING_PRE};")
    w(f"localparam int V35_STR_SETS = {STRING_SETS};")
    w("function automatic logic [5:0] v35_str_shape(input int tmpl);   // {t, m, c}; 0: not one")
    w("    case (tmpl)")
    for i, (m, c, t) in reps:
        w(f"        {i}: v35_str_shape = {{2'd{t}, 2'd{m}, 2'd{c}}};   "
          f"// {example[i][0]}: {example[i][1]}")
    w("        default: v35_str_shape = 6'd0;")
    w("    endcase")
    w("endfunction")
    w("")
    # (WP79) the BCD strings' compact templates (bcd_template, expand_bcd)
    bcds = [(i, bcd_shape(t)) for i, t in enumerate(tmpls) if example[i][0] in bcd_classes()]
    w("// ---- (WP79) The BCD strings' compact templates (rtlgen.bcd_template): rows 0-1 the head")
    w("// (clocks pre, take 1), then the rows of byte pair 0 and of pair >= 1 (m rows each: the")
    w("// byte reads at IX + i and IY + i, ADD4S / SUB4S's write at IY + i), then clocks exec; the")
    w("// EU expands them by the pair count (expand_bcd) ----")
    w(f"localparam int V35_BCD_HEAD = {BCD_HEAD};")
    w(f"localparam int V35_BCD_SETS = {BCD_SETS};")
    w("function automatic logic [1:0] v35_bcd_shape(input int tmpl);   // m; 0: not one")
    w("    case (tmpl)")
    for i, m in bcds:
        w(f"        {i}: v35_bcd_shape = 2'd{m};   // {example[i][0]}: {example[i][1]}")
    w("        default: v35_bcd_shape = 2'd0;")
    w("    endcase")
    w("endfunction")
    w("")
    fw = sum(b for _, b in FMT_FIELDS)
    w(f"// ---- Template selection: the format word ({len(sel)} formats) ----")
    off = 0
    for name, bits in FMT_FIELDS:
        w(f"localparam int V35_FF_{_ident(name)} = {off}, V35_FF_{_ident(name)}_W = {bits};")
        off += bits
    w(f"localparam int V35_FMT_W = {fw};")
    w(f"function automatic int v35_tmpl_sel(input logic [{fw - 1}:0] fmt);   // -1: none")
    w("    case (fmt)")
    for key, tid in sorted(sel.items(), key=lambda kv: pack_fmt(kv[0], classes)):
        w(f"        {fw}'h{pack_fmt(key, classes):0{(fw + 3) // 4}X}: v35_tmpl_sel = {tid};")
    w("        default: v35_tmpl_sel = -1;")
    w("    endcase")
    w("endfunction")
    # (WP79) templates.BASE_CLASS: the class whose structure a class shares (every rule that
    # names a class sees it; the integers stay the class's own)
    from .sim.frozen.templates import BASE_CLASS
    w("")
    w("// ---- (WP79) templates.BASE_CLASS: the existing class whose structure a class shares")
    w("// (the EU's, the queue's and the arbiter's rules see it; the costs are the class's) ----")
    w("function automatic int v35_base_cls(input int cls);")
    w("    case (cls)")
    for c in classes:
        if c in BASE_CLASS:
            w(f"        V35_CLS_{_ident(c)}: v35_base_cls = V35_CLS_{_ident(BASE_CLASS[c])};")
    w("        default: v35_base_cls = cls;")
    w("    endcase")
    w("endfunction")
    # the EU's wbsync prefix (eu.py _start)
    w("")
    w("// ---- The EU's wbsync step before a template (eu.py: wbsync, or wbsync0 for a")
    w("// form without operand bytes when the class has it) ----")
    w("function automatic bit v35_wbsync(input int cls, input bit one_byte);")
    w("    case (cls)")
    for c in classes:
        d = cost[c]
        long_ = bool(d.get("wbsync", 0))
        short = bool(d.get("wbsync0", 0)) if "wbsync0" in d else long_
        if long_ or short:
            w(f"        V35_CLS_{_ident(c)}: v35_wbsync = one_byte ? 1'b{int(short)} : "
              f"1'b{int(long_)};")
    w("        default: v35_wbsync = 1'b0;")
    w("    endcase")
    w("endfunction")
    return "\n".join(L) + "\n"


def _step_comment(st: tuple) -> str:
    d = dict(st)
    parts = [d["op"]]
    for k in ("tag", "kind", "src"):
        if d.get(k):
            parts.append(str(d[k]) + (f"+{d['src_i']}" if k == "src" and d.get("src_i") else ""))
    n = d.get("n")
    if n is not None:
        parts.append(f"n={n[0]}" + (f"+{n[1]}*count" if n[1] else ""))
    if "width" in d:
        parts.append(f"w={d['width']}")
    if d.get("has_free"):
        parts.append(f"free={d['free'][0]}")
    for k in ("grp", "whole", "detached"):
        if d.get(k):
            parts.append(k)
    return " ".join(parts)


def generate(out: Path = OUT) -> str:
    text = render()
    Path(out).write_text(text)
    return text


def check(out: Path = OUT) -> int:
    text = render()
    old = Path(out).read_text() if Path(out).exists() else ""
    if old == text:
        print(f"{out} matches the fit")
        return 0
    diff = difflib.unified_diff(old.splitlines(), text.splitlines(), str(out), "regenerated",
                                lineterm="", n=1)
    for line in list(diff)[:40]:
        print(line)
    print(f"{out} drifted: regenerate with python -m validation.v35s.chains rtlgen")
    return 1


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(prog="python -m validation.v35s.chains rtlgen",
                                         description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="regenerate and diff; exit 1 on drift")
    parser.add_argument("--out", type=Path, default=OUT, help=f"default {OUT.relative_to(ROOT)}")
    return parser


def main(argv=None, args=None) -> int:
    if args is None:
        args = build_parser().parse_args(argv)
    if args.check:
        return check(args.out)
    text = generate(args.out)
    print(f"wrote {args.out} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
