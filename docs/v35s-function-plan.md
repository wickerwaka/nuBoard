# V35S core v2: full function validated against hardware

Approved by the user 2026-11-11. Timing accuracy is set aside for this plan: the gates compare what a
program does (its write and I/O sequence, its result region, its port and serial outputs), not when.
The cycle-exact work (docs/v35s-core-v2.md, docs/v35s-mechanisms.md) is not undone: its corpus stays a
no-loss gate throughout.

## Method

Silicon is the only reference for everything V35-specific (docs/v35s-differences.md lists what the data
book says and where it is unreadable). Every feature takes three steps:

1. **Measure on the socket first.** A directed program in validation/v35s/programs/ exercises the feature
   and writes what it saw to external memory and marker ports. The capture is kept as a receipt.
2. **Build it in the core** (fpga/v35s/core/v35/, Opus agents), from the data book and the receipt.
3. **Gate on equality.** The same program runs on the RTL in simulation; its write and I/O sequence and
   result region equal the socket's, timing ignored.

Tests are self-synchronising, since the RTL is not required to place an asynchronous event on silicon's
clock: the program announces an event through a marker port ("raise INTP0 now"), then waits in HALT or
behind a masked window; timers and serial are checked by counts, data and flags, not by tick.

Standing gates at every landing: the refresh-off corpus loses no exact run; the SingleStepTests sample,
the register vectors and the function vectors stay at 0 bad; lint and the fast tests pass.

**FPGA timing is a regression gate (the user, 2026-11-11).** Timing accuracy against silicon is set aside,
but the core is built for the T120F484 at every landing (`v35_timing.sh top`, seeds 1..3 (the user: three, not five), the 17 ns tick, one
create_clock, no exception) and compared with the baseline at 74a17eb (+0.962 / +0.721 / +0.433 / +0.465 /
-0.057 ns; 6,552 LUT4 / 73 RAM_5K). A landing that makes the worst seed materially worse goes back.

## Stages

| stage | built | the silicon measurement that leads it |
| --- | --- | --- |
| F0 harness | a marker-triggered input schedule (NMI, INTP0-2, INT with INTAK answered, DMARQ0/1, HLDRQ, RxD0/1, CTS0/1, N/S); port and serial output changes recorded in the trace; a standard dump routine (register banks, the SFR page) | none |
| F1 on-chip memory | data reads and writes of internal RAM and the SFR page, the registers visible as memory, IDB relocation, RAMEN; every SFR's reset value and write mask; PSW BRKI, F0 / F1 with FLAG, the POP / MOV masks | a sweep writing four patterns to every SFR and RAM byte and reading back |
| F2 opcodes | INS, EXT, CHKIND, POLL, the FPO trap (vector 7), the I/O trap (vector 19), undefined opcodes, REP before non-strings, the HALT wake rules, BTCLR | one program per family; the undefined-opcode probe (work item A8) |
| F3 interrupts | the controller (xxIC registers, INTM edges, ISPR, priority, FINT), NMI, INTP0-2, vectored and bank-switch entry, INT / INTAK, nesting; then BRKCS, TSKSW, MOVSPA, MOVSPB, RETRBI, BRKS, BRKN, N/S sampling | entry and exit per source and mode, the priority and nesting matrices |
| F4 peripherals | ports with PM / PMC and the comparator port PT; the time base; TM0 / TM1 with TOUT; two serial channels; two DMA channels; macro service; bus hold; READY; STBC and STOP | a program set per peripheral; macro service most (the book's mode encodings are unreadable) |
| F5 closing | random-instruction fuzz over the full set with bank and SFR dumps against the socket | the fuzz corpus |

Order by dependency: interrupts need SFR access, the bank instructions need the controller's state, every
peripheral reports through interrupts. F0 and F2's first part (INS / EXT) run beside F1.

## Rulings (the user, 2026-11-11)

- **Software Guard:** the MD bit, BRKS, BRKN and N/S sampling are built; the secure mode's opcode
  translation table (per part, unpublished) is a pass-through; extracting it is a separate project.
- **Where the RTL runs:** socket captures against the RTL in simulation, as the corpus does.
- **Refresh:** the standing rule holds; refresh in HALT and during bus hold is left out.
- **STOP:** validated as the CPU going quiet until NMI or reset, no more (the harness supplies the clock).
- Earlier the same day: the fabric period target is 17 ns; the core has no block-RAM budget.

## Resources shared by agents

The board (the socketed µPD70337 and the FPGA image) has one owner at a time, named in each brief. Efinity
runs one at a time. Agents never commit and never edit validation/v35s/chains/sim/**, fit.json or docs/.
