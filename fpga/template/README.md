# nuBoard FPGA template

This is the runtime companion for the streamed MCU firmware. It retains safe
DUT and buffer defaults, drives the 10 Hz configuration heartbeat on CSO, and
reuses CDI0..3 as a 10 MHz SPI mode-0 mailbox. NSTATUS becomes an active-low,
level-held interrupt in user mode.

The template provides one 4096-byte slot in each direction. A packet occupies
16 header bytes plus at most 4080 payload bytes. `READ_PACKET` is
non-destructive; the interrupt remains asserted until a matching `ACK_PACKET`.
The included `nuboard_app` echoes every packet back unchanged, except on
channel 1, which carries HyperRAM test commands. The echo exercises the
mailbox, both slots, backpressure, and the CRC and ACK handling.

Pin assignments in `template.isf` follow `hardware/main-board/fpga_pin_map.csv`,
including all four sideband lines on each socket (`tx[3:0]`, `bx[3:0]`,
`lx[3:0]`, `rx[3:0]`, which are `F_TX0`..`F_TX3` and so on). Revision 2 has
no PSRAM.

## HyperRAM trace buffer

The HyperRAM (U2, ISSI IS66WVH8M8BLL, 8 MB) holds trace output captured
during a test, so the controller is built for sustained throughput:

- Every transfer is one fixed-length, burst-aligned burst. `build.sh` sets the
  length per build to the largest power of two, up to one 512-word row, that
  keeps CS# low for less than tCSM (4 us): 128 words at 50 MHz, 256 at
  75-125 MHz, 512 at 150 MHz.
- Data is staged through four buffers. A producer fills a buffer and queues
  "write buffer b to burst A"; a read queues "read burst A into buffer b".
  Each command completes through a done queue. Queued commands run back to
  back with 8 clocks of CS# high between bursts.
- The producer side has its own clock and a configurable width (16, 32, 64
  or 128 bits). The buffers' dual-clock RAMs and the queues' async FIFOs do
  the clock crossing.

Measured on hardware, full 8 MB, every pattern clean:

| HyperRAM clock | Burst | Write    | Read     |
|----------------|-------|----------|----------|
| 100 MHz, 90    | 256   | 182 MB/s | 180 MB/s |
| 150 MHz, 45    | 512   | 284 MB/s | 283 MB/s |

The raw bus rate is 2 bytes per clock, so this is 91% and 95% efficient.

The HyperRAM runs from its own PLL, PLL_TR1, fed by the 50 MHz oscillator on
A18, so its clock is independent of the 50 MHz core. The PLL makes three
clocks at the HyperRAM frequency:

| Clock        | Phase      | Drives |
|--------------|------------|--------|
| `clk_hr`     | 0          | DQ and RWDS outputs, controller |
| `clk_hr90`   | 90         | CK, centred in each DQ half-cycle |
| `clk_hr_cal` | build-time | DQ and RWDS input capture |

Every HyperBus pin is an `EFX_GPIO_V2` DDIO block. Trion PLLs cannot change
frequency or phase at run time, so each frequency and capture phase is a
separate image. The read path finds words from the RWDS strobe pattern
rather than assuming a CK-to-data delay, so any capture phase that keeps
clear of the data edges works. On this board the round trip is about 7.5 ns;
good phases are 90 or 270 degrees at 100 MHz and 45 degrees at 150 MHz.

| File                    | Role |
|-------------------------|------|
| `hyperram_phy.v`        | I/O cells and CK generation |
| `hyperram_fifo.v`       | Small async FIFO (capture path and queues) |
| `hyperram_ctrl.v`       | Fixed-burst HyperBus engine, read capture, reset and ID read |
| `hyperram_buffers.v`    | Staging buffers: dual-clock RAM lanes |
| `hyperram_trace_core.v` | Controller, buffers and queues: the producer-facing interface |
| `hyperram_tester.v`     | Test harness, written as a producer would use the core |
| `nuboard_app.v`         | Mailbox application: channel 1 commands, echo |

The controller uses the device's power-up configuration: fixed 2x latency of
6 clocks, so data starts 11 clocks after the command-address.

In this template the harness is the producer, on `clk_50mhz` with 64-bit
words (400 MB/s, more than the HyperRAM takes). From the host:

```sh
nuboard hyperram id                          # configuration, ID registers
nuboard hyperram test                        # write then check all 8 MB (PRBS)
nuboard hyperram write --seed 5              # write only
nuboard hyperram read --seed 5               # check what is there
nuboard hyperram test --pattern walking --start-burst 100 --bursts 16
```

Patterns are `prbs`, `address`, `walking` and `toggle`. Results include write
and read throughput, the error and missing-word counts, the first failing
word, and an OR of all failing bits, which separates a single bad DQ line
from a framing problem.

### Frequency sweep

```sh
make -C fpga -j2 hyperram-sweep              # 50-150 MHz x 6 phases = 30 images
build/host-venv/bin/python tools/hyperram-sweep.py
```

`HR_MHZ=<n> HR_CAL_PHASE=<deg> ./fpga/template/build.sh` builds one
configuration into `build/fpga/template-hr<n>-p<deg>/`. Each build writes
`timing-summary.txt`, and the sweep marks images that missed fabric timing.
The controller closes timing at 150 MHz on the T120 C3, so the sweep stops
there.

The application connects to the mailbox through byte-wide input and output
streams with `valid`, `ready`, and `last` signals. Replace it with a
core-specific application while retaining the mailbox and slot logic.

Run the behavioral test with:

```sh
./fpga/template/test.sh
```

Route a passive-x4 image (100 MHz HyperRAM, 90 degree capture) with Efinity
2026.1 using:

```sh
./fpga/template/build.sh
```
