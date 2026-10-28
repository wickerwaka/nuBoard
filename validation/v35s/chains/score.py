"""Exact-match scoring of model runs against silicon (plan, "Score").

Both event lists are cut at t_fill and re-based so t_fill = 0; a run matches
exactly when the sequences of (clock, kind, addr, width, length) are equal.
Events before t_fill are never compared: the model does not reproduce the
prelude (see sim/machine.py, "Start state"). (WP40) The prelude's tail before
clock 0 (Normalized.pre, from its POP PSW read) is a secondary comparison
(pre_aligned, pre_score; `score --pre`), never part of Score.exact.

    python -m validation.v35s.chains score --family F0 F1 [--waits ..] [--config cfg.json | --defaults] [--show N]
    python -m validation.v35s.chains sim --id CHAIN_ID [--config cfg.json | --defaults] [--strip]
    python -m validation.v35s.chains adopt cfg.json
    python -m validation.v35s.chains score --rtl --family F0 [--rtl-dir DIR] [--show N]

(Phase B) `score --rtl` adds the RTL replays (replay.py) per family: a three-mark table
(silicon=model, silicon=RTL, RTL=model), their counts and the gate RTL-exact >= model-exact
(see "RTL" below).

Both default to the tracked fit (sim.config.FIT_PATH); --defaults is the unfitted
structural baseline (sim.config.DEFAULT). `adopt` is the one way a fit (the fitter's
build/ output or a hand fit) becomes the tracked one: the fitter never writes FIT_PATH.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .derive import variant_of
from .normalize import Normalized, load_runs, normalize


def key(e, t0: int) -> tuple:
    return (e.clock - t0, e.kind, e.addr, e.width, e.length)


def aligned(n: Normalized) -> list[tuple]:
    """Events from the fill fetch on, clocks relative to t_fill."""
    if n.t_fill is None:
        return []
    return [key(e, n.t_fill) for e in n.events[n.fill_index:]]


def pre_aligned(n: Normalized) -> list[tuple]:
    """(WP40) the prelude's tail before clock 0 (Normalized.pre: from the POP PSW read),
    clocks relative to clock 0, as aligned() keys, except a refresh's row address: a label
    the model counts from the main list's anchor (its first refresh at or after its t_fill,
    machine.py), so it would carry the main list's agreement into the pre comparison; the
    pre comparison compares a refresh's clock and length only."""
    return [(e.clock, e.kind, 0 if e.kind == "refresh" else e.addr, e.width, e.length)
            for e in n.pre]


def pre_score(silicon: Normalized, model: Normalized | None) -> tuple:
    """(WP40) the secondary comparison: (exact over the pre lists, matched prefix, silicon's
    length). Never part of Score.exact."""
    a = pre_aligned(silicon)
    b = pre_aligned(model) if model is not None else []
    prefix = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return (bool(a) and a == b, prefix, len(a))


@dataclass
class Score:
    run_id: str
    exact: bool
    n_silicon: int
    n_model: int
    matched_prefix: int
    first_divergence: tuple | None          # (index, silicon event, model event)
    residuals: list = field(default_factory=list)   # model - silicon clock, paired by order


def score(silicon: Normalized, model: Normalized) -> Score:
    a, b = aligned(silicon), aligned(model)
    prefix = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    exact = a == b and silicon.t_fill is not None and model.t_fill is not None
    div = None
    if not exact:
        div = (prefix, a[prefix] if prefix < len(a) else None, b[prefix] if prefix < len(b) else None)
    residuals = []
    for x, y in zip(a, b):
        if x[1:3] != y[1:3]:
            break
        residuals.append(y[0] - x[0])
    return Score(silicon.run_id, exact, len(a), len(b), prefix, div, residuals)


# Families --------------------------------------------------------------------

def knob_of(chain) -> tuple:
    return (chain.parity, chain.waits, variant_of(chain))


def score_family(runs: list[dict], config) -> list[tuple]:
    """[(silicon Normalized, model Normalized, Score)] for run records."""
    return [model_one(normalize(r), config) for r in runs]


