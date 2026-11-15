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
   are its clocking and configuration, the EU request port, the queue's fetch port, nothing
   else ((step D) the aborted fetch's three read strobes, the reservation and the queue's low
   hint and word room are gone).
7. (step B, docs/v35s-core-v2-interfaces.md) the port budget: per core module the outputs read
   and the inputs driven by another core module, per module pair the wires, both as v35_top
   wires them and both ceilings; v35_top's logic outside simulation is the clock, the reset
   exit, the ticks, the pins and named nets only, its instance connections plain wiring; no
   module adds a next-value (`_nx`) output.
8. (step D) the removed rule-only terms (the sequencer's stalls but the four, the EU's RAMEN
   hold and the reservation, the bus unit's aborted cycle, I/O hold and recovery window and its
   phase outputs, the queue's room rules and hints, the loader's release and staging-slot room,
   the microword flags and decode bits only they read, the fitted integers) may not reappear:
   no identifier of the ban list (BANNED) and no `FIT_` identifier in the core's RTL.
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
EU_PORT = {"req_v", "req_cyc", "req_addr", "req_width", "req_data",               # EU -> bus
           "req_ack", "req_done", "done_data",                                    # bus -> EU
           "req_ia",               # (F3b) the request kind's acknowledge bit (with RQ_IOR)
           "req_dk"}               # (F4c) the request is a DMA transfer's cycle (DMAAK, TC)
BUS_INPUTS = {"clock", "reset_n", "ce_a", "ce_b", "ce_e", "ce_mid", "wtc", "data_in",   # (step C) rfm gone (unread)
              "fetch_req", "fetch_addr",                          # the queue's fetch port
              "idb", "ramen",                                     # (F1) the on-chip decision (SFR registers)
              "sfr_rd", "oc_rd",                                  # (step B) the on-chip cycle's read data (SFR page, register RAM)
              "hrq", "rdy_en", "rdy_lv"}                          # (F4d) HLDRQ, PMC1 bit 7, READY (v35_sfr's registers: pins)
# (step C) the queue's whole port list: the FIFO's ports (fetch, read, pop, control) and the
# facts step C left in place (the tags, the head facts the loader's head select reads, the next
# values); (step D) the legacy room inputs and outputs (rel, stg, abort_go, q_low, q_word,
# fetch_raise) gone, the head byte's offset (hip) and the reset's first offset (reset_ip) in
QUEUE_PORTS = {
    "input": {"clock", "reset_n", "ce_a", "ce_b",
              "fetch_go", "dlv_v", "dlv_data",                    # the fetch port's reply
              "pop_n",                                            # the pop (0 to 2 bytes)
              "flush", "flush_addr", "reset_ip", "susp", "ps_base",   # the control
              "dlv_tag"},                                         # the tags (left by step C)
    "output": {"fetch_req", "fetch_addr",                         # the fetch port
               "vb0", "vb1", "avail", "hip",                      # the read port
               "stored", "h_q0", "h_lat", "h_latv", "h_odd",      # the head facts (MX5b)
               "h_q0t", "h_latt",                                 # the tags
               "stored_nx", "latv_nx", "odd_nx", "discard_nx"},   # the next values
}
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

    def test_queue_head_facts_are_its_registers(self):
        """(MX5b) the queue's head facts (the loader's head-byte decode before the select) are
        its own registers, driven directly: the first stored byte, the latched byte, the latch's
        bit, the in-flight word's parity; (MX5c) the first stored byte's and the latched byte's
        tags (the bits stored beside each byte, opaque to the queue); nothing else of that kind."""
        if not (V35 / "v35_queue.sv").exists():
            return
        outs = {n for d, _, n in ports("v35_queue.sv") if d == "output" and n.startswith("h_")}
        self.assertEqual(outs, {"h_q0", "h_lat", "h_latv", "h_odd", "h_q0t", "h_latt"})
        text = strip((V35 / "v35_queue.sv").read_text())
        for name, reg in (("h_q0", r"q\[0\]"), ("h_lat", "lat_byte"), ("h_latv", "lat_v"),
                          ("h_odd", "odd"), ("h_q0t", r"q_t\[0\]"), ("h_latt", "lat_t")):
            self.assertRegex(text, rf"assign\s+{name}\s*=\s*{reg}\s*;")

    def test_queue_next_values_are_its_registers_d(self):
        """(MX5c) the queue's next-value outputs (the sequencer's registered stall reads them in
        tick B) are exactly the D nets of four of its registers: the count, the latch's bit, the
        parity, the discard; each loaded with that net at ce_a."""
        if not (V35 / "v35_queue.sv").exists():
            return
        outs = {n for d, _, n in ports("v35_queue.sv") if d == "output" and n.endswith("_nx")}
        self.assertEqual(outs, {"stored_nx", "latv_nx", "odd_nx", "discard_nx"})
        text = strip((V35 / "v35_queue.sv").read_text())
        self.assertRegex(text, r"cnt\s*<=\s*stored_nx\s*;")

    def test_queue_ports_are_pinned(self):
        """(step C) the queue's port list as handed back: no port may be added without editing
        this set (the read-count pair rd / rd_b is the pop `pop_n`; variant A is gone)."""
        if not (V35 / "v35_queue.sv").exists():
            return
        p = ports("v35_queue.sv")
        for d in ("input", "output"):
            self.assertEqual({n for dd, _, n in p if dd == d}, QUEUE_PORTS[d], d)

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
        allowed = {"mp", "dec1.has_modrm", "dm.ea", "dm.eab", "UROM_EAB0", "UROM_EAB8",
                   "UROM_EAB16", "UROM_EA8", "UROM_EAD", "m_dir", "m_ea", "dm.entry"}
        if m is None:
            # (MX5) the dispatch facts as a function of the opcode and the ModR/M byte (dsp_f,
            # registered beside them): the same rule on the function's body (m the byte, d1 / d2
            # the two decode levels)
            m = re.search(r"mdir\s*=(.*?);\s*mea\s*=(.*?);.*?hd\s*=(.*?);"
                          r"\s*dsp_f\.call\s*=(.*?);", text, flags=re.S)
            allowed = {"m", "d1.has_modrm", "d2.ea", "d2.eab", "UROM_EAB0", "UROM_EAB8",
                       "UROM_EAB16", "UROM_EA8", "UROM_EAD", "mdir", "mea", "d2.entry"}
        self.assertIsNotNone(m)
        names = set(re.findall(r"[A-Za-z_][\w.]*", re.sub(r"\d+'[dhb]\w+", "", " ".join(m.groups()))))
        self.assertEqual(names - allowed, set())

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




