# V35S core v2: mechanisms, not fitted delays

Design note, 2026-11-09. Supersedes section 4 ("Rule disposition") of
[`v35s-core-v2.md`](v35s-core-v2.md) and the attribute placement of
[`v35s-arbiter-strategy.md`](v35s-arbiter-strategy.md). The Record in
`v35s-core-v2.md` stays the log; this note is the design the next packages are
written against. The evidence it rests on is in `docs/v35s-mechanisms/`:
`classes.md` (the 84 classes: forms, the model's step lists with each integer
named, the V35S / V30 / data book costs per form, the V30 routine, the open
items), `integers.md` (every class integer and constant: what it counts, where
the model reads it, which classes carry it), `rules.md` (the rule register
against the RTL, 150 items and 168 names, the 73 arbiter attributes),
`v30-structure.md` (the V20/V30 machine as the ROM and the nuV30 core show it)
and `v30-opcodes.md` (the per-opcode ROM survey). Section 5's accounting is
the data book's formula read as microinstructions where no routine has yet
been measured against the corpus; it says so where it is.

## 0. The rule

The user, 2026-11-09, after the first fit of the arbiter-free core showed a
186–202-level chain into the microcode ROM address:

> We should not be looking ahead at the next opcode to influence timing of the
> current one. Every delay being introduced by the model needs to have a
> machine explanation. E.g. EA address calculation, needing to wait for a
> shifter, register port contention, microcode execution, queue reading.
> Arbitrary delays with no explanation are not allowed.

Consequences, stated once:

1. **A clock is spent by a mechanism.** Every clock an instruction occupies is
   one of: a microinstruction executing, a bus cycle, a stall on a datum the
   bus has not delivered, a stall on an instruction byte the queue does not
   hold, a register-file port already in use, an EA adder step, an iteration
   of a loop (shift, multiply, divide, string, BCD, bit field), or a bus-unit
   law (the fetch that cannot be pre-empted, the turnaround after I/O, the
   refresh). Nothing else.
2. **A fitted integer is a check, never an input.** The fit's `setup`, `fn`,
   `lead`, `through`, `nx`, `pre`, `wb`, the floors and the holds are
   measurements of silicon. They are what a mechanism must reproduce. They do
   not go into the ROM or the RTL.
3. **The next opcode is not read to time the current one.** The only act on
   the next instruction's bytes before the current one ends is the current
   routine's own last microinstruction popping the next opcode (the V30's
   `E`-flag pop, section 3.1), and that pop is the current routine's act.
4. **Loss is recorded, not patched.** Where a mechanism does not reproduce
   silicon, the miss is classified (section 7) and left in the Record with
   the question it raises. No count is added to make it pass.

## 1. Why the fitted core's chains are long

The first fit (Record, 2026-11-09) put the worst path at 202 logic levels,
about 195 ns, from the queue's latch register to the ROM's read address. The
chain is the model's clock evaluated end to end:

| Segment | Levels | ns | What the fitted core does there |
| --- | --- | --- | --- |
| queue byte to the live format's class | 10 | 12 | decodes the ModR/M byte as it arrives |
| the T pass's three rows in series | 40 | 50 | a start, a row and a row, each a full evaluator |
| the bus interface's counters | 50 | 36 | builds the request's setup count, then subtract, increment, two compares |
| the EU's operand select | 14 | 18 | which form executes depends on the grant |
| the shift unit's count-modulo to CW's next value | 70 | 64 | the write-back forwarding of every result into the register the next template reads |
| run bits to the ROM address | 20 | 15 | the next form's template from the next opcode and the registers after this clock |

Each segment is a consequence of executing the model's description: counts
instead of waits, several model steps in one clock instead of one
microinstruction per clock, and the next template chosen from live bytes and
live results instead of from a register. A sequencer that executes one
microinstruction per clock from a registered ROM word, stalls on a flag, and
decodes the next opcode from the byte its last microinstruction popped has
none of these segments.

## 2. Sources, in order of authority

