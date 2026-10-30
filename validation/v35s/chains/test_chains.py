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
    # F23 (WP49): CMP AW,AW, the short and near branches, DBNZ, MOV CW,imm16, CALL, RET
    "cmp_aw_aw": 2, **{f"be_n{n}": 2 for n in range(8)}, "bne_n0": 2, "bne_n2": 2,
    **{f"br_n{n}": 2 for n in range(8)}, **{f"br_near_n{n}": 3 for n in range(4)},
    "dbnz_n0": 2, "dbnz_n2": 2, "mov_cw_imm1": 3, "mov_cw_imm2": 3, "call_n0": 3,
    "call_n2": 3, "ret": 1,
    # F25 (WP49): LDEA AW,r/m in the 24 modes, XLAT, the stack-frame and segment forms
    **{f"ldea_{m.name}": 2 + len(m.disp) for m in MODES},
    "xlat": 1, "push_imm16": 3, "push_imm8": 2, "push_r": 1, "pop_r": 1, "prepare_00": 4,
    "dispose": 1, "push_ds1": 1, "pop_ds1": 1, "push_ds0": 1, "pop_ds0": 1, "push_ps": 1,
    "mov_ds1_aw": 2, "mov_aw_ds1": 2, "mov_ds1_m": 2, "mov_m_ds0": 2,
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
              "F22": (1320, 1320), "F23": (360, 360), "F25": (588, 588)}

# (WP56) F26 / F27: the new forms' lengths and the two families' run counts.
LENGTHS.update({"test_m_aw_bw_d16": 4, "shl_imm31": 3, "shl_imm32": 3, "shl_imm33": 3,
                "shl_imm255": 3, "shl_cl32": 4, "shl_cl255": 4})
RUN_RANGES.update({"F26": (906, 906), "F27": (1072, 1072)})
# (WP59) F28 / F29: the [BW+200h] group forms and the two families' run counts.
LENGTHS.update({f"{n}_m{'1' if n == 'shl' else ''}_bw_d16": 4
                for n in ("inc", "not", "shl", "neg", "dec")})
RUN_RANGES.update({"F28": (1088, 1088), "F29": (456, 456)})
# (WP66) F24: the string forms (one byte, two with a REP prefix), MOV CW,n, the pattern store
LENGTHS.update({f"{p}{op}_{w}": 1 + bool(p) for op in ("movbk", "stm", "ldm", "inm", "outm")
                for p in ("", "rep_") for w in "bw"})
LENGTHS.update({f"{p}{op}_{w}": 1 + bool(p) for op in ("cmpbk", "cmpm")
                for p in ("", "repe_", "repne_") for w in "bw"})
LENGTHS.update({f"mov_cw_imm{n}": 3 for n in (0, 3, 4, 8, 16)})
LENGTHS.update({"st_imm0_dir_c42": 6})
RUN_RANGES.update({"F24": (912, 912)})
# (WP73) F30: the segment register forms by sreg field, PUSH SS / POP SS, the family's run count
LENGTHS.update({n: 2 for n in ("mov_ss_aw", "mov_ds0_aw", "mov_ds1_ix", "mov_ss_ix", "mov_ds0_ix",
                               "mov_aw_ps", "mov_aw_ss", "mov_aw_ds0", "mov_m_ds1", "mov_m_ps",
                               "mov_m_ss")})
LENGTHS.update({"push_ss": 1, "pop_ss": 1})
RUN_RANGES.update({"F30": (1476, 1476)})
RUN_RANGES.update({"F31": (234, 234)})        # (WP73) F30's two controls
# (WP74) F32 / F33: the 0F page and the register miscellany (generator-only forms)
LENGTHS.update({f"{op}_{o}{w}_{i}": 3 + (i == "imm")
                for op in ("test1", "clr1", "set1", "not1") for o in "rm" for w in "bw"
                for i in ("cl", "imm")})
LENGTHS.update({"set1_mw_cl_bw_d8": 4, "set1_mw_cl_bw_d16": 5, "set1_mw_cl_bw_ix": 3,
                "set1_mw_cl_dir": 5, "add4s": 2, "sub4s": 2, "cmp4s": 2, "rol4_dl": 3,
                "ror4_dl": 3, "rol4_m": 3, "ror4_m": 3, "pfx_test1_mw_cl": 4,
                "pfx_set1_mb_imm": 5, "pfx_rol4_m": 4, "pfx_add4s": 3})
LENGTHS.update({f"{op}_{o}_{w}": 3 for op in ("ext", "ins") for o, w in
                (("bl", "dh"), ("dl", "dh"), ("dl", "bh"), ("bh", "bl"))})
LENGTHS.update({f"{op}_{o}_i{i}": 4 for op in ("ext", "ins") for o, i in
                (("bl", 7), ("dl", 7), ("dl", 11))})
LENGTHS.update({f"{op}_{r}": 1 for op in ("inc", "dec")
                for r in ("aw", "cw", "dw", "bw", "sp", "bp", "ix", "iy")})
LENGTHS.update({"inc_al": 2, "dec_al": 2, "inc_dh": 2, "dec_dh": 2, "incb_m": 2, "decb_m": 2,
                "adj4a": 1, "adj4s": 1, "adjba": 1, "adjbs": 1, "cvtbd": 2, "cvtdb": 2,
                "cvtbw": 1, "cvtwl": 1, "mul_cw": 2, "div_cw": 2, "divu_cw": 2,
                "mul_aw_cw_imm16": 4, "mul_aw_m_imm16": 4, "mul_aw_cw_imm8": 3,
                "mul_aw_m_imm8": 3, "clc": 1, "stc": 1, "cmc": 1, "cli": 1, "sti": 1, "cld": 1,
                "std": 1, "mov_dw_imm0": 3, "mov_aw_8080": 3, "repc_cmpm_w": 2,
                "repnc_cmpm_w": 2, "repc_cmpbk_w": 2, "repnc_cmpbk_w": 2,
                "st_imm0_dir_a42": 6})
RUN_RANGES.update({"F32": (858, 858), "F33": (1050, 1050)})
# (WP80) F34: the forty-second fit's miss shapes; CMP AW,DW its one new byte string
LENGTHS.update({"cmp_aw_dw": 2})
RUN_RANGES.update({"F34": (1596, 1596)})


def _synthetic_run(chain):
    """(WP49) a run record whose trace fetches every chain word (an idle gap after the first
    LS's fetch), then makes the chain's expected data / stack / I/O cycles in order: enough
    for normalize's hard checks, not a timing claim."""
    from validation.v35s.chains.normalize import (FLAG_IO, FLAG_NUBE, FLAG_READ,
                                                  expected_accesses)
    built = build_image(chain)
    base = built.chain_base
    ls = next(i for i in chain.instrs if i.role == "ls")
    ls_last = base + ls.offset + len(ls.code) - 1
    rows, t = [], 0

    def row(addr, flags):
        nonlocal t
        rows.append({"address": addr, "flags": flags, "start": t, "end": t + 16, "data": 0})
        t += 24

    for addr in range(base & ~1, base + len(chain.code), 2):
        row(addr, FLAG_READ)
        if addr <= ls_last < addr + 2:
            t += 20 * 8
    t += 20 * 8
    for k, accs in sorted(expected_accesses(chain).items()):
        for a in accs:
            flags = (FLAG_READ if a.kind.endswith("read") else 0) | (
                FLAG_IO if a.kind.startswith("io") else 0) | (
                FLAG_NUBE if a.width == "lo" and not a.addr & 1 else 0)
            row(a.addr, flags)
    return {"chain": chain.to_json(), "chain_base": base, "socket_trace": rows,
            "complete": True}


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
            # (WP73) F30's br probe also runs under the MOV-direct marker (store)
            self.assertIn(chain.marker_kind,
                          ("push", "out", "store") if chain.family == "F30" else ("push", "out"),
                          chain.id)
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
            # F15, F16, F18 reuse F14's forms, and (WP56) F26, F27, (WP59) F28, F29, (WP73) F30,
            # (WP74) F33 (DIVU [BW]), (WP80) F34 (SHL AW,8)
            if c.family not in ("F14", "F15", "F16", "F18", "F26", "F27", "F28", "F29", "F30",
                                "F33", "F34"):
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
            # F18 B reuses DIVU IX, (WP56) F26 DEC [BW], (WP74) F32 MOV CL,n and F33 MUL / DIV /
            # DEC [BW]
            if c.family not in ("F16", "F18", "F26", "F32", "F33"):
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

    def test_f23_f25_encodings(self):
        # one form of each group, byte-exact
        for name, code in (("cmp_aw_aw", "3bc0"), ("be_n3", "7403"), ("bne_n2", "7502"),
                           ("br_n5", "eb05"), ("br_near_n2", "e90200"), ("dbnz_n2", "e202"),
                           ("mov_cw_imm2", "b90200"), ("call_n2", "e80200"), ("ret", "c3"),
                           ("ldea_bw_ix_d8", "8d4010"), ("ldea_dir", "8d06000c"),
                           ("ldea_bp_iy_d16", "8d830002"), ("xlat", "d7"),
                           ("push_imm16", "683412"), ("push_imm8", "6a12"),
                           ("prepare_00", "c8000000"), ("dispose", "c9"), ("push_r", "60"),
                           ("pop_r", "61"), ("push_ds1", "06"), ("pop_ds1", "07"),
                           ("push_ds0", "1e"), ("pop_ds0", "1f"), ("push_ps", "0e"),
                           ("mov_ds1_aw", "8ec0"), ("mov_aw_ds1", "8cc0"),
                           ("mov_ds1_m", "8e07"), ("mov_m_ds0", "8c1f")):
            self.assertEqual(FORMS[name].code.hex(), code, name)
        # (WP55) classes by encoding format: the 1-byte and 2-byte displacement, the count
        self.assertEqual({FORMS[n].cls for n in FORMS if n.startswith(("be_", "br_n", "bne_"))
                          and not n.startswith("br_near_")}, {"branch_short"})
        self.assertEqual({FORMS[n].cls for n in FORMS if n.startswith("br_near_")},
                         {"branch_near"})
        self.assertEqual({FORMS[n].cls for n in FORMS if n.startswith("dbnz_")}, {"dbnz"})
        self.assertEqual((FORMS["call_n0"].cls, FORMS["call_n2"].cls, FORMS["ret"].cls),
                         ("call", "call", "ret"))
        self.assertEqual({FORMS[n].cls for n in FORMS if n.startswith("ldea_")}, {"lea"})
        for n in FORMS:
            if n.startswith("ldea_"):
                self.assertEqual((FORMS[n].reads, FORMS[n].writes), (0, 0), n)

    def test_f23_branch_targets_and_skipped(self):
        # Walk each F23 chain's X bytes as the CPU does (Z = 1 after CMP AW,AW, CW from
        # the MOV CW,imm16 in the frame): every target is an instruction boundary, the
        # executed X indices are knob exec in order and the never-executed ones are the
        # skipped NOPs.
        from validation.v35s.chains.families import UNMODELLED
        f23 = [c for c in self.chains if c.family == "F23"]
        self.assertEqual(len(f23), 360)
        self.assertNotIn("F23", UNMODELLED)       # (WP55) modelled
        ids = {c.id for c in f23}
        for cid in ("F23-push-be-n3-pE-w1", "F23-out-callret-pO-w0", "F23-push-empty-pE-w0",
                    "F23-out-brnear-n2-pO-w2", "F23-push-dbnz-c2-n2-pE-w0"):
            self.assertIn(cid, ids)
        targets = set()
        for c in f23:
            x = [i for i in c.instrs if i.role == "x"]
            self.assertEqual([i.form for i in x], c.knobs["x"], c.id)
            at = {i.offset: i for i in x}
            end = c.instrs[[k for k, i in enumerate(c.instrs) if i.role == "marker"][1]].offset
            pc = x[0].offset if x else end
            cw, stack, done = None, [], []
            while pc != end:
                i = at[pc]
                done.append(i.index)
                nxt = pc + len(i.code)
                code = i.code
                if code[0] in (0x74, 0x75, 0xEB, 0xE2):
                    if code[0] == 0xE2:
                        cw -= 1
                    taken = {0x74: True, 0x75: False, 0xEB: True, 0xE2: cw != 0}[code[0]]
                    pc = nxt + code[1] if taken else nxt
                    if taken:
                        targets.add((c.knobs["group"], (c.instrs[0].role == "pad")
                                     ^ (pc & 1)))
                elif code[0] in (0xE9, 0xE8):
                    if code[0] == 0xE8:
                        stack.append(nxt)
                    pc = nxt + int.from_bytes(code[1:3], "little")
                elif code[0] == 0xC3:
                    pc = stack.pop()
                else:
                    if code[0] == 0xB9:
                        cw = int.from_bytes(code[1:3], "little")
                    pc = nxt
                self.assertTrue(pc == end or pc in at, c.id)
                self.assertLess(len(done), 16, c.id)
            self.assertEqual(done, c.knobs["exec"], c.id)
            # CALL +0 alone leaves its return address on the stack
            self.assertEqual(len(stack), int(c.knobs["group"] == "call"), c.id)
            never = [i for i in x if i.index not in done]
            self.assertEqual(len(never), c.knobs["skipped"], c.id)
            self.assertTrue(all(i.form == "nop" for i in never), c.id)
        # both target alignments for the taken short-branch series
        self.assertEqual({p for g, p in targets if g == "be"}, {0, 1})
        self.assertEqual({p for g, p in targets if g == "br"}, {0, 1})

    def test_f25_variants(self):
        from validation.v35s.chains.families import UNMODELLED
        f25 = [c for c in self.chains if c.family == "F25"]
        self.assertEqual(len(f25), 588)
        self.assertNotIn("F25", UNMODELLED)       # (WP52) modelled
        ids = {c.id for c in f25}
        for cid in ("F25-push-ldea-bw_ix_d8-pE-w0", "F25-out-pushr_popr-pO-w2",
                    "F25-out-ldea-dir-k2-pE-w1", "F25-push-prepare_dispose-pO-w0"):
            self.assertIn(cid, ids)
        self.assertEqual({c.knobs["mode"] for c in f25 if c.knobs["group"] == "lea"},
                         {m.name for m in MODES})
        for c in f25:
            forms = [i.form for i in c.instrs if i.role == "x"]
            self.assertEqual(forms, c.knobs["x"], c.id)
            # POP R only after PUSH R, DISPOSE only after PREPARE, never a load of DS0, SS
            # or PS from memory, and POP DS0 / POP DS1 only after their own PUSH
            for later, earlier in (("pop_r", "push_r"), ("dispose", "prepare_00"),
                                   ("pop_ds0", "push_ds0"), ("pop_ds1", "push_ds1")):
                if later in forms:
                    self.assertEqual(forms[forms.index(later) - 1], earlier, c.id)
            self.assertEqual(c.regs["BW"], 0x0800)

    def test_f23_f25_stack_accesses_normalize(self):
        # (WP49) the normaliser's expected accesses follow CALL / RET and PUSH R / POP R,
        # and a synthetic trace of a taken-branch chain and a CALL/RET chain normalises
        from validation.v35s.chains.normalize import expected_accesses, normalize
        by_id = {c.id: c for c in self.chains}
        acc = lambda cid: [(a.kind, a.addr) for k in sorted(expected_accesses(by_id[cid]))
                           for a in expected_accesses(by_id[cid])[k]]
        self.assertEqual(acc("F23-push-callret-pE-w0"),
                         [("stack_write", 0x0EFE), ("stack_write", 0x0EFC),
                          ("stack_read", 0x0EFC), ("stack_write", 0x0EFC),
                          ("io_write", 0xFF00)])
        pushr = acc("F25-out-pushr_popr-pE-w0")
        self.assertEqual(pushr[1:9], [("stack_write", 0x0F00 - 2 * (j + 1)) for j in range(8)])
        self.assertEqual(pushr[9:17], [("stack_read", 0x0EF0 + 2 * j) for j in range(8)])
        self.assertEqual(acc("F25-push-ldea-bw_ix_d8-pE-w0"),
                         [("stack_write", 0x0EFE), ("stack_write", 0x0EFC),
                          ("io_write", 0xFF00)])
        for cid in ("F23-push-be-n3-pO-w0", "F23-push-callret-pE-w0",
                    "F25-out-pushr_popr-pE-w0", "F23-out-brnear-n2-pE-w0"):
            n = normalize(_synthetic_run(by_id[cid]))
            self.assertEqual(n.checks, [], cid)
            self.assertEqual(sorted(n.t_markers), [0, 1], cid)
            self.assertIsNotNone(n.t_end, cid)

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


