"""V35S timing gate tests, independent of the Efinity installation."""

import unittest

from tools.check_v35s_build import check_clock_relationships, check_pins


REPORT = """Setup (Max) Clock Relationship
  clk_sys clk_sys 30.000 1.000 (R-R)
  spi_sck spi_sck 100.000 50.000 (R-R)
Hold (Min) Clock Relationship
  clk_sys clk_sys 0.000 0.086 (R-R)
NOTE:
"""


def path(begin, end, constraint):
    return (f"++++ Path\nPath Begin : {begin}|CLK\nPath End : {end}|D\n"
            f"Launch Clock : clk_sys (RISE)\nCapture Clock : clk_sys (RISE)\n"
            f"Constraint : {constraint}\n")


class TimingTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(check_clock_relationships(REPORT), [1, 50, 0.086])

    def test_negative_slack(self):
        with self.assertRaises(ValueError):
            check_clock_relationships(REPORT.replace("30.000 1.000", "30.000 -0.1"))

    def test_core_multicycle_is_declared(self):
        check_clock_relationships(REPORT + path("harness/model/core/u_eu/a~FF",
                                                "harness/model/core/u_biu/b~FF", "80.000"))
        check_clock_relationships(REPORT + path("harness/model/core/u_biu/a~FF",
                                                "harness/model/engine~FF", "80.000"))

    def test_other_multicycle_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "relaxed"):
            check_clock_relationships(REPORT + path("harness/socket_lane/a~FF",
                                                    "harness/socket_lane/b~FF", "80.000"))
        with self.assertRaisesRegex(ValueError, "relaxed"):
            check_clock_relationships(REPORT + path("harness/model/x_count~FF",
                                                    "harness/model/core/u_eu/a~FF", "80.000"))


class PinTests(unittest.TestCase):
    def test_pins(self):
        isf = 'design.assign_pkg_pin("t1[6]", "A9")\n'
        self.assertEqual(check_pins("| A9 | t1[6] | x |", isf), 1)
        with self.assertRaises(ValueError):
            check_pins("| A9 | t1[5] | x |", isf)


if __name__ == "__main__":
    unittest.main()