1. **V35S silicon.** The chain corpus (30,536 refresh-off runs, every bus
   cycle's clock), the EU timing suites
   ([`v35s-eu-timing.md`](v35s-eu-timing.md)) and the bus timing suites
   ([`v35s-bus-timing.md`](v35s-bus-timing.md)). The gate.
2. **The V35 data book's clock table** (`build/validation/v35s/
   v35_book_clocks.json`, pdf pp 550–554). It is the maker's statement of each
   routine's length as a formula in EA and W, with a bracketed value when the
   internal RAM is disabled. Silicon follows it within 0 to +2 clocks on 168
   of 200 forms ([`v35s-core-decision.md`](v35s-core-decision.md)). The
   formulas decompose into mechanisms; section 3 reads them.
3. **The V30 machine.** The V20 microcode ROM dump and its disassembly
   (`build/deps/nuV30/docs/V20UC.TXT`), the group-decode PLA, the measured
   BIU laws (`docs/facts/biu_model.md`) and the silicon-verified
   microcode-driven core (`hdl/rtl/ucore/v30u_eu.sv`, `v30u_biu.sv`). The
   V35's EU is a descendant with its registers in internal RAM and its own
   routine lengths (225 of 259 forms differ from the V30's). The V30 is the
   source for the *structure* of a routine (which registers move, where the
   bus request and the data interlock sit, how the next instruction begins),
   never for the V35's clock counts.
4. **The chain model** (`validation/v35s/chains/sim/`, fit 62). An instrument:
   it predicts silicon's cycles and classifies a miss. Its fitted integers are
   the measurements the mechanisms must reproduce. It is not edited by this
   work and it generates nothing in the core.

## 3. The machine

Each mechanism below has a timing law, the evidence for it, and what it
explains among the fitted rules. The fitted names in brackets are the model's
(`fit.json` enums and the class table's integers).

### 3.1 The microsequencer

One microinstruction per CPU clock, read from a ROM word registered at the
previous clock. A routine per opcode group, entered through a decode table
indexed by the opcode byte (and the 0F second byte, and the ModR/M `reg`
field for the group opcodes). Subroutines for the effective address, the
loops and the far transfers; a conditional jump and a loop counter.

- *Evidence.* The V20 ROM: 1,028 words, four per row, one per clock, 257
  activation patterns, `FARJMP` subroutines (`SHIFT`, `MULX`, `IDIV`,
  `REPX`, `CALLF`, `RETF`, `INT`, `PUSHA`, `POPA`), `JMP` on ALU conditions
  (`V20UC.TXT` 0000–04FF). The nuV30 core executes that ROM against silicon
  at 169,000 / 169,000 golden cases with one microinstruction per clock and
  five named stalls. The V35 data book's integer counts for the register
  forms (ADD reg,reg 2, XCH reg,reg 3, INC reg16 2, NEG reg 5, SHL reg,1 8,
  TEST reg,reg 4) are routine lengths.
- *The end of an instruction.* A routine's `E` microinstruction pops the
  next opcode on its own clock (if the byte is in the queue and no store
  still owes its datum; otherwise the pop is deferred to the tail), and
  exactly one microinstruction runs after `E`, overlapped with the
  successor's decode: it carries real datapath work (the result and flags
  of the `E` row's ALU operation, a push's datum) but no bus cycle and no
  pop (`v30-structure.md` section 4, with the ROM lines and the nuV30
  core's row logic). Measured on the V35S as the pre-pop
  (`v35s-core-model.md`, "The next-opcode pre-pop": the pop lands 2 clocks
  before the routine's end for the forms that do it, which is the `E` row
  and the post-`E` row). This is the whole of the look-ahead the machine
  has, and it is the current routine's act. [Explains: `nx`, `nx0`,
  `prepop`, the "end hide", `one_idle`'s last-clock shape, `late_read`.]
- *The start of an instruction.* The decode's output is the routine's entry
  and the format bits the datapath needs (width, direction, ModR/M present,
  immediate bytes, segment override, the group's operation). Measured: the
  V35S shows no decode clock between a routine's end and the next's first
  microinstruction beyond the pop and the word load (the placement costs,
  `v35s-core-model.md`). [Explains: `pre` = 0 for the two-byte register forms;
  `pre` > 0 is the ModR/M pop and the register read (3.2, 3.3), not a decode
  delay.]
- *Not in the ROM.* Prefetch, refill, idle, resume: 0 tokens in the V20 ROM
  (`biu_model.md` lines 18–40). The bus unit's laws are hardware (3.7).

### 3.2 Instruction bytes from the queue

A microinstruction that needs an instruction byte (an opcode, a ModR/M, a
displacement byte, an immediate byte, a port number) pops it from the queue
on that clock; if the byte is not in the queue the microinstruction stalls
(`stall_q`). One byte per microinstruction. The queue delivers words; the EU
holds the head word in a word register whose load costs the clock the data
book charges as an alignment effect.

- *Evidence.* The V20 ROM's `Q -> tmpa` / `Q -> tmpaH` reads, one byte each
  (79 uses). The V35S placement costs: a 2-clock word load, hidden once per
  routine at the opcode's pop or at an operand's pop (`v35s-core-model.md`
  "Placement costs"); an odd-length target reads one clock high or low by
  alignment and the effect cancels across placements
  (`v35s-core-decision.md`). The consumption-at-fixed-steps model was
  measured worse than the word register on every measure, so the word
  register is the queue's output and the routine pops bytes from it.
- *What this forbids.* The format is not assembled from bytes the EU has not
  popped. The loader's "decode ahead" of the live ModR/M byte (the first
  segment of the long chain) goes: the ModR/M is popped by the routine's
  microinstruction and decoded from the register it lands in, one clock
  later at most. [Explains: `room_ir`, `modrm_mate`, `latch_disp`,
  `imm_landed`, `port_landed`, `disp16=word`, `lea_room`, the `*_ir_room`
  family: each is "the byte is or is not in the word register when its
  microinstruction asks for it".]

### 3.3 The register file is internal RAM

General, segment and the bank's registers are words in the internal RAM
(`v35s-eu-timing.md` M3/M8: a data access to the bank's addresses reads and
writes the live registers; RAMEN = 0 sends the same addresses out and leaves
the registers untouched). A register read is a RAM read, a register write a
RAM write; the RAM has the ports it has, and a microinstruction that needs a
port already in use waits.

- *Evidence and laws.*
  - A two-operand register form reads two registers and writes one in 3
    clocks (measured: MOV, ADD, CMP, XCH reg,reg all 3, any pair, any byte
    position; the book says 2 for MOV/ADD/CMP and 3 for XCH). So two reads
    and a write fit in the routine's clocks: the ports are at least one read
    and one write per clock, and `XCH` with two writes costs 1 more. [A law
    to confirm on the two-tick core: port A read, port B read, write-back on
    the following clock.]
  - The ModR/M register forms of the unary operations cost 6 against the
    short forms' 2.5 (INC/DEC reg16 40+r), and TEST reg,reg costs 6 writing
    nothing. The data book: INC reg16 2, INC reg8 5, NEG/NOT reg 5, TEST
    reg,reg 4. The group-3 / group-5 routines are the memory form's
    read-modify-write routine with the register as the operand: a read
    microinstruction, the operation, a write microinstruction. Not a port
    count (the `regport` suite: `XCH` with four accesses costs what `CMP`
    with two does).
  - Every data write with RAMEN = 1 costs 3 + W clocks more than with
    RAMEN = 0, per write (the book's bracketed values: MOV mem,reg EA+5+W
    against EA+2, PUSH reg16 13+W against 9+W, PUSH R 74+8W against 50,
    BRK 50+5W against 38+5W; measured M2: every form that writes memory is
    exactly 3 clocks faster with RAMEN = 0, multi-write forms per write).
    **The mechanism: with the internal RAM enabled the EU holds until the
    write cycle ends, because the write may land in the RAM that holds the
    registers; with it disabled the write is posted and the routine
    continues.** This is the `wb` / `wbsync` / `mwb` family: the clocks after
    a write before the next instruction starts. [Explains: `wb`, `mwb`,
    `rwb`, `wbsync`, `wbsync0`, `xwb`, `flwb`, `lea_wb`, `push_mem_write`,
    `store_imm`'s tail, the RETI / BRK / PREPARE per-write costs.]
  - Bank makes no difference (eleven forms identical in all eight banks).
- *What this forbids.* No per-class write-back integer. The write-back is a
  microinstruction that writes the RAM and, when RAMEN = 1 and the write is
  a bus write, stalls until the bus unit reports the cycle's end
  (`req_done`).

### 3.4 The ALU and the temporaries

One ALU operation per clock between two temporaries, the result (SIGMA) to a
register or a temporary on the next microinstruction; the flags written with
the result (`W`). Byte and word at the same cost.

- *Evidence.* The V20 ROM's `tmpa`, `tmpb`, `tmpc`, `SIGMA`, `ALU op`; the
  V35S: MOV, ADD, CMP cost the same; byte and word the same; the flag
  operations (CLR1 CY, SET1 DIR) 2.5 = one microinstruction and the pop.
- *The shifter* is a loop in the ALU: 2 clocks per count on the V35S
  (12 + 2n register, 21.5 / 23 + 2n memory, n up to 255 unmasked; count 0
  costs 10; the book: SHL reg,CL 11 + 2n, reg,1 8). The V30's ROM runs the
  shift as one `R` row, one clock per count (10 + n measured). So the V35's
  iteration is two clocks where the V30's is one: a second microinstruction
  per count, or an `R` row at half rate. This is the first V35-specific
  loop mechanism to establish on silicon (`classes.md` SHIFT_CL / SHIFT_IMM,
  open items). [Explains: `shift_count`,
  `shift_cl_mem`, `shift_mem_imm`, `rmw_shift`, `abort_unit=loop`'s count,
  `unit_hold`'s parity: the loop's two microinstructions alternate, so an
  event that lands on the first or the second of them is a clock apart.]
- *Multiply, divide.* MULU r8 26, r16 34 (book 24 / 32): the ROM's loop is
  one `R` row per bit, 8 or 16 of them, and the V35's word-minus-byte
  difference of 8 is exactly the ROM's extra 8 steps (the V30 measures 7,
  which the sources do not reconcile); MUL negates the product when the
  signs differ (+8, +1 per zero half). DIVU 34 / 42, DIV 53 / 61 base, +7
  negative dividend, +2 negative quotient: the ROM's restoring loop, one
  row per bit, with a pre-check and the trap. [Explains: `mul_imm_*`, the `long_exec` /
  `hphase` / `mtail` family: the loop's phase at the clock the bus unit
  delivers or the queue refills.]
- *BCD, bit fields, rotates.* ADD4S 23 + 30 per digit pair (the book
  22 + (30 + 3W)n: 30 per pair is a read, a read, an add, a write with its
  RAMEN hold, and index steps), CMP4S 24 + 25 per pair (no write: 5 less,
  the write's microinstruction and its hold). EXT 107 − 2o − 4w, INS 94:
  per-bit loops over offset and width. ROL4 reg 18.5, mem 24.5.
  [Explains: `bcd_fetch`, `bcd_*`, `bf_*`, `rot4_exec`, `cvt_*`.]

### 3.5 The effective address

The EA adder forms base + index + displacement into the address register.
The data book charges EA = 3 for mod 00 and 01 and 4 for mod 10. Measured
on the V35S: [reg] and [base+index] +0, any form with d8 or [disp16] +1,
[base+index+d16] +2, over a base cost of 10 for a load, 8 for a store,
13 for ADD mem,reg, 6 for LDEA.

- *Mechanism.* **The ROM has no EA routine.** The address is formed by the
  loader before the routine starts, and the routine begins with the memory
  operand already read (`v30-structure.md` section 6: the ModR/M pop, then
  one clock for mod 00, two for a disp8 and three for a disp16 or a direct
  address, each one more if the displacement byte is not yet in the queue;
  the adder itself costs no clock; then the operand pre-read opens the
  routine's first row). The V35S measures the same shape over its base
  costs: +0 for [reg] and [base+index], +1 for a d8 or [disp16], +2 for
  [base+index+d16]; the book's EA = 3 / 4 is that march with the base
  cost's share folded in. So the EA is an address unit fed by the pops: the
  clocks are the displacement bytes' pops and one add. [Explains: the `ea` table (7 entries),
  `ea_class`, `disp_floor`, `disp_take`, `lea_*`, `ea_b2b`, `ea_ir_room`,
  `grp_disp`'s displacement timing: all are "which clock the displacement
  bytes are popped on and how many adds follow".]
- *Segment.* SS for BP-based forms costs the same as DS0 (measured). A
  segment prefix is its own one-microinstruction instruction (2.5 clocks:
  one microinstruction and the alignment hide; two prefixes +6).

### 3.6 Bus requests from the EU

A microinstruction posts a request (address register, kind, width, datum)
to the bus unit's EU port; the routine continues; the microinstruction that
needs the datum carries `F` and stalls until the bus unit's `req_done`
(`stall_opr`). A write with RAMEN = 1 stalls the routine's end until
`req_done` (3.3). An odd-address word is two cycles (the bus unit's pair:
load +4, store +3, read-modify-write +6, measured). A bus cycle is 3 + W
clocks (`v35s-bus-timing.md`).

- *Evidence.* The V20 ROM: `IND`/`OPR`, `MEMR`/`MEMW` with the segment, the
  `F` flag on the microinstruction that reads `OPR`; `biu_model.md`: "the
  F-flag / OPR data-ready interlock is the ONLY EU↔BIU bus sync". The V35
  book: a load is EA + 7 + W (the request, the cycle, the datum into the
  register), ADD mem,reg EA + 10 + 2W (two cycles, both waited with
  RAMEN = 1), ADD mem,reg with RAMEN = 0 EA + 7 + W (the write posted).
- *What the request carries.* Exactly the A1 port: valid, cycle type,
  address, width, datum, the reservation; `req_ack`, `req_done`,
  `done_data`. The reservation is up from the clock the routine knows it
  will request until the request is acknowledged (nuV30's "the reservation
  must LEAD the request by one cycle", `eu_soon`). [Replaces: `setup`,
  `fn`, `fo`, `lead`, `through`, the six counting modes, the floors
  `dfloor` / `istart` / `nb`, `io_count=nowait`, `grp_free_bus`, the
  detached I/O's write buffer, `relatch`, `port_latch`, the request
  positions. Each becomes the number of microinstructions between the post
  and the `F`, which is the routine's shape, or a stall.]
- *I/O.* IN 14 + W (acc,DW) / 15 + W (imm8); OUT 8–11 + W by form. The I/O
  recovery is the bus unit's turnaround (A1_IOREC = 1, kept).

### 3.7 The bus unit's laws

Kept from Q1/Q2/A1 as built, each with its measurement:

- A fetch is a word at an even address, 3 + W clocks; after a flush fetches
  run back to back; the queue is 6 bytes (3 words plus the word register);
  one word is fetched per two bytes consumed; the fill reaches the word
  boundary the budget allows (`v35s-bus-timing.md` Prefetch).
- An EU request never pre-empts a fetch in flight; it wins at the next
  boundary (`biu_model.md` exp 4; the V35S: "loads, stores and
  read-modify-writes go out at the next bus slot after the EU asks").
- A reservation blocks a fetch from starting unless the queue is low; an
  I/O reservation is absolute (A1's rule 3, the user's decision).
- The back-to-back committed fetch (rule 1), the odd pair, the aborted
  fetch (Q2's triple clock, kept as a bus-unit mechanism until a routine
  explains it), the I/O turnaround, refresh insertion.
- *What leaves.* Every attribute the arbiter carried and A1 moved into the
  sequencer's counters (the fetch-free tails, the dated holds, the group
  forms' pauses, the 0F page's counts): under this note they are not
  counters but the consequence of where the routine's post and `F` fall.
  Where silicon's fetch pattern is not reproduced by that, the miss is
  recorded (section 7), not counted.

### 3.8 Transfers

A taken branch flushes the queue at a fixed microinstruction (the V20's
`FLUSH` at fixed addresses, SUSP before it), the target is fetched back to
back, and the routine's first microinstruction waits for its opcode
(`stall_q`): measured 24 for Bcond taken (book 15 plus about 9 of refill:
a 3-clock fetch and the pop), 9 not taken (book 8). CALL near 21 + W (the
push with its RAMEN hold), RET 19 + W (the pop's read and the flush).
[Explains: `hold`, `fgap`, `nfgap`, `cfgap`, `flush_hold`, `xfer_*`,
`decide_abort`, `refill_start`: the flush clock is the routine's, the
refill is the bus unit's law, the resume is the stall.]

### 3.9 What is not a mechanism

The following fitted names have no act behind them and are not carried:
the dating variants (`free_hold=delivery`, `free_idle`, `fetch_first`'s
dating, `imm1_first`, `request_reissue=no_mem`'s sample, `grp_disp`'s
take-clock exemption, `page_*`'s restart-on-a-fetch-not-committed), the
nowrite slot's rules, `slot_room=word`, `disp_io=extend`, the page counts
(`pthru`, `ftail`, `run_wait`, `page_imm_run`), `str_raise`, `xfer_nt=odd`,
`grp_io_hold`, `io_b2b`'s stored count, `count_latch`, `lapse` and the
take-sync family. Each is a place where the model's structure (a count
compared on a clock) stood in for a routine's shape. The families they
score are in the budget of section 7; the question each raises is written
beside its loss in the Record when the mechanism core is measured.

## 4. The sequencer that results

- **The ROM word is a microinstruction**, not a timed step: source and
  destination register ports (RAM port A, port B, the write port, the
  temporaries, SIGMA, the address register, the queue byte), the ALU
  operation and whether flags are written, an EA adder step, a bus request
  (kind, width, segment) or none, a queue pop (into the opcode, ModR/M,
  displacement, immediate or port register), the `F` wait, the `E` end, and
  the sequencing (next, jump on a condition, call, return, loop on a
  counter). No count, no attribute of another instruction, no reference to
  the bus unit's state beyond `F` and the reservation.
- **The ROM address is a register.** The next address is the current word's
  sequencing field, or the decode table's entry for the opcode byte popped
  on the `E` clock, registered. The decode table is the group-decode PLA's
  function (opcode → routine entry, format bits), indexed by a popped byte.
- **A clock is one word.** The tick-A / tick-B split of S7b stays as the
  two halves of one word's execution: tick A reads the RAM ports and the
  ROM word, tick B computes the ALU result and the next address and writes
  the ports. No evaluator chains; the depth budget of the clocking
  directive (about 12 levels a tick) is met by construction, to be shown by
  `v35_timing.sh ucode` on the first package.
- **Loops** are counters loaded from CL, CW or an immediate by a
  microinstruction and decremented by the loop's `JMP`. The REP string's
  CW = 0 case is the routine's own first `JMP Z` (the V20's `00A6 JMP Z`),
  not a template selection.
- **The loader** shrinks to the word register, the pop port and the decode
  table. The format is assembled from popped bytes.
- **The EU datapath** (`v35_eu.sv`, `v35_ea.sv`, `v35_fn_pkg.sv`,
  `v35_regram.sv`) is kept as the ALU, the functions and the RAM; the
  divider's combinational `v35_div` and the shift's modulo go behind their
  loops.
- **The generator** `ucgen.py` is replaced by a microprogram assembler: the
  routines are written by hand (one file per routine family) in the word's
  vocabulary, assembled to the ROM banks and the decode table, with a test
  that every routine's length at EA = 3, W = 0 matches the data book's
  formula where the book has one (the "book check", replacing the inverse
  check against the model's steps) and that the corpus gate holds per
  family.

## 5. The classes, by mechanism

Format: class group → the data book's formula (EA = 3, W = 0, RAMEN = 1) →
the measured V35S cost → the routine's accounting in mechanisms → the fitted
integers and rules it replaces. "Book" marks an accounting that is the data
book's formula read as microinstructions and not yet confirmed by a routine
measured against the corpus. The per-class detail (forms, the model's step
lists with each integer named, the V35S / V30 / book costs per form from the
a6-timing corpus, the V30 routine, the open items) is
`docs/v35s-mechanisms/classes.md`.

| Group (classes) | Book | Measured | Accounting | Replaces |
| --- | --- | --- | --- | --- |
| Register two-operand (REG, TEST_REG, XLAT's register part) | 2 (XCH 3, TEST 4) | 3 (TEST 6) | opcode pop with ModR/M on the next word; read A, read B, ALU; write SIGMA on the `E` word with the next opcode's pop. TEST goes through the group routine (read, op, no write) | `nx` 1, `pre`, `wb` 2; `room_ir_pre=modrm`, `pre_modrm`, `start_sync=b2b_modrm` |
| Short register (INCDEC 40+r, XCH AW,r, flag ops, CVTBW) | 2 / 4 / 2 / 3 | 2.5 / 4 / 2.5 / 3 | one word (read-modify-write in place) plus the `E` pop; the .5 is the alignment hide | `pre0`, `nx0`, `one_idle`, `nop_hold` |
| Register immediate (IMM, MOV reg,imm) | 5 / 6 | 6 / 7 | pops of the immediate bytes (one per word), ALU, write; the word load under the pops | `imm_count`, `imm_head`, `imm_order`, `room_ir_imm` |
| Unary ModR/M register (INCDEC r/m, NOT, NEG, the group forms) | 5 | 6 | the RMW routine on a register: read, op, write, `E` (the ROM has one routine for the register and the memory form of a ModR/M operation; the model puts 88 such register forms in its `rmw` class with a read and a write at no address, which `classes.md` records as unresolved) | `grp_ops`, `grp_fixed`, `fixed_lookup*`, `lookup_start` |
| Load (LOAD, LOAD_ALU, LOAD_SEG, LOAD_PTR) | EA+7+W = 10 | 10 + EA mode | ModR/M pop, base read, (index read, add), (disp pops, add), post the read, 3-clock cycle, `F` word takes the datum, ALU, write on `E` | `setup` 3.., `fn`, `dfloor`, `dhold`, `grp_free`, `fgrp`, `dclk`, `mem_order`, `ea_post` |
| Store (STORE, STORE_IMM, MOV mem,sreg) | EA+5+W = 8 (EA+2 at RAMEN 0) | 8 | EA as the load, post the write with the datum, the routine's end holds until `req_done` (RAMEN) | `wb` family, `push_mem_write`, `sync_req=disp`, `post_on_take`, `disp16=word` |
| Read-modify-write (RMW, RMW_IMM, SHIFT mem, BIT1_RMW/CLR) | EA+10+2W = 13 (ADD), EA+13+2W (INC/NEG), EA+16+2W (SHL ,1) | 13 / 16 / 21.5 | EA, post the read, `F`, op, post the write, hold until `req_done`. The read and the write are 5 clocks apart (measured) = `F` + op + post | `rmw_alu=through`, `through`, `grp_read`, `rmw_shift`, `gdisp_*`, `dest_route` |
| Stack (PUSH, PUSH_SEG, PUSH_IMM, PUSH_MEM, POP, POP_SEG, POP_PSW, POP_MEM, PUSH_R, POP_R) | PUSH reg 13+W, POP reg 11+W, PUSH R 74+8W | 9 / 11.5 / 74 / 74.5 | SP read, decrement, post the write with the register read, hold until `req_done`; POP: post the read at SP, `F`, write, SP increment. PUSH R / POP R: eight of these, 9.25 per word, in a loop | `setup_free` 3, `setup` 7, `burst_*`, `pop_mem_order`, `prepare_order` |
| Calls and returns (CALL, CALL_REG/MEM/FAR/FAR_MEM, RET, RET_IMM, RET_FAR*, RETI, BRK) | CALL near 21+W, RET 19+W, RETI 40+3W, BRK 51+5W | — (F23/F30/F35/F37 families) | the push(es) with their holds, the flush at a fixed word, the target fetch, the first word's `stall_q` | `hold`, `fgap`, `setup_free`, `xfer_*`, `ret_imm_hold`, `far_room`, `xfer_mem_*`, `refill_start` |
| Branches (BRANCH_SHORT/NEAR/FAR, BR_REG/MEM, DBNZ, DBNZ_Z, BCWZ) | Bcond 8 / 15, BR short 12, DBNZ 8 / 17 | 9 / 24, —, — | the condition's `JMP` (one word), not taken: `E`; taken: flush, redirect, the 3-clock refetch, the pop's stall (about 9) | `cfgap`, `nfgap`, `nhold`, `chold`, `decide_abort`, `xfer_nt*`, `cond_gap` |
| Shifts (SHIFT_CL, SHIFT_IMM) | 11+2n, 9+2n; reg,1 8 | 10 (n=0), 12+2n | count pop or CL read, the 2-word loop, write | `shift_count=late`, `abort_unit=loop`, `unit_hold`, `hphase`, `mtail`, `sidle`, the C0/C1 mask (none) |
| Multiply, divide (MUL, MUL_IMM, DIV) | MULU 24 / 32, DIVU 31 / 39 | 26 / 34, 34 / 42 | the per-bit loops under their counters; MUL's sign fix-up; DIV's pre-check and trap | `mul_imm_*`, `long_exec`, `mul_from`, `hphase` |
| BCD, conversions, adjusts (BCD4S, BCD4S_CMP, ADJUST, ADJUST_B, CONVERT, CONVERT_D, ROL4, ROR4, *_MEM) | ADD4S 22+30n, ADJ4A 9, CVTBD 19, ROL4 17 | 23+30⌈CL/2⌉, 10.5, 22, 18.5 | per-pair loop of two reads, an add, a write with its hold; the adjusts and conversions as straight routines | `bcd_fetch`, `cvt_*`, `rot4_exec`, `pre0` |
| Bit operations (BIT1, BIT1_TEST, BIT1_RMW, BIT1_CLR, BF_EXT, BF_INS) | TEST1 reg,CL 7, mem EA+12+W; EXT 41–121 | — (F32/F34/F39/F40) | the 0F second byte's pop, the CL read and mask, the RMW routine; EXT/INS per-bit loops | `page_*` (23 fields), `bf_*`, `test1_head`, `page_mt*`, `full_latch` |
| Strings (STR_MOVE/STORE/LOAD/CMP/SCAN/IN/OUT) | MOVBK 22+2W single; REP STM 16+(9+W)n | 23.5; 25+18n / 25+9n / 26+11n | the REP prefix's own word; CW = 0 `JMP Z` first; per element: read (3+`F`), write (3 + hold), index steps, count decrement, `JMP REP`. The V30's MOVS loop is four words and a bubble at 8 per element (bus-bound); the V35's 18 per element is the second V35-specific loop mechanism to establish: two cycles, the RAMEN hold, and what else | `str_*` (12 fields), `fetch_hold/release`, `quiet`, `split_floor`, `str_single_*` |
| I/O (IN, OUT, the DW forms) | IN 14+W / 15+W, OUT 8–11+W | — (F3/F7/F29) | port pop or DW read, post, `F` (IN) or the write hold (OUT); the turnaround is the bus unit's | `lead`, `relatch`, `port_*`, `io_*` (9 fields), `dw_*`, `wlatch_*` |
| LDEA, PREPARE, DISPOSE, TRANS, HALT, prefixes | EA+2, 26+W.., 11+W, 11+W, 4 (NOP) | 6, 30/40/57, 11.5, —, 4 | EA then write; PREPARE's per-level pushes; a prefix is one word | `lea_*`, `prepare_order`, `halt_status`, `pfx` |

Two readings of the measured against the book recur and are themselves
mechanisms: the +1 that retirement-to-retirement measurement adds to a
register form with no bus cycle (the method counts the next pop), and the
exact match on forms that end with a bus cycle (the cycle's end is the
retirement).

## 6. The fitted rules, dispositioned

The rules of `v35s-core-v2.md` section 4 (it says 137; its lists enumerate
150 items and 168 distinct names, the (b) list holding 74 against its
stated 61) and the 73 arbiter attributes fall into three bins under this
note; 64 rules of the A4 register that section 4 never listed (the
`refresh_*` family, `room_ir_ready`, the `wlatch_*` rules, `ea_disp16`,
`ea_direct` and others) take the same bins. The per-rule table (name, the
model's meaning, where it lives today, section 4's bucket) is
`docs/v35s-mechanisms/rules.md`.

- **Explained** (a mechanism in section 3 produces it; the rule is deleted
  and the mechanism's law carries it): the queue-byte family (3.2), the
  write-back family (3.3), the EA family (3.5), the request-timing family
  (3.6: setup, counting modes, leads, floors, the request positions), the
  transfer family (3.8), the loop-phase family (3.4).
- **Bus unit** (a law of the prefetcher, kept where it is, with its
  measurement): the fetch length and cadence, the refill threshold, the
  non-pre-emption and the boundary grant, the reservation and `q_low`, the
  pair, the aborted fetch, the I/O turnaround, refresh.
- **Dropped** (3.9): the dating variants, the nowrite slot, the page counts,
  the count-latch family. Their runs are the loss budget.

## 7. Method and gates

1. **Write the routines, not the counts.** One file per routine family in
   the assembler's vocabulary, each routine's length checked against the
   book's formula (the book check). Where silicon and the book disagree
   (section 5's "Measured" column), the routine follows silicon and the
   reason is a mechanism named in the file (a word the book does not count,
   the RAMEN hold, an alignment hide).
2. **Measure per family on the corpus** as before (`replay --core v35
   --score`, both spacings, `+v35_chk`). Classify every miss: (i) the
   routine's shape (a microinstruction missing or extra: fix only with a
   named act), (ii) a bus-unit law (section 3.7: fix in the bus unit with a
   measurement), (iii) unexplained (recorded with its example; not fixed by
   a count).
3. **The function gates are unmoved**: write data 106,824 / 106,824, SST
   2,849,080, the register and function vectors 0 bad.
4. **Timing is measured at every package**: `v35_timing.sh ucode` at
   15.625 ns, the depth per tick reported; the whole core when the
   sequencer closes.
5. **Loss.** The mechanism core starts below the fitted core's 28,059. The
   number is reported per family with its classification. No family is
   patched to a number; the recovery of a family is a mechanism found, and
   it is written in the Record as such.

## 8. Work packages

Each is a worktree Opus package with the gates of section 7; the overseer
reviews, verifies on main, records and commits.

- **MX0, the assembler and the sequencer.** The microinstruction word, the
  assembler (`validation/v35s/chains/uasm.py`), the book check, the
  registered-ROM sequencer with the five stalls, the decode table from the
  PLA tables, the loader reduced to the word register and the pop port. The
  register two-operand, short register and register-immediate routines.
  Gate: F0 F1 F2 F3 F9 F11 F12 F20; `v35_timing.sh ucode` depth.
- **MX1, memory forms.** The EA subroutine, the request port's use, the
  RAMEN hold, loads, stores, read-modify-write, the group forms, LDEA.
  Gate: F4 F5 F6 F7 F10 F14 F15 F16 F19 F21 F22 F25 F26 F36 F38.
- **MX2, transfers and the stack.** PUSH/POP, CALL/RET, BRK/RETI, the
  branches, the flush and the refill. Gate: F23 F30 F35 F37.
- **MX3, loops.** Shifts, MUL/DIV, BCD, conversions, bit operations and
  fields, the 0F page. Gate: F32 F33 F34 F39 F40.
- **MX4, strings and I/O.** The REP loop, the string elements, IN/OUT, the
  DW forms, PREPARE/DISPOSE. Gate: F24 F29 F31; the whole corpus.
- **MX5, the whole core's timing and the bitstream.** The per-module and
  whole-core runs at 64 MHz, the harness image, the board programs.

Open to the user before MX0: whether the data book's formulas are accepted
as the first draft of every routine (the position taken here), and whether
the Q2 aborted fetch stays a bus-unit mechanism until a routine explains it.

## Corrections from MX0 (2026-11-10)

Measured on the gate families while landing MX0 (docs/v35s-core-v2.md, Record); each is a
change to the text above, kept here rather than rewritten into it.

1. **§3.1, the dispatch stall (new law, sequencer side).** The word after `E`, which hands the
   staged opcode to its routine's entry, does not execute while the bus unit runs a fetch cycle
   (its issue clock through its last clock); a form with a ModR/M byte also waits on the clock a
   back-to-back fetch is issued. Operand pops are free during a fetch. This is the frozen model's
   `_start` (`start_sync=b2b_modrm`, rules.md item 16, binned there as emerging from the
   structure; it does not emerge). It removes the wait dependence of every family. On the `E`
   word instead, the dependence returns. The machine explanation on record is the overseer's
   hypothesis, not evidence: the dispatch and the fetch are mutually exclusive through one shared
   resource (the decode's read of the queue, or a shared sequencer step). The ModR/M clause stalls
   one clock the model does not (a back-to-back fetch committed after the `E` pop): open.
   *Confirmed by the user 2026-11-10: the law and its explanation stand.*
2. **§5 and §7, the book offset.** "Measured = book + 1 or 2" is the dispatch stall: the a6
   method timed each form between I/O markers, the form's own pops make room, the room issues a
   fetch, and the marker dispatches inside it. The book's formulas are therefore the routine's
   first draft with the stall in place, not the measured costs.
3. **§7, the first draft's rule (overseer's wording; confirmed by the user 2026-11-10).** The data
   book's formula is the first draft of every routine. A routine never carries a clock without an
   explanation, so a clock may be removed on silicon's direct measurement (the a6 sweep,
   v35s-eu-timing.md, the chain families' per-form costs), less the dispatch stall where the
   method put a fetch under the marker, without further explanation; a clock is added only as a
   named act or as a book clock marked OPEN. A clock the book charges and silicon does not spend
   is a book error, not an OPEN word (PUSH r16: book 13, silicon 9; NOP: silicon 4 with the stall).
   The position of a routine's OPEN words is free and chosen on the chain evidence. Fit integers
   remain forbidden. `test_uasm` enforces: never longer than the book, never "measured" alone,
   never a fit.
4. **§3.1 / §3.2.** The `E` word pops the opcode and its ModR/M byte together; the dispatch reads
   the registered ModR/M. The word register is built as §3.2 says (a registered word loaded from
   stored bytes only, one load a clock, never the arriving word or the latch); it does not account
   for the immediates' late takes (the model's `pre` 3), which stay OPEN words placed before the
   pops.
5. **§3.6.** OUT's I/O write is posted on the `E` word and not held; silicon's write leaves 3–4
   clocks after a post following the datum. The model holds the fetch under the posted I/O write
   with a lead and issues the write at pop + 14, after the routine has ended: a bus-unit attribute
   with no act (the I/O lead A1 recorded), the cause of OUT imm8's parity residual.
6. **§3.7, Q2.** The triple clock's start is the opcode's read from the queue (the `E` pop, with
   the ModR/M as the operand take), not the routine's entry.
7. **§3.4, MOV r8,imm8.** The model's events show 4 clocks opcode to opcode where the book says 5
   (a6: 6 with the stall); evidence, not a measurement, so the routine keeps the book's 5. It is
   entangled with SHL r,CL's OPEN words on the chains where MOV CL,imm precedes the shift.

## Corrections from MX1 and MX1b (2026-11-10)

1. **§3.1 and Corrections-from-MX0 item 1: the dispatch law gates the pop.** The frozen model's start of
   an instruction is the clock its ModR/M byte is taken from the queue (the opcode prefetched into the IR
   earlier, with no effect on the room), and the fetch that take's room triggers is issued on the same clock
   and never blocks the start; a started instruction is never stalled by a fetch. In the sequencer that is
   the E word: it does not execute while a fetch granted on an earlier clock is in flight (a ModR/M form's
   also not on a back-to-back fetch's issue clock), a fetch granted on the E clock never blocks it, and the
   dispatch word and the routine's words never stall on a fetch. MX0 placed the stall on the dispatch word,
   one clock later, under the very fetch the E's pops had triggered, and sized every routine around it. The
   machine explanation stays the confirmed one (the opcode's read from the queue and a fetch in flight are
   mutually exclusive through one shared resource); it is the pop it gates.
2. **§5 and §7, the routines' clocks.** With the law on the E word, the routine's E-to-E clocks and its pop
   clocks are set to the model's start-to-start and take clocks read on a run the model is exact on, named in
   the routine's reason: ADD / CMP / MOV reg,reg 3 (book 2: the registers' RAM read a word of its own, the
   V20's shape), NOP 4, MOV r8,imm8 4 (book 5), MOV r16,imm16 5 (book 6), PUSH r16 9 (book 13), SHL r,CL
   12 + 2n (book 11 + 2n), MOV [d16],acc 9 (book 8), a load [BW] 11 (book 10) posting its read at start + 4.
3. **§3.2, the immediates.** Every immediate form takes its first operand byte three clocks after the start
   (the model's `pre` 3 in every immediate class; a d8 displacement too), while a ModR/M byte is taken at the
   start. Written as one OPEN word before the pop; the one mechanism it suggests is an operand-byte path
   latency the opcode / ModR/M path lacks (the word register of MX0b is not it). Open.
4. **§7, ruling 3 extended.** Where silicon is longer than the book with no named act (the loads, CMP, TEST,
   XCH, CMP / ADD mem,imm, MULU mem, the shifts by one and by imm8), the routine carries the extra clocks as
   OPEN words declared "silicon longer than the book" with the exact run; the test accepts a path over the
   book only with that declaration or with named acts. Fit integers remain forbidden.
5. **§3.5, the EA as built (MX1).** The word after E of a ModR/M memory cell calls the EA head of the
   registered ModR/M's mode (the displacement's pops and a return, through a one-level return register loaded
   at the dispatch) and the routine's first word is the add; two head sets, the book's EA clocks the pops do
   not fill as OPEN words (mod 00: one OPEN and one book error) or the pops alone where the routine's own acts
   exceed the book. [BW] and [BW + IX] cost +0, a d8 +1, a d16 or a direct address +1 to +2 on silicon.
6. **§3.6, the request slot.** The EU's one request slot frees on the cycle's end; a post on that clock
   stands from the next. A read's datum is latched at its end also when that clock posts the next request.
7. **§3.4, the register loops under a fetch (found at MX1b, built at MX1c).** On silicon the LS head's
   SHL AW,CL runs 75 clocks at 0 waits and 76 at 1 wait for n = 31 where 12 + 2n is 74: a register shift,
   MULU / MUL or DIVU / DIV pauses at its two-clock iteration boundary while a fetch is past its second clock,
   until the clock after that fetch's last, once per fetch (the frozen model's unit_hold, rules.md item 94,
   true over the whole corpus). The explanation on record is the overseer's hypothesis: the iteration and the
   fetched word's delivery into the queue share a resource (the internal bus or the register RAM's port the
   temporaries use). It accounts for MX0f's "instruction after the shift +1" and the OUT marker's port byte
   at start + 5 after the shift.
8. **§3.7, the room (found at MX1b, built at MX1c).** The IR / staging byte is a seventh queue slot: free
   when empty on a word's arrival clock and when the decoder is idle, not a slot while the running
   instruction still owes bytes (the model's room_ir = arrival_idle). MX0's loader counted the slot as
   occupied while bytes were owed, so a MOV r16,imm16 stream fetched three clocks later than silicon.
