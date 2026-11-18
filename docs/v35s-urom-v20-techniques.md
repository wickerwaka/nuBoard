# V35S core v2: what keeps the V20's microcode ROM small, and what each technique is worth on ours (2026-11-18, tree at 74c2b30)

Analysis only. Nothing in the repository was changed, nothing was built, the board was not used.

Sources: the V20 microcode listing `build/deps/nuV30/docs/V20UC.TXT`, its disassembler
`V20UCDIS.PAS` (the bit layout of the word), `build/deps/nuV30/docs/facts/pla_model.md` (the
group-decode array) and `notes/microcode_analysis.md`; our routines
`fpga/v35s/core/v35/urom/*.uasm` as assembled by `validation/v35s/chains/uasm.py`.

Every figure is tagged **[M]** measured (the script is named; the scripts are beside this file
and run from the repository root with `PYTHONPATH=host/src:. python3 <script>`; each script's
output is saved beside it as `<script>.txt`), **[V20]** read from the listing (addresses
given), or **[I]** inferred. Estimates of what a technique would save are measurements of the
present ROM under a stated rule, not builds.

Terms used below. A *word* is one microinstruction; in our core one word is one CPU clock
unless it stalls. An *acting* word moves data, runs the ALU, posts a bus request or pops a
queue byte. A *pacing* word does none of these: it is *empty*, or it only *waits* (it carries
only bits that make the sequencer wait on the bus unit or the datum, account a queue release
or mark the boundary: `bi`, `rl`, `ro`, `f`, `nb`, `e`), or it only sequences (a jump, a
call, the dispatch). The *shared
delay* is the routine `dly`: a word's `call=wK` spends K further clocks there. A *hold slot* is
any clock with no act: a pacing word or a clock inside the shared delay. *E* is the flag that
pops the next opcode; one more word (the *post-E word*) runs after it, in both machines.

## 0. Findings

1. **The V20 word is 29 bits because it describes the execution unit only.** It has no field
   for the queue's occupancy, the bus unit's state, the effective address or a 12-bit jump
   target. Our 96-bit word carries all four. [V20] [M]
2. **The V20 ROM is 1,028 words because of three things our ROM does not have**: the operand
   named `M` (the register or the memory operand, fetched and written back by hardwired
   logic, so one routine serves the register and every memory form), the instruction's own
   bits steering the routine (ALU operation, width, register, condition), and waiting done by
   stalling a word, not by spending words. 852 of its 1,028 words are used; 150 of those are
   the 8080 emulation, which the V35 does not have. The comparable V20 figure is **702 used
   words (836 rows)**; our ROM spends **2,607 words** on the same instructions, plus 241 on
   V35-only functions. [M: `class_table.py`]
3. **The V20 has almost no hold slots**: about ten executed empty words in 852 (1 %), against
   1,353 pacing words in our 2,848 (48 %) and a further 1,073 clocks in the shared delay.
   Its long instructions take their time from words that stall on the bus (83 words carry the
   wait flag), from one word repeated by a counter (18 words), and from the hardwired operand
   fetch. PUSH R is 17 words (`0238`-`0248`) for 67 clocks on the V20 (the manual's figure for
   the uPD70108, `facts/instructions.json`); ours is 44 words and 8 delay clocks. [V20] [M]
4. **What sharing alone can do on our ROM**: tail sharing, a hold count on a word, head
   sharing through the decode table and steering bring 2,848 words to about **1,430 to
   1,500**, with no measured clock moved. [M: `depth_stats.py`]
5. **Below about 1,400 the ROM must stop describing the bus unit.** The remainder is 1,260
   distinct acting words and about 300 waiting words; about 200 words are V35-only. Reaching
   the 1,024 class needs the two things the V20 keeps out of its ROM: the bus unit owning its
   own waits, and a loader owning the effective address. That is a redesign against the
   measured clocks, not a sharing step. [M] [I]
6. **Width**: a first-level word of 27 to 28 bits (payload index, sequencing, target) over a
   table of about 500 payloads is the form that fits tail sharing; a single typed word needs
   about 40 bits and still leaves 35 to 160 words that fit no layout. [M: `two_level.py`,
   `width_stats.py`]

