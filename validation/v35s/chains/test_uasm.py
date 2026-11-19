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
    """(work orders 24, 25) the shared ROM executes, from every entry, the same words as the
    unshared one, clock for clock: the two expanded side by side through every branch (both
    outcomes of every condition, loop, take point and EAC, a call into its callee and back
    through the return register, every decode cell's entry, every label) and compared field for
    field. The only freedoms are the ones the sequencer gives for nothing: a word whose
    successor is reached by NEXT may reach it by JMP (the same next-address clock), the target
    fields name the shared addresses, and (work order 25) a NEXT / JMP word may be a CALL to a
    stored run whose last word, a NEXT / JMP word in the unshared program, is a RET back to the
    call's next address, while the return register holds no other return."""

    # the next-address rule of v35_useq (upc_n), written out here apart from uasm's pass
    SQ = {k[3:].lower(): v for k, v in uasm.ENUMS["v35_seq_e"][1].items()}
    SQN = {v: k for k, v in SQ.items()}
    MODES = ("full", "tail")

    def kind(self, f: dict) -> str:
        k = self.SQN[f.get("seq", 0)]
        return "next" if k == "jmp" else k

    def norm(self, f: dict) -> dict:
        sq = self.SQN[f.get("seq", 0)]
        g = {k: v for k, v in f.items() if v and k not in ("seq", "tgt")}
        # tgt as data (a vector; zero on a word with no vector) unless the word's sequencing
        # reads it as an address
        g["tgt"] = 0 if sq in ("jmp", "jc", "jnc", "loop", "tki", "eac", "call") else f.get("tgt", 0)
        return g

    def entries(self, flat, sh):
        """(flat entry, shared entry, return registers) of every label and every decode cell;
        the cells' other fields equal. A label a call or the dispatch enters with a return
        outstanding (a call target, an EA head) starts with the return register taken ("ext")."""
        called = {w.fields.get("tgt") for _, w in flat.words if self.kind(w.fields) == "call"}
        called |= {flat.labels[h] for h in uasm.EA_HEADS if h in flat.labels}
        pairs = []
        for k in flat.labels:
            r = "ext" if flat.labels[k] in called else None
            pairs.append((flat.labels[k], sh.labels[k], r, r))
        for op in range(256):
            a, b = uasm.udec1(flat, op), uasm.udec1(sh, op)
            pairs.append((a.pop("entry"), b.pop("entry"), None, None))
            self.assertEqual(a, b, hex(op))
            if a["has_modrm"] or op == 0x0F or op in uasm.REP_XC:
                for x in range(256):
                    a, b = uasm.udec2(flat, op, x), uasm.udec2(sh, op, x)
                    pairs.append((a.pop("entry"), b.pop("entry"), None, None))
                    self.assertEqual(a, b, (hex(op), hex(x)))
        return pairs

    def step(self, fa, a, ra, fb, b, rb) -> list:
        """The successor states of the pair (a, b) with the return registers ra / rb (None:
        nothing outstanding; "ext": a return to whatever entered the label; an address pair;
        rb ("M", x): a stored run called, returning to x)."""
        ka, kb = self.kind(fa), self.kind(fb)
        ta, tb = fa.get("tgt", 0), fb.get("tgt", 0)
        sa = ta if self.SQN[fa.get("seq", 0)] == "jmp" else a + 1
        sb = tb if self.SQN[fb.get("seq", 0)] == "jmp" else b + 1
        mid = isinstance(rb, tuple)
        if ka == "next" and kb == "call":           # (work order 25) a middle call
            self.assertTrue(ra is None and rb is None, "a middle call with a return outstanding")
            return [(sa, tb, None, ("M", b + 1))]
        if ka == "next" and kb == "ret":            # (work order 25) the stored run's end
            self.assertTrue(mid and ra is None, "a stored run's RET not called")
            return [(sa, rb[1], None, None)]
        self.assertEqual(ka, kb)
        if ka == "next":
            return [(sa, sb, ra, rb)]
        if ka == "trap":
            return [(a + 1, b + 1, ra, rb)]
        if ka in ("jc", "jnc", "loop", "tki"):
            return [(ta, tb, ra, rb), (a + 1, b + 1, ra, rb)]
        self.assertFalse(mid, f"a {ka} inside a stored run")
        if ka == "call":
            self.assertTrue(ra is None and rb is None, "a call with a return outstanding")
            return [(ta, tb, a + 1, b + 1)]
        if ka == "eac":
            self.assertTrue(ra is None and rb is None, "an EAC with a return outstanding")
            return [(ta, tb, None, None), (a + 1, b + 1, None, None)]
        if ka == "ret":
            if ra in (None, "ext") and rb == ra:
                return []                       # back to the entry's caller
            self.assertTrue(isinstance(ra, int) and isinstance(rb, int), (ra, rb))
            return [(ra, rb, None, None)]
        self.assertEqual(ka, "disp")
        return []

    def walk(self, flat, sh):
        todo = self.entries(flat, sh)
        seen = set()
        while todo:
            st = todo.pop()
            if st in seen:
                continue
            seen.add(st)
            a, b, ra, rb = st
            fa, fb = flat.words[a][1].fields, sh.words[b][1].fields
            self.assertEqual(self.norm(fa), self.norm(fb), (flat.name_of(a), b, sh.name_of(b)))
            todo += self.step(fa, a, ra, fb, b, rb)
        return seen

    def test_every_entry_expands_to_the_same_words(self):
        flat = uasm.assemble(share=False)
        for mode in self.MODES:
            sh = uasm.assemble(share=mode)
            self.assertIsNotNone(sh.flat)
            self.assertEqual(len(flat.words), len(sh.flat.words))
            seen = self.walk(flat, sh)
            # every word of both reached from an entry ((work order 25) the placeholders "kept
            # so no address moves" deleted)
            self.assertEqual({a for a, *_ in seen}, set(range(len(flat.words))), mode)
            self.assertEqual({b for _, b, *_ in seen}, set(range(len(sh.words))), mode)
            print(f"\n(work orders 24, 25: {mode}) {len(flat.words)} words -> {len(sh.words)} "
                  f"({len(sh.copies)} copies, {len(sh.mcalls)} middle calls, "
                  f"{len(sh.mshares)} stored runs); {len(seen)} states expanded")

    def test_a_broken_middle_call_is_caught(self):
        # (work order 25) the walk sees a stored run entered one word late, and a middle call
        # made a jump (the run's RET then reached with no call)
        flat = uasm.assemble(share=False)
        for brk in ("tgt", "jmp"):
            sh = uasm.assemble()
            a = min(sh.mcalls)
            f = sh.words[a][1].fields
            if brk == "tgt":
                f["tgt"] += 1
            else:
                f["seq"] = self.SQ["jmp"]
            with self.assertRaises(AssertionError, msg=brk):
                self.walk(flat, sh)

    def test_each_source_word_sits_on_an_equal_word(self):
        # the address map (where) puts every source word on a word equal to it, the fall-through
        # pairs adjacent, and the owners list every source word on its address; (work order 25)
        # a NEXT / JMP word may sit on a middle call or a stored run's RET
        for mode in self.MODES:
            sh = uasm.assemble(share=mode)
            flat = sh.flat
            for i, (r, w) in enumerate(flat.words):
                b = sh.where[i]
                fb = sh.words[b][1].fields
                self.assertEqual(self.norm(w.fields), self.norm(fb), i)
                kb = self.kind(fb)
                if (b in sh.mcalls and kb == "call") or (b in sh.mrets and kb == "ret"):
                    # (a stored run may end in a callee's RET tail: its RET holds both)
                    self.assertIn(self.kind(w.fields), ("next", kb), i)
                else:
                    self.assertEqual(self.kind(w.fields), kb, i)
            n = sum(len(v) for v in sh.owners.values())
            # ((work order 26) a word that cannot jump in L40 runs on into a copy of its successor:
            # the source words sit on the copy and the stored word is named by them too)
            self.assertEqual(n, len(flat.words) + getattr(sh, "l40_named_twice", 0))
            self.assertEqual(len({x for v in sh.owners.values() for x in v}), len(flat.words))
            shared = [a for a, v in sh.owners.items() if len({x for x, _ in v}) > 1]
            self.assertGreater(len(shared), 100)
            self.assertIn("|", sh.name_of(shared[0]))
            # a middle call's return point holds the run's continuation
            for i, s in sh.mcall_sites:
                if sh.where[i] in sh.mcalls:
                    self.assertEqual(self.kind(sh.words[sh.where[i]][1].fields), "call", i)

    def test_the_repp_word_is_rep_p_alone(self):
        # v35_top compares the address with UROM_REPP: rep_lk's and rep_sx's E words are the same
        # bits as rep_p's, so rep_p's word is never shared or copied
        for mode in self.MODES:
            sh = uasm.assemble(share=mode)
            a = sh.labels["rep_p"]
            self.assertEqual([x for x, _ in sh.owners[a]], ["rep_p"])
            self.assertNotIn(a, sh.copies)
            self.assertNotIn(a, sh.mcalls | sh.mruns)
            for x in ("rep_lk", "rep_sx"):
                if x in sh.labels:
                    self.assertNotEqual(sh.labels[x], a, x)
                    self.assertNotIn("rep_p", [y for y, _ in sh.owners[sh.labels[x]]], x)

    def test_book_rows_are_the_unshared_ones(self):
        for mode in self.MODES:
            sh = uasm.assemble(share=mode)
            self.assertEqual(uasm.book_rows(sh), uasm.book_rows(sh.flat))

    def test_derived_bnext_marks_are_unchanged(self):
        # nb on a non-E word is derived from its successors' kinds; on the shared layout the
        # derivation gives the same marks ((work order 25) but on a stored run's RET, which has
        # no static successor: its nb is its source words', test_each_source_word_...)
        for mode in self.MODES:
            sh = uasm.assemble(share=mode)
            words = []
            for r, w in sh.words:
                f = dict(w.fields)
                if not f.get("e"):
                    f.pop("nb", None)
                words.append((r, uasm.Word(f, w.act, w.line)))
            uasm._mark_bnext(words)
            for b, ((_, x), (_, y)) in enumerate(zip(sh.words, words)):
                if b in sh.mrets:
                    continue
                self.assertEqual(x.fields.get("nb", 0), y.fields.get("nb", 0), b)

    def test_unshared_switch(self):
        flat = uasm.assemble(share=False)
        self.assertIsNone(flat.flat)
        self.assertEqual(flat.where, list(range(len(flat.words))))
        tail = uasm.assemble(share="tail")
        self.assertFalse(tail.mcalls)
        self.assertLess(len(uasm.assemble().words), len(tail.words))
        self.assertLess(len(tail.words), len(flat.words))
        with self.assertRaises(uasm.UasmError):
            uasm.assemble(share="middle")

    def test_rom_fits_the_low_part(self):
        # (work order 25) the ROM fits ROM_LO: the high part (ROM_HI) holds no word; (work order
        # 26) the high part is gone: the ROM is one part of ROM_WORDS
        self.assertLessEqual(len(uasm.assemble().words), uasm.ROM_WORDS)
        uasm.check_rom_size(uasm.ROM_WORDS)
        with self.assertRaisesRegex(uasm.UasmError, "more than the ROM's 2048"):
            uasm.check_rom_size(uasm.ROM_WORDS + 1)


