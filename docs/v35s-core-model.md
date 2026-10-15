# V35S cycle model (Phase 2, in progress)

The Python cycle model in `validation/v35s/model/` is the reference the new
RTL core will be written against ([`v35s-core-plan.md`](v35s-core-plan.md),
Phase 2). It runs a corpus image from reset and emits lane-format bus
traces. `python -m validation.v35s.fit` compares them with the silicon
corpus over each measurement window.

## Layout

| File | Role |
| --- | --- |
| `model/machine.py` | Clocked engine: bus cycles (B1 B2 waits B3), the prefetch queue, refresh, PRC/WTC/RFM, internal RAM and SFR storage, lane-format trace records |
| `model/eu.py` | Execution unit: decode and semantics for the V20/V35 instruction set, registers in the banked internal RAM, timing as named steps |
| `model/costs.py` | Every fitted number: bus-unit rules and per-step EU clocks |
| `fit.py` | Runs the model on corpus entries; `--prefetch ENTRY` compares the prefetch scenarios |

The EU is a generator. Each instruction yields its requests in order:
- `byte` takes a queue byte;
- `clocks` spends execution time;
- `read` and `write` are bus or internal accesses;
- `flush` handles a taken transfer.

The engine resolves them clock by clock against the bus unit.

## Fitting tools

| Tool | Scores |
| --- | --- |
| `fit.py` | whole windows and prefetch scenarios, cycle by cycle |
| `fit_costs.py` | per-placement instruction costs (window minus empty window), model against silicon |
| `fit_hide.py` | which routines hide a clock of a word load, from the odd-minus-even costs |
| `fit_steps.py` | EU step values, coordinate descent against `fit_costs`' measure |
| `fit_window.py` | integer costs (and optionally `decode_skip`) against whole-window exactness over all five corpora |

The odd-minus-even cost of a form is independent of its step values, so it
scores the queue and decode structure on its own. Fit the structure with it
first, then the step values.

## Decode stage: what the data says

### Placement costs (A6, both placements)

| Form | Even | Odd |
| --- | --- | --- |
| NOP, XCH AW,r, CVTBW, PUSH r | 3/5, 3/5, 2/4, 8/10 | (odd pays 2) |
| INC/DEC r16, the flag operations, CVTWL, IN/OUT DW, LDM, MOVBK, POP r, POP R | — | odd pays 1 |
| 2-byte register forms | equal | equal |
| 2-byte memory reads | — | +1 at odd |
| TEST r,r, read-modify-write, the 0F immediate bit operations | — | −1 at odd |
| 3-byte imm16 forms | — | +2 at odd |

In a word-wide decoder, an instruction pays for loading the queue word that
its next byte sits in. These figures fit:
- a 2-clock word load;
- per routine, hiding one clock of either the next opcode's load (end) or an
  operand's load (mid).

`fit_hide.py` picks the hide bits routine by routine: total odd-minus-even
error 19 clocks over about 180 forms.

### Queue word release: the open question

The fetch that refills the slot behind a target at an even address (A6,
window clocks) depends on the target itself:

| Target | Refill fetch |
| --- | --- |
| register ModR/M forms, any length (ADD r,r 3 clocks, MULU CL 26) | 64 |
| imm8 / disp8 forms (MOV r8,imm, OUT imm, Bcc) | 67 |
| imm16 / disp16 forms | 68 |
| 1-byte forms | close to their end: CVTWL 71, POP r 73, STM 77, MOVBK 85, RET 90, PUSH R 138 |

Two queue models compete:

1. **Word register (implemented).** The EU moves the queue's head word into
   a word register, freeing its slot. There are 3 queue slots, plus the
   register.
   - It reproduces the depth scenarios and the NOP runways.
   - It cannot make the refill depend on the target's operands or length.
2. **Consumption.** There are 3 word slots, and a word frees when all of its
   bytes are consumed.
   - The next opcode is consumed by the previous instruction's last step.
   - Operand bytes are consumed at their micro-step: imm8/disp8 3 clocks
     after the opcode, imm16 at +4 and +7.
   - This is nuV30's "one queue byte per micro-op read".
   - It explains the table above, depth-odd, depth-2byte and the branch
     scenario, where silicon makes no fetch between a jump's decode and its
     refill.
   - It fails only depth-even, where silicon fills one word further while
     `SHL AW,16` runs.

**Compared, 2026-10-12.** Both models are implemented (`costs.PROFILES`,
selected with `V35S_PROFILE=iwr|consume`). Each was given its own hide-bit
and step-value fit. `python -m validation.v35s.compare_models` scores them:

| Measure (a6-timing, m-prefetch-w0) | Word register | Consumption |
| --- | --- | --- |
| windows exact | 44 / 558 | 0 / 558 |
| window length exact | 379 / 558 | 24 / 558 |
| cycles in place | 72 % | 9 % |
| placement costs exact | 377 / 552 | 247 / 552 |
| odd-minus-even exact (independent of step values) | 237 / 259 | 122 / 259 |
| refill fetch exact | 198 / 293 | 152 / 293 |
| prefetch scenarios exact | 0 / 19 | 0 / 19 |

The consumption model is worse on every measure:
- **The step-independent row:** it is worse on odd-minus-even (47% against
  92%).
- **The refill row:** it is also worse on the observation that motivated it.
- **Its hide-bit fit:** error 201 clocks against 19, leaning on mid-hide bits
  for every imm16 form.

So operand consumption at fixed micro-steps is not the release rule. The word
register stays the default.

### Release probe and consumption variants, 2026-10-13

The `release` probe suite (`probes.py`, corpus entry `p2-release`, 172 cases)
puts 1-byte and longer targets at both parities after a saturated runway,
with varied followers and back-to-back pairs. Behind a target at 5Ah, the
fetch of word 60h comes:
- 64 after INC, NOP or MULU CL;
- 67 after MOV CL,imm8;
- 71 after CVTWL and 79 after ADJBA;
- for `SHL AW,4` (even), word 60h at 64 and word 62h at 67, so the next
  opcode, sharing a word with the count, is taken early.

That suggested adding a decode lookahead to the consumption model: an
instruction's last L execution clocks are spent after the next opcode is
taken (`costs.lookahead`). With `lookahead_after_operands`, an instruction
that ends on an operand byte takes the next opcode right after that byte.
Five variants were fitted (hide bits, then steps) and scored with
`compare_models --variant`:

| Measure | iwr | consume | L=1 | L=2 | L=3 | L=2, no word load | L=2, after operands |
| --- | --- | --- | --- | --- | --- | --- | --- |
| window length exact | **68%** | 4% | 3% | 23% | 31% | 0% | 28% |
| cycles in place | **72%** | 9% | 9% | 11% | 36% | 7% | 12% |
| aligned cycles in place | **64%** | 45% | 48% | 48% | 53% | 6% | 48% |
| placement costs exact | **68%** | 45% | 46% | 47% | 62% | 44% | 47% |
| odd-minus-even exact | **92%** | 47% | 58% | 56% | 76% | 36% | 56% |
| refill fetch exact | **68%** | 52% | 50% | 54% | 50% | 0% | 54% |
| release cycles in place | **61%** | 48% | 48% | 42% | 44% | 6% | 44% |

Lookahead helps the consumption model steadily but never catches the word
register, even on the refill and release rows. Without the 2-clock word
load nothing fits, so the load is real. The consumption variants also
mis-time the NOP runway: their aligned scores are far above their unaligned
ones.

### Two-word register, 2026-10-13

`queue_model = "two_word"` (profile `two_word`): the register holds the
current word and the next, so a word holds its slot until its last byte is
consumed. `queue_words` counts both register words. It explains odd-placed
`MULU CL`: there the ModR/M byte shares word 5Ch with the next opcode, and
silicon holds off fetching word 60h until MULU is nearly done (87 against 64
at even). Fitted and scored like the consumption variants:

| Measure | iwr | depth 4 | depth 4, L=2 | depth 3 | depth 3, L=2 |
| --- | --- | --- | --- | --- | --- |
| window length exact | **68%** | 35% | 33% | 35% | 33% |
| cycles in place | **72%** | 8% | 8% | 9% | 11% |
| aligned cycles in place | **64%** | 53% | 52% | 50% | 51% |
| placement costs exact | **68%** | 64% | 64% | 64% | 64% |
| odd-minus-even exact | **92%** | 73% | 80% | 73% | 80% |
| refill fetch exact | **68%** | 0% | 0% | 46% | 54% |
| release cycles in place | **61%** | 44% | 43% | 42% | 44% |

It loses too. At depth 4 the NOP runway runs about 5 clocks ahead, and at
depth 3 about 3 behind: releasing on a word's last byte puts the runway
fetches at the wrong phase, where iwr's release on loading the word puts
them right.

**The pattern no model makes yet.** After a 1-byte target, or one whose last
byte shares a word with the next opcode, silicon fetches two words back to
back (3 clocks apart). The baseline keeps a steady 8-clock cadence:

| Target (word 5Ah) | Silicon: 60h, 62h | iwr |
| --- | --- | --- |
| INC AW, even | 64, 67 | 64, 71 |
| CVTWL, even | 71, 74 | 64, 78 |
| ADJBA, even | 79, 82 | 64, 86 |
| MOV CL,imm8, even | 67, 70 | 64, 70 |
| MULU CL, odd | 87, 90 | 65, 94 |
| MULU CL, even | 64, 90 | 64, 90 |

iwr usually places the later fetch close to silicon (within 4 clocks), but
issues the first one too early. In silicon a slot is free, yet the fetch
waits for a point in the instruction, and then both go out together. Two
quick checks (not fitted) did not reproduce this:
- a byte queue that fetches when 2 bytes are free, as the V30's does (6 to 9
  bytes);
- blocking fetch starts during EU execution clocks.

The next candidate is a fetch request that the EU issues at particular
micro-steps, rather than one the bus unit makes whenever a slot is free.

### EU-issued fetch requests, 2026-10-13

The bus unit fetches only on a request from the EU. The options are in
`costs.py`:
- `fetch_request`: "opcode", "take" (any queue byte) or "ask" (when the EU
  asks for an opcode, before the byte arrives);
- `fetch_grant`: "free" grants every free slot, "one" a single fetch,
  "until_full" fetches freely until the queue fills and then waits for a
  request;
- `fetch_request_delay`.

The screen used the release probe, unfitted. It counts runs whose post-target
fetch list matches silicon exactly, aligned on the 58h fetch, from a grid of
192 combinations: release on load or on consumption, depth 3 or 4, the
request kinds, both grants, lookahead 0 to 3, delay 0 to 2.

| Rule | Exact fetch lists |
| --- | --- |
| iwr (no requests) | 20 / 174 |
| request on each opcode or byte take, grant free slots | **42 to 44 / 174** |
| request when the EU asks for an opcode | 20 / 174 |
| fill freely, then wait for a request (hysteresis) | 20 / 174 |
| two-word release with any request kind | ≤ 41 / 174 |
| depth 4, any rule | ≤ 15 / 174 |

The gain is not real. A request on the opcode take works because it lands
2 clocks after the EU asks, and that delays the whole NOP runway by 2 clocks
from the marker on. Fitted (hide bits and steps), it scores below iwr:

| Measure | iwr | opcode-take request |
| --- | --- | --- |
| window length exact | 68% | 67% |
| cycles in place | 72% | 9% (runway 2 clocks late) |
| aligned cycles in place | 64% | 57% |
| placement costs exact | 68% | 68% |
| odd-minus-even exact | 92% | 83% |
| release cycles in place | 61% | 56% |

The runway can only be put back at the right time by a request at the ask
or by the hysteresis rule. Both reproduce iwr exactly, because the slot
freed by the target's own word load is seen at once.

**What the release data needs.** Behind every 1-byte target at an even
address, the fetch of word 60h comes at the target's end, and word 62h
follows 3 clocks later:

| Target | 60h fetch, relative to the NOP baseline |
| --- | --- |
| INC, CVTBW, CLR1 | +0 |
| CVTWL | +7 |
| ADJ4A | +8 |
| ADJBA | +15 |

The slot freed when the target's word loads goes unused until the target
finishes, and then two fetches go out. Two-clock targets (INC, CVTBW, CLR1)
burst, but three-clock ones (NOP, XCH AW,CW) do not. Every rule tried that
holds the first fetch back far enough also shifts the runway. The next step
is probes rather than rule guessing:
- vary the instruction before the target and the number of NOPs after it,
  to find which event releases the held fetch;
- check whether the 2-clock against 3-clock difference follows the
  instruction's length or its phase against the bus.