def model_one(s: Normalized, config) -> tuple:
    """(silicon, model Normalized or None, Score) for one normalised silicon run."""
    from .sim.machine import refresh_anchor, simulate_normalized

    try:
        m = simulate_normalized(s.chain, config, s.chain_base, refresh=refresh_anchor(s))
    except Exception as e:      # e.g. sim.queue.QueueOverflow: the structure cannot run it
        return (s, None, Score(s.run_id, False, len(aligned(s)), 0, 0,
                               (0, None, f"model error: {e}")))
    return (s, m, score(s, m))


def table(results) -> str:
    """Rows = variant, columns = parity x waits; cell = exact (=) or first residual."""
    rows: dict = defaultdict(dict)
    for s, m, sc in results:
        col = f"{'pE' if s.chain.parity == 'even' else 'pO'}" + (
            f"-w{s.chain.waits}" if s.chain.waits >= 0 else "")
        if sc.exact:
            cell = "="
        elif m is None:
            cell = "!"
        else:
            nz = next((r for r in sc.residuals if r), None)
            cell = f"{nz:+d}" if nz is not None else f"@{sc.matched_prefix}"
        rows[variant_of(s.chain)][col] = cell
    from .report import table as render
    return render("exact '=', else first nonzero residual (+model later), @index of the "
                  "first kind/addr mismatch, or ! when the model raised (queue overflow)", dict(rows), str)


def summary(results) -> str:
    n = len(results)
    exact = sum(sc.exact for _, _, sc in results)
    by = defaultdict(lambda: [0, 0])
    for s, _, sc in results:
        for k in (f"family {s.chain.family}", f"parity {s.chain.parity}", f"waits {s.chain.waits}"):
            by[k][0] += sc.exact
            by[k][1] += 1
    hist = Counter(r for _, _, sc in results for r in sc.residuals)
    lines = [f"exact {exact}/{n}"]
    lines += [f"  {k:<14} {a}/{b}" for k, (a, b) in sorted(by.items())]
    lines.append("residual histogram (model - silicon, paired events): "
                 + " ".join(f"{k:+d}:{v}" for k, v in sorted(hist.items())))
    return "\n".join(lines)


def pre_summary(results) -> str:
    """(WP40) the pre window's exact count beside the score: overall and per cell."""
    by = defaultdict(lambda: [0, 0])
    for s, m, _ in results:
        ok = pre_score(s, m)[0]
        col = f"{'pE' if s.chain.parity == 'even' else 'pO'}" + (
            f"-w{s.chain.waits}" if s.chain.waits >= 0 else "")
        for k in ("all", col):
            by[k][0] += ok
            by[k][1] += 1
    return "pre window exact " + " ".join(f"{k} {a}/{b}" for k, (a, b) in sorted(by.items()))


def side_by_side(s: Normalized, m: Normalized | None, sc: Score) -> str:
    if m is None:
        return f"{s.run_id}: {sc.first_divergence[2]}"
    a, b = aligned(s), aligned(m)
    lines = [f"{s.run_id}: first divergence at {sc.matched_prefix}"]
    fmt = lambda e: f"{e[0]:5d} {e[1]:<11} {e[2]:05X} {e[3]:<4} {e[4]}" if e else ""
    for k in range(max(len(a), len(b))):
        x = a[k] if k < len(a) else None
        y = b[k] if k < len(b) else None
        mark = " " if x == y else "*"
        lines.append(f"  {mark} {fmt(x):<32} | {fmt(y)}")
    return "\n".join(lines)


# RTL (HDL plan, Phase B) ---------------------------------------------------------
#
# score --rtl: each silicon run against the model (as above) and against its RTL replay
# (replay.py: the run record of the same chain id through the Verilator model lane), and
# the RTL against the model. The RTL trace is normalised non-strict (normalize(strict=
# False)): its soft check failures are counted by category and the run is still scored;
# a hard normalisation error (no fetch of the first chain word, an unclassifiable cycle)
# scores the run as an RTL miss marked '!'. A run with no replay, or a replay of another
# image (image_sha256 or chain_base differs), is "no RTL": never exact. The RTL's
# refresh rows are numbered from the silicon run's anchor (its first refresh at or after
# t_fill), as the model's are (sim.machine): row addresses are a label, the refresh
# counter carries over from run to run on the board.

