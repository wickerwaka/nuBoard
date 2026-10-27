"""Offline tests of normalize/derive/report on the recorded F0, F0w and F1 silicon runs."""

from __future__ import annotations

import json
import unittest

from validation.v35s.chains.derive import (apply_costs, f6_drain_slopes, f7_interactions,
                                           family_facts, kind_pairs, run_facts)
from validation.v35s.chains.normalize import (TICKS_PER_CLOCK, load_runs, normalize)
from validation.v35s.chains.report import family_tables, jsonable, strips


def _facts(family):
    if family not in _facts.cache:
        _facts.cache[family] = family_facts(family)
    return _facts.cache[family]


_facts.cache = {}


class NormalizeTests(unittest.TestCase):
    def runs(self):
        for family in ("F0", "F0w", "F1"):
            yield from load_runs(family)

    def test_single_phase_per_run(self):
        phases = set()
        for run in self.runs():
            n = normalize(run)
            phases.add(n.phase)
            trace = run["socket_trace"]
            first = next(k for k, r in enumerate(trace) if r["start"] == n.t0_tick)
            self.assertEqual({r["start"] % TICKS_PER_CLOCK for r in trace[first:]}, {n.phase},
                             n.run_id)
        # The absolute phase does differ between runs, so alignment must not use it.
        self.assertGreater(len(phases), 1)

    def test_cycle_lengths_by_waits(self):
        for run in self.runs():
            n = normalize(run)
            mem = (run["chain"]["wtc"] & 3)
            io = (run["chain"]["wtc"] >> 14) & 3
            for e in n.events:
                want = 3 + (io if e.kind.startswith("io") else mem)
                self.assertEqual(e.length, want, f"{n.run_id} {e}")
            if n.chain.waits >= 0:
                self.assertEqual(mem, n.chain.waits)
                fetches = [e for e in n.events if e.kind == "fetch"]
                self.assertEqual(min(b.clock - a.clock for a, b in zip(fetches, fetches[1:])),
                                 3 + n.chain.waits, n.run_id)

    def test_fetch_mapping(self):
        n = normalize(next(r for r in load_runs("F0", (0,))
                           if r["chain"]["id"] == "F0-ls-pE-w0"))
        first = n.events[0]
        self.assertEqual((first.clock, first.addr, first.instr_index, first.byte_range),
                         (0, 0x10046, 0, (0, 1)))
        by_addr = {e.addr: e for e in n.events if e.kind == "fetch"}
        self.assertEqual(by_addr[0x10048].byte_range, (1, 3))     # LS bytes 0-1
        self.assertEqual(by_addr[0x1004C].instr_index, 2)        # END


class F0Tests(unittest.TestCase):
    def test_ls_even_w0_example(self):
        n = normalize(next(r for r in load_runs("F0", (0,))
                           if r["chain"]["id"] == "F0-ls-pE-w0"))
        fetches = [(e.clock, e.addr & 0xFF) for e in n.events if e.kind == "fetch"]
        self.assertEqual(fetches[:8], [(0, 0x46), (7, 0x48), (10, 0x4A), (14, 0x4C),
                                       (17, 0x4E), (26, 0x50), (104, 0x52), (107, 0x54)])
        self.assertEqual([(e.clock, e.kind, e.addr) for e in n.events if e.kind != "fetch"],
                         [(115, "io_write", 0xFF00)])
        f = run_facts(n)
        self.assertEqual(f["fill_words"], 3)
        self.assertEqual(f["idle_gap"], 78)
        self.assertEqual(n.t_fill, 28)
        self.assertEqual(f["restart_clock"], 104 - 28)
        self.assertEqual(f["restart_cadence"], 3)              # back to back

    def test_no_data_cycles_in_f0(self):
        for f in _facts("F0")["runs"]:
            self.assertNotRegex(f["interleave"], "[RWrwiX]", f["id"])
            self.assertTrue(f["interleave"].endswith("I"), f["id"])