# ------------------------------------------------------------------------------------------------
# (step B, docs/v35s-core-v2-interfaces.md section 6) The port budget: the signals between the
# core's modules as v35_top wires them, as ceilings (a later batch may lower a count without
# editing this test, never raise one); v35_top's own logic limited to its named categories (the
# CPU clock's divider, the reset exit, the two ticks, the pins' idle forcing, wiring, the trace and
# the simulation's observation); no new next-value (`_nx`) output.

CORE = ROOT / "fpga" / "v35s" / "core"
TOP = V35 / "v35_top.sv"
# instance -> (file, module): the core's modules (v35_intc, the interrupt / service unit, lives in
# ../v35_sfr.sv beside the peripherals)
CORE_INSTANCES = {
    "bus": (V35 / "v35_bus.sv", "v35_bus"),
    "queue": (V35 / "v35_queue.sv", "v35_queue"),
    "loader": (V35 / "v35_loader.sv", "v35_loader"),
    "useq": (V35 / "v35_useq.sv", "v35_useq"),
    "eu": (V35 / "v35_eu.sv", "v35_eu"),
    "regram": (V35 / "v35_regram.sv", "v35_regram"),
    "intc": (CORE / "v35_sfr.sv", "v35_intc"),
}
# ceilings at step D's hand-back (step B's and C's were bus 26/16, queue 19/11, loader 38/35,
# useq 20/50, eu 36/39, regram 3/13, intc 14/14: 156 outputs, 178 inputs; step D's 129 / 146).
# The rule-only terms went with their ports; two pairs rose with the moves step C left (the head
# byte's offset: queue -> loader 14 -> 15, eu -> loader 2 -> 1; the flush address straight from
# the EU: eu -> queue 1 -> 2), the whole budget falling: per module, the outputs read by another
# core module and the inputs driven by one; per (driver, reader) pair, the reader's inputs the
# driver feeds
BUDGET_MODULE = {
    "bus": {"out": 16, "in": 10},
    "queue": {"out": 17, "in": 9},
    "loader": {"out": 25, "in": 34},
    "useq": {"out": 20, "in": 29},
    "eu": {"out": 35, "in": 37},
    "regram": {"out": 3, "in": 13},
    "intc": {"out": 13, "in": 14},
}
BUDGET_PAIR = {
    ("bus", "eu"): 9, ("bus", "intc"): 1, ("bus", "loader"): 4, ("bus", "queue"): 3,
    ("bus", "regram"): 5,
    ("eu", "bus"): 7, ("eu", "intc"): 3, ("eu", "loader"): 1, ("eu", "queue"): 2,
    ("eu", "regram"): 8, ("eu", "useq"): 14,
    ("intc", "eu"): 10, ("intc", "useq"): 3,
    ("loader", "eu"): 13, ("loader", "queue"): 2, ("loader", "useq"): 12,
    ("queue", "bus"): 2, ("queue", "loader"): 15,
    ("regram", "bus"): 1, ("regram", "eu"): 2,
    ("useq", "eu"): 3, ("useq", "intc"): 10, ("useq", "loader"): 14, ("useq", "queue"): 2,
}
# the next-value outputs left at step D (none may be added), each with its reader: the bus
# unit's delivery (loader q_dlv_nx: q_stall_nx's byte count), datum register (loader h_dlv_nx:
# the tag register) and the EU's cycle end (eu req_done_nx: opr_rdy_nx, rq_busy_nx,
# wr_hold_nx); the queue's four (loader: q_stall_nx's byte count); the loader's q_stall_nx
# (useq: the registered stall) and opc / modrm / fmt (eu: the early register read); the
# sequencer's word and two derived bits (eu: the early read; loader: lx); the EU's three (useq:
# the registered stall)
NX_OUTPUTS = {
    "bus": {"dlv_fetch_nx", "done_nx", "eu_done_nx"},
    "queue": {"discard_nx", "latv_nx", "odd_nx", "stored_nx"},
    "loader": {"fmt_nx", "modrm_nx", "opc_nx", "q_stall_nx"},
    "useq": {"w_dispm_nx", "w_erep_nx", "word_nx"},
    "eu": {"opr_rdy_nx", "rq_busy_nx", "wr_hold_nx"},
}
# (step D) the removed rule-only terms: no identifier of these may reappear in the core's RTL
# (comments and strings stripped), nor any FIT_ integer
BANNED = {
    # the sequencer's stalls but q, f, slot, hold, halt, and their facts
    "st_bw", "st_uh", "st_wp", "st_wbw", "st_tsy", "st_fch", "st_sus", "st_rfl", "st_oth",
    "tw", "tw_n", "tw_b", "tw_f", "rqp", "drop", "drop_n", "drop_b", "u_sus", "un", "un_n",
    "wbn", "wpn", "rf", "rf_n", "arm", "ask", "mvbiu", "fetch_run", "bus_wait", "fetch_dph",
    "f_abort", "f_grant", "f_dlv", "q_req",
    # the EU's reservation
    "req_resv", "resv", "resv_e", "resv_r", "resv_eb", "tk_go", "tk_go_b",
    # the bus unit's aborted cycle, I/O hold, recovery window and phase outputs
    "ab_tri", "ab_b2b", "ab_v", "ab_pos", "abt", "g_abort", "g_abort_b", "abort_go",
    "abort_busy", "tri3", "ioh", "ioh_hold", "ioh_set", "ioh_clr_b", "ioh_set_b", "fr_prev",
    "io_tail", "io_win", "eu_ok", "fetch_inflight", "fetch_past_b2", "in_wait", "b2b_now",
    "fetch_inflight_nx", "fetch_past_b2_nx", "in_wait_nx", "b2b_now_nx", "cpu_end_prev",
    "t_start", "take_now", "l_pop",
    # the queue's room rules and hints
    "q_low", "q_word", "q_short", "fetch_raise", "lat_hold", "unc_a", "unrel", "eq_r",
    # the loader's release and staging-slot room, its rule-only facts
    "rel", "stg", "stg_free", "hold_n", "hold_r", "hold2", "hold2_n", "hold_nb", "hold_rb",
    "hold2_b", "ipo", "foff_b", "l_load", "o_pop", "o_epop", "s_modrm", "s_wbs", "e_rmodrm",
    "rmem", "s_modrm_nx", "s_wbs_nx", "rmem_nx", "q_arrive",
    # the microword flags and decode bits only the removed rules read
    # (the word's `fw` is checked on the struct below: the loader's zc_f has an argument of that
    # name, the word's FLUSH)
    "wb", "wp", "wbs", "rq",
}
# (step D) the microword and the decode carry none of the removed rules' fields
BANNED_FIELDS = {"v35_uword_t": {"resv", "wb", "wp", "fw"}, "v35_udec_t": {"rq", "wbs"}}
# v35_top's registers outside simulation (the divider, the reset exit, the ticks, the pins' idle
# forcing; (step C) N/S's sampler is the EU's) and its continuous logic (operators on the
# right-hand side)
TOP_REGS = {"x_count", "pck", "state_n", "started", "core_run", "rx_refrq_n", "ceb_age",
            "b_seen", "a0", "a19", "a18_ube", "mux_address", "data_out", "mreq_n",
            "mstb_n", "iostb_n", "read_write", "refrq_n"}
