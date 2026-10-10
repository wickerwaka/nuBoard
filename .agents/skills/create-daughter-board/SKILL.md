---
name: create-daughter-board
description: Create a KiCad daughter PCB for a Device Under Test in the nuBoard repository, starting from hardware/daughter-template. Use when a user supplies a component and wants a new daughter board, including datasheet research, package selection, bank assignments, schematic capture, and PCB routing.
---

# Create a nuBoard daughter board

Create a complete, routed daughter PCB for the user's Device Under Test (DUT). Work in the nuBoard checkout containing `hardware/daughter-template`; locate that checkout before creating files if invoked elsewhere. Read applicable repository instructions and `README.md`.

Follow the stages below in order, revisiting assignments during placement and routing. Keep a design record in the new project's `design-notes.md` with datasheet sources, package and voltage decisions, final pin mapping, bank operating modes, and validation results.

## 1. Acquire the datasheet and confirm the part

Find the manufacturer's datasheet for the supplied component. Save the PDF in the new project's `datasheets/` and record its source URL, revision, and relevant pinout, supply, timing, and application sections. Prefer manufacturer documentation over distributor summaries. If the exact variant is unknown, preliminary family research can proceed while awaiting confirmation.

Ask the user for the exact manufacturer part number, package, and suffix they will physically use, unless they have already provided that information. Prefer a through-hole DUT version and explain the available through-hole choice when relevant; do not silently substitute it for the user's specified part. This DUT preference does not apply to resistors or capacitors, which use 0805 SMD packages. Ask about intended operating modes if they affect bidirectional pin assignments or voltage selection. Continue independent template inspection and research while waiting, but do not finalize package-dependent symbols, footprints, or wiring until the exact part is known.

## 2. Prepare the project, symbol, and footprint

Copy the entire `hardware/daughter-template` directory to `hardware/<component-slug>/`, using a non-conflicting name. Do not overwrite an existing project or edit the source template. Rename the `nuDaughter.kicad_pro`, `.kicad_sch`, and `.kicad_pcb` files consistently and update any project-specific references. Omit copied lock files, backups, and personal `.kicad_prl` state.

Keep `nuBoard.kicad_sym`, `nuBoard.pretty`, `sym-lib-table`, and `fp-lib-table` with their original library names and project-relative paths. Preserve the mezzanine connector pin numbers, footprint location and orientation, board outline, and mechanical constraints. Treat actual schematic and PCB files as authoritative if template metadata disagrees with them. The existing `hardware/68000` project can provide examples, but does not determine another DUT's wiring.

Find a matching KiCad symbol and footprint in installed libraries or authoritative part resources. Verify every symbol pin number, electrical type, power unit, footprint pad number, pitch, row spacing, hole size, body dimensions, and pin-1 orientation against the exact package drawing. Create missing assets in project-local libraries and register them using `${KIPRJMOD}` paths. Include all hidden or separate power pins. Do not treat a symbol or footprint with a similar name as verified.

Use the installed KiCad version and available schematic/PCB tools. This repository uses KiCad 10 files and configures Konnect through `scripts/konnect.sh`. Discover tool capabilities before relying on them; explicitly select the new project for live operations. Do not assume a PCB tool can edit schematics or autoroute. If required tooling is unavailable, finish supported work and report exactly what remains incomplete.

## 3. Determine supply and logic voltage

Determine whether the exact part should operate at 5 V or 3.3 V from recommended operating conditions, not absolute maximum ratings. Check all supply domains, input thresholds, output levels, and input tolerance against the host interface. If both voltages are supported, choose a compatible operating voltage and document why. If the part requires other or multiple supplies, resolve the additional circuitry or missing requirements before wiring it as a single-rail DUT.

The connector includes `VCC_TL`, `VCC_TR`, `VCC_BR`, `VCC_BL`, `3V3_SELECT`, and `5V_SELECT`. Encode the DUT voltage on the daughter board as follows:

| DUT supply | Connect directly to GND | Leave floating on the daughter board |
| --- | --- | --- |
| 5 V | `5V_SELECT` | `3V3_SELECT` |
| 3.3 V | `3V3_SELECT` | `5V_SELECT` |

Ground exactly one select signal; mark the other no-connect in the schematic and leave its PCB pad unrouted. Do not fit a selection jumper or add a pull-up to the floating signal. These voltage-identification connections are separate from the X0–X3 signal-pull policy in stage 8. Inspect `hardware/main-board/nuBoard.kicad_sch` for host-side sensing and VCC connectivity; do not tie supply inputs together without checking their source. Document the selected voltage and verify the select connections in both the exported netlist and PCB.

