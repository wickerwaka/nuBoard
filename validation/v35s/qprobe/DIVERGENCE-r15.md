# Divergence notes, round 15

No newer RTL reached my worktree (still the 6+7 copy) and no corpus replay was run this round,
so round 14's cross-tab and split stand: 20,154 exact of 30,536; 10,017 diverging runs filed;
read and not built 8,610, partly read 1,096, not probed 299, probed and not read 12
(`../r14/tab14.txt`, `../r14/divergence-notes.md`).

What this round changes in those rows, by the model alone:

- Not probed (299): the small forms of Q60 are read (cmp_m_aw 24, cmp_m_al 18, adj4a 18, adjbs
  and adjba 24, in_aw_dw 20, test_al_imm 14, xch_aw_dw 7, cmp_al_imm8 7: 132 runs); lahf 8 and
  neg_m_bw_d16 21 in part; cvtbd 18 acquired, not read. Left unprobed: cmpb_m_imm8_82 12 and the
  pushes of segment registers 4.
- Partly read (1,096): not worked on this round (EXT / INS, MUL / DIV on memory, CALL mem16,
  BRK 3, SET1 mem,imm). Still the largest block without a work order.
- The interrupt probes do not appear in the corpus split; their RTL differences are in
  rtl-spec10 section I and rtl-spec11 section I (the RTL takes scan-sourced requests one
  instruction after a release where silicon takes two to eight; its INTAK pulses are 3 clocks
  apart where silicon's are 1; its timer request has no scan).
- The sim cannot check INT programs today: the INTAK answer does not reach the core in the
  direct sim build (results.md, top of round 15).
