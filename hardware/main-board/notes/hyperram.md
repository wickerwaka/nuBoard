# HyperRAM main-board integration — routing matched, power unfinished

The locked matched layout was promoted into `nuBoard.kicad_pcb` on
2026-09-24. The schematic, `fpga_pin_map.csv`, template/heartbeat
displaced-signal constraints and allocation checker are synchronized.
The original project settings and local library registrations were retained;
they already matched the candidate settings.

U2 is IS66WVH8M8BLL-100B1LI, on **F.Cu at (90.8, 75.0) mm, 90°**.
U2 and all **585 HyperRAM signal segments are locked**. CK, DQ0–7 and
RWDS have complete F.Cu-only pad-to-pad routes with **zero vias** and a
maximum PCB-only length spread of **0.214807 mm (8.457 mil)**, below
the 0.381 mm limit. CS#/RESET# FPGA-to-RAM routes are also F.Cu-only.

**The board is not fabrication-ready.** HyperRAM power/bypass and
CS#/RESET# pull-up connections remain unfinished, along with existing
unrelated open connections. The FPGA template and heartbeat no longer have any
PSRAM logic; they drive only HR_CS_N and HR_RESET_N (inactive) to keep U2
deselected. No HyperRAM controller or FPGA timing closure is included.

## Current pin allocation

| Signal | FPGA ball | RAM ball | PCB length (mm) |
| --- | --- | --- | ---: |
| DQ0 | K1 | D3 | 10.999998 |
| DQ1 | L1 | D2 | 10.999991 |
| DQ2 | H1 | C4 | 11.000001 |
| DQ3 | J1 | D4 | 11.000009 |
| DQ4 | G1 | D5 | 11.000003 |
| DQ5 | K2 | E3 | 11.000000 |
| DQ6 | L2 | E2 | 10.999998 |
| DQ7 | M3 | E1 | 10.999998 |
| CK | M1 | B2 | 11.000000 |
| RWDS | L3 | C3 | 11.214798 |

CS# is U1.G3 to U2.A3; RESET# is U1.G2 to U2.A4. All twelve FPGA balls
are DDIO-capable. RWDS uses clock-capable L3. The fast group spans clock
regions L3–L6; validate actual clock distribution and DDIO timing in Efinity.
F1 remains TEST_N, and the F1–M3 power/ground balls were not repurposed.

