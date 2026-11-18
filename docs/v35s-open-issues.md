# V35S core v2: open issues (2026-11-18, tree at acaf86f)

State: refresh-off corpus 30,181 of 30,536 exact; every program gate equal except the two
period-only differences (f4_tm, f4_tout) and five fuzz programs (f5n 3, f5v 2); 17 ns met at
+3.565 / +3.413 / +3.268 on seeds 1 to 3. The record is `docs/v35s-core-v2.md`; measured
rules are `validation/v35s/qprobe/RESULTS.md` (Q1 to Q134).

## 1. Awaiting a ruling

| # | Item | Runs | What is asked |
|---|---|---|---|
| 1 | The store's releasing word executes on the first clock of the write's last byte cycle (Q127; work order 22 C1). Functional: for three clocks an interrupt replaces a different instruction. | 24 corpus | One new bus-to-sequencer bit ("the second byte cycle of an EU pair starts now"). Raises the interface budget. |
| 2 | The second wait word kind `J` (Q120, Q128; C2, C3): the last string element's wait and CALL near's push at odd SP run four clocks from the pair's second cycle. No mechanism: two cases in the same bus state differ. | 88 corpus, 22 socket | Build as measured, or keep as a described difference. Depends on item 1's bit. |
| 3 | PUSH r16's first word changed to the model's `e ro bi` shape (landed in 04c3a30, outside the order's items; 28 runs lost without it). | - | Accept or revert. |
| 4 | Free codes of the word-kind port given meanings: flush+alt (the strict word), flush+alt without bi (the bus-idle-next mark), disp+bi (the popping bus-idle word). Port width and budget unchanged. | - | Accept as covered by the earlier free-code acceptance, or not. |
| 5 | The lead counter's `ew` compensation (starts at 2 when the E word waited for the staging slot alone) in place of silicon's pop on the delivery clock. Removing the slot's lag lengthens the loader's delivery path. | 151 gained by it | Accept as a described difference, or order the faithful build. |
| 6 | The bus-idle-next mark looks one microword ahead inside a routine (assembler-computed, not the next opcode). | 41 gained | Confirm this is within the 2026-11-09 rule. |
| 7 | Spec 18 A2 (the third-last-clock commit word) and its +2.0 ns line. All seeds are over the line again; A2 costs about 0.9 ns on seed 1. | several hundred | Nothing needed unless the line is to change. |
| 8 | 4S head's seventh-word bus-idle act (2 runs). Not built; the head is exact without it. | 2 | Close as not built. |

## 2. Interrupt rebuild (held)

The rework to work order 19 is not landed (hand-back in the session scratchpad, against
9614ced; it must be re-based). Open in it:

- f4_dma came out one instruction early; the RTL's DMA transfer is an EU routine, silicon
  takes the transfer at an instruction boundary with its write 11 clocks behind it (Q131).
  Ruling asked earlier: DMA as stolen bus cycles, or drop f4_dma as the landing condition.
- The scan lattice is 3 clocks late (sim 5/6 against silicon 2/3 mod 16). Round 26 reads
  EI as restarting the scan on its first word (E1 + 24; 87 of 92 runs). Being built on the
  main tree's controller now (work order 22 C6).
- The pop reaches the interrupt controller on the unused code of the `x_nb` port (ruling).
- The vector read is 1 to 3 clocks late in fetch-limited trains; the byte wait at the take
  is held until timing allows; f4_tm differs in writes under the rework.

## 3. In build now (no ruling needed)

Work order 22 C4 to C6: the `CH_EPRI` build fault behind MOV [d16],imm16 (9 socket runs),
EI's scan restart, MOV [d16],AL / AW with the request word second (only if f4_dma stays
equal; round 26 infers that its write 711 is the lattice, not the store: untested).

## 4. Known differences (ruled or under the 20-run line)

- The bit-field head's second commit-word kind (spec 20 A6): 112 runs, ruled not built.
- CVTDB behind an EU cycle; the OUT + CVTBD / CVTDB datum (ruled 2026-11-13).
- JMP / CALL far's request word without a cycle: 16 runs.
- 109 corpus runs the reading model does not read either: no state over 20 runs (largest:
  SHL [m],CL behind a marker, 15).
- 6 miss rows the tools do not parse.
- Round 26: two EI cells take the request 20 clocks early (unexplained, not built).

## 5. Unchecked or unproven

- "Checker silent" was not a real check before 20a078b (the replay dropped the simulator's
  stderr). It is checked from that landing on; the overseer has not repeated the builder's
  inversion test that proves the lines reach the log.
- Quartus 17.1: warnings at v35_loader.sv 376 / 382 / 470 / 471 (don't-care struct fields,
  a truncation) are not checked in the netlist; ROM recognition is off for the loader.
- The Quartus project was last built at 72680ca; three landings have gone in since.
- Timing: the worst remaining family is the pace path (ROM word, word kind, `ph_nx`, `ex`).
- Older, still open: mechanism-note items 23 and 25; DMA at the internal RAM page; the PT
  comparator / CLKOUT.
- Refresh-on families are out of scope by directive.
