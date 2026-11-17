#!/usr/bin/env python3
"""corpus_model.py: run the clocked reading model (validation/v35s/qprobe/model_m.py) on the
silicon corpus runs and score it against each run's socket trace.

    PYTHONPATH=host/src:. python3 TOOLS/corpus_model.py [--families F3 F20 ...] [--jobs 3]
        [--rtl-miss MISS.jsonl] [--out OUT.jsonl] [--offsets OFFSETS.json] [--ids SUBSTR ...]
        [--opt K=V ...] [--show N]

Run from a repo checkout root (build/validation/v35s/corpus must be there or symlinked).

The model's input for a corpus run is the run record itself: model_m.simulate reads the chain
(waits, regs, instrs: the first `ls` instruction ends the frame's head), code_hex (the whole
code at 10000h: prelude + chain) and chain_base, exactly as the qprobe runs give them. The model
starts at the end of the first long shift (queue full, bus idle) and predicts every bus event;
its clock origin is the qprobe frame's M0 cycle (TE = the long shift's NXT clock). The corpus
frame has no M0 before the long shift, so the model's clocks are mapped to the run's clocks
(normalize: clock 0 = the fetch of the chain's first word) by one offset per frame group
(waits, parity, prelude marker): the most common difference between silicon's and the model's
first event after the fill over a calibration pass (saved to --offsets; reused when present).

Exactness (the nearest equivalent of `replay --score`'s RTL-exact): silicon's events after
t_fill up to and including the END block's OUT to port FF00h, against the model's events over
the same span, compared as (clock, kind, where): kind F (fetch) / R (data or stack read) /
W (data or stack write) / O (I/O write) / I (I/O read); `where` is the fetch's address and the
I/O write's port (when the model names one). Not compared (the model has no such output): the
data cycles' addresses, every cycle's width and length (the model's lengths follow from the
waits). Not modelled: runs with a refresh cycle in the window, F0w (waits given by WTC), and
runs where the model raises (no routine for an encoding: `no routine`, with the encoding; any
other exception: `model error`).

Output: one JSON line per run (--out), and totals with the cross-tab against the RTL replay's
miss list (--rtl-miss: the land13/land14 miss-v35_chk.jsonl rows {"run", "exact", "first"}).
Each row carries the model's timeline (the boundaries, in run clocks: [clock, chain offset,
bytes held]) for cluster.py.
"""

from __future__ import annotations

import argparse
import collections
import json
import multiprocessing
import sys
import traceback
from pathlib import Path

sys.path[:0] = ["host/src", "."]

from validation.v35s.chains.normalize import load_runs, normalize  # noqa: E402
from validation.v35s.qprobe import model_m  # noqa: E402

KIND = {"fetch": "F", "data_read": "R", "stack_read": "R", "data_write": "W",
        "stack_write": "W", "io_write": "O", "io_read": "I", "refresh": "X"}
END_PORT = 0xFF00
DEFAULT_FAMILIES = None     # from the miss list, else every chains-F* corpus entry

_info_orig = model_m.info
_last_at = [None]


def _info_rec(code, at):
    _last_at[0] = at
    return _info_orig(code, at)


model_m.info = _info_rec


def group_of(chain: dict) -> str:
    return f"w{chain['waits']}-{chain['parity'][0]}-{chain.get('prelude_marker') or 'none'}"


def ls_end(chain: dict) -> int:
    for i in chain["instrs"]:
        if i["role"] == "ls":
            return i["offset"] + len(i["code"]) // 2
    raise ValueError("no ls")


def instr_at(chain: dict, off: int):
    """(index, instr dict, offset inside it) of the chain byte at chain offset `off`."""
    for k, i in enumerate(chain["instrs"]):
        n = len(i["code"]) // 2
        if i["offset"] <= off < i["offset"] + n:
            return k, i, off - i["offset"]
    return None, None, None


def encoding(code: bytes, at: int) -> str:
    """The encoding key of the instruction at `at`: prefixes, opcode, ModR/M mod+rm and the reg
    field of group opcodes, the 0F sub-opcode (the same split DIVERGENCE-r21 uses)."""
    out = []
    while code[at] in (0x26, 0x2E, 0x36, 0x3E, 0xF0, 0xF2, 0xF3, 0x64, 0x65):
        out.append(f"{code[at]:02X}")
        at += 1
    op = code[at]
    out.append(f"{op:02X}")
    if op == 0x0F:
        out.append(f"{code[at + 1]:02X}")
        mb = code[at + 2]
        out.append(f"m{mb >> 6}r{mb & 7}" if mb < 0xC0 else "reg")
        return " ".join(out)
    from validation.v35s.chains.uasm import MODRM_OPS
    if op in MODRM_OPS:
        mb = code[at + 1]
        grp = op in (0x80, 0x81, 0x82, 0x83, 0xC0, 0xC1, 0xD0, 0xD1, 0xD2, 0xD3, 0xF6, 0xF7,
                     0xFE, 0xFF, 0x8F, 0xC6, 0xC7)
        out.append(("/%d " % ((mb >> 3) & 7) if grp else "") + (f"m{mb >> 6}r{mb & 7}"
                                                                   if mb < 0xC0 else "reg"))
    return " ".join(out)


