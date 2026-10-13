# V35S execution-unit timing, measured

Phase 1 of [`v35s-core-plan.md`](v35s-core-plan.md): the measurements the new
core's step model is fitted to. All runs are on the socketed µPD70337L-8,
harness build 2, fX/2 at X1 = 8.33 MHz, one run per case from reset, socket
lane only. Bus-level results (prefetch, READY, refresh) are in
[`v35s-bus-timing.md`](v35s-bus-timing.md).

**How costs are measured.** The window is the one in `validation/v35s/timing.py`:
a saturated NOP runway, the target, a NOP runway, then a closing marker. A
cost is the time between the markers minus the empty window, in CPU clocks.
It is retirement to retirement and includes any queue refill the form
forces. Odd-length forms run at both placements and report the mean (hence
the .5 values); even-length forms run once. Unless stated, settings are
WTC = 0, refresh off, RAMEN = 1. A NOP costs 4.

**Where the data is.** Every run, with its full trace, is frozen in the
silicon corpus (`python -m validation.v35s.corpus list`):

| Entry | Contents |
| --- | --- |
| `a6-timing` | the 306 nuV30 V30 forms (step 1) |
| `m1-a6-w2`, `m1-a6-refresh`, `m2-a6-ramen0` | the same forms at 2 waits, with refresh on, with RAMEN = 0 |
| `m3-m9-probes` | suites `regs`, `ea`, `data`, `iram`, `psw`, `undefined` from `validation/v35s/probes.py` |
| `m8-iram-ramen0` | the `iram` suite with RAMEN = 0 |
| `m-psw-fixed`, `m-undefined-refresh` | the `psw` suite with a corrected RETI case; `undefined` with refresh on |

`python -m validation.v35s.timing_compare A.json B.json` sets two runs side by
side.

## Registers are internal RAM (M3, M8)

Data accesses to the current bank read and write the live registers:

- `MOV DW,[FEFE]` (bank 7, AW slot) returns AW. `[FEFC]` returns CW and
  `[FEE8]` DS0.
- `MOV word [FEFC],A55A` changes CW to A55A. A byte write to FEFC changes
  CL only.
- With RAMEN = 0 the same addresses go out on the bus, and the registers are
  untouched.

This confirms B2 in the differences list: the register file is the internal
RAM, not a cache of it.

**What register access costs.** The opcode form and the ModR/M form of the
same operation can differ:

| Operation | Short form | ModR/M form |
| --- | --- | --- |
| INC/DEC reg16 | 2.5 (40+r) | 6 (FF /0) |
| INC reg8 | — | 6 |
| PUSH reg | 9 (50+r) | 14 (FF /6) |
| POP reg | 11.5 (58+r) | 11 (8F /0) |
| XCH AW,reg | 4 (90+r) | 3 (87) |
| MOV reg,imm16 | 7 (B8+r) | 7 (C7) |
| MOV reg8,imm | 6 (B0+r) | 6 (C6) |
| ADD acc,imm | 6 / 7 (04 / 05) | 6 / 7 (80 / 81), 6 (83) |
| TEST acc,imm | 6 / 7 (A8 / A9) | 8.5 / 10 (F6 / F7) |

- **No penalty for register or byte position:** MOV, ADD, CMP, XCH reg,reg
  cost 3 for any register pair, byte or word, high or low byte.
- **Segment registers cost the same as general registers:** MOV to and from
  them is 3.
- **Read-modify-write of a register costs 6:** INC/DEC through ModR/M, NOT,
  NEG, and TEST reg,reg, which is 6 although it writes nothing.
- **Bank, not measured:** every case ran in bank 7.

## Effective address (M4)

Every mod/rm, for word loads, byte loads, stores, `ADD reg,mem`,
`ADD mem,reg` and `LDEA`:

