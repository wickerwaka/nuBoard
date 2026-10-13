# V30 to V35S: differences and work items

This catalogs how the µPD70337 (V35 Software Guard, "V35S") differs from the
µPD70116 (V30), and what each difference means for the model core in
`fpga/v35s/core/`. The model today is the nuV30 ucore (V20 die microcode)
behind a V35 bus shell; see [`v35s-harness.md`](v35s-harness.md).

Sources are tagged:

- **[DB]** NEC 1991 16-bit V-Series data book. Line numbers (L) refer to
  `~/src/nec_test/docs/converted/1991_16_bit_V-Series_Microprocessor_Data_Book.txt`;
  the V35 clock and opcode tables were read from page images (pdf pp 550–554,
  571–574) because the OCR of those tables is unusable.
- **[Si]** measured on the socketed part ([`v35s-bus-timing.md`](v35s-bus-timing.md)).
- **[MAME]** `src/devices/cpu/nec/v25*.cpp`, a hint only.
- **[?]** not stated in the data book or not readable; needs silicon.

The V35S data sheet (L162747–164116) is short. It says the V35S is a V35
with no internal ROM, a 3-state bus cycle, READY sampled in BAW2, and the
BRKS/BRKN security instructions; everything else defers to the V35 sheet.
The V35S shares its core with the V25S (L162577–162579).

## Headline

1. **Instruction timing is different, not just the bus.** The V35 clock table
   is its own (V25-family core), mostly slower than the V30 and with a
   different shape: EA is added separately, shifts cost 2 clocks per bit,
   taken branches cost 15 instead of 14, `MOV reg8,imm` costs 5,
   `DIVU r16` 39 instead of 25, `ROL4 reg` 17 instead of 25. The V20
   microcode cannot be cycle-exact on a V35 by changing the bus unit alone.
   MAME ignores this and uses V30 counts.
2. **The registers live in internal RAM.** All general, pointer, index and
   segment registers are in one of eight 32-byte banks at IDB:E00. Bank
   switching (interrupts, BRKCS, TSKSW, RETRBI) swaps the whole register set
   including the segment registers.
3. **Interrupts are internal.** A priority controller with 17 sources, three
   service modes (vectored, bank switch, macro service), ISPR and FINT
   replaces the V30's INTR/INTA pair (INT/INTAK remains as one source).
4. **8080 emulation is gone** and PSW bits 15:12, 5, 3 and 1 change meaning.
5. **The bus is a different shape** (3-state B1/B2/B3, DRAM row/column
   address, programmable waits, refresh, no status or queue pins). The shell
   already models its shape; the prefetch policy is still the V30's.

## 1. Programmer's model

| Item | V30 | V35S | Source |
| --- | --- | --- | --- |
| Register storage | flip-flops | 8 banks × 32 B in internal RAM at IDB:E00 + 20h·n; reset selects bank 7 | [DB] L103937–104106 |
| Banked registers | — | AW CW DW BW SP BP IX IY **and PS SS DS0 DS1**; PC and PSW are hardware, with save slots in the bank | [DB] L104384–104408 |
| Bank layout | — | +00 reserved, +02 vector PC, +04 PSW save, +06 PC save, +08 DS0, +0A SS, +0C PS, +0E DS1, +10 IY, +12 IX, +14 BP, +16 SP, +18 BW, +1A DW, +1C CW, +1E AW | [DB] L104042–104106 |
| PSW bit 15 | MD (8080 mode) | MD: security mode on V35S (1 normal, 0 secure); write as 1 on V35 | [DB] L163947–163951 |
| PSW 14:12 | fixed 1 | RB2–0, register bank | [DB] L104124–104255 |
| PSW 5 / 3 | fixed 0 | F1 / F0, mirrored in the FLAG SFR (xxFEA) | [DB] L109371–109375 |
| PSW 1 | fixed 1 | BRKI: 0 makes every IN/OUT trap to vector 19 | [DB] L104979–104985 |
| PSW reset | F002 | F002 (MD 1, RB 7, BRKI 1) | [DB] L104254 |
| POP PSW | full | upper 4 bits (MD, RB) unchanged | [DB] L163952–163954 |
| MOV to PSW byte | — | only the low 8 bits | [DB] L163952–163954 |
| RETI | pops PSW | restores RB and MD too | [DB] L104253, L162556–162571 |
| Reset registers | PS FFFF, others 0 | PS FFFF, PC 0, DS0 DS1 SS 0; GPRs undefined (RAM) | [DB] L104215–104223; [Si] AW read 0060 |
| 8080 mode | BRKEM, RETEM, CALLN | removed; behaviour of 0F FF undefined | [DB] L104607–104609 |

