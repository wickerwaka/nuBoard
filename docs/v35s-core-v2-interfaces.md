# V35S core v2: interface plan

Status: **approved by the user 2026-11-14 (section 7's decisions recorded there). Nothing here is built yet.** Written after the user's direction that
timing work cannot proceed on the present structure: the modules expose internal state to each
other in ways silicon would not, a legacy of rules carried over from the chain model. The facts
below are from a referenced inventory of the RTL at a6924ed (every crossing signal, stall term and
glue block, with file:line); numbers are from that inventory, which read the code but ran nothing.

## 1. Where the core is

- **149 signals cross between the six core modules**; 33 of them are next-value duplicates of
  another crossing signal, added to close timing at 17 ns. About 30 more enter from glue in
  `v35_top`.
- **The sequencer's stall has 12 terms. Nine have no hardware behind them.** Each is explained in
  its comment by a shared resource (an internal bus, a register-file write port, the queue's
  port), but no such resource exists in the RTL: the rule reads another module's state and waits.
  Six of the twelve read the bus cycle's phase.
- **The bus grant reads the loader's pop events** (instruction start, operand take, staging load)
  for two rules (the aborted fetch, the hold after an I/O issue), and two **fitted integers** from
  fit 62 remain (`FIT_HOLD_Q` = 3, `FIT_IO_RECOVER` = 2).
- **The queue is not a FIFO a designer would draw.** The loader decides how many bytes leave (up
  to two a clock), re-derives the queue's head select, keeps the head's address, and stores decode
  facts in the queue as per-byte tags. Room accounting is split across both modules.
- **State is held twice** in at least eight places (the grant's tick-B copy in bus and top, the
  on-chip address decode in bus and top, fetch-in-flight in bus and queue, the request line
  registered in the sequencer and the bus, deliveries owed counted in the sequencer).
- `v35_top` holds about 250 lines of logic that belongs to a module: the interrupt / DMA / macro
  service take (102 lines), the on-chip cycle (50), STOP (32).

The core is cycle-exact on 6,541 of 30,536 corpus runs. Most of that count was bought by the nine
rule-only stalls and the grant rules. They are the thing to remove, so **the exact count will fall
before it rises**. Function (programs, fuzz, SingleStepTests, vectors, write data) must not move.

## 2. Principle

A signal may cross a module boundary only if a designer would have routed a wire for it:

1. **A wait is one of two things.** Either a microcode word that does nothing for a clock (the
   routine is longer), or a wait on a resource that exists: one signal, owned by one module, that
   both users see. Never a rule that reads another module's phase.
2. **No module exports its internal state.** The bus says *done* and gives the datum; it does not
   say which clock of a cycle it is in.
3. **No module exports a next value.** If a registered decision is needed for 17 ns, the module
   that makes the decision registers it from its own narrow inputs.
4. **State lives once.** A second copy for timing is local to the module that owns the original.
5. **No fitted integers.** A count is a property of a mechanism (a pipeline depth, a counter's
   width) or it is absent.
6. **Names describe hardware,** not the model's time base ("ended on t-1").

## 3. The target machine

Six units; the arrows are the whole interface.

### 3.1 Bus unit (`v35_bus`)

Owns the pins, the cycle state machine, wait states, READY, bus hold, the odd-address pair, **and
the on-chip cycle** (the internal RAM / SFR decode and access move in from `v35_top`; decoded
once).

| Port | Direction | Signals |
| --- | --- | --- |
| EU request | EU → bus | request, kind (mem / I/O, read / write, INTAK, DMA), address, width, write datum |
| EU reply | bus → EU | accepted, done, read datum |
| Fetch | queue → bus | request, address |
| Fetch reply | bus → queue | accepted, word valid, word |
| Internal bus (see 4) | bus → all | busy (one signal), *only if* measurement supports it |
| Pins, SFR configuration | | as now |

Out: every phase fact (`fetch_inflight`, `fetch_past_b2`, `in_wait`, `b2b_now`, `g_abort`,
`cpu_end_prev`, all `_nx`), the 14 dead outputs, and the three loader events as inputs. The
priority between a fetch and an EU request is the bus unit's own, from its own two request inputs.

Target: **about 12 function signals** to the other core modules (today 26 out, 15 in).

### 3.2 Queue (`v35_queue`)

A self-contained FIFO: storage, count, the prefetch pointer **and the head's address**, the
request line from its own occupancy.

| Port | Direction | Signals |
| --- | --- | --- |
| Read | queue → decoder | byte valid, byte, the byte's address |
| Pop | decoder → queue | pop (one strobe) |
| Control | EU → queue | flush + new address, suspend |
| Fetch | as 3.1 | |

Out: the four byte lanes, the latch byte and its flags, the tags, the head-select facts, `rd` /
`rel` / `stg` as three separate room inputs, the next values, `q_low` / `q_word`.

Open design question (section 6, item 2): whether one byte leaves per clock. Today up to two do
(an operand byte plus the load of the next opcode into the loader's staging slot).

### 3.3 Decoder (`v35_loader`, shrunk)

The opcode, ModR/M, immediate and displacement registers and the decode tables. It pops bytes when
the microword asks and presents the routine's entry address. It holds no room accounting, no head
address, no tags. Whether the staging slot survives depends on item 2.

### 3.4 Sequencer (`v35_useq`)

The microcode ROM, the microword register, the loop counter, and a stall with **four** inputs:

| Stall | Source | Resource |
| --- | --- | --- |
| the word pops a byte and none is valid | queue | the queue |
| the word needs the read datum and it is not here | EU / bus *done* | the bus cycle |
| the word posts a request and the slot is taken | EU | the one request slot |
| halted | interrupt unit *wake* | HALT / STOP |

Plus the internal-bus wait, if section 4 establishes it. Everything else currently in `stall_f`
goes.

### 3.5 Execution unit (`v35_eu`, `v35_regram`, `v35_ea`)

As now at the bus port. It keeps the decoded registers it reads from the decoder (opcode, ModR/M,
immediates, IP): that is a real datapath connection.

### 3.6 Interrupt and service unit (new, or inside `v35_intc`)

The take decision (NMI, maskable, macro service, DMA, single step, the prefix and arming holds)
and STOP move out of `v35_top` into one module.

| Port | Direction | Signals |
| --- | --- | --- |
| Take point | sequencer → unit | "an instruction boundary / a string's take point is here" |
| Take | unit → sequencer | take, entry address |
| Parameters | unit → EU | vector / channel / mode (as now, from one place) |
| Acknowledge | sequencer → unit | acknowledge, FINT |

## 4. What happens to each inherited rule

Each of these bought corpus runs, so each is evidence about silicon even though its present form
is wrong. The proposal is to **remove them all, measure the plain machine against the corpus, and
bring timing back only as a mechanism** under section 2.

| Rule today | Reads | Disposition |
| --- | --- | --- |
| Move into the address / datum register waits in a memory wait state (`st_bw`) | bus phase | Candidate for a real **internal bus busy** signal |
| Multiply / divide step waits while a fetch is past its second clock (`st_uh`) | bus phase | Same candidate; if the one signal does not explain both, it is not that |
| Dispatch waits while a fetch runs (`st_fch`) | bus phase, loader | Same candidate, or the decode genuinely shares the queue's write clock: decided by the queue's design (3.2), not by a rule |
| Wait for fetched words owed after an operand pop (`st_tsy`, a counter in the sequencer) | bus, queue, loader, EU | Remove. If real, it is the queue's read port being unavailable on a write clock: the queue's *byte valid* says so |
| SUSP and the decide's wait for a running fetch (`st_sus`) | bus phase | Suspend stays (queue input). The wait for the running fetch: internal-bus candidate or removed |
| Refill wait after a flush (`st_rfl`) | bus, queue | Remove; a flushed queue is empty, *byte valid* is low until the first word arrives |
| Write-back waits before OUT (`st_wp`, `st_wbw`) | loader decode of the *next* opcode | Remove. Reads the staged next opcode: against the 2026-11-09 rule already. If real, it is the register file's write clock, visible to the routine that reads the register next |
| RAMEN write hold (part of `st_f`, `st_hld`) | EU, SFR | Becomes real: with the on-chip cycle in the bus unit, a write is *done* when it is done |
| Hold after an I/O issue until the next start (bus `ioh`) | loader events | Remove |
| Aborted fetch on the triple clock (bus `ab_tri`, `q_word`) | loader events, queue | Remove the loader inputs. Whether silicon has an aborted cycle at all is an open question in the record |
| I/O recovery window (`FIT_IO_RECOVER`), queue low hint (`FIT_HOLD_Q`) | fitted integers | Remove; re-derive from the bus unit's own turnaround if measurement shows one |
| Reservation (`req_resv`, microword `resv`) | EU → bus | Keep only if it becomes "the EU's request is up" (request raised early); otherwise remove |
| Queue latch, `unrel`, `lat_hold`, the uncounted second byte | loader `rel` | Internal to the queue, expressed on its own state |
| Microword flags `wb`, `wp`, `fw`, `nb`, decode `wbs`, `rq` | read only by stall rules | Removed with their rules; `nb` (no take between prefixes) stays, it is function |

The internal-bus candidate is a hypothesis, not a finding: three or four of the rules have been
explained by "the fetch holds the internal bus for its datum". If one busy signal with one
definition reproduces them together, it is a mechanism; if each needs its own window, it is not,
and those rules stay out.

## 5. Two ticks and timing closure

Two fabric ticks per CPU clock stay (17 ns). What changes is that closure may not add crossings.
With four stall inputs, each already a register in its owner, the sequencer can register its own
stall outcome without anyone's next value; the cross-module tick-A chain (sequencer → loader →
queue → request → grant) shortens because the loader's room arithmetic leaves it. This is a
claim to be proven by the three-seed build at each step, not assumed.

## 6. Order of work

Every step gated on function: program gates, fuzz, SingleStepTests, vectors, write data, lint,
three seeds at 17 ns. The corpus exact count is **reported, not gated**, from step D on.

| Step | Content | Behaviour |
| --- | --- | --- |
| A | Collapse the 62 switches, delete dead ports (in progress) | identical, clock for clock |
| B | Move glue into its owner: on-chip cycle into the bus unit, the take logic and STOP into the interrupt unit; remove duplicated state | identical |
| C | Queue self-contained: head address, room accounting and tags inside; decoder shrunk | identical if two bytes a clock is kept; otherwise see item 2 |
| D | Remove the rule-only stalls, the bus phase outputs, the loader events into the grant, the fitted integers | **timing changes**; this is the plain machine's baseline |
| E | Timing rebuilt, one mechanism at a time, each tested against the whole corpus | rises from the baseline |

`test_v35_struct` gains the port budget (signals per module pair, no `_nx` outputs, no model
names) so the structure cannot drift back.

## 7. Decisions (user, 2026-11-14: "Accept the drop, follow your recommendations on the rest")

1. **The drop in the exact count at step D is accepted.** It is measured on a throwaway build
   before the order of D is fixed.
2. **Two bytes a clock from the queue through step C;** one or two decided at D with the
   baseline in hand.
3. **The aborted fetch cycle is removed at D;** the corpus shows whether silicon needs it.
4. **Idle microcode words are acceptable** as the way to make a routine longer; each still needs
   a mechanism (the 2026-11-09 rule).
5. **Step B (glue into its owners) before step C (the queue).**
