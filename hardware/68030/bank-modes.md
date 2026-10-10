# MC68030 bank and bus contract

This is the required host behavior, not implemented firmware. H means **host → DUT**, D means **DUT → host**, and Z means bank disabled. On the host's SN74LVCH8T245, A is FPGA and B is DUT: H uses DIR=1, D uses DIR=0, and /OE=0 enables. Change direction and preload data with /OE=1; allow old-driver disable, CPU release, propagation and setup/hold time before enabling the next driver.

## Bank allocation

| Bank | DUT group | Normal operation | Granted takeover |
| --- | --- | --- | --- |
| R2 | A0–A7 | D | D to observe, or H after release |
| T0 | A8–A15 | D | D to observe, or H after release |
| T1 | A16–A23 | D | D to observe, or H after release |
| T2 | A24–A31 | D | D to observe, or H after release |
| R0 | D0–D7 | By cycle | Z or H after release |
| B2 | D8–D15 | By cycle | Z or H after release |
| B1 | D16–D23 | By cycle | Z or H after release |
| B0 | D24–D31 | By cycle | Z or H after release |
| L2 | /DBEN, /CBREQ, R/W, SIZ0, SIZ1, /AS, /DS, /CIOUT | D | D to observe, or H after release |
| L0 | FC0–FC2, /RMC | D | D to observe, or H after release; unused bits LOW |
| R1 | /ECS, /OCS, /IPEND, /BG, /REFILL, /STATUS | **D only** | **D only; these outputs do not three-state** |
| L1 | /DSACK0, /DSACK1, /STERM, /CIIN, /CBACK, /AVEC, /BERR, /HALT | H | H; keep handshake inputs inactive |

All twelve banks are used. Physical bank-bit permutations are in `pin-map.csv`; bit number does not imply logical address/data bit number. For example, host memory data must be encoded using the table, not copied directly into a bank byte.

L00–L03 are tied together and pulled to GND through R1=47 kΩ. R13–R14 are tied together and pulled to GND through R2=47 kΩ. These groups are separate nets. Mask L0 output bits with `~0x0F` before any H enable. R1 stays D, but its unused bits must also be LOW if a future mode ever enables host drive; the present design forbids R1 H because its used outputs remain driven. Conflicting levels on tied unused bits short host drivers together; the resistor is only between the shared node and GND. See `unused-bank-pins.csv` and `reports/unused-bank-pins.json`.

## X0–X3 and clock allocation

| Resource | CPU function | Startup / ordinary inactive state |
| --- | --- | --- |
| TX1 | /RESET, bidirectional open-drain | Host asserts LOW during reset, then releases |
| TX2 | /BR | Released HIGH |
| LX1 | /BGACK | Released HIGH |
| LX2 | /IPL2 | Released HIGH |
| RX1 | /IPL1 | Released HIGH |
| BX2 | /IPL0 | Released HIGH |
| BX1 | /CDIS | Assert LOW during initial uncached testing; release for cache tests |
| RX2 | /MMUDIS | Assert LOW during initial untranslated testing; release for MMU tests |
| LCLK | CLK | Continuous qualified 12.5–25 MHz |
| TCLK, BCLK, RCLK | Unused | No-connect |

The seven non-reset X0–X3 signals are CPU inputs and are driven as open-drain by the host. /RESET is the CPU's only bidirectional open-drain control; /HALT is an input, not a 68000-style bidirectional halt output. The host must assert LOW or release, never actively drive HIGH on X0–X3. Keep the TXS0108E enabled whenever its pulls are needed. Its internal pull-ups are the fitted pull-up source; no extra daughter X0–X3 pulls are required by the DC leakage budget. Do not use X0–X3 for cycle-rate acknowledgements.

Limit X0–X3 changes to slow control events. For initial qualification, allow at least 10 µs for released signals to settle before relying on their sampled HIGH, and verify the actual socket waveform. This is a conservative host scheduling allowance, not a replacement for measurements or CPU timing requirements. The TXS0108E's specified open-drain rate is at most 1.2 Mbps. Change interrupt codes deliberately; transition through inactive 111 between requested levels to avoid transient priority codes. Sample and synchronize external status as required by the host design.

## Reset and power transitions

Grounded 5V_SELECT identifies a 5 V daughter. 3V3_SELECT stays floating. Configure the host supply and valid inputs before DUT power as required by the platform. Keep /RESET LOW, the eight L1 inputs HIGH, and /BR and /BGACK released. Keep /IPL2:0=111. Initially assert /CDIS and /MMUDIS LOW. All address, data and tri-state control banks are Z during rail transition/reset; R1 may receive when levels are valid. Preload unused bits LOW.

The clock must be stable when VCC reaches its operating minimum. Hold /RESET LOW for **at least 520 clocks after VCC is within 4.75–5.25 V**, then release it and qualify the observed rise. At 12.5 MHz this is 41.6 µs; at 25 MHz it is 20.8 µs. Use at least 520 clocks for later external resets too, accounting for overlap with the CPU's 512-clock RESET instruction output. On reset release, put address and tri-state control banks in D, retain R1 D, keep data Z until a valid read response, and keep L1 H. Fetch reset vectors using the selected external port width.

