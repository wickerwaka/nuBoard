# Round 12 divergence notes: the spec-5 cross-tab split by what the model reads

Same corpus rows as round 11 (the spec-5 build's replay, 13,875 diverging runs; `fd11.jsonl`,
cross-tab `tab11.py` with the "partner unread" re-filing). No new replay: the RTL of this
worktree is still the spec-5 build. New: `build/qp/tab12.py` labels every form by the model's
status and splits each cause.

A corpus form is **read** when the small set holds probes of the same instruction signature and
the model reproduces at least 90 % of the runs that contain it together with nothing unread
(at least 12 runs). The signature is the opcode, for group opcodes the ModR/M reg field (the
write-back ALU operations folded, the shifts folded), register or memory operand, the second
byte on the 0F page, byte / word folded where one routine was measured for both, a REP or
segment prefix kept. The addressing mode is not in it (the model builds the modes by rule,
Q17 / Q18). "Partly read" is 50 to 90 %; "probed, not read" below that; "not probed" has no
probe of the signature.

| cause | model status | diverging runs | largest forms |
|---|---|---|---|
| own | read | 8069 | pop_m 318, add_m_imm 276, rep_stm_w 273, st_imm_bw_d8 265, st_imm_bw_d16 262, rep_inm_w 221, rep_movbk_w 196, push_m 174 |
| other causes | read | 2149 | add_dw_imm0 242, cmp_aw_aw 167, br_n1 109, shl1 98, ld_bw_ix_d16 88, st_bw_ix_d16 78, shl_imm8 72, shl_imm4 63 |
| own | not probed | 1447 | cmp_m_imm 138, cmp_m_imm_d16 120, dbnze_n0 82, clr1_mw_imm 54, repc_cmpm_w 50, dbnzne_n0 46, repnc_cmpm_w 40, repnc_cmpbk_w 40 |
| own | partly read | 1205 | ext_bl_dh 114, call_m_dir 96, ext_dl_dh 84, brk3 80, ext_bl_i7 78, ins_bl_i7 66, ins_bl_dh 66, set1_mw_imm 54 |
| own | probed, not read | 388 | mulu_m 102, mul_aw_m_imm8 66, mul_aw_m_imm16 58, divu_m 48, mul_m 36, div_m 30, brk5 30, mulub_m 18 |
| other causes | not probed | 122 | mov_ds1_m 20, in_aw_dw 20, test_al_imm 14, mov_ss_ix 14, mov_ds1_ix 14, mov_ds0_ix 14, lahf 8, xch_aw_dw 7 |
| other causes | partly read | 101 | br_bw 80, brf_t0053 9, brf_t0057 4, brf_t0054 3, brf_t0052 3, callf_t0053 1, callf_t0051 1 |

total 13481  read 10218

(13,481 of the 13,875 diverging runs are filed under a form; the rest have no subject.)

## Reading the split

- **10,218 runs are in forms the model reads**: 8,069 "own" (the routine itself: expected to
  clear as specs 6 / 7 / 8 are built) and 2,149 under other causes on read forms (the branch
  rows in front of Jcc / DBNZ, SHL r,1 behind OUT, the base+index+d16 modes the RTL reverted,
  the shifts by imm8: each has its rule in specs 5 to 7).
- **388 are measured but not in the model**: MUL / DIV on memory (the register routine behind
  a read, Q39) and MUL r,m,imm.
- **1,205 are partly read**: EXT / INS (the in-word cases read, the word-crossing ones not),
  CALL / JMP through memory, BRK, SET1 mem,imm, the far transfers.
- **1,447 + 122 are not probed**: CMP mem,imm16 (81 /7 memory; 83 /7 is read and 81 /0 is read:
  one small probe), DBNZE / DBNZNE (E0 / E1; E2 is read), CLR1 mem,imm, REPC / REPNC (64 / 65),
  MOV sreg,mem, IN AW,DW, a few one-offs.

After the specs for rounds 10 to 12 are built, the corpus's remaining divergence should be of
the order of 3,300 runs, about 1,600 of them one probe round away (the not-probed block is
mostly variants of read routines).

## RTL (spec-5 build) against the round-12 family probes

| group | runs | RTL exact | model |
|---|---|---|---|
| r12a (immediates on registers, MUL / DIV, 0F forms, 4S, PREPARE, transfers) | 990 | | 729 |
| r12b (EXT / INS grid) | 144 | | 108 |
| both | 1,134 | 186 | 837 |

The interrupt probes are not scored against the RTL here: its recognition is about 10 clocks
earlier than silicon's (results.md Q41), so every stepped run differs.