TOP_CE_REGS = {"ceb_age", "b_seen"}     # the registers v35_top loads in a block reading ce_a / ce_b
                                        # outside simulation: the ticks' own (b_seen: a ce_b since reset)
TOP_LOGIC = {"x_last", "x_mid", "state_start", "state_mid", "state_now", "core_reset_n",
             "ce_e", "ce_a", "ce_b",
             "unused"}          # (the lint's sink of unread inputs)
_OPS = re.compile(r"&&|\|\||==|!=|<=|>=|[?~!^+\-<>|&*/%]")


def synth_text(text: str) -> str:
    """The text a synthesis build reads: `ifndef SYNTHESIS` branches blanked (lines kept)."""
    out, stack = [], []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("`ifndef") or s.startswith("`ifdef"):
            stack.append(s.split()[0] == "`ifndef" and s.split()[1] == "SYNTHESIS")
            out.append("")
            continue
        if s.startswith("`else"):
            if stack:
                stack[-1] = False if stack[-1] else stack[-1]
            out.append("")
            continue
        if s.startswith("`endif"):
            if stack:
                stack.pop()
            out.append("")
            continue
        out.append("" if any(stack) else line)
    return "\n".join(out)


def module_ports(path: Path, module: str) -> list:
    """(direction, type, name) of `module`'s ANSI port list in `path`."""
    text = strip(path.read_text())
    m = re.search(rf"\bmodule\s+{module}\b.*?\((\s*(?:input|output|inout)\b.*?)\);", text,
                  flags=re.S)
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


