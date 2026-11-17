# Divergence notes, round 14: re-based on the 6+7 RTL

RTL: the work-order 6+7 batch from main's working tree (2026-11-16), copied into my worktree
file for file, `uasm --check` clean, sim rebuilt. One corpus replay: 30,536 runs, 0 failed,
**20,154 RTL-exact** (the build agent's figure), model-exact 30,361, pre exact 30,536.

## The cross-tab (`tab14.txt`, first table)

By the first-divergence rule (`fd9.py`, with the "partner unread" re-filing of round 11):
10,394 runs diverge; 730 re-filed under an unread partner.

| cause | runs |
|---|---|
| own | 7,242 |
| undetermined | 2,166 |
| predecessor | 263 |
| pair | 222 |
| successor | 124 |

The largest rows: the displaced MOV mem,imm forms (st_imm_bw_d8 265, st_imm_bw_d16 262,
st_imm_dir 168, st_imm_bw_ix_d16 122, st_imm_bw_ix_d8 95: 951 in all), the REP forms (rep_stm_w
205, rep_inm_w 154, rep_movbk_w 153, repe_cmpbk_w 128, rep_outm_w 118, repne_cmpm_w 104,
rep_ldm_w 84: 1,262 in all, mostly "undetermined" because the prefix is one instruction and the
string another), add_dw_imm0 242 (undetermined: the neighbour of other forms), the 0F page
(set1_rw_cl 159, test1_mw_cl 156, add4s 138, ext_bl_dh 114, rol4_dl 108), cmp_m_imm 138 and
cmp_m_imm_d16 120, POP mem with a displacement (516 in all), test_dir_aw 126, ldea_bw 117.

What left the table since the spec-5 rows: the conditional branches and DBNZ, the string
singles, MUL / DIV on a register, the odd-address word operands, the undisplaced memory
immediates, SHL mem,1, the 0F CL forms on a register.

## The split by what the model reads (`tab14.txt`, second table; also at the end of rtl-spec10.md)

| | spec-5 rows (round 13) | 6+7 rows |
|---|---|---|
| diverging, filed | 13,481 | 10,017 |
| read, not built | 11,182 | 8,610 |
| partly read | 1,344 | 1,096 |
| probed, not read | 124 | 12 |
| not probed | 831 | 299 |

- Read, not built (8,610): a little over a third is what the build agent reported unbuilt from
  specs 6 and 7 (displaced MOV mem,imm 951, REP 1,262, displaced POP mem 516, displaced 81 / 83
  forms 384, PUSH R 60); the rest belongs to specs 8, 9 and now 10.
- Not probed went from 831 to 299: this round's small forms (shifts on memory by imm8 / CL, the
  80 group, LDS / LES, MOV mem,sreg and sreg,mem, PUSH imm8, CVTWL) are read, and MUL r,m,imm
  moved from "probed, not read" to read. What is left is small and scattered: cmp_m_aw 24,
  neg_m_bw_d16 21, cvtbd 18, cmp_m_al 18, adj4a 18, adjbs / adjba 24, in_aw_dw 20, test_al_imm
  14, cmpb_m_imm8_82 12, lahf 8, xch_aw_dw 7, cmp_al_imm8 7, pushes of segment registers 4.
- Probed, not read: `sti` 12 (EI). It is read now (13 words, the next opcode on the twelfth),
  but from the interrupt probes, which the model's score does not count.
- Partly read (1,096): forms whose probes the model reproduces only in part; the largest are
  ext_bl_dh 114, mulu_m 102, call_m_dir 96, ext_dl_dh 84, brk3 80, ins_bl_dh 66.

## The build against the model

`build-check.md`: 262 small-set groups in rounds 2 to 11 where the model is exact and the 6+7
RTL is not (the groups of forms that belong to specs 8 and 9 are counted there but not
itemised). Two are not on the builder's unbuilt list: PUSH mem with a
displacement (spec 6 B3; the RTL's read 5 clocks early) and one DBNZ run of six. Two more are
older than the batch (JMP near at even alignment, LEA). Everything else on the list is the five
reported items, sized.

## What the misses of the model are now (rounds 1 to 14 forms)

7,501 / 7,656 in rounds 1 to 11; the misses that have a description but no rule: the 0F forms'
and ADD [d16],imm8's and OUTM's same-instruction-twice cases (Q48: three effects, three
directions), CALL far with waits (12), and the residues of rounds 5, 8 and 9 listed in the earlier
rounds' notes (17, 53 and 82 runs). None of them is a corpus-sized row.