MAME disagrees on two points: its POP PSW restores MD, and its RETI does not
restore RB.

## 2. Instructions

### Added

| Instruction | Encoding | Clocks [RAMEN=0] | Operation |
| --- | --- | --- | --- |
| BRKCS reg16 | 0F 2D, 11111rrr | 15 | bank-switch software interrupt to bank reg&7: save PC and PSW in the new bank, RB ← n, IE BRK ← 0, PC ← vector PC |
| TSKSW reg16 | 0F 94, 11111rrr | 20 | save PC/PSW in the current bank, switch to bank reg&7, load PC/PSW from its save slots |
| MOVSPA | 0F 25 | 16 | copy SS and SP of the previous bank (RB in PSW save) into the current bank |
| MOVSPB reg16 | 0F 95, 11111rrr | 11 | copy current SS and SP into bank reg&7 |
| RETRBI | 0F 91 | 12 | PC ← PC save, PSW ← PSW save (returns to the old bank) |
| FINT | 0F 92 | 2 | clear the in-service bit in ISPR |
| BTCLR sfr,bit,disp8 | 0F 9C sfr imm3 disp8 | 29 | if SFR bit set: clear it and branch |
| STOP | 0F 9E | — | stop the oscillator; NMI or RESET exits |
| BRKS imm8 (V35S) | F1 ib | 56+10T [44+10T] | software interrupt, MD ← 0 (secure) |
| BRKN imm8 (V35S) | 63 ib | 56+10T [44+10T] | software interrupt, MD ← 1 (normal) |

"T" in the BRKS/BRKN counts is undefined; the figures match the V25 BRK
column and look copied. [?]

**Collisions with the current ucore:** 0F 25 runs as a 4S-string alias, 0F 2D
decodes like ROL4 into NOP rows, and the 0F 9x opcodes, F1 and 63 have no
V35 meaning in the decode tables.

### Changed or removed

- **FPO escapes (D8–DF, and 66/67):** trap to vector 7 (55+5W) instead of
  executing as no-ops. [DB] pdf p573, p551
- **IN/OUT with BRKI = 0:** trap to vector 19. Whether INM/OUTM trap too is
  [?].
- **HALT:** any unmasked interrupt releases it. With IE = 0 execution resumes
  after the HALT; on the V30 INT with IE = 0 does not wake it. [DB] L108474–108480
- **POLL:** tests P14 every 5 clocks; reads low unless P14 is an input. [DB] L163404–163419
- **Vectored entry** does not set MD (the V30 sets it). [DB] L105090–105100
- **63 and F1:** undefined on V35, BRKN and BRKS on V35S.

### Timing

V35 counts are in CPU clocks (fX/2, /4, /8 per PRC.PCK). EA (3 for mod 00/01,
4 for mod 10) and W (waits from WTC) are added separately. Bracketed values
apply with RAMEN = 0. The table makes no internal-RAM versus external
distinction for operands and no odd-address penalty. [?]

A sample from the comparison (V30 even-address with EA included; V35 with
RAMEN = 1):

