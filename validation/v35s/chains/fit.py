"""Staged fitting of the chain cycle model (plan, "Model" / "Staged fit").

Each stage scores model configurations against one or more families by exact
match (score.py's definition: the (clock, kind, addr, width, length) list from
t_fill on) and freezes what it pins for the stages after it:

  1 bus      F0, F0w   read-off: cycle lengths per wait setting, nothing fitted
  2 queue    F0        the full grid of queue/decoder structure, F0-pinned costs
                       (a structure that gets a third of F0 also gets a descent
                       over those integers); every 18/18 combination survives
  3 markers  F1, F2,   per survivor: marker/hand-off/arbitration enums and the
             F9, F3,   integers of the marker and F2 body classes; the drains
             F6        (F3, F6) vote on the structure too; F9 (release series)
                       joins F2
  4 reg EU   F3        register-class integers
  5 memory   F4, F5    EA table, memory-class integers, odd_split, latencies
  6 arbiter  F6        the arbitration enums, then the queue/sync enums again
  7 validate F7, F8    zero free parameters

Every stage fits PUSH-, store- and OUT-marked chains (fifth fit: the OUT
marker, held out until the fourth, is in every stage's objective and in the
polish guard; HELD_OUT is empty). A structure
whose queue over-fills its six bytes (sim.queue.QueueOverflow) scores the run
as a miss.

Search: structural enums are enumerated (never tuned), integers by
best-improvement coordinate descent with steps +-1, +-2. A configuration's
score is lexicographic: (exact runs of the guard families, i.e. every earlier
stage's, exact runs of this stage's families, -summed first-divergence
residual). The residual of a run is |model - silicon| clock at its first
differing event when kind/address/width/length agree there, else MISMATCH.

Diagnostics per stage: exact counts per family x parity x waits x marker kind,
the residual histogram, and the knob-dependence check: for every free
integer, the value that maximises exact matches within each parity / waits /
k / marker group. A best value that differs between groups is a structural
finding (the brief: never encode it as a per-knob parameter).

    python -m validation.v35s.chains fit --stage 3 [--to 5] [--from stage2.json] [--jobs 8]
    python -m validation.v35s.chains fit --all

Results go to build/validation/v35s/chains/fit/stageN.json (config, scores,
survivors) and fit.json (the final config).
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import multiprocessing as mp
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .derive import variant_of
from .families import FAMILIES, UNMODELLED
from .score import aligned
from .sim.config import DEFAULT, DEFAULT_COST, OPTIONS, Config

OUT_DIR = Path("build/validation/v35s/chains/fit")
MISMATCH = 8                 # residual charged when the first differing events differ in kind
STEPS = (1, -1, 2, -2)


def say(*a):
    print(*a, flush=True)


# Data ----------------------------------------------------------------------------

@dataclass
class Run:
    run_id: str
    family: str
    parity: str
    waits: int
    marker: str
    variant: str
    k: int | None
    chain: object
    base: int
    silicon: list            # aligned events
    t_fill: int | None
    refresh: tuple | None = None   # refresh on: (clock after t_fill, row) of the first refresh


_DATA: dict[str, Run] = {}
# (WP16) F12's two series are fitted in different stages: series A (the OUT after a register
# form, M0 NOP^n X OUT) with the I/O and start-sync enums in stage 6, series B (the 4-byte
# form and the shift count byte, marker-less NOP^n X and M0 X M1) with F11 in stage 3.
SERIES = {"F12A": ("F12", "-a-"), "F12B": ("F12", "-b-"),
          # (WP19) F14: T (the TEST/XCH format ladder) and G (group memory forms) with the
          # memory templates in stage 5, O (the OUT after a register form) in stage 6
          "F14T": ("F14", "-t-"), "F14G": ("F14", "-g-"), "F14O": ("F14", "-o-"),
          # (WP20) F15: A (the AND control, TEST imm, the imm8 forms), P (POP / PUSH r/m) and K
          # (the k = 2 second instance) with the memory templates in stage 5, O (the OUT
          # frame's remainder) in stage 6
          "F15A": ("F15", "-a-"), "F15P": ("F15", "-p-"), "F15K": ("F15", "-k-"),
          "F15O": ("F15", "-o-"),
          # (WP21) F16: R (the reg-field ladder) and P (POP's held fetch) with the memory
          # templates in stage 5, L (long register forms after the OUT marker) in stage 6,
          # S (the marker-less shift's count byte) in stage 3 with F11 and F12 B
          "F16R": ("F16", "-r-"), "F16P": ("F16", "-p-"), "F16L": ("F16", "-l-"),
          "F16S": ("F16", "-s-"),
          # (WP25) F19: I (the immediate memory forms) with the memory templates in stage 5,
          # D (the DW I/O forms after register forms and I/O) with the I/O enums in stage 6
          "F19I": ("F19", "-i-"), "F19D": ("F19", "-d-")}
_POOL = None
_POOL_SIZE = 0
JOBS = max(1, (os.cpu_count() or 2))


def load(families) -> list[str]:
    """Load (once) and normalise the silicon runs of families; returns their ids."""
    from .normalize import load_runs, normalize
    from .sim.machine import refresh_anchor

    ids = []
    for family in families:
        if family in SERIES:
            # a series of a family (F12A / F12B): its runs by id
            tag = SERIES[family][1]
            ids += [i for i in load([SERIES[family][0]]) if tag in i]
            continue
        cached = [r for r in _DATA.values() if r.family == family]
        if not cached:
            for rec in load_runs(family):
                n = normalize(rec)
                c = n.chain
                _DATA[n.run_id] = Run(n.run_id, c.family, c.parity, c.waits, c.marker_kind,
                                      variant_of(c), c.knobs.get("k"), c, n.chain_base,
                                      aligned(n), n.t_fill, refresh_anchor(n))
            cached = [r for r in _DATA.values() if r.family == family]
        ids += [r.run_id for r in cached]
    return ids


def synthetic(runs: list[Run]):
    """Install runs directly (tests)."""
    global _POOL
    for r in runs:
        _DATA[r.run_id] = r
        _SIG_OF.pop(r.run_id, None)
    cache_clear()
    _close_pool()


def _close_pool():
    global _POOL, _POOL_SIZE
    if _POOL is not None:
        _POOL.terminate()
        _POOL = None
        _POOL_SIZE = 0


# Evaluation ------------------------------------------------------------------------

def run_result(cfg: Config, run: Run) -> tuple[bool, int, int | None, int]:
    """(exact, residual, signed first nonzero residual or None, events matched from t_fill
    before the first difference) for one run."""
    from .sim.machine import simulate_normalized

    try:
        m = aligned(simulate_normalized(run.chain, cfg, run.base, refresh=run.refresh))
    except Exception:          # a structure that cannot run the chain scores as a miss
        return False, 4 * MISMATCH, None, 0
    a = run.silicon
    if a == m:
        return True, 0, None, len(a)
    k = next((i for i, (x, y) in enumerate(zip(a, m)) if x != y), min(len(a), len(m)))
    if k < len(a) and k < len(m) and a[k][1:] == m[k][1:]:
        d = m[k][0] - a[k][0]
        return False, abs(d), d, k
    return False, MISMATCH, None, k


def _work(args):
    cfg, ids = args
    if isinstance(cfg, dict):              # _evaluate_uncached sends JSON, as before
        cfg = Config.from_json(cfg)
    return [run_result_reads(cfg, _DATA[i]) for i in ids]


def _pool():
    global _POOL, _POOL_SIZE
    if JOBS <= 1:
        return None
    if _POOL is None or _POOL_SIZE != len(_DATA):
        _close_pool()
        _POOL = mp.get_context("fork").Pool(JOBS)
        _POOL_SIZE = len(_DATA)
    return _POOL


# Result cache ------------------------------------------------------------------------
#
# A run's simulation is a deterministic function of the run and of what it reads from
# the configuration: the structural fields and top-level integers it looks at, and, of
# the per-class tables, the cost entries of the classes its chain runs and the EA
# entries of the address modes it uses (run_classes). Each simulated run records the
# fields it read (RecordingConfig: a field's first read is noted); any configuration
# that agrees on those fields and on the run's classes follows the same path and gets
# the same result. So a descent move on one class integer re-simulates only the runs
# that contain the class, and a grid of structures re-simulates a run only for the
# combinations of the fields it actually reads (a memory-form enum is never read by a
# chain without a memory operand; arbiter_q only under arbiter=fetch_wins_le_q).
#
# Key: (signature, the classes' cost JSON, the modes' EA JSON) -> run id -> [(read
# field names, {their values (type-tagged): result})], most recently hit first. It lives
# in the main process (the pool only sees the misses), in two generations of at most
# CACHE_LIMIT results each (an entry found in the old one moves to the new one), and is
# emptied at every stage start and at the start of every grid (stage_n, polish): nothing
# reuses results across grids, and a stage-6 grid alone can fill it (--cache-limit; 0
# turns the cache off). An entry keeps growing in place while it is hit (at fixed integers
# a grid's structures all share one entry per signature), so generations alone do not
# bound it: when both generations together hold more than 2 * CACHE_LIMIT results, both
# are dropped (a flush; the cache is pure, results are unaffected). evaluate() simulates a large batch of configurations in
# rounds so that configurations of the batch can reuse each other's runs.

CACHE_LIMIT = 3_000_000
_SIG_OF: dict[str, int] = {}             # run id -> index into _SIGS
_SIGS: list[tuple[tuple, tuple]] = []    # (cost classes, EA mode classes)
_SIG_INDEX: dict[tuple, int] = {}
_NAMES: dict[tuple, tuple] = {}          # one shared tuple per distinct read-field set
_CACHE_NEW: dict = {}
_CACHE_OLD: dict = {}
_CACHE_COUNT = 0                         # results in _CACHE_NEW
_CACHE_OLD_COUNT = 0                     # results in _CACHE_OLD
_CACHE_FLUSHES = 0
CACHE_STATS = {"lookups": 0, "hits": 0}
USE_CACHE = True
_FIELDS = tuple(f.name for f in dataclasses.fields(Config) if f.name not in ("cost", "ea"))


class _Recorded:
    """Non-data descriptor of a RecordingConfig field: the first read notes the name and
    caches the value on the instance (later reads are plain attribute reads)."""

    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __get__(self, obj, typ=None):
        if obj is None:
            return self
        v = obj._values[self.name]
        obj._reads.append(self.name)
        obj.__dict__[self.name] = v
        return v


class RecordingConfig(Config):
    """A Config that notes which fields the simulation reads (cost and ea are plain)."""


for _name in _FIELDS:
    setattr(RecordingConfig, _name, _Recorded(_name))


def recording(cfg: Config) -> RecordingConfig:
    r = object.__new__(RecordingConfig)
    r.__dict__.update(_values=cfg.__dict__, _reads=[], cost=cfg.cost, ea=cfg.ea)
    return r


def run_result_reads(cfg: Config, run: Run) -> tuple[tuple, tuple]:
    """(run_result, the names of the fields the simulation read, sorted)."""
    rc = recording(cfg)
    res = run_result(rc, run)
    return res, tuple(sorted(rc._reads))


def run_classes(chain) -> tuple[tuple, tuple]:
    """(cost classes, EA mode classes) the model can read for a chain: the class of every
    instruction the EU can run (it runs them in order; decode with the register effects the
    EU applies), shift_imm for a memory shift (rmw_shift=shift reads its exec), and the mode
    class of every memory operand.

    Decoding starts at the prelude's tail, not the first LS: with prelude_tail != standin the
    machine (sim/machine.py) runs image.prelude_tail before the chain, so the EU also runs
    its MOV r16,imm16 (imm), MOV sreg,AW (reg), the prelude marker and the PAD NOP (reg).
    From the first LS only, the projection key omitted those classes, and a cached result
    was reused across a reg/imm move (test_perf ProjectionKey
    test_model_reads_only_the_projected_classes and
    test_irrelevant_class_does_not_change_results, on F0-ls-pE-w0). The segs tail is a
    superset of the regs tail; a class the config never reads costs only cache hits, never
    correctness, so the signature stays independent of the config."""
    from .image import prelude, prelude_tail
    from .sim.templates import decode, execute

    tail = prelude_tail(chain, True)
    code, regs = tail + chain.code, dict(chain.regs)
    # (WP88, F35) the code offset of code[0] in the code segment, as the EU keeps it: an absolute
    # transfer target (BR / CALL r16, the far forms) is walked to its chain offset (the chain
    # follows the prelude in the code segment)
    regs["code_at"] = len(prelude(chain.regs, chain.wtc, chain.rfm, chain.prc,
                                  getattr(chain, "prelude_marker", None))) - len(tail)
    pc = 0
    classes, modes = set(), set()
    while True:
        op = decode(code, pc, regs)
        classes.add(op.cls)
        if op.shift:
            classes.add("shift_imm")
        if op.nowrite:
            classes.add("rmw_imm")           # grp_read=rmw runs it under rmw_imm
        if op.dbit == 0 and op.cls == "load_alu" and op.ea is not None:
            classes.add("rmw")               # (WP19) dest_route=slot runs it under rmw
        if op.ea is not None and op.mode_class is not None:   # (WP52) XLAT has none
            modes.add(op.mode_class)
            if op.mode_class == "base_index_disp" and op.disp == 2:
                modes.add("base_index_disp16")   # (WP27) ea_disp16=own reads it
            if op.mode_class == "direct" and op.modrm:
                modes.add("base_disp")           # (WP27) ea_direct=base_disp reads it
        if op.cls == "halt" or pc >= len(code):
            break
        execute(op, code, regs)
        pc = op.target if op.target is not None else pc + op.length   # (WP55) taken transfers
    return tuple(sorted(classes)), tuple(sorted(modes))


def _sig(run_id: str) -> int:
    k = _SIG_OF.get(run_id)
    if k is None:
        sig = run_classes(_DATA[run_id].chain)
        k = _SIG_INDEX.setdefault(sig, len(_SIGS))
        if k == len(_SIGS):
            _SIGS.append(sig)
        _SIG_OF[run_id] = k
    return k


class _Projector:
    """Cache keys of one configuration: per run signature its classes' cost and modes' EA
    entries; per read-field set the fields' values (type-tagged: True is not 1)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.keys: dict[int, tuple] = {}
        self.vals: dict[tuple, tuple] = {}

    def key(self, sig: int) -> tuple:
        k = self.keys.get(sig)
        if k is None:
            classes, modes = _SIGS[sig]
            cost, ea = self.cfg.cost, self.cfg.ea
            k = (sig, json.dumps([[c, cost.get(c)] for c in classes], sort_keys=True),
                 json.dumps([[m, ea.get(m)] for m in modes]))
            self.keys[sig] = k
        return k

    def values(self, names: tuple) -> tuple:
        v = self.vals.get(names)
        if v is None:
            d = self.cfg.__dict__
            v = tuple((type(d[n]), d[n]) for n in names)
            self.vals[names] = v
        return v


def projection_key(cfg: Config, run_id: str) -> tuple:
    """The class part of a run's cache key under cfg (its cost/EA projection)."""
    return _Projector(cfg).key(_sig(run_id))


def _cache_get(key):
    global _CACHE_OLD_COUNT
    entry = _CACHE_NEW.get(key)
    if entry is None:
        entry = _CACHE_OLD.pop(key, None)
        if entry is not None:
            n = _entry_size(entry)
            _CACHE_OLD_COUNT -= n
            _cache_adopt(key, entry, n)
    return entry


def _entry_size(entry) -> int:
    return sum(len(t) for groups in entry.values() for _, t in groups)


def _cache_adopt(key, entry, n=None):
    global _CACHE_COUNT, _CACHE_NEW, _CACHE_OLD, _CACHE_OLD_COUNT
    if _CACHE_COUNT >= CACHE_LIMIT:
        _CACHE_OLD, _CACHE_NEW = _CACHE_NEW, {}
        _CACHE_OLD_COUNT, _CACHE_COUNT = _CACHE_COUNT, 0
    _CACHE_NEW[key] = entry
    _CACHE_COUNT += _entry_size(entry) if n is None else n


def _lookup(entry, run_id, proj):
    groups = entry.get(run_id) if entry is not None else None
    if groups:
        for k, (names, table) in enumerate(groups):
            r = table.get(proj.values(names))
            if r is not None:
                if k:
                    groups.insert(0, groups.pop(k))
                return r
    return None


def _cache_put(key, run_id, names, values, result):
    global _CACHE_COUNT
    entry = _cache_get(key)
    if entry is None:
        entry = {}
        _cache_adopt(key, entry)
    groups = entry.setdefault(run_id, [])
    for n, table in groups:
        if n is names:
            break
    else:
        table = {}
        groups.insert(0, (names, table))
    if values not in table:
        _CACHE_COUNT += 1
    table[values] = result
    if _CACHE_COUNT + _CACHE_OLD_COUNT > 2 * CACHE_LIMIT:
        _cache_flush()


def _cache_flush():
    """Drop both generations (the memory bound; see above)."""
    global _CACHE_NEW, _CACHE_OLD, _CACHE_COUNT, _CACHE_OLD_COUNT, _CACHE_FLUSHES
    _CACHE_NEW, _CACHE_OLD, _CACHE_COUNT, _CACHE_OLD_COUNT = {}, {}, 0, 0
    _RESULTS.clear()                     # interning only shares memory; results unchanged
    _CACHE_FLUSHES += 1


def cache_reset():
    """Empty the result cache's generations and the memos built on it (tie-break, corpus
    guard), keeping CACHE_STATS (a stage's totals span its grids)."""
    global _CACHE_FLUSHES
    _TB.clear()
    _CORPUS_MEMO.clear()
    _cache_flush()
    _CACHE_FLUSHES = 0


def cache_clear():
    cache_reset()
    CACHE_STATS.update(lookups=0, hits=0)


def cache_size() -> int:
    """Results held in both generations."""
    return sum(len(t) for gen in (_CACHE_NEW, _CACHE_OLD) for entry in gen.values()
               for groups in entry.values() for _, t in groups)


def cache_log(label: str, log) -> None:
    """One line on the cache at the end of a grid."""
    n, hits = CACHE_STATS["lookups"], CACHE_STATS["hits"]
    log(f"  {label} cache: {cache_size()} results held ({_CACHE_COUNT} new + "
        f"{_CACHE_OLD_COUNT} old, limit {CACHE_LIMIT}{'' if USE_CACHE else ', off'}, "
        f"{_CACHE_FLUSHES} flushes this grid), {len(_RESULTS)} distinct results interned, "
        f"{len(_CORPUS_MEMO)} corpus memos, {len(_TB)} tie-break memos; stage so far "
        f"{hits}/{n} reused, {n - hits} simulated")


_RESULTS: dict = {}                      # one shared tuple per distinct result


