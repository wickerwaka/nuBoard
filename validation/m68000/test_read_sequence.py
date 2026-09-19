"""Regression gates for baseline-subtracted execution-time measurements."""

import copy
import struct
import unittest

from nuboard.debug import DebugClient

from .read_sequence import SOURCE_WORDS, measure_lane, sequence_image, summarize
from .runner import ROOT, Harness, SimulationTransport


class AccountingTests(unittest.TestCase):
    def test_missing_markers_and_unsupported_counts_are_rejected(self):
        with self.assertRaises(ValueError):
            sequence_image(7)
        with self.assertRaisesRegex(RuntimeError, "marker"):
            measure_lane([], 8)


@unittest.skipUnless(
    (ROOT / "build/fpga/m68000/verilator-direct/Vm68000_harness").exists(),
    "build the Verilator harness first",
)
class SimulationTests(unittest.TestCase):
    def test_eight_reads_have_verified_results_and_measurable_increment(self):
        transport = SimulationTransport()
        try:
            harness = Harness(DebugClient(transport.exchange))
            runs = []
            for count in (0, 8):
                harness.load(sequence_image(count))
                result = harness.run()
                self.assertTrue(result["passed"] and result["trace_complete"])
                measurement = measure_lane(result["model_trace"], count)
                runs.append({"read_count": count, "measurements": {"model": measurement}})
                expected = struct.pack(">8H", *SOURCE_WORDS) if count else bytes.fromhex("bbbb") * 8
                self.assertEqual(harness.read_memory("model", 0x300, 16), expected)
                if count:
                    corrupted = copy.deepcopy(result["model_trace"])
                    operand = next(row for row in corrupted if row["flags"] == 0x2F)
                    operand["data"] ^= 1
                    with self.assertRaisesRegex(RuntimeError, "incorrect"):
                        measure_lane(corrupted, 8)
            summary = summarize(runs, ("model",))["model"]
            self.assertEqual(summary["eight_read_increment_ns"], 12800)
            self.assertEqual(summary["eight_read_increment_cpu_clocks"], 64)
            self.assertEqual(summary["operand_start_intervals_ns"], [1600] * 7)
            self.assertEqual(summary["extra_instruction_fetches"], 8)
            self.assertEqual(summary["extra_bus_active_ns"] + summary["extra_gap_ns"], 12800)

            inconsistent = copy.deepcopy(runs[-1])
            inconsistent["measurements"]["model"]["marker_elapsed_ns"] += 20
            with self.assertRaisesRegex(RuntimeError, "repeat"):
                summarize(runs + [inconsistent], ("model",))
        finally:
            transport.close()


if __name__ == "__main__":
    unittest.main()
