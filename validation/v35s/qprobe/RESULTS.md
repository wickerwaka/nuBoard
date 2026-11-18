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

# Round 16

790 socket runs in two acquisitions (`r16a` 774 form probes, `r16e` 16 interrupt probes), each
run twice; 0 failed; 93 repeats flagged DIFFERS, every one strobe-only (compared field by field,
start and end normalised by the repeat's shift). All 790 programs reached their end in the RTL
simulation first. The board ended powered down (status query: vccb false, failure 0). No FF10h
write and no pin stimulus other than round 14's INTP0 schedule in `r16e`.

Model (`model_m.py`): rounds 1 to 15 forms **10,175 of 10,700** (was 10,073: 105 gained, 3
lost: `QPr5-em2-test1-pE-w2`, `QPr8-em3-test1-pE-w2`, `QPr8-em3-rol4-pE-w2`, all "MOV BW,imm16 ;
0F form" at even alignment and two waits); round 16 forms **761 of 774**. Pass set:
`build/qp/r10/r16final.txt`; failing stems `traces/logs/fail-final.txt`.

Scope covered: item 1 except CVTBD (not attempted) and NEG [BW+d16] (a fact, no shape); item 2:
the two RTL diagnoses, and new data on ADD [d16],imm8 (no rule); CALL far with waits and OUTM
twice were **not** re-probed; item 3: the EI outliers only; item 4: no replay (the worktree's RTL
is still the 6+7 copy), round 14's rows re-classified with this round's model.

Note for the reader: `validation/v35s/qprobe/RESULTS.md` named in the hand-over does not exist
in the worktree; this file (and its predecessors under `r15/`, `r14/`) is the cumulative record.

## Q61. The 0F page: the ModR/M byte leaves on a bus-idle third word (one fact, all forms)

Probes `ph-<pred>-<form>` (288 runs): pred ; X ; SHL AW,CL with six predecessors (NOP, CLC, CLC
CLC, NOP CLC, NOP NOP, MOV AW,BW), which put the fetch started by the predecessor's pops on a
different clock of X in each. With rounds 9 and 12's probes of the same forms.

What rounds 9 to 15 had as "the NOP ; X ; SHL variant misses at even alignment with waits" (19
forms, 38 runs) and "TEST1 r,imm twice" (Q48) is one thing: **the third word of every 0F
instruction, the one that releases the ModR/M byte, waits while a fetch's pin cycle runs** (a B
word). From a full queue no fetch is in flight on that clock, which is why the `-a` and `-s`
probes never showed it. With it the routines are:

| form | routine (was) | score |
|---|---|---|
| TEST1 / SET1 / NOT1 r,CL (0F 10 / 11 / 14-17, register) | `P . BP . . CN .` (`P . P . . CN .`) | 198 of 204 with CLR1 and the round-5 / 8 trains |
| CLR1 r,CL (0F 12 / 13) | `P . BP . . CN . .` | (in the row above) |
| TEST1 / SET1 / NOT1 r,imm (0F 18 / 19 / 1C-1F) | `P . BP . CPN .` (`P . P . . CPN .`: **one word shorter**) | 108 / 108 |
| CLR1 r,imm (0F 1A / 1B) | `P . BP . CPN . .` | 24 / 24 |
| ROL4 r (0F 28) | `P . BP . C`, ten words, `N .` (17 words; was 18) | 81 / 84 |
| ROR4 r (0F 2A) | `P . BP . C`, fourteen words, `N .` (21 words; was 22) | 24 / 24 |
| TEST1 m,CL (0F 10 / 11 memory) | `P . BP . . C Y DN .` (`P . P . C Y DN .`: **one word longer**) | 156 / 156 with the two rows below |
| SET1 / NOT1 m,CL | `P . BP . . C Y DZ G N .` | |
| CLR1 m,CL | `P . BP . . C Y D Z G N .` | |
| TEST1 / SET1 / CLR1 / NOT1 m,imm, ROL4 / ROR4 m | unchanged (`P . PC Y D...`: the third word was already the bus-idle commit word) | 264 / 264 |
| EXT / INS r,r | head `P . BP . C . Y D` (`P . P . . C . Y D`) | 204 / 204 (Q62) |
| EXT / INS r,imm4 | head `P . BP . C . . Y D` (`P . P . . C . . Y D`) | 365 / 372 |

- How it was read: behind NOP at even alignment the 0F byte's boundary falls on a fetch's last
  clock and a fetch is chained on the instruction's first clock (cycle E+1 to E+3+w). Silicon's
  later events are 2 / 3 clocks late for the r,CL forms and 1 / 2 for the r,imm forms at W = 1 /
  2 against the old shapes. A wait on word 3 until the clock after the fetch gives the CL forms
  directly; the imm, ROL4 and EXT forms then fit only with one word fewer in front of the
  commit word. That shorter shape is confirmed where nothing waits (behind CLC CLC, NOP CLC,
  NOP NOP at even alignment the next pop is 5 clocks after the boundary, not 6: 28 runs) and it
  is what Q48 saw as "TEST1 r,imm twice, one clock early" (12 runs, now exact).
- The memory CL forms in the same frames are 2 / 3 / 3 clocks late (W = 0 / 1 / 2) against the
  old shape and 1 clock late where no fetch runs: one more word in front of the commit word,
  and the same third-word wait.
- **Verified**: every score above; no run of rounds 1 to 15 is lost except the three named at
  the top. **Not separable in this data**: for the r,CL forms a wait of the boundary's kind on
  word 2 scores the same as the bus-idle word 3 (on rounds 1 to 15 and the first two wait settings of this round; not re-scored on the final set); word 3 is kept because it is
  one description for the whole page.
- Tested and not kept: a word that waits as a boundary does on word 3 of the imm forms (`act
  H`: +20, but leaves the 40 "one clock early" runs); the 0F byte as a two-word routine of its
  own with a second boundary (`OF2`: right for the r,CL forms only, 601 runs lost elsewhere).
- Left open: EXT r,imm4 behind CLC CLC / NOP CLC / NOP NOP at even alignment is one clock early
  (7 runs; EXT r,r in the same frames is exact); the three lost runs behind MOV BW,imm16.

## Q62. EXT / INS with the count in a register (the corpus forms)

Probes `xd-*` (120 runs): EXT BL,DH / DL,DH / DL,BH and INS BL,DH / DL,BH with DW = 0608h (the
corpus's values), each alone, before a long shift, twice, and behind NOP; marker OUT imm8.

- **120 of 120** with the register-count routines of round 12 and Q61's head. The length is the
  reg-field register's low nibble + 1 and the offset the r/m register's low nibble, whatever
  the registers; nothing depends on which register holds them.
- **The offset register is left at offset + length** (mod 16). That, and not a timing effect,
  is why `ext-2` / `ins-2` / `exti-2` / `insi-2` of round 9 were 0 of 6 each: the second
  instance runs at another offset (and, with the count in AL, EXT reloads AL). With the update
  in the model all four are 6 of 6, and X ; X here (same length twice, offsets 0 then 7, 8 then
  15, 8 then 1 with the word crossed) is 30 of 30. The crossing case of EXT DL,DH twice (offset
  15, length 7) uses round 13's across-a-word routine unchanged.
- So the "frame that does not chain the counts" needed no new rule. Corpus rows ext_bl_dh,
  ext_dl_dh, ext_dl_bh, ins_bl_dh, ins_dl_bh (360 diverging runs) are read.

## Q63. MUL / DIV on memory in a clean frame

Probes `mq-*` (144 runs): the operand stored before M0, then MOV AW,5 ; X (; SHL) and MOV AW,5 ;
NOP ; X ; SHL for the eight forms F6 / F7 /4 to /7 [BW], DW = 0.

- **144 of 144** with Q42's routine (`P . B Y D`, the register form's length in all). Nothing
  new about the instruction.
- Round 12's 48 misses (`mm-*`, even alignment, W = 1 / 2) are all in front of the MUL / DIV:
  in MOV [BW],imm16 ; MOV AW,imm16 ; MOV DW,imm16 the fetch of +14 starts 4 clocks later on
  silicon, and everything after it is shifted by exactly that. Two readings fit those runs and
  were not separated: MOV AW,imm16's pop word loses to the fetch chained behind the post-write
  fetch, or MOV [BW],imm16's boundary is taken one fetch later. The first as a general rule
  (`B_CH`: a bus-idle word waits when a fetch chained behind a post-write fetch starts on its
  clock) gains 0 and loses 172: **rejected**. Open; it is Q42's residue (`fw-c7-*-ri`).
- By tab12's 90 % rule the corpus rows mulu_m, divu_m, mul_m, div_m and the byte forms stay
  "partly read" because round 12's runs are counted with these; the routine itself is read.

## Q64. INT 3 and BRK imm8 behind other instructions

Probes `i3-*`, `bk-*` (96 runs): vector stored before M0; the instruction behind nothing, NOP,
CLC, NOP NOP; 0 or 1 NOP at the handler.

- **96 of 96** with round 13's routines (INT 3: bus-idle words 3 and 5, first vector read 12
  clocks after the boundary; BRK imm8: its byte on the bus-idle fourth word). No lead beyond
  Q22's, no dependence on the predecessor.
- The remainder of rounds 8 and 12 (`fl-int3`, `ld-int3`, `tr-brk`: 7 runs at even alignment,
  W = 0) is the two vector stores in the body: the second store's write comes one chained fetch
  later on silicon (100 against 97), before INT 3 starts. Q33's residue, not the transfer's.

## Q65. CALL / JMP through a direct word

Probes `cm-*`, `jm-*` (96 runs): pointer stored before M0; FF /2 and FF /4 with mod 00 r/m 110
behind nothing, NOP, CLC, NOP NOP; 0 or 1 NOP at the target.

| instruction | routine (was) | score |
|---|---|---|
| JMP [d16] (FF 26) | `P . B Y . PP2 D . . F N .` (`P PP2 B Y D . . F N .`) | 48 / 48, and 10 / 12 of round 12's |
| CALL [d16] (FF 16) | `P . B Y . PP2 D . . . Z D . . F N .` | 48 / 48, and 10 / 12 of round 12's |

- Round 12's shapes were read behind MOV [d16],imm16 in the body and were wrong: 0 of 96 here.
  The displacement leaves on the sixth word (two bytes at once), after the request word; the
  third word is bus-idle as in every FF-group member (Q27 / Q47). JMP far [d16] (Q44) differs
  only in the request's place (`P . B . Y PP2`); not re-probed.
- The four round-12 misses (odd alignment, W = 0) are again the store in front.
- Corpus row call_m_dir (96 runs) is read.

## Q66. LAHF, NEG [BW+d16], ADD [d16],imm8 three times; CVTBD not attempted

- **LAHF is `N .`** (CLC's routine), not `N . .`: 42 of 42 (round 15's 24 and `la-*`: behind
  CLC, behind two NOPs, three in a row). Round 15's "three words in 14 runs and four in the
  rest" was the third word hiding under a boundary wait.
- **NEG [BW+d16]**: still 19 of 24 (the five misses are all W = 0). The fact: with the bus idle
  the second displacement byte leaves 7 clocks after the boundary and the read starts 10 after;
  the shape that fits W = 1 / 2 has the byte 8 after with the request word in the same place. No single shape gives both;
  ten tried (`build/qp/tryshapes.py NEGD16 negd16 ...`). Open.
- **ADD [d16],imm8 three times** (`a3-3`, 0 of 6; with a NOP between, `a3-n`, 6 of 6). What Q48
  called "twice at even alignment" is not about the alignment or the second instance: the read
  comes one chained fetch late on the **second instance at even and the third at odd
  alignment**, and on time on the third at even and the second at odd. In the model's terms
  those are the instances whose boundary finds four bytes held (five in the on-time ones). A
  byte-count condition at the boundary (`EMIN_K=5`) gains 0 and loses 6: rejected. Open, with
  that description.