## 1. The word format

### 1.1 The V20 word (29 bits) [V20: `V20UCDIS.PAS`]

| Bits | Field | Content |
|---|---|---|
| 5 | source 1 | 32 codes: the eight word registers, the four segments, PC, tmpa / tmpb / tmpc, SIGMA (the ALU result), Q (a queue byte: reading it pops it), OPR (the bus datum), FLAGS, COUNT, ZEROS, ONES, CONST, and four codes resolved by the instruction: `M` (the r/m operand), `R` (the register operand), `dir*sz` (the string step), `opc&38` |
| 5 | destination 1 | 32 codes: the registers, IND (the bus address), OPR, the temporaries and their byte halves, AL / AH, COUNT, FLAGS, `M`, `R`, NULL |
| 4 | source 2 | 16 codes (SIGMA, Q, ZEROS, R, the eight registers); with source 1 = CONST the six bits of source 2 and destination 2 are the constant |
| 2 | destination 2 | tmpa, tmpb, IND |
| 3 | flags | F (the word waits for the bus datum), W (the ALU flags are written), E (end: pop the next opcode) |
| 1 + 1 | type | selects the meaning of the last 8 or 9 bits |
| 8 | type ALU | operation (5: 23 used, one of them `OPC`, the operation named by the opcode), the temporary it works on (2), R (repeat this word while COUNT is not zero) |
| 8 | type JMP | condition (4: 15 used, among them `OPC` the opcode's own condition, `OP8` the byte form, `REP`, `CNTZ`, `INTR`), target (4: a position among the 16 words of the same opcode) |
| 9 | type CTL | internal control (4: SUSP, FLUSH, FARJMP and flag controls), bus request (3: MEMR, MEMW), segment (2); with FARJMP the last five bits name one of about 20 shared routines |

One V20 word does at most: **two register-to-register moves, and one of {an ALU operation, a
conditional jump, a bus request with a control}, plus F, W, E.** Of the 852 used words 591
make one move and 179 two; 245 are ALU words, 74 jumps, 533 control words. [M: `v20_stats.py`]

The word's address is not a number in the ROM either. The ROM's address decoder matches 13
bits: a 3-bit group (first opcode byte, with REP, the F6/F7 and FE/FF groups, the 0F page,
8080, internal), the 8 bits of the opcode itself with don't-cares, and a 2-bit block number;
257 such patterns select four words each. An opcode's routine is found by the opcode; several
opcodes share a routine by a don't-care in the pattern; a jump is 4 bits. [V20]

### 1.2 Our 33 fields against it

| Our fields (bits) | V20 counterpart | Remark |
|---|---|---|
| `ra rb` (10), `d1 s1 d2 s2` (14), `wr ws` (9) = 33 | the two moves (16) | The V20 names a register as a move's end; we name a register-file port and then a move from the port. Up to five transfers a word against two. 2,796 of our 2,848 words need two transfers or fewer in the V20's sense; 52 need three or four. [M: `format_stats.py`] |
| `alu ax ay wf` (15) | operation, temporary, W, R (9) | The V20's ALU reads temporaries only; our `ax` / `ay` (8 bits) name any source. Our `loop=` to the same word is the V20's R bit. |
| `wid` (2) | none | Width comes from the opcode by hardwired logic; a byte half is a destination code; the byte form of a routine is a conditional jump (`OP8`, 15 words). |
| `pop` (3) | Q as a move source | |
| `cnt` (3) | COUNT as a move destination | |
| `bus seg` (6), `susp flush` (2) | the CTL type (9) | |
| `e f` (2) | E, F | The same. |
| `seq cond tgt` (19) | the JMP type (8) or FARJMP (5) | Our target is a full 12-bit address in every word. 264 of our 538 words with a target are calls into the shared delay. Of the others, 162 jump inside their routine (all within a 6-bit signed distance) and 112 to one of 60 places in other routines. [M: `format_stats.py`] |
| `ea` (2), the displacement pops, `ra=BASE rb=INDEX` | **outside the ROM** | The V20 has no effective-address word and no displacement pop: the loader computes the address and fetches the operand before the routine starts. We have 86 words with the address add and 125 displacement pops. [V20] [M] |
| `rl ro` (3), `bi` (1), `nb` (1), `vk` (1) | **outside the ROM** | Queue occupancy and bus-unit waits. The V20's queue is popped by the read of Q and nothing else; its bus unit arbitrates on its own. 574 of our words carry nothing but bits of this kind (with E or F). `nb` on a word that is not E is not information at all: the assembler derives it from the next word (`uasm._mark_bnext`). |
| `pfx halt` (2) | **outside the ROM** | Prefixes, the flag instructions, HALT, EI and DI have no microcode in the V20: a 16-entry hardwired operation table executes them (`pla_model.md`, the `XOP` field). Ours cost 15 words. |
| `ist`, `vk` as the vector source (2) | CONST | |

**Fields that never or rarely meet.** Taking the V20's three types on our words (ALU = `alu` or
`cnt`; jump = a `seq` with a target; bus = `bus`, `seg`, `ea` or a control bit): 1,418 words use
none, 1,331 use one, **99 use two** (48 ALU with jump, 32 jump with bus, 19 ALU with bus) and
none uses three. Without the delay calls 96. So the three payloads (17, 19 and 14 bits as the
fields stand) can share one slot of about 19 bits behind a 2-bit type, at the price of those 96
words. [M: `format_stats.py`] The V20 pays the same price and pays it in words; we cannot,
because a second word is a second clock. Section 4, technique 5 gives the measured widths.

