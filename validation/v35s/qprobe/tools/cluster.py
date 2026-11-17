#!/usr/bin/env python3
"""cluster.py: cluster the corpus runs that diverge from silicon (the RTL replay's miss list,
and the reading model's misses from corpus_model.py) by a first-divergence signature.

    PYTHONPATH=host/src:. python3 TOOLS/cluster.py --model corpus_model.jsonl \\
        --rtl-miss miss-v35_chk.jsonl [--chains romcheck_chains.json] [--top 25] \\
        [--source rtl|model|both] [--out clusters.json]

Run from a repo checkout root (the corpus is read only when the chains cache is missing).

Signature of a divergence (its first divergent event, at run clock c):
  instr     the instruction executing at c: from the model's timeline of the run (its
            boundaries, in run clocks; the instruction whose routine runs on clock c), named by
            the chain: the form name (form + addressing mode) for a body instruction, M<i>:<kind>
            for a marker, LS:movcl / LS:shl, END:movdw / END:out / END:halt / END:nop, PAD;
            `subject?` when the run has no model timeline (no routine / not modelled: the
            chain's first body instruction is named instead, marked with `?`)
  prev      the instruction before it (same naming)
  parity    the alignment of the first body byte (the chain's parity)
  waits     memory waits
  held      bytes held in the queue at instr's boundary (the model's count; `?` without it)
  div       the first divergent event's kind: fetch / read / write / io-write / io-read early or
            late by n (the other side's clock minus silicon's), missing / extra <kind> (the
            event list shifted by one), <kind> vs <kind>; for the RTL rows the replay's pair
            (silicon's event, the RTL's), with silicon's neighbour from the model row when the
            model agrees with silicon there
  behind    the frame: the subject directly behind the frame's first marker (out / push /
            store), or `-`
View 1: the whole signature. View 2: the signature without instr (the states that cut across
instructions). View 1w: view 1 without waits and held (the waits mostly move only the dt).
View 3 (coarse): prev, parity, behind.
The model's timeline is the model's, so after the model's own first divergence (model-miss
rows, or RTL rows of runs the model misses earlier) the instruction attribution is the model's
guess; such rows are marked `t?` in the JSON (`timeline_ok`: false).
"""

from __future__ import annotations

import argparse
import collections
import json
import multiprocessing
import sys
from pathlib import Path

sys.path[:0] = ["host/src", "."]

KIND = {"fetch": "F", "data_read": "R", "stack_read": "R", "data_write": "W",
        "stack_write": "W", "io_write": "O", "io_read": "I", "refresh": "X"}
KN = {"F": "fetch", "R": "read", "W": "write", "O": "io-write", "I": "io-read", "X": "refresh"}


def _load_family(fam):
    from validation.v35s.chains.normalize import load_runs
    try:
        rs = load_runs(fam, (0, 1, 2))
    except FileNotFoundError:
        return []
    return [{"chain": r["chain"], "code_hex": r["code_hex"], "chain_base": r["chain_base"]}
            for r in rs]


def chains(cache: Path, families, jobs=3):
    if cache.exists():
        return {r["chain"]["id"]: r["chain"] for r in json.loads(cache.read_text())}
    out = []
    with multiprocessing.get_context("fork").Pool(jobs) as pool:
        for rs in pool.imap(_load_family, families):
            out += rs
    cache.write_text(json.dumps(out))
    return {r["chain"]["id"]: r["chain"] for r in out}


def name_at(ch, off):
    for i in ch["instrs"]:
        n = len(i["code"]) // 2
        if not i["offset"] <= off < i["offset"] + n:
            continue
        k = off - i["offset"]
        if i["role"] == "ls":
            return "LS:movcl" if k < 2 else "LS:shl"
        if i["role"] == "end":
            return "END:movdw" if k < 3 else "END:out" if k == 3 else "END:halt" if k == 4 \
                else "END:nop"
        if i["role"] == "marker":
            return f"M{i['marker_id']}:{ch['marker_kind']}"
        if i["role"] == "pad":
            return "PAD"
        return i["form"] + ("" if k == 0 else f"+{k}")
    return f"?@{off}"


def subject(ch):
    return next((i["form"] for i in ch["instrs"] if i["role"] == "x"), "-")


def behind(ch):
    ins = ch["instrs"]
    for k, i in enumerate(ins[:-1]):
        if i["role"] == "marker" and i.get("marker_id") == 0:
            return ch["marker_kind"] if ins[k + 1]["role"] == "x" else "-"
    return "-"


def at_clock(tl, c):
    """(instr offset, prev offset, held at its boundary) of the instruction running on c."""
    cur = prev = None
    held = None
    for t, off, h in tl:
        if t < c:
            prev, cur, held = cur, off, h
        else:
            break
    return cur, prev, held


