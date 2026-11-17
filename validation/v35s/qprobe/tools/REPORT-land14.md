# Validation-loop tools: first run on the corpus (2026-11-17)

Trees: the model (`validation/v35s/qprobe/model_m.py`) and the corpus code are v35s-harness at
3a36188 (RTL / ROM = ce9ea43). RTL replay rows: land14 (`$S/v2/qprobe/land14/miss-v35_chk.jsonl`,
27,604 RTL-exact; built from main's uncommitted tree, 09:24) and land13 (ce9ea43, 25,662).
romcheck ran on the ROM of ce9ea43 and on a snapshot of main's uncommitted urom taken at 10:31
(`tools/snap/main-1031/`). Outputs: `tools/out/` (corpus_model.jsonl / .txt, offsets.json,
clusters-land14.json / .txt, clusters-land13.json / .txt, romcheck-ce9ea43.json / .txt,
romcheck-main.json / .txt, chains.json). Run time: A 1.5 min, B a few seconds, C 1 min per ROM
(3 processes).

## A. corpus_model: the model on the 30,536 corpus runs

Clock mapping, calibrated (every 7th run): w0 +20 / +17, w1 +22 / +20, w2 +26 / +24 (even / odd),
each the answer of 99.4 % or more of its sample (4 of 674 the worst), so the frame mapping holds.

| | runs |
|---|---|
| model-exact | **24,101** |
| model-miss | **3,199** |
| not modelled | **3,236**: no routine 2,784; model error 432 (pointer / vector values not tracked 324, ran outside the chain after a wrong BRK target 96, RET with no CALL 12); F0w 20 |

Largest "no routine" encodings (runs): INC AW (40) 162, STC (F9) 132, ADD [BW+IX+d8],AW 96,
ADD [BW+IX],AW 84, POP [BW+IX] 84, CS: prefix forms (2E B8, 2E 36 B8) 120, AND AW,[BW] 48,
PUSH / POP CW 84, OR AW,DW 36, SUBC AW,imm16 36, LDS / LES [IX] 72, XCH AW,CW 36, XOR r,[BW] 60,
SS: MOV 36, IN AW,imm8 24, the Bcond other than BZ / BNZ (72-7F) 24 each.

Cross-tab against land14 (land13 in brackets):

| | RTL exact | RTL miss | total |
|---|---|---|---|
| model exact | 23,385 (21,894) | **716** (2,207) | 24,101 |
| model miss | **1,371** (1,100) | **1,828** (2,099) | 3,199 |
| not modelled | 2,848 (2,668) | 388 (568) | 3,236 |

- (model exact, RTL miss) = build faults / unbuilt rules: **716** (2,207 on ce9ea43). Biggest:
  the [BW] write-back ALU forms not on ADD's routine (or / and / sub / adc / sbb / xor, byte and
  word: about 180 runs), EXT / INS with imm4 or register length, TEST AW,imm16 / CMP AW,imm16,
  MOV [BW+IX+d16],imm16, ADD [BW+d16],imm8; the largest single subject is `nop nop` (50 runs,
  not diagnosed here). By frame: behind OUT odd 256, PUSH even 191, OUT even 138, PUSH odd 94.
- (model miss, RTL miss) = unread states: **1,828**, of which **1,084 have the subject directly
  behind OUT imm8 at even alignment** (382 OUT odd, 227 PUSH even). Forms: CALL / BR pairs, IN AL,DW,
  POP mem, MULU, REP INM / OUTM with CW = 0 / 1, SHL imm4, MOV [BW],imm.
- (model miss, RTL exact) = model errors: **1,371**. Most look like function the model does not
  track rather than timing rules (not verified run by run): REP strings and CMPBK / CMPM with
  odd index registers (F24 / F30 "missing read / write": the model splits an odd word only for
  an odd SP or BW), Bcond outcomes after CMP (Z is the only flag the model tracks, and only
  through INC / DEC / CMP r,r: F34 / F35 / F40 "fetch address differs"), MUL r,mem,imm sign
  fix-ups (the operand's sign is in memory: F33 / F34 "fetch early by 8"), RCL / RCR (F16),
  ADDC mem,imm8 (F38), AND [BW],imm8 (83 /4 on memory: the model falls back to the register
  routine `ADD83`, a table gap).

## B. cluster: first-divergence signatures (land14 and the model)

RTL vs silicon (land14): 2,932 diverging runs; view 1: 1,422 clusters, view 2: 763, view 1
without waits / held: 755, the coarse view (predecessor, parity, frame): 249. The three largest
coarse clusters: **predecessor M0:out at even alignment 638**, M0:push even 271, a run without a
model timeline (subject guessed) at even behind OUT 170. The three largest view-2 states: behind
OUT imm8 even, 5 bytes held, w0, the subject's read late by 3 (97 runs: TEST1 / SET1 / CLR1 /
NOT1 mem,CL and EXT / INS); behind OUT imm8 even, 5 held, fetch early by 1 (85 / 77 / 77 at w0 /
w1 / w2: ADD DW,imm 0, POP mem, MOV [BW+IX+d16],imm16 and others: one state across forms); the
same frame, read late by 4 at w1 / w2 (57 / 57: EXT / INS). The largest view-1 cluster is the
fetch around the second long shift after the M1 OUT imm8 (LS:movcl behind M1:out, odd, w0, fetch
early by 1: 43 runs over Bcond / BR / CALL / RET forms).

Model vs silicon: 3,199 diverging runs; view 1: 1,751 clusters, view 2: 1,102. Largest view 2:
the same three states as the RTL's (behind OUT imm8 even, 5 held: read late by 3, 97; fetch early
by 1, 75 / 75 / 75), which is the evidence that those are unread states, not build faults.

The top 25 of views 1 and 2 for each source follow at the end (`tools/out/clusters-land14.txt`
has the 1w and coarse views; clusters-land13.txt the RTL views for ce9ea43).

## C. romcheck: the ROM against the model's routine strings

447 encodings (the corpus subjects, prefixes stripped; 63,298 subject-runs, a run counted once
per encoding it holds). Status on ce9ea43 / main:

| status | ce9ea43 enc (runs) | main enc (runs) |
|---|---|---|
| ok (same string, sim same; one built-in routine sim-only) | 74 (30,242) | 113 (40,270) |
| equivalent (string differs, sim same) | 133 (18,684) | 134 (13,608) |
| **mismatch** | **80 (6,332)** | **35 (1,164)** |
| decode only (lead / three-bytes wait) | 4 (570) | 9 (786) |
| model gap (a register routine for a memory encoding) | 16 (336) | 16 (336) |
| model has no routine | 118 (4,362) | 118 (4,362) |
| not covered (REP strings, EXT / INS data-dependent paths, BCD) | 20 (2,604) | 20 (2,604) |
| string differs, no sim run (RETI, BRK-class stack state) | 2 (168) | 2 (168) |

**The known true positives are found on ce9ea43**: OR / AND / SUB / XOR / ADC / SBB [BW],r16 and
ADD / OR / SUB (and ADC / SBB / AND / XOR) [BW],r8 run `rmw_b` while ADD [BW],r16 runs `rmw`
(one model routine RMW, two ROM routines; sim differs on 43 to 50 of 45 to 54 programs each;
ADD [BW],r16 itself is sim-equivalent); SET1 / NOT1 r16,CL (0F 15 / 0F 17 reg) run `b1sclw`
(`P P . . N .`) where the byte forms run `b1scl` (sim differs 65 / 66 and 45 / 45). On main's
snapshot SET1 / NOT1 r16,CL are fixed (`b1scl`, ok); **the `rmw_b` fault is still there**
(240 subject-runs).

