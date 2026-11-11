"""(MX0) The microprogram assembler (uasm.py): the checked-in outputs, the word's round trip,
bounds, the decode's coverage and the book check; (MX1) the per-path book check of the memory
forms and the EA heads.

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
    difference, the difference's reason written beside it. (MX1) A memory routine is checked
    on each path (m00 mod 00 at EA 3, d8 mod 01 at EA 3, d16 mod 10 at EA 4, dir the direct
    address at EA 3), its declared difference the routine's per path plus its EA head's."""

    def test_book_lengths(self):
        prog = uasm.assemble()
        rows = uasm.book_rows(prog)
        self.assertGreater(len(rows), 30)
        for name, form, bv, ln, diff, why, _, path, _ in rows:
            if bv is None:
                continue
            self.assertEqual(ln, bv + diff, f"{name} {path} ({form}): length {ln}, book {bv}, "
                                            f"declared {diff:+d}")
            if diff:
                self.assertTrue(why, f"{name}: a difference without its reason")

    def test_two_valued_transfers_checked_on_both_paths(self):
        # (MX2) a transfer whose book form prints two values ("8 or 15": the smaller not taken,
        # the larger taken) is checked on its taken path (the format's condition true) and its
        # not-taken path (false), each against its own value; the taken path ends with the FLUSH,
        # the book machine counting the refill's first fetch before the E word's pop
        prog = uasm.assemble()
        rows = uasm.book_rows(prog)
        two = [r for r in prog.routines if uasm.book_paths(r) == uasm.XPATHS]
        self.assertGreaterEqual(len(two), 4)            # Bcond, DBNZ, DBNZE, BCWZ
        for r in two:
            got = {row[7]: row for row in rows if row[0] == r.name}
            self.assertEqual(set(got), {"t", "nt"}, r.name)
            vals = uasm.book_values()[r.head["book"]]["values_printed"]
            self.assertEqual(got["t"][2], max(vals), r.name)
            self.assertEqual(got["nt"][2], min(vals), r.name)
            self.assertLess(got["nt"][3], got["t"][3], r.name)
            taken = uasm.path_words(prog, r.name, path="t")
            self.assertTrue(any(w.fields.get("flush") for w in taken), r.name)
            self.assertFalse(any(w.fields.get("flush")
                                 for w in uasm.path_words(prog, r.name, path="nt")), r.name)

    def test_open_words_are_declared(self):
        # a word without an act the sources name is marked OPEN, and its routine's reason says so
        prog = uasm.assemble()
        for r in prog.routines:
            if any(w.open for w in r.words) and r.name not in uasm.EA_HEADS:
                self.assertIn("OPEN", r.head.get("why", ""), r.name)

    def test_open_words_reported(self):
        # (MX1) the agenda: OPEN words per routine and in total (MX0 122)
        ow = uasm.open_words(uasm.assemble())
        print(f"\n(MX1) OPEN words: {sum(ow.values())} in {len(ow)} routines: "
              + ", ".join(f"{k} {v}" for k, v in sorted(ow.items())))
        self.assertGreater(sum(ow.values()), 0)

    def test_length_counts_the_shift_loop(self):
        prog = uasm.assemble()
        # (MX0d) the book's 11 + 2n; at n = 0 the zero test skips the loop and the write
        # (MX0e) silicon's 10 at n = 0 less the stall: 9 (one book clock on the loop's path)
        # (MX1b) the shifter's load on a word of its own: silicon's 12 + 2n, 10 at n = 0
        # (MX1f) the book's 11 + 2n again: silicon's twelfth clock is the take sync's wait for
        # the word the ModR/M pop's room asked for (F3-push-nop-k4-pE-w0 +112: 74 at n = 31)
        self.assertEqual(uasm.length(prog, "shift_cl", 0), 9)
        self.assertEqual(uasm.length(prog, "shift_cl", 4), 19)
        self.assertEqual(uasm.length(prog, "shift_cl", 31), 73)

    def test_declared_differences_name_silicon(self):
        # (MX0e) the book is the first draft; a routine is shorter than the book only where
        # silicon's direct measurement (the a6 sweep, docs/v35s-eu-timing.md, the chain
        # families) shows the clock absent, and the reason names that measurement; never a fit.
        # (MX1) a path longer than the book only by named acts: no OPEN word on it, the reason
        # naming the acts beyond the book (the displacement's pops the book's EA does not
        # resolve)
        prog = uasm.assemble()
        rows = [r for r in uasm.book_rows(prog) if r[4]]
        print("\n(MX1) the declared differences: " + ", ".join(
            f"{r[0]}{'.' + r[7] if r[7] else ''} {r[4]:+d}" for r in rows))
        for name, form, bv, ln, diff, why, _, path, opens in rows:
            self.assertNotRegex(why, r"\bfit", name)
            if diff < 0:
                self.assertRegex(why, r"(a6|v35s-eu-timing|v35s-chains|F[0-9])", f"{name} {path}")
                self.assertIn("book error", why, f"{name} {path}")
            else:
                # (MX1b) the words beyond the book are named acts, declared as such: the pops
                # the book's EA does not resolve, or "beyond the book: a named act ..." (the
                # path's OPEN words then stay the book's own clocks, none added past it)
                # (MX1b) or silicon longer than the book, measured: the frozen model exact on a
                # run the reason names (its positions), the extra clocks OPEN
                self.assertRegex(why, r"(pops?\b|beyond the book: a named act|silicon longer "
                                      r"than the book)", f"{name} {path}: the acts beyond the book")
                if opens:
                    self.assertRegex(why, r"(beyond the book: a named act|silicon longer than the "
                                          r"book|F[0-9]+-\S+-w[0-9])",
                                     f"{name} {path}: {diff:+d} over the book with {opens} OPEN "
                                     "words, neither a named act nor a measured run declared")

    def test_a_positive_difference_with_an_open_word_is_rejected(self):
        # the rule's check on a routine written to break it: one OPEN word on a path over the book
        text = ("routine bad op=8A,8B mod=mem book=\"MOV reg,mem\" diff=1 why=\"two pops\"\n"
                "    ea=BI ra=BASE rb=INDEX resv ; the add\n"
                "    open ; OPEN: a book clock\n"
                "    bus=MEMR ; post\n"
                "    f d1=TA s1=OPR ; F\n"
                "    wr=REG ws=TA e ; E\n")
        import tempfile
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as d:
            paths = sorted(uasm.UROM.glob("*.uasm"))
            body = (uasm.UROM / "mem.uasm").read_text().replace("op=8A,8B mod=mem", "op=8A mod=mem")
            files = []
            for p in paths:
                q = P(d) / p.name
                q.write_text(body if p.name == "mem.uasm" else p.read_text())
                files.append(q)
            # 8B is free in the copy: the bad routine claims it
            text = text.replace("op=8A,8B", "op=8B")
            (P(d) / "zz.uasm").write_text(text)
            files.append(P(d) / "zz.uasm")
            prog = uasm.assemble(files)
            rows = [r for r in uasm.book_rows(prog) if r[0] == "bad" and r[4] > 0]
            self.assertTrue(rows)
            self.assertTrue(any(r[8] > 0 for r in rows))   # the test above would fail on it

    def test_measured_alone_is_not_a_reason(self):
        prog = uasm.assemble()
        for r in prog.routines:
            why = r.head.get("why", "")
            if "diff" in r.head and "measured" in why:
                self.assertRegex(why, r"(a6|v35s-eu-timing|v35s-chains|F[0-9]|M[0-9])", r.name)