### Held-fetch probe, 2026-10-13

The `held` suite (`probes.py`, corpus `p2-held`, 94 cases, both placements)
has three parts:
- trains of one instruction at a steady consumption rate;
- 1-byte targets behind 0 to 3 `INC AW` (2 clocks each, which moves the EU's
  phase against the bus);
- `SHL AW,CL` and `SHL AW,imm` of graded length.

The trains show that silicon prefetches in bursts (clocks from the opening
marker, even placement):

| Train | Fetches after the runway |
| --- | --- |
| NOP, XCH AW,CW (3 clocks) | one word every 8 clocks |
| INC AW, CLR1 CY (2 clocks) | two back to back every 10 clocks: 64 67, 74 77, 84 87 |
| MOV CL,imm8 | three back to back every 17 clocks: 67 70 73, 84 87 90 |
| MOV DW,imm16 | runs of 2 to 5 |
| SHL AW,imm (3 bytes) | alternately 2 and 1 per instruction |
| CVTWL, ADJBA, SHL AW,CL, MULU CL (even) | one word per word consumed, at the instruction's end |
| SHL AW,CL, MULU CL (odd) | two back to back per two instructions, at the end of the instruction that consumes the word |

A burst is the bus unit filling every free slot at once. Slots free up
between bursts without being used, so a fetch starts only at a discrete
event. The slot-free rule of every earlier model cannot produce this.

**The request model reproduces the shape.** Settings: `fetch_request =
"opcode"`, `fetch_grant = "free"`, `fetch_request_delay = 2`, `lookahead = 1`.
The EU's opcode take sends a request; 2 clocks later the bus unit fetches
every free slot. A grid of 288 combinations scored on both probes' fetch
lists (word 58h to past the target, aligned on the 58h fetch) picked this:

| Rule | Release lists exact | Held lists exact |
| --- | --- | --- |
| iwr | 21 / 174 | 12 / 96 |
| opcode request, delay 0 | 43 / 174 | 22 / 96 |
| **opcode request, delay 2, lookahead 1** | **43 / 174** | **40 / 96** |
| a request that finds the bus busy is lost | no change | no change |
| two-word release, or depth 4 | lower | lower |

The 2-clock delay matters in itself. Shifting the EU phase instead does not
reproduce it: `post_start_delay` holds a posted write's bus cycle for N
clocks after the EU hands it over.

**Fitted, it does not yet beat iwr on whole windows:**

| Measure | iwr | request, delay 2 | request, delay 2, post_start_delay 3 |
| --- | --- | --- | --- |
| window length exact | 68% | 67% | 68% |
| cycles in place | **72%** | 7% | 38% |
| aligned cycles in place | **64%** | 56% | 59% |
| placement costs exact | 68% | 68% | 68% |
| odd-minus-even exact | **92%** | 83% | 83% |
| refill fetch exact | **68%** | 0% | 52% |
| release fetch lists exact | 12% | **24%** | **24%** |
| held fetch lists exact | 12% | **42%** | **42%** |

The request rule is the first to reproduce the bursts, and it nearly
quadruples the held-probe fetch lists. What it costs is outside the probes:
- the window head: the EU's phase against the OUT marker;
- the tail: silicon fetches one more word before `SHL AW,16`'s marker;
- odd-minus-even 83% against 92%, as the hide bits were fitted for iwr's
  release.

Next steps:
- fit the marker phase and the tail as part of the model, not leave them
  as residue;
- refit the hide bits under the request rule with more passes;
- look at the held cases the rule still misses (MOV CL,imm8 and the odd MULU
  trains).

The refill table is still the word-register model's main miss: 68% exact.
The refill behind a 1-byte target waits until near its end, and nothing in
either model produces that. Candidates for the next round:
- the word register holding two words (current plus next), with a slot
  freeing when the register advances past one;
- a fetch-start rule that depends on the EU's state.

A directed board probe would separate them. It would put 1-byte instructions
of different lengths after a saturated runway, at both parities, with the
next word's contents varied.

### Baseline steps and the tail probe, 2026-10-13

