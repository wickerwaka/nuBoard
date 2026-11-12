"""F0 harness tests: the input schedule, serial stimulus, pin records, the
INTAK answer and the dump routine.

Offline tests always run. The simulation tests need the Verilator builds
(fpga/v35s/build_sim.sh direct, dual) and skip without them; the scripted-bus
regression of the same RTL is fpga/v35s/v35s_lane_tb.sv (fpga/v35s/test.sh).
"""

import struct
import unittest
from pathlib import Path

from validation.v35s import dump
from validation.v35s.asm import assemble
from validation.v35s.runner import (
    FLAG_PIN, INPUTS, PINS, ROOT, DebugClient, Harness, ScheduleEntry, SimulationTransport,
    Transaction, compare_programs, level_bits, load_stimulus, pin_mask, pin_sequence,
    reset_image, uart_bits,
)

PROGRAMS = ROOT / "validation/v35s/programs/f0"


class ScheduleTests(unittest.TestCase):
    def test_entry_words(self):
        entry = ScheduleEntry(event=3, levels={"INT": 1, "NMI": 0}, delay=0x123456,
                              hold=70000, serial=(1,))
        self.assertEqual(entry.words(), [0x203, 0x3456, 0x12, 70000 & 0xFFFF, 1,
                                         0b100010, 0b100000, 0])

    def test_chained_entry(self):
        self.assertEqual(ScheduleEntry(None, {}).words()[0], 0xFF)
        with self.assertRaises(ValueError):
            ScheduleEntry(255, {}).words()
        with self.assertRaises(ValueError):
            ScheduleEntry(1, {}, delay=1 << 24).words()

    def test_level_bits(self):
        self.assertEqual(level_bits(RxD0=0, CTS1=1), (0x1200, 0x1000))
        self.assertEqual(len(INPUTS), 13)

    def test_uart_bits(self):
        self.assertEqual(uart_bits(b"\x55", idle=1), [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1])
        bits = uart_bits(b"\x01", data_bits=7, parity="even", stop_bits=2, idle=0)
        self.assertEqual(bits, [0, 1, 0, 0, 0, 0, 0, 0, 1, 1, 1])
        self.assertEqual(uart_bits(b"\x00", parity="odd", idle=0)[9], 1)


class PinTests(unittest.TestCase):
    def test_pin_mask(self):
        self.assertEqual(pin_mask("TXD0", "P07"), (1 << 24) | 0x80)
        self.assertEqual(pin_mask("INTAK"), pin_mask("P13"))
        # Every named pin is in the all-pins mask, and nothing else.
        everything = 0
        for bit in PINS.values():
            everything |= 1 << bit
        self.assertEqual(pin_mask(), everything)

    def test_pin_record(self):
        record = struct.pack("<IHHHHI", 500, 0x0011, FLAG_PIN << 4, 0x0100, 0, 500)
        row = Transaction.unpack(record)
        self.assertEqual((row.kind, row.pins), ("pins", 0x0100_0011))
        self.assertIn("01000011", row.describe())

    def test_pin_sequences_compare(self):
        a = [Transaction(0, 0x11, FLAG_PIN, 0x100, 0, 0)]
        b = [Transaction(9, 0x11, FLAG_PIN, 0x100, 0, 9)]
        c = [Transaction(9, 0x12, FLAG_PIN, 0x100, 0, 9)]
        self.assertEqual(pin_sequence(a), [0x0100_0011])
        self.assertTrue(compare_programs(a, b)["pin_sequence_match"])
        self.assertFalse(compare_programs(a, c)["pin_sequence_match"])
        # Pin records are not writes.
        self.assertEqual(compare_programs(a, c)["writes"], [0, 0])


class DumpTests(unittest.TestCase):
    def test_directive_expands(self):
        code = assemble("    DUMPSTATE\n    HALT\n", org=0x100)
        self.assertEqual(code[-1], 0xF4)
        self.assertEqual(code[:5], bytes([0x2E, 0xA3, 0x02, 0x0A, 0x2E]))   # MOV PS:[0A02h],AW
        short = assemble("    DUMPSTATE P0, TM0\n", org=0x100)
        # P0 is one byte, TM0 two: three SFR copies of 3 + 1 + 3 bytes.
        self.assertEqual(len(code) - 1 - len(short), 7 * (len(dump._sfr_bytes(dump.DEFAULT_SFRS)) - 3))

    def test_unknown_sfr(self):
        with self.assertRaises(ValueError):
            dump.routine(["NOPE"])

    def test_sfr_map(self):
        # Spot checks against the data book's Table 6.
        self.assertEqual((dump.SFR["INTM"], dump.SFR["TMIC0"], dump.SFR["PRC"], dump.SFR["ISPR"]),
                         (0x40, 0x9C, 0xEB, 0xFC))

    def test_decode(self):
        raw = bytearray(dump.DUMP_LENGTH)
        struct.pack_into("<H", raw, 7 * 0x20 + 0x1E, 0x1111)     # bank 7 AW
        struct.pack_into("<H", raw, 2 * 0x20 + 0x16, 0x0800)     # bank 2 SP
        raw[0x100 + 0xEB] = 0x4E                                  # PRC
        struct.pack_into("<H", raw, 0x100 + 0xE8, 0xFFFF)        # WTC
        raw[0x200] = 0xFF
        struct.pack_into("<H", raw, 0x20E, 0x7002)
        named = dump.decode(bytes(raw))
        self.assertEqual(named["banks"][7]["AW"], 0x1111)
        self.assertEqual(named["banks"][2]["SP"], 0x0800)
        self.assertEqual((named["sfr"]["PRC"], named["sfr"]["WTC"]), (0x4E, 0xFFFF))
        self.assertEqual((named["idb"], named["bank"]), (0xFF, 7))
        other = dump.decode(bytes(raw[:0x100 + 0xEB] + b"\x4F" + raw[0x100 + 0xEC:]))
        self.assertEqual(dump.differences(named, other), ["sfr.PRC"])