class F1Tests(unittest.TestCase):
    def test_markers_found_in_order(self):
        for run in load_runs("F1"):
            n = normalize(run)
            ids = [i.marker_id for i in n.chain.instrs if i.role == "marker"]
            self.assertEqual(sorted(n.t_markers), ids, n.run_id)
            clocks = [n.t_markers[i] for i in ids]
            self.assertEqual(clocks, sorted(clocks), n.run_id)
            self.assertEqual(len(set(clocks)), len(clocks), n.run_id)
            self.assertEqual(run["chain"]["knobs"]["markers"], len(ids))
            kind = {"out": "io_write", "push": "stack_write", "store": "data_write"}
            for e in n.events:
                if e.marker_id is not None:
                    self.assertEqual(e.kind, kind[n.chain.marker_kind], n.run_id)

    def test_repeat_traces_agree_after_alignment(self):
        checked = 0
        for family in ("F0", "F0w", "F1"):
            for run in load_runs(family):
                if not run.get("repeat_trace"):
                    continue
                a = run_facts(normalize(run))
                b = run_facts(normalize(run, "repeat_trace"))
                a.pop("phase"), b.pop("phase")
                self.assertEqual(a, b, run["chain"]["id"])
                self.assertEqual(a["dM"], b["dM"])
                checked += 1
        self.assertGreater(checked, 0)


class StackTrackingTests(unittest.TestCase):
    """M0=PUSH, POP [BW] x2, M1=PUSH: SP goes 0F00 -> 0EFE -> 0F00 -> 0F02 -> 0F00,
    so M1 writes at 0F00, above the initial SP."""

    def setUp(self):
        path = "build/validation/v35s/chains/F5-w0.json"
        try:
            with open(path) as handle:
                runs = json.load(handle)["runs"]
        except FileNotFoundError:
            self.skipTest(f"{path} not recorded")
        run = next((r for r in runs if r["chain"]["id"] == "F5-push-pop_m-k2-pE-w0"), None)
        if run is None:
            self.skipTest("F5-push-pop_m-k2-pE-w0 not recorded")
        self.n = normalize(run)

    def test_expected_accesses(self):
        n = self.n
        acc = [(n.chain.instrs[k].form, a.kind, a.addr)
               for k, accs in n.expected_accesses.items() for a in accs]
        self.assertEqual(acc, [("M", "stack_write", 0x0EFE),
                               ("pop_m", "stack_read", 0x0EFE), ("pop_m", "data_write", 0x0800),
                               ("pop_m", "stack_read", 0x0F00), ("pop_m", "data_write", 0x0800),
                               ("M", "stack_write", 0x0F00), ("END", "io_write", 0xFF00)])
        self.assertEqual(n.stack_range, (0x0EFE, 0x0F02))

    def test_markers_at_tracked_sp(self):
        n = self.n
        marks = {e.marker_id: (e.kind, e.addr) for e in n.events if e.marker_id is not None}
        self.assertEqual(marks, {0: ("stack_write", 0x0EFE), 1: ("stack_write", 0x0F00)})
        self.assertLess(n.t_markers[0], n.t_markers[1])
        self.assertIsNone(n.access_mismatch)
        observed = [(e.kind, e.addr, n.chain.instrs[e.instr_index].form)
                    for e in n.events if e.kind != "fetch"]
        self.assertEqual([o[1] for o in observed], [0x0EFE, 0x0EFE, 0x0800, 0x0F00, 0x0800,
                                                    0x0F00, 0xFF00])
        self.assertEqual(observed[1][2], "pop_m")


