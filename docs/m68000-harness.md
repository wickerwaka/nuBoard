# 68000 differential harness

This work uses `hardware/68000` as the socket wiring authority and the nu68020
bus-response/capture design as a reference. The upstream CPU is
<https://github.com/JTFPGA/fx68k>, pinned at
`1217ab8dc600de070c6adb71ea6fe69de8855362`.

## Implementation contract

- Three targets: Verilator, on-board fx68k, and socketed MC68000. Both board
  lanes can run simultaneously from identical images and independent memory.
- Common programmable memory windows, reset sequence, bus responder, and
  timestamped transaction capture. Comparison checks address, function code,
  read/write, byte enables, data, and separately reports timing differences.
- Programs start through the real reset vectors. Register results are written
  by test code or exception handlers; no RTL-only register injection is used.
- nuBoard USB firmware remains CPU-independent. An application debug protocol
  rides the existing FPGA mailbox; the Python transport is reusable by other
  cores. Completion uses the existing interrupt notification path.
- All DUT outputs are disabled until a host explicitly arms the socket.
  RESET/HALT use open-drain pulls through XY. Build 6 keeps read output
  enabled continuously, including between strobes. External data direction
  and FPGA output enable follow R/W together, combinationally. Run limits and
  transaction-counter overflow fail the run; finite trace windows are
  explicitly reported as incomplete.
- Software cannot infer the physical CPU part marking. Real testing requires
  the fitted part, valid 5 V selection, and explicit socket mode.

## Test sources

1. Musashi `test/mc68000`, pinned at
   `313ebf1bd9f4d0d93341eb5ce21fd8a119e9dbdd`, supplies executable instruction
   tests. **Rebuild with `-march=68000`**: upstream's default is 68040 and its
   checked-in `move.bin` contains a PC-relative CMPI unsupported by 68000.
   Its machine has RAM at zero and 0x300000,
   code at 0x10000, and pass/fail MMIO at 0x100004/0x100000.
   Source: <https://github.com/kstenerud/Musashi/tree/master/test>.
2. SingleStepTests/m68000 supplies MAME-generated single-instruction vectors.
   Revision `64b253116a3de04aaac4346c43680960dc9b67e5` is pinned separately.
   The initial adapter supports **MOVE.q only**, rejecting other instructions.
   It boots from reset, initializes registers with MOVE/MOVEM, and uses RTE plus
   a trace exception to capture registers, both stack pointers, SR, PC, and RAM.
   No private fx68k register injection is used. SR.T is forced for capture and
   normalized back to the fixture's original bit. Final prefetch and fixture bus
   timing are explicitly **not checked**. Its documented TAS timing and TRAPV
   caveats remain relevant before extending this adapter.
   The older SingleStepTests/680x0 format has different RAM byte sizes and PC
   conventions; it must not be silently interpreted as the newer format.
   Binary RAM is word-sized; the pinned `decode.py` expands it to byte pairs.
   PC is the next-prefetch address, four bytes beyond the instruction address.
   Source: <https://github.com/SingleStepTests/m68000>.

Upstream suites are candidate stimuli and expected results, not a substitute
for the real-chip capture. Simulation results and socket observations are
reported separately. Build artifacts and downloaded dependencies live under
the ignored `build/` directory.

## Build and run

Requires Python 3.11+, PyUSB, Verilator, a C++ compiler, and GNU m68k binutils.
The board build additionally requires Efinity 2026.1. The dependency helper
refuses dirty or unexpected revisions; it never resets an existing checkout.

```sh
python3 tools/fetch_m68000.py
python3 tools/fetch_m68000.py --verify-only
python3 tools/build_m68000_tests.py
bash fpga/m68000/build_sim.sh
bash fpga/m68000/build_sim.sh spi
bash fpga/m68000/build_sim.sh dual
bash fpga/m68000/test_lane.sh
bash fpga/m68000/test_pins.sh
PYTHONPATH=host/src:. python3 -m unittest discover -s host/tests
PYTHONPATH=host/src:. python3 -m unittest validation.m68000.test_harness
PYTHONPATH=host/src:. python3 -m validation.m68000.runner \
  --output build/validation/m68000/musashi-sim.json
PYTHONPATH=host/src:. python3 -m validation.m68000.runner \
  --backend spi-sim --only moveq movem lea_tas \
  --output build/validation/m68000/spi-sim.json
python3 tools/fetch_m68000_vectors.py
PYTHONPATH=host/src:. python3 -m validation.m68000.runner \
  --vectors build/deps/m68000-vectors/v1/MOVE.q.json --limit 1000 \
  --output build/validation/m68000/singlestep-sim.json
bash fpga/m68000/build.sh
```

