"""(MX0) The microprogram assembler (uasm.py): the checked-in outputs, the word's round trip,
bounds, the decode's coverage and the book check.

    PYTHONPATH=host/src:. python3 -m unittest validation.v35s.chains.test_uasm
"""

from __future__ import annotations

import re
import unittest

from . import uasm


class Outputs(unittest.TestCase):
    def test_checked_in_outputs_are_the_assembly(self):
        prog = uasm.assemble()
        self.assertEqual(uasm.check(prog), [], "run python -m validation.v35s.chains.uasm")

    def test_word_layout_is_the_package(self):
        # the field list read from v35_pkg.sv sums to UWORD_BITS and fits the banks
        self.assertLessEqual(uasm.WORD_BITS, uasm.BANKS * uasm.BANK_BITS)
        names = [n for n, _, _ in uasm.FIELDS]
        self.assertEqual(len(names), len(set(names)))
        for need in ("ra", "rb", "wr", "alu", "bus", "pop", "e", "f", "seq", "cnt", "tgt"):
            self.assertIn(need, names)


class RoundTrip(unittest.TestCase):
    def test_pack_unpack(self):
        prog = uasm.assemble()
        for _, w in prog.words:
            v = uasm.pack(w.fields)
            back = uasm.unpack(v)
            for k, x in w.fields.items():
                self.assertEqual(back[k], x, k)
            self.assertEqual(uasm.pack(back), v)

    def test_banks_reassemble_the_word(self):
        prog = uasm.assemble()
        banks = [b.split() for b in uasm.rom_banks(prog)]
        for i, (_, w) in enumerate(prog.words):
            v = sum(int(banks[b][i], 16) << (uasm.BANK_BITS * b) for b in range(uasm.BANKS))
            self.assertEqual(v, uasm.pack(w.fields))


class Bounds(unittest.TestCase):
    def test_rom_size_and_targets(self):
        prog = uasm.assemble()
        self.assertLessEqual(len(prog.words), 1 << uasm.UADDR_W)
        for _, w in prog.words:
            if "tgt" in w.fields:
                self.assertLess(w.fields["tgt"], len(prog.words))

    def test_one_word_after_each_e_and_it_is_the_dispatch(self):
        prog = uasm.assemble()
        disp = uasm.enum_value("v35_seq_e", "disp")
        for i, (r, w) in enumerate(prog.words):
            if w.fields.get("e"):
                nxt = prog.words[i + 1][1]
                self.assertEqual(nxt.fields.get("seq"), disp, f"{r.name}:{w.line}")
                for k in ("pop", "bus", "e", "f"):
                    self.assertFalse(nxt.fields.get(k), f"{r.name}:{nxt.line} {k}")

    def test_every_word_names_its_act(self):
        prog = uasm.assemble()
        for r, w in prog.words:
            self.assertTrue(w.act.strip(), f"{r.name}:{w.line}")

    def test_decode_covers_every_cell(self):
        prog = uasm.assemble()
        for op in range(256):
            f = uasm.udec1(prog, op)
            self.assertLess(f["entry"], len(prog.words))
            if f["has_modrm"] or op == 0x0F:
                for b in range(256):
                    self.assertLess(uasm.udec2(prog, op, b)["entry"], len(prog.words))


class NoCounts(unittest.TestCase):
    """The ROM word has no count field; no .uasm word names an opcode."""

    def test_no_count_field_in_the_word(self):
        for name, _, _ in uasm.FIELDS:
            self.assertIsNone(re.search(r"(clk|clock|count|setup|delay|wait|hold|lead|nx|pre)",
                                        name), name)

    def test_no_opcode_literal_in_a_word(self):
        for p in sorted(uasm.UROM.glob("*.uasm")):
            for ln, line in enumerate(p.read_text().splitlines(), 1):
                s = line.strip()
                if not s or s.startswith(";") or s.startswith("routine "):
                    continue          # comments; the routine headers name their opcodes
                code = s.split(";", 1)[0]
                self.assertIsNone(re.search(r"\b(op|opcode|reg|rm|mod)\s*=", code),
                                  f"{p.name}:{ln}")
                self.assertIsNone(re.search(r"=(0x[0-9A-Fa-f]+|[0-9A-Fa-f]{2}h?)\b", code),
                                  f"{p.name}:{ln}")


class BookCheck(unittest.TestCase):
    """Every routine with book= has the data book's length at EA = 3, W = 0 plus the declared
    difference, the difference's reason written beside it."""

    def test_book_lengths(self):
        prog = uasm.assemble()
        rows = uasm.book_rows(prog)
        self.assertGreater(len(rows), 30)
        for name, form, bv, ln, diff, why, _ in rows:
            if bv is None:
                continue
            self.assertEqual(ln, bv + diff, f"{name} ({form}): length {ln}, book {bv}, "
                                            f"declared {diff:+d}")
            if diff:
                self.assertTrue(why, f"{name}: a difference without its reason")

    def test_open_words_are_declared(self):
        # a word without an act the sources name is marked OPEN, and its routine's reason says so
        prog = uasm.assemble()
        for r in prog.routines:
            if any(w.open for w in r.words):
                self.assertIn("OPEN", r.head.get("why", ""), r.name)

    def test_length_counts_the_shift_loop(self):
        prog = uasm.assemble()
        # (MX0d) the book's 11 + 2n; at n = 0 the zero test skips the loop and the write
        # (MX0e) silicon's 10 at n = 0 less the stall: 9 (one book clock on the loop's path)
        self.assertEqual(uasm.length(prog, "shift_cl", 0), 9)
        self.assertEqual(uasm.length(prog, "shift_cl", 4), 19)
        self.assertEqual(uasm.length(prog, "shift_cl", 31), 73)

    def test_declared_differences_name_silicon(self):
        # (MX0e) the book is the first draft; a routine is shorter than the book only where
        # silicon's direct measurement (the a6 sweep, docs/v35s-eu-timing.md, the chain
        # families) shows the clock absent, and the reason names that measurement; never
        # longer (a clock is added only as a named act or an OPEN book clock); never a fit
        prog = uasm.assemble()
        rows = [r for r in uasm.book_rows(prog) if r[4]]
        print("\n(MX0e) the declared differences: " + ", ".join(f"{r[0]} {r[4]:+d}" for r in rows))
        for name, form, bv, ln, diff, why, _ in rows:
            self.assertLess(diff, 0, name)
            self.assertRegex(why, r"(a6|v35s-eu-timing|v35s-chains|F[0-9])", name)
            self.assertIn("book error", why, name)
            self.assertNotRegex(why, r"\bfit", name)


if __name__ == "__main__":
    unittest.main()
