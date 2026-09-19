"""Host-side and optional built-Verilator regression gates."""

import struct
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from nuboard.debug import DebugClient
from .runner import ROOT, Harness, SimulationTransport, Transaction, compare_traces, musashi_image
from . import runner


class ComparatorTests(unittest.TestCase):
    def test_unused_byte_is_masked_but_control_and_timing_are_not(self):
        left = [Transaction(100, 0x100, 0xAB00, 6, 130)]
        right = [Transaction(200, 0x100, 0xABFF, 6, 230)]
        self.assertTrue(compare_traces(left, right)["functional_match"])
        right[0].end += 1
        self.assertFalse(compare_traces(left, right)["timing_match"])
        right[0].flags = 7
        self.assertFalse(compare_traces(left, right)["functional_match"])
        self.assertFalse(compare_traces(left, [])["functional_match"])

    def test_failed_capture_is_saved_even_if_poweroff_also_fails(self):
        class DisconnectedBoard:
            closed = False

            def state(self):
                raise RuntimeError("USB disconnected during preflight")

            def power_off(self):
                raise RuntimeError("USB unavailable")

            def close(self):
                self.closed = True

        board = DisconnectedBoard()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "failed.json"
            arguments = ["runner", "--backend", "board", "--suite", directory,
                         "--output", str(output)]
            with patch.object(runner.sys, "argv", arguments), \
                 patch.object(runner, "NuBoard", return_value=board), \
                 patch.object(runner.subprocess, "run"):
                with self.assertRaisesRegex(RuntimeError, "disconnected"):
                    runner.main()
            report = json.loads(output.read_text())
            self.assertFalse(report["completed"])
            self.assertIn("disconnected", report["error"])
            self.assertIn("power-off failed", report["cleanup_error"])
            self.assertTrue(board.closed)


@unittest.skipUnless((ROOT / "build/fpga/m68000/verilator-direct/Vm68000_harness").exists(),
                     "build the Verilator harness first")
class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.transport = SimulationTransport()
        self.debug = DebugClient(self.transport.exchange)
        self.harness = Harness(self.debug)

    def tearDown(self):
        self.transport.close()

    def load_program(self, name):
        binary = (ROOT / f"build/validation/m68000/programs/{name}.bin").read_bytes()
        self.harness.load(musashi_image(binary), (0x300, 0x30F))

    def test_reset_vectors_pass_and_big_endian_readback(self):
        self.load_program("moveq")
        self.assertEqual(self.harness.read_memory("model", 4, 4), b"\x00\x01\x00\x00")
        result = self.harness.run()
        self.assertTrue(result["passed"])
        self.assertEqual([row["address"] for row in result["model_trace"][:4]], [0, 2, 4, 6])
        self.assertTrue(result["trace_complete"])

    def test_trace_window_replay_has_full_run_fingerprint(self):
        self.load_program("and")
        first = self.harness.run()
        self.assertTrue(first["passed"])
        self.assertGreater(first["model_total"], 2048)
        self.assertFalse(first["trace_complete"])
        self.load_program("and")
        second = self.harness.run(capture_start=2048)
        self.assertTrue(second["passed"])
        self.assertEqual(first["model_total"], second["model_total"])
        self.assertEqual(first["model_signature"], second["model_signature"])
        self.assertNotEqual(first["model_trace"], second["model_trace"])

    def test_timeout_and_unarmed_socket_fail_closed(self):
        self.load_program("moveq")
        result = self.harness.run(limit=10)
        self.assertFalse(result["passed"])
        self.assertTrue(result["timeout"])
        with self.assertRaises(RuntimeError):
            self.debug.write16(4, 0x0302)
        with self.assertRaises(RuntimeError):
            self.debug.write16(8, 25)  # Below the NMOS part's minimum clock.

    def test_oversized_image_is_rejected(self):
        with self.assertRaises(ValueError):
            self.harness.load({0: bytes(17 * 4096)})


@unittest.skipUnless((ROOT / "build/fpga/m68000/verilator-spi/Vnuboard_m68000").exists(),
                     "build the SPI simulator first")
class SpiBridgeTests(unittest.TestCase):
    def test_round_trip_malformed_range_and_local_wait(self):
        transport = SimulationTransport(spi=True)
        try:
            debug = DebugClient(transport.exchange)
            self.assertEqual(debug.read16(0), 0x6830)
            payload = bytes(range(256))
            debug.write(0x10000, payload)
            self.assertEqual(debug.read(0x10000, 256), payload)
            for request in (
                b"wrong header",
                struct.pack("<4sBBHI", b"NDB1", 0, 0, 2, 0xFFFFFFFE),
                struct.pack("<4sBBHI", b"NDB1", 1, 0, 256, 0x10000),
                struct.pack("<4sBBHIHHI", b"NDB1", 2, 0, 2, 6, 2, 2, 0),
            ):
                self.assertEqual(transport.exchange(request), b"\x01\x00\x00\x00")
            with self.assertRaisesRegex(RuntimeError, "status=3"):
                debug.wait16(6, 2, 2, 100)
            self.assertEqual(debug.read16(0), 0x6830)  # Recover after errors.
        finally:
            transport.close()


@unittest.skipUnless((ROOT / "build/fpga/m68000/verilator-dual/Vm68000_dual_sim").exists(),
                     "build the dual-model simulator first")
class DualLaneTests(unittest.TestCase):
    def test_both_lanes_and_complete_window_replay(self):
        transport = SimulationTransport(dual=True)
        try:
            harness = Harness(DebugClient(transport.exchange))
            harness.debug.write16(4, 1)
            for name in ("moveq", "movem", "mulu"):
                binary = (ROOT / f"build/validation/m68000/programs/{name}.bin").read_bytes()
                harness.load(musashi_image(binary), (0x300, 0x30F))
                result = harness.run_complete("both")
                self.assertTrue(result["passed"], f"{name}: {result.get('comparison')}")
                self.assertTrue(result["trace_complete"])
                self.assertEqual(len(result["model_trace"]), result["model_total"])
        finally:
            transport.close()


if __name__ == "__main__":
    unittest.main()