def instances(text: str) -> dict:
    """instance -> {port: expression} for every `v35_* [#(...)] name (...);` in `text`."""
    out = {}
    for m in re.finditer(r"\b(v35_\w+)\s*(?:#\s*\((?:[^()]|\([^()]*\))*\))?\s+(\w+)\s*\(", text):
        i, depth = m.end(), 1
        while depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        body = text[m.end():i - 1]
        conns, j = {}, 0
        for c in re.finditer(r"\.(\w+)\s*", body):
            if c.start() < j:
                continue
            k = c.end()
            if k < len(body) and body[k] == "(":
                d, e = 1, k + 1
                while d:
                    d += {"(": 1, ")": -1}.get(body[e], 0)
                    e += 1
                conns[c.group(1)] = body[k + 1:e - 1].strip()
                j = e
            else:
                conns[c.group(1)] = c.group(1)
                j = k
        out[m.group(2)] = conns
    return out


def idents(expr: str) -> set:
    """The nets an expression reads (a struct field or hierarchical part is its base name)."""
    expr = re.sub(r"\d*'[sS]?[bBhHdD][0-9a-fA-F_xXzZ]+|\d+'\(|'\d+", " ", expr)
    return {n for n in re.findall(r"(?<![.\w])([A-Za-z_]\w*)", expr)}


def budget(v35: Path = V35, core: Path = CORE) -> tuple:
    """(per module {"out": n, "in": n}, per pair {(driver, reader): n}) as v35_top wires them."""
    top = synth_text(strip((v35 / "v35_top.sv").read_text()))
    inst = instances(top)
    dirs = {}
    for name, (path, module) in CORE_INSTANCES.items():
        path = (core if path.parent == CORE else v35) / path.name
        dirs[name] = {n: d for d, _, n in module_ports(path, module)}
    driver = {}
    for name in CORE_INSTANCES:
        for port, expr in inst.get(name, {}).items():
            if dirs[name].get(port) == "output":
                for n in idents(expr):
                    driver[n] = (name, port)
    mod = {n: {"out": set(), "in": set()} for n in CORE_INSTANCES}
    pair = {}
    for name in CORE_INSTANCES:
        for port, expr in inst.get(name, {}).items():
            if dirs[name].get(port) != "input":
                continue
            src = {driver[n] for n in idents(expr) if n in driver and driver[n][0] != name}
            for d, dport in src:
                mod[d]["out"].add(dport)
            if src:
                mod[name]["in"].add(port)
            for d in {d for d, _ in src}:
                pair[(d, name)] = pair.get((d, name), 0) + 1
    return ({n: {"out": len(v["out"]), "in": len(v["in"])} for n, v in mod.items()}, pair)