class F26F27Tests(unittest.TestCase):
    """(WP56) the probe families: catalog bytes, counts, placement, parity and the knobs."""

    @classmethod
    def setUpClass(cls):
        cls.f26 = generate(["F26"])
        cls.f27 = generate(["F27"])

    # every form the probes use, with the bytes the brief names
    BYTES = {"st_imm_bw_ix_d16": "c780000234 12", "st_imm_bw_d16": "c787000234 12",
             "st_imm_bw_ix": "c7003412", "st_imm_bw_ix_d8": "c740103412",
             "inc_m": "ff07", "not_m": "f717", "shl_m1": "d127", "neg_m": "f71f",
             "dec_m": "ff0f", "test_dir_aw": "8506000c", "test_m_aw": "8507",
             "test_m_aw_bw_d16": "85870002", "ld_bw_d8": "8b4710", "ld_bw_d16": "8b870002",
             "ld_bw_ix_d8": "8b4010", "ld_bw_ix_d16": "8b800002", "ld_dir": "8b06000c",
             "ld_bw": "8b07", "nop": "90", "xch_aw_dw": "92", "mov_aw_dw": "8bc2",
             "add_aw_dw": "03c2", "mov_cl_imm": "b104", "out_imm_al": "e640",
             "out_imm_aw": "e740", "in_al_imm": "e440", "out_dw_al": "ef", "in_al_dw": "ec",
             "shl_imm31": "c1e01f", "shl_imm32": "c1e020", "shl_imm33": "c1e021",
             "shl_imm255": "c1e0ff", "shl_cl32": "b120d3e0", "shl_cl255": "b1ffd3e0",
             "shl_cl4": "b104d3e0", "shl_cl8": "b108d3e0", "shl_cl16": "b110d3e0",
             "mulu_dw": "f7e2", "shl_imm8": "c1e008", "mov_aw_imm": "b83412",
             "mov_dw_imm": "ba4000", "add_dw_imm": "81c23412", "mov_ds1_aw": "8ec0"}

    def test_catalog_bytes(self):
        for name, code in self.BYTES.items():
            self.assertEqual(FORMS[name].code, bytes.fromhex(code.replace(" ", "")), name)
        used = {i.form for c in self.f26 + self.f27 for i in c.instrs if i.role == "x"}
        self.assertEqual(used, set(self.BYTES))
        self.assertEqual((FORMS["test_m_aw_bw_d16"].cls, FORMS["test_m_aw_bw_d16"].reads,
                          FORMS["test_m_aw_bw_d16"].writes, FORMS["test_m_aw_bw_d16"].ea),
                         ("load_alu", 1, 0, 0x0A00))
        for n in (31, 32, 33, 255):
            self.assertEqual(FORMS[f"shl_imm{n}"].cls, "shift_imm")
        for n in (32, 255):
            self.assertEqual(FORMS[f"shl_cl{n}"].cls, "shift_cl")

    def test_f26_and_f27_are_modelled(self):
        from validation.v35s.chains.families import UNMODELLED
        self.assertNotIn("F26", UNMODELLED)
        self.assertNotIn("F27", UNMODELLED)       # (WP58) modelled: no F27 run over-fills

    def test_counts(self):
        from collections import Counter
        self.assertEqual(len(self.f26), 151 * 6)
        self.assertEqual(len(self.f27), 134 * 6 + 134 * 2)
        variants = lambda chains: Counter(
            (c.knobs["series"], c.marker_kind) for c in chains
            if c.parity == "even" and c.waits == 0)
        self.assertEqual(variants(self.f26), {
            ("empty", "push"): 1, ("empty", "out"): 1,
            ("pi", "push"): 16 + 5, ("pi", "out"): 16 + 10,
            ("fib", "push"): 8, ("fib", "out"): 8,
            ("gih", "push"): 7, ("gih", "out"): 21, ("dio", "out"): 24,
            ("lks", "push"): 11, ("lks", "out"): 11, ("cnt", "push"): 6, ("cnt", "out"): 6})
        for rfm in (0xFC, 0xEC):
            got = variants([c for c in self.f27 if c.rfm == rfm])
            for kind in ("push", "out"):
                self.assertEqual({s: got[(s, kind)] for s in
                                  ("empty", "room", "unit", "port", "beat")},
                                 {"empty": 1, "room": 15, "unit": 15, "port": 24, "beat": 12})
        # FCh at every wait, the ECh twins at 0 waits only
        self.assertEqual({c.waits for c in self.f27 if c.rfm == 0xFC}, {0, 1, 2})
        self.assertEqual({c.waits for c in self.f27 if c.rfm == 0xEC}, {0})
        self.assertEqual({c.waits for c in self.f26}, {0, 1, 2})
        ids = {c.id for c in self.f27}
        for c in self.f27:
            if c.rfm == 0xFC and c.waits == 0:
                self.assertIn(c.id.replace("-fc-", "-ec-", 1), ids)

    def test_placement(self):
        from validation.v35s.chains.types import refresh_any, rfm_writes
        for c in self.f26 + self.f27:
            k = c.knobs
            self.assertRegex(c.id, (r"^F26-(push|out)-" if c.family == "F26"
                                    else r"^F27-(push|out)-(fc|ec)-"), c.id)
            self.assertEqual(k["marker"], c.marker_kind, c.id)
            self.assertEqual(c.rfm, k["rfm"], c.id)
            self.assertEqual(c.rfm, 0xEC if c.family == "F26" else int(c.id.split("-")[2], 16))
            self.assertEqual(refresh_any(c), c.rfm == 0xFC, c.id)
            self.assertFalse(rfm_writes(c), c.id)
            self.assertIsNone(c.prelude_marker, c.id)
            roles = [i.role for i in c.instrs if i.role != "pad"]
            x = [i for i in c.instrs if i.role == "x"]
            self.assertEqual(roles, ["ls", "marker"] + ["x"] * len(x)
                             + ["marker", "ls", "end"], c.id)
            self.assertEqual([i.form for i in x], k["x"], c.id)
            self.assertEqual([i.index for i in x], list(range(len(x))), c.id)
            for m in (i for i in c.instrs if i.role == "marker"):
                self.assertEqual(m.code, blocks.marker(c.marker_kind, m.marker_id), c.id)
            # the catalog bytes at the computed offsets, M0 at the cell's parity
            built = build_image(c)
            at = built.chain_base - CODE_BASE
            for i in c.instrs:
                self.assertEqual(built.code[at + i.offset:at + i.offset + len(i.code)],
                                 FORMS[i.form].code if i.role == "x" else i.code, c.id)
            m0 = next(i for i in c.instrs if i.role == "marker")
            self.assertEqual((built.chain_base + m0.offset) & 1, c.parity == "odd", c.id)
            # the knobs: n NOPs before the probed form (after the first OUT in pi oo), k copies
            names = k["x"]
            if k["series"] == "empty":
                self.assertEqual((names, k["form"], k["k"]), ([], None, 0), c.id)
                continue
            lead = names[1:] if k.get("shape") == "oo" else names
            self.assertEqual(lead[:k["n"]], ["nop"] * k["n"], c.id)
            if k["series"] == "pi":
                self.assertEqual(names[-1], "out_imm_al", c.id)
                self.assertEqual(names.count("out_imm_al"), 2 if k["shape"] == "oo" else 1)
            elif k["series"] == "beat":
                self.assertEqual(len(names), k["n"] + 2, c.id)
                self.assertEqual(names[-1], k["form"], c.id)
            else:
                self.assertEqual(names[k["n"]:], [k["form"]] * k["k"], c.id)
            dw = any(n in ("out_dw_al", "in_al_dw") for n in names)
            self.assertEqual(c.regs["DW"], 0x0040 if dw else 0x5678, c.id)
            self.assertEqual({r: c.regs[r] for r in ("AW", "BW", "CW", "SP", "BP", "IX", "IY")},
                             {"AW": 0x1234, "BW": 0x0800, "CW": 0, "SP": 0x0F00, "BP": 0x0A00,
                              "IX": 0x0100, "IY": 0x0180}, c.id)

    def test_knob_coverage(self):
        cells = lambda chains, series: {
            (c.marker_kind, c.knobs.get("shape"), c.knobs["form"], c.knobs["n"], c.knobs["k"],
             tuple(c.knobs["x"])) for c in chains if c.knobs["series"] == series}
        f26 = {s: cells(self.f26, s) for s in ("pi", "fib", "gih", "dio", "lks", "cnt")}
        # port_issue: the oo ladder n = 0..3 behind none/XCH/MOV AW,DW, 0..1 behind ADD/MOV CL
        out = ("out_imm_al",)
        oo = {(m, n, x) for m, s, f, n, k, x in f26["pi"] if s == "oo"}
        self.assertEqual(oo, {(m, n, out + ("nop",) * n + pre + out) for m in ("push", "out")
                              for pre, ns in (((), 4), (("xch_aw_dw",), 4),
                                              (("mov_aw_dw",), 4), (("add_aw_dw",), 2),
                                              (("mov_cl_imm",), 2)) for n in range(ns)})
        o = {(m, n, x) for m, s, f, n, k, x in f26["pi"] if s == "o"}
        self.assertEqual(o, {(m, n, ("nop",) * n + (pre,) + out)
                             for m, ns in (("out", (0, 1)), ("push", (0,))) for n in ns
                             for pre in ("nop", "xch_aw_dw", "mov_aw_dw", "add_aw_dw",
                                         "mov_cl_imm")})
        # free_idle_b2b: k = 1, 2, 3 and the n = 1, 2 ladder at k = 2 for base+index+d16
        fib = {(m, f, n, k) for m, s, f, n, k, x in f26["fib"]}
        for m in ("push", "out"):
            for k in (1, 2, 3):
                self.assertIn((m, "st_imm_bw_ix_d16", 0, k), fib)
            for n in (1, 2):
                self.assertIn((m, "st_imm_bw_ix_d16", n, 2), fib)
            for f in ("st_imm_bw_d16", "st_imm_bw_ix", "st_imm_bw_ix_d8"):
                self.assertIn((m, f, 0, 2), fib)
        # grp_io_hold: OUT n = 0..2, the PUSH control n = 0
        gih = {(m, f, n) for m, s, f, n, k, x in f26["gih"]}
        forms = ("inc_m", "not_m", "shl_m1", "neg_m", "dec_m", "test_dir_aw", "test_m_aw")
        self.assertEqual(gih, {("out", f, n) for f in forms for n in range(3)}
                         | {("push", f, 0) for f in forms})
        # disp_io: OUT only, n = 0..3, six load modes
        dio = {(m, f, n) for m, s, f, n, k, x in f26["dio"]}
        self.assertEqual(dio, {("out", f, n) for n in range(4) for f in
                               ("ld_bw_d8", "ld_bw_d16", "ld_bw_ix_d8", "ld_bw_ix_d16",
                                "ld_dir", "ld_bw")})
        # lookup_start: TEST [0C00h],AW k = 1, 2 at n = 0..2 and k = 3; the controls k = 1, 2
        lks = {(m, f, n, k) for m, s, f, n, k, x in f26["lks"]}
        expect = ({(m, "test_dir_aw", n, k) for m in ("push", "out") for k in (1, 2)
                   for n in range(3)} | {(m, "test_dir_aw", 0, 3) for m in ("push", "out")}
                  | {(m, f, 0, k) for m in ("push", "out") for k in (1, 2)
                     for f in ("test_m_aw", "test_m_aw_bw_d16")})
        self.assertEqual(lks, expect)
        # the count mask: four C1 counts and two CL counts, both markers
        cnt = {(m, f) for m, s, f, n, k, x in f26["cnt"]}
        self.assertEqual(cnt, {(m, f) for m in ("push", "out") for f in
                               ("shl_imm31", "shl_imm32", "shl_imm33", "shl_imm255",
                                "shl_cl32", "shl_cl255")})
        self.assertEqual({c.knobs["probe"] for c in self.f26},
                         {"empty", "port_issue", "free_idle_b2b", "grp_io_hold", "disp_io",
                          "lookup_start", "count_mask"})
        # F27, the same cells at FCh and ECh
        for rfm in (0xFC, 0xEC):
            chains = [c for c in self.f27 if c.rfm == rfm]
            room = {(m, f, k) for m, s, f, n, k, x in cells(chains, "room")}
            self.assertEqual(room, {(m, f, k) for m in ("push", "out") for f, ks in
                                    (("mov_aw_imm", 4), ("mov_dw_imm", 4), ("mov_cl_imm", 4),
                                     ("add_dw_imm", 3)) for k in range(1, ks + 1)})
            unit = {(m, f, n) for m, s, f, n, k, x in cells(chains, "unit")}
            self.assertEqual(unit, {(m, f, n) for m in ("push", "out") for n in range(3) for f in
                                    ("shl_cl4", "shl_cl8", "shl_cl16", "mulu_dw", "shl_imm8")})
            port = {(m, f, n) for m, s, f, n, k, x in cells(chains, "port")}
            self.assertEqual(port, {(m, f, n) for m in ("push", "out") for n in range(6)
                                    for f in ("out_imm_al", "out_imm_aw", "in_al_imm")}
                             | {(m, f, n) for m in ("push", "out") for n in (0, 2, 4)
                                for f in ("out_dw_al", "in_al_dw")})
            beat = {(m, x[-2:], n) for m, s, f, n, k, x in cells(chains, "beat")}
            self.assertEqual(beat, {(m, p, n) for m in ("push", "out") for n in range(6) for p in
                                    (("mov_ds1_aw", "mov_aw_imm"), ("mov_aw_dw", "mov_dw_imm"))})

    def test_baselines(self):
        from validation.v35s.chains.derive import BASELINES, index_facts, variant_of
        for family, chains in (("F26", self.f26), ("F27", self.f27)):
            metric, base = BASELINES[family]
            self.assertEqual(metric, "dM")
            facts = []
            for c in chains:
                variant = variant_of(c)
                facts.append({"id": c.id, "marker": c.marker_kind, "knobs": c.knobs,
                              "x_variant": variant[len(c.marker_kind) + 1:],
                              "column": f"p{c.parity[0].upper()}-w{c.waits}"})
            index = index_facts(facts)
            for f in facts:
                b = base(f, index, None)
                if f["knobs"]["series"] == "empty":
                    self.assertIsNone(b, f["id"])
                    continue
                self.assertIsNotNone(b, f["id"])
                self.assertEqual(b["knobs"]["series"], "empty", f["id"])
                self.assertEqual((b["marker"], b["column"], b["knobs"]["rfm"]),
                                 (f["marker"], f["column"], f["knobs"]["rfm"]), f["id"])


