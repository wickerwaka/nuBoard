"""Fuzz generator, initialization and exact mirrored-memory regression gates."""

import hashlib
import copy
import struct
import unittest

from nuboard.debug import DebugClient
from .fuzz import acquire, bootstrap, compare_runs, cpu_bytes, load_case, make_case
from .runner import ROOT, Harness, SimulationTransport
from .scope import Scope


class GeneratorTests(unittest.TestCase):
    def test_exact_size_vectors_and_random_tail(self):
        for seed in (0, 1, 42, (1 << 64) - 1):
            case = make_case(seed)
            image = bytes.fromhex(case["image_hex"])
            self.assertEqual(case, make_case(seed))
            self.assertEqual(len(image), 1024)
            self.assertEqual(struct.unpack_from(">II", image), (0x400, case["pc"]))
            self.assertTrue(8 <= case["pc"] <= 1022 and not case["pc"] & 1)
            random_bytes = hashlib.shake_256(b"nuBoard-68000-fuzz-v1" + struct.pack("<Q", seed)).digest(1024)
            self.assertEqual(image[8:], random_bytes[8:])
            self.assertEqual(cpu_bytes(cpu_bytes(image)), image)
            self.assertLess(len(bootstrap(case)), 1024)
        self.assertNotEqual(make_case(0)["image_hex"], make_case(1)["image_hex"])

    def test_limits_and_tamper_rejected_before_io(self):
        class NoIO:
            def __getattr__(self, name):
                raise AssertionError("unexpected I/O")

        for cycles in (0, 15, 4001):
            with self.assertRaises(ValueError):
                load_case(NoIO(), make_case(0), cycles)
        case = make_case(0)
        case["image_sha256"] = "wrong"
        with self.assertRaises(ValueError):
            load_case(NoIO(), case, 2000)


@unittest.skipUnless((ROOT / "build/fpga/m68000/verilator-direct/Vm68000_harness").exists(),
                     "build the simulators first")
class FuzzSimulationTests(unittest.TestCase):
    def setUp(self):
        self.transport = SimulationTransport()
        self.debug = DebugClient(self.transport.exchange)
        self.harness = Harness(self.debug)
        self.scope = Scope(self.debug)

    def tearDown(self):
        self.transport.close()

    def run_case(self, case, cycles=2000):
        load_case(self.debug, case, cycles)
        return acquire(self.harness, self.scope, "model", case, cycles)

    def test_seed_replay_and_capacity_bound(self):
        for seed in (0, 1, 2):
            case = make_case(seed)
            a, b = self.run_case(case), self.run_case(case)
            result = compare_runs(a, b)
            self.assertTrue(result["passed"], result)
            self.assertLess(a["capture"]["accepted"], 30001)
            self.assertFalse(a["result"]["timeout"])
            # Host broadcast initially set both lanes. Model writes must not
            # mutate the inactive socket lane's image.
            self.assertEqual(cpu_bytes(self.debug.read(0x20000, 1024)).hex(), case["image_hex"])

    def test_bootstrap_registers_and_aliases_including_old_mmio(self):
        case = make_case(19)
        image = bytearray.fromhex(case["image_hex"])
        case["pc"] = 0x100
        struct.pack_into(">I", image, 4, case["pc"])
        # MOVEM.L D0-D7/A0-A7,$800200; MOVE.W SR,$800240;
        # MOVE USP,A0; MOVE.L A0,$800244;
        # MOVE.W #$1234,$100006 (old pass MMIO must now be ordinary RAM);
        # BRA.S *.
        code = bytes.fromhex("48f9 ffff 0080 0200 40f9 0080 0240 4e68 "
                             "23c8 0080 0244 33fc 1234 0010 0006 60fe")
        image[0x100:0x100 + len(code)] = code
        case.update(image_hex=image.hex(), image_sha256=hashlib.sha256(image).hexdigest())
        run = self.run_case(case)
        ram = bytes.fromhex(run["ram_hex"])
        self.assertEqual(struct.unpack_from(">16I", ram, 0x200),
                         tuple(case["initial_d"] + case["initial_a"]))
        self.assertEqual(struct.unpack_from(">H", ram, 0x240)[0], case["sr"])
        self.assertEqual(struct.unpack_from(">I", ram, 0x244)[0], case["usp"])
        self.assertEqual(ram[6:8], b"\x12\x34")
        self.assertEqual(run["result"]["model_result"], 0)
        self.assertTrue(run["budget_complete"])

    def test_small_clock_budget(self):
        run = self.run_case(make_case(0), cycles=16)
        self.assertTrue(run["budget_complete"])

    def test_extended_clock_budget(self):
        run = self.run_case(make_case(0), cycles=4000)
        self.assertTrue(run["budget_complete"])
        self.assertLess(run["capture"]["accepted"], 32768)

    def test_comparator_rejects_ram_transaction_and_epoch_changes(self):
        reference = self.run_case(make_case(0))

        changed = copy.deepcopy(reference)
        ram = bytearray.fromhex(changed["ram_hex"])
        ram[17] ^= 1
        changed["ram_hex"] = ram.hex()
        result = compare_runs(reference, changed)
        self.assertFalse(result["passed"])
        self.assertEqual(result["ram_differences"][0]["offset"], 17)

        changed = copy.deepcopy(reference)
        changed["trace"][0]["address"] ^= 2
        result = compare_runs(reference, changed)
        self.assertFalse(result["passed"])
        self.assertFalse(result["transactions_match"])

        changed = copy.deepcopy(reference)
        changed["epoch"] -= 1
        with self.assertRaisesRegex(ValueError, "expected CPU edges"):
            compare_runs(reference, changed)


if __name__ == "__main__":
    unittest.main()