Other ce9ea43 mismatches it ranks highest (all of them work orders already read: specs 15-17):
the strict bus-idle word missing (81 /0 reg 1,010 runs, C7 / 81 with d16 / direct, LEA d16 /
direct, JMP far / CALL far), JMP short's displacement word not bus-idle (EB, 900), SHL imm8's
bus-idle count word (C1 /4, 810), TEST's own head on [d16] / imm16 forms, POP [BW+IX+d16],
MOV [BW+IX+d16],imm16 one word short (156), the TEST1 / SET1 / CLR1 r,CL / r,imm commit words (C
where the model has B; fixed on main), TEST AW,imm16 / CMP AW,imm16 / CVTDB / DI routines.
On main the strict word, JMP short, SHL imm8, LEA, the 0F register forms, TEST's head and POP
[BW+IX+d16] are fixed; left: rmw_b, MOV [BW+IX+d16],imm16 (one word short of `P . . . BIYPP2`),
SET1 mem,CL with d8 / d16 / direct (the displacement released by the EA head, not later), SHL
[BW+d16],1, TEST / CMP AW,imm16, CVTDB, DI, CALL far / BR far (no Q word, by design), and the
decode differences below.

Decode facts that differ (not timing-simulated, reported separately): the three-bytes boundary
wait on FF / F7 memory forms (the model's MEM table marks them ModR/M: INC / DEC / PUSH [BW],
TEST [BW],imm16, NOT / NEG [BW+d16]: 786 runs on main; the ROM's NO_M3 exempts F6 / F7 / FE / FF
from register-form probes), and BRK 3's lead (model 1, ROM 3). One side of each is wrong; the
tool cannot say which.

## What is exact, approximate, not covered

