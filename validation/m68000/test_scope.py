"""Reference encoding, archived replay, and the actual simulated BRAM path."""

import json
import random
import struct
import unittest

from nuboard.debug import DebugClient

from .runner import ROOT, Harness, SimulationTransport
from .scope import Capture, Scope, encode_samples, events
from .timing import memory_moves_image, decode_word, operand_intervals


def capture_of(values):
    raw = encode_samples(values)
    return Capture("model", "complete", 0, len(values)-1, 0,
                   len(raw)//8, len(raw)//8, 0, raw)


class EncodingTests(unittest.TestCase):
    def test_change_expiry_terminal_and_coincident_expiry(self):
        values = [3] * 4095 + [4] * 4096 + [7]
        capture = capture_of(values)
        self.assertEqual(list(events(capture.raw)), [(0, 3), (4095, 4), (8190, 4), (8191, 7)])
        self.assertEqual([value for _, value in capture.window()], values)

    def test_random_full_snapshots_and_window(self):
        rng = random.Random(68000)
        values = []
        value = 0
        for _ in range(10000):
            if rng.randrange(10) == 0:
                value = rng.getrandbits(52)
            values.append(value)
        capture = capture_of(values)
        self.assertEqual([value for _, value in capture.window(777, 1234)], values[777:1234])

    def test_malformed_records(self):
        for raw in (b"x", struct.pack("<Q", 1 << 52), struct.pack("<QQ", 0, 1)):
            with self.assertRaises(ValueError):
                list(events(raw))
        with self.assertRaises(ValueError):
            encode_samples([1 << 52])

    def test_incomplete_capture_does_not_claim_complete(self):
        capture = Capture("socket", "overflow", 100, 105, 106, 1, 1, 32768,
                          struct.pack("<Q", 7))
        self.assertFalse(capture.complete)
        self.assertEqual(list(capture.window()), [(tick, 7) for tick in range(100, 106)])

    def test_replay_archived_paired_samples_exactly(self):
        path = ROOT / "build/validation/m68000/read-sequence-board-build-6.json"
        if not path.exists():
            self.skipTest("archived board capture unavailable")
        for run in json.loads(path.read_text())["runs"]:
            pairs = list(struct.iter_unpack("<QQ", bytes.fromhex(run["scope_hex"])))
            for lane in (0, 1):
                values = [row[lane] for row in pairs]
                capture = capture_of(values)
                self.assertEqual([value for _, value in capture.window()], values)
                self.assertLess(len(capture.raw), len(pairs) * 8)


class DownloadTests(unittest.TestCase):
    def test_wrong_scope_abi_is_rejected(self):
        class FakeDebug:
            def read16(self, address):
                return 3
        with self.assertRaisesRegex(RuntimeError, "ABI 4"):
            Scope(FakeDebug())

    def test_download_crosses_bank_boundary_without_duplicate_records(self):
        raw = encode_samples(range(9000))

        class FakeDebug:
            bank = 0
            selected_banks = []

            def wait16(self, address, mask, expected, timeout):
                return 4

            def read16(self, address):
                return {0x30: 4, 0x62: 0x11, 0x36: 1}[address]

            def write16(self, address, value):
                self.assert_bank_address(address)
                self.bank = value
                self.selected_banks.append(value)

            @staticmethod
            def assert_bank_address(address):
                if address != 0x38:
                    raise AssertionError("unexpected write")

            def read(self, address, length):
                if address == 0x64:
                    return struct.pack("<6I", 9000, 9000, 0, 8999, 0, 9000)
                if address == 0x80:
                    return bytes(8)
                if address != 0x50000 or length > 65536:
                    raise AssertionError("invalid banked read")
                offset = self.bank * 65536
                return raw[offset:offset + length]

        debug = FakeDebug()
        capture = Scope(debug).download()
        self.assertEqual(debug.selected_banks, [0, 1])
        self.assertEqual(capture.raw, raw)
        self.assertTrue(capture.complete)


@unittest.skipUnless((ROOT / "build/fpga/m68000/verilator-direct/Vm68000_harness").exists(),
                     "build Verilator harness first")
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.transport = SimulationTransport()
        self.debug = DebugClient(self.transport.exchange)
        self.harness = Harness(self.debug)
        self.scope = Scope(self.debug)

    def tearDown(self):
        self.transport.close()

    def test_capture_does_not_change_cpu_execution(self):
        self.harness.load(memory_moves_image())
        baseline = self.harness.run()
        self.scope.configure("model")
        self.harness.load(memory_moves_image())
        captured = self.harness.run()
        capture = self.scope.download()
        self.assertTrue(capture.complete)
        self.assertEqual(baseline["model_trace"], captured["model_trace"])
        samples = [{"model": decode_word(value)} for _, value in capture.window()]
        operands = operand_intervals(samples, "model")
        self.assertEqual([row["data"] for row in operands], [0xA55A, 0xA55A])
        self.assertEqual([row["as_low_ns"] for row in operands], [500, 700])
        self.assertEqual(self.scope.download().raw, capture.raw)
        with self.assertRaises(RuntimeError):
            self.debug.write16(0x50000, 0)
        self.debug.write16(0x38, 3)
        with self.assertRaises(RuntimeError):
            self.debug.read16(0x50000)

    def test_selected_window_and_empty_window(self):
        self.scope.configure("model", 256, 767)
        self.harness.load(memory_moves_image())
        self.harness.run()
        capture = self.scope.download()
        self.assertEqual((capture.first_tick, capture.last_tick), (256, 767))
        self.assertEqual(len(list(capture.window())), 512)
        self.scope.configure("model", 100000, 100100)
        self.harness.load(memory_moves_image())
        self.harness.run()
        empty = self.scope.download()
        self.assertEqual(empty.raw, b"")
        self.assertTrue(empty.complete)

    def test_invalid_settings_are_rejected(self):
        for address, value in ((0x36, 3), (0x38, 4)):
            with self.assertRaises(RuntimeError):
                self.debug.write16(address, value)
        self.scope.configure("socket")
        with self.assertRaises(RuntimeError):
            self.harness.run("model")


if __name__ == "__main__":
    unittest.main()