def rtl_div(first, t_fill, mrow):
    """(run clock, class) of an RTL row's first divergence."""
    if not first:
        return None, "no divergence recorded"
    k, a, b = first
    if a is None and isinstance(b, list):
        return t_fill + b[0], f"extra {KN.get(KIND.get(b[1], '?'), b[1])}"
    if a is None:
        return None, f"rtl {b}"
    c = t_fill + a[0]
    ka = KIND.get(a[1], "?")
    if not isinstance(b, list):
        return c, f"missing {KN.get(ka, ka)}"
    kb = KIND.get(b[1], "?")
    if ka == kb and (ka != "F" or a[2] == b[2]):
        dt = b[0] - a[0]
        return c, f"{KN[ka]} {'early' if dt < 0 else 'late'} by {abs(dt)}"
    if ka == "F" and kb == "F":
        return c, "fetch address differs"
    return c, f"{KN.get(ka, ka)} vs {KN.get(kb, kb)}"


def signature(src, run_id, ch, mrow, c, div):
    tl = (mrow or {}).get("timeline") or []
    if tl and c is not None:
        cur, prev, held = at_clock(tl, c)
        instr = name_at(ch, cur) if cur is not None else "LS:shl"
        pv = name_at(ch, prev) if prev is not None else "LS:movcl"
        held = "?" if held is None else held
    else:
        instr, pv, held = subject(ch) + "?", "?", "?"
    ok = bool(tl) and (mrow.get("exact") or (mrow.get("first") and c is not None
                                             and c <= mrow["first"]["clock"]))
    return {"run": run_id, "src": src, "instr": instr, "prev": pv,
            "parity": ch["parity"][0].upper(), "waits": ch["waits"], "held": held, "div": div,
            "behind": behind(ch), "clock": c, "timeline_ok": bool(ok),
            "from_m0": None if c is None or not mrow or mrow.get("t_m0") is None
            else c - mrow["t_m0"]}


V1 = ("instr", "prev", "parity", "waits", "held", "div", "behind")
V2 = ("prev", "parity", "waits", "held", "div", "behind")
V3 = ("prev", "parity", "behind")
V1W = ("instr", "prev", "parity", "div", "behind")


def show(rows, fields, top, title, log):
    cl = collections.defaultdict(list)
    for r in rows:
        cl[tuple(r[f] for f in fields)].append(r)
    ranked = sorted(cl.items(), key=lambda kv: -len(kv[1]))
    log(f"\n{title}: {len(rows)} divergences in {len(cl)} clusters; key = {', '.join(fields)}")
    for i, (k, rs) in enumerate(ranked[:top], 1):
        ex = [r["run"] for r in rs[:: max(1, len(rs) // 3)][:3]]
        sub = ""
        if "instr" not in fields:
            ins = collections.Counter(r["instr"] for r in rs).most_common(3)
            sub = "  instrs: " + ", ".join(f"{a} {b}" for a, b in ins)
        log(f"  {i:>3}. {len(rs):>5}  " + " | ".join(f"{f}={v}" for f, v in zip(fields, k)))
        log(f"         e.g. {', '.join(ex)}{sub}")
    return {" | ".join(f"{f}={v}" for f, v in zip(fields, k)): [r["run"] for r in rs]
            for k, rs in ranked}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 2)[2])
    ap.add_argument("--model", required=True, help="corpus_model.py's JSON lines")
    ap.add_argument("--rtl-miss", help="the RTL replay's per-run rows (miss-v35_chk.jsonl)")
    ap.add_argument("--chains", type=Path, default=Path("romcheck_chains.json"),
                    help="the corpus chains cache (romcheck.py's; built when missing)")
    ap.add_argument("--source", choices=("rtl", "model", "both"), default="both")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out", type=Path, default=Path("clusters.json"))
    a = ap.parse_args(argv)
    mrows = {}
    for line in open(a.model):
        r = json.loads(line)
        mrows[r["run"]] = r
    fams = sorted({r["family"] for r in mrows.values()}, key=lambda f: (len(f), f))
    ch = chains(a.chains, fams)
    out = {"rtl": [], "model": []}
    if a.rtl_miss and a.source in ("rtl", "both"):
        for line in open(a.rtl_miss):
            x = json.loads(line)
            if x["exact"] or x["run"] not in ch:
                continue
            m = mrows.get(x["run"])
            c, div = rtl_div(x.get("first"), (m or {}).get("t_fill") or 0, m)
            out["rtl"].append(signature("rtl", x["run"], ch[x["run"]], m, c, div))
    if a.source in ("model", "both"):
        for rid, m in mrows.items():
            if m["status"] != "ok" or m["exact"] or rid not in ch:
                continue
            f = m["first"]
            out["model"].append(signature("model", rid, ch[rid], m, f["clock"], f["class"]))
    res = {"rows": out, "views": {}}
    for src in ("rtl", "model"):
        rs = out[src]
        if not rs:
            continue
        name = "RTL vs silicon" if src == "rtl" else "model vs silicon"
        print(f"\n===== {name}: {len(rs)} diverging runs "
              f"({sum(not r['timeline_ok'] for r in rs)} attributed past the model's own "
              f"divergence or without a timeline)")
        res["views"][src] = {
            "v1": show(rs, V1, a.top, f"{name}, view 1 (instruction + state)", print),
            "v2": show(rs, V2, a.top, f"{name}, view 2 (state, no instruction)", print),
            "v1w": show(rs, V1W, a.top, f"{name}, view 1w (view 1 without waits and held)",
                        print),
            "v3": show(rs, V3, a.top, f"{name}, view 3 (coarse: predecessor, parity, frame)",
                       print)}
    a.out.write_text(json.dumps(res, indent=0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