def _evaluate_uncached(cfgs, ids):
    pool = _pool()
    if pool is None or len(cfgs) * len(ids) < 40:
        return [[run_result(c, _DATA[i]) for i in ids] for c in cfgs]
    per = max(1, JOBS // len(cfgs))
    size = -(-len(ids) // per)
    chunks = [ids[k:k + size] for k in range(0, len(ids), size)]
    tasks = [(c.to_json(), ch) for c in cfgs for ch in chunks]
    out = pool.map(_work, tasks, chunksize=1)
    res = []
    for ci in range(len(cfgs)):
        res.append([x[0] for part in out[ci * len(chunks):(ci + 1) * len(chunks)]
                    for x in part])
    return res


def _simulate(cfgs, misses, ids) -> list:
    """(result, read names) per miss (config index, position, key), over the pool. A task
    holds runs of one configuration (sent as the object: no JSON round trip); a
    configuration's misses are split into near-equal tasks of about `size` runs."""
    pool = _pool()
    if pool is None or len(misses) < 40:
        return [run_result_reads(cfgs[ci], _DATA[ids[p]]) for ci, p, _ in misses]
    size = max(4, -(-len(misses) // (JOBS * 4)))
    by_cfg = defaultdict(list)
    for m, (ci, _, _) in enumerate(misses):
        by_cfg[ci].append(m)
    tasks, owners = [], []
    for ci, ms in by_cfg.items():
        k = -(-len(ms) // size)
        for j in range(k):
            part = ms[j * len(ms) // k:(j + 1) * len(ms) // k]
            tasks.append((cfgs[ci], [ids[misses[m][1]] for m in part]))
            owners.append(part)
    out = [None] * len(misses)
    for part, got in zip(owners, pool.map(_work, tasks, chunksize=1)):
        for m, x in zip(part, got):
            out[m] = x
    return out


ROUNDS_MIN_CFGS = 33          # batches this large are simulated in rounds (evaluate)


def evaluate(cfgs: list[Config], ids: list[str]) -> list[list[tuple]]:
    """Per config, per run (in ids order) results: cached ones from the result cache, the
    rest simulated over the worker pool.

    A batch of ROUNDS_MIN_CFGS or more configurations (a grid, a large descent round) is
    simulated in up to three rounds so that configurations can reuse each other's runs:
    the first configurations (enough to keep the pool busy); then one run per group of
    misses that the run's last read-field set predicts to agree (or that agree in every
    field); then whatever the cache still misses. Smaller batches take one round."""
    if not cfgs:
        return []
    if not USE_CACHE:
        return _evaluate_uncached(cfgs, ids)
    by_sig = defaultdict(list)                     # signature -> positions in ids
    for p, i in enumerate(ids):
        by_sig[_sig(i)].append(p)
    res = [[None] * len(ids) for _ in cfgs]
    projs = [_Projector(c) for c in cfgs]
    simulated = 0

    def look(cis, positions=None):
        """Misses (config index, position, key) of cis (or of the given (ci, p) pairs)."""
        out = []
        pairs = positions if positions is not None else [
            (ci, sig, ps) for ci in cis for sig, ps in by_sig.items()]
        for ci, sig, ps in pairs:
            proj = projs[ci]
            key = proj.key(sig)
            entry = _cache_get(key)
            row = res[ci]
            for p in ps:
                r = _lookup(entry, ids[p], proj)
                if r is None:
                    out.append((ci, p, key))
                else:
                    row[p] = r
        return out

    def run(misses):
        nonlocal simulated
        simulated += len(misses)
        for (ci, p, key), (r, names) in zip(misses, _simulate(cfgs, misses, ids)):
            r = _RESULTS.setdefault(r, r)
            names = _NAMES.setdefault(names, names)
            res[ci][p] = r
            _cache_put(key, ids[p], names, projs[ci].values(names), r)

    if len(cfgs) < ROUNDS_MIN_CFGS:
        misses = look(range(len(cfgs)))
        if misses:
            run(misses)
    else:
        first = max(1, -(-16 * max(JOBS, 1) // len(ids)))    # >= 16 runs per worker
        misses = look(range(first))
        if misses:
            run(misses)
        misses = look(range(first, len(cfgs)))
        reps, deferred, seen = [], [], set()
        for m in misses:
            ci, p, key = m
            entry = _cache_get(key)
            groups = entry.get(ids[p]) if entry is not None else None
            if groups:
                names = groups[0][0]                         # predicted: the last read set
                dk = (key, p, names, projs[ci].values(names))
            else:
                dk = (key, p, None, projs[ci].values(_FIELDS))   # every field agrees
            if dk in seen:
                deferred.append(m)
            else:
                seen.add(dk)
                reps.append(m)
        if reps:
            run(reps)
        if deferred:
            sig_of = {}
            for ci, p, _ in deferred:
                sig_of.setdefault((ci, _sig(ids[p])), []).append(p)
            misses = look(None, [(ci, sig, ps) for (ci, sig), ps in sig_of.items()])
            if misses:
                run(misses)
    n = len(cfgs) * len(ids)
    CACHE_STATS["lookups"] += n
    CACHE_STATS["hits"] += n - simulated
    return res


# Stage 8 (refresh) ranks configurations with no exact run apart by the events matched from
# t_fill before the first difference (summed over the stage's runs), after the exact count:
# a refresh run has ~20 refreshes, so the first-divergence residual alone cannot tell a
# structure that gets the first long shift right from one that misses its second refresh.
RANK_MATCHED = False


@dataclass
class Scored:
    cfg: Config
    guard: int
    exact: int
    resid: int
    results: list = field(default_factory=list, repr=False)   # stage-family results
    matched: int = 0

    @property
    def key(self):
        if RANK_MATCHED:
            return (self.guard, self.exact, self.matched, -self.resid)
        return (self.guard, self.exact, -self.resid)


def score_many(cfgs, ids, guard_ids=()) -> list[Scored]:
    all_ids = list(guard_ids) + list(ids)
    out = []
    for cfg, res in zip(cfgs, evaluate(cfgs, all_ids)):
        g, s = res[:len(guard_ids)], res[len(guard_ids):]
        out.append(Scored(cfg, sum(r[0] for r in g), sum(r[0] for r in s),
                          sum(r[1] for r in g) + sum(r[1] for r in s), s,
                          sum(r[3] for r in s)))
    return out


# Parameters ------------------------------------------------------------------------

def getp(cfg: Config, name: str) -> int:
    if "." in name:
        cls, key = name.split(".", 1)
        return cfg.ea.get(key, 0) if cls == "ea" else cfg.c(cls, key)
    return getattr(cfg, name)


def setp(cfg: Config, **kw) -> Config:
    return cfg.replace(**kw)


def grid(base: Config, options: dict) -> list[Config]:
    """Every combination of the enumerated options on top of base (invalid ones dropped)."""
    names = list(options)
    out = []
    for values in itertools.product(*(options[n] for n in names)):
        kw = dict(zip(names, values))
        if kw.get("opcode_take", base.opcode_take) == "prefetch" and kw.get("opcode_overlap", 0):
            continue                       # overlap only applies to opcode_take=start
        try:
            out.append(base.replace(**kw))
        except ValueError:
            continue
    return out


def _pair_moves(cfg: Config, params) -> list[Config]:
    out = []
    for a, b in itertools.combinations(params, 2):
        va, vb = getp(cfg, a), getp(cfg, b)
        for da, db in ((1, -1), (-1, 1), (1, 1), (-1, -1)):
            if va + da >= 0 and vb + db >= 0:
                out.append(setp(cfg, **{a: va + da, b: vb + db}))
    return out


def _admissible(best: Scored, scored: list) -> Scored | None:
    """The best of scored above best on the key that the corpus guard admits (without a
    guard: the best of scored)."""
    if CORPUS_GUARD is None:
        return max(scored, key=lambda s: s.key, default=None)
    for s in sorted(scored, key=lambda s: s.key, reverse=True):
        if s.key <= best.key:
            return None
        if corpus_ok(best.cfg, s.cfg):
            return s
    return None


def descend(start: Scored, params, ids, guard_ids=(), steps=STEPS, max_rounds=40,
            log=None, label="", pairs=False, max_pair_rounds=2) -> Scored:
    """Best-improvement coordinate descent over integer params.

    Moves are single integers by +-1/+-2; with pairs=True, when no single move
    improves, every pair of integers is moved by +-1 together (an escape for
    two clocks that trade against each other), at most max_pair_rounds times.
    """
    best = start
    for rnd in range(max_rounds):
        cands = []
        for p in params:
            v = getp(best.cfg, p)
            for d in steps:
                if v + d >= 0:
                    cands.append(setp(best.cfg, **{p: v + d}))
        scored = score_many(cands, ids, guard_ids)
        top = _admissible(best, scored)
        if (top is None or top.key <= best.key) and pairs and max_pair_rounds > 0:
            max_pair_rounds -= 1
            scored = score_many(_pair_moves(best.cfg, params), ids, guard_ids)
            top = _admissible(best, scored)
        if top is None or top.key <= best.key:
            break
        best = top
        if log:
            log(f"    {label} round {rnd + 1}: guard {best.guard} exact {best.exact} "
                f"resid {best.resid}")
    return best


def diff_cfg(a: Config, b: Config) -> dict:
    """Fields and integers of b that differ from a."""
    da, db = a.to_json(), b.to_json()
    out = {}
    for k in da:
        if k in ("cost", "ea"):
            continue
        if da[k] != db[k]:
            out[k] = db[k]
    for cls in sorted(set(da["cost"]) | set(db["cost"])):
        for n in sorted(set(da["cost"].get(cls, {})) | set(db["cost"].get(cls, {}))):
            x, y = da["cost"].get(cls, {}).get(n, 0), db["cost"].get(cls, {}).get(n, 0)
            if x != y:
                out[f"{cls}.{n}"] = y
    for n in sorted(set(da["ea"]) | set(db["ea"])):
        if da["ea"].get(n) != db["ea"].get(n):
            out[f"ea.{n}"] = db["ea"].get(n)
    return out


# Ties and joint enum/integer moves (WP18) ---------------------------------------------
#
# The descent key ranks a structure by the guard, the stage's exact runs and the residual.
# When two structures tie on exact runs (guard and stage), the tie is broken on the exact
# count over every recorded family (TIE_FAMILIES, not only the stage's), then on the events
# matched before the first miss there, then on the residual; every tie is recorded in the
# stage JSON as a finding.
#
# TIE_FAMILIES is derived from families.FAMILIES (in its order) so a new family cannot be
# left out. Since 2026-10-27 the refresh-on families F13, F17 and F18 are in, so a tie is a
# tie on every family; before that the explicit list lacked them, and a tie that differed
# only on refresh-on runs was decided by enumeration order (see docs "The fitter's stage 6
# under the family guard").

TIE_FAMILIES = list(FAMILIES)
TIE_IDS = None                # run ids of the tie-break (None: every run of TIE_FAMILIES)
_TB: dict = {}


def tiebreak(cfg: Config) -> tuple[int, int]:
    """(exact runs, events matched) of cfg over every recorded family (memoised)."""
    k = json.dumps(cfg.to_json(), sort_keys=True)
    v = _TB.get(k)
    if v is None:
        # (WP49) only the families with corpus data that the simulator can run: a family
        # not yet acquired has no runs, and an UNMODELLED one would make the model raise
        ids = TIE_IDS if TIE_IDS is not None else corpus_guard_ids(
            [f for f in TIE_FAMILIES if f not in UNMODELLED])
        res = evaluate([cfg], ids)[0]
        v = (sum(r[0] for r in res), sum(r[3] for r in res))
        _TB[k] = v
    return v


def tied(a: Scored, b: Scored) -> bool:
    if RANK_MATCHED:
        return a.key[:3] == b.key[:3]
    return (a.guard, a.exact) == (b.guard, b.exact)


def tie_key(s: Scored) -> tuple:
    """The stage key with ties on exact runs broken by every family's exact runs and
    matched events, then the residual."""
    head = s.key[:3] if RANK_MATCHED else (s.guard, s.exact)
    return head + tiebreak(s.cfg) + (-s.resid,)


def pick(finals: list[Scored]) -> tuple[Scored, list[dict]]:
    """The best of finals under tie_key, and the ties it broke (as findings)."""
    top = max(finals, key=lambda s: s.key)
    group = [f for f in finals if tied(f, top)]
    if len(group) == 1:
        return top, []
    group.sort(key=tie_key, reverse=True)
    best = group[0]
    ties = []
    for f in group[1:]:
        ties.append({"diff": diff_cfg(best.cfg, f.cfg), "guard": f.guard, "exact": f.exact,
                     "resid": f.resid, "all_exact": tiebreak(f.cfg)[0],
                     "all_matched": tiebreak(f.cfg)[1],
                     "chosen_all_exact": tiebreak(best.cfg)[0],
                     "chosen_all_matched": tiebreak(best.cfg)[1],
                     "chosen_resid": best.resid})
    return best, ties


def int_classes(name: str) -> str | None:
    """The cost class (or 'ea:<mode>') an integer belongs to; None for a top-level one."""
    if "." not in name:
        return None
    cls, key = name.split(".", 1)
    return f"ea:{key}" if cls == "ea" else cls


def better(a: Scored, b: Scored) -> bool:
    """a beats b: on the stage key, or by tie_key when they tie on exact runs."""
    if tied(a, b):
        return tie_key(a) > tie_key(b)
    return a.key > b.key


# Whole-corpus guard (WP26) ---------------------------------------------------------------
#
# The stage objectives see only their own families and the earlier stages' guard; WP25's
# descent from the hand fit drifted along objective ties into enums that lost 51 runs
# outside them. With CORPUS_GUARD set (run ids: every recorded family by default, see
# corpus_guard_ids), a move of the descent, the enum sweep or the stage grid is accepted
# only if no family loses an exact run against the configuration it moves from:
# CORPUS_MODE "family" compares each family's exact count (a trade inside one family is
# allowed), "run" every run (no exact run may be lost anywhere). None: no guard (as before).

CORPUS_GUARD: list | None = None
CORPUS_MODE = "family"
# The stage's input configuration (before any seed): a family (a run, in run mode) may lose
# exact runs against the configuration a move starts from as long as it stays at or above
# its count here. A seed that drops a family below the input (stage 5's ea.base_disp 0 from
# the hand fit's 2) can then be climbed back out of; nothing ends below the input.
CORPUS_REF: Config | None = None
CORPUS_STATS = {"checked": 0, "refused": 0}
_CORPUS_MEMO: dict = {}


def corpus_guard_ids(families=None) -> list[str]:
    """The run ids of every family with recorded data (or of families); by default the
    families the simulator can run (not families.UNMODELLED)."""
    ids = []
    for fam in families or [f for f in FAMILIES if f not in UNMODELLED]:
        try:
            ids += load([fam])
        except FileNotFoundError:
            continue
    return ids


def _corpus_exact(cfg: Config) -> frozenset:
    """The exact runs of CORPUS_GUARD under cfg (memoised on the configuration)."""
    k = json.dumps(cfg.to_json(), sort_keys=True)
    v = _CORPUS_MEMO.get(k)
    if v is None:
        res = evaluate([cfg], CORPUS_GUARD)[0]
        v = frozenset(i for i, r in zip(CORPUS_GUARD, res) if r[0])
        _CORPUS_MEMO[k] = v
    return v


def corpus_losses(frm: Config, to: Config) -> dict:
    """{family: runs lost} of the move frm -> to over CORPUS_GUARD under CORPUS_MODE (empty:
    the move is admissible)."""
    if CORPUS_GUARD is None:
        return {}
    a, b = _corpus_exact(frm), _corpus_exact(to)
    lost = defaultdict(int)
    if CORPUS_MODE == "run":
        ref = _corpus_exact(CORPUS_REF) if CORPUS_REF is not None else a
        for i in a - b:
            if i in ref:
                lost[_DATA[i].family] += 1
        return dict(lost)
    for i in a ^ b:
        lost[_DATA[i].family] += 1 if i in a else -1
    lost = {f: n for f, n in lost.items() if n > 0}
    if CORPUS_REF is not None and lost:
        r = _corpus_exact(CORPUS_REF)
        for f in list(lost):
            if sum(_DATA[i].family == f for i in b) >= sum(_DATA[i].family == f for i in r):
                del lost[f]             # still at or above the stage input's count
    return lost


def corpus_ok(frm: Config, to: Config) -> bool:
    if CORPUS_GUARD is None:
        return True
    CORPUS_STATS["checked"] += 1
    ok = not corpus_losses(frm, to)
    CORPUS_STATS["refused"] += not ok
    return ok


def run_changes(a: Scored, b: Scored, ids, guard, ints) -> tuple[list | None, int]:
    """(integers, gains) of b against a: the integers of the classes (and EA modes) of the
    runs whose result differs, plus every top-level integer (None when no run differs);
    and how many runs b makes exact that a does not."""
    all_ids = list(guard) + list(ids)
    ra, rb = evaluate([a.cfg, b.cfg], all_ids)
    classes, gains = set(), 0
    for i, x, y in zip(all_ids, ra, rb):
        if x != y:
            cl, modes = _SIGS[_sig(i)]
            classes.update(cl)
            classes.update(f"ea:{m}" for m in modes)
            gains += y[0] and not x[0]
    if not classes:
        return None, 0
    return [p for p in ints if int_classes(p) is None or int_classes(p) in classes], gains


def enum_sweep(start: Scored, enums: dict, ints, ids, guard, log=say, max_cycles=40,
               desc_rounds=6, label="sweep", groups=None, group_k=3,
               lookahead=False, screen_k=None) -> tuple[Scored, dict]:
    """Coordinate descent over structural enums with the integer descent inside each move.

    The grid ranks every enum combination at the current integers, so an enum whose
    alternative needs other integers (rmw_write_issue with rmw.alu, imm_order with the
    immediate forms' integers, halt_status with out.setup0) never wins there. The sweep
    alternates two tiers until neither moves:
      1. every alternative value of every enum is scored from the current best as it is
         (first improvement, cycling until a full cycle takes no move; then the integers
         are descended);
      2. every alternative that makes some run exact that the best misses is tried with
         the integers of the classes of the runs it changes descended inside it
         (run_changes), most gains first; the first that beats the best is taken and the
         sweep returns to tier 1 (with screen_k, only the screen_k with most gains are
         tried). With lookahead, an alternative that gains no run as is
         gets one descent round first and is screened on what that round gains.
      3. (groups) when tier 2 finds nothing: each coupled group (the enums of one
         mechanism, and the integers that gate it on a coarse lattice) as a grid at the
         current integers, the group_k best by score and the group_k with most runs
         gained descended inside; the best that beats the best is taken.
    A move beats the best on the stage key, or by tie_key when the two tie on exact runs
    (every family's exact runs, then matched events, then the residual). An alternative
    that changes no run is an inert tie: recorded, and taken only when the tie-break
    prefers it. Returns (best, record)."""
    best = start
    record = {"moves": [], "ties": [], "tried": 0, "descended": 0}
    alts = [(n, v) for n, vs in enums.items() for v in vs]
    t0 = time.time()
    tie_seen = set()
    failed_at = None
    failed_alt, failed_group = {}, {}      # tier-2/3 failures (skipped until things change)

    def note_tie(name, v, cur, cand, cfg, inert):
        key = (name, json.dumps(v), json.dumps(best.cfg.to_json(), sort_keys=True))
        if key in tie_seen:
            return
        tie_seen.add(key)
        tb, tc = tiebreak(cand.cfg), tiebreak(best.cfg)
        t = {"enum": name, "value": v, "chosen": cur, "inert": inert,
             "all_exact": tb[0], "all_matched": tb[1],
             "chosen_all_exact": tc[0], "chosen_all_matched": tc[1]}
        if not inert:
            t.update(ints=diff_cfg(cfg, cand.cfg), resid=cand.resid, chosen_resid=best.resid)
        record["ties"].append(t)

    def take(name, v, cur, cand, cfg, how):
        nonlocal best
        log(f"    {label}: {name} {cur!r} -> {v!r} ({how}): guard {best.guard}->{cand.guard} "
            f"exact {best.exact}->{cand.exact} resid {cand.resid}; integers moved "
            f"{json.dumps(diff_cfg(cfg, cand.cfg))}  {time.time() - t0:.0f}s")
        record["moves"].append({"enum": name, "from": cur, "to": v, "how": how,
                                "guard": cand.guard, "exact": cand.exact,
                                "resid": cand.resid, "ints": diff_cfg(cfg, cand.cfg)})
        best = cand

    for cycle in range(max_cycles):
        # tier 1: the alternatives as they are, cycling until a full cycle takes no move
        raw_moves, since, k, pending = 0, 0, 0, []
        while since < len(alts) and k < 4 * len(alts):
            name, v = alts[k % len(alts)]
            k += 1
            since += 1
            cur = getp(best.cfg, name)
            if v == cur and type(v) is type(cur):
                continue
            try:
                cfg = best.cfg.replace(**{name: v})
            except ValueError:
                continue
            record["tried"] += 1
            raw = score_many([cfg], ids, guard)[0]
            if tied(raw, best):
                note_tie(name, v, cur, raw, cfg, raw.resid == best.resid)
            if better(raw, best) and corpus_ok(best.cfg, raw.cfg):
                take(name, v, cur, raw, cfg, "as is")
                raw_moves += 1
                since = 0
        if raw_moves:
            best = descend(best, ints, ids, guard)
        here = json.dumps(best.cfg.to_json(), sort_keys=True)
        if here == failed_at:
            break                      # tier 2 has already found nothing from here
        # tier 2: with the integers descended inside, most gains first
        screened = []
        for name, v in alts:
            cur = getp(best.cfg, name)
            if v == cur and type(v) is type(cur):
                continue
            try:
                cfg = best.cfg.replace(**{name: v})
            except ValueError:
                continue
            raw = score_many([cfg], ids, guard)[0]
            sub, gains = run_changes(best, raw, ids, guard, ints)
            if sub is None:
                note_tie(name, v, cur, raw, cfg, True)
                if tiebreak(raw.cfg) > tiebreak(best.cfg):
                    screened.append((10 ** 6, name, v, cur, cfg, raw, []))
                continue
            if not gains and lookahead and sub and failed_alt.get((name, json.dumps(v))) != 0:
                # a move that gains nothing as is (halt_status without out.setup0 breaks
                # the END block of every run): one descent round inside, then screened
                # like the rest if that round makes runs exact that the best misses
                record["lookahead"] = record.get("lookahead", 0) + 1
                la = descend(raw, sub, ids, guard, max_rounds=1)
                sub2, gains = run_changes(best, la, ids, guard, ints)
                if not gains:
                    failed_alt[(name, json.dumps(v))] = 0
                elif sub2 is not None:
                    raw, sub = la, sub2
            if gains:
                screened.append((gains, name, v, cur, cfg, raw, sub))
        screened.sort(key=lambda x: -x[0])
        if screen_k is not None:
            screened = screened[:screen_k]
        moved = False
        for gains, name, v, cur, cfg, raw, sub in screened:
            if failed_alt.get((name, json.dumps(v))) == gains:
                continue               # failed last time with the same runs gained
            record["descended"] += 1
            cand = descend(raw, sub, ids, guard, max_rounds=desc_rounds) if sub else raw
            if tied(cand, best):
                note_tie(name, v, cur, cand, cfg, False)
            if better(cand, best) and corpus_ok(best.cfg, cand.cfg):
                take(name, v, cur, cand, cfg,
                     f"{len(sub)} integers inside, {gains} runs gained as is" if sub
                     else "inert, every family prefers it")
                moved = True
                break
            failed_alt[(name, json.dumps(v))] = gains
        # tier 3: the coupled groups (enums of one mechanism, with the integers that gate
        # it on a coarse lattice) as a grid at the current integers; the best few by score
        # and by runs gained descended inside
        for gname, group in (groups or {}).items() if not moved else ():
            if failed_group.get(gname, -9) >= len(record["moves"]) - 1:
                continue               # failed within the last move: not again yet
            gt = time.time()
            cands = [c for c in grid(best.cfg, group)
                     if json.dumps(c.to_json(), sort_keys=True) != here]
            scored = []
            for j in range(0, len(cands), 256):
                scored += score_many(cands[j:j + 256], ids, guard)
            by_key = sorted(scored, key=lambda x: x.key, reverse=True)[:group_k]
            gained = []
            for x in scored:
                sub, gains = run_changes(best, x, ids, guard, ints)
                if sub is not None and gains:
                    gained.append((gains, x, sub))
            gained.sort(key=lambda g: -g[0])
            picks = {}
            for x in by_key:
                picks[id(x)] = (x, run_changes(best, x, ids, guard, ints)[0])
            for g, x, sub in gained[:group_k]:
                picks[id(x)] = (x, sub)
            top = None
            for x, sub in picks.values():
                if sub is None:
                    continue
                record["descended"] += 1
                cand = descend(x, sub, ids, guard, max_rounds=desc_rounds)
                if better(cand, top or best) and corpus_ok(best.cfg, cand.cfg):
                    top, top_raw = cand, x
            log(f"    {label} group {gname}: {len(cands)} combinations, {len(picks)} "
                f"descended, best {'none better' if top is None else (top.guard, top.exact)}"
                f"  {time.time() - gt:.0f}s")
            if top is None:
                failed_group[gname] = len(record["moves"])
            else:
                cur = {n: getp(best.cfg, n) for n in group}
                to = {n: getp(top_raw.cfg, n) for n in group}
                take(gname, {n: v for n, v in to.items() if v != cur[n]},
                     {n: v for n, v in cur.items() if v != to[n]}, top, top_raw.cfg,
                     f"group grid of {len(cands)}, integers inside")
                moved = True
                break
        log(f"  {label} cycle {cycle + 1}: guard {best.guard} exact {best.exact} resid "
            f"{best.resid} ({raw_moves} moves as is, {len(screened)} screened for joint "
            f"moves; {record['tried']} tried, {record['descended']} descended)  "
            f"{time.time() - t0:.0f}s")
        if not moved:
            failed_at = here
            if not raw_moves:
                break
    if record["moves"]:
        best = descend(best, ints, ids, guard)
    log(f"  {label} done: guard {best.guard} exact {best.exact} resid {best.resid} "
        f"({len(record['moves'])} moves)  {time.time() - t0:.0f}s")
    record["alternatives"] = len(alts)
    record["seconds"] = round(time.time() - t0, 1)
    return best, record


# Reports ---------------------------------------------------------------------------

def scorecard(cfg: Config, ids) -> dict:
    """Exact counts per family x waits x parity x marker kind, residual histogram, misses."""
    res = evaluate([cfg], ids)[0]
    cells = defaultdict(lambda: [0, 0])
    hist = Counter()
    misses = []
    for i, (ok, resid, signed, *_) in zip(ids, res):
        r = _DATA[i]
        key = f"{r.family} {r.marker:<5} w{r.waits} {'pE' if r.parity == 'even' else 'pO'}"
        cells[key][0] += ok
        cells[key][1] += 1
        if not ok:
            hist[signed if signed is not None else "kind"] += 1
            misses.append((i, signed))
    return {"exact": sum(r[0] for r in res), "runs": len(ids),
            "cells": {k: v for k, v in sorted(cells.items())},
            "histogram": {str(k): v for k, v in sorted(hist.items(), key=lambda kv: str(kv[0]))},
            "misses": misses}


def print_scorecard(card: dict, log=say):
    log(f"  exact {card['exact']}/{card['runs']}")
    fam = defaultdict(lambda: [0, 0])
    for k, (a, b) in card["cells"].items():
        fam[k.split()[0]][0] += a
        fam[k.split()[0]][1] += b
    log("  per family: " + "  ".join(f"{f} {a}/{b}" for f, (a, b) in fam.items()))
    rows = defaultdict(dict)
    for k, (a, b) in card["cells"].items():
        f, m, w, p = k.split()
        rows[f"{f} {m}"][f"{p}-{w}"] = f"{a}/{b}"
    cols = [f"{p}-w{w}" for p in ("pE", "pO") for w in (-1, 0, 1, 2)]
    cols = [c for c in cols if any(c in r for r in rows.values())]
    log("  " + f"{'':12}" + "".join(f"{c:>9}" for c in cols))
    for r, cs in rows.items():
        log("  " + f"{r:12}" + "".join(f"{cs.get(c, ''):>9}" for c in cols))
    log("  first-divergence residual histogram (model - silicon): "
        + " ".join(f"{k}:{v}" for k, v in card["histogram"].items()))


KNOBS = ("parity", "waits", "k", "marker", "family", "n", "variant")


def _knob_value(r: Run, knob: str):
    if knob == "n":
        # (WP26) the lead-in NOP count (F11, F12, F19, F20 R) or the drainer count (F6, F20 N)
        kn = r.chain.knobs
        return kn.get("n", kn.get("drain"))
    return getattr(r, knob)


def knob_dependence(cfg: Config, params, ids, span=3, log=say) -> dict:
    """Per integer: the best value within each knob group; differing bests are findings."""
    findings = {}
    for p in params:
        v0 = getp(cfg, p)
        values = [v for v in range(v0 - span, v0 + span + 1) if v >= 0]
        res = evaluate([setp(cfg, **{p: v}) for v in values], ids)
        per = {}
        for knob in KNOBS[:6]:
            groups = defaultdict(list)
            for k, i in enumerate(ids):
                v = _knob_value(_DATA[i], knob)
                if v is not None or knob != "n":
                    groups[v].append(k)
            if len(groups) < 2:
                continue
            best = {}
            for g, ks in groups.items():
                m = 3 if RANK_MATCHED else 0    # stage 8: events matched, not exact runs
                counts = [sum(res[j][k][m] for k in ks) for j in range(len(values))]
                top = max(counts)
                if top == 0:
                    continue
                cands = [values[j] for j, c in enumerate(counts) if c == top]
                best[str(g)] = (min(cands, key=lambda v: abs(v - v0)), top, len(ks))
            vals = {b[0] for b in best.values()}
            if len(vals) > 1:
                per[knob] = best
        if per:
            findings[p] = per
            for knob, best in per.items():
                log(f"  knob-dependence: {p} (fitted {v0}) best by {knob}: "
                    + ", ".join(f"{g}={b[0]} ({b[1]}/{b[2]})" for g, b in sorted(best.items())))
    if not findings:
        log("  knob-dependence: no integer's best value differs by parity/waits/k/marker/family/n")
    return findings


def summarize_survivors(base: Config, survivors: list[Config]) -> dict:
    """Option -> sorted values seen among survivors (options all survivors share are pinned)."""
    seen = defaultdict(set)
    for c in survivors:
        for name in OPTIONS:
            seen[name].add(json.dumps(getattr(c, name)))
    return {n: [json.loads(v) for v in sorted(vals)] if len(vals) > 1
            else json.loads(next(iter(vals))) for n, vals in seen.items()}


def save(stage: int, payload: dict):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"stage{stage}.json"
    path.write_text(json.dumps(payload, indent=1, default=str))
    return path


# Stages ------------------------------------------------------------------------------

QUEUE_OPTIONS = {
    "room_ir": OPTIONS["room_ir"],
    "arrive_partial": OPTIONS["arrive_partial"],
    "request_eval": OPTIONS["request_eval"],
    "request_hold": OPTIONS["request_hold"],
    "release": OPTIONS["release"],
    "take_commit": OPTIONS["take_commit"],
    "opcode_take": OPTIONS["opcode_take"],
    "opcode_overlap": OPTIONS["opcode_overlap"],
    "bytes_per_clock": OPTIONS["bytes_per_clock"],
    "start_sync": OPTIONS["start_sync"],
    "take_sync": OPTIONS["take_sync"],
    "data_ready": OPTIONS["data_ready"],
    "min_gap": OPTIONS["min_gap"],
}

# Stage 2: the integers F0 pins (NOP, MOV r,imm, the long shift, OUT DW,AL of END).
F0_INTS = ["reg.exec", "imm.pre", "imm.exec", "shift_cl.exec", "out.exec", "out.setup",
           "out.setup_free"]

# Stage 3: the marker classes (push, store, out) and the F2 bodies' classes
# (reg, imm, prefix), the shift anchor of LS, and the hand-off enums.
MARKER_INTS = ["push.setup", "push.setup_free", "push.post", "store.pre", "store.setup",
               "store.post", "out.pre", "out.pre0", "out.exec", "out.setup", "out.lead",
               "out.relatch", "io_recover", "wlatch",
               "out.nx", "out.wb", "reg.pre", "reg.pre0", "reg.exec", "reg.nx", "imm.pre",
               "imm.exec", "imm.nx", "imm.wb", "prefix.exec", "shift_cl.exec", "shift_cl.wb",
               "hold_q"]
MARKER_ENUMS = {
    # hold_fetch True/False and write_wait=issue lose on F1 at every survivor
    # (first stage-3 runs); write_wait end/mem_end and post_on_take tied or were
    # unanimous in every queue-rework run and are seeded (STAGE3_SEED);
    # hold_fetch=mem_le_q, data_while_fetch=queue and arbiter=data_wins never
    # won a queue-rework stage 3 and are left to stage 6. The rest is enumerated.
    "hold_fetch": ("le_q", "le_q_io"),
    "data_while_fetch": ("wait", "wait_before"),
    "arbiter": ("settled", "b2b"),
    "hold_run": OPTIONS["hold_run"],
    # Stage 2 pins take_sync only with the F0-pinned costs; with the marker
    # integers free it is open again (the F0 guard still has to stay exact).
    "take_sync": ("operand", "pending", "pending_end"),
    "out.wbsync": (0, 1),
    # (WP13, F11) the queue's read port on a fetch's late clocks: no double read (an
    # instruction's last operand byte and the next opcode's IR load) past a fetch's T2
    "late_read": OPTIONS["late_read"],
}

# Starting point of stage 3 (the enums above are enumerated around it, the
# integers descend from it). Read off F1/F2 by hand (WP5):
# - PUSH: write issuable 7 setup clocks after its start, the last 3 fetch-free;
#   the EU continues after a memory write's last clock (write_wait=mem_end).
# - OUT: port taken 3 clocks after the start; the I/O request is posted on the
#   take clock and issuable after 6 fetch-free clocks; the next opcode loads 5
#   clocks after the port take; the EU continues on the I/O's issue clock.
#   OUT reads its register operand after the previous instruction's write-back
#   (out.wbsync), which runs 2 clocks past the long shift, 1 past MOV r,imm16.
# - a posted memory request holds fetches while > 3 bytes are queued; an I/O
#   request never does (hold_fetch=mem_le_q); a fetch raised on the clock a
#   request becomes issuable goes first (arbiter=settled).
# - NOP/XCH (no ModR/M) run 4 clocks (reg.pre0); MOV AW,DW etc. run their
#   ModR/M take and then wait for the fetch it triggers (reg.exec 0).
# - after an operand take the EU waits for the fetches pending on the take
#   clock, in flight or requested (take_sync=pending).
# - (fourth fit) on a clock the EU starts, takes an operand byte and the IR
#   loads, a request with room for one word is an aborted 3-clock cycle the
#   take sync waits for, raised again when the next bus cycle ends
#   (abort_fetch=retry; F5 st_bw k2 even: W87 W95 F98, no fetch at 90).
#   Stage 6 enumerates it again under the guard of every family.
# - (fifth fit, the I/O mechanism, read off F1/F2/F4/F5/F7 OUT strips by hand)
#   OUT/IN: the request is posted when the port is latched (port take 3 clocks
#   after the start; DW forms 1 clock after it) and counts its setup from the
#   start on every clock with no memory wait state (io_post=start,
#   io_count=nowait): the I/O issues 7 clocks after the latch (setup 8) plus one
#   per wait state of a fetch meanwhile; its last 2 (lead) the bus unit has
#   committed to it (a fetch no younger than the I/O may run on the lead's
#   first clock, io_hold=posted_b2b). An OUT goes on 2 clocks after the port take
#   (exec 2, port_sync=none, io_release=post); a port byte taken while an I/O
#   waits holds it until 3 clocks after the take and re-latches after it
#   (port_latch=relatch, relatch 3); register-only instructions wait for the
#   issue (io_interlock=reg_pfx); memory data waits 2 clocks after an I/O cycle
#   (io_recover 2). IN waits for its data, then 4 clocks (in.post).
#   An OUT waits for the previous instruction's register write-back (out.wbsync),
#   which runs from that instruction's end (wb_from=end): 2 clocks after a shift.
#   (WP45, the thirty-third fit) the setup counts from the post instead
#   (io_post=take; seeded start until the thirty-second fit): the two differ only
#   where the pre's countable clocks are not out.pre/in.pre (a memory wait state
#   in it), F13-c-out-shlcl8-pO-w1 and F13-u-out-mulu-k1-pO-w1: the marker OUT's
#   pre holds the wait state of the fetch the refresh 144-148 pushed onto its
#   start; silicon I164 at the end of the refresh 159-163 (start: I165).
# - (sixth fit, the data latch, read off F4-F7 0-wait strips by hand) a datum stays in
#   the bus unit's data latch for 4 clocks (wlatch): a memory write from its issue, read
#   data (memory or I/O) from its delivery, a register form's immediate from the take of
#   its last byte. An IN/OUT with a port byte does not start while it is busy and holds
#   every fetch meanwhile (wlatch_cls=port, wlatch_hold); the DW forms start at once.
#   This replaces the load/IN write-backs (load.wb, load_alu.wb, pop.wb, in.wb now 0):
#   F5 store -> OUT at 0 waits starts the OUT at W+4, F7 load -> OUT at R data+4,
#   F6 MOV AW,imm16 -> IN/OUT at take+4. IN ends 2 clocks after its data (in.post 2).
STAGE3_SEED = {"take_sync": "pending", "abort_fetch": "retry",
               "write_wait": "mem_end", "hold_fetch": "le_q", "hold_q": 3,
               "arbiter": "settled", "post_on_take": True, "data_while_fetch": "wait_before",
               "push.post": 0, "push.setup": 7, "push.setup_free": 3,
               "io_release": "post", "io_post": "take", "io_count": "nowait",
               "port_latch": "relatch", "port_sync": "none", "io_hold": "posted_b2b",
               "io_interlock": "reg_pfx", "io_recover": 2, "wb_from": "end",
               "out.pre": 3, "out.pre0": 1, "out.exec": 2, "out.setup": 8, "out.lead": 2,
               "out.relatch": 3, "out.nx": 1, "out.wbsync": 1,
               "in.pre": 3, "in.pre0": 0, "in.setup": 8, "in.lead": 0, "in.post": 2,
               "in.relatch": 3,
               "wlatch": 4, "wlatch_cls": "port", "wlatch_hold": True,
               "wlatch_src": "write_imm_read", "wlatch_imm": "reg",
               "shift_cl.wb": 2, "imm.wb": 0, "reg.exec": 0, "reg.pre0": 4,
               "store.post": 0,
               # (WP16, F12, read off by hand) series A: a register-only form's last operand
               # byte enters the data latch (the OUT after MOV AW,DW starts at take+4); only
               # a ModR/M form waits out a back-to-back fetch at its start; SHL AW,1 runs a
               # clock less than SHL AW,4's exec (exec0 5), whose count byte comes 2 clocks
               # after its ModR/M (shift_count=late, cpre 2); a DW OUT does not wait for the
               # long shift's write-back (wbsync0 0). Series B: the latched byte counts
               # while the decoder is mid-take; an immediate completed on a word's delivery
               # clock syncs on the next clock's pending fetches. The overfill: an IR that
               # cannot load before the word lands is no room (room_ir_ready), and the
               # eighth fit's shift_imm.nx 10, which only that phantom room supported, is 0.
               "wlatch_imm": "reg_last", "start_sync": "b2b_modrm", "room_ir_ready": True,
               "latch_midtake": True, "imm_landed": True, "shift_count": "late",
               "shift_imm.exec0": 5, "shift_imm.cpre": 2, "shift_imm.nx": 0,
               "out.wbsync0": 0,
               # (WP19, F14 O) seeded here as the ninth fit's stage-6 rules are
               "wlatch_ir": True, "wlatch_mul": "none", "io_ir_hold": True,
               # (WP21, F16 S, read off by hand) a C1 shift taking an operand byte on a word's
               # delivery clock with its second byte latched and no other room holds every
               # fetch until its last clock; a count byte taken so reaches the counter late
               "count_latch": True}
REG_INTS = ["reg.pre", "reg.pre0", "reg.exec", "reg.nx", "reg.wb", "imm.pre", "imm.exec", "imm.nx",
            "imm.wb", "prefix.exec", "prefix.nx", "shift_imm.pre", "shift_imm.exec",
            "shift_imm.exec0", "shift_imm.cpre",
            "shift_imm.nx", "shift_imm.wb", "shift_cl.pre", "shift_cl.exec", "shift_cl.loop",
            "shift_cl.nx", "per_shift_count", "mul.pre", "mul.exec", "mul.nx", "mul.wb",
            "div.exec",
            # (WP22) the register divide's write-back, the unit forms' hold phase (unit_hold)
            "div.wb", "shift_imm.hphase", "shift_cl.hphase", "mul.hphase", "div.hphase"]
GROUP_CLASSES = ("load_alu", "store_imm", "rmw", "rmw_imm", "mul", "push_mem", "pop_mem",
                 "div")
MEM_INTS = (["load.pre", "load.pre0", "load.exec", "load_alu.pre", "load_alu.exec",
             "load_alu.rsetup", "store.pre", "store.pre0", "store.setup", "store.post",
             "store_imm.pre", "store_imm.setup", "store_imm.post", "rmw.pre", "rmw.alu",
             "rmw.setup", "rmw.post", "rmw_imm.pre", "rmw_imm.alu", "rmw_imm.rsetup",
             "rmw_imm.setup", "rmw_imm.post",
             "push_mem.pre", "push_mem.exec", "push_mem.setup", "push_mem.post",
             "pop_mem.pre", "pop_mem.exec", "pop_mem.setup", "pop_mem.post",
             "pop.setup", "pop.exec", "in.pre", "in.pre0", "in.exec", "in.setup", "in.post",
             "in.lead", "in.relatch", "in.nx", "in.setup0", "out.setup0", "out.pre0",
             "load.wb", "load_alu.wb", "store.wb", "store_imm.wb", "rmw.wb", "rmw_imm.wb",
             "push_mem.wb", "pop_mem.wb", "pop.wb", "push.wb",
             # (WP19) the routing clocks (dest_route), the CL count's clocks (shift_cl_mem),
             # the memory multiply's and divide's exec and write-back
             "load_alu.dclk", "rmw.dclk", "rmw.grpcl", "mul.mexec", "mul.mwb", "div.pre",
             "div.mexec", "div.mwb",
             # (WP20) POP r/m's stack read, TEST imm's and the direct TEST's lookup, the
             # one-byte immediate's group setup
             "pop_mem.rsetup", "pop_mem.rfree", "load_alu.fgrp", "load_alu.fgrp_free",
             "load_alu.fdisp", "rmw_imm.grp1",
             # (WP21) the signed and byte multiply/divide exec, the multiplier's loop exit
             "mul.smexec", "mul.bmexec", "div.smexec", "mul.mtail", "div.mtail",
             # (WP25) the immediate forms' count from the start, the C6 imm8 group setup
             "store_imm.istart", "rmw_imm.istart", "store_imm.grp1",
             # (WP27) the immediate store's clock after its displacement; (WP43) the
             # immediate RMW's
             "store_imm.dadd", "rmw_imm.dadd",
             # (WP31) the idle left-out write slot's clocks (slot_idle=eu)
             "rmw_imm.sidle", "rmw.sidle",
             # (WP28) disp_floor: the first data cycle's distance from the displacement's take
             "load.dfloor", "load_alu.dfloor", "store.dfloor", "store_imm.dfloor",
             "rmw.dfloor", "rmw_imm.dfloor", "push_mem.dfloor", "pop_mem.dfloor"]
            + [f"{c}.grp" for c in GROUP_CLASSES] + [f"{c}.grp_free" for c in GROUP_CLASSES]
            + [f"{c}.setup_free" for c in ("store", "store_imm", "rmw", "rmw_imm", "push_mem",
                                           "pop_mem", "pop", "in")]
            + [f"ea.{m}" for m in ("base", "base_index", "disp", "base_disp",
                                   "base_index_disp", "direct",
                                   # (WP27) ea_disp16=own: base+index with a d16
                                   "base_index_disp16")])
# The memory templates' step order (templates.py): where the ModR/M byte, the EA
# clocks, the displacement and the immediate sit, where a group opcode's decode
# clocks go, and which data step is posted on its take clock.
MEM_ENUMS = {"odd_split": OPTIONS["odd_split"], "read_use_latency": OPTIONS["read_use_latency"],
             "rmw_write_issue": OPTIONS["rmw_write_issue"], "mem_order": OPTIONS["mem_order"],
             "imm_order": OPTIONS["imm_order"], "grp_mode": OPTIONS["grp_mode"],
             "rmw_shift": OPTIONS["rmw_shift"],
             "post_on_take": (True, "write", "nomodrm"),
             # (seventh fit) a non-writing group form (CMP [BW],imm16) and the immediate
             # RMW's write issue
             "grp_read": OPTIONS["grp_read"], "rmw_imm_issue": OPTIONS["rmw_imm_issue"]}
# A second stage-5 grid (seventh fit), enumerated around the first one's result and
# descended again: the head of an immediate form with a displacement, what its address
# bytes' take sync waits for, which queued bytes a posted request's fetch hold counts,
# and how a DW form's I/O counts its first clock. Kept out of MEM_ENUMS (whose product
# it would multiply by 24).
IMM_REVISIT = {"imm_head": OPTIONS["imm_head"], "sync_req": OPTIONS["sync_req"],
               "hold_count": OPTIONS["hold_count"], "dw_count": OPTIONS["dw_count"]}
# (WP18) Stage 5's enum sweep: every memory-template enum and immediate-form enum, the
# HALT status (with the DW setups among the integers descended inside it) and the group
# free clocks' bus rule, each alternative tried with the memory integers re-descended.
# (WP19, F14 T and G) the format properties of the memory forms: which forms take the group
# setup, the result routing of the direction bit and XCH, the CL count of a memory shift;
# a third stage-5 grid (30 structures) after IMM_REVISIT.
FORM_REVISIT = {"grp_ops": OPTIONS["grp_ops"], "dest_route": OPTIONS["dest_route"],
                "shift_cl_mem": OPTIONS["shift_cl_mem"]}
# (WP20, F15 A and P) the stack-first POP r/m and its read's hold, PUSH r/m's stack write on
# the data, TEST imm's two decodes, the direct TEST's lookup on the decoder, the one-byte
# immediate's group setup: a fourth stage-5 grid (192 structures) before FORM_REVISIT's.
F15_REVISIT = {n: OPTIONS[n] for n in ("pop_mem_order", "pop_read_hold", "push_mem_write",
                                       "grp_fixed", "fixed_lookup", "imm8_grp")}
# (WP21, F16 R and P) a unit form started on an aborted fetch cycle, a fetch run into a
# posted request's fetch-free setup clocks: a fifth stage-5 grid (20 structures) after
# F15_REVISIT's.
# (WP22, F15 P and F16 P) a request that moved into the slot behind an I/O lets a held fetch
# run in its fetch-free clocks; POP r/m's one-byte displacement taken where a two-byte one
# ends: in the same grid (80 structures).
F16_REVISIT = {n: OPTIONS[n] for n in ("abort_unit", "free_run", "slot_fetch", "disp_take",
                                       # (WP25, F19 I) the immediate forms' count from their
                                       # start: in the same grid (160 structures)
                                       "imm_count")}
# (WP27, F21) the effective-address path: a d16 taken in one clock, base+index+d16's own EA
# integer, the ModR/M direct address as a d16: a sixth stage-5 grid (8 structures) after
# F16_REVISIT's, and in the sweep.
EA_REVISIT = {n: OPTIONS[n] for n in ("disp16", "ea_disp16", "ea_direct")}
# (WP28, F21 re-read) the displacement's take against the IR load, the late take, the
# data cycle's floor after the take and the latched byte on the take's delivery clock: a
# sixth stage-5 grid (16 structures) after EA_REVISIT's, and in the sweep
DISP_REVISIT = {n: OPTIONS[n] for n in ("ir_load", "late_disp", "disp_floor", "latch_disp")}
# (WP29, item 10 a-c re-read) the delivery-clock fetch held at a request's free clocks' eve,
# the idle clock after a run fetch there, the start that waits out an older fetch at a
# shallow queue, the mod 00 form's floor: a seventh stage-5 grid (24 structures) after
# DISP_REVISIT's, and in the sweep (disp_floor's posted option is in DISP_REVISIT)
FREE_REVISIT = {n: OPTIONS[n] for n in ("free_hold", "free_idle", "io_older", "ea_floor")}
# (WP30, item 10 a-c re-read) a displacement taken on an I/O issue clock holding the bus unit
# a clock, the IR no room inside a displaced form's EA clocks, an RMW's ALU clocks counting
# through a fetch, the immediate form waiting out the fetch its start raises: an eighth
# stage-5 grid (16 structures) after FREE_REVISIT's, and in the sweep
WP30_REVISIT = {n: OPTIONS[n] for n in ("disp_io", "ea_ir_room", "rmw_alu", "imm_start")}
# (WP31, the left-out-write forms and the TEST/CMP reg forms) the left-out write's slot (its
# fetch at a word's room, no bus cycle without one, the data latch), TEST's setup clock on an
# aborted start, TEST imm's floor carrying the fixed lookup, TEST [dir]'s lookup after a start
# fetch, and CMP r/m,reg as the RMW with its write left out (dest_route, also in
# FORM_REVISIT): a ninth stage-5 grid (320 structures) after WP30_REVISIT's, and in the sweep
WP31_REVISIT = {n: OPTIONS[n] for n in ("slot_room", "slot_idle", "slot_latch", "abort_fixed",
                                        "fixed_floor", "lookup_start", "dest_route")}
# (WP32, the leads before a register form, OUT after OUT, MOV CL and SHL AW,CL behind a full
# queue) a register form's IR load a clock late after a take on an I/O issue clock (with
# reg.nx 1), the ModR/M commit leaving the port to an older latched byte, a NOP start holding
# the reissued request to the next start, the port byte taken on a fetch's issue clock landing
# late, a start on the latched byte's entry clock running its clocks a clock late, the abort
# test not counting a latched byte: the stage-4 grid (288 structures; F3 is scored there) and
# a stage-6 grid after F20_REVISIT's (F20 and F19 D are scored there), and in both sweeps
WP32_REVISIT = {**{n: OPTIONS[n] for n in ("io_take_nx", "modrm_port", "nop_hold", "port_issue",
                                           "latch_start", "abort_latched")},
                "reg.nx": (1, 2)}
# (WP33, TEST [0C00h] under OUT pO and the second base+index+d16 store) a group clock waiting
# out an I/O recovery holding a younger fetch, no back-to-back fetch inside a displaced form's
# EA clocks, the idle clock after a back-to-back fetch at a request's free clocks' eve: a
# tenth stage-5 grid (8 structures) after WP31_REVISIT's, and in the sweep; the register
# multiply's end after an aborted start (F16 L is scored in stage 6): a stage-6 grid after
# WP32_REVISIT's (2 structures)
WP33_REVISIT = {n: OPTIONS[n] for n in ("grp_io_hold", "ea_b2b", "free_idle_b2b")}
WP33_STAGE6 = {"abort_reg_end": OPTIONS["abort_reg_end"]}
# (WP43, F22: the immediate forms' post against the fetch run) TEST r/m,imm16's fixed lookup in
# the decoder before its displacement, the one-byte immediate's request on a non-run delivery
# clock: an eleventh stage-5 grid (4 structures) after WP33_REVISIT's, and in the sweep
WP43_REVISIT = {n: OPTIONS[n] for n in ("fixed_lookup_grp", "imm1_first")}
STAGE5_SWEEP = {**MEM_ENUMS, **IMM_REVISIT, **FORM_REVISIT, **F15_REVISIT, **F16_REVISIT,
                **EA_REVISIT, **DISP_REVISIT, **FREE_REVISIT, **WP30_REVISIT, **WP31_REVISIT,
                **WP33_REVISIT, **WP43_REVISIT,
                "halt_status": OPTIONS["halt_status"],
                "grp_free_bus": OPTIONS["grp_free_bus"]}
# Starting integers of stage 5 for the new step orders, read off the F4/F5 strips
# by hand (fourth fit): a form without a ModR/M byte (A1/A3) takes its address
# bytes 2 clocks after its start (pre0 2: ld_acc_dir odd F84 R87); a ModR/M form
# takes its ModR/M byte at once (pre 0); base+index+disp16 takes its displacement
# 2 clocks later than base+disp16 (F85 against F84: ea 2 before the displacement);
# a group opcode's memory request comes 3 clocks after a plain one's (INC [BW] odd
# R89 against ADD [BW],AW R86), as 4 setup clocks of which the last 3 fetch-free
# (INC [BW] even: 3 clocks after the second fetch ends, at every wait setting).
# (seventh fit, read off the F5 DW strips) a DW form's I/O issues 6 clocks after its
# start, 7 when a bus cycle starts on the clock its request starts counting
# (dw_count=bus: IN AL,DW after PUSH, odd, 0 waits: I/O at s+6; even, fetch at s: s+7);
# the END block's OUT DW,AW is one clock later (setup0 8, pre0 0; see the doc).
STAGE5_SEED = {"grp_free_bus": True, "store.pre": 0, "store.pre0": 2, "load.pre0": 2,
               "dw_count": "bus", "in.setup0": 7, "out.pre0": 0,
               "ea.direct": 0,
               "ea.base_disp": 0, "ea.base_index_disp": 2,
               **{f"{c}.grp": 4 for c in GROUP_CLASSES},
               **{f"{c}.grp_free": 3 for c in GROUP_CLASSES},
               # (seventh fit) the immediate forms' first data cycle comes 4 clocks after
               # the ModR/M take's sync, during a fetch as well (PUSH; CMP/ADD/MOV [BW],imm16
               # at every parity and wait: R/W at s+7 at 0 waits, back to back with the
               # fetch at 1-2): 3 grp setup clocks, 1 of them fetch-free; ADD's write 3
               # clocks after its read data, counted during a fetch (alu 3, setup_free 0)
               "rmw_imm.grp": 3, "rmw_imm.grp_free": 1, "store_imm.grp": 3,
               "store_imm.grp_free": 1, "rmw_imm.alu": 3, "rmw_imm.setup_free": 0,
               # (WP13, F10) a DW OUT's I/O issues at s+7 as IN AL,DW does (MOV DW,imm16 ;
               # OUT DW,AL then MOV CL: I/O at s+7 whatever register the instruction before
               # writes and whatever the port); the END block's s+8 is the HALT after it
               # taking the bus unit for its start clock (halt_status, revisited in stage 6)
               "out.setup0": 7, "halt_status": True,
               # (WP19, F14 T and G, read off by hand) TEST [BW],AW reads at the group
               # forms' clock (grp_ops=fixed, load_alu 4/3 as above); CMP r/m,reg runs 2
               # clocks after its read and XCH 2 before its write (dest_route, dclk 2); SHL
               # [BW],CL reads 3 fetch-free clocks after SHL [BW],1 (grpcl 3); MULU [BW]
               # ends 29 after its read data with a 2-clock write-back an OUT waits for,
               # DIVU [BW] 37 (5678h:0000h / 9090h)
               "grp_ops": "fixed", "dest_route": "d0ro_latch", "shift_cl_mem": "count",
               "load_alu.dclk": 2, "rmw.dclk": 2, "rmw.grpcl": 3, "mul.mexec": 29,
               "mul.mwb": 2, "div.pre": 0, "div.mexec": 37, "div.mwb": 2,
               # (WP19, F14 O) the stage-6 latch and request rules, seeded here as
               # halt_status is so that the integer descents of stage 5 see them
               "wlatch_ir": True, "wlatch_mul": "none", "io_ir_hold": True,
               # (WP20, F15 A and P, read off by hand) POP r/m reads the stack first, on POP
               # AW's clock (rsetup 7, 3 fetch-free), its memory write posted on the data
               # (setup 4, the EA inside), its displacement 2 clocks after the data (pre 2),
               # no group clocks; PUSH r/m's stack write posted on its data; TEST [BW],imm16
               # reads 2 fetch-free clocks after TEST [BW],AW (fgrp 2/2); the direct TEST's
               # lookup is 5 non-wait clocks on the decoder before the displacement, in
               # place of the group setup (fdisp 5); AND/ADD [BW],imm8 read 1 before the imm16 forms
               # (grp1 2)
               "pop_mem_order": "stack_post", "push_mem_write": "at_data",
               "grp_fixed": "test", "fixed_lookup": "decoder_nowait", "imm8_grp": "own",
               "pop_mem.rsetup": 7, "pop_mem.rfree": 3, "pop_mem.setup": 4, "pop_mem.pre": 2,
               "pop_mem.grp": 0, "load_alu.fgrp": 2, "load_alu.fgrp_free": 2,
               "load_alu.fdisp": 5, "rmw_imm.grp1": 2,
               # (WP20, F15 O) the stage-6 take sync and start rule on an OUT's issue
               # clock, seeded here as the WP19 ones are; MOV AW,DW then a memory form or
               # NOP after the OUT, and the prefixed forms, need them; reg.nx 2 with them
               # (WP32: 1, with io_take_nx's clock after a take on an I/O issue clock)
               "sync_io": "latch", "io_busy_start": "issue", "reg.nx": 1,
               # (WP21, F16 R and P, read off by hand) a shift, multiply, divide or PUSH r/m
               # started on an aborted fetch cycle reads a clock early, a multiply/divide
               # ending where it would have and raising the dropped request 3 clocks before
               # its end; a fetch requested on its delivery clock runs into a posted read's
               # fetch-free setup clocks; MUL/DIV [BW] 20/21 longer than MULU/DIVU [BW], MULU
               # byte 8 shorter, DIVU IX 8 longer than MULU AW
               "abort_unit": "loop", "free_run": "run", "mul.mtail": 3, "div.mtail": 3,
               "mul.smexec": 49, "mul.bmexec": 21, "div.smexec": 58, "div.exec": 39,
               # (WP21, F16 L) the stage-6 exec rule after an OUT's issue clock, seeded here
               # as the WP20 ones are
               "io_exec": "after_io",
               # (WP22, read off by hand on F3/F5/F12/F14/F15/F16) the OUT frame's remainder:
               # the register divide among the register-only forms; a request raised under
               # an I/O issue clock on a latched delivery dropped to the unit's loop exit; a
               # one-iteration loop's re-raise on its first clock; the register units held
               # by a fetch past its second clock at their micro-boundaries (phase 1 for the
               # D0/D1/C0/C1 shifts, 2 for the rest); a register shift or multiply started
               # on an aborted cycle a clock early; the register multiply's take sync not
               # counting a request raised under the I/O, its write-back 2; a request moved
               # into the slot behind an I/O letting a held fetch run in its free clocks;
               # POP r/m's one-byte displacement taken where a two-byte one's last byte is,
               # its memory write counting through the fetch that raises (setup_free 1);
               # mtail counted from the unmoved end (2, the old 3)
               "reg_div": True, "io_take": "unit", "retry_first": True, "unit_hold": True,
               "abort_reg": True, "sync_io": "unit", "slot_fetch": "slot",
               "disp_take": "end", "pop_mem.setup_free": 1,
               "shift_imm.hphase": 1, "shift_cl.hphase": 2, "mul.hphase": 2,
               "div.hphase": 2, "mul.wb": 2, "div.wb": 2, "mul.mtail": 2, "div.mtail": 2,
               # (WP25, F19, read off by hand) an immediate memory form's first data cycle
               # comes 5 + (its immediate bytes) clocks after its start whatever runs on the
               # bus meanwhile (C7/81 s+7, C6/83 s+6; istart 5); C6 /0 takes the one-byte
               # immediate's group setup as 83 does (grp1 2); a DW form queued behind an I/O
               # holds the next port form's start and lets a fetch run on its lead's first
               # clock only with nothing posted behind it or 3 bytes queued (stage 6's enums,
               # seeded here as the WP19-WP22 ones are)
               "imm_count": "start", "store_imm.istart": 5, "rmw_imm.istart": 5,
               "store_imm.grp1": 2, "dw_port": "hold", "dw_slot": "behind",
               # (WP32, read off by hand on F20/F19 D/F7/F3/F16 S) a register form's IR load
               # a clock late after a take on an I/O issue clock, with reg.nx 1; the ModR/M
               # commit leaving the port to an older latched byte; a NOP start holding the
               # reissued request to the next start; a port byte taken on a fetch's issue
               # clock landing late; a start on a latched byte's entry clock running its
               # clocks a clock late; the abort test not counting a latched byte (stage 4's
               # and 6's enums, seeded here as the WP19-WP25 ones are)
               "io_take_nx": True, "modrm_port": True, "nop_hold": "any",
               "port_issue": True, "latch_start": True, "abort_latched": "any"}
# The storage structure stage 2's grid is built on (sixth fit). Stage 2 enumerates the
# request rule and the EU/bus syncs (QUEUE_OPTIONS) on F0; the queue's storage (the
# byte-wide write port and its latch, the ModR/M latch, the aborted fetch) is not in that
# grid: F0 alone cannot choose it (every storage alternative has F0 survivors) and the
# product of the two grids is out of reach. It was found by F9 in the third fit and is a
# seed here, revisited in stage 6 under the guard of every family (STORAGE_REVISIT).
STAGE2_SEED = {"word_latch": "byte_d", "latch_read": "commit", "latch_hold": True,
               "modrm_commit": "byte", "abort_fetch": "retry", "request_sample": "after_take",
               "ir_port": False}

# Seeds are optional data: build/validation/v35s/chains/fit/seeds/stageN.json. A stage with
# a seed file starts from its values; a stage without one starts from the previous stage's
# output (or Config() defaults), so with seeds/ absent the pipeline runs from scratch and
# no hand value enters the search. The hand read-offs above are kept as data only:
# `fit --write-seeds` writes them out as the seed files. Every stageN.json records the seed
# file (or None) and the values it used.
SEED_DEFAULTS = {2: STAGE2_SEED, 3: STAGE3_SEED, 5: STAGE5_SEED}


def seeds_dir() -> Path:
    return OUT_DIR / "seeds"


def write_seeds() -> list[Path]:
    """Write the hand read-offs (SEED_DEFAULTS, REFRESH_SEED) as seed files (opt-in)."""
    out = []
    for stage, values in {**SEED_DEFAULTS, 8: REFRESH_SEED}.items():
        path = seeds_dir() / f"stage{stage}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values, indent=1, sort_keys=True))
        out.append(path)
    return out


def load_seed(stage: int) -> tuple[dict, dict]:
    """(values, record) of a stage's seed file; no file means no seed ({})."""
    path = seeds_dir() / f"stage{stage}.json"
    if not path.exists():
        return {}, {"file": None, "values": {}}
    values = json.loads(path.read_text())
    return values, {"file": str(path), "values": values}


ARB_ENUMS = {"arbiter": OPTIONS["arbiter"], "arbiter_q": (2, 3, 4), "hold_run": OPTIONS["hold_run"],
             "data_while_fetch": OPTIONS["data_while_fetch"], "hold_fetch": OPTIONS["hold_fetch"],
             "hold_q": (2, 3, 4)}

QUEUE_REVISIT = {"room_ir": OPTIONS["room_ir"], "arrive_partial": OPTIONS["arrive_partial"],
                 "request_eval": OPTIONS["request_eval"],
                 "request_hold": OPTIONS["request_hold"], "start_sync": OPTIONS["start_sync"],
                 "take_sync": OPTIONS["take_sync"]}
# (WP26, F20) the request after a fetch's issue, the ModR/M word's slot, the shallow-queue
# start hold and its integer, and the DW form's count and port relatch, revisited on the
# stage-6 families with F20 among them
F20_REVISIT = {"request_reissue": OPTIONS["request_reissue"], "modrm_mate": OPTIONS["modrm_mate"],
               "io_b2b": OPTIONS["io_b2b"], "io_b2b_q": (2, 3, 4),
               "dw_count_b2b": OPTIONS["dw_count_b2b"], "port_landed": OPTIONS["port_landed"]}
# The storage alternatives of the F9 round (sim/queue.py): the bus-side word latch and
# what holds its write port, the IR as room, the ModR/M latch, the request's sample
# point and the single read port. Revisited in stage 6 under the guard of every family.
# The I/O mechanism (fifth fit, sim/config.py): where an I/O request is posted and how
# its setup counts, what it holds, what a port byte taken while it waits does, and
# what may run meanwhile. Revisited in stage 6 under the guard of every family.
# Two grids in turn (32 and 36 structures) rather than their product (2304).
IO_REVISIT = {"io_release": OPTIONS["io_release"], "io_post": OPTIONS["io_post"],
              "io_count": OPTIONS["io_count"], "port_latch": OPTIONS["port_latch"],
              "port_sync": OPTIONS["port_sync"]}
IO_FOLLOWER_REVISIT = {"io_hold": OPTIONS["io_hold"], "io_interlock": OPTIONS["io_interlock"],
                       "imm_latch": OPTIONS["imm_latch"], "wb_from": OPTIONS["wb_from"],
                       "halt_status": OPTIONS["halt_status"]}
# The data latch (sixth fit, sim/config.py): what occupies it, which I/O forms wait for
# it and what their wait holds; and whether a group form's free clocks need an idle bus.
# (WP19, F14 O) the OUT after a register form: an OUT in the IR waiting for a register
# form's latch, a register MULU and the latch, the IR load on an I/O cycle's issue clock
# (WP20, F15 O) the take sync on an I/O cycle's issue clock and the register forms' start
# during the I/O cycle
OUT_REVISIT = {"io_exec": OPTIONS["io_exec"],
               "wlatch_ir": OPTIONS["wlatch_ir"], "wlatch_mul": OPTIONS["wlatch_mul"],
               "io_ir_hold": OPTIONS["io_ir_hold"], "sync_io": OPTIONS["sync_io"],
               "io_busy_start": OPTIONS["io_busy_start"]}
# (WP22, F16 L, F3/F12/F14/F15 OUT frames) the request raised under an I/O issue clock on a
# latched delivery, the register units' hold by a fetch, their start on an aborted cycle, the
# register divide among the register-only forms, a one-iteration loop's re-raise: a second
# OUT grid (64 structures) after OUT_REVISIT (their product with it would be 15360)
OUT_REVISIT2 = {n: OPTIONS[n] for n in ("io_take", "unit_hold", "abort_reg", "reg_div",
                                        "retry_first",
                                        # (WP25, F19 D) the DW form behind a waiting I/O
                                        "dw_port", "dw_slot")}
LATCH_REVISIT = {"wlatch_cls": OPTIONS["wlatch_cls"], "wlatch_hold": OPTIONS["wlatch_hold"],
                 "wlatch_src": OPTIONS["wlatch_src"], "wlatch_imm": OPTIONS["wlatch_imm"],
                 "grp_free_bus": OPTIONS["grp_free_bus"]}
STORAGE_REVISIT = {"word_latch": OPTIONS["word_latch"], "latch_read": OPTIONS["latch_read"],
                   "latch_hold": OPTIONS["latch_hold"], "room_ir": OPTIONS["room_ir"],
                   "modrm_commit": OPTIONS["modrm_commit"],
                   "request_sample": OPTIONS["request_sample"],
                   "abort_fetch": OPTIONS["abort_fetch"]}

# Stage 3 chooses the queue/arbitration structure for everything after it, so it
# scores that choice on the register-only drains too (F3, F6), not only on the
# marker families; later stages guard every family an earlier stage scored.
# WP13: F11 (take phase, a queue/decoder rule) joins stage 3, which chooses the queue's
# read-port rule (late_read); F10 (the DW I/O forms after 14 predecessors) joins stage 6,
# where the I/O mechanism's enums, halt_status among them, are enumerated under the guard
# of every earlier family (its integers, the DW setups, are stage 5's and seeded there).
# WP16: F12 series B joins stage 3 (with F11: the queue's storage rules and the take sync),
# series A stage 6 (the I/O, data-latch and start-sync enums are enumerated there under the
# guard of every family; their WP16 values are seeded at stage 3 so that the integer stages
# 3-5 see them, as halt_status is seeded at stage 5).
STAGE_FAMILIES = {1: ["F0", "F0w"], 2: ["F0"],
                  3: ["F1", "F2", "F9", "F3", "F6", "F11", "F12B", "F16S"],
                  4: ["F3"], 5: ["F4", "F5", "F14T", "F14G", "F15A", "F15P", "F15K", "F16R",
                                 "F16P", "F19I", "F21", "F22"],
                  6: ["F6", "F10", "F12A", "F14O", "F15O", "F16L", "F19D", "F20"],
                  7: ["F7", "F8"],
                  8: ["F8", "F13", "F17", "F18"],
                  9: ["F25"],
                  10: ["F23"],
                  11: ["F27"],
                  12: ["F28", "F29"],
                  13: ["F24"],
                  14: ["F23", "F25"],
                  15: ["F30", "F31", "F24", "F23", "F25"],
                  16: ["F32", "F33"],
                  17: ["F32", "F33", "F34"],
                  18: ["F17", "F18"],
                  19: ["F27", "F28", "F8", "F13", "F17", "F18"],
                  20: ["F32", "F33", "F34"],
                  21: ["F35", "F36"],
                  22: ["F23", "F30", "F34", "F35"]}

# Stage 22 (WP89, F23, F30, F34, F35): the forty-fifth fit's refresh-off misses of a transfer not
# taken (scratchpad wp89/facts.txt) as two mechanisms beside the transfer's decide step: a short
# conditional's fetch ending there with a byte of room commits the bus unit to one more fetch back
# to back, the latch taking the other byte, and the test does not wait for it (xfer_nt_b2b); an
# aborted cycle answering a request since the transfer's start counts as a fetch for the decide
# step's gap (decide_abort). From a hand start (the previous fit), the enums (F48_ENUMS, the old
# value first, so a tie keeps it) as a grid at the input's integers (the top 2 descended over
# F48_INTS: every integer of the four transfer classes with a not-taken path), then the sweep
# over F48_ENUMS with F48_INTS descended inside every move; the families are those that run a
# not-taken transfer (F36 runs none); the corpus guard over every modelled run is the guard, as
# in stages 9 to 21.
F48_ENUMS = {n: OPTIONS[n] for n in ("xfer_nt_b2b", "decide_abort")}
F48_CLASSES = ("branch_short", "dbnz", "bcwz", "dbnz_z")
F48_INTS = ([f"{cls}.{name}" for cls in F48_CLASSES for name in DEFAULT_COST[cls]]
            + [f"{cls}.wb" for cls in F48_CLASSES if "wb" not in DEFAULT_COST[cls]])

# Stage 21 (WP88, F35, F36): the refresh-off coverage families read as facts (scratchpad
# wp88/facts.txt) and modelled: every form that costs what its class costs decodes to that class,
# the forms that do not to the new classes (F47_CLASSES: BCWZ, DBNZNE / DBNZE, RET imm16, CALL / BR
# through a register, the far transfers, LES / LDS, POP PSW, TEST r,r), each on an existing
# class's structure (templates.BASE_CLASS) with its own integers, and one new enum (F47_ENUMS:
# RET imm16's fetch hold over a half-taken word). From a hand start (the previous fit, the new
# classes' integers in DEFAULT_COST read off the facts and descended class by class on F35 and
# F36), the enum as a grid at the input's integers (both starts descended over F47_INTS: every
# integer of the new classes), then the sweep over F47_ENUMS with F47_INTS descended inside every
# move; no rule reads an earlier class (the transfer rules that name a class see the base class,
# which is the old class itself for every earlier form), so F23, F25 and F33 stay out; the corpus
# guard over every modelled run is the guard, as in stages 9 to 20.
F47_ENUMS = {n: OPTIONS[n] for n in ("ret_imm_hold",)}
F47_CLASSES = ("bcwz", "dbnz_z", "ret_imm", "ret_far", "ret_far_imm", "call_reg", "call_far",
               "br_reg", "branch_far", "load_ptr", "pop_psw", "test_reg")
F47_INTS = [f"{cls}.{name}" for cls in F47_CLASSES for name in DEFAULT_COST[cls]]

# Stage 20 (WP86, F32, F33, F34): the forty-third fit's misses of the 0F page and the probe family
# read as facts (scratchpad wp86/facts.txt); two of their shapes as mechanisms of the queue and the
# arbiter beside a 0F form: the register forms' back-to-back fetch on the last clock of the fetch
# running at their last take (page_b2b) and the memory forms' committed refill inside the read's
# fixed setup (page_run). From a hand start (the previous fit with the bit field INS crossing's
# xwsetup / xrsetup / xspan moved together, read off F34's crossing cells), the new enums
# (F46_ENUMS, the old value first, so a tie keeps it) as a grid at the input's integers (the top 2
# descended over F46_INTS: every integer of the 0F classes), then the sweep over F46_ENUMS with
# F46_INTS descended inside every move; no rule reads a transfer, so F23 and F30 stay out; the
# corpus guard over every modelled run is the guard, as in stages 9 to 19.
F46_ENUMS = {n: OPTIONS[n] for n in ("page_b2b", "page_run")}
F46_CLASSES = ("bit1", "rol4", "ror4", "bit1_test", "bit1_rmw", "bit1_clr", "rol4_mem", "ror4_mem",
               "bf_ext", "bf_ins", "mul_imm")
F46_INTS = [f"{cls}.{name}" for cls in F46_CLASSES for name in DEFAULT_COST[cls]]

# Stage 19 (WP85, F27, F28): the forty-third fit's refresh-on misses of the probe families as
# mechanisms of the I/O sequencer beside a refresh (scratchpad wp85/facts.txt): a port take on the
# clock the waiting I/O counts out, a port take on the clock after a refresh, the beaten fetch's
# pair beside an OUT posted on that fetch's issue clock, the I/O steps' restart and a step on the
# lead's last clock. From a hand start (the previous fit), the new enums (F45_ENUMS, the old value
# first, so a tie keeps it) as a grid at the input's integers (the top 2 descended over F45_INTS:
# the port forms' relatch and lead), then the sweep over F45_ENUMS with F45_INTS descended inside
# every move; F8, F13, F17 and F18 join F27 and F28 because every rule reads only refresh-on
# states; the corpus guard over every modelled run is the guard, as in stages 9 to 18.
F45_ENUMS = {n: OPTIONS[n] for n in ("port_ready_count", "port_refresh", "refresh_pair_post",
                                     "io_step_restart", "refresh_lead_step")}
F45_INTS = ["out.relatch", "out.lead", "in.relatch"]

# Stage 18 (WP84): a causal refresh. refresh_scope=live runs the refresh counter for every chain
# and keys the EU's refresh templates and rules on RFM.RFEN live (sim/config.py), where any (the
# old behaviour) runs them from clock 0 for a chain whose own RFM store turns refresh on later
# (types.refresh_any, a lookahead over the whole chain; the 1,416 runs of F17 S/D/W/C and F18
# B/BD/AC, scratchpad wp84/facts.txt). From a hand start (the previous fit with refresh_scope=live),
# the enum as a grid at the input's integers (both starts descended over F44_INTS: rfm_delay, the
# store's effect, which live's switch reads), then the sweep over F44_ENUMS with F44_INTS descended
# inside every move; the corpus guard over every modelled run is the guard, as in stages 9 to 17.
# The grid lists live first: on a tie over every family (the tie-break included) the stable sort
# keeps it, and the sweep takes an inert tie only on the tie-break, so a tie keeps the causal
# structure; sim.config.DEFAULT stays any.
F44_ENUMS = {"refresh_scope": ("live", "any")}
F44_INTS = ["rfm_delay"]

# Stage 17 (WP81, F34): the forty-second fit's miss shapes as mechanisms, from F34's readings
# (docs/v35s-chains.md Facts "Probes for the forty-second fit's miss shapes"). From a hand start
# (the previous fit with the new enums on and their integers read off the F34 tables), the new
# enums (F43_ENUMS: the not-taken short transfer's hold at an odd address, the RET's read behind
# a write-back, the page register form's second opcode byte, the 0F memory form's and the bit
# field's fixed fetch-free read setup, MUL imm memory's read after its immediate and its hold
# over a half-taken word, the port OUT's start under a write-back) as a grid at the input's
# integers (the top 2 descended over F43_INTS: the integers of the classes the readings name and
# the new ones), then the sweep over F43_ENUMS with F43_INTS descended inside every move; the
# corpus guard over every modelled run is the guard, as in stages 9 to 16.
F43_ENUMS = {n: OPTIONS[n] for n in ("xfer_nt", "stack_wb", "page_take", "page_mem",
                                     "bf_read", "mul_imm_read", "mul_imm_hold", "wb_fetch")}
F43_CLASSES = ("bit1", "bit1_test", "bit1_rmw", "bit1_clr", "rol4_mem", "ror4_mem", "bf_ext",
               "bf_ins", "mul_imm")
F43_INTS = ([f"{cls}.{name}" for cls in F43_CLASSES for name in DEFAULT_COST[cls]]
            + [f"{cls}.{name}" for cls in ("branch_short", "dbnz")
               for name in ("nexec", "nfgap", "nhold", "wb")]
            + ["ret.setup", "incdec.wb", "flag.wb"])

# Stage 16 (WP78, F32, F33): the 0F page and the register miscellany. From a hand start (the
# previous fit with the new classes' integers read off the facts, wp74/facts-F32.txt and
# facts-F33.txt, and descended class by class on F32 and F33), the new enums (F42_ENUMS) as a grid
# at the input's integers (the top 2 descended over F42_INTS: every integer of the new classes
# and the signed register multiply's / divide's sexec), then the sweep over F42_ENUMS with
# F42_INTS descended inside every move; the corpus guard over every modelled run is the guard,
# as in stages 9 to 15 (no run outside F32 and F33 decodes a new class or a signed register
# multiply or divide).
F42_CLASSES = ("incdec", "flag", "flag_di", "flag_ei", "extend", "extend_w", "adjust",
               "adjust_b", "convert", "convert_d", "rol4", "ror4", "bit1", "bit1_test",
               "bit1_rmw", "bit1_clr", "rol4_mem", "ror4_mem", "mul_imm", "bcd4s", "bcd4s_cmp",
               "bf_ext", "bf_ins")
F42_ENUMS = {n: OPTIONS[n] for n in ("bf_count", "page_grp")}
F42_INTS = ([f"{cls}.{name}" for cls in F42_CLASSES for name in DEFAULT_COST[cls]]
            + ["mul.sexec", "div.sexec"])

# Stage 15 (WP76, F30, F31): the facts-only shapes the probe families turned into mechanisms.
# From a hand start (the previous fit with the new enums on and their integers read off), the
# new enums (F41_ENUMS: the odd-address short jump's idle bus, the REP exit's write-back, the
# split last cycle's floor, the I/O string setup's wait clock in the refill run, the take sync
# beside the start's aborted cycle, the stream's fetch hold, 8E behind the OUT, the 8C store's
# datum, LDEA's split displacement) as a grid at the input's integers (the top 2 descended over
# F41_INTS: the string classes' exit, setup and new integers, the short transfers' and LDEA's),
# then the sweep over F41_ENUMS with F41_INTS descended inside every move; the corpus guard
# over every modelled run is the guard, as in stages 9 to 14.
F41_ENUMS = {n: OPTIONS[n] for n in ("xfer_odd", "str_exit", "str_split", "str_io_setup",
                                     "str_start", "str_fetch", "sreg_io", "sreg_store",
                                     "lea_disp")}
F41_INTS = ([f"{cls}.{name}" for cls in ("str_move", "str_cmp", "str_store", "str_load",
                                         "str_scan", "str_in", "str_out")
             for name in ("rpre", "zexit", "first", "rexit", "cexit", "nx", "xwb", "xsplit",
                          "xfetch", "zfetch")
             if name in DEFAULT_COST[cls] or name == "nx"]
            + ["branch_short.hold", "dbnz.hold", "lea.nx", "lea.exec", "store.setup"])

# Stage 14 (WP72, F23, F25): the control-flow and EA/stack-frame misses the thirty-ninth fit
# left. From the previous stage's output (the tracked fit, or a hand start), the new enums
# (F40_ENUMS: a transfer's aborted cycle on its start with an odd byte of room, a taken
# conditional form's own quiet window before its flush, PUSH R's requests counted as a DW
# form's, LDEA's EA clocks behind an I/O cycle's recovery, the IR byte as room during LDEA's
# EA clocks, PREPARE's take sync on the whole fetch run) as a grid at the input's integers (the
# top 2 descended over F40_INTS: F23's and F25's classes and the two new integers), then the
# sweep over F40_SWEEP (with imm_latch, the data latch shared by an immediate and a waiting
# OUT's data) with F40_INTS descended inside every move; the corpus guard over every modelled
# run is the guard, as in stages 9 to 13 (no run outside F23 and F25 reads the new enums'
# classes; imm_latch is checked over every family by the guard).
F40_ENUMS = {n: OPTIONS[n] for n in ("xfer_abort", "cond_gap", "burst_count", "lea_io",
                                     "lea_room", "prepare_sync")}
F40_SWEEP = dict(F40_ENUMS, imm_latch=OPTIONS["imm_latch"])

# Stage 13 (WP67, F24): the string and block forms. From the previous stage's output (the
# tracked fit), the string templates' enums (F24_ENUMS: the REP form's opcode take, the REP
# compare's overrun read) as a grid at the input's integers (the top 2 descended over
# F24_INTS, the seven str_* classes' integers), then the sweep over F24_ENUMS with F24_INTS
# descended inside every move; the corpus guard over every modelled run is the guard, as in
# stages 9 to 12 (no run outside F24 reads a str_* class or the new enums: a move can only
# change F24).
# (WP70) with the string forms' last cycle in the unprefixed form, the I/O write's datum in the
# data latch, and the requests counted as a DW-form I/O request's.
F24_ENUMS = {n: OPTIONS[n] for n in ("str_take", "str_setup", "str_overrun", "str_hold",
                                     "str_last", "str_io_latch", "str_count")}
F24_INTS = [f"{cls}.{name}" for cls in ("str_move", "str_cmp", "str_store", "str_load",
                                        "str_scan", "str_in", "str_out")
            for name in ("pre", "setup", "mid", "exec", "rpre", "zexit", "first", "loop",
                         "loop1", "last", "rexit", "cexit", "chold", "nx")
            if name in DEFAULT_COST[cls] or name == "nx"]

# Stage 12 (WP61, F28, F29): the refresh at a unit's exit before an OUT, the beaten fetch's
# successor, the group forms' displacement hold and the DW form's lift. From the previous
# stage's output (the tracked fit), the new enums (F28_ENUMS: the write-back under a refresh
# hold, a refresh beside a relatched ready I/O, the fetch-free window as posted, the boundary
# of a clocks step on the start clock, the step on a port lead's first clock, the committed
# fetch after a beaten one; F29's group displacement hold and the moved DW request's lift) as a
# grid at the input's integers (the top 2 descended over F28_INTS), then the sweep over them
# and the rules they touch (F28_SWEEP), F28_INTS descended inside every move; the corpus guard
# over every modelled run is the guard, as in stages 9 to 11.
F28_ENUMS = {n: OPTIONS[n] for n in ("refresh_wb", "refresh_relatch", "refresh_window",
                                     "refresh_start_seam", "refresh_step_lead",
                                     "refresh_beat_b2b", "grp_disp", "dw_lift")}
F28_SWEEP = dict(F28_ENUMS, **{n: OPTIONS[n] for n in (
    "refresh_wbsync", "refresh_clk_start", "refresh_lead_port", "refresh_lead",
    "refresh_post", "refresh_beat_t4", "refresh_io_step", "grp_io_hold", "disp_io",
    "dw_slot", "port_ready")})
F28_INTS = ["shift_cl.wb", "rmw.grp_free", "out.relatch"]

# Stage 11 (WP58, F27): the refresh-on probe family. From the previous stage's output (the
# tracked fit), the I/O steps' enums (F27_ENUMS: a pending refresh on the posted I/O's steps,
# the refresh's last clock under a step, an IN's issue on a step after a refresh, the beaten
# fetch's pair for an OUT only, a ready I/O not relatched by a take on its issue clock) as a
# grid with refresh_post (its post_beat: the hold kept beside a beaten fetch that does not run
# first), then the sweep over them and the refresh rules F27 probes (F27_SWEEP), F27_INTS
# descended inside every move; the corpus guard over every modelled run is the guard, as in
# stages 9 and 10 (the in/out integers are every family's: the guard refuses any loss).
F27_ENUMS = {n: OPTIONS[n] for n in ("refresh_io_step", "refresh_io_stall", "io_step_issue",
                                     "refresh_io_run", "port_ready", "refresh_post")}
F27_SWEEP = dict(F27_ENUMS, **{n: OPTIONS[n] for n in (
    "room_ir_imm", "refresh_drop_post", "refresh_lead_port", "refresh_drop_unit",
    "refresh_beat_t4", "refresh_lead")})
F27_INTS = ["in.lead", "out.lead", "refresh_stall"]

# Stage 10 (WP55, F23): control flow inside the chain. From the previous stage's output (the
# tracked fit), the transfer classes' integers (F23_INTS: branch_short, branch_near, dbnz,
# call, ret) are descended and the new enums (F23_ENUMS: the refill's gate, the hold before
# the flush, the fetch in flight at it, CALL's order, the transfers as register-only forms)
# enumerated on F23, with the corpus guard over every modelled run as stage 9's (no run outside
# F23 reads the new classes, so only an enum move could change one).
F23_ENUMS = {n: OPTIONS[n] for n in ("refill_start", "flush_hold", "flush_inflight",
                                     "untaken", "call_order", "branch_reg")}
F23_INTS = ["branch_short.pre", "branch_short.cond", "branch_short.exec", "branch_short.post",
            "branch_short.nexec", "branch_short.nx", "branch_short.fgap", "branch_short.nfgap", "branch_short.hold",
            "branch_near.pre", "branch_near.exec", "branch_near.post", "branch_near.nexec",
            "branch_near.nx", "branch_near.fgap", "branch_near.hold",
            "dbnz.pre", "dbnz.exec", "dbnz.post", "dbnz.nexec", "dbnz.nx", "dbnz.fgap", "dbnz.nfgap", "dbnz.hold",
            "call.pre", "call.setup", "call.setup_free", "call.exec", "call.post", "call.nx",
            "call.fgap", "call.hold",
            "ret.pre", "ret.setup", "ret.setup_free", "ret.exec", "ret.post", "ret.fgap", "ret.hold"]

# Stage 9 (WP52, F25): the EA alone and the stack frame. From the previous stage's output
# (the tracked fit), the new classes' integers (F25_INTS: LDEA, XLAT, MOV sreg,m16, the
# immediate, segment and burst pushes and pops, PREPARE and DISPOSE) are descended and the
# new enums (F25_ENUMS) enumerated on F25, every other family as the guard (and the corpus
# guard); the earlier classes' integers and every earlier enum stay as they are (no run
# outside F25 reads the new classes, so the guard can only move through the enums).
F25_ENUMS = {n: OPTIONS[n] for n in ("lea_form", "burst_wait", "prepare_order")}
F25_INTS = ["lea.pre", "lea.exec", "lea.nx", "lea.wb", "lea.dadd",
            "xlat.pre", "xlat.setup", "xlat.setup_free", "xlat.exec", "xlat.nx",
            "load_seg.pre", "load_seg.exec", "load_seg.wb", "load_seg.nx",
            "push_imm.pre", "push_imm.setup", "push_imm.setup_free", "push_imm.post",
            "push_imm.nx",
            "push_seg.setup", "push_seg.setup_free", "push_seg.post", "push_seg.nx",
            "pop_seg.setup", "pop_seg.setup_free", "pop_seg.exec", "pop_seg.nx",
            "dispose.pre", "dispose.setup", "dispose.setup_free", "dispose.exec", "dispose.nx",
            "prepare.pre", "prepare.setup", "prepare.setup_free", "prepare.exec", "prepare.nx",
            "push_r.pre", "push_r.setup", "push_r.setup_free", "push_r.wsetup", "push_r.gap",
            "push_r.post", "push_r.nx",
            "pop_r.pre", "pop_r.setup", "pop_r.setup_free", "pop_r.wsetup", "pop_r.gap",
            "pop_r.exec", "pop_r.nx"]
F40_INTS = F23_INTS + ["branch_short.cfgap"] + F25_INTS + ["prepare.wb"]   # (WP72)

# Stage 8 (WP14): the refresh controller, F8 only (RFM FCh), every other family as the
# guard. The refresh enums and integers are read only by a chain with refresh on, so no
# guard run can change; the stage exists so that they are fitted on F8 alone and never
# traded against another family. refresh_interval is read off (16 clocks, the mean
# refresh spacing in the long-shift idle) and only diagnosed.
REFRESH_ENUMS = {n: OPTIONS[n] for n in ("refresh_timer", "refresh_fetch", "refresh_data",
                                         "refresh_b2b", "refresh_drop", "refresh_eu",
                                         "refresh_accept")}
REFRESH_INTS = ["refresh_stall", "refresh_stall_exec"]
# (WP17, F13) the EU side, re-enumerated with F13 next to F8: the core (what a refresh
# costs the EU, on which clocks it is taken) as a grid with the bus side kept as WP14
# chose it, then a coordinate descent over the hold rule's sub-options, then the hold
# integers. REFRESH_SEED is where the descent starts (the hand-steered WP17 values).
REFRESH_CORE = {n: OPTIONS[n] for n in ("refresh_eu", "refresh_accept")}
REFRESH_HOLD_ENUMS = {n: OPTIONS[n] for n in (
    "refresh_exec", "refresh_loop_entry", "refresh_clk_start", "refresh_hold_take",
    "refresh_after", "refresh_mul", "refresh_enable", "refresh_io",
    "refresh_drop", "refresh_drop_on", "refresh_reraise", "refresh_b2b",
    # (WP23, F17: the chain turns refresh on itself; F17 joins F8 and F13 in stage 8)
    "sfr_cycle", "refresh_restart", "refresh_counter", "halt_refresh", "refresh_take",
    "refresh_start_hold",
    # (WP24, F18: the prelude marker and the exec-boundary ladder; F18 joins stage 8) the
    # divider's count loop, the memory shift's loop, the prelude tail (refresh-on preludes
    # modelled from POP PSW on; refuted, kept searchable) with its latch-sync restriction
    "refresh_unit", "refresh_rmw_loop", "refresh_rmw_span", "refresh_recent_by", "prelude_tail",
    "wlatch_ir_at",
    # (WP34, finding 8 c and h, no new data): HALT's two status clocks, no refresh in a posted
    # I/O's lead, the take sync on a beaten fetch met 2 clocks early, a fetch beaten in HALT
    # dropped (halt_refresh=run_drop), the displacement's address phase under a refresh
    "refresh_halt", "refresh_lead", "refresh_sync", "refresh_disp",
    # (WP35, finding 8 b, c, d, g, no new data): the I/O count beside the EU's early fetch run,
    # a lost request back on the next instruction start, a pending request at the loop's eve
    "dw_view", "refresh_lost", "refresh_eve",
    # (WP36, finding 8 b, f, no new data): the NOP's end inside a refresh's window, the
    # multiply's and divide's loop exit (with the class's rexit), the retry moved with the
    # exec's end, the count-less shift's 2-clock exit, the aborted request under a refresh,
    # the I/O lead's first free clock
    "refresh_take0", "refresh_mul_exit", "refresh_retry", "shift_exit0", "refresh_abort",
    "refresh_lift",
    # (WP37, finding 8, the refresh side's middle, no new data): the memory shift's write
    # setup in the register shift's shape, its read's CL clocks, the request aborted under a
    # refresh, the sync on an aborted cycle, the write-back sync, a posted request's first
    # clock, the clocks between two operand takes
    "refresh_rmw_shape", "refresh_grpcl", "refresh_abort_retry", "refresh_abort_wait",
    "refresh_wbsync", "refresh_post", "refresh_take_seam",
    # (WP38, finding 8, the refresh side's middle, no new data): the shift's loop entry as
    # the exec's hold point, the SFR store's setup, a refresh's wait states before an I/O
    # form's count began, the request lost inside a register unit's clocks at even room
    "refresh_loop_hold", "sfr_setup", "refresh_io_pre", "refresh_drop_unit",
    # (WP39, finding 8, the refresh side's middle, no new data): the fetch a refresh beat
    # while an IN or OUT waits for its I/O runs two words; a take behind a byte latched at a
    # full queue is a hold point
    "refresh_io_run", "refresh_take_latch",
    # (WP40, finding 8 a, the prelude's tail in the aligned lists): the rules the refresh-on
    # pre window needs (POP PSW's clocks under a refresh, the beaten fetch's reissue, a ModR/M
    # start and the take sync in the early run, the IR's idle slot under a 16-bit immediate);
    # every one is neutral on the chains with the stand-in prelude (17,822 runs)
    "pop_refresh", "refresh_reissue", "refresh_run_modrm", "refresh_sync_run",
    "refresh_sync_reg", "room_ir_imm",
    # (WP41, the prelude tail's last losses): a port form's lead open on its first clock, the
    # request lost on a port form's post held by the I/O, no refresh while an I/O form waits
    # for the data latch, the delivery clock of a 3-clock beaten fetch
    "refresh_lead_port", "refresh_drop_post", "refresh_wlatch", "refresh_beat_t4")}
REFRESH_HOLD_INTS = ["shift_tail", "refresh_tail_bound", "rfm_delay", "reraise_off",
                     "refresh_recent"]
# (WP23) refresh_align is no longer searched: phase and phase_eu are per-run alignments,
# which the fit does not admit (phase_eu stays a diagnostic in the code). The hand-steered
# values: refresh_align=prelude (no per-run alignment: the timer's
# counter at clock 0 is the prelude's, refresh.PRELUDE_COUNTER), the RFM store's on-chip
# cycle and effect clock, the counter-bit edge, the beaten request dropped at odd room and
# re-raised at the loop's exit, the halted run, the last-byte take.
REFRESH_SEED = dict(refresh_loop_entry="open",
                    refresh_clk_start="after_wait", refresh_hold_take="port",
                    refresh_after="fetch_next", refresh_mul="loop_odd", refresh_align="prelude",
                    sfr_cycle="io", refresh_counter="edge", rfm_delay=3,
                    halt_refresh="run_drop",     # (WP34; WP23: run)
                    refresh_drop=True, refresh_drop_on="odd", refresh_reraise="unit",
                    reraise_off=0, refresh_take="last",
                    # (WP24) the hand-steered F18 values: the divider's loop, the memory
                    # shift's loop over all its shift clocks, the loop's-eve boundary only
                    # within refresh_recent clocks of the previous refresh
                    refresh_unit="muldiv", refresh_rmw_loop="loop", refresh_rmw_span="all",
                    refresh_exec="every2_recent", refresh_recent=18, refresh_recent_by="fetch",
                    # (WP34) the hand-steered END-block and displacement values
                    refresh_halt="status", refresh_lead="closed", refresh_sync="run",
                    refresh_disp="free",
                    # (WP35) the hand-steered values
                    dw_view="eu", refresh_lost="start", refresh_eve="hold",
                    # (WP36) the hand-steered values (refresh_mul_exit reads the class's
                    # rexit: mul 8, div 6, in the hand fit's cost table)
                    refresh_take0="none", refresh_mul_exit="exit", refresh_retry="end",
                    shift_exit0="exit", refresh_abort="abort", refresh_lift="free",
                    # (WP37) the hand-steered values
                    refresh_rmw_shape="shift", refresh_grpcl="step",
                    refresh_abort_retry="next", refresh_abort_wait="run",
                    refresh_wbsync="seam", refresh_post="post", refresh_take_seam="seam",
                    # (WP38) the hand-steered values
                    refresh_loop_hold="entry", sfr_setup="count", refresh_io_pre="count",
                    refresh_drop_unit="unit",
                    # (WP39) the hand-steered values
                    refresh_io_run="pair", refresh_take_latch="hold",
                    # (WP40) the prelude tail's rules, adopted with WP41's (prelude_anchor=pop,
                    # the counter at the POP read refresh.POP_COUNTER: no stand-in table read)
                    pop_refresh="stall", refresh_reissue="keep", refresh_run_modrm="wait",
                    refresh_sync_run="two", refresh_sync_reg="delivery", room_ir_imm="none",
                    # (WP41) the hand-steered values
                    refresh_lead_port="last", refresh_drop_post="hold", refresh_wlatch="hold",
                    refresh_beat_t4="t4")


# Marker kinds held out of every fitting stage. Through the fourth fit the OUT
# marker was (its I/O timing was the open question); the fifth fit models I/O
# and fits every marker kind.
HELD_OUT = ()


def fitted(ids) -> list[str]:
    return [i for i in ids if _DATA[i].family in ("F0", "F0w") or _DATA[i].marker not in HELD_OUT]


def held_out(ids) -> list[str]:
    return [i for i in ids if i not in set(fitted(ids))]


def _ids(stage: int) -> list[str]:
    return fitted(load(STAGE_FAMILIES[stage]))


def _guard(stage: int) -> list[str]:
    fams = [f for s in range(2, stage) for f in STAGE_FAMILIES[s]
            if f not in STAGE_FAMILIES[stage]]
    if stage >= 3:
        fams = ["F0w"] + fams        # the WTC read-off (OUT marker by design) guards too
    return fitted(load(list(dict.fromkeys(fams)))) if fams else []


def stage1(cfg: Config, log=say) -> dict:
    """Bus read-off: every cycle's length is 3 + its wait count (memory field 0, I/O field 7)."""
    ids = _ids(1)
    lengths = defaultdict(Counter)
    bad = []
    for i in ids:
        r = _DATA[i]
        mem, io = r.chain.wtc & 3, (r.chain.wtc >> 14) & 3
        for e in r.silicon:
            want = 3 + (io if e[1].startswith("io") else mem)
            lengths[(e[1], "io" if e[1].startswith("io") else "mem",
                     io if e[1].startswith("io") else mem)][e[4]] += 1
            if e[4] != want:
                bad.append((i, e))
    for (kind, space, w), c in sorted(lengths.items()):
        log(f"  {kind:<12} {space} waits {w}: lengths {dict(c)}")
    log(f"  cycles whose length is not 3 + waits: {len(bad)}")
    card = scorecard(cfg, ids)
    print_scorecard(card, log)
    return {"stage": 1, "config": cfg.to_json(), "length_violations": bad[:20],
            "scorecard": card}


def stage2(cfg: Config, log=say, options=None, seed=None) -> dict:
    """Queue grid on F0 with the F0-pinned costs, built on the storage seed (seeds/stage2.json);
    every 18/18 combination survives and is carried to stage 3."""
    ids = _ids(2)
    options = options or QUEUE_OPTIONS
    if seed is None:
        seed, record = load_seed(2)
    else:
        record = {"file": None, "values": seed}
    cfg = cfg.replace(**seed)
    log(f"  seed {record['file']}: {json.dumps(seed, sort_keys=True)}")
    cfgs = grid(cfg, options)
    log(f"  grid: {len(cfgs)} queue/decoder combinations x {len(ids)} F0 runs")
    t0 = time.time()
    scored = []
    batch = 512
    for k in range(0, len(cfgs), batch):
        scored += score_many(cfgs[k:k + batch], ids)
        log(f"    {min(k + batch, len(cfgs))}/{len(cfgs)}  {time.time() - t0:.0f}s  "
            f"best so far {max(s.exact for s in scored)}/{len(ids)}")
    hist = Counter(s.exact for s in scored)
    log(f"  exact-count histogram over the grid: {dict(sorted(hist.items()))}")
    # The F0-pinned integers were read off by hand for one structure; a structure
    # that moves an instruction start by a clock or two shifts them. Give every
    # structure that already gets a third of F0 a descent over those integers.
    rescue = [s for s in scored if len(ids) // 3 <= s.exact < len(ids)]
    log(f"  descending the F0 integers {F0_INTS} for {len(rescue)} partial structures")
    for k, s in enumerate(rescue):
        f = descend(s, F0_INTS, ids, max_rounds=6)
        if f.exact == len(ids):
            scored.append(f)
        if (k + 1) % 100 == 0:
            log(f"    {k + 1}/{len(rescue)}  {time.time() - t0:.0f}s")
    full = [s for s in scored if s.exact == len(ids)]
    log(f"  survivors (18/18): {len(full)}")
    summ = summarize_survivors(cfg, [s.cfg for s in full])
    for n in options:
        log(f"    {n:<16} {summ.get(n)}")
    surv = [diff_cfg(cfg, s.cfg) for s in full]
    return {"stage": 2, "config": (full[0].cfg if full else cfg).to_json(),
            "base": cfg.to_json(), "survivors": surv, "survivor_options": summ,
            "grid_size": len(cfgs), "histogram": dict(hist), "seed": record}


def _search(bases: list[Config], enums: dict, ints: list, ids, guard, log, top_k=12,
            label="", pairs_k=2) -> tuple[Scored, list[Scored]]:
    """Enumerate bases x enums with base integers, then descend the top_k by score."""
    cands = []
    for b in bases:
        cands += grid(b, enums) if enums else [b]
    log(f"  {label}: {len(cands)} structural candidates x {len(ids)} runs "
        f"(+{len(guard)} guard runs)")
    t0 = time.time()
    scored = []
    for k in range(0, len(cands), 256):
        scored += score_many(cands[k:k + 256], ids, guard)
    scored.sort(key=lambda s: s.key, reverse=True)
    log(f"    enumerated in {time.time() - t0:.0f}s; best start guard {scored[0].guard} "
        f"exact {scored[0].exact}")
    seen, starts = set(), []
    for s in scored:
        sig = json.dumps(s.cfg.to_json(), sort_keys=True)
        if CORPUS_GUARD is not None and not any(
                sig == json.dumps(b.to_json(), sort_keys=True) for b in bases) and not any(
                corpus_ok(b, s.cfg) for b in bases):
            continue                    # (WP26) the corpus guard: a family loses a run
        if sig not in seen:
            seen.add(sig)
            starts.append(s)
        if len(starts) >= top_k:
            break
    finals = []
    for n, s in enumerate(starts):
        f = descend(s, ints, ids, guard, log=None, pairs=n < pairs_k)
        finals.append(f)
        log(f"    start {n + 1}/{len(starts)}: guard {s.guard}->{f.guard} exact {s.exact}->"
            f"{f.exact}/{len(ids)} resid {f.resid}  {time.time() - t0:.0f}s")
    finals.sort(key=lambda s: s.key, reverse=True)
    best, ties = pick(finals)
    finals = [best] + [f for f in finals if f is not best]
    for t in ties:
        log(f"    tie on exact runs, broken over every family ({t['chosen_all_exact']} "
            f"against {t['all_exact']}): the other differs in {json.dumps(t['diff'])}")
    return best, finals, ties


def _report_stage(stage: int, best: Scored, finals, ints, ids, guard, base: Config, log,
                  extra=None, ties=()) -> dict:
    log(f"  chosen: {json.dumps(diff_cfg(base, best.cfg))}")
    if ties:
        log(f"  {len(ties)} ties on exact runs recorded (stage JSON 'ties')")
    card = scorecard(best.cfg, ids)
    print_scorecard(card, log)
    if guard:
        g = scorecard(best.cfg, guard)
        log(f"  guard (earlier stages): {g['exact']}/{g['runs']}")
    out_ids = held_out(load(STAGE_FAMILIES[stage]))
    if out_ids:
        h = scorecard(best.cfg, out_ids)
        log(f"  held out (OUT marker, not fitted): {h['exact']}/{h['runs']}")
    dep = knob_dependence(best.cfg, ints, ids, log=log)
    payload = {"stage": stage, "config": best.cfg.to_json(), "scorecard": card,
               "chosen": diff_cfg(base, best.cfg),
               "ties": list(ties),
               "alternatives": [{"diff": diff_cfg(best.cfg, f.cfg), "guard": f.guard,
                                 "exact": f.exact, "resid": f.resid} for f in finals[1:]],
               "knob_dependence": dep}
    if extra:
        payload.update(extra)
    return payload


def _survivor_configs(prev: dict) -> list[Config]:
    base = Config.from_json(prev.get("base", prev["config"]))
    survivors = prev.get("survivors")
    if not survivors:
        return [Config.from_json(prev["config"])]
    return [base.replace(**d) for d in survivors]


# Stage 3 picks among the stage-2 survivors by the release families first: the PUSH-marked
# F2 and F9 runs (one instruction group after the fence) are what found the queue's
# storage and request rule (third fit), so a survivor is ranked by them before the rest.
RELEASE_CRITERION = (("F2", "push"), ("F9", "push"))


def _criterion_ids(ids) -> list[str]:
    return [i for i in ids if (_DATA[i].family, _DATA[i].marker) in RELEASE_CRITERION]


def stage3(prev: dict, log=say, top_k=4, max_bases=16, seed=None, sweep=True) -> dict:
    ids, guard = _ids(3), _guard(3)
    if seed is None:
        seed, record = load_seed(3)
    else:
        record = {"file": None, "values": seed}
    log(f"  seed {record['file']}: {len(seed)} values")
    bases = []
    for b in _survivor_configs(prev):
        seeded = b.replace(**seed)
        bases.append(seeded)
        # a survivor whose F0 integers stage 2 had to move keeps them as a second start
        moved = {n: getp(b, n) for n in F0_INTS if getp(b, n) != getp(DEFAULT, n)}
        if moved:
            bases.append(seeded.replace(**moved))
    base0 = Config.from_json(prev.get("base", prev["config"]))
    ranking = None
    if len(bases) > max_bases:
        # Rank survivors with the seed integers: the guard, then the release criterion
        # (F2/F9 PUSH), then the rest of this stage's runs; keep the best.
        crit = _criterion_ids(ids)
        rest = [i for i in ids if i not in set(crit)]
        scored = []
        for k in range(0, len(bases), 256):
            chunk = bases[k:k + 256]
            for a, b in zip(score_many(chunk, crit, guard), score_many(chunk, rest)):
                scored.append((a.guard, a.exact, b.exact, -(a.resid + b.resid), a.cfg))
        scored.sort(key=lambda x: x[:4], reverse=True)
        log(f"  {len(bases)} stage-2 survivors; keeping the {max_bases} best by guard, then "
            f"F2/F9 PUSH ({len(crit)} runs), then the rest of this stage")
        for g, c, r, _, _ in scored[:max_bases]:
            log(f"    guard {g} release {c}/{len(crit)} rest {r}/{len(rest)}")
        ranking = [{"guard": g, "release": c, "rest": r, "diff": diff_cfg(base0, cfg)}
                   for g, c, r, _, cfg in scored[:max_bases]]
        bases = [x[4] for x in scored[:max_bases]]
    best, finals, ties1 = _search(bases, MARKER_ENUMS, MARKER_INTS, ids, guard, log, top_k,
                                  "markers")
    first = diff_cfg(base0, best.cfg)
    log(f"  first grid chose: {json.dumps(first)}")
    best, finals, ties2 = _search([best.cfg], STAGE3_REVISIT, MARKER_INTS, ids, guard, log, 2,
                                  "F12 B revisit", pairs_k=0)
    extra = {"seed": record, "ranking": ranking, "first_grid": first}
    ties = ties1 + ties2
    if sweep:
        log(f"  stage 3 sweep: {len(STAGE3_SWEEP)} enums, "
            f"{sum(len(v) - 1 for v in STAGE3_SWEEP.values())} alternatives, "
            f"{len(STAGE3_SWEEP_INTS)} integers inside")
        swept, rec = enum_sweep(best, STAGE3_SWEEP, STAGE3_SWEEP_INTS, ids, guard, log,
                                label="stage 3 sweep", **SWEEP_BUDGET[3])
        if swept is not best:
            finals = [swept] + finals
        best = swept
        ties = ties + [dict(t, sweep=True) for t in rec["ties"]]
        extra["sweep"] = rec
    return _report_stage(3, best, finals, MARKER_INTS, ids, guard, base0, log,
                         extra=extra, ties=ties)


# (WP16) The F12 series-B storage and sync rules and the shift/DW-OUT forms, enumerated
# around stage 3's result (a second grid, as stage 5's IMM_REVISIT: in MARKER_ENUMS they
# would multiply the survivor grid by 32) with the marker integers descended again.
STAGE3_REVISIT = {"room_ir_ready": OPTIONS["room_ir_ready"],
                  "latch_midtake": OPTIONS["latch_midtake"],
                  "imm_landed": OPTIONS["imm_landed"], "shift_count": OPTIONS["shift_count"],
                  "count_latch": OPTIONS["count_latch"], "out.wbsync0": (0, 1)}


# (WP18) The enum sweeps (enum_sweep) of stages 3, 4 and 6. Stage 3 chooses, with the
# marker integers descended inside every move, every structure its families observe: the
# marker/arbitration enums at their full option sets, the queue storage (which F0 cannot
# choose and stage 2 no longer gets as a seed), the request rule and the EU's syncs, the
# I/O mechanism, the data latch and the F12 B rules. Stage 4 re-opens the register-side
# rules with the register integers inside (stage 3's ties on shift_count and
# room_ir_ready are decided by the shift integers). Stage 6 re-opens everything structural
# under every family's guard with every class integer inside, before the polish.
_S3 = ("hold_fetch", "data_while_fetch", "arbiter", "hold_run", "take_sync", "late_read",
       "write_wait", "post_on_take", "start_sync", "request_eval", "request_hold",
       "arrive_partial", "word_latch", "latch_read", "latch_hold", "room_ir", "modrm_commit",
       "request_sample", "abort_fetch", "io_release", "io_post", "io_count", "port_latch",
       "port_sync", "io_hold", "io_interlock", "imm_latch", "wb_from", "wlatch_cls",
       "wlatch_hold", "wlatch_src", "wlatch_imm", "room_ir_ready", "latch_midtake",
       "imm_landed", "shift_count", "count_latch")
STAGE3_SWEEP = {**{n: OPTIONS[n] for n in _S3}, "out.wbsync": (0, 1), "out.wbsync0": (0, 1)}
IN_INTS = ["in.pre", "in.pre0", "in.exec", "in.setup", "in.post", "in.lead", "in.relatch",
           "in.setup0", "out.setup0"]
STAGE3_SWEEP_INTS = list(dict.fromkeys(MARKER_INTS + IN_INTS + ["shift_imm.exec0",
                                                                 "shift_imm.cpre",
                                                                 "shift_imm.nx"]))
# The coupled groups of the sweep's tier 3: the enums of one mechanism together, with the
# integer that gates the mechanism (a latch length, a hold, a lead, a recovery: at 0 the
# group's enums change no run) on a coarse lattice for the descent to refine.
GATE_LATTICE = (0, 2, 4)
SWEEP_GROUPS = {
    "storage": {n: OPTIONS[n] for n in ("word_latch", "latch_read", "latch_hold",
                                        "modrm_commit", "abort_fetch")},
    "request": {n: OPTIONS[n] for n in ("room_ir", "request_eval", "request_hold",
                                        "arrive_partial", "request_sample")},
    "io": {**IO_REVISIT, "out.relatch": GATE_LATTICE},
    "io_follow": {**{n: OPTIONS[n] for n in ("io_hold", "io_interlock", "imm_latch",
                                             "wb_from")},
                  "out.lead": GATE_LATTICE, "io_recover": GATE_LATTICE},
    "latch": {**{n: OPTIONS[n] for n in ("wlatch_cls", "wlatch_hold", "wlatch_src",
                                         "wlatch_imm")}, "wlatch": GATE_LATTICE},
    "arbiter": {n: OPTIONS[n] for n in ("arbiter", "hold_fetch", "data_while_fetch",
                                        "write_wait")},
}
# Cycles of each stage's sweep (a cycle: tier 1, then one joint move), and the groups:
# stage 3 chooses the mechanisms (tier 3 with the coupled groups); stage 6's revisit grids
# are those groups at fixed integers already, so its sweep runs tiers 1-2 only, and with
# every class integer inside (every run differs when the END block moves) a descent there
# costs ~10 min: two rounds inside, the 6 alternatives with most gains, two cycles.
SWEEP_BUDGET = {3: dict(max_cycles=10, groups=SWEEP_GROUPS, group_k=2),
                4: dict(max_cycles=6), 5: dict(max_cycles=10, lookahead=True), 6: dict(max_cycles=2, desc_rounds=2, screen_k=6)}
STAGE4_SWEEP = {n: OPTIONS[n] for n in ("shift_count", "room_ir_ready", "latch_midtake",
                                        "imm_landed", "late_read", "start_sync",
                                        "wlatch_imm", "take_sync", "count_latch",
                                        # (WP32) WP32_REVISIT's enums
                                        "io_take_nx", "modrm_port", "nop_hold", "port_issue",
                                        "latch_start", "abort_latched")}
STAGE6_SWEEP = {**{n: OPTIONS[n] for n in OPTIONS if not n.startswith("refresh_")},
                "out.wbsync": (0, 1), "out.wbsync0": (0, 1), "arbiter_q": (2, 3, 4)}

# Stage 6's grids in order: (name, enums, extra stage_n arguments); polish runs after the
# last. --grid NAME resumes the stage at NAME (the grids before it are skipped).
STAGE6_GRIDS = [
    ("ARB_ENUMS", ARB_ENUMS, {}),
    # the queue request rule and the EU's bus syncs, revisited on F6 under the guard of
    # every earlier family (stage 2 chose them on F0 alone)
    ("QUEUE_REVISIT", QUEUE_REVISIT, {}),
    ("STORAGE_REVISIT", STORAGE_REVISIT, {}),
    # the I/O mechanism, enumerated under the guard of every family (fifth fit)
    ("IO_REVISIT", IO_REVISIT, {}),
    ("IO_FOLLOWER_REVISIT", IO_FOLLOWER_REVISIT, {}),
    ("OUT_REVISIT", OUT_REVISIT, {}),
    ("OUT_REVISIT2", OUT_REVISIT2, {}),
    ("F20_REVISIT", F20_REVISIT, {}),
    ("WP32_REVISIT", WP32_REVISIT, {}),
    ("WP33_STAGE6", WP33_STAGE6, {}),
    ("LATCH_REVISIT", LATCH_REVISIT,
     dict(sweep=STAGE6_SWEEP, sweep_ints=list(dict.fromkeys(MARKER_INTS + REG_INTS + MEM_INTS)),
          sweep_kw=SWEEP_BUDGET[6])),
]
STAGE6_GRID_NAMES = [g[0] for g in STAGE6_GRIDS]


def stage6_grids(start: str | None = None) -> list:
    """STAGE6_GRIDS from the grid named start (all of them for None)."""
    if start is None:
        return list(STAGE6_GRIDS)
    if start not in STAGE6_GRID_NAMES:
        raise ValueError(f"unknown stage 6 grid {start!r}: one of {', '.join(STAGE6_GRID_NAMES)}")
    return STAGE6_GRIDS[STAGE6_GRID_NAMES.index(start):]


def stage_n(stage: int, prev: dict, enums: dict, ints: list, log=say, top_k=4,
            pairs_k=1, sweep=None, sweep_ints=None, sweep_kw=None, guard=True) -> dict:
    """The stage's grid (enums at the current integers, the top_k descended), then, with
    sweep, the enum sweep (enum_sweep) over those enums with sweep_ints (default ints)
    descended inside every move. guard=False: no guard runs in the stage key (the corpus
    guard, CORPUS_GUARD, still checks every move over every family)."""
    cache_reset()                      # each grid starts with an empty result cache
    ids, guard = _ids(stage), (_guard(stage) if guard else [])
    base = Config.from_json(prev["config"])
    best, finals, ties = _search([base], enums, ints, ids, guard, log, top_k,
                                 f"stage {stage}", pairs_k=pairs_k)
    extra = {}
    if sweep:
        n = sum(len(v) - 1 for v in sweep.values())
        log(f"  stage {stage} sweep: {len(sweep)} enums, {n} alternatives, "
            f"{len(sweep_ints or ints)} integers inside")
        swept, rec = enum_sweep(best, sweep, sweep_ints or ints, ids, guard, log,
                                label=f"stage {stage} sweep", **(sweep_kw or {}))
        if swept is not best:
            finals = [swept] + finals
        best = swept
        ties = list(ties) + [dict(t, sweep=True) for t in rec["ties"]]
        extra["sweep"] = rec
    out = _report_stage(stage, best, finals, ints, ids, guard, base, log, extra=extra,
                        ties=ties)
    cache_log(f"stage {stage} grid", log)
    return out


POLISH_FAMILIES = ["F3", "F4", "F5", "F6"]
# the fence, the WTC read-off, the markers and the release families (F2, F9: one
# instruction group after the fence) are not traded away
POLISH_GUARD = ["F0", "F0w", "F1", "F2", "F9"]


def polish(prev: dict, log=say, max_rounds=12) -> dict:
    """Joint integer descent over every class integer on the fitted runs of F3-F6 (F0, F0w,
    F1, F2, F9 guard).

    The staged descents fit each family's integers to the structure of their
    stage; a structural change in stage 6 strands them. This re-descends all of
    them together, scored on the fitted runs of F3-F6 at once, with F0, F0w, the
    F1 markers and the release families F2 and F9 as a guard that cannot be
    traded away.
    """
    cache_reset()
    ids, guard = fitted(load(POLISH_FAMILIES)), fitted(load(POLISH_GUARD))
    cfg = Config.from_json(prev["config"])
    ints = list(dict.fromkeys(MARKER_INTS + REG_INTS + MEM_INTS))
    start = score_many([cfg], ids, guard)[0]
    log(f"  polish: {len(ints)} integers x {len(ids)} runs (+{len(guard)} guard); "
        f"start guard {start.guard} exact {start.exact}")
    t0 = time.time()
    best = descend(start, ints, ids, guard, max_rounds=max_rounds,
                   log=log, label="polish")
    log(f"  polish: guard {best.guard} exact {start.exact}->{best.exact}/{len(ids)} "
        f"resid {best.resid}  {time.time() - t0:.0f}s")
    log(f"  polish moved: {json.dumps(diff_cfg(cfg, best.cfg))}")
    card = scorecard(best.cfg, ids)
    print_scorecard(card, log)
    cache_log("polish", log)
    out = dict(prev)
    out.update({"config": best.cfg.to_json(), "polish": diff_cfg(cfg, best.cfg),
                "polish_scorecard": card})
    return out


def stage7(prev: dict, log=say) -> dict:
    cfg = Config.from_json(prev["config"])
    out = {"stage": 7, "config": cfg.to_json()}
    for fam in ("F7", "F8"):
        ids = load([fam])
        log(f"  {fam} (zero free parameters):")
        card = scorecard(cfg, ids)
        print_scorecard(card, log)
        out[fam] = card
    every = load(["F0", "F0w", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10",
                  "F11", "F12", "F14", "F15", "F16", "F19", "F20"])
    total = scorecard(cfg, every)
    log("  all families:")
    print_scorecard(total, log)
    out["all"] = total
    return out


def stage8(prev: dict, log=say) -> dict:
    """The refresh machine's EU side on F8 + F13 (WP17), ranked by exact runs, then events
    matched before the first difference (RANK_MATCHED), every other family guarding: the
    core grid (refresh_eu x refresh_accept) at the seed's sub-options, a coordinate
    descent over the hold rule's sub-options, integer descent on the hold integers; then
    each enum's losing alternatives scored at the chosen configuration."""
    global RANK_MATCHED
    RANK_MATCHED = True
    try:
        ids, guard = _ids(8), _guard(8)
        seed, record = load_seed(8)
        log(f"  seed {record['file']}: {json.dumps(seed, sort_keys=True)}")
        base = Config.from_json(prev["config"]).replace(**seed)
        best, _, _ = _search([base], REFRESH_CORE, [], ids, guard, log, top_k=1,
                          label="stage 8 core", pairs_k=0)
        for rnd in range(4):
            moved = False
            for name, values in REFRESH_HOLD_ENUMS.items():
                others = [v for v in values if v != getattr(best.cfg, name)]
                scored = score_many([best.cfg.replace(**{name: v}) for v in others], ids, guard)
                top = max(scored, key=lambda sc: sc.key, default=None)
                if top is not None and top.key > best.key:
                    log(f"  descent {rnd + 1}: {name} {getattr(best.cfg, name)!r} -> "
                        f"{getattr(top.cfg, name)!r}: exact {top.exact} matched {top.matched}")
                    best, moved = top, True
            if not moved:
                break
        best = descend(best, REFRESH_HOLD_INTS, ids, guard, log=log, label="stage 8 ints")
        cfg = best.cfg
        out = _report_stage(8, best, [best], REFRESH_HOLD_INTS, ids, guard,
                            Config.from_json(prev["config"]), log)
        alts = {}
        for name, values in {**REFRESH_ENUMS, **REFRESH_HOLD_ENUMS}.items():
            others = [v for v in values if v != getattr(cfg, name)]
            scored = score_many([cfg.replace(**{name: v}) for v in others], ids, guard)
            alts[name] = {"chosen": getattr(cfg, name), "chosen_exact": best.exact,
                          "others": [{"value": v, "guard": sc.guard, "exact": sc.exact,
                                      "matched": sc.matched, "resid": sc.resid}
                                     for v, sc in zip(others, scored)]}
            log(f"  {name} = {getattr(cfg, name)!r}; alternatives: " + ", ".join(
                f"{v!r} exact {sc.exact} matched {sc.matched}" for v, sc in zip(others, scored)))
        log(f"  chosen: guard {best.guard}/{len(guard)} exact {best.exact}/{len(ids)} "
            f"matched {best.matched}/{sum(len(_DATA[i].silicon) for i in ids)}")
        out["refresh_alternatives"] = alts
        out["seed"] = record
        out["matched"] = best.matched
        for fam in STAGE_FAMILIES[8]:
            fid = [i for i in ids if _DATA[i].family == fam]
            out[f"matched_{fam}"] = score_many([cfg], fid)[0].matched
            out[f"exact_{fam}"] = score_many([cfg], fid)[0].exact
        out["interval_dependence"] = knob_dependence(cfg, ["refresh_interval"], ids, log=log)
    finally:
        RANK_MATCHED = False
    return out


def stage9(prev: dict, log=say) -> dict:
    """(WP52) F25: the new enums as a grid at the input's integers (the top 2 descended over
    F25_INTS), then the enum sweep with F25_INTS descended inside every move; tie-break and
    corpus guard as every stage (the corpus guard is the guard: see below)."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 9 needs the corpus guard (--corpus-guard family or run)")
    # the guard is the corpus guard alone: the stage key's guard runs (every other family)
    # would be scored for every candidate of every descent round, which no move on the new
    # classes can change, and the enum moves are checked over every family by corpus_ok
    return stage_n(9, prev, F25_ENUMS, F25_INTS, log, top_k=2, pairs_k=1, sweep=F25_ENUMS,
                   guard=False)


def stage10(prev: dict, log=say) -> dict:
    """(WP55) F23: the new enums as a grid at the input's integers (the top 2 descended over
    F23_INTS), then the enum sweep with F23_INTS descended inside every move; the corpus guard
    is the guard, as in stage 9."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 10 needs the corpus guard (--corpus-guard family or run)")
    return stage_n(10, prev, F23_ENUMS, F23_INTS, log, top_k=2, pairs_k=1, sweep=F23_ENUMS,
                   guard=False)


def stage11(prev: dict, log=say) -> dict:
    """(WP58) F27: the I/O steps' enums as a grid at the input's integers (the top 2
    descended over F27_INTS), then the sweep over F27_SWEEP with F27_INTS descended inside
    every move; the corpus guard is the guard, as in stages 9 and 10."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 11 needs the corpus guard (--corpus-guard family or run)")
    return stage_n(11, prev, F27_ENUMS, F27_INTS, log, top_k=2, pairs_k=1, sweep=F27_SWEEP,
                   guard=False)


def stage12(prev: dict, log=say) -> dict:
    """(WP61) F28, F29: the new enums as a grid at the input's integers (the top 2 descended
    over F28_INTS), then the sweep over F28_SWEEP with F28_INTS descended inside every move;
    the corpus guard is the guard, as in stages 9 to 11."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 12 needs the corpus guard (--corpus-guard family or run)")
    return stage_n(12, prev, F28_ENUMS, F28_INTS, log, top_k=2, pairs_k=1, sweep=F28_SWEEP,
                   guard=False)


def stage13(prev: dict, log=say) -> dict:
    """(WP67) F24: the string templates' enums as a grid at the input's integers (the top 2
    descended over F24_INTS), then the sweep over F24_ENUMS with F24_INTS descended inside
    every move; the corpus guard is the guard, as in stages 9 to 12."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 13 needs the corpus guard (--corpus-guard family or run)")
    return stage_n(13, prev, F24_ENUMS, F24_INTS, log, top_k=2, pairs_k=1, sweep=F24_ENUMS,
                   guard=False)


def stage14(prev: dict, log=say) -> dict:
    """(WP72) F23, F25: the new enums as a grid at the input's integers (the top 2 descended
    over F40_INTS), then the sweep over F40_SWEEP with F40_INTS descended inside every move; the
    corpus guard is the guard, as in stages 9 to 13."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 14 needs the corpus guard (--corpus-guard family or run)")
    return stage_n(14, prev, F40_ENUMS, F40_INTS, log, top_k=2, pairs_k=1, sweep=F40_SWEEP,
                   guard=False)


def stage15(prev: dict, log=say) -> dict:
    """(WP76) F30, F31 (and F24, F23, F25): the new enums as a grid at the input's integers
    (the top 2 descended over F41_INTS), then the sweep over F41_ENUMS with F41_INTS descended
    inside every move; the corpus guard is the guard, as in stages 9 to 14."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 15 needs the corpus guard (--corpus-guard family or run)")
    return stage_n(15, prev, F41_ENUMS, F41_INTS, log, top_k=2, pairs_k=1, sweep=F41_ENUMS,
                   guard=False)


def stage16(prev: dict, log=say) -> dict:
    """(WP78) F32, F33: the new enums as a grid at the input's integers (the top 2 descended
    over F42_INTS), then the sweep over F42_ENUMS with F42_INTS descended inside every move; the
    corpus guard is the guard, as in stages 9 to 15."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 16 needs the corpus guard (--corpus-guard family or run)")
    return stage_n(16, prev, F42_ENUMS, F42_INTS, log, top_k=2, pairs_k=1,
                   sweep=F42_ENUMS or None, guard=False)


def stage17(prev: dict, log=say) -> dict:
    """(WP81) F32, F33, F34: the new enums as a grid at the input's integers (the top 2
    descended over F43_INTS), then the sweep over F43_ENUMS with F43_INTS descended inside every
    move; the corpus guard is the guard, as in stages 9 to 16."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 17 needs the corpus guard (--corpus-guard family or run)")
    return stage_n(17, prev, F43_ENUMS, F43_INTS, log, top_k=2, pairs_k=1, sweep=F43_ENUMS,
                   guard=False)


def stage18(prev: dict, log=say) -> dict:
    """(WP84) F17, F18: refresh_scope as a grid at the input's integers (both starts descended
    over F44_INTS), then the sweep over F44_ENUMS with F44_INTS descended inside every move; the
    corpus guard is the guard, as in stages 9 to 17."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 18 needs the corpus guard (--corpus-guard family or run)")
    return stage_n(18, prev, F44_ENUMS, F44_INTS, log, top_k=2, pairs_k=1, sweep=F44_ENUMS,
                   guard=False)


