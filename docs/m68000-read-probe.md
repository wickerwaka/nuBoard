# DTACK and read-data sampling experiment

Build 13 adds an opt-in override for reads at CPU word address `0x000200`.
It does not modify fx68k, MCU firmware, CPU frequency, buffer direction/OE,
ordinary memory, or reset-vector responses. The probe defaults off.

Each selected CPU executes a small program that reads the target and writes
the observed value into RAM at `$220`, then completes through the existing
pass marker. A separate instruction-fetch variant jumps to `$200`, where
the two possible data words encode `MOVEQ #$11,D0` and `MOVEQ #$22,D0`.
That program also stores D0 at `$220`.

## Stimulus

The normal responder is bypassed for only the selected target read's data and
DTACK outputs. Data starts at a programmable old word and changes once to a
programmable new word. DTACK asserts independently and stays asserted through
the read. The normal backing-RAM transaction log does **not** describe this
override; the CPU-written result and passive pin capture are authoritative.

Each CPU's target selection passes through identical two-stage synchronization.
Tick zero is the next rising CPU clock edge after synchronized selection.
One tick is 20 ns; a CPU clock is ten ticks (5 MHz). Relative clock phase and
actual transition times must be verified from each capture, not assumed from
the asynchronous AS assertion. ACK=64 is a separate early-ACK mode: DTACK
asserts directly from target AS assertion, before the phase scheduler starts.

| Debug register | Meaning |
| --- | --- |
| `$90` | Enable, 0/1; default 0 |
| `$92` | DTACK delay, 0–63 ticks; 64 selects early ACK |
| `$94` | Data-change delay, 0–63 ticks |
| `$96` | Old word; default `$5aa5` |
| `$98` | New word; default `$a55a` |

Configuration writes require the harness to be idle. Delay registers and both
data patterns are shared by the two independently run CPUs. No simultaneous
capture or clock stretching is involved.

## Reproduction

Build and configure the receipt-matched FPGA using the normal build flow.
The board runner requires VCCB initially off, the MC68000 daughterboard fitted,
exclusive 5 V selection, and the existing 5 MHz/eight-tick normal responder.
It holds reset for 120 ms after power-up and verifies all rails off on exit.

```sh
PYTHONPATH=host/src build/venv/bin/python -m validation.m68000.read_probe \
  --target board --ack 0 4 5 14 15 64 --data 0 13 14 15 24 25 34 35 \
  --repeats 5 --output build/validation/m68000/read-probe/new-run.json
```

Use `--target sim` or `--target spi-sim` without hardware. Use `--width high`
or `--width low` for byte reads, and `--width fetch --old 0x7011 --new 0x7022`
for the instruction-fetch experiment. Fresh output paths preserve evidence.
Every point retains the raw captures, traces, CPU-observed value, and decoded
transition timestamps. Differences are experimental results, not automatic
campaign-abort conditions; acquisition failures still abort and power off.

## Interpretation

Separate early DTACK recognition (which changes wait-state count) from early
data latching in an otherwise identical bus cycle. Changes on the sampling
edge may violate physical setup time. FPGA-level digital capture at 20 ns
resolution cannot establish nanosecond setup margins at the CPU package.

The [NXP/Motorola manual](https://www.nxp.com/docs/en/reference-manual/MC68000UM.pdf)
describes asynchronous read sequencing in section 5.1.1 and electrical timing
in section 10.10. Data is captured on the falling edge ending S6; DTACK setup
and read-data setup are separate requirements. The section 10.10 note 5 allows
the DTACK-to-data requirement to be replaced by the appropriate clock-relative
data setup when DTACK meets its asynchronous setup specification.

## Results: 2026-09-19

**No reproducible early-data-latch defect was found with matched stimulus and
data changed away from the sampling edge, at this experiment's 20 ns resolution.**
This is not a proof about sub-20-ns apertures or every type of asynchronous input.

| Experiment | Paired trials | Different observed values |
| --- | ---: | ---: |
| Independent DTACK/data word sweep (build 12) | 350 | 0 |
| Early DTACK word reads (build 13) | 65 | 2 |
| Controlled instruction fetch (`MOVEQ`) | 216 | 0 |
| Upper-byte reads | 90 | 0 |
| Lower-byte reads | 90 | 3 |
| Reversed word patterns | 240 | 30 |
| Later wait-state data boundaries | 45 | 9 |
| Total | 1096 | 44 |

All 1096 board fx68k results match their corresponding Verilator result.
All 618 data changes before the model's sampling edge and all 385 after it
gave the expected value on both CPUs. There were 93 changes scheduled exactly
on that edge; all 44 differences belong to this group. Both old/new controls
are necessary: the CPU-written result is not merely always reading backing RAM.

An especially repeatable difference uses `$a55a -> $5aa5`:

| Change relative to the reference falling sampling edge | fx68k | MC68000P12 |
| --- | --- | --- |
| -20 ns | `$5aa5` (new) | `$5aa5` (new) |
| 0 ns | `$a55a` (old) | `$a5df` (mixed) |
| +20 ns | `$a55a` (old) | `$a55a` (old) |

The zero-offset mixed value reproduced in all ten repetitions for each of
ACK=0, ACK=5, and early ACK=64. For the opposite data transition, some
on-edge samples were `$5abd` or `$5aad` instead of `$5aa5`. These are neither
the complete old word nor the complete new word. This is consistent with
per-bit skew in the real CPU's setup/hold aperture. It does not demonstrate
that a correctly set-up new word is rejected by fx68k. The scope timestamps
reference FPGA-level signals, not analog waveforms at the CPU package.

### Separate DTACK timing failure with the probe disabled

A normal directed regression stopped on `move.w.indirect.read`, after `nop`
and `moveq` passed. Defined and full chip-compatible architectural state
matched, but the marked interval lasted 248 real CPU clocks versus 247 model
clocks. **This strict timing failure is retained, not waived.** Seven remaining
requested regression cases were not run after the stop.

The first differing transfer was a program-space read at `$010076`, not the
probe address. Its sampled waveform shows unequal DTACK stimulus:

| Relative to the relevant falling clock edge | fx68k | Physical MC68000 |
| --- | ---: | ---: |
| Data becomes valid | -60 ns | -20 ns |
| DTACK asserts | -40 ns | 0 ns |
| AS negates | +200 ns | +420 ns |

The physical CPU takes one extra 200 ns wait clock, plus the observed 20 ns
AS propagation delay. The normal AS/strobe-triggered responder recognizes
the physical transfer later; unlike the diagnostic override, it does not
lock its response to the same clock phase. This is an explanation for an
apparent early-acceptance comparison without a matched input waveform.
No change to the normal ACK scheduler or fx68k has been made to hide it.
Build 13 is therefore an experimental diagnostic build, not a newly certified
replacement for the prior full directed-suite qualification.

### Evidence and verification

- All reports and raw waveforms: `build/validation/m68000/read-probe/`.
- Aggregated counts, hashes, and all differences: `summary.json` in that directory.
- Repeatable mixed-data case: `board-reverse/a00-d15-r00.json`.
- Adjacent controls: `board-reverse/a00-d14-r00.json` and `a00-d16-r00.json`.
- Disabled-probe failure: `disabled-regressions/cases/move.w.indirect.read.json`.
- Recompute the summary with `build/validation/m68000/read-probe/summarize.py`.

Both FPGA builds passed internal routed timing and all 153 package-pin checks.
Build 12 passed 63 validation tests and the continuous-drive pin test; build 13
passed 64 validation tests, including early ACK and instruction-fetch controls.
The final physical report verifies VCCB, 3.3 V, and 1.2 V off.
