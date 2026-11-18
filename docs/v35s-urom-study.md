# V35S core v2: hold slots against smaller operations — design study (2026-11-18, tree at 1a4f427)

Analysis only. Nothing in the repo was changed, nothing built, no board use.
Scripts beside this file (read-only, run from the repo root with `PYTHONPATH=host/src:.`):
`routine_holds.py` (per routine: ROM words, acting words, holds by kind, clocks in `dly`;
its output for all 284 routines is `routine_holds.txt`) and `corpus_cover.py` (which corpus
runs exercise each instruction).

Every claim is tagged **[M]** Measured (socket: corpus, qprobe RESULTS.md, v35s-eu-timing.md),
**[B]** Data book (V35 book clocks in `v35_book_clocks.json`; V20/V30 manual in
`build/deps/nuV30/docs/facts/instructions.json`), **[V20]** read from the V20 microcode
listing `build/deps/nuV30/docs/V20UC.TXT` (addresses given), **[I]** Inferred, **[U]** Unknown.

## 0. Headline findings

1. **The iterations are already loops.** [M of the ROM] MUL / DIV run one word per bit
   (`alu=MULS loop=self`, 8 or 16 times), shifts and bit fields two words per bit
   (`alu=SH1` / `BFR` / `BFL`, then a `loop=` word), 4S one pass per byte pair. No hold slot in
   these families stands for a hidden per-bit iteration, with one exception: **ROL4 / ROR4**,
   where the single code `R4` replaces a 4- or 8-step rotate loop. The options document's
   sentence "a microcode loop of a few words per iteration would both fill their holds and
   delete their long delay calls" is not what the ROM shows.
2. **The real V20 microcode is in the tree** (`V20UC.TXT`, 1,285 lines) and it settles how the
   original sequenced these instructions [V20]: a word with the `R` flag repeats while the
   `COUNT` register is non-zero, and the ALU has one-step codes `MUL`, `DIV`, `SHR`, `ROL12`
   on the pair tmpc:tmpb. So `MULS`, `DIVS`, `SH1`, `BFR`, `BFL` are **faithful** primitives.
   What is "too macro" is the set-up and finish codes: `MULI`, `MULF`, `DIVI`, `DIVF`, `CVBI`,
   `CVBF`, `CVDI`, `CVDF`, `R4`, `BCDS`, `BFK`, `BFU`, `BFI`, `BFM`. The V20 does each of those
   in two to twelve words of moves, `PASS`, `NEG`, `NOT`, `ADD`, conditional jumps.
3. **How far small operations explain the holds** (families 1 to 4, static count on the same
   basis as the 2,426):

   | | hold slots | bus-wait words with marks | branch / dispatch words | explained by V20-style small operations | left unexplained |
   |---|---|---|---|---|---|
   | 1 MUL / DIV (20 routines) | 468 | 55 | 32 | about 218 | about 163 |
   | 2 INS / EXT (6 routines) | 350 | 20 | 40 | about 18 | about 272 |
   | 3 4S, ROL4 / ROR4 (4) | 121 | 22 | 10 | about 36 | about 53 |
   | 4 shifts, CVT, ADJ (16) | 134 | 34 | 24 | about 22 | about 54 |
   | **total** | **1,073** | **131** | **106** | **about 294** | **about 542** |

   (The 1,073 here equalling the count of clocks in `dly` is a coincidence.) The "explained"
   column is [I] throughout and good to about ±20 %.
4. **The multiply is the V20's multiply plus five clocks; the divide is not.** Non-loop clocks:
   MULU V35 17 against V20 10 to 11 words; MUL V35 27 / 28 against V20 22; but DIVU V35 25
   against V20 8, DIV V35 44 against V20 18 to 19. About 16 (unsigned) and 24 (signed) clocks
   of every divide have no counterpart in the V20's algorithm. [M] against [V20]/[B].
5. **The pins cannot tell an empty word from a small operation.** [M] The only per-clock
   observables are bus cycles, queue pops / releases and the bus-idle marks. Any decomposition
   that keeps those on their clocks is clock-exact, and none can be confirmed beyond its total.
   So filling a hold with a named operation is a choice of description, not a measurement.
6. **ROM depth does not fall.** Residual stretches already cost one ROM word each (a `dly`
   call). Turning a `call=w17` into real operations adds up to 17 words. Unshared, the
   decomposition adds about 250 words. With the V20's sharing (one finish, one sign fix-up,
   byte / word by a width condition, memory forms joining the register form after the datum)
   family 1 could fall from 234 words to about 150 to 170; that is options D1 / D2, not the lens.
   The lens pays in **width** (all 18 words over 37 payload bits in these families have a hold
   beside them to split into) and in **EU logic** (the 51-bit multiply and 75-bit divide state,
   `v35_rot4`, the mask generator `bfm` go away).

