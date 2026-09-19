# Single-CPU PSRAM waveform capture (scope ABI 3)

Historical build-7 design and results. Current build 8 uses
[BRAM-only capture](m68000-bram-capture.md); PSRAM is no longer in the capture path.

Build 7 replaces the paired 512-sample recorder with a passive, single-lane
change recorder. The CPU and observation clock remain unchanged: 50 MHz fabric,
20 ns observations, and the existing programmable CPU clock divider. The
recorder never delays CPU clocks, memory responses, or buffer turnaround.

## Records and limits

Every record is an eight-byte little-endian word. Bits 0–51 retain the previous
scope signal layout: address 0–23, data 24–39, AS_N/UDS_N/LDS_N/RW/DTACK_N/BERR_N
40–45, FC 46–48, clock 49, RESET_N 50, and HALT_N 51. Bits 52–63 contain the
number of 20 ns ticks since the previous record.

The first record has delta zero and its absolute timestamp is `first_tick`.
Thereafter a record is emitted whenever any signal changes or the delta reaches
4095 (81.9 us). A change coinciding with expiration emits one record. Normal
termination emits the last observation if that tick is not already recorded.
The observation pipeline carries validity and acquisition timestamps with the
signals; timestamps do not describe FIFO insertion or PSRAM write time.

The 32,768-record asynchronous BRAM FIFO provides 256 KiB of buffering. PSRAM
holds 262,144 records in 2 MiB, with metadata kept separately in registers.
The FIFO uses bank-local write/read registers and a pipelined binary selection tree;
its variable read latency is hidden behind a valid handshake, not the CPU bus.
The write pointer crosses clock domains only after the staged BRAM write,
while capacity accounting includes the newly reserved slot immediately.
Queued and in-flight records count against that limit. Neither FIFO nor PSRAM
wraps over existing capture data. Capacity exhaustion or FIFO overflow stops
capture only, preserves the contiguous prefix, and reports the first missed
tick. `last_tick` is the last valid observation, inclusive. An empty capture
window is permitted and has zero records.

All signals, including clock-only transitions and inactive-bus data changes,
are retained. A 100 MHz quad SDR link has a raw ceiling of 50 MB/s; framing and
refresh gaps reduce this. The saved eight-read socket trace generates about
152 MB/s of change records. A finite FIFO cannot sustain that rate indefinitely.
Overflow is reported explicitly and is never treated as successful validation.

## PSRAM clock and transactions

DDR100 is the only supported implementation. A PLL supplies a 100 MHz engine
clock and Efinix's output DDIO primitive forwards the write clock. This produces
**100 MHz write SCLK and 50 MHz read SCLK**. Read clock pulses stay high for
10 ns and low for 10 ns. The unqualified SDR200 implementation has been removed
from RTL, simulation, pin assignment, and timing constraints. There is no
runtime fallback or automatic clock reduction. Build with
`bash fpga/m68000/build.sh`; obsolete non-DDR100 `PSRAM_PHY` settings are rejected.

The oscillator connects to A20 for the fabric clock and A18 for PLL_TR1's
external reference 0. The four PSRAM data pins retain their package assignments
and become bidirectional. Write data changes on SCLK falling edges; read data
is sampled at the following falling edge. The 20 ns read-return window covers
the PSRAM's specified 5.5 ns maximum output delay plus the FPGA's clock-output
and data-input pad delays.

Data, output enables, chip select, and SCLK share an output pipeline stage.
Dedicated input I/O registers sample after the 20 ns return window; a fabric
delivery stage then carries the nibble to the byte assembler. Matching strobe/index pipeline
stages preserve its association with the transaction. This pipeline is confined to the PSRAM interface; it does
not change CPU pins, buffer turnaround, or acquisition timestamps.

