"""Offline tests of the staged fitter (fit.py)."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest import mock

from validation.v35s.chains import fit
from validation.v35s.chains.families import FAMILIES, UNMODELLED, generate
from validation.v35s.chains.score import aligned
from validation.v35s.chains.sim.config import DEFAULT
from validation.v35s.chains.sim.machine import simulate_normalized


def _synthetic_runs(truth, families=("F1",), prefix="syn-"):
    """Runs whose 'silicon' is the model under `truth` (ids prefixed to stay apart)."""
    runs = []
    for chain in generate(list(families), waits=(0, 1), parities=("even", "odd")):
        n = simulate_normalized(chain, truth)
        runs.append(fit.Run(prefix + chain.id, chain.family, chain.parity, chain.waits,
                            chain.marker_kind, chain.id, chain.knobs.get("k"), chain, n.chain_base,
                            aligned(n), n.t_fill))
    fit.synthetic(runs)
    return [r.run_id for r in runs]


class StageMachinery(unittest.TestCase):
    """Grid enumeration, scoring and descent recover a known synthetic truth."""

    @classmethod
    def setUpClass(cls):
        cls.jobs = fit.JOBS
        fit.JOBS = 1
        cls.truth = DEFAULT.replace(**{"push.setup": 8, "store.pre": 1})
        cls.ids = _synthetic_runs(cls.truth)
        fit.TIE_IDS = cls.ids

    @classmethod
    def tearDownClass(cls):
        fit.JOBS = cls.jobs
        fit.TIE_IDS = None

    def test_truth_is_exact(self):
        s = fit.score_many([self.truth], self.ids)[0]
        self.assertEqual(s.exact, len(self.ids))
        self.assertEqual(s.resid, 0)

    def test_grid_enumerates_and_filters(self):
        cfgs = fit.grid(DEFAULT, {"room_ir": (False, True), "opcode_take": ("prefetch", "start"),
                                  "opcode_overlap": (0, 1)})
        # overlap=1 only with opcode_take=start: 2 x (1 + 2) combinations
        self.assertEqual(len(cfgs), 6)

    def test_descent_recovers_integers(self):
        start = fit.score_many([DEFAULT], self.ids)[0]
        self.assertLess(start.exact, len(self.ids))
        best = fit.descend(start, ["push.setup", "store.pre"], self.ids)
        self.assertEqual(best.exact, len(self.ids))
        self.assertEqual(fit.getp(best.cfg, "push.setup"), 8)
        self.assertEqual(fit.getp(best.cfg, "store.pre"), 1)

    def test_search_keeps_the_true_structure(self):
        wrong = self.truth.replace(hold_fetch=False)
        best, finals, _ = fit._search([wrong], {"hold_fetch": (True, False)}, ["push.setup"],
                                   self.ids, [], lambda *a: None, top_k=2, label="t")
        self.assertEqual(best.exact, len(self.ids))
        self.assertIs(best.cfg.hold_fetch, True)

    def test_knob_dependence_flags_a_per_knob_value(self):
        # 'silicon' whose push.setup is 8 at waits 0 and 9 at waits 1: the
        # diagnostic must report push.setup as waits-dependent.
        ids = []
        for w, v in ((0, 8), (1, 9)):
            t = DEFAULT.replace(**{"push.setup": v})
            for chain in generate(["F1"], waits=(w,), parities=("even",)):
                if chain.marker_kind != "push":
                    continue
                n = simulate_normalized(chain, t)
                rid = f"kd-{chain.id}"
                fit.synthetic([fit.Run(rid, chain.family, chain.parity, chain.waits,
                                       chain.marker_kind, chain.id, None, chain, n.chain_base,
                                       aligned(n), n.t_fill)])
                ids.append(rid)
        found = fit.knob_dependence(DEFAULT.replace(**{"push.setup": 8}), ["push.setup"], ids,
                                    log=lambda *a: None)
        self.assertIn("push.setup", found)
        self.assertEqual({k: v[0] for k, v in found["push.setup"]["waits"].items()},
                         {"0": 8, "1": 9})

    def test_diff_cfg(self):
        b = DEFAULT.replace(room_ir=True, **{"out.nx": 4})
        self.assertEqual(fit.diff_cfg(DEFAULT, b), {"room_ir": True, "out.nx": 4})


class JointMoves(unittest.TestCase):
    """The enum sweep (integers descended inside every enum move) and the tie-break."""

    @classmethod
    def setUpClass(cls):
        cls.jobs = fit.JOBS
        fit.JOBS = 1
        cls.truth = DEFAULT.replace(write_wait="end", **{"push.setup": 8, "store.pre": 1})
        cls.ids = _synthetic_runs(cls.truth, prefix="joint-")
        fit.TIE_IDS = cls.ids

    @classmethod
    def tearDownClass(cls):
        fit.JOBS = cls.jobs
        fit.TIE_IDS = None

    def test_sweep_moves_an_enum_with_its_integers(self):
        start = fit.score_many([DEFAULT], self.ids)[0]
        best, rec = fit.enum_sweep(start, {"write_wait": ("issue", "end", "mem_end")},
                                   ["push.setup", "store.pre"], self.ids, [],
                                   log=lambda *a: None)
        self.assertEqual(best.exact, len(self.ids))
        self.assertEqual(best.cfg.write_wait, "end")
        self.assertEqual(fit.getp(best.cfg, "push.setup"), 8)
        self.assertEqual(rec["moves"][0]["enum"], "write_wait")

    def test_group_grid_moves_coupled_values_with_integers(self):
        # no single alternative (enums {}): the group's grid, descended inside, finds it
        start = fit.score_many([DEFAULT], self.ids)[0]
        best, rec = fit.enum_sweep(start, {}, ["push.setup", "store.pre"], self.ids, [],
                                   log=lambda *a: None,
                                   groups={"g": {"write_wait": ("issue", "end", "mem_end"),
                                                 "hold_run": (False, True)}})
        self.assertEqual(best.exact, len(self.ids))
        self.assertEqual(best.cfg.write_wait, "end")
        self.assertEqual(rec["moves"][0]["enum"], "g")

    def test_inert_enum_is_recorded_as_a_tie(self):
        # no F1 chain reads a refresh option with refresh off: a tie, not a move
        start = fit.score_many([self.truth], self.ids)[0]
        best, rec = fit.enum_sweep(start, {"refresh_mul": ("plain", "loop")}, ["push.setup"],
                                   self.ids, [], log=lambda *a: None)
        self.assertEqual(best.cfg.refresh_mul, "plain")
        self.assertEqual([t["value"] for t in rec["ties"]], ["loop"])
        self.assertTrue(rec["ties"][0]["inert"])

    def test_tie_families_are_every_family(self):
        # the tie-break counts exact runs over every family, in FAMILIES order (F13, F17
        # and F18, the refresh-on families, were once left out of an explicit list)
        self.assertEqual(fit.TIE_FAMILIES, list(FAMILIES))

    def test_pick_breaks_a_tie_on_every_family(self):
        a = fit.score_many([self.truth], self.ids[:4])[0]
        b = fit.score_many([self.truth.replace(**{"push.setup": 6})], self.ids[:4])[0]
        a.guard = b.guard = 0
        a.exact = b.exact = 1          # forced tie on the stage's exact runs
        best, ties = fit.pick([b, a])
        self.assertIs(best, a)         # the truth gets every recorded run
        self.assertEqual(len(ties), 1)
        self.assertEqual(ties[0]["chosen_all_exact"], len(self.ids))


class CorpusGuard(unittest.TestCase):
    """(WP26) The whole-corpus guard: a move of the descent, the enum sweep or the stage grid
    is accepted only if no family of the guard corpus loses an exact run."""

    @classmethod
    def setUpClass(cls):
        cls.jobs = fit.JOBS
        fit.JOBS = 1
        # a stage family whose 'silicon' wants push.setup 8, one that wants write_wait=end,
        # and a family outside the stage recorded with the defaults
        cls.goal = DEFAULT.replace(**{"push.setup": 8})
        cls.goal_enum = DEFAULT.replace(write_wait="end")
        cls.stage = cls._runs(cls.goal, "SYNA", "cga-")
        cls.stage_enum = cls._runs(cls.goal_enum, "SYNC", "cgc-")
        cls.other = cls._runs(DEFAULT, "SYNB", "cgb-")
        fit.TIE_IDS = cls.stage

    @staticmethod
    def _runs(truth, family, prefix):
        runs = []
        for chain in generate(["F1"], waits=(0,), parities=("even", "odd")):
            if chain.marker_kind != "push":
                continue
            n = simulate_normalized(chain, truth)
            runs.append(fit.Run(prefix + chain.id, family, chain.parity, chain.waits,
                                chain.marker_kind, chain.id, chain.knobs.get("k"), chain,
                                n.chain_base, aligned(n), n.t_fill))
        fit.synthetic(runs)
        return [r.run_id for r in runs]

    @classmethod
    def tearDownClass(cls):
        fit.JOBS = cls.jobs
        fit.TIE_IDS = None
        fit.CORPUS_GUARD = None
        fit.CORPUS_MODE = "family"
        fit.CORPUS_REF = None

    def tearDown(self):
        fit.CORPUS_GUARD = None
        fit.CORPUS_MODE = "family"
        fit.CORPUS_REF = None

    def test_a_family_may_recover_up_to_the_stage_input(self):
        # the stage input is the goal; a seed moved the start to the default, where SYNB is
        # exact and SYNA is not: moving back loses SYNB against the start, but SYNB stays at
        # its count in the input (0), so the move is admissible; below the input it is not
        fit.CORPUS_GUARD = self.stage + self.other
        self.assertFalse(fit.corpus_ok(DEFAULT, self.goal))
        fit.CORPUS_REF = self.goal
        self.assertTrue(fit.corpus_ok(DEFAULT, self.goal))
        fit.CORPUS_REF = DEFAULT
        self.assertFalse(fit.corpus_ok(DEFAULT, self.goal))
        fit.CORPUS_MODE = "run"
        fit.CORPUS_REF = self.goal
        self.assertTrue(fit.corpus_ok(DEFAULT, self.goal))

    def test_losses_are_counted_per_family(self):
        fit.CORPUS_GUARD = self.stage + self.other
        lost = fit.corpus_losses(DEFAULT, self.goal)
        self.assertEqual(lost, {"SYNB": len(self.other)})
        self.assertFalse(fit.corpus_ok(DEFAULT, self.goal))
        self.assertTrue(fit.corpus_ok(DEFAULT, DEFAULT))
        self.assertEqual(fit.corpus_losses(self.goal, DEFAULT), {"SYNA": len(self.stage)})

    def test_descent_without_guard_trades_the_other_family(self):
        start = fit.score_many([DEFAULT], self.stage)[0]
        best = fit.descend(start, ["push.setup"], self.stage)
        self.assertEqual(fit.getp(best.cfg, "push.setup"), 8)
        self.assertEqual(best.exact, len(self.stage))

    def test_descent_refuses_a_move_that_loses_a_family(self):
        fit.CORPUS_GUARD = self.stage + self.other
        start = fit.score_many([DEFAULT], self.stage)[0]
        best = fit.descend(start, ["push.setup"], self.stage)
        self.assertNotEqual(fit.getp(best.cfg, "push.setup"), 8)
        self.assertFalse(fit.corpus_losses(start.cfg, best.cfg))

    def test_enum_sweep_refuses_an_enum_that_loses_a_family(self):
        start = fit.score_many([DEFAULT], self.stage_enum)[0]
        enums = {"write_wait": ("issue", "end", "mem_end")}
        free, _ = fit.enum_sweep(start, enums, ["push.setup"], self.stage_enum, [],
                                 log=lambda *a: None)
        self.assertEqual(free.cfg.write_wait, "end")
        fit.CORPUS_GUARD = self.stage_enum + self.other
        held, rec = fit.enum_sweep(start, enums, ["push.setup"], self.stage_enum, [],
                                   log=lambda *a: None)
        self.assertFalse(fit.corpus_losses(DEFAULT, held.cfg))
        self.assertEqual(held.cfg.write_wait, DEFAULT.write_wait)
        self.assertEqual(rec["moves"], [])

    def test_search_refuses_a_grid_start_that_loses_a_family(self):
        fit.CORPUS_GUARD = self.stage_enum + self.other
        best, finals, _ = fit._search([DEFAULT], {"write_wait": ("issue", "end")}, [],
                                      self.stage_enum, [], lambda *a: None, top_k=2,
                                      label="t")
        self.assertEqual(best.cfg.write_wait, DEFAULT.write_wait)
        self.assertTrue(all(f.cfg.write_wait == DEFAULT.write_wait for f in finals))

    def test_family_mode_allows_a_trade_inside_a_family_run_mode_does_not(self):
        # one family label over both halves: the move to the goal gains as many runs of
        # it as it loses
        fit.CORPUS_GUARD = self.stage + self.other
        for i in self.stage + self.other:
            fit._DATA[i].family = "SYNX"
        fit.cache_clear()
        try:
            self.assertTrue(fit.corpus_ok(DEFAULT, self.goal))
            fit.CORPUS_MODE = "run"
            self.assertFalse(fit.corpus_ok(DEFAULT, self.goal))
        finally:
            for i in self.stage:
                fit._DATA[i].family = "SYNA"
            for i in self.other:
                fit._DATA[i].family = "SYNB"
            fit.cache_clear()


class Seeds(unittest.TestCase):
    """Seeds are data files (fit/seeds/stageN.json) that every stage records."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.out = fit.OUT_DIR
        fit.OUT_DIR = Path(self.tmp.name)

    def tearDown(self):
        fit.OUT_DIR = self.out
        self.tmp.cleanup()

    def test_missing_seed_is_no_seed(self):
        # from scratch: without a seed file a stage starts from the previous stage's output
        for stage in (2, 3, 5, 8):
            values, record = fit.load_seed(stage)
            self.assertEqual(values, {})
            self.assertIsNone(record["file"])
        self.assertFalse(fit.seeds_dir().exists())

    def test_write_seeds_is_opt_in(self):
        fit.write_seeds()
        values, record = fit.load_seed(3)
        self.assertEqual(values, json.loads(json.dumps(fit.STAGE3_SEED)))
        self.assertEqual(fit.load_seed(8)[0], fit.REFRESH_SEED)
        self.assertEqual(record["values"], values)

    def test_seed_file_overrides_the_defaults(self):
        fit.seeds_dir().mkdir(parents=True)
        (fit.seeds_dir() / "stage2.json").write_text(json.dumps({"word_latch": "byte"}))
        values, record = fit.load_seed(2)
        self.assertEqual(values, {"word_latch": "byte"})
        self.assertTrue(record["file"].endswith("stage2.json"))

    def test_stage2_records_its_seed(self):
        # a one-structure grid: the payload carries the seed it was built on
        jobs, fit.JOBS = fit.JOBS, 1
        try:
            ids = fit.load(["F0"])
        except FileNotFoundError:
            raise unittest.SkipTest("no F0 corpus entries")
        finally:
            fit.JOBS = jobs
        jobs, fit.JOBS = fit.JOBS, 1
        try:
            out = fit.stage2(DEFAULT, log=lambda *a: None,
                             options={"room_ir": ("arrival_idle",)}, seed=fit.STAGE2_SEED)
        finally:
            fit.JOBS = jobs
        self.assertEqual(out["seed"]["values"], fit.STAGE2_SEED)
        self.assertEqual(fit.Config.from_json(out["base"]).word_latch, "byte_d")

    def test_release_criterion_selects_f2_f9_push(self):
        truth = DEFAULT
        ids = _synthetic_runs(truth, families=("F2", "F1"), prefix="crit-")
        crit = fit._criterion_ids(ids)
        self.assertTrue(crit)
        self.assertTrue(all(fit._DATA[i].family == "F2" and fit._DATA[i].marker == "push"
                            for i in crit))


