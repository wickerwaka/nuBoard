"""BRAM-only timing gate tests, independent of the Efinity installation."""

import unittest

from tools.check_m68000_build import check_clock_relationships


class ClockTimingTests(unittest.TestCase):
    def setUp(self):
        self.report = """Setup (Max) Clock Relationship
  clk_50mhz clk_50mhz 20.000 1.000 (R-R)
  spi_sck spi_sck 100.000 50.000 (R-R)
  spi_commit spi_commit 100.000 50.000 (R-R)
Hold (Min) Clock Relationship
  clk_50mhz clk_50mhz 0.000 0.086 (R-R)
NOTE:
"""

    def test_valid_relationships(self):
        self.assertEqual(check_clock_relationships(self.report), [1, 50, 50, 0.086])

    def test_negative_setup(self):
        with self.assertRaises(ValueError):
            check_clock_relationships(self.report.replace("20.000 1.000", "20.000 -0.001"))

    def test_negative_hold(self):
        with self.assertRaises(ValueError):
            check_clock_relationships(self.report.replace("0.086", "-0.001"))

    def test_missing_clock(self):
        with self.assertRaises(ValueError):
            check_clock_relationships(self.report.replace("spi_commit", "spi_sck"))

    def test_unexpected_psram_clock(self):
        with self.assertRaises(ValueError):
            check_clock_relationships(self.report.replace("NOTE:", "  psram_engine psram_engine 10 1 (R-R)\nNOTE:"))

    def test_same_clock_multicycle_is_rejected(self):
        path = "++++ Path\nLaunch Clock : clk_50mhz\nCapture Clock : clk_50mhz\nConstraint : 40.000\n"
        with self.assertRaisesRegex(ValueError, "relaxed"):
            check_clock_relationships(self.report + path)


if __name__ == "__main__":
    unittest.main()
