# BRAM-only waveform capture (build 8, scope ABI 4)

The former 256 KiB FIFO allocation is now the entire capture buffer:
**32,768 eight-byte records**, stored directly in block RAM at 50 MHz.
There is no PSRAM initialization, streaming, drain engine, memory PLL, or
asynchronous capture-memory domain. External PSRAM CE stays high, SCLK low,
and all four data pads are undriven. The separate FPGA template is unchanged.

Acquisition still observes one selected CPU every 20 ns. Each record retains
the previous format: 52 signal bits and a 12-bit elapsed-tick count. Changes,
4095-tick expiry, and the final observation are recorded. The first record
has delta zero. The signal layout is address 0–23, data 24–39,
AS_N/UDS_N/LDS_N/RW/DTACK_N/BERR_N 40–45, FC 46–48, clock 49,
RESET_N 50, and HALT_N 51.

The buffer is append-only, not circular. When a required record will not fit,
recording stops with reason `capacity`; the CPU keeps running without altered
clocks, ACK scheduling, or buffer direction. The existing prefix is preserved,
and `missed_tick` identifies the first unrecorded observation. Exactly filling
the buffer at normal termination remains a complete capture if no further
record is needed. A new run clears metadata, not RAM; stale tail reads are
rejected. Reads are non-destructive and allowed only after the CPU run and
the final BRAM write have finished.

## Debug registers

The generic MCU/USB protocol is unchanged. The FPGA identity is build 8 and
scope ABI is 4; the live host refuses the previous ABI rather than silently
interpreting old PSRAM metadata.

| Address | Meaning |
|---|---|
| `0x30` | Scope ABI = 4 |
| `0x32/34` | First sample tick, 32-bit little-endian |
| `0x36` | 0 disabled, 1 FPGA model, 2 socket CPU |
| `0x38` | Readback bank 0–3 (64 KiB each) |
| `0x3a/3c` | Last sample tick, inclusive |
| `0x60` | Bit 0 recording, bit 1 final write pending, bit 2 stopped/committed, bit 4 capacity reached |
| `0x62` | Reason in bits 3:0, ready bit 4; no external PHY bit |
| `0x64/66` | Accepted records |
| `0x68/6a` | Stored records; read after stopped/committed |
| `0x6c/6e` | First tick |
| `0x70/72` | Last valid tick, inclusive |
| `0x74/76` | First missed tick when capacity is reached |
| `0x78/7a` | Buffer usage in records (equals accepted; nothing drains) |
| `0x7c` | Address bits = 15 |
| `0x7e` | Sample period = 20 ns |
| `0x50000..0x5ffff` | Read-only selected 64 KiB bank |

PSRAM identity, diagnostic, and destructive memory-test registers at `0x80`
and above are removed and reject access. Out-of-range banks, reads beyond
the stored prefix, and writes to capture memory are rejected. Configuration
cannot change during capture or CPU execution.

## Build and use

```sh
bash fpga/m68000/build.sh
PYTHONPATH=host/src build/venv/bin/python -m nuboard.cli --json configure \
  build/fpga/m68000/outflow/m68000.hex.bin
PYTHONPATH=host/src build/venv/bin/python -m validation.m68000.capture \
  --backend board --lane both --socket-fitted --program memory \
  --output build/validation/m68000/capture-bram-board.json
```

The board workflow requires the receipt-matched build, VCCB off initially,
and exclusive 5 V selection before arming the fitted MC68000P12. It powers
down all rails in cleanup. Do not pass the removed `--self-test` option or
`PSRAM_PHY` build setting. Use `--program capacity --lane model` for a finite
long run that checks unchanged CPU execution after the buffer fills.

For increasing-duration testing, configure again and run:

```sh
PYTHONPATH=host/src build/venv/bin/python -m validation.m68000.stress \
  --backend board --lane both --socket-fitted \
  --counts 64 256 512 768 1024 2048 8192 \
  --output build/validation/m68000/stress-bram-board.json
```

Each trial compares recording disabled/enabled, final CPU results, exact
elapsed ticks, bus counts/signatures, and every captured clock transition.
Capacity-limited waveforms remain explicitly incomplete in the report.
`--backend sim --lane model` uses the same BRAM path in Verilator; a completed
simulation stress report can be supplied with `--reference` to check model
waveform bytes during the physical campaign.

This deliberately trades the previous roughly 42–48 thousand retained records
for a fixed 32,768-record capacity and a simpler, deterministic storage path.
The previous [PSRAM implementation](m68000-psram-capture.md) and
[bandwidth measurements](m68000-capture-stress.md) remain historical evidence.

## Qualification, 2026-09-19

Image SHA-256:
`4a04355e0b5461148399dd13fcd6b39ea6a3f260f8834a6d434ba8cf3cf7c860`.
All 153 package assignments and 12 setup/hold relationships pass. The 50 MHz
setup margin is +1.108 ns and minimum hold margin is +0.116 ns. BRAM usage is
923/1056 blocks. The timing report contains only the acquisition and existing
SPI clocks, with no PSRAM clock domain.

Receipts and tests:

- `build/validation/m68000/capture-bram-board.json`: both CPUs pass the memory
  MOVE comparison, including relative transaction timing. Each produced
  `a55aa55a`; the model's 229-record waveform retains SHA-256
  `928b04aec6407d2e608f135a301bdc074ef48271dda2b304f5059f29982c5785`.
- `build/validation/m68000/stress-bram-board.json`: all 28 trials pass over
  64–8192 loop iterations, on both CPUs separately. Twelve waveforms are
  complete; sixteen preserve a 32,768-record prefix and explicitly report
  capacity reached. CPU execution, elapsed ticks, counts/signatures, and final
  stores match capture-disabled baselines in every trial. All retained CPU
  clock transitions are present at 100 ns intervals.
- `build/validation/m68000/stress-bram-sim.json`: all 14 simulated trials pass.
  Every board model capture is compared byte-for-byte against this reference
  during the physical test. These simulation records also match the same
  prefixes of the historical PSRAM simulation captures.
- `build/validation/m68000/capacity-bram-spi-sim.json`: full-capacity download
  also passes through the simulated SPI mailbox, with unchanged CPU execution.
- `build/fpga/m68000/scope-bram.log`: full-rate writes across all banks, delta
  expiry, terminal samples, exact-capacity completion, capacity truncation,
  non-destructive reads, stale-tail rejection, live-read rejection, and invalid
  writes/settings pass. Pin tests confirm PSRAM deselection/clock-low defaults
  and unchanged immediate direction, continuous read drive, and ACK forwarding.
- `build/fpga/m68000/tests-bram.log`: 35 Python harness/capture/stress/timing
  gates pass; the separate 16 generic host tests pass as well.

Observed full-buffer durations were 2.480 ms (FPGA/NOP), 2.444 ms (FPGA/read),
approximately 1.963 ms (MC68000/NOP), and 1.866 ms (MC68000/read). These are
workload-specific observations, not a guaranteed time window: record capacity
is fixed but the number of signal changes varies.

The initial build's source gate caught Efinity removing the project XML's final
newline. Restoring the exact snapshotted bytes allowed the independent timing,
pin, and source gates to pass; see `build8-bram-gates.log` and `receipt.json`.
Future build snapshots normalize that formatting before hashing. No timing
exception was added and no unqualified image was loaded.

All board workflows confirmed VCCB and both FPGA rails off in cleanup.
