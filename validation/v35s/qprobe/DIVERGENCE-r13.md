# Round 13 divergence notes: the split again

Same corpus rows (the spec-5 build's replay; 13,481 diverging runs filed under a form), same
method as round 12 (`build/qp/tab12.py`: a form is read when probes of its instruction
signature exist and the model reproduces at least 90 % of the runs that contain it and nothing
unread). No new replay: this worktree's RTL is still the spec-5 build.

| cause | model status | diverging runs | largest forms |
|---|---|---|---|
| own | read | 9033 | pop_m 318, add_m_imm 276, rep_stm_w 273, st_imm_bw_d8 265, st_imm_bw_d16 262, rep_inm_w 221, rep_movbk_w 196, push_m 174 |
| other causes | read | 2149 | add_dw_imm0 242, cmp_aw_aw 167, br_n1 109, shl1 98, ld_bw_ix_d16 88, st_bw_ix_d16 78, shl_imm8 72, shl_imm4 63 |
| own | partly read | 1243 | ext_bl_dh 114, mulu_m 102, call_m_dir 96, ext_dl_dh 84, brk3 80, ins_bl_dh 66, set1_mw_imm 54, clr1_mw_imm 54 |
| own | not probed | 709 | shlb_m_imm4 36, shl_m_imm4 36, orb_m_imm8_80 36, les_aw_ix 36, lds_aw_ix 36, mov_m_ds0 32, push_imm8 24, cvtwl 24 |
| own | probed, not read | 124 | mul_aw_m_imm8 66, mul_aw_m_imm16 58 |
| other causes | not probed | 122 | mov_ds1_m 20, in_aw_dw 20, test_al_imm 14, mov_ss_ix 14, mov_ds1_ix 14, mov_ds0_ix 14, lahf 8, xch_aw_dw 7 |
| other causes | partly read | 101 | br_bw 80, brf_t0053 9, brf_t0057 4, brf_t0054 3, brf_t0052 3, callf_t0053 1, callf_t0051 1 |

total 13481  read 11182

## The three blocks

| block | runs | round 12 |
|---|---|---|
| read, not built (own routine read + other causes on read forms) | 11,182 | 10,218 |
| not read (partly read 1,243 + 101, probed and not read 124) | 1,468 | 1,694 |
| not probed (own 709 + other causes 122) | 831 | 1,569 |

- Moved to "read" this round: CMP mem,imm16, DBNZE / DBNZNE, the mem,imm bit forms, REPC /
  REPNC, the far transfers through memory, RETI, BRK.
- "Partly read" is larger than it looks only because the label is per signature: EXT / INS on a
  register count (the X;X probes fail: their second count is the first's result, not a timing
  miss), MUL / DIV on memory (96 of 144: one frame per form), CALL mem16, SET1 mem,imm 21 of 24.
  Their routines are in spec 9.
- "Probed, not read": MUL r,m,imm (the register form is read; the memory form's frame is not).
- "Not probed" is now small forms: shifts on memory by imm8 / CL, OR mem8,imm8, LDS / LES, MOV
  mem,sreg and sreg,mem, PUSH imm8, CVTWL, IN AW,DW, LAHF.

## RTL (spec-5 build) against the round-13 family probes

852 runs: RTL 193 exact, model 819.
