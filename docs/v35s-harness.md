# V35S differential harness

The harness runs one reset-executable program on the socketed NEC µPD70337L-8
(V35 "Software Guard", marked V35S) and on a model core in the FPGA. Each CPU
gets its own memory image and bus trace. It follows the method of the
[68000 harness](m68000-harness.md):

- Directed programs are written in NEC syntax.
- Both lanes answer through identical responders.
- Traces are compared functionally (address, data, flags) and for timing,
  separately.
- A change-encoded scope captures every pin at 30 ns.

Measured bus timing is in [`v35s-bus-timing.md`](v35s-bus-timing.md).

## Clock

From build 2 the whole FPGA design runs on one 33.33 MHz clock from PLL_TR1,
referenced to the 50 MHz oscillator on A18. One tick is 30 ns.

- **Why 33.33 MHz:** the PLL output is 50 × M / N, and the phase detector
  needs 50 / N ≥ 10 MHz. So 32 MHz is unreachable, and 33.33 MHz (M = 2,
  N = 3) is the nearest.
- **X1:** X1 is 16.67 MHz / n with n ≥ 2, so 8.33 MHz is both the default and
  the maximum.
- **Earlier receipts:** build 1 ran at 50 MHz with 20 ns ticks. The
  2026-10-12 characterization receipt was taken on build 1.
- **Lane read latency:** about 5 ticks (150 ns). At 8.33 MHz X1 and fX/2, a
  bus state is 8 ticks, so a zero-wait read has about 3 ticks of margin.

## The part

The daughterboard (`hardware/v35s/`) carries a µPD70337 in a PLCC-84 socket,
not a µPD70335 (V35 Plus). The µPD70337 is a V35 with:

- a separate 16-bit data bus;
- a DRAM-style multiplexed 20-bit address;
- /MREQ, /MSTB, /IOSTB, R//W and /REFRQ strobes;
- internal RAM, SFRs and register banks;
- BRKS/BRKN security mode.

N//S is held high, so the CPU runs in normal (unencrypted) mode.

References:
- **Data books and pinout:** `hardware/v35s/datasheets/`, mapped by page in
  `hardware/v35s/design-notes.md`.
- **Pin and bank wiring:** `hardware/v35s/pin-map.csv` and
  `hardware/v35s/bank-modes.md`.

## Layout

| Path | Role |
| --- | --- |
| `fpga/v35s/nuboard_v35s.v` | Rev-2 board top: bank permutation, DIR/OE control, X1/X2 on RCLK/TCLK, DUT power |
| `fpga/v35s/v35s_harness.sv` | Control registers, X1 divider, reset and run state machine, scope tap, two lanes |
| `fpga/v35s/v35s_lane.sv` | Responder for the V35 bus: row/column latch, 64 KiB paged RAM, trace, markers |
| `fpga/v35s/nuboard_mailbox.v` | Mailbox with the V35S identity |
| `fpga/v35s/core/v35s_model.sv` | Model lane: the forked nuV30 ucore behind a V35 bus shell |
| `fpga/v35s/core/ucore/` | Fork of nuV30's ucore, GPL-2.0; every change is listed in `PROVENANCE.md` |
| `fpga/v35s/v35s_model_stub.sv` | Idle model, for socket-only images |
| `fpga/v35s/v35s_lane_tb.sv` | Scripted-bus regression of the lane and harness |
| `fpga/v35s/build.sh`, `build_sim.sh` | Efinity image; Verilator `direct`, `spi` and `dual` builds |
| `validation/v35s/runner.py` | `Harness`, `Transaction`, `compare_traces`, board/sim entry point |
| `validation/v35s/asm.py` | NEC-syntax assembly through nuV30's `sw/v30asm.py` |
| `validation/v35s/scope.py` | V35S signal layout for the shared ABI-4 scope |
| `validation/v35s/capture.py` | One program with the scope armed; prints a text waveform |
| `validation/v35s/characterize.py` | PRC/WTC/RFM sweep with per-cycle edge timing |
| `validation/v35s/programs/` | Directed programs |
| `tools/fetch_v35s.py` | Pinned nuV30 checkout (assembler and fork base) |