## 1. Conventions

- **T** = routine words as qprobe counts them (RESULTS.md Q36): from the routine's first word
  to the dispatch word after E. v35s-eu-timing.md costs are T + 1 (MULU r16: T 33, cost 34,
  book 32). [M]
- "Hold" as in `split40.py`: a word with no register read, move, ALU, write, bus, count or pop.
  It may still carry a mark (`bi`, `rl=x`, `alt`: the B / Y / V / C words) or only sequence.
- V20 word counts: counted on the listing; where the path is not certain (signed forms) taken
  as V20 book clocks − loop − 3 (the 3 calibrated on MULU: 29 = 16 + 10 words + 3). [V20]/[B]
- [V20] two facts that bear on the lens: (a) the word after `E` still executes and usually does
  the last register write (0006/0007, 0121/0122); the V35 ROM's dispatch word after E is that
  slot, empty. (b) The V20 ROM itself has a few executed blank words (020D in IMUL, 0135 in
  DBNZ): latency after a `COUNT` or sign-latch load. "No hold slots" is nearly, not exactly, true.

## 2. Family 1: MUL / MULU / MUL imm, DIV / DIVU

### 2.1 What is there now

Register forms (loop.uasm). All share one shape: two set-up words, `bi` / `open` / `bi`
(RESULTS Q36 / Q102: `P . B . B`), the one-word loop, a `dly` call, the finish.

| routine | ROM words | acting | holds (static) | `dly` calls |
|---|---|---|---|---|
| mulu16 / mulu8 | 11 / 10 | 6 / 5 | 12 / 13 | w7 / w8 |
| mul16 / mul8 | 15 / 11 | 7 / 5 | 31 / 32 | w17, w6 / w19, w7 |
| divu16 / divu8 | 13 / 12 | 6 / 5 | 21 / 22 | w14 / w15 |
| div16 / div8 | 19 / 18 | 6 / 5 | 49 / 50 | w21, w9, w6 / w21, w10, w6 |
| mulimm_rw / rb / mw / mb | 18 / 4 / 14 / 7 | 7 / 2 / 6 / 4 | 29 / 3 / 17 / 4 | w1 w11 w6 / w1 / w1 w8 / w1 |
| mulu_m16 / m8, mul_m16 / m8 | 10 each | 5 | 12 / 13 / 22 / 24 | w1 + w6 / w7 / w16 / w18 |
| divu_m16 / m8, div_m16 / m8 | 10 / 10 / 11 / 11 | 5 / 4 / 5 / 4 | 19 / 21 / 36 / 38 | w1 + w13 / w14 / w24 w5 / w24 w6 |

The codes (v35_eu.sv 587-640, v35_fn_pkg.sv 193-300, 517-590):

- `MULI` loads a separate 51-bit record `mul` (v35_mul_t) with the **magnitudes** of both
  operands and the sign difference (F1); `MULS` is one shift-add step on that record; `MULF`
  forms the product, **negates it** when F1, and the flags. One word each.
- `DIVI` loads a 75-bit record `dv` with magnitudes, the overflow pre-check, the quotient's and
  dividend's signs; `DIVS` one restoring step; `DIVF` applies the signs, range-checks, raises
  `DTRAP`.
- The counter is the EU's loop counter (`cnt=BITS`: 8 or 16 from the width). Conditions used:
  `CNTZ`, `SGD` (F1), `SNZ` (SIGMA not zero), `DN`, `DTRAP`.
- tmpa / tmpb / tmpc take no part in the iteration; the result leaves through SIGMA and tmpc.

### 2.2 What is measured

| form | cost [M] | T [M] | book V35 [B] | book V20 [B] | data dependence [M] |
|---|---|---|---|---|---|
| MULU r8 | 26 | 25 | 24 | 21-22 | none: 40 pairs AL {00,01,7F,80,FF} x CL {00,01,02,0F,55,80,AA,FF} (m3-m9), 10 pairs (Q36) |
| MULU r16 | 34 | 33 | 32 | 29-30 | none (Q36: 0, 1, FFFF, 5555 x AAAA) |
| MUL r8 | 37 | 36 | 31-40 | 33-39 | +8 signs differ, +1 low half 0, +1 high half 0 too; all 121 pairs of the f-mul grid |
| MUL r16 | 44 | 43 | 39-48 | 41-47 | the same; 100 pairs |
| MUL r16,r16,imm8 / imm16 | 41 / 42 (imm16 from T + 1) | 40 / 41 | 39-49 / 40-50 | 28-34 / 36-42 | +8 negative (24 pairs imm8) |
| DIVU r8 | 34 | 33 | 31 | 19 | none (9 pairs Q36, 10 in m3-m9) |
| DIVU r16 | 42 | 41 | 39 | 25 | none in six pairs with DW = 0; **one probe with DW = 20h is 2 shorter at even alignment only: open** |
| DIV r8 | 53 | 52 | 46-56 | 29-34 | +7 negative dividend, +2 negative quotient; a negative divisor alone costs nothing |
| DIV r16 | 61 | 60 | 54-64 | 38-43 | +2 negative quotient measured; +7 negative dividend taken from the byte form (word: 4 cases in m3-m9, not probed in qprobe) |

