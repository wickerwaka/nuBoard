"""The fitter's speed-ups give the results of the plain full simulation (fit.py's result
cache keyed on a projected configuration; sim/machine.py's quiet-clock fast-forward)."""

from __future__ import annotations

import json
import unittest
from collections import defaultdict

from validation.v35s.chains import fit
from validation.v35s.chains.score import aligned
from validation.v35s.chains.sim import machine
from validation.v35s.chains.sim.config import DEFAULT, Config

FAMILIES = ["F0", "F0w", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9"]
# Structures on the stage-2 storage seed that stall on F0 (no bus cycle for STALL_CLOCKS)
# or over-fill the queue: the fast-forward and the error results must match too.
STALLS = {"room_ir": "idle", "request_eval": "on_take", "opcode_take": "start"}
OVERFLOWS = {"room_ir": "arrival_idle", "arrive_partial": True, "request_hold": "hold",
             "release": "first", "data_ready": 1, "take_commit": "per_byte",
             "opcode_take": "start", "take_sync": "pending_end"}


def _sample(per_cell=2) -> list[str]:
    """Run ids spanning every family x marker kind x parity (per_cell of each)."""
    cells = defaultdict(list)
    for i in fit.load(FAMILIES):
        r = fit._DATA[i]
        cells[(r.family, r.marker, r.parity)].append(i)
    out = []
    for key in sorted(cells):
        ids = cells[key]
        out += ids[::max(1, len(ids) // per_cell)][:per_cell]
    return out


def _configs() -> list[Config]:
    cfgs = [DEFAULT, DEFAULT.replace(**fit.STAGE2_SEED, **STALLS),
            DEFAULT.replace(**fit.STAGE2_SEED, **OVERFLOWS)]
    for name in ("fit-hand.json", "fit.json"):
        path = fit.OUT_DIR / name
        if path.exists():
            cfgs.append(Config.from_json(json.loads(path.read_text())))
            break
    return cfgs


def _full(cfg, run, fast: bool):
    """(run_result, the model's aligned events or the error) with fast-forward on or off."""
    from validation.v35s.chains.sim.machine import simulate_normalized

    keep, machine.FAST_FORWARD = machine.FAST_FORWARD, fast
    try:
        try:
            events = aligned(simulate_normalized(run.chain, cfg, run.base))
        except Exception as e:
            events = f"{type(e).__name__}: {e}"
        return fit.run_result(cfg, run), events
    finally:
        machine.FAST_FORWARD = keep


class _Corpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ids = _sample()
        except FileNotFoundError:
            raise unittest.SkipTest("no corpus entries")
        cls.jobs, fit.JOBS = fit.JOBS, 1
        fit.cache_clear()

    @classmethod
    def tearDownClass(cls):
        fit.JOBS = cls.jobs
        fit.cache_clear()


class SpeedUpsKeepResults(_Corpus):
    def test_sample_spans_every_family_and_marker(self):
        runs = [fit._DATA[i] for i in self.ids]
        self.assertGreaterEqual(len(runs), 60)
        self.assertEqual({r.family for r in runs}, set(FAMILIES))
        self.assertTrue({"push", "out", "store"} <= {r.marker for r in runs})

    def test_cached_fast_results_equal_the_full_simulation(self):
        errors = set()
        for cfg in _configs():
            fit.cache_clear()
            plain = [_full(cfg, fit._DATA[i], fast=False) for i in self.ids]
            fast = [_full(cfg, fit._DATA[i], fast=True) for i in self.ids]
            # exact flag, residual, signed residual (an error is a miss with no residual)
            # and the whole model event list (or the same error message)
            self.assertEqual(fast, plain)
            first = fit.evaluate([cfg], self.ids)[0]           # all simulated
            again = fit.evaluate([cfg], self.ids)[0]           # all from the cache
            self.assertEqual(first, [p[0] for p in plain])
            self.assertEqual(again, first)
            errors |= {p[1].split(":")[0] for p in plain if isinstance(p[1], str)}
        self.assertIn("RuntimeError", errors)                  # stalls were exercised
        self.assertIn("QueueOverflow", errors)

    def test_grid_batches_in_rounds_equal_the_full_simulation(self):
        # a batch of >= ROUNDS_MIN_CFGS structures goes through evaluate's rounds (runs
        # shared between structures that agree on what the run reads)
        cfg = _configs()[-1]
        cfgs = fit.grid(cfg, {"mem_order": ("pre_take", "split"), "imm_order": (
            "with_addr", "after_post", "after_data"), "odd_split": ("atomic", "separate"),
            "rmw_shift": ("alu", "shift"), "grp_mode": ("clocks", "setup")})
        cfgs += fit.grid(DEFAULT.replace(**fit.STAGE2_SEED), {
            "room_ir": (False, "idle"), "request_eval": ("every_clock", "on_take"),
            "opcode_take": ("prefetch", "start"), "arbiter_q": (2, 3)})
        self.assertGreaterEqual(len(cfgs), fit.ROUNDS_MIN_CFGS)
        ids = self.ids[::2]
        fit.cache_clear()
        got = fit.evaluate(cfgs, ids)
        self.assertGreater(fit.CACHE_STATS["hits"], 0)
        self.assertEqual(got, [[fit.run_result(c, fit._DATA[i]) for i in ids] for c in cfgs])
        self.assertEqual(fit.evaluate(cfgs, ids), got)
        # the same through a worker pool (tasks of one configuration's runs)
        fit.cache_clear()
        fit.JOBS = 2
        try:
            self.assertEqual(fit.evaluate(cfgs, ids), got)
        finally:
            fit.JOBS = 1
            fit._close_pool()

    def test_stall_reaches_the_guard_without_simulating_it(self):
        cfg = DEFAULT.replace(**fit.STAGE2_SEED, **STALLS)
        run = fit._DATA[next(i for i in self.ids if fit._DATA[i].family == "F0")]
        clocks = {}
        for fast in (False, True):
            keep, machine.FAST_FORWARD = machine.FAST_FORWARD, fast
            arbitrate, ticks = machine.arbitrate, [0]

            def counted(*a):                  # one arbitration per simulated clock
                ticks[0] += 1
                return arbitrate(*a)
            machine.arbitrate = counted
            try:
                with self.assertRaises(RuntimeError) as cm:
                    machine.Machine(run.chain, cfg, run.base).run()
            finally:
                machine.FAST_FORWARD = keep
                machine.arbitrate = arbitrate
            clocks[fast] = (str(cm.exception), ticks[0])
        self.assertEqual(clocks[True][0], clocks[False][0])
        self.assertIn("no bus cycle", clocks[True][0])
        self.assertLess(clocks[True][1], clocks[False][1] // 4)

    def test_cache_reuses_runs_without_the_moved_class(self):
        cfg = _configs()[-1]
        fit.cache_clear()
        fit.evaluate([cfg], self.ids)
        moved = cfg.replace(**{"load.exec": fit.getp(cfg, "load.exec") + 1})
        n0, h0 = fit.CACHE_STATS["lookups"], fit.CACHE_STATS["hits"]
        res = fit.evaluate([moved], self.ids)[0]
        with_load = [i for i in self.ids if "load" in fit.run_classes(fit._DATA[i].chain)[0]]
        self.assertTrue(with_load)
        self.assertEqual(fit.CACHE_STATS["lookups"] - n0, len(self.ids))
        self.assertEqual(fit.CACHE_STATS["hits"] - h0, len(self.ids) - len(with_load))
        self.assertEqual(res, [fit.run_result(moved, fit._DATA[i]) for i in self.ids])


class ProjectionKey(_Corpus):
    def test_key_omits_exactly_the_classes_a_run_lacks(self):
        cfg = _configs()[-1]
        for i in self.ids[::7]:
            classes, modes = fit.run_classes(fit._DATA[i].chain)
            key = fit.projection_key(cfg, i)
            for cls in cfg.cost:
                names = list(cfg.cost[cls]) or ["exec"]
                moved = cfg.replace(**{f"{cls}.{names[0]}": cfg.c(cls, names[0]) + 3})
                self.assertEqual(fit.projection_key(moved, i) != key, cls in classes,
                                 f"{i}: class {cls}")
            for mode in cfg.ea:
                moved = cfg.replace(**{f"ea.{mode}": cfg.ea[mode] + 3})
                self.assertEqual(fit.projection_key(moved, i) != key, mode in modes,
                                 f"{i}: mode {mode}")

    def test_structural_fields_count_only_when_read(self):
        # the cache keys a run on the fields its simulation read: a structure that differs
        # only in a field the run never read reuses the result, one that differs in a read
        # field is simulated, and either way the result is the full simulation's
        from validation.v35s.chains.sim.config import OPTIONS
        cfg = _configs()[-1]
        fit.cache_clear()
        for i in self.ids[::3]:
            run = fit._DATA[i]
            res, names = fit.run_result_reads(cfg, run)
            self.assertEqual(res, fit.run_result(cfg, run))
            self.assertIn("min_gap", names)            # every run reads some fields
            fit.evaluate([cfg], [i])
            unread = [n for n in OPTIONS if n not in names]
            for n in unread[:4] + [n for n in names if n in OPTIONS][:4]:
                alt = next((v for v in OPTIONS[n] if v != getattr(cfg, n)
                            or type(v) is not type(getattr(cfg, n))), None)
                if alt is None:
                    continue
                try:
                    moved = cfg.replace(**{n: alt})
                except ValueError:
                    continue
                h = fit.CACHE_STATS["hits"]
                got = fit.evaluate([moved], [i])[0][0]
                self.assertEqual(fit.CACHE_STATS["hits"] - h, int(n not in names), (i, n))
                self.assertEqual(got, fit.run_result(moved, run), (i, n))

    def test_irrelevant_class_does_not_change_results(self):
        # the key's premise: a class the run lacks is never read
        cfg = _configs()[-1]
        for i in self.ids[::5]:
            classes, modes = fit.run_classes(fit._DATA[i].chain)
            kw = {f"{c}.{n}": v + 5 for c, t in cfg.cost.items() if c not in classes
                  for n, v in t.items()}
            kw.update({f"ea.{m}": v + 5 for m, v in cfg.ea.items() if m not in modes})
            moved = cfg.replace(**kw)
            self.assertEqual(fit.projection_key(moved, i), fit.projection_key(cfg, i))
            self.assertEqual(_full(moved, fit._DATA[i], False), _full(cfg, fit._DATA[i], False))

    def test_model_reads_only_the_projected_classes(self):
        class Recording(dict):
            def __init__(self, d, seen):
                super().__init__(d)
                self.seen = seen

            def get(self, k, default=None):
                self.seen.add(k)
                return super().get(k, default)

            def __getitem__(self, k):
                self.seen.add(k)
                return super().__getitem__(k)

            def __contains__(self, k):
                self.seen.add(k)
                return super().__contains__(k)

        for base in _configs()[:1] + _configs()[-1:] + [
                _configs()[-1].replace(rmw_shift="shift", mem_order="split", ea_post="setup",
                                       grp_mode="setup", imm_order="after_post")]:
            for i in self.ids:
                cfg = Config.from_json(base.to_json())
                cost, ea = set(), set()
                cfg.cost, cfg.ea = Recording(cfg.cost, cost), Recording(cfg.ea, ea)
                run = fit._DATA[i]
                try:
                    machine.Machine(run.chain, cfg, run.base).run()
                except Exception:
                    pass
                classes, modes = fit.run_classes(run.chain)
                self.assertLessEqual(cost - {""}, set(classes), i)
                self.assertLessEqual(ea, set(modes), i)


if __name__ == "__main__":
    unittest.main()
