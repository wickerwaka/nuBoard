# qprobe, second reading (rounds 4, 5, 7 read; continues ../results.md, same Q format)

Receipts: `traces/socket/QPr{4,5,7}-w*.json` (r4 414 runs, r5 540, r7 42; every run twice; 0
failed; 3 of r5's repeats flagged "DIFFERS" are the known strobe-sample artefact: one fetch's
`strobe` field 7 against 8, start / end / address / data identical - `build/qp/repdiff.py`).
The reading model is `validation/v35s/qprobe/model.py` (its DEFAULT options are the rules).

**Where the model stands.** From the fill to M1: 1,944 of 2,424 runs. **From the fill to the
program's end** (M1, the second long shift, MOV DW,imm16, the final OUT, HALT): **1,912 of
2,424 whole traces** (it was 0: the part after M1 had not been read). Rounds 1, 3 and the
mixes: 795 of 804 whole traces (the nine have an OUT DW inside the body).

## Q10. The instruction boundary waits for *any* bus cycle, the EU's own included

Q4's rule ("no boundary while a fetch is in flight, except on its last clock") holds for a
memory write, a memory read and an I/O cycle of the EU as well. Read from `bp-*` (PUSH AW ; INC
x j ; X): at w0 the write is 3 clocks and nothing shows; at w2 the instruction after the PUSH
starts on the write's last clock (2 to 4 clocks later than a free boundary). 45 -> 120 of 120
runs. This is the machine behind the RTL's RAMEN hold (E waits for a write's end): it is not a
property of on-chip writes, every boundary waits for the bus cycle in flight. Confidence: high.

## Q11. OUT DW is six words and ends when its cycle is granted

The instruction after OUT DW,AL starts on the I/O cycle's *first* clock, wherever that clock
falls: at the routine's seventh clock on an idle bus, later when a fetch delays the cycle
(`base`, `rr-N`, `ri-N` after M1). So the routine's last word waits for the bus unit to take
the request; the earlier reading "8 words" was the idle case. With it and Q10 the second long
shift and the END line up in every round-1 program. The word-wide OUT DW,AW has the byte form's
timing (`ow-N` = `nop-N`, 24 / 24). Confidence: high.

## Q12. No fetch "at five held" after an EU cycle

The fetch that follows an I/O or memory cycle immediately is an ordinary one (four or fewer
held, by the pop of the next instruction's operand): with Q11 the earlier "threshold five after
an EU cycle" is not needed and is wrong for stores (`sacc` pO: five held after the write, no
fetch). Threshold five stays what Q8 says: only on the clock after a *fetch's* delivery.

## Q13. Bus-idle words wait from a fetch's third clock, not for the whole fetch

MOV CL,imm8's pop word runs in the second clock of the fetch that follows M1's I/O cycle
(`base` pO after M1), while in the trains it waited on a fetch's third clock and later. A
bus-idle word (the immediate-pop word, SHL r,CL's fourth word) is held from the fetch's third
clock to its last; the first two clocks (the address phase) are free. 36 more whole traces;
nothing lost in rounds 1-3. The OUT DW request word still waits for the whole fetch.
Confidence: medium-high (the rounds 1-3 data never put a bus-idle word in a fetch's second
clock, the after-M1 part does).

## Q14. HALT acts at the pop of its opcode

`fy-h` (MOV DW,FF00h ; OUT DW,AL ; HALT) against `fy-nh` (a NOP before the HALT): the OUT's
I/O cycle is one clock later when HALT is the next instruction (95 against 94 at w0, 103
against 102 at w2, both alignments, byte and word OUT). The HALT's opcode is popped by the
OUT's fifth word, two clocks before the cycle. Neither DW's new value, nor the word form, nor
the port (`fx-*`: ports 22h, 120h, AW: all 94) does it. And nothing is fetched after that pop
(every run: no fetch follows the final OUT). So an instruction's decode has a stage that
starts when its opcode leaves the queue, before its boundary: for HALT that stage stops the
prefetch and holds an EU cycle not yet started by one clock. This is the END of every corpus
chain. Confidence: high for the fact, medium for the reading.

## Q15. Leads: three instructions start later than their predecessor's end

`ld-X-{i,c,n}` (X after INC (2 clocks), CBW (3), NOP (4)): for OUT imm8,AL, OUT imm8,AW and IN
AL,imm8 the three traces are identical to the end of the program; for MOV sreg,AW the first of a
train is one clock late and the rest run at the bus's pace (`sr-N`). Reading: the boundary of
these comes no sooner than 3 clocks (the I/O forms with an immediate port) or 2 clocks (MOV
sreg) after the pop of their own opcode; every other form read has 1. PUSH imm, ADD AL,imm,
MOV acc,[d16], MOV [d16],acc, JMP short, MOV r,imm8 do not (their -i and -c traces are equal
only by Q4). With lead 2 MOV sreg,r16 is MOV r,r's two words: 18 / 18. The hardware statement
that fits Q14 and Q15 together: a decode stage runs from the opcode's pop; for most opcodes it
is done in one clock, for MOV sreg in two, for the immediate-port I/O forms in three, and
HALT's acts there. (The corpus prelude's MOV sreg,AW after MOV AW,imm16 and the marker OUT
imm8 are these.) Confidence: high for the leads' existence and sizes on an idle bus; OUT
imm8's interplay with fetches is not finished (below).

