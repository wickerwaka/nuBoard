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
        jmp = uasm.enum_value("v35_seq_e", "jmp")
        for i, (r, w) in enumerate(prog.words):
            if w.fields.get("e"):
                # (work order 24) the word after E is the E word's successor: the next address,
                # or a stored post-E word reached by the E word's jump (tail sharing)
                nxt = prog.words[w.fields["tgt"] if w.fields.get("seq") == jmp else i + 1][1]
                self.assertEqual(nxt.fields.get("seq"), disp, f"{r.name}:{w.line}")
                # (qprobe round 6) it may release the opcode the E word popped (ro: a store's N
                # on the model's boundary word), nothing else
                for k in ("pop", "e", "f", "rl"):
                    self.assertFalse(nxt.fields.get(k), f"{r.name}:{nxt.line} {k}")
                # (qprobe round 6, EU_HOLD) it posts an I/O write only (OUT's: the cycle after the
                # boundary), and never waits by bi (rule 10's G withdrawn)
                self.assertFalse(nxt.fields.get("bi"), f"{r.name}:{nxt.line} bi")
                self.assertIn(nxt.fields.get("bus", 0), (0, uasm.enum_value("v35_bus_e", "iow")),
                              f"{r.name}:{nxt.line} bus")

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

    def test_no_dispm(self):
        # (qprobe round 17, timing) the sequencer has no DISPM source (the second level on the
        # byte a word pops, the loader's d2ent): no ROM word is DISPM, uasm rejects the flag, and
        # the generated decode has no whole-opcode numbers
        prog = uasm.assemble()
        dm = uasm.enum_value("v35_seq_e", "dispm")
        self.assertFalse([r.name for r, w in prog.words if w.fields.get("seq") == dm])
        with self.assertRaises(uasm.UasmError):
            uasm.parse_word("dispm", "t", 1)
        self.assertNotIn("v35_udec2_fx", uasm.decode_svh(prog))

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
        # (qprobe rule 6) silicon's 12 + 2n (74 at n = 31, the qprobe SHL AW,CL runs): the fourth
        # word is a B word of its own (it waits while a fetch cycle runs)
        self.assertEqual(uasm.length(prog, "shift_cl", 0), 10)
        self.assertEqual(uasm.length(prog, "shift_cl", 4), 20)
        self.assertEqual(uasm.length(prog, "shift_cl", 31), 74)

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
                # (qprobe round 6) the qprobe socket runs are silicon's direct measurement too
                # (validation/v35s/qprobe, the receipts named by group: "the qprobe ld16 runs")
                self.assertRegex(why, r"(a6|v35s-eu-timing|v35s-chains|F[0-9]|the qprobe \w+)",
                                 f"{name} {path}")
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
                "    ea=BI ra=BASE rb=INDEX ; the add\n"
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
                self.assertRegex(why, r"(a6|v35s-eu-timing|v35s-chains|F[0-9]|M[0-9]|the qprobe \w+)",
                                 r.name)


