# Divergence notes, round 18

RTL: the worktree's copy of main at 2a30b50 (round 17's re-base; a builder is changing the RTL
elsewhere, so no re-base and no corpus replay this round). The split of the corpus is round
17's (`../r17/divergence-notes.md`): 30,536 runs, 25,422 exact, 5,114 diverging. What this
round adds is the cause of four of its rows.

| corpus row | diverging | cause | status |
|---|---|---|---|
| br_n1 (with call_n2 / ret / brk as partners) | 211 (242 by `fd17`'s subject, 197 of them at W = 1 / 2) | a transfer whose opcode comes alone in the previous transfer's first flush fetch starts W clocks too early in the RTL **and in the model** (silicon: its flush fetch 8 clocks after the end of the fetch that brings the displacement, at every W) | read on 12 of 60 `r18j` runs; rule stated as a sum (spec 14 A2), the word not identified; model not corrected |
| set1_rw_cl | 156 | RTL build: 0F 15 / 17 on a register use a short routine of their own (`b1sclw_r`); silicon is the byte forms' routine, independent of CL | read, 81 of 84 (`r18b`); spec 14 B |
| repe_cmpbk_w, repne_cmpm_w, repc_cmpm_w, repnc_cmpbk_w | 342 | RTL: head one word short, exit one length for both paths (silicon: one word more on the count exit); at W = 2 also the spacing in part of the forms | read at W = 0 to the word (`r18c`, 768 runs); the W = 2 spacing difference not diagnosed; spec 14 B2 |
| add_m_imm_d16 and the C7 d16 rows (spec 13 A1) | 70 + 175 | unchanged; Q79 shows the rule needs no wider condition | no new data |

Not advanced (as in round 17's list): NEG [BW+d16], EXT across a word's extra word, ADD
[d16],imm8 with four bytes held, CALL far with waits, OUTM twice, the five "twice" runs, the
three CVTBD runs, test_dir_aw / test_m_imm_d16, pop_m_bw_ix_d16, the shl_imm rows.

## The model's misses added this round

- `r18c`: 624 of 768 (its REP compare code assumes the two data shapes of rounds 9 to 13).
- `r18j`: 12 of 60 (above). `r18b`: 3 of 180 (SET1 AW,CL behind OUT at even alignment).
- The interrupt families are not simulated by the model (it supplies pops only).
- New model facility: `o["BLOG"]` (instruction starts). No rule or shape changed.

## Sim runs of this round (RTL copy at 2a30b50)

`build/validation/v35s/qprobe/sim18`: `r18y` 1,872 (run records for Q79; the traces are not
used), `r18j` 60 (= model on all), `r18b` 180 (= model on 90, the word SET1 / NOT1 forms
differ), `r18c` 768 (`rc18.py`). No interrupt family was simulated.
