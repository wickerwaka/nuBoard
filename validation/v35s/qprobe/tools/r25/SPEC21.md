# V35S core v2: RTL work order 21 (from qprobe round 25, results Q118 to Q126)

Against land17 (corpus 29,167 of 30,536 exact; miss list `land17/miss-v35_chk.jsonl`, 1,369 rows). The
reading model (`validation/v35s/qprobe/model_m.py` in `qprobe-pkg.tgz`) is now exact on 27,467 corpus
runs and on **1,245 of the 1,369 miss rows** (1,006 after round 24). `traces/logs/rtl-miss-model-exact.json`
names for each of the 1,245 the rules that carry it (round 24's tags kept; an empty list: exact
without any rule of rounds 24 / 25). This order adds 239 rows to work order 20; nothing of order 20
is changed. Notation as there; "pair" = the two byte cycles of a word at an odd address.

**Common gate.** No corpus run land17 has exact may be lost (the model loses none; no rule moves an
RTL-exact run). Program gates and the FPGA gate at 17 ns as always. No port of the interface budget
is needed: every item is a routine shape or a condition on levels the bus unit, the loader and the
sequencer already exchange. Whether the RTL already has part of an item is not known to this order
(no sim was run): where the RTL is exact on the W = 1 / 2 rows of a family, the function is there
and only the W = 0 clause is new. Batch: B1 + B2 + B3 together (one family set), B4 + B5 together,
B6 + B7 together.

## B1. A word string element at an odd pointer is a pair, by the element's own pointer (Q118; with B3: 88 rows)

- **Mechanism.** (1) The request word of a string routine names its pointer: IX for MOVBK's read,
  LDM, OUTM's read and CMPBK's **second** read; IY for MOVBK's write, STM, CMPM, INM's write and
  CMPBK's **first** read. (2) A word request at an odd address is two byte cycles back to back,
  as for [BW] and the stack. (3) A datum wait ends with the pair's last pin clock.
- **Measured:** corpus addresses (F30 `odd-*`), `QPr25a` 144 runs; the model gains 302 RTL-exact
  corpus runs by it (the RTL has (2) at W = 1 / 2 and for IX). **Gate:** F24 `out-a-*`, F30 `out-odd-*`
  every W; `QPr25a` string programs.

## B2. The decode lead of the opcode a store releases counts from the first clock of the write's last byte cycle (Q119, Q125; 16 + 8 rows)

- **Mechanism.** (1) A store-type tail releases the next opcode on the write's first clock (`G N .`,
  Q115). (2) **New:** when the write is a pair, or starts later than the release (the datum word's
  release with the write behind a fetch, B7), the lead counter of that opcode (OUT imm8: 3) starts
  on the first clock of the write's last byte cycle. (3) The boundary is on the later of the
  write's last clock and that count.
