# Do wider read strobes accumulate into slower execution?

**Build 5 follow-up:** removing the socket turnaround/ACK delay makes both
CPUs take 12.8 us / 64 clocks. See the [before/after hardware result](m68000-immediate-direction.md).
The build 4 measurements below are retained as historical evidence.

**Yes, in the build 4 harness.** Eight consecutive word-load instructions add
12.8 microseconds on fx68k and 16.0 microseconds on the MC68000P12: 64 versus
80 CPU clocks at 5 MHz. The physical sequence takes 25% longer. This result
repeated identically in three paired baseline/eight-read comparisons.

The experiment reused the same core build 4 image as the preceding single
read/write capture. No FPGA, MCU, bus responder, or pin-driver code was changed.
The known socket-only read-turnaround/ACK gate remains in place; this establishes
an execution-time difference in this setup, not an isolated fx68k defect.

## Program and measurement boundaries

The [assembly source](../validation/m68000/read_sequence.s) is assembled with
`READ_COUNT=0` or `READ_COUNT=8`. Its instruction words were independently
checked against the program bytes used by the runner.

```asm
        LEA     $0200.W,A0
        MOVE.W  #$1111,$0400.W   ; opening marker

        ; Omitted entirely in the zero-read baseline:
        MOVE.W  (A0)+,D0
        MOVE.W  (A0)+,D1
        MOVE.W  (A0)+,D2
        MOVE.W  (A0)+,D3
        MOVE.W  (A0)+,D4
        MOVE.W  (A0)+,D5
        MOVE.W  (A0)+,D6
        MOVE.W  (A0)+,D7

        MOVE.W  #$2222,$0402.W   ; closing marker
        MOVEM.W D0-D7,$0300.W    ; verify values AFTER the timed region
        MOVE.L  #1,$00100004    ; harness completion
```

There are no branches or stores between the eight loads. Source words at
`$0200..$020e` are `$A550..$A557`; all eight saved register words must match.
The zero-read baseline also omits the post-marker MOVEM. It leaves the result
buffer's `$BBBB` sentinel words unchanged.

Time is measured from **completion of the opening marker write to completion
of the closing marker write**, using the complete FPGA timestamped bus trace.
Subtracting the zero-read result removes the common marker/setup overhead.
Reset duration and the two CPUs' reset-exit offsets are outside this window.
USB latency and host wall-clock time are not used.

## Measured results

| Measurement | On-board fx68k | Physical MC68000P12 |
| --- | --- | --- |
| Zero-read marker window | 3.4 us | 4.0 us |
| Eight-read marker window | 16.2 us | 20.0 us |
| **Increment from adding eight loads** | **12.8 us / 64 clocks** | **16.0 us / 80 clocks** |
| Start-to-start cadence of successive operands | 1.6 us / 8 clocks | 2.0 us / 10 clocks |
| Operand read active duration | 500 ns | 700 ns |
| First operand start to eighth operand end | 11.7 us | 14.7 us |

All seven inter-operand start intervals have the same value in each lane.
The last row is a different observation window, not the total cost of eight
instructions: it excludes the front/back instruction and prefetch portions.

### The delay is not compensated by shorter gaps

Compared with the zero-read baseline, the eight-load program adds exactly:

- eight ordinary data-word reads (FC=5);
- eight instruction-word fetches (FC=6);
- no additional writes inside the marker window.

Both classes of read remain active for 500 ns on fx68k versus 700 ns on the
socket. The accounting closes exactly:

| Baseline-subtracted component | fx68k | MC68000P12 |
| --- | --- | --- |
| 16 additional active read transfers | 8.0 us | 11.2 us |
| Additional gaps between transfers | 4.8 us | 4.8 us |
| Total | 12.8 us | 16.0 us |

Thus `16 × 200 ns = 3.2 us` explains the complete extra execution time.
The wider transfers are not just a pulse-shape difference absorbed by idle
time. Each added MOVE needs one additional operand read and one additional
instruction fetch, so the extra cost is 400 ns per MOVE in this sequence.

These active intervals are the responder-observed selected-transfer windows,
not new oscilloscope measurements of CPU pins. The earlier sampled-signal
experiment established the corresponding word-read UDS/LDS widths. A 512-sample
scope window is retained in each report as supplementary evidence, but it does
not cover the whole sequence; all elapsed-time accounting uses the complete
transaction traces.

## Verification and provenance

Three baseline runs and three eight-read runs all passed on both lanes. The
baseline has 22 total transfers and the eight-read program has 49; all 213
transfers per lane match functionally across the six runs. All eight loaded
register words match in every eight-read run. Within each program, all marker
times, operand times, fetch times, and gap values repeat identically.

Raw receipt: `build/validation/m68000/read-sequence-board-2026-09-18.json`.
SHA-256: `d5bb897dfa831a5080369724e07cda9e87c45c6c9f9354b603244186dd6fcdcb`.
It contains both program images, all six complete paired traces, the measured
components, supplementary scope samples, build/source provenance, and final
power state. No transport or cleanup error occurred. VCCB, 3.3 V, and 1.2 V
were confirmed off by the runner and by a separate final status read.

Core build 4 image SHA-256:
`5e873de44af720f0c3dd790bf394f6124403eb93ba53b334c903c0abe67bbe1c`.
Clock divider=5, wait_ticks=8, exclusive 5 V selection. Two new measurement
regressions pass, covering program results, timing accounting, corrupt read
data, missing markers, and inconsistent repetitions.

## Reproduce

```sh
PYTHONPATH=host/src:. python3 -m unittest validation.m68000.test_read_sequence
PYTHONPATH=host/src:. python3 -m validation.m68000.read_sequence \
  --output build/validation/m68000/read-sequence-sim.json
nuboard configure build/fpga/m68000/outflow/m68000.hex.bin
PYTHONPATH=host/src:. python3 -m validation.m68000.read_sequence \
  --backend board --socket-fitted --repeats 3 \
  --output build/validation/m68000/read-sequence-board.json
```

The fitted MC68000P12 and exclusive 5 V selector are required. Completion uses
the mailbox interrupt path. The runner stops on a functional or measurement
failure, preserves its receipt, and shuts down the board without automatic
retry. The three comparisons are planned repetitions, not failure retries.
