# V30 opcode → microcode / measured-cost lookup

Read-only extraction, 2026-11-09. Sources (all under `build/deps/nuV30/docs/`):

- `V20UC.TXT` — microcode disassembly. **Lines** = file line numbers (`L`), **ROM** = 4-hex micro-addresses (row index in the listing). Each block = 1 header line + 4 micro-instructions; a block range `Lh-Lh+4` includes its header.
- `facts/measurements.md` — cited as `M:<line>`.
- `facts/timing_measured.json` — cited as `J<n>` = `results[n]` (0-based; 306 records, F-to-F spacing, 4 MHz, 0 waits, max mode, even code/data unless noted).
- `facts/pla_model.md` (group decode, 1BL ops), `facts/undocumented_0f.md`; `notes/ucsim_provenance.md` section 6 for the `[-06-]` meaning.

## Reading the ROM

- **Micro-address** = page(3 bits: 000 native no-REP, 001 native REP (`00?` = either), 010 F6/F7 keyed by ModR/M, 011 FE/FF keyed by ModR/M, 100 0F page keyed by 2nd byte, 101 8080 ED page, 110 8080, 111 internal/FARJMP targets) . opcode(8) . sub-row(2) . slot(2). The header line shows the PLA match pattern for page.opcode.sub-row and the opcodes it serves.
- **Sequencing**: slots run in order; after slot 3 the counter carries into the sub-row, and from sub-row 3 into the opcode bits (that is how `IMUL 30` sub-row 3 falls into internal `31`, `INS 70` into `71`, `0F 20` into `0F 21`). `JMP cond loc` replaces the low 4 bits (sub-row = loc>>2, slot = loc&3) and keeps the page/opcode bits; resolved targets are shown as `->ADDR`. `always` = blank condition (unconditional). `FARJMP NAME` goes to page 111, opcode = 8 x FAR index (`V20UCDIS.PAS` `Str_FAR`).
- **Flags**: F = OPR/bus interlock (wait for read data or queue), W = update flags, E = end of instruction (the slot after an E still executes, e.g. `0007 SIGMA->M W` after `0006 E`), R = repeat the ALU op COUNT times.
- **Counts** in the tables: `toE` = slots from the entry through the first E in fall-through (address) order, blank slots included; `total` = slots through the last non-blank slot of the chain (blank slots inside included); `nb` = non-blank slots. Branches make the executed count path-dependent; the counts do not follow JMPs. FARJMP callee slots are not included (see the shared-routine section).
- `[-06-]` in the Ext column (`CTL [-06-]`) = r/m operand write-back strobe, memory operands only (ucsim_provenance.md section 6). `[-06-]`/`[-07-]` in the *Int* column (MULX 0208/020A) clear/set CY,V. Blank SR on MEMR/MEMW = operand default segment.
- **Register vs memory form**: no ModR/M opcode has separate reg/mem routines in the ROM. `M` names the r/m operand; for memory it is pre-read by decode hardware (except stores flagged MODRM_STORE in pla_3) and written back by `[-06-]`. Costs differ (measured column) but routines do not, so reg and mem forms share one row.
- **EA calculation is not in the ROM**; see the EA section at the end.

## Opcode table

