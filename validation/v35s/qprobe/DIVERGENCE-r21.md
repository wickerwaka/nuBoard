# Divergence notes, round 21: a fresh split against ce9ea43

RTL: the worktree's copy re-based to main's ce9ea43 (16 files), direct sim rebuilt, corpus
replayed once with `+v35_chk`: **30,536 runs, 0 FAIL, 25,662 RTL-exact** (the builder's figure),
model-exact (the chain model) 30,361; **4,874 diverging**, 4,597 of them filed under a subject
form (`fd9.py` / `tab11.py`: `traces/logs/tab11.txt`). The non-interrupt socket set (38 rounds,
15,726 runs, plus this round's) was also run in the direct sim: the **build check**
(`build/qp/bc21.py`, `traces/logs/bc21.txt`): of 17,063 socket runs with a sim run, RTL exact
13,570, **model exact and RTL not 2,444**, RTL exact and model not 135.

How a row's status is decided (`build/qp/tab21b.py`, `traces/logs/tab21b.txt`): the socket probes
holding the **same encoding** (prefixes, opcode, ModR/M mod and r/m, the reg field of group
opcodes, the 0F sub-opcode: the addressing mode counts, unlike round 17's split) are scored by
the model and by the RTL sim. read = model >= 90 % of >= 12 runs.

## Headline

| status | diverging runs |
|---|---|
| read, and the RTL differs on the probes too (a work order carries it: specs 13 to 17) | 1,856 |
| read, the RTL exact on the probes: the corpus state is not the probes' (mostly "behind the marker") | 1,628 |
| partly read (50 to 90 %) | 492 |
| probed, not read (the REP compares, C7 [d16] by signature, EI) | 439 |
| not probed (903 on 94 forms before this round's `r21f`) | 171 |
| thin (< 12 probe runs) | 11 |
| not filed under a subject | 277 |

(The table is the final one, with `r21f` and `r21c` in the socket set and in the sim:
`traces/logs/tab21b.txt`. Before those two families the first two rows were 1,586 and 2,011,
partly read 379.)

**One fact cuts across the table:** 2,250 of the 4,874 diverging runs have their subject
directly behind the frame's marker (OUT imm8 1,610, PUSH 640), 1,697 of them at even alignment;
1,002 of those sat in the second row before `r21c` (probes exact in model and RTL). The small set's frames put
the long shift between the marker and the body, so "X directly behind an OUT imm8 / PUSH that
itself follows the long shift, with the same marker behind X" exists in it only where a round
copied the corpus frame (`QPr9-c40-*`, `QPr20l`, `QPr21m`, this round's `-o` / `-p` programs).
`r21c` (the corpus frame for 28 of these forms) was acquired to test this: see the end.

## Rows, by run count

| corpus row(s) | diverging | cause | status |
|---|---|---|---|
| REP compares: repe/repne/repc/repnc_cmpbk_w, _cmpm_w (and the byte forms) | 462 | RTL: head one word short, the exit, later CMPM iterations 12 clocks at every wait (silicon 12 + W) | read on `r18c` by `rc18.py` (not by model_m: "probed, not read" in the table); **spec 14 B2 + spec 15 A2**, not built |
| br_n1, br_n2, br_n0, br_n3 (call_n2 / ret / reti / brk as partners), retf 30, ret 19 | 211 + 28 + 19 + 18 + 49 | JMP short's displacement word is a bus-idle word (Q86) | read (180 / 180 model; RTL 167 / 180 on the probes); **spec 15 A1**, not built; the 13 probe runs the RTL misses are the same frames |
| set1_rw_cl (+ set1_rb_cl 15, test1_rw_cl 12, set1_rw_imm 11) | 156 + 38 | RTL: 0F 15 / 17 on a register use a routine of their own | read (132 / 132; RTL 0 / 132); **spec 14 B** (build fault) + spec 16 A2 |
| shl_imm8, shl_imm4, shl_al_imm4 | 147 + 63 + 15 | 11 + 2n words, count byte on a bus-idle word | read (324 / 324; RTL 284 / 324); **spec 16 B** |
| test_dir_aw, test_m_imm_d16, test_m_aw_bw_d16 | 126 + 118 + 27 | TEST's own head; imm16 forms a reserving request | read (42 / 42 each; RTL 0); **spec 16 B** |
| pop_m_bw_ix_d16 | 96 | one more word behind the stack read | read (42 / 42; RTL 0); **spec 16 B** |
| st_imm_bw_d16, st_imm_dir, add_m_imm_d16, add_m_imm_dir, cmp_m_imm_d16 | 87 + 61 + 70 + 53 + 44 | the request word that releases the d16 is a strict bus-idle word; W = 0 store against the chain (Q33) | read (96 / 96; RTL 71 to 83 of 96); **spec 16 addendum + spec 13 A1** |
| st_imm_bw_ix_d16, st_imm_bw_ix_d8 | 90 + 8 | two registers + d16: one more word in front of the request word | **read this round** (61 / 66, 65 / 66; RTL 30 / 66); **spec 17 B** |
| or_m_aw, and_m_aw, add_m_al, sub_m_aw, xor / or / and / sub / adc / sbb _m_al / _m_aw | 42 + 24 + 24 + 18 + 9 x 9 = 189 | **RTL build fault**: the write-back ALU forms on [BW] other than ADD word do not take ADD's routine (silicon: one routine, 66 / 66 each; RTL 3 / 66) | **read this round**; **spec 17 B1** |
| ext_dl_i11, ext_dl_bh, ext_dl_dh, ext_bl_dh, ext_bl_i7, ins_bl_i7, ins_bl_dh | 48 + 48 + 27 + 27 + 18 + 18 + 18 | EXT / INS: the extra word across a word (spec 12 / 13) and, for imm4, the pop on the datum word (Q96) | read (234 / 234, 162 / 162; RTL 168 / 234, 132 / 162); earlier specs + **spec 17 B** |
| set1_mw_cl with d8 / d16 / direct, set1_mw_cl, set1_mw_cl_bw_ix, clr1_mw_cl, clr1_mw_imm, not1_mw_cl | 18 x 3 + 15 x 3 + 12 + 6 = 117 | the word forms on memory by CL had no probe; with a displacement the routine was not known | **read this round** (63 / 66 a form; RTL 0 / 66 with d16 / direct, 30 with d8, 63 without a displacement); **spec 17 B** |
| add_m_imm8_d16, ld_dir, ld_bw_d16, ld_bp_iy_d16, ld_ix_d16 and the other d16 loads | 40 + 27 + 18 + 12 + 9 + .. | a read against the fetch chain behind an EU cycle (Q95): no arbitration inside the chain | **read this round** (`r21m` 492 / 498; RTL 423 / 498: every miss the state); **spec 17 A1** |
| st_acc_dir, st_acc_000c, st_acc_000e, st_bw_d16, st_bw_ix_d16, st_dir, st_imm_bw, st_imm_bw_d8 | 52 + 20 + 14 + 18 + 19 + 18 + 14 + 28 | stores against the chained fetch (Q33, Q69: W = 0, twice / behind PUSH) | read in part (model 59 to 60 of 66 on the d16 stores, the misses the same state); spec 13 A1; **the store's own rule is still Q33's table, no machine** |
| neg / not / inc / dec_m_bw_d16, shl_m1_bw_d16 | 21 x 5 | spec 16 B's routine; DEC and SHL 1 with d16 by this round | read (RTL 0 to 1 on the probes); **spec 16 B + spec 17 B** |
| add_m_aw_bw_ix_d16, add_m_aw_dir, add_m_aw_bw_d16, xch_dir_aw | 14 + 12 + 12 + 9 | read-modify-write with d16: routine not known to the model before | **read this round** (66 / 66, 63 / 66); **spec 17 B** |
| call_m_bw, br_m_bw | 24 + 24 | near transfers through [BW]: the request's word differs by alignment | **partly read** (6 / 12 each) |
| callf_m_bw, brf_m_bw, callf_m_dir | 20 + 20 + 20 | far transfers through memory | read at W = 1 / 2 (10 / 12; `callf_m_dir` 12 / 12, RTL 0 / 12); spec 13 + **spec 17 B** |
| rep_inm_w, rep_outm_w | 48 + 30 | CW = 0: one word more than the string forms' zero routine; CW >= 1 exact | **partly read** (CW = 0: 28 / 36) |
| cvtdb, test_aw_imm, cmp_aw_imm16, cli | 11 + 10 + 10 + 10 | no probe before (round 20's "cvtdb" row was read with CVTBD, the wrong instruction) | **read this round** (63 / 66, 66 / 66 x 3); **spec 17 B** |
| add_dw_imm0, add_dw_imm2a01, add_dw_imm, in_al_dw, in_aw_dw, pop_m, test1_mw_cl, mulu_aw, mulu_dw, mul_cw, cmp_aw_aw, cmp_aw_dw, rol4_dl, mov_aw_dw, cvtwl, add4s, ld_bw_ix_d16, rep_movbk_w, rep_stm_w, test_m_imm, ldm_w / ldm_b, adjbs / adjba, br_bw and about 90 smaller rows | about 1,150 | **the model and the RTL are both exact on every probe of the encoding; the corpus runs diverge almost only directly behind the marker at even alignment** (e.g. add_dw_imm0 63 of 243 even, 0 of 243 odd; mulu_dw 24 of 24 even, 0 of 48 odd) | **a state, not a form: not in the small set before `r21c`**; see below |
| sti | 12 | EI's routine is read; the small set's EI programs are interrupt frames | not scored by the model |
| retf_imm2 10, adj4s 6, the prefixed 0F forms 9, PUSH sreg 4, Jcc rows (1 to 3 each), dbnz / bcwz, inm_w 5, pop_m_ix / pop_m_bw_ix 6, cmp / and_dir_aw 10, the two-register d16 loads / LEA 21 | 171 | | **not probed** |

## The model's misses (non-interrupt socket set, 18,972 runs with this round's)

17,532 exact. Rounds 1 to 20: 14,528 of 15,726 (from 14,469; no stem worse than in round 20's
list). The 1,198: `r18c` 624, the interrupt-frame stems the model does not simulate (`14s` to
`16e`, 256), the INC BW artefact, and the form stems of `traces/logs/fail-21.txt`. `r21m` 492 of
498; `r21f` 2,512 of 2,748 (216 the INC BW lead).

## The state class, tested (`r21c`, results Q99)

The corpus frame `OUT imm8 ; X ; OUT imm8` at even alignment for 28 forms of the class: model
24 of 84, RTL 20 of 84 (odd: 69 / 66 of 84); `PUSH ; X ; PUSH`: 168 of 168 in both. So:

- **"directly behind OUT imm8 at even alignment" is an unread state** (not a form, not a build
  fault): about 730 diverging corpus runs of the class and part of the 323 + 99 behind M:out at
  even alignment in the other rows. Status: **probed this round, not read**; material `QPr21c`.
- **behind the PUSH marker** (about 275 runs of the class at even alignment): the frame is
  exact in model and RTL on the probes; the corpus divergence is not reproduced by the frame.
  Status: **not diagnosed** (operands / chain start).

## Ranking of what is not read, by run count

1. Behind OUT imm8 at even alignment (the state above): about 730 to 1,100 runs.
2. REP compares: 462 (diagnosed against the RTL by `rc18.py`; in specs 14 / 15; model_m does not generalise).
3. Behind the PUSH marker, forms exact on probes: about 275.
4. Stores against the chained fetch (Q33's table, no machine): about 180 on the st_* rows.
5. Near transfers through [BW] 48; REP INM / OUTM word with CW = 0, part of 78.
6. Not probed: 171 on 54 forms (largest 10).
