"""rtlgen (HDL plan, Phase C): the checked-in fpga/v35s/core/v35_chain_params.svh is what the
generator makes of fit.json and the frozen package, every class and EA mode is in it, every
template the corpus's instructions need is selectable, and its widths are the spec's A2
widths and hold what they must."""

from __future__ import annotations

import hashlib
import re
import dataclasses
import unittest
from pathlib import Path

from validation.v35s.chains import rtlgen
from validation.v35s.chains.sim.config import FIT_PATH

SPEC = rtlgen.ROOT / "docs" / "v35s-chain-rtl-spec.md"


class Generated(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = rtlgen.render()
        cls.cfg = rtlgen.fit_config()       # (WP77) the frozen package's fit
        cls.tmpls, cls.sel, cls.example = rtlgen.templates(cls.cfg)

    def test_checked_in_is_a_fresh_generation(self):
        self.assertTrue(rtlgen.OUT.exists(), "python -m validation.v35s.chains rtlgen")
        self.assertEqual(rtlgen.OUT.read_text(), self.text,
                         "v35_chain_params.svh drifted from fit.json: regenerate with "
                         "python -m validation.v35s.chains rtlgen")
        self.assertEqual(rtlgen.check(), 0)

    def test_deterministic(self):
        self.assertEqual(rtlgen.render(), self.text)

    def test_header_names_the_fit(self):
        md5 = hashlib.md5(Path(FIT_PATH).read_bytes()).hexdigest()
        self.assertIn(f"(md5 {md5}); do not edit.", "\n".join(self.text.splitlines()[:3]))
        self.assertIn(f'V35_FIT_MD5 = "{md5}"', self.text)

    def test_every_class_present(self):
        """Every class but halt's has a format word selecting a template. (WP75) A class's
        templates are found through the format words, not the templates' examples: a template
        two classes build is listed under the first (fit 40: DISPOSE's, setup 7, is POP's)."""
        cost = rtlgen.rtl_cost(self.cfg)    # (WP77) the built classes
        self.assertEqual(len(cost), 65)     # fit 38: the seven string classes; (WP79) F32 / F33
        self.assertIn(f"localparam int V35_CLS_N = {len(cost)};", self.text)
        names = [n for n, _ in rtlgen.FMT_FIELDS]
        with_tmpl = {k[names.index("cls")] for k in self.sel}
        self.assertFalse(with_tmpl & rtlgen.UNBUILT_CLASSES)
        for k, cls in enumerate(rtlgen.rtl_classes(self.cfg)):
            with self.subTest(cls=cls):
                # the class ids are the built classes' sorted order (rtl_vectors' numbering)
                self.assertIn(f"localparam int V35_CLS_{rtlgen._ident(cls)} = {k};", self.text)
                self.assertTrue(cls in with_tmpl)
                for name, value in cost[cls].items():
                    self.assertIn(f"localparam int V35_C_{rtlgen._ident(cls)}_"
                                  f"{rtlgen._ident(name)} = {value};", self.text)
        n = sum(len(d) for d in cost.values())
        self.assertEqual(len(re.findall(r"^localparam int V35_C_", self.text, re.M)), n)

    def test_string_templates(self):
        """(E3) the string forms' templates: every string opcode, byte and word, with and
        without REP / REPNE, selects one; a REP form's compact template expands to frozen
        _string_steps' list (string_template checks n = 0 .. 6 and both exits; here again at
        n = 16 and a large count's head and tail); its shape is in v35_str_shape."""
        from validation.v35s.chains.sim.frozen.templates import STRING_OPS, decode
        sc = rtlgen.string_classes()
        self.assertEqual(sc, {"str_move", "str_cmp", "str_store", "str_load", "str_scan",
                              "str_in", "str_out"})
        self.assertTrue(sc <= set(self.cfg.cost))
        for even, cls in STRING_OPS.items():
            for o in (even, even | 1):
                for pre in (b"", b"\xf3", b"\xf2", b"\x65", b"\x64"):   # (WP77) REPC, REPNC
                    op = decode(pre + bytes([o, 0x90]), 0, rtlgen._regs(0, 3))
                    self.assertEqual(op.cls, cls)
                    key = tuple(rtlgen.fmt_of(op, self.cfg, False, False)[n]
                                for n, _ in rtlgen.FMT_FIELDS)
                    with self.subTest(code=(pre + bytes([o])).hex()):
                        self.assertIn(key, self.sel)
                        tm = self.tmpls[self.sel[key]]
                        self.assertEqual(tm, rtlgen.string_template(op, self.cfg))
                        if not pre:
                            continue
                        m, c, t = rtlgen.string_shape(tm, cls)
                        self.assertIn(f"{self.sel[key]}: v35_str_shape = "
                                      f"{{2'd{t}, 2'd{m}, 2'd{c}}};", self.text)
                        for n in (16, 300):
                            for cond in (False, True) if rtlgen.is_compare(cls) else (False,):
                                want = [(rtlgen._row(d), i) for d, i in
                                        rtlgen._str_raw(op, self.cfg, n, cond)]
                                got = rtlgen.expand_string(tm, cls, self.cfg.c(cls, "last"),
                                                           n, cond)
                                got = [(r, i if dict(r)["src" if "src" in dict(r) else "op"]
                                        in ("ix", "iy") else None) for r, i in got]
                                self.assertEqual(want, got)

    def test_string_step_kinds(self):
        """(WP77) the forty-first fit's string steps: a REP form's template holds the CW = 0
        fetch_release (zfetch, raise), the fetch_release before element 0 (forever), the tail's
        fetch_release (xfetch) and, but after a single read (LDM, CMPM), split_floor (xsplit);
        the exits are less xwb. Every step kind the templates use packs and is in the include."""
        from validation.v35s.chains.sim.frozen.templates import STRING_OPS, decode
        kinds = set()
        for tm in self.tmpls:
            kinds |= {dict(r)["op"] for r in tm}
        self.assertTrue(kinds <= set(rtlgen.STEP_OPS))
        self.assertTrue({"fetch_release", "split_floor"} <= kinds)
        for name in ("FETCH_RELEASE", "SPLIT_FLOOR"):
            self.assertIn(f"localparam int V35_SOP_{name} = ", self.text)
        for name in ("FOREVER", "RAISE"):
            self.assertIn(f"localparam int V35_STAG_{name} = ", self.text)
        c = self.cfg.c
        for even, cls in STRING_OPS.items():
            op = decode(bytes([0xF3, even, 0x90]), 0, rtlgen._regs(0, 3))
            tm = [dict(r) for r in rtlgen.string_template(op, self.cfg)]
            m, cc, t = rtlgen.string_shape(tuple(rtlgen._row(d) for d in tm), cls)
            with self.subTest(cls=cls):
                self.assertEqual(tm[2], {"op": "fetch_release", "tag": "raise",
                                         "n": (c(cls, "zfetch"), 0)})
                self.assertEqual(tm[3], {"op": "clocks", "n": (c(cls, "zexit"), 0)})
                self.assertEqual(tm[4], {"op": "fetch_release", "tag": "forever", "n": (0, 0)})
                base = rtlgen._str_base() + rtlgen.STRING_SETS * m
                self.assertEqual(tm[base], {"op": "fetch_release", "n": (c(cls, "xfetch"), 0)})
                single = cls in ("str_load", "str_scan")
                self.assertEqual(t, 1 if single else 2)
                if not single:
                    self.assertEqual(tm[base + 1], {"op": "split_floor",
                                                    "n": (c(cls, "xsplit"), 0)})
                self.assertEqual(tm[base + t]["n"], (c(cls, "rexit") - c(cls, "xwb"), 0))

    def test_flush_cfgap(self):
        """(WP72) cond_gap=own: a taken BE / BNE's flush waits the class's cfgap (the step's
        tag), BR short's fgap."""
        from validation.v35s.chains.sim.frozen.templates import decode
        for code, tag in ((b"\x74\x02", "cfgap"), (b"\xeb\x02", None)):
            op = decode(code + b"\x90" * 6, 0, rtlgen._regs(1, 3))
            tm = rtlgen.template(op, self.cfg, False, False)
            fl = [dict(r) for r in tm if dict(r)["op"] == "flush"]
            self.assertEqual([d.get("tag") for d in fl], [tag])

    def test_ea_table(self):
        self.assertEqual(len(self.cfg.ea), 7)
        for mode, value in self.cfg.ea.items():
            self.assertIn(f"localparam int V35_EA_{rtlgen._ident(mode)} = {value};", self.text)

    def test_structural_integers_and_unread_fields(self):
        _, _, structure = rtlgen.load()
        sites = rtlgen.read_fields()
        for k, v in structure.items():
            line = f"localparam int FIT_{rtlgen._ident(k)} = {v};"
            emit = (isinstance(v, int) and not isinstance(v, bool) and k in sites
                    and k not in rtlgen.DEAD_FIELDS)
            with self.subTest(field=k):
                self.assertEqual(line in self.text, emit)
        for k in ("arbiter_q", "refresh_stall", "refresh_recent", "refresh_io_pre"):
            self.assertNotIn(f"FIT_{rtlgen._ident(k)} ", self.text)
        for k in ("min_gap", "io_recover", "wlatch", "hold_q"):
            self.assertIn(f"localparam int FIT_{rtlgen._ident(k)} = {structure[k]};", self.text)

    def test_widths_hold_their_values(self):
        _, _, structure = rtlgen.load()
        self.assertEqual(rtlgen.check_widths(self.cfg, structure, self.tmpls), [])

    def test_widths_are_the_specs(self):
        """The spec's A2 widths: the bus unit's table (Bits column) and the width paragraph.
        last_fetch_end is the one documented difference: the spec's 1 bit is the
        `== t-1` flag; the bus unit keeps the clocks since the fetch (3 bits) because the
        frozen EU's flush (F23, after the spec's tables) reads t <= last_fetch_end + fgap."""
        spec = SPEC.read_text()
        bus = spec.split("### Bus unit", 1)[1].split("###", 1)[0]
        bits = {}
        for line in bus.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 6 and cells[0].startswith("`"):
                bits[cells[0]] = cells[5]
        self.assertEqual(bits["`current.kind`"], "3")
        self.assertEqual(rtlgen.WIDTHS["KIND"], 3)
        W = rtlgen.WIDTHS
        self.assertTrue(bits["`current` position (`t - start`)"].startswith(str(W["POS"])))
        self.assertEqual(bits["`current.length`"], str(rtlgen.WIDTHS["LEN"]))
        self.assertEqual(bits["`current.addr`, `.width`, `.data`"],
                         str(W["ADDR"] + W["BWIDTH"] + W["DATA"]))
        self.assertTrue(bits["`last_io_end`"].startswith(str(rtlgen.WIDTHS["IO_TAIL"])))
        self.assertTrue(bits["`refresh_length`"].startswith(str(rtlgen.WIDTHS["REFRESH_LEN"])))
        self.assertTrue(bits["`last_fetch_end`"].startswith("1"))     # the documented difference
        self.assertGreater(rtlgen.WIDTHS["FETCH_SINCE"], 1)
        self.assertIn("1, 1, 3", bits["`early`, `early_ok`, `early_n`"])
        self.assertEqual(rtlgen.WIDTHS["EARLY_N"], 3)
        widths = spec.split("### The variables that decide widths", 1)[1].split("## A3", 1)[0]
        self.assertIn("3 bits, 6 bytes of", widths)
        self.assertEqual(rtlgen.WIDTHS["QUEUE_BYTES"], 3)
        self.assertIn("-2 .. 7", widths)
        self.assertEqual(rtlgen.WIDTHS["ROOM"], 4)
        self.assertIn("`eu.k` 0 .. 14", widths)
        self.assertEqual(rtlgen.WIDTHS["STEP_K"], 4)
        self.assertIn("count loop's 9-bit width", spec)     # decisions: the count byte unmasked
        self.assertEqual(rtlgen.WIDTHS["COUNT_LOOP"], 9)
        self.assertIn("0 .. 87 (7 bits)", widths)
        self.assertEqual(rtlgen.WIDTHS["SETUP"], 7)
        self.assertIn("All fit in 3-bit counters", widths)
        self.assertEqual(rtlgen.WIDTHS["WLATCH"], 3)
        for k, v in rtlgen.WIDTHS.items():
            self.assertIn(f"localparam int V35_W_{k} = {v};", self.text)

    def test_bus_constants(self):
        c = rtlgen.bus_constants()
        self.assertEqual((c["BASE"], c["SFR_PAGE"], c["REFRESH_LENGTH"]), (3, 0xFFF00, 5))
        self.assertEqual(c["REFRESH_LENGTHS"], [3, 4, 5, 5])
        self.assertIn("localparam logic [19:0] V35_SFR_PAGE = 20'hFFF00;", self.text)

    def test_prelude_constants(self):
        """(C4) the POP PSW read Machine.__init__ issues on clock 0, for the core's start."""
        from validation.v35s.chains.image import PRELUDE_MARKER_STACK, PSW
        c = rtlgen.prelude_constants()
        self.assertEqual((c["POP_ADDR"], c["PSW"]), (PRELUDE_MARKER_STACK, PSW))
        self.assertIn(f"localparam logic [19:0] V35_PRELUDE_POP_ADDR = 20'h{PRELUDE_MARKER_STACK:05X};",
                      self.text)
        self.assertIn(f"localparam logic [15:0] V35_PRELUDE_PSW = 16'h{PSW:04X};", self.text)

    def test_packed_steps_round_trip(self):
        off = {}
        o = 0
        for name, bits in rtlgen.STEP_FIELDS:
            off[name] = (o, bits)
            o += bits
        for tm in self.tmpls:
            for st in tm:
                word = rtlgen.pack_step(st)
                d = dict(st)
                get = lambda n: (word >> off[n][0]) & ((1 << off[n][1]) - 1)  # noqa: E731
                self.assertEqual(rtlgen.STEP_OPS[get("op")], d["op"])
                n = d.get("n")
                if n is not None:
                    self.assertEqual((get("n"), get("per_count")), n)
                if "src" in d:
                    self.assertEqual(rtlgen.ADDR_SRC[get("src")], d["src"])

    def test_corpus_instructions_have_templates(self):
        """Every instruction of every generated chain (E3: the string forms too) decodes to a
        format the selection table holds, in both refresh forms (and the count-0 form of a
        shift), with the EU's own changes at its start (a CMP r/m,reg or 81 /7 form: nowrite,
        its group's class). An instruction of an UNBUILT_CLASSES class (WP77) has no template by
        design and is skipped; (WP79) none is left: the F32 / F33 classes are checked as every
        other, a BCD string against its compact template, a bit field in both crossings."""
        from validation.v35s.chains.families import FAMILIES, UNMODELLED, generate
        from validation.v35s.chains.sim.frozen.templates import decode
        # (WP87) the modelled families only: an UNMODELLED family's forms have no template yet
        codes = sorted({bytes(i.code) for c in generate([f for f in FAMILIES if f not in UNMODELLED])
                        for i in c.instrs})
        seen = 0
        unbuilt = 0
        page = 0
        for code in codes:
            k = 0
            while k < len(code):
                try:
                    op = decode(code, k, rtlgen._regs(0, 3))
                except (ValueError, KeyError, IndexError):
                    break
                op = rtlgen.started(op, self.cfg)   # as the EU's _start selects it
                if op.cls in rtlgen.UNBUILT_CLASSES:
                    unbuilt += 1                    # (WP77) left out of the include
                    k += op.length
                    continue
                if op.cls in rtlgen.string_classes():
                    key = tuple(rtlgen.fmt_of(op, self.cfg, False, False)[n]
                                for n, _ in rtlgen.FMT_FIELDS)
                    with self.subTest(code=code.hex(" "), k=k):
                        self.assertIn(key, self.sel)   # (E3) string_template's
                    seen += 1
                    k += op.length
                    continue
                if op.cls in rtlgen.bcd_classes() or op.cls in rtlgen.bf_classes():
                    for refresh in (False, True):     # (WP79)
                        for cross in ((False, True) if op.bf is not None else (False,)):
                            o = op if op.bf is None else dataclasses.replace(
                                op, bf=(0, 0, cross, rtlgen.BF_SENT))
                            key = tuple(rtlgen.fmt_of(o, self.cfg, False, refresh)[n]
                                        for n, _ in rtlgen.FMT_FIELDS)
                            want = (rtlgen.bcd_template(o, self.cfg) if o.bf is None
                                    else rtlgen.bf_template(o, self.cfg))
                            with self.subTest(code=code.hex(" "), k=k, cross=cross):
                                self.assertIn(key, self.sel)
                                self.assertEqual(self.tmpls[self.sel[key]], want)
                    seen += 1
                    page += 1
                    k += op.length
                    continue
                page += op.page
                for refresh in (False, True):
                    cz = rtlgen.has_count(op) and op.count == 0
                    key = tuple(rtlgen.fmt_of(op, self.cfg, cz, refresh)[n]
                                for n, _ in rtlgen.FMT_FIELDS)
                    with self.subTest(code=code.hex(" "), k=k):
                        self.assertIn(key, self.sel)
                        self.assertEqual(self.tmpls[self.sel[key]],
                                         rtlgen.template(op, self.cfg, refresh, cz))
                seen += 1
                k += op.length
        self.assertGreater(seen, 300)
        if rtlgen.UNBUILT_CLASSES:
            self.assertGreater(unbuilt, 0)          # (WP77) F32 / F33 were in the corpus
        self.assertEqual(unbuilt, 0)                # (WP79) every class built
        self.assertGreater(page, 40)                # (WP79) the 0F page's forms checked

    def test_page_and_miscellany(self):
        """(WP79) The F32 / F33 classes in the include: every class a base class (BASE_CLASS)
        maps to the same in v35_base_cls; a BCD string's compact template expands to frozen
        _wp78_steps for any pair count (bcd_template checks n up to 6) with pairs 0 and >= 1;
        a bit field's template carries the cost formula in one clocks step tagged bf whose n is
        the class's span / xspan, its word reads at IX / IY (+ 2 crossing as src_i 1); the new
        widths hold (7-bit classes, the decoder's nx and ready_at, the bit field's cost)."""
        from validation.v35s.chains.sim.frozen.templates import BASE_CLASS, decode
        self.assertFalse(rtlgen.UNBUILT_CLASSES)
        for c, b in BASE_CLASS.items():
            self.assertIn(f"V35_CLS_{rtlgen._ident(c)}: v35_base_cls = V35_CLS_{rtlgen._ident(b)};",
                          self.text)
        c = self.cfg.c
        for code, cls in ((b"\x0f\x20", "bcd4s"), (b"\x0f\x26", "bcd4s_cmp")):
            op = decode(code + bytes(6), 0, rtlgen._regs(0, 3))
            tm = [dict(r) for r in rtlgen.bcd_template(op, self.cfg)]
            m = rtlgen.bcd_shape(tuple(rtlgen._row(d) for d in tm))
            self.assertEqual(m, 3 if cls == "bcd4s" else 2)
            self.assertEqual(tm[rtlgen.BCD_HEAD]["n"], (c(cls, "first"), 0))
            self.assertEqual(tm[rtlgen.BCD_HEAD + m]["n"], (c(cls, "loop"), 0))
            self.assertEqual(tm[-1], {"op": "clocks", "n": (c(cls, "exec"), 0)})
            self.assertIn(f"v35_bcd_shape = 2'd{m};   // {cls}", self.text)
        for second, cls, span in ((0x33, "bf_ext", "span"), (0x31, "bf_ins", "xspan")):
            op = decode(bytes([0x0F, second, 0xC2, 0, 0, 0, 0, 0]), 0, rtlgen._regs(0, 3))
            o = dataclasses.replace(op, bf=(0, 0, span == "xspan", rtlgen.BF_SENT))
            tm = [dict(r) for r in rtlgen.bf_template(o, self.cfg)]
            bf = [d for d in tm if d.get("tag") == "bf"]
            self.assertEqual(bf, [{"op": "clocks", "tag": "bf", "n": (c(cls, span), 0)}])
            reads = [(d["src"], d["src_i"]) for d in tm if d["op"] == "data"]
            self.assertEqual(reads[0], ("ix" if cls == "bf_ext" else "iy", 0))
            if span == "xspan":
                self.assertIn(("iy", 1), reads)
        self.assertEqual(rtlgen.WIDTHS["CLS"], 7)
        self.assertLess(len(rtlgen.rtl_classes(self.cfg)), 127)

    def test_shift_counts_are_coefficients(self):
        """SHL AW,CL: its count loop is 2 clocks per count (per_shift_count), not a literal."""
        from validation.v35s.chains.sim.frozen.templates import decode
        op = decode(bytes([0xD3, 0xE0]), 0, rtlgen._regs(0, 3))
        tm = dict(enumerate(rtlgen.template(op, self.cfg, False, False)))
        self.assertIn(("n", (0, self.cfg.per_shift_count)), tm[len(tm) - 1])


if __name__ == "__main__":
    unittest.main()
