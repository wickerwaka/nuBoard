# V35S host bank operating contract

The interface is direct. Bank direction/enable is shared by all eight bits; unused bits in a used bank share one 47 kΩ pull-down to GND per bank (see `unused-bank-pins.csv`). This document is a firmware contract, not implemented firmware. The user requested both DMA channels, all DMA transfer modes, bus arbitration, and uniform-direction GPIO tests. Arbitrary combinations of every alternate peripheral function are not supported by twelve shared banks.

**H** = enabled **host → DUT**. **D** = enabled **DUT → host** (host FPGA pins must be inputs). **Z** = bank disabled, neither side driven by its translator; internal host bus keepers still exist. Bank logic polarities must follow the host schematic; H/D here deliberately describe physical direction, not a raw DIR bit value.

## Wiring groups

| Bank | Connected DUT pins/functions | Permitted directions |
| --- | --- | --- |
| L0 | D0–D7, pins 13–20 | H for low-byte reads; D for writes; Z during turnaround |
| L1 | D8–D15, pins 21–28 | H for high-byte reads; D for writes; Z during turnaround |
| L2 | A0, multiplexed A9/A1 through A15/A7, pins 29–36 | D only during normal testing; remains D during hold |
| B0 | A16/A8, A17/A9, A19, A18//UBE, TxD0, TxD1 | D only; never drive this bank toward the DUT, including hold |
| T1 | /IOSTB, /MREQ, /MSTB, R//W, /REFRQ | D only during normal testing; remains D during hold |
| T2 | P00–P07/CLKOUT | H for all-input GPIO; D for all-output GPIO or CLKOUT with P00–P06 outputs |
| T0 | P14/INT//POLL, P17/READY | H for peripheral-input operation; H or D together for uniform GPIO |
| R2 | P13//INTP2//INTAK, P15/TOUT, P16//SCK0, /CTS0/RSCK | H when all four are inputs; D when all four are outputs; see restrictions below |
| B2 | P20/DMARQ0, P23/DMARQ1, P27/HLDRQ | H for DMA/arbitration requests; H/D together for uniform P2 GPIO |
| R0 | P21//DMAAK0, P22//TC0, P24//DMAAK1, P25//TC1, P26//HLDAK | D for DMA/arbitration outputs; H/D together for uniform P2 GPIO |
| R1 | PT0–PT7 | H, digital low/high stimulation of comparator inputs |
| B1 | RxD0, RxD1, /CTS1, N//S, P10/NMI, P11//INTP0, P12//INTP1, /RESET | H throughout operation; every pin is an input |

No entire bank is unused. Unused bank bits are tied together within each bank and share a 47 kΩ pull-down. All eight X/Y pins are marked no-connect. LCLK/BCLK are unused. The exact bit permutation and connector pad numbers are in `pin-map.csv`; the bank bit number is not generally the CPU data/address bit number.

## Initial host levels

Set these values before DUT power-on, consistent with the host's valid-input guarantee. Keep /RESET low through power rise and clock stabilization, for at least 30 ms after the supply is valid (NEC power-on/STOP reset requirement). Ordinary running-system reset minimum is 5 µs. Use the longer interval when unsure. /RESET is active LOW.

| Function | Initial level |
| --- | --- |
| /RESET | LOW (asserted) |
| N//S | HIGH for normal mode; LOW only when intentionally testing the factory security table |
| NMI, /INTP0, /INTP1, /INTP2 | HIGH and held steady; configure edge polarity before generating any transition |
| INT/P14 | LOW, no external interrupt request |
| READY/P17 | HIGH; initial port mode is input; configure wait-control/PMC1 before relying on READY wait insertion |
| DMARQ0, DMARQ1, HLDRQ | LOW, inactive; requests are active HIGH |
| RxD0, RxD1 | HIGH, UART idle |
| /CTS0, /CTS1 | HIGH, transmitter inhibited until intentionally enabled |
| P00–P07, P15/P16, unused P2 input-port bits | Defined LOW, except the inactive request/interrupt levels above |
| PT0–PT7 | LOW initially; stimulate digital levels only |

After reset, PM0/PM1/PM2 = FFh and PMC0/PMC1/PMC2 = 00h: GPIO starts as input. Consequently T2, T0, R2, B2, R0 start H, not D. B1 and R1 stay H. L2/B0/T1 stay D because their CPU pins are output/tri-state or transmit outputs. Keep data banks Z while establishing reset and until a qualified read window; their receiver values outside valid bus transfers are ignored.

