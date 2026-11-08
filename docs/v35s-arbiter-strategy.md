# V35S core v2: removing the arbiter

Written 2026-11-08 at the user's direction, after R4 (5a43654): "the arbiter is our next simplification
target. Nothing this complex would exist on real hardware; most of this complexity must exist in the EU,
microcode or bus unit. I want the arbiter removed or replaced with something similar. The EU is the only
part of the CPU that is allowed to know anything about the type of operation being executed." This
document constrains the bus unit's grant to a mechanism a silicon designer would recognise, says where
every fitted arbiter rule goes when the arbiter no longer carries it, and sets out how to find the
implementation that matches the fit. As with the queue (docs/v35s-queue-strategy.md), it accepts a loss
of overall fit where the loss is recoverable by later changes to the execution unit or the microcode.

## 1. The problem in numbers

`fpga/v35s/core/v35/v35_arbiter.sv` (at 5a43654) is 904 lines with **108 ports**, three request positions
of a 130-bit record each, and a choice tree of 39 logic levels (1,769 LUT4, −18 ns at 64 MHz). The record
it holds for every EU request (`req_t`, v35_front_pkg.sv) carries, besides the cycle's kind, address,
width and data, about 30 attributes that describe the *instruction* that posted it: a 7-bit setup count,
a fetch-free count, an I/O lead, a detached flag, a group flag, "through" clocks, imm1, gdisp, sreg,
whole, restart, not_before, relatch, alive / aoff / dlive / dimm, nowait, dwlike, memc, fhd, strc, mfr,
c0, pfv, prw, pth, ftl. The arbiter reads them to count the request's setup in one of six ways, to decide
which clocks of a fetch count, to hold or release the prefetcher, and to date the request against the
queue's line. It also takes 25 inputs that tell it what the EU and the loader are doing (`t_start`,
`take_now`, `l_pop`, `gdisp_act`, `ea_b2b_act`, `wb_hold`, `latch_wait`, `sreg_hold_set`, `floor_set`,
`pfs_x`, `pimm_x`, `bcd_idle`, `sidle`, `need_t`, `mf_old`, ...).

Every one of those is a fitted *situation* of the model's `Request` (validation/v35s/chains/sim/arbiter.py:
47-110, fifty attributes): "a group form's grp clocks count on no clock of an I/O cycle", "a 0F memory
form's read counts fetch-free clocks since the last fetch not committed back to back after the post", "a
one-byte-immediate form's first request goes before a fetch requested on the delivery clock". They were
fitted into the arbiter because the model's phase order evaluates the bus choice there, and the RTL copied
the attribution. The result is a bus arbiter that knows the instruction class of every request.

The chip does not work that way. From NEC's documentation and the nuV30 measurements
(`build/deps/nuV30/docs/facts/biu_model.md`):

- **The EU ↔ BCU interface is a handful of discrete signals.** The EU posts a memory or I/O request
  (MEMR / MEMW / IOR / IOW with an address and, for a write, a datum); the `F` / OPR data-ready interlock
  stalls the EU until the transfer completes and is "the ONLY EU↔BIU bus sync"; `SUSP` bars the
  prefetcher (asserted before every FLUSH and on stack reads / INTA); `FLUSH` clears the queue. None of
  the prefetch / arbitration machinery is microcoded (0 ROM tokens).
- **Arbitration is fixed.** "An EU data access never preempts an in-flight prefetch; it wins arbitration
  at the next bus-cycle boundary." After an EU access the prefetcher resumes after a fixed idle gap.
- **The timing the model fits as "setup" is the EU's.** nuV30's cycle-exact core expresses every
  request's lead-up as EU states ("the reservation must LEAD the request by one cycle": PUSH's
  S_PUSH_CALC, the reg-EA store's S_EA2, RMW's last S_RMWX) and the BCU's part as one reservation input
  (`eu_req` / `eu_soon`) that keeps a fresh prefetch from taking the slot the request is about to need.

So the silicon-shaped bus unit has a request port with a cycle type, an address, a datum and a
reservation, a done output, the queue's request line and a fixed priority. The fifty request attributes
are the EU's and the microcode's business, or they are emergent.

## 2. The bus unit's grant as a simple machine

The arbiter module is deleted. Its residue is a grant stage inside `v35_bus.sv` (or a one-screen
`v35_grant.sv` the bus unit instantiates) that evaluates one fixed priority once per CPU clock.