| Instruction | V30 | V35 |
| --- | --- | --- |
| MOV reg,mem | 11 | EA+7+W |
| MOV mem,reg | 9 | EA+5+W [EA+2] |
| MOV reg8,imm / reg16,imm | 4 | 5 / 6 |
| INC reg8 / NEG reg | 2 | 5 |
| ADD mem,reg | 16 | EA+10+2W |
| Bcond taken / not | 14 / 4 | 15 / 8 |
| DBNZ taken / not | 13 / 5 | 17 / 8 |
| CALL near / RET | 16 / 15 | 21+W / 19+W |
| PUSH reg / POP reg | 8 / 8 | 13+W / 11+W |
| PUSH R / POP R | 35 / 43 | 74+8W |
| SHL reg,CL | 7+n | 11+2n |
| DIVU r8 / r16 | 19 / 25 | 31 / 39 |
| ROL4 reg | 25 | 17 |
| MOVBKW per element | 8 | 18+2W [10+W] |
| BRK imm8 | 38 | 51+5W |
| RETI | 27 | 40+3W |
| NOP / EI | 3 / 2 | 4 / 12 |

The bracketed write counts often drop W (MOV mem,reg is [EA+2]), which
suggests a write buffer when RAMEN = 0. [?]

Data-book counts are nominal and cannot be trusted alone; the V30's book
counts were also off in places. Silicon decides.

## 3. Memory map and SFRs

- **IDA:** a 4 KB window at xx000–xxFFF with xx = IDB (reset FFh): internal
  RAM at xxE00–xxEFF, SFRs at xxF00–xxFFF. IDB also reads at FFFFF.
  [DB] L103930–104564
- **Instruction fetches** never hit the IDA (reset code at FFFF0 lies in the
  SFR window and is fetched externally). [Si]
- **RAMEN = 0** removes internal RAM from the data address space; it stays
  reachable as registers. What a data access to xxE00–xxEFF does then is [?].
- **Fixed users of internal RAM:** macro-service channels at xxE00–xxE3F and
  DMA channels at xxE00–xxE0F, overlapping banks 0 and 1. [DB] L104578–104589
- **SFRs:** ports P0/P1/P2/PT with PM/PMC, INTM, EMS0–2, EXIC0–2, serial ×2,
  TM0/TM1 with MD0/MD1 and TMC0/1, TMMS0–2, TMIC0–2, DMA ×2, STBC, RFM, WTC,
  FLAG, PRC, TBIC, ISPR, IDB. Reset values are mostly 00h or 47h (interrupt
  control); several are OCR-reconstructed. [DB] Table 6, L108620–109375
- Reserved SFRs read undefined and ignore writes.

The model implements PRC, WTC, RFM and IDB; all other SFRs are plain storage.

## 4. Bus interface

| Item | V30 | V35S | Source |
| --- | --- | --- | --- |
| Address/data | multiplexed AD bus, ALE | separate D15–D0; row/column multiplexed address | [DB] L163652–163664; [Si] |
| Status | S0–S2, QS0/QS1, BUSLOCK | none; MREQ, MSTB, IOSTB, R/W, REFRQ | [DB] L103440–103520 |
| Cycle | T1–T4 | B1 B2 (waits) B3 | [DB]; [Si] |
| Waits | READY only | WTC per 128 KB block plus I/O, 0/1/2/2+READY; reset FFFF | [DB] L108419–108571; [Si] |
| READY | sampled in T3 | sampled mid-BAW2; at least 2 waits when used | [DB] L163436–163440, L163674–163678 |
| Refresh | none | RFM: period 16–128 clocks, 0–2 waits, 9-bit row counter, also in HALT/hold per HLTRF/HLDRF | [DB] L106832–107016; [Si] |
| Queue | 6 bytes, fetch when 2 free | 6 bytes; refill policy [?] | [DB] L103067 |
| Odd word | 2 cycles | 2 cycles, odd byte first | [DB]; [Si] |
| Hold | HOLD/HLDA | HLDRQ/HLDAK on P27/P26, 4.7 kΩ pull-ups while held | [DB] L103560–103566 |
| Interrupt acknowledge | two INTA cycles | INT/INTAK on P14/P13, otherwise internal vectors | [DB] L103567–103585 |

