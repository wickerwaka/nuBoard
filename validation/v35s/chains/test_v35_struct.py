"""Structure lint of the core v2 RTL (docs/v35s-core-v2.md, "Verification": structure lint) over
fpga/v35s/core/v35/*.sv and *.svh. Passes on an empty or partial directory.

Rules (comments and string literals are stripped first):
1. no identifier containing `settle` (the old core's fixpoint registers);
2. no `always_comb` block that assigns a signal it also reads (no block reads its own outputs:
   the clock's logic is feed-forward);
3. no 8-bit opcode literals (`8'h..`, `8'd..`) outside the generated decode table
   v35_udecode_tbl.svh ((MX0) the assembler's; v35_pkg.sv is hand-written and has none): RTL
   compares format bits and the microinstruction's fields, never opcode bytes;
4. every `always_ff` is clocked by `posedge clock` and its state updates are gated by `ce`
   (an `if` on `ce` in the block; (S7b) or on the two-tick enables `ce_a` / `ce_b`);
6. (MX0) no .uasm word names an opcode (the routine headers do: the decode table's input) and
   no RTL file outside the decode table compares one; the ROM word (v35_pkg::v35_uword_t) has
   no count field.
5. (A1, docs/v35s-arbiter-strategy.md) no port of v35_bus.sv or v35_queue.sv names or types an
   instruction: no port of a format / class / row / run / request-record type, no port name
   carrying a class, format, row, step, count mode or kind of instruction; the bus unit's inputs
   are its clocking and configuration, the EU request port (exactly the strategy's nine signals),
   the queue's port and the three read strobes of the aborted fetch, nothing else.
The checks are textual (a lint, not a parser): keep blocks plain `begin ... end`."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V35 = ROOT / "fpga" / "v35s" / "core" / "v35"
OPCODE_FILES = ("v35_udecode_tbl.svh",)      # (MX0) the generated decode table only


def sources() -> list:
    if not V35.exists():
        return []
    return sorted(p for p in V35.iterdir() if p.suffix in (".sv", ".svh"))


def strip(text: str) -> str:
    """Comments and string literals blanked (line structure kept)."""
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', text)


def blocks(text: str, kind: str) -> list:
    """(header, body) of every `kind` block: the statement after the keyword, a begin ... end
    matched by nesting, or a single statement up to its `;`."""
    out = []
    for m in re.finditer(rf"\b{kind}\b", text):
        i = m.end()
        header = ""
        if kind == "always_ff":
            h = re.match(r"\s*@\s*\(([^)]*)\)", text[i:])
            header = h.group(1) if h else ""
            i += h.end() if h else 0
        b = re.match(r"\s*begin\b", text[i:])
        if b:
            depth, j = 0, i
            for t in re.finditer(r"\b(begin|end)\b", text[i:]):
                depth += 1 if t.group(1) == "begin" else -1
                if depth == 0:
                    j = i + t.end()
                    break
            out.append((header, text[i:j]))
        else:
            out.append((header, text[i:text.index(";", i) + 1]))
    return out


_KEYWORDS = {"begin", "end", "if", "else", "case", "endcase", "unique", "priority", "default",
             "for", "int", "logic", "automatic", "casez", "casex", "inside"}


def comb_self_reads(body: str) -> set:
    """Signals an always_comb block reads before it assigns them (blocking `=`) while also
    assigning them somewhere in the block: a combinational self-dependency. A variable assigned
    and then read further down the block is ordinary procedural code and is allowed (Verilator's
    UNOPTFLAT is the loop check for everything else)."""
    assigned_anywhere = set()
    for m in re.finditer(r"([A-Za-z_]\w*)(?:\s*\[[^\]]*\])*(?:\.\w+)*\s*=(?!=)", body):
        if body[m.end() - 2:m.end()] in ("<=", ">=", "!="):
            continue
        assigned_anywhere.add(m.group(1))
    assigned_so_far, early = set(), set()
    for stmt in re.split(r";", body):
        lhs, rhs = (stmt.split("=", 1) if re.search(r"[^<>!=]=[^=]", stmt) else ("", stmt))
        cond = re.findall(r"\b(?:if|case|casez|unique case)\s*\((.*)\)", stmt)
        for part in [rhs] + cond:
            for name in re.findall(r"\b([A-Za-z_]\w*)\b", part):
                if name in assigned_anywhere and name not in assigned_so_far:
                    early.add(name)
        m = re.match(r"\s*(?:\belse\b|\bif\s*\(.*\))?\s*([A-Za-z_]\w*)", lhs)
        for name in re.findall(r"([A-Za-z_]\w*)(?:\s*\[[^\]]*\])*(?:\.\w+)*\s*$", lhs.strip()):
            assigned_so_far.add(name)
    return early - _KEYWORDS


class Structure(unittest.TestCase):
    def test_no_settle(self):
        for p in sources():
            hits = re.findall(r"\b\w*settle\w*\b", strip(p.read_text()), flags=re.I)
            self.assertEqual(hits, [], p.name)

    def test_comb_blocks_do_not_read_their_outputs(self):
        for p in sources():
            for _, body in blocks(strip(p.read_text()), "always_comb"):
                self.assertEqual(comb_self_reads(body), set(), f"{p.name}: {body[:200]}")

    def test_no_opcode_literals_outside_the_decode_table(self):
        for p in sources():
            if p.name in OPCODE_FILES:
                continue
            hits = re.findall(r"\b8'[hHdD][0-9a-fA-F_]+", strip(p.read_text()))
            hits = [h for h in hits if set(h.split("'")[1][1:]) - set("0_")]   # 8'h00 / 8'd0 are not opcodes
            self.assertEqual(hits, [], p.name)

    def test_always_ff_clocked_by_clock_and_ce_gated(self):
        for p in sources():
            for header, body in blocks(strip(p.read_text()), "always_ff"):
                self.assertRegex(header.strip(), r"^posedge\s+clock$", p.name)
                if "<=" in body:
                    self.assertRegex(body, r"\bif\s*\(\s*[^)]*\bce(?:_a|_b)?\b", f"{p.name}: {body[:200]}")


# (A1) the bus unit's and the queue's ports
EU_PORT = {"req_v", "req_cyc", "req_addr", "req_width", "req_data", "req_resv",   # EU -> bus
           "req_ack", "req_done", "done_data"}                                    # bus -> EU
BUS_INPUTS = {"clock", "reset_n", "ce_a", "ce_b", "ce_e", "ce_mid", "wtc", "rfm", "data_in",
              "fetch_req", "q_low", "q_word", "fetch_addr",       # the queue's port
              "t_start", "take_now", "l_pop"}                     # (Q2) the aborted fetch's reads
INSTR_TYPES = ("v35_fmt_t", "v35_cls_t", "uc_row_t", "v35_run_t", "req_t", "v35_uword_t",
               "v35_udec_t", "v35_udecm_t")
INSTR_WORDS = re.compile(r"(fmt|cls|class|row|step|xop|opc|form|instr|setup|lead|detach|grp|"
                         r"thru|imm|disp|page|sreg|pfv|nowait|nwt|dwl|strc|mfr|ftl|pth|gdisp|"
                         r"floor|relatch|retire|post|own|slot|halt|wb_|latch_wait|sidle|need|"
                         r"rmw|string|mul|shift|xfer)", re.I)


def ports(name: str) -> list:
    """(direction, type, name) of the module's ANSI port list."""
    text = strip((V35 / name).read_text())
    m = re.search(r"\bmodule\s+\w+.*?\((\s*(?:input|output|inout)\b.*?)\);", text, flags=re.S)
    out = []
    for decl in re.split(r",\s*(?=(?:input|output|inout)\b)", m.group(1)):
        d = re.match(r"\s*(input|output|inout)\s+(.*)$", decl.strip(), flags=re.S)
        if not d:
            continue
        names = [n.strip() for n in d.group(2).replace("\n", " ").split(",") if n.strip()]
        head = names[0].split()
        typ = " ".join(head[:-1])
        out.append((d.group(1), typ, head[-1]))
        out += [(d.group(1), typ, n.split()[-1]) for n in names[1:]]
    return out