class L40(unittest.TestCase):
    """(work order 26) the 40-bit word (docs/v35s-urom-w40-layout.md): every stored word packed,
    decoded through the tables' address select and compared with the 96-bit word; the walk of
    work orders 24 / 25 on the ROM as the 40-bit image gives it, against the unshared ROM; a
    word with no way out fails the build."""

    @classmethod
    def setUpClass(cls):
        cls.prog = uasm.assemble()
        cls.img = cls.prog.l40

    def test_every_word_round_trips(self):
        prog, img = self.prog, self.img
        self.assertEqual(img.misfits, [])
        self.assertEqual(len(img.rom), len(prog.words))
        self.assertLessEqual(len(img.rom), uasm.ROM_WORDS)
        arm = uasm.arming_words(prog.words, uasm._succs)
        self.assertTrue(arm)
        for a, (_, w) in enumerate(prog.words):
            v = img.rom[a]
            self.assertLess(v, 1 << uasm.L40_BITS)
            self.assertIsNone(uasm.l40_check_word(img, a, w.fields, v, a in arm), prog.name_of(a))
            got = uasm.l40_unpack(v, img)
            ref = uasm.unpack(uasm.pack(w.fields))
            for k in ref:
                if k != "tgt":
                    self.assertEqual(got[k], ref[k], (prog.name_of(a), k))
            # the early bits from the raw word, at fixed positions
            r = uasm.l40_fields(v)
            self.assertEqual(r["POP"], ref["pop"])
            self.assertEqual(r["WID"], ref["wid"])
            self.assertEqual((r["K"] >> 8) & 1, ref["e"])
            e = uasm.l40_early(v)
            self.assertEqual(e["post"], uasm._posts(w.fields), prog.name_of(a))
            self.assertNotIn(r["SEQ"], (uasm.L40_SEQ["HOLD"], uasm.L40_SEQ["HJMP"]))
            if a in arm:
                self.assertTrue(e["kw"], prog.name_of(a))
        self.assertEqual(len(img.tki), 2)
        print(f"\n(work order 26) L40: {len(img.rom)} words round-trip; X "
              f"{sum(1 for q in img.xtab if q)} of 256, Y {sum(1 for h in img.ytab for q in h if q)} "
              f"of 512; {len(arm)} arming words")

    def test_the_l40_rom_expands_to_the_unshared_words(self):
        # the walk of work orders 24 / 25 (TailSharing) on the ROM read back from the L40 image:
        # the 40-bit ROM is the unshared program, clock for clock, through every branch
        flat = uasm.assemble(share=False)
        dec = uasm.l40_program(self.prog)
        t = TailSharing()
        seen = t.walk(flat, dec)
        self.assertEqual({a for a, *_ in seen}, set(range(len(flat.words))))
        self.assertEqual({b for _, b, *_ in seen}, set(range(len(dec.words))))
        # and a broken table entry is caught by it
        img = self.prog.l40
        q = next(q for q in range(1, 256) if img.xtab[q])
        keep = img.xtab[q]
        try:
            img.xtab[q] = tuple(keep[:-1]) + (keep[-1] ^ 1,)
            with self.assertRaises(AssertionError):
                t.walk(flat, uasm.l40_program(self.prog))
        finally:
            img.xtab[q] = keep

    def test_a_misfit_with_no_way_out_fails_the_build(self):
        # a conditional jump on a word that reads a register and carries an ALU payload: no
        # room for the target (form RT), and no way out (the target is the source's)
        import tempfile
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as d:
            files = []
            for p in sorted(uasm.UROM.glob("*.uasm")):
                q = P(d) / p.name
                t = p.read_text()
                if p.name == "str.uasm":
                    old = "    jnc=SNZ:rz_io                           ; c5: CW = 0: no element (rep_z) ("
                    self.assertIn(old, t)
                    t = t.replace(old, "    rb=IY wid=WORD alu=PASS ax=RB jnc=SNZ:rz_io ; c5 (", 1)
                q.write_text(t)
                files.append(q)
            with self.assertRaisesRegex(uasm.UasmError, r"(?s)L40.*rep_stm\+1: register read \+ "
                                        r"target \+ X: no payload bits \(form RT\)"):
                uasm.assemble(files)
            # the 96-bit layout alone still assembles (the check is L40's)
            self.assertGreater(len(uasm.assemble(files, l40=False).words), 0)

    def test_words_that_cannot_jump_are_not_given_one(self):
        # the layout's ways out: no jump or middle call on a word that could not carry it
        for a, (_, w) in enumerate(self.prog.words):
            k = uasm._SQN[w.fields.get("seq", 0)]
            if k == "jmp" or a in self.prog.mcalls:
                f = {x: v for x, v in w.fields.items() if x not in ("seq", "tgt")}
                self.assertIsNone(uasm.l40_tgt_ok(f), self.prog.name_of(a))

    def test_checked_in_l40_files_are_the_assembly(self):
        # (work order 27) the core reads them: part of every build and of --check
        out = uasm.l40_outputs(self.img)
        self.assertEqual(set(out), {"v35_l40_rom.hex", "v35_l40_x.hex", "v35_l40_y.hex",
                                    "v35_l40.svh"})
        for name, text in out.items():
            p = uasm.V35 / name
            self.assertTrue(p.exists(), name)
            self.assertEqual(p.read_text(), text,
                             f"{name}: run python -m validation.v35s.chains.uasm")
        self.assertEqual(uasm.check(self.prog), [])



