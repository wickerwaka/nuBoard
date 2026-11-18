# V35S core v2: options for a smaller microcode ROM (2026-11-18, tree at acaf86f)

Figures are from `validation/v35s/chains/urom_stats/` (`fields.py`, `groups.py`, `merge.py`,
`pacing.py`; run with `PYTHONPATH=host/src:. python3 <script>` from the repo root). They are
measurements of the present ROM and estimates of what each option could reach; nothing here
has been built.

## What the ROM is today

- Address 12 bits. Storage 2,048 x 96 (low part) + 1,024 x 96 (high part) = 294,912 bits;
  2,848 words used in 284 routines. 30 M10K in Quartus, 60 of the 108 RAM_5K in Efinity.
- The word is horizontal: 33 fields, 96 bits, every field present in every word.
- **The word is sparse.** Median word uses 17 bits of its fields, 90 % use 28 or fewer.
  Only **758 distinct words** exist in the 2,848; without the 12-bit target, **568**.
  Each field group is used by a minority of words: sequencing 27 %, queue 23 %, ALU 16 %,
  bus 14 %, register read 13 %, move 13 %, register write 7 %, second move 3 %.
- **Nearly half the depth is pacing.** 1,377 words (48 %) have no datapath, bus or pop act:
  they exist because one ROM word is one CPU clock. Of them 266 are calls into the shared
  delay routine `dly`, 212 are completely empty, the rest carry only word-kind bits
  (bus-idle, release, boundary marks).
- Largest sources: mem.uasm 682 words, xfer.uasm 509, str.uasm 264, loop.uasm 215,
  bf.uasm 204, page.uasm 190.

The V30 class of ROM (about 1,024 x 32 = 33 kbit) is nine times smaller than the storage
here. Width is the cheaper half to recover; depth is bounded by the pacing words.

## Width options

| Option | Result | Cost and risk |
|---|---|---|
| **W1. Two-level ROM (pointer + word table).** The first ROM holds a 10-bit index per address; a second ROM holds the 758 distinct words. | 2,848 x 10 + 758 x 96 = 101 kbit (34 % of today's storage). | A second lookup in series. The sequencer reads the ROM at tick B and registers the word at tick A, so the second read may fit in that slot; whatever now reads the raw ROM output in between (the pre-decode) has to move. Needs a timing study. No change of behaviour. |
| **W2. Two-level, sequencing kept in the first level.** First level 32 bits: index 10, seq 4, cond 3, target 12, 3 spare. Second level 568 x 77. | 91 kbit + 44 kbit = 135 kbit. A 32-bit first-level word, as the originals had. | As W1, but the next-address path does not wait for the second lookup: the safer of the two for the ROM-address timing path. |
| **W3. Word formats.** A 2- or 3-bit type selects which field groups the payload carries (move / ALU word, bus word, sequencing word, pacing word). | About 40 to 48 bits wide. | 47 words use more than 40 bits of groups and 16 more than 48; each would need a second word, which is a second clock, so those routines must be reshaped another way or the format widened. Changes every decode of the word; the highest risk to exactness and timing of the width options. |
| **W4. Per-group dictionaries.** Each group replaced by an index into a small table (ALU 139 combinations in 8 bits for 15, register read 42 in 6 for 10, and so on). | About 72 bits. | A small gain for a table lookup in front of every control signal. Not recommended alone. |
| **W5. Plain field packing.** | 92 bits. | Not worth doing: the fields are already near their minimum individually. |

## Depth options

| Option | Result | Cost and risk |
|---|---|---|
| **D1. Merge identical tails.** Words with the same fields and the same continuation are stored once; the other routines jump to them (a jump is in the word's own sequencing field, no extra clock). | 2,848 to about **2,134** words (2,104 distinct, about 30 copies forced where the preceding word's sequencing field is busy). | Assembler work only (`uasm.py`), no RTL change, behaviour identical clock for clock: the corpus gate proves it. The listing, the book check and the side-by-side tool assume a routine is contiguous and need adapting. |
| **D2. Parameterise from the instruction register.** One routine for forms that differ only in width, ALU operation, register or segment select, the field taken from the opcode. | With D1: about 2,047 (width + ALU), 2,004 (+ registers), **1,941** (+ segment / EA). | Small gain. It gets D1 under 2,048 words, which removes the high ROM part (10 M10K) and one address bit. New selects on datapath control lines. |
| **D3. A hold count on a word.** A word may say "then idle n clocks" with a pacing kind, in place of n pacing words behind it. | Up to 583 words on the present ROM (337 runs of 1 to 6 words, 25 distinct pacing kinds); overlaps with D1, so the sum is less than both. | A new sequencer mechanism (a word that lasts several clocks, a 3-bit count and a kind). It is a count in the ROM, so it needs a ruling against the 2026-11-09 rule that every delay has a machine explanation. |
| **D4. Pacing by level, not by word.** Words wait for a bus or queue level (cycle end, queue count, request taken) where the ROM now counts clocks. | The only route to the 1,024 class: 1,471 words are not pacing; how far they merge afterwards is not measured. | A redesign of how the EU and bus unit hand off, against measured clock-exact behaviour. Each wait needs a level found on the socket (round 26 could not find one for the `J` word). Corpus exactness is at risk throughout. Research, not an optimisation round. |

## Combinations

| Combination | Storage | vs today |
|---|---|---|
| Today | 3,072 x 96 = 295 kbit | 100 % |
| D1 alone | 2,134 x 96 = 205 kbit (still needs the high part) | 69 % |
| D1 + D2 (under 2,048 words) | 2,048 x 96 = 197 kbit | 67 % |
| W1 alone | 101 kbit | 34 % |
| D1 + W2 | about 2,134 x 32 + 568 x 77 = 112 kbit | 38 % |
| D1 + D2 + W1 | about 2,048 x 10 + 758 x 96 = 93 kbit | 32 % |
| 1,024 x 32 class | 33 kbit | 11 % (needs D4 and W3) |

The second-level table sizes after D1 / D2 are taken unchanged (merging removes repeats of
words, not distinct words); D2 would shrink the table as well, by an amount not measured.

## Recommended order

1. **D1** first: no RTL change, proof by an identical corpus, and it shows the real merged
   count rather than the estimate.
2. **W2** next, behind a timing study of the second lookup at tick A. It gives the 32-bit
   first-level word and two thirds of the storage back without touching behaviour.
3. **D2** if the count after D1 is close enough to 2,048 to drop the high part.
4. **D3** and **D4** only on a ruling: D3 is a count in the ROM, D4 reopens the timing work.

W3 is the alternative to W2 if a single-level ROM is wanted for its likeness to the
original; it costs more and endangers the 63 widest words' clocks.