class F28F29Tests(unittest.TestCase):
    """(WP59) the probes of the thirty-sixth fit's open states: catalog bytes, counts,
    placement, the fence count, parity, the knobs and the baselines."""

    @classmethod
    def setUpClass(cls):
        cls.f28 = generate(["F28"])
        cls.f29 = generate(["F29"])

    BYTES = {"inc_m_bw_d16": "ff870002", "not_m_bw_d16": "f7970002",
             "shl_m1_bw_d16": "d1a70002", "neg_m_bw_d16": "f79f0002",
             "dec_m_bw_d16": "ff8f0002", "st_bw_d8": "894710", "st_bw_d16": "89870002",
             "st_dir": "8906000c", "st_bw_ix_d16": "89800002", "ld_bw_d8": "8b4710",
             "ld_bw_d16": "8b870002", "ld_dir": "8b06000c", "ld_bw_ix_d16": "8b800002",
             "test_dir_aw": "8506000c", "test_m_aw_bw_d16": "85870002", "out_dw_b": "ee",
             "out_imm_al": "e640", "out_imm_aw": "e740", "mov_aw_imm": "b83412",
             "mov_dw_imm": "ba4000", "add_dw_imm": "81c23412", "nop": "90",
             "shl_cl8": "b108d3e0", "shl_cl16": "b110d3e0", "shl_cl24": "b118d3e0",
             "shl_cl31": "b11fd3e0", "shl_imm8": "c1e008", "mulu_dw": "f7e2"}

    def test_catalog_bytes(self):
        for name, code in self.BYTES.items():
            self.assertEqual(FORMS[name].code, bytes.fromhex(code), name)
        used = {i.form for c in self.f28 + self.f29 for i in c.instrs if i.role == "x"}
        self.assertEqual(used, set(self.BYTES))
        for name in ("inc_m_bw_d16", "not_m_bw_d16", "shl_m1_bw_d16", "neg_m_bw_d16",
                     "dec_m_bw_d16"):
            f = FORMS[name]
            self.assertEqual((f.cls, f.reads, f.writes, f.width, f.mode, f.ea),
                             ("rmw", 1, 1, 2, "bw_d16", 0x0A00), name)

    def test_f28_and_f29_are_modelled(self):
        from validation.v35s.chains.families import UNMODELLED
        self.assertNotIn("F28", UNMODELLED)
        self.assertNotIn("F29", UNMODELLED)

    def test_counts(self):
        from collections import Counter
        self.assertEqual(len(self.f28), 136 * 6 + 136 * 2)
        self.assertEqual(len(self.f29), 76 * 6)
        variants = lambda chains: Counter(
            (c.knobs["series"], c.marker_kind) for c in chains
            if c.parity == "even" and c.waits == 0)
        for rfm in (0xFC, 0xEC):
            self.assertEqual(variants([c for c in self.f28 if c.rfm == rfm]), {
                ("empty", "push"): 1, ("empty", "out"): 1, ("fence", "push"): 7,
                ("fence", "out"): 7, ("tail", "push"): 36, ("tail", "out"): 36,
                ("beat", "out"): 48})
        self.assertEqual(variants(self.f29), {
            ("empty", "push"): 1, ("empty", "out"): 1, ("dio", "out"): 16 + 8,
            ("gih", "out"): 15 + 7, ("pi", "push"): 14, ("pi", "out"): 14})
        self.assertEqual({c.waits for c in self.f28 if c.rfm == 0xFC}, {0, 1, 2})
        self.assertEqual({c.waits for c in self.f28 if c.rfm == 0xEC}, {0})
        self.assertEqual({c.waits for c in self.f29}, {0, 1, 2})
        self.assertEqual({c.rfm for c in self.f29}, {0xEC})
        ids = {c.id for c in self.f28}
        for c in self.f28:
            if c.rfm == 0xFC and c.waits == 0:
                self.assertIn(c.id.replace("-fc-", "-ec-", 1), ids)

    def test_placement(self):
        from validation.v35s.chains.types import refresh_any, rfm_writes
        for c in self.f28 + self.f29:
            k = c.knobs
            self.assertRegex(c.id, r"^F2[89]-(push|out)-(fc|ec)-[a-z]+(-[a-z0-9]+)*-p[EO]-w[012]$"
                             if k["series"] != "empty" else r"^F2[89]-(push|out)-(fc|ec)-empty-",
                             c.id)
            if k["series"] != "empty":
                self.assertRegex(c.id, r"-n\d(-k\d)?-p", c.id)
                self.assertEqual("-k" in c.id, k["series"] == "beat", c.id)
            self.assertEqual(k["marker"], c.marker_kind, c.id)
            self.assertEqual(c.rfm, k["rfm"], c.id)
            self.assertEqual(c.rfm, int(c.id.split("-")[2], 16), c.id)
            self.assertEqual(refresh_any(c), c.rfm == 0xFC, c.id)
            self.assertFalse(rfm_writes(c), c.id)
            self.assertIsNone(c.prelude_marker, c.id)
            roles = [i.role for i in c.instrs if i.role != "pad"]
            x = [i for i in c.instrs if i.role == "x"]
            self.assertEqual(roles, ["ls", "marker"] + ["x"] * len(x)
                             + ["marker", "ls", "end"], c.id)
            self.assertEqual([i.form for i in x], k["x"], c.id)
            self.assertEqual([i.index for i in x], list(range(len(x))), c.id)
            for m in (i for i in c.instrs if i.role == "marker"):
                self.assertEqual(m.code, blocks.marker(c.marker_kind, m.marker_id), c.id)
            # the fence: B1 cl D3 E0, cl = 31 but in the fence cells; the closing LS is LS
            fence, close = [i for i in c.instrs if i.role == "ls"]
            cl = k.get("fence_cl", 31)
            self.assertEqual(fence.code, bytes([0xB1, cl, 0xD3, 0xE0]), c.id)
            self.assertEqual(close.code, blocks.LS, c.id)
            self.assertEqual(k["series"] == "fence", cl != 31, c.id)
            built = build_image(c)
            at = built.chain_base - CODE_BASE
            for i in c.instrs:
                self.assertEqual(built.code[at + i.offset:at + i.offset + len(i.code)],
                                 FORMS[i.form].code if i.role == "x" else i.code, c.id)
            m0 = next(i for i in c.instrs if i.role == "marker")
            self.assertEqual((built.chain_base + m0.offset) & 1, c.parity == "odd", c.id)
            names = k["x"]
            if k["series"] in ("empty", "fence"):
                self.assertEqual((names, k["form"], k["k"]), ([], None, 0), c.id)
                continue
            shape = k.get("shape")
            lead = names[1:] if shape == "oo" else names
            self.assertEqual(lead[:k["n"]], ["nop"] * k["n"], c.id)
            if k["series"] == "tail":
                self.assertEqual(names[k["n"]:], [k["unit"], k["form"]], c.id)
            elif k["series"] == "pi":
                self.assertEqual(names[-1], "out_imm_al", c.id)
                self.assertEqual(names.count("out_imm_al"), 2, c.id)
            elif shape == "dw":
                self.assertEqual((k["n"], names), (0, ["out_dw_b", k["form"]]), c.id)
            else:
                self.assertEqual(names[k["n"]:], [k["form"]] * k["k"], c.id)
            dw = "out_dw_b" in names
            self.assertEqual(c.regs["DW"], 0x0040 if dw else 0x5678, c.id)
            self.assertEqual({r: c.regs[r] for r in ("AW", "BW", "CW", "SP", "BP", "IX", "IY")},
                             {"AW": 0x1234, "BW": 0x0800, "CW": 0, "SP": 0x0F00, "BP": 0x0A00,
                              "IX": 0x0100, "IY": 0x0180}, c.id)

    def test_knob_coverage(self):
        cells = lambda chains, series: {
            (c.marker_kind, c.knobs.get("shape"), c.knobs["form"], c.knobs["n"], c.knobs["k"],
             tuple(c.knobs["x"])) for c in chains if c.knobs["series"] == series}
        for rfm in (0xFC, 0xEC):
            chains = [c for c in self.f28 if c.rfm == rfm]
            fence = {(c.marker_kind, c.knobs["fence_cl"]) for c in chains
                     if c.knobs["series"] == "fence"}
            self.assertEqual(fence, {(m, cl) for m in ("push", "out") for cl in range(24, 31)})
            tail = {(m, x) for m, s, f, n, k, x in cells(chains, "tail")}
            want = {(m, ("nop",) * n + (u, "out_imm_al")) for m in ("push", "out")
                    for u, ns in (("shl_cl8", range(6)), ("shl_cl16", range(6)),
                                  ("shl_cl24", range(6)), ("shl_cl31", range(6)),
                                  ("shl_imm8", (0, 2, 4)), ("mulu_dw", (0, 2, 4)))
                    for n in ns}
            want |= {(m, ("nop",) * n + ("shl_cl31", p)) for m in ("push", "out")
                     for p in ("out_imm_aw", "out_dw_b") for n in (0, 2, 4)}
            self.assertEqual(tail, want)
            beat = {(m, f, n, k) for m, s, f, n, k, x in cells(chains, "beat")}
            self.assertEqual(beat, {("out", f, n, k) for f in
                                    ("mov_aw_imm", "mov_dw_imm", "add_dw_imm")
                                    for n in range(4) for k in range(1, 5)})
        dio = {(s, f, n) for m, s, f, n, k, x in cells(self.f29, "dio")}
        self.assertEqual(dio, {(None, f, n) for n in range(4) for f in
                               ("st_bw_d8", "st_bw_d16", "st_dir", "st_bw_ix_d16")}
                         | {("dw", f, 0) for f in ("st_bw_d8", "st_bw_d16", "st_dir",
                                                    "st_bw_ix_d16", "ld_bw_d8", "ld_bw_d16",
                                                    "ld_dir", "ld_bw_ix_d16")})
        g16 = ("inc_m_bw_d16", "not_m_bw_d16", "shl_m1_bw_d16", "neg_m_bw_d16",
               "dec_m_bw_d16")
        gih = {(s, f, n) for m, s, f, n, k, x in cells(self.f29, "gih")}
        self.assertEqual(gih, {(None, f, n) for n in range(3) for f in g16}
                         | {("dw", f, 0) for f in g16 + ("test_dir_aw", "test_m_aw_bw_d16")})
        out = ("out_imm_al",)
        pi = {(m, s, x) for m, s, f, n, k, x in cells(self.f29, "pi")}
        self.assertEqual(pi, {(m, "oo", out + ("nop",) * n + (x,) + out)
                              for m in ("push", "out") for n in range(4)
                              for x in ("mov_aw_imm", "add_dw_imm")}
                         | {(m, "noo", ("nop",) * n + out + out) for m in ("push", "out")
                            for n in range(6)})
        self.assertEqual({c.knobs["probe"] for c in self.f28},
                         {"empty", "fence_out", "tail_out", "refresh_beat_t4/b2b"})
        self.assertEqual({c.knobs["probe"] for c in self.f29},
                         {"empty", "disp_io", "grp_io_hold", "port_issue"})

    def test_baselines(self):
        from validation.v35s.chains.derive import BASELINES, index_facts, variant_of
        for family, chains in (("F28", self.f28), ("F29", self.f29)):
            metric, base = BASELINES[family]
            self.assertEqual(metric, "dM")
            facts = []
            for c in chains:
                variant = variant_of(c)
                facts.append({"id": c.id, "marker": c.marker_kind, "knobs": c.knobs,
                              "x_variant": variant[len(c.marker_kind) + 1:],
                              "column": f"p{c.parity[0].upper()}-w{c.waits}"})
            index = index_facts(facts)
            for f in facts:
                b = base(f, index, None)
                if f["knobs"]["series"] == "empty":
                    self.assertIsNone(b, f["id"])
                    continue
                self.assertIsNotNone(b, f["id"])
                self.assertEqual(b["knobs"]["series"], "empty", f["id"])
                self.assertEqual((b["marker"], b["column"], b["knobs"]["rfm"]),
                                 (f["marker"], f["column"], f["knobs"]["rfm"]), f["id"])


