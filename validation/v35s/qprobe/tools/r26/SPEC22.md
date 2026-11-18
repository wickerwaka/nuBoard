# V35S core v2: RTL work order 22 (from qprobe round 26, results Q127 to Q134)

Against land21 (04c3a30: corpus 30,181 of 30,536 exact; miss list `land21/miss-v35_chk.jsonl`, 355 rows). The
reading model (`validation/v35s/qprobe/model_m.py` in `qprobe-pkg.tgz`) is exact on 27,491 corpus runs and on 240 of
the 355 miss rows; `traces/logs/rtl-miss-model-exact.json` names for each the rule that carries it (`J`, `LEAD`,
`ARB_IDLE`; an empty list: no rule of rounds 24 to 26). Notation as work order 21; s2 = the first clock of a
pair's second byte cycle; "last" = a cycle's or pair's last pin clock.

**Common gate.** No corpus run land21 has exact may be lost (the model loses none). Program gates and the FPGA
gate at 17 ns as always. **Two items need one new bus-unit-to-sequencer level and are marked so: that is the
user's ruling, not assumed here.** No RTL was built or simulated for this order except the main tree's
existing build on the new socket families (for the miss lists below).

## C1. The store's N word executes on the first clock of the write's last byte cycle (Q127; replaces work order 21's B2; 16 + 8 rows) **needs a ruling**

- **Mechanism (measured by INT stepped across the store, 5 forms x even / odd pointer, both alignments).** (1) A
  store-type tail `G N .` releases the next opcode on the first clock of the write. (2) When the write is a
  pair, the release is on the first clock of the **second** byte cycle (pop 96 for a pair on 93 / 96; STM
  single and ADD [BW],AW the same). (3) When the write starts behind a fetch (MOV [d16],imm16 behind OUT imm8 at
  even alignment, Q125: datum word 99, write 102) the release is on the write's first clock (102), not on the
  datum word. (4) Nothing else is special: the decode lead counts from the release (OUT imm8 behind the store:
  boundary on release + 3), the boundary is on the later of the write's last clock and the lead.
- **What it changes.** F5 `out-*-odd` (16 rows, W = 0) and the 8 rows of B7 with the marker behind: exact by this
  alone; no lead-counter change. **Functionally visible:** for the three edges in front of the second byte cycle
  an interrupt replaces the instruction behind the store in silicon (`QPr26e` `st-o`, `sto-o`: edges 84 to 86).
- **Signal.** The N word must wait for a level the bus unit has: "the last byte cycle of the EU's write starts
  on this clock". For a single cycle the existing grant of the `G N` tail is that level. For a pair it is the
  second half's first clock, which work order 21 found no existing level carries (the wait is formed before
  the request's address is in the bus unit). **One bus-to-sequencer bit (`p2`: the second byte cycle of an EU
  pair starts on this clock, read or write) is needed: ruling.** It is the bit B2 asked for, now going to the
  sequencer's stall of the N word instead of the loader's lead counter. For (3) no new signal: the datum
  word's release moves onto a word that waits for the write's grant as `G N` does (MOV [m],imm: `K PP2` then
  the release with the write).
- **Gate:** F5 `out-*-odd`, the 8 B7 rows; `QPr25a` `so-*`, `rmw-*`, `sti-*`, `sp-push*`, `stm-iy-*`; `QPr26g` `i-s8`, `iii-s8`,
  `ji-s8` (6 runs); once the interrupt path is lined up: `QPr26e` / `QPr26j` `st-*`, `sto-*`, `sm-*`, `rmw-*`, `wl` (the
  instruction pushed per edge: `tools/r26/e26.py` prints silicon's).

## C2. The second kind of wait word (`J`): four clocks from the pair's second cycle (Q128; work order 21's B3; 88 rows) **measured, no mechanism; needs a ruling**

- **What is measured.** A `J` word executes on the later of last + 1 and s2 + 4 (so one clock later than a `D`
  word behind a pair with no wait state, and never otherwise). The words: the wait behind the write of MOVBK /
  INM single; behind the second read of CMPBK single; the last element's wait of REP MOVBK / STM / INM (any
  count, CW = 1 included); the read-ahead pair's second read of REP CMPBK; **CALL near's wait behind its push
  (C3)**. Every other wait is `D`: first reads, LDM, CMPM, OUTM's read (single and REP, last element included),
  the earlier iterations of every REP, PUSHA, CALL far / CALL r16 / CALL [m] / INT 3 / BRK, RET / RETF / RET imm16.
  STM single has no wait word (store tail, C1).
- **What is known of the mechanism.** It is a property of the routine's word, not a state of the bus unit: REP
  STM's last element and CALL far's second push stand in the same bus state (pair, 7 clocks, pair, queue full,
  no fetch) and differ. **Inferred:** the ROM has two wait kinds; `J` asks the bus unit for something released
  four clocks into a pair's second cycle. Which: **unknown** (the address path is the candidate: CALL near is
  the one transfer that adds PC + displacement behind its push).