@dataclass
class ThreeWay:
    silicon: Normalized
    model: Normalized | None
    model_score: Score | None       # silicon vs model; None: model n/a (UNMODELLED)
    rtl: Normalized | None
    rtl_score: Score | None         # silicon vs RTL; None: no RTL run
    rtl_model: Score | None         # model (reference) vs RTL; None: either missing
    rtl_status: str = "ok"          # ok | no RTL | image differs | error: <category>
    rtl_checks: list = field(default_factory=list)  # the RTL trace's soft check failures
    stale: bool = False             # replayed with another RTL build than the current one

    @property
    def model_exact(self) -> bool:
        return self.model_score is not None and self.model_score.exact

    @property
    def rtl_exact(self) -> bool:
        return self.rtl_score is not None and self.rtl_score.exact

    @property
    def rtl_model_exact(self) -> bool:
        return self.rtl_model is not None and self.rtl_model.exact

    @property
    def has_rtl(self) -> bool:
        return self.rtl_status not in ("no RTL", "image differs")


def check_category(message: str) -> str:
    """A normalisation message without its run id, addresses and counts."""
    import re
    message = re.sub(r"^F\d+w?-\S+: ", "", message)
    message = message.split(": expected", 1)[0]
    message = re.sub(r"\b[0-9A-F]{4,5}\b", "#", message)
    return re.sub(r"\d+", "#", message)


def relabel_refresh(n: Normalized, addr: int):
    """Number n's refresh rows (pre list included) from `addr` at its first refresh at or
    after t_fill, REFRESH_ROW_STEP apart, as the model's (sim.machine._prelude_run)."""
    from .sim.machine import REFRESH_ROW_STEP
    evs = n.pre + n.events
    refs = [k for k, e in enumerate(evs) if e.kind == "refresh"]
    first = next((k for k in refs if n.t_fill is not None and k >= len(n.pre)
                  and evs[k].clock >= n.t_fill), None)
    if first is None:
        return
    for j, k in enumerate(refs):
        evs[k].addr = addr + REFRESH_ROW_STEP * (j - refs.index(first))


def rtl_one(s: Normalized, run: dict, rec: dict | None, m: Normalized | None,
            current_key: str | None = None) -> tuple:
    """(rtl Normalized or None, silicon-vs-RTL Score or None, model-vs-RTL Score or None,
    status, soft checks, stale) for one silicon run and its replay record."""
    from .normalize import NormalizeError
    if rec is None:
        return None, None, None, "no RTL", [], False
    stale = current_key is not None and rec.get("rtl_key") != current_key
    if (rec.get("chain_base") != run.get("chain_base")
            or run.get("image_sha256") and rec.get("image_sha256")
            and rec["image_sha256"] != run["image_sha256"]):
        return None, None, None, "image differs", [], stale
    try:
        n = normalize(rec, strict=False)
    except (NormalizeError, KeyError, ValueError, StopIteration) as e:
        cat = check_category(str(e))
        sc = Score(s.run_id, False, len(aligned(s)), 0, 0, (0, None, f"RTL error: {e}"))
        return None, sc, None, f"error: {cat}", [], stale
    from .sim.machine import refresh_anchor
    anchor = refresh_anchor(s, events=False)
    relabel_refresh(n, anchor[1] if anchor is not None else 0)
    return (n, score(s, n), score(m, n) if m is not None else None, "ok", list(n.checks),
            stale)


def three_way(runs: list[dict], config, rtl_runs: dict, current_key: str | None = None,
              model: bool = True) -> list[ThreeWay]:
    """One ThreeWay per silicon run record; rtl_runs {chain id: replay record}; model=False
    (an UNMODELLED family): silicon against RTL only."""
    out = []
    for r in runs:
        s = normalize(r)
        m = msc = None
        if model:
            _, m, msc = model_one(s, config)
        rtl, rsc, rm, status, checks, stale = rtl_one(s, r, rtl_runs.get(s.run_id), m,
                                                       current_key)
        out.append(ThreeWay(s, m, msc, rtl, rsc, rm, status, checks, stale))
    return out


def _column(chain) -> str:
    return f"{'pE' if chain.parity == 'even' else 'pO'}" + (
        f"-w{chain.waits}" if chain.waits >= 0 else "")


