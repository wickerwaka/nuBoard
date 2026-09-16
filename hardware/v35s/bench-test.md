# V35S bench qualification — NOT YET PERFORMED

Status: pending physical board, CPU, host firmware and instruments. This is a test procedure, not measured evidence. The layout is verified; direct-drive bus-keeper and timing margins remain unqualified by user choice.

Record the full CPU marking/table suffix, socket and host translator markings, supply at both CPU VDD pins, ambient temperature, clock source/divider, probe loading and firmware revision with every result.

## Bring-up

1. With power off, check pin-1 orientation, no VCC–GND short, continuity of both CPU grounds/VDDs, 6.8 kΩ from reserved pin 9 to GND, and 15 kΩ from the tied IC group to VCC_TL. Confirm J1 pad 68 is grounded and pad 34 is isolated. Keep all unused X/Y outputs disabled. With the board disconnected from the host, verify the groups in `unused-bank-pins.csv`: continuity within each group, approximately 47 kΩ to GND, and isolation between groups and from used pins.
2. Configure valid host input levels as in `bank-modes.md`: RESET LOW, N/S HIGH for normal mode, DMARQ0/1 and HLDRQ LOW, interrupt inputs stable, UART inputs idle. Configure initial GPIO banks H and data banks Z. The host must distinguish initial GPIO P26 from actual HLDAK after PMC2 selects it.
3. Enable 5 V power with a suitable current limit for the host plus DUT. Check the DUT rail directly at pins 50 and 80; log transient droop/ripple and steady consumption. NEC's CPU operating-current limit is 120 mA at 8 MHz, excluding the host. Check reserved-pin bias voltages without driving those pins.
4. Apply complementary RCLK→X1 and TCLK→X2 using one source. Start at 4 MHz input; verify the configured PRC division. Measure high/low levels, rise/fall times, pulse widths and relative phase at the CPU pins. Meet 0.8×VDD high threshold on X1/X2 and 20 ns rise/fall/high-low limits. Keep RESET asserted for at least 30 ms after valid power/clock.
5. Release RESET and supply the normal-mode reset-vector fetch at FFFF0h. Capture the multiplexed address phases and selected byte lanes. Establish simple known CPU reads/writes before enabling DMA or advanced peripheral functions.

## Bus-keeper drive margin

The critical test is low→high drive by the CPU against a keeper previously set low. Test every usable DUT output and bidirectional bank pin with both walking and simultaneous patterns, especially D0–D15 and GPIO.

1. For a GPIO group, put the CPU pins in input mode and use H to drive zeros long enough to establish low keeper states. Disable OE, then program the CPU output latches and output mode according to the mode-transition contract. Enable D for observation only. Never enable H against an active CPU output.
2. Measure the DUT-side voltage as the CPU drives ones. A logic-analyzer pass alone is insufficient: capture the analog rising edge and stable level at the socket, and confirm it crosses the TI high threshold, including rail tolerance, before the host sampling instant. Note stalls or plateaus near the keeper switching point.
3. Repeat with initial keeper high and CPU low, 0x00↔0xFF, 0x55↔0xAA, walking bits and all-switching patterns. Perform equivalent data-bus tests using controlled CPU writes after a prior read drove the bus low. Observe address/control rising transitions after prior low cycles without enabling a host driver on output-only banks.
4. Check the selected part at nominal supply first; extend to intended operating voltage/temperature corners only within the verified part rating. Use enough repeated transactions to expose intermittent failures and record the count. This is sample characterization, not a guaranteed rating upgrade.
5. If any CPU-driven high does not reach the required level/timing, stop qualification of that operating condition. Do not mask the failure by adding pull resistors or driving against the CPU. Record the failing net, conditions and waveform for a later interface decision.

## DMA and arbitration

- For each DMA channel, test all six valid DMAM mode encodings, byte and word transfers, aligned/odd word addressing, source/destination fixed/increment/decrement, terminal count and retrigger behavior. Test both channels requesting service and NMI abort. Set EDMA before a rising DMARQ edge. DMARQ is active HIGH.
- In memory-to-memory modes, provide source reads with H data and observe destination writes with D data. In fly-by I/O↔memory modes the DUT releases data: host H supplies the external source while its model checks destination transfer strobes. Verify DMAAK and TC against the manufacturer's diagrams; DMAAK remains inactive in memory-to-memory transfers.
- Configure P2 alternate functions and bank directions before testing HLDRQ. Assert HLDRQ HIGH during idle, reads, writes and DMA; continue servicing the current transaction until HLDAK goes LOW. Observe address/control release with banks D and data Z. Release HLDRQ LOW after removing any optional host data stimulus; verify HLDAK rises and CPU ownership resumes without contention.
- Repeat with RFM.HLDRF disabled and enabled. With hold-refresh enabled, keep data Z and observe refresh cycles; do not assume permanently undriven buses throughout hold. Test HALT/refresh combinations and reset release separately.
- Electrical high-impedance tests require a controlled external measurement with the relevant transmitter/bank drivers disabled; host keeper voltages alone cannot prove the DUT output is high impedance. Do not reverse B0 to probe addresses because TxD0/TxD1 share that bank and remain outputs.

## GPIO, serial and security checks

Test uniform all-input/all-output patterns for P0, P2 and the four GPIO-capable P1 bits. Follow the coordinated P13/CTS0 settings in `bank-modes.md`; incompatible arbitrary peripheral combinations are excluded. Exercise UART1 and the supported UART0 or synchronous-clock R2 profiles separately. For PT use midscale threshold and digital low/high; do not claim analog threshold calibration from rail-only stimuli.

Keep N/S HIGH until the physical factory table is known. Then construct valid security-mode code for that table and separately test reset/interrupt sampling and BRKS/BRKN transitions. Record table identity with results.

## Results log

| Measurement | Result |
| --- | --- |
| Physical CPU/socket/host identification | Pending |
| VDD levels, current and ripple | Pending |
| Clock phase, levels, pulse widths, slew and operating rate | Pending |
| RESET and initial bus cycles | Pending |
| Low→high keeper overdrive on all tested nets | Pending |
| High→low drive and simultaneous switching | Pending |
| CPU memory/I/O, byte lanes and turnaround | Pending |
| DMA0/DMA1 complete mode matrix | Pending |
| Hold acquire/release, DMA interaction and refresh | Pending |
| GPIO/serial/comparator digital tests | Pending |
| Security table and mode tests | Pending |

Attach oscilloscope captures, logic traces and a machine-readable transaction/error log before changing the project's `hardware_tested` or `timing_qualified` status.

### Shared unused-bank pin qualification — pending

Check the host output masks against `unused-bank-pins.csv`. Every tied unused bit must be LOW before host → DUT enable and remain LOW through reset, CPU/DMA, GPIO and takeover transitions. No walking-bit, all-ones or other test pattern may set one of these tied unused bits. Scope the shared nets while changing direction and confirm there is no conflicting host drive. Record results before declaring these modes qualified.