Do not confuse the default GPIO-input level on P26 with a valid /HLDAK handshake. First configure PMC2 to select DMA/hold functions and complete the direction transition below.

## CPU and DMA bus phases

The bank states below assume P2 has been configured for DMA/arbitration and the normal peripheral input selection for T0. GPIO/serial modes are an independent overlay described below.

| Phase | L0/L1 data | L2/B0/T1 output banks | B2 requests | R0 DMA/hold responses | B1, R1 | T0 |
| --- | --- | --- | --- | --- | --- | --- |
| Reset asserted; GPIO initialization | Z | D | H | H (P2 input ports) | H | H |
| Reset release / instruction fetch preparation | Z until qualified read | D | H | H until PMC2 transition | H | H |
| CPU address phase / bus idle | Z | D | H | D | H | H |
| CPU memory or I/O read | H on selected byte banks only, after DUT releases data | D | H | D | H | H |
| CPU memory or I/O write | D on selected byte banks; never H | D | H | D | H | H |
| DMA memory-to-memory source read | H on selected byte banks | D | H | D | H | H |
| DMA memory-to-memory destination write | D on selected byte banks | D | H | D | H | H |
| DMA I/O-to-memory fly-by transfer | H, representing the peripheral driving the bus into memory | D | H | D | H | H |
| DMA memory-to-I/O fly-by transfer | H, representing memory driving the bus into the peripheral | D | H | D | H | H |
| Read/write bus turnaround | Z | D | H | D | H | H |
| External hold request pending | Follow the current CPU/DMA transfer until completed; then Z | D | H, HLDRQ HIGH | D, monitor /HLDAK | H | H |
| Hold granted (/HLDAK LOW) | Z normally; optional H stimulus only while all data outputs are released | D (observe only) | H | D | H | H |
| Hold relinquish | Z before HLDRQ falls; await CPU ownership, then normal read/write policy | D | H, HLDRQ LOW | D | H | H |
| HALT | Z except qualified refresh/bus cycles | D | H | D | H | H |
| STOP | Z; follow NEC STOP supply/clock restrictions | D | H with stable levels | D | H | H |
| Warm reset / STOP release | Z; transition GPIO banks back to H only after reset has disabled their outputs | D | H | H after outputs are released | H | H |

**Fly-by DMA is not a CPU read followed by a CPU write.** During I/O↔memory transfer modes, the DUT outputs address and strobes and enables the external peripheral with /DMAAK; data is supplied by an external source. There are no physical memory/peripheral chips on this daughter board. The host supplies the source data and models the destination, while verifying the DUT's address, strobe, DMAAK and TC sequences. Do not derive host data direction only from R//W in these modes. See NEC V35 1991 timing diagrams, section pp. 45–46.

A0 and /UBE select byte lanes. For byte transfers, enable only the selected byte bank toward the DUT; a word spanning an odd address takes two byte cycles. L0 and L1 have independent enable controls but must obey the same ownership/turnaround contract. Internal DMA transfers, interrupt-acknowledge reads, CPU fetches and normal operand transfers must all be decoded by the host.

DMARQ0/1 are active HIGH: set EDMA first, then generate a rising request edge; demand-release service continues while the request stays high. Both channels support DMAM mode encodings 000 (memory-to-memory single step), 100 (memory-to-memory burst), 001/010 (I/O→memory / memory→I/O demand release), and 101/110 (corresponding single transfer). Byte/word width and source/destination increment/decrement/fixed addressing do not change the bank partition. Service simultaneous requests and terminal-count edges according to NEC's priority/mode behavior. /DMAAK is not asserted for memory-to-memory transfers. Test NMI abort with a deliberately configured interrupt edge.

## Arbitration, refresh and release timing

Assert HLDRQ HIGH and continue servicing the transfer already in progress. Wait for /HLDAK LOW before treating the bus as released. NEC gives bus-float-to-/HLDAK timing of T−50 ns, HLDRQ setup 30 ns, inactive request-low interval at least 1.5T, and request-release-to-acknowledge-release delay up to 3T+160 ns; use the timing diagrams and the configured CPU T, not a fixed number of host clocks. After releasing HLDRQ LOW, do not drive CPU data again until a valid CPU read and confirmed ownership.