## Q16. Memory requests: the cycle four clocks after the third word, with no bus-idle wait

MOV AW,[d16] (A1): `. . Y PP DN .` - the read starts on word 7's clock (or when the bus frees),
both displacement bytes leave on word 4, word 5 waits for the datum and pops the next opcode,
word 6 is the last: 54 / 54 (`lacc-N`, round 2's `ld-N`, `ld-lacc-*`). MOV [d16],AW (A3):
`. . Y PP G . . N`, the last word then waiting for the write's last clock (Q10): 54 / 54. POP
AW `. . Y DN .` 18 / 18; PUSH AW `. . Y . . . N .` (marker 30 / 30, `bp` 120 / 120, trains
15 / 18). Unlike OUT DW's request word these do **not** wait for a running fetch (with the
wait: 9 / 18 and worse). So "four clocks from the request word to the cycle" is common to I/O
and memory; the bus-idle wait is the I/O form's. Confidence: high for A1 / A3 / POP.

## Not read yet

| tests | state |
|---|---|
| OUT imm8 (`e6*` 47 / 54, `mm` 25 / 54, `o6*` 70 / 144, `bo` 105 / 120) | shape `. . B P . X . . N .` + lead 3; misses when its boundary falls on the last clock of a back-to-back fetch that its own pop started, and after MOV r16,imm16 at pE. A second agent is on it (model_e6.py) |
| PUSH imm16, POP PSW (`pi`, `pp`, `pre`) | PUSH imm: both bytes on word 5, the write 11 clocks from the start; a fetch at five held is *not* made while its request stands at w0 but is at w1 / w2: not yet a rule. POP PSW: the read at word 7, about 14 clocks long |
| ModR/M memory forms (`lbw ld8 ld16 lbi ldir sbw sd8 sdir rmw`) | [BW]: ModR/M on word 1, the request on word 2 (read 6 clocks from the start): single instructions fit, trains do not (8 / 18) |
| PUSH trains, PUSH / POP pairs at w2 (7 runs) | the request word one clock late when it falls on the third clock of a five-clock fetch |
| CALL / RET near (`cr`), JMP far (`jfar`), JMP near (`jn`), Jcc taken (20 / 24) | JMP far: immediate words popped on words 5 and 9, target fetch 3 clocks after a flush word at 14 (not 5: the short jump's 5 is then "bus-idle word, two more words, flush, 3 clocks") |
| SHL r,imm8, MULU, `em2-*` (which ModR/M forms wait for three bytes: 26 / 54) | not looked at |

## The next tests

1. PUSH imm / POP PSW with the queue level stepped (INC x j before) so the request word falls
   on each clock of a fetch: when is a five-held fetch made with a request standing.
2. JMP short with a fetch between its bus-idle word and the flush (a pop placed there), to
   split "5 clocks" into "2 words + 3 clocks" as JMP far suggests.
3. The ModR/M memory forms in pairs with an INC between (trains differ from singles).

## Q17. ModR/M memory forms with a displacement (shape search, rules fixed)

| form | shape | runs |
|---|---|---|
| MOV AW,[BW+d8] (8B 47) | `P . Y P DN .` | 18 / 18 |
| MOV AW,[d16] by ModR/M (8B 06) | `P . Y PP DN .` | 18 / 18 |
| MOV [BW+d8],AW (89 47) | `P . Y P N G . .` | 18 / 18 |
| MOV [d16],AW by ModR/M (89 06) | `P . Y PP N G . .` | 12 / 18 |
| MOV AW,[BW] / [BW+IX] (8B 07 / 8B 00) | `P Y . DN .` (request a word earlier: no displacement) | 8 / 18 each: singles fit, trains do not |
| MOV [BW],AW (89 07) | `P Y . . . G N .` | 10 / 18 |

The displacement forms are the accumulator forms (Q16) with the ModR/M byte on word 1: request
word 3, displacement on word 4, the cycle on word 7. Without a displacement the request is on
word 2. No separate EA-step clock is visible for [BW+d8] against [d16].

# The merged reading (model_m.py): supersedes Q11, Q13, Q16's "no wait" where they differ

Two readings ran in parallel: mine above (model.py, "A") and a second agent's of OUT imm8 and
of what follows an EU cycle (model_e6.py, "B", with a round 6 of 48 programs / 288 runs it
designed, predicted 243 / 288 before acquiring, and acquired: `traces/socket/QPr6-*`). A third
pass merged them, testing each rival rule alone and together on all 2,712 runs
(`build/qp/merge/rivals.out`, `drop.out`, `ABM.txt`):

**`validation/v35s/qprobe/model_m.py`: 2,596 of 2,712 runs, to M1 and to the program's end
alike** (A 2,098 / 2,058 whole, B 2,176). Every group at or above both parents; rounds 1, 3 and
the mixes 100 %; `pre` (the corpus prelude's instructions behind a long shift: PUSH imm, POP
PSW, three MOV AW,imm / MOV sreg,AW, two MOV r16,imm16) **6 / 6 whole traces as a prediction**
(it was not fitted). Its docstring states every rule; what changed against Q10-Q17:

| question | survivor | evidence |
|---|---|---|
| Q10 boundary against an EU cycle | as Q10 (A and B had the same rule), plus: the boundary also waits while a *memory* cycle is posted and not started (`E_PEND`) | off: 2,146; with E_PEND off 2,500 |
| Q11 how OUT DW ends | **not** "last word waits for the grant": the I/O cycle starts no sooner than the clock after the routine's boundary (`EU_HOLD`), and OUT DW's *first* word waits for the bus unit's slot. Q11's fact (the next instruction starts on the I/O's first clock) stays, as a consequence. Decisive: OUT imm8 followed by an opcode with a lead - the boundary is delayed by the lead and the I/O moves with it (`gb`, `gc`: 16 runs) | G changes no run in any combination; A's shape 2,334 |
| Q13 bus-idle words | **not** "from the fetch's third clock": the bus unit has a sequencing stage (a "slot") two clocks ahead of the pins for an EU cycle and for every fetch chained behind it until the bus idles. I/O request words, OUT DW's first word and SHL r,CL's 4th word wait for the slot; the boundary, the immediate-pop words and the flush wait for the pin cycle. Decisive: `o6i`, `gf-p`, `gf-or` (the shift's 4th word runs in the third clock of a fetch behind an EU cycle) | slot alone 2,596, third-clock alone 2,503, no lag 2,362 |
| Q16 memory request word | neither "no wait" (2,521) nor "by the slot" (2,446): it is taken only in a running fetch's **last two clocks** (2,596). This is the PUSH-train misses at w2 and the PUSH imm case | `Y_LEFT=2` |
| Q8 five-held continuation | also not made when an EU request word executed on the fetch's last clock (`REQ_PRI`: PUSH imm at w0) | 9 runs |
| Q9 | any boundary needs two bytes behind the staged opcode (three for ModR/M) | `EMIN=2`, 3 runs |
| Q14, Q15 | as read (HALT at its pop; leads 3 / 2), plus: a boundary released by its lead on the very clock a back-to-back fetch would start executes, and the fetch starts a clock later | `LEAD_EPRI`, 8 runs |

New shapes read by the merge (18 / 18 whole traces each unless noted): OUT imm8 / OUT imm8,AW
`. . . BP . . X . N .`, IN imm8 `. . . BP . . X DN .`, OUT DW `A . X . N .`, PUSH imm16
`. . . . PP . Y N`, POP PSW `. . Y D . N .`, MOV r,[BW] / [BW+IX] `P Y . DN .`, [BW+d8]
`P Y . P DN .`, [d16] `P Y . PP DN .`, MOV [BW],r `P Y . N`, [BW+d8] `P Y . P N`, MOV
[d16],AW `. . Y PP N`, MOV [d16],r by ModR/M 12 / 18.

Still unreproduced (116 runs): SHL r,imm8 (30), MULU (18), JMP near at pE (12: one more
old-stream fetch is made before the target), taken Jcc at pE w2 (6), JMP far at pE (9), CALL /
RET (6), ADD [BW],AW (12), MOV [d16],r trains at pO (6), TEST / TEST1 / INC r8 after MOV
r16,imm16 (16), `ge-rrn-pE-w0` (1).

Thin rules (kept only because a group needs them; each wants its own test): OUT DW's first-word
exception `LAG_FIRST` (one program, 3 runs), `EMIN` (3), `HALT_STOP` (3), `LEAD_EPRI` (8, w0
only), `REQ_PRI` (9), `CHAIN_POP` (10), `EU_HOLD` (16).