class F24Tests(unittest.TestCase):
    """(WP66) the string and block forms: catalog bytes, counts per series, placement, the
    register presets, the expected accesses (REP, the compares' exit, odd splits, I/O) and the
    baselines."""

    @classmethod
    def setUpClass(cls):
        cls.f24 = generate(["F24"])
        cls.by_id = {c.id: c for c in cls.f24}

    OPCODES = {"movbk": 0xA4, "cmpbk": 0xA6, "stm": 0xAA, "ldm": 0xAC, "cmpm": 0xAE,
               "inm": 0x6C, "outm": 0x6E}
    COUNTS = {"movbk": (1, 1, 0), "cmpbk": (2, 0, 0), "stm": (0, 1, 0), "ldm": (1, 0, 0),
              "cmpm": (1, 0, 0), "inm": (0, 1, 1), "outm": (1, 0, 1)}

    def _acc(self, cid):
        from validation.v35s.chains.normalize import expected_accesses
        acc = expected_accesses(self.by_id[cid])
        return [(a.kind, a.addr, a.width) for k in sorted(acc) for a in acc[k]]

    def test_catalog_bytes(self):
        from validation.v35s.chains.forms import STRING_FORMS, UNMODELLED_FORMS
        self.assertEqual(len(STRING_FORMS), 32)
        for name, s in STRING_FORMS.items():
            f = FORMS[name]
            prefix = {None: b"", "rep": b"\xf3", "repe": b"\xf3", "repne": b"\xf2"}[s.rep]
            self.assertEqual(f.code, prefix + bytes([self.OPCODES[s.op] | (s.width - 1)]), name)
            self.assertEqual((f.reads, f.writes, f.io), self.COUNTS[s.op], name)
            self.assertEqual(f.width, s.width, name)
            self.assertTrue(f.cls.startswith("str_"), name)
            self.assertEqual(dict(f.needs).get("DW"), 0x40 if f.io else None, name)
            self.assertNotIn(name, UNMODELLED_FORMS)      # (WP67) the simulator decodes them
            if s.rep:
                self.assertEqual(s.rep != "rep", s.op in ("cmpbk", "cmpm"), name)
        for name, code in (("rep_stm_w", "f3ab"), ("repne_cmpm_w", "f2af"),
                           ("repe_cmpbk_b", "f3a6"), ("rep_inm_w", "f36d"), ("outm_b", "6e"),
                           ("movbk_w", "a5"), ("mov_cw_imm0", "b90000"),
                           ("mov_cw_imm16", "b91000"), ("st_imm0_dir_c42", "c706420c0000")):
            self.assertEqual(FORMS[name].code.hex(), code, name)
        # the MOV CW forms and the pattern store are modelled forms (the simulator decodes them)
        self.assertNotIn("mov_cw_imm8", UNMODELLED_FORMS)
        self.assertNotIn("st_imm0_dir_c42", UNMODELLED_FORMS)

    def test_f24_is_modelled(self):
        from validation.v35s.chains.families import UNMODELLED
        # (WP67) the simulator runs the string forms: no family is generator-only
        for f in ("F23", "F24", "F25", "F26", "F27", "F28", "F29"):
            self.assertNotIn(f, UNMODELLED)

    def test_counts(self):
        from collections import Counter
        self.assertEqual(len(self.f24), 152 * 6)
        cells = [c for c in self.f24 if c.parity == "even" and c.waits == 0]
        self.assertEqual(Counter(c.knobs["series"] for c in cells),
                         {"empty": 1, "s": 28, "r": 75, "a": 27, "t": 13, "d": 8})
        self.assertEqual(Counter(c.knobs["series"] for c in cells if c.knobs["form"] is None),
                         {"empty": 1, "r": 7, "t": 1, "d": 2})
        self.assertEqual({(c.waits, c.parity) for c in self.f24},
                         {(w, p) for w in (0, 1, 2) for p in ("even", "odd")})
        self.assertEqual({(c.marker_kind, c.rfm, c.prelude_marker) for c in self.f24},
                         {("out", 0xEC, None)})
        r = {(c.knobs["form"], c.knobs["n"]) for c in cells if c.knobs["series"] == "r"
             and c.knobs["form"]}
        self.assertEqual(len(r), 11 * 6 + 2)
        self.assertIn(("rep_movbk_w", 16), r)
        self.assertIn(("repne_cmpm_w", 0), r)

    def test_placement_and_registers(self):
        from validation.v35s.chains.forms import F24_IX, F24_IY
        for c in self.f24:
            k = c.knobs
            self.assertRegex(c.id, r"^F24-out-(empty|[srtad]-[a-z0-9-]+)-p[EO]-w[012]$", c.id)
            roles = [i.role for i in c.instrs if i.role != "pad"]
            pre = ["x"] * len(k["pre"])
            body = roles[len(pre) + 2:-3]
            self.assertEqual(roles[:len(pre) + 2], pre + ["ls", "marker"], c.id)
            self.assertEqual(roles[-3:], ["marker", "ls", "end"], c.id)
            self.assertEqual(body.count("drain"), k["drain"], c.id)
            x = [i for i in c.instrs if i.role == "x" and i.index is not None]
            self.assertEqual([i.form for i in x], k["x"], c.id)
            self.assertEqual([i.index for i in x], list(range(len(x))), c.id)
            self.assertEqual([i.form for i in c.instrs if i.role == "x" and i.index is None],
                             k["pre"], c.id)
            self.assertEqual(k["pre"], ["st_imm0_dir_c42"] if k["pattern"] else [], c.id)
            # the registers: IX / IY presets (odd per the align knob), DW the port, segments 0
            odd = {"even": (0, 0), "ix": (1, 0), "iy": (0, 1), "ixiy": (1, 1)}[k["align"]]
            self.assertEqual((c.regs["IX"], c.regs["IY"]), (F24_IX + odd[0], F24_IY + odd[1]),
                             c.id)
            self.assertEqual((k["ix"], k["iy"]), (c.regs["IX"], c.regs["IY"]), c.id)
            self.assertEqual((c.regs["DW"], c.regs["DS0"], c.regs["DS1"], c.regs["SS"]),
                             (0x0040, 0, 0, 0), c.id)
            self.assertEqual({r: c.regs[r] for r in ("AW", "BW", "CW", "SP", "BP")},
                             {"AW": 0x1234, "BW": 0x0800, "CW": 0, "SP": 0x0F00, "BP": 0x0A00},
                             c.id)
            if k["align"] != "even":
                self.assertEqual((k["series"], k["width"]), ("a", 2), c.id)
            # the REP count is set in the frame, directly before the string form or the drains
            if k["n"] is not None:
                self.assertEqual(k["x"][0], f"mov_cw_imm{k['n']}", c.id)
            if k["form"]:
                self.assertEqual(k["x"][-1], k["form"], c.id)
                self.assertEqual(k["x"].count(k["form"]), k["k"], c.id)
            built = build_image(c)
            at = built.chain_base - CODE_BASE
            for i in c.instrs:
                self.assertEqual(built.code[at + i.offset:at + i.offset + len(i.code)],
                                 FORMS[i.form].code if i.role == "x" else i.code, c.id)
            m0 = next(i for i in c.instrs if i.role == "marker")
            self.assertEqual((built.chain_base + m0.offset) & 1, c.parity == "odd", c.id)

    def test_iterations_match_the_walk(self):
        from validation.v35s.chains.normalize import expected_accesses, string_elements
        for c in self.f24:
            runs = string_elements(c).values()
            got = sum(len(r.elements) for r in runs)
            self.assertEqual(got, c.knobs["iters"] or 0, c.id)
            # the overrun: one element's reads after a REP compare that ran an element
            k = c.knobs
            want = bool(k["rep"] and k["op"] in ("cmpbk", "cmpm") and k["iters"])
            self.assertEqual([bool(r.overrun) for r in runs], [want] * len(runs), c.id)
            for r in runs:
                if r.overrun:
                    self.assertEqual(len(r.overrun), len(r.elements[-1]), c.id)
                    self.assertTrue(all(a.kind == "data_read" for a in r.overrun), c.id)
            for accs in expected_accesses(c).values():
                for a in accs:
                    if a.kind.startswith("data"):
                        in_src = 0x0A40 <= a.addr < 0x0A60
                        in_dst = 0x0C40 <= a.addr < 0x0C60
                        self.assertTrue(in_src or in_dst, (c.id, a))
                    if a.kind.startswith("io") and a.addr not in (0x20, 0x21, 0xFF00):
                        self.assertEqual(a.addr, 0x0040, c.id)
        it = {c.id.rsplit("-p", 1)[0]: c.knobs["iters"] for c in self.f24}
        self.assertEqual(it["F24-out-t-repe-cmpm-w-n4-fill"], 1)
        self.assertEqual(it["F24-out-t-repne-cmpbk-w-n4-fill"], 1)
        self.assertEqual(it["F24-out-t-repe-cmpbk-w-n4-pat"], 2)
        self.assertEqual(it["F24-out-t-repne-cmpm-w-n4-pat"], 2)
        self.assertEqual(it["F24-out-t-repne-cmpm-b-n4-pat"], 3)
        self.assertEqual(it["F24-out-r-repe-cmpbk-w-n8"], 8)
        self.assertEqual(it["F24-out-r-rep-stm-w-n0"], 0)
        self.assertEqual(it["F24-out-s-movbk-w-k2"], 2)

    def test_expected_accesses(self):
        m0, m1, end = ("io_write", 0x20, "lo"), ("io_write", 0x21, "lo"), ("io_write", 0xFF00,
                                                                           "word")
        self.assertEqual(self._acc("F24-out-r-rep-stm-w-n4-pE-w0"),
                         [m0] + [("data_write", 0x0C40 + 2 * j, "word") for j in range(4)]
                         + [m1, end])
        # REPE CMPM on the fill: 0000h against 9090h differs at once, one element, then the
        # overrun read of the next one (F24 silicon)
        self.assertEqual(self._acc("F24-out-t-repe-cmpm-w-n4-fill-pO-w1"),
                         [m0, ("data_read", 0x0C40, "word"), ("data_read", 0x0C42, "word"),
                          m1, end])
        # REPNE CMPM over the pattern: the store before the first LS, then 9090h (differs,
        # go on) and the zeroed word at 0C42h (equal, stop): two elements of four, the overrun
        self.assertEqual(self._acc("F24-out-t-repne-cmpm-w-n4-pat-pE-w0"),
                         [("data_write", 0x0C42, "word"), m0, ("data_read", 0x0C40, "word"),
                          ("data_read", 0x0C42, "word"), ("data_read", 0x0C44, "word"), m1,
                          end])
        # REPE CMPBK over the pattern: destination then source per element, stop at 2, the
        # overrun element's pair
        self.assertEqual(self._acc("F24-out-t-repe-cmpbk-w-n4-pat-pE-w2"),
                         [("data_write", 0x0C42, "word"), m0,
                          ("data_read", 0x0C40, "word"), ("data_read", 0x0A40, "word"),
                          ("data_read", 0x0C42, "word"), ("data_read", 0x0A42, "word"),
                          ("data_read", 0x0C44, "word"), ("data_read", 0x0A44, "word"),
                          m1, end])
        # REPNE CMPM run out at n = 1: the element and the overrun; the single CMPBK: one pair
        self.assertEqual(self._acc("F24-out-r-repne-cmpm-w-n1-pE-w0"),
                         [m0, ("data_read", 0x0C40, "word"), ("data_read", 0x0C42, "word"),
                          m1, end])
        self.assertEqual(self._acc("F24-out-s-cmpbk-b-k1-pE-w0"),
                         [m0, ("data_read", 0x0C40, "lo"), ("data_read", 0x0A40, "lo"), m1,
                          end])
        self.assertEqual(self._acc("F24-out-r-repe-cmpbk-w-n0-pE-w0"), [m0, m1, end])
        # REP with CW = 0: no element
        self.assertEqual(self._acc("F24-out-r-rep-movbk-w-n0-pE-w0"), [m0, m1, end])
        # odd source and destination: each word splits, read then write per element
        self.assertEqual(self._acc("F24-out-a-rep-movbk-w-n1-ixiy-pE-w0"),
                         [m0, ("data_read", 0x0A41, "hi"), ("data_read", 0x0A42, "lo"),
                          ("data_write", 0x0C41, "hi"), ("data_write", 0x0C42, "lo"), m1, end])
        # INM / OUTM: the port DW = 0040h and the memory side per element
        self.assertEqual(self._acc("F24-out-r-rep-inm-b-n2-pE-w0"),
                         [m0, ("io_read", 0x40, "lo"), ("data_write", 0x0C40, "lo"),
                          ("io_read", 0x40, "lo"), ("data_write", 0x0C41, "hi"), m1, end])
        self.assertEqual(self._acc("F24-out-s-outm-w-k2-pO-w0"),
                         [m0, ("data_read", 0x0A40, "word"), ("io_write", 0x40, "word"),
                          ("data_read", 0x0A42, "word"), ("io_write", 0x40, "word"), m1, end])

    def test_unknown_values_raise(self):
        # a compare under REP after a form the walk does not follow cannot be predicted
        from validation.v35s.chains.families import make_chain
        from validation.v35s.chains.families import LS, M, X, END
        from validation.v35s.chains.normalize import NormalizeError, expected_accesses
        body = [LS(), M(0), X("mov_cw_imm4", 0), X("mulu_dw", 1), X("repe_cmpm_w", 2), M(1),
                LS(), END()]
        with self.assertRaises(NormalizeError):
            expected_accesses(make_chain("F24", "x", {}, body, 0, "even"))

    def test_synthetic_runs_normalize(self):
        from validation.v35s.chains.derive import f24_apply, run_facts
        from validation.v35s.chains.normalize import normalize
        for cid in ("F24-out-r-rep-stm-w-n4-pE-w0", "F24-out-t-repne-cmpm-w-n4-pat-pO-w0",
                    "F24-out-a-rep-movbk-w-n2-ixiy-pE-w0", "F24-out-d-rep-stm-w-n4-d2-pO-w0",
                    "F24-out-r-rep-outm-b-n3-pE-w0", "F24-out-empty-pE-w0"):
            n = normalize(_synthetic_run(self.by_id[cid]))
            self.assertEqual(n.checks, [], cid)
            self.assertEqual(sorted(n.t_markers), [0, 1], cid)
            f = run_facts(n)
            f24_apply([f], {cid: n})
            self.assertEqual(f["str_elements"], n.chain.knobs["iters"], cid)
            self.assertEqual(f["str_overrun"] is not None, "cmpm" in cid, cid)

    def test_baselines(self):
        from validation.v35s.chains.derive import BASELINES, index_facts, variant_of
        metric, base = BASELINES["F24"]
        self.assertEqual(metric, "dM")
        facts = []
        for c in self.f24:
            variant = variant_of(c)
            facts.append({"id": c.id, "marker": c.marker_kind, "knobs": c.knobs,
                          "x_variant": variant[len(c.marker_kind) + 1:],
                          "column": f"p{c.parity[0].upper()}-w{c.waits}"})
        index = index_facts(facts)
        for f in facts:
            b = base(f, index, None)
            k = f["knobs"]
            if k["baseline"] is None:
                self.assertIsNone(b, f["id"])
                self.assertIsNone(k["form"], f["id"])
                continue
            self.assertIsNotNone(b, f["id"])
            self.assertIsNone(b["knobs"]["form"], f["id"])
            self.assertEqual(b["column"], f["column"], f["id"])
            # the baseline's frame is X's less the string form (the controls hold no pattern
            # store: it runs before the first LS)
            self.assertEqual(b["knobs"]["x"], [x for x in k["x"] if x != k["form"]], f["id"])

    def test_gen_check(self):
        import contextlib
        import io
        from validation.v35s.chains.__main__ import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["gen", "--family", "F24", "--check"]), 0)
        self.assertIn("checked 912 images", out.getvalue())



