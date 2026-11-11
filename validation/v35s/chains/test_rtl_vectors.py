"""D1 and D2 (HDL plan, Phase D): the functional reference (funcref.py: nuV30's semantics,
checked against the frozen model's timing quantities, silicon's data and SingleStepTests) and,
when the core v2's whole-core bench is built (fpga/v35s/build_core2_tb.sh), the --regfile vectors
and a sample of SingleStepTests on it (rtl_vectors.py). The first RTL attempt's bench tests (the
chain core's bus unit, queue, EU and whole core: C1 to C5, and the old unit bench's mutations)
were retired with that core (docs/v35s-core-v2.md, S7). The gates' full runs:
python -m validation.v35s.chains.rtl_vectors --regfile and --fn, funcref --silicon, sst and sst
--rtl."""

from __future__ import annotations

import unittest

from validation.v35s.chains import rtl_vectors

# (WP75) the lists of the whole corpus: F0, F0w, F1 .. F31 (F30 and F31 the probe families);
# (WP79) and F32, F33: 35 lists, 28,142 runs
ALL_FAMILIES = ("F0", "F0w") + tuple(f"F{i}" for i in range(1, 34))


class FunctionalReference(unittest.TestCase):
    """(D2) funcref.py: nuV30's semantics against the frozen model's timing quantities, silicon's
    data and the ALU's laws."""

    def test_agrees_with_the_frozen_execute_over_the_corpus(self):
        """Every instruction start of the whole corpus (every family, the prelude's tail first,
        the string forms included): the quantities the timing depends on (the memory operand's
        address, the port, the stack offsets, the shift count, a transfer's decision and target,
        a string form's start registers, element count and exit) are the frozen model's; and
        every data cycle's datum (a write's, a read's delivered word, on the cycle's lanes) is
        silicon's."""
        from validation.v35s.chains import funcref
        tot = funcref.agree_corpus(ALL_FAMILIES, silicon=True)
        self.assertGreater(tot["runs"], 28000)
        self.assertGreater(tot["starts"], 700000)
        self.assertEqual((tot["bad"], tot["nm"], tot["trap"]), (0, 0, 0), tot["first"])
        self.assertGreater(tot["scyc"], 90000)
        self.assertEqual(tot["seq"], tot["scyc"], tot["first"])
        self.assertEqual(tot["sbad"], 0, tot["first"])

    def test_alu_laws(self):
        """A few of nuV30's results by hand: ADD's carries and overflow, SUB's borrow, the
        logic forms clearing CY V AC, INC keeping CY, ROLC through the carry, SHL's V, SHR by
        more than the width, MULU leaving S Z AC P, MUL's S Z AC P of the low half's self-add,
        DIVU's pre-check flags and trap, DIV's symmetric range trap."""
        from validation.v35s.chains import funcref as fr
        r, f = fr.alu(0, 0x7FFF, 1, 2, 0xF002)
        self.assertEqual((r, f & fr.ARITH), (0x8000, (1 << fr.V) | (1 << fr.S) | (1 << fr.AC)
                                              | (1 << fr.P)))
        r, f = fr.alu(5, 0, 1, 1, 0)
        self.assertEqual(r, 0xFF)
        self.assertTrue(f & (1 << fr.CY) and f & (1 << fr.S) and f & (1 << fr.AC))
        _, f = fr.alu(4, 0xFF, 0x0F, 1, 0xFFFF)
        self.assertEqual(f & ((1 << fr.CY) | (1 << fr.V) | (1 << fr.AC)), 0)
        _, f = fr.incdec(False, 0xFFFF, 2, 1 << fr.CY)
        self.assertTrue(f & (1 << fr.CY) and f & (1 << fr.Z))
        r, f = fr.shift(2, 0x80, 1, 1, 0)                       # ROLC 80h: CY 1, AL 0
        self.assertEqual((r, f & 1), (0x00, 1))
        r, f = fr.shift(4, 0x4000, 1, 2, 0)                     # SHL: V = MSB ^ CY
        self.assertTrue(f & (1 << fr.V))
        r, f = fr.shift(5, 0xFFFF, 17, 2, 0)
        self.assertEqual((r, f & 1), (0, 0))
        p, f = fr.mul(False, 0xFF, 0xFF, 1, 0x00D5)
        self.assertEqual((p, f & 0x00D4, f & 0x0801), (0xFE01, 0x00D4, 0x0801))
        p, f = fr.mul(True, 0x80, 0x7F, 1, 0)                   # C080h: lo 80h: Z 1, S 0
        self.assertEqual(p, 0xC080)
        self.assertTrue(f & (1 << fr.Z) and not f & (1 << fr.S))
        q, rem, f, trap = fr.div(False, 0x0100, 0x01, 1, 0)    # AH 1 >= 1: the trap
        self.assertTrue(trap)
        q, rem, f, trap = fr.div(False, 0x1234, 0x56, 1, 0)
        self.assertEqual((q, rem, trap), (0x1234 // 0x56, 0x1234 % 0x56, False))
        self.assertTrue(f & (1 << fr.CY))                       # SUB(12h, 56h) borrows
        self.assertTrue(fr.div(True, 0x3C15, 0x88, 1, 0)[3])   # quotient -128 traps
        for cc in range(16):
            self.assertNotEqual(fr.cond(cc, 0), fr.cond(cc ^ 1, 0))


@unittest.skipUnless((rtl_vectors.ROOT / "build" / "deps" / "sst-v20" / "v1_native" / "00.json.gz")
                     .exists(), "SingleStepTests not fetched: tools/fetch_sst_v20.py")
class SingleStepTests(unittest.TestCase):
    """(D2) the V20 suite: the reference (and, built, the unit bench) on a sample of files."""
    FILES = ("01", "2B", "81.3", "C1.2", "D3.7", "F7.6", "F7.7", "F6.5", "8F", "61", "C3", "7C",
             # (WP79) the 0F page and the register miscellany
             "0F15", "0F1A", "0F20", "0F22", "0F26", "0F33", "0F39", "27", "3F", "D4", "D5", "6B")

    def test_reference_passes(self):
        from validation.v35s.chains import sst
        res = sst.check_funcref(self.FILES, show=0)
        for stem, counts in res.items():
            self.assertEqual(counts.get("fail", 0), 0, (stem, counts))
            self.assertGreater(counts.get("pass", 0), 1900, (stem, counts))

    @unittest.skipUnless(rtl_vectors.C2BENCH.exists(),
                         "bench not built: fpga/v35s/build_core2_tb.sh")
    def test_rtl_passes(self):
        res = rtl_vectors.check_sst(self.FILES, show=0)
        for stem, counts in res.items():
            self.assertFalse([k for k in counts if k.startswith("rtl fail")], (stem, counts))
            if stem in self.LATER:
                # a form a later package builds (the trap routine pops its bytes: trap_nop, not
                # compared): every test of the file is one, none ran wrong
                ran = sum(v for k, v in counts.items() if k == "pass" or k.startswith("trap_nop"))
                self.assertGreater(ran, 1900, (stem, counts))
                continue
            # (MX1) the memory forms built: the 1900-pass bar, pass alone (sst.py --rtl: MX4)
            self.assertGreater(counts.get("pass", 0), 1900, (stem, counts))

    # (MX1) the files whose forms are a later package's (docs/v35s-mechanisms.md section 8):
    # RET, the branch (MX2); the 0F page (MX3; the adjusts, the converts and MUL imm built at
    # MX3 part 2: 27 3F D4 D5 6B pass)
    LATER = {"C3": "MX2", "7C": "MX2", "0F15": "MX3", "0F1A": "MX3", "0F20": "MX3",
             "0F22": "MX3", "0F26": "MX3", "0F33": "MX3", "0F39": "MX3"}


@unittest.skipUnless(rtl_vectors.C2BENCH.exists(), "bench not built: fpga/v35s/build_core2_tb.sh")
class RegfileBench(unittest.TestCase):
    def test_every_form_against_the_reference(self):
        """(S6) the whole-core bench (check_regfile: each vector a single instruction on
        v35_top) against the functional reference on every instruction start of the corpus's
        chains, every encoding on random register files and memory, the 24 ModR/M memory modes
        on the address-computing forms and random operands on every ALU form."""
        bad, counts, out = rtl_vectors.check_regfile(ALL_FAMILIES)
        self.assertEqual(bad, 0, out[-1500:])
        self.assertGreater(counts["walk"], 1000)
        self.assertGreater(counts["modes"], 24 * 8)
        self.assertGreater(counts["alu"], 3000)


if __name__ == "__main__":
    unittest.main()