## 2. Sequencing and sharing

### 2.1 How the V20 shares [V20]

- **Entry by the opcode, grouping by don't-care.** 82 entry blocks serve 232 first-byte
  opcodes; one block serves 32 opcodes (the ALU group, r/m with register, both directions,
  both widths: `0000`-`0001`, two words), four serve 16, four serve 8. With the two groups
  and the 0F page there are 112 entry blocks, and 25 internal blocks reached by FARJMP.
  [M: `sharing_stats.py`]
- **The instruction steers the word.** `ALU OPC` (12 words) takes the operation from the
  opcode or from the ModR/M reg field; `JMP OPC` (4) the condition; `JMP OP8` (15) skips the
  high byte of an immediate; `R` and `M` take the register and the r/m operand by the
  direction bit; the string words read `dir*sz`.
- **`M` joins register and memory forms.** `M -> tmpb` reads a register, or the datum the
  loader has already fetched; `SIGMA -> M` with control code 6 writes the register, or posts
  the write-back. No routine of the V20 has a memory variant, a displacement variant or an
  effective-address prelude. This is the largest single difference from our ROM.
- **Shared finishes by jump.** FARJMP (41 words) enters about 20 shared routines: the
  interrupt entry, IRET, the far call and far return, the REP restart (`REPX`, used by seven
  string loops), the shift loop, the multiply's sign and flag finish (`MULX`, `MULADJ`), the
  divide. There is no call and no return.
- **Width by a skip, not by a routine.** One routine serves byte and word; the word form's
  extra pop is one word skipped by `JMP OP8`.

### 2.2 The same on ours [M: `sharing_stats.py`, `class_table.py`]

We have 251 routines with an opcode header (and 33 heads, tails and service routines) against
the V20's 112 entry blocks. 158 of the 251 serve one opcode. One opcode byte enters up to 31
routines (FF: 31, F7: 23, F6: 20, 80 to 83 and FE: 10 each) where the V20 has 6 or 7 blocks for
a group and 1 or 2 for 80 to 83. Routines by their ModR/M selector: 37 register forms, 47
memory forms, and **56 written for one addressing mode** (`mod=m00`, `m01`, `m10`), 495 words.

