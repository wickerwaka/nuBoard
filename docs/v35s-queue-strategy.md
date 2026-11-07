# V35S core v2: a new strategy for the prefetch queue

Written 2026-11-06 at the user's direction: the queue module of the core v2 is not a simple machine, and
the fitted features it carries describe what the queue *does* on the corpus, not how it is *built*. This
document constrains the queue to a mechanism a silicon designer would recognise, says where every fitted
queue feature goes when the queue no longer carries it, and sets out how to find the implementation that
matches the fit. It accepts a loss of overall fit where the loss is recoverable by later changes to the
execution unit or the microcode.

## 1. The problem in numbers

`fpga/v35s/core/v35/v35_queue.sv` (at ec5a146) has **164 ports and 71 registers** for a six-byte FIFO.
Of the fit's 243 refresh-off structural fields, about 45 are evaluated inside the model's `Queue` or
exist only to feed its room and request rules (`room_ir`, `room_ir_pre`, `room_ir_imm`, `room_ir_ready`,
`ea_ir_room`, `lea_room`, `far_room`, `xfer_mem_room`, `page_ir_room`, `pre_modrm`, `modrm_mate`,
`modrm_port`, `word_latch`, `latch_read`, `latch_hold`, `latch_midtake`, `latch_disp`, `latch_start`,
`take_commit`, `release`, `arrive_partial`, `request_eval`, `request_hold`, `request_sample`,
`request_reissue`, `abort_fetch`, `abort_unit`, `retry_first`, `nop_hold`, `io_ir_hold`, `count_latch`,
`flush_hold`, `flush_from`, `ret_far_fetch`, `xfer_odd`, `xfer_nt`, `xfer_nt_b2b`, `xfer_abort`,
`str_fetch`, `str_hold`, `bf_imm_hold`, `cvt_hold`, `page_b2b`, `page_b2b_win`, `page_run`,
`page_dcommit`, `page_fl_eval`, `page_disp`, `refill_start`, `slot_fetch`). Each is a *situation*: "on a
delivery clock while the decoder is mid-take the latched byte counts", "a short transfer not taken at an
odd address holds the request", "a 0F register form commits one more fetch back to back once per form".
They were fitted into the queue because the model's phase order put the fetch decision there, and the
RTL copied the attribution: 120 of the 164 ports exist to tell the queue what the EU, the loader and the
sequencer are doing so that it can apply those situations itself.

The chip does not work that way. What is known of the V30 family's bus control unit (BCU), from NEC's
documentation and the nuV30 measurements (`build/deps/nuV30/docs/facts/biu_model.md`,
`notes/microcode_analysis.md`):

- The BCU holds a **prefetch pointer (PFP)**, a 16-bit counter incremented per prefetch and loaded from
  the PC on a branch, call, return or break; the EU holds the **PC**, incremented as it takes bytes. Two
  pointers in hardware "save several clocks on branches" (the data book). The queue is cleared on those
  instructions and on an interrupt acknowledge.
- The **queue is 6 bytes** (measured: no fetch ever initiated at depth ≥ 5); a **word is fetched when two
  bytes are free**; fetches are words at even addresses. The 70116 "prefetches if the queue has one or
  more empty words".
- **None of the prefetch, refill or resume machinery is microcoded.** The EU's whole interface to it is a
  handful of discrete signals: the `Q` source read (one byte per micro-op that reads it, the `E` flag
  marking the opcode boundary), `SUSP` (suspend prefetch: asserted before every `FLUSH` and on stack
  reads and INTA), `FLUSH` at a fixed micro-address per transfer opcode, the EU's MEMR / MEMW requests,
  and the `F` / OPR data-ready interlock that stalls the EU until its bus transfer completes.

So the silicon-shaped queue has no notion of a "form", a "ModR/M take", a "0F register form" or a
"string compare's result clocks". It has a count, a pointer, a request line and a suspend input. The
forty-five situations are the EU's and the microcode's business, or they are emergent.

## 2. The queue as a simple machine

### 2.1 State