- Word minus byte is 8 in MULU, DIVU, DIV and 7 in MUL. [M] So one clock a bit (or two bits in
  a two-clock iteration: the totals cannot tell, [U]).
- The corpus varies the operands enough to rule out any per-set-bit cost in MULU, MUL and
  DIVU r8. [M] DIVU r16 with a non-zero high half and DIV r16 with a negative dividend are thin.
- Memory forms: sign terms not acquired (RESULTS "Not acquired"). Divide errors: 143-181, not
  resolved by clock. [U]
- Pinned clock by clock: the B words at 3 and 5, the next opcode's release on the next-to-last
  word (Q36, 288 of 288), `F14-g-push-mulu_aw`, `F16-l-push-divu_ix`, `F33-out-{mul,divu,div}_cw`,
  chains F13-F18, F27, F28, F33, F34, F40 (1,027 runs name MULU, 842 MUL, 287 DIVU, 65 DIV).

### 2.3 The faithful micro-sequence: the V20's own

[V20] MULU r16, 0178-017F then MULX 0208-020B:

```
0178 M -> tmpc, ZEROS -> tmpb        ALU PASS tmpc
0179 AX -> tmpa
017A CONST 8 -> COUNT                JMP OP8 (byte: to 017C)
017B CONST 16 -> COUNT
017C SIGMA -> tmpb                 R ALU MUL tmpc     ; repeats COUNT times
017D                                 ALU PASS tmpb    ; the high half, for the zero test
017E tmpa -> AX                      JMP OP8 (byte: to 0180, tmpb -> AH)
017F tmpb -> DX                      FARJMP MULX
0208 CTL [-06-] (CY, V cleared)   0209 JMP Z   020A CTL [-07-] (set)   020B E
```

Signed MUL (0184, IMUL 020C-0218, MULADJ 0204-0206, MULX): the magnitudes by an ALU code and
`NEG`, the same `R` row, then `NEG tmpa`, `NEG tmpb`, `JMP NC`, `NOT tmpb` (0213-0217) when the
signs differ. DIVU (0188-0193): `SUB tmpc` and `JMP NC` as the overflow pre-check, the `R` row
`ALU DIV`, one more `DIV` word, two writes. Signed DIV (0198-019F, IDIV 01A0-01A7, IDIV2
01A8-01B7): the dividend's `NEG` / `NOT` pair when negative (01A2-01A5, 4 words), the divisor's
magnitude, the loop, then `NEG` of quotient (01B0) and remainder (01B3) by sign.

So the loop is a one-word repeat on a hardware shift step, not a shift / test / add / decrement
loop of several words. A software loop (three or four words a bit) would give 16-bit
multiplies of 60 to 80 clocks; the V35 measures n + 17. **The measurements favour the V20's
form outright.**

### 2.4 The arithmetic

Non-loop words = T − n. "V20 words" as section 1. "Now" = acting non-loop words in the
present routine. The V35 sequence taken as the V20's words + the dispatch word.

| form | T | n | non-loop | acting now | holds on path | V20 non-loop words | V20 pattern + 1 | residual |
|---|---|---|---|---|---|---|---|---|
| MULU r8 | 25 | 8 | 17 | 4 | 13 | 10 (listing 9-10) | 11 | **6** |
| MULU r16 | 33 | 16 | 17 | 5 | 12 | 10 (listing 10-11) | 11-12 | **5** |
| MUL r8, signs equal | 36 | 8 | 28 | 4 | 24 | 22 (book) | 23 | **5** |
| MUL r16, signs equal | 43 | 16 | 27 | 5 | 22 | 22 (book) | 23 | **4** |
| DIVU r8 | 33 | 8 | 25 | 4 | 21 | 8 (book; listing 8) | 9 | **16** |
| DIVU r16 | 41 | 16 | 25 | 5 | 20 | 6-8 | 9 | **16** |
| DIV r8, all positive | 52 | 8 | 44 | 4 | 40 | 18 (book) | 19 | **25** |
| DIV r16, all positive | 60 | 16 | 44 | 5 | 39 | 19 (book) | 20 | **24** |