class CacheAndGrids(unittest.TestCase):
    """The result cache's limit and per-grid reset, and stage 6's resumable grid sequence."""

    NAMES = ["ARB_ENUMS", "QUEUE_REVISIT", "STORAGE_REVISIT", "IO_REVISIT",
             "IO_FOLLOWER_REVISIT", "OUT_REVISIT", "OUT_REVISIT2", "F20_REVISIT",
             "WP32_REVISIT", "WP33_STAGE6", "LATCH_REVISIT"]

    def setUp(self):
        self.saved = (fit.CACHE_LIMIT, fit.USE_CACHE, fit.JOBS, fit.CORPUS_GUARD)

    def tearDown(self):
        fit.CACHE_LIMIT, fit.USE_CACHE, fit.JOBS, fit.CORPUS_GUARD = self.saved

    def _args(self, *argv):
        import argparse
        return fit.add_arguments(argparse.ArgumentParser()).parse_args(list(argv))

    def test_grid_sequence_order(self):
        self.assertEqual(fit.STAGE6_GRID_NAMES, self.NAMES)
        self.assertIs({n: e for n, e, _ in fit.STAGE6_GRIDS}["STORAGE_REVISIT"], fit.STORAGE_REVISIT)
        kw = fit.STAGE6_GRIDS[-1][2]
        self.assertIs(kw["sweep"], fit.STAGE6_SWEEP)
        self.assertEqual(kw["sweep_kw"], fit.SWEEP_BUDGET[6])
        self.assertTrue(all(not g[2] for g in fit.STAGE6_GRIDS[:-1]))

    def test_grid_option_selects_from_storage_revisit(self):
        args = self._args("--stage", "6", "--grid", "STORAGE_REVISIT")
        self.assertEqual(args.grid, "STORAGE_REVISIT")
        grids = fit.stage6_grids(args.grid)
        self.assertEqual(grids, fit.STAGE6_GRIDS[2:])
        self.assertEqual([g[0] for g in grids], self.NAMES[2:])
        self.assertEqual(fit.stage6_grids(None), fit.STAGE6_GRIDS)
        with self.assertRaises(ValueError):
            fit.stage6_grids("NOPE")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self._args("--stage", "6", "--grid", "NOPE")

    def test_grid_resume_calls_stage_n_as_the_full_run(self):
        calls = []

        def fake_stage_n(stage, prev, enums, ints, log=None, **kw):
            calls.append((stage, prev["config"], enums, ints, kw))
            return {"config": prev["config"]}

        cfg = DEFAULT.to_json()
        with mock.patch.object(fit, "stage_n", fake_stage_n), \
             mock.patch.object(fit, "polish", lambda out, log: dict(out)), \
             mock.patch.object(fit, "save", lambda stage, out: "x"):
            fit.run_stage(6, {"config": cfg}, log=lambda *a: None)
            full = list(calls)
            calls.clear()
            fit.run_stage(6, {"config": cfg}, log=lambda *a: None, grid="STORAGE_REVISIT")
        self.assertEqual(len(full), 11)
        self.assertEqual(calls, full[2:])

    def test_grid_with_another_stage_is_refused(self):
        args = self._args("--stage", "5", "--grid", "IO_REVISIT", "--corpus-guard", "off")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fit.fit_main(args), 2)

    def test_cache_limit_option(self):
        self.assertEqual(self._args().cache_limit, 3_000_000)
        args = self._args("--stage", "7", "--grid", "IO_REVISIT", "--corpus-guard", "off",
                          "--cache-limit", "12345")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            fit.fit_main(args)              # refused (--grid with stage 7) after the limit
        self.assertEqual(fit.CACHE_LIMIT, 12345)
        self.assertTrue(fit.USE_CACHE)
        args = self._args("--stage", "7", "--grid", "IO_REVISIT", "--corpus-guard", "off",
                          "--cache-limit", "0")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            fit.fit_main(args)
        self.assertFalse(fit.USE_CACHE)

    def test_cache_holds_at_most_twice_the_limit(self):
        # one entry per signature grows in place across structures (fixed integers): the
        # flush keeps both generations together within 2 * CACHE_LIMIT results
        fit.JOBS = 1
        ids = _synthetic_runs(DEFAULT, prefix="bound-")
        cfgs = [DEFAULT.replace(**{"push.setup": v}) for v in range(2, 10)]
        fit.cache_clear()
        fit.CACHE_LIMIT = 10 ** 9
        first = fit.evaluate(cfgs, ids)
        total = fit.cache_size()
        fit.cache_clear()
        fit.CACHE_LIMIT = total // 6
        self.assertEqual(fit.evaluate(cfgs, ids), first)
        self.assertLessEqual(fit.cache_size(), 2 * fit.CACHE_LIMIT)
        self.assertEqual(fit.cache_size(), fit._CACHE_COUNT + fit._CACHE_OLD_COUNT)
        self.assertGreater(fit._CACHE_FLUSHES, 0)

    def test_cache_reset_and_clear_empty_both_generations(self):
        fit.JOBS = 1
        ids = _synthetic_runs(DEFAULT, prefix="cache-")
        fit.cache_clear()
        fit.CACHE_LIMIT = len(ids) // 2 + 1  # rotates once: both generations fill, no flush
        fit.evaluate([DEFAULT], ids)
        self.assertTrue(fit._CACHE_NEW and fit._CACHE_OLD)
        self.assertEqual(fit._CACHE_FLUSHES, 0)
        self.assertGreater(fit.cache_size(), 0)
        fit._CORPUS_MEMO["x"] = frozenset()
        fit._TB["x"] = (0, 0)
        self.assertTrue(fit._RESULTS)
        stats = dict(fit.CACHE_STATS)
        fit.cache_reset()
        self.assertEqual((fit._CACHE_NEW, fit._CACHE_OLD, fit._CACHE_COUNT,
                          fit._CACHE_OLD_COUNT), ({}, {}, 0, 0))
        self.assertEqual((fit._CORPUS_MEMO, fit._TB, fit._RESULTS), ({}, {}, {}))
        self.assertEqual(fit.CACHE_STATS, stats)     # a stage's totals span its grids
        self.assertEqual(fit.cache_size(), 0)
        fit.evaluate([DEFAULT], ids)
        fit.cache_clear()
        self.assertEqual((fit._CACHE_NEW, fit._CACHE_OLD, fit._CACHE_COUNT,
                          fit._CACHE_OLD_COUNT), ({}, {}, 0, 0))
        self.assertEqual(fit.CACHE_STATS, {"lookups": 0, "hits": 0})