class BaselineTests(unittest.TestCase):
    @staticmethod
    def fake(family, marker, x_variant, column, **values):
        return {"id": f"{family}-{marker}-{x_variant}-{column}", "family": family,
                "marker": marker, "x_variant": x_variant, "variant": f"{marker}-{x_variant}",
                "column": column, "knobs": {"marker": marker}, "dM": None,
                "restart_clock": None, **values}

    def test_same_kind_baselines(self):
        f = self.fake
        facts = [f("F3", "push", "empty", "pE-w0", dM=9), f("F3", "out", "empty", "pE-w0", dM=12),
                 f("F3", "push", "nop-k1", "pE-w0", dM=12), f("F3", "out", "nop-k1", "pE-w0", dM=14),
                 f("F3", "push", "empty", "pO-w0", dM=10), f("F3", "push", "nop-k1", "pO-w0", dM=11),
                 f("F3", "out", "nop-k1", "pO-w0", dM=20)]   # no out-empty at pO: no cost
        cost = apply_costs("F3", facts)
        self.assertEqual(cost, {"push-nop-k1": {"pE-w0": 3, "pO-w0": 1}, "out-nop-k1": {"pE-w0": 2}})
        self.assertEqual(facts[2]["baseline"], "F3-push-empty-pE-w0")
        self.assertEqual(facts[3]["baseline"], "F3-out-empty-pE-w0")
        self.assertNotIn("cost", facts[6])
        pairs = kind_pairs(facts)
        self.assertEqual(pairs["nop-k1"], {"pE-w0": (3, 2, 1), "pO-w0": (1, None, None)})

        f6 = [f("F6", "push", "ld_bw-n0", "pE-w1", dM=20), f("F6", "out", "ld_bw-n0", "pE-w1", dM=30),
              f("F6", "push", "ld_bw-n2", "pE-w1", dM=27), f("F6", "out", "ld_bw-n2d4", "pE-w1", dM=40)]
        self.assertEqual(apply_costs("F6", f6), {"push-ld_bw-n2": {"pE-w1": 7},
                                                 "out-ld_bw-n2d4": {"pE-w1": 10}})

        f2 = [f("F2", "push", "empty", "pO-w2", restart_clock=86),
              f("F2", "out", "empty", "pO-w2", restart_clock=82),
              f("F2", "out", "nop", "pO-w2", restart_clock=79)]
        self.assertEqual(apply_costs("F2", f2), {"out-nop": {"pO-w2": -3}})


