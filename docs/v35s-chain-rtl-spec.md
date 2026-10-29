# V35S chain model: RTL specification (Phases A2 to A4)

The signal-level description of the fitted chain-timing model that the RTL timing
machines are written from ([`v35s-hdl-plan.md`](v35s-hdl-plan.md), Phase A). A2 lists
every state variable of the five machines with its range and width, A3 every signal one
machine reads from another and the arbiter as a decision table, A4 every structural field
that is a situation rule, with a proposed verdict. The chain facts
([`v35s-chains.md`](v35s-chains.md)) are the evidence; this document only points into
them. Phase A1's resolved simulator (`sim/frozen/`) is being generated in parallel and is
not used here: code sites are lines of the unfrozen `validation/v35s/chains/sim/`.

## Scope and conventions

**The fit.** The thirty-third fit, `validation/v35s/chains/fit.json`, loaded by
`sim.config.Config.fitted()`: 208 structural fields, 140 class integers over 20 classes,
7 EA entries (the thirty-fourth fit of 2026-10-27, which this document's decisions
section records, adds F25's three enums and 51 integers over ten classes and changes
seven enum values; the tables below are as read under the thirty-third). Only the fitted value of each structural field exists in the RTL; a field is
named (`field=value`) wherever it decides a rule, so the reader can find its OPTIONS
comment in `sim/config.py`. The integers and the EA table are parameters (`rtlgen`); they
appear here only where they bound a width.

