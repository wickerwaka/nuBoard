# qprobe: what the socketed chip does (three rounds, 1,428 programs x settings, each run twice)

Receipts: `traces/socket/QPr{1,2,3}-w{0,1,2}.json` (every run with its repeat; 1,428 runs, 1,428
repeats, 0 differing, 0 failed). Acquisition logs: `traces/qp-r{1,2,3}-socket.log`. Tools:
`validation/v35s/qprobe/` (gen.py the programs, run.py, read.py the strips, model.py the reading
as a 200-line clocked model, search.py the routine-shape search). Clocks below are CPU clocks
from M0's I/O cycle; a fetch is written `clock:+offset` (the word's address minus the body's
first byte); w = memory waits (a fetch is 3 + w clocks); pE / pO = the body's first byte at an
even / odd address.

**The test of the reading.** One set of rules (below, `model.py`) reproduces *every bus event
from the end of the long shift to the marker* on

- all 330 round-1 runs (the runs the rules were read from);
- the 96 round-2 random mixes of NOP / INC / MOV r,r / MOV r16,imm16 (read from 3 of them: two
  rules were corrected by these, see Q8 and Q9);
- **all 378 round-3 runs, none of which was used to form a rule**: 144 random mixes of ten
  instruction kinds, 60 + 120 single-variable tests of the two corner rules, 54 short shifts;