| Opcode (/reg) | Mnemonic (Intel / NEC) | Measured V30 clocks (source) | Routine | V20UC.TXT lines | ROM | toE / total (nb) | F / W / E / R (ROM addr) | FARJMP calls | JMPs | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| 00-03 | ADD r/m,r / r,r/m (NEC ADD) | reg,reg 3 (J11,J12); reg,mem 13 (J7,J8); odd-anchor reg,mem 12 (J9); mem,reg RMW 19 (J3); odd RMW 27 (J4); classes M:136,139,144 | `ALU_RM` | L1-5 | 0000-0003 | 2 / 2 (2) | F:- / W:0001 / E:0001 / R:- | – | – | reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed) |
| 04/05 | ADD AL/AX,imm | 4 (J0 byte, J1 word) | `ALU_ACC` | L6-10 | 0004-0007 | 3 / 4 (4) | F:- / W:0007 / E:0006 / R:- | – | 0004 JMP OP8 2 ->0006 | 0004 JMP OP8 skips the imm high byte for the byte form |
| 06 | PUSH ES (PUSH DS1) | not measured (PUSH sreg class 9: J223,J224; M:334) | `PUSH_SREG` | L16-20 | 000C-000F | 3 / 3 (3) | F:- / W:- / E:000E / R:- | – | – |  |
| 07 | POP ES (POP DS1) | 9 (J210) | `POP_SREG` | L11-15 | 0008-000B | 4 / 4 (4) | F:000B / W:- / E:000B / R:- | – | – |  |
| 08-0B | OR r/m,r / r,r/m (OR) | reg,reg 3 (J198); mem forms not measured (class: load 13 M:139, RMW 19 M:144) | `ALU_RM` | L1-5 | 0000-0003 | 2 / 2 (2) | F:- / W:0001 / E:0001 / R:- | – | – | reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed) |
| 0C/0D | OR acc,imm | 4 (J197 word); byte not measured | `ALU_ACC` | L6-10 | 0004-0007 | 3 / 4 (4) | F:- / W:0007 / E:0006 / R:- | – | 0004 JMP OP8 2 ->0006 | 0004 JMP OP8 skips the imm high byte for the byte form |
| 0E | PUSH CS (PUSH PS) | 9 (J224) | `PUSH_SREG` | L16-20 | 000C-000F | 3 / 3 (3) | F:- / W:- / E:000E / R:- | – | – |  |
| 0F | 0F extension-page prefix (8086 POP CS slot) | not measured as such | not in the sources | – | – | – | – | – | – | ROM block 000??111 (POP sreg) pattern covers 0F, but pla_3 decodes 0F as the extension-page prefix (pla_model.md XOP 0001); prefix handled by hardware, not in the ROM |
| 10-13 | ADC (NEC ADDC) | reg,reg 3 (J19); mem forms not measured | `ALU_RM` | L1-5 | 0000-0003 | 2 / 2 (2) | F:- / W:0001 / E:0001 / R:- | – | – | reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed) |
| 14/15 | ADC acc,imm (ADDC) | 4 (J18 word) | `ALU_ACC` | L6-10 | 0004-0007 | 3 / 4 (4) | F:- / W:0007 / E:0006 / R:- | – | 0004 JMP OP8 2 ->0006 | 0004 JMP OP8 skips the imm high byte for the byte form |
| 16 | PUSH SS | not measured (class 9, M:334) | `PUSH_SREG` | L16-20 | 000C-000F | 3 / 3 (3) | F:- / W:- / E:000E / R:- | – | – |  |
| 17 | POP SS | not measured (class 9, M:334) | `POP_SREG` | L11-15 | 0008-000B | 4 / 4 (4) | F:000B / W:- / E:000B / R:- | – | – |  |
| 18-1B | SBB (NEC SUBC) | reg,reg 3 (J277); mem forms not measured | `ALU_RM` | L1-5 | 0000-0003 | 2 / 2 (2) | F:- / W:0001 / E:0001 / R:- | – | – | reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed) |
| 1C/1D | SBB acc,imm (SUBC) | 4 (J276 word) | `ALU_ACC` | L6-10 | 0004-0007 | 3 / 4 (4) | F:- / W:0007 / E:0006 / R:- | – | 0004 JMP OP8 2 ->0006 | 0004 JMP OP8 skips the imm high byte for the byte form |
| 1E | PUSH DS (PUSH DS0) | 9 (J223) | `PUSH_SREG` | L16-20 | 000C-000F | 3 / 3 (3) | F:- / W:- / E:000E / R:- | – | – |  |
| 1F | POP DS (POP DS0) | 9 (J209) | `POP_SREG` | L11-15 | 0008-000B | 4 / 4 (4) | F:000B / W:- / E:000B / R:- | – | – |  |
| 20-23 | AND (AND) | reg,reg 3 (J28); reg,mem 13 (J27); RMW not measured | `ALU_RM` | L1-5 | 0000-0003 | 2 / 2 (2) | F:- / W:0001 / E:0001 / R:- | – | – | reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed) |
| 24/25 | AND acc,imm | 4 (J26 word) | `ALU_ACC` | L6-10 | 0004-0007 | 3 / 4 (4) | F:- / W:0007 / E:0006 / R:- | – | 0004 JMP OP8 2 ->0006 | 0004 JMP OP8 skips the imm high byte for the byte form |
| 26 | ES: prefix (DS1:) | prefix retires as own F pop, 2 clocks; DS1:+MOV AW,[BW] 13 total (J304); M:345-356 | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 0000, hardware prefix latch |
| 27 | DAA (ADJ4A) | 3 (J20,J21; M:205) | `DAA` | L21-25 | 0010-0013 | 2 / 3 (3) | F:- / W:0012 / E:0011 / R:- | – | – |  |
| 28-2B | SUB (SUB) | reg,reg 3 (J274); reg,mem 13 (J273); RMW not measured | `ALU_RM` | L1-5 | 0000-0003 | 2 / 2 (2) | F:- / W:0001 / E:0001 / R:- | – | – | reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed) |
| 2C/2D | SUB acc,imm | 4 (J272 word) | `ALU_ACC` | L6-10 | 0004-0007 | 3 / 4 (4) | F:- / W:0007 / E:0006 / R:- | – | 0004 JMP OP8 2 ->0006 | 0004 JMP OP8 skips the imm high byte for the byte form |
| 2E | CS: prefix (PS:) | not measured (segment prefix class 2, M:345-356) | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 0000 |
| 2F | DAS (ADJ4S) | 3 (J22; M:205) | `DAS` | L26-30 | 0014-0017 | 2 / 3 (3) | F:- / W:0016 / E:0015 / R:- | – | – |  |
| 30-33 | XOR (XOR) | reg,reg 3 (J298,J299); mem,reg RMW 19 (J296) | `ALU_RM` | L1-5 | 0000-0003 | 2 / 2 (2) | F:- / W:0001 / E:0001 / R:- | – | – | reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed) |
| 34/35 | XOR acc,imm | 4 (J295 word) | `ALU_ACC` | L6-10 | 0004-0007 | 3 / 4 (4) | F:- / W:0007 / E:0006 / R:- | – | 0004 JMP OP8 2 ->0006 | 0004 JMP OP8 skips the imm high byte for the byte form |
| 36 | SS: prefix | SS:+MOV AW,[BW] 13 total (J305); M:345-356 | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 0000 |
| 37 | AAA (ADJBA) | 7 (J23,J24; M:206) | `AAA` | L31-35, L36-40 | 0018-001B, 001C-001F | 6 / 6 (6) | F:- / W:001A / E:001D / R:- | – | 001B JMP NC 5 ->001D |  |
| 38-3B | CMP (CMP) | reg,reg 3 (J70); mem,reg 13 (J67); reg,mem 13 (J69) - no writeback | `ALU_RM` | L1-5 | 0000-0003 | 2 / 2 (2) | F:- / W:0001 / E:0001 / R:- | – | – | reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed) |
| 3C/3D | CMP acc,imm | 4 (J65 word) | `ALU_ACC` | L6-10 | 0004-0007 | 3 / 4 (4) | F:- / W:0007 / E:0006 / R:- | – | 0004 JMP OP8 2 ->0006 | 0004 JMP OP8 skips the imm high byte for the byte form |
| 3E | DS: prefix (DS0:) | DS0:+ADD BW,DW 5 (J301); DS0:+MOV AW,[BW] 13 (J302); stacked DS1:DS0: 16 (J303); M:345-356 | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 0000 |
| 3F | AAS (ADJBS) | 7 (J25; M:206) | `AAS` | L41-45, L36-40 | 0020-0023, 001C-001F | 6 / 6 (6) | F:- / W:0022 / E:001D / R:- | – | 0023 JMP NC 5 ->001D |  |
| 40-47 | INC r16 | 2 (J101,J102; M:135) | `INCDEC_R16` | L46-50 | 0024-0027 | 1 / 2 (2) | F:- / W:0025 / E:0024 / R:- | – | – | ALU OPC (INC/DEC chosen by opcode bit 3) |
| 48-4F | DEC r16 | 2 (J87) | `INCDEC_R16` | L46-50 | 0024-0027 | 1 / 2 (2) | F:- / W:0025 / E:0024 / R:- | – | – |  |
| 50-57 | PUSH r16 | 9 (J220); odd anchor 10 (J221); SP odd 13 (J222); M:150 | `PUSH_R16` | L51-55 | 0028-002B | 2 / 3 (3) | F:- / W:- / E:0029 / R:- | – | – |  |
| 58-5F | POP r16 | 9 (J207); SP odd 13 (J208) | `POP_R16` | L56-60 | 002C-002F | 4 / 4 (4) | F:002F / W:- / E:002F / R:- | – | – |  |
| 60 | PUSHA (PUSH R) | 52 (J215,J216; M:152,297-303) | `PUSHA_ENTRY` | L711-715 | 0238-023B | no E (exits via FARJMP) / 4 (4) | F:0239,023B / W:- / E:- / R:- | PUSHA | – |  |
| 61 | POPA (POP R) | 33 (J204,J205; M:153,304-308) | `POPA_ENTRY` | L736-740 | 024C-024F | no E (exits via FARJMP) / 4 (4) | F:024F / W:- / E:- / R:- | POPA | – | SP slot skipped in POPA (0250/0251: SIGMA->tmpb twice, no read) |
| 62 | BOUND (CHKIND) | in bounds 22 (J54); trap to handler 63 (J55); M:338-339 | `CHKIND` | L791-795, L796-800, L801-805 | 0278-027B, 027C-027F, 0280-0283 | 9 / 12 (11) | F:0278,027D,0282 / W:027B,027E / E:0280 / R:- | INT | 027C JMP L 10 ->0282; 027F JMP L 11 ->0283 | trap path: 0283 CONST(5)->tmpbL; FARJMP INT |
| 63 | (undefined; 8086 alias) | not measured | not in the sources | – | – | – | – | – | – | not in the sources (no ROM block matches 63; pla_3 gives it ModR/M, pla_model.md finding 2) |
| 64 | REPNC prefix (V30) | not measured | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 1001 |
| 65 | REPC prefix (V30) | not measured | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 1000 |
| 66/67 | FPO2 (coprocessor escape, V30) | not measured | `FPO2` | L61-65 | 0030-0033 | 1 / 1 (1) | F:- / W:- / E:0030 / R:- | – | – | ROM routine is a single E row (0030); pla_3 term 01100?1? makes 66/67 aliases of 62/63 for group decode |
| 68 | PUSH imm16 | 10 (J217; M:151) | `PUSH_IMM16` | L811-815 | 0288-028B | 4 / 4 (4) | F:- / W:- / E:028B / R:- | – | – |  |
| 69 | IMUL r16,r/m16,imm16 (NEC MUL reg16,reg16,imm16) | 40 (J150,J151; M:114) | `IMUL_IMM` | L821-825 | 0290-0293 | no E (exits via FARJMP) / 4 (4) | F:- / W:- / E:- / R:- | IMULI | 0290 JMP OP8 2 ->0292 |  |
| 6A | PUSH imm8 (sign-extended) | 9 (J218; M:151) | `PUSH_IMM8` | L806-810 | 0284-0287 | 3 / 4 (4) | F:- / W:- / E:0286 / R:- | – | – |  |
| 6B | IMUL r16,r/m16,imm8 (NEC MUL reg16,reg16,imm8) | 40 / 44 when operand signs differ (J152-J154; M:113,117-118) | `IMUL_IMM` | L821-825 | 0290-0293 | no E (exits via FARJMP) / 4 (4) | F:- / W:- / E:- / R:- | IMULI | 0290 JMP OP8 2 ->0292 |  |
| 6C/6D | INSB/INSW (NEC INM), no REP | not measured | `INM` | L826-830 | 0294-0297 | 3 / 4 (4) | F:- / W:- / E:0296 / R:- | – | – |  |
| REP 6C/6D | REP INSB/INSW (REP INM) | not measured | `REP_INM` | L831-835, L836-840 | 0298-029B, 029C-029F | no E (exits via FARJMP) / 8 (7) | F:- / W:- / E:- / R:- | REPX | 029A JMP Z 7 ->029F; 029E JMP REP 3 ->029B |  |
| 6E/6F | OUTSB/OUTSW (NEC OUTM), no REP | not measured | `OUTM` | L841-845 | 02A0-02A3 | 3 / 4 (4) | F:- / W:- / E:02A2 / R:- | – | – |  |
| REP 6E/6F | REP OUTSB/OUTSW (REP OUTM) | not measured | `REP_OUTM` | L846-850, L851-855 | 02A4-02A7, 02A8-02AB | no E (exits via FARJMP) / 8 (8) | F:- / W:- / E:- / R:- | REPX | 02A6 JMP Z 7 ->02AB; 02AA JMP REP 3 ->02A7 |  |
| 70-7F | Jcc rel8 (NEC Bcond) | not taken 4, taken 13 (incl. flush+refetch) for 72/73/74/75 (J29,J30,J33-J36,J47-J49; M:186-187); other conditions not measured | `JCC` | L66-70, L71-75 | 0034-0037, 0038-003B | 3 / 6 (5) | F:- / W:- / E:0036,0039 / R:- | – | 0035 JMP OPC 4 ->0038 | condition from pla_2 (pla_model.md); 0035 JMP OPC 4 -> 0038 when taken |
| 80-83 /0-/7 | group 1 r/m,imm: /0 ADD /1 OR /2 ADC /3 SBB /4 AND /5 SUB /6 XOR /7 CMP (82 = 80 alias) | reg: ADD 6 (J5 81/0, J6 83/0), XOR 6 (J297 81/6), CMP 6 (J68 83/7); mem: ADD word 22 (J2 83/0), CMP word 16 (J66 83/7); M:137,145; other reg values not measured | `GRP1` | L76-80, L81-85 | 003C-003F, 0040-0043 | 5 / 5 (5) | F:- / W:0040 / E:0040 / R:- | – | 003C JMP OP8 2 ->003E | one routine for all eight reg values (ALU OPC selects the op from the reg field); 003C JMP OP8 skips the imm high byte for 80/82/83; 83 sign-extension is not visible in the ROM |
| 84/85 | TEST r/m,r | reg,reg 2 (J280,J281); mem 12 (J279); M:140,165 | `TEST_RM` | L86-90 | 0044-0047 | 1 / 2 (2) | F:- / W:0045 / E:0044 / R:- | – | – |  |
| 86/87 | XCHG r/m,r (XCH) | reg,reg 3 (J294); mem 19 (J292); odd mem 27 (J293) | `XCHG_RM` | L91-95 | 0048-004B | 2 / 3 (3) | F:- / W:- / E:0049 / R:- | – | – |  |
| 88-8B | MOV r/m,r / r,r/m | reg,reg 3 (J130-J132); load 13 (J126-J128); odd word load 17 (J129); store 11 (J117,J118); odd-anchor store 10 (J119); odd store 15 (J120) | `MOV_RM` | L96-100 | 004C-004F | 2 / 2 (2) | F:- / W:- / E:004D / R:- | – | – | 88/89 stores: operand pre-read suppressed (pla_3 MODRM_STORE) |
| 8C | MOV r/m16,sreg | reg 2 (J133,J134); mem 11 (J121) | `MOV_SREG` | L101-105 | 0050-0053 | 1 / 1 (1) | F:- / W:- / E:0050 / R:- | – | – |  |
| 8D | LEA (LDEA) | [BW+IX] 3 (J107); direct 5 (J106); M:335 | `LEA` | L106-110 | 0054-0057 | 1 / 2 (2) | F:- / W:- / E:0054 / R:- | – | – | EA computed by hardware; 0055 SIGMA->R takes it after the E row |
| 8E | MOV sreg,r/m16 | reg 2 (J136); mem 12 (J135) | `MOV_SREG` | L101-105 | 0050-0053 | 1 / 1 (1) | F:- / W:- / E:0050 / R:- | – | – |  |
| 8F /0 | POP r/m16 | mem 15 (J206; M:333); reg form not measured | `POP_RM` | L111-115 | 0058-005B | 4 / 4 (4) | F:005A / W:- / E:005B / R:- | – | – | [-06-] at 005B writes memory only; mod=3 leaves the register unwritten (ucsim_provenance.md section 6) |
| 90 | NOP (XCHG AX,AX) | 3 (J185,J186; M:135) | `XCHG_AX` | L116-120 | 005C-005F | 2 / 3 (3) | F:- / W:- / E:005D / R:- | – | – |  |
| 91-97 | XCHG AX,r16 (XCH AW,r) | 3 (J291) | `XCHG_AX` | L116-120 | 005C-005F | 2 / 3 (3) | F:- / W:- / E:005D / R:- | – | – |  |
| 98 | CBW (CVTBW) | 2 (J76; M:208) | `CBW` | L121-125 | 0060-0063 | 1 / 2 (2) | F:- / W:- / E:0060 / R:- | – | – |  |
| 99 | CWD (CVTWL) | 5 (J78,J79; M:208) | `CWD` | L126-130 | 0064-0067 | 4 / 4 (4) | F:- / W:- / E:0067 / R:- | – | 0065 JMP NS 3 ->0067 |  |
| 9A | CALL far ptr16:16 | 27 (J50; M:195) | `CALL_FAR_DIR` | L131-135 | 0068-006B | no E (exits via FARJMP) / 4 (4) | F:- / W:- / E:- / R:- | CALLF | – |  |
| 9B | WAIT (POLL) | not measured | `WAIT` | L136-140, L141-145 | 006C-006F, 0070-0073 | 2 / 8 (7) | F:- / W:- / E:006D,0073 / R:- | – | 006C JMP BUSY 3 ->006F; 006F JMP INTR 5 ->0071; 0070 JMP always 0 ->006C | loops on JMP BUSY / JMP INTR |
| 9C | PUSHF (PUSH PSW) | 9 (J214) | `PUSHF` | L146-150 | 0074-0077 | 2 / 3 (3) | F:- / W:- / E:0075 / R:- | – | – |  |
| 9D | POPF (POP PSW) | 9 (J203) | `POPF` | L151-155 | 0078-007B | 3 / 4 (4) | F:007A / W:- / E:007A / R:- | – | – |  |
| 9E | SAHF (MOV PSW,AH) | not measured | `SAHF` | L156-160 | 007C-007F | 2 / 3 (3) | F:- / W:- / E:007D / R:- | – | – |  |
| 9F | LAHF (MOV AH,PSW) | not measured | `LAHF` | L161-165 | 0080-0083 | 1 / 1 (1) | F:- / W:- / E:0080 / R:- | – | – |  |
| A0/A1 | MOV AL/AX,[moffs] | 10 (J111,J113); odd word 14 (J112); M:142 | `MOV_ACC_DMEM` | L166-170 | 0084-0087 | 4 / 4 (4) | F:0087 / W:- / E:0087 / R:- | – | – |  |
| A2/A3 | MOV [moffs],AL/AX | 10 (J115); odd word 14 (J114); M:143 | `MOV_DMEM_ACC` | L171-175 | 0088-008B | 3 / 4 (4) | F:- / W:- / E:008A / R:- | – | – |  |
| A4/A5 | MOVSB/W (MOVBKB/W), no REP | 13 (J137,J138; M:198) | `MOVS` | L176-180 | 008C-008F | 4 / 4 (4) | F:- / W:- / E:008F / R:- | – | – |  |
| REP A4/A5 | REP MOVSB/W | 9+8n (M:202); CX=0 12 (M:204) | `REP_MOVS` | L186-190, L191-195 | 0094-0097, 0098-009B | no E (exits via FARJMP) / 8 (8) | F:- / W:- / E:- / R:- | REPX | 0096 JMP Z 7 ->009B; 009A JMP REP 3 ->0097 |  |
| A6/A7 | CMPSB/W (CMPBKB/W), no REP | 13 (J72,J73; M:199) | `CMPS` | L196-200, L201-205 | 009C-009F, 00A0-00A3 | 7 / 8 (8) | F:00A0,00A2 / W:00A3 / E:00A2 / R:- | – | – |  |
| REP A6/A7 | REPE/REPNE CMPSB/W | REPE CMPSW 11+14n (M:203); odd addresses 7+22/rep (M:395-396); CX=0 12 (M:204) | `REP_CMPS` | L206-210, L211-215, L216-220 | 00A4-00A7, 00A8-00AB, 00AC-00AF | no E (exits via FARJMP) / 12 (12) | F:00AA,00AC / W:00AD / E:- / R:- | REPX | 00A6 JMP Z 11 ->00AF; 00AE JMP REP 3 ->00A7 |  |
| A8/A9 | TEST AL/AX,imm | 4 (J278 word) | `TEST_ACC` | L226-230 | 00B4-00B7 | 3 / 4 (4) | F:- / W:00B7 / E:00B6 / R:- | – | 00B4 JMP OP8 2 ->00B6 |  |
| AA/AB | STOSB/W (STMB/W), no REP | 9 (J269,J270); odd 13 (J271); M:198 | `STOS` | L231-235 | 00B8-00BB | 3 / 4 (4) | F:- / W:- / E:00BA / R:- | – | – |  |
| REP AA/AB | REP STOSB/W | REP STOSW 9+4n (M:201); CX=0 12 (M:204) | `REP_STOS` | L236-240, L241-245 | 00BC-00BF, 00C0-00C3 | no E (exits via FARJMP) / 6 (6) | F:- / W:- / E:- / R:- | REPX | 00BE JMP Z 5 ->00C1; 00C0 JMP REP 3 ->00BF |  |
| AC/AD | LODSB/W (LDMB/W), no REP | 9 (J108,J109); odd 13 (J110); M:198 | `LODS` | L246-250 | 00C4-00C7 | 4 / 4 (4) | F:00C7 / W:- / E:00C7 / R:- | – | – |  |
| REP AC/AD | REP LODSB/W | not measured (CX=0 class 12, M:204) | `REP_LODS` | L251-255, L256-260 | 00C8-00CB, 00CC-00CF | no E (exits via FARJMP) / 8 (8) | F:00CD / W:- / E:- / R:- | REPX | 00CA JMP Z 7 ->00CF; 00CE JMP REP 3 ->00CB |  |
| AE/AF | SCASB/W (CMPMB/W), no REP | not measured | `SCAS` | L261-265, L266-270 | 00D0-00D3, 00D4-00D7 | 6 / 6 (6) | F:00D4 / W:00D5 / E:00D5 / R:- | – | – |  |
| REP AE/AF | REPE/REPNE SCASB/W | not measured (CX=0 class 12, M:204) | `REP_SCAS` | L206-210, L271-275, L276-280 | 00A4-00A7, 00D8-00DB, 00DC-00DF | no E (exits via FARJMP) / 12 (10) | F:00DA / W:00DB / E:- / R:- | REPX | 00A6 JMP Z 11 ->00DF; 00DC JMP REP 3 ->00A7 | first block (00A4-00A7) shared with REP CMPS |
| B0-B7 | MOV r8,imm8 | 4 (J124); extra idle cycle before next pop on a prefetched queue (M:481-486) | `MOV_R_IMM` | L281-285 | 00E0-00E3 | 3 / 3 (3) | F:- / W:- / E:00E2 / R:- | – | 00E0 JMP OP8 2 ->00E2 |  |
| B8-BF | MOV r16,imm16 | 4 (J122,J123,J125) | `MOV_R_IMM` | L281-285 | 00E0-00E3 | 3 / 3 (3) | F:- / W:- / E:00E2 / R:- | – | 00E0 JMP OP8 2 ->00E2 |  |
| C0/C1 /0-/7 | shift r/m,imm8: /0 ROL /1 ROR /2 RCL /3 RCR /4 SHL /5 SHR /6 (undefined, ALU op [-0E-]) /7 SAR | reg: ROR AW,4 14 (J236), SHL AW,4 14 (J264), class 10+n (M:147); mem not measured | `SHIFT_IMM` | L816-820 | 028C-028F | no E (exits via FARJMP) / 4 (4) | F:- / W:- / E:- / R:- | SHIFT | – | one routine for all reg values; count from Q (imm8); loop in SHIFT |
| C2 | RET imm16 (RET pop-value) | 17 (J226; M:197) | `RET_IMM` | L286-290, L291-295 | 00E4-00E7, 00E8-00EB | 7 / 7 (6) | F:00EA / W:- / E:00EA / R:- | – | – |  |
| C3 | RET | 16 (J225; M:196) | `RET` | L301-305 | 00F0-00F3 | 4 / 4 (4) | F:00F3 / W:- / E:00F3 / R:- | – | – |  |
| C4 | LES r16,m32 (MOV DS1,...) | not measured | `LES` | L311-315 | 00F8-00FB | 3 / 3 (3) | F:00F8,00FA / W:- / E:00FA / R:- | – | – |  |
| C5 | LDS r16,m32 (MOV DS0,...) | not measured | `LDS` | L316-320 | 00FC-00FF | 3 / 3 (3) | F:00FC,00FE / W:- / E:00FE / R:- | – | – |  |
| C6/C7 /0 | MOV r/m,imm | mem word 11 (J116; M:141); reg8 form shares the B0 tail (M:485-486); write-only store, cadence M:487-505 | `MOV_RM_IMM` | L321-325 | 0100-0103 | 3 / 3 (3) | F:- / W:- / E:0102 / R:- | – | 0100 JMP OP8 2 ->0102 |  |
| C8 | ENTER imm16,imm8 (PREPARE) | imm8=0 12, =1 22, =2 30 (J211-J213; M:336) | `ENTER_ENTRY` | L761-765 | 0260-0263 | no E (exits via FARJMP) / 4 (4) | F:0263 / W:- / E:- / R:- | ENTER | – |  |
| C9 | LEAVE (DISPOSE) | 9 (J89; M:337) | `LEAVE` | L786-790 | 0274-0277 | 4 / 4 (4) | F:0277 / W:- / E:0277 / R:- | – | – |  |
| CA | RETF imm16 | not measured | `RETF_IMM` | L286-290, L296-300 | 00E4-00E7, 00EC-00EF | no E (exits via FARJMP) / 6 (5) | F:- / W:- / E:- / R:- | RETF | – |  |
| CB | RETF | not measured | `RETF_` | L306-310 | 00F4-00F7 | no E (exits via FARJMP) / 4 (4) | F:- / W:- / E:- / R:- | RETF | – |  |
| CC | INT 3 (BRK 3) | BRK 3 trap to handler 43 (J44; M:341) - encoding (CC vs CD 03) not recorded in J44 | `INT3` | L326-330 | 0104-0107 | no E (exits via FARJMP) / 2 (2) | F:- / W:- / E:- / R:- | INT | – |  |
| CD | INT imm8 (BRK imm8) | not measured (see CC) | `INT_N` | L331-335 | 0108-010B | no E (exits via FARJMP) / 1 (1) | F:- / W:- / E:- / R:- | INT | – |  |
| CE | INTO (BRKV) | V=0 3 (J45); V=1 trap 44 (J46); M:342 | `INTO` | L336-340 | 010C-010F | 2 / 4 (3) | F:- / W:- / E:010D / R:- | INT | 010C JMP O 3 ->010F |  |
| CF | IRET (RETI) | 22 (J227; M:340) | `IRET_` | L341-345 | 0110-0113 | no E (exits via FARJMP) / 2 (2) | F:- / W:- / E:- / R:- | IRET | – |  |
| D0/D1 /0-/7 | shift r/m,1: /0 ROL /1 ROR /2 RCL(ROLC) /3 RCR(RORC) /4 SHL /5 SHR /6 undefined /7 SAR(SHRA) | reg 6 for all ops measured (ROL J228, RCL J232, ROR J235, RCR J239, SHL J256-J259, SHR J265, SAR J267; M:146); mem 22 (ROR J233, SHL J251; M:149); odd mem 30 (J252) | `SHIFT_1` | L346-350 | 0114-0117 | 4 / 4 (4) | F:- / W:0116 / E:0117 / R:0116 | – | – | R flag at 0116 repeats ALU OPC COUNT(=1) times |
| D2/D3 /0-/7 | shift r/m,CL (same reg map) | reg 10+n, CL=0 9 (J229,J240,J260-J263,J266,J268; M:147-148); mem 25+n (J234,J253-J255; M:211) | `SHIFT_CL` | L351-355 | 0118-011B | no E (exits via FARJMP) / 4 (4) | F:- / W:- / E:- / R:- | SHIFT | – |  |
| D4 | AAM imm8 (CVTBD) | 15 (J74,J75; M:207) | `AAM` | L356-360, L361-365 | 011C-011F, 0120-0123 | 6 / 7 (7) | F:- / W:0122 / E:0121 / R:011F | – | – | divide by Q via ALU DIV repeated (COUNT=8) |
| D5 | AAD imm8 (CVTDB) | 8 (J77; M:207) | `AAD` | L366-370, L371-375 | 0124-0127, 0128-012B | 7 / 8 (8) | F:- / W:012B / E:012A / R:- | – | – |  |
| D6 | (undocumented; SALC on Intel) | not measured | not in the sources | – | – | – | – | – | – | not in the sources (no ROM block; pla_3 BYTE_ONLY term shared with D4/D5) |
| D7 | XLAT (TRANS) | 9 (J290; M:209) | `XLAT` | L376-380 | 012C-012F | 3 / 3 (3) | F:012E / W:- / E:012E / R:- | – | – |  |
| D8-DF | ESC (FPO1) | not measured | `ESC` | L381-385 | 0130-0133 | 1 / 1 (1) | F:- / W:- / E:0130 / R:- | – | – | single E row; the ModR/M EA/bus activity is not in the ROM |
| E0 | LOOPNZ (DBNZNE) | not taken 5, taken 16 (J84,J85; M:189-190) | `LOOPCC` | L386-390, L391-395 | 0134-0137, 0138-013B | 4 / 8 (7) | F:- / W:- / E:0137,013B / R:- | – | 0136 JMP REP 4 ->0138 |  |
| E1 | LOOPZ (DBNZE) | not taken 5, taken 16 (J82,J83) | `LOOPCC` | L386-390, L391-395 | 0134-0137, 0138-013B | 4 / 8 (7) | F:- / W:- / E:0137,013B / R:- | – | 0136 JMP REP 4 ->0138 |  |
| E2 | LOOP (DBNZ) | not taken 5, taken 15 (J80,J81; M:188) | `LOOP` | L396-400, L391-395 | 013C-013F, 0138-013B | 4 / 8 (8) | F:- / W:- / E:013F,013B / R:- | – | 013E JMP NZ 5 ->0139 |  |
| E3 | JCXZ (BCWZ) | not taken 5, taken 15 (J31,J32; M:188) | `JCXZ` | L401-405, L391-395 | 0140-0143, 0138-013B | 4 / 8 (8) | F:- / W:- / E:0143,013B / R:- | – | 0142 JMP Z 5 ->0139 |  |
| E4/E5 | IN AL/AX,imm8 | 9 (J97,J98; M:210) | `IN_IMM` | L406-410 | 0144-0147 | 3 / 3 (3) | F:0146 / W:- / E:0146 / R:- | – | – |  |
| E6/E7 | OUT imm8,AL/AX | 9 (J201,J202) | `OUT_IMM` | L411-415 | 0148-014B | 2 / 2 (2) | F:- / W:- / E:0149 / R:- | – | – |  |
| E8 | CALL rel16 | 18 (J52; M:194) | `CALL_NEAR` | L416-420, L421-425 | 014C-014F, 0150-0153 | 6 / 6 (6) | F:- / W:- / E:0151 / R:- | – | – |  |
| E9 | JMP rel16 (BR near) | 13 (J39,J40; M:192) | `JMP_NEAR` | L426-430 | 0154-0157 | 4 / 4 (4) | F:- / W:- / E:0157 / R:- | – | 0155 JMP always 2 ->0156 |  |
| EA | JMP ptr16:16 (BR far) | 15 (J37; M:191) | `JMP_FAR_DIR` | L436-440, L441-445 | 015C-015F, 0160-0163 | 6 / 6 (6) | F:- / W:- / E:0161 / R:- | – | – |  |
| EB | JMP rel8 (BR short) | 12 (J42,J43; M:191) | `JMP_SHORT` | L431-435 | 0158-015B | 4 / 4 (4) | F:- / W:- / E:015B / R:- | – | – |  |
| EC/ED | IN AL/AX,DX | 9 (J95,J96) | `IN_DX` | L446-450 | 0164-0167 | 2 / 2 (2) | F:0165 / W:- / E:0165 / R:- | – | – |  |
| EE/EF | OUT DX,AL/AX | 9 (J199,J200) | `OUT_DX` | L451-455 | 0168-016B | 1 / 2 (2) | F:- / W:- / E:0168 / R:- | – | – |  |
| F0 | LOCK (BUSLOCK) | LOCK+NOP 5 (J300; M:353) | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 1111 |
| F1 | (undocumented; BUSLOCK alias) | not measured | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 1110, decoded as a prefix (pla_model.md finding 1) |
| F2 | REPNE prefix (REPNZ) | REP prefix own pop 2 (M:200) | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 1101; REP forms select the 001 page |
| F3 | REP/REPE prefix | 2 (M:200) | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 1100 |
| F4 | HLT (HALT) | 4 F-pop to HALT T1 (J94; M:343) | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 1011 |
| F5 | CMC (NOT1 CY) | 2 (J189) | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 1010 |
| F6/F7 /0,/1 | TEST r/m,imm (/1 undocumented alias) | not measured | `F6_TEST` | L456-460 | 016C-016F | 3 / 4 (4) | F:- / W:016F / E:016E / R:- | – | 016C JMP OP8 2 ->016E |  |
| F6/F7 /2 | NOT r/m | reg 4 (J187,J188; M:138); mem not measured | `F6_NOT` | L466-470 | 0174-0177 | 2 / 2 (2) | F:- / W:- / E:0175 / R:- | – | – |  |
| F6/F7 /3 | NEG r/m | reg 4 (J184); mem word 20 (J183; M:145) | `F6_NEG` | L461-465 | 0170-0173 | 2 / 2 (2) | F:- / W:0171 / E:0171 / R:- | – | – |  |
| F6/F7 /4 | MUL r/m (NEC MULU) | reg8 24, reg16 31, mem8 34, mem16 41, data independent (J163-J182; M:108-110); odd mem16 45 (J166) | `F6_MUL` | L471-475, L476-480, L481-485 | 0178-017B, 017C-017F, 0180-0183 | no E (exits via FARJMP) / 9 (9) | F:- / W:- / E:- / R:017C | MULX | 017A JMP OP8 4 ->017C; 017E JMP OP8 8 ->0180 |  |
| F6/F7 /5 | IMUL r/m (NEC MUL) | reg8 34/38, reg16 41/45 (+4 when operand signs differ), mem8 44, mem16 51 (J139-J162; M:111-114) | `F6_IMUL` | L486-490 | 0184-0187 | no E (exits via FARJMP) / 2 (2) | F:- / W:- / E:- / R:- | IMUL | – |  |
| F6/F7 /6 | DIV r/m (NEC DIVU) | reg16 28 (J90,J91; M:156); reg8/mem not measured | `F6_DIV` | L491-495, L496-500, L501-505, L506-510 | 0188-018B, 018C-018F, 0190-0193, 0194-0197 | 12 / 15 (14) | F:- / W:018B,018E / E:0193,0196 / R:0190 | INT | 0189 JMP OP8 4 ->018C; 018B JMP always 7 ->018F; 018F JMP NC 13 ->0195; 0192 JMP OP8 14 ->0196 | divide-error path 0195 ZEROS->tmpbL; FARJMP INT (vector 0) |
| F6/F7 /7 | IDIV r/m (NEC DIV) | relative to dispatch: early trap 21+s, late trap 36+s (byte) / 44+s (word), non-trap 37+s / 44+s, s=3 iff dividend negative (M:446-474); not an F-spacing figure | `F6_IDIV` | L511-515, L516-520 | 0198-019B, 019C-019F | no E (exits via FARJMP) / 8 (8) | F:- / W:- / E:- / R:- | IDIV | 019B JMP OP8 5 ->019D; 019C JMP always 6 ->019E |  |
| F8 | CLC (CLR1 CY) | 2 (J56) | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 0111 |
| F9 | STC (SET1 CY) | 2 (J241) | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 0110 |
| FA | CLI (DI) | not measured | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 0101 |
| FB | STI (EI) | not measured | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 0100 |
| FC | CLD (CLR1 DIR) | 2 (J57) | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 0011 |
| FD | STD (SET1 DIR) | 2 (J242) | not in the sources | – | – | – | – | – | – | not in the sources (ROM): pla_3 1BL XOP 0010 |
| FE/FF /0 | INC r/m | reg8 4 (J103; M:138); mem word 20 (J99); odd 28 (J100) | `FF_INCDEC` | L551-555 | 01B8-01BB | 2 / 2 (2) | F:- / W:01B9 / E:01B9 / R:- | – | – |  |
| FE/FF /1 | DEC r/m | reg8 4 (J88); mem word 20 (J86) | `FF_INCDEC` | L551-555 | 01B8-01BB | 2 / 2 (2) | F:- / W:01B9 / E:01B9 / R:- | – | – |  |
| FE/FF /2 | CALL r/m16 (near indirect) | reg 16 (J53); mem 26 (J51); M:194-195 | `FF_CALL_NEAR` | L556-560 | 01BC-01BF | 4 / 4 (4) | F:- / W:- / E:01BF / R:- | – | – | FE with reg 2-7 is not a documented form; the ROM block matches on the ModR/M byte only |
| FE/FF /3 | CALL m16:16 (far indirect) | not measured | `FF_CALL_FAR` | L561-565 | 01C0-01C3 | no E (exits via FARJMP) / 4 (4) | F:01C1,01C3 / W:- / E:- / R:- | CALLF | – |  |
| FE/FF /4 | JMP r/m16 (near indirect) | reg 12 (J41); mem 20 (J38); M:191-192 | `FF_JMP_NEAR` | L566-570 | 01C4-01C7 | 1 / 1 (1) | F:- / W:- / E:01C4 / R:- | – | – |  |
| FE/FF /5 | JMP m16:16 (far indirect) | not measured | `FF_JMP_FAR` | L571-575 | 01C8-01CB | 4 / 4 (4) | F:01C8,01CA / W:- / E:01CB / R:- | – | – |  |
| FE/FF /6 | PUSH r/m16 | mem 21 (J219; M:333); reg form not measured | `FF_PUSH` | L576-580 | 01CC-01CF | 3 / 3 (3) | F:- / W:- / E:01CE / R:- | – | – |  |
| FE/FF /7 | (undocumented PUSH alias) | not measured | `FF_PUSH` | L576-580 | 01CC-01CF | 3 / 3 (3) | F:- / W:- / E:01CE / R:- | – | – | block 011.??11???? covers reg 6 and 7 |
| 0F 10/11 | TEST1 r/m,CL | reg 6 (J286,J288); mem 14 (J282,J284); M:323-324 | `TEST1_CL` | L856-860 | 02AC-02AF | 3 / 3 (3) | F:- / W:02AE / E:02AE / R:- | – | – |  |
| 0F 12/13 | CLR1 r/m,CL | reg 7 (J62,J63); mem 21 (J58,J60); M:327 | `CLR1_CL` | L876-880 | 02BC-02BF | 4 / 4 (4) | F:- / W:- / E:02BF / R:- | – | – |  |
| 0F 14/15 | SET1 r/m,CL | reg 6 (J247,J249); mem 21 (J243,J245); M:326 | `SET1_CL` | L866-870 | 02B4-02B7 | 3 / 3 (3) | F:- / W:- / E:02B6 / R:- | – | – |  |
| 0F 16/17 | NOT1 r/m,CL | reg 6 (J194,J195); mem 21 (J190,J192); M:325 | `NOT1_CL` | L886-890 | 02C4-02C7 | 3 / 3 (3) | F:- / W:- / E:02C6 / R:- | – | – |  |
| 0F 18/19 | TEST1 r/m,imm3/4 | reg 6 (J287,J289); mem 14 (J283,J285) | `TEST1_IMM` | L861-865 | 02B0-02B3 | 3 / 3 (3) | F:- / W:02B2 / E:02B2 / R:- | – | – |  |
| 0F 1A/1B | CLR1 r/m,imm3/4 | reg 7 (J64); mem 23 (J59,J61) | `CLR1_IMM` | L881-885 | 02C0-02C3 | 4 / 4 (4) | F:- / W:- / E:02C3 / R:- | – | – |  |
| 0F 1C/1D | SET1 r/m,imm3/4 | reg 6 (J248,J250); mem 21 (J244,J246) | `SET1_IMM` | L871-875 | 02B8-02BB | 3 / 3 (3) | F:- / W:- / E:02BA / R:- | – | – |  |
| 0F 1E/1F | NOT1 r/m,imm3/4 | reg 6 (J196); mem 21 (J191,J193) | `NOT1_IMM` | L891-895 | 02C8-02CB | 3 / 3 (3) | F:- / W:- / E:02CA / R:- | – | – |  |
| 0F 20 | ADD4S | 13+22n: 35/57/79 at n=1/2/3 (J15-J17; M:332) | `ADD4S` | L896-900, L901-905, L906-910, L911-915, L916-920, L921-925 | 02CC-02CF, 02D0-02D3, 02D4-02D7, 02D8-02DB, 02DC-02DF, 02E0-02E3 | 23 / 24 (24) | F:02D2,02D4 / W:02D5,02D7,02DF / E:02E2 / R:- | – | 02DA JMP CNTZ 3 ->02CF; 02DC JMP [-00-] 3 ->02DF; 02DD JMP [-09-] 3 ->02DF | nibble loop: 02DA JMP CNTZ 3 -> 02CF |
| 0F 22 | SUB4S | 56 at n=2 (J275; M:332) | `SUB4S` | L896-900, L901-905, L926-930, L911-915, L916-920, L921-925 | 02CC-02CF, 02D0-02D3, 02E4-02E7, 02D8-02DB, 02DC-02DF, 02E0-02E3 | 23 / 24 (24) | F:02D2,02E4 / W:02E5,02E7,02DF / E:02E2 / R:- | – | 02DA JMP CNTZ 3 ->02CF; 02DC JMP [-00-] 3 ->02DF; 02DD JMP [-09-] 3 ->02DF |  |
| 0F 26 | CMP4S | 55 at n=2 (J71; M:332) | `CMP4S` | L896-900, L901-905, L931-935, L911-915, L916-920, L921-925 | 02CC-02CF, 02D0-02D3, 02E8-02EB, 02D8-02DB, 02DC-02DF, 02E0-02E3 | 23 / 24 (24) | F:02D2,02E8 / W:02E9,02EB,02DF / E:02E2 / R:- | – | 02DA JMP CNTZ 3 ->02CF; 02DC JMP [-00-] 3 ->02DF; 02DD JMP [-09-] 3 ->02DF | sub-row 2 (02E8-02EB) has no MEMW: compare only |
| 0F 24 | (undocumented, CMP4S-like) | not measured (behaviour: undocumented_0f.md:23) | `0F24` | L896-900, L901-905 | 02CC-02CF, 02D0-02D3 | no E (exits via FARJMP) / 8 (8) | F:02D2 / W:- / E:- / R:- | – | – | ROM has sub-rows 0-1 (shared 20/22/24/26) only; no block matches 0F 24 sub-row 2 - continuation not in the sources |
| 0F 21/23/25/27 | (undocumented; tail of the 4S routines as an entry) | not measured; 21/27 behave as 2-byte no-ops (undocumented_0f.md:22) | `0F21_TAIL` | L916-920, L921-925 | 02DC-02DF, 02E0-02E3 | 7 / 8 (8) | F:- / W:02DF / E:02E2 / R:- | – | 02DC JMP [-00-] 3 ->02DF; 02DD JMP [-09-] 3 ->02DF | entering at sub-row 0 of 21 runs the 4S epilogue (02DC-02E3) |
| 0F 28 | ROL4 r/m8 | reg 16 (J231); mem 27 (J230); M:328-329 | `ROL4` | L936-940, L941-945, L946-950 | 02EC-02EF, 02F0-02F3, 02F4-02F7 | 9 / 10 (10) | F:- / W:- / E:02F4 / R:02EF | – | – |  |
| 0F 2A | ROR4 r/m8 | reg 20 (J238); mem 31 (J237); M:328-329 | `ROR4` | L951-955, L941-945, L946-950 | 02F8-02FB, 02F0-02F3, 02F4-02F7 | 9 / 10 (10) | F:- / W:- / E:02F4 / R:02FB | – | – |  |
| 0F 29,2B-2F | (undocumented 28-2F block aliases) | not measured; 0F 2C behaviour undocumented_0f.md:24 | not in the sources | – | – | – | – | – | – | not in the sources: no ROM block matches these second bytes at sub-row 0 |
| 0F 31 | INS r8,r8 | 51 (J104); worst case 120 (M:397-399); M:330 | `INS_REG` | L991-995, L996-1000, L1001-1005, L1006-1010 | 0318-031B, 031C-031F, 0320-0323, 0324-0327 | no E (exits via FARJMP) / 15 (15) | F:031C / W:0326 / E:- / R:031D | INS | 031A JMP Z 6 ->031E |  |
| 0F 39 | INS r8,imm4 | 54 (J105; M:330) | `INS_IMM` | L991-995, L1046-1050, L1001-1005, L1006-1010 | 0318-031B, 0344-0347, 0320-0323, 0324-0327 | no E (exits via FARJMP) / 15 (15) | F:0344 / W:0326 / E:- / R:0345 | INS | 031A JMP Z 6 ->0346 |  |
| 0F 33 | EXT r8,r8 | 43 (J92; M:331) | `EXT_REG` | L956-960, L961-965, L966-970, L971-975, L976-980, L981-985, L641-645 | 02FC-02FF, 0300-0303, 0304-0307, 0308-030B, 030C-030F, 0310-0313, 0200-0203 | 25 / 25 (24) | F:0305,0309 / W:0304 / E:0200 / R:030F,0313 | – | 0305 JMP Z 11 ->0307; 0306 JMP NC 14 ->030A; 0307 JMP Z 14 ->030A; 0312 JMP Z 8 ->0200 |  |
| 0F 3B | EXT r8,imm4 | 43 (J93; M:331) | `EXT_IMM` | L986-990, L961-965, L966-970, L971-975, L976-980, L981-985, L641-645 | 0314-0317, 0300-0303, 0304-0307, 0308-030B, 030C-030F, 0310-0313, 0200-0203 | 25 / 25 (25) | F:0305,0309 / W:0304 / E:0200 / R:030F,0313 | – | 0305 JMP Z 11 ->0307; 0306 JMP NC 14 ->030A; 0307 JMP Z 14 ->030A; 0312 JMP Z 8 ->0200 |  |
| 0F 34/3C | (undocumented; EXT continuation rows as an entry) | 0F 34 = silent lockup (undocumented_0f.md:26; M:434) | `0F34_ENTRY` | L976-980, L981-985, L641-645 | 030C-030F, 0310-0313, 0200-0203 | 9 / 9 (9) | F:- / W:- / E:0200 / R:030F,0313 | – | 0312 JMP Z 8 ->0200 | 0F 34 sub-row 0 is 030C, the middle of EXT |
| 0F 30,32,35-38,3A,3D-3F | (undocumented 30-3F block aliases) | 0F 30 INS-like (undocumented_0f.md:25); others not measured | not in the sources | – | – | – | – | – | – | not in the sources: no ROM block at sub-row 0 |
| 0F FF | BRKEM imm8 | not measured | `BRKEM` | L1051-1055 | 0348-034B | no E (exits via FARJMP) / 2 (2) | F:- / W:- / E:- / R:- | INTEM | – | enters INTEM with COUNT=1; aliases 0F 40/60/80/A0/C0/E4 behave identically (undocumented_0f.md:27) but the ROM pattern for this block is exactly FF - alias dispatch not in the sources |
| 0F other | 0F 00-0F, 40-FE (rest) | 00/04/08/0C 2-byte no-ops (undocumented_0f.md:21) | not in the sources | – | – | – | – | – | – | not in the sources |