def marks(t: ThreeWay) -> str:
    """Three marks: silicon=model, silicon=RTL, RTL=model."""
    if t.model_score is None:
        a = "-"
    else:
        a = "=" if t.model_exact else ("!" if t.model is None else "x")
    if not t.has_rtl:
        b = "?"
    else:
        b = "=" if t.rtl_exact else ("!" if t.rtl is None else "x")
    c = "-" if t.model is None or t.rtl is None else ("=" if t.rtl_model_exact else "x")
    return a + b + c


def table3(results: list[ThreeWay]) -> str:
    rows: dict = defaultdict(dict)
    for t in results:
        rows[variant_of(t.silicon.chain)][_column(t.silicon.chain)] = marks(t)
    from .report import table as render
    return render("three marks: silicon=model, silicon=RTL, RTL=model; '=' exact, 'x' miss, "
                  "'!' error (model raised / RTL trace not normalisable), '?' no RTL run, "
                  "'-' n/a", dict(rows), str)


def summary3(results: list[ThreeWay], modelled: bool = True) -> str:
    n = len(results)
    me = sum(t.model_exact for t in results)
    re_ = sum(t.rtl_exact for t in results)
    rm = sum(t.rtl_model_exact for t in results)
    no_rtl = sum(not t.has_rtl for t in results)
    errors = Counter(t.rtl_status for t in results if t.rtl_status.startswith("error"))
    stale = sum(t.stale for t in results)
    head = (f"model-exact {me}/{n}" if modelled else "model-exact n/a") + (
        f"  RTL-exact {re_}/{n}  RTL=model " + (f"{rm}/{n}" if modelled else "n/a")
        + f"  no RTL {no_rtl}  RTL errors {sum(errors.values())}")
    lines = [head]
    by = defaultdict(lambda: [0, 0, 0, 0])
    for t in results:
        c = t.silicon.chain
        for k in (f"parity {c.parity}", f"waits {c.waits}"):
            by[k][0] += t.model_exact
            by[k][1] += t.rtl_exact
            by[k][2] += t.rtl_model_exact
            by[k][3] += 1
    for k, (a, b, c, d) in sorted(by.items()):
        lines.append(f"  {k:<14} model {a if modelled else '-'}/{d}  RTL {b}/{d}  "
                     f"RTL=model {c if modelled else '-'}/{d}")
    soft = Counter(check_category(x) for t in results for x in t.rtl_checks)
    if errors or soft:
        lines.append("RTL normalisation failures by category (runs; errors are scored '!'):")
        lines += [f"  {v:5d}  {k}" for k, v in errors.most_common()]
        lines += [f"  {v:5d}  soft: {k}" for k, v in soft.most_common()]
    if stale:
        lines.append(f"warning: {stale} RTL runs were replayed with another RTL build than "
                     f"the current one (replay --resume re-runs them)")
    if modelled:
        lines.append(f"gate RTL-exact >= model-exact: {'yes' if re_ >= me else 'no'} "
                     f"({re_} vs {me})")
    else:
        lines.append(f"gate (model n/a, RTL-exact alone, every run): "
                     f"{'yes' if n and re_ == n else 'no'} ({re_}/{n})")
    return "\n".join(lines)


def side_by_side3(t: ThreeWay) -> str:
    """silicon | model | RTL from t_fill on; '*' where silicon and RTL differ."""
    s, m, r = t.silicon, t.model, t.rtl
    if r is None:
        why = (t.rtl_score.first_divergence[2] if t.rtl_score is not None
               and t.rtl_score.first_divergence else t.rtl_status)
        return f"{s.run_id}: {why}"
    a, b, c = aligned(s), aligned(m) if m is not None else [], aligned(r)
    head = f"{s.run_id}: silicon | model | RTL, first silicon/RTL divergence at " \
           f"{t.rtl_score.matched_prefix}"
    if t.rtl_checks:
        head += "\n  RTL checks: " + "; ".join(t.rtl_checks)
    lines = [head]
    fmt = lambda e: f"{e[0]:5d} {e[1]:<11} {e[2]:05X} {e[3]:<4} {e[4]}" if e else ""
    for k in range(max(len(a), len(b), len(c))):
        x = a[k] if k < len(a) else None
        y = b[k] if k < len(b) else None
        z = c[k] if k < len(c) else None
        lines.append(f"  {' ' if x == z else '*'} {fmt(x):<32} | {fmt(y):<32} | {fmt(z)}")
    return "\n".join(lines)


