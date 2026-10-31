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
  Since 2026-10-31 the chain core does this itself in the lane (WP82,
  "The chain core in the model lane" in Phase C): `replay --core chain
  --score` reports the three marks and the pre window per family.
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
EA table, 204 templates (212 since C3, see below) enumerated by running every opcode and ModR/M byte
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
the A2 representations (177 bits, 180 with `grp_disp`'s stamp: storage count and 8 bytes, the
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

**C2 follow-up (2026-10-28, WP63):** the thirty-seventh fit's `grp_disp=hold`
gives the queue a stamp the C2 RTL lacked, `gdisp_until`; `v35_queue.sv`
gained `gd_valid` + `gd_off` (the state is 180 bits now), the op
`V35_QOP_GDISP` (the EU's store), the width `V35_W_Q_GD_OFF`, and the
recorder classifies the store; the arbiter's read is state only, as for
the other arbiter-read stamps. Queue and joint gates again exact over the
whole corpus (23,612/23,612, joint 895,194 cycles). Under this fit no run
holds 8 bytes inside a clock any more (the peak is 7); the RTL keeps its 8
entries.

**C3 done 2026-10-28 (WP63):** `fpga/v35s/core/v35_decoder.sv` (package
`v35_decoder_pkg`, 155 lines: the decoder's state `v35_dec_t`, 55 bits,
the queue view the EU reads, the bus view, and the decoder's bookkeeping
as functions) and `fpga/v35s/core/v35_eu.sv` (module `v35_eu`, 1,783
lines, lint-clean; state 516 bits = decoder + EU `v35_eus_t` 218 bits +
three request records of 81 bits, the slot and two queued, in the A2
representations). One clock is `eu_begin`, phase C (the fetch-done
count), T (`eu_tick`), L (`dec_load_ir`), X (the arbiter's touches,
`V35_XOP_*`: issue, nowrite, fetch_start, sync_one, free0, not_before), P
(`mach_post`: the second tick and IR load) and E (`latch_start`), the
bundle exposed after each phase and registered. Every EU and decoder
method is a function of the same name; the templates come from
`v35_tmpl_sel` and the step words of the include; the queue ops the EU
emits are C2's codes (`V35_EQ_*`). The register file and the EA adder are
Phase D: the bench supplies per start an operand record (EA, port, stack
addresses, shift count, bytes taken and target) and AW as write data; the
arbiter's choice, its EU touches, the requests' setup counts and
`disp_io`'s extension are scripted from the Python side (C4); refresh-on
runs raise NotModelled (C5). `rtl_vectors.py --eu` runs the frozen Machine
with the EU, Decoder and each Request's class swapped for recording
subclasses and the arbiter and `eu.execute` wrapped (the model untouched;
any unclassified touch raises, none over the refresh-off corpus); `--joint3`
runs the RTL EU, queue (NSLOT 40) and bus unit together, the C++ chaining
T/L ops, the scripted X ops and P ops into the RTL queue, feeding its
per-op states back into the EU to a fixpoint, the bus unit running the
queue's fetches and the EU's data cycles. Bench `fpga/v35s/v35_eu_tb.sv` +
`.cpp`, `fpga/v35s/build_eu_tb.sh`, binary in `build/fpga/v35s/eu-tb/`.
Gate (re-run by the overseer, scratchpad wp63r/): F1, F2, F3, F9, F11,
F12 and F20, 5,352/5,352 runs exact against the model in both modes
(1,820,123 clocks, 140,460 starts, 1,052,684 queue ops, no state, op,
data-cycle, queue, bus-unit or ungated-fetch failure; joint 182,412/182,412
bus cycles), RTL-exact = model-exact in every family. Stretch: every
refresh-off run of the corpus exact, 19,850 runs (the overseer's `--eu`
run over all 30 family lists: 6,783,501 clocks, 509,753 starts, no
failure, model-exact 19,565 = RTL-exact 19,565; the agent's `--joint3` run
the same 19,850 exact), F22 1,314, F23 255 and F25 446 among them and the
refresh-off parts of F13/F17/F18/F27/F28; the 3,762 refresh-on runs not
modelled. `rtlgen` gained `started()`: the templates
are enumerated after `_start`'s own class changes (CMP r/m,reg and the
nowrite forms to `grp_class`), 212 templates over 630 formats now (204 /
606 before; three memory nowrite formats had no template). Fourteen places
where the frozen code and the spec disagree are in the spec's Decisions
("C3, the decoder and the EU in RTL"); the largest: the start decodes the
format from the operand bytes (the model reads the image), `start_clock`
and `resume` need wider offsets, the requests are logical positions that
shift on promote, and `done_t`/`wb_until` need four fields. The queue
module exposes its per-op state only under `V35S_STATE_DUMP`; a
synthesizable core needs it exported to the EU (C4).

**C4 done 2026-10-28 (WP64):** `fpga/v35s/core/v35_arbiter.sv` (module
`v35_arbiter`, 742 lines, lint-clean; `arbitrate`, `_choose`,
`_fetch_first`, `_fetch_run` and the request's `counts`/`ready`/`holding`
as functions of the same names) and the core top
`fpga/v35s/core/v35_chain_core.sv` (476 lines), which instantiates the bus
unit, the queue (NSLOT 40), the EU with the decoder and the arbiter and
chains the clock's phases in RTL: the EU's T/L queue ops, the arbiter's X
ops and the EU's P ops are one op chain in the queue, and what one machine
reads of another that is computed later in the same clock (the queue's
state before each op and each read, the arbiter's touches, cycle and
counts, the bus unit after the choice, the queue's phase-E `latch_in`)
passes through settle registers that every fast-clock edge re-evaluates;
`settled` is "next equals current", `run && settled` is the machines'
`ce`. The corpus needs at most 6 settle edges per model clock (mean 1.25).
The memory, immediate, push, pop and I/O templates, the EA table and the
group and free-clock holds the table above lists under C4 were already in
C3's EU; C4 adds the arbiter's decisions, the setup counting and
`disp_io`'s extension, so nothing timing-related is scripted any more.
The arbiter owns 69 bits of state (`v35_ast_t`): per request position
(slot, two queued, shifting on a promotion) the setup count, an 8-bit
saturating post age, and `ready_since`, `lift_t`, `free_held`, `grp_held`
as "== t" flags; plus the fetch-run flag and a 4-bit age of the last I/O
start. Interface-only changes to C2/C3: `v35_queue_pkg` and `v35_eu_pkg`
packages; the queue's `state_c`/`state_op`/`state_e` and the EU's
`state_l`/`state_e`/`fresh_l`/`fresh_p` are ports always (only the dumps
stay under `V35S_STATE_DUMP`); `rtlgen` adds `V35_PRELUDE_POP_ADDR` and
`V35_PRELUDE_PSW` for the POP PSW read the core starts on clock 0. On the
Python side `rtl_vectors.py --core` wraps `arbitrate` around the EU
recorder (`ArbiterRecorder`: classifies the arbiter's stores, raises on
any other and on a take sync below the completed count; none over the
refresh-off corpus), writes format V35ARB-1, and the bench checks the EU
after every phase, every op in the chain word by word, the queue's state
after every op, the arbiter's touches and state, the bus unit's signals
and the core's error codes and settle count; four built-in mutations
(the `arbiter=b2b` choice, the `hold_q` comparison, the `disp_io`
extension, `dw_count`'s give-back) are each caught by the bench
(`test_rtl_vectors.CoreBench`). Bench `fpga/v35s/v35_core_tb.sv` + `.cpp`,
`fpga/v35s/build_core_tb.sh` (`LINT=1` lints the core alone), binary in
`build/fpga/v35s/core-tb/`. Gate (re-run by the overseer, scratchpad
wp64r/): F4, F5, F6, F7, F10, F14, F15, F16, F19, F21, F22, F26 and F29,
12,642/12,642 runs exact against the model (4,333,778 clocks, 443,384
bus cycles, no failed check), RTL-exact = model-exact in every family
(12,607). Stretch: the whole refresh-off corpus, 19,850 runs exact over all
30 family lists (6,783,501 clocks, 689,895 bus cycles, model-exact 19,565 =
RTL-exact 19,565); the 3,762 refresh-on runs not modelled (C5). The C1,
C2 (`--queue`, `--joint`) and C3 (`--eu`, `--joint3`) gates re-run exact
after the interface changes. Twelve places where the frozen code and the
spec disagree are in the spec's Decisions ("C4, the arbiter in RTL"); the
largest: the arbiter holds state A2 put in the other machines, `posted`
needs a saturating age rather than order flags, the fetch run is one flag
over the bus unit's `fetch_end_prev`, and the abort compares the fetches
still owed rather than the absolute sync. Still scripted (Phase D): the
operand record per start, the EU's write data and the memory. Not
modelled: refresh (C5), the prelude tail before the POP PSW read and the
reset (C6).

**C5 done 2026-10-29 (WP65, WP68):** `fpga/v35s/core/v35_refresh.sv`
(module `v35_refresh`, 154 lines: the edge counter on bit RFT+3 from
`FIT_REFRESH_INTERVAL`, RFEN and RFT from the RFM value, `pending` set in
R and cleared by the arbiter's start in X, the RFM store taking effect
`FIT_RFM_DELAY` clocks after its issue through `rfm_load`/`rfm_value` into
the bus unit; `en` and `init_counter` (the prelude's POP counter) are
inputs; R and X are separate processes), the arbiter's whole `_refresh`
path (`_winner` with `fetch_first`, `refresh_halt`, `step_lead`,
`refresh_lead=closed` and `lead_port=last`, `refresh_relatch`,
`refresh_io_step`, `refresh_wlatch`, `refresh_ok`, abort / drop_post /
drop / lost, `early_ok`, the beat and `refresh_cost`, `halt_defer`,
`lost_start`/`lost_after`, `halt_refresh=run_drop`, `refresh_lift=free`,
`refresh_after=fetch_next`, `io_step_issue`, `refresh_beat_t4` and
`_b2b`, `post_beat`'s give-back, `dw_view=eu`) and the EU's refresh rules
(`refresh_eu=hold` with `refresh_retry` and `refresh_wb=free_wait`,
`refresh_reraise=unit`, `shift_exit0`, `refresh_sync=run` with its
`run=two` and `reg=delivery` limits, `clk_seam`/`clk_tag`/`clk_end` with
`refresh_start_seam=start`, the HALT queue op under `halt_refresh`, the
early start rules, `refresh_run_modrm`, `pop_refresh=stall`; the package
holds the step functions and the boundary map `eu_boundary`, `eu_in_loop`,
`eu_rmw_*`, `eu_inside`). The core instantiates the controller, drives the
bus unit's RFM load from it, takes `refresh_on` and `init_counter` as
inputs, and a refresh cycle's datum is 0. State: the controller 24 bits;
the arbiter 69 → 103 (`xeu` per request position, the bus history
`early_on`/`early_ok`/`early_n`, `after_ref`, `lc_age`, `rf_v`/`rf_n`/
`rf_age`); the EU 516 → 582 (`prev_cls`, `sfr`, `rmw`/`rmw_cl`, the
clock-tag and seam fields, `ce_off` 11 bits signed, the hold/halt
offset-plus-past pairs; `sa_off` 5 bits signed, `v35_req_t` gains `grpcl`
and `beat_ext`); the touch word is a 4-bit code plus 8-bit value and NXOP
6. `rtl_vectors.py --core` models refresh (`--eu`/`--joint3` stay
refresh-off and raise NotModelled on a refresh run); a `RefreshRecorder`
classifies the controller's stores and raises on any other; format
V35ARB-2 adds `refresh_on`, `init_counter` and the R lines; five refresh
samples (F8, F17, F18, two F13 RFM runs) and three more mutations (lead
closed off, `refresh_after` off, the `dw_view` t−2 add off) in
`test_rtl_vectors`. Gate (re-run by the overseer on the live tree after
fit 38, scratchpad wp65r/): F8, F13, F17, F18 2,472/2,472 exact against
the model (961,646 clocks, 115,144 bus cycles, no failed check,
model-exact 2,364 = RTL-exact); F27 and F28 2,160/2,160 (model-exact
1,709 = RTL-exact); the whole corpus over all 31 family lists 23,678 of
24,524 exact and the other 846 not modelled (the F24 runs with a string
form, Phase E item 3; 8,359,539 clocks, 897,465 bus cycles, model-exact
22,837 = RTL-exact 22,837, at most 6 settle edges per clock, mean 1.25);
C1 38/38, C2 2,040/2,040 in both modes, C3 5,352/5,352 in both modes, C4
12,642/12,642 unchanged; the eleven test modules 534 OK; `LINT=1`,
`rtlgen --check` and `freeze --check` clean; `fit.json` and `sim/frozen`
untouched by the RTL work. Eighteen places where the frozen code and the
spec disagree are in the spec's Decisions ("C5, refresh in RTL"); the
largest: the model's two kinds of "refresh off" need a static
`refresh_on` input, `pop_refresh=stall` (marked C6) fires in ten F13 runs
and makes `sa_off` signed, `refresh_cost`/`refresh_ok` are computed in
the arbiter and reach the EU as touches, and `io_step`'s three-cycle
look-back is kept as saturating ages. WP68 (the same day): with fit 38
adopted, `rtlgen` leaves the seven `str_*` classes out of the step tables
(`string_classes`; their class ids and costs stay in the include, XLAT
moving from 34 to 41) and every `rtl_vectors` mode reports a run with a
string form as not modelled, "string forms (E3)". Still scripted
(Phase D): the operand record per start, the EU's write data and the
memory. Not modelled: the prelude tail before the POP PSW read and the
reset (C6), the string forms (E3).

**Gate for Phase C:** whole-corpus RTL-exact equals model-exact (22,771 of
23,612 under the thirty-seventh fit) with the state rows identical on every
clock of every run.

**D1 done 2026-10-30 (WP69):** the register file, the operand record and the
write data are the RTL's own. The register file lives in the EU
(`v35_eu.sv`, `v35_rf_t`, 180 bits: AW CW DW BW SP BP IX IY DS1, Z with a
valid bit, one held return address with its SP, the DS1-prefix bit), preset
from the chain's registers as the model's is. At each start, inside
`eu_start` as in the model's `_start`, the EU decodes the instruction from a
12-byte code window at the end-of-clock pc (the bench serves it, since the
model decodes from the image; a start moves pc by at most 6 in a clock and a
flush empties the IR), computes the operand record with `v35_operands` (the
EA of all 24 ModR/M modes, the direct forms, XLAT's BW + AL, the
DS1-prefixed SFR store's linear address; the port byte or DW; the stack
addresses of push, pop, call, ret, PUSH R/POP R, PREPARE, DISPOSE from BP,
the segment pushes and PUSH/POP r/m; the shift count, C1's byte, 1, or the
full CL; F23's taken flag and target from Z, CW, the displacement or the held
return address) and applies the register effects with `v35_execute`, every
case of `templates.execute`, so a second start in the same clock reads the
updated registers. Every EU cycle's datum is the RTL's AW at phase X, the
model's `regs["AW"]` at issue; nothing is scripted per class any more, and
the core's `opnd_a/opnd_b` and `eu_data` inputs are gone (`code_addr` and
`code_win` replace them; `opr_*`, `rfx_*` and `x_data` are dump outputs).
EU state 582 → 762 bits, the arbiter's `ESTATE_W` following. Gates (the
overseer's re-run under the thirty-ninth fit, scratchpad wp7069r/): the
whole corpus 23,678 of 24,524 exact and 846 not modelled (string forms),
with 613,481 starts each checked for its operand record, the register file
after it and every EU cycle's datum, model-exact 22,837 = RTL-exact; C1
38/38, C2 2,040 in both modes, C3 5,352 in both modes (140,460 starts, the
`--eu` and `--joint3` benches computing the record too), C4 12,642, C5
2,472 and 2,160; the new `--regfile` mode (`v35_rf_tb`, `build_rf_tb.sh`)
runs 39,188 vectors against `execute`, 22,318 from walking the chains,
15,958 random register files and 912 covering every memory mode, 0 bad;
three register-file mutations (an EA without IX, a push's SP step of 4, a
byte immediate into the high byte) each caught. Twelve places where the
frozen code and the spec disagree are in the spec's Decisions ("D1, the
register file in RTL"); the largest: the datum of every EU cycle is AW, every
memory read returns the data fill (`V35_FILL_WORD`) and delivered data never
reaches a register, the segment registers are never written, RET's target
is the CALL's held entry (one, the corpus maximum; `V35_EE_RF` on a second),
and Z is set by CMP r16,r16 alone. Left for D2: the full PSW from nuV30 for
every ALU form, real read data into the registers and real write data per
form, signed MUL/DIV and the divide traps, the segment registers. Still
scripted: the code window, the fetch words and the delivered words (memory).

**D2 done 2026-10-30 (WP71):** the EU computes. `v35_eu_pkg` gains the ALU
(`v35_alu`, `v35_shift`, `v35_mul`, `v35_div`, `v35_szp`, `v35_cond`) with
nuV30's semantics, the undefined-flag notes included, and the full V35 PSW
in the register file (`v35_rf_t` 211 bits: the eight registers, PS SS DS0
DS1, PSW, a 3-bit prefix; initialised to F002h, the POP PSW keeping bits
15–12); every memory read's datum reaches the register file or the ALU at
its delivery (`v35_deliver`, the new `v35_fx_t` in flight, 86 bits), every
write's datum is the form's own (`v35_wdata`: the source register, the ALU
result, the immediate, the segment register, CALL's real return address
`code_org` + pc + 3); real segment arithmetic (segment base + offset for
data, SS for the BP modes and the stack, the prefix's segment, PS's base +
`code_org` for code; the frozen "DS1 store becomes linear only at or above
the SFR page" rule is replaced and gives the same address on all 635,078
starts); RET's target from the stack read, so the held return entry is
gone; `eu_decode` accepts all sixteen Bcond; the divide error is `V35_EE_DIV`
and a form whose function is not built `V35_EE_FUNC` (F6/F7 /1, FF /2–/5 and
/7, the register forms of F6/F7 /2 /3, FF, 8F, C6/C7, 8F /1–7, MOV PS,
PREPARE with a level). The checking reference is new: `funcref.py` executes
the chain's instruction stream with real data (the image written by the
chain's own stores, the prelude's push, I/O reads 0000h as the board
answers) and asserts on every start that every quantity the timing depends
on equals the frozen `execute`'s; over the whole corpus 635,078 starts agree,
and every data cycle's datum matches the silicon record's on its lanes
(91,980 of 91,980: an odd byte on D15–8, an odd word as two byte cycles, the
low byte on the first's high lane). The benches compare the RTL's register
file before every start, every EU cycle's datum and the final state against
funcref. SingleStepTests (the V20 `v1_native` suite at revision 6b3748f9,
fetched by `tools/fetch_sst_v20.py` into build/deps/sst-v20/, run by
`sst.py`): funcref 1,693,875 pass, 0 fail; the RTL through the rf bench
1,651,237 pass, 0 fail, the rest counted apart as expected differences (the
divide traps, 24,387, every trap condition agreeing; the `V35_EE_FUNC` forms,
92,647; the on-chip page FFE00–FFFFF, 448; a REP prefix on a non-string
form, 1,340; PREPARE with a level, 1,941). Gates (the overseer's re-run,
scratchpad wp71r/, over 33 lists with F30 and F31): 24,542 of 26,234 runs
exact against the model and 1,692 not modelled (string forms), model-exact
23,389 = RTL-exact, the 31 earlier lists as before (23,678, 846, 22,837);
funcref over the 33 lists 679,829 starts agreeing and 99,834 data cycles
matching silicon; C1–C5 unchanged; `--regfile` 58,508 vectors (walk 26,164,
random 16,968, modes 912, alu 14,464), 0 bad; mutations 8–13 caught (an ALU flag, a write datum,
a BP-mode segment among them); 587 tests OK. State: `v35_st_t` {d, e, f, x,
r} 879 bits, the arbiter's `ESTATE_W` following; the core's `code_base`
input becomes `code_org`. Twenty decisions in the spec ("D2, the EU
computes"); among them the state rows leave the `f_*`/`x_*` fields out of the
per-phase comparison (the RTL updates them at the delivery, not at the
model's start), OUT's datum is AW at the issue, the SFR store drives its
immediate, V20 behaviours adopted where the suite decides (C6/C7 ignore
reg, 8C/8E use reg & 3, shift /6 is SHL), POP R reads SP's slot (the V35
does, the V20 does not). Still scripted: the code window, the memory image
(the bench's array, updated by the RTL's writes), the I/O read value and the
initial register file. Not built: the trap sequence, the string forms (E3).

**E3 and the fortieth fit's catch-up done 2026-10-30 (WP75):** the string
forms run in RTL and the RTL has every mechanism of the fortieth fit. The
whole corpus under `--core` (33 lists, 26,234 runs; the overseer's re-run,
scratchpad wp76r/) is 26,234 exact against the model, 0 not modelled, 0
differing, model-exact 24,710 = RTL-exact (the baseline at the adoption was
24,183 exact, 1,692 not modelled, 359 differing); C1–C3 as before, `--regfile`
58,508 vectors 0 bad, funcref over the 33 lists 679,829 starts agreeing and
99,834 silicon cycles matching, SST 1,693,875 (funcref) and 1,651,237
(`--rtl`) pass; mutations 14–23 (each fit-40 enum off, the string element's
address step, the overrun read, the compare exit) caught on their deciding
runs; 605 tests. The string forms: a REP form's element count comes from CW
and a compare's exit from the RTL's own data at the deciding element's last
read (the model takes both from the normaliser's walk at the start, so
`x_sn`/`x_sc` are checked at the next start against the walk's values, not
per phase); addresses are segment base + offset (DS0 or the prefix's segment
for the source, DS1 for the destination) and honour DIR, identical to the
model's linear upward stepping on the corpus; IX, IY and CW update at the
start for the non-compares and at the decision for REP compares; `e.k` is the
model's flat step index (18 bits), the compact template holding the rows for
elements 0, 1 and ≥ 2 with the `last` clocks from `V35_C_*_LAST`; OUTM's I/O
write fills the data latch from the EU (`wl_fill_x`). The fortieth fit's
mechanisms: `cond_gap=own` needed the bus unit's `fetch_since` counter
widened to 4 bits (it saturated at 7 where the flush waits 8 clocks after
the last fetch; rtlgen's width check now includes `cfgap`, which it had
also dropped from the flush step as a third element); `xfer_abort`'s store is
folded into the queue's ABORT op; `lea_ea` and `str_held`, never cleared in
the model, are a valid bit plus an offset in the queue (`V35_QOP_LEA_EA`,
`V35_QOP_STR_HELD`); `prepare_sync=run` sets one fetch owed, assuming
completed = sync (C4 decision 5, the recorder raising otherwise); C5
decision 15's `io_stall` (nowait and refresh on) now also requires an I/O
kind, since string and PUSH R requests are nowait too (`dwlike`). The
`dispose` class had not left the step tables: with `dispose.setup` 7 its
template equals POP's and the table dedupes it, so `test_rtlgen` now reads
classes from the format words. Widths: `v35_st_t` 958 (`e.k` 18, `v35_fx_t`
151 with `sn`, `sc`, `six`, `siy`, `sseg`), the queue's state 187, the bus
unit's bundle 65 and view 19, `mutate` 5 bits, vector format V35EU-4 (each
P line ends with string form, elements, cond), 239 templates. Still scripted:
the code window, the memory image, the I/O read value, the initial register
file. Not built: the trap sequence, the 0F page (F32), REPC/REPNC (F33),
interrupts, and the forty-first fit's nine mechanisms (adopted the same
evening, the next catch-up).

**The forty-first fit's catch-up done 2026-10-30 (WP77):** the RTL has the
nine F30/F31 mechanisms (`xfer_odd`, `str_exit`, `str_split`, `str_io_setup`,
`str_start`, `str_fetch`, `sreg_io`, `sreg_store`, `lea_disp`) and decodes
REPC/REPNC (64/65) as REP prefixes, the compare ending on CY. Whole corpus
`--core` over the 33 lists (the overseer's re-run, scratchpad wp78r/): 26,234
exact against the model, 0 not modelled, model-exact 25,423 = RTL-exact;
C1–C3, `--regfile` 58,508 vectors 0 bad, funcref and SST unchanged; mutations
24–32 (one per enum) caught on their deciding runs, each silicon-exact
unmutated; F33's four REPC/REPNC runs exact against the frozen model through
the core bench with the STC/CLC replaced by a NOP (`test_repc_repnc`). Two
structural changes: `rtlgen` now reads the structure, costs and EA table from
the frozen package (`rtlgen.fit_config()`) and refuses to run when
`fit.json`'s sha256 differs from the frozen `FIT_SHA256`, so live model edits
(WP78's 23 classes broke the 6-bit class field) no longer disturb the RTL side
mid-package; and `rtlgen.UNBUILT_CLASSES` leaves the F32/F33 classes'
templates, ids and integers out of the include (a chain instruction of one is
"not modelled") until they are built. The step encoding gains the ops
`fetch_release` and `split_floor` (16 ops, still 4 bits) and the tags
`forever` and `raise` (16 tags); the compact REP template is head (2 rows),
CW = 0 rows (2), a pre-element row (`fetch_release` forever), 3 × m element
rows, a tail (`fetch_release` xfetch, `split_floor` except after LDM/CMPM),
`rexit`, `cexit`, every exit less `xwb`; `v35_str_shape` is 6 bits {t, m, c};
the STEP_K width check leaves the REP compact templates out (their cursor is
the 18-bit flat `e.k`). Widths: `v35_st_t` 985 (`v35_eus_t` gains `sreg` 2,
`lea_split`, `nw_tv`, `nw_age` 3, `nw_ran`, `ls_split`, `ls_age` 3;
`v35_req_t` gains `sreg_held`, `sreg`, `li_age` 3), queue state 197 (`sd_off`
4, `sd_inf`, `sr_valid`, `sr_off` 3, `ox_valid`, `ox_now`, `ox_fed`), arbiter
state 112 (`so_v`, `so_now`, `sa_v` per position), bus view 20 (`run`: the
arbiter's registered back-to-back flag, a new `run_r` output), `mutate` 6
bits; queue op `V35_QOP_STR_RAISE` 38, `STR_HELD`'s a bit = infinite,
`START`'s b bit = odd_xfer. Thirteen decisions in the spec ("The forty-first
fit's catch-up"). The baseline before the mechanisms could not be measured
per run: the frozen arbiter's `sreg_at` store on every request becoming ready
was unclassified by the recorder, so every run read "not modelled" until it
was. Still scripted: the code window, the memory image, the I/O read value,
the initial register file. Not built: the trap sequence, the 0F page and the
register miscellany (F32/F33, `UNBUILT_CLASSES`; the forty-second fit,
adopted the same day, changes nothing on the 33 gate lists), interrupts.

**The 0F page and the register miscellany built 2026-10-30 (WP79, Phase E
items 4 and 5):** all 23 F32/F33 classes are in RTL and
`rtlgen.UNBUILT_CLASSES` is empty. Whole corpus `--core` over the 35 lists
(the overseer's re-run, scratchpad wp79r/): 28,142 exact against the model,
0 not modelled, model-exact 26,643 = RTL-exact (F32 858/858 with silicon 379,
F33 1,050/1,050 with 841; F34's 1,596 runs exact too, 469 silicon-exact on
both sides); C1–C3 unchanged, `--regfile` 69,099 vectors 0 bad, funcref
29,738 runs over 36 lists 0 disagree (INS's written data and the BCD results
included), SST funcref 2,044,304 and RTL 2,001,666 pass with 62 more V20 files
(the BCD, bit-field, adjust, convert and digit-rotate suites); mutations 33–38
(the BCD pair step, `bf_count`, the bit index, the BCD carry, the bit-field
offset step, the 0F second byte at the ModR/M latch) caught on their runs,
each exact unmutated. Structure: the EU's `e.cls` holds the base class
(`templates.BASE_CLASS`, generated as `v35_base_cls`: the rules see it) and
a new `e.ccls` the class's own (every cost read of the running instruction);
the 0F form's ModR/M, displacement and immediate are read through
`v35_mcode` with the first byte dropped, the second byte skipped at the
decoder's ModR/M latch (`skip`), `nx0` loading `ra_off` for the one-byte
forms; the BCD strings are a compact template (head, pair 0, pair ≥ 1, exec)
the EU expands by (CL + 1)/2 pairs, the count checked at the next start
against the walk's as a REP's is, addresses always stepping up; the bit
fields carry the formula's clocks in a `bf`-tagged step (n = span or xspan)
that the RTL computes with `v35_bf_cost` (ported from `templates.bf_cost`),
the crossing a format field from the whole registers (o + w ≥ 16), and the
record's `bfc` checks the cost at every start. Data paths read off the V20
suite where silicon is silent: BCD flags carried pair by pair (S = AC = CY,
P = Z, V = 0, the carry the high digit's adjust decision: 2,000/2,000 where
nuV30's binary carry fails 1,930); bit-field flags SUB8(15, o + w) for EXT
and SUB8(15, o + w + 1) for INS, INS stepping its offset register before
reading AW, EXT re-stepping it after writing AW (20,000/20,000); ADJ4A/ADJ4S
a high threshold of 9Fh with AC set, else 99h, ADJBA/ADJBS stepping AH with
no carry from AL (10,000/10,000); CVTBD by 0 does not trap (AH = FFh);
CVTDB multiplies by 10 whatever its immediate. Where silicon speaks it wins:
ROL4/ROR4 keep AL's high digit as the data book says (F32's OUT writes
AL = 08h; the V20 differs, 18,368 SST tests set apart as "V20's ROL4 / ROR4
AL" and passing under a `v20_digits` switch); INS with offset 0 and width
field 15 reads the word in model, funcref and RTL where the V20 does not
(82 tests "unlisted"). funcref's `frozen_walk` lacked the REPC/REPNC and BCD
counts and is keyed as the frozen machine is. Widths: `v35_st_t` 1021
(decoder + 5: nx 3, `ra_off` 5, `skip`; EU + 12: cls 7, `ccls` 7, tmpl 9,
`res` 11, `prev_cls` 7, `ce_off` 12, an INS with whole registers reaching
1,998 cost clocks), `v35_fx_t` 167 (`bfo`, `bfw`), `v35_opnd_t` 212 (fmt 33
with `cross`, tmpl 9, `bfc` 12; `opr_a`/`opr_b` [211:0], no new ports),
`CLS_NONE` 127, `V35_CLS_N` 65, `V35_TMPL_N` 330, `STEP_W` 39 (tag 5 bits),
`V35_W_CLS` 7, `V35_W_NX` 3, `V35_W_RA_OFF` 5, `V35_W_BF_COST` 12;
`v35_bcd_shape`, `V35_BCD_HEAD`/`SETS` in the include; the rf vector format
V35RF-3. Bit-field data for registers above 15 stays unprobed (the corpus
and the suite stop at 15; silicon's FFFFh write with DL = 78h is not nibble
data). Still scripted: the code window, the memory image, the I/O read
value, the initial register file. Not built: the trap sequence,
interrupts.

**The chain core in the model lane, 2026-10-31 (WP82, Phase D3 and the
start of C6):** `fpga/v35s/build_sim.sh direct chain` builds the Verilator
harness with the chain core in the model lane (`core/v35s_chain_model.sv`
wrapping `v35_chain_core.sv` built with `V35S_CHAIN_LANE`, the ucore build
and every core bench unchanged; binary
`build/fpga/v35s/verilator-direct-chain/`), and `acquire --backend sim
--core chain`, `replay --core chain` and `replay --core chain --score` run
and score it (output `build/validation/v35s/chains-sim-chain/`, the header's
`"core": "chain"`; `--diag` prints the lane's diagnostics). Nothing is
scripted: the core leaves reset, fetches the reset vector at FFFF0h (PS
FFFFh, IP 0, not F000h:0000h), runs the image's prelude, and every fetch,
data and I/O cycle is a bus cycle whose data the core itself latched. The
wrapper adds the clock (one bus state per CLKOUT = X1/8 at reset, PRC.PCK
at the prelude's store; a model clock ends at a state's start and its
strobes sit mid-state, 8 edges per state at fX/2 against the core's worst
settle of 6), the reset exit as parameters from docs/v35s-bus-timing.md
"Reset" and docs/v35s-core-decision.md A3 (`RESET_REFRESH_STATE` 15,
`RESET_FETCH_STATE` 25: the wrapper drives the one reset refresh, the core
is held in reset until the state before the first fetch's B1 and its
counter continues that refresh's grid, `INIT_COUNTER` 18), the SFR block
`core/v35_sfr.sv` (PRC, WTC, RFM, IDB at IDB:F00–FFF and FFFFFh, reset 4Eh,
FFFFh, FCh, FFh, written at the SFR store cycle's end; only the RFM store
reaches the refresh controller), a 4 KiB direct-mapped code cache filled by
the core's own fetches with a valid bit per byte, and `refresh_on` =
RFM.RFEN live. In the EU (lane only, its state outside `v35_st_t`) a start
waits for the bytes it reads, except a ModR/M byte still on the bus
(decoded as the register form, the format checked when it lands: never
wrong on the corpus) and a data-only immediate (80–83, F6/F7 /0, C6/C7,
B0–BF, 05, A8/A9, 68/6A), whose function is redone from the saved register
file once the bytes are in; the prelude's POP PSW starts as a NOP whose
stack read the core issues on the first clock the EU waits for it with the
bus free (`pop_fire`, the model's clock-0 bus view), and the reset
vector's JMP far runs as BR near with PS loaded at the start. Results
(overseer's re-run, scratchpad wp82r/): all 29,738 corpus runs replay;
every refresh-off family RTL = model on every run, RTL-exact = model-exact,
pre window exact; the six refresh-on families (F8, F13, F17, F18, F27, F28)
leave 2,228 runs with RTL ≠ model, from two things the model does not have
causally: the refresh counter's phase at the POP read (the model's fitted
`POP_COUNTER`, the lane's from its reset exit and prelude: FC/F8 +3 at 0
waits and +13 at 1 and 2, EC +2; the lane's counter in the model makes
every 0-wait refresh cell exact) and `refresh_any`, the model's lookahead
that runs the refresh templates from clock 0 for a chain whose own RFM
store turns refresh on later (1,416 runs: F17 S/D/W/C 66 of 246 equal, F18
B 0 of 864). The prelude before the POP read is not modelled and the lane
shows it (docs/v35s-chains.md Facts "The prelude from reset against the
chain core"): four reset-vector words fetched against silicon's six, the
jump target 112–140 ticks early, the fX/2 switch 196–256 ticks late, the
PUSH-to-POP gap 6 clocks against 9. Gate: nothing lost (rtlgen --check,
five builds and lint, C1–C3, `--core` 28,142/28,142 model-exact 26,643 =
RTL-exact, F34 1,596/1,596, `--regfile` 69,099 0 bad, funcref 29,738 runs 0
disagree, SST 2,044,304 / 2,001,666, the ucore lane byte-identical to
HEAD's); `test_chain_lane` adds five offline tests and one end-to-end run
of F0-ls-pE-w0 through the chain binary (skipped when the binary is older
than its sources unless `V35S_BUILD_CHAIN=1`). Still scripted: nothing in
the lane; the benches keep their code window, memory image, I/O read value
and initial register file. Not built: the internal RAM (IDB:E00–EFF, which
no chain touches), the trap sequence, interrupts.

**The forty-third fit adopted 2026-10-31 (WP81), the RTL behind it:** the
fit encodes F34's readings as eight enums (`page_mem=fixed`, `bf_read=fixed`,
`page_take=own`, `xfer_nt=odd`, `mul_imm_hold=word`, `wb_fetch=hold`,
`stack_wb=ret`, `mul_imm_read=issue`) and new class integers (`nhold`, `wb`
on the short transfers and DBNZ, `fsetup` on the bit, digit-rotate and
bit-field forms, `mul_imm.mhold`/`rsetup`), 27,838/29,738 over the 36 lists
(docs/v35s-chains.md "The forty-third fit"). `rtlgen` re-ran on it (the
include's class integers renumbered, 495) and the benches rebuilt; the
`--core` gate at the adoption (scratchpad wp81r/baseline/) is the baseline
the catch-up starts from: over the 35 lists 27,446 of 28,142 runs exact
against the model (696 differing, all in F23, F30, F32 and F33; the
vectors of 108 runs not generated, the walk not knowing the queue's
`odd_nt` event), model-exact as the gate counts it 26,772, RTL-exact
26,511; F34 698 of 1,596 exact against the model (model-exact 860,
RTL-exact 594). C1–C3 unchanged. `test_rtl_vectors`' page-and-miscellany
run and mutation tests fail until the catch-up (WP83); three WP78 model
tests pin the forty-second fit's superseded enums (`bf_read=count`,
`page_mem=group`, `wb_fetch=free`) for their alternative checks. New model
state the RTL has no counterpart for: `Cycle.b2b`, `Request.pfree`,
`Queue.odd_nt`/`odd_until`, `Op.half_word`, the `wb_fetch` arbiter rule and
the decide-wait exception.

**Model mechanisms landed unadopted the same day, for the catch-up after
WP83:** `refresh_scope=live` (WP84; the causal refresh, a tie) and WP85's
five I/O-sequencer enums beside a refresh (`port_ready_count=count`,
`port_refresh=late`, `refresh_pair_post=before`, `io_step_restart=last`,
`refresh_lead_step=step`; docs/v35s-chains.md Facts "The I/O sequencer
beside a refresh"), F27 932/1,072 and F28 898/1,088 at the candidate. All
are arbiter, queue and EU-request conditions with no new template step
kind: `rtlgen` is unaffected, the RTL's refresh-on lane is behind by them.

### Phase D: function

The chain model fixes when each step happens; this phase makes the steps do
the right thing. It is the core plan's Phases 3 to 5 with the chain
sequencer in place of a cost table.

- Register file and PSW in internal RAM (`v35_iram.sv`), with the access
  cost the model's `wb` and `nx` integers imply; the core plan's open
  question (one port or two) is answered by the fitted `reg` and `imm`
  templates, which have no separate register-access clock. D1 (2026-10-30)
  put the register file in the EU's state as flops (`v35_rf_t`), since the
  fitted templates charge no access clock; whether it moves into
  `v35_iram.sv` with the data RAM is decided with the SFR block (D3).
- ALU and flags from nuV30 (`instructions.json`, flag notes), driven by the
  sequencer's `alu`/`exec` steps; the SingleStepTests adapter of the core
  plan runs through the replay harness. Done 2026-10-30 (D2 above): the
  adapter runs through the rf bench as a function-only check, not the
  replay harness.
- Segment arithmetic (done with D2), the IDA routing and the SFR block for
  WTC, RFM, PRC (D3, with the reset and the prelude of C6). Done
  2026-10-31 (WP82, "The chain core in the model lane" above): the SFR
  block `v35_sfr.sv`, the routing (FFF00h and up on-chip, the stack on the
  bus; RAMEN set by PRC 4Ch but IDB = FFh puts the internal RAM at
  FFE00h–FFEFFh, which nothing touches, so it is not built), the reset exit
  as A3's parameters; the prelude before the POP PSW read runs but is not
  modelled (C6 stays open there).
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
   The fortieth fit (WP72, 2026-10-30, docs/v35s-chains.md "The fortieth
   fit"; F23 303/360, F25 534/588) adds seven mechanisms the RTL lacks:
   `xfer_abort=word` and `cond_gap=own` (the queue's abort and the EU's
   flush), `burst_count=dw`, `lea_io=recover`, `lea_room=ir`,
   `prepare_sync=run` and `imm_latch=wait` (the EU's requests, EA clocks,
   take sync and the decoder's immediate against the latch); adopted
   2026-10-30 after D2, the RTL catching up in WP75: at the adoption the
   `--core` gate differs from the model on 359 of 26,234 runs (F23 60, F25 153, F30 142, and 4 F0w runs in an internal latch field only; 24,183 exact, 1,692 not modelled); `rtlgen` leaves the
   `dispose` class out of the step tables and `test_rtlgen`'s class check
   fails. That was the baseline WP75 cleared the same day (its whole-corpus run under the
   adopted fit is in scratchpad wp72a/core-all-baseline.txt; "E3 and the fortieth fit's catch-up done" above). The probe
   family F30
   and its controls F31 (WP73, 2026-10-30, 1,476 and 234 runs;
   docs/v35s-chains.md "Probes for the facts-only shapes") join the RTL
   gate lists with that package: the whole-corpus `--core` list becomes 33
   families, 26,234 runs.
2. F25 LDEA, XLAT, PUSH imm, PUSH R and POP R, PREPARE and DISPOSE, the
   segment pushes and moves: the EA step alone, stack bursts, the segment
   write-back. Done 2026-10-27 (ten classes, three enums, 446/588; the
   thirty-fourth fit, docs/v35s-chains.md); item 1 follows it.
3. F24 strings and REP, INM and OUTM: sustained data demand through the
   arbiter. In the generator and acquired 2026-10-28 (WP66, 912 runs,
   docs/v35s-chains.md "The string and block forms"): a string element
   takes no queue bytes, so the stream never raises a fetch request; the
   facts are the per-element cadence, the REP setup and exit, the
   compares' destination-first read and one-element overrun. Modelled
   and fitted 2026-10-29 (WP67, the thirty-eighth fit, 746/912; seven
   str_* classes, four enums, docs/v35s-chains.md "The thirty-eighth
   fit"; the thirty-ninth, 2026-10-30, WP70, 778/912: three more enums,
   the single OUTM and the STM/LDM pairs exact, two miss shapes left as
   facts): the element count and a compare's exit come from the
   normaliser's walk, each element's bus cycles are data steps. The RTL
   leaves the string classes out of its step tables (WP68) until this
   item is built: it needs element-indexed addresses from IX/IY/DW, the
   walk's count in the vector format, and the fetch hold after a compared
   element. Built 2026-10-30 (WP75, "E3 and the fortieth fit's catch-up done"
   above): every string run exact against the model, 0 not modelled.
4. The 0F page: a second opcode byte in the decoder. Acquired 2026-10-30
   (F32, WP74, 858 runs, generator-only; docs/v35s-chains.md "The 0F page
   and the register miscellany"): the bit ops are register, load_alu and
   rmw shapes, the BCD strings and the bit fields need new templates, and
   silicon does not reduce the bit-field offset and width registers to 4
   bits. Modelled 2026-10-30 (WP78, docs/v35s-chains.md "The forty-second
   fit", adopted the same night: the 0F page decoded through `Op.page`, the BCD
   byte-pair loop and the bit-field class, 379/858; the bit fields and the
   CL-indexed bit ops mostly ±1 off). Built 2026-10-30 (WP79, "The 0F page
   and the register miscellany built" above: the second opcode byte at the
   ModR/M latch, the BCD compact template, the bit-field cost step and
   whole-register arithmetic; 858/858 against the model).
5. The register miscellany (INC and DEC r16, flags, adjusts, CVTBD and
   CVTDB, signed multiply and divide, IMUL with an immediate). Acquired
   2026-10-30 (F33, WP74, 1,050 runs, generator-only, with REPC/REPNC): the
   one-byte forms cost 3 clocks per instance, the compares' carry exits equal
   F24's Z exits, so REPC/REPNC are a flag choice in the string template.
   Modelled 2026-10-30 (WP78, with item 4: 841/1,050, the register forms on
   the reg and imm shapes with their own integers, `mul.sexec`/`div.sexec`
   for the signed register forms; REPC/REPNC decoded as REP prefixes since
   WP76). Built 2026-10-30 (WP79, with item 4; 1,050/1,050 against the
   model, the adjust, convert and BCD data paths read off the V20 suite).
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
