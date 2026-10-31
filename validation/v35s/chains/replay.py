"""Replay chain images through the Verilator RTL model lane (HDL plan, Phase B).

From the repo root:

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains replay --family F0 [F1 ...] \\
        [--waits 0 1 2] [--parity even odd] [--ids ...] [--jobs N] [--output-dir DIR] [--resume]
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains score --rtl --family F0 [--show N]
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains replay --state DUMP --id RUN_ID
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains replay --dump-model DUMP --id RUN_ID
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains replay --core chain --family F0 ...
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains replay --core chain --score \
        --family F0 [F1 ...] [--waits ...] [--show N]

(WP82) --core chain replays through the chain-model core in the model lane (fpga/v35s/
build_sim.sh direct chain: build/fpga/v35s/verilator-direct-chain/Vv35s_harness), from /RESET
with nothing scripted, into build/validation/v35s/chains-sim-chain (the header's "core":
"chain"). --score reads those replays against the silicon corpus with score.py's normaliser
and scorer: per family the runs, model-exact (the frozen model, sim/frozen: the tracked fit,
against silicon), RTL-exact (the replay against silicon), RTL = model (the replay against the
frozen model, from t_fill) and the pre window (score.pre_score: the fetch train from the POP
PSW read before clock 0, silicon against the replay, and the first divergence).

B1, the replay driver. Every selected chain is built (image.build_image) and run once
from reset through the model lane of the `direct` Verilator build
(build/fpga/v35s/verilator-direct/Vv35s_harness, fpga/v35s/build_sim.sh direct), with
acquire.run_built: the same X_HALF, the chain's own WTC, RFM and PRC from its prelude,
the same lane-format trace. The records go to acquire's file format, one file per
(family, waits) in build/validation/v35s/chains-sim/ (acquire.file_name, acquire.RunFile,
"backend": "sim", the trace under "socket_trace"), so `normalize`, `report` and `score`
read them like corpus entries. No determinism repeats are run (the simulation is
deterministic; `acquire --backend sim` has them when wanted).

Parallel over chains: --jobs N worker processes (default min(8, CPUs)), each with its
own SimulationTransport, i.e. one Verilator process per worker (the transport is a
private stdin/stdout pipe to its own process, so instances do not share state). Each
file is rewritten atomically at most every SAVE_EVERY seconds and once at the end
(acquire rewrites after every run; a replay is ~0.06 s, so that would be the cost).

RTL identity. The file header's "rtl" (rtl_identity) names the Verilator binary, its
mtime, the git commit and tree hash of fpga/v35s at run time, whether fpga/v35s had
uncommitted changes, and the build's source files newer than the binary. Every record
carries the short form ("rtl_key": binary mtime and tree hash) so files mixing builds
are visible: `score --rtl` flags runs whose key is not the current build's, and
--resume re-runs them instead of skipping them.

B3, the state-row comparison (Python side). A state dump is JSON Lines, one object per
CPU clock, in clock order, holding the model's per-clock state (sim.machine.Machine.
_clock_row) under the same keys and in the same JSON shape (tuples as lists, None as
null; `ir` and `pc` both chain offsets, relative to the chain base, the prelude tail
excluded: _clock_row gives them in that frame, so neither side is corrected here, and an
RTL dump must give them so too). An optional first line
without "t" is a header: {"format": STATE_FORMAT, "chain": id, "t0": N}; "t0" is the
absolute clock of the model's clock 0 (the start of the prelude's POP PSW read,
prelude_anchor=pop) and is subtracted from every row's "t". Keys:

    required  STATE_REQUIRED: the machines' clocked state and the per-clock strobes
              (t, bus, queued, occ, room, inflight, flag, latched, ir, need, pc,
              started_now, took, ir_load, b2b, req)
    optional  STATE_OPTIONAL: the model's bookkeeping, compared only when the dump has
              the key (requested_at, cls, k, step, resume, sync, clk_tag, clk_start,
              clk_end)

compare_state_rows(model_rows, rtl_rows) gives the first differing clock and key
(StateDiff) or None. `replay --state DUMP --id RUN_ID` simulates the model for the run
with a full clock log (a clock log turns the quiet-clock fast-forward off) and compares;
`--dump-model DUMP` writes the model's rows in this format (the reference dump).

The RTL hook (not built yet): the RTL machines' state variables go out on a
simulation-only debug bus, inside `ifdef V35S_STATE_DUMP`, one bundle per CPU clock
(sampled at the end of the clock, after the machines' updates, where _clock_row is
taken), with a strobe on the clock edge (the X1/2 enable in v35s_model.sv). sim_main.cpp
gets a `+state_dump=FILE` plusarg: when set, it writes one JSON line per strobe from the
bundle, with "t" the CPU clock count since reset, and a header line whose "t0" is the
clock count at the start of the first memory read at 0EFEh after the first write there
(the prelude's PUSH 0002h / POP PSW). build_sim.sh would pass -DV35S_STATE_DUMP to a
`direct-state` variant so the normal build is unchanged. The ucore lane has none of the
model's machines; this hook is for the Phase C RTL.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .acquire import (DEFAULT_LIMIT, ROOT, SIM_BINARY, SIM_CORES, SIM_OUTPUT, TICKS_PER_CLOCK,
                      X_HALF, RunFile, file_name, group_chains, run_built, select_chains,
                      sim_transport)

FPGA_DIR = ROOT / "fpga/v35s"
SHARED_SOURCES = ("fpga/m68000/m68000_scope.sv", "fpga/m68000/scope_encoder.sv")
SAVE_EVERY = 2.0                # seconds between rewrites of one output file
MAX_JOBS = 8


# RTL identity -------------------------------------------------------------------

def _git(*args) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                             timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _sources() -> list[Path]:
    """The files the direct build reads (build_sim.sh): fpga/v35s and the shared scope."""
    out = [p for p in FPGA_DIR.rglob("*") if p.is_file()
           and p.suffix in (".sv", ".svh", ".v", ".vh", ".cpp", ".hex", ".sh")]
    return sorted(out + [ROOT / s for s in SHARED_SOURCES if (ROOT / s).exists()])


def rtl_identity(binary: Path = SIM_BINARY) -> dict:
    """What a replay ran: the binary and its mtime, fpga/v35s's commit, tree and dirty
    state, and the sources newer than the binary (a stale build)."""
    binary = Path(binary)
    mtime = binary.stat().st_mtime if binary.exists() else None
    try:
        shown = str(binary.relative_to(ROOT))
    except ValueError:
        shown = str(binary)
    status = _git("status", "--porcelain", "--", "fpga/v35s")
    return {
        "binary": shown,
        "binary_mtime": mtime,
        "binary_mtime_iso": None if mtime is None else datetime.datetime.fromtimestamp(
            mtime).astimezone().isoformat(timespec="seconds"),
        "fpga_commit": _git("log", "-1", "--format=%H", "--", "fpga/v35s"),
        "fpga_tree": _git("rev-parse", "HEAD:fpga/v35s"),
        "fpga_dirty": None if status is None else bool(status),
        "sources_newer": [] if mtime is None else
            [str(p.relative_to(ROOT)) for p in _sources() if p.stat().st_mtime > mtime],
    }


def rtl_key(identity: dict) -> str:
    """The short identity stored in every record: binary mtime and fpga/v35s tree."""
    mtime = identity.get("binary_mtime")
    tree = identity.get("fpga_tree") or "?"
    dirty = "+dirty" if identity.get("fpga_dirty") else ""
    return f"{'?' if mtime is None else f'{mtime:.3f}'}:{tree[:12]}{dirty}"


# Replay ---------------------------------------------------------------------------

_worker = None                  # (transport, harness) of this worker process


def _open_lane(core: str = "ucore", diag: bool = False):
    from nuboard.debug import DebugClient
    from ..runner import Harness
    transport = sim_transport(core, diag)
    return transport, Harness(DebugClient(transport.exchange))


def _init_worker(core: str = "ucore", diag: bool = False):
    global _worker
    from multiprocessing import util
    _worker = _open_lane(core, diag)
    util.Finalize(None, _worker[0].close, exitpriority=10)


def replay_one(chain, limit: int = DEFAULT_LIMIT, build=None, harness=None) -> dict:
    """One chain through the model lane: the run record (acquire's fields, no repeat)."""
    if build is None:
        from .image import build_image as build
    if harness is None:
        harness = _worker[1]
    started = time.monotonic()
    built = build(chain)
    record = {"chain": chain.to_json(), "code_hex": built.code.hex(),
              "chain_base": built.chain_base, "image_sha256": built.image_sha256}
    record.update(run_built(harness, built, "sim", limit))
    record.update(repeat_trace=None, repeat_identical=None, repeat_shift=None)
    record["replay_seconds"] = round(time.monotonic() - started, 4)
    return record


def _pool_task(item):
    chain, limit = item
    return replay_one(chain, limit)


def replay(chains, *, output_dir: Path = SIM_OUTPUT, jobs: int = 1, resume: bool = False,
           limit: int = DEFAULT_LIMIT, identity: dict | None = None, runner=None,
           log=print, core: str = "ucore", diag: bool = False) -> dict:
    """Replay the chains into acquire-format files under output_dir. runner(chain) -> record
    replaces the Verilator run (tests); with it, or jobs == 1, everything runs in this
    process. core (WP82): the model lane's core (acquire.SIM_CORES)."""
    if identity is None:
        identity = rtl_identity(SIM_CORES[core][0])
    key = rtl_key(identity)
    groups = group_chains(chains)
    files: dict = {}
    for (family, waits) in groups:
        header = {"backend": "sim", "board_state": None, "x_half": X_HALF,
                  "ticks_per_clock": TICKS_PER_CLOCK, "family": family, "waits": waits,
                  "rtl": identity}
        if core != "ucore":
            header["core"] = core
        files[(family, waits)] = RunFile(output_dir / file_name(family, waits), header)
    order = {k: [c.id for c in members] for k, members in groups.items()}
    todo, skipped = [], 0
    for k, members in groups.items():
        for chain in members:
            old = files[k].runs.get(chain.id)
            if resume and old is not None and old.get("rtl_key") == key:
                skipped += 1
                continue
            todo.append(chain)

    stats = {"runs": 0, "failures": 0, "incomplete": 0, "skipped": skipped,
             "seconds": 0.0, "run_seconds": 0.0, "jobs": jobs}
    started = time.monotonic()
    saved = {k: started for k in files}
    dirty: set = set()

    def save(k, force=False):
        now = time.monotonic()
        if k in dirty and (force or now - saved[k] >= SAVE_EVERY):
            files[k].save(order[k])
            saved[k] = now
            dirty.discard(k)

    def take(record):
        k = (record["chain"]["family"], record["chain"]["waits"])
        record["rtl_key"] = key
        files[k].runs[record["chain"]["id"]] = record
        dirty.add(k)
        stats["runs"] += 1
        stats["failures"] += not record["passed"]
        stats["incomplete"] += not record["complete"]
        stats["run_seconds"] += record.get("replay_seconds", 0.0)
        if not record["passed"] or not record["complete"]:
            log(f"  {record['chain']['id']}: {'FAIL' if not record['passed'] else ''}"
                f"{'' if record['complete'] else ' INCOMPLETE'}", flush=True)
        save(k)

    try:
        if runner is not None or jobs <= 1 or len(todo) <= 1:
            if runner is None:
                transport, harness = _open_lane(core, diag)
                runner = lambda c: replay_one(c, limit, harness=harness)
            else:
                transport = None
            try:
                for chain in todo:
                    take(runner(chain))
            finally:
                if transport is not None:
                    transport.close()
        else:
            import multiprocessing
            ctx = multiprocessing.get_context("fork")
            with ctx.Pool(jobs, initializer=_init_worker, initargs=(core, diag)) as pool:
                for record in pool.imap_unordered(_pool_task, [(c, limit) for c in todo]):
                    take(record)
                pool.close()
                pool.join()
    finally:
        for k in files:
            save(k, force=True)

    stats["seconds"] = time.monotonic() - started
    n = stats["runs"]
    log(f"{n} runs ({stats['failures']} failed, {stats['incomplete']} incomplete), "
        f"{skipped} skipped (resume); {stats['seconds']:.1f} s wall, "
        f"{(stats['run_seconds'] / n if n else 0):.3f} s/run per worker, "
        f"{(stats['seconds'] / n if n else 0):.3f} s/run wall with {jobs} jobs", flush=True)
    for out in files.values():
        log(f"  {out.path}")
    return stats


# Reading replays (score --rtl) ------------------------------------------------------

def load_rtl_runs(family: str, waits=(0, 1, 2), rtl_dir: Path | None = None) -> tuple:
    """({chain id: record}, {path: header}) of a family's replay files in rtl_dir."""
    rtl_dir = Path(rtl_dir or SIM_OUTPUT)
    names = [file_name(family, -1)] if family == "F0w" else [file_name(family, w)
                                                               for w in waits]
    runs, headers = {}, {}
    for name in names:
        path = rtl_dir / name
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        headers[str(path)] = {k: v for k, v in data.items() if k != "runs"}
        for run in data.get("runs", []):
            runs[run["chain"]["id"]] = run
    return runs, headers


# (WP82) Scoring a core's replays against silicon and the frozen model --------------------

def _pre_event(e) -> str:
    return "-" if e is None else f"{e[1]}@{e[0]} {e[2]:05X}/{e[4]}"


def score_lane_run(item) -> dict:
    """One silicon run record and its replay record (or None): the three marks and the pre
    window (silicon against the replay) as a plain dict."""
    run, rec = item
    from .normalize import NormalizeError, normalize
    from .score import pre_aligned, pre_score, relabel_refresh, score
    from .sim.frozen.config import DEFAULT as FROZEN
    from .sim.frozen.machine import refresh_anchor, simulate_normalized
    s = normalize(run)
    out = {"id": s.run_id, "family": s.chain.family, "waits": s.chain.waits,
           "parity": s.chain.parity, "model_exact": False, "rtl_exact": False,
           "rtl_model": False, "pre_exact": False, "pre_prefix": 0, "pre_len": 0,
           "pre_first": None, "status": "ok", "first": None, "model_first": None}
    try:
        m = simulate_normalized(s.chain, FROZEN, s.chain_base, refresh=refresh_anchor(s))
        out["model_exact"] = score(s, m).exact
    except Exception as e:      # noqa: BLE001 (the model cannot run it)
        m = None
        out["status"] = f"model error: {type(e).__name__}"
    if rec is None:
        out["status"] = "no RTL"
        return out
    if rec.get("chain_base") != run.get("chain_base") or (
            run.get("image_sha256") and rec.get("image_sha256")
            and rec["image_sha256"] != run["image_sha256"]):
        out["status"] = "image differs"
        return out
    try:
        n = normalize(rec, strict=False)
    except (NormalizeError, KeyError, ValueError, StopIteration) as e:
        out["status"] = f"RTL error: {e}"
        return out
    anchor = refresh_anchor(s, events=False)
    relabel_refresh(n, anchor[1] if anchor is not None else 0)
    sc = score(s, n)
    out["rtl_exact"] = sc.exact
    if sc.first_divergence:
        k, a, b = sc.first_divergence
        out["first"] = f"#{k}: silicon {a} rtl {b}"
    if m is not None:
        sm = score(m, n)
        out["rtl_model"] = sm.exact
        if sm.first_divergence:
            k, a, b = sm.first_divergence
            out["model_first"] = f"#{k}: model {a} rtl {b}"
    exact, prefix, length = pre_score(s, n)
    out["pre_exact"], out["pre_prefix"], out["pre_len"] = exact, prefix, length
    a, b = pre_aligned(s), pre_aligned(n)
    if not exact:
        out["pre_first"] = (prefix, _pre_event(a[prefix] if prefix < len(a) else None),
                            _pre_event(b[prefix] if prefix < len(b) else None))
    return out


def score_lane(families, waits=(0, 1, 2), rtl_dir: Path | None = None, jobs: int = 1,
               show: int = 0, log=print) -> dict:
    """{family: [score_lane_run dicts]} for the replays in rtl_dir, printed per family:
    runs, model-exact, RTL-exact, RTL = model, pre-window exact and the commonest first
    pre divergences."""
    from collections import Counter
    from .normalize import load_runs
    items_by: dict = {}
    for family in families:
        try:
            runs = load_runs(family, tuple(waits))
        except FileNotFoundError as e:
            log(f"{family}: no silicon runs ({e})")
            continue
        rtl_runs, _ = load_rtl_runs(family, tuple(waits), rtl_dir)
        items_by[family] = [(r, rtl_runs.get(r["chain"]["id"])) for r in runs]
    results: dict = {}
    flat = [(f, it) for f, its in items_by.items() for it in its]
    if jobs > 1 and len(flat) > 1:
        import multiprocessing
        with multiprocessing.get_context("fork").Pool(jobs) as pool:
            outs = pool.map(score_lane_run, [it for _, it in flat], chunksize=4)
    else:
        outs = [score_lane_run(it) for _, it in flat]
    for (f, _), o in zip(flat, outs):
        results.setdefault(f, []).append(o)
    tot = Counter()
    for family, rs in results.items():
        c = Counter()
        for r in rs:
            c["runs"] += 1
            c["model"] += r["model_exact"]
            c["rtl"] += r["rtl_exact"]
            c["rm"] += r["rtl_model"]
            c["pre"] += r["pre_exact"]
            c["norl"] += r["status"] != "ok"
            c["rtl_not_model"] += r["model_exact"] and not r["rtl_exact"]
        tot.update(c)
        log(f"{family:<5} runs {c['runs']:>5}  model-exact {c['model']:>5}  RTL-exact "
            f"{c['rtl']:>5}  RTL = model {c['rm']:>5}  pre exact {c['pre']:>5}  "
            f"model-exact not RTL-exact {c['rtl_not_model']}  not scored {c['norl']}")
        firsts = Counter((r["pre_first"][0], r["pre_first"][1], r["pre_first"][2])
                         for r in rs if r["pre_first"])
        for (k, a, b), n in firsts.most_common(3):
            log(f"      pre first divergence at #{k}: silicon {a} | rtl {b}  ({n} runs)")
        bad = [r for r in rs if r["status"] != "ok"]
        for r in bad[:3]:
            log(f"      {r['id']}: {r['status']}")
        for r in [r for r in rs if not r["rtl_model"] and r["status"] == "ok"][:show]:
            log(f"      {r['id']}: RTL != model {r['model_first']}")
    if len(results) > 1:
        log(f"all   runs {tot['runs']:>5}  model-exact {tot['model']:>5}  RTL-exact "
            f"{tot['rtl']:>5}  RTL = model {tot['rm']:>5}  pre exact {tot['pre']:>5}  "
            f"model-exact not RTL-exact {tot['rtl_not_model']}  not scored {tot['norl']}")
    return results


# State rows (B3) --------------------------------------------------------------------

STATE_FORMAT = "v35s-state-1"
STATE_REQUIRED = ("t", "bus", "queued", "occ", "room", "inflight", "flag", "latched", "ir",
                  "need", "pc", "started_now", "took", "ir_load", "b2b", "req")
STATE_OPTIONAL = ("requested_at", "cls", "k", "step", "resume", "sync", "clk_tag",
                  "clk_start", "clk_end")


@dataclass
class StateDiff:
    t: int                      # the first differing clock
    key: str                    # the first differing key there ("t": a clock missing)
    model: object
    rtl: object

    def __str__(self):
        return f"clock {self.t}: {self.key} model={self.model!r} rtl={self.rtl!r}"


def _plain(row: dict) -> dict:
    """A row in its JSON shape (tuples as lists), as a dump holds it."""
    return json.loads(json.dumps(row))


def compare_state_rows(model_rows: list, rtl_rows: list) -> StateDiff | None:
    """The first clock (in the model's clock order) where the rows differ, and the first
    key there (STATE_REQUIRED then STATE_OPTIONAL order): a required key the dump lacks
    differs (rtl "<missing>"); an optional key is compared when the dump has it. A clock
    in one list but not the other differs on "t". None when they agree."""
    model = [_plain(r) for r in model_rows]
    rtl = {r["t"]: r for r in (_plain(r) for r in rtl_rows)}
    keys = STATE_REQUIRED + STATE_OPTIONAL
    seen = set()
    for m in model:
        t = m["t"]
        seen.add(t)
        r = rtl.get(t)
        if r is None:
            return StateDiff(t, "t", t, None)
        for k in keys:
            if k not in r:
                if k in STATE_REQUIRED:
                    return StateDiff(t, k, m.get(k), "<missing>")
                continue
            if m.get(k) != r[k]:
                return StateDiff(t, k, m.get(k), r[k])
    extra = sorted(t for t in rtl if t not in seen)
    if extra:
        return StateDiff(extra[0], "t", None, extra[0])
    return None


def write_state(path: Path, rows: list, chain_id: str | None = None, t0: int = 0):
    with open(path, "w") as handle:
        handle.write(json.dumps({"format": STATE_FORMAT, "chain": chain_id, "t0": t0}) + "\n")
        for row in rows:
            handle.write(json.dumps(_plain(row)) + "\n")


def read_state(path: Path) -> list:
    """The rows of a dump, "t" re-based by the header's "t0"."""
    rows, t0 = [], 0
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "t" not in row:
            t0 = row.get("t0", 0) or 0
            continue
        if t0:
            row["t"] -= t0
        rows.append(row)
    return rows


def model_state_rows(run_id: str, config=None, files=None) -> list:
    """The model's per-clock rows for one chain id, fast-forward off: chain base and
    refresh anchor from the recorded silicon run when the corpus (or `files`) has it, else
    the generated chain and its built image."""
    from .families import generate
    from .image import build_image
    from .normalize import load_runs, normalize
    from .sim.config import Config
    from .sim.machine import refresh_anchor, simulate_normalized

    cfg = config if config is not None else Config.fitted()
    family = run_id.split("-", 1)[0]
    rec = None
    try:
        rec = next((r for r in load_runs(family, files=files) if r["chain"]["id"] == run_id),
                   None)
    except FileNotFoundError:
        pass
    rows: list = []
    if rec is not None:
        s = normalize(rec)
        simulate_normalized(s.chain, cfg, s.chain_base, clock_log=rows,
                            refresh=refresh_anchor(s))
        return rows
    chain = next((c for c in generate([family]) if c.id == run_id), None)
    if chain is None:
        raise SystemExit(f"unknown chain id {run_id}")
    simulate_normalized(chain, cfg, build_image(chain).chain_base, clock_log=rows)
    return rows


# CLI --------------------------------------------------------------------------------

def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(
            prog="python -m validation.v35s.chains replay", description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--family", nargs="+", help="families to replay, e.g. F0 F1")
    parser.add_argument("--waits", nargs="+", type=int, choices=(0, 1, 2),
                        help="keep chains at these waits (F0w chains are always kept)")
    parser.add_argument("--parity", nargs="+", choices=("even", "odd"))
    parser.add_argument("--ids", "--id", nargs="+", dest="ids",
                        help="keep chain ids containing any of these (with --state or "
                             "--dump-model: the one exact run id)")
    parser.add_argument("--jobs", type=int, default=min(MAX_JOBS, os.cpu_count() or 1),
                        help=f"Verilator worker processes (default min({MAX_JOBS}, CPUs))")
    parser.add_argument("--output-dir", type=Path, help=f"default {SIM_OUTPUT}")
    parser.add_argument("--resume", action="store_true",
                        help="skip chain ids already replayed with the current RTL build")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="tick limit per run")
    parser.add_argument("--state", type=Path, metavar="DUMP",
                        help="compare an RTL state dump (JSON Lines) with the model's rows "
                             "for --id")
    parser.add_argument("--dump-model", type=Path, metavar="DUMP",
                        help="write the model's per-clock rows for --id in the dump format")
    parser.add_argument("--config", metavar="PATH",
                        help="with --state/--dump-model: model config (default the tracked fit)")
    parser.add_argument("--core", choices=tuple(SIM_CORES), default="ucore",
                        help="(WP82) the model lane's core: ucore (build_sim.sh direct) or chain "
                             "(build_sim.sh direct chain), each with its own default output")
    parser.add_argument("--diag", action="store_true",
                        help="(WP82) with --core chain: the lane's diagnostics on stderr")
    parser.add_argument("--score", action="store_true",
                        help="(WP82) score the core's replays (--output-dir or the core's "
                             "default) against silicon and the frozen model, with the pre window")
    parser.add_argument("--show", type=int, default=0,
                        help="with --score: list the first N runs where RTL != model per family")
    return parser


def _state_main(args) -> int:
    from .sim.config import Config
    if not args.ids or len(args.ids) != 1:
        raise SystemExit("--state and --dump-model take exactly one --id RUN_ID")
    run_id = args.ids[0]
    rows = model_state_rows(run_id, Config.fitted(args.config))
    if args.dump_model:
        write_state(args.dump_model, rows, run_id)
        print(f"{len(rows)} model rows -> {args.dump_model}")
    if args.state:
        rtl = read_state(args.state)
        diff = compare_state_rows(rows, rtl)
        if diff is None:
            print(f"{run_id}: {len(rows)} clocks, state rows identical")
            return 0
        print(f"{run_id}: first difference at {diff}")
        return 1
    return 0


def main(argv=None, args=None) -> int:
    if args is None:
        args = build_parser().parse_args(argv)
    if args.state or args.dump_model:
        return _state_main(args)
    if not args.family:
        raise SystemExit("replay needs --family (or --state/--dump-model with --id)")
    if args.jobs < 1:
        raise SystemExit("--jobs must be at least 1")
    binary, default_output = SIM_CORES[args.core]
    output_dir = args.output_dir or default_output
    if args.score:
        score_lane(args.family, tuple(args.waits or (0, 1, 2)), output_dir, args.jobs, args.show)
        return 0
    if not binary.exists():
        print(f"error: the Verilator model is not built ({binary} is missing; "
              f"fpga/v35s/build_sim.sh direct{' chain' if args.core == 'chain' else ''})",
              file=sys.stderr)
        return 2
    chains = select_chains(args.family, args.waits, args.parity, args.ids)
    if not chains:
        raise SystemExit("no chains match the filters")
    identity = rtl_identity(binary)
    print(f"{len(chains)} chains from {' '.join(args.family)} -> {output_dir}", flush=True)
    print(f"RTL: {identity['binary']} built {identity['binary_mtime_iso']}, fpga/v35s "
          f"{(identity['fpga_commit'] or '?')[:12]} tree {(identity['fpga_tree'] or '?')[:12]}"
          f"{' (uncommitted changes)' if identity['fpga_dirty'] else ''}", flush=True)
    if identity["sources_newer"]:
        print(f"warning: sources newer than the binary: {' '.join(identity['sources_newer'])}"
              f" (fpga/v35s/build_sim.sh direct)", flush=True)
    stats = replay(chains, output_dir=output_dir, jobs=args.jobs, resume=args.resume,
                   limit=args.limit, identity=identity, core=args.core, diag=args.diag)
    return 1 if stats["incomplete"] else 0


if __name__ == "__main__":
    sys.exit(main())