Do not stop or arbitrarily slow this CPU's clock during normal operation: the 25 MHz grade's specified operating range is 12.5–25 MHz. STOP, /HALT and cache-only execution are separate CPU states, not permission to violate the clock specification. Before power-down, quiesce transactions, disable host bus drives and follow host rail sequencing.

## Memory, I/O and interrupt transfers

| Phase | R2/T0/T1/T2 + L0/L2 | B0 | B1 | B2 | R0 | L1 | R1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Reset | Z | Z | Z | Z | Z | H | D or Z |
| Idle / bus turnaround | D | Z | Z | Z | Z | H | D |
| Read from 8-bit port | D | H | Z | Z | Z | H | D |
| Read from 16-bit port | D | H | H | Z | Z | H | D |
| Read from 32-bit port | D | H | H | H | H | H | D |
| CPU write, any port size | D | D | D | D | D | H | D |
| 32-bit synchronous/burst read | D | H | H | H | H | H | D |
| Takeover request pending | D | Continue current CPU cycle | Continue | Continue | Continue | H | D |
| Granted takeover observation | D | Z | Z | Z | Z | H | D |
| Granted conductor-drive test | H on selected released groups | H or Z | H or Z | H or Z | H or Z | H | D |
| Return from takeover | D after host release | Z | Z | Z | Z | H | D |

An 8-bit port uses **D31–D24**; a 16-bit port uses **D31–D16**. It does not use the least significant CPU lanes. A 32-bit port uses all 32 bits. Decode A1:A0, SIZ1:SIZ0, FC2:FC0 and R/W for each transaction, including misaligned and split transfers. The host may return a full aligned 32-bit word in a qualified 32-bit read window; the CPU consumes the required bytes. For writes, receive all data banks and select the bytes using Motorola tables 7-4 and 7-5. Do not infer byte enables solely from operand size, and do not reverse inactive data banks into H on CPU writes.

For asynchronous cycles, /DSACK1:/DSACK0 = HH inserts waits, HL acknowledges an 8-bit port, LH acknowledges a 16-bit port, and LL acknowledges a 32-bit port. Port width is the responding device's width even for smaller operands. Keep /STERM HIGH for asynchronous responses. Hold data/acknowledgements through their required sampling intervals, and remove host data drive before the CPU can begin a write. Use wait states until the timing schedule is qualified.

Synchronous termination uses /STERM and a 32-bit port; keep /DSACKx HIGH. Cache burst fills are **reads**, up to four longwords in one 16-byte line. Assert /CBACK with /STERM only for a supported /CBREQ request. The host must generate the subsequent longword addresses locally, incrementing the low line index modulo four from the requested first word; the CPU does not provide a fresh complete address for each beat. Keep all data banks H throughout the qualified read burst and obey /CBREQ, /CBACK and /STERM termination/abort behavior. Test instruction and data cache fills, cache-inhibited cycles, partial/aborted fills, /BERR and retry; do not invent burst writes for this write-through cache.

Interrupt acknowledge is a distinct CPU-space cycle. Support either /AVEC autovector response or a qualified vector-data response using the documented port-width/data-lane rules. /BERR and /HALT are in L1 for cycle-level error, retry and halt testing. /STATUS and /REFILL expose internal status but never transfer bus ownership.

## Arbitration and takeover

For normal three-wire arbitration, assert /BR through TX2 while completing the current CPU cycle. Observe /BG LOW through R1, /AS HIGH, inactive termination signals and /BGACK HIGH. Allow the specified CPU bus float interval before assuming ownership: the 25 MHz grade permits up to 40 ns after the relevant rising edge for address/data/function and bus-control release (specifications 7 and 16). Add host translator disable/enable delays, synchronization and board timing; /BG alone is insufficient.

Assert /BGACK through LX1 and hold it LOW for the entire takeover. Release /BR only after ownership is established. Switch only the released address, data and tri-state control banks to H for conductor tests, with all tied unused bits LOW. Keep R1 receiving throughout. A stable held voltage does not prove the CPU is still driving; the host bus keepers retain released levels.

Before releasing /BGACK, disable every takeover-driving bank and wait for its outputs to reach high impedance. Return the address/control banks to D and leave data Z. Release /BGACK, qualify its actual HIGH through the slow X0–X3 path, then serve subsequent CPU cycles. Never resume a host-drive test merely because a timer expired.

For explicit single-wire arbitration tests, /BGACK may force release without /BR. Motorola requires observing /AS HIGH on **two consecutive rising clock edges after /BGACK is recognized LOW**, plus the bus float/translator margins, before driving. Preserve the integrity of read-modify-write operands; ordinary /BR grants are deferred while /RMC is active. /HALT alone leaves control outputs driven inactive and is not a takeover grant. Follow manual §7.7 for arbitration overlapping retries, lock sequences or cache execution.