class F30Tests(unittest.TestCase):
    """(WP73) the facts-only shapes' probe family: the segment forms' bytes, counts per probe,
    placement (the bytes between the markers, the pads before M0, the presets), the execution
    order of the transfers, the string walks, classification of synthetic and recorded runs,
    the baselines."""

    @classmethod
    def setUpClass(cls):
        cls.f30 = generate(["F30"])
        cls.by_id = {c.id: c for c in cls.f30}
        cls.cells = [c for c in cls.f30 if c.parity == "even" and c.waits == 0]

    def test_catalog_bytes(self):
        for name, code in (("mov_ss_aw", "8ed0"), ("mov_ds0_aw", "8ed8"), ("mov_ds1_ix", "8e04"),
                           ("mov_ss_ix", "8e14"), ("mov_ds0_ix", "8e1c"), ("mov_aw_ps", "8cc8"),
                           ("mov_aw_ss", "8cd0"), ("mov_aw_ds0", "8cd8"), ("mov_m_ds1", "8c07"),
                           ("mov_m_ps", "8c0f"), ("mov_m_ss", "8c17"), ("push_ss", "16"),
                           ("pop_ss", "17")):
            self.assertEqual(FORMS[name].code.hex(), code, name)
        for name in ("mov_ds1_ix", "mov_ss_ix", "mov_ds0_ix"):
            f = FORMS[name]
            self.assertEqual((f.cls, f.reads, f.ea, f.mode_class), ("load_seg", 1, 0x0100, "base"))
        for name in ("mov_m_ds1", "mov_m_ps", "mov_m_ss"):
            self.assertEqual((FORMS[name].cls, FORMS[name].writes, FORMS[name].ea),
                             ("store", 1, 0x0800))
        self.assertEqual(blocks.drainer4_zero().hex(), "81c20000")

    def test_counts(self):
        from collections import Counter
        from validation.v35s.chains.types import RFM_OFF
        self.assertEqual(len(self.f30), 246 * 6)
        self.assertEqual(Counter(c.knobs["probe"] for c in self.cells),
                         {"empty": 3, "str": 57, "odd": 46, "seg": 56, "br": 16, "nt": 24,
                          "cr": 12, "lea": 32})
        self.assertEqual(Counter((c.knobs["probe"], c.marker_kind) for c in self.cells
                                 if c.knobs["probe"] in ("br", "seg", "nt", "cr", "lea")),
                         {("br", "out"): 11, ("br", "store"): 5, ("seg", "out"): 28,
                          ("seg", "push"): 28, ("nt", "out"): 12, ("nt", "push"): 12,
                          ("cr", "out"): 6, ("cr", "push"): 6, ("lea", "out"): 16,
                          ("lea", "push"): 16})
        for c in self.f30:
            self.assertEqual(c.rfm, RFM_OFF, c.id)
            self.assertTrue(c.id.startswith(f"F30-{c.marker_kind}-"), c.id)
            self.assertEqual(c.knobs["marker"], c.marker_kind, c.id)

    def _between(self, c):
        """(pre, body): the codes between the first LS and M0, and between M0 and M1."""
        roles = [i.role for i in c.instrs]
        ls, m0 = roles.index("ls"), roles.index("marker")
        m1 = roles.index("marker", m0 + 1)
        return c.instrs[ls + 1:m0], c.instrs[m0 + 1:m1]

    def test_placement(self):
        from validation.v35s.chains.forms import F24_IX, F24_IY, IO_PORT
        code = lambda names: b"".join(FORMS[n].code for n in names)
        b = lambda c, label: c.id == f"F30-{c.marker_kind}-{label}-pE-w0"
        for c in self.cells:
            build_image(c)                      # raises on any misplaced byte
            pre, body = self._between(c)
            k = c.knobs
            got = b"".join(i.code for i in body)
            self.assertEqual(b"".join(i.code for i in pre), code(["nop"] * len(pre)), c.id)
            if k["probe"] in ("str", "odd"):
                self.assertEqual(c.marker_kind, "out")
                self.assertEqual(c.regs["DW"], IO_PORT, c.id)
                self.assertEqual(c.regs["IX"], F24_IX + (k["align"] in ("ix", "ixiy")), c.id)
                self.assertEqual(c.regs["IY"], F24_IY + (k["align"] in ("iy", "ixiy")), c.id)
                self.assertEqual(sum(i.code == FORMS[k["form"]].code for i in body),
                                 1 + (k.get("follower") == "rep"), c.id)
            if k["probe"] == "br":
                self.assertEqual(len(pre), int(k["lead"][3:]) if k["lead"].startswith("pad")
                                 else 0, c.id)
            if k["probe"] != "empty":
                self.assertEqual([i.form for i in body if i.role == "x"], k["x"][len(pre):], c.id)
        by = {c.id: c for c in self.cells}
        body = lambda cid: b"".join(i.code for i in self._between(by[cid + "-pE-w0"])[1])
        self.assertEqual(body("F30-out-str-inm-w-n2-l0"), bytes.fromhex("b90200f36d"))
        self.assertEqual(body("F30-out-str-inm-w-n2-d"), bytes.fromhex("b83412b90200f36d"))
        self.assertEqual(body("F30-out-str-outm-w-n1-d4"), bytes.fromhex("81c20000b90100f36f"))
        self.assertEqual(body("F30-out-str-stm-w-n0-nop2"), bytes.fromhex("b9000090 90f3ab"))
        self.assertEqual(body("F30-out-str-stm-b-n1-l0"), bytes.fromhex("b90100f3aa"))
        self.assertEqual(body("F30-out-str-inm-w-n1-sep"), bytes.fromhex("b90100c1e008f36d"))
        self.assertEqual(body("F30-out-odd-movbk-iy-n1-rep"), bytes.fromhex("b90100f3a5b90100f3a5"))
        self.assertEqual(body("F30-out-odd-cmpbk-ixiy-n1-ld"), bytes.fromhex("b90100f3a78b07"))
        self.assertEqual(body("F30-push-seg-8e-ss-ix-n1"), bytes.fromhex("908e14"))
        self.assertEqual(body("F30-out-seg-8e-ds0-aw-n0-k2"), bytes.fromhex("8ed88ed8"))
        self.assertEqual(body("F30-out-seg-pair-ss-n0"), bytes.fromhex("1617"))
        self.assertEqual(body("F30-out-br-short-n3-nop"), bytes.fromhex("90eb03909090"))
        self.assertEqual(body("F30-store-br-short-n2-l0"), bytes.fromhex("eb029090"))
        self.assertEqual(body("F30-out-br-near-n1-nop"), bytes.fromhex("90e9010090"))
        self.assertEqual(body("F30-push-nt-bne-k3-n0"), bytes.fromhex("3bc0750075007500"))
        self.assertEqual(body("F30-out-nt-dbnz-k2-n0"), bytes.fromhex("b90100e200b90100e200"))
        self.assertEqual(body("F30-out-cr-a2-b0"), bytes.fromhex("e80200eb039090c3"))
        self.assertEqual(body("F30-push-cr-shl8"), bytes.fromhex("e80200eb04c1e008c3"))
        self.assertEqual(body("F30-out-lea-bw_ix_d16-k2"), bytes.fromhex("8d8000028d800002"))
        self.assertEqual(body("F30-push-lea-dir-nopb"), bytes.fromhex("908d06000c"))
        self.assertEqual(body("F30-out-lea-bw-d4"), bytes.fromhex("81c234128d07"))
        pre = self._between(by["F30-out-br-short-n1-pad2-pE-w0"])[0]
        self.assertEqual(b"".join(i.code for i in pre), b"\x90\x90")

    def test_transfer_execution_order(self):
        """The exec knob follows the instructions the chain runs: a taken BR skips its n NOPs;
        cr runs CALL, NOP^a, RET, BR, NOP^b."""
        from validation.v35s.chains.sim.templates import decode
        for c in self.cells:
            k = c.knobs
            if k["probe"] not in ("br", "cr", "nt"):
                continue
            xs = [i for i in c.instrs if i.role == "x"]
            self.assertEqual(sorted(k["exec"]), sorted(set(k["exec"])), c.id)
            self.assertEqual(len(xs) - len(k["exec"]), k["skipped"], c.id)
            # follow the targets through the X instructions after M0 (the br pads before M0
            # run in order, indices 0..pre-1)
            pre = len(self._between(c)[0])
            at, order = xs[pre].offset, list(range(pre))
            offs = {i.offset: n for n, i in enumerate(xs)}
            regs = {"Z": 1, "CW": 0, "SP": 0x0F00, "DW": 0x40, "AW": 0, "BW": 0x0800,
                    "BP": 0x0A00, "IX": 0x0100, "IY": 0x0180}
            from validation.v35s.chains.sim.templates import execute
            while at in offs:
                op = decode(c.code, at, regs)
                order.append(offs[at])
                execute(op, c.code, regs)
                at = op.target if getattr(op, "target", None) is not None else at + op.length
            self.assertEqual(order, k["exec"], c.id)

    def test_string_walks(self):
        from validation.v35s.chains.normalize import expected_accesses, string_elements
        for c in self.cells:
            if c.knobs["probe"] not in ("str", "odd"):
                continue
            runs = string_elements(c)
            self.assertEqual(sum(len(r.elements) for r in runs.values()), c.knobs["iters"], c.id)
            acc = expected_accesses(c)
            k = c.knobs
            if k["probe"] == "odd":
                # every element of an odd operand splits into two byte cycles
                splits = sum(a.split for accs in acc.values() for a in accs)
                per = {"ix": 1, "iy": 1, "ixiy": 2}[k["align"]] * 2
                overrun = 1 if k["op"] in ("cmpbk", "cmpm") else 0
                self.assertEqual(splits, per * (k["iters"] + overrun), c.id)
            if k["probe"] == "str" and k["op"] in ("inm", "outm"):
                self.assertTrue(all(a.addr == 0x40 for accs in acc.values() for a in accs
                                    if a.kind.startswith("io") and a.addr != 0xFF00
                                    and a.addr not in (0x20, 0x21)), c.id)

    def test_seg_and_lea_accesses(self):
        from validation.v35s.chains.normalize import expected_accesses
        cid = lambda label: self.by_id[f"F30-{label}-pE-w0"]
        flat = lambda c: [(a.kind, a.addr) for k in sorted(expected_accesses(c))
                          for a in expected_accesses(c)[k]]
        self.assertEqual(flat(cid("out-seg-8e-ss-ix-n0")),
                         [("io_write", 0x20), ("data_read", 0x0100), ("io_write", 0x21),
                          ("io_write", 0xFF00)])
        self.assertEqual(flat(cid("push-seg-8c-bw-ds1-n1")),
                         [("stack_write", 0x0EFE), ("data_write", 0x0800),
                          ("stack_write", 0x0EFC), ("io_write", 0xFF00)])
        self.assertEqual(flat(cid("push-seg-pair-ss-n0")),
                         [("stack_write", 0x0EFE), ("stack_write", 0x0EFC),
                          ("stack_read", 0x0EFC), ("stack_write", 0x0EFC), ("io_write", 0xFF00)])
        self.assertEqual(flat(cid("out-cr-a0-b2")),
                         [("io_write", 0x20), ("stack_write", 0x0EFE), ("stack_read", 0x0EFE),
                          ("io_write", 0x21), ("io_write", 0xFF00)])
        self.assertEqual(flat(cid("out-lea-bw_ix_d16-k2")),
                         [("io_write", 0x20), ("io_write", 0x21), ("io_write", 0xFF00)])
        self.assertEqual(flat(cid("store-br-short-n0-l0")),
                         [("data_write", 0x0C00), ("data_write", 0x0C00), ("io_write", 0xFF00)])

    def test_synthetic_runs_normalize(self):
        """Every F30 cell's synthetic run classifies: each data, stack and I/O cycle matched
        to its instruction, both markers found."""
        from validation.v35s.chains.normalize import normalize
        for c in self.cells:
            n = normalize(_synthetic_run(c))
            self.assertIsNone(n.access_mismatch, c.id)
            self.assertEqual(sorted(n.t_markers), [0, 1], c.id)
            self.assertTrue(all(e.instr_index is not None for e in n.events
                                if e.kind != "fetch"), c.id)

    def test_recorded_runs_classify(self):
        """(when the corpus or build/ holds F30) every recorded run normalises strictly with no
        unclassified cycle: each non-fetch cycle has its instruction, every fetch maps."""
        from validation.v35s.chains.normalize import load_runs, normalize
        try:
            runs = load_runs("F30", (0,))
        except (FileNotFoundError, ImportError):
            self.skipTest("no recorded F30 runs")
        self.assertTrue(runs)
        for r in runs[::7]:
            n = normalize(r)
            self.assertEqual(n.checks, [], n.run_id)
            self.assertTrue(all(e.instr_index is not None for e in n.events
                                if e.kind not in ("fetch", "refresh")), n.run_id)

    def test_baselines(self):
        from validation.v35s.chains.derive import BASELINES, index_facts, run_facts
        from validation.v35s.chains.normalize import normalize
        metric, base = BASELINES["F30"]
        self.assertEqual(metric, "dM")
        facts = [run_facts(normalize(_synthetic_run(c))) for c in self.cells]
        index = index_facts(facts)
        for f in facts:
            b = base(f, index, None)
            if f["knobs"]["probe"] == "empty":
                self.assertIsNone(b, f["id"])
                continue
            self.assertIsNotNone(b, f["id"])
            self.assertEqual((b["knobs"]["probe"], b["marker"], b["column"]),
                             ("empty", f["marker"], f["column"]), f["id"])

    def test_gen_check(self):
        import contextlib
        import io
        from validation.v35s.chains.__main__ import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["gen", "--family", "F30", "--check"]), 0)
        self.assertIn("checked 1476 images", out.getvalue())



