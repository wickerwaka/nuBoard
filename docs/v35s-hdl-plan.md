# V35S chain model to RTL: conversion plan

The chain-timing model in `validation/v35s/chains/sim/` is the fitted cycle
model the V35S core plan called for in its Phase 2
([`v35s-core-plan.md`](v35s-core-plan.md)). This plan says how that model
becomes the timing half of `v35_core`. It replaces the core plan's
assumption that `costs.py` emits a cost table: the chain model is a set of
clocked machines with a fitted structure, and the RTL has to carry the
structure, not only the numbers. The function half (ALU, flags, register
file, SFRs, interrupts) stays as the core plan has it, from nuV30's
semantics checked by SingleStepTests.

## What is being converted

Five machines, one step per CPU clock (`sim/machine.py`, `Machine.run`):

| Machine | File | State it owns |
| --- | --- | --- |
| bus unit | `bus.py` | the current cycle (kind, address, width, start, length), the last end per kind, the recovery gap |
| queue | `queue.py` | six bytes of storage, the request flag, in-flight and latched words, the IR-load clock, the abort/retry state, the storage count |
| decoder | `decoder.py` | bytes needed by the current take, the IR hold, the take and commit clocks |
| EU | `eu.py`, `templates.py` | the step list of the running instruction and its cursor, the pending data request, the count loop, the hold phases, the since-start counter |
| refresh | `refresh.py` | the free-running counter, the RFM fields, the enable delay |

plus the arbiter (`arbiter.py`), which is a function of the four machines'
state on each clock.

The fitted configuration (`validation/v35s/chains/fit.json`, the
thirty-seventh fit; the thirty-third had 208 fields, 140 integers and 20
classes when this plan was written) has 232 structural fields, 217 class
integers over 35 classes and 7 EA entries. The structural fields are the enums the fitter
enumerated; in the RTL only the chosen value of each exists. The integers
and the EA table are parameters. The EU's templates (`templates.steps`) are
per-class step lists built from the configuration; they are the microcode.

What the model does not have, and the RTL must get elsewhere or later:

- no instruction semantics beyond the register effects the templates need
  (`templates.execute`): the ALU, flags, segment arithmetic and the
  register file come from nuV30's definitions;
