"""Human-readable tables and ASCII clock strips of derived chain facts.

    python -m validation.v35s.chains report --family F1 [--waits 0 1 2] [--strips] [--file PATH]
    python -m validation.v35s.chains facts --family F0 [--json] [--file PATH]

Tables: rows = chain variant (id without family, parity and waits), columns =
parity x waits (pE-w0 pE-w1 pE-w2 pO-w0 ...; F0w: pE pO). All clocks are
relative to t_fill unless a title says otherwise (see derive.py).

Strips: one character per clock from t_fill-8 to the END write: '.' idle, the
cycle's letter (F R W r w I i X) on its first clock and '-' on the rest. Each
variant's runs are stacked pE-w0..w2 then pO-w0..w2 and aligned at t_M0 when
the chain has markers, else at t_fill (the '|' column of the ruler).
"""

from __future__ import annotations

import json
import sys

from .derive import family_facts
from .types import TICKS_PER_CLOCK  # noqa: F401  (documented unit)


def _join(values, sep=",") -> str:
    return sep.join(str(v) for v in values)


def _num(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


# Cell functions per family: list of (title, function(facts) -> str).
TABLES = {
    "F0": [("fill_words/idle_gap/restart_clock  (restart cadence after the '+')",
            lambda f: f"{f['fill_words']}/{f['idle_gap']}/{f['restart_clock']}"
                      f"+{_num(f['restart_cadence'])}"),
           ("refill burst cadence (fetch start-to-start from the restart)",
            lambda f: _join(f["burst_cadence"])),
           ("fill_bytes past LS / restart_word (chain offset)",
            lambda f: f"{f['fill_bytes']}/{f['restart_word']}")],
    "F0w": [("cycle lengths fetch/io_write (clocks)",
             lambda f: f"{_join(f['lengths'].get('fetch', []))}/"
                       f"{_join(f['lengths'].get('io_write', []))}"),
            ("idle_gap/restart_clock/t_M0",
             lambda f: f"{f['idle_gap']}/{f['restart_clock']}/{_num(f['t_M'][0] if f['t_M'] else None)}"),
            ("refill burst cadence", lambda f: _join(f["burst_cadence"]))],
    "F1": [("t_M (marker starts, rel t_fill)", lambda f: _join(f["t_M"])),
            ("dM / marker spacing",
             lambda f: f"{_num(f['dM'])} [{_join(f['marker_spacing'])}]" if f["dM"] is not None
                       else "-"),
            ("restart_clock / refill burst cadence",
             lambda f: f"{f['restart_clock']} {_join(f['burst_cadence'])}"),
            ("occupancy_at_M1 / marker_adjacent",
             lambda f: f"{_num(f['occupancy_at_M1'])}{' adj' if f['marker_adjacent'] else ''}"),
            ("interleave from M0 to the next idle", lambda f: f["interleave_M"] or "-")],
    "F2": [("restart_clock", lambda f: _num(f["restart_clock"])),
            ("cost = restart_clock - restart_clock(empty)", lambda f: _num(f.get("cost"))),
            ("t_M0 / interleave from M0", lambda f: f"{_num(f['t_M'][0] if f['t_M'] else None)} "
                                                   f"{f['interleave_M'] or '-'}")],
    "F9": [("restart_clock/refill_fetches (fetches from the restart to the next idle)",
            lambda f: f"{_num(f['restart_clock'])}/{f['refill_fetches']}"),
           ("cost = restart_clock - restart_clock(empty), same marker",
            lambda f: _num(f.get("cost"))),
           ("refill burst cadence", lambda f: _join(f["burst_cadence"])),
           ("t_M0 / bus cycles from the gap to the next idle",
            lambda f: f"{_num(f['t_M'][0] if f['t_M'] else None)} "
                      f"{f['interleave_restart'] or '-'}")],
}
TABLES["F10"] = [
    ("X's I/O cycle rel t_M0 (marker-less: rel t_fill)",
     lambda f: _num(f["io_rel_M0"] if f["io_rel_M0"] is not None else f["t_io"])),
    ("dM (t_M1 - t_M0; marker-less: t_end)",
     lambda f: _num(f["dM"] if f["dM"] is not None else f["t_end"])),
    ("cost = dM - dM(P none, same X)", lambda f: _num(f.get("cost"))),
    ("interleave from M0 (marker-less: from the restart)",
     lambda f: f["interleave_M"] or f["interleave_restart"] or "-")]
TABLES["F11"] = [
    ("t_end (END write rel t_fill)", lambda f: _num(f["t_end"])),
    ("restart_clock/refill_fetches", lambda f: f"{_num(f['restart_clock'])}/{f['refill_fetches']}"),
    ("bus cycles from the gap to the next idle", lambda f: f["interleave_restart"] or "-"),
    ("fetch clocks rel t_fill from the restart (first 6)",
     lambda f: _join(e["t"] for e in f["fetches"][:6]))]
TABLES["F12"] = [
    ("probe rel t_M0: closing OUT's I/O (series A out/pushout), M1 write (push frames); "
     "marker-less: t_end rel t_fill",
     lambda f: _num(f["io_rel_M0"] if f["io_rel_M0"] is not None
                    else f["dM"] if f["dM"] is not None else f["t_end"])),
    ("fetch clocks from M0 (marker-less: rel t_fill from the restart, first 5)",
     lambda f: _join([e["t"] - (f["t_M"][0] if f["t_M"] else 0) for e in f["fetches"]
                      if e["t"] >= (f["t_M"][0] if f["t_M"] else 70)][:5])),
    ("interleave from M0 (marker-less: from the restart)",
     lambda f: f["interleave_M"] or f["interleave_restart"] or "-")]
# F14 (WP19): per series the data cycles of X rel t_M0 (marker-less: rel t_fill) with the
# clocks after the last fetch's end in brackets, dM and the cost, the timeline from M0; then
# difference rows between the format pairs (F14_PAIRS) of the first data cycle, of the
# second (the write) and of dM.
def _xc(f, i=None):
    cyc = f.get("x_cycles") or []
    if i is not None:
        return cyc[i][1] if len(cyc) > i else None
    return " ".join(f"{c}{t}[{_num(d)}]" for c, t, d in cyc) or "-"


TABLES["F14"] = [
    ("X's data cycles rel t_M0 (marker-less: rel t_fill) [clocks after the last fetch's end]",
     _xc),
    ("dM (cost = dM - dM(empty frame, same marker)); marker-less: t_end",
     lambda f: (f"{_num(f['dM'])} ({_num(f.get('cost'))})" if f["dM"] is not None
                else _num(f["t_end"]))),
    ("timeline from M0 to the idle after M1 (marker-less: from the restart), clocks rel M0 "
     "(rel t_fill)", lambda f: f.get("timeline") or "-")]
# (label, a, b): b - a answers the question in the label; every T pair at each frame
F14_PAIRS = [
    ("direction ADD: 03 - 01", "add_bw_aw", "add_aw_bw"),
    ("direction CMP: 3B - 39", "cmp_bw_aw", "cmp_aw_bw"),
    ("RO vs RMW, reg operand: 39 - 01", "add_bw_aw", "cmp_bw_aw"),
    ("TEST vs CMP r/m,reg: 85 - 39", "cmp_bw_aw", "test_bw_aw"),
    ("group RO vs TEST: F7/0 - 85", "test_bw_aw", "test_bw_imm"),
    ("group RO vs group RMW imm: F7/0 - 81/0", "add_bw_imm", "test_bw_imm"),
    ("XCH vs ADD: 87 07 - 01 07", "add_bw_aw", "xch_bw_aw"),
    ("XCH register: 87 0F - 87 07", "xch_bw_aw", "xch_cw_bw"),
    ("store vs ADD: 89 - 01", "add_bw_aw", "mov_bw_aw"),
    ("load vs ADD AW,[BW]: 8B - 03", "add_aw_bw", "mov_aw_bw"),
    ("group RMW: NOT - ADD", "add_bw_aw", "not_bw"),
    ("group RMW: NEG - NOT", "not_bw", "neg_bw"),
    ("group RMW: INC - NOT", "not_bw", "inc_bw"),
    ("byte TEST: 84 - 85", "test_bw_aw", "test_bw_al"),
    ("byte XCH: 86 - 87", "xch_bw_aw", "xch_bw_al"),
    ("byte ADD: 00 - 01", "add_bw_aw", "add_bw_al"),
    ("byte CMP: 38 - 39", "cmp_bw_aw", "cmp_bw_al"),
    ("direct TEST: 85 06 - 85 07", "test_bw_aw", "test_dir_aw"),
    ("direct XCH: 87 06 - 87 07", "xch_bw_aw", "xch_dir_aw"),
]


def f14_tables(ff: dict) -> str:
    rows = ff["rows"]
    out = []
    for series, name in (("t", "T"), ("g", "G"), ("o", "O")):
        sub = {v: c for v, c in rows.items() if v.startswith(series + "-")}
        for title, cell in TABLES["F14"]:
            out.append(table(f"F14 {name}: {title}", sub, cell))
    for what, fn in (("first data cycle", lambda f: _xc(f, 0)),
                     ("second data cycle", lambda f: _xc(f, 1)),
                     ("dM (marker-less: t_end)",
                      lambda f: f["dM"] if f["dM"] is not None else f["t_end"])):
        diff = {}
        for frame in ("push", "push-k2", "out", "none"):
            kind, _, k = frame.partition("-")
            for label, a, b in F14_PAIRS:
                va = rows.get(f"t-{kind}-{a}" + (f"-{k}" if k else ""))
                vb = rows.get(f"t-{kind}-{b}" + (f"-{k}" if k else ""))
                if not va or not vb:
                    continue
                cells = {}
                for col in va:
                    x, y = fn(va[col]), fn(vb.get(col, va[col])) if col in vb else None
                    cells[col] = None if x is None or y is None else y - x
                diff[f"{frame} {label}"] = cells
        out.append(table(f"F14 T: {what}, b - a per format pair", diff, _num))
    kd = ff["k_differences"]
    return "\n\n".join(out)


# F15 (WP20): the F14 tables per series (A, P, K, O), then difference rows between pairs
# (label, a, b) per frame: b - a of the first and second data cycle and of dM.
TABLES["F15"] = TABLES["F14"]
F15_PAIRS = [
    ("AND vs TEST: 21 - 85", "a", "test_bw_aw", "and_bw_aw"),
    ("AND direction: 23 - 21", "a", "and_bw_aw", "and_aw_bw"),
    ("OR vs AND: 09 - 21", "a", "and_bw_aw", "or_bw_aw"),
    ("SUB vs AND: 29 - 21", "a", "and_bw_aw", "sub_bw_aw"),
    ("XOR vs AND, d=1: 33 - 23", "a", "and_aw_bw", "xor_aw_bw"),
    ("TEST imm vs TEST: F7/0 - 85", "a", "test_bw_aw", "test_bw_imm"),
    ("TEST imm vs AND imm: F7/0 - 81/4", "a", "and_bw_imm", "test_bw_imm"),
    ("TEST imm vs CMP imm: F7/0 - 81/7", "a", "cmp_bw_imm", "test_bw_imm"),
    ("CMP imm vs AND imm: 81/7 - 81/4", "a", "and_bw_imm", "cmp_bw_imm"),
    ("AND imm vs AND: 81/4 - 21", "a", "and_bw_aw", "and_bw_imm"),
    ("imm8 AND: 83/4 - 81/4", "a", "and_bw_imm", "and_bw_imm8"),
    ("imm8 ADD vs AND: 83/0 - 83/4", "a", "and_bw_imm8", "add_bw_imm8"),
    ("direct AND vs TEST: 21 06 - 85 06", "a", "test_dir_aw", "and_dir_aw"),
    ("direct CMP vs TEST: 39 06 - 85 06", "a", "test_dir_aw", "cmp_dir_aw"),
    ("direct AND vs [BW]: 21 06 - 21 07", "a", "and_bw_aw", "and_dir_aw"),
    ("direct TEST vs [BW]: 85 06 - 85 07", "a", "test_bw_aw", "test_dir_aw"),
    ("reg TEST: A9 - A8", "a", "test_al_imm", "test_aw_imm"),
    ("POP direct - POP [BW]", "p", "pop_bw", "pop_dir"),
    ("POP [BW+10h] - POP [BW]", "p", "pop_bw", "pop_bw_d8"),
    ("POP [IX] - POP [BW]", "p", "pop_bw", "pop_ix"),
    ("POP [BW] - POP AW", "p", "pop_aw", "pop_bw"),
    ("POP CW - POP AW", "p", "pop_aw", "pop_cw"),
    ("POP [BW] - PUSH [BW]", "p", "push_bw", "pop_bw"),
    ("NOP POP - POP", "p", "pop_bw", "nop_pop"),
    ("POP NOP - POP", "p", "pop_bw", "pop_nop"),
]


def f15_tables(ff: dict) -> str:
    rows = ff["rows"]
    out = []
    for series, name in (("a", "A"), ("p", "P"), ("k", "K"), ("o", "O")):
        sub = {v: c for v, c in rows.items() if v.startswith(series + "-")}
        for title, cell in TABLES["F15"]:
            out.append(table(f"F15 {name}: {title}", sub, cell))
    for what, fn in (("first data cycle", lambda f: _xc(f, 0)),
                     ("second data cycle", lambda f: _xc(f, 1)),
                     ("dM (marker-less: t_end)",
                      lambda f: f["dM"] if f["dM"] is not None else f["t_end"])):
        diff = {}
        for kind in ("push", "out", "none"):
            for label, series, a, b in F15_PAIRS:
                va, vb = rows.get(f"{series}-{kind}-{a}"), rows.get(f"{series}-{kind}-{b}")
                if not va or not vb:
                    continue
                cells = {}
                for col in va:
                    x = fn(va[col])
                    y = fn(vb[col]) if col in vb else None
                    cells[col] = None if x is None or y is None else y - x
                diff[f"{kind} {label}"] = cells
        out.append(table(f"F15: {what}, b - a per pair", diff, _num))
    return "\n\n".join(out)


# F16 (WP21): the F14 tables per series (R, P, L, S), then difference rows (label, a, b)
# of the first and second data cycle and of dM (marker-less: t_end): R the second instance
# of every form against its first and the INC [BW] X pair against X X.
TABLES["F16"] = TABLES["F14"]


# (label, a, b): b - a per pair of variants (full variant names)
def _f16_pairs():
    from .families import F16_L_X, F16_P_FRAME_X, F16_P_N, F16_S_M, F16_S_N
    pairs = []
    for shape in ("x_x", "inc_x"):
        for lab, x in (("ROL", "rol"), ("ROR", "ror"), ("RCL", "rcl"), ("RCR", "rcr"),
                       ("SHR", "shr"), ("SAR", "sar"), ("SHL byte D0", "shlb")):
            pairs.append((f"{shape} {lab} - SHL D1 /4", f"r-push-shl1-{shape}",
                          f"r-push-{x}-{shape}"))
        for lab, a, b in (("NEG - NOT", "not", "neg"), ("MULU - NOT", "not", "mulu"),
                          ("MUL - MULU", "mulu", "mul"), ("DIVU - MULU", "mulu", "divu"),
                          ("DIV - DIVU", "divu", "div"), ("MULU byte - MULU", "mulu", "mulub"),
                          ("SHL [BW],1 - NOT", "not", "shl1"), ("PUSH - NOT", "not", "push"),
                          ("TEST imm - NOT", "not", "test_imm")):
            pairs.append((f"{shape} {lab}", f"r-push-{a}-{shape}", f"r-push-{b}-{shape}"))
    pairs.append(("x_x DEC - INC", "r-push-inc-x_x", "r-push-dec-x_x"))
    for kind in ("push", "out", "none"):
        for n in F16_P_N[kind]:
            pairs.append((f"{kind} n{n} POP [BW] - POP AW", f"p-{kind}-n{n}-pop_aw",
                          f"p-{kind}-n{n}-pop_bw"))
            if any(lab == "pop_bw_d8" for lab, _ in F16_P_FRAME_X[kind]):
                pairs.append((f"{kind} n{n} POP [BW+d8] - POP [BW]", f"p-{kind}-n{n}-pop_bw",
                              f"p-{kind}-n{n}-pop_bw_d8"))
                pairs.append((f"{kind} n{n} POP [0C00h] - POP [BW]", f"p-{kind}-n{n}-pop_bw",
                              f"p-{kind}-n{n}-pop_dir"))
    for label, _, _ in F16_L_X:
        pairs.append((f"{label}: OUT frame - PUSH twin", f"l-push-{label}", f"l-out-{label}"))
    for n in F16_S_N:
        for m in F16_S_M:
            pairs.append((f"n{n} m{m} SHL AW,m (C1) - MOV CL,m ; SHL AW,CL",
                          f"s-none-n{n}-shlcl{m}", f"s-none-n{n}-shli{m}"))
    return pairs


def _last_read(f):
    cyc = [t for c, t, _ in (f.get("x_cycles") or []) if c in "Rr"]
    return cyc[-1] if cyc else None


def f16_tables(ff: dict) -> str:
    rows = ff["rows"]
    out = []
    for series, name in (("r", "R"), ("p", "P"), ("l", "L"), ("s", "S")):
        sub = {v: c for v, c in rows.items() if v.startswith(series + "-")}
        for title, cell in TABLES["F16"]:
            out.append(table(f"F16 {name}: {title}", sub, cell))
    for what, fn in (("first data cycle", lambda f: _xc(f, 0)),
                     ("last data read (R: the second instance's)", _last_read),
                     ("dM (marker-less: t_end)",
                      lambda f: f["dM"] if f["dM"] is not None else f["t_end"])):
        diff = {}
        for label, a, b in _f16_pairs():
            va, vb = rows.get(a), rows.get(b)
            if not va or not vb:
                continue
            cells = {}
            for col in va:
                x = fn(va[col])
                y = fn(vb[col]) if col in vb else None
                cells[col] = None if x is None or y is None else y - x
            diff[label] = cells
        out.append(table(f"F16: {what}, b - a per pair", diff, _num))
    return "\n\n".join(out)


COST_TABLES = [
    ("cost = dM - dM(baseline)", lambda f: _num(f.get("cost"))),
    ("dM", lambda f: _num(f["dM"])),
    ("occupancy_at_M1", lambda f: _num(f["occupancy_at_M1"])),
    ("interleave from M0 to the idle after M1", lambda f: f["interleave_M"] or "-"),
]


# (WP66) F24: the cost frame's tables, then the string forms' elements on the bus
TABLES["F24"] = COST_TABLES + [
    ("elements seen (knob iters) / element start-to-start spacing",
     lambda f: (f"{_num(f.get('str_elements'))}({_num(f['knobs'].get('iters'))}) "
                f"{_join(f.get('str_spacing') or [])}" if f["knobs"].get("form") else "-")),
    ("REP compare overrun: its cycles rel t_M0 (clocks from the last element's start)",
     lambda f: (f"{f['str_overrun']} ({_num(f.get('str_overrun_gap'))})"
                if f.get("str_overrun") else "-")),
    ("first element's first cycle rel t_M0 / fetches inside the stream / first fetch after "
     "the stream's last cycle, the overrun's included (clocks)",
     lambda f: (f"{_num((f.get('str_t') or [None])[0])}/{_num(f.get('str_fetches'))}/"
                f"{_num(f.get('str_next_fetch'))}" if f.get("str_t") else "-")),
    ("bus cycles from the first element to M1", lambda f: f.get("str_window") or "-"),
    ("each element's cycles, clocks rel t_M0",
     lambda f: " | ".join(f.get("str_cycles") or []) or "-"),
]


# (WP74) F32 / F33: the cost frame's tables, X's own cycles, the k series (slope and intercept
# per form), and F33's REPC / REPNC elements as F24's
F3X_TABLES = COST_TABLES + [
    ("X's data cycles rel t_M0 [clocks after the last fetch's end]", _xc),
]
TABLES["F32"] = F3X_TABLES
TABLES["F33"] = F3X_TABLES + TABLES["F24"][len(COST_TABLES):]
# (WP80) F34: the cost frame's tables and X's own cycles, as F32's
TABLES["F34"] = F3X_TABLES


def f3x_k_table(ff: dict) -> str:
    """(WP74) per form stem: cost at k = 1, 2 (4), slope = c2 - c1, intercept = c1 - slope."""
    ks = ff.get("k_series") or {}
    cell = lambda t: f"{'/'.join(_num(v) for v in t[0].values())} s{_num(t[1])} i{_num(t[2])}"
    return table(f"{ff['family']}: cost at k = 1/2[/4], slope s = c2 - c1, intercept i = c1 - s",
                 ks, cell)


def columns_of(rows) -> list[str]:
    cols = {c for cells in rows.values() for c in cells}
    return sorted(cols, key=lambda c: (c[:2] != "pE", c))


def table(title: str, rows: dict, cell, columns=None) -> str:
    """rows {variant: {column: x}} rendered with cell(x) -> str."""
    columns = columns or columns_of(rows)
    body = [[variant] + [cell(cells[c]) if c in cells else "" for c in columns]
            for variant, cells in rows.items()]
    head = ["variant"] + columns
    widths = [max(len(r[i]) for r in [head] + body) for i in range(len(head))]
    fmt = lambda r: "  ".join(v.ljust(widths[0]) if i == 0 else v.rjust(widths[i])
                             for i, v in enumerate(r)).rstrip()
    lines = [title, fmt(head), fmt(["-" * w for w in widths])]
    lines += [fmt(r) for r in body]
    return "\n".join(lines)


def family_tables(ff: dict) -> str:
    rows = ff["rows"]
    family = ff["family"]
    out = []
    for title, cell in TABLES.get(family, COST_TABLES):
        out.append(table(f"{family}: {title}", rows, cell))
    pairs = ff.get("push_minus_out")
    if pairs:
        cell = lambda t: f"{_num(t[0])}/{_num(t[1])} ({_num(t[2])})"
        out.append(table(f"{family}: cost push/out (push - out), same-kind baselines",
                         pairs, cell))
    if family == "F6":
        slopes = ff["drain_slopes"]
        out.append(table("F6: clocks per drainer (cost(n4)-cost(n2))/2 / (cost(n6)-cost(n2))/4",
                         slopes, lambda t: f"{_num(t[0])}/{_num(t[1])}"))
        out.append(table("F6: X's first data cycle - end clock of the fetch of X's last byte",
                         rows, lambda f: _num(f["x"][0]["issue_after_fetch"]) if f["x"] else "-"))
    if family == "F7":
        out.append(f7_matrices(ff))
    if family == "F13":
        return f13_tables(ff)
    if family == "F14":
        return f14_tables(ff)
    if family == "F15":
        return f15_tables(ff)
    if family == "F16":
        return f16_tables(ff)
    if family == "F17":
        return f17_tables(ff)
    if family == "F18":
        return f18_tables(ff)
    if family in ("F32", "F33", "F34"):
        out.append(f3x_k_table(ff))
    if family == "F8":
        out.append(table("F8: refreshes from clock 0 to END / positions in the M0 window",
                         rows, lambda f: f"{f['refresh_count']} [{_join(f['refresh_positions_M'])}]"))
        out.append(f8_runs(ff))
    if family == "F1":
        mc = ff["marker_cost"]
        cells = lambda c: (f"{_num(c.get('slope_m2'))}/{_num(c.get('slope_m4'))}/"
                           f"{_num(c.get('m4_minus_m2'))}")
        out.append(table("F1 marker cost: slope m2 / slope m4 / (t_M3-t_M0)-(t_M1-t_M0)",
                         mc, cells))
        lat = lambda c: _join(_num(c.get(f"latency_m{n}")) for n in (1, 2, 4))
        out.append(table("F1 marker latency t_M0 for m1,m2,m4", mc, lat))
    oe = ff["odd_minus_even"]
    if oe:
        out.append(table(f"{family}: odd - even of {ff['metric']}", oe, _num))
    kd = ff["k_differences"]
    if any(kd.values()):
        out.append(table(f"{family}: k differences", kd, _num))
    return "\n\n".join(out)


def _series_rows(rows, *series) -> dict:
    out = {v: c for v, c in rows.items()
           if next(iter(c.values()))["knobs"].get("series") in series}
    key = lambda v: (v.split("-")[0], v.rsplit("-", 1)[0],
                     int("".join(ch for ch in v.rsplit("-", 1)[-1] if ch.isdigit()) or 0))
    return {v: out[v] for v in sorted(out, key=key)}


def f13_tables(ff: dict) -> str:
    """F13 (refresh EU series): S/S0 X's end against the count, C/U/N the cost frames,
    marker-less U/N, R the refresh interval and cycle per RFM value."""
    rows = ff["rows"]
    s = _series_rows(rows, "s", "s0")
    c = _series_rows(rows, "c", "u", "n")
    c = {v: cells for v, cells in c.items() if next(iter(cells.values()))["dM"] is not None}
    bare = {v: cells for v, cells in _series_rows(rows, "u", "n").items()
            if next(iter(cells.values()))["dM"] is None}
    r = _series_rows(rows, "r")
    out = [
        table("F13 S/S0: X's end fetch - restart (D = that minus refresh off, S0; b = the "
              "fetch starts the clock after a refresh ends, X ended on or before)", s,
              lambda f: f"{_num(f.get('x_len'))} ({_num(f.get('D'))}"
                        f"{'b' if f.get('x_end_blocked') else ''})"),
        table("F13 S: refreshes from restart-4 to X's end fetch, rel the restart", s,
              lambda f: _join(f.get("x_refreshes") or []) or "-"),
        table("F13 S/S0/R: restart (the first LS's end) rel t_fill / refreshes 0.. before it",
              {**s, **r},
              lambda f: f"{_num(f['restart_clock'])}/"
                        f"{_join(x for x in f['refreshes'] if 0 <= x < (f['restart_clock'] or 0))}"),
        table("F13 C/U/N: dM (cost = dM - refresh-off dM from F3) [refreshes from M0-4 to M1, "
              "rel M0]", c,
              lambda f: f"{_num(f['dM'])} ({_num(f.get('cost'))}) "
                        f"[{_join(f.get('window_refreshes') or [])}]"),
        table("F13 C/U/N: t_M0 rel t_fill", c, lambda f: _num(f["t_M"][0])),
        table("F13 U/N marker-less: t_end (minus r-rfm-f0's) [refreshes from the restart]",
              bare,
              lambda f: f"{_num(f['t_end'])} ({_num(f.get('t_end_minus_empty'))}) "
                        f"[{_join(x for x in f['refreshes'] if x >= (f['restart_clock'] or 0) - 4)}]"),
        table("F13 R: refresh length(s) / gaps between refreshes", r,
              lambda f: f"{_join(f['refresh_lengths'])}/{_join(f.get('refresh_gaps') or [])}"),
    ]
    return "\n\n".join(out)


def f17_tables(ff: dict) -> str:
    """F17 (the chain turns refresh on): the first refresh rel t_fill and the idle grid's
    residues against clock 0 (the timer's phase); the second LS's end and D against the
    refresh-off control; the refreshes from the first one on."""
    rows = ff["rows"]
    on = {v: c for v, c in rows.items()
          if next(iter(c.values()))["knobs"].get("rfmon") != 0xEC}
    out = [
        table("F17: first refresh rel t_fill / idle-grid residues against clock 0", on,
              lambda f: f"{_num(f.get('first_refresh'))}/{_join(f.get('grid') or [])}"),
        table("F17: second LS's end rel t_fill (D = minus the RFMON ECh control's)", rows,
              lambda f: f"{_num(f.get('ls_end'))} ({_num(f.get('D'))})"),
        table("F17: refreshes rel t_fill", on, lambda f: _join(f.get("refreshes") or []) or "-"),
    ]
    return "\n\n".join(out)


def f18_tables(ff: dict) -> str:
    """F18: A/AC, the prelude marker and the first LS against clock 0 (marker / t_fill /
    the first LS's end, the refreshes before it); B/BD, the first refresh rel t_fill, the
    second LS's end and the refreshes."""
    rows = ff["rows"]
    a = {v: c for v, c in rows.items() if v.startswith("a")}
    b = {v: c for v, c in rows.items() if v.startswith("b")}
    out = [
        table("F18 A: prelude marker / t_fill / first LS's end, clocks rel clock 0", a,
              lambda f: f"{_num(f.get('pre_marker'))}/{_num(f.get('fill'))}/"
                        f"{_num(f.get('ls1_end'))}"),
        table("F18 A: refreshes before the first LS's end, rel clock 0", a,
              lambda f: _join(f.get("ls1_refreshes") or []) or "-"),
        table("F18 B: first refresh rel t_fill / second LS's end", b,
              lambda f: f"{_num(f.get('first_refresh'))}/{_num(f.get('ls_end'))}"),
        table("F18 B: refreshes rel t_fill", b, lambda f: _join(f.get("refreshes") or []) or "-"),
    ]
    return "\n\n".join(out)


def f7_matrices(ff: dict) -> str:
    """Per column and kind: interaction matrix, a rows x b columns. Row labels
    carry a's byte parity, cells b's: value(e|o). Then push - out."""
    inter = ff["interactions"]
    cells = inter["cells"]
    names = list(dict.fromkeys(a for grid in cells.values() for a in grid))
    columns = columns_of({0: {c: 1 for _, c in cells}})
    out = ["F7: interaction = dM(a b) - dM(a) - dM(b) + dM(empty); singles from "
           "F4 (ld_bw), F3 (mov_aw_dw), F5 (others), same kind and column; "
           "row label (p) = a's byte parity, cell (p) = b's"]
    for column in columns:
        grids = {}
        for marker in ("push", "out"):
            grid = cells.get((marker, column))
            if grid is None:
                continue
            grids[marker] = grid
            rows = {}
            for a in names:
                r = grid.get(a, {})
                pa = next((v[1] for v in r.values()), "?")
                rows[f"{a}({pa})"] = {b: f"{_num(v[0])}({v[2]})" for b, v in r.items()}
            out.append(table(f"F7 {marker} {column}", rows, lambda x: x, names))
        if len(grids) == 2:
            rows = {}
            for a in names:
                rows[a] = {}
                for b in names:
                    p, o = grids["push"].get(a, {}).get(b), grids["out"].get(a, {}).get(b)
                    if p and o and p[0] is not None and o[0] is not None:
                        rows[a][b] = str(p[0] - o[0])
            out.append(table(f"F7 push - out {column}", rows, lambda x: x, names))
    if inter["empties"]:
        out.append("F7: F3/F4/F5 empties DISAGREE (dM by family): " + "; ".join(
            f"{m} {c}: {d}" for (m, c), d in inter["empties"].items()))
    else:
        out.append("F7: F3/F4/F5 same-kind empties agree in every column")
    return "\n\n".join(out)


def f8_runs(ff: dict) -> str:
    lines = ["F8 per run: refreshes, positions in the whole interleave, interleave"]
    for f in ff["runs"]:
        lines.append(f"{f['id']:<26} {f['refresh_count']:>2} "
                     f"[{_join(f['refresh_positions'])}]  {f['interleave']}")
    return "\n".join(lines)


# Strips ----------------------------------------------------------------------

def strip(n, before: int = 8) -> tuple[str, int]:
    """(strip, index of the alignment clock in it)."""
    start = n.t_fill - before
    end_ev = next(e for e in n.events if e.kind == "io_write" and e.clock == n.t_end)
    stop = end_ev.end
    chars = ["."] * (stop - start + 1)
    for e in n.events:
        for c in range(e.clock, e.end + 1):
            if start <= c <= stop:
                chars[c - start] = e.char if c == e.clock else "-"
    anchor = n.t_markers.get(0, n.t_fill)
    return "".join(chars), anchor - start


def strips(ff: dict) -> str:
    groups: dict = {}
    for f in ff["runs"]:
        groups.setdefault(f["variant"], []).append(f)
    out = []
    for variant, runs in groups.items():
        runs.sort(key=lambda f: (f["parity"] != "even", f["waits"]))
        rendered = [(f["column"], *strip(ff["normalized"][f["id"]])) for f in runs]
        lead = max(a for _, _, a in rendered)
        label = max(len(c) for c, _, _ in rendered)
        anchored = "t_M0" if ff["normalized"][runs[0]["id"]].t_markers else "t_fill"
        ruler = "".join("|" if i == lead else ("+" if (i - lead) % 10 == 0 else " ")
                        for i in range(lead + 1 + max(len(s) - a for _, s, a in rendered)))
        out.append(f"{ff['family']}-{variant}  (aligned at {anchored}, '+' every 10 clocks)")
        out.append(" " * (label + 2) + ruler.rstrip())
        for column, s, a in rendered:
            out.append(f"{column:<{label}}  " + " " * (lead - a) + s)
        out.append("")
    return "\n".join(out)


# Entry points ----------------------------------------------------------------

def _facts(args) -> dict:
    return family_facts(args.family, waits=tuple(args.waits), files=args.file)


def report_main(args) -> int:
    ff = _facts(args)
    print(family_tables(ff))
    if args.strips:
        print()
        print(strips(ff))
    return 0


def jsonable(ff: dict) -> dict:
    """The facts without the Normalized objects, JSON-safe (dict keys as str)."""
    def clean(x):
        if isinstance(x, dict):
            return {str(k): clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        return x
    return clean({k: v for k, v in ff.items() if k not in ("normalized", "rows")})


def facts_main(args) -> int:
    ff = _facts(args)
    if args.json:
        json.dump(jsonable(ff), sys.stdout, indent=1)
        print()
        return 0
    for f in ff["runs"]:
        print(f"{f['id']:<36} t_fill={f['t_fill']:<4} fill={f['fill_words']} "
              f"idle={f['idle_gap']} restart={f['restart_clock']} t_M={f['t_M']} "
              f"dM={f['dM']} occ={f['occupancy_at_M1']} {f['interleave']}")
    return 0


def add_arguments(parser, json_flag: bool = False):
    parser.add_argument("--family", required=True, help="e.g. F0, F0w, F1")
    parser.add_argument("--waits", nargs="+", type=int, choices=(0, 1, 2), default=[0, 1, 2])
    parser.add_argument("--file", nargs="+", help="read these result files, not the corpus")
    if json_flag:
        parser.add_argument("--json", action="store_true", help="dump the facts as JSON")
    else:
        parser.add_argument("--strips", action="store_true", help="ASCII clock strip per run")
    return parser