def silicon_events(s):
    """Silicon's events after t_fill to the END's OUT (inclusive), and whether a refresh is in
    that window."""
    out, refresh = [], False
    for e in s.events[s.fill_index + 1:]:
        k = KIND[e.kind]
        if k == "X":
            refresh = True
            continue
        where = e.addr if k == "F" else (e.addr & 0xFFFF) if k in "OI" else None
        out.append((e.clock, k, where))
        if k == "O" and where == END_PORT:
            break
    return out, refresh


def model_events(run, o, d, limit, body):
    log_b, hist = [], {}
    oo = dict(o)
    oo["BLOG"], oo["HIST"] = log_b, hist
    ev = model_m.simulate(run, oo, limit=limit)
    out = []
    for c, k, wh in ev:
        if k == "F":
            wh = wh + body
        elif k == "I" or (k == "O" and wh is None):
            wh = None
        elif k in "RW":
            wh = None
        out.append((c + d, k, wh))
        if k == "O" and wh == END_PORT:
            break
    return out, log_b, hist


def same(a, b):
    """Events equal under the comparison: clock and kind; a fetch's address. The data cycles'
    addresses and the I/O ports are function (the model tracks DW only as MOV DW,imm16 sets it):
    not compared."""
    if a[0] != b[0] or a[1] != b[1]:
        return False
    return a[1] != "F" or a[2] == b[2]


def same_nc(a, b):
    return a[1] == b[1] and (a[1] != "F" or a[2] == b[2])


def first_div(si, mo):
    """(index, silicon event, model event, class) of the first difference, or None."""
    n = min(len(si), len(mo))
    k = next((i for i in range(n) if not same(si[i], mo[i])), None)
    if k is None:
        if len(si) == len(mo):
            return None
        k = n
    a = si[k] if k < len(si) else None
    b = mo[k] if k < len(mo) else None
    return k, a, b, classify(si, mo, k)


def kname(k):
    return {"F": "fetch", "R": "read", "W": "write", "O": "io-write", "I": "io-read"}.get(k, k)


def classify(si, mo, k):
    a = si[k] if k < len(si) else None
    b = mo[k] if k < len(mo) else None
    if a is None:
        return f"extra {kname(b[1])}"
    if b is None:
        return f"missing {kname(a[1])}"
    if same_nc(a, b):
        dt = b[0] - a[0]
        return f"{kname(a[1])} {'early' if dt < 0 else 'late'} by {abs(dt)}"
    # one side has an event the other does not (the rest shifted by one)
    if k + 1 < len(mo) and same_nc(a, mo[k + 1]):
        return f"extra {kname(b[1])}"
    if k + 1 < len(si) and same_nc(si[k + 1], b):
        return f"missing {kname(a[1])}"
    if a[1] == "F" and b[1] == "F":
        return "fetch address differs"
    return f"{kname(a[1])} vs {kname(b[1])}"


