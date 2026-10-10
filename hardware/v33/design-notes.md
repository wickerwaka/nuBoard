# NEC V33 daughter board

Routed daughter board based on `hardware/daughter-template`, for the confirmed
**NEC µPD70136L-16**, 68-pin PLCC, installed in a through-hole socket. Supply is
**5 V**. Supports host-emulated memory/I/O and HLDRQ/HLDAK bus arbitration.
No additional buffers are fitted, following the user's existing instruction.

The CPU is rated for 16 MHz. The actual operating clock has not been specified;
16 MHz operation through the host interface has not been timing-qualified.
ERC, PCB DRC, routing completeness and schematic/PCB parity pass. This is a
layout-verified design, not a hardware-tested assembly.

## Sources and package

NEC Electronics, *1991 16-bit V-Series Microprocessor Data Book*, V33 document
50049, retrieved 2026-09-13 from the [NEC databook archive](https://bitsavers.trailing-edge.com/components/nec/_dataBooks/1991_16_bit_V-Series_Microprocessor_Data_Book.pdf).

- `datasheets/nec-upd70136-v33-1991.pdf`: complete V33 section, original PDF
  pages 270–315. Section pages 1–2 give ordering and PLCC pinout; pages 3–8
  describe pins and operation; pages 9–10 give electrical/AC specifications.
- `datasheets/nec-68pin-plcc-pga-packages-1991.pdf`: original PDF pages
  1089–1090, package drawings. The L suffix is PLCC; R is PGA and GJ is QFP.
  Do not apply the PGA bottom-view numbering to the PLCC socket.
- `datasheets/assmann-plcc-socket-ass0981co.pdf`: [Assmann drawing ASS0981CO](https://www.assmann-wsw.com/uploads/datasheets/ASS_0981_CO.pdf), revision 11,
  2023-08-31. Selected socket **A-CCS 068-Z-T**, since no socket was specified.
  Its 68-pin hole pattern uses 2.54 mm grid spacing and 0.8 mm holes, with
  20.32 mm inner and 25.40 mm outer pad-grid dimensions; body is 30.80 mm square.

Project-local four-unit symbol `v33:uPD70136L` includes all 68 pins; the fitted
value is `uPD70136L-16`. Pin numbers were checked against the PLCC drawing.
`v33:PLCC-68_THT-Socket` is based on the installed KiCad PLCC-68 THT socket,
with the pad grid checked against the Assmann drawing. Its 31.05 mm body outline
allows clearance around the specified socket. Socket pin 1 faces the board's
TOP edge and is marked on silkscreen. Align the CPU pin-1 marking with it.

## Power, bias and assembly

NEC specifies 5 V ±10%. VDD pins 1, 19, 35 and 53 connect to VCC_TL; GND pins
2, 18, 36 and 52 connect to GND. C1–C4 respectively bypass those four VDD
pins: 100 nF ceramic, 50 V, 0805 SMD with enlarged HandSolder pads. This is a
chosen local bypass value, not a quoted NEC application requirement.

Only J1's VCC_TL power contact is used on the daughter board. The host schematic
shows all four VCC contacts supplied from the common switched VCC_DUT rail.
5V_SELECT (J1 pad 68) connects directly to GND; leave 3V3_SELECT (J1 pad 34) floating on the daughter board. No selection header or shunt is fitted. The host's 10 kΩ
pull-ups then produce GPIO20=0 and GPIO21=1 on the RP2040. Host firmware must
interpret this identification as 5 V and control the supply accordingly;
firmware implementing that behavior was not available for verification.
The select connection identifies the voltage; it does not itself set the regulator.

The host guarantees valid input states before powering on the DUT, so no
DUT-input default pull-up or pull-down resistors are fitted. All X0–X3 signals are unused.
Unused connector bits in used banks have the shared 47 kΩ pull-downs listed below. Establish these levels through the
host's B0/B1 banks before enabling DUT power and maintain valid levels while powered:

| CPU input | Host-driven startup level |
| --- | --- |
| INT | Low, inactive |
| /NMI | High, inactive |
| /CPBUSY | High, no coprocessor selected at reset |
| /CPERR | High, inactive |
| CPREQ | Low, inactive |
| RESET | High, reset asserted |
| /READY | High, wait requested |
| HLDRQ | Low, no takeover request |
| /BS8/BS16 | High, 16-bit bus |

The fitted host banks are [SN74LVCH8T245](https://www.ti.com/lit/ds/symlink/sn74lvch8t245.pdf)
with bus hold. NEC's VOH guarantee is 0.7 VDD at its specified test load, leaving
no additional CMOS-high margin against the host's 0.7 VCCI threshold. The scan's
IOH test-current unit is questionable (printed “-400 mA”); no corrected value
is assumed as a verified specification. Direct DUT-output compatibility with
the host bus-hold load is therefore **not guaranteed across specifications**.
No buffers were added, as requested. Check levels and edges on real hardware.

## Pin and bank assignments

`pin-map.csv` records all 68 physical pins, functions, electrical types,
connector names/pads and host-driven startup levels. `dut-pinout.csv` records the symbol pinout.
Every connected DUT pin uses a labelled schematic stub. Unused bits in used banks share per-bank 47 kΩ pull-downs; other unused connector
signals have no-connect markers. Prefix `/` below means active low.

| Bank/resource | Assignment | Normal direction |
| --- | --- | --- |
| T0 | T00–T07 = A0–A7 | DUT → host |
| T1 | T10–T17 = A8–A15 | DUT → host |
| T2 | T20–T27 = A16–A23 | DUT → host |
| L1 | L10–L17 = D0–D7 | By bus phase |
| L2 | L20–L27 = D8–D15 | By bus phase and byte lane |
| B0 | B03 INT, B04 /NMI, B05 /CPBUSY, B06 /CPERR | Host → DUT |
| B1 | B10 CPREQ, B11 RESET, B12 /READY, B13 HLDRQ, B14 /BS8/BS16 | Host → DUT |
| R0 | R04 HLDAK, R05 AEX, R06 /BUSLOCK | DUT → host, including takeover |
| R1 | R10 /BCYST, R11 /UBE, R12 BUSST1, R13 BUSST0, R14 R-/W, R15 M-/IO, R16 /DSTB | DUT → host normally; released in hold/reset |
| BCLK | CLK, pin 30 | Host → DUT |
| L0, R2, B2 | Unused | Disabled |
| All X0–X3; TCLK, LCLK, RCLK | Unused | Disabled where controllable |

Bank direction/enable applies to all eight bits. Drive all tied unused bits LOW whenever the bank drives host → DUT,
including takeover and startup. Host transceivers have A=FPGA, B=DUT: DIR=0 means
DUT → host, DIR=1 means host → DUT; /OE=0 enables, /OE=1 disables.
The separate R0 bank prevents host drive into outputs that remain driven in hold.

| Phase | T0/T1/T2 and R1 | L1/L2 | B0/B1 | R0 |
| --- | --- | --- | --- | --- |
| Power off / rail transition | Disabled | Disabled | Establish valid input levels before DUT power-on | Disabled |
| Reset asserted, rails stable | Receive or disabled; no drive | Disabled | Drive safe reset defaults | Receive |
| CPU memory/I/O read | Receive | Host drives only requested byte lane(s) during valid read window | Drive | Receive |
| CPU memory/I/O write | Receive | Receive requested lane(s) | Drive | Receive |
| Idle / turnaround | Receive | Disabled before any direction reversal | Drive | Receive |
| HLDRQ pending, HLDAK low | Receive | Continue normal CPU cycles | Drive HLDRQ high | Receive |
| HLDAK high, float interval elapsed | Receive; optionally drive released bus for takeover test | Disabled, or explicitly drive released data for takeover test | Drive | Receive only |
| Return from takeover | Stop all host bus drive before lowering HLDRQ; return to receive | Disabled until next valid CPU cycle | Drive | Receive |

Interpret A0 and /UBE with the cycle/status signals for lower/upper byte selection.
Odd-address byte accesses on the 16-bit bus use the upper lane. Dynamic 8-bit
cycles use D0–D7; leave L2 disabled for those cycles. Keep L1 and L2 independently
controlled so the host never drives an inactive lane that the CPU may be driving.
Host memory emulation must decode address extension AEX as specified by NEC,
not silently discard it; it is exposed on R05.

Assert HLDRQ and continue completing outstanding cycles, including /READY,
until HLDAK asserts. Do not infer ownership from elapsed clocks or /BUSLOCK
alone. Account for the CPU's maximum 50 ns bus float delay after the relevant
clock edge and host translator delays before enabling any host bus drive.
Release host address, control and data outputs before deasserting HLDRQ.
Keep R0 receiving throughout: HLDAK, AEX and /BUSLOCK are not takeover inputs.
The NEC scan shows a BUSLOCK overbar but inconsistent polarity prose; preserve
the pin designation and qualify lock behavior against observed CPU cycles.

## Clock and host timing

Use BCLK only. The -16 grade clock period specification is 62.5–500 ns
(2–16 MHz), with high and low times ≥25 ns and rise/fall times ≤5 ns.
Do not assume a running V33 accepts an arbitrarily slow or stopped clock;
its documented STOP behavior is a separate operating mode. CLK has a stricter
high threshold (0.8 VDD) than ordinary inputs (2.2 V), and a 0.6 V low limit.
The host [SN74LVC1T45](https://www.ti.com/lit/ds/symlink/sn74lvc1t45.pdf)
clock path must meet those limits at the socket.

After VDD becomes valid, allow at least 1 µs and hold RESET high for at least six
clock periods; satisfy its 10 ns setup / 15 ns hold around the specified falling
clock edge. Establish all host input levels before DUT power-on and hold them through reset. /READY
is active LOW; leaving it high inserts waits. The host-driven /CPBUSY high selects
no coprocessor at reset, while the exposed CP signals permit deliberate tests.

At the CPU pins the AC table specifies /READY, bus sizing and HLDRQ setup/hold
of 7/15 ns about their specified rising clock edge; read data needs 7/10 ns
about its specified falling edge. Address/control and data output delays extend
to 40 ns. Include FPGA logic, bank-transceiver propagation, PCB/socket delay,
clock skew and DUT setup/hold in the timing budget. At 16 MHz a half-cycle is
only 31.25 ns, so same-half-cycle host reaction cannot be assumed to meet timing.
Use wait states and a qualified host schedule. X0–X3 are not used for clocks or
handshakes; their TXS0108E open-drain path is unsuitable for this timing role.

## PCB and verification

The template connector's 136 pad positions, dimensions, drill sizes and board
outline are preserved. Placement puts address pins toward the top banks, data
pins toward the left banks, controls toward the bottom/right and a bypass
capacitor beside each supply group. Copper uses two layers, 0.20 mm routed
tracks and the specified 0.50 mm diameter / 0.30 mm drill via rule.
B.Cu has one continuous filled GND region with isolated-island removal after
the 0805 conversion. External vias connect the SMD ground pads to that plane;
DRC reports no isolated required ground connection. Signal clearances affect
the plane geometry;
clock edges and return-path performance require hardware qualification.

Validation artifacts are in `reports/`: ERC/DRC JSON, schematic and PCB PDFs,
and `verification.json`. Checks cover every DUT pin and schematic/PCB net,
local socket pad geometry, unchanged template mechanics, actual track/via
sizes, layer count, ground fill and zero unrouted connections. No ERC or DRC
violations or schematic/PCB parity issues remain. Schematic and both copper
layers were visually inspected. Fabrication files, firmware and physical
measurements are outside this deliverable.

## Shared pull-downs on unused bank pins

Each partially used bank has one 47 kΩ pull-down to GND shared by all of its unused connector bits. Each bank has its own net; no DUT-connected bits are tied together. Fully occupied and entirely unused banks have no added pull-down. See `unused-bank-pins.csv` for connector pad numbers.

| Bank | Unused connector bits tied together | Shared net | Resistor |
| --- | --- | --- | --- |
| B0 | B00, B01, B02, B07 | B0_UNUSED | R1 = 47 kΩ |
| B1 | B15, B16, B17 | B1_UNUSED | R2 = 47 kΩ |
| R0 | R00, R01, R02, R03, R07 | R0_UNUSED | R3 = 47 kΩ |
| R1 | R17 | R1_UNUSED | R4 = 47 kΩ |

Use 47 kΩ, 1%, ≥0.25 W 0805 SMD resistors on enlarged HandSolder pads. **Preload all tied unused bits LOW before enabling host → DUT, and keep them LOW in every host-driven phase**, including startup, reset, GPIO tests and bus takeover. Test patterns must mask these bits to zero. Opposite output levels on tied bits would short host output drivers together; the shared resistor does not limit that inter-output current. Set direction/data with the bank disabled and enable only after the prior driver releases. This is a host firmware requirement; no firmware was changed or bench-tested.

With the board disconnected from the host and unpowered, verify continuity among each listed group, approximately 47 kΩ from each group to GND, and isolation from other groups and used signal pins. On the host, verify that the tied bits are driven LOW together before power-up and through every direction transition. These measurements remain pending.

The updated layout passes ERC, DRC after ground refill, zero-unrouted checks and schematic/PCB parity. `validation/verify.py` also verifies exact shared-net membership and per-bank resistor values; `reports/unused-bank-pins.json` includes host output zero masks. `reports/pull-down-change-audit.json` confirms the existing component geometry and all other pad nets were preserved. Updated schematic and both copper-layer PDFs were visually reviewed.

Passive assembly was converted to top-side 0805 HandSolder footprints; see
`../daughter-template/passive-assembly.md` for assembly and part-selection notes.