The output-only L2/B0/T1 banks remain D during hold. Tri-stated address/control pins and still-active UART outputs are compatible with that direction. They are not external address-input buses to the V35S; the host observes them rather than driving them. B0 also contains TxD0/TxD1, so reversing it during hold would contend with those transmitters. If the purpose is electrical high-impedance measurement of each address/control pin, use a separate bench measurement; the host bus keepers can mask a released pin's voltage.

Refresh may be enabled during HOLD or HALT using RFM.HLDRF/HLTRF. For exclusive host data-drive experiments during HOLD, disable hold-refresh first. For refresh-during-HOLD tests, leave data banks Z, keep L2/B0/T1 D, and observe REFRQ plus address timing. RFM's reset value is FCh, so explicitly program it before arbitration tests rather than assuming refresh is disabled.

## GPIO and alternate-function transitions

To change a group from input to output: disable its host bank first, wait for translator output disable, program the CPU's direction/mode registers, then enable D. To change output to input: leave the host bank D or Z while programming the CPU to input, wait for CPU output release, then enable H with valid data. Do not change raw DIR while OE is enabled. Disabling the bank does not disable its bus keeper.

- **P0:** T2 H tests all eight inputs. T2 D tests all eight outputs. To observe CLKOUT, select P07's clock function and put P00–P06 in output mode (T2 D). Independent input P00–P06 alongside CLKOUT is excluded.
- **P2:** B2 and R0 both H for all-input GPIO, both D for all-output GPIO. In DMA/arbitration mode use B2 H and R0 D. Mixed arbitrary GPIO direction patterns are excluded as requested. Transition R0 from reset-input to peripheral-output before accepting /HLDAK, DMAAK or TC.
- **P1:** only P14–P17 are general-purpose outputs. P10–P12 remain input functions in B1. P13 can be /INTP2 input or /INTAK output, not general-purpose output. For P14–P17 all-input GPIO, T0/R2 are H and choose /INTP2 input and CTS0 input. For all-output GPIO, T0/R2 are D and choose /INTAK output plus CTS0 internal receive-clock output. Preload GPIO output latches before switching direction.
- **R2 peripheral combinations:** when R2 H, P13 must be /INTP2 input, P15/P16 input GPIO, and CTS0 UART CTS or external receive-clock input. When R2 D, P13 must be /INTAK output, P15/P16 output GPIO or TOUT/SCK0 outputs, and CTS0 the internally generated receive-clock output (channel 0 synchronous I/O mode, SCM0.SL/RSCK=1). Hold the receiver/transmitter in the intended disabled state when only GPIO/interrupt functionality is being tested. UART0 CTS input cannot run simultaneously with /INTAK or TOUT/SCK0 outputs on this board. UART1 does not share this restriction. These coordinated configurations preserve uniform GPIO tests and all requested DMA/arbitration modes.
- **T0 peripheral mode:** P14 INT/POLL and P17 READY are both inputs. With T0 D for GPIO-output tests, disable their peripheral-input functions; choose internal wait counts instead of external READY. INT and READY cannot remain active input functions in that configuration.
- **PT:** fixed VTH=VDD. R1 stimulates zero/full-scale digital inputs. This provides comparator logic tests at programmable fractions of VDD; it is not a calibrated analog threshold source. Prefer the midscale threshold for digital tests, not VTH×16/16.

## Clock and voltage

X1 pin 78 = RCLK, X2 pin 79 = TCLK. Drive complementary phases of one source, never unrelated clocks. NEC's illustrated external-clock circuit adds one inverter delay in the X2 path; qualify both waveforms at the CPU pins. Meet X1's 20 ns maximum rise/fall time and minimum 20 ns high/low widths. Use a 4–16 MHz source; PRC selects division by 2, 4 or 8, with CPU clock no faster than 8 MHz. Begin at 4 MHz input and a slow documented division for bench bring-up. This is not evidence that arbitrary single-stepping or a stopped external clock during normal execution is supported.

5V_SELECT is grounded, 3V3_SELECT is floating. Host control must select a 5 V DUT rail. All X/Y channels are unused; their pull configuration is immaterial to this design.

## Unused-bit drive rule for every profile

For every H (host → DUT) bank, all bits listed in `unused-bank-pins.csv` must be LOW together. Preload them LOW while disabled, before DUT power and before every direction change; mask GPIO and takeover patterns accordingly. Never drive tied unused bits to opposite levels. D and Z profiles must not add host output drive. This applies to all profiles in `reports/bank-profiles.json`; physical host behavior is not yet verified.
