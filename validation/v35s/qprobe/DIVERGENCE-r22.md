# Divergence notes, round 22: what moved in round 21's split

No RTL change and no new replay this round: the corpus figures are round 21's replay of ce9ea43
(30,536 runs, 25,662 RTL-exact, 4,874 diverging; `build/qp/r21/fd21.jsonl`), re-tabulated by the
model key of the subject and by what stands directly in front of it (`build/qp/ck22.py`,
`corp22.py`; `traces/logs/ck22.txt`). 2,250 diverging runs have their subject directly behind
the frame's marker; by this tabulation 1,217 behind OUT imm8 at even alignment, 393 at odd, 480
behind PUSH at even, 160 at odd.

## Headline

**Measured offline on the corpus itself** (the coordinator's `corpus_model.py`, this round's model
against land14's RTL miss list; results Q107): model-exact 24,101 -> **25,396** (+1,307, -12);
runs that both the model and the RTL miss 1,828 -> **899**; runs the model has and the RTL has
not 716 -> **1,651**. Per rule (switched off alone): spec 18 A1 256, A2 335, MULU / MUL / DIV 84,
the other shapes 260. The table below is the cross-tabulation of round 21's replay (ce9ea43),
kept for the row names; where the two differ the offline figure is the measurement.

Round 21's first unread item, "X directly behind OUT imm8 at even alignment" (about 730 to 1,100
runs), **is read**: it was three things (results Q101, Q102), each now a rule or a shape of the
model with 0 socket runs lost. Round 21's third item, "behind the PUSH marker, forms exact on
the probes" (about 275), **was a comparison artefact** (Q100): the probes do diverge there, for
the same shapes.

| what | status before | status now | diverging corpus runs it should carry |
|---|---|---|---|
| the first fetch behind OUT's I/O cycle one clock late (ADD / CMP r16,imm16; POP m; every two-register + d16 form) | unread state | **read: spec 18 A1** (outcome rule, 104 forms; mechanism inferred) | 234 behind OUT at even alignment |
| the commit word against the chain's second fetch (0F page on memory by CL, ROL4, EXT / INS, SHL r,imm8 / imm4) | unread state | **read: spec 18 A2** | up to 446 behind OUT at even alignment (shared with spec 16 B / 17 B shapes on the same rows) |
| MULU / MUL / DIV r: a second bus-idle word | "exact on probes, diverges behind PUSH: not diagnosed" | **read: spec 18 B** | 84 (39 behind OUT even, 39 behind PUSH even, 6 elsewhere) |
| CVTWL, IN AL / AW,DW, LODS, ADJ4, TEST m,imm16, XCH [d16],r: a bus-idle word | in the unread state class | **read: spec 18 B** | 139 (110 directly behind a marker) |
| JMP / CALL near through [BW] / [d16] | partly read (6 / 12) | **read: spec 18 A3** | 31 |
| REP INM / OUTM word, CW = 0 | partly read (28 / 36) | **read: spec 18 B** (36 / 36) | part of rep_inm_w 48 + rep_outm_w 30 |
| ADD [BW+IX+d16],imm8 at even alignment behind OUT; ADD / CMP [d16],imm8 behind OUT (Q95's fourth row) | open, 6 runs | open, 9 runs | part of add_m_imm8_d16 40 |
| stores against the chained fetch (Q33's table) | no machine | unchanged | about 180 |
| REP compares | read by `rc18.py`, in specs 14 / 15 | unchanged | 462 |
| interrupts | spec 15 I / 16 I | not touched | - |

Sum of the rows read this round: about 930 diverging corpus runs (the A2 row overlapping with
earlier work orders' shapes on the same forms). They are **estimates by cross-tabulation**: a
corpus run is counted when its subject has the key and stands in the state; whether the run
becomes exact also depends on the other work orders on that form.

## What is still directly behind OUT imm8 at even alignment and not explained by a rule of spec 18

Of the 1,217: the rows above carry 759 (234 + 446 + 39 + 40). The rest by key: the frame's own
trailing long shift as "subject" 99 (the subject could not be named: these follow whatever is in
front), TEST1 / SET1 / NOT1 r,CL 55 (spec 14 B's build fault), CMP r,r 41 (cmp_aw_aw 29 of 222,
cmp_aw_dw: the model and the RTL are exact on `QPr21c-c-cmp_aw_aw-oo`; **not diagnosed**: chains
of two or three), OUT DW 21, MOV m,imm16 with d16 13, IN DW 15 (in the 139), the read-modify-write
build fault 7, and rows of fewer than 10.

## Behind PUSH at even alignment (480)

ALU m,r write-back build fault 60 (spec 17 B1); the trailing long shift 65; MULU / MUL 39 (spec 18
B); SHL r,imm 32 (spec 16 B + 18 A2); ADD r16,imm16 29 (the model is exact on `QPr22c-p-{ai16,ci16}`:
the RTL's difference there is an earlier work order's, spec 16 A1's strict bus-idle word); the
d16 loads 62 and ADD m,r with d16 12 (spec 17 A1); IN DW 18, CVTWL 3 (spec 18 B); MOV r,r 21 and
MOVBK / CMPBK 20 (**not diagnosed**; the model is exact on `QPr22c-p-rr`).

## The model's misses (non-interrupt socket set)

By `cmp22.compare`: 22,378 of 23,670 (rounds 1 to 21: 18,518 of 19,644, +442 and 0 lost against
round 21's options; round 22: 3,860 of 4,026). The 1,126 of rounds 1 to 21: `r18c` 624, the
interrupt-frame stems (`r14s` to `r16e`) 330, `r21c` 49 (`ext_dl_bh`, `add4s`: operands), `r21f` 30,
`r8` 26, `r20a` 21, others under 20.

## Ranking of what is not read, by corpus run count

0. **EXT / INS directly behind OUT imm8 at even alignment at W = 1 / 2: 114** (the largest state
   cluster left in `traces/logs/clusters22.txt`; W = 0 is read by spec 18 A2).

1. REP compares: 462 (diagnosed against the RTL by `rc18.py`; specs 14 / 15; not in model_m).
2. Stores against the chained fetch (Q33's table, no machine): about 180.
3. CMP r,r / MOV r,r chains behind a marker: 41 + 21 (probe exact; not diagnosed).
4. Q95's fourth row (a V request against the chain with four held): part of 40.
5. Not probed (round 21's list, 171 on 54 forms): unchanged except CMP r,m with two registers +
   d16 and the EA modes of `r22a`.
