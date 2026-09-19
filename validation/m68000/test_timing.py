"""Checks for passive waveform capture and its host-side interpretation."""

import unittest

from nuboard.debug import DebugClient

from .runner import ROOT, Harness, SimulationTransport
from .scope import Scope
from .timing import (
    decode_word,
    decode_capture,
    memory_moves_image,
    minimal_image,
    operand_intervals,
    read_intervals,
    read_scope,
)


class DecoderTests(unittest.TestCase):
    def test_signal_bit_positions(self):
        word = 0x123456 | (0xABCD << 24) | (6 << 46) | (1 << 49)
        word |= (1 << 43) | (1 << 45)
        decoded = decode_word(word)
        self.assertEqual(decoded["address"], 0x123456)
        self.assertEqual(decoded["data"], 0xABCD)
        self.assertEqual(decoded["fc"], 6)
        self.assertEqual(decoded["clock"], 1)
        self.assertEqual(decoded["read"], 1)
        self.assertEqual(decoded["as_n"], 0)
        self.assertEqual(decoded["dtack_n"], 0)


@unittest.skipUnless(
    (ROOT / "build/fpga/m68000/verilator-direct/Vm68000_harness").exists(),
    "build the scope-enabled Verilator harness first",
)
class ScopeTests(unittest.TestCase):
    def test_delayed_capture_records_memory_read_and_write_without_changing_bus(self):
        transport = SimulationTransport()
        try:
            debug = DebugClient(transport.exchange)
            harness = Harness(debug)
            self.assertEqual(debug.read16(0x30), 4)
            scope = Scope(debug)
            scope.configure("model", 0, 511)
            harness.load(memory_moves_image())
            before = harness.run()
            first_samples = [{"model": decode_word(value)}
                             for _, value in scope.download().window()]

            scope.configure("model", 256, 767)
            harness.load(memory_moves_image())
            after = harness.run()
            delayed = [{"model": decode_word(value)}
                       for _, value in scope.download().window()]
            self.assertTrue(before["passed"] and after["passed"])
            self.assertEqual(before["model_trace"], after["model_trace"])
            self.assertEqual(first_samples[256:], delayed[:256])
            self.assertEqual(harness.read_memory("model", 0x200, 4), bytes.fromhex("a55a a55a"))
            operands = operand_intervals(delayed, "model")
            self.assertEqual([(row["address"], row["read"]) for row in operands],
                             [(0x200, 1), (0x202, 0)])
            self.assertEqual([row["data"] for row in operands], [0xA55A, 0xA55A])
            self.assertEqual([row["as_low_ns"] for row in operands], [500, 700])
            self.assertEqual([row["uds_n_low_ns"] for row in operands], [500, 500])
        finally:
            transport.close()

    def test_repeatable_capture_freezes_and_is_read_only(self):
        transport = SimulationTransport()
        try:
            debug = DebugClient(transport.exchange)
            harness = Harness(debug)
            scope = Scope(debug)
            scope.configure("model", 0, 511)
            captures = []
            for _ in range(3):
                harness.load(minimal_image())
                result = harness.run()
                self.assertTrue(result["passed"])
                self.assertTrue(result["trace_complete"])
                capture = scope.download()
                raw = capture.raw
                samples = [{"model": decode_word(value)} for _, value in capture.window()]
                reads = read_intervals(samples, "model")
                # Reset/idle address and data levels are not bus transfers and
                # may retain the previous run's values. Compare control edges
                # and acknowledged read data, not those unspecified levels.
                controls = [
                    [sample["model"][name] for name in (
                        "clock", "as_n", "uds_n", "lds_n", "read", "dtack_n",
                    )]
                    for sample in samples[reads[0]["start_tick"]:]
                ]
                captures.append((reads, controls))
                self.assertEqual([row["address"] for row in reads[:2]], [0, 2])
                self.assertEqual([row["data"] for row in reads[:2]], [0, 0x3F0])
                self.assertEqual([row["as_low_ns"] for row in reads[:2]], [500, 500])
                self.assertEqual(reads[1]["start_tick"] - reads[0]["start_tick"], 40)
                self.assertEqual(scope.download().raw, raw)
            self.assertEqual(captures[0], captures[1])
            self.assertEqual(captures[1], captures[2])
            with self.assertRaises(RuntimeError):
                debug.write16(0x50000, 0)
            with self.assertRaises(RuntimeError):
                debug.read16(0x52000)
        finally:
            transport.close()


if __name__ == "__main__":
    unittest.main()