Sign terms:

| term | V35 [M] | V20 [V20]/[B] | reading |
|---|---|---|---|
| product negated | +8 | 0213-0217: 4 to 5 words; book range 6 | about 5 of the 7 holds in `call=w6`+1 become `NEG lo`, store, `NEG hi`, `NOT hi`, store; 3 left [I] |
| low half zero | +1 | `JMP NC` at 0215 | a taken branch: fits the V20's structure [I] |
| high half zero too | +1 | `JMP Z` at 0209 | a second taken branch [I]; note the V35 shows it **only** on the negated path, the V20 on every multiply (29 or 30) |
| dividend negative | +7 | 01A2-01A5: 4 words | 4 explained, 3 left [I] |
| quotient negative | +2 | 01B0: 1 word | 1 or 2 explained [I] |

Reading:

- **Multiply.** A V20-pattern sequence lands within 4 to 6 clocks of every measured multiply,
  signed and unsigned, both widths. The residual is nearly the head's `B . B` (three words, two
  of them measured bus waits). [I] The sign structure (constant for equal signs, +8 for the
  negation, +1 per taken zero branch) fits "magnitudes, unsigned loop, conditional negate".
  A Booth recoding would show no +8; it is ruled out. [M]
- **Divide.** The V20 pattern leaves 16 clocks (unsigned) and 24 to 25 (signed). No natural
  restoring or non-restoring divide I can write lands on n + 25. Candidates, none fitted:
  (a) the loop runs n + 8 steps (the byte divide as a 16-step, the word as a 24-step): residual
  8 / 16, and DIVU's overhead becomes the multiply's 17; (b) a pre-check done as trial steps;
  (c) a quotient and a remainder correction pass. **[U]; the residual stands at 16 / 24.**
  CVTBD (the same 8-step divide on AL) is T 21 = 8 + 13, twelve shorter than DIVU r8: so about
  12 of DIVU's 16 belong to what DIVU does and CVTBD does not (the 16-bit dividend, the
  overflow pre-check, the trap test). [M]

### 2.5 The loop form in the ROM

Proposed words for MULU r16 (T 33 kept; `.` = a hold that stays):

```
1  P   M -> tmpc ; 0 -> tmpb
2      AW -> tmpa
3  B   COUNT <- 16 (8)                     ; was bi
4      PASS tmpc                           ; was open
5  B   .                                   ; bi stays
6-21   R: mul step {CY,tmpb,tmpc} >> 1, + tmpa when tmpc[0]   (as MULS loop=self)
22     PASS tmpb                           ; high half to SIGMA (zero test)
23     AW <- tmpc                          ; 23-27: five of w7's eight
24     DW <- tmpb
25     CY, V <- 0
26     jc SNZ
27     CY, V <- 1
28-30  . . .                               ; three holds left (call=w2)
31     (write lands)        32  E          33  dispatch
```

The order of 22-30 against the holds is free: nothing on the pins dates those words. [M]

| | now | loop form, each routine its own | loop form, shared as the V20 |
|---|---|---|---|
| 8 register routines, ROM words | 109 | about 190 | about 75 (one multiply body, one divide body, byte / word by a width jump, shared finish and sign fix-up) |
| 8 memory routines | 82 | about 150 | about 45 (the read, then the register body) |
| 4 MUL imm routines | 43 | about 75 | about 30 |
| total | 234 | about 415 | about 150 |
| clocks | unchanged | unchanged | unchanged, **if** the shared entry jumps ride in a neighbouring word's sequencing field |

Datapath the loop form needs:

| resource | present? |
|---|---|
| shift-by-one on the pair tmpb:tmpc with carry in | yes for the bit fields (`BFR` / `BFL` rotate the pair, v35_eu.sv 675-686); the multiply needs the adder's carry-out as the bit shifted in, the divide the quotient bit: one new ALU step each, replacing `v35_mul_step` / `v35_div_step` |
| add of tmpa conditional on tmpc[0] inside the step | new (it is inside `v35_mul_step` on the separate record today) |
| loop counter, zero test, decrement-and-branch | yes (`cnt=`, `CNTZ`, `SQ_LOOP`) |
| conditional branch on a datapath flag | `SNZ`, `SGN`, `SGD`, `DN`, `DTRAP` exist; need "tmp sign" for the magnitudes (or keep F1 / DN latches loaded by a `PASS`) |
| `NEG`, `NOT`, `PASS`, `ADD` with carry between halves | `NEG`, `NOT`, `PASS`, `ADD` exist; add-with-saved-carry (`scy`) exists for shifts and BCD |
| the 51-bit `mul` and 75-bit `dv` records | **removed** (126 flops and their functions) |

