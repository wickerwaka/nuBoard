"""Offline tests of the chain generator: catalog, placement, parity, counts."""

from __future__ import annotations

import json
import unittest

from validation.v35s.asm import assemble
from validation.v35s.chains import blocks
from validation.v35s.chains.families import FAMILIES, generate
from validation.v35s.chains.forms import FORMS, MODES, MODE_CLASSES
from validation.v35s.chains.image import build_image
from validation.v35s.chains.types import CODE_BASE, Chain, Instr

# Declared length of every catalog form (plan, "Form catalog").
LENGTHS = {
    "nop": 1, "xch_aw_dw": 1, "mov_aw_dw": 2, "add_aw_dw": 2, "mov_cl_imm": 2,
    **{f"shl_cl{n}": 4 for n in range(32)},
    "shl1": 2, "mulu_dw": 2, "mov_aw_imm": 3, "add_aw_imm": 3, "shl_imm4": 3, "add_dw_imm": 4,
    "pfx_nop": 2, "pfx_mov_aw_dw": 3, "pfx_mov_aw_imm": 4, "pfx2_mov_aw_imm": 5,
    "pfx3_mov_aw_imm": 6, "pfx_es": 1,
    **{f"ld_{m.name}": 2 + len(m.disp) for m in MODES},
    "ld_acc_dir": 3, "ldb_bw": 2,
    "add_aw_m": 2, "cmp_aw_m": 2, "test_m_aw": 2, "cmp_m_imm": 4, "mulu_m": 2,
    "st_bw": 2, "stb_bw": 2, "st_acc_dir": 3, "st_imm_bw": 4, "st_imm_bw_d16": 6,
    "add_m_aw": 2, "inc_m": 2, "not_m": 2, "shl_m1": 2, "add_m_imm": 4, "add_m_imm_d16": 6,
    "xch_m_aw": 2, "push_m": 2, "pop_m": 2, "push_aw": 1, "pop_aw": 1,
    "out_imm_al": 2, "out_imm_aw": 2, "in_al_imm": 2, "in_aw_imm": 2, "out_dw_al": 1,
    "in_al_dw": 1,
    # F10 predecessors
    "mov_dw_imm": 3, "mov_dw_ff04": 3, "mov_dw_aw": 2, "mov_cw_aw": 2, "add_dw_imm0": 4, "ld_dw_dir": 4,
    # F12
    "add_aw_imm81": 4,
    # F14
    "cmp_m_aw": 2, "test_m_imm": 4, "xch_cw_m": 2, "neg_m": 2, "test_m_al": 2, "xch_m_al": 2,
    "add_m_al": 2, "cmp_m_al": 2, "test_dir_aw": 4, "xch_dir_aw": 4, "divu_m": 2,
    "shl_m_cl": 2, "mulu_aw": 2, "shl_imm8": 3,
    # F15
    "and_m_aw": 2, "and_aw_m": 2, "and_m_imm": 4, "or_m_aw": 2, "xor_aw_m": 2, "sub_m_aw": 2,
    "and_dir_aw": 4, "cmp_dir_aw": 4, "test_al_imm": 2, "test_aw_imm": 3, "add_m_imm8": 3,
    "and_m_imm8": 3, "pop_m_dir": 4, "pop_m_d8": 3, "pop_m_ix": 2, "pop_cw": 1,
    "shl_imm16": 3,
    # F16
    "rol_m1": 2, "ror_m1": 2, "rcl_m1": 2, "rcr_m1": 2, "shr_m1": 2, "sar_m1": 2, "mul_m": 2,
    "div_m": 2, "dec_m": 2, "shlb_m1": 2, "mulub_m": 2, "shl_aw_cl": 2, "divu_ix": 2,
    "shl_imm1": 3, "shl_imm2": 3, "mov_cl1": 2, "mov_cl2": 2, "mov_cl8": 2, "mov_cl16": 2,
    # F17: DS1: MOV byte [0FFE1h],imm8 (prefix + C6 06 lo hi imm8)
    "rfm_fc": 6, "rfm_ec": 6, "rfm_fd": 6,
    # F19: C6 07 imm8, C7 47 d8 imm16, 83 3F imm8, EE, ED
    "st_imm8_bw": 3, "st_imm_bw_d8": 5, "cmp_m_imm8": 3, "out_dw_b": 1, "in_aw_dw": 1,
    # F21: the consumers over the EA modes not in the catalog before
    "st_bw_d8": 3, "st_bw_d16": 4, "st_bw_ix": 2, "st_bw_ix_d8": 3, "st_bw_ix_d16": 4,
    "st_dir": 4, "st_imm_bw_ix": 4, "st_imm_bw_ix_d8": 5, "st_imm_bw_ix_d16": 6,
    "st_imm_dir": 6, "add_m_aw_bw_d8": 3, "add_m_aw_bw_d16": 4, "add_m_aw_bw_ix": 2,
    "add_m_aw_bw_ix_d8": 3, "add_m_aw_bw_ix_d16": 4, "add_m_aw_dir": 4, "pop_m_bw_d16": 4,
    "pop_m_bw_ix": 2, "pop_m_bw_ix_d8": 3, "pop_m_bw_ix_d16": 4,
    # F22: the immediate RMW, CMP and TEST forms not in the catalog before
    "add_m_imm_d8": 5, "add_m_imm_dir": 6, "add_m_imm8_d16": 5, "cmp_m_imm_d16": 6,
    "test_m_imm_d16": 6,
}

# Runs per family: the plan's figures with room for the documented choices.
# F2-F8 run once per cost marker kind (push, out), so their counts double.
RUN_RANGES = {"F0": (18, 18), "F0w": (16, 20), "F1": (54, 54), "F2": (120, 120),
              "F3": (680, 880), "F4": (400, 520), "F5": (720, 880), "F6": (540, 660),
              "F7": (432, 460), "F8": (36, 72), "F9": (408, 408),
              "F10": (204, 204), "F11": (132, 132),
              "F12": (204, 204), "F13": (462, 462), "F14": (732, 732),
              "F15": (840, 840), "F16": (1014, 1014), "F17": (798, 798),
              "F18": (1164, 1164), "F19": (1290, 1290),
              "F20": (3594, 3594), "F21": (3576, 3576),
              "F22": (1320, 1320)}