class RunClassesPreludeTail(unittest.TestCase):
    """run_classes decodes from the prelude's tail, which the machine runs before the
    chain (prelude_tail != standin): its MOV r16,imm16 (imm), MOV sreg,AW (reg) and the
    prelude marker are in the projection key."""

    def test_f0_has_tail_classes(self):
        chain = next(c for c in generate(["F0"]) if c.parity == "even")
        classes, _ = fit.run_classes(chain)
        self.assertIn("reg", classes)
        self.assertIn("imm", classes)

    def test_f18_has_marker_class(self):
        from validation.v35s.chains.image import PRELUDE_MARKERS
        from validation.v35s.chains.sim.templates import decode
        seen = set()
        for chain in generate(["F18"]):
            marker = getattr(chain, "prelude_marker", None)
            if marker is None or marker in seen:
                continue
            seen.add(marker)
            cls = decode(PRELUDE_MARKERS[marker][1], 0, dict(chain.regs)).cls
            self.assertIn(cls, fit.run_classes(chain)[0], (chain.id, marker))
        self.assertEqual(seen, set(PRELUDE_MARKERS))


class FittedConfig(unittest.TestCase):
    """Regression: the fitted config keeps every F0 run exact."""

    def test_fit_json_keeps_f0(self):
        try:
            ids = fit.load(["F0"])
        except FileNotFoundError:
            raise unittest.SkipTest("no F0 corpus entries")
        cfg = fit.Config.fitted()
        jobs, fit.JOBS = fit.JOBS, 1
        try:
            s = fit.score_many([cfg], ids)[0]
        finally:
            fit.JOBS = jobs
        self.assertEqual(s.exact, 18)

    def test_fit_json_never_overfills(self):
        # The fitted request rule keeps the queue within its six bytes on every chain.
        from validation.v35s.chains.sim.machine import Machine
        from validation.v35s.chains.sim.queue import QUEUE_BYTES
        cfg = fit.Config.fitted()
        peak = 0
        for chain in generate([f for f in FAMILIES if f not in UNMODELLED], waits=(0, 2)):
            m = Machine(chain, cfg)
            m.run()                      # raises sim.queue.QueueOverflow on an over-fill
            peak = max(peak, m.queue.peak)
        self.assertLessEqual(peak, QUEUE_BYTES)