These modules are shared with the 68000 harness and used in place:

- `fpga/m68000/nuboard_debug_bridge.sv`
- `scope_encoder.sv`
- `m68000_scope.sv`

## Building

```sh
python3 tools/fetch_v35s.py           # nuV30 at the pinned commit
fpga/v35s/build.sh                    # socket-only image
V35S_MODEL=1 fpga/v35s/build.sh       # image with the model lane
fpga/v35s/build_sim.sh direct         # Verilator, harness + model
fpga/v35s/build_sim.sh dual           # Verilator, model in both lanes
```

The image lands in `build/fpga/v35s/outflow/v35s.hex.bin`. `build.sh` fails if
timing is not met. The runner configures the board itself when the V35S image
is not loaded, because `power_off` at the end of every run also removes FPGA
power.

## Running

```sh
# Socket only, on the board
PYTHONPATH=host/src:. python -m validation.v35s.runner --socket-fitted \
    --print-trace validation/v35s/programs/smoke.s

# Model only, in Verilator
PYTHONPATH=host/src:. python -m validation.v35s.runner --backend sim --mode model \
    validation/v35s/programs/smoke.s

# Differential runner regression: two model cores
PYTHONPATH=host/src:. python -m validation.v35s.runner --backend dual-sim --mode both \
    validation/v35s/programs/*.s

# Socket against model on the board (image built with V35S_MODEL=1)
PYTHONPATH=host/src:. python -m validation.v35s.runner --socket-fitted --mode both \
    --program-only validation/v35s/programs/*.s

# Scope capture and timing sweep (board)
PYTHONPATH=host/src:. python -m validation.v35s.capture --socket-fitted validation/v35s/programs/clocks.s
PYTHONPATH=host/src:. python -m validation.v35s.characterize --socket-fitted
```

Program layout:

- A program is assembled at 0x00100. The image builder puts `JMP FAR
  0000:0100` at the reset vector FFFF0.
- `OUT` to I/O port FF00h passes and FF02h fails.
- The CPU's general registers are undefined at reset, so a program must
  initialize everything it writes.

A differential run reports three comparisons:

- **trace:** the whole bus trace, cycle by cycle, functionally and for timing.
- **writes:** the ordered writes and I/O cycles only. The V35 bus has no
  fetch status, so this is the part of a trace that a different prefetch
  policy cannot change.
- **results:** the result region at 0x00400–0x004FF in both lane memories.

By default a run passes only on identical traces. `--program-only` passes on
identical writes, which is the right gate while the model's prefetch policy
is still V30's.

## Safety

These conditions guard the CPU and the translators:

- **Supply and core checks:** the runner refuses to power the socket unless
  the 5 V selector is set, the V35S core identity is loaded, and VCCB starts
  off.
- **Power sequence:**
  1. Arming switches DUT power (`dut_isolate` low).
  2. The translators and X1/X2 stay disabled for 1 ms while the supply settles.
  3. /RESET is held for at least 30 ms after arming.
  4. Later runs reset for `reset_ticks` (at least 5 µs).
- **Banks that only receive:** L2, B0 and T1 (address and strobes) are FPGA
  inputs with no output driver.
- **Banks that only drive:** B1, B2 and R1 (resets, requests, comparator
  inputs) always drive toward the CPU at the levels in `bank-modes.md`.
- **Data banks (L0/L1):** they drive toward the CPU only while the lane is
  answering a read strobe and R//W is high.
- **Port banks (T2, R2, R0, T0):** they start host-driven, because those
  ports are inputs at reset. Internal SFR writes never reach the bus, so a
  program announces each change with an `OUT` to marker port FF10h, whose
  data is the new bank-mode byte. It releases a bank (Z) before switching the
  port to output, then claims it (D). See `programs/clocks.s`.