def _svh_udec2(text: str, name: str) -> dict:
    """(work order 28) the generated function `name` (v35_udec2 / v35_udec2_ref) read back from
    the svh: {"idx": {index name: SV expression}, "items": [(ops, index name, [(values or None
    for default, row)])], "default": row}."""
    m = re.search(rf"function automatic v35_udecm_t {name}\(.*?\n(.*?)endfunction", text, flags=re.S)
    assert m, name
    body = m.group(1)
    idx = dict(re.findall(r"^\s*(k\d) = (.*);$", body, flags=re.M))
    lit = re.compile(r"'\{(\d+)'d(\d+), 1'b(\d), 3'd(\d), 1'b(\d), 1'b(\d), 1'b(\d), 1'b(\d), 1'b(\d)\}")

    def row(s):
        g = lit.search(s)
        assert g, s
        assert int(g.group(1)) == uasm.UENT_W
        return tuple(int(x) for x in g.groups()[1:])

    items, dflt, cur = [], None, None
    for line in body.splitlines():
        s = line.strip()
        a = re.match(r"((?:8'h[0-9A-F]{2}, )*8'h[0-9A-F]{2}): begin$", s)
        if a:
            cur = ([int(x, 16) for x in re.findall(r"8'h([0-9A-F]{2})", a.group(1))], None, [])
            items.append(cur)
            continue
        c = re.match(r"case \((\w+)\)$", s)
        if c and cur is not None:
            items[-1] = cur = (cur[0], c.group(1), cur[2])
            continue
        if s.startswith("default: f = "):
            if cur is not None:
                cur[2].append((None, row(s)))
            else:
                dflt = row(s)
            continue
        v = re.match(r"(.*?): f = ", s)
        if v and cur is not None:
            vals = [int(x.split("'")[1][1:], 16 if "'h" in x else 10) for x in v.group(1).split(", ")]
            cur[2].append((set(vals), row(s)))
            continue
        if s == "end":
            cur = None
    return {"idx": idx, "items": items, "default": dflt}


