# MC68000P12 / fx68k comparison campaigns

The campaign runner now requires the build-14, scope-ABI-4 harness. Build 10
adds opt-in [mirrored-RAM fuzzing](m68000-fuzz.md); directed tests use the
unchanged default memory map. It does not
change the MCU protocol, CPU clocks, ACK scheduling, immediate data direction,
continuous read drive, or the 32,768-record BRAM capture. PSRAM stays disabled.

Build 9 adds 4068-byte debug transfers, local memory fill, batched register
access and one broadcast initialization per paired repetition. It passed routed
timing/pin checks, physical debug-transfer checks and all 231 directed physical
comparisons on 2026-09-19. That paired run took 138.46 seconds. Evidence is in
`build/validation/m68000/campaign-extended/build9-board.json`; the earlier
recorded results below remain build-8 evidence. See the generic debug ABI section
in `docs/m68000-harness.md` for compatibility and failure semantics.

The first build-9 hour chunk completed 5,890 additional seeded paired cases in
3600.51 seconds, with zero state/timing differences and no transport/capture
errors. It covered full-suite indices 268 through 6157; the continuation resumed
at `--start-index 6158` (`not.w.absolute_w.05`). All rails
were confirmed off afterward. Throughput was 0.611 seconds/case, about 6.2 times
the prior chunk's rate; case mixes differ. The previous build-8 timing difference
remains recorded and was not retested in this chunk. See
`validation/m68000/build9-qualification-2026-09-19.json`
for evidence paths and hashes.

The continuation completed all remaining 7,057 cases in 4172.79 seconds, with
zero new differences or transport/capture errors. All rails were confirmed off
both by cleanup and a separate USB status read. The three runs cover every
manifest index 0 through 13214 exactly once, excluding the interrupted trailing
entry from the first run. Full-corpus accounting is **13,214 strict passes and
one retained strict timing failure**, with zero defined-state failures. The
failure is the previously analyzed build-8 DTACK sampling-phase difference,
with no observed marked-region execution-time difference; it has not been
waived or retested. See `validation/m68000/full-campaign-2026-09-19.json` for the
coverage audit, run hashes and retained failure. This is completion of the
selected seeded corpus, not exhaustive 68000 validation.

## What is tested

`validation/m68000/corpus.py` generates 231 directed smoke cases. The full
profile contains 13,215 cases at seed 68000: a broader size/addressing matrix,
five boundary operands and sixteen deterministic random operands per ordinary
form, plus directed exceptions. This is **not exhaustive opcode coverage**.
Register permutations, arbitrary initial prefetch state, external interrupts,
bus arbitration, injected bus faults, VPA cycles, and supervisor STOP/RESET are
not qualified by this suite. The manifest records these exclusions.

Coverage includes arithmetic/logic, shifts/rotates, condition codes and branches,
stack and return operations, MOVEM/MOVEP, TAS, BCD chains, both byte lanes,
PC-relative/indexed reads, page-crossing long accesses, and byte-sized A7
increments. Synchronous cases cover address error, illegal instruction,
divide-by-zero, CHK, TRAPV, privilege violation, trace, line A/F, and all sixteen
TRAP vectors. User-mode execution has directed coverage, not every instruction
form repeated in both modes.

Each case boots through actual reset vectors. Native assembly initializes state;
there is no internal fx68k register injection. Registers and SR are saved before
reporting instructions alter flags. Vector-specific exception entry stubs save
the entry registers and original stack frame. The normal collector's TRAP #15
is outside the timed interval and is distinguished from a TRAP #15 under test.
Normal control-flow destinations are evidenced by instruction/bus traces;
exception PCs are retained in their frames. Internal prefetch registers are not
observable on the socket and are not claimed as checked.

The native memory layout is: vectors at 0, data at `0x2000`, supervisor/user
stacks below `0x4000`/`0x5000`, results at `0x5000`, markers at `0x6000/0x6002`,
and code at `0x10000`. Every run reloads the mapped pages. Longword completion
uses the existing MMIO write at `0x100004`.

## Verdicts and timing policy

A single simulation run qualifies **wrapper completion and expected exception
delivery**, not arithmetic equivalence. Differential validation requires a
physical reference or another explicitly identified reference report.