169 opcode rows (145 with a ROM routine, 24 not in the ROM).

## Routine catalogue (per-opcode routines, one line per micro-instruction)

Format: `ADDR src->dst, src2->dst2; operation  [flags]`; `—` = blank slot. `Q` pops a queue byte; `M`/`R` = ModR/M r/m and reg operands; `IND` = bus address latch; `OPR` = bus data register; `SIGMA` = ALU result (also the EA for LEA); `dir*sz` = +-1/+-2 from DIR and width; `AL:AH` = byte-swapped AW.

### `ALU_RM`

Blocks: L1 `00?.00???0??.00 00..03,08..0B,10..13,18..1B,20..23,28..2B,30..33,38..3B`. toE 2, total 2, nb 2. Calls: none.

```
0000 M->tmpb, R->tmpa; ALU OPC tmpa
0001 SIGMA->M; CTL [-06-]  [WE]
```

### `ALU_ACC`

Blocks: L6 `00?.00???10?.00 04,05,0C,0D,14,15,1C,1D,24,25,2C,2D,34,35,3C,3D`. toE 3, total 4, nb 4. Calls: none.

```
0004 M->tmpb, Q->tmpa; JMP OP8 2 ->0006
0005 Q->tmpaH
0006 ALU OPC tmpa  [E]
0007 SIGMA->M  [W]
```