| Class | V20 used words (rows) | Our words (routines) | acting / waiting / other pacing | Delay clocks | Why ours is larger |
|---|---|---|---|---|---|
| ALU (00-3F, 80-85, A8, A9, TEST imm) | 21 (28) | 240 (44) | 146 / 40 / 54 | 21 | Register and memory forms apart (172 words in memory forms), the immediate group by width and by addressing mode (78 words in by-mode routines), compare apart from the writing operations. |
| INC DEC NOT NEG | 8 (16) | 168 (22) | 76 / 60 / 32 | 0 | Four operations times register and four memory variants each; the V20 has two blocks with `ALU OPC`. The largest ratio, 21 to 1. |
| MOV, XCH, LDEA | 31 (44) | 147 (29) | 92 / 17 / 38 | 7 | Memory forms and by-mode forms (103 words). |
| PUSH, POP, PREPARE, DISPOSE | 94 (104) | 334 (23) | 173 / 61 / 100 | 43 | The bus handshake in words (PUSH R: five words a register against two), by-mode forms of PUSH / POP mem (97 words). |
| Transfers (branches, calls, returns, BRK, RETI) | 126 (156) | 509 (33) | 237 / 131 / 141 | 115 | The FF memory forms by mode (174 words), the flush and refill paced in words, the V35's vector and stack sequences. |
| MUL, DIV | 84 (100) | 234 (20) | 102 / 55 / 77 | 336 | One routine per width, per sign and per register / memory (16 routines; the V20 has one per sign and a shared finish), set-up and finish as delay. |
| Strings and REP | 97 (104) | 233 (17) | 125 / 43 / 65 | 157 | The REP forms' heads and element pacing; the count is comparable otherwise. |
| 0F bit fields (INS, EXT) | 74 (80) | 216 (6) | 114 / 20 / 82 | 248 | Register-count and immediate-count forms apart, delay. |
| 0F bit operations | 26 (32) | 96 (6) | 53 / 31 / 12 | 0 | Register and memory paths inside each routine, the wait words. |
| Shifts | 16 (16) | 94 (8) | 40 / 24 / 30 | 15 | Register, memory and by-mode forms of three count sources; the V20 has three heads and one shared loop. |
| 0F BCD strings, digit rotates, adjusts | 77 (84) | 136 (10) | 61 / 30 / 45 | 103 | Delay; the forms are few. |
| I/O, other | 48 (72) | 128 (28) | 59 / 23 / 46 | 10 | |
| Effective-address heads, the shared delay | 0 | 72 (15) | 18 / 15 / 39 | 12 | Hardwired in the V20. |
| V35 only (register banks, macro service, DMA, interrupt entry, BTCLR, traps) | 0 | 241 (23) | 175 / 24 / 42 | 6 | Not in the V20. |
| 8080 emulation | 150 (192) | 0 | | | Not in the V35. |
| **Total** | **852 (1,028)** | **2,848 (284)** | **1,471 / 574 / 803** | **1,073** | |

"Waiting" is a pacing word with a wait or release bit; "other pacing" is empty, a delay call or
sequencing only. Two readings of the table. First, even our acting words alone (1,296 without
the V35-only class) are 1.85 times the V20's 702: that part is duplication by form. Second, the
V20 spent 192 rows on the 8080; a V35 ROM of the same generation had those rows free for its
own additions, which is consistent with a V35 ROM of about the same size as the V20's. [I]

## 3. Where the V20's time goes without hold slots

| Mechanism | In the listing | What it covers |
|---|---|---|
| **F: the word stalls until the bus datum is there** | 83 words [M] | Every memory and I/O cycle after the first. The word that needs the datum (`OPR -> R F E`) waits; nothing is counted. PUSH R: `SIGMA -> IND MEMW` then `reg -> OPR F`, two words a register (`0238`-`0248`). |
| **The loader** (hardwired) | no words | The ModR/M byte, the displacement, the effective address and the read of the r/m operand, all before the first word. ADD mem,reg is two words (`0000`, `0001`); its other clocks are the loader's and the write's. |
| **Q: a read of the queue stalls while it is empty** | 79 words [M] | Immediates and branch displacements. |
| **R: one ALU word repeated while COUNT is not zero** | 18 words [M] | Multiply, divide, shifts, digit rotates, the bit-field shifts: 8 or 16 clocks in one word. |
| **SUSP and FLUSH with E** | 28 and 26 words [M] | A taken branch: the bus unit finishes its fetch, redirects, refills; the E word waits for the new opcode. |
| **The hardwired one-byte operations** | no words | Prefixes, flag instructions, HALT. |
| **Real sequencing words** | 29 jump words with no move [M] | A decision costs a clock where the word had nothing else to do. |
| **Executed empty words** | about ten: `006E`, `0135`, `01F7`, `01F8`, `020D`, `029C`, and four in the 8080 part [V20] | Each sits before a condition test or between two bus requests. The ruling "the original would not have had hold slots just to introduce delays" fits the listing: they are 1 % of the ROM and none is a run. |

