# V35S bus timing, measured

First-pass measurements of the socketed µPD70337L-8 (V35 "Software Guard",
marked V35S) on nuBoard revision 2. They were taken with the harness in
[`v35s-harness.md`](v35s-harness.md). The raw receipt is
[`validation/v35s/characterize-2026-10-12.json`](../validation/v35s/characterize-2026-10-12.json),
produced by `python -m validation.v35s.characterize --socket-fitted`.

The receipt is from harness build 2, whose fabric runs at 33.33 MHz: one
scope tick is 30 ns. Build 1 (50 MHz, 20 ns ticks) gave the same cycles,
kinds and counts in every case; only its edge quantization differed. Each sample goes through the FPGA's two-flop
synchronizer, so every edge carries up to one tick of uncertainty. The CPU's
X1 ran at 25 MHz / 3 = 8.33 MHz, the same as the build 2 default.

## Clock

| PRC.PCK | CLKOUT period | Note |
| --- | --- | --- |
| 10 (reset, fX/8) | 32 ticks = 0.96 µs | PRC resets to 4Eh |
| 01 (fX/4) | 16 ticks = 480 ns | |
| 00 (fX/2) | 8 ticks = 240 ns | |

- P07 becomes CLKOUT after PMC0 bit 7 is set. The data book's PMC0 figure is
  unreadable in the converted text; the bit position is confirmed on silicon.
- CLKOUT is visible only once the T2 bank has been handed to the CPU through
  the marker port.

## Bus cycle shape

One bus state is one CLKOUT period. Times are in states, relative to the
CLKOUT rising edge at or before /MREQ (or /REFRQ) falls. Build 1 placed
fX/2 edges about ¼ state late (3 of 12 ticks); build 2 places them on the
half state at every rate, so that offset was synchronizer quantization, not
CLKOUT delay.

| Cycle | /MREQ ↓ | strobe ↓ | strobe ↑, /MREQ ↑ | /MREQ low |
| --- | --- | --- | --- | --- |
| memory read, 0 waits | 0.5 | /MSTB 1.5 | 2.5 | 2 states |
| memory write, 0 waits | 0.5 | /MSTB 1.5 | 2.5 | 2 states |
| memory write, 1 wait | 0.5 | /MSTB 2.5 | 3.5 | 3 states |
| memory write, 2 waits | 0.5 | /MSTB 3.5 | 4.5 | 4 states |
| memory read, n waits | 0.5 | /MSTB 1.5 | 2.5 + n | 2 + n |
| I/O read or write, n waits | 0.5 | /IOSTB 1.5 | 2.5 + n | 2 + n |
| refresh (RFW = 2) | /REFRQ ↓ 0.5 | none | /REFRQ ↑ 4.5 | 4 states |

So a cycle is B1, B2, waits and B3:

- /MREQ falls in the middle of B1.
- A read /MSTB and every /IOSTB fall in the middle of B2.
- A write /MSTB falls in the middle of the state before B3.
- All strobes rise in the middle of B3.
- Back-to-back cycles are 3 + n states apart, start to start (5 states at
  reset).

/MREQ is asserted for I/O cycles as well as memory cycles. A refresh asserts
only /REFRQ.

## Addresses

- **Address phases:** row (A9–A17) is on the multiplexed pins while /MREQ
  falls, and column (A1–A8) once the strobe falls. A18 is taken at the row
  phase. /UBE is taken at the column phase. A0 and A19 hold for the whole
  cycle. These phases reconstruct every observed fetch and data address
  exactly.
- **Odd-address word access:** split into a high-byte cycle at the odd address
  (/UBE low, A0 high) and then a low-byte cycle at the next even address.
- **Refresh row counter:** the A9/A1 … A17/A9 pins carry a 9-bit row counter
  that advances by one per refresh. The lane records it as address
  `counter << 9`, with A0, A19 and A18 low.

## Waits (WTC)

- **At reset:** WTC = FFFFh, "2 waits + READY". With READY high that is
  exactly two waits, 4-state /MREQ.
- **Programmed values:** WTC = 0000h, 5555h and AAAAh give 0, 1 and 2 waits
  on memory and I/O alike.
- **Refresh waits:** refresh cycles keep the RFM.RFW count (2 at reset)
  whatever WTC says.

## Refresh (RFM)

Measured by `python -m validation.v35s.prefetch --refresh` (corpus entry
`m-refresh`). Each case is a stretch with no bus cycles of its own, then
HALT.

- **Period (RFM.RFT, bits 1–0):** 16, 32, 64 or 128 CPU clocks for
  RFT = 0–3. It counts CPU clocks, not a fixed clock: at fX/2, fX/4 and fX/8
  the RFT = 0 period is 16 clocks each time.
- **Jitter:** in HALT, successive intervals alternate 15 and 17 clocks
  (31/33, 63/65, 127/129 for the longer periods). While running, a refresh
  waits for the current bus cycle to finish, so intervals of 13–18 clocks
  appear, still averaging the period.
