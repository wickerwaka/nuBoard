"""Offline tests of the V35S host tools: record decoding, comparison, images."""

import struct
import unittest

from validation.v35s.runner import (
    FLAG_COL_A9, FLAG_IO, FLAG_READ, FLAG_REFRESH, FLAG_STROBE, FLAG_UBE_N,
    BANK_D, BANK_Z, Transaction, compare_traces, port_modes, reset_image,
)
from validation.v35s.scope import decode


def record(start, address, flags, data, strobe, end):
    return struct.pack("<IHHHHI", start, address & 0xFFFF,
                       (flags << 4) | (address >> 16), data, strobe, end)


class TransactionTests(unittest.TestCase):
    def test_unpack_fields(self):
        row = Transaction.unpack(record(10, 0xFFFF2, FLAG_READ | FLAG_STROBE, 0x0001, 48, 203))
        self.assertEqual((row.start, row.address, row.data, row.strobe, row.end),
                         (10, 0xFFFF2, 0x0001, 48, 203))
        self.assertEqual(row.kind, "mem-read")

    def test_kinds(self):
        self.assertEqual(Transaction(0, 0x200, FLAG_REFRESH | FLAG_READ, 0, 192, 193).kind,
                         "refresh")
        self.assertEqual(Transaction(0, 0xFF00, FLAG_IO | FLAG_STROBE, 0, 48, 193).kind,
                         "io-write")

    def test_refresh_address_is_not_functional(self):
        a = Transaction(0, 0x200, FLAG_REFRESH, 0, 192, 193)
        b = Transaction(0, 0x400, FLAG_REFRESH, 0, 192, 193)
        self.assertEqual(a.functional, b.functional)

    def test_column_a9_pin_is_not_functional(self):
        a = Transaction(0, 0x100, FLAG_READ | FLAG_STROBE, 0x90, 48, 193)
        b = Transaction(0, 0x100, FLAG_READ | FLAG_STROBE | FLAG_COL_A9, 0x90, 48, 193)
        self.assertEqual(a.functional, b.functional)

    def test_describe_byte_lanes(self):
        odd = Transaction(0, 0x403, FLAG_STROBE, 0x3400, 145, 193)
        self.assertIn(" hi ", odd.describe() + " ")
        self.assertNotIn("lo", odd.describe().split()[4])
        even_byte = Transaction(0, 0x404, FLAG_STROBE | FLAG_UBE_N, 0x0012, 145, 193)
        self.assertIn("lo", even_byte.describe())


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.trace = [Transaction(100 + 240 * i, 0xFFFF0 + 2 * i, FLAG_READ | FLAG_STROBE,
                                  i, 48, 293 + 240 * i) for i in range(4)]

    def test_identical_and_shifted(self):
        shifted = [Transaction(t.start + 7, t.address, t.flags, t.data, t.strobe, t.end + 7)
                   for t in self.trace]
        result = compare_traces(self.trace, shifted)
        self.assertTrue(result["functional_match"])
        self.assertTrue(result["timing_match"])

    def test_data_difference(self):
        changed = list(self.trace)
        changed[2] = Transaction(**{**changed[2].__dict__, "data": 0xBEEF})
        result = compare_traces(self.trace, changed)
        self.assertFalse(result["functional_match"])
        self.assertEqual(result["differences"][0]["index"], 2)

    def test_timing_difference(self):
        changed = list(self.trace)
        changed[1] = Transaction(**{**changed[1].__dict__, "strobe": 60})
        result = compare_traces(self.trace, changed)
        self.assertTrue(result["functional_match"])
        self.assertEqual(result["timing_difference_indices"], [1])

    def test_length_difference(self):
        result = compare_traces(self.trace, self.trace[:3])
        self.assertFalse(result["functional_match"])


class ImageTests(unittest.TestCase):
    def test_reset_vector(self):
        image = reset_image(b"\x90", origin=0x00100)
        self.assertEqual(image[0xFFFF0], bytes([0xEA, 0x00, 0x01, 0x00, 0x00]))
        self.assertEqual(image[0x00100], b"\x90")

    def test_segment_origin(self):
        image = reset_image(b"\x90", origin=0x12340, segment=0x1000)
        self.assertEqual(image[0xFFFF0], bytes([0xEA, 0x40, 0x23, 0x00, 0x10]))

    def test_origin_out_of_segment(self):
        with self.assertRaises(ValueError):
            reset_image(b"\x90", origin=0x20000, segment=0x0000)

    def test_port_modes(self):
        self.assertEqual(port_modes(), 0)
        self.assertEqual(port_modes(t2=BANK_Z), 1)
        self.assertEqual(port_modes(t2=BANK_D, r0=BANK_D), 0x22)


class ScopeTests(unittest.TestCase):
    def test_decode(self):
        value = (0x1234 | (0x1FF << 16) | (1 << 29) | (1 << 33) | (1 << 47))
        fields = decode(value)
        self.assertEqual(fields["data"], 0x1234)
        self.assertEqual(fields["mux"], 0x1FF)
        self.assertEqual(fields["mreq_n"], 1)
        self.assertEqual(fields["x1"], 1)
        self.assertEqual(fields["clkout"], 1)
        self.assertEqual(fields["mstb_n"], 0)


class AssemblerTests(unittest.TestCase):
    def test_v35_extension_expansion(self):
        from validation.v35s.asm import _expand
        self.assertIn("DB 0x0F, 0x92", _expand("    FINT\n"))
        self.assertIn("DB 0xF1", _expand("    BRKS ; enter security mode\n"))
        self.assertIn("MOV AW, 1", _expand("    MOV AW, 1\n"))


class ProbeTests(unittest.TestCase):
    def test_every_suite_builds(self):
        from validation.v35s.probes import SUITES
        from validation.v35s.timing import build
        for name, suite in SUITES.items():
            for case in suite():
                with self.subTest(suite=name, case=case.name, odd=case.odd):
                    _, target, _, _ = build(case)
                    self.assertEqual(target & 1, int(case.odd))

    def test_trap_stubs(self):
        from validation.v35s.timing import CODE_SEGMENT, STUB_SIZE, TRAP_PORT, Case, build
        image, _, next_offset, code = build(Case(name="t", target="    NOP\n", stubs=True))
        vectors = image[0x00000]
        for vector in (0, 7, 19, 31):
            offset, segment = struct.unpack_from("<HH", vectors, vector * 4)
            self.assertEqual(segment, CODE_SEGMENT)
            stub = code[offset:offset + STUB_SIZE]
            self.assertEqual(stub[:8], bytes([0x68, 0x02, 0xF0, 0x9D, 0xB0, vector,
                                              0xE6, TRAP_PORT]))
            rel = struct.unpack_from("<h", stub, 9)[0]
            self.assertEqual((offset + 11 + rel) & 0xFFFF, next_offset)


if __name__ == "__main__":
    unittest.main()