## 4. Plan pin assignments

Use the template's existing signal names:

| Resource | Names | Constraint |
| --- | --- | --- |
| Twelve 8-signal banks | Each side `T`, `L`, `B`, `R` has banks `0`, `1`, `2`, each with bits `0` through `7`; e.g. `T00`–`T07`, `T10`–`T17`, `T20`–`T27` | Enable and direction apply to an entire bank |
| Four clocks | `TCLK`, `LCLK`, `BCLK`, `RCLK` | Use one for a single required clock input; use multiple only if the DUT requires multiple clock inputs |
| Sixteen bidirectional sideband signals | `TX0`–`TX3`, `LX0`–`LX3`, `BX0`–`BX3`, `RX0`–`RX3` | Four per side, separate from the eight-signal banks; verify open-collector/open-drain compatibility and pull-ups |

Use the numbered X names in symbols, net labels, PCB nets, pin maps, and operating-mode notes. The former per-side X and Y signals are now X1 and X2; X0 and X3 are additional signals on former ground contacts. Do not ground those contacts or use X4. Read `hardware/daughter-template/interface-update.md` for the physical pin mapping. J1.102 and J1.136 are now GND, not NC; preserve all 14 connector ground contacts and compare all 136 mating pins against the current main-board connectors.

Describe direction explicitly as **host → DUT** or **DUT → host**. Group unidirectional pins by direction; do not mix conflicting directions in one enabled bank. For bidirectional or multiplexed pins, enumerate the intended operating phases, the DUT's drive/release behavior, and each bank's direction and enable state. Pins sharing a bank must have compatible direction/enable requirements in every phase, including reset and bus turnaround. Account for tri-state intervals to prevent contention. Keep an entire compatible bidirectional bus together where practical; otherwise split it across banks that switch together. Ask for missing usage information instead of guessing.

Use X0–X3 only for signals compatible with open-collector/open-drain operation. They are not interchangeable with push-pull bank signals. Inspect host pull-ups before adding more, and verify pull-up voltage, sink current, and rise-time requirements. Leave clocks unused when no clock input is required.

Record every DUT pin in a table: physical pin number, datasheet function, direction/drive type, assigned connector signal and pad, bank, net label, and pull or special handling. Include power, ground, and unused pins. Record bank enable/direction requirements separately for each operating phase, plus unused banks. Never assign one connector signal to unrelated DUT nets.

Choose banks near the corresponding physical DUT pins. Consider DUT orientation and permutations within compatible banks to minimize crossings, route length, and vias. Electrical and bank constraints take precedence over shorter routing.

## 5. Place the DUT and connect power

Place all DUT symbol units in the schematic, annotate them, and assign the verified footprint. Connect every power and ground pin. Prefer `VCC_TL`; use another VCC input when it materially improves routing, after verifying supply compatibility. Preserve the connector's ground connections. Add power flags only where justified by the actual supply source, rather than to hide wiring problems.

## 6. Add decoupling

Use **0805 (2012 metric) SMD capacitors and resistors with enlarged hand-solder pads**, not through-hole passives. Use these installed KiCad footprints:

- Capacitors: `Capacitor_SMD:C_0805_2012Metric_Pad1.18x1.45mm_HandSolder`
- Resistors: `Resistor_SMD:R_0805_2012Metric_Pad1.20x1.40mm_HandSolder`

Add ceramic decoupling capacitors at every DUT power input, using datasheet-recommended values and topology. When the datasheet gives no value, choose and document a suitable value, commonly 100 nF per supply pin. Include additional bulk or domain-specific capacitance when required. Select real 0805 parts with adequate voltage, dielectric, tolerance, and resistor power ratings; check effective ceramic capacitance at operating DC bias, especially for bulk capacitors. If the required characteristics cannot be met in 0805, resolve the exception with the user rather than silently changing package or value. Place each local capacitor close to its associated supply pin with a short ground return during PCB placement.

## 7. Label the DUT pins

Add electrically attached net labels on short wire stubs for every connected DUT pin, including power and ground. Use existing connector labels as canonical signal net names at the DUT, with readable datasheet function text where useful. A floating label or decorative text is not an electrical connection. Keep label scope valid between sheets if introducing hierarchy.

