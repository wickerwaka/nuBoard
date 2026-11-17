# Divergence notes, round 20

RTL: the worktree's copy of main at 2a30b50 (not re-based: no "Land" commit seen when the round
started; no sim and no corpus replay this round). The corpus split is round 17's (30,536 runs,
25,422 exact). This round changes the cause or the status of these rows; "read" means a routine
or rule exists in `model_m.py` with the socket score given in `rtl-spec16.md`.

| corpus row | diverging (round 17's count) | cause | status |
|---|---|---|---|
| the 11 lost LEA runs (F25 `push-ldea-*-pE-w0`, F30 `push-lea-*`, `out-lea-*-nopb`) | 11 | LEA with d16 / direct starting with four bytes held and the bus idle: its release word waits for the chained fetch that starts on its own clock (3 clocks) | read: spec 16 A1 (`QPr20l` 648 of 648) |
| far transfers, callf_t0055 | 16 + 5 | the segment word of JMP far / CALL far is the same strict bus-idle word | read: spec 16 A1 (72 of 72, 114 of 114) |
| test_dir_aw, test_m_imm_d16 | 126, 118 | cells were by analogy; the routines have TEST [BW],AW's head and, for the imm16 forms, the displacement on a reserving request word | read: spec 16 B (42 of 42, 84 of 84) |
| pop_m_bw_ix_d16 | 96 | one more word behind the stack read (two registers + d16) | read: spec 16 B (42 of 42) |
| neg_m_bw_d16 | 21 | the request one word earlier, the displacement one word, two words behind the request | read: spec 16 B (213 of 216 with NOT / INC / direct) |
| shl_imm8, shl_imm4 | 147, 63 | 11 + 2n words, the count byte on a bus-idle word, the slot word sixth | read: spec 16 B (360 of 360); whether this is the whole of the corpus rows needs the builder's replay |
| cvtdb (CVTBD) | 11 | the operand byte's word is bus-idle | read: spec 16 B (120 of 120) |
| SET1 word behind OUT at even alignment | 3 | the register forms' commit word is a plain bus-idle word | read: spec 16 A2 (+27, 0 lost) |
| OUTM twice | (model rows) | the fifth word is bus-idle | read: spec 16 B (108 of 108) |
| add_m_imm_d16 (ADD word mem,imm16, d16 / direct), st_imm_bw_d16, st_imm_dir | 70, 107, 68 | the request word that releases the d16 is a strict bus-idle word | read for the socket probes: spec 16 addendum (+17, 0 lost); how many corpus runs it carries needs the builder's replay |
| add_m_imm8_d16 (ADD mem,imm8, d16 / direct) | 40 | four bytes held with the bus idle at the boundary: two chained fetches go ahead of the read | state closed, no rule: spec 16 C |
| EXT / INS r,imm4 behind short instructions | (model rows) | the imm4 byte leaves by the read's end; length open | partly read: spec 16 C |
| br_n1, the REP compares, set1_rw_cl, the C7 rows | as round 19 | unchanged | no new data |

## The model's misses

- Rounds 1 to 19, non-interrupt: 12,322 of 13,404 (from 12,215; 0 lost). The 1,082: `r18c` 624
  (REP compare code not generalised), the interrupt-frame stems the model does not simulate
  (`14s` to `16e`), and 58 form stems (`build/qp/r20/fail-20.txt`): `mi8*` (MUL r,r/m,imm8 at
  W >= 1), `fw-c7-*` 8, the transfers through memory and BRK / INT 3 at one alignment, `lds-2`,
  the "behind MOV r16,imm16" rows, `a3-3` / `addi8x-2` / the `mi-*-2` runs (spec 16 C), EXT.
- Round 20's own 2,322: 2,147 exact. The 175: 132 are INC BW in front of a [BW..] form or of
  EXT / INS (the lead changes the operand: the known artefact, not scored), 18 ADD mem,imm8 with
  d16 / direct in the four-bytes-held state, 22 EXT / INS r,imm4 behind short instructions, 3 NEG
  behind MOV BW,imm16.
- Interrupt families: not simulated by model_m. `sc20.py` (sc19 with the DIV loop offsets as a
  parameter) on round 20's sweeps: see results Q93.