class F9Facts(unittest.TestCase):
    """The release series (chains-F9-w<N>): marker-less chains go through the same
    path, the restart is wait-independent and the refill counts the bytes consumed."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.ff = family_facts("F9")
        except FileNotFoundError:
            raise unittest.SkipTest("no corpus entries for F9")

    def row(self, variant, column):
        return self.ff["rows"][variant][column]

    def test_all_runs_normalize(self):
        self.assertEqual(len(self.ff["runs"]), 408)
        none = [f for f in self.ff["runs"] if f["marker"] == "none"]
        self.assertEqual(len(none), 204)
        self.assertTrue(all(f["t_M"] == [] and f["dM"] is None for f in none))

    def test_restart_and_refill(self):
        # Silicon: NOP x8 after the fence restarts at +72 (even) / +76 (odd) at every
        # wait setting and refills 6 words before the trailing LS idles.
        for w in (0, 1, 2):
            self.assertEqual(self.row("none-nop8", f"pE-w{w}")["restart_clock"], 72)
            self.assertEqual(self.row("none-nop8", f"pO-w{w}")["restart_clock"], 76)
            self.assertEqual(self.row("none-nop8", f"pE-w{w}")["refill_fetches"], 6)
            self.assertEqual(self.row("none-empty", f"pE-w{w}")["restart_clock"], 75)
            self.assertEqual(self.row("push-empty", f"pE-w{w}")["restart_clock"], 81 + w)
        # Gaps of 12-40 free clocks inside a NOP train do not end the refill.
        self.assertEqual(self.row("push-nop8", "pE-w1")["refill_fetches"], 7)

    def test_costs_against_same_marker_empty(self):
        self.assertEqual(self.ff["cost"]["none-nop2"]["pE-w0"], 72 - 75)
        self.assertEqual(self.ff["cost"]["push-nop2"]["pE-w0"], 72 - 81)

    def test_tables_render(self):
        text = family_tables(self.ff)
        self.assertIn("refill_fetches", text)
        self.assertIn("none-es3_imm", text)


class F7BaselineTests(unittest.TestCase):
    """F7 pairs resolve their singles from F4 (ld_bw), F3 (mov_aw_dw) and F5 (the
    rest), same marker kind and column, and the empty of a's family."""

    @staticmethod
    def fake(family, marker, xv, column, dM, knobs=None, x=()):
        return {"id": f"{family}-{marker}-{xv}-{column}", "family": family, "marker": marker,
                "x_variant": xv, "variant": f"{marker}-{xv}", "column": column,
                "knobs": {"marker": marker, **(knobs or {})}, "dM": dM,
                "x": [{"parity": p} for p in x]}

    def test_interaction(self):
        f = self.fake
        from validation.v35s.chains.derive import index_facts
        extra = {
            "F3": index_facts([f("F3", "push", "empty", "pE-w0", 9),
                               f("F3", "push", "mov_aw_dw-k1", "pE-w0", 12),
                               f("F3", "out", "mov_aw_dw-k1", "pE-w0", 99)]),
            "F4": index_facts([f("F4", "push", "empty", "pE-w0", 9),
                               f("F4", "push", "ld_bw-k1", "pE-w0", 20),
                               f("F4", "push", "ld_bw-k1", "pO-w0", 77)]),
            "F5": index_facts([f("F5", "push", "empty", "pE-w0", 10),
                               f("F5", "push", "st_bw-k1", "pE-w0", 18)]),
        }
        pairs = [f("F7", "push", "ld_bw-mov_aw_dw", "pE-w0", 25,
                   {"a": "ld_bw", "b": "mov_aw_dw"}, "oo"),
                 f("F7", "push", "st_bw-ld_bw", "pE-w0", 30, {"a": "st_bw", "b": "ld_bw"}, "oo"),
                 f("F7", "out", "ld_bw-mov_aw_dw", "pE-w0", 25,
                   {"a": "ld_bw", "b": "mov_aw_dw"}, "ee")]
        result = f7_interactions(pairs, extra)
        self.assertEqual(pairs[0]["interaction"], 25 - 20 - 12 + 9)     # F4 empty (a's)
        self.assertEqual(pairs[1]["interaction"], 30 - 18 - 20 + 10)    # F5 empty (a's)
        self.assertIsNone(pairs[2]["interaction"])                      # no out ld_bw single
        cells = result["cells"]
        self.assertEqual(cells[("push", "pE-w0")]["ld_bw"]["mov_aw_dw"], (2, "o", "o"))
        # F5's push empty (10) differs from F3/F4's (9) in pE-w0: reported.
        self.assertEqual(result["empties"], {("push", "pE-w0"): {"F3": 9, "F4": 9, "F5": 10}})
        cost = apply_costs("F7", pairs, extra)
        self.assertEqual(cost["push-ld_bw-mov_aw_dw"], {"pE-w0": 25 - 9})
        self.assertEqual(cost["push-st_bw-ld_bw"], {"pE-w0": 30 - 10})

    def test_f6_slopes(self):
        f = BaselineTests.fake
        facts = [f("F6", "push", f"ld_bw-n{n}", "pE-w0", dM=d)
                 for n, d in ((0, 20), (2, 30), (4, 44), (6, 58))]
        facts.append(f("F6", "push", "ld_bw-n2d4", "pE-w0", dM=31))
        facts.append(f("F6", "push", "ld_bw-n4d4", "pE-w0", dM=47))
        apply_costs("F6", facts)
        slopes = f6_drain_slopes(facts)
        self.assertEqual(slopes["push-ld_bw"], {"pE-w0": (7.0, 7.0)})
        self.assertEqual(slopes["push-ld_bw d4"], {"pE-w0": (8.0, None)})


class F8Tests(unittest.TestCase):
    def test_refresh_runs_normalize(self):
        try:
            runs = load_runs("F8", (0,))
        except (FileNotFoundError, KeyError):
            self.skipTest("F8 not in the corpus")
        for run in runs:
            n = normalize(run)                      # strict: refresh allowed with RFM on
            refresh = [e for e in n.events if e.kind == "refresh"]
            self.assertTrue(refresh, n.run_id)
            self.assertEqual({e.length for e in refresh}, {5}, n.run_id)
            self.assertIsNotNone(n.t_fill)
            self.assertEqual(len(n.t_markers), 2)
        run = dict(runs[0], chain={**runs[0]["chain"], "rfm": 0xEC})
        with self.assertRaises(AssertionError):
            normalize(run)                          # the same trace with RFM off fails