**The numbers.** Every observed range below comes from
`python -m validation.v35s.chains.statestats --jobs 8 --out statestats.json`
(`validation/v35s/chains/statestats.py`): all 19,142 runs of the 23 modelled families
(`families.FAMILIES` less F23 and F25), simulated under the fitted Config with a clock log
and so with the quiet-clock fast-forward off, 6,635,654 clock rows, 18,961 runs exact
(the scorecard's count, so the logged runs are the scored ones), no model error, 307.8 s
on 8 workers. The JSON of that run is kept in the work package's scratchpad
(`wpA2/statestats.json`, with the printed table `statestats.txt`); the command reproduces
it. "Observed" is the minimum and maximum over every row; p99.9 is given where the tail is
thin. The run also records, per family, the number of runs whose simulation reads each
structural field (`fit.recording`), quoted in A4 as *Reads*.

**Clocks.** The model steps once per CPU clock. Its clock 0 is the prelude's POP PSW
stack read (`prelude_anchor=pop`): `Machine.__init__` issues that read on clock 0 with the
queue preloaded with three words (`prelude_tail=segs`) and runs the prelude's segment
loads from `pop_exit` (4) clocks after the read's delivery. The normaliser's clock 0 (the
fetch of the word holding the chain's first byte) and `t_fill` are later; state rows are
in the model's own clocks. *The end of clock t* is the state after every phase of clock t
in the order below, which is what `Machine._clock_row(t)` returns; the registered value a
phase of clock t+1 reads is the end-of-clock-t value. (One exception: `eu.since_start`
is incremented after the row is taken. Under the fit nothing reads it, A2.)

**Bus cycles.** A cycle started on clock s with w wait states occupies clocks s .. s+2+w
(`bus.Cycle.end`): B1 on s, B2 on s+1, W on s+2 .. s+1+w, B3 on its last clock
(`BusUnit.state`). w is the WTC's field 0 for memory and fetches, field 7 for I/O; a
refresh cycle is 3 + RFM.RFW clocks (RFW 3 as 2; 5 for RFM FCh); the on-chip SFR store is
a write of 3 + the I/O waits that never reaches the pins (`sfr_cycle=io`). A fetch's word
and a read's data are delivered at the start of clock end+1 (the completions phase) and
usable at once (`data_ready=0`). `min_gap=0`: the next cycle may start on clock end+1.
"In a wait state" (`BusUnit.in_wait`) is a non-I/O cycle on clocks s+2 .. end-1, a refresh
cycle's included. "A fetch past its second clock" is a fetch on s+2 .. end.

**The update order inside a clock.** `Machine.run`, `sim/machine.py:130-230`, in this
fixed order; the phase letters are used in A2 and A3.

| Phase | What runs (model function) |
| --- | --- |
| C completions | `bus.completed(t)`: the cycle whose last clock was t-1 leaves the bus; a fetch's word goes to `queue.arrive` (`arrived_t = t`, the second byte latched under `word_latch=byte_d`), a read's data to `eu.complete` (the data latch filled, the request's `done_at`); after any non-fetch cycle `queue.retry_after` (the aborted request's retry); the END write's completion ends the run |
| A aborted-cycle end | `queue.abort_done()` when an aborted fetch cycle's last clock was t-1 |
| T EU | `eu.tick(t)`: hold and retry bookkeeping, then steps until one waits: `_start` (the instruction start, from the IR), takes through `decoder.take`, request posts (`_submit`), syncs |
| L IR load | `decoder.load_ir(t)` |
| R refresh raise | `refresh.raise_(t)` (refresh-on chains only): an RFM write's effect, the counter edge, `pending` |
| X arbitrate | `arbitrate(t, cfg, bus, queue, eu)`: setup counting before the choice (`data_while_fetch=wait_before`), the choice (`_choose`), the cycle's start, the count after it, the DW and EU-view adjustments |
| P post-issue | in this order, each only when its condition holds: an EU data cycle issued with `decoder.ir_hold` set clears it and loads the IR again (the flag re-evaluated if it loaded); an EU cycle issued with `eu.retick` or the request's `done_at == t` runs `eu.tick(t)` and `decoder.load_ir(t)` a second time, then the `io_ir_hold` check; `io_take=unit`'s drop; `port_issue`'s relatch; `nop_hold`'s hold; the END write noted |
| E end of clock | `queue.end_clock(t, bus)`: the storage check (raises above 6 stored bytes) and the back-to-back decision (`b2b_at = t+1`, `refresh_io_run`'s pair); then `latch_start`'s adjustment of `eu.resume` |
| (row) | `_clock_row(t)` |
| K | `eu.since_start` += 1 unless a memory cycle is in a wait state |

The RTL's combinational order inside a cycle follows this table: each phase reads the
values the earlier phases of the same clock wrote (the arbiter sees this clock's takes,
posts and IR load; the back-to-back decision sees this clock's bus choice), and the flops
take the end-of-clock values. Phase P is the one place where a machine acts twice in a
clock: the EU's second tick after an issue (a start an OUT's issue releases, a write's
`mem_end` release on an I/O issue clock). The RTL either builds that second pass as
combinational logic fed by the arbiter's issue, or proves an equivalent registered form
against the state rows (B3).

**Clock stamps in RTL.** The model stores many events as the absolute clock they happened
on (`queue.arrived_t`, `eu.start_clock`, `req.posted`, ...) and compares them with t. The
RTL holds what the comparisons need: an equality with t becomes a flag set in the phase
that records the event and valid for the rest of that clock; an equality with t-1 a
registered copy of that flag; an order between two stamps a flag captured when the later
event happens, or a saturating age counter. A2 gives each stamp as an offset from the
row's clock (value - t, clipped at -256, "stale") and the representation it needs. B3's
state-row comparison must compare the same representation, not raw clocks.

## A2. State table

One table per machine. *Observed* is statestats' range over all 6,635,654 rows (for a
clock stamp the offset from the row's clock, "stale" at -256; "None" when the variable was
also unset). *Bound* is what the model allows in principle. *Bits* is the proposed RTL
width for the representation in the *Meaning* column. *Start* is the value at the model's
clock 0 (the POP PSW read, `Machine.__init__`), not a silicon reset (Open items). *Phase*
is where it is written (letters of the update-order table; "init" only at the start).
**Dead** marks state the fitted configuration never reads: it exists in the model for
other options and is not built.

The arbiter (`arbiter.py`) holds no state of its own: it is a function of the other
machines' state and of the request records, and the history it needs (the last cycles'
kinds, a fetch run, the I/O recovery) lives in the bus unit and the queue, as listed in A3.
(The RTL arbiter does hold the request record's arbiter-written fields and the fetch-run and
I/O-start history, 69 bits: see Decisions, "C4, the arbiter in RTL".)

### Bus unit (`bus.py`, `BusUnit`)

| Variable | Meaning, RTL form | Type, range | Observed | Bound | Bits | Start | Phase |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `current.kind` | the cycle on the bus | none, fetch, read, write, io_read, io_write, refresh | all 7 | 7 values | 3 | read (the POP PSW stack read) | X starts, C clears |
| `current` position (`t - start`) | B1, B2, W.., B3 as a clock counter | 0 .. length-1 | 0 .. 4 | 4 (3 + 2 waits; refresh 3 + RFW, 5 clocks) | 3 | 0 | X, each clock |
| `current.length` | cycle length | 3 .. 5 | 3 .. 5 | 3 + 2 waits = 5; refresh 5 | 3 | 3 + waits | X |
| `current.addr`, `.width`, `.data` | address, word/lo/hi, write data | 20, 2, 16 bits | | | 38 | 0EFEh word | X |
| `last_end` | last clock of the last cycle; `free(t) = t > last_end + min_gap` | stamp | -102 .. +4 | | derived from `current` (min_gap 0) | -10 | X |
| `last_fetch_end` | a fetch ended on t-1 (the delivery clock: `in_run`, `free_run`, `free_hold`, the arbiter's `fresh`) | stamp, compared `== t-1` | -173 .. +4 | | 1 (registered "fetch ended last clock") | -10 | X |
| `last_io_end` | the I/O recovery window `t <= last_io_end + io_recover`; `disp_io` moves it a clock | stamp | stale .. +4 | | 3 (countdown: io_recover 2 + the disp_io clock) | -10 | X |
| `last_cpu_end` | the stall guard (`STALL_CLOCKS`) | stamp | -131 .. +4 | | 0: simulation guard, not built | -10 | X |
| `refresh_length` | refresh cycle length from RFM.RFW | 3 .. 5 | 3 .. 5 | 5 | 3 | from the prelude's RFM | R (an RFM write) |
| `early`, `early_ok`, `early_n` | `refresh_sync=run`: the current fetch belongs to the early run behind a beaten fetch; the last refresh beat a synced fetch; fetches in the run | flag, flag, count | early on 346,753 rows; `early_n` 0 .. 5 | a back-to-back fetch run: 5 observed | 1, 1, 3 | none, False, 0 | X |
| `waits_mem`, `waits_io`, `min_gap`, `sfr_cycle`, `refresh_whole` | WTC fields and configuration | constants | | | WTC register | from the chain | init |
| `cycles` | the trace log | | | | history only (A3) | | X |

### Queue (`queue.py`, `Queue`)

C2 (2026-10-28) found the widths below short in five places (the count, `abort_t`,
`after_refresh`, `io_held`, `retry_at`/`shift_until`) and two meanings narrower than the code
(`latched`, the uncounted latched byte): see Decisions, "C2, the queue in RTL".

| Variable | Meaning, RTL form | Type, range | Observed | Bound | Bits | Start | Phase |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `bytes` (length) | **the storage count**: bytes stored plus the latched byte (`stored() = len - latched`) | 0 .. 7 | 0 .. 7 (7 on 39,910 rows) | 6 stored + 1 latched; `check` raises above 6 stored | 3 count + 6 x 8 storage + 1 x 8 latch | 6 (three words preloaded) | C adds, T and L remove, E (latch enters) |
| `bytes[].usable` | clock a byte becomes usable | stamp | always the delivery clock | `data_ready=0` | 0: not built | | C |
| `latched` | the delivered word's second byte waits in the 1-byte latch (`word_latch=byte_d`) | 0 .. 1 | 0 .. 1 | 1 | 1 | 0 | C sets, E clears (`check`), T (taken through it) |
| `latch_full` | that byte waits behind a full queue | flag | | | 1 | False | E |
| `latch_in_t` | such a byte went into the queue on t (`latch_start`) | stamp, `== t` | stale .. 0 | | 1 | None | E |
| `uncommitted` (length) | bytes taken by the running take step, not yet committed (`take_commit=at_end`) | 0 .. 1 | 0 .. 1 | 1 (a two-byte take over two clocks; the ModR/M commits at once, `modrm_commit=byte`) | 1 | 0 | T |
| occupancy (`occupancy()`) | `len(bytes) + len(uncommitted)` (`release=byte`) | 0 .. 7 | 0 .. 7 | 7 | derived | 6 | |
| room (`room(t)`) | **the request rule's room**, signed: 6 (+1 for the IR's slot) - occupancy - 2 if a word is in flight, the latched byte uncounted on its delivery clock unless mid-take or on a displacement take (A3) | -4 .. 7 | -2 .. 7 (negative on 368,591 rows) | -4 .. 7 | 4 signed, combinational | | computed |
| `flag` | **the request flag** (`request_eval=on_change`: re-evaluated on a take commit, an IR load, a delivery, and the listed exceptions) | flag | True on 442,206 rows | | 1 | False | C, T, X, P |
| `requested_at` | the clock the current request was first raised: the arbiter's dating (A3) | stamp, compared `== t`, against `req.posted`, the last I/O's start | -99 .. 0, None on 6,382,997 rows | unbounded while held | 7-bit saturating age (99 observed), or the three order flags A3 lists | None | X (also T `io_older`, P) |
| `inflight` | a fetch (or an aborted cycle) is on the bus | flag | | | 1 | False (the POP read is a data read) | X sets, C/A clear |
| `completed` | delivered fetches; the take sync's target is a count of it | counter, unbounded | 3 .. 43 | unbounded | 0: replaced by the sync's relative count (EU `sync`) | 3 | C, A |
| `fetch_addr` | the prefetch pointer | address | chain offset 6 .. 86 | 16-bit IP | 16 (+ segment) | the tail's first word + 6 (three words preloaded) | X |
| `arrived_t` | a word was delivered on t | stamp, `== t` | -177 .. 0 | | 1 (combinational in C) | None | C |
| `removed_t`, `ir_t`, `qport_t`, `disp_t`, `mate_t` | on t: a byte left the queue / the IR loaded / a commit held the port / a displacement's last byte was taken / the ModR/M's word-mate was taken | stamps, `== t` | -117 .. 0 (each) | | 1 each | None | T, L |
| `take_t` | an operand byte was taken on t, or on t-1 (`>= t-1` in the refresh seams) | stamp | -163 .. 0 | | 2 (this clock, last clock) | None | T |
| `read_t` | a byte was read on t | stamp | | | **dead** (read only by `latch_read=read`) | None | T |
| `start_t`, `starts` | an instruction started on t (the abort's triple read); starts so far (`starts > 2`) | stamp; counter | stamp; 0 .. 40 | starts unbounded | 1; 2 (saturating at 3) | None; 0 | T |
| `b2b_at` | **the back-to-back commit**: set at the end of a fetch's last clock to the next clock when the request stands | stamp, `== t` | stale .. +1 | | 1 registered | None | E |
| `abort_end`, `abort_t` | the aborted cycle's last clock (`inflight` during it); the clock it started (compared with `eu.start_clock`) | stamp; stamp | 0 .. +2; stale .. 0 | | 2 (position); 1 ("this instruction started on an aborted cycle") | None | X, A; X, P, T |
| `retry`, `retry_loop`, `retry_at` | a dropped request is raised again when the next CPU cycle ends / at a count loop's exit / on clock `retry_at` | flag, flag, stamp ahead | `retry_at` +1 .. +60 | the longest count loop: 62 (SHL by CL, CL masked to 5 bits); 510 for C0/C1 (Open items) | 1, 1, 6 (9) | False, False, None | C, T, X, P |
| `abort_ref` | aborted under a refresh (`refresh_abort_retry=next`) | flag | | | 1 | False | X, C |
| `shift_held`, `shift_until` | `count_latch`: no fetch until the shift's last clock | flag, stamp ahead | +1 .. +31 | as `retry_at` | 1, 6 (9) | False, None | T |
| `nop_held` | `nop_hold`: the request is held until the next start | stamp, `start_t > nop_held` | -6 .. 0 | | 1 | None | P |
| `io_held` | `io_ir_hold`: held until the next start | stamp | -3 .. 0 | | 1 | None | P, X |
| `slot_fetch`, `slot_word` | the fetch in flight runs in a left-out write's slot; the last word was such a fetch's | flags | | | 1, 1 | False | X, C |
| `after_refresh`, `beat_eval`, `refresh_beaten` | a refresh beat a fetch request: it goes on the clock after the refresh; the beaten clock was an evaluation clock; beaten before HALT | stamp `== t`; flags | stale .. +5 | the refresh's length | 1 (set at the refresh's start, live on the clock after its last), 1, 1 | None, False, False | X |
| `dropped`, `drop_hold` | `refresh_drop`: the request was lost; it waits for the unit's loop | flags | dropped on 45,221 rows | | 1, 1 | False, True | X, T |
| `lost_start`, `lost_eval`, `lost_after` | `refresh_lost=start`: lost outside a loop, raised at the next start; evaluated on this clock; in HALT, two clocks later | stamps | -107 .. 0; `== t`; +1 .. +2 | | 1, 1, 2 | None | X |
| `io_run_at`, `t4_at` | a fetch committed for the next clock (`refresh_io_run`, `refresh_beat_t4`) | stamps `== t` | stale .. +1 | | 1, 1 | None | E, X |
| `halted` | the EU is halted (`halt_refresh`) | flag | | | 1 (a copy of `eu.halted`) | False | T |
| `held`, `io_abort`, `words`, `snap`, `peak` | `request_hold=hold`, `io_take=abort`, the release-by-word table, `request_sample=before_take`, a statistic | | held and io_abort always False; `words.released` always 0 | | **dead** | | |

### Decoder (`decoder.py`, `Decoder`)

| Variable | Meaning, RTL form | Type, range | Observed | Bound | Bits | Start | Phase |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ir` | the instruction register: the next opcode, a seventh byte outside the queue | empty or a byte | held on 5,184,949 rows | | 1 valid + 8 + its address | empty | L loads, T empties (start) |
| `need` | operand bytes the running instruction still has to take | 0 .. op_len-1 | 0 .. 4 | 5 (a 6-byte form) | 3 | 0 | T |
| `nx`, `ready_at` | the class's `nx`; the first clock the IR may load (`t >= ready_at`; `room_ir_ready` compares `ready_at > t + fetch length`; `io_take_nx` adds 1) | int; stamp | 0 .. 1; -114 .. +2 | nx max 1 (reg) + 1 | 1; 2 (countdown) | 0; 0 | T |
| `ir_hold` | `ir_load=disp_data`: no IR load (and no IR slot) until the first data cycle issues | flag | True on 35,719 rows | | 1 | False | T, P |
| `ea_end` | a displaced form's EA clocks end before this clock (`ea_ir_room`, `ea_b2b`) | stamp, `t < ea_end` | -28 .. +3 | the largest EA entry, 3 | 2 (countdown) | None | T |
| `modrm_next`, `modrm_addr`, `imm_reg` | the next byte taken is a ModR/M; that byte's address (its word-mate is `modrm_addr + 1`, `modrm_mate`); a register form with an immediate | flag, address, flag | | | 1, 1 (the mate is next: low address bit), 1 | False, None, False | T |
| `stopped` | HALT stopped the loader | flag | | | 1 | False | T |

### EU (`eu.py`, `EU`; steps from `templates.py`)

Instruction and step state:

| Variable | Meaning, RTL form | Type, range | Observed | Bound | Bits | Start | Phase |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `pc` | the instruction pointer (here a chain offset) | address | -41 .. 42 | 16-bit IP | 16 | minus the tail's length (the tail's first byte; the model's `eu.pc` is 0 there, Open items note the frame) | T |
| `cls`, `steps` | the running instruction's class and template (the step list, `rtlgen`'s ROM entry) | 20 classes; a list | 20 classes | 21 with HALT | 5 class + template index | none | T (start) |
| `steps` length | template length | 0 .. 14 | 0 .. 14 (F22 `TEST [BW+d16],imm16`) | the longest generated template; a port relatch inserts 2 steps (`_port_take`) | 4 | 0 | T |
| `k` | **the step cursor** | 0 .. len | 0 .. 14 (p99.9 11) | as the length | 4 | 0 | T |
| `resume` | **the clock the current step may go on**: the count of a clocks step (a count loop is one clocks step), moved by holds | stamp ahead | -109 .. +63 (p99.9 +62) | 62 for SHL by CL (CL & 1Fh), 58 (`div.smexec`); 510 for a C0/C1 count byte, which the model does not mask; plus refresh holds | 6 (9 if C0/C1 counts above 31 exist, Open items) | 0 (no start before `start_at`) | T, X (refresh holds), P, E (`latch_start`) |
| `left`, `left_nw` | bytes left in the current take; clocks left in a `nowait` step (`fixed_lookup=decoder_nowait`) | 0 .. 2; 1 .. 3 | 0 .. 2; 1 .. 3 | 4; `fdisp` 3 + 1 (`lookup_start`) | 3, 3 | 0, None | T |
| `taken`, `op_len`, `imm_bytes`, `disp` | operand bytes taken; the form's length, immediate and displacement bytes | ints | 0 .. 5; 1 .. 6; 0 .. 2; 0 .. 2 | 5; 6; 2; 2 | 3, 3, 2, 2 | 0, 1, 0, 0 | T |
| `sync` | **the take sync**: none, a count of fetches still to be delivered (stored as an absolute target of `queue.completed`), `defer` (`imm_landed`) | mode + count | none; 0 .. 2 fetches (2 on 394 rows); defer | 2 (the fetch in flight and one requested) | 2 mode + 2 count | None | T, X (`abort_latched`) |
| `modrm`, `mem`, `unit`, `fixed`, `ro`, `route` | per-instruction format bits: a ModR/M byte, a memory operand, a unit form, a fixed-lookup group setup, read-only, `dest_route` clocks | flags; 0 .. 2 | route 0 .. 2 | | 1 each; 2 | | T (start) |
| `seg_prefix`, `sfr` | the prefix the next instruction carries; the SFR store's RFM value | byte | 26h .. 36h; ECh .. FDh | | 8, 8 | None | T |
| `start_clock` | the running instruction started on t; with `fetch_start` (a fetch issued on the start clock), `queue.abort_t` and the I/O cycle's start compared with it | stamp | -114 .. 0 | | 1 + the three per-instruction flags | -1 | T |
| `fetch_start` | a fetch issued on an instruction's start clock (`lookup_start`, `dw_count`) | stamp, `== start_clock` | stale .. 0 | | 1 (captured at the start) | None | X |
| `done_t`, `wb`, `wb_until` | the running instruction's steps ended on `done_t`; its write-back clocks; the next instruction's `wbsync` waits until `wb_until` (`wb_from=end`) | stamp; 0 .. 2; stamp ahead | -12 .. 0; 0 .. 2; up to +2 | `wb`/`mwb` max 2 | 2 (one countdown replaces the three) | None, 0, 0 | T |
| `halted`, `halt_t`, `halt_defer` | HALT: halted; the halt status's clocks (`halt_status`, `refresh_halt`: on H and H+1, or after a refresh) | flag; stamps | halt_t -17 .. 0; defer up to +5 | the refresh's length | 1; 2 (status phase) + 3 (deferral) | False, None, None | T, X |
| `started`, `start_at`, `pop_ref` | the first LS's stand-in hold (always started under `prelude_tail`); no start before `start_at` (POP PSW's clocks); the refresh POP PSW already counted (`pop_refresh`) | flag; stamp ahead; flag | started always True; start_at up to +9 | `pop_exit` + read length + refresh stalls | 0; 4; 1 | True; read end + 1 + 4; None | T |
| `trace`, `origin`, `regs`, `ls_shift` | the start log, the tail offset, the register file, `refresh_align=phase_eu` | | | | not timing state (`regs` is Phase D's) | | |

The data latch and the I/O path:

| Variable | Meaning, RTL form | Type, range | Observed | Bound | Bits | Start | Phase |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `wlatch_until` | the bus unit's data latch is busy before this clock | stamp ahead | -249 .. +4 | `wlatch` 4 | 3 (countdown) | 0 | C, T, X |
| `latch_until` | an OUT's I/O holds the port latch: infinite while posted, the cycle's end + 1 once issued (the `slot` step waits for it) | stamp or inf | stale .. +5; inf on 308,057 rows | the I/O length | 1 held + 3 countdown | 0 | T, X |
| `latch_wait` | an I/O instruction waited for the data latch on t (`wlatch_hold`, `refresh_wlatch`) | stamp `== t` | stale .. 0 | | 1 | None | T |
| `reg_latch_t` | this instruction's last operand byte filled the latch, and on which clock (`wlatch_ir`, `sync_io`) | stamp | stale .. 0 | | 1 + 1 | None | T |
| `port_t`, `port_held` | a port byte was taken on t; the I/O requests it relatched (`port_issue`) | stamp; list | port_held 0 .. 1 | 2 (slot + queued) | 1; 2 | None, [] | T |
| `req`, `queued`, `own` | the bus unit's request slot, the requests posted behind a detached I/O, the request the instruction waits on (A2 request record below) | records | queued 0 .. 2 (2 on 120 rows); `own` is `req` or `queued[0]` | 2 behind the slot | 3 request registers | None, [], None | T, X |
| `retick` | a detached request issued on t: the EU ticks again (phase P) | flag | always False at the end of a clock | | combinational | False | X, P |
| `floor_n`, `dfloor_at` | `imm_count`'s floor from the start (`istart` + immediate bytes, + `fgrp`); `disp_floor`'s floor clock | int; stamp ahead | 0 .. 9; -4 .. +5 | 9; pre + 1 + EA + dfloor = 6 | 4; 3 | 0, None | T |
| `rmw_loop`, `rmw_top`, `rmw_cl` | a memory shift's loop clocks and boundary limits (refresh); its `grpcl` clocks | ints | 0 .. 69; 5 .. 65; 0 .. 3 | 3 + 6 + 2 x 30 = 69 with CL masked | 7, 7, 2 | 0 | T |
| `since_start`, `since_t`, `io_pre` | `io_post=start`'s count from the instruction's start | counter; stamp; int | 0 .. 94 | unbounded (resets at each start and `wbsync`) | **dead**: read only by `eu._preload` under `io_post=start`; the thirty-third fit's `io_post=take` never reads it | 0 | T, K |

The unit, abort and refresh-hold state:

| Variable | Meaning, RTL form | Type, range | Observed | Bound | Bits | Start | Phase |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `exec_t`, `hold_done` | **unit hold phase** (`unit_hold`): the exec's first clock (boundaries at every second clock from `hphase`); the fetch or aborted cycle that already held it | stamp; cycle ref | exec_t -98 .. 0; hold_done set on 65,592 rows | | 1 parity toggle + 2 `hphase` count; 1 ("this cycle held it") | None | T |
| `unit_early`, `reg_early`, `shift_latched` | `abort_unit`'s early setup clock taken; `abort_reg`'s early exec; `count_latch` holds the port | flags | | | 1 each | False | T |
| `clk_tag`, `clk_start`, `clk_end`, `clk_seam` | **the refresh hold phases' frame**: the running clocks step's tag (exec, loop, loop_odd, mexit, tail, shift), its first clock, its end (= `resume` while inside), and whether it started seamlessly on the previous step's end | enum; stamps; flag | 7 tags; clk_start stale .. 0; clk_end stale .. +63 | as `resume` | 3; 1 (first clock) + the parity of `resume - t`; 1 | None, -1, -1, False | T, X |
| `hold_from`, `hold_end` | **refresh hold**: the EU waits at its next boundary from the refresh's start to its last clock | stamps | hold_from -128 .. 0; hold_end 0 .. +4 | the refresh's length - 1 | 1 + 3 (countdown) | None | X, T |
| `refresh_beat` | the last refresh beat a fetch request (`refresh_post`) | flag | True on 137,940 rows | | 1 | absent | X |
| `stalled` | refresh stall clocks of this instruction | counter | 0 .. 22 | unbounded | **dead**: read only by the `micro` acceptance modes, not `boundary_bus` | 0 | T, X |

### The request record (`arbiter.py`, `Request`)

Three instances: the slot (`eu.req`) and up to two posted behind a detached I/O
(`eu.queued`); `eu.own` points at one of them. The ranges are the slot's; the queued
requests' are the same or narrower (`statestats`'s `eu.queued0.*`).

| Field | Meaning, RTL form | Observed | Bound | Bits |
| --- | --- | --- | --- | --- |
| `cycles` | cycles still to issue: kind (read, write, io_read, io_write, nowrite) and address; 2 for an odd-address word (`odd_split=atomic`) | 0 .. 2 | 2 | 3 kind + 1 second half + 20 address + 2 width |
| `setup`, `count` | setup clocks needed and counted | 0 .. 87 each (7 on most rows; 69 .. 87 the memory shift by CL, its loop in the write's setup plus refresh stalls) | 69 + the refresh holds inside it | 7, 7 |
| `free_need`, `free_orig` | the last setup clocks that must be fetch-free (None: all); as posted | 0 .. 7; 0 .. 7 | 7 | 3 + valid, 3 |
| `through` | `rmw_alu=through`: setup clocks that count through a fetch | 0 .. 68 | 68 | 7 |
| `lead` | I/O lead clocks (`out.lead`) | 0 .. 2 | 2 | 2 |
| `posted` | the clock it was posted or moved into the slot | -92 .. 0 | unbounded while it waits | 1 ("posted this clock") + the order flags A3 lists |
| `ready_since` | the first clock it was issuable at a choice (`arbiter=b2b` compares `== t`) | -12 .. 0 | | 1 + 1 (ready) |
| `not_before` | no issue before this clock (port relatch, floors, `free_idle`) | up to +6 | relatch 3 + 1 + 1; floors 6 | 3 (countdown) |
| `lift_t` | the lead's first clock (the hold lifted) | -11 .. 0 | | 1 + 1 (this clock) |
| `done_at` | the EU may continue from this clock (a write's end) | +1 .. +5 | the cycle's length | 3 |
| `free_held`, `grp_held` | `free_hold` / `grp_io_hold` held a fetch on t-1 | -6 .. 0; -11 .. 0 | | 1, 1 |
| `xeu` | `dw_view=eu`: setup clocks not counted, as the EU sees them (only `t-2` is looked up) | 0 .. 9 entries | | 3-clock shift register |
| `issued` | cycles issued so far | 0 .. 2 | 2 | 2 |
| `detached`, `port`, `moved`, `dw_moved`, `floor_hold`, `nowait`, `free_bus`, `imm1` | posted and left by an OUT; a port form's; moved in behind an I/O (a memory request / a DW I/O); floored after its post; `io_count=nowait`; group free clocks on an idle bus; `imm1_first`'s form | flags | | 1 each |
| `grpcl`, `cls`, `recover` | a memory shift's CL clocks (refresh); the posting class; `io_recover` | 0 .. 3; 14 classes; 2 | | 2, 5, constant |
| `atomic`, `whole` | `odd_split`, `pop_read_hold=queue` | always True, always False | | constant |

### Refresh (`refresh.py`, `Refresh`; refresh-on chains only)

| Variable | Meaning, RTL form | Type, range | Observed | Bound | Bits | Start | Phase |
| --- | --- | --- | --- | --- | --- | --- | --- |
| counter (`c0 + t`) | the free-running refresh counter; a request on the rising edge of bit RFT + 3 (`refresh_counter=edge`) | mod 128 | c0 3 .. 125 | 7 bits | 7 | `POP_COUNTER[(RFM, WTC)]` at the POP read | every clock |
| `prev_bit` | the selected bit on the previous clock | 0 .. 1 | 0 .. 1 | | 1 | None (no edge on clock 0) | R |
| `rft`, `interval` | RFM.RFT and the interval 16 << RFT | 0 .. 3; 16 .. 128 | 0 .. 3; 16 .. 128 | | 2; derived | from the prelude's RFM | R |
| `on` | RFM.RFEN | flag | | | 1 | from the prelude's RFM | R |
| `pending` | **a refresh request is pending** (its clock is only logged) | stamp | -9 .. 0 | | 1 | None | R sets, X clears |
| `write_at` | an RFM write takes effect `rfm_delay` (3) clocks after its issue | stamp ahead + value | +1 .. +3 | 3 | 2 + 8 | None | X (the store's issue), R |
| `due`, `enable_at`, `timer` | the `due` timer (unused under `edge`), the prelude cut-off (0 under `prelude_anchor=pop`), `refresh_timer` | | due -256 .. +122 | | **dead** | | R |
| `served`, `writes` | logs; `refresh_exec=every2_recent` reads the last start only under `refresh_loop_hold=eve` | | | | not built | | X |

### The variables that decide widths

- **Storage count**: `queue.bytes` reaches 7 on 39,910 rows (6 stored and the latched
  byte); the storage check (`Queue.check`) never fires on the corpus. 3 bits, 6 bytes of
  storage, a 1-byte latch, the IR outside them.
- **Request flag**: one bit, `queue.flag`; the request itself is combinational
  (`requesting`, `wants_fetch`) from it, the room and the change clocks. The room is signed
  (-2 .. 7: the in-flight reservation can exceed the space), 4 bits.
- **Since-start counter**: 0 .. 94 observed, unbounded in principle (it resets only at an
  instruction start and a write-back sync and runs through HALT), and **dead under the
  fit**: only `eu._preload` reads it, under `io_post=start`, which the thirty-third fit
  replaced with `io_post=take`. The plan's width concern does not arise; do not build it.
- **Hold phases**: the refresh hold (`hold_end` 0 .. +4), the unit hold's boundary parity
  (`exec_t`, `hphase` 1 or 2), the halt status (2 clocks, deferred up to 5 by a refresh),
  the data latch (4), the aborted cycle (3). All fit in 3-bit counters.
- **Step cursor**: `eu.k` 0 .. 14 over templates up to 14 steps: 4 bits.
- **Count loops**: a count loop is one clocks step whose length is in `resume`: up to +63
  observed (SHL AW,CL with CL = 31: the step of 62; `div.smexec` 58). 6 bits for the
  corpus; the model lets a C0/C1 count byte reach 255 (510 clocks, 9 bits), see Open items.
  `queue.retry_at` (+60) and `queue.shift_until` (+31) are counted against the same loop.
- **Request setup and count**: 0 .. 87 (7 bits): the memory shift by CL carries its count
  loop in the write's setup (`rmw_loop` 69) and the refresh holds inside it add 3 a
  refresh. `through` reaches 68.
- **Unbounded in principle** (they reset only at an instruction start, or never): the
  address counters `queue.fetch_addr` and `eu.pc` (the IP), `queue.completed` (replaced by
  the sync's relative count, 0 .. 2), `queue.starts` (only `> 2` is read), `eu.since_start`
  and `eu.stalled` (dead), and every clock stamp, of which only the comparisons in A3 are
  built (the longest-lived observed: a request held 99 clocks, a request posted 92 clocks
  before it issued).

## A3. Interface table

Every value one machine reads from another, by producer. *Valid*: "reg" is a registered
value (the end of clock t-1, unchanged until its producer's phase writes it in clock t);
"after C/T/L/X/P/E" is a value written in that phase of clock t and read by a later phase
of the same clock; "comb" is a function evaluated where it is read, whose inputs are as of
that point in the clock (the same `room` read by the EU in T and by the arbiter in X can
differ: the EU's takes and the IR load lie between). *Form* is what the RTL wire carries
(A2 gives the register behind it). The machine-internal reads (the queue's own flag, the
EU's own step state) are not listed. The arbiter is listed as a consumer; it is part of the
bus unit in RTL (`v35_arbiter.sv`), and its writes into the other machines (dating a
request, dropping it, aborting it, counting a setup clock) are listed last.

### From the queue

| Signal | Form | Consumers | Valid | Use |
| --- | --- | --- | --- | --- |
| `room(t)` | signed 4 bits | queue (request), EU (sync lapse `room < 2`, `count_latch`, `imm_start`'s look-ahead with the IR emptied), arbiter (abort `room == 2`, `slot_room`, `refresh_drop_on` odd room, `refresh_drop_post`), machine P (the flag after a late IR load) | comb | the request rule's room (A2 Queue) |
| `counted(t)` | 6 - room | arbiter (`hold_fetch` against `hold_q`, `dw_slot`, `imm1_first`) | comb | |
| `requesting(t)`, `wants_fetch(t)` | 1 bit | arbiter (`fetch_want`), EU (the first LS's quiescence, unused after the start), machine P (`io_ir_hold`) | comb; updates `flag` and `requested_at` as a side effect | a fetch is wanted: the flag (or a fresh evaluation on a change clock) and room >= 2, not in flight, not held by the latch (`latch_hold`), the shift (`count_latch`) or `nop_hold` |
| `asked(t)` | 1 bit | EU (`take_sync=pending`'s count) | comb, in T | a request raised on the take clock not yet on the bus |
| `flag` | 1 bit | arbiter (`io_held`'s release, `refresh_drop`), EU (`retick` raised check), machine P (`io_take`, `nop_hold`) | reg, rewritten in C, T, X, P | |
| `requested_at` | age / order flags | arbiter (`arbiter=b2b` same-clock test, `io_hold`'s older-fetch test against `req.posted`, `free_hold`, `grp_io_hold` against the last I/O's start, `slot_fetch` against `req.posted`, `refresh_drop`), EU (`io_older`: requested before t) | reg, rewritten in X | |
| `inflight` | 1 bit | EU (sync target `completed + inflight`, sync lapse), arbiter (abort tests, slot fetch), machine P | reg; X sets, C/A clear | a fetch or aborted cycle on the bus |
| `completed` | relative count | EU (the sync's target and its met test) | after C, A | replaced in RTL by the sync's count of fetches still owed |
| `b2b_at == t` | 1 bit | EU (`start_sync=b2b_modrm`, `io_b2b`, `refresh_sync` run), arbiter (`arbiter=b2b`, `io_hold=posted_b2b`, `ea_b2b`, `free_hold`, `free_idle_b2b`, `imm1_first`, `dw_count_b2b`, `halt_refresh`) | reg (written in E of t-1) | the bus unit committed to a back-to-back fetch on the previous fetch's last clock |
| `arrived_t == t` | 1 bit | EU (`_start` first LS, `count_latch`, `imm_landed`, `ir_load`'s delivery-clock take, `port_landed`), arbiter (`refresh_drop_on`, `slot_room`, `refresh_beat_t4`, `refresh_drop_unit`), machine P (`io_take`) | after C | a word was delivered this clock |
| `latched`, `latch_full` | 1 bit each | EU (`count_latch`, `imm_landed`, `port_landed`, `refresh_take_latch`), arbiter (`abort_latched`, `refresh_drop_on` / `_post`, `refresh_beat_t4`), machine P (`io_take`) | reg, rewritten in C, T, E | |
| `latch_in_t == t` | 1 bit | machine E (`latch_start`) | after E (`check`) | |
| `take_t`, `ir_t`, `start_t`, `disp_t` this clock | 1 bit each | arbiter (`refresh_beat_t4`, `triple`, `disp_io`), EU (`refresh_clk_start`, `refresh_take_seam`, `_after_disp`: also `take_t >= t-1`), machine P (`io_ir_hold`, `nop_hold`), decoder (`ir_port`, dead) | after T, L | |
| `triple(t)` | 1 bit | arbiter (`abort_fetch`, `refresh_abort`) | comb in X | start, take and IR load on t, `starts > 2` |
| `stored()` | 0 .. 6 | EU (`io_older`, `imm_start`, `io_b2b` against `io_b2b_q`) | comb in T | bytes physically stored |
| `available(t)` | 0 .. 7 | decoder (take, IR load) | comb | usable bytes at the head |
| `abort_end`, `abort_t` | position; per-instruction flag | EU (sync during an aborted cycle, `unit_hold`, `abort_reg`, `abort_unit`), arbiter (`abort_*`), machine (A) | reg; X sets | |
| `retry`, `retry_loop`, `retry_at` | flags, countdown | EU (raises the retry at the loop exit, `retry_first`, `refresh_retry`), arbiter (`refresh_abort`'s loop retry), machine P (`io_take`) | reg | |
| `dropped`, `drop_hold` | 1 bit each | EU (sync lapse, a starved take re-raises, `refresh_reraise`), arbiter | reg; X sets | |
| `after_refresh == t`, `beat_eval`, `refresh_beaten`, `lost_*`, `io_run_at == t`, `t4_at == t`, `io_held`, `nop_held` | 1 bit each (lost_after 2) | arbiter (the beaten fetch's turn, `refresh_lost`, the committed fetches, the holds) | reg | written by the arbiter, read back on later clocks |
| `shift_held`, `shift_until` | flag, countdown | EU (`count_latch`'s release at the shift's last clock) | reg | |
| `halted` | 1 bit | queue (`_evaluates` under `halt_refresh`) | reg | a copy of `eu.halted` |

### From the decoder

| Signal | Form | Consumers | Valid | Use |
| --- | --- | --- | --- | --- |
| `ir` valid (and its opcode) | 1 bit + 8 | queue (the IR's slot in `room`), EU (start; `wlatch_ir` reads the opcode for an I/O form) | after L; emptied in T by a start | |
| `need` | 0 .. 5 | queue (`room_ir` mid-take, `latch_midtake`), arbiter (`hold_count=ahead` subtracts it), EU (`count_latch`, `io_take`, `io_exec`) | after T | **the decoder's need**: operand bytes still to come |
| `ready_at` | countdown | queue (`room_ir_ready`), EU (`io_take_nx` adds 1) | after T | the IR may load |
| `ir_hold` | 1 bit | queue (no IR slot), machine P (cleared on the data cycle's issue, IR reloaded) | after T | `ir_load=disp_data` |
| `ea_end` | countdown | queue (`ea_ir_room`), arbiter (`ea_b2b`) | after T | inside a displaced form's EA clocks |
| `take(t, n)` result | 0 .. 2 bytes | EU | in T | bytes moved this clock; 0 stalls the EU |
| `loads_after(t, n)` | 1 bit | EU (`late_read`) | comb in T | the IR would load on t after this take |
| `mate_t == t` (queue-held) | 1 bit | queue (`modrm_mate`) | after T | |

### From the EU

| Signal | Form | Consumers | Valid | Use |
| --- | --- | --- | --- | --- |
| `req` (slot) and its fields | request record | arbiter (everything in the decision table), queue (`_io_form`, `refresh_io_run`), machine P | after T; X rewrites count, flags, `ready_since`, `lift_t`, `not_before` | **eu.req**: the bus unit's request slot |
| `queued` | 0 .. 2 records | arbiter (`dw_slot`: another request behind), EU (`dw_port`) | after T, X | |
| `start_clock == t`, `fetch_start` | 1 bit; per-instruction flag | arbiter (`refresh_lost` at a start, `dw_count`, `refresh_abort`'s loop retry, `refresh_drop_post`), machine P (`nop_hold`, `latch_start`), queue (`start_t`) | after T | an instruction started this clock |
| `cls`, `mem`, `unit`, `disp`, `op_len`, `imm_bytes` | class and format bits | arbiter (`refresh_abort`, `io_take`, `ea_b2b`, `disp_io`), queue (`room_ir_imm`, `_io_form`), machine P (`nop_hold`: `op_len == 1` and an interlocked class) | after T (start) | |
| `halted`, `halt_t`, `halt_defer` | flags / phase | arbiter (no prefetch in HALT, `halt_status`'s uncounted clock, `refresh_halt`, `halt_refresh`), queue | after T; `halt_defer` after X | |
| `latch_wait == t` | 1 bit | arbiter (`wlatch_hold`, `refresh_wlatch`) | after T | an I/O form waited at its start for the data latch |
| `sync` | mode + count | arbiter (`refresh_sync`'s early run, `abort_latched`'s sync fix), machine | after T | |
| `resume`, `clk_end`, `clk_tag` | step countdown, tag | arbiter (`refresh_drop_unit`: inside a unit's clocks), machine E (`latch_start`) | after T | |
| `in_loop(t)` | 1 bit | arbiter (`refresh_reraise`, `refresh_drop_unit`) | comb in X | a count loop runs |
| `refresh_ok(t, other)` | 1 bit | arbiter (`_refresh`) | comb in X | **the EU accepts a refresh**: its micro-boundary (`refresh_accept=boundary_bus`) |
| `port_t == t`, `port_held` | 1 bit; up to 2 records | machine P (`port_issue`) | after T | |
| `retick` | 1 bit | machine P | after X | a detached request issued: tick again |
| `wlatch_until`, `reg_latch_t` | countdown; flags | EU only (start, `wlatch_ir`); arbiter none | | the data latch is EU-held state in the model; in RTL it belongs to the bus unit (C1) |
| `refresh.write` call | RFM value | refresh | X (the SFR store's issue) | |

### From the bus unit

| Signal | Form | Consumers | Valid | Use |
| --- | --- | --- | --- | --- |
| `current` (kind, start, end, length) | cycle record | EU (`start_sync`, `io_busy_start`, `io_exec`, `io_take_nx`, `_io_drop`, `sync_io`, `unit_hold`, `late_read`, `_late_fetch`, `dw_port`, `_early`), arbiter, queue (`end_clock`'s b2b decision on a fetch's last clock), machine K | reg; X starts, C clears | **bus.current**: the cycle on the bus |
| `busy(t)`, `free(t)` | 1 bit | arbiter (nothing starts on a busy bus), EU (`io_older`, `imm_start` need a free bus), machine (HALT end) | comb | |
| `fetch_inflight(t)` | 1 bit | EU (`start_sync`, setup counting), arbiter (`data_while_fetch` counting) | comb | |
| `in_wait(t)` | 1 bit | arbiter (`io_count=nowait`), EU (`nowait` steps), machine K | comb | |
| `last_fetch_end == t-1` | 1 bit | arbiter (`free_run`, `free_hold`, `imm1_first`, `fresh`), EU (`imm_start`) | reg | the delivery clock of a fetch |
| `last_io_end` window | countdown | arbiter (`io_recover`, `grp_free_bus`, `grp_io_hold`) | reg; X (`disp_io` extends) | the I/O recovery |
| `cycles` history | flags | arbiter: `_fetch_run` (the fetch that just ended started on the clock after an earlier fetch's last: a fetch run), `grp_io_hold` (the last I/O's start against `requested_at`), `refresh_beat_t4` (the last two cycles: a refresh, then a 3-clock fetch right after it); EU: `pop_refresh` (the last cycle a refresh) | reg | the history the RTL keeps as 3 flags and a stamp comparison |
| `early`, `early_ok`, `early_n` | 1, 1, 3 bits | EU (`_early`, `refresh_sync_run`), arbiter | reg | `refresh_sync=run`'s early run |
| `length(kind)` | 3 bits | queue (`fetch_len` for `room_ir_ready`), EU (`refresh_recent_by`, dead) | constant per run | |
| `completed(t)` | the ending cycle | machine C | C | delivery: fetch word to the queue, read data to the EU |

### From the refresh controller

| Signal | Form | Consumers | Valid | Use |
| --- | --- | --- | --- | --- |
| `pending` | 1 bit | arbiter (`_refresh`) | after R | **the refresh pending** |
| `served` (last start) | stamp | EU (`refresh_exec=every2_recent`'s window) | | dead under `refresh_loop_hold=entry` |
| `refresh_length` (into the bus unit) | 3 bits | bus unit | after R (an RFM write's effect) | |

### Writes the arbiter makes into the other machines (phase X)

`queue.requested_at` (re-dated by `free_hold`, `grp_io_hold`, `refresh_lost`; cleared by
an I/O's hold under `le_q_io`, not fitted), `queue.flag`, `dropped`, `drop_hold`,
`lost_start`, `lost_eval`, `lost_after` (the refresh's drop), `queue.abort()` (the aborted
cycle: `inflight`, `abort_end`, `abort_t`, `retry`, `retry_loop`), `queue.after_refresh`,
`beat_eval`, `refresh_beaten`, `t4_at`, `io_held` (released), `queue.issue()` (the fetch:
`inflight`, `fetch_addr`, the flag cleared or re-evaluated by `request_reissue`), the
request's `count`, `free_need`, `free_held`, `grp_held`, `lift_t`, `ready_since`,
`not_before` (`free_idle`), `xeu`; `bus.last_io_end` and `last_end` (`disp_io`),
`bus.early`, `early_n`, `early_ok`; `eu.fetch_start`, `eu.refresh_beat`, `eu.halt_defer`,
`eu.issue()` / `issue_nowrite()` (the data cycle, `done_at`, the data latch, the promotion
of a queued request), `eu.refresh_cost()` (the EU's refresh hold, `hold_from`, `hold_end`,
and the setup extensions of a memory shift's write and read), `refresh.start()`.

### The arbiter as a decision table

`arbitrate` (`arbiter.py:111`) and `_choose` (`arbiter.py:319`) under the fit, in their
order. The first block computes the two candidates (a fetch, `fetch_want`; a data or I/O
request, `req`, the slot's request with cycles left); the second block picks what starts.
Each row names the field(s) that fix it. "Posted" is a request with cycles left, not yet
issued; "issuable" is `count >= setup` and `t >= not_before`.

**Before the choice (setup counting).** Unless the clock is HALT's status clock
(`halt_status`), a posted, not yet issuable request counts this clock when its counting
rule accepts it (`data_while_fetch=wait_before`: counted before the choice, so a fetch
starting this clock does not stop it): a memory request on a clock with no fetch in
flight, or with one while still in the part of its setup before its last `free_need`
clocks or within `through` (`rmw_alu`); a group request's clocks never during an I/O
cycle or its recovery and its free clocks only on an idle bus (`grp_free_bus`), a refresh
counting for a memory shift's read (`refresh_grpcl`); an I/O request on every clock with
no memory wait state (`io_count=nowait`, `refresh_io=waits`).

**Block 1: the candidates** (`_choose` lines 320-451).

| # | Condition | Effect | Fields |
| --- | --- | --- | --- |
| 1 | `queue.lost_start` set and an instruction starts this clock | the lost request is evaluated again now (`lost_eval = t`); at HALT's start two clocks later as a beaten request | `refresh_lost=start`, `halt_status` |
| 2 | always | `fetch_want = queue.wants_fetch(t)` and not `eu.halted` | `request_eval`, `latch_hold`, `count_latch`, `nop_hold` (a halted EU raises no prefetch) |
| 3 | EU halted, a refresh beat a request before HALT, the queue wants a fetch | `fetch_want` = true (the held fetches still run) | `halt_refresh=run_drop` |
| 4 | posted memory request in its fetch-free clocks, the fetch first requested on the delivery clock of the fetch just ended | the fetch is not held; the request's remaining clocks count through it (`free_need = 0`) | `free_run=run` |
| 5 | posted memory request held a fetch on t-1 (`free_held`) | the fetch is dated t and runs (or beats the request now issuable) | `free_hold=delivery` |
| 6 | posted memory request on its free clocks' eve, the fetch requested on this delivery clock, not back to back, not a run's | `fetch_want` = false, `free_held = t` | `free_hold=delivery` |
| 7 | posted group request whose next clock is a bus-free group clock, an I/O cycle or its recovery on, the fetch requested on or after that I/O's issue | `fetch_want` = false (`grp_held = t`); on the clock after the hold the fetch is dated then | `grp_io_hold` |
| 8 | posted memory request that moved into the slot behind an I/O, in its fetch-free part, the fetch older than the move | held until the free clocks start, then let through (`free_need = 0`) | `slot_fetch=slot` |
| 9 | the fetch is a back-to-back one, a displaced memory form inside its EA clocks | `fetch_want` = false | `ea_b2b` |
| 10 | posted request in the holding part of its setup (`count < setup - lead`), or a memory request in the I/O recovery, or floored (`floor_hold`), not a fetch run's free case | I/O request: a back-to-back fetch goes (`io_hold=posted_b2b`); any other fetch is held on every clock after the post clock, and on the post clock as a memory request's. Memory request: held while `counted(t) - need > hold_q` (`hold_run=False`: also on a fetch's delivery clock) | `hold_fetch=le_q`, `hold_count=ahead`, `hold_q` 3, `io_recover` 2, `disp_floor=posted` |
| 11 | `queue.io_held` set, no start since, flag still up, nothing in flight | `fetch_want` = false | `io_ir_hold` |
| 12 | an I/O form waits at its start for the data latch | `fetch_want` = false | `wlatch_hold=True` |
| 13 | posted I/O request in its lead (`count >= setup - lead`) | `lift_t` = the lead's first free clock (not a refresh's, `refresh_lift`); only a fetch requested no later than the I/O runs, and only on that first clock; a moved-in DW request with another request behind and more than `hold_q` counted holds even that; a committed back-to-back fetch in HALT or `refresh_io_run`'s fetch goes | `io_hold`, `dw_slot=behind`, `refresh_lift=free`, `halt_refresh`, `refresh_io_run` |
| 14 | the clock after a refresh that beat a fetch request, the queue still wants it, no posted memory request | `fetch_want` = true, ahead of a posted I/O request (the request is dropped from this clock's candidates) | `refresh_after=fetch_next` |
| 15 | posted request not issuable, or `t < not_before`, or a memory request in the I/O recovery | no data candidate | `io_recover`, `port_latch` relatch, floors |
| 16 | the data candidate is issuable for the first time | `ready_since = t` | |

**Block 2: what starts** (`_choose` lines 452-541, `_refresh` lines 194-278).

| # | Condition | Issued | Why | Fields |
| --- | --- | --- | --- | --- |
| 17 | bus busy (`current` on t) or `t <= last_end + min_gap` | nothing | one cycle at a time | `min_gap=0` |
| 18 | the slot's request issued its first half (odd-address word) | its second half | atomic pair | `odd_split=atomic` |
| 19 | a refresh is pending and none of: HALT's status second clock; a posted I/O in its lead (a port form's first lead clock blocks only when a fetch is also wanted); an I/O form waiting for the data latch; the EU refusing (`refresh_ok` false off a micro-boundary) | the refresh cycle (it beats the fetch and the data request: `refresh_fetch`, `refresh_data`). On this clock: a request that would be aborted is aborted under it (`refresh_abort`); a request raised this clock with odd room and a latched byte (or room 2 inside a unit's loop) is lost (`refresh_drop`), unless it is an I/O's post-clock request (`refresh_drop_post`); a surviving fetch request becomes the beaten one (`after_refresh`); the EU's hold starts (`refresh_cost`) | the refresh controller's request has priority on a free bus | `refresh_halt=status`, `refresh_lead=closed`, `refresh_lead_port=last`, `refresh_wlatch=hold`, `refresh_accept`, `refresh_abort`, `refresh_drop`, `refresh_drop_on=odd`, `refresh_drop_unit=unit`, `refresh_drop_post=hold`, `refresh_lost`, `refresh_reraise`, `refresh_sync=run` |
| 20 | an issuable data request and a wanted fetch | the fetch if it was committed back to back (`b2b_at == t`), or both became ready and requested this clock; except a one-byte-immediate form's first request on a non-run delivery clock with more than `hold_q` counted: the data | data otherwise | `arbiter=b2b`, `imm1_first=hold` |
| 21 | data candidate, a left-out write (`nowrite`) | the slot: a fetch if the queue has room for a word, not counting a word delivered this clock (or one is wanted); else no cycle, the EU goes on `sidle` clocks later; the data latch filled either way | CMP/TEST's kept write slot | `grp_read=rmw_slot_any`, `slot_room=word`, `slot_idle=eu`, `slot_latch` |
| 22 | data candidate | the data or I/O cycle (`eu.issue`); a write fills the data latch; a detached I/O's issue promotes the queued request (it counts from now) and reticks the EU (phase P) | | `write_wait=mem_end`, `wlatch`, `dw_count=bus` (a DW I/O does not count its post clock if a cycle starts on it), `disp_io=extend` (the I/O held a clock longer after a displacement take on its issue clock) |
| 23 | no candidate, but start + take + IR load this clock (`triple`), the fetch wanted with room exactly 2, nothing in flight; or not wanted with the latched byte making it 2 | an aborted 3-clock cycle (nothing on the bus); the retry is the next CPU cycle's end or, for a unit form started on it, its loop's exit | the queue's three reads on one clock | `abort_fetch=retry`, `abort_latched=any`, `abort_unit=loop`, `abort_reg` |
| 24 | a wanted fetch on the delivery clock of a 3-clock fetch a refresh beat, the word's byte latched, no take or IR load, not committed back to back | nothing now; the fetch starts next clock (`t4_at`) | the bus unit is still in that fetch | `refresh_beat_t4=t4` |
| `refresh_io_step=own` | a pending refresh beside a posted I/O request (port or DW form, EU not in HALT) starts only on the I/O's steps (every second clock back from the issue, from `setup − 5` after the post, restarted after any bus cycle in the setup; the post clock); beside an OUT the step takes it whatever the EU's boundaries | arbiter.py `io_step`, `_refresh`; eu.py `refresh_ok` | arbiter, EU | special | `F27-push-fc-port-inb-n0-pO-w0`, `F27-out-fc-port-outb-n0-pO-w0`; any −65, step −4 | F27 FCh, F8, F13, F17 | P: one step-phase bit in the I/O sequencer |
| `refresh_io_stall=step` | the refresh's last clock does not count toward the I/O setup when the count would end on a step | arbiter.py `Request.counts` | arbiter | special | F27 port ladders; waits −53 +6 F27, −14 elsewhere | F27 FCh, F8, F13, F17 | P: reads the same phase bit |
| `io_step_issue=step` | after a refresh in its setup an IN's I/O issues on a step only | arbiter.py `_choose` | arbiter | special | `F27-push-fc-port-inb-n1-pE-w0`; count −7 | F27 FCh | P: the sequencer's issue condition; the model's three-cycle look-back becomes a refresh-seen flag |
| 25 | a wanted fetch | the fetch (`queue.issue`: the flag re-evaluated with the word reserved unless a memory request waits, `request_reissue=no_mem`); it joins the early run behind a beaten fetch (`refresh_sync=run`); a run's delivery-clock fetch (or a back-to-back one) at a posted request's free clocks' eve leaves an idle clock before the request (`not_before`) | | `request_reissue`, `refresh_sync`, `free_idle`, `free_idle_b2b` |
| 26 | otherwise | nothing (idle) | | |

**After the choice** (`arbitrate` lines 128-158): the request just handed the slot by
this clock's issue counts this clock as posted before it; a DW-form I/O posted on this
clock with a cycle starting on it, or posted at its start with a back-to-back fetch
starting, gives that clock back (`dw_count=bus`, `dw_count_b2b`); under refresh a DW
I/O's uncounted clocks follow the EU's early-run view (`dw_view=eu`).

**History the arbiter reads.** The last cycle's end and kind (the delivery clock, the
I/O recovery window from `last_io_end`, extended a clock by `disp_io`), whether the fetch
that just ended was part of a fetch run (the two last non-refresh cycles back to back),
the last I/O cycle's start (`grp_io_hold`), the last two cycles (`refresh_beat_t4`),
the back-to-back commit made at the previous clock's end (`b2b_at`), the request's own
history (`ready_since`, `free_held`, `grp_held`, `lift_t`, `xeu`), and the queue's refresh
history (`after_refresh`, `beat_eval`, `refresh_beaten`, `lost_*`, `io_run_at`, `t4_at`).

## A4. Rule register

Every structural field of `fit.json` (208) is in exactly one of two tables: the register
below, which lists the fields whose fitted value is a situation rule (its OPTIONS comment
or its code names a hold, a reissue, a class or form it is keyed on, a neighbour, a clock
position or a bus-cycle kind), and the structure table at the end of the section, which
lists the plain machine structure, the parameters, the harness fields and the fields no
run reads.

Columns. *Rule*: the field and its fitted value. *What it does*: the fitted behaviour in
plain words. *Code*: the site that applies it (the first of several where the field is
read in more than one place; `grep -n "cfg.<field>" sim/*.py` finds the rest). *RTL*: the
RTL machine it belongs to (the arbiter is part of the bus unit's module set, C4). *Kind*:
`core`, a general mechanism with a guard that any implementation has in some form;
`micro`, a rule that only shapes the generated step lists (`templates.steps`) or picks a
class integer, which the RTL gets from `rtlgen` as data; `special`, a case rule in the
clocked logic. *Pinned by*: the named run(s) and the counts the record holds. "doc NNNN"
is a line of `docs/v35s-chains.md` (the fitted-structure row, or the flip-back table that
holds the number); "cfg" is the field's OPTIONS comment in `sim/config.py`; "st6" is the
table in "The fitter's stage 6 under the family guard", which flips each field it lists
alone on the thirty-second fit over all 19,142 runs. A signed count is the doc's: "+n" the
exact runs the rule gained when adopted, "−n" the exact runs lost when it alone is set back
(on the fit it was adopted in, or the later one the doc names). *Reads*: the runs out of
19,142 whose simulation reads the field at all (statestats' `field_reads`, from
`fit.recording`): an upper bound on the runs the rule can touch, and 19,142 for a field the
request rule or the start reads on every clock. *Verdict*: **P** port as is; **C** port as a
cleaner mechanism, named in the family's paragraph, after a re-fit (or a whole-corpus flip
for an inert rule) shows the 19,142 runs unchanged and the state rows equivalent (B3);
**M** re-measure, with the family or chain that would settle it. The verdicts are
proposals.

**Count.** 144 register fields (19 core, 17 micro, 108 special) and 64 structure fields.
Verdicts: 71 P, 63 C, 10 M. By family: the abort cycle, the slot, the EA path's microcode
and the I/O slot port as is; the C verdicts are concentrated in five proposed mechanisms,
each replacing a family of case rules: the refresh boundary map as generated step data
(21 fields), the latched byte's explicit write port (8), the I/O issue clock's `alu_busy`
(7), the early fetch run as a boundary stall (5), the posted request's window machine (5),
plus the reissue (3) and five inert rules to drop (`room_ir_ready`, `ea_floor`, `wlatch_ir`
with `wlatch_ir_at`, `wlatch_mul`, `sfr_setup`). The ten M rules rest on one cell or a
handful of runs: `room_ir_imm`, `port_issue`, `free_idle_b2b`, `grp_io_hold`, `disp_io`,
`lookup_start`, `refresh_drop_unit`, `refresh_drop_post`, `refresh_beat_t4`,
`refresh_lead_port`; five of them are refresh-on or prelude-only.

**The plan's named rules.** `nop_hold` (reissue family, C: it takes back the reissue
`request_reissue` makes), `port_issue` (M: one cell, F7 OUT OUT at pO w0), `latch_start`
(latched-byte family, C: an explicit port owner makes the start's lost clock a
consequence), `io_take=unit` (I/O issue family, C: +81 when adopted, so the `alu_busy`
re-fit must keep those runs).

### Decisions (overseer, 2026-10-27)

The proposals above were reviewed on 2026-10-27; these are the decisions the RTL work
follows. The register's verdict columns stay as proposed so the reasoning is kept; where a
decision differs it is said here.

- **P, 71 fields: accepted.** They are ported as the mechanisms the family paragraphs
  describe, in the phase their RTL column names.
- **Inert rules: dropped, verified.** The thirty-third fit with `room_ir_ready=False`,
  `ea_floor=False`, `wlatch_ir=False` (`wlatch_ir_at=busy`, its first option),
  `wlatch_mul=take`, `sfr_setup=fetch_free` and the tie `sync_io=issue` scores every one of
  the 19,142 runs as the thirty-third fit does, byte for byte including the residual
  histograms (scratchpad wp53/, `fit-inert-off.json` and `fit-inert-off-syncio.json`
  against sc35v.txt). That configuration, on top of the F25 fit (below), was adopted as
  the thirty-fourth fit on 2026-10-27 (scratchpad wp54/, byte-identical over F0–F22 and
  F25); the frozen package is regenerated from it and the RTL never builds these rules. `abort_latched`
  stays `any` (its tie `full` is no simpler).
- **The refresh boundary map (21 fields) and `unit_hold`: accepted as a representation,
  not a re-fit.** The model keeps the fields; `rtlgen` emits a boundary bit and a hold bit
  per clock of every generated step, and the RTL has the one rule the paragraph names.
  Equivalence is by the B3 state rows on the refresh-on runs. The merge of `unit_hold`
  into that rule is tried first as an enum alternative in Python (the register's C) and
  adopted only if the scorecard is unchanged; otherwise `unit_hold` ports as is.
- **The other C verdicts: each is a Python experiment before it is RTL.** `alu_busy`
  (7 fields), the latched byte's write port (8), the posted request's window machine (5),
  the reissue (3), the early fetch run as a boundary stall (5), the lost request's
  evaluation clocks (2), the shallow-queue start (2), the `late_disp` and `dw_count_b2b`
  folds and the EA unit's queue port (`ea_ir_room`, `ea_b2b`). Each is a new enum
  alternative in `sim/config.py` with the old behaviour as DEFAULT, scored over the whole
  corpus, and adopted only when the 19,142 runs score as before (the +81 of `io_take`
  included). They are taken in the order the RTL needs them: the latched port and the
  reissue before C2, `alu_busy` and `unit_hold` before C3, the window machine, the shallow
  start, the EA port and the folds before C4, the refresh ones before C5. An experiment
  that loses runs is dropped and its rules are ported as fitted; no phase waits on a
  cleanup.
- **M, 10 fields: two probe families, then decide.** F26 holds the refresh-off probes the
  rows name: `port_issue` (port takes on a fetch's issue clock after 1- and 2-byte register
  forms at 0 waits), `free_idle_b2b` (base+index+d16 immediate stores at k = 2 under both
  markers at 1 and 2 waits), `grp_io_hold` (INC/NOT/SHL [BW] with a bus-free group clock
  behind the OUT marker at pO), `disp_io` (d8 and base+d16 forms timed to take on the I/O's
  issue clock by a leading NOP ladder under the OUT marker), `lookup_start` (TEST
  [0C00h],AW at k = 1, 2 with and without a start-clock fetch at every wait), and the C0/C1
  count mask (`SHL AW,32`, `SHL AW,255`). F27 holds the refresh-on probes: `room_ir_imm`
  (a MOV r16,imm16 ladder against MOV r8,imm8 and ADD r,imm16 with the IR empty and room
  one byte short), `refresh_drop_unit`, `refresh_drop_post`, `refresh_beat_t4` and
  `refresh_lead_port` as their rows describe. Until they are measured these ten rules are
  ported as fitted.
  **Measured 2026-10-28** (docs/v35s-chains.md, the probe families' section; F26 882/906 and
  F27 646/1,072 under the thirty-fourth fit, each rule flipped and rescored): `lookup_start`
  (−108 flipped), `free_idle_b2b` (−32), `room_ir_imm` (−140), `refresh_drop_post` (−16) and
  `refresh_lead_port` (−6) are P; `disp_io` (−42, base+index+d16 cells only) and `grp_io_hold`
  (−42, TEST forms only) are confirmed where the corpus saw them and keep their rows' question
  about the other modes and forms as a state read; `refresh_drop_unit` (−3) is weakly
  confirmed; `port_issue` (−1, the same one cell) and `refresh_beat_t4` (+1 −2) are still
  undecided and stay fitted. The C0/C1 count byte is NOT masked by silicon (SHL AW,255 runs
  510 loop clocks in both the immediate and the CL form): the count loop's 9-bit width stands,
  and the model's 5-bit CL mask becomes an enum with the unmasked value fitted.
  **Under the thirty-sixth fit (F27 fitted, 2026-10-28)** the refresh-on flips are `room_ir_imm`
  −171, `refresh_drop_post` −16 F27 −15 F18, `refresh_lead_port` −18 F27 −31 F18, `refresh_drop_unit`
  −6 (confirmed), `refresh_lead` −77 +2, and `refresh_beat_t4` +2 −2 on F27 but −4 on F13: decided,
  t4 stands (P). `port_issue` is the one still-undecided row.
  **Under the thirty-seventh fit (F28 and F29 fitted, 2026-10-28, WP61; docs/v35s-chains.md, "The refresh at a
  unit's exit before an OUT")** eight enums are added, rows below marked "2026-10-28, WP61": `refresh_wb`,
  `refresh_relatch`, `refresh_window`, `refresh_start_seam`, `refresh_step_lead`, `refresh_beat_b2b`, `grp_disp`,
  `dw_lift`; no integer changed; byte-identical on every refresh-off family but F29, gains-only elsewhere (F8 37,
  F13 440, F17 754, F27 889, F28 820, F29 427; 22,771/23,612). Every earlier value re-flipped is confirmed
  (`refresh_beat_t4=none` −4 F13, `port_issue=False` −6 F29, `disp_io=none` −6 F29, `grp_io_hold=False` −18 F26);
  `refresh_wbsync` is inert now. For the RTL: `grp_disp` adds queue state (`gdisp_until`, an offset) that the C2
  queue lacks, and the eu's `done_t`, `prev_cls`, `grp_form` and the request's `gdisp` flag (with the
  arbiter's new reads of `dw_moved` and `free_orig`) join A2 for C3/C4.
- **Dead state and unread fields:** `freeze.py` drops what nothing reads under the fit and
  `rtlgen` emits none of it (`since_start` and `refresh_io_pre` included).
- **`_clock_row`'s `pc` and `ir` frames:** fixed in the model (both relative to the chain
  base) rather than corrected in every consumer; B3 compares the fixed row. Done
  2026-10-28 (WP60): `pc` is `eu.pc - eu.origin`; statestats no longer corrects it;
  `freeze --verify` (events and rows) identical over 22,068 runs.
- **C1, the bus unit in RTL (2026-10-28, WP60; docs/v35s-hdl-plan.md):** `v35_biu.sv` from
  `frozen/bus.py`; gate exact on F0/F0w and over the whole corpus. Where the frozen code,
  this spec and the existing model-lane wrapper disagreed, the frozen code was followed:
  (1) `last_fetch_end` needs a 3-bit since-counter, not A2's 1 bit (F23's flush reads
  `t <= last_fetch_end + fgap`, fgap up to 5); (2) `last_end` needs one more bit (`gap`)
  because `disp_io` moves it a clock past the cycle's end; `last_io_end`'s countdown needs
  2 bits (0..3), A2 says 3; (3) the frozen model applies `sfr_cycle=io` only when the chain
  writes RFM (`rfm_writes`), the RTL always treats an SFR-page write as internal, equivalent
  on the corpus whose only on-chip stores are RFM stores; (4) WTC mode 3 is 3 waits with no
  READY in the frozen `waits_of`, 2 waits plus READY in the wrapper: the RTL follows the
  model and has no READY input; (5) the wrapper makes IDB-page (xxE00–xxFFF) and FFFFF data
  accesses internal, reads included; the model makes only writes at FFF00h and up internal,
  as a 3 + I/O-waits cycle: the RTL follows the model; (6) the wrapper asserts /MREQ on I/O
  cycles and the RTL ports that as is, the model saying nothing; (7) the prelude's POP PSW
  read (owner None in `Machine.__init__`) does not fill the data latch on delivery while
  every EU read does, reproduced with `req_latch`, for C6 to revisit since in RTL that read
  is a real EU read; (8) only memory writes (`kind == "write"`) fill the latch, not an
  `io_write`: `wlatch_src`'s row below should read so. The state bundle (`ifdef
  V35S_STATE_DUMP`, 64 bits) carries the A2 representations only: c_valid, c_kind, c_pos,
  c_len, c_ext, c_internal, c_latch, c_addr, c_width, c_data, gap, f_since, io_tail, wl,
  refresh_len. Left for C4/C5: the bus history flags (`_fetch_run`, `grp_io_hold`'s last
  I/O start, `refresh_beat_t4`) and `early`/`early_ok`/`early_n`. The plan's field counts
  are now 222 fields, 217 integers, 35 classes.
- **C2, the queue in RTL (2026-10-28, WP62; docs/v35s-hdl-plan.md):** `v35_queue.sv` from
  `frozen/queue.py` and the queue's store sites in the other frozen machines; gate exact on
  F0/F2/F9/F11 and over the whole corpus (23,612 runs), alone and together with the RTL bus
  unit. The state is the A2 representations (177 bits, 180 since the follow-up below); each queue method is a function of
  the same name; the other machines' touches are 34 op codes in a per-clock chain of 16
  stages. Where the frozen code and this spec disagreed, the frozen code was followed:
  (1) the storage holds 8 bytes inside a clock (a word delivered into 6 stored bytes that the
  decoder takes from on the same clock, `F13-c-out-shlcl16-pO-w0`), so the count is 4 bits and
  the array 8 entries, 7 at most at a clock's end; the room inside a clock goes below A2's -4
  and is computed 5 bits wide; (2) under `word_latch=byte_d` an odd-address one-byte fetch is
  latched too (`latched` on every arrival), not only a word's second byte; (3) the latched
  byte is uncounted on its delivery clock only when the decoder holds the port on that clock
  (`removed_t == t`) and the word is not a slot fetch's (`_latched_now`), otherwise it counts;
  (4) `abort_t` needs a second bit, `abort_t == t`: a start in P after an abort in X on the
  same clock makes `abort_t == start_clock`, and `io_take` sets it to `eu.start_clock`, an
  earlier clock; (5) `after_refresh` needs its offset (3 bits) and a flag "the last issued
  fetch started on `after_refresh`", because `end_clock` compares it with the ending fetch's
  start and `refresh_beat_t4` with the last cycle's start; (6) `io_held` needs "a start since
  it was set" (the release tests `start_clock > io_held`); (7) `retry_at` and `shift_until`
  are set at or before t inside a clock (`retry_first` sets `resume - 2` and clears it at
  once), so the offsets are signed, 10 bits, never negative at a clock's end; (8) `asked`,
  `requesting` and `wants_fetch` are reads that also write `flag` and `requested_at` (A3 lists
  them as combinational): in RTL they are ops in the chain; (9) A3's `wants_fetch` row omits
  the forced request (`io_run_at` / `t4_at == t`), `dropped && drop_hold` and F23's
  `flush_held`; (10) `refresh_io_run=pair_out` also requires no latched byte after the check,
  that the ending fetch is the beaten one (`after_refresh == c.start`) and that `_raised` is
  false; (11) the fetch pointer is the model's 20-bit linear address, not 16 bits plus a
  segment; (12) the A4 rows for `room_ir_ready` and `room_ir_imm` still name the values of the
  register's fit (True, none / M); the fit and the Decisions above say False and P. In joint
  mode the queue takes the bus unit's mid-B3 `done_data` at the end of the delivery clock, so
  its chain is compared after `ce_mid`. Not built, being dead under the fit: `words`, `held`,
  `io_abort`, `snap`, `peak`, `read_t`, `flush_t`, the per-byte usable clocks and `completed`.
  Follow-up (WP63): `grp_disp=hold` (the thirty-seventh fit) adds `gdisp_until`, built as
  `gd_valid` + `gd_off` (2 bits, `rmw.grp_free` is 3) and the op `V35_QOP_GDISP`; 180 bits now.
- **C3, the decoder and the EU in RTL (2026-10-28, WP63; docs/v35s-hdl-plan.md):**
  `v35_decoder.sv` and `v35_eu.sv` from `frozen/decoder.py`, `eu.py`, `templates.py` and
  `machine.py`; gate exact on F1/F2/F3/F9/F11/F12/F20 (5,352 runs) and every refresh-off run of
  the corpus, alone and with the RTL queue and bus unit. The arbiter, the register file and the
  refresh are scripted or not modelled (C4, D, C5). Where the frozen code and this spec
  disagreed, the frozen code was followed: (1) the model decodes the instruction at `pc` from
  the chain image at its start, before the ModR/M and operand bytes are taken; the RTL decodes
  the format from the bytes of the operand record, checks the record is at `pc`, and takes the
  operand values from the register file as an input (A3 has the start reading only the IR's
  opcode); (2) rtlgen gaps: the port take's step word carries the request's setup in `n`, so
  the RTL takes `op_len - 1` bytes; and the templates were enumerated from `decode()` without
  `_start`'s class changes (CMP r/m,reg to nowrite, nowrite to `grp_class`), so the memory
  nowrite formats (81 /7, 39/38, F7 /0) had none: `rtlgen.started()` fixes it, 212 templates
  over 630 formats; (3) `done_at` needs a "past" bit, machine P compares `req.done_at == t`;
  (4) `start_clock` needs a 4-bit saturating age, not A2's 1 bit plus flags (`floor_n`'s
  `not_before`, `io_exec`'s `cur.start == start_clock`, `lookup_start`'s `t == start_clock +
  1`); (5) `hold_done`'s aborted-cycle key is compared again only within the clock, so a
  per-clock flag, and its fetch key a bit cleared when the fetch leaves the bus; (6) the
  decoder keeps its own next-byte address (`taddr`, 20 bits) for the IR's address and the
  ModR/M mate's parity (A2's `modrm_addr` 1 bit is `mate_next`); the IR's address is 0 when
  the IR is empty; (7) the requests are logical positions (slot, q0, q1) that shift on
  `_promote`, `own` a 2-bit index and `port_held` a 3-bit mask shifting with them (A2: 2); the
  slot may be empty while q0 is valid after `_retire`; (8) `wb`, `wb_until` and `done_t` need
  `wb`, `wbu`, `done_v` and `done_age`, not one countdown: `done_t` is stamped when the steps
  end, before the next start computes `wb_until`; (9) `resume` is a 10-bit offset (A2: 6 or
  9) for 510 count-loop clocks plus exec and holds; `start_at` 4 bits; (10) the data latch is
  the bus unit's (C1): the EU reads its busy flag before and after X, ORs in its own same-clock
  fill and outputs fills (T, the X slot, P); (11) the order inside the model's `and` chains
  decides the op stream: `load_ir` reads `available()` before testing `ir_hold`, `imm_start`'s
  room is read with the IR emptied, machine P's EVAL after a held IR load tests `queue.ir_t ==
  t`; (12) WP61 state not in A2: `grp_form`, the request's `gdisp`, the queue's `gdisp_until`;
  (13) dead under the fit and not built: `since_start`/`since_t`/`io_pre`, `stalled`,
  `reg_latch_t`, `ro`, `prev_cls` (refresh only), `seg_prefix` and `sfr` (they arrive with the
  operands), `ls_shift`, `started`, the refresh-only fields; (14) the queue module exposes its
  per-op state only under `V35S_STATE_DUMP` and the joint bench reads the EU's queue views from
  there; a synthesizable core must export them (C4). Bundle widths: `v35_dec_t` 55 (`ir_v`,
  `ir_addr` 20, `taddr` 20, `need` 3, `nx` 2, `ra_off` 2, `ir_hold`, `ea_off` 2, `modrm_next`,
  `mate_next`, `imm_reg`, `stopped`), `v35_eus_t` 218, `v35_req_t` 81 x 3, 516 in all.
- **C4, the arbiter in RTL (2026-10-28, WP64; docs/v35s-hdl-plan.md):** `v35_arbiter.sv`
  from `frozen/arbiter.py` (`arbitrate`, `_choose`, `_fetch_first`, `_fetch_run`, the
  request's `counts`/`ready`/`holding`) and `v35_chain_core.sv`, the five machines with the
  phase chain and its fixpoint in RTL; gate exact on F4/F5/F6/F7/F10/F14/F15/F16/F19/F21/F22/
  F26/F29 (12,642 runs) and every refresh-off run of the corpus (19,850). Where the frozen
  code and this spec disagreed, the frozen code was followed: (1) A2 says the arbiter holds
  no state of its own; the RTL arbiter owns 69 bits (`v35_ast_t`): the request record's
  arbiter-written fields by request position and the bus history C1 left to it; (2) `posted`
  is an 8-bit saturating age (t - posted), not A2's 1 bit plus order flags: `_choose` compares
  `requested_at` with `posted` in four orders and `posted` with t, against the queue's 7-bit
  `rq_age`; a comparison that saturation leaves open raises an error, none on the corpus;
  (3) `_fetch_run` reads the last three or four cycles; the RTL keeps one flag, set at a
  fetch's start when the cycle that ended on t-1 was a fetch, combined with the bus unit's
  `fetch_end_prev` (C5 must leave it unchanged on a refresh start); (4) `grp_io_hold`'s last
  I/O start is a 4-bit saturating age, and its window is exactly the bus unit's `io_win`
  (`recover` is always `io_recover`, 2); (5) `abort_latched` compares the sync's absolute
  target with `queue.completed`; the C3 EU keeps only the fetches still owed, so the RTL tests
  `owed == 0`, the two differing only if the sync is below the completed count, which the
  recorder raises on and never saw; (6) the count of the request handed the slot reads the bus
  after the start (the new cycle's B1, its I/O window): the arbiter computes that view itself
  rather than reading the bus unit's `_x` outputs, to avoid a path back through the bus unit;
  (7) the touch's cycle length (`bus.length`, with C1's SFR-write I/O waits) is computed in
  the arbiter from the WTC and checked by the core against the bus unit's `start_len`; (8)
  `Machine.__init__` starts the POP PSW read before clock 0's phases: the core shows the EU and
  the arbiter a busy "before the choice" view (a read at position 0) on clock 0 and starts it
  on the request port with no data-latch fill (C1 decision 7), where C3's joint bench showed an
  idle bus; C6 should make it a real EU read; (9) the arbiter's own stores of `free_need`
  (`free_run`, `free_hold`, `slot_fetch`) are read by later rules in the same `_choose`, so it
  keeps a working copy of the slot's record within X (A3 lists `free_need` as written only);
  (10) the request record holds `eu_halted`, stored every clock with a request, which A2's
  table lacks; only `refresh_io_stall` reads it, so it is not built; (11) not built because
  they need refresh: `xeu` (`dw_view=eu` runs only with `eu.refresh`), `halt_defer` (halting is
  `halt_now` only), `halt_refresh`'s branches, `after_refresh`/`lost_*`, `io_step_issue`
  (always passes refresh-off), `refresh_lift` (`lift_t` is always set on the lead's first
  clock); (12) a latent C3 point not reached on the corpus: the EU's P-phase `port_ready` reads
  0 for a request posted in T even after the arbiter counted it in X, where the model reads
  the real count. The queue and the EU now export their per-op and per-phase state through
  ports (`v35_queue_pkg`, `v35_eu_pkg`), closing C2's and C3's dump-only notes above. The
  corpus needs at most 6 settle iterations per model clock; the arbiter's queue ops per clock
  peak at 6 of the 8 it holds.
- **F25 in the register (2026-10-27, the thirty-fourth fit):** three new structural
  fields, read by F25's classes only. `lea_form=reg` (LDEA is a register-only form for the
  I/O interlocks and the latch rules; the EU's `mem` flag is off for it; the IR-hold rule
  requires a form with a bus cycle), `burst_wait=data` (PUSH R / POP R: each of the eight
  stack words a data step the EU waits for, which the corrected PUSH R cadence 9 / 10 / 11
  at 0 / 1 / 2 waits requires) and `prepare_order=write_first` (PREPARE's BP write before
  its operand take). Provisional verdict P for all three: each is a template shape the
  F25 facts fix, not a special case; the EU's step table gains the `sent` step
  (`burst_wait=issue`, unused under the fit and so dropped by `freeze`) and ten classes
  with 51 integers (`rtlgen` parameters). The 142 F25 misses, grouped in
  docs/v35s-chains.md, are state reads for the model before any RTL rule; none is ported.
- **F23 and the count mask in the register (2026-10-28, the thirty-fifth fit):** six transfer
  fields read by the five transfer classes only (`refill_start=full_io`, `flush_hold=start`,
  `flush_inflight=wait`, `untaken=wait`, `call_order=write_first`, `branch_reg=reg`), the
  queue's `flush()` (bytes, latch and uncommitted bytes discarded, an in-flight word dropped
  on arrival, the fetch pointer at the target, an odd target fetched at its odd address for
  one byte) and the EU's flush, decide and refill-gate steps: provisional P, each a template
  shape the F23 facts fix, with `refill_start=full_io`'s IN/OUT exception the one narrow
  rule to re-read when F23's 105 misses are. The queue table gains the flush's three
  registers (`discard`, `flush_t`, `flush_held`) and the fetch pointer may now be odd. The
  CL shift count is unmasked (`shift_count_mask=cl8`): the count loop keeps its 9-bit width
  and `Op.cl_count` is a decode bit, not a field.
- **F27 in the register (2026-10-28, the thirty-sixth fit):** the posted I/O request's sequencer
  has steps, every second clock back from its issue (from `setup − 5` after the post, restarted on
  the clock after any bus cycle in the setup, the post clock a step). Four fields read with refresh
  on only, by I/O requests posted while the EU runs: `refresh_io_step=own` (a pending refresh starts
  on a step; beside an OUT whatever the EU's boundaries), `refresh_io_stall=step` (the refresh's last
  clock does not count toward the setup when the count would end on a step), `io_step_issue=step`
  (an IN's I/O after a refresh in its setup issues on a step) and `port_ready=issue` (an I/O counted
  out and waiting only for the bus a port take frees issues there, not relatched). Two values:
  `refresh_io_run=pair_out` (the beaten fetch's pair beside an OUT only, with a byte of room counting
  the decoder's pending take) and `refresh_post=post_beat` (the post-clock hold beside a beaten fetch
  too, given back when that fetch runs ahead of the request). Provisional P for the step mechanism
  (one phase counter in the arbiter's I/O sequencer: a 1-bit step phase reset on the post and on the
  clock after any bus cycle, read by three rules), with `port_ready` and the two values as C:
  candidates to fold into the sequencer's issue condition and the queue's pair rule. The request
  record gains `io_stall`, `eu_halted` and `beat_ext`; `io_step`'s three-cycle look-back for a
  refresh in the setup is a model shortcut the RTL replaces with a "refresh seen in this setup"
  flag. No F27 run overfills; F8, F13 and F17 gain, nothing else changes. The 294 F27 misses (the
  M0 marker OUT at pO w2 under FCh is 67 of them, one state with 19 more in F8 and F13) are state
  reads for the model before any RTL rule.

### The request rule and the queue's room

The queue's fetch request is `room >= 2` evaluated on change clocks (`request_eval=on_change`), with the IR as a seventh slot under conditions. These are the queue's own definition of room; port them as one combinational `room` function (A3 lists its inputs).

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `room_ir=arrival_idle` | the empty IR counts as a seventh slot on a word's delivery clock and whenever the decoder is not mid-take | queue.py:271 | queue | core | `8B C2` odd restarts at 72, even at 75 with MOV CL's immediate outstanding (F0, F2, F9; doc 4755) | 19,142 | P: the room function's definition |
| `room_ir_ready=True` | on a non-delivery clock the IR counts only if the loader can load it by the word's delivery (`decoder.ready_at <= t + fetch length`) | queue.py:283 | queue | special | the F12 A overfill, `F12-a-out-n3-shl1-pO-w1/w2` (doc 4876); st6: the flip is identical on every run | 19,142 | C: inert on the corpus: drop it if `test_fit.FittedConfig.test_fit_json_never_overfills` still passes without it |
| `room_ir_imm=none` | while MOV r16,imm16 (class imm, two immediate bytes) runs, the IR's idle slot is not counted | queue.py:192 | queue | special | 9 of the 11 refresh-on 0-wait prelude cells (`F13-r-rfm-f1-pE-w0`, cfg); st6 −205 | 19,142 | M: keyed on one class and seen only in the prelude's MOV r16,imm16 train: a chain-body ladder of MOV r16,imm16 against MOV r8,imm8 and ADD r,imm16 with the IR empty and room one byte short settles it |
| `hold_count=ahead` | the posted request's fetch hold compares `hold_q` with the queue bytes ahead of the running instruction (its own operand bytes still queued not counted) | arbiter.py:405 | arbiter | core | `F5-out-add_m_imm-k1-pE-w0`, +20 −0 (doc 4840) | 18,179 | P |

### The latched byte and the queue's write port

`word_latch=byte_d` gives the queue a byte-wide write port shared with the decoder's reads and a one-byte latch for a delivered word's second byte. Eight rules then say, case by case, when that byte counts as stored, when it holds the port, and that a byte taken through the port on its delivery clock (an immediate, a port byte, a count byte) arrives a clock late. Proposed cleaner mechanism: model the port explicitly, one owner per clock (decoder read or commit, latch write, EA unit), with the latch byte counted from the clock it is written and every byte taken through the latch on its delivery clock reaching its consumer one clock later; then re-fit these eight enums as one (`word_latch` with the explicit port) and show the 19,142 runs unchanged.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `latch_hold=True` | no fetch starts while a byte delivered on an earlier clock is still latched and cannot go in this clock | queue.py:370 | queue | core | `26 90` even 0 waits, the byte behind a full queue (doc 4754) | 19,142 | P: the port's definition |
| `latch_midtake=True` | the latched byte is counted on its delivery clock when the decoder is mid-take (the IR cannot take it) | queue.py:266 | queue | special | `F12-b-none-n2-addi-pE-w1`, +12 −0 (doc 4880) | 19,142 | C: latched-byte port |
| `latch_disp=True` | the latched byte is also counted on the clock the decoder takes a displacement | queue.py:268 | queue | special | `F21-none-n1-ld-bw_d8-pE-w1`, −159 flipped back (doc 5089) | 19,142 | C: latched-byte port |
| `modrm_mate=imm` | a register form's immediate byte that is the ModR/M's word-mate, taken on a delivery clock, keeps its slot that clock | decoder.py:53 | decoder | special | `F19-d-push-adddwi-outb-pE-w0` (doc 5031) | 19,142 | C: latched-byte port |
| `modrm_port=True` | a ModR/M byte's commit does not hold the write port for a byte latched on an earlier clock | queue.py:231 | queue | special | `F20-r-push-es-movawdw-ld-pO-w0` (doc 5200) | 19,142 | C: latched-byte port |
| `count_latch=True` | a C0/C1 shift operand byte taken on a latched delivery clock with no room for a word: no fetch until the shift's last clock | eu.py:641 | queue | special | F16 S `n1-shli4`, `n2-shli4` pE w1; −57 (F16 S 40, F12 B 6, F15 O 9, F14 O 2; doc 4947) | 19,142 | C: latched-byte port |
| `latch_start=True` | an instruction starting on the clock a byte latched behind a full queue goes in runs its first clocks a clock late | machine.py:197 | EU | special | `F3-push-mov_cl_imm-k4-pO-w0`, 10 of 10 MOV r,imm8 (doc 5203) | 19,142 | C: latched-byte port |
| `imm_landed=True` | a register form's last immediate byte taken on a latched delivery clock: the take sync counts the fetches pending on the next clock | eu.py:688 | EU | special | `F12-b-push-n0-addi-pE-w1`, +48 −0 (doc 4882) | 19,142 | C: latched-byte port |
| `port_landed=True` | a port byte taken on a latched delivery clock holds the waiting I/O a clock longer | eu.py:1162 | EU | special | `F19-d-out-movawdw-outb-pE-w0`, −18 (F19 12, F20 6; doc 5034) | 7,402 | C: latched-byte port |
| `port_issue=True` | a port byte taken on a fetch's issue clock holds the waiting I/O a clock longer | machine.py:178 | EU | special | `F7-out-out_imm_al-out_imm_al-pO-w0` only; 24 of 24 at 1-2 waits and 858 of 858 elsewhere agree either way (doc 5202) | 19,142 | M: shown by one cell (OUT OUT, pO, 0 waits): a port take on a fetch's issue clock after 1- and 2-byte register forms at 0 waits settles whether it is the port or the fetch |

### The aborted fetch cycle

On a clock where the EU starts, takes an operand byte and the IR loads (three queue reads) with room for exactly a word, the bus unit runs a 3-clock aborted cycle and the request is re-raised later. The family is large but each rule is a consequence of treating the aborted cycle as a real bus cycle the take sync waits for and the unit forms count through; port as is, as one aborted-cycle state in the bus unit and one retry latch in the queue.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `abort_fetch=retry` | start, operand take and IR load on one clock with room for exactly a word: a 3-clock aborted cycle, the take sync waits for it, the request is raised again when the next bus cycle ends | arbiter.py:488 | queue + bus | core | two `89 07` even, every 0-wait marker-less F9 miss (doc 4757); without it −1034 (doc 5115) | 19,142 | P |
| `abort_latched=any` | the abort's room test counts a byte still latched after its delivery clock | arbiter.py:483 | arbiter | special | `F16-s-none-cl4-n1-shlcl-pO-w0`, 5 of 5 (doc 5204); `full` identical (st6) | 19,142 | P: part of the abort test's definition |
| `abort_unit=loop` | a memory unit form (shift, MULU/DIVU, PUSH r/m) or a register shift started on an aborted cycle counts one group setup clock during it and raises the dropped request at its loop's exit | eu.py:1104 | EU | special | `F16-r-push-rol-inc_x-pE-w0`, `F16-s-none-cl4-n1-shlcl-pE-w0`; `none` −187, `early` −84, `all` +15 −145 (doc 4946) | 19,142 | P |
| `abort_reg=True` | a register D0/D1/C0/C1 shift, MULU or DIVU started on an aborted cycle runs its exec from the cycle's last clock | eu.py:454 | EU | special | `F3-push-mulu_dw-k2-pE-w0`, `F3-push-shl1-k2-pE-w0`; −36, with SHL AW,CL included −192 (doc 4979) | 19,142 | P |
| `abort_reg_end=early` | that early exec ends early (no clock kept) | eu.py:512 | EU | special | 3 of the 18 aborted-start MULUs show it, `F16-l-push-nop2_mulu_aw-pO-w1`; −5 (doc 1787) | 131 | P: the value without a special case |
| `abort_fixed=True` | a TEST or F6/F7 /0 memory form (group setup by fixed lookup) started on an aborted cycle counts a setup clock during it, as abort_unit's forms | eu.py:1105 | EU | special | `F14-t-none-test_bw_aw-pO-w0`, 15 of 15 (doc 5173) | 19,142 | P: every group form refuted (`abort_unit=all` −145) |
| `retry_first=True` | a count loop of one iteration raises the retried request on its first clock | eu.py:515 | EU | special | `F16-l-out-shl1-pO-w0`, `F16-s-none-cl1-n1-shlcl-pE-w0`; −53 (doc 4975) | 115 | P |
| `refresh_abort=abort` | the abort test applies when a refresh takes the bus on that clock too (nothing but the refresh on the bus) | arbiter.py:220 | arbiter | special | `F18-b-p-n1-mulu-pE-w0`, 29 refreshes; −43 (doc 2643) | 2,142 | P: makes the abort uniform |
| `refresh_abort_retry=next` | a request aborted under a refresh is retried when the next CPU cycle after the refresh ends | queue.py:449 | queue | special | `F18-b-n3-shlmcl-pE-w1`, `F17-s-n3-ld-pE-w1` (doc 5337) | 160 | P: the refresh is no CPU cycle |
| `refresh_abort_wait=run` | the clocks the take sync waits for an aborted cycle are no micro-boundary | eu.py:920 | EU | special | `F18-b-n4-shlmcl-pE-w2`, `F18-b-n7-divu-pO-w1`, 10 rows (doc 5338) | 2,142 | P: the aborted cycle is the EU's own |
| `refresh_retry=end` | the retry clock of a dropped request moves with the EU's refresh holds | eu.py:393 | EU | special | `F17-d-n1-mulu-pE-w0`, 18 rows; −14 (doc 2643) | 2,141 | P: the retry is defined from the step's end |

### The request re-evaluated on a fetch's issue

`request_reissue` re-evaluates the request flag on the fetch's issue clock (the bus unit's back-to-back decision moved into the queue); `nop_hold` and the `no_mem` exception then take it back in two situations, and `refresh_reissue` extends it to a beaten fetch. Proposed cleaner mechanism: let the back-to-back decision (`queue.end_clock`) alone carry the second fetch and drop the reissue, then re-fit the three together; the plan names `nop_hold` as debt.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `request_reissue=no_mem` | on a fetch issue clock that evaluates the flag, it is evaluated again with the in-flight word reserved, except while a memory data request waits in the slot | queue.py:412 | queue | special | `F6-out-ld_bw-n1-pE-w0`, `F1-store-m1-pE-w0` (`always` −41); F6 n1 18/18 (doc 5030) | 19,142 | C: reissue |
| `nop_hold=any` | the request so kept raised on a fetch issue clock where a form without operand bytes started and the IR loaded waits for the next start | machine.py:185 | queue | special | `F19-d-out-movawdw_nop-outb-pE-w0` (doc 5201); `io` +3 −5 (st6) | 19,142 | C: reissue |
| `refresh_reissue=keep` | the fetch a refresh beat is evaluated again on its issue when the beaten clock was an evaluation clock | queue.py:415 | queue | special | prelude only, `F13-c-out-shlcl0-pE-w1`; no chain run changes (cfg) | 1,437 | C: reissue |

### The I/O issue clock and the ALU path

Seven rules say what an instruction may do on and after the clock an OUT's I/O issues: the register-only classes do not start before it (`io_interlock`, which the doc calls the least physical rule of the set), start only on it or after the cycle (`io_busy_start`), run their clocks after it (`io_exec`), load the IR a clock late after a take on it (`io_take_nx`), and requests raised on it are dropped or ignored by the take sync (`io_take`, `sync_io`, `io_ir_hold`). Proposed cleaner mechanism: one `alu_busy` signal from the bus unit (the OUT's datum passes the ALU on the issue clock; the ALU-to-bus path is the I/O's while its cycle runs) that the EU's start, exec, IR load and take sync respect; re-fit the seven as that one signal.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `io_interlock=reg_pfx` | register-only classes and a segment prefix do not start while an OUT's I/O waits in the slot | eu.py:161 | EU | special | F3 OUT NOP OUT, even, 0 waits (doc 4787) | 19,142 | C: `alu_busy` |
| `io_busy_start=issue` | they start only on the I/O's issue clock or after its last clock | eu.py:166 | EU | special | `F3-out-pfx_mov_aw_imm-k1-pE-w0`, +20 −0, every F3 OUT prefix row (doc 4927) | 19,142 | C: `alu_busy` |
| `io_exec=after_io` | a register form started on the I/O's issue clock runs its clocks after its last take only once the I/O cycle has ended | eu.py:468 | EU | special | `F16-l-out-shl1-pE-w0`; `any` −8, `all` −64 (doc 4949) | 19,142 | C: `alu_busy` |
| `io_take_nx=True` | a class reg form's last take on an I/O issue clock delays the IR load a clock (with `reg.nx` 1) | eu.py:610 | decoder | special | `F19-d-out-movawdw-outb-pE-w0` 64 of 64, `F20-r-push-es-none-movr-pO-w0` 13 of 13 (doc 5199) | 19,142 | C: `alu_busy` |
| `io_take=unit` | a request first raised on an I/O issue clock by a latched delivery with a register form's last take (or while a memory MULU/DIVU runs) is dropped and raised at the loop's exit | eu.py:328 | queue | special | `F16-l-out-shlcl4-pO-w0`, `F14-g-out-mulu_bw-pO-w0`; `none` −81, `drop` −18 (doc 4974) | 19,142 | C: `alu_busy` |
| `sync_io=unit` | the take sync ignores a request raised on the I/O's issue clock when the take filled the data latch or is a register MULU/DIVU's | eu.py:672 | EU | special | `F15-o-out-movr_ld-pE-w0`, +74 −10 (doc 4928); `latch` −27, `issue` identical (st6) | 19,142 | C: `alu_busy`; `issue` (every take) is already equivalent |
| `io_ir_hold=True` | a request first raised by the IR load on an I/O issue clock goes no earlier than the next start | machine.py:162 | queue | special | `F12-a-out-n1-imm-pE-w0`, +9 (F3 OUT 6, F12 A 3; doc 4905) | 19,142 | C: `alu_busy` |

### The start against a fetch

An instruction start is held off a back-to-back fetch's issue clock (`start_sync=b2b_modrm`, `io_b2b` below `io_b2b_q` stored), and two more rules hold an I/O, ModR/M or immediate memory form off an older fetch or the fetch its own start raises at a shallow queue. Proposed: port `start_sync` and `io_b2b` as is; merge `io_older` and `imm_start` into one rule (a start whose first queue read races an issuing fetch with `io_b2b_q` or fewer stored waits it out) and re-fit.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `start_sync=b2b_modrm` | a form with a ModR/M byte does not start on a back-to-back fetch's issue clock | eu.py:156 | EU | core | F6 at 2 waits; `F12-a-out-n1-movr-pE-w1`, +51 −0 (doc 4879) | 19,142 | P |
| `io_b2b=all` | any other form does not either while fewer than `io_b2b_q` bytes are stored | eu.py:204 | EU | special | `F7-out-mov_aw_dw-mov_aw_dw-pE-w1`, `F19-d-out-adddwi-inb-pE-w0`; `io` −12 (doc 5032) | 19,142 | P |
| `io_older=io_modrm` | an I/O or ModR/M form waits out an older fetch issuing on its start clock with fewer than `io_b2b_q` stored | eu.py:187 | EU | special | `F19-i-out-l0-stimm-pO-w0`, `F21-out-l0-sti-bw_d16-k2-pO-w0`; MOV r,imm and PUSH 100 of 100 (doc 5114) | 19,142 | C: one shallow-queue start rule |
| `imm_start=wait` | a ModR/M memory form with an immediate whose start raises a fetch on a delivery clock with `io_b2b_q` or fewer stored waits that fetch out | eu.py:192 | EU | special | `F21-out-l0-sti-bw_d8-k2-pE-w0`, 9 of 9 (doc 5145) | 19,142 | C: one shallow-queue start rule |
| `reg_div=True` | the register DIVU is one of the interlocked register-only classes, as MULU | eu.py:303 | EU | micro | `F16-l-out-divu_ix-pE-w0`, −6 (doc 4973) | 156 | P: a class bit |
| `dw_port=hold` | a port-form IN/OUT does not start while a DW-form I/O waits behind another I/O or the I/O ahead of it is on the bus | eu.py:173 | EU | special | `F19-d-out-none-outb-pO-w0`, −30 (F19 D 20, F5 10; doc 5010) | 19,142 | P |

### The bus unit's data latch

A datum occupies the data latch for `wlatch` clocks; a port-form IN/OUT does not start while it is busy and the bus unit is reserved for it meanwhile. Core rules port as is. `wlatch_ir`, `wlatch_ir_at` and `wlatch_mul` are inert on the corpus (st6: the flip of `wlatch_ir` or `wlatch_mul` alone is identical on every run): drop them.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `wlatch_cls=port` | the IN/OUT forms with a port byte do not start while the data latch is busy; the DW forms start at once | eu.py:181 | EU | core | F5 PUSH then IN AL,imm; holding the DW forms too −882 (doc 4801) | 19,142 | P |
| `wlatch_src=write_imm_read` | read data (memory or I/O) occupies the data latch from its delivery clock, as a memory write from its issue (an I/O write does not fill it; C1) | eu.py:1270 | bus | core | F5 `MOV [BW],AW` then OUT (doc 4800) | 19,142 | P |
| `wlatch_imm=reg_last` | a register-only form's last operand byte (ModR/M, immediate) enters the data latch on its take | eu.py:628 | EU | special | `F12-a-out-n2-movr-pE-w0`, +28 −0 (doc 4878) | 19,142 | P |
| `wlatch_hold=True` | while an I/O instruction waits at its start for the data latch, no fetch starts | arbiter.py:416 | arbiter | core | F7 load then PUSH under the OUT marker (doc 4802) | 19,142 | P |
| `refresh_wlatch=hold` | nor does a refresh | arbiter.py:210 | arbiter | special | `F18-a-out-fd-empty-pE-w0`, 17 rows (doc 5459) | 2,142 | P: as `wlatch_hold` |
| `slot_latch=True` | the left-out write's slot fills the data latch as the write would | eu.py:1228 | EU | special | `F19-i-out-l0-cmpimm-pE-w0`, 34 of 34 at w0; −56 (doc 5172) | 570 | P |
| `wlatch_ir=True` | a register form's take sync lapses while the latch it filled will still hold the I/O form in the IR at its start | eu.py:359 | EU | special | `F14-o-out-movr-pE-w0` (doc 4902); st6: flip identical on every run | 10,485 | C: drop (inert) |
| `wlatch_ir_at=start` | only while that latch is still busy at the end of the running form's own clocks | eu.py:363 | EU | special | `F2-out-empty-pE-w0` under `prelude_tail=segs`; `busy` −3,234 (st6) | 10,197 | C: drop with `wlatch_ir` (the pair is inert) |
| `wlatch_mul=none` | a register MULU's ModR/M does not enter the data latch | eu.py:632 | EU | special | `F3-out-mulu_dw-k1-pE-w0` (doc 4902); st6: flip identical on every run | 576 | C: drop (inert) |

### A posted request's fetch-free setup window

A posted memory request holds fetches during its setup (`hold_fetch=le_q`), and its last `setup_free` clocks must be fetch-free. Seven rules then say which fetch may still run at the window's edge (on a delivery clock, back to back, after an I/O, inside the EA clocks) and what it costs (an idle clock, the request first). Proposed cleaner mechanism: one window state machine per posted request (counting, eve, free, issuable) with the fetch's provenance (run, back to back, fresh on a delivery clock) as its only inputs; re-fit `free_run`, `free_hold`, `free_idle`, `slot_fetch` and `imm1_first` as that machine. `free_idle_b2b` and `grp_io_hold` rest on two and six runs: re-measure.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `arbiter=b2b` | with an issuable data request and a fetch request on a free bus, data goes first unless the fetch was committed back to back on the previous fetch's last clock or both requests arose on this clock | arbiter.py:287 | arbiter | core | F1 store train at 1 wait, 83 F 87 F 91 W (doc 4761) | 7,506 | P |
| `hold_fetch=le_q` | a posted, not yet issuable data request holds fetches while the queue counts more than `hold_q` bytes | arbiter.py:398 | arbiter | core | PUSH after NOP, even, 1 wait (doc 4762) | 19,142 | P |
| `free_run=run` | a posted memory request already in its fetch-free clocks lets a fetch first requested on a fetch's delivery clock run, counting through it | arbiter.py:347 | arbiter | special | `F16-p-push-n0-pop_bw-pE-w1`; `none` −62, `any` −85 (doc 4948) | 19,142 | C: window machine |
| `free_hold=delivery` | on the clock before its first fetch-free clock it holds a fetch first requested there (a non-run delivery clock, not back to back); the fetch dates from the next clock | arbiter.py:355 | arbiter | special | `F21-none-l0-sti-bw_d16-pO-w0`, `F19-i-push-n1-stimm-pO-w0` (doc 5112) | 19,142 | C: window machine |
| `free_idle=True` | a run's delivery-clock fetch let go at that eve is followed by an idle clock before the request | arbiter.py:533 | arbiter | special | `F21-push-l0-sti-bw_d16-pE-w0` (doc 5113) | 19,142 | C: window machine |
| `free_idle_b2b=True` | so is a fetch committed back to back at that eve | arbiter.py:520 | arbiter | special | the only two such fetches, `F21-out-l0-sti-bw_ix_d16-k2-pE-w0` and `-push-...-k2-pO-w0`; −2 (doc 1787) | 19,142 | M: two runs: base+index+d16 immediate stores at k = 2 under both markers at 1-2 waits settle it |
| `slot_fetch=slot` | a request that moved into the slot behind an I/O holds an older fetch until its fetch-free clocks start, then lets it run through them | arbiter.py:383 | arbiter | special | `F15-p-out-pop_bw-pE-w0`; −42 (F5 9, F14 G 6, F15 P 24, F16 P 3; doc 4980) | 19,142 | C: window machine |
| `imm1_first=hold` | a one-byte-immediate memory form's first request issuable on a non-run delivery clock goes before the fetch requested there while the queue counts more than `hold_q` | arbiter.py:288 | arbiter | special | `F22-none-l0-add8_d16-pO-w0`, 34 of 34; −34 (F22; doc 4190) | 7,506 | C: window machine |
| `grp_io_hold=True` | while an I/O cycle or its recovery keeps a group request's bus-free clock from counting, a fetch requested on or after the I/O's issue waits | arbiter.py:368 | arbiter | special | the six `F14-t-out-test_dir_aw` cells; −6 (doc 1787) | 19,142 | M: six cells of one form: group memory forms with a bus-free group clock behind the OUT marker at pO (INC [BW], NOT [BW], SHL [BW],1) settle whether it is the group clock or TEST's lookup |
| `grp_disp=hold` | a group RMW form without an immediate with a d16 displacement: no fetch on the displacement take clock and the `grp_free` clocks after it (a committed back-to-back one goes; on the take clock one with room for two words), the take sync waits only for a fetch on the bus, a fetch no older than the read waits for the read's fetch-free clocks to start, which count through a fetch but not an I/O | eu.py:719, arbiter.py | EU, arbiter, queue (`gdisp_until`) | micro | `F29-out-ec-gih-incd16-n1-pO-w0`, n0-pO, n1-pE; none −79 F29 | | P (2026-10-28, WP61); the queue's `gdisp_until` is a C2 follow-up (WP63) |
| `rmw_alu=through` | an RMW write's ALU clocks count through a fetch in flight; its routing clocks and its last need a fetch-free bus | eu.py:1211 | arbiter | special | `F21-out-l0-add-bw_d16-pE-w0` (doc 5144) | 2,100 | P |
| `grp_free_bus=True` | a group form's setup clocks count on no clock of an I/O cycle or its recovery, and its free clocks only on an idle bus | eu.py:1202 | arbiter | core | F5 OUT then INC [BW], +67 (doc 4804) | 5,526 | P |

### The I/O request in the bus unit's slot

The OUT posts its I/O into the slot and goes on; the request counts its setup on clocks with no memory wait state, holds fetches, commits the bus for its `lead`, and recovers `io_recover` clocks. Port as is: these are the I/O mechanism the fifth and sixth fits found and every OUT-marked family exercises.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `io_count=nowait` | an I/O request's setup counts every clock on which no memory cycle is in a wait state | eu.py:1201 | arbiter | core | F2 OUT after NOP NOP, even, 1 wait (doc 4784) | 19,142 | P |
| `io_hold=posted_b2b` | a posted I/O holds fetches after its post clock whatever the queue holds, except a back-to-back fetch; a fetch requested no later than the I/O may run on the lead's first clock | arbiter.py:402 | arbiter | core | F2 OUT after NOP; F1 single OUT; MOV AW,imm16 even 1 wait (doc 4785) | 19,142 | P |
| `io_recover=2` | no memory data cycle until `io_recover` clocks after an I/O cycle's last; the request holds fetches meanwhile | arbiter.py:341 | arbiter | core | F4 OUT then load, odd, 0 waits (doc 4788) | 19,142 | P |
| `port_latch=relatch` | one port latch: a port byte taken while an I/O waits holds that I/O to take + `relatch`; the taker posts after that cycle ends | eu.py:1158 | EU | core | F1 two OUTs; the alternatives lose 149 (doc 4786) | 7,402 | P |
| `port_ready=issue` | an I/O whose setup has counted out and which waits only for the bus freed on a port take's clock issues there and is not relatched | eu.py `_port_take` | EU | special | `F27-out-fc-empty-pE-w1`; relatch −16 F27, −3 F8 | F27 FCh, F8 | C: fold into the issue condition (no refresh-off run has the state) |
| `dw_count=bus` | a DW-form I/O does not count a setup clock on which a bus cycle starts, on its post or move-in clock | arbiter.py:143 | arbiter | special | `F5-push-in_al_dw-k1-pO-w0`, +10 (doc 4843) | 19,142 | P |
| `dw_count_b2b=True` | nor, when posted at its own start, a clock a back-to-back fetch starts on | arbiter.py:150 | arbiter | special | `F19-d-out-movawdw-inb-pE-w0`; −12 (doc 5033) | 19,142 | C: fold into `dw_count` as one rule |
| `dw_slot=behind` | a DW-form I/O moved into the slot runs before the lead's fetch when another request is posted behind it and the queue counts more than `hold_q` | eu.py:1150 | arbiter | special | `F19-d-push-pair-outb-pO-w0`; −21 (doc 5011) | 114 | P |
| `dw_lift=moved` | a DW request that moved into the slot on the issue of the I/O ahead does not let a fetch first requested on that clock run on its lead's first clock | arbiter.py:524 | arbiter | micro | `F29-out-ec-dio-dw-stbwd8-n0-pO-w0` (G1, every pO dw cell); posted −39 F29 | | P (2026-10-28, WP61) |
| `disp_io=extend` | a displacement taken on an I/O cycle's issue clock extends that cycle a clock (nothing starts after its last; its recovery counts from there) | arbiter.py:137 | bus | special | base+index+d16 only, 78 takes in the OUT frame; `F21-out-l0-ld-bw_ix_d16-pE-w1` (doc 5142) | 19,142 | M: one EA mode in one frame: d8 and base+d16 forms timed to take on the I/O's issue clock (a leading NOP count ladder under the OUT marker) settle whether it is the take or the base+index adder |
| `halt_status=True` | the clock HALT starts is the bus unit's: a request in the slot does not count it | arbiter.py:119 | bus | special | F10 84 → 174/204 (doc 4862) | 19,142 | P |

### The effective-address path

The EA unit's clocks and the displacement's take. The table entries and the take width are microcode; the floors are data-cycle lower bounds the template cannot express.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `disp16=word` | a two-byte displacement is taken in one clock when both bytes are queued | templates.py:355 | decoder | micro | 154 of 172 single-instance F21 cells (doc 5056) | 12,108 | P: a decoder take width |
| `ea_disp16=own` | base+index with a d16 runs its own EA integer | templates.py:532 | EU | micro | 132 of 160 F21 cells (doc 5057) | 12,162 | P |
| `ea_direct=base_disp` | a direct address behind a ModR/M byte runs the base+d16 EA entry | templates.py:534 | EU | micro | 480 of 480 F21 cells; −125 +1 (doc 5058) | 11,550 | P |
| `late_read=True` | the decoder does not serve an instruction's last operand byte and the IR load on one clock while a fetch is past its second clock: the take waits for the word | eu.py:596 | decoder | special | F9 382 → 408/408, F11 96 → 128/132; fires in about 1,000 runs (doc 4863) | 19,142 | P |
| `late_disp=all` | the same late take for every memory form's displacement | eu.py:599 | decoder | special | `F21-none-n1-ld-bw_d8-pO-w1`; −605 (doc 5087) | 2,712 | C: fold into `late_read` as one read-port rule |
| `sync_req=disp` | no take sync after an immediate memory form's displacement (its write's group setup counts through the fetch the take frees); a displacement due on a fetch's late clocks waits for that word (eu.py:598) | eu.py:681 | EU | special | `F21-none-l0-sti-bw_d8-pO-w0`, `F21-none-n1-sti-bw_d8-pE-w1` (cfg; doc 4841) | 19,142 | P |
| `ir_load=disp_data` | a ModR/M memory form with a displacement keeps its successor in the queue (no IR load, no IR slot) until its first data cycle issues, unless the displacement was taken on a delivery clock | eu.py:277 | decoder | special | `F21-none-l0-ld-bw_d16-pO-w0` and its control (doc 5086) | 19,142 | P |
| `ea_ir_room=True` | the IR is no room inside a displaced form's EA clocks before the take | queue.py:278 | queue | special | `F21-push-l0-ld-bw_ix_d16-pE-w0`, 0 of 18 cells fetch (doc 5143) | 3,540 | C: with `ea_b2b`: the EA unit owns the queue port in its clocks |
| `ea_b2b=True` | no back-to-back fetch on an EA clock before the displacement's take | arbiter.py:394 | arbiter | special | `F21-out-l0-st-bw_ix_d16-k2-pE-w0`, 3 cells; −3 (doc 1787) | 19,142 | C: with `ea_ir_room` |
| `disp_floor=posted` | the first data cycle no earlier than `dfloor` clocks after the displacement's take; a request already posted (POP r/m's write) floored too | eu.py:623 | EU | special | `F21-none-es-ld-bw_d8-pE-w1`, −271; `F21-none-n1-pop-bw_ix_d16-pE-w1` (doc 5088) | 11,706 | P |
| `ea_floor=True` | a mod 00 form is floored the same way from its address step | eu.py:246 | EU | special | `F21-none-es-ld-bw-pE-w0` (doc 5115); st6: flip identical on every run | 19,142 | C: drop (inert) |
| `imm_count=start` | an immediate memory form's first request issues no earlier than `istart` + its immediate bytes after its start | eu.py:256 | EU | special | F19 I; −138 (F19 I 133, F5 5; doc 5008) | 19,142 | P |
| `post_on_take=nomodrm` | only a form without a ModR/M byte (A1/A3) posts its request on the address take | eu.py:664 | EU | micro | `[BW+d16]` even; F4 170 → 213 (doc 4770) | 19,142 | P |
| `disp_take=end` | POP r/m's one-byte displacement is taken where a two-byte one's last byte is | templates.py:661 | EU | micro | `F15-p-out-pop_bw_d8-pO-w0`; −11 (F15 P 6, F16 P 5; doc 4981) | 1,002 | P |
| `pop_mem_order=stack_post` | POP r/m: the stack read first, the memory write posted as its data arrives with the EA in its setup, the displacement taken while it waits | templates.py:649 | EU | micro | `F15-p-push-pop_dir-pO-w0`; +85 (F5 13, F14 G 8, F15 P 64; doc 4922) | 1,002 | P |
| `push_mem_write=at_data` | PUSH r/m's stack write posted on the read data's arrival | templates.py:639 | EU | micro | `F15-p-out-push_bw-pO-w0`; +22 (doc 4923) | 192 | P |
| `rmw_shift=shift` | a shift RMW adds the shift unit's clocks to its ALU step | templates.py:628 | EU | micro | SHL [BW],1 odd (doc 4773) | 336 | P |
| `shift_count=late` | C0/C1 take the count byte `cpre` clocks after the ModR/M byte (chained, no sync) | templates.py:572 | EU | micro | `F12-b-none-n3-shli-pE-w0`, +18 −0 (doc 4881) | 390 | P |
| `shift_cl_mem=count` | a memory shift by CL adds `grpcl` setup clocks, all fetch-free | templates.py:420 | EU | micro | every framed `SHL [BW],CL`, F14 +18 (doc 4904) | 19,142 | P |

### Group and fixed-operation forms

Format properties of the encoding (the reg field selects the operation; TEST's operation is named by no ALU-op field): all microcode, generated into the step lists.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `grp_ops=fixed` | TEST 84/85 (no ALU-op field names its operation) takes the group setup | templates.py:426 | EU | micro | `F14-t-push-test_bw_aw-pE-w0`, all 18 framed cells (doc 4900) | 19,142 | P |
| `grp_fixed=test` | F6/F7 /0 TEST r/m,imm: TEST 84/85's setup, then `fgrp` more | templates.py:457 | EU | micro | `F15-a-push-test_bw_imm-pE-w0`; +26 (doc 4924) | 5,526 | P |
| `imm8_grp=own` | 83 /x (one-byte immediate) runs its own `grp1` setup | templates.py:417 | EU | micro | `F15-a-push-and_bw_imm8-pO-w0`; +16 (doc 4926) | 19,142 | P |
| `fixed_lookup=decoder_nowait` | TEST 84/85 with a displacement: `fdisp` lookup clocks between the ModR/M and the displacement, not counted in a memory wait state | templates.py:437 | decoder | special | `F15-a-push-test_dir_aw-pO-w0`; +21 (F14 T 12, F15 A 9; doc 4925) | 5,526 | P |
| `fixed_lookup_grp=group` | F7 /0 with a displacement runs the same lookup | templates.py:438 | EU | micro | `F22-none-l0-test_d16-pO-w0`; −109 +1 (doc 4190) | 168 | P |
| `fixed_floor=True` | TEST r/m,imm16's floor counts `fgrp` more clocks | eu.py:261 | EU | special | `F15-a-none-test_bw_imm-pO-w0`, 12 of 12 (doc 5174) | 4,542 | P |
| `lookup_start=True` | the lookup costs a clock more when a fetch issued on the start clock | eu.py:570 | EU | special | `F14-t-push-test_dir_aw-k2-pE-w0` and its pO twin (doc 5175) | 150 | M: two cells: TEST [0C00h],AW at k = 1 and 2 with and without a start-clock fetch at every wait settles whether the lookup or the decoder pays the clock |
| `dest_route=slot` | CMP r/m,reg (d = 0) runs the RMW template with the write left out and its slot kept | eu.py:144 | EU | micro | `cmp_bw_aw` w100 (F14 T; doc 4901) | 19,142 | P |

### The left-out write's slot

CMP and TEST read like an RMW and write nothing: the template keeps the write's bus slot, which carries a fetch when the queue has room for a word and otherwise is no bus cycle. Port as is.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `grp_read=rmw_slot_any` | a group form that reads and does not write runs the RMW template with the write's slot kept; the slot carries a fetch when the queue has room | arbiter.py:471 | arbiter | micro | `F5-push-cmp_m_imm-k1-pO-w0` (doc 4838) | 570 | P |
| `slot_room=word` | the slot fetches only with room for a word, not counting a word delivered on the slot clock | arbiter.py:467 | arbiter | special | `F19-i-push-l0-cmpimm8-pE-w0`; 31 of 31 and 266 of 266 (doc 5170) | 570 | P |
| `slot_idle=eu` | a slot with no fetch is no bus cycle: the EU goes on `sidle` clocks after it | eu.py:1232 | EU | special | `F19-i-push-l0-cmpimm8-pE-w1`, 12 of 12; −59 (doc 5171) | 70 | P |

### HALT, the prelude and the SFR store

Rules that fire only in the END block's HALT, the prelude's POP PSW or the RFM store (Phase C5 and C6).

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `halt_refresh=run_drop` | in HALT the fetches a refresh held off before HALT still run; one beaten after HALT started is dropped | arbiter.py:335 | arbiter | special | `F13-s-shlcl7-pE-w2`; −28 (doc 5259); `none` −520, `run` −78 (st6) | 2,142 | P: Phase C5 |
| `refresh_halt=status` | the halt status holds the bus on HALT's first two clocks: a request pending on the first goes at once and the status follows it, none goes on the second | arbiter.py:198 | arbiter | special | 310 END-block requests; −315 (doc 2285) | 2,142 | P: Phase C5 |
| `sfr_setup=count` | the SFR store's write request counts every setup clock, a fetch in flight or not | eu.py:1204 | arbiter | special | `F17-w-ec-n2-pE-w1`, 34 rows; −21 (doc 3193); st6: identical on every run (carried by the prelude tail since the thirty-first fit) | 19,142 | C: drop (inert) |
| `pop_refresh=stall` | a refresh inside the prelude's POP PSW clocks after its read stalls them by its length less 2 | eu.py:119 | EU | special | every refresh-on prelude cell (cfg); −7 (st6) | 19,142 | P: Phase C6 |

### Refresh: the EU's micro-boundary map

With refresh on, the EU takes a pending refresh and holds for one only on its micro-boundaries (`refresh_eu=hold`, `refresh_accept=boundary_bus`). Twenty fields then define, clock by clock, which clocks of which steps are boundaries. Proposed cleaner mechanism: a boundary bit (and a hold-point bit) per clock of every step, generated by `rtlgen` from the configuration into the step tables, so the RTL has one rule (`hold at the next boundary while a refresh it let through is on the bus`) and the per-situation logic becomes table data; the equivalence is the state rows (B3) on the 2,472 refresh-dump runs. `refresh_exec=every2_recent`'s recent window is not read under `refresh_loop_hold=entry` (it ties with `every2`): port as `every2`.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `refresh_eu=hold` | the EU does not pass a micro-boundary while a refresh it let through is on the bus | eu.py:385 | EU | core | F13 series R (cfg) | 2,142 | P: the one rule the map serves |
| `refresh_accept=boundary_bus` | a pending refresh is taken in a clocks step on its boundaries; while the EU waits on a posted data request only when the bus unit would start a cycle or on the window's first clock; on any other wait at once | eu.py:915 | EU | core | `F8-push-empty-pE-w0`, `-w2` (cfg) | 2,142 | P |
| `unit_hold=True` | a register shift, MULU or DIVU in its exec waits at a micro-boundary (every second exec clock from `hphase`) while a fetch or an aborted cycle is past its second clock, until the clock after its last | eu.py:478 | EU | special | `F16-l-out-shli4-pE-w1`, `F16-l-push-mulu_aw-pE-w1`; −127 (doc 4976) | 19,142 | C: the same boundary hold as the refresh's: one rule, the bus's late fetch clocks and a refresh both holding the unit at its boundaries |
| `refresh_clk_start=after_wait` | a clocks step's first clock is a boundary only at a start or after a wait, not straight after a take | eu.py:491 | EU | special | `F8-out-empty-pO-w0` (cfg) | 2,142 | C: boundary bits |
| `refresh_hold_take=port` | an operand take is no hold point unless it is a port byte's | eu.py:853 | EU | special | `F8-out-empty-pE-w0` (cfg) | 1,254 | C: boundary bits |
| `refresh_take=last` | a multi-byte take takes a refresh only on its last byte's clock | eu.py:924 | EU | special | `F17-d-n0-shlcl16-pE-w0` (cfg) | 2,142 | C: boundary bits |
| `refresh_take0=none` | the empty take that ends a form without operand bytes is no step: that clock is the next start | eu.py:822 | EU | special | `F17-s-n0-nop8-pE-w0`, 771 NOP rows; −190 (doc 2643) | 2,085 | C: boundary bits |
| `refresh_take_seam=seam` | a clocks step between two takes, due on the clock after the first, is no hold point | eu.py:840 | EU | special | `F18-b-n3-shli4-pE-w1` (doc 5341) | 1,966 | C: boundary bits |
| `refresh_take_latch=hold` | a take while a delivered byte waits latched behind a full queue is a hold point | eu.py:848 | EU | special | `F13-n-none-nop8-pE-w2`, 8 rows; −8 (doc 3379) | 1,966 | C: boundary bits (and the latched-byte port) |
| `refresh_wbsync=seam` | the write-back sync's clocks are no hold point | eu.py:828 | EU | special | `F8-out-empty-pE-w0` (doc 5339) | 2,047 | C: boundary bits; inert since the thirty-seventh fit (`refresh_wb=free_wait` subsumes it: `wait` is an exact tie) |
| `refresh_disp=free` | the clocks step after a displacement's take and the post after it are no hold point | eu.py:846 | EU | special | `F17-p-n1-shlcl31-pO-w1`; −6 (doc 2285) | 1,966 | C: boundary bits |
| `refresh_loop_entry=open` | a count loop's first clock takes a pending refresh | eu.py:937 | EU | special | `F13-s-shlcl3-pE-w0` (cfg) | 2,142 | C: boundary bits |
| `refresh_loop_hold=entry` | the loop's eve is no boundary; the loop's first clock is the hold point | eu.py:833 | EU | special | 310 refreshes on the exec's L−4 boundary; −202 (doc 3193) | 2,118 | C: boundary bits |
| `refresh_exec=every2_recent` | the shift's exec has a boundary every second clock (the eve's recent window is not read under `entry`) | eu.py:893 | EU | special | `F17-d-n1-shlcl16-pE-w0`, +55 −0 (cfg); ties `every2` under `entry` (doc 3193) | 1,568 | C: boundary bits, as `every2` |
| `refresh_mul=loop_odd` | a register MULU's exec is a count loop with boundaries an odd number of clocks before its end | templates.py:498 | EU | special | F13 series U, `F13-u-push-mulu-k2-pO-w1` (cfg) | 408 | C: boundary bits |
| `refresh_mul_exit=exit` | its last `rexit` clocks run as the loop's exit (boundaries an even number before the end) | templates.py:501 | EU | special | `F17-s-n2-mulu-pE-w0`; −188 (doc 2643) | 408 | C: boundary bits |
| `refresh_unit=muldiv` | the register DIVU's exec is the same unit's count loop | eu.py:785 | EU | special | `F18-b-n0-divu-pE-w0`, +3 exact (cfg) | 2,142 | C: boundary bits |
| `shift_exit0=exit` | the D1 shift (exec0) runs the C1 form's exec head; the clock it lacks is its exit's | eu.py:416 | EU | special | `F18-b-n2-shl1-pE-w1`, 17 rows; −33 (doc 2643), −44 (st6) | 2,142 | C: boundary bits |
| `refresh_rmw_loop=loop` | a memory shift's write setup takes a refresh on its iteration boundaries and waits it out | eu.py:929 | EU | special | `F18-b-n1-shlmcl-pE-w2`, +63 events (cfg) | 2,142 | C: boundary bits |
| `refresh_rmw_span=all` | within all the shift unit's clocks after the read | eu.py:227 | EU | special | F18 B memory shifts (cfg) | 336 | C: boundary bits |
| `refresh_rmw_shape=shift` | with the register shift's shape end-aligned to the write's issue | eu.py:905 | EU | special | 96 silicon memory shifts (doc 5335) | 96 | C: boundary bits |
| `refresh_grpcl=step` | a memory shift by CL's read takes a refresh on the first `grpcl` clock; its setup counts through the refresh | eu.py:1094 | EU | special | `F18-b-n4-shlmcl-pE-w0` (doc 5336) | 96 | C: boundary bits |
| `refresh_post=post_beat` | a posted memory request takes a refresh on its post's first clock, its setup counting through it, the EU holding at the next boundary; beside a beaten fetch the hold stays unless that fetch runs ahead of the request on the clock after the refresh (thirty-sixth fit; `post` before) | eu.py:947 | EU | special | `F13-c-push-shlcl2-pO-w0`, `F17-c-push-empty-pE-w0` (doc 5340) | 2,142 | C: boundary bits |
| `refresh_wb=free_wait` | an instruction held at its end by a refresh is dated from the clock its steps ended, its write-back running under the refresh; a port-form OUT's wbsync clocks take no refresh (the OUT's third clock) | eu.py:427 | EU | special | `F28-out-fc-fence-cl27-n0-pE-w0` (A), `-cl26-` (B); hold −2 F8 −41 F13 −78 F27 −194 F28, free −14 F13 −17 F27 −77 F28 (doc, the thirty-seventh fit) | | P (2026-10-28, WP61) |
| `refresh_relatch=issue` | a pending refresh beside a counted-out I/O held by a port take's relatch goes on the relatched issue clock | arbiter.py:262 | arbiter | special | `F28-out-fc-fence-cl27-n0-pE-w0`; free −7 F27 −53 F28 | | P (2026-10-28) |
| `refresh_window=posted` | `refresh_post`'s window-start boundary uses the window as posted (`free_orig`) after `free_run` cleared it | eu.py:1019 | EU | special | `F28-push-fc-tail-shlcl8-outb-n0-pO-w0`; need −5 F27 −30 F28 | | P (2026-10-28) |
| `refresh_start_seam=start` | a clocks step beginning on the start clock after a ModR/M taken there keeps the start's boundary | eu.py:527 | EU | special | `F28-out-fc-beat-adddwi-n1-k1-pE-w0`; seam −6 F27 −22 F28 | | P (2026-10-28) |
| `refresh_step_lead=step` | with `refresh_io_step=own` a step on a port lead's first clock takes the refresh over the older fetch, which becomes the lead's and waits for the issue | arbiter.py:249 | arbiter | special | `F28-out-fc-fence-cl24-n0-pO-w0`; lead −1 F8 −2 F17 −4 F27 −22 F28 | | P (2026-10-28) |

### Refresh: the beaten and lost fetch request

A refresh that takes the bus from a fetch request either lets it run next (`refresh_after`) or, with odd room and a latched byte, loses it until an evaluation event. `refresh_lost` and `refresh_reraise` add the instruction start and the unit's last loop iteration as such events. Proposed cleaner mechanism for those two: make the instruction start and the loop exit evaluation clocks of the request flag in general (`request_eval`), not only for a lost request, and re-fit.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `refresh_after=fetch_next` | a fetch request a refresh beat goes on the clock after the refresh, ahead of a posted I/O and its hold | arbiter.py:438 | arbiter | core | `F8-out-empty-pE-w2` (cfg) | 1,775 | P |
| `refresh_drop=True` | a request raised on the clock a refresh takes the bus is dropped (under `refresh_drop_on`) and raised again on the queue's next change or a starved take | arbiter.py:241 | arbiter | core | F13, F17 (cfg) | 1,852 | P |
| `refresh_drop_on=odd` | only one raised by a delivery whose second byte is latched, leaving an odd room | arbiter.py:242 | arbiter | special | F17: room 3 loses it in 82 + 14 runs, room 4 keeps it in 47 + 34 (cfg) | 1,840 | P |
| `refresh_drop_unit=unit` | also, inside a register unit's clocks, one leaving room for exactly a word; one lost in a shift's exec comes back at the next start | arbiter.py:244 | arbiter | special | `F17-s-n1-rmw-pE-w2`; −9 (doc 3193) | 1,496 | P since 2026-10-28 (F27 −6 flipped; was M: nine runs: a refresh on a delivery clock with room 2 inside SHL AW,CL's exec and loop and MULU's loop at 2 waits settles it |
| `refresh_drop_post=hold` | on the clock an IN/OUT posts its I/O after its start, that request stays raised as one no younger than the I/O | arbiter.py:233 | arbiter | special | 16 runs, F18 A FCh at 2 waits (doc 5458) | 1,852 | M: one cell: a port-form OUT whose port take lands on a refresh's first clock with odd room at 0-1 waits in the chain body settles it |
| `refresh_lost=start` | a request lost outside a count loop is evaluated again on the next instruction start (HALT: after the status) | arbiter.py:321 | arbiter | special | `F13-s-shlcl4-pO-w0`, 68 runs; −69 (doc 2264) | 955 | C: start as an evaluation clock |
| `refresh_reraise=unit` | a request lost while a count loop runs is raised again as its last iteration starts | eu.py:400 | EU | special | F17 (cfg) | 955 | C: loop exit as an evaluation clock |
| `refresh_io_run=pair_out` | while an OUT waits for its I/O, the fetch a refresh beat is followed by a committed back-to-back fetch when a byte of room remains counting the decoder's pending take (thirty-sixth fit; `pair`, any IN/OUT and the room rule alone, before) | queue.py:308 | queue | special | `F13-c-out-shlcl2-pE-w2`, 477 rows; −7 (doc 3379) | 1,522 | P |
| `refresh_beat_t4=t4` | on the delivery clock of a 3-clock beaten fetch, a fetch requested there is committed and starts a clock later | arbiter.py:504 | arbiter | special | 4 rows at 0 waits, prelude only (`F13-r-rfm-f2-pE-w0`; doc 5460) | 2,142 | P since 2026-10-28 (F27 ties +2 −2 flipped, F13 loses 4; was M: four prelude rows: a beaten 3-clock fetch in the chain body at 0 waits followed by a latched delivery settles it |
| `refresh_beat_b2b=imm` | the back-to-back fetch committed on a beaten 3-clock fetch's last clock is a clock late when on the delivery clock (no IR load) the decoder takes an operand, an imm form runs with bytes outstanding without starting there, or a non-imm form starts there right after an imm form | arbiter.py:352 | arbiter | special | `F28-out-fc-beat-movawi-n0-k2-pE-w0`, `F27-out-fc-room-movawi-n0-k2-pO-w0`; none and take −15 F27 −16 F28 | | P (2026-10-28, WP61) |

### Refresh: the EU's early fetch run

`refresh_sync=run` makes the fetch a refresh beat, and the fetches back to back behind it, two clocks earlier for the EU than on the bus (the EU loses the refresh's length less 2, as a count loop does); four rules then limit or extend that view. Proposed cleaner mechanism: account the refresh as a stall of length - 2 at the EU's boundary (as `refresh_eu=hold` does for the count loop) instead of shifting the fetch run, and re-fit the five together (−484 when `refresh_sync` is flipped back, doc 2285).

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `refresh_sync=run` | for the EU the fetch a refresh beat and the run behind it are 2 clocks earlier: the take sync is met early and a start may go on the last two clocks of a run fetch | eu.py:443 | EU | special | `F17-s-n0-shlcl1-pO-w0`; −484 (doc 2285) | 2,142 | C: stall at the boundary |
| `refresh_sync_run=two` | only for the beaten fetch and the one behind it | eu.py:444 | EU | special | prelude only, `F13-r-rfm-f1-pE-w1` (cfg) | 1,411 | C: stall at the boundary |
| `refresh_sync_reg=delivery` | not for a class reg form's sync | eu.py:445 | EU | special | prelude only, `F13-c-out-shlcl0-pE-w0` (cfg) | 1,411 | C: stall at the boundary |
| `refresh_run_modrm=wait` | a ModR/M form may not start early in the run | eu.py:159 | EU | special | prelude only, `F13-c-out-shlcl0-pE-w1` (cfg) | 987 | C: stall at the boundary |
| `dw_view=eu` | an I/O request's uncounted setup clocks owed to an early-run fetch are the clocks 2 earlier | arbiter.py:155 | arbiter | special | `F17-s-n2-out-pE-w0`, 64 END blocks; −64 (doc 2264), −187 (st6) | 19,142 | C: stall at the boundary |

### Refresh: the arbiter's other refresh rules

When a pending refresh may take a free bus beside a posted I/O, a latch wait or HALT.

| Rule | What it does | Code | RTL | Kind | Pinned by | Reads | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `refresh_lead=closed` | no refresh starts in a posted I/O's lead; it goes on the I/O's issue clock, ahead of it | arbiter.py:202 | arbiter | special | `F13-s-shlcl7-pO-w0`, 49 runs at w0; −116 +1 (doc 2285) | 2,142 | P |
| `refresh_lead_port=last` | for a port-form IN/OUT only on the lead's last clock | arbiter.py:205 | arbiter | special | 37 rows: 33 on the first clock served at once, 4 on the last held (doc 5457) | 270 | M: the four last-clock rows decide it: port-form OUT leads under refresh at every wait in the chain body |
| `refresh_lift=free` | the lead's first clock is the first free one: after a refresh still on the bus | arbiter.py:424 | arbiter | special | `F13-c-out-shlcl0-pO-w0`, 25 rows; −14 (doc 2643) | 430 | P |

### Plain structure, parameters, harness and unread fields

| RTL | Fields (= fitted value) |
| --- | --- |
| queue | `word_latch=byte_d` (byte-wide write port, 1-byte latch counted from the clock after delivery); `latch_read=commit` (the write port is held by a committed take or an IR load); `release=byte`; `take_commit=at_end`; `request_eval=on_change`; `request_hold=lapse`; `request_sample=after_take`; `arrive_partial=False` (no rule); `data_ready=0` |
| decoder | `ir_port=False` (no rule); `modrm_commit=byte` (the ModR/M latch); `bytes_per_clock=1`; `opcode_take=prefetch` |
| bus | `min_gap=0`; `odd_split=atomic` (st6: `separate` identical); `sfr_cycle=io` (the SFR store: 3 + I/O waits, no pins); `wlatch=4` |
| arbiter | `refresh_b2b=False` (no rule); `refresh_fetch=refresh`; `refresh_data=refresh`; `data_while_fetch=wait_before` (setup counted before the clock's choice); `hold_run=False` (no rule); `refresh_io=waits`; `hold_q=3`; `arbiter_q=2` (unread under `arbiter=b2b`) [reads 0] |
| EU | `opcode_overlap=0` (no rule) [reads 0]; `write_wait=mem_end` (st6: `end` identical); `take_sync=pending` (the take sync: fetches in flight or requested on the take clock); `read_use_latency=0`; `io_release=post`; `io_post=take` (the thirty-third fit's move); `imm_latch=free` (no rule; st6: `wait` identical); `wb_from=end`; `port_sync=none` (st6: `sync` identical); `refresh_start_hold=none` (no rule); `refresh_stall=3` (unread under `refresh_eu=hold`) [reads 0]; `refresh_stall_exec=4` (unread under `refresh_eu=hold`) [reads 0]; `refresh_recent=18` (unread under `refresh_loop_hold=entry`) [reads 0]; `refresh_recent_by=fetch` (unread under `refresh_loop_hold=entry`) [reads 0]; `refresh_eve=hold` (unread under `refresh_loop_hold=entry`) [reads 0]; `refresh_io_pre=count` (read, but only feeds `eu.since_start`, which `io_post=take` never reads); `io_b2b_q=3`; `reraise_off=0`; `pop_exit=4` (POP PSW's clocks after its read) |
| EU (micro) | `mem_order=split`; `imm_order=after_issue`; `imm_head=split`; `grp_mode=setup`; `ea_post=clocks`; `rmw_write_issue=immediate`; `rmw_imm_issue=rmw`; `pop_read_hold=hold`; `per_shift_count=2`; `shift_tail=3`; `refresh_tail_bound=2` |
| refresh | `refresh_timer=grid` (inert under `refresh_counter=edge`); `refresh_counter=edge`; `refresh_restart=free`; `refresh_interval=16`; `rfm_delay=3` |
| harness | `refresh_enable=fill` (unread under `prelude_anchor=pop`) [reads 0]; `refresh_align=prelude`; `prelude_anchor=pop`; `prelude_tail=segs` |

## Open items

What the model leaves undefined that the RTL needs, and where the plan handles it.

- **Reset.** The model has no reset: its clock 0 is the prelude's POP PSW stack read, with
  the queue preloaded with the three words after it, the bus running that read, the EU
  held until `pop_exit` clocks after its delivery and the refresh counter at
  `refresh.POP_COUNTER[(RFM, WTC)]` (a measured constant per prelude). Every Start value in
  A2 is that state, not a reset value. The RTL must reach this state from a real reset;
  the reset exit and the slow reset clock are the core plan's A3, and the mismatch, if
  any, shows in Phase C6 and is measured with a new family, not patched (plan, Risks:
  "Reset and the prelude").
- **The prelude's start.** The model runs the prelude's tail from the POP PSW read
  (`prelude_tail=segs`, `prelude_anchor=pop`): the segment loads, the register loads, the
  prelude marker. The RTL runs the whole prelude functionally (B4); the counter value at
  the POP read and the queue's state there are the two facts it must reproduce (C6, the
  `--pre` window).
- **HALT wake.** HALT exists only as the END block's last instruction: its two status
  clocks (`halt_status`, `refresh_halt`), the fetches a refresh held off before it
  (`halt_refresh`) and the run's end. No interrupt or reset leaves HALT in the model; the
  RTL's wake path has no model behind it (plan, "What the model does not have"; Phase E).
- **The 181 missing runs.** statestats' scoring of the logged runs: 18,961 of 19,142
  exact; the misses are F8 19 of 48, F13 76 of 462, F17 49 of 798, F18 31 of 1,164 (175
  refresh-on) and F22 6 of 1,320 (`TEST [BW+200h],imm16`). The RTL inherits them; they
  stay open states in the facts record (plan, Risks: "The model's miss set"). Phase C's
  gate is RTL-exact equal to model-exact, so these runs are compared against the model.
- **The C0/C1 shift count.** The model takes a count byte unmasked (`templates.decode`:
  `count=code[...]`) and masks CL to 5 bits; the corpus's count bytes are small (the
  longest observed clocks step, 62, is SHL by CL with CL = 31). If the V35 masks the count
  byte too, the count-loop counters are 6 bits; if not, 9 (a count of 255, 510 clocks).
  One chain with `SHL AW,32` and `SHL AW,255` settles it (Phase E).
- **The second EU pass in a clock.** Phase P runs the EU's tick a second time after an
  issue that releases it. The RTL needs either that combinational path or a registered
  equivalent shown on the state rows (B3).
- **Clock stamps on the debug bus.** B3 compares `_clock_row` per clock, and four of its
  keys are absolute clocks (`requested_at`, `resume`, `clk_start`, `clk_end`). The RTL's
  debug bus should expose the A2 representations (offsets, flags), and the replay driver
  convert the model's row the same way, as statestats does.
- **Dead state and unread fields.** Under the fit nothing reads `eu.since_start`,
  `since_t`, `io_pre`, `stalled`, `refresh.due`, `enable_at`, `queue.read_t`, `held`,
  `words`, `snap`; `eu.started` (True), `ls_shift` (0) and `queue.io_abort` (False) are
  read but constant; and the fields `opcode_overlap`,
  `refresh_stall`, `refresh_stall_exec`, `refresh_enable`, `refresh_recent`,
  `refresh_recent_by`, `refresh_eve`, `arbiter_q` are read by no run. The frozen simulator
  (A1) should drop them; the RTL does not build them.
- **Not modelled at all.** Control flow and the queue flush (F23, acquired 2026-10-27 and read in the chains
  doc's facts), strings (F24), the F25 forms (acquired the same day), the 0F page, interrupts and the internal RAM and SFR block beyond
  the RFM store: Phase E, model first.

### Observations for the overseer (not fixed here)

- The plan names the since-start counter among the width-deciding state; under the
  thirty-third fit's `io_post=take` it is unread (only `eu._preload` reads it, under
  `io_post=start`), so it should not be built. Likewise `refresh_io_pre`, which only feeds
  that counter: the doc already says so in its OPTIONS comment.
- `Machine._clock_row` gives `ir` relative to the chain base (`d.ir - self.base`) but
  `pc` as the EU's code offset, which under `prelude_tail` includes the tail: the two keys
  are in different frames by `len(tail)`. statestats subtracts `eu.origin` from `pc`;
  B3's comparison should do the same or the row should be fixed in the model.
- Five structural fields are inert on the corpus (st6: identical on every run when
  flipped), so the fit carries rules no run tests: `room_ir_ready`, `ea_floor`,
  `wlatch_ir`, `wlatch_mul`, `sfr_setup` (and the `wlatch_ir_at` that only matters with
  `wlatch_ir`); likewise `abort_latched=full`/`any` and `sync_io=issue`/`unit` tie.