def stage19(prev: dict, log=say) -> dict:
    """(WP85) F27, F28 (with F8, F13, F17, F18): the new enums as a grid at the input's integers
    (the top 2 descended over F45_INTS), then the sweep over F45_ENUMS with F45_INTS descended
    inside every move; the corpus guard is the guard, as in stages 9 to 18."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 19 needs the corpus guard (--corpus-guard family or run)")
    return stage_n(19, prev, F45_ENUMS, F45_INTS, log, top_k=2, pairs_k=1, sweep=F45_ENUMS,
                   guard=False)


def stage20(prev: dict, log=say) -> dict:
    """(WP86) F32, F33, F34: the new enums as a grid at the input's integers (the top 2
    descended over F46_INTS), then the sweep over F46_ENUMS with F46_INTS descended inside every
    move; the corpus guard is the guard, as in stages 9 to 19."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 20 needs the corpus guard (--corpus-guard family or run)")
    return stage_n(20, prev, F46_ENUMS, F46_INTS, log, top_k=2, pairs_k=1, sweep=F46_ENUMS,
                   guard=False)


def stage21(prev: dict, log=say) -> dict:
    """(WP88) F35, F36: ret_imm_hold as a grid at the input's integers (both starts descended
    over F47_INTS), then the sweep over F47_ENUMS with F47_INTS descended inside every move; the
    corpus guard is the guard, as in stages 9 to 20."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 21 needs the corpus guard (--corpus-guard family or run)")
    return stage_n(21, prev, F47_ENUMS, F47_INTS, log, top_k=2, pairs_k=1, sweep=F47_ENUMS,
                   guard=False)


def stage22(prev: dict, log=say) -> dict:
    """(WP89) F23, F30, F34, F35: xfer_nt_b2b and decide_abort as a grid at the input's integers
    (the top 2 descended over F48_INTS), then the sweep over F48_ENUMS with F48_INTS descended inside every
    move; the corpus guard is the guard, as in stages 9 to 21."""
    if CORPUS_GUARD is None:
        raise SystemExit("stage 22 needs the corpus guard (--corpus-guard family or run)")
    return stage_n(22, prev, F48_ENUMS, F48_INTS, log, top_k=2, pairs_k=1, sweep=F48_ENUMS,
                   guard=False)


def run_stage(stage: int, prev: dict | None, log=say, grid: str | None = None) -> dict:
    cfg = Config.from_json(prev["config"]) if prev else DEFAULT
    log(f"== stage {stage} ({', '.join(STAGE_FAMILIES[stage])})")
    t0 = time.time()
    cache_clear()
    global CORPUS_REF
    if CORPUS_GUARD is not None:
        CORPUS_REF = cfg                # (WP26) the stage input, before its seed
    if stage == 1:
        out = stage1(cfg, log)
    elif stage == 2:
        out = stage2(cfg, log)
    elif stage == 3:
        out = stage3(prev or {"config": cfg.to_json()}, log)
    elif stage == 4:
        out = stage_n(4, prev, WP32_REVISIT, REG_INTS, log, sweep=STAGE4_SWEEP,
                      sweep_kw=SWEEP_BUDGET[4])
    elif stage == 5:
        seed, record = load_seed(5)
        log(f"  seed {record['file']}: {len(seed)} values")
        seeded = dict(prev, config=Config.from_json(prev["config"]).replace(**seed).to_json())
        # 4608 structures x ~80 integers: two starts, no pair moves (time); then the
        # 24 of IMM_REVISIT around the result
        out = stage_n(5, seeded, MEM_ENUMS, MEM_INTS, log, top_k=2, pairs_k=0)
        out = stage_n(5, out, IMM_REVISIT, MEM_INTS, log, top_k=2, pairs_k=0)
        out = stage_n(5, out, F15_REVISIT, MEM_INTS, log, top_k=2, pairs_k=0)
        out = stage_n(5, out, F16_REVISIT, MEM_INTS, log, top_k=2, pairs_k=0)
        out = stage_n(5, out, EA_REVISIT, MEM_INTS, log, top_k=2, pairs_k=0)
        out = stage_n(5, out, DISP_REVISIT, MEM_INTS, log, top_k=2, pairs_k=0)
        out = stage_n(5, out, FREE_REVISIT, MEM_INTS, log, top_k=2, pairs_k=0)
        out = stage_n(5, out, WP30_REVISIT, MEM_INTS, log, top_k=2, pairs_k=0)
        out = stage_n(5, out, WP31_REVISIT, MEM_INTS, log, top_k=2, pairs_k=0)
        out = stage_n(5, out, WP33_REVISIT, MEM_INTS, log, top_k=2, pairs_k=0)
        out = stage_n(5, out, WP43_REVISIT, MEM_INTS, log, top_k=2, pairs_k=0)
        out = stage_n(5, out, FORM_REVISIT, MEM_INTS, log, top_k=2, pairs_k=0,
                      sweep=STAGE5_SWEEP, sweep_kw=SWEEP_BUDGET[5])
        out["seed"] = record
    elif stage == 6:
        grids = stage6_grids(grid)
        if grid is not None:
            log(f"  resuming at grid {grid}: skipping "
                f"{', '.join(STAGE6_GRID_NAMES[:len(STAGE6_GRIDS) - len(grids)]) or 'none'}")
        out = prev
        for name, enums, kw in grids:
            log(f"  grid {name}: {len(enums)} enums")
            out = stage_n(6, out, enums, [], log, **kw)
        out = polish(out, log)
        if grid is not None:
            out["resumed_at"] = grid
    elif stage == 7:
        out = stage7(prev, log)
    elif stage == 8:
        out = stage8(prev, log)
    elif stage == 9:
        out = stage9(prev, log)
    elif stage == 10:
        out = stage10(prev, log)
    elif stage == 11:
        out = stage11(prev, log)
    elif stage == 12:
        out = stage12(prev, log)
    elif stage == 13:
        out = stage13(prev, log)
    elif stage == 14:
        out = stage14(prev, log)
    elif stage == 15:
        out = stage15(prev, log)
    elif stage == 16:
        out = stage16(prev, log)
    elif stage == 17:
        out = stage17(prev, log)
    elif stage == 18:
        out = stage18(prev, log)
    elif stage == 19:
        out = stage19(prev, log)
    elif stage == 20:
        out = stage20(prev, log)
    elif stage == 21:
        out = stage21(prev, log)
    else:
        out = stage22(prev, log)
    out["seconds"] = round(time.time() - t0, 1)
    n, hits = CACHE_STATS["lookups"], CACHE_STATS["hits"]
    out["cache"] = {"lookups": n, "hits": hits, "simulated": n - hits}
    if CORPUS_GUARD is not None:
        out["corpus_guard"] = dict(CORPUS_STATS, mode=CORPUS_MODE, runs=len(CORPUS_GUARD))
        log(f"  corpus guard: {CORPUS_STATS['refused']} of {CORPUS_STATS['checked']} moves "
            f"refused")
    log(f"  result cache: {hits}/{n} run results reused "
        f"({100 * hits / max(n, 1):.1f}%), {n - hits} simulated")
    path = save(stage, out)
    log(f"  wrote {path} ({out['seconds']}s)")
    return out


# CLI -------------------------------------------------------------------------------

def add_arguments(p):
    p.add_argument("--stage", type=int, choices=range(1, 23), help="run one stage")
    p.add_argument("--to", type=int, choices=range(1, 23), help="with --stage: run stages N..TO")
    p.add_argument("--all", action="store_true", help="run stages 1-22 in order")
    p.add_argument("--from", dest="src", help="previous stage JSON (default: stage N-1's)")
    p.add_argument("--jobs", type=int, default=JOBS)
    p.add_argument("--corpus-guard", choices=("family", "run", "off"), default="family",
                   help="(WP26) accept a move only if no family loses an exact run over every "
                        "recorded family (family: per-family counts; run: every run)")
    p.add_argument("--grid", choices=STAGE6_GRID_NAMES, metavar="NAME",
                   help="stage 6 only: resume at grid NAME, skipping the grids before it "
                        f"({', '.join(STAGE6_GRID_NAMES)})")
    p.add_argument("--cache-limit", type=int, default=CACHE_LIMIT, metavar="N",
                   help="results per result-cache generation (two generations; the cache is "
                        "emptied at every grid); 0 turns the cache off")
    p.add_argument("--write-seeds", action="store_true",
                   help="write the hand read-offs as seed files (seeds/stageN.json) and exit")
    return p


def fit_main(args) -> int:
    global JOBS, CACHE_LIMIT, USE_CACHE
    JOBS = args.jobs
    limit = getattr(args, "cache_limit", None)
    if limit is not None:
        if limit < 0:
            say("--cache-limit must be >= 0")
            return 2
        CACHE_LIMIT = limit
        USE_CACHE = limit > 0
    if getattr(args, "write_seeds", False):
        for path in write_seeds():
            say(f"wrote {path}")
        return 0
    global CORPUS_GUARD, CORPUS_MODE
    mode = getattr(args, "corpus_guard", "off")
    if mode != "off":
        CORPUS_MODE = mode
        CORPUS_GUARD = corpus_guard_ids()
        say(f"corpus guard ({mode}): {len(CORPUS_GUARD)} runs")
    first = args.stage or 1
    stages = range(1, 23) if args.all else range(first, (args.to or first) + 1)
    grid = getattr(args, "grid", None)
    if grid is not None and (args.all or first != 6):
        say("--grid resumes stage 6: give it with --stage 6")
        return 2
    prev = None
    if args.src:
        prev = json.loads(Path(args.src).read_text())
    for stage in stages:
        if prev is None and stage > 1:
            src = OUT_DIR / f"stage{stage - 1}.json"
            if src.exists():
                prev = json.loads(src.read_text())
        prev = run_stage(stage, prev, grid=grid if stage == 6 else None)
    if prev is not None:
        (OUT_DIR / "fit.json").write_text(json.dumps(prev["config"], indent=1, sort_keys=True))
        say(f"wrote {OUT_DIR / 'fit.json'}")
    _close_pool()
    return 0