| EA form | Extra clocks |
| --- | --- |
| [reg], [base+index] | 0 |
| any + disp8, [disp16], [reg+disp16] | +1 |
| [base+index+disp16] | +2 |

- **Base costs:** `LDEA` 6, word or byte load 10, store 8, `ADD reg,mem` 10,
  `ADD mem,reg` 13.
- **BP-based forms (SS) cost the same as BW-based forms (DS0).**
- **Odd-address word:** a load costs +4 and a store +3 (two bus cycles, odd
  byte first). A read-modify-write costs +6. An odd-address byte costs
  nothing extra.
- **Segment prefix:** +2.5 each (mean of both placements). Two prefixes
  cost +6.

## Data-dependent forms (M5)

**Multiply.**

| Form | Cost |
| --- | --- |
| MULU r8 | 26, any operands |
| MULU r16 | 34, any operands |
| MUL r8 | 37 with operand signs equal |
| MUL r16 | 44 with operand signs equal |
| MUL r8 / r16, signs differ | +8 |
| MUL r8 / r16, signs differ and one operand zero | +10 |
| MUL AW,reg,imm8 | 41; 49 when signs differ |

Exceptions to the table:
- MUL r8 80h × 02h costs 46, not 45.
- "Sign" is the operand's top bit, so 0 × 80h counts as differing.

**Divide.**

| Form | Cost |
| --- | --- |
| DIVU r8 | 34, any operands |
| DIVU r16 | 42, any operands |
| DIV r8 | 53 base |
| DIV r16 | 61 base |
| DIV, negative dividend | +7 |
| DIV, quotient negative (signs differ) | +2 |
| divide error (vector 0, to our stub) | 143–181 |

**Shifts and rotates (reg).**
- **Cost:** 10 for a count of 0, and 12 + 2n for n ≥ 1. It is the same for
  SHL, SAR, RCL and ROR, byte or word, and for the CL and imm8 forms.
- **The count is not masked:** n = 255 costs 522.
- **Memory word:** 21.5 + 2n for the immediate form, and 23 + 2n with CL.

**Strings.** n is CW.

| Form | Cost | Single form |
| --- | --- | --- |
| REP MOVBKW / MOVBKB | 25 + 18n | 23.5 |
| REP STMW | 25 + 9n | 13 |
| REP LDMW | 26 + 11n | 13.5 |
| REPE CMPBKW | 50 + 18n | 25.5 |
| REPE CMPMW | 40 + 12n | — |
| any REP form, CW = 0 | 15 | — |

- **Odd source and destination:** per element +6 for MOVBKW; +3 for an odd
  source only.

**Other forms.**

| Form | Cost |
| --- | --- |
| PREPARE 8, L | 30, 40, 57, then +18 per level (L = 0, 1, 2, 3…) |
| DISPOSE | 11.5 |
| ADD4S / SUB4S | 23 + 30·⌈CL/2⌉ |
| CMP4S | 24 + 25·⌈CL/2⌉ |
| ROL4 / ROR4 reg | 18.5 / 22.5 |
| ROL4 mem | 24.5 |
| CVTBD | 22, any AL |
| CVTDB | 21, any AL |
| ADJBA | 17.5 |
| ADJ4A | 10.5 |
| CVTWL | 9.5 |
| CVTBW | 3 |
| CLR1 / NOT1 CY | 2.5 |

**EXT and INS are strongly data dependent.** EXT AL,w from bit offset 0
costs 107 − 4w for w ≤ 8, but 43 at w = 15, and 71–85 from offset 12. INS is 84–172. It
needs an offset × width sweep before the model can take it (open item).

## Settings: waits, refresh, RAMEN (M1, M2)

**2 waits (WTC = AAAA).** Every form slows, including register-only forms
(XCH reg,reg 3 → 5):
- each fetch takes 5 clocks instead of 3, so the queue runs dry;
- each memory operand adds 2 clocks per bus cycle on top of that.