class EA(unittest.TestCase):
    """(MX1) the effective address: the heads pop and return, the routine's first word adds."""

    def test_heads_pop_and_return_only(self):
        prog = uasm.assemble()
        allowed = {"pop", "seq", "tgt"}
        for name in uasm.EA_HEADS:
            r = prog.routine(name)
            for w in r.words:
                self.assertEqual(set(w.fields) - allowed, set(), f"{name}:{w.line}")
            self.assertEqual(r.words[-1].fields.get("seq"), uasm.enum_value("v35_seq_e", "ret"))

    def test_head_lengths_are_the_pops_and_the_book(self):
        prog = uasm.assemble()
        book = {"eab0": 1, "eab8": 2, "eab16": 2, "ea8": 1, "ead": 2}     # (MX1b) eab16: no OPEN
        pops = {"eab0": 0, "eab8": 1, "eab16": 2, "ea8": 1, "ead": 2}
        for name, n in book.items():
            r = prog.routine(name)
            self.assertEqual(len(r.words), n, name)
            self.assertEqual(sum(1 for w in r.words if w.fields.get("pop")), pops[name], name)
            self.assertEqual(sum(1 for w in r.words if w.open), n - pops[name], name)

    def test_memory_routines_start_with_the_add(self):
        prog = uasm.assemble()
        bi = uasm.enum_value("v35_ea_e", "bi")
        disp = (uasm.enum_value("v35_pop_e", "dl"), uasm.enum_value("v35_pop_e", "dh"))
        for r in prog.routines:
            if uasm.is_mem(r):
                self.assertEqual(r.words[0].fields.get("ea"), bi, r.name)
                self.assertFalse(r.words[0].fields.get("bus"), r.name)
                self.assertFalse(any(w.fields.get("pop") in disp for w in r.words), r.name)

    def test_decode_cells_call_the_heads(self):
        prog = uasm.assemble()
        for (op, b), name in prog.cells2.items():
            if op == 0x0F:
                continue
            r = prog.routine(name)
            d = uasm.udec2(prog, op, b)
            mem = uasm.is_mem(r) and b >> 6 != 3
            self.assertEqual(d["ea"], int(mem), (hex(op), hex(b), name))
            self.assertEqual(d["eab"], int(mem and r.head.get("ea", "book") == "book"))

    def test_path_ea_clocks(self):
        # the EA's clocks per path: the book's EA (3 3 4 3) with mod 00's book error (2), or
        # the pops and the add alone (1 2 3 3)
        prog = uasm.assemble()
        # (MX1b) ld and st on the model's positions: [BW] 11 / 8, a displacement +1
        for name, want in (("ld", {"m00": 11, "d8": 12, "d16": 12, "dir": 12}),
                           ("st", {"m00": 8, "d8": 9, "d16": 9, "dir": 9})):
            for path, n in want.items():
                self.assertEqual(uasm.length(prog, name, path=path), n, (name, path))


if __name__ == "__main__":
    unittest.main()
