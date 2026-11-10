# The V20/V30 EU machine: what the ROM and the nuV30 ucore show

All paths are under `build/deps/nuV30/`. Short names used in citations:
UC = `docs/V20UC.TXT` (the number is the file line; the 4-digit hex is the micro-address),
PAS = `docs/V20UCDIS.PAS`, BM = `docs/facts/biu_model.md`, MS = `docs/facts/measurements.md`,
PLA = `docs/facts/pla_model.md`, RM = `hdl/rtl/ucore/README.md`, EU = `hdl/rtl/ucore/v30u_eu.sv`,
COND / STEP / ROW / POSTE / TAIL / TPOP / IEND / EA = `hdl/rtl/ucore/v30u_eu_{cond,step,row,poste,arm_tail,arm_tail_pop,arm_instr_end,arm_ea_calc}.svh`,
BIU = `hdl/rtl/ucore/v30u_biu.sv`.

## 1. Registers and fields the ROM names

The micro-instruction is 29 bits, inverted on read (PAS:148): Source1 (5 bits) -> Dest1 (5), Source2 (4) -> Dest2 (2), flags F/W/E (active low), then a type: CTL (Int 4 bits, Ext 3, SR 2), JMP (Cond 4 bits, Loc 0..15) or ALU (Op 5 bits, Tmp 2, R flag) (PAS:29-40, 150-172).