`build_m68000_tests.py` accepts installed `m68k-linux-gnu-as/ld`, or a Debian
binutils package extracted to `build/deps/binutils`. It does not modify upstream
sources. `sim` runs the debug bus directly; `spi-sim` exercises the real mode-0
SPI mailbox, CRC/tag checking, and IRQ/ACK path around the same CPU/memory RTL.
The SPI simulator asserts that DUT power, bank OEs, XY, and socket clock remain
disabled in model mode.
The `dual` simulator uses a second fx68k as a socket surrogate to exercise both
independent responders and full-window replay. It is a harness regression test,
**not** independent CPU validation or a model of analog translator behavior.

For FPGA-only testing, including with the daughterboard installed, use model
mode. It leaves VCCB and the socket outputs disabled:

```sh
nuboard configure build/fpga/m68000/outflow/m68000.hex.bin
PYTHONPATH=host/src:. python3 -m validation.m68000.runner \
  --backend board --mode model --only moveq movem lea_tas \
  --output build/validation/m68000/board-model.json
```

After installing the MC68000P12 **with power removed**, confirming orientation,
and selecting 5 V exclusively, configure again and opt in explicitly:

```sh
nuboard configure build/fpga/m68000/outflow/m68000.hex.bin
PYTHONPATH=host/src:. python3 -m validation.m68000.runner \
  --backend board --mode both --socket-fitted --only moveq \
  --output build/validation/m68000/board-paired.json
```

`--mode socket` uses the physical CPU only. `--vectors` works with any backend;
the same reset executable is sent to both lanes. The runner verifies the core
UUID/debug ABI before enabling VCCB, requires VCCB initially off, and checks the
exclusive 5 V selector. It enables continuous 5 MHz clock/reset, waits 10 ms for
power settling, then applies 600 more reset clock periods. Paired runs stop on
the first failure. The `finally` path powers the board off and releases USB.
An unplugged USB device is an error, never a fallback to simulation.