def rtl_score_main(args, cfg) -> int:
    from .families import UNMODELLED
    from .replay import load_rtl_runs, rtl_identity, rtl_key

    current = rtl_identity()
    key = rtl_key(current)
    print(f"RTL now: {current['binary']} built {current['binary_mtime_iso']}, fpga/v35s tree "
          f"{(current['fpga_tree'] or '?')[:12]}{' +dirty' if current['fpga_dirty'] else ''}")
    for family in args.family:
        print(f"== {family}")
        try:
            runs = load_runs(family, tuple(args.waits))
        except FileNotFoundError as e:
            print(f"no silicon runs: {e}\n")
            continue
        rtl_runs, headers = load_rtl_runs(family, tuple(args.waits), args.rtl_dir)
        for path, h in headers.items():
            ident = h.get("rtl") or {}
            print(f"RTL file {path}: {ident.get('binary', 'no RTL identity (acquire --backend sim?)')}"
                  f" {ident.get('binary_mtime_iso') or ''} tree {(ident.get('fpga_tree') or '?')[:12]}")
        modelled = family not in UNMODELLED
        results = three_way(runs, cfg, rtl_runs, key, model=modelled)
        if modelled:
            legacy = [(t.silicon, t.model, t.model_score) for t in results]
            print(table(legacy))
            print(summary(legacy))
            if getattr(args, "pre", False):
                print(pre_summary(legacy))
        else:
            print(f"{family} is UNMODELLED: silicon against RTL only")
        print(table3(results))
        print(summary3(results, modelled))
        for t in [t for t in results if not t.rtl_exact][:args.show]:
            print()
            print(side_by_side3(t))
        print()
    return 0


# CLI -------------------------------------------------------------------------

def _config(args):
    from .sim.config import DEFAULT, Config
    return DEFAULT if args.defaults else Config.fitted(args.config)


def _add_config_arguments(p):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--config", metavar="PATH",
                   help="model config JSON (default: the tracked fit, sim.config.FIT_PATH)")
    g.add_argument("--defaults", action="store_true",
                   help="use the unfitted structural baseline sim.config.DEFAULT")


def adopt_main(args) -> int:
    """Write the config at args.path to FIT_PATH, canonical (sorted keys, indent 1).

    Stricter than Config.load, which drops unknown keys and fills missing ones from
    DEFAULT: the file must round-trip exactly, so a renamed or missing field cannot be
    adopted silently."""
    import json

    from .sim import config
    try:
        d = json.loads(open(args.path).read())
        cfg = config.Config.from_json(d)
    except (OSError, ValueError, TypeError) as e:
        print(f"adopt: cannot load {args.path}: {e}")
        return 2
    if cfg.to_json() != d:
        print(f"adopt: {args.path} is not exactly a Config (unknown or missing keys)")
        return 2
    config.FIT_PATH.write_text(json.dumps(cfg.to_json(), indent=1, sort_keys=True))
    print(config.FIT_PATH)
    return 0


def add_score_arguments(p):
    p.add_argument("--family", nargs="+", required=True)
    p.add_argument("--waits", nargs="+", type=int, choices=(0, 1, 2), default=[0, 1, 2])
    _add_config_arguments(p)
    p.add_argument("--show", type=int, default=0, help="print the first N diverging runs")
    p.add_argument("--pre", action="store_true",
                   help="(WP40) also report the pre window (POP PSW read to clock 0) "
                        "exact per family and cell, after the family's summary")
    p.add_argument("--rtl", action="store_true",
                   help="(Phase B) also score the RTL replays (replay.py): three-way table, "
                        "summary and gate; --show then prints the first N RTL misses")
    p.add_argument("--rtl-dir", metavar="DIR",
                   help="with --rtl: the replay files (default build/validation/v35s/chains-sim)")
    return p