Initialization waits 200 us, issues reset, and reads the 64-bit manufacturer/
known-good-die identity using SPI `9Fh` at 25 MHz. A preceding dummy `9Fh`
satisfies the [APS1604M datasheet](https://www.mouser.com/datasheet/2/1127/APM_PSRAM_QSPI_APS1604M_3SQR_v2_7_PKG-1954896.pdf)
ID precondition. It then enters QPI and sets MR0 to
512-byte wrap. The SPI ID path avoids relying on the QPI MR/EID repetition
behavior: the first board diagnostic returned duplicated EID bits through that
path, despite the initial digital model passing it. Initialization still fails
closed on an invalid manufacturer/known-good-die prefix.
QPI `82h` writes use at most 128 bytes; `8Bh` reads use at most 64 bytes, never
crossing a 512-byte boundary. A host cache miss uses two read bursts to fill
the 128-byte cache. Write data is prefetched before CE asserts; no command waits for FIFO
data with CE held low. Read dummy cycles, chip-select hold time, and refresh
release gaps are explicit. Each command remains below the conservative 4 us
CE-low limit. The original template's SPI echo controller is unchanged.

Timing constraints include PSRAM setup/hold and output-delay limits with a
0.5 ns board-skew allowance. Efinity's physical clock-out reference accounts
for the internal clock tree; peripheral reports supply the SCLK clock-to-out,
data/enable output, and input-register setup/hold. Both reported PVT corners
are checked for outgoing data/CE. A separate external check covers the 20 ns
read-return interval; registered inputs then use the ordinary controller-cycle
constraint to reach the fabric. No blanket read multicycle hides input routing.
This is an engineering budget, not a measured
electrical qualification over voltage and temperature.

## Debug interface

The generic NDB1 transport and MCU firmware are unchanged. Existing CPU RAM,
transaction traces, and register addresses remain available. Scope ABI is 3 at
`0x30`; old live scope readers must reject it. Archived ABI-1/2 reports retain
their existing decoders.

| Address | Meaning |
|---|---|
| `0x2e` | Low 16 bits of accepted record count; use `0x64` for the full count |
| `0x30` | Scope ABI, 3 |
| `0x32` | 32-bit first requested capture tick, inclusive |
| `0x36` | Lane: 0 disabled, 1 model, 2 socket |
| `0x38` | PSRAM download bank, 0–31 |
| `0x3a` | 32-bit last requested capture tick, inclusive; default `0xffffffff` |
| `0x60` | Status flags, below |
| `0x62` | Reason in bits 3:0; initialized bit 4; DDR100 bit 5 |
| `0x64` / `0x68` | 32-bit accepted / committed record counts |
| `0x6c` / `0x70` | 32-bit first / last valid acquisition ticks |
| `0x74` / `0x78` | 32-bit first missed tick / FIFO high-water count |
| `0x7c` / `0x7e` | FIFO address bits (15) / sample period in ns (20) |
| `0x80` | Eight identity bytes, little-endian register order |
| `0x88` | Write 1 for idle-only destructive PSRAM self-test; read busy/done/error bits 0/1/2 |
| `0x8a` | 32-bit self-test failing byte address |
| `0x8e` | Diagnostic bits 0–5: initialized, drained, memory fault, PLL locked, qualified-lock seen, lock lost |
| `0x50000–0x5ffff` | Read-only 64 KiB window into the selected PSRAM bank |

Status bits 0–8 are capturing, draining, download-ready, overflow, capacity,
memory fault, self-test error, self-test complete, and self-test busy.
Reasons are 0 running, 1 complete, 2 overflow, 3 capacity, 4 aborted,
5 memory fault, 6 disabled, and 7 invalidated by the destructive memory test.
Download-ready alone is not proof of a complete
capture: inspect reason and accepted/committed counts too.

Configure only while idle. Starting a run rejects an uninitialized/faulted
enabled recorder or a selected lane absent from the run mode. Downloads are
rejected until draining finishes, and reads beyond committed data fail. The
self-test requires the socket to be disarmed; host hardware workflows also
require VCCB off. It writes all PSRAM before reading it back, invalidating any
previous waveform. Metadata should be read after completion, not as a live
multiword counter snapshot.
The identity registers retain a rejected PSRAM ID after a latched initialization
fault, so a failure can be diagnosed without enabling VCCB or retrying a capture.
Reports format this 64-bit value as conventional hexadecimal, starting with
`0d5d`; the debug register bytes themselves remain little-endian.

## Workflow and verification

Build with `bash fpga/m68000/build.sh`, or explicitly choose the fallback with
`bash fpga/m68000/build.sh`. The build gate checks source
provenance, fresh artifacts, clock constraints, every reported setup/hold
relationship, package pins, PSRAM directions, and memory utilization. A failed
build is not a qualified image.

After configuring a qualified image, use:

```sh
PYTHONPATH=host/src build/venv/bin/python -m validation.m68000.capture \
  --backend board --lane both --socket-fitted --self-test --program memory \
  --output build/validation/m68000/psram-memory-board.json
```

`--program reads` selects eight consecutive reads; `baseline` selects the
matching zero-read overhead program. `--start` and `--end` select the capture
window. The host downloads the model run before loading identical initial RAM
for the socket run, saves both compressed streams with hashes and metadata,
and preserves existing transaction-comparison rules. It powers down in cleanup.
The board's configured image must match the build receipt. Incomplete captures
remain in the report with their reason and cause a failing exit status.

Use `--backend sim --lane model` or `--backend spi-sim --lane model` for the same
record/download path in Verilator. `Capture.window(start, end)` expands only the
requested interval; `events()` yields timestamped changes without expansion.

`--program overflow --lane model` runs a finite 8,192-iteration loop twice,
first with capture disabled and then enabled. It requires identical CPU
results, a nonempty contiguous downloaded prefix, and explicit FIFO overflow.
On the board this test leaves VCCB off. Its report may set
`overflow_test_passed` even though the waveform is deliberately incomplete;
it never labels the truncated waveform a complete capture.

Run `bash fpga/m68000/test_scope.sh` for encoder edge cases and the DDR100 model,
including worst-case PSRAM output delay, FIFO wrap/overflow prefixes, and full
2 MiB write/read tests. Host tests are in `validation.m68000.test_scope`.
`bash fpga/m68000/test_qpi_requests.sh` checks zero-length, oversized, and
page-crossing requests, including same-cycle metadata changes.
It also checks the complete SPI identity and rejection of a bad known-good-die
code without retry. The memory model checks exact 100/50/25 MHz command clocks,
balanced pulses, refresh release, and the dummy-ID precondition. Host power-gate
failure tests are in `validation.m68000.test_capture`.
Existing lane, pin-safety, CPU, mailbox, and host tests remain required gates.

Simulation results are not hardware evidence. Hardware acceptance additionally
requires a qualified routed image, a VCCB-off 100 MHz-write/50 MHz-read memory self-test, separate
MC68000P12/fx68k captures, unchanged execution timing, overflow reporting, and
confirmed shutdown. Keep the actual receipts with the capture reports.

## Qualification result (2026-09-19)

The original physically tested image used the **DDR100 controller**, with
100 MHz quad writes, 50 MHz quad reads, and 25 MHz SPI identification. The
200 MHz controller was simulation-tested but never routed/hardware-qualified;
it has since been removed. Historical image SHA-256:

`c4e14c66f99236d5206d3afa2bc479833963674fcd02a75ef9370dd68b31c067`

All 153 package assignments and 16 setup/hold relationships pass. Setup slack
is +1.678 ns at 50 MHz, +0.723 ns for full-cycle PSRAM paths, and +0.413 ns for
the DDR half-cycle path; minimum hold slack is +0.086 ns. BRAM use is 929/1056.
The source manifest, timing margins, and complete reports are under
`build/fpga/m68000/`; the static build receipt does not claim electrical bench
qualification. The following capture receipts supply the separate bench evidence.

- `build/validation/m68000/psram-memory-board-spi-id.json`: full 2 MiB memory
  test passed with VCCB off; identity `0d5d1bdbd1cd7928`; complete independent
  model/socket captures of 229/305 records. Both CPUs produced `a55aa55a`.
  The model waveform matches Verilator byte-for-byte (SHA-256
  `928b04aec6407d2e608f135a301bdc074ef48271dda2b304f5059f29982c5785`).
  **The CPU trace comparison failed**, as described below; this is not a
  successful CPU differential-acceptance receipt.
- `build/validation/m68000/psram-overflow-board-build7.json`: VCCB remained
  off; memory test passed; deliberate overflow retained 47,536 complete
  records / 380,288 bytes. FIFO high-water was 32,768. The valid prefix ends
  at tick 179,894 and the first missed tick is 179,895. Every CPU result field
  matches the capture-disabled run. The overflow test passed, but its waveform
  is explicitly incomplete.
- Both workflows confirmed VCCB, 3.3 V, and 1.2 V off afterward. No failing-
  timing image was configured. The earlier PSRAM initialization failure and
  diagnostics remain in their original reports, not overwritten as successes.

At this historical checkpoint, recorder regressions passed in both PHY models, including exact clocks, full
memory, rejected identity, overflow, FIFO wrap, and PLL loss. There are also
33 passing harness/capture/timing tests and 16 passing generic host tests.

### Separate responder issue exposed by the new recorder

The failed physical comparison contains three socket records with a missing
UDS flag: instruction reads at `0x01000c` and `0x01000e`, and the MMIO write at
`0x100004`. The PSRAM waveform shows both strobes asserted well before ACK.
The existing responder records the byte mask on the first selected sample;
independent strobe propagation/synchronization can place the other byte on
the following sample. The comparator has not been weakened to hide this.

`bash fpga/m68000/test_lane_skew.sh` originally provided a failing reproducer independent
of PSRAM and fx68k: start RAM at `0x1122`, write `0xabcd`, and delay UDS by one
20 ns observation after LDS. Both strobes settle before ACK, but the old
responder writes only the low byte, leaving `0x11cd` and flags `0x29`.
This is a responder correctness issue, not merely a presentation mismatch.

### Responder sampling correction (2026-09-19)

The responder now samples both byte strobes and write data when its existing
delay expires, one system cycle before ACK. The first selected sample still
starts exactly the same timer and latches address, direction, and function code.
No CPU clocks, ACK scheduling, immediate direction controls, or continuous
read-drive logic changed. Genuine byte transfers are not promoted to words.

The expanded skew regression passes both strobe arrival orders, simultaneous
strobes, upper/lower byte accesses, late-settling write data, read masks, and a
TAS-style read/write pair that holds AS asserted. Every case checks the same
13-tick first-strobe-to-ACK latency with `wait_ticks=8`. Reset qualification and
pin-safety regressions also pass, along with 33 harness/capture/timing tests and
16 host tests. The original failed hardware report above remains unchanged.

The corrected DDR100 image passed the routed timing/pin gates and physical
comparisons. Image SHA-256:

`6f48a9947cd69800b09896dbc356da83ac8f5afe9ae9c4c3345dbe86f965e357`

Setup slack is +1.580 ns at 50 MHz, +0.426 ns for full-cycle PSRAM paths,
and +1.243 ns for the DDR half-cycle path; minimum hold slack is +0.086 ns.
All 153 package assignments and 16 setup/hold relationships pass. Quad writes
remain 100 MHz and readback remains 50 MHz. Physical receipts:

- `build/validation/m68000/psram-memory-board-strobe-fixed.json`: complete
  model/socket captures of 229/314 records, both operand results `a55aa55a`.
  Functional and relative transaction timing comparisons pass. The model
  waveform retains its previous byte-exact Verilator SHA-256
  `928b04aec6407d2e608f135a301bdc074ef48271dda2b304f5059f29982c5785`.
- `build/validation/m68000/psram-reads-board-strobe-fixed.json`: complete
  model/socket captures of 579/839 records, eight saved words `a550` through
  `a557` on both CPUs, and matching 16.2 us marker intervals. Operand starts
  are spaced 1.6 us apart on both CPUs.
- `build/validation/m68000/psram-baseline-board-strobe-fixed.json`: complete
  model/socket captures of 273/373 records and matching 3.4 us marker intervals.
  Subtraction gives 12.8 us / 64 CPU clocks for eight additional reads on
  both CPUs, unchanged from the previous immediate-direction measurements.

All three runs passed the full 2 MiB PSRAM self-test before VCCB enable,
passed the existing functional and relative transaction-timing comparator,
and confirmed all rails off in cleanup. Relative transaction timing excludes
the reset-exit offset; this does not assert identical raw pin waveforms or
eliminate real propagation delays. No comparison tolerances were changed.

`build/validation/m68000/psram-overflow-board-strobe-fixed.json` also passes:
VCCB stayed off, the full memory self-test passed, and deliberate overflow
preserved 47,536 records through tick 179,894, with first missed tick 179,895.
CPU results with capture enabled exactly match the capture-disabled baseline.
The waveform is explicitly incomplete, as intended for this overflow test.
A final independent status read confirmed VCCB, 3.3 V, and 1.2 V off.

The subsequent DDR100-only increasing-duration campaign and FIFO sizing
analysis are documented in [Capture stress test](m68000-capture-stress.md).