Our hold slots (2,426, options document) against these:

| Our hold slots | Count | The V20's mechanism for that time | What the V35 plausibly did |
|---|---|---|---|
| Clocks inside the shared delay, and the words that call it | 1,073 + 244 | R on one word (the iterations), F (waiting for a cycle), real set-up and finish words (the multiply's and divide's sign work is about 40 words in the V20, `01A0`-`01B7`, `0204`-`0217`) | The same three. The iterations are already loops in our ROM (study, section 0). What remains is set-up and finish work not yet named, and waits on the bus not yet tied to a level. [I] |
| Waiting words (`bi`, `rl`, `ro`, `f`, `nb` and nothing else) | 574 | None in the ROM. The bus unit decides when a posted request runs; the queue's occupancy changes when Q is read. | The V35's bus unit differs (a posted write does not hold E; a request is announced before its address is ready), but the kind of thing is the same: these words are our model of the bus unit written into the EU's program. [I] |
| Sequencing-only words | 341 | 201 of ours are the empty post-E word [M: `format_stats.py`]; the V20 has that word too (its unused rows). The rest correspond to its 29 bare jump words. | No difference of kind. |
| Empty words | 194 | The loader's clocks (before the first word) and F. | A loader with its own clocks. [I] |

Two measurements on our ROM point at hardwired sequences on the V35 as well. (a) Wherever a
routine has a request word (`rl=x`, the word on which the bus unit learns of a request) and
then the post in line, the post is exactly three words later in 67 of 68 cases (the other is
an I/O write five words later), whatever stands between (empty, waiting or acting words)
[M: `residual.py`]. A constant of three across every class is a property of the bus unit, not
of 67 routines. (b) The measured shapes release a 16-bit
displacement in one clock, late, with the read posted on the next clock (`inc_m_d16`: the
displacement released on the seventh word, the read posted on the eighth), while our routines
pop it byte by byte on the first two words because our address add needs it. The silicon's
address add therefore sits behind that late release, next to the bus request, which is where
the V20 has it. [I]

## 4. Techniques for our ROM, ranked

The depth figures stack; each row of the table is measured on the ROM as the rows above leave
it. [M: `depth_stats.py`]

| Step | Words | Change |
|---|---|---|
| Today | 2,848 | |
| 1. Tail sharing | 2,134 | -714 |
| 2. A hold count on a word | 1,775 | -359 |
| 3. Head sharing through the decode table | 1,496 | -279 |
| 4. Steering from the instruction | 1,428 to 1,459 | -37 to -68 |
| 5. Word format | (width, see below) | |
| 6. The bus unit owns its waits | about 1,200 to 1,300 [I] | research |
| 7. The loader owns the effective address | about 1,100 to 1,200 [I] | research |

### 1. Tail sharing (the V20's FARJMP finishes)

| | |
|---|---|
| Changes | Assembler only. The listing, the book check and the side-by-side tool assume a routine is contiguous. |
| Saves | 714 words: 2,848 to 2,134 (2,104 distinct, 30 copies where the word before already jumps). 334 are pacing words, 200 the empty post-E word, 210 acting words. [M: `depth_stats.py`; the same figure as option D1] |
| Cycle exactness | No risk: every instruction executes the same words in the same order. The corpus replay proves it. |
| Address path | None. A jump is already in every word. |

It needs a jump on about 210 more words than today (about 260 with technique 2), and at least
108 (121) of those words also carry an ALU or bus payload [M: `jumps_after_sharing.py`]. That is free in a word with a sequencing
field in every word and it is what makes a V20-style typed word expensive (technique 5).

### 2. A hold count on a word

