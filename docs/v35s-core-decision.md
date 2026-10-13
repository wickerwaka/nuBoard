# V35S core: keep the V30 microcode or build a new core?

Measured 2026-10-12 on the socketed µPD70337L-8, harness build 2 (30 ns
tick), X1 = 8.33 MHz, fX/2, zero waits, refresh off unless stated. Work
items A2, A3 and a full A6 from [`v35s-differences.md`](v35s-differences.md).

**Recommendation: build a new V35 execution unit and bus unit. Do not keep
patching the V20 microcode.** Reuse nuV30's datapath knowledge (ALU, flags,
decode lengths, ModR/M), its architectural test suites, and this harness.
The evidence is below.

## Instruction timing (A6)

`validation/v35s/timing.py` runs the 306 instruction forms nuV30 measured on
a real V30, using the same bytes, operands and memory fill. Each form runs at
an even and at an odd address, in both lanes, from reset (556 runs, all
pass). The cost is the time between two I/O markers around a saturated-queue
window, minus the empty window: retirement to retirement, as nuV30 measured
the V30. `validation/v35s/timing_report.py` sets the results beside the V35
data book's clock table (transcribed from pdf pp 550–553, EA = 3, W = 0).

| Comparison (non-branch forms) | Result |
| --- | --- |
| V35S silicon vs V30 silicon | 34 of 259 the same, 225 differ |
| V35S silicon − V35 data book | 168 of 200 scored within 0 to +2 clocks |
| V30 silicon − V30 data book (nuV30's data) | 118 of 179 within 0 to +2 |
| V35 data book − V30 data book | −8 to +39 clocks, spread across the whole range |
| model lane (V20 microcode in the V35 shell) vs V35S | 50 of 293 the same |

So the V35S follows its own data book about as closely as the V30 follows
its own. The two books describe different machines. The +1 to +2 offset
against the book is the same offset the V30 shows under this method (the
book counts EU clocks; the method counts retirement to retirement).

The differences are not a bus effect that a new bus unit would absorb. Many
are in register-only forms with a full queue:

| Form | V30 | V35S | V35 book |
| --- | --- | --- | --- |
| ADD reg,reg | 3 | 3 | 2 |
| TEST reg,reg | 2 | 6 | 4 |
| INC reg8 / INC reg16 | 4 / 2 | 6 / 2.5 | 5 / 2 |
| MOV reg8,imm / reg16,imm | 4 / 4 | 6 / 7 | 5 / 6 |
| SHL reg,1 / SHL reg,CL (n = 4) | 6 / 14 | 10 / 20 | 8 / 19 |
| DIVU reg16 | 28 | 42 | 39 |
| ADJBA / CVTDB | 7 / 8 | 17.5 / 21 | 17 / 20 |
| EXT reg,reg | 43 | 77.5 | 41–121 |
| PREPARE 8,2 | 30 | 57 | 63 |
| PUSH R / POP R | 52 / 33 | 74 / 74.5 | 74 / 74 |
| MOVBKW (single) | 13 | 23.5 | 22 |
| Bcond taken / not taken | 13 / 4 | 24 / 9 | 15 / 8 (plus refill) |
| RETI | 22 | 52 | 40 (plus refill) |

Some forms are faster on the V35S, because its bus cycle is 3 clocks
against the V30's 4 (`ADD reg,mem` 10 against 13, `MOV mem,reg` 8 against
11). Others are slower by a factor of 2–3 (BCD adjusts, string primitives,
`PREPARE`, `PUSH R`/`POP R`). Some match exactly (`ADD reg,reg`,
`XCH reg,reg`). There is no common offset or scale. The pattern fits a core
that keeps its registers in internal RAM (the V25/V35 design). For example,
16-bit `INC` with the register in the opcode is fast, while forms that go
through a ModR/M register operand cost extra.

