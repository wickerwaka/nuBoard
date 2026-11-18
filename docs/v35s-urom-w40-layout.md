# V35S core v2: a 2,048 x 40 microcode ROM (2026-11-18, tree at 14ed755)

Design study only. Nothing in the repository was changed, nothing was built in Efinity, the
board was not used. Scripts and their saved outputs are beside this file (section 9); they
run from any directory with `python3 -B <script>` and read the routines through
`validation/v35s/chains/uasm.py` and `urom_stats/v20/depth_stats.py`.

Every figure is tagged **[M: script]** measured (the output is saved as `<script>.txt` unless
named) or **[I]** inferred. "Measured" means measured on the assembled ROM or on a model of
it after sharing; no figure here is a synthesis or timing result.

## 0. Answer

**Yes. 2,048 x 40 in one ROM, 16 block RAMs against today's 60, no side table, no measured
clock moved** — on the condition the depth work already planned brings the word count under
2,048, which it does with tail sharing and hold counts (1,875 words in this layout
[M: fit_shared]).

- The layout (section 2) keeps every field the tick-B logic reads from the ROM data raw and
  at one bit position in every word. The fields read only after the word register (ALU,
  moves, register write, bus request, counter load, rare controls) are two codes into two
  generated tables, expanded between the ROM output and the word register.
- **Present ROM: 2,835 of 2,848 words fit as they stand**; each was packed to 40 bits,
  decoded and compared field by field [M: fit_present]. The 13 that do not fit are one kind
  of word: a register read, a jump target and a late payload in the same word.
- All 13 are cleared without a clock moving (section 4): 7 by placement (the word is laid
  in front of its successor and needs no jump), 2 by the delay call taking its own first
  clock as a word (with hold counts they fit as they are), 3 by moving an act into the
  adjacent word, 1 by running on into a copy of four shared words. Seven more words fit
  only because the REP strings' take entry becomes a sequencing code.
- After tail sharing and hold counts every one of the 1,875 words packs, decodes and
  compares [M: fit_shared]. Tail sharing alone gives 2,193 words in this layout, over 2,048
  as it is without the layout (2,137).
- RTL: the assembler, an expand stage inside `v35_useq`, one line in `v35_eu`. No port is
  added; `v35_uword_t` stays the registered word, so the next-address path and every reader
  of the registered word are untouched.
- The price is logic, not block RAM: the two tables are about 900 LUT4 by estimate
  [M: table_cost, an estimate, not a synthesis], and up to about 8 LUT levels in tick B in
  front of the word register [I]. That path has not been timed. It is the first risk.

## 1. What the word must give early