def _svh_eval(f: dict, op: int, b: int) -> tuple:
    ix = {"b": b, "k4": uasm.k4_of(b), "k6": uasm.k6_of(b)}
    for ops, name, rows in f["items"]:
        if op in ops:
            for vals, r in rows:
                if vals is None or ix[name] in vals:
                    return r
    return f["default"]


class CompactDecode(unittest.TestCase):
    """(work order 28) the second level held compactly (uasm udec2_forms): the forms are proved
    per opcode, and the emitted v35_udec2 equals the full table (v35_udec2_ref, the old form) for
    all 65,536 (opcode, byte) pairs and every field."""

    @classmethod
    def setUpClass(cls):
        cls.prog = uasm.assemble()
        cls.forms = uasm.udec2_forms(cls.prog)
        text = (uasm.V35 / "v35_udecode_tbl.svh").read_text()
        cls.cmp = _svh_udec2(text, "v35_udec2")
        cls.ref = _svh_udec2(text, "v35_udec2_ref")
        cls.text = text

    def test_the_model_is_the_table(self):
        table_ops = uasm.MODRM_OPS | {0x0F} | set(uasm.REP_XC)
        for op in range(256):
            for b in range(256):
                want = (uasm.udec2_row(uasm.udec2(self.prog, op, b)) if op in table_ops
                        else self.forms[1])
                self.assertEqual(uasm.udec2_compact(self.forms, op, b), want, f"{op:02X} {b:02X}")

    def test_the_emitted_function_equals_the_full_table(self):
        n = 0
        for op in range(256):
            for b in range(256):
                self.assertEqual(_svh_eval(self.cmp, op, b), _svh_eval(self.ref, op, b),
                                 f"{op:02X} {b:02X}")
                n += 1
        self.assertEqual(n, 65536)
        # the reference is one case of the whole byte per opcode (the old form)
        self.assertEqual({name for _, name, _ in self.ref["items"]}, {"b"})
        self.assertEqual(self.ref["idx"], {})

    def test_the_index_expressions_are_the_forms(self):
        forms = {name: expr for name, _, _, expr in uasm.UDEC2_FORMS}
        self.assertTrue(self.cmp["idx"])
        for name, expr in self.cmp["idx"].items():
            self.assertEqual(expr, forms[name])
        # the SV expressions against the Python index functions, every byte
        for b in range(256):
            mod, reg, rm = b >> 6, (b >> 3) & 7, b & 7
            self.assertEqual(uasm.k4_of(b), (int(mod == 3) << 3) | reg)
            x = (mod == 0 and rm == 6) or (mod == 2 and not (rm >> 2) & 1)
            self.assertEqual(uasm.k6_of(b), (mod << 4) | (int(x) << 3) | reg)

    def test_most_opcodes_read_the_reg_field_and_mode_3(self):
        by = {}
        for ops, name, _ in self.forms[0]:
            for op in ops:
                by[op] = name
        self.assertEqual({op for op, n in by.items() if n == "b"}, {0x0F} | set(uasm.REP_XC))
        self.assertGreater(sum(1 for n in by.values() if n == "k4"), 50)

    def test_a_wrong_form_is_caught(self):
        # an opcode whose cells depend on the mode, read on k4 alone, differs from the table
        op = 0x80
        rows = [uasm.udec2_row(uasm.udec2(self.prog, op, b)) for b in range(256)]
        k4tab = {}
        for b in range(256):
            k4tab.setdefault(uasm.k4_of(b), rows[b])
        self.assertTrue(any(k4tab[uasm.k4_of(b)] != rows[b] for b in range(256)))

    def test_entries_fit_the_entry_width(self):
        self.assertEqual(1 << uasm.UENT_W, uasm.ROM_WORDS)
        for op in range(256):
            self.assertLess(uasm.udec1(self.prog, op)["entry"], 1 << uasm.UENT_W)


if __name__ == "__main__":
    unittest.main()
