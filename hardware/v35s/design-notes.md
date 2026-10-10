# NEC V35S daughter board

Complete routed KiCad daughter board for **NEC µPD70337L-8-xxx (V35 Software Guard), 84-pin PLCC, 5 V**, fitted in an **Assmann A-CCS 084-Z-T through-hole socket**. The user selected PLCC84; the physical marking and factory opcode-table suffix `xxx` remain unknown. This design uses the documented L-8 PLCC pinout and does not assume a particular security translation table.

Supports both DMA channels and all documented DMA transfer modes, HLDRQ//HLDAK arbitration, CPU memory/I/O bus transactions, and uniform-direction general-purpose-port tests. Some alternate peripheral functions must be configured together because the host controls direction per eight-bit bank; see `bank-modes.md`. No firmware is included.

**Layout verification passes; physical bench testing is pending.** The user explicitly chose a direct experimental interface despite the host bus-keeper drive-margin limitation. Neither bus-keeper operation nor full-speed timing is guaranteed by ERC/DRC. See `bench-test.md` before hardware qualification.

## Files and results

Open `v35s.kicad_pro`. Keep the local `nuBoard.*`, `v35s.kicad_sym`, `v35s.pretty`, and both library tables with the project. Capacitors/resistors use standard KiCad 10 symbols and footprints. No other daughter project is required to open the design.

| Item | Result / location |
| --- | --- |
| Schematic and PCB | `v35s.kicad_sch`, `v35s.kicad_pcb` |
| Every physical DUT pin | `pin-map.csv` (84 entries, connector signal and pad, direction/type, bank, net label, special handling) |
| Source pinout transcription | `dut-pinout.csv`; checked against NEC PLCC top view |
| Phase and mode requirements | `bank-modes.md` and `reports/bank-profiles.json` |
| Schematic ERC | Zero violations, `reports/erc.json` |
| PCB DRC after zone refill | Zero violations, `reports/drc.json` |
| Unrouted connections | Zero |
| Schematic/PCB parity | Zero issues; node-by-node comparison also passes |
| Mechanical preservation | All 136 connector pad locations/orientations/sizes/drills and Edge.Cuts unchanged |
| Routed object dimensions | 336 segments, all 0.20 mm; 21 through-vias, all 0.50 mm diameter / 0.30 mm drill |
| Ground copper | F.Cu and B.Cu; all required ground pads connected; 13 ground vias |
| Bank profiles | 35 checked profiles covering reset, CPU, byte lanes, DMA, hold, standby, GPIO and transitions |
| Visual review | Final schematic, front/back copper, silkscreen, pin-1 orientation, socket/connector/capacitor clearance, ground pours |
| Summary and netlist | `reports/verification.json`, `reports/netlist.xml` |
| Review exports | `reports/schematic.pdf`, `reports/pcb.pdf` |
| Bench evidence | Not performed; `bench-test.md` records procedure and pending results |

KiCad CLI reports 10.0.6; the embedded pcbnew build reports 10.0.6-rc2. Routing used installed Freerouting 1.9.0 after explicit discovery of Konnect 0.2.0 capabilities, then KiCad import, manual ground-return corrections, zone refill and final verification. Only the V35S project was modified for PCB operations; no live edits to another open project were used. `validation/verify.py` provides the geometry, node mapping, source-symbol/pad and bank-profile audit. It additionally uses the repository template for its preservation checks.

## Manufacturer sources

All documents are saved in `datasheets/`, with file hashes in `datasheets/sha256.json`. Acquisition date: 2026-09-13. Archive metadata creation dates are not NEC revision dates.

