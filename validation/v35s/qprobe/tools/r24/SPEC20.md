# V35S core v2: RTL work order 20 (from qprobe round 24, results Q110 to Q117)

Against land17 (corpus 29,167 of 30,536 exact; miss list `land17/miss-v35_chk.jsonl`). The reading model
(`validation/v35s/qprobe/model_m.py` in `qprobe-pkg.tgz`) is now exact on 26,926 corpus runs and on
1,006 of the RTL's 1,369 miss rows. Per rule: the mechanism as stages, what is measured / inferred /
unknown, the gate. Notation as in the model: a routine is words, one a clock; `P` / `P2` / `N` pop;
`B` bus-idle; `C` the commit word; `Y` / `X` request words; "held" = bytes behind the staged opcode.
`traces/logs/rtl-miss-model-exact.json` names, for every RTL miss row the model reads, the rules of
this order that carry it (an empty list: the model was already exact without them).

**Common gate.** No corpus run that land17 has exact may be lost (the model loses none of its own
with these rules; it does not move a single RTL-exact run). The program gates and the FPGA gate at
17 ns as in every order. No port of the interface budget is needed by any item: every item is a
condition on levels the bus unit, the loader and the sequencer already exchange. Items A1, A3 and
A4 are the large ones (306 / 146 / 92 rows); build and gate them in one batch.

## A1. The decode lead at a flush target runs from the stream-valid clock (Q113; 306 rows)