### 2.1 The EU request port (the EU's bus interface, replacing `post_t` / `rq_t` / `post_p` / `rq_p`)

| Signal | Dir | Width | Meaning |
| --- | --- | --- | --- |
| `req_v` | EU → bus | 1 | a cycle is wanted (level: stands until accepted) |
| `req_cyc` | EU → bus | 2 | memory read, memory write, I/O read, I/O write (the pin-level cycle; the SFR page is decoded from the address as the bus unit does today) |
| `req_addr` | EU → bus | 20 | the cycle's physical address |
| `req_width` | EU → bus | 1 | byte / word (an odd word is two cycles, the bus unit's own pair) |
| `req_data` | EU → bus | 16 | a write's datum, sampled at B2 (so a datum that is ready a clock late needs no descriptor bit) |
| `req_resv` | EU → bus | 1 | the reservation: a request is about to be posted; no fetch starts while it is up (nuV30's `eu_soon`; the fitted holds and fetch-free counts are the EU raising it) |
| `req_ack` | bus → EU | 1 | the request's (first) cycle issued on this clock |
| `req_done` | bus → EU | 1 | its last cycle ended on the last clock (the datum is in `done_data`) |
| `done_data` | bus → EU | 16 | the read datum (exists) |

Nothing else crosses from the EU to the bus unit about a request. No class, format, row, step, count or
kind-of-instruction bit. The bus facts the EU may read are the bus unit's existing status outputs
(`free`, `busy`, `fetch_inflight`, `fetch_end_prev`, `fetch_since`, `cpu_end_prev`, `io_win`, `b2b_now`,
`dlv_*`, `abort_*`): they say what the bus is doing, not what instruction runs.

### 2.2 The queue port (unchanged from the queue strategy)

`fetch_req` (the level line), `q_low` (the starvation hint that overrides the EU's reservation),
`q_word` (the abort test's term), and the grant back (`g_fetch`, `g_abort`, `g_b2b`, delivery).

### 2.3 The grant (one priority, evaluated once)

On a clock the bus is free (the aborted cycle's and the odd pair's second half go first, as today):

1. a fetch the bus unit **committed to back to back** (the line up at the last clock of the fetch that
   just ended, no EU request standing then: today's `b2b_now`, sampled against `req_v` instead of the
   arbiter's `mem_wait_o`), else
2. the EU's request if `req_v`, else
3. the queue's fetch if `fetch_req && (!req_resv || q_low)`, else
4. nothing.

The Q2 aborted fetch (the fetch begun and abandoned on the start clock's triple read) stays the bus
unit's mechanism as built: it reads the queue's `q_word` and the loader's read strobes, which are queue
events, not instruction types. Whether it survives the EU-side rewrite of the start gate is a measured
question (section 5).

### 2.4 What the bus unit no longer knows

Setup counts and which clocks count; fetch-free tails; I/O leads; the io_recover turnaround as a request
attribute (it becomes the bus unit's own: no EU cycle for `io_recover` clocks after an I/O cycle, a plain
turnaround with no request involved — or the EU's wait, settled by the corpus); detached I/O; group forms;
RMW through clocks; imm1; gdisp; sreg; floors; not_before / relatch; the 0F page's fetch-free restarts,
`pthru`, `ftail`, `run_wait`; the request's position among others; dating of the request against the line
beyond the one-bit back-to-back sample.

## 3. Where each fitted arbiter feature goes

| Fitted feature (model name) | Today | Home | How |
| --- | --- | --- | --- |
| setup count, `data_while_fetch=wait_before`, `setup_free` / `free_need`, `through` | arbiter counting | **microcode** | the clocks before a request are CLOCKS rows (the row's `n` already carries the setup); the fetch-free tail is the EU raising `req_resv` for the last `f` clocks and counting them only while `fetch_inflight` is low (a sequencer counter fed by a bus fact); "through" clocks count regardless. ucgen emits the counts from the fit's class integers it already reads |
| `hold_fetch=le_q`, `hold_count=ahead`, `hold_q` | arbiter hold tree | **bus unit + queue hint** | `req_resv` bars fetches unless `q_low` (the queue's starvation hint overrides the EU, as the queue strategy intended); `hold_count=ahead`'s operand-byte term is the loader's and stays in the loader's `need` feeding `q_low` or is dropped |
| `hold_run`, `free_run`, `free_hold=delivery`, `free_idle` | arbiter | **bus unit (1) + accepted loss** | the back-to-back commitment is the bus unit's sample; a fetch that runs inside the EU's fetch-free clocks is the EU's counter not restarting on a committed fetch (one bus fact, `g_b2b`); the dating variants are dropped |
| `io_hold=posted_b2b`, I/O `lead`, `lift`, `dw_lift`, `dw_slot`, `io_ir_hold` | arbiter | **microcode** | the lead is the last `lead` clocks of the reservation window with `req_resv` dropped; `posted_b2b` is the bus unit's (1) |
| `io_recover` | request attribute | **bus unit** | a plain turnaround: no EU cycle issues within `io_recover` clocks of an I/O cycle's end (the bus unit's `io_win` already exists) |
| `io_count=nowait`, `dw_count`, `str_count=dw` | counting mode | **microcode** | the sequencer's count of its own clocks does or does not pause on `in_wait` (a bus fact), a row attribute |
| `io_release=post` (detached I/O), the three positions, `_promote`, `moved` | arbiter positions | **EU** | a one-entry write buffer in the EU's bus interface: a detached I/O write parks there while the sequencer goes on; the next POST row waits for `req_ack` of the parked one. Two queued positions become one buffer; a form that needs more waits (accepted loss, measured) |
| `grp_free_bus`, `grp_io_hold`, `grp_disp=hold`, `gdisp` | arbiter | **microcode** | group forms' extra clocks are rows whose count pauses on `busy` / `io_win` (bus facts); the hold is `req_resv` |
| `port_latch=relatch`, `not_before`, `port_ready`, `port_issue` | arbiter | **microcode** | the EU delays its post (rows that already exist after every port take: the two fixed relatch rows) |
| `floor_hold`, `disp_floor=posted`, `imm_count=start` (nb) | arbiter | **microcode** | the floor is the sequencer's (it owns `floor_n` / `dfloor`); it raises `req_resv` while floored and posts after |
| `grp_read=rmw_slot` (the nowrite slot), `slot_room=word`, `slot_idle=eu`, `slot_latch`, `slot_fetch` | arbiter + bus | **emergent or dropped** | the EU posts no write for the left-out slot; the fetch that silicon runs there falls out of (3) if the line is up; the slot's special room and latch rules are not rebuilt (class (b) / (c) losses recorded) |
| `arbiter=b2b` / `_fetch_first`, `imm1_first=hold`, `request_reissue=no_mem`, `b2b_hold` | choice tree | **bus unit (1)** | one sample bit; the imm1 exemption is dropped |
| `sreg_store=own`, `sreg_io=hold`, `wb_fetch=hold`, `wlatch_hold`, `halt` | arbiter inputs | **microcode / EU** | `req_resv` windows from the sequencer (HALT: `fetch_req` is already gated by `halted` in the queue's suspend) |
| `page_mem=fixed` / `page_free`, `page_run`, `page_cl=thru`, `pthru`, `ftail`, `page_commit=post`, `page_imm_run`, `bcd_fetch=hold`, `mul_imm_count=sync` | arbiter + bus cycle flags | **microcode on bus facts, or accepted loss** | the 0F read's fetch-free count is a sequencer counter that restarts on `fetch_start && !g_b2b`; `pthru` and `ftail` are row counts against `fetch_since`; the cycle flags `c_thru`, `c_pfa`, `c_after_post`, `c_tn`, `c_as`, `c_nt` leave the bus unit (they encode the EU's state in the bus cycle). Expected initial loss in F32 F34 F39 F40 |
| the own-request interlock (`own_issued`, `own_done`, `own_dlv`, `own_two`, ISSUED / WAIT rows) | arbiter outputs | **EU bus interface** | `req_ack` / `req_done` (the F / OPR interlock); the odd pair is the bus unit's and `own_two` is the width and address bit the EU already has |
| `alive` / `aoff` (the address follows the EA), `dlive` / `dimm` / `g_dsel` (the datum at B2), `disp_io=extend` | record fields | **EU** | the EU posts `req_v` only once the address is known (the earlier part of the window is `req_resv`); the datum is sampled at B2 from the EU's live datum register; `disp_io=extend` is a measured question (the bus unit sees no form) |
| refresh interactions (`refresh_*`) | not built | unchanged | out of the gates |

## 4. What this changes elsewhere

- **The bus unit** gains the EU request port and the four-way grant (about 60 lines), loses the cycle
  flags that encode EU state (`c_after_post`, `c_disp_in_flight`, `c_ir_before`, `c_thru`, `c_pfa`,
  `c_tn`, `c_tkin`, `c_as`, `c_nt`, `g_take_near`, `g_lea_start`) and their ports. Its pin timing is
  unchanged.
- **The sequencer** gains a bus-interface block: the current request register (`req_v`, cycle, address,
  width, datum), the one-entry write buffer, the reservation window (`req_resv` as the OR of the active
  windows: the fetch-free tail counter, the floors, the holds the generator emits as row attributes), and
  the `req_done` interlock replacing ISSUED / WAIT's arbiter-fed conditions. It loses the request record
  assembly (`ptm`, the 30 attributes) and the 40-odd arbiter-facing outputs.
- **ucgen** emits the new row attributes (fetch-free tail, lead, count mode, hold windows) from the fit
  integers it already reads; `test_ucgen`'s inverse check extends to them. The fit is not edited.
- **The loader** is unchanged, except that `need_t` no longer goes to an arbiter.
- **The queue** is unchanged.
- **The model is not edited.** Its arbiter stays the description of the fit; the RTL's divergences from
  it become the list of EU / microcode features still to express.
- **Timing.** The 39-level choice tree goes. The grant is a handful of terms on registered facts. The
  sequencer's new counters are small; the request register moves to the EU but is the same width minus
  the attributes.

## 5. Method: constrain the machine, then find the implementation that matches the fit

The order matters: the bus unit's port and grant are fixed first and the EU moves to meet them.

1. **Build the port and the grant** (section 2) in the bus unit; delete `v35_arbiter.sv`; route the
   queue's line and the EU's request through the new grant. The Q2 abort stays. Lint and the structure
   test as before; the structure test gains the rule that no signal crossing into `v35_bus.sv` or
   `v35_queue.sv` carries a class, format, row or step (a port-name and type check on the two modules).
2. **Build the EU bus interface in the sequencer**: the request register, the write buffer, `req_resv`
   as the fetch-free tail + the floor + the generator's hold windows, the `req_done` interlock. First
   with the plain counts (setup from the rows as they are; the fetch-free tail from the class's
   `setup_free`; the I/O lead from the class's `lead`), no page rules, no group rules.
3. **Measure the whole refresh-off corpus** against 5a43654's 29,208 at both spacings, with every miss
   classified by the first divergent event (the R2 classifier): (a) an EU-side wait or window the
   microcode could express (recoverable: accepted), (b) a grant the bus unit made differently with the
   same `req_v` / `req_resv` / `fetch_req` / `q_low` inputs (a grant-rule question: fix if it is a fixed
   rule of the four, else record), (c) a grant that needs an instruction attribute at the bus unit (the
   only kind the port may never carry: recorded with the attribute it would need, for the EU / microcode
   recovery list).
4. **Recover what the microcode can express**: the group forms' pauses, the I/O lead, the relatch rows,
   the page rules as counters on bus facts, each behind a macro, measured alone then cumulatively, no
   run lost at any step, as R1–R4 did.

**Budget.** The whole refresh-off corpus is 29,208 / 30,361 today. Families whose exactness rests on the
arbiter's attributes are F4–F7 and F10 (memory data, io_recover), F14–F16 (displaced forms, the nowrite
slot, free_run), F19–F22 (immediates, RMW through clocks, the group forms), F29 (I/O frames, DW counts),
F30 / F35 / F37 (transfers' stack requests), F32 / F34 / F39 / F40 (the 0F page). An initial loss of
10–15 % of the runs in those families after step 2, with every miss classified, is acceptable; step 4
brings back what the microcode can say. Any family losing more than that, or a (b) miss that needs a fifth
grant rule, stops the work for a decision. The queue's history is the precedent: Q1 lost 4,816 runs and
R1–R4 recovered 5,517.

## 6. Work package

One Opus agent, one worktree from 5a43654: steps 1–3, then step 4 for the rules the brief lists, a diff
against its base. Its brief forbids any instruction attribute on the bus unit's or the queue's ports (no
input that names a form, class, row, step, count mode or kind of instruction; the four cycle types,
address, width, datum and the reservation only), caps the grant at the four rules of section 2.3 plus the
aborted cycle and the odd pair, forbids editing the model and fit.json, allows ucgen changes with the
inverse check kept green, and asks for the per-family table and the miss classification before any
recovery work. The overseer verifies on main, records the per-family losses in the core v2 Record as the
baseline the recovery stages are measured against, and commits.