class PreWindowTests(unittest.TestCase):
    """(WP40) Normalized.pre: the prelude's tail from its POP PSW read to clock 0."""

    def run_of(self, family, run_id):
        try:
            return next(r for r in load_runs(family) if r["chain"]["id"] == run_id)
        except (FileNotFoundError, KeyError, StopIteration):
            self.skipTest(f"{run_id} not in the corpus")

    def test_refresh_off_prelude(self):
        n = normalize(self.run_of("F0", "F0-ls-pE-w0"))
        self.assertEqual([(e.clock, e.char) for e in n.pre],
                         [(-79, "r"), (-68, "F"), (-65, "F"), (-62, "F"), (-55, "F"),
                          (-52, "F"), (-49, "F"), (-45, "F"), (-42, "F"), (-35, "F"),
                          (-32, "F"), (-28, "F"), (-21, "F"), (-18, "F"), (-14, "F"),
                          (-7, "F"), (-4, "F")])
        self.assertEqual((n.pre[0].addr, n.pre[0].length), (0x0EFE, 3))
        self.assertEqual([e.addr for e in n.pre[1:4]], [0x10026, 0x10028, 0x1002A])
        self.assertEqual(n.pre[-1].addr, 0x10044)
        self.assertTrue(all(e.instr_index is None for e in n.pre))
        # the existing lists are untouched: events still start at clock 0
        self.assertEqual((n.events[0].clock, n.events[0].addr), (0, 0x10046))
        self.assertEqual(n.t_fill, 28)

    def test_refresh_on_prelude(self):
        n = normalize(self.run_of("F17", "F17-p-n0-empty-pE-w0"))
        self.assertEqual(" ".join(f"{e.char}{e.clock}" for e in n.pre),
                         "r-98 X-87 F-82 F-79 F-76 X-69 F-64 F-61 F-58 X-54 F-49 F-46 F-42 "
                         "X-39 F-34 F-31 F-27 X-24 F-19 F-16 F-12 F-9 X-5")
        self.assertEqual({e.length for e in n.pre if e.kind == "refresh"}, {5})

    def test_pre_aligned_and_score(self):
        from validation.v35s.chains.score import pre_aligned, pre_score
        s = normalize(self.run_of("F18", "F18-a-push-fc-empty-pE-w0"))
        a = pre_aligned(s)
        self.assertEqual(a[0], (-102, "stack_read", 0x0EFE, "word", 3))
        self.assertEqual(a[-1][:2], (-4, "fetch"))
        # a refresh's row address is a label the model counts from its own anchor: not compared
        self.assertTrue(any(x[1] == "refresh" for x in a))
        self.assertTrue(all(x[2] == 0 for x in a if x[1] == "refresh"))
        self.assertTrue(all(e.addr for e in s.pre if e.kind == "refresh"))
        self.assertEqual(pre_score(s, s), (True, len(a), len(a)))
        # a model run without the prelude's tail has an empty pre list: never exact
        t = normalize(self.run_of("F18", "F18-a-push-fc-empty-pE-w0"))
        t.pre = []
        self.assertEqual(pre_score(s, t), (False, 0, len(a)))
        self.assertEqual(pre_score(s, None), (False, 0, len(a)))

    def test_pre_window_one_per_prelude(self):
        # the pre window is the prelude's: the same at both parities and in every chain of
        # one prelude (RFM, WTC)
        seen = {}
        for family in ("F0", "F1"):
            for run in load_runs(family):
                n = normalize(run)
                k = (n.chain.rfm, n.chain.wtc)
                seen.setdefault(k, set()).add(tuple(e.clock for e in n.pre))
        self.assertTrue(seen)
        for k, v in seen.items():
            self.assertEqual(len(v), 1, k)


class ReportTests(unittest.TestCase):
    def test_tables_and_strips_render(self):
        for family in ("F0", "F0w", "F1"):
            ff = _facts(family)
            text = family_tables(ff)
            self.assertIn("pO", text)
            strip_text = strips(ff)
            self.assertIn("|", strip_text)
            json.dumps(jsonable(ff))


if __name__ == "__main__":
    unittest.main()