def run_one(r, o, offsets, want_offset=False):
    ch = r["chain"]
    rid = ch["id"]
    row = {"run": rid, "family": ch["family"], "group": group_of(ch), "status": "ok",
           "exact": False}
    if ch["waits"] < 0:
        row["status"] = "not modelled: waits from WTC"
        return row
    try:
        s = normalize(r)
    except Exception as e:      # noqa: BLE001
        row["status"] = f"normalize error: {type(e).__name__}"
        return row
    if s.t_fill is None:
        row["status"] = "no t_fill"
        return row
    si, refresh = silicon_events(s)
    row["t_fill"] = s.t_fill
    row["t_m0"] = s.t_markers.get(0)
    if refresh:
        row["status"] = "not modelled: refresh"
        return row
    body = r["chain_base"] + ls_end(ch)
    d = offsets.get(row["group"], 0)
    end = si[-1][0] if si else 400
    code = bytes.fromhex(r["code_hex"])
    _last_at[0] = None
    try:
        mo, blog, hist = model_events(r, o, d, end - d + 40, body)
    except Exception as e:      # noqa: BLE001
        at = _last_at[0]
        off = at - (r["chain_base"] - 0x10000) if at is not None else None
        k, ins, _ = instr_at(ch, off) if off is not None else (None, None, None)
        enc = None
        try:
            enc = encoding(code, at) if at is not None else None
        except Exception:      # noqa: BLE001
            pass
        tb = traceback.extract_tb(e.__traceback__)
        fn = tb[-1].name
        if ins is None and off is not None:
            row["status"] = "model error"
            row["error"] = f"ran outside the chain ({type(e).__name__} at chain offset {off})"
            row["where"] = f"{fn}:{tb[-1].lineno}"
        elif isinstance(e, KeyError) and fn in ("info", "_info_orig", "routine", "words"):
            row["status"] = "no routine"
        elif isinstance(e, KeyError) and any(t.name == "routine" for t in tb):
            row["status"] = "no routine"
        else:
            row["status"] = "model error"
            row["error"] = f"{type(e).__name__}: {e}"[:200]
            row["where"] = f"{fn}:{tb[-1].lineno}"
        row["missing"] = {"encoding": enc, "form": ins["form"] if ins else None,
                          "key": str(e)[:60]}
        return row
    if want_offset:
        row["d_first"] = (si[0][0] - (mo[0][0] - d)) if si and mo else None
    fd = first_div(si, mo)
    row["exact"] = fd is None
    row["n_si"], row["n_mo"] = len(si), len(mo)
    if fd:
        k, a, b, cls = fd
        row["first"] = {"index": k, "si": a, "mo": b, "class": cls,
                        "clock": (a or b)[0],
                        "from_m0": (a or b)[0] - (row["t_m0"] or 0)}
    lse = ls_end(ch)
    row["timeline"] = [[t + d, off + lse, hist.get(t)] for t, off in blog]
    keys = set()
    for t, off in blog:
        try:
            keys.add(_info_orig(code, r["chain_base"] - 0x10000 + lse + off)[0])
        except Exception:      # noqa: BLE001
            pass
    row["keys"] = sorted(keys)
    return row


def _family_task(args):
    fam, o, offsets, ids, want_offset, sample = args
    try:
        runs = load_runs(fam, (0, 1, 2)) if fam != "F0w" else load_runs(fam, (0, 1, 2))
    except FileNotFoundError:
        return fam, []
    if ids:
        runs = [r for r in runs if any(x in r["chain"]["id"] for x in ids)]
    if sample:
        runs = runs[::sample]
    return fam, [run_one(r, o, offsets, want_offset) for r in runs]


def families_from(miss):
    fams = []
    if miss and Path(miss).exists():
        for line in open(miss):
            f = json.loads(line)["family"]
            if f not in fams:
                fams.append(f)
    return fams


def calibrate(families, o, jobs, log):
    """One offset per frame group: the most common (silicon first event - model first event)
    over every 7th run of the families."""
    cnt = collections.defaultdict(collections.Counter)
    tasks = [(f, o, {}, None, True, 7) for f in families]
    with multiprocessing.get_context("fork").Pool(jobs) as pool:
        for fam, rows in pool.imap_unordered(_family_task, tasks):
            for r in rows:
                if r.get("d_first") is not None:
                    cnt[r["group"]][r["d_first"]] += 1
    offsets = {}
    for g, c in sorted(cnt.items()):
        (v, n), = c.most_common(1)
        offsets[g] = v
        log(f"  offset {g}: {v:+d} ({n} of {sum(c.values())} sampled runs; others "
            f"{dict(c.most_common(4)[1:])})")
    return offsets


def load_miss(path):
    out = {}
    if path and Path(path).exists():
        for line in open(path):
            x = json.loads(line)
            out[x["run"]] = x
    return out


def report(rows, miss, log=print, show=0):
    n = len(rows)
    st = collections.Counter()
    for r in rows:
        if r["status"] == "ok":
            st["model-exact" if r["exact"] else "model-miss"] += 1
        elif r["status"] == "no routine":
            st["no routine"] += 1
        else:
            st["not modelled / error: " + r["status"]] += 1
    log(f"{n} corpus runs")
    for k, v in st.most_common():
        log(f"  {k:<44} {v:>6}")
    nr = collections.Counter((r["missing"]["encoding"], r["missing"]["form"]) for r in rows
                             if r["status"] == "no routine")
    if nr:
        log("model has no routine (encoding, form of the instruction), by runs:")
        for (e, f), v in nr.most_common(25):
            log(f"  {str(e):<20} {str(f):<28} {v:>5}")
    me = collections.Counter(r.get("error", "")[:90] for r in rows if r["status"] == "model error")
    if me:
        log("model errors:")
        for e, v in me.most_common(8):
            log(f"  {v:>5}  {e}")
    if miss:
        crosstab(rows, miss, log)
    _tail(rows, log, show)


