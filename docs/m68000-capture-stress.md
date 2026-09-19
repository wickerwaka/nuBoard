# DDR100 capture stress test

Historical build-7 measurements. Current build 8 instead uses
[the BRAM buffer directly](m68000-bram-capture.md), with no PSRAM traffic.

Only DDR100 is supported: 100 MHz controller, 100 MHz quad writes, and 50 MHz
quad readback. The SDR200 RTL and build selection have been removed. An old
`PSRAM_PHY=sdr200` invocation fails before starting the build.

## Reproduction

Build with `bash fpga/m68000/build.sh`, then configure its timing-qualified
`build/fpga/m68000/outflow/m68000.hex.bin` using the normal host CLI.

```sh
PYTHONPATH=host/src build/venv/bin/python -m validation.m68000.stress \
  --backend sim --output build/validation/m68000/stress-simulation.json

PYTHONPATH=host/src build/venv/bin/python -m validation.m68000.stress \
  --backend board --lane both --socket-fitted \
  --reference build/validation/m68000/stress-simulation.json \
  --output build/validation/m68000/stress-board.json
```

The physical workflow requires the receipt-matched image already configured,
with VCCB disabled. It runs the full 2 MiB memory self-test before powering
the fitted MC68000P12 at an exclusive 5 V selection. FPGA and socket are never
captured together. Cleanup powers off VCCB and both FPGA rails, even on failure.

The default sweep is 64, 256, 512, 768, 1024, 1280, 1536, 2048, 4096, 8192,
and 16384 iterations. `--counts` changes the strictly increasing sequence;
`--patterns nop` or `--patterns read` selects one workload. Each finite loop
uses DBF, saves its final registers, and terminates through the normal pass
marker. The read workload repeatedly loads the word `0xa55a` at `0x200`.
The CPU clock, response wait states, output direction, and signal selection
are not changed to make the recorder keep up.

Each point first runs without recording, then with recording. The gate checks
CPU completion, exact elapsed ticks, all-transaction count/signature, retained
transaction contents, and final register stores. The transaction trace itself
is limited to its original 2048 entries; it is not claimed to contain all bus
cycles of a long run. Every downloaded waveform must have strictly increasing
timestamps and retain every 100 ns CPU-clock transition in its valid prefix.
The optional reference also compares every common FPGA-lane waveform byte
against simulation; physical CPU waveforms are not expected to be byte-identical.

Expected FIFO overflow is a *measurement*, not a complete waveform. The report
keeps `capture.complete=false`, the reason, first missed tick, all accepted
records, FIFO high-water, and CPU result. Unexpected CPU/memory/integrity
failures terminate the sweep without retry. Reports are saved after each point
and during cleanup. A `completed` campaign means its checks passed, not that
all its waveforms were complete.

## Sizing interpretation

The acquisition clock remains 50 MHz (20 ns), but only changed samples are
stored. Each change record is 8 bytes. The 5 MHz CPU clock alone changes
10 million times per second, requiring **80 MB/s** even when other signals
are idle. The 100 MHz quad write wire rate is **50 MB/s**, before command,
refresh, staging, and FIFO overhead. Thus no finite FIFO sustains unlimited
recording with the current all-signal change trigger.

The report measures the actual input byte rate. At overflow, an approximate
drain rate is `(accepted_records - 32768) * 8 / captured_duration`; up to
16 staged records and startup overhead make this an estimate, not a direct
SCLK throughput measurement. Required FIFO size is workload- and duration-
dependent: approximately `(input_rate - drain_rate) * duration`, plus burst
margin. The summary extrapolates the FIFO needed to accept 262144 records
at each measured workload rate; that larger configuration is not built or tested.

## Board results, 2026-09-19

DDR100-only image SHA-256:
`7cd986b6725d8bb2f438f4ea82738375ec896256b578cb12445f77ca0a7298fa`.
All 153 package assignments and 16 setup/hold relationships passed. Setup
slacks were +1.580 ns at 50 MHz, +0.426 ns for full-cycle PSRAM paths, and
+1.243 ns for the DDR half-cycle path. Minimum hold slack was +0.086 ns.
BRAM usage remained 929/1056 blocks. The FIFO was not resized.