- the round-2 trains of MOV r8,imm8, ADD r,r, XCH AW,r, CLC, CBW, ADD AW,imm16, ADD r,imm8,
  MOV r8,r8, a segment prefix, SHL r,1, JNZ not taken, and PUSH AW as the marker (each: the
  routine's shape searched, the rules fixed).

1,214 of the 1,428 runs in all. The 214 not reproduced are instructions whose routine is not
read yet (OUT imm8, SHL r,imm8, MULU, JMP near, Jcc taken 20 / 24, memory loads / stores, PUSH
trains, two markers), listed at the end.

## Q1. How many bytes are held before fetching stops (`base`, `sp-*`)

| program | SHL at | last word fetched before the idle gap | bytes held beyond the SHL |
|---|---|---|---|
| base pE (all w) | even address | +4 (bytes +4, +5) | **6** |
| base pO (all w) | odd address | +5 (bytes +5, +6) | **7** |
| sp-j: a second SHL after j NOPs, SHL at an even address | | | 6 during it, a 7th-and-8th byte's word fetched 3 clocks before M1 |
| sp-j, SHL at an odd address | | | **5** during it; one word fetched 9 clocks before M1 (then 7) |

Reading: at most seven bytes are ever held beyond the running instruction (six bytes and one
more place). The count alone does not say when fetching restarts: with five held at an odd
SHL nothing is fetched for 70 clocks. Confidence: high (48 runs, both alignments, three waits).

## Q2. When fetching restarts (`sp-*`, `rsp-*`, `nop-*`, `inc-*`)

A fetch starts from an idle bus when the bytes held fall to **four** (three free of seven), on
the clock of the pop that makes it so. Evidence, w0:

| program | pops after the fill | first fetch |
|---|---|---|
| NOP train, pE (6 held) | the 2nd opcode leaves at 80 | 80 |
| NOP train, pO (7 held) | 2nd at 80, 3rd at 84 | 84 |
| INC train, pO | 2nd at 80, 3rd at 82 | 82 |
| MOV r,r train, pO | ModR/M and the 2nd opcode at 80 | 80 |
| SHL, pO (`sp-0`) | ModR/M at 80: five left | none until the SHL's last-but-one clock (152), when the next opcode leaves |

Right after a bus cycle the threshold is **five** (a fetch continues back to back, or follows an
I/O cycle, with five held: the word's second byte takes the seventh place), unless an
instruction boundary falls on that very clock (Q8). Confidence: high for 4 / 5; the after-I/O
case rests on the base programs' fetch after M1 only (medium).

## Q3. Which pop: the next opcode leaves the queue on a word of the *running* routine (NXT)

The fetch clocks only fit if the next instruction's opcode is taken from the queue by a
particular word of the running routine, not at the boundary and not "as soon as the staging
register is empty":

| routine | words (one a clock) | the word that takes the next opcode (N) |
|---|---|---|
| NOP, XCH AW,r16 | 4 | 1st |
| CBW | 3 | 1st |
| INC r16, CLC, MOV r,r, ADD r,r, prefix | 2 | 1st |
| MOV r8,imm8 | 5 | 4th (with the immediate byte) |
| MOV r16,imm16, ADD AW,imm16 | 6 | 5th (with both immediate bytes: three bytes leave on one clock) |
| ADD r16,imm8 | 5 | 4th (with the immediate; the ModR/M byte on the 1st) |
| OUT DW,AL | 8 (7 not excluded) | 5th; the I/O cycle starts on the 7th |
| SHL r,CL | 12 + 2n | the last but one; ModR/M on the 1st |
| SHL r,1 | 9 | 8th |
| JNZ not taken | 8 | 7th; the displacement on the 4th |
| JMP short | 9 | displacement on the 4th, the flush on the 7th, the target's opcode on the 8th |

So NOP is "take the next opcode, then three more clocks", INC "take it, then one". The long
shift holds only its own successor's opcode at its very end: that is why five bytes sit unfetched
during an odd-aligned SHL (Q1). Confidence: high for the N positions (each fixes the fetch
clocks of a whole train at three waits and two alignments); the number of words *after* N in the
immediate forms and OUT is not separable from the boundary wait of Q4 (stated where so).

## Q4. The EU's pace against the fetches: the instruction boundary waits for a running fetch

The measured pace of no-bus instructions from a *full* queue:

| train | w0 | w1 | w2 | bus pattern |
|---|---|---|---|---|
| NOP x N (1 byte) | 4.0 / instr | 4.0 | 4.5 | one fetch per 8 clocks; pairs per 16; pairs per 18 |
| INC x N (1 byte, 2 clocks) | 2.5 | 3.0 | 3.5 | two fetches back to back, then 4 idle: 10 / 12 / 14 per four INCs |
| MOV r,r x N (2 bytes, 2 clocks) | 3 | 4 | 5 | fetches back to back, **one instruction per bus cycle from the first one**, with six bytes in the queue |
| MOV r16,imm16 x N (3 bytes) | 7 | 8 | 9.5 | three fetches, then 4 idle: 14 / 16 / 19 per two (the corpus prelude's unexplained train) |

One rule gives all four at every wait, the transients included: **an instruction boundary (the
last word of a routine, when the staged opcode becomes the running instruction) cannot happen
while a fetch cycle is in flight, except on that cycle's last clock.** With the pop of Q2
starting a fetch on the same clock, an instruction that pops across the threshold is stretched
to the end of the fetch it caused: MOV r,r (every instruction pops two bytes) becomes exactly
one bus cycle; a pair of INCs is 2 + one cycle; a pair of NOPs is 4 + max(4, one cycle);
two MOV r16,imm16 are three cycles + 4 or 5. The EU does not wait for *bytes* (the queue holds
four to six throughout); it waits for the bus unit to finish its cycle. In hardware terms: the
boundary uses something the fetch cycle holds until its last clock (the candidates: the address
unit that forms PC / PFP, or the internal bus the fetched word arrives on). This replaces the
frozen model's "the start waits for the words its own pops asked for" and E1 / E2's rejected
stalls (those were tested on a queue whose pops were in the wrong place, Q3). Confidence: high.

## Q5. Words that wait for the bus to be idle (B), and the EU's own cycle

- OUT DW,AL: the I/O cycle starts 4 clocks after the routine's 3rd word; that word waits while
  a fetch is in flight (its last clock included), and a fetch that starts in the 4 clocks after
  it delays the I/O cycle to its own end. Seen as "M1 = last fetch's end + 4" whenever M1
  follows a fetch burst (MOV r,r trains at pE, after a jump), "+6" when the boundary itself
  waited (pO), and M1 = start + 7 on an idle bus. PUSH AW as the marker and POP AW have the same
  3rd-word shape (the cycle 4 clocks later).
- The immediate forms' pop word (MOV r,imm8 / imm16, ADD AW,imm16, ADD r,imm8) and JNZ's 7th
  word wait the same way; so does **the 4th word of SHL r,CL**: SHL r,CL is 12 + 2n on an idle
  bus and 12 + 2n + (w) when a fetch runs across its 4th clock (the corpus's "C: 74 / 75 / 76").
- A jump's flush word waits the same way; the target's fetch starts 5 clocks after it (and the
  bytes of the old stream are not fetched in between).

Reading: one resource ("the bus unit's address path is busy while a fetch cycle runs") is asked
for by the boundary (free from the cycle's last clock) and by these words (free from the clock
after). The 4-clock distance from the request word to the EU's cycle is the same for the I/O
write, the stack write and the stack read. Confidence: high for OUT DW and the immediate forms
(the mixes), medium for the reading as one resource. Open: a B word against a fetch that
*follows an EU cycle* (base pO after M1: MOV CL,imm8's pop word seems not to wait for the fetch
that starts right after the I/O cycle; the measured region ends at M1, so this is one case).

## Q6. The empty queue: a jump (`j0-*`, `j1-*`, `jf*-*`)

| | even target | odd target |
|---|---|---|
| first fetch | a word | the target's byte alone (the word's address, one byte kept), then words |
| fetches before the first instruction starts | 3 (it starts on the 3rd's last clock) | 4 |
| bytes delivered when it starts | 4 (the opcode and 3) | 5 |

The first instruction after a flush starts only when **four bytes of the new stream have been
delivered** (two full words after an even target, the byte and two words after an odd one), and
then on a fetch's last clock (Q4). It is not "as soon as the opcode arrives": the opcode is in
the queue 7 (w0) to 12 (w2) clocks earlier. Ten different first instructions (round 3,
`jf0-*`, `jf1-*`: 120 runs predicted) behave the same. After that the instructions run at the
bus's pace (Q4) until the queue has filled. The JMP short itself: displacement popped on its
4th word, the flush on its 7th (waiting for a running fetch to end), the target's fetch 5
clocks later (12 clocks from the JMP's start on an idle bus). Confidence: high.

## Q7. Alignment

Alignment changes nothing by itself. Every pE / pO difference in the three rounds is the one
byte more or less in the queue at the start (6 or 7 held), which moves the pop that crosses the
threshold of Q2 by one pop. The apparent rule "M1 is 4 clocks after the last fetch when OUT is
at an even address, 6 when odd" is that: at pE one more fetch is owed, so the OUT's request word
waits for it (Q5); at pO the boundary waited instead (Q4).

## Q8. Back to back at five held: the boundary has priority (read from the mixes)

On the clock after a fetch's last clock, with five held: a fetch starts **unless an instruction
boundary executes on that clock**; with four or fewer held the fetch starts and the boundary
waits (Q4). Read from `mix-4` (five held, a boundary on that clock: no fetch) against the NOP /
INC trains (five held, the boundary on the clock before: fetch) and the MOV r8,imm8 trains (five
held, no boundary near: fetch). Three statements of the rule were tried (`B2B_MODE` plain /
elast / enow in model.py); only this one fits rounds 1-3. Confidence: medium-high (it then
predicted round 3's 144 mixes).

## Q9. A ModR/M instruction's boundary needs three bytes behind its opcode

The boundary of an instruction with a ModR/M byte waits while fewer than three bytes are in the
queue behind the staged opcode. Read from three mixes where MOV r,r followed MOV r16,imm16 at pE
(the triple pop leaves two); round 3's `em-*` opened it one variable at a time (after the same
triple pop: MOV r,r, ADD r,r, MOV r8,r8 wait one fetch; INC, NOP, MOV r,imm, ADD AW,imm, CBW,
OUT do not): 60 runs predicted. The first instruction after a flush (Q6) is the same number
(the opcode and three bytes) for every opcode. Why three (the ModR/M byte and two more) is not
understood: it is the size of the longest thing a ModR/M byte can announce (a displacement
word), so "the decoder waits for the bytes a memory form could need before it knows the form"
is the candidate. Confidence: medium (one count, consistent on 180 runs).

## What the trains say about wait states (the brief's question)

With the queue full the EU's pace on no-bus instructions depends on w exactly through Q4: only
when an instruction's pop starts a fetch that is still running at its boundary. NOP at w0 / w1
never meets it (4 clocks); at w2 each fetch costs one clock. With the queue empty (after a
jump) the pace is the bus's. There is no stall "for a byte" in any of the 1,214 reproduced
runs except the first instruction after a flush.

## Not read yet (the 214 runs)

| tests | what is seen | what is missing |
|---|---|---|
| `e6n` `e6r` `e6i` `mm` (OUT imm8, 108 runs) | port byte popped 7 clocks after the opcode's own pop whatever the previous routine's tail (NOP's 3 or SHL's 1); the next opcode 12 after; the I/O 4 clocks after a word that waits for a running fetch | the routine seems timed from its opcode's pop, not from the boundary: no shape fits (best 40 / 54). It is the corpus's marker and M0 here |
| `shli` (30), `mul` (12) | - | loop routines; SHL r,imm8's best shape 0 / 30 |
| `jn` (JMP near, 24), `jz` (Jcc taken, 20 / 24 reproduced) | as JMP short with other word positions | 4 runs of jz, the near form's shape |
| `ld` `st` `push` `pop` (72; pop 18 / 18, push 1 / 18, ld 12 / 18 best, st 6 / 18 best) | request on the 3rd word, cycle 4 clocks later, as OUT | the wait for a write's end; whether a fetch follows an EU cycle at five held (base after M1 says yes for I/O) |
| after M1 (every run) | reproduced to the last event in most runs but the final OUT DW,AW (1 clock later than the model: it follows MOV DW,imm16) and LS2 at pO (3 clocks) | Q5's open case; a register written by the previous instruction and read by the next |

## The next tests

1. OUT imm8: after each tail length (SHL, INC, CBW, NOP) x queue level (pE / pO, one and two
   bytes more by a preceding INC) x the next instruction's N position, each with a slow shift
   behind it so every pop's fetch is alone on the bus.
2. B words after an EU cycle: [OUT DW or PUSH] [MOV r,imm8 | MOV r,imm16 | SHL r,CL] with 0-3
   INCs between, pE / pO, three waits: is the wait for "a fetch in flight" or for something the
   fetch after an EU cycle does not hold.
3. Register forwarding: MOV DW,imm16 ; OUT DW,AL against MOV BW,imm16 ; OUT DW,AL.
4. Memory operands, one variable at a time: MOV AW,[disp16] / [BW] / [BW+d8] / [BW+IX], the
   store forms, PUSH / POP trains, each after a slow shift and in pairs (the EA step's clocks,
   the request word, the datum's wait, the write's end).
5. Taken Jcc, JMP near, CALL / RET against the JMP short rule (the flush word, the 5 clocks,
   four bytes delivered).
6. The corpus prelude itself (PUSH imm, POP PSW, MOV sreg,AW) as qprobe programs behind a long
   shift, so that the first event of every corpus run is explained from a known state.

## Round 4 (414 runs acquired for the next tests; two things read from it)

- **No register forwarding stall** (`fw-*`): MOV DW,imm16 ; OUT DW,AL and MOV BW,imm16 ; OUT
  DW,AL give identical traces at every wait and alignment, and so do INC DW ; DEC DW and INC BW ;
  DEC BW before the OUT. The one-clock difference at the corpus END's OUT DW,AW (after M1) is
  not a register written by the previous instruction; the word-wide OUT is the remaining
  candidate.
- **OUT imm8 hides its predecessor's tail** (`o6s-i`, `o6s-c`, `o6s-n`): INC (2 clocks), CBW (3)
  and NOP (4) before OUT 22h,AL give *identical* traces to the end of the program. The OUT
  imm8's first clocks run under the predecessor's last ones: its port byte leaves the queue 7
  clocks after its own opcode did, whatever is running. So an instruction has a part timed
  from the pop of its opcode (for OUT imm8 at least three clocks long, for the others read so
  far one clock) and a part that waits for the previous routine's end. A model with "OUT
  imm8's boundary no sooner than 3 clocks after its opcode's pop" reproduces 53 of 102 runs
  (`LEAD_E6` in model.py): the rest need the after-EU-cycle rules (Q5's open case) first.
- `bp-*` / `bo-*` (a bus-idle word after a PUSH / an OUT imm8): acquired, not read (the model
  reproduces 45 of 120 `bp` runs).
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

# Round 8 (912 runs; rounds 1-8: the model reproduces 3,291 of 3,624)

Receipts: `traces/socket/QPr8-w{0,1,2}.json`, `traces/qp-r8-socket.log`, `qp-r8b-socket.log`.
912 first runs, 908 repeats (the 4 missing are `fl-iret` at w2, below). 51 repeats are flagged
DIFFERS: all the `strobe` sample artefact (7 against 8 on one fetch) except `fl-iret`'s.
Model: `model_m.py` (one model). Score per round: r1 330 / 330, r2 674 / 720, r3 378 / 378,
r4 414 / 414, r5 514 / 540, r6 287 / 288, r7 42 / 42, r8 652 / 912; rounds 1-7 2,639 (was
2,596; nothing lost).

**Two incidents, both reported, neither a board fault.**
1. `fl-iret` (PUSH 0002h ; PUSH PS ; PUSH IP ; RETI) **runs away on silicon** (trap frames
   pushed into unmapped memory until the 2,048-record limit, FAIL) and passes in simulation.
   A function difference between the RTL and the chip, found by accident: the likely reading is
   that RETI restores the PSW's register-bank bits and the prelude's POP PSW does not, so the
   program lands in bank 0 with other registers. It ran 12 + 8 times before I removed it from
   the generator (the note is in gen_r8.py). Not understood further; do not re-run it.
2. My first acquisition was cut by its own `timeout` (the runaway runs made it slow), which
   kills the runner without its power-off: the next start found the board in a state it
   refuses ("NuBoardError: state"). A read-only state query then showed VCCB off, no failure,
   the right image; I ran the remaining repeats without a kill timer and the board ended
   powered down (vccb false). No program other than `fl-iret` misbehaved. Lesson for the
   harness: never wrap an acquisition in `timeout`.

## Q18. The EA modes measured directly: the measured heads hold, with one exception

MOV AW,[ea] for [BW+IY], [BP+IX], [BP+IY], [IX], [IY], [BW+IX+d8], [BP+IX+d8], [IX+d8],
[BP+d8], [BP+d16] and two stores ([BW+IX], [BP+d8]): **predicted by the forms already read**
(ModR/M on word 1, request on word 2, displacement on word 4), 148 of 156 before any change.
Two registers, a BP base (SS), an index alone: no extra clock. The exception: **base + index
+ 16-bit displacement ([BW+IX+d16]) is one word longer** (`P . Y . PP DN .`: request on word
3, displacement on word 5): 156 / 156 with it. The one EA-adder clock the pins show is the
three-term sum with a carry-propagating 16-bit displacement. Confidence: high (the corpus's
`ld_bw_ix_d16` / `st_bw_ix_d16` runs miss by exactly this clock).

## Q19. A routine's second bus cycle: two clocks after the first one's datum word

ADD [BW],AW: `P Y . . DZ N` - the read as a load (cycle 6 clocks from the start), and the write
**2 clocks after the word that waits for the read's datum** (Z; 4 for a first request), the
boundary then waiting for the write (Q10). 24 / 24, and round 5's `rmw` 12 / 12. ADD
[BW+d8],AW `P Y . P DZ N` 12 / 12. ADD AW,[BW] and CMP AW,[BW] are the plain load `P Y . DN .`
(12 / 12 each). Reading: the address is already in the bus unit, so the second request skips
the two clocks a first one spends handing it over (the "slot" lead of the merged reading).
Confidence: high for the 2; the reading is a guess.

## Q20. Group opcodes have a bus-idle fourth word; and they do not wait for three bytes

| form | shape | runs |
|---|---|---|
| INC r8 (FE /0, register) | `P . . BN .` | 18 / 18 |
| NOT r16 (F7 /2, register) | `P . . BN .` | 18 / 18 |
| LDEA r,[BW] (8D) | `P . . BN .` | 18 / 18 |
| TEST r,r (84) | `P . BN .` | 18 / 18 |
| INC word [BW] (FF /0) | `P . . B Y . . DZ N` | 12 / 12 |
| MOV word [BW],imm16 (C7 /0) | `P . . BY . . . PPN .` | 12 / 12 |
| CMP r,r (3B), XCH r,r (86), prefix + MOV r,r | `PN .` (as MOV r,r) | 18 / 18 each |

With SHL r,CL (4th word) and SHL r,1 (3rd) from rounds 1-2: every form whose operation is
selected by the ModR/M reg field (FE / FF / F6 / F7 / C7 / D0-D3), and LDEA and TEST, has a
word 3 or 4 clocks in that waits for a running fetch, and takes the next opcode there or
later. That is where the 0F-page forms should be looked for too (TEST1 / ROL4: not read).

**Q9 opened.** After MOV r16,imm16 at pE (two bytes held): TEST r,r, CMP r,r, XCH r,r and
prefix + MOV r,r wait for the third byte as MOV r,r does (predicted, 24 / 24); **INC r8 and NOT
r do not** (18 / 18 with the rule off for FE / F7, 9 / 18 with it on); the shift group does
(3 runs of round 5 lost with it off). So "three bytes behind a ModR/M opcode" is not a
property of the ModR/M byte: it holds for the opcodes whose ModR/M byte is used by the first
word (register selects), and not for FE / F7, whose first three words do not touch it. The
mechanism candidate that fits: the boundary of such an opcode needs its ModR/M byte *and the
two bytes a displacement could be* present, because the first word forms the EA before the
mode is known; FE / F7 form theirs on the bus-idle word. A guess; the shift group contradicts
the simplest form of it (it has the late word and still waits).

## Q21. One flush tail for every transfer

| form | last input | flush word | target's fetch |
|---|---|---|---|
| JMP short | displacement popped, word 4 | word 7 | 5 clocks later |
| JMP near (E9) | displacement word popped, word 5 | word 8 | 5 later |
| JMP far (EA) | segment word popped, word 9 | word 12 | 5 later |
| CALL near | the write's end | 3 clocks after it | 5 later |
| CALL far | the second write's end | 3 after | 5 later |
| RET, RETF | the (second) read's end | 3 after | 5 later |
| INT 3 | the third stack write's end | 3 after (target 11 clocks from that write's start at w0) | - |

**The target's fetch starts 8 clocks after the routine's last input** - the last operand byte
popped or the last stack cycle's end - at every wait, as a bus-idle flush word 3 clocks after
the input and the fetch 5 clocks after that word. The earlier "JMP far 3, short 5" was two
placements of the same 8. So the distance is not the PS load and not the opcode: it is one
tail. Shapes (all reproduce): JN `. . . . PP . . F N .` (r2 `jn` 24 / 24, `fl-jn` 24 / 24);
CALL `. . . . PP . Y D . . F N .`, RET `. . Y D . . F N .` (`fl-call`, `fl-ret` 24 / 24, `cr`
6 / 6); RETF `. . Y D . Y D . . F N .` (12 / 12: the second read's request 2 clocks after the
first datum word, as Q19); CALL far `. . . . PP . Q . PP . Y D . Y D . . F N .` (8 / 12); JMP
far 12 / 18. Two additions read here:
- a back-to-back fetch of the old stream that starts on the flush word's own clock is still
  made and thrown away, and the target's fetch then starts 3 clocks after its end (JMP near at
  pE: 12 runs);
- in the far forms the word two after the first immediate pop counts as a request for Q8's
  rule (no five-held continuation behind it at w0): the offset handed to the bus unit.
Not reproduced: the far forms at pE w1 / w2 (2 clocks later than the model: 10 runs), a taken
Jcc at w2 pE (4) and to an odd target (2), LOOP taken (6 / 12; flush word at 14), JCXZ not
taken (6 / 12), JMP r16 (0 / 12), INT 3 (0 / 12; its bus sequence is: vector IP read, stack
write, vector PS read, two stack writes, the target 11 clocks after the last write's start).

## Q22. Leads: INT 3 has one; nothing else new does

`ld-X-{i,c,n}` at pO (CBW and NOP against INC: 1,2 = no lead; 0,0 = the predecessor's tail
hidden): **INT 3: 0,0 at every wait** (a lead of three or more, with OUT / IN imm8). No lead:
IN AL,DW, LDEA, MOV r16,sreg, MOVBK, PUSH PSW, PUSH r16, PUSH sreg, XLAT, TEST1, POP r16, RET
(the last two reproduced by the model without one: 18 / 18, 16 / 18). POP sreg looked like a
lead of 2 and is not: it is POP r16 with one more word (`. . Y DN . .`, 18 / 18), PUSH sreg is
PUSH r16 one word later (`. . . Y . . . N .`, 18 / 18). So the leads are: OUT imm8, OUT
imm8,AW, IN imm8, INT 3 (3); MOV sreg,r16 (2). What these share: the opcode's second byte or
an implied vector is needed *by the bus unit as an address* (a port, a vector) before the
routine can ask for it, or (MOV sreg) the segment the next fetch address is formed from may
change. The decode stage that runs from the pop is then "form what the bus unit needs first".
A guess that fits five forms; IN AL,DW (port in DW: no lead) fits it too.

## Not read in round 8 (the data is acquired)

ADD [BW],imm8 (`rw-addi`: read 7 clocks from the start, the write 2 after the datum, the
immediate between; no shape found), SHL r,imm8 (`si-*`), the string forms and REP (`st-*`),
TEST1 / ROL4 (`t-test1`, `t-rol4`, `em3-*` of them), JMP r16, INT 3's routine, LOOP / JCXZ in
half their runs.

## Interrupt recognition (item 4): not attempted

No probe was built. What a probe would need: the harness's event port (OUT FF12h) to start a
scheduled INT / NMI edge a programmable number of ticks later, an enabled interrupt with a
handler that makes a marker, and a body of one long instruction (the slow shift) and of a
train of two-clock instructions; stepping the delay by one clock then shows on which clock of
a routine the line must be up for the boundary to take it. It is a schedule-driven test
(`foo.stim.json`), outside this package's frame; left for a round of its own.

# Round 9 (330 programs, 1,980 runs; rounds 1-9: the model reproduces 3,963 of 5,604)

Receipts: `traces/socket/QPr9-w{0,1,2}.json`, `traces/qp-r9-socket.log`. Every new routine was
acquired four ways: `X-a` behind the long shift (its start known), `X-s` followed by a long
shift (its tail on an idle bus), `X-2` against itself, `X-n` behind a NOP and before a long
shift. A routine is called **read** below only when all four reproduce at three waits and both
alignments (24 runs); otherwise the count is given and it is not read.

Model score per round (`model_m.py`): r1 330 / 330, r2 704 / 720, r3 378 / 378, r4 414 / 414,
r5 517 / 540, r6 287 / 288, r7 42 / 42, r8 707 / 912 (rounds 1-8: 3,379, was 3,291; nothing
lost), r9 584 / 1,980.

## Q23. The 40 lost runs: it is the follower's start, and one fact about the write's routine

`c40-*` (OUT imm8 ; X ; follower, X = ADD [BW],AW, MOV [BW],AW and the d8 forms; 168 runs).
On silicon the fetch after the write is **the same for the read-modify-write and for the plain
store** in every frame; it moves with the follower: before OUT imm8 or OUT DW at pE it comes
4 clocks after the write's end, at pO 0-1, before a NOP or a long shift 0. So the RMW's tail is
not longer than a store's. The RTL agrees with silicon on every `c40` run whose follower is
OUT DW, NOP or a long shift (96 / 96) and misses 32 of the 72 whose follower is OUT imm8 - for
the store exactly as for the RMW, at W = 0 (the corpus says the same: st_bw misses 123 of its
437 runs before the OUT imm8 marker at W = 0; the "40 lost" joined them when ADD [BW],AW's
routine became right elsewhere).

The mechanism: **a routine that ends in a memory write takes the next opcode from the queue on
the write cycle's first clock** (not on its last word, not at a fixed word: it follows the
cycle when a fetch delays it). The follower's boundary is then the later of "the write's last
clock" (Q10) and "its own lead after that pop" (Q15): for OUT imm8 (lead 3) behind a 3-clock
write that is one clock after the write's end, at W = 1 / 2 the write is long enough to hide
it. With it `c40` is 168 / 168, nothing lost elsewhere, and the same placement holds for every
store and RMW form read (it is in all their shapes: `... G N .`, G = the word completes on the
clock before the cycle starts). Confidence: high.

## Q24. One pattern for the late bus-idle word: three words after the routine's last queue byte

| form | last operand byte | bus-idle word | read? |
|---|---|---|---|
| SHL r,CL (round 1) | ModR/M, word 1 | word 4 | yes |
| SHL / SAR r,imm8, byte and word (C0 / C1) | the count, word 4 | word 7; the routine is the CL form's 12 + 2n | 201 / 210 |
| TEST1 / SET1 / NOT1 r,CL (0F 10 / 14 / 16, byte and word) | ModR/M, word 3 (second opcode byte on word 1) | word 6, with the next opcode; 7 words | 18 / 24 each (CLR1 10 / 24): not read |
| every flush (Q21) | last displacement / segment byte, or the last stack cycle's end | the flush word, 3 later | yes |
| INC / NOT r, LDEA, TEST r,r, INC mem, MOV mem,imm (Q20) | ModR/M, word 1 | word 3 or 4 | yes |

So the "group forms have a bus-idle word" of Q20 and the flush word of Q21 look like one thing:
a routine's commit point comes three words after the last byte it takes from the queue and
needs the bus unit idle. A pattern over five families, not yet a rule the model applies by
itself (each shape still carries its own B).

## Q25. Memory forms read in round 9 (all four ways, 24 / 24 each)

| form | shape | note |
|---|---|---|
| XCH [BW],AW (87) | `P Y . . D . Z G N .` | the write 4 clocks after the read's end (ADD [BW],r: 2) |
| TEST [BW],AW (85) | `P . B Y DN .` | TEST r,r's bus-idle third word, then a load |
| DEC word [BW] (FF /1), NOT word [BW] (F7 /2), INC byte [BW] (FE /0) | `P . . B Y . . DZ G N .` | **predicted** from INC word [BW] (round 8): the group's memory forms are one routine |
| MOV word [BW+IX],imm16 (C7 /0) | `P . . BY . . . PPN .` | **predicted** from [BW] |

Partly reproduced, not read: MOV [BW+d8],imm16 `P . . BYP . . . PPN .` 21 / 24 (the pair
misses); MOV [BW+d16] / [d16],imm16 11 / 24; MOV byte [BW],imm8 9 / 24 (its request is a word
earlier than the word form's and its third word does not wait at pE). The three-bytes rule
holds for C7 (off: the pairs break). Not looked at this round though acquired: ADD / CMP / TEST
mem,imm, PUSH / POP mem, SHL mem,1, PUSHA / POPA, PREPARE, the string forms and REP, EXT / INS /
ROL4 / ROR4, the 0F bit forms on memory and with imm, MULU / MUL / DIV (operand-dependent).
First observations for the next reading (W = 0, pO, clocks from the routine's start): ADD
[BW],imm8 read at 7, write 2 after the datum; ADD [BW],imm16 read at 8; TEST [BW],imm16 read at
10; CMP [BW],imm8 read at 7; SHL [BW],1 read at 8, write 8 after the read's end; PUSH [BW] read
at 8, the stack write 6 after its end; MOV byte [BW],imm8 write at 7; SHL r,imm8 = 12 + 2n.

## Interrupt recognition: not reached

Items 1-3's first families took the round; no probe was built. The design note of round 8
stands (a schedule-driven test with the event port, stepping the edge by one clock across a
long shift and across a train).

## Board

No incident, no `timeout` wrapper, no program ran away: 1,980 runs and 1,980 repeats, 0 failed,
0 incomplete. 189 repeats are flagged DIFFERS; every one is the strobe-sample artefact (270 fetch records with `strobe` 7 against 8, no other field differing: `build/qp/repdiff.py 9`), a higher rate than in earlier rounds (51 of 908 in round 8). The board ended powered down.

# Round 10 (114 programs, 684 runs; rounds 1-10: the model reproduces 4,979 of 6,288)

Two acquisitions, both with the board's safety sequence unchanged and no kill timer: `r10`
(51 programs, 306 runs + 306 repeats, 0 failed, 29 repeats flagged, all strobe-only) and `r10b`
(63 programs, 378 runs + 378 repeats, 0 failed, 2 flagged, both strobe-only). Board powered down
at the end (vccb false, failure 0). Receipts: `traces/socket/QPr10-w{0,1,2}.json`,
`QPr10b-w{0,1,2}.json`, logs `traces/qp-r10-socket.log`, `traces/qp-r10b-socket.log`.

Model score per round (no run lost in any round against the round-9 hand-back; 332 gained in rounds 1-9):

| round | r1 | r2 | r3 | r4 | r5 | r6 | r7 | r8 | r9 | r10 + r10b |
|---|---|---|---|---|---|---|---|---|---|---|
| round-9 hand-back | 330/330 | 704/720 | 378/378 | 414/414 | 517/540 | 287/288 | 42/42 | 707/912 | 584/1,980 | - |
| now | 330 | 708 | 378 | 414 | 520 | 287 | 42 | 740 | 876 | 684/684 |

Rounds 1-8: 3,419 (was 3,379). The RTL of this worktree (the round-8 build) on the round-10 set:
435 of 684.

## The three neighbour effects (spec 5 item E): one dissolves, one is a corrected condition, one is a routine

### (a) "INC word [BW] behind a stack write": not an effect

Probes `ia-*` (INC word [BW] behind PUSH, a plain store, an accumulator store, PUSH+POP, a load,
OUT imm8, the long shift, each with 0 / 1 NOP between; 84 runs) and `ip-*` (the corpus's own
chain: the PUSH marker behind INC word [BW], behind PUSH + INC, store + INC, INC + NOP, INC + INC,
and behind store / PUSH / XCH mem / ADD mem,r alone; 60 runs). Result: 144 of 144 reproduced by
the model **with no change**, and 138 of 144 by the round-8 RTL (the six are `ip-xchm`, XCH mem,
which the RTL does not have yet).

So there is no rule to find. Looking again at the corpus rows that carried the "inc_m behind the
PUSH marker, 114 of 186" count (table in divergence notes): the plain chain `push-inc_m` is 12 of
12 equal in the corpus as well. The misses are (1) chains that pair inc_m with a memory form
that is itself unread (`F15-k-push-{mulu,push,shl1}-inc_x`, `F16-r-push-{div,divu,mul,mulu,rcl,
rcr,rol,ror,sar,shl1,shlb,shr,test_imm,push}-inc_x`: the positional rule names inc_m because it
is the oldest instruction in the window, the partner is the cause) and (2) the odd-address
operand (`F5-*-inc_m-kN-odd`, a word at an odd address: two byte cycles each way, never measured
here). The cross-tab's "predecessor" label for inc_m was the positional rule's artefact.

### (b) "SHL r,1 behind an I/O cycle": Q13's condition corrected (one rule, no new shape)

Probes `ib-X-P`: X = SHL AW,1 / TEST r,r / INC r8 behind P = OUT imm8, OUT DW, IN imm8, PUSH, a
store, a load, the long shift (126 runs). The model as handed back in round 9: 102. With one
correction, 118; with one shape refinement, 126.

**Q26 (corrects Q13). A bus-idle word waits for the EU's own bus cycle as well as for a
fetch.** Until now the model's bus-idle test looked at fetches only (Q13: from a fetch's second
clock). On silicon the word also waits while an EU cycle is on the pins. It shows only when an
instruction with an early bus-idle word (third word: SHL r,1 and TEST r,r) directly follows a
routine whose cycle runs *after* its end, which is OUT imm8 and OUT DW (Q11) and nothing else
measured: behind IN (datum wait), a load, a store or PUSH (Q10 / Q23 hold the boundary until the
cycle is over or starting) the cycle is past before the third word. Hence "behind an I/O cycle".
INC r8 (bus-idle fourth word) is never caught. In the model: `B_EU`, set for every kind of EU
cycle (I/O, read, write score alike: only the OUT case discriminates). 16 runs gained, none
lost in rounds 1-9. This is the answer to "the I/O cycle, or the fetch that follows any EU cycle
(Q12)": it is the cycle itself; the fetch behind it is already covered.

Shape: SHL r,1 has a second bus-idle word, `P . B . . B . N .` (was `P . B . . . . N .`). Seen
behind PUSH and a store at one and two waits (the fetch that follows the write is still in flight
on the sixth word). 8 runs.

### (c) Jcc / DBNZ behind CMP r,r and MOV CW,imm16: the branch's own routine, in bus terms

Probes `ic-P-B` and `id-P-B`: JZ taken, JNZ not taken, DBNZ taken behind 19 predecessors (none,
1 / 2 / 3 NOPs, CMP r,r, MOV r,r, MOV CW,imm16, MOV r8,imm8, ADD AW,imm16, INC r16, CBW, CLC,
SHL r,1, TEST r,r, PUSH, a store, a load, OUT imm8, DBNZ); `ie-*`: DBNZ not taken (CW = 1) and
BCWZ taken / not taken behind none, NOP, two NOPs, MOV r,r, CMP r,r. 414 runs. Model as handed
back: Jcc most, DBNZ / BCWZ almost none. Now 414 of 414.

The branch's timing depends on the bus state at fixed words of its own routine, not on which
routine precedes it. The predecessor matters only through (i) the fetch it leaves in flight and
(ii) for DBNZ how long ago its opcode was taken (a lead). No rule names a predecessor.

**Q27. Every conditional branch has a bus-idle fourth word.** Jcc pops its displacement on that
word (`. . . BP`), DBNZ and BCWZ wait on it and pop the displacement three words later. Behind a
short predecessor at an even address the opcode's pop starts a fetch on the branch's first
clock; at 1 / 2 waits that fetch is still running on the fourth word and the branch is 1 / 2
clocks later. That is the whole "behind CMP r,r / MOV CW,imm16 / MOV r,r" effect on Jcc (behind
NOPs and the long shift the queue is full and no fetch runs). Possible mechanism, not tested: the
target adder is the bus unit's address incrementer.

Routines (word 0 is the first clock after the boundary):

| branch | routine | notes |
|---|---|---|
| Jcc not taken | `. . . BP . . BN .` | was `. . . P . . BN .` |
| Jcc taken | `. . . BP . . . B . . F N .` | a bus-idle word four after the displacement: 22 runs, 8 of them old misses in rounds 2, 5, 8 |
| DBNZ taken | `. . . B . . P . . B . . F N .` | lead 2 (below); bus-idle three words after the displacement (Q24) |
| DBNZ not taken | `. . . B . . P . BN .` | lead 2 |
| BCWZ taken | `. . . B . . P . . F N .` | flush word three after the displacement (Q21's distance) |
| BCWZ not taken | `. . . B . . PN .` | no lead |

**Q28. DBNZ has a lead of two** (Q15 / Q22's kind: its boundary no sooner than two clocks after
its opcode's pop into the staging latch). It is the only thing that made DBNZ look
predecessor-dependent: behind the long shift, INC r16, CLC, a load, OUT imm8, SHL r,1 and
another DBNZ (next opcode taken one clock before the end) it is one clock later than behind
NOP, CBW, PUSH and a store (taken two or more before), and the one-clock predecessors lose the
extra clock again whenever their boundary had to wait for a fetch. 40 W = 0 runs tabulated
(`build/qp/brtab.py`), every one explained. MOV sreg,r is the other lead-2 opcode.

## Q29. The memory-immediate forms (item 2), read all four ways

| form | routine | score |
|---|---|---|
| ADD [BW],imm8 (83 /0) | `P . V DPZ G N .` | 24 / 24 |
| ADD [BW+d8],imm8 | `P . V P DPZ G N .` | 24 / 24 |
| ADD [d16],imm8 | `P . V PP2 DPZ G N .` | 21 / 24 (X;X at even alignment: a second back-to-back fetch precedes the second read) |
| ADD [BW],imm16 (81 /0) | `P . . BY DPP2Z G N .` | 24 / 24 |
| CMP [BW],imm8 (83 /7) | `P . V DP . BN .` | 24 / 24 |
| TEST [BW],imm16 (F7 /0) | `P . B . . Y DPP2 . BN .` | 24 / 24 |

Three facts, each used by more than one row:

- **V: a request on the routine's third word is honoured from the running fetch's last clock,
  not from its last two** (Y's rule), and it does not stop the back-to-back fetch that was
  already due (the read then follows that fetch with no gap). Both halves are what the slot
  picture of the merged reading predicts for a request that arrives one clock after the slot's
  decision; Y on the second word arrives in time, V on the third does not. In the model `V` is
  Y with those two differences; ADD mem,imm16's request on the fourth word needs the bus idle
  (`BY`), the next step of the same thing.
- **The displacement is popped on the word after the request**, as in the loads and stores
  (Q17 / Q18): the request is made before the address bytes are taken.
- **The immediate is popped on the datum word** (`DP`, `DPP2`), and a form that does not write
  ends with a bus-idle commit word two after it (`BN`).

MOV mem,imm with a displacement and the byte form: not improved. `stid8` 21 / 24, `stid16` and
`stix` 11 / 24, `stib` 9 / 24 as before. What the misses have in common (written down so the
next round starts there): they are the five- and six-byte forms that drain the queue; the write
is due exactly at a fetch's end; at W = 0 the write goes first, at W = 1 / 2 a back-to-back fetch
goes first. A rule in slot terms (the write's slot against the chained fetch's slot) should
cover them and the 3 `addi8x` misses together. Not found this round.

## Q30. PUSH mem and POP mem

| form | routine | score |
|---|---|---|
| PUSH [BW] (FF /6) | `P . B Y D . . . Z G N .` | 24 / 24 |
| PUSH [BW+d8] | `P . . B Y P D . . . Z G N .` | 24 / 24 |
| PUSH [d16] | `P . . B Y P P2 D . . . Z G N .` | 24 / 24 |
| POP [BW] (8F /0) | `P . Y D . . Z G N .` | 24 / 24 |
| POP [BW+d8] | `P . Y DP . . Z G N .` | 19 / 24 |
| POP [d16] | `P . Y DPP2 . . Z G N .` | 8 / 24 |

PUSH mem is the group form (bus-idle word, request, datum) with the stack write requested four
words after the datum and Q23's ending. POP mem requests its stack read on the third word (plain
Y), and the displacement, which the read does not need, is taken at or after the datum: the two
displacement forms are partial.

## Q31. The 0F bit forms on a register

TEST1 / SET1 / NOT1 r,CL (0F 10 / 14 / 16, and the word form 0F 11): `P . P . . CN .`, 88 of 96
(was 72; all of -a, -s, -2; the eight left are NOP;X;SHL at 1 / 2 waits). CLR1 r,CL (0F 12):
`P . P . . CN . .`, 22 of 24 (was 10): the next opcode is taken on the same word and one more
word follows. `C` is a bus-idle word that also waits on the clock a back-to-back fetch starts
(the condition that already holds a boundary, Q8). Applying that to every bus-idle word loses 93
runs, so it stays the property of this one commit word. 8 old misses of TEST1 in rounds 5 and 8
come back with it. The imm8 forms (0F 18 / 1C), ROL4 / ROR4, EXT / INS: not read.

## Q24 tested as a rule the model applies itself: no, but the table is simpler than it was

`build/qp/q24.py` lists every bus-idle word of every routine; `build/qp/q24test.py` scores the
model with the words placed by rule.

- **The first bus-idle word is the routine's fourth word** in 28 of the 36 routines that have
  one: every accumulator / register immediate, OUT imm8 / IN imm8, every branch, the group forms
  on register and memory, LEA, MOV mem,imm16, ADD mem,imm16, PUSH mem with a displacement. It
  is the third word in six (TEST r,r, TEST mem,r, TEST mem,imm16, SHL r,1, PUSH [BW], MOV
  mem8,imm8) and the fifth in two (MOV r16,imm16 and ADD AW,imm16). For a ModR/M routine "fourth
  word" and "three after the last queue byte" are the same statement.
- **A later commit word is three words after the last queue byte before it** in JNZ, DBNZ
  taken, TEST1 / CLR1, SHL r,CL, SHL r,imm8 and the flush words of JMP near, JMP r16 and BCWZ;
  two after it in CMP mem,imm8, TEST mem,imm16 and DBNZ not taken; four in Jcc taken.
- Forcing rule one on the eight exceptions costs 351 runs; forcing rule two on SHL r,1 costs 12.
  The exceptions are measured, not noise.

So: a default (fourth word; three after the last byte) with a short exception list is a fair
description and a smaller microcode table, but the model cannot drop the per-routine position.

## Not read (data acquired)

MOV mem,imm with displacement / byte form (above); POP mem with displacement; ADD [d16],imm8
X;X; SHL [BW],1; PUSHA / POPA; PREPARE; strings and REP (item 3, not reached); the 0F imm8 bit
forms, ROL4 / ROR4, EXT / INS; MULU / MUL / DIV; the odd-address word operand (not acquired:
one small test would settle the `-odd` corpus rows). Interrupt recognition: deferred as told.

# Round 11 (228 programs, 1,368 runs; rounds 1-11: the model reproduces 7,184 of 7,656)

One acquisition (`r11a` 192 runs, `r11b` 420, `r11c` 468, `r11d` 288; each run repeated), safety
sequence unchanged, no kill timer: 1,368 runs + 1,368 repeats, 0 failed, 97 repeats flagged, all
strobe-only (`repdiff.py`). Board powered down at the end (vccb false, failure 0). Receipts:
`traces/socket/QPr11{a,b,c,d}-w{0,1,2}.json`, log `traces/qp-r11-socket.log`. Every program was
run in the RTL simulation first (1,368 of 1,368 reach the end; the divide operands are chosen so
that no divide error can occur).

Model score per round (no run lost in any round; rounds 1-10 gained 839):

| round | r1 | r2 | r3 | r4 | r5 | r6 | r7 | r8 | r9 | r10 | r11 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| round-10 hand-back | 330/330 | 708/720 | 378/378 | 414/414 | 520/540 | 287/288 | 42/42 | 740/912 | 876/1,980 | 684/684 | - |
| now | 330 | 720 | 378 | 414 | 523 | 287 | 42 | 800 | 1,640 | 684 | 1,366/1,368 |

The RTL of this worktree is now the spec-5 build (nine files copied from the main tree; corpus
replay 16,673 of 30,536 exact, the coordinator's number). On the round-11 set it has 319 of
1,368 (odd operands 102 of 192, the write probes 73 of 420, strings and REP 0 of 468, MUL / DIV
144 of 288).

## Q32. A word operand at an odd address: one cycle of twice the length

Probes `ob-*` (BW = 0801h: load, store, ADD mem,r, INC mem; the byte load and store as the
one-cycle control) and `os-*` (SP = 0EFFh: PUSH, POP), each four ways. The word is moved in two
byte cycles, the odd (low) address first, the second starting on the clock after the first
ends; no fetch and no idle clock ever comes between them, at any wait or alignment. Everything
else is unchanged: the request word, the datum wait (it ends with the second byte), Q23's ending
(the next opcode is taken on the first byte cycle's first clock), the read-modify-write's two
pairs. In the model: the EU cycle is 2 x (3 + W) clocks long and nothing else is touched.
192 of 192 (144 word runs + 48 byte controls). This is the whole of the corpus's `-odd` rows.

## Q33. The write that falls due at a fetch's end: the slot decision, with two corrections

Probes `w-*` (420 runs): MOV mem,imm16 with d8 / d16 / direct, the byte form, POP mem with d8 /
direct, behind seven pads (nothing, CLC, two CLC, one / two / three NOPs, a segment prefix on
the instruction itself), followed by M1 or by a long shift. The pads walk the instruction over
every queue phase. Tabulated against the instruction's own boundary b (`build/qp/wtab.py`) the
picture is regular. For MOV [BW+d16],imm16 the request word is b+4 and the write is nominally at
b+8:

| queue at b | W = 0 | W = 1 | W = 2 |
|---|---|---|---|
| a fetch at b+1, chained one at b+4 / 5 / 6 | write b+8 | write at the chained fetch's end + 1 | same |
| full; fetch at b+4 (from the displacement's pop), count then allows another | **write b+8, no fetch at b+7** | **fetch at b+8, write b+12** | **fetch b+9, write b+14** |
| the same, count does not allow another | write b+8 | write b+8 | write b+9 (fetch's end + 1) |

So "write first at W = 0, fetch first at W = 1 / 2" is the second row only, and it is the slot
decision of spec 6 A4 seen from the other side, with two facts added:

1. **The chained fetch is decided two clocks before its pins, from the count on that clock**
   (count + bytes in flight <= 5). Already in the merged reading; here it is what separates rows
   two and three (the immediate's pop two clocks later must not be counted).
2. **A request raised on the decision's eve holds the decision.** At W = 0 the request word
   (b+4) is the clock before the decision (b+5): no chained fetch, the bus stays idle one clock,
   the write starts at b+8. At W = 1 / 2 the decision (b+6, b+7) is later than that and the
   request no longer holds it.
3. **A posted write whose datum has not been taken yet does not compete.** MOV mem,imm takes
   its immediate on its eighth word (b+8). Until then a chained fetch that the count allows goes
   first and the write follows it; this is the W = 1 / 2 column. A store of a register (datum
   there from the start: MOV [d16],AW, 66 runs in rounds 2, 5, 10) is never overtaken; that is
   the control that fixed this statement (the first version, "an old request loses", lost
   exactly those 66 runs).

In the model: `ARB` (facts 2 and 3) and the act `K` on the immediate's word. MOV mem,imm16 d8 /
d16 / direct: 252 of 252 here, and the round-9 probes 23 of 24 each (were 21, 11, 11). No
routine changed.

Two shapes fell out of the same table:

- **MOV mem8,imm8 (C6): `P . V . . . KPN .`** - its request is on the third word and is
  honoured from the fetch's last clock (V, Q29), not a bus-idle word. 108 of 108 (84 here, 24 in
  round 9; was 9 of 24).
- **POP mem with a displacement: the displacement is taken on the write's request word**:
  `P . Y D . . PZ G N .` (d8), `P . Y D . . PP2Z G N .` (direct / d16). The stack read needs no
  address bytes; the fetch that this late pop starts is what delayed the write. 66 of 66 each
  (were 19 and 8 of 24).

## Q34. Strings, single element (round-9 data, read now; all four ways, 24 / 24 or 48 / 48)

| instruction | routine |
|---|---|
| LDM (AC / AD) | `. . . . Y DN .` |
| STM (AA / AB) | `. . B . . . Y G N .` |
| MOVBK (A4 / A5) | `. . . . . Y D . . . Z DN .` |
| CMPM (AE / AF) | `. . . . . . Y D . . N . .` |
| CMPBK (A6 / A7) | `. . . . . Y D . . . U D . N .` (U: the second read, [IX] after [IY]) |
| INM (6C / 6D) | `. . . . . X D Z DN .` |
| OUTM (6E / 6F) | `. . . . . . Y D . X . . . N .` (46 of 48) |

Byte and word forms are the same routine. MOVBK and INM end at their write's end (`Z DN .`),
not on its first clock: the exception to Q23, and the shape the REP iteration has.

## Q35. REP: a head, CW iterations, a tail

Probes: round 9 (CW = 0, 1, 2, 5; MOVBK byte / word, STM, LDM, CMPM; -a and -s) and round 11c
(CW = 1, 2, 3; those plus STM byte, CMPBK, INM, OUTM; -a, -s and behind a NOP). 660 runs, all
reproduced. The prefix is its own two-word routine (as a segment prefix). Behind it:

- **CW = 0:** 12 words, `. . . B . . . . . . N .`.
- **Head:** 14 words with a bus-idle fourth word, then the first request (first cycle 19 clocks
  after the string opcode's boundary). CMPBK's head is 13 words, OUTM's 15; INM and OUTM have
  the bus-idle word fifth.
- **Iteration** (period at W = 0; every cycle's waits add):

| form | iteration | period | tail after the last iteration |
|---|---|---|---|
| MOVBK | `Y D . . . Z D .` | 18 | `. . . . . . N .` |
| STM | `Y D .` | 9 | `. . . . . . N .` |
| LDM | `Y D . . .` | 11 | `. . . . . . . N .` |
| CMPM | `Y D . .` | 10 | 14 words, N next to last |
| CMPBK | `Y D . . . U D .` | 18 | 16 words, N next to last |
| INM | `X D Z D` | 14 | `. . . . . . . N .` |
| OUTM | `Y D X . . . . .`, the last one `Y D . X . . . . .` | 14 | `. . . . . . . N .` |

- **The compare forms read one element ahead.** REPE CMPBK over equal data makes CW + 1 pairs
  of reads (CW = 1: four reads). REPNE CMPM ended by its first element still makes a second
  read, and CW - 1 is left (seen as the length of the shift by CL behind it). The RTL's function
  makes the same reads; only the timing is open.
- **SHL r,CL with CL = 0 is two words shorter** (10, not 12): seen behind every REP, which
  leaves CW = 0.

Each iteration waits for its own cycles (D), so a fetch can only fall between iterations where
the queue has room; none does in these programs (the queue is full when the REP starts).
Interrupt sampling between iterations: not examined (deferred with interrupt recognition).

## Q36. MULU / MUL / DIVU / DIV on a register: fixed lengths, sign fix-ups only

Round 9 (8 probes) and round 11d (48 programs: six operand pairs each, chosen to expose operand
dependence: 0, 1, FFFFh, 5555h x AAAAh, mixed signs). Every one has a bus-idle third word (as
TEST and SHL r,1), takes the next opcode on its next-to-last word and is exempt from the
three-bytes rule like the other F6 / F7 group members.

| instruction | words | operand dependence |
|---|---|---|
| MULU r8 | 25 | none (10 operand pairs) |
| MULU r16 | 33 | none |
| MUL r8 | 36 | + 8 when the product is negative (operand signs differ) |
| MUL r16 | 43 | + 8 likewise |
| DIVU r8 | 33 | none (9 pairs) |
| DIVU r16 | 41 | none in six pairs with DW = 0 (one round-9 probe with DW = 20h is 2 shorter at even alignment only: open) |
| DIV r8 | 52 | + 2 when the quotient is negative, + 7 when the dividend is negative |
| DIV r16 | 60 | + 2 when the quotient is negative (dividend negative: not probed) |

No dependence on the operand's bit pattern: the multiply and divide loops run a fixed count.
The three sign terms are separate (a negative divisor alone costs nothing: 127 / -1 is base + 2,
-1 / -1 is base + 7, -1 / 1 is base + 9). 288 of 288 here, 162 of 168 in round 9.
Not measured: the memory forms, MUL r,r/m,imm (69 / 6B), divide errors.

## Also read from round-9 data (each 24 / 24)

- SHL [BW],1: `P . B Y D . . . . . Z G N .`.
- PUSH R (60): `. . B .`, then seven `Y D .`, then `Y G N .` (period 9, the STM iteration).
- POP R (61): `. .`, then seven `Y D .`, then `Y DN .`.

## The cross-tab on the spec-5 corpus, with "partner unread"

`build/qp/tab11.py` (table in divergence-notes.md): 13,875 diverging runs; 940 of them re-filed
from the positional subject to an unread partner in the window. Causes now: own 11,109,
undetermined 1,550, pair 355, predecessor 273, successor 194. By family, the diverging runs sit
in: REP strings 1,575, ALU / CMP / TEST mem,imm 1,318, the 0F bit forms 1,065, MOV mem,imm with
displacement / byte 1,060, POP mem 984, EXT / INS 672, MUL / DIV 620, the transfer forms 586,
ADD r16,imm (81 /0) 468, single strings 408. The first, second, fourth and fifth are read as of
this round (and POP mem, MUL / DIV on registers).

## Not read (data acquired)

The 0F memory bit forms and the imm8 forms, EXT / INS, ROL4 / ROR4, ADD4S, PREPARE, MUL
r,r/m,imm; ADD [d16],imm8 twice in a row (3 runs); OUTM twice in a row at even alignment (2
runs); DIVU r16 at even alignment with DW not 0; NOP;X;SHL for the CL bit forms and the shifts
by imm8 at one wait (round 9, 14 runs). Not acquired: MUL / DIV on memory, signed DIV r16 with
a negative dividend, REP with a segment override, REP interrupted. Interrupt recognition:
deferred as told.

# Round 12 (4,834 runs: 1,134 on the unread families, 3,700 interrupt probes)

Four acquisitions, safety sequence unchanged, no kill timer: `r12a` 990 runs (165 programs),
`r12b` 144 (the EXT / INS grid), the interrupt probes at W = 0 with the first windows (1,064)
and at W = 0 / 1 with the edge 20 clocks earlier (2,636). 0 failed, 0 incomplete; 2,059
repeats, every flagged one strobe-only (also in the interrupt rounds: the scheduled edge is
synchronous to the CPU clock, so a run and its repeat take the interrupt on the same clock).
Board powered down at the end (vccb false, failure 0). Every family program was run in the RTL
simulation first; the interrupt programs at all three waits with the first windows (3,984
runs) and a one-in-seven subset with the second (676): all reach their end.

New in the package: a run can carry its own stimulus (`knobs.stim`, loaded with the runner's
`load_stimulus` before the run and cleared for every other run), instructions before M0 and
behind END, and a handler address patched into a vector store. The interrupt programs use the
event port (OUT FF12h) once, before M0; NMI and INTP0 are driven only by the schedule.

Model score (no run lost in any round; rounds 1-11 gained 300):

| round | r1 | r2 | r3 | r4 | r5 | r6 | r7 | r8 | r9 | r10 | r11 | r12a + r12b |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| round-11 hand-back | 330 | 720 | 378 | 414 | 523 | 287 | 42 | 800 | 1,640 | 684 | 1,366 | - |
| now | 330/330 | 720/720 | 378/378 | 414/414 | 523/540 | 287/288 | 42/42 | 848/912 | 1,892/1,980 | 684/684 | 1,366/1,368 | 837/1,134 |

Rounds 1-11: 7,484 of 7,656. The 297 round-12 family runs the model does not reproduce are the
memory MUL / DIV (144: read directly, below), the word-crossing EXT / INS (36), MUL r,m,imm
(48), MUL r,r,imm (26), the register-indirect transfers at odd alignment and BRK imm8 behind
two stores (20) and X;X / NOP;X residues of the bit forms (23). The RTL (spec-5 build) has 186 of 1,134. The interrupt probes are read
from the traces directly (the model gives the uninterrupted program's boundaries).

## Q37. The 80 / 81 / 83 / F6 / F7 immediate forms on a register

| instruction | routine | score |
|---|---|---|
| ADD ... CMP r8/r16,imm8 (80, 83, every operation) | `P . . BNP .` | 96 / 96 |
| ADD ... CMP r16,imm16 (81) | `P . . . BNPP2 .` | 96 / 96 |
| TEST r8,imm8 (F6 /0) | `P . B . . NP .` | 24 / 24 |
| TEST r16,imm16 (F7 /0) | `P . B . . . NPP2 .` | 24 / 24 |

No dependence on the immediate's value (81 C2 0000h and 2A01h are the same) or on the
operation (CMP = ADD). The imm16 forms have their bus-idle word fifth, as MOV r16,imm16 and the
accumulator form. The corpus's add_dw_imm rows are the RTL's, not the chip's.

## Q38. The 0F page

One head for every form: `P . P`, and the commit word C (bus idle and no chained fetch starting)
three words after the ModR/M byte.

| instruction | routine | score |
|---|---|---|
| TEST1 / SET1 / NOT1 r,CL | `P . P . . CN .` (Q31) | |
| CLR1 r,CL | `P . P . . CN . .` | |
| TEST1 / SET1 / NOT1 r,imm | `P . P . . CPN .` | 51 / 72 (-a, -s all; X;X not) |
| CLR1 r,imm | `P . P . . CPN . .` | 17 / 24 |
| TEST1 mem,CL | `P . P . C Y DN .` | 44 / 48 |
| SET1 / NOT1 mem,CL | `P . P . C Y DZ G N .` | 44 / 48 |
| CLR1 mem,CL | `P . P . C Y D Z G N .` | 22 / 24 |
| TEST1 mem,imm | `P . PC Y DPN .` | 24 / 24 |
| SET1 mem,imm | `P . PC Y DPZ G N .` | 21 / 24 |
| ROL4 r8 / ROR4 r8 | head + 12 / 16 words: 18 / 22 words | 22 / 24 each |
| ROL4 mem / ROR4 mem | `P . PC Y D`, 8 / 12 words, `Z G N .` | 24 / 24 each |

The immediate of the r,imm forms is taken on the commit word; the routines are the CL forms'
lengths. What misses is X;X and NOP;X;SHL at one or two runs each (the second instruction's
entry), as for the CL forms. ROR4 is four words longer than ROL4 in both forms.

**EXT and INS** (grid: bit offset 0 / 5 / 12 x length 1 / 4 / 8 / 16, immediate count; round 9's
register-count probes): the head, the operand word's read on the ninth word, then

- EXT, field inside one word: 24 words + 2 x (16 - offset - length) + 2 x (16 - length), plus 4
  when length < 16, then the immediate and the next opcode on the next-to-last word. 54 of 54.
  Two shift loops at two words a bit: the field is moved to the top of the word and then down.
- INS, field inside one word: 70 words (72 with a non-zero offset, 8 fewer when the field ends
  at bit 15), then the write and Q23's ending. 54 of 54. A fixed 16-step structure: the length
  does not change it.
- The register-count forms are the same with the count in the second register and no immediate
  byte (round 9: 16 of 24 each, the rest X;X whose second count is the first's result).
- A field that crosses the word (offset + length > 16) reads / writes a second word: 6 grid
  points acquired (second read 29 clocks after the first; EXT 64 to 79 clocks from the first
  read to the marker), not fitted.

**ADD4S / SUB4S / CMP4S** (digit counts 1, 2, 4, 8 in CL): 144 of 144.

- one iteration per byte, ceil(CL / 2) of them; a 13-word head with a bus-idle fourth word;
- ADD4S / SUB4S iteration `Y D . . . U D . . . . . . Z D .` (read source, read destination,
  write destination; 30 clocks at W = 0), tail 10 words;
- CMP4S iteration `Y D . . . U D . . . . . . . .` (25 clocks), tail 11 words;
- ADD and SUB are the same routine; no data dependence seen (the memory image's bytes).

## Q39. MUL / DIV: what the lengths say about the machine

Round 11's register lengths, with this round's additions:

- **memory forms** (8 forms x 3 frames x 6): the operand's read (bus-idle third word, request,
  datum) in front of the register routine: read-to-marker = the register form's length + 11
  clocks at W = 0 for all eight (13 / 14 at W = 1, 15 / 17 at W = 2: the read's own waits), at
  both alignments (`build/qp/mmtab.py`). The model does not score them only because the setup
  in front (MOV [BW],imm16; MOV AW,imm16) is one of its known misses.
- **DIV r16 with a negative dividend** (4 pairs): the model's prediction from the 8-bit terms
  holds: + 7, and + 2 for a negative quotient. 24 of 24.
- **DIVU r16 with DW not 0** (3 pairs incl. the round-9 one): 41 words, no dependence. 18 of 18
  (the round-9 residue was the frame in front, not the divide).
- **MUL r16,r16,imm16 / imm8** (69 / 6B): 42 / 41 words, the immediate on word 4 / 3, + 8 for a
  negative product. imm8: 32 of 48 (the positive immediate 23 of 24, the negative one 9); imm16:
  14 of 24 (odd alignment 1 to 3 clocks late when a chained fetch follows the immediate's pop:
  open).

Structure these imply:

| | words (8 / 16 bit) | reading |
|---|---|---|
| MULU | 25 / 33 | one word per multiplier bit (8 more for 8 more bits), 17 words of entry and exit |
| DIVU | 33 / 41 | one word per quotient bit, 25 of entry and exit |
| MUL | 36 / 43 | the unsigned loop on magnitudes: + 11 / + 10 for the two sign tests and negations in front; + 8 to negate a negative product (the same 8 at both sizes: a double-word negate) |
| DIV | 52 / 60 | DIVU + 19; + 2 to negate the quotient; + 7 for a negative dividend (negate it in front, fix the remainder's sign behind); a negative divisor costs nothing by itself |
| MUL r,r,imm | 41 / 42 | the 16-bit signed routine, one or two words shorter (no accumulator high half) |

All are counted loops with no early exit and no dependence on the operands' bit patterns
(0, 1, FFFFh, 5555h x AAAAh, mixed signs: 6 to 10 pairs per form).

## Q40. PREPARE / DISPOSE; the transfer residue

- PREPARE imm16,0: `. . Y D . . . PP2 P . . C . . . . . . . . N .` (push BP first; the three
  operand bytes behind it; commit three words after the last byte). PREPARE with level L >= 1:
  the same head, L - 1 frame-pointer copies `U D . . . Z D . .` (read, push; 18 clocks) and the
  push of the new frame pointer. Levels 0, 1, 2: 72 of 72.
- DISPOSE: `. . Y DN .` (the POP routine). 24 of 24.
- **INT 3** (round-8 data) and **BRK imm8**: vector offset read, PSW push, vector segment read,
  PS push, PC push, flush: R W R W W. Each push is requested so that it starts 6 clocks after
  the read before it or on the third clock after that read's end, whichever is later;
  `. . . B . . . . Y . . . . . . . DZ D . . U . . . . . DZ D . . . Z D . . F N .` (first read
  13 clocks after the boundary). INT 3: 6 of 12 (odd alignment all waits; even alignment is
  blocked by the two vector stores in front, a known miss). BRK imm8 is one word longer; 2 of
  12 for the same reason plus a wait at 1 / 2 waits not placed.
- RET imm16: `. . . Y DPP2 . . F N .` - the immediate is taken at the datum, after the read.
  12 of 12.
- JMP mem16: `P PP2 B Y D . . F N .`, CALL mem16: `P PP2 B Y D . . . Z D . . F N .`: 10 of 12
  each.
- CALL r16: `P . . B . Y D . . F N .`, JMP r16: `P . . B . . F N .`: 6 of 12 each: at odd
  alignment behind MOV BW,imm16 silicon is 2 clocks later than the model at every wait. Not a
  count rule (four bytes held does not fit); open.

What is left of the transfer family in the corpus: BRK 3 / BRK imm (the routine above, not
verified at even alignment), CALL / JMP through a register at odd alignment, CALL far at even
alignment with waits (4 runs), the far forms through memory (not probed), RETI (not probed:
needs a frame that survives the mode bit).

## Q41. Interrupt recognition (NMI, INTP0)

Design: an edge on the pin a programmed number of ticks after the event OUT, stepped one clock
at a time across nine targets (the long shift's end, 20 CLC, 12 NOP, REP MOVBK with CW = 3,
four ADD [BW],AW, a prefixed load, MOV SS,AW, MOV DS0,AW, two MULU), for NMI and INTP0, both
alignments, W = 0 and 1. For every run the trace gives the acknowledge's five cycles and the
pushed PC, which names the instruction not executed; the model gives that instruction's
boundary B and the clock P its opcode entered the staging latch; e is the edge's clock at the
pin (event record's end + delay + 4 ticks; a constant of up to half a clock is not known).
Tables: `itab-all.txt` (every group), `istate-nmi.txt`; tools `build/qp/itab.py`, `istate.py`.

**What is settled**

1. **The acknowledge** is the INT sequence: vector offset read, PSW push, vector segment read,
   PS push, PC push, then the handler's fetch. Its first cycle starts **16 clocks after the
   boundary** it is taken at (14 to 18 with a fetch in flight; INT 3 is 13: three clocks of
   entry more), at every target, both sources, W = 0 and 1. The spacing inside is INT 3's.
2. **Where it can be taken.** Only at an instruction boundary; never inside the long shift
   (edges up to 35 clocks before its end are all taken at its end), MULU, or a read-modify-write.
   Never between a segment prefix and its instruction. **Never at the boundary behind MOV
   sreg,r16: the next instruction always runs first, for DS0 as for SS** (the same tables for
   8E D8 and 8E D0), and only that one.
3. **A REP string is broken between iterations**, and the pushed PC is the prefix's address.
   The break is decided before an iteration's write: an NMI edge at least 15.5 clocks before
   the write cycle of iteration k starts stops the string after iteration k; later than that,
   iteration k + 1 runs (or, on the last one, the string ends normally and the interrupt is
   taken at its boundary). **A broken REP's acknowledge starts 48 clocks after its last write
   ends** (W = 0; the normal boundary is 16), a long exit path.
4. **Latency from the pin.** With the bus quiet (the long shift's end, a REP iteration, the
   first instruction after either) an NMI edge is taken in front of instruction X when it is at
   the pin **14.5 clocks before X's opcode enters the staging latch** (15.5 before the boundary
   for routines that take the next opcode on their next-to-last word). The RTL of this
   worktree takes it about 10 clocks sooner (in simulation the same programs acknowledge 11 to
   13 clocks after the edge; silicon 31 to 36).
5. **INTP0 is sampled on a 16-clock grid** that runs from reset (the thresholds are 16 clocks
   apart at W = 0 and at W = 1, and move by one clock with the frame's alignment pad): an edge
   is seen at the next grid point and from there behaves as an NMI edge at about that point.
   So a maskable request's latency is the NMI's plus 0 to 16 clocks.

**What is not settled**

- In trains of short instructions the 14.5 grows: 15.5, 16.5, and 17.5 in a steady NOP train
  (an NMI edge must be 20.5 clocks before the boundary it is taken at; the first NOP behind a
  long shift 17.5, the second 18.5, then 20.5), 16.5 to 18.5 in the CLC train, 16.5 in the
  RMW train. I could not tie the extra 0 to 3 clocks to one state variable: the queue count,
  a fetch in flight at the pop, the time since the last fetch, a fixed number of instructions
  or staging pops after a delayed recognition were each tried on the 532 W = 0 NMI runs
  (`irule.py`, `icount.py`) and none reproduces more than 73 %. In the CLC train the edge
  thresholds repeat with the fetch pattern's 10-clock period, which says the bus unit takes
  part in the sampling. Rejected, so the builder does not try them: a pure delay to the
  boundary; a pure delay to the staging pop; "N more instructions after recognition".
- INTP0 across the RMW train: edges up to 27.5 clocks before the second boundary are taken
  there; every later edge in the window (30 clocks of them) is not taken at any of the next
  five boundaries but only behind the frame's second long shift, at W = 0 and 1, both
  alignments (NMI on the same programs is regular). Reproducible, not understood; the pulse was
  50 clocks wide in every run, a width dependence is the first thing to test.
- NMI and INTP0 arriving together, INT, the priority and vector lines (f3_vec / f3_order /
  f3_prio), HALT release: not probed here.

## The cross-tab split by what the model reads (item 4)

`build/qp/tab12.py` on the spec-5 rows (table in divergence-notes.md). A corpus form counts as
read when the small set holds probes of the same instruction signature and the model
reproduces at least 90 % of the runs that contain it and nothing unread. Of the 13,481
diverging runs filed under a form:

| | runs |
|---|---|
| own routine, read by the model (expected to clear when the specs are built) | 8,069 |
| other causes on read forms (the neighbour rows: branches behind CMP, SHL r,1 behind OUT, ...; also expected to clear) | 2,149 |
| own, partly read (EXT / INS word-crossing, CALL / JMP mem, BRK, SET1 mem,imm, CALL far) | 1,205 |
| own, not probed (CMP mem,imm16; DBNZE / DBNZNE; CLR1 mem,imm; REPC / REPNC; other encodings) | 1,447 |
| own, probed and not read by the model (MUL / DIV on memory: measured directly, Q39) | 388 |
| other causes, not probed or partly read | 223 |

So about 10,200 of the 13,500 are in forms the model has; about 3,300 are left, 388 of them
measured.

## Not read

EXT / INS across a word; MUL r,m,imm and MUL r,r,imm16 at odd alignment; the register-indirect
transfers at odd alignment; BRK imm8 at waits; MOV mem,imm16 followed by MOV r,imm16 (the
fetch behind the write is not chained on silicon: it costs the memory MUL / DIV their model
score); the residues named in the tables. Interrupts: the two open items above.

# Round 13 (1,960 runs: 852 on the families, 1,108 interrupt probes)

Two acquisitions, safety sequence unchanged, no kill timer: `r13a` 852 runs + 852 repeats, the
twelve interrupt rounds 1,108 runs + 277 repeats; 0 failed, every flagged repeat strobe-only.
Board powered down at the end (vccb false, failure 0). Every program ran in the RTL simulation
first (all 1,960 reach their end, RETI with PSW F002h included).

Model: rounds 1-11 7,495 of 7,656 (was 7,484); round 13a 819 of 852; the RTL (spec-5 build)
has 193 of 852. Against the round-12 hand-back the model gains 1,182 runs and gives up 19: 7
MUL r,r,imm8 runs (the new two-wait shape is better on 26 others) and 12 JMP / CALL r16
directly behind MOV BW,imm16 at even alignment (the old shape had those and missed 36 clean
ones; see Q44).

## Q42. The fetch behind a write (item 1): not Q33's "armed" condition; a new, small fact

Probes `fw-*`: MOV [BW],imm16 / MOV [BW],AW / PUSH, behind four pads, followed by MOV r,imm16,
MOV r8,imm8, NOP, MOV r,r, CLC or the marker (192 runs). The fetch that was waiting under the
write starts on the clock after the write (W+3 at W = 0). What follows it:

| follower | W = 0 | W = 1, 2 |
|---|---|---|
| MOV r,r; CLC; MOV r8,imm8; the marker (OUT DW) | next fetch chained (W+6) | chained |
| NOP | **one idle clock, fetch at W+7** | chained |
| MOV r16,imm16 | **one idle clock, fetch at W+7** | chained |

It does not depend on the queue count (both alignments, all four pads, counts 1 to 3 at the
decision) nor on the store (the same after MOV [BW],AW and PUSH where the phase is the same):
only on what the EU does on the two clocks where the chained fetch would begin.

- NOP's boundary falls on that clock (W+6). The boundary executes and the fetch gives way one
  clock. Q8 says the opposite for an ordinary chained fetch (the boundary waits); **the fetch
  chained to the fetch that followed an EU cycle yields to a boundary that arrives fresh on its
  clock** (a boundary that was already waiting, as MOV r,r's for its byte count, does not win).
  This is EU_EPRI of the merged reading (the boundary wins against the fetch pending under an
  EU cycle) carried one fetch further.
- MOV r16,imm16 has its bus-idle word on the next clock (W+7). **That chained fetch is not
  started when the EU's next word is a bus-idle word** (the word would have to wait the whole
  fetch). MOV r8,imm8's bus-idle word is on W+6 itself and pops there: no conflict.
- At W = 1 / 2 the first fetch is longer, both events fall inside it and wait as usual: no case.

In the model: `CH_EPRI`, `CH_BNEXT`. Together: the `fw` probes 176 of 192 (the rest are tails behind MOV r,imm16 / MOV r8,imm8
at one alignment), nothing lost elsewhere, and the memory MUL / DIV probes can be
scored (their setup was the MOV [BW],imm16 ; MOV AW,imm16 case).

**MUL / DIV on memory, scored:** `P . B Y D` in front and the register form's word count in
total (the read replaces five of its words; with the datum wait that is the + 4 clocks of
Q39). 96 of 144 (4 of 6 in every form; the two that miss are one wait / alignment of the frame).

## Q43. The not-probed block

| instruction | routine | score |
|---|---|---|
| CMP [BW],imm16 (81 /7) | `P . . BY DPP2 . BN .` | 24 / 24 |
| CMP [BW+d8],imm16 | `P . . BYP DPP2 . BN .` | 24 / 24 |
| CLR1 mem,imm | `P . PC Y DP Z G N .` | 21 / 24 |
| NOT1 / SET1 mem,imm, byte and word | `P . PC Y DPZ G N .` | 21 / 24 each |
| TEST1 mem16,imm | `P . PC Y DPN .` | 24 / 24 |

**DBNZE / DBNZNE (E1 / E0): not DBNZ's routine and no lead.** 60 of 60.

| case | routine |
|---|---|
| taken | `. . . B . . . P . . B . . F N .` (DBNZ's with the displacement one word later; 19 clocks to the target's fetch behind every predecessor) |
| not taken, flag false, count not 0 | `. . . B . . PN .` (BCWZ's not-taken routine) |
| not taken, count 0, flag true | `. . . B . . . P . BN .` |
| not taken, count 0, flag false | `. . . B P . BN .` |

**REPC / REPNC (65 / 64)** are REPNE / REPE with the carry as the condition: the same head,
iterations and one-element read-ahead. REPC CMPBK over equal data ends at the first pair (two
pairs read, CW - 1 left; tail 15 words, one fewer than the count-ended exit); REPNC CMPM runs to
the count with CW + 1 reads, the first 10 clocks apart and the rest 12 (`Y D . . . .`), tail 13
words. 72 of 72 (with REPNC CMPBK and REPC CMPM, which needed nothing).

## Q44. The partly-read block

**EXT / INS across a word** (12 grid points each): 144 of 144.

- EXT: the second word is read 29 clocks after the first; then 12 + 2 x offset words (one more
  when the length is under 16), the immediate and the next opcode. The length does not matter.
- INS: the first word is written as a field ending at bit 15 (write 71 clocks after the read),
  the second word read 14 clocks later and written after 17 + 4 x m words, m = the bits that
  fall in the second word.

**Transfers.**

| instruction | routine | score |
|---|---|---|
| JMP r16 | `P . B . . . . F N .` | 36 / 36 clean, 6 / 12 behind MOV BW,imm16 |
| CALL r16 | `P . B . . . . Y D . . F N .` | 36 / 36 clean, 6 / 12 behind MOV BW,imm16 |
| INT 3 | `. . B . B . . Y . . . . . . . DZ D . . U . . . . . DZ D . . . Z D . . F N .` | 37 / 42 |
| BRK imm8 | `. . . BP . B . . Y ...` (the same from the first request on) | 22 / 24 |
| JMP far [d16] | `P . B . Y PP2 D . U D . . F N .` | 12 / 12 |
| CALL far [d16] | `P . B . Y PP2 D . U D . . . Z D . . . Z D . . F N .` | 12 / 12 |
| RETI | `. . Y D . . . U D . . . U D . . . . . . . . F N .` | 12 / 12 |

- **The "two clocks late at odd alignment" of JMP / CALL r16 was the shape, not a rule**: with
  BW loaded before M0 (so that the transfer stands alone behind the long shift) and with one or
  two NOPs between, the routine is one word longer than round 12's and its bus-idle word is the
  third (Q27's word, one earlier, as in the other FF-group members and in TEST). The flush tail
  is Q21's. The old shape was right only where the frame's own stall hid the difference. What
  is left (12 runs) is the transfer directly behind MOV BW,imm16 at even alignment: silicon runs
  it 3 clocks earlier than the model, i.e. MOV BW's boundary does not wait there as the model
  has it. They are also exempt from the three-bytes rule (as F6 / F7 / FE).
- INT 3 behind the long shift: first vector read 12 clocks after the boundary; bus-idle words
  third and fifth. BRK imm8 takes its byte on the fourth word (bus idle) and has a second
  bus-idle word two later; both then run the same sequence.
- RETI: three stack reads 9 clocks apart, then 8 words to the flush. PSW F002h (MD = 1, register
  bank 7, the reset bank) returns cleanly on the chip.
- CALL far behind CLC / NOP at odd alignment, 1 / 2 waits (8 runs): the first push is two
  clocks later than the model when three fetches chain in front of it. A bus-idle word in the
  routine does not fit; open.

**MUL r16,r16,imm** (round-12 data): 41 words (imm16) / 40 (imm8), bus-idle words two and four
words after the immediate's; imm16 24 of 24, imm8 34 of 48.

Not done: the X;X and NOP;X entry misses of the 0F forms; ADD [d16],imm8 twice; OUTM twice.

## Q45. Interrupts, continued

1,108 probes: NMI across four more trains (CBW, MOV r,r, NOP / CLC alternating, MOV r8,imm8)
and the NOP / CLC trains at W = 2; INTP0 across RMW / load / store trains with pulses of 10, 50
and 500 clocks; HALT release; NMI and INTP0 on the same clock. Tables: `itab13.txt`;
`build/qp/ievt.py` lists every threshold against candidate decision events.

**(a) The 0 to 3 extra clocks: one rule now covers most of it.**

*An NMI edge is taken in front of instruction X when it is at the pin 15.5 clocks before X's
opcode leaves the queue* (the model's pop P). Over the 278 thresholds of rounds 12 and 13:
15.5 in 81, 14.5 in 68, 17.5 in 71, 16.5 in 31, other 27.

- 15.5 is the steady value of every train but one: CBW, MOV r,r, MOV r8,imm8, NOP / CLC
  alternating, RMW, and most of the CLC train. Put the other way: the request is examined one
  clock before the next opcode is taken, and the opcode that is taken then runs.
- 14.5 when the bus has been idle and the queue full (the long shift's end, a REP iteration, the
  first instruction behind them, and the first two instructions of any train).
- 17.5 in a train of NOPs only (NOPs alternating with CLC have 15.5), and 17.5 to 19.5 in the
  NOP train at W = 2, moving with the fetch's phase against the train. So the bus unit does
  take part, but only there.
- The first three thresholds behind the long shift are the same in every train, at every wait
  (edge + 14.5 = one clock after the long shift's end, then three clocks later, then two), whatever
  the instructions' lengths: for those the decision follows the queue's own refill, not the
  EU's routine. After them the thresholds step with the instructions.
- Tested and rejected: sampling on a particular clock of a fetch cycle (first, last, start of
  the last fetch before the pop, end of it); the pop that follows a completed fetch; "the opcode
  already staged runs, the next is replaced" as a two-deep rule (decision at the previous pop
  + 1: it fits the NOP train alone). None is constant across trains.

What I would build: 15.5 before the pop, 14.5 from an idle bus; and leave the NOP train's two
extra clocks.

**(b) INTP0 across the RMW train: it is the read-modify-write, not the pulse.**

- The pulse width makes no difference at all (10, 50, 500 clocks: the same three ranges to the
  clock, in the RMW train and in the NOP train). INTP0 is edge-latched.
- A train of loads and a train of stores are regular: thresholds on the 16-clock grid, each
  taken at the first boundary 16 to 24 clocks behind its grid point.
- Only the train of ADD [BW],AW shows the gap: edges up to 7.5 clocks before the first RMW's
  read are taken (at the first or second RMW's boundary); every later edge is delivered only
  after the train has ended and a further grid point has passed, which in this frame is behind
  the second long shift. The edge is not lost.
- The RMW's operand is DS0:0800h, external RAM, not the on-chip page; nothing the program does
  touches the SFR area after the setup.

So: while read-modify-write instructions run back to back, the maskable request is not
presented to the CPU (the NMI is). The simplest machine that does this is a scan that is
restarted (or held) by the read-modify-write's locked read-to-write window: with RMWs every 13
clocks no 16-clock scan completes. Not proved: it needs a train with idle gaps of chosen length
between the RMWs.

**(c) First facts on the rest.**

- NMI and INTP0 on the same clock: the NMI's vector is taken (8 runs).
- HALT release: the acknowledge's first cycle is 34.5 clocks after an NMI edge at W = 0 and 33.5
  at W = 1 / 2 (the edge 10 to 30 clocks into the HALT), pushed PC the instruction behind HALT.
  INTP0: 33.5 clocks after its grid point. One INTP0 case at odd alignment releases the HALT and
  is taken one instruction later; not followed up.
- An interrupt edge that arrives before the HALT's boundary is taken in front of the HALT.
- Priority and vector order among maskable sources, INT / INTAK: not probed.

# Round 14

3,826 socket runs in four batches (456 form probes, 3,370 interrupt probes), 0 failed, every
flagged repeat strobe-only; the board ended powered down. Model: rounds 1 to 11 7,501 / 7,656
(was 7,495), round 12 1,446 (was 1,396), round 13a 819 / 852, round 14 forms 451 / 456.

Two things could not be done under the standing limits and are reported, not worked around:
**the INT pin with INTAK** and **TOUT's edge on the pin trace**. Both need the port bank R2
handed to the CPU, which the harness does only through marker writes to FF10h
(`docs/v35s-harness.md`: the INTAK answer drives only while R2 is CPU-driven; a pin is recorded
only while its bank is in mode D), and FF10h is excluded for my programs. Without the answer
the CPU would read its vector from an undriven bus, so the INT pin was not pulsed at all. The
timer's latency is given against the timer's own count instead (Q51).

## Q46. The small not-probed forms (item 3): all read

| form | routine | runs |
|---|---|---|
| 80 group on memory, byte (ADD / OR ... [BW],imm8; CMP) | the 83 group's (`P . V DPZ G N .`, `P . V DP . BN .`) | 72 / 72 |
| SHL / SHR ... word or byte [BW],imm8 (C1 / C0) | `P . V DP . B`, 4 + 2n words, `Z G N .` | 96 / 96 |
| the same by CL (D3 / D2) | `P . . B . . . Y D`, 3 + 2n words, `Z G N .` | 96 / 96 |
| LDS / LES r,[BW] | `P Y . D . U . D . . N .` | 44 / 48 |
| MOV [BW],sreg | `P . V . G N .` | 24 / 24 |
| MOV sreg,[BW] | `P Y . DN . .` (and the MOV sreg lead of two) | 24 / 24 |
| PUSH imm8 (6A) | `. . . P . Y N` (PUSH imm16 less one word) | 23 / 24 |
| CVTWL (99) | `. . . . . . . N .`: nine words, the next opcode on the eighth | 24 / 24 |
| MUL r16,[BW],imm16 (69 mem) | `P . . BY DPP2 . B . B`, 39 words in all, next opcode on word 38 | 47 / 48 |
| MUL r16,[BW],imm8 (6B mem) | `P . V DP . B . B`, 38 words in all, next opcode on word 37 | 47 / 48 |
| EI | `. . . . . . . . . . . N .`: thirteen words, the next opcode on the twelfth | from the interrupt probes |

- **The shift on memory is the register shift's count loop between a read and a write.** The
  count was probed at 3 and 4 first, the routine written as "2 words a count", and the counts 1
  and 8 then acquired: 96 / 96 as predicted. The CL form waits on its fourth word like the
  register form and reads after it; the imm8 form reads first (the 83 group's head, the count
  byte taken with the datum) and has the bus-idle word behind the read.
- **MUL r,m,imm has the ALU-immediate heads**: the imm16 form the 81 group's (`P . . BY DPP2`),
  the imm8 form the 83 group's (`P . V DP`), then the register form's two bus-idle words (two
  and four words behind the immediate) and a body two words shorter than the register form's.
  One of 48 each is open (NOP;X;SHL at odd alignment, W = 0, 3 clocks).
- LDS;LDS misses 4 runs for a reason that is the probe's: the first LDS loads DS0, so the
  second reads from another segment (LES;LES is exact). Not a timing fact.
- CVTWL and EI are long for what they do (9 and 13 clocks from a full queue) and release the
  next opcode late: neither is CBW- or CLC-shaped.

## Q47. JMP / CALL r16 at even alignment: a second bus-idle word, not a byte count

`JMP r16` is `P . B . B . . F N .` and `CALL r16` is `P . B . . B . Y D . . F N .`; the "four
bytes in the queue" stall of round 12 is removed (96 / 96; the 12 runs behind MOV BW,imm16 that
were 3 clocks late are exact). The second bus-idle word is what made the old shape right
everywhere except where a chained fetch was in flight on that word: it is Q26's rule (the word
waits for the bus), on the fifth word of JMP and the sixth of CALL. So the answer to "is it the
bus-idle word against the chained fetch?" is yes, and the word had been missing.

## Q48. Same instruction twice (item 4): two different things, one rule each, one withdrawn

- **0F memory bit forms with an imm8 (SET1 / CLR1 / NOT1 mem,imm), X;X at odd alignment,
  12 runs**: the second instance's commit word was held by a chained fetch that silicon lets
  pass. Rule kept: *a commit word that also pops is not held by the fetch chained behind an EU
  cycle's fetch* (the fetch Q42 is about). 12 gained, 0 lost over 14,450 runs. The boundary fact
  is one the bus unit already has for Q42 ("this fetch is the one chained behind the post-cycle
  fetch"); no new level.
- **TEST1 r,imm twice at even alignment (3 runs)**: silicon's second instance starts one clock
  earlier than the model's at all three waits: its boundary goes on the second-last clock of the
  fetch that started on the clock the first instance's commit word passed. Written as a rule
  ("behind a commit word the boundary goes one clock before the fetch's last") it gains these 3
  and 8 more and loses 46 (the CL forms at one and two waits, where the boundary does wait for
  the last clock). **Withdrawn as a rule**; the three runs stay open with that description.
- **ADD [d16],imm8 twice at even alignment (3 runs)**: silicon's second read loses to one more
  chained fetch than the model's (read at 103 against 100 at W = 0), which needs the second
  instance's boundary one clock later than the write's last clock, where the model puts it.
  Lengthening the routine's tail does not do it (the tail is absorbed by the write). Not the
  same thing as the TEST1 case (that one is early, this one late). Open.
- **OUTM twice at two waits (2 runs)**: one clock, unchanged. Open.

So the coordinator's "one rule about a routine following itself" does not exist in this data:
the three families miss in three directions. What they share is only that X;X is the one
neighbour whose first word is sensitive to the boundary's clock (SHL, OUT and NOP behind X wait
on a slot and hide it).

CALL far at even alignment with waits and at odd alignment (12 runs, the first push 2 clocks
late in the model's terms at W = 1 / 2): the push starts 3 clocks after the end of the third
fetch where the model has 1. Six shapes with a bus-idle word in front of the request tried,
none kept. Open.

## Q49. Interrupts: the maskable request is found by a level scan, two clocks a level

Requests set by software (a store of IF into the request-control register with IE = 0), then
released at a known instruction; no pin is involved, so the result is exact to the instruction
(90 + 140 runs, `r14s`, `r14u`, `r14v`).

- **Order and vectors are the RTL's**: INTP0, INTP1, INTP2 in that order at one level; timer 0
  before INTP0 at one level; a level-2 request before a level-5 one; a request of higher level
  set inside a handler nests after EI, one of equal level waits for FINT. Two and three pins
  pulled on one grid point: INTP0, then INTP1, then INTP2. Two pins one grid point (16 clocks)
  apart: the earlier wins whatever its place in the order (nothing can displace it: the later
  request is not seen until the next grid point, after the decision).
- **The latency after EI depends on the request's level** (EI in front of a NOP train, moved in
  2.5-clock steps by 0 to 13 CLCs, both alignments; NOPs executed between the EI and the
  acknowledge):

  | level | NOPs executed after EI (28 positions each) |
  |---|---|
  | 0 | 2 at 27 positions, 6 at one |
  | 2 | 3 at 9, 4 at 19 |
  | 5 | 4 at 3, 5 at 24, 2 at one |
  | 7 (INTP0), 7 (timer 0) | 6 at all 28 |

  In clocks: level 0 is seen 8 to 12 clocks after EI's last word, level 2 about 6 clocks later
  than level 0, level 5 about 12 later, level 7 16 later. **Two clocks a level and a 16-clock
  round: this is the 16-clock "grid" of Q41 / Q45.** The grid on which a pin's edge becomes a
  request is the scan passing that source's level; a level-7 source is looked at once every 16
  clocks.
- **EI starts the scan; POP PSW and clearing the mask do not.** After EI the latency is the same
  at every position (the table: no 16-clock jumps as the EI moves through 32 clocks). After
  POP PSW it is 4 to 8 NOPs, after `AND byte [EXIC0],0BFh` 7 to 8, i.e. a round that was already
  running. Three EI runs of about 170 are a round off (`nei-nop` at even alignment, W = 2, and level 5
  with 10 CLCs at odd alignment, 16 clocks early; level 0 with 6 CLCs at even alignment, 16
  late): noted, not explained.
- **What the gate programs see.** `f3_order` releases a pending request (EI, POP PSW, a mask
  clear, RETI, FINT) in front of MULU absorbers; `f3_prio` sets several requests and releases
  them the same way. Behind a MULU (24 clocks and more) silicon and the RTL take the request
  in front of the same instruction (`sw-ei-mul`: both after the first MULU, silicon's vector
  read 11 clocks later), so those programs differ on clocks only; behind short instructions
  (the INC AW chains of the latency tests) silicon is 1 to 7 instructions later than the RTL,
  by the level and the instructions' length.
- **RTL against silicon**: the RTL takes every one of these one instruction after the release;
  silicon 2 to 8 instructions after. After a handler's FINT; RETI the next pending request is
  taken after 2 or 3 instructions of the interrupted stream (RTL: 1); from the RETI's last
  stack read to the next vector read 47 to 51 clocks (RTL 37 to 41).
- **From the deciding pop to the acknowledge**: the vector read starts 17 clocks after the pop
  of the first instruction not executed (CLC, INC, MULU trains) and 19 in NOP / XCHG trains, at
  every wait, alignment and release kind (every run where the model gives the pop). This is the constant behind Q41's
  "16 clocks after the boundary".
- **EI itself is 13 clocks** from a full queue and releases the next opcode on its twelfth word
  (RTL: one clock shorter). The corpus form `sti` (12 runs) is this.

## Q50. NMI against a maskable request, and nesting

- **First come, first served at the request latch, not "NMI wins".** INTP0's edge fixed, the
  NMI's stepped a clock at a time from 6 clocks after it to 111 after: an NMI that is in before
  INTP0's grid point is taken first (its own vector, at whichever boundary it reaches); an NMI
  that arrives after INTP0's request has been raised does not displace it, even where the NMI
  alone would have made the same boundary (NMI edges 1 to 6 clocks after the grid point):
  INTP0's acknowledge runs, **two clocks later than without the NMI** (vector read 18 clocks
  behind the boundary, not 16) for every NMI edge up to about 11 clocks before that vector read,
  and the NMI is acknowledged in front of the handler's first instruction (pushed PC = the
  handler's entry). Round 13's "the NMI's vector is taken" on a common edge was the NMI being
  earlier (it does not wait for the grid).
- **The end of an acknowledge is an ordinary boundary.** The NMI's own vector read comes 64
  clocks after INTP0's at even alignment and 67 at odd (2 more at two of every eight edge
  positions); an NMI edge up to 18 clocks
  before the handler's first boundary is taken in front of the handler's first instruction,
  later edges behind the first, second, third instruction by the usual threshold. Nothing is
  special about "during the acknowledge" or "during the handler's first instruction".

## Q51. Timer 0's request goes through the same scan

Timer 0 as an interval timer (SCLK / 6), the count n from 3 to 18, the timer started by a store
in front of NOP; HALT, the request releasing the HALT (r14t, 56 runs, W = 0).

- The acknowledge moves in steps of 16 clocks, one step every 16 / 6 counts (n = 3, 4, 5: 165;
  6, 7, 8: 181; 9, 10: 197; 11, 12, 13: 213; 14, 15, 16: 229; 17, 18: 245, even alignment):
  the underflow sets the request flag and the scan finds it at its level-7 point, as for a pin.
  The RTL's acknowledge moves 6 clocks a count (135 + 6(n - 3)): no scan, and 18 to 30 clocks
  earlier.
- In pin terms: the underflow of count n acts like an INTP0 edge at clock 97.5 to 99.5 + 6n from
  M0 in this frame (the start store's instruction begins at 79), i.e. **the flag is set 12.5 to
  14.5 clocks after the start store's instruction begins, plus 6(n + 1) clocks**, to within the
  2 clocks the thresholds leave. NOPs in front of the start store move it 4 clocks each (6
  positions): the count starts at the store, not on a free-running divider, at this resolution.
- The same request in a NOP train: taken 27 to 31 clocks later than the RTL (6 NOPs).
- TOUT's edge against the underflow: not measured (see the top of this round).

## Q52. The HALT release taken an instruction late: not alignment; two programs do it

INTP0 into `NOP; HALT`, one clock at a time (88 runs), timer 0 into the same (32 runs) and
INTP0 into HALT behind a jump with 0, 1, 2, 3, 4, 6 NOPs between (72 runs).

| program | alignment | released by a request raised while halted |
|---|---|---|
| NOP; HALT | even | acknowledge 33.5 clocks after the grid point, pushed PC = the instruction behind HALT |
| NOP; HALT | odd | **the instruction behind HALT runs first** (a fetch 15.5 clocks after the grid point, the marker's cycle, then the acknowledge 40.5 after the grid point; pushed PC one instruction on); every grid point, INTP0 and timer alike |
| JMP; HALT | even | **late in the same way** (no fetch at the release: the queue is full) |
| JMP; HALT | odd | normal |
| JMP; 1 to 6 NOPs; HALT | both | normal |

So it is not the alignment and not "a fetch starts on the release". In the two late programs
the HALT is the second instruction behind a queue that was just refilled (the long shift's
end, a jump) with nothing between; what they have that the others lack was not found. The
queue's content, whether the next opcode had been taken before the halt (it had, in one late
and one normal program), the HALT's address parity (even in both late programs and in one
normal one) were each checked against the table and do not separate the rows. Open, with the
table as the test for any rule. The RTL never runs the instruction first.

## Q53. INTP0 held back: it is one instruction class, from its request word to its end

Twenty-eight trains, INTP0's edge stepped a clock at a time across each (2,480 runs).

- **The window.** Against `ADD [BW],AW; NOP`, with one, two and four NOPs between, with CLC
  between, with a displacement, with a BUSLOCK prefix: an edge that arrives from about the
  instruction's first clock (half a clock before to half a clock after its boundary, on the
  2-clock lattice below) is **not seen by the next scan point; it is seen by the one after the
  instruction has ended**. Every threshold in these trains is either a scan point (16 apart) or
  an ADD's start, to the clock. The edge is never lost. Back to back (round 13) the windows
  touch and the edge waits for the train's end: the same fact.
- **Which instructions** (each as `X; NOP` four times; "window" = a threshold at X's start,
  "none" = thresholds on the 16-clock scan only):

  | window | none |
  |---|---|
  | ADD / OR / ADC / AND / SUB / XOR [BW],AW (01, 09, 11, 21, 29, 31) | ADD AW,[BW] (03) |
  | ADD [BW],AL (00) | TEST [BW],AW (85) |
  | **CMP [BW],AW (39): no write at all** | MOV [BW],AW (89), MOV AW,[BW] (8B) |
  | ADD [BW],imm8 (83 /0) | INC [BW] (FF /0), NOT [BW] (F7 /2), SHL [BW],1 (D1 /4) |
  | ADD [BW+2],AW; BUSLOCK ADD [BW],AW | XCH [BW],AW (87); BUSLOCK MOV AW,[BW] |

  So it is **not the read-modify-write** (CMP does it; INC, NOT, SHL, XCH do not) and **not a
  bus lock** (the prefix changes nothing either way). It is the two-operand ALU instruction
  with memory as its first operand: opcodes 00 to 3F with the direction bit clear, and the 83
  group on memory. Those are one routine family in any microcoded 86 (the result or the flags
  come from "memory operand, then source"); the unary groups, TEST and the reversed direction
  are other families.
- **The pin is sampled every second clock.** Every threshold of every train lies on one 2-clock
  lattice per alignment (x.5 with x odd at even alignment, x even at odd alignment): the
  edge detector runs on a divided clock, and the scan's 16 is 8 of its periods.
- In all these trains the request is taken at the boundary behind the memory instruction (in
  front of the NOP), almost never in front of the memory instruction: consistent with Q54 (the
  deciding pop for the instruction behind a NOP is the NOP's own first word, two clocks after
  the previous decision).

## Q54. The NOP train's 17.5: the pop that matters is one instruction earlier

NMI stepped across a train of XCHG AW,BW and a train of NOP, NOP, CLC (120 runs).

- XCHG AW,BW (the same routine shape as NOP) gives NOP's figure: 17.5 clocks before the model's
  pop of the first instruction not executed, where the general figure is 15.5.
- Measured against the pop of the instruction **before** it, the threshold is constant: 13.5
  clocks before the pop of X - 1 in the XCHG train (4 of 4 steady positions) and in the mixed
  train (4 of 5; the fifth 12.5), against 2 of 5 for the pop of X. The first two instructions
  behind the long shift (popped back to back from a full queue) are the exception both ways.
- The six earliest thresholds are the same clock in both trains although the instructions
  differ in length: the threshold follows the pops, not the boundaries.

So the hypothesis holds: for an instruction that releases the next opcode on its first word the
decision for its successor is made at its own pop. In machine terms the request is looked at
when an opcode leaves the queue; a one-word-release instruction has already taken its successor
when it starts.

# Round 15

1,533 socket runs (1,245 interrupt probes, 288 form probes), 0 failed, flagged repeats
strobe-only, the board powered down at the end. FF10h marker writes were used from this round
(authorised), only to hand port bank R2 to the CPU and back, exactly as `banks.py` INT_HEAD /
INT_TAIL and `periph.py`'s TOUT set-up do it; the first INT program was run alone and its vector
read checked before the batch.

**Scope actually covered:** item 1 (INT / INTAK, TOUT) and item 2 (class, timer under the
window, levels, HALT predecessors, the EI outlier) in full; of item 3 only the not-probed small
forms (Q60). **Not done this round:** the partly-read block (EXT / INS frames, MUL / DIV on
memory in the missing frame, CALL mem16, BRK 3 / INT 3 remainder, SET1 mem,imm), and item 4
(CALL far with waits, ADD [d16],imm8 twice, OUTM twice, the word-level diagnosis of JMP near
and LEA in the RTL). No corpus replay was needed (the RTL in my worktree is still the 6+7
copy), so the split table is round 14's.

One thing for the builder outside the core: **in the direct sim build the INTAK answer does not
reach the core** (the RTL reads its vector from the idle bus, 90h, and goes through 0240h), so
INT programs cannot be sim-checked with `qprobe.run --backend sim`; on the socket the same
programs read 0100h as set. The RTL's INTAK cycles themselves are visible there (below).

## Q55. The INT pin: it does not go through the scan; INTAK is 2 low, 1 high, 2 low

INT raised a clock at a time across a NOP train and into HALT, with INTP0 and with NMI on the
same edge, and held high behind IE = 0 and released by EI (212 runs; /INTAK recorded).

- **No scan, no grid.** The thresholds move with every instruction (even alignment, NOP train:
  68.5, 70.5, 74.5, 78.5, 82.5, 86.5), the same clocks as the NMI's from the second
  instruction on (Q54: 70.5, 74.5, 78.5, 82.5), 5 clocks later than the NMI's for the first.
  INT is level-sensed and goes to the EU directly; the decision is at the pop, as for the NMI.
- **The acknowledge.** Counted from the pop P of the first instruction not executed (NOP
  train): /INTAK low P + 8 to P + 10, high one clock, low P + 11 to P + 13; the vector table's
  offset read starts at P + 23 (a vectored source: P + 19), then the usual four cycles. For the
  first instruction behind the long shift everything is 2 clocks earlier. The vector byte is
  the one on D7 to D0 during the pulses (40h answered, 0100h read, every run). The RTL: 2 low,
  **3 high**, 2 low, and the table read 5 clocks after the second pulse where silicon has 10.
- **Out of HALT**: /INTAK falls 21.5 clocks after the INT edge and the table read starts 36.5
  after it, at every clock of the edge and **at both alignments**: the "one instruction late"
  release of Q52 does not happen for INT.
- **Released by EI** (INT high since before the long shift, the EI moved by 0 to 13 CLCs, both
  alignments): always one instruction after the EI (28 of 28). No level latency.
- **Against INTP0**: on one edge, INT is acknowledged first at every position (it does not
  wait for the scan). With both pending behind IE = 0 and released by EI: INT first when INTP0
  is at level 7, 5 or 2; with INTP0 at level 0 INTP0 is first at one EI position and INT at the
  other (the level-0 request arrives 8 to 12 clocks after the EI, INT's one instruction after:
  whichever is raised first is taken, Q50's rule).
- **Against NMI on one edge**: INT is acknowledged first (it reaches the EU about 5 clocks
  sooner than the NMI), its vector read 2 clocks later than without the NMI, and the NMI is
  taken in front of the handler's first instruction, 64 clocks after: Q50's pattern exactly.

## Q56. TOUT against the underflow and the request flag

Timer 0, SCLK / 6, TOUT enabled (TMC0 = 8Ch), P15 recorded (64 runs).

- The start store's effect reaches the pin 13.5 clocks after its instruction begins (TOUT
  takes its level at 92.5 with the instruction at 79).
- **TOUT's first edge is 3.9 clocks + 6 (n + 1) after that** (120.4, 126.4, 132.4 ... for n = 3,
  4, 5 ...), and every 6 (n + 1) after.
- **The request flag**: the underflow acts on the scan like an INTP0 pin edge 2.9 to 4.9 clocks
  before TOUT's recorded edge (five scan thresholds between n = 5 and 17 agree). So the flag is
  set at the underflow, and TOUT toggles 3 to 5 clocks later less whatever the pin's own
  synchroniser adds to an INTP0 edge (at least one sample of the 2-clock detector). Pin times
  are as the harness records them (two flops, a quarter to half a clock).
- TOUT's edges do not move with the acknowledge (in HALT or in a NOP train): the pin follows
  the counter, the request waits for the scan.

## Q57. Pin requests at other levels: two clocks a level, to the clock

INTP0 at level 5, 2 and 0 across the NOP train (240 runs). Scan thresholds of the edge, even
alignment: level 7 71.5 and 87.5 (round 14); level 5 67.5 and 83.5; level 2 61.5 and 77.5;
level 0 73.5 and 89.5 (= 57.5 + 16). Odd alignment one clock later throughout. **Exactly
2 clocks a level earlier, modulo the 16-clock round**: Q49's prediction. The scan visits level
0 first and level 7 last, 2 clocks each.

## Q58. The held-back request: the class is closed, and the timer is held too

- **Class** (seven more trains, 476 runs): the window is opened by ADD [BW],imm16 (81 /0),
  ADD byte [BW],imm8 (80 /0), **CMP [BW],imm8 (83 /7)** and SBB [BW],AW; not by DEC [BW]
  (FF /1), NEG [BW] (F7 /3) or TEST [BW],imm16 (F7 /0). With round 14: every two-operand ALU
  instruction whose first operand is memory (00 to 3F with the direction bit clear, and the 80
  to 83 group on memory), CMP included; nothing else tried (TEST, the unary groups, shifts,
  XCH, MOV, the reversed direction).
- **Timer 0's request across `ADD [BW],AW; NOP`** against the same across NOPs (120 runs, the
  count n from 2 to 11, the start moved by 0, 1, 2 CLCs): in the NOP train the counts fall into
  the scan's groups (16 clocks). In the ADD train counts that share a scan group in the NOP
  train are taken at different boundaries (n = 3, 4 at one, n = 5 at a later one; n = 2 apart
  from 3, 4), in four of the six start / alignment combinations. A pure scan
  cannot split one group. **So the timer's request is held by the same window**: what is held
  is not the pin's edge detector but the setting of the request flag (or its passage to the
  scan), for any source.
- The scan itself is not stopped: thresholds behind a window are still on the original 16-clock
  round (round 14's g4 train).

## Q59. HALT release one instruction late: a table of 16 programs, still no rule

INTP0 into `X; HALT` for twelve predecessors (72 runs), with round 14's:

| in front of HALT | even | odd |
|---|---|---|
| nothing (HALT first behind the long shift) | late | normal |
| CLC; INC AW | late | normal |
| NOP; XCHG AW,BW | normal | late |
| PUSH AW | normal | normal |
| CLC, NOP; MOV CL,imm8 | late | late |
| NOP, NOP; MOV AW,imm16; NOP, NOP, NOP | normal | late |
| MOV AW,[BW] | late | normal |
| JMP | late | normal |
| JMP; 1 to 6 NOPs | normal | normal |
| JMP; CLC | late | late |

"Late" = the instruction behind HALT runs before the acknowledge, at every scan point. What is
new: (1) **INT never does it** (Q55), so it belongs to scan-sourced requests, not to the HALT
exit as such; (2) it is not the HALT's address parity, not the predecessor's length in bytes
(one-byte predecessors go both ways) and not simply its length in clocks. With the scan's
2-clock steps and phase set by the last EI, the natural candidate is the clock at which the EU
halts against the scan's 2-clock phase, combined with whether the next opcode had been taken;
the instruction lengths here are not known to the clock in this frame well enough to test it.
A probe that would: one predecessor, the EI (which sets the scan) moved a clock at a time by
the wait setting of an earlier fetch. Open.

Also: EI behind a NOP at two waits, moved by 0 to 13 CLCs (28 runs): the latency is 5 or 6 NOPs
everywhere except the one position round 14 found (no CLC, even alignment: 2 NOPs). The outlier
is reproducible and isolated; the other two of round 14 were not re-probed.

## Q60. The not-probed small forms

| form | routine | runs |
|---|---|---|
| CMP [BW],AW / AL (39 / 38) | `P Y . D . N .` | 48 / 48 |
| TEST AL,imm8 (A8), CMP AL,imm8 (3C) | ADD AL,imm8's (`. . . BNP .`) | 48 / 48 |
| XCH AW,DW (92) | XCHG's | 24 / 24 |
| IN AW,DW (ED) | IN AL,DW's | 24 / 24 |
| ADJ4A (27) | ten words, the next opcode on the ninth | 24 / 24 |
| ADJBA / ADJBS (37 / 3F) | seventeen words, the next opcode on the sixteenth | 48 / 48 |
| NEG [BW+d16] (F7 /3) | `P . . . B Y P P2 . DZ G N .` | 19 / 24 |
| LAHF (9F) | `N . .` | 14 / 24 |
| CVTBD (D4 0A) | not fitted (the immediate is taken by the third or fourth word; about 29 words) | 0 / 24 |

LAHF is three words in 14 runs and four in the rest (the X;SHL and X;X variants); NEG with a
displacement misses the NOP;X;SHL variant. Neither followed up.