| State | Width | Meaning |
| --- | --- | --- |
| `q[0..5]` | 6 × 8 | the bytes, oldest at the head |
| `cnt` | 3 | bytes stored, 0..6 |
| `pfp` | 16 | the prefetch pointer (segment offset); the physical address is `{PS, 0} + pfp` with the 16-bit wrap the core already has (README Divergence 6) |
| `inflight` | 1 | a word fetch is on the bus |
| `discard` | 1 | the word in flight belongs to a flushed stream and is dropped on delivery |
| `odd` | 1 | the stream starts at an odd address: the first delivered word's low byte is dropped |

Possibly (variant B, §4): `lat` (1) and `lat_byte` (8), a one-byte holding register behind a byte-wide
write port. Nothing else. No take addresses, no stamps, no "starts" counter, no per-form commitments.

### 2.2 Ports (about twenty, from 164)

To and from the bus unit / arbiter:

| Port | Dir | Meaning |
| --- | --- | --- |
| `fetch_req` | out | the request line, a level: `free >= 2` and not suspended, where `free = 6 - cnt - (inflight ? 2 : 0)` (variant B: `- lat`) |
| `fetch_addr[19:0]` | out | `{PS,0} + pfp`, even (the low bit cleared; `odd` remembers the dropped byte) |
| `q_low` | out | `cnt <= HOLD_Q` (3, the fit's `hold_q`): the priority hint the user asked for. The arbiter prefers a posted data request over a fetch while the queue holds more than this (`hold_fetch=le_q`); below it a fetch competes on equal terms |
| `q_starved` | out | `cnt == 0 && pop_wanted`: the EU is stalled on a byte (the urgent form of the hint; the arbiter may use it as the fit's `free_run` / starvation rules did) |
| `fetch_go` | in | the bus unit started our fetch this clock (sets `inflight`, `pfp += 2`) |
| `dlv_v`, `dlv_data[15:0]` | in | the word delivered (clears `inflight`; stored unless `discard`; low byte dropped if `odd`) |
| `abort_go` | in | the bus unit started and then aborted a fetch (the model's 3-clock aborted cycle): `inflight` for its duration, nothing delivered; the request line is simply still up afterwards |

To and from the execution unit (loader and sequencer):

| Port | Dir | Meaning |
| --- | --- | --- |
| `vb0..vb3[7:0]`, `avail[2:0]` | out | the head window (four bytes) and the count, with this clock's delivery bypassed as today (S1 before the take) |
| `pop[1:0]` | in | bytes taken this clock (0..2; the opcode and operand takes, the IR load counted as a pop like any other `Q` read) |
| `flush`, `flush_addr[15:0]` | in | clear the queue, load `pfp`, set `odd` from the address, set `discard` if a fetch is in flight |
| `susp` | in | suspend prefetch: `fetch_req` is held low while asserted (the chip's SUSP) |
| `ps_base[19:0]` | in | the segment base from the EU's PS shadow |

The request line is a level. The **bus unit samples it at its own decision points** (a fetch's last
clock, an idle clock, after a data cycle): the fit's `arbiter=b2b` (back to back when the request stands
at a fetch's last clock), `request_sample=after_take` and `request_eval=on_change` then describe *when
the bus unit looks*, and belong to the bus unit, not to a flag the queue re-evaluates "on change". The
`b2b_at` commitment, today a queue register with four page_* exceptions, becomes "the bus unit saw
`fetch_req` high at the fetch's last clock".

### 2.3 What the queue no longer decides

- **Whether the IR counts as a seventh slot** (`room_ir=arrival_idle` and its seven refinements).
  In the chip the opcode leaves the queue when the EU reads it; the EU's opcode register is the EU's.
  The RTL equivalent: the loader's IR load is a `pop`, and the clock at which the loader pops the opcode
  relative to the fetch decision is the *EU's* timing. If the corpus says the fetch decision sees the
  opcode as "already gone" a clock before the loader takes it (that is what `arrival_idle` describes),
  that is a statement about when the loader pops, and it is implemented in the loader, not by the queue
  counting a phantom slot.
- **Every hold.** `flush_hold=start`, `str_hold` / `str_fetch` (fetch_hold and fetch_release rows),
  `bf_imm_hold`, `cvt_hold`, `count_latch` (a shift's count byte), `nop_hold`, `io_ir_hold`, `xfer_odd`,
  `xfer_nt`, `xfer_abort`, `page_disp`, `page_dcommit`: each is "no fetch request from step A to step B of
  this form". That is `SUSP`. The microcode ROM already has FETCH_HOLD, FETCH_RELEASE, QUIET and FLUSH
  operations (S5a); the generator turns each of these rules into a suspend window on the form's rows, and
  the queue sees one input.
- **Every per-form commitment.** `page_b2b=reg`, `page_run`, `xfer_nt_b2b=decide`, `refill_start` are
  "this form commits the bus unit to one more fetch back to back, once". A one-shot request is EU
  behaviour: a sequencer row that raises a `fetch_ask` strobe the bus unit treats as a request at its
  next decision point. Whether a separate strobe is needed at all is a question for the corpus (§5).
- **The take sync** (`take_sync=pending`, `imm_landed`, `port_landed`, `start_sync=b2b_modrm`): the
  EU waiting until the fetches it "asked for" are in. The chip's EU stalls on the byte it needs (the `Q`
  read has no data) and on the `F` interlock for its own bus transfers; it does not count fetches. In the
  RTL the loader stalls when `avail` is short, full stop. Where the corpus shows the EU waiting *longer*
  than the byte's arrival (the fitted sync targets), that is EU-side pacing to be expressed as rows, not
  as a queue count the EU reads.
- **The aborted fetch** (`abort_fetch=retry`, `abort_unit=loop`, `retry_first`, `abort_latched`): a
  fetch the bus unit started on a request that was withdrawn in the same clock (three queue reads at
  once took the room away). With a level request and a bus unit that samples it, this is the bus unit's
  behaviour when the line falls after it committed: it runs the short aborted cycle (`v35_bus` already
  has it) and the request line comes back up by itself when the room is back. The "retry at the loop's
  exit" variants are suspend windows (EU).
- **Refresh interactions** stay out of scope (the refresh-off focus).

## 3. Where each fitted queue feature goes

| Fitted feature (value) | Today | New home | How |
| --- | --- | --- | --- |
| six bytes, word fetch at two free, PFP increment, even fetch address, odd-target first byte dropped, discard of a flushed fetch | queue | **queue** | the mechanism itself |
| `request_eval=on_change`, `request_hold=lapse`, `request_sample=after_take`, `arbiter=b2b`, `b2b_at` | queue flag + register | **bus unit** | the bus unit samples the level at its decision points; back to back = the line high at a fetch's last clock |
| `hold_fetch=le_q` (`hold_q=3`), `hold_count=ahead`, `free_hold`, `free_run`, `slot_fetch`, `request_reissue=no_mem` | arbiter + queue dating (`requested_at`, `rq_*`) | **arbiter** | from `q_low`, `q_starved` and the request line; no request dating in the queue. `hold_count=ahead` (bytes ahead of the running form) is the first candidate for a divergence: the arbiter would need the loader's `need` to subtract |
| `abort_fetch=retry`, `abort_latched`, `retry_first`, `abort_unit=loop` | queue retry registers | **bus unit** (the aborted cycle) + **ucode** (suspend windows for the loop forms) | the request line falling after commit |
| `room_ir=arrival_idle`, `room_ir_pre=modrm`, `pre_modrm=arrival`, `room_ir_imm`, `room_ir_ready`, `ea_ir_room`, `lea_room=ir`, `lea_slot=ea`, `far_room=take`, `xfer_mem_room=arrival`, `page_ir_room=end`, `modrm_mate=imm`, `modrm_port` | queue room rule (the seventh slot) | **loader** (when the opcode / ModR/M / immediate pops) | the pop's clock relative to the delivery, generated as decode attributes where the fit says the take is early or late; the queue only counts |
| `word_latch=byte_d`, `latch_read=commit`, `latch_hold`, `latch_midtake`, `latch_disp`, `latch_start`, `take_commit=at_end`, `release=byte`, `arrive_partial` | queue latch rules | **queue variant B** (a byte-wide write port and a one-byte latch, two structural bits) or **dropped** (variant A, word write) | §4 decides by the corpus; the five situational count rules go in neither case |
| `flush_hold=start`, `flush_from`, `ret_far_fetch=after`, `str_hold`, `str_fetch=hold`, fetch_hold / fetch_release rows, `bf_imm_hold=word`, `cvt_hold=word`, `count_latch` + `shift_until`, `nop_hold=any`, `io_ir_hold`, `io_hold=posted_b2b`'s fetch side, `xfer_odd=idle`, `xfer_nt=dbnz_z`, `xfer_abort=word`, `page_disp`, `page_dcommit=hold`, `page_fl_eval` | queue hold registers (fhold, rs, sh, fh, ox, ou, od, th, pb, pr, nop_held, io_held) | **ucode** | `SUSP` windows: row attributes `susp_set` / `susp_clr` (or a window length) emitted by ucgen from the same fitted rules; one queue input |
| `page_b2b=reg`, `page_b2b_win=run`, `page_run=field`, `xfer_nt_b2b=decide`, `refill_start=full_io`, `io_run_at` | queue one-shot commitments | **ucode → bus unit** | a `fetch_ask` row strobe if the corpus needs it; first try without it (the level may already be high) |
| `take_sync=pending`, `imm_landed`, `port_landed`, `start_sync=b2b_modrm`, `io_b2b`, `sync_req` | queue `asked` / `completed`, EU sync | **loader / ucode** | the EU stalls on `avail`; extra waits the corpus shows become rows (`WAIT` / `CLOCKS`), never a fetch count |
| `triple` (start, take, IR load on one clock), `starts > 2`, `take_addr`, `first` | queue | **dropped** | prelude and abort bookkeeping the simple machine does not need; the abort is the bus unit's |

## 4. Two structural variants to settle by the corpus

**A. Word write port.** A delivered word is stored in one clock. `free = 6 - cnt - 2·inflight`. The
cleanest machine; every `latch_*` rule is lost outright (they bind about 19,000 corpus rows by the
specification's count, so some families will move).

**B. Byte-wide write port with a one-byte latch.** The queue's storage has one write port shared by
delivery and the EU's reads (the chip's queue is plausibly a small register file with one write port);
a delivered word takes two clocks to enter, the second byte waiting in a latch. This is still a simple
mechanism (two bits of state and a fixed owner chain: the EU's read first, else the latch drains, else
the delivery's second byte latches). It keeps `word_latch=byte_d` and `latch_hold` as *structure* while
dropping the five situational counting rules (`latch_midtake`, `latch_disp`, `modrm_port`,
`latch_start`, `arrive_partial`).

Build A first (it is the lower bound and the simplest), measure, then B; keep whichever matches more of
the corpus *after* the loader's pop timing (§3, the seventh-slot family) has been placed. Do not reach
for a third variant: if neither closes a family, the miss is the EU's or the microcode's by hypothesis,
and it is recorded as such.

## 5. Method: constrain the machine, then find the implementation that matches the fit

The order matters: the queue is fixed first and the other units move to meet it, never the reverse.

1. **Write the queue (variant A) and the bus unit's sampling of the request line**, with the arbiter
   reading `fetch_req`, `q_low`, `q_starved`. Delete the queue's 120 situation ports and the request
   dating. The bus unit keeps its aborted cycle. Lint and the structure test as before.
2. **Move the holds into the microcode.** ucgen gains `susp` windows derived from the fitted hold rules
   (the rules stay in the model; the generator reads them as it reads every other field). The sequencer
   drives one `susp` output: the OR of the active windows and the FETCH_HOLD / QUIET rows it already has.
   The one-shot commitments start as *not built*.
3. **Place the pop timing in the loader.** The seventh-slot family becomes "the loader pops the opcode
   on clock X of its delivery / of the form's start": first the plain rule (pop when taken), then, where
   a family shows the fetch decision running a clock ahead of the loader, a decode attribute from ucgen
   that moves the pop. The queue is untouched by this step.
4. **Gate by silicon, with an accepted-loss budget.** The gate is `replay --core v35 --score` per family
   against the corpus as before, but the requirement changes from "RTL-exact ≥ model-exact" to "RTL-exact
   within the budget below, and every miss classified". A miss is classified by the first divergent
   event (`evtrace`): (a) an EU-side wait or a suspend window the microcode could express (recoverable:
   accepted), (b) a fetch the bus unit issued or held differently with the same request line
   (bus-unit sampling: fix if structural, else accepted and recorded), (c) a count the simple queue
   cannot produce (a real queue-mechanism gap: the only kind that may change the queue, and only through
   a structural knob, never a situation). The report lists the families, their RTL-exact counts against
   fit 62's, and the classification of every miss.
5. **Recover.** With the classification in hand, the recoverable misses are EU / microcode work packages
   in later stages (rows, decode attributes, loader timing), each with its own gate, and the queue stays
   as built.

**Budget.** The whole refresh-off corpus is 30,361 / 30,536 model-exact today. Families whose exactness
rests on the queue's situation rules are F6 (starvation, the aborted fetch), F12 and F16 (latched
deliveries, the shift count), F19–F21 (the latched byte with immediates and displacements), F23 / F25 /
F30 / F33 (the transfers' holds and the far forms), F32 / F34 / F39 / F40 (the 0F page's commitments).
An initial loss of 5–10 % of the runs in those families, with every miss classified as (a) or (b), is
acceptable for step 1; the recovery stages bring them back. Any family losing more than that, or any
miss of kind (c), stops the work for a decision.

## 6. What this changes elsewhere

- **The arbiter** loses the request-dating inputs (`rq_v_x`, `rq_now_x`, `rq_old_*`, `rq_clr_p`) and the
  queue's many room views; it keeps the data / I/O request records and decides fetch against data from
  the level and the two hints. This is a large simplification of its fetch-hold tree as well.
- **The sequencer** gains one output (`susp`) and loses about forty (`t_sth`, `rs_set`, `sh_set`,
  `fh_set`, `ox_set`, `nt_set`, `ou_set`, `ff_set`, `th_*`, `fl_*`, `pgb2b_e`, `pg_act_e`, ...). The
  S8 sequencer redesign (table-driven selection) is orthogonal: the suspend windows are row attributes
  whichever evaluator reads them, so this work can precede or follow S8's resumption.
- **The loader** owns the pop timing and the stall on `avail`.
- **The bus unit** owns sampling the request line and the aborted cycle; its pin timing is unchanged.
- **The model is not edited.** It stays the description of the fit; the generator reads its fields. The
  RTL's divergences from it become the list of EU / microcode features still to express, which is the
  user's stated expectation.

## 7. Work package

One Opus agent, one worktree, from ec5a146 (or the S8 landing if that resumes first): steps 1–4 above,
variant A then B, the gate report with the classification, a diff against its base. Its brief forbids any
situation rule in the queue (no input that names a form, a class, a row or an EU step other than `pop`,
`flush`, `susp`), caps the queue at 24 ports and 32 bits of state beyond the six bytes, and asks for the
per-family table and the miss classification before any recovery work. The overseer verifies on main,
records the per-family losses in the core v2 Record as the baseline the recovery stages are measured
against, and commits.

## 8. Outcome of Q1 (2026-11-07; the core v2 Record has the detail)

Variant B is the queue (24 ports, 34 bits of state beyond the bytes). Two structural knobs were needed and
approved: a read pointer and a release pointer (storage frees when a byte is read, the room when the take
step ends) and the IR as the staging byte counted in the capacity when empty. The start gate's wait for a
fetch on the bus and the take sync had to stay as EU rules on bus-unit facts (without them nothing matched).
`latch_hold` was dropped from the request line. Baseline: 23,691 of fit 62's 30,361 runs exact, F0–F2 and F24
lossless, F23 / F35 / F37 / F11 / F32 / F40 worst; misses classified 2,725 (a), 884 (b), 3,071 (c) of which
1,565 are the triple-clock aborted fetch that a level request line cannot produce, the one open question
about the queue's mechanism. Recovery stages measure against this table.
