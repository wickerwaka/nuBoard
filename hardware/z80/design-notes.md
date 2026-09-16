# Z80 DUT daughter board

DUT: **Zilog Z84C0008PEG**, CMOS, 40-pin through-hole DIP, operated at **5 V / 8 MHz**. Includes host-emulated memory/I/O and BUSREQ/BUSACK testing. Created from `hardware/daughter-template`; connector geometry and board outline are preserved. No extra buffers are fitted, as explicitly requested after reviewing the host bus-hold loading.

Open `z80.kicad_pro`. The schematic, PCB, project-local libraries, `pin-map.csv`, datasheet and reports are in this directory. `pin-map.csv` is the final physical-pin-to-connector mapping; bank bits are permuted for placement rather than matching logical bus bit numbers.

## Supply and assembly

- Use **VCC_TL (J1 pad 1)** for the DUT supply. U1 pin 11 is VCC; pin 29 is GND. All connector ground pads join the B.Cu ground plane. The other three VCC contacts are unused on this daughter board.
- **5V_SELECT (J1 pad 68) connects directly to GND.** Leave 3V3_SELECT (J1 pad 34) floating on the daughter board. No selection header or shunt is fitted.
- The host schematic has 10 kohm pull-ups on both select inputs to `+3.3V_MCU`; RP2040 GPIO20 reads 5V_SELECT and GPIO21 reads 3V3_SELECT. All four host supply contacts share `VCC_DUT`, downstream of the VCCB power switch. Host firmware must interpret **GPIO20=0, GPIO21=1 as 5 V**, set its supply mux accordingly, and confirm the rail before enabling DUT power. Firmware is absent from this checkout, so that interpretation is a documented integration requirement, not a verified firmware behavior.
- U1 footprint: DIP-40 socket, 15.24 mm row spacing, 2.54 mm pitch, 0.8 mm finished drill in the KiCad footprint. Pin 1 is at the upper left with the notch toward TOP. Use a compatible socket; confirm the selected socket's tail dimensions against the drill before buying it.
- C1: **100 nF ceramic, 50 V, through-hole, 5.00 mm lead spacing**, body no larger than the 5 mm disc footprint. Located alongside U1 pin 11. This is the local bypass choice, not a value explicitly specified in PS0178.
- R1/R2/R4/R5: **10 kohm**, through-hole axial DIN0207, 7.62 mm lead spacing, 0.25 W. Pull INT/NMI/BUSREQ/RESET inactive high.
- /WAIT is driven by the host through B20; no bank-input bias resistor is fitted. The host establishes valid DUT input states before powering on the DUT.

## Banks and operating modes

D→H means DUT → host (`DIR=0` at the host transceiver); H→D means host → DUT (`DIR=1`). Enabled means the transceiver's **/OE=0**; disabled means **/OE=1**. These are transceiver pin levels, not unverified FPGA register encodings. Set output data and direction while disabled, then enable after the previous driver has released.

| Bank | Connected DUT functions | Ordinary execution | CPU reset | BUSACK takeover test |
| --- | --- | --- | --- | --- |
| L0 | A11–A15 on L03–L07 | D→H, enabled | Disabled | D→H to observe, or H→D only after CPU release |
| R1 | A0–A3 on R14–R17 | D→H, enabled | Disabled | Same as L0 |
| R2 | A4–A10 on R21–R27 | D→H, enabled | Disabled | Same as L0 |
| L1 | All eight data bits | H→D for reads/interrupt acknowledge; D→H for writes; disabled during turnaround and unserved cycles | Disabled | Disabled unless explicitly driving a released data bus |
| B1 | /MREQ, /IORQ, /RD, /WR on B10–B13 | D→H, enabled | Disabled | D→H to observe, or H→D only after CPU release |
| R0 | /HALT, /BUSACK, /M1, /RFSH | D→H, enabled | D→H observation is permitted; interpret only valid status | **D→H only**, remains enabled to observe BUSACK |
| B2 | /WAIT on B20 | H→D, enabled | Drive high before DUT power-on | H→D; keep inactive unless deliberately testing wait interactions |
| T0, T1, T2, L2, B0 | Unused | Disabled | Disabled | Disabled |