Fifteen existing signals were moved to the replacement balls listed in
[the relocation table](hyperram-top-layer-plan.md#displaced-signals).
Their replacement routes pass copper-clearance checks and have no
unconnected items. The original PSRAM connections remain removed.

The pre-promotion matched reference remains in `../routing/hyperram-top/`.
Its README describes the tuning geometry. The authoritative editable
project is now the main-board directory, not that reference snapshot.

## Symbol, package and power

`HyperRAM.kicad_sym` contains the exact BLL/B1 part, registered in the
project library table. `nuBoard.pretty/ISSI_TFBGA-24_6x8mm_P1.0mm.kicad_mod`
has a 6×8 mm body, 1 mm pitch and 24 balls with A1 absent. The 0.40 mm
copper lands with 0.05 mm mask expansion are an NSMD land-pattern choice;
confirm assembly-process requirements before release. No unverified 3D
model is attached.

The BLL device runs from 2.7–3.6 V and uses one CK at up to 100 MHz.
B1 is RFU, not CK#. A2/A5/B1/B5/C2/C5 are left disconnected. VCC=B4,
VCCQ=D1/E4 and VSS/VSSQ=B3/C1/E5. These assignments and the body/ball
dimensions were checked against ISSI Rev. B2 pp. 41, 47–48:
[manufacturer URL](https://www.issi.com/WW/pdf/66-67WVH8M8ALL-BLL.pdf),
[ISSI-authored PDF mirrored by LCSC](https://datasheet.lcsc.com/datasheet/pdf/758baa89b3f0c85f736a6e0a7bb4cd5c.pdf).
The manufacturer's URL returned an access-block page during this work.

## Accepted PCB-only 15 mil matching

On 2026-09-21 the user approved PCB-only matching because F484 package
lengths are unavailable. The requirement is a **maximum PCB length spread
of 0.381 mm**, not ±0.381 mm per signal. The fast group is DQ[7:0], CK and
RWDS. CS#/RESET# are excluded from that group but still need their timing
requirements met. IC package interconnect is excluded from this acceptance
criterion; its skew remains unknown.

`nuBoard.kicad_dru` contains the 0.381 mm group skew constraint. The former
missing-package-length assertion has been removed. Leave pad-to-die
compensation unset on both endpoints for this PCB-only matching basis.
KiCad adds any configured pad-to-die lengths to net lengths;
see [the PCB Editor documentation](https://docs.kicad.org/master/en/pcbnew/pcbnew.html).

The Efinix pinout workbook and Packaging User Guide v5.3 do **not** supply
the required per-ball substrate/bond-wire lengths. On 2026-09-21 the user
supplied `~/Downloads/T55-T85-T120-F324-package-netlength.xlsx` and reported
that no F484 lengths exist. The supplied workbook identifies **F324**, not
F384, in both its `T120 T85 T55 F324` sheet name and its revision history
(v0.1, initial preliminary release). It contains `NetLength(mm)` and
`Delay(pS)` columns, but no F484 sheet.

Those values cannot be transferred to F484 by matching ball numbers or
GPIO names: they describe a different package interconnect. They are not
a demonstrated upper bound on F484 skew either. No values were imported,
guessed from ball position or substituted with zero; the evidence CSV and
FPGA pad-to-die fields remain unset.

This supersedes the original package-inclusive matching requirement.
The blank `hyperram-package-lengths.csv` is retained as a record of the
unavailable data; it is no longer a signoff prerequisite. Do not introduce
package compensation without also revisiting the matching basis.

For geometric length matching, tune so that
`max(Lpcb + Lvia) - min(Lpcb + Lvia) <= 0.381 mm` across the group.
Include the actual via travel through the board stackup. Prefer consistent
layers and transition counts: equal physical lengths across different
dielectrics do not establish equal flight times. IC package skew remains
outside this PCB matching check.

PCB matching alone does not establish 100 MHz operation.
The B1 read strobe is edge-aligned: the controller needs a justified capture
phase/delay. Validate the RWDS clock path, bidirectional turnaround,
DDIO placement and input/output timing with Efinity for T120F484C3. No
Efinity implementation or timing closure was performed in this change.

## Verification after promotion

The exported schematic netlist changes only the intended 27 U1 endpoints
(12 HyperRAM plus 15 displaced signals); all other connected schematic
nets are preserved. ERC retains one pre-existing undriven-power violation.
The promoted PCB has zero schematic-parity issues and no length-skew,
shorting, copper-clearance or courtyard violations. Six dangling-track
warnings and 27 unconnected items remain outside the completed fast group.

Current reports: `hyperram-main-drc.json` and
`hyperram-main-validation.json`. The older `hyperram-validation.json`
describes the original provisional inner-ball allocation, not this layout.

Repeat from the repository root, using KiCad's Python for the surface audit:

```sh
kicad-cli sch export netlist -o /tmp/hyperram.net hardware/main-board/nuBoard.kicad_sch
kicad-cli pcb drc --refill-zones --schematic-parity --format json -o hardware/main-board/notes/hyperram-main-drc.json hardware/main-board/nuBoard.kicad_pcb
python3 hardware/main-board/validation/check_hyperram.py --netlist /tmp/hyperram.net --drc hardware/main-board/notes/hyperram-main-drc.json
python3 hardware/main-board/validation/check_hyperram_surface.py hardware/main-board/nuBoard.kicad_pcb --drc hardware/main-board/notes/hyperram-main-drc.json
```

The `check_hyperram.py --signoff` gate still fails on remaining whole-board
opens; the ten-signal surface/length audit passes. Neither replaces FPGA
timing or signal-integrity validation.

The project files from immediately before promotion are recoverable from
`/tmp/nuboard-promote.OlAi3C/before.zip`. Existing unrelated work was
preserved. Historical production exports were not regenerated.
