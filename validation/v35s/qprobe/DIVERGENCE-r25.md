# Known differences after qprobe round 25 (RTL of land17 against silicon, 1,369 rows)

Source: `traces/logs/model25.jsonl` (the coordinator's `corpus_model.py` on this round's model),
`traces/logs/rtl-miss-model-exact.json`, `traces/logs/unread25.txt` (every remaining row with the model's
first difference). Counts are RTL miss rows.

| rows | state | status |
|---|---|---|
| 709 | read in round 24 (Q110 to Q115) | work order 20 |
| 297 | exact in the model without a rule of rounds 24 / 25 | build items (work order 20, C) |
| 88 | word string elements at odd pointers, W = 0 (was "REP successors"): the pair (Q118) and the last element's wait (Q120) | read; **Q120 has no mechanism: ruling wanted** (work order 21, B1 + B3) |
| 48 | d16 / direct stores against the chain: the third fetch in front of the write (Q123) | read (B6) |
| 39 | ADD4S / SUB4S / CMP4S head (33), ADJ4S (6) (Q122) | read (B5) |
| 25 | MOVBK / CMPBK / INM single behind PUSH: the bus-idle word (Q121) | read (B4) |
| 23 | stores / RMW with an immediate and d16 behind OUT, pE, W = 0 (Q125) | read (B7, B2) |
| 16 | word stores at odd BW, the marker behind (Q119) | read (B2) |
| 15 | SHL / SHLB [m],CL behind a marker at even alignment (read early by 1 / 2 / 3 with W) | known difference |
| 13 | MOV [BW+IX+d16],r / imm16 against the chain (F21 `bw_ix_d16` 4, F26 `fib-bixd16` 9): the two-register address path, not in `r25b` | known difference |
| 12 | IN AL / AW,DW behind MOV r,r (Q107) | known difference |
| 12 | RETF imm16 behind CALLF (F35 `far-callf-retf2`; the model's shape is by analogy) | known difference |
| 8 | ADD DW,imm16 behind NOP at even alignment (F20 6, F29 2) | known difference |
| 8 | RET imm16 (F35 `ret-imm*`, F40 `xfer-retimm`), W = 2 | known difference |
| 6 | the marker behind CVTDB (ruled a known difference) | known difference |
| 6 | EXT with BH as the length / an immediate 11, crossing (F34) | known difference |
| 6 | CLR1 / SET1 [m],imm word forms with a displacement (F34 `mbit-*-d`) | known difference |
| 5 | PUSH imm8 / PUSH DS0 at W = 2 (F25) | known difference |
| 4 each | ADD byte [d16],imm8 behind OUT (F22 `add8_d16`); MUL AW,CW,imm (F33); JMP far [m] (F37 `brfm-sep`); MOV r,r ; NOP ; IN / OUT at pE W = 0 (F19) | known difference |
| 3 each | DBNZNE with CMP in the loop (fetch address: function); PUSH DS0 then a transfer at W = 2 (F39) | known difference |
| 2 each | EXT BH,BL twice (Q110, ruled); POP [m] at odd BW | known difference |
| 1 | LEA [BW+IX+d16] ; NOP at pE W = 0 | known difference |
| 6 | not parsed (PUSH DS1 / PS / SS, CMP [d16],AW: no routine) | model function |

No state over 20 rows is unread. The model misses 1,041 corpus runs the RTL has exact (unchanged
this round; the largest: REPNE / REPC CMPM, the `-pat` compare patterns, MOV sreg forms of F30
`seg-*`): model faults, of no consequence for the work orders, listed in `traces/logs/model25.jsonl`.