Unused bits of occupied banks are tied together per bank and pulled to GND through one 47 kΩ resistor; see the table below. Preload and maintain LOW on all tied unused host output bits whenever driving host → DUT. The CPU's address and bus-control outputs do not become CPU inputs during takeover: H→D here is only for exercising the released conductors, never for normal execution.

For L1 the physical bit order **L10…L17 = D4, D3, D5, D6, D2, D7, D0, D1**. Decode/encode this permutation in the host. Interrupt-acknowledge data requires its own cycle decode; do not use /RD alone to decide when to drive the bus.

### BUSREQ/BUSACK sequence

1. Assert /BUSREQ through BY while continuing the clock; allow the current machine cycle to finish. Keep all output-observation banks D→H. Finish any active host data response, then disable L1.
2. Wait for synchronized /BUSACK low and for the CPU's documented address/data/control release delays, plus host-translator and synchronization latency. Do not reverse a bank on the same instant that BUSACK is first observed.
3. Keep R0 D→H throughout. If exercising tri-state release, disable the chosen L0/R1/R2/B1/L1 banks, preload the test pattern with all tied unused bits masked LOW and H→D direction, wait for old-driver disable, then enable them. Drive only while BUSREQ remains asserted and BUSACK remains active.
4. Disable every takeover-driving bank and wait for the host outputs to reach high impedance **before releasing BUSREQ**. Restore address/control banks to D→H, leave L1 disabled until a valid response/write phase, then release BY and observe BUSACK deassertion. This avoids contention as the CPU resumes.

The host's bus hold retains a level on released conductors. A stable sampled value therefore does **not** prove the CPU is still driving; a tri-state test must use controlled takeover rather than inferring release from a floating input.

## Clock and asynchronous inputs

Only **LCLK (J1 pad 125)** drives U1 CLK. Other clocks remain unconnected. Set the host clock translator for A→B and generate a continuous, correctly shaped 8 MHz clock during execution; verify waveform levels, duty cycle and edges at U1, not only at the FPGA.