- **Length (RFM.RFW, bits 3–2):** RFW = 0, 1 and 2 give refresh cycles of 2,
  3 and 4 states (0, 1 and 2 waits). RFW = 3 behaves as 2.
- **HALT:** refresh continues in HALT at the same period. The earlier note of
  a 60-state HALT interval came from a build-1 trace that ends at the pass
  write and holds no HALT refreshes; it is withdrawn.
- **Placement against memory cycles:** at fX/2 a refresh cycle starts 1 tick
  (⅛ state) earlier in the state than memory cycles do.
- **Disabling refresh:** RFM.RFEN = 0 (ECh) removes refresh cycles completely.

## Prefetch

Measured by `python -m validation.v35s.prefetch` (corpus entries
`a2a3-prefetch`, `m-prefetch-w0`, `-w2` and `-refresh`). Reruns reproduce
every scenario cycle for cycle.

- **Queue:** 6 bytes, filled a word at a time.
  - After a flush the BIU fetches back to back: every 3 clocks at 0 waits,
    every 5 at 2 waits.
  - It fills to the word boundary that the 6-byte budget allows past the
    instruction being executed: 9–10 bytes past a branch target that starts
    a 3-byte instruction.
- **Odd targets:** a byte fetch at the odd address first, then words.
  Checked for targets at each byte alignment.
- **Refill:** with the queue draining one byte at a time (NOPs), one word is
  fetched per two bytes consumed.
- **Data cycles:** a load, store or read-modify-write goes out at the next
  bus slot after the EU asks, between fetches. The read and write of a
  read-modify-write are 5 clocks apart at 0 waits and 7 at 2 waits.
- **Refresh:** takes the next free slot and delays the next fetch by its
  length.

## READY

Measured by `prefetch.py --wtc FFFF --pmc1 80 --ready-ticks N` (corpus
entries `m-ready-pmc*`).

- **Enabling READY:** P17 must be switched to READY with PMC1 bit 7 (PMC1 at
  xxF0Ah). Without it, a held READY input is ignored and WTC = FFFFh gives
  plain 2-wait cycles.
- **Sampling:** with READY selected, the cycle keeps its 2 programmed waits.
  After that READY is sampled once per state.
  - With READY held low for N ticks after the column strobe falls, the
    cycle gains one wait for N = 2–9 and two for N = 10–16.
  - Each further 8 ticks (one state) adds one wait, up to the 6-state hold
    tested.
  - Allowing for the lane's synchronizer delay, the first sample falls about
    1.2 states after /MSTB or /IOSTB falls.
- **I/O cycles** extend the same way as memory cycles.

## Internal RAM and SFRs

Data accesses to IDB:E00–EFF (with RAMEN = 1), the SFRs IDB:F00–FFF, and
FFFFF never appear on the bus. Their timing equals a zero-wait external
access. With RAMEN = 0 the RAM range goes out on the bus and the SFRs stay
internal. Details are in [`v35s-eu-timing.md`](v35s-eu-timing.md).

## Reset

- **Reset to first bus activity:** the first bus activity is a refresh
  118–128 X1 periods after /RESET rises (about 15.5 states of fX/8). The
  first fetch, from FFFF0, follows at 198–208 X1 periods (about 25.5
  states). Both are independent of the /RESET hold time; the spread is the
  phase of the fX/8 divider at release. See
  [`v35s-core-decision.md`](v35s-core-decision.md#reset-exit-a3).
- **Reset prefetch:** before the reset far jump executes, the CPU fetches six
  words, FFFF0 to FFFFA. After the jump it fetches five words before the
  first data cycle.
- **AW at reset:** undefined. The smoke run read 0060h.

## Model comparison, first core

The first model core is the nuV30 V30 ucore behind a V35 bus shell; see
`fpga/v35s/core/v35s_model.sv`. Its bus states, strobe positions, waits and
refresh cycle shape match the table above. Its prefetch policy and
reset-exit timing are V30's, and they differ:

| | silicon | model |
| --- | --- | --- |
| first bus cycle | refresh at 118–128 X1 periods | fetch FFFF0 at 78–84 X1 periods |
| fetches before the reset jump executes | 6 words | 4 words |
| fetches after the jump, before the I/O write | 5 words | 4 words |

These are the first targets for a V35 bus unit.

## Data book versus silicon versus MAME

| Item | Data book | Silicon | MAME `v25.cpp` |
| --- | --- | --- | --- |
| zero-wait cycle | B1 B2 B3 | B1 B2 B3 (3 states) | no bus model |
| write /MSTB | "data valid" while low | falls 1 state before end | none |
| WTC reset | FFFFh | FFFFh, 2 waits with READY high | not modelled |
| refresh | 16 × 2^RFT clocks | 16 × 2^RFT clocks running and in HALT, at every PCK | not modelled |
| PRC reset | 4Eh (fX/8) | 4Eh, CLKOUT = fX/8 | stored only |