`fit_steps.py` used to skip every step that the baseline window spends
(MOV r16,imm16, MOV reg,reg, the shifts, OUT, the prelude's far jump). Some of
those steps were 2 to 6 clocks off as targets: MOV AW,imm16 cost 9 against
silicon's 6, SHL AW,1 16 against 10. The 16-NOP runway hid the error in the
window head, and the SHL AW,16 that ends every window hid it in the tail.

The `tail` suite (`probes.py`, corpus `p2-tail`, 30 cases) measures
SHL AW,n by immediate up to 31, SHL AW,CL up to 31, the count-1 form, and
OUT 0x40,AL once and twice (even placement):

| Form | Silicon cost | Model before |
| --- | --- | --- |
| SHL AW,n (C1) | 11 + 2n (9 for n = 0), linear to 31 | 3 more |
| SHL AW,CL | 12 + 2n (10 for n = 0) | 1 more |
| SHL AW,1 (D1) | 10 | 16 |
| OUT 0x40,AL | 10 | 9 |
| OUT 0x40,AL twice | 22 | 18 |

The shift step is now split by form (`shift_r_imm`, `shift_r_1`, `shift_r`).
The window's closing SHL AW,16 is 3 clocks cheaper than the model had it, and
those 3 clocks sit before the closing OUT's write: `out_imm` 9. With that, a
second OUT back to back costs 12, as on silicon. A single OUT costs 12 where
silicon has 10, so 2 clocks of a lone OUT overlap whatever precedes it. Those
4 runs are still open.

`fit_steps.py` now also fits baseline steps, as long as both baseline windows
stay exact. 14 values moved, `mov_rr` 3 to 1 and `br_far` 12 to 19 among them.

| Measure (iwr) | Before | After |
| --- | --- | --- |
| window length exact | 68% | 80% |
| cycles in place | 72% | 77% |
| placement costs exact | 68% | 81% |
| release probe cycles in place | 61% | 79% |
| held fetch lists exact | 12% | 18% |

The request rule on top of these costs, with iwr's hide bits and no refit:
release fetch lists 27%, held fetch lists 54%, but the window head is still
out of phase (7% cycles in place).

### Bursts are word-load timing, not a fetch rule, 2026-10-13

On the corrected costs, every request rule still loses the window
(cycles in place 7% to 46%, against iwr's 77%). On the NOP runway silicon
fetches exactly 2 clocks after the model's word load, which is iwr's rule;
a rule that fetches on the opcode take is 2 clocks late on every window.
Two more variants failed:
- a request only when an opcode take empties the word register, latched
  through its delay;
- the two-word register on the new costs (14% cycles in place at best).

Counted against the model's word loads, nearly every silicon fetch on the
held trains starts when 2 words are waiting, which is iwr's slot rule. The
bursts come from when silicon's EU loads words.
`python -m validation.v35s.load_times` prints the load clocks implied by
the fetches (fetch minus 2) next to the model's:

| Train | Silicon loads | Model loads |
| --- | --- | --- |
| NOP, XCH (even and odd) | every 8 | identical |
| ADD AW,CW (even) | every 3 | identical |
| INC AW, CLR1 CY | pairs 3 apart, every 10: 62 65, 72 75, 82 85 | every 5: 62 68 73 78 83 |
| MOV CL,imm8, even | triples 3 apart, every 17: 65 68 71, 82 85 88 | every 6 |
| MOV CL,imm8, odd | every 6, 2 clocks after the model | every 6 |

The train costs match silicon, so the EU's total time is right. What is
wrong is where its word loads fall: after 2-clock 1-byte instructions, and
in the even MOV CL train, silicon loads two or three words back to back and
then consumes them. Next: an EU load schedule that can load ahead, for
example a register that holds more than one word and refills when it
empties, fitted with `load_times` on the held trains.

### The V30's byte queue, 2026-10-13

nuV30's microcoded V30 (`build/deps/nuV30/hdl/rtl/ucore`) uses a
different queue:
- a 6-byte queue with no word register, popped one byte at a time;
- a byte becomes poppable a fixed delay after its fetch;
- the next opcode is popped on the last micro-row;
- whether the next bus cycle is a fetch is decided once per running cycle,
  at T3, and latched: fetch when 2 bytes are free;
- an idle bus unit re-evaluates every clock.

The `byte` profile models this with five parameters: queue_bytes,
ripe_delay, fetch_sample, idle_fetch_delay and opcode_pop.
For each bus configuration, a coordinate-descent search fitted the
baseline-window steps (NOP, OUT, MOV imm16, SHL imm, opcode pop) (queue 6 to 9 bytes, ripe delay 1 to 3, idle delay
0 to 2).

| Queue | Best baseline-window rows | What happens |
| --- | --- | --- |
| 8 bytes | 36 of 41 | Runway exact; the odd-placement tail misses |
| 7 bytes | 22 of 41 | Fixes the tail; breaks the runway |
| 6 or 9 bytes | lower | — |

The tail rules the byte queue out:
- In the odd baseline, SHL AW,16 takes its count byte, 6Bh, which is the
  second byte of word 6Ah. 6 bytes are then queued, so the byte rule fetches
  word 72h at clock 135.
- Silicon fetches it at 177, as the OUT opcode at 6Ch is taken. That is the
  first byte of the next word.
- In the even baseline, the count byte at 6Ch is the first byte of its word.
  Silicon fetches 72h at once, back to back with 70h.

A word slot frees when the EU takes the word's first byte. That is iwr's
rule, so the V35S queue is word-slotted.

The latched decision added nothing on iwr (`fetch_latch`):
- With no idle delay it scores the same as iwr.
- Any idle delay breaks the runway (35% to 38% cycles in place, against 77%).

The bursts still come down to EU load timing.

### The next-opcode pre-pop, 2026-10-13

The V30's EU pops the next opcode on its last micro-row while that row
runs. The held probe shows the V35S does the same. Its "phase INC xN"
cases put 0 to 3 INC AW in front of a 1-byte target:
- An INC at the first byte of a word (x1 even, x2 odd) turns the next
  fetch into a back-to-back pair (62h at 67, not 72).
- NOP and XCH never do this.
- With CVTWL or ADJBA at the first byte of word 5Ah, silicon fetches 60h
  about 3 clocks before the instruction ends (71 and 79), not at its
  opcode take (64).

The model now does this:
- A routine in `prepop` pops the next opcode `prepop_end` (2) clocks
  before its end. Those last clocks run during the pop and during any
  word load the pop needs.
- If the pop empties the word register, the next word loads at once,
  freeing its slot. That is what makes the pairs.
- Taking the first byte of a word loaded this way costs
  `preload_penalty` (1) clock.
- `fit_hide.py --prepop` chooses, for each routine, between the
  pre-pop, the end hide and neither. On the A6 odd-minus-even costs the
  pre-pop and the end hide tie for almost every routine, so the fit
  prefers the pre-pop on a tie.
- The pre-pop replaces all of the old `end_hide` set except POP ALL and
  the IN/OUT forms, whose last step is a bus cycle.
- INC r16 and the flag operations, which the old set partly covered, are
  pre-pop routines too.

Timing the pop from the routine's end matters. Counting it from the start
(one clock in) matched INC but not CVTWL.

Results (`compare_models`; iwr before, the default model after):

| Measure | Before | After |
| --- | --- | --- |
| A6 windows exact | 61 | 85 |
| A6 window length exact | 449 | 450 |
| A6 cycles in place | 77% | 78% |
| Placement costs exact | 447 | 446 |
| Release probe exact | 13 / 174 | 28 / 174 |
| Release fetch lists exact | 24 / 174 | 44 / 174 |
| Held fetch lists exact | 17 / 96 | 46 / 96 |

Step values refitted with it (`fit_steps.py`):
- most pre-pop routines gained a clock: INC r16 3, flag operations 3,
  CVTWL 10, ADJ4 11, ADJB 18 and others;
- PUSH ALL and POP ALL, which only the A6 CALL forms' stubs spend, are now
  41 and 42.

Rejected on the way:
- **A latched fetch decision with an idle bus that waits for an EU
  request at a word load** (`fetch_latch`, `fetch_request: "load"`):
  no gain.
- **Every routine pre-pops:** it breaks the transfers and I/O.
- **The consume model with pre-pops:** it gets CVTWL's late fetch but
  not the pair after it.

The `consume` profile has not been refitted since the baseline-step fit and
no longer runs the windows (10% cycles in place); it is kept only as a
record.

Still open:
- **MOV CL,imm8 at even placement:** silicon leaves the bus idle for 11
  clocks after the runway, then fetches three words back to back. A
  deeper queue does not explain it (see "EU timeline probe").
- **MOV DW,imm16 trains** keep part of their bursts.

### EU timeline probe, 2026-10-13

The `eu` suite (`probes.py`, corpus `p2-eu`, 56 cases, both placements)
puts an `OUT 40h,AL` after k instructions of a train, so its I/O cycle
marks the EU's position next to the fetches. Trains are NOP (k = 1-6),
INC AW (1-8), MOV CL,imm8 (1-6) and CVTWL (1-4). Four more trains of
one-word instructions check whether the even MOV CL triples are particular
to it.

The current model matches 1 of 56 fetch-and-OUT lists (`MOV CW,AW` x8,
even, which is bus-limited).

What it shows:
- **The triples belong to every one-word imm8 instruction.** `MOV AL,imm8`
  and `ADD AL,imm8` trains fetch exactly as `MOV CL,imm8` does: triples
  every 17 clocks at even placement, every 6 at odd.
- **The even MOV CL train runs 6, 6, 5 clocks** per instruction (OUT at
  81, 87, 93, 98, 104, 110 for k = 1 to 6), the triples' period.
- **INC AW runs 2.5 clocks on average in a two-word rhythm:** from k to
  k + 2 the OUT moves 5 clocks when it starts a word, and 6 and 4
  alternately when it does not. The model's INC costs 3 (fitted on single
  INCs), so its trains run 6 clocks long.
- **What follows changes the fetches before it runs.** MOV CL x1 and x2 at
  even placement run the same EU path up to the second word, yet x1 fetches
  62h at 74 and x2 at 70 (the triple). The second word is OUT's in x1 and
  the second MOV's in x2. Under the word-register rule, x2's triple needs
  the second and third words loaded at 68 and 71. That fits if reading
  MOV's immediate empties the register and the next word loads at once
  (the pre-pop's preload). It does not fit x1, where that load would fetch
  62h at 70.
- **After an OUT opcode whose port byte is in the same word,** the next
  fetch comes 5 clocks after the opcode (NOP x1 odd, MOV CL x1 even) with
  a slot free earlier, as if decoding OUT held the bus unit.
- **A mid-train OUT whose port byte needs a word load** starts its I/O 2
  clocks before the model's (NOP x1 even, NOP x2 odd, INC x1 even). A port
  read at the opcode + 7, with the load overlapping the routine's last
  clocks, matches these. It moves the closing marker (OUT after SHL AW,16)
  2 clocks early at odd placement, though, where silicon keeps the model's
  timing (window lengths exact falls from 450 to 233). The difference is
  in when OUT's opcode is taken after a short instruction, not in OUT
  itself.

Rejected, by `screen.py` over a6, release and held:

| Variant | Cycles in place | Window length exact | Held lists |
| --- | --- | --- | --- |
| model | 77.6% | 450 | 46 |
| 4 or 5 queue words, fetch once 2-4 slots are free, then fill | 4.8-40.9% | 278-448 | 0-10 |
| fetch decision latched in each cycle, idle bus waits 1-3 clocks | 5.7-38.8% | 172-339 | 11-46 |
| word register refills whenever it empties | 6.5-37.8% | 0-214 | 0-10 |
| NOP in the pre-pop set (nop 3, 4 or 5) | runway rate or phase wrong | | |

The runway fixes the queue at 3 words, the fetch in flight included. The
triples and pairs therefore come from when the EU empties its word
register, and that turns on the next instruction's kind.

### Follow probe, 2026-10-13

The `follow` suite (corpus `p2-follow`, 128 cases) puts each of 16
followers after a one-word leader (MOV CL,imm8; NOP NOP; INC INC; MOV
CW,AW), then OUT 40h. Clocks are from the opening marker; a silicon load
is the fetch 2 clocks later.

- **After a MOV CL leader at even placement, the second word loads at 68**
  (62h fetched at 70) for every follower except OUT and IN, where the
  fetch comes at 74. Whatever the second word holds, it loads at the same
  time; OUT and IN then hold the next fetch until about 5 clocks after
  their opcode. That accounts for the x1/x2 difference in the EU probe.
- **The leader's own word loads 3 clocks late when it is a MOV CL:** 60h is
  fetched at 67 after MOV CL, and at 64 after NOP NOP, INC INC and MOV
  CW,AW. At odd placement, MOV CL's immediate word (5Ah) loads at 65,
  against 63 in the model. Both fit an immediate read about 3 clocks after
  the opcode, with the word's slot held until then. That is the consume
  rule for the immediate; it is not iwr's slot release at the opcode.
- **The third word's load depends on the follower:** at 71 after another
  imm8 instruction or INC INC, 75 after MOV CW,AW or ADD AW,CW, 79 after
  NOP NOP, 83 after SHL AW,1 or MOV CL,[BW], and 92 after CVTWL CVTWL.
- **The current model matches 1 of the 128 lists** to clock 125. In the
  MOV CL-leader rows it misses mostly by loading the first word at 62
  instead of 65.

Taken with the EU probe, the MOV CL train looks like a front end that
reads instructions ahead of execution: three words 3 clocks apart, then a
wait until execution needs the next one. Execution takes 6, 6 and 5 clocks
per MOV, and the I/O of a following OUT keeps that pace. That would need
a decoded-instruction buffer between the word register and execution,
refilled in bursts. The NOP runway's steady one word per 8 clocks argues
against a plain refill-when-empty rule, so the refill condition is open.

Tried and rejected: a per-opcode prefetch hold from the opcode take (MOV
CL hold 2-5 clocks). It moves the odd case but cannot reach the even
case's first fetch, which the bus unit starts before the opcode is taken.

### Decoder read-ahead, 2026-10-13

Tried: when the EU waits for an opcode's word, the decoder keeps loading
words until `readahead_count` whole instructions past the one it waited
for are in the register (instruction lengths from a V30 length table).
Opcodes 90h-97h (NOP, XCH) do not read ahead, which keeps the runway at
one word per 8 clocks.

- With MOV r8,imm, INC, the flag ops, the shifts and the 2-byte register
  forms reading ahead 2 instructions, the even MOV CL train fetches in
  triples. It does so 3 clocks early (64, 67, 70 against 67, 70, 73) and
  with a 16-clock period against 17. The odd train stays steady, as on
  silicon, provided only an opcode wait starts a read-ahead.
- Unfitted, it scores below the model: 68.6% cycles in place, 234 lengths
  exact, 24 release and 32 held lists.
- A coordinate-descent fit of the read-ahead set and the step values over
  all five corpora (sum of per-transaction timing errors) turned the
  read-ahead off for nearly every opcode. The step changes it kept bought
  timing error at the cost of the closing marker (233 lengths exact), so
  that error measure is not usable as it stands.

The 3-clock offset is the follow probe's: the MOV word's slot frees when
its immediate is read, not when the word is loaded. A read-ahead model
therefore also needs a slot to free when the decoder has taken the word's
last byte. That puts operand reads in a decode stage ahead of execution,
a restructuring of the EU, not a parameter of it.

### Decode stage, 2026-10-13

The EU now has an optional decode stage (`decode_bytes` > 0 in costs.py,
off by default). It takes instruction bytes out of the word register
ahead of execution into a decoded-byte buffer, and the routines take their
bytes from that buffer. `model/length.py` gives it instruction lengths.

Variants:
- **fill:** refill when the buffer holds `decode_refill` bytes or fewer,
  up to `decode_bytes`.
- **ahead:** decode on demand. On an opcode wait for a word not yet
  loaded, also decode `decode_ahead` more whole instructions, unless the
  opcode is in `decode_skip`, at `decode_rate` bytes a clock.
- **slot release:** `slot_release` "taken" holds a register word's queue
  slot until its last byte is decoded; "load" frees it at the load.

With "ahead", 2 instructions, 2 bytes a clock and NOP/XCH skipped, the
even MOV CL train fetches its triples 3 clocks apart, as on silicon, and
the odd train stays steady.

Every variant was refitted before scoring. Fill variants had their
in-window baseline steps set so both baseline windows came out exact, then
`fit_steps.py`; ahead variants went through `fit_window.py` (new),
coordinate descent on whole-window exactness over all five corpora. Result:

| Model | Fit error | Cycles in place | Lengths exact | Release / held / eu / follow lists |
| --- | --- | --- | --- | --- |
| current model | 7344 | 77.6% | 450 | 44 / 46 / 3 / 5 |
| current model, `fit_window` refit | 6846 | 78.8% | 460 | 46 / 46 / 3 / 3 |
| fill, 4 or 6 bytes from empty | | 5.1% | 211-262 | 0 / 0 / 0 / 0 |
| fill, 1 byte | | 8.6% (48.9% refitted) | 189-287 | |
| ahead, slot freed at load, skip set fitted | 13912 | 50.9% | 333 | 33 / 33 / 3 / 3 |
| ahead, slot freed when taken | 22653 | | | |

- **Fill from empty** bursts the NOP runway, three words at a time.
- **Every decode-ahead variant** stores more than silicon does. The queue
  runs a word ahead at the opening marker, and the runway phase moves.
- **Given the choice, the fitter switches the decode stage off.** It
  returns to the current model's error.
- **With decode-ahead held on,** it puts MOV CL itself in the skip set.

So the read-ahead that the MOV CL trains show is not a decode stage that
holds extra bytes.

**Shared store (tried next).** The register's word and the decoded bytes'
words count against `queue_words` (`shared_store` 1), so reading ahead
cannot deepen storage. Refitted with `fit_window.py --skip-set`, 3 passes:

| Shared slots | Fit error | Cycles in place | Lengths exact | Release / held lists |
| --- | --- | --- | --- | --- |
| 3 | 23428 | 13.7% | 17 | 0 / 0 |
| 4 | 14897 | 48.9% | 314 | 10 / 10 |

With 4 slots the NOP runway is exact. But the MOV CL train no longer
bursts, even with MOV CL decoding ahead (it is not in the fitted skip
set): a word decoded ahead keeps its slot until execution takes it, so
reading ahead frees nothing and the bus has no reason to fetch three
words at once.

That closes the decode-stage question both ways. Freeing a slot when a
word is decoded makes storage deeper, which silicon does not show. Holding
the slot until execution makes no bursts, which silicon does show. The
triples need slots that free in a burst without the freed words being
held anywhere further down the pipeline. Two possibilities remain:
- the words go into a structure that holds whole decoded instructions,
  not bytes, and the probes so far have not seen its depth;
- the fetch timing is not slot-driven in these trains at all, for example
  a bus-unit request that the EU sends at certain decode events.

### EU fetch requests on the current model, 2026-10-13

The request model's existing rules, on top of the word-register model
with the pre-pop and scored on all five corpora (60 combinations): the
trigger is a byte take, an opcode take, an opcode ask, a word load or a
word end; the grant is every free slot, one fetch, or until full; the
delay is 0-3 clocks.

- **On the 3-word queue** no rule beats the slot rule. The best ties it
  (77.6% cycles in place, 450 lengths, 44 / 46 / 3 / 5 lists): a request
  at each word load, or at each take with until-full grants, is the slot
  rule. A 2-clock delay costs held lists (30). A 3-word queue cannot make
  a triple, since only one word has been loaded when it would start.
- **On a 4- or 5-word queue** that fetches only on requests, the best is
  15.7% unrefitted. After `fit_window.py`, 3 passes:

| Queue, request, grant, delay | Fit error | Cycles in place | Lengths exact | Release / held / eu / follow |
| --- | --- | --- | --- | --- |
| current model | 7344 | 77.6% | 450 | 44 / 46 / 3 / 5 |
| 4 words, word end, free slots, 2 | 11248 | 61.3% | 361 | 10 / 10 / 2 / 2 |
| 4 words, opcode, free slots, 2 | 22741 | 9.0% | 398 | 9 / 10 / 2 / 2 |

  The word-end variant keeps the NOP runway exact. It turns the MOV CL and
  INC trains into long back-to-back runs, though, not triples and pairs:
  with a deeper queue each request grants every slot the EU has freed
  since the last one.

A request rule alone does not produce the bursts. On the 3-word queue
the slots are not free; on a deeper one, too many are.

### Classed read-ahead, 2026-10-14

The stall probe (corpus `p2-stall`) shows that after an EU stall the
fetch restarts in triples, and that the decoder reads ahead past a memory
operand or MULU but then stops. It never reads IN or OUT ahead; those hold
the fetch. `decode_mode = "classed"` models this. Words go from the queue
straight into a decoded store, which frees each slot at the take. An opcode
wait for a `decode_simple` instruction starts a burst, which takes words
until `decode_cap` bytes are held past the executing instruction. A
non-simple take or a `decode_io` instruction ends it. With `decode_simple`
empty it reproduces the current model exactly.

Unfitted, it gets the shapes right: the MOV CL triples, the INC and CLR1
pairs, and SHL CL at the even placement. It does not reproduce the
odd-placement SHL CL and MULU CL pairs. Refitted by `fit_window.py`,
toggling each opcode's set membership jointly with ±1/±2 on its steps:

| Variant | Fit error | Cycles in place | Lengths exact | Release / held / eu / follow / stall |
| --- | --- | --- | --- | --- |
| current model | — | 77.6% | 450 | 44 / 46 / 3 / 5 / 2 |
| current model, refitted | 6846 | 78.8% | 460 | 46 / 46 / 3 / 3 / 2 |
| classed, unfitted | — | 75.4% | 423 | 28 / 45 / 3 / 7 / 2 |
| classed, `decode_simple` fitted | 6838 | 76.2% | 427 | 28 / 45 / 3 / 3 / 2 |
| classed, `decode_simple` + `prepop` fitted (2 passes) | 6815 | 77.4% | 442 | 42 / 46 / 3 / 3 / 2 |

It does not beat the refitted current model, so it stays an option. Two
caveats:
- **The fit error misleads.** It counts mismatched transactions, so the
  classed fits score a lower error while fewer windows are exact.
- **The fit undoes the evidence.** The `decode_simple`-only fit drops MOV
  CL (0xB1) from the set, though its triples are the clearest burst in the
  data. The fit with `prepop` restores it.

The bursts are real and this structure produces them, but its timing
elsewhere costs more than the trains gain.

### Operand hold, 2026-10-15

At odd placement `SHL AW,CL` fetches word 60h at 74 + 2n for a count of
n: the fetch tracks the instruction's end, not its ModR/M read near 63.
So the ModR/M's word keeps its queue slot until its last byte (the next
opcode) is taken. `operand_hold` makes a word loaded into the register
for a non-opcode byte hold its slot until that last byte is taken:
- **1:** any non-opcode byte. This delays the marker OUT's port byte
  past its I/O cycle and shifts every window.
- **"modrm":** ModR/M bytes only. Memory forms then end 1 clock early
  (odd) or 2 early (even 0F bit ops): silicon reads ahead past a memory
  form.
- **"modrm_r":** register-form ModR/M bytes only (mod = 3).

`preload_alternate` skips a pre-pop's pre-load when the register's last
load was itself a pre-load. With it, odd `train SHL AW,CL x6` fetches in
pairs after SHL 1, 3 and 5 as silicon does (83/86, 122/125, 161/164 against
80/83, 117/120, 154/157; the residual is the step value). It does not move
the corpus scores. Unrefitted:

| Variant | Cycles in place | Lengths exact | Release / held / eu / follow / stall |
| --- | --- | --- | --- | --- |
| current model | 77.6% | 450 | 44 / 46 / 3 / 5 / 2 |
| + `modrm` hold | 73.9% | 385 | 46 / 53 / 3 / 6 / 2 |
| + `modrm_r` hold, alternation | 79.1% | 450 | 46 / 53 / 3 / 6 / 2 |
| refitted current model | 78.8% | 460 | 46 / 46 / 3 / 3 / 2 |
| refitted values + `modrm_r` hold | 80.3% | 460 | 48 / 53 / 3 / 3 / 2 |

The `MULU CL` train at odd placement still fetches singly (silicon: pairs
at 87/90, 139/142, 191/194).

### Two waits, register forms and the release table, 2026-10-15

**At 2 waits** (corpora `p2-held-w2`, `p2-eu-w2`, `p2-follow-w2`, WTC AAAAh)
every train fetches in bursts, including those that are steady at 0
waits:

| Train (even) | 0 waits | 2 waits |
| --- | --- | --- |
| NOP, XCH AW,CW | one every 8 clocks | pairs 5 apart, every 18 |
| INC AW, CLR1 CY | pairs 3 apart, every 10 | pairs 5 apart, every 14 |
| MOV CL,imm8 | triples 3 apart, every 17 | triples 5 apart, every 23 |

A burst is a general bus-unit behaviour that slower fetches expose. In
the eu probe the OUT after k MOV CL slips about 2 clocks per instruction
against 0 waits, so the EU does wait on read-ahead words. The model has
not been fitted at 2 waits; it scores about 4% cycles in place there.

**Register forms** (corpus `p2-regform`, `--suite regform`): 68 register
ModR/M forms then four NOPs, both placements. At odd placement word 60h
is fetched at 64 for the ALU r,r, MOV and XCH forms; 66 for TEST and the
0F bit ops; 67 for NOT/NEG, INC/DEC and the r,imm forms; 71 for shifts by
1; 73 POP, 77 PUSH, 80 shifts by CL; 87 to 122 for MULU, MUL, DIVU and
DIV. That measures the pre-pop and end of each form directly.

**Release table.** A fetch that starts after an idle bus clock dates the
release of the word three slots back. Silicon against the model, with the
`modrm_r` hold, by what the released word held:
- **ModR/M (register) + next opcode:** silicon releases about 4 clocks
  earlier (60 cases in a6, 38 in regform). The hold is right in kind but
  ends too late.
- **Opcode + immediate:** silicon about 5 clocks later. Almost all of it
  is one word, the closing marker `OUT 20h,AL` after the `SHL AW,16`
  tail. A trial that held opcode + immediate words (all, or IN/OUT only)
  until the immediate was taken broke the opening marker, whose word
  silicon frees 14 clocks before its I/O cycle: cycles in place fell to
  about 41%. Dropped.
- **Opcode pairs and immediate + opcode:** 73 to 85% exact in the queue
  probes, 1 to 2 clocks early in eu, follow and stall.

A model run takes 3.9 ms (about 500 clocks), so a fetch-only simulator
would gain 2 to 3 times at most; scoring a variant on every corpus takes
about 5 seconds. Fitting is slow because of its trial count.

### One wait, and fetch rules scored at 0, 1 and 2 waits, 2026-10-15

**At 1 wait** (corpora `p2-held-w1`, `p2-eu-w1`, `p2-follow-w1`, WTC
5555h) the NOP lead-in of the eu trains fetches in pairs 4 apart every 16
clocks. At 0 waits it fetches one word every 8, at 2 waits pairs 5 apart
every 18. The EU's rate is the same at 0 and 1 wait, so the pairing is a
bus-unit rule that a longer fetch cycle exposes, not a slower EU. Only 2
waits also costs the EU about a clock per word.

**Model options added, all off by default:**
- `fetch_dry_words`: the EU's fetch request counts only when the queue
  holds that many words or fewer.
- `fetch_grant` as an integer: a request grants that many fetches.
- `load_block` (`cycle`, `waits`, `wait1`): no word load into the
  instruction word register while a fetch with wait states runs, or during
  its wait states, or its first one.

**Sweep** (fetch lists from 58h, aligned on the first fetch; lists exact
out of 674 / 284 / 284 runs, and the share of consecutive fetch gaps that
match):

| Rule | Exact w0 / w1 / w2 | Gaps w0 / w1 / w2 |
| --- | --- | --- |
| current (fetch whenever a slot is free), `modrm_r` hold | 149 / 0 / 0 | 70 / 12 / 11% |
| request at word end, grant 2, dry 2, `load_block` waits | 0 / – / 30 | 10 / – / 65% |
| request on opcode, grant free, delay 3, `modrm_r` hold | 104 / 24 / 0 | 61 / 60 / 40% |
| same, `load_block` wait1 | 104 / 24 / 0 | 61 / 60 / 40% |

The word-end rule with `load_block` gets the 2-wait NOP rhythm right
(pairs every 18) but pairs at 0 waits too. The opcode request with a
3-clock delay is the first rule that is fair at every wait setting; it
loses 45 exact lists at 0 waits to the current rule. No rule tried fits
all three.

### Fetches forced to silicon's times, 2026-10-15

`python -m validation.v35s.forced_fetch` runs the model with every code
fetch and refresh started when silicon started it, re-anchored at each
data cycle, so the EU is measured on its own. Marker-to-marker time
against silicon:

| | 0 waits (1230 runs) | 1 wait (284) | 2 waits (284) |
| --- | --- | --- | --- |
| current model: exact / mean error | 705 / +0.06 | 65 / −0.31 | 0 / −24.8 |
| + `load_wait_extra` 1 | 705 / +0.06 | 65 / −0.31 | 30 / −2.2 |

- **The EU costs carry fetch error.** Fed silicon's real fetches, the
  model's EU gets the window time right in 57% of runs at 0 waits. The
  free-running model reaches 78–80% cycles in place because its step
  values were fitted against its own (wrong) fetch timing. EU and bus unit
  should be fitted apart: the EU under forced fetches, then the bus rule
  with the EU fixed.
- **2 waits costs the EU a clock per word, 1 wait does not.** Every 2-wait
  window was about 13 clocks short per 16 NOPs, whatever the instruction
  under test; a later data arrival (`fetch_data_delay` up to 6) changes
  nothing, so the EU is not starved. `load_wait_extra` 1 adds a clock to
  each word load per code wait state over `load_wait_free` (1). With it,
  the latched rule (`fetch_latch`, sample 0, idle delay 5) scores 133 / 15
  / 15 exact fetch lists at 0 / 1 / 2 waits, and the opcode request with
  delay 3 scores 104 / 22 / 13. These are the first rules to score at all
  three settings.
- **Where silicon starts a fetch** (`--table`, model state at each free
  bus clock). At 0 waits silicon starts almost every fetch when the model
  holds two queued words besides the word register: the third slot, as
  modelled. At 1 and 2 waits about 40% start when the model's queue is
  already full. A queue one word deeper when code has wait states
  (`queue_words_waited`) only runs further ahead; it does not make pairs.
  An idle bus restarts 6 clocks after its last cycle at 0 waits and 8 to 9
  at 1 and 2.

Other options added, off by default: `fetch_request` "demand" (on a
demand load only; same as "load" in every train) and "opcode_end" (on
taking an opcode that ends its word; gives the even `MOV AL,imm8` triples
but loses the 1-wait pairs), and `empty_grant` "free".

### Branches

- **Prefetch suspend (implemented, nuV30's SUSP):** a decided transfer stops
  prefetching until its flush.
- **Short branches:** silicon reaches the refill about 3 clocks later than
  the model. The time from the jump's opcode to its refill matches.
- **After a refill:** the first instruction at the target starts about 8
  clocks after the target fetch. Both are pending the queue-model decision,
  since both turn on when the jump's word is released.

## Data cycles

`python -m validation.v35s.data_check` compares each window's non-fetch
bus cycles with silicon's, timing aside: kind, address, data, byte enables
and order. Since 2026-10-13 every run of a6-timing, release, held, eu,
follow and stall matches. Three fixes got it there:
- **ADD4S, SUB4S, CMP4S:** read the source byte (IX) before the
  destination (IY).
- **CMPBK:** reads IY before IX.
- **Trap entry:** reads the vector offset, pushes PSW, reads the vector
  segment, then pushes PS and PC. CHKIND's trap pushes the next
  instruction's address, not its own.

## Bus-unit rules (stable under both queue models)

- **I/O recovery:** after an I/O cycle the bus stays idle one clock.
- **Posted writes:** the EU hands a write to the bus unit and goes on.
- **Odd targets:** after a flush the first fetch is a byte fetch at an odd
  target.
- **Refill:** back to back, 3 clocks apart at 0 waits.

## Status

On `a6-timing`, 558 runs, 2026-10-13: word-register model with the
next-opcode pre-pop, fitted hide and pre-pop sets, step values refitted by
`fit_steps.py` with baseline steps included:

| Measure | Result |
| --- | --- |
| Exact windows | 85 |
| Window length exact | 450 runs (81%) |
| Cycles matching in place | 78% |
| Placement costs exact | 446 of 552 (81%) |
| Held / release fetch lists exact | 46 of 96 / 44 of 174 |

Window misses concentrate in:
- flow forms (branch and refill timing);
- the ±1 placement residue;
- traps.

Next steps:
- the one-word imm8 triples and the INC two-word rhythm, against `p2-eu`
  (see "EU timeline probe"); the next word appears to load early when it
  holds another simple instruction;
- OUT's opcode take after a short instruction;
- the remaining held and release fetch-list misses;
- branch and refill timing.