INT=LX, NMI=LY, BUSREQ=BY, RESET=RX use the X/Y open-collector interface. The FPGA must assert low or release, never contend by driving high. The host TXS0108E includes internal pull-ups; the four external 10k pulls provide inactive levels when it is disabled. Their parallel loading must be included in rise-time measurements. Keep these control changes slow enough for the TXS0108E open-drain limit (1.2 Mbps); stretch NMI and RESET and schedule BUSREQ early. **WAIT uses B20 instead of X/Y** so frequent wait-state control does not rely on that lower-rate interface. [TXS0108E datasheet](https://www.ti.com/lit/ds/symlink/txs0108e.pdf)

At power-up, stop CLK low and keep output-observation/data banks disabled. Configure supply selection, drive /WAIT high through B20, and assert /RESET through RX before enabling DUT power. The host guarantees valid input states before DUT power-on. Once power is valid, run enough clock cycles to meet reset timing before releasing /RESET. The X/Y pull-ups alone are not a power-on reset circuit. For shutdown, stop traffic and disable host drives before removing DUT power; avoid powering the CPU through signal pins.

## Electrical and timing review

The [Zilog product specification](https://www.zilog.com/docs/z80/ps0178.pdf), saved as `datasheets/zilog-ps0178.pdf`, is revision **PS017801-0602**, June 2002. Relevant printed pages: 5 (DIP pinout), 21–22 (signals), 23–28 (bus timing), 34–36 (CMOS DC/AC). Pin numbers were checked against the DIP drawing, including VCC=11, GND=29 and CLK=6. The selected CMOS grade supports 8 MHz at 5 V ±10%. At 8 MHz the clock period is at least 125 ns, high and low pulse widths at least 55 ns, and rise/fall times at most 10 ns. Clock-high must reach VCC−0.6 V; ordinary input-high is 2.2 V. Read-data setup is 30 ns; WAIT setup/hold is 50/10 ns. BUSREQ setup/hold is 40/10 ns; address/data float delay is up to 70 ns and control float delay up to 60 ns. Include host delay in addition to these CPU limits; use wait states when the host cannot meet the response budget.

The host clock translator is a [SN74LVC1T45](https://www.ti.com/lit/ds/symlink/sn74lvc1t45.pdf), powered from host 3.3 V and VCCB. Its lightly loaded CMOS output is appropriate for the CPU clock, subject to measurement at U1 after the host series resistor and PCB interconnect. This design has not undergone oscilloscope or hardware timing validation.

**Known direct-interface limitation, retained at the user's instruction:** the [SN74LVCH8T245](https://www.ti.com/lit/ds/symlink/sn74lvch8t245.pdf) has bus hold, a 5 V-side high threshold of 0.7×VCCB, and up to 0.9 mA bus-hold overdrive demand at the high supply corner. The CPU guarantees VCC−0.8 V high only at 250 µA source load, or 2.4 V at 1.6 mA. These bounds do not establish a guaranteed worst-case CMOS-high transition into the host bus-hold receiver. The design intentionally has no corrective buffers. Passing ERC/DRC does not establish this electrical margin; characterize the direct interface on the intended hardware.

## PCB and validation

Two copper layers, with a B.Cu GND plane; 0.20 mm tracks and 0.30 mm drill / 0.50 mm diameter vias. Address groups follow the left/right physical pin positions; the data bank follows the left DIP row. Placement preserves the socket courtyard and connector ring. Routing used local Freerouting 1.9.0 in single-thread mode, followed by KiCad zone refill and DRC.

See `reports/erc.json`, `reports/drc.json`, `reports/verification.json`, `reports/schematic.pdf` and `reports/pcb.pdf` for final checks and review drawings. Firmware implementation, fabrication ordering, and physical board testing are not part of this deliverable.

## Shared pull-downs on unused bank pins

Each partially used bank has one 47 kΩ pull-down to GND shared by all of its unused connector bits. Each bank has its own net; no DUT-connected bits are tied together. Fully occupied and entirely unused banks have no added pull-down. See `unused-bank-pins.csv` for connector pad numbers.

| Bank | Unused connector bits tied together | Shared net | Resistor |
| --- | --- | --- | --- |
| B1 | B14, B15, B16, B17 | B1_UNUSED | R6 = 47 kΩ |
| B2 | B21, B22, B23, B24, B25, B26, B27 | B2_UNUSED | R7 = 47 kΩ |
| L0 | L00, L01, L02 | L0_UNUSED | R8 = 47 kΩ |
| R0 | R01, R02, R04, R07 | R0_UNUSED | R9 = 47 kΩ |
| R1 | R10, R11, R12, R13 | R1_UNUSED | R10 = 47 kΩ |
| R2 | R20 | R2_UNUSED | R11 = 47 kΩ |

Use 47 kΩ, 1%, ≥0.25 W axial DIN0207 resistors with 7.62 mm lead spacing. **Preload all tied unused bits LOW before enabling host → DUT, and keep them LOW in every host-driven phase**, including startup, reset, GPIO tests and bus takeover. Test patterns must mask these bits to zero. Opposite output levels on tied bits would short host output drivers together; the shared resistor does not limit that inter-output current. Set direction/data with the bank disabled and enable only after the prior driver releases. This is a host firmware requirement; no firmware was changed or bench-tested.

With the board disconnected from the host and unpowered, verify continuity among each listed group, approximately 47 kΩ from each group to GND, and isolation from other groups and used signal pins. On the host, verify that the tied bits are driven LOW together before power-up and through every direction transition. These measurements remain pending.

The updated layout passes ERC, DRC after ground refill, zero-unrouted checks and schematic/PCB parity. `validation/verify.py` also verifies exact shared-net membership and per-bank resistor values; `reports/unused-bank-pins.json` includes host output zero masks. `reports/pull-down-change-audit.json` confirms the existing component geometry and all other pad nets were preserved. Updated schematic and both copper-layer PDFs were visually reviewed.