if __name__ == "__main__":
    unittest.main()


class StringStage(unittest.TestCase):
    """(WP67) stage 13: F24's string templates, the corpus guard as its guard."""

    def test_stage_13_is_f24(self):
        from validation.v35s.chains.sim.config import DEFAULT_COST, OPTIONS
        self.assertEqual(fit.STAGE_FAMILIES[13], ["F24"])
        self.assertNotIn("F24", UNMODELLED)
        self.assertEqual(set(fit.F24_ENUMS), {"str_take", "str_setup", "str_overrun", "str_hold",
                                              "str_last", "str_io_latch", "str_count"})
        for name, values in fit.F24_ENUMS.items():
            self.assertEqual(values, OPTIONS[name])
        classes = {p.split(".")[0] for p in fit.F24_INTS}
        self.assertEqual(classes, {"str_move", "str_cmp", "str_store", "str_load",
                                   "str_scan", "str_in", "str_out"})
        for p in fit.F24_INTS:
            cls, name = p.split(".")
            self.assertTrue(name in DEFAULT_COST[cls] or name == "nx", p)

    def test_stage_13_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage13({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_13_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage13({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 13)
        self.assertEqual(args[2], fit.F24_ENUMS)
        self.assertEqual(args[3], fit.F24_INTS)
        self.assertEqual(kw["sweep"], fit.F24_ENUMS)
        self.assertFalse(kw["guard"])

    def test_cli_accepts_stage_13(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "13"])
        self.assertEqual(args.stage, 13)


class TransferFrameStage(unittest.TestCase):
    """(WP72) stage 14: F23's and F25's misses of the thirty-ninth fit, the corpus guard as
    its guard."""

    def test_stage_14_is_f23_f25(self):
        from validation.v35s.chains.sim.config import OPTIONS
        self.assertEqual(fit.STAGE_FAMILIES[14], ["F23", "F25"])
        self.assertEqual(set(fit.F40_ENUMS), {"xfer_abort", "cond_gap", "burst_count", "lea_io",
                                              "lea_room", "prepare_sync"})
        self.assertEqual(set(fit.F40_SWEEP), set(fit.F40_ENUMS) | {"imm_latch"})
        for name, values in fit.F40_SWEEP.items():
            self.assertEqual(values, OPTIONS[name])
            self.assertEqual(getattr(DEFAULT, name), values[0], name)
        for p in ("branch_short.cfgap", "prepare.wb"):
            self.assertIn(p, fit.F40_INTS)
        self.assertTrue(set(fit.F23_INTS) <= set(fit.F40_INTS))
        self.assertTrue(set(fit.F25_INTS) <= set(fit.F40_INTS))

    def test_stage_14_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage14({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_14_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage14({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 14)
        self.assertEqual(args[2], fit.F40_ENUMS)
        self.assertEqual(args[3], fit.F40_INTS)
        self.assertEqual(kw["sweep"], fit.F40_SWEEP)
        self.assertFalse(kw["guard"])

    def test_cli_accepts_stage_14(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "14"])
        self.assertEqual(args.stage, 14)


class ProbeShapesStage(unittest.TestCase):
    """(WP76) stage 15: F30's and F31's readings as mechanisms (with F24, F23, F25), the corpus
    guard as its guard."""

    def test_stage_15_families_and_enums(self):
        from validation.v35s.chains.sim.config import OPTIONS
        self.assertEqual(fit.STAGE_FAMILIES[15], ["F30", "F31", "F24", "F23", "F25"])
        self.assertEqual(set(fit.F41_ENUMS), {"xfer_odd", "str_exit", "str_split",
                                              "str_io_setup", "str_start", "str_fetch",
                                              "sreg_io", "sreg_store", "lea_disp"})
        for name, values in fit.F41_ENUMS.items():
            self.assertEqual(values, OPTIONS[name])
            self.assertEqual(getattr(DEFAULT, name), values[0], name)
        for p in ("str_move.xwb", "str_cmp.xsplit", "str_store.xfetch", "str_out.zfetch",
                  "str_out.nx", "branch_short.hold", "lea.nx"):
            self.assertIn(p, fit.F41_INTS)

    def test_stage_15_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage15({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_15_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage15({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 15)
        self.assertEqual(args[2], fit.F41_ENUMS)
        self.assertEqual(args[3], fit.F41_INTS)
        self.assertEqual(kw["sweep"], fit.F41_ENUMS)
        self.assertFalse(kw["guard"])

    def test_cli_accepts_stage_15(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "15"])
        self.assertEqual(args.stage, 15)


class PageMiscStage(unittest.TestCase):
    """(WP78) stage 16: F32's 0F page and F33's register miscellany, the corpus guard as its
    guard."""

    def test_stage_16_families_enums_and_integers(self):
        from validation.v35s.chains.sim.config import DEFAULT_COST, OPTIONS
        self.assertEqual(fit.STAGE_FAMILIES[16], ["F32", "F33"])
        self.assertNotIn("F32", UNMODELLED)
        self.assertNotIn("F33", UNMODELLED)
        for name, values in fit.F42_ENUMS.items():
            self.assertEqual(values, OPTIONS[name])
            self.assertEqual(getattr(DEFAULT, name), values[0], name)
        for cls in fit.F42_CLASSES:
            self.assertIn(cls, DEFAULT_COST, cls)
            for name in DEFAULT_COST[cls]:
                self.assertIn(f"{cls}.{name}", fit.F42_INTS)
        for p in ("mul.sexec", "div.sexec", "incdec.nx0", "bf_ext.span", "bcd4s.wmid"):
            self.assertIn(p, fit.F42_INTS)
        # no integer of an existing class other than the signed register forms' sexec
        old = {p.split(".")[0] for p in fit.F42_INTS} - set(fit.F42_CLASSES)
        self.assertEqual(old, {"mul", "div"})

    def test_stage_16_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage16({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_16_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage16({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 16)
        self.assertEqual(args[2], fit.F42_ENUMS)
        self.assertEqual(args[3], fit.F42_INTS)
        self.assertEqual(kw["sweep"], fit.F42_ENUMS or None)
        self.assertFalse(kw["guard"])

    def test_cli_accepts_stage_16(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "16"])
        self.assertEqual(args.stage, 16)
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(
            ["--stage", "15", "--to", "16"])
        self.assertEqual(args.to, 16)

    def test_corpus_guard_covers_f32_f33(self):
        with mock.patch.object(fit, "load", side_effect=lambda fams: list(fams)):
            ids = fit.corpus_guard_ids()
        self.assertIn("F32", ids)
        self.assertIn("F33", ids)


class MissShapeStage(unittest.TestCase):
    """(WP81) stage 17: F34's readings as mechanisms over F32, F33 and F34, the corpus guard as
    its guard."""

    def test_stage_17_families_enums_and_integers(self):
        from validation.v35s.chains.sim.config import DEFAULT_COST, OPTIONS
        self.assertEqual(fit.STAGE_FAMILIES[17], ["F32", "F33", "F34"])
        self.assertNotIn("F34", UNMODELLED)
        for name, values in fit.F43_ENUMS.items():
            self.assertEqual(values, OPTIONS[name])
            self.assertEqual(getattr(DEFAULT, name), values[0], name)
        for cls in fit.F43_CLASSES:
            for name in DEFAULT_COST[cls]:
                self.assertIn(f"{cls}.{name}", fit.F43_INTS)
        for p in ("branch_short.nhold", "dbnz.nhold", "branch_short.wb", "dbnz.wb",
                  "bit1_test.fsetup", "bf_ext.fsetup", "mul_imm.mhold", "mul_imm.rsetup",
                  "ret.setup", "incdec.wb"):
            self.assertIn(p, fit.F43_INTS)

    def test_stage_17_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage17({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_17_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage17({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 17)
        self.assertEqual(args[2], fit.F43_ENUMS)
        self.assertEqual(args[3], fit.F43_INTS)
        self.assertEqual(kw["sweep"], fit.F43_ENUMS)
        self.assertFalse(kw["guard"])

    def test_cli_accepts_stage_17(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "17"])
        self.assertEqual(args.stage, 17)
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(
            ["--stage", "16", "--to", "17"])
        self.assertEqual(args.to, 17)

    def test_run_stage_dispatches_17(self):
        with mock.patch.object(fit, "stage17", return_value={"config": {}}) as s17, \
                mock.patch.object(fit, "save", return_value="x"), \
                mock.patch.object(fit, "CORPUS_GUARD", None):
            fit.run_stage(17, {"config": DEFAULT.to_json()}, log=lambda *a: None)
        s17.assert_called_once()


class PageFormStage(unittest.TestCase):
    """(WP86) stage 20: the 0F forms' register-form run and memory-form refill over F32, F33 and
    F34, every integer of the 0F classes, the corpus guard as its guard."""

    def test_stage_20_families_enums_and_integers(self):
        from validation.v35s.chains.sim.config import DEFAULT_COST, OPTIONS
        self.assertEqual(fit.STAGE_FAMILIES[20], ["F32", "F33", "F34"])
        self.assertEqual(set(fit.F46_ENUMS), {"page_b2b", "page_run"})
        for name, values in fit.F46_ENUMS.items():
            self.assertEqual(values, OPTIONS[name])
            # the old value first (DEFAULT): a tie keeps it
            self.assertEqual(getattr(DEFAULT, name), values[0], name)
        for cls in fit.F46_CLASSES:
            for name in DEFAULT_COST[cls]:
                self.assertIn(f"{cls}.{name}", fit.F46_INTS)
        for p in ("bf_ins.xwsetup", "bf_ins.xrsetup", "bf_ins.xspan", "bit1.exec",
                  "bit1_rmw.fsetup", "mul_imm.rsetup"):
            self.assertIn(p, fit.F46_INTS)

    def test_stage_20_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage20({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_20_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage20({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 20)
        self.assertEqual(args[2], fit.F46_ENUMS)
        self.assertEqual(args[3], fit.F46_INTS)
        self.assertEqual(kw["sweep"], fit.F46_ENUMS)
        self.assertFalse(kw["guard"])

    def test_cli_accepts_stage_20(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "20"])
        self.assertEqual(args.stage, 20)
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(
            ["--stage", "19", "--to", "20"])
        self.assertEqual(args.to, 20)

    def test_run_stage_dispatches_20(self):
        with mock.patch.object(fit, "stage20", return_value={"config": {}}) as s20, \
                mock.patch.object(fit, "stage19") as s19, \
                mock.patch.object(fit, "save", return_value="x"), \
                mock.patch.object(fit, "CORPUS_GUARD", None):
            fit.run_stage(20, {"config": DEFAULT.to_json()}, log=lambda *a: None)
        s20.assert_called_once()
        s19.assert_not_called()


class RefreshSequencerStage(unittest.TestCase):
    """(WP85) stage 19: the I/O sequencer's rules beside a refresh over F27 and F28 (with F8, F13,
    F17, F18), the corpus guard as its guard."""

    NAMES = {"port_ready_count", "port_refresh", "refresh_pair_post", "io_step_restart",
             "refresh_lead_step"}

    def test_stage_19_families_enums_and_integers(self):
        from validation.v35s.chains.sim.config import OPTIONS
        self.assertEqual(fit.STAGE_FAMILIES[19], ["F27", "F28", "F8", "F13", "F17", "F18"])
        self.assertEqual(set(fit.F45_ENUMS), self.NAMES)
        for name, values in fit.F45_ENUMS.items():
            self.assertEqual(values, OPTIONS[name])
            # the old value first (DEFAULT): a tie keeps it
            self.assertEqual(getattr(DEFAULT, name), values[0], name)
        self.assertEqual(fit.F45_INTS, ["out.relatch", "out.lead", "in.relatch"])
        from validation.v35s.chains.sim.config import Config
        for p in fit.F45_INTS:
            cls, name = p.split(".")
            self.assertIn(name, Config.fitted().cost[cls])

    def test_stage_19_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage19({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_19_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage19({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 19)
        self.assertEqual(args[2], fit.F45_ENUMS)
        self.assertEqual(args[3], fit.F45_INTS)
        self.assertEqual(kw["sweep"], fit.F45_ENUMS)
        self.assertFalse(kw["guard"])

    def test_cli_accepts_stage_19(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "19"])
        self.assertEqual(args.stage, 19)
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(
            ["--stage", "18", "--to", "19"])
        self.assertEqual(args.to, 19)

    def test_run_stage_dispatches_19(self):
        with mock.patch.object(fit, "stage19", return_value={"config": {}}) as s19, \
                mock.patch.object(fit, "stage18") as s18, \
                mock.patch.object(fit, "save", return_value="x"), \
                mock.patch.object(fit, "CORPUS_GUARD", None):
            fit.run_stage(19, {"config": DEFAULT.to_json()}, log=lambda *a: None)
        s19.assert_called_once()
        s18.assert_not_called()


class CausalRefreshStage(unittest.TestCase):
    """(WP84) stage 18: refresh_scope over F17 and F18, the corpus guard as its guard."""

    def test_stage_18_families_enums_and_integers(self):
        from validation.v35s.chains.sim.config import OPTIONS
        self.assertEqual(fit.STAGE_FAMILIES[18], ["F17", "F18"])
        self.assertEqual(set(fit.F44_ENUMS), {"refresh_scope"})
        for name, values in fit.F44_ENUMS.items():
            self.assertEqual(set(values), set(OPTIONS[name]))
            self.assertEqual(getattr(DEFAULT, name), OPTIONS[name][0], name)
        # the causal structure first: a tie keeps it (the grid's stable sort)
        self.assertEqual(fit.F44_ENUMS["refresh_scope"][0], "live")
        self.assertEqual(DEFAULT.refresh_scope, "any")
        self.assertEqual(fit.F44_INTS, ["rfm_delay"])

    def test_stage_18_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage18({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_18_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage18({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 18)
        self.assertEqual(args[2], fit.F44_ENUMS)
        self.assertEqual(args[3], fit.F44_INTS)
        self.assertEqual(kw["sweep"], fit.F44_ENUMS)
        self.assertFalse(kw["guard"])

    def test_grid_lists_live_first(self):
        cands = fit.grid(DEFAULT, fit.F44_ENUMS)
        self.assertEqual([c.refresh_scope for c in cands], ["live", "any"])

    def test_cli_accepts_stage_18(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "18"])
        self.assertEqual(args.stage, 18)
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(
            ["--stage", "17", "--to", "18"])
        self.assertEqual(args.to, 18)

    def test_run_stage_dispatches_18(self):
        with mock.patch.object(fit, "stage18", return_value={"config": {}}) as s18, \
                mock.patch.object(fit, "stage17") as s17, \
                mock.patch.object(fit, "save", return_value="x"), \
                mock.patch.object(fit, "CORPUS_GUARD", None):
            fit.run_stage(18, {"config": DEFAULT.to_json()}, log=lambda *a: None)
        s18.assert_called_once()
        s17.assert_not_called()


class CoverageClassStage(unittest.TestCase):
    """(WP88) stage 21: the F35 / F36 classes (every integer of the new classes) and RET imm16's
    fetch hold over F35 and F36, the corpus guard as its guard."""

    def test_stage_21_families_enums_and_integers(self):
        from validation.v35s.chains.sim.config import DEFAULT_COST, OPTIONS
        from validation.v35s.chains.sim.templates import BASE_CLASS
        self.assertEqual(fit.STAGE_FAMILIES[21], ["F35", "F36"])
        self.assertEqual(set(fit.F47_ENUMS), {"ret_imm_hold"})
        for name, values in fit.F47_ENUMS.items():
            self.assertEqual(values, OPTIONS[name])
            # the old value first (DEFAULT): a tie keeps it
            self.assertEqual(getattr(DEFAULT, name), values[0], name)
        for cls in fit.F47_CLASSES:
            self.assertIn(cls, BASE_CLASS)          # each on an existing class's structure
            for name in DEFAULT_COST[cls]:
                self.assertIn(f"{cls}.{name}", fit.F47_INTS)
        # no earlier class's integer: the stage reads only the new classes
        self.assertFalse({p.split(".")[0] for p in fit.F47_INTS} - set(fit.F47_CLASSES))
        for p in ("bcwz.exec", "dbnz_z.zexec", "ret_imm.mhold", "call_far.wsetup",
                  "load_ptr.phold", "test_reg.pre"):
            self.assertIn(p, fit.F47_INTS)

    def test_stage_21_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage21({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_21_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage21({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 21)
        self.assertEqual(args[2], fit.F47_ENUMS)
        self.assertEqual(args[3], fit.F47_INTS)
        self.assertEqual(kw["sweep"], fit.F47_ENUMS)
        self.assertFalse(kw["guard"])

    def test_cli_accepts_stage_21(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "21"])
        self.assertEqual(args.stage, 21)
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(
            ["--stage", "20", "--to", "21"])
        self.assertEqual(args.to, 21)

    def test_run_stage_dispatches_21(self):
        with mock.patch.object(fit, "stage21", return_value={"config": {}}) as s21, \
                mock.patch.object(fit, "stage20") as s20, \
                mock.patch.object(fit, "save", return_value="x"), \
                mock.patch.object(fit, "CORPUS_GUARD", None):
            fit.run_stage(21, {"config": DEFAULT.to_json()}, log=lambda *a: None)
        s21.assert_called_once()
        s20.assert_not_called()


class NotTakenB2BStage(unittest.TestCase):
    """(WP89) stage 22: xfer_nt_b2b and decide_abort over F23, F30, F34 and F35 with every integer
    of the four transfer classes with a not-taken path, the corpus guard as its guard."""

    def test_stage_22_families_enums_and_integers(self):
        from validation.v35s.chains.sim.config import DEFAULT_COST, OPTIONS
        self.assertEqual(fit.STAGE_FAMILIES[22], ["F23", "F30", "F34", "F35"])
        self.assertEqual(set(fit.F48_ENUMS), {"xfer_nt_b2b", "decide_abort"})
        for name, values in fit.F48_ENUMS.items():
            self.assertEqual(values, OPTIONS[name])
            # the old value first (DEFAULT): a tie keeps it
            self.assertEqual(getattr(DEFAULT, name), values[0], name)
        for cls in fit.F48_CLASSES:
            for name in DEFAULT_COST[cls]:
                self.assertIn(f"{cls}.{name}", fit.F48_INTS)
            self.assertIn(f"{cls}.wb", fit.F48_INTS)
        self.assertFalse({p.split(".")[0] for p in fit.F48_INTS} - set(fit.F48_CLASSES))
        self.assertEqual(len(fit.F48_INTS), len(set(fit.F48_INTS)))

    def test_stage_22_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage22({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_22_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage22({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 22)
        self.assertEqual(args[2], fit.F48_ENUMS)
        self.assertEqual(args[3], fit.F48_INTS)
        self.assertEqual(kw["sweep"], fit.F48_ENUMS)
        self.assertFalse(kw["guard"])

    def test_cli_accepts_stage_22(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "22"])
        self.assertEqual(args.stage, 22)
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(
            ["--stage", "21", "--to", "22"])
        self.assertEqual(args.to, 22)

    def test_run_stage_dispatches_22(self):
        with mock.patch.object(fit, "stage22", return_value={"config": {}}) as s22, \
                mock.patch.object(fit, "stage21") as s21, \
                mock.patch.object(fit, "save", return_value="x"), \
                mock.patch.object(fit, "CORPUS_GUARD", None):
            fit.run_stage(22, {"config": DEFAULT.to_json()}, log=lambda *a: None)
        s22.assert_called_once()
        s21.assert_not_called()


class LdeaDisplacementStage(unittest.TestCase):
    """(WP92) stage 23: lea_slot and lea_disp over F25 and F30 with every integer of the lea
    class, the corpus guard as its guard."""

    def test_stage_23_families_enums_and_integers(self):
        from validation.v35s.chains.sim.config import DEFAULT_COST, OPTIONS
        self.assertEqual(fit.STAGE_FAMILIES[23], ["F25", "F30"])
        self.assertEqual(set(fit.F49_ENUMS), {"lea_slot", "lea_disp"})
        for name, values in fit.F49_ENUMS.items():
            self.assertEqual(values, OPTIONS[name])
        # the old value first (DEFAULT): a tie keeps it
        self.assertEqual(fit.F49_ENUMS["lea_slot"][0], DEFAULT.lea_slot)
        for name in DEFAULT_COST["lea"]:
            self.assertIn(f"lea.{name}", fit.F49_INTS)
        self.assertFalse({p.split(".")[0] for p in fit.F49_INTS} - {"lea"})
        self.assertEqual(len(fit.F49_INTS), len(set(fit.F49_INTS)))

    def test_stage_23_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage23({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_23_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage23({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 23)
        self.assertEqual(args[2], fit.F49_ENUMS)
        self.assertEqual(args[3], fit.F49_INTS)
        self.assertEqual(kw["sweep"], fit.F49_ENUMS)
        self.assertFalse(kw["guard"])

    def test_cli_accepts_stage_23(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "23"])
        self.assertEqual(args.stage, 23)
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(
            ["--stage", "22", "--to", "23"])
        self.assertEqual(args.to, 23)

    def test_run_stage_dispatches_23(self):
        with mock.patch.object(fit, "stage23", return_value={"config": {}}) as s23, \
                mock.patch.object(fit, "stage22") as s22, \
                mock.patch.object(fit, "save", return_value="x"), \
                mock.patch.object(fit, "CORPUS_GUARD", None):
            fit.run_stage(23, {"config": DEFAULT.to_json()}, log=lambda *a: None)
        s23.assert_called_once()
        s22.assert_not_called()


class MemIndirectTransferStage(unittest.TestCase):
    """(WP93) stage 24: xfer_mem_head, xfer_mem_disp and xfer_mem_ir over F37 with every integer
    of the six F37 classes, the corpus guard as its guard."""

    def test_stage_24_families_enums_and_integers(self):
        from validation.v35s.chains.sim.config import DEFAULT_COST, OPTIONS
        self.assertEqual(fit.STAGE_FAMILIES[24], ["F37"])
        self.assertEqual(set(fit.F50_ENUMS), {"xfer_mem_head", "xfer_mem_disp", "xfer_mem_ir"})
        for name, values in fit.F50_ENUMS.items():
            self.assertEqual(values, OPTIONS[name])
            # the old value first (DEFAULT): a tie keeps it
            self.assertEqual(values[0], getattr(DEFAULT, name))
        self.assertEqual(set(fit.F50_CLASSES), {"call_mem", "br_mem", "call_far_mem",
                                                "branch_far_mem", "brk", "reti"})
        for cls in fit.F50_CLASSES:
            for name in DEFAULT_COST[cls]:
                self.assertIn(f"{cls}.{name}", fit.F50_INTS)
        self.assertFalse({p.split(".")[0] for p in fit.F50_INTS} - set(fit.F50_CLASSES))
        self.assertEqual(len(fit.F50_INTS), len(set(fit.F50_INTS)))

    def test_stage_24_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage24({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_24_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage24({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 24)
        self.assertEqual(args[2], fit.F50_ENUMS)
        self.assertEqual(args[3], fit.F50_INTS)
        self.assertEqual(kw["sweep"], fit.F50_ENUMS)
        self.assertFalse(kw["guard"])

    def test_cli_accepts_stage_24(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "24"])
        self.assertEqual(args.stage, 24)
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(
            ["--stage", "23", "--to", "24"])
        self.assertEqual(args.to, 24)

    def test_run_stage_dispatches_24(self):
        with mock.patch.object(fit, "stage24", return_value={"config": {}}) as s24, \
                mock.patch.object(fit, "stage23") as s23, \
                mock.patch.object(fit, "save", return_value="x"), \
                mock.patch.object(fit, "CORPUS_GUARD", None):
            fit.run_stage(24, {"config": DEFAULT.to_json()}, log=lambda *a: None)
        s24.assert_called_once()
        s23.assert_not_called()


class StringPairStage(unittest.TestCase):
    """(WP95) stage 25: str_single_wb and str_single_start over the families that run a string
    class, with every integer an unprefixed string form reads, the corpus guard as its guard."""

    def test_stage_25_families_enums_and_integers(self):
        from validation.v35s.chains.sim.config import DEFAULT_COST, OPTIONS
        self.assertEqual(fit.STAGE_FAMILIES[25], ["F24", "F30", "F31", "F33"])
        self.assertEqual(set(fit.F51_ENUMS), {"str_single_wb", "str_single_start"})
        for name, values in fit.F51_ENUMS.items():
            self.assertEqual(values, OPTIONS[name])
            # the old value first (DEFAULT): a tie keeps it
            self.assertEqual(values[0], getattr(DEFAULT, name))
        self.assertEqual(set(fit.F51_CLASSES), {"str_move", "str_cmp", "str_store", "str_load",
                                                "str_scan", "str_in", "str_out"})
        for cls in fit.F51_CLASSES:
            for name in ("uwb", "ugap", "setup", "exec"):
                self.assertIn(f"{cls}.{name}", fit.F51_INTS)
            for name in ("rpre", "first", "loop", "rexit"):     # REP-only integers stay out
                self.assertNotIn(f"{cls}.{name}", fit.F51_INTS)
        self.assertFalse({p.split(".")[0] for p in fit.F51_INTS} - set(fit.F51_CLASSES))
        self.assertEqual(len(fit.F51_INTS), len(set(fit.F51_INTS)))

    def test_stage_25_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage25({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_25_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage25({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 25)
        self.assertEqual(args[2], fit.F51_ENUMS)
        self.assertEqual(args[3], fit.F51_INTS)
        self.assertEqual(kw["sweep"], fit.F51_ENUMS)
        self.assertFalse(kw["guard"])

    def test_cli_accepts_stage_25(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "25"])
        self.assertEqual(args.stage, 25)
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(
            ["--stage", "24", "--to", "25"])
        self.assertEqual(args.to, 25)

    def test_run_stage_dispatches_25(self):
        with mock.patch.object(fit, "stage25", return_value={"config": {}}) as s25, \
                mock.patch.object(fit, "stage24") as s24, \
                mock.patch.object(fit, "save", return_value="x"), \
                mock.patch.object(fit, "CORPUS_GUARD", None):
            fit.run_stage(25, {"config": DEFAULT.to_json()}, log=lambda *a: None)
        s25.assert_called_once()
        s24.assert_not_called()


class PageMechanismStage(unittest.TestCase):
    """(WP96) stage 26: WP94's bf_imm_hold, page_imm_run and page_b2b_win over F32, F33 and F34
    with every integer of the classes the mechanisms read, the corpus guard as its guard."""

    def test_stage_26_families_enums_and_integers(self):
        from validation.v35s.chains.sim.config import DEFAULT_COST, OPTIONS
        self.assertEqual(fit.STAGE_FAMILIES[26], ["F32", "F33", "F34"])
        self.assertEqual(set(fit.F52_ENUMS), {"bf_imm_hold", "page_imm_run", "page_b2b_win"})
        for name, values in fit.F52_ENUMS.items():
            self.assertEqual(values, OPTIONS[name])
            # the old value first (DEFAULT): a tie keeps it
            self.assertEqual(values[0], getattr(DEFAULT, name))
        self.assertEqual(set(fit.F52_CLASSES), {"bf_ext", "bf_ins", "bit1", "rol4", "ror4",
                                                "bit1_test", "bit1_rmw", "bit1_clr"})
        for cls in fit.F52_CLASSES:
            for name in DEFAULT_COST[cls]:
                self.assertIn(f"{cls}.{name}", fit.F52_INTS)
        for p in ("bf_ext.hrel", "bf_ins.hrel", "bf_ext.span", "bf_ext.xspan", "bf_ext.wb"):
            self.assertIn(p, fit.F52_INTS)
        # the 0F classes no mechanism reads stay out
        for cls in ("rol4_mem", "ror4_mem", "mul_imm"):
            self.assertNotIn(cls, fit.F52_CLASSES)
        self.assertFalse({p.split(".")[0] for p in fit.F52_INTS} - set(fit.F52_CLASSES))
        self.assertEqual(len(fit.F52_INTS), len(set(fit.F52_INTS)))

    def test_stage_26_needs_the_corpus_guard(self):
        with mock.patch.object(fit, "CORPUS_GUARD", None):
            with self.assertRaises(SystemExit):
                fit.stage26({"config": DEFAULT.to_json()}, log=lambda *a: None)

    def test_stage_26_calls_stage_n(self):
        with mock.patch.object(fit, "CORPUS_GUARD", ["x"]), \
                mock.patch.object(fit, "stage_n", return_value={"config": {}}) as sn:
            fit.stage26({"config": DEFAULT.to_json()}, log=lambda *a: None)
        args, kw = sn.call_args
        self.assertEqual(args[0], 26)
        self.assertEqual(args[2], fit.F52_ENUMS)
        self.assertEqual(args[3], fit.F52_INTS)
        self.assertEqual(kw["sweep"], fit.F52_ENUMS)
        self.assertFalse(kw["guard"])

    def test_cli_accepts_stage_26(self):
        import argparse
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(["--stage", "26"])
        self.assertEqual(args.stage, 26)
        args = fit.add_arguments(argparse.ArgumentParser()).parse_args(
            ["--stage", "25", "--to", "26"])
        self.assertEqual(args.to, 26)

    def test_run_stage_dispatches_26(self):
        with mock.patch.object(fit, "stage26", return_value={"config": {}}) as s26, \
                mock.patch.object(fit, "stage25") as s25, \
                mock.patch.object(fit, "save", return_value="x"), \
                mock.patch.object(fit, "CORPUS_GUARD", None):
            fit.run_stage(26, {"config": DEFAULT.to_json()}, log=lambda *a: None)
        s26.assert_called_once()
        s25.assert_not_called()

    def test_run_stage_dispatches_25_not_26(self):
        with mock.patch.object(fit, "stage25", return_value={"config": {}}) as s25, \
                mock.patch.object(fit, "stage26") as s26, \
                mock.patch.object(fit, "save", return_value="x"), \
                mock.patch.object(fit, "CORPUS_GUARD", None):
            fit.run_stage(25, {"config": DEFAULT.to_json()}, log=lambda *a: None)
        s25.assert_called_once()
        s26.assert_not_called()
