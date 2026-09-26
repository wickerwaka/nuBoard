# HyperRAM top-layer escape trial — 2026-09-23

**Promoted 2026-09-24:** The locked, matched version is now the main-board
PCB, with schematic, pin-map CSV and displaced-signal FPGA constraints
synchronized. The trial chronology below is historical; see
[`hyperram.md`](hyperram.md) for the current project status.

**2026-09-24: the fast-group routing objective is now met in the
[saved matched candidate](../routing/hyperram-top/README.md).** CK and
DQ0–7 are approximately 11.000 mm; RWDS is 11.214798 mm. The verified
spread is **0.214807 mm**, all on F.Cu with zero vias. The historical
untuned measurements and incomplete tuning results below describe the
earlier trial, not the saved matched candidate. Power/pull-up work and
main-project synchronization remain unfinished.

## Result and limits

The requested F1–M3 rectangle contains **15 repurposable DDIO GPIOs**.
F1 is TEST_N and remains reserved; F2/F3/K3 are supply balls and H2/M2
are ground. Do not reassign these six balls.

A separate PCB trial demonstrates all **12 FPGA-to-HyperRAM connections
on F.Cu with zero signal vias**, using 0.0762 mm (3 mil) traces. All 15
displaced signals have replacement routes using F.Cu, In3.Cu and B.Cu.
These are geometric routing results, not FPGA timing closure.

**This pin map has not been applied to the project schematic, PCB, CSV or
FPGA constraints.** Their earlier provisional inner-ball allocation remains
in place. The trial is not fabrication-ready: the CS#/RESET# pull-up
branches, power/bypass connections and 0.381 mm length matching are
unfinished. Do not treat FPGA-to-RAM connectivity alone as completion of
each whole signal net.

The review board is `/tmp/hyperram-top-layer-review.kicad_pcb`, with matching
`.kicad_pro` and `.kicad_dru` files. This is a temporary review artifact,
not a production board or a schematic-synchronized project. No manufacturing
outputs were generated. The durable allocation and measurements are below.

## Proposed allocation

U2 trial placement: **F.Cu, (90.8, 75.0) mm, 90°**. The 6 × 8 mm package
faces the cleared west edge of U1. Keep the existing project footprint's
ball numbering; do not manually mirror its pads.

| Signal | U2 ball | U1 ball | Efinix GPIO | Untuned PCB length (mm) |
| --- | --- | --- | --- | ---: |
| DQ0 | D3 | K1 | GPIOL_87 | 8.573377 |
| DQ1 | D2 | L1 | GPIOL_68_CLK2 | 8.490534 |
| DQ2 | C4 | H1 | GPIOL_133 | 9.531956 |
| DQ3 | D4 | J1 | GPIOL_119 | 8.490534 |
| DQ4 | D5 | G1 | GPIOL_136 | 8.449113 |
| DQ5 | E3 | K2 | GPIOL_89 | 8.361245 |
| DQ6 | E2 | L2 | GPIOL_69_CLK3 | 8.249113 |
| DQ7 | E1 | M3 | GPIOL_67_CLK1 | 9.049113 |
| CK | B2 | M1 | GPIOL_65_CTRL3 | 10.531956 |
| RWDS | C3 | L3 | GPIOL_73_CLK7 | 11.214798 |
| CS# | A3 | G3 | GPIOL_141 | 15.382565 |
| RESET# | A4 | G2 | GPIOL_142 | 12.663326 |

The local `t120f484.csv` marks every proposed ball DDIO-capable. RWDS uses
a clock-input-capable ball. This allocation spans clock regions L3–L6;
unlike the previous allocation, it is **not all in L3**. Efinity must still
validate the RWDS clock distribution, capture phase, DDIO placement and
timing. The existing APS1604M controller is not a HyperRAM controller.

The ten fast lengths have an untuned spread of **2.965685 mm**, exceeding
the required **0.381 mm maximum spread**. A partial tuning experiment did
not meet the target and is not included in the review board. Matching is
PCB-only, as approved; no F324 package data or invented F484 compensation
was used. CS#/RESET# are outside the length-match group but still require
timing checks.

## Displaced signals

These replacements are unused DDIO GPIOs after releasing the earlier
HyperRAM allocation. The trial routes all fifteen; they do not need to
obey the HyperRAM's surface-only routing constraint.

| Existing signal | Old ball | Proposed replacement |
| --- | --- | --- |
| F_LCLK_EN | G1 | G4 |
| F_LCLK | G2 | G5 |
| DUT_ISOLATE | G3 | E5 |
| F_L11 | H1 | H4 |
| F_L10 | H3 | H6 |
| F_L14 | J1 | J4 |
| F_L13 | J2 | J5 |
| F_L12 | J3 | J7 |
| F_L16 | K1 | K4 |
| F_L15 | K2 | K5 |
| ~F_L1_OE | L1 | L4 |
| F_L1_DIR | L2 | L5 |
| F_L17 | L3 | L6 |
| F_L20 | M1 | N4 |
| F_L21 | M3 | M4 |

H3, J2 and J3 are unused in this proposed final signal allocation. They
were cleared to make the surface escape corridor available.

## Checks and remaining work

KiCad 10.0.6 DRC on the combined trial, with the main-board project/rules
and copper zones refilled, reports **no shorts, copper-clearance, hole
clearance or courtyard violations**. It reports nine length-skew
violations, six dangling-track warnings and 27 unconnected items.
All fifteen relocated signal nets are absent from the unconnected list.
Report: `/tmp/hr-relocated-drc.json`.

For comparison, the current source PCB checked during this session has
53 unconnected items and 15 violations (13 dangling-track, one silk
overlap and one silk-over-copper). This supersedes the earlier session's
baseline counts for this comparison, not the historical report in
`hyperram-validation.json`.

The trial's remaining unconnected items include both unfinished HyperRAM
power/pull-ups and existing unrelated connections. A plane refill also
exposes one additional +3.3V connectivity item. Therefore the trial must
not be copied over the main board as a completed layout.

Before applying this allocation:

1. Complete the pull-up branches on F.Cu and the local power/bypass layout.
2. Tune DQ[7:0], CK and RWDS to a maximum PCB spread of 0.381 mm; rerun
   DRC after tuning and inspect the reference-plane continuity.
3. Apply matching changes to the schematic, `fpga_pin_map.csv`, template
   and heartbeat pin constraints, and `validation/check_hyperram.py`.
   The existing audit deliberately still checks the current project map.
4. Re-export the netlist, compare all changed nets, rerun ERC/DRC and
   perform FPGA implementation/timing validation before signoff.
