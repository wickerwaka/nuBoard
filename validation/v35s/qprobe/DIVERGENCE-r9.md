# Round 9, item 1: the corpus misses, position against cause

Tree: the round-8 build (rtl-spec4 built), replayed once at the default spacing in my worktree:
0 FAIL, chk silent, **15,342 exact** of 30,536 (the scorer; 15,194 runs not exact).

## Method (`build/qp/fd9.py`, `tab9.py`; data `fd9.jsonl`, `fd9-tab.json`)

For every run: the first differing bus event and its *subject* (the oldest instruction in the
nine bytes below the highest address silicon had fetched, skipping markers, NOPs, pads,
drainers), as in round 8. New: every instruction X of every run is one observation
(form, predecessor, successor, wait, parity, hit), hit = "the run diverges and X is the
subject". Instructions behind the subject are not observed (the run has already left
silicon); instructions before it count as passed. So each form has a miss *rate* per
predecessor class and per successor class, not only a count.

Evidence rule for the cause column (classes with at least 6 observations):
- **own**: the rate is >= 70 % behind every predecessor class and before every successor class;
- **predecessor**: some predecessor class >= 70 % and another <= 15 %, the successor classes
  not split that way; **successor**: the converse; **pair**: both split;
- **undetermined**: anything else - mostly forms that miss at some waits or alignments in
  every frame (the last column shows it), i.e. their own routine is partly right.
The rule is mechanical and coarse: a small class can tip it (st_bw is labelled predecessor
by one small class; its table row says successor: it misses before the OUT marker at W = 0
only). Read the row, not only the label.

## Answer to the question "is the opcode before the diverging one the cause in some cases?"

Yes, and the opcode after it more often. Of the 14,858 misses attributed to an instruction:

| cause | runs |
|---|---|
| own | 8297 |
| undetermined | 4659 |
| predecessor | 837 |
| successor | 694 |
| pair | 371 |

