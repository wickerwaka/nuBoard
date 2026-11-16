# Round 11 divergence notes: the cross-tab on the spec-5 corpus, "partner unread" applied

Data: a fresh corpus replay of this worktree's RTL after copying the nine spec-5 files from the
main tree (`build/qp/replay11.sh`; replay 0 failures, score 16,673 of 30,536 exact, the
coordinator's number). First divergences by `build/qp/fd9.py` (file `fd11.jsonl` here; its own
equality test counts 16,661 equal, 12 fewer than the scorer: it compares one more field).
Cross-tab by `build/qp/tab11.py`, which is `tab9.py` plus the caution raised in round 10:

1. **U, the forms that fail by themselves**: a form whose runs diverge at >= 70 % over the
   chains in which it is the only instruction (markers, NOPs, pads aside; >= 6 such runs), or,
   when it was never measured alone, a form >= 90 % of whose runs diverge (>= 12 runs).
2. A diverging run whose positional subject X is not in U, with an instruction of a form in U
   inside the fetched window, is **re-filed under that instruction** ("partner unread"), not
   under X as predecessor / successor / pair.

13,875 diverging runs; 940 re-filed. Columns "moved in" / "moved away" give the re-filed runs
per form; "alone" is the form's own-chain rate (- when never measured alone).