class F31Tests(unittest.TestCase):
    """(WP73 follow-up) F30's controls: alf (aligned REP forms with followers) and lone (one
    refill fetch, not back to back, inside the REP setup): counts, bytes, presets, the string
    walks, classification of synthetic and recorded runs, baselines, gen --check."""

    @classmethod
    def setUpClass(cls):
        cls.f31 = generate(["F31"])
        cls.cells = [c for c in cls.f31 if c.parity == "even" and c.waits == 0]
        cls.by = {c.id: c for c in cls.cells}

    def test_counts(self):
        from collections import Counter
        self.assertEqual(len(self.f31), 39 * 6)
        self.assertEqual(Counter(c.knobs["probe"] for c in self.cells),
                         {"empty": 1, "alf": 26, "lone": 12})
        for c in self.f31:
            self.assertEqual((c.marker_kind, c.knobs["marker"]), ("out", "out"), c.id)
            self.assertTrue(c.id.startswith("F31-out-"), c.id)

    def test_placement_and_presets(self):
        from validation.v35s.chains.forms import F24_IX, F24_IY, IO_PORT
        body = lambda cid: b"".join(i.code for i in self.by[cid + "-pE-w0"].instrs
                                    if i.role == "x")
        self.assertEqual(body("F31-out-alf-stm-n2-rep"), bytes.fromhex("b90200f3abb90100f3ab"))
        self.assertEqual(body("F31-out-alf-cmpbk-n1-ld"), bytes.fromhex("b90100f3a78b07"))
        self.assertEqual(body("F31-out-alf-ldm-n1-end"), bytes.fromhex("b90100f3ad"))
        self.assertEqual(body("F31-out-lone-inm-w-n1-b1a4"), bytes.fromhex("90b9010090909090f36d"))
        self.assertEqual(body("F31-out-lone-outm-w-n1-b0a5"), bytes.fromhex("b9010090909090 90f36f"))
        self.assertEqual(body("F31-out-lone-stm-w-n1-b2a4"), bytes.fromhex("9090b9010090909090f3ab"))
        for c in self.cells:
            build_image(c)
            roles = [i.role for i in c.instrs if i.role != "pad"]
            self.assertEqual(roles[:2], ["ls", "marker"], c.id)
            if c.knobs["form"]:
                self.assertEqual((c.regs["IX"], c.regs["IY"], c.regs["DW"]),
                                 (F24_IX, F24_IY, IO_PORT), c.id)
                self.assertEqual(c.knobs["align"], "even")

    def test_string_walks_and_classification(self):
        from validation.v35s.chains.normalize import expected_accesses, normalize, string_elements
        for c in self.cells:
            n = normalize(_synthetic_run(c))
            self.assertIsNone(n.access_mismatch, c.id)
            self.assertEqual(sorted(n.t_markers), [0, 1], c.id)
            if c.knobs["form"]:
                runs = string_elements(c)
                self.assertEqual(sum(len(r.elements) for r in runs.values()), c.knobs["iters"])
                acc = expected_accesses(c)
                self.assertFalse(any(a.split for accs in acc.values() for a in accs), c.id)

    def test_recorded_runs_classify(self):
        from validation.v35s.chains.normalize import load_runs, normalize
        try:
            runs = load_runs("F31", (0, 1, 2))
        except (FileNotFoundError, ImportError):
            self.skipTest("no recorded F31 runs")
        self.assertEqual(len(runs), 234)
        for r in runs:
            n = normalize(r)
            self.assertEqual(n.checks, [], n.run_id)
            self.assertTrue(all(e.instr_index is not None for e in n.events
                                if e.kind not in ("fetch", "refresh")), n.run_id)

    def test_baselines(self):
        from validation.v35s.chains.derive import BASELINES, index_facts, run_facts
        from validation.v35s.chains.normalize import normalize
        metric, base = BASELINES["F31"]
        facts = [run_facts(normalize(_synthetic_run(c))) for c in self.cells]
        index = index_facts(facts)
        for f in facts:
            b = base(f, index, None)
            if f["knobs"]["probe"] == "empty":
                self.assertIsNone(b)
            else:
                self.assertEqual((b["knobs"]["probe"], b["column"]), ("empty", f["column"]))

    def test_gen_check(self):
        import contextlib
        import io
        from validation.v35s.chains.__main__ import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["gen", "--family", "F31", "--check"]), 0)
        self.assertIn("checked 234 images", out.getvalue())