| | |
|---|---|
| Changes | Sequencer RTL (a 5-bit down counter and one more term among the registered stalls: while it runs, the word register is loaded with the empty word and the address is kept) and the assembler. No new bits: a sequencing code `HOLD` with the count in the target's bits, since a holding word has no jump. The shared delay routine and its return-register use go. No port is added (the counter is inside `v35_useq`). |
| Saves | 359 more words: 1,775 after tail sharing. 461 words carry a count: 209 of one clock, 152 of two, 100 of 3 to 32. The count includes the 69 words whose only bit is the derived `nb` mark; without them 1,844. [M: `depth_stats.py`, `NBFOLD=0` for the second figure] |
| Cycle exactness | Low risk if a held clock is presented to the bus unit and the loader exactly as an executing empty word is today (same word kind, same `ex`). That equivalence is the thing to prove; the corpus replay proves it. |
| Address path | The "same address" leg of the next-address mux already exists for stalls; the new term is a registered bit like the other stalls. |

This is not a V20 mechanism. It is what `call=wK` already is (264 of our words are a count
spelled as a call target), stored without the calling word, the 24-word routine and the return
register. The rule that every delay has a machine explanation is neither met nor hurt by it:
each count stays an OPEN item exactly as each delay call is today. Two consequences should be
stated. Run-length on identical waiting words is worth nothing more (2 words): the waiting
words do not repeat. And the ruling that a named operation is preferred to a hold slot works
against depth once holds are free: the 461 counts stand for 1,464 clocks, and each one that
becomes a named word is a word again, unless the operation is a repeated word (the V20's R) or
rides on a word that exists.

### 3. Head sharing through the decode table (the V20's loader, kept in microcode)

| | |
|---|---|
| Changes | Assembler and the generated decode tables: a cell names a head and a body; the dispatch enters the head with the body as the return address. This is the existing effective-address-head mechanism (`ea=q`, 8 routines today) generalised to any identical first words, and to opcodes without a ModR/M byte. No sequencer change if heads use the one return register (with technique 2 a head no longer needs it for a delay call). |
| Saves | 279 more words: 1,496. 51 heads; the largest are the by-mode preludes of the 81 / C7 / FE / FF / F6 / F7 / 8D memory forms (three groups of 7 or 8 routines, 3 words each), the multiply and divide heads, the immediate pops of the accumulator and register immediate forms (6 and 7 routines), the stack-read head of POP and the returns. Greedy estimate, one level of return. [M: `depth_stats.py`] |
| Cycle exactness | No risk in principle (the same words run); the dispatch's call is on the measured path today. |
| Address path | None new: the dispatch already selects between a routine's entry and a head. The head's address comes from the table instead of from the ModR/M mode. |

Tail sharing joins routines that end alike; this joins routines that begin alike and is the
part of the V20's `M` that can be had without changing any clock: the by-mode routines exist
because each mode has its own measured prelude, and the preludes are the same across opcodes.

### 4. Steering from the instruction (the V20's `OPC`, `OP8`, `R` / `M`)

| | |
|---|---|
| Changes | EU RTL: new selector codes (the ALU operation from the ModR/M reg field for F6 / F7 / FE / FF as `alu=GRP` does for 00-3F and 80-83; the width from the format where routines now name it), assembler, routines merged by hand. |
| Saves | 37 words for width and ALU operation, up to 68 with register and segment selects, on top of techniques 1 to 3: 1,459 to 1,428. Upper bounds: the fields are ignored when comparing words, which also joins words whose difference no instruction bit explains. [M: `depth_stats.py`; alone on tail sharing 87 to 141, the options document's D2] |
| Cycle exactness | Low risk; each merged pair must have the same shape, which the measurement requires. |
| Address path | None. The new selects are on datapath controls, which is where the long paths have been (the timing gate applies). |

Small after head sharing, because most of what the instruction would steer is in heads and
tails that are then stored once. INC / DEC / NOT / NEG (168 words in 22 routines, 8 in the V20)
is the clearest case and falls to techniques 1, 3 and 4 together.

### 5. The word format (the V20's typed word, or an index)

Measured on the ROM after techniques 1 and 2, the jump target kept as an address so that no
table stands on the next-address path. [M: `width_stats.py`, `two_level.py`]

| Form | Width | Words that do not fit | Storage at 1,775 words |
|---|---|---|---|
| Today | 96 | 0 | 170 kbit (295 as stored today) |
| Typed word, fields as they are, 8 layouts | 40 | 363 | |
| Typed word, each field group coded (the V20's way: 5-bit codes for 32 sources), 8 layouts | 40 | 158 (67 without the jumps tail sharing forces) | 71 kbit |
| The same, 16 layouts | 40 | 96 (35) | 71 kbit |
| The same, 8 layouts | 32 | 349 (208) | |
| Two levels: index, sequencing and target in the first, the payload in a table | 28, and 520 x 77 | 0 | 50 + 40 = 90 kbit |
| Two levels after technique 4 | 27, and 480 x 77 | 0 | 45 + 37 = 82 kbit |

| | |
|---|---|
| Changes | ROM format and every decode of the word (typed word), or the sequencer's read path (two levels; the options document's W2). |
| Cycle exactness | Two levels: none. Typed: each word that fits no layout must be reshaped without a new clock, or tail sharing given up for it (a copy of the shared words up to one that can carry the jump). |
| Address path | Two levels: sequencing and target stay in the first level, so the next address does not wait for the second read; the second read must fit between the ROM read and the word register (the timing study the options document asks for). Typed: a layout decode in front of every control, none on the address. |

The V20 reaches 29 bits with a typed word because its sharing is by grouping, not by jumps (41
FARJMPs in 852 words), and because it has no queue, wait or hold bits. Our sharing is by jumps
and the first-level word of the two-level form comes out at the V20's width for the V20's
reason: it is what is left when the word names one payload and where to go next. A 32-bit
single-level word is not reachable without moving clocks.

### 6. The bus unit owns its waits (the V20's F and its bus unit)

| | |
|---|---|
| Changes | Bus unit and EU RTL, sequencer stalls, every routine with a bus cycle. |
| Saves | First step, measured: the request word posts, the bus unit keeps the three clocks to the cycle itself. 68 places; 85 pacing words between request and post go, and the post word joins the request word where nothing but pacing stands between (32 places): about 115 words on the ROM as built, fewer after sharing [M: `residual.py`]. PUSH R would be about 20 words for 44. Further: the 299 waiting words that remain after techniques 1 and 2 (110 bus-idle, 86 request words, 42 release words, 24 datum waits, 19 with the derived mark) are the pool; how many can become a stall on a level is not measured. [I] |
| Cycle exactness | High risk. Each wait needs a level that exists on the socket; round 26 did not find one for one word kind. The three-clock constant is the best-supported candidate because it holds in all 68 cases. |
| Address path | None; stalls are registered. The interface budget must not grow: the request and its kind already cross it. |

### 7. The loader owns the effective address (the V20's `M`)

| | |
|---|---|
| Changes | Loader and EU RTL: the displacement pops, the address add and the request leave the ROM; the decode table says per cell what the loader fetches. |
| Saves | The pool after techniques 1 and 2: 258 words used only by by-mode routines, 23 in the address heads, 86 address-add words and 125 displacement pops as built [M: `residual.py`, `format_stats.py`]. Head sharing has already taken the cross-opcode part; what is left for this step is perhaps 100 to 150 words. [I] |
| Cycle exactness | High risk: the loader must reproduce each mode's measured prelude for every class of instruction, and those differ by class today. No per-opcode case may sit outside the decode tables, so the differences must become table columns. |
| Address path | None, but the loader is where the 17 ns work has been hardest. |

### Not worth a step of their own

- **Run-length on waiting words**: 2 words. [M]
- **The hardwired one-byte operations** (prefixes, flags, HALT): 15 words. [M]
- **Joining register and memory forms in one routine**: the register forms are 135 words in
  all and their shapes differ from the memory forms'; head and tail sharing take what is
  common.
- **Popping where the release is** (dropping `rl` and `ro`, 3 bits): no depth; it needs the
  datapath to take its operands as late as the silicon does. It belongs with technique 7.

## 5. End state

| Stage | Words | Word | Storage | Of today's 295 kbit |
|---|---|---|---|---|
| Today | 2,848 | 96 | 295 kbit as stored | 100 % |
| A: techniques 1 and 2 (assembler, a counter in the sequencer) | about 1,775 | 96 | 2,048 x 96 = 197 kbit; the high ROM part and one address bit go | 67 % |
| B: + techniques 3 and 4 (decode table, EU selects) | about 1,430 to 1,500 | 96 | 144 kbit used (2,048 x 96 as stored) | 49 % used |
| C: + two-level storage | about 1,430 to 1,500 | 27 or 28, and about 480 x 77 | about 40 + 37 = 77 kbit | 26 % |
| D: + techniques 6 and 7, if the levels are found | about 1,100 to 1,200 [I] | the same | about 65 kbit | 22 % |
| The V20 class | 1,024 | 32 to 40 | 33 to 41 kbit | 11 to 14 % |

Stages A to C move no measured clock and their figures are measured, with these cautions: the
head-sharing figure is a greedy estimate with one return level; the steering figure is an upper
bound; the stack is measured in this order only.

**The irreducible part**, in words that being exact to the V35 costs over a V20-class ROM:

- About 200 words of V35-only function (register banks, macro service, DMA service, the
  interrupt controller's entry). The V20 has nothing there; it spent 150 words on the 8080.
- One distinct word sequence per measured shape. Where two forms of an instruction differ on
  the pins by a clock, they differ in the ROM unless a hardware mechanism produces the
  difference. After sharing that is the by-mode residue (about 250 words) and the per-class
  preludes.
- The waits for which no level has been found. Each is a word (or a count on a word) until it
  is a stall.
- A sequencing field on every word, because our sharing is by jump: the first-level word is
  the V20's width, and the payload table (about 37 kbit) is the cost over the V20.

So about 1,450 words at 28 bits plus a payload table is reachable by sharing; about 1,100 to
1,200 is the plausible floor if the bus unit and the loader take their waits back; 1,024 x 32
in one level is not reachable while every measured clock is kept and the ROM still describes
the bus unit.

**The step to build first: technique 1 (tail sharing)**, as the options document also
recommends: assembler only, proof by an identical corpus, and it replaces the estimate with a
count. Technique 2 follows it directly; it is the first RTL step and removes the shared delay.

## 6. Scripts

| Script | Measures |
|---|---|
| `v20_stats.py` | The V20 listing: used words, types, moves, flags, conditions, opcodes per entry block, words by class. |
| `class_table.py` | Our routines and the V20's blocks under one classification (section 2.2). |
| `sharing_stats.py` | Routines per opcode and opcodes per routine, both machines. |
| `format_stats.py` | Our words in the V20's terms: transfers per word, the three types, targets, pops and releases, the post-E words. |
| `depth_stats.py` | Tail sharing, hold counts, head sharing and steering, stacked (section 4). `NBFOLD=0` keeps the derived-mark words. |
| `residual.py` | What is left after sharing, by kind and class; the request-word pattern. |
| `jumps_after_sharing.py` | The jumps tail sharing forces and the words they land on. |
| `width_stats.py` | Typed-word layouts (`RAWSEQ=1`: the target kept as an address; `FORCED=0`: without the forced jumps). |
| `two_level.py` | Distinct payloads and first-level width after sharing. |
| `inventory.py` | One line per routine. |

## 7. Limits

- The V20's control codes 3 to 7 and 0A to 0D are not named in the disassembler; code 6 is
  read as "write `M` back" from its position after every `SIGMA -> M` and `tmpa -> M`. [I]
- "Used" V20 words are those with any move, flag, type payload or control; an executed empty
  word and an unreached one look the same, so the count of executed empty words is by reading
  the blocks, not by script.
- The classification of our routines is by the first opcode of the header; a routine serving
  two classes is counted in the larger.
- Sharing estimates assume the assembler may place any word anywhere and that the dispatch's
  call serves any head; neither was built.
- Techniques 6 and 7 are not measured beyond their pools. Their figures are judgement.