Word format: every proposed word is one move + one ALU step, or one ALU step + a loop / branch.
In the 96-bit word all are expressible today except the two new step codes. At 40 bits
(3-bit tag + 37): move word 14 + ALU 15 + wid 2 = 31; ALU + sequencing 15 + 19 = 34; the
register-read set-up `ra rb d1 s1 d2 s2` 24. The two present words over 37 bits in this family
(`mulimm_rw` word 4 and `mulimm_rb` word 3, 53 bits: read + ALU + count + jump + mark) split
into the hold beside them.

### 2.6 Risk to exactness

- Must stay on their clocks: the B words (3 and 5 in the register forms; `B . B` two and four
  words after the immediate's release or the datum in 69 / 6B and the memory forms), the
  request word and read post of the memory forms, the release of the next opcode on the
  next-to-last word, E. All are outside the stretches being filled.
- The register writes move from the last two words to the middle of the old delay. With RAMEN
  the write of a register is not a bus cycle, but the port's use is timing-visible to a
  following instruction only through E; keep the last write no later than now.
- The divide error's entry clock (`jc=DTRAP`) must not move: its 143-181 is not resolved. [U]
- Gate: Q36 (288 runs), rounds 12-14 for 69 / 6B, F14 / F16 / F33 chains, the f-mul grid.

## 3. Family 2: INS / EXT

### 3.1 What is there now

`ext` 43 words (51 holds), `exti` 44 (51), `ins` 52 (115), `insi` 53 (115), `bf_pass` 12 (6),
`ext_xq_body` 12 (12): 216 ROM words, 350 holds, of which 248 are clocks in `dly`
(EXT: w1 w2 w11 w17 w1; INS: w1 w17 w24 w20 w8 w9 w11).

Already loops, two words a bit (`BFR` or `BFL`, then `loop=`): EXT in one word shifts up by
15 − o − w and down by 15 − w; EXT across rotates by o then masks (`BFM`); INS rotates by o,
merges AW's field under a mask (`BFI`), rotates on to sixteen; INS across rotates the spill
in and out (4 clocks a spilled bit). Macro codes: `BFK` (15 − x), `BFU` (offset + width + 1
mod 16 with carry), `BFI` / `BFM` (merge / mask with the generated mask `bfm`).

### 3.2 What is measured [M]

All 256 (o, w) pairs swept (f-ext, 586 INS and 718 EXT runs over 11-12 file groups); no data
dependence, only o and w.

| case | EXT | INS |
|---|---|---|
| within one word, o + w <= 14 | 107 − 2o − 4w | 94 (92 at o = 0) |
| ends at bit 15 | 107 − 2o − 4w | 86 (84 at o = 0) |
| crosses | 61 + 2o (−1 at w = 15) | 128 + 4(o + w − 16) |

Book [B]: V35 EXT 41-121, INS 63-155; V20 EXT 26-55 (34-59), INS 31-117. The V20's routine
(0318-0347, INS 0328-0343) is built from `R ALU MUL` / `SHR` / `DIV` rows at one clock a bit
and is not constant in o and w; **the V35's algorithm is its own** (constant 94 for INS).

### 3.3 Faithful sequence and the arithmetic

EXT in one word: the per-bit terms are exact: 2(15 − o − w) + 2(15 − w) = 60 − 2o − 4w.
The constant 47 is the head to the datum (about 14: `P . BP . C . . Y D`, bus-paced), the
set-up (4 words), the second shift's four-word entry, twelve words after it, the two register
writes, two pointer clocks, E. INS in one word: sixteen rotations at two clocks (31 or 32
clocks, constant because o + (16 − o) = 16), which is the natural "rotate, insert, rotate on"
algorithm; a three-phase serial insert (o rotations, w + 1 bits shifted in from AW,
15 − o − w more) gives the same sixteen and would retire `BFI`'s mask. [I]

What small operations add:

| macro code | small-operation form | holds filled |
|---|---|---|
| `BFK` | constant 15 to a temporary, `SUB` | 1 |
| `BFU` | `ADD`, `INC`, mask to four bits, the carry kept | 2 |
| `BFI` | serial insert (no new clocks) or `AND` / `AND` / `OR` with a mask register | 0 to 2 |
| `BFM` (EXT across) | cannot be a w-step loop: the cost is independent of w [M] | 0 |

About 4 a routine in `ext` / `exti`, 5 in `ins` / `insi`: **about 18 of 350**.

The long stretches stay: EXT's twelve words after the second shift (w11) and eighteen before
the second read (w17); INS's 18 / 26 before the write (w17 / w24 + 1), 21 (w20), 9 (w8),
10 / 12 (w9 / w11). A second constant pass would explain some (a 16-step pass at one clock a
step fits inside INS's 26), and the "eight fewer when the field ends at bit 15" and "two fewer
at o = 0" are the footprints of skipped loop entries, but nothing dates a word inside those
stretches. **Residual about 272 holds, [U].**

### 3.4 ROM and risk

No depth gain; +18 words if every code is split in place. Width: 13 of the 18 over-wide words
of the four families are here (two of 60 bits: read + two moves + ALU + jump); each has a hold
within two words. Risk: the head's marks, the request and post words of up to two reads and two
writes, the datum words, E held to the write's end; pinned by rounds 12, 13, 16, 21 (Q38, Q44,
Q61, Q96), F32 / F34 / F39 chains and the 256-pair sweep. Do not touch before the other
families: worst ratio of holds explained to risk.

## 4. Family 3: ADD4S / SUB4S / CMP4S, ROL4 / ROR4

### 4.1 ROL4 / ROR4: the one place a loop is missing

Now: `rol4` 22 words (27 holds), `ror4` 22 (35). Register path after the commit word: `R4`
(the whole digit rotate, `v35_rot4`), write AL, write the register, **7 holds (ROL4) or 11
(ROR4)**, E. Memory path: `R4` on the datum word, write AL, **8 or 12 holds**, the write.

Measured [M]: ROL4 reg 18.5, ROR4 reg 22.5, ROL4 mem 24.5 (book 17 / 21 / EA+20); the head
`P . BP . C`, N ten (ROL4) or fourteen (ROR4) words after the commit word; the memory write
nine or thirteen words after the datum. No data dependence seen, but only AW = 0005 and a few
operands were run (160 + 52 runs, 8 + 5 distinct forms). **ROR4 − ROL4 = 4 in every form.**

[V20] 02EC-02F5 / 02F8-02FB: `COUNT <- 4` (ROL4) or `8` (ROR4), `M -> tmpbL`,
`AL:AH -> tmpbH`, then `R ALU ROL12 tmpb`: a 12-bit rotate left by one, four or eight times
(right by a digit = left by eight), then the write-back moves. V20 book 25 / 29: also 4 apart.

| hypothesis | loop clocks ROL4 / ROR4 | set-up + finish | of 10 / 14 words C..E | residual |
|---|---|---|---|---|
| A: V20's, one bit a clock, count 4 / 8 | 4 / 8 | 2 + 2 | 8 / 12 | **2 / 2** |
| B: a digit a pass, the V35's two-word iteration, count 1 / 3 (three left rotations of a digit = one right) | 2 / 6 | 2 + 2 | 6 / 10 | 4 / 4 |

Both give exactly the measured difference of 4; A leaves less and has the V20's precedent. The
totals cannot choose. [U] Either way the loop explains what is now four separate delay
lengths (w6 / w10, w7 / w11): **about 28 of the 62 holds** over the two routines, and the
difference between ROL4 and ROR4 stops being two integers and becomes a count of 4 against 8
taken from the opcode.

ROM: 44 words now; with the loop and one routine for both opcodes (the count from the opcode's
bit 1) about 26 to 30. Needs: a `ROL12` step on {tmpb[11:0]} (new ALU code replacing `R4`;
`v35_rot4` deleted), a count of 4 / 8 (a `cnt` source keyed by op3[0], like `CN_BITS` keyed by
the width), the existing loop. 40-bit: all words fit.

Risk: low on the register path (no bus act between C and E; AL's write before the
register's, F5b `rot4al`, must keep its order). Memory path: the write's post stays nine /
thirteen words after the datum, E on the write's first clock. Gate: Q38 / Q61 runs, F32
`rol4_dl` / `ror4_dl`, F39 / F40, a6.

### 4.2 The BCD strings

Now: `add4s` 26 words (29 holds; SUB4S shares it), `cmp4s` 24 (30). Already a loop of one
pass per byte pair: 19 words a pass, plus the waits on three bus cycles. Measured [M]
23 + 30 per pair (ADD4S / SUB4S), 24 + 25 (CMP4S), no data-dependent exit (CL 1, 2, 3, 4, 8).
[V20] 02CC-02EB: 13 words a pair with the BCD step as `ADC`, `ADJD`, `ADD ONES`; book 7 + 19n.

Small operations: `BCDS` to three words (+2 a pass), `BCDI` / `BCDF` +1 each: **about 4 holds
a routine**. The rest of a pass's holds are the request word (Y), the gaps to the second read
(2) and to the write (4), which are bus pacing, and the head's eight and the tail's seven
(w7, w6), unexplained. [U] Not worth building alone.

## 5. Family 4: shifts, CVTBD / CVTDB, the adjusts

- **Shifts.** `shift_cl` 12 words, `shift_imm` 13, `shift_1` 9, memory forms 60 more. Already
  the smallest operations: `SH1` then `loop=` (two words a count [M]: 10 at n = 0, 12 + 2n,
  n unmasked to 255; the V20 is one `R` row, 7 + n [V20 0229]). 4 to 5 holds a register form:
  the request / commit word (measured bus waits), three book clocks before the zero test, one
  after the loop. The V20 has 7 non-loop words against 5 acting + the zero test here: 1 or 2
  holds become `COUNT` moves or the far jump. **About 8 of 69** over the eight routines.
  Why the V35 spends a second word a count is [U] (mechanisms 3.4).
- **CVTBD.** T 21 [M] (cost 22, book 19, V20 15): pop the byte on word 4, `CVBI`, B, four
  holds, the 8-step divide loop, `CVBF`, the write. V20 011C-0122: 6 non-loop words against
  4 acting: **2 filled**; the three words before the pop are the queue's (every immediate
  routine pops on its fourth word, RESULTS Q24), the rest [U].
- **CVTDB.** T 20 [M] (book 20, V20 7: the V20 multiplies by ten with adds, no loop; the V35
  multiplies by the byte in 8 steps [M f5x]). **2 filled.**
- **ADJ4A / ADJ4S.** T 10 / 9 [M] (book 9, V20 3: `ADJD`, `ADD ONES`, write). 2 acting, 7 to 8
  holds, one a measured B word. **1 or 2 filled**; 5 unexplained. **ADJBA / ADJBS** 17 (V20 6
  words, 0018-001D): about 4 of 26 filled.
- Total: **about 22 of 134**; no ROM gain.

## 6. Family 5 (not studied in depth)

PUSH R / POP R are loops already (8 ROM words each); their clocks are `Y D .` request / datum
triples at a period of nine [M Q, round 9], i.e. bus pacing with marks and the RAMEN hold after
each write. PREPARE (37 words, 30 holds) and the REP heads (`rep_outm` 33 holds, `rep_cmpbk`
29, the 15-clock head of every form) were not decomposed. They belong to the pacing-by-level
question (D4), not to operation size.

## 7. Synthesis

**Hold slots accounted for.** Of the 2,426, families 1 to 4 hold 1,073. A faithful
decomposition explains about **294** (12 % of all; 27 % of these families'): the multiply's
set-up, finish and negation (about 150), the divide's V20 part (about 68), ROL4 / ROR4's
rotate loop (about 28), and ones and twos elsewhere. 131 more are measured bus waits with
marks; 106 are branch or dispatch words the original would also have had. About **542 remain
unexplained**, in five lumps: the divide's 16 / 24 clocks (about 160), INS / EXT's fixed
stretches (about 270), the 4S head and tail and gaps (about 45), the adjusts (about 16), the
shifts' book clocks (about 30).

**ROM words.** Families 1 to 4 are 689 of the 2,848 words. Decomposing in place adds about
250 (a `dly` call of K clocks is one word today). With the V20's sharing, family 1 goes
234 to about 150 and ROL4 / ROR4 44 to about 28; net for the four families about −100 at best,
about +250 at worst. The lens is not a depth reduction. It makes the 40-bit word free in these
families (all 18 over-wide words split into an adjacent hold) and removes the EU's composite
units.

**What remains as holds:** bus waits with marks (keep, D4's question); sequencing words
(real); residual stretches (keep as `dly` calls, labelled OPEN as now).

**Probes that would most reduce the Unknowns** (not run):

1. *Stall map.* For MULU r16, DIVU r16, DIV r8, INS (o 3, w 3), ROR4 r: slide one fetch cycle
   (queue depth by the lead-in, both alignments, 0 and 1 wait) across every clock of the
   instruction and record at which clocks the instruction stretches. Words that stall like the
   loop's steps are loop-like; this is the only pin-level handle on the unmarked stretches
   (it would show whether the divide runs n + 8 steps, and whether INS has a second pass).
2. *DIVU r16 with a non-zero high half.* DW:AW over {0000, 0001, 0020, 00FF, 7FFF} x a divisor
   just above DW, even and odd alignment: settles the open "2 shorter" run.
3. *DIV r16 sign grid.* (+,+), (−,+), (+,−), (−,−), zero remainder, zero quotient, and the
   same four on DIV mem: the word form's +7 and any +1 zero terms like the multiply's.
4. *MULU with a zero high half* (1 x 1 against FFFF x FFFF) at both alignments with an OUT
   marker: confirms the V35 has no V20-style 29 / 30 split on the unsigned form.
5. *ROL4 / ROR4 operand sweep* (AL and the byte over 00, 0F, F0, FF, A5): confirms no data
   dependence before the count becomes 4 / 8.

**Recommended first build: ROL4 / ROR4 as a rotate loop** (best ratio: 28 of 62 holds
explained, two routines, no bus act inside the register path's stretch, the measured 4-clock
difference is the loop's own prediction). Work order outline:

1. Add ALU step `ROL12` ({tmpb[11:0]} left by one) and a 4 / 8 count source keyed by op3[0];
   delete `AL_R4` and `v35_rot4` once the gate passes.
2. Rewrite `rol4` / `ror4` (register path): load byte and AL's low digit into tmpb, the count,
   the one-word `R`-style loop (`alu=ROL12 loop=self`), write AL then the register, the
   residual holds (2, hypothesis A) kept as OPEN; T unchanged at 10 / 14 words C to N.
3. Memory path the same body between the datum word and the write's post (nine / thirteen
   words apart, unchanged).
4. Optionally one routine for both opcodes (D2-style), entry words unmoved.
5. Gate: probe 5 first (socket), then function bench, the Q38 / Q61 qprobe runs, F32 / F39 /
   F40, a6; 17 ns timing as a regression.

Second build, if the first is liked: the multiply's finish and negation (`MULF` into `PASS`,
`NEG`, `NOT`, writes; the `mul` record replaced by the tmpb:tmpc shift pair), unsigned forms
first; then the divide's finish. INS / EXT last or never.

**Rulings needed.**

- R1. Is a named small operation in a clock the pins cannot date preferable to an OPEN hold?
  It replaces "OPEN: a book clock with no act" by an inferred act; the count is unchanged and
  unverifiable. (Rule 4 of 2026-11-09 says loss is recorded, not patched; this is neither.)
- R2. Hypothesis A or B for the digit rotate, and in general: where two sequences fit, follow
  the V20 listing.
- R3. Accept ROM growth (in-place decomposition) or tie each build to sharing (D1 / D2).
- R4. Removing the `mul` / `dv` records changes the EU datapath on the 17 ns path (the
  conditional add inside the shift step); no new inter-unit signal and no port-budget change
  is needed for any build proposed here.
- R5. The divide's 16 / 24 residual and INS / EXT's stretches stay as counted delays in the
  ROM (`dly` calls) until a probe explains them: confirm that is acceptable under the
  2026-11-09 rule, as it is today.
- No build proposed here changes a measured clock.

## 8. Limits of this study

- V20 word counts for the signed forms come from book clocks, not a full trace of the listing
  (my direct count of the signed-multiply path came out 6 short of the V20 book, so I did not
  use it); the "explained" figures inherit that (±20 %).
- The V20 listing itself does not reconcile its byte and word multiply (book difference 8,
  listing words 9; mechanisms 3.4 notes the V30 measures 7).
- The memory forms, 69 / 6B and the per-routine split of the 294 were estimated from the
  register forms, not walked word by word.
- Family 5 was not studied.

## 9. Rulings (the user, 2026-11-18)

- **R1: yes.** Where the pins cannot date an act, a named small operation is preferred to an
  OPEN hold. The word's comment says the act is inferred, not measured.
- **First build: yes**, ROL4 / ROR4 as a rotate loop with the count from the opcode.
- **R3: no tie to sharing.** Short-term ROM growth is accepted; depth is recovered by the
  later sharing steps (options D1 / D2).
- **The V20 listing is a guide to NEC's general architecture, not a thing to clone.** The
  V35's microcode must differ from the V20 / V30's because the instruction timings differ.
  The listing is read for the techniques that keep a ROM small (the repeat flag, shared
  finishes, width by condition, the word format), and those are applied to our routines
  where the V35's measured clocks allow; no routine is copied because the V20 has it. So R2
  ("where two sequences fit, follow the V20") is answered: prefer the sequence that leaves
  the smaller residual and the smaller ROM, with the V20's as a tie-break only.
- R4 (EU datapath for multiply / divide) and R5 (divide and bit-field residuals stay counted
  delay calls) were not ruled on; R5 stays as it is today.
