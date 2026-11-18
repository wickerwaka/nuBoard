# qprobe round 23: RTL work order 19 (the interrupt rebuild: the DMA-end source, the sample word)

Evidence: `results.md` Q108, Q109. Adds to spec 15 section I and the r19 interrupt rebuild
(`r19/rtl/rtl.md`); where it differs, it replaces. Every statement is marked measured /
inferred / unknown. Notation is `model_m.py`'s. tw = the first pin clock of the terminal DMA
cycle (the write of the transfer that takes TC to its end); c = the first clock a request
stands at the EU (the end of stage 4).

## I-4. DIC0 / DIC1 (the DMA count's end): a scanned source like INTPn, entering at the flag

- **Measured.** c = the first clock of the level's scan lattice (16 clocks, the one EI / an IC
  store restarts: the same clock mod 16 as INTP0 at the same level in the same frame) that is at
  least 7 clocks behind tw. Then spec 15's 6a to 6c unchanged (event, the 2-clock occupation, 5
  clocks, first pop; the occupation's displacements are on the pins as for INTPn). Counts (load trains, W = 0, pushed instruction + vector-read clock + reads, `c23.py`): memory
  to memory burst, channel 0, level 7 `r23bld` 104 of 104 (lattice 2 / 3 mod 16, threshold 7 the
  only cell); channel 1 `r23eld` 104 of 104 (same cell); level 5 `r23dld` 104 of 104 (lattice
  14 / 15, threshold 7); I/O to memory single `r23ald` 74 of 74 (same lattice, threshold
  bracketed 5 to 8). NOP / INC / MOV r8,imm8 trains (504 runs): consistent, not scored run by run. W = 1 / 2, HALT, demand release: **not run**. INTP0's own figure in the same terms: c = the first lattice clock at or after
  e + 10.2 (e the pin edge).
- **Build.** Keep the rebuild's path for DIC (scan, the 7-clock line, event, occupation, 5
  clocks): it is right. **Move only where DIC's IF is set: from the resuming start (`dm_rs`) to
  the terminal transfer's write, early enough that the scan treats it as it treats INTP0's flag
  for a pin edge 3.125 to 4.25 clocks in front of tw.** In the rebuild's terms: INTP's IF is
  written (`ip_set`) on the divided clock one period after the edge is detected; set DIC's IF
  on the tick on which `ip_set` would be written for such an edge. Where the RTL's INTP path
  reproduces `r17r` / `r17p` / `r19qp0` (lead 10.2), there are two candidate set points, not separated by the
  socket (**inferred**; the threshold is what is measured): the terminal-count signal of the
  terminal cycle (TC0 falls at tw + 0.5: `r23c`, 12 runs; INTP0's flag is readable 4.1 to 6.1
  behind its edge, which puts the equivalent flag at tw - 0.15 to tw + 2.975), or the routine's word that posts the terminal
  write (4 clocks in front of tw at W = 0). Build the first (a signal the bus unit already
  makes for the TC pin; check it against the port budget: if it needs a new port, that is the
  user's decision) and read the threshold with `c23.py`. Do not add a register count to make it fit: if the request word's tick is
  one period off, report it.
- **Do not build:** a shorter path for DIC behind the scan or the line (the old `ird` 3 to 4
  clocks: it matched f4_dma by landing in the same instruction, not by mechanism); the DMA
  cycle as the event or as the occupation.
- **Unknown.** The exact clock IF is set (no pin shows it; the threshold is known to one CPU
  clock, the flag is on the divided clock). W = 1 / 2 (not run: tw - 3.x in clocks or in
  request-word terms cannot be told apart at W = 0). DMA taken in HALT. A transfer that ends
  while a higher level is in service. Demand-release mode.
- **Gates.** The socket traces themselves in the direct sim (`build/qp/intsim.py` as the
  rebuild used it): `QPr23bld` (208 runs; 104 unmasked: pushed instruction and vector-read
  clock), `QPr23ald`, `QPr23bnop`, `QPr23anop`, `QPr23binc`, `QPr23ami8`, `QPr23dld`,
  `QPr23eld`; the masked twins (`-m-`) are the DMA frame alone and should be exact first.
  `python3 build/qp/c23.py r23bld r23ald r23dld r23eld` on a sim output directory prints the
  lattice and threshold the sim has (silicon: (2, 7) / (3, 7), level 5 (14, 7) / (15, 7)).
  Program gate: f4_dma (write 711: vector 20 in front of 1CCAh).

## I-5. The word on which a request is read: the pop

- **Measured (Q109).** INT's latch (stage 5) is read on the clock the N word executes; the
  vectored sources' "replace this pop" (6c) likewise. NOP: word 1 of 4. INC r16: word 1 of 2.
  CBW: word 1 of 3. MOV r,[BW]: word 4 of 5 (the datum word, on the clock the datum arrives).
  MOV r8,imm8: word 4 of 5. The popped opcode is not loaded; the instruction holding the N word
  runs to its last word; the acknowledge (INT) or the vector sequence starts behind that word
  (vector read = pop + 16 + the words from the pop to the last word: 19 / 17 / 18 / 17).
- **Build.** Read `it_ld` / `nmi_ld` / `ir_ld` on the pop (the N word executing: the
  sequencer's `wk_nx.pop` registered and not stalled) and hold the decision to the boundary,
  instead of reading at `x_end`. This removes known difference 1 of the rebuild (NOP trains 2
  clocks early, INC / CBW 1) without the two fitted registers the builder tried and withdrew.
  The event (6a) is already on first word / N word: unchanged.
- **Inferred.** That the RTL's `x_end` is the model's last word less one clock in these four
  routines (from the builder's 2 / 1 / 1 / 0 against the model's 3 / 2 / 1 / 1); if the vector
  read then comes out one clock off uniformly, that is this, not the sample word.
- **Gates.** `r17i`, `r17r`, `r17q` INT and INTP0 halves, `r18tnop1/2`, `r18tinc1/2`,
  `r18tld0`, `r18tmm0`, `r19qp0`, `r19pint` (the rebuild's score table: r17r/intp0 56 -> 0 and
  r17q/intp0 14 -> 0 are the rows to recover).