What the caution changed against round 9's table: the predecessor + successor + pair total falls
from 1,902 to 822 of the diverging runs (part of that is spec 5's Q23, part the re-filing);
inc_m keeps 10 of its 136 (108 re-filed to its partners, the rest fixed by spec 5); cmp_aw_aw and
cmp_aw_dw give 80 and 82 runs to the DBNZ behind them, and what they keep (167, 50) sits in
front of Jcc, which passes alone at W = 0 and so is not in U: those are the branch's runs too
(spec 6 A2 / B1).

## By family (own-routine families by diverging runs: where the next reading should go)

"read" = the model has the family as of round 11 (the probes named); the RTL does not yet.

| family | diverging runs | largest forms | status |
|---|---|---|---|
| other | 2092 | cmp_aw_aw 167, shl1 98, in_al_dw 54, cmp_aw_dw 50 | - |
| REP strings | 1575 | rep_stm_w 273, rep_inm_w 221, rep_movbk_w 196, rep_outm_w 173 | read: Q35 (660 probe runs) |
| ALU / CMP / TEST memory,imm | 1318 | add_m_imm 276, add_m_imm_d16 144, cmp_m_imm 138, test_m_imm_d16 120 | read: Q29 (round 10); [d16] twice in a row open |
| 0F bit forms | 1065 | set1_rw_cl 159, test1_mw_cl 156, set1_mw_cl 72, set1_mw_cl_bw_ix 60 | register CL forms read (Q31); memory and imm8 forms not |
| MOV memory,imm (disp, byte) | 1060 | st_imm_bw_d8 265, st_imm_bw_d16 262, st_imm_dir 168, st_imm_bw_ix_d16 122 | read: Q33 |
| POP memory | 984 | pop_m 318, pop_m_dir 138, pop_m_d8 138, pop_m_bw_ix_d8 96 | read: Q30, Q33 |
| EXT / INS | 672 | ext_bl_dh 114, ext_dl_dh 84, ext_bl_i7 78, ins_bl_i7 66 | not read (data in round 9) |
| MUL / DIV | 620 | mulu_m 102, mulu_aw 84, mul_aw_m_imm8 66, mul_cw 60 | register forms read (Q36); memory and imm forms not acquired |
| CALL / RET / BRK / JMP forms | 586 | call_m_dir 96, brk3 80, br_bw 80, ret_imm0 36 | mostly read (Q21); CALL mem, BRK 3 routine partly |
| ADD r16,imm (81 /0) | 468 | add_dw_imm0 242, add_dw_imm2a01 120, add_dw_imm 106 | not probed: the ModR/M immediate form on a register |
| single strings | 408 | stm_w 72, movbk_w 72, inm_w 72, cmpbk_w 72 | read: Q34 |
| Jcc | 393 | br_n1 109, be_n0 52, br_n2 19, br_n0 19 | read: Q27 (round 10) |
| loads / stores with base+index+d16 | 322 | ld_bw_ix_d16 88, st_bw_ix_d16 78, ld_bp_iy_d16 62, add_m_aw_bw_ix_d16 62 | read (Q18: one word longer); RTL reverted it |
| shift memory | 318 | shl_m1 132, shl_m_imm4 36, shl_m1_bw_d16 24, shr_m1 18 | SHL mem,1 read this round; by CL / imm8 not |
| DBNZ / BCWZ / LOOP | 316 | dbnz_n0 134, dbnze_n0 82, dbnzne_n0 46, bcwz_n0 22 | read: Q27, Q28 (round 10) |
| BCD strings (ADD4S ...) | 216 | add4s 138, cmp4s 42, sub4s 36 | not probed |
| TEST mem,r | 207 | test_dir_aw 126, test_m_aw 48, test_m_aw_bw_d16 27, test_m_al 6 | read: Q25 (round 9) |
| LEA | 202 | ldea_bw 75, ldea_bw_ix 29, ldea_bw_ix_d16 20, ldea_bw_iy_d16 8 | read (Q20); the RTL's head cannot express it |
| shift r,imm8 | 183 | shl_imm8 72, shl_imm4 63, shl_imm2 11, shl_imm1 11 | read: Q24 / round 9 (201 of 210) |
| PUSH memory | 174 | push_m 174 | read: Q30 |
| ROL4 / ROR4 | 156 | rol4_dl 108, ror4_dl 18, rol4_m 18, ror4_m 12 | not read |
| PREPARE / DISPOSE / PUSH R | 120 | push_r 60, prepare_00 60 | PUSH R / POP R read this round; PREPARE not |
| XCH mem | 26 | xch_m_aw 10, xch_dir_aw 9, xch_aw_dw 7 | read: Q25 |

## RTL (spec-5 build) against the round-11 probes

| group | runs | RTL exact | model |
|---|---|---|---|
| r11a odd-address operands (and byte controls) | 192 | 102 | 192 |
| r11b write against the chained fetch | 420 | 73 | 420 |
| r11c OUTM single, REP forms | 468 | 0 | 466 |
| r11d MUL / DIV on registers | 288 | 144 | 288 |
| all | 1,368 | 319 | 1,366 |

## Causes

runs 30536, equal 16661, diverging 13875; re-filed as partner unread: 940

| cause | runs |
|---|---|
| own | 11109 |
| undetermined | 1550 |
| pair | 355 |
| predecessor | 273 |
| successor | 194 |

## By form (the 120 largest)


| form | misses at it / observed | alone | cause | moved in (as the unread partner) | moved away | by predecessor (misses/observed) | by successor | by wait+parity |
|---|---|---|---|---|---|---|---|---|
| pop_m | 318 / 318 | 300/300 | own | 0 | 0 | nop 114/114, M:push 72/72, M:out 72/72, LS 42/42 | M:push 84/84, M:out 78/78, pop_m 60/60, LS 60/60 | w0e 53/53, w0o 53/53, w1e 53/53, w1o 53/53, w2e 53/53, w2o 53/53 |
| add_m_imm | 276 / 276 | 276/276 | own | 0 | 0 | nop 114/114, M:push 56/56, M:out 50/50, pfx_nop 42/42 | add_m_imm 90/90, M:push 74/74, M:out 74/74, LS 38/38 | w0e 56/56, w0o 56/56, w1e 56/56, w1o 56/56, w2e 26/26, w2o 26/26 |
| rep_stm_w | 273 / 282 | - | own | 15 | 0 | mov_cw_imm1 84/84, nop 57/60, mov_cw_imm2 54/54, mov_cw_imm0 12/18 | M:out 201/210, nop 24/24, mov_cw_imm1 24/24, mov_aw_dw 12/12 | w0e 47/47, w0o 47/47, w1e 45/47, w1o 47/47, w2e 44/47, w2o 43/47 |
| st_imm_bw_d8 | 265 / 324 | 265/306 | own | 0 | 0 | nop 142/162, pfx_nop 56/60, M:push 20/32, M:out 22/32 | M:out 69/89, M:push 74/87, st_imm_bw_d8 66/84, LS 56/64 | w1e 39/69, w1o 44/69, w0e 61/61, w0o 61/61, w2o 29/33, w2e 31/31 |
| st_imm_bw_d16 | 262 / 366 | 262/342 | own | 0 | 0 | nop 104/162, pfx_nop 36/60, M:push 34/50, M:out 50/50 | st_imm_bw_d16 84/108, M:push 72/99, M:out 62/92, LS 44/67 | w1o 43/79, w1e 43/75, w0e 67/67, w0o 67/67, w2o 21/41, w2e 21/37 |
| add_dw_imm0 | 242 / 486 | - | undetermined | 0 | 0 | nop 44/132, M:push 30/90, M:out 84/84, D 24/72 | out_dw_b 44/90, ld_bw 32/72, st_bw 32/72, mov_aw_dw 32/72 | w0e 81/81, w0o 81/81, w1e 14/81, w1o 26/81, w2e 14/81, w2o 26/81 |
| rep_inm_w | 221 / 228 | - | own | 15 | 0 | mov_cw_imm1 78/78, nop 57/60, mov_cw_imm2 30/30, mov_cw_imm0 14/18 | M:out 173/180, nop 12/12, mov_aw_dw 12/12, ld_bw 12/12 | w0e 38/38, w0o 38/38, w1e 38/38, w1o 38/38, w2e 35/38, w2o 34/38 |
| rep_movbk_w | 196 / 198 | - | own | 0 | 0 | mov_cw_imm1 90/90, mov_cw_imm2 42/42, mov_cw_imm4 30/30, D 12/12 | M:out 148/150, nop 12/12, mov_aw_dw 12/12, ld_bw 12/12 | w0e 33/33, w0o 33/33, w1e 32/33, w1o 33/33, w2e 33/33, w2o 32/33 |
| push_m | 174 / 174 | 132/132 | own | 12 | 0 | M:push 84/84, M:out 54/54, LS 24/24, inc_m 12/12 | push_m 72/72, M:push 36/36, M:out 24/24, pop_m 18/18 | w0e 29/29, w0o 29/29, w1e 29/29, w1o 29/29, w2e 29/29, w2o 29/29 |
| rep_outm_w | 173 / 180 | - | own | 15 | 0 | nop 57/60, mov_cw_imm1 30/30, mov_cw_imm2 30/30, mov_cw_imm0 14/18 | M:out 173/180 | w0e 30/30, w0o 30/30, w1e 30/30, w1o 30/30, w2e 27/30, w2o 26/30 |
| st_imm_dir | 168 / 234 | 168/216 | own | 0 | 0 | nop 80/120, pfx_nop 26/42, M:push 14/20, M:out 20/20 | st_imm_dir 54/72, M:push 42/57, M:out 38/56, LS 34/49 | w1o 30/55, w1e 30/54, w0e 46/46, w0o 46/46, w2o 8/17, w2e 8/16 |
| cmp_aw_aw | 167 / 952 | 0/24 | undetermined | 0 | 80 | M:out 56/444, M:push 99/348, nop 6/42, mov_aw_imm 6/36 | bne_n0 52/304, be_n0 48/144, mov_aw_dw 0/48, M:push 0/24 | w0e 6/159, w0o 1/159, w1e 28/159, w2e 28/159, w1o 52/158, w2o 52/158 |
| set1_rw_cl | 159 / 248 | 84/84 | own | 38 | 0 | M:out 16/72, M:push 24/48, set1_rw_cl 33/33, nop 23/29 | M:out 82/92, set1_rw_cl 18/51, M:push 36/39, ld_bw 3/12 | w1e 24/43, w2e 24/43, w0e 24/42, w0o 28/40, w1o 31/40, w2o 28/40 |
| test1_mw_cl | 156 / 156 | 84/84 | own | 3 | 0 | M:out 72/72, M:push 54/54, nop 18/18, mov_aw_imm 6/6 | M:out 36/36, test1_mw_cl 36/36, M:push 18/18, ld_bw 12/12 | w0e 26/26, w0o 26/26, w1e 26/26, w1o 26/26, w2e 26/26, w2o 26/26 |
| add_m_imm_d16 | 144 / 144 | 144/144 | own | 0 | 0 | nop 72/72, pfx_nop 24/24, M:push 20/20, M:out 20/20 | add_m_imm_d16 72/72, M:push 26/26, M:out 26/26, LS 20/20 | w0e 34/34, w0o 34/34, w1e 34/34, w1o 34/34, w2e 4/4, w2o 4/4 |
| pop_m_dir | 138 / 138 | 138/138 | own | 0 | 0 | nop 66/66, M:push 24/24, M:out 18/18, pfx_nop 18/18 | M:push 60/60, M:out 36/36, LS 30/30, pop_m_dir 12/12 | w0e 23/23, w0o 23/23, w1e 23/23, w1o 23/23, w2e 23/23, w2o 23/23 |
| pop_m_d8 | 138 / 138 | 138/138 | own | 0 | 0 | nop 66/66, M:push 24/24, M:out 18/18, pfx_nop 18/18 | M:push 60/60, M:out 36/36, LS 30/30, pop_m_d8 12/12 | w0e 23/23, w0o 23/23, w1e 23/23, w1o 23/23, w2e 23/23, w2o 23/23 |
| cmp_m_imm | 138 / 138 | 138/138 | own | 0 | 0 | nop 42/42, M:push 36/36, M:out 36/36, pfx_nop 18/18 | M:push 48/48, M:out 48/48, cmp_m_imm 24/24, LS 18/18 | w0e 23/23, w0o 23/23, w1e 23/23, w1o 23/23, w2e 23/23, w2o 23/23 |
| add4s | 138 / 138 | - | own | 69 | 0 | mov_cl2 108/108, mov_cl_imm 18/18, mov_cl8 6/6, mov_cl16 6/6 | add4s 36/36, M:out 30/30, M:push 12/12, ld_bw 12/12 | w0e 23/23, w0o 23/23, w1e 23/23, w1o 23/23, w2e 23/23, w2o 23/23 |
| dbnz_n0 | 134 / 138 | - | own | 67 | 0 | mov_cw_imm1 126/126, mov_cw_imm2 8/12 | M:out 58/60, nop 36/36, M:push 28/30, mov_cw_imm1 12/12 | w0e 23/23, w0o 23/23, w1e 23/23, w1o 23/23, w2e 21/23, w2o 21/23 |
| shl_m1 | 132 / 132 | 108/108 | own | 12 | 0 | M:push 72/72, M:out 36/36, inc_m 12/12, nop 12/12 | M:push 42/42, M:out 42/42, shl_m1 30/30, nop 6/6 | w0e 22/22, w0o 22/22, w1e 22/22, w1o 22/22, w2e 22/22, w2o 22/22 |
| repe_cmpbk_w | 128 / 130 | - | own | 0 | 0 | mov_cw_imm1 66/66, mov_cw_imm2 32/32, mov_cw_imm4 14/14, mov_cw_imm0 4/6 | M:out 92/94, nop 12/12, mov_aw_dw 12/12, ld_bw 12/12 | w1o 23/23, w2o 22/23, w0e 21/21, w0o 21/21, w1e 20/21, w2e 21/21 |
| test_dir_aw | 126 / 156 | 126/138 | own | 3 | 0 | nop 51/60, M:push 21/42, M:out 36/36, test_dir_aw 12/12 | test_dir_aw 45/57, M:out 51/57, M:push 30/42 | w0e 18/28, w1e 18/28, w2e 18/28, w0o 24/24, w1o 24/24, w2o 24/24 |
| st_imm_bw_ix_d16 | 122 / 174 | 122/156 | own | 0 | 0 | nop 40/72, M:push 20/30, M:out 30/30, pfx_nop 10/18 | st_imm_bw_ix_d16 44/62, M:push 34/46, M:out 30/42, LS 14/24 | w1o 17/32, w2o 17/32, w1e 18/29, w2e 18/29, w0e 26/26, w0o 26/26 |
| test_m_imm_d16 | 120 / 120 | 120/120 | own | 0 | 0 | nop 72/72, pfx_nop 24/24, M:push 8/8, M:out 8/8 | test_m_imm_d16 60/60, M:push 20/20, M:out 20/20, LS 20/20 | w0e 30/30, w0o 30/30, w1e 30/30, w1o 30/30 |
| cmp_m_imm_d16 | 120 / 120 | 120/120 | own | 0 | 0 | nop 72/72, pfx_nop 24/24, M:push 8/8, M:out 8/8 | cmp_m_imm_d16 60/60, M:push 20/20, M:out 20/20, LS 20/20 | w0e 30/30, w0o 30/30, w1e 30/30, w1o 30/30 |
| add_m_imm_dir | 120 / 120 | 120/120 | own | 0 | 0 | nop 72/72, pfx_nop 24/24, M:push 8/8, M:out 8/8 | add_m_imm_dir 60/60, M:push 20/20, M:out 20/20, LS 20/20 | w0e 30/30, w0o 30/30, w1e 30/30, w1o 30/30 |
| add_m_imm_d8 | 120 / 120 | 120/120 | own | 0 | 0 | nop 72/72, pfx_nop 24/24, M:push 8/8, M:out 8/8 | add_m_imm_d8 60/60, M:push 20/20, M:out 20/20, LS 20/20 | w0e 30/30, w0o 30/30, w1e 30/30, w1o 30/30 |
| add_dw_imm2a01 | 120 / 156 | 10/12 | own | 0 | 0 | M:out 102/102, M:push 18/54 | bv_n0 8/12, bnv_n0 8/12, bnh_n0 8/12, bh_n0 8/12 | w0e 26/26, w0o 26/26, w1e 17/26, w1o 17/26, w2e 17/26, w2o 17/26 |
| rep_ldm_w | 118 / 120 | - | own | 0 | 0 | mov_cw_imm1 72/72, mov_cw_imm2 18/18, mov_cw_imm4 12/12, mov_cw_imm0 4/6 | M:out 70/72, nop 12/12, mov_aw_dw 12/12, ld_bw 12/12 | w0e 20/20, w0o 20/20, w1e 19/20, w1o 20/20, w2e 20/20, w2o 19/20 |
| add_m_imm8_d16 | 118 / 122 | 118/120 | own | 0 | 0 | nop 72/72, pfx_nop 24/24, M:push 8/8, M:out 4/8 | add_m_imm8_d16 58/60, M:out 20/22, M:push 20/20, LS 20/20 | w0o 29/31, w1o 29/31, w0e 30/30, w1e 30/30 |
| ext_bl_dh | 114 / 114 | 54/54 | own | 3 | 0 | M:out 54/54, nop 24/24, M:push 24/24, mov_aw_imm 6/6 | M:out 36/36, mov_aw_dw 18/18, ext_bl_dh 12/12, M:push 12/12 | w0e 19/19, w0o 19/19, w1e 19/19, w1o 19/19, w2e 19/19, w2o 19/19 |
| br_n1 | 109 / 324 | 13/36 | undetermined | 0 | 31 | call_n2 97/247, M:out 9/18, callf_t0054 0/18, callf_t0053 0/9 | ret 97/247, retf 0/41, nop 12/36 | w0o 14/60, w0e 14/57, w1e 27/52, w1o 21/52, w2o 17/52, w2e 16/51 |
| rol4_dl | 108 / 108 | 48/48 | own | 0 | 0 | M:out 60/60, M:push 48/48 | rol4_dl 30/30, M:out 12/12, ld_bw 12/12, st_bw 12/12 | w0e 18/18, w0o 18/18, w1e 18/18, w1o 18/18, w2e 18/18, w2o 18/18 |
| add_dw_imm | 106 / 190 | 90/126 | own | 14 | 0 | nop 48/90, LS 20/30, M:push 8/24, M:out 18/18 | LS 38/60, out_imm_al 28/48, M:push 14/38, add_dw_imm 16/32 | w1e 10/33, w1o 14/33, w2e 10/33, w2o 14/33, w0e 29/29, w0o 29/29 |
| repne_cmpm_w | 104 / 106 | - | own | 0 | 0 | mov_cw_imm1 54/54, mov_cw_imm2 20/20, mov_cw_imm4 14/14, mov_cw_imm0 4/6 | M:out 68/70, nop 12/12, mov_aw_dw 12/12, ld_bw 12/12 | w1o 19/19, w2o 18/19, w0e 17/17, w0o 17/17, w1e 16/17, w2e 17/17 |
| mulu_m | 102 / 102 | 78/78 | own | 12 | 0 | M:push 60/60, M:out 30/30, inc_m 12/12 | mulu_m 36/36, M:push 30/30, M:out 18/18, nop 6/6 | w0e 17/17, w0o 17/17, w1e 17/17, w1o 17/17, w2e 17/17, w2o 17/17 |
| shl1 | 98 / 214 | 58/114 | pair | 0 | 0 | M:out 72/72, M:push 22/66, nop 4/36, LS 0/24 | M:push 8/38, nop 24/36, shl1 16/32, M:out 26/30 | w0e 12/37, w0o 12/37, w1o 12/37, w2o 12/37, w1e 25/33, w2e 25/33 |
| pop_m_bw_ix_d8 | 96 / 96 | 96/96 | own | 0 | 0 | nop 48/48, pfx_nop 18/18, M:push 12/12, M:out 12/12 | M:push 30/30, M:out 30/30, LS 24/24, pop_m_bw_ix_d8 12/12 | w0e 16/16, w0o 16/16, w1e 16/16, w1o 16/16, w2e 16/16, w2o 16/16 |
| pop_m_bw_ix_d16 | 96 / 96 | 96/96 | own | 0 | 0 | nop 48/48, pfx_nop 18/18, M:push 12/12, M:out 12/12 | M:push 30/30, M:out 30/30, LS 24/24, pop_m_bw_ix_d16 12/12 | w0e 16/16, w0o 16/16, w1e 16/16, w1o 16/16, w2e 16/16, w2o 16/16 |
| pop_m_bw_d16 | 96 / 96 | 96/96 | own | 0 | 0 | nop 48/48, pfx_nop 18/18, M:push 12/12, M:out 12/12 | M:push 30/30, M:out 30/30, LS 24/24, pop_m_bw_d16 12/12 | w0e 16/16, w0o 16/16, w1e 16/16, w1o 16/16, w2e 16/16, w2o 16/16 |
| call_m_dir | 96 / 96 | - | own | 44 | 0 | st_acc_dir 84/84, nop 12/12 | br_n1 72/72, M:out 12/12, M:push 12/12 | w0e 16/16, w0o 16/16, w1e 16/16, w1o 16/16, w2e 16/16, w2o 16/16 |
| st_imm_bw_ix_d8 | 95 / 116 | 95/108 | own | 0 | 0 | nop 43/48, M:push 12/18, pfx_nop 17/18, M:out 12/18 | M:push 29/34, M:out 28/34, st_imm_bw_ix_d8 16/24, LS 22/24 | w1o 12/22, w1e 12/20, w2o 17/20, w0e 18/18, w0o 18/18, w2e 18/18 |
| cmp_m_imm8 | 90 / 90 | 90/90 | own | 0 | 0 | nop 42/42, pfx_nop 18/18, M:push 12/12, M:out 12/12 | M:push 30/30, M:out 30/30, LS 18/18, cmp_m_imm8 12/12 | w0e 15/15, w0o 15/15, w1e 15/15, w1o 15/15, w2e 15/15, w2o 15/15 |
| st_imm8_bw | 88 / 90 | 88/90 | own | 0 | 0 | nop 42/42, pfx_nop 18/18, M:push 12/12, M:out 10/12 | M:push 30/30, M:out 28/30, LS 18/18, st_imm8_bw 12/12 | w0e 15/15, w0o 15/15, w1e 14/15, w1o 15/15, w2e 14/15, w2o 15/15 |
| ld_bw_ix_d16 | 88 / 134 | 88/132 | undetermined | 0 | 0 | nop 38/66, M:out 24/24, M:push 12/18, pfx_nop 10/18 | M:out 40/60, M:push 24/38, LS 14/24, ld_bw_ix_d16 10/12 | w1o 10/23, w2o 10/23, w0e 22/22, w0o 22/22, w1e 12/22, w2e 12/22 |
| pop_m_bw_ix | 84 / 84 | 84/84 | own | 0 | 0 | nop 48/48, pfx_nop 18/18, M:push 6/6, M:out 6/6 | M:push 30/30, M:out 30/30, LS 24/24 | w0e 14/14, w0o 14/14, w1e 14/14, w1o 14/14, w2e 14/14, w2o 14/14 |
| mulu_aw | 84 / 90 | 84/90 | own | 0 | 0 | nop 30/36, M:push 30/30, M:out 24/24 | M:push 31/36, M:out 35/36, nop 12/12, mulu_aw 6/6 | w0e 14/15, w0o 12/15, w1e 15/15, w1o 14/15, w2e 15/15, w2o 14/15 |
| ext_dl_dh | 84 / 84 | 24/24 | own | 0 | 0 | M:out 48/48, M:push 36/36 | M:out 12/12, ld_bw 12/12, st_bw 12/12, push_aw 12/12 | w0e 14/14, w0o 14/14, w1e 14/14, w1o 14/14, w2e 14/14, w2o 14/14 |
| dbnze_n0 | 82 / 84 | - | own | 82 | 0 | cmp_aw_dw 60/60, cmp_aw_aw 22/24 | M:out 29/30, M:push 29/30, dbnze_n0 24/24 | w0e 14/14, w0o 14/14, w1e 14/14, w1o 14/14, w2e 13/14, w2o 13/14 |
| brk3 | 80 / 80 | - | own | 74 | 0 | st_acc_000e 70/70, nop 10/10 | br_n1 70/70, br_n2 10/10 | w1e 16/16, w1o 16/16, w2e 16/16, w2o 16/16, w0e 8/8, w0o 8/8 |
| br_bw | 80 / 116 | - | successor | 0 | 10 | mov_bw_t0052 31/51, mov_bw_t0053 25/30, mov_bw_t0051 21/24, mov_bw_t0057 0/4 | nop 20/24, push_aw 10/12, out_imm_al 10/12, set1_rw_cl 0/12 | w2e 8/22, w2o 8/22, w0e 16/18, w0o 16/18, w1e 16/18, w1o 16/18 |
| st_bw_ix_d16 | 78 / 122 | 78/120 | undetermined | 0 | 0 | nop 38/66, pfx_nop 10/18, M:out 18/18, M:push 8/12 | M:out 34/54, M:push 20/32, LS 14/24, st_bw_ix_d16 10/12 | w1o 9/21, w2o 9/21, w0e 20/20, w0o 20/20, w1e 10/20, w2e 10/20 |
| ext_bl_i7 | 78 / 78 | 54/54 | own | 3 | 0 | M:out 36/36, nop 24/24, mov_aw_imm 6/6, shl_imm8 6/6 | M:out 36/36, ext_bl_i7 12/12, M:push 12/12, ld_dir 6/6 | w0e 13/13, w0o 13/13, w1e 13/13, w1o 13/13, w2e 13/13, w2o 13/13 |
| ldea_bw | 75 / 99 | 77/96 | own | 0 | 0 | M:push 21/30, M:out 18/30, nop 10/12, D 11/12 | M:push 36/39, M:out 21/36, ldea_bw 9/12, nop 9/12 | w0e 12/17, w1e 11/17, w2e 12/17, w0o 16/16, w1o 11/16, w2o 13/16 |
| stm_w | 72 / 72 | 24/24 | own | 0 | 0 | M:out 42/42, M:push 30/30 | M:out 12/12, ld_bw 12/12, push_aw 12/12, out_imm_al 12/12 | w0e 12/12, w0o 12/12, w1e 12/12, w1o 12/12, w2e 12/12, w2o 12/12 |
| shl_imm8 | 72 / 300 | 14/54 | pair | 0 | 105 | M:out 6/132, br_n4 30/36, nop 18/30, br_n5 16/24 | ret 42/48, LS 6/36, nop 16/24, rep_inm_w 0/18 | w0e 9/50, w0o 7/50, w1e 14/50, w1o 11/50, w2e 17/50, w2o 14/50 |
| set1_mw_cl | 72 / 72 | 60/60 | own | 3 | 0 | M:out 30/30, nop 18/18, M:push 12/12, mov_aw_imm 6/6 | M:out 36/36, M:push 18/18, set1_mw_cl 12/12, nop 6/6 | w0e 12/12, w0o 12/12, w1e 12/12, w1o 12/12, w2e 12/12, w2o 12/12 |
| movbk_w | 72 / 72 | 24/24 | own | 0 | 0 | M:out 42/42, M:push 30/30 | M:out 12/12, ld_bw 12/12, push_aw 12/12, out_imm_al 12/12 | w0e 12/12, w0o 12/12, w1e 12/12, w1o 12/12, w2e 12/12, w2o 12/12 |
| inm_w | 72 / 72 | 24/24 | own | 0 | 0 | M:out 42/42, M:push 30/30 | M:out 12/12, ld_bw 12/12, push_aw 12/12, out_imm_al 12/12 | w0e 12/12, w0o 12/12, w1e 12/12, w1o 12/12, w2e 12/12, w2o 12/12 |
| cmpbk_w | 72 / 72 | 24/24 | own | 0 | 0 | M:out 42/42, M:push 30/30 | M:out 12/12, ld_bw 12/12, push_aw 12/12, out_imm_al 12/12 | w0e 12/12, w0o 12/12, w1e 12/12, w1o 12/12, w2e 12/12, w2o 12/12 |
| mul_aw_m_imm8 | 66 / 66 | 54/54 | own | 3 | 0 | M:out 24/24, nop 24/24, mov_aw_imm 6/6, shl_imm8 6/6 | M:out 36/36, mul_aw_m_imm8 18/18, M:push 12/12 | w0e 11/11, w0o 11/11, w1e 11/11, w1o 11/11, w2e 11/11, w2o 11/11 |
| ins_bl_i7 | 66 / 66 | 42/42 | own | 3 | 0 | M:out 36/36, nop 18/18, mov_aw_imm 6/6, shl_imm8 6/6 | M:out 36/36, ins_bl_i7 12/12, ld_dir 6/6, nop 6/6 | w0e 11/11, w0o 11/11, w1e 11/11, w1o 11/11, w2e 11/11, w2o 11/11 |
| ins_bl_dh | 66 / 66 | 42/42 | own | 3 | 0 | M:out 36/36, nop 18/18, mov_aw_imm 6/6, shl_imm8 6/6 | M:out 36/36, ins_bl_dh 12/12, ld_dir 6/6, nop 6/6 | w0e 11/11, w0o 11/11, w1e 11/11, w1o 11/11, w2e 11/11, w2o 11/11 |
| shl_imm4 | 63 / 196 | 51/150 | pair | 0 | 0 | nop 16/48, M:push 14/42, M:out 21/42, shl_imm4 0/28 | LS 18/66, M:push 10/38, shl_imm4 10/38, M:out 15/36 | w0o 2/36, w1o 4/36, w2o 8/36, w0e 8/32, w1e 19/28, w2e 22/28 |
| ld_bp_iy_d16 | 62 / 96 | 62/96 | undetermined | 0 | 0 | nop 28/48, pfx_nop 10/18, M:push 8/12, M:out 12/12 | M:push 24/36, M:out 24/36, LS 14/24 | w0e 16/16, w0o 16/16, w1e 8/16, w1o 7/16, w2e 8/16, w2o 7/16 |
| add_m_aw_bw_ix_d16 | 62 / 98 | 62/96 | undetermined | 0 | 0 | nop 28/48, pfx_nop 10/18, M:push 8/12, M:out 12/12 | M:push 20/32, M:out 18/30, LS 14/24, add_m_aw_bw_ix_d16 10/12 | w1o 7/17, w2o 7/17, w0e 16/16, w0o 16/16, w1e 8/16, w2e 8/16 |
| set1_mw_cl_bw_ix | 60 / 60 | 54/54 | own | 0 | 0 | M:out 30/30, M:push 18/18, nop 6/6, mov_aw_imm 6/6 | M:out 30/30, set1_mw_cl_bw_ix 24/24, M:push 6/6 | w0e 10/10, w0o 10/10, w1e 10/10, w1o 10/10, w2e 10/10, w2o 10/10 |
| push_r | 60 / 60 | 12/12 | own | 0 | 0 | M:push 30/30, M:out 30/30 | pop_r 48/48, M:push 6/6, M:out 6/6 | w0e 10/10, w0o 10/10, w1e 10/10, w1o 10/10, w2e 10/10, w2o 10/10 |
| prepare_00 | 60 / 60 | 12/12 | own | 0 | 0 | M:push 30/30, M:out 30/30 | dispose 48/48, M:push 6/6, M:out 6/6 | w0e 10/10, w0o 10/10, w1e 10/10, w1o 10/10, w2e 10/10, w2o 10/10 |
| mul_cw | 60 / 60 | 42/42 | own | 0 | 0 | M:out 24/24, mov_dw_imm0 18/18, M:push 18/18 | mul_cw 30/30, M:out 18/18, M:push 12/12 | w0e 10/10, w0o 10/10, w1e 10/10, w1o 10/10, w2e 10/10, w2o 10/10 |
| mul_aw_m_imm16 | 58 / 62 | 46/48 | own | 3 | 0 | M:out 20/24, nop 18/18, mov_aw_imm 6/6, shl_imm8 6/6 | M:out 36/38, mul_aw_m_imm16 16/18, M:push 6/6 | w2e 8/12, w0e 10/10, w0o 10/10, w1e 10/10, w1o 10/10, w2o 10/10 |
| set1_rb_cl | 56 / 86 | 48/48 | own | 3 | 0 | M:out 9/30, nop 17/23, set1_rb_cl 15/15, mov_aw_imm 3/6 | M:out 52/62, set1_rb_cl 3/18, nop 1/6 | w1e 9/15, w2e 9/15, w0e 9/14, w0o 9/14, w1o 11/14, w2o 9/14 |
| set1_mw_imm | 54 / 54 | 42/42 | own | 5 | 0 | M:out 30/30, nop 12/12, mov_aw_imm 6/6, shl_imm8 6/6 | M:out 36/36, set1_mw_imm 12/12, nop 6/6 | w0e 9/9, w0o 9/9, w1e 9/9, w1o 9/9, w2e 9/9, w2o 9/9 |
| in_al_dw | 54 / 285 | 46/90 | pair | 0 | 0 | nop 11/65, M:push 15/30, M:out 24/24, mov_aw_imm 0/24 | M:push 19/142, LS 0/68, M:out 17/51, in_al_dw 18/24 | w1o 5/54, w2o 5/54, w0o 4/51, w0e 10/42, w1e 15/42, w2e 15/42 |
| clr1_mw_imm | 54 / 54 | 42/42 | own | 5 | 0 | M:out 30/30, nop 12/12, mov_aw_imm 6/6, shl_imm8 6/6 | M:out 36/36, clr1_mw_imm 12/12, nop 6/6 | w0e 9/9, w0o 9/9, w1e 9/9, w1o 9/9, w2e 9/9, w2o 9/9 |
| clr1_mw_cl | 54 / 54 | 42/42 | own | 3 | 0 | M:out 30/30, nop 12/12, mov_aw_imm 6/6, shl_imm8 6/6 | M:out 36/36, clr1_mw_cl 12/12, nop 6/6 | w0e 9/9, w0o 9/9, w1e 9/9, w1o 9/9, w2e 9/9, w2o 9/9 |
| be_n0 | 52 / 172 | - | successor | 0 | 4 | cmp_aw_aw 49/96, cmp_aw_dw 0/62, be_n0 3/14 | M:out 8/52, M:push 4/24, be_n0 10/24, set1_rw_cl 0/12 | w0o 5/44, w0e 3/40, w1e 11/23, w2e 11/23, w1o 11/21, w2o 11/21 |
| repc_cmpm_w | 50 / 52 | - | own | 0 | 0 | mov_cw_imm2 20/20, mov_cw_imm4 14/14, mov_cw_imm1 12/12, mov_cw_imm0 4/6 | M:out 44/46, M:push 6/6 | w1o 9/10, w2o 10/10, w0e 8/8, w0o 8/8, w1e 8/8, w2e 7/8 |
| cmp_aw_dw | 50 / 330 | 0/12 | undetermined | 0 | 82 | M:out 20/114, M:push 18/60, mov_cw_imm1 0/36, mov_cw_imm2 0/36 | be_n0 16/78, dbnze_n0 0/60, dbnzne_n0 0/24, M:out 0/18 | w0e 4/55, w0o 0/55, w1e 11/55, w1o 12/55, w2e 11/55, w2o 12/55 |
| test_m_imm | 48 / 48 | 42/42 | own | 6 | 0 | M:push 24/24, M:out 12/12, LS 6/6, inc_m 6/6 | M:push 18/18, test_m_imm 12/12, M:out 12/12, LS 6/6 | w0e 8/8, w0o 8/8, w1e 8/8, w1o 8/8, w2e 8/8, w2o 8/8 |
| test_m_aw | 48 / 144 | 48/126 | pair | 0 | 0 | M:push 0/54, M:out 48/48, test_m_aw 0/18, LS 0/12 | M:push 0/54, M:out 36/48, test_m_aw 12/30, LS 0/12 | w0e 8/24, w0o 8/24, w1e 8/24, w1o 8/24, w2e 8/24, w2o 8/24 |
| mulu_dw | 48 / 48 | 48/48 | own | 0 | 0 | M:push 24/24, M:out 24/24 | mulu_dw 24/24, M:push 12/12, M:out 12/12 | w0e 8/8, w0o 8/8, w1e 8/8, w1o 8/8, w2e 8/8, w2o 8/8 |
| ins_dl_i11 | 48 / 48 | 36/36 | own | 3 | 0 | M:out 18/18, nop 18/18, mov_aw_imm 6/6, shl_imm8 6/6 | M:out 36/36, ins_dl_i11 12/12 | w0e 8/8, w0o 8/8, w1e 8/8, w1o 8/8, w2e 8/8, w2o 8/8 |
| ins_dl_bh | 48 / 48 | 36/36 | own | 3 | 0 | M:out 18/18, nop 18/18, mov_aw_imm 6/6, shl_imm8 6/6 | M:out 36/36, ins_dl_bh 12/12 | w0e 8/8, w0o 8/8, w1e 8/8, w1o 8/8, w2e 8/8, w2o 8/8 |
| ext_dl_i11 | 48 / 48 | 36/36 | own | 3 | 0 | M:out 18/18, nop 18/18, mov_aw_imm 6/6, shl_imm8 6/6 | M:out 36/36, ext_dl_i11 12/12 | w0e 8/8, w0o 8/8, w1e 8/8, w1o 8/8, w2e 8/8, w2o 8/8 |
| ext_dl_bh | 48 / 48 | 36/36 | own | 3 | 0 | M:out 18/18, nop 18/18, mov_aw_imm 6/6, shl_imm8 6/6 | M:out 36/36, ext_dl_bh 12/12 | w0e 8/8, w0o 8/8, w1e 8/8, w1o 8/8, w2e 8/8, w2o 8/8 |
| divu_m | 48 / 48 | 24/24 | own | 6 | 0 | M:push 18/18, mov_dw_imm0 18/18, M:out 6/6, inc_m 6/6 | M:push 18/18, divu_m 18/18, M:out 12/12 | w0e 8/8, w0o 8/8, w1e 8/8, w1o 8/8, w2e 8/8, w2o 8/8 |
| and_m_imm8 | 48 / 48 | 48/48 | own | 0 | 0 | M:push 24/24, M:out 24/24 | and_m_imm8 24/24, M:push 12/12, M:out 12/12 | w0e 8/8, w0o 8/8, w1e 8/8, w1o 8/8, w2e 8/8, w2o 8/8 |
| dbnzne_n0 | 46 / 48 | - | own | 46 | 0 | cmp_aw_aw 24/24, cmp_aw_dw 22/24 | M:out 23/24, M:push 23/24 | w0e 8/8, w0o 8/8, w1e 8/8, w1o 8/8, w2e 7/8, w2o 7/8 |
| or_m_aw | 42 / 48 | 42/48 | own | 0 | 0 | M:push 24/24, M:out 18/24 | or_m_aw 24/24, M:push 12/12, M:out 6/12 | w0e 6/8, w0o 8/8, w1e 6/8, w1o 8/8, w2e 6/8, w2o 8/8 |
| cmp4s | 42 / 42 | - | own | 21 | 0 | mov_cl_imm 18/18, mov_cl2 12/12, mov_cl8 6/6, mov_cl16 6/6 | M:out 24/24, cmp4s 12/12, M:push 6/6 | w0e 7/7, w0o 7/7, w1e 7/7, w1o 7/7, w2e 7/7, w2o 7/7 |
| rep_outm_b | 41 / 42 | - | own | 0 | 0 | mov_cw_imm1 12/12, mov_cw_imm0 5/6, mov_cw_imm2 6/6, mov_cw_imm3 6/6 | M:out 41/42 | w0e 7/7, w0o 7/7, w1e 7/7, w1o 7/7, w2e 7/7, w2o 6/7 |
| rep_inm_b | 41 / 42 | - | own | 0 | 0 | mov_cw_imm1 12/12, mov_cw_imm0 5/6, mov_cw_imm2 6/6, mov_cw_imm3 6/6 | M:out 41/42 | w0e 7/7, w0o 7/7, w1e 7/7, w1o 7/7, w2e 7/7, w2o 6/7 |
| repnc_cmpm_w | 40 / 42 | - | own | 0 | 0 | mov_cw_imm1 12/12, mov_cw_imm2 12/12, mov_cw_imm4 12/12, mov_cw_imm0 4/6 | M:out 40/42 | w0e 7/7, w0o 7/7, w1e 7/7, w1o 6/7, w2e 6/7, w2o 7/7 |
| repnc_cmpbk_w | 40 / 40 | - | own | 0 | 0 | mov_cw_imm2 14/14, mov_cw_imm4 14/14, mov_cw_imm1 12/12 | M:out 40/40 | w1o 8/8, w2o 8/8, w0e 6/6, w0o 6/6, w1e 6/6, w2e 6/6 |
| rep_stm_b | 40 / 42 | - | own | 0 | 0 | mov_cw_imm1 12/12, mov_cw_imm0 4/6, mov_cw_imm2 6/6, mov_cw_imm3 6/6 | M:out 40/42 | w0e 7/7, w0o 7/7, w1e 6/7, w1o 7/7, w2e 7/7, w2o 6/7 |
| mov_aw_dw | 38 / 1993 | 0/642 | undetermined | 0 | 12 | nop 0/420, M:push 9/240, M:out 23/228, mov_aw_dw 0/192 | M:out 3/470, M:push 3/395, LS 0/210, mov_aw_dw 0/192 | w1e 9/337, w2e 9/337, w1o 3/334, w2o 3/334, w0e 11/326, w0o 3/325 |
| sub4s | 36 / 36 | - | own | 18 | 0 | mov_cl2 12/12, mov_cl_imm 12/12, mov_cl8 6/6, mov_cl16 6/6 | M:out 24/24, sub4s 12/12 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| shlb_m_imm4 | 36 / 36 | 36/36 | own | 0 | 0 | M:out 18/18, M:push 18/18 | shlb_m_imm4 24/24, M:out 6/6, M:push 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| shl_m_imm4 | 36 / 36 | 36/36 | own | 0 | 0 | M:out 18/18, M:push 18/18 | shl_m_imm4 24/24, M:out 6/6, M:push 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| ret_imm0 | 36 / 36 | - | own | 36 | 0 | br_n3 36/36 | call_n2 24/24, M:out 6/6, M:push 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| repc_cmpbk_w | 36 / 36 | - | own | 0 | 0 | mov_cw_imm1 12/12, mov_cw_imm2 12/12, mov_cw_imm4 12/12 | M:out 36/36 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| orb_m_imm8_80 | 36 / 36 | 36/36 | own | 0 | 0 | M:out 18/18, M:push 18/18 | orb_m_imm8_80 24/24, M:out 6/6, M:push 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| mul_m | 36 / 36 | 18/18 | own | 6 | 0 | M:push 12/12, mov_dw_imm0 12/12, inc_m 6/6, M:out 6/6 | mul_m 12/12, M:push 12/12, M:out 12/12 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| les_aw_ix | 36 / 36 | 36/36 | own | 0 | 0 | M:out 18/18, M:push 18/18 | les_aw_ix 24/24, M:out 6/6, M:push 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| lds_aw_ix | 36 / 36 | 36/36 | own | 0 | 0 | M:out 18/18, M:push 18/18 | lds_aw_ix 24/24, M:out 6/6, M:push 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| br_m_dir | 36 / 36 | - | own | 14 | 0 | st_acc_dir 24/24, nop 12/12 | M:out 12/12, nop 12/12, M:push 12/12 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| rep_movbk_b | 34 / 36 | - | own | 0 | 0 | mov_cw_imm0 4/6, mov_cw_imm1 6/6, mov_cw_imm2 6/6, mov_cw_imm3 6/6 | M:out 34/36 | w0e 6/6, w0o 6/6, w1e 5/6, w1o 6/6, w2e 6/6, w2o 5/6 |
| mov_cw_imm0 | 34 / 258 | 0/18 | predecessor | 0 | 0 | M:out 8/174, M:push 8/30, D 0/18, D4 18/18 | nop 0/36, bcwz_n0 12/36, rep_stm_w 6/24, rep_inm_w 6/24 | w0e 7/43, w0o 7/43, w1e 7/43, w1o 7/43, w2e 3/43, w2o 3/43 |
| set1_rw_imm | 33 / 96 | 58/60 | own | 3 | 0 | M:out 6/30, nop 12/30, set1_rw_imm 12/18, mov_aw_imm 0/6 | M:out 30/60, set1_rw_imm 0/18, M:push 3/12, nop 0/6 | w0e 5/16, w0o 6/16, w1e 5/16, w1o 8/16, w2e 3/16, w2o 6/16 |
| mov_m_ds0 | 32 / 36 | 32/36 | own | 0 | 0 | M:push 12/12, M:out 8/12, nop 12/12 | M:push 18/18, M:out 14/18 | w0e 6/6, w0o 6/6, w1e 4/6, w1o 6/6, w2e 4/6, w2o 6/6 |
| st_imm0_dir_c42 | 30 / 60 | 8/12 | predecessor | 0 | 0 | PAD 30/30, start 0/30 | LS 30/60 | w0e 10/10, w0o 0/10, w1e 10/10, w1o 0/10, w2e 10/10, w2o 0/10 |
| st_acc_dir | 30 / 396 | 0/24 | undetermined | 0 | 82 | mov_aw_imm 12/72, mov_aw_t0059 0/60, mov_aw_t0058 0/57, mov_aw_t005e 5/36 | mov_aw_1000 24/144, call_m_dir 0/84, nop 2/36, M:push 2/24 | w0e 15/66, w0o 15/66, w1e 0/66, w1o 0/66, w2e 0/66, w2o 0/66 |
| set1_rb_imm | 30 / 84 | 46/48 | own | 3 | 0 | M:out 6/30, nop 9/24, set1_rb_imm 12/18, mov_aw_imm 0/6 | M:out 30/60, set1_rb_imm 0/18, nop 0/6 | w0e 5/14, w0o 5/14, w1e 5/14, w1o 7/14, w2e 3/14, w2o 5/14 |
| retf | 30 / 41 | - | own | 30 | 0 | br_n1 30/41 | callf_t005c 8/12, M:push 5/8, M:out 7/7, callf_t005b 6/6 | w0o 6/10, w0e 0/7, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| div_m | 30 / 30 | 12/12 | own | 6 | 0 | M:push 12/12, mov_dw_imm0 12/12, inc_m 6/6 | div_m 12/12, M:push 12/12, M:out 6/6 | w0e 5/5, w0o 5/5, w1e 5/5, w1o 5/5, w2e 5/5, w2o 5/5 |
| brk5 | 30 / 30 | - | own | 24 | 0 | st_acc_0016 20/20, nop 10/10 | br_n1 20/20, br_n2 10/10 | w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6, w0e 3/3, w0o 3/3 |
| brf_m_dir | 30 / 30 | - | own | 8 | 0 | st_acc_0c02 20/20, nop 10/10 | M:out 10/10, nop 10/10, M:push 10/10 | w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6, w0e 3/3, w0o 3/3 |