class EA(unittest.TestCase):
    """(MX1) the effective address: the heads pop and return, the routine's first word adds."""

    def test_heads_pop_and_return_only(self):
        prog = uasm.assemble()
        allowed = {"pop", "seq", "tgt", "rl"}     # (qprobe rule 3) rl: a pop releases its byte
        # (qprobe round 6) the ea=q heads also carry the request word (rl=x with bi) and the add
        allowed_q = allowed | {"bi", "ea", "ra", "rb"}
        for name in uasm.EA_HEADS:
            r = prog.routine(name)
            for w in r.words:
                self.assertEqual(set(w.fields) - (allowed_q if name.startswith("eaq") else allowed),
                                 set(), f"{name}:{w.line}")
            self.assertEqual(r.words[-1].fields.get("seq"), uasm.enum_value("v35_seq_e", "ret"))

    def test_q_heads_are_the_measured_shape(self):
        """(qprobe round 6) ea=q: four words in every mode, the request word (rl=x bi) second,
        the add third, the displacement's release (0, 1, 2 bytes: its pops') on the fourth."""
        prog = uasm.assemble()
        bi = uasm.enum_value("v35_ea_e", "bi")
        for name, n in (("eaq0", 0), ("eaq8", 1), ("eaq16", 2)):
            r = prog.routine(name)
            self.assertEqual(len(r.words), 4, name)
            self.assertEqual(r.words[1].fields.get("rl"), uasm.RL_X, name)
            self.assertTrue(r.words[1].fields.get("bi"), name)
            self.assertEqual(r.words[2].fields.get("ea"), bi, name)
            self.assertEqual(sum(1 for w in r.words if w.fields.get("pop")), n, name)
            self.assertEqual(r.words[3].fields.get("rl", 0), n, name)
            self.assertEqual(sum(w.fields.get("rl", 0) for w in r.words[:3]
                                 if w.fields.get("rl") != uasm.RL_X), 0, name)

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
            if uasm.is_mem(r) and r.head.get("ea") == "q":
                # (qprobe round 6) the add is the head's (word 3); the routine's first word posts
                self.assertTrue(r.words[0].fields.get("bus"), r.name)
                self.assertFalse(any(w.fields.get("ea") for w in r.words), r.name)
                self.assertFalse(any(w.fields.get("pop") in disp for w in r.words), r.name)
            elif uasm.is_mem(r):
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
            self.assertEqual(d["eaq"], int(mem and r.head.get("ea") == "q"))   # (qprobe round 6)

    def test_path_ea_clocks(self):
        # the EA's clocks per path: the book's EA (3 3 4 3) with mod 00's book error (2), or
        # the pops and the add alone (1 2 3 3)
        prog = uasm.assemble()
        # (MX1b) ld and st on the model's positions: [BW] 11 / 8, a displacement +1
        # (qprobe round 6) ea=q: the measured shapes, every mode alike (model_m.py L_* / S_*:
        # the read four clocks after the request word on word 2, F, E: 10; the store's post on
        # word 5, E on word 6 held to the write's end at W = 0 on the chip: 10)
        for name, want in (("ld", {"m00": 10, "d8": 10, "d16": 10, "dir": 10}),
                           ("st", {"m00": 10, "d8": 10, "d16": 10, "dir": 10})):
            for path, n in want.items():
                self.assertEqual(uasm.length(prog, name, path=path), n, (name, path))