def score_main(args) -> int:
    cfg = _config(args)
    if getattr(args, "rtl", False):
        return rtl_score_main(args, cfg)
    for family in args.family:
        results = score_family(load_runs(family, tuple(args.waits)), cfg)
        print(f"== {family}")
        print(table(results))
        print(summary(results))
        if getattr(args, "pre", False):
            print(pre_summary(results))
        bad = [r for r in results if not r[2].exact][:args.show]
        for s, m, sc in bad:
            print()
            print(side_by_side(s, m, sc))
        print()
    return 0


def add_sim_arguments(p):
    p.add_argument("--id", required=True, help="chain id, e.g. F0-ls-pE-w0")
    _add_config_arguments(p)
    p.add_argument("--strip", action="store_true", help="ASCII clock strip (report.py)")
    p.add_argument("--silicon", action="store_true",
                   help="simulate the recorded run (its chain and base, from the corpus or "
                        "--file) and print silicon | model from t_fill on")
    p.add_argument("--file", nargs="+", help="with --silicon: read these result files")
    p.add_argument("--trace", nargs="*", type=int, metavar="CLOCK",
                   help="print the model's state at the end of every clock (relative to "
                        "t_fill; optional FROM [TO] window)")
    return p


def _trace_lines(rows, t_fill, window) -> list[str]:
    lo = window[0] if window else None
    hi = window[1] if window and len(window) > 1 else None
    out = ["  clock  rel  bus        q occ room fl infl IR   need pc   cls       k step"
           "                       sync     req"]
    for r in rows:
        rel = r["t"] - t_fill if t_fill is not None else r["t"]
        if lo is not None and rel < lo or hi is not None and rel > hi:
            continue
        step = r["step"]
        step = "-" if step is None else " ".join(str(x) for x in step[:3])
        marks = ("S" if r["started_now"] else " ") + ("T" if r["took"] else " ") + (
            "L" if r["ir_load"] else " ") + ("b" if r["b2b"] else " ")
        out.append(f"  {r['t']:5d} {rel:+4d} {r['bus']:<10} {r['queued']} {r['occ']:>3} "
                   f"{r['room']:>4} {'R' if r['flag'] else '.':>2} {'F' if r['inflight'] else '.':>4} "
                   f"{'-' if r['ir'] is None else r['ir']:>4} {r['need']:>4} {r['pc']:>4} "
                   f"{str(r['cls']):<9} {r['k']:>1} {step:<26} {str(r['sync']):<8} "
                   f"{'' if r['req'] is None else r['req']} {marks}")
    return out


def sim_main(args) -> int:
    from .families import generate
    from .sim.machine import refresh_anchor, simulate_normalized

    cfg = _config(args)
    log = [] if args.trace is not None else None
    if args.silicon:
        family = args.id.split("-", 1)[0]
        rec = next((r for r in load_runs(family, files=args.file)
                    if r["chain"]["id"] == args.id), None)
        if rec is None:
            raise SystemExit(f"no recorded run {args.id}")
        s = normalize(rec)
        n = simulate_normalized(s.chain, cfg, s.chain_base, clock_log=log,
                                refresh=refresh_anchor(s))
        sc = score(s, n)
        print(f"{'exact' if sc.exact else 'MISS'} silicon t_fill={s.t_fill} | model "
              f"t_fill={n.t_fill}")
        print(side_by_side(s, n, sc))
    else:
        family = args.id.split("-", 1)[0]
        chain = next((c for c in generate([family]) if c.id == args.id), None)
        if chain is None:
            raise SystemExit(f"unknown chain id {args.id}")
        n = simulate_normalized(chain, cfg, clock_log=log)
        print(f"{n.run_id}: t_fill={n.t_fill} markers={n.t_markers} t_end={n.t_end} "
              f"checks={n.checks}")
        for e in n.events:
            rel = e.clock - n.t_fill if n.t_fill is not None else e.clock
            tag = f" M{e.marker_id}" if e.marker_id is not None else ""
            print(f"  {e.clock:5d} {rel:+5d} {e.kind:<11} {e.addr:05X} {e.width:<4} {e.length}{tag}")
    if log is not None:
        print("\n".join(_trace_lines(log, n.t_fill, args.trace)))
    if args.strip and n.t_fill is not None and n.t_end is not None:
        from .report import strip
        st, _ = strip(n)
        print(st)
    return 0