| Local PDF | Manufacturer document and source | Sections used |
| --- | --- | --- |
| `NEC-uPD70337.pdf` | NEC Electronics Inc., *µPD70337 (V35 Software Guard)*, identifier 50282; printed pp. 4G-1–4G-11. Original publication date not established. [NEC scan mirror](https://datasheet4u.com/pdf/553340/UPD70337.pdf) | 4G-1 ordering and reference to V35 electrical specifications; 4G-2 exact PLCC pinout and reserved-pin resistors; 4G-4–7 pin functions, clock/supply; 4G-8–11 normal/security operation |
| `NEC-uPD70330-70332-1991.pdf` | NEC *1991 16-bit V-Series Microprocessor Data Book*, V35 document 50006-2 (NECEL-870), original PDF pp. 496–575, section pp. 1–80. [Databook archive](https://bitsavers.trailing-edge.com/components/nec/_dataBooks/1991_16_bit_V-Series_Microprocessor_Data_Book.pdf) | pp. 2–7 pin/function descriptions; 24 refresh; 25–32 serial/DMA/port configuration; 33–36 waits, standby, reset registers; 37–39 DC/AC specifications; 40 clock circuit; 41–47 CPU/DMA/refresh timing; 48–50 reset/ready/hold/input timing |
| `NEC-84PLCC-package-1991.pdf` | Same NEC databook, original PDF p. 1093 / section 7-18; drawing P84L-50A3-1, 83YL-5806B (2/90) | PLCC body, lead pitch, pin-1 numbering/orientation |
| `NEC-uPD70330-1995-secondary.pdf` | NEC µPD70330/70330(A), U10170EJ8V0DS00, eighth edition, October 1995. [NEC scan mirror](https://datasheet4u.com/pdf/553338/UPD70330.pdf) | Secondary comparison only. Its IC-bias and oscillator options differ from the earlier documents; the specific V35S requirements take precedence here. It is not the µPD70332 document despite the archive search label. |
| `assmann-plcc-socket-ass0981co.pdf` | Assmann WSW, ASS 0981 CO rev11, 2023-08-31. [Manufacturer drawing](https://www.assmann-wsw.com/uploads/datasheets/ASS_0981_CO.pdf) | Sheet 2, 84-contact socket dimensions and recommended PCB hole grid |
| `TI-SN74LVCH8T245.pdf` | Texas Instruments, SCES637D, May 2026. [Manufacturer datasheet](https://www.ti.com/lit/ds/symlink/sn74lvch8t245.pdf) | Recommended voltages/input thresholds, electrical/bus-hold currents, output-enable/propagation timing |
| `TI-SN74LVC1T45.pdf` | Texas Instruments, SCES515N, June 2024. [Manufacturer datasheet](https://www.ti.com/lit/ds/symlink/sn74lvc1t45.pdf) | Host clock translation voltage levels and timing |

The 1991 V35 section is the explicitly referenced family electrical/functional basis. V35S page 4G-2 takes precedence over family pinout variants, particularly N//S pin 53 and reserved pin 9. Some legacy text copies contain errors (for example an 8-bit data-bus reference in a V35 hold description); the actual 16-bit V35 bus and waveform/function context are used. Critical request polarity was checked visually: **DMARQ0/1 and HLDRQ active HIGH; DMAAK0/1, TC0/1 and HLDAK active LOW**. NMI/INTP edge polarity is programmable; their startup levels are held steady.

## Package and mechanical choices

The NEC ordering table lists µPD70337L-8-xxx in PLCC84 and µPD70337GJ-8-xxx in QFP94. There is no listed DIP. The confirmed PLCC choice is supported through a socket rather than substituting another CPU package.

NEC's PLCC body is 30.2 ±0.2 mm square with 1.27 mm contact pitch. Assmann's A-CCS 084-Z-T socket body is 36.00 mm square, 8.28 ±0.15 mm high, with nominal 3.00 ±0.25 mm solder tails. The PCB hole grid is staggered on 2.54 mm pitch: 25.40 mm inner-row span and 30.48 mm outer-row span, using 0.80 mm plated holes. The selected KiCad socket footprint uses 1.4224 mm pads, giving 0.3112 mm nominal annular rings; its body/courtyard encloses the Assmann body. All 84 pad coordinates were compared against an independently derived top-view numbering pattern.

U1 pin 1 faces the board's TOP edge and is marked on silk. Align the PLCC mark to the socket mark. The footprint origin is pin 1 at (150.99, 80.76) mm, orientation 0°, with the socket centered inside the connector ring. Four orientations and compatible within-bank permutations were evaluated before routing. Socket body and capacitors do not overlap; all passives remain outside the socket courtyard so they do not require unverified clearance underneath the CPU/socket.

The source template is untouched. Its actual outline is 99.06 × 99.06 mm; the inherited nominal “100 × 100” template metadata is not the manufacturing geometry. The custom mezzanine connector remains at its original location and orientation.

## Supply, identification and decoupling

The chosen supply is **5 V**, justified by NEC's DC and AC operating specifications at **5 V ±10%**. The standard qualified temperature range in the 1991 specification is −10 to +70 °C; do not infer extended-temperature qualification from an unknown device suffix. No separate core or negative rail is required.

- U1 VDD pins 50 and 80 connect to VCC_TL. GND pins 42 and 77 connect to GND.
- VTH pin 76 connects to VCC_TL, making comparator thresholds programmable fractions of VDD. R1-bank inputs are digital stimuli, not an external analog test source.
- C1 bypasses pin 80; C2 bypasses pin 50; C3 bypasses VTH pin 76. Each is a 100 nF, ≥50 V 0805 ceramic SMD capacitor with enlarged HandSolder pads. X7R is preferred. The 100 nF local bypass value is a design choice, not a quoted NEC component value. Short local power routes were placed before autorouting.
- R1 is 6.8 kΩ from reserved pin 9 to GND, within NEC's 5–10 kΩ requirement. R2 is 15 kΩ from the tied IC pins 3/49/75 to VCC_TL, within NEC's shared 10–20 kΩ requirement. Both use 0805 SMD HandSolder footprints; select parts rated ≥0.25 W. The user explicitly authorized these required reserved-pin resistors as an exception to the skill's X0–X3-only pull policy. They are not bank-input defaults.
- No DUT-input default pull resistors, selection header or shunt is fitted. Unused bits in used banks have shared 47 kΩ pull-downs as listed below. Every X0–X3 pin is unused and has no daughter-board pull resistor.
- **5V_SELECT, J1 pad 68, is connected directly to GND. 3V3_SELECT, J1 pad 34, has a schematic no-connect and an unrouted PCB pad.** No other voltage-select connection is grounded.

The authoritative host netlist shows J5/J6/J7/J8 pin 34 on the common switched VCC_DUT rail. Only the daughter VCC_TL feed (J1 pad 1) is used. The other three VCC inputs are no-connect. Host R39/R40 are 10 kΩ pull-ups to +3.3V_MCU; the 5 V identification pulls RP2040 GPIO20 low and leaves GPIO21 high. Firmware must interpret that pattern and select the supply; grounding the identification pin does not itself regulate voltage.

At 8 MHz CPU clock, NEC specifies up to 120 mA operating supply current. With 35 µm copper, a 0.20 mm trace has approximately 2.5 Ω/m resistance; even 60 mm of feed gives about 18 mV drop at 120 mA. This is compatible with the specified geometry and supply tolerance. Confirm actual copper weight and assembled rail drop during bring-up.

## Logic interface and accepted limitation

NEC guarantees VIL ≤0.8 V, VIH ≥2.2 V on most inputs, and VIH ≥0.8×VDD on RESET, NMI, X1 and X2. DUT VOH is at least VDD−1 V at −0.4 mA, and VOL at most 0.45 V at 1.6 mA. The host's 5 V bank/clock outputs meet these thresholds for the stated small input loads. The host's 5 V data-input thresholds are 0.7×VCCB high / 0.3×VCCB low: the NEC high and low levels provide static voltage margin at the specified test currents (allowing for the small switched-rail drop).

The **bus-keeper current margin is not guaranteed**. SN74LVCH8T245 data inputs have active bus hold even when OE is disabled. TI specifies up to 900 µA low-to-high overdrive current at the 5.5 V corner; NEC guarantees its high level at only 400 µA source current. A previously low keeper may therefore resist a CPU-driven high. The stronger NEC low-state sink rating does not establish the missing high-drive margin.

The user chose the direct experimental interface with this limitation documented and to be bench-tested. No buffers, pulls to defeat bus hold, or host-board alterations were added. Good ERC/DRC results and passing logic-level calculations do not establish keeper overdrive capability. A successful room-temperature sample test also does not create a process/voltage/temperature guarantee.

## Clocks, routing and ground

The V35S description and the referenced 1991 external-clock diagram use opposite phases on X1 and X2. X1 pin 78 is RCLK; X2 pin 79 is TCLK. These are two phases of one clock, not independent oscillators. The host must generate/invert them coherently and meet the rise/fall, pulse-width and phase requirements at the CPU pins. LCLK/BCLK are unused. PRC selects divide-by-2/4/8; remain at or below the documented 8 MHz CPU maximum. Begin with a 4 MHz source and slow supported division for bench work.

RCLK route length is 53.182 mm and TCLK is 35.432 mm. They are not a matched differential pair. The unequal board flight time is small relative to the inverter-delay clock scheme shown by NEC, but translator skew and real waveforms still require measurement. No full-speed timing qualification or firmware timing implementation was performed.

Exactly two copper layers are used, F.Cu and B.Cu. Every actual routed segment is 0.20 mm wide and all 21 vias are 0.50/0.30 mm through-vias. Thirteen vias connect GND; eight carry other nets, including passive transitions replacing plated component holes. F.Cu has one connected GND fill region. B.Cu has three local fill regions joined through plated pads, the F.Cu ground network and stitching; unconnected copper islands are removed. All ground pads pass the connectivity check. U1 pin 77 retains its solid zone connection and local F.Cu ground return because neighbouring power/clock escapes leave insufficient space for useful thermal spokes at that pin. Thermal checks remain enabled.

The output-only L2/B0/T1 banks remain DUT→host during arbitration. B0 includes TxD0/TxD1, which must not be driven by the host when address outputs float. This supports observing the bus handoff; per-pin physical high-impedance characterization requires the bench procedure. Data banks L0/L1 can be disabled and then driven under a valid read or explicitly granted/released bus interval. Full DMA fly-by ownership and GPIO transition rules are in `bank-modes.md`.

## Remaining physical work

No assembled board, physical V35S, host firmware or measurement instrument was connected to this session. Fabrication, assembly, keeper-drive measurements, clock qualification and DMA/arbitration execution have **not** been performed. `bench-test.md` is a ready-to-run qualification procedure with all measurements marked pending. Read the physical part suffix before security-mode tests; normal mode can be selected independently, but encrypted test code requires the correct factory translation table.

## Shared pull-downs on unused bank pins

Each partially used bank has one 47 kΩ pull-down to GND shared by all of its unused connector bits. Each bank has its own net; no DUT-connected bits are tied together. Fully occupied and entirely unused banks have no added pull-down. See `unused-bank-pins.csv` for connector pad numbers.

| Bank | Unused connector bits tied together | Shared net | Resistor |
| --- | --- | --- | --- |
| B0 | B00, B01 | B0_UNUSED | R3 = 47 kΩ |
| B2 | B23, B24, B25, B26, B27 | B2_UNUSED | R4 = 47 kΩ |
| R0 | R00, R01, R02 | R0_UNUSED | R5 = 47 kΩ |
| R2 | R24, R25, R26, R27 | R2_UNUSED | R6 = 47 kΩ |
| T0 | T00, T01, T02, T03, T04, T05 | T0_UNUSED | R7 = 47 kΩ |
| T1 | T10, T11, T17 | T1_UNUSED | R8 = 47 kΩ |

Use 47 kΩ, 1%, ≥0.25 W 0805 SMD resistors on enlarged HandSolder pads. **Preload all tied unused bits LOW before enabling host → DUT, and keep them LOW in every host-driven phase**, including startup, reset, GPIO tests and bus takeover. Test patterns must mask these bits to zero. Opposite output levels on tied bits would short host output drivers together; the shared resistor does not limit that inter-output current. Set direction/data with the bank disabled and enable only after the prior driver releases. This is a host firmware requirement; no firmware was changed or bench-tested.

With the board disconnected from the host and unpowered, verify continuity among each listed group, approximately 47 kΩ from each group to GND, and isolation from other groups and used signal pins. On the host, verify that the tied bits are driven LOW together before power-up and through every direction transition. These measurements remain pending.

The updated layout passes ERC, DRC after ground refill, zero-unrouted checks and schematic/PCB parity. `validation/verify.py` also verifies exact shared-net membership and per-bank resistor values; `reports/unused-bank-pins.json` includes host output zero masks. `reports/pull-down-change-audit.json` confirms the existing component geometry and all other pad nets were preserved. Updated schematic and both copper-layer PDFs were visually reviewed.

Passive assembly was converted to top-side 0805 HandSolder footprints; see
`../daughter-template/passive-assembly.md` for assembly and part-selection notes.
