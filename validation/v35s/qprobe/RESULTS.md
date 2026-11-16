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