- **Signal.** A word kind for the `J` words (whether a free `wk_t` code exists is the builder's to say) and the
  timing level. With C1's `p2` the sequencer can form it (no completion of a `J` word before `p2` + 4);
  without `p2` it needs its own bit ("the pair's second cycle ended without a wait state"). **Ruling: (a) build
  with `p2` shared with C1; (b) leave the 88 rows as a described difference.** The rows: F24 `out-a-*`, F30
  `out-odd-*`, W = 0.
- **Gate:** the 88 rows; `QPr25a` string programs; `QPr26a` (1,344: 96 need it, 128 + 224 at W = 0 must not get
  it), `QPr26b` (120), `QPr26c` (306: 30 need it, 30 must not), `QPr26d`, `QPr26m`.

## C3. CALL near (E8): `. . . . PP2 . Y J . . F N .` (Q129)

- With SP odd and W = 0 the target's fetch is one clock later than with any other call form (22 socket runs:
  `QPr26d` `call-*-o`, `cr-o`; `QPr26m` `jcall` / `rcall` / `pcall` / `ncall` `-*-o`). No corpus row. Built with C2 or not at
  all. Control: `QPr26m` `callr` / `callm` / `int3` / `brk` / `retf` / `reti` / `ncallf`, `QPr26d` `callf` / `pusha` / `pp` / `pushi` / `pushf` /
  `pushm` / `popm` (must stay on `D`), `QPr26n` (156: relative transfers behind a store's pair, no wait).

## C4. MOV [d16],AL / AW (A2 / A3): the request word second, `. Y . PP2 G N .` (Q124, Q131): build it again

- **Measured on the pins:** 119 runs where no fetch starts on the displacement's pop have the write on pop + 2
  (`QPr25b` 19; `QPr26g` 24; `QPr26k` 76, 38 A2 and 38 A3 in the same programs). The main tree's build misses
  exactly `QPr26g`'s 24 and `QPr26k`'s 76. No corpus row moves (model: 0 gained, 0 lost with either shape).
- **f4_dma.** The difference at write 711 is DIC0's interrupt push (07EFEh) against the next store (0C1DAh): a
  pop one clock earlier against the scan's lattice. A DMA transfer is taken at an instruction boundary
  (`QPr26h*`: its write 11 clocks behind the boundary in 444 runs, six trains) and never arbitrates against
  the store's request. **Inferred:** with the lattice 3 clocks late (C6) the old shape's extra clock hid the
  difference; f4_dma at write 711 is C6's gate. If C6 is not built in the same batch, expect f4_dma to differ
  with C4 alone and judge C4 by its socket runs.
- **Gate:** `QPr25b` (1,026), `QPr26g` (324), `QPr26k` (480); 89 06 / 88 06 unchanged (`P Y . PP2 G N .`).

## C5. `CH_EPRI` behind a store with an immediate and a four-clock instruction (Q130): a build fault; INT 3 keeps no lead

- **State.** MOV [d16],imm16 writes on t; the fetch behind the write runs t + 3 to t + 5; the next instruction
  is NOP (four words, its boundary due on t + 6) with four bytes held: the boundary executes on t + 6 and the
  chained fetch starts on t + 7 (round 13's `CH_EPRI`). The RTL starts the fetch on t + 6.
- **Rows:** `QPr8-ld-int3-n-pE-w0` (the run lost when INT 3's lead went) and `QPr26l` `v-n-{int3,nop,inc,clc,rr,push,ld,ri}-pE-w0`
  (8). Predecessors of 2 and 3 clocks and odd alignment are exact in the RTL (208 of 216).
- **INT 3:** no lead. `QPr26f` 192 of 192 in the RTL as it is, 89 of the 90 earlier runs.
- No new signal (the rule is in the RTL for other states).

## C6. EI restarts the scan on its first word: the request stands at the EU on E1 + 24 (Q132)

- **Measured.** With INTP0 (level 7) pending and EI in the body, the lattice clock c on which the request
  stands at the EU is 24 clocks behind the clock EI's first word executes (and E1 + 8 mod 16 for requests that
  arrive later), whether or not EI's bus-idle third word or its boundary waits (92 opcode-train runs: E1 + 24
  reproduces 87; the third word + 22: 83; the boundary + 12: 72). Behind c the stages are work order 19's.
- **For the RTL:** a lattice 3 clocks late is a restart three words into EI. **Unknown:** first word or second
  (one clock of resolution); two cells (E1 = 80 at even alignment, 83 at odd) take the request 20 clocks
  earlier, at the first replaceable pop behind EI: not explained, not to be built.
- No new signal expected (the restart is the sequencer's word to the interrupt controller, as now).
- **Gate:** `QPr26i` (184: the instruction pushed and the vector read's clock; `tools/r26/i26.py`), the INTP0
  families of rounds 17 / 19 / 23, f4_dma at write 711 with C4.

## D. Rows the model reads exactly without any rule of rounds 24 to 26 (128)

112 are the bit-field head's second commit word (F32 / F34 / F39 EXT / INS behind OUT: work order 20's A6, ruled a
known difference); 16 others (F35 / F40 `callf-retf`, `brf-n0` and singles) are build items against rules already
specified: list in `traces/logs/rtl-miss-model-exact.json` (empty rule lists).
