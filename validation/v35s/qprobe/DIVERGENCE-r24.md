# Known differences after qprobe round 24 (RTL of land17 against silicon, 1,369 rows)

Source: `traces/logs/clusters24.json` / `.txt` (the coordinator's `cluster.py` on this round's model) and
`traces/logs/rtl-miss-model-exact.json`. Counts are RTL miss rows.

| rows | state | status |
|---|---|---|
| 709 | read this round (Q110 to Q115): the lead at a flush target 306, the request word on a fetch's last clock 146, the bit-field commit word 112, the popping bus-idle word 92, RET's lead 54, ADJBA / ADJBS / EI 36, PUSH imm 8 (some rows under two rules) | work order 20, A1 to A6, B |
| 297 | exact in the model without this round's rules | build items (work order 20, C) |
| 88 | REP MOVBK / STM / INM / CMPBK word forms, the successor behind the last iteration, W = 0 (F24, F30); the model diverges inside the REP first | **over the line, not read** |
| 78 | stores with d16 / direct (66) and ALU [d16],imm (12) against the fetch chain behind an EU cycle (Q33's class): silicon lets a five-held chained fetch go in front of the access | **over the line, not read** (two readings rejected, Q117) |
| 39 | ADD4S / SUB4S / CMP4S (the model does not carry the string operands) | **over the line, not read** |
| 25 | MOVBK / CMPBK / INM single behind PUSH at even alignment, W = 1 / 2 (F39 `ctl-*-s`): read early by 1 / 2 | **over the line, not read** |
| 18 | word operands at odd addresses (`F5-out-*-odd`): the marker's fetch early by 1 | known difference |
| 18 | RET imm16 directly behind CALL (8), RETF imm16 (10; the model's shape is by analogy) | known difference |
| 15 | SHL / SHLB [m],CL behind a marker at even alignment | known difference |
| 12 | IN AL / AW,DW behind MOV r,r (Q107) | known difference |
| 8 | EXT / INS with BH as the length, crossing forms | known difference |
| 7 | MOV [BW+IX+d16],imm16 twice | known difference |
| 6 each | ADD DW,imm16 behind NOP at even alignment; the marker behind CVTDB (Q110) | known difference |
| 5 | PUSH DS0 behind PUSH at even alignment, W = 2 | known difference |
| 32 | further states of 1 to 4 rows | `clusters24.txt` |
| 6 | not parsed by the model: PUSH DS1 / PS / SS (4), CMP [d16],AW (2) | no routine |

Socket runs the model misses (non-interrupt set, 24,840): 1,286. Round 24's are the 42 CVTDB runs of
`r24a`. Rounds 1 to 23: 1,244 (1,292 at round 23's hand-back): `r18c` 624 (REP compares), the
interrupt-frame stems 330, and the families listed in RESULTS "Socket runs of round 22".