The ROM is read at tick B; its data is used in the same tick before the word register loads
(`word_nx`), and the registered word is used in tick A to form the next address. The two
worst paths of the core today both start at the ROM data [timing-qp22: +3.6 ns at 17 ns, 8
levels, ROM to the loader; README: the word kind to the bus unit's hold at +2.8 to +3.4].

| Reader in tick B (from the ROM data) | Fields |
|---|---|
| `v35_useq` stall terms and the word kind for the bus unit | `e f nb bi vk ro rl flush` (9 bits), `seq` (is it the dispatch, a take point), `bus` (does it post), `e` with `ea` (the REP re-entry) |
| `v35_loader` (through `v35_top`) | `pop`, `e`, `ro`, `flush` |
| `v35_eu` early register read | `ra`, `rb`, `wid` |
| `v35_eu` request valid for the next clock | `d1`, `d2` (does the next word load OPRW) |
| Tick A, from the word register: the next-address select | `seq`, `cond`, `tgt` |

Raw, these are 9 + 3 (`pop`) + 2 (`wid`) + 5 + 5 (`ra rb`) + 5 (sequencing with its
condition, 20 values used [M: facts]) = 29 bits, and the target is 11: **40 bits with nothing
left for the ALU, the moves, the write or the bus**. That arithmetic is the whole problem.
Two facts get out of it:

1. **A register read has no side effect.** `ra` and `rb` only form the register RAM's read
   address (`rsel_g`; nothing else reads them [M: grep of `v35_eu.sv`]). A word that names no
   register can therefore hold anything in those ten bits: the early read reads a register
   nobody uses. No gate is needed in front of the read address. 2,456 of the 2,848 words
   read no register [M: facts].
2. **A word with a target seldom has a rich payload, and where sharing forces a jump on a
   rich word the assembler can undo that one sharing** at the cost of a stored word, not of
   a clock.

## 2. The layout (L40)

### 2.1 Fixed part: 40 bits, the same in every word

| Bits | Field | Width | Content |
|---|---|---|---|
| 39..35 | SEQ | 5 | sequencing and condition in one code (2.2) |
| 34..26 | K | 9 | `e f nb bi vk ro rl[2] flush`, raw, as today |
| 25..23 | POP | 3 | raw |
| 22..21 | WID | 2 | raw |
| 20..16 | RA | 5 | register selector 0..26, raw. 28..31: the word reads no register; RA[1:0] and RB are payload P (7 bits) |
| 15..11 | RB | 5 | register selector, raw; or payload |
| 10..0 | B | 11 | SEQ >= 8: the target (11 bits at 2,048 words), or the vector number. SEQ < 8: payload, with **B[10] = POST** (the word posts a bus request) |

Selector codes 27..31 are unused today (the highest is 26 [M: facts]); the escape takes
28..31. The early read sees an unknown selector and reads address 0.

### 2.2 SEQ

| Code | Meaning | Code | Meaning |
|---|---|---|---|
| 0 | NEXT | 8 | JMP |
| 1 | NEXT, the E word re-enters the REP page (`e` with `ea=REP`) | 9 | CALL |
| 2 | RET | 10 | LOOP |
| 3 | HOLD (2.5) | 11 | EAC |
| 4, 5 | TKI, take entry 0 / 1 (section 4, way out d) | 12 | JMP after a hold |
| 6, 7 | DISP | 13 | TRAP |
| | | 14 | NEXT, B is the vector number (`vec=`) |
| | | 15 | spare (TKI with a target in B, if a third take entry appears) |
| 16..31 | JC (16 + cond) and JNC (24 + cond) | | |

So that the tick-B bits stay one LUT4 each: dispatch = SEQ[4:1] = 0011, take point =
SEQ[4:1] = 0010, "B is not payload" = SEQ[4] or SEQ[3], REP re-entry = E and SEQ[0] (an E
word's SEQ is 0, 1 or 8; the assembler checks it [M: layout.check_roundtrip]). The condition
select reads SEQ[2:0] as it reads `cond` today.

### 2.3 Late fields: two generated tables

| Table | Fields | Entry | Entries | Used today |
|---|---|---|---|---|
| X | `alu ax ay wf cnt` | 18 bits | 256 | 147 distinct, 148 with page copies [M: fit_present] |
| Y | `d1 s1 d2 s2 wr ws ea bus seg pfx susp halt ist` | 35 bits | 2 x 256: the entries that post a request and those that do not | 167 distinct (136 + 33), 169 with page copies [M: fit_present] |

The tables are generated by the assembler from the routines, as the decode tables are. A
form with room for a full code reads the whole table; a form with less room reads a fixed
page of it, whose base is an address prefix (the table address is the prefix and the code:
no adder). The assembler places a payload in every page whose words need it.

### 2.4 Forms

The form is decided by RA >= 28 (no register: N, else R), SEQ >= 8 (T) and SEQ = 3 or 12 (H).
Only the late decode reads the form.

| Form | Words today [M: fit_present] | Payload bits | Coding |
|---|---|---|---|
| N: no register, no target | 1,931 | P7 + B11 = 18 | B[10] POST, B[9:2] Y (8), {P, B[1]} X (8), B[0] KW (the word loads OPRW: the arming word of an unarmed write) |
| NT: no register, target | 525 | P7 | P < 48: X page; 48..95: Y page, no post; 96..127: Y page, posts (so POST = P[6] and P[5]) |
| R: register, no target | 379 | B11 | B[1:0] = 00: X (8) at B[9:2]. 10: B[10] POST, Y (8) at B[9:2]. B[0] = 1: B[10] POST, Y page (5) at B[9:5], X page (4) at B[4:1] |
| RT: register, target | 13 | none | **the words that do not fit** when they also carry X or Y |
| NH: N with a hold count | - | P7 + B[4:0] = 12 | B[10] POST, B[9:6] count - 1, B[5] the mark on the last held clock, then X page (6), Y page (6) |
| RH: R with a hold count | - | B[4:0] | as NH; B[4] = 0: X page (4), 1: Y page (4) |
| NTH: target and hold count | - | P7 | P[4:0] count - 1, P[5] the mark; no payload |

Every word of a form is the same layout; there is no per-opcode case. What decides the form
is in the word.

### 2.5 Hold counts (technique 2 of the V20 techniques document)

HOLD is a sequencing code; the count has its own bits (4 bits, 1 to 16 clocks; 5 bits where
the word also jumps) and one bit for the derived last-clock mark that `depth_stats.py` folds
into a hold. A hold of more than 16 keeps 16 and passes the rest to an empty word behind
(12 words have a count over 16 [M: facts]). Without hold counts the codes 3 and 12 are
simply unused; the rest of the layout is the same.

### 2.6 Decode cost

**Tick B, from the ROM data, no table:**

| Bit | Logic | Today |
|---|---|---|
| K, POP, WID, RA, RB | wires | wires |
| dispatch, take point | one LUT4 on SEQ[4:1] | one LUT4 on `seq` |
| REP re-entry | E and SEQ[0] | `e` and a 2-bit compare |
| POST | (SEQ[4] or SEQ[3]) ? (RA = 31) : B[10]; 8 inputs, **2 levels** | a 3-bit compare, 1 level |
| KW (the next word arms an unarmed write) | RA[4:2] = 111, SEQ < 8, SEQ != 3, B[0]; **2 levels** | two 3-bit compares and an OR, 2 levels |

POST is the one early bit that gains a level; it feeds the slot stall, which is not on
today's worst paths [I]. KW is exact where it matters: the two arming words of the ROM are
form N in the present ROM and after sharing [M: fit_present, fit_shared].

**Tick B, from the ROM data to the word register (the expand stage):** the form (3 LUT
inputs' worth), the table address by form, the two tables, SEQ to `seq` / `cond`. By
estimate X is about 340 LUT4 and 5 levels, Y about 600 LUT4 and 6 levels [M: table_cost:
Shannon decomposition on the codes as generated, shared sub-functions, not optimised, not a
synthesis]; with the address select in front, about 8 levels [I]. The path ends at the word
register; nothing is behind it in the tick.

**Tick A:** nothing new. The next-address select reads the registered `seq`, `cond`, `tgt` of
`v35_uword_t` exactly as today; no format decode stands in front of it. For TKI the expand
stage loads `tgt` with the generated take entry, so the select does not change either. The
high ROM part, its registered select bit and its copy of the last address stage go.

## 3. The present ROM through the layout

[M: fit_present; `fit_present_notki.txt` without the take-entry codes]

| | Words |
|---|---|
| Fit: packed to 40 bits, decoded, every field equal, the five early bits equal (targets modulo 2,048, since the present ROM has 2,848 words) | 2,835 |
| Do not fit | 13 |
| ... without the two take-entry codes | 20 |

The 20, with the routine, the conflict, the corpus chain runs that enter the routine
[M: corpus_routines: 35,204 chain runs, 176 of 284 routines entered] and what clears each
[M: resolve]:

| Word | Fields | Conflict | Runs | Cleared by |
|---|---|---|---|---|
| rep_movbk+5, rep_stm+5, rep_ldm+5, rep_inm+5, rep_outm+5 | `ra d1=ADDR s1=RA tki=` | register + target + Y | 120 to 342 each | d: take-entry code |
| rep_cmpbk+19, rep_cmpm+8 | `ra=IY alu=STEP ax=RA tki=` | register + target + X | 246, 240 | d: take-entry code |
| rep_stm+1 | `ra=AW d1=OPRW s1=RA jnc=SNZ:` | register + target + Y | 342 | a: the act moves to the empty word behind (c6) |
| rep_cmpbk+1, rep_cmpm+1 | `rb=IY d1=ADDR s1=RB jnc=SNZ:` | register + target + Y | 246, 240 | a: the act is dropped; the words before and behind make the same load |
| rep_cmpbk+5 | `ra=IX d1=ADDR s1=RA call=w2` | register + target + Y | 246 | a: the call takes its first delay clock as a word (+1); with hold counts it fits as it is (form RH) |
| bcwz+0 | `rb=CW alu=PASS ax=RB call=w2` | register + target + X | 60 | the same |
| ext+11, ins+11 | `ra rb d1 d2 alu=ADD jmp=` | register + target + X + Y | 258, 138 | placement: the word falls through, no jump |
| brkcs+3 | `ra d1 d2 alu=BSW jmp=` | register + target + X + Y | 0 | placement |
| mulimm_rw+4, mulimm_rb+3 | `rb=RM alu=MULI cnt=BITS jmp=` | register + target + X | 18, 18 | placement (the sharing joins the two words; the one word falls through) |
| rep_cmpbk+24 | `ra=CW alu=DEC ax=RA jmp=rcb_q` | register + target + X | 246 | placement: the loop is closed by another of its words |
| si_first+1 | `ra=IY alu=STEP ax=RA jmp=` | register + target + X | 0 | placement |
| si_first+0 | the same | register + target + X | 0 | U: runs on into a copy of four shared words |

14 routines hold these words; 12 are entered by corpus instructions, brkcs (BRKCS) and
si_first (a REP string's interrupt entry) are not [M: corpus_routines].

## 4. The ways out

**a. Split into an adjacent hold slot.** Used for five words, no clock moved:

- The two delay calls (`call=w2` on a word with a register read and a payload): the call
  moves to an empty word behind, which is the delay's own first clock. One stored word each.
  With hold counts the count is in the word and nothing is needed.
- Three source edits in the REP string heads (`lib.A_EDITS`; applied in memory by the
  scripts): `rep_stm` c5 loads the write datum from AW and tests the count; c6 is an empty
  word, the load moves there (the datum is used six words later). `rep_cmpbk` and `rep_cmpm`
  c5 repeat the address load that c4 and c6 also make; c5's copy goes. These change which
  clock an internal act is written on, not the count of clocks; the corpus replay is the
  proof and all three routines are in it.
- Where no adjacent slot exists nothing was split: no word needed it.

**b. A parallel side table** (low k address bits, each entry tagged with the page it belongs
to and carrying a full X and Y code; read beside the main ROM, no second read in series).
Not needed, evaluated as the fallback [M: side_table]:

| ROM | Wide words (before the assembler ways out) | Chains with one | Consecutive wide words | k = 7 (128 x 21, LUT ROM, 0 blocks) | k = 8 (256 x 20, 1 block) |
|---|---|---|---|---|---|
| Tail sharing | 41 (5 more are sequencing conflicts an entry does not clear) | 40 | none | placed, 0 padding | placed, 0 padding |
| + hold counts | 73 (17 more are count or sequencing conflicts) | 66 | none (eight in `push_all`, never adjacent) | placed, 0 padding | placed, 0 padding |

Chains are moved whole, so no jump is forced; the holes the placement opens are filled by
chains without a wide word. It would make the total 17 block RAMs at k = 8, or stay at 16
with about 170 LUT4 more at k = 7 [I], and save about 80 of the stored words the assembler
ways out add. It costs a second decode source for the late fields. Keep it in reserve.

**c. A mode latch.** No word needs one. The nearest case is the take entry of the REP
strings, which is static per word and is better as a code (d).

**d. What is better.**

- **Take-entry codes.** All seven TKI words are register reads with a payload, and there are
  two take entries in the ROM (`rep_brk`, `si_cmp`) [M: facts]. TKI becomes two codes; the
  entry comes from a generated two-entry constant, as the dispatch's interrupt entry does
  today (`UROM_INT`). Clears 7 words, moves no act.
- **Placement.** A jump on a wide word disappears when the word is laid in front of its
  successor. The layout pass tail sharing needs anyway chooses, for every shared word, which
  predecessor falls through: here the one that could not carry a jump.
- **U, un-share.** Where two wide words run on into the same shared word, one of them runs
  on into a copy of that word, and the copy jumps on. Stored words only.
- **S, shed the count.** A word with a hold count and no room for it passes the count to an
  empty word behind it: the first held clock becomes that word. Stored words only.

## 5. After sharing

[M: fit_shared; the ROMs are in `rom_pt.lst`, `rom_ph.lst`, the tables in `tables_*.txt`]

| | Tail sharing | Tail sharing + hold counts |
|---|---|---|
| Words after sharing (the layout pass of `lib.py`; `depth_stats.py` says 2,134 and 1,775) | 2,137 | 1,775 |
| Do not fit before the ways out | 46 | 90 |
| ... a jump forced by sharing on a register word with a payload | 29 | 25 |
| ... a forced jump on a word with X and Y, or on an EREP / vector / arming word | 14 | 11 |
| ... hold count with no room (with a target, over 16, or with X and Y on a register word) | - | 53 |
| ... the present ROM's own (the two delay calls; one register word) | 3 | 1 |
| U applied / words added | 44 / 54 | 37 / 47 |
| S applied / words added | - | 53 / 53 |
| Delay call split / words added | 2 / 2 | - |
| **Final words** | **2,193** | **1,875** |
| Packed, decoded, compared equal | 2,193 | 1,875 |
| Do not fit | 0 | 0 |
| Table entries used (X of 256, Y of 512) | 147, 170 | 156, 181 |

The layout costs 56 stored words on tail sharing and 100 with hold counts, all executed
exactly as the words they stand for. Tail sharing alone is over 2,048 with or without the
layout; with hold counts there are 173 words of room. Head sharing and steering (techniques
3 and 4) were not run through the layout; they remove words and add calls from the dispatch,
which need no field [I].

## 6. The answer in block RAMs

| | Main ROM | Side table | RAM_5K |
|---|---|---|---|
| Today | 2,048 x 96 + 1,024 x 96 | | 60 |
| 2,048 x 96 after the depth work | | | 40 |
| **L40** | **2,048 x 40** | **none** | **16** |
| L40 with way out b instead of U and S | 2,048 x 40 | 256 x 20 | 17 |
| A 45-bit word | 2,048 x 45 | | 18 |

Other widths [I, from the measured counts]: 35 bits cannot hold the 29 early bits and an
11-bit target, so every word with a target (393 after sharing and hold counts) would need a
side entry: 512 x 20, two blocks, 16 in all, with a placement that is no longer easy. No
gain. The two-level form of the options document (W2) does not win in this count either
once the early fields must stay in the first level: 29 early bits, a 10-bit index and an
11-bit target are 50 bits.

**RTL changes.**

| Where | Change |
|---|---|
| `uasm.py` | the layout pass (shared with tail sharing), the L40 packer, the X / Y tables and their pages, the two take entries, the checks (an E word's SEQ; an arming word is form N; selector codes under 27; a third take entry), the listing and `unpack` for the tools |
| `v35_pkg.sv` | the raw 40-bit word type; `v35_uword_t` kept, one bit `kw` added (and the hold count with technique 2) |
| `v35_useq.sv` | one ROM of 2,048 x 40 (the high part, `hi_b` and `rah` go); the early bits from the raw word; the expand stage in tick B in front of the word register |
| `v35_eu.sv` | `k_nx` reads the next word's `kw` bit; the `+v35_chk` compare of the early read address applies only when the word names a register |
| Loader, bus unit, queue, top | none. No port is added or widened in the budget's terms |

No per-opcode case, no fitted integer: the page sizes are properties of the forms, and
which payload sits in which page is generated.

## 7. Risks, ranked

1. **The expand stage's depth in tick B** (about 8 LUT levels by estimate, from a block RAM
   output). Not timed. If it fails: give each page its own small table and select last; order
   the codes so the common payloads decode shallow; or fall back to way out b for the pages,
   which shortens the R and NT forms' decode. The `hi_b` select leaving the ROM data gives
   one level back to every tick-B path.
2. **POST gains one level** in front of the slot stall, KW changes shape in front of the
   request-valid term. Both are small and both are on paths that are not the worst today,
   but the worst paths start at the same ROM data and the margin is 2.8 to 3.6 ns.
3. **Page room for new microcode.** Tight pages today: R with X and Y (X page 15 entries, 12
   to 14 used; Y page 31, 16 to 18 used), RH (X 15, 13 used; Y 15, 14 used), NT (X 47, 41 used; Y 48, 48
   used after tail sharing) [M: pages_demand]. An NT, NH or RH overflow costs a stored word
   (U or S). An overflow of the R page with X and Y has no assembler way out: such a word
   must be written with another payload already in the page, or take way out b.
4. **No spare bit in the fixed part and one spare SEQ code.** A new late field is a table
   column and costs no ROM width. A new early field has no place.
5. **The three source edits** and the rule that a word naming no register reads a garbage
   register address. Both are behaviour-neutral by argument; the corpus and `+v35_chk` must
   say so.
6. **Tools that read fields from the ROM image**: `qprobe/tools/romcheck.py`, `test_uasm.py`,
   `test_v35_struct.py` (the word's field list), the listing and the side-by-side tool, the
   `urom_stats` scripts. All read through `uasm.FIELDS` / `unpack`; they need the 40-bit
   unpack and, as with tail sharing, a routine that is no longer contiguous.
7. **Depth.** The ways out add 100 words; the figure moves with every routine change. The
   assembler should report it.

## 8. First build step

In the assembler, behind tail sharing's layout pass: the L40 packer and table generator in
check-only mode (`--w40-check`: pack every word, decode, compare, list what does not fit and
which way out cleared it), with the three source edits and the two take-entry codes. No RTL.
It turns sections 3 and 5 from a model into the real ROM. The second step is the expand
stage in `v35_useq` with the 96-bit ROM still present in simulation and `+v35_chk` comparing
the expanded word with it every clock, then the 17 ns timing run of `v35_useq` alone and of
the top.

## 9. Scripts

| Script | Output | What |
|---|---|---|
| `measure.py` | `measure.py.txt` | used values per field, co-occurrence of field groups |
| `facts.py` | `facts.txt` | the small counts quoted above |
| `contexts.py` | `contexts.txt` | late payloads by register use, target and hold |
| `pages_demand.py` | `pages_demand.txt` | demand on each page |
| `lib.py` | | the three word populations; the layout pass after sharing; the source edits |
| `layout.py` | | L40: fit test, encoder, decoder, early bits, round-trip check |
| `fit_present.py` | `fit_present.txt`, `_a.txt` (A=1), `_notki.txt` (TKI=0) | section 3 |
| `fit_shared.py` | `fit_shared.txt` | section 5 |
| `resolve.py` | `resolve.txt` | what clears each of the 20 words |
| `corpus_routines.py` | `corpus_routines.txt` | routines entered by corpus chain instructions |
| `side_table.py` | `side_table.txt` | way out b |
| `table_cost.py` | `table_cost.txt` | LUT4 estimate of the tables |
| `dump_rom.py` | `rom_pt.lst`, `rom_ph.lst`, `tables_pt.txt`, `tables_ph.txt` | the packed ROMs and tables |

## 10. Limits

- The ROM after sharing is a model: `depth_stats.py`'s classes with a layout pass added here.
  The assembler's own tail sharing is being built and will differ in detail.
- A held clock is taken to be an empty word's clock, as technique 2 assumes.
- The corpus count covers chain runs only; the case-type files (`p2-*`) carry no instruction
  list and are not counted.
- The LUT figures are a decomposition estimate. No timing figure in this document is new.
- The side-table placement is first-fit on chains, without the dispatch's entry tables;
  those are generated and place no constraint [I].