- no control flow (the queue flush and the fetch of a branch target are
  F23's subject, in the generator now and not yet measured), no strings
  (F24, reserved), no 0F page, no interrupts, no HALT wake;
- no reset timing: the model starts at the prelude's POP PSW read
  (`prelude_anchor=pop`) with the fetch train before clock 0 and models the
  prelude's tail; the reset exit and the slow reset clock are the core
  plan's A3;
- no internal RAM, SFR block or IDA routing beyond the SFR store's internal
  3-clock cycle (`sfr_cycle=io`) and the WTC/RFM/PRC values.

## Principles

- **The Python model is the reference, the RTL its implementation.** Every
  RTL change is checked against the model first, against silicon second.
  The RTL never carries a timing rule the model lacks: a silicon miss is
  fixed in the model (facts, enum, fit), then ported.
- **Structure is ported by hand, parameters by generator.** The chosen
  value of each structural field is written into the RTL as a mechanism
  with a comment naming the field. The integers, the EA table and the step
  lists are generated from `fit.json` into an include file, and a test
  regenerates it and diffs, so the two cannot drift.
- **One step per CPU clock, the same update order.** `Machine.run` has a
  fixed order inside a clock: completions, queue begin, EU tick, IR load,
  refresh raise, arbitrate, the post-issue reticks, end-of-clock bookkeeping.
  The RTL's combinational order inside a cycle follows it, and the clocked
  state is exactly the model's state variables. This is what makes the
  per-clock state comparison below possible.
- **Debt is listed, not hidden.** The model has situation rules (for
  example `nop_hold`, `port_issue`, `latch_start`, `io_take=unit`) that
  the "simple machines" ideal says should not exist. Phase A writes every
  one down. Each is ported as a mechanism or sent back to measurement; the
  RTL never gets a rule the list does not have.

## Phases

### Phase A: freeze and distil the fitted model

Goal: a signal-level specification of the model under the thirty-third
fit, with the unchosen alternatives gone.

- **A1. Resolved simulator.** A generated copy of `sim/` with every
  structural field replaced by its fitted value and the dead branches
  removed (`validation/v35s/chains/sim/frozen/`, produced by a script from
  `fit.json`, never edited). Gate: bit-identical bus events and per-clock
  state rows (`Machine._clock_row`) on all 19,142 runs. The resolved code
  is the text the RTL is written from. Done 2026-10-27 (`freeze.py`,
  `sim/frozen/`, `freeze --check` and `--verify`): identical on all 19,142
  runs; the code shrank 14 %, not the third expected, because the fit keeps
  most rules live and folding only removes their unchosen options.
- **A2. State table.** For each machine, every state variable with its
  range and bit width, its reset value, and the clock phase it changes on,
  from a trace of `_clock_row` over the corpus (maxima observed, with the
  theoretical bound beside). The storage count, the request flag, the
  since-start counter and the hold phases are the ones that decide widths.
- **A3. Interface table.** Every signal one machine reads from another
  (`queue.room`, `queue.flag`, `eu.req`, `bus.current`, the decoder's
  `need`, the refresh's `pending`), with the clock it is valid on. The
  arbiter is specified as a truth table over these.
- **A4. Rule register.** Each situation rule with the configuration field
  it hangs on, the runs that pinned it, the machine it belongs to in RTL,
  and a verdict: port as is, port as a cleaner mechanism (then re-fit to
  show equivalence), or re-measure. This is where the debt is paid or
  deferred, visibly.
- **Output:** [`docs/v35s-chain-rtl-spec.md`](v35s-chain-rtl-spec.md) (A2 to A4) and the frozen
  package (A1). The spec is the only document the RTL author needs besides
  the chain facts.

### Phase B: replay path for RTL against the chain corpus

Goal: run any chain image through the RTL model lane in Verilator and score
it with the same normaliser and scorer as silicon and the Python model.

- **B1. Replay driver.** `validation/v35s/chains/replay.py`: builds the
  chain's image (`image.build`), drives the existing Verilator harness
  (`fpga/v35s/sim_main.cpp`, model lane) with the chain's WTC, RFM and PRC,
  collects the lane-format trace, and feeds it to `normalize` so `score`
  and `report` read it like a corpus entry. Parallel over chains like the
  fitter's pool.
- **B2. Three-way scoring.** `score --rtl` prints silicon, model and RTL
  per cell: a run is "RTL-exact" when it matches silicon, "model-exact"
  when it matches the model. The gate for every later phase is stated as
  RTL-exact ≥ model-exact on the family, so an RTL miss where the model
  matches is a bug and an RTL miss where the model also misses is known.
- **B3. State-row comparison.** The RTL exposes its machines' state
  variables on a debug bus (simulation only, `ifdef`), and the replay
  driver compares them per clock to the frozen model's `_clock_row`. The
  first differing clock and variable is the debugging unit; bus events are
  too coarse to find a one-clock slip in a hold phase.
- **B4. Prelude handling.** The RTL runs the prelude functionally (SFR
  stores, register loads, POP PSW, the prelude marker in F18). The
  normaliser aligns at the first LS, and the `--pre` window scores the
  fetch train from the POP PSW read; both are already there for the model.
- **Gate:** the current ucore model lane (`v35s_model.sv`) replays F0 and
  the scorer reports its numbers. They will be poor; the point is that the
  path runs end to end before any new RTL exists.

### Phase C: the timing machines in RTL, one family set at a time

Each step: write the machine from the frozen code and the spec, generate
its parameters, unit-test it against state rows, then replay its families.
The order follows the fitter's stages, so each machine is checked on the
families that pinned it before the next machine can hide its errors.

| Step | RTL | Families and gate |
| --- | --- | --- |
| C1 bus unit | `v35_biu.sv`: the B1/B2/Bw/B3 sequencer and edge placement ported from the existing shell, the fitted gaps (`min_gap`, I/O recovery), the WTC fields for memory block 0 and I/O | F0, F0w: every cycle's length, start and kind exact against the model with a scripted request stream |
| C2 queue | `v35_queue.sv`: six bytes, the request rule at two free bytes, word and byte latching (`word_latch`, `latch_read`, `latch_hold`), the storage check, in-flight and arrival (`data_ready`), abort and retry after a data cycle, the back-to-back decision | F0, F2, F9, F11 with the frozen decoder and EU driven from the Python side through the state-row interface; then with the RTL EU in C3 |
| C3 decoder and register-class EU | `v35_decoder.sv`, `v35_eu.sv` with the register, immediate, prefix, shift, multiply and divide templates, the IR load and its holds, the take sync, the count loops and the unit hold, the markers (a stack write and an I/O write, so the data request path exists minimally) | F1, F2, F3, F9, F11, F12, F20 RTL-exact ≥ model-exact |
| C4 memory templates, EA and arbiter | the load, store, RMW, immediate, push and pop templates, the EA table and displacement take, the group clocks and free-clock holds, the left-out write, the I/O forms and their issue and post rules, `v35_arbiter.sv` | F4, F5, F6, F7, F10, F14, F15, F16, F19, F21, F22 |
| C5 refresh and HALT | `v35_refresh.sv`: the counter, RFM fields and enable delay, the refresh cycle in the arbiter, the EU's refresh acceptance at loop boundaries and the stall, HALT's status clocks and the END block | F8, F13, F17, F18; the refresh-off corpus must stay where C4 left it |
| C6 prelude and start | the SFR store's internal cycle, the prelude tail from the POP PSW read, the F18 prelude marker, the fetch train before the first LS | the `--pre` window on every family; F18 A |

The generated include, `fpga/v35s/core/v35_chain_params.svh`, holds the
217 integers, the EA table and the per-class step lists as localparams and
case tables, produced by `python -m validation.v35s.chains rtlgen` from
`fit.json`; `test_rtlgen` regenerates and diffs. Done 2026-10-28 (WP60):
the integer-valued structural fields as `FIT_*` (213 of the 222 fields are
read under the fit; the enum fields appear as comments, the structure being
ported by hand), the 217 class integers with `v35_cost`/`v35_cost_has`, the
EA table, 204 templates enumerated by running every opcode and ModR/M byte
through the frozen decoder under both flag states and DBNZ outcomes (one
38-bit packed word per step, operand addresses symbolic, a shift's clocks a
per-count coefficient, `v35_tmpl_sel` from a 31-bit format word over 606
formats), the bus-unit constants and the spec's A2 widths as `V35_W_*`
(test_rtlgen parses the spec's tables and compares). The spec's one width the
code contradicts is `last_fetch_end` (1 bit in A2; F23's flush reads
`t <= last_fetch_end + fgap` with fgap up to 5, so a 3-bit since-counter).

**C1 done 2026-10-28 (WP60):** `fpga/v35s/core/v35_biu.sv` (349 lines),
written from `frozen/bus.py` and the spec, with the model-lane wrapper's
strobe placement; `fpga/v35s/v35_biu_tb.sv` + `v35_biu_tb.cpp` built by
`fpga/v35s/build_biu_tb.sh` into `build/fpga/v35s/biu-tb/`; the request
stream comes from `validation/v35s/chains/rtl_vectors.py`, which runs the
frozen Machine with a wrapped clock log (the model untouched) and writes
per clock the start, the latch fills, the expected before- and after-choice
signals, the delivery and the end-of-clock state bundle. Gate: F0 and F0w
38/38 runs exact against the model, 1,095/1,095 cycles on start, length,
kind, address, width and data, 1,095/1,095 deliveries, 10,928 clocks with
no signal, state-bundle or pin failure; and the same over the whole corpus,
22,068 runs over 28 families, the RTL's model-exact count equal to the
model's in every family (re-run by the overseer, scratchpad wp60r/). Not
exercised by the corpus: an RFM write mid-run (`rfm_load`), WTC mode 3,
`min_gap` > 0. The bus unit is not yet wired into `v35s_model.sv`.

**C2 done 2026-10-28 (WP62):** `fpga/v35s/core/v35_queue.sv` (721 lines,
lint-clean under `-Wall`), written from `frozen/queue.py` and the queue's
store sites in the other frozen machines. The state is one packed struct in
the A2 representations (177 bits: storage count and 8 bytes, the
uncommitted count, the latch flags, the request flag and age, in-flight and
the 20-bit fetch pointer, the aborted cycle and retry, the holds, the
refresh flags and offsets, the next-clock commits, the this-clock flags
and the saturating start count); one model clock is a combinational chain
`q_begin` (stamps move, flags clear), phase C (`q_arrive`, or the retry
after another cycle) and phase A (the abort's end), then 16 op stages in
model order, then `q_end_clock` (the storage check and the back-to-back
decision). Every queue method is a function of the same name (`q_room`,
`q_port_busy`, `q_evaluates`, `q_requesting`, `q_latch_blocks`,
`q_triple`), every constant from the include (`V35_QUEUE_BYTES`,
`V35_QUEUE_WORD` and seven new `V35_W_Q_*` widths are new there). The ops
are the 34 sites at which the decoder, EU, arbiter and machine phase P
touch the queue (take with its ModR/M commit, commit, IR load, start,
flush, the EU's retry and shift stamps, the reads `wants_fetch` / `asked`
/ `requesting` / room / triple / stored / available, issue, abort, the
refresh drop, beat and lost rules, redate, `io_held`, `t4`, `nop_hold`),
each carrying the decoder/EU state it reads; the corpus needs at most 13
in a clock. `rtl_vectors.py --queue` records those sites by swapping the
frozen Queue's class for a logging subclass (the model untouched; it
raises on an event sequence it cannot classify, none over the corpus) and
checks the RTL state after phases C and A, after every op, at the end of
the clock and after the registered edge, plus every read. `--joint` runs
the RTL queue and the RTL bus unit together: the queue's issues are the bus
unit's fetch starts, gated by the RTL's own last `wants_fetch`, and the bus
unit's deliveries feed the queue (data cycles scripted as in C1). Bench
`fpga/v35s/v35_queue_tb.sv` + `.cpp`, built by `fpga/v35s/build_queue_tb.sh`
into `build/fpga/v35s/queue-tb/`. Gate: F0, F2, F9 and F11 678/678 runs
exact (214,100 clocks, 512,980 ops, no state, read or storage failure) in
both modes, the joint mode 20,826/20,826 bus cycles with no ungated fetch;
the whole corpus 23,612/23,612 runs exact in both modes (joint: 895,225
cycles), re-run by the overseer on the four families and the whole joint
corpus (scratchpad wp62r/). Twelve places where the frozen code and the
spec disagreed are in the spec's Decisions ("C2, the queue in RTL"); the
largest: the storage holds 8 bytes inside a clock (4-bit count), the
latched byte is uncounted on its delivery clock only with the port held,
and `abort_t`, `after_refresh`, `io_held`, `retry_at` and `shift_until`
need more than A2's bits. C3 drives the decoder and EU from the Python side
still; the queue's `rd` outputs are what they will read.

**Gate for Phase C:** whole-corpus RTL-exact equals model-exact (22,771 of
23,612 under the thirty-seventh fit) with the state rows identical on every
clock of every run.

### Phase D: function

The chain model fixes when each step happens; this phase makes the steps do
the right thing. It is the core plan's Phases 3 to 5 with the chain
sequencer in place of a cost table.

- Register file and PSW in internal RAM (`v35_iram.sv`), with the access
  cost the model's `wb` and `nx` integers imply; the core plan's open
  question (one port or two) is answered by the fitted `reg` and `imm`
  templates, which have no separate register-access clock.
- ALU and flags from nuV30 (`instructions.json`, flag notes), driven by the
  sequencer's `alu`/`exec` steps; the SingleStepTests adapter of the core
  plan runs through the replay harness.
- Segment arithmetic, the IDA routing and the SFR block for WTC, RFM, PRC.
- **Gate:** the chain corpus unchanged (Phase C's gate holds), the directed
  programs (`smoke`, `clocks`, `alu`) match on the board with `--mode both`.

### Phase E: extend, model first

Every extension follows the standing rule: chains and facts, an enum in
`sim/config.py` with the old behaviour as default, a fit with nothing lost,
then the RTL. In the order the generator gains them:

1. F23 control flow (in the generator now): the flush, the target fetch
   and the restart; the queue's abort path already exists for data cycles.
   Done 2026-10-28 (five classes, six enums, 255/360; the thirty-fifth fit,
   docs/v35s-chains.md); the probe families F26 and F27 of the spec's
   decisions were acquired the same day, F26 exact under that fit and F27
   fitted that evening (the thirty-sixth fit, 778/1,072: the I/O sequencer's
   steps under a refresh, four fields and two values, F8/F13/F17 gaining).
   F28 and F29, probing that fit's open states, were acquired and fitted the
   same day (the thirty-seventh fit, WP61: eight enums, F28 820/1,088, F29
   427/456, 22,771/23,612, no integer changed); one of them, `grp_disp`,
   adds queue state the C2 RTL lacks (`gdisp_until`), a follow-up in WP63.
2. F25 LDEA, XLAT, PUSH imm, PUSH R and POP R, PREPARE and DISPOSE, the
   segment pushes and moves: the EA step alone, stack bursts, the segment
   write-back. Done 2026-10-27 (ten classes, three enums, 446/588; the
   thirty-fourth fit, docs/v35s-chains.md); item 1 follows it.
3. F24 strings and REP, INM and OUTM: sustained data demand through the
   arbiter.
4. The 0F page: a second opcode byte in the decoder.
5. The register miscellany (INC and DEC r16, flags, adjusts, CVTBD and
   CVTDB, signed multiply and divide, IMUL with an immediate).
6. Interrupts, the register banks and the V35 instructions: the core
   plan's Phases 5 and 6, each measured before coded.

## Verification

| Level | Tool | When |
| --- | --- | --- |
| frozen model = model | `frozen` package against `sim/` on the corpus, events and state rows | every fit |
| RTL machine = frozen machine | per-machine Verilator unit bench fed and checked by state rows | every RTL change |
| RTL run = silicon | `replay.py` and `score --rtl`, RTL-exact ≥ model-exact per family | every RTL change, full corpus at a step's gate |
| parameters = fit | `rtlgen` regenerate and diff | every test run |
| board | `acquire` on the model lane against the socket lane for a family | each phase gate |

## Risks

- **The situation rules.** About a dozen fitted fields are per-situation
  holds and reissues rather than machine structure. Ported literally they
  make the RTL as hard to read as the model's `Machine.run`; cleaned up
  without a re-fit they break the gate. Phase A4 forces a decision per
  rule before any RTL is written, and the frozen model makes a cleaner
  equivalent testable in Python first.
- **The model's miss set.** 181 runs miss today (175 refresh-on, six F22).
  The RTL inherits them. They are not RTL work; they stay in the facts
  record as open states.
- **Reset and the prelude.** The chain model starts at the POP PSW read.
  The RTL must reach that read with the same queue and bus state from a
  real reset, which the probes (A3 in the core plan) measured but the
  chain model has not fitted. C6 is where this shows; a mismatch there is
  measured with a new family, not patched.
- **Internal RAM port count.** If register accesses need a bus-visible
  cost the templates do not carry, Phase D's gate fails on the directed
  programs while the chain corpus still passes; the probes M3 in the core
  plan settle it.
- **Block RAM and timing.** The queue and the step tables are small; the
  register RAM is one block. The scope's depth remains the build option
  the core plan names.
- **Two models.** `validation/v35s/model/` and the chain model both exist.
  The chain model is the one this plan converts; the older model and its
  probe corpus stay as a second check until Phase D, then are retired as
  the core plan said of the ucore.

## Order against the current work

Phases A and B need nothing from F23 or F25 and can start now, in
parallel with the acquisition and modelling of the new families. Phase C
starts after A and B gate, on the thirty-third fit or whichever fit is
current, and takes the new families' rules as Phase E items when their
fits land. The RTL is never ahead of the model.