- **Mechanism.** (1) A flush empties the queue; the target's first fetch delivers one or two bytes
  and the opcode is popped (staged) at once. (2) The first boundary of the new stream waits for
  four delivered bytes (FIRST_MIN, built). (3) **New:** for an opcode with a decode lead (OUT imm8
  E6, OUT imm8,AW E7, IN imm8 E4: lead 3; RET C3: lead 2, item A5) the lead's count starts on the
  later of the opcode's pop and the first clock on which the fourth byte of the new stream is in
  the queue (the clock after the delivering fetch's last clock). (4) The boundary then follows
  the ordinary rules (not inside a fetch except on its last clock, and so on).
- **Measured:** corpus 306 rows, all W = 0 (transfers of F23, F30, F34, F35, F37, F39, F40 with the OUT
  marker at the target; the RTL has the boundary on the fourth fetch's last clock, silicon one
  clock later: the RTL's next fetch is one clock early). Socket `QPr24c` (144 runs, 24 of them
  discriminate). Example `F23-out-be-n0-pO-w0` (run clocks): target fetches 128 (1 byte), 131, 134,
  137; the fourth byte is in the queue from 137; the boundary on 140 = 137 + 3; port-byte word 144,
  `X` 147, `N` 149 (its pop starts the fetch on 149), I/O 152.
- **Inferred:** the decode stage is started by the loader's stream-valid level, not by the pop.
  In the loader the lead counter (`lc`, the `ld` / `le` facts) would be held at its start value until
  the FIRST_MIN condition is true. **Unknown:** whether silicon restarts or holds the count (both
  give the same clocks here); MOV sreg (lead 2) at a flush target is exact either way.
- **Does not change (gate):** W = 1 / 2 of the same families; PUSH, MOV r,imm8, MOV sreg at flush
  targets (`QPr24c`); every non-flush boundary.

## A2. LEAD_EPRI must not run a boundary in front of FIRST_MIN (model fault found with A1; check the RTL)

The model's rule "a lead that ends on the clock a back-to-back fetch would start lets the boundary
run and delays the fetch" was applied before the stream's four-byte test. With A1 the lead cannot
end before that test at a flush target, so nothing else is needed; if the RTL orders the two the
same way, A1 fixes it. No rows of its own.

## A3. A request word on a fetch's last clock; a pop on the next (Q112; 146 rows)

- **Mechanism.** (1) An EU request word (`Y` of a load, store or PUSH; `X`; not the late request `V`)
  executes on the last clock of a fetch's pin cycle. (2) On the next clock the back-to-back fetch
  is **not** started, with five held (built: REQ_PRI) and **also with four or fewer** (new). (3)
  **Unless the EU pops on that next clock** (the store's `PP2` behind its `Y`): then the back-to-back
  fetch is started by the ordinary five-held test taken behind the pop (new: today's RTL makes no
  fetch here and puts the write first). (4) With no pop the fetch starts one clock later by the
  idle rule (four or fewer held), if the EU cycle is not ripe by then; the EU cycle follows it.
- **Measured:** corpus 146 rows, W = 0, both alignments: (2) PUSH behind a store with an immediate,
  51 rows (`F19-i-push-*-stimm*`, `F21-push-*-sti-*`, `F22-push-*`): silicon's fetch one clock later
  than the RTL's, the PUSH write behind it; (3) MOV [d16],AW behind MOV AW,imm16, 95 rows (F37's
  pointer and vector set-ups, `F30-store-br-*`, `F5-*-st_acc_dir`): silicon fetch, then write; the RTL
  write, then fetch. Socket: 5 runs (`QPr24b-{ri,ai16}-ldacc`, `QPr24b-{stim07,stim80}-push`,
  `QPr21f-f-stix16-mp`). Each half alone: (2) without (3) loses 27 corpus runs.
- **Inferred:** the request takes the bus unit's next decision; a queue read is a new fetch request
  of its own (the model's CHAIN_POP is the same statement). **Unknown:** the latch. At W >= 1 the
  request word itself waits for the fetch's last two clocks and the phase is not seen.
- Example `F19-i-push-n1-stimm-pO-w0`: store write 117 to 119; fetch 120 to 122; PUSH's `Y` on 122; no
  fetch on 123; fetch 124 to 126; PUSH write 127.

## A4. A bus-idle word that pops, against a needed back-to-back fetch (Q111; 92 rows)

- **Mechanism.** (1) A fetch ends on clock t - 1; the stream is live, no EU cycle is running or
  ripe. (2) The bytes held at the start of t (the delivery counted, the word's own pop not) are
  **four or fewer**: the back-to-back fetch starts on t whatever the EU does. (3) A bus-idle word
  that pops (`BP`, `BNP`, `BYP`, `BPN` ...; in microcode terms `bi` with `rl` or `ro`) presented on t
  **stalls**; it waits by that fetch's pin cycle and passes on the clock after it, or on the first
  clock of a following fetch when that one is a five-held continuation (step 4). (4) With **five**
  held at the start of t the fetch is the continuation the word's pop completes: the word passes
  on t (as built). (5) A bus-idle word **without** a pop passes on t in both cases (as built).
  (6) The stalled word does not hold the fetch back (the round-13 rule "no chained fetch when the
  next word is bus-idle" applies to a word not yet reached, not to this one).
- **Measured:** corpus 92 rows: the OUT marker behind a store with an immediate that leaves two
  bytes (69: "I/O write early by 3 / 4" in the RTL, every wait), a second store with d8 directly
  behind the first (23: "fetch against write order"). Socket 57 runs (`QPr24b`: OUT imm8, OUT imm8,AW,
  IN imm8 and MOV AL,imm8 behind MOV [BW],imm16 / [BW+IX+d16],imm16: 16; round 22's open store rows;
  `QPr13a-fw-c7-*-i8`; CALL / JMP far [BW] at even alignment, Q104's left rows). The same wait for a
  word without a pop loses 54 corpus runs.
- **Inferred:** the bus-idle test reads "a fetch is due", which is up before the clock when four
  or fewer are held and only with the pop at five. **Unknown:** why a non-popping bus-idle word
  is not held by the same level.
- Example `F5-out-st_imm_bw-k1-pO-w0`: store write 117 to 119 (two held behind the staged E6);
  boundary 120; fetches 121, 124 (four held at its start), 127; the marker's `BP` presented on 124
  stalls 124 to 126 and passes on 127 (six held, five behind its pop: the continuation); `X` 130;
  I/O 134 (the RTL: 131). At the other alignment three are held at the boundary, five at the second
  fetch's start: the word passes on that clock (exact today; must stay).

## A5. RET near: a decode lead of 2 (Q114; 54 rows)

- **Mechanism.** The boundary of RET (C3) is no sooner than 2 clocks after its pop, as MOV sreg's.
  The decode table's lead field for C3: 2. (A1 then applies to RET at a flush target; the corpus's
  CALL ; RET frames stay exact in the model with both.)
- **Measured:** corpus 54 rows (RET behind SHL r,imm8 / imm4 at a call target, F30 / F34 `cr-shl*`, every
  wait, both alignments, both markers: silicon's stack read one clock later than the RTL's); socket
  2 (`QPr8-ld-ret-i`). Behind NOP (popped three clocks ahead) nothing changes.
- **Unknown:** RET imm16 (C2), RETF (CB), RETF imm16 (CA): 1 or 2 score the same; leave them.

## A6. The bit-field head's commit word (Q110; 112 rows)

- **Mechanism.** EXT / INS (0F 31 / 33 / 39 / 3B; the head `open ; rl=1 bi ; open ; bi alt` shared by
  the four routines) directly behind an I/O write at even alignment: I/O cycle, fetch A, fetch B
  back to back. Spec 18 A2 passes a commit word on B's third-last clock. **For this head's commit
  word: B's fourth-last clock, and not before B's first clock** (B's first clock at W = 0 and 1, its
  second at W = 2). ROL4 / ROR4 r and SHL r,imm8 stay on the third-last clock (measured again:
  moving them loses 12 + 24 socket runs).
- **Measured:** corpus 112 rows (F32 / F34, pE, W = 1 / 2: the read one clock early on silicon against
  the RTL), socket 20 (`QPr21c-c-{ext,ins}_bl_dh-oo`, `QPr24a-{o,e7}-{extr,exti,insr,insi}`). First read
  in clocks from the I/O cycle's first clock: r,r 12 / 13 / 15, imm4 13 / 14 / 16 at W = 0 / 1 / 2.
- **Inferred / unknown:** this is a second kind of commit word, or the same kind with a second
  waiting word in ROL4 / ROR4 / SHL (three decompositions fit, Q110). It is stated for the four
  routines that share the head, not per opcode; it needs a wait code of its own in the microcode
  word (the kind field has free codes: the rulings after round 22 accept them). **Decision asked
  of the coordinator** (below) before it is built.
- **Gate:** the four forms behind OUT ; CLC / CBW / NOP, PUSH, a store, IN imm8, POP and at odd
  alignment (`QPr24a`, 192 runs) are exact today with the third-last rule and must stay.

## B. Routine shapes (Q115)

| routine | change | rows |
|---|---|---|
| ADJBA / ADJBS (37 / 3F) | the third word bus-idle: `. . B` + 12 words + `N .` (17 words, length unchanged) | 24 corpus, 120 socket |
| EI (FB) | the third word bus-idle: `. . B` + 8 words + `N .` (13 words) | 12 corpus, 36 socket |
| PUSH imm16 / imm8 (68 / 6A) | the tail as PUSH r's: `. . . . PP2 . Y . . . N .` / `. . . P . Y . . . N .` (the next opcode released four words behind the request word, then the boundary word): today's successor loses its lead when it is OUT / IN imm8 | 8 corpus, 6 socket |
| PUSH r | the word in front of `N` completes on the clock before the write's first clock (`. . Y . . G N .`), so `N` is on the write's first clock also when the write is late | 2 socket (inferred; check that the RTL's PUSH already ties the release to the cycle) |
| OUT imm8,AW to an odd port | two byte cycles back to back | function; `QPr24b` / `QPr24c` e7 runs need it to be scored |

## C. Build items the model already read before this round (297 rows, no new rule)

`traces/logs/rtl-miss-model-exact.json` rows with an empty rule list. The larger clusters (instruction,
predecessor, alignment, waits, the RTL against silicon; one example each):

| rows | where | example |
|---|---|---|
| 152 | "fetch late by 1" at W = 1 / 2, almost all at or behind a transfer: JMP short / near at a RET's or RETI's target, JMP short / BE directly behind the OUT marker or CMP r,r, and the 66 runs the model could not parse before (Jcc taken, JMP / CALL through a register or memory, BRK) | `F23-out-callret-pE-w1`, `F30-out-cr-a1-b0-pO-w1`, `F23-out-br-n0-pE-w1`, `F23-out-be-n0-pE-w1`, `F35-out-cc-bv-t-n0-pE-w1` (there the chain's third fetch behind OUT ; ADD DW,imm16 is one clock late, in front of the branch) |
| 78 | the marker or the second instance behind EXT with BH as the length or an imm4 of 11 (`ext_dl_bh`, `ext_dl_i11`): fetch early by 1 | `F32-out-ext_dl_bh-k1-pO-w1`, `F34-out-bf-ext_dl_i11-nop-k1-pO-w1` |
| 26 | ADD DW,imm16 / D4 directly behind PUSH at even alignment, W = 0: fetch early by 1 | `F10-push-adddwi-outdw-pE-w0`, `F35-push-ctl-adddw-pE-w0`, `F6-push-ld_bw-n2d4-pE-w0` |
| 41 | others, under 7 rows a state | the json |

(Counted from the json: rows with an empty rule list, by run name and divergence class.)

## Decisions asked

1. **A6:** accept a second commit-word kind for the bit-field head (112 corpus rows, 20 socket runs,
   0 lost, mechanism not separated from its two rivals), or hold it as a known difference until a
   probe separates them? No probe design is known that moves the word against the chain.
2. **The stopping line.** Four states over 20 rows are not read (Q117): REP successors 88, d16 stores
   against the chain 78, BCD strings 39, single string forms behind PUSH 25. The first and the last
   two need model work on the string routines before a probe; the second is Q33's class, on which
   two more readings failed this round. Next round's order?
3. **CVTDB behind an EU cycle** (42 socket runs of `r24a`, 6 corpus rows): under the line on the
   corpus; leave as a known difference?