- CVTBD: not attempted this round (round 15's 24 runs, 0 fitted). OUTM twice, CALL far with
  waits: not re-probed.

## Q67. The EI outliers

`r16e` (16 runs): round 14's two outliers at all three waits, and with INC BW in place of the
CLCs in front of the EI.

| program | W = 0 | W = 1 | W = 2 |
|---|---|---|---|
| level 0, 6 CLCs, even | 6 NOPs after EI (16 clocks late), as round 14 | 2 (normal) | 2 |
| level 0, 6 CLCs, odd | 2 | 2 | 2 |
| level 5, 10 CLCs, odd | 2 NOPs (16 early), as round 14 | 5 (normal) | **2 (16 early)** |
| level 5, 10 CLCs, even | 4 | 5 | 4 |

- Both reproduce to the clock, and INC BW in place of CLC (the same clocks) gives the same
  result at both alignments: the cause is in the clocks, not in the instruction.
- A third outlier: level 5, 10 CLCs, odd, W = 2.
- A wait changes the outcome, so "EI restarts the scan" (Q49) is not the whole rule: when the
  EI falls at certain clocks the request is found a round early or late. With four outlier positions in about 210 EI runs there is no rule; the table is the test for one.

## The corpus split with this round's model

No replay (the RTL in the worktree is the unlanded 6+7 copy with its known REP MOVBK fault);
round 14's rows (`fd14-tab11.json`, 10,017 diverging runs filed) re-classified by
`build/qp/tab12.py` with the round-16 model and small set:

| cause | model status | round 14 | now |
|---|---|---|---|
| own + other | read | 8,610 | 9,553 |
| own + other | partly read | 1,096 | 344 |
| own + other | not probed | 299 | 90 |
| own + other | probed, not read | 12 | 30 |

(Round 15's reads account for 132 of the move out of "not probed"; cvtbd moved to "probed, not
read".) Partly read now: mulu_m 102, divu_m 48, mul_m 36, div_m 30, mulub_m 18 and the other
byte forms (Q63: the routine is read, the old frame's runs keep the signature under 90 %),
lds_aw_ix 36 (the LDS ; LDS probe loads DS0: a probe artefact, Q46), neg_m_bw_d16 21,
mul_aw_cw_imm8 18 (MUL r,r,imm8 at two waits), the far transfers' rows 21.

# Round 17

Socket runs: see the table at the end of this round (every run with its repeat; 0 failed; the
repeats flagged DIFFERS compared field by field: strobe field only). The RTL in the worktree is
now the work-order 10 to 12 tree (copied from main's working tree, 77 files, `uasm --check`
clean, sim rebuilt, the small set re-simulated, the corpus replayed once): the build check and
the split are in `build-check.md` and `divergence-notes.md`.

Clock convention for the interrupt items of this round: e is the clock (from M0) at which the
stimulus edge is scheduled at the pin, `event record's end + delay + 4 ticks`, 8 ticks a clock,
as in rounds 12 to 16; the edges were stepped a quarter clock (2 ticks) at a time, so a
threshold "x.875" means "taken at x.75, not at x + 1.0". The absolute constant (harness output
delay, the event record's own latency) is not known to better than half a clock; differences
between pins and between programs are exact.

## Q68. LEA per addressing mode: five words in every mode; the displacement leaves on the last-but-one word

Probes `QPr17a` (576 runs): twelve modes ([BW], [BW+IX], [BP+IY], [IX]; the same four kinds with
d8; [BW+d16], [BP+d16], [BW+IX+d16]; direct), each behind INC / CBW / NOP / CLC (round 8's lead
frame) and as the four probe programs (alone, in front of a long shift, twice, behind a NOP).
Shapes enumerated per mode (`build/qp/lea17.py`: the displacement's word, the next opcode's
word, a bus-idle wait on either, one or two words behind; 48 runs a mode):

| mode | routine | score |
|---|---|---|
| no displacement, one or two registers | `P . . BN .` | 192 / 192 (next best 34 / 48) |
| d8, one or two registers | `P . . BNP .` | 192 / 192 (next best without the wait 42 / 48) |
| d16 on one register, direct | `P . . BNPP2 .` | 144 / 144 |
| [BW+IX+d16] (two registers and d16) | `P . . . BNPP2 .` | 48 / 48 (the five-word shape 26 / 48) |

- **The length does not depend on the displacement.** The displacement bytes are not taken on
  words of their own: they leave the queue on the bus-idle fourth word, with the next opcode.
  (For d16 on one register the probes do not separate "released on the fourth word" from
  "released on a word of their own in front of an unwaited N": `P . . PP2 N .` is also 48 / 48
  at six words; the d8 modes do separate them, 38 / 48, and the five-word form is the one rule
  that covers every row.)
- **Two registers and a d16 cost one more word** in front of the release word, as round 8 read
  for MOV r,[BW+IX+d16] (`L_A2X`). Two registers with d8 or with nothing do not.
- Spec 12 C2 ("one more word and bi", read from [BW] alone) is right for the modes without a
  displacement and wrong as a rule for the others: the builder's EA heads already spend a word
  per displacement path, so the extra word made those six long.

The model: keys `LEA`, `LEAX`, `LEA_D8`, `LEAX_D8`, `LEA_D16`, `LEAX_D16`, `LEA_DIR`
(`model_m.info`, op 8D). 576 / 576, and round 8's `ld-lea` 18 / 18 unchanged.

## Q69. The 81 / 83 group on memory with a displacement; Q33's rule is not about the write's datum

Probes `QPr17b` (288 runs; the corpus's add_m_imm_d16 / add_m_imm_dir / the F22 d16 forms had no
probe of their own). Six forms in the lead frame and the four probe programs. The lead frame's
INC here was INC BW, which makes [BW+d] an odd address: those 24 runs show Q32's double cycle
and are a probe artefact for the shapes (the direct-address forms are not affected).

| form | routine | score (artefact runs left out) |
|---|---|---|
| ADD word [BW+d8],imm16 (81 /0, mod 01) | `P . . BYP DPP2Z G N .` | 42 / 42 |
| ADD word [BW+d16],imm16; [d16],imm16 | `P . . BYPP2 DPP2Z G N .` | 41 / 42, 47 / 48 with the rule below (31 / 42 without) |
| CMP word [BW+d16],imm16; [d16],imm16 (81 /7) | `P . . BYPP2 DPP2 . BN .` | 42 / 42, 48 / 48 with the rule (31 / 42 without) |
| ADD word [BW+d16],imm8 (83 /0, mod 10) | `P . V PP2 DPZ G N .` (the direct form's, round 9) | 39 / 42 |

- **The d16 / direct forms of 81 obey Q33's table, and they are reads.** With the request word
  at b+4 (it releases the displacement, which starts a fetch on the same clock) the read is at
  b+8 at W = 0 with no chained fetch in front of it, and at W = 1 / 2 the chained fetch goes
  first (fetch b+8 / b+9, read b+12 / b+14): the three columns of Q33's second row, to the
  clock. Q33 explained that row by the write's datum ("a posted write whose datum has not been
  taken does not compete", the K word). A read has no datum to wait for, so that is not the
  reason. What the two routines share is the request word: **a request made on the word that
  releases the displacement competes for the bus only from its due clock (request word + 4);
  until then a chained fetch that the count allows goes first, and a request made on the
  decision's eve still holds that decision** (Q33 facts 1 and 2 unchanged; fact 3 restated).
  The machine reading: the request is posted before the address exists (the displacement
  bytes leave the queue on that very word and the EA's add takes the words between), so it
  cannot start; it can only reserve.
- In the model: `YP_UN=1` (a read whose request word carries B and a P is treated as Q33
  treats the unarmed write, armed at its due clock) and `ARB_K="WR"`. Over rounds 8 to 17b:
  8,286 of 8,496 with it, 8,244 without, **0 runs lost in any round** (`build/qp/r17/ypun.txt`,
  `fail-17b.txt`). Whether the condition is "releases a displacement" or "any bus-idle request
  word" cannot be told from the small set (`YP_UN=2`: the same 8,286): no probe has a
  bus-idle read request with no displacement and a chained fetch pending at its due clock.
- Still open here: the second instance of the d16 forms at odd alignment, W = 0 (2 runs) and
  ADD [BW+d16],imm8 twice at even alignment (3 runs): Q66's "four bytes held" family.

## Q70. CVTBD

`QPr15a-cvtbd` (24) and `QPr17d` (42: behind INC, CBW, NOP, CLC, two NOPs, two CLCs, MOV
BW,imm16; a long shift behind). **`. . . P . B . . . . . . . . . . . . . N .`**: 21 words, the
operand byte on the fourth, a bus-idle sixth word, the next opcode on the twentieth. 63 of 66
(round 15's 24 of 24; the 22-word alternative that also fitted round 15 is 59 of 66). The three
misses are `cv-cvtbd-r` (behind MOV BW,imm16) at W = 1 odd and W = 2 both alignments: not read.

## Q71. The pins' front ends: pulse widths, polarity, sampling instants

`r17wn`, `r17wp`, `r17wi` (968 runs): a pulse of 0.25 to 4 clocks at 16 quarter-clock positions
(INT: 0.5 to 3 clocks at half-clock positions) in front of the NOP train. `r17n`, `r17p`,
`r17i`, `r17nr`, `r17pr` (440 runs): the edge stepped a quarter clock at a time across the NOP
train, falling and (INTM = 05h, the pin pulled low 25 clocks earlier) rising. Table:
`build/qp/r17int.py <round>`.

| pin | pulse seen | threshold phase | rising against falling |
|---|---|---|---|
| INTP0 | never at <= 1.0 clock; at 1.25 / 1.5 / 1.75 clocks only when it starts at phase .75 / .5 or .75 / .25 to .75; always at >= 2.0. The pattern repeats every clock, the same at both alignments | x.875 | identical to the quarter clock (thresholds 71.875 / 87.875 even, 72.875 / 88.875 odd, both polarities); the first edge of the wrong polarity does nothing |
| INT | never at <= 1.0; at 1.5 clocks only from phase .5; always at >= 2.0 | x.875 | (level, high) |
| NMI | never at <= 1.75 clocks at any of the 16 positions; always at >= 2.0 | x.125 | identical to the quarter clock (69.125, 71.125, 75.125, 79.125 both) |

- **INTP0 and INT are sampled every clock, and a level counts when two consecutive samples
  hold it.** A pulse that starts at phase p is seen exactly when its width exceeds 1.875 - p:
  two samples one clock apart at phase .875. This is not "sampled every second clock" (Q53):
  the 2-clock lattice of Q53 is downstream of the sampler (Q72).
- **NMI is not filtered by a clocked sampler.** The limit between 1.75 and 2.0 clocks does not
  move with the phase at all (a two- or three-sample rule would pass some 1.25 to 1.75 pulses
  or fail some 2.0 ones). It is a filter in time (an analogue noise eliminator, or one clocked
  faster than the CPU clock). Its delay is the 0.75 clock (mod 1) by which NMI's threshold
  phase (.125) leads INT's and INTP0's (.875): about 1.75 to 2 clocks. Whether the length is
  a time or a clock count needs a run at another clock frequency; not possible on this board.
- **The edge detectors are symmetric**: same latency for either polarity, to the quarter clock.
- **A short INT pulse is enough when IE = 1.** INT high for 2 clocks is acknowledged in front of
  exactly the instruction a held level with the same rising edge is (200 runs, `r17wi`),
  though the pin is low again 6 to 8 clocks before that instruction's pop. With IE = 0 the
  same pulses are forgotten (EI 25 clocks later: no acknowledge; the held level: acknowledged
  one instruction behind the EI; `r17s`, 16 runs). So the accepted level is not kept in a
  request latch of its own; it is taken, with IE, into the EU's decision within about two
  clocks, and that decision then stands.

## Q72. The INTP0 request flag read by the program: set 4 to 6 clocks after the edge, on the divided clock

`r17f`, `r17g` (452 runs): EXIC0 = 47h (masked), no EI; the body reads EXIC0 and stores the byte
to RAM five times (`MOV AL,DS1:[FF4Ch] ; MOV [BW],AL`, and the same with a CBW in each group so
that successive reads are 25 clocks apart); the edge stepped half a clock at a time. The stored
byte is C7h when the read saw the flag. Two controls with the load reading RAM show the read
cycle on the pins (the fetches around it are identical with the SFR read's).

| alignment | read cycle's first clock (control) | latest edge the read sees | difference |
|---|---|---|---|
| even | 89, 113, 139 | 84.875, 108.875, 134.875 | 4.125 |
| odd | 88, 114, 138 | 82.875, 108.875, 132.875 | 5.125 |

- **The flag is set on a 2-clock lattice**: the reads are 25 clocks apart and the thresholds
  24 and 26. Edges at x.875 with x even set it in time for a read cycle that starts 4.125 (odd
  clock) or 5.125 (even clock) later. This is Q53's lattice: the pin is sampled every clock
  (Q71) but the edge is turned into the flag by a stage on the divided clock.
- **Pin to flag is 4.1 to 6.1 clocks** counted to the reading cycle's first clock (plus
  whatever part of the read cycle passes before the register is sampled: at most 2 clocks; not
  known). A machine that gives this: two samples (1.1 to 2.1 clocks to the accepted level),
  the edge detector and the flag on the divided clock (2 to 4 clocks, by the lattice).
- The RTL has 11 clocks here (`INTP_DLY`). Six of them are not in front of the flag.

## Q73. INT, NMI and INTP0 side by side: how long before the pop

Fine-step probes across trains of NOP (4 clocks), CBW (3), INC AW (2 to 3, fetch-limited):
`r17i/n/p`, `r17q`, `r17r` (812 runs). P = the pop of the first instruction not executed
(vector read - 17 behind INC, - 18 behind CBW, - 19 behind NOP for a vectored source; 4 more
for INT's acknowledge cycle), threshold = the latest edge that is taken in front of it.

| source | NOP train | CBW train | INC train | RTL (same probes, sim) |
|---|---|---|---|---|
| INT | 9.125 (every instruction) | 9.125 (every instruction) | 9.125 (every instruction) | about 0.6 (CBW), under 2.1 (NOP) |
| NMI | 14.875 (first), then 16.875 | 13.875 (first), then 14.875 | 13.875 and 14.875; one of every four instructions is never the take point | 11.6 (CBW) |
| INTP0, level 7, the scan's latest edge | 20.1 / 19.1 (even / odd) | 17.1 / 16.1 | 16.1 / 17.1 | CBW 17.5 / 18.5; NOP 16.5 / 18.5 |

- **INT needs 9.125 clocks to the pop, in every train, at every instruction, both
  alignments**: a path of fixed length in clocks, made every clock (the thresholds step by 3
  in the CBW train). About 1.1 to 2.1 of it is the two-sample acceptance; the other 7 to 8
  clocks are between the accepted level and the pop of the instruction it replaces. The RTL
  takes INT straight to the EU: 8.5 clocks sooner. **The 7 to 8 clocks are a property of the
  EU's decision, common to every source, and it is not in the RTL**; the RTL's `NMI_DLY` (10)
  and `INTP_DLY` (11) each hold a copy of it.
- **NMI is 4.75 to 5.75 clocks behind INT** (7.75 in the NOP train): 1.75 to 2 of filter
  (Q71), 3 to 4 more, and a part that depends on the bus: in the INC train an NMI is never
  taken in front of the instructions whose pop falls in one particular place of the 10-clock
  fetch pattern (x5, x9 at even alignment, x2, x6, x10 at odd: the edges that would select them
  go to the next one), and INT on the
  same train has no such gaps. Something between the NMI's edge detector and the EU waits
  for the bus unit. What: not read.
- **INTP0 at the scan's latest edge is 7 to 8 clocks behind INT** (16.1 to 17.1 to the pop
  where boundaries are dense). Of these, pin to flag is 4.1 to 6.1 (Q72), of which the
  acceptance (1.1 to 2.1) is INT's too; so from the flag at the scan's level-7 point to the
  point where an accepted INT level stands is about 3 to 5 clocks: the scan's compare and
  the passage on the divided clock (the RTL's `ird`, 3 to 4 clocks, is the right size).
- The absolute constant in these figures (harness edge to pin) is the same for all three pins
  to within the quarter-clock steps: all three are driven by the same schedule.

## Q74. HALT: the release is on a 2-clock lattice for NMI and for INT

`r17h` (64 runs): the edge 20 clocks into the HALT, a quarter clock at a time. The vector read
moves 2 clocks for every 2 clocks of edge: INT thresholds 90.875, 92.875 (vector read 36.1 to
38.1 clocks after the edge), NMI 90.125, 92.125 (32.9 to 34.9), the same at both alignments.
In the trains the same pins are taken every clock (Q73: NMI thresholds at odd x there, even x
here), so the lattice is the release's, not the samplers': the stopped EU is restarted by
something that runs every second clock (the divided clock of Q72, or a two-word wait loop).
The RTL releases every clock, INT 12 clocks sooner than silicon (24.6 after the edge) and NMI
2 sooner (31.6).

## Round 17 in numbers

| round | what | runs | flagged repeats (all strobe-only) |
|---|---|---|---|
| r17a | LEA, twelve modes | 576 | 47 |
| r17b | 81 / 83 group with a displacement | 288 | 69 |
| r17d | CVTBD | 42 | 5 |
| r17i, r17n, r17p | INT / NMI / INTP0, quarter-clock edge, NOP train | 80, 96, 84 | 0, 22, 19 |
| r17nr, r17pr | the same, rising edge selected | 96, 84 | 20, 28 |
| r17wn, r17wp, r17wi | pulse widths | 384, 384, 200 | 93, 131, 115 |
| r17f, r17g | the request flag read by the program | 192, 260 | 56, 94 |
| r17h | NMI / INT into HALT | 64 | 18 |
| r17q, r17r | the three sources across INC and CBW trains | 276, 276 | 94, 98 |
| r17s | INT pulse behind IE = 0 | 16 | 8 |

3,398 runs, each run twice, 0 failed, 0 incomplete; 917 repeats flagged DIFFERS, every one
differing in the strobe field only (`build/qp/repdiff.py`, `build/qp/r17/repdiff-*.txt`).
FF10h was written only by the INT rounds (`r17i`, `r17wi`, `r17h`, `r17q`, `r17r`, `r17s`),
with gen_r15's INT_HEAD / hand-back sequences; in `r17wi` and `r17s`, where the interrupt may
not be taken, the body ends with the same hand-back sequence so that every run restores the
port bank. The first INT round was run alone and its vector read (0100h) checked first.

The model after this round: 11,834 of 12,396 non-interrupt runs (`build/qp/fail17.py`; was 10,936 of
11,490), no run lost against the round-16 model.

# Round 18

6,036 socket runs in 20 families (table at the end), each run twice, 0 failed, 0 incomplete;
1,849 repeats flagged DIFFERS, every one differing in the strobe field only
(`build/qp/r18/repdiff-18.txt`). Plus 2,880 runs in simulation of the worktree's RTL copy (main
at 2a30b50; not re-based this round). Board powered down at the end (vccb false, failure 0).
All interrupt items: the edge clock e is as in round 17 (`event record's end + delay + 4
ticks`, 8 ticks a clock); edges were stepped half a clock, INT at x.5 and NMI at x.0 / x.5, so
with round 17's phases (INT sampled at x.875, NMI's threshold at x.125) "INT taken up to P - 9.5"
reads as a true threshold of P - 9.125 and "NMI up to P - 9.0" as P - 8.875.

P is the model's staging pop of an instruction (the clock its opcode leaves the queue on an N
word; `model_m` with `NLOG`); "start" is the clock of its first word (`BLOG`, added this round).
Tools: `build/qp/r18int.py` (thresholds per pushed instruction), `fit18.py` (rules scored on
every run), `dump18.py` (pops, starts and thresholds of one train).

## Q75. INT: the request is taken by the first pop at least 9.125 clocks after the edge, whatever the EU and the bus are doing

`r18tnop1/2`, `r18tinc1/2` (NOP and INC BW trains at W = 1, 2), `r18tmi80`, `r18tmi160` (MOV
r8,imm8 and MOV r16,imm16 trains: pops 5 to 7 clocks apart, on a bus-idle fourth / fifth word),
`r18tld0` (MOV AW,[BW]: a read cycle per instruction), `r18tmul0` (MULU BW, 35 clocks),
`r18tshl0` (SHL AW,CL with CL = 31, 76 clocks: a microcode loop), `r18tmm0/2` (a mix of INC, NOP,
CBW, MOV r,imm8 / imm16 at W = 0 and 2), with round 17's CBW train.

- **One rule, 1,760 of 1,760 runs: the instruction pushed is the one whose pop is the first at
  or after e + 9.125.** The next best cell of the grid (lead 0 to 20 clocks, a second stage of 0 to
  12 clocks, pops or instruction starts as the anchor) is a lead half a clock off, at 88 %. The lead is the same at
  W = 0, 1, 2, with pops 2 to 10 clocks apart, across a read cycle per instruction, and inside
  MULU and the 76-clock shift (the pop made by the long instruction's own N word, 35 and 76
  clocks after the pop before it, is replaced for exactly the edges up to 9.125 before it).
- So the 7 to 8 clocks behind the two samples are **not** a microcode sample point a fixed
  number of words in front of the pop (the shift's loop cannot know it is 7 words from its end),
  **not** on the divided clock (round 17: thresholds step with every clock), not a bus or queue
  synchronisation (W, fetch pattern and EU cycles do not move it). It is a fixed number of
  CPU clocks between the accepted level and a level at the loader that the next pop reads.
- **Behind a flush the pop that counts is late.** `r18tjmp0` (one JMP $+2 in a NOP train),
  `r18tjch0` (eight in a row): the edge is taken in front of the first jump's target up to 6
  clocks later than the model's nominal pop of the target allows: the threshold is 11.5 clocks
  before the last word in front of the target (four thresholds: two families, two alignments;
  with the nominal pops the rule scores 150 of 168 and 168 of 192, every miss in front of a
  target). The model stages the target as soon as its byte arrives and holds the boundary until
  two more bytes are in (`EMIN`); for the interrupt the opcode leaves the queue 2 clocks before
  that last word. Read from the first target of each program only (the windows end there).
  `r18tjch2` (W = 2): 186 of 216 with the nominal pops, not looked at further.
- The vector read follows the replaced pop by 21 to 23 clocks (INTAK first), as round 15.

## Q76. NMI: stands at the EU 8.875 clocks after the edge, like INT; then a second stage that INT does not have

The same families, NMI beside INT.

- **Opcode-only trains** (NOP at W = 0, 1, 2; INC at W = 1, 2; CBW; MOV r8,imm8; MOV
  r16,imm16): one two-stage rule reproduces every run except the first two instructions behind
  the frame's long shift (806 of 856; the 50 are those). (1) S = the first pop at or after
  e + 8.875. (2) The pop replaced is the first one at least 5 clocks after S that is not made
  on the first word of the instruction S took out of the queue. In a NOP train that is the
  second pop behind S (round 14's "the pop that matters is one instruction earlier", Q54, and
  round 17's "4.75 to 7.75 behind INT" are this); in the INC train it makes one instruction in
  four unreachable (round 17's gaps: no bus dependence is needed for them); in the MOV r8,imm8
  train (pops 5 or 6 apart on a fourth word) it is the next pop. "At least 6 clocks, any pop"
  is 762 of 856 (it fails the 5-clock steps of MOV r8,imm8).
- **Stage 1 is INT's.** 8.875 against 9.125, of which the filter is 1.75 to 1.875 (Q77) where
  INT has its two samples (1.1 to 2.1): the same 7 clocks behind the front end.
- **The rule does not hold where the EU makes bus cycles or runs long** (404 of the other 904
  runs differ, always silicon earlier than the rule):

  | context (even alignment) | the pop replaced comes this long after e + 8.875, with no pop in between |
  |---|---|
  | MOV AW,[BW] train (pops 10 apart, on the datum word of a read) | 3 clocks |
  | first instruction behind the frame's long shift | 5 |
  | behind SHL AW,CL (76 clocks): the shift's own pop / the pop after | 5 / 6 |
  | behind MULU BW: MULU's own pop / the pop after | 7 / 5 |
  | first jump's target (JMP $+2) | 6 from the nominal pop |
  | mixed train: the pop behind MOV r16,imm16 | 7 (rule: 10 or more) |

  So the second stage is armed by something other than a pop when there is no pop, and can
  then end 3 clocks later. What arms it (a microcode word kind, the bus unit's state at a
  cycle's start, both): **not read**. The table is the data for whoever continues.
- From the replaced pop to the vector read: 17 to 19 clocks, as before.

## Q77. NMI's filter to an eighth of a clock

`r18w` (96 runs): NMI low for 14, 15, 16 ticks at 16 consecutive tick positions (the schedule's
resolution is one tick, an eighth of a CPU clock, a quarter of the oscillator period). 14 ticks
(1.75 clocks): never taken, 32 of 32. 15 ticks (1.875): always, 32 of 32. 16: always. The limit
is between 1.75 and 1.875 clocks and does not move with the phase at this resolution, and both
repeats agree on every run. A count on the CPU clock or on the oscillator (two edges a clock)
would pass some 1.75 pulses or fail some 1.875 ones; this is a time (or a count on a clock at
least eight times the CPU clock, which the chip does not have). Whether it tracks the clock
frequency still needs another oscillator.

## Q78. The scan against EI and against a store to the request register

`r18f` (304 runs): INTP0 unmasked at level 7, IE = 0; the body reads EXIC0 and stores the byte
twice, then EI (with and without a CBW in front), then six more read / store pairs; the edge a
clock at a time. `r18s` (92 runs): EI, a pad of 0 to 24 clocks (NOP / CBW / CLC), `ES: MOV byte
[EXIC0],87h`, NOPs; and the same with the store going to RAM, which shows the write cycle.

- **The 16-clock grid is locked to EI.** The latest edge acknowledged in the first round is
  137.5 without the CBW and 140.5 with it (EI 3 clocks later), at both alignments; the next
  cut is 16 later in each (153.5, 156.5). Any edge up to the cut, however long before the EI,
  is acknowledged at one fixed clock (vector read 37.5 after the cut-off edge in this train).
- **The scan's look at level 7 is 4 clocks earlier than a program's read of the same flag
  would have to be.** The read behind the EI stores the flag as set for edges up to 141.5
  (144.5 with the CBW): for edges 138.5 to 141.5 the program sees the flag set and the scan of
  that round has already missed it. With round 17's pin-to-flag figure the level-7 look is at
  about the clock a read cycle starting at 142 would sample, i.e. about 19 clocks after EI's
  start and 6 after its end (EI's start is placed from the store's write cycle in front of
  it, to 2 clocks: **inferred**; the model does not know the body's MOV AL,[d16]). So EI
  restarts the scan from one of its early words, not its last (spec 13's inference, now with
  a measurement behind it).
- **A store to the request control register restarts the scan too.** With the request set by
  the store, the vector read is 50 clocks after the store's write cycle at every one of the 23
  pads, both alignments (46 of 46): no 16-clock steps at all as the store moves through 24
  clocks behind the EI. A free-running round would give steps. 50 = 3 (the cycle) + 14 (levels
  0 to 7) + 33 (level-7 look to vector read, as in `r18f`: 32 to 33). The arithmetic is
  consistent; that it is a restart, and from level 0, is **inferred** from it.

## Q79. Q69's reserving request: no probe can separate the two readings

The candidates for "a bus-idle request word that releases no displacement" in the model's
tables are `BY` words: ADD / CMP word [BW],imm16, C7 [BW], MUL r,[BW],imm16. For the two reads,
behind every one of 156 predecessor pairs (NOP, INC, CBW, CLC, MOV r,imm8 / imm16, JMP, a
load, a store, PUSH, XCHG, MULU), three waits, both alignments, the model's prediction with
`YP_UN=1` (only a word that releases a displacement) and `YP_UN=2` (any bus-idle request word)
is the same trace on all 1,872 runs (`build/qp/yp18.py sim18`). The reason is structural: a
bus-idle word executes only when the bus unit has no fetch sequenced, a new fetch needs a pop,
and between such a request word and its datum word nothing is popped; only a request word
that itself releases bytes can have a fetch start under it. **In the model's terms the two
readings are the same machine**; nothing was acquired for this item. (Model-derived, not a
silicon measurement.)

## Q80. The REP compares over data that ends the loop anywhere

`r18c` (768 runs): REPE / REPNE / REPNC / REPC with CMPBK and CMPM, byte and word, CW = 4, over
data that satisfies the exit condition at element 1, 2, 3, 4 or never; alone and with a shift
by CL behind (its length shows the count left). Rounds 9 to 13 had only "never" and "at the
first element". Table: `build/qp/rc18.py`.

- **One loop for all eight forms and all four prefixes.** The prefix only selects the flag
  tested (Z or CY, and its sense); byte and word differ by nothing at even addresses.
- **k elements compared, k + 1 read**, in every case: ended by the condition at element k
  (k = 1 to 4) or by the count (k = 4). CMPBK: 2 (k + 1) reads 9 clocks apart at W = 0; CMPM:
  k + 1 reads, the second 10 clocks after the first and every later one 12 after the one
  before (rounds 9 / 13 read "10 when the condition ends it, 12 to the count": it is "10 once,
  then 12", whatever ends it).
- **The count left is CW - k** (shift lengths 19, 17, 15, 11 for k = 1 to 4: 13 + 2 CL, and
  the two-word-shorter CL = 0 form).
- **The exit:** from the last read to the marker 26 clocks when the condition ended it (also
  when that was at the last element) and 27 when the count ended it with the condition still
  holding. One word, by which exit.
- At W = 2 the same with each cycle's waits (reads 11 apart, CMPM 12 then 14).
- The RTL copy makes the same number of reads in all 768 runs. At W = 0 (both alignments)
  the spacing is silicon's, its first read is one clock early (head one word short) and its
  exit is the same length on both paths (one word long on the count exit, two on the
  condition exit). At W = 2 the first read is 1 to 3 clocks early and the spacing differs in
  28 of the 64 programs of each alignment; not diagnosed. The model as it stands reproduces only the two data shapes it was read from (144 of
  768): its REP compare code takes the element count from the prefix, not from the data. Not
  generalised this round.

## Q81. Two corpus rows diagnosed

- **set1_rw_cl (156 corpus runs).** `r18b` (180 runs): SET1 AW,CL with CL = 0, 1, 2, 3, 7, 8,
  15, 16, 31, alone, twice, behind OUT; SET1 AL,CL at the same nine counts; TEST1 / CLR1 / NOT1
  word at three. Silicon: **the word forms are the byte forms' routine, and no length depends on
  CL** (model 177 of 180; the 3 are SET1 word behind OUT at even alignment, silicon 2 clocks
  shorter, not read). The RTL keeps a separate short routine for 0F 15 / 0F 17 on a register
  (`b1sclw_r`, "the round-9 register routine", kept because the byte shape once lost nine F39
  runs): every SET1 / NOT1 word r,CL run differs (0 of 90 in the sim against the model; next
  fetch 10 clocks early at even alignment, the marker 3 early). CLR1 and TEST1 word are right.
- **br_n1 (211).** The corpus sequence is CALL $+5 ; JMP $+3 ; RET executed as CALL, RET, JMP:
  a transfer whose opcode is the first byte behind another transfer's flush. `r18j` (60 runs:
  that sequence alone, behind NOP, behind OUT, twice; JMP behind JMP; JMP behind OUT): model 48
  of 60, **RTL = model on all 60**. The 12: the second transfer at W = 1 and 2 at the alignment
  where the first flush fetch brings its opcode alone. Silicon's second flush fetch starts 8
  clocks after the fetch that brings the displacement ends, at every wait; the model and the
  RTL have 8 - W. JMP behind OUT, behind NOP, and the first transfer are exact. This is one
  shared misreading (the transfer's start against a fetch still in progress behind a flush),
  not an RTL build fault; the corpus count is larger at W = 1 / 2 (197 of 242 by `fd17`) as it
  predicts. The model is not corrected this round.

## Round 18 in numbers

| family | what | runs | flagged repeats (all strobe-only) |
|---|---|---|---|
| r18tnop1, r18tnop2 | INT / NMI across NOPs, W = 1, 2 | 228, 244 | 8, 52 |
| r18tinc1, r18tinc2 | across INC BW, W = 1, 2 | 260, 292 | 71, 99 |
| r18tmi80, r18tmi160 | across MOV r8,imm8 / MOV r16,imm16 | 260, 260 | 71, 83 |
| r18tld0 | across MOV AW,[BW] | 292 | 110 |
| r18tmul0, r18tshl0 | behind MULU BW / SHL AW,CL (31) | 484, 420 | 142, 162 |
| r18tjmp0, r18tjch0, r18tjch2 | behind one jump / eight / eight at W = 2 | 340, 388, 436 | 114, 133, 149 |
| r18tmm0, r18tmm2 | a mixed train, W = 0, 2 | 292, 340 | 97, 122 |
| r18w | NMI widths in eighth-clock steps | 96 | 19 |
| r18f, r18s | flag reads with EI; request set by a store | 304, 92 | 114, 23 |
| r18j, r18b, r18c | transfer pairs; bit forms by CL; REP compares | 60, 180, 768 | 11, 38, 231 |

6,036 runs (5,028 + 1,008), 0 failed, 0 incomplete, 1,849 flagged repeats, all strobe-only.
FF10h was written only by the INT halves of the `r18t*` families, with gen_r15's INT_HEAD and
handler hand-back; the first INT program was run alone and its vector read (0100h) checked.
Scout runs (34, `build/qp/r18/scout`) are not counted. Model change this round: `BLOG` (a log of
instruction starts) only; no rule or shape changed, so round 17's 11,834 of 12,396 stands.


# Round 19

## Q82. NMI and INTP0 occupy the bus unit for two clocks with nothing on the pins; INT does not

Found while reading `r19nld1`: with the NMI edge at some positions a prefetch or an EU cycle of
the train is on the pins 2 to 4 clocks later than in the control run of the same program (the
edge at d2000, never taken), **before** anything of the interrupt is on the bus, and with no
record in between (no strobe, no refresh record). Tools: `build/qp/hs19.py` (table per cycle
kind and distance to the level's arrival), `hd19.py` (is anything displaced), `h19.py` / `ev19.py`
(one program, run beside control).

- **Measured, every NMI family of rounds 17 to 19 (38 families, W = 0, 1, 2; `build/qp/r19/hs-nmi.txt`):** let c be the
  first clock on which the level stands at the EU (the clock containing e + 8.875: stage 4's
  end). A bus cycle of the control whose first pin clock T is before c is never moved. A cycle
  with T = c or c + 1 is moved: an EU read or write by **2 clocks at every wait** (332 of 332
  runs with such a cycle behind an idle bus, and 0 of 163 with T = c + 2), a prefetch from an idle bus in a train with EU cycles by 3 (W = 0: also 4), a prefetch started by a pop by 2 or 4, a prefetch chained behind another cycle by 2 to
  5 (the chain is re-formed). A cycle with T >= c + 2 behind an idle bus is not moved; one
  chained to a cycle that was in flight at c is (the occupation waits for the cycle in flight
  and runs in front of the chained one).
- So **the bus unit is taken for 2 clocks** by something that is not a pin cycle, with
  priority over a cycle that has not reached its first pin clock (also over one already in its
  two set-up clocks, S_LAG), and behind a cycle that has. The EU's cycle keeps its place in
  the queue and starts when the 2 clocks are over; a prefetch is decided again.
- **INT: none.** No cycle is displaced in any INT run of `r18tld0`, `r18tmi80`, `r18tmm0`,
  `r18tnop2`, `r17r` (632 runs; the same trains show it in NMI's half). **INTP0: yes**, in round 17's trains (`r17p`, `r17q`, `r17r`: prefetches 2, 3 and 4
  clocks late 11 to 16 clocks after the edge, 93 of 251 runs; NMI in the same CBW train: 46 of
  96 at 9 to 11 clocks). The occupation belongs to the sources the interrupt controller
  vectors, not to the pin INT, whose vector comes by INTAK on the pins.
- Inferred: it is the EU fetching the request's vector / priority from the interrupt
  controller over the internal bus (an acknowledge that needs the bus unit but no pin cycle;
  2 clocks, no wait states at W = 1, 2). What is transferred is not observable on the pins.
- This is what makes round 18's "A - P = 17 to 19": the vector read is 17 clocks behind the
  replaced pop where nothing is displaced; the 18s and 19s are runs where the last EU cycle
  or the pop's own fetch was moved.

## Q83. NMI's second stage: one rule for opcode-only trains, bus cycles and long instructions

`r19n*` (25 families, NMI alone, the edge in half-clock steps, quarter steps in `r19nld0`):
MOV AW,[BW] at W = 0 / 1 / 2, with [BW+d8], a direct address and [BW+IX]; with 1, 2, 3 NOPs
between; MOV [BW],AW at W = 0 / 2 and with a NOP between; PUSH, POP, PUSH ; POP, PUSH ; NOP;
ADD [BW],AW; MULU BL; SHL AW,CL with CL = 0, 1, 2, 3, 4, 6, 9. Tool: `build/qp/sc19.py hid=2
ev=F <rounds>` (prediction of the pushed instruction per run from the model's word log,
`o["WLOG"]`, new this round).

**The rule (measured as a whole: 5,092 of 5,128 runs of rounds 17 to 19, W = 0, 1, 2):**

1. c = the first clock the level stands at the EU (stage 4, INT's 7 clocks: e + 8.875 for NMI).
2. **Event:** the first clock t >= c on which the microcode's current word is (a) the first
   word of an instruction, (b) its N word, executing **or waiting** (MOV r,[m]'s N word waits
   on the datum of the read from the word behind the request), (c) a word waiting for the
   EU's own cycle (`D`: ADD [BW],AW's read), or (d) a loop word of a long routine (SHL by CL:
   every second clock back from the word in front of N; MULU: 2 and 7 clocks in front of N;
   other words of those routines are not events).
3. **The hidden occupation (Q82)** starts at the event: at once if the bus unit is free, on
   the first pin clock of a cycle that is in its set-up (that cycle then 2 late), behind a
   cycle in flight; one clock later when the event is a pop that starts a prefetch on its own
   clock.
4. **Five clocks after the occupation's first clock the request stands at the loader; the
   first pop at or after that clock is replaced** (not loaded: its opcode's address is what
   is pushed). Vector read 17 clocks after the replaced pop.

What this replaces. Round 18's "S = first pop >= e + 8.875; the pop replaced is the first one
at least 5 clocks after S that is not made on the first word of the instruction S loaded" is
the special case of an opcode-only train, where the only events are pops (a NOP's N word is
its first word; MOV r,imm's is its fourth or fifth with no event between). Its exception
clause ("not on the first word") is the fifth clock: a first-word pop is 4 clocks behind the
pop before it. Its failures (404 of 904 runs across bus cycles and long instructions, "3 to
7 clocks with no pop") are events that are not pops: a waiting N word (3 clocks in front of
the datum pop of a read at W = 0, which the occupation then moves by 2), a loop word (5 or 7).

Evidence for each element (each is a threshold read to half a clock, both alignments):

| element | probe | reading |
|---|---|---|
| a waiting N word is an event on every clock | `r18tld0`, `r19nld1/2`, `r19nld80`, `r19nldd0`, `r19nlbi0` | level by the cycle's first pin clock T (c <= T): this instruction's datum pop is replaced; c = T - 1 or T: the read is 2 clocks late and its pop is still the one replaced; c = T + 1: the next instruction's. Same at W = 1, 2 (pop at T + 4, T + 5): the 5 clocks are counted from the event, not back from the pop |
| the first word is an event, the words behind it are not | `r19nst0` (c on the store's first word: its own pop, 5 clocks later, is replaced), `r19npush0`, `r19npq0` (c on PUSH's second word: not this pop, the next), `r18tmm0` (MOV r16,imm16: first word yes, second and third no) | scores with (a) alone / (a)+(b)+(c): see below |
| a word waiting for the EU's cycle is an event | `r19nrmw0` | c on the read's first pin clock: the pop on the write's first clock, 5 later, is replaced |
| loop words | `r18tshl0`, `r19nsh*`, `r18tmul0`, `r19nmul80` | SHL by CL at CL = 0, 2, 3, 4, 6, 9, 31 (even / odd): level 5 clocks in front of N: the shift's own pop; 3 in front: the pop behind it; later: the second pop behind. CL = 1: 7 and 3 (8 runs miss: the model's place for N at CL = 1 is not verified by an INT sweep). MULU BW / BL: 7 and 2 in front of N at even alignment, 7 and 4 at odd (12 runs miss; the routine's length differs by a clock between the alignments, so by operand or queue state: not read) |
| 5 clocks, from the occupation | every family; `r18tnop2`, `r18tinc2`, `r18tmm2` | with the pop-and-prefetch clock of step 3: W = 2 trains exact; without it 66 / 79 / 99 of 120 / 144 / 168 |

Scores by event set (`ev=`), delay 5, all families: N word executing only (round 18's S)
3,865; N word current 4,723; every word up to N 5,037; first word + N current
+ D 5,092 (of 5,128).

Status. Measured: steps 1, 3 (as displacement of pin cycles), 4 (the 5 and "first pop"), the
event list as a list. **Inferred: what the events have in common.** Every event word is one
on which the EU hands something to, or waits for, the loader or the bus unit (the boundary's
first word, the pop, a wait for its cycle), and the words that are not events are words
executed inside the EU (the tail behind the pop, the ALU words of PUSH and MOV r,imm16). The
reading that fits: the EU's request for the internal acknowledge can only be issued on a
clock on which the EU's sequencer is synchronised with the front end, and the loop words of
SHL / MULU are such clocks because the loop counts through the loader's side (not shown;
**unknown**). Not measured: DIV, the string routines, REP, the 0F page, I/O instructions,
transfers (the two jump families of round 18 still miss in front of a target: `r18tjmp0` 136 of 168, `r18tjch0` 165 of 192, `r18tjch2` 206 of 216).
The 36 misses left are the second and third instruction behind the frame's long shift
at odd alignment in three trains and MULU's successor at odd alignment (6 runs).

## Q84. INTP0 goes through NMI's second stage (a test); a timer request shows the same occupation

`r19pnmi`, `r19pp0`, `r19ptm`, `r19pint` (78 runs each: the request at one fixed clock, the
trains NOP / MOV r8,imm8 / MOV AW,[BW] moved against it by pads of 0 to 13 clocks) and
`r19qnmi`, `r19qp0`, `r19qtm`, `r19qtn` (the same with the request 34 clocks later, when the pad
is long over). Tools: `build/qp/p19.py` (for every candidate clock c, the runs each rule
reproduces), `g19.py` (the read / prefetch gaps of the load train in front of the vector read).

- **Design note.** The first set is weak: its request stands at the EU while the pad itself
  executes, where an event comes almost at once, and both rules fit NMI's own control (INT's
  rule with c = 85 for all three trains). The second set is the test: in a steady train
  NMI's rule looks like INT's with a lead that depends on the train.
- **NMI control (measured):** Q83's rule reproduces 78 of 78 with one clock, c = 113 (the edge
  at 104 + 8.875, as predicted). INT's rule needs c = 116 for the load train, 119 for MOV
  r8,imm8, 121 for NOP: 3, 6 and 8 clocks late, by train.
- **INTP0 (measured): the same.** Q83's rule: 78 of 78 with c = 114 at even alignment and 115
  at odd (the edge at 92: 22 to 23 clocks from the pin through the sampler, the flag, the
  scan and stage 4). INT's rule would need 117 / 118, 120 / 121, 122 / 123 by train, the
  spread NMI has. In the first set: Q83's rule 78 of 78 at c = 83, INT's rule 74 of 78 at
  best. With the hidden occupation seen in INTP0's runs of round 17 (Q82) this is no longer
  "compatible": **an INTPn request stands at the EU like NMI's and is taken by the same
  second stage.**
- **INT control:** the first pop at or after c = 80, 78 of 78; Q83's rule fits no c.
- **Timer 0 (measured in part):** the model cannot place the pops of these programs (it does
  not know the store to TMC0 that starts the timer), so the rule is not scored. In the load
  train at even alignment, where undisturbed reads are 10 clocks apart, 18 of the 26 runs of
  `r19qtm` / `r19qtn` have a read 1 to 3 clocks late in front of the take, the classes NMI's
  and INTP0's runs have in the same frame (9 of 13 and 8 of 13); the occupation is there.
  That the take then follows Q83's rule for the timer is **inferred**.

## Q85. INT's stage 4: a delay in front of a request latch at the loader; IE acts at the latch

`r19d` (224 runs): a NOP train with a DI in it (DI popped at 92, its boundary at 95, its first
word, which pops the next opcode, at 96), INT raised in half-clock steps and held 30 clocks;
the same with an EI 16 clocks behind the DI and the pin high for 2 clocks only, or held.
`r19s` (200 runs): INT high for 2 and for 3 clocks across the MOV AW,[BW] train (pops 10
clocks apart) in half-clock steps, and at 96 and 136 inside SHL AW,CL (76 clocks).
`r19pint` (78 runs): the edge fixed, the train moved by pads of 0 to 13 clocks. Tool:
`build/qp/d19.py <round> [pE|pO]`.

- **A short pulse is carried and kept (measured).** INT high for 2 clocks is acknowledged in
  front of the instruction whose pop is the first at or after e + 9.125, at every one of the
  44 half-clock positions and both alignments in the load train (the pin is low again up to
  17 clocks before that pop), and at the shift's own pop when the pulse was 68 and 28 clocks
  earlier (8 of 8). 3 clocks: the same. So the 7 clocks are **not a counter that needs the
  level standing**, and what arrives is **held at the loader until a pop takes it**: a delay
  that carries the accepted level, then a set-and-hold request latch. (Round 17 had this for
  the NOP train only, where a pop comes every 4 clocks.)
- **IE does not gate the input of the delay; it gates the latch (measured).** With DI in the
  train the latest edge acknowledged is 82.5 (in front of the DI itself: 82.5 + 9.125 <= 92,
  its pop); an edge at 83.0 to 97.5 is never acknowledged, at either alignment, though for
  83.0 to 86.5 the level was accepted by the two samples 7 to 11 clocks before the pop at 96
  with IE = 1 all that time and the level stays for 30 clocks. A line whose input is ANDed
  with IE would deliver those to the pops at 96 and 99. So spec 14 I-2 item 1 ("ANDed with IE
  at the input") is wrong: **the request latch at the loader is set by the delayed level
  only while IE = 1 and is cleared when IE = 0.**
- **Cleared, not masked (measured):** the 2-clock pulse that entered before the DI is not
  acknowledged behind the EI 16 clocks later (30 of 30 edges from 83 to 97, both alignments);
  the held level is, in front of the second instruction behind the EI at every edge (the
  first one's opcode is popped by the EI's own N word before IE is seen set: 30 of 30).
- **DI is in effect at its own first-word pop** (the pop at 96 is not replaced with the
  request standing since 92.1): IE is clear at the loader no later than the boundary of DI.
- With the level standing at EI, the EU-side wait is under 2 clocks from the pop the EI makes
  (126) to the pop that is replaced (128): the seven clocks are not run again when IE is set.
  They sit between the two samples and the latch, whatever IE is (inferred from the two
  bullets above: a delay behind an IE gate would cost 7 clocks after EI; "EI sets IE 7 clocks
  before its end" would fit the EI runs alone, and the DI runs exclude a gate at the input).
- The pad control: one rule, the first pop at or after c = 80 (e = 70 + 9.125), 78 of 78; no
  bus cycle displaced in any INT run (Q82).

**What the seven clocks are: still unknown.** Excluded by measurement so far: the divided
clock (round 17), a microcode sample point, the bus unit, the queue (round 18), a counter on
the standing level, an IE-gated input (this round). Not tried: HALT (round 17's release
lattice is the only data), HLDRQ (the schedule can drive the pin, but PMC2 and the port-bank
hand-over of validation/v35s/dma.py's frame are needed, not gen_r15's: not attempted), PRC
(a write changes the CPU clock under the capture: not attempted).

## Q86. br_n1: the word that waits is the displacement word (model corrected)

No new acquisition: round 18's `r18j` (60 runs) decides it. The transfer in the 12 differing
runs is always a JMP short whose routine starts while fetches of the new stream are still
running (the first flush fetch has brought its opcode, with or without the displacement; the
model's boundary is on the last clock of the third fetch behind the flush and the fourth fetch
starts under the routine's first words).

- **Measured (on the model's word grid): the fourth word of JMP short, the one that pops the
  displacement, does not execute while a fetch's pin cycle is in flight** (a bus-idle word, the
  model's `B`: the same act JZ / JNZ already carry on their displacement word). With it the
  flush word comes W clocks later at W = 1, 2 in exactly the 12 runs and nowhere else:
  `JMP = ". . . BP . . F N ."` gives `r18j` 60 of 60 (from 48).
- **The rivals are excluded by the same 60 runs**: the wait on the routine's second word 30 of
  60, on the third 30, on the fifth 32 (they move W = 0 runs that are exact today). So "the
  transfer's first word waits" is wrong and "its displacement word waits" is right; no probe
  that moves the displacement fetch against the opcode pop was needed (the W = 0 / 1 / 2
  triple at both alignments already moves the fetch by 0 / 1 / 2 clocks against the routine).
- Round 18's wording "its flush fetch starts 8 clocks after the end of the fetch that brings
  its displacement" was a coincidence of the two alignments read: in `j0j0` at even alignment
  the displacement arrives with the opcode in the first flush fetch, and the fetch that
  counts is the one in flight under the displacement word (the fourth behind the flush).
- `model_m.py` corrected (the one default string). The whole non-interrupt socket set:
  **12,215 of 13,404 exact (from 12,203); 0 runs lost, 12 gained (all `r18j`)**. In round 17's
  frame (rounds 8 to 17) nothing changes: 11,834 of 12,396.
- Inferred, not measured: that CALL near, JMP near and the far forms carry the same wait on
  their displacement word. Their `r18j` runs are exact without it (the CALL is always the
  first transfer of the program, with the queue full), and a `B` there was not tried against
  a probe that would show it. The corpus rows call_n2 / ret (partners of br_n1 in `fd17`'s
  count) differ only at the JMP of the sequence in the 60 runs.

## Q87. The REP compares at W = 1 and 2: the difference is the RTL's, in CMPM's later iterations only

`build/qp/rc18.py socket|sim18 <w> <pE|pO>` on round 18's `r18c` (768 runs silicon, 768 sim).

- **Silicon (measured, all 128 programs an alignment and wait):** every read's waits are added
  once, serially. CMPBK: reads 9 + W apart (9 / 10 / 11). CMPM: the second read 10 + W after the
  first (10 / 11 / 12), every later read 12 + W after the one before (12 / 13 / 14). The
  exit lengths grow by the waits of the cycles in them only (26 / 27 at W = 0 as Q80).
- **RTL copy (2a30b50):** CMPBK right at every wait. CMPM: 10 + W for the second read (right),
  then **12 at every wait** (12 / 12 / 12): the two words by which a later iteration is longer
  than the first run concurrently with the read cycle in the RTL, so one or two waits are
  absorbed; on silicon they are words behind the datum word (`Y D . . . .`: the four idle
  words follow the cycle whatever its length). The 28 of 64 programs an alignment that
  differ at W = 2 are exactly the CMPM / CMPMW programs with three or more reads (14 + 14);
  at W = 1 the same 28 differ by one clock a later read.
- Rule for the builder: in the CMPM loop the wait for the read cycle (`D`) is the second word
  of every iteration and the remaining words (2 in the first iteration, 4 in every later one)
  execute after it, none of them a wait for the same cycle.
- model_m's REP compare code was not generalised (it still takes the element count from the
  prefix: 144 of 768 on `r18c`); the silicon side is the table above and Q80.

## Round 19 in numbers

| family | what | runs | flagged repeats (all strobe-only) |
|---|---|---|---|
| r19nld1, r19nld2, r19nld80, r19nldd0, r19nlbi0, r19nld0 | NMI across MOV AW,[m]: W = 1, 2; d8, direct, [BW+IX]; quarter-clock edges | 114, 130, 106, 106, 106, 98 | 0, 1, 8, 8, 11, 25 |
| r19nln10, r19nln20, r19nln30 | the load with 1, 2, 3 NOPs between | 122, 154, 170 | 14, 30, 28 |
| r19nst0, r19nst2, r19nsn0 | MOV [BW],AW at W = 0, 2; with a NOP | 106, 130, 122 | 19, 37, 28 |
| r19npush0, r19npop0, r19npq0, r19npn0 | PUSH, POP, PUSH ; POP, PUSH ; NOP | 106, 106, 122, 122 | 20, 18, 31, 21 |
| r19nrmw0, r19nmul80 | ADD [BW],AW; MULU BL | 154, 138 | 39, 25 |
| r19nsh00 .. r19nsh90 | SHL AW,CL, CL = 0, 1, 2, 3, 4, 6, 9 | 130, 138, 146, 154, 162, 178, 202 | 24, 26, 22, 32, 31, 40, 37 |
| r19pnmi, r19pp0, r19ptm, r19pint | fixed request, padded trains | 78 each | 17, 22, 20, 18 |
| r19qnmi, r19qp0, r19qtm, r19qtn | the same, the request 34 clocks later | 78 each | 21, 18, 28, 23 |
| r19d, r19s | INT against DI / DI .. EI; INT pulses of 2 and 3 clocks | 224, 200 | 63, 52 |

4,370 runs, 0 failed, 0 incomplete, 857 flagged repeats, every one strobe-only
(`build/qp/rep19.py r19`: both traces field by field). FF10h was written by `r19pint`, `r19d`,
`r19s` only (gen_r15's INT_HEAD and hand-back); the first INT program was run alone and its
vector read at 0100h checked before the batch (`build/qp/r19/scout-int.txt`). One scout run.
Board left with vccb false, failure 0. No sim was run and the RTL copy was not re-based (no
new "Land" commit on v35s-harness during the round).

Model: `o["WLOG"]` (every clock's word, acts, stalled or not; a log) and one rule change, JMP
short's displacement word a bus-idle word (Q86): 12,215 of 13,404 non-interrupt socket runs
exact (from 12,203; none lost). Interrupt families are scored by `build/qp/sc19.py`, not by
model_m (5,092 of 5,128 NMI runs of rounds 17 to 19).

Not started: every "unread form" of the brief's item 5 (NEG [BW+d16], EXT across a word's
extra word, ADD [d16],imm8 with four bytes held, CALL far with waits, OUTM twice, the five
"twice" runs, the three CVTBD runs, SET1 word behind OUT at even alignment), the scan figures
at W = 1 / 2, `r18tjch2`'s INT half; HLDRQ, PRC and HALT against INT's seven clocks; the
generalisation of model_m's REP compare code.

# Round 20

Acquired: `QPr20l` 648, `QPr20t` 270, `QPr20a` 678, `QPr20b` 726 (non-interrupt, 2,322), `QPr20h` 240 and eight NMI sweeps `QPr20n*` 1,160 (interrupt, 1,400): 3,722 runs, each twice; 606 repeats differ, all strobe-only (`build/qp/rep20.py r20`). No failures, no incomplete runs. Board left with vccb false, failure 0.

## Q88. LEA with d16 / direct at even alignment, four bytes held: the release word waits for a chained fetch that starts on its own clock (and so does MOV r16,imm16's)

Probes `QPr20l` (648 runs): LEA AW,[BW+d16] / [BP+d16] / [d16] and, as the control, [BW+d8]; nine
programs a mode (alone, NOP before, NOP after, PUSH before, OUT imm8 before, OUT imm8 ; NOP before,
PUSH ; NOP before, PUSH after, twice) with each of the three markers (PUSH AW, OUT imm8, OUT DW).
The corpus's lost frames are in it: F25 `push-ldea-*` and F30 `push-lea-*-k1` = `pb-mp`, F30
`out-lea-*-nopb` = `onb-mi`.

- **Measured: the two shapes of Q68 are both wrong in one state and the five-word one is right
  everywhere else.** `P . . BNPP2 .` 603 of 648 at first; the six-word `P . . PP2 N .` 166 of the
  first 216 against 196. All 45 misses are one state (`build/qp/tab20.py 8D ...`): the LEA's boundary
  finds exactly **four bytes held with the bus idle** (ModR/M, d16, next opcode; the fetch that was
  held off by the PUSH's write or the OUT's cycle then starts on the LEA's first word, and the
  fetch chained behind it starts on the LEA's fourth word, the release word). There silicon's next
  boundary is 3 clocks later at every wait (W = 0, 1, 2): the chained fetch starts on time, the
  release word does not execute on its first clock and waits to the clock after it; the boundary
  then falls on the last clock of the fetch the release pop itself starts.
  Every other state (5 or 6 held idle; 3 or 4 held on a fetch's last clock) is exact: 495 / 495.
- **Measured: LEA with d8 in the same frames does not wait** (108 of 108 with the plain `B`; 93 of
  108 with the stricter word). LEA without displacement and with two registers and d16 were not put in the state.
- **The same act on MOV r16,imm16's release word (`. . . . BNPP2 .`) reads round 12's oldest open
  rows**: MUL / DIV on memory at even alignment, W = 1 / 2 (`QPr12a-mm-*`, 24 stems x 2 = 48 runs,
  open since Q63). There the MOV AW,imm16 behind the frame's `C7 07` store has its release word on
  the first clock of the fetch chained behind the store's fetch. At W = 0 in the same frame the
  release word is the EU's *next* word on that clock and the chained fetch is not started (Q42's
  CH_BNEXT, unchanged): the two cases separate "the word the EU has reached" from "the word it
  reaches next".
- Model: act `I` (a bus-idle word that also waits on the clock a back-to-back / chained fetch
  starts, with none of the exemptions `C_NOCH` gives the commit word; CH_BNEXT does not hold the
  fetch back for an `I` word already stalled). `LEA_D16 = LEA_DIR = "P . . BINPP2 ."`,
  `RI = ". . . . BINPP2 ."`. Whole non-interrupt socket set: **+101, 0 lost** (LEA 45, mm 56).
  The same act on ADD AW,imm16 / ALU r,imm16 / LEA [BW+IX+d16]: no run changes (not in the state:
  inferred by analogy, not measured). On the two-byte release words (`BNP`: MOV r8,imm8, ADD r,imm8
  83, ADD AL,imm8): +5, -12 (`QPr13a-fw-c7-*-i8`), so not a rule for them; LEA d8 says no (15 runs).
- **Unknown:** why the three-byte release differs from the two-byte one. Two readings fit all
  1,368 runs of the families: (a) the word kind (the imm16 / d16 release is a strict bus-idle
  word); (b) a count (the release leaves two bytes behind the staged opcode when the chained
  fetch was decided at five held; the two-byte release leaves three). No probe here separates them.

## Q89. Transfers at a flush target: the far forms wait on their segment word; the near forms need nothing

Probes `QPr20t` (270 runs): JMP short (the control), JMP near, CALL near, JMP far, CALL far, each
as the first instruction, behind a NOP, at the target of a JMP short (`j0`, `j1`, `j0n`, `j0nn`,
`nj0`, behind OUT imm8 ; JMP), and twice in a row. Repeats: 80 differ, strobe only.

- **JMP short (control): 54 of 54** with Q86's bus-idle displacement word; without it 44 (the ten
  runs are the `j0` / `j1` / `oj0` / `nj0` / twice frames at W = 1, 2: the frame works as designed).
- **JMP near, CALL near: 108 of 108 with the shapes as they are (no wait).** Measured: a waiting
  word in JMP short's position (word 4, in front of the displacement pop) is excluded (182 of 204
  with rounds 8 and 18); a bus-idle or strict bus-idle displacement word (word 5) changes no run of
  any round (204 of 204 either way): in none of these programs does a fetch start or run on that
  word. **Not separable here; do not build a wait.**
- **JMP far, CALL far: the word that pops the segment (the second pointer word, word 9) is a
  strict bus-idle word, Q88's act `I`.** `JFAR = ". . . . PP2 . Q . BIPP2 . . F N ."` 72 of 72
  (`QPr20t-t-jf-*` 54, `QPr5-jfar-*` 18; was 60); `CALLF = ". . . . PP2 . Q . BIPP2 . Y D . Y D . .
  F N ."` 114 of 114 (`QPr20t-t-cf-*`, `QPr8-fl-callf-*`, `QPr13a-tj-callf-*`; was 91). Single
  placements of B, BI and the T wait on each of the eleven words of JMP far: the next best is 60.
  This is the whole of "CALL far with waits" (open since round 8) and of `QPr5-jfar` at W = 1, 2:
  from a full queue at even alignment the fetch chained at five held starts on the segment word's
  clock at W >= 1 (silicon: everything behind is 2 clocks late at W = 1 and at W = 2) and not at
  W = 0. A plain B on the offset word or on the segment word gains 5 of the 35.
- Inferred, not measured: the memory forms (JMP / CALL far [d16]) and RET far / RETI are not in
  these frames.

## Q90. The forms that had no probe: TEST with a displacement, POP to [BW+IX+d16], NEG / NOT / INC with a displacement

Probes `QPr20a` (678 runs): each form behind INC BW / CBW / NOP / CLC (the lead frame) and as the
four probe programs; NEG [BW+d16] also behind MOV BW,imm16, MOV AW,BW, two NOPs, two INCs, OUT imm8.
(The INC BW lead changes the address register of the [BW+..] modes one clock before it is used:
the known artefact of round 17; those 13 stems are not scored.)

| form (corpus row) | routine | score |
|---|---|---|
| TEST [d16],AW (85 06; test_dir_aw) | `P . B Y . PP2 DN .` | 42 / 42 (`f-testd-*`, `fl-testd-{c,k,n}`) |
| TEST [BW+d16],AW (85 87; test_m_aw_bw_d16) | `P . B Y . PP2 DN .` | 42 / 42 |
| TEST word [BW+d8],imm16 (F7 47) | `P . B . . BYP DPP2 . BN .` | 42 / 42 |
| TEST word [BW+d16],imm16 (F7 87; test_m_imm_d16), [d16],imm16 (F7 06) | `P . B . . BYPP2 DPP2 . BN .` with Q69's reserving request | 84 / 84 (72 without the B on the request word: the 12 are the first instance at odd alignment, W = 1 / 2, where a second fetch goes ahead of the read) |
| POP [BW+d16] (8F 87) | `P . Y D . . PP2Z G N .` (the direct form's) | 42 / 42 |
| POP [BW+IX+d8] (8F 40) | `P . Y D . . PZ G N .` (the d8 form's: two registers cost nothing) | 42 / 42 |
| POP [BW+IX+d16] (8F 80; pop_m_bw_ix_d16) | `P . Y D . . . PP2Z G N .`: one word more, behind the stack read and in front of the release | 42 / 42 (the direct form's shape 0 / 42) |
| NEG / NOT word [BW+d16], NEG [d16], INC word [BW+d16] (F7 9F / 97 / 1E, FF 87) | `P . . B Y . PP2 . DZ G N .` | 213 / 216 with `QPr15a-negd16` (was 19 / 24 on round 15's 24 and 0 for the rest) |
| NEG word [BW+d8] (F7 5F) | `P . . B Y . P . DZ G N .` | 42 / 42 |

- TEST m,r with a displacement is TEST [BW],AW's head (`P . B`) in front of the load's body
  (`Y . PP2 DN .`). A second `.` in front of `DN` scores the same (hidden under the read).
- NEG [BW+d16]: Q66's "no single shape gives both" is closed. The old shape had the request one
  word late and the two displacement bytes on words of their own; the reading is INC [BW]'s head
  (`P . . B Y`) with the displacement released as one word two words behind the request. All
  five W = 0 misses of round 15 are exact. NOT, INC and the direct mode are the same routine
  (measured, 48 runs each). The 3 misses are `fp-negd16-ri` at even alignment (behind MOV
  BW,imm16), all waits: the "behind MOV r16,imm16" family (CVTBD, the 0F forms of `em2` / `em3`).
- POP [BW+IX+d16]: where the extra word sits is not fixed by these runs beyond "between the
  datum and the write's boundary" (five shapes tie; the simplest is given).

## Q91. The second-instance family, one item at a time (`QPr20b`, 726 runs)

**SHL / SAR r,imm8 (the shl_imm rows): one word shorter, the count byte on a bus-idle word, the
waiting word one place earlier.** Probes `h-shli{1,4,8}-*` (162 runs: behind INC / CBW / CLC /
two NOPs, a NOP behind, and alone or behind a NOP in front of the OUT imm8 and PUSH markers) with
rounds 2 and 9. Routine: `P . . BP . S`, then the count loop, `N .`; 11 + 2n words (was 12 + 2n
with the count byte on a plain fourth word and the waiting word seventh). **360 of 360** (was
321). Each element is needed: without the bus-idle pop 249, with the old length 297, the waiting
word one place either side 87. Measured; the waiting word is the CL form's (`S`, the bus unit's
slot), B / BI / BC there score the same.

**CVTBD: the operand byte's word is bus-idle too.** `. . . BP . B` + thirteen words + `N .` (21
words, as Q70, with the fourth word a bus-idle word): **120 of 120** (`QPr15a-cvtbd`, `QPr17d`,
`QPr20b-c-*`: behind MOV r16,imm16, ADD AW,imm16, MOV r8,imm8, ADD r,imm8, MOV r,r and three
two-instruction leads); Q70's shape 95. The three runs behind MOV BW,imm16 are in it.

**SET1 / TEST1 word and byte behind OUT (set1 behind OUT at even alignment): the commit word is a
plain bus-idle word.** Probes `s-*` (78 runs: SET1 AW,CL behind OUT imm8 byte and word, PUSH, a
store, IN, a load, OUT ; NOP, NOP ; OUT, two OUTs; SET1 AL,CL, TEST1 AW,CL, SET1 with CL = 3 and
SET1 AW,imm4 behind OUT). Round 10's `C` (a commit word that also waits on the clock a
back-to-back fetch starts) on the r,CL and r,imm forms' N word is wrong behind an I/O cycle (27
runs, 2 clocks late in the model at every wait) and needed nowhere: `TEST1 = "P . BP . . BN ."`,
`CLR1 = "P . BP . . BN . ."`, `TEST1I = "P . BP . BPN ."`, `CLR1I = "P . BP . BPN . ."` gain 27
and lose 0 on the whole set. (The memory forms keep their `C` word: not re-tested.)

**OUTM twice: the fifth word is bus-idle.** `OUTM = ". . . . B . Y D . X . . . N ."`: **108 of
108** (`QPr20b-o-*`, `QPr11c-outm*`; was 94). All 14 misses were W = 2 second instances: the
fetch started by the first instance's last pop is still on the pins on the second's fifth word
only when it is five clocks long. The REP form's head already has the word (`RH_OUTM`).

**ADD mem,imm with d16 / direct, "four bytes held": the state is closed, the rule is not.**
Probes `m-*` (38 programs). Every miss of the 83 forms (ADD [d16],imm8, ADD [BW+d16],imm8: 30
runs, all waits) and of the 81 forms (imm16: 8 runs, W = 0 only) is an instance whose boundary
finds **four bytes held with the bus idle** (`build/qp/tab20.py 83 ...`: 0 of 30 exact there, 138
of 138 in the nine other states); a PUSH in front makes the state directly (`m-*-p`, even
alignment). Measured: the fetch that starts on the first word is followed by two chained fetches
and the read comes behind the second (3 + W clocks later than the model, which lets the read go
at its due clock against a fetch at five held). It is Q88's state, but neither Q88's strict
bus-idle word on the displacement word, nor Q69's reserving request on these keys (`RSV_KEYS`: -7),
nor REQ_PRI off reads it. **Open, with the state as the description.** The "five twice runs" of
round 17 (`mi-addi816-2` E0-E2, `mi-addiw16-2` / `mi-addiwx-2` O0) are this state.

**EXT / INS r,imm4 behind two or three short instructions: partly read.** `e-*` (the stems
without INC BW, which moves the offset): in the 22 round-20 misses (looked at: the EXT ones) the only difference is one
fetch: silicon makes a fetch on the clock after the field's read, the model 60 clocks later, and
the ends agree. So the imm4 byte has left the queue by the read's last clock (measured: the count
allows the fetch). Moving the pop to the datum word (`EXT_HEAD = "P . BP . C . . Y DP"`, tail `N .`)
puts that fetch right and the end one clock early (+3 runs net); with round 16's seven "one clock
early" runs this says the routine is also one word longer somewhere behind the read, but no
single placement tried gives both (`EXTI_TAIL` variants). **Open.**

## Q92. INT and NMI stepped across the entry into HALT

Probes `QPr20h` (240 runs, W = 0, both alignments; even alignment read): four NOPs and HALT, the
edge stepped half a clock from 74 to 103.5 (HALT's pop is at clock 92; `build/qp/h20.py r20h`).
Columns: edge e, vector read's first clock A, the return offset pushed (4 = HALT itself, 5 = the
byte behind it).

| source | e | pushed | A | reading |
|---|---|---|---|---|
| INT | <= 82.5 | the NOP or HALT popped first at or after e + 9.125 (HALT for 79 to 82.5) | pop + 21 to 23 | Q75's rule holds up to HALT's own pop: e = 82.5 (at the loader 91.6) replaces HALT, e = 83.0 (92.1) does not. **Measured: HALT's pop is an ordinary pop for the latch at the loader; nothing re-times the 7-clock line in front of a HALT** |
| INT | 83 to 90.5 | 5 (HALT executed, then released) | **127 for every edge** (A - e from 44 down to 36.5) | a request that reaches the loader behind HALT's pop is not taken before a fixed point: vector read 35 clocks after HALT's pop however long it has stood |
| INT | >= 91 | 5 | 129, 131, ... : a 2-clock lattice, A - e = 36.5 to 38 (thresholds between e = x.5 and x + 1, x even) | round 17's lattice (Q74), now tied to the entry: the slot that serves e = 83 to 90.5 is the first one |
| NMI | <= 75 | 4 (HALT's pop replaced) | | the running path (stage 6a to 6c) |
| NMI | 75.5 to 90 | 5 | **123 for every edge** | as INT, 4 clocks earlier |
| NMI | >= 90.5 | 5 | 125, 127, ... , A - e = 33 to 34.5 (thresholds between x and x.5, x even) | the lattice, half a clock ahead of INT's (the filter against the two samples, as round 17) |

- **Measured: in the same lattice slot NMI's vector read is exactly 4 clocks ahead of INT's**
  (123 / 127, 125 / 129, ...). From one pop INT's vector read is 21 clocks behind (two INTAK cycles in front of it)
  and NMI's 17: so **the pop that leaves HALT is on the same clock for both sources** (inferred
  from the two figures; the pop itself is not on the pins). Running, NMI's pop is 5 or more clocks
  behind INT's for the same edge (stage 6a to 6c). So the vectored source's event / occupation /
  five-clock stage is not passed on the way out of HALT, or INT waits for the same time there.
- **Measured:** release latency, edge to the releasing pop: NMI 16 to 17.5 clocks, INT 15.5 to
  17 (running: 9.125 for INT). The extra is the lattice (0 to 2) and about 6.4 clocks.
- **Unknown:** what the 6.4 clocks are (the restart of the EU's clock, the line re-run, or the
  occupation), and whether stage 4's seven stages are clocked during HALT. A request that entered
  the line before HALT's pop (e = 83 to 90.5) and one that enters in HALT are served by the same
  lattice, which says the release does not depend on where the request is in the line: the
  release looks at the sampled level, not at the line's output (inferred).
- What this does for "the line's identity": nothing re-times INT in front of HALT, and HALT's
  release does not use the line's output. The identity of the seven stages is still unknown.

## Q93. NMI's event words in DIVU / DIV byte, the string instructions and REP

Probes `QPr20n<train>` (1,160 runs, W = 0, both alignments): the NMI edge stepped half a clock
(one clock for the REP trains and DIV) across DIVU BH (F6 F7), DIV BH (F6 FF), trains of MOVBK,
STMB, LDMB, and REP MOVBK / STMB / LDMB with CW = 6 or 8. c = the first clock the request stands
at the EU (e + 8.875, spec 15). Scored with spec 15's rule (`build/qp/sc20.py hid=2 ev=F`: the
pushed instruction per run) where the pushed address says something; for REP it never does (the
prefix's address is pushed whatever the iteration) and the vector read's clock A is read instead
(`build/qp/h20.py`).

| train | score with spec 15's rule | what is measured |
|---|---|---|
| MOVBK x 10 | **144 / 144** (first word, N word, the words waiting for the EU's cycles) | nothing new needed |
| STMB x 12 | 86 / 120 | a request with c up to the instruction's fifth word (N - 6; the 13-clock routine's N word is its ninth) is taken by this instruction's pop; c on the sixth word, the request word or the write's wait is not. With every word from the first to the N word an event: 110 / 120 (the 10: c on the sixth word, which is not an event). So: **words 1 to 5 are events, word 6, the request word and the write's wait are not** (measured as thresholds; scored 110, the exact list not re-scored) |
| LDMB x 12 | 85 / 120 | the 35 misses are c = 94 to 96 in every period: the read's own wait; silicon takes the pop on the datum word one instruction earlier than the rule. The occupation in front of this read (Q82) moves the datum word, and with it the pop, behind the request: **not closed** |
| DIVU BH (33 clocks) | 192 / 200 with MULU's two offsets (N - 2, N - 7); 194 / 200 with one event at N - 5 | **inside the routine every edge from c = 89 to c = 118 is taken at the routine's end** (A constant at 140 for 60 edges; N = 123), c = 119 is not: the last event that still reaches the end pop is at N - 5. The 6 left are at even alignment, c = 119 to 121 (a further event in N - 4 to N - 1 at even alignment only): not read |
| DIV BH (signed, 52 clocks) | **134 / 136** with MULU's offsets (N - 2, N - 7); N - 5 alone 131 | MULU's two loop words fit signed DIV; DIVU's fit is not separated from them (192 against 194) |
| REP MOVBK (18 clocks an iteration: read, write 9 later) | - | **the loop ends with the iteration whose write starts at W when c <= W - 6** (= the read's first clock + 3: the datum word's clock), every 18 clocks (thresholds e = 117, 135, 153; both alignments). Vector read **50 clocks after that write's first clock** (17 after a pop outside REP) |
| REP STMB (9 clocks) | - | ends with the write at W when the request stands by W - 6 + a fraction (threshold between e = W - 14.5 and W - 14: half a clock later than c's lattice); vector read W + 47 |
| REP LDMB (11 clocks) | - | ends with the read at R when c <= R (threshold between e = R - 8.5 and R - 8); vector read R + 50 |

- **Measured in all three REP trains:** the hidden two-clock occupation (Q82) is there: for the
  two edges whose c is the first clock of an EU cycle or the clock before, A is 2 later (e.g.
  REP MOVBK e = 121, 122 and 130, 131 in each period).
- **Inferred (one reading of the three thresholds with spec 15's "event, then five clocks"):**
  the events are the wait / datum words of the iteration's cycles (as outside REP), and the loop
  looks at the request once an iteration: for MOVBK and STMB on a word 1 clock either side of
  the write's first clock (W - 1 to W + 1), for LDMB on the iteration's last-but-one word (R +
  5). It is a window, not a word, in each case; the three are not one offset from the
  iteration's end. **Do not build from this; the thresholds are the data.**
- **Unknown:** what the 47 to 50 clocks between the last cycle and the vector read are (33 more
  than behind an ordinary pop: the prefix's address is recovered and pushed; no pin activity was
  looked at in that interval).
- Not run: REP with compares (CMPBK / CMPM), INM / OUTM under NMI, any of this at W = 1 / 2, and
  INT in the same trains.

## Q94. The strict bus-idle word, generalised: every bus-idle word that releases a 16-bit operand

A search over every routine of the model (`build/qp/isearch20.py`: act `I` added to each word
that pops, one word at a time, the whole non-interrupt set re-scored; 54 variants change a run)
found two more words that gain and lose nothing, and both are of Q88's kind:

- MOV word [d16] / [BW+d16],imm16: the request word that releases the d16
  (`STIM_D16 = "P . . BIYPP2 . . . KPP2N ."`): +9, 0 lost.
- With it, the same word of ADD word mem,imm16 with d16 / direct (`ADDIW_D16`, `ADDIW_DIR`):
  +8, 0 lost: these are the 81 forms' runs of Q91's "four bytes held" state.
- The request word with a d8 (+1, -3) or with no displacement (-6) does not carry it; nor do
  the release words of the two-byte immediates (Q88) and LEA d8.

**Measured, as one statement:** a bus-idle word whose release is a word-wide operand (d16,
imm16, the far pointer's segment) also waits on the clock a chained fetch starts; one that
releases a byte or nothing does not. Six instruction groups measured (LEA d16 / direct, MOV
r16,imm16, JMP far, CALL far, MOV mem,imm16, ADD mem,imm16), 0 runs lost in any round; the
other words of the kind (CMP / TEST mem,imm16 with d16 / direct, ADD AW,imm16, the 81 group on
a register, LEA [two registers + d16]) are installed the same way and change no run (inferred).
Whole set: **14,469 of 15,726; rounds 1 to 19 alone 12,322 of 13,404 (from 12,215, none lost)**.
The byte-count reading of Q88 is weakened by the far forms (their segment word releases two
bytes and waits; MOV r8,imm8's release word releases two bytes and does not).

Also from the search, thin (3 runs, W = 0, one frame): OUT DW's N word as a strict word gains
`QPr13a-fw-c7-*-nop` 3 and loses nothing. Not installed.


# Round 21

Socket runs this round: see the table at the end of the round. The RTL copy in the worktree was
re-based to main's ce9ea43 (16 files from `git archive ce9ea43`: `fpga/v35s/**`,
`validation/v35s/chains/{uasm,test_uasm}.py`; nothing under `chains/sim`), the direct sim rebuilt
and the corpus replayed once; the split is in `divergence-notes.md`.

## Q95. A read against the fetch chain behind an EU cycle: no arbitration inside the chain

This closes round 20's open state (ADD mem,imm8 with d16 / direct, "four bytes held with the bus
idle", Q91) and shows it is not a property of that instruction.

**The state.** An EU bus cycle (PUSH's write, a store, OUT, the write of a read-modify-write
instruction) ends with four or fewer bytes held, so a fetch was wanted under it; that fetch (A)
starts on the clock after the cycle and further fetches (B, C) follow back to back while five or
fewer are held: the *chain behind an EU cycle* (the model's S_LAG chain, rounds 6 to 12).
The subject's read request is made while the chain is on the pins.

**Measured (probes `QPr21m`, 498 runs: ten subjects behind eight leads; and rounds 9, 16, 17, 20):**

| request made (model's request word) | fetch at whose end the read is ripe | held then | silicon | runs |
|---|---|---|---|---|
| two clocks before A's first pin clock (under the EU cycle) | A | 5 | the read goes behind A | `QPr9-c40-add8-o*` 24, `QPr21m-m-add8-o`, `-ld16-o`, `-ldir-o` |
| on A's first pin clock or later | A or B, ripe 0 to 3 clocks before its end | 5 | **the chain goes on (B, then C) and the read follows the last fetch**, 3 + W clocks later per fetch | ADD [d16] / [BW+d16],imm8 behind PUSH, a store, two PUSHes, OUT ; NOP (`QPr21m-m-addi8x-*`, `QPr20b-m-addi8*`, 21 + 27 runs), MOV r,[BW+d16] and MOV r,[d16] behind the same leads (`QPr21m-m-ld16-*`, `-ldir-*`, 24 runs) |
| the clock before A's first pin clock | A, ripe on the clock after its end | 5 | the read goes behind A | `QPr21m-m-addi88-o` E (3) |
| the clock before A's first pin clock | A, ripe on the clock after its end | 4 | fetch B first | `QPr21m-m-addi8x-o` E, `-cmpi8x-o` E (6): **not in the rule** |

- **Rule (model option `LCH=3`, `LCH_Y=0`, installed):** once the first fetch behind an EU cycle
  is on the pins, a read requested from then on is not arbitrated against the chain: the chain
  runs until more than five bytes are held, then the read's cycle starts. A read requested before
  that clock is arbitrated as before (it goes behind A). Whole socket set: **+75, 0 lost**
  (rounds 1 to 20: +30, the 21 runs of Q91's state, `QPr16a-a3-3` 6, `QPr9-addi8x-2` 3; round 21: 45).
- **Two readings were separated on the way.** "From the chain's second fetch on, a read not ripe
  one clock before the fetch's end loses" (`LCH=1;LCH_MIN=2`) and "behind a memory write only"
  (`LCH=1;LCH_AFTER=W`) both read rounds 1 to 20 (+30, 0 lost). `QPr21m-m-addi8x-on` (OUT ; NOP ;
  ADD, the chain behind an I/O cycle) is read by the first and not the second: **the kind of the
  EU cycle in front does not matter** (measured, 3 runs + the loads' `-on` 6). The loads at W = 2
  (`-ld16-p`, `-st`, `-pp`, `-on`, `-ldir-*`: 8 runs, the read ripe three clocks before B's end
  and still behind C) are read by neither threshold and by the installed rule: **there is no
  ripeness threshold inside the chain** (measured).
- **Not the rule for writes:** the same act for a write request loses 86 runs (the stores of
  rounds 2, 5, 8, 9, 12); the stores keep Q33 / Q69.
- **Nothing behind the imm8 matters** (`-p-fn`, `-p-fri`, `-p-fs`: a NOP, MOV r16,imm16 or a long
  shift behind ADD [d16],imm8: 9 of 9 with the rule) **and the instruction does not either**: MOV
  r,[BW+d16] in the same frames behaves the same. Round 20's three failed rules were all on the
  ADD's own words; the cause is in the bus unit.
- **Mechanism, inferred:** behind an EU cycle the bus unit's sequencing runs two clocks ahead of
  the pins (S_LAG, measured in rounds 6 to 12 on the S / A / X words). In that mode the next
  cycle is chosen before the EU's request can be seen: the request is only looked at when the
  chain stops (queue full) and the bus unit is idle again. What register holds "the chain is
  running" is unknown; the outcome table above is measured.
- **Open (6 runs):** the fourth row: a request one clock before A's first pin clock with four
  held loses to B, with five held it wins. Read as the four-held fetch's priority over a read
  ripe on the very clock (`RIPE4`): +1 of 6 only; not installed.

Two shapes read on the way (no key before): **CMP r,[BW+d16] (3B 87): `P Y . PP2 DN .`** (the
load's routine; 48 of 48, `QPr21m-m-cmpm-*`); **CMP byte/word [d16],imm8 (83 3E): `P . V PP2 DP . BN .`**
(45 of 48, the 3 misses the open row above; `QPr21m-m-cmpi8x-*`).

## Q96. EXT / INS r,imm4: the imm4 leaves on the datum word; a bus-idle word two (EXT) or three (INS) words behind it

Round 20 left 22 misses (EXT / INS r,imm4 behind two or three one-byte instructions at one
alignment) with "the imm4 byte has left the queue by the read's last clock; the length is not
closed". On the same traces (`QPr20b-e-*`, `QPr16a-ph-*`; no new probe):

- In the failing runs the pop of the imm4 on the datum word starts a fetch (five held becomes
  four) and the next opcode's pop is a fixed 62 clocks behind **that fetch's end**; in the passing
  runs (no fetch there) it is 62 behind the read's end. So a word behind the datum word waits
  for the bus to be idle: the fetch (3 + W clocks from the datum word's clock) costs 1 + W clocks
  for EXT and W for INS.
- **EXT r,imm4: `P . BP . C . . Y DP . B` + (22 + v) words + `N .`** (v as Q59; the same total
  length as before, the pop moved from the last-but-one word to the datum word).
  **INS r,imm4: `P . BP . C . . Y DP . . B` + (67 + v) words + `Z G N .`**.
  Whole set **+29, 0 lost** (EXT 18: `QPr20b-e-exti-{kn,rn,kkk,nnn}` 11, `QPr16a-ph-{cc,nc,nn}-exti` 7;
  INS 11). B one word either side: EXT 0 / 30 and INS 19 / 30 of the 30-run subset. Measured.
- The register forms (EXT r,r8 / INS r,r8) pop nothing on the datum word; whether they have the
  same bus-idle word cannot be seen (inferred to: same routine body).
- Remaining EXT / INS misses: only the INC BW lead artefact (`-ii`, `-in`, `-ni`).

## Q97. The strict bus-idle word: the word kind, not a byte count; no exception among the routines

- `P2_Q=2` (act `I` on **every** bus-idle word that pops a word-wide operand, by rule rather than
  per key) changes no run of 16,224: every `B` + `PP2` word of the model already carries the act
  and none contradicts it. With Q94's counter-example (the far forms' segment word releases two
  bytes and waits; MOV r8,imm8's release word releases two bytes, opcode + imm8, and does not)
  the reading is the word kind: **a bus-idle word that reads two bytes of the queue for one
  16-bit operand**. Measured as far as the routines go.
- `P2_Q=1` (every word-wide pop, bus-idle or not, waits on the clock a chained fetch starts)
  also changes no run: on the words that are not bus-idle (the displacement word of the loads and
  stores, `P Y . PP2 D..`) the wait is hidden behind the datum wait. The two routines where it
  would show (PUSH imm16's fifth word, MUL r,r,imm16) cannot be put in the state: `r21q` (480
  programs: 20 leads x 2 routines x 2 markers) was run in the direct sim and through the model
  under both options; no program's prediction differs, so the family was **not acquired**.
- No routine pops a 16-bit operand in two halves on different words with the second on a
  bus-idle word, so "a 16-bit release with one byte already popped" has no probe. **Unknown**
  stays: whether the cause is the queue's two-byte read path (inferred, Q94).

## Q98. The corpus encodings that had no probe (`QPr21f`, 2,748 runs): shapes per form

The round's split (`divergence-notes.md`) found 903 diverging corpus runs on 94 encodings with no
socket probe of the same opcode / ModR/M mode. `r21f` probes the 36 largest in round 20's frames
(four leads, the four probe programs, behind PUSH, behind OUT imm8, in front of the OUT imm8 and
PUSH markers; 72 runs a form), the transfers through [BW] and REP INM / OUTM word with CW = 0 to 2.
Scores leave out the INC BW lead (6 runs a form: the known artefact). "RTL" is the direct sim of
ce9ea43 on the same programs (all 2,748).

| instruction | routine (model notation) | score | status |
|---|---|---|---|
| OR / AND / SUB / XOR / ADC / SBB [BW],r16 (09 / 21 / 29 / 31 / 11 / 19 07) | ADD [BW],r's: `P Y . . DZ G N .` | 66 / 66 each | measured: one routine for all eight ALU operations. **The RTL has 3 of 66 on each (ADD word: 66 of 66): a build fault** |
| ADD / OR / SUB byte [BW],r8 (00 / 08 / 28 07) | the same | 66 / 66 each | measured |
| ADD [BW+d16],r ; ADD [d16],r (01 87 / 06) | `P Y . PP2 DZ G N .` | 66 / 66 each | measured (the d8 form's routine with the word-wide pop) |
| ADD [BW+IX+d16],r (01 80) | `P . Y . PP2 DZ G N .` | 63 / 66 | measured; 3 behind OUT imm8 at even alignment |
| XCH [d16],r (87 06) | `P Y . PP2 D . Z G N .` | 63 / 66 | measured; the same 3 |
| DEC word [BW+d16] (FF 8F) | INC's: `P . . B Y . PP2 . DZ G N .` | 66 / 66 | measured |
| SHL word [BW+d16],1 (D1 A7) | `P . B Y . PP2 D . . . . . Z G N .` | 66 / 66 | measured |
| MOV [BW+d16],r ; [BW+IX+d16],r ; [d16],r (89 87 / 80 / 06) | by the model's mode rule (no change) | 60, 59, 60 / 66 | the misses: twice, behind PUSH (the store against the chain, Q33) and 3 behind OUT |
| MOV r,[BP+IY+d16] ; r,[IX+d16] (8B 83 / 84) | by rule | 63, 66 / 66 | |
| MOV word [BW+IX+d16],imm16 (C7 80) | `P . . . BIYPP2 . . . KPP2N .` (one word more than [BW+d16], as LEA and the load) | 61 / 66 | measured; misses twice / behind OUT |
| MOV word [BW+IX+d8],imm16 (C7 40) | the [BW+d8] routine | 65 / 66 | measured: two registers with d8 cost nothing |
| SET1 / NOT1 / CLR1 word [BW],CL ; [BW+IX],CL ; CLR1 word [BW],imm4 | the byte forms' (`S1M`, `C1M`, `C1MI`) | 63, 63, 63, 63, 66 / 66 | measured; 3 each behind OUT at even alignment |
| SET1 word [BW+d8],CL (0F 15 47) | `P . BP . . C Y . P DZ G N .` | 63 / 66 | measured: the displacement two words behind the request, as the loads |
| SET1 word [BW+d16],CL ; [d16],CL (0F 15 87 / 06) | `P . BP . . C Y . PP2 DZ G N .` | 126 / 132 | measured (the shape with the displacement in front of the request: 0) |
| TEST AW,imm16 ; CMP AW,imm16 (A9 / 3D) | ADD AW,imm16's: `. . . . BINPP2 .` | 66 / 66 each | measured |
| CVTDB (D5 0A) | `. . . BP C` + 12 words + `N .` (19 words; the fifth word waits one clock when the operand's pop starts a fetch: C, I or S, not separated) | 63 / 66 | measured; 3 in front of OUT imm8 at even alignment |
| DI (FA) | `. . BN .` (four words, the last-but-one bus-idle; CLC's `N .` 0) | 66 / 66 | measured |
| CMPBK word alone (A7) | no change | 64 / 66 | |
| JMP far [BW], CALL far [BW] (FF 2F / 1F) | `P . B Y D . U D . . F N .`, `P . B Y D . U D . . . Z D . . . Z D . . F N .` (the [d16] forms' with the displacement word and one head word gone) | 10 / 12 each | measured at W = 1, 2; the W = 0 misses are the setup store's |
| JMP near [BW], CALL near [BW] (FF 27 / 17) | even alignment `P . B Y D . . F N .` / `P . B Y D . . . Z D . . F N .`; odd alignment the request two words earlier (`P Y . D ..`) | 6 / 12 each with either | **partly read**: no one shape; at odd alignment a fetch chained behind the setup store's write is on the pins over the first words |
| REP INM / OUTM word, CW = 1, 2 | no change | 72 / 72 | |
| REP INM / OUTM word, CW = 0 | one word more than the string forms' zero-count routine (`. . . B . . . . . . . N .`) | 28 / 36 (the 11-word routine 8 / 36: the 8 others) | **partly read** |

- Common residual, **open**: behind OUT imm8 at even alignment, 3 runs a form on eleven forms
  (the memory forms of SET1 / CLR1 / NOT1, XCH [d16], the two-register d16 forms): in the SET1
  rows the commit word does not wait for the second fetch of the chain behind the I/O cycle
  (the same observation as round 20's A2 for the register forms, here on the memory forms'
  `C`); in the load the first fetch behind the I/O cycle is one clock later. Not chased.
- **The RTL (ce9ea43, direct sim) on the same programs, of 66 a form:** ADD word [BW],r 66; OR / AND
  / SUB / XOR / ADC / SBB word and ADD / OR / SUB byte [BW],r **3 each** (the build fault: only
  01 07 takes the routine); SHL 1 d16 2, DEC d16 1, TEST / CMP AW,imm16 2 each, CVTDB 0, SET1
  word [d16] / [BW+d16],CL 0, [BW+d8],CL 30, C7 [BW+IX+d16] 30, C7 [BW+IX+d8] 64, XCH [d16] 57, DI
  57, ADD [d16] / [BW+d16] / [BW+IX+d16],r 60 / 60 / 59, the d16 stores and loads 59 to 63 (the
  model's own misses), SET1 / CLR1 / NOT1 word [BW],CL 63 (as the model), CLR1 [BW],imm4 60; the
  transfers through [BW] 0 of 12 each; REP INM / OUTM word 18 of 18 at CW = 1, 2 and 4 of 18 at 0.
- Model: keys added for every row above (`model_m.info` / the MEM table); the model's default
  set now reads 17,532 of 18,972 non-interrupt socket runs (rounds 1 to 20: 14,528 of 15,726, from
  14,469, none lost; `r21m` 492 of 498; `r21f` 2,512 of 2,748, 216 of them the INC BW lead).

## Q99. The corpus frame itself: the unread state is "directly behind OUT imm8 at even alignment" (`QPr21c`, 672 runs)

The split's largest class (about 1,150 diverging corpus runs on about 110 forms) has every probe
of its encodings exact in the model **and** in the RTL, and diverges in the corpus almost only
with the subject directly behind the frame's marker at even alignment. `r21c` runs 28 of those
forms in the corpus's own frame (long shift ; marker ; X ; marker ; long shift) and in the
small set's (X ; marker):

| frame | alignment | runs | model exact | RTL exact (direct sim) |
|---|---|---|---|---|
| OUT imm8 ; X ; OUT imm8 | even | 84 | **24** | **20** |
| OUT imm8 ; X ; OUT imm8 | odd | 84 | 69 | 66 |
| PUSH ; X ; PUSH | even / odd | 168 | 168 | 168 |
| X ; OUT imm8 | even / odd | 168 | 157 | 147 |
| X ; PUSH | even / odd | 168 | 159 | 147 |

- **Measured: the state is real and neither the model nor the RTL has it.** Behind OUT imm8 at
  even alignment 20 of the 28 forms miss at every wait (MULU / MUL, ADD DW,imm16, POP [BW],
  TEST1 [BW],CL, ROL4, EXT / INS, SHL r,imm8, the two-register d16 load; IN, CVTWL and ADD4S at
  both alignments). The two-byte register forms (CMP / MOV r,r) and the three-byte SET1 r,CL
  are exact.
- **Two symptoms, read from six traces only (inferred, not a rule):** (1) for the forms whose
  first word pops a ModR/M byte or an operand, the first fetch behind the I/O cycle starts one
  clock later than the model's (two clocks behind the cycle's last clock, not one:
  `-add_dw_imm0-oo`, `-pop_m-oo`); (2) for the forms with an early bus-idle word (MULU's third
  word, SHL r,imm8's sixth) that fetch starts on time and the word, which the model lets pass
  on the fetch's first clock, passes on the fetch's second-last clock (1 + W clocks later).
  Both say the same thing: **on the first fetch behind an I/O cycle the EU and the bus unit
  are one decision apart from where the model puts them**, the other way round from Q95's open
  row. No rule; the probes are the material for round 22.
- **The PUSH frame is exact in model and RTL (168 of 168)** for these forms, yet corpus rows
  such as mulu_dw diverge behind the PUSH marker at even alignment (24 of 24, the RTL's second
  marker write one clock early). The frame alone does not reproduce it: the operand values
  (DW, AW) or the chain's start differ between the corpus program and the probe. **Unknown,
  not diagnosed** (MULU's length against its operand was not varied).
- `-ext_dl_bh` and `-add4s` miss in every frame: their operands in the corpus frame (BH as
  the length, the string registers) are not what the model carries; not scored.

## Socket runs of round 21

| family | what | runs | repeats that differ |
|---|---|---|---|
| r21m | a read against the fetch chain behind an EU cycle (ten subjects x eight leads) | 498 | 12 |
| r21f | the corpus encodings with no probe (36 forms, transfers through [BW], REP INM / OUTM word) | 2,748 | 292 |
| r21c | the corpus frame for 28 forms | 672 | 97 |

3,918 runs, each twice; 0 failed, 0 incomplete; the 401 repeats that differ, compared field by
field (`build/qp/rep20.py r21m|r21f|r21c`), differ in the strobe field only. `r21q` (480 programs)
was run in the direct sim only (Q97). Sim: corpus replay once (30,536 runs), the non-interrupt
small set (15,726 runs, `build/qp/sim21.sh`), `r21m`, `r21f`, `r21c`. No interrupt family was run.
Board left with vccb false, failure 0.

# Round 22

Tools of this round (worktree `build/qp/`): `cmp22.py` (the comparison cut at M1's own cycle, see
Q100), `sc22.py` (option sets against the whole non-interrupt socket set, gained / lost), `sh22.py`
(one act added to one word of a routine, scored on every run that holds the key), `wl22.py` (the
model's word log beside silicon), `ta22.py` (a lead ; X family per form: misses and the first-fetch
delay behind the lead's cycle), `pf22.py` (census of every fetch wanted under an EU cycle),
`bo22.py`, `bc22.py` (build check with the corrected cut), `corp22.py` / `ck22.py` (diverging corpus
runs by subject form / model key and what is directly in front). Statements are marked
**measured** / **inferred** / **unknown**.

## Q100. "The PUSH frame is exact" was a comparison artefact; behind either marker the divergence is the subject's

`model_m.compare` (and `read.window`, which `bc21.py` uses for the RTL) cut a run with a PUSH marker
at the **first memory write**. In the frame `PUSH ; X ; PUSH` that is the lead's write, in front
of X: round 21's "168 of 168 in the model and in the RTL" compared nothing of X. With the cut at
M1's own write (`cmp22.compare`: the last write before the END's OUT DW):

| frame (`QPr21c`, 28 forms) | round 21's model, old cut | round 21's model, M1's own cycle | this round's model |
|---|---|---|---|
| PUSH ; X ; PUSH, even | 84 / 84 | 59 / 84 | 79 / 84 |
| PUSH ; X ; PUSH, odd | 84 / 84 | 79 / 84 | 79 / 84 |
| OUT imm8 ; X ; OUT imm8, even | 24 / 84 | 24 / 84 | 73 / 84 |
| OUT imm8 ; X ; OUT imm8, odd | 69 / 84 | 69 / 84 | 78 / 84 |

(the misses left: `ext_dl_bh` and `add4s`, whose operands the model does not carry, 5 or 6 runs a
row; behind OUT at even alignment also `st_imm_bw_d8` at W = 0 and EXT / INS BL,DH at W = 1 / 2.)

- **Measured.** Item 2's question ("what does the corpus frame have that the probe frame lacks")
  has the answer *nothing*: the probe frame reproduces the corpus divergence (MULU DW behind PUSH
  at even alignment: silicon's second write 1 + W clocks later than round 21's model), it was not
  being compared. No operand value, chain start or predecessor is involved; the cause for MULU is
  Q102's second bus-idle word.
- Every score of this round is by `cmp22.compare`. The whole non-interrupt socket set by it:
  rounds 1 to 21 with round 21's options are the reference of the "gained / lost" figures below.
- For the builder: any RTL-against-silicon figure on a program whose lead is a PUSH and whose
  marker is a PUSH (the `-pp` programs of `r21c`) must be re-read with the new cut (`bc22.py`).

## Q101. X directly behind OUT imm8 at even alignment: not one state. Three separate things, each read

The frame at even alignment: OUT imm8's boundary with five bytes held and the bus idle, its I/O
cycle on the next three clocks (c1 c2 c3), X's first word on c1. X's first pop (the ModR/M byte)
leaves four held, so a fetch is wanted under the I/O cycle; at odd alignment seven are held and
none is. Round 21's two "symptoms" are two different mechanisms, and a third class is plain
missing words in X's own routine (Q102).

### Q101a. The first fetch behind the I/O cycle is one clock later for some X: an outcome rule over 104 forms (`r22a`)

`r22a`: OUT imm8 ; X ; OUT imm8 for 104 forms (every EA mode class of MOV r,m / MOV m,r / LEA / ADD
m,r, the immediates, POP / PUSH m, the unary group, the 0F page, the one-byte forms). Silicon's
first fetch behind the I/O cycle, in clocks after the cycle's last clock (`ta22.py QPr22a-o-`):

| X's routine (model notation) | forms | fetch starts |
|---|---|---|
| `P Y . ..` (request on the second word): every one-register load / store / ADD m,r, with or without a displacement | 30 | **+1** |
| `P . B ..`, `P . BP ..` (a bus-idle third word): MULU, TEST r,r, SHL r,1, TEST r,imm, the 0F page | 12 | **+1** |
| `P . . B ..` (a bus-idle fourth word): LEA (one register, any displacement; two registers with d8 or none), ADD r,imm8, INC r8, NOT r, INC / NOT / ADD m,imm16 / MOV m,imm16 | 17 | **+1** |
| `P . V ..` (ADD / CMP m,imm8: the request on the third word, of the kind that has no priority, Q33) | 5 | **+1** |
| `P . Y ..` (the request on the third word): the two-register + d16 forms of MOV r,m / MOV m,r / ADD m,r / CMP r,m; POP m ([BW], [BW+IX], [BW+d8]) | 8 | **+2** |
| `P . . . BI..` (three plain words, then the strict bus-idle word): ADD / CMP r16,imm16 (81 /r), LEA with two registers + d16, MOV m,imm16 with two registers + d16 | 4 | **+2** |
| no pop on the first word (five held through the cycle) | 28 | by the pop, as before |

- **Measured (39 runs of `r22a`, 25 of `r21c` / `r21f`):** the rule that reads all of them, model
  option `EU_WPRI=3`: the fetch wanted under an I/O cycle starts on the clock after the cycle,
  except that it gives way one clock when **(1)** a memory request word (Y; not V) executed on the
  cycle's last clock, or **(2)** the EU executed act-less words (no pop, no request, no bus-idle
  test, not a routine's last word) on the cycle's last clock **and** on the clock after it with no
  request outstanding. Whole socket set: **+64, 0 lost**; each half alone +42 / +22, 0 lost.
- **Measured: the phase matters, not the form.** `r22b` (OUT imm8 ; INC ; X: X's first word on the
  cycle's last clock) has the fetch at +1 for every one of the late forms, and the model reads
  them with the same rule (the words that fall on c3 and c3 + 1 are then `P` and the second word).
- **Rounds 4 to 7's EU_EPRI is the same family** (a boundary executing on the clock after the
  cycle holds the fetch one clock: NOP, XCH AW,r behind OUT imm8). Together: the fetch behind an
  I/O cycle is on time when, on the cycle's last clock or the next, the EU pops, tests the bus,
  waits, or has a request posted before the cycle's last clock; it is one clock late when the
  EU does none of that, or posts a request on the last clock itself.
- **Inferred (mechanism, two candidates, not separated):** (a) the bus unit's choice of the cycle
  behind an EU cycle is taken with the EU's request line: a request raised on the cycle's last
  clock reopens the choice (the read is not yet ripe, so the fetch is taken, one clock later) -
  the same register as REQ_PRI (Q5); (b) for the act-less case, the fetch's start behind an I/O
  cycle is enabled by an EU-side strobe (queue read / bus test) and otherwise by the idle state one
  clock later. **Unknown:** which register; why a boundary on the clock after the cycle delays
  the fetch while a boundary on the cycle's last clock does not (`OUT ; INC ; X`).
- **Only the I/O write has this phase:** X's first word runs on the first clock of OUT's cycle;
  behind PUSH, a store, IN and POP the routine ends on (or after) the cycle's last clock, so X's
  third and fourth words never fall on c3 / c3 + 1 (`r22c`, `r22d`: no late fetch there, see Q103).

### Q101b. The commit word against the chain's second fetch: it passes on that fetch's third-last clock

Behind the I/O cycle at even alignment a 0F-page routine (`P . BP . C ..` / `P . BP . . C ..`) and
SHL r,imm8 (`P . . BP . x ..`) meet the chain I/O, fetch A, fetch B. Silicon runs 3 clocks (0F) or
1 clock (SHL) ahead of round 21's model at every wait: the word that the model holds until B's end
(the commit word C) or until B's second-last clock (SHL's sixth word as a slot word S) passes on
**B's third-last clock** (its first clock at W = 0, second at W = 1, third at W = 2).

- **Measured,** model option `CH3=2` with SHL r,imm8's sixth word a commit word (`SHLI_ACT=C`):
  **+41, 0 lost** (ROL4, TEST1 / SET1 / NOT1 / CLR1 on memory by CL with every displacement, EXT /
  INS, SHL r,imm8 / imm4: `QPr21c-*-oo`, `QPr21f-f-*-o`, `QPr22a-o-{rol4,t1m}`). The kind of the EU
  cycle in front does not enter the rule (0 lost with every kind allowed).
- **Measured not to be the rule for the other waiting words:** the long shift's fourth word (S),
  OUT DW's first word (A) and an I/O request word (X) against the same fetch B keep "the slot is
  the pin cycle two clocks earlier" (they pass on B's second-last clock): the same act for them
  loses 81 to 134 runs.
- **Inferred:** against the first fetch behind an EU cycle nothing changes (C_NOCH, Q42). The
  commit word reads a bus-unit level that falls three clocks before the pin end of a fetch chained
  to the fetch behind an EU cycle. **Unknown:** the register; why three and not two (S_LAG).

## Q102. Bus-idle words that the routines were missing (they show only with a fetch on the pins at that word, which is what "directly behind a marker at even alignment" does)

`sh22.py KEY`: one act added to one word, every socket run with the key; all 0 lost.

| instruction | routine now | was | gained | corpus rows |
|---|---|---|---|---|
| MULU / MUL / DIVU / DIV r (F6 / F7 /4../7, register) | `P . B . B ..` (**a second bus-idle word, the fifth**) | `P . B ..` | +24 (`QPr21c-*-{mulu_aw,mulu_dw,mul_cw}-{oo,pp}` 18, `QPr9-divuw-{a,s}` 6: two round-9 misses closed) | mulu_aw, mulu_dw, mul_cw, divu_ix |
| CVTWL (99) | `. . B . . . . N .` | no bus-idle word | +9 | cvtwl |
| IN AL / AW,DW (EC / ED) | `. . BX DN .` (the request word is bus-idle; `S . X DN .` scores the same) | `. . X DN .` | +18 | in_al_dw, in_aw_dw |
| LODS (AC / AD) | `. . B . Y DN .` (`S . . . Y DN .` the same) | `. . . . Y DN .` | +7 | ldm_b, ldm_w |
| ADJ4A / ADJ4S (27 / 2F) | `. . . B . . . . N .` (`. S . ..` the same) | no bus-idle word | +4 | adj4a |
| TEST word [BW],imm16 (F7 07) | `P . B . . BY DPP2 . BN .` (the request word bus-idle, as the 81 group's) | `.. Y ..` | +4 | test_m_imm |
| XCH [d16],r (87 06) ; XCH [BW],r | `P Y . PP2 D . BZ G N .` ; `P Y . . D . BZ G N .` (the write's request word bus-idle) | `.. Z ..` | +3 ; 0 | xch_dir_aw |
| REP INM / OUTM word, CW = 0 | `. . . . B . . . . . . N .`: 12 words, the bus-idle word the fifth (as these two forms' own REP heads) | the string forms' 11 words | +28 (36 / 36 of the CW = 0 runs; round 21's "28 of 36") | rep_inm_w, rep_outm_w |

**Measured** (scores); **inferred** where two placements score the same (named in the row).

## Q103. Other leads and preludes (`r22b`, `r22c`, `r22d`)

None of these families was used to form a rule (the rules were read on `r21c`, `r21f` and `r22a`).

| family | what | runs | model exact |
|---|---|---|---|
| `r22b` | OUT imm8 ; INC BW ; X, 104 forms | 624 | 532 (the 92: odd-BW forms, Q105; ADD / CMP r16,imm16 and LEA two-register d16 at even alignment W = 0, below) |
| `r22c` | PUSH ; X ; OUT imm8, 104 forms | 624 | 614 (stores with d16 at even alignment 8, MOV m,imm16 two-register d16 1, 1 other) |
| `r22d` | 40 forms behind nine leads | 2,154 | **2,102** |

`r22d` per lead (of 240; OUT DW of 234): OUT ; CBW 233, OUT ; CLC 233, CLC ; OUT 232, NOP ; OUT 232,
OUT imm8,AW 232, IN imm8 239, a store 236, POP 239, OUT DW 226.

- **Measured: Q101a's late fetch goes with the I/O write, whatever its form and wherever the
  alignment puts it.** Behind OUT imm8,AW and OUT DW (DW = 22h) the same forms have the fetch at
  + 2 and the rule reads them; with one byte in front of the OUT (NOP ; OUT, CLC ; OUT) the state
  moves to the other alignment and is read there. Behind IN imm8, a store, POP and PUSH no fetch
  is late (X's first word runs on or behind the cycle's last clock).
- **Measured: the prelude (bytes held when the I/O cycle ends) is not a variable of its own**: it
  acts only through "a fetch is wanted under the cycle" (four held behind X's first pop).
- **Measured: waits.** The I/O cycle has no wait state here (three clocks at W = 0, 1, 2); every
  rule of this round holds at the three waits with the fetch's own length (the scores are over
  the three).
- **Open (12 + 3 runs):** OUT ; CBW / CLC / INC ; X for the `P . . . BI` forms at even alignment,
  W = 0: X's first word falls on c3 + 1 with the fetch, and the chain's **second** fetch is one
  clock late when the word in front of the strict bus-idle word executes on the clock it would
  start. Round 13's CH_BNEXT says this for chains behind a memory write; allowing it behind an
  I/O write (`LAG_K=WO;CH_K=WO`) reads 9 of them and loses 5 runs of TEST r,imm16 behind OUT at
  W = 0: **not installed**. It also says what Q101a's second case is: stated as "the fetch
  wanted under the I/O cycle is not started on a clock whose executed word is followed by a
  bus-idle word" (`EU_BNEXT=1` in place of bit 2 of `EU_WPRI`) it gives the identical result on
  all 23,670 runs. **Inferred:** the microcode word in front of a bus-idle word carries the
  hold on new fetch starts (one bit of that word, no look-ahead across instructions).
- The remaining misses: MOV m,imm16 at one alignment behind every OUT lead and ADD m,imm8 with
  two registers + d16 (Q106).

## Q104. JMP / CALL near [BW]: one shape; the boundary's byte test counts the word arriving on that clock

Round 21: "the request two words earlier at odd alignment" (6 / 12 a form). The shape is the even
one at both alignments (`P . B Y D . . F N .` / `P . B Y D . . . Z D . . F N .`). What differs at odd
alignment is the **boundary in front**: behind MOV [BW],imm16 two bytes are held behind the staged
FF when the first fetch behind the store's write ends; silicon's boundary executes on that
fetch's last clock, the model's (three bytes behind a ModR/M opcode, EMIN_M) waited for the next
fetch's.

- **Measured:** for FF /2 /3 /4 /5 on memory the three-byte test counts the bytes the fetch
  delivers on its last clock (`EMIN_ML`): **+16, 0 lost** (`QPr21f-t-{jmpmbw,callmbw}-*` 12 of the
  12 misses; `QPr12a-tr-{callm,jmpm}-*` 4, misses since round 12).
- **Not general (measured):** for every ModR/M opcode the same act gains 28 and loses 201. The
  12 it gains outside the FF group (TEST1 / ROL4 of `QPr5-em2` / `QPr8-em3`, NEG [BW+d16] behind MOV
  r,imm16) say the 0F page and F7 /3 may share it: **inferred, not installed**.
- **Unknown:** why the FF group's test sees the arriving word (a two-byte need with a registered
  count would execute two clocks too early: tried, `EMIN_M=2`).
- Left: CALL / JMP far [BW] at even alignment, W = 0 (4 runs).

## Q105. The INC BW lead: an artefact of the model (BW odd), not of silicon

INC BW in front of a [BW] operand makes the word odd: two byte cycles. The model took BW's parity
from the frame's registers only. With BW followed through INC / DEC BW (`BW_TRACK=1`, and POP m,
the ALU m,r group and the 0F page added to the forms that split) the `-i` stems of rounds 17, 20
and 21 are read: **+460 with `r22b`, 0 lost**. `r22b` used INC BW as its one-byte spacer (a design slip of
this round): its misses left are the odd-address forms the model does not split correctly (PUSH m
/ POP m: the stack half is even; stores at W = 0).

## Q106. Round 21's open row (Q95, 6 runs) and what was not read

- `QPr21m-m-{addi8x,cmpi8x}-o` at even alignment: the request (V) on the I/O cycle's last clock,
  four held, loses to the chain's second fetch. Q101a's first clause does not apply to V (ADD
  m,imm8 with no displacement has the fetch on time). Still open, 6 runs.
- Stores with d16 behind PUSH and behind OUT ; INC at even alignment (`r22c` `st87`, `st06`,
  `st80`; 8 + 9 runs): Q33's class, no machine, unchanged.
- EXT / INS BL,DH behind OUT at even alignment, W = 1 / 2 (4 runs); `ext_dl_bh`, `add4s` (operands).

## Q107. The rules of this round on the corpus itself, offline (the coordinator's `corpus_model.py`)

`corpus_model.py` runs `model_m` on the 30,536 corpus runs (`traces/logs/cm22.txt`,
`cm-rules.txt`; cross-tab against land14's RTL miss list, 27,604 RTL-exact):

| | round 21's model | this round's |
|---|---|---|
| model-exact | 24,101 | **25,396** (+1,307, -12) |
| model-miss | 3,199 | 2,258 |
| no routine / error | 3,236 | 2,882 |
| model miss and RTL miss ("unread states") | 1,828 | **899** |
| model exact and RTL miss (unbuilt rules / build faults) | 716 | **1,651** |
| model miss and RTL exact | 1,371 | 1,359 |

Corpus runs each rule carries, **measured** by switching it off alone: Q101a (`EU_WPRI`) 256;
Q101b (`CH3`, `SHLI_ACT`) 335; MULU / MUL / DIV's second bus-idle word 84; the shapes of Q102
(CVTWL, IN DW, LODS, ADJ4, TEST m,imm16, XCH [d16], REP INM / OUTM zero) 260; the rest of the gain
is EA modes that had no routine (354 newly modelled). Q104's test and Q105 change no corpus run
(the corpus's transfers through [BW] are not run by the model: no pointer value).

- **Lost, 12 runs (measured):** `F19-d-out-mov{awdw,cwaw,dwaw}-in{b,w}`: OUT ; MOV r,r ; IN AL / AW,DW.
  Both placements of IN DW's bus-idle word (`. . BX DN .`, `S . X DN .`) score the same on
  the corpus (334 of 348 against 236 without). The 12 are RTL-exact: **the builder should keep
  the RTL's IN DW behaviour on that frame as a gate when building the shape.** Not diagnosed.
- **The largest state cluster left** (`traces/logs/clusters22.txt`): EXT / INS (register and imm4
  forms) directly behind OUT imm8 at even alignment at W = 1 and W = 2, the field's read one
  clock late in the model: 57 + 57 corpus runs (4 socket runs, `QPr21c-c-{ext_bl_dh,ins_bl_dh}-oo`).
  With Q101b the commit word passes on fetch B's third-last clock and W = 0 is exact; at W >= 1
  silicon's read is one clock earlier still. Three head variants tried, all lose 200 to 300
  runs. Read off the four socket runs (inferred): if the whole difference is the commit word's,
  it passes 0 / 0 / 1 clocks after fetch B's first clock at W = 0 / 1 / 2 for EXT / INS, against
  0 / 1 / 2 for ROL4 and the SET1 family with the same head in front of it; a plain bus-idle
  word would give 0 / 0 / 0. **Unread; the next round's first item.**
- Next clusters: the trailing long shift behind a marker at odd alignment with six held (I/O
  write early by 3: 37 + 14, behind MOV m,imm16 forms: the store class), JMP short behind OUT
  (fetch late by 1: 25 + 19; spec 15 A1's class), REP MOVBK word's successor 114.

## Socket runs of round 22

| family | what | runs | repeats that differ |
|---|---|---|---|
| r22a | OUT imm8 ; X ; OUT imm8, 104 forms | 624 | 8 |
| r22b | OUT imm8 ; INC BW ; X | 624 | 47 |
| r22c | PUSH ; X ; OUT imm8 | 624 | 68 |
| r22d | 40 forms behind nine leads | 2,154 | 230 |

4,026 runs, each twice (353 repeats differ); 0 failed, 0 incomplete; the repeats that differ, compared field by field
(`build/qp/rep20.py r22a|r22b|r22c|r22d`), differ in the strobe field only. No sim of the RTL
was completed this round (two were started and stopped: the machine was shared, and the RTL
moved to land14 meanwhile); no corpus replay; the corpus was scored offline with the model only.
No interrupt family was run. Board left with vccb false (read back after the last run), failure 0.

**The model against the non-interrupt socket set (by `cmp22.compare`):** 22,378 of 23,670. Rounds 1
to 21: 18,518 of 19,644 (18,076 with round 21's options: **+442, 0 lost**; the INC BW lead artefact a large part of it). Round 22: 3,860 of 4,026. Against round 21's options on everything: +952, 0
lost. Misses of rounds 1 to 21 by family: `r18c` 624 (REP compares), the interrupt-frame stems
of `r14s` to `r16e` 330, `r21c` 49, `r21f` 30, `r8` 26, `r20a` 21, others under 20.

# Round 23

## Q108. The DMA-end request (DIC0 / DIC1): a scanned source. It enters at the request flag, 3 to 4 clocks in front of the terminal cycle's first pin clock, and passes every stage INTPn passes behind the pin

Families (`gen_r23.py`, W = 0, both alignments, every program twice; the control of each run is
its **masked twin**: the same program with DIC0 = 47h, so the same transfer and no interrupt):

- `r23b<train>`: a burst, memory to memory, TC 2, started by the TDMA store (DMAM0 = 8Ch) in the
  body; behind the store a pad of 0 to 13 clocks and the train (MOV AW,[BW] / NOP / INC BW); 0 to
  3 CLCs in front of the store. The transfer is taken at an instruction start about 30 clocks
  behind the store, so the pads and CLCs move **the whole transfer** against the clock from M0
  (tw = the first pin clock of the terminal write: 129 to 150), not the train against the
  transfer: behind the transfer the train always resumes the same way (first read at tw + 14 / 15).
- `r23a<train>`: a single transfer, I/O to memory, TC 1, started by a DMARQ0 edge stepped one
  clock (60 to 96 from M0); the transfer lands on the train's instruction starts (tw every 10
  clocks in the load train).
- `r23dld`: `r23bld` with DIC0 at level 5. `r23eld`: `r23bld` on channel 1 (DIC1, vector 21).
  `r23c`: `r23ald` at six edges with the pins TC0 and DMAAK0 recorded.

Tools: `build/qp/an23.py` (per run: tw, the vector read, the instruction pushed, the first event
that differs from the twin), `c23.py` (load trains: the clocks c for which Q83's rule reproduces
the run, the train's cycles and pops taken from the twin), `l23.py` (any train: distributions),
`pc23.py` (the same lattice read from INTP0's edge sweeps of rounds 17 and 19), `ev23.py`.

**Measured.**

1. **Not a fixed path from the terminal cycle (H2, H3 rejected).** In `r23bld` the vector read is
   34 to 45 clocks behind tw and the clock c on which the request stands at the EU (read by
   Q83's rule from the pushed instruction, the vector-read clock and the displaced cycles) is 7
   to 22 clocks behind tw. The best single value of c - tw reproduces 56 of 104 runs.
2. **c is on a 16-clock lattice that is fixed against M0, not against the transfer: c = the
   first clock == 2 (even alignment) / 3 (odd) mod 16 that is at least 7 clocks behind tw.**
   `r23bld`: 104 of 104, and (L, m) = (2, 7) / (3, 7) is the only cell of the grid L = 0..15,
   m = -4..29 that does it (tw + 7 is served by the lattice clock: 5 runs; tw + 6 is not: the 7
   runs with c - tw = 22). `r23ald` (I/O to memory, one write): 74 of 74 with the same lattice;
   its tw takes few values, so m is only bracketed there (5 to 8 at even alignment).
   **Channel 1** (`r23eld`, DIC1, vector 21): 104 of 104, (2, 7) / (3, 7) the only cells.
   **Level 5** (`r23dld`): 104 of 104 with the lattice 14 / 15 mod 16 and m = 7 (even alignment:
   7 or 8), 4 clocks earlier, as INTP0's level-5 lattice is. Opcode-only trains (`r23bnop`,
   `r23anop`, `r23binc`, `r23ami8`, 504 unmasked runs; no model of the pops behind a transfer, so
   a weaker check, `l23.py`): the replaced pop is 5 to 11 clocks behind the lattice clock in
   every run (NOP 8 to 11, and 6 where c = tw + 7 falls on the resuming words; INC 5 to 9; MOV
   r8,imm8 6 to 11), as Q83's rule gives for those trains; **consistent, not scored run by run**.
3. **It is INTP0's lattice, to the clock.** `pc23.py` on round 17's and 19's INTP0 families
   (level 7, the same EI directly in front of the event port's OUT): c = the first clock == 2 / 3
   mod 16 (even / odd) at or after e + 10.2 (e = the pin edge; 10.125 to 10.25 is the only lead
   that does `r17r`, `r17p` and `r19qp0`, 246 of 246). INTP0 at level 5 (`r15l5`): 14 / 15 mod
   16, 4 clocks earlier (2 clocks a level), and DIC0 at level 5 moves with it (item 2). So the 16-clock lattice is the level scan's
   round as EI restarted it (stage 3), and DIC0's request is looked at where INTP0's is.
4. **The hidden occupation is there** (Q82's displacements against the masked twin): in
   `r23bld` the first cycle of the twin that is moved is a read with its first clock at c or
   c + 1, 2 clocks late (10 runs), or a prefetch at c, c + 1 (3 late, 2 late) or chained at c + 2
   (2 late) (30 runs); none before c in any run. In `r23ald` 33 of 74 runs (reads 2 late: 20).
   `r23dld` 32 of 104 (reads 12), `r23eld` 40 of 104 (reads 10), all at c, c + 1 (chained
   prefetch c + 2). A prefetch moved by the occupation either starts at c + 3 with the read
   behind it waiting for it, or is not made in front of that read; which of the two: not read
   (`c23.py` accepts either).
5. **Behind c the rule is Q83's unchanged**: event (first word, the datum word current), the
   occupation, 5 clocks, the first pop replaced, vector read 17 clocks behind that pop. With the
   lattice of 2 nothing else is free: `r23bld` 104 of 104, `r23ald` 74 of 74, `r23dld` 104 of 104, `r23eld` 104 of 104 (pushed
   instruction, vector-read clock and every read in front of it; the words of the DMA routine
   in front of the first resumed instruction are taken as events on every clock: not read).
6. **TC0 on the pin** (`r23c`, 12 runs, `tc23.py`, I/O to memory): DMAAK0 low from the write's
   first clock (tw + 0.0) to tw + 2.5; TC0 low from tw + 0.5 to tw + 2.38, identical in all 12. f4_dma's "one instruction runs before
   DIC's interrupt" is this: c >= tw + 7, then at least the event and 5 clocks.

**The rule as stages.**

| # | stage | clock | length | status |
|---|---|---|---|---|
| D1 | DIC's request flag is set by the transfer whose count ends | the bus unit's terminal cycle (or the DMA routine's word that posts it) | so that the scan sees it as it sees INTP0's flag for a pin edge 3.125 to 4.25 clocks in front of tw (10.2 - 7, tw a whole clock) | threshold: measured. What sets it: **inferred**, two candidates not separated: (i) the terminal-count signal that drives TC0 low at tw + 0.5 (item 6): INTP0's flag is readable 4.1 to 6.1 clocks behind its pin edge (Q72), i.e. at tw - 0.15 to tw + 2.975 for the equivalent edge, which contains tw + 0.5; (ii) the routine's word that posts the terminal write, 4 clocks in front of tw (POST_LAT). Not the cycle's end, not the routine's end (the RTL's `dm_rs`). The exact clock: **unknown** |
| 3 | the level scan, as INTPn | divided clock | 0 to 15 clocks (the lattice) | measured (item 2, 3) |
| 4 | the 7-clock line | CPU clock | 7 | inferred (same lattice clock as INTP0's, whose line is measured) |
| 6a-6c | event, 2-clock occupation, 5 clocks, the first pop | as spec 15 | | measured (items 4, 5) |

No sampler (1a) and no edge detector (2): what is shorter than INTPn's path is only what is in
front of the flag. H1 holds with that correction; H2 (behind the scan) and H3 (the DMA cycle
as the event / occupation) are rejected: the occupation is a separate 2 clocks 7 to 22 clocks
behind the terminal cycle, and the terminal cycle displaces nothing by itself.

## Q109. On which word the request is read: the pop (the N word executing), for INT's latch and for the vectored take alike

From existing traces only (`build/qp/w23.py`, `pc23.py anc=E`). Model notation: NOP `N...`
(4 words, the pop on word 1, the boundary word E = word 4), INC `N.` (pop on word 1, E word 2),
CBW `N..` (pop on word 1, E word 3), MOV AW,[BW] `P Y . DN .` (pop on word 4, the datum word, E
word 5), MOV r8,imm8 `. . . BNP .` (pop on word 4).

- **(a) INT's latch (stage 5), measured.** For each train the interval of leads (from the pin
  edge) that puts the replaced instruction's anchor first at or after e + lead: with the pop as
  anchor the interval is (9.0, 9.25] in the NOP train (`r17i`) and (9.0, 9.5] in CBW (`r17r`),
  INC at W = 1, 2, NOP at W = 1, 2, MOV AW,[BW], the mixed train (`r18t*`): one lead, 9.125,
  everywhere. With the boundary word E as anchor: NOP (12.0, 12.25], CBW (11.0, 11.5], MOV
  AW,[BW] (10.0, 10.5] at even alignment and no lead at odd, INC and the mixed train no single lead (lower bound 12 to 13
  above upper bound 10.5 to 11.5). **The latch is read on the clock the N word executes**: word 1 of NOP /
  INC / CBW, word 4 of MOV r,[BW] (the datum word, when the datum arrives). The instruction
  that holds that N word then runs to its E word (3 / 1 / 2 / 1 clocks later) without loading
  the popped opcode; a request arriving in those clocks is not seen until the next pop.
- **(b) The vectored take (6a to 6c), measured.** The event words are the first word and the N
  word (executing or waiting); in NOP / INC / CBW these are the same word 1; in MOV r,[BW]
  word 1 and word 4 from the clock it becomes current. The pop replaced is the first N word
  executing at or after the occupation's first clock + 5. Test of the anchor: `r19qp0` (NOP,
  MOV r8,imm8, MOV AW,[BW] moved by pads) with the pop: 78 of 78 on the lattice of Q108; with
  the E word in the pop's place (0 to 3 clocks allowed for): 62, 57, 50, 60 of 78.
- **For the RTL (inferred from the builder's figures).** The RTL reads at its E word (`x_end`),
  which it reports 2 clocks behind silicon's pop in NOP, 1 in INC / CBW, 0 in a load: that is
  the model's E - N distance less one (3, 2, 1 less one; INC's 1 against 0 is the fetch-limited
  train's stall). So the RTL's `x_end` is the model's E word less one clock in all four, and
  the difference is not in the routines' lengths: it is that stage 5 and 6c's "replace this
  pop" must be read on the pop word (the sequencer's existing `wk_nx.pop`, registered, not
  stalled), the decision held to the boundary.

## Socket runs of round 23

| family | what | runs | repeats that differ |
|---|---|---|---|
| r23t | the first DMA program alone (check against f4_dma: one write at D060h, vector 20 behind it, two instructions run) | 4 | 0 |
| r23bld / r23bnop / r23binc | TDMA burst, memory to memory, pads and CLCs; trains MOV AW,[BW] / NOP / INC BW | 208 each | 0 / 25 / 39 |
| r23ald / r23anop / r23ami8 | DMARQ0 single transfer, I/O to memory, edge 60 to 96 | 148 each | 4 / 33 / 36 |
| r23c | r23ald at six edges, TC0 and DMAAK0 recorded | 12 | 0 |
| r23dld | r23bld, DIC0 at level 5 | 208 | 0 |
| r23eld | r23bld on channel 1 | 208 | 34 |

1,500 runs, each twice; 0 failed, 0 incomplete; the 171 repeats that differ, compared field by
field (`build/qp/rep20.py r23...`), differ in the strobe field only (r23c: not put through
rep20, its repeats are identical). Half of the runs of the a / b / d / e families are the masked
twins. No sim of the RTL was run; no corpus work; item 3 (EXT / INS behind OUT imm8 with
waits) was not started. W = 1 / 2 not run. Board left with vccb False (read back by
`nuboard.cli status` after the last run), failure 0.

# Round 24

Tools of this round (worktree `build/qp/`): `cm24.sh` (the coordinator's `corpus_model.py` on the whole
corpus with an option set, 10 s), `cw24.py` (one corpus run: silicon and model events, the model's word
log with the bytes held), `ls24.py` (socket runs by id: exact or first divergence), `sh24.py` (one act
added to one word, scored on named socket rounds), `acq24.sh`; in the hand-back's `work/`: `gl2.py`
(gained / lost between two corpus scores), `off.py` (what a rule carries: switched off alone),
`cl2.py` (the RTL miss rows by state). Every score is by `cmp22.compare` (socket) or by
`corpus_model.py` (corpus; RTL miss list of land17, 29,167 of 30,536 RTL-exact). Statements are marked
**measured** / **inferred** / **unknown**. Most of this round was read from the corpus traces first; the
socket families (`r24a` to `r24d`, 1,170 runs) were designed to confirm or separate what the corpus said.

## Q110. EXT / INS directly behind an I/O write at even alignment, W = 1 and 2: the bit-field head's commit word passes one clock earlier than ROL4's (item 1)

The frame (Q101b): I/O cycle on s .. s + 2, X's first word on s; fetch A on s + 3, fetch B back to
back behind it. EXT / INS (`P . BP . C . Y D`, imm4: `P . BP . C . . Y D`) reach the commit word on s + 5.
Silicon's first read, in clocks from s:

| | W = 0 | W = 1 | W = 2 |
|---|---|---|---|
| EXT / INS r,r (`0F 33 / 31`) | 12 | 13 | 15 |
| EXT / INS r,imm4 (`0F 3B / 39`) | 13 | 14 | 16 |
| the commit word passes on (both forms) | s + 6 | s + 7 | s + 9 |
| fetch B's pin clocks | s + 6 .. 8 | s + 7 .. 10 | s + 8 .. 12 |
| ROL4 / ROR4 r, SHL r,imm8: their commit word passes on | s + 6 | s + 8 | s + 10 |

- **Measured:** the bit-field head's commit word passes on fetch B's **fourth-last** clock, and not
  before B's first clock (B's first clock at W = 0 and 1, its second at W = 2); ROL4 / ROR4 r and SHL
  r,imm8 pass on B's third-last clock (Q101b), measured again here. Model `CH3_N=1` for the keys EXT,
  INS, EXTI, INSI: socket **+20, 0 lost** (`QPr21c-c-{ext,ins}_bl_dh-oo` 4, `QPr24a-{o,e7}-{extr,exti,
  insr,insi}` 16), corpus **+112, 0 lost** (every run of the cluster "read late by 1 behind OUT, pE,
  W = 1 / 2": F32, F34). The same act for ROL4 / ROR4 / SHL r,imm8 loses 12 runs of `r24a` and 24 of
  rounds 21 / 22: it is not one rule for every commit word.
- **Measured: the state exists only directly behind an I/O write at even alignment.** `r24a` ran
  the four forms and six others behind nine leads; behind OUT ; CLC / CBW / NOP, PUSH, a store,
  IN imm8 and POP all four bit-field forms are exact with either reading (168 runs), as are the odd
  alignments (24) and W = 0 (8): a spacer does not move the word against the chain, it removes
  the chain's second fetch from under it. The spacer families do not separate anything further.
- **Measured not to be the alternative** "a plain bus-idle word in place of the commit word, the
  request word's own wait doing the rest": reads the r,r forms (12 of the 16 `r24a` runs, corpus
  +72) and leaves the imm4 forms one clock early at W = 2 (22 corpus runs, 4 socket).
- **Inferred:** two word kinds, or one kind with a second waiting word in ROL4 / ROR4 / SHL. With
  the head's microcode equal up to the commit word in EXT and ROL4 (`open ; rl=1 bi ; open ; bi alt`)
  the difference is in what follows: EXT's next word loads the address register from IX and the
  request word comes one (r,r) or two (imm4) words later; ROL4's next words are the ALU word and
  the two register writes; SHL's is the count loop. Three decompositions fit every run: (a) the
  commit word waits by fetch B's slot moved one clock further ahead for EXT / INS; (b) every commit
  word passes on the fourth-last clock and ROL4's first register-file word (and SHL's loop entry)
  waits to B's second-last clock; (c) the wait is taken with the *next* word's kind (a word that
  only loads the address register is released a clock sooner). **Unknown:** which; no probe of
  this round separates them (the phase cannot be moved without losing the chain).
- TEST1 / SET1 / CLR1 on memory by CL (`P . BP . . C Y ..`) are indifferent: the request word's own
  wait (Y_LEFT) lands the read on the same clock with either kind.
- CVTDB (`. . . BP C ..`, commit word directly behind the release) is **not read**: 42 of its 54 `r24a`
  runs miss by one clock (the model late) behind every lead with a fetch at the word; a word that
  passes from the fetch's second-last clock (act L) reads most of them (45 runs gained) and loses the
  81 exact runs of `r21f`. 6 corpus rows (`M1:out` behind cvtdb). Open.

## Q111. The frame trailer, "I/O write early by 3 / 4": a bus-idle word that pops does not pass on the first clock of a needed back-to-back fetch (item 2, first half)

The cluster (69 corpus runs: the marker OUT imm8 behind a store with an immediate, 37 + 14 at W = 0,
10 + 8 at W = 1 / 2; model and RTL diverge on the same clock): the store's last word pops the next
opcode and the immediate (`KNPP2`), leaving **two** bytes behind the staged E6. The first fetch behind
the write (F1) brings four; the marker's fourth word (`BP`, the port byte's release) meets the fetch
back to back behind F1 (F2). Silicon's I/O cycle is one whole fetch cycle later than the model's:
the word waits F2 out and passes on F3's first clock. The same frame at the other alignment
(three held at the boundary: five held at F2's start, four behind the word's pop) is exact with
the word passing on F2's first clock.

- **Measured: the state variable is the bytes held when the back-to-back fetch starts, counted
  before the word's own pop.** With five held the fetch is the continuation that the word's pop
  completes (the word passes on its first clock, as it always has in the model); with four or
  fewer the fetch was needed without the pop, and a bus-idle word that pops (P, P2 or N on the word)
  does not pass on its first clock: it waits by the pin cycle and passes behind it, or on the first
  clock of a following five-held continuation. Model `B_I4=4`: corpus **+92, 0 lost** (the 69, and 23
  runs of the cluster "store with d8 twice, fetch against write order", whose second store's `BYP`
  word is the popping word), socket **+57, 0 lost** (`QPr24b-{stim07,stim80}-{out8,e7,in8}` 12 and
  `-ri8` 4; the stores with an immediate in front of the marker in `QPr21c / 21f / 22a / 22c / 22d`:
  round 22's open rows; `QPr13a-fw-c7-*-i8` 5; `QPr21f-t-{callfmbw,jmpfmbw}` 4: Q104's "left" rows;
  `QPr21f-f-stix8-2`, `QPr9-stid8-2`; the list is in `traces/logs/sc-e.txt`).
- **Measured: a bus-idle word with no pop passes as before** (a store immediate's request word `BY`
  directly behind another store with an immediate: the same act for it loses 54 corpus runs).
- **Measured: not a property of OUT imm8.** `r24b` put seven instructions that end on an
  immediate in front of nine followers: the followers with a popping bus-idle word in that phase
  (OUT imm8, OUT imm8,AW, IN imm8: `BP`; MOV AL,imm8: `BNP`) show it, behind the two stores that
  leave two bytes; PUSH, MOV AW,[d16], MOV AW,[BW], NOP, MOV DS1,AW have no such word there and are
  exact. A rival, "OUT / IN imm8's boundary needs three bytes held" (`EMIN_L=3`), reads the 69 corpus
  runs and 42 socket runs too, but not MOV AL,imm8 (4), the stores with d8 (23 corpus) or the 15
  older socket runs: **rejected** (the switch is left in).
- **Inferred (mechanism):** the bus-idle test reads the bus unit's "a fetch is due" level, which
  is up before the clock for a needed fetch (four or fewer held at the previous fetch's end) and
  comes up only with the pop for a five-held continuation. The word's own pop is what would have
  made the fetch at five; at four it changes nothing, so the word is not ahead of the decision.
  **Unknown:** why the test is not applied to a word without a pop (CH_BNEXT, round 13, is the
  other face: the chained fetch is not started when the next word is a bus-idle word; in the model
  the stalled popping word does not hold the fetch back).
- For the builder: on the corpus this rule and the RTL's present behaviour differ on exactly the
  92 rows; nothing RTL-exact moves in the model.

## Q112. A request word on a fetch's last clock cancels the back-to-back fetch; a pop on the next clock raises it again

REQ_PRI (Q5, 9 runs) said: the five-held continuation is not made when an EU request word executed on
the fetch's last clock. Two corpus clusters extend it in both directions.

- **Measured (no fetch even at four held):** PUSH behind a store with an immediate (two held at the
  boundary; `Y` on F1's last clock; four held behind F1): silicon starts no fetch on the next clock,
  one a clock later, then the write (51 corpus runs, "M1:push behind st_imm, fetch early by 1" in
  the model and the RTL).
- **Measured (the continuation is made when a pop falls on that clock):** MOV [d16],AW behind MOV
  AW,imm16 (`. . Y PP2 G N .`: `Y` on the fetch's last clock, `PP2` on the next, five held behind the
  pop): silicon makes the back-to-back fetch and the write follows it (95 corpus runs, the largest
  part of "fetch against write order": F37's pointer and vector set-ups, F30-store-br).
- Model `REQ_PRI=5`: the request word cancels the continuation whatever the count; a pop on the
  next clock raises it again at the usual five held; with no pop no fetch starts on that clock
  and the idle rule (four or fewer) starts one a clock later. Corpus **+146, 0 lost**; socket **+5, 0
  lost** (`QPr21f-f-stix16-mp`, `QPr24b-{ri,ai16}-ldacc`, `QPr24b-{stim07,stim80}-push` with Q115's PUSH
  shape). The halves alone: "no fetch at all" loses 27 corpus runs (the stores whose `PP2` follows
  the request word); "unless a pop" alone gains the 51.
- **Inferred:** the request word takes the bus unit's next decision (the EU cycle is not ripe, so
  nothing starts); a queue read on the following clock is a new fetch request of its own (the same
  statement as CHAIN_POP). **Unknown:** the latch; the socket evidence is thin (5 runs), the corpus's
  is not (146 runs, two frames, both alignments, W = 0 only: at W >= 1 the request word waits for
  the fetch's last two clocks and the phase does not arise).

## Q113. The frame trailer, "fetch early by 1": at a flush target the decode lead runs from the clock the new stream's fourth byte is in the queue (item 2, second half; item 3)

The cluster (about 100 RTL rows named `LS:movcl` behind `M1:out`, W = 0, both alignments) was named
through the model's timeline, which was itself wrong 15 clocks earlier: the divergent instruction
is the **marker OUT imm8 at a flush target** (behind BE / BR / DBNZ taken, CALL / RET, far transfers),
not the long shift. At W = 0 the target's first fetch delivers E6 alone or with the port byte, the
opcode is popped at once, and the model let the boundary run when the lead (3 clocks) ended, in
front of FIRST_MIN; the RTL has it on the fourth fetch's last clock; silicon has it one clock later
still.

- **Measured:** for the opcodes with a decode lead the lead runs from the later of the opcode's
  pop and the first clock on which four bytes of the new stream have been delivered (FIRST_MIN's
  clock). Model `LEAD_FM=1`: corpus **+306, 0 lost** (all W = 0: F23, F30, F34, F35, F37, F39, F40
  transfers in front of the OUT marker), socket **+24, 0 lost** (`QPr24c`, W = 0: OUT imm8, OUT imm8,AW,
  IN imm8 behind JMP short + 0 / + 1, JMP near and BE taken, both alignments; the family is 144 of
  144 with the rule).
- **Measured: only the lead opcodes.** In `r24c` PUSH, MOV AL,imm8 and MOV DS1,AW at the same targets
  are exact with and without the rule (MOV sreg's lead of 2 never ends behind FIRST_MIN's clock + 2
  in these frames: not separated for it).
- **Measured: W = 0 only shows it.** At W = 1 / 2 the fourth byte arrives late enough that the
  lead's end falls inside the next fetch and the boundary's own wait for that fetch's last clock
  hides the lead (r24c at W = 1 / 2: exact either way).
- **Inferred:** the decode stage is started by the loader's "stream valid" level (the same level
  that holds the first boundary, FIRST_MIN), not by the opcode's pop. **Unknown:** whether the
  stage restarts or merely holds its count.
- Item 3's clusters behind this rule: "fetch early by 4" 41 of 42 and "fetch early by 1" 44 of 54
  of the runs the model could not parse (Q116).

## Q114. RET near has a decode lead of 2

RET behind SHL r,imm8 / imm4 at a call target (F30, F34 `cr-shl*`, 54 corpus runs, every wait, both
alignments, both markers): the stack read is one clock later on silicon than in the model and the
RTL. Behind NOP it is exact. SHL r,imm releases the next opcode on its last-but-one word (`N .`: one
clock before the boundary), NOP three clocks before.

- **Measured:** RET's boundary is no sooner than 2 clocks after its pop (`LEAD_RET=2`, the same
  lead as MOV sreg's): corpus **+54, 0 lost**; socket **+2, 0 lost** (`QPr8-ld-ret-i`, misses since
  round 8).
- **Unknown:** RET imm16, RETF and RETF imm16 (a lead of 1 or 2 scores the same for them on
  both sets); the 8 corpus rows "RET imm16 directly behind CALL, read early by 1" and the 10 of
  RETF imm16 (whose shape is by analogy only, Q116) are not read.

## Q115. Shapes

| instruction | routine now | was | socket | corpus |
|---|---|---|---|---|
| ADJBA / ADJBS (37 / 3F) | `. . B . . . . . . . . . . . . N .` (**a bus-idle third word**; `S . .` scores the same) | no bus-idle word | +48 on `QPr24d` (120 of 120 with the round-15 runs) | +24 (F33) |
| EI (FB) | `. . B . . . . . . . . N .` (the same third word) | no bus-idle word | +24 (`QPr24d`, 36 of 36) | +12 (F33 sti) |
| PUSH imm16 / imm8 (68 / 6A) | `. . . . PP2 . Y . . . N .` / `. . . P . Y . . . N .` (the last four words as PUSH r's) | `.. Y N` (a placeholder since round 3: no boundary word, so the successor's lead was lost) | +6 (`QPr24b-pushi-{out8,e7,in8}`, W = 0) | +8 (F25) |
| PUSH r (50+) | `. . Y . . G N .`: the next opcode is released on the write's first clock, also when the write is late | `. . Y . . . N .` (the same when the write is on time) | +2 (`QPr24b-{stim07,stim80}-push` pO, with Q112) | 0 |
| OUT imm8,AW to an odd port | two byte cycles back to back (3 + 3 clocks) | one cycle | `r24b` / `r24c` used port 23h (a design slip): 66 runs scored through it | none |

**Measured** (scores, all 0 lost); the PUSH r row is **inferred** from two runs and the stores'
`G N` (it changes no other run of either set). `r24d`: ADJBA / ADJBS / EI behind OUT imm8, OUT ; CLC and
PUSH, alone and twice: 108 of 108. This closes item 4's "fetch early by 1 behind OUT at even
alignment (adjba / adjbs / sti)": a missing bus-idle word, as Q102's.

## Q116. The runs the model did not parse (item 3)

277 RTL miss rows had no model reading. None needed the socket: the model lacked function, not
rules. Taught (`model_m.py`): Jcc 70 to 7F (the JZ / JNZ routines, the outcome from the chain's own
`taken` knob); SAHF (`N .`, as LAHF) and ADJ4S (ADJ4A's routine); RETF imm16 (`. . . Y DPP2 . Y D . . F N .`
by analogy with RET imm16: **not read**); MOV [d16],AW into the pointer / vector table the model
already kept for MOV [d16],imm16, and [BW] pointers by BW's value; the return offsets of BRK 3,
BRK imm8 and CALL through a register or memory (for the RET / RETI / RETF behind them).

- **Measured:** corpus model-exact +841 by parsing alone, 0 lost (25,396 to 26,237). Of the 277
  rows: **249 exact** with this round's model, 22 miss, 6 still not parsed (PUSH DS1 / PS / SS,
  CMP [d16],AW: no routine).
- The four clusters of the brief:

| cluster (RTL against silicon) | rows | now exact in the model | by which rule |
|---|---|---|---|
| fetch against write order, W = 0 | 71 | 71 | Q112 (37), Q112 + Q113 (33), parsing alone (1) |
| fetch late by 1 at W = 1 / 2 behind OUT | 70 | 66 | **parsing alone: the rules were already there** (transfers at W = 1: Jcc taken 28, JMP / CALL through a register or memory 30, BRK 6, others 6; in the one run read, `F35-out-cc-bv-t-n0-pE-w1`, the RTL's third fetch of the chain behind OUT ; ADD DW,imm16 is one clock late, in front of the branch: a build item) |
| fetch early by 1, W = 0 | 54 | 52 | Q113 (44), parsing alone (8) |
| fetch early by 4, W = 0 | 42 | 42 | Q113 (41), parsing alone (1) |
| others | 40 | 18 | Q113 (6), parsing alone (12) |

## Q117. What was not read, and what was tried

- **Stores with d16 / direct against the fetch chain (Q33's class; item 4): 78 RTL rows, unread.**
  MOV [d16],r / MOV [BW+d16],r / MOV [BW+IX+d16],r behind PUSH, NOP or themselves at even alignment
  (66, every wait), ALU [d16 forms],imm behind OUT (12). In every one the request word executes
  inside the chain behind an EU cycle and silicon lets a five-held chained fetch go in front of
  the write. Q95's "no arbitration inside the chain" extended to these writes (`LCH_K=RW`, the
  count taken before the clock's own pops) gains 34 of them and loses 28 (PUSH behind a store with
  an immediate at W = 1 / 2, where the write does go first with five held): **not installed**. A
  displacement released behind the request word as a late arming (2, 3, 4 clocks) gains 2 to 20
  and loses 86 to 182: rejected. What separates the two frames (inferred, not a rule): in the
  losing frame the store's displacement is popped on the chained fetch's first clock; in the
  winning one the request has no operand to wait for. Round 22's 17 socket rows are the same class.
- **REP string forms, the successor behind the last iteration: 88 rows** (F24, F30: REP MOVBK / STM /
  INM / CMPBK word forms, W = 0). The model diverges inside the REP first (its timeline is not
  usable for the RTL's divergence); not looked at this round.
- **ADD4S / SUB4S / CMP4S: 39 rows** (the model does not carry the string operands). **MOVBK / CMPBK /
  INM single behind PUSH at even alignment, W = 1 / 2: 25.** Word operands at odd addresses (`-odd`):
  18. RET imm16 / RETF imm16: 18. SHL [m],CL behind a marker: 15. IN AL / AW,DW behind MOV r,r: 12
  (Q107's). Every other state is under 10 rows (list: `divergence-notes.md`).
- Tried and not kept, with counts: `B_LATE` (a bus-idle word waits behind a fetch that had given way:
  +51, -103 to -405), `B_CH` as round 16 left it (0, -1,431), a bus-idle third or fifth word in SHL
  r,imm8 (-392 to -458), `EMIN=3` for every opcode (-13,876).

## Round 24 in numbers

| | round 23's model | this round's |
|---|---|---|
| corpus, model-exact (of 30,536) | 25,396 | **26,926** (+1,530, 0 lost) |
| corpus, not parsed / error | 2,882 | 1,910 |
| RTL miss rows (1,369) the model reads exactly | 207 | **1,006** |
| RTL miss rows the model misses too ("unread") | 885 | 357 |
| RTL miss rows not parsed | 277 | 6 |
| socket, non-interrupt set by `cmp22.compare`, rounds 1 to 23 (23,670) | 22,378 | **22,426** (+48, 0 lost) |
| socket, round 24 (1,170) | | 1,128 (the 42: CVTDB, Q110) |

RTL miss rows each rule carries on the corpus (**measured**, the rule switched off alone): Q113
(`LEAD_FM`) 306; Q112 (`REQ_PRI`) 146; Q110 (`CH3_N`) 112; Q111 (`B_I4`) 92; Q114 (`LEAD_RET`) 54; Q115's
ADJBA / ADJBS / EI 36, PUSH imm 8: **709 rows** in all (some under two rules). A further 297 RTL miss
rows are exact in the model without any of them: build items, listed by cluster in `traces/logs/rtl-miss-model-exact.json` and in the spec. No rule of this
round moves a corpus run that the RTL has exact away from silicon in the model (the model misses
1,343 RTL-exact runs, as before the round).

Against the user's stopping line (states over 20 runs): read this round: the EXT / INS state (114), the
trailer's two clusters (about 100 and 69), the four parser clusters (277), RET behind SHL (54),
ADJBA / ADJBS / EI (48). **Over the line and not read:** the REP successors (88), the d16 stores
against the chain (78), the BCD strings (39), the single string forms behind PUSH (25).

## Socket runs of round 24

| family | what | runs | model exact | repeats that differ |
|---|---|---|---|---|
| r24a | 10 forms with a commit word behind nine leads, marker OUT imm8 | 540 | 498 | 12 |
| r24b | 7 instructions that end on an immediate x 9 followers | 378 | 378 | 34 |
| r24c | the lead opcodes and two controls at four kinds of flush target | 144 | 144 | 0 |
| r24d | ADJBA / ADJBS / EI behind OUT, OUT ; CLC, PUSH, alone and twice | 108 | 108 | 0 |

1,170 runs, each twice; 0 failed, 0 incomplete; the 46 repeats that differ, compared field by field
(`build/qp/rep20.py r24a|r24b`), differ in the strobe field only. One acquisition session (17 minutes
of socket time). No sim of the RTL and no corpus replay were run (the work order is against land17's
miss list). No interrupt family. Board left with vccb false, rails off, failure 0 (read back after
the last run and again at hand-back).
