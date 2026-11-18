# Known differences after qprobe round 26 (RTL of land21, 04c3a30, against silicon: 355 rows)

Source: `traces/logs/model26.jsonl` (the coordinator's `corpus_model.py` on this round's model),
`traces/logs/rtl-miss-model-exact.json`, `traces/logs/unread26.txt` (every row the model misses too, with its first
difference). Counts are RTL miss rows.

| rows | state | status |
|---|---|---|
| 88 | word string elements at odd pointers, W = 0: the last element's wait (`J`, Q120 / Q128) | measured in 5 places and excluded in 11 (round 26); a word kind, level unknown: **ruling** (work order 22, C2) |
| 24 | the marker behind a store whose write is a pair (16, F5 `out-*-odd`) or starts behind a fetch (8) | read: the store's N is on the first clock of the write's last byte cycle (Q127); **needs a bus-to-sequencer bit: ruling** (C1) |
| 112 | EXT / INS behind OUT at even alignment: the bit-field head's second commit word (Q110) | ruled a known difference (work order 20, A6) |
| 16 | exact in the model with no rule of rounds 24 to 26 (F35 / F40 `callf-retf`, `brf-n0`, singles) | build items |
| 12 | RETF imm16 behind CALLF (F35 `far-callf-retf2`) | known difference (the model's shape is by analogy) |
| 15 | SHL / SHLB [m],CL behind a marker (F14, F36) | known difference |
| 14 | IN AL / AW,DW behind MOV r,r (F19) | known difference |
| 14 | the [BW+IX+d16] forms against the chain (F21 `sti-bw_ix_d16`, F26 `fib-bixd16`, F30 `lea-bw_ix_d16`) | known difference |
| 8 | ADD DW,imm16 behind NOP at even alignment (F20, F29) | known difference |
| 6 each | the marker behind CVTDB (ruled); CLR1 / SET1 [m],imm word forms with a displacement (F34) | known difference |
| 34 | singles and pairs: RET imm16 at W = 2, PUSH imm8 / PUSH DS0, MUL AW,CW,imm, JMP far [m], ADD byte [d16],imm8 behind OUT, CMP [d16],AW, EXT BH,BL twice, POP [m] at odd BW | known difference (`unread26.txt`) |
| 6 | not parsed by the model (PUSH DS1 / PS / SS, CMP [d16],AW) | model function |

Not corpus rows (socket only), for the same work order: CALL near's wait with SP odd (22 runs, C3); MOV
[d16],AL / AW's request word (100 runs the RTL misses, C4); `CH_EPRI` behind a store with an immediate and NOP (9
runs, C5); EI's scan restart (the lattice 3 clocks late in the RTL, C6); the instruction an interrupt replaces
behind a store through an odd pointer (C1). The model misses 1,050 corpus runs the RTL has exact (unchanged:
model faults, `traces/logs/model26.jsonl`).