### `POP_SREG`

Blocks: L11 `00?.000??111.00 07,0F,17,1F`. toE 4, total 4, nb 4. Calls: none.

```
0008 SP->IND; CTL MEMR SS
0009 SP->tmpb; ALU INC2 tmpb
000A SIGMA->SP
000B OPR->R  [FE]
```

### `PUSH_SREG`

Blocks: L16 `00?.000??110.00 06,0E,16,1E`. toE 3, total 3, nb 3. Calls: none.

```
000C SP->tmpb; ALU DEC2 tmpb
000D R->OPR, SIGMA->IND; CTL MEMW SS
000E SIGMA->SP  [E]
```

### `DAA`

Blocks: L21 `00?.00100111.00 27`. toE 2, total 3, nb 3. Calls: none.

```
0010 AX->tmpbL; ALU ADJD tmpb
0011 ONES->tmpa; ALU ADD tmpa  [E]
0012 SIGMA->AL, SIGMA->[-03-]  [W]
```

### `DAS`

Blocks: L26 `00?.00101111.00 2F`. toE 2, total 3, nb 3. Calls: none.

```
0014 AX->tmpbL; ALU ADJD tmpb
0015 ONES->tmpa; ALU SUB tmpa  [E]
0016 SIGMA->AL, SIGMA->[-03-]  [W]
```

### `AAA`

Blocks: L31 `00?.00110111.00 37`; L36 `00?.0011?111.01 37,3F`. toE 6, total 6, nb 6. Calls: none.

```
0018 AX->tmpbL; ALU ADJA tmpb
0019 ONES->tmpa; ALU ADD tmpa
001A SIGMA->AL, SIGMA->[-03-]; ALU INC tmpb  [W]
001B AL:AH->tmpb; JMP NC 5 ->001D
001C SIGMA->AH
001D   [E]
```

### `AAS`

Blocks: L41 `00?.00111111.00 3F`; L36 `00?.0011?111.01 37,3F`. toE 6, total 6, nb 6. Calls: none.

```
0020 AX->tmpbL; ALU ADJA tmpb
0021 ONES->tmpa; ALU SUB tmpa
0022 SIGMA->AL, SIGMA->[-03-]; ALU DEC tmpb  [W]
0023 AL:AH->tmpb; JMP NC 5 ->001D
001C SIGMA->AH
001D   [E]
```

### `INCDEC_R16`

Blocks: L46 `00?.0100????.00 40..4F`. toE 1, total 2, nb 2. Calls: none.

```
0024 M->tmpb; ALU OPC tmpb  [E]
0025 SIGMA->M  [W]
```

### `PUSH_R16`

Blocks: L51 `00?.01010???.00 50..57`. toE 2, total 3, nb 3. Calls: none.

```
0028 SP->tmpb; ALU DEC2 tmpb
0029 SIGMA->SP, SIGMA->IND; CTL MEMW SS  [E]
002A M->OPR
```

### `POP_R16`

Blocks: L56 `00?.01011???.00 58..5F`. toE 4, total 4, nb 4. Calls: none.

```
002C SP->IND; CTL MEMR SS
002D SP->tmpb; ALU INC2 tmpb
002E SIGMA->SP
002F OPR->M  [FE]
```

### `FPO2`

Blocks: L61 `00?.0110011?.00 66,67`. toE 1, total 1, nb 1. Calls: none.

```
0030   [E]
```

### `JCC`

Blocks: L66 `00?.0111????.00 70..7F`; L71 `00?.0111????.01 70..7F`. toE 3, total 6, nb 5. Calls: none.

```
0034 Q->tmpbL; ALU ADD tmpa
0035 JMP OPC 4 ->0038
0036   [E]
0037 —
0038 PC->tmpa; CTL SUSP
0039 SIGMA->PC; CTL FLUSH  [E]
```

### `GRP1`

Blocks: L76 `00?.100000??.00 80..83`; L81 `00?.100000??.01 80..83`. toE 5, total 5, nb 5. Calls: none.

```
003C Q->tmpbL; JMP OP8 2 ->003E
003D Q->tmpbH
003E tmpb->tmpa; ALU OPC tmpa
003F M->tmpb
0040 SIGMA->M; CTL [-06-]  [WE]
```

### `TEST_RM`

Blocks: L86 `00?.1000010?.00 84,85`. toE 1, total 2, nb 2. Calls: none.

```
0044 M->tmpa, R->tmpb; ALU AND tmpa  [E]
0045 SIGMA->NULL  [W]
```

### `XCHG_RM`

Blocks: L91 `00?.1000011?.00 86,87`. toE 2, total 3, nb 3. Calls: none.

```
0048 M->tmpa, R->tmpb
0049 tmpa->R; CTL [-06-]  [E]
004A tmpb->M
```

### `MOV_RM`

Blocks: L96 `00?.100010??.00 88..8B`. toE 2, total 2, nb 2. Calls: none.

```
004C R->tmpa
004D tmpa->M; CTL [-06-]  [E]
```

### `MOV_SREG`

Blocks: L101 `00?.100011?0.00 8C,8E`. toE 1, total 1, nb 1. Calls: none.

```
0050 R->M; CTL [-06-]  [E]
```

### `LEA`

Blocks: L106 `00?.10001101.00 8D`. toE 1, total 2, nb 2. Calls: none.

```
0054   [E]
0055 SIGMA->R
```

### `POP_RM`

Blocks: L111 `00?.10001111.00 8F`. toE 4, total 4, nb 4. Calls: none.

```
0058 SIGMA->tmpa; ALU INC2 tmpb
0059 SP->IND, SP->tmpb; CTL MEMR SS
005A SIGMA->SP; ALU PASS tmpa  [F]
005B SIGMA->IND; CTL [-06-]  [E]
```

### `XCHG_AX`

Blocks: L116 `00?.10010???.00 90..97`. toE 2, total 3, nb 3. Calls: none.

```
005C M->tmpb, AX->tmpa
005D tmpa->M  [E]
005E tmpb->AX
```

### `CBW`

Blocks: L121 `00?.10011000.00 98`. toE 1, total 2, nb 2. Calls: none.

```
0060 AX->tmpbL  [E]
0061 tmpb->AX
```

### `CWD`

Blocks: L126 `00?.10011001.00 99`. toE 4, total 4, nb 4. Calls: none.

```
0064 ZEROS->DX, AX->tmpb
0065 JMP NS 3 ->0067
0066 ONES->DX
0067   [E]
```

### `CALL_FAR_DIR`

Blocks: L131 `00?.10011010.00 9A`. toE -, total 4, nb 4. Calls: CALLF.

```
0068 Q->tmpaL
0069 Q->tmpaH
006A Q->tmpbL
006B Q->tmpbH; FARJMP CALLF
```

### `WAIT`

Blocks: L136 `00?.10011011.00 9B`; L141 `00?.10011011.01 9B`. toE 2, total 8, nb 7. Calls: none.

```
006C JMP BUSY 3 ->006F
006D CTL [-0A-]  [E]
006E —
006F JMP INTR 5 ->0071
0070 JMP always 0 ->006C
0071 CTL SUSP
0072 PC->tmpb; ALU DEC tmpb
0073 SIGMA->PC; CTL FLUSH  [E]
```

### `PUSHF`

Blocks: L146 `00?.10011100.00 9C`. toE 2, total 3, nb 3. Calls: none.

```
0074 SP->tmpb; ALU DEC2 tmpb
0075 FLAGS->OPR, SIGMA->IND; CTL MEMW SS  [E]
0076 SIGMA->SP
```

### `POPF`

Blocks: L151 `00?.10011101.00 9D`. toE 3, total 4, nb 4. Calls: none.

```
0078 SP->IND; CTL MEMR SS
0079 SP->tmpb; ALU INC2 tmpb
007A OPR->FLAGS  [FE]
007B SIGMA->SP
```

### `SAHF`

Blocks: L156 `00?.10011110.00 9E`. toE 2, total 3, nb 3. Calls: none.

```
007C AL:AH->tmpaL
007D FLAGS->tmpaH  [E]
007E tmpa->FLAGS
```

### `LAHF`

Blocks: L161 `00?.10011111.00 9F`. toE 1, total 1, nb 1. Calls: none.

```
0080 FLAGS->AH  [E]
```

### `MOV_ACC_DMEM`

Blocks: L166 `00?.1010000?.00 A0,A1`. toE 4, total 4, nb 4. Calls: none.

```
0084 Q->tmpbL
0085 Q->tmpbH
0086 tmpb->IND; CTL MEMR
0087 OPR->M  [FE]
```

### `MOV_DMEM_ACC`

Blocks: L171 `00?.1010001?.00 A2,A3`. toE 3, total 4, nb 4. Calls: none.

```
0088 Q->tmpbL
0089 Q->tmpbH
008A tmpb->IND; CTL MEMW  [E]
008B M->OPR
```

### `MOVS`

Blocks: L176 `000.1010010?.00 <norep> A4,A5`. toE 4, total 4, nb 4. Calls: none.

```
008C dir*sz->tmpc, SI->tmpb; ALU ADD tmpc
008D SI->IND; CTL MEMR
008E SIGMA->SI, DI->tmpb; ALU ADD tmpc
008F DI->IND; CTL MEMW ES  [E]
```

### `REP_MOVS`

Blocks: L186 `001.1010010?.00 <rep> A4,A5`; L191 `00?.1010010?.01 A4,A5`. toE -, total 8, nb 8. Calls: REPX.

```
0094 CX->COUNT, CX->tmpb; ALU PASS tmpb
0095 SIGMA->NULL; ALU ADD tmpc
0096 dir*sz->tmpc; JMP Z 7 ->009B
0097 SI->IND, DI->tmpb; CTL MEMR
0098 SIGMA->DI
0099 tmpb->IND, SI->tmpb; CTL MEMW ES
009A SIGMA->SI; JMP REP 3 ->0097
009B COUNT->CX; FARJMP REPX
```

### `CMPS`

Blocks: L196 `000.1010011?.00 <norep> A6,A7`; L201 `000.1010011?.01 <norep> A6,A7`. toE 7, total 8, nb 8. Calls: none.

```
009C dir*sz->tmpc, SI->tmpb; ALU ADD tmpc
009D SI->IND; CTL MEMR
009E SIGMA->SI, DI->tmpb
009F DI->IND, SIGMA->tmpa; CTL MEMR ES
00A0 OPR->tmpb  [F]
00A1 tmpa->DI; ALU SUB tmpa
00A2 OPR->tmpa  [FE]
00A3 SIGMA->NULL  [W]
```

### `REP_CMPS`

Blocks: L206 `001.1010?11?.00 <rep> A6,A7,AE,AF`; L211 `001.1010011?.01 <rep> A6,A7`; L216 `001.1010011?.10 <rep> A6,A7`. toE -, total 12, nb 12. Calls: REPX.

```
00A4 CX->COUNT, CX->tmpb; ALU PASS tmpb
00A5 dir*sz->tmpc, SIGMA->[-03-]; ALU ADD tmpc
00A6 JMP Z 11 ->00AF
00A7 DI->IND, DI->tmpb; CTL MEMR ES
00A8 SIGMA->DI, SI->tmpb
00A9 SI->IND, SIGMA->tmpb; CTL MEMR
00AA OPR->tmpa  [F]
00AB tmpb->SI; ALU SUB tmpa
00AC OPR->tmpb  [F]
00AD SIGMA->NULL; ALU ADD tmpc  [W]
00AE JMP REP 3 ->00A7
00AF COUNT->CX; FARJMP REPX
```

### `TEST_ACC`

Blocks: L226 `00?.1010100?.00 A8,A9`. toE 3, total 4, nb 4. Calls: none.

```
00B4 AX->tmpb, Q->tmpa; JMP OP8 2 ->00B6
00B5 Q->tmpaH
00B6 ALU AND tmpa  [E]
00B7 SIGMA->NULL  [W]
```

### `STOS`

Blocks: L231 `000.1010101?.00 <norep> AA,AB`. toE 3, total 4, nb 4. Calls: none.

```
00B8 dir*sz->tmpc, DI->tmpb; ALU ADD tmpc
00B9 DI->IND; CTL MEMW ES
00BA M->OPR  [E]
00BB SIGMA->DI
```

### `REP_STOS`

Blocks: L236 `001.1010101?.00 <rep> AA,AB`; L241 `001.1010101?.01 <rep> AA,AB`. toE -, total 6, nb 6. Calls: REPX.

```
00BC CX->COUNT, CX->tmpb; ALU PASS tmpb
00BD dir*sz->tmpc, SIGMA->[-03-]; ALU ADD tmpc
00BE M->OPR; JMP Z 5 ->00C1
00BF DI->IND, DI->tmpb; CTL MEMW ES
00C0 SIGMA->DI; JMP REP 3 ->00BF
00C1 COUNT->CX; FARJMP REPX
```

### `LODS`

Blocks: L246 `000.1010110?.00 <norep> AC,AD`. toE 4, total 4, nb 4. Calls: none.

```
00C4 dir*sz->tmpc, SI->tmpb; ALU ADD tmpc
00C5 SI->IND; CTL MEMR
00C6 SIGMA->SI
00C7 OPR->M  [FE]
```

### `REP_LODS`

Blocks: L251 `001.1010110?.00 <rep> AC,AD`; L256 `001.1010110?.01 <rep> AC,AD`. toE -, total 8, nb 8. Calls: REPX.

```
00C8 CX->COUNT, CX->tmpb; ALU PASS tmpb
00C9 dir*sz->tmpc, SIGMA->[-03-]; ALU ADD tmpc
00CA JMP Z 7 ->00CF
00CB SI->IND, SI->tmpb; CTL MEMR
00CC SIGMA->SI
00CD OPR->M  [F]
00CE JMP REP 3 ->00CB
00CF COUNT->CX; FARJMP REPX
```

### `SCAS`

Blocks: L261 `000.1010111?.00 <norep> AE,AF`; L266 `000.1010111?.01 <norep> AE,AF`. toE 6, total 6, nb 6. Calls: none.

```
00D0 dir*sz->tmpc, DI->tmpb; ALU ADD tmpc
00D1 DI->IND; CTL MEMR ES
00D2 SIGMA->DI; ALU SUB tmpa
00D3 M->tmpb
00D4 OPR->tmpa  [F]
00D5 SIGMA->NULL  [WE]
```

### `REP_SCAS`

Blocks: L206 `001.1010?11?.00 <rep> A6,A7,AE,AF`; L271 `001.1010111?.01 <rep> AE,AF`; L276 `001.1010111?.10 <rep> AE,AF`. toE -, total 12, nb 10. Calls: REPX.

```
00A4 CX->COUNT, CX->tmpb; ALU PASS tmpb
00A5 dir*sz->tmpc, SIGMA->[-03-]; ALU ADD tmpc
00A6 JMP Z 11 ->00DF
00A7 DI->IND, DI->tmpb; CTL MEMR ES
00D8 SIGMA->DI; ALU SUB tmpa
00D9 M->tmpb
00DA OPR->tmpa  [F]
00DB SIGMA->NULL; ALU ADD tmpc  [W]
00DC JMP REP 3 ->00A7
00DD —
00DE —
00DF COUNT->CX; FARJMP REPX
```

### `MOV_R_IMM`

Blocks: L281 `00?.1011????.00 B0..BF`. toE 3, total 3, nb 3. Calls: none.

```
00E0 Q->tmpbL; JMP OP8 2 ->00E2
00E1 Q->tmpbH
00E2 tmpb->M  [E]
```

### `RET_IMM`

Blocks: L286 `00?.1100?010.00 C2,CA`; L291 `00?.11000010.01 C2`. toE 7, total 7, nb 6. Calls: none.

```
00E4 Q->tmpbL
00E5 Q->tmpbH; ALU INC2 tmpa
00E6 SP->IND, SP->tmpa; CTL SUSP MEMR SS
00E7 —
00E8 SIGMA->tmpa; ALU ADD tmpa
00E9 SIGMA->SP
00EA OPR->PC; CTL FLUSH  [FE]
```

### `RETF_IMM`

