"""Per-run facts and per-family difference tables (plan, "Analysis pipeline" 3).

All clocks are CPU clocks. Per-run times are relative to `t_fill` (the end
clock of the last fill fetch, see normalize.py) unless the name says
otherwise. Definitions:

- fill_words: fetched words lying wholly past the first LS's last byte, up to
  the first idle gap (the word holding LS's last byte is not counted, even if
  its other byte is past LS); fill_bytes counts bytes past LS's last byte.
- idle_gap: start-to-start clocks from the last fill fetch to the first bus
  cycle after the gap (any kind); idle_clocks: the free clocks between them.
- restart_clock: first fetch after the gap, relative to t_fill;
  restart_word: that word's chain offset (address - chain_base, may be odd-1);
  restart_cadence: start-to-start of the next fetch (equal to the fetch
  length when the restart is back to back); refill_fetches: fetches from the
  restart to the next long idle (>= LONG_IDLE free clocks, the trailing LS's
  shift), inclusive; interleave_restart: the bus cycles from the first one
  after the gap to that idle (F9).
- t_M[i]: marker i's cycle start relative to t_fill; dM = t_M[1] - t_M[0].
- occupancy_at_M1: fetches after M1 up to the next idle gap (the refill the
  trailing LS forces), i.e. how many words the queue lacked at M1.
- events: each non-fetch cycle's kind and address, clock relative to t_M0 and
  to the end clock of the nearest preceding fetch.
- interleave: one char per bus cycle from clock 0 to the END write
  (F fetch, R/W data read/write, r/w stack, i/I io read/write, X refresh).
- marker_adjacent: some marker starts 1 or 2 clocks after a fetch's end clock,
  i.e. on the first or second free clock after that fetch.

Per family, `family_facts` adds the difference tables: cost against the
family's baseline (`BASELINES`), odd minus even, and k-series differences.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .normalize import IDLE_MIN, LONG_IDLE, Normalized, idle_gaps, load_runs, normalize

PARITY_TAG = {"even": "pE", "odd": "pO"}


def variant_of(chain) -> str:
    """Chain id without family prefix, parity and waits: the table row."""
    stem = chain.id.rsplit("-p", 1)[0]
    return stem.split("-", 1)[1] if "-" in stem else stem


def column_of(chain) -> str:
    tag = PARITY_TAG[chain.parity]
    return tag if chain.waits < 0 else f"{tag}-w{chain.waits}"


def interleave(events, start=0, stop=None) -> str:
    return "".join(e.char for e in events[start:stop])


def run_facts(n: Normalized) -> dict:
    ev = n.events
    fetches = [k for k, e in enumerate(ev) if e.kind == "fetch"]
    t_fill = n.t_fill
    marker = n.chain.knobs.get("marker") if n.chain.family != "F1" else None
    variant = variant_of(n.chain)
    x_variant = (variant[len(marker) + 1:] if marker and variant.startswith(marker + "-")
                 else variant)
    f: dict = {"id": n.run_id, "variant": variant, "column": column_of(n.chain),
               "marker": marker, "x_variant": x_variant, "knobs": n.chain.knobs,
               "family": n.chain.family, "waits": n.chain.waits, "parity": n.chain.parity,
               "wtc": n.chain.wtc, "marker_kind": n.chain.marker_kind, "phase": n.phase,
               "wait_clocks": n.wait_clocks, "t_fill": t_fill,
               "lengths": {k: sorted({e.length for e in ev if e.kind == k})
                           for k in sorted({e.kind for e in ev})}}

    # Fill and restart.
    ls = next(i for i in n.chain.instrs if i.role == "ls")
    ls_last = n.chain_base + ls.offset + len(ls.code) - 1
    fill = [ev[k] for k in fetches if n.ls_fetch_index < k <= n.fill_index]
    f["fill_words"] = sum(1 for e in fill if e.addr > ls_last)
    f["fill_bytes"] = sum(1 for e in [ev[n.ls_fetch_index]] + fill
                          for a in (e.addr, e.addr + 1) if a > ls_last)
    gaps = idle_gaps(ev, n.ls_fetch_index)
    first_after = gaps[0][1]
    f["idle_gap"] = ev[first_after].clock - ev[n.fill_index].clock
    f["idle_clocks"] = ev[first_after].clock - ev[gaps[0][0]].end - 1
    f["after_gap"] = ev[first_after].char
    restart = next((k for k in fetches if k >= first_after), None)
    f["restart_clock"] = ev[restart].clock - t_fill if restart is not None else None
    f["restart_word"] = ev[restart].addr - n.chain_base if restart is not None else None
    f["fetches"] = [{"t": ev[k].clock - t_fill, "word": ev[k].addr - n.chain_base}
                    for k in fetches if k >= first_after]
    nxt = next((k for k in fetches if restart is not None and k > restart), None)
    f["restart_cadence"] = ev[nxt].clock - ev[restart].clock if nxt is not None else None
    # Fetch cadence from the restart to the next idle gap (the refill burst).
    burst = []
    if restart is not None:
        later = idle_gaps(ev, restart)
        stop = later[0][0] if later else len(ev) - 1
        burst = [k for k in fetches if restart <= k <= stop]
    f["burst_cadence"] = [ev[b].clock - ev[a].clock for a, b in zip(burst, burst[1:])]
    # F9: fetches from the restart to the next long idle (the trailing LS's shift):
    # the bytes consumed, in words. Gaps of IDLE_MIN..LONG_IDLE clocks inside a
    # NOP train do not end it.
    f["refill_fetches"] = None
    f["interleave_restart"] = None
    if restart is not None:
        later = idle_gaps(ev, restart, LONG_IDLE)
        stop = later[0][0] if later else len(ev) - 1
        f["refill_fetches"] = sum(1 for k in fetches if restart <= k <= stop)
        f["interleave_restart"] = interleave(ev, first_after, stop + 1)

    # Fetch cadence and its histogram.
    cadence = [ev[b].clock - ev[a].clock for a, b in zip(fetches, fetches[1:])]
    f["cadence"] = cadence
    f["gap_histogram"] = dict(sorted(Counter(cadence).items()))

    # Markers.
    t_m = {i: t - t_fill for i, t in sorted(n.t_markers.items())}
    f["t_M"] = [t_m[i] for i in sorted(t_m)]
    f["dM"] = t_m[1] - t_m[0] if 0 in t_m and 1 in t_m else None
    f["marker_spacing"] = [b - a for a, b in zip(f["t_M"], f["t_M"][1:])]
    f["t_end"] = n.t_end - t_fill if n.t_end is not None else None
    m1 = next((k for k, e in enumerate(ev) if e.marker_id == 1), None)
    if m1 is not None:
        later = idle_gaps(ev, m1)
        stop = later[0][0] if later else len(ev) - 1
        f["occupancy_at_M1"] = sum(1 for k in fetches if m1 < k <= stop)
    else:
        f["occupancy_at_M1"] = None

    # Non-fetch events relative to M0 and to the nearest preceding fetch end.
    t_m0 = n.t_markers.get(0)
    rows = []
    last_fetch_end = None
    for e in ev:
        if e.kind == "fetch":
            last_fetch_end = e.end
            continue
        rows.append({"kind": e.kind, "addr": e.addr, "width": e.width, "length": e.length,
                     "marker_id": e.marker_id, "t": e.clock - t_fill,
                     "rel_M0": e.clock - t_m0 if t_m0 is not None else None,
                     "rel_fetch_end": (e.clock - last_fetch_end
                                       if last_fetch_end is not None else None)})
    f["events"] = rows
    # The chain's own I/O cycle (not the END's FF00h write): clock rel t_fill and rel t_M0,
    # and rel the start of the last fetch before it (F10)
    io = next((r for r in rows if r["kind"].startswith("io") and r["addr"] != 0xFF00
               and r["marker_id"] is None), None)
    f["t_io"] = io["t"] if io else None
    f["io_rel_M0"] = io["rel_M0"] if io else None
    end_k = next((k for k, e in enumerate(ev) if e.clock == n.t_end and e.kind == "io_write"),
                 len(ev) - 1)
    f["interleave"] = interleave(ev, 0, end_k + 1)
    # From M0 to the idle gap after M1 (or after M0): the cost-frame window.
    if t_m0 is not None:
        k0 = next(k for k, e in enumerate(ev) if e.marker_id == 0)
        anchor = m1 if m1 is not None else k0
        later = idle_gaps(ev, anchor)
        f["interleave_M"] = interleave(ev, k0, (later[0][0] + 1) if later else None)
    else:
        f["interleave_M"] = None
    fetch_ends = [ev[k].end for k in fetches]
    f["marker_adjacent"] = any(1 <= t - e <= 2 for t in n.t_markers.values()
                               for e in fetch_ends)

    # Refresh (F8): count and positions in the interleave strings.
    f["refresh_count"] = f["interleave"].count("X")
    f["refresh_positions"] = [i for i, c in enumerate(f["interleave"]) if c == "X"]
    f["refresh_positions_M"] = ([i for i, c in enumerate(f["interleave_M"]) if c == "X"]
                                if f["interleave_M"] else [])

    # Each X: its first byte's linear parity, and (when it has data / stack /
    # I/O cycles) the first such cycle relative to the end clock of the fetch
    # that delivered X's last byte (the arbitration quantity of F6).
    xs = []
    for k, instr in enumerate(n.chain.instrs):
        if instr.role != "x":
            continue
        row = {"index": instr.index, "form": instr.form,
               "parity": "o" if (n.chain_base + instr.offset) & 1 else "e"}
        last = instr.offset + len(instr.code) - 1
        fetch = next((e for e in ev if e.kind == "fetch" and e.byte_range
                      and e.byte_range[0] <= last < e.byte_range[1]), None)
        first = next((e for e in ev if e.kind != "fetch" and e.instr_index == k), None)
        row["last_byte_fetch_end"] = fetch.end - t_fill if fetch else None
        row["first_cycle"] = first.clock - t_fill if first else None
        row["first_cycle_kind"] = first.kind if first else None
        row["issue_after_fetch"] = (first.clock - fetch.end) if first and fetch else None
        xs.append(row)
    f["x"] = xs
    # (WP19, F14) X's own data / stack / I/O cycles: (kind char, clock rel t_M0, or rel
    # t_fill without markers, clocks after the end of the last fetch before it), and the
    # timeline from M0 (marker-less: from the restart) to the idle after M1 as kind+clock
    # tokens on the same origin
    xk = {k for k, i in enumerate(n.chain.instrs) if i.role == "x"}
    origin = t_m0 if t_m0 is not None else t_fill
    xc, last_end = [], None
    for e in ev:
        if e.kind == "fetch":
            last_end = e.end
        elif e.instr_index in xk:
            xc.append((e.char, e.clock - origin,
                       e.clock - last_end if last_end is not None else None))
    f["x_cycles"] = xc
    if t_m0 is not None:
        k0 = next(k for k, e in enumerate(ev) if e.marker_id == 0)
        later = idle_gaps(ev, m1 if m1 is not None else k0)
        stop = (later[0][0] + 1) if later else len(ev)
    else:
        k0 = first_after
        later = idle_gaps(ev, restart if restart is not None else k0, LONG_IDLE)
        stop = (later[0][0] + 1) if later else len(ev)
    f["timeline"] = " ".join(f"{e.char}{e.clock - origin}" for e in ev[k0:stop])
    return f


# Family tables ---------------------------------------------------------------

# Baselines. F2-F8 are swept once per marker kind: `knobs["marker"]` holds the
# kind and the variant name starts with "<kind>-". A run's baseline is always
# the same-kind run at the same column (parity x waits); `x_variant` is the
# variant without the kind, so (marker, x_variant, column) indexes the runs.
# A baseline function maps (facts, index, extra) -> baseline facts or None;
# `extra` is another family's index (F7 will look up its F4/F5 singles there).

def index_facts(facts) -> dict:
    """{(marker, x_variant, column): facts}."""
    return {(f["marker"], f["x_variant"], f["column"]): f for f in facts}


def _empty_baseline(f, index, extra):
    if f["x_variant"] == "empty":
        return None
    return index.get((f["marker"], "empty", f["column"]))


def _n0_baseline(f, index, extra):
    stem, _, n = f["x_variant"].rpartition("-n")
    if not stem or n == "0":
        return None
    return index.get((f["marker"], f"{stem}-n0", f["column"]))


# F7 singles: the k=1 run of each X lives in the family that swept it.
F7_SOURCE = {"ld_bw": "F4", "mov_aw_dw": "F3", "st_bw": "F5", "add_m_aw": "F5",
             "push_aw": "F5", "out_imm_al": "F5"}


def f7_extra(waits=(0, 1, 2)) -> dict:
    """{family: index_facts} of the F3/F4/F5 runs F7 needs (x-k1 singles and the
    empties), loaded from the corpus."""
    out = {}
    for family in sorted(set(F7_SOURCE.values())):
        names = {f"{x}-k1" for x, src in F7_SOURCE.items() if src == family} | {"empty"}
        runs = [r for r in load_runs(family, waits)
                if r["chain"]["id"].rsplit("-p", 1)[0].split("-", 2)[-1] in names]
        out[family] = index_facts([run_facts(normalize(r)) for r in runs])
    return out


def f7_singles(f, extra):
    """(single a, single b, empty of a's family, empty of b's family) facts, same
    kind and column, from `extra` ({family: index}); None where missing."""
    if not extra:
        return None, None, None, None
    knobs = f.get("knobs", {})
    got = []
    for x in (knobs.get("a"), knobs.get("b")):
        index = extra.get(F7_SOURCE.get(x), {})
        got.append(index.get((f["marker"], f"{x}-k1", f["column"])))
    for x in (knobs.get("a"), knobs.get("b")):
        index = extra.get(F7_SOURCE.get(x), {})
        got.append(index.get((f["marker"], "empty", f["column"])))
    return tuple(got)


def _f7_baseline(f, index, extra):
    # cost(A B) against the same-kind empty of A's source family.
    return f7_singles(f, extra)[2]


def f7_interactions(facts, extra) -> dict:
    """Per F7 run: interaction = dM(a b) - dM(a) - dM(b) + dM(empty), singles and
    empty of the same kind and column (empty of a's family); sets f["interaction"]
    and returns {"cells": {(marker, column): {a: {b: (value, a parity, b parity)}}},
    "empties": {(marker, column): {family: dM}} where they disagree}."""
    cells: dict = defaultdict(lambda: defaultdict(dict))
    empties: dict = {}
    for f in facts:
        sa, sb, ea, eb = f7_singles(f, extra)
        knobs = f["knobs"]
        value = None
        if None not in (sa, sb, ea) and None not in (f["dM"], sa["dM"], sb["dM"], ea["dM"]):
            value = f["dM"] - sa["dM"] - sb["dM"] + ea["dM"]
        f["interaction"] = value
        pa, pb = (f["x"][0]["parity"], f["x"][1]["parity"]) if len(f["x"]) == 2 else ("?", "?")
        cells[(f["marker"], f["column"])][knobs["a"]][knobs["b"]] = (value, pa, pb)
    for marker, column in cells:
        dms = {fam: idx.get((marker, "empty", column), {}).get("dM")
               for fam, idx in (extra or {}).items()}
        if len({v for v in dms.values() if v is not None}) > 1:
            empties[(marker, column)] = dms
    return {"cells": {k: {a: dict(r) for a, r in v.items()} for k, v in cells.items()},
            "empties": empties}


def f6_drain_slopes(facts) -> dict:
    """{"<kind>-<x>[ d4]": {column: (slope n4, slope n6)}}: (cost(n) - cost(n2)) / (n - 2),
    the clocks each extra drainer adds. A full queue gives the drainer's EU time;
    a starved queue gives the fetch supply of its 3 bytes, 1.5 (3 + w) clocks
    (4.5 / 6 / 7.5 at 0 / 1 / 2 waits; 2 (3 + w) for the 4-byte D4)."""
    index = index_facts(facts)
    out = defaultdict(dict)
    for (marker, xv, column), f in index.items():
        stem, _, n = xv.rpartition("-n")
        if n not in ("2", "2d4"):
            continue
        d4 = n.endswith("d4")
        base = f.get("cost")
        slopes = []
        for m in (4, 6):
            g = index.get((marker, f"{stem}-n{m}{'d4' if d4 else ''}", column))
            c = g.get("cost") if g else None
            slopes.append((c - base) / (m - 2) if c is not None and base is not None else None)
        out[f"{marker}-{stem}{' d4' if d4 else ''}"][column] = tuple(slopes)
    return dict(out)


def _f10_baseline(f, index, extra):
    """F10: the same X with no instruction before it (P = none), same kind and column."""
    p, _, x = f["x_variant"].partition("-")
    if p == "none" or not x:
        return None
    return index.get((f["marker"], f"none-{x}", f["column"]))


def _f14_baseline(f, index, extra):
    """F14: the empty cost frame of the same marker and column (series T's for T and G,
    series O's for O)."""
    series, marker = f["knobs"].get("series"), f["marker"]
    if marker == "none" or f["knobs"].get("x") in (None, []):
        return None
    return index.get((marker, f"{'o' if series == 'o' else 't'}-{marker}-empty", f["column"]))


def _f15_baseline(f, index, extra):
    """F15: the empty cost frame of series A at the same marker and column."""
    if f["marker"] == "none" or not f["knobs"].get("x"):
        return None
    return index.get((f["marker"], f"a-{f['marker']}-empty", f["column"]))


def _f16_baseline(f, index, extra):
    """F16: the empty PUSH frame of series R, the empty OUT frame of series L."""
    if f["marker"] == "none" or not f["knobs"].get("x"):
        return None
    empty = {"push": "r-push-empty", "out": "l-out-empty"}.get(f["marker"])
    return index.get((f["marker"], empty, f["column"]))


BASELINES = {
    "F16": ("dM", _f16_baseline),
    "F15": ("dM", _f15_baseline),
    "F14": ("dM", _f14_baseline),
    "F10": ("dM", _f10_baseline),
    "F2": ("restart_clock", _empty_baseline), "F9": ("restart_clock", _empty_baseline),
    "F3": ("dM", _empty_baseline), "F4": ("dM", _empty_baseline),
    "F5": ("dM", _empty_baseline), "F8": ("dM", _empty_baseline),
    "F6": ("dM", _n0_baseline), "F7": ("dM", _f7_baseline),
    "F23": ("dM", _empty_baseline), "F25": ("dM", _empty_baseline),
}


def _f27_baseline(f, index, extra):
    """(WP56) F27: the empty frame of the same marker, RFM and column (x_variant
    "<rfm>-empty": the FCh runs against the FCh empty, the ECh twins against the ECh one)."""
    knobs = f.get("knobs", {})
    if knobs.get("series") == "empty" or knobs.get("rfm") is None:
        return None
    return index.get((f["marker"], f"{knobs['rfm']:02x}-empty", f["column"]))


BASELINES.update({"F26": ("dM", _empty_baseline), "F27": ("dM", _f27_baseline)})
# (WP59) F28 (FCh with ECh twins) and F29 (ECh) carry the RFM in the id as F27 does: the empty
# frame of the same marker, RFM and column (the fence cells against the count-31 empty frame)
BASELINES.update({"F28": ("dM", _f27_baseline), "F29": ("dM", _f27_baseline)})


def _f24_baseline(f, index, extra):
    """(WP66) F24: the chain the knob `baseline` names (its x_variant: the empty frame, or MOV
    CW,n [D^d] alone), same marker and column; None for the controls."""
    name = f.get("knobs", {}).get("baseline")
    return index.get((f["marker"], name, f["column"])) if name else None


BASELINES.update({"F24": ("dM", _f24_baseline)})
# (WP73) F30: the empty frame of the same marker (out, push or store) and column
BASELINES.update({"F30": ("dM", _empty_baseline)})
# (WP73) F31 (OUT marker only): the empty frame of the same column
BASELINES.update({"F31": ("dM", _empty_baseline)})
# (WP74) F32 / F33: the chain the knob `baseline` names (the empty frame or X's lead alone:
# MOV CL,n, the multiply / divide lead, STC / CLC ; MOV CW,n), same marker and column
BASELINES.update({"F32": ("dM", _f24_baseline), "F33": ("dM", _f24_baseline)})


def k_series(cost: dict) -> dict:
    """(WP74) {stem: {column: (costs by k, slope, intercept)}} for every variant stem with a
    -k1 and a -k2 cell (the stem the variant less -k<k>): slope cost(k2) - cost(k1),
    intercept cost(k1) - slope; costs by k as {k: cost} (k4 too where it exists)."""
    import re
    stems: dict = defaultdict(dict)
    for variant, cols in cost.items():
        m = re.match(r"^(.*)-k(\d+)(-.*)?$", variant)
        if not m:
            continue
        stem = m.group(1) + (m.group(3) or "")
        for column, c in cols.items():
            stems[stem].setdefault(column, {})[int(m.group(2))] = c
    out: dict = defaultdict(dict)
    for stem, cols in stems.items():
        for column, by_k in cols.items():
            if 1 in by_k and 2 in by_k:
                slope = by_k[2] - by_k[1]
                out[stem][column] = (dict(sorted(by_k.items())), slope, by_k[1] - slope)
    return dict(out)


def f24_apply(facts, normalized):
    """(WP66) F24: per run, the string forms' elements on the bus (normalize.string_elements
    groups each form's matched cycles by element; a REP compare's extra read after its last
    element, the overrun, is kept apart). str_elements: elements seen (compared / moved, as
    the iters knob); str_t: each element's first cycle rel t_M0; str_spacing: start-to-start
    between elements; str_cycles: each element's cycles as kind char + clock rel t_M0;
    str_overrun: the overrun's cycles the same way (None without one); str_overrun_gap: its
    first cycle less the last element's first cycle (the spacing to the read nothing
    compares); str_fetches: fetches starting between the first element's first cycle and the
    stream's last cycle (the overrun's when there is one: what the stream lets in);
    str_next_fetch: the first fetch after the stream's last cycle, clocks from that cycle's
    start (None when there is none before M1); str_window: the bus cycles from the first
    element's first cycle to M1, one char each. None throughout for the controls and a run
    whose cycles did not match (normalize strict raises first)."""
    from .normalize import string_elements
    keys = ("str_elements", "str_t", "str_spacing", "str_cycles", "str_overrun",
            "str_overrun_gap", "str_fetches", "str_next_fetch", "str_window")
    for f in facts:
        for key in keys:
            f[key] = None
        n = normalized[f["id"]]
        t_m0 = n.t_markers.get(0)
        if n.access_mismatch is not None or t_m0 is None:
            continue
        runs = string_elements(n.chain)
        if not runs:
            continue
        groups, overruns = [], []
        for k, run in sorted(runs.items()):
            evs = [e for e in n.events if e.instr_index == k
                   and e.kind not in ("fetch", "refresh")]
            at = 0
            for element in run.elements:
                groups.append(evs[at:at + len(element)])
                at += len(element)
            if run.overrun:
                overruns.append(evs[at:at + len(run.overrun)])
        f["str_elements"] = len(groups)
        if not groups:
            continue
        cyc = lambda g: " ".join(f"{e.char}{e.clock - t_m0}" for e in g)
        starts = [g[0].clock for g in groups]
        f["str_t"] = [t - t_m0 for t in starts]
        f["str_spacing"] = [b - a for a, b in zip(starts, starts[1:])]
        f["str_cycles"] = [cyc(g) for g in groups]
        if overruns:
            f["str_overrun"] = " | ".join(cyc(g) for g in overruns)
            f["str_overrun_gap"] = overruns[-1][0].clock - groups[-1][0].clock
        first = groups[0][0]
        last = max([g[-1] for g in groups] + [g[-1] for g in overruns], key=lambda e: e.clock)
        f["str_fetches"] = sum(1 for e in n.events if e.kind == "fetch"
                               and first.clock < e.clock < last.clock)
        t_m1 = n.t_markers.get(1)
        nxt = next((e for e in n.events if e.kind == "fetch" and e.clock > last.clock
                    and (t_m1 is None or e.clock < t_m1)), None)
        f["str_next_fetch"] = nxt.clock - last.clock if nxt is not None else None
        i0 = n.events.index(first)
        i1 = next((i for i, e in enumerate(n.events) if e.marker_id == 1), len(n.events) - 1)
        f["str_window"] = interleave(n.events, i0, i1 + 1)


def apply_costs(family, facts, extra=None) -> dict:
    """Set f["cost"] against the family's same-kind baseline; {variant: {column: cost}}."""
    metric, base = BASELINES[family]
    index = index_facts(facts)
    cost = defaultdict(dict)
    for f in facts:
        b = base(f, index, extra)
        if b is not None and f.get(metric) is not None and b.get(metric) is not None:
            f["cost"] = f[metric] - b[metric]
            f["baseline"] = b["id"]
            cost[f["variant"]][f["column"]] = f["cost"]
    return dict(cost)


def kind_pairs(facts, key="cost") -> dict:
    """{x_variant: {column: (push value, out value, push - out)}} where both kinds exist."""
    index = index_facts(facts)
    out = defaultdict(dict)
    for (marker, xv, column), f in index.items():
        if marker != "push":
            continue
        g = index.get(("out", xv, column))
        if g is None:
            continue
        p, o = f.get(key), g.get(key)
        if p is None and o is None:
            continue
        out[xv][column] = (p, o, p - o if p is not None and o is not None else None)
    return dict(out)


PRIMARY = {"F0": "fill_words", "F0w": "idle_gap", "F1": "dM", "F2": "restart_clock",
           "F9": "restart_clock", "F11": "t_end"}


def family_facts(family: str, waits=(0, 1, 2), files=None, extra=None) -> dict:
    """{'runs': [facts], 'rows': {variant: {column: facts}}, 'repeats': {id: facts of
    the repeat trace}, 'normalized': {id: Normalized}, 'cost', 'odd_minus_even',
    'k_differences' (and 'marker_cost' for F1)}."""
    runs = load_runs(family, waits, files)
    if family == "F7" and extra is None:
        extra = f7_extra(waits)
    normalized = [normalize(r) for r in runs]
    facts = [run_facts(n) for n in normalized]
    repeats = {}
    for r in runs:
        if r.get("repeat_trace"):
            repeats[r["chain"]["id"]] = run_facts(normalize(r, "repeat_trace"))
    rows: dict = defaultdict(dict)
    for f in facts:
        rows[f["variant"]][f["column"]] = f
    out = {"family": family, "runs": facts, "repeats": repeats, "rows": dict(rows),
           "normalized": {n.run_id: n for n in normalized}}

    metric = PRIMARY.get(family, "dM")
    if family in BASELINES:
        metric = BASELINES[family][0]
        out["cost"] = apply_costs(family, facts, extra)
        out["push_minus_out"] = kind_pairs(facts)
    if family == "F7":
        out["interactions"] = f7_interactions(facts, extra)
        out["push_minus_out_interaction"] = kind_pairs(facts, "interaction")
    if family == "F6":
        out["drain_slopes"] = f6_drain_slopes(facts)
    if family == "F1":
        out["marker_cost"] = f1_marker_cost(rows)
    if family == "F13":
        f13_apply(facts, out["normalized"], waits)
    if family == "F17":
        f17_apply(facts, out["normalized"])
    if family == "F18":
        f18_apply(facts, out["normalized"])
    if family in ("F24", "F33"):
        f24_apply(facts, out["normalized"])       # (WP74) F33's REPC / REPNC elements
    if family in ("F32", "F33"):
        out["k_series"] = k_series(out["cost"])
    out["metric"] = metric
    out["odd_minus_even"] = odd_minus_even(rows, metric)
    out["k_differences"] = k_differences(rows, "cost" if "cost" in out else metric)
    return out


def odd_minus_even(rows, metric) -> dict:
    out = defaultdict(dict)
    for variant, cols in rows.items():
        for column, f in cols.items():
            if not column.startswith("pE"):
                continue
            other = cols.get("pO" + column[2:])
            if other and f.get(metric) is not None and other.get(metric) is not None:
                out[variant][column[3:] or "-"] = other[metric] - f[metric]
    return dict(out)


def k_differences(rows, metric) -> dict:
    """X^k(b) - X^k(a) for consecutive k of the same X: {'name k2-k1': {column: d}}."""
    series = defaultdict(dict)
    for variant in rows:
        parts = variant.split("-")
        ks = [p for p in parts if len(p) > 1 and p[0] == "k" and p[1:].isdigit()]
        if not ks:
            continue
        key = "-".join(p for p in parts if p != ks[0])
        series[key][int(ks[0][1:])] = variant
    out = {}
    for key, by_k in series.items():
        ks = sorted(by_k)
        for a, b in zip(ks, ks[1:]):
            cols = {}
            for column, fb in rows[by_k[b]].items():
                fa = rows[by_k[a]].get(column)
                if fa and fa.get(metric) is not None and fb.get(metric) is not None:
                    cols[column] = fb[metric] - fa[metric]
            out[f"{key} k{b}-k{a}"] = cols
    return out


def f1_marker_cost(rows) -> dict:
    """Per marker kind and column: clocks per extra marker.

    `slope`: (t_M[n-1] - t_M[0]) / (n-1) for n = 2 and 4; `m4_minus_m2`:
    (t_M3 - t_M0) - (t_M1 - t_M0) over two extra markers, i.e. the marginal
    cost of markers 3 and 4; `latency`: t_M0 relative to t_fill for n = 1/2/4.
    """
    out = defaultdict(dict)
    kinds = sorted({v.split("-")[0] for v in rows})
    for kind in kinds:
        cols = sorted({c for v in rows if v.startswith(kind + "-") for c in rows[v]})
        for column in cols:
            cell = {}
            for n in (1, 2, 4):
                f = rows.get(f"{kind}-m{n}", {}).get(column)
                if f is None:
                    continue
                cell[f"latency_m{n}"] = f["t_M"][0] if f["t_M"] else None
                if n > 1 and len(f["t_M"]) == n:
                    cell[f"slope_m{n}"] = (f["t_M"][-1] - f["t_M"][0]) / (n - 1)
            m2 = rows.get(f"{kind}-m2", {}).get(column)
            m4 = rows.get(f"{kind}-m4", {}).get(column)
            if m2 and m4 and len(m4["t_M"]) == 4:
                cell["m4_minus_m2"] = (m4["t_M"][3] - m4["t_M"][0]) - m2["dM"]
            out[kind][column] = cell
    return dict(out)


# F13 (WP17, the refresh machine's EU side) ------------------------------------------

def x_end_fetch(n: Normalized) -> tuple:
    """Marker-less PAD LS X LS END with a 4-byte X: (restart clock, X's end fetch clock,
    whether that fetch starts on the clock after a refresh ends), rel t_fill. The restart
    fetch is the first after the fill's idle gap (the first LS's end, X's bytes taken).
    While X runs the queue holds at most the 6 bytes after it, so the word holding X's
    11th byte on (w) is fetched only once the second LS takes its bytes, at X's end. When
    the word before it (w - 2) was fetched late (its request lost to a refresh: later than
    6 clocks after the restart) and w follows it back to back, the late fetch is the one
    the second LS's take raised, and it marks X's end instead. Blocked: a refresh held
    the bus until then, so X ended on or before."""
    ev = n.events
    gaps = idle_gaps(ev, n.ls_fetch_index)
    if not gaps:
        return None, None, False
    restart = next((e for e in ev[gaps[0][1]:] if e.kind == "fetch"), None)
    if restart is None:
        return None, None, False
    x = next(i for i in n.chain.instrs if i.role == "x")
    target = n.chain_base + x.offset + 10
    w = target + ((target - restart.addr) % 2)       # the first fetch word from X's 11th byte
    later = [e for e in ev if e.kind == "fetch" and e.clock > restart.clock]
    fw = next((e for e in later if e.addr == w), None)
    fp = next((e for e in later if e.addr == w - 2), None)
    if fw is None:
        return restart.clock - n.t_fill, None, False
    end = fw
    if fp is not None and fp.clock > restart.clock + 6 and fw.clock == fp.end + 1:
        end = fp
    k = ev.index(end)
    prev = ev[k - 1]
    blocked = prev.kind == "refresh" and prev.end + 1 == end.clock
    return restart.clock - n.t_fill, end.clock - n.t_fill, blocked


def f13_extra(waits=(0, 1, 2)) -> dict:
    """The refresh-off baselines of the F13 cost frames, from F3: {(marker, x_variant,
    column): dM} for the empty frame, shl_cl{0,1,2,4,8,16,31}, mulu_dw k1/k2, nop k4."""
    names = {"empty", "mulu_dw-k1", "mulu_dw-k2", "nop-k4"} | {
        f"shl_cl{n}-k1" for n in (0, 1, 2, 4, 8, 16, 31)}
    runs = [r for r in load_runs("F3", waits)
            if r["chain"]["id"].rsplit("-p", 1)[0].split("-", 2)[-1] in names]
    return {k: f["dM"] for k, f in index_facts([run_facts(normalize(r)) for r in runs]).items()}


def _off_dm(base: dict, marker: str, knobs: dict, column: str):
    """Refresh-off dM of an F13 cost frame from F3 (measured where F3 has the count; a
    count F3 lacks: shl_cl1 + 2 (n - 1), the 2 clocks per count F3 shows at every count;
    NOP^8: nop-k4 + 4 x 4, the F3 slope)."""
    x = knobs.get("x")
    if x == "mulu_dw":
        return base.get((marker, f"mulu_dw-k{knobs['k']}", column))
    if x == "nop":
        b = base.get((marker, "nop-k4", column))
        return None if b is None else b + 4 * (knobs["k"] - 4)
    n = knobs["n"]
    got = base.get((marker, f"shl_cl{n}-k1", column))
    if got is not None or n == 0:
        return got
    b = base.get((marker, "shl_cl1-k1", column))
    return None if b is None else b + 2 * (n - 1)


def f13_apply(facts, normalized, waits=(0, 1, 2), base=None):
    """Per F13 run: refresh clocks rel t_fill ("refreshes"), and per series: S/S0 the
    restart (first LS's end), X's end fetch, both rel t_fill, and D = (X end - restart)
    minus the same in the refresh-off S0 run (S0 counts 1, 2, 4, 8, 16, 31; between them
    2 clocks per count, as S0 shows), with the refreshes between the restart and X's end
    rel the restart; C/U/N the refresh-off dM from F3 (`dM_off`), cost = dM - dM_off, and
    the refreshes from M0 - 4 to M1 rel M0; marker-less U/N t_end - t_end of the empty
    frame r-rfm-f0 in the same cell; R the refresh lengths and gaps."""
    if base is None:
        try:
            base = f13_extra(waits)
        except FileNotFoundError:
            base = {}
    by = {(f["variant"], f["column"]): f for f in facts}
    for f in facts:
        n = normalized[f["id"]]
        f["refreshes"] = [e.clock - n.t_fill for e in n.events if e.kind == "refresh"]
        f["refresh_lengths"] = sorted({e.length for e in n.events if e.kind == "refresh"})
        k = f["knobs"]
        series = k.get("series")
        if series in ("s", "s0"):
            f["restart"], f["x_end"], f["x_end_blocked"] = x_end_fetch(n)
    s0 = defaultdict(dict)
    for f in facts:
        if f["knobs"].get("series") == "s0" and f.get("x_end") is not None:
            s0[f["column"]][f["knobs"]["n"]] = f["x_end"] - f["restart"]
    for f in facts:
        k = f["knobs"]
        series = k.get("series")
        if series in ("s", "s0") and f.get("x_end") is not None:
            ref = s0.get(f["column"], {})
            off = ref.get(k["n"])
            if off is None and ref:
                m = min(ref, key=lambda c: abs(c - k["n"]))
                off = ref[m] + 2 * (k["n"] - m)
            f["x_len"] = f["x_end"] - f["restart"]
            f["D"] = f["x_len"] - off if off is not None else None
            f["x_refreshes"] = [r - f["restart"] for r in f["refreshes"]
                                if f["restart"] - 5 < r < f["x_end"]]
        elif series in ("c", "u", "n") and f["dM"] is not None:
            off = _off_dm(base, f["marker"], k, f["column"])
            f["dM_off"] = off
            f["cost"] = f["dM"] - off if off is not None else None
            m0, m1 = f["t_M"][0], f["t_M"][1]
            f["window_refreshes"] = [r - m0 for r in f["refreshes"] if m0 - 4 <= r <= m1]
        elif series in ("u", "n"):
            e = by.get(("r-rfm-f0", f["column"]))
            f["t_end_minus_empty"] = (f["t_end"] - e["t_end"]
                                      if e and e["t_end"] is not None else None)
        if series == "r":
            f["refresh_gaps"] = [b - a for a, b in zip(f["refreshes"], f["refreshes"][1:])]


# F17 (WP23): the chain turns refresh on itself (forms.rfm_*); every series is marker-less
# but C. The control of an S run is the E run of the same shape (RFMON ECh), of a W run its
# W ECh twin; P runs (refresh on from the prelude) have none.
F17_CONTROL = {"s": "e", "d": "e", "w": "w"}


def ls_end(n) -> int | None:
    """The second LS's end rel t_fill: the first event after the last idle gap (refresh
    cycles neither open nor close a gap), the END block's first fetch."""
    gaps = n.idle_gaps()
    return n.events[gaps[-1][1]].clock - n.t_fill if gaps and n.t_fill is not None else None


def f17_apply(facts, normalized):
    """Per F17 run: the refreshes rel t_fill ("refreshes"); the first ("first_refresh");
    their residues against clock 0 modulo the written interval ("grid": the timer's phase,
    a constant of the prelude); the second LS's end ("ls_end") and D = ls_end minus the
    refresh-off control's (RFMON ECh in the same shape, E for S and D, the W ECh twin for
    W; None for P and C)."""
    from .types import refresh_rft, rfm_writes
    by = {(f["variant"], f["column"]): f for f in facts}
    for f in facts:
        n = normalized[f["id"]]
        refs = [e.clock for e in n.events if e.kind == "refresh"]
        f["refreshes"] = [c - n.t_fill for c in refs]
        f["first_refresh"] = f["refreshes"][0] if refs else None
        rft = max([refresh_rft(n.chain.rfm)] + [refresh_rft(v) for _, v in rfm_writes(n.chain)])
        interval = 16 << rft
        idle = [c for c in refs if n.t_fill + 100 < c < (n.t_end or 10 ** 6) - 20]
        f["grid"] = sorted({c % interval for c in idle})
        f["ls_end"] = ls_end(n)
    for f in facts:
        series = f["knobs"].get("series")
        ctl = F17_CONTROL.get(series)
        f["D"] = None
        if ctl is None or f["ls_end"] is None:
            continue
        v = f["variant"]
        twin = ("e-" + v.split("-", 1)[1] if series in ("s", "d")
                else "w-ec-" + v.split("-", 2)[2])
        g = by.get((twin, f["column"]))
        if g is not None and g["ls_end"] is not None and g is not f:
            f["D"] = f["ls_end"] - g["ls_end"]


# F18 (WP24): A/AC end the prelude with a marker (Chain.prelude_marker) before the first LS;
# B/BD are the exec-boundary ladder (F17 S's shape with a NOP / ES: NOP ladder before X).


def f18_apply(facts, normalized):
    """Per F18 run, clocks rel clock 0 ("abs"): the prelude marker's cycle ("pre_marker"),
    t_fill ("fill"), the first LS's end (the restart fetch after the fill's idle gap,
    "ls1_end") and the refreshes before it ("ls1_refreshes"); rel t_fill: the refreshes
    ("refreshes"), the first ("first_refresh") and the second LS's end ("ls_end")."""
    for f in facts:
        n = normalized[f["id"]]
        refs = [e.clock for e in n.events if e.kind == "refresh"]
        f["pre_marker"] = n.t_pre_marker
        f["fill"] = n.t_fill
        ev = [e for e in n.events if e.kind != "refresh"]
        k = next((i for i, e in enumerate(ev) if e.kind == "fetch" and e.end == n.t_fill), None)
        f["ls1_end"] = ev[k + 1].clock if k is not None and k + 1 < len(ev) else None
        f["ls1_refreshes"] = [c for c in refs if f["ls1_end"] is not None and c < f["ls1_end"]]
        f["refreshes"] = [c - n.t_fill for c in refs] if n.t_fill is not None else []
        f["first_refresh"] = f["refreshes"][0] if f["refreshes"] else None
        f["ls_end"] = ls_end(n)