class F32F33Tests(unittest.TestCase):
    """(WP74) the 0F page (F32) and the register miscellany with REPC / REPNC (F33): the forms'
    bytes and generator-only status, counts per group, placement and presets, the walks (the
    BCD strings, the bit fields, the REPC / REPNC carry exits), classification of synthetic and
    recorded runs, baselines, the k series, gen --check."""

    @classmethod
    def setUpClass(cls):
        cls.f32 = generate(["F32"])
        cls.f33 = generate(["F33"])
        cls.cells = [c for c in cls.f32 + cls.f33 if c.parity == "even" and c.waits == 0]
        cls.by = {c.id: c for c in cls.cells}

    def _body(self, cid):
        return b"".join(i.code for i in self.by[cid + "-pE-w0"].instrs if i.role == "x"
                        and i.index is not None)

    def _acc(self, cid):
        from validation.v35s.chains.normalize import expected_accesses
        c = self.by[cid + "-pE-w0"]
        acc = expected_accesses(c)
        return [(a.kind, a.addr, a.width) for k in sorted(acc) for a in acc[k]
                if c.instrs[k].role == "x" and c.instrs[k].index is not None]

    def test_catalog_bytes(self):
        from validation.v35s.chains.forms import (CLASSES, F32_FORMS, F33_FORMS, STRING_FORMS,
                                                  UNMODELLED_FORMS, UNMODELLED_STRING_FORMS)
        for name, code in (("test1_rb_cl", "0f10c0"), ("test1_mw_cl", "0f1107"),
                           ("clr1_mb_imm", "0f1a0707"), ("set1_rw_imm", "0f1dc00f"),
                           ("not1_mw_imm", "0f1f070f"), ("set1_mw_cl_bw_d16", "0f15870002"),
                           ("set1_mw_cl_dir", "0f1506000c"), ("add4s", "0f20"),
                           ("sub4s", "0f22"), ("cmp4s", "0f26"), ("rol4_dl", "0f28c2"),
                           ("ror4_m", "0f2a07"), ("ext_dl_bh", "0f33fa"), ("ext_bl_dh", "0f33f3"),
                           ("ins_bh_bl", "0f31df"),
                           ("ins_dl_i11", "0f39c20b"), ("ext_bl_i7", "0f3bc307"),
                           ("pfx_add4s", "260f20"), ("pfx_set1_mb_imm", "260f1c0707"),
                           ("inc_aw", "40"), ("dec_iy", "4f"), ("inc_dh", "fec6"),
                           ("dec_al", "fec8"), ("incb_m", "fe07"), ("decb_m", "fe0f"),
                           ("adj4s", "2f"), ("adjbs", "3f"), ("cvtbd", "d40a"), ("cvtdb", "d50a"),
                           ("cvtbw", "98"), ("cvtwl", "99"), ("mul_cw", "f7e9"),
                           ("div_cw", "f7f9"), ("divu_cw", "f7f1"),
                           ("mul_aw_cw_imm16", "69c13412"), ("mul_aw_m_imm8", "6b0705"),
                           ("clc", "f8"), ("stc", "f9"), ("cmc", "f5"), ("cli", "fa"),
                           ("sti", "fb"), ("cld", "fc"), ("std", "fd"),
                           ("mov_dw_imm0", "ba0000"), ("repc_cmpm_w", "65af"),
                           ("repnc_cmpbk_w", "64a7"), ("st_imm0_dir_a42", "c706420a0000")):
            self.assertEqual(FORMS[name].code.hex(), code, name)
        for name in F32_FORMS + F33_FORMS:
            self.assertNotIn(name, UNMODELLED_FORMS)     # (WP78) the simulator decodes them
            self.assertIn(FORMS[name].cls, CLASSES, name)
        self.assertEqual(UNMODELLED_FORMS, frozenset())
        # (WP78) one class per cost the facts tell apart
        for name, cls in (("clr1_mb_cl", "bit1_clr"), ("set1_mw_imm", "bit1_rmw"),
                          ("not1_mb_cl", "bit1_rmw"), ("test1_mw_imm", "bit1_test"),
                          ("test1_rb_cl", "bit1"), ("rol4_dl", "rol4"), ("ror4_dl", "ror4"),
                          ("rol4_m", "rol4_mem"), ("ror4_m", "ror4_mem"), ("adj4a", "adjust"),
                          ("adjbs", "adjust_b"), ("cvtbd", "convert"), ("cvtdb", "convert_d"),
                          ("cvtbw", "extend"), ("cvtwl", "extend_w"), ("clc", "flag"),
                          ("cli", "flag_di"), ("sti", "flag_ei"), ("inc_dh", "incdec"),
                          ("incb_m", "rmw"), ("mul_aw_m_imm8", "mul_imm"), ("cmp4s", "bcd4s_cmp"),
                          ("pfx_add4s", "bcd4s"), ("ins_bl_i7", "bf_ins")):
            self.assertEqual(FORMS[name].cls, cls, name)
        self.assertEqual(len(STRING_FORMS), 32)
        self.assertEqual(sorted(UNMODELLED_STRING_FORMS), ["repc_cmpbk_w", "repc_cmpm_w",
                                                           "repnc_cmpbk_w", "repnc_cmpm_w"])
        self.assertFalse(set(UNMODELLED_STRING_FORMS) & set(STRING_FORMS))
        # memory operands: the bit ops at [BW] read (TEST1) or read and write
        self.assertEqual((FORMS["test1_mb_cl"].reads, FORMS["test1_mb_cl"].writes), (1, 0))
        self.assertEqual((FORMS["not1_mw_imm"].reads, FORMS["not1_mw_imm"].writes,
                          FORMS["not1_mw_imm"].width), (1, 1, 2))

    def test_modelled(self):
        # (WP78) F32 and F33 are modelled: score, fit, freeze and the corpus guard take them
        from validation.v35s.chains.families import UNMODELLED
        from validation.v35s.chains import fit
        self.assertNotIn("F32", UNMODELLED)
        self.assertNotIn("F33", UNMODELLED)
        self.assertEqual(UNMODELLED, ())
        self.assertIn("F32", fit.TIE_FAMILIES)
        self.assertEqual(fit.STAGE_FAMILIES[16], ["F32", "F33"])

    def test_counts(self):
        from collections import Counter
        self.assertEqual(len(self.f32), 143 * 6)
        self.assertEqual(len(self.f33), 175 * 6)
        out32 = Counter(c.knobs["group"] for c in self.cells
                        if c.family == "F32" and c.marker_kind == "out")
        self.assertEqual(out32, {"empty": 1, "bit": 64, "mode": 4, "bcd": 22, "rot4": 8,
                                 "bitfield": 28, "pfx": 4})
        out33 = Counter(c.knobs["group"] for c in self.cells
                        if c.family == "F33" and c.marker_kind == "out")
        self.assertEqual(out33, {"empty": 1, "incdec": 64, "adjust": 8, "convert": 4,
                                 "extend": 7, "muldiv": 15, "mulimm": 8, "flag": 14, "rep": 39})
        self.assertEqual(sum(1 for c in self.cells if c.family == "F32"
                             and c.marker_kind == "push"), 12)
        self.assertEqual(sum(1 for c in self.cells if c.family == "F33"
                             and c.marker_kind == "push"), 15)
        for c in self.cells:
            self.assertEqual(c.rfm, 0xEC, c.id)
            if c.marker_kind == "push":
                self.assertIn(c.id.replace("-push-", "-out-", 1), self.by)

    def test_placement_and_presets(self):
        self.assertEqual(self._body("F32-out-add4s-n8-k1"), bytes.fromhex("b1080f20"))
        self.assertEqual(self._body("F32-out-cmp4s-n2-k2"), bytes.fromhex("b1020f260f26"))
        self.assertEqual(self._body("F32-out-pfx_add4s-n4-k1"), bytes.fromhex("b104260f20"))
        self.assertEqual(self._body("F32-out-set1_mw_cl-k2"), bytes.fromhex("0f15070f1507"))
        self.assertEqual(self._body("F33-out-inc_sp-k4"), bytes.fromhex("44444444"))
        self.assertEqual(self._body("F33-out-divu_m-ld-k2"), bytes.fromhex("b83412ba0000f737f737"))
        self.assertEqual(self._body("F33-out-cvtwl-a8080-k1"), bytes.fromhex("b8808099"))
        self.assertEqual(self._body("F33-out-repnc-cmpbk-w-n4-stc"), bytes.fromhex("f9b9040064a7"))
        self.assertEqual(self._body("F33-out-repc-cmpm-w-n0-clc"), bytes.fromhex("f8b9000065af"))
        pat = self.by["F33-out-repnc-cmpbk-w-n2-clc-pat-pE-w0"]
        self.assertEqual([i.form for i in pat.instrs if i.role != "pad"][:3],
                         ["st_imm0_dir_a42", "LS", "M"])
        for c in self.cells:
            build_image(c)
            roles = [i.role for i in c.instrs if i.role in ("ls", "marker", "end")
                     or i.index is not None]
            self.assertEqual(roles[:2], ["ls", "marker"], c.id)
            self.assertEqual(roles[-3:], ["marker", "ls", "end"], c.id)
            k = c.knobs
            self.assertEqual(k["x"], [i.form for i in c.instrs if i.role == "x"
                                      and i.index is not None], c.id)
            if k["form"]:
                self.assertEqual(k["x"], k["lead"] + [k["form"]] * k["k"], c.id)
            names = set(k["x"])
            if names & {"add4s", "sub4s", "cmp4s", "pfx_add4s"} or k["group"] == "rep" and k["form"]:
                self.assertEqual((c.regs["IX"], c.regs["IY"]), (0x0A40, 0x0C40), c.id)
            if any(n.startswith("ext_") for n in names):
                self.assertEqual((c.regs["IX"], c.regs["DW"]), (0x0A40, 0x0608), c.id)
            if any(n.startswith("ins_") for n in names):
                self.assertEqual((c.regs["IY"], c.regs["DW"]), (0x0C40, 0x0608), c.id)
            if k["group"] in ("bit", "mode"):
                self.assertEqual((c.regs["IX"], c.regs["IY"]), (0x0100, 0x0180), c.id)
            self.assertEqual(c.regs["BW"], 0x0800, c.id)

    def test_bcd_and_bitfield_walks(self):
        r, w = "data_read", "data_write"
        self.assertEqual(self._acc("F32-out-add4s-n4-k1"),
                         [(r, 0xA40, "lo"), (r, 0xC40, "lo"), (w, 0xC40, "lo"),
                          (r, 0xA41, "hi"), (r, 0xC41, "hi"), (w, 0xC41, "hi")])
        self.assertEqual(self._acc("F32-out-cmp4s-n2-k1"), [(r, 0xA40, "lo"), (r, 0xC40, "lo")])
        self.assertEqual(len(self._acc("F32-out-sub4s-n16-k1")), 24)
        self.assertEqual(len(self._acc("F32-out-add4s-n2-k2")), 6)      # IX / IY unchanged
        # EXT DL,BH: offset 8, width field 8: crosses (two words), then offset 1 at IX + 2
        self.assertEqual(self._acc("F32-out-ext_dl_bh-k2"),
                         [(r, 0xA40, "word"), (r, 0xA42, "word"), (r, 0xA42, "word")])
        # EXT DL,DH: offset 8, width 6 within; the second at offset 15 crosses
        self.assertEqual(self._acc("F32-out-ext_dl_dh-k2"),
                         [(r, 0xA40, "word"), (r, 0xA40, "word"), (r, 0xA42, "word")])
        # INS DL,7: offset 8 + width 7 = 15 ends at the boundary: one word, IY steps by 2
        self.assertEqual(self._acc("F32-out-ins_dl_i7-k2"),
                         [(r, 0xC40, "word"), (w, 0xC40, "word"), (r, 0xC42, "word"),
                          (w, 0xC42, "word")])
        # a crossing INS reads and writes each word in turn
        self.assertEqual(self._acc("F32-out-ins_dl_i11-k1"),
                         [(r, 0xC40, "word"), (w, 0xC40, "word"), (r, 0xC42, "word"),
                          (w, 0xC42, "word")])
        # BL offset 0, width 6 (DH): one word, the second at offset 7 still in it
        self.assertEqual(self._acc("F32-out-ext_bl_dh-k2"), [(r, 0xA40, "word")] * 2)
        # BH offset 8, BL width 0: one word each (swapped operands would cross the second)
        self.assertEqual(self._acc("F32-out-ext_bh_bl-k2"), [(r, 0xA40, "word")] * 2)
        self.assertEqual(self._acc("F32-out-rol4_m-k1"), [(r, 0x800, "lo"), (w, 0x800, "lo")])
        self.assertEqual(self._acc("F32-out-test1_mw_imm-k2"), [(r, 0x800, "word")] * 2)
        self.assertEqual(self._acc("F32-out-set1_mw_cl_bw_ix-k1"),
                         [(r, 0x900, "word"), (w, 0x900, "word")])
        self.assertEqual(self._acc("F32-out-clr1_rw_cl-k2"), [])
        self.assertEqual(self._acc("F33-out-decb_m-k1"), [(r, 0x800, "lo"), (w, 0x800, "lo")])
        self.assertEqual(self._acc("F33-out-mul_aw_m_imm16-k1"), [(r, 0x800, "word")])
        self.assertEqual(self._acc("F33-out-adj4a-k2"), [])

    def test_unknown_cl_raises(self):
        from validation.v35s.chains.normalize import NormalizeError, expected_accesses
        c = self.by["F32-out-add4s-n4-k1-pE-w0"]
        broken = Chain.from_json(c.to_json())
        at = next(i for i, x in enumerate(broken.instrs) if x.form == "mov_cl_imm")
        broken.instrs[at] = Instr(broken.instrs[at].offset, FORMS["mov_aw_dw"].code, "mov_aw_dw",
                                  "x", index=0)
        broken.instrs[at + 1:at + 1] = []
        with self.assertRaises(NormalizeError):
            expected_accesses(broken)

    def test_rep_carry_walks(self):
        from validation.v35s.chains.normalize import string_elements
        seen = {}
        for c in self.cells:
            k = c.knobs
            if k["group"] != "rep" or not k["form"]:
                continue
            runs = string_elements(c)
            self.assertEqual(sum(len(r.elements) for r in runs.values()), k["iters"], c.id)
            run = next(iter(runs.values()))
            # the overrun read after the last element (F24's REP compares), none at CW = 0
            self.assertEqual(bool(run.overrun), k["n"] > 0, c.id)
            seen[(k["rep"], k["op"], k["n"], k["pattern"])] = k["iters"]
        self.assertEqual(seen[("repc", "cmpm", 4, None)], 4)
        self.assertEqual(seen[("repnc", "cmpm", 4, None)], 1)
        self.assertEqual(seen[("repc", "cmpbk", 4, None)], 1)
        self.assertEqual(seen[("repnc", "cmpbk", 4, None)], 4)
        self.assertEqual(seen[("repc", "cmpm", 4, "dst")], 2)
        self.assertEqual(seen[("repnc", "cmpbk", 4, "src")], 2)
        self.assertEqual(seen[("repc", "cmpm", 0, None)], 0)

    def test_synthetic_runs_normalize(self):
        from validation.v35s.chains.derive import f24_apply, run_facts
        from validation.v35s.chains.normalize import normalize
        for c in self.cells:
            n = normalize(_synthetic_run(c))
            self.assertIsNone(n.access_mismatch, c.id)
            self.assertEqual(n.checks, [], c.id)
            self.assertEqual(sorted(n.t_markers), [0, 1], c.id)
            self.assertTrue(all(e.instr_index is not None for e in n.events
                                if e.kind != "fetch"), c.id)
            if c.family == "F33" and c.knobs["group"] == "rep" and c.knobs["form"]:
                f = run_facts(n)
                f24_apply([f], {c.id: n})
                self.assertEqual(f["str_elements"], c.knobs["iters"], c.id)

    def test_recorded_runs_classify(self):
        from validation.v35s.chains.normalize import load_runs, normalize
        for family in ("F32", "F33"):
            try:
                runs = load_runs(family, (0, 1, 2))
            except (FileNotFoundError, ImportError):
                continue
            self.assertEqual(len(runs), {"F32": 858, "F33": 1050}[family])
            for r in runs:
                n = normalize(r)
                self.assertEqual(n.checks, [], n.run_id)
                self.assertTrue(all(e.instr_index is not None for e in n.events
                                    if e.kind not in ("fetch", "refresh")), n.run_id)

    def test_baselines(self):
        from validation.v35s.chains.derive import BASELINES, index_facts, run_facts
        from validation.v35s.chains.normalize import normalize
        for family in ("F32", "F33"):
            metric, base = BASELINES[family]
            self.assertEqual(metric, "dM")
            facts = [run_facts(normalize(_synthetic_run(c))) for c in self.cells
                     if c.family == family]
            index = index_facts(facts)
            for f in facts:
                b = base(f, index, None)
                k = f["knobs"]
                if k["group"] == "empty":
                    self.assertIsNone(b, f["id"])
                    continue
                self.assertIsNotNone(b, f["id"])
                self.assertEqual((b["marker"], b["column"]), (f["marker"], f["column"]))
                self.assertIsNone(b["knobs"]["form"], f["id"])
                self.assertEqual(b["knobs"]["x"], k["lead"] if k["form"] else [], f["id"])

    def test_k_series(self):
        from validation.v35s.chains.derive import k_series
        cost = {"out-inc_aw-k1": {"pE-w0": 4}, "out-inc_aw-k2": {"pE-w0": 6},
                "out-inc_aw-k4": {"pE-w0": 10}, "out-div_cw-ld-k1": {"pE-w0": 40},
                "out-div_cw-ld-k2": {"pE-w0": 79}, "out-movcl-n4": {"pE-w0": 2}}
        ks = k_series(cost)
        self.assertEqual(ks["out-inc_aw"]["pE-w0"], ({1: 4, 2: 6, 4: 10}, 2, 2))
        self.assertEqual(ks["out-div_cw-ld"]["pE-w0"], ({1: 40, 2: 79}, 39, 1))
        self.assertNotIn("out-movcl-n4", ks)

    def test_gen_check(self):
        import contextlib
        import io
        from validation.v35s.chains.__main__ import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["gen", "--family", "F32", "F33", "--check"]), 0)
        self.assertIn("checked 1908 images", out.getvalue())


