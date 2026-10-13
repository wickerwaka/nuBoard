# V35S core: implementation plan

This replaces Phase 4 of the original harness plan, which forked nuV30's
ucore. [`v35s-core-decision.md`](v35s-core-decision.md) explains why: the
V35S has its own execution-unit timing, so the V20 microcode cannot be
cycle-exact behind any bus unit. The work-item IDs (A1, C1, …) refer to
[`v35s-differences.md`](v35s-differences.md).

## Goal

A new core, `v35_core`, in `fpga/v35s/core/`. It produces the same full bus
trace as the socketed µPD70337 (every cycle, address, data, strobe and state)
in normal mode (N/S high).

1. **First:** the instruction set and the bus at fX/2.
2. **Next:** other clock rates, waits and refresh settings.
3. **Then:** register banks, interrupts and peripherals.

## Principles

- **Silicon decides.** The data book and MAME are hypotheses. Each timing
  rule in the core is supported by one or more traces from the board.
- **Timing comes from shared mechanisms, not a clock-count table.** An
  instruction costs what its steps cost: decode, register-RAM accesses, EA,
  ALU, bus requests, and queue waits. A form whose timing no mechanism
  explains is an open question to measure, not an exception to code.
- **Model before RTL.** A Python cycle model is fitted to the recorded traces
  first. The RTL is then written to match the model. Iterating against
  6,000 stored traces in Python is much faster than synthesis and board runs.
- **Every stage has a gate.** Each phase ends with a check that runs offline
  against stored silicon traces, plus a board run.
- **Keep the ucore until the new core beats it.** `v35s_model.sv` stays
  buildable until the new core passes the Phase 3 gate. Then the
  `core/ucore/` fork is removed.

## Architecture

```
            +-------------------------------- v35_core -------------------------------+
  x_rise -->| clock gen (PCK)  ->  ce_cpu (one per CPU clock), ce_state (bus state)   |
            |                                                                          |
            |  +---------+  queue words  +-----------+  reg RAM port  +-------------+  |
  bus pins<-|->|  BIU    |-------------->|    EU     |<-------------->| internal RAM|  |
            |  | seq,    |<--------------| decode,   |                | 8 banks x32B|  |
            |  | queue,  |  data req/ack | sequencer,|  SFR port      | + 256B data |  |
            |  | refresh,|               | ALU, EA   |<-------------->+-------------+  |
            |  | IDA,    |               | PC, PSW   |                | SFR block   |  |
            |  | reset   |               +-----------+                +-------------+  |
            |  +---------+                                                             |
            +--------------------------------------------------------------------------+
```

- **Clocking.** The harness's X1 enables (`x_rise`/`x_fall`) drive a PCK
  divider (fX/2, /4, /8). The core runs one step per CPU clock. The port list
  is the same as `v35s_model.sv`, so the lane, the harness and `build_sim.sh`
  do not change.
- **BIU (`v35_biu.sv`)**
  - **Bus states:** a B1 / B2 / Bw* / B3 sequencer with the measured edge
    placement, which the current shell already has (port it, don't
    re-derive it).
  - **Queue:** three words.
  - **Fetch policy (from A2):** after a flush, fetch back to back. Fill to
    the word boundary that the 6-byte budget allows. For an odd target, fetch
    the byte first.
  - **Data cycles:** a data request takes the next free bus slot. A
    read-modify-write goes read, gap, write.
  - **Waits and READY:** waits come from WTC. READY is sampled in BAW2.
  - **Refresh:** a refresh timer from RFM, with its own bus slot.
  - **IDA routing:** data accesses to xxE00–xxFFF and FFFFF stay internal.
  - **Reset exit:** from A3 — first refresh about 16 fX/8 states after
    /RESET rises, first fetch about 10 states later.
- **Internal RAM (`v35_iram.sv`).** 256 bytes holding the register banks and
  the data RAM, which is the same storage. The EU reads and writes registers
  through this RAM, and bus-side data accesses reach it too. PC, PSW and a
  copy of the current bank number are flops.
  - **Open question:** whether the core has one RAM port or two, and how
    many clocks a register access costs. This is the main thing the
    register-access probes (M3) must settle.
- **EU (`v35_eu.sv`)**
  - **Decoder:** prefixes, the 0F page and ModR/M, with lengths and operand
    classes taken from nuV30's `instructions.json`.
  - **Sequencer:** runs a short list of steps per instruction class. Each
    step has a cost: register read, register write, EA, ALU,
    MUL/DIV/shift loops, memory read, memory write, wait for queue, and
    flush.
  - **Cost table:** the step costs are parameters in one generated include
    file, produced from the fitted Python model.
  - **ALU and flags:** follow nuV30's semantics, including its notes on
    undefined flags. They are checked with SingleStepTests.