For datasheet NC pins, use no-connect markers and identify the function with text rather than creating an electrical net. For unused functional pins, follow the datasheet's required tie-off or permitted no-connect handling. Preserve active-low meaning in the pin mapping and annotations.

## 8. Add pulls for X0–X3 signals and unused pins in used banks

The host guarantees that DUT inputs are in valid states before powering on the DUT. Rely on host drive for reset, interrupts, arbitration, ready/wait, boot/mode, coprocessor, and other bank-connected inputs. Do not add pull-up or pull-down resistors to establish startup defaults, protect against disabled host banks, or overcome bus hold on these inputs. Record the required host-driven levels in the pin map and operating-mode notes instead. For unused functional inputs that need a defined level, assign host control or use a datasheet-permitted fixed tie-off.

For each used eight-signal bank with unused connector pins, tie all of that bank's unused pins together and connect the shared net to GND through exactly one **47 kΩ resistor per bank**. A used bank has at least one signal assigned to the DUT; unused pins are those with no DUT assignment in any supported mode. Keep each bank's shared net separate from every other bank and from all used signals. Do not fit this resistor on fully occupied or entirely unused banks. Record the unused pins, shared net, and resistor in the pin/bank mapping and BOM. Because these pins are tied together, require the host to drive all unused bits LOW whenever the bank drives host → DUT, including startup and direction changes; never drive tied bits to conflicting levels.

For X0–X3 open-collector/open-drain signals, inspect existing host and internal pulls first; add daughter-board pulls only when those are insufficient for the used X0–X3 net. Select values from the required idle level, compatible rail voltage, sink current, capacitance, and rise-time limits, and document the calculation. Do not add pulls to unused X0–X3 signals. All fitted resistors, including the per-bank 47 kΩ pull-downs, use the 0805 HandSolder footprint from stage 6.

## 9. Connect signals with labels

Connect the DUT to the assigned bank, clock, and X0–X3 signals using matching labels at both ends. Do not draw long direct wires between the DUT and the edge connector. Preserve distinct connector nets except for the intentional shared unused-pin nets required by stage 8; never short used bank bits to simplify the drawing. Check the exported netlist against the pin-assignment table, including symbol-to-footprint pad correspondence and each bank's shared 47 kΩ pull-down connection in both the schematic and PCB.

Remove unused template signal labels that would otherwise remain isolated. Connect unused pins in used banks to their stage 8 shared pull-down net without no-connect markers; mark other unused connector pins as appropriate. Run schematic ERC and address actual wiring errors before routing. Document justified residual warnings rather than suppressing checks globally.

## 10. Place and route the PCB

Update the new PCB from its schematic while preserving the template's connector and mechanical geometry. Place the DUT, decoupling capacitors, and pulls inside the usable area, allowing assembly and any selected socket clearances. Place 0805 passives on the top side with soldering-iron access, outside DUT/socket courtyards. Keep via holes outside the hand-solder pads to avoid solder wicking. Verify the actual passive footprint IDs, SMD pad types, and component ratings in the schematic, PCB, and BOM.

Use exactly two copper layers, `F.Cu` and `B.Cu`, with a connected GND copper plane/zone. Set trace width to **0.20 mm** and through-vias to **0.30 mm drill / 0.50 mm diameter**; verify those settings on actual routed objects, not just defaults. Retain compatible template clearance constraints. If current capacity or a package makes these dimensions unsuitable, explain the specific conflict and resolve it with the user rather than silently changing them.

Optimize DUT orientation and permissible signal assignments to reduce crossings before and during routing. Any assignment change must be reflected in the schematic, PCB nets, and pin/bank tables, then rechecked for every operating phase. Route decoupling loops and clocks carefully, maintain ground return paths, and use vias between the two layers where needed. Refill ground zones, remove isolated islands, and verify that all required ground pads connect to the plane; add stitching where needed for continuity.

Finish with schematic ERC, PCB DRC after zone refill, a zero-unrouted-connections check, schematic/PCB connectivity comparison, and visual inspection of labels, orientation, connector clearance, and the ground plane. Correct new errors and explicitly record any justified remaining warnings or tool limitations. Do not report a placed or partially routed board as complete.

Deliver the self-contained KiCad project and local libraries, datasheet, design notes with final pin/bank mapping and supply selection, and validation reports. Summarize the exact DUT/package, chosen voltage, output path, and any unresolved issue. Fabrication ordering and firmware implementation are outside this workflow unless requested.