def always_bodies(text: str) -> list:
    """The body of every `always` / `always_ff` / `always_comb` block (its event control
    skipped): a begin ... end matched by nesting, or a single statement up to its `;`."""
    out = []
    for m in re.finditer(r"\balways(?:_ff|_comb|_latch)?\b\s*(?:@\s*(?:\*|\([^)]*\)))?", text):
        i = m.end()
        b = re.match(r"\s*begin\b", text[i:])
        if b:
            depth, j = 0, i
            for t_ in re.finditer(r"\b(begin|end)\b", text[i:]):
                depth += 1 if t_.group(1) == "begin" else -1
                if depth == 0:
                    j = i + t_.end()
                    break
            out.append(text[i:j])
        else:
            out.append(text[i:text.index(";", i) + 1])
    return out


class Budget(unittest.TestCase):
    def test_module_ports_within_budget(self):
        mod, _ = budget()
        for name, lim in BUDGET_MODULE.items():
            self.assertLessEqual(mod[name]["out"], lim["out"], f"{name} outputs to the core")
            self.assertLessEqual(mod[name]["in"], lim["in"], f"{name} inputs from the core")
        self.assertEqual(set(mod) - set(BUDGET_MODULE), set())

    def test_module_pairs_within_budget(self):
        _, pair = budget()
        for p, n in pair.items():
            self.assertLessEqual(n, BUDGET_PAIR.get(p, 0), f"{p[0]} -> {p[1]}")

    def test_no_new_next_value_output(self):
        for name, (path, module) in CORE_INSTANCES.items():
            nx = {n for d, _, n in module_ports(path, module) if d == "output" and n.endswith("_nx")}
            self.assertEqual(nx - NX_OUTPUTS.get(name, set()), set(), name)

    def test_removed_terms_do_not_reappear(self):
        """(step D) no banned identifier and no FIT_ integer in the core's RTL (v35/*.sv,
        *.svh, and v35_sfr.sv's interrupt / service unit), comments and strings stripped."""
        # (v35_sfr.sv's peripherals have names of their own, `rq` and `arm` among them: there
        # the interrupt unit's removed output only)
        files = [(p, BANNED) for p in sources()] + [(CORE / "v35_sfr.sv", {"tk_go"})]
        for p, ban in files:
            text = strip(p.read_text())
            names = set(re.findall(r"(?<![.\w`'])([A-Za-z_]\w*)", text))
            self.assertEqual(names & ban, set(), p.name)
            self.assertEqual({n for n in names if n.startswith("FIT_")}, set(), p.name)
        pkg = strip((V35 / "v35_pkg.sv").read_text())
        for typ, bad in BANNED_FIELDS.items():
            body = re.search(r"typedef\s+struct\s+packed\s*\{(.*?)\}\s*" + typ + r"\s*;", pkg,
                             flags=re.S).group(1)
            fields = set(re.findall(r"(\w+)\s*;", body))
            self.assertGreater(len(fields), 5, typ)
            self.assertEqual(fields & bad, set(), typ)

    def test_top_holds_no_module_logic(self):
        """v35_top outside simulation: registers only of the named list (under ce_a / ce_b only
        the ticks' own), continuous logic only of the named list, instance connections plain wiring (a
        net, a constant, a bit or field select: no operator)."""
        text = synth_text(strip(TOP.read_text()))
        for body in always_bodies(text):
            regs = set(re.findall(r"([A-Za-z_]\w*)(?:\s*\[[^\]]*\])*\s*<?=(?!=)", body))
            regs -= _KEYWORDS
            self.assertEqual(regs - TOP_REGS, set(), body[:200])
            if re.search(r"\bce_[ab]\b", body):
                self.assertEqual(regs - TOP_CE_REGS, set(), body[:200])
        for m in re.finditer(r"\b(?:assign|wire|reg)\b(?:\s+(?:signed|\[[^\]]*\]))*\s+(\w+)\s*=([^;]*);",
                             text):
            if _OPS.search(m.group(2)):
                self.assertIn(m.group(1), TOP_LOGIC, m.group(0))
        for name, conns in instances(text).items():
            for port, expr in conns.items():
                self.assertIsNone(_OPS.search(re.sub(r"\[[^\]]*\]", "", expr)),
                                  f"{name}.{port}({expr})")


if __name__ == "__main__":
    unittest.main()
