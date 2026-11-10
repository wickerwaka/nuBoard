# V35S core v2: the 84 classes, evidence per class

Generated from HEAD aa7c92f, read-only. Class order = `fpga/v35s/core/v35/v35_class_tbl.svh`. Sources per section:
- **Forms**: `ucgen.enumerate_forms(Config.fitted())` (45,819 forms; fit.json md5 de193740..., the class table's), each run through `ucgen.started` (the class the EU runs: CMP r/m,reg as rmw under dest_route=slot, 81 /7 under grp_read, C0/C1 memory as rmw_imm); mnemonics are a local Intel-name helper with the NEC name in brackets; "(reg)" / "(mem)" is the ModR/M mod field.
- **V35 measured**: docs/v35s-eu-timing.md (line), docs/v35s-chains.md F3/F4 (line) where noted, and the a6-timing corpus (build/validation/v35s/corpus/a6-timing.json, the 306 nuV30 forms on the V35 socket: `socket` = V35 clocks, mean of the even/odd placements, retirement to retirement, 0 waits, RAMEN = 1; `v30` = the nuV30 measured cycles the corpus carries from nuV30 docs/facts/timing_measured.json `measured_cycles`, `doc` = the data book value). The a6 forms were assigned to classes by decoding their target bytes with templates.decode + ucgen.started (the flow cases by name).
- **Model step list**: `ucgen.model_steps(op, cfg)` (lead_steps + templates.steps, the tuples as the EU holds them, before `canonical()` drops zero steps), request tuples trimmed of default arguments. `{name}` after a number = the integer it comes from, found by bumping each integer (the class's, shift_imm / load_alu / rmw / bit1_rmw's, the ea table, per_shift_count, read_use_latency) by 1000 and diffing; `(in max/min)` = it enters through a max/min; "step count changes with" = integers that add or remove a step (a zero clocks step present or absent, wbsync). Run values used: shifts count 3 where the form's count is CL or 0, REP strings n = 3 ending on CW, BCD strings n = 2. Addresses: the enumeration's preset registers (BW 0100, IX 0200, IY 0300, SP 0800); None = a register operand.
- **Integers**: the class-table row (non-zero columns) plus the class's other cost integers (folded into the rows), with the meaning from integers.md.
- **V30 counterpart**: a6-timing pairs (above) and the V20UC.TXT routine(s) for the class's opcodes (work/v30-opcodes.md, from the per-opcode ROM survey: work/v30-opcodes.md; V20UC.TXT line ranges, micro-instruction counts to the first E / total, the F/W/E/R slots, FARJMP calls, and the routine's micro-instructions).

## 0. TRAP_NOP (`V35_CLS_TRAP_NOP`)

