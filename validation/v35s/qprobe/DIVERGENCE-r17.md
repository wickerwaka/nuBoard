# Divergence notes, round 17

RTL: the work-order 10 to 12 tree, copied from main's working tree (77 files under
`fpga/v35s/core`, `uasm.py`, `test_uasm.py`, `test_v35_struct.py`; checksums
`traces/logs/tree.sha1`). `uasm --check` clean, sim rebuilt, corpus replayed once with
`+v35_chk`: 30,536 runs, 0 FAIL, **25,422 RTL-exact** (the builder's figure), model-exact
(the chain model) 30,361. Cross-tab `traces/logs/tab11.txt`, split `traces/logs/tab12.txt`.

| | round 16 (6+7 tree) | round 17 (10 to 12 tree) |
|---|---|---|
| diverging | 10,017 filed | 5,114 (4,775 filed by form) |
| read, not built | 9,553 | 4,628 |
| partly read | 344 | 85 |
| not probed | 90 | 50 |
| probed, not read | 30 | 12 |

## What the 4,628 "read, not built" are

`tab12` calls a form read when the small set holds the same instruction signature and the
model reproduces 90 % of the runs containing it; the addressing mode is not in the signature.
With that caution, the largest rows and what stands behind each:

| form | diverging / observed | what it is |
|---|---|---|
| br_n1 and the transfers around it (call_n2, ret, reti, brk3 as partners) | 211 / 514 | cause undetermined by the cross-tab; behind CALL / RET / BRK. Not diagnosed this round |
| set1_rw_cl | 156 / 248 | SET1 word r,CL: all 84 "alone" runs differ. The small set's r,CL probes (spec 12 B's row) are exact in the model and were not re-checked against this corpus form; worth one sim trace by the builder |
| shl_imm8, shl_imm4 | 147 / 300, 63 / 196 | pair effects (behind OUT, in front of RET) |
| repe_cmpbk_w, repne_cmpm_w, repc_cmpm_w, repnc_cmpbk_w | 342 | the REP compares: the builder's not-built item (spec 13 B2) |
| test_dir_aw, test_m_imm_d16 | 126 / 156, 118 / 122 | TEST [d16],AW and TEST mem,imm16 with d16: **cells by analogy, mode not probed** (TEST [BW],r and TEST [BW],imm16 are); candidates for A1's rule or for a per-mode shape as LEA was |
| st_imm_bw_d16, st_imm_dir, st_imm_bw_ix_d16 | 107 / 428, 68 / 272, 100 / 186 | C7 with d16: W = 0 is Q33 fact 2 (not built: 148 of the 175 on the first two rows), W = 2 the armed-after-the-decision miss (build-check item 1); the two-register d16 mode not probed |
| pop_m_bw_ix_d16 | 96 / 96 | POP [BW+IX+d16]: not probed in this mode (d8 and direct are) |
| add_m_imm_d16, add_m_imm_dir | 70 / 187, 53 / 159 | Q69 / spec 13 A1: the read obeys Q33's table |
| ldea with a displacement | 159 / 372 | Q68 / spec 13 B: five words in every mode |

## Partly read, not probed, probed and not read

- add_m_imm8_d16 (40): probed this round (39 of 42 with the direct form's shape); it stays
  under 90 % only through the INC BW artefact runs.
- neg_m_bw_d16 21, far transfers 16 + 5, mul_aw_cw_imm8 1: as round 16; not advanced.
- Not probed: cvtdb 11, retf_imm2 10, cli 10, adj4s 6, the prefixed 0F forms 9, PUSH sreg 4.
- sti 12: "probed, not read" only because the signature's small-set programs are the
  interrupt frames the model does not simulate; EI's routine itself is read (13 clocks).

## The model's misses now (form probes, 562 of 12,396)

330 are the interrupt-frame programs the model does not simulate. Of the other 232: round
16's list (Q42's residue behind MOV mem,imm16 about 60, MUL r,r,imm8 at two waits 20, the
far transfers 16, the transfers' frame misses 11, ADD [d16],imm8 back to back 9, EXT r,imm4 7,
NEG d16 5, older singles) plus this round's: the INC BW artefact (24), the d16 forms' second
instance (5), CVTBD behind MOV BW,imm16 (3). CVTBD's 24 round-15 runs left the list.

## Build check

`build-check.md`: 97 groups where the model is exact and the RTL is not (r9 16, r10b 1, r11b
16, r11c 16, r12 2, r13a 39, r16a 7; folded to 47 forms), separated into seven items that are
not on the builder's not-built list and three that are; the three named diagnoses (C7 at odd
alignment W = 2 to the word; add_m_imm_d16; the interrupt-probe losses) are there.