Silicon at reset fetches six words (FFFF0–FFFFA) before the far jump and
five before the first data cycle; the model fetches four in both places.
[Si]

## 5. Interrupts

- **Vectors:** 0 divide, 1 single step, 2 NMI, 3 BRK3, 4 BRKV, 5 CHKIND,
  7 FPO, 12–14 serial 0, 16–18 serial 1, 19 I/O trap, 20–21 DMA, 24–26
  INTP0–2, 28–30 timers, 31 time base. [DB] L105003–105199
- **Priority:** eight software levels per group, fixed order within a group,
  ISPR records levels in service, FINT ends a handler (except NMI and INT).
  [DB] L105221–105675
- **xxIC registers:** IF, MK, MS/INT, ENCS, PR2–0; reset 47h. [DB] L105699–105789
- **Vectored:** push PSW, PS, PC; clear IE and BRK; load PS:PC. 55+5W.
- **Bank switch:** new bank = priority level; save PC/PSW into it; PC ←
  vector PC; no stack. 27 clocks.
- **Macro service:** one SFR↔memory transfer per request through a channel
  block in internal RAM; CPU interrupt at count 0 or character match.
  20–38+W. Mode encodings are unreadable. [?]
- **Latency:** add 27+N for arbitration (18+N for NMI); external requests
  take up to 6 clocks to set IF.
- **NMI:** edge selectable in INTM, releases STOP.
- **V35S:** N/S is sampled at reset and on every interrupt; its level sets
  MD for the handler and RETI/RETRBI restores it. [DB] L163387–163389

## 6. Standby and clock

- **PRC:** PCK fX/2, /4, /8 (reset /8); TB time-base period; RAMEN. Reset 4Eh. [DB]; [Si]
- **HALT:** clocks and peripherals run; see wake rules above. Refresh
  interval in HALT measured at 60 states at fX/2. [Si, unexplained]
- **STOP:** oscillator stops; STBC.SBF survives reset to mark a STOP return.

## 7. Software Guard

- In secure mode (MD = 0) the first opcode byte of each instruction goes
  through a 256-entry mask-programmed table between the queue and the
  decoder; other bytes pass unchanged. No time cost. [DB] L163708–163773
- Whether prefixes and the 0F second byte are translated is [?]; MAME
  translates every opcode-position byte except the 0F second byte.
- The table is per-part and unpublished. Our board holds N/S high (normal
  mode), so extracting it is a separate project.

## 8. Peripherals

Two serial channels with baud generators, two 16-bit timers, a 20-bit time
base, two DMA channels, the comparator port PT, and P0/P1/P2 with alternate
functions. None are in the model.

---

## Work items

Items are grouped by area and roughly ordered by dependency. "Measure" items
use the socket lane; each produces a receipt and a doc entry before the RTL
changes that depend on it.

### A. Measurement (silicon first)

| ID | Item | Why |
| --- | --- | --- |
| A1 | Re-run `characterize` on build 2 (30 ns tick) and replace the build-1 receipt | baseline for everything below |
| A2 | Prefetch policy: queue depth, refill threshold, behaviour on branch, around data cycles and around refresh, at 0 and 2 waits | the V35 bus unit (C1) |
| A3 | Reset exit: time from /RESET to first refresh and first fetch, across x_half and reset length | C2 |
| A4 | Refresh placement while running and in HALT; explain the 60-state HALT interval | C3 |
| A5 | Internal RAM and SFR data access: cost in clocks, RAMEN on/off, what xxE00–xxEFF does with RAMEN = 0, IDB relocation | B2, C4 |
| A6 | Per-instruction clock counts: a directed corpus timing each opcode form against the data-book table (registers, memory, EA modes, waits 0/2, RAMEN 0/1) | D1 |
| A7 | READY: sampling point and minimum waits | C1 |
| A8 | Undefined opcodes: 0F FF, 0F 21/27/34, other 0F holes, 63/F1 with N/S high | D3 |
| A9 | Interrupt entry and exit timing: INTP0 (vectored, bank switch), NMI, INT/INTAK, FINT, latency vs N | E1–E3 |
| A10 | PSW behaviour: POP and MOV masks, BRKI trap, F0/F1 vs FLAG, RETI restoring RB | B3 |