Blocks: L286 `00?.1100?010.00 C2,CA`; L296 `00?.11001010.01 CA`. toE -, total 6, nb 5. Calls: RETF.

```
00E4 Q->tmpbL
00E5 Q->tmpbH; ALU INC2 tmpa
00E6 SP->IND, SP->tmpa; CTL SUSP MEMR SS
00E7 —
00EC SIGMA->IND, SIGMA->tmpa; CTL MEMR SS
00ED SIGMA->tmpa; FARJMP RETF
```

### `RET`

Blocks: L301 `00?.11000011.00 C3`. toE 4, total 4, nb 4. Calls: none.

```
00F0 SP->IND, SP->tmpa; CTL SUSP MEMR SS
00F1 ALU INC2 tmpa
00F2 SIGMA->SP
00F3 OPR->PC; CTL FLUSH  [FE]
```

### `RETF_`

Blocks: L306 `00?.11001011.00 CB`. toE -, total 4, nb 4. Calls: RETF.

```
00F4 SP->IND, SP->tmpa; CTL SUSP MEMR SS
00F5 ZEROS->tmpb; ALU INC2 tmpa
00F6 SIGMA->IND, SIGMA->tmpa; CTL MEMR SS
00F7 SIGMA->tmpa; FARJMP RETF
```

### `LES`

Blocks: L311 `00?.11000100.00 C4`. toE 3, total 3, nb 3. Calls: none.

```
00F8 OPR->R, SIGMA->tmpb; ALU INC2 tmpb  [F]
00F9 SIGMA->IND; CTL MEMR
00FA OPR->ES  [FE]
```

### `LDS`

Blocks: L316 `00?.11000101.00 C5`. toE 3, total 3, nb 3. Calls: none.

```
00FC OPR->R, SIGMA->tmpb; ALU INC2 tmpb  [F]
00FD SIGMA->IND; CTL MEMR
00FE OPR->DS  [FE]
```

### `MOV_RM_IMM`

Blocks: L321 `00?.1100011?.00 C6,C7`. toE 3, total 3, nb 3. Calls: none.

```
0100 Q->tmpbL; JMP OP8 2 ->0102
0101 Q->tmpbH
0102 tmpb->M; CTL [-06-]  [E]
```

### `INT3`

Blocks: L326 `00?.11001100.00 CC`. toE -, total 2, nb 2. Calls: INT.

```
0104 CONST(3)->tmpbL; CTL SUSP
0105 FARJMP INT
```

### `INT_N`

Blocks: L331 `00?.11001101.00 CD`. toE -, total 1, nb 1. Calls: INT.

```
0108 Q->tmpbL; FARJMP INT
```

### `INTO`

Blocks: L336 `00?.11001110.00 CE`. toE 2, total 4, nb 3. Calls: INT.

```
010C CONST(4)->tmpbL; JMP O 3 ->010F
010D   [E]
010E —
010F FARJMP INT
```

### `IRET_`

Blocks: L341 `00?.11001111.00 CF`. toE -, total 2, nb 2. Calls: IRET.

```
0110 SP->IND, SP->tmpa; CTL SUSP MEMR SS
0111 FARJMP IRET
```

### `SHIFT_1`

Blocks: L346 `00?.1101000?.00 D0,D1`. toE 4, total 4, nb 4. Calls: none.

```
0114 CONST(1)->COUNT
0115 M->tmpb; ALU PASS tmpb
0116 SIGMA->tmpb; ALU OPC tmpb  [WR]
0117 SIGMA->M; CTL [-06-]  [E]
```

### `SHIFT_CL`

Blocks: L351 `00?.1101001?.00 D2,D3`. toE -, total 4, nb 4. Calls: SHIFT.

```
0118 M->tmpb; ALU PASS tmpa
0119 CX->tmpaL
011A tmpa->COUNT, SIGMA->[-03-]; ALU PASS tmpb
011B FARJMP SHIFT
```

### `AAM`

Blocks: L356 `00?.11010100.00 D4`; L361 `00?.11010100.01 D4`. toE 6, total 7, nb 7. Calls: none.

```
011C Q->tmpc, AX->tmpa
011D ZEROS->tmpb
011E CONST(8)->COUNT; ALU SUB tmpc
011F SIGMA->tmpb; ALU DIV tmpc  [R]
0120 SIGMA->NULL, SIGMA->tmpb; ALU DIV tmpc
0121 tmpa->AH; ALU PASS tmpb  [E]
0122 SIGMA->AL  [W]
```

### `AAD`

Blocks: L366 `00?.11010101.00 D5`; L371 `00?.11010101.01 D5`. toE 7, total 8, nb 8. Calls: none.

```
0124 AL:AH->tmpa, Q->tmpb
0125 AL:AH->tmpb; ALU ADD tmpb
0126 SIGMA->tmpb
0127 SIGMA->tmpb; ALU ADD tmpa
0128 SIGMA->tmpb; ALU ADD tmpb
0129 SIGMA->tmpb
012A ZEROS->AH, AX->tmpa; ALU ADD tmpa  [E]
012B SIGMA->AL  [W]
```

### `XLAT`

Blocks: L376 `00?.11010111.00 D7`. toE 3, total 3, nb 3. Calls: none.

```
012C AX->tmpaL, BX->tmpb
012D SIGMA->IND; CTL MEMR
012E OPR->AL  [FE]
```

### `ESC`

Blocks: L381 `00?.11011???.00 D8..DF`. toE 1, total 1, nb 1. Calls: none.

```
0130   [E]
```

### `LOOPCC`

Blocks: L386 `00?.1110000?.00 E0,E1`; L391 `00?.111000??.01 E0..E3`. toE 4, total 8, nb 7. Calls: none.

```
0134 CX->COUNT
0135 —
0136 Q->tmpaL; JMP REP 4 ->0138
0137   [E]
0138 COUNT->CX
0139 tmpa->tmpbL; CTL SUSP
013A PC->tmpa; ALU ADD tmpa
013B SIGMA->PC; CTL FLUSH  [E]
```

### `LOOP`

Blocks: L396 `00?.11100010.00 E2`; L391 `00?.111000??.01 E0..E3`. toE 4, total 8, nb 8. Calls: none.

```
013C Q->tmpaL, CX->tmpb; ALU DEC tmpb
013D SIGMA->CX
013E CX->COUNT; JMP NZ 5 ->0139
013F   [E]
0138 COUNT->CX
0139 tmpa->tmpbL; CTL SUSP
013A PC->tmpa; ALU ADD tmpa
013B SIGMA->PC; CTL FLUSH  [E]
```

### `JCXZ`

Blocks: L401 `00?.11100011.00 E3`; L391 `00?.111000??.01 E0..E3`. toE 4, total 8, nb 8. Calls: none.

```
0140 Q->tmpaL, CX->tmpb; ALU PASS tmpb
0141 SIGMA->NULL
0142 JMP Z 5 ->0139
0143 CX->COUNT  [E]
0138 COUNT->CX
0139 tmpa->tmpbL; CTL SUSP
013A PC->tmpa; ALU ADD tmpa
013B SIGMA->PC; CTL FLUSH  [E]
```

### `IN_IMM`

Blocks: L406 `00?.1110010?.00 E4,E5`. toE 3, total 3, nb 3. Calls: none.

```
0144 Q->tmpaL
0145 tmpa->IND; CTL MEMR IO
0146 OPR->M  [FE]
```

### `OUT_IMM`

Blocks: L411 `00?.1110011?.00 E6,E7`. toE 2, total 2, nb 2. Calls: none.

```
0148 Q->tmpaL; ALU PASS tmpa
0149 M->OPR, SIGMA->IND; CTL MEMW IO  [E]
```

### `CALL_NEAR`

Blocks: L416 `00?.11101000.00 E8`; L421 `00?.11101000.01 E8`. toE 6, total 6, nb 6. Calls: none.

```
014C Q->tmpaL, SP->tmpb; ALU DEC2 tmpb
014D Q->tmpaH
014E SIGMA->SP, SIGMA->IND; CTL SUSP
014F PC->tmpb; ALU ADD tmpa
0150 SIGMA->PC; CTL FLUSH
0151 tmpb->OPR; CTL MEMW SS  [E]
```

### `JMP_NEAR`

Blocks: L426 `00?.11101001.00 E9`. toE 4, total 4, nb 4. Calls: none.

```
0154 Q->tmpbL; ALU ADD tmpa
0155 Q->tmpbH; JMP always 2 ->0156
0156 PC->tmpa; CTL SUSP
0157 SIGMA->PC; CTL FLUSH  [E]
```

### `JMP_SHORT`

Blocks: L431 `00?.11101011.00 EB`. toE 4, total 4, nb 4. Calls: none.

```
0158 Q->tmpbL; ALU ADD tmpa
0159 CTL SUSP
015A PC->tmpa
015B SIGMA->PC; CTL FLUSH  [E]
```

### `JMP_FAR_DIR`

Blocks: L436 `00?.11101010.00 EA`; L441 `00?.11101010.01 EA`. toE 6, total 6, nb 6. Calls: none.

```
015C Q->tmpbL
015D Q->tmpbH
015E Q->tmpaL
015F Q->tmpaH
0160 tmpa->CS; CTL SUSP
0161 tmpb->PC; CTL FLUSH  [E]
```

### `IN_DX`

Blocks: L446 `00?.1110110?.00 EC,ED`. toE 2, total 2, nb 2. Calls: none.

```
0164 DX->IND; CTL MEMR IO
0165 OPR->M  [FE]
```

### `OUT_DX`

Blocks: L451 `00?.1110111?.00 EE,EF`. toE 1, total 2, nb 2. Calls: none.

```
0168 DX->IND; CTL MEMW IO  [E]
0169 M->OPR
```

### `F6_TEST`

Blocks: L456 `010.??00????.00 <F6/F7> 00..0F,40..4F,80..8F,C0..CF`. toE 3, total 4, nb 4. Calls: none.

```
016C Q->tmpbL; JMP OP8 2 ->016E
016D Q->tmpbH
016E M->tmpa; ALU AND tmpa  [E]
016F SIGMA->NULL  [W]
```

### `F6_NEG`

Blocks: L461 `010.??011???.00 <F6/F7> 18..1F,58..5F,98..9F,D8..DF`. toE 2, total 2, nb 2. Calls: none.

```
0170 M->tmpb; ALU OPC tmpb
0171 SIGMA->M; CTL [-06-]  [WE]
```

### `F6_NOT`

Blocks: L466 `010.??010???.00 <F6/F7> 10..17,50..57,90..97,D0..D7`. toE 2, total 2, nb 2. Calls: none.

```
0174 M->tmpb; ALU OPC tmpb
0175 SIGMA->M; CTL [-06-]  [E]
```

### `F6_MUL`

Blocks: L471 `010.??100???.00 <F6/F7> 20..27,60..67,A0..A7,E0..E7`; L476 `010.??100???.01 <F6/F7> 20..27,60..67,A0..A7,E0..E7`; L481 `010.??100???.10 <F6/F7> 20..27,60..67,A0..A7,E0..E7`. toE -, total 9, nb 9. Calls: MULX.

```
0178 M->tmpc, ZEROS->tmpb; ALU PASS tmpc
0179 AX->tmpa
017A CONST(8)->COUNT; JMP OP8 4 ->017C
017B CONST(16)->COUNT
017C SIGMA->tmpb; ALU MUL tmpc  [R]
017D ALU PASS tmpb
017E tmpa->AX; JMP OP8 8 ->0180
017F tmpb->DX, SIGMA->[-03-]; FARJMP MULX
0180 tmpb->AH, SIGMA->[-03-]; FARJMP MULX
```

### `F6_IMUL`

Blocks: L486 `010.??101???.00 <F6/F7> 28..2F,68..6F,A8..AF,E8..EF`. toE -, total 2, nb 2. Calls: IMUL.

```
0184 M->tmpa, AX->tmpb; ALU [-1E-] tmpb
0185 FARJMP IMUL
```

### `F6_DIV`

Blocks: L491 `010.??110???.00 <F6/F7> 30..37,70..77,B0..B7,F0..F7`; L496 `010.??110???.01 <F6/F7> 30..37,70..77,B0..B7,F0..F7`; L501 `010.??110???.10 <F6/F7> 30..37,70..77,B0..B7,F0..F7`; L506 `010.??110???.11 <F6/F7> 30..37,70..77,B0..B7,F0..F7`. toE 12, total 15, nb 14. Calls: INT.

```
0188 M->tmpc, AX->tmpa; ALU SUB tmpc
0189 DX->tmpb; JMP OP8 4 ->018C
018A CONST(16)->COUNT
018B SIGMA->NULL; JMP always 7 ->018F  [W]
018C AL:AH->tmpb
018D CONST(8)->COUNT
018E SIGMA->NULL  [W]
018F JMP NC 13 ->0195
0190 SIGMA->tmpb; ALU DIV tmpc  [R]
0191 SIGMA->NULL, SIGMA->tmpb; ALU DIV tmpc
0192 tmpa->AX; JMP OP8 14 ->0196
0193 tmpb->DX  [E]
0194 —
0195 ZEROS->tmpbL; FARJMP INT
0196 tmpb->AH  [E]
```

### `F6_IDIV`

Blocks: L511 `010.??111???.00 <F6/F7> 38..3F,78..7F,B8..BF,F8..FF`; L516 `010.??111???.01 <F6/F7> 38..3F,78..7F,B8..BF,F8..FF`. toE -, total 8, nb 8. Calls: IDIV.

```
0198 M->tmpb; ALU [-1E-] tmpb
0199 CONST(8)->COUNT; CTL [-07-]
019A SIGMA->tmpc; ALU PASS tmpb
019B DX->tmpb, SIGMA->tmpa; JMP OP8 5 ->019D
019C CONST(16)->COUNT; JMP always 6 ->019E
019D AL:AH->tmpb
019E CTL [-0C-]
019F FARJMP IDIV
```

### `FF_INCDEC`

Blocks: L551 `011.??00????.00 <FE/FF> 00..0F,40..4F,80..8F,C0..CF`. toE 2, total 2, nb 2. Calls: none.

```
01B8 M->tmpb; ALU OPC tmpb
01B9 SIGMA->M; CTL [-06-]  [WE]
```

### `FF_CALL_NEAR`

Blocks: L556 `011.??010???.00 <FE/FF> 10..17,50..57,90..97,D0..D7`. toE 4, total 4, nb 4. Calls: none.

```
01BC PC->tmpa, SP->tmpb; ALU DEC2 tmpb
01BD M->PC, SIGMA->IND; CTL FLUSH
01BE SIGMA->SP; CTL MEMW SS
01BF tmpa->OPR  [E]
```

### `FF_CALL_FAR`

Blocks: L561 `011.??011???.00 <FE/FF> 18..1F,58..5F,98..9F,D8..DF`. toE -, total 4, nb 4. Calls: CALLF.

```
01C0 SIGMA->tmpb; CTL SUSP
01C1 OPR->tmpa; ALU INC2 tmpb  [F]
01C2 SIGMA->IND; CTL MEMR
01C3 OPR->tmpb; FARJMP CALLF  [F]
```

### `FF_JMP_NEAR`

Blocks: L566 `011.??100???.00 <FE/FF> 20..27,60..67,A0..A7,E0..E7`. toE 1, total 1, nb 1. Calls: none.

```
01C4 M->PC; CTL FLUSH  [E]
```

### `FF_JMP_FAR`

Blocks: L571 `011.??101???.00 <FE/FF> 28..2F,68..6F,A8..AF,E8..EF`. toE 4, total 4, nb 4. Calls: none.

```
01C8 OPR->tmpb, SIGMA->tmpa; ALU INC2 tmpa  [F]
01C9 SIGMA->IND; CTL SUSP MEMR
01CA OPR->CS  [F]
01CB tmpb->PC; CTL FLUSH  [E]
```

### `FF_PUSH`

Blocks: L576 `011.??11????.00 <FE/FF> 30..3F,70..7F,B0..BF,F0..FF`. toE 3, total 3, nb 3. Calls: none.

```
01CC SP->tmpb; ALU DEC2 tmpb
01CD SIGMA->SP
01CE M->OPR, SIGMA->IND; CTL MEMW SS  [E]
```

### `PUSHA_ENTRY`

Blocks: L711 `00?.01100000.00 60`. toE -, total 4, nb 4. Calls: PUSHA.

```
0238 SP->tmpb; ALU DEC2 tmpb
0239 AX->OPR, SIGMA->IND  [F]
023A SIGMA->tmpb; CTL MEMW SS
023B CX->OPR; FARJMP PUSHA  [F]
```

### `POPA_ENTRY`

Blocks: L736 `00?.01100001.00 61`. toE -, total 4, nb 4. Calls: POPA.

```
024C SP->IND, SP->tmpb; CTL MEMR SS
024D ALU INC2 tmpb
024E SIGMA->tmpb, SIGMA->IND; CTL MEMR SS
024F OPR->DI; FARJMP POPA  [F]
```

### `ENTER_ENTRY`

Blocks: L761 `00?.11001000.00 C8`. toE -, total 4, nb 4. Calls: ENTER.

```
0260 Q->tmpaL, SP->tmpb; ALU DEC2 tmpb
0261 Q->tmpaH, SIGMA->IND
0262 CTL MEMW SS
0263 BP->OPR; FARJMP ENTER  [F]
```

### `LEAVE`

Blocks: L786 `00?.11001001.00 C9`. toE 4, total 4, nb 4. Calls: none.