Evidence:

- `build/validation/m68000/stress-ddr-only-board.json` and its `.log`:
  44 increasing-length physical trials, two workloads on each CPU separately.
- `build/validation/m68000/stress-ddr-only-sim-reference.json`:
  22 matching DDR100 simulation trials. Post-run comparison of workload image
  hashes and complete stored-record SHA-256 values matched all 22 board
  FPGA-lane cases, including overflow prefixes. The physical campaign ran
  while the reference was being generated, so this was an offline comparison.
- `build/validation/m68000/stress-reference-check.json`: exercises the
  optional in-workflow reference gate on a complete simulated NOP capture.
- `build/fpga/m68000/build7-ddr-only.log` and `receipt.json`: routed build gates.

The campaign passed: 16 complete waveforms and 28 explicitly truncated FIFO
overflow prefixes. All 44 capture-enabled CPU results matched their own
capture-disabled baselines, including exact elapsed ticks, transaction counts,
and signatures. Cross-CPU transaction counts/signatures also matched for all
22 workload/count pairs. Long runs retained only the original bounded bus
trace, so these signatures are not a claim of exhaustive bus-trace comparison.
The longest CPU run was 72.1111 ms; it completed after its recorder overflowed.
All retained waveforms preserved every CPU clock edge at 100 ns intervals.

| CPU / workload | Largest complete point in sweep | Valid prefix before FIFO overflow |
|---|---|---|
| FPGA / NOP | 38,162 records, 2.888 ms (1,024 loops) | 47,536 records, 3.598 ms |
| FPGA / read | 45,586 records, 3.400 ms (768 loops) | 47,216 records, 3.522 ms |
| MC68000 / NOP | 37,351 records, 2.172 ms (768 loops) | 43,088–43,216 records, 2.516–2.547 ms |
| MC68000 / read | 40,628 records, 2.274 ms (512 loops) | 42,544–42,576 records, 2.382–2.390 ms |

These are workload-specific observations, not a universal guaranteed capture
length. The sweep brackets the last complete program length; it is not a
one-iteration-resolution search. Physical pin propagation can spread changes
across more sample ticks than the FPGA model, and its exact boundary varied
slightly across runs. Every overflow reported a full 32,768-record FIFO and
the first missed tick immediately after the valid prefix. The records already
queued in BRAM were drained afterward; the table includes those records.

The observed change-record input rate was approximately 106–107 MB/s for the
FPGA and 136–143 MB/s for the socketed CPU. Inferred effective PSRAM drain
throughput was approximately 32.8 MB/s. Thus FIFO backlog grows continuously
during these workloads. After draining the FIFO, only about 16–18% of PSRAM
holds valid records; the limit is not the external memory's address capacity.

The 256 KiB FIFO is functioning correctly and supports these short capture
windows. It is **not sufficient for long uninterrupted all-signal captures**.
At the measured rates, accepting an entire 2 MiB of records would require
roughly 1.45–1.62 MB of FIFO buffering, far beyond the current buffer and
available BRAM budget. Even eliminating every PSRAM command/staging overhead
would leave the 50 MB/s wire ceiling below the 80 MB/s clock-only record floor.
Increasing the FIFO alone therefore cannot solve sustained recording. Longer
captures need a lower stored record rate/size or a faster storage path; no
trigger filtering, lossy sampling, CPU throttling, or FIFO resizing was added.

Verification also passed 37 Python harness/stress/timing tests, 16 generic host
tests, and RTL tests for memory requests, full PSRAM, FIFO wrap/overflow, PLL
faults, responder strobe skew, reset qualification, and immediate pin direction.
The campaign ran its full 2 MiB memory test before VCCB enable. Cleanup and a
separate final status read confirmed VCCB, 3.3 V, and 1.2 V off. All changes
were left uncommitted.