class TailSharing(unittest.TestCase):
    """(work order 24) the shared ROM executes, from every entry, the same words as the unshared
    one, clock for clock: the two expanded side by side through every branch (both outcomes of
    every condition, loop, take point and EAC, a call's callee and its return point, every
    decode cell's entry, every label) and compared field for field. The only freedom is the
    one the sequencer gives for nothing: a word whose successor is reached by NEXT may reach it
    by JMP (the same next-address clock), and the target fields name the shared addresses."""

    # the next-address rule of v35_useq (upc_n), written out here apart from uasm's pass
    SQ = {k[3:].lower(): v for k, v in uasm.ENUMS["v35_seq_e"][1].items()}

    def succ(self, f: dict, a: int) -> list:
        sq = {v: k for k, v in self.SQ.items()}[f.get("seq", 0)]
        t = f.get("tgt", 0)
        if sq == "next" or sq == "trap":
            return [a + 1]
        if sq == "jmp":
            return [t]
        if sq in ("jc", "jnc", "loop", "tki", "eac", "call"):
            return [t, a + 1]
        self.assertIn(sq, ("ret", "disp"))
        return []

    def norm(self, f: dict) -> dict:
        sq = f.get("seq", 0)
        g = {k: v for k, v in f.items() if v and k not in ("seq", "tgt")}
        g["seq"] = self.SQ["next"] if sq == self.SQ["jmp"] else sq
        # tgt as data (a vector; zero on a word with no vector) unless the word's sequencing
        # reads it as an address
        addr = {self.SQ[k] for k in ("jmp", "jc", "jnc", "loop", "tki", "eac", "call")}
        g["tgt"] = 0 if sq in addr else f.get("tgt", 0)
        return g

    def entries(self, flat, sh):
        """(flat entry, shared entry) of every label and every decode cell; the cells' other
        fields equal."""
        pairs = [(flat.labels[k], sh.labels[k]) for k in flat.labels]
        for op in range(256):
            a, b = uasm.udec1(flat, op), uasm.udec1(sh, op)
            pairs.append((a.pop("entry"), b.pop("entry")))
            self.assertEqual(a, b, hex(op))
            if a["has_modrm"] or op == 0x0F or op in uasm.REP_XC:
                for x in range(256):
                    a, b = uasm.udec2(flat, op, x), uasm.udec2(sh, op, x)
                    pairs.append((a.pop("entry"), b.pop("entry")))
                    self.assertEqual(a, b, (hex(op), hex(x)))
        return pairs

    def test_every_entry_expands_to_the_same_words(self):
        sh = uasm.assemble()
        flat = uasm.assemble(share=False)
        self.assertIsNotNone(sh.flat)
        self.assertEqual(len(flat.words), len(sh.flat.words))
        todo = self.entries(flat, sh)
        seen = set()
        while todo:
            a, b = todo.pop()
            if (a, b) in seen:
                continue
            seen.add((a, b))
            fa, fb = flat.words[a][1].fields, sh.words[b][1].fields
            self.assertEqual(self.norm(fa), self.norm(fb), (flat.name_of(a), b, sh.name_of(b)))
            sa, sb = self.succ(fa, a), self.succ(fb, b)
            self.assertEqual(len(sa), len(sb))
            todo += zip(sa, sb)
        # every shared word is reached from an entry, or holds only unshared words no entry
        # reaches (the placeholders "kept so no address moves")
        reach = {a for a, _ in seen}
        dead = {sh.where[a] for a in range(len(flat.words)) if a not in reach}
        self.assertEqual(set(range(len(sh.words))) - {b for _, b in seen}, dead - {b for _, b in seen})
        print(f"\n(work order 24) {len(flat.words)} words -> {len(sh.words)} "
              f"({len(sh.copies)} copies); {len(seen)} (unshared, shared) pairs expanded; "
              f"{len(flat.words) - len(reach)} unshared words reached from no entry")

    def test_each_source_word_sits_on_an_equal_word(self):
        # the address map (where) puts every source word on a word equal to it, the fall-through
        # pairs adjacent, and the owners list every source word on its address
        sh = uasm.assemble()
        flat = sh.flat
        for i, (r, w) in enumerate(flat.words):
            self.assertEqual(self.norm(w.fields), self.norm(sh.words[sh.where[i]][1].fields), i)
        n = sum(len(v) for v in sh.owners.values())
        self.assertEqual(n, len(flat.words))
        shared = [a for a, v in sh.owners.items() if len({x for x, _ in v}) > 1]
        self.assertGreater(len(shared), 100)
        self.assertIn("|", sh.name_of(shared[0]))

    def test_the_repp_word_is_rep_p_alone(self):
        # v35_top compares the address with UROM_REPP: rep_lk's and rep_sx's E words are the same
        # bits as rep_p's, so rep_p's word is never shared or copied
        sh = uasm.assemble()
        a = sh.labels["rep_p"]
        self.assertEqual([x for x, _ in sh.owners[a]], ["rep_p"])
        self.assertNotIn(a, sh.copies)
        for x in ("rep_lk", "rep_sx"):
            if x in sh.labels:
                self.assertNotEqual(sh.labels[x], a, x)
                self.assertNotIn("rep_p", [y for y, _ in sh.owners[sh.labels[x]]], x)

    def test_book_rows_are_the_unshared_ones(self):
        sh = uasm.assemble()
        self.assertEqual(uasm.book_rows(sh), uasm.book_rows(sh.flat))

    def test_derived_bnext_marks_are_unchanged(self):
        # nb on a non-E word is derived from its successors' kinds; on the shared layout the
        # derivation gives the same marks
        sh = uasm.assemble()
        words = []
        for r, w in sh.words:
            f = dict(w.fields)
            if not f.get("e"):
                f.pop("nb", None)
            words.append((r, uasm.Word(f, w.act, w.line)))
        uasm._mark_bnext(words)
        for (_, a), (_, b) in zip(sh.words, words):
            self.assertEqual(a.fields.get("nb", 0), b.fields.get("nb", 0))

    def test_unshared_switch(self):
        flat = uasm.assemble(share=False)
        self.assertIsNone(flat.flat)
        self.assertEqual(flat.where, list(range(len(flat.words))))
        self.assertLess(len(uasm.assemble().words), len(flat.words))


if __name__ == "__main__":
    unittest.main()
