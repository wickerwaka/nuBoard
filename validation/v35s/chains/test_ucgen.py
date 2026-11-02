"""ucgen (docs/v35s-core-v2.md, S1): the checked-in fpga/v35s/core/v35/ data is what the generator
makes of fit.json and the live model; every enumerated form's template expands back to the
model's step list; the decode table gives every form's length and class; the S5 budget holds;
the sizes are in bounds; the hex ROM reads back into v35_pkg::uc_row_t bit for bit.

Offline; about half a minute."""

from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

from validation.v35s.chains import ucgen
from validation.v35s.chains.sim.config import FIT_PATH


class Generated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gen = ucgen.generate()
        cls.files = ucgen.render_all(cls.gen)

    # (a) regenerate and diff
    def test_check_passes_on_the_committed_files(self):
        for name in ucgen.FILES:
            path = ucgen.OUT_DIR / name
            self.assertTrue(path.exists(), f"{path}: run {ucgen.INVOCATION}")
            self.assertEqual(path.read_text(), self.files[name],
                             f"{name} drifted from fit.json / the model: run {ucgen.INVOCATION}")
        self.assertEqual(ucgen.check(), 0)

    def test_headers_name_the_fit_and_the_invocation(self):
        md5 = hashlib.md5(Path(FIT_PATH).read_bytes()).hexdigest()
        for name, text in self.files.items():
            head = "\n".join(text.splitlines()[:3])
            self.assertIn(f"(md5 {md5})", head, name)
            self.assertIn(ucgen.INVOCATION, head, name)

    # (b) the inverse check
    def test_inverse_check_every_form(self):
        """Every enumerated form, selected as the RTL selects it (fmt_of, tmpl_of), under every
        run variant (shift counts 0 / 1 / 2 / 7 / 255, MUL sign clocks, REP / BCD element counts
        0 / 1 / 2 / 3 / 6 and both compare exits, bit fields within / ending at / crossing the
        word, the even-half bit, a detached I/O held at a port take or not): the template's rows
        expanded with the fit's integers equal templates.steps (with eu._start's wbsync and the
        relatch insertion), both in ucgen.canonical form."""
        checks, fails = ucgen.inverse_check(self.gen)
        msg = "\n".join(f"{c} {cls} {run} held={h} tmpl {t}:\n  got  {g}\n  want {w}"
                        for c, cls, run, h, t, g, w in fails[:5])
        self.assertEqual(fails, [], msg)
        self.assertGreater(checks, 100000)
        self.assertGreater(len(self.gen.forms) - len(self.gen.bad), 40000)

    # (c) decode
    def test_decode_length_and_class(self):
        g, cfg = self.gen, self.gen.cfg
        n = 0
        for i, f in enumerate(g.forms):
            fm = ucgen.fmt_of(g.tables, cfg, f.opcode, f.page, f.modrm or 0, g.classes)
            op = ucgen.started(f.op, cfg)
            self.assertEqual(fm["len"], op.length, f.code.hex(" "))
            if i in g.bad:
                self.assertEqual(g.classes[fm["cls"]], ucgen.TRAP, f.code.hex(" "))
                continue
            self.assertEqual(g.classes[fm["cls"]], op.cls, f.code.hex(" "))
            if op.ea is not None and f.modrm is not None and op.modrm:
                self.assertEqual(ucgen.EA_MODES[fm["ea_mode"]], ucgen._model()[0].ea_class(op, cfg))
            n += 1
        self.assertGreater(n, 40000)

    def test_data_book_trailing_bytes(self):
        """instructions.json: no decode cell's trailing operand bytes disagree with a data-book
        record of its encoding (the cells the book has no record for are its undocumented
        aliases, fpga/v35s/core/v35/README.md)."""
        for page, o, half, reg, tail, book in ucgen.json_crosscheck(self.gen):
            self.assertEqual(book, [], f"{page}:{o:02X} {half} /{reg}: {tail} not in {book}")

    def test_unknown_opcodes_are_trap_nop(self):
        g = self.gen
        T = ucgen._model()[0]
        for o in (0x62, 0x63, 0x9B, 0xD6, 0xD8, 0xF1):
            fm = ucgen.fmt_of(g.tables, g.cfg, o, 0, 0xC0, g.classes)
            self.assertEqual(fm["cls"], 0, f"{o:02X}")
            self.assertEqual(ucgen.tmpl_of(g, fm, dict.fromkeys(ucgen.RUN_NAMES, 0)), 0)
        self.assertEqual(g.templates[0], ucgen.TRAP_ROWS)
        self.assertIn(0x0F, [o for o in range(256) if g.tables.native[o]["esc"] == 1])
        self.assertEqual({o for o in range(256) if g.tables.native[o]["esc"] == 2},
                         set(T.REP_PREFIXES))

    # (d) the S5 budget
    def test_s5_budget(self):
        """Every register-only form of an I/O-interlocked class (io_interlock=reg_pfx, lea,
        the transfers, div): its start clock's actions fit {one take of a byte or a lead take,
        one post, one clocks load}."""
        res = ucgen.s5_budget(self.gen)
        self.assertGreater(len(res), 40)
        bad = [r for r in res if not r[3]]
        self.assertEqual(bad, [], "\n".join(f"{c} t{t}: {a}" for c, t, a, _ in bad))
        classes = {c for c, _, _, _ in res}
        for c in ("reg", "imm", "shift_imm", "shift_cl", "mul", "div", "prefix", "lea",
                  "branch_short", "dbnz", "call", "ret"):
            self.assertIn(c, classes)
        print("\nS5 budget (class, template: start-clock actions):")
        for c, t, a, _ in res:
            print(f"  {c:<14} t{t:<4} {' ; '.join(a)}")

    # (e) size bounds
    def test_sizes(self):
        g = self.gen
        self.assertLessEqual(len(g.rows), 2048)
        self.assertLessEqual(len(g.templates), 512)
        self.assertLessEqual(ucgen.ROW_BITS, 64)
        self.assertLessEqual(len(g.classes), 128)
        self.assertLessEqual(max(len(t) for t in g.templates), 16)

    # (f) the hex ROM against v35_pkg.sv's uc_row_t, parsed from the SV text
    def test_hex_parses_into_the_packed_struct(self):
        pkg = self.files["v35_pkg.sv"]
        enums = {}
        for m in re.finditer(r"typedef enum logic \[(\d+):0\] \{([^}]*)\} (\w+);", pkg):
            members = [x.strip() for x in m.group(2).split(",")]
            vals = {}
            for mem in members:
                name, v = mem.split("=")
                vals[int(v.strip().split("'d")[1])] = name.strip()
            enums[m.group(3)] = (int(m.group(1)) + 1, vals)
        body = pkg[pkg.index("typedef struct packed {", pkg.index("the microcode row")):]
        body = body[:body.index("} uc_row_t;")]
        fields = []                     # MSB first
        for line in body.splitlines()[1:]:
            line = line.strip().rstrip(";")
            if not line:
                continue
            typ, name = line.rsplit(" ", 1)
            if typ in enums:
                fields.append((name, enums[typ][0], enums[typ][1]))
            else:
                m = re.fullmatch(r"logic(?: \[(\d+):0\])?", typ)
                fields.append((name, int(m.group(1)) + 1 if m.group(1) else 1, None))
        self.assertEqual([(n, b) for n, b, _ in reversed(fields)], list(ucgen.ROW_FIELDS))
        words = []
        for line in self.files["v35_ucode.hex"].splitlines():
            code = line.split("//")[0].strip()
            if code:
                words.append(int(code, 16))
        self.assertEqual(len(words), len(self.gen.rows))
        width = sum(b for _, b, _ in fields)
        for k, (word, row) in enumerate(zip(words, self.gen.rows)):
            self.assertLess(word, 1 << width)
            off, got = width, {}
            for name, b, names in fields:   # MSB first, as the packed struct lays it out
                off -= b
                v = (word >> off) & ((1 << b) - 1)
                got[name] = names[v] if names is not None else v
            want = {n: (f"{ucgen.ENUM_PREFIX[n][1]}{row[n]}" if n in ucgen.ROW_ENUMS else row[n])
                    for n, _ in ucgen.ROW_FIELDS}
            self.assertEqual(got, want, f"row {k}")
            self.assertEqual(ucgen.unpack_row(word), row)

    def test_row_format(self):
        g = self.gen
        for t, rows in enumerate(g.templates):
            self.assertTrue(rows[-1]["last"], t)
            loops = [r for r in rows if r["loop"]]
            if loops:
                self.assertEqual(len(loops), 1)
                self.assertEqual(sum(r["ltop"] for r in rows), 1)
            for r in rows:
                self.assertEqual(r["tdelay"], ucgen.tdelay(r["op"], r["tag"]))
                if r["arm"] in ucgen.ARMS_X:
                    self.assertFalse(ucgen._uses_x(r), (t, r))


class Units(unittest.TestCase):
    def test_canonical(self):
        seq = [("clocks", 0), ("take", 0), ("clocks", 0, "ea"), ("data", "read", 4, 2, 3, None,
                                                                 False), ("clocks", 2)]
        self.assertEqual(ucgen.canonical(seq), [("data", "read", 4, 2, 3), ("clocks", 2)])

    def test_pack_roundtrip(self):
        row = dict(ucgen.ROW_DEFAULT, op="DATA", rkind="WRITE", asrc="SPW", aidx=3, imm=300,
                   x=127, arm="REL_RAISE", apos="EXIT", wb=3, skip="NCROSS")
        self.assertEqual(ucgen.unpack_row(ucgen.pack_row(row)), row)
        with self.assertRaises(ucgen.UcgenError):
            ucgen.pack_row(dict(row, imm=512))


if __name__ == "__main__":
    unittest.main()