- **Measured:** pair at W = 0, follower OUT imm8: boundary one clock after the pair's last clock
  (`QPr25a` 20 runs, 10 store-type instructions; 42 control runs with seven followers without a lead:
  on the pair's last clock; corpus 16 rows F5 `out-*-odd`). Write behind a fetch: 8 corpus rows, 6
  socket runs. At W = 1 / 2 nothing changes. **Inferred:** one counter origin for both. **Unknown:**
  OUT imm8,AW / IN imm8 behind a pair (same lead: expected the same); whether silicon releases the
  opcode itself on that clock (the queue count would differ by one for three clocks: no run shows it).
- **Gate:** F5 `out-*-odd` at W = 0; `QPr25a` `so-*`, `rmw-*`, `sti-*`, `sp-push*`, `stm-iy-*`; F5 `push-*-odd` unchanged.

## B3. The wait behind the last string element's pair is one clock longer at W = 0 (Q120; with B1: 88 rows). **Measured; no mechanism: needs a ruling before it is built**

- **What is measured.** At W = 0 the routine goes on one clock later than the pair's last pin
  clock + 1 behind: the write of MOVBK / INM single; the second read of CMPBK single; the last
  iteration's write of REP MOVBK / STM / INM; the read-ahead pair's second read of REP CMPBK. Not
  behind a first read (MOVBK's, CMPBK's first, LDM, CMPM), not behind the writes of the earlier
  iterations, not at W = 1 / 2. 26 socket runs, 88 corpus rows; controls 72 runs + the iteration
  spacing.
- **Stages, as far as they can be stated:** the last element's wait is a different wait from the
  loop's (the model's `J` against `D`): it ends with a level that follows the pair's end by one clock
  when the cycles have no wait state. Which level is **unknown**. Candidates not excluded: the wait
  is on the bus unit's "no request left" level rather than on the cycle's end; rejected: the bus
  itself busy one clock longer (a fetch does start on the clock after the pair), every wait one
  clock longer (the loop's spacing).
- **Options for the ruling:** (a) build it as measured (a second wait kind, +1 behind a pair at
  W = 0) and record it as a described difference; (b) leave the 88 rows as a known difference
  until a probe finds the level. A probe that could: the same last element with a fetch pending
  under the pair (queue not full: the string instruction directly behind a flush), which shows
  whether the bus unit's own next cycle moves with the wait.

## B4. The single string forms have a bus-idle word (Q121; 25 rows)

- MOVBK, CMPBK, CMPM: the fourth word; INM: the fifth; STM, LDM: the third (as built / as in the
  model before). The REP heads have the same word in the same place.
- **Measured:** corpus 25 (F39 `push-ctl-{movbk,cmpbk,inm}-s`, `push-str-*`, pE, W = 1 / 2); `QPr25c` 252 of 252
  (45 need it, 10 of them CMPM's). **Unknown:** bus-idle on that word or a boundary-type wait one
  word earlier (identical on all runs): build it as the REP head's.

## B5. ADD4S / SUB4S / CMP4S: a 12-word head with bus-idle third and seventh words; ADJ4S nine words (Q122; 33 + 6 rows)

- **Head:** `P . B . . . B . . . . .`, then the iterations and tails as built. The 13-word head was
  12 words + a stall under MOV CL,imm8's refill fetch. **Measured:** corpus 33 (F32 `*4s-*-k2`, `pfx_add4s`,
  F40 `page-add4s-k*`), `QPr25d` 90 of 90. The seventh word's bus-idle act: **inferred from 2 runs**
  (behind OUT, pE, W = 2).
- **ADJ4S (2F):** `. . B . . . . N .` (ADJ4A stays ten words). **Measured:** `QPr25d` 66 runs, no data
  dependence over four AL / flag settings; corpus 6 (F33 `out-adj4s-k2`).

## B6. A write requested inside the chain does not stop it (Q123; 48 rows)

- **Mechanism.** (1) Behind an EU cycle the pending fetch starts, and fetches follow back to back
  while five or fewer bytes are held at each fetch's end. (2) **New:** a write whose request word executed at or
  after the chain's first pin clock does not stop the chain's next fetch if five or fewer are held
  (counted before that clock's pops); the write starts when the chain ends. This is the rule
  read for reads in round 21 (Q95: "no arbitration inside the chain"), now for writes. A request
  word in front of the chain's first pin clock, and a fetch started from the idle bus: the write
  goes first (unchanged). (3) The store's `G` word (and so the release of the next opcode)
  waits with the write.
- **Measured:** `QPr25b` 36 runs fetch first against 76 write first, split exactly by (2); earlier
  socket rounds +44; corpus 48 rows (F21 `st-bw_d16`, `st-dir`, `st-bw_ix_d16` behind OUT / NOP / PUSH, F29
  `ec-dio-st*`), every W. **Inferred:** the bus unit takes an EU request into its order only between
  chains. "The chain's second fetch or later" in place of the request clock gives the same clocks
  on every run: either may be built; the request clock is the one the read rule already uses.
- **Gate:** F21 / F29 rows above; `QPr25b` whole (1,026); the stores with an immediate behind PUSH at
  W = 1 / 2 (the frame that round 24's wider version lost) unchanged.
- Also: MOV [d16],AW (A3) has its request word second (`. Y . PP2 G N .`, Q124): 19 `QPr25b` runs, no
  corpus row; check the RTL's unobstructed latency (write two clocks behind the displacement's pop).

## B7. A request armed on the clock it is due does not stop a fetch from the idle bus (Q125; 23 rows, 8 of them with B2)

- **Mechanism.** Q33's rule (built for the back-to-back fetch): a write whose datum word has not
  executed does not hold the bus. **New clause:** when the datum word (or, for a read-modify-write
  with an immediate, the word that releases the displacement) executes on the very clock the cycle
  is due, a fetch that can start from the idle bus (four or fewer held before that clock's pops)
  starts, and the EU cycle follows it.
- **Measured:** corpus 23 rows (MOV / ADD / CMP [d16 forms],imm behind OUT at even alignment, W = 0),
  7 socket runs; 0 lost. With the marker directly behind, B2's clause gives the last clock.

## C. Rows the model reads exactly without any rule of rounds 24 / 25

297, unchanged from work order 20 (C): build faults against rules already specified.