Reports distinguish:

- Defined-state differences: registers, defined SR bits, memory, exception
  vector, and defined frame fields.
- Chip compatibility: all raw values are retained, including undefined flags
  and reserved address-error status bits. A chip-only difference is reported
  separately, not promoted to an ISA failure or silently discarded.
- Timing: exact half-cycle count and phase-level bus equivalence.

Flag classification is operand-sensitive: for division overflow N/Z are
undefined but V is still checked; successful division checks all CCR bits.
CHK, divide-by-zero, and BCD use their instruction-specific masks. The policy
version and effective mask are recorded in each comparison. See the
[programmer's reference manual](https://www.nxp.com/docs/en/reference-manual/M68000PRM.pdf).

Timing aligns once after the opening marker, never independently per transfer.
The final 20 ns observation before each clock edge represents that phase. The
preceding observation checks CPU-output stability. Unresolved output changes
produce `indeterminate`, not a pass. FPGA-generated synchronous DTACK/BERR are
compared at the phase observation; they do not use the asynchronous-output
guard. Newly qualifying read data is checked against actual earlier bus data,
not against an absent dictionary field.

Address, FC, and direction are compared while AS is active. Write data is
compared while its byte strobes are active; read data is compared after ACK.
Inactive bytes and unspecified idle bus values are ignored. Raw 20 ns records
remain available. These are FPGA digital observations, **not electrical setup/
hold or contention measurements at the CPU package**.

The measured region includes deterministic setup and register collection
overhead. Counts are labelled as bracketed-region half cycles, not isolated
instruction latency. Trace mode is off except when deliberately testing trace.
Reset-vector timing is outside the marked region. No baseline subtraction or
per-instruction timing claim is made by this runner.

## Build and run

Use the existing project virtual environment and GNU m68k binutils:

```sh
export PYTHONPATH=host/src
build/venv/bin/python tools/fetch_m68000.py --verify-only
build/venv/bin/python -m validation.m68000.campaign build --profile smoke
build/venv/bin/python -m validation.m68000.campaign run \
  --target sim --output build/validation/m68000/campaign/sim.json
```

After verifying the build receipt, configure the board and run the socket and
FPGA **sequentially**, each with its own complete capture:

```sh
build/venv/bin/python tools/check_m68000_build.py
build/venv/bin/python -m nuboard.cli --json configure \
  build/fpga/m68000/outflow/m68000.hex.bin
build/venv/bin/python -m validation.m68000.campaign run \
  --target board-pair --socket-fitted \
  --reference build/validation/m68000/campaign/sim.json \
  --output build/validation/m68000/campaign/board.json
```

Board preflight requires the receipt-matched build 9, VCCB off, and exclusive
5 V for the fitted MC68000P12. Every exit requests power-off and verifies all
three rails disabled. Closing a USB client is not substituted for power-off.

Select a small reproduction with `--case nop tas exception.address_read` and
use `--repeats 3` for planned qualification repetitions. Valid mismatches are
retained and execution continues until the default 20 mismatching-case limit.
Transport/power faults, incomplete captures, timeouts, unresolved sampling, or
nondeterministic repetitions stop the campaign. There are no automatic retries.

Cases must finish within 500,000 acquisition ticks (10 ms) and fit the BRAM
buffer. Neither a capacity prefix nor a hash alone can qualify a comparison.
The older Musashi runner remains available for long functional programs and
verified transaction-window replay; those are not native timing cases.

### Full simulation and sharding

Build the full profile into a separate directory. Simulation shards use
`--shard-count N --shard-index I` and independent output files. Run indices
`0..N-1`; only simulation processes may run concurrently against this setup.
Do not run multiple USB campaigns against one board.

```sh
build/venv/bin/python -m validation.m68000.campaign build --profile full \
  --directory build/validation/m68000/full
build/venv/bin/python -m validation.m68000.campaign run --target sim \
  --directory build/validation/m68000/full --shard-count 8 --shard-index 0 \
  --output build/validation/m68000/full/shard-0.json
```

After all eight shards finish, `campaign merge --reports <eight report paths>
--output <merged.json>` verifies compatible manifests, complete shard coverage,
unique case IDs, and hashed case evidence. A missing/incomplete shard is rejected.

### Offline comparison and evidence

```sh
build/venv/bin/python -m validation.m68000.campaign compare \
  --reference build/validation/m68000/campaign/board.json \
  --candidate build/validation/m68000/campaign/board.json \
  --reference-lane socket --candidate-lane model --case tas \
  --output build/validation/m68000/campaign/tas-comparison.json
```

Each campaign index points to hashed per-case JSON, preserving raw captures,
transactions, snapshots, stimulus identity, and comparisons. Assembly, linked
symbols, binary images, compiler identity, seed and coverage metadata are kept
with the corpus. SVGs show the first differing phase with clock, strobes,
direction, acknowledgement, address, and selected data. Reproduction commands
are attached to differing cases. Failed acquisition evidence is saved too.

## Upstream suites

Musashi's pinned 60-program suite remains a separate smoke oracle. Do not amend
its expectations to make existing ABCD/SBCD/DIVS/DIVU failures disappear.

The pinned [SingleStepTests/m68000](https://github.com/SingleStepTests/m68000)
files can now be acquired explicitly with revision, license, decoder, and file
hash provenance:

```sh
build/venv/bin/python tools/fetch_m68000_vectors.py \
  --instructions MOVE.q ADD.w SUB.w AND.w OR.w CMP.w
build/venv/bin/python -m validation.m68000.vector_campaign --limit 100 \
  --output build/validation/m68000/imported-registers.json
```

The imported adapter accepts MOVEQ and two-byte register-source ADD/SUB/AND/OR/
CMP forms. It rejects memory, address-register, faulting, and control-flow forms
rather than claiming general single-step support. Its trace wrapper does not
qualify upstream bus timing or final prefetch. Those fixtures are generated from
MAME and remain a secondary expectation source, not the physical oracle.
The upstream TAS/TRAPV caveats are covered by independent native cases here.

WinUAE's Amiga-specific tester is not integrated. No fx68k, MCU, or FPGA
responder fixes are included in this work.

## Initial build-8 qualification on 2026-09-19

The [checked-in summary](../validation/m68000/comparison-2026-09-19.json) records
the exact image and evidence hashes. Raw indexed evidence remains under the
ignored `build/validation/m68000` tree.

- 231 unique physical cases passed defined-state and clock-phase comparison;
  no chip-compatibility differences were observed in these cases. Every board
  model case also matched its Verilator reference.
- Nine directed cases passed three planned repetitions. All 36 within-lane
  timing comparisons against the first repetition passed.
- All 13,215 native seeded cases completed in Verilator with their expected
  exception behavior. This is wrapper qualification, not 13,215 silicon matches.
- All 600 imported vectors passed, 100 eligible cases from each of six files.
- Musashi remains 56/60: ABCD, SBCD, DIVS, DIVU still fail its expectations.
  These are not newly established silicon/core mismatches.
- Python validation, generic host, pin, strobe-skew, BRAM, and routed timing/pin
  gates passed. A fresh USB status check confirmed VCCB and both FPGA rails off.

The full seeded physical campaign was subsequently completed as described
above. To start a new full run after configuring the qualified image, choose
a fresh output filename:

```sh
build/venv/bin/python -m validation.m68000.campaign run \
  --directory build/validation/m68000/campaign-full-v2 \
  --target board-pair --socket-fitted \
  --reference build/validation/m68000/campaign-full-v2/full-sim.json \
  --output build/validation/m68000/campaign-full-v2/full-board.json
```

The default 20-mismatch stop remains active. A truncated or stopped campaign
is recorded as incomplete, never as a complete pass.

### Time-bounded hardware chunks

Add `--duration-seconds 3600` for a one-hour chunk. The budget starts at runner
preflight; it finishes an in-flight case before powering off, so shutdown can
occur a few seconds after the deadline. Safety faults and the mismatch limit
still stop earlier. A clean budget stop sets `chunk_completed: true` while
`completed` remains false for the unfinished selection.

The report records `finished_cases`, `next_case_index`, and `next_case_name`.
After configuring the image again, continue with `--start-index INDEX` and a
new output filename. Keep the same manifest, case filters, and shard settings:
the index is relative to that ordered selection, not a global instruction ID.
