# Divergence notes, round 19

RTL: the worktree's copy of main at 2a30b50 (not re-based: no new "Land" commit; no sim and no
corpus replay this round). The corpus split is round 17's (30,536 runs, 25,422 exact). This
round changes the cause or the status of these rows:

| corpus row | diverging | cause | status |
|---|---|---|---|
| br_n1 (call_n2 / ret as partners) | 211 | JMP short's displacement word is a bus-idle word (it waits for a prefetch in flight); the RTL and, until this round, the model let it execute | read (`r18j` 60 of 60 with the model corrected); spec 15 A1 |
| repe_cmpbk_w, repne_cmpm_w, repc_cmpm_w, repnc_cmpbk_w | 342 | as round 18, plus at W = 1 / 2: the RTL's later CMPM iterations are 12 clocks at every wait, silicon 12 + W | diagnosed on `r18c`; spec 15 A2 |
| the interrupt probes (NMI, INTPn, timer) | (not in the corpus count) | the EU side is an event on listed words, a hidden 2-clock occupation of the bus unit and 5 clocks, not a delay | read: 5,092 of 5,128 NMI runs; spec 15 I |
| set1_rw_cl, the C7 / add_m_imm d16 rows | 156, 245 | unchanged (spec 14 B, spec 13 A1) | no new data |

Not advanced: NEG [BW+d16], EXT across a word's extra word, ADD [d16],imm8 with four bytes
held, CALL far with waits, OUTM twice, the five "twice" runs, the three CVTBD runs, SET1 word
behind OUT at even alignment, test_dir_aw / test_m_imm_d16, pop_m_bw_ix_d16, the shl_imm rows.

## The model's misses

- Non-interrupt socket set: 12,215 of 13,404 (from 12,203). The 1,189: `r18c` 624 (REP compare
  code not generalised), `r18b` 3, and round 17's 562.
- Interrupt families: not simulated by model_m. `sc19.py` (the second-stage rule over the
  model's word log) misses 36 of 5,128 NMI runs (results Q83) and 69 of 576 behind jumps.
- The model does not know ES: MOV byte [d16],imm8 (the timer start of `r19ptm` / `r19qt*`).