```
0274 BP->IND, BP->tmpb; CTL MEMR SS
0275 CONST(2)->tmpa; ALU ADD tmpa
0276 SIGMA->SP
0277 OPR->BP  [FE]
```

### `CHKIND`

Blocks: L791 `00?.01100010.00 62`; L796 `00?.01100010.01 62`; L801 `00?.01100010.10 62`. toE 9, total 12, nb 11. Calls: INT.

```
0278 OPR->tmpc, SIGMA->tmpa; ALU INC2 tmpa  [F]
0279 FLAGS->COUNT, SIGMA->IND; CTL MEMR
027A R->tmpb; ALU SUB tmpc
027B SIGMA->NULL  [W]
027C COUNT->FLAGS, R->tmpa; JMP L 10 ->0282
027D OPR->tmpb; ALU SUB tmpa  [F]
027E SIGMA->NULL  [W]
027F COUNT->FLAGS; JMP L 11 ->0283
0280   [E]
0281 —
0282 OPR->tmpa  [F]
0283 CONST(5)->tmpbL; FARJMP INT
```

### `PUSH_IMM8`

Blocks: L806 `00?.01101010.00 6A`. toE 3, total 4, nb 4. Calls: none.

```
0284 Q->tmpa, SP->tmpb; ALU DEC2 tmpb
0285 SIGMA->SP, SIGMA->IND; CTL MEMW SS
0286 tmpa->tmpbL  [E]
0287 tmpb->OPR
```

### `PUSH_IMM16`

Blocks: L811 `00?.01101000.00 68`. toE 4, total 4, nb 4. Calls: none.

```
0288 Q->tmpaL, SP->tmpb; ALU DEC2 tmpb
0289 Q->tmpaH
028A tmpa->OPR, SIGMA->IND; CTL MEMW SS
028B SIGMA->SP  [E]
```

### `SHIFT_IMM`

Blocks: L816 `00?.1100000?.00 C0,C1`. toE -, total 4, nb 4. Calls: SHIFT.

```
028C Q->tmpaL; ALU PASS tmpa
028D M->tmpb
028E tmpa->COUNT, SIGMA->[-03-]; ALU PASS tmpb
028F FARJMP SHIFT
```

### `IMUL_IMM`

Blocks: L821 `00?.011010?1.00 69,6B`. toE -, total 4, nb 4. Calls: IMULI.

```
0290 Q->tmpbL; JMP OP8 2 ->0292
0291 Q->tmpbH
0292 M->tmpa; ALU [-1E-] tmpb
0293 FARJMP IMULI
```

### `INM`

Blocks: L826 `000.0110110?.00 <norep> 6C,6D`. toE 3, total 4, nb 4. Calls: none.

```
0294 DX->IND; CTL MEMR IO
0295 dir*sz->tmpa, DI->tmpb
0296 DI->IND; CTL MEMW ES  [E]
0297 SIGMA->DI
```

### `REP_INM`

Blocks: L831 `001.0110110?.00 <rep> 6C,6D`; L836 `001.0110110?.01 <rep> 6C,6D`. toE -, total 8, nb 7. Calls: REPX.

```
0298 CX->COUNT, CX->tmpb; ALU PASS tmpb
0299 SIGMA->NULL; ALU ADD tmpc
029A dir*sz->tmpc; JMP Z 7 ->029F
029B DX->IND; CTL MEMR IO
029C —
029D DI->IND, DI->tmpb; CTL MEMW ES
029E SIGMA->DI; JMP REP 3 ->029B
029F COUNT->CX; FARJMP REPX
```

### `OUTM`

Blocks: L841 `000.0110111?.00 <norep> 6E,6F`. toE 3, total 4, nb 4. Calls: none.

```
02A0 SI->IND; CTL MEMR
02A1 dir*sz->tmpa, SI->tmpb
02A2 DX->IND; CTL MEMW IO  [E]
02A3 SIGMA->SI
```

### `REP_OUTM`

Blocks: L846 `001.0110111?.00 <rep> 6E,6F`; L851 `001.0110111?.01 <rep> 6E,6F`. toE -, total 8, nb 8. Calls: REPX.

```
02A4 CX->COUNT, CX->tmpb; ALU PASS tmpb
02A5 SIGMA->NULL; ALU ADD tmpc
02A6 dir*sz->tmpc; JMP Z 7 ->02AB
02A7 SI->IND, SI->tmpb; CTL MEMR
02A8 SIGMA->SI
02A9 DX->IND; CTL MEMW IO
02AA JMP REP 3 ->02A7
02AB COUNT->CX; FARJMP REPX
```

### `TEST1_CL`

Blocks: L856 `100.0001000?.00 <0F> 10,11`. toE 3, total 3, nb 3. Calls: none.

```
02AC M->tmpb, CX->tmpa; ALU BIT tmpa
02AD ONES->tmpa; ALU AND tmpa
02AE SIGMA->NULL  [WE]
```

### `TEST1_IMM`

Blocks: L861 `100.0001100?.00 <0F> 18,19`. toE 3, total 3, nb 3. Calls: none.

```
02B0 M->tmpb, Q->tmpa; ALU BIT tmpa
02B1 ONES->tmpa; ALU AND tmpa
02B2 SIGMA->NULL  [WE]
```

### `SET1_CL`

Blocks: L866 `100.0001010?.00 <0F> 14,15`. toE 3, total 3, nb 3. Calls: none.

```
02B4 M->tmpb, CX->tmpa; ALU BIT tmpa
02B5 ONES->tmpa; ALU OR tmpa
02B6 SIGMA->M; CTL [-06-]  [E]
```

### `SET1_IMM`

Blocks: L871 `100.0001110?.00 <0F> 1C,1D`. toE 3, total 3, nb 3. Calls: none.

```
02B8 M->tmpb, Q->tmpa; ALU BIT tmpa
02B9 ONES->tmpa; ALU OR tmpa
02BA SIGMA->M; CTL [-06-]  [E]
```

### `CLR1_CL`

Blocks: L876 `100.0001001?.00 <0F> 12,13`. toE 4, total 4, nb 4. Calls: none.

```
02BC M->tmpb, CX->tmpa; ALU BIT tmpa
02BD ONES->tmpa; ALU NOT tmpa
02BE SIGMA->tmpa; ALU AND tmpa
02BF SIGMA->M; CTL [-06-]  [E]
```

### `CLR1_IMM`

Blocks: L881 `100.0001101?.00 <0F> 1A,1B`. toE 4, total 4, nb 4. Calls: none.

```
02C0 M->tmpb, Q->tmpa; ALU BIT tmpa
02C1 ONES->tmpa; ALU NOT tmpa
02C2 SIGMA->tmpa; ALU AND tmpa
02C3 SIGMA->M; CTL [-06-]  [E]
```

### `NOT1_CL`

Blocks: L886 `100.0001011?.00 <0F> 16,17`. toE 3, total 3, nb 3. Calls: none.

```
02C4 M->tmpb, CX->tmpa; ALU BIT tmpa
02C5 ONES->tmpa; ALU XOR tmpa
02C6 SIGMA->M; CTL [-06-]  [E]
```

### `NOT1_IMM`

Blocks: L891 `100.0001111?.00 <0F> 1E,1F`. toE 3, total 3, nb 3. Calls: none.

```
02C8 M->tmpb, Q->tmpa; ALU BIT tmpa
02C9 ONES->tmpa; ALU XOR tmpa
02CA SIGMA->M; CTL [-06-]  [E]
```

### `ADD4S`

Blocks: L896 `100.00100??0.00 <0F> 20,22,24,26`; L901 `100.00100??0.01 <0F> 20,22,24,26`; L906 `100.00100000.10 <0F> 20`; L911 `100.00100??0.11 <0F> 20,22,24,26`; L916 `100.00100??1.00 <0F> 21,23,25,27`; L921 `100.00100??1.01 <0F> 21,23,25,27`. toE 23, total 24, nb 24. Calls: none.

```
02CC CX->tmpaL; ALU INC tmpa
02CD SIGMA->tmpb; ALU SHR tmpb
02CE SIGMA->COUNT; CTL [-04-]
02CF SI->IND, SI->tmpa; CTL MEMR
02D0 ALU INC tmpa
02D1 SIGMA->SI
02D2 OPR->tmpc  [F]
02D3 DI->IND; CTL MEMR ES
02D4 OPR->tmpb; ALU ADC tmpc  [F]
02D5 SIGMA->tmpb; ALU ADJD tmpb  [W]
02D6 ONES->tmpa; ALU ADD tmpa
02D7 DI->IND, SIGMA->[-03-]; CTL MEMW ES  [W]
02D8 CTL [-0D-]
02D9 SIGMA->OPR, DI->tmpa; ALU INC tmpa
02DA SIGMA->DI, [-00-]->tmpb; JMP CNTZ 3 ->02CF
02DB CX->tmpaL; ALU ADD tmpb
02DC JMP [-00-] 3 ->02DF
02DD CONST(1)->tmpb; JMP [-09-] 3 ->02DF
02DE ZEROS->tmpb
02DF SIGMA->NULL; ALU INC tmpa  [W]
02E0 SIGMA->tmpb; ALU SHR tmpb
02E1 DI->tmpb, SIGMA->tmpa; ALU SUB tmpa
02E2 SIGMA->DI, SI->tmpb  [E]
02E3 SIGMA->SI
```

### `SUB4S`

Blocks: L896 `100.00100??0.00 <0F> 20,22,24,26`; L901 `100.00100??0.01 <0F> 20,22,24,26`; L926 `100.00100010.10 <0F> 22`; L911 `100.00100??0.11 <0F> 20,22,24,26`; L916 `100.00100??1.00 <0F> 21,23,25,27`; L921 `100.00100??1.01 <0F> 21,23,25,27`. toE 23, total 24, nb 24. Calls: none.

```
02CC CX->tmpaL; ALU INC tmpa
02CD SIGMA->tmpb; ALU SHR tmpb
02CE SIGMA->COUNT; CTL [-04-]
02CF SI->IND, SI->tmpa; CTL MEMR
02D0 ALU INC tmpa
02D1 SIGMA->SI
02D2 OPR->tmpc  [F]
02D3 DI->IND; CTL MEMR ES
02E4 OPR->tmpb; ALU SBB tmpc  [F]
02E5 SIGMA->tmpb; ALU ADJD tmpb  [W]
02E6 ONES->tmpa; ALU SUB tmpa
02E7 DI->IND, SIGMA->[-03-]; CTL MEMW ES  [W]
02D8 CTL [-0D-]
02D9 SIGMA->OPR, DI->tmpa; ALU INC tmpa
02DA SIGMA->DI, [-00-]->tmpb; JMP CNTZ 3 ->02CF
02DB CX->tmpaL; ALU ADD tmpb
02DC JMP [-00-] 3 ->02DF
02DD CONST(1)->tmpb; JMP [-09-] 3 ->02DF
02DE ZEROS->tmpb
02DF SIGMA->NULL; ALU INC tmpa  [W]
02E0 SIGMA->tmpb; ALU SHR tmpb
02E1 DI->tmpb, SIGMA->tmpa; ALU SUB tmpa
02E2 SIGMA->DI, SI->tmpb  [E]
02E3 SIGMA->SI
```

### `CMP4S`

Blocks: L896 `100.00100??0.00 <0F> 20,22,24,26`; L901 `100.00100??0.01 <0F> 20,22,24,26`; L931 `100.00100110.10 <0F> 26`; L911 `100.00100??0.11 <0F> 20,22,24,26`; L916 `100.00100??1.00 <0F> 21,23,25,27`; L921 `100.00100??1.01 <0F> 21,23,25,27`. toE 23, total 24, nb 24. Calls: none.

```
02CC CX->tmpaL; ALU INC tmpa
02CD SIGMA->tmpb; ALU SHR tmpb
02CE SIGMA->COUNT; CTL [-04-]
02CF SI->IND, SI->tmpa; CTL MEMR
02D0 ALU INC tmpa
02D1 SIGMA->SI
02D2 OPR->tmpc  [F]
02D3 DI->IND; CTL MEMR ES
02E8 OPR->tmpb; ALU SBB tmpc  [F]
02E9 SIGMA->tmpb; ALU ADJD tmpb  [W]
02EA ONES->tmpa; ALU SUB tmpa
02EB DI->IND, SIGMA->[-03-]  [W]
02D8 CTL [-0D-]
02D9 SIGMA->OPR, DI->tmpa; ALU INC tmpa
02DA SIGMA->DI, [-00-]->tmpb; JMP CNTZ 3 ->02CF
02DB CX->tmpaL; ALU ADD tmpb
02DC JMP [-00-] 3 ->02DF
02DD CONST(1)->tmpb; JMP [-09-] 3 ->02DF
02DE ZEROS->tmpb
02DF SIGMA->NULL; ALU INC tmpa  [W]
02E0 SIGMA->tmpb; ALU SHR tmpb
02E1 DI->tmpb, SIGMA->tmpa; ALU SUB tmpa
02E2 SIGMA->DI, SI->tmpb  [E]
02E3 SIGMA->SI
```

### `0F24`

Blocks: L896 `100.00100??0.00 <0F> 20,22,24,26`; L901 `100.00100??0.01 <0F> 20,22,24,26`. toE -, total 8, nb 8. Calls: none.

```
02CC CX->tmpaL; ALU INC tmpa
02CD SIGMA->tmpb; ALU SHR tmpb
02CE SIGMA->COUNT; CTL [-04-]
02CF SI->IND, SI->tmpa; CTL MEMR
02D0 ALU INC tmpa
02D1 SIGMA->SI
02D2 OPR->tmpc  [F]
02D3 DI->IND; CTL MEMR ES
```

### `0F21_TAIL`

Blocks: L916 `100.00100??1.00 <0F> 21,23,25,27`; L921 `100.00100??1.01 <0F> 21,23,25,27`. toE 7, total 8, nb 8. Calls: none.

```
02DC JMP [-00-] 3 ->02DF
02DD CONST(1)->tmpb; JMP [-09-] 3 ->02DF
02DE ZEROS->tmpb
02DF SIGMA->NULL; ALU INC tmpa  [W]
02E0 SIGMA->tmpb; ALU SHR tmpb
02E1 DI->tmpb, SIGMA->tmpa; ALU SUB tmpa
02E2 SIGMA->DI, SI->tmpb  [E]
02E3 SIGMA->SI
```

### `ROL4`

Blocks: L936 `100.00101000.00 <0F> 28`; L941 `100.001010?0.01 <0F> 28,2A`; L946 `100.001010?0.10 <0F> 28,2A`. toE 9, total 10, nb 10. Calls: none.

```
02EC CONST(4)->COUNT
02ED M->tmpbL
02EE AL:AH->tmpbH; ALU PASS tmpb
02EF SIGMA->tmpb; ALU ROL12 tmpb  [R]
02F0 tmpb->M; ALU PASS tmpb
02F1 AX->tmpa; CTL [-06-]
02F2 tmpb->AX
02F3 AL:AH->tmpb
02F4 tmpa->tmpbH  [E]
02F5 tmpb->AX
```

### `ROR4`

Blocks: L951 `100.00101010.00 <0F> 2A`; L941 `100.001010?0.01 <0F> 28,2A`; L946 `100.001010?0.10 <0F> 28,2A`. toE 9, total 10, nb 10. Calls: none.

```
02F8 CONST(8)->COUNT
02F9 M->tmpbL
02FA AL:AH->tmpbH; ALU PASS tmpb
02FB SIGMA->tmpb; ALU ROL12 tmpb  [R]
02F0 tmpb->M; ALU PASS tmpb
02F1 AX->tmpa; CTL [-06-]
02F2 tmpb->AX
02F3 AL:AH->tmpb
02F4 tmpa->tmpbH  [E]
02F5 tmpb->AX
```

### `EXT_REG`

Blocks: L956 `100.00110011.00 <0F> 33`; L961 `100.0011?011.01 <0F> 33,3B`; L966 `100.0011?011.10 <0F> 33,3B`; L971 `100.0011?011.11 <0F> 33,3B`; L976 `100.0011?100.00 <0F> 34,3C`; L981 `100.0011?100.01 <0F> 34,3C`; L641 `100.0011?100.10 <0F> 34,3C`. toE 25, total 25, nb 24. Calls: none.

```
02FC CONST(15)->tmpc; ALU PASS tmpc
02FD R->tmpaL, SIGMA->tmpb; ALU SUB tmpa
02FE SIGMA->AX; ALU PASS tmpa
02FF —
0300 SI->IND, SIGMA->tmpb; CTL MEMR
0301 M->tmpaL; ALU ADD tmpa
0302 tmpc->tmpb, SIGMA->tmpa; ALU AND tmpa
0303 SIGMA->COUNT; ALU SUB tmpa
0304 SI->tmpb, SIGMA->[-03-]; ALU INC2 tmpb  [W]
0305 OPR->tmpc; JMP Z 11 ->0307  [F]
0306 JMP NC 14 ->030A
0307 SIGMA->SI, SIGMA->IND; JMP Z 14 ->030A
0308 tmpc->tmpa; CTL MEMR
0309 OPR->tmpc  [F]
030A COUNT->tmpb; ALU INC tmpb
030B SIGMA->COUNT, SIGMA->tmpb; ALU ADJA tmpb
030C SIGMA->NULL; ALU PASS tmpc
030D tmpb->M, SIGMA->tmpb
030E ZEROS->tmpc; ALU PASS tmpb
030F SIGMA->tmpb; ALU MUL tmpc  [R]
0310 AX->tmpb; ALU PASS tmpb
0311 SIGMA->COUNT
0312 ZEROS->tmpb; JMP Z 8 ->0200
0313 SIGMA->tmpb; ALU MUL tmpc  [R]
0200 tmpa->AX  [E]
```