- **SFR block (`v35_sfr.sv`).** The SFRs the core needs to work: PRC, WTC,
  RFM, IDB, FLAG, ISPR, and the xxIC registers. Ports and peripheral SFRs are
  plain storage until Phase 6.

**Resources:** the model image today uses 22% of the logic and 938 of 1,056
block RAMs, most of them for the scope. The new core needs about one block
RAM for internal RAM. It should come in under the ucore's logic, because it
has no microcode ROM or PLA tables.

## Phases

### Phase 0: close step 1

- [x] Commit the step-1 probes and docs (`timing.py`, `timing_report.py`,
  `prefetch.py`, the differences and decision docs).
- [x] **A1:** rerun `characterize` on build 2 (30 ns tick) and replace the
  build-1 receipt in `v35s-bus-timing.md`.
- [x] Make `timing.json`, `prefetch.json` and the characterize receipt the
  first **silicon corpus**. Store them in `build/validation/v35s/corpus/`
  with a manifest of harness build hash, settings and date. Everything
  offline checks against it.

### Phase 1: measurements the design needs

Each probe extends `timing.py` or `prefetch.py`. Results go into the corpus
and a short section in `v35s-bus-timing.md`.

| ID | Probe | Settles |
| --- | --- | --- |
| M1 | A6 at WTC = 2 waits, and with refresh on | how waits and refresh shift data cycles and fetches; W terms |
| M2 | A6 with RAMEN = 0 | the bracketed book counts; write buffering |
| M3 | Register-access probes: the same operation through opcode-embedded register, ModR/M register, and an internal-RAM data address; byte vs word; each bank | the internal RAM's port count and access cost (the Architecture open question) |
| M4 | EA sweep: every mod/rm, disp8/16, segment prefix, odd/even operand | EA cost; odd-address penalty (+3 seen) |
| M5 | Data-dependent sweeps: MUL/MULU/DIV/DIVU operands, shift/rotate counts 0–31, REP counts 0–3 and larger, EXT/INS widths, PREPARE levels | loop costs per mechanism |
| M6 | Prefetch at the edges: fills around refresh, around a held READY, at 2 waits, branch to each byte alignment | BIU arbitration rules |
| M7 | A4 refresh placement while running and in HALT (the 60-state interval) | refresh timer details |
| M8 | A5 internal RAM / SFR data access cost, IDB relocation, xxE00 with RAMEN = 0 | IDA routing and its timing |
| M9 | A10 PSW masks and A8 undefined opcodes | functional rules for Phase 4 |

The A6 sweep took about 7 minutes. M1 to M5 together are about 3,000 runs,
or roughly an hour of board time.

**Status (2026-10-12):** done, including the follow-ups (EXT/INS, the
signed-multiply rule, banks, undefined 0F, the RAMEN write penalty). M1 to M5, M8 and M9 are in that
doc; M6 and M7, plus READY (A7), are in
[`v35s-bus-timing.md`](v35s-bus-timing.md). Every run is in the corpus.
The board time was about 15 minutes, not an hour.
- **M3 result:** register access is through the internal RAM. A register
  read-modify-write costs 6, and register moves and ALU operations 3.
- **M2 result:** RAMEN = 1 adds 3 clocks to every data write.

### Phase 2: Python cycle model

**File:** `validation/v35s/model/` (`biu.py`, `eu.py`, `costs.py`,
`semantics.py`).

- **What it does:** runs an image and emits `Transaction` records in the
  same format as the lane trace, so `compare_traces` works on it unchanged.
- **Semantics:** a small functional 8086/V-series interpreter. It is checked
  against nuV30's SingleStepTests for the shared opcodes before any timing
  goes in.
- **BIU:** the fetch and arbitration policy from A2, A3, M6 and M7.
- **EU:** each instruction class is a list of steps. Step costs live in
  `costs.py`.
- **Fitting:** `validation/v35s/fit.py` fits the step costs against the
  corpus and lists every case that still differs. A case left over after the
  fit means a missing mechanism. Measure it (back to Phase 1); do not patch
  that opcode.
- **Gate:**
  - every non-flow A6 form and every prefetch scenario matches its full
    trace (cycle times and order) at 0 waits;
  - at least 95% match under M1 (waits, refresh) and M2 (RAMEN = 0), with
    the rest written up.
- **Output:** `costs.py` generates `fpga/v35s/core/v35_costs.svh`, and the
  documented step model becomes `docs/v35s-core-model.md`.

### Phase 3: RTL bus unit and a skeleton EU

- **What to build:**
  - `v35_biu.sv`, `v35_iram.sv` and a minimal `v35_sfr.sv`;
  - an EU that only knows what `smoke` and the probe windows use: MOV
    imm/mem, OUT, NOP, BR near/far, SHL, and the setup stores;
  - a `v35_core` wrapper with the `v35s_model` ports.