Class 0: an opcode / form the model has no template for (ucgen.py:1275, TRAP); the decode table points every invalid cell here (build_tables, ucgen.py:1764-1790). No enumerated form starts in it (every enumerated form decodes to a modelled class); all integers 0. a6-timing forms the decoder refuses (ValueError, so they would land here): BRKV [PSW=0000] V35 6.5 / V30 3 (doc [40]); CHKIND DW, [BW] [BW=0800 DW=0005; ram] V35 27 / V30 22 (doc [18]); PREPARE 8, 1 [BP=0F20] V35 40 / V30 22 (doc []); PREPARE 8, 2 [BP=0F20] V35 57 / V30 30 (doc [27]); CHKIND DW,[BW] (trap) V35 85 / V30 63 (doc [55]), and BRKV (V=1, trap) V35 63 / V30 44 (no class: not in the model's decode).

**Open**: not applicable (no template).

## 1. ADJUST (`V35_CLS_ADJUST`)

**Forms**: 2 enumerated, opcodes 27, 2F. Examples: DAA [ADJ4A] x1; DAS [ADJ4S] x1 (2 distinct names).

**V35 measured**:
- ADJ4A 10.5 (docs/v35s-eu-timing.md:225)
- a6: `ADJ4A [AW=0033]` (ADJ4A (no operand)): V35 10.5 (even 10, odd 11); V30 3 (doc [3]); V35 - V30 = 7.5
- a6: `ADJ4A [AW=009A]` (ADJ4A (no operand)): V35 10.5 (even 10, odd 11); V30 3 (doc [3]); V35 - V30 = 7.5
- a6: `ADJ4S [AW=009A]` (ADJ4S (no operand)): V35 9.5 (even 9, odd 10); V30 3 (doc [7]); V35 - V30 = 6.5

**Model steps, register / no-memory form**: `DAA [ADJ4A]` bytes 27

```
('clocks', 10{pre0})
('take', 0)
('clocks', 0{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `nx0` | 8 | table | form without operand bytes: its successor's IR load held nx0 clocks from its start [decoder.py:112-114; E:459-460] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 10 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:43 `27` DAA (ADJ4A): measured 3 (J20,J21; M:205); routine `DAA` V20UC.TXT L21-25 (ROM 0010-0013); toE/total(nb) 2 / 3 (3); flags F:- / W:0012 / E:0011 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:47 `2F` DAS (ADJ4S): measured 3 (J22; M:205); routine `DAS` V20UC.TXT L26-30 (ROM 0014-0017); toE/total(nb) 2 / 3 (3); flags F:- / W:0016 / E:0015 / R:-; FARJMP –; JMP –

  Routine `DAA` (work/v30-opcodes.md:241):
```
0010 AX->tmpbL; ALU ADJD tmpb
0011 ONES->tmpa; ALU ADD tmpa  [E]
0012 SIGMA->AL, SIGMA->[-03-]  [W]
```

  Routine `DAS` (work/v30-opcodes.md:251):
```
0014 AX->tmpbL; ALU ADJD tmpb
0015 ONES->tmpa; ALU SUB tmpa  [E]
0016 SIGMA->AL, SIGMA->[-03-]  [W]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1, `nx0`=8, `wb`=2.

## 2. ADJUST_B (`V35_CLS_ADJUST_B`)

**Forms**: 2 enumerated, opcodes 37, 3F. Examples: AAA [ADJBA] x1; AAS [ADJBS] x1 (2 distinct names).

**V35 measured**:
- ADJBA 17.5 (docs/v35s-eu-timing.md:224)
- a6: `ADJBA [AW=0004]` (ADJBA (no operand)): V35 17.5 (even 17, odd 18); V30 7 (doc [3]); V35 - V30 = 10.5
- a6: `ADJBA [AW=000B]` (ADJBA (no operand)): V35 17.5 (even 17, odd 18); V30 7 (doc [3]); V35 - V30 = 10.5
- a6: `ADJBS [AW=000B]` (ADJBS (no operand)): V35 17.5 (even 17, odd 18); V30 7 (doc [7]); V35 - V30 = 10.5

**Model steps, register / no-memory form**: `AAA [ADJBA]` bytes 37

```
('clocks', 17{pre0})
('take', 0)
('clocks', 0{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `nx0` | 16 | table | form without operand bytes: its successor's IR load held nx0 clocks from its start [decoder.py:112-114; E:459-460] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 17 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |
| `wb` | 3 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:51 `37` AAA (ADJBA): measured 7 (J23,J24; M:206); routine `AAA` V20UC.TXT L31-35, L36-40 (ROM 0018-001B, 001C-001F); toE/total(nb) 6 / 6 (6); flags F:- / W:001A / E:001D / R:-; FARJMP –; JMP 001B JMP NC 5 ->001D
- work/v30-opcodes.md:55 `3F` AAS (ADJBS): measured 7 (J25; M:206); routine `AAS` V20UC.TXT L41-45, L36-40 (ROM 0020-0023, 001C-001F); toE/total(nb) 6 / 6 (6); flags F:- / W:0022 / E:001D / R:-; FARJMP –; JMP 0023 JMP NC 5 ->001D

  Routine `AAA` (work/v30-opcodes.md:261):
```
0018 AX->tmpbL; ALU ADJA tmpb
0019 ONES->tmpa; ALU ADD tmpa
001A SIGMA->AL, SIGMA->[-03-]; ALU INC tmpb  [W]
001B AL:AH->tmpb; JMP NC 5 ->001D
001C SIGMA->AH
001D   [E]
```

  Routine `AAS` (work/v30-opcodes.md:274):
```
0020 AX->tmpbL; ALU ADJA tmpb
0021 ONES->tmpa; ALU SUB tmpa
0022 SIGMA->AL, SIGMA->[-03-]; ALU DEC tmpb  [W]
0023 AL:AH->tmpb; JMP NC 5 ->001D
001C SIGMA->AH
001D   [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1, `nx0`=16, `wb`=3.

## 3. BCD4S (`V35_CLS_BCD4S`)

**Forms**: 2 enumerated, opcodes 0F 20, 0F 22. Examples: ADD4S x1; SUB4S x1 (2 distinct names).

**V35 measured**:
- ADD4S / SUB4S 23 + 30 * ceil(CL/2) (docs/v35s-eu-timing.md:218)
- a6: `ADD4S (CL=2) [CW=0002 IY=0900]` (ADD4S [DS1-spec:]dst-string,[seg-spec:]src-string): V35 53 (even 53, odd 53); V30 35 (doc [26]); V35 - V30 = 18
- a6: `ADD4S (CL=4) [CW=0004 IY=0900]` (ADD4S [DS1-spec:]dst-string,[seg-spec:]src-string): V35 83 (even 83, odd 83); V30 57 (doc [45]); V35 - V30 = 26
- a6: `ADD4S (CL=6) [CW=0006 IY=0900]` (ADD4S [DS1-spec:]dst-string,[seg-spec:]src-string): V35 113 (even 113, odd 113); V30 79 (doc [64]); V35 - V30 = 34
- a6: `SUB4S (CL=4) [CW=0004 IY=0900]` (SUB4S [DS1-spec:]dst-string,[seg-spec:]src-string): V35 83 (even 83, odd 83); V30 56 (doc [45]); V35 - V30 = 27

**Model steps, register / no-memory form**: `ADD4S` bytes 0f20, run {'n': 2}

```
('clocks', 0{pre})
('take', 1)
('data', 'read', 0x200, 1, 16{first})
('fetch_hold', 0x1000)
('data', 'read', 0x300, 1, 7{mid})
('data', 'write', 0x300, 1, 10{wmid})
('data', 'read', 0x201, 1, 7{loop})
('data', 'read', 0x301, 1, 7{mid})
('data', 'write', 0x301, 1, 10{wmid})
('clocks', 10{exec+hrel(in max/min)})
('fetch_hold', 0)
('clocks', 2{hrel(in max/min)})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 12 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `first` | 16 | table | REP string / BCD string: the first element's first cycle setup [C:1490-1494; T:1838, 1699] |
| `hrel` | 2 | rows | fetch hold released hrel clocks before the form's last clock (bf_imm_hold, bcd_fetch, cvt_hold) [C:1343-1344; T:1641, 1707, 1745] |
| `loop` | 7 | table | REP string: each later element's first cycle setup; BCD: each later pair's source read; shift_cl: clocks added to exec for a non-zero count [C:1490-1494; T:1220, 1699, 1820] |
| `mid` | 7 | rows | string / BCD: setup of an element's later cycles (the write after the read; the destination read) [C:1489-1491; T:1810, 1700] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |
| `wmid` | 10 | rows | bcd4s: the write-back's setup [C:1544; T:1702] |

**V30 counterpart**: 
- work/v30-opcodes.md:177 `0F 20` ADD4S: measured 13+22n: 35/57/79 at n=1/2/3 (J15-J17; M:332); routine `ADD4S` V20UC.TXT L896-900, L901-905, L906-910, L911-915, L916-920, L921-925 (ROM 02CC-02CF, 02D0-02D3, 02D4-02D7, 02D8-02DB, 02DC-02DF, 02E0-02E3); toE/total(nb) 23 / 24 (24); flags F:02D2,02D4 / W:02D5,02D7,02DF / E:02E2 / R:-; FARJMP –; JMP 02DA JMP CNTZ 3 ->02CF; 02DC JMP [-00-] 3 ->02DF; 02DD JMP [-09-] 3 ->02DF; note: nibble loop: 02DA JMP CNTZ 3 -> 02CF
- work/v30-opcodes.md:178 `0F 22` SUB4S: measured 56 at n=2 (J275; M:332); routine `SUB4S` V20UC.TXT L896-900, L901-905, L926-930, L911-915, L916-920, L921-925 (ROM 02CC-02CF, 02D0-02D3, 02E4-02E7, 02D8-02DB, 02DC-02DF, 02E0-02E3); toE/total(nb) 23 / 24 (24); flags F:02D2,02E4 / W:02E5,02E7,02DF / E:02E2 / R:-; FARJMP –; JMP 02DA JMP CNTZ 3 ->02CF; 02DC JMP [-00-] 3 ->02DF; 02DD JMP [-09-] 3 ->02DF

  Routine `ADD4S` (work/v30-opcodes.md:1393):
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

  Routine `SUB4S` (work/v30-opcodes.md:1424):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `hrel`=2.

## 4. BCD4S_CMP (`V35_CLS_BCD4S_CMP`)

**Forms**: 1 enumerated, opcodes 0F 26. Examples: CMP4S x1 (1 distinct names).

**V35 measured**:
- CMP4S 24 + 25 * ceil(CL/2) (docs/v35s-eu-timing.md:219)
- a6: `CMP4S (CL=4) [CW=0004 IY=0900]` (CMP4S [DS1-spec:]dst-string,[seg-spec:]src-string): V35 74 (even 74, odd 74); V30 55 (doc [45]); V35 - V30 = 19

**Model steps, register / no-memory form**: `CMP4S` bytes 0f26, run {'n': 2}

```
('clocks', 0{pre})
('take', 1)
('data', 'read', 0x200, 1, 16{first})
('fetch_hold', 0x1000)
('data', 'read', 0x300, 1, 7{mid})
('data', 'read', 0x201, 1, 14{loop})
('data', 'read', 0x301, 1, 7{mid})
('clocks', 18{exec+hrel(in max/min)})
('fetch_hold', 0)
('clocks', 2{hrel(in max/min)})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 20 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `first` | 16 | table | REP string / BCD string: the first element's first cycle setup [C:1490-1494; T:1838, 1699] |
| `hrel` | 2 | rows | fetch hold released hrel clocks before the form's last clock (bf_imm_hold, bcd_fetch, cvt_hold) [C:1343-1344; T:1641, 1707, 1745] |
| `loop` | 14 | table | REP string: each later element's first cycle setup; BCD: each later pair's source read; shift_cl: clocks added to exec for a non-zero count [C:1490-1494; T:1220, 1699, 1820] |
| `mid` | 7 | rows | string / BCD: setup of an element's later cycles (the write after the read; the destination read) [C:1489-1491; T:1810, 1700] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:179 `0F 26` CMP4S: measured 55 at n=2 (J71; M:332); routine `CMP4S` V20UC.TXT L896-900, L901-905, L931-935, L911-915, L916-920, L921-925 (ROM 02CC-02CF, 02D0-02D3, 02E8-02EB, 02D8-02DB, 02DC-02DF, 02E0-02E3); toE/total(nb) 23 / 24 (24); flags F:02D2,02E8 / W:02E9,02EB,02DF / E:02E2 / R:-; FARJMP –; JMP 02DA JMP CNTZ 3 ->02CF; 02DC JMP [-00-] 3 ->02DF; 02DD JMP [-09-] 3 ->02DF; note: sub-row 2 (02E8-02EB) has no MEMW: compare only

  Routine `CMP4S` (work/v30-opcodes.md:1455):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `hrel`=2.

## 5. BCWZ (`V35_CLS_BCWZ`)

**Forms**: 512 enumerated, opcodes E3. Examples: JCXZ [BCWZ] x512 (1 distinct names).

**V35 measured**:
- a6: `BCWZ t (taken)` (BCWZ short-label): V35 23 (even 23, odd -); V30 15 (doc [13]); V35 - V30 = 8
- a6: `BCWZ t (not-taken)` (BCWZ short-label): V35 9 (even 9, odd -); V30 5 (doc [5]); V35 - V30 = 4

**Model steps, taken**: `JCXZ [BCWZ]` bytes e300

```
('clocks', 0{pre})
('take', 1)
('clocks', 11{exec})
('flush', 2)
('clocks', 0{post})
```

**Model steps, not taken**: `JCXZ [BCWZ]` bytes e300

```
('clocks', 0{pre})
('take', 1)
('decide')
('clocks', 4{nexec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 11 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 2 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `nexec` | 4 | rows | transfer not taken: clocks after the decide step [T:1400-1402] |
| `nfgap` | 1 | table | untaken=wait: the same wait for a not-taken transfer (decide step) [C:1410-1411; E:1332] |
| `nhold` | 2 | table | xfer_nt=odd: clocks into the clocks after a not-taken short transfer's operand take at which its odd-address hold ends [C:1330-1331; E:846-853] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:133 `E3` JCXZ (BCWZ): measured not taken 5, taken 15 (J31,J32; M:188); routine `JCXZ` V20UC.TXT L401-405, L391-395 (ROM 0140-0143, 0138-013B); toE/total(nb) 4 / 8 (8); flags F:- / W:- / E:0143,013B / R:-; FARJMP –; JMP 0142 JMP Z 5 ->0139

  Routine `JCXZ` (work/v30-opcodes.md:901):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `hold`=2, `nhold`=2, `fgap`=5, `nfgap`=1.

## 6. BF_EXT (`V35_CLS_BF_EXT`)

**Forms**: 128 enumerated, opcodes 0F 33, 0F 3B. Examples: EXT r8,r8 (reg) x64; EXT r8,imm4 (reg) x64 (2 distinct names).

**V35 measured**:
- EXT: 107 - 2o - 4w within a word; 61 + 2o crossing (-1 at w = 15) (docs/v35s-eu-timing.md:235)
- reg8,reg8 count form 1.5 less than imm4 (docs/v35s-eu-timing.md:239)
- a6: `EXT DL, CL [CW=0007 DW=0000]` (EXT reg1, reg2): V35 77.5 (even 77, odd 78); V30 43 (doc [26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55]); V35 - V30 = 34.5
- a6: `EXT DL, 4 [DW=0000; ram]` (EXT reg8,imm4): V35 91 (even 91, odd 91); V30 43 (doc []); V35 - V30 = 48

**Model steps, register / no-memory form**: `EXT r8,r8 (reg)` bytes 0f33c0

```
('take', 1, 'chain')
('clocks', 1{pre})
('take', 1)
('data', 'read', 0x200, 2, 7{fsetup})
('clocks', 61{span(in max/min)})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `fsetup` | 7 | table | 0F memory forms (page_mem=fixed) / bit fields (bf_read=fixed): the read's fetch-free setup counted back from its post [C:1335-1337; T:1655-1660, 1712-1715] |
| `ftail` | 2 | table | bf_read=fixed: the bit field's read waits ftail fetch-free clocks after the last fetch's end (+1 per imm byte) [E:1801-1804] |
| `hrel` | 2 | rows | fetch hold released hrel clocks before the form's last clock (bf_imm_hold, bcd_fetch, cvt_hold) [C:1343-1344; T:1641, 1707, 1745] |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 1 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 12 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 0 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `span` | 16 | rows | bit fields within one word: the cost formula's clocks less span run as the tail [C:1551-1553; T:1731-1739] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |
| `xsetup` | 27 | rows | bf_ext crossing: the next word's read setup [T:1730] |
| `xspan` | 45 | rows | bit fields crossing a word: the same with xspan [T:1731-1736] |

**V30 counterpart**: 
- work/v30-opcodes.md:187 `0F 33` EXT r8,r8: measured 43 (J92; M:331); routine `EXT_REG` V20UC.TXT L956-960, L961-965, L966-970, L971-975, L976-980, L981-985, L641-645 (ROM 02FC-02FF, 0300-0303, 0304-0307, 0308-030B, 030C-030F, 0310-0313, 0200-0203); toE/total(nb) 25 / 25 (24); flags F:0305,0309 / W:0304 / E:0200 / R:030F,0313; FARJMP –; JMP 0305 JMP Z 11 ->0307; 0306 JMP NC 14 ->030A; 0307 JMP Z 14 ->030A; 0312 JMP Z 8 ->0200
- work/v30-opcodes.md:188 `0F 3B` EXT r8,imm4: measured 43 (J93; M:331); routine `EXT_IMM` V20UC.TXT L986-990, L961-965, L966-970, L971-975, L976-980, L981-985, L641-645 (ROM 0314-0317, 0300-0303, 0304-0307, 0308-030B, 030C-030F, 0310-0313, 0200-0203); toE/total(nb) 25 / 25 (25); flags F:0305,0309 / W:0304 / E:0200 / R:030F,0313; FARJMP –; JMP 0305 JMP Z 11 ->0307; 0306 JMP NC 14 ->030A; 0307 JMP Z 14 ->030A; 0312 JMP Z 8 ->0200

  Routine `EXT_REG` (work/v30-opcodes.md:1550):
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
...
```

  Routine `EXT_IMM` (work/v30-opcodes.md:1582):
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
...
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1, `wb`=2, `hrel`=2, `ftail`=2, `fsetup`=7.

## 7. BF_INS (`V35_CLS_BF_INS`)

**Forms**: 128 enumerated, opcodes 0F 31, 0F 39. Examples: INS r8,r8 (reg) x64; INS r8,imm4 (reg) x64 (2 distinct names).

**V35 measured**:
- INS: 94 (92 at o = 0) within; 86 (84) ending at the boundary; 128 + 4(o + w - 16) crossing (docs/v35s-eu-timing.md:235)
- reg8,reg8 form 1.5 less (docs/v35s-eu-timing.md:239)
- a6: `INS DL, CL [AW=5555 CW=0003 DW=0000 IY=0900]` (INS reg1, reg2): V35 90.5 (even 90, odd 91); V30 51 (doc [31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117]); V35 - V30 = 39.5
- a6: `INS DL, 4 [AW=5555 CW=0003 DW=0000 IY=0900]` (INS reg8,imm4): V35 92 (even 92, odd 91); V30 54 (doc [67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87]); V35 - V30 = 38

**Model steps, register / no-memory form**: `INS r8,r8 (reg)` bytes 0f31c0

```
('take', 1, 'chain')
('clocks', 1{pre})
('take', 1)
('data', 'read', 0x300, 2, 7{fsetup})
('clocks', 74{span(in max/min)})
('data', 'write', 0x300, 2, 2{wsetup})
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `fsetup` | 7 | table | 0F memory forms (page_mem=fixed) / bit fields (bf_read=fixed): the read's fetch-free setup counted back from its post [C:1335-1337; T:1655-1660, 1712-1715] |
| `ftail` | 2 | table | bf_read=fixed: the bit field's read waits ftail fetch-free clocks after the last fetch's end (+1 per imm byte) [E:1801-1804] |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 1 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 12 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 0 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `span` | 20 | rows | bit fields within one word: the cost formula's clocks less span run as the tail [C:1551-1553; T:1731-1739] |
| `wb` | 0 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |
| `wsetup` | 2 | rows | second and later word's setup (push_r/pop_r burst words, call_far return offset, far returns' segment, LES/LDS segment word, RETI PS/PSW, INS write-back) [C:1429-1432; T:1384, 1491, 1518, 1564] |
| `xrsetup` | 12 | rows | bf_ins crossing: the next word's read setup [T:1735] |
| `xspan` | 105 | rows | bit fields crossing a word: the same with xspan [T:1731-1736] |
| `xwsetup` | 69 | rows | bf_ins crossing: the first word's write-back setup [T:1733-1734] |

**V30 counterpart**: 
- work/v30-opcodes.md:185 `0F 31` INS r8,r8: measured 51 (J104); worst case 120 (M:397-399); M:330; routine `INS_REG` V20UC.TXT L991-995, L996-1000, L1001-1005, L1006-1010 (ROM 0318-031B, 031C-031F, 0320-0323, 0324-0327); toE/total(nb) no E (exits via FARJMP) / 15 (15); flags F:031C / W:0326 / E:- / R:031D; FARJMP INS; JMP 031A JMP Z 6 ->031E
- work/v30-opcodes.md:186 `0F 39` INS r8,imm4: measured 54 (J105; M:330); routine `INS_IMM` V20UC.TXT L991-995, L1046-1050, L1001-1005, L1006-1010 (ROM 0318-031B, 0344-0347, 0320-0323, 0324-0327); toE/total(nb) no E (exits via FARJMP) / 15 (15); flags F:0344 / W:0326 / E:- / R:0345; FARJMP INS; JMP 031A JMP Z 6 ->0346

  Routine `INS_REG` (work/v30-opcodes.md:1630):
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

  Routine `INS_IMM` (work/v30-opcodes.md:1652):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1, `ftail`=2, `fsetup`=7.

## 8. BIT1 (`V35_CLS_BIT1`)

**Forms**: 1024 enumerated, opcodes 0F 10, 0F 11, 0F 12, 0F 13, 0F 14, 0F 15, 0F 16, 0F 17, 0F 18, 0F 19, 0F 1A, 0F 1B, 0F 1C, 0F 1D, 0F 1E, 0F 1F. Examples: TEST1 rm8,CL (reg) x64; TEST1 rm16,CL (reg) x64; CLR1 rm8,CL (reg) x64; CLR1 rm16,CL (reg) x64; SET1 rm8,CL (reg) x64; SET1 rm16,CL (reg) x64; ... (16 distinct names).

**V35 measured**:
- a6: `CLR1 AW, CL [CW=0003]` (CLR1 reg16,CL): V35 8.5 (even 8, odd 9); V30 7 (doc [5]); V35 - V30 = 1.5
- a6: `CLR1 AL, CL [CW=0003]` (CLR1 reg8,CL): V35 8.5 (even 8, odd 9); V30 7 (doc [5]); V35 - V30 = 1.5
- a6: `CLR1 AL, 3` (CLR1 reg8,imm3): V35 9 (even 9, odd 8); V30 7 (doc [6]); V35 - V30 = 2
- a6: `NOT1 AW, CL [CW=0003]` (NOT1 reg16,CL): V35 8 (even 7, odd 9); V30 6 (doc [4]); V35 - V30 = 2
- a6: `NOT1 AL, CL [CW=0003]` (NOT1 reg8,CL): V35 8 (even 7, odd 9); V30 6 (doc [4]); V35 - V30 = 2
- a6: `NOT1 AL, 3` (NOT1 reg8,imm3): V35 9 (even 9, odd 8); V30 6 (doc [5]); V35 - V30 = 3
- a6: `SET1 AW, CL [CW=0003]` (SET1 reg16,CL): V35 8 (even 7, odd 9); V30 6 (doc [4]); V35 - V30 = 2
- a6: `SET1 AW, 7` (SET1 reg16,imm4): V35 9 (even 9, odd 8); V30 6 (doc [5]); V35 - V30 = 3
- a6: `SET1 AL, CL [CW=0003]` (SET1 reg8,CL): V35 8 (even 7, odd 9); V30 6 (doc [4]); V35 - V30 = 2
- a6: `SET1 AL, 3` (SET1 reg8,imm3): V35 9 (even 9, odd 8); V30 6 (doc [5]); V35 - V30 = 3
- a6: `TEST1 AW, CL [CW=0003]` (TEST1 reg16,CL): V35 8 (even 7, odd 9); V30 6 (doc [3]); V35 - V30 = 2
- a6: `TEST1 AW, 5` (TEST1 reg16,imm4): V35 9 (even 9, odd 8); V30 6 (doc [4]); V35 - V30 = 3
- a6: `TEST1 AL, CL [CW=0003]` (TEST1 reg8,CL): V35 8 (even 7, odd 9); V30 6 (doc [3]); V35 - V30 = 2
- a6: `TEST1 AL, 3` (TEST1 reg8,imm3): V35 9 (even 9, odd 8); V30 6 (doc [4]); V35 - V30 = 3

**Model steps, register / no-memory form**: `TEST1 rm8,CL (reg)` bytes 0f10c0

```
('take', 1, 'chain')
('clocks', 1{pre})
('take', 1)
('clocks', 2{exec+cl})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `cl` | 0 | table | bit ops with the index in CL: more exec clocks (register) or clocks before the read (memory) [C:1536-1541; T:1653-1659] |
| `exec` | 2 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `flwb` | 2 | table | bit1: write-back flwb clocks longer when the register bit op's step end raises a fetch in page_ir_room=end's state (page_fl_end=wb) [E:760-763; C:1259-1263] |
| `mtx` | 1 | table | page_mt_end=exec: the ModR/M byte taken after a wait reaches the EU mtx clocks late; ALU clocks start no earlier than take+1+mtx [E:1039-1044] |
| `nx` | 4 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 1 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:169 `0F 10/11` TEST1 r/m,CL: measured reg 6 (J286,J288); mem 14 (J282,J284); M:323-324; routine `TEST1_CL` V20UC.TXT L856-860 (ROM 02AC-02AF); toE/total(nb) 3 / 3 (3); flags F:- / W:02AE / E:02AE / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:170 `0F 12/13` CLR1 r/m,CL: measured reg 7 (J62,J63); mem 21 (J58,J60); M:327; routine `CLR1_CL` V20UC.TXT L876-880 (ROM 02BC-02BF); toE/total(nb) 4 / 4 (4); flags F:- / W:- / E:02BF / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:171 `0F 14/15` SET1 r/m,CL: measured reg 6 (J247,J249); mem 21 (J243,J245); M:326; routine `SET1_CL` V20UC.TXT L866-870 (ROM 02B4-02B7); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:02B6 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:172 `0F 16/17` NOT1 r/m,CL: measured reg 6 (J194,J195); mem 21 (J190,J192); M:325; routine `NOT1_CL` V20UC.TXT L886-890 (ROM 02C4-02C7); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:02C6 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:173 `0F 18/19` TEST1 r/m,imm3/4: measured reg 6 (J287,J289); mem 14 (J283,J285); routine `TEST1_IMM` V20UC.TXT L861-865 (ROM 02B0-02B3); toE/total(nb) 3 / 3 (3); flags F:- / W:02B2 / E:02B2 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:174 `0F 1A/1B` CLR1 r/m,imm3/4: measured reg 7 (J64); mem 23 (J59,J61); routine `CLR1_IMM` V20UC.TXT L881-885 (ROM 02C0-02C3); toE/total(nb) 4 / 4 (4); flags F:- / W:- / E:02C3 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:175 `0F 1C/1D` SET1 r/m,imm3/4: measured reg 6 (J248,J250); mem 21 (J244,J246); routine `SET1_IMM` V20UC.TXT L871-875 (ROM 02B8-02BB); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:02BA / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:176 `0F 1E/1F` NOT1 r/m,imm3/4: measured reg 6 (J196); mem 21 (J191,J193); routine `NOT1_IMM` V20UC.TXT L891-895 (ROM 02C8-02CB); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:02CA / R:-; FARJMP –; JMP –

  Routine `TEST1_CL` (work/v30-opcodes.md:1311):
```
02AC M->tmpb, CX->tmpa; ALU BIT tmpa
02AD ONES->tmpa; ALU AND tmpa
02AE SIGMA->NULL  [WE]
```

  Routine `CLR1_CL` (work/v30-opcodes.md:1351):
```
02BC M->tmpb, CX->tmpa; ALU BIT tmpa
02BD ONES->tmpa; ALU NOT tmpa
02BE SIGMA->tmpa; ALU AND tmpa
02BF SIGMA->M; CTL [-06-]  [E]
```

  Routine `SET1_CL` (work/v30-opcodes.md:1331):
```
02B4 M->tmpb, CX->tmpa; ALU BIT tmpa
02B5 ONES->tmpa; ALU OR tmpa
02B6 SIGMA->M; CTL [-06-]  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=4, `wb`=2, `flwb`=2, `mtx`=1.

## 9. BIT1_CLR (`V35_CLS_BIT1_CLR`)

**Forms**: 768 enumerated, opcodes 0F 12, 0F 13, 0F 1A, 0F 1B. Examples: CLR1 rm8,CL (mem) x192; CLR1 rm16,CL (mem) x192; CLR1 rm8,imm3 (mem) x192; CLR1 rm16,imm4 (mem) x192 (4 distinct names).

**V35 measured**:
- a6: `CLR1 word [BW], CL [BW=0800 CW=0003]` (CLR1 mem16,CL): V35 19.5 (even 19, odd 20); V30 21 (doc [14]); V35 - V30 = -1.5
- a6: `CLR1 word [BW], 5 [BW=0800]` (CLR1 mem16,imm4): V35 17 (even 17, odd 16); V30 23 (doc [15]); V35 - V30 = -6
- a6: `CLR1 byte [BW], CL [BW=0800 CW=0003]` (CLR1 mem8,CL): V35 19.5 (even 19, odd 20); V30 21 (doc [14]); V35 - V30 = -1.5
- a6: `CLR1 byte [BW], 3 [BW=0800]` (CLR1 mem8,imm3): V35 17 (even 17, odd 16); V30 23 (doc [15]); V35 - V30 = -6

**Model steps, memory form**: `CLR1 rm8,CL (mem)` bytes 0f1200, EA mode base_index (ea table `base_index`)

```
('take', 1, 'chain')
('clocks', 1{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 1, 6{fsetup+cl}, 6{fsetup+cl})
('clocks', 0)
('data', 'write', 0x300, 1, 4{alu+setup(in max/min)})
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `alu` | 4 | rows | rmw / rmw_imm / 0F rmw forms: clocks between the read data and the write's post (ALU step); with rmw_write_issue=immediate the write is posted at the ALU step's start with max(alu, setup) setup [T:1253-1305, 1773] |
| `cl` | 3 | table | bit ops with the index in CL: more exec clocks (register) or clocks before the read (memory) [C:1536-1541; T:1653-1659] |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `fsetup` | 3 | table | 0F memory forms (page_mem=fixed) / bit fields (bf_read=fixed): the read's fetch-free setup counted back from its post [C:1335-1337; T:1655-1660, 1712-1715] |
| `grp` | 1 | rows | group memory form: the group setup clocks before the first data request (as EU clocks or extra setup per grp_mode) [T:1032-1041] |
| `grp_free` | 0 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `mtx` | 0 | table | page_mt_end=exec: the ModR/M byte taken after a wait reaches the EU mtx clocks late; ALU clocks start no earlier than take+1+mtx [E:1039-1044] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pdhold` | 3 | table | page_disp=hold: a 0F memory form's displacement taken inside a fetch's flight: no fetch before pdhold clocks after that fetch's delivery [E:1081-1084] |
| `pre` | 1 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 0 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `sidle` | 2 | table | slot_idle=eu: clocks from a left-out write's slot that runs no fetch to the clock the EU goes on [C:1381-1384; E:1984-1987] |
| `wb` | 0 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:170 `0F 12/13` CLR1 r/m,CL: measured reg 7 (J62,J63); mem 21 (J58,J60); M:327; routine `CLR1_CL` V20UC.TXT L876-880 (ROM 02BC-02BF); toE/total(nb) 4 / 4 (4); flags F:- / W:- / E:02BF / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:174 `0F 1A/1B` CLR1 r/m,imm3/4: measured reg 7 (J64); mem 23 (J59,J61); routine `CLR1_IMM` V20UC.TXT L881-885 (ROM 02C0-02C3); toE/total(nb) 4 / 4 (4); flags F:- / W:- / E:02C3 / R:-; FARJMP –; JMP –

  Routine `CLR1_CL` (work/v30-opcodes.md:1351):
```
02BC M->tmpb, CX->tmpa; ALU BIT tmpa
02BD ONES->tmpa; ALU NOT tmpa
02BE SIGMA->tmpa; ALU AND tmpa
02BF SIGMA->M; CTL [-06-]  [E]
```

  Routine `CLR1_IMM` (work/v30-opcodes.md:1362):
```
02C0 M->tmpb, Q->tmpa; ALU BIT tmpa
02C1 ONES->tmpa; ALU NOT tmpa
02C2 SIGMA->tmpa; ALU AND tmpa
02C3 SIGMA->M; CTL [-06-]  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `dfloor`=2, `sidle`=2, `pdhold`=3, `setup_free`=3, `fsetup`=3.

## 10. BIT1_RMW (`V35_CLS_BIT1_RMW`)

**Forms**: 1536 enumerated, opcodes 0F 14, 0F 15, 0F 16, 0F 17, 0F 1C, 0F 1D, 0F 1E, 0F 1F. Examples: SET1 rm8,CL (mem) x192; SET1 rm16,CL (mem) x192; NOT1 rm8,CL (mem) x192; NOT1 rm16,CL (mem) x192; SET1 rm8,imm3 (mem) x192; SET1 rm16,imm4 (mem) x192; ... (8 distinct names).

**V35 measured**:
- a6: `NOT1 word [BW], CL [BW=0800 CW=0003]` (NOT1 mem16,CL): V35 18.5 (even 18, odd 19); V30 21 (doc [18]); V35 - V30 = -2.5
- a6: `NOT1 word [BW], 5 [BW=0800]` (NOT1 mem16,imm4): V35 16 (even 16, odd 15); V30 21 (doc [19]); V35 - V30 = -5
- a6: `NOT1 byte [BW], CL [BW=0800 CW=0003]` (NOT1 mem8,CL): V35 18.5 (even 18, odd 19); V30 21 (doc [18]); V35 - V30 = -2.5
- a6: `NOT1 byte [BW], 3 [BW=0800]` (NOT1 mem8,imm3): V35 16 (even 16, odd 15); V30 21 (doc [19]); V35 - V30 = -5
- a6: `SET1 word [BW], CL [BW=0800 CW=0003]` (SET1 mem16,CL): V35 18.5 (even 18, odd 19); V30 21 (doc [13]); V35 - V30 = -2.5
- a6: `SET1 word [BW], 5 [BW=0800]` (SET1 mem16,imm4): V35 16 (even 16, odd 15); V30 21 (doc [14]); V35 - V30 = -5
- a6: `SET1 byte [BW], CL [BW=0800 CW=0003]` (SET1 mem8,CL): V35 18.5 (even 18, odd 19); V30 21 (doc [13]); V35 - V30 = -2.5
- a6: `SET1 byte [BW], 3 [BW=0800]` (SET1 mem8,imm3): V35 16 (even 16, odd 15); V30 21 (doc [14]); V35 - V30 = -5

**Model steps, memory form**: `SET1 rm8,CL (mem)` bytes 0f1400, EA mode base_index (ea table `base_index`)

```
('take', 1, 'chain')
('clocks', 1{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 1, 6{fsetup+cl}, 6{fsetup+cl})
('clocks', 0)
('data', 'write', 0x300, 1, 3{alu+setup(in max/min)})
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `alu` | 3 | rows | rmw / rmw_imm / 0F rmw forms: clocks between the read data and the write's post (ALU step); with rmw_write_issue=immediate the write is posted at the ALU step's start with max(alu, setup) setup [T:1253-1305, 1773] |
| `cl` | 3 | table | bit ops with the index in CL: more exec clocks (register) or clocks before the read (memory) [C:1536-1541; T:1653-1659] |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `fsetup` | 3 | table | 0F memory forms (page_mem=fixed) / bit fields (bf_read=fixed): the read's fetch-free setup counted back from its post [C:1335-1337; T:1655-1660, 1712-1715] |
| `grp_free` | 0 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `mtx` | 0 | table | page_mt_end=exec: the ModR/M byte taken after a wait reaches the EU mtx clocks late; ALU clocks start no earlier than take+1+mtx [E:1039-1044] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pdhold` | 3 | table | page_disp=hold: a 0F memory form's displacement taken inside a fetch's flight: no fetch before pdhold clocks after that fetch's delivery [E:1081-1084] |
| `pre` | 1 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 0 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `sidle` | 2 | table | slot_idle=eu: clocks from a left-out write's slot that runs no fetch to the clock the EU goes on [C:1381-1384; E:1984-1987] |
| `wb` | 0 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:171 `0F 14/15` SET1 r/m,CL: measured reg 6 (J247,J249); mem 21 (J243,J245); M:326; routine `SET1_CL` V20UC.TXT L866-870 (ROM 02B4-02B7); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:02B6 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:172 `0F 16/17` NOT1 r/m,CL: measured reg 6 (J194,J195); mem 21 (J190,J192); M:325; routine `NOT1_CL` V20UC.TXT L886-890 (ROM 02C4-02C7); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:02C6 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:175 `0F 1C/1D` SET1 r/m,imm3/4: measured reg 6 (J248,J250); mem 21 (J244,J246); routine `SET1_IMM` V20UC.TXT L871-875 (ROM 02B8-02BB); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:02BA / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:176 `0F 1E/1F` NOT1 r/m,imm3/4: measured reg 6 (J196); mem 21 (J191,J193); routine `NOT1_IMM` V20UC.TXT L891-895 (ROM 02C8-02CB); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:02CA / R:-; FARJMP –; JMP –

  Routine `SET1_CL` (work/v30-opcodes.md:1331):
```
02B4 M->tmpb, CX->tmpa; ALU BIT tmpa
02B5 ONES->tmpa; ALU OR tmpa
02B6 SIGMA->M; CTL [-06-]  [E]
```

  Routine `NOT1_CL` (work/v30-opcodes.md:1373):
```
02C4 M->tmpb, CX->tmpa; ALU BIT tmpa
02C5 ONES->tmpa; ALU XOR tmpa
02C6 SIGMA->M; CTL [-06-]  [E]
```

  Routine `SET1_IMM` (work/v30-opcodes.md:1341):
```
02B8 M->tmpb, Q->tmpa; ALU BIT tmpa
02B9 ONES->tmpa; ALU OR tmpa
02BA SIGMA->M; CTL [-06-]  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `dfloor`=2, `sidle`=2, `pdhold`=3, `setup_free`=3, `fsetup`=3.

## 11. BIT1_TEST (`V35_CLS_BIT1_TEST`)

**Forms**: 768 enumerated, opcodes 0F 10, 0F 11, 0F 18, 0F 19. Examples: TEST1 rm8,CL (mem) x192; TEST1 rm16,CL (mem) x192; TEST1 rm8,imm3 (mem) x192; TEST1 rm16,imm4 (mem) x192 (4 distinct names).

**V35 measured**:
- a6: `TEST1 word [BW], CL [BW=0800 CW=0003]` (TEST1 mem16,CL): V35 15.5 (even 15, odd 16); V30 14 (doc [12]); V35 - V30 = 1.5
- a6: `TEST1 word [BW], 5 [BW=0800]` (TEST1 mem16,imm4): V35 13 (even 13, odd 13); V30 14 (doc [13]); V35 - V30 = -1
- a6: `TEST1 byte [BW], CL [BW=0800 CW=0003]` (TEST1 mem8,CL): V35 15.5 (even 15, odd 16); V30 14 (doc [12]); V35 - V30 = 1.5
- a6: `TEST1 byte [BW], 3 [BW=0800]` (TEST1 mem8,imm3): V35 13 (even 13, odd 13); V30 14 (doc [13]); V35 - V30 = -1

**Model steps, memory form**: `TEST1 rm8,CL (mem)` bytes 0f1000, EA mode base_index (ea table `base_index`)

```
('take', 1, 'chain')
('clocks', 1{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 1, 6{fsetup+cl}, 6{fsetup+cl})
('clocks', 0)
('clocks', 2{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `cl` | 3 | table | bit ops with the index in CL: more exec clocks (register) or clocks before the read (memory) [C:1536-1541; T:1653-1659] |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `exec` | 2 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fsetup` | 3 | table | 0F memory forms (page_mem=fixed) / bit fields (bf_read=fixed): the read's fetch-free setup counted back from its post [C:1335-1337; T:1655-1660, 1712-1715] |
| `grp` | 1 | rows | group memory form: the group setup clocks before the first data request (as EU clocks or extra setup per grp_mode) [T:1032-1041] |
| `grp_free` | 0 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `mtx` | 1 | table | page_mt_end=exec: the ModR/M byte taken after a wait reaches the EU mtx clocks late; ALU clocks start no earlier than take+1+mtx [E:1039-1044] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pdhold` | 3 | table | page_disp=hold: a 0F memory form's displacement taken inside a fetch's flight: no fetch before pdhold clocks after that fetch's delivery [E:1081-1084] |
| `pre` | 1 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 0 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:169 `0F 10/11` TEST1 r/m,CL: measured reg 6 (J286,J288); mem 14 (J282,J284); M:323-324; routine `TEST1_CL` V20UC.TXT L856-860 (ROM 02AC-02AF); toE/total(nb) 3 / 3 (3); flags F:- / W:02AE / E:02AE / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:173 `0F 18/19` TEST1 r/m,imm3/4: measured reg 6 (J287,J289); mem 14 (J283,J285); routine `TEST1_IMM` V20UC.TXT L861-865 (ROM 02B0-02B3); toE/total(nb) 3 / 3 (3); flags F:- / W:02B2 / E:02B2 / R:-; FARJMP –; JMP –

  Routine `TEST1_CL` (work/v30-opcodes.md:1311):
```
02AC M->tmpb, CX->tmpa; ALU BIT tmpa
02AD ONES->tmpa; ALU AND tmpa
02AE SIGMA->NULL  [WE]
```

  Routine `TEST1_IMM` (work/v30-opcodes.md:1321):
```
02B0 M->tmpb, Q->tmpa; ALU BIT tmpa
02B1 ONES->tmpa; ALU AND tmpa
02B2 SIGMA->NULL  [WE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `dfloor`=2, `mtx`=1, `pdhold`=3, `fsetup`=3.

## 12. BR_MEM (`V35_CLS_BR_MEM`)

**Forms**: 24 enumerated, opcodes FF. Examples: JMP near rm16 (mem) x24 (1 distinct names).

**V35 measured**:
- a6: `BR [BW]` (BR memptr16): V35 28 (even 28, odd -); V30 20 (doc [20]); V35 - V30 = 8

**Model steps, memory form**: `JMP near rm16 (mem)` bytes ff20, EA mode base_index (ea table `base_index`)

```
('take', 1, 'lead')
('clocks', 0{pre})
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 2, 6{grp}, 6, True)
('clocks', 8{exec})
('flush', 0x1000)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `dhold` | 3 | table | xfer_mem_disp=grp / grp_disp=hold: clocks after a d16's take a fetch is held (falls back to grp_free) [E:1154-1164; C:1468-1470] |
| `exec` | 8 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `grp` | 6 | rows | group memory form: the group setup clocks before the first data request (as EU clocks or extra setup per grp_mode) [T:1032-1041] |
| `grp_free` | 6 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `hold` | 10 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |

**V30 counterpart**: 
- work/v30-opcodes.md:165 `FE/FF /4` JMP r/m16 (near indirect): measured reg 12 (J41); mem 20 (J38); M:191-192; routine `FF_JMP_NEAR` V20UC.TXT L566-570 (ROM 01C4-01C7); toE/total(nb) 1 / 1 (1); flags F:- / W:- / E:01C4 / R:-; FARJMP –; JMP –

  Routine `FF_JMP_NEAR` (work/v30-opcodes.md:1123):
```
01C4 M->PC; CTL FLUSH  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=10, `fgap`=5, `dhold`=3, `grp_free`=6.

## 13. BR_REG (`V35_CLS_BR_REG`)

**Forms**: 8 enumerated, opcodes FF. Examples: JMP near rm16 (reg) x8 (1 distinct names).

**V35 measured**:
- a6: `BR DW` (BR regptr16): V35 22 (even 22, odd -); V30 12 (doc [11]); V35 - V30 = 10

**Model steps, register / no-memory form**: `JMP near rm16 (reg)` bytes ffe0

```
('take', 1)
('clocks', 5{pre})
('clocks', 5{exec})
('flush', 5)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 5 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 8 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 10 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 5 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |

**V30 counterpart**: 
- work/v30-opcodes.md:165 `FE/FF /4` JMP r/m16 (near indirect): measured reg 12 (J41); mem 20 (J38); M:191-192; routine `FF_JMP_NEAR` V20UC.TXT L566-570 (ROM 01C4-01C7); toE/total(nb) 1 / 1 (1); flags F:- / W:- / E:01C4 / R:-; FARJMP –; JMP –

  Routine `FF_JMP_NEAR` (work/v30-opcodes.md:1123):
```
01C4 M->PC; CTL FLUSH  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1, `hold`=10, `fgap`=8.

## 14. BRANCH_FAR (`V35_CLS_BRANCH_FAR`)

**Forms**: 256 enumerated, opcodes EA. Examples: JMP far [BR] x256 (1 distinct names).

**V35 measured**:
- a6: `BR far 0:0x0514` (BR far-label): V35 28 (even 28, odd -); V30 15 (doc [15]); V35 - V30 = 13

**Model steps, register / no-memory form**: `JMP far [BR]` bytes ea00020000

```
('clocks', 3{pre})
('take', 2, 'chain')
('clocks', 2{spre})
('take', 2)
('clocks', 5{exec})
('flush', 0x200)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 5 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 16 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `pre` | 3 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `spre` | 2 | rows | far forms: clocks between the offset word's take and the segment word's [C:1434-1435; T:1474-1476] |

**V30 counterpart**: 
- work/v30-opcodes.md:138 `EA` JMP ptr16:16 (BR far): measured 15 (J37; M:191); routine `JMP_FAR_DIR` V20UC.TXT L436-440, L441-445 (ROM 015C-015F, 0160-0163); toE/total(nb) 6 / 6 (6); flags F:- / W:- / E:0161 / R:-; FARJMP –; JMP –

  Routine `JMP_FAR_DIR` (work/v30-opcodes.md:970):
```
015C Q->tmpbL
015D Q->tmpbH
015E Q->tmpaL
015F Q->tmpaH
0160 tmpa->CS; CTL SUSP
0161 tmpb->PC; CTL FLUSH  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=16, `fgap`=5.

## 15. BRANCH_FAR_MEM (`V35_CLS_BRANCH_FAR_MEM`)

**Forms**: 24 enumerated, opcodes FF. Examples: JMP far rm16 (mem) x24 (1 distinct names).

**V35 measured**: not in the sources (no eu-timing row, no a6 form).

**Model steps, memory form**: `JMP far rm16 (mem)` bytes ff28, EA mode base_index (ea table `base_index`)

```
('take', 1, 'lead')
('clocks', 0{pre})
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 2, 6{grp}, 6, True)
('data', 'read', 0x302, 2, 5{rwsetup}, 5{rwsetup})
('clocks', 8{exec})
('flush', 0x1000)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `dhold` | 3 | table | xfer_mem_disp=grp / grp_disp=hold: clocks after a d16's take a fetch is held (falls back to grp_free) [E:1154-1164; C:1468-1470] |
| `exec` | 8 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `grp` | 6 | rows | group memory form: the group setup clocks before the first data request (as EU clocks or extra setup per grp_mode) [T:1032-1041] |
| `grp_free` | 6 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `hold` | 16 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rwsetup` | 5 | rows | far memory-indirect transfers: the segment word's read setup, every clock fetch-free [C:1470-1471; T:1588] |

**V30 counterpart**: 
- work/v30-opcodes.md:166 `FE/FF /5` JMP m16:16 (far indirect): measured not measured; routine `FF_JMP_FAR` V20UC.TXT L571-575 (ROM 01C8-01CB); toE/total(nb) 4 / 4 (4); flags F:01C8,01CA / W:- / E:01CB / R:-; FARJMP –; JMP –

  Routine `FF_JMP_FAR` (work/v30-opcodes.md:1131):
```
01C8 OPR->tmpb, SIGMA->tmpa; ALU INC2 tmpa  [F]
01C9 SIGMA->IND; CTL SUSP MEMR
01CA OPR->CS  [F]
01CB tmpb->PC; CTL FLUSH  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=16, `fgap`=5, `dhold`=3, `grp_free`=6.

## 16. BRANCH_NEAR (`V35_CLS_BRANCH_NEAR`)

**Forms**: 256 enumerated, opcodes E9. Examples: JMP near [BR] x256 (1 distinct names).

**V35 measured**:
- a6: `BR t (near, disp16)` (BR near-label): V35 24 (even 24, odd -); V30 13 (doc [12]); V35 - V30 = 11
- a6: `BR t (near, even target)` (BR near-label): V35 22 (even 22, odd -); V30 13 (doc [12]); V35 - V30 = 9

**Model steps, register / no-memory form**: `JMP near [BR]` bytes e90002

```
('clocks', 3{pre})
('take', 2)
('clocks', 5{exec})
('flush', 0x203)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 5 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 3 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 10 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `nexec` | 4 | rows | transfer not taken: clocks after the decide step [T:1400-1402] |
| `pre` | 3 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |

**V30 counterpart**: 
- work/v30-opcodes.md:137 `E9` JMP rel16 (BR near): measured 13 (J39,J40; M:192); routine `JMP_NEAR` V20UC.TXT L426-430 (ROM 0154-0157); toE/total(nb) 4 / 4 (4); flags F:- / W:- / E:0157 / R:-; FARJMP –; JMP 0155 JMP always 2 ->0156

  Routine `JMP_NEAR` (work/v30-opcodes.md:948):
```
0154 Q->tmpbL; ALU ADD tmpa
0155 Q->tmpbH; JMP always 2 ->0156
0156 PC->tmpa; CTL SUSP
0157 SIGMA->PC; CTL FLUSH  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=10, `fgap`=3.

## 17. BRANCH_SHORT (`V35_CLS_BRANCH_SHORT`)

**Forms**: 8448 enumerated, opcodes 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 7A, 7B, 7C, 7D, 7E, 7F, EB. Examples: JO x512; JNO x512; JB x512; JNB x512; JZ x512; JNZ x512; ... (17 distinct names).

**V35 measured**:
- a6: `BZ t (taken)` (BZ short-label): V35 24 (even 24, odd -); V30 13 (doc [14]); V35 - V30 = 11
- a6: `BZ t (not-taken)` (BZ short-label): V35 9 (even 9, odd -); V30 4 (doc [4]); V35 - V30 = 5
- a6: `BNZ t (taken)` (BNZ short-label): V35 24 (even 24, odd -); V30 13 (doc [14]); V35 - V30 = 11
- a6: `BNZ t (not-taken)` (BNZ short-label): V35 9 (even 9, odd -); V30 4 (doc [4]); V35 - V30 = 5
- a6: `BC t (taken)` (BC short-label): V35 24 (even 24, odd -); V30 13 (doc [14]); V35 - V30 = 11
- a6: `BC t (not-taken)` (BC short-label): V35 9 (even 9, odd -); V30 4 (doc [4]); V35 - V30 = 5
- a6: `BNC t (taken)` (BNC short-label): V35 24 (even 24, odd -); V30 13 (doc [14]); V35 - V30 = 11
- a6: `BNC t (not-taken)` (BNC short-label): V35 9 (even 9, odd -); V30 4 (doc [4]); V35 - V30 = 5
- a6: `BZ t (taken, odd target)` (BZ short-label): V35 27 (even 27, odd -); V30 13 (doc [14]); V35 - V30 = 14
- a6: `BR t (short)` (BR short-label): V35 20 (even 20, odd -); V30 12 (doc [12]); V35 - V30 = 8
- a6: `BR t (short, odd target)` (BR short-label): V35 23 (even 23, odd -); V30 12 (doc [12]); V35 - V30 = 11

**Model steps, taken**: `JO` bytes 7000

```
('clocks', 0{pre})
('take', 1)
('clocks', 4{cond})
('clocks', 8{exec})
('flush', 2, 'cfgap')
('clocks', 0{post})
```

**Model steps, not taken**: `JO` bytes 7000

```
('clocks', 0{pre})
('take', 1)
('clocks', 4{cond})
('decide')
('clocks', 1{nexec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `cfgap` | 8 | table | cond_gap=own: fgap for a taken form with a condition field [C:1416-1419; T:1403-1406] |
| `cond` | 4 | rows | short transfers with a condition field: the flag test clocks after the displacement take [T:1396-1399] |
| `exec` | 8 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 6 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `nexec` | 1 | rows | transfer not taken: clocks after the decide step [T:1400-1402] |
| `nfgap` | 1 | table | untaken=wait: the same wait for a not-taken transfer (decide step) [C:1410-1411; E:1332] |
| `nhold` | 3 | table | xfer_nt=odd: clocks into the clocks after a not-taken short transfer's operand take at which its odd-address hold ends [C:1330-1331; E:846-853] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:75 `70-7F` Jcc rel8 (NEC Bcond): measured not taken 4, taken 13 (incl. flush+refetch) for 72/73/74/75 (J29,J30,J33-J36,J47-J49; M:186-187); other conditions not measured; routine `JCC` V20UC.TXT L66-70, L71-75 (ROM 0034-0037, 0038-003B); toE/total(nb) 3 / 6 (5); flags F:- / W:- / E:0036,0039 / R:-; FARJMP –; JMP 0035 JMP OPC 4 ->0038; note: condition from pla_2 (pla_model.md); 0035 JMP OPC 4 -> 0038 when taken
- work/v30-opcodes.md:139 `EB` JMP rel8 (BR short): measured 12 (J42,J43; M:191); routine `JMP_SHORT` V20UC.TXT L431-435 (ROM 0158-015B); toE/total(nb) 4 / 4 (4); flags F:- / W:- / E:015B / R:-; FARJMP –; JMP –

  Routine `JCC` (work/v30-opcodes.md:325):
```
0034 Q->tmpbL; ALU ADD tmpa
0035 JMP OPC 4 ->0038
0036   [E]
0037 —
0038 PC->tmpa; CTL SUSP
0039 SIGMA->PC; CTL FLUSH  [E]
```

  Routine `JMP_SHORT` (work/v30-opcodes.md:959):
```
0158 Q->tmpbL; ALU ADD tmpa
0159 CTL SUSP
015A PC->tmpa
015B SIGMA->PC; CTL FLUSH  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `hold`=6, `nhold`=3, `fgap`=5, `nfgap`=1, `cfgap`=8.

## 18. BRK (`V35_CLS_BRK`)

**Forms**: 257 enumerated, opcodes CC, CD. Examples: INT imm8 [BRK] x256; INT 3 [BRK 3] x1 (2 distinct names).

**V35 measured**:
- a6: `BRK 3 (trap)` (BRK 3): V35 62 (even 62, odd -); V30 43 (doc [38]); V35 - V30 = 19

**Model steps, register / no-memory form**: `INT imm8 [BRK]` bytes cd00

```
('clocks', 0{pre})
('take', 1, 'chain')
('post', 'read', 0, 2, 12{rsetup}, 8{rfree})
('issued')
('clocks', 3{rexec})
('wait')
('data', 'write', 0x7fe, 2, 3{setup})
('post', 'read', 2, 2, 6{vsetup}, 6{vsetup})
('issued')
('clocks', 3{rexec})
('wait')
('data', 'write', 0x7fc, 2, 3{setup})
('data', 'write', 0x7fa, 2, 7{wsetup}, 7{wsetup})
('clocks', 8{exec})
('flush', 0x1000)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 8 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 6 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rexec` | 3 | rows | brk: EU clocks from a vector read's issue to the push after it [C:1476-1477; T:1577] |
| `rfree` | 8 | rows | fetch-free clocks of rsetup (pop_mem stack read, brk vector offset) [T:1321, 1573] |
| `rfree0` | 10 | rows | brk_free=format: BRK 3's own rfree [C:1481-1483; T:1573] |
| `rsetup` | 12 | rows | a read's setup where the template names it separately (immediate memory forms' read, pop_mem's stack read, brk vector offset) [C:1340-1342, 1476; T:1005, 1321, 1574] |
| `setup` | 3 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `vsetup` | 6 | rows | brk: the vector segment read's setup (all fetch-free) [C:1477-1478; T:1575] |
| `wsetup` | 7 | rows | second and later word's setup (push_r/pop_r burst words, call_far return offset, far returns' segment, LES/LDS segment word, RETI PS/PSW, INS write-back) [C:1429-1432; T:1384, 1491, 1518, 1564] |

**V30 counterpart**: 
- work/v30-opcodes.md:119 `CC` INT 3 (BRK 3): measured BRK 3 trap to handler 43 (J44; M:341) - encoding (CC vs CD 03) not recorded in J44; routine `INT3` V20UC.TXT L326-330 (ROM 0104-0107); toE/total(nb) no E (exits via FARJMP) / 2 (2); flags F:- / W:- / E:- / R:-; FARJMP INT; JMP –
- work/v30-opcodes.md:120 `CD` INT imm8 (BRK imm8): measured not measured (see CC); routine `INT_N` V20UC.TXT L331-335 (ROM 0108-010B); toE/total(nb) no E (exits via FARJMP) / 1 (1); flags F:- / W:- / E:- / R:-; FARJMP INT; JMP –

  Routine `INT3` (work/v30-opcodes.md:765):
```
0104 CONST(3)->tmpbL; CTL SUSP
0105 FARJMP INT
```

  Routine `INT_N` (work/v30-opcodes.md:774):
```
0108 Q->tmpbL; FARJMP INT
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=6, `fgap`=5, `setup_free`=3, `rfree`=8, `rfree0`=10.

## 19. CALL (`V35_CLS_CALL`)

**Forms**: 256 enumerated, opcodes E8. Examples: CALL near x256 (1 distinct names).

**V35 measured**:
- a6: `CALL 0x0600` (CALL near-proc): V35 32 (even 32, odd -); V30 18 (doc [16]); V35 - V30 = 14

**Model steps, register / no-memory form**: `CALL near` bytes e80002

```
('clocks', 3{pre})
('take', 2)
('data', 'write', 0x7fe, 2, 7{setup})
('clocks', 8{exec})
('flush', 0x203)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 8 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 10 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `pre` | 3 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |

**V30 counterpart**: 
- work/v30-opcodes.md:136 `E8` CALL rel16: measured 18 (J52; M:194); routine `CALL_NEAR` V20UC.TXT L416-420, L421-425 (ROM 014C-014F, 0150-0153); toE/total(nb) 6 / 6 (6); flags F:- / W:- / E:0151 / R:-; FARJMP –; JMP –

  Routine `CALL_NEAR` (work/v30-opcodes.md:935):
```
014C Q->tmpaL, SP->tmpb; ALU DEC2 tmpb
014D Q->tmpaH
014E SIGMA->SP, SIGMA->IND; CTL SUSP
014F PC->tmpb; ALU ADD tmpa
0150 SIGMA->PC; CTL FLUSH
0151 tmpb->OPR; CTL MEMW SS  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=10, `fgap`=5, `setup_free`=3.

## 20. CALL_FAR (`V35_CLS_CALL_FAR`)

**Forms**: 256 enumerated, opcodes 9A. Examples: CALL far imm x256 (1 distinct names).

**V35 measured**:
- a6: `CALL far 0:0x0600` (CALL far-proc): V35 45 (even 45, odd -); V30 27 (doc [21]); V35 - V30 = 18

**Model steps, register / no-memory form**: `CALL far imm` bytes 9a00020000

```
('clocks', 3{pre})
('take', 2, 'chain')
('clocks', 2{spre})
('take', 2, 'chain')
('data', 'write', 0x7fe, 2, 6{tsetup}, 3{tfree}, False, False, True)
('data', 'write', 0x7fc, 2, 7{wsetup}, 7{wsetup})
('clocks', 8{exec})
('flush', 0x200)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 8 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 16 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `pre` | 3 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 3 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `spre` | 2 | rows | far forms: clocks between the offset word's take and the segment word's [C:1434-1435; T:1474-1476] |
| `tfree` | 3 | rows | its fetch-free tail [C:1436-1437; T:1518] |
| `tsetup` | 6 | rows | call_far (call_far_post=take): first write's setup from the clock after the segment take [C:1436-1437; T:1517-1518] |
| `wpre` | 1 | rows | CALL r16 / far: clocks between the operand take and the first write's post [C:1435; T:1482] |
| `wsetup` | 7 | rows | second and later word's setup (push_r/pop_r burst words, call_far return offset, far returns' segment, LES/LDS segment word, RETI PS/PSW, INS write-back) [C:1429-1432; T:1384, 1491, 1518, 1564] |

**V30 counterpart**: 
- work/v30-opcodes.md:88 `9A` CALL far ptr16:16: measured 27 (J50; M:195); routine `CALL_FAR_DIR` V20UC.TXT L131-135 (ROM 0068-006B); toE/total(nb) no E (exits via FARJMP) / 4 (4); flags F:- / W:- / E:- / R:-; FARJMP CALLF; JMP –

  Routine `CALL_FAR_DIR` (work/v30-opcodes.md:436):
```
0068 Q->tmpaL
0069 Q->tmpaH
006A Q->tmpbL
006B Q->tmpbH; FARJMP CALLF
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=16, `fgap`=5, `setup_free`=3, `tfree`=3.

## 21. CALL_FAR_MEM (`V35_CLS_CALL_FAR_MEM`)

**Forms**: 24 enumerated, opcodes FF. Examples: CALL far rm16 (mem) x24 (1 distinct names).

**V35 measured**: not in the sources (no eu-timing row, no a6 form).

**Model steps, memory form**: `CALL far rm16 (mem)` bytes ff18, EA mode base_index (ea table `base_index`)

```
('take', 1, 'lead')
('clocks', 0{pre})
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 2, 6{grp}, 6, True)
('data', 'read', 0x302, 2, 5{rwsetup}, 5{rwsetup})
('data', 'write', 0x7fe, 2, 7{setup})
('data', 'write', 0x7fc, 2, 7{wsetup}, 7{wsetup})
('clocks', 8{exec})
('flush', 0x1000)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `dhold` | 3 | table | xfer_mem_disp=grp / grp_disp=hold: clocks after a d16's take a fetch is held (falls back to grp_free) [E:1154-1164; C:1468-1470] |
| `exec` | 8 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `grp` | 6 | rows | group memory form: the group setup clocks before the first data request (as EU clocks or extra setup per grp_mode) [T:1032-1041] |
| `grp_free` | 6 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `hold` | 16 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rwsetup` | 5 | rows | far memory-indirect transfers: the segment word's read setup, every clock fetch-free [C:1470-1471; T:1588] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 7 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `wsetup` | 7 | rows | second and later word's setup (push_r/pop_r burst words, call_far return offset, far returns' segment, LES/LDS segment word, RETI PS/PSW, INS write-back) [C:1429-1432; T:1384, 1491, 1518, 1564] |

**V30 counterpart**: 
- work/v30-opcodes.md:164 `FE/FF /3` CALL m16:16 (far indirect): measured not measured; routine `FF_CALL_FAR` V20UC.TXT L561-565 (ROM 01C0-01C3); toE/total(nb) no E (exits via FARJMP) / 4 (4); flags F:01C1,01C3 / W:- / E:- / R:-; FARJMP CALLF; JMP –

  Routine `FF_CALL_FAR` (work/v30-opcodes.md:1112):
```
01C0 SIGMA->tmpb; CTL SUSP
01C1 OPR->tmpa; ALU INC2 tmpb  [F]
01C2 SIGMA->IND; CTL MEMR
01C3 OPR->tmpb; FARJMP CALLF  [F]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=16, `fgap`=5, `dhold`=3, `setup_free`=7, `grp_free`=6.

## 22. CALL_MEM (`V35_CLS_CALL_MEM`)

**Forms**: 24 enumerated, opcodes FF. Examples: CALL near rm16 (mem) x24 (1 distinct names).

**V35 measured**:
- a6: `CALL [BW]` (CALL memptr16): V35 37 (even 37, odd -); V30 26 (doc [23]); V35 - V30 = 11

**Model steps, memory form**: `CALL near rm16 (mem)` bytes ff10, EA mode base_index (ea table `base_index`)

```
('take', 1, 'lead')
('clocks', 0{pre})
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 2, 6{grp}, 6, True)
('data', 'write', 0x7fe, 2, 7{setup})
('clocks', 8{exec})
('flush', 0x1000)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `dhold` | 3 | table | xfer_mem_disp=grp / grp_disp=hold: clocks after a d16's take a fetch is held (falls back to grp_free) [E:1154-1164; C:1468-1470] |
| `exec` | 8 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `grp` | 6 | rows | group memory form: the group setup clocks before the first data request (as EU clocks or extra setup per grp_mode) [T:1032-1041] |
| `grp_free` | 6 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `hold` | 10 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 7 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |

**V30 counterpart**: 
- work/v30-opcodes.md:163 `FE/FF /2` CALL r/m16 (near indirect): measured reg 16 (J53); mem 26 (J51); M:194-195; routine `FF_CALL_NEAR` V20UC.TXT L556-560 (ROM 01BC-01BF); toE/total(nb) 4 / 4 (4); flags F:- / W:- / E:01BF / R:-; FARJMP –; JMP –; note: FE with reg 2-7 is not a documented form; the ROM block matches on the ModR/M byte only

  Routine `FF_CALL_NEAR` (work/v30-opcodes.md:1101):
```
01BC PC->tmpa, SP->tmpb; ALU DEC2 tmpb
01BD M->PC, SIGMA->IND; CTL FLUSH
01BE SIGMA->SP; CTL MEMW SS
01BF tmpa->OPR  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=10, `fgap`=5, `dhold`=3, `setup_free`=7, `grp_free`=6.

## 23. CALL_REG (`V35_CLS_CALL_REG`)

**Forms**: 8 enumerated, opcodes FF. Examples: CALL near rm16 (reg) x8 (1 distinct names).

**V35 measured**:
- a6: `CALL DW` (CALL regptr16): V35 32 (even 32, odd -); V30 16 (doc [14]); V35 - V30 = 16

**Model steps, register / no-memory form**: `CALL near rm16 (reg)` bytes ffd0

```
('take', 1)
('clocks', 3{pre})
('data', 'write', 0x7fe, 2, 7{setup})
('clocks', 8{exec})
('flush', 5)
('clocks', 0{post})
# step count changes with: wpre
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 8 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 10 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `pre` | 3 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 7 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |

**V30 counterpart**: 
- work/v30-opcodes.md:163 `FE/FF /2` CALL r/m16 (near indirect): measured reg 16 (J53); mem 26 (J51); M:194-195; routine `FF_CALL_NEAR` V20UC.TXT L556-560 (ROM 01BC-01BF); toE/total(nb) 4 / 4 (4); flags F:- / W:- / E:01BF / R:-; FARJMP –; JMP –; note: FE with reg 2-7 is not a documented form; the ROM block matches on the ModR/M byte only

  Routine `FF_CALL_NEAR` (work/v30-opcodes.md:1101):
```
01BC PC->tmpa, SP->tmpb; ALU DEC2 tmpb
01BD M->PC, SIGMA->IND; CTL FLUSH
01BE SIGMA->SP; CTL MEMW SS
01BF tmpa->OPR  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=10, `fgap`=5, `setup_free`=7.

## 24. CONVERT (`V35_CLS_CONVERT`)

**Forms**: 256 enumerated, opcodes D4. Examples: AAM [CVTBD] x256 (1 distinct names).

**V35 measured**:
- CVTBD 22, any AL (docs/v35s-eu-timing.md:222)
- a6: `CVTBD [AW=0053]` (CVTBD (no operand)): V35 22 (even 22, odd 22); V30 15 (doc [15]); V35 - V30 = 7
- a6: `CVTBD [AW=00FF]` (CVTBD (no operand)): V35 22 (even 22, odd 22); V30 15 (doc [15]); V35 - V30 = 7

**Model steps, register / no-memory form**: `AAM [CVTBD]` bytes d400

```
('clocks', 3{pre})
('take', 1)
('clocks', 16{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 16 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `hrel` | 1 | rows | fetch hold released hrel clocks before the form's last clock (bf_imm_hold, bcd_fetch, cvt_hold) [C:1343-1344; T:1641, 1707, 1745] |
| `hx` | 1 | rows | convert (cvt_tail=release): clocks more after the fetch hold's release [T:1625-1628] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 3 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:125 `D4` AAM imm8 (CVTBD): measured 15 (J74,J75; M:207); routine `AAM` V20UC.TXT L356-360, L361-365 (ROM 011C-011F, 0120-0123); toE/total(nb) 6 / 7 (7); flags F:- / W:0122 / E:0121 / R:011F; FARJMP –; JMP –; note: divide by Q via ALU DIV repeated (COUNT=8)

  Routine `AAM` (work/v30-opcodes.md:824):
```
011C Q->tmpc, AX->tmpa
011D ZEROS->tmpb
011E CONST(8)->COUNT; ALU SUB tmpc
011F SIGMA->tmpb; ALU DIV tmpc  [R]
0120 SIGMA->NULL, SIGMA->tmpb; ALU DIV tmpc
0121 tmpa->AH; ALU PASS tmpb  [E]
0122 SIGMA->AL  [W]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `hrel`=1.

## 25. CONVERT_D (`V35_CLS_CONVERT_D`)

**Forms**: 256 enumerated, opcodes D5. Examples: AAD [CVTDB] x256 (1 distinct names).

**V35 measured**:
- CVTDB 21, any AL (docs/v35s-eu-timing.md:223)
- a6: `CVTDB [AW=0503]` (CVTDB (no operand)): V35 21 (even 21, odd 20); V30 8 (doc [7]); V35 - V30 = 13

**Model steps, register / no-memory form**: `AAD [CVTDB]` bytes d500

```
('clocks', 2{pre})
('take', 1)
('clocks', 16{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 16 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `hrel` | 3 | rows | fetch hold released hrel clocks before the form's last clock (bf_imm_hold, bcd_fetch, cvt_hold) [C:1343-1344; T:1641, 1707, 1745] |
| `hx` | 2 | rows | convert (cvt_tail=release): clocks more after the fetch hold's release [T:1625-1628] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 2 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 0 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:126 `D5` AAD imm8 (CVTDB): measured 8 (J77; M:207); routine `AAD` V20UC.TXT L366-370, L371-375 (ROM 0124-0127, 0128-012B); toE/total(nb) 7 / 8 (8); flags F:- / W:012B / E:012A / R:-; FARJMP –; JMP –

  Routine `AAD` (work/v30-opcodes.md:838):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hrel`=3.

## 26. DBNZ (`V35_CLS_DBNZ`)

**Forms**: 512 enumerated, opcodes E2. Examples: LOOP [DBNZ] x512 (1 distinct names).

**V35 measured**:
- a6: `DBNZ t (taken)` (DBNZ short-label): V35 26 (even 26, odd -); V30 15 (doc [13]); V35 - V30 = 11
- a6: `DBNZ t (not-taken)` (DBNZ short-label): V35 12 (even 12, odd -); V30 5 (doc [5]); V35 - V30 = 7

**Model steps, taken**: `LOOP [DBNZ]` bytes e200

```
('clocks', 0{pre})
('take', 1)
('clocks', 14{exec})
('flush', 2)
('clocks', 0{post})
```

**Model steps, not taken**: `LOOP [DBNZ]` bytes e200

```
('clocks', 0{pre})
('take', 1)
('decide')
('clocks', 6{nexec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 14 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 2 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `nexec` | 6 | rows | transfer not taken: clocks after the decide step [T:1400-1402] |
| `nfgap` | 1 | table | untaken=wait: the same wait for a not-taken transfer (decide step) [C:1410-1411; E:1332] |
| `nhold` | 4 | table | xfer_nt=odd: clocks into the clocks after a not-taken short transfer's operand take at which its odd-address hold ends [C:1330-1331; E:846-853] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:132 `E2` LOOP (DBNZ): measured not taken 5, taken 15 (J80,J81; M:188); routine `LOOP` V20UC.TXT L396-400, L391-395 (ROM 013C-013F, 0138-013B); toE/total(nb) 4 / 8 (8); flags F:- / W:- / E:013F,013B / R:-; FARJMP –; JMP 013E JMP NZ 5 ->0139

  Routine `LOOP` (work/v30-opcodes.md:886):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `hold`=2, `nhold`=4, `fgap`=5, `nfgap`=1.

## 27. DBNZ_Z (`V35_CLS_DBNZ_Z`)

**Forms**: 1536 enumerated, opcodes E0, E1. Examples: LOOPNZ [DBNZNE] x768; LOOPZ [DBNZE] x768 (2 distinct names).

**V35 measured**:
- a6: `DBNZE t (taken)` (DBNZE short-label): V35 27 (even 27, odd -); V30 16 (doc [14]); V35 - V30 = 11
- a6: `DBNZE t (not-taken)` (DBNZE short-label): V35 9 (even 9, odd -); V30 5 (doc [5]); V35 - V30 = 4
- a6: `DBNZNE t (taken)` (DBNZNE short-label): V35 27 (even 27, odd -); V30 16 (doc [14]); V35 - V30 = 11
- a6: `DBNZNE t (not-taken)` (DBNZNE short-label): V35 9 (even 9, odd -); V30 5 (doc [5]); V35 - V30 = 4

**Model steps, taken**: `LOOPNZ [DBNZNE]` bytes e000

```
('clocks', 0{pre})
('take', 1)
('clocks', 15{exec})
('flush', 2)
('clocks', 0{post})
```

**Model steps, not taken**: `LOOPNZ [DBNZNE]` bytes e000

```
('clocks', 0{pre})
('take', 1)
('decide')
('clocks', 7{nexec})
```

**Model steps, not taken on the Z test (zfail)**: `LOOPNZ [DBNZNE]` bytes e000

```
('clocks', 0{pre})
('take', 1)
('decide')
('clocks', 4{zexec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `chold` | 5 | table | compares (str_hold=hold): no fetch request for chold clocks after a compared element; dbnz_z: nhold for the count's exit [C:1500-1501, 1433-1434; T:1813-1816; E:849-851] |
| `exec` | 15 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 2 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `nexec` | 7 | rows | transfer not taken: clocks after the decide step [T:1400-1402] |
| `nfgap` | 1 | table | untaken=wait: the same wait for a not-taken transfer (decide step) [C:1410-1411; E:1332] |
| `nhold` | 2 | table | xfer_nt=odd: clocks into the clocks after a not-taken short transfer's operand take at which its odd-address hold ends [C:1330-1331; E:846-853] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |
| `zexec` | 4 | rows | dbnz_z not taken on its Z test: its clocks (nexec when the count ended it) [C:1432-1433; T:1470] |

**V30 counterpart**: 
- work/v30-opcodes.md:130 `E0` LOOPNZ (DBNZNE): measured not taken 5, taken 16 (J84,J85; M:189-190); routine `LOOPCC` V20UC.TXT L386-390, L391-395 (ROM 0134-0137, 0138-013B); toE/total(nb) 4 / 8 (7); flags F:- / W:- / E:0137,013B / R:-; FARJMP –; JMP 0136 JMP REP 4 ->0138
- work/v30-opcodes.md:131 `E1` LOOPZ (DBNZE): measured not taken 5, taken 16 (J82,J83); routine `LOOPCC` V20UC.TXT L386-390, L391-395 (ROM 0134-0137, 0138-013B); toE/total(nb) 4 / 8 (7); flags F:- / W:- / E:0137,013B / R:-; FARJMP –; JMP 0136 JMP REP 4 ->0138

  Routine `LOOPCC` (work/v30-opcodes.md:871):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `hold`=2, `nhold`=2, `chold`=5, `fgap`=5, `nfgap`=1.

## 28. DISPOSE (`V35_CLS_DISPOSE`)

**Forms**: 1 enumerated, opcodes C9. Examples: LEAVE [DISPOSE] x1 (1 distinct names).

**V35 measured**:
- DISPOSE 11.5 (docs/v35s-eu-timing.md:217)
- a6: `DISPOSE [BP=0F10]` (DISPOSE (no operand)): V35 11.5 (even 11, odd 12); V30 9 (doc [6]); V35 - V30 = 2.5

**Model steps, register / no-memory form**: `LEAVE [DISPOSE]` bytes c9

```
('data', 'read', 0x400, 2, 7{setup})
('clocks', 2{exec})
# step count changes with: pre
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 2 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |

**V30 counterpart**: 
- work/v30-opcodes.md:116 `C9` LEAVE (DISPOSE): measured 9 (J89; M:337); routine `LEAVE` V20UC.TXT L786-790 (ROM 0274-0277); toE/total(nb) 4 / 4 (4); flags F:0277 / W:- / E:0277 / R:-; FARJMP –; JMP –

  Routine `LEAVE` (work/v30-opcodes.md:1185):
```
0274 BP->IND, BP->tmpb; CTL MEMR SS
0275 CONST(2)->tmpa; ALU ADD tmpa
0276 SIGMA->SP
0277 OPR->BP  [FE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `setup_free`=3.

## 29. DIV (`V35_CLS_DIV`)

**Forms**: 128 enumerated, opcodes F6, F7. Examples: DIV rm8 (mem) x24; IDIV rm8 (mem) x24; DIV rm16 (mem) x24; IDIV rm16 (mem) x24; DIV rm8 (reg) x8; IDIV rm8 (reg) x8; ... (8 distinct names).

**V35 measured**:
- DIVU r8 34, DIVU r16 42, DIV r8 53, DIV r16 61 base, +7 negative dividend, +2 negative quotient (docs/v35s-eu-timing.md:184)
- divide error 143-181 (docs/v35s-eu-timing.md:190)
- a6: `DIVU CW [AW=0009 CW=0003 DW=0000]` (DIVU reg16): V35 42 (even 42, odd 42); V30 28 (doc [25]); V35 - V30 = 14

**Model steps, register / no-memory form**: `DIV rm8 (reg)` bytes f6f0

```
('clocks', 0{pre})
('take', 1)
('clocks', 39{exec})
```

**Model steps, memory form**: `DIV rm8 (mem)` bytes f630, EA mode base_index (ea table `base_index`)

```
('clocks', 0{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 1, 4{grp}, 3{grp_free(in max/min)}, True)
('clocks', 37{mexec}, 'mexec')
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 39 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `grp` | 4 | rows | group memory form: the group setup clocks before the first data request (as EU clocks or extra setup per grp_mode) [T:1032-1041] |
| `grp_free` | 3 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `hphase` | 2 | table | unit_hold: the exec clock of the first micro-boundary (every second exec clock from it) at which a register shift/mul/div waits for a fetch past its second clock [E:608-613; C:1310-1311] |
| `mexec` | 37 | rows | mul/div/mul_imm memory form: clocks after the read data (the multiply/divide) [T:1231-1242, 1688] |
| `mtail` | 2 | table | mul/div (abort_unit=loop, io_take): clocks before the exec's end at which a request an aborted start dropped is raised again [C:1307-1309, 1312-1315; E:734, 899, 918] |
| `mwb` | 2 | table | a memory-operand form's own wb [E:322-323] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rexit` | 6 | rows | REP string exit clocks when CW ran out; mul/div (refresh on): the exec's last clocks run as the loop exit [C:1325-1329, 1494; T:1850, 1133] |
| `sexec` | 58 | rows | mul/div: the signed register form's exec (F7 /5, /7); rmw_imm: extra clocks of the memory shift by imm8's ALU step [C:1356-1357, 1375-1380; T:1227, 1259] |
| `smexec` | 58 | rows | mul/div memory form, signed operation (F7 /5, /7): its own mexec [C:1305-1306; T:1233] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:153 `F6/F7 /6` DIV r/m (NEC DIVU): measured reg16 28 (J90,J91; M:156); reg8/mem not measured; routine `F6_DIV` V20UC.TXT L491-495, L496-500, L501-505, L506-510 (ROM 0188-018B, 018C-018F, 0190-0193, 0194-0197); toE/total(nb) 12 / 15 (14); flags F:- / W:018B,018E / E:0193,0196 / R:0190; FARJMP INT; JMP 0189 JMP OP8 4 ->018C; 018B JMP always 7 ->018F; 018F JMP NC 13 ->0195; 0192 JMP OP8 14 ->0196; note: divide-error path 0195 ZEROS->tmpbL; FARJMP INT (vector 0)
- work/v30-opcodes.md:154 `F6/F7 /7` IDIV r/m (NEC DIV): measured relative to dispatch: early trap 21+s, late trap 36+s (byte) / 44+s (word), non-trap 37+s / 44+s, s=3 iff dividend negative (M:446-474); not an F-spacing figure; routine `F6_IDIV` V20UC.TXT L511-515, L516-520 (ROM 0198-019B, 019C-019F); toE/total(nb) no E (exits via FARJMP) / 8 (8); flags F:- / W:- / E:- / R:-; FARJMP IDIV; JMP 019B JMP OP8 5 ->019D; 019C JMP always 6 ->019E

  Routine `F6_DIV` (work/v30-opcodes.md:1055):
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

  Routine `F6_IDIV` (work/v30-opcodes.md:1077):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Divide-error cost 143-181 (eu-timing.md:190) is outside the model. Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `mwb`=2, `grp_free`=3, `mtail`=2, `hphase`=2.

## 30. EXTEND (`V35_CLS_EXTEND`)

**Forms**: 1 enumerated, opcodes 98. Examples: CBW [CVTBW] x1 (1 distinct names).

**V35 measured**:
- CVTBW 3 (docs/v35s-eu-timing.md:227)
- a6: `CVTBW [AW=0080]` (CVTBW (no operand)): V35 3 (even 2, odd 4); V30 2 (doc [2]); V35 - V30 = 1

**Model steps, register / no-memory form**: `CBW [CVTBW]` bytes 98

```
('clocks', 3{pre0})
('take', 0)
('clocks', 0{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `nx0` | 0 | table | form without operand bytes: its successor's IR load held nx0 clocks from its start [decoder.py:112-114; E:459-460] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 3 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |
| `wb` | 1 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:86 `98` CBW (CVTBW): measured 2 (J76; M:208); routine `CBW` V20UC.TXT L121-125 (ROM 0060-0063); toE/total(nb) 1 / 2 (2); flags F:- / W:- / E:0060 / R:-; FARJMP –; JMP –

  Routine `CBW` (work/v30-opcodes.md:416):
```
0060 AX->tmpbL  [E]
0061 tmpb->AX
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1, `wb`=1.

## 31. EXTEND_W (`V35_CLS_EXTEND_W`)

**Forms**: 1 enumerated, opcodes 99. Examples: CWD [CVTWL] x1 (1 distinct names).

**V35 measured**:
- CVTWL 9.5 (docs/v35s-eu-timing.md:226)
- a6: `CVTWL [AW=0001]` (CVTWL (no operand)): V35 9.5 (even 9, odd 10); V30 5 (doc [4, 5]); V35 - V30 = 4.5
- a6: `CVTWL [AW=8000]` (CVTWL (no operand)): V35 9.5 (even 9, odd 10); V30 5 (doc [4, 5]); V35 - V30 = 4.5

**Model steps, register / no-memory form**: `CWD [CVTWL]` bytes 99

```
('clocks', 9{pre0})
('take', 0)
('clocks', 0{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `nx0` | 8 | table | form without operand bytes: its successor's IR load held nx0 clocks from its start [decoder.py:112-114; E:459-460] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 9 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |
| `wb` | 3 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:87 `99` CWD (CVTWL): measured 5 (J78,J79; M:208); routine `CWD` V20UC.TXT L126-130 (ROM 0064-0067); toE/total(nb) 4 / 4 (4); flags F:- / W:- / E:0067 / R:-; FARJMP –; JMP 0065 JMP NS 3 ->0067

  Routine `CWD` (work/v30-opcodes.md:425):
```
0064 ZEROS->DX, AX->tmpb
0065 JMP NS 3 ->0067
0066 ONES->DX
0067   [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1, `nx0`=8, `wb`=3.

## 32. FLAG (`V35_CLS_FLAG`)

**Forms**: 7 enumerated, opcodes 9E, 9F, F5, F8, F9, FC, FD. Examples: SAHF x1; LAHF x1; CMC [NOT1 CY] x1; CLC [CLR1 CY] x1; STC [SET1 CY] x1; CLD [CLR1 DIR] x1; ... (7 distinct names).

**V35 measured**:
- CLR1 / NOT1 CY 2.5 (docs/v35s-eu-timing.md:228)
- a6: `CLR1 CY` (CLR1 CY): V35 2.5 (even 2, odd 3); V30 2 (doc [2]); V35 - V30 = 0.5
- a6: `CLR1 DIR` (CLR1 DIR): V35 2.5 (even 2, odd 3); V30 2 (doc [2]); V35 - V30 = 0.5
- a6: `NOT1 CY` (NOT1 CY): V35 2.5 (even 2, odd 3); V30 2 (doc [2]); V35 - V30 = 0.5
- a6: `SET1 CY` (SET1 CY): V35 2.5 (even 2, odd 3); V30 2 (doc [2]); V35 - V30 = 0.5
- a6: `SET1 DIR` (SET1 DIR): V35 2.5 (even 2, odd 3); V30 2 (doc [2]); V35 - V30 = 0.5

**Model steps, register / no-memory form**: `SAHF` bytes 9e

```
('clocks', 3{pre0})
('take', 0)
('clocks', 0{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `nx0` | 0 | table | form without operand bytes: its successor's IR load held nx0 clocks from its start [decoder.py:112-114; E:459-460] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 3 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |
| `wb` | 1 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:92 `9E` SAHF (MOV PSW,AH): measured not measured; routine `SAHF` V20UC.TXT L156-160 (ROM 007C-007F); toE/total(nb) 2 / 3 (3); flags F:- / W:- / E:007D / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:93 `9F` LAHF (MOV AH,PSW): measured not measured; routine `LAHF` V20UC.TXT L161-165 (ROM 0080-0083); toE/total(nb) 1 / 1 (1); flags F:- / W:- / E:0080 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:147 `F5` CMC (NOT1 CY): measured 2 (J189); routine not in the sources V20UC.TXT – (ROM –); toE/total(nb) –; flags –; FARJMP –; JMP –; note: not in the sources (ROM): pla_3 1BL XOP 1010
- work/v30-opcodes.md:155 `F8` CLC (CLR1 CY): measured 2 (J56); routine not in the sources V20UC.TXT – (ROM –); toE/total(nb) –; flags –; FARJMP –; JMP –; note: not in the sources (ROM): pla_3 1BL XOP 0111
- work/v30-opcodes.md:156 `F9` STC (SET1 CY): measured 2 (J241); routine not in the sources V20UC.TXT – (ROM –); toE/total(nb) –; flags –; FARJMP –; JMP –; note: not in the sources (ROM): pla_3 1BL XOP 0110
- work/v30-opcodes.md:159 `FC` CLD (CLR1 DIR): measured 2 (J57); routine not in the sources V20UC.TXT – (ROM –); toE/total(nb) –; flags –; FARJMP –; JMP –; note: not in the sources (ROM): pla_3 1BL XOP 0011
- work/v30-opcodes.md:160 `FD` STD (SET1 DIR): measured 2 (J242); routine not in the sources V20UC.TXT – (ROM –); toE/total(nb) –; flags –; FARJMP –; JMP –; note: not in the sources (ROM): pla_3 1BL XOP 0010

  Routine `SAHF` (work/v30-opcodes.md:483):
```
007C AL:AH->tmpaL
007D FLAGS->tmpaH  [E]
007E tmpa->FLAGS
```

  Routine `LAHF` (work/v30-opcodes.md:493):
```
0080 FLAGS->AH  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1, `wb`=1.

## 33. FLAG_DI (`V35_CLS_FLAG_DI`)

**Forms**: 1 enumerated, opcodes FA. Examples: CLI [DI] x1 (1 distinct names).

**V35 measured**: not in the sources (no eu-timing row, no a6 form).

**Model steps, register / no-memory form**: `CLI [DI]` bytes fa

```
('clocks', 4{pre0})
('take', 0)
('clocks', 0{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `nx0` | 3 | table | form without operand bytes: its successor's IR load held nx0 clocks from its start [decoder.py:112-114; E:459-460] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 4 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |
| `wb` | 3 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:157 `FA` CLI (DI): measured not measured; routine not in the sources V20UC.TXT – (ROM –); toE/total(nb) –; flags –; FARJMP –; JMP –; note: not in the sources (ROM): pla_3 1BL XOP 0101

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1, `nx0`=3, `wb`=3.

## 34. FLAG_EI (`V35_CLS_FLAG_EI`)

**Forms**: 1 enumerated, opcodes FB. Examples: STI [EI] x1 (1 distinct names).

**V35 measured**: not in the sources (no eu-timing row, no a6 form).

**Model steps, register / no-memory form**: `STI [EI]` bytes fb

```
('clocks', 13{pre0})
('take', 0)
('clocks', 0{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `nx0` | 12 | table | form without operand bytes: its successor's IR load held nx0 clocks from its start [decoder.py:112-114; E:459-460] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 13 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |
| `wb` | 3 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:158 `FB` STI (EI): measured not measured; routine not in the sources V20UC.TXT – (ROM –); toE/total(nb) –; flags –; FARJMP –; JMP –; note: not in the sources (ROM): pla_3 1BL XOP 0100

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1, `nx0`=12, `wb`=3.

## 35. HALT (`V35_CLS_HALT`)

**Forms**: 1 enumerated, opcodes F4. Examples: HLT x1 (1 distinct names).

**V35 measured**: not in the sources (no eu-timing row, no a6 form).

**Model steps, register / no-memory form**: `HLT` bytes f4

```
('halt')
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |


**V30 counterpart**: 
- work/v30-opcodes.md:146 `F4` HLT (HALT): measured 4 F-pop to HALT T1 (J94; M:343); routine not in the sources V20UC.TXT – (ROM –); toE/total(nb) –; flags –; FARJMP –; JMP –; note: not in the sources (ROM): pla_3 1BL XOP 1011

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: nothing beyond the integers above; the sources give no micro-instruction breakdown for this class on the V35.

## 36. IMM (`V35_CLS_IMM`)

**Forms**: 8968 enumerated, opcodes 04, 05, 0C, 0D, 14, 15, 1C, 1D, 24, 25, 2C, 2D, 34, 35, 3C, 3D, 80, 81, 82, 83, A8, A9, B0, B1, B2, B3, B4, B5, B6, B7, B8, B9, BA, BB, BC, BD, BE, BF, F7. Examples: ADD AL,imm8 x256; ADD AX,imm16 x256; OR AL,imm8 x256; OR AX,imm16 x256; ADC AL,imm8 x256; ADC AX,imm16 x256; ... (59 distinct names).

**V35 measured**:
- MOV reg,imm16 7 (B8+r, C7) (docs/v35s-eu-timing.md:57)
- MOV reg8,imm 6 (B0+r, C6) (docs/v35s-eu-timing.md:58)
- ADD acc,imm 6 / 7 (04 / 05); 6 / 7 (80 / 81 reg), 6 (83) (docs/v35s-eu-timing.md:59)
- TEST acc,imm 6 / 7 (A8 / A9) (docs/v35s-eu-timing.md:60)
- F3: MOV CL,imm8 6; MOV/ADD AW,imm16 7 (docs/v35s-chains.md:175)
- a6: `ADD AL, 0x11` (ADD acc,imm): V35 6 (even 6, odd 6); V30 4 (doc [4]); V35 - V30 = 2
- a6: `ADD AW, 0x1111` (ADD acc,imm): V35 7 (even 6, odd 8); V30 4 (doc [4]); V35 - V30 = 3
- a6: `ADD BW, 0x0111` (ADD reg,imm): V35 7 (even 7, odd 7); V30 6 (doc [4]); V35 - V30 = 1
- a6: `ADD BW, 0x11` (ADD reg,imm): V35 6 (even 5, odd 7); V30 6 (doc [4]); V35 - V30 = 0
- a6: `ADDC AW, 0x1111` (ADDC acc,imm): V35 7 (even 6, odd 8); V30 4 (doc [4]); V35 - V30 = 3
- a6: `AND AW, 0x1111` (AND acc,imm): V35 7 (even 6, odd 8); V30 4 (doc [4]); V35 - V30 = 3
- a6: `CMP AW, 0x1111` (CMP acc,imm): V35 7 (even 6, odd 8); V30 4 (doc [4]); V35 - V30 = 3
- a6: `CMP BW, 0x11` (CMP reg,imm): V35 6 (even 5, odd 7); V30 6 (doc [4]); V35 - V30 = 0
- a6: `MOV AW, 0x1234` (MOV reg,imm): V35 7 (even 6, odd 8); V30 4 (doc [4]); V35 - V30 = 3
- a6: `MOV BL, 0x12` (MOV reg,imm): V35 6 (even 6, odd 6); V30 4 (doc [4]); V35 - V30 = 2
- a6: `MOV BW, 0x1234` (MOV reg,imm): V35 7 (even 6, odd 8); V30 4 (doc [4]); V35 - V30 = 3
- a6: `OR AW, 0x1111` (OR acc,imm): V35 7 (even 6, odd 8); V30 4 (doc [4]); V35 - V30 = 3
- a6: `SUB AW, 0x1111` (SUB acc,imm): V35 7 (even 6, odd 8); V30 4 (doc [4]); V35 - V30 = 3
- a6: `SUBC AW, 0x1111` (SUBC acc,imm): V35 7 (even 6, odd 8); V30 4 (doc [4]); V35 - V30 = 3
- a6: `TEST AW, 0x1111` (TEST acc,imm): V35 7 (even 6, odd 8); V30 4 (doc [4]); V35 - V30 = 3
- a6: `XOR AW, 0x1111` (XOR acc,imm): V35 7 (even 6, odd 8); V30 4 (doc [4]); V35 - V30 = 3
- a6: `XOR BW, 0x0111` (XOR reg,imm): V35 7 (even 7, odd 7); V30 6 (doc [4]); V35 - V30 = 1

**Model steps, register / no-memory form**: `ADD AL,imm8` bytes 0400

```
('clocks', 3{pre})
('take', 1)
('clocks', 0{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `pre` | 3 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 0 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:25 `04/05` ADD AL/AX,imm: measured 4 (J0 byte, J1 word); routine `ALU_ACC` V20UC.TXT L6-10 (ROM 0004-0007); toE/total(nb) 3 / 4 (4); flags F:- / W:0007 / E:0006 / R:-; FARJMP –; JMP 0004 JMP OP8 2 ->0006; note: 0004 JMP OP8 skips the imm high byte for the byte form
- work/v30-opcodes.md:29 `0C/0D` OR acc,imm: measured 4 (J197 word); byte not measured; routine `ALU_ACC` V20UC.TXT L6-10 (ROM 0004-0007); toE/total(nb) 3 / 4 (4); flags F:- / W:0007 / E:0006 / R:-; FARJMP –; JMP 0004 JMP OP8 2 ->0006; note: 0004 JMP OP8 skips the imm high byte for the byte form
- work/v30-opcodes.md:33 `14/15` ADC acc,imm (ADDC): measured 4 (J18 word); routine `ALU_ACC` V20UC.TXT L6-10 (ROM 0004-0007); toE/total(nb) 3 / 4 (4); flags F:- / W:0007 / E:0006 / R:-; FARJMP –; JMP 0004 JMP OP8 2 ->0006; note: 0004 JMP OP8 skips the imm high byte for the byte form
- work/v30-opcodes.md:37 `1C/1D` SBB acc,imm (SUBC): measured 4 (J276 word); routine `ALU_ACC` V20UC.TXT L6-10 (ROM 0004-0007); toE/total(nb) 3 / 4 (4); flags F:- / W:0007 / E:0006 / R:-; FARJMP –; JMP 0004 JMP OP8 2 ->0006; note: 0004 JMP OP8 skips the imm high byte for the byte form
- work/v30-opcodes.md:41 `24/25` AND acc,imm: measured 4 (J26 word); routine `ALU_ACC` V20UC.TXT L6-10 (ROM 0004-0007); toE/total(nb) 3 / 4 (4); flags F:- / W:0007 / E:0006 / R:-; FARJMP –; JMP 0004 JMP OP8 2 ->0006; note: 0004 JMP OP8 skips the imm high byte for the byte form
- work/v30-opcodes.md:45 `2C/2D` SUB acc,imm: measured 4 (J272 word); routine `ALU_ACC` V20UC.TXT L6-10 (ROM 0004-0007); toE/total(nb) 3 / 4 (4); flags F:- / W:0007 / E:0006 / R:-; FARJMP –; JMP 0004 JMP OP8 2 ->0006; note: 0004 JMP OP8 skips the imm high byte for the byte form
- work/v30-opcodes.md:49 `34/35` XOR acc,imm: measured 4 (J295 word); routine `ALU_ACC` V20UC.TXT L6-10 (ROM 0004-0007); toE/total(nb) 3 / 4 (4); flags F:- / W:0007 / E:0006 / R:-; FARJMP –; JMP 0004 JMP OP8 2 ->0006; note: 0004 JMP OP8 skips the imm high byte for the byte form
- work/v30-opcodes.md:53 `3C/3D` CMP acc,imm: measured 4 (J65 word); routine `ALU_ACC` V20UC.TXT L6-10 (ROM 0004-0007); toE/total(nb) 3 / 4 (4); flags F:- / W:0007 / E:0006 / R:-; FARJMP –; JMP 0004 JMP OP8 2 ->0006; note: 0004 JMP OP8 skips the imm high byte for the byte form
- ... 5 more rows: `80-83 /0-/7`, `A8/A9`, `B0-B7`, `B8-BF`, `F6/F7 /0,/1`

  Routine `ALU_ACC` (work/v30-opcodes.md:209):
```
0004 M->tmpb, Q->tmpa; JMP OP8 2 ->0006
0005 Q->tmpaH
0006 ALU OPC tmpa  [E]
0007 SIGMA->M  [W]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: nothing beyond the integers above; the sources give no micro-instruction breakdown for this class on the V35.

## 37. IN (`V35_CLS_IN`)

**Forms**: 514 enumerated, opcodes E4, E5, EC, ED. Examples: IN AL,imm8 x256; IN AX,imm8 x256; IN AL,DX x1; IN AX,DX x1 (4 distinct names).

**V35 measured**:
- a6: `IN AL, DW [DW=0040]` (IN acc,DW): V35 11.5 (even 11, odd 12); V30 9 (doc [8]); V35 - V30 = 2.5
- a6: `IN AW, DW [DW=0040]` (IN acc,DW): V35 11.5 (even 11, odd 12); V30 9 (doc [8]); V35 - V30 = 2.5
- a6: `IN AL, 0x40` (IN acc,imm8): V35 15 (even 15, odd 16); V30 9 (doc [9]); V35 - V30 = 6
- a6: `IN AW, 0x40` (IN acc,imm8): V35 15 (even 15, odd 16); V30 9 (doc [9]); V35 - V30 = 6

**Model steps, register / no-memory form**: `IN AL,imm8` bytes e400

```
('clocks', 3{pre})
('take', 1, 'port', ('io_read', 0, 1, 8{setup}), False)
('wait')
('clocks', 2{post})
# step count changes with: wbsync
```

**Model steps, form without operand bytes**: `IN AL,DX` bytes ec

```
('clocks', 0{pre0})
('post', 'io_read', 224, 1, 7{setup0})
('wait')
('clocks', 2{post})
# step count changes with: wbsync
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 3 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `lead` | 0 | table | I/O: the last setup clocks during which the bus unit has committed to the I/O (Request.lead) [C:1298-1299; E:1929] |
| `post` | 2 | rows | clocks after the last data cycle is issued (stores, RMW, transfers after the flush); IN: clocks after the data [C:1293, 1302] |
| `pre` | 3 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 0 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |
| `relatch` | 3 | table | port_latch=relatch: clocks a port byte's take holds a waiting detached I/O request [C:1300; E:1890; machine.py:218] |
| `setup` | 8 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup0` | 7 | rows | I/O form without a port byte (DW): its own setup [T:1431] |
| `wb` | 0 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |
| `wbsync` | 0 | table | 1: the template begins by waiting for the previous instruction's write-back [C:1296-1297; E:474-479, 1323] |

**V30 counterpart**: 
- work/v30-opcodes.md:134 `E4/E5` IN AL/AX,imm8: measured 9 (J97,J98; M:210); routine `IN_IMM` V20UC.TXT L406-410 (ROM 0144-0147); toE/total(nb) 3 / 3 (3); flags F:0146 / W:- / E:0146 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:140 `EC/ED` IN AL/AX,DX: measured 9 (J95,J96); routine `IN_DX` V20UC.TXT L446-450 (ROM 0164-0167); toE/total(nb) 2 / 2 (2); flags F:0165 / W:- / E:0165 / R:-; FARJMP –; JMP –

  Routine `IN_IMM` (work/v30-opcodes.md:916):
```
0144 Q->tmpaL
0145 tmpa->IND; CTL MEMR IO
0146 OPR->M  [FE]
```

  Routine `IN_DX` (work/v30-opcodes.md:983):
```
0164 DX->IND; CTL MEMR IO
0165 OPR->M  [FE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `relatch`=3.

## 38. INCDEC (`V35_CLS_INCDEC`)

**Forms**: 32 enumerated, opcodes 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 4A, 4B, 4C, 4D, 4E, 4F, FE. Examples: INC rm8 (reg) x8; DEC rm8 (reg) x8; INC AX x1; INC CX x1; INC DX x1; INC BX x1; ... (18 distinct names).

**V35 measured**:
- INC/DEC reg16: 2.5 (40+r), 6 (FF /0) (docs/v35s-eu-timing.md:52)
- INC reg8: 6 (docs/v35s-eu-timing.md:53)
- read-modify-write of a register (INC/DEC via ModR/M, NOT, NEG, TEST reg,reg) 6 (docs/v35s-eu-timing.md:66)
- a6: `DEC AW` (DEC reg16): V35 2.5 (even 2, odd 3); V30 2 (doc [2]); V35 - V30 = 0.5
- a6: `DEC DL` (DEC reg8): V35 6 (even 6, odd 6); V30 4 (doc [2]); V35 - V30 = 2
- a6: `INC AW` (INC reg16): V35 2.5 (even 2, odd 3); V30 2 (doc [2]); V35 - V30 = 0.5
- a6: `INC DL` (INC reg8): V35 6 (even 6, odd 6); V30 4 (doc [2]); V35 - V30 = 2

**Model steps, register / no-memory form**: `INC rm8 (reg)` bytes fec0

```
('clocks', 3{pre})
('take', 1)
('clocks', 0{exec})
```

**Model steps, form without operand bytes**: `INC AX` bytes 40

```
('clocks', 3{pre0})
('take', 0)
('clocks', 0{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `nx0` | 0 | table | form without operand bytes: its successor's IR load held nx0 clocks from its start [decoder.py:112-114; E:459-460] |
| `pre` | 3 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 3 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |
| `rwb` | 0 | table | incdec: INC/DEC r8's own wb (WP114) [E:325-326] |
| `wb` | 1 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:56 `40-47` INC r16: measured 2 (J101,J102; M:135); routine `INCDEC_R16` V20UC.TXT L46-50 (ROM 0024-0027); toE/total(nb) 1 / 2 (2); flags F:- / W:0025 / E:0024 / R:-; FARJMP –; JMP –; note: ALU OPC (INC/DEC chosen by opcode bit 3)
- work/v30-opcodes.md:57 `48-4F` DEC r16: measured 2 (J87); routine `INCDEC_R16` V20UC.TXT L46-50 (ROM 0024-0027); toE/total(nb) 1 / 2 (2); flags F:- / W:0025 / E:0024 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:161 `FE/FF /0` INC r/m: measured reg8 4 (J103; M:138); mem word 20 (J99); odd 28 (J100); routine `FF_INCDEC` V20UC.TXT L551-555 (ROM 01B8-01BB); toE/total(nb) 2 / 2 (2); flags F:- / W:01B9 / E:01B9 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:162 `FE/FF /1` DEC r/m: measured reg8 4 (J88); mem word 20 (J86); routine `FF_INCDEC` V20UC.TXT L551-555 (ROM 01B8-01BB); toE/total(nb) 2 / 2 (2); flags F:- / W:01B9 / E:01B9 / R:-; FARJMP –; JMP –

  Routine `INCDEC_R16` (work/v30-opcodes.md:287):
```
0024 M->tmpb; ALU OPC tmpb  [E]
0025 SIGMA->M  [W]
```

  Routine `FF_INCDEC` (work/v30-opcodes.md:1092):
```
01B8 M->tmpb; ALU OPC tmpb
01B9 SIGMA->M; CTL [-06-]  [WE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Short form 2.5 against ModR/M form 6 (eu-timing.md:52); the ModR/M register forms are class rmw in the model. Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=1.

## 39. LEA (`V35_CLS_LEA`)

**Forms**: 192 enumerated, opcodes 8D. Examples: LEA [LDEA] (mem) x192 (1 distinct names).

**V35 measured**:
- LDEA 6 (+EA) (docs/v35s-eu-timing.md:149)
- a6: `LDEA BW, [0x0800] [BW=0800]` (LDEA reg16,mem16): V35 6 (even 6, odd 6); V30 5 (doc [4]); V35 - V30 = 1
- a6: `LDEA BW, [BW+IX] [BW=0800]` (LDEA reg16,mem16): V35 6 (even 6, odd 6); V30 3 (doc [4]); V35 - V30 = 3

**Model steps, memory form**: `LEA [LDEA] (mem)` bytes 8d00, EA mode base_index (ea table `base_index`)

```
('clocks', 0{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('clocks', 0{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `fwb` | 5 | table | lea: lea_wb=fetch, LDEA started on a fetch issue clock writes back to fwb clocks after that fetch's last clock [E:314-319] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |

**V30 counterpart**: 
- work/v30-opcodes.md:81 `8D` LEA (LDEA): measured [BW+IX] 3 (J107); direct 5 (J106); M:335; routine `LEA` V20UC.TXT L106-110 (ROM 0054-0057); toE/total(nb) 1 / 2 (2); flags F:- / W:- / E:0054 / R:-; FARJMP –; JMP –; note: EA computed by hardware; 0055 SIGMA->R takes it after the E row

  Routine `LEA` (work/v30-opcodes.md:386):
```
0054   [E]
0055 SIGMA->R
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `fwb`=5.

## 40. LOAD (`V35_CLS_LOAD`)

**Forms**: 896 enumerated, opcodes 8A, 8B, A0, A1. Examples: MOV AL,[m] x256; MOV AX,[m] x256; MOV r8,rm8 (mem) x192; MOV r16,rm16 (mem) x192 (4 distinct names).

**V35 measured**:
- word or byte load 10 (+EA 0 / +1 / +2, lines 145-147) (docs/v35s-eu-timing.md:149)
- odd-address word load +4 (docs/v35s-eu-timing.md:152)
- BP-based = BW-based (docs/v35s-eu-timing.md:151)
- F4: MOV AW,r/m16 11 / 10 (mod 00), 11 / 11 (d8), 13 / 12 (base+index+d16) (docs/v35s-chains.md:193)
- a6: `MOV AL, [0x0802] [BW=0800]` (MOV acc,dmem): V35 11.5 (even 11, odd 12); V30 10 (doc [10]); V35 - V30 = 1.5
- a6: `MOV AW, [0x0801] [DS0=0000]` (MOV acc,dmem): V35 14.5 (even 14, odd 15); V30 14 (doc [14]); V35 - V30 = 0.5
- a6: `MOV AW, [0x0802] [BW=0800]` (MOV acc,dmem): V35 11.5 (even 11, odd 12); V30 10 (doc [10]); V35 - V30 = 1.5
- a6: `MOV DL, byte [BW] [BW=0800]` (MOV reg,mem): V35 10 (even 10, odd 11); V30 13 (doc [11]); V35 - V30 = -3
- a6: `MOV DL, byte [BW] [BW=0801]` (MOV reg,mem): V35 10 (even 10, odd 11); V30 13 (doc [11]); V35 - V30 = -3
- a6: `MOV DW, [BW] [BW=0800]` (MOV reg,mem): V35 10 (even 10, odd 11); V30 13 (doc [11]); V35 - V30 = -3
- a6: `MOV DW, [BW] [BW=0801 DS0=0000 IX=0010]` (MOV reg,mem): V35 13 (even 13, odd 14); V30 17 (doc [15]); V35 - V30 = -4
- a6 (with prefix): `DS0: MOV AW,[BW] (redundant) [BW=0800]`: V35 12.5, V30 13
- a6 (with prefix): `DS1: MOV AW,[BW] [BW=0800]`: V35 12.5, V30 13
- a6 (with prefix): `SS: MOV AW,[BW] [BW=0800]`: V35 12.5, V30 13
- a6 (with prefix): `DS1: DS0: MOV AW,[BW] (stacked) [BW=0800]`: V35 16, V30 16

**Model steps, memory form**: `MOV r8,rm8 (mem)` bytes 8a00, EA mode base_index (ea table `base_index`)

```
('clocks', 0{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 1, 0)
('clocks', 0)
('clocks', 2{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `exec` | 2 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 2 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |
| `wb` | 0 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:79 `88-8B` MOV r/m,r / r,r/m: measured reg,reg 3 (J130-J132); load 13 (J126-J128); odd word load 17 (J129); store 11 (J117,J118); odd-anchor store 10 (J119); odd store 15 (J120); routine `MOV_RM` V20UC.TXT L96-100 (ROM 004C-004F); toE/total(nb) 2 / 2 (2); flags F:- / W:- / E:004D / R:-; FARJMP –; JMP –; note: 88/89 stores: operand pre-read suppressed (pla_3 MODRM_STORE)
- work/v30-opcodes.md:94 `A0/A1` MOV AL/AX,[moffs]: measured 10 (J111,J113); odd word 14 (J112); M:142; routine `MOV_ACC_DMEM` V20UC.TXT L166-170 (ROM 0084-0087); toE/total(nb) 4 / 4 (4); flags F:0087 / W:- / E:0087 / R:-; FARJMP –; JMP –

  Routine `MOV_RM` (work/v30-opcodes.md:369):
```
004C R->tmpa
004D tmpa->M; CTL [-06-]  [E]
```

  Routine `MOV_ACC_DMEM` (work/v30-opcodes.md:501):
```
0084 Q->tmpbL
0085 Q->tmpbH
0086 tmpb->IND; CTL MEMR
0087 OPR->M  [FE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `dfloor`=2.

## 41. LOAD_ALU (`V35_CLS_LOAD_ALU`)

**Forms**: 3456 enumerated, opcodes 02, 03, 0A, 0B, 12, 13, 1A, 1B, 22, 23, 2A, 2B, 32, 33, 3A, 3B, 84, 85. Examples: ADD r8,rm8 (mem) x192; ADD r16,rm16 (mem) x192; OR r8,rm8 (mem) x192; OR r16,rm16 (mem) x192; ADC r8,rm8 (mem) x192; ADC r16,rm16 (mem) x192; ... (18 distinct names).

**V35 measured**:
- ADD reg,mem 10 (+EA) (docs/v35s-eu-timing.md:149)
- a6: `ADD DL, byte [BW] [BW=0800]` (ADD reg,mem): V35 10 (even 10, odd 11); V30 13 (doc [11]); V35 - V30 = -3
- a6: `ADD DW, [BW] [BW=0800]` (ADD reg,mem): V35 10 (even 10, odd 11); V30 13 (doc [11]); V35 - V30 = -3
- a6: `ADD DW, [BW] [BW=0801 DS0=0000 IX=0010]` (ADD reg,mem): V35 13 (even 13, odd 14); V30 17 (doc [15]); V35 - V30 = -4
- a6: `AND DW, [BW] [BW=0800]` (AND reg,mem): V35 10 (even 10, odd 11); V30 13 (doc [11]); V35 - V30 = -3
- a6: `CMP DW, [BW] [BW=0800]` (CMP reg,mem): V35 10 (even 10, odd 11); V30 13 (doc [11]); V35 - V30 = -3
- a6: `SUB DW, [BW] [BW=0800]` (SUB reg,mem): V35 10 (even 10, odd 11); V30 13 (doc [11]); V35 - V30 = -3
- a6: `TEST [BW], DW [BW=0800]` (TEST mem,reg or TEST reg,mem): V35 13 (even 13, odd 13); V30 12 (doc [10]); V35 - V30 = 1

**Model steps, memory form**: `ADD r8,rm8 (mem)` bytes 0200, EA mode base_index (ea table `base_index`)

```
('clocks', 0{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 1, 0)
('clocks', 0)
('clocks', 2{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `dclk` | 2 | table | dest_route: clocks a form spends routing its result to the operand its direction bit does not name [T:1143-1158] |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `exec` | 2 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fdisp` | 3 | rows | load_alu: fixed_lookup=decoder, the TEST lookup's EU clocks between the ModR/M take and the displacement take [T:1066-1078] |
| `fgrp` | 2 | table | load_alu: the fixed operation's lookup (TEST, F6/F7 /0) clocks added to the group setup (grp_fixed) and to the imm floor (fixed_floor) [T:1090-1104; E:443-447] |
| `fgrp_free` | 2 | table | load_alu: fetch-free part of fgrp [T:1094, 1104] |
| `grp` | 4 | rows | group memory form: the group setup clocks before the first data request (as EU clocks or extra setup per grp_mode) [T:1032-1041] |
| `grp_free` | 3 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 0 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:24 `00-03` ADD r/m,r / r,r/m (NEC ADD): measured reg,reg 3 (J11,J12); reg,mem 13 (J7,J8); odd-anchor reg,mem 12 (J9); mem,reg RMW 19 (J3); odd RMW 27 (J4); classes M:136,139,144; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:28 `08-0B` OR r/m,r / r,r/m (OR): measured reg,reg 3 (J198); mem forms not measured (class: load 13 M:139, RMW 19 M:144); routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:32 `10-13` ADC (NEC ADDC): measured reg,reg 3 (J19); mem forms not measured; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:36 `18-1B` SBB (NEC SUBC): measured reg,reg 3 (J277); mem forms not measured; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:40 `20-23` AND (AND): measured reg,reg 3 (J28); reg,mem 13 (J27); RMW not measured; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:44 `28-2B` SUB (SUB): measured reg,reg 3 (J274); reg,mem 13 (J273); RMW not measured; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:48 `30-33` XOR (XOR): measured reg,reg 3 (J298,J299); mem,reg RMW 19 (J296); routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:52 `38-3B` CMP (CMP): measured reg,reg 3 (J70); mem,reg 13 (J67); reg,mem 13 (J69) - no writeback; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- ... 1 more rows: `84/85`

  Routine `ALU_RM` (work/v30-opcodes.md:200):
```
0000 M->tmpb, R->tmpa; ALU OPC tmpa
0001 SIGMA->M; CTL [-06-]  [WE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: CMP / CHKIND / CMPBK pay +2 to +3 of the RAMEN write penalty though they write nothing (eu-timing.md:89-95: "probably run the memory form's write-back step with the write suppressed. That is not modelled yet"). TEST [BW],DW is 13 against ADD reg,mem's 10. Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `dfloor`=2, `grp_free`=3, `fgrp_free`=2, `dclk`=2.

## 42. LOAD_PTR (`V35_CLS_LOAD_PTR`)

**Forms**: 384 enumerated, opcodes C4, C5. Examples: LES [MOV DS1] (mem) x192; LDS [MOV DS0] (mem) x192 (2 distinct names).

**V35 measured**: not in the sources (no eu-timing row, no a6 form).

**Model steps, memory form**: `LES [MOV DS1] (mem)` bytes c400, EA mode base_index (ea table `base_index`)

```
('clocks', 0{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 2, 0)
('data', 'read', 0x302, 2, 5{wsetup}, 5{wsetup})
('fetch_hold', 3{phold})
('clocks', 0)
('clocks', 5{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `exec` | 5 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `phold` | 3 | rows | LES/LDS, POP PSW: no fetch request for phold clocks from the last read's data [C:1436; T:1523-1524] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 2 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |
| `wsetup` | 5 | rows | second and later word's setup (push_r/pop_r burst words, call_far return offset, far returns' segment, LES/LDS segment word, RETI PS/PSW, INS write-back) [C:1429-1432; T:1384, 1491, 1518, 1564] |

**V30 counterpart**: 
- work/v30-opcodes.md:112 `C4` LES r16,m32 (MOV DS1,...): measured not measured; routine `LES` V20UC.TXT L311-315 (ROM 00F8-00FB); toE/total(nb) 3 / 3 (3); flags F:00F8,00FA / W:- / E:00FA / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:113 `C5` LDS r16,m32 (MOV DS0,...): measured not measured; routine `LDS` V20UC.TXT L316-320 (ROM 00FC-00FF); toE/total(nb) 3 / 3 (3); flags F:00FC,00FE / W:- / E:00FE / R:-; FARJMP –; JMP –

  Routine `LES` (work/v30-opcodes.md:735):
```
00F8 OPR->R, SIGMA->tmpb; ALU INC2 tmpb  [F]
00F9 SIGMA->IND; CTL MEMR
00FA OPR->ES  [FE]
```

  Routine `LDS` (work/v30-opcodes.md:745):
```
00FC OPR->R, SIGMA->tmpb; ALU INC2 tmpb  [F]
00FD SIGMA->IND; CTL MEMR
00FE OPR->DS  [FE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `dfloor`=2, `phold`=3.

## 43. LOAD_SEG (`V35_CLS_LOAD_SEG`)

**Forms**: 192 enumerated, opcodes 8E. Examples: MOV sreg,rm16 (mem) x192 (1 distinct names).

**V35 measured**:
- a6: `MOV DS1, [BW] [BW=0800]` (MOV sreg,mem16): V35 11 (even 11, odd 11); V30 12 (doc [11]); V35 - V30 = -1

**Model steps, memory form**: `MOV sreg,rm16 (mem)` bytes 8e00, EA mode base_index (ea table `base_index`)

```
('clocks', 0{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 2, 0)
('clocks', 0)
('clocks', 3{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `exec` | 3 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 2 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |

**V30 counterpart**: 
- work/v30-opcodes.md:82 `8E` MOV sreg,r/m16: measured reg 2 (J136); mem 12 (J135); routine `MOV_SREG` V20UC.TXT L101-105 (ROM 0050-0053); toE/total(nb) 1 / 1 (1); flags F:- / W:- / E:0050 / R:-; FARJMP –; JMP –

  Routine `MOV_SREG` (work/v30-opcodes.md:378):
```
0050 R->M; CTL [-06-]  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `dfloor`=2.

## 44. MUL (`V35_CLS_MUL`)

**Forms**: 128 enumerated, opcodes F6, F7. Examples: MUL rm8 (mem) x24; IMUL rm8 (mem) x24; MUL rm16 (mem) x24; IMUL rm16 (mem) x24; MUL rm8 (reg) x8; IMUL rm8 (reg) x8; ... (8 distinct names).

**V35 measured**:
- MULU r8 26, MULU r16 34, MUL r8 37, MUL r16 44 (signs equal) (docs/v35s-eu-timing.md:164)
- signs differ: +8, +1 low half zero, +1 more high half zero (docs/v35s-eu-timing.md:170)
- F3: MULU DW 34 each, +1 once (docs/v35s-chains.md:177)
- a6: `MUL word [BW] [AW=7FFF BW=0800; ram]` (MUL mem16): V35 50 (even 50, odd 50); V30 51 (doc [47, 48, 49, 50, 51, 52, 53]); V35 - V30 = -1
- a6: `MUL word [BW] [AW=FFFF BW=0800; ram]` (MUL mem16): V35 50 (even 50, odd 50); V30 51 (doc [47, 48, 49, 50, 51, 52, 53]); V35 - V30 = -1
- a6: `MUL byte [BW] [AW=007F BW=0800; ram]` (MUL mem8): V35 43 (even 43, odd 43); V30 44 (doc [39, 40, 41, 42, 43, 44, 45]); V35 - V30 = -1
- a6: `MUL byte [BW] [AW=00FF BW=0800; ram]` (MUL mem8): V35 43 (even 43, odd 43); V30 44 (doc [39, 40, 41, 42, 43, 44, 45]); V35 - V30 = -1
- a6: `MUL CW [AW=0000 CW=0000]` (MUL reg16): V35 44 (even 44, odd 44); V30 41 (doc [41, 42, 43, 44, 45, 46, 47]); V35 - V30 = 3
- a6: `MUL CW [AW=0001 CW=0001]` (MUL reg16): V35 44 (even 44, odd 44); V30 41 (doc [41, 42, 43, 44, 45, 46, 47]); V35 - V30 = 3
- a6: `MUL CW [AW=7FFF CW=7FFF]` (MUL reg16): V35 44 (even 44, odd 44); V30 41 (doc [41, 42, 43, 44, 45, 46, 47]); V35 - V30 = 3
- a6: `MUL CW [AW=8000 CW=0000]` (MUL reg16): V35 54 (even 54, odd 54); V30 45 (doc [41, 42, 43, 44, 45, 46, 47]); V35 - V30 = 9
- a6: `MUL CW [AW=8000 CW=7FFF]` (MUL reg16): V35 52 (even 52, odd 52); V30 45 (doc [41, 42, 43, 44, 45, 46, 47]); V35 - V30 = 7
- a6: `MUL CW [AW=FFFF CW=0001]` (MUL reg16): V35 52 (even 52, odd 52); V30 45 (doc [41, 42, 43, 44, 45, 46, 47]); V35 - V30 = 7
- a6: `MUL CW [AW=FFFF CW=FFFF]` (MUL reg16): V35 44 (even 44, odd 44); V30 41 (doc [41, 42, 43, 44, 45, 46, 47]); V35 - V30 = 3
- a6: `MUL CL [AW=0000 CW=0000]` (MUL reg8): V35 37 (even 37, odd 37); V30 34 (doc [33, 34, 35, 36, 37, 38, 39]); V35 - V30 = 3
- a6: `MUL CL [AW=0001 CW=0001]` (MUL reg8): V35 37 (even 37, odd 37); V30 34 (doc [33, 34, 35, 36, 37, 38, 39]); V35 - V30 = 3
- a6: `MUL CL [AW=0002 CW=00C0]` (MUL reg8): V35 45 (even 45, odd 45); V30 38 (doc [33, 34, 35, 36, 37, 38, 39]); V35 - V30 = 7
- a6: `MUL CL [AW=007F CW=007F]` (MUL reg8): V35 37 (even 37, odd 37); V30 34 (doc [33, 34, 35, 36, 37, 38, 39]); V35 - V30 = 3
- a6: `MUL CL [AW=0080 CW=007F]` (MUL reg8): V35 45 (even 45, odd 45); V30 38 (doc [33, 34, 35, 36, 37, 38, 39]); V35 - V30 = 7
- a6: `MUL CL [AW=00FF CW=0000]` (MUL reg8): V35 47 (even 47, odd 47); V30 38 (doc [33, 34, 35, 36, 37, 38, 39]); V35 - V30 = 9
- a6: `MUL CL [AW=00FF CW=0001]` (MUL reg8): V35 45 (even 45, odd 45); V30 38 (doc [33, 34, 35, 36, 37, 38, 39]); V35 - V30 = 7
- a6: `MUL CL [AW=00FF CW=00FF]` (MUL reg8): V35 37 (even 37, odd 37); V30 34 (doc [33, 34, 35, 36, 37, 38, 39]); V35 - V30 = 3
- a6: `MULU word [BW] [AW=0000 BW=0800; ram]` (MULU mem16): V35 40 (even 40, odd 40); V30 41 (doc [35, 36]); V35 - V30 = -1
- a6: `MULU word [BW] [AW=0007 BW=0800; ram]` (MULU mem16): V35 40 (even 40, odd 40); V30 41 (doc [35, 36]); V35 - V30 = -1
- a6: `MULU word [BW] [AW=FFFF BW=0800; ram]` (MULU mem16): V35 40 (even 40, odd 40); V30 41 (doc [35, 36]); V35 - V30 = -1
- a6: `MULU word [BW] [AW=0007 BW=0801 DS0=0000 IX=0010; ram]` (MULU mem16): V35 43 (even 43, odd 43); V30 45 (doc [39, 40]); V35 - V30 = -2
- a6: `MULU byte [BW] [AW=0000 BW=0800; ram]` (MULU mem8): V35 32 (even 32, odd 32); V30 34 (doc [27, 28]); V35 - V30 = -2
- a6: `MULU byte [BW] [AW=0007 BW=0800; ram]` (MULU mem8): V35 32 (even 32, odd 32); V30 34 (doc [27, 28]); V35 - V30 = -2
- a6: `MULU byte [BW] [AW=00FF BW=0800; ram]` (MULU mem8): V35 32 (even 32, odd 32); V30 34 (doc [27, 28]); V35 - V30 = -2
- a6: `MULU CW [AW=0000 CW=0000]` (MULU reg16): V35 34 (even 34, odd 34); V30 31 (doc [29, 30]); V35 - V30 = 3
- a6: `MULU CW [AW=0001 CW=0001]` (MULU reg16): V35 34 (even 34, odd 34); V30 31 (doc [29, 30]); V35 - V30 = 3
- a6: `MULU CW [AW=0007 CW=0005]` (MULU reg16): V35 34 (even 34, odd 34); V30 31 (doc [29, 30]); V35 - V30 = 3
- a6: `MULU CW [AW=1234 CW=5678]` (MULU reg16): V35 34 (even 34, odd 34); V30 31 (doc [29, 30]); V35 - V30 = 3
- a6: `MULU CW [AW=8000 CW=0002]` (MULU reg16): V35 34 (even 34, odd 34); V30 31 (doc [29, 30]); V35 - V30 = 3
- a6: `MULU CW [AW=FFFF CW=FFFF]` (MULU reg16): V35 34 (even 34, odd 34); V30 31 (doc [29, 30]); V35 - V30 = 3
- a6: `MULU CL [AW=0000 CW=0000]` (MULU reg8): V35 26 (even 26, odd 26); V30 24 (doc [21, 22]); V35 - V30 = 2
- a6: `MULU CL [AW=0001 CW=0001]` (MULU reg8): V35 26 (even 26, odd 26); V30 24 (doc [21, 22]); V35 - V30 = 2
- a6: `MULU CL [AW=0007 CW=0005]` (MULU reg8): V35 26 (even 26, odd 26); V30 24 (doc [21, 22]); V35 - V30 = 2
- a6: `MULU CL [AW=0080 CW=0080]` (MULU reg8): V35 26 (even 26, odd 26); V30 24 (doc [21, 22]); V35 - V30 = 2
- a6: `MULU CL [AW=00AA CW=000F]` (MULU reg8): V35 26 (even 26, odd 26); V30 24 (doc [21, 22]); V35 - V30 = 2
- a6: `MULU CL [AW=00FF CW=00FF]` (MULU reg8): V35 26 (even 26, odd 26); V30 24 (doc [21, 22]); V35 - V30 = 2

**Model steps, register / no-memory form**: `MUL rm8 (reg)` bytes f6e0

```
('clocks', 0{pre})
('take', 1)
('clocks', 31{exec})
```

**Model steps, memory form**: `MUL rm8 (mem)` bytes f620, EA mode base_index (ea table `base_index`)

```
('clocks', 0{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 1, 4{grp}, 3{grp_free(in max/min)}, True)
('clocks', 21{bmexec}, 'mexec')
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `bmexec` | 21 | rows | mul/div memory form, byte operation (F6): its own mexec [C:1305-1306; T:1237] |
| `exec` | 31 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `grp` | 4 | rows | group memory form: the group setup clocks before the first data request (as EU clocks or extra setup per grp_mode) [T:1032-1041] |
| `grp_free` | 3 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `hphase` | 2 | table | unit_hold: the exec clock of the first micro-boundary (every second exec clock from it) at which a register shift/mul/div waits for a fetch past its second clock [E:608-613; C:1310-1311] |
| `mexec` | 29 | rows | mul/div/mul_imm memory form: clocks after the read data (the multiply/divide) [T:1231-1242, 1688] |
| `mtail` | 2 | table | mul/div (abort_unit=loop, io_take): clocks before the exec's end at which a request an aborted start dropped is raised again [C:1307-1309, 1312-1315; E:734, 899, 918] |
| `mwb` | 2 | table | a memory-operand form's own wb [E:322-323] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rexit` | 8 | rows | REP string exit clocks when CW ran out; mul/div (refresh on): the exec's last clocks run as the loop exit [C:1325-1329, 1494; T:1850, 1133] |
| `sexec` | 41 | rows | mul/div: the signed register form's exec (F7 /5, /7); rmw_imm: extra clocks of the memory shift by imm8's ALU step [C:1356-1357, 1375-1380; T:1227, 1259] |
| `smexec` | 39 | rows | mul/div memory form, signed operation (F7 /5, /7): its own mexec [C:1305-1306; T:1233] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:151 `F6/F7 /4` MUL r/m (NEC MULU): measured reg8 24, reg16 31, mem8 34, mem16 41, data independent (J163-J182; M:108-110); odd mem16 45 (J166); routine `F6_MUL` V20UC.TXT L471-475, L476-480, L481-485 (ROM 0178-017B, 017C-017F, 0180-0183); toE/total(nb) no E (exits via FARJMP) / 9 (9); flags F:- / W:- / E:- / R:017C; FARJMP MULX; JMP 017A JMP OP8 4 ->017C; 017E JMP OP8 8 ->0180
- work/v30-opcodes.md:152 `F6/F7 /5` IMUL r/m (NEC MUL): measured reg8 34/38, reg16 41/45 (+4 when operand signs differ), mem8 44, mem16 51 (J139-J162; M:111-114); routine `F6_IMUL` V20UC.TXT L486-490 (ROM 0184-0187); toE/total(nb) no E (exits via FARJMP) / 2 (2); flags F:- / W:- / E:- / R:-; FARJMP IMUL; JMP –

  Routine `F6_MUL` (work/v30-opcodes.md:1030):
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

  Routine `F6_IMUL` (work/v30-opcodes.md:1046):
```
0184 M->tmpa, AX->tmpb; ALU [-1E-] tmpb
0185 FARJMP IMUL
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: The V20 ROM gives the 16-bit multiply 8 more loop steps than the 8-bit one but the V30 measures 7 more (24 vs 31; v30-structure.md); on the V35 the difference is 8 (26 vs 34). The sign-dependent +8/+1/+1 (eu-timing.md:170-177) has no ROM line in these notes. Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `mwb`=2, `grp_free`=3, `mtail`=2, `hphase`=2.

## 45. MUL_IMM (`V35_CLS_MUL_IMM`)

**Forms**: 512 enumerated, opcodes 69, 6B. Examples: IMUL r,rm,imm16 [MUL] (mem) x192; IMUL r,rm,imm8 [MUL] (mem) x192; IMUL r,rm,imm16 [MUL] (reg) x64; IMUL r,rm,imm8 [MUL] (reg) x64 (4 distinct names).

**V35 measured**:
- MUL AW,reg,imm8 41 with operand signs equal (docs/v35s-eu-timing.md:168)
- a6: `MUL BW, CW, 0x1234 [CW=0000]` (MUL reg16,reg16,imm16): V35 42 (even 42, odd 43); V30 40 (doc [36, 37, 38, 39, 40, 41, 42]); V35 - V30 = 2
- a6: `MUL BW, CW, 0x7FFF [CW=7FFF]` (MUL reg16,reg16,imm16): V35 42 (even 42, odd 43); V30 40 (doc [36, 37, 38, 39, 40, 41, 42]); V35 - V30 = 2
- a6: `MUL BW, CW, 0x10 [CW=0000]` (MUL reg16,reg16,imm8): V35 41 (even 40, odd 42); V30 40 (doc [28, 29, 30, 31, 32, 33, 34]); V35 - V30 = 1
- a6: `MUL BW, CW, 0x10 [CW=FFFF]` (MUL reg16,reg16,imm8): V35 49 (even 48, odd 50); V30 44 (doc [28, 29, 30, 31, 32, 33, 34]); V35 - V30 = 5
- a6: `MUL BW, CW, 0x7F [CW=7FFF]` (MUL reg16,reg16,imm8): V35 41 (even 40, odd 42); V30 40 (doc [28, 29, 30, 31, 32, 33, 34]); V35 - V30 = 1

**Model steps, register / no-memory form**: `IMUL r,rm,imm16 [MUL] (reg)` bytes 69c00200

```
('clocks', 0{pre})
('take', 1, 'chain')
('clocks', 2{igap})
('take', 2)
('clocks', 35{exec})
```

**Model steps, memory form**: `IMUL r,rm,imm16 [MUL] (mem)` bytes 69000200, EA mode base_index (ea table `base_index`)

```
('clocks', 0{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('post', 'read', 0x300, 2, 5{rsetup})
('issued')
('take', 2, 'chain')
('wait')
('clocks', 0)
('clocks', 43{mexec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 35 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `hphase` | 2 | table | unit_hold: the exec clock of the first micro-boundary (every second exec clock from it) at which a register shift/mul/div waits for a fetch past its second clock [E:608-613; C:1310-1311] |
| `igap` | 2 | rows | mul_imm register form (mul_imm_reg=gap): clocks between the ModR/M take and the immediate's [T:1666-1670] |
| `mexec` | 43 | rows | mul/div/mul_imm memory form: clocks after the read data (the multiply/divide) [T:1231-1242, 1688] |
| `mhold` | 41 | rows | ret_imm / ret_far_imm / mul_imm: a half-taken immediate word holds fetch requests mhold clocks [C:1338-1340, 1435-1436; T:1502-1504, 1674] |
| `mtail` | 2 | table | mul/div (abort_unit=loop, io_take): clocks before the exec's end at which a request an aborted start dropped is raised again [C:1307-1309, 1312-1315; E:734, 899, 918] |
| `mwb` | 2 | table | a memory-operand form's own wb [E:322-323] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rsetup` | 2 | rows | a read's setup where the template names it separately (immediate memory forms' read, pop_mem's stack read, brk vector offset) [C:1340-1342, 1476; T:1005, 1321, 1574] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:68 `69` IMUL r16,r/m16,imm16 (NEC MUL reg16,reg16,imm16): measured 40 (J150,J151; M:114); routine `IMUL_IMM` V20UC.TXT L821-825 (ROM 0290-0293); toE/total(nb) no E (exits via FARJMP) / 4 (4); flags F:- / W:- / E:- / R:-; FARJMP IMULI; JMP 0290 JMP OP8 2 ->0292
- work/v30-opcodes.md:70 `6B` IMUL r16,r/m16,imm8 (NEC MUL reg16,reg16,imm8): measured 40 / 44 when operand signs differ (J152-J154; M:113,117-118); routine `IMUL_IMM` V20UC.TXT L821-825 (ROM 0290-0293); toE/total(nb) no E (exits via FARJMP) / 4 (4); flags F:- / W:- / E:- / R:-; FARJMP IMULI; JMP 0290 JMP OP8 2 ->0292

  Routine `IMUL_IMM` (work/v30-opcodes.md:1248):
```
0290 Q->tmpbL; JMP OP8 2 ->0292
0291 Q->tmpbH
0292 M->tmpa; ALU [-1E-] tmpb
0293 FARJMP IMULI
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `mwb`=2, `mhold`=41, `mtail`=2, `hphase`=2.

## 46. OUT (`V35_CLS_OUT`)

**Forms**: 514 enumerated, opcodes E6, E7, EE, EF. Examples: OUT imm8,AL x256; OUT imm8,AX x256; OUT DX,AL x1; OUT DX,AX x1 (4 distinct names).

**V35 measured**:
- a6: `OUT DW, AL [AW=0055 DW=0040]` (OUT DW,acc): V35 6.5 (even 6, odd 7); V30 9 (doc [8]); V35 - V30 = -2.5
- a6: `OUT DW, AW [AW=5555 DW=0040]` (OUT DW,acc): V35 6.5 (even 6, odd 7); V30 9 (doc [8]); V35 - V30 = -2.5
- a6: `OUT 0x40, AL [AW=0055]` (OUT imm8,acc): V35 10 (even 10, odd 11); V30 9 (doc [8]); V35 - V30 = 1
- a6: `OUT 0x40, AW [AW=5555]` (OUT imm8,acc): V35 10 (even 10, odd 11); V30 9 (doc [8]); V35 - V30 = 1

**Model steps, register / no-memory form**: `OUT imm8,AL` bytes e600

```
('wbsync')
('clocks', 3{pre})
('take', 1, 'port', ('io_write', 0, 1, 8{setup}), True)
('clocks', 2{exec})
```

**Model steps, form without operand bytes**: `OUT DX,AL` bytes ee

```
('clocks', 0{pre0})
('post_io', 'io_write', 224, 1, 7{setup0})
('clocks', 2{exec})
# step count changes with: wbsync0
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 2 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `lead` | 2 | table | I/O: the last setup clocks during which the bus unit has committed to the I/O (Request.lead) [C:1298-1299; E:1929] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 3 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 0 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |
| `relatch` | 3 | table | port_latch=relatch: clocks a port byte's take holds a waiting detached I/O request [C:1300; E:1890; machine.py:218] |
| `setup` | 8 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup0` | 7 | rows | I/O form without a port byte (DW): its own setup [T:1431] |
| `wbsync` | 1 | table | 1: the template begins by waiting for the previous instruction's write-back [C:1296-1297; E:474-479, 1323] |
| `wbsync0` | 0 | table | wbsync for a form without operand bytes [E:476] |

**V30 counterpart**: 
- work/v30-opcodes.md:135 `E6/E7` OUT imm8,AL/AX: measured 9 (J201,J202); routine `OUT_IMM` V20UC.TXT L411-415 (ROM 0148-014B); toE/total(nb) 2 / 2 (2); flags F:- / W:- / E:0149 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:141 `EE/EF` OUT DX,AL/AX: measured 9 (J199,J200); routine `OUT_DX` V20UC.TXT L451-455 (ROM 0168-016B); toE/total(nb) 1 / 2 (2); flags F:- / W:- / E:0168 / R:-; FARJMP –; JMP –

  Routine `OUT_IMM` (work/v30-opcodes.md:926):
```
0148 Q->tmpaL; ALU PASS tmpa
0149 M->OPR, SIGMA->IND; CTL MEMW IO  [E]
```

  Routine `OUT_DX` (work/v30-opcodes.md:992):
```
0168 DX->IND; CTL MEMW IO  [E]
0169 M->OPR
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `relatch`=3, `lead`=2, `wbsync`=1.

## 47. POP (`V35_CLS_POP`)

**Forms**: 8 enumerated, opcodes 58, 59, 5A, 5B, 5C, 5D, 5E, 5F. Examples: POP AX x1; POP CX x1; POP DX x1; POP BX x1; POP SP x1; POP BP x1; ... (8 distinct names).

**V35 measured**:
- POP reg (58+r) 11.5; (8F /0) 11 (docs/v35s-eu-timing.md:55)
- a6: `POP BW` (POP reg16): V35 11.5 (even 11, odd 12); V30 9 (doc [8]); V35 - V30 = 2.5
- a6: `POP BW [SP=0F01 SS=0000]` (POP reg16): V35 14.5 (even 14, odd 15); V30 13 (doc [12]); V35 - V30 = 1.5

**Model steps, register / no-memory form**: `POP AX` bytes 58

```
('data', 'read', 0x800, 2, 7{setup})
('clocks', 2{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 2 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `wb` | 0 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:59 `58-5F` POP r16: measured 9 (J207); SP odd 13 (J208); routine `POP_R16` V20UC.TXT L56-60 (ROM 002C-002F); toE/total(nb) 4 / 4 (4); flags F:002F / W:- / E:002F / R:-; FARJMP –; JMP –

  Routine `POP_R16` (work/v30-opcodes.md:306):
```
002C SP->IND; CTL MEMR SS
002D SP->tmpb; ALU INC2 tmpb
002E SIGMA->SP
002F OPR->M  [FE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `setup_free`=3.

## 48. POP_MEM (`V35_CLS_POP_MEM`)

**Forms**: 256 enumerated, opcodes 8F. Examples: POP rm16 (mem) x192; POP rm16 (reg) x64 (2 distinct names).

**V35 measured**:
- POP reg via 8F /0 11 (register operand) (docs/v35s-eu-timing.md:55)
- a6: `POP word [BW] [BW=0800]` (POP mem16): V35 17 (even 17, odd 17); V30 15 (doc [17]); V35 - V30 = 2

**Model steps, register / no-memory form**: `POP rm16 (reg)` bytes 8fc0

```
('take', 1, 'lead')
('data', 'read', 0x800, 2, 7{rsetup}, 3{rfree})
('post', 'write', None, 2, 4{setup})
('wait')
('clocks', 0{post})
```

**Model steps, memory form**: `POP rm16 (mem)` bytes 8f00, EA mode base_index (ea table `base_index`)

```
('take', 1, 'lead')
('data', 'read', 0x800, 2, 7{rsetup}, 3{rfree})
('post', 'write', 0x300, 2, 6{setup+grp+ea.base_index})
('wait')
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `exec` | 3 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `grp_free` | 3 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `pre` | 2 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rfree` | 3 | rows | fetch-free clocks of rsetup (pop_mem stack read, brk vector offset) [T:1321, 1573] |
| `rsetup` | 7 | rows | a read's setup where the template names it separately (immediate memory forms' read, pop_mem's stack read, brk vector offset) [C:1340-1342, 1476; T:1005, 1321, 1574] |
| `setup` | 4 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 0 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |

**V30 counterpart**: 
- work/v30-opcodes.md:83 `8F /0` POP r/m16: measured mem 15 (J206; M:333); reg form not measured; routine `POP_RM` V20UC.TXT L111-115 (ROM 0058-005B); toE/total(nb) 4 / 4 (4); flags F:005A / W:- / E:005B / R:-; FARJMP –; JMP –; note: [-06-] at 005B writes memory only; mod=3 leaves the register unwritten (ucsim_provenance.md section 6)

  Routine `POP_RM` (work/v30-opcodes.md:395):
```
0058 SIGMA->tmpa; ALU INC2 tmpb
0059 SP->IND, SP->tmpb; CTL MEMR SS
005A SIGMA->SP; ALU PASS tmpa  [F]
005B SIGMA->IND; CTL [-06-]  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: 8F /0 with a register operand (64 forms) is in this class. Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `dfloor`=2, `grp_free`=3, `rfree`=3.

## 49. POP_PSW (`V35_CLS_POP_PSW`)

**Forms**: 1 enumerated, opcodes 9D. Examples: POPF [POP PSW] x1 (1 distinct names).

**V35 measured**:
- a6: `POP PSW [ram]` (POP PSW): V35 13.5 (even 13, odd 14); V30 9 (doc [8]); V35 - V30 = 4.5

**Model steps, register / no-memory form**: `POPF [POP PSW]` bytes 9d

```
('data', 'read', 0x800, 2, 7{setup})
('fetch_hold', 2{phold})
('clocks', 4{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 4 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `phold` | 2 | rows | LES/LDS, POP PSW: no fetch request for phold clocks from the last read's data [C:1436; T:1523-1524] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:91 `9D` POPF (POP PSW): measured 9 (J203); routine `POPF` V20UC.TXT L151-155 (ROM 0078-007B); toE/total(nb) 3 / 4 (4); flags F:007A / W:- / E:007A / R:-; FARJMP –; JMP –

  Routine `POPF` (work/v30-opcodes.md:472):
```
0078 SP->IND; CTL MEMR SS
0079 SP->tmpb; ALU INC2 tmpb
007A OPR->FLAGS  [FE]
007B SIGMA->SP
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `phold`=2, `setup_free`=3.

## 50. POP_R (`V35_CLS_POP_R`)

**Forms**: 1 enumerated, opcodes 61. Examples: POPA [POP R] x1 (1 distinct names).

**V35 measured**:
- RAMEN = 0 saves 18 (docs/v35s-eu-timing.md:257)
- a6: `POP R` (POP R): V35 74.5 (even 74, odd 75); V30 33 (doc [43]); V35 - V30 = 41.5

**Model steps, register / no-memory form**: `POPA [POP R]` bytes 61

```
('data', 'read', 0x800, 2, 7{setup})
('data', 'read', 0x802, 2, 7{wsetup})
('data', 'read', 0x804, 2, 7{wsetup})
('data', 'read', 0x806, 2, 7{wsetup})
('data', 'read', 0x808, 2, 7{wsetup})
('data', 'read', 0x80a, 2, 7{wsetup})
('data', 'read', 0x80c, 2, 7{wsetup})
('data', 'read', 0x80e, 2, 7{wsetup})
('clocks', 2{exec})
# step count changes with: pre, gap
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 2 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `gap` | 0 | table | push_r / pop_r burst: clocks between words [T:1384-1390] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `wsetup` | 7 | rows | second and later word's setup (push_r/pop_r burst words, call_far return offset, far returns' segment, LES/LDS segment word, RETI PS/PSW, INS write-back) [C:1429-1432; T:1384, 1491, 1518, 1564] |

**V30 counterpart**: 
- work/v30-opcodes.md:61 `61` POPA (POP R): measured 33 (J204,J205; M:153,304-308); routine `POPA_ENTRY` V20UC.TXT L736-740 (ROM 024C-024F); toE/total(nb) no E (exits via FARJMP) / 4 (4); flags F:024F / W:- / E:- / R:-; FARJMP POPA; JMP –; note: SP slot skipped in POPA (0250/0251: SIGMA->tmpb twice, no read)

  Routine `POPA_ENTRY` (work/v30-opcodes.md:1163):
```
024C SP->IND, SP->tmpb; CTL MEMR SS
024D ALU INC2 tmpb
024E SIGMA->tmpb, SIGMA->IND; CTL MEMR SS
024F OPR->DI; FARJMP POPA  [F]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `setup_free`=3.

## 51. POP_SEG (`V35_CLS_POP_SEG`)

**Forms**: 3 enumerated, opcodes 07, 17, 1F. Examples: POP ES x1; POP SS x1; POP DS x1 (3 distinct names).

**V35 measured**:
- a6: `POP DS0` (POP sreg): V35 12 (even 11, odd 13); V30 9 (doc [8]); V35 - V30 = 3
- a6: `POP DS1` (POP sreg): V35 12 (even 11, odd 13); V30 9 (doc [8]); V35 - V30 = 3

**Model steps, register / no-memory form**: `POP ES` bytes 07

```
('data', 'read', 0x800, 2, 7{setup})
('clocks', 3{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 3 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |

**V30 counterpart**: 
- work/v30-opcodes.md:27 `07` POP ES (POP DS1): measured 9 (J210); routine `POP_SREG` V20UC.TXT L11-15 (ROM 0008-000B); toE/total(nb) 4 / 4 (4); flags F:000B / W:- / E:000B / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:35 `17` POP SS: measured not measured (class 9, M:334); routine `POP_SREG` V20UC.TXT L11-15 (ROM 0008-000B); toE/total(nb) 4 / 4 (4); flags F:000B / W:- / E:000B / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:39 `1F` POP DS (POP DS0): measured 9 (J209); routine `POP_SREG` V20UC.TXT L11-15 (ROM 0008-000B); toE/total(nb) 4 / 4 (4); flags F:000B / W:- / E:000B / R:-; FARJMP –; JMP –

  Routine `POP_SREG` (work/v30-opcodes.md:220):
```
0008 SP->IND; CTL MEMR SS
0009 SP->tmpb; ALU INC2 tmpb
000A SIGMA->SP
000B OPR->R  [FE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `setup_free`=3.

## 52. PREFIX (`V35_CLS_PREFIX`)

**Forms**: 5 enumerated, opcodes 26, 2E, 36, 3E, F0. Examples: ES: x1; CS: x1; SS: x1; DS: x1; LOCK [BUSLOCK] x1 (5 distinct names).

**V35 measured**:
- segment prefix +2.5 each (mean of both placements); two prefixes +6 (docs/v35s-eu-timing.md:155)
- F3: +3 per prefix at 0 waits (docs/v35s-chains.md:180)

**Model steps, register / no-memory form**: `ES:` bytes 26

```
('clocks', 0)
('take', 0)
('clocks', 2{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 2 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |

**V30 counterpart**: 
- work/v30-opcodes.md:42 `26` ES: prefix (DS1:): measured prefix retires as own F pop, 2 clocks; DS1:+MOV AW,[BW] 13 total (J304); M:345-356; routine not in the sources V20UC.TXT – (ROM –); toE/total(nb) –; flags –; FARJMP –; JMP –; note: not in the sources (ROM): pla_3 1BL XOP 0000, hardware prefix latch
- work/v30-opcodes.md:46 `2E` CS: prefix (PS:): measured not measured (segment prefix class 2, M:345-356); routine not in the sources V20UC.TXT – (ROM –); toE/total(nb) –; flags –; FARJMP –; JMP –; note: not in the sources (ROM): pla_3 1BL XOP 0000
- work/v30-opcodes.md:50 `36` SS: prefix: measured SS:+MOV AW,[BW] 13 total (J305); M:345-356; routine not in the sources V20UC.TXT – (ROM –); toE/total(nb) –; flags –; FARJMP –; JMP –; note: not in the sources (ROM): pla_3 1BL XOP 0000
- work/v30-opcodes.md:54 `3E` DS: prefix (DS0:): measured DS0:+ADD BW,DW 5 (J301); DS0:+MOV AW,[BW] 13 (J302); stacked DS1:DS0: 16 (J303); M:345-356; routine not in the sources V20UC.TXT – (ROM –); toE/total(nb) –; flags –; FARJMP –; JMP –; note: not in the sources (ROM): pla_3 1BL XOP 0000
- work/v30-opcodes.md:142 `F0` LOCK (BUSLOCK): measured LOCK+NOP 5 (J300; M:353); routine not in the sources V20UC.TXT – (ROM –); toE/total(nb) –; flags –; FARJMP –; JMP –; note: not in the sources (ROM): pla_3 1BL XOP 1111

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: A prefix is a pseudo-instruction of its own in the model (templates.py:2-5); +2.5 per prefix measured.

## 53. PREPARE (`V35_CLS_PREPARE`)

**Forms**: 256 enumerated, opcodes C8. Examples: ENTER [PREPARE] x256 (1 distinct names).

**V35 measured**:
- PREPARE 8, L: 30, 40, 57, then +18 per level (docs/v35s-eu-timing.md:216)
- a6: `PREPARE 8, 0 [BP=0F20]` (PREPARE imm16,imm8): V35 30 (even 30, odd 30); V30 12 (doc [12]); V35 - V30 = 18

**Model steps, register / no-memory form**: `ENTER [PREPARE]` bytes c8000200

```
('data', 'write', 0x7fe, 2, 7{setup})
('clocks', 2{pre})
('take', 3)
('clocks', 11{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 11 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `pre` | 2 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:115 `C8` ENTER imm16,imm8 (PREPARE): measured imm8=0 12, =1 22, =2 30 (J211-J213; M:336); routine `ENTER_ENTRY` V20UC.TXT L761-765 (ROM 0260-0263); toE/total(nb) no E (exits via FARJMP) / 4 (4); flags F:0263 / W:- / E:- / R:-; FARJMP ENTER; JMP –

  Routine `ENTER_ENTRY` (work/v30-opcodes.md:1174):
```
0260 Q->tmpaL, SP->tmpb; ALU DEC2 tmpb
0261 Q->tmpaH, SIGMA->IND
0262 CTL MEMW SS
0263 BP->OPR; FARJMP ENTER  [F]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `setup_free`=3.

## 54. PUSH (`V35_CLS_PUSH`)

**Forms**: 9 enumerated, opcodes 50, 51, 52, 53, 54, 55, 56, 57, 9C. Examples: PUSH AX x1; PUSH CX x1; PUSH DX x1; PUSH BX x1; PUSH SP x1; PUSH BP x1; ... (9 distinct names).

**V35 measured**:
- PUSH reg (50+r) 9; (FF /6) 14 (docs/v35s-eu-timing.md:54)
- a6: `PUSH PSW` (PUSH PSW): V35 9 (even 8, odd 10); V30 9 (doc [8]); V35 - V30 = 0
- a6: `PUSH BW` (PUSH reg16): V35 9 (even 8, odd 10); V30 9 (doc [8]); V35 - V30 = 0
- a6: `PUSH BW [SP=0F01 SS=0000]` (PUSH reg16): V35 12 (even 11, odd 13); V30 13 (doc [12]); V35 - V30 = -1

**Model steps, register / no-memory form**: `PUSH AX` bytes 50

```
('data', 'write', 0x7fe, 2, 7{setup})
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |

**V30 counterpart**: 
- work/v30-opcodes.md:58 `50-57` PUSH r16: measured 9 (J220); odd anchor 10 (J221); SP odd 13 (J222); M:150; routine `PUSH_R16` V20UC.TXT L51-55 (ROM 0028-002B); toE/total(nb) 2 / 3 (3); flags F:- / W:- / E:0029 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:90 `9C` PUSHF (PUSH PSW): measured 9 (J214); routine `PUSHF` V20UC.TXT L146-150 (ROM 0074-0077); toE/total(nb) 2 / 3 (3); flags F:- / W:- / E:0075 / R:-; FARJMP –; JMP –

  Routine `PUSH_R16` (work/v30-opcodes.md:296):
```
0028 SP->tmpb; ALU DEC2 tmpb
0029 SIGMA->SP, SIGMA->IND; CTL MEMW SS  [E]
002A M->OPR
```

  Routine `PUSHF` (work/v30-opcodes.md:462):
```
0074 SP->tmpb; ALU DEC2 tmpb
0075 FLAGS->OPR, SIGMA->IND; CTL MEMW SS  [E]
0076 SIGMA->SP
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `setup_free`=3.

## 55. PUSH_IMM (`V35_CLS_PUSH_IMM`)

**Forms**: 512 enumerated, opcodes 68, 6A. Examples: PUSH imm16 x256; PUSH imm8 x256 (2 distinct names).

**V35 measured**:
- a6: `PUSH 0x1234` (PUSH imm16): V35 13 (even 12, odd 14); V30 10 (doc [8]); V35 - V30 = 3
- a6: `PUSH 0x12` (PUSH imm8): V35 12 (even 12, odd 12); V30 9 (doc [7]); V35 - V30 = 3

**Model steps, register / no-memory form**: `PUSH imm16` bytes 680002

```
('clocks', 3{pre})
('take', 2)
('data', 'write', 0x7fe, 2, 7{setup})
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `pre` | 3 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |

**V30 counterpart**: 
- work/v30-opcodes.md:67 `68` PUSH imm16: measured 10 (J217; M:151); routine `PUSH_IMM16` V20UC.TXT L811-815 (ROM 0288-028B); toE/total(nb) 4 / 4 (4); flags F:- / W:- / E:028B / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:69 `6A` PUSH imm8 (sign-extended): measured 9 (J218; M:151); routine `PUSH_IMM8` V20UC.TXT L806-810 (ROM 0284-0287); toE/total(nb) 3 / 4 (4); flags F:- / W:- / E:0286 / R:-; FARJMP –; JMP –

  Routine `PUSH_IMM16` (work/v30-opcodes.md:1226):
```
0288 Q->tmpaL, SP->tmpb; ALU DEC2 tmpb
0289 Q->tmpaH
028A tmpa->OPR, SIGMA->IND; CTL MEMW SS
028B SIGMA->SP  [E]
```

  Routine `PUSH_IMM8` (work/v30-opcodes.md:1215):
```
0284 Q->tmpa, SP->tmpb; ALU DEC2 tmpb
0285 SIGMA->SP, SIGMA->IND; CTL MEMW SS
0286 tmpa->tmpbL  [E]
0287 tmpb->OPR
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `setup_free`=3.

## 56. PUSH_MEM (`V35_CLS_PUSH_MEM`)

**Forms**: 32 enumerated, opcodes FF. Examples: PUSH rm16 (mem) x24; PUSH rm16 (reg) x8 (2 distinct names).

**V35 measured**:
- PUSH via FF /6 14 (register operand) (docs/v35s-eu-timing.md:54)
- a6: `PUSH word [BW] [BW=0800]` (PUSH mem16): V35 20 (even 20, odd 19); V30 21 (doc [18]); V35 - V30 = -1

**Model steps, register / no-memory form**: `PUSH rm16 (reg)` bytes fff0

```
('clocks', 0{pre})
('take', 1)
('clocks', 0, 'ea')
('data', 'read', None, 2, 0)
('data', 'write', 0x7fe, 2, 7{exec+setup})
('clocks', 0{post})
```

**Model steps, memory form**: `PUSH rm16 (mem)` bytes ff30, EA mode base_index (ea table `base_index`)

```
('clocks', 0{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 2, 4{grp}, 3{grp_free(in max/min)}, True)
('data', 'write', 0x7fe, 2, 7{exec+setup})
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `exec` | 6 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `grp` | 4 | rows | group memory form: the group setup clocks before the first data request (as EU clocks or extra setup per grp_mode) [T:1032-1041] |
| `grp_free` | 3 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 1 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |

**V30 counterpart**: 
- work/v30-opcodes.md:167 `FE/FF /6` PUSH r/m16: measured mem 21 (J219; M:333); reg form not measured; routine `FF_PUSH` V20UC.TXT L576-580 (ROM 01CC-01CF); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:01CE / R:-; FARJMP –; JMP –

  Routine `FF_PUSH` (work/v30-opcodes.md:1142):
```
01CC SP->tmpb; ALU DEC2 tmpb
01CD SIGMA->SP
01CE M->OPR, SIGMA->IND; CTL MEMW SS  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: FF /6 with a register operand (8 forms) is in this class with no memory operand. Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `dfloor`=2, `grp_free`=3.

## 57. PUSH_R (`V35_CLS_PUSH_R`)

**Forms**: 1 enumerated, opcodes 60. Examples: PUSHA [PUSH R] x1 (1 distinct names).

**V35 measured**:
- RAMEN = 0 saves 22.5 (writes cost 3 each with RAMEN = 1) (docs/v35s-eu-timing.md:257)
- a6: `PUSH R` (PUSH R): V35 74 (even 73, odd 75); V30 52 (doc [35]); V35 - V30 = 22

**Model steps, register / no-memory form**: `PUSHA [PUSH R]` bytes 60

```
('data', 'write', 0x7fe, 2, 9{setup})
('data', 'write', 0x7fc, 2, 7{wsetup})
('data', 'write', 0x7fa, 2, 7{wsetup})
('data', 'write', 0x7f8, 2, 7{wsetup})
('data', 'write', 0x7f6, 2, 7{wsetup})
('data', 'write', 0x7f4, 2, 7{wsetup})
('data', 'write', 0x7f2, 2, 7{wsetup})
('data', 'write', 0x7f0, 2, 7{wsetup})
('clocks', 0{post})
# step count changes with: pre, gap
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `gap` | 0 | table | push_r / pop_r burst: clocks between words [T:1384-1390] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 9 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 7 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `wsetup` | 7 | rows | second and later word's setup (push_r/pop_r burst words, call_far return offset, far returns' segment, LES/LDS segment word, RETI PS/PSW, INS write-back) [C:1429-1432; T:1384, 1491, 1518, 1564] |

**V30 counterpart**: 
- work/v30-opcodes.md:60 `60` PUSHA (PUSH R): measured 52 (J215,J216; M:152,297-303); routine `PUSHA_ENTRY` V20UC.TXT L711-715 (ROM 0238-023B); toE/total(nb) no E (exits via FARJMP) / 4 (4); flags F:0239,023B / W:- / E:- / R:-; FARJMP PUSHA; JMP –

  Routine `PUSHA_ENTRY` (work/v30-opcodes.md:1152):
```
0238 SP->tmpb; ALU DEC2 tmpb
0239 AX->OPR, SIGMA->IND  [F]
023A SIGMA->tmpb; CTL MEMW SS
023B CX->OPR; FARJMP PUSHA  [F]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `setup_free`=7.

## 58. PUSH_SEG (`V35_CLS_PUSH_SEG`)

**Forms**: 4 enumerated, opcodes 06, 0E, 16, 1E. Examples: PUSH ES x1; PUSH CS x1; PUSH SS x1; PUSH DS x1 (4 distinct names).

**V35 measured**:
- a6: `PUSH DS0` (PUSH sreg): V35 10 (even 9, odd 11); V30 9 (doc [8]); V35 - V30 = 1
- a6: `PUSH PS` (PUSH sreg): V35 10 (even 9, odd 11); V30 9 (doc [8]); V35 - V30 = 1

**Model steps, register / no-memory form**: `PUSH ES` bytes 06

```
('data', 'write', 0x7fe, 2, 8{setup})
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `setup` | 8 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 4 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |

**V30 counterpart**: 
- work/v30-opcodes.md:26 `06` PUSH ES (PUSH DS1): measured not measured (PUSH sreg class 9: J223,J224; M:334); routine `PUSH_SREG` V20UC.TXT L16-20 (ROM 000C-000F); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:000E / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:30 `0E` PUSH CS (PUSH PS): measured 9 (J224); routine `PUSH_SREG` V20UC.TXT L16-20 (ROM 000C-000F); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:000E / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:34 `16` PUSH SS: measured not measured (class 9, M:334); routine `PUSH_SREG` V20UC.TXT L16-20 (ROM 000C-000F); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:000E / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:38 `1E` PUSH DS (PUSH DS0): measured 9 (J223); routine `PUSH_SREG` V20UC.TXT L16-20 (ROM 000C-000F); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:000E / R:-; FARJMP –; JMP –

  Routine `PUSH_SREG` (work/v30-opcodes.md:231):
```
000C SP->tmpb; ALU DEC2 tmpb
000D R->OPR, SIGMA->IND; CTL MEMW SS
000E SIGMA->SP  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `setup_free`=4.

## 59. REG (`V35_CLS_REG`)

**Forms**: 2568 enumerated, opcodes 00, 01, 02, 03, 08, 09, 0A, 0B, 10, 11, 12, 13, 18, 19, 1A, 1B, 20, 21, 22, 23, 28, 29, 2A, 2B, 30, 31, 32, 33, 38, 39, 3A, 3B, 86, 87, 88, 89, 8A, 8B, 8C, 8E .... Examples: ADD rm8,r8 (reg) x64; ADD rm16,r16 (reg) x64; ADD r8,rm8 (reg) x64; ADD r16,rm16 (reg) x64; OR rm8,r8 (reg) x64; OR rm16,r16 (reg) x64; ... (48 distinct names).

**V35 measured**:
- MOV, ADD, CMP, XCH reg,reg: 3 for any pair, byte or word (docs/v35s-eu-timing.md:62)
- MOV to / from a segment register: 3 (docs/v35s-eu-timing.md:64)
- XCH AW,reg (90+r) 4; (87) 3 (docs/v35s-eu-timing.md:56)
- NOP 4 (docs/v35s-eu-timing.md:15)
- F3: NOP, XCH AW,DW 4 per instruction; MOV/ADD AW,DW 3 (k=1), 9 (k=2) (docs/v35s-chains.md:172)
- a6: `ADD BL, DL` (ADD reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6: `ADD BW, DW` (ADD reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6: `ADD DW, CW` (ADD reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6: `ADDC BW, DW` (ADDC reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6: `AND BW, DW` (AND reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6: `CMP BW, DW` (CMP reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6: `MOV BL, DL` (MOV reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6: `MOV BW, DW` (MOV reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6: `MOV DL, CL` (MOV reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6: `MOV CW, SS` (MOV reg16,sreg): V35 3 (even 3, odd 3); V30 2 (doc [2]); V35 - V30 = 1
- a6: `MOV DW, DS0` (MOV reg16,sreg): V35 3 (even 3, odd 3); V30 2 (doc [2]); V35 - V30 = 1
- a6: `MOV DS1, DW` (MOV sreg,reg16): V35 3 (even 3, odd 3); V30 2 (doc [2]); V35 - V30 = 1
- a6: `NOP` (NOP (no operand)): V35 4 (even 3, odd 5); V30 3 (doc [3]); V35 - V30 = 1
- a6: `OR BW, DW` (OR reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6: `SUB BW, DW` (SUB reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6: `SUBC BW, DW` (SUBC reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6: `XCH AW, BW` (XCH AW,reg16 / XCH reg16,AW): V35 4 (even 3, odd 5); V30 3 (doc [3]); V35 - V30 = 1
- a6: `XCH BW, DW` (XCH reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [3]); V35 - V30 = 0
- a6: `XOR BL, DL` (XOR reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6: `XOR BW, DW` (XOR reg,reg): V35 3 (even 3, odd 3); V30 3 (doc [2]); V35 - V30 = 0
- a6 (with prefix): `BUSLOCK NOP`: V35 7, V30 5
- a6 (with prefix): `DS0: ADD BW,DW (no mem ref)`: V35 5.5, V30 5

**Model steps, register / no-memory form**: `ADD rm8,r8 (reg)` bytes 00c0

```
('clocks', 0{pre})
('take', 1)
('clocks', 0{exec})
```

**Model steps, form without operand bytes**: `NOP` bytes 90

```
('clocks', 4{pre0})
('take', 0)
('clocks', 0{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 4 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |

**V30 counterpart**: 
- work/v30-opcodes.md:24 `00-03` ADD r/m,r / r,r/m (NEC ADD): measured reg,reg 3 (J11,J12); reg,mem 13 (J7,J8); odd-anchor reg,mem 12 (J9); mem,reg RMW 19 (J3); odd RMW 27 (J4); classes M:136,139,144; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:28 `08-0B` OR r/m,r / r,r/m (OR): measured reg,reg 3 (J198); mem forms not measured (class: load 13 M:139, RMW 19 M:144); routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:32 `10-13` ADC (NEC ADDC): measured reg,reg 3 (J19); mem forms not measured; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:36 `18-1B` SBB (NEC SUBC): measured reg,reg 3 (J277); mem forms not measured; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:40 `20-23` AND (AND): measured reg,reg 3 (J28); reg,mem 13 (J27); RMW not measured; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:44 `28-2B` SUB (SUB): measured reg,reg 3 (J274); reg,mem 13 (J273); RMW not measured; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:48 `30-33` XOR (XOR): measured reg,reg 3 (J298,J299); mem,reg RMW 19 (J296); routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:52 `38-3B` CMP (CMP): measured reg,reg 3 (J70); mem,reg 13 (J67); reg,mem 13 (J69) - no writeback; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- ... 6 more rows: `86/87`, `88-8B`, `8C`, `8E`, `90`, `91-97`

  Routine `ALU_RM` (work/v30-opcodes.md:200):
```
0000 M->tmpb, R->tmpa; ALU OPC tmpa
0001 SIGMA->M; CTL [-06-]  [WE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1.

## 60. RET (`V35_CLS_RET`)

**Forms**: 1 enumerated, opcodes C3. Examples: RET x1 (1 distinct names).

**V35 measured**:
- a6: `RET` (RET (no operand)): V35 28 (even 28, odd -); V30 16 (doc [15]); V35 - V30 = 12

**Model steps, register / no-memory form**: `RET` bytes c3

```
('clocks', 0{pre})
('data', 'read', 0x800, 2, 7{setup})
('clocks', 8{exec})
('flush', 16)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 8 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 6 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |

**V30 counterpart**: 
- work/v30-opcodes.md:111 `C3` RET: measured 16 (J225; M:196); routine `RET` V20UC.TXT L301-305 (ROM 00F0-00F3); toE/total(nb) 4 / 4 (4); flags F:00F3 / W:- / E:00F3 / R:-; FARJMP –; JMP –

  Routine `RET` (work/v30-opcodes.md:713):
```
00F0 SP->IND, SP->tmpa; CTL SUSP MEMR SS
00F1 ALU INC2 tmpa
00F2 SIGMA->SP
00F3 OPR->PC; CTL FLUSH  [FE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=6, `fgap`=5, `setup_free`=3.

## 61. RET_FAR (`V35_CLS_RET_FAR`)

**Forms**: 1 enumerated, opcodes CB. Examples: RETF x1 (1 distinct names).

**V35 measured**: not in the sources (no eu-timing row, no a6 form).

**Model steps, register / no-memory form**: `RETF` bytes cb

```
('clocks', 0{pre})
('data', 'read', 0x800, 2, 7{setup})
('data', 'read', 0x802, 2, 7{wsetup}, 7{wsetup})
('clocks', 8{exec})
('flush', 16)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 8 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 6 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `wsetup` | 7 | rows | second and later word's setup (push_r/pop_r burst words, call_far return offset, far returns' segment, LES/LDS segment word, RETI PS/PSW, INS write-back) [C:1429-1432; T:1384, 1491, 1518, 1564] |

**V30 counterpart**: 
- work/v30-opcodes.md:118 `CB` RETF: measured not measured; routine `RETF_` V20UC.TXT L306-310 (ROM 00F4-00F7); toE/total(nb) no E (exits via FARJMP) / 4 (4); flags F:- / W:- / E:- / R:-; FARJMP RETF; JMP –

  Routine `RETF_` (work/v30-opcodes.md:724):
```
00F4 SP->IND, SP->tmpa; CTL SUSP MEMR SS
00F5 ZEROS->tmpb; ALU INC2 tmpa
00F6 SIGMA->IND, SIGMA->tmpa; CTL MEMR SS
00F7 SIGMA->tmpa; FARJMP RETF
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=6, `fgap`=5, `setup_free`=3.

## 62. RET_FAR_IMM (`V35_CLS_RET_FAR_IMM`)

**Forms**: 256 enumerated, opcodes CA. Examples: RETF imm16 x256 (1 distinct names).

**V35 measured**: not in the sources (no eu-timing row, no a6 form).

**Model steps, register / no-memory form**: `RETF imm16` bytes ca0002

```
('clocks', 0{pre})
('post', 'read', 0x800, 2, 7{setup})
('issued')
('take', 2, 'chain')
('fetch_release', None)
('wait')
('data', 'read', 0x802, 2, 8{wsetup}, 8{wsetup})
('fetch_release', 0)
('flush_from', 1)
('clocks', 8{exec})
('flush', 16)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 8 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 6 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `mhold` | 6 | rows | ret_imm / ret_far_imm / mul_imm: a half-taken immediate word holds fetch requests mhold clocks [C:1338-1340, 1435-1436; T:1502-1504, 1674] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `wsetup` | 8 | rows | second and later word's setup (push_r/pop_r burst words, call_far return offset, far returns' segment, LES/LDS segment word, RETI PS/PSW, INS write-back) [C:1429-1432; T:1384, 1491, 1518, 1564] |

**V30 counterpart**: 
- work/v30-opcodes.md:117 `CA` RETF imm16: measured not measured; routine `RETF_IMM` V20UC.TXT L286-290, L296-300 (ROM 00E4-00E7, 00EC-00EF); toE/total(nb) no E (exits via FARJMP) / 6 (5); flags F:- / W:- / E:- / R:-; FARJMP RETF; JMP –

  Routine `RETF_IMM` (work/v30-opcodes.md:700):
```
00E4 Q->tmpbL
00E5 Q->tmpbH; ALU INC2 tmpa
00E6 SP->IND, SP->tmpa; CTL SUSP MEMR SS
00E7 —
00EC SIGMA->IND, SIGMA->tmpa; CTL MEMR SS
00ED SIGMA->tmpa; FARJMP RETF
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=6, `fgap`=5, `mhold`=6, `setup_free`=3.

## 63. RET_IMM (`V35_CLS_RET_IMM`)

**Forms**: 256 enumerated, opcodes C2. Examples: RET imm16 x256 (1 distinct names).

**V35 measured**:
- a6: `RET 4` (RET pop-value): V35 30 (even 30, odd -); V30 17 (doc [20]); V35 - V30 = 13

**Model steps, register / no-memory form**: `RET imm16` bytes c20002

```
('clocks', 0{pre})
('post', 'read', 0x800, 2, 8{setup})
('issued')
('take', 2, 'chain')
('wait')
('clocks', 8{exec})
('flush', 16)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 8 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 13 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `mhold` | 6 | rows | ret_imm / ret_far_imm / mul_imm: a half-taken immediate word holds fetch requests mhold clocks [C:1338-1340, 1435-1436; T:1502-1504, 1674] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 8 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 4 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |

**V30 counterpart**: 
- work/v30-opcodes.md:110 `C2` RET imm16 (RET pop-value): measured 17 (J226; M:197); routine `RET_IMM` V20UC.TXT L286-290, L291-295 (ROM 00E4-00E7, 00E8-00EB); toE/total(nb) 7 / 7 (6); flags F:00EA / W:- / E:00EA / R:-; FARJMP –; JMP –

  Routine `RET_IMM` (work/v30-opcodes.md:686):
```
00E4 Q->tmpbL
00E5 Q->tmpbH; ALU INC2 tmpa
00E6 SP->IND, SP->tmpa; CTL SUSP MEMR SS
00E7 —
00E8 SIGMA->tmpa; ALU ADD tmpa
00E9 SIGMA->SP
00EA OPR->PC; CTL FLUSH  [FE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=13, `fgap`=5, `mhold`=6, `setup_free`=4.

## 64. RETI (`V35_CLS_RETI`)

**Forms**: 1 enumerated, opcodes CF. Examples: IRET [RETI] x1 (1 distinct names).

**V35 measured**:
- a6: `RETI` (RETI (no operand)): V35 52 (even 52, odd -); V30 22 (doc [27]); V35 - V30 = 30

**Model steps, register / no-memory form**: `IRET [RETI]` bytes cf

```
('clocks', 0{pre})
('data', 'read', 0x800, 2, 7{setup})
('data', 'read', 0x802, 2, 7{wsetup}, 7{wsetup})
('data', 'read', 0x804, 2, 7{wsetup}, 7{wsetup})
('clocks', 14{exec})
('flush', 16)
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 14 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `fgap` | 5 | table | flush_inflight=wait: the flush waits until no fetch is in flight and fgap clocks have passed since the last fetch's last clock [C:1407-1409; E:1331-1361] |
| `hold` | 6 | table | flush_hold=start: no fetch request from hold clocks after a taken transfer's start to its flush [C:1414-1415; E:526-530] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `wsetup` | 7 | rows | second and later word's setup (push_r/pop_r burst words, call_far return offset, far returns' segment, LES/LDS segment word, RETI PS/PSW, INS write-back) [C:1429-1432; T:1384, 1491, 1518, 1564] |

**V30 counterpart**: 
- work/v30-opcodes.md:122 `CF` IRET (RETI): measured 22 (J227; M:340); routine `IRET_` V20UC.TXT L341-345 (ROM 0110-0113); toE/total(nb) no E (exits via FARJMP) / 2 (2); flags F:- / W:- / E:- / R:-; FARJMP IRET; JMP –

  Routine `IRET_` (work/v30-opcodes.md:793):
```
0110 SP->IND, SP->tmpa; CTL SUSP MEMR SS
0111 FARJMP IRET
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `hold`=6, `fgap`=5, `setup_free`=3.

## 65. RMW (`V35_CLS_RMW`)

**Forms**: 4576 enumerated, opcodes 00, 01, 08, 09, 10, 11, 18, 19, 20, 21, 28, 29, 30, 31, 38, 39, 86, 87, D0, D1, D2, D3, F6, F7, FE, FF. Examples: ADD rm8,r8 (mem) x192; ADD rm16,r16 (mem) x192; OR rm8,r8 (mem) x192; OR rm16,r16 (mem) x192; ADC rm8,r8 (mem) x192; ADC rm16,r16 (mem) x192; ... (72 distinct names).

**V35 measured**:
- ADD mem,reg 13 (+EA: 0 / +1 / +2, lines 145-147) (docs/v35s-eu-timing.md:149)
- odd-address word RMW +6 (docs/v35s-eu-timing.md:152)
- register NOT / NEG (group 3 register forms) 6 (docs/v35s-eu-timing.md:66)
- memory word shift: 21.5 + 2n (imm8), 23 + 2n (CL) (docs/v35s-eu-timing.md:196)
- memory shifts read and write the operand once, 2 per count (docs/v35s-eu-timing.md:114)
- a6: `ADD [BW], DW [BW=0800]` (ADD mem,reg): V35 13 (even 13, odd 13); V30 19 (doc [16]); V35 - V30 = -6
- a6: `ADD [BW], DW [BW=0801 DS0=0000 IX=0010]` (ADD mem,reg): V35 19 (even 19, odd 19); V30 27 (doc [24]); V35 - V30 = -8
- a6: `CMP [BW], DW [BW=0800]` (CMP mem,reg): V35 12 (even 12, odd 13); V30 13 (doc [11]); V35 - V30 = -1
- a6: `DEC word [BW] [BW=0800]` (DEC mem): V35 16 (even 16, odd 16); V30 20 (doc [16]); V35 - V30 = -4
- a6: `INC word [BW] [BW=0800]` (INC mem): V35 16 (even 16, odd 16); V30 20 (doc [16]); V35 - V30 = -4
- a6: `INC word [BW] [BW=0801 DS0=0000 IX=0010]` (INC mem): V35 22 (even 22, odd 22); V30 28 (doc [24]); V35 - V30 = -6
- a6: `NEG word [BW] [BW=0800]` (NEG mem): V35 16 (even 16, odd 16); V30 20 (doc [16]); V35 - V30 = -4
- a6: `NEG AW` (NEG reg): V35 6 (even 6, odd 6); V30 4 (doc [2]); V35 - V30 = 2
- a6: `NOT AW` (NOT reg): V35 6 (even 6, odd 6); V30 4 (doc [2]); V35 - V30 = 2
- a6: `NOT DL` (NOT reg): V35 6 (even 6, odd 6); V30 4 (doc [2]); V35 - V30 = 2
- a6: `ROR word [BW], 1 [BW=0800]` (ROR mem,1): V35 22 (even 22, odd 21); V30 22 (doc [16]); V35 - V30 = 0
- a6: `ROR word [BW], CL [BW=0800 CW=0004]` (ROR mem,CL): V35 31 (even 31, odd 31); V30 29 (doc [23]); V35 - V30 = 2
- a6: `SHL word [BW], 1 [BW=0800]` (SHL mem,1): V35 22 (even 22, odd 21); V30 22 (doc [16]); V35 - V30 = 0
- a6: `SHL word [BW], 1 [BW=0801 DS0=0000 IX=0010]` (SHL mem,1): V35 28 (even 28, odd 27); V30 30 (doc [24]); V35 - V30 = -2
- a6: `SHL byte [BW], CL [BW=0800 CW=0004]` (SHL mem,CL): V35 31 (even 31, odd 31); V30 29 (doc [23]); V35 - V30 = 2
- a6: `SHL word [BW], CL [BW=0800 CW=0001]` (SHL mem,CL): V35 25 (even 25, odd 25); V30 26 (doc [20]); V35 - V30 = -1
- a6: `SHL word [BW], CL [BW=0800 CW=0004]` (SHL mem,CL): V35 31 (even 31, odd 31); V30 29 (doc [23]); V35 - V30 = 2
- a6: `XCH [BW], DW [BW=0800]` (XCH mem,reg / XCH reg,mem): V35 15 (even 15, odd 15); V30 19 (doc [16]); V35 - V30 = -4
- a6: `XCH [BW], DW [BW=0801 DS0=0000 IX=0010]` (XCH mem,reg / XCH reg,mem): V35 21 (even 21, odd 21); V30 27 (doc [24]); V35 - V30 = -6
- a6: `XOR [BW], DW [BW=0800]` (XOR mem,reg): V35 13 (even 13, odd 13); V30 19 (doc [16]); V35 - V30 = -6

**Model steps, register / no-memory form**: `NOT rm8 (reg)` bytes f6d0

```
('clocks', 0{pre})
('take', 1)
('clocks', 0, 'ea')
('data', 'read', None, 1, 0)
('clocks', 0)
('data', 'write', None, 1, 3{alu+setup(in max/min)})
('clocks', 0{post})
```

**Model steps, memory form**: `ADD rm8,r8 (mem)` bytes 0000, EA mode base_index (ea table `base_index`)

```
('clocks', 0{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 1, 0)
('clocks', 0)
('data', 'write', 0x300, 1, 3{alu+setup(in max/min)})
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `alu` | 3 | rows | rmw / rmw_imm / 0F rmw forms: clocks between the read data and the write's post (ALU step); with rmw_write_issue=immediate the write is posted at the ALU step's start with max(alu, setup) setup [T:1253-1305, 1773] |
| `dclk` | 2 | table | dest_route: clocks a form spends routing its result to the operand its direction bit does not name [T:1143-1158] |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `grp` | 4 | rows | group memory form: the group setup clocks before the first data request (as EU clocks or extra setup per grp_mode) [T:1032-1041] |
| `grp_free` | 3 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `grpcl` | 3 | table | memory shift by CL (D2/D3, shift_cl_mem=count): more group-setup clocks before the read, all fetch-free [T:1045-1048] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 0 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `sidle` | 2 | table | slot_idle=eu: clocks from a left-out write's slot that runs no fetch to the clock the EU goes on [C:1381-1384; E:1984-1987] |

**V30 counterpart**: 
- work/v30-opcodes.md:24 `00-03` ADD r/m,r / r,r/m (NEC ADD): measured reg,reg 3 (J11,J12); reg,mem 13 (J7,J8); odd-anchor reg,mem 12 (J9); mem,reg RMW 19 (J3); odd RMW 27 (J4); classes M:136,139,144; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:28 `08-0B` OR r/m,r / r,r/m (OR): measured reg,reg 3 (J198); mem forms not measured (class: load 13 M:139, RMW 19 M:144); routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:32 `10-13` ADC (NEC ADDC): measured reg,reg 3 (J19); mem forms not measured; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:36 `18-1B` SBB (NEC SUBC): measured reg,reg 3 (J277); mem forms not measured; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:40 `20-23` AND (AND): measured reg,reg 3 (J28); reg,mem 13 (J27); RMW not measured; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:44 `28-2B` SUB (SUB): measured reg,reg 3 (J274); reg,mem 13 (J273); RMW not measured; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:48 `30-33` XOR (XOR): measured reg,reg 3 (J298,J299); mem,reg RMW 19 (J296); routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- work/v30-opcodes.md:52 `38-3B` CMP (CMP): measured reg,reg 3 (J70); mem,reg 13 (J67); reg,mem 13 (J69) - no writeback; routine `ALU_RM` V20UC.TXT L1-5 (ROM 0000-0003); toE/total(nb) 2 / 2 (2); flags F:- / W:0001 / E:0001 / R:-; FARJMP –; JMP –; note: reg and memory forms share the routine; memory operand pre-read by decode hardware (M), memory result written by the [-06-] strobe at 0001 (CMP: write suppressed)
- ... 11 more rows: `86/87`, `D0/D1 /0-/7`, `D2/D3 /0-/7`, `F6/F7 /0,/1`, `F6/F7 /2`, `F6/F7 /3`, `FE/FF /0`, `FE/FF /1`, `FE/FF /3`, `FE/FF /5`, `FE/FF /7`

  Routine `ALU_RM` (work/v30-opcodes.md:200):
```
0000 M->tmpb, R->tmpa; ALU OPC tmpa
0001 SIGMA->M; CTL [-06-]  [WE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: The class also holds 88 register forms (F6/F7 /1 /2 /3, FE/FF /0 /1, FF /3 /5 /7 register: NOT, NEG, INC/DEC via ModR/M ...): their printed template posts a read and a write with address None (the register operand); the sources do not say which machine step the 6-clock register RMW (eu-timing.md:66, "the extra clocks belong to the unary micro-routine") spends, and eu._post (eu.py:1913-1918) computes `addr & 1`, so how the EU runs a None address is not settled here. Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `dfloor`=2, `sidle`=2, `setup_free`=3, `grp_free`=3, `dclk`=2.

## 66. RMW_IMM (`V35_CLS_RMW_IMM`)

**Forms**: 1176 enumerated, opcodes 80, 81, 82, 83, C0, C1, F7. Examples: ADD rm8,imm8 (mem) x48; OR rm8,imm8 (mem) x48; ADC rm8,imm8 (mem) x48; SBB rm8,imm8 (mem) x48; AND rm8,imm8 (mem) x48; SUB rm8,imm8 (mem) x48; ... (41 distinct names).

**V35 measured**:
- TEST reg,imm via F6 / F7: 8.5 / 10 (docs/v35s-eu-timing.md:60)
- memory word shift by imm8: 21.5 + 2n (docs/v35s-eu-timing.md:196)
- a6: `ADD word [BW], 0x11 [BW=0800]` (ADD mem,imm): V35 14.5 (even 13, odd 16); V30 22 (doc [18]); V35 - V30 = -7.5
- a6: `CMP word [BW], 0x11 [BW=0800]` (CMP mem,imm): V35 14.5 (even 13, odd 16); V30 16 (doc [13]); V35 - V30 = -1.5

**Model steps, memory form**: `ADD rm8,imm8 (mem)` bytes 800002, EA mode base_index (ea table `base_index`)

```
('clocks', 0{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('post', 'read', 0x300, 1, 2{grp1}, 1{grp_free(in max/min)}, True)
('issued')
('take', 1, 'chain')
('wait')
('clocks', 0)
('clocks', 0)
('data', 'write', 0x300, 1, 3{alu+setup(in max/min)})
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `alu` | 3 | rows | rmw / rmw_imm / 0F rmw forms: clocks between the read data and the write's post (ALU step); with rmw_write_issue=immediate the write is posted at the ALU step's start with max(alu, setup) setup [T:1253-1305, 1773] |
| `dadd` | 1 | rows | mem_order=split: EU clocks after a displacement's take (store_imm) [C:1316-1318; T:982-985] |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `grp` | 3 | rows | group memory form: the group setup clocks before the first data request (as EU clocks or extra setup per grp_mode) [T:1032-1041] |
| `grp1` | 2 | rows | grp for a group form with a one-byte immediate (83 /x, imm8_grp=own) [T:1042-1043] |
| `grp_free` | 1 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `istart` | 5 | table | imm_count=start: the first data request of a memory form with an immediate issues no earlier than istart + imm bytes clocks after the start [E:435-439] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 0 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 0 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `sexec` | 3 | rows | mul/div: the signed register form's exec (F7 /5, /7); rmw_imm: extra clocks of the memory shift by imm8's ALU step [C:1356-1357, 1375-1380; T:1227, 1259] |
| `sidle` | 2 | table | slot_idle=eu: clocks from a left-out write's slot that runs no fetch to the clock the EU goes on [C:1381-1384; E:1984-1987] |
| `sthru` | 2 | rows | rmw_imm memory shift by imm8: the first sthru setup clocks of the write count through a fetch in flight [C:1378-1380; T:1265-1271] |

**V30 counterpart**: 
- work/v30-opcodes.md:76 `80-83 /0-/7` group 1 r/m,imm: /0 ADD /1 OR /2 ADC /3 SBB /4 AND /5 SUB /6 XOR /7 CMP (82 = 80 alias): measured reg: ADD 6 (J5 81/0, J6 83/0), XOR 6 (J297 81/6), CMP 6 (J68 83/7); mem: ADD word 22 (J2 83/0), CMP word 16 (J66 83/7); M:137,145; other reg values not measured; routine `GRP1` V20UC.TXT L76-80, L81-85 (ROM 003C-003F, 0040-0043); toE/total(nb) 5 / 5 (5); flags F:- / W:0040 / E:0040 / R:-; FARJMP –; JMP 003C JMP OP8 2 ->003E; note: one routine for all eight reg values (ALU OPC selects the op from the reg field); 003C JMP OP8 skips the imm high byte for 80/82/83; 83 sign-extension is not visible in the ROM
- work/v30-opcodes.md:109 `C0/C1 /0-/7` shift r/m,imm8: /0 ROL /1 ROR /2 RCL /3 RCR /4 SHL /5 SHR /6 (undefined, ALU op [-0E-]) /7 SAR: measured reg: ROR AW,4 14 (J236), SHL AW,4 14 (J264), class 10+n (M:147); mem not measured; routine `SHIFT_IMM` V20UC.TXT L816-820 (ROM 028C-028F); toE/total(nb) no E (exits via FARJMP) / 4 (4); flags F:- / W:- / E:- / R:-; FARJMP SHIFT; JMP –; note: one routine for all reg values; count from Q (imm8); loop in SHIFT
- work/v30-opcodes.md:148 `F6/F7 /0,/1` TEST r/m,imm (/1 undocumented alias): measured not measured; routine `F6_TEST` V20UC.TXT L456-460 (ROM 016C-016F); toE/total(nb) 3 / 4 (4); flags F:- / W:016F / E:016E / R:-; FARJMP –; JMP 016C JMP OP8 2 ->016E

  Routine `GRP1` (work/v30-opcodes.md:338):
```
003C Q->tmpbL; JMP OP8 2 ->003E
003D Q->tmpbH
003E tmpb->tmpa; ALU OPC tmpa
003F M->tmpb
0040 SIGMA->M; CTL [-06-]  [WE]
```

  Routine `SHIFT_IMM` (work/v30-opcodes.md:1237):
```
028C Q->tmpaL; ALU PASS tmpa
028D M->tmpb
028E tmpa->COUNT, SIGMA->[-03-]; ALU PASS tmpb
028F FARJMP SHIFT
```

  Routine `F6_TEST` (work/v30-opcodes.md:1001):
```
016C Q->tmpbL; JMP OP8 2 ->016E
016D Q->tmpbH
016E M->tmpa; ALU AND tmpa  [E]
016F SIGMA->NULL  [W]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `dfloor`=2, `istart`=5, `sidle`=2, `grp_free`=1, `sthru`=2, `dadd`=1.

## 67. ROL4 (`V35_CLS_ROL4`)

**Forms**: 64 enumerated, opcodes 0F 28. Examples: ROL4 (reg) x64 (1 distinct names).

**V35 measured**:
- ROL4 reg 18.5 (docs/v35s-eu-timing.md:220)
- a6: `ROL4 AL [AW=0005]` (ROL4 reg8): V35 18.5 (even 18, odd 19); V30 16 (doc [25]); V35 - V30 = 2.5

**Model steps, register / no-memory form**: `ROL4 (reg)` bytes 0f28c0

```
('take', 1, 'chain')
('clocks', 1{pre})
('take', 1)
('clocks', 13{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 13 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 1 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:182 `0F 28` ROL4 r/m8: measured reg 16 (J231); mem 27 (J230); M:328-329; routine `ROL4` V20UC.TXT L936-940, L941-945, L946-950 (ROM 02EC-02EF, 02F0-02F3, 02F4-02F7); toE/total(nb) 9 / 10 (10); flags F:- / W:- / E:02F4 / R:02EF; FARJMP –; JMP –

  Routine `ROL4` (work/v30-opcodes.md:1516):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2.

## 68. ROL4_MEM (`V35_CLS_ROL4_MEM`)

**Forms**: 192 enumerated, opcodes 0F 28. Examples: ROL4 (mem) x192 (1 distinct names).

**V35 measured**:
- ROL4 mem 24.5 (docs/v35s-eu-timing.md:221)
- a6: `ROL4 byte [BW] [AW=0005 BW=0800]` (ROL4 mem8): V35 24.5 (even 24, odd 25); V30 27 (doc [28]); V35 - V30 = -2.5

**Model steps, memory form**: `ROL4 (mem)` bytes 0f2800, EA mode base_index (ea table `base_index`)

```
('take', 1, 'chain')
('clocks', 1{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 1, 3{fsetup}, 3{fsetup})
('clocks', 0)
('data', 'write', 0x300, 1, 12{alu+setup(in max/min)})
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `alu` | 12 | rows | rmw / rmw_imm / 0F rmw forms: clocks between the read data and the write's post (ALU step); with rmw_write_issue=immediate the write is posted at the ALU step's start with max(alu, setup) setup [T:1253-1305, 1773] |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `fsetup` | 3 | table | 0F memory forms (page_mem=fixed) / bit fields (bf_read=fixed): the read's fetch-free setup counted back from its post [C:1335-1337; T:1655-1660, 1712-1715] |
| `grp_free` | 0 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `nx` | 7 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 1 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 0 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `sidle` | 2 | table | slot_idle=eu: clocks from a left-out write's slot that runs no fetch to the clock the EU goes on [C:1381-1384; E:1984-1987] |
| `wb` | 0 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:182 `0F 28` ROL4 r/m8: measured reg 16 (J231); mem 27 (J230); M:328-329; routine `ROL4` V20UC.TXT L936-940, L941-945, L946-950 (ROM 02EC-02EF, 02F0-02F3, 02F4-02F7); toE/total(nb) 9 / 10 (10); flags F:- / W:- / E:02F4 / R:02EF; FARJMP –; JMP –

  Routine `ROL4` (work/v30-opcodes.md:1516):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=7, `dfloor`=2, `sidle`=2, `setup_free`=3, `fsetup`=3.

## 69. ROR4 (`V35_CLS_ROR4`)

**Forms**: 64 enumerated, opcodes 0F 2A. Examples: ROR4 (reg) x64 (1 distinct names).

**V35 measured**:
- ROR4 reg 22.5 (docs/v35s-eu-timing.md:220)
- a6: `ROR4 AL [AW=0005]` (ROR4 reg8): V35 22.5 (even 22, odd 23); V30 20 (doc [29]); V35 - V30 = 2.5

**Model steps, register / no-memory form**: `ROR4 (reg)` bytes 0f2ac0

```
('take', 1, 'chain')
('clocks', 1{pre})
('take', 1)
('clocks', 17{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 17 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 1 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:183 `0F 2A` ROR4 r/m8: measured reg 20 (J238); mem 31 (J237); M:328-329; routine `ROR4` V20UC.TXT L951-955, L941-945, L946-950 (ROM 02F8-02FB, 02F0-02F3, 02F4-02F7); toE/total(nb) 9 / 10 (10); flags F:- / W:- / E:02F4 / R:02FB; FARJMP –; JMP –

  Routine `ROR4` (work/v30-opcodes.md:1533):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2.

## 70. ROR4_MEM (`V35_CLS_ROR4_MEM`)

**Forms**: 192 enumerated, opcodes 0F 2A. Examples: ROR4 (mem) x192 (1 distinct names).

**V35 measured**:
- a6: `ROR4 byte [BW] [AW=0005 BW=0800]` (ROR4 mem8): V35 28.5 (even 28, odd 29); V30 31 (doc [33]); V35 - V30 = -2.5

**Model steps, memory form**: `ROR4 (mem)` bytes 0f2a00, EA mode base_index (ea table `base_index`)

```
('take', 1, 'chain')
('clocks', 1{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'read', 0x300, 1, 3{fsetup}, 3{fsetup})
('clocks', 0)
('data', 'write', 0x300, 1, 16{alu+setup(in max/min)})
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `alu` | 16 | rows | rmw / rmw_imm / 0F rmw forms: clocks between the read data and the write's post (ALU step); with rmw_write_issue=immediate the write is posted at the ALU step's start with max(alu, setup) setup [T:1253-1305, 1773] |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `fsetup` | 3 | table | 0F memory forms (page_mem=fixed) / bit fields (bf_read=fixed): the read's fetch-free setup counted back from its post [C:1335-1337; T:1655-1660, 1712-1715] |
| `grp_free` | 0 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 1 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 0 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |
| `sidle` | 2 | table | slot_idle=eu: clocks from a left-out write's slot that runs no fetch to the clock the EU goes on [C:1381-1384; E:1984-1987] |
| `wb` | 0 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:183 `0F 2A` ROR4 r/m8: measured reg 20 (J238); mem 31 (J237); M:328-329; routine `ROR4` V20UC.TXT L951-955, L941-945, L946-950 (ROM 02F8-02FB, 02F0-02F3, 02F4-02F7); toE/total(nb) 9 / 10 (10); flags F:- / W:- / E:02F4 / R:02FB; FARJMP –; JMP –

  Routine `ROR4` (work/v30-opcodes.md:1533):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1, `dfloor`=2, `sidle`=2, `setup_free`=3, `fsetup`=3.

## 71. SHIFT_CL (`V35_CLS_SHIFT_CL`)

**Forms**: 128 enumerated, opcodes D2, D3. Examples: ROL rm8,CL (reg) x8; ROR rm8,CL (reg) x8; RCL rm8,CL (reg) x8; RCR rm8,CL (reg) x8; SHL rm8,CL (reg) x8; SHR rm8,CL (reg) x8; ... (16 distinct names).

**V35 measured**:
- reg: 10 for a count of 0, 12 + 2n for n >= 1 (docs/v35s-eu-timing.md:193)
- count not masked (docs/v35s-eu-timing.md:195)
- F3: MOV CL,n ; SHL AW,CL 16 (n=0), 18+2n: shift alone 10 / 12+2n (docs/v35s-chains.md:177)
- a6: `ROL AW, CL [CW=0004]` (ROL reg,CL): V35 20 (even 20, odd 21); V30 14 (doc [11]); V35 - V30 = 6
- a6: `RORC AW, CL [CW=0004]` (RORC reg,CL): V35 20 (even 20, odd 21); V30 14 (doc [11]); V35 - V30 = 6
- a6: `SHL AL, CL [CW=0004]` (SHL reg,CL): V35 20 (even 20, odd 21); V30 14 (doc [11]); V35 - V30 = 6
- a6: `SHL AW, CL [CW=0000]` (SHL reg,CL): V35 10 (even 10, odd 11); V30 9 (doc [7]); V35 - V30 = 1
- a6: `SHL AW, CL [CW=0001]` (SHL reg,CL): V35 14 (even 14, odd 15); V30 11 (doc [8]); V35 - V30 = 3
- a6: `SHL AW, CL [CW=0004]` (SHL reg,CL): V35 20 (even 20, odd 21); V30 14 (doc [11]); V35 - V30 = 6
- a6: `SHR AW, CL [CW=0004]` (SHR reg,CL): V35 20 (even 20, odd 21); V30 14 (doc [11]); V35 - V30 = 6
- a6: `SHRA AW, CL [CW=0004]` (SHRA reg,CL): V35 20 (even 20, odd 21); V30 14 (doc [11]); V35 - V30 = 6

**Model steps, register / no-memory form**: `ROL rm8,CL (reg)` bytes d2c0, run {'count': 3}

```
('clocks', 0{pre})
('take', 1)
('clocks', 9{exec+loop})
('clocks', 6{per_shift_count*3})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 7 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `hphase` | 2 | table | unit_hold: the exec clock of the first micro-boundary (every second exec clock from it) at which a register shift/mul/div waits for a fetch past its second clock [E:608-613; C:1310-1311] |
| `loop` | 2 | table | REP string: each later element's first cycle setup; BCD: each later pair's source read; shift_cl: clocks added to exec for a non-zero count [C:1490-1494; T:1220, 1699, 1820] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:124 `D2/D3 /0-/7` shift r/m,CL (same reg map): measured reg 10+n, CL=0 9 (J229,J240,J260-J263,J266,J268; M:147-148); mem 25+n (J234,J253-J255; M:211); routine `SHIFT_CL` V20UC.TXT L351-355 (ROM 0118-011B); toE/total(nb) no E (exits via FARJMP) / 4 (4); flags F:- / W:- / E:- / R:-; FARJMP SHIFT; JMP –

  Routine `SHIFT_CL` (work/v30-opcodes.md:813):
```
0118 M->tmpb; ALU PASS tmpa
0119 CX->tmpaL
011A tmpa->COUNT, SIGMA->[-03-]; ALU PASS tmpb
011B FARJMP SHIFT
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: As shift_imm: 2 clocks per count; the zero-count form skips `loop` (templates.py:1218-1222). Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `hphase`=2.

## 72. SHIFT_IMM (`V35_CLS_SHIFT_IMM`)

**Forms**: 256 enumerated, opcodes C0, C1, D0, D1. Examples: ROL rm8,imm8 (reg) x8; ROR rm8,imm8 (reg) x8; RCL rm8,imm8 (reg) x8; RCR rm8,imm8 (reg) x8; SHL rm8,imm8 (reg) x8; SHR rm8,imm8 (reg) x8; ... (32 distinct names).

**V35 measured**:
- reg: 10 for a count of 0, 12 + 2n for n >= 1, same for CL and imm8 forms, byte or word (docs/v35s-eu-timing.md:193)
- count not masked: n = 255 costs 522 (docs/v35s-eu-timing.md:195)
- F3: SHL AW,1 10; SHL AW,4 (C1) 20 (docs/v35s-chains.md:176)
- a6: `ROL AW, 1` (ROL reg,1): V35 10 (even 10, odd 10); V30 6 (doc [2]); V35 - V30 = 4
- a6: `ROLC AW, 1` (ROLC reg,1): V35 10 (even 10, odd 10); V30 6 (doc [2]); V35 - V30 = 4
- a6: `ROR AW, 1` (ROR reg,1): V35 10 (even 10, odd 10); V30 6 (doc [2]); V35 - V30 = 4
- a6: `ROR AW, 4` (ROR reg,imm8): V35 20 (even 19, odd 21); V30 14 (doc [11]); V35 - V30 = 6
- a6: `RORC AW, 1` (RORC reg,1): V35 10 (even 10, odd 10); V30 6 (doc [2]); V35 - V30 = 4
- a6: `SHL AL, 1` (SHL reg,1): V35 10 (even 10, odd 10); V30 6 (doc [2]); V35 - V30 = 4
- a6: `SHL AW, 1` (SHL reg,1): V35 10 (even 10, odd 10); V30 6 (doc [2]); V35 - V30 = 4
- a6: `SHL DW, 1` (SHL reg,1): V35 10 (even 10, odd 10); V30 6 (doc [2]); V35 - V30 = 4
- a6: `SHL AW, 4` (SHL reg,imm8): V35 20 (even 19, odd 21); V30 14 (doc [11]); V35 - V30 = 6
- a6: `SHR AW, 1` (SHR reg,1): V35 10 (even 10, odd 10); V30 6 (doc [2]); V35 - V30 = 4
- a6: `SHRA AW, 1` (SHRA reg,1): V35 10 (even 10, odd 10); V30 6 (doc [2]); V35 - V30 = 4

**Model steps, register / no-memory form**: `ROL rm8,imm8 (reg)` bytes c0c002, run {'count': 2}

```
('clocks', 0{pre})
('take', 1, 'chain')
('clocks', 2{cpre})
('take', 1)
('clocks', 6{exec})
('clocks', 4{per_shift_count*2})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `cpre` | 2 | rows | shift_imm (shift_count=late): clocks from the ModR/M take to the count byte's take [C:1304-1305; T:1211-1215] |
| `exec` | 6 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `exec0` | 5 | rows | shift_imm: exec for the form without a count byte (D0/D1, count 1) [C:1303-1304; T:1208-1210] |
| `hphase` | 1 | table | unit_hold: the exec clock of the first micro-boundary (every second exec clock from it) at which a register shift/mul/div waits for a fetch past its second clock [E:608-613; C:1310-1311] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `wb` | 2 | table | result write-back clocks running on past the instruction's end; only a successor with wbsync waits for them [C:1295-1296; E:351, 323] |

**V30 counterpart**: 
- work/v30-opcodes.md:109 `C0/C1 /0-/7` shift r/m,imm8: /0 ROL /1 ROR /2 RCL /3 RCR /4 SHL /5 SHR /6 (undefined, ALU op [-0E-]) /7 SAR: measured reg: ROR AW,4 14 (J236), SHL AW,4 14 (J264), class 10+n (M:147); mem not measured; routine `SHIFT_IMM` V20UC.TXT L816-820 (ROM 028C-028F); toE/total(nb) no E (exits via FARJMP) / 4 (4); flags F:- / W:- / E:- / R:-; FARJMP SHIFT; JMP –; note: one routine for all reg values; count from Q (imm8); loop in SHIFT
- work/v30-opcodes.md:123 `D0/D1 /0-/7` shift r/m,1: /0 ROL /1 ROR /2 RCL(ROLC) /3 RCR(RORC) /4 SHL /5 SHR /6 undefined /7 SAR(SHRA): measured reg 6 for all ops measured (ROL J228, RCL J232, ROR J235, RCR J239, SHL J256-J259, SHR J265, SAR J267; M:146); mem 22 (ROR J233, SHL J251; M:149); odd mem 30 (J252); routine `SHIFT_1` V20UC.TXT L346-350 (ROM 0114-0117); toE/total(nb) 4 / 4 (4); flags F:- / W:0116 / E:0117 / R:0116; FARJMP –; JMP –; note: R flag at 0116 repeats ALU OPC COUNT(=1) times

  Routine `SHIFT_IMM` (work/v30-opcodes.md:1237):
```
028C Q->tmpaL; ALU PASS tmpa
028D M->tmpb
028E tmpa->COUNT, SIGMA->[-03-]; ALU PASS tmpb
028F FARJMP SHIFT
```

  Routine `SHIFT_1` (work/v30-opcodes.md:802):
```
0114 CONST(1)->COUNT
0115 M->tmpb; ALU PASS tmpb
0116 SIGMA->tmpb; ALU OPC tmpb  [WR]
0117 SIGMA->M; CTL [-06-]  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: The V35 count loop is 2 per count against the V30's 1 (V35 12+2n, eu-timing.md:193; V30 10+n, v30-structure.md); the sources do not say why each count costs two clocks. The shift_imm exec splits into exec (C0/C1) and exec0 (D0/D1) by format. Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `wb`=2, `hphase`=1.

## 73. STORE (`V35_CLS_STORE`)

**Forms**: 1088 enumerated, opcodes 88, 89, 8C, A2, A3. Examples: MOV [m],AL x256; MOV [m],AX x256; MOV rm8,r8 (mem) x192; MOV rm16,r16 (mem) x192; MOV rm16,sreg (mem) x192 (5 distinct names).

**V35 measured**:
- store 8 (+EA) (docs/v35s-eu-timing.md:149)
- odd-address word store +3 (docs/v35s-eu-timing.md:152)
- each data write costs 3 extra clocks after its bus cycle with RAMEN = 1 (docs/v35s-eu-timing.md:260)
- a6: `MOV [0x0801], AW [DS0=0000]` (MOV dmem,acc): V35 12 (even 11, odd 13); V30 14 (doc [13]); V35 - V30 = -2
- a6: `MOV [0x0802], AW [BW=0800]` (MOV dmem,acc): V35 9 (even 8, odd 10); V30 10 (doc [9]); V35 - V30 = -1
- a6: `MOV [BW], DL [BW=0800]` (MOV mem,reg): V35 8 (even 8, odd 8); V30 11 (doc [9]); V35 - V30 = -3
- a6: `MOV [BW], DW [BW=0800]` (MOV mem,reg): V35 8 (even 8, odd 8); V30 11 (doc [9]); V35 - V30 = -3
- a6: `MOV [BW], DW [BW=0801 DS0=0000 IX=0010]` (MOV mem,reg): V35 11 (even 11, odd 11); V30 15 (doc [13]); V35 - V30 = -4
- a6: `MOV [BW], DS0 [BW=0800]` (MOV mem16,sreg): V35 9 (even 9, odd 9); V30 11 (doc [10]); V35 - V30 = -2

**Model steps, memory form**: `MOV rm8,r8 (mem)` bytes 8800, EA mode base_index (ea table `base_index`)

```
('clocks', 0{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('data', 'write', 0x300, 1, 0{setup})
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 2 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |
| `setup` | 0 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |

**V30 counterpart**: 
- work/v30-opcodes.md:79 `88-8B` MOV r/m,r / r,r/m: measured reg,reg 3 (J130-J132); load 13 (J126-J128); odd word load 17 (J129); store 11 (J117,J118); odd-anchor store 10 (J119); odd store 15 (J120); routine `MOV_RM` V20UC.TXT L96-100 (ROM 004C-004F); toE/total(nb) 2 / 2 (2); flags F:- / W:- / E:004D / R:-; FARJMP –; JMP –; note: 88/89 stores: operand pre-read suppressed (pla_3 MODRM_STORE)
- work/v30-opcodes.md:80 `8C` MOV r/m16,sreg: measured reg 2 (J133,J134); mem 11 (J121); routine `MOV_SREG` V20UC.TXT L101-105 (ROM 0050-0053); toE/total(nb) 1 / 1 (1); flags F:- / W:- / E:0050 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:95 `A2/A3` MOV [moffs],AL/AX: measured 10 (J115); odd word 14 (J114); M:143; routine `MOV_DMEM_ACC` V20UC.TXT L171-175 (ROM 0088-008B); toE/total(nb) 3 / 4 (4); flags F:- / W:- / E:008A / R:-; FARJMP –; JMP –

  Routine `MOV_RM` (work/v30-opcodes.md:369):
```
004C R->tmpa
004D tmpa->M; CTL [-06-]  [E]
```

  Routine `MOV_SREG` (work/v30-opcodes.md:378):
```
0050 R->M; CTL [-06-]  [E]
```

  Routine `MOV_DMEM_ACC` (work/v30-opcodes.md:512):
```
0088 Q->tmpbL
0089 Q->tmpbH
008A tmpb->IND; CTL MEMW  [E]
008B M->OPR
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `dfloor`=2.

## 74. STORE_IMM (`V35_CLS_STORE_IMM`)

**Forms**: 512 enumerated, opcodes C6, C7. Examples: MOV rm8,imm8 (mem) x192; MOV rm16,imm16 (mem) x192; MOV rm8,imm8 (reg) x64; MOV rm16,imm16 (reg) x64 (4 distinct names).

**V35 measured**:
- a6: `MOV word [BW], 0x1234 [BW=0800]` (MOV mem,imm): V35 10 (even 10, odd 10); V30 11 (doc [11]); V35 - V30 = -1

**Model steps, register / no-memory form**: `MOV rm8,imm8 (reg)` bytes c6c002

```
('clocks', 0{pre})
('take', 1)
('clocks', 0, 'ea')
('post', 'write', None, 1, 0{setup})
('issued')
('take', 1, 'chain')
('wait')
('clocks', 0{post})
```

**Model steps, memory form**: `MOV rm8,imm8 (mem)` bytes c60002, EA mode base_index (ea table `base_index`)

```
('clocks', 0{pre})
('take', 1)
('clocks', 2{ea.base_index}, 'ea')
('take', 0)
('post', 'write', 0x300, 1, 2{setup+grp1}, 1{grp_free(in max/min)}, True)
('issued')
('take', 1, 'chain')
('wait')
('clocks', 0{post})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `dadd` | 1 | rows | mem_order=split: EU clocks after a displacement's take (store_imm) [C:1316-1318; T:982-985] |
| `dfloor` | 2 | table | disp_floor / ea_floor: the first data cycle no earlier than dfloor clocks after the displacement take (or where a mod-00 form's displacement would be taken) [C:1319-1324; E:427-434, 1087] |
| `grp` | 3 | rows | group memory form: the group setup clocks before the first data request (as EU clocks or extra setup per grp_mode) [T:1032-1041] |
| `grp1` | 2 | rows | grp for a group form with a one-byte immediate (83 /x, imm8_grp=own) [T:1042-1043] |
| `grp_free` | 1 | table | the last grp_free of the group setup clocks must be fetch-free (grp_mode=setup) [T:1084-1088] |
| `istart` | 5 | table | imm_count=start: the first data request of a memory form with an immediate issues no earlier than istart + imm bytes clocks after the start [E:435-439] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 0 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |

**V30 counterpart**: 
- work/v30-opcodes.md:114 `C6/C7 /0` MOV r/m,imm: measured mem word 11 (J116; M:141); reg8 form shares the B0 tail (M:485-486); write-only store, cadence M:487-505; routine `MOV_RM_IMM` V20UC.TXT L321-325 (ROM 0100-0103); toE/total(nb) 3 / 3 (3); flags F:- / W:- / E:0102 / R:-; FARJMP –; JMP 0100 JMP OP8 2 ->0102

  Routine `MOV_RM_IMM` (work/v30-opcodes.md:755):
```
0100 Q->tmpbL; JMP OP8 2 ->0102
0101 Q->tmpbH
0102 tmpb->M; CTL [-06-]  [E]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: C6/C7 register forms (128) are in this class. Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `dfloor`=2, `istart`=5, `grp_free`=1, `dadd`=1.

## 75. STR_CMP (`V35_CLS_STR_CMP`)

**Forms**: 10 enumerated, opcodes A6, A7, REP+A6, REP+A7. Examples: REPNC CMPSB [CMPBK] x1; REPNC CMPSW [CMPBK] x1; REPC CMPSB [CMPBK] x1; REPC CMPSW [CMPBK] x1; CMPSB [CMPBK] x1; CMPSW [CMPBK] x1; ... (10 distinct names).

**V35 measured**:
- REPE CMPBKW 50 + 18n; single 25.5 (docs/v35s-eu-timing.md:205)
- CW = 0: 15 (docs/v35s-eu-timing.md:207)
- a6: `CMPBKB [IY=0900]` (CMPBK/CMPBKB/CMPBKW): V35 25.5 (even 25, odd 26); V30 13 (doc [13]); V35 - V30 = 12.5
- a6: `CMPBKW [IY=0900]` (CMPBK/CMPBKB/CMPBKW): V35 25.5 (even 25, odd 26); V30 13 (doc [13]); V35 - V30 = 12.5

**Model steps, register / no-memory form**: `REPNC CMPSB [CMPBK]` bytes 64a6, run {'n': 3, 'cond': False}

```
('take', 1)
('nowait', 5{rpre})
('fetch_release', None)
('data', 'read', 0x300, 1, 14{first})
('data', 'read', 0x200, 1, 7{mid})
('fetch_hold', 2{chold})
('data', 'read', 0x301, 1, 7{loop})
('data', 'read', 0x201, 1, 7{mid})
('fetch_hold', 2{chold})
('data', 'read', 0x302, 1, 7{loop})
('data', 'read', 0x202, 1, 7{mid})
('fetch_hold', 2{chold})
('data', 'read', 0x303, 1, 7{loop})
('data', 'read', 0x203, 1, 7{mid})
('fetch_release', 8{xfetch})
('split_floor', 4{xsplit})
('clocks', 18{rexit+xwb*-1})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `cexit` | 19 | rows | REP compare exit clocks when the condition ended it [C:1494-1495; T:1850] |
| `chold` | 2 | table | compares (str_hold=hold): no fetch request for chold clocks after a compared element; dbnz_z: nhold for the count's exit [C:1500-1501, 1433-1434; T:1813-1816; E:849-851] |
| `exec` | 6 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `first` | 14 | table | REP string / BCD string: the first element's first cycle setup [C:1490-1494; T:1838, 1699] |
| `loop` | 7 | table | REP string: each later element's first cycle setup; BCD: each later pair's source read; shift_cl: clocks added to exec for a non-zero count [C:1490-1494; T:1220, 1699, 1820] |
| `mid` | 7 | rows | string / BCD: setup of an element's later cycles (the write after the read; the destination read) [C:1489-1491; T:1810, 1700] |
| `nx` | 2 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rexit` | 20 | rows | REP string exit clocks when CW ran out; mul/div (refresh on): the exec's last clocks run as the loop exit [C:1325-1329, 1494; T:1850, 1133] |
| `rpre` | 5 | rows | REP string: clocks after the opcode's take before the first element [C:1490; T:1830] |
| `setup` | 9 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `ugap` | 1 | table | unprefixed string form: starts no earlier than ugap clocks past the last fetch's delivery (str_single_start) [C:1497-1499; E:245-250, 347-350] |
| `uwb` | 2 | table | string class, unprefixed form: the exec's last uwb clocks are a write-back (str_single_wb=wb/index) [E:351-355; T:1824] |
| `xfetch` | 8 | rows | str_fetch=hold: fetch requests again xfetch clocks after the last cycle [C:1328; T:1843-1844] |
| `xsplit` | 4 | rows | str_split=floor: exit no earlier than xsplit clocks after a split last cycle's second half issue [C:1327-1328; T:1845-1849] |
| `xwb` | 2 | table | string class, REP form: the exit's last xwb clocks are a write-back past the end (str_exit=wb) [E:356-359; T:1850-1852] |
| `zexit` | 10 | rows | REP string with CW = 0: clocks to the end [C:1491; T:1834] |
| `zfetch` | 6 | rows | str_fetch=hold, CW = 0: clocks into the exit at which the aborted start's request is raised again [C:1329; T:1832-1833] |

**V30 counterpart**: 
- work/v30-opcodes.md:98 `A6/A7` CMPSB/W (CMPBKB/W), no REP: measured 13 (J72,J73; M:199); routine `CMPS` V20UC.TXT L196-200, L201-205 (ROM 009C-009F, 00A0-00A3); toE/total(nb) 7 / 8 (8); flags F:00A0,00A2 / W:00A3 / E:00A2 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:99 `REP A6/A7` REPE/REPNE CMPSB/W: measured REPE CMPSW 11+14n (M:203); odd addresses 7+22/rep (M:395-396); CX=0 12 (M:204); routine `REP_CMPS` V20UC.TXT L206-210, L211-215, L216-220 (ROM 00A4-00A7, 00A8-00AB, 00AC-00AF); toE/total(nb) no E (exits via FARJMP) / 12 (12); flags F:00AA,00AC / W:00AD / E:- / R:-; FARJMP REPX; JMP 00A6 JMP Z 11 ->00AF; 00AE JMP REP 3 ->00A7

  Routine `CMPS` (work/v30-opcodes.md:549):
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

  Routine `REP_CMPS` (work/v30-opcodes.md:564):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=2, `uwb`=2, `xwb`=2, `chold`=2, `ugap`=1, `xsplit`=4, `xfetch`=8, `zfetch`=6.

## 76. STR_IN (`V35_CLS_STR_IN`)

**Forms**: 10 enumerated, opcodes 6C, 6D, REP+6C, REP+6D. Examples: REPNC INSB [INM] x1; REPNC INSW [INM] x1; REPC INSB [INM] x1; REPC INSW [INM] x1; INSB [INM] x1; INSW [INM] x1; ... (10 distinct names).

**V35 measured**: not in the sources (no eu-timing row, no a6 form).

**Model steps, register / no-memory form**: `REPNC INSB [INM]` bytes 646c, run {'n': 3, 'cond': False}

```
('take', 1)
('nowait', 5{rpre})
('fetch_release', None)
('data', 'io_read', 224, 1, 15{first})
('data', 'write', 0x300, 1, 4{mid})
('data', 'io_read', 224, 1, 6{loop})
('data', 'write', 0x301, 1, 4{mid})
('data', 'io_read', 224, 1, 6{loop})
('data', 'write', 0x302, 1, 4{mid})
('fetch_release', 8{xfetch})
('split_floor', 4{xsplit})
('clocks', 10{rexit+xwb*-1})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 4 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `first` | 15 | table | REP string / BCD string: the first element's first cycle setup [C:1490-1494; T:1838, 1699] |
| `loop` | 6 | table | REP string: each later element's first cycle setup; BCD: each later pair's source read; shift_cl: clocks added to exec for a non-zero count [C:1490-1494; T:1220, 1699, 1820] |
| `mid` | 4 | rows | string / BCD: setup of an element's later cycles (the write after the read; the destination read) [C:1489-1491; T:1810, 1700] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rexit` | 12 | rows | REP string exit clocks when CW ran out; mul/div (refresh on): the exec's last clocks run as the loop exit [C:1325-1329, 1494; T:1850, 1133] |
| `rpre` | 5 | rows | REP string: clocks after the opcode's take before the first element [C:1490; T:1830] |
| `setup` | 9 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `ufree` | 6 | table | unprefixed INM/OUTM (str_in_io / str_out_rd=free): fetch-free clocks of the I/O / memory read's setup [E:1935-1949] |
| `ugap` | 1 | table | unprefixed string form: starts no earlier than ugap clocks past the last fetch's delivery (str_single_start) [C:1497-1499; E:245-250, 347-350] |
| `uwb` | 2 | table | string class, unprefixed form: the exec's last uwb clocks are a write-back (str_single_wb=wb/index) [E:351-355; T:1824] |
| `xfetch` | 8 | rows | str_fetch=hold: fetch requests again xfetch clocks after the last cycle [C:1328; T:1843-1844] |
| `xsplit` | 4 | rows | str_split=floor: exit no earlier than xsplit clocks after a split last cycle's second half issue [C:1327-1328; T:1845-1849] |
| `xwb` | 2 | table | string class, REP form: the exit's last xwb clocks are a write-back past the end (str_exit=wb) [E:356-359; T:1850-1852] |
| `zexit` | 11 | rows | REP string with CW = 0: clocks to the end [C:1491; T:1834] |
| `zfetch` | 7 | rows | str_fetch=hold, CW = 0: clocks into the exit at which the aborted start's request is raised again [C:1329; T:1832-1833] |

**V30 counterpart**: 
- work/v30-opcodes.md:71 `6C/6D` INSB/INSW (NEC INM), no REP: measured not measured; routine `INM` V20UC.TXT L826-830 (ROM 0294-0297); toE/total(nb) 3 / 4 (4); flags F:- / W:- / E:0296 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:72 `REP 6C/6D` REP INSB/INSW (REP INM): measured not measured; routine `REP_INM` V20UC.TXT L831-835, L836-840 (ROM 0298-029B, 029C-029F); toE/total(nb) no E (exits via FARJMP) / 8 (7); flags F:- / W:- / E:- / R:-; FARJMP REPX; JMP 029A JMP Z 7 ->029F; 029E JMP REP 3 ->029B

  Routine `INM` (work/v30-opcodes.md:1259):
```
0294 DX->IND; CTL MEMR IO
0295 dir*sz->tmpa, DI->tmpb
0296 DI->IND; CTL MEMW ES  [E]
0297 SIGMA->DI
```

  Routine `REP_INM` (work/v30-opcodes.md:1270):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `uwb`=2, `xwb`=2, `ugap`=1, `ufree`=6, `xsplit`=4, `xfetch`=8, `zfetch`=7.

## 77. STR_LOAD (`V35_CLS_STR_LOAD`)

**Forms**: 10 enumerated, opcodes AC, AD, REP+AC, REP+AD. Examples: REPNC LODSB [LDM] x1; REPNC LODSW [LDM] x1; REPC LODSB [LDM] x1; REPC LODSW [LDM] x1; LODSB [LDM] x1; LODSW [LDM] x1; ... (10 distinct names).

**V35 measured**:
- REP LDMW 26 + 11n; single 13.5 (docs/v35s-eu-timing.md:204)
- CW = 0: 15 (docs/v35s-eu-timing.md:207)
- a6: `LDMB [IY=0900]` (LDM/LDMB/LDMW): V35 13.5 (even 13, odd 14); V30 9 (doc [7]); V35 - V30 = 4.5
- a6: `LDMW [IY=0900]` (LDM/LDMB/LDMW): V35 13.5 (even 13, odd 14); V30 9 (doc [7]); V35 - V30 = 4.5
- a6: `LDMW [DS0=0000 DS1=0000 IX=0801 IY=0900]` (LDM/LDMB/LDMW): V35 16.5 (even 16, odd 17); V30 13 (doc [11]); V35 - V30 = 3.5

**Model steps, register / no-memory form**: `REPNC LODSB [LDM]` bytes 64ac, run {'n': 3, 'cond': False}

```
('take', 1)
('nowait', 6{rpre})
('fetch_release', None)
('data', 'read', 0x200, 1, 14{first})
('data', 'read', 0x201, 1, 9{loop})
('data', 'read', 0x202, 1, 9{loop})
('fetch_release', 8{xfetch})
('clocks', 13{rexit+xwb*-1})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 2 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `first` | 14 | table | REP string / BCD string: the first element's first cycle setup [C:1490-1494; T:1838, 1699] |
| `loop` | 9 | table | REP string: each later element's first cycle setup; BCD: each later pair's source read; shift_cl: clocks added to exec for a non-zero count [C:1490-1494; T:1220, 1699, 1820] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rexit` | 15 | rows | REP string exit clocks when CW ran out; mul/div (refresh on): the exec's last clocks run as the loop exit [C:1325-1329, 1494; T:1850, 1133] |
| `rpre` | 6 | rows | REP string: clocks after the opcode's take before the first element [C:1490; T:1830] |
| `setup` | 9 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `ugap` | 0 | table | unprefixed string form: starts no earlier than ugap clocks past the last fetch's delivery (str_single_start) [C:1497-1499; E:245-250, 347-350] |
| `uwb` | 0 | table | string class, unprefixed form: the exec's last uwb clocks are a write-back (str_single_wb=wb/index) [E:351-355; T:1824] |
| `xfetch` | 8 | rows | str_fetch=hold: fetch requests again xfetch clocks after the last cycle [C:1328; T:1843-1844] |
| `xsplit` | 4 | rows | str_split=floor: exit no earlier than xsplit clocks after a split last cycle's second half issue [C:1327-1328; T:1845-1849] |
| `xwb` | 2 | table | string class, REP form: the exit's last xwb clocks are a write-back past the end (str_exit=wb) [E:356-359; T:1850-1852] |
| `zexit` | 9 | rows | REP string with CW = 0: clocks to the end [C:1491; T:1834] |
| `zfetch` | 5 | rows | str_fetch=hold, CW = 0: clocks into the exit at which the aborted start's request is raised again [C:1329; T:1832-1833] |

**V30 counterpart**: 
- work/v30-opcodes.md:103 `AC/AD` LODSB/W (LDMB/W), no REP: measured 9 (J108,J109); odd 13 (J110); M:198; routine `LODS` V20UC.TXT L246-250 (ROM 00C4-00C7); toE/total(nb) 4 / 4 (4); flags F:00C7 / W:- / E:00C7 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:104 `REP AC/AD` REP LODSB/W: measured not measured (CX=0 class 12, M:204); routine `REP_LODS` V20UC.TXT L251-255, L256-260 (ROM 00C8-00CB, 00CC-00CF); toE/total(nb) no E (exits via FARJMP) / 8 (8); flags F:00CD / W:- / E:- / R:-; FARJMP REPX; JMP 00CA JMP Z 7 ->00CF; 00CE JMP REP 3 ->00CB

  Routine `LODS` (work/v30-opcodes.md:618):
```
00C4 dir*sz->tmpc, SI->tmpb; ALU ADD tmpc
00C5 SI->IND; CTL MEMR
00C6 SIGMA->SI
00C7 OPR->M  [FE]
```

  Routine `REP_LODS` (work/v30-opcodes.md:629):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `xwb`=2, `xsplit`=4, `xfetch`=8, `zfetch`=5.

## 78. STR_MOVE (`V35_CLS_STR_MOVE`)

**Forms**: 10 enumerated, opcodes A4, A5, REP+A4, REP+A5. Examples: REPNC MOVSB [MOVBK] x1; REPNC MOVSW [MOVBK] x1; REPC MOVSB [MOVBK] x1; REPC MOVSW [MOVBK] x1; MOVSB [MOVBK] x1; MOVSW [MOVBK] x1; ... (10 distinct names).

**V35 measured**:
- REP MOVBKW / MOVBKB 25 + 18n; single 23.5 (docs/v35s-eu-timing.md:202)
- any REP form, CW = 0: 15 (docs/v35s-eu-timing.md:207)
- odd source and destination +6 per element (docs/v35s-eu-timing.md:209)
- a6: `MOVBKB [IY=0900]` (MOVBK/MOVBKB/MOVBKW): V35 23.5 (even 23, odd 24); V30 13 (doc [11]); V35 - V30 = 10.5
- a6: `MOVBKW [IY=0900]` (MOVBK/MOVBKB/MOVBKW): V35 23.5 (even 23, odd 24); V30 13 (doc [11]); V35 - V30 = 10.5

**Model steps, register / no-memory form**: `REPNC MOVSB [MOVBK]` bytes 64a4, run {'n': 3, 'cond': False}

```
('take', 1)
('nowait', 5{rpre})
('fetch_release', None)
('data', 'read', 0x200, 1, 15{first})
('data', 'write', 0x300, 1, 7{mid})
('data', 'read', 0x201, 1, 7{loop})
('data', 'write', 0x301, 1, 7{mid})
('data', 'read', 0x202, 1, 7{loop})
('data', 'write', 0x302, 1, 7{mid})
('fetch_release', 8{xfetch})
('split_floor', 4{xsplit})
('clocks', 10{rexit+xwb*-1})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 4 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `first` | 15 | table | REP string / BCD string: the first element's first cycle setup [C:1490-1494; T:1838, 1699] |
| `loop` | 7 | table | REP string: each later element's first cycle setup; BCD: each later pair's source read; shift_cl: clocks added to exec for a non-zero count [C:1490-1494; T:1220, 1699, 1820] |
| `mid` | 7 | rows | string / BCD: setup of an element's later cycles (the write after the read; the destination read) [C:1489-1491; T:1810, 1700] |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rexit` | 12 | rows | REP string exit clocks when CW ran out; mul/div (refresh on): the exec's last clocks run as the loop exit [C:1325-1329, 1494; T:1850, 1133] |
| `rpre` | 5 | rows | REP string: clocks after the opcode's take before the first element [C:1490; T:1830] |
| `setup` | 9 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `ugap` | 1 | table | unprefixed string form: starts no earlier than ugap clocks past the last fetch's delivery (str_single_start) [C:1497-1499; E:245-250, 347-350] |
| `uwb` | 2 | table | string class, unprefixed form: the exec's last uwb clocks are a write-back (str_single_wb=wb/index) [E:351-355; T:1824] |
| `xfetch` | 8 | rows | str_fetch=hold: fetch requests again xfetch clocks after the last cycle [C:1328; T:1843-1844] |
| `xsplit` | 4 | rows | str_split=floor: exit no earlier than xsplit clocks after a split last cycle's second half issue [C:1327-1328; T:1845-1849] |
| `xwb` | 2 | table | string class, REP form: the exit's last xwb clocks are a write-back past the end (str_exit=wb) [E:356-359; T:1850-1852] |
| `zexit` | 10 | rows | REP string with CW = 0: clocks to the end [C:1491; T:1834] |
| `zfetch` | 6 | rows | str_fetch=hold, CW = 0: clocks into the exit at which the aborted start's request is raised again [C:1329; T:1832-1833] |

**V30 counterpart**: 
- work/v30-opcodes.md:96 `A4/A5` MOVSB/W (MOVBKB/W), no REP: measured 13 (J137,J138; M:198); routine `MOVS` V20UC.TXT L176-180 (ROM 008C-008F); toE/total(nb) 4 / 4 (4); flags F:- / W:- / E:008F / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:97 `REP A4/A5` REP MOVSB/W: measured 9+8n (M:202); CX=0 12 (M:204); routine `REP_MOVS` V20UC.TXT L186-190, L191-195 (ROM 0094-0097, 0098-009B); toE/total(nb) no E (exits via FARJMP) / 8 (8); flags F:- / W:- / E:- / R:-; FARJMP REPX; JMP 0096 JMP Z 7 ->009B; 009A JMP REP 3 ->0097

  Routine `MOVS` (work/v30-opcodes.md:523):
```
008C dir*sz->tmpc, SI->tmpb; ALU ADD tmpc
008D SI->IND; CTL MEMR
008E SIGMA->SI, DI->tmpb; ALU ADD tmpc
008F DI->IND; CTL MEMW ES  [E]
```

  Routine `REP_MOVS` (work/v30-opcodes.md:534):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: V35 18 per element against the V30's 8 (eu-timing.md:202; V30 per v30-structure.md); the sources do not say what fills the 18 beyond two bus cycles. Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1, `uwb`=2, `xwb`=2, `ugap`=1, `xsplit`=4, `xfetch`=8, `zfetch`=6.

## 79. STR_OUT (`V35_CLS_STR_OUT`)

**Forms**: 10 enumerated, opcodes 6E, 6F, REP+6E, REP+6F. Examples: REPNC OUTSB [OUTM] x1; REPNC OUTSW [OUTM] x1; REPC OUTSB [OUTM] x1; REPC OUTSW [OUTM] x1; OUTSB [OUTM] x1; OUTSW [OUTM] x1; ... (10 distinct names).

**V35 measured**: not in the sources (no eu-timing row, no a6 form).

**Model steps, register / no-memory form**: `REPNC OUTSB [OUTM]` bytes 646e, run {'n': 3, 'cond': False}

```
('take', 1)
('nowait', 5{rpre})
('fetch_release', None)
('data', 'read', 0x200, 1, 16{first})
('data', 'io_write', 224, 1, 6{mid})
('data', 'read', 0x201, 1, 6{loop})
('data', 'io_write', 224, 1, 6{mid})
('data', 'read', 0x202, 1, 6{loop})
('data', 'io_write', 224, 1, 7{mid+last})
('fetch_release', 9{xfetch})
('split_floor', 4{xsplit})
('clocks', 11{rexit+xwb*-1})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 3 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `first` | 16 | table | REP string / BCD string: the first element's first cycle setup [C:1490-1494; T:1838, 1699] |
| `last` | 1 | table | the CW-ending element's last cycle: last more setup clocks (str_out) [C:1493-1494; T:1812] |
| `loop` | 6 | table | REP string: each later element's first cycle setup; BCD: each later pair's source read; shift_cl: clocks added to exec for a non-zero count [C:1490-1494; T:1220, 1699, 1820] |
| `mid` | 6 | rows | string / BCD: setup of an element's later cycles (the write after the read; the destination read) [C:1489-1491; T:1810, 1700] |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rexit` | 13 | rows | REP string exit clocks when CW ran out; mul/div (refresh on): the exec's last clocks run as the loop exit [C:1325-1329, 1494; T:1850, 1133] |
| `rpre` | 5 | rows | REP string: clocks after the opcode's take before the first element [C:1490; T:1830] |
| `setup` | 10 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `ufree` | 7 | table | unprefixed INM/OUTM (str_in_io / str_out_rd=free): fetch-free clocks of the I/O / memory read's setup [E:1935-1949] |
| `ugap` | 0 | table | unprefixed string form: starts no earlier than ugap clocks past the last fetch's delivery (str_single_start) [C:1497-1499; E:245-250, 347-350] |
| `usetup` | 11 | table | unprefixed OUTM (str_out_rd=free): its read's setup in all [E:1941-1949] |
| `uwb` | 0 | table | string class, unprefixed form: the exec's last uwb clocks are a write-back (str_single_wb=wb/index) [E:351-355; T:1824] |
| `xfetch` | 9 | rows | str_fetch=hold: fetch requests again xfetch clocks after the last cycle [C:1328; T:1843-1844] |
| `xsplit` | 4 | rows | str_split=floor: exit no earlier than xsplit clocks after a split last cycle's second half issue [C:1327-1328; T:1845-1849] |
| `xwb` | 2 | table | string class, REP form: the exit's last xwb clocks are a write-back past the end (str_exit=wb) [E:356-359; T:1850-1852] |
| `zexit` | 11 | rows | REP string with CW = 0: clocks to the end [C:1491; T:1834] |
| `zfetch` | 7 | rows | str_fetch=hold, CW = 0: clocks into the exit at which the aborted start's request is raised again [C:1329; T:1832-1833] |

**V30 counterpart**: 
- work/v30-opcodes.md:73 `6E/6F` OUTSB/OUTSW (NEC OUTM), no REP: measured not measured; routine `OUTM` V20UC.TXT L841-845 (ROM 02A0-02A3); toE/total(nb) 3 / 4 (4); flags F:- / W:- / E:02A2 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:74 `REP 6E/6F` REP OUTSB/OUTSW (REP OUTM): measured not measured; routine `REP_OUTM` V20UC.TXT L846-850, L851-855 (ROM 02A4-02A7, 02A8-02AB); toE/total(nb) no E (exits via FARJMP) / 8 (8); flags F:- / W:- / E:- / R:-; FARJMP REPX; JMP 02A6 JMP Z 7 ->02AB; 02AA JMP REP 3 ->02A7

  Routine `OUTM` (work/v30-opcodes.md:1285):
```
02A0 SI->IND; CTL MEMR
02A1 dir*sz->tmpa, SI->tmpb
02A2 DX->IND; CTL MEMW IO  [E]
02A3 SIGMA->SI
```

  Routine `REP_OUTM` (work/v30-opcodes.md:1296):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `xwb`=2, `ufree`=7, `xsplit`=4, `xfetch`=9, `zfetch`=7.

## 80. STR_SCAN (`V35_CLS_STR_SCAN`)

**Forms**: 10 enumerated, opcodes AE, AF, REP+AE, REP+AF. Examples: REPNC SCASB [CMPM] x1; REPNC SCASW [CMPM] x1; REPC SCASB [CMPM] x1; REPC SCASW [CMPM] x1; SCASB [CMPM] x1; SCASW [CMPM] x1; ... (10 distinct names).

**V35 measured**:
- REPE CMPMW 40 + 12n (docs/v35s-eu-timing.md:206)
- CW = 0: 15 (docs/v35s-eu-timing.md:207)

**Model steps, register / no-memory form**: `REPNC SCASB [CMPM]` bytes 64ae, run {'n': 3, 'cond': False}

```
('take', 1)
('nowait', 5{rpre})
('fetch_release', None)
('data', 'read', 0x300, 1, 15{first})
('fetch_hold', 3{chold})
('data', 'read', 0x301, 1, 8{loop1})
('fetch_hold', 3{chold})
('data', 'read', 0x302, 1, 10{loop})
('fetch_hold', 3{chold})
('data', 'read', 0x303, 1, 10{loop})
('fetch_release', 8{xfetch})
('clocks', 18{rexit+xwb*-1})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `cexit` | 19 | rows | REP compare exit clocks when the condition ended it [C:1494-1495; T:1850] |
| `chold` | 3 | table | compares (str_hold=hold): no fetch request for chold clocks after a compared element; dbnz_z: nhold for the count's exit [C:1500-1501, 1433-1434; T:1813-1816; E:849-851] |
| `exec` | 7 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `first` | 15 | table | REP string / BCD string: the first element's first cycle setup [C:1490-1494; T:1838, 1699] |
| `loop` | 10 | table | REP string: each later element's first cycle setup; BCD: each later pair's source read; shift_cl: clocks added to exec for a non-zero count [C:1490-1494; T:1220, 1699, 1820] |
| `loop1` | 8 | table | str_scan: the second element's setup (1-to-2 spacing) [C:1492-1493; T:1820] |
| `nx` | 1 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rexit` | 20 | rows | REP string exit clocks when CW ran out; mul/div (refresh on): the exec's last clocks run as the loop exit [C:1325-1329, 1494; T:1850, 1133] |
| `rpre` | 5 | rows | REP string: clocks after the opcode's take before the first element [C:1490; T:1830] |
| `setup` | 10 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `ugap` | 1 | table | unprefixed string form: starts no earlier than ugap clocks past the last fetch's delivery (str_single_start) [C:1497-1499; E:245-250, 347-350] |
| `uwb` | 0 | table | string class, unprefixed form: the exec's last uwb clocks are a write-back (str_single_wb=wb/index) [E:351-355; T:1824] |
| `xfetch` | 8 | rows | str_fetch=hold: fetch requests again xfetch clocks after the last cycle [C:1328; T:1843-1844] |
| `xsplit` | 4 | rows | str_split=floor: exit no earlier than xsplit clocks after a split last cycle's second half issue [C:1327-1328; T:1845-1849] |
| `xwb` | 2 | table | string class, REP form: the exit's last xwb clocks are a write-back past the end (str_exit=wb) [E:356-359; T:1850-1852] |
| `zexit` | 10 | rows | REP string with CW = 0: clocks to the end [C:1491; T:1834] |
| `zfetch` | 6 | rows | str_fetch=hold, CW = 0: clocks into the exit at which the aborted start's request is raised again [C:1329; T:1832-1833] |

**V30 counterpart**: 
- work/v30-opcodes.md:105 `AE/AF` SCASB/W (CMPMB/W), no REP: measured not measured; routine `SCAS` V20UC.TXT L261-265, L266-270 (ROM 00D0-00D3, 00D4-00D7); toE/total(nb) 6 / 6 (6); flags F:00D4 / W:00D5 / E:00D5 / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:106 `REP AE/AF` REPE/REPNE SCASB/W: measured not measured (CX=0 class 12, M:204); routine `REP_SCAS` V20UC.TXT L206-210, L271-275, L276-280 (ROM 00A4-00A7, 00D8-00DB, 00DC-00DF); toE/total(nb) no E (exits via FARJMP) / 12 (10); flags F:00DA / W:00DB / E:- / R:-; FARJMP REPX; JMP 00A6 JMP Z 11 ->00DF; 00DC JMP REP 3 ->00A7; note: first block (00A4-00A7) shared with REP CMPS

  Routine `SCAS` (work/v30-opcodes.md:644):
```
00D0 dir*sz->tmpc, DI->tmpb; ALU ADD tmpc
00D1 DI->IND; CTL MEMR ES
00D2 SIGMA->DI; ALU SUB tmpa
00D3 M->tmpb
00D4 OPR->tmpa  [F]
00D5 SIGMA->NULL  [WE]
```

  Routine `REP_SCAS` (work/v30-opcodes.md:657):
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

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `nx`=1, `xwb`=2, `chold`=3, `ugap`=1, `xsplit`=4, `xfetch`=8, `zfetch`=6.

## 81. STR_STORE (`V35_CLS_STR_STORE`)

**Forms**: 10 enumerated, opcodes AA, AB, REP+AA, REP+AB. Examples: REPNC STOSB [STM] x1; REPNC STOSW [STM] x1; REPC STOSB [STM] x1; REPC STOSW [STM] x1; STOSB [STM] x1; STOSW [STM] x1; ... (10 distinct names).

**V35 measured**:
- REP STMW 25 + 9n; single 13 (docs/v35s-eu-timing.md:203)
- CW = 0: 15 (docs/v35s-eu-timing.md:207)
- a6: `STMB [AW=0090 IY=0900]` (STM/STMB/STMW): V35 13 (even 12, odd 14); V30 9 (doc [7]); V35 - V30 = 4
- a6: `STMW [AW=9090 IY=0900]` (STM/STMB/STMW): V35 13 (even 12, odd 14); V30 9 (doc [7]); V35 - V30 = 4
- a6: `STMW [AW=9090 DS0=0000 DS1=0000 IX=0800 IY=0901]` (STM/STMB/STMW): V35 16 (even 15, odd 17); V30 13 (doc [11]); V35 - V30 = 3

**Model steps, register / no-memory form**: `REPNC STOSB [STM]` bytes 64aa, run {'n': 3, 'cond': False}

```
('take', 1)
('nowait', 5{rpre})
('fetch_release', None)
('data', 'write', 0x300, 1, 15{first})
('data', 'write', 0x301, 1, 7{loop})
('data', 'write', 0x302, 1, 7{loop})
('fetch_release', 8{xfetch})
('split_floor', 4{xsplit})
('clocks', 10{rexit+xwb*-1})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `first` | 15 | table | REP string / BCD string: the first element's first cycle setup [C:1490-1494; T:1838, 1699] |
| `loop` | 7 | table | REP string: each later element's first cycle setup; BCD: each later pair's source read; shift_cl: clocks added to exec for a non-zero count [C:1490-1494; T:1220, 1699, 1820] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `rexit` | 12 | rows | REP string exit clocks when CW ran out; mul/div (refresh on): the exec's last clocks run as the loop exit [C:1325-1329, 1494; T:1850, 1133] |
| `rpre` | 5 | rows | REP string: clocks after the opcode's take before the first element [C:1490; T:1830] |
| `setup` | 11 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `ugap` | 0 | table | unprefixed string form: starts no earlier than ugap clocks past the last fetch's delivery (str_single_start) [C:1497-1499; E:245-250, 347-350] |
| `uwb` | 0 | table | string class, unprefixed form: the exec's last uwb clocks are a write-back (str_single_wb=wb/index) [E:351-355; T:1824] |
| `xfetch` | 8 | rows | str_fetch=hold: fetch requests again xfetch clocks after the last cycle [C:1328; T:1843-1844] |
| `xsplit` | 4 | rows | str_split=floor: exit no earlier than xsplit clocks after a split last cycle's second half issue [C:1327-1328; T:1845-1849] |
| `xwb` | 2 | table | string class, REP form: the exit's last xwb clocks are a write-back past the end (str_exit=wb) [E:356-359; T:1850-1852] |
| `zexit` | 10 | rows | REP string with CW = 0: clocks to the end [C:1491; T:1834] |
| `zfetch` | 6 | rows | str_fetch=hold, CW = 0: clocks into the exit at which the aborted start's request is raised again [C:1329; T:1832-1833] |

**V30 counterpart**: 
- work/v30-opcodes.md:101 `AA/AB` STOSB/W (STMB/W), no REP: measured 9 (J269,J270); odd 13 (J271); M:198; routine `STOS` V20UC.TXT L231-235 (ROM 00B8-00BB); toE/total(nb) 3 / 4 (4); flags F:- / W:- / E:00BA / R:-; FARJMP –; JMP –
- work/v30-opcodes.md:102 `REP AA/AB` REP STOSB/W: measured REP STOSW 9+4n (M:201); CX=0 12 (M:204); routine `REP_STOS` V20UC.TXT L236-240, L241-245 (ROM 00BC-00BF, 00C0-00C3); toE/total(nb) no E (exits via FARJMP) / 6 (6); flags F:- / W:- / E:- / R:-; FARJMP REPX; JMP 00BE JMP Z 5 ->00C1; 00C0 JMP REP 3 ->00BF

  Routine `STOS` (work/v30-opcodes.md:594):
```
00B8 dir*sz->tmpc, DI->tmpb; ALU ADD tmpc
00B9 DI->IND; CTL MEMW ES
00BA M->OPR  [E]
00BB SIGMA->DI
```

  Routine `REP_STOS` (work/v30-opcodes.md:605):
```
00BC CX->COUNT, CX->tmpb; ALU PASS tmpb
00BD dir*sz->tmpc, SIGMA->[-03-]; ALU ADD tmpc
00BE M->OPR; JMP Z 5 ->00C1
00BF DI->IND, DI->tmpb; CTL MEMW ES
00C0 SIGMA->DI; JMP REP 3 ->00BF
00C1 COUNT->CX; FARJMP REPX
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `xwb`=2, `xsplit`=4, `xfetch`=8, `zfetch`=6.

## 82. TEST_REG (`V35_CLS_TEST_REG`)

**Forms**: 128 enumerated, opcodes 84, 85. Examples: TEST rm8,r8 (reg) x64; TEST rm16,r16 (reg) x64 (2 distinct names).

**V35 measured**:
- TEST reg,reg 6 although it writes nothing (docs/v35s-eu-timing.md:66)
- TEST AW,AW about 5.5 in a train (docs/v35s-eu-timing.md:103)
- a6: `TEST BW, DW` (TEST reg,reg): V35 6 (even 6, odd 5); V30 2 (doc [2]); V35 - V30 = 4
- a6: `TEST DW, CW` (TEST reg,reg): V35 6 (even 6, odd 5); V30 2 (doc [2]); V35 - V30 = 4

**Model steps, register / no-memory form**: `TEST rm8,r8 (reg)` bytes 84c0

```
('clocks', 3{pre})
('take', 1)
('clocks', 0{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `nx` | 0 | table | hand-off: the next opcode may load into the IR nx clocks after the last operand take (the loader busy that long) [C:1294-1295; E:454; decoder.py:98-111] |
| `pre` | 3 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `pre0` | 4 | table | instead of pre for a form without operand bytes (and the A1/A3 direct forms' head, T:971-974): a format property [C:1290; T:1197-1198] |

**V30 counterpart**: 
- work/v30-opcodes.md:77 `84/85` TEST r/m,r: measured reg,reg 2 (J280,J281); mem 12 (J279); M:140,165; routine `TEST_RM` V20UC.TXT L86-90 (ROM 0044-0047); toE/total(nb) 1 / 2 (2); flags F:- / W:0045 / E:0044 / R:-; FARJMP –; JMP –

  Routine `TEST_RM` (work/v30-opcodes.md:350):
```
0044 M->tmpa, R->tmpb; ALU AND tmpa  [E]
0045 SIGMA->NULL  [W]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: TEST reg,reg costs 3 more than MOV/ADD reg,reg (templates.py:357-359: "the fixed operation's lookup"); the sources name the lookup but no ROM/microcode step for it.

## 83. XLAT (`V35_CLS_XLAT`)

**Forms**: 1 enumerated, opcodes D7. Examples: XLAT [TRANS] x1 (1 distinct names).

**V35 measured**:
- a6: `TRANS [AW=0005 BW=0800]` (TRANS no operand / TRANS src-table / TRANSB no operand): V35 11.5 (even 11, odd 12); V30 9 (doc [9]); V35 - V30 = 2.5

**Model steps, memory form**: `XLAT [TRANS]` bytes d7

```
('clocks', 0{pre})
('data', 'read', 0x105, 1, 7{setup})
('clocks', 2{exec})
```

**Integers** (class value; `table` = a v35_cls_t column, `rows` = folded into the microcode rows; present-at-0 integers listed too):

| Integer | Value | Where | Model's reading |
| --- | --- | --- | --- |
| `exec` | 2 | rows | EU clocks after the operand take / after the last data step (template's exec step); for transfers the clocks before the flush; for I/O OUT the clocks after the post [C:1290-1291, 1300-1302] |
| `pre` | 0 | table | EU clocks before the operand take (the template's first clocks step) [C:1287-1289; T:_steps] |
| `setup` | 7 | table | clocks from posting a data request to its earliest issue (the request's setup) [C:1291-1292] |
| `setup_free` | 3 | table | how many of the last setup clocks must be fetch-free (default all); read as the Request's free_need [C:1292-1293; E:1928] |

**V30 counterpart**: 
- work/v30-opcodes.md:128 `D7` XLAT (TRANS): measured 9 (J290; M:209); routine `XLAT` V20UC.TXT L376-380 (ROM 012C-012F); toE/total(nb) 3 / 3 (3); flags F:012E / W:- / E:012E / R:-; FARJMP –; JMP –

  Routine `XLAT` (work/v30-opcodes.md:853):
```
012C AX->tmpaL, BX->tmpb
012D SIGMA->IND; CTL MEMR
012E OPR->AL  [FE]
```

  FARJMP / internal subroutines are listed in work/v30-opcodes.md:1683-2070 ("Shared FARJMP subroutines"); the EA is not in the ROM (work/v30-opcodes.md:2071).

**Open**: Integers the sources give only as fitted counts (hand-offs, write-backs, holds, gaps, floors, fetch-free counts; config.py's read-off / fitted comments), with no micro-instruction or unit breakdown: `setup_free`=3.
