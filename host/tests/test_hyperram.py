import struct
import unittest

from nuboard import hyperram
from nuboard.device import NuBoardError


class HyperRamTests(unittest.TestCase):
    def test_command_layout(self):
        payload = hyperram.pack_command(hyperram.OP_WRITE, 2, 0x12345678,
                                        5, 200)
        self.assertEqual(len(payload), 16)
        self.assertEqual(payload[:4], bytes([3, 2, 0, 0]))
        self.assertEqual(struct.unpack("<III", payload[4:]),
                         (0x12345678, 5, 200))

    def test_command_range_checks(self):
        with self.assertRaises(ValueError):
            hyperram.pack_command(hyperram.OP_TEST, first_burst=-1)

    def test_result_layout(self):
        payload = bytearray(56)
        payload[0:4] = bytes([0, 0, 1, 0b011])
        struct.pack_into("<HHHHIIII", payload, 4, 150, 45, 512, 64,
                         4096, 3, 1, 0x1234)
        struct.pack_into("<HHHHHH", payload, 28, 0xaaaa, 0xaaab, 0x0001,
                         0x0c83, 0x0001, 4)
        struct.pack_into("<IIII", payload, 40, 25000, 30000, 7, 8)
        result = hyperram.unpack_result(bytes(payload))
        self.assertEqual((result.mhz, result.phase), (150, 45))
        self.assertEqual((result.burst_words, result.user_width,
                          result.buffers), (512, 64, 4))
        self.assertEqual((result.words, result.errors, result.missing),
                         (4096, 3, 1))
        self.assertEqual(result.first_error_address, 0x1234)
        self.assertEqual((result.id0, result.id1), (0x0c83, 0x0001))
        self.assertEqual((result.write_cycles, result.read_cycles,
                          result.seed, result.bursts), (25000, 30000, 7, 8))
        # 8 bursts of 512 words = 8192 bytes in 25000 cycles at 50 MHz.
        self.assertEqual(result.write_mb_per_s, 16.4)
        self.assertTrue(result.pll_locked and result.init_done)
        self.assertFalse(result.busy or result.ok)
        self.assertEqual(result.as_dict()["id0"], "0x0c83")

    def test_result_length_checked(self):
        with self.assertRaises(NuBoardError):
            hyperram.unpack_result(bytes(48))


if __name__ == "__main__":
    unittest.main()