- **Lint:** `v35s_lane_tb.sv` fails if data is ever driven during a write or a
  refresh.

## Debug register map

All registers are 16-bit at word addresses.

| Address | Register |
| --- | --- |
| 00 | ID 7033h |
| 02 | version 1 |
| 04 | control: bit 0 arm, bit 1 start, bit 2 abort, bits 9:8 lanes (1 model, 2 socket, 3 both) |
| 06 | status: 0 busy, 1 complete, 3:2 model result, 5:4 socket result, 6 overflow, 7 timeout, 8 cold-reset wait |
| 08 | X1 half period in 30 ns ticks (2–255; X1 = 16.67 MHz / n) |
| 0A | READY hold in ticks after the column strobe (0 = ready) |
| 0C/0E, 10/12 | run limit, run ticks |
| 14/16 | model / socket trace record counts |
| 18 | live socket pins |
| 1A–28 | totals and CRC fingerprints |
| 2A/2C | capture start (transaction index) |
| 2E–3C, 60–7E, 0x5xxxx | scope (ABI 4, shared with the 68000 harness); 7E reports the tick in 10 ps (3000) |
| 40–5E | page map: 16 × {valid, A19..A12} |
| 84/86 | reset hold ticks |
| 88 | bank modes at start: two bits each for T2, R2, R0, T0 (0 host drives, 1 off, 2 CPU drives) |
| 8A | live bank modes |
| 8C | P0 levels while T2 is host-driven |
| 8E | input levels: N//S, NMI, /INTP0–2, INT, DMARQ0/1, HLDRQ, RxD0/1, /CTS0/1 |
| 90/92 | marker counts, last socket marker |
| 94/96 | ticks since arming |
| 98/9A | live P0, R2 and P2 outputs |
| 0x1xxxx | model RAM (host writes go to both lanes) |
| 0x2xxxx | socket RAM |
| 0x3xxxx / 0x4xxxx | model / socket trace |

Trace record (8 words):

| Words | Field |
| --- | --- |
| 0–1 | start tick |
| 2 | A15–A0 |
| 3 | {flags[11:0], A19–A16} |
| 4 | data, masked to the active byte lanes |
| 5 | ticks from cycle start to the strobe |
| 6–7 | end tick |

Flags:

| Bit | Meaning |
| --- | --- |
| 0 | read |
| 1 | I/O |
| 2 | refresh |
| 3 | /UBE |
| 4 | unmapped |
| 5 | marker port |
| 6 | A17/A9 pin in the column phase |
| 7 | strobe seen |

## Status

**Working on silicon:**

- Socket runs, scope capture, and the bank handoff to bring CLKOUT out on P07.
- Reset-default and fX/2 timing at 0, 1 and 2 waits, with and without
  refresh.

**First core:**

- **What runs:** the forked nuV30 ucore with a V35 bus shell. It boots from
  FFFF0 and passes `smoke`, `clocks` and `alu` in Verilator and on the FPGA.
- **On the board, socket against model (`--mode both --program-only`):** the
  write and I/O sequence and the result region match silicon on all three
  programs. The bus traces differ in prefetch and timing (21 versus 16 cycles
  on `smoke`; 368 versus 360 on `alu`).
- **Model image:** 22% of the logic and 938 of 1,056 block RAMs, most of it
  the scope. It meets timing at 33.33 MHz with a 2-tick multicycle on core
  paths (`core/model.sdc`), and `tools/check_v35s_build.py` qualifies it.
- **How the shell drives it:** the core is frozen in T2 while each V35 cycle
  runs, because the ucore latches read data at T2.
- **What matches silicon:** bus states, strobes, waits and refresh shape.
- **What does not yet:**
  - prefetch depth, reset exit and refresh placement (see the timing doc);
  - register banks in internal RAM;
  - the V35-only instructions;
  - every peripheral.

**Next work:**

1. A V35 bus unit to replace the V30 prefetch policy.
2. The directed corpus and vector campaigns from the 68000 harness.
3. The open refresh-in-HALT item.