The spread is +1 to +22. The fit has to come from the BIU model, not per-form
terms.

**Refresh on (RFM = FC).** −1 to +23 depending on where refreshes land. Use
the traces, not the costs.

**RAMEN = 0.** 219 forms are unchanged. Every form that writes memory is
exactly 3 clocks faster: 47 forms at −3, plus the stack forms at −2.5. The
multi-write forms save more: PUSH R −22.5, POP R −18, BRK and RETI −5,
PREPARE 2 −8. Reads are unaffected.

So with internal RAM enabled each data write costs 3 extra clocks after its
bus cycle. External writes pay it too, which suggests the write is checked
against or mirrored to the internal RAM. The data book's bracketed RAMEN = 0
counts show the same thing.

## Internal RAM and SFR data access (M8)

- **RAMEN = 1:** accesses to xxE00–xxEFF make no bus cycle and cost exactly
  what a zero-wait external access costs. That is 11 for `MOV AW,[disp16]`,
  internal or external. An odd internal word still costs +3, so internal
  RAM is accessed a word at a time.
- **SFRs (xxF00–xxFFF) and IDB at FFFFF:** never on the bus, at either RAMEN
  setting.
  - Byte SFR reads cost the same as RAM.
  - A word read of WTC costs +3, like an odd word.
  - Reserved FF80 costs +1 (+3 with RAMEN = 0).
- **RAMEN = 0:** the RAM range goes out on the bus as ordinary memory (the
  lane answered 0).
- **IDB relocation to 20h:** FFE00 then goes external, and 20E00 is internal
  RAM. FFFFF still reads IDB (20h), as does 20FFF.

## PSW (M9)

- **POP PSW:** keeps bits 15–12 (MD, RB). Bits 11–0 are all written,
  including BRKI (bit 1) and F0/F1 (bits 3 and 5): 0EFF → FEFF, 0000 → F000.
- **SAHF:** writes all of bits 7–0. SAHF with AH = 00 clears BRKI, and the
  next OUT traps.
- **BRKI = 0:** IN, OUT and OUTM all trap to vector 19.
- **RETI:** restores RB. The probe returned to bank 6 and read PSW E002 there.
  It also restores MD: a first attempt with PSW 6002 entered secure mode, and
  the following opcodes ran translated. MAME is wrong on RB.
- **Reset PSW:** F002, as the data book says.

## Traps and undefined opcodes (M9, A8)

| Opcode | Result |
| --- | --- |
| D8–DF (any ModR/M), 66, 67 | vector 7 (FPO); 128 clocks to the stub |
| 63 ib (BRKN) | vector ib; the same cost as INT ib (CD) |
| 0F 21, 0F 24, 0F 30, 0F 93, 0F 96, 0F FF | all bus activity stops, refresh included (STOP-like); the run times out |
| 0F 80 | stopped once with refresh off, completed with refresh on: unstable, recheck |
| 0F E0 | reads SS:SP, then runs from 1909:0 (a far transfer through the stack) |
| 0F 00, 0F 01, 0F 0F, 0F 27, 0F 40, 0F 90, 0F A0 | a read-modify-write of 098D0 with about 300 clocks between read and write; no trap |
| 0F 34 | 18 clocks, no visible effect |
| FE /7 | 14 clocks, no visible effect |
| 8F /1 | behaves as POP |

F1 (BRKS) was not probed: it enters secure mode with an unknown table.

## Open items from Phase 1

- **EXT/INS:** an offset × width sweep.
- **MUL r8 80h × 02h = 46:** more signed-multiply operands, to find the rule.
- **Register access by bank:** confirm costs are bank-independent once
  bank-switch code exists (Phase 5).
- **The undefined 0F group:** decode the 098D0 read-modify-write and the
  STOP-like opcodes.
- **The RAMEN write penalty:** where the 3 clocks fall relative to the next
  bus cycle (from the traces, in the Phase 2 fit).