The NMOS MC68000 is not a static-clock part. Divider values are restricted to
5 or 6 (5 MHz or approximately 4.167 MHz), and cannot change while armed. Clock
continues between runs while the socket is powered and RESET/HALT are asserted.
See the [Motorola/NXP manual, section 10.8](https://www.nxp.com/docs/en/reference-manual/MC68000UM.pdf).
The bench must still verify clock levels, edges, supply, and bus turnaround.

## Memory and capture

Build 8 uses [single-CPU change capture directly in BRAM](m68000-bram-capture.md)
with scope ABI 4. Build 7's PSRAM path has been replaced. The paired 512-sample scope descriptions later in this document
describe builds 3–6; their archived report decoders remain supported.

Each lane has independent 64 KiB RAM, mapped by sixteen programmable 4 KiB page
entries over the 24-bit CPU address space. Host image writes initialize both
copies. Unmapped cycles receive BERR; there is no silent wrapping. Byte strobes
select independent high/low byte RAM writes. The responder recognizes each
UDS/LDS phase, including the two halves of TAS while AS remains asserted.
After reset it requires two synchronized idle-bus samples before accepting
the first transfer. Reset-time low or undriven strobes must not write vector RAM
or create a false trace record.

MMIO is 0x100000..0x1000ff. Long writes to 0x100000 fail; long writes to 0x100004
pass, latched after the second word completes. Other MMIO reads return zero and
writes are acknowledged but ignored: print-state, interrupt injection, and UART
semantics are **not implemented**. This is sufficient for the selected 60
`mc68000` programs, not a general Musashi machine or 68040/FPU environment.

Each lane captures a selected window of 2,048 completed transfers. A record is
16 bytes, little endian `<IIHHI>`: start tick, even byte address, data, flags,
end tick. Ticks are 20 ns. Flags: bit 0 LDS, bit 1 UDS, bit 2 read, bits 5:3 FC,
bit 6 unmapped. Start/end are synchronized responder observations, not direct
oscilloscope edge timestamps; idle cycles and address errors without AS are not
captured. Unselected data lanes are masked in functional comparison.

Total transaction counts and a rolling CRC32C fingerprint cover the whole run.
Single-lane reports retain a diagnostic prefix and explicitly set
`trace_complete=false` for longer programs. A paired success requires every
window, replayed from the original RAM image; each replay must reproduce the
same total and fingerprint before records are concatenated and compared exactly.
Fingerprints alone never establish equality. Timing differences are reported
separately from functional differences, after aligning the first transfer.
Long suites can be expensive in paired mode because each window requires a new
reset run. A failed or interrupted run never produces a passing report.

## Generic debug application ABI

Channel 0x44 carries one `NDB1` request per mailbox packet. Integers are little
endian. Header `<4sBBHI>`: magic, operation, reserved zero, byte length, 20-bit
byte address. Transfers are aligned, even, nonzero, and cannot cross the 1 MiB
debug-address boundary. Build 9 raises READ/WRITE from 256 to 4068 bytes:
4096 minus the 16-byte mailbox header and the 12-byte NDB1 request header.
Operations:

- 0 READ: no body; return bytes.
- 1 WRITE: body contains exactly `length` bytes; no reply data.
- 2 WAIT16: length 2; body `<HHI>` mask, expected value, maximum 50 MHz ticks
  (1..100,000,000). Repeat local reads until `(value & mask) == expected`.
- 3 FILL16 (build 9): body `<H>` repeated word; length is the destination byte
  count, up to 65534, not the body size. No reply data. A 64 KiB fill requires
  two commands. It uses the same sequential debug-bus writes and access checks
  as WRITE; this is not a CPU-specific RAM backdoor.

Reply `<HH>` status/reserved-zero followed by read data. Status 0 success,
1 invalid request/access, 3 timeout. On errors, no read data is returned.
WAIT16 completion produces the ordinary mailbox IRQ and USB interrupt record.
The host blocks on that event; it does not poll GET_STATE or debug registers.
The same device instance must not have another concurrent event consumer.

WRITE/FILL stop at the first bus error. Earlier writes are not rolled back;
failed initialization must abort the case, never continue into CPU execution.
The host validates the entire address range before sending the first chunk.
Old builds do not support the new maximum or FILL; hardware runners require
build 9 rather than retrying or silently falling back to the old protocol.

The bridge keeps request/reply headers in small register arrays and payloads in
a synchronous-read 2048-by-16 RAM. CRC and transmit prefetch states account for
RAM latency; output backpressure holds the byte and packet position stable.
Mailbox framing, CRC32C, IRQ/ACK ownership and MCU firmware remain unchanged.

Initialization batches the sixteen page-map registers, fills all mapped memory
with zero, and uploads each page's nonzero span with word-aligned boundaries.
This preserves zero-filled holes, empty stack/results pages, byte order and
overlapping-segment semantics. The host memory-write port broadcasts to both
independent CPU RAMs. The comparison campaign initializes once per repetition,
then runs/captures the model and socket separately without reloading in between.
CPU reset/trace clear does not clear RAM; each new repetition still initializes
both memories. CPU clocks, ACK timing, continuous drive and buffer direction
are unchanged.

Build-9 qualification (2026-09-19): 20 host, 53 validation and 6 build-checker
tests pass, together with pin-safety, strobe-skew and BRAM-capture RTL gates.
All 231 directed physical cases pass defined-state and sampled-phase comparison;
the on-board model also matches simulation. Five SPI simulation cases match the
direct model. Physical full-size transfers and 64 KiB fills/readback pass with
VCCB disabled. The directed paired run took 138.46 seconds (0.60 seconds/case),
versus roughly 3.7 seconds/case in the previous seeded run; case mixes differ.

The first synthesis attempt exposed incompatible inferred RAM write ports.
Explicitly muxing the receive/readback producers before one RAM write port fixed
that inference. The routed image uses 931/1056 RAM blocks, checks all 153 package
assignments, and has +2.013 ns 50 MHz setup slack and +0.086 ns minimum constrained
hold slack. Its SHA-256 is
`400e281fbc80a681164b89c271ecf8dd3dbaf4301cb76dbe00c54b40e1774f36`.
Evidence: `build/fpga/m68000/receipt.json`,
`build/fpga/m68000/build-9-debug-board.json`, and
`build/validation/m68000/campaign-extended/build9-board.json`.

## Harness register map

All addresses are byte addresses and registers are 16 bits unless noted.

| Address | Meaning |
| --- | --- |
| 0x00 / 0x02 | ID 0x6830 / ABI 1 |
| 0x04 | control: bit 0 arm, bit 1 start, bit 2 abort; start mode bits 9:8 (1 model, 2 socket, 3 both) |
| 0x06 | busy bit 0, complete bit 1, model result bits 3:2, socket result bits 5:4, overflow bit 6, timeout bit 7 |
| 0x08 / 0x0a | half-period divider / responder wait ticks (2..255) |
| 0x0c / 0x10 | 32-bit run limit / elapsed ticks |
| 0x14 / 0x16 | model / socket captured-record counts |
| 0x18 | raw socket RESET/HALT/AS/UDS/LDS/RW/FC diagnostic bits |
| 0x1a / 0x1e | 32-bit model / socket total transactions |
| 0x22 / 0x26 | 32-bit model / socket functional fingerprint |
| 0x2a | 32-bit capture starting transaction ordinal |
| 0x2e / 0x30 | passive waveform sample count / scope ABI (1 in build 3, 2 in builds 4/5/6) |
| 0x32..0x35 | 32-bit first waveform sample tick, default 0 (scope ABI 2) |
| 0x40..0x5e | sixteen page entries: bit 15 valid, bits 11:0 CPU page number |
| 0x10000..0x1ffff | model RAM read; writes broadcast to both lanes |
| 0x20000..0x2ffff | socket RAM read-only |
| 0x30000..0x37fff | model trace read-only |
| 0x40000..0x47fff | socket trace read-only |
| 0x50000..0x51fff | 512 passive waveform samples, 16 bytes each (core build 3+) |

Result codes are 0 pending, 1 pass, 2 fail, 3 counter overflow. RAM/page/control
writes and RAM/trace reads are rejected while busy, except explicit abort. Abort
terminates the run; it does not remove socket power or stop its clock.

Build 3 adds a passive waveform recorder for timing investigations. It captures
512 system-clock samples after reset release; build 4 adds a programmable start
tick so operand transfers later in a program can be observed. It does not change the
responders, CPU, or pin drivers. Both lanes pass through the same two-register
observation pipeline. See [the timing reproduction](m68000-timing.md) for the
sample format and reset-read waveform, and [ordinary memory moves](m68000-memory-timing.md)
for the operand read/write test.

Build 5 removes the socket adapter's clocked data-buffer turnaround and its
read-only DTACK gate. Both T0/T1 DIR and FPGA data drive follow the same
combinational read-drive condition; their bank OEs remain enabled while armed.
The scope's socket DTACK now also feeds the socket output directly, with no
additional logical qualification. Disarming still disables the bank OEs and
releases FPGA drive. This does not eliminate physical pin/buffer propagation
delay or establish analog electrical timing qualification.
The [build 5 hardware comparison](m68000-immediate-direction.md) documents the
eliminated read slowdown and paired instruction regressions.

Build 6 also removes AS/UDS/LDS and responder-ready gating of the data drive.
While armed, T0/T1 DIR and FPGA output enables follow raw R/W only: they stay
in output mode throughout reads and idle gaps with R/W high, and switch to
input mode when R/W goes low for a write. Both bank OEs remain enabled while
armed. Data validity is still established by the common responder and DTACK,
not by toggling output enable. Disarming still disables the socket.
The [build 6 hardware result](m68000-immediate-direction.md#build-6-continuous-read-drive)
records the unchanged matching read timing and all paired regressions.

## Daughterboard wiring

Indices in this table are **in increasing bank-bit order**. DIR=0 is CPU to
FPGA, DIR=1 is FPGA to CPU. Bank OEs are active low. XY OE is active **high**
despite the schematic-derived `xy_oe_n` port name.

| Bank | Signals [0] through [7] |
| --- | --- |
| T0 | D15 D14 D13 D12 D11 D10 D9 D8 |
| T1 | D5 D6 D7 D0 D1 D2 D3 D4 |
| B0 | A1 A2 A3 A4 A16 A15 A14 A13 |
| B1 | A12 A11 A10 A9 A8 A7 A6 A5 |
| B2 | A17 A18 A19 A20 A21 A22 A23 unused |
| L0 | AS_N UDS_N LDS_N R/W BG_N E VMA_N unused |
| L1 | DTACK_N BGACK_N BR_N BERR_N IPL2_N IPL1_N IPL0_N VPA_N |
| L2 | FC2 FC1 FC0 unused unused unused unused unused |

LX=HALT_N, LY=RESET_N, LCLK=CPU clock. RESET/HALT only pull low. T2 and all
right-hand banks remain disabled. PSRAM is deselected again in build 8;
build 7 used it for the independent waveform recorder. CPU memory still uses
internal block RAM for deterministic response timing, leaving the PSRAM echo
template unchanged. `dut_isolate=1` opens P-channel Q1; crowbar remains off.

## Licensing and scope

fx68k is GPL-3.0; retain its license and corresponding source when distributing
a combined core/bitstream. Musashi's license is in its `readme.txt`; the newer
SingleStepTests repository includes MIT `LICENSE`. Dependencies are fetched,
not relabeled as original nuBoard code. This harness does not patch fx68k.
The generic host debug client/exchange is CPU-independent; MCU firmware is
unchanged. The copied mailbox remains local to `fpga/m68000`, so changes here
do not alter the proven PSRAM template.

## Progress and evidence

- [x] Confirm daughterboard address, data, control, RESET/HALT and clock nets.
- [x] Inspect upstream core and executable suite; pin source revisions.
- [x] Implement common responder, traces, control and board adapter.
- [x] Implement mailbox debug transport and shared host runner.
- [x] Run upstream tests in Verilator; 56/60 Musashi programs pass, four fail:
  `abcd`, `sbcd`, `divs`, `divu`. No timeout or trace overflow in those failures.
  These are unresolved suite/core disagreements, **not confirmed silicon bugs**.
  A physical paired DIVU run also fails on the MC68000P12; its captured prefix
  matches fx68k, but the failed run does not establish complete trace equality.
- [x] Run 1,000 MOVE.q single-step vectors: 1,000 pass, zero skipped.
- [x] Pass 16 host unit tests and 8 harness regressions, including malformed
  SPI debug requests, timeout/error recovery, unarmed-socket rejection, and
  two-lane full-window comparison. A separate long replay gate compared all
  79,843 AND-test transactions using two fx68k instances. The reset-strobe
  regression fails against build 1 and passes with the build 2 correction.
- [x] Route Efinity T120F484/C3 seed 1, core build 2: 50 MHz setup slack
  +0.949 ns, hold +0.116 ns; 10 MHz SPI setup/hold positive. 26,199 logic
  elements and 411/1056 memory blocks. Passive-x4 bitstream SHA-256:
  `9ae525acd25950172487084f881aac10a394f10015cea398294ddddb053bb574`.
- [x] On-board model TAS/MOVEM/MOVEQ: all 882 transfers exactly match Verilator.
- [x] Fitted MC68000P12 and on-board fx68k TAS/MOVEM/MOVEQ: all 882 functional
  transfers match with complete traces. Timing differs; not cycle-exact.
- [x] First 100 MOVE.q vectors on both physical lanes: all architectural
  checks pass and all 12,200 functional transfers match. Final prefetch and
  source-suite timing remain outside the adapter's checked scope.
- [ ] Qualify socket electrical timing with bench measurements; broaden paired
  instruction coverage and investigate the four simulation disagreements.

The original simulation-only receipt is
[`validation/m68000/baseline-2026-09-18.json`](../validation/m68000/baseline-2026-09-18.json).
The subsequent physical results are summarized separately in
[`validation/m68000/hardware-2026-09-18.json`](../validation/m68000/hardware-2026-09-18.json).
Full raw traces are under `build/validation/m68000/`. The build checker validates
all 153 package assignments and all twelve constrained setup/hold relationships,
and saves source and bitstream hashes to `build/fpga/m68000/receipt.json`.
The simulated `divs`/`divu` terminal traces reach the accumulated-flag comparison
at 0x100090 after passing the accumulated-data check. The physical DIVU run also
emits FAIL, but terminal flag values were not captured. Root-cause investigation
is still needed before deciding whether suite expectations or the core require
changes; DIVS/ABCD/SBCD have not yet been run on the socketed CPU.

The user subsequently connected nuBoard with the MC68000P12 daughterboard
installed. The [hardware bring-up journal](m68000-hardware-2026-09-18.md)
records physical results and the failed attempts that led to two harness/host
corrections. Neither fx68k nor MCU firmware was changed. Socket electrical
constraints are not signed off by internal FPGA/SPI timing closure or by these
functional captures.
