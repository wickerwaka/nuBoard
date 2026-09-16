# Motorola MC68030RC25B daughter board

Complete routed daughter board for the user-specified **Motorola MC68030RC25B, CPGA128, 5 V**. It supports host-emulated 8/16/32-bit ports, synchronous and burst reads, cache/MMU controls, interrupts, error/retry, and bus arbitration/takeover. The direct-interface preference from the preceding daughter boards is retained. **Physical bench, logic-level and timing qualification remain pending.**

Open `68030.kicad_pro`. The project includes its schematic, PCB, local CPU symbol/footprint, the unchanged local `nuBoard` libraries, and project-relative library tables. Passive symbols/footprints use the standard KiCad libraries. `pin-map.csv` covers every physical CPU pin; `bank-modes.md` is the required host contract. No host firmware is included.

## Primary documentation

| Saved file in `datasheets/` | Source / revision | Used sections |
| --- | --- | --- |
| `MC68030-1991.pdf` | Motorola MC68030/D, Rev.3, ©1991; [Motorola scan archive](https://ftpmirror.your.org/pub/misc/bitsavers/components/motorola/68000/68030_Data_Sheet_1991.pdf) | pp.27–29 signals; 34 DC; 36–40 AC; 47 CPGA pinout; mechanical drawings and ordering |
| `MC68030UM.pdf` | Motorola MC68030UM/AD Rev.2, third edition, ©1990; [NXP-hosted manual](https://www.nxp.com/docs/en/reference-manual/MC68030UM.pdf) | §5 signal types; §6 caches; §7 bus/lanes, arbitration and reset; §9 MMU; §12.8 power; §14 RC package |
| `MC68030RC.pdf` | [NXP RC package extract](https://www.nxp.com/docs/en/package-information/MC68030RC.pdf), manual pp.14-2 and 14-4, CASE789C-01 | Exact sparse grid, power pins and mechanical dimensions |
| `TI-SN74LVCH8T245.pdf` | Texas Instruments SCES637D, May2026; [manufacturer datasheet](https://www.ti.com/lit/ds/symlink/sn74lvch8t245.pdf) | Host bank CMOS thresholds and keeper loading |
| `TI-SN74LVC1T45.pdf` | Texas Instruments SCES515N, June2024; [manufacturer datasheet](https://www.ti.com/lit/ds/symlink/sn74lvc1t45.pdf) | Host clock translation |
| `TI-TXS0108E.pdf` | Texas Instruments SCES642L, November2024; [manufacturer datasheet](https://www.ti.com/lit/ds/symlink/txs0108e.pdf) | X/Y internal pulls, open-drain operation and rate limit |

URLs and SHA-256 hashes are recorded in `datasheets/sources.json`. The supplied marking is preserved exactly. Motorola's ordering table identifies RC as the ceramic PGA and 25 as the 25 MHz grade; the saved documents do not separately decode the trailing B into a verified silicon mask/errata identity. No different package or speed grade has been substituted. Record the physical mask marking during bench work if mask-specific errata are needed.

## Footprint, orientation and assembly

No matching MC68030 CPGA symbol or footprint was found in the installed libraries. The project-local eight-unit symbol includes all 128 pins, including all supplies and reserved pins. `dut-pinout.csv` is a row-by-row transcription of the Motorola drawing, including pin electrical types from manual table5-2. /RESET is bidirectional open-drain; /HALT is an input. /ECS, /OCS, /BG, /IPEND, /STATUS and /REFILL do not three-state.

The RC drawing is a **bottom view**. The footprint mirrors its columns to obtain the PCB component-side view, then places U1 at 180°. On the finished board, **A1 is at the upper-left corner**, marked by a square pad and A1 silkscreen. The row sequence is A,B,C,D,E,F,G,H,J,K,L,M,N; there is no I row. It is a sparse 13×13 grid with 128 populated sites, not a fully populated 169-pin array.

CASE789C-01 specifies 2.54 mm pitch, 34.04–35.05 mm body dimensions and 0.44–0.56 mm pin diameter. The footprint uses 1.50 mm pads and 0.80 mm finished holes, leaving nominal 0.35 mm annular rings and 0.12 mm radial clearance around a maximum-size CPU pin. Its body envelope allows the maximum package size. The design is for **direct through-hole mounting of the CPU package**. No socket has been selected or mechanically qualified; a socket option must independently match this sparse grid, tail dimensions, body clearance and host mating height. The CPU pin fit does not verify a socket's tails.

Keep components outside the CPU body area. C1–C15 are ceramic through-hole disc footprints, 5.00 mm lead spacing, body ≤5.0 mm diameter and ≤2.5 mm thickness; use ≥50 V parts. C16 is a 10 µF, ≥25 V aluminum electrolytic, 5 mm diameter, 2 mm lead spacing; observe its marked positive pin and confirm actual component height against the host assembly. R1/R2 are 47 kΩ, 1%, ≥0.25 W axial DIN0207, 7.62 mm lead spacing.

## Supply, decoupling and signal pulls

The specified rail is **5.0 V ±5%**, measured at the CPU: 4.75–5.25 V. The DC table lists 2.6 W dissipation at its stated condition; budget about 0.55 A at 4.75 V before external loading and host overhead. The host supply, connector and cooling must support the actual measured load.

All ten VCC pins join VCC_TL. All fourteen grounds join GND. Only J1 pad1, VCC_TL, supplies the daughter; the other three VCC contacts are no-connect. The actual host netlist confirms all four potential feeds are on the same switched VCC_DUT rail. A broad F.Cu supply pour distributes current; the CPU's total supply current is not intentionally funnelled through one long 0.20 mm track. Explicit routed links bridge pour subdivisions and connect local branches. Plane impedance, transient droop and current sharing remain bench measurements.

5V_SELECT, J1 pad68, connects directly to GND. 3V3_SELECT, pad34, is no-connect and unrouted. No jumper or pull-up is fitted to it. The host's pull-ups and sensing logic must interpret this as a 5 V board; the select connection does not itself set the regulator. See the host schematic for its power switch and sensing circuit.

| Power group | VCC pins | GND pins |
| --- | --- | --- |
| Address bus | C6, D10 | C5, C7, C9, E11 |
| Data bus | L6, K10 | J11, L9, L7, L5 |
| ECS/size/strobes/DBEN/CBREQ/RW | K4 | J3 |
| FC/RMC/OCS/CIOUT/BG | D4 | E3 |
| Internal logic/reset/status | H3, F2, F11, H11 | L8, G3, F3, G11 |

C1–C10 provide 100 nF ceramic bypassing at L6, K4, K10, H3, H11, F2, F11, D4, D10 and C6 respectively. C11–C15 add 330 pF C0G bypassing near C6, L6, K4, D4 and H3; C16 adds 10 µF bulk storage. This implements the manual §12.8 suggestion to combine low-, middle- and high-frequency capacitance, while fitting local ceramic decoupling at every power pin. Capacitor connections share the relevant common supply/ground nets; proximity and short return paths determine the physical local bypass function.

The five reserved pins D5, E12, F4, F10 and K5 are physically unconnected. No daughter pull establishes a default on a bank-connected CPU input; the host provides valid startup levels. The only daughter resistors are the required shared **47 kΩ pull-downs**: R1 on L00–L03 and R2 on R13–R14. `unused-bank-pins.csv` gives exact connector pads. These groups must never contain used signals or be driven to conflicting levels.

All eight X/Y channels are used. The host TXS0108E provides the pull-ups: its current datasheet specifies approximately 4 kΩ in HIGH and 40 kΩ in LOW, disabled when OE is LOW. At a 4.75 V rail, even the CPU /RESET's 20 µA input leakage causes only about 0.08 V loss with a nominal 4 kΩ high-state pull, comfortably above the CPU's 2.0 V VIH. Low-state pull currents from both rails are modest compared with the CPU's 10.7 mA reset sink test load. These nominal calculations establish why no additional X/Y pull is fitted; actual translator/FPGA sink levels and rise times must still be measured. The 1.2 Mbps open-drain ceiling and capacitance make these suitable for slow mode/arbitration/interrupt controls, not cycle acknowledgements.

## Electrical and timing limitations

The direct bank interface has **no guaranteed HIGH margin**: Motorola guarantees VOH≥2.4 V at IOH=400 µA, while the host SN74LVCH8T245 uses CMOS input thresholds around 0.7×VCCB (3.5 V at 5 V). The host's keeper can also require up to 0.9 mA overdrive, exceeding that CPU source-current guarantee. This limitation is stronger than a missing timing estimate: the datasheet DC bounds themselves do not establish compatibility. No corrective buffer or signal pull has been added. Passing ERC/DRC or a successful sample test does not create a worst-case guarantee.

CPU ordinary inputs accept VIH≥2.0 V and VIL≤0.8 V. Drive bank inputs with the host's correctly selected 5 V-side levels. X/Y remains sink-or-release only; all eight internal pull-ups must be available while relied on. /RESET must be observable when asserted by the CPU itself.

The 25 MHz grade is specified for **12.5–25 MHz**, not DC. LCLK alone drives E1. At the CPU pin, the clock period is 40–80 ns, high/low pulse widths use the datasheet's 19–61 ns limits at the stated measurement levels, and rise/fall must be ≤4 ns. The routed clock is 36.484 mm; no complete host/socket/board timing budget is claimed. Start at 12.5 MHz with asynchronous waits; do not assume a sub-12.5 MHz slow clock is valid.

For the 25 MHz column, address/data output delays can reach 20 ns, bus float delays 40 ns, data setup to the relevant falling edge is 2 ns, and synchronous data hold is 8 ns. Include the precise cycle-specific limits, translator propagation, FPGA latency and skew. A 25 MHz half-cycle is 20 ns, so a same-half-cycle response cannot be presumed feasible. Full-speed burst and takeover timing remain unqualified. Reset requires at least 520 clocks after valid supply, with the clock already stable; see `bank-modes.md` for phase-specific details.

## Routing and validation

The actual template outline is 99.06×99.06 mm. All 136 connector pad locations, orientations, sizes and drills, connector origin, and Edge.Cuts are preserved. U1 is centered at (150.99,96.00) mm, orientation180°.

Exactly two copper layers are used. All **600 routed segments are 0.20 mm**; all **nine through-vias are 0.50 mm diameter / 0.30 mm drill**. F.Cu carries the VCC_TL pour, B.Cu the GND plane. Five supply fill regions and eight ground fill regions are connected through routed copper, plated pads and vias; unconnected islands are removed. Every required power and ground pad passes connectivity checking. A local F.Cu path joins J11 ground to L8 around the existing control routes. Solid zone connections are used at C5/C7 supply pads, C8 ground, U1 D10 supply and U1 J11 ground where thermal geometry was unsuitable; these are explicit physical connections, not disabled DRC rules.

The project used installed KiCad10 and Freerouting1.9.0, with placement/assignment optimization over four CPU rotations. Local route and plane corrections followed the initial route. Konnect0.2.0 and available CLI capabilities were checked; board work used the explicit new project path without live edits to other open projects. The CLI identifies 10.0.6; its embedded pcbnew reports 10.0.6-rc2.

| Check | Result |
| --- | --- |
| Schematic ERC | 0 violations |
| DRC after refill | 0 violations |
| Unrouted connections | 0 |
| Schematic/PCB parity | 0 issues; independent node comparison passes |
| CPU pin and package audit | All128 pins, names/types, sparse grid and rotation checked |
| Bank audit | 20 profiles; four independent data-byte banks; always-driven outputs isolated |
| Shared pull-down audit | Correct two nets, exact unused pad membership and 47 kΩ values |
| Mechanical audit | Template connector and outline unchanged |
| Visual review | Final schematic, both copper layers, A1 marking, component clearance and pours reviewed |
| Hardware/firmware/timing | Not tested; pending |

Review exports are `reports/schematic.pdf` and `reports/pcb.pdf`. Machine-readable results are `reports/erc.json`, `drc.json`, `verification.json`, `bank-profiles.json`, `unused-bank-pins.json` and `netlist.xml`. Run `validation/verify.py` with KiCad's Python after regenerating the netlist and checks; it uses the repository template for preservation checks. `bench-test.md` supplies the pending qualification procedure. Fabrication ordering and firmware implementation are outside this deliverable.