def _binary(variant):
    top = {"direct": "v35s_harness", "dual": "v35s_dual_sim"}[variant]
    return ROOT / f"build/fpga/v35s/verilator-{variant}/V{top}"


class SimTest(unittest.TestCase):
    variant = "dual"

    def setUp(self):
        if not _binary(self.variant).exists():
            self.skipTest(f"build with fpga/v35s/build_sim.sh {self.variant}")
        self.transport = SimulationTransport(self.variant)
        self.harness = Harness(DebugClient(self.transport.exchange), strict=True)
        self.harness.configure()
        if self.variant == "dual":
            self.harness.arm()

    def tearDown(self):
        self.transport.close()

    def run_program(self, name, stimulus=None, limit=2_000_000):
        self.harness.load(reset_image(assemble((PROGRAMS / name).read_text(), org=0x100)))
        load_stimulus(self.harness, stimulus)
        return self.harness.run_complete("both", limit)


class DualSimTests(SimTest):
    def test_schedule_raises_int(self):
        import json
        spec = json.loads((PROGRAMS / "sched_int.stim.json").read_text())
        result = self.run_program("sched_int.s", spec)
        self.assertTrue(result["passed"])
        stimulus = result["stimulus"]
        for lane in ("socket", "model"):
            self.assertEqual(stimulus[f"{lane}_events"], 2)
            self.assertEqual(stimulus[f"{lane}_unmatched"], 0)
            self.assertEqual(stimulus[f"{lane}_status"] & 0x3F, 2)      # both entries ran
        self.assertEqual(self.harness.read_memory("socket", 0x400, 2), b"\x34\x12")

    def test_without_schedule_int_never_comes(self):
        # Control: the same program with no schedule waits in HALT forever.
        result = self.run_program("sched_int.s", None, limit=200_000)
        self.assertFalse(result["passed"])
        self.assertTrue(result["timeout"])

    def test_dump(self):
        result = self.run_program("dump.s")
        self.assertTrue(result["passed"])
        self.assertTrue(result["program_comparison"]["dump_region_match"])
        socket = dump.read(self.harness, "socket")
        model = dump.read(self.harness, "model")
        self.assertEqual(dump.differences(socket, model), [])
        bank = socket["banks"][socket["bank"]]
        self.assertEqual((bank["AW"], bank["CW"], bank["IX"], bank["IY"], bank["DS1"]),
                         (0x1111, 0x2222, 0x6666, 0x7777, 0))
        self.assertEqual(socket["saved"]["AW"], 0x1111)
        self.assertEqual(socket["idb"], 0xFF)


class DirectSimTests(SimTest):
    variant = "direct"

    def test_registers(self):
        harness = self.harness
        self.assertEqual(harness.version, 2)
        entries = [ScheduleEntry(1, {"NMI": 0}, delay=5, hold=7),
                   ScheduleEntry(None, {"RXD1": 1}, serial=(1,))]
        harness.load_schedule(entries, intak_vector=0x20, int_release=True,
                              rxd1=(uart_bits(b"\xA5"), 400))
        debug = harness.debug
        self.assertEqual(struct.unpack("<16H", debug.read(0x60000, 32)),
                         tuple(entries[0].words() + entries[1].words()))
        self.assertEqual(debug.read16(0xA0), 0x0302)
        self.assertEqual(debug.read16(0xA2), 0x20)
        self.assertEqual((debug.read16(0xA6), debug.read16(0xAA)), (400, 11))
        bits = uart_bits(b"\xA5")
        self.assertEqual(debug.read16(0x60300), sum(b << i for i, b in enumerate(bits)))
        harness.record_pins(pin_mask("TXD0", "TXD1"))
        self.assertEqual(struct.unpack("<I", debug.read(0xAC, 4))[0], 0x0300_0000)
        # Rejected: more than 32 entries, a bit time under 2, a pattern over 2048 bits.
        for address, value in ((0xA0, 33), (0xA4, 1), (0xA8, 2049)):
            with self.assertRaises(Exception):
                debug.write16(address, value)
        # Levels at rest follow register 8E in both lanes.
        debug.write16(0x8E, 0x1E1D)
        self.assertEqual((debug.read16(0xBE), debug.read16(0xC0)), (0x1E1D, 0x1E1D))
        harness.clear_schedule()
        self.assertEqual(debug.read16(0xA0), 0)

    def test_model_lane_schedule(self):
        # The model lane alone follows its own events (direct build, socket idle).
        import json
        spec = json.loads((PROGRAMS / "sched_int.stim.json").read_text())
        self.harness.load(reset_image(assemble((PROGRAMS / "sched_int.s").read_text(), org=0x100)))
        load_stimulus(self.harness, spec)
        result = self.harness.run_complete("model", 2_000_000)
        self.assertTrue(result["passed"])
        self.assertEqual(result["stimulus"]["model_events"], 2)
        self.assertEqual(result["stimulus"]["socket_events"], 0)


if __name__ == "__main__":
    unittest.main()