Multiplication differs as well. `MUL` on the V35S has its own
data-dependent cases (`MUL CL`, AW = 00FF, CL = 0: 47 against the V30's 38),
outside the book's ranges in 7 cases.

Other findings from the sweep:

- **Alignment.** An odd-length target reads one clock high or low depending
  on alignment, and the effect cancels across the two placements. The V35S
  steps through its queue a word at a time.
- **Odd-address words** cost +3 clocks over the book (the book does not list
  the second bus cycle).
- **Taken branches** cost the book value plus about 9 clocks of refill
  (3-clock fetch, then decode).

## Prefetch (A2)

`validation/v35s/prefetch.py` jumps to the next instruction and then runs
long instructions that use no bus cycle.

- **Refill after a flush:** the chip fetches back to back, one fetch every 3
  clocks with no idle state. The model's V30 policy leaves 3 idle clocks
  between fetches.
- **Fill depth:** while a 3-byte instruction executes, the chip holds 7
  bytes beyond it when the instruction ends on an even address, and 6 when
  it ends on an odd one. It fills to the word boundary that the queue's
  6-byte budget allows, one word more than the V30 policy in the first case.
  The same 7-byte fill explains the six reset-time fetches (FFFF0–FFFFA)
  ahead of a 5-byte far jump.
- **Refill trigger:** with a NOP stream, one word is fetched per two bytes
  consumed. After a long instruction, the fetches arrive back to back until
  the queue is full.
- **Odd targets:** a byte fetch at the odd address comes first, then words,
  as on the V30.
- **Data cycles:** loads, stores and read-modify-write cycles go out as soon
  as the EU asks, between fetches, with no gap. The read and write of a
  read-modify-write are 5 clocks apart (read, then write, B3 to B1).
- **Taken branches:** prefetched bytes past the branch are discarded, and the
  target is refetched back to back.

## Reset exit (A3)

`prefetch.py` also runs the smoke program at /RESET hold times of 167,
1,667 and 16,667 ticks, at X1 = 16.67 MHz / 4, / 6 and / 8.

| | silicon | model |
| --- | --- | --- |
| first refresh after /RESET rises | 118–128 X1 periods (about 15.5 states of fX/8) | 134–140 |
| first fetch (FFFF0) | 198–208 X1 periods (about 25.5 states of fX/8) | 78–84 |

The exit is independent of how long /RESET was held. The spread of up to 8
X1 periods is the phase of the internal fX/8 divider at release. The first
refresh comes one refresh period (16 clocks) after release, and the first
fetch about 10 states after that.

## Why a new core rather than a patched ucore

1. **The timing is in the EU, not the bus.** The ucore's timing comes from
   the V20 die microcode, one row per clock. Matching the V35S would mean
   retiming nearly every form: 225 of 259 differ, by amounts with no shared
   structure. That amounts to writing a new microcode program into the
   V20's row format, against nuV30's own rule of no per-opcode timing
   exceptions, and without the die evidence that makes the V20 ROM
   trustworthy.
2. **The bus unit has to be replaced anyway.** The ucore's bus unit
   hard-codes the V30's 4-state cycle and fixed offsets, and nuV30 notes it
   as a rewrite, not a parameter change. The V35S cycle, refill policy,
   reset exit and refresh are all different.
3. **The register file has to move anyway.** The V35 keeps GPRs and segment
   registers in internal RAM banks, and its timings suggest the EU's
   register access goes through that RAM. The ucore's flat register file and
   micro-register addressing would be reworked.
4. **The 8080 mode and the V20 interrupt path do not apply.** The V35 needs
   a priority controller, bank switching and macro service instead.
5. **What carries over is architectural.** Flag semantics, ALU results,
   instruction lengths and ModR/M decode match the 8086 and V20. nuV30's
   SingleStepTests suites can still check the new core's architectural
   results.

## Suggested shape of the new core

- **A V35 bus unit** built to the measured policy, with a 6-byte word queue,
  back-to-back refill, the reset exit, refresh insertion and the WTC waits.
- **An execution unit whose per-instruction step sequences are written from
  measurement.** Use a small set of mechanisms (register RAM access, EA,
  ALU, bus request) rather than a table of clock counts. The A6 sweep, now
  repeatable in about 7 minutes, is the regression for it.
- **Registers in an internal-RAM model**, with banks, from the start.
- **The first milestone:** the three existing programs and the A6 sweep at
  full-trace match, then widen to waits = 2, refresh on, and fX/8.

## Files

- `validation/v35s/timing.py` and `timing_report.py`: the A6 sweep and its
  comparison.
- `validation/v35s/prefetch.py`: the prefetch scenarios and the reset sweep.
- Raw results in `build/validation/v35s/`:
  - `timing.json`, with both lanes' full traces for every run;
  - `prefetch.json`;
  - `v35_book_clocks.json`, the data book transcription;
  - `timing_report.txt`.

Still open from step 1: A1, rerunning `characterize` at the 30 ns tick.