### `EXT_IMM`

Blocks: L986 `100.00111011.00 <0F> 3B`; L961 `100.0011?011.01 <0F> 33,3B`; L966 `100.0011?011.10 <0F> 33,3B`; L971 `100.0011?011.11 <0F> 33,3B`; L976 `100.0011?100.00 <0F> 34,3C`; L981 `100.0011?100.01 <0F> 34,3C`; L641 `100.0011?100.10 <0F> 34,3C`. toE 25, total 25, nb 25. Calls: none.

```
0314 CONST(15)->tmpc; ALU PASS tmpc
0315 Q->tmpaL, SIGMA->tmpb
0316 ALU SUB tmpa
0317 SIGMA->AX; ALU PASS tmpa
0300 SI->IND, SIGMA->tmpb; CTL MEMR
0301 M->tmpaL; ALU ADD tmpa
0302 tmpc->tmpb, SIGMA->tmpa; ALU AND tmpa
0303 SIGMA->COUNT; ALU SUB tmpa
0304 SI->tmpb, SIGMA->[-03-]; ALU INC2 tmpb  [W]
0305 OPR->tmpc; JMP Z 11 ->0307  [F]
0306 JMP NC 14 ->030A
0307 SIGMA->SI, SIGMA->IND; JMP Z 14 ->030A
0308 tmpc->tmpa; CTL MEMR
0309 OPR->tmpc  [F]
030A COUNT->tmpb; ALU INC tmpb
030B SIGMA->COUNT, SIGMA->tmpb; ALU ADJA tmpb
030C SIGMA->NULL; ALU PASS tmpc
030D tmpb->M, SIGMA->tmpb
030E ZEROS->tmpc; ALU PASS tmpb
030F SIGMA->tmpb; ALU MUL tmpc  [R]
0310 AX->tmpb; ALU PASS tmpb
0311 SIGMA->COUNT
0312 ZEROS->tmpb; JMP Z 8 ->0200
0313 SIGMA->tmpb; ALU MUL tmpc  [R]
0200 tmpa->AX  [E]
```

### `0F34_ENTRY`

Blocks: L976 `100.0011?100.00 <0F> 34,3C`; L981 `100.0011?100.01 <0F> 34,3C`; L641 `100.0011?100.10 <0F> 34,3C`. toE 9, total 9, nb 9. Calls: none.

```
030C SIGMA->NULL; ALU PASS tmpc
030D tmpb->M, SIGMA->tmpb
030E ZEROS->tmpc; ALU PASS tmpb
030F SIGMA->tmpb; ALU MUL tmpc  [R]
0310 AX->tmpb; ALU PASS tmpb
0311 SIGMA->COUNT
0312 ZEROS->tmpb; JMP Z 8 ->0200
0313 SIGMA->tmpb; ALU MUL tmpc  [R]
0200 tmpa->AX  [E]
```

### `INS_REG`

Blocks: L991 `100.0011?001.00 <0F> 31,39`; L996 `100.00110001.01 <0F> 31`; L1001 `100.0011?001.10 <0F> 31,39`; L1006 `100.0011?001.11 <0F> 31,39`. toE -, total 15, nb 15. Calls: INS.

```
0318 M->tmpaL; ALU PASS tmpa
0319 tmpa->COUNT, SIGMA->[-03-]
031A ZEROS->tmpc; JMP Z 6 ->031E
031B DI->IND; CTL MEMR ES
031C OPR->tmpb; ALU PASS tmpb  [F]
031D SIGMA->tmpb; ALU MUL tmpc  [R]
031E tmpa->OPR
031F R->tmpaL; ALU INC tmpa
0320 M->tmpaL, SIGMA->tmpb; ALU ADD tmpa
0321 SIGMA->tmpc
0322 tmpb->COUNT
0323 CONST(15)->tmpb; ALU AND tmpc
0324 M->tmpaL
0325 SIGMA->M; ALU SUB tmpc
0326 AX->tmpb, SIGMA->[-03-]; FARJMP INS  [W]
```

### `INS_IMM`

Blocks: L991 `100.0011?001.00 <0F> 31,39`; L1046 `100.00111001.01 <0F> 39`; L1001 `100.0011?001.10 <0F> 31,39`; L1006 `100.0011?001.11 <0F> 31,39`. toE -, total 15, nb 15. Calls: INS.

```
0318 M->tmpaL; ALU PASS tmpa
0319 tmpa->COUNT, SIGMA->[-03-]
031A ZEROS->tmpc; JMP Z 6 ->0346
031B DI->IND; CTL MEMR ES
0344 OPR->tmpb; ALU PASS tmpb  [F]
0345 SIGMA->tmpb; ALU MUL tmpc  [R]
0346 tmpa->OPR
0347 Q->tmpaL; ALU INC tmpa
0320 M->tmpaL, SIGMA->tmpb; ALU ADD tmpa
0321 SIGMA->tmpc
0322 tmpb->COUNT
0323 CONST(15)->tmpb; ALU AND tmpc
0324 M->tmpaL
0325 SIGMA->M; ALU SUB tmpc
0326 AX->tmpb, SIGMA->[-03-]; FARJMP INS  [W]
```

### `BRKEM`

Blocks: L1051 `100.11111111.00 <0F> FF`. toE -, total 2, nb 2. Calls: INTEM.

```
0348 Q->tmpbL
0349 CONST(1)->COUNT; FARJMP INTEM
```

## Shared FARJMP subroutines and internal (page 111) entries

| Routine | Reached from | V20UC.TXT lines | ROM | toE / total (nb) | F / W / E / R | FARJMP calls |
|---|---|---|---|---|---|---|
| `INT` | CHKIND, F6_DIV, IDIV2, INT3, INTO, INT_N, internal 00 (single-step trap / NMI), internal 02 bank A (INTR acknowledge?), internal 02 bank B (INTR acknowledge?) | L616-620, L621-625, L626-630, L631-635, L636-640 | 01EC-01EF, 01F0-01F3, 01F4-01F7, 01F8-01FB, 01FC-01FF | 17 / 17 (15) | F:01F1,01F3,01F4,01F6,01FA / W:- / E:01FC / R:- | – |
| `INTEM` | BRKEM | L616-620, L621-625, L181-185, L631-635, L636-640 | 01EC-01EF, 01F0-01F3, 0090-0093, 01F8-01FB, 01FC-01FF | 17 / 17 (16) | F:01F1,01F3,0090,0092,01FA / W:- / E:01FC / R:- | – |
| `IRET` | IRET_ | L606-610, L611-615 | 01E4-01E7, 01E8-01EB | 7 / 7 (7) | F:01E6,01E8,01EA / W:- / E:01EA / R:- | – |
| `MULADJ` | IMUL, IMULI | L646-650 | 0204-0207 | - / 3 (3) | F:- / W:0205 / E:- / R:- | MULX |
| `MULX` | F6_MUL, MULADJ | L651-655 | 0208-020B | 4 / 4 (4) | F:- / W:- / E:020B / R:- | – |
| `IMUL` | F6_IMUL | L656-660, L661-665, L666-670, L221-225, L671-675 | 020C-020F, 0210-0213, 0214-0217, 00B0-00B3, 0218-021B | - / 17 (16) | F:- / W:0214 / E:- / R:0211 | MULADJ |
| `IMULI` | IMUL_IMM | L656-660, L661-665, L666-670, L676-680 | 020C-020F, 0210-0213, 0214-0217, 021C-021F | - / 13 (12) | F:- / W:0214 / E:- / R:0211 | MULADJ |
| `REPX` | REP_CMPS, REP_INM, REP_LODS, REP_MOVS, REP_OUTM, REP_SCAS, REP_STOS | L681-685, L686-690 | 0220-0223, 0224-0227 | 5 / 8 (8) | F:- / W:- / E:0224,0227 / R:- | – |
| `SHIFT` | SHIFT_CL, SHIFT_IMM | L691-695 | 0228-022B | 4 / 4 (4) | F:- / W:0229 / E:022B / R:0229 | – |
| `ENTER` | ENTER_ENTRY | L766-770, L771-775, L776-780, L781-785 | 0264-0267, 0268-026B, 026C-026F, 0270-0273 | 15 / 16 (16) | F:0271 / W:- / E:0272 / R:- | – |
| `PUSHA` | PUSHA_ENTRY | L716-720, L721-725, L726-730, L731-735 | 023C-023F, 0240-0243, 0244-0247, 0248-024B | 13 / 13 (13) | F:023D,023F,0241,0243,0245,0247 / W:- / E:0248 / R:- | – |
| `POPA` | POPA_ENTRY | L741-745, L746-750, L751-755, L756-760 | 0250-0253, 0254-0257, 0258-025B, 025C-025F | 13 / 13 (13) | F:0252,0254,0256,0258,025A,025C / W:- / E:025C / R:- | – |
| `CALLF` | CALL_FAR_DIR, FF_CALL_FAR | L696-700, L701-705 | 022C-022F, 0230-0233 | 6 / 7 (7) | F:022D,022F / W:- / E:0231 / R:- | – |
| `INS` | INS_IMM, INS_REG | L1011-1015, L1016-1020, L1021-1025, L1026-1030, L1031-1035, L1036-1040, L1041-1045 | 0328-032B, 032C-032F, 0330-0333, 0334-0337, 0338-033B, 033C-033F, 0340-0343 | 14 / 28 (27) | F:033D / W:- / E:0335,0343 / R:032D,0339,033E,0342 | – |
| `IDIV` | F6_IDIV | L521-525, L526-530 | 01A0-01A3, 01A4-01A7 | - / 8 (8) | F:- / W:01A2,01A7 / E:- / R:- | IDIV2 |
| `IDIV2` | IDIV | L531-535, L536-540, L541-545, L546-550 | 01A8-01AB, 01AC-01AF, 01B0-01B3, 01B4-01B7 | 14 / 16 (15) | F:- / W:01AD / E:01B5,01B7 / R:01AA | INT |
| `RETF` | RETF_, RETF_IMM | L706-710 | 0234-0237 | 4 / 4 (4) | F:0234,0236 / W:- / E:0237 / R:- | – |
| `internal 03 (reset)` | hardware (reset) | L581-585, L586-590 | 01D0-01D3, 01D4-01D7 | 5 / 6 (6) | F:- / W:- / E:01D4 / R:- | – |
| `internal 00 (single-step trap / NMI)` | hardware: slot 01D8 = vector 1 (trap), 01DA = vector 2 (NMI) | L591-595 | 01D8-01DB | - / 4 (4) | F:- / W:- / E:- / R:- | INT |
| `internal 02 bank A (INTR acknowledge?)` | hardware; [-05-] IO ext = INTA-type cycle; two banks share pattern 111.00000010.00 (L596, L601; ambiguous, first match wins in ucsim) | L596-600 | 01DC-01DF | - / 4 (4) | F:01DD / W:- / E:- / R:- | INT |
| `internal 02 bank B (INTR acknowledge?)` | hardware; see bank A | L601-605 | 01E0-01E3 | - / 4 (4) | F:01E1,01E3 / W:- / E:- / R:- | INT |

Notes: `INT` and `INTEM` share sub-rows 0,1,3 (pattern `0001?000`) and differ only in sub-row 2 (INT 01F4-01F7 with CITF/MFS; INTEM 0090-0093 with MFS/MFC and a JMP CNTZ); both fall from sub-row 3 into internal `11/19` (01FC: SIGMA->SP, E, FLUSH). `IMUL` and `IMULI` share sub-rows 0-2 (pattern `0011?000`); IMUL sub-row 3 is 00B0-00B3 (placed between the A6 REP blocks) and falls into internal `31` (0218); IMULI sub-row 3 is 021C. `INS` (70) sub-row 3 falls into internal `71` (0338-0343). Callee chains: F6/F7 /4 -> MULX; /5 -> IMUL -> MULADJ -> MULX; 69/6B -> IMULI -> MULADJ -> MULX; F6/F7 /7 -> IDIV -> IDIV2 (-> INT on overflow); CC/CD/CE/62/divide error -> INT; 0F FF and 8080 ED ED -> INTEM; CF and 8080 ED FD -> IRET; 9A and FF /3 -> CALLF; CA/CB -> RETF; D2/D3/C0/C1 -> SHIFT; REP strings -> REPX; 60 -> PUSHA; 61 -> POPA; C8 -> ENTER; 0F 31/39 -> INS.

### `INT`

Blocks: L616 `111.0001?000.00 <internal> INT    10,18`; L621 `111.0001?000.01 <internal> INT    10,18`; L626 `111.00010000.10 <internal> INT    10`; L631 `111.0001?000.11 <internal> INT    10,18`; L636 `111.0001?001.00 <internal> 11,19`.

```
01EC ZEROS->tmpbH; ALU ADD tmpb
01ED SIGMA->tmpb; CTL SUSP [-03-] IO
01EE SIGMA->IND; CTL MEMR IO
01EF SIGMA->tmpb; ALU INC2 tmpb
01F0 SIGMA->IND; CTL MEMR IO
01F1 OPR->tmpc  [F]
01F2 SP->tmpb; ALU DEC2 tmpb
01F3 OPR->tmpa  [F]
01F4 FLAGS->OPR  [F]
01F5 SIGMA->tmpb, SIGMA->IND; CTL CITF MEMW SS
01F6 CS->OPR, SIGMA->IND; CTL MFS  [F]
01F7 —
01F8 —
01F9 tmpa->CS, SIGMA->tmpb; CTL MEMW SS
01FA PC->OPR, SIGMA->IND  [F]
01FB tmpc->PC; CTL MEMW SS
01FC SIGMA->SP; CTL FLUSH  [E]
```

### `INTEM`

Blocks: L616 `111.0001?000.00 <internal> INT    10,18`; L621 `111.0001?000.01 <internal> INT    10,18`; L181 `111.00011000.10 <internal> INTEM  18`; L631 `111.0001?000.11 <internal> INT    10,18`; L636 `111.0001?001.00 <internal> 11,19`.

```
01EC ZEROS->tmpbH; ALU ADD tmpb
01ED SIGMA->tmpb; CTL SUSP [-03-] IO
01EE SIGMA->IND; CTL MEMR IO
01EF SIGMA->tmpb; ALU INC2 tmpb
01F0 SIGMA->IND; CTL MEMR IO
01F1 OPR->tmpc  [F]
01F2 SP->tmpb; ALU DEC2 tmpb
01F3 OPR->tmpa  [F]
0090 FLAGS->OPR  [F]
0091 SIGMA->tmpb, SIGMA->IND; CTL MFS MEMW SS
0092 CS->OPR, SIGMA->IND; JMP CNTZ 12 ->01F8  [F]
0093 CTL MFC
01F8 —
01F9 tmpa->CS, SIGMA->tmpb; CTL MEMW SS
01FA PC->OPR, SIGMA->IND  [F]
01FB tmpc->PC; CTL MEMW SS
01FC SIGMA->SP; CTL FLUSH  [E]
```

### `IRET`

Blocks: L606 `111.00001000.00 <internal> IRET   08`; L611 `111.00001000.01 <internal> IRET   08`.

```
01E4 ALU INC2 tmpa
01E5 SIGMA->IND, SIGMA->tmpa; CTL SUSP MEMR SS
01E6 OPR->PC  [F]
01E7 SIGMA->IND, SIGMA->tmpa; CTL MEMR SS
01E8 OPR->CS; CTL FLUSH  [F]
01E9 SIGMA->SP
01EA OPR->FLAGS  [FE]
```

### `MULADJ`

Blocks: L646 `111.00100000.00 <internal> MULADJ 20`.

```
0204 tmpa->tmpb; ALU ADD tmpb
0205 SIGMA->NULL, ZEROS->tmpb; ALU ADC tmpc  [W]
0206 SIGMA->NULL; FARJMP MULX
```

### `MULX`

Blocks: L651 `111.00101000.00 <internal> MULX   28`.

```
0208 CTL [-06-]
0209 JMP Z 3 ->020B
020A CTL [-07-]
020B   [E]
```

### `IMUL`

Blocks: L656 `111.0011?000.00 <internal> IMUL   30,38`; L661 `111.0011?000.01 <internal> IMUL   30,38`; L666 `111.0011?000.10 <internal> IMUL   30,38`; L221 `111.00110000.11 <internal> IMUL   30`; L671 `111.00110001.00 <internal> 31`.

```
020C tmpa->tmpb, SIGMA->tmpa; CTL [-0C-]
020D —
020E SIGMA->tmpc, ZEROS->tmpb; ALU PASS tmpc
020F CONST(8)->COUNT; JMP OP8b 5 ->0211
0210 CONST(16)->COUNT
0211 SIGMA->tmpb; ALU MUL tmpc  [R]
0212 tmpb->tmpc; JMP [-09-] 12 ->00B0
0213 ALU NEG tmpa
0214 SIGMA->tmpa; ALU NEG tmpb  [W]
0215 JMP NC 11 ->0217
0216 ALU NOT tmpb
0217 SIGMA->tmpc, SIGMA->tmpb
00B0 tmpb->tmpc; JMP OP8 15 ->00B3
00B1 tmpb->DX
00B2 tmpa->AX; FARJMP MULADJ
00B3 tmpb->AH
0218 tmpa->AL; FARJMP MULADJ
```