class Ports(unittest.TestCase):
    def test_bus_and_queue_carry_no_instruction(self):
        for f in ("v35_bus.sv", "v35_queue.sv"):
            if not (V35 / f).exists():
                continue
            names = ports(f)
            self.assertGreater(len(names), 10, f)
            for d, typ, name in names:
                for t in INSTR_TYPES:
                    self.assertNotIn(t, typ.split(), f"{f}: {name} is a {t}")
                self.assertIsNone(INSTR_WORDS.search(name), f"{f}: {name}")

    def test_bus_inputs_are_the_ports(self):
        if not (V35 / "v35_bus.sv").exists():
            return
        p = ports("v35_bus.sv")
        ins = {n for d, _, n in p if d == "input"}
        self.assertEqual(ins - BUS_INPUTS - EU_PORT, set())
        req = {n for _, _, n in p if n.startswith("req_") or n == "done_data"}
        self.assertEqual(req, EU_PORT)


class MX0(unittest.TestCase):
    """(MX0) the microprogram: no opcode in a word, no count in the word's layout."""

    def test_no_opcode_compare_in_rtl_or_words(self):
        from . import uasm
        for p in sources():
            if p.name in OPCODE_FILES:
                continue
            text = strip(p.read_text())
            hits = [h for h in re.findall(r"==\s*8'[hHdD]([0-9a-fA-F_]+)", text)
                    if set(h[1:] if len(h) > 1 else h) - set("0_")]
            self.assertEqual(hits, [], p.name)
        for p in sorted((V35 / "urom").glob("*.uasm")):
            for ln, line in enumerate(p.read_text().splitlines(), 1):
                code = line.split(";", 1)[0].strip()
                if not code or code.startswith("routine "):
                    continue
                self.assertIsNone(re.search(r"\b(op|reg|rm|mod)\s*=|\b[0-9A-Fa-f]{2}h\b", code),
                                  f"{p.name}:{ln}")
        self.assertTrue(uasm.FIELDS)

    def test_the_word_has_no_count_field(self):
        text = strip((V35 / "v35_pkg.sv").read_text())
        m = re.search(r"typedef\s+struct\s+packed\s*\{(.*?)\}\s*v35_uword_t", text, flags=re.S)
        self.assertIsNotNone(m)
        for name in re.findall(r"(\w+)\s*;", m.group(1)):
            self.assertIsNone(re.search(r"(clk|clock|count|setup|delay|wait|hold|lead|nx|pre)",
                                        name), name)

    def test_no_class_table(self):
        for gone in ("v35_class_tbl.svh", "v35_ucode.sv", "v35_ucode_tbl.svh", "v35_consts.svh",
                     "v35_decode_tbl.svh"):
            self.assertFalse((V35 / gone).exists(), gone)