class CatalogTests(unittest.TestCase):
    def test_lengths_declared(self):
        self.assertEqual(set(FORMS), set(LENGTHS))
        for name, form in FORMS.items():
            self.assertEqual(form.length, LENGTHS[name], name)

    def test_forms_round_trip_through_db(self):
        for name, form in FORMS.items():
            source = "DB " + ", ".join(f"0x{b:02X}" for b in form.code)
            self.assertEqual(assemble(source, org=0x100), form.code, name)

    def test_modes(self):
        self.assertEqual(len(MODES), 24)
        self.assertEqual(len({(m.mod, m.rm) for m in MODES}), 24)
        for m in MODES:
            self.assertIn(m.mode_class, MODE_CLASSES)
            self.assertLess(m.ea, 0x1000, m.name)
        self.assertEqual(FORMS["ld_dir"].code, bytes([0x8B, 0x06, 0x00, 0x0C]))
        self.assertEqual(FORMS["ld_bw_d8"].code, bytes([0x8B, 0x47, 0x10]))
        self.assertEqual(FORMS["st_imm_bw_d16"].code, bytes.fromhex("c7870002" "3412"))
        self.assertEqual(FORMS["shl_cl16"].code, bytes.fromhex("b110d3e0"))
        self.assertEqual([m.name for m in MODES if m.uses_bw], ["bw", "bw_d8"])

    def test_blocks(self):
        self.assertEqual(blocks.LS, bytes.fromhex("b11fd3e0"))
        self.assertEqual(blocks.marker("out", 2), bytes.fromhex("e622"))
        self.assertEqual(blocks.marker("store", 0), bytes.fromhex("a3000c"))
        self.assertEqual([blocks.drainer(i).hex() for i in range(3)],
                         ["b83412", "ba7856", "b83412"])
        self.assertEqual(blocks.END, bytes.fromhex("ba00ffeff4") + b"\x90" * 16)


class ChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chains = generate()

    def test_ids_unique_and_safe(self):
        ids = [c.id for c in self.chains]
        self.assertEqual(len(ids), len(set(ids)))
        for i in ids:
            self.assertRegex(i, r"^[A-Za-z0-9_.-]+$")

    def test_every_chain_builds_with_parity(self):
        for chain in self.chains:
            built = build_image(chain)          # asserts byte placement itself
            code = built.code
            for instr in chain.instrs:
                at = built.chain_base - CODE_BASE + instr.offset
                self.assertEqual(code[at:at + len(instr.code)], instr.code, chain.id)
            ls = next(i for i in chain.instrs if i.role == "ls")
            after = built.chain_base + ls.offset + len(ls.code)
            self.assertEqual(after & 1, int(chain.parity == "odd"), chain.id)
            pads = [i for i in chain.instrs if i.role == "pad"]
            self.assertLessEqual(len(pads), 1)
            if pads:
                self.assertEqual(chain.instrs[0].role, "pad")
            self.assertEqual(chain.instrs[-1].role, "end")
            self.assertEqual(built.image[0x0800], b"\x90" * 0x800)

    def test_parity_pairs_differ_by_pad(self):
        by_id = {c.id: c for c in self.chains}
        for chain in self.chains:
            if chain.parity == "even":
                odd = by_id[chain.id.replace("-pE", "-pO")]
                strip = lambda c: [i.code for i in c.instrs if i.role != "pad"]
                self.assertEqual(strip(chain), strip(odd), chain.id)

    def test_family_counts(self):
        for family, (low, high) in RUN_RANGES.items():
            n = sum(1 for c in self.chains if c.family == family)
            self.assertGreaterEqual(n, low, family)
            self.assertLessEqual(n, high, family)
        self.assertEqual(set(RUN_RANGES), set(FAMILIES))

    def test_odd_alignment_only_for_bw_forms(self):
        for chain in self.chains:
            if chain.knobs.get("align") == "odd":
                self.assertEqual(chain.regs["BW"], 0x0801)
                self.assertIn(FORMS[chain.knobs["x"]].mode, ("bw", "bw_d8"))
            else:
                self.assertEqual(chain.regs["BW"], 0x0800, chain.id)

    def test_dw_port_forms(self):
        for chain in self.chains:
            if any(i.form in ("out_dw_al", "in_al_dw", "out_dw_b", "in_aw_dw")
                   for i in chain.instrs):
                self.assertEqual(chain.regs["DW"], 0x0040)

    def test_wtc_memory_waits_only(self):
        for chain in self.chains:
            if chain.family != "F0w":
                self.assertEqual(chain.wtc, chain.waits, chain.id)   # field 0; I/O field 0
                self.assertEqual(chain.wtc & 0xC000, 0, chain.id)

    def test_cost_families_have_both_markers(self):
        for chain in self.chains:
            markers = [i for i in chain.instrs if i.role == "marker"]
            if chain.family in ("F0", "F0w", "F1", "F9", "F10", "F11", "F12", "F13", "F14",
                                "F15", "F16", "F17", "F18", "F19", "F20", "F21",
                                "F22"):
                continue
            self.assertIn(chain.marker_kind, ("push", "out"), chain.id)
            self.assertTrue(chain.id.startswith(f"{chain.family}-{chain.marker_kind}-"), chain.id)
            self.assertEqual(chain.knobs["marker"], chain.marker_kind)
            self.assertTrue(markers)
            for m in markers:
                self.assertEqual(m.code, blocks.marker(chain.marker_kind, m.marker_id), chain.id)
        by_id = {c.id for c in self.chains}
        for chain in self.chains:
            if chain.marker_kind == "push" and chain.family not in ("F1", "F9", "F10", "F12", "F13",
                                                                         "F14", "F15", "F16",
                                                                         "F17", "F19", "F20", "F21",
                                                                         "F22"):
                self.assertIn(chain.id.replace("-push-", "-out-", 1), by_id)

    def test_f9_counts_and_markers(self):
        from validation.v35s.chains.families import F9_X
        f9 = [c for c in self.chains if c.family == "F9"]
        self.assertEqual(len(F9_X), 34)
        self.assertEqual(len({x for x, _ in F9_X}), 34)
        self.assertEqual(len(f9), 34 * 2 * 3 * 2)
        for kind, n_markers in (("push", 1), ("none", 0)):
            runs = [c for c in f9 if c.marker_kind == kind]
            self.assertEqual(len(runs), 34 * 6, kind)
            for c in runs:
                self.assertTrue(c.id.startswith(f"F9-{kind}-"), c.id)
                self.assertEqual(c.knobs["marker"], kind)
                markers = [i for i in c.instrs if i.role == "marker"]
                self.assertEqual(len(markers), n_markers, c.id)
                for m in markers:
                    self.assertEqual(m.code, blocks.marker("push", 0))
        ids = {c.id for c in f9}
        for c in f9:
            if c.marker_kind == "push":
                self.assertIn(c.id.replace("-push-", "-none-", 1), ids)
        self.assertEqual({c.waits for c in f9}, {0, 1, 2})
        self.assertEqual({c.parity for c in f9}, {"even", "odd"})

    def test_f9_placement(self):
        """X's bytes sit right after the first LS, then the marker (or LS), then LS END."""
        from validation.v35s.chains.families import F9_X
        want = {label: b"".join(FORMS[n].code for n in names) for label, names in F9_X}
        self.assertEqual(want["empty"], b"")
        self.assertEqual(want["nop8"], b"\x90" * 8)
        self.assertEqual(want["es2_nop"], bytes.fromhex("262690"))
        self.assertEqual(want["es3_imm"], bytes.fromhex("262e36b83412"))
        self.assertEqual(want["nop_addi"], bytes.fromhex("9081c23412"))
        self.assertEqual(want["imm_nop3"], bytes.fromhex("b83412909090"))
        self.assertEqual(want["movr_nop4"], bytes.fromhex("8bc290909090"))
        for c in (c for c in self.chains if c.family == "F9"):
            label = c.id.split("-", 2)[2].rsplit("-p", 1)[0]
            built = build_image(c)              # raises on any misplaced byte
            ls = [i for i in c.instrs if i.role == "ls"]
            self.assertEqual(len(ls), 2, c.id)
            start = ls[0].offset + len(ls[0].code)
            xs = [i for i in c.instrs if i.role == "x"]
            self.assertEqual(b"".join(i.code for i in xs), want[label], c.id)
            self.assertEqual(c.knobs["bytes"], len(want[label]), c.id)
            if xs:
                self.assertEqual(xs[0].offset, start, c.id)
            at = built.chain_base - CODE_BASE + start
            tail = blocks.marker("push", 0) if c.marker_kind == "push" else b""
            self.assertEqual(built.code[at:at + len(want[label]) + len(tail) + 4],
                             want[label] + tail + blocks.LS, c.id)
            self.assertEqual(c.instrs[-1].role, "end")

    def test_f9_form_not_in_f3(self):
        from validation.v35s.chains.forms import REGISTER_ONLY
        self.assertNotIn("pfx_es", REGISTER_ONLY)
        self.assertFalse(any("pfx_es" in c.id for c in self.chains if c.family == "F3"))

    def test_f10_placement_and_ports(self):
        """F10: LS M0 P X M1 LS END (PUSH) or LS P X LS END; the DW form's expected port
        is the DW the chain leaves it (the long shift clears AW, the load reads the fill)."""
        from validation.v35s.chains.families import F10_HIGH, F10_P, F10_X
        from validation.v35s.chains.normalize import expected_accesses
        f10 = [c for c in self.chains if c.family == "F10"]
        self.assertEqual(len(f10), (len(F10_P) * 2 + 2 * 2 + 2) * 6)
        port = {"movdwaw": 0x0000, "xch": 0x0000, "lddw": 0x9090, "movdwff": 0xFF04}
        for c in f10:
            build_image(c)
            kind, plabel, xlabel = c.id.split("-")[1:4]
            pnames = dict(F10_P + F10_HIGH)[plabel]
            xname = dict(F10_X)[xlabel]
            roles = [i.role for i in c.instrs if i.role != "pad"]
            want = (["ls", "marker"] if kind == "push" else ["ls"]) + ["x"] * (len(pnames) + 1)
            want += (["marker"] if kind == "push" else []) + ["ls", "end"]
            self.assertEqual(roles, want, c.id)
            self.assertEqual([i.form for i in c.instrs if i.role == "x"], pnames + [xname])
            self.assertEqual(c.regs["DW"], 0x0040)
            io = [a for accs in expected_accesses(c).values() for a in accs
                  if a.kind.startswith("io") and a.addr != 0xFF00]
            self.assertEqual([a.addr for a in io], [port.get(plabel, 0x0040)], c.id)

    def test_f11_placement(self):
        from validation.v35s.chains.families import F11_N, F11_X
        f11 = [c for c in self.chains if c.family == "F11"]
        self.assertEqual(len(f11), sum(len(F11_N[x]) for x, _ in F11_X) * 6)
        for c in f11:
            build_image(c)
            xs = [i for i in c.instrs if i.role == "x"]
            n = c.knobs["n"]
            self.assertEqual([i.form for i in xs[:n]], ["nop"] * n, c.id)
            self.assertEqual([i.form for i in xs[n:]], c.knobs["x"], c.id)
            self.assertEqual(c.marker_kind, "none")
            self.assertFalse([i for i in c.instrs if i.role == "marker"])

    def test_f12_placement(self):
        """F12 series A: LS M0 90^n X P LS END (P = OUT 40h,AL, or the PUSH M1 marker in
        the push frame); series B: LS 90^n X LS END and LS M0 X M1 LS END (PUSH)."""
        from validation.v35s.chains.families import (F12_A_FRAMES, F12_A_N, F12_B_N,
                                                     F12_B_PUSH, F12_B_X, F12_PROBE)
        f12 = [c for c in self.chains if c.family == "F12"]
        n_a = sum(len(labels) for _, labels in F12_A_FRAMES.values()) * len(F12_A_N)
        self.assertEqual(len(f12), (n_a + len(F12_B_X) * len(F12_B_N) + len(F12_B_PUSH)) * 6)
        self.assertEqual(FORMS["add_aw_imm81"].code, bytes.fromhex("81c03412"))
        self.assertNotIn("add_aw_imm81", [c.knobs.get("x") for c in self.chains
                                          if c.family == "F3"])
        for c in f12:
            build_image(c)
            k = c.knobs
            roles = [i.role for i in c.instrs if i.role != "pad"]
            xs = [i.form for i in c.instrs if i.role == "x"]
            markers = [i for i in c.instrs if i.role == "marker"]
            self.assertEqual(c.marker_kind, k["marker"], c.id)
            for m in markers:
                self.assertEqual(m.code, blocks.marker(c.marker_kind, m.marker_id), c.id)
            if k["series"] == "a":
                self.assertEqual(c.marker_kind, F12_A_FRAMES[k["frame"]][0], c.id)
                tail = [] if k["frame"] == "push" else [F12_PROBE]
                self.assertEqual(xs, ["nop"] * k["n"] + k["x"] + tail, c.id)
                self.assertEqual(roles, ["ls", "marker"] + ["x"] * len(xs)
                                 + (["marker"] if k["frame"] == "push" else []) + ["ls", "end"])
            elif k["frame"] == "none":
                self.assertEqual(xs, ["nop"] * k["n"] + k["x"], c.id)
                self.assertFalse(markers)
            else:
                self.assertEqual(xs, k["x"], c.id)
                self.assertEqual(roles, ["ls", "marker", "x", "marker", "ls", "end"])

    def test_f13_placement(self):
        """F13: S/S0 LS shl_cl(n) LS END (S0 refresh off), C LS M0 shl_cl(n) M1 LS END, U
        MULU DW^k framed and bare, N NOP^8 bare and PUSH-framed, R LS LS END per RFM."""
        from validation.v35s.chains.families import (F13_C_N, F13_NOPS, F13_R_RFT, F13_R_RFW,
                                                     F13_S0_N, F13_S_N, F13_U_K)
        from validation.v35s.chains.types import RFM_OFF, RFM_ON
        f13 = [c for c in self.chains if c.family == "F13"]
        n = (len(F13_S_N) + len(F13_S0_N) + 2 * len(F13_C_N) + 2 * len(F13_U_K) + 1 + 2
             + len(F13_R_RFT) + len(F13_R_RFW))
        self.assertEqual(len(f13), n * 6)
        for name in (f"shl_cl{n}" for n in range(32)):
            self.assertEqual(FORMS[name].code, bytes([0xB1, int(name[6:]), 0xD3, 0xE0]))
        self.assertEqual(sorted({c.knobs["x"] for c in self.chains if c.family == "F3"
                                 and (c.knobs.get("x") or "").startswith("shl_cl")}),
                         sorted(f"shl_cl{n}" for n in (0, 1, 2, 4, 8, 16, 31)))
        for c in f13:
            build_image(c)
            k = c.knobs
            roles = [i.role for i in c.instrs if i.role != "pad"]
            xs = [i.form for i in c.instrs if i.role == "x"]
            markers = [i for i in c.instrs if i.role == "marker"]
            self.assertEqual(c.marker_kind, k["marker"], c.id)
            self.assertTrue(c.id.startswith(f"F13-{k['series']}-"), c.id)
            for m in markers:
                self.assertEqual(m.code, blocks.marker(c.marker_kind, m.marker_id), c.id)
            if k["series"] == "r":
                self.assertEqual(c.rfm, 0xF0 | (k["rfw"] << 2) | k["rft"], c.id)
                self.assertEqual(roles, ["ls", "ls", "end"], c.id)
                continue
            self.assertEqual(c.rfm, RFM_OFF if k["series"] == "s0" else RFM_ON, c.id)
            want = {"s": [k.get("x")], "s0": [k.get("x")], "c": [k.get("x")],
                    "u": ["mulu_dw"] * k.get("k", 0), "n": ["nop"] * F13_NOPS}[k["series"]]
            self.assertEqual(xs, want, c.id)
            mid = ["x"] * len(xs)
            if c.marker_kind == "none":
                self.assertEqual(roles, ["ls"] + mid + ["ls", "end"], c.id)
            else:
                self.assertEqual(roles, ["ls", "marker"] + mid + ["marker", "ls", "end"], c.id)
        self.assertIn("F13-s-shlcl17-pE-w0", {c.id for c in f13})
        self.assertIn("F13-c-push-shlcl4-pO-w1", {c.id for c in f13})
        self.assertIn("F13-r-rfm-f3-pE-w0", {c.id for c in f13})

    def test_f14_placement(self):
        """F14: T/G LS M0 X^k M1 LS END (PUSH k 1, 2; OUT k 1; G OUT k 2 for three forms) and
        T LS X LS END; O LS M0 X M1 LS END under both markers and LS X LS END."""
        from validation.v35s.chains.families import (F14_G_FRAMES, F14_G_OUT_K2, F14_G_X,
                                                     F14_O_BARE, F14_O_X, F14_T_BARE,
                                                     F14_T_FRAMES, F14_T_X)
        f14 = [c for c in self.chains if c.family == "F14"]
        n = (2 + len(F14_T_X) * len(F14_T_FRAMES) + len(F14_T_BARE)
             + len(F14_G_X) * len(F14_G_FRAMES) + len(F14_G_OUT_K2)
             + 2 * len(F14_O_X) + len(F14_O_BARE))
        self.assertEqual(len(f14), n * 6)
        code = {"cmp_m_aw": "3907", "test_m_imm": "f7073412", "xch_cw_m": "870f",
                "neg_m": "f71f", "test_m_al": "8407", "xch_m_al": "8607", "add_m_al": "0007",
                "cmp_m_al": "3807", "test_dir_aw": "8506000c", "xch_dir_aw": "8706000c",
                "divu_m": "f737", "shl_m_cl": "d327", "mulu_aw": "f7e0", "shl_imm8": "c1e008",
                "test_m_aw": "8507", "xch_m_aw": "8707", "add_m_aw": "0107"}
        for name, hexcode in code.items():
            self.assertEqual(FORMS[name].code.hex(), hexcode, name)
        new = set(code) - {"test_m_aw", "xch_m_aw", "add_m_aw"}
        for c in self.chains:
            if c.family not in ("F14", "F15", "F16", "F18"):   # F15, F16, F18 reuse F14's
                self.assertFalse(new & {i.form for i in c.instrs}, c.id)
        for c in f14:
            build_image(c)
            k = c.knobs
            roles = [i.role for i in c.instrs if i.role != "pad"]
            xs = [i.form for i in c.instrs if i.role == "x"]
            markers = [i for i in c.instrs if i.role == "marker"]
            self.assertEqual(c.marker_kind, k["marker"], c.id)
            self.assertTrue(c.id.startswith(f"F14-{k['series']}-{c.marker_kind}-"), c.id)
            self.assertEqual(c.rfm, 0xEC, c.id)
            for m in markers:
                self.assertEqual(m.code, blocks.marker(c.marker_kind, m.marker_id), c.id)
            want = (k["x"] if isinstance(k["x"], list) else [k["x"]] * k["k"]
                    if k["x"] else [])
            self.assertEqual(xs, want, c.id)
            mid = ["x"] * len(xs)
            if c.marker_kind == "none":
                self.assertEqual(roles, ["ls"] + mid + ["ls", "end"], c.id)
            else:
                self.assertEqual(roles, ["ls", "marker"] + mid + ["marker", "ls", "end"], c.id)
        ids = {c.id for c in f14}
        for i in ("F14-t-push-test_bw_aw-pE-w0", "F14-t-push-xch_bw_aw-k2-pO-w2",
                  "F14-t-out-xch_dir_aw-pE-w1", "F14-t-none-cmp_bw_aw-pO-w0",
                  "F14-g-out-pop_bw-k2-pE-w0", "F14-o-out-movr_nop-pO-w1",
                  "F14-o-push-empty-pE-w0", "F14-o-none-nop_shl4-pE-w2"):
            self.assertIn(i, ids)

    def test_f15_placement(self):
        """F15: A PUSH/OUT LS M0 X M1 LS END and LS X LS END for three forms; P every form at
        its k under PUSH, OUT and marker-less; K PUSH-framed pairs; O OUT and PUSH frames
        and marker-less shifts."""
        from validation.v35s.chains.families import (F15_A_BARE, F15_A_X, F15_FRAMES,
                                                     F15_K_SHAPES, F15_K_X, F15_O_BARE,
                                                     F15_O_X, F15_P_K, F15_P_PAIRS)
        from validation.v35s.chains.forms import F15_IX
        f15 = [c for c in self.chains if c.family == "F15"]
        n_p = len(F15_FRAMES) * (sum(len(ks) for _, _, ks in F15_P_K) + len(F15_P_PAIRS))
        n = (2 + 2 * len(F15_A_X) + len(F15_A_BARE) + n_p + len(F15_K_SHAPES) * len(F15_K_X)
             + 2 * len(F15_O_X) + len(F15_O_BARE))
        self.assertEqual(n, 140)
        self.assertEqual(len(f15), n * 6)
        code = {"and_m_aw": "2107", "and_aw_m": "2307", "and_m_imm": "81273412",
                "or_m_aw": "0907", "xor_aw_m": "3307", "sub_m_aw": "2907",
                "and_dir_aw": "2106000c", "cmp_dir_aw": "3906000c", "test_al_imm": "a834",
                "test_aw_imm": "a93412", "add_m_imm8": "830705", "and_m_imm8": "832705",
                "pop_m_dir": "8f06000c", "pop_m_d8": "8f4710", "pop_m_ix": "8f04",
                "pop_cw": "59", "shl_imm16": "c1e010", "test_m_imm": "f7073412",
                "cmp_m_imm": "813f3412", "test_dir_aw": "8506000c", "pop_m": "8f07"}
        for name, hexcode in code.items():
            self.assertEqual(FORMS[name].code.hex(), hexcode, name)
        new = set(code) - {"test_m_imm", "cmp_m_imm", "test_dir_aw", "pop_m"}
        for c in self.chains:
            if c.family not in ("F15", "F16", "F21"):   # F16 and F21 reuse F15's forms
                self.assertFalse(new & {i.form for i in c.instrs}, c.id)
        for c in f15:
            build_image(c)
            k = c.knobs
            roles = [i.role for i in c.instrs if i.role != "pad"]
            xs = [i.form for i in c.instrs if i.role == "x"]
            markers = [i for i in c.instrs if i.role == "marker"]
            self.assertEqual(c.marker_kind, k["marker"], c.id)
            self.assertTrue(c.id.startswith(f"F15-{k['series']}-{c.marker_kind}-"), c.id)
            self.assertEqual(c.rfm, 0xEC, c.id)
            self.assertEqual(xs, k["x"], c.id)
            for m in markers:
                self.assertEqual(m.code, blocks.marker(c.marker_kind, m.marker_id), c.id)
            mid = ["x"] * len(xs)
            if c.marker_kind == "none":
                self.assertEqual(roles, ["ls"] + mid + ["ls", "end"], c.id)
            else:
                self.assertEqual(roles, ["ls", "marker"] + mid + ["marker", "ls", "end"], c.id)
            if "pop_m_ix" in xs:
                self.assertEqual(c.regs["IX"], F15_IX, c.id)
            # parity is that of the first body byte after the first LS
            built = build_image(c)
            first = next(i for i in c.instrs if i.role not in ("pad", "ls"))
            self.assertEqual((built.chain_base + first.offset) & 1, c.parity == "odd", c.id)
        ids = {c.id for c in f15}
        for i in ("F15-a-push-and_bw_aw-pE-w0", "F15-a-out-test_aw_imm-pO-w2",
                  "F15-a-none-test_bw_imm-pE-w1", "F15-p-push-pop_bw-k3-pO-w1",
                  "F15-p-none-pop_ix-pE-w0", "F15-p-out-pop_push-pO-w2",
                  "F15-k-push-mulu-x_nop_x-pE-w0", "F15-k-push-not-inc_x-pO-w1",
                  "F15-o-out-movr2-pE-w0", "F15-o-push-nop_mulu_aw-pO-w1",
                  "F15-o-none-shl16-pE-w2"):
            self.assertIn(i, ids)

    def test_f16_placement(self):
        """F16: R PUSH-framed X X / INC X / X; P NOP^n POP under PUSH, OUT and marker-less; L
        the OUT frame and PUSH twin, MOV CL,n before M0 for the CL shifts; S marker-less."""
        from validation.v35s.chains.families import (F16_L_X, F16_P_FRAME_X, F16_P_N,
                                                     F16_R_NEW, F16_R_X, F16_S_M, F16_S_N)
        from validation.v35s.chains.forms import F16_DIV_DW, F16_DIVU_IX
        f16 = [c for c in self.chains if c.family == "F16"]
        n_r = 1 + 2 * len(F16_R_X) - 1 + len(F16_R_NEW)
        n_p = sum(len(F16_P_FRAME_X[k]) * len(F16_P_N[k]) for k in F16_P_N)
        n_l = 1 + 2 * len(F16_L_X)
        n_s = len(F16_S_N) * len(F16_S_M) * 2 + (len(F16_S_N) - 1) * len(F16_S_M) + len(F16_S_N)
        self.assertEqual((n_r, n_p, n_l, n_s), (49, 30, 31, 59))
        self.assertEqual(len(f16), (n_r + n_p + n_l + n_s) * 6)
        code = {"rol_m1": "d107", "ror_m1": "d10f", "rcl_m1": "d117", "rcr_m1": "d11f",
                "shl_m1": "d127", "shr_m1": "d12f", "sar_m1": "d13f", "test_m_imm": "f7073412",
                "not_m": "f717", "neg_m": "f71f", "mulu_m": "f727", "mul_m": "f72f",
                "divu_m": "f737", "div_m": "f73f", "inc_m": "ff07", "dec_m": "ff0f",
                "push_m": "ff37", "shlb_m1": "d027", "mulub_m": "f627", "shl_aw_cl": "d3e0",
                "divu_ix": "f7f6", "shl_imm1": "c1e001", "shl_imm2": "c1e002",
                "mov_cl1": "b101", "mov_cl2": "b102", "mov_cl8": "b108", "mov_cl16": "b110"}
        for name, hexcode in code.items():
            self.assertEqual(FORMS[name].code.hex(), hexcode, name)
        new = {"rol_m1", "ror_m1", "rcl_m1", "rcr_m1", "shr_m1", "sar_m1", "mul_m", "div_m",
               "dec_m", "shlb_m1", "mulub_m", "shl_aw_cl", "divu_ix", "shl_imm1", "shl_imm2",
               "mov_cl1", "mov_cl2", "mov_cl8", "mov_cl16"}
        for c in self.chains:
            if c.family not in ("F16", "F18"):            # F18 B reuses DIVU IX
                self.assertFalse(new & {i.form for i in c.instrs}, c.id)
        for c in f16:
            k = c.knobs
            roles = [i.role for i in c.instrs if i.role != "pad"]
            xs = [i.form for i in c.instrs if i.role == "x"]
            self.assertEqual(c.marker_kind, k["marker"], c.id)
            self.assertTrue(c.id.startswith(f"F16-{k['series']}-{c.marker_kind}-"), c.id)
            self.assertEqual(c.rfm, 0xEC, c.id)
            self.assertEqual(xs, k["x"], c.id)
            pre = ["x"] * len(k.get("pre", []))
            mid = ["x"] * (len(xs) - len(pre))
            if c.marker_kind == "none":
                self.assertEqual(roles, ["ls"] + mid + ["ls", "end"], c.id)
            else:
                self.assertEqual(roles, ["ls"] + pre + ["marker"] + mid + ["marker", "ls", "end"],
                                 c.id)
                for m in (i for i in c.instrs if i.role == "marker"):
                    self.assertEqual(m.code, blocks.marker(c.marker_kind, m.marker_id), c.id)
            if "div_m" in xs:
                self.assertEqual(c.regs["DW"], F16_DIV_DW, c.id)
            if "divu_ix" in xs:
                self.assertEqual(c.regs["IX"], F16_DIVU_IX, c.id)
            if "shl_aw_cl" in xs:       # the count in CL from a MOV CL,n before the shift
                cl = [x for x in xs[:xs.index("shl_aw_cl")] if FORMS[x].code[0] == 0xB1]
                self.assertEqual(len(cl), 1, c.id)
            built = build_image(c)
            first = next(i for i in c.instrs if i.role not in ("pad", "ls"))
            self.assertEqual((built.chain_base + first.offset) & 1, c.parity == "odd", c.id)
        ids = {c.id for c in f16}
        for i in ("F16-r-push-empty-pE-w0", "F16-r-push-sar-x_x-pE-w0",
                  "F16-r-push-div-inc_x-pO-w2", "F16-r-push-mulub-pE-w1",
                  "F16-p-push-n3-pop_bw_d8-pE-w1", "F16-p-out-n2-pop_aw-pO-w0",
                  "F16-p-none-n0-pop_bw-pE-w2", "F16-l-out-shlcl8-pO-w1",
                  "F16-l-push-nop2_mulu_aw-pE-w0", "F16-l-out-divu_ix-pE-w2",
                  "F16-s-none-n3-shli16-pE-w0", "F16-s-none-cl2-n1-shlcl-pO-w1",
                  "F16-s-none-n0-movcl-pE-w0"):
            self.assertIn(i, ids)

    def test_f17_placement(self):
        """F17: the prelude leaves refresh off (RFM ECh, FCh for P) and the chain writes RFM
        with DS1: MOV byte [0FFE1h],imm8 (26 C6 06 E1 FF ii, DS1 = F000h) right after the
        first LS (W: after NOP^n); S/E/D/W marker-less, C PUSH-framed; the first body byte
        at the cell's parity."""
        from validation.v35s.chains.families import (F17_C_X, F17_D_X, F17_E_ALL_N, F17_N,
                                                     F17_P_N, F17_P_X, F17_W_N, F17_X)
        from validation.v35s.chains.forms import F17_DS1, RFM_ADDR, RFM_LINEAR
        from validation.v35s.chains.types import refresh_any, rfm_writes
        f17 = [c for c in self.chains if c.family == "F17"]
        n = (len(F17_X) * len(F17_N) + len(F17_X) + (len(F17_N) - 1) * len(F17_E_ALL_N)
             + len(F17_D_X) * len(F17_N) + 3 * len(F17_W_N) + len(F17_C_X)
             + len(F17_P_X) * len(F17_P_N))
        self.assertEqual(n, 133)
        self.assertEqual(len(f17), n * 6)
        self.assertEqual((RFM_ADDR, F17_DS1, RFM_LINEAR), (0xFFE1, 0xF000, 0xFFFE1))
        for v in (0xFC, 0xEC, 0xFD):
            form = FORMS[f"rfm_{v:02x}"]
            self.assertEqual(form.code, bytes([0x26, 0xC6, 0x06, 0xE1, 0xFF, v]))
            self.assertEqual((form.cls, form.writes, form.rfm, len(form.code)),
                             ("store_imm", 0, v, 6))
        # the assembler's own encoding of the store after the DS1 prefix byte (it drops a
        # "DS1:" written before the mnemonic, so the prefix is a DB)
        from validation.v35s.asm import assemble
        self.assertEqual(assemble("    DB 0x26\n    MOV byte [0FFE1h], 0FCh\n", org=0),
                         FORMS["rfm_fc"].code)
        for c in self.chains:
            if c.family not in ("F17", "F18"):            # F18 AC and B reuse RFMON
                self.assertFalse(rfm_writes(c), c.id)
        for c in f17:
            k = c.knobs
            writes = rfm_writes(c)
            self.assertEqual([v for _, v in writes], [k["rfmon"]], c.id)
            self.assertEqual(c.regs["DS1"], F17_DS1, c.id)
            self.assertEqual(c.rfm, 0xFC if k["series"] == "p" else 0xEC, c.id)
            self.assertEqual(refresh_any(c), k["rfmon"] != 0xEC or c.rfm == 0xFC, c.id)
            roles = [i.role for i in c.instrs if i.role != "pad"]
            forms = [i.form for i in c.instrs if i.role == "x"]
            rfm = f"rfm_{k['rfmon']:02x}"
            if k["series"] == "w":
                self.assertEqual(forms, ["nop"] * k["n"] + [rfm], c.id)
            elif k["series"] == "c":
                self.assertEqual(roles, ["ls", "x", "marker"] + ["x"] * len(k["x"])
                                 + ["marker", "ls", "end"], c.id)
                self.assertEqual(forms, [rfm] + k["x"], c.id)
            else:
                self.assertEqual(forms, [rfm] + ["nop"] * k["n"] + k["x"], c.id)
            if k["series"] != "c":
                self.assertEqual(c.marker_kind, "none", c.id)
                self.assertEqual(roles[0], "ls", c.id)
                self.assertEqual(roles[-2:], ["ls", "end"], c.id)
            built = build_image(c)
            first = next(i for i in c.instrs if i.role not in ("pad", "ls"))
            self.assertEqual((built.chain_base + first.offset) & 1, c.parity == "odd", c.id)
            # the store is 6 bytes: what follows it keeps the parity the store had
            w = next(i for i in c.instrs if i.form == rfm)
            self.assertEqual(len(w.code), 6, c.id)

    def test_f18_placement(self):
        """F18: A/AC end the prelude with the marker (PUSH AW 50 or OUT 20h,AL E6 20) directly
        after its MOV AW,imm16 and directly before the chain's first byte (PAD or LS), the
        bare prelude otherwise byte for byte; the chain marker-less; B/BD as F17 S with the
        ES: NOP step; no prelude marker outside A/AC; the first body byte at the cell's
        parity; the normaliser finds the marker before or after clock 0 and tracks SP."""
        from validation.v35s.chains.families import (F18_A_RFM, F18_A_X, F18_B_FD_X, F18_B_N,
                                                     F18_B_STEPS, F18_B_X, F18_MARKERS)
        from validation.v35s.chains.image import PRELUDE_MARKERS, prelude
        from validation.v35s.chains.normalize import expected_accesses, prelude_marker_row
        from validation.v35s.chains.types import refresh_any, rfm_writes
        f18 = [c for c in self.chains if c.family == "F18"]
        n = (len(F18_MARKERS) * (len(F18_A_RFM) * len(F18_A_X) + 1)
             + (len(F18_B_X) + len(F18_B_FD_X)) * len(F18_B_STEPS) * len(F18_B_N))
        self.assertEqual(n, 194)
        self.assertEqual(len(f18), n * 6)
        self.assertEqual(PRELUDE_MARKERS["push"][1], bytes([0x50]))
        self.assertEqual(PRELUDE_MARKERS["out"][1], bytes([0xE6, 0x20]))
        for c in self.chains:
            if c.family != "F18":
                self.assertIsNone(c.prelude_marker, c.id)
                self.assertNotIn("prelude_marker", c.to_json(), c.id)
        for c in f18:
            k = c.knobs
            built = build_image(c)
            head = built.code[:built.chain_base - CODE_BASE]
            bare = prelude(c.regs, c.wtc, c.rfm, c.prc)
            self.assertEqual(c.marker_kind, "none", c.id)
            roles = [i.role for i in c.instrs if i.role != "pad"]
            forms = [i.form for i in c.instrs if i.role == "x"]
            self.assertEqual(roles[0], "ls", c.id)
            self.assertEqual(roles[-2:], ["ls", "end"], c.id)
            if k["series"] in ("a", "ac"):
                tail = PRELUDE_MARKERS[k["pre_marker"]][1]
                self.assertEqual(c.prelude_marker, k["pre_marker"], c.id)
                self.assertEqual(head, bare + tail, c.id)
                self.assertEqual(bare[-3:], bytes([0xB8, 0x34, 0x12]), c.id)   # MOV AW,1234h
                self.assertEqual(c.rfm, k["rfm"], c.id)
                self.assertEqual(Chain.from_json(c.to_json()), c)
                if k["series"] == "a":
                    self.assertEqual(forms, k["x"], c.id)
                    self.assertEqual(refresh_any(c), c.rfm != 0xEC, c.id)
                    self.assertFalse(rfm_writes(c), c.id)
                else:
                    self.assertEqual(forms, ["rfm_fc"], c.id)
                    self.assertEqual(c.rfm, 0xEC, c.id)
                # the marker's cycle is found in a trace and SP starts 2 lower
                sp = c.regs["SP"] - (2 if c.prelude_marker == "push" else 0)
                rows = [{"address": 0x0EFE, "flags": 0}, {"address": 0x0EFE, "flags": 1},
                        {"address": 0x0020, "flags": 2}, {"address": 0x0EFE, "flags": 0}]
                self.assertEqual(prelude_marker_row(c, rows),
                                 3 if c.prelude_marker == "push" else 2, c.id)
                self.assertEqual(sp, 0x0EFE if c.prelude_marker == "push" else 0x0F00)
                self.assertEqual(expected_accesses(c)[len(c.instrs) - 1][0].addr, 0xFF00)
            else:
                self.assertIsNone(c.prelude_marker, c.id)
                self.assertEqual(head, bare, c.id)
                self.assertEqual(c.rfm, 0xEC, c.id)
                rfm = f"rfm_{k['rfmon']:02x}"
                self.assertEqual(k["rfmon"], 0xFC if k["series"] == "b" else 0xFD, c.id)
                self.assertEqual(forms, [rfm] + F18_B_STEPS[k["step"]] + ["nop"] * k["n"]
                                 + k["x"], c.id)
            first = next(i for i in c.instrs if i.role not in ("pad", "ls"))
            self.assertEqual((built.chain_base + first.offset) & 1, c.parity == "odd", c.id)

    def test_f21_placement(self):
        from validation.v35s.chains.forms import F21_FORM, MODE
        f21 = [c for c in self.chains if c.family == "F21"]
        self.assertEqual(len(f21), 596 * 6)
        for c in f21:
            kn = c.knobs
            self.assertTrue(c.id.startswith(f"F21-{kn['marker']}-{kn['lead']}-{kn['cons']}-"
                                            f"{kn['mode']}"), c.id)
            body = [i for i in c.instrs if i.role == "x"]
            x = F21_FORM[(kn["cons"], kn["mode"])]
            self.assertEqual([i.form for i in body][kn["n"]:], [x] * kn["k"], c.id)
            self.assertEqual(FORMS[x].mode, kn["mode"], c.id)
            self.assertEqual(len(MODE[kn["mode"]].disp), kn["disp"], c.id)
            markers = [i for i in c.instrs if i.role == "marker"]
            self.assertEqual(len(markers), 0 if kn["marker"] == "none" else 2, c.id)
            self.assertEqual(c.regs["BW"], 0x0800)
            ea = FORMS[x].ea
            self.assertTrue(0x0100 <= ea < 0x0E00, c.id)     # data, off the stack
            if FORMS[x].writes:
                self.assertTrue(0x0800 <= ea < 0x0E00, c.id)
        counts = {}
        for c in f21:
            counts[c.knobs["marker"]] = counts.get(c.knobs["marker"], 0) + 1
        self.assertEqual(counts, {"push": (5 * 39 + 25) * 6, "out": (5 * 39 + 25) * 6,
                                  "none": 4 * 39 * 6})

    def test_f22_placement(self):
        from validation.v35s.chains.families import F22_LEADS
        from validation.v35s.chains.forms import F22_FORM, F22_FORMS, MODE, modrm
        f22 = [c for c in self.chains if c.family == "F22"]
        self.assertEqual(len(f22), 3 * 5 * 11 * 2 * 2 * 2)
        code = {"add_d16": "818700023412", "add_d8": "8147103412", "add_bw": "81073412",
                "add_dir": "8106000c3412", "add8_d16": "8387000205",
                "cmp_d16": "81bf00023412", "test_d16": "f78700023412",
                "sti_d16": "c78700023412", "sti_d8": "c747103412", "sti_bw": "c7073412",
                "sti_dir": "c706000c3412"}
        self.assertEqual(set(F22_FORM), set(code))
        for label, x in F22_FORM.items():
            self.assertEqual(FORMS[x].code.hex(), code[label], label)
            cls, opcode, reg, mode, tail, counts = F22_FORMS[label]
            self.assertEqual(FORMS[x].code, bytes(opcode) + modrm(MODE[mode], reg) + tail)
            self.assertEqual(FORMS[x].mode, mode, label)
            self.assertEqual((FORMS[x].reads, FORMS[x].writes),
                             (counts.get("reads", 0), counts.get("writes", 0)), label)
        for c in f22:
            kn = c.knobs
            self.assertEqual(c.id, f"F22-{kn['marker']}-{kn['lead']}-{kn['form']}"
                             + (f"-k{kn['k']}" if kn["k"] > 1 else "")
                             + f"-p{'E' if c.parity == 'even' else 'O'}-w{c.waits}")
            self.assertIn(c.waits, (0, 1), c.id)
            self.assertEqual(c.rfm, 0xEC, c.id)
            self.assertEqual(c.marker_kind, kn["marker"], c.id)
            x = F22_FORM[kn["form"]]
            self.assertEqual(kn["x"], x, c.id)
            body = [i for i in c.instrs if i.role == "x"]
            self.assertEqual([i.form for i in body], F22_LEADS[kn["lead"]] + [x] * kn["k"],
                             c.id)
            roles = [i.role for i in c.instrs if i.role != "pad"]
            mid = ["x"] * (kn["n"] + kn["k"])
            self.assertEqual(roles, ["ls"] + (mid if kn["marker"] == "none" else
                                              ["marker"] + mid + ["marker"]) + ["ls", "end"],
                             c.id)
            built = build_image(c)              # the catalog bytes at the computed offsets
            for i in c.instrs:
                start = built.chain_base + i.offset - CODE_BASE
                self.assertEqual(built.code[start:start + len(i.code)], i.code, c.id)
            first = next(i for i in c.instrs if i.role not in ("pad", "ls"))
            self.assertEqual((built.chain_base + first.offset) & 1, c.parity == "odd", c.id)
            self.assertEqual(c.regs["BW"], 0x0800)
            ea = FORMS[x].ea
            self.assertIn(ea, (0x0800, 0x0810, 0x0A00, 0x0C00), c.id)   # data, off the stack
        counts = {}
        for c in f22:
            key = (c.knobs["marker"], c.waits)
            counts[key] = counts.get(key, 0) + 1
        self.assertEqual(counts, {(m, w): 5 * 11 * 2 * 2 for m in ("push", "out", "none")
                                  for w in (0, 1)})
        self.assertEqual(len({c.id for c in f22}), len(f22))

    def test_f16_division_trap_free(self):
        """F16's signed DIV [BW] with DW = 0100h and DIVU IX with IX = 9090h: every quotient
        fits (no divide trap), X X and INC [BW] X included; DIVU DW cannot (always traps)."""
        from validation.v35s.chains.forms import F16_DIV_DW, F16_DIVU_IX

        def sdiv(dw, aw, d):
            n = (dw << 16) | aw
            n -= (1 << 32) if n >> 31 else 0
            d -= (1 << 16) if d >> 15 else 0
            q = abs(n) // abs(d) * (1 if (n < 0) == (d < 0) else -1)
            self.assertTrue(-32768 <= q <= 32767)
            return (n - q * d) & 0xFFFF, q & 0xFFFF

        for d in (0x9090, 0x9091):          # the fill, and after INC [BW]
            sdiv(*sdiv(F16_DIV_DW, 0, d), d)
        self.assertLess((0x5678 << 16) // F16_DIVU_IX, 0x10000)
        self.assertGreaterEqual((0x5678 << 16) // 0x5678, 0x10000)

    def test_f0w_wtc(self):
        f0w = [c for c in self.chains if c.family == "F0w"]
        self.assertEqual(sorted({c.wtc for c in f0w}),
                         sorted([2 << (2 * i) for i in range(8)] + [0, 0xAAAA]))
        self.assertTrue(all(c.waits == -1 for c in f0w))

    def test_misplaced_bytes_raise(self):
        chain = Chain.from_json(self.chains[0].to_json())
        chain.instrs[1].offset += 1
        with self.assertRaises(RuntimeError):
            build_image(chain)
        chain = Chain.from_json(self.chains[0].to_json())
        chain.parity = "odd" if chain.parity == "even" else "even"
        with self.assertRaises(RuntimeError):
            build_image(chain)

    def test_json_round_trip(self):
        for chain in self.chains[::37]:
            data = json.loads(json.dumps(chain.to_json()))
            again = Chain.from_json(data)
            self.assertEqual(again, chain)
            self.assertIsInstance(again.instrs[0], Instr)
            self.assertEqual(build_image(again).image_sha256, build_image(chain).image_sha256)


if __name__ == "__main__":
    unittest.main()
