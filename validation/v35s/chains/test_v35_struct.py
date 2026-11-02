"""Structure lint of the core v2 RTL (docs/v35s-core-v2.md, "Verification": structure lint) over
fpga/v35s/core/v35/*.sv and *.svh. Passes on an empty or partial directory.

Rules (comments and string literals are stripped first):
1. no identifier containing `settle` (the old core's fixpoint registers);
2. no `always_comb` block that assigns a signal it also reads (no block reads its own outputs:
   the clock's logic is feed-forward);
3. no 8-bit opcode literals (`8'h..`, `8'd..`) outside the generated v35_decode_tbl.svh and
   v35_pkg.sv: RTL compares format bits and row fields, never opcode bytes;
4. every `always_ff` is clocked by `posedge clock` and its state updates are gated by `ce`
   (an `if` on `ce` in the block).
The checks are textual (a lint, not a parser): keep blocks plain `begin ... end`."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V35 = ROOT / "fpga" / "v35s" / "core" / "v35"
OPCODE_FILES = ("v35_decode_tbl.svh", "v35_pkg.sv",
                # S2's hand-written stub decode, retired by S3 (docs/v35s-core-v2.md Record)
                "v35_decode_stub.svh", "v35_stub_pkg.sv")


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
                    self.assertRegex(body, r"\bif\s*\(\s*[^)]*\bce\b", f"{p.name}: {body[:200]}")


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