### B. Programmer's model

| ID | Item |
| --- | --- |
| B1 | Remove the 8080 path (MD flop, pages 5/6, BRKEM rows) from the fork |
| B2 | Move GPRs and segment registers into banked internal RAM (or banked flops with RAM aliasing), so data accesses to IDB:E00 see live registers |
| B3 | V35 PSW: RB, BRKI, F0/F1 (linked to FLAG), MD; reset F002; POP/MOV masks; RETI restores all |
| B4 | Reset state per the data book (bank 7, segments) |

### C. Bus unit

| ID | Item |
| --- | --- |
| C1 | V35 bus unit replacing `v30u_biu.sv`: 3-state cycle, 6-byte queue with the measured policy, no T2 freeze in the shell, READY in BAW2 |
| C2 | Reset exit matching A3 |
| C3 | Refresh placement matching A4, including HALT and hold |
| C4 | Internal RAM/SFR access timing matching A5 |
| C5 | HLDRQ/HLDAK bus hold |

Exit criterion for C: `--mode both` (full trace, not `--program-only`) passes
on `smoke`, `clocks` and `alu`.

### D. Execution unit

| ID | Item |
| --- | --- |
| D1 | V35 instruction timing. Decide between (a) a V35 microcode overlay generated alongside the V20 tables, or (b) a per-form timing layer calibrated from A6. Prototype on a few forms before choosing |
| D2 | New instructions: BRKCS, TSKSW, MOVSPA, MOVSPB, RETRBI, FINT, BTCLR, STOP; fix the 0F 25 and 0F 2D collisions |
| D3 | Traps: FPO (vector 7), I/O trap (vector 19), undefined opcodes per A8 |
| D4 | HALT wake rules (IE = 0 resumes) and STOP |
| D5 | POLL on P14 |
| D6 | V35S: BRKS/BRKN, MD handling, N/S sampling on interrupts; translation table as a pass-through hook |

### E. Interrupts

| ID | Item |
| --- | --- |
| E1 | Priority controller: xxIC registers, INTM edges, ISPR, FINT, priority resolution and latency |
| E2 | Vectored and bank-switch entry sequences |
| E3 | INT/INTAK external acknowledge |
| E4 | Macro service |

### F. Peripherals and SFRs

| ID | Item |
| --- | --- |
| F1 | Ports P0/P1/P2/PT with PM/PMC and the harness bank handoff |
| F2 | Time base and TBIC |
| F3 | Timers TM0/TM1 |
| F4 | Serial channels |
| F5 | DMA |
| F6 | STBC and reset-value audit of every SFR |

### G. Harness and verification

| ID | Item |
| --- | --- |
| G1 | Directed corpus in `validation/v35s/programs/` covering each area above, with register dumps to the result region |
| G2 | Vector and fuzz campaigns ported from the 68000 harness |
| G3 | Harness inputs for interrupts: drive INTP0–2, NMI, INT and answer INTAK on a schedule |
| G4 | Run nuV30's SingleStepTests suite on the fork after B and D changes, for the shared 8086 opcodes (function only) |
| G5 | Free block RAM: the scope uses most of it; shrink or make it optional for model builds that need RAM |

### Suggested order

1. A1, A2, A3, A6 (sampled) — establish how far the V30 timing really is
   from silicon.
2. C1–C4 — full-trace match on the existing programs.
3. B1–B4 and D2 — run V35 code that uses banks.
4. D1 — instruction timing, driven by A6.
5. E1–E3 with G3, then D3–D6.
6. F and E4 as programs need them.