**A (corpus_model).** Exact: the model's own prediction (model_m.simulate unchanged, DEFAULT
options) on the corpus record as-is; the comparison of clock, kind and fetch address of every
event from t_fill to the END's OUT. Approximate: the clock origin (one calibrated offset per
waits x parity group; unanimous on the sample). Not compared (differs from replay's RTL-exact):
data-cycle addresses, I/O ports (the model tracks DW only from MOV DW,imm16), widths, lengths,
events after the END's OUT. Not covered: 2,784 runs whose encodings the model has no routine for,
432 where it raises on function it does not track, F0w.

**B (cluster).** Exact: parity, waits, frame, the RTL's and the model's first divergent event
pair and its class. Approximate: the instruction at the divergence and the bytes held come from
the model's timeline, right up to the model's own first divergence (663 of the 2,932 RTL rows
lie past it or have no timeline: flagged `timeline_ok: false`; runs without a timeline name the
subject with `?`). The RTL rows' class uses only the miss list's (silicon, RTL) pair, so a
missing / extra event shows as "kind vs kind". The divergent instruction is the one in the EU on
that clock: a fetch's cause may be the instruction before it (the `prev` field).

**C (romcheck).** Exact: the ROM path (the decode cells as `assemble()` lays them out, the
dispatch's EA head as `v35_loader.sv` chooses it, incl. eaq16x, the 0F EAC call, calls / jumps /
loops / counters from CL and the immediate), releases (ro, rl, the loader's ModR/M release),
the wait kinds (bi, alt, rl=x, strict), D, F, K and the post positions. Approximate: the request
act's position is the post's word minus 3 (first post, or after an rl=x word) or minus 1 (later
posts) in an unstalled path; the conditions XC / SNZ follow the model key (taken / not taken),
the DBNZE / DBNZNE count-and-flag pair collapses into one (E0 / E1 show `LOOP` in the string
column; the sim uses the model's own override keys); the decode facts compare the lead and the
three-bytes wait only. Not derivable from ROM bits: the model's G and Q acts (judged by the sim).
Not covered: REP strings (the model builds them from the prefix and CW), EXT / INS / EXTI / INSI
(the ROM counter from SIGMA and data-dependent conditions), ADD4S / SUB4S / CMP4S (no sim run),
transfers that need stack or pointer state for the sim (RETI, BRK, CALL / BR through memory:
string comparison only), prefixes (run as their own instruction), encodings without a model
routine (118). The sim check uses the model's machine, so "equivalent" means "the same bus
events under the model's rules", not "the same as silicon".

## Appendix 1: cluster tables (top 25; RTL = land14)

#### RTL (land14) vs silicon, view 1: instr | prev | parity | waits | held | div | behind

| # | runs | signature | examples |
|---|---|---|---|
| 1 | 43 | LS:movcl / M1:out / O / 0 / 6 / fetch early by 1 / out | F23-out-be-n0-pO-w0, F30-out-br-short-n1-pad1-pO-w0, F35-out-far-callf-retf-pO-w0 |
| 2 | 31 | LS:movcl / M1:out / E / 0 / 6 / fetch early by 1 / out | F23-out-be-n1-pE-w0, F23-out-dbnz-c2-n0-pE-w0, F34-out-cr-nop-l0-pE-w0 |
| 3 | 29 | LS:movcl / M1:out / O / 0 / 6 / io-write early by 3 / out | F5-out-st_imm_bw-k1-pO-w0, F21-out-l0-sti-bw_d16-pO-w0, F21-out-es-sti-bw_ix-pO-w0 |
| 4 | 16 | D4 / M0:out / E / 0 / 5 / fetch early by 1 / - | F6-out-ld_bw-n2d4-pE-w0, F6-out-out_imm_al-n4d4-pE-w0, F30-out-str-outm-w-n1-d4-pE-w0 |
| 5 | 16 | D4 / M0:out / E / 1 / 5 / fetch early by 1 / - | F6-out-ld_bw-n2d4-pE-w1, F6-out-out_imm_al-n4d4-pE-w1, F30-out-str-outm-w-n1-d4-pE-w1 |
| 6 | 16 | D4 / M0:out / E / 2 / 5 / fetch early by 1 / - | F6-out-ld_bw-n2d4-pE-w2, F6-out-out_imm_al-n4d4-pE-w2, F30-out-str-outm-w-n1-d4-pE-w2 |
| 7 | 16 | add_dw_imm2a01? / ? / E / 0 / ? / fetch early by 1 / out | F35-out-cc-bv-t-n0-pE-w0, F35-out-cc-bnh-nt-n2-pE-w0, F35-out-cc-bpo-t-n0-pE-w0 |
| 8 | 16 | add_dw_imm2a01? / ? / E / 1 / ? / fetch early by 1 / out | F35-out-cc-bv-t-n0-pE-w1, F35-out-cc-bnh-nt-n2-pE-w1, F35-out-cc-bpo-t-n0-pE-w1 |
| 9 | 16 | add_dw_imm2a01? / ? / E / 2 / ? / fetch early by 1 / out | F35-out-cc-bv-t-n0-pE-w2, F35-out-cc-bnh-nt-n2-pE-w2, F35-out-cc-bpo-t-n0-pE-w2 |
| 10 | 15 | add_dw_imm0 / M0:push / E / 0 / 4 / fetch early by 1 / push | F10-push-adddwi-outdw-pE-w0, F19-d-push-adddwi_nop-outw-pE-w0, F20-r-push-l0-adddwi-ld-pE-w0 |
| 11 | 15 | LS:movcl / M1:out / E / 0 / 4 / fetch early by 1 / out | F24-out-a-rep-movbk-w-n1-iy-pE-w0, F24-out-a-rep-inm-w-n1-iy-pE-w0, F30-out-odd-cmpbk-ix-n1-end-pE-w0 |
| 12 | 14 | add_dw_imm0 / M0:out / E / 0 / 5 / fetch early by 1 / out | F19-d-out-adddwi-outb-pE-w0, F19-d-out-adddwi-inb-pE-w0, F20-r-out-l0-adddwi-ld-pE-w0 |
| 13 | 14 | add_dw_imm0 / M0:out / E / 1 / 5 / fetch early by 1 / out | F19-d-out-adddwi-outb-pE-w1, F19-d-out-adddwi-inb-pE-w1, F20-r-out-l0-adddwi-ld-pE-w1 |
| 14 | 14 | add_dw_imm0 / M0:out / E / 2 / 5 / fetch early by 1 / out | F19-d-out-adddwi-outb-pE-w2, F19-d-out-adddwi-inb-pE-w2, F20-r-out-l0-adddwi-ld-pE-w2 |
| 15 | 14 | cmp_aw_aw? / ? / E / 0 / ? / fetch early by 4 / out | F35-out-cc-bnv-t-n0-pE-w0, F35-out-cc-bnh-t-n0-pE-w0, F35-out-cc-bpe-t-n0-pE-w0 |
| 16 | 14 | cmp_aw_aw? / ? / O / 0 / ? / fetch early by 1 / out | F35-out-cc-bnv-t-n0-pO-w0, F35-out-cc-bnh-t-n0-pO-w0, F35-out-cc-bpe-t-n0-pO-w0 |
| 17 | 14 | cmp_aw_aw? / ? / E / 1 / ? / fetch late by 1 / out | F35-out-cc-bnv-t-n0-pE-w1, F35-out-cc-bnh-t-n0-pE-w1, F35-out-cc-bpe-t-n0-pE-w1 |
| 18 | 13 | LS:movcl / M1:out / E / 0 / 6 / io-write early by 3 / out | F19-i-out-n3-stimm-pE-w0, F21-out-l0-sti-bw_ix_d8-pE-w0, F21-out-n3-sti-dir-pE-w0 |
| 19 | 13 | LS:shl / LS:movcl / E / 0 / 4 / fetch early by 1 / out | F24-out-a-rep-movbk-w-n4-iy-pE-w0, F24-out-a-repe-cmpbk-w-n2-ixiy-pE-w0, F30-out-odd-movbk-ixiy-n2-end-pE-w0 |
| 20 | 12 | pop_m / M0:out / E / 0 / 5 / fetch early by 1 / out | F5-out-pop_m-k1-pE-w0, F14-g-out-pop_bw-k2-pE-w0, F15-p-out-pop_push-pE-w0 |
| 21 | 12 | pop_m / M0:out / E / 1 / 5 / fetch early by 1 / out | F5-out-pop_m-k1-pE-w1, F14-g-out-pop_bw-k2-pE-w1, F15-p-out-pop_push-pE-w1 |
| 22 | 12 | pop_m / M0:out / E / 2 / 5 / fetch early by 1 / out | F5-out-pop_m-k1-pE-w2, F14-g-out-pop_bw-k2-pE-w2, F15-p-out-pop_push-pE-w2 |
| 23 | 12 | test1_mw_cl / M0:out / E / 0 / 5 / read late by 3 / out | F32-out-test1_mw_cl-k1-pE-w0, F34-out-mbit-test1_mw_cl-l0-k2-gap-pE-w0, F39-out-page-test1-out-pE-w0 |
| 24 | 12 | test1_mw_cl / M0:out / E / 1 / 5 / read late by 3 / out | F32-out-test1_mw_cl-k1-pE-w1, F34-out-mbit-test1_mw_cl-l0-k2-gap-pE-w1, F39-out-page-test1-out-pE-w1 |
| 25 | 12 | test1_mw_cl / M0:out / E / 2 / 5 / read late by 3 / out | F32-out-test1_mw_cl-k1-pE-w2, F34-out-mbit-test1_mw_cl-l0-k2-gap-pE-w2, F39-out-page-test1-out-pE-w2 |

#### RTL (land14) vs silicon, view 2: prev | parity | waits | held | div | behind (no instruction)

| # | runs | signature | examples |
|---|---|---|---|
| 1 | 97 | M0:out / E / 0 / 5 / read late by 3 / out | F32-out-test1_mb_cl-k1-pE-w0, F32-out-ins_bl_dh-k1-pE-w0, F34-out-bf-ins_bl_i7-l0-k1-freg-pE-w0 |
| 2 | 85 | M0:out / E / 0 / 5 / fetch early by 1 / out | F3-out-add_dw_imm-k1-pE-w0, F19-d-out-adddwi_nop-inw-pE-w0, F25-out-ldea-bw_iy_d16-pE-w0 |
| 3 | 77 | M0:out / E / 1 / 5 / fetch early by 1 / out | F3-out-add_dw_imm-k1-pE-w1, F19-d-out-adddwi-inb-pE-w1, F21-out-l0-pop-bw_d8-k2-pE-w1 |
| 4 | 77 | M0:out / E / 2 / 5 / fetch early by 1 / out | F3-out-add_dw_imm-k1-pE-w2, F19-d-out-adddwi-inb-pE-w2, F21-out-l0-pop-bw_d8-k2-pE-w2 |
| 5 | 57 | M0:out / E / 1 / 5 / read late by 4 / out | F32-out-ext_bl_dh-k1-pE-w1, F32-out-ins_dl_bh-k2-pE-w1, F34-out-bf-ext_bl_i7-l0-k1-freg-pE-w1 |
| 6 | 57 | M0:out / E / 2 / 5 / read late by 4 / out | F32-out-ext_bl_dh-k1-pE-w2, F32-out-ins_dl_bh-k2-pE-w2, F34-out-bf-ins_bl_dh-l0-k1-pE-w2 |
| 7 | 53 | M0:push / E / 1 / 4 / fetch vs read / push | F4-push-ld_dir-k1-pE-w1, F14-t-push-add_bw_al-k2-pE-w1, F21-push-l0-add-bw_ix_d16-k2-pE-w1 |
| 8 | 51 | M0:push / E / 2 / 4 / fetch vs read / push | F4-push-ld_dir-k1-pE-w2, F14-t-push-add_bw_al-k2-pE-w2, F21-push-l0-add-bw_ix_d16-k2-pE-w2 |
| 9 | 44 | M0:push / E / 0 / 4 / fetch vs read / push | F4-push-ld_dir-k1-pE-w0, F14-t-push-xch_dir_aw-k2-pE-w0, F22-push-l0-add8_d16-k2-pE-w0 |
| 10 | 43 | M1:out / O / 0 / 6 / fetch early by 1 / out | F23-out-be-n0-pO-w0, F30-out-br-short-n1-pad1-pO-w0, F35-out-far-callf-retf-pO-w0 |
| 11 | 40 | M0:out / E / 1 / 5 / read late by 3 / out | F32-out-test1_mb_cl-k1-pE-w1, F32-out-not1_mb_cl-k2-pE-w1, F34-out-mbit-clr1_mw_cl-l0-k2-gap-pE-w1 |
| 12 | 40 | M0:out / E / 2 / 5 / read late by 3 / out | F32-out-test1_mb_cl-k1-pE-w2, F32-out-not1_mb_cl-k2-pE-w2, F34-out-mbit-clr1_mw_cl-l0-k2-gap-pE-w2 |
| 13 | 34 | M0:push / E / 0 / 4 / fetch early by 1 / push | F3-push-add_dw_imm-k1-pE-w0, F19-d-push-adddwi_nop-outw-pE-w0, F21-push-l0-sti-bw_ix_d16-k2-pE-w0 |
| 14 | 34 | ? / E / 1 / ? / fetch late by 1 / out | F33-out-adj4s-k2-pE-w1, F35-out-cc-bp-t-n0-pE-w1, F37-out-indm-callm-n0-pE-w1 |
| 15 | 31 | M1:out / E / 0 / 6 / fetch early by 1 / out | F23-out-be-n1-pE-w0, F23-out-dbnz-c2-n0-pE-w0, F34-out-cr-nop-l0-pE-w0 |
| 16 | 30 | ? / O / 0 / ? / fetch early by 1 / out | F35-out-cc-bv-t-n0-pO-w0, F35-out-cc-bh-t-n0-pO-w0, F35-out-cc-blt-t-n0-pO-w0 |
| 17 | 30 | ? / E / 0 / ? / fetch early by 4 / out | F35-out-cc-bnv-t-n0-pE-w0, F35-out-cc-bp-t-n0-pE-w0, F35-out-ind-callr-ret-pE-w0 |
| 18 | 29 | M1:out / O / 0 / 6 / io-write early by 3 / out | F5-out-st_imm_bw-k1-pO-w0, F21-out-l0-sti-bw_d16-pO-w0, F21-out-es-sti-bw_ix-pO-w0 |
| 19 | 29 | ? / E / 0 / ? / fetch early by 1 / out | F15-a-out-and_dir_aw-pE-w0, F35-out-cc-bh-t-n0-pE-w0, F35-out-cc-bgt-t-n2-pE-w0 |
| 20 | 27 | ? / O / 0 / ? / fetch vs write / out | F37-out-indm-callm-n0-pO-w0, F37-out-farm-callfm-n0-pO-w0, F39-out-ind-callm-push-pO-w0 |
| 21 | 27 | ? / E / 0 / ? / fetch vs write / push | F37-push-indm-callm-n0-pE-w0, F37-push-farm-callfm-n0-pE-w0, F39-push-ind-callm-push-pE-w0 |
| 22 | 23 | M0:out / O / 0 / 4 / read early by 1 / out | F14-t-out-add_bw_al-pO-w0, F24-out-s-ldm-w-k2-pO-w0, F38-out-rmw-add_m_al-pO-w0 |
| 23 | 23 | M0:out / O / 1 / 4 / read early by 1 / out | F14-t-out-add_bw_al-pO-w1, F24-out-s-ldm-w-k2-pO-w1, F38-out-rmw-add_m_al-pO-w1 |
| 24 | 23 | M0:out / O / 2 / 4 / read early by 1 / out | F14-t-out-add_bw_al-pO-w2, F24-out-s-ldm-w-k2-pO-w2, F38-out-rmw-add_m_al-pO-w2 |
| 25 | 20 | M0:push / O / 0 / 5 / read early by 2 / push | F14-t-push-add_bw_al-pO-w0, F38-push-rmw-addc_m_aw-pO-w0, F38-push-rmw-or_m_al-pO-w0 |

#### model vs silicon, view 1: instr | prev | parity | waits | held | div | behind

| # | runs | signature | examples |
|---|---|---|---|
| 1 | 37 | LS:movcl / M1:out / O / 0 / 6 / io-write early by 3 / out | F5-out-st_imm_bw-k1-pO-w0, F21-out-es-sti-dir-pO-w0, F22-out-es-sti_bw-pO-w0 |
| 2 | 16 | D4 / M0:out / E / 0 / 5 / fetch early by 1 / - | F6-out-ld_bw-n2d4-pE-w0, F6-out-st_bw-n4d4-pE-w0, F30-out-str-outm-w-n0-d4-pE-w0 |
| 3 | 16 | D4 / M0:out / E / 1 / 5 / fetch early by 1 / - | F6-out-ld_bw-n2d4-pE-w1, F6-out-st_bw-n4d4-pE-w1, F30-out-str-outm-w-n0-d4-pE-w1 |
| 4 | 16 | D4 / M0:out / E / 2 / 5 / fetch early by 1 / - | F6-out-ld_bw-n2d4-pE-w2, F6-out-st_bw-n4d4-pE-w2, F30-out-str-outm-w-n0-d4-pE-w2 |
| 5 | 14 | add_dw_imm0 / M0:out / E / 0 / 5 / fetch early by 1 / out | F19-d-out-adddwi-inb-pE-w0, F19-d-out-adddwi_nop-inb-pE-w0, F20-r-out-l0-adddwi-ld-pE-w0 |
| 6 | 14 | add_dw_imm0 / M0:out / E / 1 / 5 / fetch early by 1 / out | F19-d-out-adddwi-inb-pE-w1, F19-d-out-adddwi_nop-inb-pE-w1, F20-r-out-l0-adddwi-ld-pE-w1 |
| 7 | 14 | add_dw_imm0 / M0:out / E / 2 / 5 / fetch early by 1 / out | F19-d-out-adddwi-inb-pE-w2, F19-d-out-adddwi_nop-inb-pE-w2, F20-r-out-l0-adddwi-ld-pE-w2 |
| 8 | 14 | LS:movcl / M1:out / E / 0 / 6 / io-write early by 3 / out | F19-i-out-l0-stimmd8-pE-w0, F21-out-l0-sti-bw_ix_d8-pE-w0, F21-out-n3-sti-bw_ix_d16-pE-w0 |
| 9 | 12 | pop_m / M0:out / E / 0 / 5 / fetch early by 1 / out | F5-out-pop_m-k1-odd-pE-w0, F14-g-out-pop_bw-pE-w0, F15-p-out-pop_nop-pE-w0 |
| 10 | 12 | pop_m / M0:out / E / 1 / 5 / fetch early by 1 / out | F5-out-pop_m-k1-odd-pE-w1, F14-g-out-pop_bw-pE-w1, F15-p-out-pop_nop-pE-w1 |
| 11 | 12 | pop_m / M0:out / E / 2 / 5 / fetch early by 1 / out | F5-out-pop_m-k1-odd-pE-w2, F14-g-out-pop_bw-pE-w2, F15-p-out-pop_nop-pE-w2 |
| 12 | 12 | repe_cmpbk_w+1 / repe_cmpbk_w / E / 0 / 3 / read late by 6 / out | F24-out-a-repe-cmpbk-w-n1-ixiy-pE-w0, F30-out-odd-cmpbk-ix-n2-end-pE-w0, F30-out-odd-cmpbk-ixiy-n1-reg-pE-w0 |
| 13 | 12 | repe_cmpbk_w+1 / repe_cmpbk_w / E / 1 / 3 / read late by 6 / out | F24-out-a-repe-cmpbk-w-n1-ixiy-pE-w1, F30-out-odd-cmpbk-ix-n2-end-pE-w1, F30-out-odd-cmpbk-ixiy-n1-reg-pE-w1 |
| 14 | 12 | repe_cmpbk_w+1 / repe_cmpbk_w / E / 2 / 3 / read late by 6 / out | F24-out-a-repe-cmpbk-w-n1-ixiy-pE-w2, F30-out-odd-cmpbk-ix-n2-end-pE-w2, F30-out-odd-cmpbk-ixiy-n1-reg-pE-w2 |
| 15 | 12 | repe_cmpbk_w+1 / repe_cmpbk_w / O / 0 / 4 / read late by 6 / out | F24-out-a-repe-cmpbk-w-n1-ixiy-pO-w0, F30-out-odd-cmpbk-ix-n2-end-pO-w0, F30-out-odd-cmpbk-ixiy-n1-reg-pO-w0 |
| 16 | 12 | repe_cmpbk_w+1 / repe_cmpbk_w / O / 1 / 4 / read late by 6 / out | F24-out-a-repe-cmpbk-w-n1-ixiy-pO-w1, F30-out-odd-cmpbk-ix-n2-end-pO-w1, F30-out-odd-cmpbk-ixiy-n1-reg-pO-w1 |
| 17 | 12 | repe_cmpbk_w+1 / repe_cmpbk_w / O / 2 / 4 / read late by 6 / out | F24-out-a-repe-cmpbk-w-n1-ixiy-pO-w2, F30-out-odd-cmpbk-ix-n2-end-pO-w2, F30-out-odd-cmpbk-ixiy-n1-reg-pO-w2 |
| 18 | 12 | test1_mw_cl / M0:out / E / 0 / 5 / read late by 3 / out | F32-out-test1_mw_cl-k1-pE-w0, F34-out-mbit-test1_mw_cl-l0-k2-pE-w0, F39-out-page-test1-push-pE-w0 |
| 19 | 12 | test1_mw_cl / M0:out / E / 1 / 5 / read late by 3 / out | F32-out-test1_mw_cl-k1-pE-w1, F34-out-mbit-test1_mw_cl-l0-k2-pE-w1, F39-out-page-test1-push-pE-w1 |
| 20 | 12 | test1_mw_cl / M0:out / E / 2 / 5 / read late by 3 / out | F32-out-test1_mw_cl-k1-pE-w2, F34-out-mbit-test1_mw_cl-l0-k2-pE-w2, F39-out-page-test1-push-pE-w2 |
| 21 | 10 | LS:movcl / M1:out / O / 1 / 4 / io-write early by 4 / out | F5-out-st_imm_bw-k1-odd-pO-w1, F19-i-out-n3-stimmd8-pO-w1, F21-out-n3-sti-bw_d8-pO-w1 |
| 22 | 9 | st_imm_bw_d16 / M0:out / E / 0 / 5 / extra write / out | F5-out-st_imm_bw_d16-k1-pE-w0, F19-i-out-l0-stimmd16-pE-w0, F22-out-l0-sti_d16-k2-pE-w0 |
| 23 | 9 | br_n1 / ret / E / 0 / 4 / fetch late by 1 / out | F23-out-callret-pE-w0, F35-out-ret-callret-pE-w0, F39-out-xfer-callret-out-pE-w0 |
| 24 | 9 | br_n1 / ret / O / 0 / 3 / fetch late by 1 / out | F23-out-callret-pO-w0, F35-out-ret-callret-pO-w0, F39-out-xfer-callret-out-pO-w0 |
| 25 | 9 | ext_bl_dh / M0:out / E / 0 / 5 / read late by 3 / out | F32-out-ext_bl_dh-k1-pE-w0, F34-out-bf-ext_bl_dh-l0-k1-fnop-pE-w0, F39-out-page-ext-movr-pE-w0 |

#### model vs silicon, view 2: prev | parity | waits | held | div | behind (no instruction)

| # | runs | signature | examples |
|---|---|---|---|
| 1 | 97 | M0:out / E / 0 / 5 / read late by 3 / out | F32-out-clr1_mb_cl-k1-pE-w0, F32-out-not1_mb_cl-k1-pE-w0, F34-out-bf-ins_dl_bh-l0-k1-pE-w0 |
| 2 | 75 | M0:out / E / 0 / 5 / fetch early by 1 / out | F3-out-add_dw_imm-k1-pE-w0, F19-d-out-adddwi_nop-inw-pE-w0, F21-out-l0-st-bw_ix_d16-k2-pE-w0 |
| 3 | 75 | M0:out / E / 1 / 5 / fetch early by 1 / out | F3-out-add_dw_imm-k1-pE-w1, F19-d-out-adddwi_nop-inw-pE-w1, F21-out-l0-st-bw_ix_d16-k2-pE-w1 |
| 4 | 75 | M0:out / E / 2 / 5 / fetch early by 1 / out | F3-out-add_dw_imm-k1-pE-w2, F19-d-out-adddwi_nop-inw-pE-w2, F21-out-l0-st-bw_ix_d16-k2-pE-w2 |
| 5 | 57 | M0:out / E / 1 / 5 / read late by 4 / out | F32-out-ext_bh_bl-k1-pE-w1, F32-out-ins_bl_i7-k2-pE-w1, F34-out-bf-ins_bl_dh-l0-k1-fld-pE-w1 |
| 6 | 57 | M0:out / E / 2 / 5 / read late by 4 / out | F32-out-ext_bh_bl-k1-pE-w2, F32-out-ins_bl_i7-k2-pE-w2, F34-out-bf-ins_bl_dh-l0-k1-fld-pE-w2 |
| 7 | 40 | M0:out / E / 1 / 5 / read late by 3 / out | F32-out-clr1_mb_cl-k1-pE-w1, F32-out-set1_mw_cl_bw_ix-k1-pE-w1, F34-out-mbit-set1_mw_cl_bw_ix-l0-k1-pE-w1 |
| 8 | 40 | M0:out / E / 2 / 5 / read late by 3 / out | F32-out-clr1_mb_cl-k1-pE-w2, F32-out-set1_mw_cl_bw_ix-k1-pE-w2, F34-out-mbit-set1_mw_cl_bw_ix-l0-k1-pE-w2 |
| 9 | 37 | M1:out / O / 0 / 6 / io-write early by 3 / out | F5-out-st_imm_bw-k1-pO-w0, F21-out-es-sti-dir-pO-w0, F22-out-es-sti_bw-pO-w0 |
| 10 | 26 | M0:out / E / 0 / 5 / fetch late by 1 / out | F14-t-out-xch_bw_al-pE-w0, F23-out-br-n7-pE-w0, F30-out-br-short-n1-pad2-pE-w0 |
| 11 | 20 | shl_imm8 / E / 0 / 6 / fetch late by 1 / out | F16-l-out-shli8-pE-w0, F34-out-bf-ins_bl_i7-sep-k1-pE-w0, F34-out-mbit-set1_mw_cl-sep-k1-pE-w0 |
| 12 | 20 | shl_imm8 / E / 1 / 6 / fetch late by 1 / out | F16-l-out-shli8-pE-w1, F34-out-bf-ins_bl_i7-sep-k1-pE-w1, F34-out-mbit-set1_mw_cl-sep-k1-pE-w1 |
| 13 | 20 | shl_imm8 / E / 2 / 6 / fetch late by 1 / out | F16-l-out-shli8-pE-w2, F34-out-bf-ins_bl_i7-sep-k1-pE-w2, F34-out-mbit-set1_mw_cl-sep-k1-pE-w2 |
| 14 | 19 | M0:out / O / 0 / 4 / fetch late by 1 / out | F23-out-br-n0-pO-w0, F23-out-br-n6-pO-w0, F23-out-call-pO-w0 |
| 15 | 16 | M0:out / E / 0 / 5 / fetch early by 1 / - | F6-out-ld_bw-n2d4-pE-w0, F6-out-st_bw-n4d4-pE-w0, F30-out-str-outm-w-n0-d4-pE-w0 |
| 16 | 16 | M0:out / E / 1 / 5 / fetch early by 1 / - | F6-out-ld_bw-n2d4-pE-w1, F6-out-st_bw-n4d4-pE-w1, F30-out-str-outm-w-n0-d4-pE-w1 |
| 17 | 16 | M0:out / E / 2 / 5 / fetch early by 1 / - | F6-out-ld_bw-n2d4-pE-w2, F6-out-st_bw-n4d4-pE-w2, F30-out-str-outm-w-n0-d4-pE-w2 |
| 18 | 15 | M0:push / O / 1 / 5 / read vs fetch / push | F15-a-push-and_bw_imm8-pO-w1, F16-r-push-sar-x_x-pO-w1, F38-push-grp-sub_m_imm8-pO-w1 |
| 19 | 15 | M0:push / O / 2 / 5 / read vs fetch / push | F15-a-push-and_bw_imm8-pO-w2, F16-r-push-sar-x_x-pO-w2, F38-push-grp-sub_m_imm8-pO-w2 |
| 20 | 14 | M0:push / E / 1 / 4 / read early by 1 / push | F14-t-push-test_bw_imm-k2-pE-w1, F39-push-ctl-cmpbk-s-pE-w1, F39-push-str-cmpbk-out-pE-w1 |
| 21 | 14 | M0:push / E / 2 / 4 / read early by 2 / push | F14-t-push-test_bw_imm-k2-pE-w2, F39-push-ctl-cmpbk-s-pE-w2, F39-push-str-cmpbk-out-pE-w2 |
| 22 | 14 | M1:out / E / 0 / 6 / io-write early by 3 / out | F19-i-out-l0-stimmd8-pE-w0, F21-out-l0-sti-bw_ix_d8-pE-w0, F21-out-n3-sti-bw_ix_d16-pE-w0 |
| 23 | 14 | ret / E / 0 / 4 / fetch late by 1 / out | F23-out-callret-pE-w0, F34-out-cr-none-l0-pE-w0, F35-out-ret-callret-pE-w0 |
| 24 | 13 | M0:out / E / 0 / 5 / extra write / out | F5-out-st_imm_bw_d16-k1-pE-w0, F21-out-l0-sti-bw_d16-k2-pE-w0, F22-out-l0-sti_d16-k2-pE-w0 |
| 25 | 13 | ret / O / 0 / 3 / fetch late by 1 / out | F23-out-callret-pO-w0, F34-out-cr-none-l0-pO-w0, F39-out-stack-ds0-callret-pO-w0 |

## Appendix 2: romcheck tables

#### ROM of ce9ea43: status of 447 encodings

| status | encodings | subject-runs |
|---|---|---|
| equivalent (shape differs, sim same) | 133 | 18684 |
| model has no routine | 118 | 4362 |
| mismatch | 80 | 6332 |
| ok | 73 | 30182 |
| not covered | 20 | 2604 |
| model gap | 16 | 336 |
| decode only | 4 | 570 |
| shape differs, no sim run (transfers / stack state) | 2 | 168 |
| ok (sim) | 1 | 60 |

#### ROM of ce9ea43: mismatches by corpus runs (top 30)

| runs | encoding | model key | ROM routine | sim differ | model | ROM | forms |
|---|---|---|---|---|---|---|---|
| 1010 | `81 /0 reg` | AI16R | grp1_rw | 6/66 | `P . . . BIPP2N .` | `P . . . BPP2N .` | add_dw_imm, add_dw_imm0 |
| 900 | `EB` | JMP | br_short | 6/66 | `. . . BP . . F N .` | `. . . P . . F N .` | br_n1, br_n3 |
| 810 | `C1 /4 reg` | SHLI | shift_imm | 14/66 | `P . . BP . S . . . . . . . . . . . N .` | `P . . P . . S . . . . . . . . . . . N .` | shl_imm8, shl_imm4 |
| 342 | `C7 /0 m2r7` | STIM_D16 | st_imm16_d16 | 6/66 | `P . . BIYPP2 . . . PP2KN .` | `P . . BYPP2 . . . PP2KN .` | st_imm_bw_d16 |
| 294 | `C7 /0 m0r6` | STIM_D16 | st_imm16_dir | 4/66 | `P . . BIYPP2 . . . PP2KN .` | `P . . BYPP2 . . . PP2KN .` | st_imm_dir, st_imm0_dir_c42 |
| 210 | `0F 15 reg` | TEST1 | b1sclw | 65/66 | `P . BP . . BN .` | `P P . . N .` | set1_rw_cl |
| 156 | `C7 /0 m2r0` | STIM_X16 | st_imm16_d16 | 30/66 | `P . . . BIYPP2 . . . PP2KN .` | `P . . BYPP2 . . . PP2KN .` | st_imm_bw_ix_d16 |
| 144 | `81 /0 m2r7` | ADDIW_D16 | grp1_mw_d16 | 5/66 | `P . . BIYPP2 DPP2Z G N .` | `P . . BYPP2 . . . DPP2Z . BN .` | add_m_imm_d16 |
| 144 | `85 m0r6` | TESTM_DIR | test_m16 | 61/66 | `P . B Y . PP2 DN .` | `PP2 P . . B Y . . . DN .` | test_dir_aw |
| 120 | `81 /0 m0r6` | ADDIW_DIR | grp1_mw_dir | 4/66 | `P . . BIYPP2 DPP2Z G N .` | `P . . BYPP2 . . . DPP2Z . BN .` | add_m_imm_dir |
| 120 | `81 /7 m2r7` | CMPIW_D16 | grp1_mcw_d16 | 3/66 | `P . . BIYPP2 DPP2 . BN .` | `P . . BYPP2 . . . DPP2 . BN .` | cmp_m_imm_d16 |
| 120 | `F7 /0 m2r7` | TESTIM_D16 | test_miw | 65/66; three-bytes wait model 1 ROM 0 | `P . B . . BIYPP2 DPP2 . BN .` | `PP2 P . . B . . Y . . . DPP2 . BN .` | test_m_imm_d16 |
| 108 | `8D m2r7` | LEA_D16 | ldea_d16 | 12/66 | `P . . BIPP2N .` | `P . . BPP2N .` | ldea_bw_d16 |
| 96 | `8F /0 m2r0` | POPM_X16 | pop_m16 | 66/66 | `P . Y D . . . PP2Z G N .` | `P . Y . . . D . . PP2Z . BN .` | pop_m_bw_ix_d16 |
| 96 | `FF /2 m0r6` | CALLM | call_mem_d | 0/0; three-bytes wait model 1 ROM 0 | `P . B Y . PP2 D . . . Z D . . F N .` | `P . B Y . PP2 . D . . . Z . D . . F N .` | call_m_dir |
| 96 | `CC` | INT3 | brk3 | 0/0; lead model 1 ROM 3 | `. . B . B . . Y . . . . . . . DZ D . . U . . . . . DZ D . . . Z D . . F N .` | `. . B . B . . Y . . . . . . . DZ . D . . U . . . . . DZ . D . . . Z . D . . F N .` | brk3 |
| 84 | `E1` | LOOP | dbnz_z | 9/63 | `. . . B . . P . . B . . F N .` | `. . . B . . . P . . B . . F N .` | dbnze_n0 |
| 72 | `0F 1D reg` | TEST1I | b1sim | 9/60 | `P . BP . BPN .` | `P . BP . CPN .` | set1_rw_imm |
| 66 | `0F 14 reg` | TEST1 | b1scl | 10/59 | `P . BP . . BN .` | `P . BP . . CN .` | set1_rb_cl |
| 60 | `8D m0r6` | LEA_DIR | ldea_dir | 12/57 | `P . . BIPP2N .` | `P . . BPP2N .` | ldea_dir |
| 60 | `0F 1C reg` | TEST1I | b1sim | 9/57 | `P . BP . BPN .` | `P . BP . CPN .` | set1_rb_imm |
| 60 | `9A` | CALLF | call_far | 23/30 | `. . . . PP2 . Q . BIPP2 . Y D . Y D . . F N .` | `. . . . PP2 . . . PP2 . Y . . . D . Y . . . D . . F N .` | callf_t0054, callf_t0055 |
| 48 | `09 m0r7` | RMW | rmw_b | 50/54 | `P Y . . DZ G N .` | `YP . . DZ . N .` | or_m_aw |
| 48 | `E0` | LOOP | dbnz_z | 15/54 | `. . . B . . P . . B . . F N .` | `. . . B . . . P . . B . . F N .` | dbnzne_n0 |
| 48 | `EA` | JFAR | br_far | 21/30 | `. . . . PP2 . Q . BIPP2 . . F N .` | `. . . . PP2 . . . PP2 . . F N .` | brf_t0052, brf_t0053 |
| 36 | `8D m2r0` | LEAX_D16 | ldea_d16x | 6/51 | `P . . . BIPP2N .` | `P . . . BPP2N .` | ldea_bw_ix_d16 |
| 36 | `FF /4 m0r6` | JMPM | br_mem_d | 0/0; three-bytes wait model 1 ROM 0 | `P . B Y . PP2 D . . F N .` | `P . B Y . PP2 . D . . F N .` | br_m_dir |
| 36 | `FF /5 m0r6` | JMPFM | br_far_mem_d | 0/0; three-bytes wait model 1 ROM 0 | `P . B . Y PP2 D . U D . . F N .` | `P . B . Y PP2 . . D . U . D . . F N .` | brf_m_dir |
| 36 | `C0 /4 reg` | SHLI | shift_imm | 9/51 | `P . . BP . S . . . . . . . . . . . N .` | `P . . P . . S . . . . . . . . . . . N .` | shl_al_imm4 |
| 30 | `00 m0r7` | RMW | rmw_b | 45/50 | `P Y . . DZ G N .` | `YP . . DZ . N .` | add_m_al |

#### ROM of ce9ea43: one model routine, several ROM routines (top 8)

- model `RMW` (966 runs): ROM `rmw` `P Y . . . DZ . BN .` 726 runs (01 m0r7); ROM `rmw_b` `YP . . DZ . N .` 240 runs (09 m0r7, 00 m0r7, 21 m0r7, 29 m0r7, 11 m0r7, 19 m0r7)
- model `SHL1` (402 runs): ROM `shift_1` `P . B . . B . N .` 294 runs (D1 /4 reg); ROM `shm_1` `P . B Y . . . D . . . . . Z . BN .` 108 runs (D1 /0 m0r7, D1 /1 m0r7, D1 /2 m0r7, D1 /3 m0r7, D1 /5 m0r7, D1 /7 m0r7)
- model `TEST1` (342 runs): ROM `b1sclw` `P P . . N .` 222 runs (0F 15 reg, 0F 17 reg); ROM `b1scl` `P . BP . . CN .` 78 runs (0F 14 reg, 0F 16 reg); ROM `b1tcl` `P . BP . . CN .` 42 runs (0F 11 reg, 0F 10 reg)
- model `LOOP` (306 runs): ROM `dbnz` `. . . B . . P . . B . . F N .` 174 runs (E2); ROM `dbnz_z` `. . . B . . . P . . B . . F N .` 132 runs (E1, E0)
- model `SR` (288 runs): ROM `mov_rs` `PN .` 216 runs (8E reg); ROM `ld_sr` `P Y . . . DN . .` 72 runs (8E m0r4)
- model `INCB` (66 runs): ROM `inc_rm` `P . . BN .` 30 runs (FE /0 reg); ROM `dec_rm` `P . . BN .` 24 runs (FE /1 reg); ROM `dec_m` `P . . B Y . . . DZ . BN .` 12 runs (FE /1 m0r7)
- model `TESTRR` (54 runs): ROM `test_rr` `P . BN .` 36 runs (84 reg); ROM `test_m8` `P . B Y . . . DN .` 18 runs (84 m0r7)

Decode-only differences (ce9ea43): `FF /0 m0r7` 270 runs (three-bytes wait model 1 ROM 0); `FF /6 m0r7` 192 runs (three-bytes wait model 1 ROM 0); `FF /1 m0r7` 60 runs (three-bytes wait model 1 ROM 0); `F7 /0 m0r7` 48 runs (three-bytes wait model 1 ROM 0)

Not covered / no sim (ce9ea43): `REP AB` 300 (not covered: REP string); `0F 33 reg` 258 (not covered: data-dependent ROM path); `REP 6D` 246 (not covered: REP string); `REP A7` 234 (not covered: REP string); `REP AF` 228 (not covered: REP string); `REP A5` 198 (not covered: REP string); `REP 6F` 198 (not covered: REP string); `0F 20 m0r0` 144 (not covered: model routine built in simulate, no sim run); `0F 3B reg` 144 (not covered: data-dependent ROM path); `0F 31 reg` 138 (not covered: data-dependent ROM path); `0F 39 reg` 132 (not covered: data-dependent ROM path); `CF` 132 (shape differs, no sim run); `REP AD` 120 (not covered: REP string); `REP AA` 42 (not covered: REP string)

#### ROM of main: status of 447 encodings

| status | encodings | subject-runs |
|---|---|---|
| equivalent (shape differs, sim same) | 134 | 13608 |
| model has no routine | 118 | 4362 |
| ok | 112 | 40210 |
| mismatch | 35 | 1164 |
| not covered | 20 | 2604 |
| model gap | 16 | 336 |
| decode only | 9 | 786 |
| shape differs, no sim run (transfers / stack state) | 2 | 168 |
| ok (sim) | 1 | 60 |

#### ROM of main: mismatches by corpus runs (top 30)

| runs | encoding | model key | ROM routine | sim differ | model | ROM | forms |
|---|---|---|---|---|---|---|---|
| 156 | `C7 /0 m2r0` | STIM_X16 | st_imm16_d16 | 30/66 | `P . . . BIYPP2 . . . PP2KN .` | `P . . BIYPP2 . . . PP2KN .` | st_imm_bw_ix_d16 |
| 96 | `FF /2 m0r6` | CALLM | call_mem_d | 0/0; three-bytes wait model 1 ROM 0 | `P . B Y . PP2 D . . . Z D . . F N .` | `P . B Y . PP2 . D . . . Z . D . . F N .` | call_m_dir |
| 96 | `CC` | INT3 | brk3 | 0/0; lead model 1 ROM 3 | `. . B . B . . Y . . . . . . . DZ D . . U . . . . . DZ D . . . Z D . . F N .` | `. . B . B . . Y . . . . . . . DZ . D . . U . . . . . DZ . D . . . Z . D . . F N .` | brk3 |
| 84 | `E1` | LOOP | dbnz_z | 9/63 | `. . . B . . P . . B . . F N .` | `. . . B . . . P . . B . . F N .` | dbnze_n0 |
| 60 | `9A` | CALLF | call_far | 7/30 | `. . . . PP2 . Q . BIPP2 . Y D . Y D . . F N .` | `. . . . PP2 . . . BIPP2 . Y . . . D . Y . . . D . . F N .` | callf_t0054, callf_t0055 |
| 48 | `09 m0r7` | RMW | rmw_b | 50/54 | `P Y . . DZ G N .` | `YP . . DZ . N .` | or_m_aw |
| 48 | `E0` | LOOP | dbnz_z | 15/54 | `. . . B . . P . . B . . F N .` | `. . . B . . . P . . B . . F N .` | dbnzne_n0 |
| 48 | `EA` | JFAR | br_far | 7/30 | `. . . . PP2 . Q . BIPP2 . . F N .` | `. . . . PP2 . . . BIPP2 . . F N .` | brf_t0052, brf_t0053 |
| 36 | `FF /4 m0r6` | JMPM | br_mem_d | 0/0; three-bytes wait model 1 ROM 0 | `P . B Y . PP2 D . . F N .` | `P . B Y . PP2 . D . . F N .` | br_m_dir |
| 36 | `FF /5 m0r6` | JMPFM | br_far_mem_d | 0/0; three-bytes wait model 1 ROM 0 | `P . B . Y PP2 D . U D . . F N .` | `P . B . Y PP2 . . D . U . D . . F N .` | brf_m_dir |
| 30 | `00 m0r7` | RMW | rmw_b | 45/50 | `P Y . . DZ G N .` | `YP . . DZ . N .` | add_m_al |
| 30 | `21 m0r7` | RMW | rmw_b | 45/50 | `P Y . . DZ G N .` | `YP . . DZ . N .` | and_m_aw |
| 24 | `29 m0r7` | RMW | rmw_b | 44/48 | `P Y . . DZ G N .` | `YP . . DZ . N .` | sub_m_aw |
| 24 | `D1 /4 m2r7` | SHLM1_D16 | shm_1 | 46/48 | `P . B Y . PP2 D . . . . . Z G N .` | `PP2 P . . B Y . . . D . . . . . Z . BN .` | shl_m1_bw_d16 |
| 24 | `0F 15 m1r7` | S1M_D8 | b1scl | 27/48 | `P . BP . . C Y . P DZ G N .` | `P P . BP . . C Y . . . DZ . BN .` | set1_mw_cl_bw_d8 |
| 24 | `0F 15 m2r7` | S1M_D16 | b1scl | 48/48 | `P . BP . . C Y . PP2 DZ G N .` | `P P P . BP . . C Y . . . DZ . BN .` | set1_mw_cl_bw_d16 |
| 24 | `0F 15 m0r6` | S1M_D16 | b1scl | 48/48 | `P . BP . . C Y . PP2 DZ G N .` | `P P P . BP . . C Y . . . DZ . BN .` | set1_mw_cl_dir |
| 24 | `FF /2 m0r7` | CALLMB | call_mem | 0/0; three-bytes wait model 1 ROM 0 | `P . B Y D . . . Z D . . F N .` | `BP Y . . . D . . . Z . D . . F N .` | call_m_bw |
| 24 | `FF /4 m0r7` | JMPMB | br_mem | 0/0; three-bytes wait model 1 ROM 0 | `P . B Y D . . F N .` | `BP Y . . . D . . F N .` | br_m_bw |
| 24 | `FF /3 m0r6` | CALLFM | call_far_mem_d | 0/0; three-bytes wait model 1 ROM 0 | `P . B . Y PP2 D . U D . . . Z D . . . Z D . . F N .` | `P . B . Y PP2 . . D . U . D . . . Z . D . . . Z . D . . F N .` | callf_m_dir |
| 24 | `FF /3 m0r7` | CALLFMB | call_far_mem | 0/0; three-bytes wait model 1 ROM 0 | `P . B Y D . U D . . . Z D . . . Z D . . F N .` | `YP . . . D . U . D . . . Z . D . . . Z . D . . . . . . . F N .` | callf_m_bw |
| 24 | `FF /5 m0r7` | JMPFMB | br_far_mem | 0/0; three-bytes wait model 1 ROM 0 | `P . B Y D . U D . . F N .` | `YP . . . D . U . D . . . . . . . F N .` | brf_m_bw |
| 12 | `A9` | TESTAI | test_ai16 | 40/45 | `. . . . BIPP2N .` | `. P P N .` | test_aw_imm |
| 12 | `D5` | CVTDB | cvtdb | 44/45 | `. . . BP C . . . . . . . . . . . . N .` | `. P . . . . . . . . . . . . . . . . N .` | cvtdb |
| 12 | `FA` | DIK | flag_di | 16/45 | `. . BN .` | `. . N .` | cli |
| 12 | `3D` | TESTAI | cmp_ai16 | 41/45 | `. . . . BIPP2N .` | `. P P N .` | cmp_aw_imm16 |
| 12 | `11 m0r7` | RMW | rmw_b | 43/45 | `P Y . . DZ G N .` | `YP . . DZ . N .` | addc_m_aw |
| 12 | `19 m0r7` | RMW | rmw_b | 43/45 | `P Y . . DZ G N .` | `YP . . DZ . N .` | subc_m_aw |
| 12 | `31 m0r7` | RMW | rmw_b | 43/45 | `P Y . . DZ G N .` | `YP . . DZ . N .` | xor_m_aw |
| 12 | `08 m0r7` | RMW | rmw_b | 43/45 | `P Y . . DZ G N .` | `YP . . DZ . N .` | or_m_al |

#### ROM of main: one model routine, several ROM routines (top 8)

- model `RMW` (966 runs): ROM `rmw` `P Y . . . DZ . BN .` 726 runs (01 m0r7); ROM `rmw_b` `YP . . DZ . N .` 240 runs (09 m0r7, 00 m0r7, 21 m0r7, 29 m0r7, 11 m0r7, 19 m0r7)
- model `SHL1` (402 runs): ROM `shift_1` `P . B . . B . N .` 294 runs (D1 /4 reg); ROM `shm_1` `P . B Y . . . D . . . . . Z . BN .` 108 runs (D1 /0 m0r7, D1 /1 m0r7, D1 /2 m0r7, D1 /3 m0r7, D1 /5 m0r7, D1 /7 m0r7)
- model `LOOP` (306 runs): ROM `dbnz` `. . . B . . P . . B . . F N .` 174 runs (E2); ROM `dbnz_z` `. . . B . . . P . . B . . F N .` 132 runs (E1, E0)
- model `SR` (288 runs): ROM `mov_rs` `PN .` 216 runs (8E reg); ROM `ld_sr` `P Y . . . DN . .` 72 runs (8E m0r4)
- model `INCB` (66 runs): ROM `inc_rm` `P . . BN .` 30 runs (FE /0 reg); ROM `dec_rm` `P . . BN .` 24 runs (FE /1 reg); ROM `dec_m` `P . . B Y . . . DZ . BN .` 12 runs (FE /1 m0r7)
- model `TESTRR` (54 runs): ROM `test_rr` `P . BN .` 36 runs (84 reg); ROM `test_m8` `P . B Y . . . DN .` 18 runs (84 m0r7)

Decode-only differences (main): `FF /0 m0r7` 270 runs (three-bytes wait model 1 ROM 0); `FF /6 m0r7` 192 runs (three-bytes wait model 1 ROM 0); `F7 /0 m2r7` 120 runs (three-bytes wait model 1 ROM 0); `FF /1 m0r7` 60 runs (three-bytes wait model 1 ROM 0); `F7 /0 m0r7` 48 runs (three-bytes wait model 1 ROM 0); `FF /0 m2r7` 24 runs (three-bytes wait model 1 ROM 0); `F7 /2 m2r7` 24 runs (three-bytes wait model 1 ROM 0); `F7 /3 m2r7` 24 runs (three-bytes wait model 1 ROM 0); `FF /1 m2r7` 24 runs (three-bytes wait model 1 ROM 0)

Not covered / no sim (main): `REP AB` 300 (not covered: REP string); `0F 33 reg` 258 (not covered: data-dependent ROM path); `REP 6D` 246 (not covered: REP string); `REP A7` 234 (not covered: REP string); `REP AF` 228 (not covered: REP string); `REP A5` 198 (not covered: REP string); `REP 6F` 198 (not covered: REP string); `0F 20 m0r0` 144 (not covered: model routine built in simulate, no sim run); `0F 3B reg` 144 (not covered: data-dependent ROM path); `0F 31 reg` 138 (not covered: data-dependent ROM path); `0F 39 reg` 132 (not covered: data-dependent ROM path); `CF` 132 (shape differs, no sim run); `REP AD` 120 (not covered: REP string); `REP AA` 42 (not covered: REP string)
