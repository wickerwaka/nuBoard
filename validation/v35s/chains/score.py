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
    from .sim.machine import refresh_anchor, simulate_normalized

    out = []
    for r in runs:
        s = normalize(r)
        try:
            m = simulate_normalized(s.chain, config, s.chain_base, refresh=refresh_anchor(s))
        except Exception as e:      # e.g. sim.queue.QueueOverflow: the structure cannot run it
            out.append((s, None, Score(s.run_id, False, len(aligned(s)), 0, 0,
                                       (0, None, f"model error: {e}"))))
            continue
        out.append((s, m, score(s, m)))
    return out


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
    return p


def score_main(args) -> int:
    cfg = _config(args)
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