class F34Tests(unittest.TestCase):
    """(WP80) the forty-second fit's miss shapes' probe family: the one new byte string, every
    other one already in an earlier family (the frozen decoder and the RTL's selection table know
    them), counts per probe and marker, placement, leads and baselines, the bit-field walks, the
    transfers' execution order, synthetic and recorded runs, simulation under the tracked fit,
    gen --check."""

    @classmethod
    def setUpClass(cls):
        cls.f34 = generate(["F34"])
        cls.cells = [c for c in cls.f34 if c.parity == "even" and c.waits == 0]
        cls.by = {c.id[len("F34-"):-len("-pE-w0")]: c for c in cls.cells}

    def _body(self, label):
        return " ".join(i.code.hex() for i in self.by[label].instrs if i.role == "x")

    def _acc(self, label):
        from validation.v35s.chains.normalize import expected_accesses
        c = self.by[label]
        acc = expected_accesses(c)
        return [(a.kind, a.addr, a.width) for k in sorted(acc) for a in acc[k]
                if c.instrs[k].role == "x"]

    def test_codes_already_run(self):
        from validation.v35s.chains.forms import F34_FORMS
        self.assertEqual(F34_FORMS, ("cmp_aw_dw",))
        self.assertEqual((FORMS["cmp_aw_dw"].cls, FORMS["cmp_aw_dw"].code.hex()), ("reg", "3bc2"))
        others = {bytes(i.code) for f in FAMILIES if f != "F34" for c in generate([f])
                  for i in c.instrs}
        new = {i.form for c in self.f34 for i in c.instrs if bytes(i.code) not in others}
        self.assertEqual(new, {"cmp_aw_dw"})

    def test_counts(self):
        from collections import Counter
        self.assertEqual(len(self.f34), 266 * 6)
        self.assertEqual(Counter((c.marker_kind, c.knobs["probe"]) for c in self.cells),
                         {("out", "empty"): 1, ("out", "lead"): 8, ("out", "bf"): 60,
                          ("out", "rbit"): 37, ("out", "mbit"): 49, ("out", "inc"): 20,
                          ("out", "mul"): 15, ("out", "nt"): 29, ("out", "cr"): 12,
                          ("push", "empty"): 1, ("push", "lead"): 1, ("push", "bf"): 4,
                          ("push", "rbit"): 4, ("push", "mbit"): 4, ("push", "inc"): 3,
                          ("push", "mul"): 3, ("push", "nt"): 7, ("push", "cr"): 8})
        for c in self.f34:
            self.assertEqual(c.rfm, 0xEC, c.id)
            self.assertTrue(c.id.startswith(f"F34-{c.marker_kind}-"), c.id)
            self.assertEqual(c.knobs["marker"], c.marker_kind, c.id)
        for label, c in self.by.items():
            if c.marker_kind == "push":
                self.assertIn(label.replace("push-", "out-", 1), self.by)

    def test_placement_and_knobs(self):
        for label, body in (("out-bf-ext_dl_bh-nop-k2", "90 0f33fa 0f33fa"),
                            ("out-bf-ins_bl_i7-l0-k1-fld", "0f39c307 8b06000c"),
                            ("out-bf-ext_bl_dh-sep-k1", "c1e008 0f33f3"),
                            ("out-rbit-set1_rb_cl-l0-k2-gap", "0f14c0 90 0f14c0"),
                            ("out-rbit-set1_rw_cl-cl-k1", "b104 0f15c0"),
                            ("out-mbit-set1_mw_cl_dir-d-k1", "b83412 0f1506000c"),
                            ("out-inc-inc_aw-l0-k4-n2", "40 40 40 40 90 90"),
                            ("out-mul-mul_aw_m_imm16-nop2-k1", "90 90 69073412"),
                            ("out-nt-be-d3-k1", "b83412 b83412 b83412 3bc2 7400"),
                            ("out-nt-dbnz-nop3-k1", "90 90 90 b90100 e200"),
                            ("out-nt-twin-l0-k1", "3bc0 8bc2"),
                            ("push-nt-bne-nop-k1", "90 3bc0 7500"),
                            ("out-cr-nopshl8-nop", "90 e80200 eb05 90 c1e008 c3"),
                            ("push-cr-shl8-l0", "e80200 eb04 c1e008 c3"),
                            ("out-lead-d2", "b83412 b83412")):
            self.assertEqual(self._body(label), body, label)
        for c in self.cells:
            build_image(c)
            k = c.knobs
            xs_ = [i.form for i in c.instrs if i.role == "x"]
            self.assertEqual(xs_, k["x"], c.id)
            self.assertEqual(xs_[:len(k["lead"])], k["lead"], c.id)
            self.assertEqual(xs_[len(xs_) - len(k["follow"]):], k["follow"], c.id)
            if k["form"]:
                self.assertIn(k["form"], xs_, c.id)
            if k["probe"] == "bf":
                op = "IX" if k["op"] == "ext" else "IY"
                self.assertEqual((c.regs[op], c.regs["DW"]), (0x0A40 if op == "IX" else 0x0C40,
                                                              0x0608), c.id)
            else:
                self.assertEqual(c.regs["DW"], 0x5678, c.id)
            self.assertEqual(c.regs["BW"], 0x0800, c.id)
            self.assertEqual(k["skipped"], 0, c.id)
            self.assertEqual(sorted(k["exec"]), list(range(len(xs_))), c.id)
        # the RET's chain: CALL, the filler, RET, then the BR over them; the target parity
        self.assertEqual(self.by["out-cr-shl8nop-nop"].knobs["exec"], [0, 1, 3, 4, 5, 2])
        self.assertEqual(self.by["out-cr-none-l0"].knobs["exec"], [0, 2, 1])
        self.assertEqual((self.by["out-cr-none-l0"].knobs["target"],
                          self.by["out-cr-none-nop"].knobs["target"]), (3, 4))

    def test_bitfield_walks(self):
        r, w = "data_read", "data_write"
        # EXT DL,BH crosses (offset 8, width 8) then starts again at offset 1 at IX + 2
        self.assertEqual(self._acc("out-bf-ext_dl_bh-nop-k2"),
                         [(r, 0xA40, "word"), (r, 0xA42, "word"), (r, 0xA42, "word")])
        self.assertEqual(self._acc("out-bf-ins_bl_i7-l0-k1-fld"),
                         [(r, 0xC40, "word"), (w, 0xC40, "word"), (r, 0xC00, "word")])
        self.assertEqual(self._acc("out-bf-ext_bl_dh-sep-k1"), [(r, 0xA40, "word")])
        self.assertEqual(self._acc("out-bf-ins_dl_i11-d-k1"),
                         [(r, 0xC40, "word"), (w, 0xC40, "word"), (r, 0xC42, "word"),
                          (w, 0xC42, "word")])
        self.assertEqual(self._acc("out-mbit-clr1_mw_imm-l0-k2-gap"),
                         [(r, 0x800, "word"), (w, 0x800, "word")] * 2)
        self.assertEqual(self._acc("out-nt-be-d3-k1"), [])
        self.assertEqual(self._acc("push-cr-shl8-l0"),
                         [("stack_write", 0x0EFC, "word"), ("stack_read", 0x0EFC, "word")])

    def test_synthetic_runs_normalize(self):
        from validation.v35s.chains.normalize import normalize
        for c in self.cells:
            n = normalize(_synthetic_run(c))
            self.assertIsNone(n.access_mismatch, c.id)
            self.assertEqual(n.checks, [], c.id)
            self.assertEqual(sorted(n.t_markers), [0, 1], c.id)
            self.assertTrue(all(e.instr_index is not None for e in n.events
                                if e.kind != "fetch"), c.id)

    def test_baselines(self):
        from validation.v35s.chains.derive import BASELINES, index_facts, run_facts
        from validation.v35s.chains.normalize import normalize
        metric, base = BASELINES["F34"]
        self.assertEqual(metric, "dM")
        facts = [run_facts(normalize(_synthetic_run(c))) for c in self.cells]
        index = index_facts(facts)
        for f in facts:
            b = base(f, index, None)
            k = f["knobs"]
            if k["probe"] in ("empty", "lead"):
                self.assertIsNone(b, f["id"])
                continue
            self.assertIsNotNone(b, f["id"])
            self.assertEqual((b["marker"], b["column"]), (f["marker"], f["column"]))
            self.assertIsNone(b["knobs"]["form"], f["id"])
            self.assertEqual(b["knobs"]["x"], k["lead"], f["id"])

    def test_simulates_under_the_fit(self):
        from validation.v35s.chains.sim.config import Config
        from validation.v35s.chains.sim.machine import Machine
        from validation.v35s.chains.sim.queue import QUEUE_BYTES
        cfg = Config.fitted()
        for c in self.cells:
            m = Machine(c, cfg)
            m.run()                      # raises on an over-fill or an undecodable form
            self.assertLessEqual(m.queue.peak, QUEUE_BYTES, c.id)

    def test_recorded_runs_classify(self):
        from validation.v35s.chains.normalize import load_runs, normalize
        try:
            runs = load_runs("F34", (0, 1, 2))
        except (FileNotFoundError, ImportError):
            self.skipTest("no recorded F34 runs")
        self.assertEqual(len(runs), 1596)
        for r in runs[::5]:
            n = normalize(r)
            self.assertEqual(n.checks, [], n.run_id)
            self.assertTrue(all(e.instr_index is not None for e in n.events
                                if e.kind not in ("fetch", "refresh")), n.run_id)

    def test_gen_check(self):
        import contextlib
        import io
        from validation.v35s.chains.__main__ import main
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["gen", "--family", "F34", "--check"]), 0)
        self.assertIn("checked 1596 images", out.getvalue())

if __name__ == "__main__":
    unittest.main()