class MX1(unittest.TestCase):
    """(MX1) the memory forms: the dispatch's EA head is chosen by the ModR/M byte's mode bits
    and the decode table's two bits, nothing else; the bus unit and the queue untouched."""

    def test_the_ea_head_reads_the_mode_only(self):
        text = strip((V35 / "v35_loader.sv").read_text())
        m = re.search(r"wire\s+m_dir\s*=(.*?);\s*wire\s+m_ea\s*=(.*?);.*?head\s*=(.*?);"
                      r"\s*assign\s+dcall\s*=(.*?);", text, flags=re.S)
        self.assertIsNotNone(m)
        names = set(re.findall(r"[A-Za-z_][\w.]*", re.sub(r"\d+'[dhb]\w+", "", " ".join(m.groups()))))
        self.assertEqual(names - {"mp", "dec1.has_modrm", "dm.ea", "dm.eab", "UROM_EAB0",
                                  "UROM_EAB8", "UROM_EAB16", "UROM_EA8", "UROM_EAD", "m_dir",
                                  "m_ea", "dm.entry"}, set())

    def test_heads_named_by_the_assembler(self):
        from . import uasm
        text = (V35 / "v35_udecode_tbl.svh").read_text()
        for name in uasm.EA_HEADS.values():
            self.assertRegex(text, rf"localparam logic \[UADDR_W-1:0\] {name} = ")


class Lint(unittest.TestCase):
    """The lint's own checks, on snippets."""

    def test_comb_self_read(self):
        self.assertEqual(comb_self_reads("begin x = a; y = x & b; end"), set())  # write, then read: procedural
        self.assertEqual(comb_self_reads("begin x = a; if (c) x = b; end"), set())
        self.assertEqual(comb_self_reads("begin n = n + 1; end"), {"n"})

    def test_blocks(self):
        t = strip("always_ff @(posedge clock) begin if (ce) begin q <= d; end end // settle")
        (h, b), = blocks(t, "always_ff")
        self.assertEqual(h, "posedge clock")
        self.assertIn("q <= d", b)
        self.assertNotIn("settle", t)


if __name__ == "__main__":
    unittest.main()
