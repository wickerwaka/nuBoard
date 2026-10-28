"""statestats: one F0 run (refresh off) and one F8 run (refresh on) through the reducer."""

from __future__ import annotations

import unittest

from validation.v35s.chains import statestats
from validation.v35s.chains.normalize import load_runs
from validation.v35s.chains.sim import machine
from validation.v35s.chains.sim.config import Config


def _first(family: str, waits: int) -> dict:
    return load_runs(family, (waits,))[0]


class StateStatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config.fitted()
        cls.f0 = statestats.run_stats(_first("F0", 0), cls.cfg)
        cls.f8 = statestats.run_stats(_first("F8", 0), cls.cfg)

    def test_one_run_each_no_error(self):
        for st in (self.f0, self.f8):
            self.assertEqual(st.runs, 1)
            self.assertEqual(st.errors, [])
            self.assertGreater(st.clocks, 50)
        self.assertEqual(self.f0.exact, 1)          # every F0 run is exact under the fit

    def test_machine_is_restored(self):
        self.assertEqual(machine.Machine.__name__, "Machine")

    def test_clock_row_keys_and_machine_attributes(self):
        v = self.f0.values
        # every key of Machine._clock_row (t aside; req split in three)
        for k in ("bus", "queued", "occ", "room", "inflight", "flag", "requested_at",
                  "latched", "ir", "need", "pc", "cls", "k", "step", "resume", "sync",
                  "started_now", "clk_tag", "clk_start", "clk_end", "took", "ir_load", "b2b"):
            self.assertIn("row." + k, v, k)
        for k in ("row.req.kind", "row.req.count", "row.req.setup"):
            self.assertIn(k, v)
        for k in ("queue.latched", "queue.bytes.len", "decoder.need", "eu.since_start",
                  "eu.req.count", "bus.current", "bus.current.pos"):
            self.assertIn(k, v, k)
        self.assertNotIn("refresh.pending", v)      # refresh off: no fifth machine

    def test_known_ranges_f0(self):
        v = self.f0.values
        self.assertLessEqual(max(v["queue.bytes.len"]), 7)     # 6 stored + 1 latched
        self.assertTrue(set(v["queue.latched"]) <= {0, 1})     # word_latch=byte_d
        self.assertEqual(set(v["eu.req.lead"]), {2})           # out.lead (the END's OUT DW)
        self.assertTrue(set(v["bus.current"]) <= {None, "fetch", "read", "write",
                                                  "io_read", "io_write"})
        self.assertTrue(set(v["row.step"]) <= {None, "clocks", "take", "data", "post",
                                               "post_io", "slot", "issued", "wait",
                                               "wbsync", "nowait", "halt"})
        offs = [x for x in v["row.requested_at"] if isinstance(x, int)]
        self.assertTrue(all(x <= 0 for x in offs))             # a past clock, as an offset

    def test_refresh_run_f8(self):
        v = self.f8.values
        self.assertIn("refresh.pending", v)
        self.assertIn("refresh", set(v["bus.current"]))
        self.assertEqual(set(v["refresh.interval"]), {16})      # RFM FCh: RFT 0
        self.assertIn("refresh_eu", self.f8.reads["F8"])
        self.assertNotIn("refresh_eu", self.f0.reads["F0"])

    def test_summary_merges(self):
        st = statestats.Stats()
        st.merge(self.f0)
        st.merge(self.f8)
        s = statestats.summarize(st)
        self.assertEqual(s["runs"], 2)
        self.assertEqual(s["clocks"], self.f0.clocks + self.f8.clocks)
        room = s["vars"]["row.room"]
        self.assertEqual(room["kind"], "int")
        self.assertLessEqual(room["min"], room["p50"])
        self.assertLessEqual(room["p50"], room["max"])
        self.assertEqual(s["vars"]["queue.requested_at"]["kind"], "clock offset")
        self.assertIn("eu.since_start", statestats.table(s))


if __name__ == "__main__":
    unittest.main()