def crosstab(rows, miss, log=print):
    if miss:
        x = collections.Counter()
        for r in rows:
            m = miss.get(r["run"])
            rtl = "RTL ?" if m is None else ("RTL exact" if m["exact"] else "RTL miss")
            mod = ("model exact" if r["exact"] else "model miss") if r["status"] == "ok" else \
                "not modelled"
            x[(mod, rtl)] += 1
        log("cross-tab (model against silicon) x (RTL against silicon):")
        cols = ["RTL exact", "RTL miss", "RTL ?"]
        log(f"  {'':<14}" + "".join(f"{c:>11}" for c in cols) + f"{'total':>9}")
        for mod in ("model exact", "model miss", "not modelled"):
            log(f"  {mod:<14}" + "".join(f"{x[(mod, c)]:>11}" for c in cols)
                + f"{sum(x[(mod, c)] for c in cols):>9}")
        log(f"  (model exact, RTL miss) = build faults / unbuilt rules: {x[('model exact', 'RTL miss')]}")
        log(f"  (model miss, RTL miss)  = unread states:               {x[('model miss', 'RTL miss')]}")
        log(f"  (model miss, RTL exact) = model errors:                {x[('model miss', 'RTL exact')]}")


def _tail(rows, log, show):
    fam = collections.defaultdict(collections.Counter)
    for r in rows:
        fam[r["family"]]["runs"] += 1
        fam[r["family"]]["exact"] += bool(r["exact"])
        fam[r["family"]]["nm"] += r["status"] != "ok"
    log("per family (runs / model-exact / not modelled):")
    log("  " + "  ".join(f"{f}:{c['runs']}/{c['exact']}/{c['nm']}" for f, c in
                         sorted(fam.items(), key=lambda kv: (len(kv[0]), kv[0]))))
    cls = collections.Counter(r["first"]["class"] for r in rows if r.get("first"))
    log("model's first divergences by class:")
    for k, v in cls.most_common(15):
        log(f"  {k:<32} {v:>6}")
    for r in [r for r in rows if r.get("first")][:show]:
        f = r["first"]
        log(f"  {r['run']}: #{f['index']} +{f['from_m0']} from M0: si {f['si']} model {f['mo']}"
            f" ({f['class']})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 2)[2])
    ap.add_argument("--families", nargs="+", help="corpus families (default: the miss list's)")
    ap.add_argument("--rtl-miss", nargs="+", default=[],
                    help="the RTL replay's per-run rows (miss-v35_chk.jsonl); several: one "
                         "cross-tab each (the first is the one cluster.py is pointed at)")
    ap.add_argument("--out", default="corpus_model.jsonl")
    ap.add_argument("--offsets", default="corpus_model_offsets.json",
                    help="the frame groups' clock offsets (computed when missing)")
    ap.add_argument("--recalibrate", action="store_true")
    ap.add_argument("--ids", nargs="+", help="only runs whose id contains one of these")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--opt", nargs="+", default=[], help="model_m options K=V")
    ap.add_argument("--show", type=int, default=0, help="print the first N model misses")
    a = ap.parse_args(argv)
    o = model_m.options(a.opt)
    fams = a.families or families_from(a.rtl_miss[0] if a.rtl_miss else None)
    if not fams:
        from validation.v35s import corpus
        names = corpus.manifest()["entries"]
        fams = sorted({n.split("-")[1] for n in names if n.startswith("chains-F")},
                      key=lambda f: (len(f), f))
    if Path(a.offsets).exists() and not a.recalibrate:
        offsets = json.loads(Path(a.offsets).read_text())
    else:
        print("calibrating the frame groups' clock offsets ...", flush=True)
        offsets = calibrate(fams, o, a.jobs, print)
        Path(a.offsets).write_text(json.dumps(offsets, indent=1) + "\n")
    rows = []
    tasks = [(f, o, offsets, a.ids, False, 0) for f in fams]
    with multiprocessing.get_context("fork").Pool(a.jobs) as pool:
        for fam, rs in pool.imap_unordered(_family_task, tasks):
            rows += rs
            print(f"  {fam}: {len(rs)} runs, {sum(r['exact'] for r in rs)} model-exact",
                  flush=True)
    order = {f: i for i, f in enumerate(fams)}
    rows.sort(key=lambda r: (order.get(r["family"], 999), r["run"]))
    with open(a.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    report(rows, None, show=a.show)
    for m in a.rtl_miss:
        print(f"\nagainst {m}:")
        crosstab(rows, load_miss(m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