- **Source1** (PAS:50-54): ES CS SS DS PC, OPR, Q, dir*sz, ZEROS, PFXCNT, tmpa tmpb tmpc, FLAGS, AL:AH, COUNT, R, M, SIGMA, ONES, opc&38, CONST, the eight GPRs. **Dest1** (PAS:56-60): the segments, PC, IND, OPR, NULL, AL, AH, tmpa/b/c, FLAGS, COUNT, R, M, tmpaL/tmpbL/tmpaH/tmpbH, the GPRs.
- **Source2** (PAS:62-64): SIGMA, Q, ZEROS, R, the GPRs. **Dest2** (PAS:66-67): tmpa, tmpb, IND only. With Source1 = CONST the second field holds a 6-bit constant (PAS:239-241; e.g. `CONST -> COUNT 16`, UC:475).
- **tmpa / tmpb / tmpc**: the ALU temporaries; an ALU row's Tmp field picks the operand (PAS:75-76). **SIGMA** is the ALU result as a source (EU:1477). ALU ops (PAS:68-72): ADD OR ADC SBB AND SUB XOR CMP, ROL ROR RCL RCR SHL SHR SAR, ROL12, DIV, MUL, ADJD, ADJA, OPC (the opcode's own op), BIT, INC DEC NOT NEG INC2 DEC2, PASS.
- **IND**: the bus address register; **OPR**: the bus data register, read data arrives in it, write data is placed in it (BM:33-37; EU:735-739).
- **Q**: the next prefetch-queue byte, one byte per use (BM:38-39; STEP:291-301).
- **M / R**: the ModR/M operands. M is the r/m operand. For a memory r/m the loader reads it before micro-row 0 (`S_PRERD`, "the pre-decode operand read", STEP:238-279), and a row that writes M back carries Ext `[-06-]`, which the ucore names `E_WRITEBACK` (EU:229-230; e.g. UC:3 `SIGMA -> M ... CTL [-06-]`). R is the reg-field register (e.g. POP r16's `OPR -> R`, UC:15).
- **COUNT**: the counter for `R` rows, `CNTZ` and `REP` (UC:347, 474-475; COND:22-25, 32-39).
- **FLAGS**: the architectural PSW. JMP conditions read a separate ALU status latch (COND:3-4). PSW bits CY P AC Z S BRK IE DIR V (EU:197-198).
- Others: **dir*sz** = +/-1 or +/-2 by DIR and width, the string step (EU:1555). **PFXCNT** = prefix count, read only by REPX's PC rewind (UC:688; EU:1113-1114). **opc&38** = the 8080 RST vector (UC:1195). **ZEROS / ONES** are constants.
- Control fields: Int = ENDEM CITF MFC MFS SUSP FLUSH FARJMP plus unnamed codes (PAS:82-84); the ucore names 4 BCDINIT, 6 CLRCYV, 7 SETCYV, 12 SIGNTGL, 13 BCDNZ (EU:225-228). Ext = MEMR, MEMW, 3 INTATAIL, 5 INTA, 6 WRITEBACK (PAS:86-87; EU:229-230). SR = ES, IO, SS, or the default segment (PAS:89-90). JMP conditions: NC Z NZ OP8b CNTZ L OP8 (always) O NS REP BUSY INTR OPC (PAS:78-80).

## 2. Row structure and the FARJMP subroutines

- The ROM is 257 rows x 4 micro-instructions = 1028 words (PAS:6-8; RM:76). Each 4-word row has a match pattern, printed on the `-------` line (PAS:227-229), of 13 bits `{page[2:0], opc[7:0], rowgrp[1:0]}` (RM:86-96). Pages (PAS:199-212): 0 norep, 1 rep, 2 F6/F7, 3 FE/FF, 4 0F, 5 8080+ED, 6 8080, 7 internal (the FARJMP targets).
- The full micro-address is `{page, opc, loc[3:0]}`. One opcode owns up to four row groups, so up to **16 micro-instructions**, and JMP `Loc` 0..15 addresses inside that block (PAS:39; EU:39-43). `loc` carries into the opcode byte, so a sequence can run off one block into the next (EU:42-43, "IMUL 00B3 -> 0218"; UC:221-225 then 671-675). Most opcodes use a single row, often padded with empty CTL words.
- The group-decode PLA (`pla_3`, 3 x 256 x 14 outputs by `{mode, opcode}`) is separate from the ROM (PLA:13, 34ff; RM:78).
- **FARJMP subroutines** (page 7, `<internal>`; target = Ext:SR, PAS:257-260, 92-96):

| Name | UC lines (addresses) |
|---|---|
| INTEM | 181-185 (0090-0093) |
| IMUL | entry 221-225 (00B0-00B3); body 656-670 (020C-0217); 31 at 671-675 (0218); IMULI 676-680 (021C) |
| IDIV | 521-530 (01A0-01A7) |
| IDIV2 | 531-550 (01A8-01B7) |
| reset (03) | 581-590 (01D0-01D5) |
| 00 (CONST 1 / 2 -> INT) | 591-595 (01D8-01DB) |
| 02 INTA (two banks, ambiguous match) | 596-605 (01DC-01E3); RM:103-111 |
| IRET | 606-615 (01E4-01EB) |
| INT | 616-635 (01EC-01FB), continuing at 636-640 (01FC) |
| MULADJ | 646-650 (0204-0206) |
| MULX | 651-655 (0208-020B) |
| REPX | 681-690 (0220-0227) |
| SHIFT | 691-695 (0228-022B) |
| CALLF | 696-705 (022C-0232) |
| RETF | 706-710 (0234-0237) |
| PUSHA | 716-735 (023C-0248) |
| POPA | 741-760 (0250-025C) |
| ENTER | 766-785 (0264-0273) |
| INS | 1011-1030 (0328-0337); unnamed 71 (EXT) at 1031-1045 (0338-0343) |

## 3. The F / W / E / R flags

- **F** (PAS:11, 155; the legend gives no comment): the F/OPR interlock. "The F-flag / OPR data-ready interlock is the ONLY EU<->BIU bus sync - the EU stalls on OPR reads/writes (`000B OPR->R F`) until the bus transfer completes" (BM:33-37). The ucore splits it by direction: "A row that READS OPR waits for the read that fills it; a row that only LOADS OPR waits only for a store to give OPR back" (EU:735-739). A blocked row performs none of its acts (EU:1915-1916).
- **W** = "write flags" (PAS:12): the row commits the ALU flags to the PSW (POSTE:46; STEP:402).
- **E** = "end of instruction" (PAS:13). See section 4.
- **R** = "repeat ALU instruction" (PAS:14): the ALU row iterates COUNT times, one step per clock (STEP:379-416). The sequencer leaves the R row after the last iteration (STEP:408-413).

## 4. How an instruction ends and the next begins

**In the ROM, exactly one micro-instruction runs after the E row.** Across the ROM the E word is followed by one more word that carries real work, and nothing after it:
- `0006 ... E ALU OPC tmpa` then `0007 SIGMA -> M W` (UC:9-10): the ALU op is on the E row, and its result and flags are written on the row after.
- `0029 SIGMA -> SP SIGMA -> IND E CTL MEMW SS` then `002A M -> OPR` (UC:53-54): PUSH issues its write on the E row and supplies the datum on the row after.
- `007A OPR -> FLAGS F E` then `007B SIGMA -> SP` (UC:154-155); `0272 ... E ALU SUB` then `0273 SIGMA -> SP` (UC:784-785); `0121 tmpa -> AH E ALU PASS` then `0122 SIGMA -> AL W` (UC:363-364).
- E can be on the first word (`0030 E`, UC:62; `034C E`, UC:1057) or on the last word of a row group (`000B OPR -> R F E`, UC:15).

**In the ucore, the successor's opcode pop rides the E row's own clock, before the post-E row.** ROW:233-234: "the successor's opcode pop rides the E row's own clock; a store the pairing latch still owes data defers it to the sequence tail." When no store is pending, the queue byte is ripe and the row does not flush, the E row latches `opc_byte_n = q_byte` and sets `poste` (ROW:257-269). Otherwise the pop is deferred to `S_EPOP` (ROW:270-272; STEP:418-445) or to the tail's `S_TAIL_POP` (TAIL:20-22; TPOP:19-40, "the DEFERRED opcode pre-pop ... M8b: the clock AFTER the pop belongs to the successor's decode").

The post-E row costs no clock of its own. POSTE:4-9: "the E row and the row after it are charged by the SUCCESSOR's decode, which overlaps them ... The post-`E` row therefore costs NO clock of its own but its datapath work is real (`9D`'s `SIGMA -> SP` lives there), and it lands on the clock the successor's first loader step also rides". It "carries no bus cycle and no queue pop" (POSTE:11-12). The successor then starts at `S_TAKE_OPC`, "consume the pre-popped opcode" (EU:487; IEND:46). BM:38-39 says the same from the BIU side: the queue drains one byte per `Q` micro-op "+ the E-flag opcode-fetch boundary". The interrupt boundary is decided at the same point (ROW:244-256). Forms that the pre-decode executes entirely have no E row and retire at the next cold pop (IEND:39-45).

**Answer:** yes. The next opcode is popped before the current instruction's last micro-instruction: on the E row's clock, if the byte is ready and no store still owes its data, or later through `S_EPOP` / `S_TAIL_POP`. Exactly one micro-instruction runs after the E, overlapped with the successor's decode.

## 5. How a bus request is made

The row writes the address into IND (as Dest1 or Dest2) and names the cycle in Ext/SR on the same row: `MEMR` or `MEMW`, with SR = ES, SS, IO or the default segment (PAS:86-90). Data moves through OPR. A read is consumed by a later `OPR -> x` row with F set. A write's datum is placed in OPR on the same row or the next one (UC:18 same row, UC:53-54 next row). IO selects the I/O space for the port and block-I/O opcodes (EU:716-718). The prefetch machinery is not microcoded (BM:23-25). SUSP appears only before FLUSH and on stack reads / INTA (BM:30-32). The ucore gives the EU one request slot (`stall_slot`, EU:28).

Example, POP r16 (58..5F), UC:56-60:
```
002C SP     -> IND                            CTL        MEMR   SS     ; request the stack read
002D SP     -> tmpb                           ALU INC2   tmpb          ; SP+2 in the meantime
002E SIGMA  -> SP                             CTL
002F OPR    -> M                         F E  CTL                      ; wait for the datum; end
```
A store, `A2/A3 MOV [addr],AL/AX` (UC:171-175): two `Q` bytes go into tmpb, then `tmpb -> IND E MEMW`, then the post-E row `M -> OPR` supplies the datum.

## 6. Effective address

**There is no EA routine in the ROM.** No micro-row computes a ModR/M address (UC:1-1285; M simply appears as an operand). The ucore computes the address in the loader, outside the ROM. `S_MODRM` pops the ModR/M byte and branches by mode (STEP:152-168). The adder, `S_EA_CALC`, costs no clock (EA:19-31, 53-57: a base+index table, `[BP]` only when mod != 0, plus the displacement, SS for BP forms). Clocks after the ModR/M pop, from STEP:
- mod=11 (register): straight to `S_BIND`, no EA clock (STEP:164-165).
- mod=00, rm != 110 ([BX+SI], [SI], [BX], ...): one clock, `S_EA_CHG`, "the EA-compute clock" (STEP:163, 219-221).
- disp8 (mod=01): `S_D8_A` (no byte demanded) plus `S_D8_B` (takes the byte): 2 clocks, +1 if the byte was not ripe beforehand (STEP:170-188).
- disp16 (mod=10) and direct (mod=00, rm=110): `S_D16_LO`, `S_D16_A`, `S_D16_HI`: 3 clocks, +1 on the same condition (STEP:159-161, 190-217).
- Then comes the memory operand pre-read (`S_PRERD`), which opens micro-row 0 "at its T4 + 2" (STEP:238-279).

Measured: "modrm EA loads all pay +2" over the manual (MS:176); LDEA [BW+IX] takes 3 and direct takes 5 (MS:335). A per-mode EA clock count measured on silicon is not in the sources.

## 7. Loops: shifts, MUL, DIV, strings

All iterative ALU work uses the `R` row, one step per clock for COUNT steps (STEP:379-416). A taken JMP or FARJMP costs one bubble clock, `S_ROW_CHG` (STEP:373-377; EU:508).

| Operation | ROM loop | per iteration (ROM) | measured V30 |
|---|---|---|---|
| shift/rotate by 1 (D0/D1) | UC:346-350: COUNT=1 (0114), `0116 W R ALU OPC` | 1 R step | 6 total (MS:146) |
| shift by CL / imm8 | UC:351-355, 816-820, then SHIFT UC:691-695: `0228 JMP Z 3` (skip if 0), `0229 W R ALU OPC` | 1 clock per count | 10+n for n>=1; 9 at CL=0 (MS:147-148) |
| MUL/MULU (F6/F7 /4) | UC:471-485: COUNT 8 or 16 (017A/017B), `017C R ALU MUL tmpc` | 1 clock per bit | MULU reg8 24, reg16 31, data-independent; MUL = MULU+10, +4 if the signs differ (MS:108-114) |
| DIV/DIVU (/6) | UC:491-510: COUNT 16 (018A) or 8 (018D), `0190 R ALU DIV tmpc`, then `0191` one more DIV | 1 clock per bit | DIVU reg16 28, wait-insensitive (MS:156; BM:227-228) |
| ROL4/ROR4 | UC:936-955: COUNT 4, `R ALU ROL12` | 1 clock per step | 16 / 20 for reg8 (MS:328) |
| REP STOS | UC:236-243: loop 00BF (MEMW) + `00C0 JMP REP 3` (UC:242) | 2 words + bubble | 9+4n (MS:201) |
| REP MOVS | UC:186-195: loop 0097-009A, `009A JMP REP 3` (UC:194) | 4 words + bubble | 9+8n (MS:202) |
| REP LODS | UC:251-260: loop 00CB-00CE, `00CE JMP REP 3` (UC:259) | 4 words + bubble | not in the sources |
| REP CMPS | UC:206-220: loop 00A7-00AE, `00AE JMP REP 3` (UC:219) | 8 words + bubble | REPE CMPBKW 11+14n (MS:203) |
| REP SCAS | UC:206-210, 271-280: 00A7 then 00D8-00DC, `00DC JMP REP 3` (UC:277) | 6 words + bubble | not in the sources |
| REP INS / OUTS | UC:831-855: `029E` / `02AA JMP REP 3` (UC:839, 854) | 4 words + bubble | not in the sources |
| ADD4S etc. (0F 20/22/26) | UC:896-935: `02DA JMP CNTZ 3` (UC:914) | about 16 words | 13+22n (MS:332) |

REP entry is `CX -> COUNT`, with an early exit by `JMP Z` to `COUNT -> CX FARJMP REPX` (e.g. UC:187-189); with CW=0 it measures 12 (MS:204). The REP condition decrements COUNT. It is taken (loop back) while COUNT != 0 and the Z/CY test holds, and it is forced not-taken on a pending interrupt so the loop can be withdrawn (COND:32-77). REPX (UC:681-690) tests `JMP Z 4` / `JMP INTR 5`; on an interrupt it rewinds PC by PFXCNT and flushes (0225-0227). The string slopes are bus-bound (one 4-clock bus cycle per access, so 4 or 8 per element), and the REP slopes match the manual exactly (MS:220-221). The ROM gives MUL 8 more R steps for reg16 than for reg8, but the measured difference is 7 clocks (24 vs 31); the sources read here do not reconcile this.

## 8. BIU laws (BM) and the five ucore stalls

- **Queue**: 6 bytes; no fetch is started at depth >= 5; refill starts when 2 bytes are free, so the second pop from full restarts fetching (BM:10-15, 826-829). Fetches are words at even addresses; after a jump to an odd target the first fetch is one byte (BM:16, 78-79).
- **Fetch length**: a bus cycle is T1 T2 T3 (Tw x N) T4, so 4+N clocks (BM:817-818, 225-226). A fetched byte is poppable at the eval instant + 3 (BIU:40-43).
- **Arbitration**: an EU access never preempts an in-flight prefetch. It wins the next bus-cycle boundary, with a gap of 0 after the fetch's T4 (BM:167-168, 832-834).
- **Resume after an EU access**: prefetch resumes after 3 idle cycles at w0 (11 cycles per write = 4 MEMW + 4 CODE + 3 idle) (BM:169-171). Under waits the resume depends on phase and is an open item (BM:842-860).
- **The reservation leads the request**: a pending EU request must hold a reservation one grid slot before it is ready. Without it a fresh prefetch takes the T4 slot and the store lands about 4 cycles late (BM:200-210, 834-838). A reg-EA read becomes ready one cycle after its EA settles (BM:178).
- **Flush**: EU-deterministic per opcode (26 FLUSH micro-ops at fixed addresses). A doomed in-flight fetch completes and its data is discarded (BM:26-29, 49-72, 868-874).
- **EU compute is wait-insensitive**; F/OPR is the only coupling (BM:35-37, 227-228, 878-881).

The ucore EU's five stalls (EU:24-30). Each one re-enters the state and withholds its acts:
- `stall_q`: a queue byte is demanded and not yet ripe (M8).
- `stall_opr`: the F / OPR interlock (11.4/M13).
- `stall_slot`: the EU's one bus-request slot is busy (M10).
- `stall_retire`: the retire deadline; a store still owes its data (7.7).
- `stall_pin`: the 1BL retire lead, or a halted part (S9a).