(own = the routine itself is unread or wrong in every frame; the three neighbour classes
together are 1,902 runs with a clear split, and most of "undetermined" is wait- or
alignment-dependent, which in this machine usually means "depends on what the bus is doing",
i.e. on the neighbours' fetches.)

## The converse check: forms exact in isolation in the small set that are corpus subjects

A form that the RTL reproduces behind a long shift and before a long shift (or before the
plain OUT DW marker) and that is still the subject of corpus misses is a pair effect by
construction:

| corpus form | small-set tests (reading model exact; RTL exact where the coordinator or `read cmp` confirmed it: sbw, sacc, shl1, rr, ri, rw-add, c40 with OUT DW / NOP / shift followers) | corpus misses at it | where | reading |
|---|---|---|---|---|
| st_bw (MOV [BW],AW) | r5 `sbw` 18 / 18, r9 `c40-st-od / -on / -os` | 139 of 1,066 | before the OUT imm8 marker, W = 0 (123 of 139) | **successor**: OUT imm8 behind a memory write (item 2 below) |
| add_m_aw (ADD [BW],AW) | r8 `rw-add` 12 / 12 | 118 of 657 | before the OUT imm8 marker, W = 0 (105) | **successor**: the same |
| inc_m (INC word [BW]) | r8 `rw-incm` 12 / 12 | 136 of 286 | behind the PUSH marker (114 of 186), every wait | **predecessor**: a group form behind a stack write |
| shl1 (SHL AW,1) | r2 `shl1` 30 / 30 | 98 of 214 | behind the OUT imm8 marker 72 of 72, behind the long shift 0 of 24 | **predecessor**: behind an I/O cycle (its bus-idle third word against the fetch that follows the cycle) |
| cmp_aw_aw, cmp_aw_dw (CMP r,r) | r8 `t-cmprr` 18 / 18 | 247, 132 | before be / bne / dbnze / dbnzne only (0 before MOV, markers) | **successor is the subject**: the Jcc / DBNZcc behind it (position puts the CMP first) |
| mov_cw_imm1 (MOV CW,imm16) | r1 `ri` 48 / 48 | 87 of 948 | before dbnz 63 of 126, else ~0 | the DBNZ behind it |
| add_dw_imm* (ADD DW,imm16) | r2 `addi` (ADD AW,imm16) 30 / 30 | 242 + 120 + 92 | W = 0 everywhere, W = 1 / 2 in part; behind OUT imm8 always | own at W = 0 (81 C2 is a ModR/M immediate form, not the accumulator form measured) plus predecessor |
| st_acc_dir (MOV [d16],AW) | r5 `sacc` 18 / 18 | 118 of 396 | behind MOV AW,imm16 of some values, before CALL mem | pair (the store's address is the CALL's vector: a function of the data, not of timing?) - undetermined |
| mov_aw_dw (MOV r,r) | r1 `rr` 54 / 54 | 64 of 1,993 | behind the OUT imm8 marker 29 of 228 | predecessor, rare |
| ldea_bw | r8 `ld-lea` 0 / 18 (reverted in the RTL: known) | 75 of 99 | every frame | own (known: the head cannot express it) |

## By form (the 400 largest; misses at the form / observations of it)

| form | misses at it / observed | cause | by predecessor (misses/observed) | by successor | by wait+parity |
|---|---|---|---|---|---|
| st_imm_bw | 321 / 330 | own | nop 162/162, pfx_nop 60/60, M:push 44/44, M:out 35/44 | M:push 92/92, M:out 83/92, st_imm_bw 84/84, LS 62/62 | w0e 65/65, w0o 65/65, w1e 60/65, w1o 65/65, w2e 31/35, w2o 35/35 |
| pop_m | 318 / 318 | own | nop 114/114, M:push 72/72, M:out 72/72, LS 42/42 | M:push 84/84, M:out 78/78, pop_m 60/60, LS 60/60 | w0e 53/53, w0o 53/53, w1e 53/53, w1o 53/53, w2e 53/53, w2o 53/53 |
| shl_imm8 | 298 / 298 | own | M:out 132/132, br_n4 36/36, nop 28/28, br_n5 24/24 | ret 46/46, LS 36/36, nop 24/24, rep_inm_w 18/18 | w1e 50/50, w1o 50/50, w2e 50/50, w2o 50/50, w0e 49/49, w0o 49/49 |
| add_m_imm | 276 / 276 | own | nop 114/114, M:push 56/56, M:out 50/50, pfx_nop 42/42 | add_m_imm 90/90, M:push 74/74, M:out 74/74, LS 38/38 | w0e 56/56, w0o 56/56, w1e 56/56, w1o 56/56, w2e 26/26, w2o 26/26 |
| st_imm_bw_d8 | 265 / 324 | undetermined | nop 142/162, pfx_nop 56/60, M:push 20/32, M:out 22/32 | M:out 69/89, M:push 74/87, st_imm_bw_d8 66/84, LS 56/64 | w1e 39/69, w1o 44/69, w0e 61/61, w0o 61/61, w2o 29/33, w2e 31/31 |
| st_imm_bw_d16 | 262 / 366 | undetermined | nop 104/162, pfx_nop 36/60, M:push 34/50, M:out 50/50 | st_imm_bw_d16 84/108, M:push 72/99, M:out 62/92, LS 44/67 | w1o 43/79, w1e 43/75, w0e 67/67, w0o 67/67, w2o 21/41, w2e 21/37 |
| rep_stm_w | 255 / 264 | undetermined | mov_cw_imm1 84/84, nop 57/60, mov_cw_imm2 54/54, mov_cw_imm0 12/18 | M:out 183/192, nop 24/24, mov_cw_imm1 24/24, mov_aw_dw 12/12 | w0e 44/44, w0o 44/44, w1e 42/44, w1o 44/44, w2e 41/44, w2o 40/44 |
| cmp_aw_aw | 247 / 952 | successor | M:out 78/444, M:push 111/348, nop 6/42, mov_aw_imm 6/36 | bne_n0 54/304, be_n0 52/144, mov_aw_dw 0/48, M:push 0/24 | w0e 18/159, w0o 9/159, w1e 45/159, w2e 44/159, w1o 66/158, w2o 65/158 |
| add_dw_imm0 | 242 / 486 | undetermined | nop 44/132, M:push 30/90, M:out 84/84, D 24/72 | out_dw_b 44/90, ld_bw 32/72, st_bw 32/72, mov_aw_dw 32/72 | w0e 81/81, w0o 81/81, w1e 14/81, w1o 26/81, w2e 14/81, w2o 26/81 |
| rep_inm_w | 203 / 210 | own | mov_cw_imm1 78/78, nop 57/60, mov_cw_imm2 30/30, mov_cw_imm0 14/18 | M:out 155/162, nop 12/12, mov_aw_dw 12/12, ld_bw 12/12 | w0e 35/35, w0o 35/35, w1e 35/35, w1o 35/35, w2e 32/35, w2o 31/35 |
| rep_movbk_w | 196 / 198 | undetermined | mov_cw_imm1 90/90, mov_cw_imm2 42/42, mov_cw_imm4 30/30, D 12/12 | M:out 148/150, nop 12/12, mov_aw_dw 12/12, ld_bw 12/12 | w0e 33/33, w0o 33/33, w1e 32/33, w1o 33/33, w2e 33/33, w2o 32/33 |
| st_imm_dir | 168 / 234 | undetermined | nop 80/120, pfx_nop 26/42, M:push 14/20, M:out 20/20 | st_imm_dir 54/72, M:push 42/57, M:out 38/56, LS 34/49 | w1o 30/55, w1e 30/54, w0e 46/46, w0o 46/46, w2o 8/17, w2e 8/16 |
| shl_imm4 | 168 / 168 | own | nop 48/48, M:push 42/42, M:out 42/42, LS 18/18 | LS 66/66, M:push 30/30, M:out 30/30, shl_imm4 24/24 | w0e 28/28, w0o 28/28, w1e 28/28, w1o 28/28, w2e 28/28, w2o 28/28 |
| push_m | 162 / 162 | own | M:push 84/84, M:out 54/54, LS 24/24 | push_m 72/72, M:push 24/24, M:out 24/24, pop_m 18/18 | w0e 27/27, w0o 27/27, w1e 27/27, w1o 27/27, w2e 27/27, w2o 27/27 |
| rep_outm_w | 155 / 162 | own | nop 57/60, mov_cw_imm1 30/30, mov_cw_imm2 30/30, mov_cw_imm0 14/18 | M:out 155/162 | w0e 27/27, w0o 27/27, w1e 27/27, w1o 27/27, w2e 24/27, w2o 23/27 |
| test1_mw_cl | 150 / 150 | own | M:out 72/72, M:push 54/54, nop 18/18, mov_aw_imm 6/6 | test1_mw_cl 36/36, M:out 30/30, M:push 18/18, ld_bw 12/12 | w0e 25/25, w0o 25/25, w1e 25/25, w1o 25/25, w2e 25/25, w2o 25/25 |
| add_m_imm_d16 | 144 / 144 | own | nop 72/72, pfx_nop 24/24, M:push 20/20, M:out 20/20 | add_m_imm_d16 72/72, M:push 26/26, M:out 26/26, LS 20/20 | w0e 34/34, w0o 34/34, w1e 34/34, w1o 34/34, w2e 4/4, w2o 4/4 |
| br_n1 | 140 / 321 | predecessor | call_n2 101/247, M:out 9/18, callf_t0054 13/18, M:push 0/6 | ret 101/247, retf 27/38, nop 12/36 | w0e 14/57, w0o 17/57, w1e 34/52, w1o 28/52, w2o 24/52, w2e 23/51 |
| st_bw | 139 / 1066 | predecessor | nop 22/144, M:push 8/96, M:out 23/90, mov_aw_dw 8/88 | M:out 123/437, M:push 9/389, LS 0/150, st_bw 2/30 | w1e 3/188, w2e 3/188, w1o 2/184, w2o 2/184, w0o 68/166, w0e 61/156 |
| test_dir_aw | 138 / 138 | own | nop 60/60, M:push 42/42, M:out 36/36 | test_dir_aw 54/54, M:out 48/48, M:push 36/36 | w0e 23/23, w0o 23/23, w1e 23/23, w1o 23/23, w2e 23/23, w2o 23/23 |
| pop_m_dir | 138 / 138 | own | nop 66/66, M:push 24/24, M:out 18/18, pfx_nop 18/18 | M:push 60/60, M:out 36/36, LS 30/30, pop_m_dir 12/12 | w0e 23/23, w0o 23/23, w1e 23/23, w1o 23/23, w2e 23/23, w2o 23/23 |
| pop_m_d8 | 138 / 138 | own | nop 66/66, M:push 24/24, M:out 18/18, pfx_nop 18/18 | M:push 60/60, M:out 36/36, LS 30/30, pop_m_d8 12/12 | w0e 23/23, w0o 23/23, w1e 23/23, w1o 23/23, w2e 23/23, w2o 23/23 |
| cmp_m_imm | 138 / 138 | own | nop 42/42, M:push 36/36, M:out 36/36, pfx_nop 18/18 | M:push 48/48, M:out 48/48, cmp_m_imm 24/24, LS 18/18 | w0e 23/23, w0o 23/23, w1e 23/23, w1o 23/23, w2e 23/23, w2o 23/23 |
| inc_m | 136 / 286 | successor | M:push 114/186, M:out 16/48, inc_m 2/34, nop 4/12 | M:push 6/60, M:out 20/58, inc_m 2/36, mulu_m 12/12 | w0o 29/48, w1e 20/48, w1o 19/48, w2e 20/48, w2o 19/48, w0e 29/46 |
| cmp_aw_dw | 132 / 330 | pair | M:out 20/114, M:push 18/60, mov_cw_imm1 24/36, mov_cw_imm2 22/36 | be_n0 16/78, dbnze_n0 60/60, dbnzne_n0 22/24, M:out 0/18 | w0e 18/55, w0o 14/55, w1e 25/55, w1o 26/55, w2e 24/55, w2o 25/55 |
| repe_cmpbk_w | 128 / 130 | undetermined | mov_cw_imm1 66/66, mov_cw_imm2 32/32, mov_cw_imm4 14/14, mov_cw_imm0 4/6 | M:out 92/94, nop 12/12, mov_aw_dw 12/12, ld_bw 12/12 | w1o 23/23, w2o 22/23, w0e 21/21, w0o 21/21, w1e 20/21, w2e 21/21 |
| test_m_aw | 126 / 126 | own | M:push 54/54, M:out 48/48, LS 12/12, nop 12/12 | M:out 48/48, M:push 36/36, test_m_aw 30/30, LS 12/12 | w0e 21/21, w0o 21/21, w1e 21/21, w1o 21/21, w2e 21/21, w2o 21/21 |
| st_imm_bw_ix_d16 | 122 / 174 | undetermined | nop 40/72, M:push 20/30, M:out 30/30, pfx_nop 10/18 | st_imm_bw_ix_d16 44/62, M:push 34/46, M:out 30/42, LS 14/24 | w1o 17/32, w2o 17/32, w1e 18/29, w2e 18/29, w0e 26/26, w0o 26/26 |
| test_m_imm_d16 | 120 / 120 | own | nop 72/72, pfx_nop 24/24, M:push 8/8, M:out 8/8 | test_m_imm_d16 60/60, M:push 20/20, M:out 20/20, LS 20/20 | w0e 30/30, w0o 30/30, w1e 30/30, w1o 30/30 |
| shl_m1 | 120 / 120 | own | M:push 72/72, M:out 36/36, nop 12/12 | M:out 42/42, M:push 30/30, shl_m1 30/30, nop 6/6 | w0e 20/20, w0o 20/20, w1e 20/20, w1o 20/20, w2e 20/20, w2o 20/20 |
| cmp_m_imm_d16 | 120 / 120 | own | nop 72/72, pfx_nop 24/24, M:push 8/8, M:out 8/8 | cmp_m_imm_d16 60/60, M:push 20/20, M:out 20/20, LS 20/20 | w0e 30/30, w0o 30/30, w1e 30/30, w1o 30/30 |
| add_m_imm_dir | 120 / 120 | own | nop 72/72, pfx_nop 24/24, M:push 8/8, M:out 8/8 | add_m_imm_dir 60/60, M:push 20/20, M:out 20/20, LS 20/20 | w0e 30/30, w0o 30/30, w1e 30/30, w1o 30/30 |
| add_m_imm_d8 | 120 / 120 | own | nop 72/72, pfx_nop 24/24, M:push 8/8, M:out 8/8 | add_m_imm_d8 60/60, M:push 20/20, M:out 20/20, LS 20/20 | w0e 30/30, w0o 30/30, w1e 30/30, w1o 30/30 |
| add_dw_imm2a01 | 120 / 156 | undetermined | M:out 102/102, M:push 18/54 | bv_n0 8/12, bnv_n0 8/12, bnh_n0 8/12, bh_n0 8/12 | w0e 26/26, w0o 26/26, w1e 17/26, w1o 17/26, w2e 17/26, w2o 17/26 |
| st_acc_dir | 118 / 396 | predecessor | mov_aw_imm 14/72, mov_aw_t0059 45/60, mov_aw_t0058 13/57, mov_aw_t005e 5/36 | mov_aw_1000 24/144, call_m_dir 42/84, nop 6/36, M:push 2/24 | w0e 33/66, w0o 33/66, w1e 13/66, w1o 13/66, w2e 13/66, w2o 13/66 |
| set1_rw_cl | 118 / 207 | undetermined | M:out 16/72, M:push 24/48, set1_rw_cl 33/33, nop 23/29 | M:out 58/68, set1_rw_cl 18/51, M:push 19/22, ld_bw 3/12 | w0e 18/36, w2e 17/36, w0o 23/35, w1e 16/35, w2o 21/33, w1o 23/32 |
| rep_ldm_w | 118 / 120 | undetermined | mov_cw_imm1 72/72, mov_cw_imm2 18/18, mov_cw_imm4 12/12, mov_cw_imm0 4/6 | M:out 70/72, nop 12/12, mov_aw_dw 12/12, ld_bw 12/12 | w0e 20/20, w0o 20/20, w1e 19/20, w1o 20/20, w2e 20/20, w2o 19/20 |
| add_m_imm8_d16 | 118 / 122 | undetermined | nop 72/72, pfx_nop 24/24, M:push 8/8, M:out 4/8 | add_m_imm8_d16 58/60, M:out 20/22, M:push 20/20, LS 20/20 | w0o 29/31, w1o 29/31, w0e 30/30, w1e 30/30 |
| add_m_aw | 118 / 657 | undetermined | M:push 8/90, M:out 23/90, nop 18/84, D 10/60 | M:out 105/377, M:push 6/160, add_m_aw 2/30, LS 0/30 | w1e 2/115, w2e 2/115, w1o 1/114, w2o 1/114, w0o 60/105, w0e 52/94 |
| rol4_dl | 108 / 108 | own | M:out 60/60, M:push 48/48 | rol4_dl 30/30, M:out 12/12, ld_bw 12/12, st_bw 12/12 | w0e 18/18, w0o 18/18, w1e 18/18, w1o 18/18, w2e 18/18, w2o 18/18 |
| ext_bl_dh | 108 / 108 | own | M:out 54/54, nop 24/24, M:push 24/24, mov_aw_imm 6/6 | M:out 30/30, mov_aw_dw 18/18, ext_bl_dh 12/12, M:push 12/12 | w0e 18/18, w0o 18/18, w1e 18/18, w1o 18/18, w2e 18/18, w2o 18/18 |
| repne_cmpm_w | 104 / 106 | undetermined | mov_cw_imm1 54/54, mov_cw_imm2 20/20, mov_cw_imm4 14/14, mov_cw_imm0 4/6 | M:out 68/70, nop 12/12, mov_aw_dw 12/12, ld_bw 12/12 | w1o 19/19, w2o 18/19, w0e 17/17, w0o 17/17, w1e 16/17, w2e 17/17 |
| shl1 | 98 / 214 | pair | M:out 72/72, M:push 22/66, nop 4/36, LS 0/24 | M:push 8/38, nop 24/36, shl1 16/32, M:out 26/30 | w0e 12/37, w0o 12/37, w1o 12/37, w2o 12/37, w1e 25/33, w2e 25/33 |
| pop_m_bw_ix_d8 | 96 / 96 | own | nop 48/48, pfx_nop 18/18, M:push 12/12, M:out 12/12 | M:push 30/30, M:out 30/30, LS 24/24, pop_m_bw_ix_d8 12/12 | w0e 16/16, w0o 16/16, w1e 16/16, w1o 16/16, w2e 16/16, w2o 16/16 |
| pop_m_bw_ix_d16 | 96 / 96 | own | nop 48/48, pfx_nop 18/18, M:push 12/12, M:out 12/12 | M:push 30/30, M:out 30/30, LS 24/24, pop_m_bw_ix_d16 12/12 | w0e 16/16, w0o 16/16, w1e 16/16, w1o 16/16, w2e 16/16, w2o 16/16 |
| pop_m_bw_d16 | 96 / 96 | own | nop 48/48, pfx_nop 18/18, M:push 12/12, M:out 12/12 | M:push 30/30, M:out 30/30, LS 24/24, pop_m_bw_d16 12/12 | w0e 16/16, w0o 16/16, w1e 16/16, w1o 16/16, w2e 16/16, w2o 16/16 |
| st_imm_bw_ix_d8 | 95 / 116 | undetermined | nop 43/48, M:push 12/18, pfx_nop 17/18, M:out 12/18 | M:push 29/34, M:out 28/34, st_imm_bw_ix_d8 16/24, LS 22/24 | w1o 12/22, w1e 12/20, w2o 17/20, w0e 18/18, w0o 18/18, w2e 18/18 |
| st_imm_bw_ix | 94 / 96 | own | nop 48/48, pfx_nop 18/18, M:push 12/12, M:out 10/12 | M:push 30/30, M:out 28/30, LS 24/24, st_imm_bw_ix 12/12 | w0e 16/16, w0o 16/16, w1e 15/16, w1o 16/16, w2e 15/16, w2o 16/16 |
| add_dw_imm | 92 / 176 | predecessor | nop 46/88, LS 20/30, M:push 8/24, M:out 18/18 | LS 38/60, M:push 14/38, out_imm_al 14/34, add_dw_imm 16/32 | w1e 8/31, w1o 12/31, w2e 8/31, w2o 12/31, w0e 26/26, w0o 26/26 |
| mulu_m | 90 / 90 | own | M:push 60/60, M:out 30/30 | mulu_m 36/36, M:push 18/18, M:out 18/18, nop 6/6 | w0e 15/15, w0o 15/15, w1e 15/15, w1o 15/15, w2e 15/15, w2o 15/15 |
| cmp_m_imm8 | 90 / 90 | own | nop 42/42, pfx_nop 18/18, M:push 12/12, M:out 12/12 | M:push 30/30, M:out 30/30, LS 18/18, cmp_m_imm8 12/12 | w0e 15/15, w0o 15/15, w1e 15/15, w1o 15/15, w2e 15/15, w2o 15/15 |
| br_bw | 90 / 116 | undetermined | mov_bw_t0052 35/51, mov_bw_t0053 28/30, mov_bw_t0051 24/24, mov_bw_t0057 0/4 | nop 20/24, push_aw 10/12, out_imm_al 10/12, set1_rw_cl 10/12 | w2e 9/22, w2o 9/22, w0e 18/18, w0o 18/18, w1e 18/18, w1o 18/18 |
| st_imm8_bw | 88 / 90 | own | nop 42/42, pfx_nop 18/18, M:push 12/12, M:out 10/12 | M:push 30/30, M:out 28/30, LS 18/18, st_imm8_bw 12/12 | w0e 15/15, w0o 15/15, w1e 14/15, w1o 15/15, w2e 14/15, w2o 15/15 |
| ld_bw_ix_d16 | 88 / 134 | undetermined | nop 38/66, M:out 24/24, M:push 12/18, pfx_nop 10/18 | M:out 40/60, M:push 24/38, LS 14/24, ld_bw_ix_d16 10/12 | w1o 10/23, w2o 10/23, w0e 22/22, w0o 22/22, w1e 12/22, w2e 12/22 |
| mov_cw_imm1 | 87 / 948 | predecessor | M:out 24/684, M:push 24/90, nop 12/60, stc 0/30 | dbnz_n0 63/126, nop 0/108, rep_stm_w 6/90, rep_movbk_w 0/90 | w0e 14/158, w0o 15/158, w1e 14/158, w1o 15/158, w2e 14/158, w2o 15/158 |
| pop_m_bw_ix | 84 / 84 | own | nop 48/48, pfx_nop 18/18, M:push 6/6, M:out 6/6 | M:push 30/30, M:out 30/30, LS 24/24 | w0e 14/14, w0o 14/14, w1e 14/14, w1o 14/14, w2e 14/14, w2o 14/14 |
| mulu_aw | 84 / 90 | own | nop 30/36, M:push 30/30, M:out 24/24 | M:push 31/36, M:out 35/36, nop 12/12, mulu_aw 6/6 | w0e 14/15, w0o 12/15, w1e 15/15, w1o 14/15, w2e 15/15, w2o 14/15 |
| ext_dl_dh | 84 / 84 | own | M:out 48/48, M:push 36/36 | M:out 12/12, ld_bw 12/12, st_bw 12/12, push_aw 12/12 | w0e 14/14, w0o 14/14, w1e 14/14, w1o 14/14, w2e 14/14, w2o 14/14 |
| st_bw_ix_d16 | 78 / 122 | undetermined | nop 38/66, pfx_nop 10/18, M:out 18/18, M:push 8/12 | M:out 34/54, M:push 20/32, LS 14/24, st_bw_ix_d16 10/12 | w1o 9/21, w2o 9/21, w0e 20/20, w0o 20/20, w1e 10/20, w2e 10/20 |
| st_acc_000e | 75 / 100 | undetermined | mov_aw_1000 75/100 | brk3 70/70, nop 4/20, M:out 1/5, M:push 0/5 | w1e 15/20, w1o 15/20, w2e 15/20, w2o 15/20, w0e 8/10, w0o 7/10 |
| ldea_bw | 75 / 99 | undetermined | M:push 21/30, M:out 18/30, nop 10/12, D 11/12 | M:push 36/39, M:out 21/36, ldea_bw 9/12, nop 9/12 | w0e 12/17, w1e 11/17, w2e 12/17, w0o 16/16, w1o 11/16, w2o 13/16 |
| stm_w | 72 / 72 | own | M:out 42/42, M:push 30/30 | M:out 12/12, ld_bw 12/12, push_aw 12/12, out_imm_al 12/12 | w0e 12/12, w0o 12/12, w1e 12/12, w1o 12/12, w2e 12/12, w2o 12/12 |
| movbk_w | 72 / 72 | own | M:out 42/42, M:push 30/30 | M:out 12/12, ld_bw 12/12, push_aw 12/12, out_imm_al 12/12 | w0e 12/12, w0o 12/12, w1e 12/12, w1o 12/12, w2e 12/12, w2o 12/12 |
| inm_w | 72 / 72 | own | M:out 42/42, M:push 30/30 | M:out 12/12, ld_bw 12/12, push_aw 12/12, out_imm_al 12/12 | w0e 12/12, w0o 12/12, w1e 12/12, w1o 12/12, w2e 12/12, w2o 12/12 |
| ext_bl_i7 | 72 / 72 | own | M:out 36/36, nop 24/24, mov_aw_imm 6/6, M:push 6/6 | M:out 30/30, ext_bl_i7 12/12, M:push 12/12, ld_dir 6/6 | w0e 12/12, w0o 12/12, w1e 12/12, w1o 12/12, w2e 12/12, w2o 12/12 |
| cmpbk_w | 72 / 72 | own | M:out 42/42, M:push 30/30 | M:out 12/12, ld_bw 12/12, push_aw 12/12, out_imm_al 12/12 | w0e 12/12, w0o 12/12, w1e 12/12, w1o 12/12, w2e 12/12, w2o 12/12 |
| add4s | 69 / 69 | own | mov_cl2 54/54, mov_cl_imm 9/9, mov_cl8 3/3, mov_cl16 3/3 | add4s 18/18, M:out 15/15, M:push 6/6, ld_bw 6/6 | w0o 14/14, w1o 14/14, w2o 14/14, w0e 9/9, w1e 9/9, w2e 9/9 |
| dbnz_n0 | 67 / 71 | undetermined | mov_cw_imm1 63/63, mov_cw_imm2 4/8 | M:out 29/31, nop 18/18, M:push 14/16, mov_cw_imm1 6/6 | w2e 11/13, w0e 12/12, w1e 12/12, w2o 10/12, w0o 11/11, w1o 11/11 |
| set1_mw_cl | 66 / 66 | own | M:out 30/30, nop 18/18, M:push 12/12, mov_aw_imm 6/6 | M:out 30/30, M:push 18/18, set1_mw_cl 12/12, nop 6/6 | w0e 11/11, w0o 11/11, w1e 11/11, w1o 11/11, w2e 11/11, w2o 11/11 |
| mov_cl2 | 66 / 192 | undetermined | M:out 42/90, M:push 24/48, LS 0/36, nop 0/18 | add4s 54/108, shl_aw_cl 0/24, nop 0/18, M:out 0/12 | w0e 14/32, w0o 8/32, w1e 14/32, w1o 8/32, w2e 14/32, w2o 8/32 |
| out_dw_b | 64 / 954 | successor | nop 2/145, M:out 48/108, mov_aw_imm 0/90, mov_aw_dw 0/84 | M:out 6/358, M:push 9/306, LS 1/188, out_dw_b 0/12 | w1o 5/165, w2o 10/165, w1e 13/161, w2e 16/161, w0o 8/154, w0e 12/148 |
| mov_aw_dw | 64 / 1993 | successor | nop 4/420, M:push 9/240, M:out 29/228, mov_aw_dw 0/192 | M:out 3/470, M:push 3/395, LS 0/210, mov_aw_dw 0/192 | w1e 11/337, w2e 11/337, w1o 5/334, w2o 5/334, w0e 24/326, w0o 8/325 |
| ld_bp_iy_d16 | 62 / 96 | undetermined | nop 28/48, pfx_nop 10/18, M:push 8/12, M:out 12/12 | M:push 24/36, M:out 24/36, LS 14/24 | w0e 16/16, w0o 16/16, w1e 8/16, w1o 7/16, w2e 8/16, w2o 7/16 |
| add_m_aw_bw_ix_d16 | 62 / 98 | undetermined | nop 28/48, pfx_nop 10/18, M:push 8/12, M:out 12/12 | M:push 20/32, M:out 18/30, LS 14/24, add_m_aw_bw_ix_d16 10/12 | w1o 7/17, w2o 7/17, w0e 16/16, w0o 16/16, w1e 8/16, w2e 8/16 |
| xch_m_aw | 60 / 60 | own | M:push 30/30, M:out 24/24, LS 6/6 | M:push 18/18, xch_m_aw 18/18, M:out 18/18, LS 6/6 | w0e 10/10, w0o 10/10, w1e 10/10, w1o 10/10, w2e 10/10, w2o 10/10 |
| set1_mw_cl_bw_ix | 60 / 60 | own | M:out 30/30, M:push 18/18, nop 6/6, mov_aw_imm 6/6 | M:out 30/30, set1_mw_cl_bw_ix 24/24, M:push 6/6 | w0e 10/10, w0o 10/10, w1e 10/10, w1o 10/10, w2e 10/10, w2o 10/10 |
| push_r | 60 / 60 | own | M:push 30/30, M:out 30/30 | pop_r 48/48, M:push 6/6, M:out 6/6 | w0e 10/10, w0o 10/10, w1e 10/10, w1o 10/10, w2e 10/10, w2o 10/10 |
| prepare_00 | 60 / 60 | own | M:push 30/30, M:out 30/30 | dispose 48/48, M:push 6/6, M:out 6/6 | w0e 10/10, w0o 10/10, w1e 10/10, w1o 10/10, w2e 10/10, w2o 10/10 |
| mul_cw | 60 / 60 | own | M:out 24/24, mov_dw_imm0 18/18, M:push 18/18 | mul_cw 30/30, M:out 18/18, M:push 12/12 | w0e 10/10, w0o 10/10, w1e 10/10, w1o 10/10, w2e 10/10, w2o 10/10 |
| mul_aw_m_imm8 | 60 / 60 | own | M:out 24/24, nop 24/24, mov_aw_imm 6/6, M:push 6/6 | M:out 30/30, mul_aw_m_imm8 18/18, M:push 12/12 | w0e 10/10, w0o 10/10, w1e 10/10, w1o 10/10, w2e 10/10, w2o 10/10 |
| ins_bl_i7 | 60 / 60 | own | M:out 36/36, nop 18/18, mov_aw_imm 6/6 | M:out 30/30, ins_bl_i7 12/12, ld_dir 6/6, nop 6/6 | w0e 10/10, w0o 10/10, w1e 10/10, w1o 10/10, w2e 10/10, w2o 10/10 |
| ins_bl_dh | 60 / 60 | own | M:out 36/36, nop 18/18, mov_aw_imm 6/6 | M:out 30/30, ins_bl_dh 12/12, ld_dir 6/6, nop 6/6 | w0e 10/10, w0o 10/10, w1e 10/10, w1o 10/10, w2e 10/10, w2o 10/10 |
| br_n3 | 60 / 94 | pair | call_n2 48/60, M:push 0/6, M:out 1/6, nop 1/6 | nop 2/36, ret_imm0 36/36, ret_imm2 12/12, retf_imm2 10/10 | w1e 11/16, w1o 11/16, w2e 10/16, w2o 10/16, w0e 9/15, w0o 9/15 |
| be_n0 | 58 / 168 | successor | cmp_aw_aw 55/92, cmp_aw_dw 0/62, be_n0 3/14 | M:out 8/52, M:push 4/24, be_n0 10/24, nop 4/8 | w0o 5/44, w0e 5/40, w1e 12/22, w2e 12/22, w1o 12/20, w2o 12/20 |
| in_al_dw | 54 / 285 | pair | nop 11/65, M:push 15/30, M:out 24/24, mov_aw_imm 0/24 | M:push 19/142, LS 0/68, M:out 17/51, in_al_dw 18/24 | w1o 5/54, w2o 5/54, w0o 4/51, w0e 10/42, w1e 15/42, w2e 15/42 |
| mul_aw_m_imm16 | 52 / 56 | own | M:out 20/24, nop 18/18, mov_aw_imm 6/6, M:push 6/6 | M:out 30/32, mul_aw_m_imm16 16/18, M:push 6/6 | w2e 7/11, w0e 9/9, w0o 9/9, w1e 9/9, w1o 9/9, w2o 9/9 |
| call_m_dir | 52 / 52 | own | st_acc_dir 42/42, nop 10/10 | br_n1 36/36, M:out 8/8, M:push 8/8 | w1e 9/9, w1o 9/9, w2e 9/9, w2o 9/9, w0e 8/8, w0o 8/8 |
| set1_rb_cl | 50 / 80 | undetermined | M:out 9/30, nop 17/23, set1_rb_cl 15/15, mov_aw_imm 3/6 | M:out 46/56, set1_rb_cl 3/18, nop 1/6 | w1e 8/14, w2e 8/14, w0e 8/13, w0o 8/13, w1o 10/13, w2o 8/13 |
| repc_cmpm_w | 50 / 52 | undetermined | mov_cw_imm2 20/20, mov_cw_imm4 14/14, mov_cw_imm1 12/12, mov_cw_imm0 4/6 | M:out 44/46, M:push 6/6 | w1o 9/10, w2o 10/10, w0e 8/8, w0o 8/8, w1e 8/8, w2e 7/8 |
| mulu_dw | 48 / 48 | own | M:push 24/24, M:out 24/24 | mulu_dw 24/24, M:push 12/12, M:out 12/12 | w0e 8/8, w0o 8/8, w1e 8/8, w1o 8/8, w2e 8/8, w2o 8/8 |
| clr1_mw_cl | 48 / 48 | own | M:out 30/30, nop 12/12, mov_aw_imm 6/6 | M:out 30/30, clr1_mw_cl 12/12, nop 6/6 | w0e 8/8, w0o 8/8, w1e 8/8, w1o 8/8, w2e 8/8, w2o 8/8 |
| and_m_imm8 | 48 / 48 | own | M:push 24/24, M:out 24/24 | and_m_imm8 24/24, M:push 12/12, M:out 12/12 | w0e 8/8, w0o 8/8, w1e 8/8, w1o 8/8, w2e 8/8, w2o 8/8 |
| set1_mw_imm | 46 / 46 | own | M:out 30/30, nop 12/12, mov_aw_imm 4/4 | M:out 28/28, set1_mw_imm 12/12, nop 6/6 | w0e 8/8, w0o 8/8, w1o 8/8, w2o 8/8, w1e 7/7, w2e 7/7 |
| clr1_mw_imm | 46 / 46 | own | M:out 30/30, nop 12/12, mov_aw_imm 4/4 | M:out 28/28, clr1_mw_imm 12/12, nop 6/6 | w0e 8/8, w0o 8/8, w1o 8/8, w2o 8/8, w1e 7/7, w2e 7/7 |
| out_imm_al | 43 / 1804 | successor | M:push 13/240, M:out 11/234, nop 0/210, mov_aw_dw 0/180 | M:out 6/592, M:push 7/506, LS 0/238, nop 2/204 | w2e 8/308, w1e 8/307, w2o 6/307, w1o 5/304, w0e 8/289, w0o 8/289 |
| test_m_imm | 42 / 42 | own | M:push 24/24, M:out 12/12, LS 6/6 | M:push 12/12, test_m_imm 12/12, M:out 12/12, LS 6/6 | w0e 7/7, w0o 7/7, w1e 7/7, w1o 7/7, w2e 7/7, w2o 7/7 |
| or_m_aw | 42 / 48 | undetermined | M:push 24/24, M:out 18/24 | or_m_aw 24/24, M:push 12/12, M:out 6/12 | w0e 6/8, w0o 8/8, w1e 6/8, w1o 8/8, w2e 6/8, w2o 8/8 |
| ins_dl_i11 | 42 / 42 | own | M:out 18/18, nop 18/18, mov_aw_imm 6/6 | M:out 30/30, ins_dl_i11 12/12 | w0e 7/7, w0o 7/7, w1e 7/7, w1o 7/7, w2e 7/7, w2o 7/7 |
| ins_dl_bh | 42 / 42 | own | M:out 18/18, nop 18/18, mov_aw_imm 6/6 | M:out 30/30, ins_dl_bh 12/12 | w0e 7/7, w0o 7/7, w1e 7/7, w1o 7/7, w2e 7/7, w2o 7/7 |
| ext_dl_i11 | 42 / 42 | own | M:out 18/18, nop 18/18, mov_aw_imm 6/6 | M:out 30/30, ext_dl_i11 12/12 | w0e 7/7, w0o 7/7, w1e 7/7, w1o 7/7, w2e 7/7, w2o 7/7 |
| ext_dl_bh | 42 / 42 | own | M:out 18/18, nop 18/18, mov_aw_imm 6/6 | M:out 30/30, ext_dl_bh 12/12 | w0e 7/7, w0o 7/7, w1e 7/7, w1o 7/7, w2e 7/7, w2o 7/7 |
| divu_m | 42 / 42 | own | M:push 18/18, mov_dw_imm0 18/18, M:out 6/6 | divu_m 18/18, M:push 12/12, M:out 12/12 | w0e 7/7, w0o 7/7, w1e 7/7, w1o 7/7, w2e 7/7, w2o 7/7 |
| rep_outm_b | 41 / 42 | own | mov_cw_imm1 12/12, mov_cw_imm0 5/6, mov_cw_imm2 6/6, mov_cw_imm3 6/6 | M:out 41/42 | w0e 7/7, w0o 7/7, w1e 7/7, w1o 7/7, w2e 7/7, w2o 6/7 |
| rep_inm_b | 41 / 42 | own | mov_cw_imm1 12/12, mov_cw_imm0 5/6, mov_cw_imm2 6/6, mov_cw_imm3 6/6 | M:out 41/42 | w0e 7/7, w0o 7/7, w1e 7/7, w1o 7/7, w2e 7/7, w2o 6/7 |
| repnc_cmpm_w | 40 / 42 | undetermined | mov_cw_imm1 12/12, mov_cw_imm2 12/12, mov_cw_imm4 12/12, mov_cw_imm0 4/6 | M:out 40/42 | w0e 7/7, w0o 7/7, w1e 7/7, w1o 6/7, w2e 6/7, w2o 7/7 |
| repnc_cmpbk_w | 40 / 40 | own | mov_cw_imm2 14/14, mov_cw_imm4 14/14, mov_cw_imm1 12/12 | M:out 40/40 | w1o 8/8, w2o 8/8, w0e 6/6, w0o 6/6, w1e 6/6, w2e 6/6 |
| rep_stm_b | 40 / 42 | undetermined | mov_cw_imm1 12/12, mov_cw_imm0 4/6, mov_cw_imm2 6/6, mov_cw_imm3 6/6 | M:out 40/42 | w0e 7/7, w0o 7/7, w1e 6/7, w1o 7/7, w2e 7/7, w2o 6/7 |
| shlb_m_imm4 | 36 / 36 | own | M:out 18/18, M:push 18/18 | shlb_m_imm4 24/24, M:out 6/6, M:push 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| shl_m_imm4 | 36 / 36 | own | M:out 18/18, M:push 18/18 | shl_m_imm4 24/24, M:out 6/6, M:push 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| shl_imm2 | 36 / 36 | own | nop 18/18, M:push 6/6, M:out 6/6, LS 6/6 | LS 24/24, M:push 6/6, M:out 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| shl_imm1 | 36 / 36 | own | nop 18/18, M:push 6/6, M:out 6/6, LS 6/6 | LS 24/24, M:push 6/6, M:out 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| shl_al_imm4 | 36 / 36 | own | M:out 18/18, M:push 18/18 | shl_al_imm4 24/24, M:out 6/6, M:push 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| repc_cmpbk_w | 36 / 36 | own | mov_cw_imm1 12/12, mov_cw_imm2 12/12, mov_cw_imm4 12/12 | M:out 36/36 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| orb_m_imm8_80 | 36 / 36 | own | M:out 18/18, M:push 18/18 | orb_m_imm8_80 24/24, M:out 6/6, M:push 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| les_aw_ix | 36 / 36 | own | M:out 18/18, M:push 18/18 | les_aw_ix 24/24, M:out 6/6, M:push 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| lds_aw_ix | 36 / 36 | own | M:out 18/18, M:push 18/18 | lds_aw_ix 24/24, M:out 6/6, M:push 6/6 | w0e 6/6, w0o 6/6, w1e 6/6, w1o 6/6, w2e 6/6, w2o 6/6 |
| st_dir | 34 / 133 | undetermined | nop 16/66, pfx_nop 2/18, M:out 4/18, M:push 6/12 | M:out 28/64, M:push 3/33, LS 0/24, st_dir 3/12 | w1o 1/23, w2o 1/23, w0o 10/22, w1e 5/22, w2e 5/22, w0e 12/21 |
| st_bw_d16 | 34 / 133 | undetermined | nop 16/66, pfx_nop 2/18, M:out 4/18, M:push 6/12 | M:out 28/64, M:push 3/33, LS 0/24, st_bw_d16 3/12 | w1o 1/23, w2o 1/23, w0o 10/22, w1e 5/22, w2e 5/22, w0e 12/21 |
| st_acc_0c02 | 34 / 120 | undetermined | mov_aw_1000 34/120 | nop 0/20, brf_m_dir 8/20, callf_m_dir 8/20, callf_m_bw 8/20 | w1e 8/24, w1o 8/24, w2e 8/24, w2o 8/24, w0e 1/12, w0o 1/12 |
| rep_movbk_b | 34 / 36 | undetermined | mov_cw_imm0 4/6, mov_cw_imm1 6/6, mov_cw_imm2 6/6, mov_cw_imm3 6/6 | M:out 34/36 | w0e 6/6, w0o 6/6, w1e 5/6, w1o 6/6, w2e 6/6, w2o 5/6 |
| mov_cw_imm0 | 34 / 258 | predecessor | M:out 8/174, M:push 8/30, D 0/18, D4 18/18 | nop 0/36, bcwz_n0 12/36, rep_stm_w 6/24, rep_inm_w 6/24 | w0e 7/43, w0o 7/43, w1e 7/43, w1o 7/43, w2e 3/43, w2o 3/43 |
| mov_m_ds0 | 32 / 36 | undetermined | M:push 12/12, M:out 8/12, nop 12/12 | M:push 18/18, M:out 14/18 | w0e 6/6, w0o 6/6, w1e 4/6, w1o 6/6, w2e 4/6, w2o 6/6 |
| st_imm0_dir_c42 | 30 / 60 | predecessor | PAD 30/30, start 0/30 | LS 30/60 | w0e 10/10, w0o 0/10, w1e 10/10, w1o 0/10, w2e 10/10, w2o 0/10 |
| shl_imm16 | 30 / 30 | own | nop 18/18, LS 12/12 | LS 30/30 | w0e 5/5, w0o 5/5, w1e 5/5, w1o 5/5, w2e 5/5, w2o 5/5 |
| set1_rw_imm | 30 / 90 | undetermined | M:out 6/30, nop 12/30, set1_rw_imm 12/18, mov_aw_imm 0/6 | M:out 27/54, set1_rw_imm 0/18, M:push 3/12, nop 0/6 | w0e 4/15, w0o 6/15, w1e 4/15, w1o 8/15, w2e 2/15, w2o 6/15 |
| mul_m | 30 / 30 | own | M:push 12/12, mov_dw_imm0 12/12, M:out 6/6 | mul_m 12/12, M:out 12/12, M:push 6/6 | w0e 5/5, w0o 5/5, w1e 5/5, w1o 5/5, w2e 5/5, w2o 5/5 |
| ldea_bw_ix | 29 / 39 | undetermined | M:push 8/12, M:out 8/12, nop 10/12, ldea_bw_ix 3/3 | M:push 14/15, ldea_bw_ix 9/12, M:out 6/12 | w0e 5/7, w1e 4/7, w2e 5/7, w0o 6/6, w1o 4/6, w2o 5/6 |
| mov_cw_imm2 | 28 / 560 | predecessor | M:out 5/376, M:push 5/72, clc 0/46, stc 0/30 | rep_stm_w 6/60, nop 2/60, rep_movbk_w 0/42, rep_inm_w 6/36 | w1o 5/96, w2o 3/96, w0e 6/92, w0o 6/92, w1e 5/92, w2e 3/92 |
| set1_rb_imm | 27 / 78 | undetermined | M:out 6/30, nop 9/24, set1_rb_imm 12/18, mov_aw_imm 0/6 | M:out 27/54, set1_rb_imm 0/18, nop 0/6 | w0e 4/13, w0o 5/13, w1e 4/13, w1o 7/13, w2e 2/13, w2o 5/13 |
| bne_n0 | 27 / 337 | pair | cmp_aw_aw 22/250, bne_n0 0/80, cmp_aw_dw 5/7 | M:out 3/83, bne_n0 0/80, nop 0/50, M:push 2/44 | w0o 5/69, w0e 6/68, w1e 5/65, w2e 5/65, w1o 3/35, w2o 3/35 |
| st_acc_0016 | 25 / 50 | undetermined | mov_aw_1000 25/50 | nop 4/20, brk5 20/20, M:out 1/5, M:push 0/5 | w1e 5/10, w1o 5/10, w2e 5/10, w2o 5/10, w0e 3/5, w0o 2/5 |
| test_m_aw_bw_d16 | 24 / 24 | own | M:push 12/12, M:out 12/12 | test_m_aw_bw_d16 12/12, M:push 6/6, M:out 6/6 | w0e 4/4, w0o 4/4, w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4 |
| set1_mw_cl_dir | 24 / 24 | own | M:out 12/12, nop 6/6, mov_aw_imm 6/6 | M:out 24/24 | w0e 4/4, w0o 4/4, w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4 |
| set1_mw_cl_bw_d8 | 24 / 24 | own | M:out 12/12, nop 6/6, mov_aw_imm 6/6 | M:out 24/24 | w0e 4/4, w0o 4/4, w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4 |
| set1_mw_cl_bw_d16 | 24 / 24 | own | M:out 12/12, nop 6/6, mov_aw_imm 6/6 | M:out 24/24 | w0e 4/4, w0o 4/4, w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4 |
| set1_mb_cl | 24 / 24 | own | M:out 18/18, nop 6/6 | M:out 18/18, set1_mb_cl 6/6 | w0e 4/4, w0o 4/4, w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4 |
| push_imm8 | 24 / 24 | own | M:push 12/12, M:out 12/12 | push_imm8 12/12, M:push 6/6, M:out 6/6 | w0e 4/4, w0o 4/4, w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4 |
| not_m | 24 / 179 | undetermined | M:push 6/78, M:out 13/36, not_m 1/35, nop 4/18 | M:push 6/78, M:out 17/47, not_m 1/36, nop 0/6 | w0o 9/30, w1e 2/30, w1o 1/30, w2e 2/30, w2o 1/30, w0e 9/29 |
| mov_cl_imm | 24 / 324 | undetermined | M:out 18/102, M:push 6/54, LS 0/54, nop 0/54 | mov_cl_imm 0/48, out_imm_al 0/42, M:out 0/36, M:push 0/30 | w0e 6/54, w0o 2/54, w1e 6/54, w1o 2/54, w2e 6/54, w2o 2/54 |
| ld_dir | 24 / 180 | undetermined | nop 6/66, M:push 18/36, M:out 0/30, ld_dir 0/18 | M:out 6/78, M:push 6/42, ld_dir 6/24, LS 0/24 | w0o 0/31, w1o 0/31, w2o 0/31, w0e 8/29, w1e 8/29, w2e 8/29 |
| div_m | 24 / 24 | own | M:push 12/12, mov_dw_imm0 12/12 | div_m 12/12, M:push 6/6, M:out 6/6 | w0e 4/4, w0o 4/4, w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4 |
| cmpb_m_imm8_80 | 24 / 24 | own | M:out 12/12, M:push 12/12 | M:out 12/12, M:push 12/12 | w0e 4/4, w0o 4/4, w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4 |
| cmp_m_aw | 24 / 24 | own | M:push 12/12, M:out 6/6, LS 6/6 | M:push 6/6, cmp_m_aw 6/6, M:out 6/6, LS 6/6 | w0e 4/4, w0o 4/4, w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4 |
| call_bw | 24 / 24 | own | mov_bw_t0053 6/6, mov_bw_t0052 6/6, mov_bw_t0054 6/6, mov_bw_t0055 3/3 | br_n1 12/12, M:out 6/6, M:push 6/6 | w0e 4/4, w0o 4/4, w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4 |
| and_m_imm | 24 / 24 | own | M:push 12/12, M:out 12/12 | M:push 12/12, M:out 12/12 | w0e 4/4, w0o 4/4, w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4 |
| and_m_aw | 24 / 30 | undetermined | M:push 12/12, M:out 6/12, LS 6/6 | M:push 12/12, M:out 6/12, LS 6/6 | w0e 3/5, w0o 5/5, w1e 3/5, w1o 5/5, w2e 3/5, w2o 5/5 |
| addb_m_imm8_80 | 24 / 24 | own | M:out 12/12, M:push 12/12 | M:out 12/12, M:push 12/12 | w0e 4/4, w0o 4/4, w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4 |
| add_m_imm8 | 24 / 24 | own | M:push 12/12, M:out 12/12 | M:push 12/12, M:out 12/12 | w0e 4/4, w0o 4/4, w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4 |
| add_m_al | 24 / 30 | undetermined | M:push 18/18, M:out 6/12 | M:push 12/12, M:out 6/12, add_m_al 6/6 | w0e 3/5, w0o 5/5, w1e 3/5, w1o 5/5, w2e 3/5, w2o 5/5 |
| xch_aw_dw | 23 / 504 | undetermined | nop 8/174, M:push 4/84, M:out 7/78, pfx_nop 4/66 | out_imm_al 0/120, out_dw_b 0/72, ld_bw 0/54, st_bw 8/54 | w0e 9/84, w0o 8/84, w1e 3/84, w1o 0/84, w2e 3/84, w2o 0/84 |
| mov_dw_aw | 23 / 342 | undetermined | nop 4/132, pfx_nop 2/66, M:push 6/54, M:out 11/48 | out_dw_b 6/72, ld_bw 0/54, st_bw 4/54, out_imm_al 0/54 | w0e 10/57, w0o 3/57, w1e 4/57, w1o 1/57, w2e 4/57, w2o 1/57 |
| mov_m_ds1 | 22 / 24 | undetermined | nop 12/12, M:out 4/6, M:push 6/6 | M:out 10/12, M:push 12/12 | w0e 4/4, w0o 4/4, w1e 3/4, w1o 4/4, w2e 3/4, w2o 4/4 |
| brf_m_dir | 22 / 22 | own | st_acc_0c02 12/12, nop 10/10 | M:out 8/8, M:push 8/8, nop 6/6 | w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4, w0e 3/3, w0o 3/3 |
| br_m_dir | 22 / 22 | own | st_acc_dir 12/12, nop 10/10 | M:out 8/8, M:push 8/8, nop 6/6 | w1e 4/4, w1o 4/4, w2e 4/4, w2o 4/4, w0e 3/3, w0o 3/3 |
| bcwz_n0 | 22 / 38 | predecessor | mov_cw_imm0 16/24, bcwz_n0 0/8, mov_cw_imm1 6/6 | bcwz_n0 12/20, M:out 5/9, M:push 5/9 | w2e 3/11, w2o 3/11, w0o 4/4, w0e 4/4, w1o 4/4, w1e 4/4 |
| add_m_aw_dir | 22 / 105 | undetermined | nop 8/48, pfx_nop 2/18, M:push 6/12, M:out 2/12 | M:out 16/36, M:push 3/33, LS 0/24, add_m_aw_dir 3/12 | w0o 6/18, w1o 1/18, w2o 1/18, w0e 8/17, w1e 3/17, w2e 3/17 |
| add_m_aw_bw_d16 | 22 / 105 | undetermined | nop 8/48, pfx_nop 2/18, M:push 6/12, M:out 2/12 | M:out 16/36, M:push 3/33, LS 0/24, add_m_aw_bw_d16 3/12 | w0o 6/18, w1o 1/18, w2o 1/18, w0e 8/17, w1e 3/17, w2e 3/17 |
| cvtwl | 21 / 21 | own | M:out 12/12, M:push 6/6, mov_aw_8080 3/3 | M:out 9/9, cvtwl 6/6, M:push 6/6 | w0o 4/4, w1o 4/4, w2o 4/4, w0e 3/3, w1e 3/3, w2e 3/3 |
| cmp4s | 21 / 21 | own | mov_cl_imm 9/9, mov_cl2 6/6, mov_cl8 3/3, mov_cl16 3/3 | M:out 12/12, cmp4s 6/6, M:push 3/3 | w0o 6/6, w1o 6/6, w2o 6/6, w0e 1/1, w1e 1/1, w2e 1/1 |
| test1_rw_cl | 20 / 36 | successor | M:out 8/24, test1_rw_cl 12/12 | M:out 20/24, test1_rw_cl 0/12 | w0e 4/6, w0o 2/6, w1e 4/6, w1o 4/6, w2e 4/6, w2o 2/6 |
| st_bw_d8 | 20 / 136 | undetermined | nop 12/66, pfx_nop 2/18, M:out 4/18, M:push 0/12 | M:out 20/64, M:push 0/36, LS 0/24, st_bw_d8 0/12 | w1e 0/23, w1o 0/23, w2e 0/23, w2o 0/23, w0e 10/22, w0o 10/22 |
| st_acc_000c | 20 / 120 | undetermined | mov_aw_t005c 14/45, mov_aw_t005d 2/27, mov_aw_imm 4/24, mov_aw_t005b 0/21 | mov_aw_1000 20/120 | w0e 10/20, w0o 10/20, w1e 0/20, w1o 0/20, w2e 0/20, w2o 0/20 |
| mov_ds1_m | 20 / 36 | predecessor | M:push 12/12, M:out 0/12, nop 8/12 | M:push 17/18, M:out 3/18 | w0e 3/6, w0o 2/6, w1e 3/6, w1o 4/6, w2e 4/6, w2o 4/6 |
| ldea_bw_ix_d16 | 20 / 40 | undetermined | M:push 4/12, M:out 12/12, nop 4/12, ldea_bw_ix_d16 0/4 | M:push 4/16, M:out 8/12, ldea_bw_ix_d16 8/12 | w1e 2/7, w1o 2/7, w2e 2/7, w2o 2/7, w0e 6/6, w0o 6/6 |
| in_aw_dw | 20 / 47 | predecessor | nop 9/25, M:push 3/6, mov_aw_dw 0/6, M:out 6/6 | M:push 9/29, M:out 11/18 | w1o 2/9, w2o 2/9, w1e 6/8, w2e 6/8, w0o 1/7, w0e 3/6 |
| br_n2 | 19 / 60 | undetermined | call_n2 15/36, M:push 0/6, M:out 2/6, nop 2/6 | nop 19/60 | w0e 2/10, w0o 3/10, w1e 4/10, w1o 4/10, w2e 3/10, w2o 3/10 |
| br_n0 | 19 / 48 | undetermined | M:out 12/24, nop 6/12, M:push 0/6, M:store 1/6 | M:out 15/30, M:store 4/12, M:push 0/6 | w0e 6/8, w0o 6/8, w1e 4/8, w1o 2/8, w2e 1/8, w2o 0/8 |
| xch_m_al | 18 / 18 | own | M:push 12/12, M:out 6/6 | M:push 6/6, xch_m_al 6/6, M:out 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| xch_cw_m | 18 / 18 | own | M:push 12/12, M:out 6/6 | M:push 6/6, xch_cw_m 6/6, M:out 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| test_m_al | 18 / 18 | own | M:push 12/12, M:out 6/6 | M:push 6/6, test_m_al 6/6, M:out 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| sub_m_aw | 18 / 24 | undetermined | M:push 12/12, M:out 6/12 | M:push 12/12, M:out 6/12 | w0e 2/4, w0o 4/4, w1e 2/4, w1o 4/4, w2e 2/4, w2o 4/4 |
| sub4s | 18 / 18 | own | mov_cl2 6/6, mov_cl_imm 6/6, mov_cl8 3/3, mov_cl16 3/3 | M:out 12/12, sub4s 6/6 | w0o 6/6, w1o 6/6, w2o 6/6 |
| shl_m_cl | 18 / 18 | own | M:push 12/12, M:out 6/6 | M:push 6/6, shl_m_cl 6/6, M:out 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| shl_m1_bw_d16 | 18 / 18 | own | nop 12/12, M:out 6/6 | M:out 18/18 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| ror4_dl | 18 / 18 | own | M:out 12/12, M:push 6/6 | M:out 6/6, ror4_dl 6/6, M:push 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| rol4_m | 18 / 18 | own | M:out 12/12, M:push 6/6 | M:out 6/6, rol4_m 6/6, M:push 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| pop_m_ix | 18 / 18 | own | M:push 6/6, M:out 6/6, LS 6/6 | M:push 6/6, M:out 6/6, LS 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| not_m_bw_d16 | 18 / 21 | own | nop 9/12, M:out 6/6, out_dw_b 3/3 | M:out 18/21 | w0o 4/4, w1o 4/4, w2o 4/4, w0e 2/3, w1e 2/3, w2e 2/3 |
| not1_mb_imm | 18 / 18 | own | M:out 12/12, M:push 6/6 | M:out 6/6, not1_mb_imm 6/6, M:push 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| neg_m_bw_d16 | 18 / 21 | own | nop 9/12, M:out 6/6, out_dw_b 3/3 | M:out 18/21 | w0o 4/4, w1o 4/4, w2o 4/4, w0e 2/3, w1e 2/3, w2e 2/3 |
| mul_aw_cw_imm8 | 18 / 18 | own | M:out 18/18 | M:out 12/12, mul_aw_cw_imm8 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| ld_bw_d16 | 18 / 168 | undetermined | nop 6/66, M:out 0/30, M:push 12/24, ld_bw_d16 0/18 | M:out 6/78, M:push 6/42, ld_bw_d16 6/24, LS 0/24 | w0o 0/29, w1o 0/29, w2o 0/29, w0e 6/27, w1e 6/27, w2e 6/27 |
| ins_dl_i7 | 18 / 18 | own | M:out 12/12, M:push 6/6 | M:out 6/6, ins_dl_i7 6/6, M:push 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| inc_m_bw_d16 | 18 / 21 | own | nop 9/12, M:out 6/6, out_dw_b 3/3 | M:out 18/21 | w0o 4/4, w1o 4/4, w2o 4/4, w0e 2/3, w1e 2/3, w2e 2/3 |
| ext_dl_i7 | 18 / 18 | own | M:out 12/12, M:push 6/6 | M:out 6/6, ext_dl_i7 6/6, M:push 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| dec_m_bw_d16 | 18 / 21 | own | nop 9/12, M:out 6/6, out_dw_b 3/3 | M:out 18/21 | w0o 4/4, w1o 4/4, w2o 4/4, w0e 2/3, w1e 2/3, w2e 2/3 |
| cvtbd | 18 / 18 | own | M:out 12/12, M:push 6/6 | M:out 6/6, cvtbd 6/6, M:push 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| cmp_m_al | 18 / 18 | own | M:push 12/12, M:out 6/6 | M:push 6/6, cmp_m_al 6/6, M:out 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| adj4a | 18 / 18 | own | M:out 12/12, M:push 6/6 | M:out 6/6, adj4a 6/6, M:push 6/6 | w0e 3/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| xch_dir_aw | 17 / 18 | own | M:push 12/12, M:out 5/6 | M:push 6/6, xch_dir_aw 6/6, M:out 5/6 | w0e 2/3, w0o 3/3, w1e 3/3, w1o 3/3, w2e 3/3, w2o 3/3 |
| ret | 16 / 179 | undetermined | br_n1 6/146, nop 10/33 | M:push 2/50, call_n2 0/32, nop 0/24, M:out 8/23 | w0e 6/41, w0o 5/40, w2o 1/27, w2e 1/27, w1o 1/25, w1e 2/19 |
| mul_aw_cw_imm16 | 16 / 18 | undetermined | M:out 12/12, M:push 4/6 | M:out 6/6, mul_aw_cw_imm16 6/6, M:push 4/6 | w0e 3/3, w0o 3/3, w1e 2/3, w1o 3/3, w2e 2/3, w2o 3/3 |
| test_dl_al | 14 / 60 | predecessor | test_dl_al 0/24, M:out 14/18, M:push 0/18 | test_dl_al 12/36, M:push 0/18, M:out 2/6 | w0e 3/10, w0o 3/10, w1e 2/10, w1o 2/10, w2e 2/10, w2o 2/10 |
| test_al_imm | 14 / 24 | undetermined | M:push 10/12, M:out 4/12 | M:push 10/12, M:out 4/12 | w0e 2/4, w0o 4/4, w1e 2/4, w1o 2/4, w2e 2/4, w2o 2/4 |
| mov_ss_ix | 14 / 24 | predecessor | nop 8/12, M:out 0/6, M:push 6/6 | M:out 3/12, M:push 11/12 | w0e 2/4, w0o 1/4, w1e 2/4, w1o 3/4, w2e 3/4, w2o 3/4 |
| mov_ds1_ix | 14 / 24 | predecessor | nop 8/12, M:out 0/6, M:push 6/6 | M:out 3/12, M:push 11/12 | w0e 2/4, w0o 1/4, w1e 2/4, w1o 3/4, w2e 3/4, w2o 3/4 |
| mov_ds0_ix | 14 / 24 | predecessor | nop 8/12, M:out 0/6, M:push 6/6 | M:out 3/12, M:push 11/12 | w0e 2/4, w0o 1/4, w1e 2/4, w1o 3/4, w2e 3/4, w2o 3/4 |
| clr1_rw_cl | 13 / 24 | successor | M:out 4/12, clr1_rw_cl 6/6, M:push 3/6 | M:out 10/12, clr1_rw_cl 0/6, M:push 3/6 | w0e 2/4, w0o 2/4, w1e 2/4, w1o 3/4, w2e 2/4, w2o 2/4 |
| br_near_n0 | 13 / 18 | undetermined | M:push 3/6, M:out 5/6, nop 5/6 | M:out 10/12, M:push 3/6 | w0e 2/3, w0o 3/3, w1e 2/3, w1o 3/3, w2e 1/3, w2o 2/3 |
| xorb_m_imm8_80 | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| xor_m_imm8 | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| test1_mw_imm | 12 / 12 | own | M:out 12/12 | M:out 6/6, test1_mw_imm 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| test1_mb_imm | 12 / 12 | own | M:out 12/12 | M:out 6/6, test1_mb_imm 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| test1_mb_cl | 12 / 12 | own | M:out 12/12 | M:out 6/6, test1_mb_cl 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| subcb_m_imm8_80 | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| subc_m_imm8 | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| subb_m_imm8_80 | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| sub_m_imm8 | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| stm_b | 12 / 12 | own | M:out 12/12 | M:out 6/6, stm_b 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| sti | 12 / 12 | own | M:out 12/12 | M:out 6/6, sti 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| st_bw_ix_d8 | 12 / 108 | undetermined | nop 6/48, pfx_nop 2/18, M:push 0/12, st_bw_ix_d8 2/12 | M:push 0/36, M:out 12/36, LS 0/24, st_bw_ix_d8 0/12 | w0e 6/18, w0o 6/18, w1e 0/18, w1o 0/18, w2e 0/18, w2o 0/18 |
| shr_m1 | 12 / 12 | own | M:push 12/12 | shr_m1 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| shlb_m_cl | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| shlb_m1 | 12 / 12 | own | M:push 12/12 | shlb_m1 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| shl_imm33 | 12 / 12 | own | M:push 6/6, M:out 6/6 | M:push 6/6, M:out 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| shl_imm32 | 12 / 12 | own | M:push 6/6, M:out 6/6 | M:push 6/6, M:out 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| shl_imm31 | 12 / 12 | own | M:push 6/6, M:out 6/6 | M:push 6/6, M:out 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| shl_imm255 | 12 / 12 | own | M:push 6/6, M:out 6/6 | M:push 6/6, M:out 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| set1_mb_imm | 12 / 12 | own | M:out 12/12 | M:out 6/6, set1_mb_imm 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| sar_m1 | 12 / 12 | own | M:push 12/12 | sar_m1 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| ror_m1 | 12 / 12 | own | M:push 12/12 | ror_m1 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| ror4_m | 12 / 12 | own | M:out 12/12 | M:out 6/6, ror4_m 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| rol_m1 | 12 / 12 | own | M:push 12/12 | rol_m1 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| repne_cmpbk_w | 12 / 12 | own | mov_cw_imm2 6/6, mov_cw_imm4 6/6 | M:out 12/12 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| repe_cmpm_w | 12 / 12 | own | mov_cw_imm2 6/6, mov_cw_imm4 6/6 | M:out 12/12 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| rcr_m1 | 12 / 12 | own | M:push 12/12 | rcr_m1 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| rcl_m1 | 12 / 12 | own | M:push 12/12 | rcl_m1 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| push_aw | 12 / 354 | predecessor | M:push 1/90, M:out 5/90, D 0/60, push_aw 0/24 | M:out 3/124, M:push 3/122, push_aw 0/24, ld_bw 0/12 | w0e 4/61, w0o 4/61, w2e 1/59, w1e 1/58, w2o 1/58, w1o 1/57 |
| outm_w | 12 / 12 | own | M:out 12/12 | M:out 6/6, outm_w 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| outm_b | 12 / 12 | own | M:out 12/12 | M:out 6/6, outm_b 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| or_m_imm8 | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| or_m_imm | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| not1_mw_imm | 12 / 12 | own | M:out 12/12 | M:out 6/6, not1_mw_imm 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| not1_mw_cl | 12 / 12 | own | M:out 12/12 | M:out 6/6, not1_mw_cl 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| not1_mb_cl | 12 / 12 | own | M:out 12/12 | M:out 6/6, not1_mb_cl 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| mulub_m | 12 / 12 | own | M:push 12/12 | mulub_m 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| movbk_b | 12 / 12 | own | M:out 12/12 | M:out 6/6, movbk_b 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| mov_cw_aw | 12 / 48 | undetermined | M:push 6/24, M:out 6/12, LS 0/12 | in_al_dw 9/24, out_dw_b 3/18, out_dw_al 0/6 | w0e 3/8, w0o 1/8, w1e 3/8, w1o 1/8, w2e 3/8, w2o 1/8 |
| ldm_w | 12 / 12 | own | M:out 12/12 | M:out 6/6, ldm_w 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| ldm_b | 12 / 12 | own | M:out 12/12 | M:out 6/6, ldm_b 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| ins_dl_dh | 12 / 12 | own | M:out 12/12 | M:out 6/6, ins_dl_dh 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| ins_bh_bl | 12 / 12 | own | M:out 12/12 | M:out 6/6, ins_bh_bl 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| inm_b | 12 / 12 | own | M:out 12/12 | M:out 6/6, inm_b 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| ext_bh_bl | 12 / 12 | own | M:out 12/12 | M:out 6/6, ext_bh_bl 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| divu_ix | 12 / 12 | own | M:push 6/6, M:out 6/6 | M:push 6/6, M:out 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| divu_cw | 12 / 12 | own | mov_dw_imm0 12/12 | M:out 6/6, divu_cw 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| div_cw | 12 / 12 | own | mov_dw_imm0 12/12 | M:out 6/6, div_cw 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| cmpm_w | 12 / 12 | own | M:out 12/12 | M:out 6/6, cmpm_w 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| cmpm_b | 12 / 12 | own | M:out 12/12 | M:out 6/6, cmpm_b 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| cmpbk_b | 12 / 12 | own | M:out 12/12 | M:out 6/6, cmpbk_b 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| cmpb_m_imm8_82 | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| clr1_mb_imm | 12 / 12 | own | M:out 12/12 | M:out 6/6, clr1_mb_imm 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| clr1_mb_cl | 12 / 12 | own | M:out 12/12 | M:out 6/6, clr1_mb_cl 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| callf_m_dir | 12 / 12 | own | st_acc_0c02 12/12 | br_n1 6/6, M:out 3/3, M:push 3/3 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| callf_m_bw | 12 / 12 | own | st_acc_0c02 12/12 | br_n1 6/6, M:out 3/3, M:push 3/3 | w0o 2/2, w0e 2/2, w1o 2/2, w1e 2/2, w2o 2/2, w2e 2/2 |
| call_m_bw | 12 / 12 | own | st_acc_dir 12/12 | br_n1 6/6, M:out 3/3, M:push 3/3 | w0o 2/2, w0e 2/2, w1o 2/2, w1e 2/2, w2o 2/2, w2e 2/2 |
| brf_m_bw | 12 / 12 | own | st_acc_0c02 12/12 | nop 6/6, M:out 3/3, M:push 3/3 | w0o 2/2, w0e 2/2, w1o 2/2, w1e 2/2, w2o 2/2, w2e 2/2 |
| br_m_bw | 12 / 12 | own | st_acc_dir 12/12 | nop 6/6, M:out 3/3, M:push 3/3 | w0o 2/2, w0e 2/2, w1o 2/2, w1e 2/2, w2o 2/2, w2e 2/2 |
| andb_m_imm8_80 | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| adjbs | 12 / 12 | own | M:out 12/12 | M:out 6/6, adjbs 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| adjba | 12 / 12 | own | M:out 12/12 | M:out 6/6, adjba 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| adj4s | 12 / 12 | own | M:out 12/12 | M:out 6/6, adj4s 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| addcb_m_imm8_80 | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| addc_m_imm8 | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| addb_m_imm8_82 | 12 / 12 | own | M:out 6/6, M:push 6/6 | M:out 6/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| add_m_aw_bw_ix_d8 | 12 / 108 | undetermined | nop 6/48, pfx_nop 2/18, M:push 0/12, add_m_aw_bw_ix_d8 2/12 | M:push 0/36, M:out 12/36, LS 0/24, add_m_aw_bw_ix_d8 0/12 | w0e 6/18, w0o 6/18, w1e 0/18, w1o 0/18, w2e 0/18, w2o 0/18 |
| add_m_aw_bw_d8 | 12 / 108 | undetermined | nop 6/48, pfx_nop 2/18, M:push 0/12, add_m_aw_bw_d8 2/12 | M:push 0/36, M:out 12/36, LS 0/24, add_m_aw_bw_d8 0/12 | w0e 6/18, w0o 6/18, w1e 0/18, w1o 0/18, w2e 0/18, w2o 0/18 |
| add_aw_imm81 | 12 / 18 | undetermined | nop 10/12, M:push 2/6 | LS 10/12, M:push 2/6 | w0e 3/3, w0o 3/3, w1e 2/3, w1o 1/3, w2e 2/3, w2o 1/3 |
| cvtdb | 11 / 12 | own | M:out 11/12 | M:out 5/6, cvtdb 6/6 | w0e 1/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2 |
| test_aw_imm | 10 / 12 | undetermined | M:push 4/6, M:out 6/6 | M:push 4/6, M:out 6/6 | w0e 2/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| test1_rb_cl | 10 / 18 | successor | M:out 4/12, test1_rb_cl 6/6 | M:out 10/12, test1_rb_cl 0/6 | w0e 2/3, w0o 1/3, w1e 2/3, w1o 2/3, w2e 2/3, w2o 1/3 |
| st_bw_ix | 10 / 84 | undetermined | nop 6/48, pfx_nop 2/18, M:push 0/6, M:out 2/6 | M:push 0/30, M:out 10/30, LS 0/24 | w0e 5/14, w0o 5/14, w1e 0/14, w1o 0/14, w2e 0/14, w2o 0/14 |
| st_acc_0014 | 10 / 60 | undetermined | mov_aw_imm 4/24, mov_aw_t005d 4/15, mov_aw_t005e 2/12, mov_aw_t005c 0/6 | mov_aw_1000 10/60 | w0e 5/10, w0o 5/10, w1e 0/10, w1o 0/10, w2e 0/10, w2o 0/10 |
| not1_rw_cl | 10 / 18 | successor | M:out 4/12, not1_rw_cl 6/6 | M:out 10/12, not1_rw_cl 0/6 | w0e 2/3, w0o 1/3, w1e 2/3, w1o 2/3, w2e 2/3, w2o 1/3 |
| not1_rb_cl | 10 / 18 | successor | M:out 4/12, not1_rb_cl 6/6 | M:out 10/12, not1_rb_cl 0/6 | w0e 2/3, w0o 1/3, w1e 2/3, w1o 2/3, w2e 2/3, w2o 1/3 |
| mov_m_ss | 10 / 12 | undetermined | M:out 4/6, M:push 6/6 | M:out 4/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| mov_m_ps | 10 / 12 | undetermined | M:out 4/6, M:push 6/6 | M:out 4/6, M:push 6/6 | w0e 2/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| ld_bw_iy_d16 | 10 / 12 | undetermined | M:push 4/6, M:out 6/6 | M:push 4/6, M:out 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 1/2, w2e 2/2, w2o 1/2 |
| ld_bp_ix_d16 | 10 / 12 | undetermined | M:push 4/6, M:out 6/6 | M:push 4/6, M:out 6/6 | w0e 2/2, w0o 2/2, w1e 2/2, w1o 1/2, w2e 2/2, w2o 1/2 |
| dec_m | 10 / 71 | undetermined | M:push 0/24, M:out 5/18, nop 4/12, dec_m 1/11 | M:push 0/30, M:out 9/29, dec_m 1/12 | w0o 5/12, w1e 0/12, w1o 0/12, w2e 0/12, w2o 0/12, w0e 5/11 |
| dbnz_m3 | 10 / 10 | undetermined | nop 10/10 | M:out 5/5, M:push 5/5 | w1e 2/2, w1o 2/2, w2e 2/2, w2o 2/2, w0o 1/1, w0e 1/1 |
| cmp_dir_aw | 10 / 12 | undetermined | M:push 6/6, M:out 4/6 | M:push 6/6, M:out 4/6 | w0e 1/2, w0o 2/2, w1e 2/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| cmp_aw_imm16 | 10 / 12 | undetermined | M:out 6/6, M:push 4/6 | M:out 6/6, M:push 4/6 | w0e 2/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| clr1_rb_cl | 10 / 18 | successor | M:out 4/12, clr1_rb_cl 6/6 | M:out 10/12, clr1_rb_cl 0/6 | w0e 2/3, w0o 1/3, w1e 2/3, w1o 2/3, w2e 2/3, w2o 1/3 |
| cli | 10 / 12 | undetermined | M:out 10/12 | M:out 4/6, cli 6/6 | w0e 2/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| add_m_aw_bw_ix | 10 / 84 | undetermined | nop 6/48, pfx_nop 2/18, M:push 0/6, M:out 2/6 | M:push 0/30, M:out 10/30, LS 0/24 | w0e 5/14, w0o 5/14, w1e 0/14, w1o 0/14, w2e 0/14, w2o 0/14 |
| xor_m_aw | 9 / 12 | undetermined | M:out 3/6, M:push 6/6 | M:out 3/6, M:push 6/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| xor_m_al | 9 / 12 | undetermined | M:out 3/6, M:push 6/6 | M:out 3/6, M:push 6/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| subc_m_aw | 9 / 12 | undetermined | M:out 3/6, M:push 6/6 | M:out 3/6, M:push 6/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| subc_m_al | 9 / 12 | undetermined | M:out 3/6, M:push 6/6 | M:out 3/6, M:push 6/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| sub_m_al | 9 / 12 | undetermined | M:out 3/6, M:push 6/6 | M:out 3/6, M:push 6/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| st_imm0_dir_a42 | 9 / 18 | predecessor | PAD 9/9, start 0/9 | LS 9/18 | w0e 3/3, w0o 0/3, w1e 3/3, w1o 0/3, w2e 3/3, w2o 0/3 |
| or_m_al | 9 / 12 | undetermined | M:out 3/6, M:push 6/6 | M:out 3/6, M:push 6/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| mov_cl8 | 9 / 78 | undetermined | LS 0/36, M:out 9/24, nop 0/18 | shl_aw_cl 0/24, nop 0/18, M:out 0/12, M:push 0/6 | w0e 3/13, w0o 0/13, w1e 3/13, w1o 0/13, w2e 3/13, w2o 0/13 |
| mov_cl16 | 9 / 66 | undetermined | LS 0/24, M:out 9/24, nop 0/18 | shl_aw_cl 0/24, nop 0/18, M:out 0/6, add4s 3/6 | w0e 3/11, w0o 0/11, w1e 3/11, w1o 0/11, w2e 3/11, w2o 0/11 |
| ld_ix_d16 | 9 / 96 | undetermined | nop 3/48, pfx_nop 0/18, M:push 6/12, M:out 0/12 | M:push 6/36, M:out 3/36, LS 0/24 | w0e 3/16, w0o 0/16, w1e 3/16, w1o 0/16, w2e 3/16, w2o 0/16 |
| brf_t0053 | 9 / 15 | successor | M:out 9/12, M:push 0/3 | nop 0/6, brf_t0058 6/6, M:out 3/3 | w0e 3/4, w1e 3/4, w2e 3/4, w0o 0/1, w1o 0/1, w2o 0/1 |
| brf_t0051 | 9 / 9 | own | M:push 9/9 | brf_t0056 6/6, M:push 3/3 | w0o 3/3, w1o 3/3, w2o 3/3 |
| br_near_n1 | 9 / 18 | undetermined | M:push 3/6, M:out 3/6, nop 3/6 | nop 9/18 | w0e 1/3, w0o 2/3, w1e 1/3, w1o 2/3, w2e 1/3, w2o 2/3 |
| bpe_n0 | 9 / 11 | own | cmp_aw_aw 5/7, add_dw_imm2a01 4/4 | M:push 6/8, M:out 3/3 | w0o 1/2, w1o 2/2, w1e 2/2, w2o 2/2, w2e 2/2, w0e 0/1 |
| bnv_n0 | 9 / 11 | own | cmp_aw_aw 5/7, add_dw_imm2a01 4/4 | M:push 6/8, M:out 3/3 | w0o 1/2, w1o 2/2, w1e 2/2, w2o 2/2, w2e 2/2, w0e 0/1 |
| bnh_n0 | 9 / 11 | own | cmp_aw_aw 5/7, add_dw_imm2a01 4/4 | M:push 6/8, M:out 3/3 | w0o 1/2, w1o 2/2, w1e 2/2, w2o 2/2, w2e 2/2, w0e 0/1 |
| ble_n0 | 9 / 11 | own | cmp_aw_aw 5/7, add_dw_imm2a01 4/4 | M:push 6/8, M:out 3/3 | w0o 1/2, w1o 2/2, w1e 2/2, w2o 2/2, w2e 2/2, w0e 0/1 |
| and_m_al | 9 / 12 | undetermined | M:out 3/6, M:push 6/6 | M:out 3/6, M:push 6/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| addc_m_aw | 9 / 12 | undetermined | M:out 3/6, M:push 6/6 | M:out 3/6, M:push 6/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| addc_m_al | 9 / 12 | undetermined | M:out 3/6, M:push 6/6 | M:out 3/6, M:push 6/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 2/2 |
| neg_m | 8 / 66 | undetermined | M:push 0/24, neg_m 0/12, M:out 4/12, nop 4/12 | M:push 0/30, M:out 8/24, neg_m 0/12 | w0e 4/11, w0o 4/11, w1e 0/11, w1o 0/11, w2e 0/11, w2o 0/11 |
| ldea_bw_iy_d16 | 8 / 12 | undetermined | M:push 2/6, M:out 6/6 | M:push 2/6, M:out 6/6 | w0e 2/2, w0o 2/2, w1e 1/2, w1o 1/2, w2e 1/2, w2o 1/2 |
| ldea_bp_iy_d16 | 8 / 12 | undetermined | M:push 2/6, M:out 6/6 | M:push 2/6, M:out 6/6 | w0e 2/2, w0o 2/2, w1e 1/2, w1o 1/2, w2e 1/2, w2o 1/2 |
| ldea_bp_ix_d16 | 8 / 12 | undetermined | M:push 2/6, M:out 6/6 | M:push 2/6, M:out 6/6 | w0e 2/2, w0o 2/2, w1e 1/2, w1o 1/2, w2e 1/2, w2o 1/2 |
| ld_bw | 8 / 1182 | undetermined | nop 0/162, M:push 0/114, M:out 2/114, mov_aw_dw 0/96 | M:out 3/518, M:push 3/412, LS 0/150, ld_bw 0/42 | w1e 1/202, w2e 1/201, w1o 1/198, w2o 1/198, w0e 3/192, w0o 1/191 |
| lahf | 8 / 96 | undetermined | lahf 0/48, M:out 5/24, M:push 3/24 | lahf 0/48, M:out 0/18, M:push 0/18, sahf 8/12 | w0e 1/16, w0o 2/16, w1e 1/16, w1o 2/16, w2e 0/16, w2o 2/16 |
| be_n2 | 8 / 18 | undetermined | cmp_aw_aw 8/12, cmp_aw_dw 0/6 | nop 8/18 | w0e 2/4, w0o 0/4, w1o 2/3, w2o 2/3, w1e 1/2, w2e 1/2 |
| ldea_iy | 7 / 12 | undetermined | M:push 5/6, M:out 2/6 | M:push 5/6, M:out 2/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 1/2, w2e 1/2, w2o 1/2 |
| ldea_ix | 7 / 12 | undetermined | M:push 5/6, M:out 2/6 | M:push 5/6, M:out 2/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 1/2, w2e 1/2, w2o 1/2 |
| ldea_bw_iy | 7 / 12 | undetermined | M:push 5/6, M:out 2/6 | M:push 5/6, M:out 2/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 1/2, w2e 1/2, w2o 1/2 |
| ldea_bp_iy | 7 / 12 | undetermined | M:push 5/6, M:out 2/6 | M:push 5/6, M:out 2/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 1/2, w2e 1/2, w2o 1/2 |
| ldea_bp_ix | 7 / 12 | undetermined | M:push 5/6, M:out 2/6 | M:push 5/6, M:out 2/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 1/2, w2e 1/2, w2o 1/2 |
| cmp_al_imm8 | 7 / 12 | undetermined | M:out 2/6, M:push 5/6 | M:out 2/6, M:push 5/6 | w0e 1/2, w0o 2/2, w1e 1/2, w1o 1/2, w2e 1/2, w2o 1/2 |
| br_near_n2 | 7 / 12 | undetermined | M:push 3/6, M:out 4/6 | nop 7/12 | w0e 1/2, w0o 1/2, w1e 1/2, w1o 2/2, w2e 1/2, w2o 1/2 |
| test1_rw_imm | 6 / 18 | undetermined | M:out 3/12, test1_rw_imm 3/6 | M:out 6/12, test1_rw_imm 0/6 | w0e 1/3, w0o 1/3, w1e 1/3, w1o 2/3, w2e 0/3, w2o 1/3 |
| test1_rb_imm | 6 / 18 | undetermined | M:out 3/12, test1_rb_imm 3/6 | M:out 6/12, test1_rb_imm 0/6 | w0e 1/3, w0o 1/3, w1e 1/3, w1o 2/3, w2e 0/3, w2o 1/3 |
| repne_cmpbk_b | 6 / 6 | own | mov_cw_imm4 6/6 | M:out 6/6 | w0e 1/1, w0o 1/1, w1e 1/1, w1o 1/1, w2e 1/1, w2o 1/1 |
| repe_cmpm_b | 6 / 6 | own | mov_cw_imm4 6/6 | M:out 6/6 | w0e 1/1, w0o 1/1, w1e 1/1, w1o 1/1, w2e 1/1, w2o 1/1 |
| pfx_add4s | 6 / 6 | own | mov_cl_imm 6/6 | M:out 6/6 | w0e 1/1, w0o 1/1, w1e 1/1, w1o 1/1, w2e 1/1, w2o 1/1 |
| out_dw_al | 6 / 212 | undetermined | nop 2/45, M:push 0/30, out_dw_al 0/24, M:out 0/24 | M:push 6/132, M:out 0/38, out_dw_al 0/24, LS 0/18 | w1o 0/38, w2o 0/38, w0o 0/35, w1e 3/35, w2e 3/35, w0e 0/31 |
| not1_rw_imm | 6 / 18 | undetermined | M:out 3/12, not1_rw_imm 3/6 | M:out 6/12, not1_rw_imm 0/6 | w0e 1/3, w0o 1/3, w1e 1/3, w1o 2/3, w2e 0/3, w2o 1/3 |
| not1_rb_imm | 6 / 18 | undetermined | M:out 3/12, not1_rb_imm 3/6 | M:out 6/12, not1_rb_imm 0/6 | w0e 1/3, w0o 1/3, w1e 1/3, w1o 2/3, w2e 0/3, w2o 1/3 |
| ldea_bw_d8 | 6 / 48 | undetermined | M:push 1/12, ldea_bw_d8 2/12, M:out 0/12, nop 3/12 | M:push 6/18, M:out 0/18, ldea_bw_d8 0/12 | w0e 0/8, w0o 1/8, w1e 0/8, w1o 2/8, w2e 2/8, w2o 1/8 |
| ld_dw_dir | 6 / 12 | undetermined | M:push 6/12 | out_dw_al 3/6, in_al_dw 3/6 | w0e 2/2, w0o 0/2, w1e 2/2, w1o 0/2, w2e 2/2, w2o 0/2 |
| clr1_rw_imm | 6 / 18 | undetermined | M:out 3/12, clr1_rw_imm 3/6 | M:out 6/12, clr1_rw_imm 0/6 | w0e 1/3, w0o 1/3, w1e 1/3, w1o 2/3, w2e 0/3, w2o 1/3 |
| clr1_rb_imm | 6 / 18 | undetermined | M:out 3/12, clr1_rb_imm 3/6 | M:out 6/12, clr1_rb_imm 0/6 | w0e 1/3, w0o 1/3, w1e 1/3, w1o 2/3, w2e 0/3, w2o 1/3 |
| brk5 | 6 / 6 | own | nop 6/6 | br_n1 6/6 | w0e 1/1, w0o 1/1, w1e 1/1, w1o 1/1, w2e 1/1, w2o 1/1 |
| brk3 | 6 / 6 | own | nop 6/6 | br_n1 6/6 | w0e 1/1, w0o 1/1, w1e 1/1, w1o 1/1, w2e 1/1, w2o 1/1 |
| br_near_n3 | 6 / 12 | undetermined | M:push 3/6, M:out 3/6 | nop 6/12 | w0e 1/2, w0o 1/2, w1e 1/2, w1o 1/2, w2e 1/2, w2o 1/2 |
| be_n1 | 6 / 8 | own | cmp_aw_aw 6/8 | nop 6/8 | w0e 1/2, w0o 1/2, w1e 1/1, w1o 1/1, w2e 1/1, w2o 1/1 |
| and_dir_aw | 6 / 12 | undetermined | M:push 5/6, M:out 1/6 | M:push 5/6, M:out 1/6 | w0e 2/2, w0o 0/2, w1e 1/2, w1o 1/2, w2e 1/2, w2o 1/2 |
| push_ds0 | 5 / 60 | undetermined | M:push 5/30, M:out 0/30 | pop_ds0 4/48, M:push 1/6, M:out 0/6 | w0e 0/10, w0o 0/10, w1e 0/10, w1o 0/10, w2e 5/10, w2o 0/10 |
| pfx_set1_mb_imm | 5 / 6 | own | M:out 5/6 | M:out 5/6 | w0e 1/1, w0o 0/1, w1e 1/1, w1o 1/1, w2e 1/1, w2o 1/1 |
| pfx_rol4_m | 5 / 6 | own | M:out 5/6 | M:out 5/6 | w0e 1/1, w0o 0/1, w1e 1/1, w1o 1/1, w2e 1/1, w2o 1/1 |
| bp_n0 | 5 / 17 | predecessor | cmp_aw_dw 0/10, cmp_aw_aw 5/7 | M:out 3/9, M:push 2/8 | w0o 1/4, w0e 0/3, w1e 1/3, w2e 1/3, w1o 1/2, w2o 1/2 |
| bnc_n0 | 5 / 17 | predecessor | cmp_aw_dw 0/10, cmp_aw_aw 5/7 | M:out 3/9, M:push 2/8 | w0o 1/4, w0e 0/3, w1e 1/3, w2e 1/3, w1o 1/2, w2o 1/2 |
| bn_n0 | 5 / 17 | predecessor | cmp_aw_aw 0/10, cmp_aw_dw 5/7 | M:out 3/9, M:push 2/8 | w0o 1/4, w0e 0/3, w1e 1/3, w2e 1/3, w1o 1/2, w2o 1/2 |
| blt_n0 | 5 / 17 | predecessor | cmp_aw_aw 0/10, cmp_aw_dw 5/7 | M:out 3/9, M:push 2/8 | w0o 1/4, w0e 0/3, w1e 1/3, w2e 1/3, w1o 1/2, w2o 1/2 |
| bge_n0 | 5 / 17 | predecessor | cmp_aw_dw 0/10, cmp_aw_aw 5/7 | M:out 3/9, M:push 2/8 | w0o 1/4, w0e 0/3, w1e 1/3, w2e 1/3, w1o 1/2, w2o 1/2 |
| bc_n0 | 5 / 17 | predecessor | cmp_aw_aw 0/10, cmp_aw_dw 5/7 | M:out 3/9, M:push 2/8 | w0o 1/4, w0e 0/3, w1e 1/3, w2e 1/3, w1o 1/2, w2o 1/2 |
| stb_bw | 4 / 35 | undetermined | M:push 0/12, M:out 3/12, stb_bw 1/11 | M:push 0/12, stb_bw 1/12, M:out 3/11 | w0o 2/6, w1e 0/6, w1o 0/6, w2e 0/6, w2o 0/6, w0e 2/5 |
| push_imm16 | 4 / 36 | undetermined | M:push 0/12, push_imm16 2/12, M:out 2/12 | M:push 0/12, push_imm16 0/12, M:out 4/12 | w0e 2/6, w0o 2/6, w1e 0/6, w1o 0/6, w2e 0/6, w2o 0/6 |
| mov_aw_imm | 4 / 1332 | undetermined | M:out 4/450, nop 0/240, M:push 0/162, mov_aw_imm 0/138 | mov_aw_imm 0/138, out_imm_al 0/126, mov_dw_imm0 0/96, out_dw_b 0/90 | w0e 0/222, w0o 0/222, w1e 2/222, w1o 0/222, w2e 2/222, w2o 0/222 |
| incb_m | 4 / 17 | undetermined | M:out 3/12, incb_m 1/5 | M:out 3/11, incb_m 1/6 | w0o 2/3, w1e 0/3, w1o 0/3, w2e 0/3, w2o 0/3, w0e 2/2 |
| decb_m | 4 / 17 | undetermined | M:out 3/12, decb_m 1/5 | M:out 3/11, decb_m 1/6 | w0o 2/3, w1e 0/3, w1o 0/3, w2e 0/3, w2o 0/3, w0e 2/2 |
| dbnz_n2 | 4 / 8 | undetermined | mov_cw_imm2 4/8 | nop 4/8 | w2e 0/2, w2o 0/2, w0e 1/1, w0o 1/1, w1e 1/1, w1o 1/1 |
| callf_t0053 | 4 / 12 | undetermined | M:push 3/9, M:out 1/3 | br_n1 3/9, M:out 1/3 | w0o 3/3, w1o 0/3, w2o 0/3, w0e 1/1, w1e 0/1, w2e 0/1 |
| bv_n0 | 4 / 14 | undetermined | cmp_aw_aw 0/10, add_dw_imm2a01 4/4 | M:push 4/8, M:out 0/6 | w1e 1/3, w2e 1/3, w0e 0/2, w0o 0/2, w1o 1/2, w2o 1/2 |
| brf_t0057 | 4 / 12 | undetermined | brf_t0052 4/12 | brf_t005c 2/6, M:out 1/3, M:push 1/3 | w0o 2/2, w0e 2/2, w1o 0/2, w1e 0/2, w2o 0/2, w2e 0/2 |
| bpo_n0 | 4 / 14 | undetermined | cmp_aw_aw 0/10, add_dw_imm2a01 4/4 | M:push 4/8, M:out 0/6 | w1e 1/3, w2e 1/3, w0e 0/2, w0o 0/2, w1o 1/2, w2o 1/2 |
| bh_n0 | 4 / 14 | undetermined | cmp_aw_aw 0/10, add_dw_imm2a01 4/4 | M:push 4/8, M:out 0/6 | w1e 1/3, w2e 1/3, w0e 0/2, w0o 0/2, w1o 1/2, w2o 1/2 |
| bgt_n0 | 4 / 14 | undetermined | cmp_aw_aw 0/10, add_dw_imm2a01 4/4 | M:push 4/8, M:out 0/6 | w1e 1/3, w2e 1/3, w0e 0/2, w0o 0/2, w1o 1/2, w2o 1/2 |
| be_n7 | 4 / 8 | undetermined | cmp_aw_aw 4/8 | nop 4/8 | w0e 0/2, w0o 0/2, w1e 1/1, w1o 1/1, w2e 1/1, w2o 1/1 |
| be_n6 | 4 / 8 | undetermined | cmp_aw_aw 4/8 | nop 4/8 | w0e 0/2, w0o 0/2, w1e 1/1, w1o 1/1, w2e 1/1, w2o 1/1 |
| be_n5 | 4 / 8 | undetermined | cmp_aw_aw 4/8 | nop 4/8 | w0e 0/2, w0o 0/2, w1e 1/1, w1o 1/1, w2e 1/1, w2o 1/1 |
| be_n4 | 4 / 8 | undetermined | cmp_aw_aw 4/8 | nop 4/8 | w0e 0/2, w0o 0/2, w1e 1/1, w1o 1/1, w2e 1/1, w2o 1/1 |
| be_n3 | 4 / 8 | undetermined | cmp_aw_aw 4/8 | nop 4/8 | w0e 0/2, w0o 0/2, w1e 1/1, w1o 1/1, w2e 1/1, w2o 1/1 |
| bcwz_n2 | 4 / 8 | undetermined | mov_cw_imm0 4/8 | nop 4/8 | w2e 0/2, w2o 0/2, w0o 1/1, w0e 1/1, w1o 1/1, w1e 1/1 |
| pfx_test1_mw_cl | 3 / 6 | undetermined | M:out 3/6 | M:out 3/6 | w0e 1/1, w0o 0/1, w1e 1/1, w1o 0/1, w2e 1/1, w2o 0/1 |
| mov_aw_8080 | 3 / 18 | undetermined | M:out 3/18 | M:out 0/6, cvtbw 0/6, cvtwl 3/6 | w0e 1/3, w0o 0/3, w1e 1/3, w1o 0/3, w2e 1/3, w2o 0/3 |
| ldea_bw_ix_d8 | 3 / 36 | undetermined | M:push 1/12, ldea_bw_ix_d8 2/12, M:out 0/12 | M:push 3/12, ldea_bw_ix_d8 0/12, M:out 0/12 | w0e 0/6, w0o 0/6, w1e 0/6, w1o 1/6, w2e 1/6, w2o 1/6 |
| ld_iy_d16 | 3 / 12 | undetermined | M:push 3/6, M:out 0/6 | M:push 3/6, M:out 0/6 | w0e 1/2, w0o 0/2, w1e 1/2, w1o 0/2, w2e 1/2, w2o 0/2 |
| ld_bp_d16 | 3 / 12 | undetermined | M:push 3/6, M:out 0/6 | M:push 3/6, M:out 0/6 | w0e 1/2, w0o 0/2, w1e 1/2, w1o 0/2, w2e 1/2, w2o 0/2 |
| callf_t0055 | 3 / 13 | undetermined | M:out 3/9, push_aw 0/4 | br_n1 3/9, br_n3 0/4 | w1e 0/4, w2e 0/4, w0e 3/3, w1o 0/1, w2o 0/1 |
| call_n0 | 3 / 12 | undetermined | M:push 0/6, M:out 3/6 | M:push 0/6, M:out 3/6 | w0e 1/2, w0o 1/2, w1e 0/2, w1o 1/2, w2e 0/2, w2o 0/2 |
| brf_t0054 | 3 / 3 | undetermined | M:out 3/3 | nop 3/3 | w0e 1/1, w1e 1/1, w2e 1/1 |
| brf_t0052 | 3 / 21 | undetermined | M:push 3/12, M:out 0/9 | brf_t0057 0/12, M:out 0/3, M:push 0/3, nop 3/3 | w0o 1/4, w1o 1/4, w2o 1/4, w0e 0/3, w1e 0/3, w2e 0/3 |
| bpe_n2 | 3 / 4 | undetermined | cmp_aw_aw 3/4 | nop 3/4 | w0e 1/1, w0o 0/1, w1o 1/1, w2o 1/1 |
| bp_n2 | 3 / 10 | undetermined | cmp_aw_dw 0/6, cmp_aw_aw 3/4 | nop 3/10 | w0e 1/2, w0o 0/2, w1o 1/2, w2o 1/2, w1e 0/1, w2e 0/1 |
| bnv_n2 | 3 / 4 | undetermined | cmp_aw_aw 3/4 | nop 3/4 | w0e 1/1, w0o 0/1, w1o 1/1, w2o 1/1 |
| bnh_n2 | 3 / 4 | undetermined | cmp_aw_aw 3/4 | nop 3/4 | w0e 1/1, w0o 0/1, w1o 1/1, w2o 1/1 |
| bne_n2 | 3 / 20 | undetermined | cmp_aw_aw 0/16, cmp_aw_dw 3/4 | nop 3/20 | w0e 1/4, w0o 0/4, w1e 0/3, w1o 1/3, w2e 0/3, w2o 1/3 |
| bnc_n2 | 3 / 10 | undetermined | cmp_aw_dw 0/6, cmp_aw_aw 3/4 | nop 3/10 | w0e 1/2, w0o 0/2, w1o 1/2, w2o 1/2, w1e 0/1, w2e 0/1 |
| bn_n2 | 3 / 10 | undetermined | cmp_aw_aw 0/6, cmp_aw_dw 3/4 | nop 3/10 | w0e 1/2, w0o 0/2, w1o 1/2, w2o 1/2, w1e 0/1, w2e 0/1 |
| blt_n2 | 3 / 10 | undetermined | cmp_aw_aw 0/6, cmp_aw_dw 3/4 | nop 3/10 | w0e 1/2, w0o 0/2, w1o 1/2, w2o 1/2, w1e 0/1, w2e 0/1 |
| ble_n2 | 3 / 4 | undetermined | cmp_aw_aw 3/4 | nop 3/4 | w0e 1/1, w0o 0/1, w1o 1/1, w2o 1/1 |
| bge_n2 | 3 / 10 | undetermined | cmp_aw_dw 0/6, cmp_aw_aw 3/4 | nop 3/10 | w0e 1/2, w0o 0/2, w1o 1/2, w2o 1/2, w1e 0/1, w2e 0/1 |
| bc_n2 | 3 / 10 | undetermined | cmp_aw_aw 0/6, cmp_aw_dw 3/4 | nop 3/10 | w0e 1/2, w0o 0/2, w1o 1/2, w2o 1/2, w1e 0/1, w2e 0/1 |
| st_al_dir | 2 / 12 | undetermined | M:out 2/6, M:push 0/6 | M:out 2/6, M:push 0/6 | w0e 1/2, w0o 1/2, w1e 0/2, w1o 0/2, w2e 0/2, w2o 0/2 |
| repne_cmpm_b | 2 / 2 | undetermined | mov_cw_imm4 2/2 | M:out 2/2 | w1o 1/1, w2o 1/1 |
| repe_cmpbk_b | 2 / 2 | undetermined | mov_cw_imm4 2/2 | M:out 2/2 | w1o 1/1, w2o 1/1 |
| push_ds1 | 2 / 24 | undetermined | M:push 2/12, M:out 0/12 | pop_ds1 1/12, M:push 1/6, M:out 0/6 | w0e 0/4, w0o 0/4, w1e 0/4, w1o 0/4, w2e 2/4, w2o 0/4 |
| lock_add_m_aw | 2 / 12 | undetermined | M:out 2/6, M:push 0/6 | M:out 2/6, M:push 0/6 | w0e 1/2, w0o 1/2, w1e 0/2, w1o 0/2, w2e 0/2, w2o 0/2 |
| ldea_dir | 2 / 72 | undetermined | M:push 0/24, M:out 0/24, ldea_dir 0/12, nop 2/12 | M:push 1/24, M:out 1/24, ldea_dir 0/12, nop 0/12 | w0e 1/12, w0o 1/12, w1e 0/12, w1o 0/12, w2e 0/12, w2o 0/12 |
| ldea_bw_d16 | 2 / 87 | undetermined | M:push 0/24, M:out 0/24, ldea_bw_d16 0/12, nop 2/12 | M:push 1/32, M:out 1/31, ldea_bw_d16 0/12, nop 0/12 | w0o 1/17, w0e 1/16, w2e 0/14, w2o 0/14, w1e 0/13, w1o 0/13 |
| br_n5 | 2 / 48 | undetermined | call_n2 2/36, M:push 0/6, M:out 0/6 | nop 2/24, shl_imm8 0/24 | w0e 1/8, w0o 1/8, w1e 0/8, w1o 0/8, w2e 0/8, w2o 0/8 |
| push_ss | 1 / 12 | undetermined | M:out 0/6, M:push 1/6 | pop_ss 1/12 | w0e 0/2, w0o 0/2, w1e 0/2, w1o 0/2, w2e 1/2, w2o 0/2 |
| push_ps | 1 / 12 | undetermined | M:push 1/6, M:out 0/6 | M:push 1/6, M:out 0/6 | w0e 0/2, w0o 0/2, w1e 0/2, w1o 0/2, w2e 1/2, w2o 0/2 |
| ldea_iy_d8 | 1 / 12 | undetermined | M:push 1/6, M:out 0/6 | M:push 1/6, M:out 0/6 | w0e 0/2, w0o 0/2, w1e 0/2, w1o 0/2, w2e 0/2, w2o 1/2 |
| ldea_ix_d8 | 1 / 12 | undetermined | M:push 1/6, M:out 0/6 | M:push 1/6, M:out 0/6 | w0e 0/2, w0o 0/2, w1e 0/2, w1o 0/2, w2e 0/2, w2o 1/2 |
| ldea_bw_iy_d8 | 1 / 12 | undetermined | M:push 1/6, M:out 0/6 | M:push 1/6, M:out 0/6 | w0e 0/2, w0o 0/2, w1e 0/2, w1o 0/2, w2e 0/2, w2o 1/2 |
| ldea_bp_iy_d8 | 1 / 12 | undetermined | M:push 1/6, M:out 0/6 | M:push 1/6, M:out 0/6 | w0e 0/2, w0o 0/2, w1e 0/2, w1o 0/2, w2e 0/2, w2o 1/2 |
| ldea_bp_ix_d8 | 1 / 12 | undetermined | M:push 1/6, M:out 0/6 | M:push 1/6, M:out 0/6 | w0e 0/2, w0o 0/2, w1e 0/2, w1o 0/2, w2e 0/2, w2o 1/2 |
| ldea_bp_d8 | 1 / 12 | undetermined | M:push 1/6, M:out 0/6 | M:push 1/6, M:out 0/6 | w0e 0/2, w0o 0/2, w1e 0/2, w1o 0/2, w2e 0/2, w2o 1/2 |