### `IMULI`

Blocks: L656 `111.0011?000.00 <internal> IMUL   30,38`; L661 `111.0011?000.01 <internal> IMUL   30,38`; L666 `111.0011?000.10 <internal> IMUL   30,38`; L676 `111.00111000.11 <internal> IMULI  38`.

```
020C tmpa->tmpb, SIGMA->tmpa; CTL [-0C-]
020D —
020E SIGMA->tmpc, ZEROS->tmpb; ALU PASS tmpc
020F CONST(8)->COUNT; JMP OP8b 5 ->0211
0210 CONST(16)->COUNT
0211 SIGMA->tmpb; ALU MUL tmpc  [R]
0212 tmpb->tmpc; JMP [-09-] 12 ->021C
0213 ALU NEG tmpa
0214 SIGMA->tmpa; ALU NEG tmpb  [W]
0215 JMP NC 11 ->0217
0216 ALU NOT tmpb
0217 SIGMA->tmpc, SIGMA->tmpb
021C tmpa->R; FARJMP MULADJ
```

### `REPX`

Blocks: L681 `111.01000000.00 <internal> REPX   40`; L686 `111.01000000.01 <internal> REPX   40`.

```
0220 CX->tmpb; ALU PASS tmpb
0221 PC->tmpb, SIGMA->[-03-]; ALU SUB tmpa
0222 JMP Z 4 ->0224
0223 JMP INTR 5 ->0225
0224   [E]
0225 PFXCNT->tmpa
0226 SIGMA->tmpb; ALU DEC tmpb
0227 SIGMA->PC; CTL FLUSH  [E]
```

### `SHIFT`

Blocks: L691 `111.01001000.00 <internal> SHIFT  48`.

```
0228 JMP Z 3 ->022B
0229 SIGMA->tmpb; ALU OPC tmpb  [WR]
022A SIGMA->M; CTL [-06-]
022B   [E]
```

### `ENTER`

Blocks: L766 `111.01010000.00 <internal> ENTER  50`; L771 `111.01010000.01 <internal> ENTER  50`; L776 `111.01010000.10 <internal> ENTER  50`; L781 `111.01010000.11 <internal> ENTER  50`.

```
0264 SIGMA->SP, Q->tmpb
0265 ZEROS->tmpbH; ALU PASS tmpb
0266 SIGMA->NULL; ALU DEC tmpb
0267 SP->tmpc; JMP Z 14 ->0272
0268 SIGMA->NULL; ALU DEC tmpb
0269 SIGMA->COUNT; JMP Z 11 ->026F
026A BP->tmpb; ALU DEC2 tmpb
026B SIGMA->BP, SIGMA->IND; CTL MEMR SS
026C SP->tmpb
026D SIGMA->SP, SIGMA->IND; CTL MEMW SS
026E JMP CNTZ 6 ->026A
026F SP->tmpb; ALU DEC2 tmpb
0270 SIGMA->SP, SIGMA->IND; CTL MEMW SS
0271 tmpc->OPR  [F]
0272 tmpc->BP, SP->tmpb; ALU SUB tmpa  [E]
0273 SIGMA->SP
```

### `PUSHA`

Blocks: L716 `111.01011000.00 <internal> PUSHA  58`; L721 `111.01011000.01 <internal> PUSHA  58`; L726 `111.01011000.10 <internal> PUSHA  58`; L731 `111.01011000.11 <internal> PUSHA  58`.

```
023C SIGMA->tmpb, SIGMA->IND; CTL MEMW SS
023D DX->OPR  [F]
023E SIGMA->tmpb, SIGMA->IND; CTL MEMW SS
023F BX->OPR  [F]
0240 SIGMA->tmpb, SIGMA->IND; CTL MEMW SS
0241 SP->OPR  [F]
0242 SIGMA->tmpb, SIGMA->IND; CTL MEMW SS
0243 BP->OPR  [F]
0244 SIGMA->tmpb, SIGMA->IND; CTL MEMW SS
0245 SI->OPR  [F]
0246 SIGMA->tmpb, SIGMA->IND; CTL MEMW SS
0247 DI->OPR  [F]
0248 SIGMA->SP, SIGMA->IND; CTL MEMW SS  [E]
```

### `POPA`

Blocks: L741 `111.01100000.00 <internal> POPA   60`; L746 `111.01100000.01 <internal> POPA   60`; L751 `111.01100000.10 <internal> POPA   60`; L756 `111.01100000.11 <internal> POPA   60`.

```
0250 SIGMA->tmpb, SIGMA->IND; CTL MEMR SS
0251 SIGMA->tmpb
0252 OPR->SI  [F]
0253 SIGMA->tmpb, SIGMA->IND; CTL MEMR SS
0254 OPR->BP  [F]
0255 SIGMA->tmpb, SIGMA->IND; CTL MEMR SS
0256 OPR->BX  [F]
0257 SIGMA->tmpb, SIGMA->IND; CTL MEMR SS
0258 OPR->DX  [F]
0259 SIGMA->tmpb, SIGMA->IND; CTL MEMR SS
025A OPR->CX  [F]
025B SIGMA->SP
025C OPR->AX  [FE]
```

### `CALLF`

Blocks: L696 `111.01101000.00 <internal> CALLF  68`; L701 `111.01101000.01 <internal> CALLF  68`.

```
022C tmpb->tmpc, SP->tmpb; CTL SUSP
022D CS->OPR; ALU DEC2 tmpb  [F]
022E SIGMA->IND; CTL MEMW SS
022F PC->OPR, SIGMA->tmpb  [F]
0230 tmpc->CS, SIGMA->IND; CTL MEMW SS
0231 tmpa->PC; CTL FLUSH  [E]
0232 SIGMA->SP
```

### `INS`

Blocks: L1011 `111.01110000.00 <internal> INS    70`; L1016 `111.01110000.01 <internal> INS    70`; L1021 `111.01110000.10 <internal> INS    70`; L1026 `111.01110000.11 <internal> INS    70`; L1031 `111.01110001.00 <internal> 71`; L1036 `111.01110001.01 <internal> 71`; L1041 `111.01110001.10 <internal> 71`.

```
0328 DI->IND; JMP NC 14 ->0336
0329 CONST(16)->tmpb; ALU SUB tmpa
032A SIGMA->COUNT
032B OPR->tmpa
032C ZEROS->tmpc, AX->tmpb; ALU PASS tmpb
032D SIGMA->tmpb; ALU MUL tmpc  [R]
032E DI->tmpc; ALU PASS tmpc
032F DI->IND; CTL MEMW ES
0330 tmpa->OPR
0331 M->tmpaL; ALU INC2 tmpc
0332 SIGMA->DI; ALU PASS tmpa
0333 tmpa->COUNT, SIGMA->[-03-]
0334 ZEROS->tmpc; JMP NZ 14 ->0336
0335 SIGMA->M  [E]
0336 —
0337 DI->IND; CTL MEMR ES
0338 OPR->tmpa; ALU PASS tmpb
0339 SIGMA->tmpb; ALU MUL tmpc  [R]
033A tmpa->tmpc
033B M->tmpaL
033C tmpa->COUNT
033D OPR->tmpb; ALU PASS tmpb  [F]
033E SIGMA->tmpb; ALU SHR tmpb  [R]
033F tmpa->COUNT; ALU PASS tmpc
0340 DI->IND, SIGMA->tmpa
0341 ZEROS->tmpc
0342 SIGMA->tmpb; ALU DIV tmpc  [R]
0343 tmpb->OPR; CTL MEMW ES  [E]
```

### `IDIV`

Blocks: L521 `111.01111000.00 <internal> IDIV   78`; L526 `111.01111000.01 <internal> IDIV   78`.

```
01A0 AX->tmpa; ALU NEG tmpa
01A1 tmpb->OPR; JMP NS 6 ->01A6
01A2 SIGMA->tmpa; ALU NEG tmpb  [W]
01A3 JMP NC 5 ->01A5
01A4 ALU NOT tmpb
01A5 SIGMA->tmpb
01A6 ALU SUB tmpc
01A7 SIGMA->NULL; FARJMP IDIV2  [W]
```

### `IDIV2`

Blocks: L531 `111.10010000.00 <internal> IDIV2  90`; L536 `111.10010000.01 <internal> IDIV2  90`; L541 `111.10010000.10 <internal> IDIV2  90`; L546 `111.10010000.11 <internal> IDIV2  90`.

```
01A8 JMP [-00-] 2 ->01AA
01A9 ZEROS->tmpbL; FARJMP INT
01AA SIGMA->tmpb; ALU DIV tmpc  [R]
01AB SIGMA->NULL, SIGMA->tmpb; ALU DIV tmpc
01AC tmpb->tmpc; ALU PASS tmpa
01AD OPR->tmpb, SIGMA->[-03-]; ALU NEG tmpa  [W]
01AE JMP L 1 ->01A9
01AF JMP [-09-] 9 ->01B1
01B0 SIGMA->tmpa
01B1 ALU NEG tmpc
01B2 JMP NS 12 ->01B4
01B3 SIGMA->tmpc
01B4 tmpa->AX; JMP OP8 15 ->01B7
01B5 tmpc->DX  [E]
01B6 —
01B7 tmpc->AH  [E]
```

### `RETF`

Blocks: L706 `111.10000000.00 <internal> RETF   80`.

```
0234 OPR->tmpc; ALU ADD tmpa  [F]
0235 SIGMA->SP
0236 OPR->CS  [F]
0237 tmpc->PC; CTL FLUSH  [E]
```

### `internal 03 (reset)`

Blocks: L581 `111.00000011.00 <internal> 03`; L586 `111.00000011.01 <internal> 03`.

```
01D0 ZEROS->DS, ZEROS->tmpb; ALU PASS tmpa
01D1 ZEROS->FLAGS; CTL SUSP
01D2 ONES->CS
01D3 ZEROS->PC; CTL FLUSH
01D4 ZEROS->ES; CTL MFS  [E]
01D5 ZEROS->SS
```

### `internal 00 (single-step trap / NMI)`

Blocks: L591 `111.00000000.00 <internal> [-00-] 00`.

```
01D8 CONST(1)->tmpbL; CTL SUSP
01D9 FARJMP INT
01DA CONST(2)->tmpbL; CTL SUSP
01DB FARJMP INT
```

### `internal 02 bank A (INTR acknowledge?)`

Blocks: L596 `111.00000010.00 <internal> 02`.

```
01DC AX->tmpc; CTL SUSP [-05-] IO
01DD OPR->AX  [F]
01DE AL:AH->tmpbL
01DF tmpc->AX; FARJMP INT
```

### `internal 02 bank B (INTR acknowledge?)`

Blocks: L601 `111.00000010.00 <internal> 02`.

```
01E0 ZEROS->IND; CTL SUSP [-05-] IO
01E1 OPR->tmpb  [F]
01E2 ZEROS->IND; CTL [-05-] IO
01E3 OPR->tmpb; FARJMP INT  [F]
```

## Effective-address calculation

There is **no EA routine in the ROM**: no FARJMP target (Str_FAR: IRET INT INTEM MULADJ MULX IMUL IMULI REPX SHIFT ENTER PUSHA POPA CALLF INS IDIV RETF IDIV2) and no internal block computes an EA, and no opcode block references the displacement or the base/index registers for a ModR/M operand. Evidence that the EA and the operand pre-read are hardware ahead of the routine:

- 8D LEA (L106-110, 0054-0057) is `0054 E` then `0055 SIGMA->R`: the EA is already on SIGMA (the address adder) at entry; the measured LEA cost depends on the EA mode (3 for [BW+IX], 5 for direct; J106, J107, M:335).
- Every ModR/M routine reads the r/m operand as `M` with no MEMR (e.g. 0000 `M->tmpb`); ROL4/ROR4 read `M` with no MEMR anywhere (pla_model.md, b6 section), so the read is the decode-time pre-fetch. Memory results leave through the `[-06-]` strobe (0001, 0040, 0049, 004D, 0050, 005B, 0102, 0117, 0171, 0175, 01B9, 022A, 02B6, 02BA, 02BF, 02C3, 02C6, 02CA, 02F1).
- `pla_4` (pla_model.md, "effective-address / ModR/M mem decode", HYPOTHESIS, core exact) decodes `mem[2:0]` into base (BW/BP) and index (IX/IY) selects for an address adder; segment default SS for BP-base forms.
- Stores 88/89/8C/C6/C7/8F: pre-read suppressed by pla_3 b6 MODRM_STORE (native mode only).

## 8080-emulation pages (110 / 101), for completeness

Not V30-native opcodes; one line per block (header line, pattern, opcodes, ROM, E slots).

- L1056 `110.00000000.00` <8080> 00: 034C-034F, E at 034C
- L1061 `110.01??????.00` <8080> 40..7F: 0350-0353, E at 0352
- L1066 `110.00???110.00` <8080> 06,0E,16,1E,26,2E,36,3E: 0354-0357, E at 0356
- L1071 `110.00??0001.00` <8080> 01,11,21,31: 0358-035B, E at 035A
- L1076 `110.00111010.00` <8080> 3A: 035C-035F, E at 035F
- L1081 `110.00110010.00` <8080> 32: 0360-0363, E at 0362
- L1086 `110.00101010.00` <8080> 2A: 0364-0367, E at 0367
- L1091 `110.00100010.00` <8080> 22: 0368-036B, E at 036A
- L1096 `110.000?1010.00` <8080> 0A,1A: 036C-036F, E at 036D
- L1101 `110.000?0010.00` <8080> 02,12: 0370-0373, E at 0371
- L1106 `110.11100011.00` <8080> E3: 0374-0377, E at 0376
- L1111 `110.11101011.00` <8080> EB: 0378-037B, E at 0379
- L1116 `110.11101001.00` <8080> E9: 037C-037F, E at 037C
- L1121 `110.11111001.00` <8080> F9: 0380-0383, E at 0380
- L1126 `110.00???100.00` <8080> 04,0C,14,1C,24,2C,34,3C: 0384-0387, E at 0386
- L1131 `110.00???101.00` <8080> 05,0D,15,1D,25,2D,35,3D: 0388-038B, E at 038A
- L1136 `110.00??0011.00` <8080> 03,13,23,33: 038C-038F, E at 038C
- L1141 `110.00??1011.00` <8080> 0B,1B,2B,3B: 0390-0393, E at 0390
- L1146 `110.10??????.00` <8080> 80..BF: 0394-0397, E at 0395
- L1151 `110.11???110.00` <8080> C6,CE,D6,DE,E6,EE,F6,FE: 0398-039B, E at 0399
- L1156 `110.00??1001.00` <8080> 09,19,29,39: 039C-039F, E at 039D
- L1161 `110.00100111.00` <8080> 27: 03A0-03A3, E at 03A1
- L1166 `110.00101111.00` <8080> 2F: 03A4-03A7, E at 03A4
- L1171 `110.000??111.00` <8080> 07,0F,17,1F: 03A8-03AB, E at 03AB
- L1176 `110.11000011.00` <8080> C3: 03AC-03AF, E at 03AF
- L1181 `110.11???010.00` <8080> C2,CA,D2,DA,E2,EA,F2,FA: 03B0-03B3, E at 03B3
- L1186 `110.11???010.01` <8080> C2,CA,D2,DA,E2,EA,F2,FA: 03B4-03B7, E at 03B5
- L1191 `110.11???111.00` <8080> C7,CF,D7,DF,E7,EF,F7,FF: 03B8-03BB, E at 03BB
- L1196 `110.11001101.00` <8080> CD: 03BC-03BF, E at -
- L1201 `110.11001101.01` <8080> CD: 03C0-03C3, E at 03C0
- L1206 `110.11???100.00` <8080> C4,CC,D4,DC,E4,EC,F4,FC: 03C4-03C7, E at 03C7
- L1211 `110.11???100.01` <8080> C4,CC,D4,DC,E4,EC,F4,FC: 03C8-03CB, E at 03CB
- L1216 `110.11001001.00` <8080> C9: 03CC-03CF, E at 03CF
- L1221 `110.11???000.00` <8080> C0,C8,D0,D8,E0,E8,F0,F8: 03D0-03D3, E at 03D2
- L1226 `110.11???000.01` <8080> C0,C8,D0,D8,E0,E8,F0,F8: 03D4-03D7, E at 03D7
- L1231 `110.110?0101.00` <8080> C5,D5: 03D8-03DB, E at 03DA
- L1236 `110.11100101.00` <8080> E5: 03DC-03DF, E at 03DE
- L1241 `110.11110101.00` <8080> F5: 03E0-03E3, E at 03E2
- L1246 `110.110?0001.00` <8080> C1,D1: 03E4-03E7, E at 03E7
- L1251 `110.11100001.00` <8080> E1: 03E8-03EB, E at 03EB
- L1256 `110.11110001.00` <8080> F1: 03EC-03EF, E at -
- L1261 `110.11110001.01` <8080> F1: 03F0-03F3, E at 03F2
- L1266 `110.11010011.00` <8080> D3: 03F4-03F7, E at 03F5
- L1271 `110.11011011.00` <8080> DB: 03F8-03FB, E at 03FA
- L1276 `101.11111101.00` <8080,ED> FD: 03FC-03FF, E at -, FARJMP IRET
- L1281 `101.11101101.00` <8080,ED> ED: 0400-0403, E at -, FARJMP INTEM

## ROM blocks not attributed to any row above

- none