- **Selecting the core:** `build_sim.sh … model|v35|stub` and a build define
  choose ucore or the new core.
- **Offline check:** `validation/v35s/replay.py` runs a corpus case in
  Verilator and compares its trace to the stored silicon trace. It also
  compares against the Python model.
- **Gate:**
  - `smoke` matches the full trace (`--mode both`, not `--program-only`)
    on the board;
  - every prefetch scenario and the reset sweep match in replay;
  - the image meets timing and passes `tools/check_v35s_build.py`.

### Phase 4: execution unit, group by group

Groups go in this order. Each group is done when its A6/M-forms match in
replay, its functional checks pass, and a board spot check (`timing.py
--case <group>`, model lane) matches.

1. Data moves, immediates, XCH, LDEA, segment moves, prefixes
2. ALU reg/mem/imm, INC/DEC, NEG/NOT, TEST, CMP
3. Shifts and rotates (fixed and CL), ROL4/ROR4
4. MUL/DIV (signed and unsigned, data-dependent)
5. Stack: PUSH/POP, PUSH R/POP R, PREPARE/DISPOSE
6. Control flow: Bcond, DBNZ/BCWZ, BR/CALL/RET near and far, indirect
7. Strings and REP, including interrupted-REP restart (needs Phase 6 to test fully)
8. BCD adjusts and CVTxx, TRANS, CHKIND
9. Bit ops: TEST1/SET1/CLR1/NOT1, EXT/INS, ADD4S/SUB4S/CMP4S
10. Traps: BRK, BRKV, divide error, FPO (vector 7), I/O trap (BRKI = 0, vector 19)

**Functional check:** a SingleStepTests adapter runs nuV30's V20 suite
through `replay.py`'s Verilator harness by injecting state through a prelude
(G4). Expected differences are listed explicitly: no 8080 mode, the PSW bit
layout, and the FPO trap.

**Gate:** the whole A6 corpus plus M1 to M5 match in replay, and
`timing.py --backend board` matches in both lanes on every form.

### Phase 5: V35 programmer's model

- **Registers and PSW:**
  - banked registers are live in internal RAM;
  - bank switching through PSW.RB;
  - the PSW masks for POP and MOV;
  - F0/F1 linked to FLAG;
  - reset state F002, bank 7 (B2 to B4).
- **New instructions:** BRKCS, TSKSW, MOVSPA, MOVSPB, RETRBI, FINT, BTCLR,
  STOP. Also HALT's wake rules, POLL, and BRKS/BRKN with MD handling (D2,
  D4 to D6).
- **Silicon first:** each is measured with a directed program before it is
  coded (A10, plus new timing cases in `timing.py`).
- **Gate:** a new directed program `banks.s` and the new timing cases match
  on the board.

### Phase 6: interrupts

- **Harness:** add the inputs the tests need (G3): scheduled INTP0–2, NMI
  and INT drives, and an INTAK responder in `v35s_harness.sv`.
- **Measure, then build:** measure A9 first, then build E1 to E3 (priority
  controller, ISPR, vectored and bank-switch entry, latency).
- **Then:** macro service (E4), once the timers or serial channels can raise
  requests.
- **Gate:** interrupt programs match the full trace, including entry
  latency, against N.

### Phase 7: peripherals as programs need them

Ports with the harness bank handoff (F1) come first. Then the time base,
timers, serial, DMA and STBC (F2 to F6). Each is measured from silicon
before RTL. These are separate plans when the time comes.

## Verification summary

| Level | Tool | Runs |
| --- | --- | --- |
| Function | Python model and RTL against SingleStepTests | every change |
| Cycle, offline | `fit.py` (model) and `replay.py` (Verilator) against the silicon corpus | every change |
| Cycle, board | `timing.py`, `prefetch.py`, programs with `--mode both` | each phase gate |
| Random | fuzz campaigns ported from the 68000 harness (G2), once Phase 4 is done | nightly |

## Risks

- **The register-RAM hypothesis is wrong or incomplete.** Then the step
  model needs a different set of mechanisms. M3 tests it before any EU RTL
  is written, and Phase 2's leftover cases will show it early.
- **The fit lands on numbers instead of mechanisms.** Watch the parameter
  count: if `costs.py` grows toward one entry per opcode, stop and measure.
- **Board time.** About an hour per full sweep. The corpus plus offline
  replay keeps that to the phase gates.
- **Block RAM.** The scope uses most of it. The core needs about one block.
  If that is short, make the scope depth a build option (G5).
- **Secure mode** (MD = 0, opcode translation) stays out of scope. The core
  keeps a pass-through hook where the translation table would sit.
