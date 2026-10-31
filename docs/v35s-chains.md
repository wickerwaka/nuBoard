# V35S instruction chains: bus, queue, decoder and EU timing

A fresh measurement of the socketed µPD70337's bus behaviour, built on the
[harness](v35s-harness.md) but independent of the earlier probe windows
(`timing.py`, `probes.py`) and of the cycle model in `validation/v35s/model/`.
The code is `validation/v35s/chains/`; the data is frozen in the corpus as
`chains-<family>-w<N>`.

## Method

Every run executes one straight-line chain from reset. Nothing in a chain
changes the PC. The chain is

    [PAD] LS  body  LS  END

- **LS** is `MOV CL,31 ; SHL AW,CL` (`B1 1F D3 E0`): about 70 clocks with no
  bus cycle of its own, so the prefetch queue fills and the bus goes idle. The
  state at the end of the first LS is the reference point: queue full, bus idle,
  the prelude's clock change and arbitrary queue history erased.
- **PAD** is a NOP placed *before* the first LS when needed, so the first body
  byte sits at the requested parity (even or odd linear address). The PAD runs
  before the LS, so its execution leaves no trace after the fill.
- **Markers** `M0..M3` are `OUT 20h+i,AL` (two bytes, one I/O write whose port
  identifies it). `PUSH AW` and `MOV [0C00h],AW` are alternative markers used in
  the marker-control family.
- **END** is `MOV DW,0FF00h ; OUT DW,AW ; HALT` plus 16 NOPs (`BA 00 FF EF F4`: EF is
  the word form; the record called it `OUT DW,AL` up to the fifteenth fit and the
  catalog's name for EF, `out_dw_al`, stands), so the pass write
  ends the run and prefetch past HALT reads real bytes.

Code is at segment 1000h (linear 10000h), data at 0800h–0FFFh in segment 0, the
stack at 0E00h–0F00h, so every bus cycle is classified by its address: a read in
the code page is a fetch, anything below 1000h is data. Refresh is off (RFM ECh)
except in the refresh family; the clock is fX/2 with X1 = 8.33 MHz, so one CPU
clock is 8 scope ticks and a zero-wait bus cycle is 3 clocks. WTC 0000h, 5555h
and AAAAh give 0, 1 and 2 waits.

Register presets: BW=0800h (0801h for odd-operand variants), BP=0A00h,
IX=0100h, IY=0180h, DS0=DS1=SS=0, SP=0F00h, AW=1234h, DW=5678h.

### Families

| Family | Body | Question |
| --- | --- | --- |
| F0 | nothing; `LS`; `NOP LS` | fetch cadence, cycle length per wait setting, words fetched past LS before idle, fence history-independence |
| F0w | `M0` with one WTC field set at a time | which WTC field governs block-0 memory and which I/O |
| F1 | 1, 2 or 4 markers of each kind | marker cost, marker latency after the fence, marker collisions with the restart fetch |
| F2 | `X M0`, X of 0–6 bytes | when the first post-idle fetch restarts against the bytes the decoder has taken |
| F3 | `M0 X^k M1`, register-only X, k ∈ {1,2,4} | per-class EU cost (slope) and opcode-take overlap (intercept) |
| F4 | `M0 X M1`, loads in all 24 ModR/M modes | EA cost structure, read issue point, read-to-use latency |
| F5 | `M0 X M1`, stores, read-modify-write, PUSH/POP mem, stack, I/O, load+ALU | write issue point, read-then-write spacing, odd-word split, I/O vs memory |
| F6 | `M0 D^n X M1`, drainer D = `MOV r,imm16` | fetch-vs-data arbitration as the queue empties; the starved regime |
| F7 | `M0 A B M1` over a 6×6 grid | neighbour interactions; held back as a zero-parameter validation set |
| F8 | `M0 X^4 M1` with refresh on | refresh insertion and priority |
| F9 | `X M0` and marker-less `X`, 34 groups X of NOPs, 2/3/4-byte register forms and prefixes | the restart fetch and the refill to idle as a function of the bytes taken and how they are grouped (added after the second fit) |
| F10 | `M0 P X M1`, X ∈ {`OUT DW,AW` (EF, the catalog's `out_dw_al`), `IN AL,DW`}, 15 predecessors P that write DW, write another register in the same format, read DW, or put distance after the DW write; marker-less `P X` for three P | what makes the END block's `OUT DW,AL` one clock later than a free-standing one (added after the seventh fit) |
| F11 | marker-less `NOP^n X`, n = 0..5, X ∈ {`MOV AW,DW`, `MOV AW,imm16`, `ADD DW,imm16`, `MOV AW,DW` twice} | the phase of an operand take against the fetch cadence behind the 3-clock wait of finding 4 (added after the seventh fit) |
| F12 | series A `M0 NOP^n X OUT`, n = 0..3, X ∈ {∅, `MOV AW,DW`, `SHL AW,1`, `MOV AW,imm16`}, M0 = OUT or PUSH, plus the PUSH twin; series B marker-less `NOP^n X`, n = 2, 3, X ∈ {`ADD DW,imm16`, `ADD AW,imm16` (81 C0), `ES: MOV AW,imm16`, `SHL AW,4`}, and `M0 X M1` for the two 81 forms | the OUT after a register form at 0 waits (the F7 companion) and the 4-byte `ADD DW,imm16` fetch delay (added after the eighth fit) |
| F13 | refresh on: S marker-less `LS (MOV CL,n ; SHL AW,CL) LS`, n = 1..31; S0 the same with refresh off for n ∈ {1, 2, 4, 8, 16, 31}; C the cost frame with the same X, n ∈ {0..8, 12, 16, 24, 31}, PUSH and OUT; U `MULU DW` k = 1, 2 under both markers and marker-less; N `NOP^8` marker-less and PUSH; R the empty marker-less frame at RFM F0h, F4h, F8h, FCh, FDh, FEh, FFh | the EU side of refresh: the stall per refresh against the shift's loop phase, whether it generalises to MULU, the markers across the timer phase, the RFM interval and cycle-length fields (added after the ninth fit) |
| F14 | T a format ladder at [BW] under PUSH k = 1, 2 and OUT k = 1: `ADD`/`CMP`/`TEST`/`XCH`/`MOV` in both directions, word and byte, `TEST [BW],imm16`, `ADD [BW],imm16`, `NOT`/`NEG`/`INC [BW]`, `TEST`/`XCH` direct, four marker-less; G the group memory forms `MULU`/`DIVU`/`POP`/`PUSH`/`SHL ,1`/`SHL ,CL`/`INC`/`NOT [BW]` and `MULU AW` at k = 1, 2, PUSH and OUT; O the OUT frame and its PUSH twin over `MOV AW,DW`, its pairs with NOP and itself, `XCH AW,DW`, `MOV AW,imm16`, `ADD AW,DW`, `SHL AW,1`, `SHL AW,4`, NOP, ∅, and four marker-less shifts | which format property silicon keys on for the TEST and XCH delays (finding 2), the group memory forms (5), the OUT after a register form and the marker-less shift (4, 9) (added after the ninth fit) |
| F15 | A the AND control and the rest of the TEST ladder (`AND`/`OR`/`XOR`/`SUB` at [BW] in both directions, `AND`/`TEST`/`CMP [BW],imm16`, `AND`/`ADD [BW],imm8`, direct `TEST`/`AND`/`CMP`, `TEST AL/AW,imm`), PUSH and OUT frames and marker-less; P `POP [BW]` and `PUSH [BW]` at k = 1..3 under PUSH, OUT and marker-less, POP in direct, [BW+d8] and [IX] modes, `POP AW`/`POP CW`, the PUSH/POP pairs and NOP neighbours; K the pairs `X ; X`, `X ; NOP ; X`, `X ; INC [BW]`, `INC [BW] ; X`, `X ; MOV AW,DW` for X ∈ {`MULU [BW]`, `SHL [BW],1`, `PUSH [BW]`, `NOT [BW]`}; O the OUT frame and twin over `MOV AW,DW` pairs with NOP, itself and memory forms, `SHL AW,1`, `MULU AW` and their NOP pairs, and marker-less shifts with and without NOP | the AND control for the TEST reading, TEST imm's extra clocks, `POP [BW]`'s stack read and held fetch, the early second instance at k = 2, the OUT-frame remainder (added after the tenth fit) |
| F16 | R the reg-field ladder under PUSH at k = 2: `X ; X` and `INC [BW] ; X` for X over D1 /0–/7 (`ROL`/`ROR`/`RCL`/`RCR`/`SHL`/`SHR`/`SAR [BW],1`), F7 /0–/7 (`TEST [BW],imm16`, `NOT`, `NEG`, `MULU`, `MUL`, `DIVU`, `DIV [BW]`), FF /0, /1, /6 (`INC`, `DEC`, `PUSH [BW]`), the byte forms `SHL [BW]b,1` and `MULU [BW]b`, and the new forms alone at k = 1; P `NOP^n ; POP [BW]` and `NOP^n ; POP AW`, n = 0..3 under PUSH and marker-less, 0..2 under OUT, plus `POP [BW+d8]` and `POP [0C00h]` under PUSH; L the OUT frame and its PUSH twin over `SHL AW,1`, `MOV CL,n ; SHL AW,CL` and `SHL AW,n` for n ∈ {1, 2, 4, 8}, `MULU AW`, `MULU DW`, `DIVU IX`, `NOP ; MULU AW`, `NOP NOP ; MULU AW`, `MULU AW ; NOP`; S marker-less `NOP^n ; SHL AW,m`, `NOP^n ; MOV CL,m ; SHL AW,CL`, `MOV CL,m ; NOP^n ; SHL AW,CL` for n = 0..3, m ∈ {1, 2, 4, 8, 16}, and `NOP^n ; MOV CL,4` alone | whether the early second instance is a reg-field bit or an operation unit, `POP [BW]`'s held fetch against the fetch phase, the long register forms after the OUT marker, and what the marker-less shift's missing fetch is tied to (added after the eleventh fit) |
| F17 | refresh turned on by the chain after the fill, the prelude at RFM ECh: RFMON = `DS1: MOV byte [0FFE1h],imm8` (`26 C6 06 E1 FF ii`, DS1 = F000h); S `LS RFMON(FCh) NOP^n X LS END`, n = 0..3, X ∈ {∅, `MOV CL,m ; SHL AW,CL` for m ∈ {1, 2, 4, 8, 16, 31}, `MULU DW`, `NOP^8`, `MOV AW,[BW]`, `MOV [BW],AW`, `ADD [BW],AW`, `OUT 20h,AL`}; E the same writing ECh (refresh stays off); D writing FDh (RFT 1) for four X; W `LS NOP^n RFMON LS END`, n = 0..7, with FCh, FDh and ECh (the write itself moved); C the PUSH cost frame `LS RFMON M0 X M1 LS END` for six X; P the S chain with refresh on from the prelude for five X, n = 0, 1 | the refresh timer's phase as an observable (restart on the write or free-running; its value at clock 0), the SFR store's own cost, RFEN's delay, the EU side with the first LS exact (added after the thirteenth fit) |
| F18 | the prelude closed by a marker (`Chain.prelude_marker`: `PUSH AW` = 50 or `OUT 20h,AL` = E6 20 directly after the prelude's `MOV AW,1234h`, both leaving the chain's first byte in the word at 10048h): A `[marker] PAD LS X LS END` under prelude RFM ECh (control), FCh and FDh, X ∈ {∅, `MOV CL,m ; SHL AW,CL` for m ∈ {4, 16, 31}, `MULU DW`, `NOP^8`, `MOV AW,[BW]`, `MOV [BW],AW`}; AC the ECh prelude with the marker and `LS RFMON(FCh) LS END`; B `PAD LS RFMON(FCh) [ES: NOP] NOP^n X LS END`, n = 0..7, X ∈ {`MOV CL,4 ; SHL AW,CL`, `MOV CL,16 ; SHL AW,CL`, `SHL AW,4`, `SHL AW,1`, `MULU DW`, `DIVU IX`, `SHL [BW],CL`} (the `ES: NOP`, 7 clocks, steps the request 3 clocks where a NOP steps it 4); BD the same writing FDh for two X | the first LS's start under a refresh-on prelude against a known clock; the refresh request placed at every exec clock of the unit forms (finding 8 a and b of the fourteenth fit) |
| F19 | I: the immediate memory forms `MOV [BW],imm16` (C7 07), `MOV byte [BW],imm8` (C6 07), `MOV [BW+10h],imm16` (C7 47), `MOV [BW+200h],imm16` (C7 87), `CMP [BW],imm16` (81 /7), `ADD [BW],imm16` (81 /0), `CMP [BW],imm8` (83 /7) behind a lead-in of none, `NOP^1..3` or `ES: NOP`, PUSH and OUT frames at k = 1 (k = 2 with no lead-in) and marker-less; D: `OUT DW,AL` (EE), `OUT DW,AW` (EF), `IN AL,DW` (EC), `IN AW,DW` (ED) after a register form of 1–4 bytes (none, `NOP`, `XCH AW,DW`, `MOV DW,AW`, `MOV AW,DW`, `MOV CW,AW`, `MOV AW,imm16`, `ADD DW,0`, `SHL AW,1`, `MOV CL,imm8`), with one NOP between for the 2–4-byte forms, after itself and after `OUT 40h,AL`; PUSH, OUT and marker-less; AW = DW = 0040h | the immediate's fetch alignment against the write's issue (findings 1 and 3 of the fifteenth fit: the immediate's width, the displacement, the I/O ahead's kind and the queue count behind a DW form) |
| F20 | R: a lead-in of none, `NOP`, `NOP NOP` or `ES: NOP`, then a register form P of 1–4 bytes whose last byte is its opcode, a ModR/M or an immediate (none, `NOP`, `XCH AW,DW`, `MOV AW,DW`, `MOV DW,AW`, `MOV AW,imm16`, `ADD AW,imm16`, `ADD DW,0`, `ES: NOP`, `ES: MOV AW,DW`, `ES: MOV AW,imm16`), then X ∈ {`MOV AW,[BW]`, `MOV [BW],AW`, `ADD [BW],AW`, `OUT DW,AL` (EE), `OUT 40h,AL`, `MOV AW,DW`}; the OUT frame with every X and lead, PUSH at three leads without the RMW, marker-less at two; N: the F6 drain frame `M0 D^n P X M1` for five P and four X, OUT n = 1, 2 and PUSH n = 1; AW = DW = 0040h | finding 4 of the sixteenth fit: the state separating the 4-byte form's extra fetch, the 2-byte forms on the I/O issue clock, the F6 `n1` drains and the `MOV AW,DW` pairs from F4's loads (P's length and last byte against X's ModR/M, the frame, the alignment, the stored count at X's start) |
| F21 | the EA path: five consumers of a ModR/M memory operand, `MOV AW,r/m` (8B), `MOV r/m,AW` (89), `MOV r/m,imm16` (C7 /0), `ADD r/m,AW` (01) and `POP r/m` (8F /0), in seven modes [BW], [BW+10h], [BW+200h], [BW+IX], [BW+IX+10h], [BW+IX+200h] and [0C00h] (mod 00 rm 110), behind a lead-in of none, `NOP`, `NOP NOP`, `NOP NOP NOP` or `ES: NOP`; PUSH and OUT frames at every lead, marker-less at none, NOP, NOP NOP and ES: NOP; k = 2 with no lead for the five displaced modes in both frames; the load in [IX+10h], [IX+200h], [BP+IY+10h] and [BP+IY+200h] as controls | the EA cost structure the seventeenth fit's one-value table could not carry: the mode class against the displacement width, the d16's second byte against its alignment (the ModR/M's word-mate or a straddle), the immediate forms' displacement order, and the consumer |
| F22 | the immediate forms' post against the fetch run: the immediate RMW `ADD r/m,imm16` (81 /0) at [BW+200h], [BW+10h], [BW] and [0C00h], `ADD [BW+200h],imm8` (83 /0), the left-out write `CMP [BW+200h],imm16` (81 /7), `TEST [BW+200h],imm16` (F7 /0) and the immediate store `MOV r/m,imm16` (C7 /0) in the same four modes as the controls, behind the F21 lead-ins (none, `NOP`, `NOP NOP`, `NOP NOP NOP`, `ES: NOP`); PUSH, OUT and marker-less frames at every lead; k = 1 and 2; 0 and 1 waits only | item 1's three runs: whether the read of an immediate RMW and the write of an immediate store differ in the same counted state, the one-byte immediate's group setup against the delivery clock, and TEST imm with a displacement, which the corpus had never held |
| F23 | control flow inside the chain (acquired 2026-10-27; modelled and fitted 2026-10-28, the thirty-fifth fit, 255/360; the fortieth, 2026-10-30, 303/360; the forty-first, 2026-10-30, 333/360): the cost frame under PUSH and OUT with flags made known by `CMP AW,AW` (3B C0); taken `BE +n ; NOP^n` (74 n) and `BR short +n ; NOP^n` (EB n) for n = 0..7 (the NOPs are chain bytes that never run, knob `skipped`), `BR near +n` (E9 n 00) for n = 0..3; not-taken `BNE +n` (75 n) at n = 0 (k = 1, 2) and 2; `MOV CW,1 ; DBNZ +0` (not taken), `MOV CW,2 ; DBNZ +n` for n = 0, 2 (taken once); `CALL +0` (E8 00 00) and the pair `CALL +2 ; BR +1 ; RET` (run in the order 0, 2, 1); controls the empty frame and `CMP AW,AW` alone; 60 variants, 360 runs | the queue flush and the fetch of a branch target: bytes discarded, the restart word and its alignment (both target parities appear over n and the pad), the bytes the decoder needs before the EU resumes, the near CALL's stack write against the flush, the not-taken cost |
| F25 | EA without a bus cycle and the stack frame (acquired 2026-10-27; modelled and fitted the same day, the thirty-fourth fit, 446/588; the fortieth, 2026-10-30, 534/588; the forty-first, 2026-10-30, 569/588): `LDEA AW,r/m` (8D /0) in all 24 modes, k = 2 for [BW], [BW+10h], [BW+200h], [BW+IX], [BW+IX+10h] and [0C00h]; `XLAT` (D7, a byte read at BW+AL = 0800h since the fence leaves AW = 0); `PUSH imm16` (68) and `PUSH imm8` (6A) at k = 1, 2; `PUSH R` (60), `PUSH R ; POP R` (61, eight stack words each); `PREPARE 0,0` (C8 00 00 00) and `PREPARE 0,0 ; DISPOSE` (C9); `PUSH DS1`/`PUSH DS1 ; POP DS1` (06, 07), `PUSH DS0`/`PUSH DS0 ; POP DS0` (1E, 1F), `PUSH PS` (0E), `MOV DS1,AW` (8E C0), `MOV AW,DS1` (8C C0), `MOV DS1,[BW]` (8E 07) and `MOV [BW],DS0` (8C 1F); DS0, SS and PS are never loaded from memory or with an unknown value; the empty frame as control; 98 variants, 588 runs | the EA table on its own, separated from the read it has always been bundled with; stack bursts of eight words through the arbiter; the segment write-back; the immediate push |
| F26 | the refresh-off probe family (generator WP56, acquired 2026-10-28; 906/906 under the thirty-fifth fit; 151 variants, 906 runs; ids `F26-<push|out>-<series>-<label>-n<n>[-k<k>]-p<E|O>-w<N>`): the cost frame `M0 NOP^n X^k M1` for five rules the rule register (docs/v35s-chain-rtl-spec.md) found pinned by one or two cells, each as a ladder that puts the deciding state in many cells: `pi` (`port_issue`: `M0 OUT 40h,AL NOP^n X OUT 40h,AL M1`, X ∈ {∅, XCH AW,DW, MOV AW,DW, ADD AW,DW, MOV CL,imm8}, n = 0..3, and `M0 NOP^n X OUT 40h,AL M1`), `fib` (`free_idle_b2b`: `MOV [BW+IX+200h],imm16` at k = 1..3, NOP^1..2 before the k = 2 pair, the k = 2 comparison forms [BW+200h], [BW+IX], [BW+IX+10h]), `gih` (`grp_io_hold`: INC, NOT, SHL ,1, NEG, DEC [BW] and the controls TEST [0C00h],AW, TEST [BW],AW after NOP^0..2 under OUT, PUSH at n = 0), `dio` (`disp_io`: six load modes after NOP^0..3 under OUT), `lks` (`lookup_start`: TEST [0C00h],AW at k = 1, 2 after NOP^0..2 and k = 3, controls TEST [BW],AW and TEST [BW+200h],AW), `cnt` (the C0/C1 count mask: `SHL AW,n` for n = 31, 32, 33, 255 and `MOV CL,n ; SHL AW,CL` for n = 32, 255); the empty frame per marker | which alternative of each rule silicon takes, in cells the corpus never had; whether the shift count byte is masked |
| F27 | the refresh-on probe family (WP56, acquired 2026-10-28; 646/1,072 read under the thirty-fourth fit, modelled and fitted the same day, the thirty-sixth fit, 778/1,072, then 889/1,072 under the thirty-seventh; RFM FCh at every wait with an ECh twin of every variant at 0 waits; 134 variants per RFM, 804 + 268 = 1,072 runs; ids `F27-<push|out>-<fc|ec>-<series>-<label>-n<n>[-k<k>]-p<E|O>-w<N>`): `room` (`room_ir_imm`: `MOV AW,imm16`^k and `MOV DW,imm16`^k, k = 1..4, against `MOV CL,imm8`^k, k = 1..4, and `ADD DW,imm16`^k, k = 1..3), `unit` (`refresh_drop_unit`: `SHL AW,CL` by 4, 8, 16, `MULU DW`, `SHL AW,8`, each after NOP^0..2), `port` (`refresh_drop_post`, `refresh_lead_port`: `OUT 40h,AL`, `OUT 40h,AW`, `IN AL,40h` after NOP^0..5, `OUT DW,AL` and `IN AL,DW` at n = 0, 2, 4), `beat` (`refresh_beat_t4`: `MOV DS1,AW ; MOV AW,imm16` and `MOV AW,DW ; MOV DW,imm16` after NOP^0..5); the empty frame per marker and RFM | the five refresh-side rules' alternatives in the chain body; the refresh-on model's coverage outside the corpus's cells |
| F28 | the refresh-on probe family for the thirty-sixth fit's open states (WP59, acquired 2026-10-28; 573/1,088 under the thirty-sixth fit, 820/1,088 under the thirty-seventh, fitted the same day; RFM FCh at every wait with an ECh twin of every variant at 0 waits; 136 variants per RFM, 816 + 272 = 1,088 runs; ids `F28-<push|out>-<fc|ec>-<series>-<label>-n<n>[-k<k>]-p<E|O>-w<N>`): `fence` (the empty frame with the fence's count CL = 24..30, each count moving M0's OUT two clocks against the free-running refresh timer; 31 is the empty frame), `tail` (NOP^n then a register unit then `OUT 40h,AL` at once: `SHL AW,CL` by 8, 16, 24, 31 at n = 0..5, `SHL AW,8` and `MULU DW` at n = 0, 2, 4; `OUT 40h,AW` and `OUT DW,AL` (EE) behind the count-31 shift at n = 0, 2, 4), `beat` (OUT marker only: NOP^n, n = 0..3, then `MOV AW,imm16`^k, `MOV DW,imm16`^k or `ADD DW,imm16`^k, k = 1..4) | the M0 OUT at pO w2 state (the refresh at a unit's exit before an OUT) swept over the refresh phase; the beaten 3-clock fetch's successor against the decoder's state on its delivery clock |
| F29 | the refresh-off probe family for F26's open reads (WP59, acquired 2026-10-28; 309/456 under the thirty-sixth fit, 427/456 under the thirty-seventh, fitted the same day; RFM ECh at every wait; 76 variants, 456 runs; ids `F29-<push|out>-ec-<series>-<label>-n<n>-p<E|O>-w<N>`): `dio` (OUT marker: NOP^n, n = 0..3, then the stores `MOV [BW+10h],AW`, `MOV [BW+200h],AW`, `MOV [0C00h],AW` and the control `MOV [BW+IX+200h],AW`; the `dw` cells `OUT DW,AL` right after M0 then those stores and the four loads, the displacement take on the DW OUT's issue clock at pO), `gih` (OUT marker: NOP^n, n = 0..2, then INC, NOT, SHL ,1, NEG, DEC `[BW+200h]`; the `dw` cells with those five and the controls `TEST [0C00h],AW`, `TEST [BW+200h],AW`), `pi` (both markers: `OUT 40h,AL NOP^n X OUT 40h,AL` with X = `MOV AW,imm16`, `ADD DW,imm16`, n = 0..3; `NOP^n OUT OUT`, n = 0..5) | `disp_io` in the other mode classes, `grp_io_hold` for the plain group forms, `port_issue` deciding cells |
| F30 | the facts-only shapes' probe family (WP73, acquired 2026-10-30; 909/1,476 under the thirty-ninth fit, 959/1,476 under the fortieth; modelled 2026-10-30, the forty-first fit, 1,349/1,476; RFM ECh; 246 variants, 1,476 runs; ids `F30-<out|push|store>-<probe>-<label>-p<E|O>-w<N>`): `str` (OUT: `MOV CW,n ; REP INM/OUTM/STM` for n = 0, 1, 2 word and n = 1 byte, behind leads l0, a drainer `MOV AW,1234h` or `ADD DW,0` before `MOV CW,n`, one or two NOPs or `SHL AW,8` between `MOV CW,n` and the REP form), `odd` (OUT: every REP form with IX or IY odd alone, MOVBK/CMPBK both odd, n = 1, 2; STM-iy, INM-iy, MOVBK-iy, CMPBK-ixiy, LDM-ix, CMPM-iy followed by NOP, `MOV AW,DW`, `MOV AW,[BW]`, or `MOV CW,1` and the same REP form), `seg` (OUT and PUSH: 8E with DS1/SS/DS0 from AW and [IX], DS1 also from [BW]; 8C with DS1/PS/SS/DS0 to AW and to [BW]; a NOP before the 8E forms and `MOV [BW],DS1/DS0`; k = 2 for the 8E register forms; `PUSH SS ; POP SS`), `br` (OUT: BR short +0..3 and BR near +0/+1 behind a NOP, BR short +0/+1 with one or two NOPs before M0, BR short +0; MOV-direct marker: BR short +0..3 and +0 behind a NOP), `nt` (OUT and PUSH: `CMP AW,AW ; BNE +0` × k `; NOP^n`, `MOV CW,1 ; DBNZ +0 ; NOP^n` and the pair twice), `cr` (OUT and PUSH: `CALL +2 ; BR +(a+1) ; NOP^a ; RET ; NOP^b` for (a, b) = (0,0), (1,0), (2,0), (0,1), (0,2), and `SHL AW,8` in place of the NOPs), `lea` (OUT and PUSH: LDEA behind a NOP in six modes, followed by a NOP and alone in [BW], [BW+200h], [0C00h], k = 2 in [BP+200h] and [BW+IX+200h], [BW] behind D and D4) | the mechanism behind each facts-only shape of the thirty-ninth and fortieth fits: the fetch wait clock the INM/OUTM setup absorbs, the split last cycle's exit at w0, 8E behind the OUT and the sreg store, the odd-address BR short's fetch, BNE/DBNZ not taken, the RET's refill, LDEA's d16 |
| F31 | F30's two controls (WP73 follow-up, acquired 2026-10-30; 66/234 under the thirty-ninth and fortieth fits; the forty-first, 2026-10-30, 234/234; RFM ECh; OUT marker, the F24 presets; 39 variants, 234 runs; ids `F31-out-<alf|lone>-<label>-p<E|O>-w<N>`): `alf` (REP STM, INM, MOVBK, REPE CMPBK, LDM, REPNE CMPM, word, IX and IY even, n = 1, followed by NOP, `MOV AW,DW`, `MOV AW,[BW]` or, for the non-compares, `MOV CW,1` and the same REP form; STM also n = 2 with NOP and the second REP form; STM and LDM with nothing after), `lone` (REP INM, OUTM, STM, word, n = 1, behind `NOP^b ; MOV CW,1 ; NOP^a` for (b, a) = (1, 4), (0, 5), (0, 4), (2, 4), leads that put one refill fetch, not back to back, inside the REP setup) | whether the string exit's late next fetch with a follower needs an odd operand (it does not), and whether any fetch in the REP setup gives INM/OUTM their one-clock gain (only the post-M0 back-to-back refill run does) |
| F32 | the 0F page (WP74, acquired 2026-10-30, read as facts; modelled 2026-10-30, WP78, the forty-second fit, 379/858; RFM ECh; OUT marker, a PUSH subset; 143 variants, 858 runs; ids `F32-<out|push>-<form>[-n<n>]-k<k>-p<E|O>-w<N>`): `bit` (TEST1 / CLR1 / SET1 / NOT1, 0F 10-1F, on AL / AW and at [BW], byte and word, the index in CL (31, masked to bit 7 / 15) and as imm3 / imm4, k = 1, 2), `mode` (SET1 [m],CL word at [BW+10h], [BW+200h], [BW+IX], [0C00h]), `bcd` (MOV CL,n ; ADD4S / SUB4S / CMP4S, 0F 20 / 22 / 26, IX 0A40h to IY 0C40h, n = 2, 4, 8, 16 digits, k = 2 at n = 2, 4; MOV CL,n alone as controls), `rot4` (ROL4 / ROR4, 0F 28 / 2A, on DL and at [BW]), `bitfield` (EXT / INS, 0F 33 / 31 register width and 0F 3B / 39 imm4, offsets BL 0, DL 8, BH 8 and widths DH 6, BH 8, BL 0 with DW = 0608h, seven (offset, width) cases within, at the boundary and crossing, k = 1, 2), `pfx` (DS1: before TEST1 [BW],CL, SET1 [BW],7, ROL4 [BW], ADD4S) | the 0F page's costs and cycles before the decoder learns it: the bit ops as register / load_alu / rmw shapes (the CL forms ~2 clocks before the EA), the BCD strings' byte-element loop (30 / 25 per pair, every cycle's waits in it), the rotates' ALU span, the bit fields' (offset, width) span and IX / IY step, and the undocumented: offset / width registers with bits 4-7 set run hundreds of clocks longer |
| F33 | the register miscellany and REPC / REPNC (WP74, acquired 2026-10-30, read as facts; modelled 2026-10-30, WP78, the forty-second fit, 841/1,050; RFM ECh; OUT marker, a PUSH subset; 175 variants, 1,050 runs; ids `F33-<out|push>-<label>-p<E|O>-w<N>`): `incdec` (INC / DEC r16 for every register, k = 1, 2, 4; INC / DEC AL, DH and byte / word [BW], k = 1, 2), `adjust` (ADJ4A, ADJ4S, ADJBA, ADJBS), `convert` (CVTBD, CVTDB), `extend` (CVTBW, CVTWL at AW = 0 and behind MOV AW,8080h), `muldiv` (MUL CW, MUL [BW], DIV / DIVU CW and [BW] behind MOV AW,1234h ; MOV DW,0, no trap; MUL CW / [BW] at AW = 0), `mulimm` (MUL AW,CW / [BW],imm16 (69) and imm8 (6B)), `flag` (CLC STC CMC CLI STI CLD STD), each k = 1, 2; `rep` (STC or CLC ; MOV CW,n ; REPC / REPNC CMPM / CMPBK word, n = 1, 2, 4, IX 0A40h, IY 0C40h: the carry exit after element 1 against CW running out; the patterns [0C42h] = 0 / [0A42h] = 0 for an exit after element 2, n = 2, 4; n = 0; controls) | the HDL plan's Phase E item 5 classes against the existing ones: INC / DEC r16, CVTBW and the flags at 3 clocks (one less than NOP), INC r8 = MOV r8,imm8, the adjust / convert / multiply / divide spans, EI's ~10 extra clocks; REPC / REPNC = REPE / REPNE with CY for Z, cell for cell against F24 |
| F34 | the forty-second fit's miss shapes' probe family (WP80, acquired 2026-10-30, read as facts; 469/1,596 under the forty-second fit, 958/1,596 under the forty-third; RFM ECh; OUT marker, a PUSH subset; 266 variants, 1,596 runs; ids `F34-<out|push>-<probe>-<label>-p<E|O>-w<N>`): the leads l0, `nop`/`nop2`/`nop3` (NOP^1..3), `d`/`d2`/`d3` (`MOV AW,1234h`^1..3), `sep` (`SHL AW,8`), `cl` (`MOV CL,4`), each alone as a control; `bf` (EXT/INS BL,DH and DL,BH (register width, within and crossing) and BL,7 and DL,11 (imm4), DW = 0608h, behind l0, nop, nop2, d, sep at k = 1, k = 2 behind a NOP, the within-word forms followed by NOP, `MOV AW,DW` or `MOV AW,[0C00h]`), `rbit` (SET1 AL/AW by CL and imm behind l0, nop, nop2, d, sep, k = 2 behind l0 and nop, the pair with a NOP between, the CL forms behind `MOV CL,4`; TEST1 AW,CL as the op control), `mbit` (TEST1/SET1/CLR1 [BW],CL and SET1/CLR1 [BW],15 word behind the five leads, k = 2 and the pair with a NOP between; SET1 [m],CL in [BW+10h], [BW+200h], [BW+IX], [0C00h] behind l0, nop, d; SET1 [BW],CL byte), `inc` (`INC AW`^k `; NOP`^n, k = 1..4, n = 0..2, behind a NOP at n = 0; `CLC`^k `; NOP`^n, k = 1, 2, n = 0, 1), `mul` (MUL AW,[BW],5 and AW,[BW],1234h behind the five leads, k = 2 behind l0 and nop; MUL AW,CW,5), `nt` (`CMP AW,AW ; BNE +0`, `MOV CW,1 ; DBNZ +0`, `CMP AW,DW ; BE +0` (not taken; CMP AW,DW, 3B C2, the one new byte string) and the twin `CMP AW,AW ; MOV AW,DW` behind l0, d, d2, d3, nop, nop2, nop3; BE twice), `cr` (`CALL +2 ; BR +(f+1) ; <filler> ; RET` behind l0 or a NOP (the RET's target at either parity), the filler none, NOP, `SHL AW,8`, `SHL AW,8 ; NOP`, `NOP ; SHL AW,8`, `SHL AW,4`) | per miss shape one thing varied against a control: the bit fields' read is 6 (imm4 7) clocks after the last fetch's end behind every lead, EXT = INS, crossing = within; the register bit ops' +7 is a back-to-back fetch on a page form's word-ending last byte, and a 0F at an even address behind a lead takes its fetch a clock before the model; the memory bit ops read on one clock for every op (the model's classes split it by 3); INC/CLC's -1/-4 only with M1's OUT directly after; MUL imm memory's read a clock per immediate byte late, no fetch for the multiply when the immediate ends a word's first byte; BE not taken = BNE not taken, both 2 longer than modelled, DBNZ at an odd address holding prefetch 5 clocks; the RET's -1 is the shift before it, not its target's parity |
| F24 | the string and block forms (WP66, acquired 2026-10-28; modelled and fitted 2026-10-29, the thirty-eighth fit, 746/912; the thirty-ninth, 2026-10-30, 778/912; the forty-first, 2026-10-30, 868/912): MOVBK (A4/A5), CMPBK (A6/A7), STM (AA/AB), LDM (AC/AD), CMPM (AE/AF), INM (6C/6D), OUTM (6E/6F), byte and word, under the OUT marker and the cost frame, with IX = 0A40h (source), IY = 0C40h (destination) and DW = 0040h (the port) as register presets, DS0 = DS1 = 0, DIR clear, AW = 0 after the fence; series `s` (unprefixed singles, k = 1, 2), `r` (`MOV CW,n` then REP STM/MOVBK/LDM/INM/OUTM, REPNE CMPM, REPE CMPBK for n = 0, 1, 2, 3, 4, 8, and 16 for STM w and MOVBK w; `MOV CW,n` alone as controls), `a` (IX and/or IY odd, n = 1, 2, 4), `t` (REPE/REPNE compares exiting on the fill after one element or over a stored pattern `MOV word [0C42h],0` after two (word) or three (byte) elements, n = 2, 4), `d` (drainers before `MOV CW,4 ; REP STM/MOVBK w`, d = 0, 2, 4); 152 variants, 912 runs; ids `F24-out-<series>-[<rep>-]<op>-<b|w>-(k<k>|n<n>)[-ix|iy|ixiy|-fill|-pat|-d<d>]-p<E|O>-w<N>` | the per-element cadence of a bus stream that takes no queue bytes, the REP setup and exit, the n = 0 check, the compares' termination, the odd split per element, the I/O-plus-memory element |
| F35 | control flow completed (WP87, generated and acquired 2026-10-31, 1,044 runs, every repeat equal, refresh off; modelled the same day, WP88, the forty-fifth fit, 922/1,044; the cost frame under OUT and PUSH markers, 174 variants, 1,044 runs; ids `F35-<out|push>-<series>-<label>-p<E|O>-w<N>`): `ctl` (the empty frame and three flag controls: `cmpaa` CMP AW,AW with Z = 1, CY = 0, S = 0, V = 0, P = 1; `cmpad` CMP AW,DW, AW being 0 after the fence, so Z = 0, CY = 1, S = 1, V = 0, P = 1; `adddw` ADD DW,2A01h giving 8079h: Z = 0, CY = 0, S = 1, V = 1, P = 0), `cc` (all sixteen short conditional branches 70–7F, each taken and not taken at +0 and +2 with the control that decides it: `adddw`/`cmpaa` for BV BH BPO BGT, `cmpaa`/`adddw` for BNV BNH BPE BLE, `cmpad`/`cmpaa` for BC BNE BN BLT, `cmpaa`/`cmpad` for BNC BE BP BGE; the PUSH frame at +0 only), `cw` (BCWZ taken after MOV CW,0 at +0/+2 and not taken after MOV CW,1; DBNZE E1 and DBNZNE E0 at CW = 1 and 2 under `cmpaa` and `cmpad`), `loop` (MOV CW,2 then NOP or MOV AW,DW then DBNZ back over it: the body runs twice, a backward taken transfer), `ret` (CALL +2 ; BR +3 ; RET 0 and, after PUSH AW, RET 2: RET imm16 against F23's RET), `ind` (MOV BW,target ; CALL BW to the next instruction and to a RET; BR BW to the next instruction and over a NOP; MOV BW,0800h the control), `far` (BR far EA to the next instruction and over a NOP, CALL far 9A to the next instruction, CALL far ; BR +1 ; RETF, and after PUSH AW CALL far ; BR +3 ; RETF 2). Absolute targets are code offsets 51h–56h built per parity (the prelude is a constant 71 bytes, checked at generation), PS = 1000h. Left out: memory-indirect transfers (the data fill is 9090h), BRK and RETI (no vector hook in the image) | whether every condition costs what BE/BNE cost; CW-tested transfers against DBNZ; re-execution from a backward transfer's refill; RET imm16; register-indirect and far transfers (two stack words, the PS reload) |
| F36 | the data forms no family had run (WP87, generated and acquired 2026-10-31, 750 runs, every repeat equal, refresh off; modelled the same day, WP88, the forty-fifth fit, 747/750; 125 variants, 750 runs, k = 1; ids `F36-<out|push>-<series>-<label>-p<E|O>-w<N>`): `mov` (MOV AL,[0C00h] A0 and MOV [0C00h],AL A2; MOV r8,12h for AL DL BL AH CH DH BH; MOV BW/BP/IX/IY,preset BB BD–BF; MOV SP,0F00h under OUT only), `shift` (SHL AL,CL and SHL byte [BW],CL, CL = 31), `test` (TEST DL,AL 84 C2), `xch` (XCH AW,r for 91 93 95–97 and 94 SP under OUT only), `stack` (PUSH r 51–57; PUSH r ; POP r for CW DW BW BP IX IY; PUSH SP ; POP SP under OUT only; PUSH PSW ; POP PSW as a pair), `alu` (OR ADDC SUBC AND SUB XOR AW,DW 0B 13 1B 23 2B 33; the same six and CMP with AW,1234h 0D 15 1D 25 2D 35 3D; ADD and CMP byte [BW],5 as 80 /0, 80 /7 and the 82 alias), `psw` (LAHF; LAHF ; SAHF, AH the PSW's low byte so BRKI stays set), `lock` (BUSLOCK MOV AW,DW and BUSLOCK ADD [BW],AW with the unprefixed controls), `ptr` (LES AW,[IX] C4 and LDS AW,[IX] C5 with IX = 0100h: the pointer sits in the zeroed vector table, so offset and segment load 0000h; C4 loads DS1 and C5 DS0). Already in the corpus and not repeated: the word strings (F24), INC/DEC r16 (F33), IN AW,DW (F19). With F35 the two families add 76 first bytes to the catalog. New classes (WP88, from the facts): `bcwz`, `dbnz_z`, `ret_imm`, `call_reg`, `br_reg`, `branch_far`, `call_far`, `ret_far`, `ret_far_imm`, `load_ptr`, `pop_psw`, `test_reg`; every other register, immediate and stack variant decodes to the class it measured equal to (PUSH PSW the push class, LAHF/SAHF the flag class) | the class-equivalence assumption on every register, immediate and stack variant; the byte direct moves, byte shifts by CL, BUSLOCK, the PSW forms and the pointer loads |
| F37 | memory-indirect transfers, BRK and RETI through words the chain writes (WP90, generated and acquired 2026-10-31, 432 runs, every repeat equal, refresh off; modelled the same day, WP91, 420/432 under its candidate; the cost frame under OUT and PUSH markers, 72 variants, 432 runs, k = 1; ids `F37-<out|push>-<series>-<label>-p<E|O>-w<N>`): the lead `MOV AW,imm16 ; MOV [d16],AW` writes any word in page 0 because DS0 = 0, so a pointer word goes to the data area (0C00h, with 1000h at 0C02h for a far pointer) and a vector to the zeroed interrupt table (BRK 3 at 0Ch/0Eh, BRK 5 at 14h/16h); every cell's baseline is its lead alone (`ctl`: one word, two words, each vector pair, with and without a NOP after the stores, and MOV BW,0C00h before them; all existing imm and store classes). `indm` (CALL near [0C00h] FF 16 to the next instruction, to a RET via CALL ; BR +1 ; RET, and after a NOP; BR near [0C00h] FF 26 to the next instruction, over a NOP and after a NOP; the same through [BW] with BW = 0C00h, FF 17 / FF 27), `farm` (BR far [0C00h] FF 2E to the next instruction, over a NOP and after a NOP; CALL far [0C00h] FF 1E to the next instruction and to a RETF; the [BW] forms FF 1F / FF 2F), `brk` (BRK 3 CC and BRK 5 CD 05: BRK ; BR +1 ; RETI, the handler NOP ; RETI with the exec order recorded, and the BRK after a NOP; PSW 0002h from the prelude keeps MD and RB, IE = 0). Absolute targets are code offsets 56h–61h built per parity. New classes (WP91): `call_mem`, `br_mem`, `call_far_mem`, `branch_far_mem`, `brk`, `reti`. Left out: a handler directly after its BRK (RETI would run twice), a handler or RET placed before its BRK or CALL (the normaliser walks stack cycles in chain order), CHKIND, FPO1, POLL, BRKV, a pointer at an odd address | the memory-indirect transfers against F35's register-indirect and far forms (the pointer read(s) before the stack words, direct vs base EA, a store followed at once by the read of the same word); BRK's three pushes and vector reads, RETI's three pops, BRK 3 against BRK imm8 |

Each chain runs at 0, 1 and 2 memory waits (WTC 0000h, 0001h, 0002h; I/O
stays at 0 waits) and at both parities. F2–F8 are generated twice, with
`PUSH AW` markers and with `OUT` markers, so every cost has a cross-check:
3,404 chains in all, about ten minutes of board time at 0.18 s per run. F9
(PUSH marker and marker-less only) adds 408 runs: 3,812 in all. F10 (PUSH
marker and marker-less, AW = DW = 0040h preset) adds 204 and F11
(marker-less) 132, recorded 2026-10-19: 4,148 in all. F12 (204 runs, 42
of which reproduce F3 and F11 traces exactly) brings it to 4,352. F13
(462 runs, refresh on except its S0 control, 0.2 s per run) brings it to
4,814, F14 (732 runs, 2026-10-20) to 5,546, F15 (840 runs,
2026-10-20) to 6,386, F16 (1,014 runs, 2026-10-20) to 7,400, F17
(798 runs, 150 of them refresh-off controls, 2026-10-21) to 8,198 and
F18 (1,164 runs, 96 of them refresh-off controls, 2026-10-21) to 9,362
F19 (1,290 runs, 2026-10-21) to 10,652, F20 (3,594 runs,
2026-10-21) to 14,246, F21 (3,576 runs, 2026-10-21) to 17,822, F22
(1,320 runs, 2026-10-23) to 19,142, F23 (360 runs, 2026-10-27) to 19,502,
F25 (588 runs, 2026-10-27) to 20,090, F26 (906 runs, 2026-10-28) to 20,996 and
F27 (1,072 runs, 268 of them refresh-off controls, 2026-10-28) to 22,068, F28
(1,088 runs, 272 of them refresh-off controls, 2026-10-28) to 23,156 and F29
(456 runs, refresh off, 2026-10-28) to 23,612.
Parity is that of the first body byte after the fence; with the 1-byte PUSH
marker the instruction after M0 therefore sits at the other parity, and each
PUSH lowers SP by 2, so stack forms behind a PUSH marker use 0EFEh downward.

### Measurements

The cost of a body X is the marker interval `ΔM(X) = t(M1) − t(M0)` minus the
interval of the empty body at the same parity and waits. Three independent
handles put the EU on the bus and must agree: the markers; the restart of
fetching after the fence (F2), which only the decoder taking bytes can cause;
and the starved regime (F6), where fetch arrivals pace the EU.

## Facts

Clocks are CPU clocks at fX/2 (8 ticks). Corpus entries are named in brackets.

### Bus and WTC (F0, F0w, 2026-10-17)

- **Cycle length:** 3, 4 and 5 clocks at 0, 1 and 2 waits, for fetches, data
  and I/O alike; back-to-back fetches start 3, 4 and 5 clocks apart.
- **WTC fields:** bits 1:0 govern memory in block 0 (code at 10000h and data at
  0800h both), bits 15:14 govern I/O. No other field changes either. The sweep
  therefore runs memory waits with I/O held at 0 waits (WTC 0001h, 0002h), so a
  marker's bus occupancy is the same at every wait setting. [chains-F0w]
- **Fence:** after the long shift's bytes, three more words are fetched and
  then the bus idles for 78 clocks at 0 waits (both parities), after which
  fetching restarts back to back. The run-to-run tick phase of a trace differs
  by half a clock (reset phase), so every alignment is to the first chain
  fetch, never to absolute ticks. Repeats of 11 chains were identical up to
  that constant offset. [chains-F0-w0..w2]

### Markers (F1, 2026-10-17; recorded with I/O waits equal to memory waits)

Clocks from the fence fill (end of the last fetch before the idle gap).

| Marker | First marker starts | Interval between markers |
| --- | --- | --- |
| `PUSH AW` (1 byte, stack write) | 77 / 78 / 79 at 0 / 1 / 2 waits, both parities | 9 at 0 waits, 10 at 1 wait, 11–12 alternating at 2 waits |
| `MOV [0C00h],AW` (3 bytes) | 77 / 79 / 81 | 9 at 0 waits; 11–12 at 1 wait, 13–15 at 2 waits |
| `OUT 20h+i,AL` (2 bytes, I/O) | 83–84 / 85–86 / 87–88 | 10–12 at 0 waits, 12–14 at 1 wait, 14–16 at 2 waits |

- The PUSH marker's write goes out before fetching restarts after the fence
  (write at 77, first fetch at 80 or later), so its position reads the EU
  directly. Its interval does not depend on parity.
- OUT's interval varies with how its two queue bytes meet the refill, so it is
  the noisier marker. The cost-frame families are run with both kinds, PUSH as
  the primary and OUT as a cross-check. [chains-F1-w0..w2]

### Release after the fence (F2, 2026-10-17)

With `LS X M0 LS`, the first fetch after the idle gap comes a fixed time after
the fill, independent of the wait setting (the bus is idle, so only the EU
decides). At even parity it is 72 clocks after the fill for X = NOP, NOP NOP,
NOP×3, MOV AW,DW, DS1: NOP, ADD DW,imm16 and the prefixed MOV AW,imm16 forms,
but 76 for MOV AW,imm16 alone, 77 for an OUT marker and 81 for a PUSH marker
directly after the fence. At odd parity the same bodies give 72 to 76, with a
single NOP at 79–85. So the slot release is not "first byte taken", nor a
plain byte count; the model has to produce these from the decoder and EU
structure. [chains-F2-w0..w2]

### Register-only costs (F3, preliminary, PUSH marker, even parity, 0 waits)

cost(X^k) = ΔM(X^k) − ΔM(empty), clocks:

| X | k=1 | k=2 | k=4 | Reading |
| --- | --- | --- | --- | --- |
| NOP, XCH AW,DW | 4 | 8 | 16 | 4 per instruction, no overlap |
| MOV/ADD AW,DW (2 bytes) | 3 | 9 | 15 | not linear: 2 bytes per 3 clocks meets the fetch rate |
| MOV CL,imm8 | 6 | 12 | 24 | 6 |
| MOV/ADD AW,imm16 | 7 | 14 | 28 | 7 |
| ADD DW,imm16 (4 bytes) | 7 | 17 | 31 | bus-bound at k ≥ 2 |
| SHL AW,1 | 10 | 20 | 40 | 10 |
| MOV CL,n ; SHL AW,CL | 16 (n=0), 18+2n (n ≥ 1) | ×2 | ×4 | shift alone 10 / 12+2n; exactly linear |
| SHL AW,4 (C1) | 20 | 40 | 80 | 20 |
| MULU DW | 35 | 69 | 137 | 34 each, +1 once |
| segment prefix | +3 per prefix at 0 waits | | | grows with waits: 6-byte forms starve |

Wait states raise the cost of byte-hungry trains (MOV AW,imm16: 7 / 8 / 10 at
0 / 1 / 2 waits; three prefixes + MOV AW,imm16: 16 / 20 / 23) but not of NOP
trains until 2 waits, and not of shifts at all beyond a constant. The OUT
marker reads the same costs within ±1 except where its own fetch interleaving
intrudes. [chains-F3-w0..w2]

### Loads by addressing mode (F4, preliminary, PUSH marker, 0 waits)

cost of one `MOV AW,r/m16` load, even / odd parity:

| Mode | Bytes | Cost |
| --- | --- | --- |
| [BW], [IX], [IY], [BW+IX], [BP+IY] and every other mod 00 form | 2 | 11 / 10 |
| every disp8 form (mod 01) | 3 | 11 / 11 |
| every disp16 form with base+index (mod 10) | 4 | 13 / 12 |
| [IX+d16], [IY+d16], [BP+d16], [BW+d16], direct `8B 06` | 4 | 14 / 11 |
| `A1 disp16` (short direct) | 3 | 11 / 12 |
| byte load `8A 07` | 2 | 11 / 10 |
| `MOV AW,[BW]` with BW odd (split word) | 2 | 14 / 13 |
| two loads back to back (k=2) | | 22 / 20: additive |

Effective-address arithmetic costs nothing measurable: base, index and
base+index forms are identical. The cost follows the bytes consumed (a fourth
byte costs 2–3 more) and the operand's bus cycles (an odd word operand costs
exactly one more 3-clock cycle). Each wait state adds 2–3 clocks to a load,
more than its own data cycle's single wait, so the fetches around it are on
the path. The OUT marker reads 1–3 clocks higher but the same shape.
[chains-F4-w0..w2]

### Read/write orders (F5, preliminary, PUSH marker, even parity, 0 waits)

Every data, stack and I/O cycle in all 3,200 runs recorded so far matches the
list the chain predicts, by kind and address, in program order, including the
split cycles of odd-address words. Costs of one instruction:

| Class | Form | Cost | Note |
| --- | --- | --- | --- |
| load + ALU | ADD AW,[BW]; CMP AW,[BW] | 11 | same as a plain load |
| load + ALU | TEST [BW],AW | 13 | |
| read + imm, no write | CMP [BW],imm16 | 15 | |
| load + multiply | MULU [BW] | 40 | MULU DW is 34 |
| store | MOV [BW],AW; MOV [BW],AL; MOV [0C00h],AW | 9 | a store is 2 cheaper than a load |
| store + imm | MOV [BW],imm16 (4 bytes) | 10 | 6-byte form 13 |
| read-modify-write | ADD [BW],AW | 14 | |
| read-modify-write | INC [BW]; NOT [BW]; XCH [BW],AW | 16 | |
| read-modify-write | SHL [BW],1 | 22 | |
| read-modify-write + imm | ADD [BW],imm16 | 15 | 6-byte form 18 |
| read A, write B | PUSH word [BW] | 20 | POP word [BW] 17 |
| stack | PUSH AW 9; POP AW 11 | | |
| I/O | OUT imm,AL 11; IN AL,imm 16; OUT DW,AW (EF) 7; IN AL,DW 12 | | |
| odd word operand | +3 per split access | | RMW on an odd word: +6 |

Where the data cycle lands after the marker: at even parity X's first data
cycle comes after two fetches, at odd after one; the 4-byte displacement forms
need one more fetch first; PUSH AW, POP AW and IN AL,DW at odd parity go out
with no fetch in between. The OUT marker agrees with PUSH within 3 clocks
everywhere; the larger gaps are where the PUSH write itself competes with X's
cycles for the bus. [chains-F5-w0..w2]

### Arbitration while the queue drains (F6, preliminary, PUSH marker)

Body `M0 D^n X M1`, D = `MOV AW,imm16` / `MOV DW,imm16` alternating (3 bytes,
7 clocks at a full queue). Cost of the body against n = 0, even parity:

| n | 0 waits | 1 wait | 2 waits |
| --- | --- | --- | --- |
| 1 | 6 | 6 | 7 |
| 2 | 13 | 14 | 17 |
| 4 | 27 | 30 | 36 |
| 6 | 41 | 46 | 55 |

- At 0 waits each drainer costs 7, as alone: 3 bytes per 7 clocks is slower
  than the fetch supply of 2 bytes per 3 clocks, so the queue never empties.
- At 2 waits the supply is 2 bytes per 5 clocks and the drainers cost about
  2.3 clocks more each: the EU is waiting for bytes. At 1 wait the extra is
  under 1 clock per drainer. The 4-byte drainer `ADD DW,imm16` already costs
  1.5 extra per instruction at 0 waits.
- X's data cycle (load, store, RMW, I/O) always comes after every fetch that
  the drainers need and directly before the closing marker's write, at every
  n and wait setting; the fetch stream is never broken by X's request before
  the drainers are done. The same costs hold for every X within ±1.
- The slope in n, from n = 2 to 6, is 7 / 8 / 9.5 clocks per drainer at 0 / 1
  / 2 waits for every X and both markers (the 4-byte drainer: 7 / 8 / 10). A
  purely byte-starved EU would run at the supply rate, 4.5 / 6 / 7.5 clocks
  per 3-byte drainer; the measured slope stays above the EU's own 7 and rises
  less than the supply slows, so at waits the EU is waiting on something other
  than raw byte count.
- For n ≥ 2, X's first data cycle starts 13 / 15 / 18 clocks after the end of
  the fetch that delivered X's last byte (17 / 19 / 22 when that byte is the
  second of its word). [chains-F6-w0..w2]

### Neighbour pairs (F7, PUSH marker, 0 waits)

interaction(a, b) = ΔM(a b) − ΔM(a) − ΔM(b) + ΔM(empty), singles from F3/F4/F5
under the same frame (their empties agree in every column):

| a \ b (even chain) | load | store | RMW | PUSH AW | OUT | MOV AW,DW |
| --- | --- | --- | --- | --- | --- | --- |
| load | 0 | −1 | −1 | 0 | 2 | 0 |
| store | 0 | −1 | −1 | 0 | 1 | 0 |
| RMW | 0 | −1 | −1 | 0 | 1 | 0 |
| PUSH AW | −1 | −1 | −1 | 0 | 0 | 0 |
| OUT | 0 | −1 | −1 | 0 | 2 | 0 |
| MOV AW,DW | 2 | 2 | 2 | 0 | 0 | 3 |

At odd chain parity the matrix is 0 everywhere except 1 for PUSH AW or OUT
followed by a memory form and for load followed by OUT. With the OUT marker
the interactions run −3 to 0 instead. So from a full queue the costs compose
additively to within a clock or three; this family is the zero-parameter
validation set for the model. [chains-F7-w0..w2]

### Refresh (F8, RFM FCh; read in full 2026-10-19)

A refresh cycle is 5 clocks at every wait setting and is recorded one tick
before the clock edge. With refresh on, the empty frame's own ΔM varies
from 9 to 15 with where refreshes fall, so F8 costs carry placement noise
and are left for the model, which places refreshes itself.
[chains-F8-w0..w2]

| Fact | Evidence (clocks after t_fill) |
| --- | --- |
| a refresh cycle is 5 clocks at every WTC setting; the memory waits do not apply | w0 284×5, w1 304×5, w2 324×5 |
| the row address goes up by 200h per refresh and never skips | 864 of 864 refresh pairs |
| the period is 16 CPU clocks on a free-running grid, not counted in bus cycles | in the shift's idle the gaps alternate 15/17 around 16.0 (w0: 15×40, 16×4, 17×32, 18×4); w1 and w2 give the same clocks (1 16 31 48 63 80) though their cycles are 4 and 5 clocks; timing from the previous cycle's start or end would give a constant gap |
| the 15/17 alternation comes from the EU, not the bus | odd idle gaps (64 of 515) occur only at the ends of the long shift; with nothing on the bus `out-empty-pE-w0` takes the request at 87 and `push-empty-pE-w0` at 89 |
| a refresh stalls the long shift, about 3 clocks per refresh | the M0 PUSH write lands at 94/101/101/101/92 (pE w0, pO w0, w1, pE w2, pO w2) against 78 with refresh off; the second LS lengthens too |
| a NOP train is barely stalled | `push-nop-k4-pO-w0`: ΔM 26 against 25 with refresh off |
| a refresh waits for a free bus, then beats a pending fetch | 149 refreshes start on the clock right after a fetch ends; `push-nop-k4-pO-w0`: X112 F117 |
| a refresh beats a data write that becomes issuable on the same clock | `push-empty-pE-w0` X103 W108; `pE-w1` X111 W116 |
| a fetch request raised on the clock a refresh takes the bus can be lost | `push-empty-pO-w1`: X128, then no fetch until 217 while the second shift runs without it |
| the timer's phase at the fill is fixed per parity × waits cell | first refresh after the fill: pE w0 +7, every other cell +1 (blocked behind the fill fetch) |

### Release series (F9, 2026-10-17)

`PAD LS X M0 LS END` with a PUSH marker and `PAD LS X LS END` with none,
34 groups X. All 408 traces complete and refresh-free; 42 repeats
identical up to the reset phase; the PUSH runs reproduce F2's restart
clocks where the two overlap. Each cell below is the restart fetch's clock
after the fill and the number of fetches from the restart to the next idle.
Restart clocks and fetch counts are the same at 0, 1 and 2 waits except the
three cells where the PUSH write comes before the restart (+1 per wait).
[chains-F9-w0..w2]

| X | PUSH even | PUSH odd | none even | none odd |
| --- | --- | --- | --- | --- |
| empty | 81/82/83 · 3 | 84/85/86 · 2 | 75 · 2 | 75 · 2 |
| NOP×1 | 72 · 3 | 85/86/87 · 3 | 72 · 3 | 79 · 2 |
| NOP×2 | 72 · 4 | 76 · 3 | 72 · 3 | 76 · 3 |
| NOP×3 | 72 · 4 | 76 · 4 | 72 · 4 | 76 · 3 |
| NOP×4 | 72 · 5 | 76 · 4 | 72 · 4 | 76 · 4 |
| NOP×8 | 72 · 7 | 76 · 6 | 72 · 6 | 76 · 6 |
| `8B C2` | 72 · 4 | 72 · 3 | 72 · 3 | 72 · 3 |
| `8B C2` NOP×n (n=1..4) | 72 · 4,5,5,6 | 72 · 4,4,5,5 | 72 · 4,4,5,5 | 72 · 3,4,4,5 |
| NOP `8B C2` | 72 · 4 | 76 · 4 | 72 · 4 | 76 · 3 |
| `8B C2 8B C2` | 72 · 5 | 72 · 4 | 72 · 4 | 72 · 4 |
| `B8 ii ii` NOP×n (n=0..3) | 76 · 4,5,5,6 | 76 · 4,4,5,5 | 76 · 4,4,5,5 | 76 · 3,4,4,5 |
| NOP `B8 ii ii` | 72 · 5 | 80 · 4 | 72 · 4 | 80 · 4 |
| `26` | 72 · 3 | 83/84/85 · 3 | 72 · 3 | 77 · 2 |
| `26` NOP×n (n=1..3) | 72 · 4,4,5 | 74 · 3,4,4 | 72 · 3,4,4 | 74 · 3,3,4 |
| `26 8B C2` | 72 · 4 | 74 · 4 | 72 · 4 | 74 · 3 |
| `26 B8 ii ii` | 72 · 5 | 78 · 4 | 72 · 4 | 78 · 4 |
| `26 2E 36 B8 ii ii` | 72 · 6 | 74 · 5 | 72 · 5 | 74 · 5 |
| `81 C2 ii ii` | 72 · 5 | 76 · 4 | 72 · 4 | 76 · 4 |

Readings: at even parity every X whose first byte is taken at 72 restarts
at 72 (the queue was one byte short of a word after the fill, and the first
take frees it); `MOV AW,imm16` first restarts at 76, when its immediate
commits, not when its opcode leaves. At odd parity the restart waits for
two bytes to go: 76 for NOP NOP, 74 for prefix+NOP, 72 only when a 2-byte
instruction takes its ModR/M byte. One extra fetch per two bytes taken, and
the PUSH marker's own two bytes add one.

### OUT DW predecessors (F10, 2026-10-19)

X's I/O cycle relative to t(M0), silicon, columns pE w0/w1/w2 then pO
w0/w1/w2; where IN differs from OUT the IN cell is in brackets.

| P | OUT DW,AW, EF (IN AL,DW) |
| --- | --- |
| none | 10 12 14 / 10 12 14 (IN pO 9 10 11) |
| `MOV DW,imm16` = `MOV AW,imm16` = `MOV DW,0FF04h` | 17 20 24 / 17 20 23 |
| `MOV DW,AW` = `MOV CW,AW` = `MOV AW,DW` | 13 16 19 / 13 16 19 |
| `XCH AW,DW` = `NOP` | 14 16 19 / 13 14 16 (IN pE w0 13) |
| `ADD DW,imm16` | 17 22 26 / 17 20 24 |
| `ADD AW,imm16` | 17 20 24 / 17 20 23 |
| `MOV DW,imm16 ; NOP` | 20 22 26 / 21 24 28 |
| `MOV DW,imm16 ; NOP ; NOP` | 25 26 31 / 24 26 30 |
| `MOV DW,[0C00h]` = `MOV AW,[0C00h]` | 23 28 33 / 21 26 31 (IN pO 20 24 28) |
| marker-less `MOV DW,imm16` = `MOV DW,0FF04h` (from t_fill) | 86 88 90 / 86 88 90 |

No predecessor moves the OUT by writing DW: every pair of a DW writer and
its same-format control is identical in every cell, for OUT and IN alike,
whatever the port (0040h, 0FF04h, 0 after the shift clears AW, 9090h for
the load). `ADD DW,imm16` is 0/+2/+2 later than `ADD AW,imm16` at pE only,
its extra byte (the finding-4 drainer case), not its DW write. After any
instruction OUT DW issues at s+7, as IN DW does; the named pair
`F10-none-movdwi-outdw-pE-w0` is F76 F79 I86, the END's own fetch pattern
with the OUT starting on the back-to-back fetch at 79, yet the END block
in the same run (`F0-ls-pE-w0`, F76 F79 I87) is s+8. The register
interlock and the fetch-pattern distinction of finding 3 are both refuted;
the one difference left is the HALT after the END's OUT. Determinism: 24
of 204 runs repeated identically.

### Take phase against the fetch (F11, 2026-10-19)

Per cell: the phase of the trailing `MOV CL`'s immediate take in the
seventh-fit model (B1/B3/W = the in-flight fetch's clock, idle), the
clocks to the shift's start, and the seventh-fit residual.

| variant | pE w0 | pE w1 | pE w2 | pO w0 | pO w1 | pO w2 |
| --- | --- | --- | --- | --- | --- | --- |
| n0 `MOV AW,DW` | B1+3 = | B3+1 −3 | W+2 −3 | B1+3 = | B1+4 = | B1+5 = |
| n1 `MOV AW,DW` | B1+3 = | B1+4 = | B1+5 = | B1+3 = | B3+1 −3 | W+2 −3 |
| n2 `MOV AW,DW` | B1+3 = | idle+1 = | idle+1 = | B1+3 = | B1+4 = | B1+5 = |
| n0 `MOV AW,imm16` | B1+3 = | B3+5 = | W+7 = | B1+3 = | B3+1 −3 | W+2 −3 |
| n1 `MOV AW,imm16` | B1+3 = | B3+1 −3 | W+2 −3 | B1+3 = | B3+5 = | W+7 = |
| n2 `ADD DW,imm16` | B1+3 = | idle+1 −4 | W+2 −4 | B1+3 = | B1+4 = | B1+5 = |
| n0 `MOV AW,DW` ×2 | B1+3 = | B3+1 −3 | W+2 −3 | B1+3 = | B1+4 = | B1+5 = |

The pattern alternates with n and parity through all 22 rows and never
occurs at 0 waits (44/44), where the take always falls on a fetch's issue
clock or an idle bus. The 3-clock wait occurs exactly when the immediate
is taken on the last clock (1 wait) or the last wait state (2 waits) of an
in-flight fetch with no request raised on that clock: `F11-none-n0-movr-pE-w1`
refills F72 F76 F80 F162 where the model gave 159, and `F9-none-movr2-pE-w1`
F166 against 163. A take on a fetch's issue clock, on an idle bus, or at B3
with a request raised there costs nothing. The model's state at the
shift's start is identical between misses and their exact neighbours; the
difference is one clock earlier, a double queue read (the immediate's
take and the IR load of the shift's opcode) on the fetch's last clock. The
−4 cells are the 4-byte `ADD DW,imm16` delaying a fetch, unresolved.
Determinism: 15 of 132 runs repeated identically.

### The OUT after a register form, and the 4-byte form (F12, 2026-10-19)

Series A: the closing OUT's I/O relative to t(M0) (the PUSH twin: the M1
write), silicon, then the eighth-fit model minus silicon on the probe, in
brackets the run's first residual where it differs; `!` = the model
overfills the queue. Columns pE w0/w1/w2, pO w0/w1/w2.

| variant | pE w0 | pE w1 | pE w2 | pO w0 | pO w1 | pO w2 |
| --- | --- | --- | --- | --- | --- | --- |
| out n0 ∅ | 10 = | 11 = | 12 = | 11 = | 12 = | 13 = |
| out n1 ∅ | 14 = (+3) | 16 = (+3) | 18 = (+3) | 14 = | 15 = | 16 = |
| out n2 ∅ | 18 = | 19 = | 21 = | 19 = | 20 = | 22 = |
| out n3 ∅ | 23 = | 24 = | 27 = | 22 = | 22 = | 24 = |
| out n0 `MOV AW,DW` | 14 +2 (−1) | 16 +2 (−1) | 18 +2 (−1) | 14 +3 (−1) | 16 +3 (−1) | 18 +3 (−1) |
| out n1 `MOV AW,DW` | 18 +3 (−1) | 20 +4 (+8) | 23 +4 (+8) | 18 −1 (−4) | 19 = | 21 = |
| out n2 `MOV AW,DW` | 22 −1 (−4) | 23 = | 26 = | 23 −1 | 24 = | 27 = |
| out n3 `MOV AW,DW` | 27 −1 | 28 = | 32 = | 26 −1 (−4) | 26 = | 29 = |
| out n0 `SHL AW,1` | 22 +4 | 24 +4 | 26 +4 | 23 +4 (−5) | 24 +5 (−5) | 26 +5 (−5) |
| out n1 `SHL AW,1` | 27 +1 | 30 = | 33 −1 | 26 +1 | 28 +1 | 30 +1 |
| out n2 `SHL AW,1` | 30 +1 | 32 +1 | 35 +1 | 30 +2 (−7) | 33 +1 | 36 +1 |
| out n3 `SHL AW,1` | 34 +2 (−7) | 37 +1 | 41 +1 | 34 +1 | 34 ! | 37 ! |
| out n0 `MOV AW,imm16` | 18 = | 20 = | 23 = | 18 = | 19 = | 21 = |
| out n1 `MOV AW,imm16` | 22 = (+4) | 23 +1 (+4) | 26 +1 (+4) | 22 = | 24 = | 27 = |
| out n2 `MOV AW,imm16` | 26 = | 28 = | 32 = | 26 = | 27 = | 30 = |
| out n3 `MOV AW,imm16` | 30 = | 31 = | 35 = | 30 = | 32 = | 36 = |
| pushout n0 `MOV AW,DW` | 17 +3 (−1) | 20 +4 (+8) | 24 +4 (+8) | 17 −1 (−4) | 19 = | 22 = |
| pushout n1 `MOV AW,DW` | 21 −1 (−4) | 23 = | 27 = | 22 −1 | 24 = | 28 = |
| pushout n2 `MOV AW,DW` | 26 −1 | 28 = | 33 = | 25 −1 (−4) | 26 = | 30 = |
| pushout n3 `MOV AW,DW` | 29 −1 (−4) | 30 = | 35 = | 30 −1 | 32 = | 37 = |
| push n0 `MOV AW,DW` | 12 +3 | 14 +4 | 17 +4 | 12 = | 14 = | 17 = |
| push n1 `MOV AW,DW` | 16 = | 18 = | 22 = | 16 = | 18 = | 21 = |
| push n2 `MOV AW,DW` | 20 = | 22 = | 26 = | 20 = | 22 = | 26 = |
| push n3 `MOV AW,DW` | 24 = | 26 = | 31 = | 24 = | 26 = | 30 = |

Reading. (1) At 0 waits the OUT starts no earlier than 4 clocks after
`MOV AW,DW`'s ModR/M take, one clock later than the model, in every
`MOV AW,DW` cell with n ≥ 1 and every pushout cell: the ModR/M is taken on
B1 of the fetch issued that clock, the model starts the OUT on the clock
after that fetch ends (take+3), silicon one later (`a-out-n2-movr-pE-w0`:
take 8, model F11 I21, silicon no fetch at 11, F15 I22; pO: model F19
I22, silicon F20 I23). The same take+4 accounts for the n0 rows and for
the F7 and F3 k=1 runs, where the take is on M0's I/O issue clock and the
fetch it raised issues on the OUT's start clock (t(M0)+4) instead of
right after the I/O. The controls separate it: the PUSH twin starts at
take+3 and is exact at every n ≥ 1, so it is the OUT that waits; after
`MOV AW,imm16`, whose last take is an immediate on B1, the model already
starts the OUT at take+4 and n ≥ 2 is exact; at 1–2 waits the take's
fetch ends later and the same cells are exact. (2) Where the fetch after
the take's fetch is back to back, silicon starts the next instruction on
that fetch's issue clock (pE n1 out, pE n0 pushout and push); the model's
`start_sync=b2b` holds it to that fetch's end: this is the `reg.nx` k=1
finding (`a-out-n1-movr-pE-w1`: silicon F4 F8 F12 I20, the model holds the
OUT to 12 and gives I24). (3) After `SHL AW,1` the OUT's I/O is one clock
earlier in silicon in 13 of 16 n ≥ 1 cells (`a-out-n2-shl1-pE-w0`:
port-take fetch 23 against 24): the model's `out.wbsync` clock behind the
shift's write-back is not there; directly after the OUT marker the SHL is
4 clocks shorter in silicon, the F3 rows. (4) The first fetch after the
OUT marker at pE with n = 1 is at t(M0)+4 whatever X is; the model gives
+7 for ∅ and +8 for the immediate form.

Series B, marker-less: the first four fetches from the restart relative
to t_fill, then the first residual; PUSH-marked: the M1 write.

| variant | pE w0 | pE w1 | pE w2 | pO w0 | pO w1 | pO w2 |
| --- | --- | --- | --- | --- | --- | --- |
| push n0 `ADD DW,imm16` = `ADD AW,imm16` (81 C0) | 16 +2 (−1) | 22 −4 | 26 −4 | 16 = | 18 = | 22 = |
| none n2 `ADD DW,imm16` = 81 C0 | 72 80 84 87 = | 72 76 84 88 −4 | 72 77 86 91 −4 | 76 84 87 90 = | 76 80 84 91 = | 76 81 86 94 = |
| none n3 `ADD DW,imm16` = 81 C0 | 72 80 88 91 = | 72 76 88 92 = | 72 77 90 95 = | 76 84 88 91 = | 76 80 88 92 −4 | 76 81 90 95 −4 |
| none n2 `ES: MOV AW,imm16` | 72 80 87 90 = | 72 76 86 90 = | 72 77 88 93 = | 76 86 89 92 = | 76 80 88 95 = | 76 81 90 98 = |
| none n3 `ES: MOV AW,imm16` | 72 80 90 93 = | 72 76 90 94 = | 72 77 92 97 = | 76 84 91 94 = | 76 80 90 94 = | 76 81 92 97 = |
| none n2 `SHL AW,4` | 72 80 83 103 = | 72 76 97 104 −17 | 72 77 99 107 −17 | 76 83 103 106 −2 | 76 80 103 107 −2 | 76 81 105 110 −2 |
| none n3 `SHL AW,4` | 72 80 87 107 −2 | 72 76 87 108 −2 | 72 77 89 111 −2 | 76 84 87 107 = | 76 80 101 108 −17 | 76 81 103 111 −17 |

Reading. Neither DW nor the length is the variable: 81 C0 and 81 C2 give
identical traces in all 18 pairs, and the 4-byte `26 B8 ii ii` is exact in
all 12 cells. Marker-less, the delay needs the ModR/M take on the clock the
refill burst's third back-to-back fetch would issue, with an operand byte
still outstanding and the previous word delivered the clock before (6
bytes queued): silicon issues no fetch there and the next comes on the
clock after the immediate's second byte is taken (84 not 80 at 1 wait, 86
not 82 at 2), the slot a 3-byte `MOV AW,imm16` fetches in. With the ModR/M
on the burst's first or second fetch clock, or after an idle clock,
silicon fetches on the take clock as modelled, and `MOV AW,DW` in the same
third slot (`F11-none-n2-movr-pE-w1`) fetches at 80. `SHL AW,4` (ModR/M +
imm8) in the third slot also issues no fetch, and elsewhere its count-byte
fetch is 2 clocks after the model's at every wait. PUSH-marked, the
fetches are identical and the EU is late instead: the M1 write is 4
clocks later at pE at 1 and 2 waits for both 81 forms, exact at pO with
the same take phases; the one distinction left is alignment (at pE the
ADD's immediate straddles two words). Determinism: 21 of 21 repeats
identical.

### Refresh, the EU side (F13, 2026-10-19)

462 runs, all `trace_complete` with a constant tick phase; refresh cycles
in every run with RFM bit 4 set and in none of the 36 S0 runs; 48 repeats
identical. RFM's layout (docs/v35s-bus-timing.md): bit 4 RFEN, bits 3–2
RFW, bits 1–0 RFT. Notation: S runs are `LS X LS END` with X = `MOV CL,n ;
SHL AW,CL`; tr is the restart fetch (the first LS's end); E is X's end
fetch, the first fetch of the word holding X's 11th byte; with refresh
off E − tr is 18/20/22 + 2n at 0/1/2 waits, exactly linear, and D is the
excess over that with refresh on.
[chains-F13-w0..w2]

| Fact | Evidence (clocks after t_fill) |
| --- | --- |
| RFT sets the interval to 16 << RFT clocks | r-rfm-f0..f3: idle gaps 14–18, 29–35, 60–67, 125–129 |
| RFW sets the cycle to 3 + RFW clocks; RFW 3 behaves as RFW 2 | F0h 3 clocks, F4h 4, F8h 5; F8h and FCh traces identical clock for clock; the interval is 16 at every RFW |
| a refresh stalls the count loop by (cycle length − 2): 3 / 2 / 1 clocks | the first LS ends at 93 with 6 refreshes (FCh), 85 with 5 (F4h), 79 with 5 (F0h), 75 with refresh off |
| the 15/17 alternation follows the parity of that stall | 15/17 at F0h and FCh, a constant 16 at F4h; 31/33 at RFT 1 and 63/65 at RFT 2 in the idle |
| inside the loop a refresh starts only on an iteration boundary | s pE-w0 deep refreshes 27 42 59 74 on a grid of 26 42 58 74 |
| near X's end a refresh starts at a fixed clock before it, by its distance from the grid | x = (end without this refresh) − grid: x 0–2 → E0 (the second LS's take); 3–4 → E0−3; 5–7 → E0−5; 8–9 → E0−8; 10–11 → E0−10; all six cells |
| a refresh costs 3, but 2 on the loop's last iteration; E − r is never 11 or 12 | unblocked E − r is only 8, 10, 13, 15; on equal refresh clocks E steps by 3 exactly at 10→13 (pE-w0 n 8→9, 14→15, 21→22, 27→28) |
| a refresh in the shift's setup clocks costs 0 or 1, not 3 | a refresh 2 clocks before the loop: D 0 at n=1, 1 at n=2, 3; one 6 clocks before the loop costs 3 |
| MULU is stalled too, about 3 per refresh, as a 2-clock loop with odd-aligned boundaries | u-push-mulu-k1 cost 9/9/14/7/9/12 with 3–4 refreshes; k=2 pO-w1 refreshes 111 128 |
| a NOP train is stalled about 1.7 per refresh, mostly through fetch placement | n-push-nop8 cost 5/5/5/7/5/5 with 3 refreshes; refreshes that only delay fetches give ΔM 44 against silicon's 46–48 |
| PUSH and OUT after the first LS see the same timer grid | identical chains to M0; pE-w0 grid 7 mod 16: PUSH frame refreshes 103 120, OUT frame 105 120 |
| the refresh at the first LS's end depends on the follower | follower MOV CL / PUSH / OUT: pE-w0 88/89/87, pE-w1 95/96/97, pO-w0 96/96/98 |
| PUSH takes a refresh only at start+4 (its first fetch-free setup clock) or at its write's issue | pE-w0: start 85, refresh 89, write 94; the other cells refresh 96, write 101 |
| MOV CL takes a refresh only at its start or at its immediate take, never on its two middle clocks | S series, every cell |
| OUT takes it on its first pre clock or its port take, not on the two clocks after; the refresh delays its I/O 1–6 clocks beyond its own 5 | F8-out-empty I/O at start+16..21 against +14..15 with refresh off |
| a fetch lost to a refresh comes back at X's loop end | pO w0/w1: word 13 fetched at E−6 / E−7 for every n |
| the first LS's end differs per cell by the prelude's refreshes; implied offsets −2/+2/0/0/0/−4 | RFT 3 pO-w1: a refresh at −12, the fill fetches unchanged, the first LS ends 2 clocks early |
| the "first refresh after the fill +7 at pE w0, +1 elsewhere" phase holds at FCh, F8h, F4h only | F0h 7, 4, 1, 7, 3, 1; at the other intervals the phase is set by the prelude, fixed per cell |

Reading: the refresh cycle holds something the shift's loop and MULU's
loop need at each 2-clock iteration boundary, so a loop iteration cannot
start while the cycle runs; the loop resumes the clock after the cycle
ends, and the cost is the cycle length less the 2 clocks the iteration
would have taken anyway. Steps that are not loops (NOP, the shift's
setup) lose at most the clock they would have started on. What the
model lacks is the state at t_fill: the prelude's refreshes (before the
trace's aligned region) leave the first long shift's execution at a
per-cell offset against the fill fetches, and no observable in the
chain pins it before the first LS ends.

### Format properties at [BW], group memory forms, the OUT frame (F14, 2026-10-20)

732 runs, all `trace_complete`, constant tick phase, no refresh events,
75 of 75 repeats identical. `DIVU [BW]` is data-fixed: after the fence
AW is 0 and DW:AW = 5678h:0000h over the 9090h fill gives 991Fh with no
trap. Clocks are relative to M0 in the PUSH frame at pE w0 unless stated;
the pairs vary one format property at a time.
[chains-F14-w0..w2]

| Pair | Property varied | Read | Write | End (M1) |
| --- | --- | --- | --- | --- |
| 84/86/00/38 against 85/87/01/39 | width | 0 | 0 | 0, identical in all 18 framed cells |
| `XCH CW,[BW]` 87 0F against 87 07 | the register | 0 | 0 | 0 |
| 03 against 01 (`ADD AW,[BW]` / `ADD [BW],AW`) | direction bit, writing form | 0 | – | the write only |
| 3B against 39 (`CMP AW,[BW]` / `CMP [BW],AW`) | direction bit, read-only form | 0 | – | 39 is +2 in every cell, +4 at k = 2 |
| 39 against 01 | the write, d = 0 | 0 | – | 39 = 3B + 2 |
| 85 against 39 (`TEST [BW],AW` / `CMP [BW],AW`) | TEST against CMP in the same format | +2 pE / +3 pO, on `NOT [BW]`'s and `INC [BW]`'s read clock in all 18 cells | – | 0 pE / +1 pO: the ALU runs after the read |
| F7 /0 against 85 (`TEST [BW],imm16`) | group TEST with an immediate | +2 in every cell | – | +5..+10 |
| 87 against 01 (`XCH [BW],AW` / `ADD [BW],AW`) | XCH against ADD | 0 | +2 in all 24 cells | +2 |
| `NOT` = `NEG` = `INC [BW]` against 01 | group RMW | +2 / +3 | +2 / +3 | +2 / +3 |
| 85 06, 87 06 (direct) | address mode | one more fetch first; TEST's delay is absorbed at pE by a fetch-free setup | | |
| `MULU [BW]` | | the group clock at both parities | | 36 clocks after the read cycle ends, at every wait |
| `DIVU [BW]` | | the group clock | | 44 after the read cycle ends |
| `SHL [BW],CL` (CL = 31) against `SHL [BW],1` | the count from a register | +4 pE / +3 pO at every wait | read to write 71 | |
| `POP [BW]` | | the stack read at 9 (model 8); pE has two fetches first | | |
| k = 2 at pE: `MULU`, `DIVU`, `SHL [BW],1`, `PUSH [BW]` | the second instance | 1 clock earlier than modelled; `INC` and `NOT` are not | | |
| OUT frame: `MOV AW,DW`, `ADD AW,DW` | after the OUT marker | NOP's and `XCH AW,DW`'s trace exactly: first fetch +4, closing I/O +14/16/18, both parities | | |
| OUT frame, PUSH twin | | every twin exact except `SHL AW,1` at pE w1/w2 | | |
| marker-less `NOP ; SHL AW,4` at pE w1/w2 | | no fetch during the shift: F72 F76 F99 | | |

Reading: the width, the register and the direction bit of a writing
form change nothing. A read-only form whose direction bit names memory
as the destination (CMP 39) ends 2 clocks later than its twin; TEST is
delayed at the read, on the group forms' clock, where CMP in the same
format is not: the one property that separates them is that TEST's
operation is named by no ALU-op field (neither the opcode's bits 5:3 of
the 00–3F block nor a group's reg field). XCH writes 2 clocks after ADD
with the same read. An AND [BW],AW / AND AW,[BW] control (in the 00–3F
block, TEST's operation with a write) would confirm the TEST reading and
is not in F14.

### The AND control, POP [BW], the second instance, the OUT frame (F15, 2026-10-20)

840 runs, all `trace_complete`, constant tick phase, no refresh events,
84 of 84 repeats identical. `POP [IX]` runs with IX = 0900h so its write
stays in the data page. Clocks relative to M0 in the PUSH frame at pE w0
unless stated.
[chains-F15-w0..w2]

| Fact | Evidence (clocks after t_fill) |
| --- | --- |
| AND reads on CMP's clock, not TEST's: the operation in the 00–3F field is not looked up | 21, 23, 09, 33 and 29 all read on ADD's clock in every cell, both frames and marker-less; TEST 85 +2 pE / +3 pO. The F14 reading of TEST holds |
| TEST imm's extra 2 clocks are neither the immediate's take nor the group decode | the immediate is taken after the read issues in both group read-only forms (one fetch at R+5 for F7 /0 and 81 /7); `CMP [BW],imm16` (81 /7) and `AND [BW],imm16` (81 /4) read on the same clock everywhere; the register forms `TEST AL,imm8`/`TEST AW,imm16` show no delay; F7 /0 reads at TEST 85's clock + 2 in all 18 cells: two decodes in series |
| a one-byte immediate (83 /x, sign-extended) reads 1 clock earlier than the two-byte form | at pO and at pE w0 |
| direct TEST: the lookup holds back the displacement's take | the fetch 3 clocks later and the read +3 at pO; at PUSH pE the delay is absorbed behind the third fetch |
| `POP [BW]` reads the stack on `POP AW`'s clock wherever the same fetches come first; the stack is read before the displacement in every address mode; the write comes 8 clocks after the read plus the read's waits, with no fetch between | all modes; [IX] exactly as [BW]; `POP CW` exactly as `POP AW` |
| what holds the fetch in `POP AW` (the fetch-free tail of its setup) is missing in `POP [BW]`: the fetch its ModR/M take raises runs, and the stack read follows that fetch's end | `F15-p-push-pop_bw-pE-w1`: F82 F86 r90 against `POP AW`'s F82 r88 |
| the early second instance at k = 2 is a property of the second form's start, not the first's end | `INC ; X` is early for MULU, SHL and PUSH [BW] and not for NOT; `X ; INC` is exact for every X; the same instruction is not needed (the address was not varied) |
| it shows only when the second form starts on an aborted fetch cycle, and after such a start silicon raises no fetch until the next instruction starts | `MULU [BW] ; MULU [BW]` pE w0: fetch at 80 against the model's 54 |
| OUT frame, `MOV AW,DW` then a memory form: the memory form's start moves | `F15-o-out-movr_ld-pE-w0`: I/O 84, F87 F90, the load reads at 93 on the second fetch's end |
| `MOV ; MOV` and `MOV ; NOP` after the marker: the second fetch +1 and the OUT's start −3; at pE w1/w2 the second MOV waits for a back-to-back fetch | OUT at 96, I/O 107 at w1 (`MOV AW,DW ; MOV AW,DW` is the same chain as `F3-out-mov_aw_dw-k2`) |
| `SHL AW,1` directly after the marker runs 2 clocks long; at pO no fetch until the shift ends | 24 runs in F3, F12 and F15 |
| `MULU AW` after the marker: at pO the fetch is deferred to the multiply's end; after a NOP the multiply waits for the back-to-back fetch | O series |

Reading: the AND control settles finding 2's TEST rule, and TEST imm is
the fixed-operation lookup and the F6/F7 group decode in series (the
F6/F7 reg field selects TEST/NOT/NEG/MUL/DIV and is not an ALU-op field,
unlike 80–83's). POP r/m reads the stack first, with POP AW's setup, and
decodes its reg field after the read. The early second instance has no
machine-state property that separates MULU, SHL and PUSH [BW] from NOT
and INC; they differ in the reg field's top bit, which is too close to
opcode keying to encode without a ladder over every reg value.

### The reg-field ladder, POP's held fetch, the long register forms after the OUT marker, the marker-less shift's count byte (F16, 2026-10-20)

1,014 runs (169 chains × 6), all `trace_complete`, constant tick phase, no
refresh events, 102 of 102 repeats identical (91 of them at a half-clock or
whole-clock reset offset, as in every family). Data: `DIV [BW]` (F7 /7) runs
with DW = 0100h (with the fence's 5678h the signed quotient overflows: a
divide trap): 0100h:0000h / 9090h = -588 rem 2752, the second instance
-6324, after `INC [BW]` -588 / -7675, no trap. `MUL [BW]` multiplies AW = 0.
`DIVU DW` cannot run at all (DW:AW / DW >= 10000h whenever AW >= 0, a trap
at every datum), so the register divide is `DIVU IX` (F7 /6 on IX) with IX =
9090h, the datum of `DIVU [BW]` (5678h:0000h / 9090h = 991Fh; the F14 note's
990Ch was a typo, corrected there). `MUL`, `DIV` and `MULU byte` are trap-free and data-fixed
(one datum each; whether the signed forms' clocks depend on the data is not
tested). Clocks rel M0 in the PUSH frame unless stated (marker-less: rel
t_fill). [chains-F16-w0..w2]

R, the second instance (PUSH frame; `X X` and `INC [BW] ; X`):

| Fact | Evidence |
| --- | --- |
| every D1 reg value (/0 ROL, /1 ROR, /2 RCL, /3 RCR, /4 SHL, /5 SHR, /7 SAR) and D0 /4 (byte) give the same trace, event for event, in all 6 cells of `X`, `X X` and `INC X` | `rol-x_x` pE w0: R11 W22 R32 W43 F46 w52, identical for all eight forms |
| the early second instance (1 clock early at pE, every wait, against the eleventh fit) is shown by every D0/D1 form, `MULU`, `MUL`, `DIVU`, `DIV` (F7 /4-/7), `MULU byte` (F6 /4) and `PUSH [BW]` (FF /6); not by `NOT`, `NEG` (F7 /2, /3), `INC`, `DEC` (FF /0, /1); `TEST [BW],imm16` (F7 /0) is 1 late instead (model -1) | `rol-inc_x` pE w0: INC W94, ROL R104 (model 105); `not-inc_x`: R105 = model. The reg field's top bit is refuted as the property: D1 /0-/3 show it like /4-/7 |
| the split is by the unit that runs the operation after the read: the shift unit (all eight D0/D1 operations), the multiplier/divider and the stack write show it; the one-pass ALU operations (NOT, NEG, INC, DEC: 5 clocks read to write) do not. Width (D0 against D1, F6 against F7) changes nothing | read to write: ALU 5, shift 11, PUSH r/m 9 (stack write), MUL/DIV no write |
| after the early start a multiply or divide still ends where it would have (its exec does not move with the early read), and silicon runs no fetch until 3 clocks before it ends (at every wait); the eleventh fit fetches right after the read | `mulu-inc_x` pE w0: R104, F134, PUSH write 143 (R105 + 3 + 29 = 137 the end); w1 R109 F140; `divu-inc_x` pE w0 R104 F142 w151 (8 later, as DIVU's exec); at pO, `mulu-x_x` R11 F43 R51 |
| it needs the second form to start on an aborted fetch cycle (pE); at pO every R chain is exact for the shift, ALU, PUSH and MULU/DIVU forms | 75 pE runs 1 late in the eleventh fit (25 variants x 3 waits), 0 pO runs; second-instance read, b - a: `inc_x` SHL - NOT -1 / -1 / -1 at pE, 0 at pO; MULU - NOT and PUSH - NOT the same; every D0/D1 form - SHL D1 /4 = 0 in all 12 cells of both shapes; NEG - NOT = 0 |
| the signed MUL [BW] (AW = 0 × 9090h) runs 20 clocks more than MULU [BW], the signed DIV [BW] 21 more than DIVU [BW]; MULU byte [BW] 8 fewer than MULU [BW] | `mul` k1: R11 w69 against MULU's R11 w49 (model -20 in all 6 cells); `div` -21; `mulub` k1 R11 w41 (model +8) |

P, POP's held fetch:

| Fact | Evidence |
| --- | --- |
| with NOP^n before it (n = 1-3) `POP [BW]` under PUSH reads the stack on `POP AW`'s clock in every cell, and the fetch POP AW holds runs in neither or in both | `n1-pop_bw` pE w1: F82 F86 r92 = `n1-pop_aw`; all 18 n >= 1 runs exact |
| at n = 0, pE, 1-2 waits, the fetch whose room POP [BW]'s ModR/M take made (requested on the delivery clock of the fetch issued on POP's start clock) runs, and the stack read issues on the clock after it: the read's remaining setup clocks counted through the fetch; at 0 waits the same request is held behind the read | `n0-pop_bw` pE w1: F82 F86 r90 (POP AW F82 r88); w0: F81 r87 F98, exact. The request arrives on the read's first fetch-free setup clock (w1: start+4, the read issuable at +6) or its second (w2); at w0 it arrives on the last clock before them (start+3). So what moves the held fetch is whether its request first rises, on a delivery clock, before or inside the read's 3 fetch-free setup clocks; NOPs before POP move the fetch out of POP's setup altogether. The same holds for other posted reads and writes: 10 F5 and 4 F7 runs share it |
| the same in the OUT frame one NOP later | `out-n1-pop_bw` pE w1: I/O 85, F89 F93 r97 (model F89 r95); at n = 0, pE, every wait: F88 r91 (model F87 r92) |
| POP [BW+d8] and POP [0C00h]: the held fetch as POP [BW] at n = 0; at n >= 1 the fetch after the read and the write differ by 1 (the displacement's take) | d8 n0 pE w0: r87 F93 W96 (model F84 r89); d8 n1 pO w0 r91 F97 W100 (model F96 W101); dir n1 pO w1 r92 W101 F105 (model F99 W103) |
| marker-less, NOP^n POP [BW] and POP AW, n = 0-3: all 48 runs exact | |

L, long register forms after the OUT marker (OUT frame; PUSH twin):

| Fact | Evidence (rel the marker's I/O) |
| --- | --- |
| at pO the first fetch after the marker waits for the register form's end whenever the form starts on the I/O's issue clock, takes its ModR/M there and that clock is a word's delivery clock (its second byte latched): `SHL AW,1` F8 (I/O at 23), `SHL AW,CL` F(10 + 2n), `MULU AW`/`MULU DW` F32, `DIVU IX` F40; it scales with the form's length, 2 clocks per count. The fetch lands 2 (shifts) or 5 (MULU) clocks before the form ends, and MULU AW runs 37 clocks from its start at pO as at pE (where its take sync waits for the fetch at +3): as if the take sync waited for a fetch that does not appear | the empty frame F8 I11; `shlcl4` pO w0: F18 F30 I33 (model F3); `mulu_aw` pO F32 F44 I47 (model F3); at pE (no delivery on the issue clock) `mulu_aw` F3 F40 I47 |
| a shift with a count byte (C1) does not: its fetch at pO is at +3 as in the empty frame (the count byte is taken later) | `shli4` pO w0: I0 F3 F25 I32, exact |
| at pE the first fetch is at +3 for every form; what moves is the OUT's port-take fetch after the form: `SHL AW,1` +2 against the eleventh fit (its exec runs after the I/O cycle: the shift started on the issue clock, its ModR/M taken there, its clocks from the cycle's last clock + 1), `SHL AW,CL` after MOV CL +3/+4/+5 (w0/1/2: it scales with the waits, so a fetch, not the I/O), `NOP ; MULU AW` +3/+4/+5, C1 shifts +0/+1/+2 | `shl1` pE w0: F87 F99 I106 (model F97 I104); `shlcl4` pE w0 F115 I122 (model F112 I119) |
| `MULU AW ; NOP` at pE: the closing I/O 2 earlier than modelled; at pO the fetch at the multiply's end as above | |
| the PUSH twin: `SHL AW,CL` after MOV CL at pE writes 1 later with the fetch 2 earlier (F105 w114, model F107 w113); `MULU AW` at pE writes 1/2/3 later at w0/1/2 (the multiply's end vs a fetch); `DIVU IX` (register divide) runs 8 clocks longer than `MULU AW`, as DIVU [BW] does against MULU [BW] | `divu_ix` push pO w0: w51 against MULU AW's w43 |

S, the marker-less shift's count byte (`LS NOP^n X LS END`):

| Fact | Evidence (rel t_fill) |
| --- | --- |
| a C1 shift whose count byte is taken on a word's delivery clock at 1-2 waits (late_read moved it there from the fetch's last clock) issues no fetch until the shift ends, at every count 1-16, and its exec starts a clock later than modelled; the next fetch comes after the shift (the second LS's MOV CL immediate) and the deficit is the shift's length (11 + 2m clocks); it happens only where the room for that fetch was the uncounted latched byte; at 0 waits, or with real room, the fetch runs | `n1-shli4` pE w1: F72 F76 F99 F103 (model F80); 20 runs: pE n1 and pO n2 at w1/w2, m = 1, 2, 4, 8, 16; F12 B, F14 O and F15 O share it |
| the same shift with its count in CL (MOV CL,m right before it, or MOV CL,m ; NOP^n before it) fetches during the shift in the same cells: the missing fetch is tied to the shift's own count byte, not to the shift's length or the count | `n1-shlcl4` pE w1: F72 F79 F83 F107 (exact); `n2-shlcl4` pE w1 F72 F76 F85 F109 |
| `MOV CL,m ; NOP^n ; SHL AW,CL`: where the shift starts on an aborted fetch cycle (pE n1 w0, pE n3, pO n1 w0, pO n2; every m) the dropped request goes 2 clocks before the shift ends, as its last count iteration starts, not at the next take (5 clocks later in the eleventh fit); with NOP^n before MOV CL and the shift adjacent, exact everywhere | `cl4-n1-shlcl` pE w0: the shift starts at 82 on the aborted cycle, F75 F78 F100 F106 (eleventh fit F105) |
| a C1 shift whose ModR/M is taken on a word's delivery clock with the word's second byte latched and the queue full (the count byte taken later, not on a delivery clock) also runs no fetch until the shift's last clock, where the request its count take raised goes: pE n2 and pO n3 at 1-2 waits, every count | `n2-shli4` pE w1: F72 F76 F97 F104 F108 (eleventh fit F83: the count take's request); 20 runs, F12 B 4 more |
| `NOP^n ; MOV CL,4` alone: exact but at pE n2 w1/w2 and pO n3 w1/w2 (-1) | |

Reading. R: the reg field's top bit is not the property: D1 /0-/3 (the
rotates) show the early second instance as /4-/7 do, and the byte forms
as the word forms; it is not a write-back either (MUL/DIV write no memory,
NOT/NEG/INC/DEC do) nor the aborted start alone (NOT and INC start on the
same aborted cycle). What separates the forms is the unit that runs the
operation after the read: the shift unit (every D0/D1 operation), the
multiplier/divider (F6/F7 /4-/7) and PUSH r/m's stack write (FF /6) read a
clock sooner after an aborted-cycle start than the one-pass ALU operations
(F7 /2-/3, FF /0-/1); within each group the decode selects the routine by
the whole reg field, so the reading is a microcode entry per operation
unit, not a bit test. A multiply or divide started that way keeps its end
and holds the dropped prefetch until 3 clocks before it. P: what moves the
held fetch is the clock its request first rises: on a delivery clock inside
the stack read's fetch-free setup clocks (1-2 waits) the fetch runs and the
read issues right after it, before them (0 waits) it is held; with NOPs
before POP the fetch is out of POP's setup. The same rule holds for every
posted memory request (F5, F7). L: after the OUT marker the register form
started on the I/O's issue clock runs its exec only after the cycle (SHL
AW,1 at pE, +2); at pO, where the issue clock is a delivery clock, the
fetch is deferred to the form's end, scaling with the form's length, while
the form itself runs its pE length. S: the missing fetch belongs to the
shift's own count byte taken on a delivery clock whose only room was the
uncounted latched byte; it lasts to the shift's end whatever the count, and
the same shift with the count in CL fetches; with the ModR/M taken that way
and the count later, the request the count take raises waits for the
shift's last clock. Both are one rule: an operand byte of the count-byte
shift read through the port while it writes a delivered word, with no room
but the latched byte, makes the shift hold the port for its run.

### The OUT frame's remainder (F3, F5, F12, F14, F15 and F16 re-read, 2026-10-21; no new acquisition)

Clocks relative to t_fill; T is the OUT marker's I/O issue clock (84 at pE, 85 at pO
at 0 waits); "end" is the clock the next instruction starts.

| Fact | Evidence |
| −-- | −-- |
| the register divide sits outside the register-only classes in the twelfth fit's model: `DIVU IX` starts on the marker's port take, before the I/O issues, where `MULU AW` waits for the issue clock | `F16-l-out-divu_ix-pE-w0`: silicon F87 F132 I139, MULU AW's F87 F124 I131 plus 8 (the PUSH twin's w130 against w122); the twelfth fit F123 I130 |
| at pO, a register shift whose ModR/M take on T is its last operand byte, on a delivery clock with the word's second byte latched, defers the first fetch to its last count iteration's start, as a shift started on an aborted cycle does (abort_unit=loop): every count n ≥ 2 exact with no new integer | `F16-l-out-shlcl4-pO-w0`: I/O 90, SHL AW,CL starts and takes its ModR/M there, exec 93–109, F108 (= end − 2), F120 I123; `shlcl8` F116; `shl1` (D1) F93 |
| a count loop of one iteration raises that request on the loop's first clock, the same clock as any longer loop's last iteration; the model checked the retry clock only at the start of a clock, one late | `F16-l-out-shl1-pO-w0` F93 (model F94); `F16-s-none-cl1-n1-shlcl-pE-w0` and the PUSH-twin `shlcl1` at pE: 10 runs of F16 S/L |
| a C1 shift does not defer: its ModR/M is a chained take, the count byte still to come, and with the latched byte counted mid-take no request rises on T | `F16-l-out-shli4-pO-w0`: F88 (+3), exact in the twelfth fit |
| a register shift, multiply or divide is held by a fetch that runs in its exec: at a micro-boundary (every second exec clock from its first for the D0/D1/C0/C1 shifts, from its second for the shift by CL, MULU and DIVU) while the fetch is past its second clock, the EU waits until the clock after the fetch's last; a fetch starting on the exec's first clock costs the D1/C1 shifts its wait states, the shift by CL and the multiply its wait states + 1 | `F16-l-out-shli4-pE`: exec from 92 (w1), the back-to-back fetch 92–95, the closing I/O +0/+1/+2 at w0/w1/w2 later than the twelfth fit; `F16-l-out-shlcl4-pE` +1/+2/+3 (exec from the I/O's end, the fetch raised under the I/O issuing there); `F16-l-push-mulu_aw-pE` w122 w125 w128 against the fit's w121 w123 w125: the back-to-back fetch after the take's |
| the memory multiply and divide are not held so: a fetch on their mexec's first clock leaves them exact | F14 G and F16 R `push-mulu_bw`/`divu_bw` at pE, 15 of 18 exact with the fetch on the exec's first clock |
| at pO the register multiply after the marker ends 35 clocks after T at every wait, one clock more than its exec from the I/O's end; a 3-clock cycle with no waits starting there (the dropped request answered by an aborted cycle) gives it, the hold costing 1 | `F16-l-out-mulu_aw_nop-pO`: the NOP starts 120/121/122 at w0/w1/w2 (I/O 85/86/87); `mulu_aw-pO-w1`: F118 F130 I134 |
| the request the multiply's take dropped is raised mexec − 2 clocks after its operand (the exec's first clock for the register form, the read data for the memory form): in the early-start case (abort_unit) the same clock as the eleventh fit's "3 before the moved end" | `F16-l-out-mulu_aw-pO-w1` F118 (exec from 89); `F14-g-out-mulu_bw-pO-w0`: read 93–95, F123 (= 96 + 27); `F16-r-push-mulu-inc_x-pE-w0`: R104, F134 (= 107 + 27) |
| the memory multiply or divide that runs when the marker's I/O issues on a latched delivery clock defers the request that delivery raised to the same clock | `F14-g-out-mulu_bw-pO-w0`, `divu_bw` F131, F5 `out-mulu_m` pO (18 runs, −27/−35 in the twelfth fit) |

Reading. The two OUT-frame effects of finding 9 are one mechanism seen at two parities:
the bus unit, having given the issue clock to the I/O, treats a fetch request raised on
that clock by the arrival of a word whose second byte is latched as an aborted
request, and the unit running a count loop raises it again at the loop's exit (the
shift's last iteration, the multiplier's operand + mexec − 2), as it does after an
aborted fetch cycle. At pE no word lands on T, the request is an ordinary one and the
fetch runs right after the I/O, where it holds the unit's exec as a refresh cycle holds
the count loop: at its micro-boundaries while the bus cycle is past its second clock.
The hold explains the PUSH twin's register MULU at pE (+1/+2/+3 with the waits: the
back-to-back fetch the take raised, not the take's own) and every pE OUT-frame shift
row (= / −1 / −2 for the D1/C1 shifts, −1/−2/−3 for SHL AW,CL).

Further facts (same corpus; clocks rel t_fill):

| Fact | Evidence |
| −-- | −-- |
| the register multiply after the marker at pE ends 35 + (the waits of the fetch after the I/O) clocks after T, and a NOP or a second MULU starts there; the closing OUT directly after it starts 2 later; the PUSH twin's PUSH starts at the end itself. So the multiply writes back for 2 clocks past its end as the shifts do (`shift_*.wb` 2) and only the port-form OUT waits for it (`out.wbsync` 1) | `F16-l-out-mulu_aw_nop-pE-w0`: NOP (and its fetch) at 119, I134; `F16-l-out-mulu_aw-pE-w0`: the OUT at 121, F124 I131; `F3-out-mulu_dw-k2-pE`: the second MULU's fetch F119/F121/F123 at w0/w1/w2 |
| the multiply's take on the I/O issue clock does not wait for the fetch raised under the I/O (as the latched forms' takes do not, sync_io=latch); its exec runs from the I/O's end and that fetch, starting there, holds it by its waits + 1 | the same three runs; with the take sync waiting for the fetch the NOP starts at 121 |
| at pO the same multiply ends 34 clocks after T (exec from the I/O's end, no fetch in it); the deferred fetch at its operand + 29 holds a following NOP to its delivery (no start while a fetch is in flight), and the closing OUT waits the write-back | `F16-l-out-mulu_aw_nop-pO`: NOP 120/122/124 (F120/F122/F124) at w0/w1/w2; `mulu_aw-pO-w1`: F118, OUT at 122, F130 I134 |
| a register D1/C1 shift or multiply started on an aborted fetch cycle (k = 2 at pE, the second instance) runs its exec from the aborted cycle's last clock, one clock early; the multiply still ends where it would have and raises the dropped request 29 clocks after the early start; the shift by CL does not (the closing LS's SHL AW,CL started on an aborted cycle is exact without it in 192 runs) | `F3-push-mulu_dw-k2-pE-w0`: the second MULU on the aborted cycle 116–118, F147 w156 (model F150); `F3-push-shl1-k2-pE-w0`: F98 w107 (model F99 w108); the same in F14 G and F3 k = 4 |
| after the OUT marker at pE, POP r/m's stack read (posted at its start behind the marker's I/O, setup 7 with the last 3 fetch-free) moves into the bus unit's slot when the I/O issues; the fetch its ModR/M take requested before that runs on the read's first fetch-free clock, not right after the I/O, and the read counts its setup through it | `F15-p-out-pop_bw-pE-w0`: I/O 84, F88 r91 W99 (the twelfth fit F87 r92 W100); w1 F89 r93, w2 F90 r95; every POP r/m mode and k (F5, F14 G, F15 P, F16 P n = 0: 42 runs); a load behind the same I/O (setup 0) and the group forms (their free clocks on an idle bus) keep the fetch right after the I/O: `F4-out-ld_bw-k1-pE-w0` F87 R90, `F5-out-inc_m-k1-pE-w0` F87 R92 |
| the twelfth fit's knob dependence of `div.exec` (40/41 better at pE on 5 runs) is the hold and the write-back above: with them `div.exec` 39 is best at every knob | knob_dependence: no integer moves |

Reading, continued. The register multiply's 31 exec clocks are 29 to its end and 2 of
write-back (the shifts' wb 2), the pipeline's `mul.pre 1 / exec 29 / wb 2` basin read the
same split from the other side. POP's stack read behind an I/O is the one posted request
that is still in its setup with fetch-free clocks to count when it reaches the slot (a
load is ready, a group form's free clocks need an idle bus): the bus unit holds the fetch
pending from before until those clocks, then runs it inside them and the read counts
through, as free_run=run does for a fetch first raised on a delivery clock inside them.

Still open after this reading: `POP [BW+d8]` at n ≥ 1 and pO (the fetch after the read 1 early, the
write 1 late: the displacement take, 12 runs) and `POP [0C00h]` at 1–2 waits (silicon
writes before the displacement's fetch, 9 runs) — pop_mem.pre 3 (−32), setup 3 (−331),
pop_read_hold=queue (−34), hold_count=queue (−74) refuted; the OUT directly after a register
multiply at pO w0 (6 runs: the OUT starts on the deferred fetch's delivery clock in the
model, a clock later in silicon); `NOP NOP ; MULU AW` after the marker at pO w0 and the PUSH
twin's `NOP NOP ; MULU AW` at pO w1/w2 (3 runs, ±1); the F16 S `MOV CL,m ; NOP ; SHL AW,CL`
pO w0 rows (5, −2, unchanged) and `NOP^n ; MOV CL,4` (4).

| Fact | Evidence |
| −-- | −-- |
| POP r/m's displacement ends on a fixed clock after the stack data: a two-byte displacement (direct `[0C00h]`) is taken at data + 2 and + 3, a one-byte one (`[BW+d8]`) at data + 3; the memory write then counts its setup through the fetch the take raises | `F15-p-out-pop_bw_d8-pO-w0`: r91 (data 94), F97 W100 (the twelfth fit F96 W101); `F16-p-push-n1-pop_dir-pO-w0`: r91, F97 W100; the same at n = 1–3 and marker-less: 11 runs |

Refuted on this corpus (scores against the thirteenth fit):
- an aborted cycle on the first free clock for the multiply's dropped request
  (`io_take=abort`, −30);
- the take sync extended to a fetch the bus unit commits to back to back at the synced
  fetch's last clock, for every take (+14 −93) or a memory form's (+4 −13), or to a fetch
  requested on the synced fetch's delivery clock when the take was on its B1 (+36 −835),
  or the `imm_landed` deferral for every memory form's last take (+36 −486): each gains the
  18 F6 `n1` drains (one MOV AW,imm16 then a load/store/RMW, the data cycle 2 late) and the
  ten `MOV AW,DW` pairs but no state separates them from F4's PUSH-frame loads;
- the fetch a latch-waiting I/O form held going first when the latch frees
  (`latch_fetch`, +2 −177; for `MOV [BW],imm16` then OUT at pO, 12 runs open);
- the store's immediate entering the data latch (`wlatch_imm=all`, +10 −171);
- no fetch on the clock after an I/O cycle while a memory request waits in the slot
  (−480), or every request moved in behind an I/O counting its setup through fetches (−83);
- `pop_mem.pre` 3 for every displacement (+11 −32: the direct form's bytes then end a
  clock late), `pop_mem.setup` 3 (−331), `pop_read_hold=queue` (−34), `hold_count=queue`
  (−74);
- the early start on an aborted cycle for the shift by CL as well (−192, the closing LS).

### The refresh fill phase made observable (F17, 2026-10-21)

798 runs (133 chains × 6), all `trace_complete`, constant tick phase, refresh
cycles in every run whose chain sets RFEN and in none of the others (the
refresh-off prelude leaves none after clock 0 before the chain's RFM write);
81 of 81 repeats identical up to a constant offset (13 at 0, the rest at a
half-clock multiple, as in every family). The prelude writes RFM ECh as every
refresh-off family does; the chain writes RFM itself right after the first LS
with RFMON = `DS1: MOV byte [0FFE1h],imm8`, bytes `26 C6 06 E1 FF ii`, DS1 =
F000h (the brief's `3E` is DS0, which is 0 in every chain; the assembler drops
a `DS1:` written before the mnemonic, parsing it as a label, so the bytes are
given in forms.py and checked by test_chains). Series: S `LS RFMON(FCh) NOP^n
X LS END`, n = 0..3, 13 X; E the same with ECh (n = 0..3 for four X, 0 for the
rest); D with FDh (RFT 1) for four X; W `LS NOP^n RFMON LS END`, n = 0..7, FCh,
FDh and ECh (the NOPs move the write itself: S cannot tell a restarting timer
from a free-running one, since its NOPs come after the write); C the PUSH cost
frame `LS RFMON M0 X M1 LS END`; P the S chain with refresh on from the prelude
(FCh) for five X, n = 0, 1. Clocks rel t_fill unless stated; "abs" is rel clock
0 (the fetch of the word holding the chain's first byte). [chains-F17-w0..w2]

| Fact | Evidence |
| --- | --- |
| the SFR store makes no bus cycle on the pins (none in any prelude either) and holds the bus unit for 3 clocks at every memory wait setting: the I/O block's waits (WTC field 7, 0 here) or a fixed 3, not block 0's | E (refresh off throughout), 150 of 150 runs exact with the store a 3-clock internal write cycle (`sfr_cycle=io`); with the memory-wait length every w1 and w2 run is +1 / +2. `F17-e-n0-empty-pE-w0`: F72 F75 F78 F87 F90 (the store's cycle in the gap) F168 |
| the refresh timer is not restarted by the RFM write: it runs free, and RFEN only gates its requests | W FCh pE w0, the write 4 clocks later per NOP (n = 0..7, 28 clocks in all): the idle refreshes at 108 125 140 157 172 (n0), 109 124 141 (n2, n4, n5), 125 140 157 (n6), all on one grid; the first refresh is the first grid request after the write (93, 93, 92, 110, 109, 109, 108, 126) |
| the timer's phase at clock 0 is a constant of the prelude: the same in every chain that shares the prelude's RFM and WTC, at both parities and whatever the chain holds | the idle refreshes' residues abs mod 16: refresh-off prelude (F17 S, E/W with refresh written on, D, C: 250 runs per wait setting) 8/9, 2/3, 5/6 at w0/w1/w2; FCh prelude (F8, F13 FCh, F17 P: 231 runs per wait) 8/9, 11/12, 6/7; F8h as FCh; F4h 3, 12, 6; F0h 3/4, 12/13, 4/5 |
| the record's per-cell phase ("pE w0 +7, else +1" against t_fill) is this constant seen from t_fill, which is itself single-valued per prelude and parity | silicon t_fill: ECh 28/32/38 at pE, 25/30/36 at pO; FCh 33/28/39 and 24/28/39; every family, every run |
| the timer is a binary counter: RFT selects which bit's rising edge is a request (bit RFT + 3); the 32-clock grid lies 8 clocks off the 16-clock one | F17 D and W FDh (same prelude as S): residues abs mod 32 0/1, 10/11, 13/14 at w0/w1/w2 against the 16-grid's 8, 2, 5. One counter value at clock 0 fits both (c0 = 16 / 6 / 3 mod 32): a request when (c0 + t) mod 2^(RFT+4) = 2^(RFT+3) |
| a write that switches RFT to a bit already high while the old bit was low raises a request at once: the edge is detected against the previous clock's selected bit | W FDh pE w0, the write taking effect 3 clocks after its issue: n4 effect at 100, counter 144 (bits 4 and 3 both high, the previous bit 3 high), no refresh until 133; n5 effect 103, counter 147 (bit 4 high, bit 3 low): X103; n6 108, counter 152: X108; n7 111, counter 155 (bit 3 high again): none until 132. The grid alone gives X100 in n4 and nothing in n5, n6 |
| RFEN takes effect 3 clocks after the store's issue, the clock after its 3-clock cycle | W FDh n4/n5/n6/n7 above bound it to exactly 3 (2 gives X100 in n4; 4 gives X103 in n4, X106 in n5 and nothing in n6); FCh: `F17-w-fc-n2-pE-w0` request 92, served; n3 the request 95 two clocks after the write is not |
| the phase is set long before the chain: relative to the reset refresh (the first trace row) the post-fill 16-grid sits at 109 / 101 / 93 ticks mod 128 at w0/w1/w2, one CPU clock earlier per wait setting, while clock 0 moves 45 / 85 / 53 ticks | prelude refreshes run every 480 ticks before the PRC write (9 in each refresh-off prelude) |

The EU side, with the first LS and the fill exact (every event before the first refresh
is the refresh-off model's in all 798 runs but the 16 W ECh misses below):

| Fact | Evidence (clocks rel t_fill) |
| --- | --- |
| a refresh that beats the fetch request the END's MOV DW take raised still lets that fetch run after it though HALT has started meanwhile, and the queue goes on fetching back to back, ahead of the waiting OUT's I/O | `F17-s-n0-empty-pE-w0`: F186 X189 F194 F197 I200; `F13-s-shlcl12-pE-w2`: X259 F264 F269 X274 I279. The record's "the OUT's I/O after a refresh: silicon runs one more fetch first" is this run |
| a fetch request raised on a word's delivery clock with the word's second byte latched is lost to a refresh that takes the bus on that clock when the room it leaves is odd (one word and the latched byte's slot), kept when it is even | over F17: room 3, 82 runs with the EU waiting on a shift's take sync and 14 with an OUT, all lost; room 4, 47 and 34 runs, all kept. `F13-s-shlcl2-pO-w1`: X97 X113 F118 (kept: F102). This is the record's pO w0/w1 loss; the pE cells it kept have the even room |
| a request lost while a register shift (or MULU) runs comes back as the count loop's exit starts, the clock after its last iteration, not on the next take | `F13-c-out-shlcl5-pO-w1`: X128, F138, X145 (next take: F152; the last iteration's start: F135); `F17-d-n1-empty-pE-w2` the second LS ends F183 (the last iteration's start F180) |
| an operand take of several bytes takes a pending refresh only on the clock its last byte goes | the END's `MOV DW,0FF00h` immediate at 228 and 229: `F17-d-n0-shlcl16-pE-w0` X229 (on the first byte: X228); `F17-s-n1-empty-pE-w0` X190 F195 F198 |
| inside `SHL AW,CL`'s exec (6 clocks before its count loop in the model) a request at exec+3 or +4 is served at +4 in 33 runs and at +6, the loop's first clock, in 27; every first refresh after RFEN that falls there (20 runs: S n0 and W n0/n4 at pO w0/w1) waits for +6, and those LS end 4 clocks after the model's (2 for the later refresh, 2 for a whole-cycle hold at the loop's entry) | `F17-s-n0-empty-pO-w0`: request 95, X98 (model 96), the second LS ends 185 (model 181); `F17-s-n1-rmw-pE-w0`: request 124 served at 124, ends 209 = model. No machine state the model carries separates the two groups (exec start parity, refresh count, time since the last refresh all tried) |
| in the END's HALT a request is served on HALT's first clock, +2, +3, +5, +8, +10, not on +1 or +4 | request at H+1 → H+2 (18) or H+3 (10); H+4 → H+5 (26 of 26); H+2 → H+2 (19) |
| with refresh on from the prelude the first LS ends 16 to 19 clocks later than with refresh off, absolute (rel clock 0), with 7 or 8 refreshes after clock 0: one or two of them fall before the LS's execution or in its setup, per cell | P n0 empty: pE 18 / 16 / 19, pO 17 / 16 / 17 at w0/w1/w2; `F17-p-n0-empty-pE-w0` restart at 118 abs against `F17-s-n0-empty-pE-w0`'s 100 |

Reading. The timer is a binary counter running from reset whatever RFEN says; RFT picks the
bit whose rising edge (against the previous clock's selected bit) is a request and RFEN
gates it, so the RFM write's effect on the phase is nil and on the first request a glitch
only when the switch selects a bit already high. The fill phase the record could not pin is
the prelude's: the counter at clock 0 is the same for every chain of a prelude (RFM, WTC),
and seen from t_fill it moves only with t_fill itself, which is single-valued per prelude and
parity. With the phase from the prelude no per-run alignment is left: F8 and F13 score as
with it (F8 1/48, F13 43/462 before the EU rules), F17 as well. What a refresh-on prelude still
hides is where the first LS starts against clock 0 (silicon's prelude ends while the fill
runs; the model's stand-in starts the LS on a full queue): the P series shows the LS stalled
by 16 to 19 clocks per cell for 7 or 8 refreshes, so 1 or 2 of them land before its loop.
The observable that pins it is that start: a PUSH (stack write) or OUT marker as the
prelude's last instruction, directly before the first LS, under both RFM values.

### The first LS under a refresh-on prelude and the exec-boundary ladder (F18, 2026-10-21)

1,164 runs (194 chains x 6), all `trace_complete`, constant tick phase, refresh
cycles in every run whose prelude or chain sets RFEN and in none of the 96 A ECh
runs; 117 of 117 repeats identical up to a constant offset (12 at 0, the rest at a
half-clock multiple). Series: A `[marker] PAD LS X LS END`, the marker the prelude's
last instruction (Chain.prelude_marker: `PUSH AW` = 50, its stack write at 0EFEh,
or `OUT 20h,AL` = E6 20) directly after its `MOV AW,1234h` and directly before the
chain's first byte, X in {empty, `MOV CL,m ; SHL AW,CL` m = 4, 16, 31, `MULU DW`,
`NOP^8`, `MOV AW,[BW]`, `MOV [BW],AW`}, prelude RFM ECh (the control), FCh, FDh; AC
the ECh prelude with the marker and `LS RFMON(FCh) LS END` (the counter read off with
the marker in place); B `PAD LS RFMON(FCh) [ES: NOP] NOP^n X LS END`, prelude ECh,
n = 0..7, X in {`MOV CL,4 ; SHL AW,CL`, `MOV CL,16 ; SHL AW,CL`, `SHL AW,4` (C1),
`SHL AW,1` (D1), `MULU DW`, `DIVU IX`, `SHL [BW],CL`}; BD the same with RFMON FDh for
the CL-4 shift and MULU. The ES: NOP (26 90, 7 clocks at 0 waits, no register
written) steps the request 3 clocks against X where a NOP steps it 4; with n >= 4 the
first request after RFEN falls in the NOPs and the second lands in X. Placement: both
markers put the chain's first byte in the word at 10048h (PUSH: chain base 10048h,
OUT: 10049h), so clock 0 is the same fetch for both; the image check asserts the
prelude is the bare prelude plus the marker's bytes after `B8 34 12`; the normaliser
finds the marker's cycle in the trace (the OUT's I/O at port 20h; the PUSH's write at
0EFEh after the prelude's POP PSW read there, its PUSH 0002h writing 0EFEh first),
keeps it in the event list (it closes the bus gap the fill is measured across) and out
of the access match, and tracks SP from 0EFEh after a PUSH marker. [chains-F18-w0..w2]

| Fact | Evidence (clocks rel clock 0) |
| --- | --- |
| the marker's cycle is single-valued per prelude RFM and wait setting and the same at both parities and for every X | PUSH write: ECh 16 / 18 / 21, FCh 18 / 19 / 25, FDh 17 / 19 / 22 at w0 / w1 / w2; OUT I/O: ECh 22 / 24 / 28, FCh 25 / 28 / 32, FDh 24 / 26 / 29; 16 runs per cell |
| t_fill is single-valued per prelude and parity with the marker in place | PUSH ECh 27 / 32 / 38 (pE), 31 / 36 / 43 (pO); FCh 31 / 35 / 47, 34 / 39 / 49; FDh 28 / 33 / 39, 32 / 37 / 39. OUT ECh 34 / 38 / 44, 30 / 34 / 40; FCh 37 / 47 / 50, 33 / 38 / 49; FDh 36 / 40 / 50, 32 / 36 / 41 (8 or 9 runs each) |
| the counter at clock 0 is a constant of the marker prelude, the same for both markers | idle-grid residues: ECh (AC, 1 run per cell) requests at 1 / 10 / 12 mod 16 (no marker 8 / 2 / 5): c0 7 / 14 / 12; FCh (48 runs per wait) 4 / 7 / 1 mod 16 (no marker 8 / 11 / 6): c0 4 / 1 / 7; FDh 9 / 10 / 7 mod 32: c0 7 / 6 / 9. Entered in refresh.PRELUDE_COUNTER and SILICON_FILL under (RFM, WTC, marker); AC is then exact in 4 of 6 cells with the existing rules |
| with refresh off the first LS starts on a fixed clock after the marker: PUSH at pE on the clock after its write cycle (3 / 4 / 5 clocks after the write's first), at pO 4 / 4 / 5 later (the PAD NOP); OUT at pE 4 after its I/O, at pO on the I/O's clock (the PAD runs ahead of the waiting I/O) | the prelude-tail model (below), exact in all 96 A ECh runs: LS start 19 / 22 / 26 (PUSH pE), 23 / 26 / 31 (pO), 26 / 28 / 32 (OUT pE), 22 / 24 / 28 (pO); the LS runs 83 / 85 / 87 clocks from its start to the restart fetch |
| with refresh on from the prelude the marker itself is 1-4 clocks later and the LS runs 16-21 clocks longer (FCh) or 4-9 (FDh), with 8 or 9 refreshes (FCh) or 4 (FDh) after clock 0 before its end: 1 or 2 before its start, 0 or 1 in its MOV CL and exec, 5 or 6 (FCh) / 2 or 3 (FDh) in its count loop | PUSH FCh pE: M 18 / 19 / 25, restart 124 / 128 / 138 (ECh 102 / 107 / 113); OUT FCh pE 25 / 28 / 32, restart 130 / 140 / 143 (ECh 109 / 113 / 119); `F18-a-push-fc-empty-pE-w0`: F0 F3 X7 F12 w18 X21 F26 F29 (fill 31) X38 X53 X68 X85 X100 X116 F124, against ECh F0 F3 F7 w16 F22 F25 (fill 27) F102 |
| the prelude's POP PSW stack read is single-valued per prelude and both parities; a refresh-on prelude takes 19-24 clocks longer from it to clock 0 | ECh -79 / -92 / -109 (513 runs per wait), FCh -98 / -111 / -133 (83), PUSH/OUT marker ECh -86 / -100 / -118, FCh -102 / -115 / -138, FDh -95 / -111 / -134 |
| in the prelude's register-load train (MOV r16,imm16) a refresh request goes on the first free bus clock at 1-2 waits, and 0, 1 or 3 clocks after it at 0 waits, where the EU is the bottleneck | 76 / 78 of 76 / 78 train refreshes at w1 / w2 on the first free clock; w0: 44 at once, 20 one later, 12 three later (`F17-p-n0-empty-pE-w0`: requests -72 -56 -40 -24 -8 served -69 -54 -39 -24 -5) |

The prelude tail made the model's (prelude_tail=regs or segs): run the prelude's register
loads (and its segment loads, MOV sreg,AW as a register-only form) from an empty or a full
queue, then the marker, the PAD and the first LS as they come, and take the model's own
clock 0. With refresh off this reproduces silicon's t_fill and the marker's clock in all 18
prelude cells (three preludes x six cells) with no SILICON_FILL, and with one restriction
(wlatch_ir_at=start: a register form's lapsed take sync needs the data latch still busy when
the I/O form in the IR can start) every refresh-off run of F0-F17 as the stand-in does;
without it every OUT-marked pE run (1,094) is 2 clocks short, the first LS's SHL AW,CL
running with the OUT in the IR. With refresh on it is worse than the stand-in on the first
LS's end against t_fill (27 of 66 refresh-on prelude cells right against 41): the train's
refresh interplay is not modelled closely enough, and the counter's anchor (clock 0, t_fill
or the POP PSW read) has no fixed point in several cells (`F17-p-n0-empty-pE-w2`: the
model's clock 0 alternates 149 / 151 with the phase it implies).

Series B, the exec-boundary ladder. E is the unit form's exec start (the model's, exact up to
the first refresh after RFEN); the request (from the counter) against E and the clock silicon
serves it on, the first refresh after RFEN unless marked by the delay of the refresh before
(`dN`: that one went N clocks after its request). `SHL AW,CL`'s exec is E..E+5 and its count
loop starts at E+6 (2-clock iterations).

| X | request -> served |
| --- | --- |
| `MOV CL,m ; SHL AW,CL` (m = 4, 16; F17 S m = 1..31 agree) | E+0 -> E+0; E+1 -> E+2 (after a d0 refresh: E+4 in 3 runs per m); E+2 -> E+2; E+3 -> E+6 (first, 14 runs; d1, 1) but E+4 (d2, d3: 8 runs); E+4 -> E+6 (first, 6; d2, 8) but E+4 (d3, 2) and E+5 (d1, 2); E+5 -> E+6; E+6 -> E+6; E+7 -> E+8 |
| `SHL AW,4` (C1) | E+0 -> E+0; E+1 -> E+3 (first 3, d0 4, d2 2); E+2 -> E+3; E+3 -> E+3 |
| `SHL AW,1` (D1) | E+0 -> E+0; E+1 -> E+3; E+2 -> E+3; E+3 -> E+3 (model E+5) |
| `MULU DW`, `DIVU IX` | the same pattern for both (the divider runs the multiplier's loop): the first request served on an even clock from E (E+1 -> E+2 in 12 + 4 runs, E+2 -> E+2 in 7 + 2), where the model's loop_odd boundaries take E+1 and E+3 |
| `SHL [BW],CL` (CL 31) | the read's data, then refreshes on the shift's iteration boundaries every 16 clocks through its 69 clocks, each costing 3: `F18-b-n1-shlmcl-pE-w2` read 108, refreshes 113 128 143 160 175 193, write 198 (refresh off: read to write 71) |

Reading. The loop's-eve boundary of the shift by CL (E+4) is the one silicon does not always
take, and what separates the cases is not the first refresh after RFEN as such: it is taken
only when the previous refresh cycle started within 18 clocks at 0 waits (17 at 1, 16 at 2)
before it; a request after none, or after one longer ago (every request at RFT 1, whose
32-clock interval leaves the previous one 27+ clocks back), waits for the loop's first clock.
The F17 split of finding 8 (b) (33 runs at +4, 27 at +6, every first refresh after RFEN among the 27) is consistent with it: a first refresh has no recent predecessor. The divider
and the multiplier share the count-loop structure (refresh at the loop's boundaries, a hold
there), and so does the shift unit run from a memory operand: its write's setup counts the
shift, and the refresh stalls the count by the cycle's length less 2 there as in the register
form. Left: the shift by CL at E+1 after a refresh served at once (d0, 3 runs) and at E+4 after
one 2 clocks late (4 runs); the C1/D1 shifts' acceptance on E+3 for requests at E+1..E+3 (model
E+1/E+2 and E+5); the multiply's and divide's boundary parity (silicon even from E for the
first request, the model's loop_odd odd; loop refuted, -19, since the later refreshes of F13 U
and F17 favour it); the prelude train under refresh (above). Determinism: 117 of 117 repeats.

### Immediate memory forms and the DW I/O forms (F19, 2026-10-21)

1,290 runs (430 per wait setting), all `trace_complete`, constant tick
phase, no refresh events (RFM ECh throughout), 129 of 129 repeats
identical up to a constant tick offset. Series I: seven immediate memory
forms (`MOV [BW],imm16` C7 07, `MOV byte [BW],imm8` C6 07, `MOV
[BW+10h],imm16` C7 47, `MOV [BW+200h],imm16` C7 87, `CMP [BW],imm16`
81 /7, `ADD [BW],imm16` 81 /0, `CMP [BW],imm8` 83 /7) behind a lead-in
of none, `NOP`, `NOP NOP`, `NOP NOP NOP` or `ES: NOP` (each NOP moves X
one byte and 4 clocks, `ES: NOP` keeps n = 0's alignment at 7 clocks),
PUSH and OUT frames at k = 1 (k = 2 with no lead-in) and marker-less
(none, NOP, ES: NOP). Series D: `OUT DW,AL` (EE), `OUT DW,AW` (EF, the
catalog's `out_dw_al`), `IN AL,DW` (EC), `IN AW,DW` (ED) after a register
form P of 1–4 bytes (none, NOP, `XCH AW,DW`, `MOV DW,AW`, `MOV AW,DW`,
`MOV CW,AW`, `MOV AW,imm16`, `ADD DW,imm16` with 0, `SHL AW,1`, `MOV
CL,imm8`), with one NOP between for the 2–4-byte P, the word forms over
four P; the DW form after itself and after `OUT 40h,AL`; PUSH, OUT and
marker-less; AW = DW = 0040h. The fifteenth fit scores 895/1290 (I 324/630,
D 571/660). s below is the instruction's start in the model, which is
right wherever the earlier events match; clocks rel t_fill.
[chains-F19-w0..w2]

| Fact | Evidence (clocks rel t_fill) |
| --- | --- |
| The first data cycle of every immediate memory form comes 7 clocks after its start at 0 waits (6 with a one-byte immediate), whatever its alignment, lead-in, frame or address mode, when its address bytes are queued: C7 07, C7 47 d8, C7 87 d16, 81 /0 and 81 /7 alike; C6 07 and 83 /7 one clock earlier | PUSH frame, X at s = 81 + 4n: `F19-i-push-n1-stimm-pE-w0` W92 and `-pO-w0` W92 (X even and odd); n2 W96 both parities, n3 W100, ES: NOP W95 (s = 88); `addimm`/`cmpimm` read on the same clocks, `stimm8`/`cmpimm8` one earlier (W91, R91 at n1); marker-less `F19-i-none-l0-stimm-pE-w0` W79 = `-pO-w0` W79 (s = 72), n1 83, `stimmd16`/`stimmd8` 79 and 83 at both parities. The model is 2 early (3 for C6, which gets no group setup in it) in every cell where no fetch runs between the start and the data cycle (`-pO-w0` n1: model W90; `stimm8` n1 pO W88) and exact where one does |
| At 1–2 waits the 7 clocks run on every clock, wait states included; a fetch in the head delays the data cycle further only through the path the model already has (the ModR/M take's sync on that fetch, then the group setup), which then ends later than s+7 | no fetch between the start and the write: s+7 at every wait (`F19-i-push-n2-stimm-pO-w1` F86 W97, s = 90, model W95; `F19-i-none-l0-stimm-pO-w2` W79, s = 72); a fetch in the head: `F19-i-push-n1-stimm-pE-w1` F86 W94 (s = 86, one wait state), `F19-i-push-l0-stimm-pE-w1` F82 F86 W90 (s = 82, two fetches and two wait states in the head, W at s+8, not s+9: the wait states are not added to the 7) |
| Directly after the OUT marker the form's start waits behind the I/O (s = 80) and its data cycle is the I/O's recovery's, as modelled | `F19-i-out-l0-stimm-pE-w0` I84 F87 W91; `-pO-w0` I85 W92 |
| After `MOV [BW],imm16` (and d8/d16) the next instruction runs one more fetch first wherever the store leaves the queue shallow: 5 bytes queued at the write, 2 after the immediate's take (the model's count), against 6 or more and 3 in every exact twin; under the OUT frame the closing OUT starts 3 clocks later (the second fetch after the write, not the first), under PUSH the second fetch after the write is a clock later and the PUSH write a clock earlier | OUT: `F19-i-out-l0-stimm-pO-w0` W92 F96 F99 F102 I109 (model F96 F99 I106), `-k2-pO-w0` the second write W108 (model W104), n2 pO, n3 pE, ES pO the same at 0 waits (`F19-i-out-n2-stimm-pO-w0` W100 F104 F107 F110 I117); the deep-queue twins `n1` pE/pO, `l0`/`n2`/`ES` pE exact (W95 F99 F102 I109). PUSH: `F19-i-push-n1-stimm-pO-w0` W92 F95 F99 w102 (model F95 F98 w103), likewise n2 pE, n3 pO, ES pE |
| With a displacement at odd alignment the first fetch after the start comes at s+3 for d8 and d16 alike, and the write still at s+7 at 0 waits; at 1–2 waits a d16 form's write follows the second fetch | `F19-i-none-l0-stimmd8-pO-w0` F75 W79 (model F73 W80), `stimmd16-pO-w0` F75 W79 (model F74 F77 W81), `stimmd16-pO-w1` F75 F79 W83, `-w2` F75 F80 W85; at even alignment both are exact (F72 F75 W79) |
| `CMP [BW],imm8` (83 /7): the left-out write's slot carries a fetch at one alignment and not the other; under the OUT frame at 0 waits the closing OUT after either CMP is a clock later than modelled | PUSH: `F19-i-push-l0-cmpimm8-pE-w0` R87 w100, no fetch (model R87 F92 w101), `-pO-w0` R87 F92 w101 (exact); OUT: `F19-i-out-l0-cmpimm8-pE-w0` R90 F95 F107 I110 (model F106 I109), `F19-i-out-l0-cmpimm-pE-w0` R91 F94 F97 I111 (model I110), at every lead-in and both parities; `ADD [BW],imm8` in the same frame exact (F15: R90 W95 F99 F102 I109) |
| `CMP [BW],imm16` at k = 2 reads the second time on `ADD [BW],imm16`'s clock: the left-out write's slot ends the first instance where ADD's write does | PUSH pO: CMP R88 F91 F94 R104, ADD R88 F91 W94 F97 R104 (model CMP R102); at every wait; under OUT pE the same (R107 vs model R105) |
| A DW form queued behind an I/O waiting in the bus unit's slot neither delays that I/O nor waits for it to latch its port: it issues 7 clocks after the I/O ahead issues, counting that clock, unless a later port-byte take relatches | `F19-d-push-pair-outb-pO-w0` I88 I95 (model F93 I96); `F19-d-push-outimm-outb-pE-w0` I92 I99 (model F97 I100); `F19-d-out-pair-outb-pO-w0` I85 I92 (model I85 F90 I93); `F19-d-out-none-outb-pO-w0` M0 I85 (model I88: the DW form's port latch relatched it), the DW I/O at 94 = the closing OUT's port take + 3 |
| While it waits there it holds fetches only as a memory request does, while the queue holds more than 3 bytes | the twins of the cells above with 3 bytes queued run a fetch first: `F19-d-push-pair-outb-pE-w0` I88 F93 I96, `F19-d-push-outimm-outb-pO-w0` I92 F97 I100 (both exact); with 4 queued no fetch |
| After the OUT marker at pE, a 2-byte register form (8B: `MOV AW,DW`, `MOV DW,AW`, `MOV CW,AW`) whose ModR/M is taken on the I/O's issue clock delays a following DW form to the back-to-back fetch after the one its take raised, at every wait; one NOP between moves that fetch a clock later; the same pair is exact at pO, under PUSH and marker-less | `F19-d-out-movawdw-outb-pE-w0` I84 F87 F90 I97 (model F87 I96), w1 F88 F92 I100, w2 F89 F94 I103; `movawdw_nop` F87 F91 I100 (model F87 F90 I101); `XCH AW,DW` (1 byte) and `MOV AW,imm16` exact |
| `ADD DW,imm16` (4 bytes) before a DW form, PUSH and OUT pE: one more fetch before the DW form | `F19-d-push-adddwi-outb-pE-w0` w78 F81 F85 F88 I95 (model F84 F87 I96); OUT pE: F88 F91 F94 I103 (model F88 F91 I100) |

Reading. The immediate memory forms issue their first data cycle no
earlier than a fixed count from their start: 5 clocks plus one per
immediate byte, displacement bytes free, every clock counted. The model
reaches the same clock only through
the take sync it runs after the ModR/M byte when a fetch is in flight
there; with none in flight its group setup (3 after the EA clocks) ends
2 clocks early, and C6 /0 had no group setup at all. The DW forms'
port comes from DW, not the shared port latch, so a DW form neither
relatches an I/O waiting in the slot nor waits for it: it queues behind
it and counts its setup from the clock the I/O ahead issues, holding
fetches as a memory request does. What the corpus cannot order and F19
does: alignment against the fetch (every lead-in at both parities moves X
across the cadence with the same result), the immediate's width (C6/83
against C7/81), the displacement (d8 and d16 at the [BW] clock), the
clock against the alignment (ES: NOP), the I/O ahead's kind (port form,
DW form) and the queue count behind it. Left as found: the OUT after an
odd-placed immediate store (one more fetch), the 8B forms on the I/O
issue clock before a DW form at pE, and `ADD DW,imm16`'s extra fetch
(finding 4).

### The register form before a load, a store, an RMW, an I/O form or another register form (F20, 2026-10-21)

3,594 runs (1,198 per wait setting), all `trace_complete`, constant tick phase, no
refresh events (RFM ECh throughout), 360 repeats identical up to a constant tick
offset in every row's start, end, address, flags and data (12 of them, 5 at 1 wait
and 7 at 2 waits, differ in one row's harness `strobe` field, 7 against 8, which
nothing in the analysis reads; `repeat_shift` is null for them for that reason
alone). Series R: a lead-in of none, `NOP`, `NOP NOP` or `ES: NOP` (each NOP moves P
one byte and 4 clocks, `ES: NOP` keeps l0's alignment at 7 clocks), a register form
P of 1–4 bytes whose last byte is its opcode, a ModR/M byte or an immediate (none,
`NOP`, `XCH AW,DW`, `MOV AW,DW`, `MOV DW,AW`, `MOV AW,imm16`, `ADD AW,imm16` (05),
`ADD DW,0` (81 C2: DW stays the port), `ES: NOP`, `ES: MOV AW,DW`, `ES: MOV
AW,imm16`), then X ∈ {`MOV AW,[BW]`, `MOV [BW],AW`, `ADD [BW],AW`, `OUT DW,AL` (EE),
`OUT 40h,AL`, `MOV AW,DW`}; the OUT frame with every X and lead (1,584 runs), the
PUSH frame at l0, n1 and ES without the RMW (990), marker-less at l0 and n1 without
the RMW (660). Series N, the F6 drain frame `M0 D^n P X M1` for P ∈ {none, NOP,
`MOV AW,DW`, `MOV AW,imm16`, `ADD DW,0`} and X ∈ {load, store, `OUT DW,AL`, `MOV
AW,DW`}: OUT n = 1, 2 (at n = 2 the second drainer sets DW, so the DW form goes to
port 5678h) and PUSH n = 1 (360). AW = DW = 0040h throughout (the shift clears AW
before the body, so `MOV DW,AW` sets the port to 0). The sixteenth fit scores
3289/3594 (w0 1025, w1 1131, w2 1133). Clocks rel t_fill; s is the instruction's
start in the model, right wherever the earlier events match. [chains-F20-w0..w2]

| Fact | Evidence (clocks rel t_fill) |
| --- | --- |
| A register form whose last operand byte is taken on a fetch's issue clock, with room for another word once that fetch's word is reserved, gets the next fetch back to back, and a ModR/M form after it waits that fetch out; this holds for every register immediate form (B8, 05, 81 C2, 26 B8) before every ModR/M X, in every frame, lead and wait setting: the data cycle comes 2 later than the sixteenth fit | `F20-r-out-l0-movawi-ld-pE-w0` F88 F91 F94 R99 (sixteenth fit: the same fetches, R97); `-pO-w0` F89 F92 R97 (the take not on an issue clock; exact before); `F20-r-push-l0-movawi-ld-pO-w0` w78 F85 F88 F91 R96 (R94); `F20-r-none-l0-movawi-ld-pE-w0` F76 F79 F82 R87 (R85); `F20-r-out-l0-movawi-ld-pE-w2` F90 F95 F100 R107 (R105); the F6 `n1` drains are this case (`F6-out-ld_bw-n1-pE-w0` F88 F91 F94 R99); a form without a ModR/M byte after the same P starts on the back-to-back fetch as before (`F20-r-out-l0-movawi-outdw-pE-w0` F88 F91 I100) |
| Not while a memory data request waits in the bus unit's slot: the data cycle goes first | `F1-store-m1-pE-w0` (A3, the write posted on the address take on fetch 75's issue clock) F75 W78 F81; every direct-address form (A1, A3, `POP [0C00h]`) the same |
| `ADD DW,imm16` (81 C2) at an odd address started on a fetch's issue clock s at 0 waits: no fetch on that fetch's delivery clock s + 3, where the immediate's first byte (the ModR/M byte's word-mate) is taken, but at s + 4, as for the 3-byte `ADD AW,imm16`; the following fetch back to back, the next instruction a clock earlier than modelled where it ends a sync | `F20-r-push-l0-adddwi-outdw-pE-w0` w78 F81 F85 F88 I95 (F84 F87 I96); twin `F20-r-push-l0-addawi-outdw-pE-w0` w78 F81 F85 F88 I95 (exact before); `F20-r-out-n1-adddwi-ld-pE-w0` F88 F92 F95 F98 R103 (F91 F94 F97 R102); at an even address (`-pO-w0` of the same) or not started on an issue clock (`F20-r-push-n1-adddwi-ld-pO-w0`, `-es-`) exact before; at 1–2 waits the delivery falls after the immediate's take and every cell is exact |
| The same geometry with a displacement as the word-mate (`MOV AW,[BW+d16]`, 8B 87 at an odd address after PUSH) fetches on s + 3; with base+index+d16 silicon does not fetch there, and the read is earlier than with base+d16 at pE | `F4-push-ld_bw_d16-k1-pE-w0` F81 F84 F87 R90; `F4-push-ld_bw_ix_d16-k1-pE-w0` F81 F85 R88 F91 (the model F84 F87 R90, its EA table 2 for every mode); `F4-push-ld_bw_d16-k1-pO-w0` F81 F84 R87 (model F85 R88) |
| An I/O form (port or DW) due to start on a back-to-back fetch's issue clock with 2 bytes stored (the delivered word's second byte latched) starts after that fetch instead; with 3 or more stored it starts there, as modelled. Every case in the corpus: X 32 of 32 at 2 stored, = 248 of 248 at 3 | `F20-r-out-l0-movawdw-movr-pE-w1` F88 F92 F96 I107 (the closing OUT on fetch 96's issue clock; model I104 on 92); `F20-r-out-l0-pfxnop-movr-pE-w1` the same clocks, exact; `-pO-w1` F89 F93 F97 I105 (3 stored at 93, exact); `F20-r-out-l0-adddwi-outdw-pE-w1` F89 F93 F97 I107 (I103); twin `F20-r-out-l0-movawi-outdw-pE-w1` F89 F93 I103 (3 stored); `F19-d-out-adddwi-inb-pE-w0` F88 F91 F94 i101 (i98); `F3-out-mov_aw_imm-k1-pE-w1` F89 F93 F97 I105 (3 stored, on the back-to-back clock) |
| ... except where the latch-waiting OUT holds the back-to-back fetch itself: the OUT starts on the next fetch's issue clock as modelled | `F20-r-out-l0-movawdw-movr-pE-w0` F87 F91 F94 I101; `F20-r-out-l0-adddwi-outimm-pE-w0` F88 F92 F95 I104 |
| A DW form posted at its own start does not count the clock a back-to-back fetch starts on (as its start clock) | `F19-d-out-movawdw-inb-pE-w0` F87 F90 i95 (i94); `F20-r-out-l0-movawdw-outdw-pE-w1` F88 F92 I100 |
| The closing port-form OUT's port byte taken on a word's delivery clock with the second byte latched holds the DW request a clock longer | `F19-d-out-movawdw-outb-pE-w0` F87 F90 I97, the port take at 93 on fetch 90's delivery (I96); `F20-r-out-l0-movawdw-outdw-pE-w0` the same |
| New, not in item 4: `ES: NOP` (26 90) directly before a memory form at 0 waits, at one alignment per frame: the data cycle 2 late, and before `MOV AW,DW` the next fetch a clock early; exact at the other alignment and at 1–2 waits | `F20-r-none-l0-pfxnop-ld-pE-w0` F72 F75 R84 (model R82); `-pO-w0` F74 R83 exact; `F20-r-none-l0-nop-ld-pE-w0` F72 R81 exact; `F20-r-none-l0-pfxnop-ld-pE-w1` F72 F76 R85 exact; OUT frame `es-pfxnop` pE, `n1-pfxnop` pO, `n2-pfxnop` pE; PUSH `l0-pfxnop` pO, `n1-pfxnop` pE, the ES lead with P none pO (27 runs) |
| New: after the `ES: NOP` lead under PUSH at pO 0 waits, the 8B forms' next fetch a clock early | `F20-r-push-es-movawdw-ld-pO-w0` w78 F81 F84 F90 R95 (model F91 R96); `-pE-w0` exact (8 runs) |

Reading. The four groups of finding 4 are three mechanisms, each with a state the
sixteenth fit did not carry, and F20 separates each from its controls. (1) The F6
`n1` drains and the register-immediate rows are the request flag: with
`request_eval=on_change` a fetch's issue cleared it and nothing raised it again until
the next queue change, so a register form whose last take fell on a fetch's issue
clock left no back-to-back fetch for the ModR/M form after it to wait out; silicon
evaluates the request after the issue on such a clock, unless a memory request waits
in the slot. (2) The 4-byte `ADD DW,imm16` under PUSH (and after the NOP under OUT)
is the ModR/M byte's word: when the ModR/M opens a word whose second byte is the
immediate, taking that byte on a delivery clock does not free the word for that
clock's request; a displacement byte in the same place does (the F4 base+d16 loads),
so the split is by the byte's kind, and the F4 base+index+d16 loads, which silicon
also does not fetch for, stay open with their read clock. (3) The 8B forms before a
DW form, the ten `MOV AW,DW` pairs and the 4-byte form under the OUT frame are one
start rule: an I/O form does not start on a back-to-back fetch's issue clock while
the queue stores fewer than 3 bytes; the controls with 3 stored (`MOV AW,imm16`,
`NOP ; MOV AW,DW`, pO) start there. What the corpus could not order and F20 does:
P's length and last byte against X's ModR/M, the frame, the alignment and the
stored count at X's start.

### The effective-address path: mode class, displacement width and alignment, five consumers (F21, 2026-10-21)

3,576 runs (1,192 per wait setting), all `trace_complete`, constant tick phase, no
refresh events (RFM ECh throughout), 360 repeats identical up to a constant tick offset
(5 at 2 waits differ only in one row's harness `strobe` field, so that acquire exited 1;
the file is complete). X is one of five consumers of a ModR/M memory operand, `MOV
AW,r/m` (8B), `MOV r/m,AW` (89), `MOV r/m,imm16` (C7 /0), `ADD r/m,AW` (01) and `POP r/m`
(8F /0), in seven modes: [BW], [BW+10h], [BW+200h], [BW+IX], [BW+IX+10h], [BW+IX+200h] and
[0C00h] (mod 00 rm 110), so base and base+index with no displacement, d8 and d16, and the
direct address. A lead-in of none, `NOP`, `NOP NOP`, `NOP NOP NOP` or `ES: NOP` moves X one
byte (whether the displacement's first byte is the ModR/M byte's word-mate, and whether a
d16 straddles two words) and 4 clocks (`ES: NOP` keeps none's alignment at 7 clocks); PUSH
and OUT frames at every lead (`PAD LS M0 L X M1 LS END`), marker-less at none, NOP, NOP
NOP and ES: NOP; k = 2 with no lead for the five displaced modes in both frames; the load
in [IX+10h], [IX+200h], [BP+IY+10h] and [BP+IY+200h] as controls at every lead and frame.
Every data address is in the data page or (index alone) below it, off the stack. The
seventeenth fit scores 2547/3576 (w0 759, w1 894, w2 894). s below is X's start in the
model, which is right wherever the earlier events match (every run tabulated by s was
checked for that); clocks rel t_fill. [chains-F21-w0..w2]

| Fact | Evidence (clocks rel t_fill) |
| --- | --- |
| No address mode without a displacement costs anything for its index: base and base+index give the same trace in every cell, every consumer, frame, lead, parity and wait | [BW] = [BW+IX] in 420 of 420 cells (140 per wait); `F21-none-l0-ld-bw-pO-w0` and `-bw_ix-` both R77 F80 F86 |
| Every one-byte displacement is one class: base+d8, base+index+d8, index+d8 and [BP+IY+d8] are identical everywhere | [BW+10h] = [BW+IX+10h] 480/480, = [IX+10h] 84/84, = [BP+IY+10h] 84/84; `F21-none-l0-ld-bw_d8-pO-w0` = `-bw_ix_d8-` F75 R78 |
| Every two-byte displacement without an index register is one class: base+d16, index+d16 and the direct address are identical everywhere | [BW+200h] = [0C00h] 480/480, = [IX+200h] 84/84; `F21-none-l0-ld-bw_d16-pO-w0`, `-dir-`, `-ix_d16-` all F75 R78 F81 (model F76 F79 R82, F74 F77 R80, F76 F79 R82) |
| Base+index with a two-byte displacement is its own class ([BW+IX+200h] = [BP+IY+200h] 84/84) and costs one clock: at 0 waits every event from the first one after the displacement on is exactly one clock later than base+d16's in 132 of 160 cells and later in the other 28 (the +1 meeting a fetch boundary); never equal. At 1–2 waits it is equal in 77 of 160 cells (where a fetch issued on X's start still runs at s+3, so the next fetch cannot go before s+4 for either), +1 throughout in 79, otherwise 4 | `F21-none-l0-ld-bw_ix_d16-pO-w0` F76 R79 F82 against `-bw_d16-` F75 R78 F81; every consumer: `F21-none-l0-sti-bw_ix_d16-pO-w0` F76 W80 (bw_d16 F75 W79), `-pop-` r78 F85 W88 (r78 F84 W87), `-st-` F76 W79 (F75 W78), `-add-` F76 R79 W84 (F75 R78 W83); F4's `push-ld_bw_ix_d16-k1-pE-w0` F81 F85 R88 and the 24 OUT-frame base+index+d16 runs are this class |
| The second displacement byte costs nothing once queued: base+d16 equals base+d8 through X's first data cycle in 154 of 172 single-instance cells at 0 waits (all 30 POP cells); the 18 others are one alignment per frame, where the d16's second byte lies in a word not yet fetched when the first is taken: then the data cycle follows that word's delivery | PUSH pO: `F21-push-n1-ld-bw_d16-pO-w0` F88 R91 = `-bw_d8-` F88 R91 (model F89 F92 R95); the straddle `F21-push-l0-ld-bw_d16-pE-w0` F81 F84 F87 R90 against `-bw_d8-` F81 F84 R87 (exact in the model) |
| Relative to s, with the bus free at the displacement's take, at 0 waits: a mod 00 form reads or writes at s+5; with any one- or two-byte displacement the first fetch after the start is at s+3 and the data cycle at s+6; base+index+d16 fetches at s+4 and reads or writes at s+7. The same in all three frames and all five consumers (POP r/m behind its stack read: write 14 / 15 / 16 after s) | marker-less, s = 72: `F21-none-l0-ld-bw-pO-w0` R77, `-bw_d8-` F75 R78, `-bw_d16-` F75 R78, `-bw_ix_d16-` F76 R79; `-st-` W77 / F75 W78 / F75 W78 / F76 W79; `-pop-` r78 W86 / r78 F84 W87 / r78 F84 W87 / r78 F85 W88. Tabulated over F21 w0 by s: "F+3 R+6" in every d8 and d16 cell of every frame without a fetch at s, "F+4 R+7" in every base+index+d16 one |
| The immediate store keeps its count floor (s+7, the sixteenth fit's `imm_count`) for every mode but base+index+d16, which writes at s+8; with a displacement its first fetch is at s+3 (s+4) whatever the alignment, as for the other consumers: F19's odd-aligned d8/d16 head is this fact | `F21-none-l0-sti-bw-pO-w0` W79, `-bw_d8-` F75 W79 (model F73 W80), `-bw_d16-` F75 W79 (model F74 F77 W81), `-bw_ix_d16-` F76 W80; at pE `-bw_d8-pE-w0` and `-bw_d16-pE-w0` F72 F75 W79 (exact); F19's `F19-i-none-l0-stimmd8-pO-w0` F75 W79 is the same chain |
| At 1–2 waits the same takes: the fetch at s+3 (base+index+d16 s+4) when the bus is free, the data cycle one cycle after it (s+7 / s+8 at 1 wait, s+8 / s+9 at 2); with a fetch issued at s, the next fetch at s+4 (s+5 at 2 waits) for every displaced mode, base+index+d16 included | 1 wait, marker-less: d8 and d16 "F+3 R+7", base+index+d16 "F+4 R+8"; after "F+0": all "F+0 F+4 R+8"; 2 waits "F+3 R+8", "F+4 R+9", "F+0 F+5 R+10"; `F21-push-l0-ld-bw_d16-pE-w1` = `-bw_ix_d16-pE-w1` F82 F86 F90 R94 (F4's equal pair) |
| The model's seventeenth fit takes a d16 a byte a clock after its EA clocks (so every d16 behaves like silicon's base+index+d16 or later), takes the immediate forms' displacement before the EA clocks (`imm_head=disp_ea`, so their first fetch comes at s+1 or s+2 where silicon's is at s+3), and gives the direct address no EA clocks | `F21-none-l0-ld-dir-pO-w0` model F74 F77 R80 against silicon F75 R78; `F21-none-l0-sti-bw_d8-pO-w0` model F73 W80 against F75 W79 |
| k = 2: the second instance follows the same class split (b8 = bi8, b16 = direct, bi16 apart in all 60 k = 2 cells at 0 waits); several second instances still differ from the model in the fetch after the first data cycle | `F21-push-l0-ld-bw_d16-k2-pO-w0` F84 R87 F92 F95 R98 (model F85 R88 F93 F97 R100); `F21-out-l0-ld-bw_d8-k2-pE-w0` R90 F93 F96 R101 (model F96 F99 R102) |

Reading. The address path has two costs and no others. A displacement costs the clock the
EU unit takes it in, one clock, whatever its width: the two bytes of a d16 go together
when both are queued (the second byte is free unless its word has not arrived), so base,
index and direct with d8 or d16 are one class and the mod 00 forms one clock earlier. The
displacement is taken after the EA clocks (its slot frees and the fetch it allows goes at
s+3, not at s+1), for the immediate forms as for the others. Base+index plus a two-byte
displacement takes one clock more, before the displacement leaves the queue (the fetch it
frees goes a clock later, then everything follows), while base+index plus d8 and
base+index alone take nothing: a three-operand sum with a 16-bit offset, not the index,
not the width. The direct address is a d16 with no register (it runs the base+d16 timing,
not an EA of 0). What the corpus could not order and F21 does: the mode class against the
displacement width (base+index costs only with d16), the d16's second byte against its
alignment (free when queued), the immediate forms' displacement order (s+3, after the EA,
at every alignment), and the consumer (all five alike, POP r/m behind its stack read).
Open after F21: the k = 2 second instances' fetch after the first data cycle, and the
`ES: NOP` lead at one alignment per frame (F20's finding, seen here again in every mode).

Addendum, read off during the rule work (after the facts above were written):

| Fact | Evidence (clocks rel t_fill) |
| --- | --- |
| The immediate store writes 4 clocks after its displacement's take where a load reads or a store writes 3 after it (bus permitting): one clock more, its own; at 0 waits the s+7 floor hides it for d8 and d16 (take s+3), not for base+index+d16 (take s+4, write s+8) | `F21-none-l0-sti-bw_ix_d16-pE-w0` F72 F76 W80; `F21-none-n1-sti-bw_d8-pE-w1` F76 W84 (the d8 taken at 80) |
| An immediate form's displacement due on a fetch's clock past its second (its wait state or last clock) is taken on that word's delivery clock, as `late_read`'s take is | `F21-none-n1-sti-bw_d8-pE-w1` F72 F76 W84, s = 76, the d8 due at 79 on fetch 76's last clock; `-w2` F72 F77 W86 |
| The immediate form's displacement take waits for no fetch: the fetch it frees at s+3 runs and the write still comes at s+7 | `F21-none-l0-sti-bw_d8-pO-w0` F75 W79 |

### The displacement's take state, re-read from F21 (nineteenth fit, 2026-10-22)

Written 2026-10-21 from the recorded F21 runs (chains-F21-w0..w2) and the
eighteenth fit's model state (fit-wp27-hand.json), before any change to the
simulator. s is X's start in the model (right wherever the earlier events
match); clocks rel t_fill unless written s+n. "q" is the number of bytes in
the queue at the end of the clock before the displacement's take (the latched
byte of a delivered word included), "infl" whether a fetch was on the bus
then, "take" the model's clock of X's last address take. Tool:
scratchpad/wp28/ff.py (per run) and tab2.py (tabulation); load, store and
ADD r/m,AW pooled (the immediate store and POP r/m take their last byte
elsewhere and are listed apart).

#### Exact and missed cells by take state (ld, st, add; k = 1)

| waits | mode class | q before take | fetch in flight | take | exact | missed |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | d16 (bw_d16, dir, ix_d16) | 3 | yes | s+3 | 21 | 0 |
| 0 | d16 | 4 | yes | s+3 | 77 | 0 |
| 0 | d16 | 4 | no | s+3 | 5 | 2 (OUT l0, the take on the I/O issue: group d) |
| 0 | d16 | **5** | **no** | s+3 | **0** | **77** |
| 0 | d16 | 6 | no | s+3 | 14 | 0 |
| 0 | d8 (all four d8 modes) | 3 / 4 | yes | s+3 | 112 | 0 |
| 0 | d8 | 4 / 5 | no | s+3 | 96 | 0 |
| 0 | d8 | **6** | **no** | s+3 | **0** | **16** |
| 0 | base+index+d16 | 5 | no | s+4 | 0 | 44 |
| 0 | base+index+d16 | 6 | no | s+4 | 52 | 0 |
| 0 | mod 00 | 3–6 | – | s | 156 | 0 |
| 0 | mod 00 | **7** (6 + a latched byte) | no | s | **0** | **12** (group c) |
| 1, 2 | d16 | 5 | no | s+3 | 0 | 14 each |
| 1, 2 | d16 | 3 / 4 / 5 / 6 | yes / yes / yes / no | s+3 | 175 each | 0 |
| 1, 2 | d8 | **6** | **no** | s+3 | **0** | **48 each** |
| 1, 2 | d8 | **5** | **yes, issued at s** | s+4 (w1) / s+5 (w2), the delivery clock | **0** | **72 each** |
| 1, 2 | d8 | 3 / 4 | yes | delivery clock | 72 each | 0 |
| 1, 2 | d8 | 4 / 5 | no | s+3 | 24 each | 0 |
| 1, 2 | mod 00 | 3–6 | – | s | 168 each | 0 |

#### Facts

| Fact | Evidence (clocks rel t_fill unless s+n) |
| --- | --- |
| Group a is one take state, not one alignment: every d16 mode (and base+index+d16) misses at 0 waits exactly when the queue holds 5 bytes and no fetch is in flight at the take; with 3–4 bytes and a fetch in flight, or 6 bytes, it is exact. The ModR/M's word parity does not separate (the missed cells have the ModR/M at either parity: none pO and PUSH pE have it even, PUSH n1 pO and none n1 pE odd) | d16 q5 no fetch 0/77, q6 14/14, q4+fetch 77/77 (table above); `F21-none-l0-ld-bw_d16-pO-w0` (ModR/M even) and `F21-none-n1-ld-bw_d16-pE-w0` (ModR/M odd) both q5 |
| In those cells silicon fetches at s+3 (the take clock), reads at s+6 and fetches at s+9, right after the read: no back-to-back fetch at s+6. The model's two-byte take leaves 2 bytes stored (5 − 2 − the next opcode into the IR), so with the in-flight word counted the request stays raised through the fetch, the bus unit commits to a back-to-back fetch on its last clock (s+5) and that fetch beats the read | `F21-none-l0-ld-bw_d16-pO-w0` silicon F75 R78 F81 F87 F90, model F75 F78 R81 F89 F92, s = 72; `F21-none-n1-ld-bw_d16-pE-w0` silicon F72 F79 R82 F85, model F72 F79 F82 R85, s = 76 |
| The d8 twin at the same state leaves 3 bytes stored (5 − 1 − 1), no back-to-back fetch, and is exact in all 88 cells; the d16 at 6 bytes leaves 3 likewise (14/14) | `F21-none-l0-ld-bw_d8-pO-w0` F75 R78 F86 (exact) |
| The d8 modes miss at 6 bytes queued with no fetch in flight, at every wait setting (16 cells at 0 waits, 48 at 1 and at 2): silicon runs no fetch at the take and reads at s+5, the mod 00 form's clock, at 0, 1 and 2 waits alike; the first fetch comes right after the read (s+8 / s+9 / s+10). The model takes the d8 and loads the IR on s+3, leaving 4 stored, fetches at s+3 and reads after it (s+6 / s+7 / s+8) | `F21-none-es-ld-bw_d8-pE-w0` silicon R+5 F+8 (model F+3 R+6), s = 79; `F21-none-es-ld-bw_d8-pE-w1` silicon F72 F76 R85 F89, model F72 F76 F83 R87, s = 80; `-w2` silicon R+5 F+10, model F+3 R+8; the mod 00 form in the same cell `F21-none-es-ld-bw-pO-w0` R+5 F+8 |
| The d8 modes miss at 1–2 waits at 5 bytes queued with a fetch issued at s, where the displacement falls due on that fetch's last clock (1 wait) or wait state (2 waits): the model takes it on the delivery clock (s+4 / s+5), loads the IR, counts the IR as room on the delivery clock and fetches there; silicon reads at s+6 (1 wait) / s+7 (2 waits) with no fetch before the read. The same state with 3–4 bytes (fetch at s+4 / s+5 in silicon too) is exact, 72/72 at each wait | `F21-none-n1-ld-bw_d8-pE-w1` silicon F72 F76 R82 F91, model F72 F76 F80 R84, s = 76; `F21-none-es-ld-bw_d8-pO-w2` silicon F+0 R+7, model F+0 F+5 R+10; exact control `F21-none-n1-ld-bw_d8-pO-w1` F+0 F+4 R+8 (4 bytes) |
| Every consumer shows the same two d8 cases: the store writes and ADD reads at s+5 at 6 bytes queued | `F21-none-es-st-bw_d8-pE-w1` silicon W+5 F+9 (model F+3 W+7); `F21-none-es-add-bw_d8-pE-w1` silicon R+5 W+11 (model F+3 R+7 W+13) |
| The immediate store at the d8 1-wait state is exact because nothing changes there: its displacement is not its last operand byte, so the IR cannot load at the take, no fetch is raised, and the write waits for the s+7 count floor | `F21-none-n1-sti-bw_d8-pE-w1` F72 F76 W84 (exact; model take on the delivery clock 80, IR loads only after the immediate at 86); `F21-none-es-sti-bw_d8-pE-w1` F72 F76 W87 |
| What the three missed d8/d16 states share: in each, the fetch the model raises (at the take or on the next delivery) exists only because the next opcode left the queue for the IR on the take clock (or the IR was counted as room on the delivery clock); one more byte stored and the request is not raised. In every exact state the count is the same with or without the IR byte (q ≤ 4 with a fetch, or the d16 at 6, the d8 at 5) | d16 q5: 3 stored without the IR load, 2 with it; d8 q6: 5 / 4; d8 q5 + fetch at 1 wait: 5 + 2 delivered − 1 = 6 / 5 (the room_ir arrival slot then makes 2) |
| No d8/d16 cell misses at 0 waits with a fetch in flight at the take, nor at the d8's 5-byte / d16's 6-byte state; so the miss is not the displacement width, the alignment or the consumer, but the queue count after the take | table above |
| Group c is the mod 00 form at 7 bytes stored (six and a latched byte) at X's start after `ES: NOP`: silicon reads at s+5 as every other mod 00 form; the model reads at s+3. In the model a mod 00 form's s+5 comes from the aborted cycle (abort_fetch: start, ModR/M take and IR load on one clock with exactly a word of room) or a real fetch the take sync waits for; at 7 stored there is no room, no abort, and the read posts at s+3 | `F21-none-es-ld-bw-pE-w0` silicon F72 F75 R84, model R82, s = 79 (model trace: 79 start, no fetch, read 82); its pO twin `F21-none-es-ld-bw-pO-w0` s = 78, aborted cycle 78–80, R83 exact; `F21-push-es-ld-bw-pO-w0` silicon R+5 w+16, model R+3 w+14; 12 of 12 mod 00 cells at 7 stored miss, 156 of 156 at 3–6 exact |
| The immediate store's d16 misses at 0 waits are the same cells as the load's (q5 at the displacement take; the tabulated take there is the immediate's) and silicon writes at s+7 with the fetch after it at s+10, the model writes at s+6+3 behind the back-to-back fetch | `F21-none-l0-sti-bw_d16-pO-w0` silicon F+3 W+7 F+10 F+13, model F+3 F+6 W+9 F+12 |
| POP r/m: its d8/d16 misses at 0 waits are at 7 stored at the displacement's take (the ModR/M take before the stack data) and the OUT/PUSH frames; the same 5-byte d16 state is exact for POP (its write is posted before the take and holds fetches) | `F21-none-l0-pop-bw_d16-pO-w0` r+6 F+12 W+15 exact at q5 |

#### Addendum, read off during the rule work (after the facts above were written)

| Fact | Evidence (clocks rel t_fill) |
| --- | --- |
| The 5-byte d16 state and its delivery-clock twin leave the same bytes after the take (the next opcode and one word, a fetch issued on the take clock), yet silicon runs the back-to-back fetch before the read only in the twin, where the take falls on the delivery clock of the fetch issued at X's start: the difference is the delivery clock, not the byte count | `F21-none-l0-ld-bw_d16-pO-w0` F75 R78 F81 (take 75, bus idle before) against `F21-push-l0-ld-bw_d16-pE-w0` w78 F81 F84 F87 R90 (take 84 on fetch 81's delivery); F4's `push-ld_bw_d16-k1-pE-w0` the same; holding the IR on the delivery-clock take as well gives R87 F90 there and loses 638 runs (F4 push pE d16, F10 `push-lddw`, F14/F15 direct, F21 PUSH l0 and OUT n1 pE) |
| With no fetch issued on the displacement's take clock, the data cycle comes 2 clocks after the take, at every wait setting and for the late take too: s+5 after a take at s+3, s+6 / s+7 after a take on the delivery clock s+4 / s+5 at 1 / 2 waits | `F21-none-es-ld-bw_d8-pE-w0/w1/w2` R+5; `F21-none-n1-ld-bw_d8-pE-w1` R82 (take 80), `F21-none-es-ld-bw_d8-pO-w2` F+0 R+7 (take s+5); with the IR held and no floor the model reads a clock early in all of them (271 runs) |
| At 1–2 waits the late take on the delivery clock fetches there with 4 bytes stored before it (one of them the delivered word's latched second byte) and not with 5: the latched byte counts on that clock | `F21-none-n1-ld-bw_d8-pO-w1` F76 F80 R84 (4) against `F21-none-n1-ld-bw_d8-pE-w1` F76 R82 F91 (5) |
| The immediate store's d16 in the group-a cells: at 0 waits no fetch on the delivery clock s+6 and the write at its s+7 floor, the fetch after it; at 1 wait the fetch on the delivery clock s+7 (the floor clock) and the write after it. The model's s+6 fetch at 0 waits goes while the write is in its fetch-free setup clock (count 2 of 3); the hold rule does not hold it because hold_count=ahead subtracts the 2 immediate bytes still to take | `F21-none-l0-sti-bw_d16-pO-w0` F75 W79 F82 (model F75 F78 W81); `-w1` F75 F79 W83 (exact) |
| PUSH-frame base+index+d16 at pE 0 waits: silicon fetches on the displacement's take clock s+4, not on the delivery clock s+3 before it; the model counts the empty IR as room on that delivery clock (room_ir arrival) and fetches at s+3 | `F21-push-l0-ld-bw_ix_d16-pE-w0` silicon w78 F81 F85 R88 F91, model F81 F84 R87 F90 (the doc's item-4 F4 base+index+d16 runs are the same state) |
| The `ES: NOP` mod 00 cells (group c) start X with 7 bytes stored (6 and the delivered word's second byte still latched because the queue was full on its delivery clock); not counting that byte while it waits in the latch makes the request rise a clock later and fetch (F80), not abort: the read stays early | `F21-none-es-ld-bw-pE-w0` silicon F72 F75 R84; `latch_wait=uncounted` F75 F80 R85 (refuted, −274) |

### The free clocks' eve, the older fetch and the mod 00 floor, re-read from F21, F19, F5 and F20 (twentieth fit, 2026-10-22)

Written 2026-10-22 from the recorded runs and the nineteenth fit's model state
(fit.json = fit-wp28-hand.json, 15424/17822), before any change to the simulator.
Clocks rel t_fill unless written s+n (s = the instruction's start in the model, right
wherever the earlier events match) or t+n (t = the clock of the decision tabulated).
Tools (scratchpad wp29/): hold.py logs every clock on which a posted memory data request
(not I/O, not issued) exists, the bus is free and a fetch is wanted, with the request's
setup count, the queue count, the decoder's outstanding bytes, the bus history, the
model's choice and silicon's event on that clock; htab.py tabulates it; dc.py logs every
memory form's first data cycle by offset from its start (model and silicon); lat.py logs
every port-form IN/OUT starting on the clock after it waited for the data latch. Only
decisions with every earlier event matching silicon are counted.

"ph" is a posted request's setup phase: count − (setup − setup_free), so ph = 0 is the
clock before its first fetch-free setup clock, ph ≥ 1 inside them. "Delivery-clock
request": the fetch request first raised on the clock after a fetch's last clock (its
word's delivery). "Run": that fetch itself started on the clock after an earlier fetch's
last clock.

#### Tabulation 1: a fetch wanted at ph = 0 (all classes, all waits, prefix matched)

| class | queue count / outstanding bytes | delivery-clock request | run | model fetches | silicon fetches | cells |
| --- | --- | --- | --- | --- | --- | --- |
| store_imm write | 4 / 2 | yes | no | yes | **no** | **57** |
| store_imm write | 3 / 2 | yes | no | yes | **no** | **8** |
| store_imm write | 4 / 2 | yes | yes | yes | yes | 19 |
| store_imm write | 3 / 2 | yes | yes (b2b committed) | yes | yes | 4 |
| rmw_imm read | 3–4 / 2 | yes | no | yes | **no** | **4** |
| pop_mem stack read | 4 / 1–2 | yes | no | yes | **no** | **26** |
| push write | 3 / 0 | yes | no | yes | **no** | **15** |
| pop_mem read, push write | 4 / 0 | yes | no | no (le_q holds) | no | 97 |
| every class | 3–4 / 0 | no (an older request) | – | as le_q | as le_q | 6,300+ exact, 3 rmw `F14-g-out-shl_bw_cl` fetch, exact |

No ph = 0 delivery-clock request outside a run is fetched by silicon (0 of 207); every one
inside a run is (23 of 23).

#### Facts

| Fact | Evidence (clocks rel t_fill unless s+n / t+n) |
| --- | --- |
| Group a (1) is not the queue count. At the clock before a posted request's first fetch-free setup clock, a fetch first requested on the delivery clock of the fetch that just ended is never run by silicon, whatever the queue holds (3 or 4 bytes counted, 0–2 still to take), for the immediate store, the immediate RMW, POP r/m's stack read and PUSH alike: 110 cells, every one a model fetch. `hold_count=ahead`'s discount is not the handle: PUSH's write at 3 bytes with nothing outstanding is held as the store at 4 with 2 | `F21-none-l0-sti-bw_d16-pO-w0` s = 72, the write posted at 76 (grp 3, the last fetch-free), fetch 75 delivers at 78 with the write at count 2 of 3: silicon F75 W79 F82, model F75 F78 W81; `F19-i-push-n1-stimm-pO-w0` PUSH posted at 95 (setup 7, the last 3 free), fetch 95 delivers at 98 at count 4: silicon F95 F99 w102, model F95 F98 w103; `F21-push-l0-pop-bw_d8-pE-w0` POP's stack read posted at 81, fetch 81 delivers at 84 at count 4: silicon F81 r87, model F81 F84 r89 |
| The F5 run `hold_count=ahead` was adopted on is not at ph = 0: its read is in I/O recovery at count 0 of 3, ph −2, with a fetch requested long before (held by the I/O); every such cell fetches in silicon (39 of 39 rmw_imm at ph −2, 4 bytes) | `F5-out-add_m_imm-k1-pE-w0` I/O 84, F87, R91 (exact) |
| The exception is a fetch run: when the fetch that just ended was itself started on the delivery clock of an earlier one (the displacement taken on that delivery clock), silicon runs the next delivery-clock fetch at ph = 0 too (23 of 23). These are the cells where `ir_load=disp_data` already lets the IR load at the take | `F21-push-l0-sti-bw_d16-pE-w0` s = 81: F81, F84 (on fetch 81's delivery, the d16 taken there), F87 on fetch 84's delivery, W91; `F21-out-n1-sti-bw_d16-pE-w0` F+0 F+3 F+6 W+10 |
| After the held clock: the immediate store writes on the next clock (its last setup count, data first against a request raised a clock earlier), the fetch 3 clocks later; PUSH and POP run the held fetch on the next clock, their first fetch-free one, and count their remaining fetch-free clocks through it (as `free_run=run` does for a fetch first requested inside them) | sti: t+1 W, t+4 F in 49 of 57 cells (`F21-none-l0-sti-bw_d16-pO-w0` W79 F82); PUSH: `F19-i-push-n1-stimm-pO-w0` F99 (t+1), w102 = t+4 (counting through 99–101); POP: `F21-push-l0-pop-bw_d8-pE-w0` r87 = t+3, the read's 3 free clocks 85–87 |
| The immediate store's 1-wait twin is not at ph = 0: the delivery clock is its last setup clock (count 3 of 3, issuable), where a request raised on the clock the write became issuable goes first (`arbiter=b2b`) | `F21-none-l0-sti-bw_d16-pO-w1`: fetch 75 delivers at 79, the write at count 3 there; F75 F79 W83 (exact) |
| In the run cells silicon then writes one clock later than the model, t+4 after a fetch issued at t (model t+3): one idle clock between that fetch and the write, where a load in the same cell reads right after the fetch (`F21-push-l0-ld-bw_d16-pE-w0` F87 R90). Not explained by this re-read (23 cells) | `F21-push-l0-sti-bw_d16-pE-w0` silicon F87 W91, model F87 W90 |
| 8 of the 65 store cells at ph = 0 (the OUT frame l0 pE, stored 3) fetch on t+1 and write at t+4 in silicon, where the stored-4 cells write at t+1 | `F21-out-l0-sti-bw_d16-pE-w0` I+4 F+7 F+11 W+14 against `-pO-` F+2 I+5 F+8 W+12 |
| Group a (2), the OUT follower: a port-form OUT that starts on the clock the data latch frees, where the fetch the latch wait held (`wlatch_hold`) issues on the same clock, waits that fetch out when the queue stores fewer than 3 bytes, as `io_b2b` makes it wait out a back-to-back fetch below `io_b2b_q` 3: 14 of 14 such starts at 2 stored miss by +3 at the I/O; 400 of 400 at 3–4 stored are exact | `F19-i-out-l0-stimm-pO-w0` the store writes at 92 (latch busy to 95), the OUT and fetch 96 on one clock with 2 stored: silicon F96 F99 F102 I109, model I106; the twin `-pE-w0` with 3 stored, OUT and fetch 95 on one clock: F95 F98 I105 exact |
| Group a (2), the PUSH follower is the ph = 0 hold above (PUSH's stack write at ph = 0 with 3 bytes and nothing outstanding) | `F19-i-push-n1-stimm-pO-w0` F95 F99 w102 |
| Group b (i), POP r/m d8/d16 at 0 waits in the PUSH l0 pE and OUT n1 pE cells, is the ph = 0 hold on POP's stack read (26 cells at ph = 0 with 4 bytes and the ModR/M or displacement outstanding) | `F21-push-l0-pop-bw_d8-pE-w0` silicon F81 r87 F93 W96, model F81 F84 r89; `F21-out-n1-pop-bw_d8-pE-w0` silicon F88 r94 F100 W103, model F88 F91 r96 |
| Group b (ii), POP r/m base+index+d16 at 1–2 waits: the write is one clock later than the d16 twin's (the extra EA clock runs before the displacement's take, the write's setup counts from the stack data, not the take): silicon writes 2 clocks after the take (`dfloor`), the fetch after; the model's write is issuable on the d16 twin's clock, the request raised on that clock by the later take goes first | `F21-none-n1-pop-bw_ix_d16-pE-w1` silicon r82 W92 F96, model r82 F91 W95 (take at 90); its d16 twin `F21-none-n1-pop-bw_d16-pE-w1` take 89, W91 F95 exact; at 2 waits `-bw_ix_d16-pE-w2` W95 against the twin's W94; `F21-push-l0-pop-bw_ix_d16-pE-w1` r90 W100 F104 (model F99 W103) |
| POP's memory write is posted at the stack data, before the displacement's take, so the nineteenth fit's `disp_floor` (applied when a request is posted) never reaches it | sim/eu.py `_submit`: dfloor_at set at the take, applied at the next post |

#### Tabulation 2: the first data cycle of a ModR/M memory form, offset from its start

Prefix-matched, every family but refresh-on, 9,420 data cycles. Silicon minima per mode
and wait (count at the minimum):

| mode | w0 | w1 | w2 |
| --- | --- | --- | --- |
| mod 00 base / base+index | s+5 (838 / 81) | s+5 (135 / 25) | s+5 (135 / 25) |
| d8 and d16 (base_disp, base_index_disp) | s+5 (11 / 10) | s+5 (24 / 24) | s+5 (24 / 24) |
| base+index+d16 | s+7 | s+8 | s+9 |
| direct (A1/A3, no ModR/M) | s+6 | s+7 | s+8 |

No ModR/M memory form's first data cycle comes before s+5 in silicon, in any mode, class
or wait setting. The model issues a mod 00 form's first data cycle before s+5 only at 7
stored (6 + a latched byte) at the start, s+3 in all 33 such cells (13 loads, 13 stores,
7 RMWs; F20 and F21), all misses; at 3–6 stored it is at s+5 or later and matches.

| Fact | Evidence |
| --- | --- |
| Group c: a mod 00 form's first data cycle is at s+5 or later at every wait; the aborted cycle is the model's way of getting s+5 when the queue has exactly one word of room, not the mechanism: at 7 stored there is no room, no abort, no fetch, and silicon still reads at s+5. It is the same clock as a displaced form's floor with its displacement taken at s+3 (dfloor 2): ModR/M at s, the EA clocks s+1–s+2, the address step s+3 (where a displacement is taken, empty for mod 00), the data cycle no earlier than 2 clocks after it | `F21-none-es-ld-bw-pE-w0` s = 79, 7 stored, no fetch: silicon F72 F75 R84, model R82; `-pO-w0` 6 stored, aborted cycle 78–80, R83 exact; `F20-r-push-l0-pfxnop-ld-pO-w0` M+3 against S+5; the d8 at 6 stored with no fetch at its take `F21-none-es-ld-bw_d8-pE-w0` R+5 |

#### Addendum, read off during the rule work (after the facts above were written)

| Fact | Evidence (clocks rel t_fill) |
| --- | --- |
| The held fetch dates from the clock after the hold. Where it is still wanted there (3 bytes stored at the hold, 4 once the latched byte goes in) it goes before the store or RMW that has just become issuable (10 of 10: 8 stores, 2 immediate RMWs, all the OUT frame l0 pE and its F5/F19 twins). Where it is not wanted (4 stored at the hold) the write goes on that clock (49 cells). POP's stack read with 4 bytes stays fetch-free | `F21-out-l0-sti-bw_d16-pE-w0` held at 90, F91 W94; `F5-out-add_m_imm_d16-k1-pE-w0` F91 R94; `F21-push-l0-pop-bw_d8-pE-w0` r87 with no fetch at 85 |
| The run cells' idle clock is that of a fetch the free_hold rule lets run at the free clocks' eve. When the request is already issuable and a run's delivery-clock fetch goes first (`arbiter=b2b`), silicon leaves the idle clock at 0 waits (3 runs) but not at 1–2 waits (72 runs lost by the same rule there). That is a knob dependence and is not encoded. Counting a fetch's wait state as the fetch-free clock instead, everywhere, is refuted (+8 −170) | `F5-push-add_m_imm_d16-k1-pE-w0` F87 R91 (model R90); `F5-push-st_imm_bw_d16-k1-pE-w1` exact without the clock |
| The OUT follower at 1–2 waits does not wait for the latch: the store ends, the OUT starts beside a fetch requested on an earlier clock that waited for the bus, with 2 stored (16 cells, all +3 at the I/O). So the handle is a fetch requested earlier and issuing on the start clock, not the latch. MOV r,imm and PUSH in the same state start beside it (100 of 100 exact). Of the forms with a ModR/M byte only the immediate store is observed at 2 stored (13 cells, all misses; 3 stored exact for every class); waiting it out closes 4 of them | `F21-out-l0-sti-bw-pO-w1` W93, the OUT at 97 beside fetch 97 (requested 95): silicon F97 F101 F105 I113 (model I110); `F21-out-l0-sti-bw_d16-k2-pO-w0` W108 (model W107); still missed `F5-out-st_imm_bw-k2-pO-w0` W108 (model W105) |
| The mod 00 form's s+5 is counted from its start, not from its EA step: when the ModR/M take's sync waits for a fetch issued at s, the EA step moves but the read does not (counting from the step loses 2,882 runs) | `F4-push-ld_bw-k1-pO-w0` s = 81, fetch 81–83, the EA step from 84, silicon R86 = s+5 |
| The aborted cycle still carries other runs once the mod 00 floor is in (`abort_fetch=False` −1,034): it is not only the s+5 | F3 `push-shl1-k2` and others |
| POP's write floored at its displacement holds fetches while it waits out the floor, as its setup does. Floored without the hold, the fetch the take raised goes on the clock the write would have issued | `F21-none-n1-pop-bw_ix_d16-pE-w1` without the hold F91 W95, with it W92 F96 (silicon W92 F96) |

### The take on an I/O issue clock, the IR's room inside the EA clocks, the RMW's ALU clocks through a fetch, the immediate form's start beside one (twenty-first fit, 2026-10-22)

Written 2026-10-22 from the recorded runs and the twentieth fit's model state
(fit.json = fit-wp29-hand.json, 15640/17822), before any change to the simulator.
Clocks rel t_fill unless written s+n (s = the instruction's start in the model, right
wherever the earlier events match) or t+n (t = the clock of the decision tabulated).
Only decisions with every earlier event matching silicon are counted ("prefix matched");
refresh-on runs are left out of every tabulation.

Tools (scratchpad wp30/): take.py logs every displaced memory form's displacement take clock
(after the EU's tick and the IR load, before the bus choice) with the queue, IR, request and
I/O state and the model's and silicon's next fetch and data cycle relative to the take;
ioiss.py logs every I/O issue clock (what changed in the queue on it, the request's age) with
the model's and silicon's next fetch relative to the I/O's last clock; irroom.py logs every
clock on which a fetch is wanted only because the empty IR counts as a seventh slot (room >= 2
with it, < 2 without); rmw.py pairs every read with the write to the same address (the RMW)
in silicon and model; start.py logs every instruction start on a clock a fetch issues;
ttab.py prints take.py rows per run.

#### Tabulation A1: a displacement taken on the clock an I/O cycle issues

ioiss.py over F1-F21 (30,156 I/O issues). Every I/O issue on whose clock the decoder took
an operand byte before the bus choice, and every fetch after it, prefix matched:

| state on the I/O issue clock | I/O length | model next fetch | silicon next fetch | cells |
| --- | --- | --- | --- | --- |
| a displacement taken (base+index+d16 only, OUT frame lead l0), request raised before (pE) | 3 | I/O end + 1 | **I/O end + 2** | **39** |
| the same on a word's delivery clock, the request raised there (pO), IR loaded (ld, st, add) or not (sti) | 3 | I/O end + 1 | **I/O end + 2** | **39** |
| no take, request raised before | any | I/O end + n | = model | 2,264 |
| no take, a word delivered on the issue clock (the request raised there) | any | I/O end + n | = model | 5,521 of 5,533 (6 F14 T TEST [0C00h] pO +3, 6 F14 T CMP pO +2: other findings) |
| no take, no delivery, no request standing | any | I/O end + n | = model | 6,761 |

take.py over F4 F5 F14 F15 F16 F19 F20 F21 (3,816 displacement takes): silicon's first fetch
after a displacement's take, prefix matched:

| take state | silicon first fetch | cells |
| --- | --- | --- |
| a fetch issued on the take clock | t+0 | 2,631 (519 base+index+d16) |
| take on the clock before an I/O issue (d8, d16, direct, base+index+d8 under OUT l0) | t+4 = I/O end + 1 | 195, exact |
| take on the I/O issue clock (base+index+d16 under OUT l0) | t+4 = I/O end + 2 | 78, model t+3 |
| take on the I/O's last clock (`TEST [0C00h],AW`, F14 T pE) | t+1 | 6, exact |
| no fetch at the take, the data cycle first | after the data cycle | 648 (POP r/m 285, ld 143, sti 92, st 64, add 64), the data cycle exact in every one |

#### Tabulation A2: a fetch wanted only through the IR's seventh slot, a displaced form before its take

irroom.py, prefix matched, a ModR/M memory form with a displacement, no data request posted
yet, the delivery clock (room_ir=arrival_idle counts the empty IR there):

| where the EU is | clock | cells silicon fetches / cells |
| --- | --- | --- |
| base+index+d16, in its third EA clock (`ea.base_index_disp16` 3: s+1 to s+3), the displacement not due | s+3 | **0 / 18** (ld 9, st 3, add 3, sti 3; the PUSH l0 and OUT n1 frames, pE w0) |
| an immediate store (C6/C7 d8 imm), its EA clocks done, the displacement due but not taken on the clock | s+3, s+4, s+5 | 135 / 135 |
| `TEST [0C00h],AW` (load_alu) in its `fdisp` (nowait) clocks | s+3 to s+5 | 9 / 9 |
| base+index+d16 store_imm, EA done, the displacement taken on the clock (1-2 waits) | s+4, s+5 | 18 / 18 |
| any displaced form on its start clock (ModR/M taken there) | s+0 | 486 / 486 |

#### Facts, group A (base+index+d16)

| Fact | Evidence (clocks rel t_fill unless s+n / t+n) |
| --- | --- |
| A1. Under the OUT frame at lead l0 the base+index+d16 forms take their displacement on the marker I/O's issue clock (s+4 at pE, the extra EA clock s+3 pushing the take onto it; s+5 to s+7 at pO on the delivery clock of fetch s+2); their d16, direct, d8 and base+index+d8 twins take theirs one clock before the issue. That is the only state in the corpus in which a displacement is taken on an I/O issue clock: 78 takes (54 F21 runs, k = 1 and the first instance of k = 2, ld/st/sti/add and `[BP+IY+d16]`; 24 F4 loads) | take.py: `F21-out-l0-ld-bw_ix_d16-pE-w1` take 85 = I/O 85; `-bw_d16-pE-w1` take 84, I/O 85; `-bw_ix_d16-pO-w0` take 85 on fetch 82's delivery = I/O 85 |
| A2. After such a take silicon starts no fetch on the I/O cycle's first free clock (the clock after its last): the first fetch is one clock later than every other fetch after an I/O, 78 of 78, at every wait (the I/O 3 clocks in each), every parity, whether the request was raised clocks before (pE, IR held) or on the take clock by the delivery (pO, IR loaded on the delivery-clock take) and for every consumer; everything later moves with it | `F21-out-l0-ld-bw_ix_d16-pE-w1` I85–87, silicon F89 R93, model F88 R92; `F4-out-ld_bw_ix_d16-k1-pO-w2` I87 F91 R96 (model F90 R95); the twins F88 R92 exact |
| A3. Silicon's first fetch after a displacement take is never 1–3 clocks after it except where the take is on an I/O's last clock (6 TEST [0C00h] cells, t+1): with the take on the I/O issue clock the fetch lands at t+4, the twins' take a clock before the issue also t+4 (195 exact). So the reading "a fetch no earlier than 4 clocks after the take" and "no fetch on the I/O's first free clock after a take on its issue clock" are the same on this corpus; the I/O length is 3 in every cell, so the corpus cannot tell them apart either | take.py rows above |
| A4. The model's data request is in I/O recovery on that clock (`io_recover` 2: not issuable until I/O end + 3) and does not hold the fetch (1–2 bytes counted); the clock goes idle in silicon, neither the fetch nor the read | `F21-out-l0-ld-bw_ix_d16-pE-w0` I84–86, silicon idle 87, F88, R91 |
| A5. The model also clears `ir_load=disp_data`'s hold when the OUT's I/O issues (machine.py clears the hold on any EU-owned cycle's issue, the I/O is one): the IR loads on the I/O issue clock in both the ix forms and the twins. Not observable on its own here (the request stands either way) | trace `F21-out-l0-ld-bw_d16-pE-w1` L at 85 |
| A6. Under PUSH l0 pE w0 and OUT n1 pE w0 the base+index+d16 forms start on the delivery clock of a fetch (s = 81 resp. 88), run EA clocks s+1–s+3, and the next word is delivered at s+3 inside the third EA clock with 3 bytes stored plus 2 delivered: the model counts the empty IR as a seventh slot there and fetches at s+3; silicon fetches at s+4, the take clock (18 of 18, the IR's room deciding). Where the EU has finished its EA clocks (the displacement due on the delivery clock, or the immediate store's displacement waiting a clock) silicon does fetch through the IR's slot (every such cell in Tabulation A2; the file first gave this as 162 of 162, a sum of that table's rows the agent later flagged as a miscount) | `F21-push-l0-ld-bw_ix_d16-pE-w0` silicon w78 F81 F85 R88, model F81 F84 R87; `F21-out-n1-ld-bw_ix_d16-pE-w0` silicon F88 F92 R95, model F88 F91 R94; `F19-i-push-l0-stimmd8-pO-w0` s+3 fetch through the IR (exact) |
| A7. The IR cannot load during those EA clocks under `ir_load=disp_data` (only the displacement's take on a delivery clock or the first data cycle frees it), so the room it is counted as is room for a byte that cannot leave the queue before the word lands. The nineteenth fit's refuted "held IR no room from the clock after the start" (+70 −66) covered every clock up to the take, including the immediate store's and TEST [dir]'s (fetching cells above) | doc, nineteenth fit refuted list |

#### Tabulation B: an RMW's read and write with a fetch between (rmw.py, F5 F14 F15 F16 F19 F20 F21, prefix matched)

| class | fetch between | silicon R→W at w0 / w1 / w2 | model | cells |
| --- | --- | --- | --- | --- |
| rmw (ADD/AND r/m,reg) | none | 5 / 6 / 7 (2 ALU clocks after the read) | = | 1,500+ |
| rmw (ADD/AND r/m,reg) | one, issued right after the read | **6 / 8 / 10** (the write on the clock after the fetch) | 7 / 9 / 11 | **15** (F21 `add` d16 and direct k = 1, 2; F15 A `AND [0C00h],AW`; all OUT l0 pE) + 6 base+index+d16 not prefix matched |
| rmw XCH [0C00h],AW (`dest_route` 2 clocks) | one, right after the read | 8 / 10 / 12 (two clocks after the fetch) | = | 3 |
| rmw_imm | one, right after the read | 6 / 8 / 10 | = | 145 |

#### Facts, group B

| Fact | Evidence |
| --- | --- |
| B1. An ALU RMW's write goes on the clock after a fetch issued on the clock after its read: the fetch does not stall the ALU clocks, the write waits only for the bus (15 of 15, every wait); the model's `rmw.setup_free` 3 needs three fetch-free clocks and writes a clock later | `F21-out-l0-add-bw_d16-pE-w0` R90 F93 W96 (model W97); `F15-a-out-and_dir_aw-pE-w0` the same |
| B2. XCH, the RMW with the `dest_route` clocks before its write, writes two clocks after such a fetch: its 2 routing clocks run after the fetch, its ALU clocks through it (setup 5 = alu 3 + dclk 2) | `F14-t-out-xch_dir_aw-pE-w0` R90 F93 W98 (exact; `rmw.setup_free` 1: W97) |
| B3. `rmw.setup_free` 1 alone gains the 15 and loses the 3 XCH cells and 2 F17 refresh-on `ADD [BW],AW` cells (the refresh at 92 moving to 94 behind the write's earlier issuable clock): +15 −5; the knob dependence the eighteenth to twentieth fits reported ("prefers 1 at even parity, k = 1–2, the OUT frame, n = 0") is this state | sc-sf1.txt; `F17-s-n0-rmw-pE-w0` silicon refresh 92 W97, setup_free 1 refresh 94 W99 |

#### Tabulation C: an immediate store starting on a fetch issue clock (start.py, prefix matched)

| class, state at the start | cells silicon = model | cells silicon later |
| --- | --- | --- |
| store_imm, 2 stored (one latched), on a fetch run's delivery clock, the fetch requested and issued on the start clock, mod 00 or d8 | 0 | **9** (+3 at w0, +4 at w1–2: the write at s+10 / s+12 / s+14) |
| the same, d16 or direct | 4 (write at s+10, model too) | 0 |
| every other ModR/M class in that state (load, store, rmw, pop_mem, mul, shift_imm) | 726 | 0 |
| store_imm at 3–4 stored in that state | 256 | 0 |

#### Facts, group C

| Fact | Evidence |
| --- | --- |
| C1. The k = 2 follower is the second immediate store (C7 imm16) starting with 2 bytes stored, one of them the latched second byte of the word delivered on that clock, on the delivery clock of a fetch run, beside a fetch requested on that clock: silicon writes 3 clocks later than the model at 0 waits (the fetch's length later at 1–2 waits), as if the store started after that fetch; the write's clock (s+10 at w0) is the one the d16 and direct forms reach in both silicon and model | `F21-out-l0-sti-bw_d8-k2-pE-w0` start 97, F94 F97 F100 W107 (model W104); `F5-out-st_imm_bw-k2-pO-w0` start 98, W108 (model W105); `F21-out-l0-sti-dir-k2-pO-w0` W108 exact |
| C2. No other class waits out a fetch in that state (726 of 726 start beside it, exact); the immediate store is the only class whose write needs all its operand bytes (the immediate) after its address, so the 2 stored bytes do not cover its operands (ModR/M, d8, imm16: 4 bytes at d8) | start.py |

#### Addendum, read off during the rule work (after the facts above were written)

| Fact | Evidence (clocks rel t_fill) |
| --- | --- |
| The held clock after a take on the I/O issue clock is the I/O cycle's, not only the fetch's: the immediate store's group setup (`grp_free_bus`, which counts no clock of an I/O cycle or its recovery) counts from the clock after it, so its free clocks' eve falls on the next delivery clock and `free_hold` holds that fetch a clock. Holding only the fetch (recovery from the I/O's real last clock) closes the loads, stores and RMWs but leaves those two (+84 against +86 with the rest of the package) | `F21-out-l0-sti-bw_ix_d16-pE-w0` I84–86, held 87, F88, idle 91, F92 W95 (fetch-only hold: F88 F91 W94); `-pO-w0` W93 F97 |
| The ADD base+index+d16 cells under OUT l0 pE (6, k = 1 and 2) are group B's state once group A's clock is in: read, a fetch on the write's first setup clock, the write on the clock after the fetch | `F21-out-l0-add-bw_ix_d16-pE-w1` closed by `rmw_alu` |
| The refresh-on F17 `ADD [BW],AW` cells pin `refresh_accept`'s window at the write's first setup clock (`count == setup - setup_free + 1` with setup_free 3): an RMW's ALU clocks counting through a fetch must not move that window, so the rule is the count through a fetch in flight, with `rmw.setup_free` kept | `F17-s-n0-rmw-pE-w0` refresh 92, W97 (setup_free 1: refresh 94, W99) |
| No fetch request at all inside a displaced form's EA clocks (the room capped below a word, not only the IR's slot) is refuted: +1 −230 (F21 132, F4 69, F19 12, F5 11, F14 3, F15 3); silicon fetches inside the EA clocks with room for a word without the IR (234 cells at s+2 with 3 bytes of room) | eaclk.py |
| The immediate form's wait is sharp at `io_b2b_q` 3 bytes stored before the ModR/M take: one more loses 134 (F5 d16 forms under the OUT frame and others start beside the fetch at 4); restricting it to mod 00 and d8 gains 2 fewer (the d16 base+index k = 2 cells close only with it) | sc-c-4.txt, sc-c-short.txt |
| Left in F21 (3 runs): the second instance of a base+index+d16 store or immediate store at k = 2 under OUT l0 pE w0 and PUSH l0 pO w0. At its third EA clock it is in the same counted state as first instances that silicon holds (5 bytes counted, 4 stored, room 1 without the IR, a delivery) but silicon fetches; and a back-to-back fetch committed at the end of a fetch inside the EA clocks (room 2) that silicon does not run. Both directions in 5 decisions, no state in the model separates them | `F21-push-l0-sti-bw_ix_d16-k2-pE-w0` @98 silicon fetches; `F21-out-l0-st-bw_ix_d16-k2-pE-w0` b2b at 96, silicon F98 (model F97) |

### The left-out write's slot and TEST's fixed lookup, re-read from F19, F14, F15, F16 and F5 (twenty-second fit, 2026-10-22)

Written 2026-10-22 from the recorded runs and the twenty-first fit's model state
(fit.json = fit-wp30-hand.json, 15758/17822), before any change to the simulator.
Clocks rel t_fill unless written s+n (s = the instruction's start in the model, right
wherever the earlier events match), R+n (R = the read's issue clock), D+n (D = the read's
data clock, R + 3 + w) or slot+n (the clock the model issues the left-out write's slot).
Only decisions with every earlier event matching silicon are counted ("prefix matched");
refresh-on runs are left out of every tabulation.

Tools (scratchpad wp31/): nw.py logs every left-out-write slot (`issue_nowrite`: clock, whether
a fetch runs in it, the queue's counted bytes and room, the request flag, the back-to-back
commitment) with both event lists and the model's starts; tab.py prints them per read;
slots.py classifies the slots by state against silicon's fetch on the slot clock; rd.py logs
every model start (opcode, ModR/M, class, queue state, aborted cycles) and rdtab.py tabulates
the first data cycle's offset from the start by form, mode and head (fetches at s-3..s, an
aborted cycle at s); route2.py logs the queue count on a read's data clock D and the first fetch
after the read in both; tabB.py prints a run's events from its first read to the closing marker.

#### Group A: the left-out write's slot (81 /7, 83 /7, F7 /0 under `grp_read=rmw_slot_any`)

How the forms are templated: `CMP [BW],imm16` (81 /7) and `CMP [BW],imm8` (83 /7) decode as
`nowrite` and run class `rmw_imm` (templates.grp_class): the head, the read posted with the
group setup (81: `rmw_imm.grp` 3; 83: `grp1` 2, `imm8_grp=own`; `grp_free` 1), the immediate
taken once the read is on the bus (`imm_order=after_issue`), then a `nowrite` request with the
write's setup (`max(alu, setup)` = 3, posted at the read's data clock) whose issue is the slot.
The count floor is `istart` 5 + the immediate's bytes (s+7 for 81, s+6 for 83). The one-byte
immediate leaves one byte more in the queue at the slot: that is the only difference the
slot sees between the two. `TEST [BW],imm16` (F7 /0) runs the same template (nowrite, two
immediate bytes) with TEST 84/85's group setup plus `fgrp` (`grp_fixed=test`).

##### Tabulation A1: the slot, by state (slots.py over F5 F14 F15 F16 F19, every cmp/test/add imm run)

| state on the slot clock (slot = R + 5 + w unless a fetch ran after the read) | model | silicon fetches on the slot clock | cells |
| --- | --- | --- | --- |
| no bus cycle since the read, 4 bytes counted, room 2 (request flag raised) | fetch | yes | 109, all exact here |
| a fetch ended on the clock before (its word lands on the slot clock), 4 counted, room 2 | fetch | yes | 38 |
| a fetch ended on the clock before, its word landing, **5 counted, room 1**, no request flag | fetch (`rmw_slot_any`: a byte of room) | **yes** | 119 |
| no bus cycle since the read, **5 counted, room 1**, no request flag | fetch | **no** | **31 of 31** (every one 83 /7: F19 I `cmpimm8`) |

The 31: `F19-i-push-l0-cmpimm8-pE-w0/1/2`, `-push-l0-cmpimm8-k2-pE-w0/1/2` (first instance),
`-k2-pO-w0/1/2` (second), `-push-n1-cmpimm8-pO-w1/2`, `-push-n2-cmpimm8-pE-w1/2`,
`-push-es-cmpimm8-pE-w1/2`, `-out-l0-cmpimm8-k2-pE-w0/1/2` (second), `-out-n1-cmpimm8-pE-w0/1/2`,
`-out-n2-cmpimm8-pO-w1/2`, `-out-n3-cmpimm8-pE-w1/2`, `-out-es-cmpimm8-pO-w1/2`,
`-none-n1-cmpimm8-pE-w1/2`, `-none-es-cmpimm8-pO-w1/2`. At 0 waits the 83 form's read and the
fetch before it fall so that a fetch runs R+3..R+5 at one alignment per lead (slot after a
fetch, room 1, silicon fetches) and none at the other (slot after the read, room 1, silicon
does not): that is item 1's "a fetch at one alignment and not the other". The 81 form never
reaches the second state (one byte fewer stored).

##### Tabulation A2: the end of a slot with no fetch (the 31 cells, the PUSH frame read off the PUSH write: s = w - 6)

| wait | slot | silicon: the next instruction starts | model (`issue_nowrite`: no fetch → a write cycle's length) |
| --- | --- | --- | --- |
| 0 | R+5 | **slot+2** (`push-l0-cmpimm8-pE-w0` R87 w100: PUSH at 94) | slot+3 (but the model fetches there: slot+3, w101) |
| 1 | R+6 | **slot+2** (`-pE-w1` R90 w104) | slot+4 |
| 2 | R+7 | **slot+2** (`-pE-w2` R93 w108) | slot+5 |

Every cell of the 31 followed by the PUSH (12) has the PUSH write at slot+8 (= start slot+2 + 6); the
marker-less and OUT-frame cells fit the same start (below). With no cycle to run the slot is
no bus cycle and carries no wait states.

##### Tabulation A3: the closing OUT after a slot that ran a fetch (OUT frame, prefix matched to the slot)

| wait | model I/O | silicon I/O | cells |
| --- | --- | --- | --- |
| 0 | slot+13 / slot+14 | **slot+14 / slot+15** | **34 of 34 one clock later** (F19 I `cmpimm`, `cmpimm8` every lead both parities, the k = 2 second instances; F5 `out-cmp_m_imm` k1/k2/k1-odd; F15 A `out-cmp_bw_imm`, `out-test_bw_imm`, F14 T `out-test_bw_imm` w0) |
| 1 | slot+14 / +16 | = | 31 |
| 2 | slot+15 / +18 | = | 31 |

At 0 waits the slot's fetch is 3 clocks and the OUT starts on the clock after it (slot+3);
at 1–2 waits it is 4–5 clocks. The ADD/AND twins in the same cells (a real write at the same
clock) are exact: their write fills the data latch for `wlatch` 4 clocks from its issue, and
the port-form OUT does not start while it is busy (`wlatch_cls=port`): the OUT after
`ADD [BW],imm16` starts at W+4 (`F19-i-out-l0-addimm-pE-w0`, next start s+10 against s+9 for
CMP in the model).

##### Facts, group A

| Fact | Evidence |
| --- | --- |
| A1. The left-out write's slot runs a fetch when the queue has room for a word counting the stored bytes and the IR but not the word delivered on the slot clock: 4 counted (room 2) fetch in 147 of 147; 5 counted after a fetch whose word lands on the slot clock fetch in 119 of 119 (3 stored before that word); 5 counted with no cycle since the read do not, 31 of 31. The model's `rmw_slot_any` (any byte of room) fetches in all 297; `rmw_slot` (the request rule) was refuted on these runs before (+5 −90, the 119) | `F19-i-push-l0-cmpimm8-pE-w0` slot 92 c5, silicon none (model F92); `F19-i-push-l0-cmpimm-pO-w0` slot 94 c5 on fetch 91's delivery, F94 in both |
| A2. A slot with no fetch is no bus cycle: the instruction ends and the next starts 2 clocks after the slot clock, at every wait (12 of 12 cells followed by the PUSH, read off its write; the k = 2 first instances and the OUT and marker-less frames below) | `F19-i-push-l0-cmpimm8-pE-w1` R90, slot 96, PUSH at 98, w104; `-w2` R93, slot 100, PUSH 102, w108 |
| A3. The slot fills the data latch as the write it stands for would: the closing port-form OUT starts no earlier than slot + `wlatch` 4, which only shows at 0 waits where the slot's fetch ends at slot+2 (34 of 34 at w0 one clock late, 62 of 62 at w1–2 exact) | `F19-i-out-l0-cmpimm-pE-w0` slot 97, F97, OUT model 100 I110, silicon I111; `-w1` slot 100 F100–103, OUT 104 I114 both |
| A4. With A2 and A3 together the no-fetch OUT-frame cells fall in place: the OUT waits for the latch to slot+4, its port take at slot+7 carries the fetch silicon shows at R+12/13/14 by wait and the I/O moves by that fetch's wait states | `F19-i-out-n1-cmpimm8-pE-w0` R94 slot 99: silicon F106 I113 (R+12, R+19); `-w1` R97 slot 103: F110 I118; `-w2` R100 slot 107: F114 I123 |
| A5. Marker-less, the no-fetch cells' next fetch is the closing `MOV CL`'s: `F19-i-none-n1-cmpimm8-pE-w1` R83 silicon F94 F98 (R+11, R+15), model F89 (the slot fetch) F98 | tab.py |

#### Group B: the TEST/CMP reg forms against their ADD/AND twins

##### Tabulation B1: the first data cycle's offset from the start (rdtab.py over F4 F5 F14 F15 F16 F19 F20 F21)

Head = the model's fetches at s-3..s (`+0`: one issued on the start clock), `A` = an aborted
fetch cycle at s (`abort_fetch=retry`: start, an operand take and an IR load on one clock with
room for exactly one word). Offsets with no I/O between (the OUT frame's s+11 and later rows are
exact in every form and left out):

| form (mod 00 [BW]) | head | model | silicon | cells |
| --- | --- | --- | --- | --- |
| ADD/AND/XOR/SUB r/m,reg; XCH; CMP r,r/m; CMP r/m,reg; MOV r,r/m | `A` | s+5 | = | 67+9 ALU, 27 base+index, 15 XCH, 6+9 CMP, 168 MOV |
| ADD r/m,reg | `+0` | s+5..s+8 by wait | = | 283 |
| **TEST r/m,reg (84/85)** | **`A`** | **s+8** | **s+7** | **15 of 15** (marker-less pO inst 1: F14 T 3, F15 A 3; PUSH pE k = 2 inst 2: F14 T `test_bw_aw`/`test_bw_al` 6, F5 `push-test_m_aw-k2` 3) |
| TEST r/m,reg | `+0` | s+8 / s+9 / s+10 at w0/1/2 | = | 32+14 |
| **TEST r/m,imm16 (F7 /0)** | none (no fetch at or after s in the head) | **s+8** | **s+9** | **12 of 12** (F15 A `none-test_bw_imm` pO 3; F14 T `push-test_bw_imm-k2` pO inst 2, 3 + 2 more with the fetch at s-3 ended; F16 R `push-test_imm-x_x` pO inst 2, 3; `-inc_x` pE inst 1, 3) |
| TEST r/m,imm16 | `+0` | s+10 / s+11 / s+12 | = | 26+4 |
| CMP r/m,imm16 (81 /7) | none | s+7 | = | 26+8+8 |
| CMP r/m,imm8 (83 /7) | none | s+6 | = | 26+5 |

No TEST r/m,reg cell starts with neither a fetch nor an aborted cycle in its head except
under the OUT frame (an I/O between). The aborted cycle is the one state that puts the
TEST 84/85 read early: every ALU form in that state reads at the floor s+5 in both; TEST,
the one form whose group setup is taken because no ALU-op field names its operation
(`grp_ops=fixed`), loses one clock less than the model gives it.

##### Tabulation B2: the first fetch after a read, CMP r/m,reg (38/39) against the other read-only forms (route2.py)

| form | counted on D (the read's data clock) | model | silicon | cells |
| --- | --- | --- | --- | --- |
| **CMP r/m,reg (38/39: `dest_route` 2 clocks after the read)** | **4** | D+0 | **D+2** | **18 of 18** (F14 T `push-cmp_bw_aw/al-k2-pE` inst 2, `out-cmp_bw_aw/al-pO`, `none-cmp_bw_aw-pO`; F15 A `out-cmp_dir_aw-pO`, every wait) |
| CMP r/m,reg | 3 | D+0 | D+0 | 3 of 3 (`F15-a-out-cmp_dir_aw-pE-w0/1/2`) |
| CMP r,r/m, TEST r/m,reg, MOV r,r/m, ADD/AND r,r/m (no route clocks) | 3 / 4 | D+0 | = | 24 / 331 |
| the same | 5 | D+2 | = | 57 |

The CMP r/m,reg twin in every one of the 18 cells is `CMP r,r/m` or `ADD r/m,reg` with the same
read clock: the 3B form fetches at D+0 with 4 counted (`F14-t-push-cmp_aw_bw-k2-pE-w0` R97 F100),
the 39 form at D+2 (`F14-t-push-cmp_bw_aw-k2-pE-w0` R99 F104, model F102).

##### Facts, group B

| Fact | Evidence |
| --- | --- |
| B1. TEST 84/85 started on an aborted fetch cycle reads one clock earlier than the model puts it, s+7 against s+8, at every wait (15 of 15); with a fetch on its start clock it is exact. The twelfth fit's `abort_unit=loop` gives the unit forms (shift, multiply, divide, PUSH r/m) one group setup clock counted during the aborted cycle; TEST's group setup (`grp_ops=fixed`: TEST takes it because no ALU-op field names its operation) is not given it. The ALU forms in the same state read at the floor s+5 in both (an RMW has no group setup) | `F14-t-none-test_bw_aw-pO-w0` aborted cycle 72–74, model post 77 R80, silicon R79; `F14-t-push-test_bw_aw-k2-pE-w0` second TEST at 94 on an aborted cycle, model R102, silicon R101, everything after one clock earlier (w113 against w114) |
| B2. TEST r/m,imm16 (F7 /0) with no fetch in its head reads at s+9, one clock later than the model's s+8 (12 of 12); with a fetch on its start clock both read at s+10 (w0). CMP r/m,imm16 in the same state reads at its count floor s+7 (istart 5 + 2) in both; TEST imm's s+9 is that floor plus `fgrp` 2, the fixed operation's lookup in series before the group decode (`grp_fixed=test`), which the floor does not carry today. This is the sixteenth to twenty-first fits' `rmw_imm.istart` knob dependence (F16 wants 7: 7 + 2 = s+9) | `F15-a-none-test_bw_imm-pO-w0` s 72, model R80, silicon R81; its pE twin with a fetch at 72 R82 both |
| B3. CMP r/m,reg's two route clocks after its read (`dest_route=d0ro_latch`, the datum entering the data latch after them) hold a fetch as a posted data request does under `hold_fetch=le_q`: with more than `hold_q` 3 bytes counted on the data clock the fetch waits to D+2 (18 of 18), with 3 it runs at D (3 of 3); no other read-only form waits there (355 of 355) | `F14-t-none-cmp_bw_aw-pO-w0` R77 silicon F82 (model F80); `F14-t-out-cmp_bw_aw-pO-w0` R90 silicon F95 (F93); `F15-a-out-cmp_dir_aw-pE-w0` 3 counted at 93, F93 both |
| B4. The k = 2 PUSH-frame cells of `cmp_bw_aw`/`cmp_bw_al` pE (6) are B3 at the second instance: after the fetch at D+2 the PUSH waits that fetch out and writes a clock later (w26 against w25 at w0, w29/w27 at w1 where the model's fetch sits inside the PUSH's setup) | tabB.py `t-push-cmp_bw_aw-k2-pE-w0`: silicon R0 R12 F17 w26, model R0 R12 F15 w25 |
| B5. Not read off yet: `F15-a-out-cmp_dir_aw-pE` (3, +6/+5/+4): silicon runs a second fetch at D+3 (F93 F96) where the model's queue has room 1; and `test_dir_aw` under OUT pO (F14 T, F15 A, 6): silicon's first fetch after the marker's I/O is 4 clocks after its end (F91, I/O 85–87) where the model fetches at 88; TEST [0C00h]'s displacement is taken at 86, on the I/O's second clock | sim --silicon |

#### Group C: not started.

#### Addendum, read off during the rule work (after the facts above were written)

| Fact | Evidence (clocks rel t_fill) |
| --- | --- |
| B5's first half is the slot: in `F15-a-out-cmp_dir_aw-pE` the AND twin writes at 96, on fetch 93's delivery clock (its ALU clocks counting through that fetch, `rmw_alu=through`); CMP [0C00h],AW runs a fetch on that clock with 5 counted, 3 stored before the delivered word (A1's second state), and the closing OUT waits for the latch to 96 + 4 = 100, I/O 110 at every wait (+6/+5/+4 before). CMP r/m,reg (38/39) is the RMW with its write left out, as CMP r/m,imm is: B3's hold is its posted write's `hold_fetch=le_q` hold during the write's setup (3 clocks from the read data, issuable at D+2), not a route of its own | `F15-a-out-cmp_dir_aw-pE-w0` F93 F96 I110; `F15-a-out-and_dir_aw-pE-w0` F93 W96 F103 I110 |
| Run that way (`dest_route=slot`, the tenth fit's refuted alternative, −14 then, before the slot rules) every one of B3's 21 cells and the three B5 cells are exact; the d0ro_latch reading with a fetch hold on its route clocks (prototype `route_hold`, removed) closed the 18 and not the 3. Holding every fetch through the route clocks whatever the count ties with the le_q hold on exact runs (+0 −0) and disagrees with the 3 cells' first fetch | sc-d-slot.txt, sc-alt-routeall.txt |
| CMP r/m,reg's slot without a fetch ends 2 clocks after it as rmw_imm's does: `rmw.sidle` 2, pinned (1 and 3 each lose 33: F14 27, F15 6) | `F14-t-push-cmp_bw_aw-pE-w0` R87, data 90, slot 92 idle, PUSH at 94, w100 |
| B5's second half, TEST [0C00h],AW under OUT pO (F14 T, F15 A, 6 runs, every wait): the marker's I/O at 85/86/87 by wait, the displacement taken on its issue clock (fetch 82's delivery, at s+5); silicon's first fetch after the I/O is 4 clocks after its last clock (F91, F92, F93), the read 3+w after that fetch (R94, R96, R98); the model's `disp_io=extend` gives the fetch 2 clocks after (F89/F90/F91). The F21 base+index+d16 forms in the same take state are 2 after (78 of 78). Not separated; left open | `F14-t-out-test_dir_aw-pO-w0` I85 F91 R94 F97 |
| TEST [0C00h]'s lookup costs a clock after a fetch issued on its start clock (`lookup_start`, fdisp 3): the twentieth fit's knob dependence "`load_alu.fdisp` 4 prefers 3 at even parity" was this, the pE second instance being the only TEST [dir] start with no fetch | `F14-t-push-test_dir_aw-k2-pE-w0` second TEST at 95, no fetch, F100 R103; `-pO-w0` beside fetch 95, F101 R104 |
| Group C probe, not adopted: `reg.nx` 1 (the long-standing knob dependence) closes 5 of the 13 F20 `ES: NOP ; MOV r,r` cells and loses 64 (F19 D OUT-frame `mov*-{outb,inb,outw,inw}` 48, F20 OUT `l0-mov*-outdw` 12, F7 4); the 8 `es-movawdw/movdwaw` pO cells' MOV starts with a lapsing take-sync request and loads the IR at take + 2 where silicon's next start says take + 1 | sc-c-nx1.txt; `F20-r-push-es-movawdw-ld-pO-w0` silicon F90 R95, model F91 R96 |

### The register form's IR load, the NOP's fetch after an I/O, the port take on a fetch's issue clock, the latched byte's clock, re-read from F20, F19, F7, F3 and F16 (twenty-third fit, 2026-10-22)

Written 2026-10-22 from the recorded runs and the twenty-second fit's model state
(fit.json = fit-wp31-hand.json, 15874/17822), before any change to the simulator.
Clocks rel t_fill unless written T+n (T = the clock the model takes the form's last operand
byte), s+n (s = the instruction's start in the model) or t+n (t = the clock named in the
table). Only decisions with every earlier event matching silicon are counted ("prefix
matched"); refresh-on runs are left out of every tabulation.

Tools (scratchpad wp32/): rt.py logs, per run, every model instruction start with its take
clocks, IR load clocks, the next start and the per-clock state at the last take (the
`sim --trace` clock log); an1–an5.py tabulate the 8B forms (8B C2 `MOV AW,DW`, 8B D0
`MOV DW,AW`) from it, an4/an5 against a run with `reg.nx` 1 (nx1.json) so that the next start
silicon wants is read off as the one whose run is exact; ri.py logs every fetch issue on
which `request_reissue` re-evaluates the flag and keeps it raised (the instruction started on
the clock, the queue, the I/O history, both runs' next fetch); pt.py logs every port-byte take
made while an I/O waits in the bus unit's slot (`port_latch=relatch`), the waiting I/O's count,
the bus on the take clock and both runs' next I/O. tr.sh prints a run's chain and `sim --trace`.

#### Group A: the leads before a register form

##### Tabulation A1: the 8B forms' take state, every family (rt.py, an5.py; 1,638 8B starts in F20 alone)

Every 8B start is in one of these states at its ModR/M take T. Only two are sensitive to the
loader's `reg.nx` (the IR loads at T + nx, the next instruction starts at T + nx + 1 at the
earliest); in every other the take sync waits for a fetch at least as long and hides it.

| state at T (prefix matched) | cells | next start T+3 (nx 2) exact | next start T+2 (nx 1) exact | silicon |
| --- | --- | --- | --- | --- |
| a fetch issued on T (`issue@T`), or one in flight | ~1,500 | all | all (hidden: the sync ends at the fetch's delivery) | either |
| **the marker's I/O cycle issues on T** (MOV started on the I/O issue clock under the OUT frame, `sync_io=unit` not counting the request raised under it); 4–5 stored, room 2–3 | 64 sensitive (+ 133 hidden) | **64 of 64** | 0 of 64 | **T+3, at every wait** (w0 24, w1 20, w2 20: F19 D 48, F20 R OUT `l0-mov*-outdw` 12, F7 4) |
| **nothing on the bus, nothing in flight, no request** (after `ES: NOP`: the NOP ran with 6 stored + 1 latched + the IR full, room −1; MOV starts at T with 6 stored, 1 latched, room 1; the sync counts nothing and lapses) | 13 sensitive (+ 6 hidden) | **0 of 13** | 5 of 13 (8 need a second change, A3) | **T+2** |

The 13: `F20-r-push-es-movawdw-{ld,st,outdw,movr}-pO-w0`, `-es-movdwaw-{ld,st,outdw,movr}-pO-w0`,
`-push-es-none-movr-pO-w0`, `-push-l0-pfxnop-movr-pO-w0`, `-push-n1-pfxnop-movr-pE-w0`,
`-none-l0-pfxnop-movr-pE-w0`, `-none-n1-pfxnop-movr-pO-w0`. The six hidden ones in the same state
are followed by an I/O form held by the data latch (`-push-es-mov*-outimm-pO-w0`,
`-out-{n1,n2,es}-pfxnop-movr`, `F20-n-out-d2-nop-movr-pO-w0`). No 8B start in the corpus takes
its ModR/M with the bus idle and a request raised, or on an aborted cycle, with the IR load
visible.

The pE twins of the 8 `es-mov` cells take on a fetch's issue clock (fetch 88, the sync to 91):
exact either way. `ES: NOP ; NOP ; load` (`F20-r-push-es-nop-ld-pO-w0`, exact) puts the second
NOP at 88 in the same full state, so the NOP after `ES:` is 4 clocks in silicon as in the model:
it is the MOV that is 2 clocks start to start there, not the lead that is short.

##### Tabulation A2: under nx 1 the 8 `es-mov*` cells (the next form starts at T+2 = 90)

| cell | model with nx 1 | silicon |
| --- | --- | --- |
| `-es-movawdw-ld-pO-w0` | load starts 90 with a raised request, room 3, but the byte delivered at 87 into a full queue is still latched: the decoder read on 88 (ModR/M take), 89 (IR load), 90 (start, take, IR load), so `latch_hold` holds the fetch: F91 R96 | F90 R95 |
| `-es-movawdw-movr-pO-w0` | the same: F92 | F90 F93 |
| `-es-movawdw-outdw-pO-w0` | OUT DW at 90, I/O 96 F100 | F94 I97 |

##### Tabulation A3: fetches `request_reissue` keeps raised, the instruction started on the issue clock, an IR load and no operand take there (ri.py, every family)

| started on the fetch's issue clock t | the I/O cycle ended on t−1 | the back-to-back clock against the next start | cells | model b2b fetch | silicon |
| --- | --- | --- | --- | --- | --- |
| NOP (register class, no operand byte) | no | b2b at or after the next start | 66 | yes | yes |
| NOP | no | b2b before the next start (the room lapses first) | 37 | no | no |
| **NOP** | **yes** | **b2b before the next start (w0: t+3 is the NOP's last clock)** | **6** | **yes** | **no: the fetch at t+4, the next start** |
| NOP | yes | b2b at or after the next start (w1, w2) | 12 | yes | yes |
| OUT DW / IN DW (1 byte, its I/O posted in the slot) | yes | — | 18 / 12 | yes | yes |
| segment prefix | no | b2b at or after the next start | 18 | yes | yes |

The 6: `F19-d-out-movawdw_nop-{outb,outw,inb,inw}-pE-w0`, `F14-o-out-movr_nop-pE-w0`,
`F15-o-out-movr_nop-pE-w0`: the OUT marker's I/O 84–86, `MOV AW,DW` takes its ModR/M on 84 (A1's
I/O state, next start 87), the NOP starts at 87 on fetch 87's issue clock and the IR loads the
DW form; silicon F87 F91 I100 (the DW form starting at 91 with the fetch on its start clock,
its I/O at s+9 as one counted clock is lost), model F87 F90 I101. At w1/w2 (12) the
back-to-back clock is at or after the next start and both agree. No NOP start anywhere in the
corpus has silicon run a back-to-back fetch before the next start.

##### Facts, group A

| Fact | Evidence |
| --- | --- |
| A1. The 8B form's next start is visible in exactly two states, and they disagree on `reg.nx`: on the clock the marker's I/O cycle issues the next start is T+3 at every wait (64 of 64), on an idle bus with nothing requested T+2 (13 of 13). Every other state hides the IR load behind the take sync | `F19-d-out-movawdw-outb-pE-w0` T 84 (I/O 84–86), OUT DW at 87, F87 F90 I97 (nx 1: OUT DW at 86, F90 I93); `F20-r-push-es-none-movr-pO-w0` T 88, silicon PUSH at 90 (w96), model 91 (w97) |
| A2. The idle-state 13 are all `ES: NOP` before the 8B form (lead `es`, or P = `pfxnop`): the only way the corpus reaches an 8B take with 6 stored, one latched, the IR just emptied and no bus cycle. The `ES:` NOP itself is 4 clocks in silicon | `F20-r-push-es-nop-ld-pO-w0` exact with the second NOP at 88 |
| A3. With the IR loading at T+1 the next form starts at T+2 in all 13, but in the 8 whose next form wants a fetch on its start clock the byte latched at T−1 (delivered into a full queue) has had no clock without a decoder read (T take, T+1 IR load, T+2 start), so `latch_hold` holds the fetch silicon runs at T+2 | `F20-r-push-es-movawdw-ld-pO-w0` silicon F90 R95; nx 1 model F91 R96 |
| A4. A NOP started on the first fetch's issue clock after an I/O cycle, where the IR load and the reissue keep the request raised, does not get the back-to-back fetch on its last clock (w0): the fetch waits for the next instruction's start (6 of 6); at 1–2 waits the back-to-back clock is the next start or later (12 of 12 agree). `io_ir_hold` holds a request the IR load raises on the I/O issue clock itself until the next start; this is the same shape a clock after the cycle | `F19-d-out-movawdw_nop-outb-pE-w0` F87 F91 I100 (model F87 F90 I101); `-pE-w1` F88 F92 exact |

#### Group B: OUT directly after OUT at odd parity, 0 waits

##### Tabulation B1: every port-byte take while an I/O waits in the slot (pt.py, every family; 978 runs)

The waiting I/O issues at max(its count of `out.setup` 8 non-wait clocks, the take + `relatch` 3,
+1 under `port_landed`). Columns: the waits, the bus on the take clock t, the setup clocks the
waiting I/O still had to count at t, the model's issue (t+n), silicon's.

| waits | bus on the take clock | left to count | model | silicon | cells |
| --- | --- | --- | --- | --- | --- |
| 0 | **a fetch issues on t** | 3 | t+3 | **t+4** | **8 of 8** |
| 1 | a fetch issues on t | 3 | t+4 (its wait state not counted) | = | 12 |
| 2 | a fetch issues on t | 3 | t+5 | = | 12 |
| 0–2 | a word's delivery, second byte latched (`port_landed`) | 3 | t+4 | = | 18 |
| 0–2 | idle | 2 | t+3 (relatch) | = | 621 |
| 0–2 | a fetch in flight (issued before t) | 2 | t+3 / t+4 | = | 237 |

The 8: `F1-out-m4-pO-w0`, `F5-out-out_imm_al-k1/k2-pO-w0`, `F5-out-out_imm_aw-k1/k2-pO-w0`,
`F6-out-out_imm_al-n0-pO-w0`, `F7-out-out_imm_al-out_imm_al-pO-w0`,
`F20-r-out-l0-none-outimm-pO-w0`: in every one the second OUT (port form) starts at 91 on the
OUT frame at pO, its port byte taken at 94 on fetch 94's issue clock, the first OUT's I/O
waiting with 3 to count; silicon I98, model I97, the fetch at 94 in both. At pE the same pair
takes its port byte at 95 on an idle bus with 2 left: I98 in both.

##### Facts, group B

| Fact | Evidence |
| --- | --- |
| B1. A port byte taken on a fetch's issue clock holds the I/O waiting in the slot to take + 4, a clock past `relatch` 3, at every wait: at 0 waits it is the binding clock (8 of 8, the model's count ends at t+3), at 1–2 waits the count through the fetch's wait states ends at t+4/t+5 and both agree (24 of 24). The take on a delivery clock with the byte latched already lands a clock late (`port_landed`); on an idle bus or with a fetch issued earlier the port take is on time (858 of 858) | `F7-out-out_imm_al-out_imm_al-pO-w0` port take 94 = fetch 94's issue, I98 (model I97); `F20-r-out-l0-none-outimm-pE-w0` port take 95 idle, I98 both |
| B2. (Read off the counts, not run.) Counting the I/O's setup without the clock a fetch issues (as `dw_count=bus` does for the DW forms) instead gives t+4 at 0 waits but t+5 at 1 wait, against silicon's t+4 (12 cells): the delay is on the port latch, not the count | pt.py w1 rows |

#### Group C: not tabulated before the rule work (see the addendum).

#### Addendum, read off during the rule work (after the facts above were written)

Correction made to the table above after the fact: the nx 1 clocks of
`F19-d-out-movawdw-outb-pE-w0` were first written from reasoning as I96; the run gives OUT DW at
86, F90 I93.

| Fact | Evidence (clocks rel t_fill) |
| --- | --- |
| A1 resolved: `reg.nx` 1, the register form's IR load a clock later when its last operand byte is taken on an I/O cycle's issue clock (`io_take_nx`): 5 of the 13 at once, every one of the 64 kept. The same clock for every class (the shifts and the multiply taking their ModR/M on the I/O issue clock) loses 75 (F3 `out-shl1`/`out-mulu_dw` pO, F12 A `n0-shl1`, F14 G `out-mulu_aw`, F14/F15 O `out-shl1`) | `F20-r-push-es-none-movr-pO-w0` w96 (nx 2: w97); `F19-d-out-movawdw-outb-pE-w0` I97 |
| A3 resolved: the byte latched at T−1 behind a full queue goes in on the 8B form's ModR/M take clock (a ModR/M commit into the decoder's ModR/M latch, `modrm_commit=byte`, does not hold the write port for a byte latched on an earlier clock; `modrm_port`). Alone it changes no run; with nx 1 it closes the other 8. Letting any older latched byte in on the first clock with room (the port ignored) loses 135 (F9 marker-less `nop2`, `nop3`, `es_nop1`, `imm_nop2` ... at 1–2 waits, F11 `n2-movr`, F16 S `n2-shlcl*`: `MOV CL,31`'s immediate take frees the room with the port busy and silicon still holds the fetch to the next clock, `F9-none-nop2-pE-w1` F85); a ModR/M commit freeing the port on the delivery clock too loses 364 | `F20-r-push-es-movawdw-ld-pO-w0` F90 R95 |
| A4: `nop_hold` scoped to the clock after an I/O cycle (`io`) and on every fetch issue clock (`any`) tie (+6 −0 each): no NOP start outside the 18 after an I/O has the back-to-back clock before the next start with the room still raised (A3 tabulation) | sc-f-nophold-io.txt |
| B1 confirmed: +8 −0 | `F7-out-out_imm_al-out_imm_al-pO-w0` I98 |
| C1. `MOV r,imm8` (B1) started on a delivery clock with 6 stored and the delivered word's second byte latched (7 stored counting it), its immediate taken at s+3 with the IR load: the next instruction starts at T+1 in both, and the byte goes into the queue on that start clock unless the next form takes a byte there. A `SHL AW,CL` there (its ModR/M taken on its start clock: the byte waits) is exact in 82 of 82; a `MOV CL,imm8` (no take before its pre 3 clocks) takes its immediate a clock late in silicon in 10 of 10 (F3 `mov_cl_imm-k4` push pO and out pE, every wait; F16 S `n2-movcl` pE, `n3-movcl` pO, 1–2 waits). An instruction starting on the clock such a byte goes in runs its first EU clocks from the clock after (`latch_start`); in the corpus it changes only those 10 | `F3-push-mov_cl_imm-k4-pO-w0` F101 (model F100); `F16-s-none-n2-movcl-pE-w1` F88 (F87); `F9-none-nop2-pE-w1` F85 exact either way |
| C2. `SHL AW,CL` started after a NOP that ran with 6 stored and one latched (the 5 `F16-s-none-cl*-n1-shlcl-pO-w0`, the only SHL AW,CL starts in that state): its start, ModR/M take and IR load on one clock leave room for one word but for the latched byte. Silicon's shift runs 2 clocks later (the closing `MOV CL`'s fetch at 105 against 103), as after an aborted cycle whose 3 clocks the take sync waits out. The abort's room test not counting a byte still latched after its delivery clock, with the take sync waiting for that cycle (`abort_latched`), closes all 5; counting only a byte latched behind a full queue (`full`) ties. The doc's earlier attempt (an aborted cycle at one byte of room with a latched byte) changed nothing because the take's sync, computed before the arbiter, counted no request | `F16-s-none-cl4-n1-shlcl-pO-w0` F105 F108 (model F103 F106); pE twin F100 exact either way |
| C3, not closed: `NOP NOP ; MULU AW` at pO (`F16-l-push-nop2_mulu_aw-pO-w1/w2`, `F16-l-out-nop2_mulu_aw-pO-w0`, silicon a clock earlier from the MULU's end on): the MULU starts on an aborted cycle (at w1/w2 also a word's delivery clock with its second byte latched, under OUT w0 not), and silicon ends it a clock before `abort_reg`'s kept end, where `F3-push-mulu_dw-k2-pE-w0` (an aborted start, no NOP lead) keeps it. No state found that separates the three from the F3 cells; no rule tried | `F16-l-push-nop2_mulu_aw-pO-w1` w129 (model w130); `F16-l-out-nop2_mulu_aw-pO-w0` F136 I139 (F137 I140) |

### The last four refresh-off groups: the direct TEST under OUT, the aborted-start multiply's end, the second base+index+d16 store, the immediate RMW's idle clock (twenty-fourth fit, 2026-10-22)

Written 2026-10-22 from the recorded runs and the twenty-third fit's model state
(fit.json = fit-wp32-hand.json, 15916/17822; 15 refresh-off misses outside F8), before any
change to the simulator's behaviour. Clocks rel t_fill unless written s+n (s = the instruction's
start in the model), t+n (t = the clock tabulated) or I/O end+n. Only decisions with every
earlier event matching silicon are counted ("prefix matched"); refresh-on runs are left out of
every tabulation.

Tools (scratchpad wp33/): take.py (wp30's, re-run on fit.json: every displacement take with the
state before the bus choice); grpio.py (every clock on which a posted memory request with group
setup clocks, `grp_free_bus`, waits while an I/O cycle or its recovery is on: its count, the
fetch's age against the I/O's issue, both runs' next fetch); abrt.py (every register
multiply/divide/shift start whose start clock carries an aborted cycle, with the queue state);
mulend.py (per register MULU start: the abort_reg early end, the next start, the next events in
both runs); bix.py / bixtab.py (every base+index+d16 start: the queue and bus per clock s..s+4,
both runs' fetch clocks); b2b.py (every clock a back-to-back fetch is due while a displaced
ModR/M form has not taken its displacement); idle.py (every fetch issued on the clock after a
fetch's last while a memory request is posted and that fetch was a run's, with the request's
per-clock count history); probe.py (per-clock EU step); cmpruns.py (two configs, per run).

#### Group A: `TEST [0C00h],AW` under OUT at pO (F14 T, F15 A, w0/w1/w2; −2)

Silicon `F14-t-out-test_dir_aw-pO-w0`: F82, I85, F91, R94, F97, F109 I112. Model: F82 I85 F89 F92
R95 F110 I113. At w1 I86 F92 R96 (model F90 F94 R98), at w2 I87 F93 R98 (F91 F96 R101): the first
fetch 4 clocks after the I/O's last clock at every wait (the I/O is 3 clocks in every cell), the
read on the clock after that fetch ends, one fetch before the read where the model runs two; from
the read on silicon is a clock earlier than the model.

##### Tabulation A1: displacement takes on an I/O cycle's issue clock (take.py, prefix matched)

| class (cells) | parity | state on the take clock (counted/stored/latched; delivery; IR) | the form's data request | model F, D (t+n) | silicon F, D |
| --- | --- | --- | --- | --- | --- |
| ld/st/add/sti base+index+d16, F21 + F4 (39) | pE | 2/2/0, no delivery, IR held, fetch requested at t−4 | ld/st/add: posted at the take, `dfloor` 2; sti: posted after `dadd`, setup 3 (1 free, grp) | t+4, D = silicon | t+4 (I/O end+2), = |
| ld/st/add base+index+d16 (30) | pO | 2/1/1, **a delivery (fetch 82's), IR loads on the take**, s+5/6/7 | as above | t+4 | t+4 |
| sti base+index+d16 (6) | pO | 2/2/1, delivery, IR not loaded | setup 3, 1 free, grp | t+4 | t+4 |
| **TEST [0C00h],AW (load_alu), F14 T + F15 A (6)** | **pO** | **2/1/1, delivery, IR loads on the take, s+5/6/7: the same as the ld pO row** | **read posted at t+1, setup 1, all of it a bus-free group clock (load_alu grp 4 − fdisp 3)** | **t+4, D t+10/12/14** | **t+6, D t+9/10/11** |

The take state does not separate TEST from the 30 loads, stores and ADDs at pO: same counted state,
same delivery, same IR load, same start clock (s = 80), same fetch requested on the take clock. The
direct address (`ea_direct=base_disp`, 2 EA clocks) and TEST's fixed lookup (`fdisp` 3 nowait
clocks 81–83, then the EA clocks 83–84) only bring the take to the same clock 85 the base+index+d16
forms reach with 3 EA clocks. Half of the 78 (the pO 39) also take on a delivery clock, so the
take being on a delivery clock as well as an I/O issue clock is not the difference. What differs
is the request: TEST's read carries one group setup clock that counts only on an idle bus outside
I/O recovery (`grp_free_bus`); the loads have none.

The pE twin (exact) takes at 85 on the I/O's second clock, its take sync waits for fetch 87, the
read is posted only at 90: no group clock waits in the recovery there.

##### Tabulation A2: a group setup request waiting while an I/O cycle or its recovery is on (grpio.py, the first free-bus clock with a fetch wanted, prefix matched)

| request's next setup clock | fetch first requested | queue | model | silicon | cells |
| --- | --- | --- | --- | --- | --- |
| a non-free one (count < setup − free) | before the I/O's issue | ≤ 3 | fetch here | fetch here | 156 (+6 ext) |
| a non-free one | at or after the I/O's issue | ≤ 3 | fetch here | fetch here | 30 (+6 ext) |
| a non-free one | either | > 3 | as le_q | = | 84 + 107 |
| **a free one (count = setup − free)** | before the I/O's issue | ≤ 3 | fetch here | fetch here | 3 (`F14-g-out-shl_bw_cl-pE`, setup 7 all free) |
| **a free one** | **at or after the I/O's issue (the delivery on the issue clock)** | ≤ 3 | **fetch here** | **2 clocks later (F+2), with the request** | **6 (the TEST cells)** |
| a free one | at or after the I/O's issue | > 3 | held (le_q) | = | 3 (`F14-g-out-shl_bw_cl-pO`) |

##### Facts, group A

| Fact | Evidence |
| --- | --- |
| A1. The six are the only cells in the corpus in which a request whose next setup clock is a bus-free group clock waits out an I/O cycle's recovery while a fetch requested on or after that I/O's issue clock is wanted with ≤ 3 bytes queued. In every one silicon runs neither the fetch nor the read until the clock the group clock could count (I/O end + 1 + `io_recover` 2 + the take's held clock = I/O end + 4), then the fetch, then the read: as if the waiting group clock holds the fetch and the held fetch dates from the clock the hold lifts, where it goes first against the request just become issuable (the arbiter's same-clock rule) | `F14-t-out-test_dir_aw-pO-w0` I85–87, held 88, recovery 89–90, F91 R94 |
| A2. A fetch requested before the I/O issued is not held by such a request: `F14-g-out-shl_bw_cl-pE` (SHL [BW],CL, setup 7 all free, fetch requested at I−4) fetches on the I/O's first free clock in silicon (3 of 3). Every request at a non-free setup clock lets the fetch run whatever its age (36 cells at ≤ 3 queued) | grpio.py table above |
| A3. No other take state distinguishes TEST from the base+index+d16 loads: queue, delivery, IR, start clock, fetch age are equal; only the request (a group clock) differs | take.py rows |

#### Group B: `NOP NOP ; MULU AW` after the marker at pO (+1)

##### Tabulation B1: every register multiply started on an aborted cycle (abrt.py, mulend.py; no register divide starts on one in the corpus; F12 has none)

The start state is the same in every instance: 4 stored, 4 counted, the start, the ModR/M take and
the IR load on one clock, room for one word: `abort_fetch` aborts the request; under `abort_reg` the
exec runs from the aborted cycle's last clock, the dropped request is raised `mtail` 2 clocks before
that early end E, and the end is then kept a clock later (E + 1). Columns: what is on the bus at E.

| runs | lead / waits | E rel s | retry fetch | next start (keep) | silicon | keep vs early |
| --- | --- | --- | --- | --- | --- | --- |
| `F3-push-mulu_dw-k2-pE-w0/1/2`, `F14-g-push-mulu_aw-k2-pE-w0/1/2` (2nd MULU) | the previous MULU | s+33 | E−2, in flight on E (3/4/5 clocks) | after the fetch (start_sync) | = | same events (the fetch hides E+1) |
| `F3-push-mulu_dw-k4-pE-w0/1/2` (2nd and 4th) | MULU | s+33 | in flight on E | after the fetch | = | same |
| `F3-out-mulu_dw-k4-pO-w0/1/2` (3rd) | MULU | s+33 | in flight on E | after the fetch | = | same |
| `F15-o-push-nop_mulu_aw-pO-w0`, `F16-l-push-nop_mulu_aw-pO-w0`, `F16-l-push-nop2_mulu_aw-pE-w0` | NOP / NOP NOP | s+33 | E−2, in flight on E | after the fetch | = | same |
| **`F16-l-out-nop2_mulu_aw-pO-w0`** | NOP NOP (OUT frame) | s+33 = 126 | 124–126, ends on E | **127**, closing OUT's fetch 137 | **136** | silicon = early |
| **`F16-l-push-nop2_mulu_aw-pO-w1/w2`** | NOP NOP, the MULU start also a delivery with the second byte latched | s+33 | **none** (no room) | **E+1**, PUSH w130/w133 | **w129/w132** | silicon = early |

(`F3-out-mulu_dw-k4-pO`'s first MULU starts on the I/O issue clock with an abort; its exec waits
for the I/O, `abort_reg` does not fire.)

##### Facts, group B

| Fact | Evidence |
| --- | --- |
| B1. In 15 of the 18 aborted-start register MULUs the kept end E+1 is not observable: the retry fetch raised at E−2 is in flight on E and the next instruction waits for it (start_sync), at every wait. `F3-push-mulu_dw-k2-pE-w0`, the run the kept end was adopted on, is one of them: F147 w156 with the end at E or E+1 | mulend.py; cmpruns.py fit.json vs early: 15 runs identical |
| B2. In the other 3 the end is observable (no retry fetch at w1/w2: the queue has no room; under OUT w0 the retry fetch ends on E) and silicon's next start is E, not E+1, at every wait. So no state separates the three from the F3 cells: the F3 cells never showed the kept end | `F16-l-push-nop2_mulu_aw-pO-w1` w129 (keep w130); `F16-l-out-nop2_mulu_aw-pO-w0` F136 I139 (keep F137 I140) |

#### Group C: the second base+index+d16 store / immediate store at k = 2 (−1)

##### Tabulation C1: every base+index+d16 start (bix.py, prefix matched; per clock s..s+4: counted/stored(+latched) room, D = delivery, b = a back-to-back fetch due, > the model's choice)

| instance | s+0 | s+1 | s+2 | s+3 | s+4 | model F | silicon F | cells |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| first, PUSH pE w0 | 3/3 r3 >fe | 5/3 r1 | 5/3 r1 | 5/4+L r1 D (ea_ir_room) > . | 3/3 r3 > fe | 0, 4 | 0, 4 | 18 |
| first, PUSH pO w0 | 4/4 r2 >fe | 6/4 r0 | 6/4 r0 | 6/5+L r0 D > . | 4/4 > fe | 0, 4 | 0, 4 | 63 |
| first, OUT pO (fetch held to the I/O lead) | 3/3 | 3/3 | 3/3 > fe | 5/3 r1 | 5/3 r1 | 2 | 2 | 39 |
| first and second, every other state (w1, w2, n1, n2, es, OUT pE) | | | | no fetch due at s+3 | | = | = | the other 441 of 564 |
| **second, k = 2, w0 (3 cells)** | **2/2 r4 > fe** | 4/2 r2 | 4/2 r2 (**b2b committed: the request raised on the fetch's last clock**) | **4/3+L r2 D b > fe** | 4/2 r2 | **0, 3** | **0, 4** | **3** |
| second, k = 2, w1 (same start) | 2/2 r4 > fe | 4/2 r2 | 4/2 r2 | 4/2 r2 (W) | 1/0+L r5 D b > fe | 0, 4 | 0, 4 | 3 |

The three misses are the only base+index+d16 instances that start beside a fetch issued on s with
2 bytes stored: every first instance starts with 3 or more stored. That is what precedes them: the
first instance's write (and, for the immediate store, its immediate take) leaves 2 stored, and the
second starts on the next fetch's issue clock. The data latch (`wlatch`) is not involved (stores,
no I/O form between), the pending request is the b2b one committed on s+2.

##### Tabulation C2: back-to-back fetches due before a displaced form's displacement take (b2b.py, every family)

| form, clock | room | model | silicon | cells |
| --- | --- | --- | --- | --- |
| base+index+d16 st / sti, s+3 (its third EA clock), a delivery | 2 (4 counted) | b2b fetch at s+3 | **fetch at s+4, the take clock** | **3 of 3** (the three misses) |

No other back-to-back fetch in the corpus falls inside a displaced form's EA clocks.

##### Facts, group C

| Fact | Evidence |
| --- | --- |
| C1. Silicon issues no fetch on base+index+d16's third EA clock (s+3) in any cell: 21 cells want one in the model's rules, 18 through the IR's seventh slot (`ea_ir_room` already holds them) and 3 back to back; all 21 fetch on the take clock s+4 in silicon. Fetches inside the EA clocks do run at s+2 (the OUT pO frame, a fetch requested before the I/O lead) | bixtab.py |
| C2. The first and second instances differ only in what precedes them: the second starts with 2 stored beside a fetch issued on its start clock, so that fetch's last clock (s+2) sees room for a word and commits a back-to-back fetch into s+3 | `F21-out-l0-st-bw_ix_d16-k2-pE-w0` F94 F98 F101 W104 (model F94 F97 F100 W103) |
| C3. With that fetch on the take clock the immediate store's write is posted after `dadd` and the next fetch is back to back on the write's free clocks' eve (count 2 of 3); silicon writes 4 after that fetch, the `free_idle` idle clock, which today follows only a run's delivery-clock fetch | read off a prototype, see the addendum |

#### Group D: `ADD [BW+200h],imm16` under PUSH pE k1/k2 and OUT pO k2, 0 waits (−1)

##### Tabulation D1: a fetch issued on the clock after a fetch's last, a run's, while an immediate memory form's request is posted (idle.py, prefix matched; the count after each clock, "fe n" the fetch's clock n)

| request | waits | posted (rel the delivery clock t) | counts before t | at t | silicon idle after the fetch | cells |
| --- | --- | --- | --- | --- | --- | --- |
| store_imm write | 0 | t−1 (B3) | B3:1 | 2 = the eve (free_idle) | yes (the rule; 8 of them a fetch also committed back to back) | 29 |
| **rmw_imm read (ADD imm16)** | **0** | **t−2 (B2)** | **B2:1 B3:2** | **3, ready; the run's fetch goes first (b2b arbiter)** | **yes** | **3 (the misses)** |
| rmw_imm read | 1 | t−3 (B2) | B2:1 W:2 B3:2 | 3, ready | no | 4 |
| rmw_imm read | 2 | t−4 (B2) | B2:1 W:2 W:2 B3:2 | 3, ready | no | 4 |
| **store_imm write** | **1** | **t−2 (W)** | **W:1 B3:2** | **3, ready** | **no** | 30 |
| store_imm write | 2 | t−3 (W1) | W1:1 W2:2 B3:2 | 3, ready | no | 40 |

##### Facts, group D

| Fact | Evidence |
| --- | --- |
| D1. The 0-wait ADD cells and the 1-wait immediate stores reach the same counted state: posted 2 clocks before the delivery clock, counted on the post clock and on the fetch's last clock, issuable on the delivery clock where the run's fetch goes first. The wait state does not change what the eve is in the model's terms (both reach count 2 of 3 on the fetch's last clock). Silicon idles after that fetch in the ADD cells and not in the stores | `F5-push-add_m_imm_d16-k1-pE-w0` F87 R91 (model R90); `F5-push-st_imm_bw_d16-k1-pE-w1` F90 W94 exact |
| D2. What differs between the two: the request's kind (an RMW's read against a store's write) and whether the post clock was a wait state (B2 against W). The ADD's own 1–2-wait twins are in a different count state (the eve reached on a wait state, a clock before the fetch's last) and do not idle. No other cell has a read in the 0-wait state, so the corpus cannot separate "a read" from "posted on a non-wait clock" | idle.py |

#### Addendum, read off during the rule work (after the facts above were written)

All on the whole corpus (17,822 runs) against sc23v.txt; "+n −m" = runs gained / lost. The four
adopted enums are in sim/config.py with the old option as DEFAULT and tests in
`test_sim.AbortEndEaB2bAndGroupHold`; every other prototype below is removed from the code.

| Fact | Evidence (clocks rel t_fill) |
| --- | --- |
| B resolved: the register multiply/divide started on an aborted cycle ends with its early exec, no clock kept (`abort_reg_end=early`): +5 −0 (the three F16 L runs and two refresh-on F18 BD MULU runs, `F18-bd-p-n6-mulu-pE-w1`, `F18-bd-p-n7-mulu-pO-w1`); the 15 hidden cells are identical event for event under both options (cmpruns.py) | `F16-l-push-nop2_mulu_aw-pO-w1` w129; `F16-l-out-nop2_mulu_aw-pO-w0` F136 I139 |
| A resolved: a group setup request whose next setup clock is a bus-free group clock, waiting out an I/O cycle or its recovery, holds a fetch first requested on or after that I/O's issue clock; the held fetch dates from the clock the hold ends and goes first against the request just become issuable (`grp_io_hold`): +6 −0. Holding a fetch of any age (also one requested before the I/O issued) +6 −3 (`F14-g-out-shl_bw_cl-pE-w0/1/2`, +2: silicon fetches at 87, on the I/O's first free clock) | `F14-t-out-test_dir_aw-pO-w0` F91 R94 F97 (False: F89 F92 R95); w2 F93 R98 |
| C, first half: no back-to-back fetch on an EA clock of a displaced ModR/M form before its displacement's take; the clock stays idle and the still-raised request issues on the take clock (`ea_b2b`): +1 −0 alone (`F21-out-l0-st-bw_ix_d16-k2-pE-w0`). No fetch at all on any EA clock after the start (the request held whatever its origin) +1 −233 (F4 OUT pO base+d8/d16/direct loads at s+2 and more: the fetch requested before the marker's I/O lead) | `F21-out-l0-st-bw_ix_d16-k2-pE-w0` F94 F98 F101 W104 |
| C, second half: with ea_b2b the two immediate stores take the d16 at s+4 with a fetch, post the write after `dadd`, and the next fetch is committed back to back onto the write's free clocks' eve (count 2 of 3); it is not a run's delivery-clock fetch, so `free_idle` gave no idle clock, and silicon has one (the write 4 after that fetch). `free_idle_b2b` (the idle clock also after a fetch the bus unit committed to back to back at the eve, `free_hold`'s other exception): +2 −0 with ea_b2b, +0 −0 alone (no such fetch exists in the corpus without ea_b2b). The 8 store_imm w0 cells whose eve fetch is both back to back and a run's delivery fetch already took the idle clock under free_idle | `F21-out-l0-sti-bw_ix_d16-k2-pE-w0` F102 F105 W109 (free_idle_b2b False: W108); `F21-push-l0-sti-bw_ix_d16-k2-pO-w0` F99 W103 (W102) |
| D, not resolved. The idle clock after the run's fetch when the request is already issuable: for every class +3 −76 (all at 1–2 waits, the immediate stores and ADD's own w1/w2 twins); only when the request reached its eve on the fetch's last clock or later (`eve` prototype) +3 −35 (the 1-wait immediate stores, D1's identical state); only for a read in that state +3 −0, but no read other than these three is in that state and no write in it idles, so "a read" cannot be told from "posted on a non-wait clock" on this corpus; only for a 3-clock fetch +3 −0, a rule on the knob. Neither adopted (no separating model state; the rule would be fitted to the three runs of one cell) | sc-d-ready.txt, sc-d-eve.txt, sc-d-read.txt, sc-d-ready0.txt |
| Combined (fit-wp33-hand.json): +14 −0 (F14 +3, F15 +3, F16 +3, F21 +3, F18 +2); refresh-off misses outside F8: the three D runs only. Flip-back losses on the final configuration: abort_reg_end −5, grp_io_hold −6, ea_b2b −3, free_idle_b2b −2 | sc24-all.txt, sc-flip-*.txt |

### The refresh side: HALT's service clocks, the beaten take sync, the RFMON store's head, the refresh-on prelude, F13's first divergences (twenty-fifth fit, 2026-10-22)

Written 2026-10-22 from the recorded runs and the twenty-fourth fit's model state (fit.json =
fit-wp33-hand.json, 15930/17822; refresh-on F8 1/48, F13 67/462, F17 314/798, F18 201/1164; the
refresh-off corpus exact but for 3 F5 runs). Clocks rel t_fill unless written H+n (H = the
model's HALT start, its first clock, in the END block `MOV DW,0FF00h ; OUT DW,AW ; HALT`),
q (a refresh request: the clock the free-running counter's selected bit rises, from the
model's counter, which is a constant of the prelude) or E (the last clock of a refresh cycle).
With refresh on, a request is only counted when every event of both runs (silicon and model)
that starts before it is identical ("prefix matched"); per run only the first such request in
the END window is kept (the model's later events are not prefix matched).

Tools (scratchpad wp34/): runs.py (per run: silicon and model events rel t_fill, first
divergence, the model's HALT clock, its refreshes (request, start), the counter's request
grid; NOHALTREF=1 suppresses every request raised at or after the model's HALT start, which
gives X0, the clock the END's I/O issues with no refresh in HALT); htab.py (every prefix-matched
request at H−1 or later up to silicon's END I/O: q−H, silicon's start − H, the model's, both
I/Os, the cycle on the bus at q, the gap from the last fetch's end, the previous refresh);
eu.py (the model's instruction starts and takes before H); beat.py (every refresh that beats a
fetch request the EU's take sync counts); cmp.py (two dumps: exact gained/lost, matched-prefix
sum); mk.py (config overrides).

#### Group A: a refresh request in HALT (finding 8 c)

##### A1. Where the END-block runs first diverge (baseline)

Of 2,142 refresh-on runs (F8, F13, F17, F18 with refresh on; 261 exact), the first divergence
falls at or after the model's H in 412 (F8 4, F13 83, F17 175, F18 150), within 20 clocks
before the END's I/O but before H in 78, earlier in 1,391.

##### A2. Every prefix-matched request at H−1 or later, before the END I/O (398 runs)

H is always the clock after the last fetch's last clock in these runs (the HALT byte's word
delivered on H−1): the gap from the last fetch's end to q is q − H + 1 in all 398. The bus is
idle from H on but for the halt_refresh run's fetches (rows marked x0 ≠ 5 below). With no
refresh in HALT the model's I/O (X0, NOHALTREF) is H+5 at every wait setting (the OUT's DW
setup, H not counted, halt_status). Columns: waits, q−H, silicon's refresh start − H,
silicon's I/O − H, the model's refresh − H, the model's I/O − H; runs; a named run.

Group A: no refresh served on the END's `MOV DW` immediate take (310 runs).

| w | q | sil R | sil I | mod R | mod I | runs | e.g. |
| - | - | - | - | - | - | - | - |
| 0 | 0 | 0 | 8 | 0 | 7 | 13 | F13-s-shlcl9-pO-w0 |
| 0 | 1 | 2 | 7 | 1 | 7 | 22 | F13-s-shlcl2-pO-w0 |
| 0 | 2 | 2 | 7 | 2 | 7 | 1 | F17-w-fd-n3-pE-w0 |
| 0 | 3 | 5 | 10 | 3 | 8 | 1 | F13-r-rfm-f2-pO-w0 |
| 0 | 4 | 5 | 10 | 4 | 9 | 49 | F13-s-shlcl7-pO-w0 |
| 0 | 5 | 5 | 10 | 5 | 10 | 27 | F13-s-shlcl6-pO-w0 |
| 1 | 0 | 0 | 8 | 0 | 7 | 2 | F17-d-n3-empty-pE-w1 |
| 1 | 1 | 2 | 7 | 1 | 7 | 6 | F17-w-fd-n3-pE-w1 |
| 1 | 2 | 2 | 7 | 2 | 7 | 29 | F8-out-ld_bw-k4-pO-w1 |
| 1 | 3 | 5 | 10 | 3 | 8 | 22 | F13-s-shlcl10-pO-w1 |
| 1 | 3 | 5 | 8 | 3 | 6 | 1 | F13-r-rfw-0-pO-w1 (RFW 0: a 3-clock refresh) |
| 1 | 4 | 5 | 10 | 4 | 9 | 1 | F18-a-out-fd-st-pO-w1 |
| 2 | 0 | 0 | 8 | 0 | 7 | 28 | F13-s-shlcl2-pE-w2 |
| 2 | 1 | 2 | 7 | 1 | 7 | 33 | F8-push-empty-pE-w2 |
| 2 | 2 | 2 | 7 | 2 | 7 | 4 | F17-d-n0-empty-pE-w2 |
| 2 | 5 | 5 | 10 | 5 | 10 | 5 | F17-d-n0-empty-pO-w2 |
| 0/1/2 | −1 (fetch on the bus at q) | 0 | 8 | 0 | 7 | 1/16/4 | F13-s-shlcl6-pO-w1 |

The same at every wait setting and both RFT values: a request is served on H+0 (also one
raised at H−1 behind the last fetch), H+2 (requests at H+1 and H+2) and H+5 (requests at H+3,
H+4, H+5), never on H+1, H+3 or H+4; the I/O follows the refresh on its next clock, except
after a refresh on H+0, where it waits 3 more clocks (H+8 for a 5-clock refresh, not H+5).
H+5 is X0, the clock the I/O would issue: a request in the I/O's last two setup clocks (the
class's `lead` 2, the bus unit committed to the I/O) waits for the I/O's issue clock and goes
ahead of it there (refresh_data=refresh). H+1 is HALT's second clock: the halt status
(halt_status: HALT's first clock is the bus unit's) holds the bus unit two clocks, H and H+1;
a refresh pending on H goes first and the status follows it, on E+1, a clock the I/O's count
does not count either (the I/O then E+4 = H+8: count 3 at H−1 in the model, H not counted,
the refresh's B2 and B3 clocks counted as now (refresh_io=waits), E+1 not, E+2, E+3 → 7).
The record's "H+3 accepted" and "H+1 → H+3" (F17) are group B below, where the model's H is
2 clocks late. Rows with fetches in HALT (halt_refresh=run: `F17-s-n2-shlcl1-pE-w1` F0 F4 R8,
`F13-s-shlcl5-pE-w2` F0 F5 R10) are served on the first free clock, as the model does.

Group B: a refresh served on the END's `MOV DW,0FF00h` immediate take (the take of its last,
latched byte; refresh_take=last), beating the fetch request that take raised and that MOV
DW's take sync counts (P − I = 4: the refresh 4 clocks after MOV DW's start; 88 runs):

| w | q | sil R | sil I | mod R | mod I | runs | e.g. |
| - | - | - | - | - | - | - | - |
| 0 | 3 | 3 | 8 | 3 | 8 | 16 | F13-s-shlcl5-pO-w0 |
| 1 | 0 | 0 | 5 | 0 | 7 | 12 | F13-r-rfm-f0-pO-w1 |
| 1 | 1 | 3 | 8 | 1 | 7 | 18 | F8-push-empty-pO-w1 |
| 1 | 2 | 3 | 8 | 2 | 7 | 12 | F13-s-shlcl9-pO-w1 |
| 1 | 3 | 3 | 8 | 3 | 8 | 15 | F13-s-shlcl2-pO-w1 |
| 2 | 0 | 0 | 5 | 0 | 7 | 14 | F13-s-shlcl7-pE-w2 |
| 2 | 1 | 3 | 8 | 1 | 7 | 1 | F17-s-n0-shlcl8-pO-w2 |
| 2 | −1 | 0 | 5 | 0 | 7 | 11 | F17-s-n0-empty-pO-w2 |

With H' = H − 2 every group B row is a group A row (q' = q + 2: 0 → H'+2, I'+7; 1 → H'+5,
I'+10; 2 → H'+5; 3 → H'+5; −1 → H'+2, I'+7), at every wait setting: in silicon the OUT and
HALT run 2 clocks earlier than in the model after such a take. Without a request in HALT the
same runs show it directly: the END I/O at H+3 in silicon, H+5 in the model (19 prefix-matched
runs, `F18-bd-n0-shlcl4-pO-w0`, `F18-a-out-fd-shlcl31-pO-w1`, `F18-bd-p-n2-shlcl4-pO-w2`; and
13 more where the model's late I/O lets a refresh in first, `F17-p-n0-empty-pO-w0` I3 against
the model's R I10).

##### A3. Group B's state: the take sync on a fetch a refresh beat

In the model (`F17-s-n0-shlcl1-pO-w0`, w0): MOV DW starts 203, takes its immediate 206 and
(latched byte) 207, the request raised on 207 is beaten by the refresh 207–211 (q = 207), the
take sync (take_sync=pending) waits for that fetch, 212–214, the OUT starts 215 (start_sync:
no start while a fetch is in flight), its I/O is posted there, the b2b fetch 215–217, HALT
218, I/O 223 (silicon 221). Refresh-off the same take (`F17-e-n0-shlcl1-pO-w0`) has the fetch
on the take clock 187–189, OUT 190, HALT 193 (after the b2b fetch 190–192), I/O 198: OUT at
TL+3+w, HALT at TL+6+2w (TL the latched take). Silicon's group B is that schedule moved by 3
= the refresh's length less 2: OUT at TL+6+w, HALT at TL+9+2w (w0 213/216, w1 232/236, w2
248/253 in the three runs F17-s-n0-shlcl1-pO-w0, F8-push-empty-pO-w1, F13-s-shlcl7-pE-w2),
while the fetches move by the whole 5: for the EU the fetch run that follows the refresh (the
beaten fetch and the fetches back to back behind it) is 2 clocks earlier than on the bus: the
take sync is met on the beaten fetch's last clock but one, and an instruction start waits
for that run's fetches only up to their last clock but one (the run's next fetch, committed
back to back, holding it from the previous one's last clock). The F13 count-loop stall of
(length − 2) per refresh is the same quantity. beat.py: 1,264 prefix-matched refreshes beat
a fetch request on a take clock; 382 with MOV r16/r8,imm's sync counting it (70 of their runs
exact, 312 diverging later), the rest in shift/multiply/divide/memory classes.

##### A4. Other END-block facts

* A refresh that beats the b2b fetch the bus unit committed to after HALT has started drops
  it: `F13-s-shlcl7-pE-w2` (with group B corrected: HALT 253 while the b2b fetch 250–254 runs,
  the request on its last clock committed back to back, the refresh at 255 = H+2 beats it):
  silicon R255 I260, no fetch; halt_refresh=run (the flag raised by an earlier refresh never
  clears) runs it at 260 and the I/O at 265. The rule's own evidence (`F17-s-n0-empty-pE-w0`:
  the refresh at 189 before HALT, F194 F197 I200) is a request beaten before HALT started.
* 37 prefix-matched rows (after the rules below) still serve one clock later than silicon,
  all with a third fetch back to back in HALT after a group-B take (`F17-s-n2-out-pE-w0`:
  R−9 F−4 F−1 F2 R5 I10, model R6 I11; w1 R6 I11, w2 R7 I12): silicon's I/O is due a clock
  earlier than the model's count gives (the request at the third fetch's end + 1 goes then,
  in the model it is in the I/O's lead). The count's lost clocks (dw_count: a fetch's issue
  clock, HALT's first) fall where the fetches are for the EU, 2 clocks earlier; moving the
  b2b exclusion by 2 alone does it at w0 but not at w1/w2, where the posted clock is a wait
  state the nowait count skips (−127 runs): the count would need the whole bus state seen 2
  clocks early. Open.

#### Addendum (written after the group A prototypes; tabulations under fit-wp34-hand.json unless stated)

##### Group B: the RFMON store under a refresh on its displacement (finding 8 h, 1 run)

`F17-p-n1-shlcl31-pO-w1` (P: refresh on from the FCh prelude; `LS RFMON NOP X LS END`, X =
`MOV CL,31 ; SHL AW,CL`; RFMON = 26 C6 06 E1 FF FC). The model (twenty-fourth fit): the ES
prefix 90–91, the store starts 92 (EA clocks 2), takes its displacement word 93–96 (the
eighteenth fit's head: after the EA clocks), the request at 96 is served at 96 on the take's
last byte (refresh_take=last), the store's `clocks 1` step after the displacement (its
address add) begins on 97, a micro-boundary (the step's first clock: refresh_clk_start
=after_wait counts a step straight after a take as no boundary only inside the step, while
the hold's check ahead of the step treats the step's first clock as one), so the EU waits
97–100, the clocks step runs 101, the write is posted 101 (setup 2), the on-chip SFR write
103–105 (sfr_cycle=io), the next fetch 106. Silicon: the next fetch at 104 and every later
event 2 clocks earlier up to the closing LS (its first divergence, index 9). The SFR write
is not on the pins; 104 puts it at 101–103: posted by 99, i.e. the EU did not wait for the
refresh at the address step nor at the post: the refresh at 96 left the address phase
running and the write waited for the bus (free at 101). The free-hold and slot rules of the
twentieth to twenty-second fits do not apply (no fetch is requested in 96–103: the queue
holds 4 bytes with the IR, room 2 is taken by the write's slot).

Tested: no boundary straight after any take (−214 runs: MOV CL's immediate → SHL's exec is
a hold point the F13 S series pins); a post step never a boundary (alone 0 change); the
clocks step after a two-byte displacement's take alone (0 change); both together, only after
a displacement (refresh_disp=free): +3 −0 (`F17-p-n1-empty-pO-w1`, `-shlcl8-`, `-shlcl31-`),
matched +94. The two parts are one state: the memory form's address phase between its
displacement and its posted request.

##### Group C: the first LS under a refresh-on prelude (finding 8 a), facts only

F18 A, the first LS's end (the restart fetch, rel t_fill) model − silicon per prelude cell,
8 runs per cell (X ∈ 8 forms), under fit-wp34-hand.json (the WP34 rules move none of them):

| RFM | marker | pE w0 | pE w1 | pE w2 | pO w0 | pO w1 | pO w2 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ECh | PUSH, OUT | 0 (8) | 0 | 0 | 0 | 0 | 0 |
| FCh | PUSH | 0 (8) | 0 (8) | −1 (8) | −1 (7), −5 | 0 (7), −6 | 0 (7), −6 |
| FCh | OUT | 0 (8) | +2 (8) | 0 (8) | −2 (4), −3, −4 (2), −35 | 0 (7), −6 | +4 (7), −1 |
| FDh | PUSH | 0 (8) | 0 (8) | 0 (8) | 0 (7), −3 | 0 (7), −3 | +3..+5, +31 |
| FDh | OUT | 0 (8) | −1 (8) | +2 (8) | 0 (7), −3 | 0 (7), −3 | 0 (7), −3 |

16 of the 24 refresh-on cells are right at the first LS's end with the stand-in (the
model's own fill with SILICON_FILL and PRELUDE_COUNTER); 8 are off by −2..+4 in every run of
the cell (one X per cell more where the X's own first refresh differs). The prelude tail run
by the model (prelude_tail=segs with wlatch_ir_at=start) under the WP34 rules: +45 −106 over
the four refresh families (regs: +15 −140), matched −2,265: still worse than the stand-in, as
in the fifteenth fit. The one-rule derivation (the refresh beating a register load's fetch,
the LS waiting for a refresh at its exec's first boundary) cannot be read off: the prelude's
fetch train is before clock 0, where the recorded trace's events are not in the aligned
lists the model is compared on, and the model's anchor (clock 0 against t_fill) has no fixed
point under refresh in the cells that are off (`F17-p-n0-empty-pE-w2`, the record). No rule.

##### Group D: F13's first divergences (426 refresh-on runs; S0's 36 refresh-off controls exact)

Phase of the first divergence: at or before the first LS's restart fetch ("first LS"), in X or
the second LS ("X"), in the END block from the model's H − 1 on ("END"); kind: both events
the same kind (a clock difference) or silicon/model kinds.

| config | exact | first LS | X | END |
| --- | --- | --- | --- | --- |
| twenty-fourth fit (sc24v) | 31 | 278 | 34 | 83 |
| fit-wp34-hand.json | 115 | 262 | 26 | 23 |
| fit-wp34-hand + refresh_align=phase_eu (diagnostic, a per-run alignment, not in the fit) | 168 | 181 | 41 | 36 |

By series under fit-wp34-hand.json: S 58 exact; first LS 67 same-kind + 31 refresh/fetch
(a refresh where silicon fetches: the request served a clock off at the restart); X 16; END
12 fetch/io_write + 2: silicon fetches at H+2 where the model has no fetch request
(`F13-s-shlcl4-pO-w0`: the OUT starts and loads the IR at H−5 with room 3 and no request
raised in the model (request_eval), the refresh H−5..H−1, HALT at H; silicon F H+2, I/O H+5:
a request standing at the refresh that goes after HALT's two status clocks, H and H+1, as
refresh_halt has them; the model's I/O is right). Open: the request is not raised in the model. C (cost
frames) 30 exact; first LS 78 same-kind + 31 other; X 9; END 8. U (MULU) first LS 29, X 1.
N (NOP train) first LS 11, END 1. R (RFM sweep) 27 exact, first LS 15. So 262 of the 311
inexact refresh-on F13 runs first diverge in or before the first LS, which the record
already put down to the prelude's phase (finding 8 a): the counter's value at clock 0 is
read off, but the first LS's start against it under a refresh-on prelude is the stand-in's;
phase_eu, shifting the first LS's exec −4..4 per run, takes 81 of them past the first LS.

None of the twentieth to twenty-fourth fits' rules moves an F13 first divergence: each of
free_hold, free_idle, io_older, ea_floor, disp_io, ea_ir_room, imm_start, rmw_alu,
slot_room, slot_idle, slot_latch, abort_fixed, fixed_floor, lookup_start, io_take_nx,
modrm_port, nop_hold, port_issue, latch_start, abort_latched, ea_b2b, free_idle_b2b and
grp_io_hold flipped back changes no F13 event; abort_reg_end=keep moves 2 U runs' first
divergence earlier (4 matched events). The S series' chains have no memory form, no
displacement and no I/O form before the END, so the free-clock, slot and latch rules are
never reached there.

### The refresh side's remainder: the END I/O's count beside the early fetch run, the lost request in HALT, the loop's eve, the F17 ladder and F18 B/BD (twenty-sixth fit, 2026-10-22)

Written 2026-10-22 from the recorded runs and the twenty-fifth fit's model state (fit.json =
fit-wp34-hand.json, 16371/17822; refresh-on F8 7/48, F13 151/462, F17 480/798, F18 386/1164;
refresh-on END mismatches 1380). Clocks rel t_fill unless written H+n (H = the model's HALT
start in the END block `MOV DW,0FF00h ; OUT DW,AW ; HALT`), E (a unit form's exec start in
the model), eve (the shift's exec clock 2 before its count loop, `left == 2`). "Prefix
matched" up to a clock: every event of both runs starting before it is identical.

Tools (scratchpad wp35/): runs.py, cmp.py, mk.py, show.py (as wp34); cnt.py / cntall.py (the
END I/O request's setup count clock by clock from its post, with the reason each uncounted
clock is uncounted: h HALT's status clock, w a memory wait state (io_count=nowait), S a cycle
starting, b a back-to-back fetch (dw_count_b2b), P the post clock, e the clock's cycle is a
fetch of refresh_sync=run's early run); ctab.py (the END I/O's due clock model vs silicon by
that pattern, prefix matched to the post); endst.py (the queue at the END OUT's start);
haltflag.py (the queue's flag and room at H-1, both sides' fetches after H); drops.py (every
request refresh_drop loses: class, in a loop or not, the next fetch); lad.py / ladtab.py /
fdloc.py / f17tab.py (the unit forms' exec/loop spans and the requests in them, first
divergences by phase); eve4.py (every eve decision with a request pending); fdall.py (per
run: where the first divergence is); rf2.py (delivery-clock fetches after a refresh-beaten
fetch). Per-run first divergences: wp35/fd-base.txt (twenty-fifth fit), wp35/fd-final.txt
(final), one line per refresh-on run: id, phase, the two events.

#### 0. Where the refresh-on runs first diverge

Phase: "first LS" (at or before the first LS's shift exit + 3), "X" (after it, up to the
END's `MOV DW` start: X, the closing LS), "END" (from `MOV DW`'s start on). 2,472 refresh-on
runs (F8, F13, F17, F18, refresh-on cells only).

| series | twenty-fifth fit: exact / first LS / X / END | final (fit-wp35-hand): exact / first LS / X / END |
| --- | --- | --- |
| F8 PUSH | 6 / 8 / 6 / 4 | 10 / 8 / 6 / 0 |
| F8 OUT | 1 / 4 / 19 / 0 | 1 / 4 / 19 / 0 |
| F13 S | 58 / 62 / 52 / 14 | 86 / 62 / 38 / 0 |
| F13 C | 30 / 39 / 77 / 10 | 42 / 39 / 75 / 0 |
| F13 U, N, R | 27 / 25 / 30 / 2 | 28 / 25 / 30 / 1 |
| F17 S | 146 / 0 / 122 / 44 | 219 / 0 / 93 / 0 |
| F17 D | 63 / 0 / 20 / 13 | 76 / 0 / 20 / 0 |
| F17 C | 10 / 0 / 22 / 4 | 14 / 0 / 22 / 0 |
| F17 P | 8 / 30 / 22 / 0 | 12 / 30 / 18 / 0 |
| F17 W | 63 / 0 / 26 / 7 | 67 / 0 / 26 / 3 |
| F18 A, AC | 82 / 64 / 42 / 16 | 102 / 64 / 38 / 0 |
| F18 B (no ES: NOP / ES: NOP) | 69 / 0 / 256 / 11; 46 / 0 / 282 / 8 | 110 / 0 / 226 / 0; 80 / 0 / 256 / 0 |
| F18 BD (both) | 93 / 0 / 92 / 7 | 100 / 0 / 92 / 0 |
| all | 702 / 232 / 1068 / 140 | 947 / 232 / 959 / 4 |

The four END rows left: `F13-r-rfm-f3-pO-w2` (a fetch 1 clock early in the model, 161/160),
`F17-w-fd-n5-pE-w0`, `-n6-pO-w0`, `-n6-pO-w1` (a refresh 2 off, the W FDh RFT switch).

#### Group A

##### A1. The END I/O's count beside the early fetch run (item 8 c)

Every refresh-on run prefix matched up to the END OUT's post, grouped by the post (rel H) and
the setup clocks the count does not count (cntall.py, rel H); "E" rows: the post falls inside
refresh_sync=run's early fetch run (the beaten synced fetch and the fetches back to back
behind it). Due clock: "d" the I/O with no refresh before it (silicon − model), else both
sides' refresh(es) and I/O rel H. Twenty-fifth fit; every non-E row (35 patterns, 469 runs)
agrees but one group, A2.

| w | post | uncounted (e = a fetch of the early run) | silicon / model | runs | e.g. |
| - | - | - | - | - | - |
| 0 | −3 | −1 Sb e, 0 h | R5 I10 / R5 I10; d 0 | 20; 19 | F13-s-shlcl5-pO-w0 |
| 0 | −3 | −1 Sb e, 0 h, +2 Sb e | R5 I10 / R6 I11; d −1; R none I5 / R6 I11 | 15; 11; 7 | F17-s-n2-shlcl16-pE-w0, F17-s-n2-shlcl8-pE-w0, F17-s-n2-shlcl2-pE-w0 |
| 1 | −4 | −4 w e, −2 Sb e, 0 hw e | R5 I10 / same (RFW 1: R5 I9); d 0 | 46 + 1; 5 | F8-push-empty-pO-w1 |
| 1 | −4 | −4 w e, −2 Sb e, 0 hw e, +2 Sb e, +4 w e | R6 I11 / R7 I12; d −1 | 18; 6 | F8-push-empty-pE-w1, F17-d-n0-shlcl16-pE-w1 |
| 1 | −4 | −4 w e, −2 Sb e, 0 hw e, +4 w, +5 w (a refresh at +2) | R2 I7 / same | 26 | F8-push-ld_bw-k4-pE-w1 |
| 2 | −5 | −5 w e, −3 Sb e, −1 w e, 0 hw e | d 0; R5 I10 / same | 14; 1 | F17-d-n3-empty-pE-w2 |
| 2 | −5 | the same, +2 Sb e, +4 w e, +5 w e | R7 I12 / R8 I13; d −1 | 4; 3 | F13-s-shlcl6-pE-w2, F18-a-push-fd-ld-pE-w2 |
| 2 | −5 | the same, +4 w, +5 w (a refresh at +2) | R2 I7 / same | 34 | F13-s-shlcl1-pE-w2 |

Every E row with a third fetch of the run issuing after HALT (+2 Sb e) is a clock early in
silicon (64 runs, the 37 of item 8 c among them; at w0 7 of them need no refresh before the
I/O at all, the I/O due at H+5); every E row without it is right. Read as the EU sees the
run (2 clocks earlier, refresh_sync=run): at w0 the run's fetches issue on −3, 0, +3 bus
clocks −1, +2 → for the EU −3 (the post clock: a cycle starting on it, dw_count=bus) and 0
(HALT's status clock, where the third fetch's issue falls too): two uncounted clocks
against the bus view's three (−1, 0, +2), so the I/O is due on H+5 as the EU counts, a clock
before the bus view's H+6 (`F17-s-n2-out-pE-w0`, H 215: the request at H+5 goes on the I/O's
issue clock ahead of it, silicon R220 I225; the bus view R221 I226). At w1 the run's clocks −4 (the
beaten fetch's wait), −2 (b2b issue), 0 (wait), +2 (b2b), +4 (wait) seen 2 earlier: −6
(before the post: costs nothing), −4 (the post, now a b2b issue), −2, 0 (with HALT's), +2:
four against five; at w2 (5-clock fetches: waits −5, −1, 0, +4, +5; issues −3, +2) six
against seven. Without the third fetch both views count alike at every wait setting (the
moved clock lands on the post or on HALT's clock, which the bus view already does not
count). The previous package's prototype moved only the b2b exclusion (−127): the wait
states of the run have to move with it, and a moved clock that lands before the post or on
an uncounted clock is absorbed.

##### A2. The request the END OUT's start raises, lost to a refresh (item 8 d)

The END OUT starting on a refresh's issue clock (the refresh B1 at the OUT's start, on the
delivery clock of the fetch the IR load came from), prefix matched to the start (endst.py):
queue at the end of the start clock.

| w | occupancy / room / flag / latched | silicon / model after the refresh | runs | e.g. |
| - | - | - | - | - |
| 0 | 4 / 3 / down / 1 | fetch H+2 (I H+5) / no fetch (I H+5) | 26 | F13-s-shlcl4-pO-w0 |
| 1 | 4 / 3 / down / 1 | fetch H+2 (I H+6) / no fetch (I H+5) | 30 | F13-s-shlcl1-pO-w1 |
| 2 | 4 / 3 / down / 1 | fetch H+2 (I H+7) / none (I H+5); 2 with I +7 more | 12 | F17-s-n0-rmw-pO-w2 |
| 0/1/2 | 3 / 4 / up / 1 | fetch H (= the refresh's end + 1), as the model | 17 / 32 / 34 | F17-s-n0-empty-pE-w0 |

The room-3 rows are refresh_drop's lost request (raised on the delivery clock, the second
byte latched, odd room); in the model it comes back only on the queue's next change, and
nothing changes in HALT. haltflag.py over every refresh-on run prefix matched to H (the same
68 runs): at H−1 room ≥ 2 with the flag down → silicon fetches at H+2 in all 68; flag up
(83, the request the refresh beat) → fetch at H in both; room < 2 → no fetch (and the
refresh-off corpus never has room ≥ 2 at H−1: 15,350 runs). The fetch at H+2 is after HALT's
two status clocks (refresh_halt), ahead of the posted I/O and its hold (silicon's I/O follows
the fetch at H+5+w). Every request refresh_drop loses outside a count loop (drops.py, prefix
matched): 68 with the OUT (HALT next), 35 MOV imm and 4 NOP whose next fetch both sides have
at E+1 (the queue changes there), 10 store_imm (both E+4), and 2 load, 2 store, 5 RMW where
silicon fetches 3–10 clocks earlier than the model (F17-s-n1-st-pE-w2: E+8 against E+11).
A re-raise on the refresh's end (+68 −3: the store_imm's three P runs, 19 more diverging
earlier: the load fetches ahead of its read) is wrong outside HALT; on the next instruction
start it is right in all of them.

#### Group B: the ladder and the loop's eve (items 8 b, g)

##### B1. Every eve with a request pending (eve4.py, prefix matched, no refresh on the bus)

The model's own eve clocks (the shift's exec clock with two left), the request pending
there; silicon takes it on the eve or not; the bus since the previous refresh's last clock
(silicon's events), the previous refresh's age at the eve; the twenty-fifth fit's decision
(refresh_exec=every2_recent, refresh_recent 18 less the waits).

| unit, w | idle clocks since the previous refresh / its age at the eve | silicon takes it at the eve | twenty-fifth fit takes it | runs | e.g. |
| - | - | - | - | - | - |
| SHL AW,CL w0 | 2 / 16 (three fetches after it, the last ending 3 before the eve) | yes | yes | 7 | F8-push-empty-pO-w0 |
| w0 | 4 / 15 | no | yes | 13 | F13-s-shlcl1-pO-w0 |
| w1 | 2 / 15 | no | yes | 64 | F13-s-shlcl5-pO-w1 |
| w1 | 4 / 17 | no | yes | 27 | F8-push-st_bw-k4-pE-w1 |
| w2 | 2 / 12 | no | yes | 7 | F13-s-shlcl9-pE-w2 |
| w2 | 4 / 14 | no | yes | 8 | F18-b-n4-shlcl4-pE-w2 |
| w2 | 2 / 17, 4 / 17 | no | no | 40 | F8-push-nop-k4-pE-w2 |
| every w | 8+ / 25+ (RFT 1), none (first after RFEN) | no | no | 98 | F17-s-n0-empty-pO-w0 |
| SHL AW,4 (C1) w1, w2 | 1 / 14, 1 / 16 | no | yes | 6 | F18-b-p-n6-shli4-pE-w1 |
| C1 w1 | none | no | no | 3 | F18-b-n1-shli4-pE-w1 |

303 decisions: silicon takes the pending request on the eve in 7 (one cell), and waits for
the loop's first clock in 296; the window took 164 of those. No window in clocks or fetches
separates them (the w0 cell taken at age 16 beside w1 ages 15 and 17 not taken; no idle
count either: idle 2 taken at w0 and not at w1/w2). What the window measured was mostly the
hold (B3), not the acceptance.

##### B2. F17 S/D/C first divergences by X and waits (f17tab.py; each cell counts both parities and n)

= exact, L before X's unit (the NOPs, the first refresh after RFEN), x in X's exec/loop, Z
the closing LS's shift, E the END block.

| series X | twenty-fifth fit w0 / w1 / w2 | final w0 / w1 / w2 |
| --- | --- | --- |
| S shlcl1 | =8 / =6 Z2 / =3 E1 L2 Z2 | =8 / =8 / =4 L2 Z2 |
| S shlcl2 | =4 E2 Z2 / =2 E4 Z2 / =4 L2 Z2 | =8 / =8 / =4 L2 Z2 |
| S shlcl4 | =7 Z1 / =7 Z1 / =1 L2 Z3 x2 | =8 / =8 / =1 L2 Z3 x2 |
| S shlcl8 | =6 E2 / =4 E2 Z2 / =4 L2 x2 | =8 / =8 / =4 L2 x2 |
| S shlcl16 | =4 E4 / =6 Z2 / =3 L2 Z1 x2 | =8 / =8 / =4 L2 x2 |
| S shlcl31 | =4 E2 Z2 / =2 E4 Z2 / =1 L2 Z3 x2 | =8 / =8 / =1 L2 Z3 x2 |
| S empty, ld, st, rmw | =24 Z1 E7 / =17 L3 Z5 E7 / =16 L6 Z6 E4 | =32 / =29 L3 / =22 L4 Z6 |
| S mulu | =3 Z1 x4 / L1 Z5 x2 / Z3 x5 | =3 Z1 x4 / =2 L1 Z3 x2 / Z3 x5 |
| S nop8, out | =1 L13 E2 / =7 L4 Z2 E3 / =2 L12 Z2 | =3 L13 / =12 L4 / =2 L12 Z2 |
| D shlcl16, shlcl31 | =9 Z1 E6 / =5 x4 Z2 E5 / =14 E2 | =15 Z1 / =10 x4 Z2 / =16 |
| D empty, mulu | =11 x3 Z2 / =11 x1 Z4 / =13 L1 x2 | the same |
| C (6 X) | =1 L2 x3 Z2 E4 / =5 L2 x4 Z1 / =4 L3 x2 Z3 | =5 L2 x4 Z1 / =5 L2 x4 Z1 / =4 L3 x2 Z3 |

What is left in F17 S is at 2 waits: L2 in every X (`F17-s-n2-shlcl4-pE-w2` and the pO n3
twins: in the NOP train after the first refresh a fetch one clock later in silicon, E−9
against E−10), Z/x at w2 (a request 17 clocks after the exec's start served there in silicon
and a clock later in the model: `F17-s-n1-shlcl16-pE-w2` R E+2, E+17 against E+18; the loop's
iteration parity after a refresh held in the exec, B3), the MULU loop's in-loop requests (B4),
and the NOP/OUT trains' first refresh (L: the first LS's end against the counter, item 8 a,
and the NOP train, C2).

##### B3. The hold at the eve: refresh_recent's wait dependence

With the acceptance at the eve gone (the rule below), refresh_recent only decides whether a
refresh already on the bus at the eve (served on E+2 or E+3) holds the EU there or lets the
exec run into its loop. Scanned on the final configuration (exact runs against it, by waits):

| window | gained (by w) | lost (by w) |
| --- | --- | --- |
| fetch 18 (18 / 17 / 16; the fit) | — | — |
| fetch 19 (19 / 18 / 17) | w2 51 | w0 35, w1 44 |
| clocks 17 (17 at every w) | w0 1, w2 51 | w0 35 |
| fetch 16 / clocks 15 | w0 1–5, w1 6 | w0 35, w1 44 |
| fetch 21 / clocks 19 | w2 31 | w0 35, w1 45, w2 1 |

The best window by waits is 18 / 17 / 17: still not a count of clocks or of fetch lengths, so
the hold's state is not the window either; the hold itself is not on the pins and could not
be tabulated directly (an always-hold / never-hold comparison per run puts nearly every
decision on "hold" but loses 81 exact runs as a rule: several eves per run interact). Open.

##### B4. The rest of the ladder (ladtab.py on the final configuration, prefix matched to the
first request in X's exec window)

Off rows (silicon / model rel E): `SHL AW,1` (D1, exec0): requests at E+1 and E+2 served at
E+3 / E+2 (9 + 6 runs), E+3 at E+3 / E+5 (8), E+5 at E+5 / E+7 (1); `SHL AW,4` (C1) E+5 → E+6 /
E+5 (2), E+6 → E+6 / E+7 (2); `SHL AW,CL` E+4 → E+5 / E+7 after a refresh 15 back (3). The
twenty-fifth fit's D1 rows are the template's split: exec0 5 runs as exec 2, a one-iteration
loop (E+2, E+3) and a 3-clock exit; silicon takes nothing on the loop's first clock and
takes the loop's last and the exit's clock E+5, which a split with the shorter exec0 taken
from the exit (exec 3, loop E+3–E+4, exit 2) gives. The multiply's and divide's first-request
parity is no longer off in any prefix-matched X window (mul E+1 → E+2, E+3 → E+4 both sides,
72 rows); what is left of MULU is in its loop (`F17-s-n2-mulu-pE-w0` the third request at
E+26: silicon E+28, model E+27) and at its end (`F17-s-n1-mulu-pE-w0` the model fetches at
E+29 where silicon refreshes at E+35).

#### Group C: F18 B/BD (facts only)

##### C1. Where F18 B/BD first diverge (final configuration, fdloc.py)

| series | exact | before X's unit | in X's exec/loop | after X | no unit (SHL [BW],CL) |
| --- | --- | --- | --- | --- | --- |
| B (no ES: NOP) | 110 | 84 | 46 | 48 | 48 |
| B (ES: NOP) | 80 | 123 | 42 | 43 | 48 |
| BD | 52 | 12 | 17 | 15 | — |
| BD (ES: NOP) | 48 | 18 | 19 | 11 | — |

"Before X" by kind (silicon / model, silicon − model): B w0 a fetch one clock later in
silicon, 38 runs (n4–n7, `F18-b-n5-shlcl4-pE-w0`: R92 F97 F101 against F100); B-ES w0 a
refresh where the model fetches, 46 runs (n3–n7, `F18-b-p-n4-shlcl4-pE-w0`: R95 F100 then
silicon R108 F113 against the model's F103 R110: item 8 f); the rest 1–11 runs per cell.

##### C2. The fetch on the delivery clock of a refresh-beaten fetch (rf2.py, w0, prefix matched)

A fetch f2 on the delivery clock of a fetch f1 that started on the clock after a refresh's
last (refresh_after=fetch_next), by the EU's state on f2's clock (the instruction class
there, whether it started there with the IR load, the class on f1's last clock):

| on f2's clock | silicon: fetch on f2's clock / later / a refresh first | e.g. |
| --- | --- | --- |
| an instruction starting with the IR load after MOV imm (OUT after MOV DW, SHL after MOV CL) | 149 / 0 / 0 | F13-s-shlcl6-pO-w0 |
| committed back to back on f1's last clock (OUT, SHL, HALT) | 162 / 0 / 0 | F13-s-shlcl5-pO-w0 |
| inside a unit or a take | 51 / 0 / 0 | F17-s-n3-mulu-pE-w0 |
| an instruction starting with the IR load after a NOP (the NOP train, X's unit after it) | 0 / 69 (+1, +4, +5, +8) / 59 | F17-s-n0-nop8-pE-w0, F18-b-n4-shlcl4-pE-w0 |

At 1–2 waits every such fetch is on f2's clock in both. In the refresh-off corpus the same
state (a start with the IR load after a NOP, the fetch on a delivery clock) issues at once
in 1,567 exact runs, so it is the refresh-beaten f1 that differs, and after MOV imm it is
the take-synced f1 (refresh_sync=run's early run). A rule holding such a fetch a clock
(f1 the beaten fetch, not an early run, the request fresh on its delivery clock) gains 0 or
8 and loses 33–108 (the NOP train then fetches 3 clocks early at the next delivery: the
NOP train after a refresh is a clock late in silicon from the refresh on, which the model's
NOP hold does not give). No rule.

#### Addendum (written after the prototypes; scores over all 17,822 runs, refresh-on runs the
only ones that can move; flip-backs on the final configuration fit-wp35-hand.json)

Adopted (each an enum in sim/config.py, default the old model, tests in
`test_sim.RefreshEarlyCountLostRequestAndEve`):

| rule | named run | gain when adopted | flip-back loss on the final configuration |
| --- | --- | --- | --- |
| `dw_view=eu`: an I/O request's uncounted setup clocks owed to a fetch of refresh_sync=run's early run are the clocks 2 earlier, as the EU sees the run; one landing before the post or on an uncounted clock costs nothing | F17-s-n2-out-pE-w0 R220 I225 (bus: R221 I226); w1 R228 I233 (R229 I234) | +64 −0 | −64 exact, END mismatches 1110 → 1191 |
| `refresh_lost=start`: a request refresh_drop loses outside a count loop is evaluated again on the next instruction start (or on the queue's change, as before, if that comes first); at HALT's start it waits out the halt status and goes as a beaten request, ahead of the posted I/O | F13-s-shlcl4-pO-w0 F233 I236 (queue: I236 without the fetch); F13-s-shlcl1-pO-w1 F232 I236 (I235) | +68 −0 (matched +148) | −69 exact, END 1110 → 1187 |
| `refresh_eve=hold`: the loop's eve is a hold point for a refresh already on the bus (within refresh_recent, as before) but never takes a pending request | F17-s-n0-shlcl2-pE-w0 R126 I226 (both: R124 I225) | +113 −0 (matched +1,186) | −113 exact, END 1110 → 1223 |

Refuted and removed: the lost request re-raised on the refresh's end (`after`: +68 −3, 19
runs diverging earlier: the memory forms' fetch before their read), the same without the
I/O-hold precedence (`raise`, identical), only when HALT finds it lost (`halt`: +68 −0 but
matched 10 fewer than `start`); at the eve, acceptance only while the bus has run a cycle on
every clock since the previous refresh ended (`busy`: +113 −0, identical to `hold` on this
corpus: no pending request meets an eve with no idle clock since the previous refresh), only
with at most k idle clocks before the eve (k = 1: +111; k = 2: +40 −30; k = 3: +37 −30),
only when a fetch issued in the last 4/5/6 clocks (+113 / +111 −0 against `busy`'s 2 / +47);
the D1 split with exec0's clock taken from the exit (+4 −1: `F18-b-n0-shl1-pO-w1`, the
lost request's re-raise at the loop exit moving a clock); a fetch requested on a beaten
fetch's delivery clock held a clock (0 to +8, −33 to −108).

Final (fit-wp35-hand.json = fit.json): 16616/17822 (+245 −0 over sc25v: F8 +4, F13 +41,
F17 +98, F18 +102); refresh-off 15,347 exact as before, every refresh-off END block exact
(endchk), no model error; refresh-on END mismatches 1110 (from 1380). The twenty-fifth fit's
rules flipped back on it: refresh_lead=open +1 −116 (it gained 38 before: the 37 third-fetch
rows now close under dw_view), refresh_sync=wait −484, refresh_halt=none −315,
halt_refresh=run −28, refresh_disp=hold −6. Stage 8 from the hand fit: no move (exact
1269/2472 refresh-on, the guard 15347/15350); its alternatives at the hand fit: dw_view=bus
1205, refresh_lost=queue 1200, refresh_eve=both 1156. knob_dependence (exact runs, F8 F13
F17 F18): refresh_recent best 18 / 18 / 19 by waits (the twenty-fifth fit's 18 / 15 / 19:
the 1-wait dependence went with the acceptance), 16 under the PUSH marker; shift_tail,
refresh_tail_bound, rfm_delay, reraise_off none.

### The refresh side's middle: the NOP's end under a refresh, the register shifts' exec windows, the multiply's exit, the aborted request and the I/O lead under a refresh (twenty-seventh fit, 2026-10-22)

Written 2026-10-22 from the recorded runs and the twenty-sixth fit's model state (fit.json = fit-wp35-hand.json,
16616/17822; refresh-on F8 11/48, F13 192/462, F17 578/798, F18 488/1164; refresh-on END mismatches 1110; of the
refresh-on runs 947 exact, 232 first LS, 959 X, 4 END). Clocks rel t_fill unless written E+n: in group A, E is a
refresh cycle's last clock (R its first); in groups B and C, E is a unit form's exec start (the first clock of its
template's exec / loop_odd step in the model). "Prefix matched" through a clock or event: every event of both runs
starting before it (or up to and including it) is identical. "Model" is fit-wp35-hand.json unless stated.

Tools (scratchpad wp36/): runs.py, cmp.py, mk.py, show.py, lad.py (as wp35; base.jsonl / lad-base.json the dumps);
reft.py (per refresh-on run, every model refresh prefix matched through itself: the model's instruction starts
around it with class and opcode, the EU's per-clock rows E-1..E+6, the next three events both sides; reft-base.json);
reftab.py (those by the instruction running at R and the next start rel E); a2.py (the refreshes in whose window
the model starts an instruction after a NOP, by series); b1.py (every request inside a register shift's window,
b1rows.json); c1.py, mul.py (every request inside a register multiply's / divide's exec, rel E and rel the model's
end Z; mul-base.json).

#### Group A: the instruction after a NOP, started inside a refresh's window (item 8 f)

##### A1. Every model instruction start inside a refresh cycle (R < start <= E+1), by the instruction before it

Over the 13,649 model refreshes prefix matched through themselves (all refresh-on runs, every wait):

| w | instruction before / start rel E / class started | refreshes |
| - | - | - |
| 0 | NOP / E / NOP 147, imm 21, mul 9, shift_imm 8, rmw 5, div 4, load 1, out 1, store 1 | 197 |
| 1 | NOP / E / NOP 152, imm 20, shift_imm 12, mul 10, rmw 6, div 6 | 206 |
| 2 | NOP / E / NOP 271, imm 38, shift_imm 18, mul 15, rmw 11, div 9, load 2, out 2, store 2 | 368 |
| 0/1/2 | MOV CL,imm / E+1 / SHL AW,CL | 6 / 43 / 57 |
| 0/1/2 | OUT / E+1 / HALT | 43 / 63 / 46 |
| 0/1/2 | load, SHL AW,imm / E+1 / MOV imm, load | 7 / 7 / 1 |

Every instruction the model starts inside a refresh's window after anything but a NOP starts on E+1, the clock
after the cycle's last (refresh_eu=hold: the EU's first micro-boundary after the cycle starts waits until then;
an instruction start is a micro-boundary). After a NOP the next instruction starts on E itself, at every wait
setting: the NOP's template is `clocks pre0 (4) ; take 0 ; clocks 0`, and the boundary test on E (asked ahead of
the EU's step) sees the empty take as its next step, which it treats as a take the decoder serves while a refresh
runs (refresh_hold_take=port: no hold point). Nothing is taken there: the step is the operand take of a form
without operand bytes. No other template ends in an empty take in the refresh-on corpus (the ES: prefix's
template ends `take 0 ; clocks 2`, a clocks step).

##### A2. Silicon after those refreshes: the next two events rel E, silicon / model ("=" both the same)

By series, waits and the class started on E after the NOP (a2.py; all refresh-on families):

| series | w | started on E | silicon / model (runs) | e.g. |
| - | - | - | - | - |
| F17 S | 0 | NOP | F+1 F+5 / F+1 F+4 (8) | F17-s-n0-nop8-pE-w0 |
| F17 S | 0 | imm, load, mul, out, rmw, store | = F+1 F+4 (12) | F17-s-n3-empty-pE-w0 |
| F17 S | 1 | NOP; imm | = F+1 F+5 (11), = F+1 F+8 (2); F+4 F+8 / F+3 F+7 (2) | F17-s-n0-nop8-pE-w1 |
| F17 S | 2 | NOP; imm; out | = (30), F+8 R+13 / F+7 R+12 (2), F+5 R+10 / F+4 R+12 (1); F+4 F+9 / F+3 F+8 (16); F+4 R+13 / F+3 R+12 (2) | F17-s-n2-empty-pE-w2 |
| F18 B | 0 | NOP | F+1 F+5 / F+1 F+4 (45), F+1 F+8 / F+1 F+4 (4) | F18-b-n5-shlcl4-pE-w0 |
| F18 B | 0 | div, imm, mul, rmw, shift_imm | = F+1 F+4 (14) | F18-b-n3-shlcl4-pE-w0 |
| F18 B | 1/2 | NOP | = (35 / 70) | F18-b-n6-shlcl4-pE-w1 |
| F18 B | 1/2 | imm | F+4 F+8 / F+3 F+7 (4); F+4 F+9 / F+3 F+8 (4), F+4 R+9 / F+3 F+8 (4) | F18-b-n4-shlcl4-pE-w1 |
| F18 B | 1/2 | rmw | F+1 R+11 / F+1 R+13 (2); F+1 R+12 / F+1 R+14 (4) | F18-b-n4-shlmcl-pE-w1 |
| F18 B ES: | 0 | NOP | F+1 R+9 / F+1 F+4 (53), F+1 R+10 / F+1 F+4 (4), F+1 F+8 / F+1 F+7 (4), F+1 F+8 / F+1 F+4 (2) | F18-b-p-n4-shlcl4-pE-w0 |
| F18 B ES: | 0 | imm; rmw | F+4 F+7 / F+3 F+6 (4); F+1 R+10 / F+1 R+12 (2) | F18-b-p-n2-shlcl4-pE-w0 |
| F18 B ES: | 1/2 | NOP | = (70 / 126) | F18-b-p-n4-shlcl4-pE-w1 |
| F18 B ES: | 1/2 | imm | F+4 F+8 / F+3 F+7 (8); F+4 F+9 / F+3 F+8 (6), F+4 R+9 / F+3 F+8 (4) | F18-b-p-n2-shlcl4-pE-w1 |
| F18 BD, BD ES: | 0 | NOP | F+1 F+5 / F+1 F+4 (4), F+1 F+9 / F+1 F+4 (4), F+1 F+8 (2+2), F+1 F+12 (2), F+1 R+25 (2) | F18-bd-n7-shlcl4-pE-w0 |
| F18 BD, BD ES: | 0/1/2 | imm | F+4 F+7 / F+3 F+6 (2); F+4 F+8 / F+3 F+7 (2+2); F+4 F+9 / F+3 F+8 (2+2) | F18-bd-p-n4-shlcl4-pE-w0 |
| F13 N, F17 C, F17 P, F18 A, F8 | 0 | NOP | F+1 F+5 / F+1 F+4 (4), F+1 F+9 / F+1 F+4 (5), F+1 F+12 / F+1 F+4 (1), F+1 S+11 / F+1 F+4 (1) | F17-p-n0-nop8-pO-w0 |

By lead length and parity at 0 waits (F18 B and B ES:, F17 S; the NOP train after a refresh on E):

| series | n (parity) | silicon / model |
| - | - | - |
| F17 S nop8 | n0-n3 pE, pO | F+1 F+5 / F+1 F+4 (1 each) |
| F17 S | n3 pE, the X form on E | = (12) |
| F18 B | n3, n4 pO (X on E) | = (7 each) |
| F18 B | n4 pE, n5 pO | F+5 / F+4 (5), F+8 / F+4 (2) |
| F18 B | n5 pE, n6, n7 | F+5 / F+4 (7 per cell) |
| F18 B ES: | n2 pE, n3 pO (X on E) | imm F+4 / F+3 (2), rmw R+10 / R+12 (1), the rest = |
| F18 B ES: | n3 pE, n4 pO | F+8 / F+7 (2), F+8 / F+4 (1), R+10 / F+4 (2), R+9 / F+4 (2) |
| F18 B ES: | n4 pE, n5-n7 | R+9 / F+4 (7 per cell) |

Read with A1 (in silicon the instruction after the NOP starts on E+1, as every other start in a refresh's window):

* At 0 waits after a beaten fetch (F+1, 3 clocks), the model's next NOP starts on E+4 with the fetch's delivery and
  its IR load raises the next fetch there (F+4). Silicon's F+5 is that NOP on E+5: the NOP on E held to E+1 moves
  the train by one clock, and every later start with it (`F17-s-n0-nop8-pE-w0`: R92 F97, NOPs at 97, 101, 105 and
  109 rather than 96, 100, 104 and 108: F101 on 101's IR load; the request at 108 falls inside the NOP 105-108 and
  is taken on the start at 109 (silicon R109, model R108); that NOP's successor, on E = 113, again on 114; MOV CL
  on 118, its immediate taken on 121 with the fetch (silicon F121, model F116 with MOV CL on 116)).
* At 1-2 waits the beaten fetch is 4-5 clocks: its delivery (E+5, E+6) is a clock on which the model's delivery-clock
  room rule raises the fetch whether or not the NOP starts there, so the NOP train's clock does not show (the "=" NOP
  rows) - but a MOV imm (F+3 / F+4: its immediate taken on start + 3) or SHL [BW],CL (the next refresh 2 clocks
  earlier in silicon) started on E shows it at every wait: every such row in the corpus is a clock late in silicon
  (imm: 20 at w1, 38 at w2, 4 + 6 at w0 where no beaten fetch hides it). At w0 the forms started on E after a beaten
  fetch (F17 S n3, F18 B n3/n4) are "=": their first event is the beaten fetch's, the delivery-clock fetch at F+4
  that both have; their own clock does not show before their first divergence.
* The ES: NOP series (one ES: prefix, then n NOPs) is the same state with another phase: the refresh is taken on a
  NOP's start (q 3 clocks earlier, inside the previous NOP), so the NOP on E raises the fetch F+1 by its own IR load
  (no beaten fetch), and the NOP after it starts on E+4 in the model, on the fetch's delivery, which raises F+4.
  With every start a clock later in silicon that NOP is on E+5, a clock that is not a delivery clock: the room
  there is one byte short of a word and the next start is MOV CL on E+9, whose immediate take (E+12) would raise
  it; the request at E+9 (q, the 16-clock grid) is taken on that start: silicon R+9 F+14 (`F18-b-p-n4-shlcl4-pE-w0`
  R95 F100 R108 F113: the model F103 R110). The plain series differs only by the refresh's place (q on the start, a
  beaten fetch) and lands on a delivery clock; the ES: series' 46 "refresh where the model fetches" runs and the
  plain series' 38 "fetch one clock later" runs are the same clock.
* Nothing in the beaten fetch's delivery differs: the model's take sync and refresh_sync=run do not touch these runs
  (a NOP has no take); the fetch after the beaten one is on the delivery clock in silicon too whenever an IR load
  falls there (C2 of the twenty-sixth fit: 362 of 362 after a MOV imm, inside a unit or committed back to back).
  The NOP train is not a clock longer either: in silicon the NOPs after the held one run 4 clocks apart again
  (F101, R109 = 101 + 8).

#### Group B: the register shifts' exec windows (item 8 b)

##### B1. Every model refresh request inside a register shift's exec window, prefix matched to q (b1.py)

D1 `SHL AW,1` (template: exec0 5 split as exec 2 E..E+1, loop E+2..E+3, exit E+4..E+6, next start E+7), C1
`SHL AW,4` (exec 6 as exec E..E+2, loop E+3..E+10, exit E+11..E+13, next start E+14), D3 `SHL AW,CL` (exec 7 + loop
2 as exec E..E+5, loop E+6.., exit 3); "moved k": the loop started k clocks late in the model (a refresh hold or
unit_hold in the exec). q-E: silicon start-E / model start-E [runs by w].

| unit | q | silicon / model [w0 w1 w2] |
| - | - | - |
| D1 | 0 | 0/0 [0 4 2] |
| D1 | 1 | 3/2 [0 5 4] |
| D1 | 2 | 3/2 [2 4 0] |
| D1 | 3 | 3/5 [1 3 4] |
| D1 | 5 | 5/5 [4 2 0]; 5/7 [0 0 1] (exit moved 2, `F18-b-n0-shl1-pO-w2`) |
| D1 | 6 / 7 | 7/7 [0 4 4] / 7/7 [0 2 0] |
| C1 | -1, 0 | 0/0 [1 4 1] |
| C1 | 1, 2, 3 | 3/3 [4 11 4] |
| C1 | 5 | 5/5 [2 0 0] (`F18-b-n3-shli4-pE-w0`); 6/5 [2 0 0] (`F18-b-n2-shli4-pE-w0`) |
| C1 | 6 | 7/7 [1 0 0]; 6/7 [0 0 2] (`F18-b-p-n6-shli4-pE-w2`) |
| C1 | 7, 9 | 7/7, 9/9 [2 1 7] |
| C1 | 10, 11 | 12/12 [0 8 2] |
| C1 | 14 | 14/14 [2 0 0]; 14/15 [0 0 4] (loop moved 1, `F18-b-n6-shli4-pE-w2`) |
| C1 | 16, 17 | 16/16, 17/17 [0 9 4] |
| D3 | 1 | 2/2 [10 11 68]; 3/2 [0 1 0]; 4/2 [0 0 8] (the first LS, F18 A FCh w2) |
| D3 | 2 | 2/2 [16 18 23] |
| D3 | 3, 4, 5, 6 | 6/6 [238 190 136] |
| D3 | 7 | 8/8 [28 42 9]; 9/9 [0 2 0] |
| D3 moved 1 | 1, 2 | 2/2 [38 43 0] |
| D3 moved 1 | 4, 5 | 5/7 [7 0 0] (`F8-push-empty-pO-w0`, `F13-c-push-shlcl4-pO-w0`) |
| D3 moved 1 | 6, 7 | 7/7 [4 0 0] |
| D3 moved 2-5 | -1 .. 7 | silicon = model in all 405 |

Silicon's acceptance clocks, unmoved: D3 E+2, E+6 (the loop's first clock), E+8, ... (q E+3..E+6 all wait for
E+6: the eve E+4 takes nothing, refresh_eve=hold); C1 E+0, E+3 (the loop's first clock), E+5, E+7, E+9, E+12 (the
exit's clock 2 before its end), E+14; D1 E+0, E+3, E+5, E+7. Against the end of the shift's loop (the exit's first
clock, L = E+6+2n, E+11, E+4 in the template): D3 and C1 take on L-2k (every iteration start, the loop's first
clock among them, the exec's every-2 clocks before it but the eve) and on L+1 (the exit's clock 2 before its end);
D1 takes on E+3 = L-1 and E+5 = L+1. As distances from the instruction's end (E+9+2n, E+14, E+7): D3 and C1 take
on odd distances in the exec and loop and on distance 2 in the exit; D1 takes on distance 4 and 2. D1 is the one
form whose in-loop clock does not fit the template's split: with D1's exit 2 clocks (exec 3 E..E+2 as C1's, loop
E+3..E+4, exit E+5..E+6) its clocks are the loop's first clock E+3 and the exit's E+5 (distance 2 from the end,
as C1's and D3's exit clock), the eve E+1 taking nothing (q 1, 2 -> 3) as C1's and D3's eve. The exec0 form lacks
the count byte, and the clock it lacks (exec0 5 against exec 6) is then the exit's, not the exec's. No other split
of D1's 7 clocks with the shared rules (iteration starts, the eve holding only, the exit clock 2 before the end)
gives E+3 and E+5 and not E+2.

The C1 rows off are 2 + 2 + 4 runs in three different states (q5 taken on E+5 in `F18-b-n3-shli4-pE-w0` and on E+6
in `F18-b-n2-shli4-pE-w0`, same template, same age 16; q6 on E+6 at w2 against E+7 at w0): not one boundary.

##### B2. The eve after an exec hold (D3, the 7-run eve cell of the twenty-sixth fit)

The seven D3 rows "moved 1, q 4/5 -> silicon 5, model 7" are all w0 PUSH-marker runs (`F8-push-empty-pO-w0`, F13 C
PUSH pO) where unit_hold held the exec a clock on E+2 (fetch E+0..E+2 past its second clock: the exec's micro-
boundary waits for its end), so the eve is E+5 and the loop starts on E+7. Silicon takes the request pending at the
eve there (E+5); the model (refresh_eve=hold) waits for the loop's first clock. Every unmoved eve with a request
pending (q E+3, E+4: 243 rows at every wait) waits in silicon. There is no moved eve with a request pending that
silicon does not take in the corpus (7 of 7, all w0, all one cell family).

Also left in D3 after the exec window (not this group's): 324 rows off over all D3 requests, mostly in the long
loop's iteration parity after a refresh held in the exec (q E+17 at w2 45 runs: silicon E+17, model E+18; q E+18
-> E+19/E+18, 28; item 8 g's hold window) and the first LS (item 8 a).

#### Group C: the register multiply (item 8 b)

##### C1. Every model refresh request inside a register MULU's exec, prefix matched to q (c1.py, mul.py)

MULU AW: exec 31 as one loop_odd step: boundaries where the clocks left to the exec's end are odd (E+2, E+4, ...
before any refresh; the refresh's hold at the next boundary adds 3 clocks, after which the boundaries are the odd
offsets, and so on). Z = the model's next instruction start rel E (31 + 3 per refresh held). The first request in
the exec (no refresh before it), silicon = model for every q from -1 to E+22 (218 rows, w0-w2); of all 488
prefix-matched MULU rows 87 are off (c1.py); the first off request per run:

| refreshes before (rel E) | q | silicon / model | Z | Z - silicon / Z - model | runs [w] | e.g. |
| - | - | - | - | - | - | - |
| - | 23 | 25 / 24 | 34 | 9 / 10 | 2 [0] | F18-a-push-fd-mulu-pO-w0 |
| - | 24 | 26 / 25 | 35 | 9 / 10 | 2 [0] | F18-bd-n5-mulu-pE-w0 |
| - | 25 | 25 / 26 | 34 | 9 / 8 | 1 [0] | F18-a-push-fd-mulu-pE-w0 |
| - | 26 | 27 / 26 | 34, 36 | 7 / 8, 9 / 10 | 2 [0], 4 [1] | F18-bd-n4-mulu-pE-w0 |
| - | 30 | 30 / 31 | 37 | 7 / 6 | 3 [0 2] | F18-bd-p-n2-mulu-pE-w0 |
| 0 | 31 | 32 / 31 | 37 | 5 / 6 | 4 [1] | F18-bd-n4-mulu-pE-w1 |
| 2 | 33 | 34 / 33 | 38 | 4 / 5 | 6 [2] | F17-d-n2-mulu-pE-w2 |
| 10 | 26 | 28 / 27 | 37 | 9 / 10 | 4 [0] | F17-s-n2-mulu-pE-w0 |
| 12 | 27 | 28 / 27 | 40 | 12 / 13 | 5 [2] | F17-s-n1-mulu-pE-w2 |
| 15 | 30 | 31 / 30 | 40 | 9 / 10 | 4 [0 2] | F18-b-p-n1-mulu-pO-w0 |
| 0, 15 | 31 | 31 / 32 | 40 | 9 / 8 | 1 [0] | F17-p-n1-mulu-pO-w0 |
| 0, 17 | 32 | 33 / 32 | 40 | 7 / 8 | 11 [0 1 2] | F13-u-none-mulu-pE-w2 |
| 2, 17 | 33 | 33 / 34 | 40 | 7 / 6 | 13 [1 2] | F17-s-n2-mulu-pE-w1 |
| 2, 19 | 34 | 35 / 34 | 40 | 5 / 6 | 7 [0 1] | F13-u-push-mulu-k1-pO-w1 |
| 3, 20 | 35 | 36 / 35 | 41 | 5 / 6 | 1 [0] | F17-p-n0-mulu-pO-w0 |
| 4, 19 | 34; 35 | 35 / 34; 35 / 36 | 42; 41 | 7 / 8; 6 / 5 | 2 [1]; 9 [1 2] | F17-s-n1-mulu-pE-w1 |
| 5, 22 | 37 | 38 / 37 | 43 | 5 / 6 | 2 [2] | F17-s-n0-mulu-pO-w2 |

Of the requests the model serves 11 or more clocks before Z (mul.py, every request, any refreshes before), 308
are served as silicon does and 5 are off (the (12) row at w2, Z - 12 / 13); every other off row is a request
taken in the exec's last part. There
silicon takes on Z - 9, 7, 5 (the end after this refresh's own 3-clock hold), the model on Z - 10, 8, 6. Counted
in the exec as it stood before that refresh (the end Z - 3), silicon's clocks are 6, 4 and 2 clocks before the
exec's end and the model's 7, 5, 3; in the exec's first part both are the odd distances (9 and more). Silicon's
last odd-distance clock is 9 before the end (no refresh before: q21, q22 -> E+22 in both, Z 34, 7 + 4 runs; q23
-> silicon E+25 = 6 before the pre-hold end, nothing on 8 or 7). Three rows do not fit (2 [w2] Z - 4; 12 [w2]; 4,19 q35 [w1 w2] 6 before): all with a
later divergence before Z, where Z may not be silicon's. So the multiply's last 8 exec clocks run as an exit: its
clocks are those 6, 4 and 2 before the end, the even distances, as the shift's 3-clock exit has its one clock 2
before its end (refresh_tail_bound), the exit's first clock not one (no request is taken 8 before the end). The
loop before it (23 clocks) keeps the odd distances to its own end, which are the same clocks as before.

The divide (refresh_unit=muldiv: the same loop_odd template; 202 rows, 17 off, the 61 first requests all right):
off rows (10, 25) q41 41/42,
(10, 27) q42 43/42, (12, 27) q43 43/44 and 43/48, (15, 30) q46 46/47, (8, 23) q39 41/40, (9, 24) q40 42/41,
(9, 26) q41 42/41: all third requests late in the exec.

##### C2. The multiply's end: the retry fetch after a refresh held in the exec (mul.py, prefix matched through the exec)

A register MULU started on an aborted fetch cycle with no retry in flight (abort_reg, io_take: the request
raised again mtail = 2 clocks before the exec's end, `q.retry_at`):

| w | refreshes in the exec | silicon / model first event rel Z | runs | e.g. |
| - | - | - | - | - |
| 0 | 1 | F-2 / F-5 | 10 | F17-d-n1-mulu-pE-w0 |
| 1 | 1 | F-3 / F-6 | 8 | F17-d-n3-mulu-pE-w1 |
| 0 | 2 | R-5 / R-6 (the retry's fetch beaten) | 4 | F17-s-n1-mulu-pE-w0 |
| 0/1/2 | 1 or 2, no retry pending | = (F+3 or R+3 or R+0) | 64 | F17-d-n0-mulu-pE-w0 |

The model sets the retry clock at the exec's start (resume - mtail) and the refresh's hold moves the exec's end by
3 without moving it: the request rises 5 clocks before the end the exec then has (F17-d-n1-mulu-pE-w0: exec
90-123 with the refresh 100-104 held on 102-104, the retry raised at 119, F119; silicon F122 = the end 124 - 2).
Silicon's retry is mtail before the end the exec has after the hold, at every wait setting (w1: F-3 is the fetch's
issue, 4-clock fetch). `F17-s-n1-mulu-pE-w0` (the model's fetch at E+29 where silicon refreshes at E+35, two refreshes held in the
exec) is the 0-wait two-refresh row: the model's retry fetch at the unmoved clock, silicon's request taken first
and the retry fetch behind it (checked under the rule work, addendum).

#### Addendum, read off during the rule work (after the facts above were written)

Prototype scores are over the refresh-on dumps (runs.py over F8 F13 F17 F18; no refresh-off run can move: every
rule is read only with refresh on), exact runs and matched events, against the configuration before the step.

##### Group A

The empty take as no step (`refresh_take0=none`) on fit-wp35-hand: +153 -0 (F8 1, F13 4, F17 33, F18 115),
matched 30,108 -> 32,930, 228 runs diverging later, none earlier. Re-tabulated (reft.py on the final
configuration): every instruction started after a NOP inside a refresh's window now starts on E+1 and every row
is "=" in silicon at every wait (182 / 152 / 269 NOP -> NOP, all imm, mul, div, shift_imm, load, store, out rows)
except two families: SHL [BW],CL started on E+1 after a NOP (16 refreshes, F18 B / B ES: n2-n4: silicon's next
refresh 2 clocks earlier, R+10 / R+12; the memory shift's loop, not this state) and 2 F17 P / F13 N rows. The
previous package's one-clock hold on the delivery-clock fetch (0 to +8, -33 to -108) moved the fetch, not the
start: the NOP train after it was still a clock early.

##### Group E (found in the X-phase re-read): the aborted request under a refresh

ustart.py: every refresh (prefix matched through it) taken on the clock an instruction starts, the model's next
event a fetch on E+1 (the beaten request), by the form started and the queue at R (twenty-sixth fit + WP36 A-C):

| form started on R | w | room at R | silicon / model next events rel E | refreshes |
| - | - | - | - | - |
| MULU AW, DIVU (F7 /4, /6) | 0/1/2 | 2 | no fetch on E+1: R+9 R+26, R+11 R+28, R+26 F+33 ... / F+1 R+10 ... | 6 / 15 / 13 |
| MULU AW, DIVU | 0/2 | 3, 4 | = (F+1) | 19 / 1 |
| SHL AW,1 (D1) | 0/1/2 | 2 | F+6 or F+11 / F+1 | 2 / 7 / 4 |
| SHL AW,1 | 0 | 3 | = F+1 | 6 |
| SHL [BW],CL | 0/1/2 | 2 | R+9 D+14, D+9 R+13 / F+1 R+10 | 2 / 7 / 4 |
| SHL AW,4 (C1, count byte still to take: no IR load) | 0 | 2 | F+1 (= but for the later refresh) | 6 |
| SHL AW,CL, MOV imm, NOP, OUT, loads, stores | all | any | = | 1,000+ |

Every register unit form started on a refresh's issue clock with room for exactly one word, the clock on which
the start, the ModR/M take and the IR load fall together (abort_fetch's triple: on a free bus the request is
answered by an aborted cycle), loses the request in silicon: nothing on E+1, the fetch at the unit's loop exit /
mtail before its end, as after an aborted cycle. With room 3 or 4 (no abort on a free bus either) the beaten
fetch runs on E+1 as the model has it. `refresh_abort=abort` (the request aborted as on a free bus, the refresh
on the bus): +43 -0 (F17 2, F18 41), matched +655. A memory shift (SHL [BW],CL) started so retries in the model
on the next cycle's end (the refresh's), F+1; silicon fetches only after the shift's write (F18-b-n3-shlmcl-pE-w1
F205 after W201); a retry held to the write's end gained no run (+57 matched) and the 64 refresh-off memory
shifts started on an aborted cycle (exact, F5-push-shl_m1-k2-pE-w0 ...) have the retry after the read, so it was
not kept.

##### Group F (found in the X-phase re-read): the I/O lead under a refresh

ioh.py: refreshes (prefix matched) that start while an I/O request is posted and a fetch request is raised and
held by it, by waits, setup clocks left at R, the fetch request's age at R:

| w | left | age | silicon / model | refreshes |
| - | - | - | - | - |
| 0/1/2 | 4 | 3 | F+1 I+4 (I+5, I+6) / I+2 F+5 (I+4 F+7) | 21 / 3 / 1 |
| 0/1/2 | 3 | 2 | = I+1 | 24 / 9 / 28 |
| 0/1/2 | 0 | 5 | = I+1 | 45 / 7 / 2 |
| 0/1/2 | 5, 7, 3 | 0 (beaten) | = (mostly; 2 7 0: F+1 F+6 / F+1 I+7, 19) | 300+ |

The 4/3 rows are the marker OUT 20h,AL (F13 C OUT, F8 OUT, F13 U OUT, F17 S out): the I/O posted on the port take
with the fetch raised on the same clock (no younger than the I/O: io_hold lets it run on the lead's first clock),
the refresh still on the bus on the clock the hold lifts. Silicon runs the fetch on the clock after the refresh
and the I/O behind it; the model spends the lead's first clock under the refresh and holds the fetch to the
issue. `refresh_lift=free` (the lead's first clock for the waiting fetch is its first clock off a refresh):
+14 -0 (F8 2, F13 9, F17 3), matched +334, 25 runs later. The w2 7/0 rows (`F8-out-empty-pE-w2`: the fetch on
the delivery of the beaten fetch's run, raised on the lead's first clock while that run is on the bus) are not
this state: open.

##### Group B, after the rules

* `shift_exit0=exit` alone (exec 3, loop 2, exit 2 for D1, the exit's clock 2 before its end its first): +4 -3
  on the configuration with A and C: the refresh template's seams moved unit_hold's hold points (the exec clocks
  E+1, E+3, E+5 of hphase 1 fall on a seam, where tick does not test unit_hold: F18-b-n0-shl1-pO-w1, the hold at
  E+3 lost, MOV CL a clock early) and the loop exit's re-raise (a clock after the exit's first clock: 2 before the
  end with a 3-clock exit, 1 before with a 2-clock one: F18-b-n1-shl1-pE-w2, F105 against F106). With unit_hold
  tested at the split's seams (no change on any run under the old split: 0 / 0) and the re-raise kept 2 clocks
  before the shift's end (the 2-clock exit's first clock): +4 -0; with the 2-clock exit's first clock a hold
  point as well as an acceptance point (the EU waits there for a refresh taken on E+3: F18-b-n1-shl1-pE-w1, MOV
  CL on 105 not 103): +33 -0 in all. Re-tabulated, every D1 row is right.
* The eve after a unit_hold wait taking the pending request (`refresh_eve_held`, prototype): +0 -1
  (`F18-ac-out-fc-pO-w1`: w1, the eve a clock late after unit_hold, the request of 104 pending, silicon R106,
  the rule R104), matched +29: the 7 w0 rows are not separated from it by any state the model has (a 1-clock
  hold at w0, a 2-clock one at w1; ages 16 and 15). Removed.
* C1 started on a refresh's issue clock (`F18-b-n2-shli4-pE-w0` q E+5 -> E+6, `F18-b-n6-shli4-pE-w0` q E+4 -> E+4;
  its twins started after the refresh are right): silicon's exec a clock earlier than the model's (the take sync
  on the count byte met as if the beaten fetch's run were early). The early run extended to a fetch beaten on any
  instruction's start clock: -139; to the unit forms' starts only: 0 / 0 (matched +35). Open (6 runs).

##### Group C, after the rules

`refresh_mul_exit=exit` with mul.rexit 8 on top of A: +157 -0 with no divide exit; the divide's exit scanned
with mul 8: div 2 +157, 4 +168, 6 +196 -0, 8 +173 -11, 10 +166 -20, 12 +166 -24; mul scanned with div 6: 6 +153,
8 +196, 10 +160 -17. `refresh_retry=end` alone on A: +39 -0; on A with the exit: +2 (most of its runs then have
the retry set at the exit's first clock, after the holds in the loop). Left in the multiply (70 X-phase runs
after all rules): the third request in a two-refresh exec at 1-2 waits, the early fetches of the ES: MULU runs,
and the END at Z with mixed patterns; no further single state read off.

##### Group D

Not resolved. The W FDh runs: the closing LS's shift ends 2 clocks later in silicon (MOV DW's take 2 later: R198
F203 F206 I212 against R196 F201 F204 I210 in `F17-w-fd-n5-pE-w0`), after two refreshes at RFT 1 (32-clock
interval) inside its loop, both served on the same clocks in both: the stall per refresh in that loop is not the
model's 3 on one of them. `F13-r-rfm-f3-pO-w2` (RFW 0, a 3-clock refresh at 87 in the loop): the shift ends a
clock later in silicon (MOV DW 157 against 156): a 3-clock refresh stalls the loop 2 clocks there, not 1. Two
cells, one or two runs each: no state rule read off.

##### Final (fit-wp36-hand.json = fit.json)

17,055 / 17,822 (+439 -0 over sc26v: F8 +3, F13 +19, F17 +63, F18 +354); refresh-off 15,347 exact as before, every
refresh-off END block exact (endchk), no model error; refresh-on END mismatches 731 (from 1110). Refresh-on runs:
1,386 exact, 232 first LS, 520 X, 4 END (947 / 232 / 959 / 4 before). By series (exact / first LS / X / END):
F8 PUSH 11/8/5/0, F8 OUT 3/4/17/0, F13 S 86/62/38/0, F13 C 50/39/67/0, F13 U N R 39/25/19/1, F17 S 268/0/44/0,
F17 D 83/0/13/0, F17 C 17/0/19/0, F17 P 16/30/14/0, F17 W 67/0/26/3, F18 A AC 122/64/18/0, F18 B 229/0/107/0,
F18 B ES: 221/0/115/0, F18 BD 85/0/11/0, BD ES: 89/0/7/0.

Flip-backs on the final configuration (refresh-on exact runs lost, END mismatches 731 ->): refresh_take0=take
-190 (907), refresh_mul_exit=none -188 (882), refresh_retry=fixed -14 (741), shift_exit0=tail -33 (764),
refresh_abort=beat -43 (767), refresh_lift=clock -14 (745); none gains a run. Stage 8 from the wrapped hand fit:
no move (exact 1708/2472, guard 15347/15350; alternatives at the hand fit: take0=take 1518, mul_exit=none 1520,
retry=fixed 1694, shift_exit0=tail 1675, abort=beat 1665, lift=clock 1694; wlatch_ir_at=start ties at 1708).
knob_dependence (F8 F13 F17 F18): refresh_recent 18 / 18 / 19 by waits, 16 under PUSH (as before); shift_tail,
refresh_tail_bound, rfm_delay, reraise_off, mul.rexit, div.rexit none.

### The refresh side's middle, continued: the memory shift under refresh, the multiply and divide, the C1 start, the I/O lead and the RFT cells, the posted request's first clock and the write-back sync (twenty-eighth fit, 2026-10-22)

Written 2026-10-22 from the recorded runs and the twenty-seventh fit's model state (fit.json = fit-wp36-hand.json,
17055/17822; refresh-on F8 14/48, F13 211/462, F17 641/798, F18 842/1164; refresh-on END mismatches 731; of the
2,142 refresh-on runs fdall counts (the brief's 2,472 counts the F17 refresh-off W/E cells too) 1,386 exact, 232
first LS, 520 X, 4 END). Clocks rel t_fill unless written E+n (E = the model's start of the form named, the first
clock of its start step), D+n (D = the clock after the last clock of a memory shift's read, the first clock of its
write setup) or d (clocks left to a posted request's issue, d = setup - count on the clock asked: d = 0 is the
issue clock). q is a refresh request (the counter's grid, a constant of the prelude). "Prefix matched" through a
clock or event: every event of both runs starting before it (or up to and including it) is identical. "Model" is
fit-wp36-hand.json unless stated.

Tools (scratchpad wp37/): runs.py, cmp.py, mk.py, show.py, lad.py, b1.py, mul.py, reft.py, fdall.py (as wp36;
base.jsonl the baseline dump); grp.py / grpsum.py (every X-phase run: the model's instruction running at the first
divergence, its chain block, its class, the two events); ms.py / ms2.py / ms3.py (every memory shift: silicon's
read and write, the refreshes between, q and start rel D, the same for the model where the read is prefix
matched); xwin.py (a form's window rel its model start E: EU rows, events both sides; FORM= selects the X form) /
xmssum.py; eaq.py (requests on a clocks step tagged ea); eut.py (per-clock EU rows of one run); named.py (each
adopted rule's named run under the final fit and its flip). Per-run first divergences under the final fit:
wp37/fd-final.txt.

#### 0. The 520 X-phase runs by the instruction at the first divergence (grp.py, baseline)

The model's instruction running on the first divergence clock (min of the two events' clocks), its block in the
chain, and the event pair (silicon / model kind, silicon - model clocks):

| group | runs | series | waits 0/1/2 | main kinds | what it is |
| - | - | - | - | - | - |
| closing LS's shift (SHL AW,CL after X) | 130 | F17 S/D/C/W, F18 A/B/BD, F13 C/S | 16/21/93 | refresh/refresh -1 (64), +1 (46) | the loop's iteration parity after a refresh held in the exec, almost all at 2 waits (item 8 g; B5 below) |
| A: the memory shift SHL [BW],CL | 96 | F18 B, B ES: (every n, parity, wait) | 32/32/32 | refresh -2 (27), +1 (26), read -3 (15) | Group A |
| the marker OUT 20h,AL / 21h after the first LS | 69 | F13 C OUT, F8 OUT, F13 U OUT | 27/25/17 | refresh +2 (20, pE w1), fetch -3 (19, pE w0), fetch/io -1 (17, pE w2) | three whole cells (pE at each wait), C2 below |
| C1 SHL AW,4 | 39 | F18 B, B ES: | 14/8/17 | fetch -2 (16), refresh +-1 (22) | C1 below |
| closing LS's MOV CL | 36 | F17 S, F18 B, BD | 15/4/17 | fetch +1/+2 | X's end moved by its own refreshes (D1, C1, SHL AW,CL n1/n2 cells): the X form's exit, not the LS |
| X's MOV CL in F13 S | 31 | F13 S, every pE w1 run | 0/31/0 | refresh where the model fetches (+2) | the first LS's restart fetch under the FCh prelude (item 8 a), on the phase boundary the classifier draws |
| X's SHL AW,CL | 27 | F17 S/C/D, F13 C, F18 | 4/7/16 | refresh +-1 | the same loop parity as the closing LS (item 8 g) |
| the RFMON store | 26 | F17 W FC/FD n2,n3,n6,n7 at w1/w2; F17 P w2 | 0/8/18 | fetch +3 | the prefixed SFR store's next fetch at 1-2 waits (item 8 e; the W ECh twins miss the same way) |
| the marker PUSH AW | 19 | F13 C PUSH, F17 C, F13 U/N | 6/8/5 | refresh -4 (16) | D below (a posted request's first clock) |
| MULU / DIVU | 16 | F18 B, F13 U, F17 P/C | 2/3/11 | refresh +1 (10), refresh where the model fetches (+8..+12) | Group B |
| loads, stores, OUT imm, NOP, ADD [BW] | 18 | F8, F17 S, F17 P | | | single cells |
| first-LS blocks in the short F13 R / F18 A chains, D1 | 13 | | | | item 8 a and the D1 exit (wp36) |

#### Group A: the memory shift `SHL [BW],CL` (CL = 31) under refresh (F18 B, 96 runs, all inexact in the baseline)

##### A1. The write setup: every refresh between the read and the write (ms.py / ms3.py, silicon, all 96 runs)

Refresh-off (F14 G, `SHL [BW],CL` with CL = 31) the write issues 68 clocks after the read's data at every wait
(read to write 71 / 72 / 73 = read length + 68): the write's setup (rmw.alu 3 + shift_imm.exec 6 + 2 x 30 = 69) is
counted from the post, D, to the issue clock D+68. Under refresh, silicon's (q - D, start - D) per refresh, the
write rel D, and the model's for the same rows where the read is prefix matched:

| w | silicon (q / start rel D) | W - D | runs (read-matched) | model | model W - D |
| - | - | - | - | - | - |
| 0 | -2/0 14/15 30/30 46/47 62/62 78/80 | 85 | 2 (2) | the same but 78/79 | 86 |
| 0 | -1/0 15/15 31/32 47/47 63/64 79/80 | 85 | 4 (4) | ... 79/79 | 86 |
| 0 | 0/0 16/17 32/32 48/49 64/64 80/80 | 85 | 2 (1) | ... 80/81 | 86 |
| 0 | 2/3 18/18 34/35 50/50 66/67 82/83 | 88 | 3 (3) | 2/2 18/19 34/34 50/51 66/66 82/83 | 88 |
| 0 | 5/5 21/22 37/37 53/54 69/69 | 83 | 4 (0) | | |
| 0 | 6/7 22/22 38/39 54/54 70/71 | 83 | 5 (0) | | |
| 0 | 7/7 23/24 39/39 55/56 71/71 | 83 | 8 (4) | 7/8 23/23 39/40 55/55 71/72 | 83 |
| 0 | 8/9 24/24 40/41 56/56 72/73 | 83 | 4 (1) | 8/8 24/25 40/40 56/57 72/72 | 83 |
| 1 | -3/0 13/13 29/30 45/45 61/62 77/77 | 84 | 4 (1) | the same | 86 |
| 1 | -2/0 14/15 30/30 46/47 62/62 78/80 | 85 | 4 (0) | | |
| 1 | 0/0 16/17 32/32 48/49 64/64 80/80 | 85 | 4 (0) | | |
| 1 | 1/3 17/18 33/33 49/50 65/65 81/81 | 86 | 4 (4) | 1/2 17/17 33/34 49/49 65/66 81/81 | 86 |
| 1 | 4/5 20/20 36/37 52/52 68/69 | 83 | 4 (0) | | |
| 1 | 5/5 21/22 37/37 53/54 69/69 | 83 | 4 (0) | | |
| 1 | 6/7 22/22 38/39 54/54 70/71 | 83 | 4 (2) | 6/6 22/23 38/38 54/55 70/70 | 83 |
| 1 | 7/7 23/24 39/39 55/56 71/71 | 83 | 4 (0) | | |
| 2 | -4/0 12/13 28/28 44/45 60/60 76/77 | 84 | 2 (2) | the same | 86 |
| 2 | -2/0 14/15 30/30 46/47 62/62 78/80 | 85 | 10 (6) | ... 78/79 | 86 |
| 2 | 0/0 16/17 32/32 48/49 64/64 80/80 | 85 | 2 (2) | ... 80/81 | 86 |
| 2 | 3/3 19/20 35/35 51/52 67/67 83/83 | 88 | 8 (0) | | |
| 2 | 4/5 20/20 36/37 52/52 68/69 | 83 | 1 (0) | | |
| 2 | 6/7 22/22 38/39 54/54 70/71 | 83 | 9 (0) | | |

No fetch runs between the read and the write in any silicon memory shift. Reading every row with the EU's work
counted (tau = start - D less the clocks the earlier refreshes cost; the write at tau 68):

* Requests at tau 1, 2 are served at tau 3 (1/3 at w1, 2/3 at w0); from tau 3 on silicon serves on odd tau (3, 5,
  7, ..., 63: every q on an even tau waits a clock), i.e. on odd distances d >= 5 from the issue; the model serves
  on even d (its rule: (setup - count) even), the rows 7/8, 8/8, 6/6 against silicon's 7/7, 8/9, 6/7.
* Near the end silicon serves on d = 2 (q at d 3 or 4 waits for it: -1/0 ... 79/80, 2/3 ... 82/83 rows) and on the
  issue clock itself (d 0: the refresh ahead of the write, which then waits the whole cycle: 2/3 ... 82/83, W 88,
  5 more), never on d 1, 3, 4. That is the register shift's exit: 3 clocks (shift_tail) with its boundary 2 before
  its end (refresh_tail_bound), the loop's iteration starts end-aligned before it (d = 5, 7, ...).
* A refresh on the post's own clock (the read's request waiting behind the read: q -4..0, served on D) costs 2
  (W - D 85 with six refreshes: 2 + 4 x 3 + 3); every other refresh 3, a refresh on d 5 costs 2 (the next boundary
  is d 2, 3 clocks on: W 84 at w1 -3/0 and w2 -4/0), one on the issue 5. Each is the hold rule (refresh_eu=hold):
  the EU runs to its next boundary after the refresh's start and waits there until the clock after the cycle's last;
  the next boundary after the post is tau 3, the first clock of the shift unit (the ALU's 3 clocks, tau 0-2, carry
  none).
* So the memory shift's write setup has the register shift's shape end-aligned to the write's issue: the D3 table of
  wp36 B1 has D3 taking on odd distances from its end in the exec and loop and on distance 2 in the exit; here the
  same distances from the write's issue, with the post's first clock and the issue added (any posted request's).
  The model's even-d rule matched the clocks only where the first refresh fell on the post and cost it 3 (the
  -2/0 rows: every middle refresh right, the last off by one, W one late).

##### A2. The read setup: every refresh between the shift's start and its read (xwin.py, prefix matched to the refresh)

The read is posted on E+5 (w0, room for the take sync's fetch) with setup 7 = grp 4 + grpcl 3, all fetch-free
(shift_cl_mem=count). The count on the request q arrives on, silicon's start and read rel E:

| w | q (count at q) | silicon R / read | model R / read | runs | e.g. |
| - | - | - | - | - | - |
| 0 | E+4 (before the post) | E+5 / E+12 | E+5 / E+15 | 4 | F18-b-n1-shlmcl-pE-w0 |
| 0 | E+5 (1, the post) | E+5 / E+12 | E+5 / E+15 | 1 | F18-b-p-n0-shlmcl-pO-w0 |
| 1 | E+5, E+6 (-, 1) | E+6 / E+13 | E+6 / E+16 | 5 | F18-b-n5-shlmcl-pE-w1 |
| 2 | E+6 (-) | E+7 / E+14 | E+7 / E+17 | 4 | F18-b-n3-shlmcl-pE-w2 |
| 0 | E+7, E+8 (3, 4) | E+9 (5) / E+14 | E+11 (7, the issue) / E+16 | 8 | F18-b-n4-shlmcl-pE-w0 |
| 1 | E+7, E+9 (2, 4) | E+10 (5) / E+15 | E+12 / E+17 | 5 | F18-b-n1-shlmcl-pE-w1 |
| 2 | E+8 (2) | E+11 (5) / E+16 | E+13 / E+18 | 4 | F18-b-n6-shlmcl-pE-w2 |
| 0/1/2 | count 5 (E+9..E+11) | on it / R+5 | = | 10 | F18-b-n4-shlmcl-pE-w1 |
| 0/1 | count 6 | count 7 (the issue) / R+5 | = | 6 | F18-b-n3-shlmcl-pE-w0 |
| 0/1 | E+3 (before the post, the EA clocks over) | E+3 / E+14 | = | 7 | F18-b-n5-shlmcl-pE-w0 |
| 2 | E+10 (1, the post) | E+10 / E+17 | E+10 / E+20 | 1 | F18-b-n0-shlmcl-pO-w2 |

Silicon takes a request while the read waits on the post's first clock (count 1), on count 5 and on the issue
(count 7): never on counts 2-4 or 6. Count 5 is the first of the grpcl clocks (the last grpcl = 3 of the setup; it
is also setup - grp_free + 1, the class's own fetch-free window, the two coincide here). The read then issues: after
a refresh on the post, one clock late (E+12 for E+11: the count runs through the refresh to 4 and the EU holds at
count 5 until the clock after the cycle's last, s + 5); after one on count 5, on the refresh's end + 1 (the count
runs 5, 6, 7 under it, the issue waits for the bus); after one before the post, the post itself held to the
refresh's end + 1 (E+14 = E+8 + 6). The model counts none of the fetch-free setup while a refresh is on the bus
(grp_free_bus) and takes a request only on the post's first clock and the issue: a refresh on the post costs the
read 4 clocks there (E+15) and one on counts 2-6 waits for the issue (E+11, read E+16). So in silicon the read's
setup has the hold shape too (boundaries post, the CL clocks' first, the issue) and a refresh cycle is not a fetch
for its fetch-free count.

##### A3. The memory shift started on a refresh's issue clock (refresh_abort=abort, the aborted request)

| w | runs | silicon after R (rel E = R) | model |
| - | - | - | - |
| 0 | 2 | R0 R13 D18 (no fetch) | R0 F5 R14 D19 |
| 1 | 7 | R0 D13 ... W, F at W + 4 (no fetch before the write) | R0 F5 R15 D20 |
| 2 | 4 | R0 R13 D18 (no fetch) | R0 F5 R14 D19 |

(F18-b-n3-shlmcl-pE-w1: R99 D112 ... R196 W201 F205.) The model retries the aborted request when the next bus cycle
ends (abort_fetch=retry), and under the refresh that cycle is the refresh: F5. Silicon fetches nothing until the
write has gone, with room for a word throughout: the request comes back at the read's end (as the 64 refresh-off
memory shifts started on an aborted cycle have it, after the read), where the posted write's setup holds fetches
(hold_fetch, 4 bytes > hold_q 3) until the write issues. The same state with a load and a store: F17-s-n3-ld-pE-w1,
F17-s-n3-st-pE-w1 (the model's F+5 before the data cycle, silicon none).

##### A4. A request raised while the take sync waits on an aborted cycle (eaq.py, prefix matched)

| class, w | q (rel the start E) | silicon R | model R | runs | e.g. |
| - | - | - | - | - | - |
| rmw (memory shift) w0 | E+1 | E+3 | E+1 | 1 | F18-b-p-n0-shlmcl-pE-w0 |
| rmw w1 | E+2 | E+3 | E+2 | 4 | F18-b-n6-shlmcl-pE-w1 |
| rmw w2 | E+1 | E+3 | E+1 | 4 | F18-b-n4-shlmcl-pE-w2 |
| store w2 | E+2 | E+3 | E+2 | 1 | F8-push-st_bw-k4-pE-w2 |
| load, rmw, store, store_imm (no aborted cycle) | E+0 .. E+3 | = | = | 34 | F17-s-n2-rmw-pE-w0 |

In every off row the form started on an aborted cycle (abort_fetch: start, ModR/M take and IR load on one clock
with room for exactly a word; the cycle E..E+2): the model's take sync waits for it and each such clock is a wait,
a micro-boundary, where the refresh is taken; silicon takes nothing until E+3. The register divide started so
(F18-b-n7-divu-pO-w1, abort_reg: its exec from the cycle's last clock E+2) takes the request on E+2: the clocks of
the aborted cycle are the EU's own (the EA clocks, or the unit's exec from E+2), not a wait. A bus-side reading (the
aborted cycle holding the bus unit against a refresh, as a real cycle) was tested and loses 12 such divide and
multiply runs (silicon R on E+2 inside the cycle): refuted.

##### A5. The 16 NOP-then-memory-shift rows the twenty-seventh fit left (refresh_take0)

reft.py, a refresh in whose window SHL [BW],CL starts after a NOP (start on E+1 of the refresh): 17 rows in the
baseline, silicon's next refresh R+10 / R+11 / R+12 at w0 / w1 / w2 against the model's R+12 / 13 / 14 in 16, the
17th (F18-b-p-n7-shlmcl-pE-w2) R+10 then the read R+15 against R+12 / R+17. They are A2's state (the request
arriving at counts 2-4 of the read's setup, taken on count 5), not the NOP's: under the final fit 16 of the 17 are
right; the 17th's next event is the read where the model fetches (A3's retry at 2 waits, open).

#### Group B: the register multiply and divide (mul.py over every register MULU/DIVU exec)

Every model refresh request from E-1 to Z+2 (E the exec's first clock, Z the next start), prefix matched to q,
under the twenty-seventh fit's rules (rexit 8/6, the exit's boundaries 6, 4, 2 before the end, the loop's odd ones
before it) and, after the A rules (refresh_abort_wait), on the final fit: 885 requests in 408 runs at every wait
setting, with and without the ES: prefix; one off (F13-u-push-mulu-k1-pO-w0: q Z, silicon at once, the model
Z+4: past the exec, the marker's PUSH). Under the baseline the aborted-start divides and multiplies at w1 (F18 B
n6, n7, ES: n4, n5: 10 runs) took a request inside the aborted cycle's clocks (A4: silicon E+2, model E+1); those
are right under the final fit. So no request inside a multiply's or divide's exec is off any more: the third
request at 1-2 waits and F17-s-n1-mulu-pE-w0's end (the brief's group B) were closed by the twenty-seventh fit
(both exact in the baseline already).

Left in the 77 inexact multiply/divide runs (final fit): before the exec 31 (the first LS under the FCh prelude,
F13 U none, F17 P, F18 A: item 8 a), in the exec window 7 (all fetch/marker events, not a refresh), after Z 43: the
closing LS's loop parity at 2 waits (F18 B / B ES: n0-n7 w2 15, BD 8, F17 S/D/C 11; B5) and the F13 U marker
after the multiply (5). No state of the multiply's own is left in them.

#### Group C

##### C1. `SHL AW,4` (C1) started on a refresh's issue clock (F18 B, B ES:)

xwin.py, FORM=shl_imm4, baseline: the 39 C1 runs in X; the largest cell, 16 runs at every wait (n3-n7 at w1/w2, ES:
n1/n2 at w0): the form starts on E with the refresh E..E+4 (a request pending at its start), silicon fetches on
E+5 (the request the count byte's take raised, beaten by the refresh), the model on E+7. The model: start and
ModR/M take on E, the cpre clocks (2, the count-byte form's clocks between the ModR/M byte and the count byte)
due on E+1, held there (the boundary test asked ahead of a clocks step treats its first clock as a hold point)
to E+5, the count byte on E+5-E+6, the fetch on E+7. Silicon took the count byte under the refresh: the cpre clocks
are not a hold point (inside a clocks step its first clock after a take is no boundary already,
refresh_clk_start=after_wait; the test ahead of the step did not apply it). The wp36 note (the exec a clock early,
as if the count byte's sync met the beaten fetch early) is this: the count byte taken 2 clocks early. Extending the
same to every clocks step after a take (the exec after the ModR/M or immediate take) loses 356 (the WP34 refutation
again: the exec's first clock after a take is a hold point, F13 S); restricted to a clocks step that lies between
two operand takes of one instruction: +18 -0. The other C1 rows: requests in the loop at w2 (E+7 -> silicon E+7,
model E+6; 4 runs) and at the closing LS (B5).

##### C2. The marker OUT after the first LS (F8 OUT, F13 C OUT, F13 U OUT; pE cells)

Three whole cells (pE, every X form, one per wait setting), the first LS ending on a refresh:

| w | runs | silicon (rel the OUT's start) | model | state |
| - | - | - | - | - |
| 0 | 19 | R0 F5 I14 | R0 F8 R16 I21 | the OUT starts with the refresh 87-91 (F8-out-empty-pE-w0): wbsync 87-88 (the shift's write-back), pre 89-91, port take 92: silicon F92 I101; the model holds the EU at the end of the wbsync wait (a micro-boundary) to 92, the pre clocks 92-94, the take and F95, I108 |
| 1 | 20 | R7 F12 F16 I20 | R5 F10 I15 | q at the port take (95): silicon's refresh at 97 (the take's I/O posted on 95 holding the fetch the take raised; the refresh two clocks on), the model's at 95 |
| 2 | 17 | R0 F5 F10 I15 | R0 F5 I11 F21 | after the beaten fetch 100-104 silicon fetches again on its delivery (105) ahead of the I/O (110); in the model the I/O's lead (104-105) holds it (the WP36 "w2 7/0" rows, F8-out-empty-pE-w2) |

w0: silicon's clocks are the refresh-off OUT's (port take at the start + 5) with the wbsync clocks running under
the refresh: the write-back sync is no hold point. With that, the cell's 19 runs first diverge at the second OUT
(silicon F109 F112 I115 against F109 I113 F116: the second OUT's I/O, moved into the slot on 104 under a refresh,
is counted 2 clocks ahead of silicon's, the same state as w2's: the run of the beaten fetch before the I/O). The
w1 and w2 cells: the I/O issues on 110 in silicon at both wait settings while the model has 105 / 106; the I/O's
count across a refresh (refresh_io=waits) and the beaten fetch's run in the lead are the open state. A prototype
letting the beaten fetch's back-to-back successor run ahead of the I/O's hold as the beaten fetch does
(refresh_after=fetch_next extended to its run): +0 -0, matched +5 (F8-out-empty-pE-w2 then diverges at the second
OUT): the w2 cell's room differs too (F13-c-out-shlcl0-pE-w2: room 1 at 104 in the model, silicon fetches at 105).
Not adopted, removed.

##### C3. `F13-r-rfm-f3-pO-w2` and the W FDh runs (the refresh length and interval)

* The brief's "RFW 0" is not this run's: F13-r-rfm-f3 runs under RFM FFh (RFW 3: 5-clock refreshes on the pins,
  silicon and model alike; RFT 3: a 128-clock interval). Its single refresh (87, q 86) is held in the second LS's
  loop; silicon's restart fetch 161, the model's 160; its pE twin (q 84, R85) is exact (restart 163). A 3-clock
  RFW 0 refresh is F13-r-rfw-0 (F0h): 3 of 6 exact, the others first diverge in the first LS (2) and at the END (1).
* The W FDh runs: F17-w-fd-n5-pE-w0 R103 R133 R164 then silicon R198 F203 F206 I212 against R196 F201 F204 I210; the
  two refreshes inside the closing LS's loop (133, 164) on the same clocks in both.
* How the model derives length and interval: types.refresh_length (3 + min(RFW, 2)) is right on the pins for every
  RFW (F13 R: F0h 3, F4h 4, F8h/FCh/FDh/FEh/FFh 5). The one difference a 3 + RFW reading would make is an RFW-3
  refresh holding the EU a clock longer than its 5 bus clocks: tested (`refresh_eu` waits 6 clocks with RFW 3):
  -1,473 refresh-on runs, because FCh, the prelude of nearly every refresh-on chain, is RFW 3 too. Refuted and
  removed. The interval (refresh_interval << RFT, the counter's bit RFT + 3) places every request of these runs
  right (all prefix-matched refreshes served on the same clocks). Nothing in the length or interval derivation
  separates FFh / FDh from FCh other than the interval itself, and the runs' refreshes are where silicon has them:
  the off clock is the EU's (a loop parity after a refresh in the loop, B5's state, at RFT 1 and 3 where the
  refresh falls on other loop clocks than at RFT 0). No rule: 1 + 3 runs.

#### D. Found on the re-read: a posted request's first clock (the marker PUSH AW, 19 runs)

xwin / eut on F13-c-push-shlcl2-pO-w0: the marker PUSH AW after the first LS starts on 129, its stack write posted
there (setup 7, the last 3 fetch-free), the request of 128 pending: silicon R129, W136; the model R133 (the first
fetch-free clock, count 5), W138. Refresh-off the write issues S+6; silicon's S+7 is the hold rule's cost: the
setup counts through the refresh (1-4 on 129-132) and the EU holds at count 5 (133, the next boundary) until 134.
Every row of the 19 (F13 C PUSH, F17 C, F13 U/N; every wait) has silicon's refresh on the PUSH's start (its post)
and the model's 4 clocks later. Where the refresh at the post beats a fetch request (F17-c-push-empty-pE-w0: R93
F98, the write at 101) there is no hold cost: the write issues as the beaten fetch lets it (the hold costs one
clock more there: W102, -2 runs when applied).

#### Addendum (written after the prototypes; scores on the refresh-on dumps (runs.py), then over all 17,822 runs)

Adopted (each an enum in sim/config.py, default the old model; tests in
`test_sim.RefreshMemoryShiftPostAndTakes`):

| rule | state | named run | gain when adopted (refresh-on, in order) |
| - | - | - | - |
| `refresh_rmw_shape=shift` | A1 | F18-b-n2-shlmcl-pE-w0 R189 W194 (even: R188 W195) | +29 -0 |
| `refresh_grpcl=step` | A2 | F18-b-n4-shlmcl-pE-w0 R110 D115 (hold: R112 D117) | +36 -0 (first try without the hold at the post: +36 -13, the post then counted under a refresh started before it) |
| `refresh_abort_retry=next` | A3 | F18-b-n3-shlmcl-pE-w1 R99 D112 (refresh: F104 R114 D119) | +11 -0 (F17 S n3 ld/st 2, F18 9) |
| `refresh_abort_wait=run` | A4 | F18-b-n4-shlmcl-pE-w2 R113 (wait: R111) | +20 -0 (memory shifts 9, MULU 5, DIVU 5, F8 1) |
| `refresh_wbsync=seam` | C2 w0 | F8-out-empty-pE-w0 F92 I101 (wait: F95 R103 I108) | +0 -0, matched +22, 19 runs first diverge later (all of the pE w0 cell) |
| `refresh_post=post` | D | F13-c-push-shlcl2-pO-w0 R129 W136 (free: R133 W138) | +13 -0 (with the hold cost on a refresh that beat a fetch: +13 -2) |
| `refresh_take_seam=seam` | C1 | F18-b-n3-shli4-pE-w1 F104 (hold: F106) | +18 -0 (every clocks step after a take: +16 -356) |

Refuted and removed: the aborted cycle holding the bus against a refresh (`refresh_abort_bus=busy`, +10 -12: the
aborted-start divides and multiplies take the refresh inside the cycle); an RFW-3 refresh holding the EU 6 clocks
(-1,473); the beaten fetch's back-to-back successor ahead of the I/O's hold (+0 -0, matched +5); the write-back
sync's following clocks step made seamless (+0 -7: the hold sits on the sync step's end, not on the step after it);
the take seam for every clocks step after a take (-356); the loop-eve window re-scanned on the final rules
(refresh_recent 17 / 19 / 20: +1 -120, +61 -120, +0 -122: as the twenty-sixth fit found).

Final (fit-wp37-hand.json = fit.json): 17,182 / 17,822 (+127 -0 over sc27v: F8 +2, F13 +9, F17 +5, F18 +111);
refresh-off unchanged (15,347 exact, every refresh-off END block exact, endchk), no model error; refresh-on END
mismatches 604 (from 731). Refresh-on runs (fdall): 1,513 exact, 232 first LS, 393 X, 4 END (1,386 / 232 / 520 / 4
before). By series (exact / first LS / X / END): F8 PUSH 13/8/3/0, F8 OUT 3/4/17/0, F13 S 86/62/38/0, F13 C
57/39/60/0, F13 U 9/9/12/0, F13 N 5/5/2/0, F13 R 27/11/3/1, F17 S 270/0/42/0, F17 D 83/0/13/0, F17 C 20/0/16/0,
F17 P 16/30/14/0, F17 W 67/0/26/3, F18 A 114/64/14/0, F18 AC 8/0/4/0, F18 B 284/0/52/0, F18 B ES: 277/0/59/0,
F18 BD 85/0/11/0, BD ES: 89/0/7/0. Of the 96 memory shifts 83 exact (0 before); of the 96 C1 runs 66 (48).

The X phase left (393, grp.py on the final fit): the closing LS's shift 150 and X's SHL AW,CL 27 (the loop's
iteration parity after a refresh held in the exec, 107 of the 150 at 2 waits: item 8 g, the hold window, B5 of
wp36 and the eve table of the twenty-sixth fit; refresh_recent re-scanned, no window separates them), the marker
OUT cells 67 (C2 w1, w2 and the second OUT), the closing LS's MOV CL 41 (X's own end: D1 / C1 / SHL AW,CL cells at
w0 and w2, a clock or two either way, no single state), F13 S pE w1 31 (item 8 a), the RFMON store 26 (item 8 e),
C1 17, multiply/divide 6, singles 28.

### The refresh side's middle, concluded: the shift's loop entry under a refresh, the marker OUT's I/O, X's exit, the SFR store's setup (twenty-ninth fit, 2026-10-22)

Written 2026-10-22 from the recorded runs and the twenty-eighth fit's model state (fit.json = fit-wp37-hand.json,
17182/17822; refresh-on F8 16/48, F13 220/462, F17 646/798, F18 953/1164; refresh-on END mismatches 604; of the
2,142 refresh-on runs fdall counts 1,513 exact, 232 first LS, 393 X, 4 END). Clocks rel t_fill unless written E+n
(E = the model's first exec clock of the shift named: the first clock of its template's `exec` step), L+n (L = the
loop's first clock: the first clock of the `loop` step; L0 = L less the hold clocks the refresh in question
caused, i.e. where the loop would start without it), s (a model refresh cycle's first clock), q (its request,
the counter's grid). "Prefix matched" through s: every event of both runs up to and including the refresh at s is
identical. "Model" is fit-wp37-hand.json unless stated. Waits w0/w1/w2.

Tools (scratchpad wp38/): runs.py, cmp.py, mk.py, show.py, fdall.py, grp.py, grpsum.py, xwin.py, eut.py (as wp37;
base.jsonl the baseline dump, fd-base.txt / grp-base.json its first divergences and X groups, identical to
wp37/fd-final.txt); ga.py (every register SHL AW,CL instance in every refresh-on run: start S, E, L, the exit X, the
next start Z, the EU's hold-stall clocks; ga-base.json) and gat.py (every model refresh served from S-1 to Z,
prefix matched through it: place, hold clocks, the previous refresh's age q - s_prev and silicon fetches since,
the next event both sides; gat-base.json); evepatch.py (diagnostic only, imported by runs.py / ga.py: EVE=always
/ never / entry overrides the eve's hold for the register shift classes in EVECLS; SFR=1 lets an SFR store's
setup count with a fetch in flight); sfrt.py (every SFR store's post, prefix matched to it: the bus there, the
write's clock, the next fetches both sides).

#### 0. The 393 X-phase runs regrouped (grp.py on the baseline; the same groups as wp37's final count)

| group | runs | waits 0/1/2 | main kinds (silicon / model, silicon - model) |
| - | - | - | - |
| the closing LS's shift `SHL AW,CL` (CL 31) | 150 | 21/22/107 | refresh/refresh -1 (65), +1 (56), -2 (13) |
| X's `SHL AW,CL` | 27 | 4/7/16 | refresh/refresh -1 (9), +1 (6), -2 (5) |
| the marker OUT 20h,AL / 21h after the first LS | 67 | 25/25/17 | refresh +2 (20, pE w1), fetch/io -1 (18), io -2 (16) |
| the closing LS's `MOV CL,31` (X's end) | 41 | 16/4/21 | fetch +1 (10), +2 (8), refresh +1 (7) |
| X's `MOV CL` in F13 S pE w1 (item 8 a) | 31 | 0/31/0 | refresh where the model fetches (+2) |
| the RFMON store | 26 | 0/8/18 | fetch +3 (23), refresh where the model fetches (+3) |
| C1 `SHL AW,4` | 17 | 6/1/10 | refresh +1 (8), -1 (6) |
| singles (loads, stores, OUT imm, NOP, MULU, the marker PUSH, first-LS blocks, one memory shift) | 34 | | |

#### Group A: the shift's loop entry under a refresh (item 8 g; 177 runs)

##### A1. Every model refresh served inside a register `SHL AW,CL` exec, prefix matched through it (ga.py / gat.py)

The exec runs E..L-1 (6 clocks, more after a unit_hold wait); its refresh boundaries (refresh_exec=every2_recent)
are every second clock counted back from the loop, L-6 and L-4, and the eve L-2 only as a hold point within
`refresh_recent` of the previous refresh (refresh_eve=hold: never an acceptance point). So a refresh starts in the
exec only on L0-6 or L0-4. Silicon's cost (the loop's start moved, read off the next event: whichever of the
baseline's hold and the A2 alternative gives silicon's next event; "both" = the next event does not separate them)
by the refresh's place, by series group (LS1 = the first LS, X/LS2 = X's shift and the closing LS) and waits:

| place | w | refreshes (prefix matched) | baseline's hold clocks: right / wrong | silicon's hold clocks | e.g. |
| - | - | - | - | - | - |
| L0-6 (E+0) | 0/1/2 | X/LS2 159 / 165 / 170, LS1 93 / 195 / 216 | 3 at every w: all right (both) | 3 | F8-push-ld_bw-k4-pO-w0 |
| L0-4 (E+2), X/LS2 | 0 | 78 | 1: 60 right (both); 0 (age 31, 32, none): 12 wrong; 3 (age 13): 5 (both); RFW 0: 1 wrong | 1 (0 with the 3-clock RFW 0 refresh) | F17-d-n3-shlcl31-pE-w0 |
| L0-4, X/LS2 | 1 | 86 | 1: 53 right (both); 0 (age 31, 32, none): 26 wrong; 3: 7 (both) | 1 | F17-d-n2-shlcl16-pE-w1 |
| L0-4, X/LS2 | 2 | 111 | 0 (every age 14-32, none): 110 wrong, 1 (RFW 1, 4-clock) right | 1 (0 for the 4-clock refresh) | F13-s-shlcl4-pE-w2 |
| L0-4, LS1 | 0/1/2 | 20 / 10 / 5 | 1: 4 right; 0: 16 / 8 / 5 wrong | 1 | F18-a-push-fc-empty-pO-w0 |

Every refresh that starts on the exec's boundary 4 before the loop (L0-4) holds the EU for one clock in silicon,
at every wait setting, after any previous refresh (age 13 to 64 clocks, or none since RFEN), in X's shift, the
closing LS and the first LS alike; a 4-clock (RFW 1) or 3-clock (RFW 0) refresh there holds nothing. That is the
hold rule (refresh_eu=hold: the EU runs to its next boundary after the cycle's start and waits there until the
clock after the cycle's last) with the loop's first clock L as that boundary: the cycle s..s+4 = L-4..L ends on
L, so the loop starts on L+1. A refresh on L-6 meets the boundary L-4 first and holds there to L-1: 3 clocks, as
the baseline has it.

The baseline has no boundary at L (the exec runs into the loop on a seam) and a hold at the eve L-2 gated by the
window: within it the eve stalls one clock and then, the eve test being asked again on the next clock against
t - s_prev, the window lapses (a 1-clock hold by accident of the window's arithmetic: w0 ages 15, 16, w1 ages
14, 15, exactly the ages where t - s_prev = refresh_recent less the waits at the eve); at smaller ages the eve
holds the whole cycle (3, F18-b-p-n1-shlcl4-pE-w0 age 13), at larger ages or with no previous refresh nothing
(0). At 2 waits the window (16) is shorter than every age the corpus has at L-4 (t - s_prev = age + 3 >= 17), so
none of the 111 holds. That is the "wait dependence" of `refresh_recent` (item 8 g): the window was standing in
for a fixed 1-clock hold, and its best value moved with the waits because the request grid sits at different
ages from the exec at each wait setting. No window, no exec-clock count, no bus history in cycles and no
first-or-later distinction is needed: silicon's hold is the same in every row.

##### A2. The loop and the exit: the iteration parity (gat.py, the same runs)

Every model refresh served in a count loop (X/LS2: 7,374 prefix-matched; LS1 3,318), by waits: the request
waits 0 or 1 clock for the next iteration start (s - q 0: 2,367, 1: 3,734; 2-3: 273 where the bus was busy),
and the hold costs the loop length - 2 (3 clocks in 7,156 rows; 2 in 212: the 4-clock RFW 1 refresh and holds
that cross into the exit; 1 in 6). The next event is silicon's in 7,361 of 7,374 (X/LS2): the loop loses
length - 2 per refresh wherever it lands, a refresh on an odd or even iteration costing the same; the 13 off are
at the loop's last iterations (A4). The exit (tail, 3 clocks): a refresh on its boundary X+1 costs 3, after Z
none; 774 of 777 right. So the parity the closing LS shows (the next refresh +-1, the shift's end +-1) is not the
loop's: it is the exec's last refresh shifting the loop's start by 0 or 3 where silicon has 1. With the loop's
first clock a hold point and the eve none (diagnostic EVE=entry for `SHL AW,CL`): +180 -0 refresh-on runs,
matched events 39,428 -> 41,316, 189 runs diverging later, none earlier; for both register shift classes
(EVECLS=shift_cl,shift_imm: C1 `SHL AW,4` and D1 `SHL AW,1` have the same split): +201 -0, matched 41,591.

##### A3. The alternatives the brief listed, read against A1

* "Always hold at the eve" (EVE=always; the eve the whole cycle's hold point): +0 -115 (F13 14, F17 36, F18 65),
  matched 39,428 -> 39,087: the L0-4 refreshes then cost 3, where silicon has 1.
* "Never hold at the eve" (EVE=never, nothing at the loop's entry): +1 -120: 0 where silicon has 1.
* The window counted in exec clocks already run, in bus cycles since the previous refresh, or by first/later refresh
  in the unit: in A1 every L0-4 row costs 1 whatever those are (exec clocks run at s: always 2; previous refresh
  13-64 clocks back or none; first refresh in the unit in every row at L0-4, since none fits before it), so none of
  them separates anything; the window's apparent dependence was the accident described in A1.

##### A4. What A2's rule leaves in the shift (gat.py under EVE=entry, both classes)

25 prefix-matched shift refreshes still off: 11 at 2 waits where a refresh on E+0 is followed by a model fetch at
s+5 and silicon's next refresh at s+15 (F17 S n1/n2 RMW, F17 C PUSH, F18 A PUSH st, F18 B memory shift: the queue
after the closing LS's exec refresh, not the hold); 7 at the loop's last iterations in the PUSH/OUT pO w1 cells
(F13-c-push-shlcl2-pO-w1: q L+57, the next refresh 17 / 18); 4 in the W FDh RFT-1 cells (32-clock interval); 3
near the exit (L+72, model fetch where silicon refreshes).

#### Group C: the closing LS's MOV CL, X's exit (41 runs)

With A2's rule (diagnostic) 33 of the 41 are exact (fd-entry2.txt): X's own end (D1, C1, `SHL AW,CL` n1/n2 at w0
and w2) was X's exec refresh holding 0 or 3 clocks where silicon holds 1, moving X's end and the MOV CL's take
by +-1 or +-2. The 8 left are tabulated in the addendum on the final configuration.

#### Group B: the marker OUT after the first LS (67 runs; baseline, prefix matched to the first event shown)

The marker is `OUT 20h,AL ; X ; OUT 21h,AL` after the first LS (CL 31). Events from 84 on, silicon / model, by
waits and parity (every X form of the cell has the same rows):

| w, parity | runs | silicon | model |
| - | - | - | - |
| w0 pE, X empty (the second OUT next) | 1 | R87 F92 I101 R104 F109 F112 I115 | R87 F92 I101 R104 F109 I113 F116 |
| w0 pE, X a form | 15 | R87 F92 I99 F102 R105 F110 | R87 F92 I101 R104 F109 F112 |
| w0 pE, X = 4 NOPs | 1 | R87 F92 I99 R103 F108 F112 | R87 F92 I101 R105 F110 F114 |
| w0 pO | 8 | the first divergence after the second OUT (R112/R113) | |
| w1 pE | 19 | R97 F102 F106 I110 R113 | R95 F100 I105 F108 R112 |
| w1 pO, X empty | 1 | R95 F102 I106 R112 F117 I121 | R95 F102 I110 R113 F120 I124 |
| w2 pE | 17 | R95 F100 F105 I110 R113 | R95 F100 I106 F109 R114 |

The OUT starts at 87 (w0) / 90 (w1, w2) in the model, the refresh-off port take at the start + 5 and the I/O
(refresh-off F3-out-shl_cl0-k1-pE: start 72, I/O 84 / 85 / 86) at the start + 12 + w; with the second OUT
straight after, at the start + 14 + w (F3-out-empty-pE: 86 / 87 / 88). Refresh-on, silicon's first I/O is at
the refresh-off clock at w0 (87 + 12 = 99, 87 + 14 = 101: the refresh 87-91 under the wbsync and pre clocks costs
the I/O nothing; the model, not counting its two wait states, has 101 for the 15 X-form runs) and at 110 at w1
and w2 (90 + 13 + 7, 90 + 14 + 6). The PUSH-marker twins (F8 PUSH, F13 C PUSH pE w1/w2, exact) put the first LS's
end, and so the OUT's start, on the same clock at w1 and w2 in silicon too. At w2 silicon runs the refresh on the
port take (95) as the model does, then the beaten fetch (100) and a second fetch back to back (105) ahead of the
I/O (110); at w1 it runs no cycle on 95 or 96 and the refresh on 97, then the two fetches (102, 106) and the I/O
(110). No state the model has before 95 differs between w1 and w2 (no bus cycle from 85 to 94 at either; the
EU rows are identical): the record does not show why the refresh waits two clocks at w1. Facts only here; see
the addendum.

#### Group D: the SFR store's setup (the RFMON store at 1-2 waits; the W ECh refresh-off twins)

sfrt.py: every RFMON store (`ES: MOV byte [0FFE1h],imm8`, sfr_cycle=io: a 3-clock on-chip write at the I/O block's
waits) prefix matched to its post P, by the bus from P-1 on, the model's write clock, the next two fetches or
refreshes rel P:

| w | bus P-1..P+4 | model write | silicon / model next | rows | e.g. |
| - | - | - | - | - | - |
| 0 | B1 B2 B3 B1 B2 B3 (a fetch, one back to back) | P+2 | = (13 patterns) | 237 | F17-w-ec-n0-pO-w0 |
| 0 | B1 B2 B3 B1 B2 W | P+7 | = | 10 | F17-p-n0-empty-pO-w0 |
| 1 | B1 B2 W B3 B1 B2 (the write due after the fetch) | P+3 | = (16 patterns) | 233 | F17-w-ec-n0-pO-w1 |
| 1 | B1 B2 W B3 B1 B2, a fetch committed back to back on the fetch's last clock | P+7 | F+6 F+10 / F+3 F+13 | 12 | F17-w-ec-n2-pE-w1 |
| 2 | B1 B2 W W B3 B1 | P+4 | = | 239 | F17-w-ec-n0-pO-w2 |
| 2 | the same, a fetch committed back to back | P+9 | F+7 F+12 / F+4 F+15 | 12 | F17-w-ec-n2-pE-w2 |
| 2 | W B3 B1 B2 W W (the post inside a fetch, P series) | P+11 | F+1 F+9 / F+1 F+6 | 10 | F17-p-n0-empty-pE-w2 |

The store's setup is 2 clocks with a fetch-free part (store_imm's setup_free): with a fetch in flight from the
post on, the model counts the second setup clock only on the fetch's delivery clock or after, so the write is due
on the clock after the fetch's last; at 1-2 waits, when the queue then commits a fetch back to back on that last
clock, the fetch goes first and the write follows it (P+7, P+9). Silicon has the write right after the first
fetch in every row (its next fetch 3 clocks after the write's 3 clocks), back to back request or not, and in the
P w2 rows too. Read as: the on-chip write's setup counts through a fetch in flight (it does not need the bus free
of fetches: it never reaches the pins), so it is due on the fetch's last clock and beats the back-to-back fetch
as any issuable data request does (arbiter=settled/b2b). At w0 the fetch is 3 clocks and the write is due on
its delivery either way (no row changes). Diagnostic SFR=1 (free_need 0 for the SFR write): +20 -0 refresh-on
(F17 W FC/FD and P), and the 8 refresh-off W ECh runs of F8/F13/F17/F18's dumps that missed are exact (330/330
refresh-off there), no run diverging earlier; the two F17 S `out` singles (F17-s-n0-out-pE-w0, -n1-out-pE-w1:
the next refresh a clock off after the store) are not this state.

#### Addendum (written after the simulator changes; scores on the refresh dumps of F8, F13, F17, F18 (runs.py, 2,472 runs, the F17 refresh-off W/E cells included), then over all 17,822 runs)

##### Adopted (each an enum in sim/config.py, default the old model; tests in `test_sim.RefreshLoopEntrySfrSetupIoPreAndUnitDrop`)

| rule | state | named run | gain when adopted (in order) |
| - | - | - | - |
| `refresh_loop_hold=entry` | A1 / A2: the eve no micro-boundary, the loop's first clock (the exec->loop seam) the hold point | F13-s-shlcl4-pE-w2 R159 R176 R191 R208 R224 F233 (eve: R160 R175 R192 R207 R223 F232) | +201 -0 (F13 12, F17 54, F18 135; matched 39,428 -> 41,591, 210 later, 0 earlier); `SHL AW,CL` alone +180 |
| `sfr_setup=count` | D | F17-w-ec-n2-pE-w1 (refresh off) F92 F96 F100 (fetch_free: F89 F99 F103) | +21 -0 (F17; 8 of them the refresh-off W ECh twins) |
| `refresh_io_pre=count` | B, w0 (below) | F13-c-out-shlcl2-pE-w0 I99 F102 R105 F110 (waits: I101 R104 F109 F112) | +3 -0 (matched +181, 18 later) |
| `refresh_drop_unit=unit` | A4's w2 rows (below) | F17-s-n1-rmw-pE-w2: no fetch from the exec's refresh (129) to the shift's end, F218 (odd: F134) | +9 -0 (matched +201, 19 later) |

Over all 17,822 runs (sc29-all.txt): 17,416 (+234 -0 over sc28v: F8 +1, F13 +16, F17 +81, F18 +136); the
refresh-off families unchanged (every refresh-off END block exact, endchk), the 8 F17 W ECh refresh-off misses
of 1-2 waits exact; refresh-on END mismatches 604 -> 399; no model error. Refresh-on runs (fdall over the 2,142):
1,739 exact, 208 first LS, 177 X, 18 END (1,513 / 232 / 393 / 4 before; the 14 new END rows are W FDh, F17 P/C/S
and F18 B memory-shift runs at w1/w2 that now reach the END block: the MOV DW take's back-to-back fetch, F-10 in
the model where silicon refreshes at F-6, after a request lost in the closing LS's exec; open).

##### B, after the rules: the marker OUT (63 runs left)

* w0 pE, X a form (15 runs): the first I/O at 99 (refresh-off start + 12) is the refresh 87-91's two wait states
  counted: the refresh began on the OUT's start, under its write-back sync (87-88), before its setup count began
  (89). An OUT started on a refresh's first clock with no write-back sync (F17-s-n3-out-pE-w1, R99, I113 in both)
  does not count them. Counting every refresh wait state before the post: +1 -9 (the F17 S `out` and F13 C OUT
  pO rows); only those of a refresh started before the count began (`refresh_io_pre=count`): +3 -0. The cell then
  first diverges at the second OUT.
* pE at every wait (w0's second OUT, w1 and w2's first OUT; 45 runs): the refresh taken on the port take (the
  I/O's post, room 3 after the IR load) beats the fetch; silicon runs the beaten fetch and a second fetch back to
  back before the I/O (w0 R136 F141 F144 I147 against the model's F141 I145; w2 R95 F100 F105 I110 against F100
  I106), the I/O a clock or two later than the model's. The model's queue has room for only one word after the
  beaten fetch, and the next instruction (MOV CL, interlocked behind the waiting OUT until its issue; or the
  second OUT, held by start_sync while the fetch is on the bus) does not start before the I/O issues, so nothing
  raises the second fetch. Refuted: a refresh's wait states counted everywhere (+0 -464), counted when the refresh
  starts on the I/O's post clock (+0 -18: the pO rows), the early fetch run (refresh_sync=run) for a fetch beaten
  on an I/O's post (+0 -1). No state the model carries gives the second fetch's room: open.
* w1 pE (19 runs): silicon runs nothing on 95 or 96 and the refresh on 97 where w2 runs it on 95, with every
  model state before 95 the same at both wait settings (and the PUSH-marker twins putting the first LS's end on
  the same clock): open.

##### C, after the rules: X's exit (8 of the 41 left)

33 of the 41 are exact (X's own exec refresh had moved its end by 0 or 3 where silicon has 1); 12 X-phase runs
first diverge at the closing LS's MOV CL now (8 of the 41; the other 4 came from the marker OUT and RFMON groups). Left: 3 F13 C/U OUT pE w0 and
2 F17 S `out` w2 (the I/O one clock later in silicon: B's state), 6 F18 B `SHL AW,1` at w0 started on a refresh's
first clock (silicon F107 R110 against the model's R109 F114: the next instruction's start 2 clocks earlier in
silicon after the D1 shift held from its first clock), 1 F17 P. No single state.

##### A, after the rules: what is left in the shift (24 closing-LS, 13 X shifts, 11 C1)

* The eve after a unit_hold wait (uhe2.py; every acceptance test on an eve with a request pending, prefix
  matched): with a 1-clock unit_hold wait in the exec (w0, the fetch's last clock) silicon takes the pending
  request on the eve (13 rows: F8-push-empty-pO-w0, F13 C PUSH pO w0, F18 B memory-shift LS w0); after a 2- or
  3-clock wait (w1, w2) it waits for the loop's first clock (16 rows: F13 C PUSH pE w2, F18-ac-out-fc-pO-w1);
  with no unit_hold wait it waits in 322 of 324 (2 W FC pO w1 rows take). The eve taking a pending request after
  any unit_hold wait: +13 -16. The only separating quantity is the stall's length (the fetch's wait states + 1),
  i.e. the wait setting: no rule adopted.
* A request on a word's delivery clock at even room inside a register unit's clocks (bt.py): every one at 1-2
  waits in a shift's exec or a multiply's loop is lost in silicon (no fetch after the refresh; 13 + 5 rows), as
  the odd-room ones are: `refresh_drop_unit` above. Lost in the shift's exec it comes back at the next start
  (the closing LS's end: F17-s-n1-rmw-pE-w2 F218), not at the loop's exit (reraise_off 1: -3, 2: -312).
* The PUSH/OUT pO w1 loop ends (6: the last refresh 239 / 240), the W FDh RFT-1 cells (4), the w2 NOP train
  before the closing LS (F13-n-none-nop8-pE-w2: MOV CL started on a refresh's first clock, its fetch 136 against
  the model's 134; 8 rows), C1 at w2 (requests at E+6 served at E+7 / E+6): small cells, not separated.

##### D, after the rule

Of the 26 RFMON-store runs of the X phase 13 are exact and 13 diverge later, past the store (5 in the END block,
8 in the X phase: the closing LS's or X's shift, F17 P MULU at w2); the 2 F17 S `out` singles are B's state.

##### The 393 X-phase runs of the baseline, by group, on the final configuration (fd-p6.txt)

| group | runs | exact / X / END |
| - | - | - |
| the closing LS's shift | 150 | 119 / 21 / 10 |
| X's `SHL AW,CL` | 27 | 16 / 11 / 0 |
| the marker OUT | 67 | 2 / 65 / 0 |
| the closing LS's MOV CL (X's end) | 41 | 33 / 8 / 0 |
| the RFMON store | 26 | 13 / 8 / 5 |
| C1 `SHL AW,4` | 17 | 6 / 11 / 0 |
| X's MOV CL in F13 S pE w1 (item 8 a) | 31 | 0 / 31 / 0 |
| singles | 34 | 12 / 22 / 0 |

##### Flip-backs, stage 8, knob dependence (final configuration fit-wp38-hand.json = fit.json)

Each adopted enum flipped back alone on the final hand fit (wp38/fl-<key>=<old>.json, scored over all 17,822
runs against sc29-all.txt; END mismatches from 399): `refresh_loop_hold=eve` -202 (584), `sfr_setup=fetch_free`
-21 (409), `refresh_io_pre=waits` -3 (402), `refresh_drop_unit=odd` -9 (408); none gains a run, no model error.
Stage 8 from the wrapped hand fit (wp38/hand-wrap.json): no move (chosen {}), exact 2,069 / 2,472, guard
15,347 / 15,350; the alternatives at the hand fit: refresh_loop_hold=eve 1,867, sfr_setup=fetch_free 2,048,
refresh_io_pre=waits 2,066, refresh_drop_unit=odd 2,060; ties: refresh_exec every2 and every2_early (2,069,
45,505 matched: the eve is no longer read, so the window's variants are one model), wlatch_ir_at=start, and
refresh_timer start/end. knob_dependence (F8 F13 F17 F18; REFRESH_HOLD_INTS + mul.rexit, div.rexit): no
integer's best value differs by parity, waits, k, marker, family or n (refresh_recent, 18 / 18 / 19 by waits
and 16 under PUSH before, is not read under refresh_loop_hold=entry).

### The refresh side's remainder: the marker OUT's beaten fetch, the register shifts, the END's MOV DW take, the eve after a unit hold, the small cells, and the first LS's offsets per prelude cell (thirtieth fit, 2026-10-22)

Written 2026-10-22 from the recorded runs and the twenty-ninth fit's model state (fit.json = fit-wp38-hand.json,
17416/17822; refresh-on F8 17/48, F13 236/462, F17 727/798, F18 1089/1164; refresh-on END mismatches 399; of the
2,142 refresh-on runs fdall counts 1,739 exact, 208 first LS, 177 X, 18 END = wp38/fd-p6.txt, reproduced as
wp39/fd-base.txt). Clocks rel t_fill unless written H+n (H = the model's HALT start), S+n (the instruction's start),
E+n (the first exec clock), L+n (the loop's first clock), X+n (the exit's first clock), s (a refresh cycle's first
clock), q (its request). "Prefix matched" through an event: every event of both runs up to and including it is
identical. "Model" is fit-wp38-hand.json unless stated. Waits w0/w1/w2; pE/pO the parity.

Tools (scratchpad wp39/): runs.py, cmp.py, fdall.py, grp.py (now X and END), show.py, mk.py as wp38 (runs.py: PROTO=
module list imports diagnostic patches); cmp2.py (cmp.py counting model errors as misses, GAIN rows with a 3rd arg);
grp2.py (the regroup below); ga.py (group A events by cell); twins.py (refresh-off runs with the same codes, parity
and waits); lsdiag.py (diagnostic only: the first LS's exec moved by SHIFT clocks in every FCh non-marker run of one
(wait, parity) cell, via eu.ls_shift); beat.py / bfr.py (every model refresh that beats a raised fetch request /
every beaten fetch, prefix matched: EU and queue state, whether each side runs a second fetch back to back);
qtrace.py (the queue's request state per clock); bsh.py (group B: the shift's S, E, L, X, Z and the refreshes);
uhe2.py (wp38's eve table with the last fetch's clocks); lostt.py (every request lost to a refresh, its return);
tdl.py (every fetch issued on a take + IR-load delivery clock); sons.py (every instruction started on a refresh's
first clock); rplace.py (refreshes inside one class by step); offg.py (every refresh-off run of the corpus, exact
and first divergence, against a baseline: the refresh-off guard, 15,680 runs, 15,677 exact on the baseline).

#### 0. The 195 runs regrouped by the instruction at the first divergence (grp2.py on the baseline)

| group | runs | cells (parity, waits) | kinds (silicon / model, silicon - model) |
| - | - | - | - |
| the marker OUT 20h,AL / 21h after the first LS | 63 | pE w0 13, pE w1 19, pE w2 17, pO w0 8, pO w1 6 | refresh +2 (22), fetch/io -1 (21), refresh +1 (8) |
| X's MOV CL in F13 S pE w1 (item 8 a) | 31 | pE w1 31 | refresh where the model fetches (+2) |
| the closing LS's shift `SHL AW,CL` | 24 | w0 10, w1 8, w2 6 | refresh -2 (11), -1 (6), fetch +2 (4) |
| the END block (`MOV DW` / OUT DW) | 18 | w0 2, w1 5, w2 11 | refresh where the model fetches +4/+5 (11) |
| X's `SHL AW,CL` | 13 | w0 4, w1 2, w2 7 | refresh -2 (4), fetch +2 (4) |
| the closing LS's `MOV CL,31` | 12 | w0 9, w2 3 | io +1 (5), fetch/refresh -2 (4) |
| C1 `SHL AW,4` | 11 | w0 4, w1 1, w2 6 | refresh +1 (8) |
| singles (loads 5, OUT imm 4, stores 3, MULU 3, NOP 2, first-LS-ish 4, PUSH 1, memory shift 1) | 23 | | |

#### Group A: the marker OUT after the first LS (63 runs)

##### A1. Every beaten fetch, prefix matched (bfr.py): the second fetch back to back

A fetch a refresh beat (refresh_after=fetch_next: it runs on the clock after the refresh), prefix matched through its
issue; at its last clock: does the EU run an IN or OUT whose I/O cycle has not issued (posted or still to post), the
room the request rule counts (the in-flight word counted); does each side run a second fetch back to back:

| EU at the beaten fetch's last clock | w | room 0 / 1 | room 2 / 3 | silicon second fetch | model second fetch |
| - | - | - | - | - | - |
| an IN/OUT waiting for its I/O | 0 | 5 / 4 | 76 / 75 | 160 of 160 | 152 (none at room 0 / 1 but F17-s-n3-out-pE-w0) |
| an IN/OUT waiting for its I/O | 1 | 4 / 0 | 84 / 88 | 176 of 176 | 172 (none at room 0) |
| an IN/OUT waiting for its I/O | 2 | 0 / 19 | 57 / 65 | 141 of 141 | 122 (none at room 1) |
| any other class (shift, multiply, divide, MOV imm, NOP, load, store, RMW, HALT) | 0-2 | 600 | 960 | as the model's in 1,558 of 1,560 | the request rule's decision |

e.g. F13-c-out-shlcl2-pE-w2: the marker OUT starts at 90, takes its port byte and posts its I/O at 95 with 3 bytes
stored (the IR loaded with MOV CL's opcode), the refresh 95-99 beats the fetch the take raised; silicon R95 F100 F105
I110 R113, the model R95 F100 I106 F109 R114. F13-c-out-shlcl2-pO-w0: the refresh 128-132 at the end of X's shift
beats a fetch (room 2), the second OUT starts at 133 on that fetch's issue; silicon F133 F136 I143, the model F133
F143. At room 0-1 the queue model has no room for the second word when the bus unit commits to it; the word lands
with the I/O's issue (the next instruction, interlocked behind the I/O, starts and takes there) or the port take,
its second byte in the latch when the queue is still full on delivery. Not the room, the IR load, the port byte or
the I/O count: the room-3 starts of a multiply, divide or `SHL AW,imm` (q 3, take and IR load on s, no posted I/O;
28 rows) have no second fetch in silicon, and the refresh-off twins (F3-out-shl_cl2-k1-pE-w2: the same queue at the
port take, the fetch issued there directly) have none either: only a fetch a refresh beat while an I/O waits does.
The I/O then follows that second fetch (w0 second OUT R136 F141 F144 I147, w2 first OUT I110 = 95 + 15): its count
is the model's, the second fetch (committed back to back, io_hold=posted_b2b) is what delays it.

##### A2. pE w1 (19 runs) is item 8 a (lsdiag.py)

At pE w1 silicon runs nothing on 95-96 and refreshes on 97 where pE w2 refreshes on 95. The refresh request is not
later at w1: the counter's request is at 95 at both (model grid 79, 95, 111 at w1 and w2), and silicon's F13 S pE w1
runs serve it at 95 (R95 F100 F104 where the model has F93 R97 F102), the PUSH twins at 96 at both waits (R96 S101,
exact; a PUSH started 0 or 2 clocks later gives the same events: its write setup's first fetch-free clock or the
write's issue takes the refresh either way). The EU is later: the first LS's exec runs 1-2 clocks later in silicon
in that cell. Diagnostic (the first LS's exec moved in every FCh non-marker run of the cell; F8, F13, F17 P), exact
before -> after, no run diverging earlier:

| cell | exec moved | F13 S | F13 C | F13 U | F13 N/R | F17 P | F8 OUT / PUSH | all |
| - | - | - | - | - | - | - | - | - |
| pE w1 | +1 or +2 | 0 -> 31 | 12 -> 12 (13 later) | 2 -> 3 | 1 -> 3 | 0 -> 2 (10 later) | 0 -> 0 (4 later) / 4 -> 4 | 19 -> 55 |
| pE w0 | -2 | 0 -> 31 | 2 -> 14 | 0 -> 3 | 0 -> 3 | 0 -> 7 | 1 -> 1 / 0 -> 3 | 3 -> 62 |
| pO w2 | -2 | 0 -> 31 | 0 -> 9 | 0 -> 3 | 0 -> 3 | 0 -> 10 | 0 -> 0 / 0 -> 3 | 0 -> 59 |
| pO w0, pO w1, pE w2 | -2..+2 | | | | | | | none better than 0 |

With the move and A1's rule the OUT pE w1 cell behaves as pE w2 (F8 OUT 0 -> 3, F13 C 12 -> 15). The offset is one
constant per (prelude, wait, parity) cell: the prelude's phase (item 8 a), not a state the aligned record shows; a
per-cell offset is the per-cell alignment the rules forbid. Not adopted; reported.

##### A3. What A1's rule leaves (49 of the 63 in X, 7 exact, 7 later in X)

pE w1 19 (A2); the pO w0/w1 second OUT 8 (after the second fetch the I/O 1-2 clocks off: silicon I143 against the
model's R145 I150 at pO w0, the OUT started on the beaten fetch's issue 133, the I/O at start + 10); the second OUT
after X at pE w0/w2 started on a refresh's first clock after X's shift (R s, silicon F s+8, the model F s+10: 9 rows,
F13-c-out-shlcl5-pE-w2 R143 F151); F8-out-empty-pE-w2 (the second OUT's port take on the first I/O's issue clock:
port_latch relatch holds that I/O to 116, silicon I110). No single state.

#### Group B: the register shifts' remainder (48 runs; bsh.py)

| cluster | runs | w | place (model) | silicon / model | state |
| - | - | - | - | - | - |
| eve after a 1-clock unit_hold stall | 13 | 0 | the loop's eve L-2, q L-3/L-2 | R L-2 / R L+0 | D (below): 10 closing LS (F8-push-empty-pO-w0, F13 C PUSH pO, F17 C PUSH-MULU pO, F18 B memory-shift LS), 3 X (F17-c-push-shlcl4/16/31-pE-w0) |
| eve with no stall | 2 | 1 | L-2 | R L-2 / R L+0 | F17-w-fc-n3/n7-pO-w1 (the 2 of 324 the twenty-sixth fit noted) |
| the loop's exit | 7 | 1 | X+1 (q X-1 / X) | R X / R X+1 | PUSH/OUT pO w1 (F13 C/U, F17 C PUSH: last refresh 239 / 240) and F17-w-fd-n7-pE-w1 (RFT 1) |
| MOV CL started on a refresh's first clock, 6 stored + 1 latched | 8 | 2 | the SHL's start S | F S+2 / F S+0 | E (below): adopted |
| C1, a request on E+1 | 5 | 1, 2 | E+1 | R E+2 / R E+1 | F18-b-n3/n4-shli4-w2, F18-b-p-n1/n2-shli4-w2, F18-b-p-n7-shli4-pE-w1; requests on E-k or E, served on E, are right (22 rows); the shift's end then 3 clocks earlier in silicon (F133 / F136): the refresh on E+2 costs nothing |
| C1 other | 6 | 0, 2 | L+6 (3), X+3 (2), S+8 (1) | +1, +3, refresh/fetch | no common state |
| `SHL AW,CL` with CL 0 | 4 | 0-2 | the exec's head | F / R | F13 C OUT/PUSH shlcl0 |
| singles | 3 | 2 | L+70, L+0, X+2 | +1, +2 | F17 P n0 (2), F17-w-fd-n5-pE-w2 |

The C1 E+1 cell: the model takes the request at E+1 only because the bus would start the take's fetch there
(boundary_bus); E+1 is the 3-clock exec's eve (no micro-boundary under refresh_loop_hold=entry); silicon serves at
E+2 = L-1 and holds nothing (the shift and the next start 3 clocks earlier than the model's). 5 rows, two cells; no
rule tried.

#### Group C: the END block (18 runs)

| cluster | runs | w | silicon / model (rel H) | state |
| - | - | - | - | - |
| lost request's return, then the take's fetch | 8 | 2 (7), 1 (1) | F-15 R-6 F-1 F+4 / F-15 F-10 R-5 F+2 | a request lost to a refresh in the closing LS's exec (refresh_drop_unit=unit, at E+5..E+8 of the exec) returns at the END's MOV DW start H-15 (refresh_lost=start): silicon fetches there too (F-15 in every row); the MOV DW's last immediate byte is taken on that fetch's delivery H-10 with room 2 and the second byte latched, and the model fetches there; silicon has no fetch, serves the request of H-9 at H-6 and fetches at H-1 and H+4 |
| the take's fetch, no lost request | 4 | 2 | R-5 F+0 / F-10 R-5 F+0 or F+2 | F17-w-fc-n2-pE/pO-w2, -n5-pE-w2, F17-p-n1-shlcl8-pE-w2: the same take state at H-10 (room 2, latched), request at H-6; silicon fetches the word at H+0, after the refresh |
| W FDh, RFT 1 | 5 | 0, 1 | R-7 / R-9 (w0), R-13 / R-11 (w1) | the 32-clock interval at the RFT switch |
| F17-s-n3-rmw-pE-w1 | 1 | 1 | R-3 F+2 F+6 / F-8 F-4 R+0 | |

tdl.py: every fetch the model issues on a delivery clock where the EU takes its last operand byte and the IR loads
(no start), prefix matched through the clock before: refresh off 14,040 rows, every one right; refresh on 623 rows,
right but 7 (the 6 imm rows of the two END clusters above and F17-p-n1-shlcl31-pE-w2). The same logged
state (imm, w2, room 2, latched 1) is right in 8 rows (F13-r-rfw-0-pO-w2 q H-2, F17-w-fc-n3-pO-w2 and -n6-pE-w2 q
H-8) and wrong in 6 (q H-9 or H-6): neither the refresh request's clock nor the lost request's return separates them
(the n2/n3 pair has none lost). The END block's other history differs in the closing LS's exit (n2: the last
refresh served a clock late in its exit, the MOV DW starting 2 clocks after it; n3: 5): consistent with silicon's
closing LS ending later in the wrong rows, not shown. No rule.

#### Group D: the eve after a unit_hold wait (uhe2.py on the baseline; prefix matched, a request pending at the eve)

| w | unit_hold stall clocks (rel E) | eve | q rel eve | the fetch (rel eve) | previous refresh (rel eve) | silicon / model | rows |
| - | - | - | - | - | - | - | - |
| 0 | E+2 (1 clock: the fetch's B3) | E+5 | -1 (10), 0 (3) | -5..-3 (B1 B2 B3) | -16 | eve / L | 13 |
| 1 | E+2, E+3 (W, B3) | E+6 | 0 | -6..-3 | -15 | L / L | 1 |
| 2 | E+2..E+4 (W, W, B3) | E+7 | -1 | -7..-3 | -17 | L / L | 15 |

The stall in kind: at 0 waits the exec's boundary E+2 meets the fetch on its last clock (B3) and waits that one clock
(no wait state); at 1-2 waits it meets a wait state and waits through the wait states and B3. In every row the fetch
ends 3 clocks before the eve and the request comes 1 clock or 0 before it; the only difference is whether the stall
held a fetch wait state, i.e. the wait setting (the corpus has no 1-clock stall at 1-2 waits with a request at the
eve, and no stall at 0 waits on a wait state). No rule.

#### Group E: small cells

* The w2 NOP train before the closing LS (8 runs: F13-n-none-nop8-pE-w2, F17-s-n0/n1-nop8, F18-a-out-fc-nop8-pE-w2,
  F18-b-p-n6/n7-shlcl4/16): sons.py, every instruction the model starts on a refresh cycle's first clock, prefix
  matched (3,301): the next event is silicon's in 3,286; the 8 are the only starts with 6 bytes stored and one
  latched (a word delivered on s into a full queue): MOV CL,31 starts on s=129, takes its immediate at 132 under the
  refresh, SHL AW,CL starts at 134 (F134); silicon F136. The other 7 are four other states (CL 0 shifts 3, F17 P NOP
  pO w1 2, F17-w-fd-n7-pO-w1, F17-p-n1-mulu-pE-w2).
* W FDh at RFT 1 (C's 5 END rows, 4 X): the 32-clock grid's switch; not separated.
* PUSH/OUT pO 1-wait loop ends: B's exit cluster (7).
* F18-b-p-n7-shlmcl-pE-w2: the memory shift's write (D) against the model's fetch, one run.

#### Addendum (written after the simulator changes; refresh dumps of F8, F13, F17, F18 by runs.py, 2,472 runs, then all 17,822)

##### Adopted (each an enum in sim/config.py, default the old model; tests in `test_sim.RefreshIoRunAndTakeLatch`)

| rule | state | named run | gain when adopted (in order) |
| - | - | - | - |
| `refresh_io_run=pair` | A1 | F13-c-out-shlcl2-pE-w2 R95 F100 F105 I110 R113 (none: F100 I106 F109 R114) | +7 -0 (F8 2, F13 5; matched 42,223 -> 42,481, 31 runs later, none earlier) |
| `refresh_take_latch=hold` | E (B's NOP-train cluster) | F13-n-none-nop8-pE-w2 R129 F136 R143 (free: F134 R145) | +8 -0 (F13 1, F17 2, F18 5; matched 42,481 -> 42,589, 8 later) |

Prototype variants measured on the way (removed): the second fetch only with the I/O already posted and room >= 1
(+7, 23 later) or room >= 0 (+7, 23 later); with any IN/OUT running and room >= 1 (+7, 23 later); with every beaten
fetch, no I/O condition, room counting the latch (+32 -421, 450 earlier). refresh_io_run=pair is the IN/OUT-running
variant without a room condition (+7, 31 later: the pO second-OUT rows reach their I/O).

Over all 17,822 runs (sc30-all.txt): 17,431 (+15 -0 over sc29v: F8 +2 -> 19/48, F13 +6 -> 242/462, F17 +2 ->
729/798, F18 +5 -> 1094/1164); the refresh-off corpus unchanged (offg: 15,677 of 15,680, the guard 15,347 / 15,350;
every refresh-off END block exact, endchk); refresh-on END mismatches 399 -> 384; no model error. Refresh-on runs
(fdall, 2,142): 1,754 exact, 208 first LS, 162 X, 18 END.

##### Flip-backs, stage 8, knob dependence (final configuration fit-wp39-hand.json = fit.json)

Each adopted enum flipped back alone on the final hand fit (wp39/fl-<key>=<old>.json, all 17,822 runs against
sc30-all.txt; END mismatches from 384): `refresh_io_run=none` -7 (391), `refresh_take_latch=free` -8 (392); neither
gains a run, no model error. Stage 8 from the wrapped hand fit (wp39/hand-wrap.json): no move (chosen {}), exact
2,084 / 2,472, guard 15,347 / 15,350, matched 45,871; at the hand fit refresh_io_run=none 2,077, refresh_take_latch
=free 2,076; ties: refresh_timer start/end, refresh_exec every2/every2_early, refresh_recent_by=clocks,
wlatch_ir_at=start, refresh_eve=both. Its fit.json equals the hand fit (kept); its output is fit-wp39-stage8.json.
knob_dependence (F8 F13 F17 F18; REFRESH_HOLD_INTS + mul.rexit, div.rexit): no integer's best value differs by
parity, waits, k, marker, family or n.

##### Open, and why

* Item 8 a: the first LS's exec offset per FCh (wait, parity) cell (A2): pE w0 -2, pE w1 +1..2, pO w2 -2 would lift
  3 -> 62, 19 -> 55, 0 -> 59 runs with nothing earlier; one constant per cell, the prelude's phase; a per-cell
  alignment by the rules. The pE w1 marker OUT cell (19) and X's MOV CL in F13 S pE w1 (31) are this.
* A3 (the marker OUT's remainder after the rule): the pO second OUT's I/O count after the second fetch (8), the second
  OUT started after a refresh at X's shift's end (7: silicon's port take at s+8, the model's s+10; the MOV CL starts
  in the same state are right in 152 rows), F8-out-empty-pE-w2 (port_latch).
* D: the eve after a unit_hold wait (13 rows at w0 take, 16 at w1-w2 wait): the stall's kind (no wait state at w0)
  is the wait setting; the corpus has no row that separates them. No rule.
* B: the loop's exit at w1 pO (7: silicon's exit a clock earlier after the loop's refreshes), C1's 3-clock exec eve
  (5: a request on E+1 served on E+2 at no cost), CL 0 shifts (4), singles.
* C: the END's MOV DW take's fetch at H-10 (12): the state the model logs is identical in the right (8) and wrong
  (6) rows of tdl.py; consistent with silicon's closing LS ending later in the wrong rows after a refresh served a
  clock late in its exit (not shown); W FDh RFT 1 (5).

### The prelude's tail in the aligned lists: silicon's pre window, the model's run of it from the POP PSW read, the rules it needs (harness extension after the thirtieth fit, 2026-10-23; nothing adopted)

Written 2026-10-23 from the recorded runs (all 17,822, the raw traces from reset) and the thirtieth fit's model state
(fit.json = fit-wp39-hand.json = fit-wp39.json, 17431/17822; refresh-on F8 19/48, F13 242/462, F17 729/798, F18
1094/1164; of the 2,142 refresh-on runs fdall counts 1,754 exact, 208 first LS, 162 X, 18 END; rescore sc30v.txt).
Clocks are rel clock 0 (the fetch of the word holding the chain's first byte) unless written "rel R": rel the
prelude's POP PSW stack read (R = 0). r = the POP read, X a refresh (its first clock, as normalize rounds it), F a
fetch, q a refresh request (the counter's bit edge), s its service clock, L a refresh's length. "Model" is
fit-wp39-hand.json unless stated; "the candidate" is build/validation/v35s/chains/fit/wp40/fit-wp40-pop-candidate.json
(fit.json + prelude_tail=segs, prelude_anchor=pop, wlatch_ir_at=start and the six WP40 rules, section 5).

Tools (scratchpad wp40/): pre.py (silicon's pre window per run -> pre.pkl), grp.py (patterns per prelude cell), raw.py
(raw rows before clock 0), pair.py (each refresh-on cell's fetch i against the ECh cell's fetch i, the same word),
cells.py (model vs silicon pre window per prelude cell, one run each), rr.py / cmpr.py / xt.py (every run: exact,
first divergence, first-LS flag, pre exact; gained/lost; by cell), tr.py / starts.py / ev0.py (model clock traces,
instruction timelines, events from clock 0), rtab.py (every refresh in the pre window against the train), lsoff.py
(the first LS's start, stand-in vs candidate), tfill.py (t_fill and the clock-0 counter from the model's own tail),
flips.py (every enum value flipped alone, pre cells counted), esync.py / dlf.py / irlog2.py / bi.py / ior.py (state
logs used for the refutations, section 7), fdall40.py (wp39/fdall.py with the model's clock-0 offset: with the tail
run the simulation's clocks start at the POP read).

#### 1. Silicon's pre window, every run (pre.py, grp.py)

The prelude's POP PSW read is the first memory read at 0EFEh in the raw trace (the prelude's PUSH 0002h writes 0EFEh
just before it; nothing else reads below 1000h before the register loads). From it to clock 0 every row of every run
lies on the run's tick phase (0 of 17,822 runs with an off-phase row; refresh rows one tick early as after clock 0).
Per prelude (RFM, WTC) and marker the window is single-valued: one pattern in every cell, the same at both
parities and in every family and chain that shares the prelude, every repeat included. The marker preludes' window is
the bare prelude's rel R (the same refreshes, the same fetches) plus the fetch of the marker's word (10046h) before
clock 0 (10048h); their POP read lies 7 (ECh w0), 8, 9 or 5 clocks earlier against clock 0 for that reason only. F8h is
FCh to the clock (RFW 3 = RFW 2).

| RFM | WTC (waits) | marker | runs | patterns | families | parities | POP read rel clock 0 | the window rel the read (r0 = the read; X refresh, F fetch) |
| - | - | - | - | - | - | - | - | - |
| ECh | 0000 | - | 5658 | 1 | 22 families | both | -79 | F11 F14 F17 F24 F27 F30 F34 F37 F44 F47 F51 F58 F61 F65 F72 F75 |
| ECh | 0001 | - | 5656 | 1 | 21 families | both | -92 | F12 F16 F20 F28 F32 F36 F40 F44 F52 F56 F60 F68 F72 F76 F84 F88 |
| ECh | 0002 | - | 5658 | 1 | 22 families | both | -109 | F13 F18 F23 F32 F37 F42 F47 F52 F61 F66 F71 F80 F85 F90 F99 F104 |
| ECh | 0008 | - | 2 | 1 | F0w | both | -79 | F11 F14 F17 F24 F27 F30 F34 F37 F44 F47 F51 F58 F61 F65 F72 F75 |
| ECh | 0020 | - | 2 | 1 | F0w | both | -79 | F11 F14 F17 F24 F27 F30 F34 F37 F44 F47 F51 F58 F61 F65 F72 F75 |
| ECh | 0080 | - | 2 | 1 | F0w | both | -79 | F11 F14 F17 F24 F27 F30 F34 F37 F44 F47 F51 F58 F61 F65 F72 F75 |
| ECh | 0200 | - | 2 | 1 | F0w | both | -79 | F11 F14 F17 F24 F27 F30 F34 F37 F44 F47 F51 F58 F61 F65 F72 F75 |
| ECh | 0800 | - | 2 | 1 | F0w | both | -79 | F11 F14 F17 F24 F27 F30 F34 F37 F44 F47 F51 F58 F61 F65 F72 F75 |
| ECh | 2000 | - | 2 | 1 | F0w | both | -79 | F11 F14 F17 F24 F27 F30 F34 F37 F44 F47 F51 F58 F61 F65 F72 F75 |
| ECh | 8000 | - | 2 | 1 | F0w | both | -79 | F11 F14 F17 F24 F27 F30 F34 F37 F44 F47 F51 F58 F61 F65 F72 F75 |
| ECh | AAAA | - | 2 | 1 | F0w | both | -109 | F13 F18 F23 F32 F37 F42 F47 F52 F61 F66 F71 F80 F85 F90 F99 F104 |
| ECh | 0000 | out | 18 | 1 | F18 | both | -86 | F11 F14 F17 F24 F27 F30 F34 F37 F44 F47 F51 F58 F61 F65 F72 F75 F79 |
| ECh | 0001 | out | 18 | 1 | F18 | both | -100 | F12 F16 F20 F28 F32 F36 F40 F44 F52 F56 F60 F68 F72 F76 F84 F88 F92 |
| ECh | 0002 | out | 18 | 1 | F18 | both | -118 | F13 F18 F23 F32 F37 F42 F47 F52 F61 F66 F71 F80 F85 F90 F99 F104 F109 |
| ECh | 0000 | push | 18 | 1 | F18 | both | -86 | F11 F14 F17 F24 F27 F30 F34 F37 F44 F47 F51 F58 F61 F65 F72 F75 F79 |
| ECh | 0001 | push | 18 | 1 | F18 | both | -100 | F12 F16 F20 F28 F32 F36 F40 F44 F52 F56 F60 F68 F72 F76 F84 F88 F92 |
| ECh | 0002 | push | 18 | 1 | F18 | both | -118 | F13 F18 F23 F32 F37 F42 F47 F52 F61 F66 F71 F80 F85 F90 F99 F104 F109 |
| F0h | 0000 | - | 2 | 1 | F13 | both | -80 | X3 F12 F15 F18 X21 F25 F28 F31 X35 F38 F41 F45 F48 X52 F55 F59 F62 F66 X69 F73 F76 |
| F0h | 0001 | - | 2 | 1 | F13 | both | -92 | X8 F12 F16 F20 X24 F28 F32 F36 X40 F43 F47 F51 F55 X59 F62 F66 F70 X74 F77 F81 F85 X89 |
| F0h | 0002 | - | 2 | 1 | F13 | both | -115 | X7 F14 F19 X24 F27 F32 F37 X42 F46 F51 X56 F59 F64 F69 X74 F77 F82 X87 F91 F96 F101 X106 F110 |
| F4h | 0000 | - | 2 | 1 | F13 | both | -89 | F11 X14 F18 F21 F25 X28 F32 F36 F39 F42 X45 F49 F52 F56 X63 F67 F71 F74 X78 F82 F86 |
| F4h | 0001 | - | 2 | 1 | F13 | both | -102 | X4 F14 X18 F22 F26 F30 X34 F38 F42 F46 X50 F54 F58 F62 X66 F70 F74 F78 X82 F86 F90 F94 X98 |
| F4h | 0002 | - | 2 | 1 | F13 | both | -123 | X5 F15 X20 F24 F29 X34 F38 F43 F48 X53 F57 F62 X67 F71 F76 X81 F85 F90 F95 X100 F104 F109 X114 F118 |
| F8h | 0000 | - | 2 | 1 | F13 | both | -98 | X11 F16 F19 F22 X29 F34 F37 F40 X44 F49 F52 F56 X59 F64 F67 F71 X74 F79 F82 F86 F89 X93 |
| F8h | 0001 | - | 2 | 1 | F13 | both | -111 | X12 F17 F21 F25 X29 F34 F38 X42 F47 F51 F55 X59 F64 F68 F72 X76 F81 F85 F89 X93 F98 F102 X106 |
| F8h | 0002 | - | 2 | 1 | F13 | both | -133 | X13 F18 F23 X28 F33 F38 X43 F48 F53 F58 X63 F68 F73 X78 F83 F88 X93 F98 F103 X108 F113 F118 X123 F128 |
| FCh | 0000 | - | 166 | 1 | F8, F13, F17 | both | -98 | X11 F16 F19 F22 X29 F34 F37 F40 X44 F49 F52 F56 X59 F64 F67 F71 X74 F79 F82 F86 F89 X93 |
| FCh | 0001 | - | 166 | 1 | F8, F13, F17 | both | -111 | X12 F17 F21 F25 X29 F34 F38 X42 F47 F51 F55 X59 F64 F68 F72 X76 F81 F85 F89 X93 F98 F102 X106 |
| FCh | 0002 | - | 166 | 1 | F8, F13, F17 | both | -133 | X13 F18 F23 X28 F33 F38 X43 F48 F53 F58 X63 F68 F73 X78 F83 F88 X93 F98 F103 X108 F113 F118 X123 F128 |
| FCh | 0000 | out | 16 | 1 | F18 | both | -102 | X11 F16 F19 F22 X29 F34 F37 F40 X44 F49 F52 F56 X59 F64 F67 F71 X74 F79 F82 F86 F89 X93 F98 |
| FCh | 0001 | out | 16 | 1 | F18 | both | -115 | X12 F17 F21 F25 X29 F34 F38 X42 F47 F51 F55 X59 F64 F68 F72 X76 F81 F85 F89 X93 F98 F102 X106 F111 |
| FCh | 0002 | out | 16 | 1 | F18 | both | -138 | X13 F18 F23 X28 F33 F38 X43 F48 F53 F58 X63 F68 F73 X78 F83 F88 X93 F98 F103 X108 F113 F118 X123 F128 F133 |
| FCh | 0000 | push | 16 | 1 | F18 | both | -102 | X11 F16 F19 F22 X29 F34 F37 F40 X44 F49 F52 F56 X59 F64 F67 F71 X74 F79 F82 F86 F89 X93 F98 |
| FCh | 0001 | push | 16 | 1 | F18 | both | -115 | X12 F17 F21 F25 X29 F34 F38 X42 F47 F51 F55 X59 F64 F68 F72 X76 F81 F85 F89 X93 F98 F102 X106 F111 |
| FCh | 0002 | push | 16 | 1 | F18 | both | -138 | X13 F18 F23 X28 F33 F38 X43 F48 F53 F58 X63 F68 F73 X78 F83 F88 X93 F98 F103 X108 F113 F118 X123 F128 F133 |
| FDh | 0000 | - | 2 | 1 | F13 | both | -88 | X11 F16 F19 F22 F29 F32 F35 F39 X42 F47 F51 F54 F58 F65 F68 X72 F77 F81 F84 |
| FDh | 0001 | - | 2 | 1 | F13 | both | -103 | F12 F16 F20 X28 F33 F37 F41 F45 F49 X57 F62 F66 F70 F78 F82 F86 X90 F95 F99 |
| FDh | 0002 | - | 2 | 1 | F13 | both | -125 | X13 F18 F23 F28 F37 F42 X47 F52 F57 F62 F71 F76 X81 F86 F91 F96 F101 X110 F115 F120 |
| FDh | 0000 | out | 16 | 1 | F18 | both | -95 | X11 F16 F19 F22 F29 F32 F35 F39 X42 F47 F51 F54 F58 F65 F68 X72 F77 F81 F84 F88 |
| FDh | 0001 | out | 16 | 1 | F18 | both | -111 | F12 F16 F20 X28 F33 F37 F41 F45 F49 X57 F62 F66 F70 F78 F82 F86 X90 F95 F99 F103 |
| FDh | 0002 | out | 16 | 1 | F18 | both | -134 | X13 F18 F23 F28 F37 F42 X47 F52 F57 F62 F71 F76 X81 F86 F91 F96 F101 X110 F115 F120 F125 |
| FDh | 0000 | push | 16 | 1 | F18 | both | -95 | X11 F16 F19 F22 F29 F32 F35 F39 X42 F47 F51 F54 F58 F65 F68 X72 F77 F81 F84 F88 |
| FDh | 0001 | push | 16 | 1 | F18 | both | -111 | F12 F16 F20 X28 F33 F37 F41 F45 F49 X57 F62 F66 F70 F78 F82 F86 X90 F95 F99 F103 |
| FDh | 0002 | push | 16 | 1 | F18 | both | -134 | X13 F18 F23 F28 F37 F42 X47 F52 F57 F62 F71 F76 X81 F86 F91 F96 F101 X110 F115 F120 F125 |
| FEh | 0000 | - | 2 | 1 | F13 | both | -84 | F11 F14 F17 F24 X27 F32 F36 F39 F42 F49 F52 F56 F63 F66 F70 F77 F80 |
| FEh | 0001 | - | 2 | 1 | F13 | both | -94 | F12 F16 X20 F25 F29 F33 F37 F41 F45 F53 F57 F61 F69 F73 F77 X81 F86 F90 |
| FEh | 0002 | - | 2 | 1 | F13 | both | -113 | X5 F16 F21 F26 F35 F40 F45 F50 F55 F64 X69 F74 F79 F84 F89 F94 F103 F108 |
| FFh | 0000 | - | 2 | 1 | F13 | both | -79 | F11 F14 F17 F24 F27 F30 F34 F37 F44 F47 F51 F58 F61 F65 F72 F75 |
| FFh | 0001 | - | 2 | 1 | F13 | both | -92 | F12 F16 F20 F28 F32 F36 F40 F44 F52 F56 F60 F68 F72 F76 F84 F88 |
| FFh | 0002 | - | 2 | 1 | F13 | both | -114 | F13 F18 F23 F32 F37 F42 F47 F52 F61 F66 F71 F80 F85 F90 F99 X104 F109 |

The prelude bytes (image.prelude_source): 86 distinct byte strings over the 17,822 runs, differing only in the register
immediates (BW, CW, DW, SP-load, BP, IX, IY, AW values) and the three SFR values; 71 bytes without a marker, 72 with PUSH
AW, 73 with OUT 20h,AL; PRC 76h in every chain. Within one (RFM, WTC, marker) cell up to 10 byte strings occur (ECh w0:
10) with one window: the window is timing-identical whatever the immediates. The tail after POP PSW (10020h-10046h): MOV
AW,imm16 ; MOV DS0,AW ; MOV AW,imm16 ; MOV DS1,AW ; MOV AW,imm16 ; MOV SS,AW (three segment loads, 8E /r) ; MOV BW,CW,
DW,SP,BP,IX,IY,imm16 (B8+r) ; MOV AW,imm16 ; [marker].

Each refresh-on cell's fetch i against the ECh cell's fetch i (the same word), rel R (pair.py; +n: n clocks later than
ECh; marker cells as their bare cell):

```
F0 w0 None X3(L3) F12+1 F15+1 F18+1 X21(L3) F25+1 F28+1 F31+1 X35(L3) F38+4 F41+4 F45+1 F48+1 X52(L3) F55+4 F59+1 F62+1 F66+1 X69(L3) F73+1 F76+1 F80+1
F0 w1 None X8(L3) F12+0 F16+0 F20+0 X24(L3) F28+0 F32+0 F36+0 X40(L3) F43+3 F47+3 F51-1 F55-1 X59(L3) F62+2 F66-2 F70-2 X74(L3) F77+1 F81-3 F85-3 X89(L3) F92+0
F0 w2 None X7(L3) F14+1 F19+1 X24(L3) F27+4 F32+0 F37+0 X42(L3) F46+4 F51+4 X56(L3) F59+7 F64+3 F69+3 X74(L3) F77+6 F82+2 X87(L3) F91+6 F96+6 F101+2 X106(L3) F110+6 F115+6
F4 w0 None F11+0 X14(L4) F18+4 F21+4 F25+1 X28(L4) F32+5 F36+6 F39+5 F42+5 X45(L4) F49+5 F52+5 F56+5 X63(L4) F67+9 F71+10 F74+9 X78(L4) F82+10 F86+11 F89+10
F4 w1 None X4(L4) F14+2 X18(L4) F22+6 F26+6 F30+2 X34(L4) F38+6 F42+6 F46+6 X50(L4) F54+10 F58+6 F62+6 X66(L4) F70+10 F74+6 F78+6 X82(L4) F86+10 F90+6 F94+6 X98(L4) F102+10
F4 w2 None X5(L4) F15+2 X20(L4) F24+6 F29+6 X34(L4) F38+6 F43+6 F48+6 X53(L4) F57+10 F62+10 X67(L4) F71+10 F76+10 X81(L4) F85+14 F90+10 F95+10 X100(L4) F104+14 F109+10 X114(L4) F118+14 F123+14
F8 w0 None X11(L5) F16+5 F19+5 F22+5 X29(L5) F34+10 F37+10 F40+10 X44(L5) F49+15 F52+15 F56+12 X59(L5) F64+17 F67+16 F71+13 X74(L5) F79+18 F82+17 F86+14 F89+14 X93(L5) F98+19
F8 w1 None X12(L5) F17+5 F21+5 F25+5 X29(L5) F34+6 F38+6 X42(L5) F47+11 F51+11 F55+11 X59(L5) F64+12 F68+12 F72+12 X76(L5) F81+13 F85+13 F89+13 X93(L5) F98+14 F102+14 X106(L5) F111+19
F8 w2 None X13(L5) F18+5 F23+5 X28(L5) F33+10 F38+6 X43(L5) F48+11 F53+11 F58+11 X63(L5) F68+16 F73+12 X78(L5) F83+17 F88+17 X93(L5) F98+18 F103+18 X108(L5) F113+23 F118+19 X123(L5) F128+24 F133+24
FC w0 None X11(L5) F16+5 F19+5 F22+5 X29(L5) F34+10 F37+10 F40+10 X44(L5) F49+15 F52+15 F56+12 X59(L5) F64+17 F67+16 F71+13 X74(L5) F79+18 F82+17 F86+14 F89+14 X93(L5) F98+19
FC w1 None X12(L5) F17+5 F21+5 F25+5 X29(L5) F34+6 F38+6 X42(L5) F47+11 F51+11 F55+11 X59(L5) F64+12 F68+12 F72+12 X76(L5) F81+13 F85+13 F89+13 X93(L5) F98+14 F102+14 X106(L5) F111+19
FC w2 None X13(L5) F18+5 F23+5 X28(L5) F33+10 F38+6 X43(L5) F48+11 F53+11 F58+11 X63(L5) F68+16 F73+12 X78(L5) F83+17 F88+17 X93(L5) F98+18 F103+18 X108(L5) F113+23 F118+19 X123(L5) F128+24 F133+24
FD w0 None X11(L5) F16+5 F19+5 F22+5 F29+5 F32+5 F35+5 F39+5 X42(L5) F47+10 F51+7 F54+7 F58+7 F65+7 F68+7 X72(L5) F77+12 F81+9 F84+9 F88+9
FD w1 None F12+0 F16+0 F20+0 X28(L5) F33+5 F37+5 F41+5 F45+5 F49+5 X57(L5) F62+10 F66+10 F70+10 F78+10 F82+10 F86+10 X90(L5) F95+11 F99+11 F103+11
FD w2 None X13(L5) F18+5 F23+5 F28+5 F37+5 F42+5 X47(L5) F52+10 F57+10 F62+10 F71+10 F76+10 X81(L5) F86+15 F91+11 F96+11 F101+11 X110(L5) F115+16 F120+16 F125+16
FE w0 None F11+0 F14+0 F17+0 F24+0 X27(L5) F32+5 F36+6 F39+5 F42+5 F49+5 F52+5 F56+5 F63+5 F66+5 F70+5 F77+5 F80+5 F84+5
FE w1 None F12+0 F16+0 X20(L5) F25+5 F29+1 F33+1 F37+1 F41+1 F45+1 F53+1 F57+1 F61+1 F69+1 F73+1 F77+1 X81(L5) F86+2 F90+2 F94+2
FE w2 None X5(L5) F16+3 F21+3 F26+3 F35+3 F40+3 F45+3 F50+3 F55+3 F64+3 X69(L5) F74+8 F79+8 F84+4 F89+4 F94+4 F103+4 F108+4 F113+4
FF w0 None F11+0 F14+0 F17+0 F24+0 F27+0 F30+0 F34+0 F37+0 F44+0 F47+0 F51+0 F58+0 F61+0 F65+0 F72+0 F75+0 F79+0
FF w1 None F12+0 F16+0 F20+0 F28+0 F32+0 F36+0 F40+0 F44+0 F52+0 F56+0 F60+0 F68+0 F72+0 F76+0 F84+0 F88+0 F92+0
FF w2 None F13+0 F18+0 F23+0 F32+0 F37+0 F42+0 F47+0 F52+0 F61+0 F66+0 F71+0 F80+0 F85+0 F90+0 F99+0 X104(L5) F109+5 F114+5
```

A refresh at the first fetch's clock moves the whole train by its length (FCh/F8h/FDh w0-w2: +5 from X11-X13 on); later
ones cost the train their length, or less, or nothing (FDh w0: X42 then +5 for the beaten fetch and +2 after it), per the
EU's state (section 4).

#### 2. The harness (normalize.py, score.py; test_analysis.PreWindowTests)

* normalize.py: `Normalized.pre` (new field, default empty): the Events from the prelude's POP PSW read (`prelude_pop_row`:
  the first non-I/O, non-refresh read at `PRE_STACK[0]` = 0EFEh before clock 0's row) up to clock 0, clocks rel clock 0,
  the same Event fields (kind by kind_of with the prelude's stack 0EFEh-0F00h, so the read is a stack_read; fetches carry
  instr_index/byte_range None: they are prelude bytes); an off-phase row is a soft check like the others (none occurs).
  `events`, `t_fill`, `fill_index`, the markers and the access match are untouched.
* score.py: `pre_aligned(n)` (the pre list as aligned() keys, a refresh's row address left out: it is a label the model
  counts from the main list's anchor at t_fill, so comparing it would carry the main list's agreement into the pre
  comparison), `pre_score(silicon, model)` -> (exact, matched prefix, silicon length), `pre_summary`, and `score --pre`
  (a "pre window exact all a/b pE-w0 ..." line after each family's summary). Score.exact and the default output are
  unchanged: all 23 families rescored with the new code under fit.json are byte-identical to sc30v.txt (cmp), before
  and after every later change (sc31-all.txt).
* the model's pre list: with prelude_anchor=pop the simulation's trace holds the POP read and everything after it, so the
  same normalize() call fills `pre` (machine.py); with the stand-in, or prelude_tail=regs/segs anchored at clock 0, the
  model has no POP read and its pre list is empty (never exact).

#### 3. The model's tail from the POP read: the refresh-off preludes (cells.py, tfill.py)

prelude_tail=segs (the segment loads as register forms, from a queue full with the 3 words after POP PSW's opcode,
10020h-10025h) reproduces every refresh-off window's fetches rel clock 0 exactly as it stands (the record's "every
refresh-off cell at t_fill" holds for the whole window: ECh F-68 ... F-4 at w0, all nine ECh cells, both parities). The
start state the tail needs is one fact, read off the window, not a table:

| fact | evidence (rel R) |
| - | - |
| the POP read issues on the run's first clock with the queue full (6 bytes after 9Dh, the IR loading the first B8h) and the bus idle after it | ECh w0/w1/w2: r0, F11 / F12 / F13: the first fetch 9 clocks after the read's last clock at every wait |
| the first segment load starts pop_exit = 4 clocks after the read's delivery (R + 7 + w), and runs as the model's tail from its first clock (first fetch at R + 11 + w) | pop_exit 3: r-78 for r-79 against the same train (and the post-clock-0 refresh grid a clock off in F17 S/E/W) |
| the refresh counter's value at the POP read is one constant per prelude RFM and WTC, POP_COUNTER (refresh.py) = PRELUDE_COUNTER + the read's clock rel clock 0 | the marker preludes give the same value modulo the interval in every cell (ECh 1 / 10 / 6 mod 16, FCh 14 / 14 / 13 mod 16, FDh 8 / 23 / 3 mod 32); FCh w0: 30, requests at R + 10 + 16k, served 11 29 44 59 74 93 |

With these (prelude_anchor=pop, POP_COUNTER, pop_exit 4) and nothing else new, the pre window is exact in all 15,680
refresh-off runs and their scores are unchanged (15,677 / 15,680; every refresh-off END block exact), and in 1,628 of the
2,142 refresh-on runs (19 of the 42 prelude cells): F0h w1/w2, FCh/F8h w1 (the bare and both marker cells), FEh w1, FFh
w0-w2 and ECh. The refresh-on score: +45 -265 against fit.json (the record's +45 -106 with segs anchored at clock 0).

#### 4. The refresh-on preludes: every refresh in the window (rtab.py on the candidate, exact in 40 of 42 cells)

Rel R; "beats fetch": the bus would have started a fetch on s; the class and step are the EU's on s, start its last
instruction start (imm = MOV r16/AW,imm16, reg = MOV sreg,AW; "-": still in POP PSW's clocks).

```
(F8h is FCh to the clock; omitted)
F0 w0 F13-r-rfw-0-pE-w0 pre exact
     q3 s3 (+0, L3) None/- start-1
     q19 s21 (+2, L3) imm/take start21
     q35 s35 (+0, L3) imm/clocks start31 beats fetch
     q51 s52 (+1, L3) imm/clocks start48 beats fetch
     q67 s69 (+2, L3) imm/take start69
F0 w1 F13-r-rfw-0-pE-w1 pre exact
     q8 s8 (+0, L3) imm/take start8
     q24 s24 (+0, L3) imm/take start24
     q40 s40 (+0, L3) imm/clocks start36 beats fetch
     q56 s59 (+3, L3) imm/clocks start55 beats fetch
     q72 s74 (+2, L3) imm/clocks start70 beats fetch
     q88 s89 (+1, L3) imm/clocks start85 beats fetch
F0 w2 F13-r-rfw-0-pE-w2 pre exact
     q7 s7 (+0, L3) None/- start-1
     q23 s24 (+1, L3) reg/clocks start24 beats fetch
     q39 s42 (+3, L3) imm/take start42 beats fetch
     q55 s56 (+1, L3) reg/clocks start56 beats fetch
     q71 s74 (+3, L3) imm/clocks start69 beats fetch
     q87 s87 (+0, L3) imm/take start87 beats fetch
     q103 s106 (+3, L3) imm/take start106 beats fetch
F4 w0 F13-r-rfw-1-pE-w0 pre DIFFERS
     q12 s14 (+2, L4) imm/- start7 beats fetch
     q28 s28 (+0, L4) reg/clocks start28 beats fetch
     q44 s45 (+1, L4) imm/take start45
     q60 s63 (+3, L4) imm/clocks start59 beats fetch
     q76 s76 (+0, L4) imm/take start76
F4 w1 F13-r-rfw-1-pE-w1 pre exact
     q1 s4 (+3, L4) None/- start-1
     q17 s18 (+1, L4) imm/- start10 beats fetch
     q33 s34 (+1, L4) reg/clocks start34 beats fetch
     q49 s50 (+1, L4) reg/clocks start50 beats fetch
     q65 s66 (+1, L4) imm/clocks start62 beats fetch
     q81 s82 (+1, L4) imm/clocks start78 beats fetch
     q97 s98 (+1, L4) imm/clocks start94 beats fetch
F4 w2 F13-r-rfw-1-pE-w2 pre exact
     q1 s5 (+4, L4) None/- start-1
     q17 s20 (+3, L4) imm/- start11 beats fetch
     q33 s34 (+1, L4) imm/clocks start29 beats fetch
     q49 s53 (+4, L4) imm/clocks start48 beats fetch
     q65 s67 (+2, L4) imm/clocks start62 beats fetch
     q81 s81 (+0, L4) imm/clocks start76 beats fetch
     q97 s100 (+3, L4) imm/clocks start95 beats fetch
     q113 s114 (+1, L4) imm/take start114 beats fetch
FC w0 (F8h the same) F13-c-out-shlcl0-pE-w0 pre exact
     q10 s11 (+1, L5) imm/clocks start7 beats fetch
     q26 s29 (+3, L5) imm/clocks start25 beats fetch
     q42 s44 (+2, L5) imm/clocks start40 beats fetch
     q58 s59 (+1, L5) imm/take start59 beats fetch
     q74 s74 (+0, L5) imm/take start74 beats fetch
     q90 s93 (+3, L5) imm/clocks start89 beats fetch
FC w1 F13-c-out-shlcl0-pE-w1 pre exact
     q10 s12 (+2, L5) imm/clocks start8 beats fetch
     q26 s29 (+3, L5) imm/take start29
     q42 s42 (+0, L5) imm/take start42 beats fetch
     q58 s59 (+1, L5) imm/take start59
     q74 s76 (+2, L5) imm/take start76
     q90 s93 (+3, L5) imm/take start93
     q106 s106 (+0, L5) imm/clocks start102 beats fetch
FC w2 F13-c-out-shlcl0-pE-w2 pre exact
     q11 s13 (+2, L5) imm/clocks start9 beats fetch
     q27 s28 (+1, L5) reg/clocks start28 beats fetch
     q43 s43 (+0, L5) reg/clocks start43 beats fetch
     q59 s63 (+4, L5) reg/clocks start63 beats fetch
     q75 s78 (+3, L5) imm/take start78 beats fetch
     q91 s93 (+2, L5) imm/clocks start88 beats fetch
     q107 s108 (+1, L5) imm/clocks start103 beats fetch
     q123 s123 (+0, L5) imm/take start123 beats fetch
FD w0 F13-r-rfm-f1-pE-w0 pre exact
     q8 s11 (+3, L5) imm/clocks start7 beats fetch
     q40 s42 (+2, L5) reg/clocks start42 beats fetch
     q72 s72 (+0, L5) imm/clocks start68 beats fetch
FD w1 F13-r-rfm-f1-pE-w1 pre exact
     q25 s28 (+3, L5) imm/clocks start24 beats fetch
     q57 s57 (+0, L5) imm/clocks start53 beats fetch
     q89 s90 (+1, L5) imm/take start90
FD w2 F13-r-rfm-f1-pE-w2 pre exact
     q13 s13 (+0, L5) imm/clocks start9 beats fetch
     q45 s47 (+2, L5) imm/take start47 beats fetch
     q77 s81 (+4, L5) imm/clocks start76 beats fetch
     q109 s110 (+1, L5) imm/clocks start106 beats fetch
FE w0 F13-r-rfm-f2-pE-w0 pre DIFFERS
     q26 s27 (+1, L5) reg/clocks start27 beats fetch
FE w1 F13-r-rfm-f2-pE-w1 pre exact
     q17 s20 (+3, L5) reg/clocks start20 beats fetch
     q81 s81 (+0, L5) imm/take start81
FE w2 F13-r-rfm-f2-pE-w2 pre exact
     q5 s5 (+0, L5) None/- start-1
     q69 s69 (+0, L5) imm/take start69 beats fetch
FF w0 F13-r-rfm-f3-pE-w0 pre exact
FF w1 F13-r-rfm-f3-pE-w1 pre exact
FF w2 F13-r-rfm-f3-pE-w2 pre exact
     q104 s104 (+0, L5) imm/take start104 beats fetch
```

Read against section 1: the requests go on the first free bus clock at 1-2 waits and 0-4 clocks after it at 0 waits only
because the EU, not the bus, is the bottleneck there (the record's "0, 1 or 3 clocks after it at 0 waits"); every refresh
is served where the existing acceptance (refresh_accept=boundary_bus, refresh_take=last: on an operand take's last byte
or when the bus would start a cycle) puts it; what differed was the EU's and the queue's state after it:

| silicon, in the window | the model before WP40 | machine state |
| - | - | - |
| a refresh inside POP PSW's clocks after its read delays the first segment load by L - 2 | nothing (the EU is idle there) | POP PSW's post-read clocks take a refresh as a count loop's iteration: F0h w0 X3 (L3) F12 (+1), F4h w1 X4 (L4) F14 (+2), F4h w2 X5 F15 (+2), FEh w2 X5 (L5) F16 (+3); a refresh on the start clock itself costs nothing (F0h w1 X8 F12 +0) |
| the fetch a refresh beat on a take + IR-load clock runs with a second back to back (FCh w1: X12 F17 F21 F25) | the flag cleared on the beaten fetch's issue, the next queue change raising it (F17, X31 F36) | the beaten fetch keeps the reissue evaluation of the clock it was beaten on |
| MOV sreg,AW (8E /r) after a MOV AW,imm16 whose fetch a refresh beat starts after the run of fetches (FCh w0: on 22, ECh + 5) | on the run's early clocks (17) | a ModR/M form does not use refresh_sync=run's early start (it waits out the run, as start_sync=b2b_modrm holds it off a back-to-back fetch) |
| the take sync counting the third fetch of such a run is met on its delivery (FDh w1 F70 F78) | 2 clocks early (F70 F76) | refresh_sync=run's early sync on the run's first two fetches only |
| MOV sreg,AW's own take sync on a fetch of the run is met on the delivery (FCh w0 X44 F49) | early (X43 F48) | not early for class reg (its sync is its end) |
| MOV r16,imm16's last immediate take with the queue a byte short of a word raises no request on the IR's idle slot (FDh w0 X72 F77 F81: the next load on the beaten fetch's issue clock) | it does (room_ir=arrival_idle), and the take sync then waits for the beaten fetch (F82) | the IR's idle slot is not counted while a register form with a 16-bit immediate runs |

#### 5. Rules (each an enum in sim/config.py, DEFAULT the old model; test_sim.PreludePopAnchor; none in fit.json)

| enum | values (default first) | named run, rel R: silicon / the alternative | pre cells the flip-back loses (cells.py, from the candidate's 40/42) | effect on the 17,822 chain runs with the stand-in prelude |
| - | - | - | - | - |
| prelude_anchor | clock0 / pop (+ pop_exit 4, refresh.POP_COUNTER) | F17-s-n0-empty-pE-w0 r0 F11 F14 F17 F24 (no POP read in the model) | all 42 (no pre list) | prelude_tail=standin: not read |
| pop_refresh | none / stall | F13-r-rfw-1-pE-w1: X4 F14 X18 F22 / X4 F12 F16 X20 | 4 (F0h w0, F4h w1, F4h w2, FEh w2) | read only with prelude_anchor=pop |
| refresh_reissue | clear / keep | F13-c-out-shlcl0-pE-w1: X12 F17 F21 F25 X29 F34 / ... F25 X31 F36 | 14 (F8h w0/w1, FCh w0/w1 x3, FDh w0/w2 x3) | none (matched prefixes identical) |
| refresh_run_modrm | early / wait | F13-c-out-shlcl0-pE-w1: the same / X31 F36 | 14 (the same cells) | none |
| refresh_sync_run | all / two | F13-r-rfm-f1-pE-w1: F70 F78 F82 F86 X90 / F70 F76 F80 F84 X92 | 5 (FDh w1 x3, FDh w2 marker x2) | none (1,405 prefix-matched early syncs in F8/F13/F17/F18, all on a run's first or second fetch) |
| refresh_sync_reg | early / delivery | F13-c-out-shlcl0-pE-w0: F40 X44 F49 / F40 X43 F48 | 4 (F8h w0, FCh w0 x3) | none (no class reg sync is met early in the chain) |
| room_ir_imm | idle / none | F13-r-rfm-f1-pE-w0: X72 F77 F81 / X72 F77 F82 | 8 (F0h w0, F8h w0, FCh w0 x3, FDh w0 x3) | none, refresh off included (15,680 runs: there the request comes from the real room) |

All six together on the stand-in: no run of the corpus changes (17,822 runs, every first-divergence index identical).
In stage 8's search list; REFRESH_SEED carries their old values (not adopted, section 6).

#### 6. The candidate against the gate (rr.py, the official score with --pre: wp40/sc-cand.txt; tally against sc30v)

| | fit.json (sc30v = sc31-all) | prelude_anchor=pop alone | the candidate |
| - | - | - | - |
| pre window exact, refresh off (15,680) | 0 (no pre list) | 15,680 | 15,680 |
| pre window exact, refresh on (2,142) | 0 | 1,628 | 2,138 (all but F13-r-rfw-1-p?-w0, F13-r-rfm-f2-p?-w0) |
| pre prelude cells exact (42) | 0 | 19 | 40 |
| refresh-off exact (15,680; guard 15,350) | 15,677 (15,347) | 15,677 (15,347) | 15,677 (15,347); every refresh-off END block exact |
| exact, all 17,822 | 17,431 | 17,211 (+45 -265) | 17,572 (+192 -51) |
| F8 / F13 / F17 / F18 | 19 / 242 / 729 / 1094 | | 28 / 378 / 748 / 1071 |
| refresh-on first divergence (fdall40): exact / first LS / X / END | 1,754 / 208 / 162 / 18 | | 1,895 / 68 / 157 / 22 |
| the 208 first-LS runs of sc30v | | | 153 exact, 33 now in X, 4 in END, 18 still first LS |
| model t_fill = silicon's (refresh on) | (SILICON_FILL by construction) | | 2,072 of 2,142; the counter at the model's own clock 0 = PRELUDE_COUNTER (mod the interval) in 2,140 |

The first LS's offsets of the thirtieth fit (A2: the exec moved -2 at FCh pE w0, +1..2 at pE w1, -2 at pO w2, 62 / 55 / 59
runs exact) come out of the model's own run (lsoff.py, the first LS's SHL AW,CL start rel t_fill, stand-in -> candidate):
pE w0 -2 -> -7, exact 5 -> 64 of 83; pE w1 -3 -> +1, 19 -> 61; pO w2 -4 -> -9, 0 -> 59; pO w0, pO w1, pE w2 unchanged
(-2, -3, -4; 67, 68, 59), as A2 found no offset better than 0 there. The start moves more than A2's exec shift (5 and 4
clocks against 2 and 1): the shift's start waits on its take sync in the stand-in, the exec clocks are what A2 moved.

Each rule flipped back alone on the candidate (F8, F13, F17, F18; rr.py, against the candidate's 2,225 / 2,472):
pop_refresh=none -8 (F13 R); refresh_reissue=clear -198 and refresh_run_modrm=early -198 (F8 13, F13 113, F17 9, F18
63; the same runs: each alone undoes the FCh/F8h/FDh 0- and 1-wait trains); refresh_sync_run=all +4 -34 (F18 32: the
FDh 1- and 2-wait cells); room_ir_imm=idle -169; refresh_sync_reg=early +2 -0 (F13-r-rfm-f2-pE-w0 and F13-r-rfw-1-pE-w0,
whose pre windows are wrong either way, become exact), and it makes the pre window of every FCh/F8h 0-wait run wrong
(200 runs) while their scores stay: the rule is the window's, the chain does not see it.

Not adopted: the gate is "nothing lost", and 51 runs are lost (all refresh-on; xt.py, the official tally):

| lost | runs | where silicon and the candidate first differ |
| - | - | - |
| F18 A, the OUT 20h,AL marker, FCh w0 pE/pO, w1 pO, w2 pE | 31 | the pre window exact; after clock 0 the refresh requested inside the marker's I/O lead: silicon serves it on its request, the model holds it to the I/O's issue (refresh_lead=closed): FCh pE w0 rel clock 0 silicon F12 F15 X20 I25, candidate X22 I27 (w2: silicon F27 I32, candidate I29) |
| F18 A, the OUT marker, FDh w0 pE/pO | 16 | the request at clock 0 + 9 during the last load's fetch: silicon X11 F21 I24 (the OUT starts during the refresh), candidate X10 F23 I26 |
| F13-r-rfw-1-pE-w0, F13-r-rfm-f2-pE/pO-w0 (F4h, FEh at 0 waits) | 3 | the pre window: the fetch after a beaten fetch's delivery (a start or a pre clock on the delivery clock, the second byte latched) a clock later in silicon (FEh: F32 F36 / F35; F4h: X63 F67 F71 / F70) |
| F13-r-rfm-f3-pE-w1 (FFh, RFT 3) | 1 | the pre window exact; after clock 0 silicon F20 X24, candidate X20 F28 |

#### 7. Refuted on the way (measured, removed)

| alternative | pre cells | chain runs (fit.json, F8/F13/F17/F18 unless stated) |
| - | - | - |
| refresh_sync=wait (every beaten fetch delays the EU with it) | 29 of 42 with pop_refresh | -982 |
| the early run only through committed back-to-back fetches | 32 | -224 |
| the early run two fetches long (starts included) | 32 | -159 |
| no early sync for any ModR/M form | 27 | -629 |
| the take sync met on the beaten fetch's issue clock | 32 | -607 |
| the take sync not counting a request the IR's idle slot alone raised | 35 | -187 (+0): MOV CL,imm8 -> SHL AW,CL rows in the chain count it |
| room_ir=arrival (no idle IR slot anywhere) | 38 | -579 refresh-off |
| no idle IR slot while refresh is on / while class imm runs | 40 / 40 | -514 / -167 |
| refresh_lead closed only for the DW-form I/O (the marker's port form open) | (the 31 marker runs of section 6 right) | +1 -4 (F8 1, F17 3: port-form OUTs in the chain whose lead does hold the request) |

#### 8. Open, and why

* The marker OUT under a refresh-on prelude (47 runs): silicon serves a request that arrives inside the port-form OUT's
  I/O lead at once (FCh w0/w1) and starts the OUT during a refresh served a clock after its request (FDh w0); the chain's
  port-form OUTs with a request in the lead hold it (refresh_lead=closed; opening it for port forms loses 4 chain runs).
  No state separates them in the logs taken (ior.py: the lead count, the idle clocks before the request, the form).
* F4h and FEh at 0 waits (3 runs; 2 cells, 4 pre windows): the fetch a delivery raises right after a beaten fetch, with
  the second byte latched and no take or IR load on that clock, goes a clock later in silicon; the chain's rows of that
  state (dlf.py: on a beaten fetch's delivery clock, no take and no IR load) are right with the model's same-clock issue in 7 of
  9 (the 2 wrong: F8-out-st_bw-k4-pO-w0/w1). Not separated.
* FFh w1 (1 run): after clock 0, silicon's refresh 4 clocks after its request where the model serves it at once.
* So the stand-in tables (PRELUDE_COUNTER, SILICON_FILL) stay in fit.json. With the six rules the model derives both from
  its own run of the tail in all but these cells (section 6), and the pre window is in the lists for the next package.

#### Addendum (written after the simulator changes)

* Guard: all 23 families rescored under fit.json with the final code (sc31-all.txt) are byte-identical to sc30v.txt
  (cmp; tally.py sc30v.txt sc31-all.txt: gained 0, lost 0); endchk on fit.json: 17,822 runs, 0 model errors, no
  refresh-off END mismatch, 384 END mismatches (as the thirtieth fit). The six test modules: 349 pass (336 + 4
  test_analysis.PreWindowTests + 9 test_sim.PreludePopAnchor).
* The refresh-off reads: the three tests that assert a refresh-off run reads no refresh field caught the first
  version of refresh_run_modrm (read before the early-run test); the conditions are ordered so that refresh_run_modrm,
  refresh_reissue, refresh_sync_run and refresh_sync_reg are read only once a refresh beat a fetch, pop_refresh only
  with prelude_anchor=pop. room_ir_imm is a queue rule and is read by every run (neutral on all 17,822).
* Stage 8 from the wrapped hand fit (wp40/hand-wrap.json, the six enums in its list): no move (chosen {}), guard
  15,347 / 15,350, exact 2,084 / 2,472, matched 45,871; every WP40 enum ties at its alternative (exact 2,084, matched
  45,871: neutral under the stand-in prelude); knob dependence clean. Its fit.json is the hand fit with the new fields
  at their defaults (saved as build/.../fit/wp40/fit-wp40-stage8.json, stage8.json as wp40/stage8-wp40-out.json);
  fit.json restored from fit-wp39.json (= fit-wp39-hand.json) and stage8.json from its copy.
* knob_dependence (F8 F13 F17 F18; REFRESH_HOLD_INTS + mul.rexit, div.rexit): no integer's best value differs by parity,
  waits, k, marker, family or n, on the hand fit and on the candidate (with pop_exit added: clean too).
* Nothing adopted, so no fit-wp40-hand.json and no flip-back configs; the candidate's own flip-backs are in section 6.

### The prelude-tail candidate's 51 losses: the marker OUT's I/O lead and post under refresh, the data-latch wait, the FFh 1-wait counter, the beaten fetch's delivery at 0 waits (thirty-first fit, 2026-10-23)

Written 2026-10-23 from the recorded runs and the WP40 candidate's model state, before any simulator change. "The
candidate" is build/validation/v35s/chains/fit/wp40/fit-wp40-pop-candidate.json (prelude_anchor=pop, prelude_tail=segs,
pop_exit 4, refresh.POP_COUNTER, the six WP40 rules, wlatch_ir_at=start; 17,572 / 17,822, +192 -51 against fit.json's
sc31v.txt). Every tabulation is under the candidate, over the 2,472 runs of F8, F13, F17 and F18 (the refresh-on
families and their refresh-off cells) unless stated, with the pre window in the lists: the model's and silicon's events
from the POP PSW read on, clocks rel clock 0 (the fetch of 10046h / the chain's first word), and a row is counted only
when both lists agree on every event before the clock the row is about ("prefix matched"). q = a refresh request (the
counter's edge), X a refresh's first clock, F a fetch, I an I/O cycle, R the POP read. "Lead position" is setup - count
at the clock in question: an I/O form's I/O request has `lead` 2, so position 2 is the lead's first clock, 1 its last,
0 the issue clock.

Tools (scratchpad wp41/): sil.py (silicon's full list rel clock 0 per run -> sil.pkl), lib.py (hooked run, prefix
match), lead.py / leadan.py (every request pending in an I/O's lead), iorf.py (every refresh started while an I/O
request is posted), drop.py (every fetch request lost to a refresh, refresh_drop), lw.py (every request pending while
an I/O form waits for the data latch), rq.py / rqan.py (every request, the bus and EU at it), beat.py (every refresh
that beats a fetch request), dlf2.py / dlf3.py (every fetch on a word's delivery clock with a latched byte).

#### 0. The 51 losses (tally.py sc31v.txt sc31cand.txt)

| group | runs | cells |
| - | - | - |
| A | 31 | F18 A `a-out-fc-*` (the OUT 20h,AL marker after the FCh prelude): pE w0 8, pO w0 7, pO w1 8, pE w2 8 |
| B | 16 | F18 A `a-out-fd-*` (the OUT marker after the FDh prelude) at 0 waits, pE 8, pO 8 |
| C | 3 | F13-r-rfw-1-pE-w0 (F4h), F13-r-rfm-f2-pE-w0 and -pO-w0 (FEh) |
| D | 1 | F13-r-rfm-f3-pE-w1 (FFh, RFT 3) |

The FCh marker OUT's other cells (pE w1, pO w2, 16 runs) are inexact in both; they are the same two states as A.

#### A1. Every refresh request pending in an I/O's lead (lead.py; 348 prefix-matched requests)

Every one of them is raised inside the lead (none is pending at the lead's first clock from before it). Form: port =
OUT imm8,AL (the request posted after the port byte's take, `port` set); dw = OUT DW,AL, every one of them the END's,
posted with the EU in HALT (/H). Delays from q.

| form | lead position at q | runs | model (refresh_lead=closed): served at | silicon: served at | silicon I - X |
| - | - | - | - | - | - |
| dw /H | 1 | 169 | q+1 (the issue clock) | q+1 | 5 (3, 4 at RFW 0, 1) |
| dw /H | 2 | 112 | q+2 | q+2 | 5 (3, 4) |
| dw /H | 2 (q+3 / q+4: the issue moved by HALT's clocks) | 30 | q+3 / q+4 | the same | 5 |
| port | 1 | 4 | q+1 | q+1 | 5 |
| port | 2 | 33 | q+2 | **q** | 5 |

The port rows by run: position 1: F8-out-ld_bw-k4-pE-w0 (q 200, X201 I206), F17-s-n0-out-pE-w1 (q 130, X131 I136),
F17-s-n2-out-pE-w2 and F17-s-n3-out-pO-w2 (q 149, X150 I155), all right; position 2: F17-s-n1-out-pO-w0 (q 120: silicon
F115 X120 I125, model X122 I127) and the 32 F18 A FCh marker OUTs at 0 and 1 waits (pE w0 / pO w0: q 20, silicon F12 F15
X20 I25, model X22 I27; pE w1 / pO w1: q 23, silicon X23 I28, model X25 I30), all wrong. So:

* silicon serves a request raised on a port-form OUT's lead's first clock at once, and the I/O follows the refresh (I =
  X + its length); one raised on the lead's last clock waits for the issue clock (as refresh_lead=closed has it), 4 of 4;
* the DW-form END OUT in HALT holds a request on both lead clocks (281 of 281), as the twenty-fifth fit found;
* no other state at q separates the rows: room 0 or 1, nothing on the bus in every port row, the previous refresh
  13-15 clocks back or none, the first I/O after the prelude (the F18 marker) or not (the F17 S and F8 OUTs, the
  chain's second I/O), the port latch's relatch and the data-latch wait long past. The lead's first clock is open
  for a port form and closed for the DW form in HALT; the corpus has no DW-form I/O outside HALT with a request in its
  lead and no port form in HALT, so "port form" and "not halted" cannot be told apart here.
* This is WP40's "opening the lead for port forms loses 4 chain runs (F8 1, F17 3)": the 4 are exactly the position-1
  port rows; opening only the first clock leaves them.

#### A2. The FCh 2-wait marker OUT: a refresh on the port-form OUT's post clock (iorf.py, drop.py)

Every refresh the model starts on the clock a port-form OUT posts its I/O (its port byte's take), prefix matched to the
refresh's start (96 rows):

| the fetch request at the refresh's start | room | latched byte | runs | model = silicon up to the I/O |
| - | - | - | - | - |
| none raised | 1 | 1 | 2 | 2 |
| raised (not beaten: refresh_after not involved) | 2 | 0 / 1 | 28 / 1 | 27 / 1 (F8-out-empty-pO-w1 off later, at the I/O's count) |
| beaten (refresh_after: it runs after the refresh, with its pair, refresh_io_run) | 3 | 0 | 48 | 46 (F8-out-empty-pE-w1/-w2: a refresh before the I/O in the model, none in silicon) |
| beaten and lost (refresh_drop: odd room, the word's second byte latched) | 3 | 1 | 16 | **0** |

The 16 are F18 A FCh pE w2 and pO w2, all 8 chains each (rel clock 0): the OUT starts at 15 on the marker word's fetch
15-19, takes its port byte and posts on 20 with the word delivered and its second byte latched (room 3), q = 20, the
refresh 20-24. Silicon X20 F27 I32 (pO the same); the model X20 I29, no fetch before the I/O. 27 is the I/O's lead's
first clock in the model's own count (setup 11, count 4 on the post, the refresh's two wait states not counted, position
2 on 27): silicon runs one fetch there, as a fetch requested before the I/O's post runs on the lead's first clock
(io_hold=posted_b2b's lift, refresh_lift=free), and the I/O right after it (27 + 5). Not the beaten fetch's place
(refresh_after would run it on 25, ahead of the hold, with a pair: the 46 rows above) and not lost (the model: no fetch
until the next instruction start, refresh_lost=start).

Every request the model loses to a refresh (refresh_drop, 2,008 prefix-matched rows; drop.py), by what the EU holds:

| state at the refresh's start | runs | next fetch: model = silicon |
| - | - | - |
| no I/O request | 1,828 | 1,810 (the 18 off: F8 OUT/PUSH ld_bw and F13 C shlcl0 / F17 P mulu cells, the loss inside a unit's exec, not an I/O state) |
| a DW-form OUT's I/O request posted on its start clock (the END's OUT started on the refresh's clock) | 164 | 164 (silicon F at +7) |
| a port-form OUT's I/O request posted on this clock, after its port take (start + 5) | 16 | **0** (silicon +7 = the lead's first clock; model +12 / +18) |

So the only lost requests silicon does not lose are the 16 raised on a port form's post clock: there the request stays
up and is treated as one older than the I/O (it runs on the lead's first clock, not after the refresh).

#### B. The FDh 0-wait marker OUT: a refresh request while an I/O form waits for the data latch (lw.py, rq.py)

Every refresh request the model raises with a fetch in flight (rq.py; 9,000-odd prefix-matched requests): the model's
service clock equals silicon's in every row but 18, by the fetch's last clock against q and the next start (rqan.py).
16 of the 18 are B: q on the last clock of the last register load's fetch (F7-9 at 0 waits, q = 9), served by the model
on 10, by silicon on 11.

Every request pending on a clock an I/O form waits at its start for the data latch (wlatch: eu.latch_wait, the port
form's start held until the latch is free; lw.py) - 17 rows in the corpus:

| first such clock - q | latch free (wlatch_until) - that clock | runs | model serves | silicon serves |
| - | - | - | - | - |
| 1 | 1 | 16 (F18-a-out-fd-*-pE/pO-w0) | q+1 (on the wait) | q+2 (the wait's end) |
| 1 | 2 | 1 (F8-out-ld_bw-k4-pE-w2) | q+1 | q+3 (the wait's end) |

In all 17 silicon starts no refresh while the OUT waits for the data latch: the refresh goes on the first clock the
latch is free. B's run (F18-a-out-fd-empty-pE-w0, rel clock 0): the OUT's opcode in the IR from 7, its start held by the
latch (the last MOV AW,imm16's immediate) through 10; silicon F7 X11 F21 I24, the model F7 X10 F23 I26 (the refresh on
the latch wait, holding the OUT's start to 15). With the refresh on 11 the OUT starts on 11, on the refresh's first
clock, and silicon's I24 is the start + setup 11 + the refresh's 2 wait states, which refresh_io_pre=count leaves
uncounted for a refresh starting on the count's first clock (the I/O at 22 + 2). The fetches, the wlatch_hold rule
(no fetch while an I/O form waits for the latch), already wait so; the refresh does not (refresh_fetch / the free bus).
The other two of the 18 (F13-c-out-shlcl1-pO-w0, F13-c-out-shlcl8-pO-w0: q on a fetch's last clock, the OUT starting
next; silicon a clock later than the model) are inexact in both configurations and not in the 51.

#### C. The beaten fetch's delivery at 0 waits (dlf3.py; F4h and FEh pre windows)

Rel R (the POP read):

* FEh w0 (F13-r-rfm-f2-pE/pO-w0): MOV DS1,AW (8E, class reg) starts on 27 on the refresh 27-31 (q 26, L 5), which beats
  its fetch; F32 runs after it; on 35, F32's delivery (its second byte latched), the reg form's take sync is met (on the
  delivery, refresh_sync_reg=delivery) and MOV AW,imm16 starts there, no take and no IR load on 35. The model fetches on
  35, silicon on 36 (S: X27 F32 F36 F39 F42; M: X27 F32 F35 F39 F42); the train after it is the same until X91, then the
  model's fetches run 1-3 clocks early through clock 0 (S F96 F100 F103 F110 F113, M F96 F99 F102 F105 F114).
* F4h w0 (F13-r-rfw-1-pE-w0): the refresh 63-66 (L 4) beats the fetch of MOV AW,imm16's take; F67-69 after it; the next
  MOV r16,imm16 starts on 68 (an early-run start, refresh_sync=run: the last two clocks of the run's fetch), its take
  waiting for the word; on 70 the delivery (the word not latched: 5 stored), no take and no IR load. The model fetches
  on 70, silicon on 71 (S X63 F67 F71 F74 X78, M X63 F67 F70 F73 X78); from the F4h POP read the model then runs 2
  clocks late at clock 0.

Every fetch the model issues on a word's delivery clock with the second byte latched (and no back-to-back commitment),
the delivered word a beaten fetch's (it started on the clock after a refresh), prefix matched, by the EU on that clock
(7,079 rows; dlf3.py):

| start on t | take on t | IR load on t | class starting / running, the one before | runs | silicon fetches on t |
| - | - | - | - | - | - |
| yes | no | no | imm after imm | 838 (pre, 1-2 waits) | 838 |
| yes | no | no | imm after reg | 87 (chain, 1 wait) + 202 (pre, FCh/F8h 2 waits) | 289 |
| yes | no | no | imm after reg, **0 waits** | 2 (FEh pE w0, pO w0) | **0** (a clock later) |
| yes | no | yes | out / reg | 674 | 674 |
| no | no | no | imm | 68 | 68 |
| no / yes | yes | yes / no | (every class) | 3,208 | 3,208 |

The FEh rows are the only 0-wait rows of the "start, no take, no IR load" state after a register form. Every other row
of that state is at 1-2 waits; at 0 waits a fetch is 3 clocks and the class reg form's take sync met on its delivery
(refresh_sync_reg) puts the start on the delivery clock itself only here. The F4h row is not in the table (its word is
not latched); its state (an early-run start two clocks before the delivery, the take still waiting on it) has no other
prefix-matched row with a fetch on the delivery clock. No logged state separates C from the right rows except the wait
setting with the previous class, which is not a model state; open.

#### D. FFh at 1 wait: the request on the chain's first instruction start (beat.py)

F13-r-rfm-f3-pE-w1 (RFM FFh: RFT 3, a 128-clock interval; RFW 3, 5 clocks): POP_COUNTER (FFh, 1) = 80 puts the first
request after clock 0 on 20 (rel clock 0), where the chain's first instruction starts, loads the IR and the fetch F16's
word is delivered (room 2, a fetch request raised on 20). The model serves the refresh on 20 (X20 F28 F32); silicon runs
the fetch on 20 and the refresh after it (F20 X24 F31).

Every refresh the model starts while a fetch is wanted, request and fetch request both raised on the refresh's clock,
an instruction start, an IR load and a delivery on it, no take (beat.py): 269 rows, silicon has the refresh on t in
268; the FFh row is the only exception. So the model's arbitration is right in that state and the FFh row says the
request is not on 20 in silicon. The same run's second request (q + 128 = 148): silicon X149, the model X148; the pO
twin (F13-r-rfm-f3-pO-w1, inexact in both): silicon X23 ... X150, the model X20 ... X149. Both runs' refreshes are one
clock or more after the model's requests at both intervals, consistent with the request on 21 / 149 (the counter one
lower at the POP read: 79), and with nothing else. FFh at 1 wait has no refresh in its pre window (the window,
R..R+92, lies between two requests 128 apart), so POP_COUNTER (FFh, 1) was not read off the window but carried over
from PRELUDE_COUNTER (44) and the POP read's clock (-92): it is the one entry of the table the pre window does not pin.

#### Addendum (written after the simulator changes; refresh dumps of F8, F13, F17, F18 by wp40/rr.py, 2,472 runs, then the official score over all 17,822)

##### Corrections and later reads

* A1: the previous refresh in the port rows is 13-16 clocks back (F17-s-n2/-n3-out at 2 waits: 16), not 13-15.
* C, re-read: the first tabulation compared the lists rel clock 0, and F4h at 0 waits has the model's clock 0 two clocks
  late against its POP read (the divergence is in the window), so its rows failed the prefix match. With both lists
  rebased to their POP read (lib.prefix) the F4h runs join the FEh ones: the first divergence in all four (F4h, FEh, both
  parities) is the same clock, rel R silicon F32 F36 F39 / model F32 F35 F39, the same state (a refresh beat the fetch
  of a register form started on the refresh's first clock; MOV AW,imm16 starts on that fetch's delivery 35, its second
  byte latched, no take, no IR load). The prefix-matched rows of the state, by the beaten fetch's length: 3 clocks
  (0 waits) 4 rows, all a clock late in silicon; 4 or 5 clocks (1-2 waits) 1,197 rows, all on the delivery clock. After
  the rule the second occurrence in each run is in the state too: F4h rel R X63 F67 F71 (an early-run start on 68),
  FEh after clock 0 X91 F96 F100, both a clock late in silicon, both now the model's.
* C, the alternative refuted first: refresh_sync_reg met early on the run's first fetch and on its delivery only for
  the second ("second", the FCh 0-wait rule's own case): the three runs exact, the pre windows wrong in all four
  (the model a clock early from 35 on: F35 F38 F41), the chain scoring the shift by luck. Removed.
* D: POP_COUNTER (FFh, 1) = 79 makes both FFh 1-wait runs exact (pE: F20 X24 ... X149; pO: X23 ... X150, inexact in
  both fit.json and the candidate before); every other refresh-on run is unchanged by the entry.

##### Adopted (each an enum in sim/config.py, default the old model; tests in `test_sim.RefreshPreludeTailLosses`)

| enum | values (default first) | named run (rel clock 0 unless stated): silicon / the alternative | flip-back from the final fit (all 17,822) |
| - | - | - | - |
| refresh_lead_port | lead / last | F18-a-out-fc-empty-pE-w0: X20 I25 / X22 I27 | -32 (F17 1, F18 31) |
| refresh_drop_post | drop / hold | F18-a-out-fc-empty-pE-w2: X20 F27 I32 / X20 I29 | -15 (F18) |
| refresh_wlatch | free / hold | F18-a-out-fd-empty-pE-w0: F7 X11 F21 I24 / F7 X10 F23 I26 | -17 (F8 1, F18 16) |
| refresh_beat_t4 | none / t4 | F13-r-rfm-f2-pE-w0, rel R: X27 F32 F36 F39 / X27 F32 F35 F39 | -4 (F13) |
| POP_COUNTER (FFh, 1) | 80 / 79 (a table entry, not an enum) | F13-r-rfm-f3-pE-w1: F20 X24 / X20 F28 | -2 (F13) |

The WP40 rules and the anchor, flipped back alone from the final fit: prelude_tail=standin -209 (the stand-in tables
read again: F8 9, F13 142, F17 19, F18 39), prelude_anchor=clock0 -36 (F13 4, F18 32), wlatch_ir_at=busy -3,006 (every refresh-off
family, the first divergence after clock 0 in the chain, e.g. F3-out-empty-pE-w0 silicon F184, flipped F182 rel
clock 0, 210 of F3's 840; under the stand-in the two tie, as WP40 found: the chain's start state is the tail's own
under prelude_anchor=pop; not read further), pop_refresh=none -7, refresh_reissue=clear -237, refresh_run_modrm=early -229,
refresh_sync_run=all -34, room_ir_imm=idle -205, refresh_sync_reg=early -0 (the chain does not see it; 200 pre
windows wrong, every FCh/F8h 0-wait run: kept on the pre window). No flip-back gains a run.

##### Refuted on the way (measured on the refresh dumps from the final rules, then removed)

| alternative | against the final rules |
| - | - |
| the whole lead open for a port form (refresh_lead_port without the last-clock hold) | -5 (F8 2, F17 3: the position-1 rows) |
| the lead's first clock open for every form (the DW form in HALT too) | -78 |
| refresh_drop_post for the DW form's post on its own start clock too | -167 |
| refresh_beat_t4 for a beaten fetch of any length | -226 (pre 2,200 of 2,472) |
| refresh_beat_t4 for any fetch right after a refresh (beaten or not) | -0, 2 pre windows wrong (F4h at 0 waits: X45 F49 F52, a refresh that beat nothing) |
| refresh_beat_t4 as a plain hold (the request re-evaluated on the next clock, not committed) | the request lapses (room 1 once the latched byte is in): F39 for F36; the three C runs still lost, 4 pre windows wrong |
| refresh_sync_reg=second (above) | +3 -0 in the chain, 4 pre windows wrong |

##### The gate (fit-wp41-hand.json = fit.json)

| | sc31v (fit-wp40.json = the thirtieth fit) | the WP40 candidate | final |
| - | - | - | - |
| exact, all 17,822 | 17,431 | 17,572 (+192 -51) | 17,642 (+211 -0) |
| F8 / F13 / F17 / F18 | 19 / 242 / 729 / 1094 | 28 / 378 / 748 / 1071 | 29 / 384 / 749 / 1133 |
| every other family | unchanged | unchanged | unchanged (F5 837/840 as before) |
| pre window exact (all 17,822; refresh off 15,680) | 0 | 17,818 (15,680) | 17,822 (15,680); all 42 refresh-on prelude cells |
| refresh-on first divergence (fdall41): exact / first LS / X / END | 1,754 / 208 / 162 / 18 | 1,895 / 68 / 157 / 22 | 1,965 / 0 / 154 / 23 |
| endchk: model errors / refresh-off END mismatches / END mismatches | 0 / 0 / 384 | | 0 / 0 / 175 |
| stand-in tables read (PRELUDE_COUNTER, SILICON_FILL) | yes | no | no |

tally.py sc31v.txt sc32-all.txt: gained 211 (F8 10, F13 142, F17 20, F18 39), lost 0. The fit.json rescore with the
final code (sc32v.txt) is byte-identical to sc31v.txt. The six test modules: 356 pass (349 + 7).

##### Found after the adoption: the overfill test (test_fit.FittedConfig.test_fit_json_never_overfills)

The first version of refresh_lead_port let the refresh start on a port form's lead's first clock whatever the bus
unit would run there. On the generated F13-c-out-shlcl12-pO-w2 at timer phase 0 (Machine without the run's anchor;
the recorded run's phase does not do it) a fetch older than the I/O is waiting there, the one io_hold=posted_b2b's lift
lets run on the lead's first clock: the refresh beat it, the beaten fetch ran after the refresh with its pair
(refresh_io_run) and the queue held 7 bytes at 359. No corpus row has such a fetch (all 33 of A1's position-2 rows
have room 0 or 1 and nothing requested), so the rule now leaves that clock to the older fetch, as before, and serves the
refresh there only when no fetch would run: every one of the 17,822 runs' exact / first divergence / pre window is the
same under both versions (rr.py), the overfill test passes, and a test in RefreshPreludeTailLosses runs that chain
(it fails with the first version). All the checks above (guard rescore, score, --pre, tally, endchk, tests) were
redone with the final code; the numbers are unchanged.

##### Flip-backs, stage 8, knob dependence (final code, fit-wp41-hand.json = fit.json)

* Every flip-back above was re-scored with the final code (build/.../fit/wp41/fl-<key>=<old>.json, scores
  wp41/sc-fl-*.txt against sc32-all.txt); the numbers in the tables are those (only prelude_anchor=clock0 moved, -43 to
  -36, with the lead's older-fetch exception). No flip-back gains a run.
* Stage 8 from the wrapped hand fit (wp41/hand-wrap.json; the four WP41 enums in its list, REFRESH_SEED carrying the
  adopted WP40 and WP41 values): no move (chosen {}), guard 15,347 / 15,350, exact 2,295 / 2,472, matched 50,358 /
  52,828. Ties at the chosen configuration: refresh_timer start / end, refresh_exec every2 / every2_early,
  refresh_enable start, refresh_recent_by clocks, refresh_eve both, refresh_wbsync wait, refresh_io_pre waits,
  refresh_sync_reg early (200 refresh-on pre windows wrong, which stage 8 does not rank), wlatch_ir_at busy (stage 8's
  families only: -3,006 in the others). Its fit.json is the hand fit byte for byte (saved as fit-wp41-stage8.json, its
  stage8.json as wp41/stage8-wp41-out.json); the thirtieth fit's stage files and seeds are in wp40b/.
* knob_dependence (F8 F13 F17 F18; REFRESH_HOLD_INTS + mul.rexit, div.rexit, pop_exit; wp41/knob41.py): no integer's best
  value differs by parity, waits, k, marker, family or n.

##### Open

* 180 runs inexact (F5 3, F8 19, F13 78, F17 49, F18 31; refresh off: the 3 F5 runs as before). Of the 177 refresh-on
  ones none diverges in the first LS any more: 154 in X (F13 C 63, F17 P 20, F8 OUT 14, F18 B prefix 13, F13 U 12, F18 B
  10, F17 S 7, F17 C 5, F17 W 4, F8 PUSH 4, F18 A 1, F18 AC 1), 23 in the END block (F17 W 8, F13 C 3, F17 C 2, F17 P 2,
  F18 A 2, F18 B 2, F18 B prefix 2, F17 S 1, F8 PUSH 1); these are the thirtieth fit's open X / END states (finding 8 b,
  d, the register shifts' remainder, the END's MOV DW take), not read here.
* refresh_lead_port keys the lead on the I/O form: the corpus has no DW-form I/O outside HALT and no port form in HALT
  with a request in its lead, so "port form" and "the EU not halted" are one state here.
* refresh_beat_t4 is a 3-clock fetch's property (no wait state); the corpus has its state only at 0 waits in the F4h and
  FEh preludes (4 prefix-matched rows, 2 more after the rule) against 1,197 at 1-2 waits.
* POP_COUNTER (FFh, 1) rests on two runs' refreshes after clock 0 (the window has none).

### The immediate forms' post against the fetch run: item 1's three runs, TEST [BW+d16],imm16, the one-byte immediate on the delivery clock (F22, thirty-second fit, 2026-10-23)

Written 2026-10-23 from the recorded runs and the thirty-first fit's model state (fit.json, 17642/17822 on F0-F21;
F22 1068/1320 under it, scratchpad/sc-F22.txt), before any change to the simulator. Clocks rel t_fill unless written s+n
(s = the instruction's start in the model, right wherever the earlier events match) or t+n (t = the clock of the
decision tabulated). Only decisions with every earlier event matching silicon are counted ("prefix matched").

F22 (chains-F22-w0, chains-F22-w1; families.py `f22`, forms.py's F22 block): 1,320 runs, 660 per wait setting (0 and 1
waits only; 2 waits not generated), all `complete` and `passed`, no refresh (RFM ECh), 66 repeats per wait setting, every
one identical to its first trace up to a constant tick shift. `PAD LS M0 L X^k M1 LS END` under the PUSH and OUT markers
and the marker-less `PAD LS L X^k LS END`, k = 1, 2, both parities, the lead-in L of F21 (none, NOP, NOP NOP, NOP NOP
NOP, ES: NOP), X one of eleven immediate memory forms: the immediate RMW `ADD r/m,imm16` (81 /0) at [BW+200h]
(`add_d16`, 81 87 00 02 ii ii), [BW+10h] (`add_d8`, 81 47 10 ii ii), [BW] (`add_bw`, 81 07 ii ii) and [0C00h]
(`add_dir`, 81 06 00 0C ii ii); `ADD [BW+200h],imm8` (`add8_d16`, 83 87 00 02 ii); the left-out write `CMP
[BW+200h],imm16` (`cmp_d16`, 81 BF 00 02 ii ii); `TEST [BW+200h],imm16` (`test_d16`, F7 87 00 02 ii ii); and the
immediate store `MOV r/m,imm16` (C7 /0) in the same four modes (`sti_d16`, `sti_d8`, `sti_bw`, `sti_dir`), the controls.
Each form has 60 cells per wait setting (3 frames x 5 leads x 2 k x 2 parities). Ids
`F22-<push|out|none>-<l0|n1|n2|n3|es>-<form>[-k2]-p<E|O>-w<0|1>`.

Tools (scratchpad wp43/): tr.py (one run's per-clock model state with the clocks corrected to t_fill; `sim --trace`
prints machine clocks against the normalised t_fill, so its "rel" column is off by the prelude's length); lad.py (every
immediate-form instance: start, takes, post, the request's count per clock, both event lists) and view.py / pair.py /
ttab.py / miss.py over it; steps.py (templates.steps() of every F22 form and its F19/F14 analogues under fit.json);
dec.py / dtab.py (every clock a memory data request is issuable on a free bus with a fetch wanted, with the request's
count history, the delivery-clock and fetch-run flags and silicon's event on that clock); fiss.py / ftab.py (every fetch
issued while an immediate form's request is posted and not issued, with the request's state and the gap between that
fetch's end and the next data cycle in both).

#### 0. The templates

templates.steps() for the five forms added for F22 (`add_m_imm_d8`, `add_m_imm_dir`, `add_m_imm8_d16`, `cmp_m_imm_d16`,
`test_m_imm_d16`) is the template of the exact `add_m_imm` / `cmp_m_imm` / `cmp_m_imm8` / `test_m_imm` ([BW]) with the
displacement take added exactly as in the immediate store's displaced forms (`('take', 1, 'chain')`, the EA clocks,
`('take', 2, 'word')` or `('take', 1)`), then the same post: 81 /0 and 81 /7 `('post', 'read', ea, 2, 3, 1, True)`, 83
/0 setup 2 (`grp1`), F7 /0 setup 6 free 5 (`grp_fixed=test`). Two differences from the store's displaced template: the
RMW has no `dadd` clock between the displacement's take and the post (`store_imm.dadd` 1, `rmw_imm.dadd` absent = 0);
and F7 /0, a group opcode, gets no fixed lookup between its ModR/M and its displacement (`fixed_lookup=decoder_nowait`
applies only to `fixed and not op.group`, TEST 84/85). No template is wrong otherwise.

#### 1. The ladder

| form | cells / wait | exact w0 / w1 (fit.json) | silicon through the first data cycle against the `sti_*` twin in the same cell and mode (pair.py) |
| --- | --- | --- | --- |
| `sti_d16`, `sti_d8`, `sti_bw`, `sti_dir` | 60 | 60/60 each, both waits | the controls |
| `add_bw` (81 07) | 60 | 60 / 60 | identical event for event to `sti_bw` in 60 of 60 cells at each wait |
| `add_d16` (81 87) | 60 | 31 / 60 | identical to `sti_d16` in 60 of 60 at each wait |
| `add_dir` (81 06) | 60 | 31 / 60 | identical to `sti_dir` 60 of 60 at each wait |
| `add_d8` (81 47) | 60 | 60 / 42 | identical to `sti_d8` 60 of 60 at each wait |
| `cmp_d16` (81 BF, left-out write) | 60 | 32 / 60 | identical to `sti_d16` 60 of 60 at each wait |
| `add8_d16` (83 87) | 60 | 34 / 52 | the first data cycle one clock before the twin's write in 60 of 60 at w0 and 52 of 60 at w1 (s+6 against s+7 with no fetch in the head, the one-byte immediate's count floor) |
| `test_d16` (F7 87) | 60 | 3 / 3 | a different head: see section 4 |

The `@n` kind/address mismatches and the residuals (miss.py, every one prefix matched up to the mismatch):

| form | wait | first divergence | cells |
| --- | --- | --- | --- |
| `add_d16`, `add_dir`, `cmp_d16` | 0 | **a fetch at s+6 the model has and silicon lacks**: silicon reads at s+7 with no cycle at s+6, the model fetches at s+6 (the delivery clock of the displacement's fetch at s+3) and reads at s+9 | 24 each (X at odd alignment, no fetch at s: the fetch at s+3 is not a run) |
| `add_d16`, `add_dir`, `cmp_d16` | 0 | the read one clock late in silicon, s+10 against s+9, after the fetch at s+6 (item 1's state, section 2) | 5, 5, 4 (X odd with a fetch at s: the fetch at s+3 is a run) |
| `add_d8` | 1 | the read one clock late in silicon, s+8 against s+7 | 18 (a fetch at s, the d8 taken on its delivery at s+4, no fetch between it and the read) |
| `add8_d16` | 0 / 1 | **a read on a delivery clock where the model fetches**: silicon reads at s+6 (w0) / s+7 (w1), the model fetches there | 24+2 / 6+2 (section 3) |
| `test_d16` | 0 / 1 | the displacement's fetch later in silicon, s+5 or s+6 against s+3 (or s+7 against s+4 at w1), or that fetch missing | 57 / 57 (section 4) |

So the kind mismatches are not a template fault, not a second read, not a write at the wrong address and not the group
setup's clocks: in the RMW forms they are one extra model fetch at the request's free clocks' eve (the store's
`free_hold` state, which the store twin passes), and in TEST a late displacement.

#### 2. The RMW's read is the store's write (item 1)

| Fact | Evidence (clocks rel t_fill) |
| --- | --- |
| 2a. Through its first data cycle the immediate RMW (81 /0 in all four modes) and the left-out write (81 /7 at [BW+200h]) run exactly as the immediate store in the same mode, cell and wait: every fetch, the data cycle's clock, the fetch after it. 600 of 600 cells (5 forms x 60 x 2 waits); no cell separates a read from a write | pair.py; `F22-none-l0-add_d16-pO-w0` F75 R79 F82 against `-sti_d16-pO-w0` F75 W79 F82 (model F75 F78 R81); `F22-none-n1-add_d8-pE-w1` F72 F76 R84 against `-sti_d8-` W84 (model R83); `F22-none-n1-cmp_d16-pE-w0` F72 F79 R83 = `-sti_d16-` W83 (model F82 R85) |
| 2b. The model posts the RMW's read one clock before the store's write: the store spends `store_imm.dadd` 1 EU clock after its displacement's take, the RMW none. In the 0-wait cells without a fetch run the read therefore reaches count 3 of 3 (setup done, the s+7 floor still ahead) on the delivery clock s+6, where the store is at count 2 of 3, its free clocks' eve, and `free_hold` holds the delivery fetch; the RMW's read is past that state, the fetch goes | `F22-none-l0-add_d16-pO-w0` lad.py: post 76, counts 76/77/78 = 1/2/3, fetch 78 (the request floored to 79); `-sti_d16-pO-w0` post 77, 77/78 = 1/2 (eve at 78, held), W79 |
| 2c. Item 1's counted state (posted 2 clocks before a fetch run's delivery clock, counted on the post clock and on the fetch's last clock, issuable but for the s+7 floor on the delivery clock where the run's fetch goes first) holds, prefix matched, in **17 cells**, all an immediate RMW's read at 0 waits: the three F5 runs and 14 F22 cells (`add_d16`, `add_dir` and `cmp_d16` under PUSH l0 pE and OUT n1 pE at k = 1 and 2, and the second instance of `add_d16` and `add_dir` under OUT l0 pO k = 2); silicon idles one clock after that fetch in all 17 (the read 4 after the fetch's issue, the model 3). No immediate store is in that state at 0 waits: with its `dadd` clock it is a clock later, at count 2 of 3 on the fetch's last clock (86 cells: `free_idle`'s state, idle in silicon and model). The reads and stores in that counted state at 1 and 2 waits (the post on a wait state; 50 reads, 163 stores at a run's delivery clock) idle in neither | fiss.py/ftab.py on fit.json: `read rmw_imm w0 ... cnt 3/3 floor run sil+1 mod+0` 17; `write store_imm w0 B3 cnt 2/3 floor run sil+1 mod+1` 86; `F5-push-add_m_imm_d16-k1-pE-w0` F87 R91 (model R90); `F22-push-l0-add_d16-pE-w0` F81 F84 F87 R91; `F5-push-st_imm_bw_d16-k1-pE-w1` exact |
| 2d. So the kind of request is not the state: the read was posted a clock early. Posted where the store's write is (the RMW's displaced forms taking the store's `dadd` clock), every RMW and left-out-write cell of section 1 except 83 /0 lands in a state the store already passes: the 17 in `free_idle`'s state (idle clock, both), the 72 non-run 0-wait cells in `free_hold`'s (the delivery fetch held, read at s+7), the 18 1-wait `add_d8` cells one clock later (R s+8). TEST d16 and the 83 /0 form are not closed by it (sections 3, 4) | config probe dadd1.json (`rmw_imm.dadd` 1, nothing else): F22 1172/1320 (`add_d16`, `add_dir`, `add_d8`, `cmp_d16` 120/120 each), F5 840/840 (the three runs), F19 1290/1290, F21 3576/3576 |

#### 3. The one-byte immediate (83 /0) on the delivery clock

With the read posted where the store's would be (the 2d probe) every `add8_d16` miss is one decision: the read's
setup (2, `grp1`) completes on a delivery clock t = s+6 (w0) or s+7 (w1) on which the fetch request is raised too, and
`arbiter=b2b` runs the fetch first (both became pending on t). dec.py, prefix matched up to t, every F22 `add8_d16`
cell in that state:

| wait | the request's count, t-2 / t-1 / t | the fetch that ended at t-1 | silicon on t | cells |
| --- | --- | --- | --- | --- |
| 0 | post / 1 / 2 | not a run (no fetch at s) | **read** | 24 (+2 after the OUT marker's I/O, pO) |
| 0 | post / 1 / 2 | a run (a fetch at s, the displacement's at s+3 on its delivery) | fetch, read at t+3 (no idle clock) | 19 |
| 1 | 1 (W) / 1 (B3: the fetch-free clock not counted, a fetch in flight) / 2 | not a run | **read** | 6 (+2 after the I/O, pO) |
| 1 | 1 / 1 / 2 | a run | fetch | 19 |
| 0 / 1 | after the marker's I/O and recovery | not a run, pE | fetch | 2 / 2 |

| Fact | Evidence |
| --- | --- |
| 3a. In the same cell, with the same queue (5 bytes, room 1 after the delivery), the same fetches and the same request state on t (issuable, both pending on t), silicon reads first for 83 /0 and fetches first for 81 /0 and C7 /0 at 1 wait; what differs is the request's count history (83's fetch-free clock not counted on the fetch's last clock; 81's counting its second, non-free clock there) and the immediate's width | `F22-push-n3-add8_d16-pO-w1` F97 R101 F105 (model F101 R105); `F22-push-n3-add_d16-pO-w1` F97 F101 R105 (exact); `F22-none-l0-add8_d16-pO-w0` F75 R78 (model F75 F78 R81) |
| 3b. At 0 waits the 83 /0 read wins on t whenever the displacement's fetch was not itself a run (24 of 24), and loses whenever it was (19 of 19); the 1-wait cells split the same way (6 / 19). The 81 /0 and C7 /0 requests issuable on a 1-wait delivery clock lose whether or not the fetch was a run (38 non-run, 169 run) | dec-dadd1.jsonl, dtab.py `both_now` |
| 3c. No older issuable data request (ready before t) meets a fetch run's delivery-clock request anywhere in the prefix-matched corpus (dtab.py `other`, delivery and run both set: none), so whether a run's delivery fetch beats a request older than itself is not observed outside these cells | dtab.py |

#### 4. TEST [BW+200h],imm16 (F7 87 d16)

Silicon, first instance, prefix matched (ttab.py; "fetch at s" = a fetch issued on the start clock):

| wait | X | fetch at s | silicon | model (fit.json) | cells |
| --- | --- | --- | --- | --- | --- |
| 0 | even (the ModR/M and d16 in two whole words) | yes | F s, **F s+6**, R s+10 | F s, F s+3, R s+10 | 12 |
| 0 | even | no | **F s+5**, R s+9 | F s+3, R s+10 | 2 (ES: NOP) |
| 0 | odd (the d16 straddles) | no | **F s+5**, R s+9 | F s+3, F s+6, R s+10 | 12 |
| 1 | even | yes | F s, **F s+7**, R s+11 | F s, s+4, R s+12 | 7 |
| 1 | even | no | **F s+5**, R s+9 | F s+3, R s+11 | 7 |
| 1 | odd | yes | F s, **no displacement fetch**, R s+11 | F s, s+4, R s+12 | 9 |
| 0 / 1 | odd | back to back (F s, s+3 or s+4, ...) | exact | exact | 2 / 2 |
| 0 / 1 | either, OUT l0 (the start behind the marker's I/O) | | pE exact, pO the displacement's fetch 3 later (s+11 against s+8) | | 2 / 2 |
| 1 | odd | no | **F s+5, F s+9**, R s+13 | F s+3, s+7, R s+11 | 3 |

| Fact | Evidence |
| --- | --- |
| 4a. TEST r/m,imm16 with a displacement takes its displacement 2 clocks later than every other form's s+3: its first fetch after the start (the room the take frees) is at s+5 with no fetch on the start clock, s+6 with one, at both waits and both alignments. These are TEST [0C00h],AW's (85 06) clocks exactly: the fixed operation's lookup between the ModR/M and the displacement (`fixed_lookup=decoder_nowait`, `fdisp` 3) and its extra clock after a start-clock fetch (`lookup_start`). The group opcode F7 does not get that lookup in the model | `F22-none-l0-test_d16-pO-w0` F77 R81 (s 72; model F75 F78 R82); `-pE-w0` F72 F78 R82 (model F72 F75 R82); `F14-t-push-test_dir_aw-pO-w0` F81 F87 R90 (s 81, fetch at s: s+6); `F14-t-push-test_dir_aw-k2-pE-w0` the second TEST at 95 with no fetch, F100 R103 (s+5) |
| 4b. Its read keeps TEST [BW],imm16's clocks: s+9 with no fetch on the start clock, s+10 with one (F7 07: `F15-a-none-test_bw_imm-pO-w0` R s+9, `-pE-w0` F s R s+10, `fixed_floor`); in every 0-wait cell the read is 4 after the displacement's fetch where 85 06 reads 3 after it | `F22-none-l0-test_d16-pO-w0` F77 R81; `F22-push-l0-test_d16-pO-w0` F81 F87 R91; 85 06 F87 R90 |
| 4c. At 1 wait with no fetch on the start clock the read is still at s+9 (the count floor counting wait states, as F19's); with a start-clock fetch at odd alignment no displacement fetch runs before the read (R s+11) and at even alignment one does (F s+7, R s+11) | `F22-none-n2-test_d16-pE-w1` F85 R89 (s 80); `F22-none-n1-test_d16-pE-w1` F72 F76 R87 (s 76); `F22-none-l0-test_d16-pE-w1` F72 F79 R83 |
| 4d. The three exact cells are the back-to-back heads (`F22-push-l0-test_d16-pE-w0`, `-out-n1-...-pE-w0`, `-out-l0-...-pE-w0`): fetches at s, s+3, s+6 whatever the take does | ttab.py |

#### 5. `add_d8` at 1 wait

| Fact | Evidence |
| --- | --- |
| 5a. The 18 cells (push n1 pO, n2 pE, es pE; out n2 pO, n3 pE, es pO; none n1 pE, n2 pO, es pO; k = 1 and 2) are those with a fetch on the start clock, the d8 taken on its delivery at s+4 and no other fetch before the read: silicon reads at s+8, the store twin writes at s+8, the model reads at s+7 (its floor, posted at s+4 with no `dadd`). `add_d16` in the same cells has a second fetch (the d16 frees a word) and the read waits for it (s+8 both); `sti_d8` gets its s+8 from `dadd`. It is 2b at 1 wait | `F22-none-n1-add_d8-pE-w1` F72 F76 R84 W92 (model R83 W91); `F22-none-n1-sti_d8-pE-w1` F72 F76 W84; `F22-none-n1-add_d16-pE-w1` F72 F76 F80 R84 |

#### Addendum, read off during the rule work (after the facts above were written)

All scores over the 19,142 runs of the 23 families; F0-F21 against sc33v.txt (tally.py), F22 against sc-F22.txt
(wp43/t22.py, F22's four-column rows; tally.py does not read them). "+n -m" = runs gained / lost. Adopted rules are in
sim/config.py with the old option as DEFAULT and tests in `test_sim.ImmediateFormsPostAgainstTheRun`; every other
prototype below is removed from the code.

| Fact | Evidence (clocks rel t_fill) |
| --- | --- |
| A1. `rmw_imm.dadd` 1 (the immediate store's EU clock after the displacement's take, given to the immediate RMW, an integer of its class; read only by its displaced forms, so `add_bw`/F19/F15's [BW] forms are untouched): F0-F21 +3 -0 (the three F5 runs), F22 +104; F19 1290/1290 and F21 3576/3576 unchanged. TEST d16 runs under `rmw_imm` too and takes it | sc-dadd1.txt; `F5-push-add_m_imm_d16-k1-pE-w0` F87 R91 |
| A2. TEST r/m,imm16 with a displacement: the fixed lookup in the decoder (`fixed_lookup=decoder_nowait`'s `nowait` fdisp 3 step and `lookup_start`) put on F7 /0 puts every fetch on silicon's clock; the read then needs only its group's own setup (`rmw_imm` grp 3 / grp_free 1): with the request left at `grp_fixed=test`'s 6/5 the read is 1-2 late (F22 -1 against A1 alone), with the lookup's 3 clocks taken from it (3 free 3, or 3 free 2) +21 / +51, with the group's own +108 (test_d16 114/120). Adopted as `fixed_lookup_grp=group` | lg_*.json probes; `F22-none-l0-test_d16-pO-w0` F77 R81 |
| A3. The one-byte immediate on the delivery clock: with the read first whenever 83 /0's request is issuable on the delivery clock of a fetch that was not a run's: F22 +34 -4, the 4 the OUT l0 pE cells (the request issuable behind the marker's I/O with 3 bytes counted, silicon F87 F90 R93, the fetch first); with the condition that the queue counts more than `hold_q` 3 bytes (every one of the 34 has 4, the 4 have 3): +34 -0. For every form's read or write (not only the one-byte immediate's) with that condition: +34 -102 (F22 50 and F5/F19/F21 52, the 1-wait immediate stores and RMWs at a non-run delivery fetch first, 3a). Adopted as `imm1_first=hold`: keyed on the immediate's width (a format property; the 83 /x and C6 /0 forms' one-clock-shorter group setup, `grp1` 2), and no other form reaches the state, so it is constrained by these 38 cells alone (34 + the 4) | sc-p3.txt, sc-p3q.txt, sc-p3all.txt |
| A4. A fetch started on the clock after an I/O cycle's last clock counted as a run's for `free_hold`/`free_idle` (the OUT l0 pE TEST cells fetch at the eve and idle as a run's would): F0-F21 -26, F22 -22 against the hand fit. Refuted, removed | sc-p4.txt |
| A5. Refuted integer probes: `rmw_imm.grp1` 1 (F15 830/840, F19 1248/1290) and 3 (F15 824, F19 1232, F22 -34 against A1) | g1_1.json, g1_3.json |
| A6. Combined, fit-wp43-hand.json = fit-wp41-hand.json + A1 + A2 + A3 (fit.json): F0-F21 +3 -0 (17645/17822: F5 840/840; refresh-off misses outside F8: none), F22 1068 -> 1314/1320 (+247 -1). Flip-backs on it: `rmw_imm.dadd`=0 -3 (F5) -179 (F22); `fixed_lookup_grp`=none -109 +1 (F22); `imm1_first`=none -34 (F22). endchk with F22 added: no refresh-off END mismatch, no model error (175 refresh-on END mismatches, the same as fit-wp41.json's) | sc34-all.txt, wp43/sc-fl-*.txt, endchk |
| A7. The one F22 run lost, `F22-out-l0-test_d16-pE-w0`, was exact by a wrong head: without the lookup the d16 left at s+3 (83) before the marker's I/O and the 6-clock setup ran 89-94; with it the d16 leaves at s+5 (85) on the I/O's second clock and the read reaches its eve on 90, the delivery of the fetch run right after the I/O (87), where `free_hold` holds the fetch (F91, model) and silicon runs it (F90 R94, the idle clock after). It is one of the 6 open OUT l0 TEST cells below | tr.py |
| A8. Open, 6 runs, TEST [BW+200h],imm16 directly after the OUT marker (`F22-out-l0-test_d16-{pE-w0, pO-w0, pO-w1}`, k = 1 and 2; pE-w0 k = 1 the lost run, k = 2 already missed): at pO the displacement is taken on the marker I/O's issue clock (85 / 86) and the fetch requested there waits 2 clocks past the recovery (silicon F91 R95 at w0, F92 F96 R100 at w1; model F89 R93, F90 F94 R98): `grp_io_hold`'s hold through the request's non-free group clocks too, which it applies today only when the next setup clock is a free group clock (TEST [0C00h],AW's one-clock setup). At pE (the take on the I/O's second clock) the fetch right after the I/O is not held at the eve (A7). Two rules for these 6 cells alone; the second refuted in its general form (A4) | tr.py |

### The fitter's stage 6 under the family guard: no move, the arbitrary tie picks, the memory failure (2026-10-24 to 2026-10-26)

Stage 6 (F6, F10, F12 A, F14 O, F15 O, F16 L, F19 D, F20: 5,712 runs,
every other recorded run the guard, 10,526) was run from the
thirty-second hand fit through its eleven grids and the sweep. No grid
gained an exact run: every grid's best start was the fit itself
(5,712/5,712 on the stage's families, the guard 10,520/10,526
throughout, the six misses the F22 `TEST [BW+200h],imm16` runs), the
sweep's 213 alternatives made no move (6 descended with their integers)
and polish none. Three grids nevertheless wrote a different value into
their output on a tie: IO_REVISIT `io_post=take` with `port_sync=sync`,
OUT_REVISIT `wlatch_ir=False`, `wlatch_mul=take` and `sync_io=issue`,
WP32_REVISIT `abort_latched=full`. The tie-break ranks by exact runs
and matched events over `TIE_FAMILIES`, which leave out F13, F17 and
F18, so two configurations that differ on refresh-on runs rank equal
there and the grid's enumeration order decides. The 26 alternatives the
run recorded as inert ties were each scored as a single flip of the
hand fit over all 19,142 runs:

| Flip of the thirty-second fit | Over all 23 families |
| --- | --- |
| `abort_latched=full`, `arbiter_q` 3, `arbiter_q` 4, `ea_floor=False`, `imm_latch=wait`, `odd_split=separate`, `port_sync=sync`, `room_ir_ready=False`, `sfr_setup=fetch_free`, `sync_io=issue`, `wlatch_ir=False`, `wlatch_mul=take`, `write_wait=end` | identical on every run (13 flips; `sfr_setup`'s 8 F17 W ECh runs of the twenty-ninth fit are carried by the prelude tail since the thirty-first) |
| `nop_hold=io` | +3 −5 (F17 +3 −4, F8 −1) |
| `pop_refresh=none` −7 (F13); `sync_io=latch` −27 (F3, F14, F15, F16); `prelude_anchor=clock0` −36 (F13, F18); `shift_exit0=tail` −44 (F18); `halt_refresh=run` −78; `dw_view=bus` −187; `room_ir_imm=idle` −205; `prelude_tail=standin` −209; `halt_refresh=none` −520; `sfr_cycle=bus` −1,055 (F17, F18); `wlatch_ir_at=busy` −3,234 (every refresh-off family but F0) | lose; all but `sync_io=latch` and `wlatch_ir_at=busy` only on F8, F13, F17 and F18 |
| `io_post=take` | +2 −0 (`F13-c-out-shlcl8-pO-w1`, `F13-u-out-mulu-k1-pO-w1`): the thirty-third fit |

The fitter's written output (its five tie picks plus `io_post=take`)
scores exactly the hand fit plus those two runs (18,961/19,142), so the
five picks are inert and only `io_post` was a move. The hand fit with
`io_post=take` alone is the thirty-third fit.

The first attempt at the run was killed after 17 hours: the fitter's
main process reached 55 GB on the 60 GB machine inside the third grid
(STORAGE_REVISIT, 2,592 structures) and the kernel's out-of-memory
killer took it, with the shell session that had started it (the same
systemd scope). The result cache (`fit.py`, "Result cache") lives in
the main process, counted results rather than bytes, checked its limit
only when a generation rotated, never at a put, and was emptied at a
stage's start, not between its grids; with every family as the guard a
grid's batch adds about 5 million results unchecked. It is now bounded
at twice `--cache-limit` (default 3,000,000 results; 5,000,000 was
used, about 700 bytes a result), emptied with the corpus-guard memo at
every grid, and logged at each grid's end (results held, flushes,
reused against simulated); `--grid NAME` resumes stage 6 at a named
grid with the same calls the full run makes from there. The second
attempt (`--grid STORAGE_REVISIT`, 73,625 s for the nine grids, the
sweep and polish; the storage grid's enumeration 22,074 s and its
descent 30,070 s) ran in a `systemd-run` scope capped at 40 GB and
peaked at 20.1 GB with the eight workers, the cache's sawtooth
visible in a five-minute memory log; 59.3 % of its 224 million run
results came from the cache.

A flaw in that cache's key, found on 2026-10-26 when the regression tests
were pointed at the current fit instead of the 2026-10-19 hand fit: the
class part of a run's key (`run_classes`) decoded the chain from its first
LS, while since the twenty-fourth fit the machine runs the prelude's tail
before it (`MOV sreg,AW` is a `reg` form, the F18 prelude marker a `push`
or `out`, the PAD NOP a `reg`). The key therefore left `reg` out on the
8,384 runs with no register form after the first LS (every F4, F5, F6 run,
450 of F13's, 12 of F0's) and `push` out on F18's 150 push-marker runs, so
inside a descent a move of a `reg` integer was scored against those runs'
cached results from before the move. Every adopted fit was scored without
the cache, so no scorecard is affected; what is weakened is the fitter's
own verdict on `reg` integers in every stage since the twenty-fourth fit,
stage 6's included. `run_classes` now decodes the segment-load tail and the
chain from offset 0 (a superset at every `prelude_tail` setting; a class
the configuration does not read costs cache hits, not correctness);
distinct signatures fall from 298 to 197, and `test_perf`'s projection
tests run against the tracked fit.

The register-class descent re-run with the corrected key (2026-10-26,
scratchpad wp47/), from the thirty-third fit: `fit --stage 4` under the
family guard (288 structures, two descended starts, the 15-enum sweep;
4,744 s, 38.3 % of 10.5 million run results reused against 68 % with the
old key) moved no integer and no enum: F3 840/840, the guard 1,742/1,742,
286 of 287 enum moves refused by the guard, the one admitted the known
inert tie `abort_latched=any`/`full`, seven inert ties recorded (the
stage-4 sweep's, as before). Then a coordinate descent of the 32
register-class integers (`REG_INTS`) by ±1 and ±2 clocks on every one of
the 19,142 runs at once, refresh-on families included, under the family
guard (wp47/regdesc.py, 730 s): no integer changes the exact count
(18,961); one, `shift_imm.hphase` 1 → 3, lowers the summed
first-divergence residual by 2 (644 → 642) by turning five F18 B
refresh-on shift runs (`b-n5-shli4-pE-w0`, `b-n6-shli4-pO-w0`,
`b-p-n7-shli4-pE-w0` a clock early → a clock late; `b-n6-shl1-pE-w0`,
`b-n7-shl1-pO-w0` +2 → +1) while ten more paired events leave zero, so
it is not adopted. It is a small fact against `unit_hold`'s note that
only `hphase`'s parity matters: with a refresh-on fetch starting on a
D1/C1 shift's first or second exec clock, a first boundary at exec clock
3 instead of 1 moves those five runs by two clocks. No held register
integer was a stale-cache artefact.

### The I/O setup counted from the post, not the start: `io_post` start → take (thirty-third fit, 2026-10-26, from the stage-6 ties)

Configs: start = build/validation/v35s/chains/fit/fit.json (= fit-wp43-hand.json);
take = scratchpad wp44/fl/io_post-take.json (differs only in io_post; key order aside).
Clocks are rel t_fill (aligned). The --trace column is the machine's absolute clock
(refresh runs): there, trace t = rel + 139 in both runs (trace 304 = I165, 298 = R159).
Traces: scratchpad wp45/full-<id>-{start,take}.txt.

#### The two runs (same picture in both)

F13-c-out-shlcl8-pO-w1 (SHL AW,CL, CL=8) and F13-u-out-mulu-k1-pO-w1 (MULU), the
second marker OUT 21h,AL:

| rel | event |
|---|---|
| 144-148 | refresh (R144); the long instruction's tail; queue wants a fetch, the refresh holds it |
| 149 | the OUT starts, on the fetch 149-152 that the refresh pushed onto its start clock |
| 149-150 | out.wbsync (write-back sync after the shift / multiply) |
| 151-153 | the pre (since_t reset at 151, after the sync); 151 is fetch 149's wait state (B1 149 B2 150 W 151 B3 152) |
| 151-153 | step `take 1 port` waits for the port byte (fetch 153-156 starts on 153) |
| 154 | port byte taken and the I/O posted (trace marks T L): request ('io_write', count, setup) |
| 155 | fetch 153's wait state (uncounted in both) |
| 159-163 | refresh R159: B1 159, B2 160, W 161, W 162, B3 163 |
| 164 | silicon I164 = take; start I165 |

Setup count (io_count=nowait: every clock but a memory/refresh wait state counts):
- take: setup 8 from the post, the issue on the 8th countable clock. Counted 154 (1),
  155 W (-), 156..160 (2..6), 161-162 W (-), 163 (7), 164 (8): issue at 164, the clock
  after the refresh's B3. Silicon I164; the run is exact from there (END included).
- start: setup 8 + out.pre 3 = 11, preloaded with eu.since_start = the countable clocks
  from 151 to 153 = 2 (152, 153; 151 is the fetch's W). Count 3 on 154, the same
  increments as take after that -> 9 on 163, 10 on 164, the 11th countable clock is 165:
  I165, then every
  event a clock late (F168 F172 R176...) and the END block's refreshes alternate.
- The refresh 159-163 does the same thing under both: its two waits (161, 162) are
  not counted. It is not the cause of the difference; it only sits right before the
  issue. The cause is the memory wait state inside the pre (151), which exists because
  the refresh at 144-148 delayed the fetch onto the OUT's start clock. Under start the
  pre needs 3 countable clocks and gets 2; under take the pre is not counted at all.

#### Why the other 19,140 runs do not change

Instrumented eu._preload (scratchpad scratchpad wp45/reads.py, reads.pkl) over all 24 family
names (F0 F0w F1..F22, 19,142 runs): for io_post=start the request's remaining count is
(setup + io_pre) - (count + since_start); with count 0 at the post (every case) it is
the take value exactly when since_start == io_pre. Of 34,106 preloads:

| class | port | io_pre | counted before post | n |
|---|---|---|---|---|
| out | DW | 0 | 0 | 20,240 |
| out | imm | 3 | 3 | 13,309 |
| in | DW | 0 | 0 | 426 |
| in | imm | 3 | 3 | 114 |
| out | imm | 3 | 4 | 10 |
| out | imm | 3 | 2 | 4 |
| out | imm | 3 | 1 | 3 |

The 17 unequal preloads are all in F13 (cells C OUT and U OUT): shlcl0/1/2/3/7/8/12/16
and mulu at w0 (n=4), shlcl1/2/8 and mulu pO-w1, shlcl4-pE-w1 (n=2 or 4), shlcl1/2/8-pO-w2
(n=1). All are misses under start; 15 diverge before the marker OUT's I/O (or for another
reason) and their result tuple (exact, residual, first residual, matched prefix) is
identical under take. Only shlcl8-pO-w1 and mulu-k1-pO-w1 change: +2 -0 (every other run's
result tuple is identical, not just its exact flag). Note the w0 ones with n=4 would put
the I/O a clock later under take; it is hidden by their earlier divergence.

#### Fields read (fit.RecordingConfig, run_result_reads under both configs)

Every run reads io_post, io_count, dw_count, dw_count_b2b under both values; the 2,142
refresh-on runs read refresh_io_pre under both. The set of fields read over all runs is
identical under start and take: no field becomes unread under take by the recorder's
definition. The reads are not gated on io_post:
- refresh_io_pre: machine.py reads it on every clock of a refresh run while building
  eu.since_start; since_start is consumed only by eu._preload under io_post=start. Under
  take it is read but has no effect. Single flips over all runs: refresh_io_pre=waits
  changes 0 results under take, and 0 under start either (already inert in the
  thirty-second fit).
- dw_count: two parts. The _preload part (start only) needs since_start > 0 for a DW
  form, which never happens (all 20,666 DW preloads counted 0): inert under both. The
  arbiter.py part (a bus cycle starting on the post / start clock takes the first count)
  is independent of io_post and in force: under take dw_count=all -18,439, fetch -102.
- dw_count_b2b: arbiter.py, independent of io_post: under take False -326.
- io_count=nowait: arbiter's Request.counts, independent of io_post: under take
  fetch_free -18,081.
- out.pre / in.pre (cost table, not recorder fields): still read for the template.

Fields unread on every run under take (in effect): refresh_io_pre (read, no effect)
and dw_count's io_post=start sub-rule. By the recorder: none.

#### knob_dependence
No `knob_dependence` subcommand (python -m validation.v35s.chains: gen acquire report
facts score sim fit; fit has no such flag). Skipped.

#### Hand fit (fit-wp45-hand.json = fit.json with io_post=take)
score over F0 F0w F1..F22 (scratchpad sc35-all.txt vs scratchpad sc34v.txt, 19,142 cells): 18,959 ->
18,961, +2 -0 (F13 c-out-shlcl8 pO-w1, u-out-mulu-k1 pO-w1). endchk: 0 model errors,
refresh-off END mismatches none, END mismatches 173 (fit.json: 175; F13-c 66->65,
F13-u 12->11).

### Control flow and the EA alone: the branch's flush and refill, PUSH R's cadence, LDEA by mode (F23, F25, 2026-10-27; no fit)

Read 2026-10-27 from the recorded runs with the thirty-third fit untouched, before either family had a template
(`families.UNMODELLED`; F25's model and fit follow in the next section, F23's two sections on). Costs are `ΔM − ΔM(empty)` at the same frame, parity and
waits, written PUSH/OUT; pE w0 unless said otherwise. Both families ran with RFM ECh, every run `complete` and
`passed`, 12 (F23) and 20 (F25) repeats per wait setting all identical to their first trace up to a constant tick
shift; the normaliser's expected-access list matched every data, stack and I/O cycle of all 948 runs, the eight-word
bursts of PUSH R and POP R and the CALL's and RET's stack cycles included, which confirms POP R reads eight words.
Ids `F23-<push|out>-<variant>-p<E|O>-w<0|1|2>` and `F25-<push|out>-<variant>[-k2]-p<E|O>-w<0|1|2>`; the corpus
entries are chains-F23-w0..2 and chains-F25-w0..2. [chains-F23-w0..w2, chains-F25-w0..w2]

**The PUSH marker and a balanced body (normaliser fix, 2026-10-27).** The marker matcher took the first stack write at
M1's address after M0. A body that pushes and pops the same number of words puts its first push at that address, so
M1 was read off the body's first write and the PUSH-frame ΔM of `callret`, `pushr_popr`, `prepare_dispose`,
`push_ds1_pop_ds1` and `push_ds0_pop_ds0` came out at the empty frame's 9. The matcher now takes the event the
program-order access match assigned to the marker's own instruction (the old rule remains the fallback when that
match fails). Over the whole corpus 36 runs changed their M1: the 30 above and F15's `p-push-push_pop` cells (PUSH-frame
ΔM 20 → 46 at w0 against the OUT twin's 48); nothing else moved, and the scorer never read the marker clocks, so no
scorecard changed. After the fix every balanced PUSH-frame variant is within −4..+2 clocks of its OUT twin.

**F23 (chains-F23-w0..2; `f23`; 60 variants, 360 runs).** Flags are made known by `CMP AW,AW` (3B C0) before every
conditional form; the skipped NOPs after a taken branch are chain bytes that never execute (knob `skipped`).

| Form | Cost pE w0 (PUSH/OUT) | Reading |
| --- | --- | --- |
| `CMP AW,AW` | 3/4 | a 2-byte register form (F3: 3) |
| `BE +n` taken, n = 0..7 | even target 27/28, odd target 30/32 | identical for n = 0, 2, 4, 6 and for n = 1, 3, 5, 7: the skipped bytes cost nothing, only the target's parity counts (3–4 more when odd at w0, 4–6 at w1, 4–7 at w2) |
| `BR +n` short, n = 0..7 | even 20/21, odd 23/25 | 7 under BE taken; the same parity rule |
| `BR +n` near (E9 n 00), n = 0..3 | even 21/23, odd 24/27 | one more than the short form (its third byte) |
| `BNE +0` not taken (after CMP) | 11/13 with the CMP, so 8/9 alone | k = 2 (two CMP; BNE pairs) 23/25: linear |
| `BNE +2` not taken then NOP NOP | 19/20 | the two executed NOPs add 8/7 (F3: 4 per NOP) |
| `MOV CW,1 ; DBNZ +0` not taken | 17/20, so 10/13 after the 7 of MOV CW,imm16 | |
| `MOV CW,2 ; DBNZ +n` taken once, n = 0, 2 | 33/38, so DBNZ taken 26 (even target) / 31 (odd) | the same for n = 0 and 2 |
| `CALL +0` | 30 (even target) / 35 (odd) | the return address's stack write 10 clocks after M0's I/O cycle, then 8 idle clocks, then the target's fetches |
| `CALL +2 ; BR +1 ; RET` (run 0, 2, 1) | 79/83 | with CALL 30/35 and BR 23/21 by target parity, RET is about 26–27 |

Which target parity a cell sees follows from the frame: under PUSH (M0 one byte) the branch sits at an odd offset at
pE and an even n gives an odd target; under OUT (two bytes) the reverse, and pO flips both. Read that way the two
frames agree within 1–2 clocks on every form, as they do elsewhere.

The strip of a taken branch (OUT, pE w0, even target: `F23-out-be-n0-pE-w0`, aligned at M0's I/O cycle, OUT = 10
clocks): M0 I at 0, the refill fetches F at 3 and 6, then nine idle clocks, then the target's fetches F at 18, 21 and 24
back to back, four idle clocks, F at 31, four idle, M1's I at 38. The first target fetch starts 8 clocks after the
branch's start (BE at 10). The EU does not resume on the first target word: M1 (the first instruction at the target)
starts about 28, one clock after the third back-to-back fetch ends, so the refill delivers three words before anything
executes. With an odd target (`be-n1`) the refill is four fetches back to back (18, 21, 24, 27; the first carries one
useful byte), M1 starts about 32 (two clocks after the fourth ends) and its I/O cycle is at 42. The same shape, with its
own lead, serves BR short, BR near, DBNZ taken and CALL (`out-call`: w at 10, eight idle clocks, F at 21, 24, 27, 30, nine idle,
F at 42, I at 45) and the RET of `callret` (r at 39, eight idle clocks, F at 50, 53, 56, 59, then the BR's own flush and
refill). Not-taken
BNE and DBNZ make no flush: their strips are fetch-paced like a register train (`out-bne-n0-k1`: F at 3, 6, 9 back to
back, eleven idle clocks, I at 23).

**F25 (chains-F25-w0..2; `f25`; 98 variants, 588 runs).**

| Form | Cost pE w0 (PUSH/OUT) | Reading |
| --- | --- | --- |
| `LDEA AW,[BW]`, `[BW+IX]`, `[BW+IY]`, `[BP+IX]`, `[BP+IY]`, `[IX]`, `[IY]` | 6/7 | one cost for every mod 00 register mode: base and base+index are not told apart |
| the eight d8 modes | 6/7 (pO 6/6) | the displacement byte costs nothing at k = 1 |
| `[BW+IX+200h]`, `[BW+IY+200h]`, `[BP+IX+200h]`, `[BP+IY+200h]` | 7/8 (pO 7/7) | |
| `[IX+200h]`, `[IY+200h]`, `[BP+200h]`, `[BW+200h]`, `[0C00h]` | 9/7 (pO 6/6) | parity-dependent under PUSH only; base+d16 reads 2 above base+index+d16 at pE, the reverse of the EA table's order (fitted: every mod 00 and d8 mode 2, base+index+d16 3, base+d16 and direct 2; the 3/4 of `DEFAULT_EA` are the unfitted start). The fit below shows the inversion is confined to the PUSH pE cells where the d16's high byte sits in a word not yet fetched when the EA step reaches it: the load shows the same +3 there (`F21-push-l0-ld-bw_d16-pE-w0` reads at +12 against [BW]'s +9, +9 at pO), so it is the d16's fetch, not the table |
| LDEA at k = 2 | `[BW]` 11/13, `[BW+IX]` 11/13, `[BW+10h]` 12/16, `[BW+IX+10h]` 12/16, `[BW+200h]` 15/16, `[0C00h]` 15/16 | the second instance costs 5/6 for the 2-byte forms and 6/9 for the displaced ones: fetch-paced |
| `XLAT` | 11/14 | the byte read at 0800h |
| `PUSH imm16` | 13/14; k = 2 26/27 | 13 each (PUSH AW 9) |
| `PUSH imm8` | 12/13; k = 2 24/25 | 12 each |
| `PUSH R` | 75/76 | eight stack writes, the first 9 clocks after M0's I/O cycle, then issue to issue every 9 / 10 / 11 clocks at 0 / 1 / 2 waits: the 3+w-clock write cycle and six idle clocks, so the burst is bus-bound, the EU waiting for each write's end (`F25-push-pushr-pE-w2` s16 27 38 ...; the totals 84/84, 92/93 at 1 and 2 waits grow with the frame on top). At pO w2 one fetch gets through before the eighth write (173 between 168 and 180). The first reading here, a 9-clock cadence at every wait, was wrong |
| `PUSH R ; POP R` | 150/151 | POP R about 75, eight reads at the same 9-clock cadence, the first 9 after the last write |
| `PREPARE 0,0` | 30/32 | one stack write (BP) 6 clocks after M0's I/O cycle, then two fetches and some twenty idle clocks |
| `PREPARE 0,0 ; DISPOSE` | 41/44 | DISPOSE 11/12 with one stack read |
| `PUSH DS1`, `PUSH DS0`, `PUSH PS` | 10/11 | one above PUSH AW |
| `PUSH DS1 ; POP DS1`, `PUSH DS0 ; POP DS0` | 22/23 | POP sreg 12/12 (POP AW 11) |
| `MOV DS1,AW`, `MOV AW,DS1` | 3/4 | 2-byte register forms |
| `MOV DS1,[BW]` | 12/13 | the load's 11 plus one |
| `MOV [BW],DS0` | 9/10 | the store's 9 |

What the model needs from these two families, in the order the HDL plan lists them (Phase E): a `branch` class with a
flush, a target fetch 8 clocks after the start, a refill of three words before the EU resumes and a not-taken path
that is a plain register form; a `call` class adding the return-address write before the flush and RET's read; an EA
step that costs the same for every mod 00 and d8 mode (the fitted table already does; the d16 inversion is the
straddling word's fetch, above); a stack burst of eight words for PUSH R and POP R, each waited for as a write; the
immediate push; and the segment forms as register forms with a write-back. Both are fitted below.

### The EA alone and the stack frame in the model: ten classes, three enums, the thirty-fourth fit (F25, 2026-10-27)

**Decode and classes** (`sim/templates.py`, WP52, Opus). 8D with a memory operand is `lea` (`Op.bus=False`: the
memory form's head, so the EA table's clocks, and no bus cycle; the offset is written to the register); D7 is `xlat`
(a byte read at BW+AL, no ModR/M); 68 / 6A are `push_imm` (a 2- or 1-byte immediate); 60 / 61 are `push_r` / `pop_r`
(eight words AW CW DW BW SP BP IX IY from SP−2 down / SP up, SP's word read and discarded, the registers kept as POP
AW keeps them); C8 is `prepare` (level 0 only; BP's write, BP := SP, SP −= imm16); C9 is `dispose` (SP := BP, the read
at BP, BP := the data fill); 06 0E 16 1E are `push_seg`, 07 17 1F `pop_seg`; 8E with a memory operand is `load_seg`
(the load's template), 8C is `store` with a memory operand and `reg` with a register one; segment registers themselves
are not modelled (nothing in F25 reads one). Templates: `lea` the memory head then exec; `xlat` pre, the byte read with
setup / setup_free, exec; `push_imm` pre, the immediate's take, the write with its setup, post; `push_seg` / `pop_seg`
PUSH AW's / POP AW's templates with their own integers (one clock above PUSH AW and POP AW, so PUSH AW's integers
do not fit them); `dispose` POP's template with an optional pre; `prepare` the write and the 3-byte take in
`prepare_order`, then exec; `push_r` / `pop_r` eight data steps, the first with `setup` and the rest with `wsetup`,
`gap` clocks between, then post / exec. Three enums (`sim/config.py`, DEFAULT the old behaviour):

| Enum | Options, chosen in bold | Reading |
| --- | --- | --- |
| `lea_form` | mem / **reg** | LDEA is a register-only form for the I/O interlocks (`io_interlock`, `io_busy_start`, the latch rules: as MOV AW,DW it does not start while an OUT's I/O waits in the slot) and `self.mem` is off for it; its template still runs the EA table's clocks. Stage 9's grid: 276 of the 360 LDEA runs against 192 |
| `burst_wait` | **data** / issue | each of the eight words is a data step the EU waits for as for any write or read / posted and left on the bus, the EU going on after its issue (a cadence that would not stretch with the waits). The data variant is what the corrected PUSH R reading says; issue was refuted |
| `prepare_order` | **write_first** / take_first | BP's write posted before the three operand bytes are taken / after |

The IR-hold rule (`ir_load=disp_data`) now requires `op.bus`: without it a displaced LDEA never let the IR load.
`forms.STACK_CLASSES` carries the push and pop classes for the normaliser's expected-access lists (all 948 F23/F25
lists identical before and after). `fit.py` gained stage 9 (`STAGE_FAMILIES[9] = ["F25"]`, `F25_ENUMS`, 51 integers
in `F25_INTS`), run with the corpus guard over all 19,730 modelled runs rather than the stage guard: under the stage
guard every descent round scored about 200 candidates over the other 19,142 runs and was killed twice at the 40G
memory cap, even at `--cache-limit 1000000`; no other family's run reads the new classes, so only an enum move could
change one, and the corpus guard checks every move ("0 of 4 moves refused"). `families.UNMODELLED` is `("F23",)`.

**Integers** (stage 9 from hand read-offs now in `DEFAULT_COST`; the descent moved only `dispose.setup` 7 → 6 on a
tie, 446 → 446):

| Class | Integers |
| --- | --- |
| lea | pre 0, exec 0, nx 2 |
| xlat | pre 0, setup 7, setup_free 3, exec 2 (POP AW's) |
| load_seg | pre 0, pre0 2, dfloor 2 (the load's), exec 3 (the load's 2 plus one) |
| push_imm | pre 3, setup 7, setup_free 3, post 0 (PUSH AW's setup) |
| push_seg | setup 8, setup_free 4, post 0 (PUSH AW plus one) |
| pop_seg | setup 7, setup_free 3, exec 3 (POP AW plus one) |
| dispose | pre 0, setup 6, setup_free 3, exec 2 |
| prepare | pre 2, setup 7, setup_free 3, exec 16 |
| push_r | pre 0, setup 10, setup_free 7, wsetup 7, gap 0, post 0 |
| pop_r | pre 0, setup 7, setup_free 3, wsetup 7, gap 0, exec 2 |

**Scorecard** (`score --family F25`, scratchpad wp52/score-F25.txt and wp54/fit-34/F25.txt, identical): 446/588;
even 226/294, odd 220/294; 0 waits 140/196, 1 wait 152/196, 2 waits 154/196.

| Frame | pE w0 | pE w1 | pE w2 | pO w0 | pO w1 | pO w2 |
| --- | --- | --- | --- | --- | --- | --- |
| PUSH | 38/49 | 39/49 | 39/49 | 35/49 | 34/49 | 36/49 |
| OUT | 33/49 | 38/49 | 39/49 | 34/49 | 41/49 | 40/49 |

Exact in all 12 runs: XLAT; PUSH DS1, PUSH DS0, PUSH PS and both push/pop pairs; MOV AW,DS1; PUSH R and
PUSH R ; POP R under OUT; PUSH imm16 and imm8 at k = 1 and 2 under PUSH; every LDEA d8 mode at k = 1; every OUT
d16 mode, direct included, and their k = 2 forms; the PUSH frame's k = 2 d16 and direct forms; every PUSH mod 00
mode at pE. The 142 misses, by cause (clocks from t_fill, silicon against model):

| Group | Runs | Where | First divergence and reading |
| --- | --- | --- | --- |
| A. LDEA under PUSH at pO, mod 00 | 29 | 7 modes × 3 waits, [BW] and [BW+IX] at k = 2 at every wait, [BW+10h] and [BW+IX+10h] at k = 2 at w1 | after fetch 81 silicon fetches back to back at 84 (86 / 88 at w1 / w2); the model has no fetch there and posts M1's write first (st92 against st93); at k = 2 the model's fetch is 86 against 84. In silicon the queue has room for a word while LDEA runs its EA clocks; in the model the room is still 1 (the IR loads nx = 2 clocks after the ModR/M take) so the room/IR rule does not raise the request. MOV DS1,AW (8E C0), a 2-byte register form in the same cell, is exact |
| B. LDEA with a d16 straddling a word, PUSH pE | 27 | base+d16 and direct (5 modes) −3 / −4 / −4 at w0 / w1 / w2; base+index+d16 (4 modes) −1 / −4 / −4 | M1's write st96 / 100 / 104 against st93 / 96 / 100: silicon ends LDEA 3–4 clocks later once the word holding the d16's high byte has arrived; the load does the same (F21 above). Refuted: the memory forms' displacement rules (`late_disp`, the take latch, `ea_ir_room`) applied to LDEA's displacement, 268 against 276; a floor of N clocks from the displacement's take, N = 6 fixes pE w0 and w1 and breaks w2 and the aligned cells (126/360). The extra time is fetch-state dependent, not a constant |
| C. LDEA under OUT | 28 | mod 00 at w0 (14): silicon's next fetch 94 (pE) / 100 (pO) against 90 / 99, a fetch held 7 clocks after fetch 87; k = 2 mod 00 (12): pE +5 (fetch 93 against 98), pO −2 (106 against 104); d8 k = 2 at pE w1 (2): +6 | the w1 / w2 k = 1 mod 00 cells are exact |
| D. PUSH imm under OUT | 24 | imm16 and imm8, k = 1 and 2 | the fetch after M0's I/O: imm16 silicon I+4 against I+3; imm8 at pE I+3 against I+4; imm8 at pO the stack write 9 clocks after the I/O against 6. The PUSH frame is exact: a frame-state finding (the marker dependence of `push_imm.pre` / `setup` below) |
| E. Segment forms | 12 | MOV DS1,AW and MOV DS1,[BW] under OUT at pE (6): the M0 marker's own I/O is a clock later in silicon (85 against 84 at w0) when 8E follows it; pO exact, MOV AW,DS1 exact. MOV [BW],DS0 at pO in both frames (6): the store a clock later (da87 against da86 under PUSH, da91 against da90 under OUT); pE exact | both parity-dependent; left as misses rather than giving 8E / 8C their own classes |
| F. PREPARE / DISPOSE | 16 | PREPARE's M1 grows about 2 clocks less across w0 → w2 than the model's under PUSH (+2, +1, 0) and about 2 more under OUT (0, −1, −2); prepare_dispose the same spread | the wait dependence of `prepare.exec` and `dispose.setup` below |
| G. PUSH R under PUSH at pO | 6 | pushr and pushr_popr | the first write at M0's end + 9 in silicon (89 / 90 / 91) against 90 / 91 / 92; pE exact (the first write at the intervening fetch's end + 7) and OUT exact. PUSH R's first write sits 2–4 clocks after PUSH AW's by cell, so no one setup fits all |

**Knob dependence** (rule 5, reported by the fitter and not encoded; each is a structural finding for a later
state read): `lea.nx` 2 / 1 / 2 by waits and 2 under OUT, 0 under PUSH; `push_imm.pre` 4 under OUT, 3 under PUSH;
`push_imm.setup` 10 under OUT, 7 under PUSH; `dispose.pre` 0 / 0 / 1 and `dispose.setup` 5 / 6 / 7 by waits;
`prepare.exec` 15 / 16 / 17 by waits; `push_r.setup` 10 under OUT, 9 under PUSH.

**LDEA and the EA table.** The fitted EA table applies to LDEA as an "ea" step with exec 0: all 96 d8 k = 1 runs
exact, OUT d16 24/24 per wait and parity, PUSH pO d16 exact, the base+index+d16 extra clock present. LDEA needs no EA
cost of its own; the facts table's inversion is group B's straddling fetch.

**The thirty-fourth fit** (`fit.json`, 2026-10-27; scratchpad wp54/fit-34.json) is the F25 fit above with the
rule register's six inert rules and the `sync_io` tie dropped, as docs/v35s-chain-rtl-spec.md's decisions record:
`room_ir_ready=False`, `ea_floor=False`, `wlatch_ir=False` (`wlatch_ir_at=busy`), `wlatch_mul=take`,
`sfr_setup=fetch_free`, `sync_io=issue`. Scored over F0, F0w, F1–F22 and F25 (wp54/fit-34/) its output is byte for byte
the wp53 verification's (18,961/19,142; the six F22 runs, the 175 refresh-on runs, END 173 unchanged) plus F25's
446/588: 19,407/19,730 over the 24 scored families. No existing class integer or EA entry changed. The frozen
package was regenerated from it (`freeze`, `freeze --check` clean) and `freeze --verify --jobs 8` is bit-identical over
all 19,730 runs (52 s); 422 tests pass.

### Control flow in the model: five transfer classes, six enums, the flush and the refill (F23, 2026-10-28)

**Decode and classes** (`sim/templates.py`, WP55, Opus; classes by encoding format). 74 / 75 / EB are `branch_short`
(a 1-byte displacement; `Op.cond`, the 70–7F row's condition field, is a format property), E9 `branch_near`, E2 `dbnz`,
E8 `call` (the stack write at SP−2), C3 `ret` (the stack read at SP); `Op.target` is the taken transfer's code offset.
Taken or not is semantics: BE taken iff Z, BNE iff not Z, BR always, DBNZ iff CW−1 ≠ 0; `execute` sets Z on
CMP r16,r16, decrements CW on DBNZ, lowers SP and keeps the return offset on CALL, raises SP on RET, so `callret` runs
0, 2, 1 and `io_ports` follows targets. Templates: pre, the take, `cond` clocks for a form with a condition field, then
either exec, a flush step and post (taken) or an optional decide step and `nexec` (not taken); CALL runs its write and
the exec + flush in `call_order`; RET pre, the read, exec, the flush, post. The queue (`sim/queue.py`) gained
`flush()`: bytes, latched byte and uncommitted bytes discarded, the word of a fetch still in flight dropped when it
arrives, the fetch pointer at the target (an odd target is fetched at its odd address and brings one byte; the next
fetch takes the following even word), a queue change for the request rule; `flush_held` blocks fetch requests once the
transfer's operand bytes are all taken. The EU (`sim/eu.py`) gained the flush and decide steps, `_flush` (IR emptied,
pc at the target) and a refill gate in `_start`. Six enums (`sim/config.py`, DEFAULT the old behaviour; the flip score
is F23 exact out of 360 with that one enum flipped at the fitted integers):

| Enum | Options, chosen in bold | Flipped | Mechanism |
| --- | --- | --- | --- |
| `refill_start` | ir / full / full_d / **full_io** | 128 / 83 / 216 | the target instruction starts only once the refill has filled the queue (nothing in flight, no fetch wanted), on the last delivery clock itself, except an IN / OUT on the delivery clock of a 3-clock fetch (0 waits), a clock later. Three words for an even target and four for an odd one fall out of the request rule, with the IR loading during the refill: no word count |
| `flush_hold` | none / **start** | 241 | no fetch request from `hold` clocks after a taken transfer's start until the flush |
| `flush_inflight` | discard / **wait** | 190 | the flush waits until no fetch is in flight and `fgap` clocks have passed since the last fetch's end |
| `untaken` | reg / **wait** | 246 | a not-taken branch is not a plain register form: its end waits the same way (`nfgap` after the last fetch's end), then `nexec` |
| `call_order` | **write_first** / flush_first | 237 | CALL posts its stack write before the flush |
| `branch_reg` | none / **reg** | 198 | the transfer classes are register-only forms for the I/O interlocks |

Stage 10 (`fit.py`: `STAGE_FAMILIES[10] = ["F23"]`, `F23_ENUMS` with 128 combinations, 39 integers in `F23_INTS`,
the corpus guard as stage 9) started from strip read-offs settled by F23-only descents in scratch and moved nothing
(255 → 255; 0 of 3 moves refused by the guard; 74 s). The only listed alternative is `untaken=reg` with `dbnz.nexec` 7
at 249. `branch_short.nx` 6 scores the same 255 but overfills the queue in `F23-out-bne-n0-k2-pE-w0` under the DEFAULT
enums, so it is 0. `forms.STACK_CLASSES` gained `ret`; the normaliser's access lists are unchanged; `families.UNMODELLED`
lost F23.

| Class | Integers |
| --- | --- |
| branch_short | pre 0, cond 4, exec 8, post 0, fgap 5, hold 6, nexec 1, nfgap 1, nx 0 |
| branch_near | pre 3, exec 5, post 0, fgap 3, hold 10, nexec 4 (unused) |
| dbnz | pre 0, exec 14, post 0, fgap 5, hold 2, nexec 6, nfgap 1 |
| call | pre 3, setup 7, setup_free 3, exec 8, post 0, fgap 5, hold 10 |
| ret | pre 0, setup 7, setup_free 3, exec 8, post 0, fgap 5, hold 6 |

**Scorecard** (scratchpad wp55/score-F23.txt, wp57/fit-35/F23.txt identical): 255/360; even 146/180, odd 109/180;
0 waits 93/120, 1 wait 93/120, 2 waits 69/120.

| Frame | pE w0 | pE w1 | pE w2 | pO w0 | pO w1 | pO w2 |
| --- | --- | --- | --- | --- | --- | --- |
| PUSH | 29/30 | 29/30 | 21/30 | 20/30 | 20/30 | 20/30 |
| OUT | 25/30 | 25/30 | 17/30 | 19/30 | 19/30 | 11/30 |

Exact in every cell: the controls, BR near (24/24 per frame), CALL, DBNZ taken, the PUSH frame's BNE at k = 1 and
n = 2. The 105 misses (wp55/final-div.txt; clocks from t_fill, silicon against model):

| Group | Runs | Reading |
| --- | --- | --- |
| A. BR short at pO | 48 | PUSH frame (24): the sequential fetch after M0's write is 3 clocks late in silicon (F52 at 84 against 81 at w0), the shape of an aborted cycle at the BR's start, take and IR load; the model's room there is 3, not 2, so `abort_fetch` does not fire. OUT frame (24): the model makes an extra sequential fetch after the marker's I/O (I20 at 85, then F54 at 88; silicon has none and its target fetch is at 96) |
| B. BE at 2 waits | 24 | PUSH pE 8, OUT pE 8, OUT pO 8: the target fetch a clock early (`out-be-n0-pE-w2` F52 at 107 against 106); the per-knob table wants `cond` or `exec` one higher at w2 |
| C. BNE not taken | 18 | OUT 15, PUSH bne-k2 pE 3: the back-to-back fetches and M1's I/O off by −6 to +5 by cell (`out-bne-n0-k1-pE-w0` I at 107 against 108; PUSH k2 pE F5A at 101 against 95): the latch and room around the not-taken resolution do not match |
| D. DBNZ not taken | 9 | OUT 6, PUSH pO 3: `out-dbnz-c1-n0-pE-w0` F58 at 99 against 94; `nexec` / `nfgap` depend on marker and parity |
| E. callret | 6 | PUSH pO, OUT pE: after the RET's refill the BR's pre-flush gets an extra model fetch (silicon F52 137, F54 140, F52 154; the model adds F56 at 143): the BR's hold of 6 comes too late there |

**Knob dependence** (reported, not encoded): `branch_short.cond` 4 / 4 / 5 and `.exec` 8 / 8 / 9 by waits;
`branch_short.fgap` 5 even, 8 odd and 5 / 5 / 8 by waits; `branch_short.hold` 6 even, 3 odd; `dbnz.nexec` 6 even, 8
odd and 6 under PUSH, 8 under OUT; `dbnz.nfgap` 1 even, 3 odd and 1 under PUSH, 3 under OUT. Groups A, C and D are
the states behind these: the transfer's interaction with the fetch in flight and the latch at its start, by parity.

**Corrections to the facts section.** An odd target is fetched at the odd address itself (`F23-out-be-n1-pE-w0`: the
fetch at 10053 at 102), not at the even word holding it; that fetch carries one byte and the next is at 10054. "The
first target fetch starts 8 clocks after the branch's start" assumed BE starts at M0 + 10; in the model CMP AW,AW
starts on M0's I/O clock and BE at +3, and the target fetch is set by the take, 4 `cond` clocks, 8 `exec` clocks and
the flush's wait of `fgap` = 5 past the last pre-flush fetch's end, which is what makes it scale with the wait states
(for BR short the target fetch is always 6 clocks after the last pre-flush fetch). Prefetch keeps going for a few clocks
after a taken transfer starts (fetches up to start + 3 still go in every frame: `out-be-n0-pE-w0` 87 and 90, the
latter back to back, none at 93). The EU resumes on the refill's last delivery clock, except an OUT at 0 waits, one
clock later (w0: the third fetch ends 110, M1 starts 112; w1: delivered 116, starts 116). BE taken costs 4 more than
BR short, put in `cond`; the data cannot tell a flag test from an interlock with the preceding CMP, since every
conditional form follows CMP AW,AW. Not-taken BNE and DBNZ are not purely register forms (`untaken=wait`, 255 against
246).

**The thirty-fifth fit** (`fit.json`, 2026-10-28; scratchpad wp57/fit-35.json) is the thirty-fourth with F23's six
enums and five classes above and `shift_count_mask=cl8` (the F26 count-mask finding: the CL count is the full byte, as
the C0/C1 immediate count already was; `Op.cl_count` marks a D2/D3 count and the EU masks it under `cl5`, the old
behaviour and DEFAULT). Scored over every family (wp57/fit-35/) it is byte for byte the thirty-fourth's on F0–F22 and
F25 (18,961/19,142 and 446/588), F23 255/360, F26 906/906: 20,568/20,996 over the 26 scored families (F27 is read
above and unmodelled until its fit). The frozen package was regenerated from it and `freeze --verify --jobs 8` is
bit-identical over all 20,996 runs (56 s); 434 tests pass. The freezer needed one fix on the way: a condition
`A and (B\n or C)` whose `A` folds to the fitted True is rendered as the multi-line operand alone, and its grouping
parentheses, which belonged to the outer expression, are now put back (`freeze.py` `_repls`).

### The probe families under the thirty-fourth fit: five rules confirmed, the shift count unmasked, the refresh-on body (F26, F27, 2026-10-28; no fit)

Acquired 2026-10-28 from the WP56 generator (built in a git worktree while the F23 model was being written, run on the
board from there, frozen as chains-F26-w0..2 and chains-F27-w0..2): 1,978 runs, 0 failed or incomplete, every F26 repeat
and every F27 repeat at 1 and 2 waits identical up to a constant tick shift; three F27 repeats at 0 waits
(`push-fc-unit-shlcl8-n1-pE`, `push-fc-beat-movr-n4-pE`, `push-ec-port-outw-n4-pE`) differ in one fetch cycle's
`strobe` sample count only (7 against 8), with the same start, end, address and data, a field the normaliser never
reads. Scored with the thirty-fourth fit and no free parameter (scratchpad wp56/score-F26.txt, score-F27.txt, the flips
in wp56/flips/). [chains-F26-w0..w2, chains-F27-w0..w2]

**F26: 882/906.** Every cell of the five probes is exact; the 24 misses are the two `MOV CL,n ; SHL AW,CL` cells at
n = 32 and 255 in both frames, at every parity and wait. Flipping each probed rule to its alternative and rescoring F26
tells which cells decide it:

| Rule (fitted value) | Flipped | F26 exact | Cells lost | Reading |
| --- | --- | --- | --- | --- |
| `lookup_start=True` | False | 774 | 108: every TEST [0C00h],AW and TEST [BW+200h],AW cell with a start-clock fetch, both frames, k = 1..3, the NOP ladder moving the fetch on and off the start clock (+2 with, −1 without) | the lookup pays the clock, in 108 cells across both frames and every wait: P |
| `disp_io=extend` | none | 840 | 42: the base+index+d16 forms only (`fib` at every k, `dio` at n = 0, the `gih`/`lks` TEST [0C00h] and [BW+200h] pO cells) | confirmed where it was seen; the d8, base+d16 and direct ladders are exact under both values, so either their displacement take never lands on the I/O's issue clock in these ladders or only the base+index form extends: a state read on `dio` decides which (open) |
| `grp_io_hold=True` | False | 864 | 42: TEST [0C00h],AW and TEST [BW+200h],AW under OUT at pO only; INC, NOT, SHL, NEG and DEC [BW] exact under both | the hold is seen with TEST's fixed lookup only; whether the plain group forms never make the state or do not hold is a state read (open) |
| `free_idle_b2b=True` | False | 874 | 32: the base+index+d16 immediate store at k = 2 and 3 under both markers, every n, at 0 waits (and the pO w0 pair) | P |
| `port_issue=True` | False | 881 | 1: `out-pi-oo-none-n0` pO w0, the same cell shape as the one F7 run | the ladder did not make a second deciding cell: the rule stays pinned by one cell; a longer ladder, or a port form after a fetch run, is the next probe |

The count mask (`cnt`): `SHL AW,n` costs 74 / 76 / 78 / 522 clocks at n = 31 / 32 / 33 / 255 under PUSH at pE w0
(+2 per count beyond 31, 522 = 74 + 224 × 2), and `MOV CL,n ; SHL AW,CL` 82 / 528 at 32 / 255 (the MOV CL plus the same
line). Silicon uses the full 8-bit count in both forms. The model does for the immediate form (those cells are exact)
and masks CL to 5 bits in `templates.py` (`regs["CW"] & 0x1F`), so the two CL cells miss by −66 and −448 (the model
early by 33 and 224 counts): the mask is the enum `shift_count_mask` (cl5 / cl8, the old value DEFAULT) since the
thirty-fifth fit, under which F26 is 906/906. The RTL spec's count-loop width (9 bits for a 255 count)
stands.

**F27: 646/1,072; the ECh controls 265/268, the FCh runs 381/804** (pE w0 68/134, pE w1 67, pE w2 59, pO w0 70, pO w1 71,
pO w2 46; by series `port` 125/288, `unit` 107/180, `room` 78/180, `beat` 66/144, the empty frame 5/12). Sixteen FCh
runs overfill the model's queue (`!`): `IN AL,40h` and `IN AL,DW` cells at every wait, a refresh-on IN the corpus never
had (F8, F13, F17, F18 have no IN). The flips:

| Rule (fitted) | Flipped | F27 exact | Gained / lost | Reading |
| --- | --- | --- | --- | --- |
| `room_ir_imm=none` | idle | 506 | +0 −140, the empty frame and every `room` ladder cell among them | not a prelude artefact: P |
| `refresh_drop_post=hold` | drop | 630 | +0 −16: `port-outb/outw/inb-n0` under PUSH and `room` cells | P |
| `refresh_lead_port=last` | lead | 640 | +0 −6: `port-outb/outw-n3` under PUSH, `room-movcl` under OUT | P |
| `refresh_drop_unit=unit` | odd | 643 | +0 −3: `unit-mulu-n0`, `-n2` and `room-movcl-k4` under PUSH | weakly confirmed |
| `refresh_beat_t4=t4` | none | 645 | +1 −2 (`room-movcl-k3` pE w0 gained; `room-movawi-k3`, `-movdwi-k3` pO w0 lost) | undecided: the `beat` ladder's own cells score the same either way |

The three refresh-off misses (the first new refresh-off misses since F22's six), read with `sim --silicon`:
`out-ec-beat-ds1-n0-pE-w0`, the M0 marker's own I/O a clock later in silicon (85 against 84) when `MOV DS1,AW` (8E C0)
follows it, the F25 group E finding again (MOV DS1,AW and MOV DS1,[BW] under OUT at pE); `out-ec-beat-movr-n0-pE-w0`,
`MOV AW,DW ; MOV DW,imm16` after the OUT marker at pE: the second fetch after the I/O a clock late (91 against 90), the
rest in step; `push-ec-room-movcl-n0-k3-pO-w0`, three `MOV CL,imm8` under PUSH at pO: M1's write a clock late (104
against 103), k = 1, 2, 4 exact. The refresh-on empty frame under OUT misses in five of six cells: at pE w1 silicon
issues the marker's I/O at 110 and the refresh after it at 113, the model refreshes at 111 and holds the I/O to 116, so
a pending refresh does not beat an OUT whose I/O is about to issue there; the `refresh_lead` rules were read on F18's
prelude-side cells and the chain body puts the OUT in states they never saw. The F27 FCh misses were the thirty-sixth
fit's material (the next section): the overfill's mechanism, the empty frame's and the ECh misses' readings there
correct the ones given here.

### The I/O sequencer's steps under a refresh: four enums, two new values, the thirty-sixth fit (F27, 2026-10-28)

The eleventh fitter stage (WP58; `fit.py` `stage11`, `F27_ENUMS`, `F27_SWEEP`, `F27_INTS`, the corpus guard as in
stages 9 and 10) fitted F27 from the thirty-fifth fit: a grid over the six enums below (216 candidates, the top two
descended over `in.lead`, `out.lead` and `refresh_stall`), then the sweep over those and the six refresh rules F27
probes, the three integers descended inside every move. **F27 goes from 646 to 778/1,072** (ECh 265/268 unchanged,
FCh 381 → 513/804), no F27 run overfills the queue any more (every generated F27 chain runs within the six bytes
under DEFAULT and under the fit), and the fit changes no integer. The grid's 216 candidates were scored at the
input's integers; the sweep at the final config moved nothing (778 with 0 moves, 0 of 2 corpus-guard moves
refused).

**What the model lacked.** The overfill was not a fetch into a full queue during the IN's lead or read. With a
refresh pending while an IN counted its setup, the model held the refresh to the IN's ready clock, where it beat the
fetch the IN's I/O had been holding; `refresh_after` then ran that fetch ahead of the IN and `refresh_io_run=pair`
committed a second word with the queue full, and the queue overflowed later (clock 251 of
`F27-push-fc-port-inb-n1-pO-w0`, in the END block). In silicon the refresh goes earlier, on one of the IN's setup
clocks, no pair follows, and the I/O issues 5 to 7 clocks after the refresh starts. The readings are one mechanism:
**a posted I/O request's sequencer has steps**, every second clock back from the issue its setup gives (from the
clock `setup − 5` after the post: the third clock after a port form's post, the second after a DW form's, four
clocks before an unhindered issue), restarted on the clock after any bus cycle that runs during the setup, the post
clock itself a step. A pending refresh beside such a request (port or DW form, the EU not in HALT) starts only on a
step; after a refresh in its setup an IN's I/O issues only on a step; and a refresh's last clock does not count toward
the setup when that would end the count on a step. Beside an OUT, whose request is detached from the EU, the step
takes the refresh whatever the EU's own boundary rules say. Two existing rules got a value each: the beaten fetch's
back-to-back pair runs beside an OUT only and only with a byte of room counting the byte the decoder is still about to
take, and the post-clock hold applies beside a beaten fetch too, given back when that fetch runs ahead of the request
on the clock after the refresh. One port rule got a value: an I/O already counted out and waiting only for the bus
that frees on a port take's clock issues there instead of being relatched (no refresh-off run has this state).

| Field (`sim/config.py`) | Options (fitted in bold) | Mechanism | Flipped at the final fit |
| --- | --- | --- | --- |
| `refresh_io_step` | any / step / **own** | the pending refresh starts on the I/O's steps only; `own`: beside an OUT whatever the EU's state | any −59 F27, −3 F8, −2 F13, −1 F17; step −4 F27 |
| `refresh_io_stall` | waits / **step** | the refresh's last clock does not count toward the setup when the count would end on a step | waits −53 +6 F27, −11 F13, −2 F17, −1 F8 |
| `io_step_issue` | count / **step** | after a refresh in its setup an IN's I/O issues on a step | count −7 F27 |
| `port_ready` | relatch / **issue** | an I/O counted out, waiting only for the bus freed on a port take's clock, issues there | relatch −16 F27, −3 F8 |
| `refresh_io_run` | none / pair / **pair_out** | the beaten fetch's committed pair beside an OUT only, with a byte of room counting the decoder's pending take | pair −7 F27 and 6 overflows; none −115 +4 F27, −9 F8, −19 F13 |
| `refresh_post` | free / post / **post_beat** | the post-clock hold beside a beaten fetch too, given back when that fetch runs ahead of the request | post −14 F27; free −60 F27, −7 F8, −15 F13, −6 F17, −32 F18 |

Deciding runs (clocks from t_fill, silicon against the model without the value): `F27-push-fc-port-inb-n1-pO-w0`,
the IN posts at 111 and the refresh request comes at 112, silicon R114 I121 F124, the old model R118 F123 F126 and
the overfill at 251; `F27-push-fc-port-inb-n0-pO-w0`, silicon R113 I118, `any` R115 I120;
`F27-out-fc-port-outb-n0-pO-w0`, silicon R113 F118 I122, `step` F115 R118 I123; `F27-push-fc-port-inb-n1-pE-w0`,
silicon R104 F109 I114, `count` I113, `pair` F109 F112 I115; `F27-out-fc-empty-pE-w1`, silicon I110 R113 I122,
`relatch` R111 I116 I126 (the empty frame's reading in the previous section was wrong: the request is raised only at
111, and the model held M0's I/O, counted out since 105, to 113 behind M1's port relatch at 110, so the refresh took
the free bus; the `refresh_lead` rules play no part); `F27-push-fc-room-movawi-n0-k1-pE-w0`, PUSH posts its write
at 104 with the refresh 104–108 beating a fetch the write's setup then holds, silicon W111 F114, `post` W110 F113.
The port-form refreshes in the F27 port ladders all sit on a step; an OUT posted mid-fetch
(`F13-c-out-shlcl8-pO-w1`) takes its refresh at count 5, which the restart after a bus cycle gives, so the step is
a clock rule, not an even count.

**The probed rules at the final fit** (each flipped and rescored): `room_ir_imm` idle −171 F27; `refresh_drop_post`
drop −16 F27 and −15 F18; `refresh_lead_port` lead −18 F27 and −31 F18; `refresh_drop_unit` odd −6 F27;
`refresh_lead` open −77 +2 F27; `refresh_beat_t4` none +2 −2 F27 and −4 F13. The last is a tie on F27 alone and
decided by F13 (the fitter's tie-break over every family: 21,368 against 21,364 corpus-exact), so the previous
section's "undecided" becomes t4 confirmed, and `refresh_drop_unit` moves from weakly confirmed to confirmed.

**Scorecard** (scratchpad wp58/score-F27-wp58.txt): 778/1,072, ECh 265/268, FCh 513/804; FCh pE 278/402, pO
235/402; FCh w0 171/268, w1 197/268, w2 145/268; by series `port` 206/288 (125 before), `unit` 120/180 (107), `room`
98/180 (78), `beat` 80/144 (66), the empty frame 9/12 (5). FCh by frame and cell:

| Frame | pE w0 | pE w1 | pE w2 | pO w0 | pO w1 | pO w2 |
| --- | --- | --- | --- | --- | --- | --- |
| PUSH | 57/67 | 56/67 | 46/67 | 53/67 | 45/67 | 55/67 |
| OUT | 28/67 | 47/67 | 44/67 | 33/67 | 49/67 | 0/67 |

**The 294 misses** (wp58/miss-final.txt), by cause: (1) **the M0 marker OUT at pO w2 under FCh, all 67 OUT-frame
runs** of that cell, and the same state in 4 F8 and 15 F13 runs: silicon R81 F94 R99 I104, model F96 R101 I106; the
refresh 81–85 lies inside `SHL AW,CL`'s tail and over the OUT's start, the model holds the EU from 83 to 86, and
silicon's first fetch after the marker's post comes two clocks earlier, which fits a port take at 89 against the
model's 91 (the OUT starting at 84 against 86). Two rules were tried and rejected: the instruction start as a seam
when `wbsync` follows (−14 F27, −1 F8, +5 F13: the take then starts a clock early) and t4 for back-to-back fetches
(−272 corpus). One state, 86 runs, left as a finding: a probe of the shift's tail under a refresh before the OUT is
the read. (2) **The END block, 30 runs**, the corpus's END shapes (R129 against 131 after the closing LS's fetch run;
the pO w1/w2 single-fetch differences). (3) **The body, 197 runs** including the three ECh: the fetch after a 3-clock
beaten fetch a clock late in silicon (19 runs; R103 F108 F112, model F111: t4 for back-to-back fetches loses 272
corpus runs, so this state needs a distinguishing read), PUSH's write a clock early (12; W126 against 127), the I/O
against the fetch order after refresh plus fetch (12; OUT frame w1: silicon I140, model F136 I141), a refresh a clock
late after two fetches (11), the shift-exit fetch two clocks early (11; R137 F145, model F147), the rest in groups of
2 to 8. The three ECh misses are unchanged and kept as findings (no rule tried for them keeps the other families
identical): `out-ec-beat-ds1-n0-pE-w0` is F25's group E again; in `out-ec-beat-movr-n0-pE-w0` the fetch is issued
on `MOV DW,imm16`'s first take, a delivery clock (silicon F91, model F90); in `push-ec-room-movcl-n0-k3-pO-w0` the
third `MOV CL` starts with a byte latched behind a full queue and PUSH posts on the clock before that byte enters,
which `latch_start` covers only for a clocks-step start (W104 against 103). Knob dependence: no integer's best value
differs by parity, waits, k, marker, family or n; the new rules carry no per-knob value.

**The nothing-lost gate, run twice** (the agent's wp58/gate/ and the overseer's wp58r/gate.txt, `score --show 5000`
per family under the tracked and the new fit, `cmp` and a run-by-run set difference): F0, F0w, F1–F7, F9–F12,
F14–F16, F18–F23, F25 and F26 byte-identical; F8 29 → 35/48, F13 386 → 399/462, F17 749 → 752/798, each gains-only
run by run; F27 646 → 778 with 122 runs gained outright, the 16 overflow runs now scored (10 of them exact) and no
run lost (the six runs that appear as new misses in the set difference are overflow runs of the old fit, which the
listing cannot show as misses). F0–F22 18,961 → 18,983/19,142; the six F22 misses stand; the refresh-on misses in
F8/F13/F17/F18 go from 175 to 153; END and every refresh-off run untouched; no per-run alignment.

**The thirty-sixth fit** (`fit.json`, 2026-10-28; scratchpad wp58r/fit-36.json, the fitter's own stage-11 output,
md5 016de626) is the thirty-fifth with the four new fields and the two new values (`refresh_io_step=own`,
`refresh_io_stall=step`, `io_step_issue=step`, `port_ready=issue`, `refresh_io_run=pair_out`,
`refresh_post=post_beat`), 224 fields, no integer changed: **21,368/22,068 over the 27 scored families**
(F0–F22 18,983/19,142, F23 255/360, F25 446/588, F26 906/906, F27 778/1,072). `families.UNMODELLED` is empty. The
frozen package was regenerated from it and `freeze --verify --jobs 8` is bit-identical over all 22,068 runs (60 s);
447 tests pass (`test_sim.RefreshOnProbesF27`, 12 tests: every F27 chain within six bytes under DEFAULT and the fit,
the IN under a refresh exact, one test per new value against its alternative on a named run, the END's `OUT DW` in
HALT not stepped, refresh-off runs never seeing the rules, the defaults the old model;
`test_chains.test_f26_and_f27_are_modelled`). The code: `arbiter.py` `io_stepped()` and `io_step()` (the steps, with
a three-cycle look-back for a refresh in the setup on the issue test), the request fields `io_stall`, `eu_halted`
and `beat_ext`, the refresh's last clock under a step in `counts()`, the step gate and `own` in `_refresh`, the IN's
issue gate in `_choose` and the `post_beat` give-back on the fetch issue; `eu.py` `refresh_ok` (an IN's wait takes a
refresh on its steps), `refresh_cost` (`post_beat`), `_port_take` (`port_ready`), `io_stall` set in `_post` and read
with refresh on only; `queue.py` the `pair_out` condition and `_taking()`.

### The refresh at a unit's exit before an OUT, the beaten fetch's successor, the d16 group hold (F28, F29, 2026-10-28; the thirty-seventh fit)

Two probe families (WP59, generator comment blocks in `families.py`, scratchpad wp59/) for the states the thirty-sixth
fit left: F28, refresh on, 1,088 runs (the ECh twins 272/272 exact, the FCh runs 301/816), and F29, refresh off, 456
runs (309/456). All 171 acquisition repeats matched; no chain overfills the model's queue under the fit (under
`refresh_io_run=pair` nine F28 runs would). Scored with the thirty-sixth fit and no free parameter
(wp59/score-F28.txt, score-F29.txt; the overseer rescored both): F28 by series `empty` 5/6 PUSH and 4/6 OUT, `fence`
38/42 and 11/42, `tail` 102/216 and 52/216, `beat` (OUT only) 89/288; FCh by cell PUSH 21, 28, 22, 21, 21, 32 of 44
and OUT 19, 38, 44, 14, 38, 3 of 92 at pE w0..w2, pO w0..w2. F29: `empty` 12/12, `pi` 168/168, `dio` 114/144, `gih`
15/132. The corpus is 23,612 runs over 30 family lists, 22,250 exact over the 29 scored families.

**The flips** (one field at a time from the thirty-sixth fit): on F28 `room_ir_imm` idle −79, `refresh_io_run` none
−114 +4 and pair 0 with nine overflows, `refresh_io_stall` waits −35 +3, `port_ready` relatch −32, `refresh_lead` open
−31 +4, `refresh_io_step` any −24 +1 (step 0), `refresh_post` free −14 (post 0), `refresh_lead_port` lead −14,
`refresh_drop_post` drop −10, `refresh_drop_unit` odd −6, `refresh_beat_t4` none −2, `io_step_issue` count 0: every
fitted value confirmed or untouched. On F29 `disp_io` none −6 (the base+index+d16 store at n = 0 only), `port_issue`
False −6 (the `noo` cells under OUT at 0 waits, one per n, alternating parity: six deciding cells beside F7's and F26's
one each), `grp_io_hold` False 0 (its `dw` TEST cells miss either way).

**The refresh at a unit's exit before an OUT (F28 `fence`, `tail`; 515 FCh misses, mostly two states).** With d the
model's OUT start minus the refresh's start, the model anchored to silicon's refresh grid:

- **State A, 160 runs: the refresh ends on the clock before the model's OUT start (d = 5), and silicon's first fetch
  after it comes two clocks earlier.** The 89 M0 pO w2 OUT-frame runs are this state. Of every F28 FCh OUT at d = 5,
  160 show it, 35 are exact (mostly OUTs after `MOV r16,imm16`, that is with no unit before the OUT; behind a unit the
  DW-form OUTs and four PUSH-frame `shlcl8` cells) and 34 diverge earlier. It shows at every wait and parity, with M0,
  `OUT 40h,AL` and `OUT 40h,AW`. Readings: `F28-out-fc-fence-cl27-n0-pE-w0` (R72, the model's M0 start 77): silicon
  F80 R89 I94, model F82 R87 I95; `F28-push-fc-tail-mulu-outb-n0-pE-w0`: silicon F149 R152 I157, model F151 R154 I159.
- **State B, 76 runs: a refresh the model starts on the OUT's first clock (d = 0) or second (d = −1) starts on the
  OUT's third clock in silicon.** All 28 d = −1 cases and 48 of the d = 0 cases (the other d = 0 OUTs are mostly not
  behind a unit). Readings: `F28-out-fc-fence-cl26-n0-pE-w0`: silicon R74 F79 R88 I93, model R72 F77 I86 R89;
  `F28-push-fc-tail-mulu-outb-n0-pO-w0`: silicon R146 F151 I158, model R144 F149 I156.
- **The fence ladder sweeps both cleanly**: over the OUT-frame fence and empty cells, 11 of 11 d = 5 cells are A and
  8 of 8 d = 0 / −1 cells are B; the other cells are exact or miss otherwise (d = 7, −8, −5). Rows CL 24..31, columns
  pE w0..w2 then pO w0..w2 (b a body miss of another kind, M another M0 miss, E the END block):

  | CL | pE w0 | pE w1 | pE w2 | pO w0 | pO w1 | pO w2 |
  | --- | --- | --- | --- | --- | --- | --- |
  | 24 | b | = | b | b | = | A |
  | 25 | B | = | = | b | = | M |
  | 26 | B | B | = | b | = | = |
  | 27 | A | A | B | B | B | = |
  | 28 | b | A | A | B | A | = |
  | 29 | b | b | A | A | A | B |
  | 30 | b | = | b | M | b | A |
  | 31 | E | = | = | = | = | A |

  So A is one state: the refresh covers the unit's last clocks up to the OUT's start and silicon does not lose the two
  clocks the model's hold costs (the OUT starts while the refresh's two wait clocks still run, the model after its last
  clock); B is its neighbour: a refresh requested at the OUT's start goes two clocks into the OUT in silicon where the
  model admits it on the OUT's first clock. What varies them is the refresh phase alone; count, n, parity and waits
  matter only through it. Deciding cells: for A the fence cells `cl27` pE w0/w1, `cl28` pE w1/w2 and pO w1, `cl29` pE
  w2 and pO w0/w1, `cl24`/`cl30` pO w2, plus 141 `tail`/`beat` runs; for B `cl25`/`cl26` pE w0, `cl26` pE w1, `cl27`
  pE w2 and pO w0/w1, `cl28` pO w0, `cl29` pO w2, plus 68 runs. The ECh twins are all exact.
- The other F28 groups (wp59/class-F28.txt, rel-F28.txt): the I/O a clock late in silicon with a refresh 7–8 clocks
  before the OUT or 4–5 clocks into its setup, 48 (`F28-out-fc-tail-mulu-outb-n0-pE-w0`: I160 against 159); silicon
  refreshing on the clock the model fetches, 47 (`F28-out-fc-beat-adddwi-n0-k3-pE-w0`: R121 F126 against F121 R125); a
  refresh inside the shift's count loop two clocks earlier in silicon, 20 (`F28-out-fc-tail-shlcl16-outb-n1-pE-w0`:
  R119 against 121); a refresh a clock early, 31; the `adddwi` cells with the refresh four clocks early, 12; groups of
  2 to 10 and the END block, 24.

**The beaten 3-clock fetch's successor (F28 `beat` and 881 corpus instances at 0 waits in F8, F13, F17, F18, F27).**
Each instance is a refresh at X, a 3-clock fetch at X+5 and the next fetch. **When the decoder loads the IR on X+8
(the beaten fetch's delivery clock) silicon's next fetch is at +3, about 1,100 instances; when the EU takes an operand
byte with no IR load on X+8 it is at +4, 28 of 28 instances in both frames and every series** (the model gets 11 right
and 17 wrong); and when an imm-class instruction runs on X+7 with room 2, room 1 on X+8, no take and no new start on
X+8, silicon is +4 in 34 of 34 OUT-frame instances (the model +3), while a `MOV r16,imm16` of the train starting on
X+8 gives +3 (12 of 12, and 4 PUSH-frame). So the successor goes on time only when X+8 is an IR load or an
instruction start, and late when X+8 is an operand take or idle inside an immediate form: room and the decoder's
take decide it, not the fetch's back-to-back-ness alone. The silicon-late, model-on-time instances are 54: 35 in F28
(the OUT-frame `beat` cells `movawi`/`movdwi` n0/n1/n3 at k ≥ 2, n2 with the take, `adddwi` n1..n3) and 19 in F27 (the
`room` movawi/movdwi cells, `beat` ds1/movr n1/n4/n5, `push-room-adddwi-n0-k3-pO`). Readings:
`F28-out-fc-beat-movawi-n2-k1-pE-w0` (an operand take on X+8): R103 F108, silicon F112, model F111;
`F28-out-fc-beat-movawi-n0-k2-pE-w0` (no take): the same, then silicon F115 R119 F124, model F114 R121 F126. 116 other
`beat` misses are at 1 and 2 waits and in other states.

**F29.** `pi`: all 168 exact; the six `noo` cells under OUT decide `port_issue`; the `oo` cells decide nothing.
`dio`: the four stores' n-ladders all exact; only the base+index+d16 store at n = 0 decides `disp_io` (−6). In the
`dw` cells the d8, base+d16 and direct takes sit on the DW OUT's issue clock at pO, but every pO `dw` cell misses for
another reason (G1 below); at pE base+index+d16 (load and store) has the fetch after the DW I/O a clock late in
silicon, 6 runs (`F29-out-ec-dio-dw-stbixd16-n0-pE-w0`: F96 D99 against F95 D98), the d8, base+d16 and direct pE cells
exact. So base+index+d16 is still the only form that shows a hold, and whether it is "a take on the issue clock" is
not settled: the model's take in those pE cells is two clocks after the issue. **G1, 45 runs, every `dw` cell at pO
with all 15 X forms at every wait: `OUT DW,AL` right after the M0 OUT at pO issues before the fetch in silicon**
(`F29-out-ec-dio-dw-stbwd8-n0-pO-w0`: silicon I85 I92 F95, model I85 F90 I93); X plays no part; no rule probes this
state. **`gih`, 117 misses: the plain group forms with a d16 displacement (INC, NOT, SHL ,1, NEG, DEC `[BW+200h]`)
delay a fetch by three clocks, which the model never does for RMW forms.** At n = 0 pO silicon F91 D94 D99 against
F88 F91 D94 D99 (`F29-out-ec-gih-incd16-n0-pO-w0`), matching TEST [0C00h]'s F91; at n = 1 pO and n = 2 pE the fetch
is three later (95 against 92, 98 against 95); at n = 1 pE silicon fetches at 94 before the read and its post-write
fetch is at 114 against 106 (`F29-out-ec-gih-incd16-n1-pE-w0`); at n = 2 pO w1/w2 the read comes two clocks earlier;
n = 0 pE is exact; the `dw` RMW cells at pE F98 D101 against F95 F98 D101 (15 runs), the `dw` TEST cells a clock late
(6). Because the effect persists at n = 1 and 2 with M0's I/O ten or more clocks away, it reads as a `[BW+d16]`
group-form fetch hold rather than an I/O-recovery hold; no PUSH control was run, so whether an I/O is needed at all is
open. The `[BW]` forms stay exact in F26.

### The string and block forms: a bus stream that takes no bytes (F24, 2026-10-28; the thirty-eighth and thirty-ninth fits)

F24 (WP66, generator comment block in `families.py`, scratchpad wp66/) puts the seven string forms under the OUT
marker's cost frame: 912 runs at 0.25 s each, every one of the 93 repeats identical up to a constant tick shift. The
corpus is 24,524 runs over 33 family lists. The forms sat in `forms.UNMODELLED_FORMS` and F24 in `families.UNMODELLED`
(the fitter's corpus guard and the simulator leaving them out) until the model of 2026-10-29 (WP67; both are empty
now). The normaliser's expected-access
walk (`normalize._StringState`, `string_elements`) tracks AW, CW, DW, IX, IY, DS0 and DS1 and the data page's contents
through the chain and expands each string form to its per-element bus cycles; an unknown count, port, address or
compared operand raises rather than guesses. Its first pass over silicon mismatched all 192 compare runs and settled
two facts, now in the walk (912/912 match):

- **CMPBK reads the destination first.** Every element is a read at IY, then a read at IX, with and without REP, byte
  and word (the 8086-order assumption, source first, was wrong).
- **Every repeated compare reads one element past its end.** REPE and REPNE CMPM and CMPBK read the next element's
  operands, at the next IX/IY, in the same order and at the steady cadence, after the element that terminates the
  repeat, whether CW reached 0 or the condition failed: the loop issues element k+1's read before element k's
  termination test takes effect and discards it (`StringRun.overrun`; `str_overrun`, `str_overrun_gap` in derive).
  With CW = 0 there is no read at all; the unprefixed compares and the other REP forms run exactly their elements.

**Facts** (wp66/report-F24.txt, facts-F24.txt; clocks relative to M0, costs against each chain's baseline, the knob
`baseline` naming it):

- **Per-element spacing under REP**, aligned, the same at both parities: STM 9 + w; LDM 11 + w; CMPM 12 + w, but
  10 + w from element 1 to element 2; MOVBK and CMPBK 18 + 2w (two memory cycles 9 + w apart); INM and OUTM 14 + w
  (the I/O cycle stays at 0 waits). Byte and word cost the same when aligned. cost(n) = A + n · spacing exactly from
  n = 4 to 8 (STM 63 → 99, MOVBK 99 → 171 at w0) and to 16 (MOVBK 171 → 315).
- **The REP setup.** The first element's first cycle comes 27–28 clocks after M0 at w0, 29–31 at w1, 31–34 at w2,
  odd parity a clock or two earlier at w1/w2; unprefixed 9–11. The intercept A at w0: STM 27, MOVBK 27, LDM 28,
  INM 28, OUTM 30, CMPM 42, CMPBK 52 (the compares' A holds the overrun read and a slower end). Unprefixed singles cost
  15 (STM), 17 (LDM), 21 (CMPM), 23 (INM, OUTM), 26 (MOVBK), 28 (CMPBK) at pE w0, one or two less at pO; an unprefixed
  pair costs more per instance than REP n = 2 (STM 13–14, MOVBK 23–24, CMPBK 25–26, INM 20–21, OUTM 22 at w0: the
  second instance is decoded again).
- **REP with CW = 0** costs 17 / 19 / 20 (w0 / w1 / w2) at pE and 16 / 18 / 19 at pO for every form, INM/OUTM one
  more at w0; no data cycle; the only fetch is M1's, three clocks before its OUT.
- **No fetch inside any REP stream** (`str_fetches` 0 in all 738 element runs): the queue is full when the stream
  starts and a string element takes no bytes, so no request arises; the REP setup lets the post-M0 refill finish
  first, and the drain series (d = 2, 4) changes the cost by −1 or 0. Occupancy at M1 is 2 in every run. The only
  mid-stream fetches are the one between an unprefixed pair's instances (42 runs). Whether the arbiter lets a fetch
  in beside a stream with a short queue is not testable with REP (its setup outlasts the refill); F6 covers the
  priority question.
- **The restart after the stream** is M1's decode fetch, three clocks before its OUT: 23 / 24 / 25 clocks after
  the last cycle for STM, MOVBK, INM; 26 / 27 / 28 LDM; 21 at every wait OUTM; the compares 30–31 / 31–32 / 32–33
  from the overrun read. Odd parity restarts five clocks earlier in every REP case.
- **Odd word:** one extra 3 + w bus cycle per odd operand per element, no overlap: MOVBK one side odd 21 / 24 / 27,
  both 24 / 28 / 32 (18 / 20 / 22 aligned); STM IY odd 12 / 14 / 16; LDM IX odd 14 / 16 / 18; CMPM 15 / 17 / 19;
  INM, OUTM one side odd 17 / 19 / 21; CMPBK both odd 24 / 28 / 32.
- **Early exit** on the condition costs one clock less than running CW out to the same element count (REPE CMPM
  one element 53 against REPNE CMPM n = 1 54; CMPBK one element 69 / 70; two elements 87 / 88 CMPBK, 65 / 66 CMPM;
  three bytes 105 / 106, 77 / 78), and the next fetch is one clock earlier (30 against 31). At n = 2 over the
  pattern, where both conditions end the repeat on the same element, the cost equals the n = 4 pattern case.

Open: the CMPM first-to-second spacing (10 + w against the steady 12 + w); REPC/REPNC (65/64) need a known carry
after the fence and are left to a later family. The model is the thirty-ninth fit ("The thirty-eighth fit" and "The
thirty-ninth fit" under Model): the str_* classes as templates (setup, element, overrun as an enum, exit, the n = 0
check), the unprefixed form's element as the CW-ending one, the string I/O write through the data latch and the
string requests counted as a DW form's, 778/912, fitted under the corpus guard with nothing lost elsewhere.

### Probes for the facts-only shapes: the odd-address transfer, 8E behind the OUT, the INM/OUTM setup (F30, F31, 2026-10-30; the forty-first fit)

F30 (WP73; 246 variants, 1,476 runs, w0/w1/w2 × pE/pO, refresh off; 150 repeats identical up to a constant tick shift,
one strobe-only difference) varies one thing against a control for each shape the thirty-ninth and fortieth fits left as
facts. Under the thirty-ninth fit 909/1,476 (`str` 263/342, `odd` 100/276, `seg` 264/336, `br` 54/96, `nt` 54/144, `cr`
30/72, `lea` 126/192, the empty frames 18/18), under the fortieth's candidate 959 (`br` 78, `lea` 152, the rest
unchanged). F31 (the same day; 39 variants, 234 runs, 24 repeats identical) adds the two controls the readings below
asked for, 66/234 under both fits (the empty frame 6/6, `alf` 12/156, `lone` 48/72). The corpus is 26,234 runs over 33
lists. The forty-first fit (WP76, the same day, Model "The forty-first fit") encodes seven of the readings below as
mechanisms: F30 1,349/1,476 (`str`, `odd`, `seg` and `br` all exact; `nt` 54/144, `cr` 60/72, `lea` 167/192), F31 234/234. Tables in scratchpad wp73/facts-F30.txt and wp73/f31/facts-F31.txt (clocks rel t_fill, silicon against both
fits), `runs.json` every run's silicon and both models. Readings, in machine terms where the probes decide:

- **The REP INM/OUTM setup absorbs one wait clock of a fetch in flight** (F24 shape 1). First string cycle minus the end
  of the last fetch before it, n = 1 word: with the bare lead at pE, INM 16/15/15 at w0/w1/w2 (the model 16/16/16) and
  STM 16/16/16; at pO, and behind every other lead (a drainer or `ADD DW,0` before `MOV CW,n`, one or two NOPs or
  `SHL AW,8` between `MOV CW,n` and the REP form) all three classes start a constant 19 after it at every wait and both
  parities (OUTM 20 at pO). The bare pE lead is the only cell where a refill fetch, the third and back to back, is still
  on the bus during the REP setup: INM/OUTM's setup overlaps min(w, 1) wait clocks of a fetch in flight, STM's none.
  F31 `lone` (leads that put exactly one refill fetch, not back to back, inside the setup, and one with a back-to-back
  pair late in it): in all 72 runs INM = STM to the clock (OUTM one more, its read first), so a lone fetch with wait
  states or a later pair is not enough: the gain needs the setup to start while M0's own refill run is still going back
  to back, its third fetch issuing on the clock after the second. New miss, F30's separators and F31's long-gap leads
  alike: where the setup contains no fetch and starts after a long gap both fits are +1 late for all three ops
  (silicon last + 22 at w0, + 25 at w1/w2; model + 23/+26), and under OUTM the model adds a fetch silicon lacks.
- **The split last cycle's extra clock is the stream's** (F24 shape 2). From the stream's last cycle end to the next
  fetch at pE, w0/w1/w2: STM-iy, MOVBK-iy, MOVBK-ixiy and INM-iy 22/21/21 at M1 and the same +1 at w0 behind a NOP
  (19/18/18), a register form (12/11/11) or a second REP form (16/15/15); CMPBK-ix and CMPBK-ixiy 30/29/29; CMPBK-iy,
  CMPM-iy, LDM-ix, MOVBK-ix and OUTM-ix constant. The w0 clock belongs to the end of a stream whose last cycle is a split
  write (or CMPBK's second read, through IX), not to a split single read or a split first cycle, and not to M1. New miss:
  with any follower but M1 both fits put the next fetch +1 (w0) or +2 (w1, w2) late for every probed form, split reads
  included. F31 `alf` (the same forms with IX and IY even, the same followers): both fits are +2 in every aligned
  follower cell (all forms, waits and parities) and exact in every end cell, so the follower miss does not need an odd
  operand: the stream's exit frees the decoder for the next instruction 2 clocks earlier than modelled before any
  successor but the port-form OUT, whose own port take hides it when M1 follows. Shape 2 is a pure +1 on top of that
  aligned exit (odd = aligned + 1 at w0 when the element's last cycle is a split write or CMPBK's split IX read), the
  same across every follower.
- **8E behind the OUT holds the OUT's I/O a clock** (F25 E). M0's I/O at pE is 84/85/86 for every 8C form, every form
  behind a NOP and `PUSH SS ; POP SS`, and 85/86/87 whenever 8E (MOV sreg,r/m) directly follows, for every legal sreg
  field, both operand kinds, k = 1 and 2; pO is 85/86/87 throughout and the PUSH marker never moves. Decoding 8E behind
  the OUT holds its I/O issue one clock, independent of the sreg and the operand, visible only where the I/O would
  otherwise issue a clock early. `MOV [BW],sreg` (8C to memory, every sreg alike) writes a clock after the model in OUT
  pO, PUSH pO and PUSH pE behind a NOP, and is exact where the write issues on the clock after a fetch's end: the sreg
  store's request is one setup clock later than `MOV [BW],AW`'s, hidden when the write waits behind a fetch. The 8C
  register forms are exact everywhere.
- **An odd-address BR short raises no prefetch before its flush unless a fetch is in flight** (F23 A, E). Under the
  fortieth's candidate the model's extra fetch remains exactly where BR short sits at an odd address with no fetch in
  flight at its start: the bare OUT frame at pO, pad1 at pE and pad2 at pO (started on the I/O issue clock), the
  MOV-direct frame behind a NOP at pO (started on an idle bus); silicon fetches nothing between the start and the
  target, the model 8 clocks early (F96 against F88). Every even-address BR short is exact, and so is an odd-address one
  whose start lands on a fetch's issue. The callret residual is the same rule: after the RET's refill both fits add one
  fetch silicon lacks exactly when the RET's target is at an odd address, independent of the NOPs before and after.
  From a full queue (`SHL AW,8` in place of the NOPs) the RET's stack read is a clock later than the model in all 12
  cells.
- **BNE and DBNZ not taken differ in kind** (F23 C, D). BNE not taken under OUT at pE: silicon's third refill fetch is
  back to back (F93) where the model's is at 98, or 95 with NOPs after, and M1 comes later in silicon (I107 against
  105); each further BNE costs silicon 8 to 9 against the model's 8. DBNZ not taken holds the prefetch about 5 clocks
  longer than the model (OUT pE F99 against 94, PUSH pO F96 against 91) and finishes 1 to 2 clocks earlier. BNE releases
  the fetch at once and runs longer in the EU; DBNZ holds the bus unit through its CW test and ends sooner, which is why
  one `nexec`/`nfgap` pair cannot serve both.
- **LDEA's d16 residual follows its address parity** (F25 B, C). `[BW+200h]` and `[0C00h]` under PUSH at pE: M1's write
  −3/−4 in the model alone and with a NOP after, exact with a NOP before; k = 2 `[BP+200h]` exact everywhere; under OUT
  the d16 and direct modes behind a NOP (LDEA at the odd address) are −8 at pE w1/w2 in both fits. OUT pE w0 mod 00 alone
  −4, −1 behind a NOP, pO fixed by the fortieth's candidate; a drainer before LDEA [BW] gives −2 at every wait.

### The 0F page and the register miscellany: costs read as facts, modelled the same day (F32, F33, 2026-10-30)

F32 (WP74; 143 variants, 858 runs) and F33 (175 variants, 1,050 runs), both generator-only when acquired
(`families.UNMODELLED`, `forms.UNMODELLED_FORMS`: `score`, `fit`, `freeze` and the corpus guard skipped them until the
decoder gained the forms the same day, WP78, Model "The forty-second fit"; HDL plan Phase E items 4 and 5), the cost frame under the OUT marker with a PUSH subset, k = 1, 2, w0/w1/w2 × pE/pO, refresh
off; 10 % repeats identical up to a constant tick shift. Tables in scratchpad wp74/facts-F32.txt and facts-F33.txt (cost
at k = 1 and 2, slope and intercept per parity and wait, interleave strings, data cycles against M0 and the last fetch).
The corpus was 28,142 runs over 35 lists (29,738 over 36 with F34, below). PUSH minus OUT stays within −4..+3 and the data cycles keep their offsets from
the fetch end, as in every earlier family. Readings:

- **Bit-field registers are not reduced to 4 bits.** With DL = 78h and DH = 56h (the default DW), EXT DL,7 cost 303
  clocks against 65 at a 4-bit offset, INS DL,7 861 against 87, and INS wrote FFFFh into IY + 2: silicon uses the whole
  byte of the offset and width registers where the data book says the low 4 bits. The bit-field chains were re-taken
  with DW = 0608h (the first pass is kept in wp74/bak/, not in the corpus).
- **Bit ops on a register** (TEST1/CLR1/SET1/NOT1 AL/AW, CL or imm index): 11/9 (CL) and 10/10 (imm) at k = 1 with a
  slope of 8–9, the same for all four ops and both widths: an ordinary register form with one more opcode byte. **In
  memory** they are the existing load_alu (TEST1) and rmw shapes, byte costing the same as word; the CL form costs 2–3
  more than the imm form (the read at R9 against R11); CLR1 is a clock longer than SET1/NOT1, between the read and the
  write; for SET1 the base+index mode costs the same as [BW], d16 and direct one more.
- **BCD strings** (ADD4S/SUB4S/CMP4S, CL = 2, 4, 8, 16 digits): ADD4S and SUB4S 30/33/36 clocks per byte pair at w0/w1/w2
  plus a setup of 24, CMP4S 25/27/29 plus 25. On the bus each pair is a byte read at IX, a read at IY 9 clocks later and a
  write 12 after that; no fetch inside the stream, every cycle's wait clocks add to the pair, no parity effect, IX/IY/CL
  unchanged after. A new template, a byte-element loop.
- **Digit rotates**: ROR4 is 4 clocks longer than ROL4 in both forms; in memory the read-to-write gap is 14 for ROL4 and 18
  for ROR4.
- **Bit fields** (EXT/INS, register and imm4 forms, seven offset/width cases): the cost depends on (offset, width) alone
  and matches docs/v35s-eu-timing.md's formulas plus 2 (EXT) or plus 1 (INS); the register forms cost the same as the
  imm4 forms for the same operands; the operand order is the data book's (the offset in ModR/M bits 2:0), confirmed by
  INS's written data. Crossing into the next word reads R…R 29 clocks apart for EXT and read/write/read/write for INS,
  whose write lands 70–78 clocks after its read; IX/IY step by 2 when the offset passes 15. New templates.
- **A DS1: prefix** before an 0F form adds 1–4 clocks.
- **One-byte register forms** (F33): INC/DEC r16 (SP included), CVTBW, CLC, STC, CMC, CLD, STD cost 4/7/13 at k = 1/2/4,
  3 clocks per instance where NOP is 4; INC/DEC r8 costs what MOV CL,imm8 does (6); INC/DEC [BW] is the rmw shape, byte
  as word. ADJ4A/ADJ4S 13, ADJBA/ADJBS 21, CVTBD 24, CVTDB 22, CVTWL 13. CLI 8; STI 17 with a slope of 13: EI holds the EU
  about 10 clocks longer than DI, with no bus effect.
- **Multiply and divide** (slopes): MUL CW 44 (10 more than MULU), DIVU CW 42, DIV CW 61; the [BW] forms the register
  form + 14 / + 8 / + 6, the memory read before the immediate's fetch; MUL with an immediate (69/6B) 42/40. MUL at AW = 0
  costs 2–3 more than at 1234h and CVTWL varies by ±1, both confounded with the lead's effect on the queue. Nothing
  trapped.
- **REPC/REPNC** (65/64, CMPM/CMPBK word, STC or CLC before `MOV CW,n`, n = 0, 1, 2, 4, two stored patterns forcing an exit
  at element 2): REPE/REPNE with the carry in place of Z, every cell equal to F24's cell of the same exit kind (the STC/CLC
  byte flips the parity, F33 pE = F24 pO): CW running out 53/65/89 (CMPM) and 69/87/123 (CMPBK) at n = 1/2/4, the carry
  exit after element 1 52 and 68, the pattern exit after element 2 64 and 86, n = 0 16; a condition exit costs 1 less
  than CW running out at the same element; the overrun read is present in every n ≥ 1 cell; STC against CLC changes
  nothing. No new template: the compare's exit condition is a flag choice.

### Probes for the forty-second fit's miss shapes: one thing varied against a control (F34, 2026-10-30; no fit)

F34 (WP80; 266 variants, 1,596 runs, w0/w1/w2 × pE/pO, refresh off, the OUT marker with a PUSH subset; 164 repeats
identical up to a constant tick shift) is the forty-second fit's probe family, designed as F30 was: for each of the
seven miss shapes left by that fit one probe varies one thing against a control. The frame is `PAD LS M0 <lead> X^k
<follow> M1 LS END`; the leads (none, NOP^1..3, the F6 drainer `MOV AW,1234h`^1..3, `SHL AW,8`, `MOV CL,4`) set the
queue's state at X's start and each stands alone as a control; every byte string but `CMP AW,DW` (3B C2, the BE
probe's flag setter) was already run by an earlier family. 469/1,596 under the forty-second fit (the empty frame and
the leads 66/66, bf 30/384, rbit 53/246, mbit 46/318, inc 119/138, mul 7/108, nt 72/216, cr 76/120). Tables in
scratchpad wp80/facts-F34.txt and readings.txt (per probe the first divergence of every run, the events after M0, X's
first data cycle against the end of the last fetch before it, the next fetch and M1 after X's last data cycle).
Clocks relative to t_fill; residual = model − silicon. Readings:

- **Bit fields** (EXT/INS BL,DH and DL,BH, BL,7 and DL,11; DW = 0608h): the field's first word read is a constant 6
  clocks (register-width forms) or 7 (imm4 forms) after the end of the last fetch before it, behind every lead and at
  every wait (36 of 40 lead × column cells per form); the model's gap is 11 / 9. EXT = INS and crossing = within-word
  at the first divergence. Exceptions: behind no lead at pE a refill fetch already committed runs back to back inside
  the window (F87 F90 R96: the model reads at 96 too but drops F90); behind NOP NOP at pO w1/w2 the gap is 8 / 9.
  The successor's fetch comes 72 (even start) or 77 (odd) clocks after the read for the register forms; the imm4 forms
  at an odd address (the imm byte the first of its word, the next opcode its second) fetch 61 clocks after the read where
  the model waits 16–25 more, at an even address 68 (model +2/+3). The follower (NOP, `MOV AW,DW`, `MOV AW,[0C00h]`)
  does not move the read. Candidate: the field's read is posted at the form's start and issues a fixed setup after the
  bus's last fetch ends, raising no fetch of its own in between; the imm4 forms release prefetch at a fixed clock into
  the span when the queue holds the next opcode's byte.
- **Register bit ops** (SET1/TEST1 AL/AW by CL and imm): TEST1 = SET1 and byte = word in every cell. The CL forms at an
  odd address behind no lead or a NOP (the form's last byte the last of its word) are +7: silicon raises the next fetch
  back to back (F88 F91 I105, model F98); behind `MOV CL,4` or a drainer +1, behind `SHL AW,8` −1. The imm forms show
  the same +7 at an even address (their last byte again a word's last) behind a drainer and NOP NOP (w1/w2). Separately,
  and the same in bf, mbit and mul: when an 0F form's first byte is at an even address behind a lead, silicon's fetch at
  the 0F's take is a clock before the model's (F89 against F90), where the same lead before a one-byte or a non-0F
  2-byte form is exact. The k = 2 second-instance offsets follow that +7 fetch. Candidates (decoder / room rule,
  class-keyed on the page): the room rule raises a fetch on the clock a page form's word-ending last byte leaves the
  queue, and the page take removes 0F and the second opcode byte on consecutive clocks (the model frees the room a
  clock late).
- **Memory bit ops** (TEST1/SET1/CLR1 [BW],CL and [BW],15 word, SET1 [BW],CL byte, four modes): TEST1, SET1 and CLR1
  read on the same clock in all 84 op-comparable cells; SET1 = CLR1 with the imm index; byte = word; [BW+IX] = [BW]. With
  the CL index silicon reads 5 clocks after the last fetch's end behind every lead (2 behind no lead at pE, 8 behind
  NOP NOP at pO w1/w2), with the imm index 2 (0 at l0 pE); d16 and direct 0 or 5. The model splits one timing by class:
  bit1_test / bit1_clr read 3 late at pE and are exact at pO, bit1_rmw (SET1/NOT1) exact at pE and 3 early at pO; behind
  a lead the model raises a fetch silicon does not. The forty-second fit's parity and wait dependence here is the queue
  state at the start, not a per-op cost. Candidate: one fixed setup after the last fetch's end for every page memory
  op (CL 5, imm 2), no fetch raised once the form has started.
- **INC AW / CLC after the OUT** (k = 1..4, n = 0..2 NOPs after): the −1 at pE and the −4 at k = 2 pE w0 appear only
  when M1's OUT directly follows the one-byte form; with a NOP after it every cell is exact; INC = CLC cell for cell.
  Candidate: M1's port byte, taken a clock earlier behind a 3-clock form, lands on the issue clock of the post-M0 fetch
  and holds it (the `port_issue` family of rules); at k = 2 w0 it holds the second fetch until M1's setup.
- **MUL AW,[BW],imm** (6B 07 05 and 69 07 34 12; `MUL AW,CW,5` the control): the read is 1 clock (imm8) or 2 (imm16)
  later than the model in nearly every cell, the register form exact. When the immediate's last byte is the first byte
  of a queue word (imm8 at an even address, imm16 at an odd one at w1/w2) silicon raises no fetch from the read until
  near the multiply's end (R90 F134, model F93: the −41/−42); otherwise it fetches right after the read. Candidates
  (mul_imm): the read is requested after the immediate is taken, a clock per immediate byte; a half-taken queue word
  holding the next opcode keeps the room rule from raising a fetch over the multiply's span.
- **BNE / BE / DBNZ not taken** (`CMP AW,AW ; BNE +0`, `CMP AW,DW ; BE +0`, `MOV CW,1 ; DBNZ +0`, the twin `CMP AW,AW ;
  MOV AW,DW`): BE = BNE in every one of 108 OUT and 12 PUSH cells; the twin and every lead control are exact. The model
  is 2 short on the first fetch after the branch and on M1 at every fill level and with a fetch in flight, 3 short at an
  odd address behind a drainer or NOP^2..3; the one exception is no lead at an even address, where silicon's third refill
  fetch is back to back (+5). DBNZ at an even address is BNE's −2; at an odd address silicon holds the prefetch 5 clocks
  longer than the model and ends a clock earlier (F99 I114, model F94 I115) for every lead, wait and marker. Candidates
  (transfer classes): a not-taken short conditional runs 2 EU clocks longer and releases its fetch request 2 later (one
  nexec / nfgap pair for both); DBNZ at an odd address holds the prefetch as `xfer_odd=idle` does for a taken jump.
- **The RET's refill** (`CALL +2 ; BR ; <filler> ; RET`, the target at either parity, fillers none, NOP, `SHL AW,8`,
  `SHL AW,8 ; NOP`, `NOP ; SHL AW,8`, `SHL AW,4`): the −1 is set by the shift directly before the RET, not by the
  target's parity: all 48 OUT and 12 PUSH shift cells read the return address a clock later than the model, a NOP between
  the shift and the RET makes every cell exact; where the shift starts at an odd address the model also fetches 22 clocks
  early during it. The fetch after the stack read is 8 clocks after its end in silicon and model alike. Candidate (EU):
  a stack read requested on an immediate shift's exit clock is held a clock, as the string exit's `wbsync`.

### The prelude from reset against the chain core (2026-10-31, WP82; no fit)

Not a probe: the chain core running in the Verilator model lane from /RESET
with nothing scripted (HDL plan "The chain core in the model lane";
`replay --core chain --score`) replays every corpus run, and the pre window
(the fetch train from the POP PSW read to clock 0) and the bus before it
are compared with silicon's. The lane is deterministic; silicon's spread is
the fX/8 divider's phase at release. What the comparison reads off silicon
that the model does not have:

- **The reset exit.** First refresh 483–517 ticks after release over the
  corpus (lane 500), first fetch of FFFF0h at 804–832 (lane 820). Silicon
  fetches six words of the reset vector (FFFF0h–
  FFFFAh) before the far jump's target; the lane, with the model's queue,
  four (FFFF0h–FFFF6h). The jump target's fetch (10000h) is 112–140 ticks
  (3.5–4.4 fX/8 states) later on silicon than in the lane: the far jump at
  the slow clock costs more than BR near does.
- **The prelude at the slow clock.** The switch to fX/2 (the PRC store) is
  196–256 ticks earlier on silicon than in the lane (F0-ls-pE-w0: 5,272
  against 5,504); the PUSH 0002h write and the POP read 164–224 and 148–200
  ticks earlier (5,480 / 5,552 against 5,680 / 5,728); the PUSH-to-POP gap
  is 9 clocks on silicon, 6 in the lane. The SFR stores are internal and
  show only as fetch spacing.
- **Equal on every run:** 19 fetches from the jump to the POP read; the 3
  words after the POP PSW fetched before its read (the model's
  `preload(3)`); the refreshes before the POP read, except F13 where 268
  of 462 runs differ by ±1 (264 one fewer in the lane).
- **The refresh counter at the POP read** (lane minus `refresh.POP_COUNTER`,
  mod the interval): FC and F8 preludes +3 at 0 waits, +13 at 1 and 2
  waits; EC +2 at every wait; F0 +4/+1/0, F4 +1/+13/+13, FD (mod 32) +6/0/0,
  FE (mod 64) +2/+2/+7, FF (mod 128) −1/0/+4 (scratchpad
  wp82/logs/pop_counter_f13.txt). The lane's value in the frozen model
  makes every 0-wait refresh cell exact and no 1- or 2-wait cell.
- **In the pre window** of refresh-on preludes the first divergence is the
  POP read itself: 5 clocks closer to clock 0 on silicon at 0 waits (−98
  against the lane's −93), 3 further at 1 and 2 waits (−111 against −114,
  −133 against −136). Refresh-off preludes: the pre window is exact on
  every run.
- **`refresh_any` is a lookahead.** A chain whose own RFM store turns
  refresh on (F17 S/D/W/C, F18 B, F18 EC with a marker) runs the refresh
  controller and templates from clock 0 in the model; the lane, knowing
  only RFM.RFEN live, runs without until the store: 1,416 runs differ
  (F17 66 of 246 equal, F18 B 0 of 864), the counter swap above changing
  none of them.
- **Per family** (runs / model-exact / RTL-exact / RTL = model / pre exact):
  F8 48/37/27/32/0, F13 462/440/290/306/44, F17 798/754/219/238/738, F18
  1,164/1,133/205/208/1,004, F27 1,072/889/684/804/268, F28
  1,088/820/659/816/272; every other list RTL = model on every run with the
  pre window exact; all 29,738/27,112/25,123/27,510/27,432.
- **The model is an oracle for 466 starts:** it decodes a start from the
  image when bytes of the instruction are still on the bus (a memory form's
  trailing immediate, a register form's immediate, three ModR/M bytes).
  Silicon's timing is the model's, so the EU does not wait for them.
- **A pin:** in the column phase of data and I/O cycles the A17/A9 pin is
  0 on silicon even with A9 = 1 (fetches carry A9); A17 is 0 in every such
  corpus cycle. Unprobed; the scorer does not compare it.

### A causal refresh: the lookahead is unobservable (WP84, 2026-10-31; a tie, adopted in the forty-fourth fit)

The model's `refresh_any` (types.py) decides from the whole chain whether the
refresh controller and the EU's refresh templates run from clock 0, so a
chain with an ECh prelude whose own RFM store turns refresh on (F17 S/D/W/C,
F18 B/BD/AC: 1,416 runs) runs them before the store, which a causal core
cannot. Facts over those runs (scratchpad wp84/facts.txt, one row per
family, series, wait and parity; clocks the model's from clock 0):

- **The store** issues its internal cycle at a fixed clock per wait and
  parity: 109/105 (pE/pO) at 0 waits, 116/112 at 1, 125/120 at 2 (W moves 4
  per NOP; AC a little); RFEN takes effect 3 clocks after the issue
  (`rfm_delay`). The next instruction starts on the effect clock in 1,410
  runs and the clock after in 6: the EU waits out the store's 3-clock cycle.
- **The first refresh after the store** is requested 0–32 clocks after the
  effect (0 at the RFT switch's edge, `F17-w-fd-n5-pE-w0`) and starts 0–4
  clocks after its request.
- **Before the store** the model's trace equals the twin's (the same chain
  with the store writing ECh) in all 1,416 runs, and stays equal up to the
  first refresh's start; silicon's trace before the store equals the
  recorded twin's in all 306 runs that have one (F17 E, W ec). No run has
  an instruction started before the effect still running at any refresh
  request or start: nothing the lookahead chooses is ever observed.
- **1,366 of the 1,416 are exact** under the forty-third fit; the 50 misses
  (F18 B, mostly the register shift behind the store at 0 waits and the
  `shl1`/`shli4`/`shlmcl` cells at 2 waits) are the same under both
  structures.

Encoded as `refresh_scope` (sim/config.py, WP84): `any` is the DEFAULT (the
old behaviour); `live` builds the counter for every chain with refresh on or
an RFM store (one with neither can never set RFEN; its counter is
unobservable and the field unread, as the fit cache needs), gates its
requests by RFEN as it stands on each clock (the prelude's value, then each
store's from its effect clock), and keys the EU's refresh templates (chosen
at an instruction's start) and rules on `Refresh.eu_on`: RFEN in force or a
request pending, set at the top of every clock; the RFM store reaches the
controller through `eu.rfc` in both. A switch at the store's issue clock or
at its cycle's last clock gives the same event lists as the effect clock on
all of F17 and F18, so there is no second knob. Fit stage 18 (F17, F18;
`F44_ENUMS`, `F44_INTS` = `rfm_delay`; the grid lists `live` first so a tie
keeps the causal structure) from the forty-third fit with `live`: 1,887 of
1,962 either way (F17 754, F18 1,133), the tie-break 27,838 against 27,838,
the corpus guard refusing nothing; the three-pass gate byte-identical on all
36 lists, flips 0 both ways; the full event lists with the refresh rows
differ in 0 of 4,632 runs over F8, F13, F17, F18, F27 and F28. The
candidate (wp84/fit-wp84.json) is the forty-third fit with
`refresh_scope=live` and nothing else.

**The lane's 1,416 differences are the RTL's**, not the model's: in
fpga/v35s/core/v35_refresh.sv the write's arming (`wr && en`) and the
requests are gated by `en`, and the lane wires `en` to RFM.RFEN live, so
with an ECh prelude the chain's store is never armed and the lane runs no
refresh after clock 0 in any of those runs (its first divergence from the
model is the model's first refresh after the store, in all 1,416). The
causal RTL is `live`'s: the controller always enabled, requests gated by
its own `on`, the EU's refresh input `on || pending` (WP83 takes it).

### The I/O sequencer beside a refresh: F27 and F28's misses read, five enums (WP85, 2026-10-31; adopted in the forty-fourth fit)

Under the forty-third fit F27 misses 183 of 1,072 and F28 268 of 1,088.
Three of F27's are refresh-off (`out-ec-beat-ds1-n0-pE-w0`,
`out-ec-beat-movr-n0-pE-w0`, `push-ec-room-movcl-n0-k3-pO-w0`: the
thirty-sixth fit's findings, unchanged), so the refresh-on misses are 448
(F27 180, F28 268). Facts over them (scratchpad wp85/facts.txt: one row
per miss with the first divergence, the nearest refresh in silicon and in
the model, the counter phase, the EU instruction and step, and the
neighbours at k or n ± 1, the other parity, the other waits and the ECh
twin; clocks relative to t_fill):

- **Every miss is near a refresh:** a silicon refresh starts within 8
  clocks of each first divergence. The divergences avoid the refresh's own
  clocks (counter phase 2–4) and otherwise spread over the 16-clock period:
  no phase keys a shape.
- **The counter grid stands.** In the miss runs every silicon refresh
  starts 0–4 clocks after the model's request clock (`POP_COUNTER`), never
  before it; the lane's phase of WP82 (3 clocks later at 1 and 2 waits)
  would put 4,579 of those starts before their request. The lane's counter
  differs by its own request latency, not the model's grid.
- **No remaining shape keys on the opcode byte or a neighbour.**

Encoded as five enums (sim/config.py, each with the old behaviour as
DEFAULT, the deciding run in its comment and a test in
test_sim.RefreshSequencerF27F28; no integer changed or added), all
conditions of the I/O sequencer when a refresh sits in or beside an I/O's
setup:

| Enum (old → new) | Rule | Deciding run (silicon; old model) | Flip |
| --- | --- | --- | --- |
| `port_ready_count` (ready → count) | the I/O waiting in the slot also issues on the next OUT's port-take clock when its setup counts out on that clock (the clock after a refresh whose stalled last clock moved the count's end there); silicon on the take in 28 of 28 such requests | `F27-out-fc-port-outb-n3-pE-w0`: I/O 125; 129 (128 with `port_refresh=none`) | −27 |
| `port_refresh` (none → late) | a port byte taken on the clock after a refresh cycle's last reaches the port latch a clock late, as `port_landed`'s; silicon issues at the take + 4 in 43 of 43 | `F28-out-fc-fence-cl29-n0-pE-w0`: 98; 97 | −28 |
| `refresh_pair_post` (any → before) | `refresh_io_run=pair_out`'s second back-to-back fetch after a fetch a refresh beat runs only when the OUT posted its I/O before the beaten fetch's issue clock: posted on that clock 0 of 45 pair in silicon, posted earlier 474 of 474 | `F27-out-fc-room-movawi-n0-k2-pE-w1`: I/O 140, no fetch at 136; fetch 136, I/O 141 | −45 |
| `io_step_restart` (max → last) | the I/O steps restart on the clock after any bus cycle in the setup, even before setup − 5; 12 requests sit on that grid's first step in silicon, none on the old grid only | `F27-out-fc-beat-ds1-n4-pO-w0`: refresh 145; 144 | −12 |
| `refresh_lead_step` (block → step) | a pending refresh held off a port-form I/O's lead takes the clock that is one of a detached I/O's steps, as `refresh_io_step=own` does in the setup | the same run: 145; 146 with `io_step_restart=last` alone | −25 |

Fit stage 19 (`F45_ENUMS` with the old value first so a tie keeps it,
`F45_INTS` = `out.relatch`, `out.lead`, `in.relatch`; F27 F28 with F8 F13
F17 F18, since every rule reads refresh-on state only; the corpus guard the
guard) from the forty-third fit chose all five new values with no integer
move, refusing 0 of 2 moves. **F27 889 → 932/1,072, F28 820 → 898/1,088,
the corpus 27,838 → 27,959** over the 36 lists, no run lost in any family;
the three-pass gate (HEAD worktree and live tree under the tracked fit
byte-identical on all 36 lists; tracked against the candidate: F27 won 43,
F28 won 78, lost 0, only F13, F27 and F28 differ byte-wise, F13 in one
already-missing run's trace after its divergence) and a fourth pass with
`refresh_scope=live` byte-identical to the candidate on all 36 lists. The
candidate (wp85/fit-wp85.json) is the forty-third fit plus the five
fields. One rule was tried and removed: a zero-clock step as no EU
micro-boundary under a refresh hold (the P shape below) loses about 1,500
runs because it moves the prelude.

**What stays a fact** (327 refresh-on misses under the candidate, PART 2 of
the facts file):

- **O1, 26 runs, 0 waits only:** the OUT has counted out 1–2 clocks before
  the next OUT's port take on the bus-free clock after a refresh in its
  setup. Silicon issues at the take + 1 at 0 waits (26 of 26) and on the
  take at 1 and 2 waits (55 of 55), with the same visible state. A rule
  would key on the wait count alone: a structural finding, not encoded.
- **O2, 18 runs, 2 waits (one at 1):** the M1 OUT posts on a refresh's
  first clock; silicon issues at the post + 7 in 17 of 35 such requests and
  at + 9 (the model's) in 15, with identical bus history up to the post.
  The difference lies before the OUT inside the EU; it needs a probe of the
  OUT's start against the refresh at 2 waits.
- **R, 39 runs:** refresh starts beside the M1 OUT's setup with mixed
  outcomes under one visible key (setup 8, 1 wait, the request at post + 3,
  the fetch ending at post − 1: + 4 in 14, + 3 in 4).
- **P, 37 runs:** the M1 PUSH write beside a refresh; 12 are one clean
  state (silicon post + 5, model + 6): the EU after a refresh hold starts
  the PUSH a clock earlier.
- **L, 35 runs:** the closing LS's `SHL AW,CL`, two clean sub-states (12 of
  12 and 20 of 20) inside the eight fitted shift-refresh boundary rules
  that are right on thousands of requests; not encoded.
- **E, 34 runs (PUSH frame, 1 and 2 waits):** the END block's `MOV
  DW,imm16 ; OUT DW,AL`: silicon runs no fetch between two refreshes 16
  apart where the model runs one or two.
- **B, 70 runs:** the immediate train after a beaten 3-clock fetch, the
  successor's clock (the thirty-seventh fit's open state). **L2 21, M 17,
  U 23, I 7:** small groups.

The RTL does not implement the five rules yet; they are arbiter and queue
conditions with no new template step kind, so `rtlgen` is unaffected.

### The 0F page's fetch commitments: F32, F33 and F34's misses read, two enums (WP86, 2026-10-31; adopted in the forty-fourth fit)

Under the forty-third fit F32 misses 418 of 858, F33 123 of 1,050 and F34
638 of 1,596, the corpus's largest open area. Facts over all of them, with
F23 and F30's transfer cells (scratchpad wp86/facts.txt, about 2,900
lines: one row per miss with the first divergence, the EU's instruction,
class and step there, the model's queue (bytes held, a fetch in flight,
committed back to back), the word half of the form's start and last byte,
and the neighbours at the other parity, the other waits, k ± 1, the
PUSH/OUT twin and the other F34 leads):

- **Every data operand is word-aligned** (the BCD strings' byte elements
  aside), so the alignment knob is the ModR/M and immediate bytes' word
  half. **Byte = word and TEST1 = SET1 = CLR1 = NOT1** in every comparable
  cell. No remaining shape keys on the opcode byte or a neighbour.
- **Parity alone (structural findings):** the memory bit ops'
  immediate-index forms at pE (+2, 66 runs) and CVTBD/CVTDB at pO (−16 and
  −14, 12 runs), both word-half shapes of the form's last byte that
  resisted a structural rule; the not-taken transfers at pE.
- **Waits alone (structural findings):** the register bit ops' +7 left at
  2 waits, the bit fields' l0 pE w2 −1, MUL imm memory's read offsets.

Encoded as two enums (sim/config.py, the old behaviour as DEFAULT, a dated
deciding run, tests in test_sim.PageFormRuns), both keyed on the class and
the queue, IR and bus state only; no new template step kind or tag:

| Enum (old → new) | Rule | Deciding run (silicon; old model) | Flip |
| --- | --- | --- | --- |
| `page_b2b` (none → reg) | a 0F register form (TEST1/CLR1/SET1/NOT1 r, ROL4/ROR4 r) commits the bus unit to one more back-to-back fetch on the last clock of the fetch running at its last operand take (or issued the clock after), with a byte of room left (the word latch takes the other), once per form; not when the next opcode was already in the IR when that fetch issued (ROL4/ROR4 DL load it on the take clock and fetch nothing more), nor when the queue could not take the word before the form's clocks end | `F34-out-rbit-set1_rw_cl-l0-k1-pO-w0`: F88 F91; F88 F98 | −69 (F32 −25, F34 −44) |
| `page_run` (none → mem → field) | while a 0F memory form's read is posted and not issued (field: also a bit field's first read), the request is evaluated on a running fetch's last clock and room for a word commits the next fetch back to back, once per form; that fetch passes the read's fetch hold, and for the memory forms its wait clocks do not count toward the read's setup (the bit fields count them: counting them too loses 6) | `F34-out-mbit-set1_mw_cl-l0-k1-pE-w0`: F87 F90 D95 (w1 D98, w2 D101); no F90. `F34-out-bf-ext_bl_dh-l0-k1-pE-w0`: F87 F90 D96; `mem` D96 then F99 | none −126 (F32 −82, F34 −44); mem −38 |

Integers: the INS crossing's `bf_ins.xwsetup` 68 → 69, `xrsetup` 11 → 12,
`xspan` 106 → 105 (every crossing INS cell −1 at every lead, parity and
wait; the three move only together, which is why stage 17's single-integer
descent never found them: +61 by hand), and from the stage `rol4_mem.fsetup`
1 → 3, `ror4_mem.pre` 5 → 1. Fit stage 20 (`F46_ENUMS` with the old value
first, `F46_INTS` = the 103 integers of the 0F, bit-field and MUL imm
classes; F32 F33 F34; the corpus guard the guard) from that hand start
chose `page_b2b=reg`, `page_run=field` and moved four more ROL4/ROR4
register integers (`rol4.pre` 0 → 2, `rol4.wb` 1 → 2, `rol4.exec` 14 → 13,
`ror4.pre` 1 → 2) that gain 5 and lose 2 inside one class
(`F32-out-rol4_dl-k2-pE-w0`, `F32-out-ror4_dl-k2-pE-w0`): a within-class
trade, so the candidate keeps the tracked values there (wp86/
fit-wp86-noloss.json; the stage's full output, 28,097 with the two losses,
is wp86/fit-wp86.json). **F32 440 → 560/858, F34 958 → 1,094/1,596, F33
unchanged, the corpus 27,838 → 28,094** over the 36 lists, nothing lost in
any family; the gate (a clean worktree and the work's worktree under the
tracked fit byte-identical on all 36 lists; the candidate won F32 120 and
F34 136, lost 0; the same won and lost sets on top of the pending WP84 +
WP85 candidate, wp86/fit-wp86-pending-noloss.json, which differs from the
plain candidate on F13, F27 and F28 only, WP85's gains).

Tried and refuted (measured, removed): re-evaluating the request on a
fetch's issue after it waited for the bus (+1 F34 but F27 +30 −1, F28 +45
−4: a refresh-beside-an-OUT effect, for the WP85 line); no fetch raised
after a bit field's or 0F memory form's read post until it issues (lost
39–145, won 0: a request raised by the width byte's take on a fetch's B3
runs back to back in silicon); any fetch issued the clock after a fetch's
last counting as committed inside the read's setup (F32 +72 −38, F34 +31
−119); `page_b2b` keyed on the last byte's word half (identical to keying
on nothing once the IR and queue state is read); a CVTBD/CVTDB fetch hold
like `mul_imm_hold` (silicon's PUSH twin fetches at once in the same
alignment: 0 won, 3 lost).

**What stays a fact** (PART 2 of the facts file): the bit fields, about
290 runs (the imm4 forms at an odd start behind a lead at pE, where the
model fetches on the width byte's take and silicon does not while the
other parity runs that fetch back to back; the imm4 forms at l0 pO −61 and
−30, the mid-span prefetch release; k = 2 +2, a k-keyed integer; the PUSH
write +2); the register bit ops, about 190 (the k = 2 second instance 2–3
clocks later in silicon; the imm form at an odd start behind a lead at pE
3 clocks shorter; cells behind `MOV CL` or `NOP NOP` at pO); the memory bit
ops, about 175 (the immediate index at pE +2, where a delivery-clock fetch
runs inside silicon's read setup and counting such fetches loses 157;
TEST1 [m],CL at pO; the d16 and direct modes); MUL imm memory, about 85
(the best formula matches 76 of 162 reads, the rest shift with the waits);
the not-taken transfers' l0 pE third refill, k = 2 and DBNZ −1; F33's
INC/DEC r8 (the cost of `wb_fetch`), one-byte forms at k = 2 pE +1,
CVTBD/CVTDB pO, MUL [BW] +2; BCD k = 2 pO −1, the DS1: prefix, the RET −22,
INC k = 4 +1, LDEA.

The RTL does not implement the two rules yet.

### Control flow completed and the data forms no family had run: F35 and F36 read as facts, twelve classes, one enum (WP88, 2026-10-31; the forty-fifth fit)

F35 (1,044 runs) and F36 (750 runs), generator-only when acquired (WP87), read the same day from the cost tables, the
strips and a corpus-wide index of ΔM by (marker, parity, waits, X's bytes) over every refresh-off frame of every family,
so that a variant's class mate is the same frame with the catalog's form of its class wherever it ran (scratchpad
wp88/facts.txt, report-F35.txt, report-F36.txt, strips-F3x.txt). Costs are against the frame with X's lead alone, cells
pE-w0 pE-w1 pE-w2 / pO-w0 pO-w1 pO-w2, OUT unless said. Readings:

- **The condition is not a cost.** Every one of the sixteen 70–7F conditions costs exactly what BE/BNE cost, taken and
  not taken, in every cell and behind every control: taken 24 26 30 / 28 31 36 behind a 2-byte CMP, not taken 9 9 10 /
  10 11 12; the PUSH frame 27 32 37 / 24 28 32 and 8 10 11 / 8 9 9. Taken +0 = taken +2 (the skipped bytes cost nothing,
  F23's +0..+7 again); not taken +2 adds the two NOPs. What moves the cost is the 4-byte lead ADD DW,2A01h (+3 +2 +2 /
  0 +1 +1 taken and not taken alike): the queue state a 4-byte form leaves, not the flag tested. F35's BE/BNE repeat
  F23's cells one for one. In the model the decoder decides every condition from the flags `execute` keeps (Z CY S V
  P, computed for CMP r16,r16 and ADD r16,imm16); the forms join `branch_short`.
- **BCWZ is not DBNZ.** Against `MOV CW,n ; DBNZ` in the same frame BCWZ is 3 clocks shorter taken and 2 shorter not
  taken in every one of the 12 cells (no count to decrement), with DBNZ's refill and interleaves shifted. Own class
  `bcwz` on the loop format's structure.
- **DBNZE/DBNZNE: the Z test decides first.** Not taken on the Z test 9 10 11 / 9 11 12 whatever CW is (CW = 1 and
  CW = 2 identical in every Z-fail cell), not taken on the count +3 in every cell, taken a clock longer than DBNZ (30 34
  38 / 27 31 35). Own class `dbnz_z` (`zexec` for the Z exit, `chold` for the odd-address hold of the count's exit,
  which ends 3 clocks after the Z exit's `nhold`).
- **The backward DBNZ** (`loop`: the body and DBNZ run twice) refills from the body's address exactly as a forward
  taken transfer does and re-fetches the body's words; nothing survives the flush. DBNZ's own class, no new rule.
- **RET imm16**: its stack read comes one clock after RET's in every cell (+1 +2 +3 / +1 +1 +1). Where the immediate's
  last byte ends its word (the form at an odd address: OUT pE, PUSH pO) its take frees a whole word and silicon fetches
  it back to back after the read; where that byte is the even half of a word no fetch comes between the read and the
  target's. Own class `ret_imm` (the read posted at the start with its own `setup`, the immediate taken once the read
  is on the bus) and one enum, `ret_imm_hold` (none → word): a half-taken immediate word raises no fetch request for
  `mhold` clocks from its take, as `mul_imm_hold` holds MUL imm's. Keyed on the operand's word alignment, not the
  chain's parity. Deciding run `F35-out-ret-imm0-pO-w0`: the read at 122, the target's fetch at 133 (none: F125 1005A
  first); the pE twin fetches 1005A at 127 right after its read under both. Flip at the candidate: −8.
- **CALL BW / BR BW**: the ModR/M byte names the register and leaves the queue at the form's start; it is not a memory
  form's ModR/M (no back-to-back start, no older-I/O wait, no latch): with that, all 60 `ind` runs are exact. CALL BW's
  write comes 7 clocks after the last fetch's end at every wait (its setup all fetch-free); BR BW's target fetch 9
  after. Classes `call_reg` and `br_reg` on CALL near's and BR near's structure.
- **The far forms**: CALL far writes PS at SP−2, then the return offset at SP−4, issue to issue 9/10/11 clocks at 0/1/2
  waits, the eight-word bursts' cadence (PUSH R); RET far reads the offset, then PS, at the same cadence, and reloading
  PS costs nothing beyond its read (the refill after it is RET's). The 5-byte operand frees the queue in two steps: the
  offset word, then the segment word `spre` clocks later. Classes `branch_far`, `call_far`, `ret_far`, `ret_far_imm`
  (`wsetup` the second word's fetch-free setup). What stays a fact (26 runs): at w0 the second fetch after M0's I/O is
  not back to back in silicon where at w1/w2 it is (one idle clock), and CALL far's first write is a clock late in one
  alignment and right in the other under every post time tried.
- **F36: every register, immediate and stack variant is class-equivalent, in all 12 cells, except two forms.** PUSH r
  51–57 = PUSH AW; POP r = each other; XCH AW,r = XCH AW,DW; MOV r8,imm8 and MOV r16,imm16 = each other; the six ALU
  AW,DW forms = MOV AW,DW = ADD AW,DW; the seven AW,imm16 forms = ADD AW,1234h; 80 = 82 = 83 /0 (byte = word); the
  byte shift D2 = D3 in memory and SHL AL,CL at CL = 31 the word form's cost; A0/A2 = A1/A3; BUSLOCK MOV AW,DW = DS1:
  MOV AW,DW in every cell (a prefix pseudo-instruction, no segment); LAHF = CLC and LAHF ; SAHF = CLC ; CLC (the flag
  class, 3 clocks per instance, not NOP's 4); LES = LDS: a load plus a second read 7/8/9 clocks later, then no fetch
  for 3 clocks and the EU's end 2 later than a load's (class `load_ptr`, `wsetup` and `phold`). PUSH PSW writes on
  PUSH r's clock (the push class); the pair PUSH PSW ; POP PSW costs PUSH r ; POP r + 2, the +2 after POP PSW's read
  (silicon's next fetch 2 clocks later: class `pop_psw`, a fetch hold after the read). TEST DL,AL costs 7 7 8 / 7 7 8,
  MOV DL,12h's cost, not the other 2-byte register forms' 4 5 6 / 3 4 5: the fixed operation costs the imm form's pre
  clocks (class `test_reg`, the register template with its own integers).
- **Structural**: nothing keys on parity beyond where X's bytes sit in their words (OUT pE = PUSH pO throughout) and
  nothing on waits beyond the wait clocks of the form's own cycles; the one w0-only shape is the far forms' second
  fetch above.

Model (sim/templates.py `_wp88_steps`, `BASE_CLASS` for the twelve classes, `decode` for every F35/F36 form,
`cond_taken` and `_set_flags`; sim/config.py `ret_imm_hold` with the old behaviour as DEFAULT and the twelve classes'
integers in `DEFAULT_COST` as the hand start; the rules that name a transfer class, `xfer_odd`, `xfer_nt` and
`stack_wb`, see the base class; `fit.run_classes` walks absolute targets, a cache-key fix found on the way; stage 21,
`F47_ENUMS` / `F47_CLASSES` / `F47_INTS`, F35 and F36 only since no rule reads an earlier class, the corpus guard the
guard; tests test_sim.CoverageDecode and CoverageForms, test_fit.CoverageClassStage). `families.UNMODELLED` and
`forms.UNMODELLED_FORMS` are empty. Stage 21 from the hand start (1,651/1,794) chose `ret_imm_hold=word`,
`call_far.spre` 2, `load_ptr.wb` 2, `pop_psw.wb` 2, `ret_far_imm.setup` 6 / `setup_free` 4 / `wsetup` 8: **F35
922/1,044, F36 747/750**, every one of the 36 earlier lists byte-identical under the candidate (the gate: a clean
worktree and the work's tree under the tracked fit, then the candidate, `score --show 5000` on all 38 lists; F35 won
676, F36 won 501 against the clean worktree, nothing lost anywhere). F35 by series: cc 312/384 OUT (the 72 not-taken
OUT pE cells are the open F34 shape of a not-taken short transfer at an even address behind no lead, the same cells for
every condition and for BE/BNE in F23) and 192/192 PUSH, cw 198/204 (DBNZE/DBNZNE at OUT pE w0 a clock early), ind
60/60, ret 48/48, loop 30/48 (the second, not-taken DBNZ releases its fetch a clock early: an earlier class, fitted on
F23/F30/F34, left), far 34/60 (above). F36: everything exact except TEST DL,AL under PUSH at pO (3 runs: silicon fetches
right after the marker's write as a ModR/M form would, the model after the pre clocks; a lead-take template lost more
than it won).

### Memory-indirect transfers, BRK and RETI on the bus (F37, 2026-10-31; modelled the same day, WP91)

F37 (WP90; 72 variants, 432 runs, generator-only: `families.UNMODELLED`, six unmodelled classes) read strictly by the
normaliser once it expected the pointer and vector reads (`normalize.VECTORED_ACCESSES`, keyed on the class: the bus
order of the reads at EA + 2j and the pushes; `derive.BASELINES` F37 = the lead-alone control; scratchpad
wp90/traces.txt, report-F37.txt). Every order below holds in all 432 runs at every wait, parity and marker, with no
extra read and the expected SP walk:

- **CALL near [m]** (FF /2, direct or [BW]): the pointer word read at the EA, then one push (the next instruction's
  offset) 9 clocks after the read at 0 waits; the read 10–12 clocks after the lead's store. **BR near [m]**: the read
  alone. **CALL far [m]**: the offset read, the segment read 7 clocks later, then PS pushed at SP−2 and the offset at
  SP−4. **BR far [m]**: the two reads alone.
- **BRK n interleaves its vector reads with its pushes**: the offset word at 4n, then PSW pushed (F046h: MD 1, RB 7,
  BRKI kept), then the segment word at 4n+2, then PS, then the return offset; the same for n = 3 (CC) and n = 5 (CD 05).
  **RETI** pops the offset, PS and PSW at SP, SP+2, SP+4.
- **First costs** (X alone against its lead, OUT w0, pE/pO): CALL [0C00h] 38/40 against F35's CALL BW 36/32, BR [m]
  29/31 against BR BW 27/22, BR far [m] 36/38 against BR far 31/25, CALL far [m] 54/56 against CALL far 48/43: the
  pointer read(s) and the alignment the longer lead leaves. Direct and [BW] agree within a clock once the length swap
  (the [BW] form 2 bytes shorter, its lead one MOV BW longer) is allowed for: no visible EA-mode cost. Reading the word
  right after storing it costs nothing extra (the `-sep` cells only swap alignment). BRK 3 and BRK 5 cost the same
  (`brk3` 136/133, `brk5` 136/136 including BR +1 and RETI). The controls (`ctl-ptr` 17/20/24 over w0/w1/w2, the
  two-word stores 33/40/48) are F5's store class and modelled.

The six classes were modelled the same day (below); until the candidate is adopted the frozen package still skips
nothing but scores F37 with the tracked fit's defaults.

**Modelled (WP91, 2026-10-31; a candidate, scratchpad wp91/fit-wp91.json on the forty-fifth fit and wp91r/
fit-wp91-on46.json on the forty-sixth):** the facts first, from all 432 runs (wp91/facts.txt). Everything after a
form's first cycle is the same at every parity, marker, mode and BRK type; only the first cycle's position depends on
X's word alignment (OUT pE = PUSH pO) and on direct against [BW]. The `[0C00h]` forms hold the fetch after the
displacement's take 3 clocks and issue the pointer read the clock after that fetch ends; the `[BW]` forms issue it 6
fetch-free clocks after the start. The far forms' segment read follows the offset read by 7/8/9 clocks (LES/LDS's
cadence); CALL near [m] pushes 7 clocks after the read's end (CALL r16's write); the target's first fetch comes 9
clocks after the transfer's last cycle in all 360 transfer runs, RETI's 15 after its last pop. BRK's train (read,
push, read, push, push) runs 6/6/7, 8/9/10, 6/6/7 and 9/10/11 clocks issue to issue at 0/1/2 waits with no fetch
inside; a read-to-push gap is the later of 6 clocks after the read issues and 3 after it ends; RETI's three pops are
9/10/11 apart, RET far's cadence. In the model (sim/templates.py `_wp91_steps`, `_execute_wp91`): FF /2–/5 with a
memory operand decode to `call_mem`, `call_far_mem`, `br_mem`, `branch_far_mem` (memory ModR/M group forms on CALL
near's and BR near's structures: the head, the pointer read taking the group setup, the far forms' segment read, the
push(es), exec and the flush), CC / CD n to `brk` (the type byte taken without a sync; the vector's offset read, PSW
pushed, the segment read, PS pushed, then the return offset with CALL's cadence) and CF to `reti` (RET's structure
with two more reads); the words the chain's stores write are kept as `regs["mem<addr>"]` as `ret<SP>` keeps return
addresses, and a far pointer or vector must name PS. Three enums with the old behaviour as DEFAULT: `xfer_mem_head`
(split → lead: the ModR/M byte taken on the start; flip −150), `xfer_mem_disp` (none → grp: the `grp_disp=hold` rule
on these classes' two-byte displacement with their own `dhold` 3; flip −120), `xfer_mem_ir` (none → hold: the
successor stays out of the IR until the pointer read issues; flip −48). Integers read off the facts (push setup 7,
`wsetup` 7, `rwsetup` 5, exec 8, RETI exec 14, BRK `rexec` 3 / `setup` 3 / `vsetup` 6) or found by score scans
(`grp` 6 / `grp_free` 6, `dhold` 3, BRK `rsetup` 12 / `rfree` 8 / `hold` 6); every read-off integer loses runs at ±1
(wp91/sens.txt). **F37 420/432** (controls 132/132, brk 144/144, farm 104/108, indm 140/148), the 38 old lists
byte-identical under the tracked fit and under the candidate. The 12 misses are the six `-sep` rows at OUT pE / PUSH
pO w1/w2: silicon fetches back to back on the transfer's start clock after the fetch the NOP started under, where the
model's queue has no room on the delivery clock; the NOP's and that fetch's timing belong to old classes, so they stay
facts. Tests test_sim.CoverageF37Decode and CoverageF37Forms. No fit stage yet: the integers are the hand start for
the stage that fits them.

### The not-taken transfer's back-to-back fetch and the aborted cycle's gap: F23, F30, F34 and F35's misses read, two enums (WP89, 2026-10-31; the forty-sixth fit)

Under the forty-fifth fit 135 refresh-off runs missed with what looked like one shape (a short conditional transfer
not taken at an even address behind no lead, silicon's third refill fetch back to back). Read run by run (scratchpad
wp89/facts.txt: every model fetch whose last clock falls inside a not-taken transfer, prefix-matched, with the EU's
step, the queue's room, the IR and the latch at that clock, and every not-taken DBNZ-family start with the cycle
running on it) they are two mechanisms:

- **A: the not-taken short conditional's decide step commits a back-to-back fetch.** In all 120 cases where a fetch
  ends inside a not-taken `branch_short`'s decide step (its condition tested) with a byte of room, silicon runs the
  next fetch back to back; the model never did. In the 149 cases where the fetch ends inside the cond clocks before
  the test (the fetch running on the transfer's start clock) silicon never does; with room 0 never. The state at every
  miss is the same: the IR holds the next opcode, 3 bytes queued, a fetch in flight, nothing latched. Odd addresses
  are exact because the `xfer_nt=odd` hold leaves room 0, and the leads (F34's `d2`/`nop2`, F35's ADD DW) are exact
  because no fetch ends inside the decide step: the word half of the opcode is not what decides it. DBNZ, BCWZ and
  DBNZE/DBNZNE give no evidence either way (their decide step starts on the take, with the start clock's fetch
  running), so the rule stays on `branch_short`. Enum `xfer_nt_b2b` (none → decide): the same structure as
  `page_b2b`, the latch taking the word's other byte, once per form, and the decide step does not wait for the fetch it
  committed. Deciding run `F23-out-bne-n0-k1-pE-w0`: BNE starts on F87, F90 back to back, its last clock 92 in the
  decide step with room 1; silicon F93, I107 (none: F100, I107). Flip at the candidate −120 (F23 −9, F30 −30, F34 −9,
  F35 −72); gated alone it wins exactly those 120 and loses nothing.
- **B: an aborted cycle counts as the fetch it stood for in the decide step's gap.** For a DBNZ at an odd address
  silicon's next fetch comes 6 clocks after the end of whichever cycle ran on its start clock: a fetch (st+8/9/10 at
  w0/w1/w2, 54 runs exact already) or an aborted cycle (3 clocks at every wait: silicon st+8, the model st+7 in all
  31 rows). The 15 F34 `nt-dbnz` misses, 16 of F35's 18 `loop` misses and all 6 F35 `cw` misses at OUT pE w0 are this.
  Enum `decide_abort` (fetch → cycle): an aborted cycle that answered a fetch request since the transfer's start
  counts as the fetch, the `nfgap` counted from its last clock, as the take sync already waits for it. Every odd
  DBNZE/DBNZNE starts on an aborted cycle, so `dbnz_z.nhold` 3 → 2 and `chold` 6 → 5 (the old integers carried the
  clock). Deciding run `F34-out-nt-dbnz-d-k1-pO-w0`: DBNZ at 10053 starts on 99 with an aborted cycle 99–101; silicon
  fetches at 107, the model under `fetch` at 106. Flip at the candidate −67 (F34 −15, F35 −52), −37 with dbnz_z's old
  integers; gated alone it wins F34 15 and F35 22 and loses nothing.

Fit stage 22 (`F48_ENUMS` the two enums, `F48_INTS` the 41 integers of branch_short, dbnz, bcwz and dbnz_z; F23 F30
F34 F35; the corpus guard the guard) from the tracked fit chose both and the two dbnz_z integers, 3,909 → 3,945 of
4,476 on its families; the sweep moved nothing. **F23 360/360, F30 1,451/1,476, F34 1,118/1,596, F35 1,016/1,044,
29,884 → 30,041 of 31,532**, the other 34 lists byte-identical (the gate: a clean worktree and the work's tree under
the tracked fit byte-identical on all 38 lists; the candidate won 157, lost 0). Tests test_sim.NotTakenBackToBack,
test_fit.NotTakenB2BStage.

**What stays a fact:** F35 `far` (26 runs: the w0 second fetch after M0's I/O and CALL far's first write, taken
transfers that neither rule touches); two F35 `loop` runs where silicon makes one more sequential fetch before the
first DBNZ's backward flush (a taken transfer's pre-flush fetch); F30's remaining 25 are all LDEA; F34's other 478
are untouched (the bit fields, the register and memory bit ops, MUL imm memory).

## Model

`validation/v35s/chains/sim/` is a clocked simulation of four machines: a bus
unit (B1 B2 waits B3, one cycle at a time), a byte queue, a decoder that
serves the EU's byte takes, and an EU that runs one step template per
instruction class (take, clocks, EA, read, write, I/O), with an arbiter
between fetch and data requests. Every structural alternative is an enum in
`sim/config.py`; every clock count is an integer per class. The model's
cycles go through the same normaliser as silicon's, so `derive` and `report`
read both alike, and `score` compares event lists from the fill point on.

`fit.py` fits it in the plan's seven stages: bus read-off (F0, F0w), full
enumeration of the queue options on F0, then per stage an enumeration of the
newly free enums with integer coordinate descent, scored lexicographically
(exact runs of the earlier stages' families first, then this stage's, then
the summed first-divergence residual). Each stage writes
`build/validation/v35s/chains/fit/stageN.json` and the final configuration
`fit.json` there, under the ignored `build/`. The adopted fit is tracked in
the package as `validation/v35s/chains/fit.json` (since 2026-10-26,
`sim.config.FIT_PATH`; the forty-sixth fit since 2026-10-31): `score` and `sim` read it by
default (`--config PATH` for another file, `--defaults` for the unfitted
baseline `sim.config.DEFAULT`), the regression tests in `test_fit.py` and
`test_perf.py` run against it, and

    python -m validation.v35s.chains score --family F0 ... F23 F25 F26 F27

reproduces every number below. The fitter never writes the tracked file:
`python -m validation.v35s.chains adopt PATH` does, after the file round-trips
exactly through `Config` (an unknown or missing field is refused), so a fit
becomes the model's by a reviewed step. The fitter also reports, per integer, the
best value within each parity, wait setting, k, marker kind and family; a
value that moves with a knob is reported as a structural finding, never
encoded.

Since 2026-10-19 the fitter caches each run's result on the part of the
configuration that run actually reads (the cost classes and address modes
in its chain, and the structural fields its simulation touched), so a move
on one class re-simulates only the chains containing it, and the simulator
fast-forwards quiet idle stretches so a stalled structure reaches the
guard at once. Results are bit-identical to the uncached full simulation
(`test_perf.py` checks a cross-family sample and a structure grid, in
process and through the pool). A seeded `fit --all` took about 1.5 h on
8 cores (stage 5 170 s, was 2.3 h; stages 2 and 6 grid-bound at about 20
and 48 min). Since 2026-10-20 each stage ends with an enum sweep that
re-descends the integers inside every enum flip that makes a run exact
(below); stage 5 takes 11–15 min with it, and a seedless `fit --all`
about 8 h, stages 3 and 6 about 3 h each.

### Fence and fill (F0, 2026-10-17)

All 18 F0 runs are exact, at every wait setting and parity, with:

| Machine | Rule |
| --- | --- |
| queue | 6 bytes; a fetch is requested when 2 bytes are free |
| decoder | one byte per clock; bytes taken in one step free their room when the step ends; the next opcode is loaded as soon as the current instruction has all its bytes |
| EU–bus coupling | an instruction does not start while a fetch issued earlier is on the bus |
| costs pinned | NOP 4; MOV r,imm 3 before the operand; `MOV CL,31 ; SHL AW,CL` 71 in total |

Each of capacity 4 or 8, fetching at 1 free byte, two bytes per clock, a
forced idle clock between cycles, releasing a word's room on its first byte,
taking the opcode only when the EU starts, or committing takes per byte
fails F0 outright. 108 combinations of the remaining queue options survive
F0; the later stages choose among them.

**The thirty-seventh fit** (`fit.json`, 2026-10-28, md5 22affc16; scratchpad wp61/fit-wp61.json, the fitter's own
stage-12 output under the corpus guard, WP61) is the thirty-sixth with eight new enums at their found values, 232
fields, no integer changed. Stage 12 (`fit.py` `STAGE_FAMILIES[12]`, `F28_ENUMS`, `F28_SWEEP`, `F28_INTS` =
`shift_cl.wb`, `rmw.grp_free`, `out.relatch`): a grid of 576 candidates over the eight enums, both leaders descended
over the three integers, then a sweep of 19 enums and 23 alternatives with the integers descended inside every move
(0 moves, the guard refusing 0 of 2), 716 s. The chosen values equal the hand configuration the reading produced
(wp61/c8.json). Each enum is in `sim/config.py` OPTIONS with the old behaviour as DEFAULT and a dated comment naming
the deciding runs (clocks relative to t_fill) and the flips; `test_sim.RefreshExitBeatGroupF28F29` (14 tests) pins
each value against its alternative on those runs, the six-byte bound on every F28/F29 chain, the refresh-off runs
reading no refresh field, and the `[BW]` forms untouched.

| Enum (value) | Mechanism | Deciding run (silicon; the old value) | Flips at the adopted fit (losses only) |
| --- | --- | --- | --- |
| `refresh_wb=free_wait` (hold, free) | states A and B as one mechanism: an instruction held at its end by a refresh is dated from the clock its steps ended, so its 2-clock write-back runs under the refresh and a port-form OUT after a shift, multiply or divide (the only class with a wbsync step) waits for nothing (A); the OUT's wbsync clocks take no refresh, it goes at the OUT's third clock (B) | A `F28-out-fc-fence-cl27-n0-pE-w0` F80 R89 I94 (hold F82 R87 I95); B `F28-out-fc-fence-cl26-n0-pE-w0` R74 F79 R88 I93 (hold and free R72 F77 I86 R89) | hold −2 F8, −41 F13, −78 F27, −194 F28; free −14 F13, −17 F27, −77 F28 |
| `refresh_relatch=issue` (free) | a pending refresh beside an I/O that has counted out but is held by a port take's relatch waits for, and goes on, the relatched issue clock | cl27: R89 I94 (free R87 I92) | free −7 F27, −53 F28 |
| `refresh_window=posted` (need) | `refresh_post`'s window-start boundary uses the window as posted (`free_orig`), after `free_run` has cleared `free_need` | `F28-push-fc-tail-shlcl8-outb-n0-pO-w0` R162 S167 (need R164 S169) | need −5 F27, −30 F28 |
| `refresh_start_seam=start` (seam) | a clocks step that begins on the instruction's start clock, after a ModR/M taken there, keeps the start's boundary | `F28-out-fc-beat-adddwi-n1-k1-pE-w0` R103 F108 (seam F103 R107) | seam −6 F27, −22 F28 |
| `refresh_step_lead=step` (lead) | with `refresh_io_step=own`, a step on a port lead's first clock takes the refresh over the older fetch, which then counts as the lead's, not as one the refresh beat, and waits for the issue | `F28-out-fc-fence-cl24-n0-pO-w0` R97 I102 F105 (lead F97 R100 I105) | lead −1 F8, −2 F17, −4 F27, −22 F28 |
| `refresh_beat_b2b=imm` (none, take) | the beaten fetch's successor: on the delivery clock D of a beaten 3-clock fetch with no IR load on D, the back-to-back fetch committed there is a clock late when D is an operand take, when an immediate form (class imm) runs with bytes outstanding and did not start on D, or when a non-imm form starts on D right after an imm form (an imm form starting on D stays on time) | `F28-out-fc-beat-movawi-n0-k2-pE-w0` F112 (none F111); `F27-out-fc-room-movawi-n0-k2-pO-w0` F122 (none F121); `F27-push-fc-room-movawi-n0-k3-pE-w0` on time in both | none and take −15 F27, −16 F28 (the take instances alone flip no run); extending the delay to the non-committed fetch requested on D with a take would lose about 590 runs |
| `grp_disp=hold` (none) | a group RMW form without an immediate with a d16 displacement (INC, NOT, SHL ,1, NEG, DEC [BW+200h]): on the displacement take P no fetch starts on P..P+`grp_free`−1 (one committed back to back goes; on P itself one goes if the take left room for two words), the take sync waits only for a fetch already on the bus, a fetch no older than the read waits until the read's fetch-free clocks start, and those clocks count through a fetch but not an I/O cycle or its recovery; no new integer (`rmw.grp_free`) | `F29-out-ec-gih-incd16-n1-pO-w0` F95 D98 (none F92 D98); n0-pO F91 D94 (none F88 F91 D94); n1-pE F91 F94 D97 (none F91 D97) | none −79 F29, nothing else; a first version covering `rmw_imm` too cost 543 F22 and 18 F5 runs |
| `dw_lift=moved` (posted) | G1: a DW request that moved into the slot on the issue of the I/O ahead does not let a fetch first requested on that same clock run on its lead's first clock | `F29-out-ec-dio-dw-stbwd8-n0-pO-w0` I85 I92 F95 (posted I85 F90 I93) | posted −39 F29, nothing else |

**Result.** F28 573 → 820/1,088 (the ECh twins 272/272; FCh 301 → 548/816: `empty` 5/6 and 5/6, `fence` 38/42 and
29/42, `tail` 183/216 and 146/216, `beat` 142/288; by cell PUSH 39, 41, 38, 36, 36, 36 of 44 and OUT 42, 59, 61,
44, 60, 56 of 92 at pE w0..w2, pO w0..w2); F29 309 → 427/456 (`dio` 132/144, `gih` 115/132, `pi` 168/168, `empty`
12/12). Nothing-lost gate (the overseer's re-run, scratchpad wp61r/: `score --show 5000` under both fits over all
30 family lists, `cmp`, then a run-by-run set difference, with the miss counts equal to total minus exact in every
family so no overflow run hides): byte-identical on F0, F0w, F1–F7, F9–F12, F14–F16, F18–F23, F25 and F26;
gains-only on F8 35 → 37, F13 399 → 440, F17 752 → 754, F27 778 → 889, F28 and F29 as above; 0 newly lost, no
overflow cell. The corpus is 22,771/23,612 exact over the 29 scored families. Every earlier fitted value re-flipped
at the final fit is confirmed (wp61/flips-final.txt; among them `refresh_beat_t4=none` −4 F13, `refresh_io_run=none`
−158 +11 F28, `refresh_io_step=any` −80 F27, `port_ready=relatch` −44 F28, `refresh_lead=open` −117 F18,
`disp_io=none` −6 F29, `port_issue=False` −6 F29, `grp_io_hold=False` −18 F26); `refresh_wbsync=wait` is now inert
(exact and matched counts identical: `refresh_wb=free_wait` subsumes it). The fitter reports no integer whose best
value differs by parity, waits, k, marker, family or n. `freeze` regenerated and `freeze --verify` identical over
23,612 runs; `rtlgen` regenerated (the enum comment lines and the md5 only) and `rtlgen --check` clean.

**Corrections to the reading above.** State A is not the OUT starting during the refresh's wait clocks: the OUT
starts where the model has it, but its write-back wait is already over (DW-form OUTs, which have no wbsync step, and
the PUSH frame are unaffected, which fits). The A/B fence runs also need `refresh_relatch` (the M1 relatch, R89
I94). "No new start on X+8" is wrong for 16 of the 34 OUT-frame late instances: in the model the closing OUT starts
on D right after the MOV's sync, and the clean statement is "a non-imm form starting on D after an imm form". G1 and
the dw-cell base+index+d16 holds are separate states.

**Misses left** (wp61/miss-final.txt; first divergence as silicon kind / model kind / silicon − model). F28, 268:
the I/O a clock late (51, i,i,+1), in two sub-shapes, a refresh on the I/O's post clock P with the next OUT's port
take at P+11 issuing it (silicon P+12) and a refresh at P+3 with the relatch at P+8 (silicon one past the relatch),
not one state, no rule; the refresh a clock late (33, r,r,+1: PUSH-frame END-block and late refreshes); the beat
train's fetch ±1 (25 and 12: a take on D where the fetch was requested on D rather than committed is late in
silicon, and a MOV starting on D with the requested fetch is on time where `t4` delays it); the 1-wait beat cells
with the fetch 3 clocks early (22); the refresh a clock early (21); the I/O 3 clocks early (20); the I/O before the
fetch at 1 wait (15); groups of 2 to 11 for the rest. The reading's "refresh on the model's fetch clock" group (47)
is 2 now, most of it `refresh_start_seam` and `refresh_step_lead`. F29, 29: the base+index+d16 dw cells (12, the
fetch after the DW I/O a clock late at both parities now; the `dio` pE base+index+d16 misses are in this group, no
clean state), TEST dw pE (6, +1), gih n2 pO at 1–2 waits (10, the read a clock late in silicon), `shl1d16-n2-pO-w0`.

**The thirty-eighth fit** (`fit.json`, 2026-10-29, md5 e785b574; scratchpad wp67/fit-wp67.json, WP67) is the
thirty-seventh with the seven string classes and four new enums, 236 fields, no existing integer or enum changed. The
string forms are one two-byte instruction when a REP prefix (F3, F2) precedes them (`templates.STRING_OPS`,
`_string_op`, `Op.rep`; not the segment-prefix class), decode their addresses from IX, IY and DW in the register
file, and take their element count and a compare's exit from the normaliser's expected-access walk
(`normalize.string_elements`, `StringRun.cond`; `Machine` hands `eu.strings` to the EU), since the model's register
file does not hold the data page. The template (`templates._string_steps`): unprefixed, `pre` clocks, one element
with `setup`, `exec` clocks; under REP, the opcode take, `rpre` clocks, then with CW = 0 `zexit` clocks and nothing
else, otherwise element 0 with `first`, element 1 with `loop1` where the class has one, the rest with `loop`, every
later bus cycle of an element with `mid`, the CW-ending element's last cycle `last` more, then `rexit` (CW ran out)
or `cexit` (a compare's condition). Each bus cycle is an ordinary data step, so an odd word splits through
`odd_split=atomic` and an I/O cycle runs at the I/O waits. Stage 13 (`fit.py` `STAGE_FAMILIES[13]`, `F24_ENUMS`,
`F24_INTS`, the seven classes' integers): a grid over the four enums at the start integers (an F24-only scan descent's),
the two leaders descended, then the sweep with the integers descended inside every move, 760 s under the corpus
guard (0 of 14 moves refused); it changed nothing from the start values. The new enums, each in `sim/config.py`
OPTIONS with the old behaviour (the forms undecoded) as DEFAULT and a dated comment; `test_sim.StringForms` and
`test_fit.StringStage` pin them:

| Enum (value) | Mechanism | Pinned by |
| --- | --- | --- |
| `str_take=sync` (chain, quiet) | the REP form's string opcode, the byte after the prefix, is an operand take with the take sync | the stage-13 grid at the start integers: sync 746, quiet 474 (chain, then a wait for no fetch on the bus or wanted), chain 198 |
| `str_setup=nowait` (clocks) | `rpre` counts only on clocks with no memory cycle in a wait state | silicon's first element is 28 clocks after M0 plus the waits of the refill's fetches, three at pE and two at pO; `clocks` 247 |
| `str_overrun=read` (none) | a REP compare issues the next element's reads after the last one, where the loop's next element would go (10 + w after element 1 for CMPM) | the overrun fact; `none` 564/912 |
| `str_hold=hold` (none) | after a compared element no fetch request for the class's `chold` clocks | a single CMPM's or CMPBK's next fetch 2–3 clocks after its read where LDM's follows at once; `none` leaves 12 of the 48 single compares exact against 22 |

Integers: `str_move` setup 10, mid 7, exec 4, nx 1, rpre 5, zexit 10, first 15, loop 7, rexit 12; `str_cmp` setup 10,
mid 7, exec 6, nx 2, rpre 5, zexit 10, first 14, loop 7, rexit 20, cexit 19, chold 2; `str_store` setup 12, exec 0,
rpre 5, zexit 10, first 15, loop 7, rexit 12; `str_load` setup 10, exec 1, rpre 6, zexit 9, first 14, loop 9, rexit
15; `str_scan` setup 11, exec 7, nx 1, rpre 5, zexit 10, first 15, loop 10, loop1 8, rexit 20, cexit 19, chold 3;
`str_in` setup 9, mid 4, exec 4, rpre 5, zexit 11, first 15, loop 6, rexit 12; `str_out` setup 11, mid 6, exec 3,
nx 1, rpre 5, zexit 11, first 16, loop 6, last 1, rexit 13 (pre 0 everywhere). `loop1` is CMPM's 10 + w spacing from
element 1 to 2 against 12 + w after it (CMPBK shows none); `cexit = rexit − 1` is the early-exit fact, and when CW and
the condition end on the same element silicon pays the condition's exit; `last = 1` is OUTM alone, its CW-ending
element's I/O a clock later than the others'.

**Result.** F24 746/912: controls 66/66, `t` 72/72, `d` 36/36, `r` 360/408, `a` 120/162, `s` 92/168; by cell 123,
112, 112 of 152 at pE w0..w2 and 123, 138, 138 at pO. Exact: every REP STM, MOVBK, LDM, REPNE CMPM and REPE CMPBK
cell at every n (0 to 16), byte and word, both parities, all waits; REP INM and OUTM at pE w0 and every pO cell; all
unprefixed k = 1 singles but OUTM. Nothing-lost gate (the overseer's re-run, scratchpad wp67r/: `score --show 5000`
over all 31 family lists under HEAD's code and the thirty-seventh fit, the new code and the thirty-seventh fit, and
the new code and this fit, `cmp`, run-by-run set differences, miss counts equal to total minus exact everywhere):
byte-identical on all 30 other lists in both comparisons; F24 under the new code with the default enums 219 → 746,
30 runs lost (REP INM and OUTM at pE w2, which the undecoded defaults landed by the parity effect below) and 557 won.
The corpus is 23,517/24,524 exact over the 30 scored families. `freeze` regenerated and `freeze --verify` identical;
the RTL include regenerated with the string classes left out of its step tables (WP68, Phase E item 3 pending).

**Misses left** (wp67/miss-shapes-wp67.txt, ev-wp67.txt; silicon − model), 166, all 1 or 2 clocks, four shapes, each
a parameter that wanted to vary with a knob and so a structural finding, none special-cased:

- **REP INM and OUTM at pE w1 and w2** (66; −1): the first I/O or data cycle, or the post-stream fetch at n = 0,
  a clock late in the model. The fitter flags `str_in` and `str_out` `rpre`, `zexit` and `first` as wanting one clock
  less at even parity at w ≥ 1; silicon's INM first I/O is 16, 15, 15 clocks after the refill's last fetch at w0, w1,
  w2 where STM's is 16 at every wait. STM shows no such dependence.
- **An odd last operand at w0** (30; fetch +1): `a`-series STM-iy, MOVBK-iy/ixiy, CMPBK-ixiy and INM-iy at w0 only,
  both parities: after a split last cycle M1's fetch is a clock later than the model; exact at w1 and w2, so the exit
  would have to vary with the waits.
- **The second instance of an unprefixed pair** (52; −2 to +1 by parity): the first instance's request queues behind
  M0's detached OUT and counts its `setup` from that I/O's issue, the second from its own start; one `setup` serves
  only one of them.
- **A single OUTM** (24; I/O +1): the model's I/O a clock early; `mid` one higher lands the I/O but puts the next fetch a
  clock early, since silicon leaves an idle clock after the OUTM's I/O cycle that an I/O data step does not.

**The thirty-ninth fit** (`fit.json`, 2026-10-30, md5 93e32c36; scratchpad wp70/fit-wp70.json, WP70) takes two of
the thirty-eighth's four miss shapes as mechanisms and leaves the other two as facts. Three new enums, 239 fields; the
only integer moves are in the string classes, where `setup` is one less in six of the seven (`str_move`, `str_cmp`,
`str_load` 9, `str_scan`, `str_out` 10, `str_store` 11) and `str_load` `exec` is 2, the counterpart of `str_count=dw`
below (the clock a bus cycle starts on no longer counts). Stage 13 again, from a hand configuration an F24-only
per-class descent produced (the sweep from the tracked fit stopped at 764/912 with `str_count=data`: at the old
integers the move scores 668 and the sweep screens it out before descending inside it); the fitter kept the hand
configuration with no move. The enums, each in `sim/config.py` OPTIONS with the old behaviour as DEFAULT and a dated
comment; `test_sim.StringForms` pins each against its alternative on a deciding run:

| Enum (value) | Mechanism | Pinned by |
| --- | --- | --- |
| `str_last=all` (rep) | the one element of an unprefixed form is the element that ends the instruction, so its last cycle takes the class's `last` clocks as a REP form's CW-ending element does | `s-outm-b-k1-pE-w0`: read 94, I/O 103 (rep: 102), fetch 107; rep −14 F24 |
| `str_io_latch=write` (none) | a string form's I/O write takes its datum from the data latch (the element's read data) and holds it `wlatch` clocks from its issue, as a memory write does; a port-form OUT starting meanwhile waits for it and (`wlatch_hold`) holds the fetch, a second OUTM (no port byte) does not | the single OUTM's closing OUT: fetch 107 after an idle clock, the k = 2 pair's second OUTM: fetch 106 with none; none −14 F24 |
| `str_count=dw` (data) | a string form's requests count their setup as a DW-form I/O request's (`io_count=nowait`, and with `dw_count=bus` not the clock a cycle starts on its post or move-in clock), since the form has no operand byte and takes its addresses from IX, IY and DW; `Request.dwlike` through the existing `dw_count` path | unprefixed pairs: the second STM writes at D1end + 11 at pO at every wait, D1end + 12 + w at pE where the fetch at D1end + 1 costs its first clock and wait states; the first instance moves in on M0's I/O issue and writes 11 later at every wait; data −110 F24 |

Tried and removed: `str_exec=dw` (the unprefixed form's exec clocks counted the same way) lands every INM second
instance but makes the exec before the closing OUT pay a fetch silicon does not; it won nowhere in a setup × exec grid
(F24 758), so the cost belongs to the next string form's count, not the exec clocks.

**Result.** F24 778/912, by series with the `MOV CW,n` controls counted in theirs: `r` 402/450, `a` 120/162, `s`
124/168, `t` 78/78, `d` 48/48, the six empty frames 6/6; by cell 137, 112, 112 of 152 at pE w0..w2 and 129, 144, 144 at pO. All 24 single OUTMs and
every STM and LDM pair are exact. Nothing-lost gate (the overseer's re-run, scratchpad wp70r/, as for the
thirty-eighth): byte-identical on all 30 other lists under both comparisons; F24 44 won (12 single OUTM, 2 OUTM pairs,
12 STM, 6 LDM, 8 CMPM, 2 MOVBK and 2 CMPBK pairs) and 12 lost, the second instances of CMPBK, CMPM and MOVBK pairs at
pE w1 and w2, where the fetch runs inside the first instance's exec and one `setup` still serves only one instance.
The corpus is 23,549/24,524 exact over the 30 scored families.

**Misses left** (wp70/miss-shapes-wp70.txt, ev-wp70.txt), 134, three shapes, each recorded as a fact and none encoded:

- **REP INM and OUTM at pE w1 and w2** (60; −1). From the form's start the first cycle comes at a base (STM 21, OUTM
  22) plus the wait states in the window; STM counts none of them (0/2/4 at pE, 0/1/2 at pO), INM and OUTM count 0/1/3
  at pE against 0/1/2 at pO: exactly one wait clock of the second, back-to-back refill fetch, none of the first's. The
  n = 0 exit shows the same pattern. No machine statement of that one-wait-clock rule was found.
- **An odd last operand at w0** (30; fetch +1). The fetch after the stream is 21 clocks after the last cycle's end when
  aligned at every wait; 22 at w0 only after a split last write (STM-iy, MOVBK-iy and ixiy, INM-iy) and after
  CMPBK-ixiy, both parities, and still 21 after split reads (LDM-ix, CMPM-iy); the loop spacing after a split is the
  unchanged 9 + w. "Done no earlier than the second half's issue + 4" fits the split writes but not CMPBK and would
  move the n ≥ 2 loop.
- **The second instance of an unprefixed pair** (44; −1 to +1 by parity): MOVBK, CMPBK and INM pairs at pO (−1) and pE
  w1/w2 (+1), CMPM pE w1/w2 (+1), OUTM pE w1/w2 (−1) and pO (+1). In these classes the fetch runs inside the first
  instance's exec; INM's second I/O is at D1end + 12 at pO and D1end + 13 + w at pE, and one `setup` cannot serve the
  moved-in first instance and the second one.

**The fortieth fit** (`fit.json`, md5 23562d00; scratchpad wp72/fit-wp72.json, WP72, fitted and verified 2026-10-30,
adopted the same day after HDL plan D2; until then the tracked file was the thirty-ninth fit in the fortieth's schema,
the six new fields at their defaults, md5 bf77c277. The RTL had none of the new mechanisms until the catch-up package
WP75, done the same day (HDL plan "E3 and the fortieth fit's catch-up done"; 26,234/26,234 exact against the model, 0 not modelled): at the adoption the `--core` gate differed from the model on 359 of 26,234 runs (F23 60, F25 153, F30 142, and 4 F0w runs in an internal latch field only; 24,183 exact, 1,692 not modelled), and `rtlgen` leaves the `dispose` class out of
the step tables, so `test_rtlgen`'s class check fails until then) takes the
F25 and F23 miss shapes by size. Six new enums, one existing enum flipped, two new class integers, four moved; F25
446 → 534/588 and F23 255 → 303/360 with nothing lost in any family, 23,685/24,524 over the 30 scored families. Stage
14 (`fit.py` `F40_ENUMS`, `F40_SWEEP`, `F40_INTS`) from a hand start (827 exact on F23 + F25) under the corpus guard,
344 s: the descent moved `lea.nx` 2 → 0 (837), the sweep nothing. The enums, each in `sim/config.py` OPTIONS with the
old behaviour as DEFAULT and a dated comment; `test_sim.TransferAndFrameMisses` pins each against its alternative on
its deciding run and `test_fit.TransferFrameStage` the stage. Several are keyed on a class with one form (`lea`,
`prepare`, `push_r`, the transfer classes): per-class template choices, none on an opcode byte, a parity, a wait count
or a neighbour.

| Enum (value) | Mechanism | Pinned by |
| --- | --- | --- |
| `imm_latch=wait` (free; existing, flipped) | a data immediate is not taken before a waiting OUT's I/O cycle has ended: the decoder's immediate bytes and the OUT's datum share the data latch | `out-push_imm8-pO-w0`: M0's I/O 85, the stack write 94 (I + 9 at every wait and parity, imm16 I + 10; free 91); flipped alone at the thirty-ninth fit it changes no run outside F25; free −24 F25 |
| `xfer_abort=word` (none) | the aborted fetch cycle answers a request on a transfer's start/take/IR-load clock with 2 or 3 bytes of room (the displacement goes to the target adder and still counts on its take clock); with no data cycle to raise the request again it is raised on the aborted cycle's end | `push-br-n0-pO-w0`: BR short starts 81 with 3 bytes of room, silicon's aborted cycle 81–83 and fetch 84, target fetch 92 (none: F81); none −24 F23 |
| `cond_gap=own` (fgap) | a taken form with a condition field (BE, BNE) flushes its class's `cfgap` clocks (8) after the last fetch's end, the flag test holding the quiet window open, where BR short waits `fgap` | `out-be-n0-pE-w2`: target fetch 107 = last fetch's end + 9 in every BE cell at 1 and 2 waits, BR short's at + 6 (fgap 106); fgap −24 F23 |
| `burst_count=dw` (data) | PUSH R's stack writes count their setup as a DW-form I/O request's, as the strings' do (`str_count=dw`): no operand byte, addresses from SP, data from the register file; POP R keeps the data count | `push-pushr-pO-w0..w2`: start 81/82/83, first write 89/90/91 (setup 9, every clock counted); pE a fetch on the start clock, 90/92/94; under OUT the write 9 after the I/O issue; data needs setup 10 under PUSH and 9 under OUT; data −12 F25 |
| `lea_io=recover` (free) | LDEA started on an I/O's issue clock runs its EA clocks only after the I/O's recovery (`io_recover`): the EA uses the bus unit's address adder, held through the recovery | `out-ldea-bw-pE-w0`: silicon F87 F94 I101 (free: EA 87–88, OUT at 90, I100); free −7 F25 |
| `lea_room=ir` (none) | during LDEA's EA clocks after its last operand byte the IR byte is not counted by the request rule: LDEA's successor decodes while the adder works and the bus unit fetches as if the slot were free | `push-ldea-bw-pO-w0`: fetch 81–83, M1's opcode in the IR on 83, EA clocks 84–85 with 3 bytes queued and a word delivered on 84: silicon F84 W93 (none: W92 F95); every mod 00 mode at pO, OUT LDEA k = 2 at pE w1/w2; `lea.nx` 2 → 0 with it; none −24 F25 (+7 −31) |
| `prepare_sync=run` (take) | PREPARE's take sync waits for a fetch the bus unit commits back to back on the last clock of the one it waits for, the whole refill run; `prepare.exec` 11 and `prepare.wb` 2, the closing OUT waiting for the write-back of SP and BP (`out.wbsync`), M1's PUSH not | `push-prepare-pE-w0..w2`: M1's write at the second refill fetch's end + 18 at every wait (117/121/126; take 119/122/126); `out-prepare`: the OUT's fetch at the run's end + 17; take −24 F25 |

Integers moved: `push_r.setup` 10 → 9, `prepare.exec` 16 → 11 (new `prepare.wb` 2), `dispose.setup` 6 → 7, `lea.nx`
2 → 0, new `branch_short.cfgap` 8. Won: F23 every BE cell at 2 waits but PUSH pO (24) and the PUSH-frame BR short at
pO (24); F25 every PUSH imm cell under OUT (24), PREPARE and PREPARE/DISPOSE in both frames (16), PUSH R and PUSH R/POP
R under PUSH at pO (6), LDEA mod 00 under PUSH at pO in seven modes (21) and the k = 2 cells (8), LDEA mod 00 under
OUT at pO w0 (7) and k = 2 at pE w1/w2 (6). After: F23 162/180 at pE, 141/180 at pO, 101/120 at every wait; F25
252/294 at pE, 282/294 at pO, 172/181/181 of 196 at w0/w1/w2. Nothing-lost gate (the overseer's re-run, scratchpad
wp72r/, as for the thirty-eighth): byte-identical on all 29 other lists in both comparisons, F23 and F25 won only.

**Facts left, none encoded** (wp72/; F30 probes each of them, Facts "Probes for the facts-only shapes"): F25 B, LDEA base+d16 and direct under PUSH at pE (27): M1's write at the end of
the third fetch after M0 + 7 at every wait (`bw_d16` 96/100/104, model 93/96/100), pO exact; F25 C, LDEA under OUT at
pE w0 mod 00 (7: silicon F87 F94 I101, model F87 F90 I103, the cells `lea_room` gives back) and k = 2 (8); F25 E, the
segment forms (12): the M0 marker's I/O a clock later at pE when 8E (MOV DS1,r/m) follows it, 8C and pO exact, and
MOV [BW],DS0 at pO storing a clock late, where every statement found is keyed on the opcode; F23 A, the OUT-frame BR
short at pO (24): the io_take drop on the I/O issue clock retried at the I/O's end gives the model a fetch at 88 that
silicon lacks before its target fetch at 96, and excluding transfers from the drop changes nothing; F23 C/D/E, BNE and
DBNZ not taken (27) and callret (6): `dbnz.nexec` and `dbnz.nfgap` still want to vary by parity and frame
(`out-bne-n0-k1-pE-w0` silicon F93 I107, model F98 I105; `out-dbnz-c1-n0-pO-w0` silicon F107, model F105), and after
the RET's refill the model adds a fetch silicon has none of (push pO F146).

**The forty-first fit** (`fit.json`, md5 e39153f3; scratchpad wp76/fit-wp76.json, WP76, fitted, verified and adopted
2026-10-30 after HDL plan E3) encodes seven of the F30/F31 readings (Facts "Probes for the facts-only shapes") as
mechanisms. Nine new enums, four new integers in every string class, one integer moved; F30 959 → 1,349/1,476, F31
66 → 234/234, F24 778 → 868/912, F23 303 → 333/360, F25 534 → 569/588; 25,423/26,234 over the 33 scored families, 716
runs won and 3 lost (F30 `push-lea-{bw_d16,bw_ix_d16,dir}-nopb-pO-w0`, where silicon starts LDEA's successor on the
back-to-back fetch's issue when a NOP precedes the LDEA). Stage 15 (`fit.py` `F41_ENUMS`, `F41_INTS`) from a hand start
(the fortieth fit with the enums on and the integers read off the tables) under the corpus guard, 2,174 s: the grid's
best start was the hand start (3,353/3,570 on the stage lists), the descent and the sweep moved nothing (511 moves, all
refused by the guard). The enums, each in `sim/config.py` OPTIONS with the old behaviour as DEFAULT and a dated comment;
`test_sim.ProbeShapes` pins each against its alternative on its deciding run and REPC/REPNC at decode and through the
simulator, `test_fit.ProbeShapesStage` the stage. Two rules key on where a byte sits in its word (the short jump's
opcode at an odd address, LDEA's displacement split across two words): the word alignment of the operand, as the odd-word
split of a data cycle is; none keys on an opcode byte, the chain's parity, a wait count or a neighbour. BNE/DBNZ not
taken stay facts: a hold on DBNZ (no request until `nhold` clocks past the last fetch's end) over a grid in `nhold`,
`nexec`, `nfgap` made no DBNZ cell exact and lost the 21 exact now; BNE's back-to-back third fetch needs queue room the
model lacks at that clock.

| Enum (value) | Mechanism | Pinned by |
| --- | --- | --- |
| `xfer_odd=idle` (hold) | a taken short jump (`branch_short`, `dbnz`: a one-byte displacement, no stack cycle) whose opcode is at an odd address raises no fetch request after its start clock, its bytes taken, unless a fetch was on the bus on that clock; BR near and CALL at an odd address fetch and are outside the rule | `F30-out-br-short-n0-pad1-pE-w0`: BR short at 1004F starts on M0's I/O issue 87 with no fetch on the bus, silicon's next fetch the target's at 98 (hold: F90, a word the flush drops); the callret BR at the RET's odd target the same; F30 +48, F23 +30 (shapes A and E) |
| `str_exit=wb` (eu) | a REP form's exit ends `xwb` clocks (2) early, those clocks a write-back only a `wbsync` form (the port-form OUT) waits for: the decoder is free 2 clocks earlier before any other successor | `F31-out-alf-stm-n1-nop-pE-w0`: REP STM's write 112–114, silicon's next fetch 132 and M1's I/O 139 (eu: F134, I141); `-n1-end` (M1 straight after) I133 either way; F31 `alf` 156/156 |
| `str_split=floor` (none) | when the stream's last cycle was split (an odd word) the exit starts no earlier than `xsplit` clocks (4) after the second half's issue, except after a single-read element (LDM, CMPM: the EU waits for the data); covers the split writes (STM, MOVBK, INM with IY odd) and CMPBK's split IX overrun read | `F30-out-odd-stm-iy-n1-end-pE-w0`: the split write 112–114 and 115–117, silicon's next fetch 139 and I142 (none: F138, I141); at w1 and w2 the end + 1 bound holds; F24 shape 2 (30), F30 `odd` +58 |
| `str_io_setup=run` (nowait) | REP INM/OUTM's nowait setup counts the first wait clock of a fetch that issued on the setup's first clock back to back after another fetch (the post-marker refill still running back to back) | `F30-out-str-inm-w-n1-l0-pE-w1`: the refill 89, 93, 97 back to back, the setup from 97, silicon's I/O 115 (nowait: 116), STM's write 116 either way; F31 `lone` INM = STM to the clock in all 72 runs; F24 shape 1, all 60 runs |
| `str_start=skip` (count) | a REP form's take sync is met on the last clock of the aborted cycle that answered the request of its start clock (no word comes) | `F30-out-str-stm-w-n1-sep-pO-w0`: REP STM starts 120 after `SHL AW,8` with no fetch since 97, the aborted cycle 120–122, silicon's write 140 (count: W141) |
| `str_fetch=hold` (room) | a REP form raises no fetch request from its first element's post until `xfetch` clocks (8; `str_out` 9) after the stream's last cycle has ended; with CW = 0 the aborted start's request is raised again `zfetch` clocks (`zexit` − 4) into the exit; with it `str_out.nx` 1 → 0 (OUTM's IR load on its start clock) | `-stm-w-n1-sep-pO-w0`: the write 140–142, silicon's fetch 151 (the last cycle's end + 9 at every wait, n = 1 and 2, STM and INM; OUTM's I/O end + 7); `-stm-w-n0-sep-pO-w0` F132 (room: F139); `-outm-w-n1-sep-pO-w0` no fetch at 120 (nx 1: F120); F30 `str` 342/342 |
| `sreg_io=hold` (free) | a MOV sreg,r/m (8E, `Op.sreg` "load") decoded behind the OUT before its I/O's setup counts out holds that I/O one clock | `F30-out-seg-8e-ds1-aw-n0-pE-w0`: 8E starts on 84 where M0's I/O would issue, silicon I85 (free: I84); every sreg field and operand kind, k = 1 and 2; behind a NOP and every 8C form exact either way; F25 E (+12) |
| `sreg_store=own` (store) | MOV r/m,sreg's (8C, `Op.sreg` "store") write issues only after one clock on which it was issuable but for a fetch on the bus, and holds fetches on that clock: the segment register's datum reaches the bus unit a clock after a general register's | `F30-out-seg-8c-bw-ds1-n0-pO-w0`: M0's I/O 85–87, silicon's write 91 where MOV [BW],AW's is 90 (store: 90); `push-...-pO-w0` posted 86 on an idle bus, silicon 87; F30 `seg` 336/336 |
| `lea_disp=split` (none) | after an LDEA whose two-byte displacement is split across two words (its last byte the even half) the successor does not start on the issue clock of a back-to-back fetch; not after an LDEA started on an I/O's issue clock (`lea_io` applies there) | `F30-push-lea-bw_d16-k1-pE-w1`: LDEA [BW+200h] at 1004D, the refill 82, 86, 90 back to back, silicon's PUSH write 100 = the third fetch's end + 7 at every wait (none: W96); pO (the d16 in one word) exact either way; F25 B (+23), F30 +18, the 3 `nopb` losses |

REPC (65) and REPNC (64) are decoded as REP prefixes (`templates.REP_PREFIXES`), the compare's exit the chain walk's
(`normalize.WALK_STRING_FORMS`: the carry in place of Z), the template never reading which flag; all 186 F33 REPC/REPNC
runs simulated with the STC/CLC replaced by a NOP give the model's data cycles equal to silicon's (addresses and widths,
the overrun included). F33 stays in `families.UNMODELLED` until its other forms are modelled. Nothing-lost gate (the
overseer's re-run, scratchpad wp76r/, as for the fortieth): byte-identical on 27 other lists in both comparisons; F27's
exact count 889/1,072 unchanged with two miss traces (`out-fc-beat-ds1-n0-pE-w0`, `-ec-`: 8E after the marker OUT with
refresh on) diverging later and the residual histogram improved; F23, F24, F25, F31 won only, F30 won 393 lost 3. The
RTL has none of the nine mechanisms until the next catch-up package (WP77): at the adoption `rtlgen` refuses the string
template's new step kinds (`fetch_release`, `split_floor`: "not a string template step"), so the include stays the
fortieth fit's, the benches cannot rebuild and no RTL gate runs until rtlgen expresses them; the adoption was held in the
live tree and committed with the catch-up.

**Facts left, none encoded** (wp76/): BNE and DBNZ not taken, F30 `nt` 90 of 144 and all 27 F23 misses (BNE 18, DBNZ
9); the RET's refill, F30 `cr` 12; LDEA, F30 `lea` 25 (the 3 `nopb` cells among them) and all 19 F25 misses (OUT 15,
PUSH 4); the second instance of an unprefixed string pair, all 44 F24 misses (series `s`). F30 `str`, `odd`, `seg` and
`br` and all of F31 are exact.

**The forty-second fit** (`fit.json`, md5 e7b1d062; scratchpad wp78/fit-wp78.json, WP78, fitted and verified 2026-10-30,
adopted the same evening once the RTL had caught up to the forty-first fit (WP77) and rtlgen read the frozen package;
the RTL left the F32/F33 classes unbuilt, `rtlgen.UNBUILT_CLASSES`, so the 33 gate lists were unchanged by it;
WP79 built them later the same day, 28,142/28,142 against the model) models the 0F page and the register miscellany (Facts "The 0F page and the
register miscellany"). Twenty-three new classes, two new enums, two new integers on existing classes (`mul.sexec` 41,
`div.sexec` 58: the signed register multiply and divide), no existing field, EA entry or integer changed; F32 42 →
379/858 and F33 116 → 841/1,050 (the decode alone, at DEFAULT_COST, gives 343 and 841; the fit's integers and
`page_grp=group` the rest), 26,643/28,142 over the 35 lists, the 33 earlier lists byte-identical at 25,423. Stage 16
(`fit.py` `F42_CLASSES`, `F42_ENUMS`, `F42_INTS`) from a hand start read off the facts tables under the corpus guard,
1,161 s: 1,197 → 1,220 on F32 + F33 (7 of 16 moves refused), the sweep taking `page_grp` none → group (+36 F32 net: 53
won, 17 lost within F32, the SET1/NOT1 [BW],CL cells at pO; the family-mode guard allows the trade, nothing lost against
HEAD). Each new class shares an existing class's structure (`templates.BASE_CLASS`: the EU applies every class-named
rule to the base class and reads costs from the class itself) and has its own integers; the format integers `nx0` (a
form without operand bytes holds its successor's IR load from its start), `sexec` and `cl` (the CL-index clocks) are
absent on every existing class. `families.UNMODELLED` and `forms.UNMODELLED_FORMS` are empty: `score`, `fit`, `freeze`
and the corpus guard take all 35 lists. `test_sim.PageAndMiscellanyDecode` and `PageAndMiscellany` pin the decode, each
enum against its alternative on its deciding run, the BCD loop and the templates' data cycles; `test_fit.PageMiscStage`
the stage. No rule keys on an opcode byte (the second opcode byte selects a class as the first does), a parity, a wait
count or a neighbour.

| Enum (value) | Mechanism | Pinned by |
| --- | --- | --- |
| `page_grp=group` (none) | a 0F memory form (TEST1/CLR1/SET1/NOT1 r/m, ROL4/ROR4 r/m: the operation named by the second opcode byte) runs its class's group setup as a group opcode's memory form does (`grp`, `grp_free`, `grp_mode`), the CL-index clocks part of it; none: the `cl` clocks as EU clocks before the read | `F32-out-set1_mb_cl-k1-pE-w0`: the refill 87, 90 back to back, silicon's read 95 and write 100 (none: R96 W101); none −18 F32 |
| `bf_count=dw` (data) | the bit fields' requests (EXT/INS: the word at IX/IY, no EA) count their setup as a DW-form I/O request's, as the strings' under `str_count=dw` (only a wait state stops the count); data: as a memory form's | `F32-out-ext_bl_dh-k1-pO-w0`: M0's I/O 85, the refill fetch 88, silicon's read 97 (data: R96, start + 12 whatever the fetch); data −31 F32 |

The decoder: the IR holds 0F and the second opcode byte is taken first (`Op.page` tells the ModR/M latch to skip it); a
DS1: prefix before an 0F form stays its own prefix instruction; 40–4F (`ONE_BYTE`), D4/D5, the FE group and 69/6B
(`mul_imm`) decode; `execute` tracks INC/DEC, the converts, the signed register multiply and divide, MUL imm and the bit
field's offset register and IX/IY step, the registers used whole (not reduced to 4 bits), as silicon does. Templates
(`_wp78_steps`): the register forms and CVTBD/CVTDB on the reg and imm shapes; the memory bit ops, digit rotates and MUL
imm memory on the load_alu, rmw and mul shapes (MUL imm takes its immediate once the read is issued); the BCD strings a
byte-pair loop (`first`, `mid`, `wmid`, `loop`, `exec`) whose pair count comes from the chain walk (`normalize.bcd`
returns a `StringRun`, keyed by the 0F opcode's offset); the bit fields a class whose cost is docs/v35s-eu-timing.md's
formula (`bf_cost`) less a class constant, the field read and written per word with the crossing pattern from the facts
(`setup`, `xsetup`, `span`, `xspan`; INS `wsetup`, `xwsetup`, `xrsetup`, `post`). Tried and removed: `bcd_count`,
`page_commit`, `page_sync`, `isetup`, `ir_end` (a late IR load for the bit fields and MUL imm memory: stage 16 kept its
default and it lost overall).

**Facts left, none encoded** (wp78/): the bit fields (about 13 % exact: reads and writes ±1, at pE the model's word read
before silicon's back-to-back refill fetch at 90; at pO the imm forms suggest the successor's opcode held out of the IR
until near the end); the register bit ops (about 36 %: at pO with the index in CL silicon runs a back-to-back fetch the
room rule does not raise, ±1–7 second-instance offsets at k = 2); the memory bit ops' misses that move by parity and wait
(`bit1_*.pre`/`cl` flagged by the knob dependence); INC/DEC r16 and the flag forms −1 on the first fetch after the OUT at
pE and −4 at k = 2; CLI/STI/CVTWL/ADJBA small offsets; MUL imm memory at pE (silicon fetches near the end); BCD at pO
k = 2 and behind the DS1: prefix −1; the ADJ4A k = 2 and the MUL/CVTWL data dependences, unprobed. F34 probed the first seven the same evening (Facts "Probes
for the forty-second fit's miss shapes"); its readings are the forty-third fit's brief.

**The forty-third fit** (`fit.json`, md5 cfc8902b; scratchpad wp81/fit-wp81b.json, WP81, fitted and verified
2026-10-30, adopted 2026-10-31 once WP82 had landed, the RTL catching up next) encodes F34's readings (Facts "Probes for
the forty-second fit's miss shapes") as eight enums and ten new class integers; no EA entry changed. 27,112 → 27,838 of
29,738 over the 36 lists: F23 333 → 351/360, F30 1,349 → 1,421/1,476 (their not-taken BNE/DBNZ and CALL/RET runs share
F34's shapes; gains only), F32 379 → 440/858, F33 841 → 927/1,050, F34 469 → 958/1,596 (per probe: bf 30 → 141, rbit
53 → 86, mbit 46 → 185, inc 119 → 128, mul 7 → 42, nt 72 → 192, cr 76 → 118; the empty frame and the leads 66/66
throughout); 31 lists byte-identical; 873 runs won, 104 lost, every loss inside F32/F33/F34 (SET1/NOT1 [m] at pE, which
the old per-class split had exact; INC/DEC r8 at pE w1/w2, 8 runs, the cost of `wb_fetch`; bf imm4 at l0 pE w2; rbit imm
behind SHL AW,8 or NOP NOP). Stage 17 (`fit.py` `F43_ENUMS`, `F43_CLASSES`, `F43_INTS`) ran twice under the corpus guard
from a hand start read off the readings: 2,197 → 2,257 on F32 + F33 + F34, then, with the rule that a fetch running while
the ready read waits restarts its count (+62 −6), 2,313 → 2,325; the sweep took `mul_imm_read` back to `issue` with
`mul_imm.rsetup` 2. Flip numbers at the candidate (each enum back to its old value): `page_mem` −233, `bf_read` −135,
`xfer_nt` −117, `page_take` −107, `wb_fetch` −100, `stack_wb` −54, `mul_imm_hold` −35. No new template step kind or tag.
`test_sim.MissShapes` pins each enum against its alternative on its deciding run and the not-taken write-back integer;
`test_fit.MissShapeStage` the stage. No rule keys on an opcode byte, a parity, a wait count or a neighbour; `xfer_nt` and
`mul_imm_hold` key on the operand's word alignment, `stack_wb` on the reading class and the write-back's presence.

| Enum (value) | Mechanism | Pinned by |
| --- | --- | --- |
| `page_mem=fixed` (group) | a 0F memory form's read (TEST1/CLR1/SET1/NOT1 r/m, ROL4/ROR4 r/m) issues `fsetup` clocks (plus `cl` with the index in CL) after the last fetch's end, every one fetch-free, counted back from the read's post to the form's start; a fetch the bus unit committed back to back after the start runs inside the count, any other fetch restarts it (one running while the ready read waits too); no group setup; one rule for every op | F34-out-mbit-test1_mw_cl-l0-k1-pE-w0 R95 (group R98); the pO twin R96 exact under both; F34 reads TEST1, SET1 and CLR1 on one clock in all 84 cells |
| `bf_read=fixed` (count) | a bit field's first word read issues `fsetup` clocks plus one per immediate byte after its post, every one fetch-free (a fetch on the bus at the post restarts the count, a committed back-to-back one runs inside it) | F34-out-bf-ext_bl_dh-nop-k1-pE-w0 R100 (count R105); EXT = INS, crossing = within |
| `page_take=own` (operand) | a 0F register form's (and a bit field's) second opcode byte is a take of its own on the start clock, chained to the rest, as the memory forms' head takes it: the byte leaves the queue a clock or two earlier | F34-out-rbit-set1_rw_imm-nop-k1-pO-w0 F89 (operand F90) |
| `xfer_nt=odd` (none) | a not-taken short transfer (BNE/BE, DBNZ) at an odd address holds its fetch request as `xfer_odd=idle` holds a taken one's, until `nhold` clocks into the clocks after its operand take; DBNZ holds whatever the bus; with `branch_short.wb`/`dbnz.wb` 2, the form's last clocks a write-back only the port OUT waits for (the PUSH frame exact without it) | F34-out-nt-bne-d-k1-pE-w0 F103 (none F100); F34-out-nt-dbnz-l0-k1-pE-w0 F99 (none F94) |
| `mul_imm_hold=word` (none) | MUL imm memory with the immediate's last byte the even half of its word (the next opcode its second) raises no fetch for `mhold` clocks from the read's post | F34-out-mul-mul_aw_m_imm8-l0-k1-pE-w0 R90 F134 (none R93) |
| `mul_imm_read=issue` (imm) | the read posted as the immediate forms' is, `rsetup` 2 carrying the lateness; the sweep refused `imm` (+26 for issue) | the reading "a clock per immediate byte" stays a cost |
| `wb_fetch=hold` (free) | a fetch requested before a wbsync form's start (the port OUT), or on a word's delivery on it, does not start on that start clock while the predecessor's write-back runs; a committed back-to-back fetch and one the start itself raises are not held | F34-out-inc-inc_aw-l0-k1-n0-pE-w1 F89 F93 I101 (free F88 F92 I100); F33 +95 net |
| `stack_wb=ret` (none) | a RET's stack read posted on its start clock while the previous form's write-back runs (an immediate shift's exit) is held a clock, as the string exit's write-back holds a wbsync form; POP's read is not (every stack read: F15/F16/F25 lose 42) | F34-out-cr-shl8-l0-pE-w0 r151 (none r150) |

**Facts left, none encoded** (wp81/): the register bit ops' +7 back-to-back fetch after a word-ending last byte (the
model has no queue change in the fetch's run to re-raise the request; a `page_take=latch` variant lost 257); the imm4
bit fields' mid-span prefetch release (−61) and the l0 pE committed refill fetch inside the field's setup; the memory bit
ops' remaining `pre` split (4/1/1) and the d16/direct modes; MUL imm's read-before-fetch order behind SHL AW,8 and imm16
at pO w0; the not-taken forms' l0 pE back-to-back third refill fetch (+7) and the k = 2 cells; the odd-address shift's
22-clock early fetch before a RET; INC k = 4 at pO +1.

**The forty-fourth fit** (`fit.json`, md5 5f73ebb97bff1097bf18d0c52654bfc3; scratchpad wp86/fit-wp86-pending-noloss.json, adopted
2026-10-31 after the user stopped the RTL and refresh-on work) is the forty-third fit plus three verified candidates
of the same day, each gated alone on all 36 lists and together: WP84's `refresh_scope=live` (a tie: the causal refresh,
Facts "A causal refresh"), WP85's five I/O-sequencer enums beside a refresh (`port_ready_count=count`,
`port_refresh=late`, `refresh_pair_post=before`, `io_step_restart=last`, `refresh_lead_step=step`; Facts "The I/O
sequencer beside a refresh") and WP86's `page_b2b=reg` and `page_run=field` with `bf_ins.xwsetup` 69, `xrsetup` 12,
`xspan` 105, `rol4_mem.fsetup` 3 and `ror4_mem.pre` 1 (Facts "The 0F page's fetch commitments"). 27,838 → 28,215 of
29,738 over the 36 lists: F27 889 → 932/1,072, F28 820 → 898/1,088, F32 440 → 560/858, F34 958 → 1,094/1,596; the
other 32 lists byte-identical except one already-missing F13 trace after its divergence; no run lost anywhere. Stages 18
to 20 (`fit.py`). The refresh-off corpus stands at 24,021 of 25,106 (F34 502, F32 298, F33 123, F30 55, F24 44, F29 29,
F25 19, F23 9, F22 6 missing) and is the focus from here; the refresh-on families (F8, F13, F17, F18, F27, F28) and the
RTL mirror are not worked further (the RTL stays at the forty-second fit's structure; its catch-up to the forty-third,
WP83, is parked on branch `wp83-rtl-catchup`; docs/v35s-hdl-plan.md "Synthesis trial").

**The forty-fifth fit** (`fit.json`, md5 296300307303010bf4ca64d11f66cbb4; scratchpad wp88/fit-wp88.json, adopted 2026-10-31) is the
forty-fourth fit plus WP88's candidate: the F35 and F36 forms decoded (the class-equivalent ones into their classes),
twelve classes on existing structures (`bcwz`, `dbnz_z`, `ret_imm`, `ret_far`, `ret_far_imm`, `call_reg`, `call_far`,
`br_reg`, `branch_far`, `load_ptr`, `pop_psw`, `test_reg`) and `ret_imm_hold=word` (Facts "Control flow completed and
the data forms no family had run"). 28,215 → 29,884 of 31,532 over 38 lists: F35 922/1,044 and F36 747/750 newly
scored, all 36 earlier lists byte-identical; stage 21 (`fit.py`). The refresh-off corpus stands at 25,690 of 26,900
(F34 502, F32 298, F33 123, F35 122, F30 55, F24 44, F29 29, F25 19, F23 9, F22 6, F36 3 missing). Model side only, and
the RTL mirror now lags for good: `rtlgen` fails outright on the frozen package (`RtlgenError: step ('fetch_hold', 2)`,
the fetch hold inside a template, which the include's format has no place for), so the include stays at the
forty-fourth fit's and `test_rtlgen` leaves the maintained set (nine offline modules from here; it is RTL-side, with
`test_rtl_vectors` and `test_chain_lane`).

**The forty-sixth fit** (`fit.json`, md5 c13152ddfe0c637a30d9500332b9ec38; scratchpad wp89/fit-wp89.json, adopted 2026-10-31) is the
forty-fifth fit plus WP89's two not-taken transfer mechanisms, `xfer_nt_b2b=decide` and `decide_abort=cycle`, with
`dbnz_z.nhold` 2 and `chold` 5 (Facts "The not-taken transfer's back-to-back fetch and the aborted cycle's gap").
29,884 → 30,041 of 31,532 over 38 lists: F23 360/360, F30 1,451/1,476, F34 1,118/1,596, F35 1,016/1,044; the
other 34 lists byte-identical; nothing lost. Stage 22 (`fit.py`). The refresh-off corpus stands at 25,847 of 26,900
(F34 478, F32 298, F33 123, F24 44, F29 29, F35 28, F30 25, F25 19, F22 6, F36 3 missing; F23 complete). F37 (432
runs) is in the corpus but unmodelled and not scored. Model side only, no RTL work.


### Fitted structure (forty-sixth fit, 2026-10-31)

Forty-six fits so far. The first (`fit-wp5.json`, 994/3404) let the queue hold
7 bytes. The second (`fit-wp6.json`, 1146/3404) made storage physical
(6-byte queue, instruction register as a seventh byte outside it, an
in-flight word reserves 2, the simulator raises on any clock ending with
more than 6 bytes queued) and gained the F6 drain but lost 21 of the 60
PUSH-marked F2 runs. F9 was recorded to pin the restart rule and the third
fit (`fit-wp7.json`, 1724/3812) found the missing element: a one-byte write
latch on the queue. The fourth fit (`fit-wp8.json`, 1989/3812) kept that queue and reworked
the EU-side templates for memory forms, with OUT-marked chains held out.
The fifth fit (`fit-wp9.json`, 2695/3812) found the I/O mechanism and
brought the OUT-marked chains into the objective and the polish guard. The
sixth fit (`fit-wp11.json`, 3045/3812) found the bus unit's data latch,
which fixes the 0-wait I/O column, rebuilt the IN template and made the
from-scratch fitter path reproduce the structure. The seventh fit
(`fit-wp12.json`, 3135/3812) worked the immediate memory forms and the DW
I/O forms. The eighth fit (`fit-wp14.json`, 3478/4148) recorded F10 and
F11 to settle findings 3 and 4 of the seventh and added one rule from
each. The ninth fit (`fit.json`, 3797/4352) recorded F12 around the OUT
after a register form and the 4-byte immediate, fixed the queue overfill
F12 exposed, and added seven rules, five of them with nothing lost. The
tenth fit (`fit-wp19-hand.json`, 3933/4352) recorded F14 around findings
2, 4, 5 and 9 and added six rules with nothing lost on F0–F12. The
eleventh (`fit-wp20-hand.json`, 4007/4352) recorded F15 to settle what F14 left
and added seven rules, +84 −10 on F0–F12. The twelfth (`fit-wp21-hand.json`,
4049/4352) recorded F16 as a ladder over every reg value of the D0/D1
and F6/F7 groups, refuted the reg-field bit, and added four rules and
the signed and byte multiply/divide integers: +42 −0 on F0–F12, +349
−0 over every recorded family. The thirteenth (`fit-wp22-hand.json`, 4130/4352)
took no new data: it re-read the OUT-frame misses of F3, F5, F12 and
F14–F16 and found the two parities' effects to be one mechanism, the
register unit forms' dropped request and the fetch's hold on their
exec; eight rules, +81 −0 on F0–F12, +283 −0 over every family. The
fourteenth (`fit-wp23-hand.json`, 4130/4352 unchanged on F0–F12) recorded F17,
where the chain itself turns refresh on after the fill, read the
refresh timer off as a free-running binary counter whose value at clock
0 is a constant of the prelude, and replaced the per-run timer
alignment with that constant at no cost; eight refresh rules take F13
from 43 to 62/462 and F17 to 275/798, with no refresh-off run moved.
The fifteenth (`fit-wp24-hand.json`, 4130/4352 unchanged on F0–F12) recorded
F18, a marker closing the prelude under three RFM values and a ladder
placing the first refresh request at every exec clock of the unit
forms; three refresh rules, +65 −0 over the refresh-on families (F13
67/462, F17 305/798, F18 199/1164) and no refresh-off run moved. The
first LS's start under a refresh-on prelude is observed but not
derived. The sixteenth (`fit-wp25-hand.json`, 4148/4352) recorded F19, a ladder
over the immediate memory forms and the DW I/O forms after a register
form, and added three rules with three integers: the immediate form's
count floor from its start, the DW form queued behind an I/O without
relatching it, and its hold on the lead-clock fetch; +18 −0 on F0–F12
(all F5) and F19 895 to 1109/1290, nothing lost anywhere. The
seventeenth (`fit-wp26-hand.json`, 4211/4352) recorded F20, a ladder of register
forms by length and last byte before a load, a store, an RMW, an I/O
form and another register form, and added five rules with one integer:
the fetch request re-evaluated after a fetch's issue, the ModR/M's
immediate word-mate keeping its slot, no start without a ModR/M on a
back-to-back fetch's issue clock below 3 stored bytes, and two DW-form
counts; +63 −0 on F0–F12 (F6 575/576), +123 −0 on the old corpus, F20
3289 to 3559/3594. Finding 4 is closed but for 4 runs. The eighteenth
(`fit-wp27-hand.json`, 4218/4352) recorded F21, a ladder over the EA modes by
displacement width and alignment against five consumers, and found the
address path to have two costs: the displacement's take clock, whatever
its width (a d16's two bytes go together when queued), and one more for
base+index with a d16; the displacement is taken after the EA clocks
for the immediate forms too, with no sync after it, and the direct
address behind a ModR/M byte is a d16 with no register. Seven rules
(two of them integers) and two refits: +7 −0 on F0–F12 (all F4), +409
−1 over every family, F21 2547 to 2901/3576; the one run lost is
refresh-on (item 8 h). The nineteenth (`fit-wp28-hand.json`, 4233/4352) took no new
data: it tabulated F21's misses by the queue count and the fetch in
flight at the displacement's take and found them to be three take
states, not alignments, widths or consumers; four rules and one integer
(the next opcode held in the queue until a displaced form's data cycle
issues, the late take as the decoder's rule, a two-clock floor from the
take to the data cycle, the latched byte counted on a take clock):
+15 −0 on F0–F12 (all F4), +469 −0 over every family, F21 2901 to
3352/3576. The twentieth (`fit-wp29-hand.json`, 4249/4352) took no new data
either: it logged every clock on which a posted memory request, a free
bus and a wanted fetch met, by the request's setup phase, the queue
count, the bytes outstanding and the fetch's provenance, and found
items 10 a and b to be one state (a fetch first requested on the
delivery clock of the fetch that just ended is never run on the clock
before the request's first fetch-free setup clock, 110 cells, unless
that fetch was itself a run's) and 10 c to be a floor every mod 00
form already kept (the first data cycle at s + 5 in 9,420 cycles);
five enums (the hold at the free clocks' eve, its idle clock in a run,
the I/O and ModR/M forms' wait beside an older fetch at 2 stored, the
floor from the address step for the mod 00 forms and for a request
posted before the take): +16 −0 on F0–F12 (all F5), +216 −0 over every
family, F21 3352 to 3493/3576 with the marker-less series 936/936.
The twenty-first (`fit-wp30-hand.json`, 4280/4352) took no new data either: it
logged every displacement take, every I/O issue clock and every clock
on which a fetch was wanted only through the IR's seventh slot, and
found the base+index+d16 group to be the one state in the corpus in
which a displacement is taken on an I/O cycle's issue clock (78 takes,
the fetch after the I/O a clock late in every one) and, under PUSH,
the IR counted as room inside the EA clocks before the take (0 of 18
cells fetching, every cell with the EA clocks done); the RMW's early
write beside a fetch and the k = 2 immediate store's start beside one
fell to two more states. Four enums (the I/O cycle extended a clock
by a take on its issue clock, the IR no room inside a displaced form's
EA clocks, the RMW's ALU clocks counting through a fetch, the
immediate form's start waiting out a fetch below 4 stored): +31 −0 on
F0–F12 (F4 456/456, the first memory-stage family fully exact, F5
824/840), +118 −0 over every family, F21 3493 to 3573/3576. The
twenty-second (`fit-wp31-hand.json`, 4289/4352) took no new data either: it
classified every left-out write's slot (CMP and TEST read like an RMW
and write nothing) by the queue's room and the bus history, and the
first data cycle of every TEST and CMP form against its ADD/AND twin
by what stood in its head. The slot fetches only with room for a word
not counting a word delivered on the slot clock, is no bus cycle when
it carries no fetch, and fills the data latch as the write it stands
for would; TEST's fixed lookup counts a clock on an aborted start
cycle, sits before the group decode its immediate form's floor counts,
and costs a clock more after a start-clock fetch; and CMP r/m,reg is
the RMW with its write left out, the tenth fit's refuted alternative,
right once the slot rules were in. Seven enums (one an existing value)
and three integers: +9 −0 on F0–F12 (all F5), +116 −0 over every
family, F19's immediate series 630/630, F14 728/732, F15 836/840,
F16 R 294/294. The twenty-third (`fit-wp32-hand.json`, 4302/4352) took no new
data either: it logged every 8B register form's ModR/M take state,
every fetch issue on which the request is kept raised and every port
byte taken while an I/O waits, and found the register form's IR load
visible in only two states, which disagree on `reg.nx`: a take on the
marker I/O's issue clock (the next start at T + 3, 64 of 64) and a
take on an idle bus after `ES: NOP` (T + 2, 13 of 13). `reg.nx` is 1,
closing the oldest knob dependence (by marker and n since the ninth
fit), with the load a clock later after a take on an I/O issue clock;
a byte latched behind a full queue goes in on a ModR/M take clock; a
NOP's back-to-back fetch after an I/O waits for the next start; a port
byte taken on a fetch's issue clock lands a clock late; an instruction
starting as a latched byte goes in loses that clock; and the aborted
cycle's room test does not count a byte still latched. Six enums and
one integer moved: +13 −0 on F0–F12, +42 −0 over every family; F1, F3,
F6, F7, F19 and F20 are fully exact and 15 refresh-off runs are
missed outside F8. The twenty-fourth (`fit-wp33-hand.json`, 4302/4352 unchanged)
took no new data either: it read the four groups left on the
refresh-off corpus to their states and closed three. The direct TEST
under OUT at odd parity is its one bus-free group clock holding a
fetch requested on or after the I/O's issue through the recovery;
`NOP NOP ; MULU AW` is the aborted-start multiply's kept end clock,
which was never observable in the 15 runs it was adopted on and is
wrong in the 3 where it shows; the k = 2 base+index+d16 stores are no
back-to-back fetch inside the EA clocks before the take, with the idle
clock after a fetch committed back to back at the write's eve. The
fourth, `ADD [BW+200h],imm16` at 0 waits, is left open with its reason:
on this corpus a read cannot be told from a write posted on a
non-wait clock. Four enums, no integer: +14 −0 over every family (F14,
F15, F16 and F21 fully exact, F18 201/1164); 3 refresh-off runs are
missed outside F8. The twenty-fifth (`fit-wp34-hand.json`, 4308/4352) took no
new data either and worked the refresh side: it tabulated every
prefix-matched refresh request in the END block against HALT's start
and found the service clocks to be two things, the halt status
holding the bus unit on HALT's first two clocks and a posted I/O's
two-clock lead, and the runs read as served late to be the EU
running two clocks ahead of the bus after a refresh beats the fetch a
take sync counts, the refresh-off schedule moved by the refresh's
length less 2; with the RFMON store's address phase left running
under a refresh and a beaten request dropped after HALT, five enums
(two of them fields already in the code as prototypes): +441 −0, all
refresh-on (F8 7/48, F13 151/462, F17 480/798, F18 386/1164), the
refresh-on END mismatches 1821 to 1380, the refresh-off corpus
unchanged. The twenty-sixth (`fit-wp35-hand.json`, 4312/4352) took no new data
either: it tabulated the END I/O's setup count clock by clock, the
queue's flag and room at HALT, and every loop eve with a refresh
request pending, and found the 37 END rows to be the early fetch run
as the I/O's count sees it (the wait states moving with the issues),
the F13 runs with a fetch at H+2 to be a request lost to a refresh
and not evaluated again until the next instruction start, and the
fifteenth fit's loop-eve window to have measured the hold of a
refresh already on the bus, not the acceptance of a pending request,
which silicon never takes at the eve but in one cell of 7 runs. Three
enums: +245 −0, all refresh-on (F8 11/48, F13 192/462, F17 578/798,
F18 488/1164), the refresh-on END mismatches 1380 to 1110 and only 4
refresh-on runs now first diverging in the END block; the refresh-off
corpus unchanged. The twenty-seventh (`fit-wp36-hand.json`, 4315/4352) took no
new data either: it tabulated every instruction the model starts
inside a refresh cycle's window by the instruction before it (13,649
prefix-matched refreshes) and found the NOP's empty operand take
letting the next start through on the refresh's last clock, where
every other start waits a clock; every refresh request inside a
register shift's and multiply's exec by its offset, finding the
multiply's last 8 clocks (the divide's 6) to run as a loop exit with
even-spaced boundaries and `SHL AW,1` to lack its exit's clock, not a
loop clock; and, in the re-read, the aborted request under a refresh
and the I/O lead's first free clock. Six enums and two integers: +439
−0, all refresh-on (F8 14/48, F13 211/462, F17 641/798, F18
842/1164), the refresh-on END mismatches 1110 to 731, 1,386 of 2,142
refresh-on runs exact (947 before); the refresh-off corpus unchanged.
The twenty-eighth (`fit-wp37-hand.json`, 4317/4352) took no new data either: it
grouped the 520 middle-phase runs by the instruction at the first
divergence and tabulated every refresh between a memory shift's read
and its write, every refresh in its read setup, every request raised
while a take sync waits on an aborted cycle and the count-byte shift's
start on a refresh, and found the memory shift's write setup to have
the register shift's shape end-aligned to the write's issue where the
model had even distances, its read setup to count through a refresh,
a memory form's aborted request under a refresh to come back when the
next bus cycle ends, the aborted cycle's sync clocks to be the EU's
own, and the clocks step between two operand takes to be no hold
point; two states found in the re-read, the posted request's first
clock and the write-back sync, closed cells the record had not named.
Seven enums, no integer: +127 −0, all refresh-on (F8 16/48, F13
220/462, F17 646/798, F18 953/1164), the refresh-on END mismatches 731
to 604, 1,513 of 2,142 refresh-on runs exact; every multiply and
divide window exact but one request; the refresh-off corpus unchanged.
The twenty-ninth (`fit-wp38-hand.json`, 4318/4352) took no new data either: it
tabulated every refresh served inside a register shift's exec or
count loop (7,374 in the loop, 7,361 of them costing the refresh's
length less 2 wherever they land) and found the loop's parity to come
from the exec's end alone: a refresh on the exec's boundary 4 clocks
before the loop holds exactly one clock, the loop's first clock the
hold point and the eve no boundary, which the fifteenth fit's
`refresh_recent` window had stood in for (the window is no longer
read). With the on-chip SFR store's setup counting through a fetch, a
refresh's wait states counted before an I/O's count when the cycle
started earlier, and a request lost at a word of room inside a unit,
four enums: +234 −0 (F8 17/48, F13 236/462, F17 727/798, F18
1089/1164, 8 of them the F17 W ECh refresh-off twins), the refresh-on
END mismatches 604 to 399, 1,739 of 2,142 refresh-on runs exact, and
no integer's best value differing by any knob. The thirtieth
(`fit-wp39-hand.json`, 4320/4352) took no new data either: it read the marker
OUT's missing fetch off every refresh-beaten fetch (a second fetch
back to back while an IN or OUT's I/O has not issued, 477 of 477,
whatever room the request rule counts) and the one state of 3,301
instruction starts on a refresh's first clock that is late (an
operand take behind a byte latched at a full queue); two enums, +15
−0 (F8 19/48, F13 242/462, F17 729/798, F18 1094/1164), the
refresh-on END mismatches 399 to 384. Its agent also measured, as a
diagnostic only, the first LS's exec offset per refresh-on prelude
cell (−2, +1 and −2 clocks at pE 0 waits, pE 1 wait and pO 2 waits,
about 154 runs): a per-cell alignment, which the record keeps out of
the fit (item 8 a). After the thirtieth fit the harness was extended
(2026-10-23): the normaliser keeps the prelude's tail from its POP PSW
read to clock 0 as a second event list, the scorer compares it beside
the score (`score --pre`), and the model can run the tail from that
read with the refresh counter's value there a constant per RFM and WTC
(`prelude_anchor=pop`, `refresh.POP_COUNTER`, `pop_exit` 4). The
existing score is byte-identical under the new code for every run.
With six further rules read off the pre window the model reproduces
it in 40 of 42 prelude cells (every refresh-off cell, 2,138 of 2,142
refresh-on runs), derives the thirtieth fit's per-cell offsets from
its own run, and would score 17,572 (+192 −51); the 51 lost are
refresh-on runs after clock 0, 47 of them the marker OUT under a
refresh-on prelude, so the candidate is not adopted and the stand-in
tables stay. The six rules are in the code at their old defaults,
neutral on every run under the stand-in. The thirty-first fit
(`fit-wp41-hand.json`, 4330/4352) then read the candidate's 51 losses and met
the gate: a port-form I/O's lead holds a refresh only on its last
clock, a request a refresh would lose on the clock an I/O form posts
stays raised and runs on the lead's first clock, a refresh does not
start while an I/O form waits for the data latch, a fetch requested
on a 3-clock beaten fetch's delivery clock with the second byte
latched is committed there and starts a clock later, and the FFh
1-wait counter at the read is 79 (read off two runs after clock 0, the
window having no refresh); four enums and one table entry, with the
tail (`prelude_anchor=pop`, `prelude_tail=segs`, `pop_exit` 4, the six
harness-extension rules and `wlatch_ir_at=start`): +211 −0 (F8 29/48,
F13 384/462, F17 749/798, F18 1133/1164), the pre window exact in
every one of 17,822 runs, no refresh-on run first diverging at the
first LS, `PRELUDE_COUNTER` and `SILICON_FILL` no longer read, the
refresh-on END mismatches 384 to 175. One overfill found by the fitted
configuration's overfill test on a generated chain was traced to the
lead rule's first version and fixed before the figures above were
taken. The thirty-second (`fit.json`, 4333/4352) recorded F22, a
ladder of the immediate memory forms by mode behind the F21 lead-ins
in three frames, to decide item 1's three runs, and found the read
of an immediate RMW to run exactly as the write of the immediate
store in the same cell through its first data cycle (600 of 600
cells): the model had posted the read a clock early, lacking the
store's EU clock after the displacement's take, so the three runs
were a missing integer, not a kind of request. Two more states the
corpus had never held: TEST r/m,imm16 with a displacement runs TEST
84/85's fixed lookup between its ModR/M and displacement bytes and
then only its group's own setup, and a one-byte immediate's first
request issuable on a non-run fetch's delivery clock goes before the
fetch requested there while the queue counts more than 3 bytes. One
integer and two enums: +3 −0 on F0–F21 (F5 840/840: the refresh-off
corpus of F0–F21 exact outside F8), F22 1068 to 1314/1320 (one run
lost, exact before by a wrong head), 18959/19142 over the 23
families (first recorded here as 17959, a slip of a thousand); stage 5
with F22 in its families chose nothing. The thirty-third (`fit.json`,
4333/4352) came from the fitter's stage 6, run through every grid
under the family guard with no exact gain: of the 26 alternatives it
recorded as inert ties on its tie-break families (which leave out the
refresh-on ones), scored one by one as flips of the hand fit over
every family, 13 are inert everywhere, 12 lose and one gains: an I/O
form's setup counts from its post (the port byte's take), not from
its start (`io_post=take`, the sixth fit's `start` put back). The two
count the same clocks on every run but two: F13's second OUT marker
after `SHL AW,CL` (CL 8) and after `MULU`, odd parity, 1 wait, where a
refresh has pushed a fetch onto the OUT's start clock and its wait
state falls inside the pre; counted from the start the pre needs 3
countable clocks and gets 2, and the I/O lands a clock late. +2 −0
over the 19,142 runs, 18961/19142. The thirty-fourth (`fit.json`,
2026-10-27) adds F25's ten classes and three enums (`lea_form=reg`,
`burst_wait=data`, `prepare_order=write_first`; 446/588, the fitter's
stage 9 under the corpus guard) and drops the six rules the rule register
found inert and the `sync_io` tie (`room_ir_ready=False`, `ea_floor=False`,
`wlatch_ir=False`, `wlatch_ir_at=busy`, `wlatch_mul=take`,
`sfr_setup=fetch_free`, `sync_io=issue`): byte-identical over F0–F22,
19407/19730 over the 24 scored families. The thirty-fifth (`fit.json`,
2026-10-28) adds F23's five transfer classes and six enums
(`refill_start=full_io`, `flush_hold=start`, `flush_inflight=wait`,
`untaken=wait`, `call_order=write_first`, `branch_reg=reg`; 255/360, the
fitter's stage 10 under the corpus guard) and `shift_count_mask=cl8` (the
CL shift count unmasked, F26 906/906): byte-identical elsewhere,
20568/20996 over the 26 scored families. The thirty-sixth (`fit.json`,
2026-10-28) adds the I/O sequencer's steps under a refresh, four fields
and two values (`refresh_io_step=own`, `refresh_io_stall=step`,
`io_step_issue=step`, `port_ready=issue`, `refresh_io_run=pair_out`,
`refresh_post=post_beat`; F27 778/1072, the fitter's stage 11 under the
corpus guard), no integer changed: byte-identical on every refresh-off
run, gains-only on F8 (35/48), F13 (399/462) and F17 (752/798),
21368/22068 over the 27 scored families. The thirty-seventh (`fit.json`,
2026-10-28) adds F28 and F29's eight enums (`refresh_wb=free_wait`,
`refresh_relatch=issue`, `refresh_window=posted`, `refresh_start_seam=start`,
`refresh_step_lead=step`, `refresh_beat_b2b=imm`, `grp_disp=hold`,
`dw_lift=moved`; F28 820/1088, F29 427/456, the fitter's stage 12 under the
corpus guard), no integer changed: byte-identical on every refresh-off
family but F29, gains-only on F8 (37/48), F13 (440/462), F17 (754/798) and
F27 (889/1072), 22771/23612 over the 29 scored families. The
thirty-eighth (`fit.json`, 2026-10-29) adds the seven string classes and
F24's four enums (`str_take=sync`, `str_setup=nowait`, `str_overrun=read`,
`str_hold=hold`; F24 746/912, the fitter's stage 13 under the corpus
guard), no existing field changed: byte-identical on every other family,
23517/24524 over the 30 scored families. The thirty-ninth (`fit.json`,
2026-10-30) adds `str_last=all`, `str_io_latch=write` and `str_count=dw`
with the string classes' `setup` one less and `str_load` `exec` 2 (F24
778/912, stage 13 from a hand start), no field outside the string classes
changed: byte-identical on every other family, 23549/24524 over the 30
scored families. The fortieth (`fit.json`, 2026-10-30, adopted that evening)
adds `xfer_abort=word`, `cond_gap=own`, `burst_count=dw`, `lea_io=recover`,
`lea_room=ir` and `prepare_sync=run`, flips `imm_latch` to `wait`, and moves
`push_r.setup` 9, `prepare.exec` 11 with `prepare.wb` 2, `dispose.setup` 7,
`lea.nx` 0 and the new `branch_short.cfgap` 8 (F23 303/360, F25 534/588,
stage 14 from a hand start): byte-identical on every other family,
23685/24524 over the 30 earlier scored families, 24660/26234 with F30 and
F31. The forty-first (`fit.json`, 2026-10-30, the same evening) adds
`xfer_odd=idle`, `str_exit=wb`, `str_split=floor`, `str_io_setup=run`,
`str_start=skip`, `str_fetch=hold`, `sreg_io=hold`, `sreg_store=own` and
`lea_disp=split`, the string classes' `xwb` 2, `xsplit` 4, `xfetch` 8
(`str_out` 9) and `zfetch` = `zexit` − 4, and moves `str_out.nx` 1 → 0 (F30
1349/1476, F31 234/234, F24 868/912, F23 333/360, F25 569/588, stage 15
from a hand start): byte-identical on 27 other lists, two F27 miss traces
move without a count change, 25423/26234 over the 33 scored families. The
forty-second (`fit.json`, 2026-10-30, the same night) models the 0F page and
the register miscellany: 23 new classes on existing structures, `page_grp=group`,
`bf_count=dw`, `mul.sexec` 41 and `div.sexec` 58, no existing field changed
(F32 379/858, F33 841/1050, stage 16 from a hand start): byte-identical on
the 33 earlier lists, 26643/28142 over the 35 scored families. The
forty-third (`fit.json`, 2026-10-31, fitted 2026-10-30) encodes F34's seven
readings as eight enums and ten class integers (`page_mem=fixed`, `bf_read=fixed`,
`page_take=own`, `xfer_nt=odd`, `mul_imm_hold=word`, `wb_fetch=hold`, `stack_wb=ret`,
`mul_imm_read=issue`; F32 440/858, F33 927/1050, F34 958/1596, F23 351/360, F30
1421/1476, stage 17 from a hand start): byte-identical on 31 lists, 27838/29738
over the 36 scored families. The forty-fourth (`fit.json`, 2026-10-31) adopts
the day's three candidates together (`refresh_scope=live`, WP85's five refresh
enums, WP86's `page_b2b=reg` / `page_run=field` and five integers): 28215/29738,
F27 932, F28 898, F32 560, F34 1094; byte-identical on 32 lists. The
forty-fifth (`fit.json`, 2026-10-31) models F35 and F36 (twelve classes,
`ret_imm_hold=word`, stage 21): 29884/31532 over 38 lists, F35 922/1044, F36
747/750, byte-identical on all 36 earlier lists. The forty-sixth (`fit.json`,
2026-10-31) adds the not-taken transfer's two mechanisms (`xfer_nt_b2b=decide`,
`decide_abort=cycle`, stage 22): 30041/31532, F23 360/360, F30 1451, F34 1118,
F35 1016; byte-identical on 34 lists.

**Queue, decoder and arbiter** (settled by F0, F2, F9 PUSH; unchanged since
the third fit except the aborted fetch):

| Machine | Rule chosen | Evidence (clocks after the fill) |
| --- | --- | --- |
| queue | 6 bytes, fetch requested at 2 free bytes, in-flight word reserves 2 | F0 |
| queue | byte-wide write port shared with the decoder's reads (`word_latch=byte_d`): with a decoder read on the delivery clock the word's second byte waits in a 1-byte latch, uncounted that clock, counted after | NOP train, even, 1 wait: word lands at 76 as the IR loads; silicon fetches 72, 76, 91, 95; a whole-word latch fetches again at 80, silicon does not |
| queue | only a committed take or an IR load holds the port (`latch_read=commit`) | `81 C2 ii ii`, even, 0 waits: the immediate's first byte is read at 75 but commits at 76; silicon fetches at 76 |
| queue | no fetch starts while an earlier delivery's byte is latched (`latch_hold`) | `26 90`, even, 0 waits: the byte waits from 78 behind a full queue; silicon fetches at 84 |
| queue | the empty IR counts as room on a delivery clock or whenever no operand bytes are outstanding (`room_ir=arrival_idle`) | `8B C2` odd restarts at 72; `8B C2` even at 75 while `MOV CL`'s immediate is outstanding |
| queue | the request is re-evaluated only when a take commits, the IR loads or a word lands (`request_eval=on_change`) | F0: `MOV DW,imm16` empties the IR at 72 but the fetch comes at 76 |
| queue | on a clock where the EU starts an instruction, takes an operand byte and the IR loads, a request with room for exactly one word becomes an aborted 3-clock cycle: nothing on the bus, the take sync waits for it, the request is raised again when the next bus cycle ends (`abort_fetch=retry`) | two `89 07` even: W87 W95 F98, no fetch at 90, the write at start+5 at every wait; fixed every 0-wait marker-less F9 miss |
| decoder | a ModR/M byte taken inside a multi-byte take leaves the queue count on its own clock (`modrm_commit=byte`) | `MOV AW,[BW+10h]` odd after the PUSH: silicon fetches at 81, not 82 |
| decoder → EU | after an operand take the EU waits for every fetch in flight or requested on the take clock (`take_sync=pending`); a sync whose request has lapsed stops waiting | first fit; the release keeps 9 OUT-marked chains from stalling |
| EU–bus | no instruction starts on the clock after a fetch whose last clock left the request raised (`start_sync=b2b`; since the seventeenth fit `b2b_modrm`: a form with a ModR/M byte only, `io_b2b` holding the rest below 3 stored) | F6 at 2 waits: 83 88 93 98 then 107, third drainer held 98→103 |
| arbiter | data wins unless both requests arose on the same clock, and a fetch the bus unit committed to on the previous fetch's last clock beats a write that has just become issuable (`arbiter=b2b`) | F1 store train at 1 wait: 83 F, 87 F, 91 W |
| arbiter | a posted, not yet issuable data request holds fetches while more than 3 bytes are queued, on every clock; a fetch an I/O request held dates from the clock the I/O becomes issuable (`hold_fetch=le_q_io`; since the fifth fit plain `le_q`, the I/O's dating carried by its `lead`) | PUSH after NOP, even, 1 wait: write 82, fetch 89; odd-parity OUT after the fence: 82 F, 85 I/O |

**EU templates** (fourth fit, chosen from 1,536 enumerated orders on F4/F5):

| Rule chosen | Evidence |
| --- | --- |
| one memory template (`mem_order=split`): pre clocks, the ModR/M take (synced only when it is the last operand byte), the EA clocks, then the displacement bytes; a form without a ModR/M byte (`A1`/`A3`) runs its `pre0` clocks then its address bytes | `89 07` even: F81 F84 W87; the `A3` marker: F75 W78; `[BW+d16]` odd: F81 F84 R87 at every wait, so the displacement leaves before the first fetch ends; mod 00 odd reads 3 clocks after the fetch ends |
| the EA table is 2 for every ModR/M mode class and 0 for direct; `load`/`store` pre 0, pre0 2 | the `store.pre` knob dependence (2 for the direct marker, 0 for `89 07`) is gone; superseded by the eighteenth fit's EA classes |
| only a form without a ModR/M byte posts its data request on the take clock (`post_on_take=nomodrm`) | `[BW+d16]` even: F81 F84 F87 R90; posted on the take clock the read would win at 87; fixed the even-parity `[BW]` vs d16/direct order, F4 170→213 |
| a memory form's immediate bytes are taken once its data request is on the bus (`imm_order=after_issue`) | `CMP [BW],imm16` odd: R88 F91 F94; `MOV [BW],imm16` odd: W88 F91; the four orders score 364/373/361/377 on F4+F5 |
| group opcodes (80–83, 8F, C0/C1, C6/C7, D0–D3, F6/F7, FE/FF: the ModR/M reg field selects the operation, a format property) give their first data request `grp` extra setup clocks, the last `grp_free` fetch-free (`grp_mode=setup`) | INC [BW] odd reads at 89 against ADD [BW],AW at 86; INC even reads 3 clocks after the second fetch ends at every wait |
| a read-modify-write whose operation is a shift adds the shift unit's clocks to the class `alu` (`rmw_shift=shift`), no new integer | SHL [BW],1 odd: R89 W100 |
| a shift by CL with count 0 skips `loop` clocks (`shift_cl` exec 7 + loop 2 keeps LS at 71) | `MOV CL,0 ; SHL AW,CL` was +2 at every knob |
| POP AW has the same setup shape as PUSH (7, last 3 fetch-free) | POP AW even: read 87/88/90 |

**I/O mechanism** (fifth fit; each rule is an option in `sim/config.py` with
a test in `test_sim.IOMechanism` asserting the silicon clocks against the
alternative it replaced; s = the instruction's start):

| Rule chosen | Evidence |
| --- | --- |
| the OUT posts its I/O when its port is latched (at the port take, s+3, or `pre0` clocks after the start for the DW form) and its EU goes on (`io_release=post`, `out.exec` 2); the request waits in the bus unit's single slot and a later data request queues behind it, counting its setup from the I/O's issue clock | F5 OUT then PUSH, odd, 1 wait: I/O 93, PUSH write 99; releasing at the issue gives 98/105 |
| the I/O issues 8 clocks after the start counting only clocks on which no memory cycle is in a wait state (`io_post=start`, `io_count=nowait`, `out.setup` 8; the count from the start is superseded by the thirty-third fit's `io_post=take`, the count from the post, which puts the same clocks on every run but the two F13 OUT runs with a fetch's wait state inside the pre) | F2 OUT after NOP NOP, even, 1 wait, no fetch nearby: I/O at s+10, the old count gave s+8; a fetch's wait state before the port take still delays the I/O (odd, 91 not 90) |
| for the last 2 setup clocks the bus unit is committed to the I/O (`out.lead` 2); after its post the I/O holds fetches whatever the queue holds, except a fetch requested no later than the I/O, which may run on the lead's first clock, and a fetch the bus unit committed to back to back (`io_hold=posted_b2b`) | F2 OUT after NOP, even, 0 waits: fetch 84, I/O 87; F1 single OUT even: the `MOV CL` take at 83 gets its fetch at 87, after the I/O at 84; `MOV AW,imm16` even 1 wait: fetches 76/80/84, I/O 92 |
| one port address latch shared by the decoder's port-byte take and the waiting I/O (`port_latch=relatch`): the take goes and the waiting I/O cannot issue before take+3 (`out.relatch` 3); the taker posts its own I/O once that cycle has ended | F1 two OUTs, even, 0 waits: I/O at 86 and 96 where a lone marker gives 84; "the take waits" gives 84/91 and no latch 84/92, both lose 149 runs; F7 OUT OUT matches at every wait |
| a register-only instruction or a prefix does not start before a waiting OUT's I/O issues; it may start on the issue clock, when the OUT's data passes the ALU (`io_interlock=reg_pfx`); loads, stores, PUSH and port-form OUT/IN run ahead | F3 OUT NOP OUT, even, 0 waits: second I/O at 98, 94 without; NOP, `XCH AW,DW` and `MOV AW,DW` after an OUT have identical timing. The alternative, data immediates waiting for a shared data latch (`imm_latch=wait`), fits the F6 drainer equally and scores no better; it is kept as an option. This is the least physical rule of the set |
| no memory data cycle until 2 clocks after an I/O cycle; the request holds fetches like one still in its setup; a fetch may follow at once (`io_recover` 2) | F4 OUT then load, odd, 0 waits: I/O 85, read 90; 88 without |
| a write-back runs from the producing instruction's end, not the next start (`wb_from=end`; `load.wb` = `load_alu.wb` = 2): the doc's load→OUT −2 | F7 load then OUT, odd, 1 wait: I/O 107, 105 without; OUT load OUT at odd 1 wait (111) shows a start held by a fetch absorbs it |
| a halted EU raises no prefetch | the END block's HALT now starts before its I/O |

**Data latch** (sixth fit; each rule is an option in `sim/config.py` with
a test in `test_sim.DataLatch` asserting the silicon clocks against the
alternative it replaced). This is the fifth fit's untried reading of its
0-wait problem, generalised from writes to every datum the bus unit
handles:

| Rule chosen | Evidence |
| --- | --- |
| a datum occupies the bus unit's data latch for 4 clocks from the clock it enters (`wlatch` 4): a memory write from its issue, read data (memory or I/O) from its delivery clock (`wlatch_src=write_imm_read`), and the last immediate byte of a form without a memory operand from its take (`wlatch_imm=reg`; a memory form's immediate is the write data or the ALU operand) | F5 `MOV [BW],AW` then OUT, even, 0 waits: write 90, the store ends 92, the OUT starts 94 (port take 97, I/O 104), not 93; `wlatch` 3 changes nothing, 5 loses 661 runs |
| an IN or OUT with a port byte does not start while the latch is busy; the DW forms start at once (`wlatch_cls=port`) | F5 PUSH then `IN AL,imm`, even, 0 waits: write 78, the IN starts 82 (fetch 82, I/O 92); `IN AL,DW` after the same PUSH fetches at 81 and does its I/O at 88; holding the DW forms too loses 882 |
| the I/O instruction waiting for the latch holds every fetch; the bus unit is reserved for it (`wlatch_hold`) | F7 load then PUSH under the OUT marker, even, 0 waits: write 101, fetches 105 and 108, I/O 115; without the hold the fetch goes at 104 and the I/O lands at 118; `le_q` scores one run lower |
| IN ends 2 clocks after its data arrives (`in.post` 2, was 4); an IN or OUT after an IN waits until data+4 through the latch, not a write-back | F5 PUSH then `IN AL,imm`, even, 0 waits: I/O 92, data 95, the PUSH writes 103 (post 4 gives 105); recovers all 21 IN runs the fifth fit lost, nothing exact in the fourth fit lost |
| no group setup clock counts during an I/O cycle or its 2-clock recovery; the `grp_free` clocks run only on an idle bus (`grp_free_bus`) | F5 OUT then INC [BW], odd, 1 wait: read 94, the old rule 91; even parity 94 against 92; +67 runs |

The latch explains the load→OUT +2 without a write-back (`load.wb`,
`load_alu.wb`, `pop.wb` and `in.wb` are now 0 with an identical score; the
latch's read source does their job), gives `MOV r,imm16` before an IN or
OUT its +1 at 0 waits and nothing at 1–2 waits (immediate taken at 85, the
latch free at 89; an end-relative `imm.wb` 1 gets that trade wrong and
loses 172), and fixes the fifth fit's finding 6 (F2 OUT after an operand
instruction, now 58/60). Still in use: `out.wbsync` 1 for the shift
write-backs (`shift_cl.wb` 2, `shift_imm.wb` 2). `port_sync` cannot be
decided from this corpus: sync and none give identical model traces on
every run; it is set to none. Refuted along the way and not encoded: an
I/O setup count that skips one clock per memory cycle as well as per wait
(breaks the END block, every run lost); `out.pre0` 0 with `imm.wb` 1 (−68
to −124); a separate latch for write-backs (`wlatch_wb`, changes no run
once the read source exists, removed).

Retired with the fifth fit's mechanism: `out.setup` 6 all fetch-free (now
8 on non-wait clocks from the start, the same for both forms), the I/O
dating rule of `hold_fetch=le_q_io` (now plain `le_q` plus the lead), and
`out.nx` as anything special. Still present: `out.pre` 3, `out.pre0` 1
(the DW form's port latch). IN: pre 3, exec 3, setup 8, post 2.

**Immediate memory and DW I/O forms** (seventh fit; each rule an enum in
`sim/config.py` with a test in `test_sim.ImmediateAndDWForms`). A reading
note first: the parity label is that of the first body byte after the
fence, so under the 1-byte PUSH marker X sits at the other parity (pE puts
X at an odd address, where a 16-bit immediate straddles two fetched words).
Silicon puts the first data cycle of CMP/ADD/MOV `[BW],imm16` after the
PUSH on the same clock in all six cells (s+7/8/10 at pE, s+7/8/9 at pO):
ready 4 clocks after the ModR/M take's sync ends, counting through a fetch.

| Rule chosen | Evidence | Alternative replaced |
| --- | --- | --- |
| a group memory form that reads and does not write (CMP `[BW],imm16`: group opcode, reads memory, no memory write) runs its group's read-modify-write template and `rmw_imm` costs with the write left out but its bus slot kept: the left-out write holds fetches during its setup like a posted write, and on the clock it would issue the bus runs a fetch in its slot whenever the queue has a byte of room; the EU goes on as after a write (`grp_read=rmw_slot_any`) | `F5-push-cmp_m_imm-k1-pO-w0`: R88 F91 F94, PUSH write 103; CMP's PUSH-write clock equals ADD's in 5 of 6 cells and a fetch runs where ADD's write would be | its own `load_alu` template reads at 89 (3107 with the other rules); the slot fetch only when the request rule wants one, 3125 |
| an immediate read-modify-write posts its write as every RMW does (`rmw_write_issue=immediate`, `rmw_imm_issue=rmw`); `rmw_imm` alu 3, setup_free 0 | `F5-push-add_m_imm-k1-pE-w0`: R88 W93 F96 | posted after the ALU step: F91 W94 |
| the posted-request fetch hold compares `hold_q` with the queue bytes ahead of the running instruction, not counting its own operand bytes still queued (`hold_count=ahead`) | `F5-out-add_m_imm-k1-pE-w0`: I/O 84, F87, R91 | counting the whole queue holds the fetch at 87; +20, nothing lost |
| a memory form with both a displacement and an immediate takes the displacement right after the ModR/M byte, syncs, then runs the EA clocks (`imm_head=disp_ea`) | `F5-push-st_imm_bw_d16-k1-pO-w0`: F81 F84 W88 | the split head gives W90; +45 on the pE d16 cells; superseded by the eighteenth fit (`split` with `sync_req=disp`) |
| after an immediate form's address bytes the take sync waits for the fetch in flight, or for the request raised on the take clock only when nothing is in flight (`sync_req=either`) | the same run: W88 | waiting for both gives W91; +9 −4, the 4 lost being the pE 0-wait d16 PUSH cells, so neither alternative is right and this one is chosen on count; superseded by the eighteenth fit's `sync_req=disp` |
| a DW-form I/O does not count a setup clock on which a bus cycle starts, on its start clock or on the clock its request moves into the slot (`dw_count=bus`); its own setup integers `in.setup0` 7, `out.setup0` 8, `out.pre0` 0 | `F5-push-in_al_dw-k1-pO-w0`: I/O 87 (s+6); at pE F81 I88 (s+7); the END's `OUT DW,AL` stays exact everywhere | counting every clock gives I87 at pE; the start clock alone gives I90 after an OUT; +10. IN AL,DW is 24/24; free-standing OUT DW,AL is 0/24 (see finding 3) |

Refuted and removed: the immediate taken after the EA clocks with the
data request posted from the latch (3026, +19 −38, a fetch slips in before
the data cycle); CMP spending the write's setup as EU clocks without the
bus slot (3054 against 3069); a memory form's immediate entering the data
latch (`wlatch_imm=all`, −14); counting only a request raised before the
take (3096, +9 −30); `grp_free` 2 on the immediate forms (−28 to −40); a
DW form counting only once the data latch is free (1020, every 1–2-wait
END lost); a DW OUT behind an OUT counting after that I/O ends (nothing
gained). The stage-5 seed now carries the hand read-off integers
(`rmw_imm` grp 3, grp_free 1, alu 3, setup_free 0; `store_imm` grp 3,
grp_free 1; the DW setups); without them stage 5 does not find these rules.

**HALT status and the queue's read port** (eighth fit, from F10 and F11;
tests in `test_sim.HaltAndLateRead`):

| Rule chosen | Evidence | Alternative replaced |
| --- | --- | --- |
| the clock on which HALT starts belongs to the bus unit, which puts out the halt status; a data or I/O request waiting in the slot does not count that clock toward its setup, as a DW form does not count a clock a bus cycle starts on (`halt_status`); with it `out.setup0` is 7, the same as `in.setup0` | F10: `MOV DW,imm16 ; OUT DW,AL` followed by `MOV CL` issues at s+7 like IN AL,DW; the END's identical pair followed by HALT at s+8, whatever the port or fetch pattern | `out.setup0` 8 without the rule: F10 84/204; with the rule and 7: 174/204, F5 +11, nothing lost. Fires only in the END block. A DW or address-register interlock (start N clocks after the writer, registers tracked for every form) scores 0/4148 at N = 1 and 2 and was removed |
| the decoder does not serve two queue reads on one clock (an instruction's last operand byte and the next opcode into the IR) while a fetch is past its second clock; that take waits for the word's delivery (`late_read`) | F11/F9 marker-less at 1–2 waits: the immediate taken on the delivery clock instead, the take sync waits for the fetch raised there, the shift starts 4 clocks later with no fetch on its start | no rule: F9 382/408, F11 96/132; with it 408/408 and 128/132, F3 +4, nothing lost. Fires in about 1,000 runs (MOV CL 658, MOV r16,imm16 162, loads 150, ADD DW,imm16 47, IN imm 34, stores 14) with no visible change elsewhere; the window length (last 2 clocks or every clock from the third) makes no difference, so no integer |

Refuted on F11: a second-word abort (a fetch issued with a word of room
left, then a committed aborted cycle: fires in the fence fill, −2299); the
take sync extended to a request on the delivery clock (no effect); no
operand take on any fetch's late clocks (+35 −174, the F6 drainers).

**The OUT after a register form, the count byte, and the latched byte's
slot** (ninth fit, from F12; tests in `test_sim.OutAfterRegisterForm`;
gains cumulative in the order applied, each from the config before it):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| the instruction register counts as room for a fetch only when the loader can load it by the word's delivery clock; an IR that cannot take a byte before the word lands is no storage for it (`room_ir_ready`); with it `shift_imm.nx` is 0 | the overfill: `F12-a-out-n3-shl1-pO-w1/w2`, `SHL AW,1` (nx 10 in the eighth fit) starts and takes its ModR/M on the clock the previous word lands, 6 bytes stored with one latched; the empty IR was counted as room, the fetch raised, and its word found 7 | never counting a blocked IR 2068; not counting it on the delivery clock alone 3499. `shift_imm.nx` 0, 1, 2 and 10 score the same 3602 without the rule; the rule makes nx 10 lose 14, so the fitter cannot drift back. No chain overfills |
| a register-only form without an immediate (a ModR/M byte, no memory operand: `MOV AW,DW`) puts its last operand byte into the data latch when taken, as a register form's immediate does: the register result passes the data latch (`wlatch_imm=reg_last`) | `F12-a-out-n2-movr-pE-w0`: ModR/M taken at 92, no fetch at 95, the OUT starts at 96, its port-take fetch 99, I/O 106; the PUSH twin writes at 98 either way | `reg`: fetch 95, I/O 105. +28 −0 → 3630. Reading (b) as a register write-back (`reg.wb` 1): +13 −138 |
| only a form with a ModR/M byte is held off a back-to-back fetch's issue clock; any other instruction may start on it (`start_sync=b2b_modrm`) | `F12-a-out-n1-movr-pE-w1`: F89 F93 F97, the OUT starting at 93, I/O 105; `F3-push-mov_aw_dw-k2-pE-w0`: the second MOV is still held, PUSH writes at 96 | `b2b`: I/O 109. +51 −0 → 3681. `inflight` +51 −24. Holding only instructions whose first step takes a byte on the start clock: identical to b2b_modrm, removed. This closes the `reg.nx` finding (below) |
| the shift form without a count byte (D1) runs its own `exec0`, as `pre0` and `setup0` serve a form with no operand byte; `shift_imm.exec0` 5 against `exec` 6 | `F12-a-out-n2-shl1-pE-w0`: port-take fetch 107, I/O 114; `F3-push-shl1-k2-pO-w0`: F91, write 107 | exec 6 for both: 108/115 and 92/109. +22 −2 → 3701; lost `F12-a-out-n1-shl1-pE-w1` and `F3-push-shl1-k1-pE-w1` (pE w1 k=1, the exec running through a back-to-back fetch). `shift_imm.wb` 1 instead +12 −8; exec 5 on both forms −51 |
| the delivered word's second byte, latched on its delivery clock by a decoder read, is counted that clock while the decoder is mid-take (operand bytes of the running instruction still to come: the IR cannot load, so the byte has no slot but the queue's) (`latch_midtake`) | `F12-b-none-n2-addi-pE-w1`: fetches 72 76 84 88, none at 80; the control `F11-none-n2-movr-pE-w1` (nothing outstanding) still fetches at 80 | the model fetched at 80. +12 −0 → 3713. Other room/latch options on this config: `room_ir` idle 3086, arrival 2095, arrival_ready 2160 |
| a shift with a count byte (C0/C1) takes the count byte `shift_imm.cpre` 2 clocks after the ModR/M byte, a chained take with no sync between (`shift_count=late`) | `F12-b-none-n3-shli-pE-w0`: 72 80 87 107 | count byte with the ModR/M: 85, 105. +18 −0 → 3731. cpre 0 and 1 change nothing, 3 is −11 |
| the take sync after a register form's last immediate byte, when that byte is taken on a word's delivery clock with the word's second byte latched, counts the fetches pending on the clock after: the immediate reaches the data latch a clock later, behind the queue write (`imm_landed`) | `F12-b-push-n0-addi-pE-w1`: F82 F86 F90, the PUSH write at 100 | write at 96. +48 −0 → 3779. Gated on a straddling immediate 3773 (the parity link in F12 B PUSH is incidental); the same deferred sync on every last take (loads, `MOV AW,DW`) −249 |
| a DW OUT does not wait for the long shift's write-back (`out.wbsync0` 0); the port-form OUT still does (`out.wbsync` 1) | `F10-none-none-outdw-pE-w0`: F76 I79 | wbsync 1 for the DW form: F72 I80. +6 −0 → 3785. `out.wbsync` 0 for the port form −1317, and `shift_cl.wb` 0 the identical loss: every port-form OUT after the fence's `SHL AW,CL` (M0, F0w, F1) waits the 2 clocks. Polish then moved `out.nx` 1 → 0, +12 −0 (the F6 `OUT imm8,AL` drains) → 3797 |

Refuted on F12: the read port (an IN/OUT with a port byte does not start
on a delivery clock, +36 −504; only when the previous instruction ended
that clock, +54 −322); a start sync on a fetch requested before the last
take (no effect: the back-to-back fetch is always requested on or after
the last take, by the IR load); a PUSH-marked straddled immediate taken
as two bytes a clock apart (+5 −44), a sync after its first byte
(+26 −37), the deferred sync on the straddle alone (+50 −37, losing the
ADD right after the fence in F9, F11 and F2); operand bytes never taken
on their own delivery clock (no effect).

**Format properties, group forms and the OUT frame** (tenth fit, from
F14; tests in `test_sim.FormatProperties`; gains cumulative in order):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| a ModR/M ALU form whose operation no ALU-op field names (TEST 84/85: neither the opcode's bits 5:3 of the 00–3F block nor a group's reg field) takes the group setup like a group opcode (`grp_ops=fixed`); `load_alu.grp`/`grp_free` 4/3, the group RMW forms' values | `F14-t-push-test_bw_aw-pE-w0`: w78 F81 F84 R89 w100, the read on `NOT`/`INC [BW]`'s clock in all 18 framed cells | plain load_alu (`modrm`): R87 w98, CMP AW,[BW]'s clocks. `nodir` (every ModR/M form without a direction bit, TEST and XCH): refuted, XCH reads on ADD's clock in all 24 cells |
| a form spends its class's `dclk` 2 clocks routing its result: a read-only form whose direction bit names the memory operand as destination (CMP r/m,reg 38/39) after its read, a form that writes both operands (XCH 86/87) before its write, the routed datum entering the data latch after them (`dest_route=d0ro_latch`; superseded by the twenty-second fit's `slot`, which was right once the slot's own rules were in) | `cmp_bw_aw` w100 against 3B's 98; `xch_bw_aw` W94 against ADD's W92 | none; `mismatch` (any form whose direction bit disagrees with its write, which gives TEST the clocks too, F14 −3); `slot` (CMP as the RMW template with the write left out and its bus slot kept, F14 −14). Rules 1 and 2 together +69 on F0–F12 (all 36 TEST and 36 XCH F5 runs less 3) and F14 +123; the latch variant +6 more. Finding 2's opcode-keyed hypotheses are retired |
| a register form whose last operand byte filled the data latch does not wait for the fetches pending on its take while the IR holds an I/O form the busy latch will hold at its start: the bus unit is already reserved for it (`wlatch_ir`); a register MULU's ModR/M does not enter the latch, its result comes from the multiplier (`wlatch_mul=none`) | `F14-o-out-movr-pE-w0`: MOV AW,DW starts on the marker's I/O clock 84, fetches 88 and 91, I/O 98; `F3-out-mulu_dw-k1-pE-w0`: fetches 87 and 124, I/O 131 | waiting: 87, 90, I/O 100; MULU's ModR/M in the latch: 119, 126. +30 on F0–F12 (F3 OUT 12, F7 OUT 12, F12 A 6), F14 +12, nothing lost |
| the memory MULU and DIVU run their own exec and write-back (format variants, as `exec0`): `mul.grp` 4, `mexec` 29, `mwb` 2; a `div` class grp 4/3, pre 0, mexec 37, mwb 2 | MULU [BW] ends 36 clocks after its read cycle, DIVU 44, at every wait and parity | `mexec` 29 alone +9 −9; with `grp` 4 net +9; `mwb` +9 more, nothing lost; DIVU F14 +12 |
| a memory shift by CL (D2/D3 on memory, the count from a register) adds `rmw.grpcl` 3 to the group setup and the whole setup is fetch-free: the count goes from CL to the shift counter before the operand read, on an idle bus (`shift_cl_mem=count`) | `F14-g-push-shl_bw_cl-pE-w0`: R93 W164, the read 4 (pE) / 3 (pO) clocks after `SHL [BW],1`'s at every wait, read to write 71 | plain: R89 W160. F14 +18, every framed `SHL [BW],CL` run |
| a fetch request first raised by the IR load on the clock an I/O cycle issues (the instruction allowed to start on that clock takes no operand byte there: NOP, `XCH AW,DW`; the IR loads its successor) goes no earlier than the next instruction's start; a request raised by an operand take on that clock is not held (`io_ir_hold`) | `F12-a-out-n1-imm-pE-w0`: NOP starts on the marker's I/O clock 84, the IR loads `MOV AW,imm16`, fetches 88 92 99, I/O 106 | without the hold the request waits for MOV's immediate take: 92, 96. +9 (F3 OUT 6, F12 A 3), nothing lost. Subsumes "an OUT start re-evaluates the request" (+15 alone, removed), and closes the finding-9 conflict with `request_eval=on_change` |

Refuted on F14: holding a fetch raised on the I/O issue clock until the
next start for every request, or exempting the take sync from it
(+35 −33, +26 −20); holding a group ModR/M byte's queue slot until MULU
ends (−36; for every group form it breaks the fence); counting a latched
byte on any clock with an operand take (for `NOP ; SHL AW,4`: breaks
every guard); a separate group integer for TEST imm (7 of 36); TEST imm
reading load_alu's group integers (nothing); `POP [BW]` grp/grp_free/exec
scans (none closes it).

**Stack first, lookups in series, the I/O issue clock** (eleventh fit,
from F15; tests in `test_sim.StackFirstAndLookups`; gains cumulative in
order):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| POP r/m reads the stack first, posted at its start with POP AW's setup (`pop_mem` rsetup 7, the last rfree 3 fetch-free: its address is SP and needs nothing from the ModR/M), then takes the ModR/M and displacement (`pre` 2 clocks after the stack data), and the memory write is posted when the data arrives (`setup` 4, holding fetches) carrying the group clocks (`grp` 0: the reg field is decoded after the read) (`pop_mem_order=stack_post`) | the stack read on POP AW's clock in every mode, the write 8 after it plus the read's waits | `modrm_first` (the old order); `stack_first` +7 −50; `stack_lead` +23. +85 (F5 13, F14 G 8, F15 P 64), `pre` 2 +12 more |
| PUSH r/m's stack write is posted on its read data's arrival, holding fetches from then (`push_mem_write=at_data`) | `F15-p-out-push_bw-pO-w0`: I/O 85, R93 w102 F106 | `after_exec`: R93 F96 w102 F114. +22 (F5 9, F14 G 6, F15 P 7) |
| a group form whose operation no ALU-op field names (F6/F7 /0, TEST r/m,imm) runs TEST 84/85's setup and then `load_alu` fgrp/fgrp_free 2/2 more: the fixed operation's lookup and the group decode in series (`grp_fixed=test`) | `F15-a-push-test_bw_imm-pE-w0`: F81 F84 R91 F96; TEST [BW],AW R89, CMP and AND [BW],imm16 R88 | its group's setup alone (`one`, CMP 81 /7's clocks); the group setup plus fgrp (`both`) +16. +26 (F14 T 13, F15 A 13) |
| TEST 84/85 with a displacement: the lookup holds the decoder for `load_alu.fdisp` 5 clocks between the ModR/M and the displacement bytes, not counted during a memory cycle's wait states, replacing the group setup (`fixed_lookup=decoder_nowait`) | `F15-a-push-test_dir_aw-pO-w0`: F81 F87 R90; AND and CMP direct F81 F84 R87 | as setup: F81 F84 R90; `decoder` counting wait states +15 with fdisp moving with waits (5 at w1, 6 at w2). +21 (F14 T 12, F15 A 9); the tenth fit's `load_alu.grp`/`grp_free` knob dependence is gone |
| a group memory form with a one-byte immediate (83 /x) takes its own `rmw_imm.grp1` 2 clocks: the immediate's width is a format property of the group decode, as the count byte is of the shift (`imm8_grp=own`) | `F15-a-push-and_bw_imm8-pO-w0`: F81 R87 W92 F95; the 81 form R88 W94 | `same`: R88 W93 F96. +16 (F15 A) |
| a register-only instruction or prefix after an OUT starts on the I/O's issue clock (when the OUT's data passes the ALU) or after the cycle's last clock, not during it: the ALU's path to the bus unit is the I/O's while the cycle runs (`io_busy_start=issue`) | `F3-out-pfx_mov_aw_imm-k1-pE-w0`: I/O 84–86, the prefix at 84, MOV at 87, F87 F91 F98 I105 | `any`: MOV at 86, F87 F90 F97 I104. +20 −0, every F3 OUT prefix row |
| the take sync does not count a fetch request raised on the take clock while an I/O cycle issues on it, for a take whose byte entered the data latch: the bus unit has given that clock to the I/O (`sync_io=latch`), with `reg.nx` 2; subsumes `wlatch_ir` | `F15-o-out-movr_ld-pE-w0`: I/O 84, MOV takes its ModR/M at 84, F87 F90, the load reads at 93 | `none`: R95; `issue` (every take) +48 −25; `busy` +12 −35. +74 −10: lost `F3-out-mov_aw_dw-k2-pE-w1/w2`, `F3-out-add_aw_dw-k2-pE-w1/w2`, `F7-out-mov_aw_dw-mov_aw_dw-pE-w1/w2`, `F14-o-out-movr2-pE-w1/w2`, `F15-o-out-movr2-pE-w1/w2`, where silicon's second MOV waits for a back-to-back fetch |

Polish: `rmw.setup_free` 3 (+3, found by the pipeline). Refuted on F15:
counting the whole queue in POP r/m's stack-read hold (`pop_read_hold=queue`,
+7 −6, kept as an option); no hold at all (−66 +28) or none in the last
setup clocks (−56 to −83); an aborted fetch not retried after a read
(−33); the take sync waiting for a back-to-back fetch (−80); holding a
latch-waiting I/O off the back-to-back clock (inert); a shift or MULU
unable to start on the I/O clock (−20); a 2-clock aborted cycle (+62
−251); `mul`/`push_mem` nx 1–30 and grp 3 (losses only); `reg.nx` 3
(−288). Each adopted enum flipped back alone loses runs and gains none.

**The operation unit, the shift's port, the fetch run and the I/O clock**
(twelfth fit, from F16; tests in `test_sim.UnitFormsAndFetchRuns`; losses
are each rule's own flip back on the final configuration):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| a memory form whose operation runs after the read in a unit other than the ALU (the shift unit: every D0–D3 operation; the multiplier and divider: F6/F7 /4–/7; the stack write of PUSH r/m, FF /6), started on an aborted fetch cycle, posts its first data request with one group setup clock already counted (the clock the take sync spent on the aborted cycle), unless every setup clock must be fetch-free (`SHL [BW],CL`); a memory multiply or divide still ends where it would have and raises the dropped request `mtail` 3 clocks before its end; a register shift started that way raises it as its last count iteration starts, `per_shift_count` before its end (`abort_unit=loop`) | `F16-r-push-rol-inc_x-pE-w0`: INC W94, ROL starts on the aborted cycle at 97, R104 W115 F118 (none: R105 W116 F119); `not-inc_x`: R105 W110 either way; `mulu-inc_x`: R104, F134, the PUSH write 143 (early: F108); `F16-s-none-cl4-n1-shlcl-pE-w0`: F100 F106 (early: F105). The ladder: D1 /0–/3 behave as /4–/7, the byte forms as the word forms, NOT/NEG/INC/DEC on their clock; the class, not a bit of the reg field | `none` −187; `early` (the read early, the end moving with it) −84; `all` (every group form, the refuted control) +15 −145. F15 K 120/120, F16 R 288/294 |
| a C0/C1 shift that takes an operand byte on a word's delivery clock with the word's second byte latched, while the queue has no room for a word but that uncounted byte, holds the queue's port for its run: no fetch until its last clock, when the request is evaluated again; a count byte taken that way reaches the counter a clock late (`count_latch`) | `F16-s-none-n1-shli4-pE-w1`: the count byte taken at 80 on the delivery, 5 bytes stored and 1 latched: F72 F76, nothing during the shift, F99 F103 (False: F80 F103); `n2-shli4`: the ModR/M taken so at 80, the count at 83: F72 F76 F97 F104 (False: F83); `n1-shlcl4` (the count in CL) fetches during the shift, F79 F83 F107 | any take. −57 (F16 S 40, F12 B 6, F15 O 9, F14 O 2); a first version counting the latched byte on the count's take alone +31, missing the ModR/M case. F12 B marker-less 48/48 |
| a posted memory request (not I/O) already counting its fetch-free setup clocks does not hold a fetch first requested on this clock, the delivery clock of the fetch that just ended: that fetch runs and the request's remaining clocks count through it (`free_run=run`) | `F16-p-push-n0-pop_bw-pE-w1`: POP [BW] starts at 82 with a fetch, its stack read posted then (setup 7, 86–88 fetch-free); the fetch's word lands at 86 and the ModR/M take's room raises a request: F82 F86 r90 (none: F82 r88 F101); at 0 waits the request comes at 84, before the free clocks, and is held (F81 r87, exact either way); `n1-pop_bw` = `n1-pop_aw` in every cell | `none` −62; `pop` (POP's stack read only) −14; `any` (a request on any clock) −85; `held` (an older request too) −2914. Fixes 10 F5 and 4 F7 runs besides F16 P |
| a register-only form that starts on an I/O cycle's issue clock runs the clocks after its last operand byte only once the cycle has ended (`io_exec=after_io`) | `F16-l-out-shl1-pE-w0`: the marker's I/O 84–86, SHL AW,1 takes its ModR/M at 84, its exec from 87: F87 F99 I106 (any: F97 I104) | `any` −8; `all` (every clock after the first take: the count byte's and the immediates' pre clocks too) −64 |

New integers: `mul.smexec` 49 and `div.smexec` 58 (the signed F7 /5 and /7
forms, 20 and 21 clocks more than the unsigned at one datum each),
`mul.bmexec` 21 (the F6 /4 byte form, 8 fewer), `div.exec` 39 (the register
divide, 8 more than `MULU AW`), `mul.mtail` and `div.mtail` 3 (sharp: 1, 2,
4 and 5 gain nothing). The decode now carries the D0/F6 byte groups and a
signed property for F6/F7 /5 and /7. Refuted on F16: holding the count
byte's fetch until the next start (the fetch right, the exec a clock off);
an aborted cycle for that fetch (+1 off); exempting the count byte from
`late_read` (−2 off); re-raising every aborted request at the next start
(breaks almost every family); a register MULU with no take sync
(`mul_take=lead`, −43); holding the take on a delivery issue clock until the
next start (the pO fetch lands right but the form's end stays wrong, nothing
gained); counting the latched byte in the triple-read abort test (breaks the
fence). Each adopted enum flipped back alone loses runs and gains none.

**The dropped request, the hold on the unit's exec, the slot behind an
I/O** (thirteenth fit, from the recorded OUT frames; tests in
`test_sim.OutFrameOdd`; losses are each rule's own flip back on the
final configuration, and none gains anything flipped):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| the register divide (class `div` with no memory operand) is a register-only class like the register multiply: it does not start while a waiting OUT's I/O is posted, only on its issue clock, runs its exec after an I/O cycle it started on, and its ModR/M is treated as the multiply's (`reg_div`) | `F16-l-out-divu_ix-pE-w0`: the marker's I/O 84, DIVU IX starts there, F87, the closing OUT F132 I139; MULU AW's F124 I131 plus 8, as in the PUSH twin (w130 against w122) | outside the classes DIVU started on the marker's port take: F126 I133. −6 |
| a fetch request raised on the clock an I/O cycle issues, by the take of a register form's last operand byte on a word's delivery clock with the second byte latched, is dropped as an aborted cycle's request is and raised again at the unit's loop exit (`abort_unit=loop`: a shift as its last count iteration starts, a multiply or divide `mtail` 2 clocks before the end its exec would have from its first clock); a request first raised on such a clock by the delivery itself while a memory multiply or divide runs is dropped the same way (`io_take=unit`) | `F16-l-out-shlcl4-pO-w0`: I/O 90, SHL AW,CL takes its ModR/M on fetch 87's delivery: F108 (the last iteration's start) F120 I123 (none: F93 F121 I124); `F14-g-out-mulu_bw-pO-w0`: I/O 85 on fetch 82's delivery while MULU [BW] waits for its read: R93 F123 F135 I138 (drop: F96). The C1 shift's ModR/M take there is chained (the count byte to come), raises no request, and is exact as before | `none` −81; `drop` (the take's request only) −18; `abort` (an aborted cycle on the first free clock for MULU's) −30 |
| a count loop of one iteration raises the re-raised request on its first clock, as a longer loop's last iteration does (`retry_first`; the retry clock set as the loop step began was checked only at the start of a clock) | `F16-l-out-shl1-pO-w0`: SHL AW,1 on the I/O clock 85, its loop 93–94: F93 F105 I108 (False: F94); `F16-s-none-cl1-n1-shlcl-pE-w0`: F75 F78 F94 F100 (False: F95 F101) | −53 |
| a register shift, multiply or divide in its exec clocks waits at a micro-boundary while a fetch is past its second clock, until the clock after the fetch's last, as the count loop waits for a refresh cycle: the boundaries are every second exec clock from the class's `hphase`-th (1 for the D0/D1/C0/C1 shifts, 2 for the shift by CL, the multiply and the divide; only its parity matters), so a fetch starting on the exec's first clock costs the D1/C1 shifts its wait states and the others its wait states + 1; the memory forms' mexec is not held (`unit_hold`) | `F16-l-out-shli4-pE-w1`: SHL AW,4 on the I/O 85, exec from 92 with the back-to-back fetch 92–95: F117 I121 (False: F116 I120); `F16-l-push-mulu_aw-pE-w1`: the back-to-back fetch 86–89 runs into the exec: w125 (False: w123); F14 G and F16 R `mulu_bw`/`divu_bw` at pE with a fetch on the mexec's first clock: exact either way | −127; the twelfth fit's `div.exec` knob dependence at pE is gone |
| the register multiply's and divide's take on the I/O issue clock does not count the request raised under the I/O (their ModR/M does not enter the data latch): their exec runs from the I/O's end and the fetch starting there holds it (`sync_io=unit`, extending `latch`) | `F16-l-out-mulu_aw_nop-pE-w0`: MULU AW on the I/O 84, fetch 87–89, the NOP at 119: F87 F119 F131 I134 (latch: F121 F133 I136) | `latch` −27 |
| the register multiply and divide write back for `wb` 2 clocks past their end as the shifts do; a NOP or a second MULU starts at the end, the port-form OUT waits for the write-back (`out.wbsync` 1) | `F16-l-out-mulu_aw-pE-w0`: the OUT at 121, F124 I131; `F3-out-mulu_dw-k2-pE`: the second MULU's fetch F119/F121/F123 at w0/w1/w2 | `mul.wb`/`div.wb` 0 −53; what the pipeline's `mul.pre 1 / exec 29 / wb 2` basin was reading |
| a register D0/D1/C0/C1 shift, multiply or divide started on an aborted fetch cycle runs its exec from the cycle's last clock, one clock early, as the memory unit forms count a setup clock during it; the multiply and divide keep their end and raise the dropped request `mtail` before the end the exec would have had; not the shift by CL (`abort_reg`; the kept end is superseded by the twenty-fourth fit's `abort_reg_end=early`: it was never observable in these runs) | `F3-push-mulu_dw-k2-pE-w0`: the second MULU on the aborted cycle 116–118: F147 w156 (False: F150); `F3-push-shl1-k2-pE-w0`: F98 w107 (False: F99 w108) | −36; with the shift by CL included −192 (the closing LS's SHL AW,CL started on an aborted cycle, F9, F11, F12 B, F16 S) |
| a posted memory request that waited behind an I/O and moved into the bus unit's slot when the I/O issued, still with fetch-free setup clocks to count (not a group setup), holds a fetch requested before it moved in until those clocks start, then lets it run there and counts its remaining setup through it (`slot_fetch=slot`, the `free_run=run` shape) | `F15-p-out-pop_bw-pE-w0`: POP [BW] starts at 80, its ModR/M lead take raises a request held by the marker's posted I/O; the stack read moves into the slot at 84: F88 r91 W99 (none: F87 r92 W100); a load (setup 0) or a group form (free clocks on an idle bus) behind the same I/O keeps the fetch right after it, F87 | −42 (F5 9, F14 G 6, F15 P 24, F16 P 3) |
| POP r/m's displacement is taken so that its last byte lands where a two-byte displacement's last byte does, `pre` + 1 clocks after the stack data (a one-byte displacement waits a clock more), and the memory write's setup counts through the fetch that take raises (`disp_take=end`, `pop_mem.setup_free` 1) | `F15-p-out-pop_bw_d8-pO-w0`: r91, the displacement at 97, F97 W100 F107 I114 (start: F96 W99); `F16-p-push-n1-pop_dir-pO-w0`: r91, bytes at 96 and 97, F97 W100 in both | `start` −11 (F15 P 6, F16 P 5); `pop_mem.pre` 3 for every displacement +11 −32 |

`mtail` is now counted from the end the exec would have had from its
operand (2, the same clock as the twelfth fit's 3 counted from the moved
end; 3 there loses 103). Refuted on this corpus: the take sync extended to
a back-to-back fetch committed at the synced fetch's last clock, for every
take (+14 −93) or a memory form's (+4 −13), or to a fetch requested on the
synced fetch's delivery clock when the take was on its B1 (+36 −835), and
the `imm_landed` deferral for every memory form's last take (+36 −486):
each gains the 18 F6 `n1` drains and the ten `MOV AW,DW` pairs, but no
state separates them from F4's PUSH-frame loads; the fetch a
latch-waiting I/O form held going first when the latch frees
(`latch_fetch`, +2 −177); the store's immediate entering the data latch
(`wlatch_imm=all`, +10 −171); no fetch on the clock after an I/O while a
memory request waits in the slot (−480); every request moved in behind an
I/O counting its setup through fetches (−83); `pop_mem.setup` 3 (−331),
`pop_read_hold=queue` (−34), `hold_count=queue` (−74). The abandoned
prototypes were removed from the code. Each adopted enum flipped back
alone loses runs and gains none.

**The immediate's count floor and the DW form behind an I/O** (sixteenth
fit, F19; tests in `test_sim.ImmediateAndDwForms`; losses are each rule's
own flip back on the final configuration, and none gains anything
flipped):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| a memory form with an immediate (`store_imm`, `rmw_imm`) issues its first data request no earlier than `istart` 5 clocks plus one per immediate byte after its start, every clock counted, wait states included, the displacement bytes free; where the template's own path (the ModR/M take's sync on a fetch in flight, the group setup) ends later, that clock stands (`imm_count=start`) | `F19-i-push-n1-stimm-pO-w0` W92 = s + 7 with no fetch in the head, as `-pE-w0` W92 with one; `F19-i-none-l0-stimm-pO-w0` W79; `F19-i-push-n1-stimm8-pO-w0` W91; `F19-i-push-n2-stimm-pO-w1` W97 = s + 7 (−138 flipped back: F19 I 133, F5 `cmp_m_imm` k = 2 5; the count skipping wait states −122; `istart` 4 −66, 6 −240) | the template and setup alone, 2 clocks early (3 for C6) wherever no fetch runs in the head |
| `MOV byte [BW],imm8` (C6 /0) takes the one-byte-immediate group setup `store_imm.grp1` 2, as 83 /x does in `rmw_imm` (`imm8_grp=own`, eleventh fit) | `F19-i-push-l0-stimm8-pO-w1` W89 (0: W88; −40, all F19 I) | no group setup for C6 |
| a DW-form I/O (its port from DW, not the shared port latch) queued behind an I/O waiting in the bus unit's slot neither delays it nor relatches it: it counts its setup from the clock the I/O ahead issues, and a port-form IN/OUT behind it does not start while the DW request waits behind another I/O or the cycle ahead of it is on the bus, so its port take relatches only the DW request (`dw_port=hold`) | `F19-d-out-none-outb-pO-w0` M0 I85, the DW I/O 94 = the closing OUT's port take + 3 (latch: the take at 85 holds M0 to 88, the DW to 96); `F19-d-out-pair-outb-pE-w0` I84 F89 I92 I101 (−30: F19 D OUT 20, `F5-out-out_dw_al` 10) | the port take relatching every waiting I/O (`port_latch`) |
| a DW request that moved into the slot when the I/O ahead issued lets the fetch requested before it run on its lead's first clock only when nothing is posted behind it or the queue holds `hold_q` 3 bytes or fewer (`dw_slot=behind`) | `F19-d-push-pair-outb-pO-w0` I88 I95, 4 bytes queued and the PUSH write posted behind (bus: F93 I96); its twin `-pE-w0` I88 F93 I96 with 3 queued; `F19-d-none-outimm-outb-pE-w0` I84 F89 I92 with nothing behind (−21: F19 D 15, `F5-{out,push}-out_dw_al-k2-pO` 6; counting the move-in clock −66, the IR's operand bytes excluded −9) | the fetch runs (`io_hold`) |

Refuted on F19: `imm_head=split` (−63; with the displacement chained
+14 −29, removed; adopted by the eighteenth fit with `sync_req=disp`,
so the refutation was of the pair), `sync_req=take` (+8 −242), `sync_io=none` for the 8B
forms on the I/O issue clock (+10 −92; `issue` no change),
`grp_read=rmw_slot` for CMP imm8 (+5 −90). `rmw_imm.istart` 5 is the one
knob-dependent integer: F16's `TEST [BW],imm16` second instance prefers
7 (994 against 988), the F7 /0 forms running under `rmw_imm` wanting
their read's floor at s + 9 (finding 5).

**The request after a fetch's issue, the ModR/M's word-mate, the start on
a back-to-back fetch** (seventeenth fit, F20; tests in
`test_sim.RegisterFormBeforeDw`; losses are each rule's own flip back on
the final configuration over all 14,246 runs, and none gains anything
flipped):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| on a clock the fetch request is evaluated (a take committed, the IR loaded, a word landed) and a fetch issues, it is evaluated again after the issue with the in-flight word's two slots reserved, so a queue with room for another word keeps it raised and the bus unit runs that fetch back to back; not while a memory data request waits in the bus unit's slot (`request_reissue=no_mem`) | `F6-out-ld_bw-n1-pE-w0`: `MOV AW,imm16` takes its last byte and the IR loads the load on fetch 88's issue clock; F88 F91 F94 R99, the load held off the back-to-back fetch (none: R97); `F1-store-m1-pE-w0` F75 W78 F81 (always: F75 F78 W81, −41 on every direct-address form). −360: F20 260, F19 48, F6 42, F3 10; the F6 `n1` drains 18/18 | `request_eval=on_change` alone: the issue clears the flag until the next queue change |
| on a delivery clock where the decoder takes the second byte of the word whose first byte was the running instruction's ModR/M, with operand bytes still to come, the word's slot still counts when that byte is a register form's immediate; a displacement's byte frees it (`modrm_mate=imm`) | `F19-d-push-adddwi-outb-pE-w0`: `ADD DW,imm16` at an odd address started on fetch 81's issue clock takes the immediate's first byte on fetch 81's delivery clock 84; w78 F81 F85 F88 I95, no fetch at 84 (False: F84 F87 I96); `F4-push-ld_bw_d16-k1-pE-w0` (8B 87 d16) F81 F84 F87 R90 (any: F85, −4). −32: F20 11, F19 8, F6 6, F3 3, F10 2, F12 B 2 | the slot free on the take clock for any byte |
| a form without a ModR/M byte does not start on a back-to-back fetch's issue clock while the queue stores fewer than `io_b2b_q` 3 bytes (the delivered word's latched second byte not counted): it waits that fetch out; checked after the data-latch wait, so a latch-waiting OUT still holds the fetch (`io_b2b=all`) | `F7-out-mov_aw_dw-mov_aw_dw-pE-w1`: the closing OUT due on fetch 92's issue clock with 2 stored; F88 F92 F96 I107 (False: I104); `F19-d-out-adddwi-inb-pE-w0` F88 F91 F94 i101 (False: i98); `F19-d-out-adddwi_nop-inb-pE-w1` i107 (`io`, IN/OUT only: i105, −12); `F3-out-mov_aw_imm-k1-pE-w1` with 3 stored starts on the back-to-back clock, F89 F93 F97 I105. Over the corpus 32 of 32 such starts at 2 stored were misses and 248 of 248 at 3 exact. −45; `io_b2b_q` 2 −45, 4 −6435 | the start on the issue clock (`start_sync=b2b_modrm` for ModR/M forms only) |
| a DW-form I/O posted at its own start does not count a setup clock on which a back-to-back fetch starts (`dw_count_b2b`) | `F19-d-out-movawdw-inb-pE-w0` F87 F90 i95 (False: i94); `F20-r-out-l0-movawdw-outdw-pE-w1` F88 F92 I100. −12 F19 | `dw_count=bus` on the start and move-in clocks only |
| a port byte taken on a word's delivery clock with the second byte latched reaches the port latch a clock later, behind the queue write, as an immediate does (`imm_landed`), so its hold on a waiting I/O runs a clock longer (`port_landed`) | `F19-d-out-movawdw-outb-pE-w0`: the closing OUT's port byte taken at 93 on fetch 90's delivery; F87 F90 I97 (False: I96). −18: F19 12, F20 6 | the port take at its clock |

Refuted on F20 (against intermediate configurations where noted): the IR
not counted as room on a mid-take delivery clock (−1247), deferring the
ModR/M commit in 81 forms (+13 −159; at even addresses +24 −105),
word-granular release (`release=last`, −6564), `ea.base_index_disp` 3
(+1 −17), a hold keyed to a ModR/M taken on the I/O issue clock (+37
−59), the shallow-queue hold counting bytes beyond the operands (+29
−185), the DW count skipping any fetch start (−6 refresh runs). The
immediate's and the port byte's late landing and the ModR/M's immediate
word-mate are three sightings of one path: an operand byte for the data
or port latch lands a clock behind the queue write, a displacement does
not (finding 9's open reading).

**The displacement's take, the EA classes, the immediate form's head**
(eighteenth fit, F21; tests in `test_sim.DisplacementForms`; losses are
each rule's own flip back on the final configuration over all 17,822
runs; the two gains on a flip back are the one F17 refresh-on run of
item 8 h):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| a two-byte displacement (mod 10, and the direct address's two bytes behind a ModR/M byte) is taken in one clock when both bytes are queued; a byte not yet delivered is taken when it lands, so a d16 costs what a d8 does (`disp16=word`) | `F21-none-n1-ld-bw_d16-pO-w0` F76 F79 R82 (byte: F80 R83); `F21-none-l0-ld-bw_d16-pO-w0` F75 R78 = `-bw_d8-`; base+d16 = base+d8 through the first data cycle in 154 of 172 single-instance cells at 0 waits, the other 18 the straddle (`F21-push-l0-ld-bw_d16-pE-w0` F81 F84 F87 R90, the second byte in the word fetched at 84). −1041: F21 544, F17 314, F18 74, F19 58, F4 19, F5 13, F14 9, F15 6, F10 4 | a byte a clock, as every operand byte |
| base+index with a two-byte displacement runs its own EA integer, `ea.base_index_disp16` 3 against 2 for every other ModR/M class; in `POP r/m` the extra clock runs before the displacement's take (`ea_disp16=own`) | `F21-push-l0-ld-bw_ix_d16-pO-w0` F85 R88 (same: F84 R87); every event from the first after the displacement on is one clock later than base+d16's in 132 of 160 cells at 0 waits, never equal, for every consumer; base+index+d8 = base+d8 in 480 of 480 cells, base+index = base in 420 of 420. −202: F21 198, F4 4; the integer at 2 +17 −131, at 4 −219 | one EA integer for every mode class but direct |
| a direct address behind a ModR/M byte (mod 00 rm 110) runs `ea.base_disp`: it is a two-byte displacement with no register; A1/A3, with no ModR/M byte, keep `ea.direct` 0 (`ea_direct=base_disp`) | `F21-none-es-ld-dir-pE-w0` F82 R85 (own: F81 R84); [0C00h] = [BW+200h] in 480 of 480 cells for all five consumers. −125 +1; `ea.direct` 2 under `own` +74 −78, A1 and A3 losing | EA 0 for every direct address |
| a memory form with both a displacement and an immediate runs the split head as every other memory form does: the ModR/M byte, the EA clocks, then the displacement (`imm_head=split`) | `F21-none-l0-sti-bw_d8-pO-w0` F75 W79 (disp_ea: F73); the first fetch after the start at s + 3 at every alignment for every consumer, so F19's odd-aligned d8/d16 head is this rule. −187 +1 | the displacement taken right after the ModR/M byte, then the sync, then the EA clocks (seventh fit) |
| no take sync after an immediate form's displacement, the write's group setup counting through the fetch the take frees; a displacement due on a fetch's clock past its second waits for that word's delivery, as `late_read`'s take does; the mod 00 forms keep `either` (`sync_req=disp`) | `F21-none-n1-sti-bw_d8-pE-w1` F76 W84, the d8 due at 79 on fetch 76's last clock (either: W83); `F21-none-l0-sti-bw_d8-pO-w0` F75 W79, the freed fetch running and the write still at s + 7. −408; `none` (the mod 00 forms too) +140 −324 | the sync for the fetch in flight or the request raised (seventh fit) |
| the immediate store spends one EU clock after its displacement's take where a load, a store and an RMW spend none (`store_imm.dadd` 1); at 0 waits the s + 7 count floor hides it for d8 and d16 (take at s + 3), not for base+index+d16 (take s + 4, write s + 8) | `F21-none-l0-sti-bw_ix_d16-pE-w0` F72 F76 W80; `F21-none-n1-sti-bw_d8-pE-w1` W84 (0: W83). −65; `dadd` 1 on any other class loses (load −646, store −296, rmw −305, load_alu −18; rmw_imm unchanged) | no clock after the displacement |
| refits under the new head: `load_alu.fdisp` 5 → 4, `pop_mem.setup_free` 1 → 0 | `F15-a-push-test_dir_aw-pO-w0` F87 (5: F88), −15; `F21-none-l0-pop-bw_d16-pO-w0` W87 (1: F87 W90), −69 | the tenth and thirteenth fits' values |

Refuted on F21 (on the final configuration unless noted): two other
releases of the d16's second byte (`word_late`, the slot freed a clock
later, +0 −197; `word_hold`, held until the data cycle issues, +36
−819; both removed from the code); no IR load on a two-byte take clock
(−125); every EA integer ±1 (`ea.base_disp` 1 −291, 3 −519;
`ea.base_index_disp16` as above; `ea.direct` 2 as above); `ea.base` 1,
which gains exactly the 15 F14 T and F15 A TEST/CMP k = 2 runs and
breaks the corpus; `sync_req=none` (+140 −324); the immediate forms'
integers (`store_imm` setup 1/3 −237/−1059, grp 4 +65 −181, grp 2
−112, grp_free 0/2 −76/−724, istart 4/6 −232/−460; `rmw_imm.grp` 2/4
−132/−200); and a single flip of every queue and I/O enum (`room_ir`,
`latch_midtake`, `modrm_mate`, `request_reissue`, `io_ir_hold`,
`sync_io`, `start_sync`, `io_take`), none gaining without large losses.

**The next opcode held through a displaced form's address, the late take
as the decoder's, the floor from the take** (nineteenth fit, F21 re-read;
tests in `test_sim.DisplacementTake`; losses are each rule's own flip
back on the final configuration over all 17,822 runs; nothing gains on a
flip back):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| a ModR/M memory form with a displacement keeps its successor's opcode in the queue until its first data cycle issues: no IR load and no seventh slot for the request rule in between, unless the displacement was taken on a word's delivery clock (`ir_load=disp_data`) | `F21-none-l0-ld-bw_d16-pO-w0`: the d16 taken at 75 with 5 bytes queued and no fetch in flight; silicon F75 R78 F81 F87 (take: the IR loads at 75, the request stays raised through fetch 75 and its back-to-back fetch beats the read, F75 F78 R81 F89); the control `F21-push-l0-ld-bw_d16-pE-w0`, the d16 taken on fetch 81's delivery clock 84 with the same bytes left, F81 F84 F87 R90, the back-to-back fetch first (held there too: R87 F90, −638). d16 at 5 bytes with no fetch in flight 0/77 before, d8 at 6 bytes 0/16 and 0/48 per wait; 3–4 bytes with a fetch in flight 98/98 and d16 at 6 bytes 14/14 exact before and after. −310 | the IR loads nx clocks after the last operand take (`ir_load=take`) |
| the late take (a displacement due on a fetch's clock past its second is taken on that word's delivery) is the decoder's rule for every displacement, not the immediate form's (`late_disp=all`); alone it changes nothing, `late_read` covering the loads, and with the IR held it is needed | `F21-none-n1-ld-bw_d8-pO-w1`: the d8 due on fetch 76's last clock 79, taken on its delivery 80; F76 F80 R84 (imm: F76 R81 F85). −605 | the late take in immediate forms only (eighteenth fit) |
| a memory form's first data cycle issues no earlier than `dfloor` 2 clocks after its displacement's take (an address adder's latency); a fetch issued on the take clock hides it (`disp_floor=take`) | `F21-none-es-ld-bw_d8-pE-w1`: no fetch at the d8's take 83, R85 (none: R84); the data cycle 2 after the take at every wait and for the late take too (`F21-none-es-ld-bw_d8-pO-w2` F+0 R+7, the take at s + 5). −271; `dfloor` 1 or 3 lose the same 271; 2 for every memory class, pinned by load, store and rmw, the other five classes tying at 0 and 2 | the template's path alone |
| the delivered word's latched second byte counts on the clock the decoder takes a memory form's displacement, as it does mid-take (`latch_disp`) | `F21-none-n1-ld-bw_d8-pE-w1`: the d8 taken on fetch 76's delivery clock 80 with 5 stored after it, one latched; no fetch, F72 F76 R82 F91 (False: F80 R84); `F21-none-n1-ld-bw_d8-pO-w1` with 4 stored fetches there, F76 F80 R84. −159 | the latched byte counted mid-take only (`latch_midtake`) |

Refuted on the F21 re-read (all removed from the code): the IR held
until the data cycle for every ModR/M memory form, the mod 00 forms
included (+437 −2069); held on a delivery-clock take as well (+436
−638); only the room counted, the IR still loading (+242 −0, against
+469 for the full rule); the held IR as no room from the address take
for the immediate store too (+29 −16: the 1–2-wait stores fetch on the
delivery clock); the held IR as no room from the clock after the start
(+70 −66; scoped to forms with no immediate and not POP r/m +15 −6,
TEST [dir] lost); for item 10 c, the latched byte uncounted while it
waits in the latch (`latch_wait`, +0 −274) and an aborted cycle at one
byte of room with a latched byte (no change: the take sync does not
count it).

**The fetch held at a request's free clocks' eve, the older fetch an I/O
or ModR/M form waits out, the floor from the address step** (twentieth
fit, F21/F19/F5/F20 re-read; tests in `test_sim.FreeClocksAndFloors`;
losses are each rule's own flip back on the final configuration over
all 17,822 runs; nothing gains on a flip back):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| on the clock before a posted memory request's first fetch-free setup clock, a fetch first requested on that clock (the delivery clock of the fetch that just ended) is held, whatever the queue holds, unless that fetch itself started on the clock after an earlier fetch's last (a fetch run) or the bus unit committed to it back to back; the held fetch dates from the next clock, where it runs with the request's fetch-free clocks counting through it or beats a request just become issuable (`free_hold=delivery`) | `F21-none-l0-sti-bw_d16-pO-w0`: the write at count 2 of 3 when fetch 75 delivers at 78, silicon F75 W79 F82 (none: F75 F78 W81); `F19-i-push-n1-stimm-pO-w0`: PUSH at count 4 of 7 on fetch 95's delivery, F95 F99 w102 (none: F95 F98 w103); `F21-push-l0-pop-bw_d8-pE-w0`: POP's stack read at count 4 of 7 on fetch 81's delivery 84, F81 r87 F93 W96 (none: F81 F84 r89 W97); `F21-out-l0-sti-bw_d16-pE-w0`: held at 90, F91 beats the write issuable there, W94. 110 cells held in silicon, 23 run cells fetching, none against; the 1-wait twin `F21-none-l0-sti-bw_d16-pO-w1` is at its last setup count on the delivery clock and goes first, F75 F79 W83. −106 | the hold by the queue count alone (`hold_count=ahead`, kept for the clocks inside the setup) |
| when the hold lets a run's delivery-clock fetch go at the free clocks' eve, one idle clock follows it before the request issues (`free_idle`) | `F21-push-l0-sti-bw_d16-pE-w0`: fetches 81, 84 (the d16 taken on fetch 81's delivery), 87 on fetch 84's delivery with the write at count 2 of 3; silicon F87 W91 (False: W90); not a run, `F21-none-l0-sti-bw_d16-pO-w1` F75 F79 W83, the write right after the fetch. −29 | the request issues on the clock after the fetch |
| an IN or OUT with a port byte, or a form with a ModR/M byte, due to start on the clock a fetch requested on an earlier clock issues, waits that fetch out while the queue stores fewer than `io_b2b_q` 3 bytes, as `io_b2b` makes it wait out a back-to-back fetch; a register form starts beside it (`io_older=io_modrm`) | `F19-i-out-l0-stimm-pO-w0`: the store writes at 92, the data latch busy to 95 holding fetch 96, the OUT due at 96 beside it with 2 stored; silicon F96 F99 F102 I109 (False: I106); the twin `-pE-w0` with 3 stored starts beside fetch 95, F95 F98 I105; `F21-out-l0-sti-bw_d16-k2-pO-w0`, the second store due beside fetch 104 with 2 stored, W108 (`io`: W107). 14 of 14 OUT starts at 2 stored, 400 of 400 at 3–4; MOV r,imm and PUSH at 2 stored start beside such a fetch, 100 of 100. −53 (`io` alone −4) | the start beside an older fetch for every form |
| a ModR/M memory form without a displacement (mod 00, base or base+index) is floored from its address step, the clock after its EA clocks where a displacement would be taken: its first data cycle no earlier than `dfloor` 2 clocks after it, s + 5 at every wait (`ea_floor`) | `F21-none-es-ld-bw-pE-w0`: X starts at 79 with 7 bytes stored, one latched, no room, no abort, no fetch; silicon F72 F75 R84 (False: R82); its pO twin with 6 stored aborts and reads at 83 either way; no ModR/M form's first data cycle before s + 5 in 9,420 cycles, the model's 33 cells at s + 3 (7 stored at the start, F20 and F21) all misses. −33 | the aborted cycle as the only way to s + 5 (`abort_fetch`, still carrying other runs: False −1034) |
| the floor from the displacement's take also reaches a memory request posted before the take (POP r/m's write, posted at the stack data): it is the first data cycle on that address (`disp_floor=posted`) | `F21-none-n1-pop-bw_ix_d16-pE-w1`: the d16 taken at 90, the extra EA clock first; silicon r82 W92 F96 (take: the write issuable at 91 and the fetch the take raised goes first, F91 W95); the d16 twin `-bw_d16-pE-w1` taken at 89, W91 F95 exact. −26 | the floor applied at the next post only (`disp_floor=take`) |

Refuted on the re-read (all removed from the code): `hold_count=ahead`'s
discount of the bytes still to take as the handle (PUSH's write at 3
bytes with nothing outstanding is held as the store's at 4 with 2; the
F5 run it was adopted on, `F5-out-add_m_imm-k1-pE-w0`, is at count 0 in
I/O recovery, where silicon fetches in 39 of 39 cells, so the rule stays
for the clocks inside the setup); the idle clock after a run's fetch
when the request is already issuable (+3 at 0 waits, −72 at 1–2 waits,
a knob dependence: `F5-push-add_m_imm_d16-k1-pE-w0` R91 against R90); a
fetch's wait state counted as the fetch-free clock everywhere (+8
−170); the mod 00 floor counted from the EA step instead of the start
(−2882: `F4-push-ld_bw-k1-pO-w0`, the take sync waiting on fetch 81,
R86 = s + 5); POP's floor without the fetch hold (+0); and the aborted
cycle removed once the floor is in (`abort_fetch=False`, −1034: it
carries more than s + 5).

**The take on an I/O issue clock, the IR's room inside the EA clocks,
the RMW's ALU clocks through a fetch, the immediate form's start beside
a fetch** (twenty-first fit, F21/F4/F5/F15/F19 re-read; tests in
`test_sim.BaseIndexDisplacement`; losses are each rule's own flip back
on the final configuration over all 17,822 runs; nothing gains on a
flip back):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| a displacement taken on the clock an I/O cycle issues extends that cycle a clock: nothing starts on the clock after its last (the fetch request stands and issues a clock later) and its recovery and the group setup's bus-free count run from that clock (`disp_io=extend`); only base+index+d16, with its extra EA clock, takes on the issue clock in the corpus (the OUT frame, lead l0, 78 takes), its d16, d8 and direct twins taking a clock before it | `F21-out-l0-ld-bw_ix_d16-pE-w1`: the d16 taken at 85, the marker's I/O 85–87; silicon F89 R93 (none: F88 R92); the twin `-bw_d16-pE-w1` taken at 84, F88 R92 exact; `F4-out-ld_bw_ix_d16-k1-pO-w2` I87 F91 R96 (none: F90 R95); `F21-out-l0-sti-bw_ix_d16-pE-w0`, the write's group setup counted from the held clock, F88 F92 W95 (the fetch alone held: F88 F91 W94). 78 of 78 a clock late, the 195 twins exact; a fetch no earlier than 4 clocks after any take reads the same on this corpus (the I/O is 3 clocks in every cell). −76 | the take changes nothing on the bus |
| the empty IR is not room for a word on a delivery clock while a ModR/M memory form with a displacement runs its EA clocks, before the address step where its displacement is taken: under `ir_load=disp_data` it cannot load before that take or the first data cycle (`ea_ir_room`) | `F21-push-l0-ld-bw_ix_d16-pE-w0`: s = 81, EA clocks 82–84, fetch 81 delivers at 84 inside the third with 3 stored and 2 delivered; silicon w78 F81 F85 R88, the fetch on the take clock (False: F81 F84 R87); `F21-out-n1-ld-bw_ix_d16-pE-w0` F88 F92 R95 (False: F91 R94). 0 of 18 such cells fetch in silicon; every cell with the EA clocks done (the immediate store's displacement due on the delivery clock, TEST [0C00h]'s free clocks) do. −20 | the IR counted as a seventh slot on every delivery clock (`room_ir`) |
| an ALU RMW's ALU clocks count through a fetch in flight; only its result-route clocks (XCH's two through the data latch) and its last setup clock need the bus free of fetches, and the class's `setup_free` still opens the window the refresh rule reads (`rmw_alu=through`) | `F21-out-l0-add-bw_d16-pE-w0`: R90, fetch 93 on the write's first setup clock, silicon W96 (free: W97); the d8 twin, no fetch, R90 W95; `F15-a-out-and_dir_aw-pE-w0` the same; `F14-t-out-xch_dir_aw-pE-w0` R90 F93 W98 either way; `F17-s-n0-rmw-pE-w0` keeps its refresh at 92 (`rmw.setup_free` 1 instead: +15 −5, the XCH cells and two refresh-on ADDs lost). 15 of 15 at every wait. −21 | every setup clock past the first `setup − setup_free` fetch-free |
| a ModR/M memory form with an immediate (the immediate store, the immediate RMW, TEST r/m,imm), due to start on a word's delivery clock with `io_b2b_q` 3 bytes or fewer stored, where its start empties the IR and that room raises a fetch on the clock, waits that fetch out as `io_older` has an I/O or ModR/M form wait out an older one: its operands are the bytes behind the address, which the stored ones do not cover (`imm_start=wait`) | `F21-out-l0-sti-bw_d8-k2-pE-w0`: the second `MOV [BW+10h],imm16` due at 97 on fetch 94's delivery with 3 stored, one latched; silicon F94 F97 F100 W107 (none: W104); `F5-out-st_imm_bw-k2-pO-w0` W108 (W105). 9 of 9; at 4 stored or more the form starts beside the fetch (the threshold one higher loses 134); loads, stores and RMWs in the same state start beside it, 726 of 726. −11 | the form starts beside the fetch its start raised |

Refuted on the re-read (all removed from the code): the I/O cycle's
clock held for the fetch alone, the recovery counted from the I/O's
real last clock (`disp_io=idle`, +84 against +86: the base+index+d16
immediate store's group setup must count from the held clock,
`F21-out-l0-sti-bw_ix_d16-pE-w0` F88 F92 W95 against F88 F91 W94); no
fetch request at all inside a displaced form's EA clocks, the room
capped below a word (+1 −230: silicon fetches inside the EA clocks with
room for a word without the IR, 234 cells at s + 2); `rmw.setup_free`
1 in place of the ALU clocks counting through (+15 −5: the three XCH
[0C00h] cells and two refresh-on F17 `ADD [BW],AW` runs, whose refresh
window moves off the write's first setup clock); the immediate form's
wait one byte higher (+8 −134, the F5 d16 forms under the OUT frame
starting beside the fetch at 4 stored) and limited to one displacement
byte (two runs fewer).

**The left-out write's slot, TEST's fixed lookup, CMP r/m,reg as the
RMW without its write** (twenty-second fit, F19/F14/F15/F16/F5 re-read;
tests in `test_sim.LeftOutWriteAndTest`; losses are each rule's own
flip back on the final configuration over all 17,822 runs; nothing
gains on a flip back):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| the left-out write's slot (CMP r/m,imm, TEST r/m,imm, CMP r/m,reg: the RMW template with nothing written) runs a fetch only when the queue has room for a word counting its stored bytes and the IR but not a word delivered on the slot clock, the bus unit having chosen the slot's cycle before that word was written (`slot_room=word`) | `F19-i-push-l0-cmpimm8-pE-w0`: the read at 87, the slot at 92 with 5 bytes counted and no cycle since the read; silicon runs no fetch there, the PUSH writes at 100 (any: F92, w101); `F19-i-push-l0-cmpimm-pO-w0`: slot 94 with 5 counted on fetch 91's delivery clock, 3 stored before it, F94 in both. 31 of 31 such slots carry no fetch (every one `CMP [BW],imm8`, whose one-byte immediate leaves the extra byte stored: item 1's one alignment), 266 of 266 with room for a word fetch. −55 | a fetch at any byte of room (`rmw_slot_any`) |
| a slot with no fetch in it is no bus cycle: the instruction ends and the next may start `sidle` 2 clocks after the slot clock, whatever the waits (`slot_idle=eu`; `rmw_imm.sidle` 2 and `rmw.sidle` 2, each pinned, 1 and 3 losing 19 and 33) | `F19-i-push-l0-cmpimm8-pE-w1`: R90, slot 96, the PUSH at 98 writes at 104 (cycle: PUSH at 100, w106); `-w2` R93, slot 100, w108; 12 of 12 cells followed by the PUSH. −59 | the slot lasts a write cycle of the bus's length |
| the slot fills the data latch from the slot clock for `wlatch` 4 clocks as the write it stands for would, so a port-form IN/OUT after it starts no earlier than slot + 4 (`slot_latch`) | `F19-i-out-l0-cmpimm-pE-w0`: slot 97 with a 3-clock fetch, the closing OUT at 101, I/O 111 (False: OUT at 100, I110); at 1–2 waits the slot's fetch ends past the latch, exact either way. 34 of 34 at 0 waits, 62 of 62 at 1–2. −56 | the latch untouched by the slot |
| a form whose operation no ALU-op field names (TEST 84/85, F6/F7 /0; `grp_ops=fixed`) counts a group setup clock on an aborted start cycle, as the unit forms' setup does under `abort_unit=loop` (`abort_fixed`) | `F14-t-none-test_bw_aw-pO-w0`: TEST starts at 72 on an aborted cycle 72–74, R79 (False: R80); `F14-t-push-test_bw_aw-k2-pE-w0`, the second TEST at 94 on one, R101 (False: R102); with a fetch on its start clock exact either way; every ALU form in that state at the floor s + 5 in both. 15 of 15. −15 | the aborted cycle's clock for the unit forms only |
| TEST r/m,imm16's count floor from its start carries the `fgrp` 2 lookup clocks: its fixed lookup runs before the group decode the floor counts (`fixed_floor`) | `F15-a-none-test_bw_imm-pO-w0`: no fetch in the head, R81 = s + 9 (False: R80); its pE twin with a fetch at s reads at s + 10 either way; `CMP [BW],imm16` in the same state at its floor s + 7. 12 of 12; the `rmw_imm.istart` dependence (F16 wanting 7) was this: 7 for every form −255. −12 | the floor at `istart` + the immediate's bytes for every immediate form |
| TEST 84/85's lookup between its ModR/M and displacement bytes costs one clock more when a fetch issued on the instruction's start clock (`lookup_start`, with `load_alu.fdisp` 3 in place of 4) | `F14-t-push-test_dir_aw-k2-pE-w0`: the second `TEST [0C00h],AW` starts at 95 with no fetch, the displacement leaves at 98, F100 R103 (False, fdisp 4: F101 R104); its pO twin starts beside fetch 95, F101 R104 either way; the twentieth fit's "fdisp 4 prefers 3 at even parity" was this. −18 (fdisp 4 with the rule −3; 3 without it −18, 2 −24) | the lookup's clocks the same after any head |
| CMP r/m,reg (38/39) runs the RMW template with its write left out and the write's slot kept, its posted write holding fetches as any does (`hold_fetch=le_q`) through the write's setup (`dest_route=slot`); the ALU clocks count through a fetch in flight for that left-out write too (`rmw_alu=through`, −24 on this write) | `F14-t-none-cmp_bw_aw-pO-w0`: R77, 4 counted on the data clock, silicon F82 (d0ro_latch: F80); `F15-a-out-cmp_dir_aw-pE-w0`: a fetch at 93 then at 96, where the AND twin writes (`F15-a-out-and_dir_aw-pE-w0` F93 W96), the closing OUT waiting for the latch to 100, I110 (d0ro_latch: I104); 18 of 18 at 4 counted wait to D + 2, 3 of 3 at 3 counted fetch at D. −21 | the datum routed into the data latch after two route clocks (`d0ro_latch`, tenth fit, right until the slot rules existed) |

Refuted on the re-read (all removed from the code): the slot fetching
with room for a word counting the word delivered on the slot clock
(−113) and the request rule alone for the slot (`grp_read=rmw_slot`,
−116); the aborted cycle's setup clock for every class
(`abort_unit=all`, −272); `rmw_imm.istart` 7 in place of the lookup's
place before the floor (−255); `load_alu.fdisp` 3 without the
start-clock clock (−18; 2: −24); a fetch hold on CMP r/m,reg's route
clocks (`route_hold`, closing 18 of the 21 cells and not the three OUT
pE ones; held through the route at any count it tied on exact runs and
contradicted those cells' first fetch; both removed once `slot` covered
the 21); for the F20 `ES: NOP ; MOV r,r` leads, `reg.nx` 1 (+5 −67).

**The register form's IR load, the latched byte's clock, the NOP's
fetch after an I/O, the port take on a fetch's issue clock**
(twenty-third fit, F20/F19/F7/F3/F16 re-read; tests in
`test_sim.RegisterFormLeadsAndPortTake`; losses are each rule's own
flip back on the final configuration over all 17,822 runs; nothing
gains on a flip back):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| a register form's IR loads `reg.nx` 1 clock after its last operand take, a clock later when that take falls on the clock an I/O cycle issues, the ALU passing the OUT's data then (`io_take_nx`, with `reg.nx` 1 in place of 2). The 8B form's next start shows in exactly two states and they disagree on nx: a take on the marker I/O's issue clock (T + 3 at every wait, 64 of 64) and a take on an idle bus with nothing requested, reached only after `ES: NOP` (T + 2, 13 of 13); every other state hides the load behind the take sync | `F20-r-push-es-none-movr-pO-w0`: MOV AW,DW takes its ModR/M at 88 with the bus idle, the PUSH starts at 90 and writes at 96 (nx 2: w97); `F19-d-out-movawdw-outb-pE-w0`: the take on the marker's I/O issue clock 84, OUT DW at 87, F87 F90 I97 (nx 1 alone: F90 I93). −64 (the rule with nx 2 −13; the later load for every class taking on the I/O issue clock −75: the shifts and the multiply) | the IR load nx 2 clocks after any take |
| a ModR/M byte committed to the decoder's ModR/M latch does not hold the queue's write port for a byte latched on an earlier clock, which goes into the queue at the end of that clock if there is room (`modrm_port`) | `F20-r-push-es-movawdw-ld-pO-w0`: the word delivered at 87 into a full queue, its second byte latched; the ModR/M take at 88, the IR load at 89, the load's start, take and IR load at 90, and silicon fetches at 90, F90 R95 (False: the byte still latched at 90 holds the fetch, F91 R96); alone it moves no run, with nx 1 it closes the 8 `ES: NOP ; MOV r,r ; X` cells. −10 | the committed ModR/M byte holding the port as any committed take (`latch_read=commit`) |
| a register-only form without operand bytes (NOP) started on the first fetch's issue clock after an I/O cycle, where the IR load and the reissue keep the request raised, gets no back-to-back fetch on its last clock: the fetch waits for the next instruction's start, as `io_ir_hold` holds one raised on the I/O issue clock itself (`nop_hold=any`; `io`, scoped to the clock after an I/O, ties: no NOP start elsewhere has the back-to-back clock before the next start) | `F19-d-out-movawdw_nop-outb-pE-w0`: the I/O 84–86, the NOP at 87 on fetch 87's issue clock, the IR loading the DW form; silicon F87 F91 I100, the DW form starting at 91 with that fetch (none: the back-to-back fetch on the NOP's last clock, F87 F90 I101); at 1–2 waits the back-to-back clock is the next start or later and both agree (12 of 12). 6 of 6. −6 | the reissued request served back to back whatever started |
| a port byte taken on a fetch's issue clock reaches the port latch a clock late, the bus unit driving the fetch's address that clock, so an I/O waiting in the slot issues no earlier than the take + 4 (`port_issue`; `port_landed`'s late landing on an issue clock) | `F7-out-out_imm_al-out_imm_al-pO-w0`: the second OUT's port byte at 94 on fetch 94's issue, the first OUT's I/O with 3 setup clocks left, silicon I98 (False: I97); at 1–2 waits the count through the fetch's wait states ends there anyway (24 of 24 agree); on an idle bus or with an earlier fetch in flight the take relatches on time (858 of 858). 8 of 8, every OUT-after-OUT at odd parity and 0 waits (F1, F5, F6, F7, F14 O, F15 O, F20). −8 | the take holding the I/O to take + `relatch` 3 wherever it falls |
| an instruction that starts on the clock a byte latched behind a full queue goes into the queue runs its first EU clocks from the clock after, the decoder's write port being the byte's that clock; a form taking an operand byte on its start clock keeps the port and the byte waits (`latch_start`) | `F3-push-mov_cl_imm-k4-pO-w0`: the third `MOV CL,imm8` starts on fetch 90's delivery with 6 stored and one latched, takes at 96 with the IR load, the fourth starts at 97 as the byte goes in; its take and fetch at 101 (False: F100); 10 of 10 `MOV r,imm8` in that state (F3 k = 4 both frames, F16 S `NOP^n ; MOV CL`), 82 of 82 `SHL AW,CL` (a take on its start clock) exact either way. −10 | the first EU clocks from the start whatever the port does |
| the aborted cycle's one-word room test does not count a byte still latched behind a full queue after its delivery clock (it is not in the queue), and the take's sync, which counted no request, waits for the aborted cycle (`abort_latched=any`; `full`, a byte latched behind a full queue only, ties) | `F16-s-none-cl4-n1-shlcl-pO-w0`: `SHL AW,CL` starts at 82 after a NOP that ran with 6 stored and one latched; its ModR/M take and IR load at 82 leave room for one word but the latched byte; silicon's shift runs 2 clocks later, from an aborted cycle 82–84, the closing `MOV CL`'s fetch at 105 (False: 103); 5 of 5, the only `SHL AW,CL` starts in that state; the pE twin exact either way. The record's earlier attempt (an aborted cycle at one byte of room with a latched byte) changed nothing because the take's sync counted no request. −5 | the latched byte counted as stored by the room test (`byte_d`) |

Refuted on the re-read (all removed from the code): the later IR load
for every class taking its last byte on an I/O issue clock (−75: the
shifts and the multiply starting on the OUT's issue clock at odd
parity); the latched byte going into the queue on any clock with room,
the port ignored (−135: the F9, F11 and F16 S marker-less runs at 1–2
waits, where `MOV CL,31`'s immediate take frees the room with the port
busy and silicon still holds the fetch a clock); a ModR/M commit
freeing the port on the delivery clock too (−364); `reg.nx` 1 alone
(+5 −64). Two ties kept at the broader option: `nop_hold=io` (the
clock after an I/O only) and `abort_latched=full` (a byte latched
behind a full queue only), each +0 −0 against the chosen value.

**The group clock's hold through an I/O's recovery, the aborted-start
multiply's end, the EA clocks' back-to-back fetch** (twenty-fourth fit,
F14/F15/F16/F21 re-read; tests in `test_sim.AbortEndEaB2bAndGroupHold`;
losses are each rule's own flip back on the final configuration over
all 17,822 runs; nothing gains on a flip back):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| a group form's request whose next setup clock is a bus-free group clock (`grp_free_bus`), waiting out an I/O cycle or its recovery, holds a fetch first requested on or after that I/O's issue clock until the group clock can count; the held fetch dates from that clock and goes first against the request just become issuable; a fetch requested before the I/O issued runs, as `io_hold` lets an older fetch run (`grp_io_hold`) | `F14-t-out-test_dir_aw-pO-w0`: `TEST [0C00h],AW` takes its displacement at 85 on the marker I/O's issue clock and fetch 82's delivery, the fetch requested there; its read, one group clock, all of it bus-free, is posted at 86; the I/O 85–87 held to 88, recovery to 90; silicon F91 R94 F97 (False: F89 F92 R95), at every wait; `F14-g-out-shl_bw_cl-pE-w0` (setup 7 all free, the fetch requested before the I/O) fetches on the I/O's first free clock, 3 of 3. The six are the only cells in the corpus in that state; the take state itself (2 counted, 1 stored, 1 latched, a delivery, the IR loading) is the 30 pO base+index+d16 loads', which fetch 2 after the I/O. −6 | the group clock letting a fetch run during the recovery as any request does (`le_q`) |
| a register multiply or divide started on an aborted fetch cycle ends with its early exec: no clock kept (`abort_reg_end=early`). In 15 of the corpus's 18 aborted-start register multiplies the retry fetch raised `mtail` 2 clocks before the early end is in flight on that end and the next start waits for it, so the kept clock never showed, `F3-push-mulu_dw-k2-pE-w0`, the run it was adopted on, among them (F147 w156 either way); in the other three it shows and silicon has the early end | `F16-l-push-nop2_mulu_aw-pO-w1`: MULU AW starts at 90 on an aborted cycle with a delivered byte latched, no retry fetch (no room), the PUSH writes at 129 (keep: w130); `F16-l-out-nop2_mulu_aw-pO-w0`: the retry fetch 124–126 ends on the early end, F136 I139 (keep: F137 I140); also two refresh-on F18 BD multiplies. −5 | the end kept a clock later, where the exec would have ended from the take sync (twelfth fit, `abort_reg`) |
| no back-to-back fetch runs on a clock inside a ModR/M memory form's EA clocks before its displacement's take: the clock stays idle and the still-raised request issues on the take clock (`ea_b2b`). Only base+index+d16 has a delivery inside its EA clocks, and silicon issues no fetch on its third EA clock in any cell: 21 want one, 18 through the IR's slot (`ea_ir_room`) and these 3 back to back, all 21 fetching on the take clock | `F21-out-l0-st-bw_ix_d16-k2-pE-w0`: the second `MOV [BW+IX+200h],AW` starts at 94 beside fetch 94 with 2 bytes stored (every first instance starts with 3 or more), the fetch's last clock 96 sees room for a word; silicon F94 F98 F101 W104 (False: F94 F97 F100 W103); the 1-wait twin's back-to-back clock is the take clock, F+4 in both; the three are the only back-to-back fetches due inside a displaced form's EA clocks in the corpus. −3 | the back-to-back fetch on the next clock wherever the EU is |
| the idle clock `free_idle` puts after a run's delivery-clock fetch at a request's free clocks' eve follows a fetch the bus unit committed to back to back at that eve as well, `free_hold`'s other exception (`free_idle_b2b`) | `F21-out-l0-sti-bw_ix_d16-k2-pE-w0` under `ea_b2b`: the second immediate store takes its d16 at 102 with fetch 102, posts its write at 103, fetch 105 is back to back on the write's eve (count 2 of 3); silicon F105 W109 (False: W108); `F21-push-l0-sti-bw_ix_d16-k2-pO-w0` F99 W103 (W102). Thin: the only two such fetches in the corpus once `ea_b2b` is in, and alone the option moves no run. −2 | no idle clock after a back-to-back fetch at the eve |

Refuted on the re-read (all removed from the code; gains and losses
against the twenty-third fit): the group clock holding a fetch of any
age (+6 −3, `F14-g-out-shl_bw_cl-pE-w0/1/2`); no fetch at all on any
EA clock after a displaced form's start (+1 −233, the F4 OUT pO loads'
fetch at s + 2, requested before the marker's I/O lead). For the
immediate RMW's idle clock (item 1, not adopted): the idle clock
whenever the request is already issuable (+3 −76, all at 1–2 waits);
when the eve was reached on the fetch's last clock or later (+3 −35,
the 1-wait immediate stores, which are in the same counted state); for a
read only (+3 −0, but no read other than these three is in the state
and no write in it idles, so a read cannot be told from a request
posted on a non-wait clock); for a 3-clock fetch only (+3 −0, a rule on
the wait knob). Neither of the last two is a model state the corpus
separates, and each would be fitted to the three runs of one cell.

**HALT's status clocks, the refresh's place in an I/O's lead, the EU's
early fetch run after a beaten sync, the address phase under a refresh**
(twenty-fifth fit, the refresh-on END blocks re-read; tests in
`test_sim.RefreshHaltAndBeatenSync`; losses are each rule's own flip
back on the final configuration over all 17,822 runs, exact runs and
the refresh-on END-mismatch count; no refresh-off run moves under any
of them):

| Rule chosen | Evidence (clocks from t_fill, H = HALT's first clock) | Alternative replaced |
| --- | --- | --- |
| the halt status holds the bus unit on HALT's first two clocks: a refresh request pending on the first goes at once and the status follows it, on the clock after its last, a clock a posted I/O's setup does not count either; nothing goes on the second (`refresh_halt=status`) | `F13-s-shlcl2-pO-w0`: HALT at 235, the END's I/O due at H+5, the request at H+1 served at H+2 (none: H+1); `F13-s-shlcl9-pO-w0`: the request at H served there, the I/O at H+8 (none: H+7). 310 prefix-matched END-block requests at every wait and both RFT values: served at H, H+2 or the I/O's issue clock, never H+1, H+3 or H+4. −204 | a refresh served on any free clock in HALT |
| no refresh starts while a posted I/O request is in its lead (its last `lead` 2 setup clocks, the bus unit committed to it); it goes on the I/O's issue clock, ahead of the I/O (`refresh_lead=closed`) | `F13-s-shlcl7-pO-w0`: the END's OUT due at H+5, the request at H+4 served at H+5 and the I/O at H+10 (open: R H+4, I/O H+9); 49 runs at 0 waits, the same at H+3 at every wait. −116 +38: the runs a flip back gains all have a third back-to-back fetch in HALT after a beaten take, where the I/O's count is a clock behind silicon's (item 8 c, open) | a refresh on any free clock whatever the I/O's count |
| when a refresh beats the fetch request an operand take's sync counts, that fetch run is 2 clocks earlier for the EU than on the bus: the sync is met on the beaten fetch's last clock but one, an instruction may start on the last two clocks of a fetch of the run, and the run's next fetch, committed back to back, holds a start from the previous one's last clock (`refresh_sync=run`). The EU loses the refresh's length less 2, as a count loop does | `F17-s-n0-shlcl1-pO-w0`: the END's MOV DW takes its latched byte at 207, the refresh 207–211 beats the take's fetch, which runs 212–214 with 215–217 back to back; silicon's OUT starts at 213 and HALT at 216, the I/O at 221 (wait: 215, 218, 223); the refresh-off schedule moved by 3 at every wait (88 runs; 19 more with no request in HALT show the I/O at H+3 against the model's H+5). −241 | the EU delayed with the fetch (the sync met on its delivery) |
| a fetch request a refresh beats after HALT has started, the bus unit's back-to-back commitment included, is dropped (`halt_refresh=run_drop`); one beaten before HALT started still runs after the refresh, as before | `F13-s-shlcl7-pE-w2`: HALT at 253 while fetch 250–254 runs, its last clock committing a fetch back to back, the refresh at 255 beats it; silicon R255 I260 with no fetch (run: F260 I265). −28 | the beaten request kept (`run`, fourteenth fit) |
| a memory form's clocks step straight after its displacement's take, and the data request it then posts, are not micro-boundaries a refresh holds: a refresh taken on the displacement's take leaves the address phase running and the request waits for the bus (`refresh_disp=free`) | `F17-p-n1-shlcl31-pO-w1`: the RFMON store takes its displacement at 96 with the refresh 96–100; the SFR write at 101 and the next fetch at 104 (hold: 103 and 106); its refresh-off twins exact; the two parts are one state and alone each moves nothing; the hold dropped after every take −214. −3 (the one run the eighteenth fit lost, item 8 h, and two more) | the step's first clock and the post as hold points |

Refuted on the re-read (all removed from the code): the sync lapsing at
the beaten fetch (HALT moved 3, 4 or 0 clocks where 2 is needed); the
early sync without the start rule (+29 alone, the OUT still held by
`start_sync`); the early fetch run for every refresh-beaten fetch, not
only a synced one (+133 −82); the I/O's uncounted clocks moved 2 clocks
early for the third-fetch rows (−127: right at 0 waits, wrong at 1–2
where the posted clock is a wait state the count skips); the boundary
dropped after every take (−214) and each half of `refresh_disp` alone
(no change). Not adopted from stage 8: `refresh_exec=every2_early`
(+96 −61, the trade the fifteenth fit refuted) and `refresh_recent` 15
(+78 −61, apparently the same runs).

**The END I/O's count beside the early fetch run, the lost request's
re-evaluation, the loop's eve as a hold point only** (twenty-sixth fit,
the refresh-on END blocks and loop eves re-read; tests in
`test_sim.RefreshEarlyCountLostRequestAndEve`; losses are each rule's
own flip back on the final configuration over all 17,822 runs; no
refresh-off run moves under any of them):

| Rule chosen | Evidence (clocks from t_fill, H = HALT's first clock, E = the unit's exec start) | Alternative replaced |
| --- | --- | --- |
| an I/O request's setup clocks not counted because a fetch issues or waits on them (`dw_count=bus`, `io_count=nowait`) are, for a fetch of the EU's early run after a refresh beat a synced fetch (`refresh_sync=run`), the clocks 2 earlier, as the EU sees the run; one that lands before the post or on a clock already uncounted (HALT's status clock) costs nothing (`dw_view=eu`) | `F17-s-n2-out-pE-w0`: the END's OUT posted at 212 inside the run 211, 214, 217 with HALT at 215, the third fetch's issue falling on HALT's clock as the EU sees it; silicon R220 I225 (bus: R221 I226); `-w1`: fetches 216, 220, 224, R228 I233 (bus: R229 I234). Every prefix-matched END block with the post inside the early run and a third fetch after HALT is a clock early in silicon (64 runs, item 8 c's 37 among them), every one without it right, at every wait; the previous package's prototype moved only the back-to-back exclusion and lost 127 because the run's wait states did not move with it. −64 | the clocks as the bus has them |
| a fetch request lost to a refresh outside a count loop (`refresh_drop`) is evaluated again on the next instruction start, or on the queue's change if that comes first; at HALT's start it waits out the halt status's two clocks and goes as a beaten request, ahead of the posted I/O and its hold (`refresh_lost=start`) | `F13-s-shlcl4-pO-w0`: the END's OUT starts and loads the IR at 226 on fetch 223's delivery with room 3 and the second byte latched, the request lost to the refresh 226–230, HALT at 231; silicon F233 I236 (queue: no fetch); `F13-s-shlcl1-pO-w1` R225 F232 I236 (queue: I235). 68 prefix-matched runs at every wait, and the only runs with room for a word and the flag down at H−1 (the refresh-off corpus never has room there); a re-raise on the refresh's end is wrong outside HALT (+68 −3, the memory forms fetching ahead of their read). −69 | the lost request back on the queue's next change only (fourteenth fit) |
| the shift's loop eve (its exec clock 2 before the count loop) is a micro-boundary for a refresh already on the bus, held within `refresh_recent` of the previous refresh as before, but never takes a pending request: that request waits for the loop's first clock whatever the previous refresh's age (`refresh_eve=hold`) | `F17-s-n0-shlcl2-pE-w0`: the closing LS's shift, exec 120–125, the previous refresh at 109, fetches 114 and 117, the request at the eve 124; silicon R126 and the END's I/O at 226 (both: R124, I225). Of 303 prefix-matched eves with a request pending, silicon takes it there in 7 (one cell: 0 waits, three fetches after a refresh 16 clocks back) and waits in 296, where the window took 164; no window in clocks, fetches or idle clocks separates the 7. −113 | the eve taking a pending request within the window (`every2_recent`, fifteenth fit) |

Refuted on the re-read (all removed from the code): the lost request
re-raised on the refresh's end (+68 −3, 19 runs diverging earlier),
the same without precedence over the posted I/O (identical), and only
when HALT finds it lost (+68 −0, 10 fewer matched events than the
start); at the eve, acceptance only while the bus has run a cycle on
every clock since the previous refresh (identical to the hold on this
corpus), with at most k idle clocks before it (k = 1 +111, k = 2 +40
−30, k = 3 +37 −30), or with a fetch issued in the last 4, 5 or 6
clocks (+113, +111, +47); the D1 shift's exec0 clock taken from the
loop's exit (+4 −1); a fetch requested on a beaten fetch's delivery
clock held a clock (0 to +8, −33 to −108). With the three rules in,
flipping `refresh_lead` back gains 1 and loses 116 (−116 +1): the 38 runs it gained before were the END rows now closed by `dw_view=eu`.

**The NOP's end under a refresh, the unit forms' exits, the aborted
request and the I/O lead under a refresh** (twenty-seventh fit, the
refresh-on middle re-read; tests in
`test_sim.RefreshNopEndUnitExitsAndAbort`; losses are each rule's own
flip back on the final configuration over all 17,822 runs; no
refresh-off run moves under any of them):

| Rule chosen | Evidence (clocks from t_fill; R and E a refresh cycle's first and last clock, or E a unit's exec start) | Alternative replaced |
| --- | --- | --- |
| the empty operand take that ends a form without operand bytes (a NOP) is no step: the clock its clocks end is the next instruction's start, a micro-boundary, and a refresh on the bus holds that start to the clock after its last as any other start in the window (`refresh_take0=none`) | `F17-s-n0-nop8-pE-w0`: the refresh 92–96 taken on a NOP's start, the next NOP's start on 96; silicon F97 F101 R109 F114 F121 (take: the NOP on 96, F100 R108 F113 F116); `F18-b-p-n4-shlcl4-pE-w0` (an `ES:` prefix before the NOPs) R95 F100 R108 F113 (take: F100 F103 R110). Of 13,649 prefix-matched refreshes, every instruction the model started inside one after anything but a NOP started on E+1; after a NOP on E (771). −190 | the empty take served while the refresh runs (no hold point) |
| a register multiply's and divide's last `rexit` exec clocks (8 and 6) run as the count loop's exit, as the shift's: the boundaries there are the clocks an even number before the end (6, 4, 2), the exit's first clock none, the loop before it keeping its odd distances to its own end (`refresh_mul_exit=exit`) | `F17-s-n2-mulu-pE-w0`: MULU AW's exec from 98, the refresh at 108 held 3 clocks, the request at 124; silicon R126, 6 before the end (none: R125, 7 before); `F13-u-none-mulu-pE-w2` the request at E+32 served at E+33 (none: E+32). The first request in the exec is right in every run up to E+22 (218 rows); every request off is in the last 8 clocks. The divide's exit scanned: 6 best, 8 loses 11. −188 | one loop of odd-aligned boundaries to the end (`loop_odd`, fifteenth fit) |
| the retry of a request dropped at a register shift's, multiply's or divide's start rises again at its distance before the exec's end as the EU's refresh holds move that end, not at the clock fixed when the step began (`refresh_retry=end`) | `F17-d-n1-mulu-pE-w0`: MULU AW started on an aborted cycle, exec 90–120, the refresh 100–104 held on 102–104 (the end 124); silicon F122 (fixed: F119); 18 prefix-matched runs, every one with a refresh held in such an exec and the retry pending. −14 | the retry clock fixed at the step's start |
| `SHL AW,1` (D1, no count byte, exec0 5) runs the count-byte form's exec head (3), its loop (2) and a 2-clock exit: the clock it lacks is its exit's; the exit's first clock is both an acceptance and a hold point, `unit_hold` holds across the split's seams and the loop-exit re-raise stays 2 clocks before the end (`shift_exit0=exit`) | `F18-b-n2-shl1-pE-w1`: the request at E+1 served at E+3 (tail: E+2, the loop's first clock); `F18-b-n1-shl1-pE-w1` E+3 at E+3 (tail: E+5). D1's prefix-matched requests: silicon takes on E, E+3, E+5, E+7, never E+2 (17 rows) nor E+4; `SHL AW,CL` and `SHL AW,4` take on every iteration start and on the exit's clock 2 before its end. The split alone +4 −3; with the seams held, +33 −0. −33 | the last `shift_tail` 3 clocks run after the loop as the exit |
| on a clock where an instruction starts, takes an operand byte and loads the IR with room for exactly a word, a pending refresh that takes the bus does not beat the fetch request: the request is aborted as on a free bus and raised again as the aborted cycle's rules have it (`refresh_abort=abort`) | `F18-b-p-n1-mulu-pE-w0`: MULU AW starts at 95 on the refresh 95–99 with room 2; silicon R108 R125 F134 (beat: F100 R109 R124); `F18-b-n3-shl1-pE-w1` F+6 (beat: F+1); every register unit form started so with room 2 (29 refreshes) has no fetch on E+1 in silicon, with room 3 or 4 all fetch there. −43 | the beaten request running after the refresh (`refresh_after=fetch_next`) |
| an older fetch held by a posted I/O runs on the first clock of the I/O's lead on which the bus is free: when a refresh is still on the bus there, on the clock after its last (`refresh_lift=free`) | `F13-c-out-shlcl0-pO-w0`: the marker's OUT posts its I/O at 95 with the fetch raised there, the refresh 98–102 runs into the lead; silicon F103 I106 (clock: I104 F107); 25 prefix-matched refreshes in that state, every one F+1 in silicon. −14 | the lead's first clock whatever the bus holds (`io_hold`) |

Refuted on the re-read (all removed from the code): the eve after a
`unit_hold` wait taking the pending request (+0 −1); the early fetch
run of `refresh_sync=run` applied to any start on a refresh's clock
(−139; restricted to the unit forms, no change); a memory shift's
aborted request retried when its write ends (no run gained, and
against the 64 refresh-off memory shifts started on an aborted cycle,
which retry after the read); the `SHL AW,1` split on its own (+4 −3,
until the seams were held). Stage 8 from the hand fit chose no move
(`wlatch_ir_at=start` ties).

**The memory shift under refresh, the aborted cycle's clocks, the
posted request's first clock, the seams** (twenty-eighth fit, the
refresh-on middle re-read; tests in
`test_sim.RefreshMemoryShiftPostAndTakes`; losses are each rule's own
single-key flip back on the final configuration over all 17,822 runs;
no refresh-off run moves under any of them):

| Rule chosen | Evidence (clocks from t_fill; E the unit's exec start) | Alternative replaced |
| --- | --- | --- |
| the memory shift's write setup (`SHL [BW],CL`: the shift unit's clocks after the read) has the register shift's shape end-aligned to the write's issue: boundaries at the post's first clock, at `shift_tail` + 2k clocks before the issue (the loop's iteration starts and the exec's every second clock, none in the ALU clocks after the post), at the exit's clock `refresh_tail_bound` before the issue, and on the issue (the refresh ahead of the write); the EU holds at the next boundary until the cycle's last clock has passed (`refresh_rmw_shape=shift`) | `F18-b-n2-shlmcl-pE-w0` (CL = 31, the read 106–108): silicon R109 R124 R141 R156 R173 R189 W194 (even: R188 W195); `F18-b-n0-shlmcl-pE-w0` R108 (q 107), R124 (q 123): 7 and 24 after the data (even: 8 and 23). Silicon serves on odd distances of 5 or more from the issue, on 2, and on the issue, never on 1, 3 or 4 nor in the ALU's two clocks after the post, in all 96 F18 B memory-shift runs. −83 | a refresh on every even number of clocks before the issue (fifteenth fit) |
| a memory shift by CL's read (grp 4 + grpcl 3 setup clocks, all fetch-free) takes a refresh on its post's first clock, on the first of the grpcl clocks and on its issue clock; a refresh cycle is not a fetch, so the setup counts through it, and the EU holds at its next such boundary until the cycle's last clock has passed (`refresh_grpcl=step`) | `F18-b-n4-shlmcl-pE-w0` (the read posted at E+5, setup 7): q E+7, silicon R E+9, the read E+14 (hold: R E+11, read E+16); `F18-b-n1-shlmcl-pE-w0`: the refresh on the post E+5, the read E+12 (hold: E+15). Every prefix-matched memory shift: a request at count 2–4 taken on count 5, at 6 on 7, the read a clock late after a refresh on the post; the 16 NOP-then-memory-shift rows the twenty-seventh fit left are this state. −36 | the setup not counting while a refresh is on the bus, taken on the post and the issue only |
| a memory form's fetch request aborted while a refresh takes the bus is raised again when the next bus cycle after the refresh ends, as an aborted cycle's on a free bus (the form's own data cycle; behind a memory shift's read the posted write's setup then holds it) (`refresh_abort_retry=next`) | `F18-b-n3-shlmcl-pE-w1`: `SHL [BW],CL` starts at 99 on the refresh 99–103 with room 2; silicon R99 D112 … W201 F205, no fetch before the write (refresh: F104 R114 D119); `F17-s-n3-ld-pE-w1` and `-st-pE-w1` the same for a load and a store; the 64 refresh-off memory shifts started on an aborted cycle retry after the read. −11 | the retry when the refresh ends (twenty-seventh fit) |
| the clocks the EU's take sync waits for an aborted cycle are the EU's own, not waits: no micro-boundary, the next step (or the exec `abort_reg` starts on the cycle's last clock) the first (`refresh_abort_wait=run`) | `F18-b-n4-shlmcl-pE-w2`: the memory shift starts at E on an aborted cycle, the request at E+1; silicon R E+3 (wait: R E+1); `F18-b-n7-divu-pO-w1`: DIVU IX started so at 114, silicon R116 on the cycle's last clock. Every prefix-matched request raised during such a sync (10: RMW at E+1 and E+2, a store at E+2) goes on E+3 in silicon; the ten multiply and divide runs off at 1 wait were this state. −20 | each wait clock a boundary |
| the clocks an instruction waits for the previous one's write-back (`wbsync`: an OUT or PUSH after a shift or multiply) are not micro-boundaries: the EU runs into the instruction's next step as the write-back ends (`refresh_wbsync=seam`) | `F8-out-empty-pE-w0`: the marker OUT after the first LS starts at 87 with the refresh 87–91, wbsync 87–88, pre 89–91; silicon F92 I101 (wait: held to 91, the port take at 95, F95 R103 I108); the 19 runs of that cell (pE, 0 waits, every X) first diverge later, at the second OUT. No exact run gained: kept on matched events and the first divergence alone (−0 exact; 19 runs diverge earlier and 22 matched events fewer on a flip back; a tie in stage 8) | the wait a hold point |
| while the EU waits on a posted memory request a pending refresh is also taken on the post's first clock; the setup counts through the cycle and the EU holds at the next boundary (the first fetch-free clock, the issue) until the cycle's last clock has passed, unless the refresh beat a fetch request, whose fetch after the refresh keeps the window from counting instead (`refresh_post=post`; `post_beat` since the thirty-sixth fit: the hold stays beside a beaten fetch too, given back when that fetch runs ahead of the request on the clock after the refresh, `F27-push-fc-room-movawi-n0-k1-pE-w0` W111 F114) | `F13-c-push-shlcl2-pO-w0`: the marker PUSH AW starts and posts its stack write at 129 (setup 7, 3 fetch-free) with the request of 128 pending; silicon R129 W136 (free: R133 W138); `F17-c-push-empty-pE-w0`: the refresh 93–97 on the PUSH's post beats a fetch (98–100), silicon W101 with no hold. 19 marker-PUSH runs. −13 | the refresh taken at the first fetch-free clock or a bus start only (`boundary_bus`) |
| a clocks step lying between two operand takes of one instruction (the count-byte shift's `cpre` clocks between its ModR/M and count bytes; the RFMON store's), due on the clock after the first take, is no hold point for a refresh already on the bus: the EU runs into it and takes the next byte while the refresh runs (`refresh_take_seam=seam`) | `F18-b-n3-shli4-pE-w1`: `SHL AW,4` starts at 99 on the refresh 99–103 and takes its ModR/M byte there; silicon fetches at 104, the count byte taken under the refresh (hold: the cpre clocks held to 104, the count byte at 106, F106). Extended to every clocks step after a take −356 (the exec's first clock after a ModR/M or immediate take is a hold point, F13 S). −18 | the step's first clock a hold point |

Refuted on the re-read (all removed from the code): the aborted cycle
holding the bus against a refresh (+10 −12); an RFW 3 refresh holding
the EU 6 clocks (−1,473: the FCh prelude is RFW 3 too, and
`refresh_length` is right on the pins for every RFW); the beaten
fetch's back-to-back successor going ahead of the I/O's hold (+0 −0, 5
matched events); the write-back seam on the following clocks step
instead (+0 −7); the take seam for every clocks step after any take
(−356); `refresh_grpcl` without the hold at the post (+36 −13); the
post's hold cost even when the refresh beat a fetch (+13 −2);
`refresh_recent` re-scanned at 17, 19 and 20 (+1 −120, +61 −120, 0
−122). `F13-r-rfm-f3-pO-w2` runs under RFM FFh (RFW 3), not RFW 0 as
the previous package had it; its off clock and the three W FDh runs'
are the loop's parity, not the refresh length or interval.

**The loop's entry under a refresh, the SFR store's setup, the I/O's
count under an earlier refresh, the request lost inside a unit**
(twenty-ninth fit, the refresh-on middle re-read; tests in
`test_sim.RefreshLoopEntrySfrSetupIoPreAndUnitDrop`; losses are each
rule's own single-key flip back on the final configuration over all
17,822 runs; no refresh-off run moves but the 8 W ECh twins gained):

| Rule chosen | Evidence (clocks from t_fill; L the loop's first clock) | Alternative replaced |
| --- | --- | --- |
| the shift's loop eve (the exec clock 2 before the count loop) is no micro-boundary at all; the loop's first clock is the hold point, where the EU waits until the refresh cycle's last clock has passed: a refresh started on the exec's boundary L−4 costs its length − 4, one clock for a 5-clock cycle, and one on L−6 three clocks (`refresh_loop_hold=entry`; `refresh_recent` is then not read) | `F13-s-shlcl4-pE-w2`: the closing LS's exec 142–147, the refresh 144–148 (q 143, the previous refresh at 129); silicon R159 R176 R191 R208 R224 F233 (eve: no hold, R160 R175 R192 R207 R223 F232). Every prefix-matched refresh on the exec's L−4 boundary (X's shift, the closing LS, the first LS: 310 rows at every wait and previous-refresh age 13–64 clocks or none) costs 1 clock in silicon; in the loop 7,361 of 7,374 refreshes cost length − 2 wherever they land; the window had held 0, 1 or 3 by its age, never at 2 waits (111 rows, all wrong). −202 | the eve a hold point within `refresh_recent` of the previous refresh, the loop's first clock a seam (fifteenth fit) |
| the on-chip SFR store's write request (`MOV byte [0FFE1h],imm8` with DS1 = F000h, the RFMON store) counts every setup clock, a fetch in flight or not, the write never reaching the pins: it is due on a fetch's last clock and beats a fetch the queue commits back to back there (`sfr_setup=count`) | `F17-w-ec-n2-pE-w1` (refresh off): the store posted at 86 inside fetch 85–88; silicon F92 F96 F100, the SFR write on 89 (fetch_free: the back-to-back fetch 89–92 first, the write at 93, F99 F103); every prefix-matched RFMON store at 1–2 waits with a back-to-back fetch committed on the fetch's last clock (24 rows) and the P series' 2-wait rows (10) have the write right after the fetch. +21, 8 of them the W ECh refresh-off twins (item 8 e). −21 | the store's last `setup_free` clocks fetch-free as any store's |
| an I/O form's setup clocks before its post (from its start, or from the end of its write-back sync) count the wait states of a refresh cycle that started before the count began; one starting on or after the count's first clock keeps its wait states from counting (`refresh_io_pre=count`) | `F13-c-out-shlcl2-pE-w0`: the marker OUT after the first LS starts at 87 with the refresh 87–91 under its write-back sync, the port take at 92; silicon I99 F102 R105 F110, the refresh-off clock start + 12 (waits: I101 R104 F109 F112); `F17-s-n3-out-pE-w1`: an OUT started on the refresh's first clock does not count them (I113 in both). −3 | no refresh wait state counted before the post (`refresh_io=waits`) |
| while the EU is inside a register unit's clocks (a shift's exec or count loop, a multiply's or divide's loop), a fetch request raised on a word's delivery clock is lost to a refresh taking the bus on that clock also when it leaves room for exactly a word; one lost in a shift's exec, before its loop, comes back at the next instruction start (`refresh_drop_unit=unit`) | `F17-s-n1-rmw-pE-w2`: the closing LS's exec from 124, fetch 124–128 delivered on 129 with room 2, the refresh 129–133; silicon no fetch until 218, the closing LS's end (odd: F134 R144 …). −9 | the loss at odd room with a byte latched only (`refresh_drop_on=odd`, fourteenth fit) |

Refuted on the re-read (all removed from the code): the eve always a
hold point (+0 −115) or never (+1 −120); the eve taking a pending
request after any `unit_hold` wait (+13 −16: silicon takes it after a
1-clock stall, 13 rows, and not after 2 or 3, 16 rows, the stall's
length being the wait setting); every refresh wait state counted
before an I/O's post (+1 −9) or everywhere (+0 −464) or for a refresh
starting on the post clock (+0 −18); the early fetch run for a fetch
beaten on an I/O's post (+0 −1); `reraise_off` 1 and 2 with the new
drop rule (−3, −312). Stage 8 from the hand fit made no move; its ties
are `refresh_exec` every2 against every2_early (the eve no longer
read), `wlatch_ir_at=start` and `refresh_timer` start against end.

**The beaten fetch's pair under an I/O form, the take behind a latched
byte** (thirtieth fit, the refresh-on remainder re-read; tests in
`test_sim.RefreshIoRunAndTakeLatch`; losses are each rule's own
single-key flip back on the final configuration over all 17,822 runs;
no refresh-off run moves):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| while the EU runs an IN or OUT whose I/O cycle has not issued, the fetch a refresh beat is followed by a second fetch the bus unit commits to back to back on its last clock, whatever room the request rule counts then (the word's second byte waits in the latch if the queue is still full on its delivery), and that fetch goes ahead of the I/O even in its lead (`refresh_io_run=pair`; `pair_out` since the thirty-sixth fit: beside an OUT only, with a byte of room left counting the byte the decoder is still about to take, F27's IN cells) | `F13-c-out-shlcl2-pE-w2`: the marker OUT after the first LS takes its port byte and posts its I/O at 95 with 3 bytes stored, the refresh 95–99 beats the fetch; silicon F100 F105 I110 (none: F100 I106 F109); `F13-c-out-shlcl2-pO-w0`: the second OUT starts at 133 on the fetch the refresh beat, F133 F136 (none: F133 F143). Every prefix-matched beaten fetch under an IN or OUT has the second fetch in silicon (477 of 477, every wait); the model had it in 446, missing it wherever its rule counted room 0 or 1; for every other class the rule already gives silicon's answer (1,558 of 1,560), and the 28 room-3 starts of MULU, DIVU and `SHL AW,imm` have no second fetch, nor the refresh-off twins. The second fetch for every beaten fetch +32 −421. −7 | the request rule alone deciding the back-to-back fetch after a beaten one |
| a posted I/O request (port or DW form, the EU not in HALT) has steps: every second clock back from the issue its setup gives, from the clock `setup − 5` after the post, restarted on the clock after any bus cycle in the setup, the post clock one as well; a pending refresh starts on a step only, and beside an OUT the step takes it whatever the EU's own boundaries (`refresh_io_step=own`) | `F27-push-fc-port-inb-n0-pO-w0` R113 I118 (any: R115 I120); `F27-out-fc-port-outb-n0-pO-w0` R113 F118 I122 (step: F115 R118 I123) | any (−59 F27, −3 F8, −2 F13, −1 F17), step (−4 F27) |
| the refresh's last clock does not count toward an I/O setup when it would end the count on a step (`refresh_io_stall=step`) | F27 port ladders | waits (−53 +6 F27, −11 F13, −2 F17, −1 F8) |
| after a refresh in its setup an IN's I/O issues on a step only (`io_step_issue=step`) | `F27-push-fc-port-inb-n1-pE-w0` R104 F109 I114 (count: I113) | count (−7 F27) |
| an I/O counted out and waiting only for the bus freed on a port take's clock issues there and is not relatched (`port_ready=issue`; no refresh-off run has the state) | `F27-out-fc-empty-pE-w1` I110 R113 I122 (relatch: R111 I116 I126) | relatch (−16 F27, −3 F8) |
| an operand take while a delivered word's second byte waits latched behind a full queue (6 stored) waits for the queue's port with the EU, so a refresh on the bus holds it to the clock after its last (`refresh_take_latch=hold`) | `F13-n-none-nop8-pE-w2`: the closing LS's `MOV CL,31` starts after the NOP train at 129 on the refresh 129–133 and fetch 124–128's delivery, 6 stored and one latched, its immediate take at 132; silicon F136 (free: the shift starting at 134 on the refresh's end, F134). The 8 such starts (F13 N, F17 S, F18 A and B at 2 waits) are 2 clocks late in silicon; of the other 3,293 prefix-matched starts on a refresh's first clock 3,286 are right. −8 | an operand take no hold point unless a port byte's (`refresh_hold_take=port`) |

Refuted on the re-read (all removed from the code): the second fetch
for every beaten fetch with no I/O condition (+32 −421); the pair
only with the I/O already posted, or only at a room of 1 or more
(+7 each, fewer runs getting further). Read and left open: the END's
`MOV DW` take at H−10 (room 2, the second byte latched), where the
model fetches and silicon does not in 12 rows while 14,040 refresh-off
and 616 of 623 refresh-on rows in the same logged state are right; the
eve after a `unit_hold` wait (silicon takes a pending request after a
1-clock stall and not after 2 or 3, the stall being a fetch's last
clock at 0 waits and its wait states besides at 1–2: no row separates
the kind from the wait setting); the register shifts' 48 (the exit a
clock early at pO 1 wait, C1's E+1 request served on E+2 at no cost,
the CL 0 shifts). Stage 8 from the hand fit made no move.

**The prelude's tail from the POP PSW read** (harness extension after
the thirtieth fit, 2026-10-23; tests in `test_sim.PreludePopAnchor`
and `test_analysis.PreWindowTests`; not in `fit.json`). The model can
start at the prelude's POP PSW stack read with the queue full
(`prelude_anchor=pop`), the segment loads `pop_exit` 4 clocks after the
read's delivery (3 puts the read a clock late in every ECh cell), and
the counter's value at the read one constant per RFM and WTC
(`refresh.POP_COUNTER`, the same with and without a prelude marker);
every request from the read on is then served and `PRELUDE_COUNTER` and
`SILICON_FILL` are not read. The pre window of every refresh-off
prelude is exact with that alone (15,680 runs). Six rules, each an enum
at its old default and neutral on every run under the stand-in, make
the refresh-on windows exact in 40 of 42 cells: a refresh in POP PSW's
post-read clocks stalls them by its length less 2 (`pop_refresh=stall`);
the fetch a refresh beat keeps its reissue evaluation
(`refresh_reissue=keep`); a ModR/M form does not start in the early
fetch run (`refresh_run_modrm=wait`); the early sync is met only on the
run's first two fetches (`refresh_sync_run=two`); a register form's
take sync is met on the fetch's delivery (`refresh_sync_reg=delivery`,
visible in the window alone); and the IR is no idle slot while
`MOV r16,imm16` runs (`room_ir_imm=none`). With them the candidate
(`fit/wp40/fit-wp40-pop-candidate.json`) scores 17,572 against 17,431,
+192 −51: 153 of the 208 first-LS runs exact, the thirtieth fit's
per-cell offsets reproduced from the model's own run, and the two
stand-in tables matched by the run in 2,140 and 2,072 of 2,142
refresh-on runs. The 51 lost are after clock 0: 31 F18 A marker OUT
runs under FCh where a refresh requested inside the marker's I/O lead
is served at once in silicon and held to the issue by
`refresh_lead=closed` (opening the lead for port forms +1 −4 on the
chains), 16 under FDh where the OUT starts during a refresh served a
clock after its request, 3 F4h/FEh 0-wait runs where the fetch raised
on a beaten fetch's delivery goes a clock later, and one FFh run. Not
adopted under the "nothing lost" gate; the stand-in stays. Refuted on
the way: every beaten fetch delaying the EU (−982), the early run only
through committed back-to-back fetches (−224) or two fetches long
(−159), no early sync for any ModR/M form (−629), the sync met on the
beaten fetch's issue clock (−607), the IR's idle slot never counted
(−579 refresh-off), nor while refresh is on (−514) or class imm runs
(−167).

**The prelude tail adopted: the port form's lead, the post under a
refresh, the data-latch wait, the beaten fetch's delivery**
(thirty-first fit, the candidate's 51 losses re-read; tests in
`test_sim.RefreshPreludeTailLosses`; losses are each rule's own
single-key flip back on the final configuration over all 17,822 runs;
no refresh-off run moves):

| Rule chosen | Evidence (clocks from clock 0, or from the POP read) | Alternative replaced |
| --- | --- | --- |
| a port-form IN or OUT's I/O request (posted after the port byte's take) holds a pending refresh only on the lead's last clock: a request raised on its first clock is served at once and the I/O follows the refresh; the DW form, in the corpus always the END's OUT with the EU in HALT, keeps both clocks (`refresh_lead_port=last`) | `F18-a-out-fc-empty-pE-w0`: the marker OUT after the FCh prelude, the request at 20 on the lead's first clock, silicon X20 I25 (lead: X22 I27); `F17-s-n0-out-pE-w1`: the request at 130 on the lead's last clock, X131 I136 either way. Of 37 prefix-matched requests in a port form's lead the 33 on its first clock are served at once and the 4 on its last on the issue clock; all 281 in the DW form's are held. The whole lead open for port forms −5, the first clock open for every form −78. −32 | both lead clocks closed for every I/O form (`refresh_lead=closed`, twenty-fifth fit) |
| a fetch request a refresh takes the bus from with odd room and the word's second byte latched is not lost on the clock an IN or OUT posts its I/O after its start: it stays raised as a request no younger than the I/O, which the posted I/O holds, and runs on the lead's first clock (`refresh_drop_post=hold`) | `F18-a-out-fc-empty-pE-w2`: the marker OUT posts on 20 with the marker word delivered there and its second byte latched, the refresh 20–24; silicon X20 F27 I32 (drop: X20 I29). Of 2,008 prefix-matched lost requests only these 16 are kept in silicon; the 164 lost on a DW form's start-clock post are lost there too (the same for them −167). −15 | the loss on any clock (`refresh_drop`, fourteenth fit) |
| a pending refresh does not start while an I/O form waits at its start for the bus unit's data latch: like a fetch it waits until the latch is free, the clock the form starts, which is then the refresh's first clock (`refresh_wlatch=hold`) | `F18-a-out-fd-empty-pE-w0`: the OUT marker after the FDh prelude, its opcode in the IR from 7, its start held by the last `MOV AW,imm16`'s latch through 10, the request at 9; silicon F7 X11 F21 I24 (free: X10, the OUT held to the refresh's end, F23 I26). Every prefix-matched request pending in such a wait (17) is served on the wait's end. −17 | the refresh on any free clock during the wait |
| the fetch a refresh beat, run on the clock after it, keeps the bus unit in it on its delivery clock when it was a 3-clock fetch: a fetch the queue requests on that clock, not one committed back to back, with the word's second byte latched and neither an operand take nor an IR load on the clock, is committed there and starts on the next clock (`refresh_beat_t4=t4`) | `F13-r-rfm-f2-pE-w0` (RFM FEh), rel the POP read: the refresh 27–31 beats `MOV DS1,AW`'s fetch 32–34, `MOV AW,imm16` starts on its delivery 35; silicon F32 F36 F39 F42 (none: F32 F35 F39); `F13-r-rfw-1-pE-w0` (F4h) the same. Every prefix-matched fetch in that state at 0 waits is a clock late in silicon (4 rows); with a 4- or 5-clock beaten fetch on the delivery clock in all 1,197. For a beaten fetch of any length −226; for any fetch after a refresh a tie on the score with 2 pre windows wrong. Rests on the F4h and FEh preludes at 0 waits alone. −4 | the bus free on the beaten fetch's delivery clock |
| the counter's value at the POP read for RFM FFh at 1 wait is 79, not the 80 carried over from the clock-0 table: that window holds no refresh, and silicon's refreshes after clock 0 place the request at 21 in both runs (`refresh.POP_COUNTER`) | `F13-r-rfm-f3-pE-w1`: F20 X24 (80: X20 F28); the pO twin the same. −2 | the carried-over entry |

With the tail adopted the harness-extension rules are pinned by the
chains as well as the windows, each flipped back alone on the final
fit: `prelude_tail=standin` −209, `prelude_anchor=clock0` −36,
`pop_refresh=none` −7, `refresh_reissue=clear` −237,
`refresh_run_modrm=early` −229, `refresh_sync_run=all` −34,
`room_ir_imm=idle` −205, `wlatch_ir_at=busy` −3,006 (the refresh-off
families: under the stand-in the two had tied); `refresh_sync_reg=early`
moves no run and makes 200 refresh-on pre windows wrong, so it stays on
the window. Refuted on the re-read (removed): the whole lead open for
the port form (−5), the lead's first clock open for every form (−78),
the kept request for the DW form's start-clock post too (−167), the
beaten fetch's delivery commitment for a beaten fetch of any length
(−226), for any fetch after a refresh (a tie, 2 windows wrong), or as
a plain hold (the request lapses), and `refresh_sync_reg=second` (the
3 C runs exact with wrong windows).

**The immediate RMW's clock after its displacement, TEST imm's lookup
with a displacement, the one-byte immediate on the delivery clock**
(thirty-second fit, F22; tests in
`test_sim.ImmediateFormsPostAgainstTheRun`; losses are each rule's own
single-key flip back on the final configuration over all 19,142 runs;
nothing gains on a flip back):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| the immediate RMW spends one EU clock after its displacement's take, as the immediate store does (`rmw_imm.dadd` 1, read by the displaced forms only): its read is then posted where the store's write is, and every RMW and left-out-write cell lands in a state the store already passes (the free clocks' eve, its idle clock, the held delivery fetch) | `F22-none-l0-add_d16-pO-w0`: silicon F75 R79 F82 W85 (0: F75 F78 R81 W86), the store twin `-sti_d16-pO-w0` F75 W79 F82; `F5-push-add_m_imm_d16-k1-pE-w0` F87 R91 (0: R90). Through its first data cycle the RMW's read and the left-out write run as the store's write in 600 of 600 cells; item 1's counted state occurs in 17 cells, all an RMW's read at 0 waits, silicon idling after the fetch in all 17, and in no store at 0 waits, which with its clock sits at the eve (86 cells). −3 on F0–F21 and −179 on F22 | no clock after the take (`rmw_imm.dadd` 0) |
| a group form whose operation no ALU-op field names (F7 /0, TEST r/m,imm16) with a displacement runs TEST 84/85's fixed lookup between its ModR/M and displacement bytes (`fixed_lookup=decoder_nowait`'s `fdisp` 3, `lookup_start`), and its read then keeps only its group's own setup, the group decode after the lookup (`fixed_lookup_grp=group`) | `F22-none-l0-test_d16-pO-w0` (an odd address, no fetch on the start clock): silicon F77 R81 (none: F75 F78 R82); `-pE-w0` with a fetch at s: F72 F78 R82 (none: F72 F75 R82). Silicon's first fetch after the start is at s + 5, or s + 6 after a start-clock fetch, TEST [0C00h],AW's clocks exactly, the read at s + 9 or s + 10 as TEST [BW],imm16's; the lookup with the read's setup left at `grp_fixed=test`'s 6/5 is 1–2 late, with the lookup's clocks taken from it +21 or +51 against +108. 114 of 120 F22 runs. −109 +1 on F22, nothing on F0–F21 | the lookup for TEST 84/85 only |
| the first data request of a form with a one-byte immediate (83 /x, C6 /0), issuable on the delivery clock of a fetch that was not itself a fetch run's, goes before the fetch requested on that clock while the queue counts more than `hold_q` 3 bytes (`imm1_first=hold`, under `arbiter=b2b`) | `F22-none-l0-add8_d16-pO-w0`: the d16's fetch 75 not a run, the read's setup (`grp1` 2) ends on 78, fetch 75's delivery, with 4 counted; silicon F75 R78 F81 (none: F75 F78 R81); `F22-push-n3-add8_d16-pO-w1` F97 R101 (none: F97 F101 R105), where `ADD [BW+200h],imm16` in the same cell fetches first (F97 F101 R105). 34 of 34 such requests read first; after a fetch run (38) and behind the OUT marker's I/O with 3 counted (4) the fetch goes first; without the queue condition +34 −4, for every form's request +34 −102. Keyed on the immediate's width, a format property, and constrained by these 38 cells alone. −34 on F22, nothing on F0–F21 | the fetch requested on the clock first (`arbiter=b2b`) |

Refuted on F22 (removed): a fetch right after an I/O cycle counted as
a fetch run's for the free-clock hold (−26 on F0–F21, −22 on F22);
`rmw_imm.grp1` 1 and 3 (F15 −10 and −16, F19 −42 and −58). Open: 6
F22 runs, `TEST [BW+200h],imm16` directly after the OUT marker (pE 0
waits, pO 0 and 1 waits, k = 1 and 2): at pO the displacement is taken
on the marker I/O's issue clock and silicon holds the fetch requested
there 2 clocks past the recovery (F91 R95 against F89 R93), which
`grp_io_hold` would have to cover for the request's non-free group
clocks too; at pE silicon runs the fetch at the eve right after the
I/O where the model holds it, the refuted rule's state. Two rules for
six cells, neither adopted; the pE 0-wait k = 1 run was exact before
by the wrong head and is the one run lost.

**The I/O setup counted from the post** (thirty-third fit, from the
fitter's stage-6 ties; tests in `test_sim.IoPostFromTake`; the loss is
the single-key flip back on the final configuration over all 19,142
runs):

| Rule chosen | Evidence (clocks from t_fill) | Alternative replaced |
| --- | --- | --- |
| an I/O form's setup (`out.setup` 8, `io_count=nowait`) counts from its post, the port byte's take, not from the instruction's start with the pre added (`io_post=take`); the pre's own clocks are then not counted, so a memory wait state inside the pre costs nothing | `F13-c-out-shlcl8-pO-w1` and `F13-u-out-mulu-k1-pO-w1`: the refresh at 144–148 holds the fetch the queue wants until 149, the OUT's start clock; write-back sync 149–150, pre 151–153 with 151 the fetch's wait state, port taken and the I/O posted at 154, refresh 159–163, silicon I164 (the clock after the refresh's B3); counted from the post the eighth countable clock is 164 (154, 156–160, 163, 164), counted from the start the pre's 3 clocks yield 2 and the eleventh is 165 (−1 from there to the end). Of 34,106 I/O preloads over the corpus 34,089 count the same clocks either way (DW forms 0 = 0, port forms 3 = 3); the 17 that differ are all F13 C and U OUT runs, 15 of them off earlier for another reason | the count from the start (`io_post=start`, sixth fit): −2 (the two runs); `refresh_io_pre` (twenty-ninth fit) is read but has no effect under either value now, `dw_count`'s start-only sub-rule never applied; the arbiter's parts of `dw_count`, `dw_count_b2b` and `io_count` stay in force (−18,439, −326, −18,081 on their flips) |

**Refresh machine** (`sim/refresh.py`, 2026-10-19, from F8; tests in
`test_sim.Refresh`). A fifth machine: a 16-clock free-running timer
(`refresh_interval` 16, read off) raises one held request
(`refresh_timer=grid`); the bus unit runs a 5-clock refresh cycle when the
bus is free; the refresh goes before a pending fetch
(`refresh_fetch=refresh`) and before an issuable data or I/O request
(`refresh_data=refresh`), the second half of an odd-word pair still
first. The timer's phase per run is anchored so that the model's first
refresh at or after its own t_fill lands on silicon's (requests raised
before the fill fetch belong to the unmodelled prelude and are dropped;
ties broken by the longest agreement from t_fill), which fixes about one
event per run. Chosen on events matched before the first difference
(the usual key ties every alternative at 0 exact; stage 8 ranks by exact
runs then matched events, `RANK_MATCHED`): 516 of F8's 1,521 events
against timer start 104 / end 96, fetch-first 454, data-first 438, no EU
stall 144. The EU side is the weak part: the request is taken inside the
shift's count loop only an even number of clocks before the loop ends,
in any other clocks step at once, and while the EU waits only on odd
clocks after the start or when the bus would otherwise start a cycle
(`refresh_accept=micro_bus`, against bus 136, loop_even 357, micro 428,
micro_all 494); a refresh adds `refresh_stall` 3 to the count loop and
`refresh_stall_exec` 4 to the shift's exec clocks (`refresh_eu=shift`,
against loop 325, clocks 487), the 4 forced by the parity of the
alternation. Undecided: a refresh between back-to-back fetches (tie) and
dropping a fetch request raised on the clock a refresh takes the bus
(reproduces the `pO-w1` 128–217 gap, 491 elsewhere; kept as an option).
No refresh field is read by a refresh-off chain (a test checks this), so
every other family is unchanged. F8 is still 0/48: the first long shift
is exact (every refresh plus the M0 write) in every PUSH cell except pO
w2, and three groups block every run before its end (finding 8).

From F13 (2026-10-19, tests in `test_sim.RefreshHold`): the RFM fields
are decoded (`types.refresh_length` 3 + min(RFW, 2) clocks, the interval
`refresh_interval` << RFT, refresh on whenever RFEN is set), pinned by
the R series (`F13-r-rfm-f2-pE-w1` exact: refreshes 19 86 147). The EU
side is now `refresh_eu=hold`: at the EU's first micro-boundary after a
refresh cycle starts, the EU waits until the clock after the cycle's
last, which gives the (length − 2) stall in a 2-clock loop with no stall
integer (`refresh_stall` and `refresh_stall_exec` are no longer read).
The boundaries, applied only with refresh on: loop iteration starts
except the first (`refresh_loop_entry=open` adds the first), the shift's
last `shift_tail` 3 exec clocks as the loop's exit with a boundary
`refresh_tail_bound` 2 clocks before it ends, a boundary every 2 clocks
in the shift's exec (`refresh_exec=every2`), a clocks step's first clock
only after a wait (`refresh_clk_start=after_wait`), a port-byte take as
the only take hold point (`refresh_hold_take=port`), MULU's exec as a
count loop with odd-aligned boundaries (`refresh_mul=loop_odd`). The
request is taken on those boundaries, and while the EU waits on a posted
data request only at its first fetch-free setup clock or when the bus
unit would start a cycle (`refresh_accept=boundary_bus`:
`F8-push-empty-pE-w0` refresh 89, write 94; any waiting clock gives
100); a fetch beaten by a refresh goes right after it, ahead of a posted
I/O's hold (`refresh_after=fetch_next`: `F8-out-empty-pE-w2` fetch 100).
Against the eighth fit's rule on F8 + F13: events matched 675 + 5,364
against 520 + 3,535. Each integer is constant but has knob-dependent
best values (finding 8). `refresh_align=phase_eu`, an offset of −4..4 on
the first LS's exec per run chosen by agreement with silicon, is in the
code as a diagnostic of the prelude-phase problem and is not in
`fit.json` (it is a fit to each run, not a machine); with it F8 1/48 and
F13 56/462, without it 1/48 and 43/462 (`fit-wp17-phase_eu.json`).
Refuted on F13: dropping the fetch request a refresh beats
(`refresh_drop`, with or without re-raising it at the loop's end),
serving refreshes from the model's first chain fetch, no refresh clock
counting toward an I/O setup, `refresh_accept=boundary_micro`, MULU as a
plain or even-aligned loop. Stage 8 fits F8, F13, F17 and F18 (core grid, enum
descent, integer descent on the hold integers; the twenty-fifth fit's
enums are in its list).

From F17 (2026-10-21, tests in `test_sim.RefreshFillPhase`; losses are
each rule's own flip back on the final configuration). The timer is read
off, not aligned: a binary counter running from reset whatever RFEN
says, whose bit RFT + 3 rising (against the previous clock's selected
bit) is a request, RFEN gating it (`refresh_restart=free`, against a
restart on the write −76; `refresh_counter=edge`, against the plain grid
−4 and the RFT-switch glitch of W FDh); RFEN takes effect `rfm_delay` 3
clocks after the SFR store's issue (2 or 4 refuted by W FDh n4–n7); the
counter's value at clock 0 is a constant of the prelude's RFM and WTC
(`refresh_align=prelude`, `refresh.PRELUDE_COUNTER`, with silicon's
t_fill per prelude and parity in `refresh.SILICON_FILL` to place the
model's fill), the same in every chain sharing the prelude at both
parities (250 runs per wait setting for the ECh prelude, 231 for FCh;
the F13 R sweep's F0h, F4h, FDh, FEh and FFh entries rest on 2 runs per
wait each and are not independently checked). It scores exactly what the
per-run phase search did (F8 1/48, F13 43/462 before the EU rules; the
per-run search gained only 55 matched events), so no per-run alignment
is left in the fit, and `refresh_align` is out of the stage-8 search so
`phase_eu` cannot be chosen (on its first run the descent took it, +29
on F13: that is the first LS's start under a refresh-on prelude, still
unobserved). The SFR store occupies the bus unit for a 3-clock internal
write cycle that never reaches the pins, at the I/O block's waits, not
block 0's (`sfr_cycle=io`, −160: every refresh-off E run exact). The EU
side: a fetch request raised on a word's delivery clock with the second
byte latched is lost to a refresh taking the bus on that clock when the
room it leaves is odd, one word and the latched byte's slot
(`refresh_drop` with `refresh_drop_on=odd`, −29/−61/−40; the WP17
refutation was the even-room pE cells silicon keeps); a request lost
while a count loop runs comes back as the loop's exit starts, the clock
after its last iteration (`refresh_reraise=unit`, `reraise_off` 0:
against `queue` −29, `loop_end` −31, the last iteration's start −2;
offset 1 is identical to 0 on this corpus); an operand take of several
bytes takes a pending refresh only on its last byte's clock
(`refresh_take=last`, −12); a fetch request a refresh beat before HALT
started still runs after it, and the queue goes on fetching back to back
ahead of the waiting OUT's I/O (`halt_refresh=run`, −40: the record's
"one more fetch first"). Refuted on F17: `refresh_loop_entry=hold`
(−13), `refresh_start_hold` start/step (−68, −103), `refresh_enable=start`
with the phase known (−25), every-clock request evaluation after a
beaten refresh (no gain, removed). `refresh_tail_bound`'s knob
dependence is gone; `shift_tail` 3 still has one (k = 0 and the PUSH
marker prefer 1 on one exact run each; F8, OUT and small k on matched
events), and inside `SHL AW,CL`'s exec a request at +3/+4 is served at
+4 in 33 runs and at +6 (the loop's first clock, with a whole-cycle
hold) in 27, every first refresh after RFEN among the 27, with no state
the model carries separating the groups (finding 8).

From F18 (2026-10-21, tests in `test_sim.RefreshLadderAndPrelude`;
losses are each rule's own flip back on the final configuration). The
ladder puts the F17 split down to the previous refresh: the boundary on
the count loop's eve (exec + 4 of `SHL AW,CL`) is one only when the
previous refresh cycle started within `refresh_recent` 18 clocks less
the memory waits (`refresh_exec=every2_recent`, `refresh_recent_by=fetch`:
18 / 17 / 16 at 0 / 1 / 2 waits); a request after none, or after one
longer ago (the first after RFEN; at RFT 1 every one, the interval
leaving the previous 27 or more clocks back) waits for the loop's first
clock (`F17-d-n1-shlcl16-pE-w0` request at exec + 3 served at 103 and
the run exact, `every2` 101; −62 flipped back, F17 D −21, F18 A −16,
F18 BD −9; the flat window −7 and knob-dependent). That the window
shrinks by one clock per wait setting says it is not counted in clocks:
it is a state of the bus or refresh unit that the record has not named,
and `refresh_recent` is reported as a knob-dependent integer on matched
events (21 at 2 waits, 16 under the PUSH marker) though not on exact
runs. The register divide's exec is the multiplier's count loop
(`refresh_unit=muldiv`: `F18-b-n0-divu-pE-w0` refreshes 93 108 125
inside DIVU; −3), and the shift unit run from a memory operand takes
refreshes on its iteration boundaries through all of its shift clocks,
3 per refresh, its write's setup counting the shift (`refresh_rmw_loop=loop`,
`refresh_rmw_span=all`: `F18-b-n1-shlmcl-pE-w2` read 108, refreshes 113
128 143 160 175 193, write 198; +63 matched events, no run exact). The
prelude-marker tables are entered under (RFM, WTC, marker) in
`PRELUDE_COUNTER` and `SILICON_FILL` (FCh 48 runs per wait, FDh 16, ECh
from the AC series' 1 run per cell). Refuted on F8/F13/F17/F18:
`every2_early` (+56 −41), gating the eve boundary on the previous
refresh's own delay (+48 −21 at best), `refresh_mul=loop` (−19),
`refresh_exec=plain` (−85). Not adopted: the prelude tail run by the
model (`prelude_tail=regs/segs` with `wlatch_ir_at=start`, the segment
loads as register forms): with refresh off it reproduces silicon's
t_fill and the marker's clock in all 18 prelude cells with no fill
table, and every refresh-off run of F0–F17 as the stand-in does, so the
fill is derived there; with refresh on it is worse than the stand-in
(27 of 66 refresh-on prelude cells right against 41), the train's
refresh interplay being unmodelled (its requests go on the first free
bus clock at 1–2 waits, 154 of 154, and 0 / 1 / 3 clocks after it at 0
waits) and the counter's anchor having no fixed point in some cells.
Both enums stay in the code at their stand-in defaults. Left in the
ladder: `SHL AW,CL` at exec + 1 after a refresh served at once (served
at + 4, 3 runs per count) and at exec + 4 after one served 2 clocks
late (+ 6, 8 runs); the C1 and D1 shifts' acceptance at exec + 3 for
requests at + 1..+ 3; the multiply's and divide's first-request parity
(silicon even from the exec start, the model's `loop_odd` odd; `loop`
loses the later refreshes); a missing fetch at 0 waits after the first
refresh behind the `ES: NOP` step (`F18-b-p-n4-shlcl4-pE-w0`, no fetch
at 103 in silicon).

**From-scratch path** (sixth fit; later results below; every result in
this and the next paragraph is seeded, see the correction after them).
The stage seeds are data files in
`build/validation/v35s/chains/fit/seeds/stage{2,3,5}.json`; until
2026-10-20 the fitter rewrote a missing seed file from the hand constants
in the code, so moving the seeds aside changed nothing, and since then a
missing file means no seed and `fit --write-seeds` writes the hand values
out only when asked. Every `stageN.json` records the seed file
and its values. The stage-2 seed holds the queue storage structure (byte
latch, ModR/M latch, aborted fetch), which F0 alone cannot choose and
which is out of reach to enumerate alongside the queue options. Stage 3
ranks its survivors by the guard, then by the 264 PUSH-marked F2/F9 runs,
then by the rest of the stage (tests in `test_fit.Seeds`). `fit --all`
from DEFAULT (about 5.5 h) now keeps 584 F0 survivors including the exact
structure, picks every queue, arbiter, I/O and latch enum and integer of
the hand fit at stage 3 (one tie, arbiter settled vs b2b), matches stage
4, and settles at stage 5 on a different memory-template optimum
(`rmw_write_issue=after_step` and 11 memory integers: `pop_mem` and
`push_mem` pre/exec/post, `push_mem.grp`, `rmw.alu`, `store_imm.grp`/`post`,
`shift_imm.nx`, `in.exec`, `ea.base_disp`). It ends at 2924
(`fit-scratch.json`), 121 below the hand-steered `fit.json` (a copy is
`fit-hand.json`). Swapping `rmw_write_issue` alone loses 251 from scratch
and 329 on the hand fit, so the two are coupled minima: the fifth fit's
basin problem, now confined to stage 5. With the seventh fit's rules
`fit --all` (1.6 h) reaches 2915: stage 5 settles in the same basin
(`rmw_write_issue=after_step`, `imm_order=after_data`, the split head, the
`take` sync) and stage 6 then adds `wlatch_imm=all`, `wb_from=start` and
`port_sync=sync`; against the hand fit it loses 227 runs and gains 7. The
gap between the pipeline and the hand-steered fit is now 220 runs and
grows with every stage-5 rule; `stage1.json`–`stage7.json` belong to the
seventh fit's from-scratch run, and `fit --stage 5 --to 7` seeded with the
sixth fit reaches 3130 (it keeps the `take` sync). The eighth fit's
`fit --stage 3 --to 7` from the seventh fit's stage 2 (1.5 h) picks
`late_read` at stage 3 and keeps `halt_status` at stage 6, then loses the
same 227 runs to the stage-5 basin: 3268/4148 (2966 on the old corpus)
against the hand fit's 3478 (`fit-wp13-hand.json`; the pipeline's result
is `fit-wp13-pipeline.json`). F11 is scored in stage 3, F10 in stage 6
with the I/O revisits; `halt_status` and `out.setup0` 7 are seeded at
stage 5 because either alone breaks the END block. The ninth fit wires
F12 in as two pseudo-families: series B scores in stage 3 with F11
through a second 32-structure grid (`STAGE3_REVISIT`) after the main one,
series A in stage 6 where `start_sync`, `wlatch_imm` and the I/O enums
are enumerated under every family's guard; the ninth fit's values are
seeded at stage 3 (`seeds/stage3.json`), `shift_imm.exec0` and `cpre`
join the stage-4 integers and stage 7 includes F12. `fit --stage 3 --to 8`
from the eighth fit's stage 2 keeps every ninth-fit enum but two that tie
at stage 3 and go to the first option (`room_ir_ready`, inert at nx 0;
`shift_count`, after which stage 4 fits the shift integers around
`with_modrm`) and reaches 3522/4352 (3363/4148) against the hand fit's
3797: −288 +13, the stage-5 basin plus stage 6's `io_post=take` and
`port_sync=sync`. `fit-wp16-hand.json` and `fit-wp16-pipeline.json` keep
both; `wp17/` holds the ninth fit's pipeline run and `wp14/` the eighth
fit's.

**The first seedless run (2026-10-20, fitter only, the model unchanged).**
The stage-5 basin was diagnosed by flipping each differing enum singly
and in pairs between the hand fit and the pipeline, with the memory
integers re-descended after each flip. The hand fit is a local optimum
even over pairs (every flip loses: `rmw_write_issue` → after_step 3686,
`imm_order` → after_data 3688, the rest 3767–3796). The pipeline's stage
5 was not one: from it, `rmw_write_issue` → immediate gains 36 stage
runs only after `rmw.alu` moves to 3, and `imm_order` → after_issue is
inert as is but gains 63 once nine `rmw_imm`/`store_imm` integers move
with it; the other four enums come alive only after that. The coupling
is between an enum and its integers, not between enums, and the old grid
ranked every flip at the integers fitted for the old enums and descended
only its top two entries. The fitter now runs an enum sweep after each
stage's grids (stages 3–6): every alternative value as is, then every
alternative that makes some missed run exact with the integers of the
affected classes re-descended inside it, and at stage 3 grids over the
enums of one mechanism (storage, request, I/O, latch, arbiter) with
their gating integer on a coarse lattice; an alternative that gains
nothing as is gets one descent round before it is screened, which takes
`halt_status` together with `out.setup0` 7 without the seed. Ties on the
stage key are broken on exact runs over every recorded family, then on
events matched before the first miss, and recorded in the stage JSON.
With the seeds, this search reaches 3713/4352 from the eighth fit's
stage 2 (the old pipeline 3522; the hand fit 3798 with F8's one run):
the stage-5 basin is gone (`imm_head` split is the only stage-5
difference), and what remains is a stage-3 tie (`arbiter=settled`),
`room_ir_ready` and `shift_count`, stage 6's `io_post=take`,
`port_sync=sync`, `io_hold=posted` and `wb_from=start`, and ten
integers (`mul` pre/exec 6/20, the `push_mem`/`pop_mem` steps,
`rmw_imm` grp/rsetup, `shift_imm.exec0` 2, `cpre` 3). Without any seed,
from `Config()` defaults, the pipeline reaches 1840/4352
(`fit-wp18-scratch.json`, stage files in `wp18-scratch/`) with five
guards failed (F0w 10/20, F1 39/54, F2 61/120, F9 282/408, F11 72/132):
stage 3 ends at guard 28/38 and every later stage inherits it. The
stage-3 sweep finds `write_wait=mem_end` (+505), `io_release=post` with
`io_post=start`, `port_latch=relatch`, `wlatch_cls=port` with `wlatch`
4, `io_interlock=reg_pfx`, `io_hold=posted_b2b` and `abort_fetch=retry`
on its own, but two things it cannot reach: the END block, which runs
in every chain and scores exact or nothing, hides `io_count=nowait`,
`data_while_fetch=wait_before` and `halt_status` (each takes the guard
to 0 from where stage 3 ends, and no single stage-3 integer moved by −4
to +7 repairs it: the hand values need `out.setup` 5 → 8 with
`out.pre0`/`setup0`, and `out.setup0` 0 → 7, to move together, and only
F0w and the END block see them, jointly); and the queue storage, a
three-enum coupling (`word_latch=byte_d` with `latch_read=commit` and
`latch_hold`) with no single-step path from the counted latch the
search takes early on a tie, which F2 and F9 PUSH decide only once the
request rule and the I/O mechanism are right. The seeds therefore stay:
the stage-2 storage seed and the stage-3 I/O values are what the chain
families cannot order, and the record's from-scratch claims before this
date were seeded runs. The tenth fit wires F14 in as three
pseudo-families (T and G at stage 5 through a `FORM_REVISIT` grid, O at
stage 6 through `OUT_REVISIT`) with its values in the stage-3 and stage-5
seeds; the seeded `fit --stage 5 --to 8` from the eighth fit's stage 4
(3 h) keeps every tenth-fit enum but `wlatch_mul` (take) and reaches
3837 against the hand fit's 3933 (`fit-wp19-hand.json`,
`fit-wp19-pipeline.json`; stage files in `wp19/`), the known gap
(`arbiter=settled`, `room_ir_ready`, `shift_count`, stage 6's I/O
revisits, `mul.grp` 1, the `push_mem`/`pop_mem` steps, `shift_imm.exec0`
2). The eleventh fit adds F15 A/P/K at stage 5 (a 192-structure
`F15_REVISIT` grid, also in the stage-5 sweep) and F15 O at stage 6
(`sync_io`, `io_busy_start` in `OUT_REVISIT`), its values in the stage-5
seed; the seeded `fit --stage 5 --to 8` from the eighth fit's stage 4
(5 h) keeps every eleventh-fit enum but `push_mem_write` and reaches
3929 on F0–F12, F14 600, F15 548 against the hand fit's 4007/634/666
(`fit-wp20-hand.json`, `fit-wp20-pipeline.json`, stage files in `wp20/`,
the tenth fit's in `wp19b/`). The twelfth fit adds F16 S at stage 3
(`count_latch` in `STAGE3_REVISIT` and the stage-3 and stage-4 sweeps),
F16 R/P at stage 5 (`F16_REVISIT`, the stage-5 sweep) and F16 L at
stage 6 (`io_exec` in `OUT_REVISIT`), its values in the stage-3 and
stage-5 seeds; the seeded `fit --stage 3 --to 8` from the eighth fit's
stage 2 (5.8 h) reaches 3964 on F0–F12 (F8 0/48), F14 613, F15 528,
F16 768 against the hand fit's 4049/655/745/888, −491 with 27 runs
the hand fit lacks (`fit-wp21-hand.json`, `fit-wp21-pipeline.json`,
stage files in `wp21/`, the eleventh fit's in `wp20b/`). Its stage 3
chose `request_eval=every_clock` for the first time (every earlier
run on_change), ending with F1 store 0/3 and F16 S 210/354, and stage
5 then settled in another integer basin (`mul.pre` 6, `mul.grp` 1,
`pop.setup` 4, `push_mem.exec` 1), dropped `abort_unit` until the
stage-6 sweep restored it, and kept `push_mem_write=after_exec` and
`dest_route=d0ro_swap`. Its 27 gains are the register MULU at pE
(F14 G, F15 O, the F16 L PUSH twin, F3 `mulu_dw` k1), from `mul.pre`
1 / exec 29 / wb 2 with its other differences; on the hand fit that
set is +27 −40 even with a register-only pre, so it is a lead for the
OUT frame, not a value. The thirteenth fit adds its OUT-frame enums to
stage 6 (`OUT_REVISIT2`) and `slot_fetch`/`disp_take` to stage 5
(`F16_REVISIT`), its integers to `REG_INTS` and the stage-5 seed; the
seeded `fit --stage 5 --to 8` from the eighth fit's stage 4 (4.6 h)
keeps every thirteenth-fit enum and reaches 3977 on F0–F12 (F8 0/48),
F14 640, F15 555, F16 826, F13 46 against the hand fit's
4130/691/811/988: +3 −625 (`fit-wp22-hand.json`,
`fit-wp22-pipeline.json`, stage files in `wp22/`, the twelfth fit's in
`wp21b/`). Its losses are the start point's: the eighth fit's stage 4
predates `count_latch`, `shift_count=late`, `exec0` and `cpre` and the
stage-5 seed does not carry them (F16 S −80, F12 B −10); stage 5 again
settled in the `pop.setup` 4 / `push_mem` basin (F15 P −158, F15 K
−30); and it chose the refresh `phase_eu` alignment, the 3 F13 gains,
which this record keeps out of the fit. Three guards fail in it (F12 B
38/48, F15 K 90/120, F16 P marker-less 24/48). The stage-5 seed, or
the start file, has to carry the stage-3/4 rules of the tenth to
twelfth fits before the pipeline can be compared again. The fourteenth
fit wires F17 into stage 8 with `refresh_align` fixed; `fit --stage 8`
from the hand fit changes nothing (338/1308 on F8 + F13 + F17, every
alternative lower, `fit-wp23-stage8.json`); the thirteenth fit's files
are in `wp22b/`. The fifteenth fit adds F18 and `refresh_recent` to
stage 8; `fit --stage 8` from the hand fit again chooses nothing new
(572/2472 on F8 + F13 + F17 + F18, guard 6,619/6,890 unchanged, every
alternative lower or tied, `fit-wp24-stage8.json`; `refresh_hold_take=hold`
scores 554 exact with 1,740 more matched events, worth a look); the
fourteenth fit's files are in `wp23b/`. The sixteenth fit adds F19 (I
to stage 5, D to stage 6) and its enums and integers to the stage-5
and stage-6 grids, and rewrites the stage-5 seed with them;
`fit --stage 5 --to 7` from the hand fit (5.8 h, 8 jobs) improves no
stage's count (stage 5 3340/3624 before and after) but drifts along
objective ties (`arbiter` settled, `modrm_commit` step, `port_sync`
sync, `io_hold` posted, `wlatch_ir` False, `wlatch_mul` take, `sync_io`
issue, `dest_route` d0ro_swap, `load_alu.wb` 2) and loses 51 outside
the stage families for 7 gained (8274 against 8318 on the corpus,
`fit-wp25-descent.json`): the stage objectives do not see F15, F16 and
F19 D for those enums. The hand fit is kept; the fifteenth fit's files
are in `wp24b/`. The seventeenth fit adds the whole-corpus guard the
sixteenth asked for (`--corpus-guard family|run|off`, default family;
tests in `test_fit.CorpusGuard`): a move of the descent, the enum sweep
or the stage grid is accepted only if no family of the recorded corpus
loses exact runs against the stage's input configuration (`CORPUS_REF`,
the input before its seed: against the current configuration the
stage-5 seed's `ea.base_disp` 0 trapped the first run at 1, the climb
to 2 refused for one F4 run though the stage net was +44). F20 is in
stage 6 and the new enums in its grid; `knob_dependence` gained the `n`
knob. `fit --stage 5 --to 7` from the hand fit: stage 5 moved only the
seeded `ea.base_disp` back to 2 (3340/3624 as the hand fit, the sweep 0
moves, the guard refusing 562 of 612); stage 6 was stopped after 5 h
partway through with one inert tie taken (`arbiter` settled, 11429
against 11429 over every family); stage 7 was not run
(`stage5-wp26-descent.json`). The sixteenth fit's files are in
`wp25b/`. The eighteenth fit ran `fit --stage 5` from the hand fit under
the family guard (8 jobs, 2 h 13 min): grids of 9216, 48, 288, 160, 8
(the new `EA_REVISIT`) and 30 structures, then a sweep of 55
alternatives with 107 integers re-descended inside. It chose nothing
(stage 6286/7200, guard 2565/2582, 603 of 648 moves refused by the
guard, one tie); `fit-wp27-stage5.json` is identical to the hand fit
and `stage5-wp27-descent.json` is the stage file; stages 6 and 7 were
not run. The stage-5 seed now carries the eighteenth fit's values and
`ea.base_disp` 2 (the old seed is in `wp26b/seeds`). The seventeenth
fit's files are in `wp26b/`. The nineteenth fit added the stage-5 grid
`DISP_REVISIT` (its four enums, also in the sweep) and the eight
`dfloor` integers; `fit --stage 5` from its hand fit under the family
guard ran the six grids and the sweep (37 enums, 115 integers) and
moved nothing (6755/7200 on its families, guard 2565/2582, one tie on
exact runs, `odd_split`, resolved by the guard); `fit.json` is
byte-identical to `fit-wp28-hand.json`. The twentieth fit added the
stage-5 grid `FREE_REVISIT` (its four enums, also in the sweep) and
`disp_floor`'s third option to `DISP_REVISIT`; `fit --stage 5` from its hand fit under the family guard ran the seven
grids and the sweep (9,216 structures, 10,387 s) and chose nothing
(6950/7200 on its families, guard 2565/2582, 656 of 697 descent moves
refused, one tie on exact runs, `odd_split`, resolved by the guard);
`fit.json` is byte-identical to `fit-wp29-hand.json`. The stage-5 seed
now carries this fit's enum values (the old seed is in `wp28b/seeds`).
The twenty-first fit added the stage-5 grid `WP30_REVISIT` (its four
enums, also in the sweep); `fit --stage 5` from its hand fit under the family guard ran the eight
grids and the sweep (9,216 structures, 10,792 s) and chose nothing in
any grid or in the sweep (7068/7200 on its families, guard 2565/2582,
one tie on exact runs, `odd_split`, resolved by the guard); `fit.json`
is byte-identical to `fit-wp30-hand.json`. The stage-5 seed carries
this fit's enum values (the old seed is in `wp29b/seeds`).
The twenty-second fit added the stage-5 grid `WP31_REVISIT` (its six
enums, also in the sweep) and the `sidle` integers to `MEM_INTS`; `fit
--stage 5` from its hand fit under the family guard ran the nine grids
and the sweep (12,016 s) and chose nothing in any grid or in the sweep
(7184/7200 on its families, guard 2565/2582, one tie on exact runs,
`odd_split`, resolved by the guard; its knob report finds no integer
whose best value differs by parity, waits, k, marker, family or n);
`fit.json` is byte-identical to `fit-wp31-hand.json`. The stage-5 seed
carries this fit's values (the old seed is in `wp30b/seeds`). The twenty-third fit added the grid `WP32_REVISIT` (its six enums,
also in the sweep); the fitter's stage 4 (F3), whose grid was empty before, now carries it
with `reg.nx` in {1, 2} (288 structures), and a stage-6 grid after
`F20_REVISIT` carries it for F19 D and F20. `fit --stage 4` from the
hand fit under the corpus guard (847 s, 32 of 35 moves refused) chose
the two ties, `nop_hold=io` and `abort_latched=full` (+0 −0 over the
whole corpus), and the hand fit is kept as `fit.json`; stage 6 was not
run (its grids take hours) and is due when the fitter is next touched.
The seeds carry this fit's values (the old seeds are in `wp31b/seeds`).
The twenty-second fit's files are in `wp31b/`, the twenty-first's in
`wp30b/`, the twentieth's in `wp29b/`, the nineteenth's in `wp28b/`,
the eighteenth's in `wp27b/`. The twenty-fourth fit added the stage-5
grid `WP33_REVISIT` (three enums, also in the sweep) and a stage-6 grid
`WP33_STAGE6` (`abort_reg_end`, F16 L being scored in stage 6; not
run); `fit --stage 5` from its hand fit under the corpus guard
(13,390 s, 906 of 944 moves refused, 7197/7200 on its families, guard
2582/2582) moved no integer and chose `ea_floor=False`, a tie (+0 −0
over the whole corpus: the twentieth fit's mod 00 floor is inert under
the rules adopted since), recorded with the `odd_split` tie; the hand
fit is kept as `fit.json`, the fitter's output in the scratchpad. The
twenty-third fit's files are in `wp32b/`. The twenty-fifth fit put its
enums in stage 8's search list; `fit --stage 8` from its hand fit
(5.6 min with the result cache) chose `refresh_exec=every2_early`
alone (+96 −61, the trade the fifteenth fit refuted), not adopted;
`fit.json` is the hand fit, the fitter's output in
`fit-wp34-stage8.json`, and its knob report finds `refresh_recent` 18
preferring 15 and 19 by wait setting (item 8 g). The twenty-fourth
fit's files are in `wp33b/`. The twenty-sixth fit added its three
enums to stage 8's list; `fit --stage 8` from its hand fit chose no
move (1269/2472 refresh-on exact, guard 15347/15350; its alternatives
1205, 1200 and 1156); `fit.json` is the hand fit, the fitter's output in
`fit-wp35-stage8.json`. The twenty-fifth fit's files are in `wp34b/`. The twenty-seventh fit
added its six enums to stage 8's list and `REFRESH_SEED`; `fit --stage
8` from its hand fit chose no move (1708/2472 refresh-on exact, guard
15347/15350; `wlatch_ir_at=start` ties); `fit.json` is the hand fit.
The twenty-sixth fit's files are in `wp35b/`. The twenty-eighth fit
added its seven enums to stage 8's list and `REFRESH_SEED`; `fit
--stage 8` from its hand fit chose nothing (1835/2472 on its set with
the controls, guard 15347/15350; the alternatives 1752 to 1835,
`refresh_wbsync=wait` the tie); `fit.json` is the hand fit, the
fitter's output in `fit-wp37-stage8.json`. The twenty-seventh fit's
files are in `wp36b/`. The twenty-ninth fit added its four enums to
stage 8's list and `REFRESH_SEED`; `fit --stage 8` from its hand fit
made no move (2069/2472 on its set with the controls, guard
15347/15350); `fit.json` is the hand fit, the fitter's output identical
to it in `fit-wp38-stage8.json`. The twenty-eighth fit's files are in
`wp37b/`. The thirtieth fit added its two enums to stage 8's list and
`REFRESH_SEED`; `fit --stage 8` from its hand fit made no move
(2084/2472 on its set with the controls, guard 15347/15350; ties
`refresh_timer` start against end, `refresh_exec` every2 against
every2_early, `refresh_recent_by=clocks`, `wlatch_ir_at=start` and
`refresh_eve=both`, none of them read); `fit.json` is the hand fit, the
fitter's output identical in `fit-wp39-stage8.json`. The twenty-ninth
fit's files are in `wp38b/`. The harness extension's six enums are in
stage 8's list and `REFRESH_SEED` at their old values; stage 8 from
the hand fit made no move with them (they tie); the candidate's stage-8
run is in `fit/wp40/`. The pre window is scored by `score --pre`,
never part of a run's exactness. The thirty-first fit put the tail's
values and its four enums in `REFRESH_SEED` and stage 8's list; stage
8 from its hand fit made no move (2295/2472 on its set with the
controls, guard 15347/15350; its output byte-identical to the hand
fit, `fit-wp41-stage8.json`); the thirtieth fit's files are in
`wp40b/`. A test now runs the generated chain on which the lead rule's
first version over-filled the queue. The thirty-second fit added F22
to stage 5's families and `TIE_FAMILIES`, `rmw_imm.dadd` to its
integers and an eleventh grid `WP43_REVISIT` (its two enums, also in
the sweep); `fit --stage 5` from its hand fit under the family guard
(8520 runs, 28,874 s) chose nothing in every grid (8514/8520, guard
2582/2582, the `odd_split` tie); its written output differed from the
hand fit by `ea_floor` alone, a tie (the twentieth fit's floor inert
since the twenty-fourth), and the hand fit is kept as `fit.json`. The
thirty-first fit's files are in `wp41b/`. F22 has four score columns
(0 and 1 waits), which the scratchpad's run tally reads separately.
`fit --stage 6` from the thirty-second hand fit under the family guard
(Facts, "The fitter's stage 6 under the family guard") chose nothing
in any grid, the sweep or polish; its first attempt was killed by the
out-of-memory killer at 55 GB in the storage grid, after which the
result cache was bounded (`--cache-limit`, twice the limit in results,
emptied at every grid, logged at each grid's end) and `--grid NAME`
added to resume stage 6 at a grid; the second attempt peaked at 20.1 GB
in a 40 GB `systemd-run` scope. Its ties, scored as single flips of
the hand fit over every family, gave the thirty-third fit
(`io_post=take`, +2 −0); the fitter's own output scores the same as
that hand fit. `STAGE3_SEED` and `seeds/stage3.json` carry `take`.
The thirty-second fit's files are in `wp43b/`, the thirty-third's in
`wp45b/`. Since 2026-10-26 the adopted fit is tracked as
`validation/v35s/chains/fit.json` (`adopt PATH` writes it; `score` and
`sim` default to it) so a checkout rescores without `build/`. F23 and F25
were generated and acquired on 2026-10-27 (chains-F23-w0..2, chains-F25-w0..2,
948 runs, read in the facts section above) and are not yet modelled:
`families.UNMODELLED` names them, the simulator has no template for their
forms, the tests that simulate every family skip them, the tie-break and
corpus guard leave them out, and the normaliser's expected-access walk
pushes `writes` and pops `reads` words per push, pop and call form (PUSH R,
POP R, CALL and RET) and matches a marker to its own instruction's cycle
(the balanced-body fix above); F24 is reserved for the string forms. The
RTL conversion's first tools landed the same day: `replay` runs chains
through the Verilator model lane and `score --rtl` scores silicon, model
and RTL three ways (docs/v35s-hdl-plan.md, Phase B); `freeze` generates
`sim/frozen/`, the simulator with every structural choice resolved to the
tracked fit (identical on all 19,142 runs, `freeze --verify`), and
`statestats` reduces the per-clock state over the corpus for the RTL spec
(docs/v35s-chain-rtl-spec.md, Phase A). On 2026-10-28 `rtlgen`
generates `fpga/v35s/core/v35_chain_params.svh` from the tracked fit (the
integers, the EA table and 204 templates, 212 since C3; `rtlgen --check` and
`test_rtlgen` diff it), and the first RTL machine, the bus unit
`fpga/v35s/core/v35_biu.sv`, replays the frozen model's request stream
(`rtl_vectors.py`) exactly over all 22,068 runs (HDL plan, Phase C1), and
the second, the queue `fpga/v35s/core/v35_queue.sv`, reproduces the frozen
queue's state after every touch by the other machines over all 23,612 runs,
alone and together with the bus unit (`rtl_vectors.py --queue`, `--joint`;
Phase C2), and the third and fourth, the decoder and the EU
(`fpga/v35s/core/v35_decoder.sv`, `v35_eu.sv`), reproduce the frozen
decoder's and EU's state after every phase of every clock on every
refresh-off run (19,850; the arbiter and the register file scripted,
refresh on not modelled), alone and with the queue and bus unit
(`--eu`, `--joint3`; Phase C3; the queue gained the thirty-seventh fit's
`grp_disp` stamp the same day), and the fifth, the arbiter
(`fpga/v35s/core/v35_arbiter.sv`), runs with the other four as one core
(`v35_chain_core.sv`: the clock's phase chain and its fixpoint in RTL,
through settle registers) exact on the same 19,850 runs, with only the
operand records, the write data and the memory supplied from outside
(`--core`; Phase C4), and since 2026-10-29 the refresh too: a sixth
module, the refresh controller (`v35_refresh.sv`), with the arbiter's and
the EU's refresh rules in RTL, runs every run of the corpus that has no
string form exact against the model, 23,678 of 24,524 (the 846 F24 runs
with one are not modelled: the include's step tables leave the string
classes out until HDL plan Phase E item 3), model-exact 22,837 = RTL-exact
(`--core`; Phase C5); and since 2026-10-30 the register file, the operand
record and the write data are the RTL's own (`v35_operands`,
`v35_execute` in `v35_eu.sv`; Phase D1), the same 23,678 runs exact under
the thirty-ninth fit with every start's record, register file and datum
checked, only the code window and the memory still served from outside; and
since the same day the EU computes (Phase D2): the ALU and the full PSW with
nuV30's semantics, real read and write data and the segment registers,
checked against a functional reference (`funcref.py`: every start's register
file and every cycle's datum, 91,980 data cycles matching silicon on their
lanes) and the SingleStepTests V20 suite (1,651,237 pass, 0 fail through the
RTL), the timing gates unchanged; and since the same evening the string forms run in RTL and
the RTL has the fortieth fit's mechanisms (Phase E item 3 and the catch-up, WP75): the whole
corpus of 26,234 runs over 33 lists exact against the model, 0 not modelled, model-exact
24,710 = RTL-exact, a REP form's count from CW and a compare's exit from the RTL's own data; and
since the same night the RTL has the forty-first fit's nine mechanisms and REPC/REPNC (WP77):
26,234 exact against the model, model-exact 25,423 = RTL-exact, rtlgen reading the frozen package's
fit so that live model edits no longer touch the include (the F32/F33 classes unbuilt); and
since later the same day the RTL builds the F32/F33 classes too (WP79, HDL plan "The 0F page
and the register miscellany built"): `UNBUILT_CLASSES` empty, the whole corpus of 28,142 runs
over 35 lists exact against the model, model-exact 26,643 = RTL-exact, funcref 0 disagree. Since
2026-10-31 the chain core also runs in the Verilator model lane from /RESET with nothing
scripted (WP82: `build_sim.sh direct chain`, `acquire --backend sim --core chain`, `replay
--core chain --score`; HDL plan "The chain core in the model lane"): every refresh-off
family RTL = model on every run with the pre window exact, the six refresh-on families 2,228
runs short for two things the model has non-causally, the counter's phase at the POP read and
the `refresh_any` lookahead (Facts "The prelude from reset against the chain core"). The
state row's `pc` is a chain offset like `ir` since the same day. The same
change fixed `run_classes` leaving the prelude tail's classes out of the
result cache's key (Facts, "The fitter's stage 6 under the family guard");
stage 4 and a whole-corpus descent of `REG_INTS` re-run with the corrected
key moved nothing (same section; `stage4.json` is that re-run's). Since
2026-10-27 `TIE_FAMILIES` is `families.FAMILIES` (a test pins it), so the
refresh-on families F13, F17 and F18 are in the tie-break and a tie is a
tie on every family; before, a tie that differed only there was decided
by the grid's order. Under the full set the thirty-third fit's tie-break
count is 18,961 exact / 261,277 matched; of the stage-4 re-run's seven
recorded ties two flips (`abort_latched=any`, `room_ir_ready=False`)
stay exact ties on every family and the other four (`io_take_nx=False`
−64, `modrm_port=False` −10, `nop_hold=none` −8, `nop_hold=io` −2) lose
exactly what they lost on the old set, so for those the refresh-on
families change nothing.

Dropped with evidence in the fourth fit: `mem_order` lead/lead_ea and EA
clocks as setup (held the back-to-back fetch), a run-aware b2b arbiter
(broke F1 store), flag-at-end, pending_pre and pending_end take syncs,
counting the latched byte on double reads (deadlock), aborting a fill or
follow-on request (all broke F0). Earlier: no latch or a counted latch
(F9 172, F2 30); an uncounted whole-word latch (F0 0/18); any read holding
the port (F9 351, F2 53, F6 135); counting the IR as room always, never,
or on delivery or idle clocks alone; sampling the request before the
takes; one queue read per clock (F0 9/18); the first fit's partial arrival
count (374 runs overflow). Retired: `capacity`, `fetch_when_free`,
`inflight_bytes`, `arrive_count`, `request_mode`.

Per-class costs are in `fit.json`. Names: `pre` clocks before the operand
take, `pre0` the same for a form with no operand byte, `exec` clocks after
it, `setup` clocks from posting a data request to its earliest issue,
`setup_free` how many of them must be fetch-free, `post` clocks after the
last data cycle, `grp`/`grp_free` the group-opcode extra setup, `nx`
clocks after the last operand take before the next opcode loads,
`wb`/`wbsync` a result write-back running past the instruction's end and a
class waiting for it. Fourth-fit values: `load`/`store` pre 0, pre0 2; EA
2 for ModR/M modes, 0 direct; `rmw` grp 4/3; `push_mem` grp 4/3; `load_alu`
and `rmw_imm` grp 4/2; `mul` and `pop_mem` grp 3; `store_imm` grp 1;
`shift_cl` exec 7, loop 2; `pop` setup 7, setup_free 3; the rest as in the
third fit. Sixth-fit moves: `mul.grp_free` 3, `rmw_imm` grp 3, pre 0,
post 0 (+24 runs, nothing lost); `in.post` 2; the four write-backs 0.
Seventh-fit moves: `rmw_imm` grp_free 1, alu 3, setup_free 0; `store_imm`
grp 3, grp_free 1; `in.setup0` 7, `out.setup0` 8, `out.pre0` 0. Eighth
fit: `out.setup0` 7. Ninth fit: `shift_imm.nx` 0 (was 10), `exec0` 5
(the D1 form; `exec` 6 for the count-byte form), `cpre` 2; `out.wbsync0`
0 (the DW form; `wbsync` 1), `out.nx` 0. Tenth fit: `load_alu` grp 4,
grp_free 3, dclk 2; `rmw` dclk 2, grpcl 3; `mul` grp 4, mexec 29, mwb 2;
`div` grp 4, grp_free 3, pre 0, mexec 37, mwb 2. Eleventh fit: `pop_mem`
rsetup 7, rfree 3, setup 4, pre 2, grp 0; `load_alu` fgrp 2, fgrp_free 2,
fdisp 5; `rmw_imm.grp1` 2; `rmw.setup_free` 3; `reg.nx` 2. Twelfth fit: `mul`
smexec 49, bmexec 21, mtail 3; `div` smexec 58, exec 39, mtail 3.
Thirteenth fit: `mul` and `div` wb 2, hphase 2, mtail 2 (recounted);
`shift_imm.hphase` 1, `shift_cl.hphase` 2; `pop_mem.setup_free` 1.
Sixteenth fit: `store_imm` istart 5, grp1 2; `rmw_imm.istart` 5.
Seventeenth fit: `io_b2b_q` 3. Eighteenth fit: `ea.base_index_disp16` 3,
`store_imm.dadd` 1; `load_alu.fdisp` 4 and `pop_mem.setup_free` 0 refitted.
Nineteenth fit: `dfloor` 2 for every memory class. Twentieth and
twenty-first fits: no new integer. Twenty-second fit: `rmw_imm.sidle` 2
and `rmw.sidle` 2 (each pinned, 1 and 3 losing 19 and 33);
`load_alu.fdisp` 3 (from 4, with `lookup_start`). Twenty-third fit:
`reg.nx` 1 (from 2, with `io_take_nx`; 2 with the rule loses 13).
Twenty-fourth to twenty-sixth fits: no new integer. Twenty-seventh
fit: `mul.rexit` 8 and `div.rexit` 6, the exit's clocks (the divide's
scanned: 8 loses 11). Twenty-eighth and twenty-ninth fits: no new integer; from the
twenty-ninth, `refresh_recent` 18 is no longer read. Thirtieth fit: no
new integer. Thirty-first fit: `pop_exit` 4 (the clocks from the POP
PSW read's delivery to the first segment load's start; 3 puts the read
a clock late in every ECh cell) and the counter at the read per RFM and
WTC (`refresh.POP_COUNTER`, read off); `PRELUDE_COUNTER` and
`SILICON_FILL` are no longer read. Thirty-second fit: `rmw_imm.dadd` 1
(the store's clock after the displacement's take, given to the
immediate RMW). Thirty-third fit: no new integer; `refresh_io_pre` is
read but has no effect under either of its values.

### Scorecard (exact runs / runs, thirty-third fit, 2026-10-26)

PUSH, store and marker-less runs (F17 E is the refresh-off control, F17 W
the write moved with ECh, FCh and FDh together; F18 A ECh is the
refresh-off control with the prelude marker, split by that marker):

| Family | Marker | pE w0 | pE w1 | pE w2 | pO w0 | pO w1 | pO w2 | Total | 32nd fit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F0 | — | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 18/18 | 18 |
| F0w | — | 10/10 | | | 10/10 | | | 20/20 | 20 |
| F1 | push | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 18/18 | 18 |
| F1 | store | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 18/18 | 18 |
| F2 | push | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 60/60 | 60 |
| F3 | push | 70/70 | 70/70 | 70/70 | 70/70 | 70/70 | 70/70 | 420/420 | 420 |
| F4 | push | 38/38 | 38/38 | 38/38 | 38/38 | 38/38 | 38/38 | 228/228 | 228 |
| F5 | push | 70/70 | 70/70 | 70/70 | 70/70 | 70/70 | 70/70 | 420/420 | 420 |
| F6 | push | 48/48 | 48/48 | 48/48 | 48/48 | 48/48 | 48/48 | 288/288 | 288 |
| F7 | push | 36/36 | 36/36 | 36/36 | 36/36 | 36/36 | 36/36 | 216/216 | 216 |
| F8 | push | 3/4 | 4/4 | 3/4 | 2/4 | 4/4 | 3/4 | 19/24 | 19 |
| F9 | push | 34/34 | 34/34 | 34/34 | 34/34 | 34/34 | 34/34 | 204/204 | 204 |
| F9 | none | 34/34 | 34/34 | 34/34 | 34/34 | 34/34 | 34/34 | 204/204 | 204 |
| F10 | push | 29/29 | 29/29 | 29/29 | 29/29 | 29/29 | 29/29 | 174/174 | 174 |
| F10 | none | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 | 30/30 | 30 |
| F11 | none | 22/22 | 22/22 | 22/22 | 22/22 | 22/22 | 22/22 | 132/132 | 132 |
| F13 S | none | 31/31 | 31/31 | 31/31 | 31/31 | 31/31 | 31/31 | 186/186 | 186 |
| F13 S0 | none | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 36/36 | 36 |
| F13 C | push | 12/13 | 12/13 | 12/13 | 10/13 | 10/13 | 9/13 | 65/78 | 65 |
| F13 U | push | 2/2 | 2/2 | 2/2 | 2/2 | 1/2 | 2/2 | 11/12 | 11 |
| F13 U, N | none | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 12/12 | 12 |
| F13 N | push | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 6/6 | 6 |
| F13 R | none | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 7/7 | 42/42 | 42 |
| F17 E | none | 25/25 | 25/25 | 25/25 | 25/25 | 25/25 | 25/25 | 150/150 | 150 |
| F17 W | none | 23/24 | 22/24 | 21/24 | 23/24 | 20/24 | 23/24 | 132/144 | 132 |
| F17 S | none | 51/52 | 50/52 | 50/52 | 52/52 | 51/52 | 50/52 | 304/312 | 304 |
| F17 D | none | 16/16 | 16/16 | 16/16 | 16/16 | 16/16 | 16/16 | 96/96 | 96 |
| F17 P | none | 7/10 | 2/10 | 2/10 | 10/10 | 7/10 | 10/10 | 38/60 | 38 |
| F17 C | push | 3/6 | 6/6 | 6/6 | 5/6 | 5/6 | 4/6 | 29/36 | 29 |
| F18 A ECh | push | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 48/48 | 48 |
| F18 A FCh, FDh | push | 16/16 | 16/16 | 16/16 | 16/16 | 15/16 | 16/16 | 95/96 | 95 |
| F18 AC | push | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 6/6 | 6 |
| F18 B | none | 104/112 | 111/112 | 106/112 | 105/112 | 112/112 | 107/112 | 645/672 | 645 |
| F18 BD | none | 32/32 | 32/32 | 32/32 | 32/32 | 32/32 | 32/32 | 192/192 | 192 |
| F19 I | push | 42/42 | 42/42 | 42/42 | 42/42 | 42/42 | 42/42 | 252/252 | 252 |
| F19 I | none | 21/21 | 21/21 | 21/21 | 21/21 | 21/21 | 21/21 | 126/126 | 126 |
| F19 D | push | 45/45 | 45/45 | 45/45 | 45/45 | 45/45 | 45/45 | 270/270 | 270 |
| F19 D | none | 22/22 | 22/22 | 22/22 | 22/22 | 22/22 | 22/22 | 132/132 | 132 |
| F20 R | push | 165/165 | 165/165 | 165/165 | 165/165 | 165/165 | 165/165 | 990/990 | 990 |
| F20 R | none | 110/110 | 110/110 | 110/110 | 110/110 | 110/110 | 110/110 | 660/660 | 660 |
| F20 N | push | 20/20 | 20/20 | 20/20 | 20/20 | 20/20 | 20/20 | 120/120 | 120 |
| F21 | push | 220/220 | 220/220 | 220/220 | 220/220 | 220/220 | 220/220 | 1320/1320 | 1320 |
| F21 | none | 156/156 | 156/156 | 156/156 | 156/156 | 156/156 | 156/156 | 936/936 | 936 |
| F22 | push | 110/110 | 110/110 |  | 110/110 | 110/110 |  | 440/440 | 440 |
| F22 | none | 110/110 | 110/110 |  | 110/110 | 110/110 |  | 440/440 | 440 |
| F12 A | push | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 24/24 | 24 |
| F12 A | pushout | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 24/24 | 24 |
| F12 A | out | 16/16 | 16/16 | 16/16 | 16/16 | 16/16 | 16/16 | 96/96 | 96 |
| F12 B | push | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 | 12/12 | 12 |
| F12 B | none | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 48/48 | 48 |
| F14 T | push | 41/41 | 41/41 | 41/41 | 41/41 | 41/41 | 41/41 | 246/246 | 246 |
| F14 T | none | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 24/24 | 24 |
| F14 G | push | 18/18 | 18/18 | 18/18 | 18/18 | 18/18 | 18/18 | 108/108 | 108 |
| F14 O | push | 11/11 | 11/11 | 11/11 | 11/11 | 11/11 | 11/11 | 66/66 | 66 |
| F14 O | none | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 | 24/24 | 24 |
| F15 A | push | 17/17 | 17/17 | 17/17 | 17/17 | 17/17 | 17/17 | 102/102 | 102 |
| F15 A | none | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 18/18 | 18 |
| F15 P | push | 17/17 | 17/17 | 17/17 | 17/17 | 17/17 | 17/17 | 102/102 | 102 |
| F15 P | none | 17/17 | 17/17 | 17/17 | 17/17 | 17/17 | 17/17 | 102/102 | 102 |
| F15 K | push | 20/20 | 20/20 | 20/20 | 20/20 | 20/20 | 20/20 | 120/120 | 120 |
| F15 O | push | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 | 72/72 | 72 |
| F15 O | none | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 48/48 | 48 |
| F16 R | push | 49/49 | 49/49 | 49/49 | 49/49 | 49/49 | 49/49 | 294/294 | 294 |
| F16 P | push | 16/16 | 16/16 | 16/16 | 16/16 | 16/16 | 16/16 | 96/96 | 96 |
| F16 P | none | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 48/48 | 48 |
| F16 L | push | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 | 15/15 | 90/90 | 90 |
| F16 S | none | 59/59 | 59/59 | 59/59 | 59/59 | 59/59 | 59/59 | 354/354 | 354 |

OUT markers (fitted from the fifth fit on):

| Family | pE w0 | pE w1 | pE w2 | pO w0 | pO w1 | pO w2 | Total | 32nd fit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 18/18 | 18 |
| F2 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 60/60 | 60 |
| F3 | 70/70 | 70/70 | 70/70 | 70/70 | 70/70 | 70/70 | 420/420 | 420 |
| F4 | 38/38 | 38/38 | 38/38 | 38/38 | 38/38 | 38/38 | 228/228 | 228 |
| F5 | 70/70 | 70/70 | 70/70 | 70/70 | 70/70 | 70/70 | 420/420 | 420 |
| F6 | 48/48 | 48/48 | 48/48 | 48/48 | 48/48 | 48/48 | 288/288 | 288 |
| F7 | 36/36 | 36/36 | 36/36 | 36/36 | 36/36 | 36/36 | 216/216 | 216 |
| F8 | 2/4 | 3/4 | 2/4 | 1/4 | 2/4 | 0/4 | 10/24 | 10 |
| F12 A | 16/16 | 16/16 | 16/16 | 16/16 | 16/16 | 16/16 | 96/96 | 96 |
| F13 C | 3/13 | 3/13 | 4/13 | 6/13 | 10/13 | 0/13 | 26/78 | 25 |
| F13 U | 0/2 | 0/2 | 0/2 | 1/2 | 1/2 | 0/2 | 2/12 | 1 |
| F18 A ECh | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 8/8 | 48/48 | 48 |
| F18 A FCh, FDh | 16/16 | 16/16 | 16/16 | 16/16 | 15/16 | 15/16 | 94/96 | 94 |
| F18 AC | 1/1 | 1/1 | 1/1 | 0/1 | 1/1 | 1/1 | 5/6 | 5 |
| F19 I | 42/42 | 42/42 | 42/42 | 42/42 | 42/42 | 42/42 | 252/252 | 252 |
| F19 D | 43/43 | 43/43 | 43/43 | 43/43 | 43/43 | 43/43 | 258/258 | 258 |
| F20 R | 264/264 | 264/264 | 264/264 | 264/264 | 264/264 | 264/264 | 1584/1584 | 1584 |
| F20 N | 40/40 | 40/40 | 40/40 | 40/40 | 40/40 | 40/40 | 240/240 | 240 |
| F21 | 220/220 | 220/220 | 220/220 | 220/220 | 220/220 | 220/220 | 1320/1320 | 1320 |
| F22 | 108/110 | 110/110 |  | 108/110 | 108/110 |  | 434/440 | 434 |
| F14 T | 21/21 | 21/21 | 21/21 | 21/21 | 21/21 | 21/21 | 126/126 | 126 |
| F14 G | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 | 72/72 | 72 |
| F14 O | 11/11 | 11/11 | 11/11 | 11/11 | 11/11 | 11/11 | 66/66 | 66 |
| F15 A | 17/17 | 17/17 | 17/17 | 17/17 | 17/17 | 17/17 | 102/102 | 102 |
| F15 P | 17/17 | 17/17 | 17/17 | 17/17 | 17/17 | 17/17 | 102/102 | 102 |
| F15 O | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 | 12/12 | 72/72 | 72 |
| F16 P | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 36/36 | 36 |
| F16 L | 16/16 | 16/16 | 16/16 | 16/16 | 16/16 | 16/16 | 96/96 | 96 |

Overall 4333/4352 exact (99.6 %) on F0–F12 with F8's twenty-nine runs,
unchanged by the thirty-third fit, which is +2 −0 over every family
(both F13 OUT, C 26/78 and U 2/12 at odd parity and 1 wait; F22
unchanged at 1314/1320; 18961/19142). The thirty-second fit was
+3 −0 against the thirty-first fit's 4330, all F5 (840/840: the
refresh-off families of F0–F21 exact outside F8); F22 1314/1320
(1068 under the thirty-first fit: PUSH 440/440, OUT 434/440, marker-less
440/440), +247 −1 on it. The thirty-first fit was +10 −0 against the
thirtieth fit's 4320, all F8 (PUSH 19/24, OUT 10/24), the refresh-off
families unchanged; +211 −0 over every family, all refresh-on. The thirtieth fit was +2 −0 against the twenty-ninth fit's
4318 (F8 OUT 6/24), the refresh-off families unchanged; +15 −0 over
every family, all refresh-on. The
twenty-ninth fit was +1 −0 against the twenty-eighth fit's 4317 (F8
OUT 4/24), the refresh-off families unchanged; +234 −0 over every
family, 8 of them the F17 W ECh refresh-off twins and the rest
refresh-on. The twenty-eighth fit was +2
−0 against the twenty-seventh fit's 4315, all F8 (PUSH 13/24, OUT
3/24), the refresh-off families unchanged; +127 −0 over every family,
all refresh-on. The twenty-seventh fit was +3
−0 against the twenty-sixth fit's 4312, all F8 (PUSH 11/24, OUT 3/24),
the refresh-off families unchanged; +439 −0 over every family, all
refresh-on. The twenty-sixth fit was +4 −0
against the twenty-fifth fit's 4308, all F8 (PUSH 10/24, OUT 1/24),
the refresh-off families unchanged; +245 −0 over every family, all
refresh-on. The twenty-fifth fit was +6 −0
against the twenty-fourth fit's 4302, all F8 (PUSH 6/24 from 0, OUT
1/24), the refresh-off families unchanged; +441 −0 over every family,
all refresh-on. The twenty-fourth fit left F0–F12 at 4302, +14 −0 over
every family (F14
732/732 from 729, F15 840/840 from 837, F16 1014/1014 from 1011, F21
3576/3576 from 3573, F18 201/1164 from 199); outside F8, 3 refresh-off
runs are missed, F5's `ADD [BW+200h],imm16` at 0 waits. The
twenty-third fit was +13 −0
against the twenty-second fit's 4289 (F3 840/840 from 834, F5
837/840 from 833 with PUSH 418/420 and OUT 419/420, F1 54/54, F6 576/576
and F7 432/432 each from one short); F14 729/732 (728), F15 837/840
(836), F16 1011/1014 (1002: S 354/354), F19 1290/1290 (1286: D 660/660),
F20 3594/3594 (3580: R 3234/3234), every other family unchanged:
+42 −0 over every family, leaving 15 refresh-off runs missed outside
F8 (F5 3, F14 3, F15 3, F16 3, F21 3). The twenty-second fit was +9 −0
against the twenty-first fit's 4280, all F5 (833/840 from 824: PUSH
418/420, OUT 415/420); F14 728/732 (696: T PUSH 246/246, OUT 123/126,
marker-less 24/24), F15 836/840 (820: A OUT 99/102, marker-less
18/18), F16 1002/1014 (996: R 294/294), F19 1286/1290 (1233: the
immediate series I 630/630), every other family unchanged: +116 −0
over every family. The twenty-first fit was +31 −0 against the
twentieth fit's 4249 (F4 456/456 from 428, PUSH 228/228
and OUT 228/228; F5 824/840 from 821, OUT 409/420); F15 820/840 (817: A
OUT 89/102), F19 1233/1290 (1229: I OUT 218/252), F21 3573/3576
(3493: PUSH 1319/1320, OUT 1318/1320, marker-less 936/936), every
other family unchanged: +118 −0 over every family. The twentieth fit
was +16 −0 against the nineteenth fit's 4233, all F5 (PUSH 415/420 from 412,
OUT 406/420 from 393); F15 817/840 (815), F16 996/1014 (994), F19
1229/1290 (1195: I PUSH 237/252, OUT 214/252, marker-less 122/126),
F20 3580/3594 (3559: R 3220/3234, N 360/360), F21 3493/3576 (3352:
PUSH 1310/1320, OUT 1247/1320, marker-less 936/936), every other
family unchanged: +216 −0 over every family. The nineteenth fit was
+15 −0 against the eighteenth fit's 4218, all F4 (PUSH 224/228 from 218,
OUT 204/228 from 195); F14 696/732 (693: T PUSH 228/246), F21
3352/3576 (2901: PUSH 1252/1320, OUT 1188/1320, marker-less 912/936),
every other family unchanged: +469 −0 over every family. The
eighteenth fit was +7 −0
against the seventeenth fit's 4211, all F4 (PUSH 218/228 from 213,
OUT 195/228 from 193); F14 693/732 unchanged, F15 815/840 (813), F16
994/1014 (988), F19 1195/1290 (1165: I PUSH 224/252, OUT 196/252,
marker-less 119/126), F20 3559/3594 unchanged, F21 2901/3576 (2547
with the seventeenth fit's rules: PUSH 1058/1320, OUT 1085/1320, marker-less
758/936): +409 −1 over every family, the one lost refresh-on (F17 W
71/144 from 61, P 3/60 from 4). The seventeenth fit was +63 −0
against the sixteenth fit's 4148 (F6 42, F3 15, F7 2, F10 2, F12 2);
F14 693/732 (691), F15 813/840 (811), F16 988/1014 unchanged, F19
1165/1290 (1109), F20 3559/3594 (3289 with the sixteenth fit's rules: R
PUSH 973/990, OUT 1574/1584, marker-less 654/660; N PUSH 120/120, OUT 238/240):
+393 −0 over every family. The sixteenth fit was +18 −0
against the fifteenth fit's 4130, all F5 (the `CMP [BW],imm16` k = 2
pairs and the `OUT DW,AW` pairs); F14 691/732, F15 811/840, F16
988/1014 unchanged; F19 1109/1290 (895 with the fifteenth fit's rules:
I PUSH 209/252, OUT 191/252, marker-less 109/126; D PUSH 262/270, OUT 206/258,
marker-less 132/132). The fourteenth and fifteenth fits left F0–F12
at the thirteenth's 4130, which was +81 −0 against the twelfth fit's
4049 (F3 52, F5 18, F12 11) and took F14 to 691 (655), F15 811 (745),
F16 988 (888): +283 −0 over every family with no new data. The twelfth fit was +42 −0 against the eleventh fit's
4007 (F5 27, F12 7, F3 4, F7 4) and +349 −0 over every family. The
eleventh fit was +84 −10 against the tenth fit's
3933 (F7 28, F3 24, F5 22, F12 0; the ten `MOV AW,DW` pairs listed in
the Model). The tenth fit was +135 and nothing lost against
the ninth fit's 3798 (F5 87, F3 24, F7 12, F12 12). The ninth fit was +197 −2 against
the eighth's 3602 (F3 50, F6 40, F12 A 33, F10 28, F7 24, F12 B 16, F11
4, F2 OUT 2; lost `F12-a-out-n1-shl1-pE-w1` and `F3-push-shl1-k1-pE-w1`).
On the 4,148-run corpus 4129 (thirty-first 4126, thirtieth 4116, twenty-ninth 4114, twenty-eighth 4113, twenty-seventh 4111, twenty-sixth 4108, twenty-fifth 4104, twenty-fourth and twenty-third 4098, twenty-second 4085, twenty-first 4076, twentieth 4045, nineteenth 4029, eighteenth 4014, seventeenth 4007, sixteenth 3946, thirteenth to fifteenth 3928, twelfth 3858, eleventh 3823, tenth 3749,
ninth 3625, eighth 3478); on the 3,812-run corpus of the earlier fits
3793 (thirty-first 3790, thirtieth 3780, twenty-ninth 3778, twenty-eighth 3777, twenty-seventh 3775, twenty-sixth 3772, twenty-fifth 3768, twenty-fourth and twenty-third 3762, twenty-second 3749, twenty-first 3740, twentieth 3709, nineteenth 3693, eighteenth 3678, seventeenth 3671, sixteenth 3612, thirteenth to fifteenth 3594, twelfth 3524, eleventh 3489, tenth 3415, ninth 3291, eighth 3176, seventh 3135, sixth 3045, fifth 2695, fourth 1989, third
1724, second 1146, first 994). PUSH/store/marker-less 2577/2582,
OUT-marked 1756/1770 on F0–F12. The guards hold; the END block is exact
in every refresh-off run; no chain overfills the queue. F7 with zero
free parameters: PUSH 216/216, OUT 216/216 (twenty-third fit; seventeenth to twenty-second 215, twelfth to sixteenth 216 and 213, eleventh 214 and 211,
tenth 210 and 187, ninth 210 and 175, eighth 200 and 161).
With refresh on, after the thirty-third fit: F8 29/48 (19, 17, 16, 14,
11, 7 after the thirtieth to twenty-fifth fits, 1/48 from the
fourteenth to the twenty-fourth), F13 386/462 (384 after the
thirty-first and thirty-second, 242, 236, 220, 211, 192, 151, 67 before
the twenty-fifth: S 186/186 from 93, C OUT 26/78 from 25, C PUSH
65/78 from 44, R 42/42 from 29, N 12/12 from 7, U 19/30 from 11, S0
36/36), F17 749/798 (729, 727, 646, 641, 578, 480, 314: E 150/150
refresh-off, W 132/144 with the ECh twins 48/48, S 304/312, D 96/96, P
38/60 from 19, C 29/36) and F18 1133/1164 (1094, 1089, 953, 842, 488,
386, 201: A ECh 96/96 refresh-off, A FCh and FDh 189/192 from 150, AC
11/12, B 645/672, BD 192/192), with no per-run alignment and no
stand-in table anywhere in the fit; the pre window exact in every run;
the refresh-on END-mismatch count 173 (175 after the thirty-first and
thirty-second fits, 384, 399, 604, 731, 1110, 1380 after the thirtieth
to twenty-fifth, 1821 before them); of the 2,142 refresh-on runs 1,967
are exact, none first diverges at or before the first LS, 152 in the
middle and 23 in the END block (1,965, 0, 154, 23 after the
thirty-first and thirty-second fits; 1,754, 208, 162, 18 after the
thirtieth). 18961/19142 on the whole corpus of 23 families after the
thirty-third fit (18959 after the thirty-second, first recorded here
as 17959; 17645/17822 on F0–F21 from the thirty-second fit on; 17642
after the thirty-first, 17431 after the thirtieth, 17416 after the
twenty-ninth). Before the
twenty-fifth fit the refresh-on families were what the fifteenth fit
scored but for F17's +10 −1 under the eighteenth fit's displacement
head and F18's +2 under the twenty-fourth fit's early multiply end.

Emergent with no per-wait integer: every family of the refresh-off
corpus of F0–F21 but F0w (F5 from the thirty-second fit): F2 and F9 since the ninth
fit, F10 to F12 from the seventeenth, F4 from the twenty-first, F1, F3,
F6, F7, F19 and F20 from the twenty-third, F14, F15, F16 and F21 from
the twenty-fourth; the
F6 drain (back-to-back fetches at 81/85/88 and 83/88/93/98, X's read
13/15/18 clocks after the fetch delivering its last byte, the 7/8/9.5
slope); `MOV/ADD AW,imm16` trains at every k; both F1 store trains; the
whole F4 mode table (456/456 from the twenty-first fit, 38/38 at odd
parity and 1–2 waits from the fourth); group RMW forms, ADD
[BW],AW and PUSH [BW]; OUT after OUT at every wait; the OUT-marked F2, F6
and F7 columns at 1–2 waits; with the data latch the 0-wait OUT-marked
columns of F2, F5, F6 and F7; the first data cycle of every `[BW],imm16`
form at both parities and all waits; `IN AL,DW`; every F10 pO cell and
every F11 cell; the PUSH-marked and PUSH-twin F12 series A cells, and
every F12 series B marker-less 0-wait cell; every TEST and XCH run of F5
and the F14 ladder's width, register and direction pairs; the whole
F19 immediate series (630/630 from the twenty-second fit); `MULU [BW]`
and `DIVU [BW]` at every wait; `SHL [BW],CL` in every framed cell; every
PUSH-marked F15 A run (the AND ladder, TEST imm, the one-byte immediate,
direct TEST at both parities) and every marker-less `POP [BW]` at pE;
every F3 OUT prefix row; every F15 K pair (120/120) and every F16 R
pair but TEST imm's (288/294: the eight D0/D1 operations, MUL/DIV, the
byte forms, PUSH [BW] and the ALU forms as second instance at both
parities and every wait); every F12 B and F16 P marker-less run;
`NOP^n ; POP [BW]` under PUSH at n ≥ 1 in every cell; every F12 A OUT
run (96/96), every F14 G run (180/180: the group memory forms at both
parities under both markers), every F15 P OUT and marker-less run and
every F15 O PUSH and marker-less run, every F16 P OUT run, and every
F16 L OUT run but one (the register forms after the OUT marker at both
parities, scaling with their length).

### Findings from the fits

Knob-dependent integers (structural signals, not encoded):

- `reg.nx` wanted 0 at k=1 and 1 otherwise in every fit up to the eighth:
  closed by `start_sync=b2b_modrm` in the ninth (1 and 2 tie at 3797, 0
  gives 3649; the k=1 cells that wanted 0 were the start on the
  back-to-back fetch's issue clock, F3 PUSH k=1 +6, k=2/4 still exact).
- `shift_imm.exec` wanted 5 at k=4, 6 otherwise: closed by `exec0` for
  the D1 form. Checked clean in the ninth fit against parity, waits, k,
  marker and family: `reg.nx`, `out.nx`, `out.wbsync`, `out.wbsync0`,
  `shift_cl.wb`, `wlatch`, `shift_imm` exec, exec0, cpre, nx and wb.
- `in.post`: the OUT-marked runs prefer 1; the one run gained reflects
  finding 3. The fifth fit's `in.setup` and `in.pre` dependence is gone.
- `store_imm.pre` wants 1 at even parity and 0 at odd; in the pipeline's
  stage 5, `store_imm.setup`/`grp` want 2 and 3 at 0 waits and
  `rmw_imm.wb` wants 1 at 0 waits.
- `pop_mem.grp` moves with parity and waits; `ea.base_disp` moves with
  every knob (tie 0/2).
- `out.setup0` 8 against `in.setup0` 7: the only difference between the
  DW forms' integers, and a finding rather than a rule (item 3).
- `load_alu.grp` wanted 3 at even parity and 4 at odd and `grp_free` 1
  at 0 waits and 3 at 1–2 waits in the tenth fit (the direct TEST form):
  closed by `fixed_lookup=decoder_nowait` in the eleventh.
- `pop_mem.rfree` prefers 1 at 1 wait (it loses 29 runs at 2 waits);
  `load_alu.fdisp` clean only with the wait-state exclusion (5 at w1, 6
  at w2 without it).
- `div.exec` 39 was best overall and at odd parity in the twelfth fit
  with 40 or 41 better at even parity on 5 runs (the register divide
  after the OUT marker in the PUSH twin): closed by `unit_hold` and the
  multiply's write-back in the thirteenth, where every `hphase`, `wb`,
  `mtail` and `exec` of `mul`/`div`/`shift_*` and `pop_mem` pre and
  setup_free have one best value at every knob. The twelfth fit's `mul`/`div` smexec, bmexec and mtail have one best
  value at every parity, wait, k, marker and family (mtail sharp at
  3).
- `refresh_tail_bound` and the F13 boundary integers' dependence is
  gone with the fourteenth fit's phase and drop rules, and after F18
  `shift_tail` 3 has none either on exact runs (nor `rfm_delay`,
  `reraise_off`, `refresh_recent`, against parity, waits, k, marker and
  family). On matched events `refresh_recent` 18 prefers 21 at 2 waits
  and 16 under the PUSH marker: with its per-wait shrinkage already in
  the `fetch` window, that is the one open integer dependence (item 8).
- `rmw_imm.istart` 5 (sixteenth fit): F16 prefers 7 on the
  `TEST [BW],imm16` second-instance runs (994 against 988), the F7 /0
  forms running under `rmw_imm` wanting their read's floor at s + 9;
  `store_imm` istart and grp1, the grp and grp_free integers, `hold_q`,
  the DW setups and `out.lead` move with nothing over F4–F7, F10,
  F14–F17 and F19.
- Seventeenth fit, over 30 integers and the 11,774 refresh-off runs
  with the new `n` knob (lead-in NOPs or drainers): `reg.nx` 2 prefers
  1 under PUSH and marker-less and at n = 1 (1 overall is +5 −64);
  `imm.nx` 0 prefers 1 at k = 4 on one F3 run; `ea.base_disp` 2 prefers
  1 on F4 alone (407 against 406); `rmw_imm.istart` as above. Every
  other integer has one best value at every knob.
- Eighteenth fit, over 31 integers and the 15,350 refresh-off runs with
  `n`: `ea.base_disp`'s F4 preference is gone and every eighteenth-fit
  integer has one best value at every knob; `rmw.setup_free` 3 prefers
  1 at even parity, k = 1–2, the OUT frame, n = 0, F15 (+3) and F21
  (+12), a finding not encoded; `reg.nx`, `imm.nx` and `rmw_imm.istart`
  as before.
- Nineteenth fit, over the same runs: every `dfloor`, the EA integers,
  `store_imm.dadd`, `pop_mem.setup_free`, `store_imm.istart` and
  `load.exec` clean; new, `load_alu.fdisp` 4 prefers 3 at even parity
  (`TEST [0C00h],AW` under PUSH in F14 T and F15 A: 3 gains 3 pE runs
  and loses 9 pO; clean on the eighteenth fit, so the nineteenth's head
  moved it); `rmw.setup_free`, `reg.nx`, `imm.nx` and `rmw_imm.istart`
  as before.
- Twentieth fit, over the same runs with the n knob (15,350
  refresh-off runs): `reg.nx` by marker and n, `imm.nx` by k and
  family, `load_alu.fdisp` by parity (even 3) and `rmw_imm.istart` (F16
  wants 7) as before; `rmw_imm.wb` 0 prefers 1 at 0 waits and
  `rmw.setup_free` 3 prefers 1 at even parity, k = 1 and 2, under the
  OUT marker, on F15 and F21 and at n = 0, both already so on the
  nineteenth fit (checked on `fit-wp28.json`) and outside its narrower
  parameter list. The idle clock after a run's fetch on a request's
  issuable clock is left out as a knob dependence (+3 at 0 waits, −72
  at 1–2).
- Twenty-first fit, over the same runs: `rmw.setup_free`'s preference
  for 1 (by parity, k, marker, family and n since the eighteenth fit)
  is gone, being the RMW's ALU clocks counting through a fetch
  (`rmw_alu`), and `load_alu.fdisp` no longer appears; `reg.nx` by
  marker and n, `imm.nx` by k and family, `rmw_imm.istart` (F16 wants
  7) and `rmw_imm.wb` (0 waits wants 1) as before; the EA integers,
  every `dfloor`, `io_b2b_q`, the `store_imm` integers, `hold_q` and
  `pop_mem.setup_free` clean.
- Twenty-second fit, over the same runs (29 integers):
  `rmw_imm.istart`'s F16 preference for 7 is gone (TEST imm's lookup
  before the floor, `fixed_floor`), as are `load_alu.fdisp`'s
  (`lookup_start`) and `rmw_imm.wb`'s; left, `reg.nx` by marker and n
  and `imm.nx` at k = 4 and on F3, as since the ninth fit; the new
  `sidle` integers, the EA integers, `hold_q`, `io_b2b_q` and `wlatch`
  clean, and the stage-5 report finds no dependence in any grid.
- Twenty-third fit, over the same runs: no integer's best value differs
  by parity, waits, k, marker, family or n. `reg.nx`'s split by marker
  and n, carried since the ninth fit, was `io_take_nx`'s clock, and
  `imm.nx`'s at k = 4 on F3 is gone with `latch_start`.
- Twenty-fourth fit, over the same runs (32 integers): no integer's
  best value differs by parity, waits, k, marker, family or n.
- Twenty-fifth fit, the refresh integers over F8, F13, F17 and F18:
  `refresh_recent` 18 prefers 15 at 1 wait and 19 at 2, and 15 on F13
  and F18 (15 everywhere: +78 −61, apparently the runs
  `refresh_exec=every2_early` trades); `shift_tail`, `refresh_tail_bound`,
  `rfm_delay` and `reraise_off` clean. Item 8 g stays open.
- Twenty-sixth fit: `refresh_recent` 18 best at 18, 18 and 19 by
  waits (the 1-wait preference went with the eve's acceptance) and 16
  under the PUSH marker; as the hold's window alone its best values
  are 18, 17 and 17, neither a count of clocks nor of fetch lengths
  (item 8 g, open); `shift_tail`, `refresh_tail_bound`, `rfm_delay`
  and `reraise_off` clean.
- Twenty-seventh fit: `refresh_recent` as before (18, 18 and 19 by
  waits, 16 under PUSH); `mul.rexit`, `div.rexit`, `shift_tail`,
  `refresh_tail_bound`, `rfm_delay` and `reraise_off` clean.
- Twenty-eighth fit: `refresh_recent` 18 best at 18, 18 and 19 by
  waits, 19 under PUSH and at k = 8 (re-scanned at 17, 19 and 20: +1
  −120, +61 −120, 0 −122); the rest clean.
- Twenty-ninth fit: no integer's best value differs by any knob;
  `refresh_recent` is no longer read, the eve hold it governed being a
  fixed one-clock hold at the loop's entry.
- Thirtieth fit: no integer's best value differs by any knob.
- Thirty-first fit (the refresh hold integers, `mul.rexit`, `div.rexit`
  and `pop_exit`): no dependence.
- Thirty-second fit, with F22 (the `rmw_imm`, `store_imm` and
  `load_alu` integers and `hold_q` over 16,670 refresh-off runs): no
  integer's best value differs by any knob.
- No dependence: `wlatch`, `io_recover`, every `out.*`, `in.pre`,
  `in.setup`, the write-backs, `rmw_imm` grp/grp_free/alu/setup/post,
  `store_imm` grp/grp_free/setup/post, the DW setups, `load_alu.dclk`,
  `rmw.dclk`, `rmw.grpcl`, the `mul` and `div` grp/mexec/mwb.

Structural problems, by the runs they share (19 misses on F0–F12, all F8's; none on F5, F14, F15, F16, F19, F20 or F21; 6 on F22; refresh on: 19 on F8, 76 on F13, 49 on F17, 31 on F18):

1. **Immediate memory forms: closed by the twenty-second fit (F19 I
   630/630) and, for F5's last three runs, by F22 (thirty-second fit:
   F5 840/840, F22 1314/1320).** the sixteenth fit's count floor closed the data cycle's clock
   in every frame and the CMP k = 2 second read; the eighteenth fit's
   head (the displacement after the EA clocks, no sync after it, the
   immediate store's one clock after the take) closed 37 of the
   odd-aligned d8/d16 head's 55 runs (item 10); the twentieth fit's hold
   at the write's free clocks' eve and the OUT's wait beside an older
   fetch at 2 stored closed the odd-aligned head and the shallow-queue
   follower (the OUT-frame `st_imm_bw` pO runs of F5, 34 F19 runs,
   F19 I 539 to 573/630); the twenty-first fit's immediate-form start
   (`imm_start`: the form waits out the fetch its start raises while
   fewer than 4 bytes are stored, its operands being the bytes behind
   the address) closed the k = 2 follower (9 runs over F5, F19 and
   F21). The twenty-second fit closed the rest: the left-out write's
   slot fetches only with room for a word not counting the word
   delivered on the slot clock (the one-byte immediate leaves one byte
   more stored, so only `CMP [BW],imm8` reaches the state: 31 of 31
   slots without a fetch, item 1's one alignment), a slot without a
   fetch is no bus cycle (the next instruction 2 clocks after it at
   every wait) and the slot fills the data latch as the write it
   stands for would (the closing OUT a clock late at 0 waits only, 34
   of 34). F5's last three runs, `ADD [BW+200h],imm16` under PUSH at pE
   0 waits and under OUT at pO 0 waits (silicon idling a clock after a
   run's delivery-clock fetch that goes first against the read already
   issuable), were read by the twenty-fourth fit as either the
   request's kind or the post clock not being a wait state, which no
   cell separated. F22 (thirty-second fit) separated them the other
   way: the immediate RMW's read runs exactly as the immediate store's
   write in the same cell through its first data cycle in 600 of 600
   cells, and the three runs' counted state occurs in 17 cells, every
   one an RMW's read, because the model had posted the read a clock
   early for want of the store's EU clock after the displacement's take
   (`rmw_imm.dadd` 1, +3 on F5, +104 on F22). F22 also gave TEST
   r/m,imm16 with a displacement TEST 84/85's fixed lookup
   (`fixed_lookup_grp=group`, +108) and the one-byte immediate's read
   its turn on a non-run fetch's delivery clock (`imm1_first=hold`,
   +34). Left: 6 F22 runs, `TEST [BW+200h],imm16` directly after the
   OUT marker (the fetch held 2 clocks past the I/O's recovery at pO,
   the fetch at the eve after the I/O at pE: two rules for six cells,
   neither adopted). `OUT imm` under the OUT frame at pO 0 waits
   was closed by the twenty-third fit (`port_issue`).
2. **TEST and XCH: closed by F14** (tenth fit). TEST's read delay keys
   on its operation being named by no ALU-op field (`grp_ops=fixed`),
   XCH's late write and CMP r/m,reg's late end on the result route
   (`dest_route`): all 72 F5 runs. The AND control confirmed the TEST
   reading, and TEST imm (the two lookups in series) and the direct TEST
   (the lookup holding the decoder) are closed by the eleventh fit. The
   twenty-second fit closed the TEST/CMP residuals: TEST's fixed lookup
   counts a clock on an aborted start cycle as the unit forms' setup
   does (`abort_fixed`, 15 of 15), TEST imm's lookup runs before the
   group decode its floor counts (`fixed_floor`, 12 of 12, the
   `rmw_imm.istart` knob dependence) and costs a clock more after a
   start-clock fetch (`lookup_start`, the `load_alu.fdisp` dependence),
   and CMP r/m,reg is the RMW with its write left out (`dest_route=slot`,
   the tenth fit's refuted alternative, right under the slot rules: 21
   of 21; F14 T 369/396, F15 A 219/222). The twenty-fourth fit closed
   the last 6, `TEST [0C00h],AW` under OUT at pO: its take state is the
   30 pO base+index+d16 loads' exactly, and what differs is its read's
   one setup clock being a bus-free group clock, which holds a fetch
   requested on or after the I/O's issue through the recovery
   (`grp_io_hold`, the only such cells in the corpus). F14 T 396/396,
   F15 A 222/222; F14 and F15 fully exact.
3. **The DW I/O forms after a register form: closed by F19** (sixteenth
   fit). The record carried this item at 30 F10 runs; on the fifteenth
   fit F10 had 2 misses (`F10-push-adddwi-{outdw,indw}-pE-w0`, item 4)
   and the `MOV DW,AW`-type pairs were exact, what was left being
   `F5-out-out_dw_al` at k = 1 and 2 and `F5-push-out_dw_al-k2-pO` (13
   runs), all closed by `dw_port=hold` and `dw_slot=behind` (F5 805/840,
   F19 D marker-less 132/132, PUSH 262/270). The seventh fit's finding 3
   itself (the END's extra clock) is closed by `halt_status`. Catalog
   note: `out_dw_al` is EF, `OUT DW,AW`.
4. **The register form before a ModR/M form, an I/O form or another
   register form: closed by F20** (seventeenth fit) as three mechanisms,
   each with a state the model did not carry. The F6 `n1` drains and the
   register-immediate rows are the fetch request flag: a register form
   whose last take falls on a fetch's issue clock keeps the request
   raised, the next fetch runs back to back and a ModR/M successor
   waits it out (`request_reissue=no_mem`; not while a memory request
   waits in the slot, which `always` breaks on every direct-address
   form). The 4-byte `ADD DW,imm16` under PUSH is the ModR/M's word: its
   immediate word-mate taken on the delivery clock keeps the word's slot
   where a displacement frees it (`modrm_mate=imm`, the F4 base+d16
   loads the control). The 8B forms before a DW form, the ten `MOV
   AW,DW` pairs and the 4-byte form under OUT are one start rule: no
   form without a ModR/M starts on a back-to-back fetch's issue clock
   with fewer than 3 bytes stored (`io_b2b`; 32 of 32 such starts at 2
   stored were misses, 248 of 248 at 3 exact). The earlier attempts
   moved the take sync and so caught the loads; the request and start
   rules do not. F6 575/576, F3 834/840, F7 431/432, F10 and F12 exact,
   F19 D 656/660. The twenty-third fit closed every run left: the 8B
   form's next start is visible in two states only, a ModR/M take on
   the marker I/O's issue clock (T + 3, 64 of 64) and a take on an idle
   bus after `ES: NOP` (T + 2, 13 of 13), so `reg.nx` is 1 with the IR
   load a clock later after an I/O-issue-clock take (`io_take_nx`), the
   byte latched behind a full queue goes in on the ModR/M take clock
   (`modrm_port`, the 8 `ES: NOP ; MOV r,r ; X` cells), a NOP's
   back-to-back fetch after an I/O waits for the next start (`nop_hold`,
   the 4 F19 D runs) and the port byte taken on a fetch's issue clock
   lands a clock late (`port_issue`, OUT OUT). F19 D 660/660, F20
   3594/3594. Closed before: the F4 base+index+d16 loads under PUSH at pE 0
   waits (the IR no room inside the EA clocks, twenty-first fit, item
   10) and `ES: NOP` directly before a memory form (the mod 00 floor,
   twentieth fit).
5. **Group memory forms:** `MULU [BW]` and `DIVU [BW]` closed by their
   own exec and write-back integers and `SHL [BW],CL` by its fetch-free
   count setup (tenth fit); `POP [BW]` reads the stack first with POP
   AW's setup and `PUSH [BW]` posts its write on the data's arrival
   (eleventh fit, +107). The twelfth fit closed the two it left: the
   fetch POP AW holds in its setup's tail runs in `POP [BW]` because its
   request first rises on a delivery clock inside the read's fetch-free
   clocks (`free_run=run`, F16 P plus 10 F5 and 4 F7 runs; with NOPs
   before POP the fetch is out of its setup), and the second instance's
   early read at k = 2 pE is the operation unit's (`abort_unit=loop`):
   the F16 ladder showed every D0/D1 reg value and the byte forms
   behaving alike and NOT/NEG/INC/DEC not, so the reg-field bit is
   refuted and the split is by class (F15 K 120/120, F16 R 288/294).
   The thirteenth closed POP directly after the OUT marker (the stack
   read moving into the bus unit's slot with fetch-free clocks still to
   count, `slot_fetch`, 42 runs across F5, F14, F15 and F16) and the
   displacement forms at n ≥ 1 (`disp_take=end`). The eighteenth
   fit's direct-address class (`ea_direct=base_disp`) and
   `pop_mem.setup_free` 0 closed `POP [0C00h]` at 1–2 waits but one run,
   and the twentieth fit's hold at the stack read's free clocks' eve
   closed that run and `POP [BW+d8]` at pE 0 waits (F15 P 102/102,
   F16 P 96/96, F21's POP r/m 648/648); TEST imm's second instance and
   the TEST/CMP k = 2 residuals are closed by the twenty-second fit
   (item 2; F14 T PUSH 246/246). Left: the signed and byte multiply/divide
   clocks are fitted at one datum each, so their data dependence is
   untested.
6. **F3: closed (840/840, twenty-third fit; OUT-marked was 51, 15 after
   the thirteenth fit):** the
   thirteenth fit closed SHL AW,1, the prefixed `MOV AW,imm16`, MULU DW
   and the 0-wait `MOV`/`ADD AW,DW` rows; the seventeenth closed
   `ADD DW,imm16` and the k = 2 `MOV`/`ADD AW,DW` pairs (item 4); the
   twenty-third closed `MOV CL,imm` k = 4 in both frames: an instruction
   starting on the clock a byte latched behind a full queue goes into
   the queue runs its first EU clocks from the clock after
   (`latch_start`, 10 of 10 with F16 S's `NOP^n ; MOV CL`).
7. **F6: closed by F20** (seventeenth fit, 575/576): the `n1` drains
   and the 4-byte drainer rows were item 4's request flag and word-mate;
   the twenty-third fit closed OUT OUT at pO 0 waits (`port_issue`):
   576/576.
8. **Refresh, the EU side (F8 29/48, F13 384/462, F17 749/798, F18
   1133/1164):** the fill phase is settled by F17 (fourteenth fit): the
   timer is a free-running binary counter from reset whose value at
   clock 0 is a constant of the prelude's RFM and WTC, and with it the
   per-run alignment is gone at no cost; RFEN only gates requests, 3
   clocks after the SFR store. The fourteenth fit's four EU rules (the
   odd-room loss of a beaten request, the re-raise at the count loop's
   exit, the take on the last byte, the beaten fetch running into HALT)
   and the fifteenth's three (the loop's-eve boundary gated by the
   previous refresh's recency, the divide on the multiplier's loop, the
   memory shift's iteration boundaries) stand, and the twenty-fifth fit
   closed HALT's service clocks (c, below) and the RFMON store's head
   (h); the twenty-sixth closed the END block's count beside the early
   fetch run (c), the lost request at HALT (d) and the loop eve's
   acceptance (b, g); the twenty-seventh closed the NOP's end under a
   refresh (f), the multiply's and divide's exit and retry and `SHL
   AW,1`'s exit (b), and two states found in its re-read, the aborted
   request under a refresh and the I/O lead's first free clock; the
   twenty-eighth closed the memory shift under refresh (b), the aborted
   cycle's sync clocks, the posted request's first clock and the
   count-byte shift's seam; the twenty-ninth closed the loop's parity
   (g), the SFR store's setup (e), the I/O's count under a refresh
   started before it and the request lost inside a unit; the thirtieth
   closed the beaten fetch's pair under an I/O form (f) and the take
   behind a latched byte. Left:
   (a) the first LS's
   start under a refresh-on prelude is now observed (F18 A: the marker's
   cycle single-valued per prelude and wait setting, the LS 16–21 clocks
   longer under FCh with 8 or 9 refreshes, 1 or 2 of them before its
   start) but not derived: the prelude tail run by the model reproduces
   every refresh-off cell and no fill table is needed there, but under
   refresh the register-load train's requests (at once at 1–2 waits; 0,
   1 or 3 clocks late at 0 waits) and the anchor's fixed point are not
   modelled, 27 of 66 cells against the stand-in's 41; the twenty-fifth
   fit re-read it: 16 of F18 A's 24 refresh-on cells are right at the
   first LS's end with the stand-in and 8 are off by −2..+4 in every run
   of the cell, the prelude tail run by the model is still worse (+45
   −106), and the one-rule derivation cannot be read off because the
   register-load train runs before clock 0, outside the aligned lists
   the model is compared on (a harness change would be needed to see
   it). The thirtieth fit measured it as a diagnostic: the first LS's
   exec runs 2 clocks earlier in silicon in the FCh pE 0-wait and pO
   2-wait cells and 1 clock later in the pE 1-wait cell, the refresh
   request itself on the same clock at every wait; moved by that
   constant per cell, 62, 55 and 59 of the three cells' runs become
   exact (3, 19 and 0 before, about 154 in all) and none diverges
   earlier. That is a per-cell alignment and is not in the fit; it says
   what the prelude's train does and not why, and the 208 first-LS runs
   wait for the harness change. The harness change was made after the
   thirtieth fit (Model, "The prelude's tail from the POP PSW read"):
   the pre window is in the lists, silicon's is one trace per prelude
   (RFM, WTC, marker) at both parities in every family and repeat, the
   model runs the tail from the POP read with the counter's value
   there read off, and six rules make the window exact in 40 of 42
   cells and derive the offsets; the candidate gains 192 and loses 51
   after clock 0 (the marker OUT under a refresh-on prelude, 47), so
   the stand-in stays until those 51 are read. The thirty-first fit
   read them (the port form's lead, the post under a refresh, the
   data-latch wait, the beaten fetch's delivery at 0 waits, the FFh
   1-wait counter) and adopted the tail with nothing lost: the pre
   window is exact in every run, no refresh-on run first diverges at
   the first LS, and the two stand-in tables are gone (a, closed; F13 S
   186/186, R 42/42, N 12/12, F18 A FCh/FDh 189/192). (b) The F17
   split is the previous refresh's recency (fifteenth fit), with a
   window that shrinks a clock per wait setting and so counts something
   other than clocks. The twenty-sixth fit read every loop eve with a
   request pending (303): silicon takes the request at the eve in 7,
   one cell at 0 waits with three fetches after a refresh 16 clocks
   back, and waits for the loop's first clock in 296, where the window
   had taken 164; the eve is now a hold point only (`refresh_eve=hold`)
   and the window governs the hold of a refresh already on the bus,
   which is not on the pins (g). The multiply's and divide's
   first-request parity is no longer off in any prefix-matched window.
   The twenty-seventh fit tabulated every refresh request inside a
   register shift's and multiply's exec window: `SHL AW,CL` and `SHL
   AW,4` take requests on every iteration start and on the exit's clock
   2 before its end, `SHL AW,1` on E+3 and E+5 and never E+2 or E+4,
   which only a 3-clock exec, 2-clock loop and 2-clock exit fits
   (`shift_exit0=exit`); the multiply's wrongly placed requests were all
   in its last 8 exec clocks, which run as a loop exit with boundaries
   6, 4 and 2 before the end (`refresh_mul_exit=exit`, `rexit` 8, the
   divide's 6), and the retry of a request dropped at the unit's start
   moves with the exec's end under a refresh hold (`refresh_retry=end`).
   The twenty-eighth fit closed the memory shift: its write setup has
   the register shift's shape end-aligned to the write's issue
   (`refresh_rmw_shape=shift`: boundaries at the post, at `shift_tail`
   + 2k before the issue, at the exit's clock and on the issue, where
   the model had even distances; 96 F18 B runs), its read takes a
   refresh on the post, on the first `grpcl` clock and on the issue
   with the setup counting through the cycle (`refresh_grpcl=step`), a
   memory form's aborted request under a refresh comes back when the
   next bus cycle ends (`refresh_abort_retry=next`), the take sync's
   clocks on an aborted cycle are the EU's own, not boundaries
   (`refresh_abort_wait=run`, which also closed the ten multiply and
   divide runs off at 1 wait), and `SHL AW,4` started on a refresh
   takes its count byte under the refresh, the clocks step between two
   takes no hold point (`refresh_take_seam=seam`); every one of 885
   prefix-matched requests inside a multiply's or divide's exec now
   matches but one past the exec. Left: the closing LS's and X's `SHL
   AW,CL` loop iteration parity after a refresh held in the exec (177
   runs, item g); the closing LS's `MOV CL`, X's exit cells (41); the
   marker OUT after the first LS at 1–2 waits and the second OUT's I/O
   count across a refresh (67); C1 at 2 waits (4); the memory shift's
   retry at 2 waits (1). The twenty-ninth fit closed the loop parity:
   it was never the loop (7,361 of 7,374 refreshes inside it cost
   length − 2 wherever they land) but the exec's end, where a refresh
   on the boundary 4 before the loop holds exactly one clock with the
   loop's first clock as the hold point (`refresh_loop_hold=entry`,
   310 rows at every wait and age, +201). Left in the shift: 24
   closing-LS, 13 X and 11 C1 runs, and the eve after a `unit_hold`
   wait, where silicon takes a pending request after a 1-clock stall
   and not after 2 or 3, the stall's length being the wait setting (29
   rows, no rule). The thirtieth fit regrouped the 48: 13 are the eve
   after a 1-clock stall (d), 7 the loop's exit a clock early at pO 1
   wait, 8 the `MOV CL` start behind a latched byte (closed,
   `refresh_take_latch=hold`), 5 C1 requests on E+1 served on E+2 at no
   cost, 6 other C1, 4 CL 0 shifts, 3 singles; no single state.
   (c) Closed by the twenty-fifth fit: a request in HALT is served at
   H, H+2 or the I/O's issue clock H+5, never H+1, H+3 or H+4, because
   the halt status holds the bus unit on H and H+1 and the posted I/O's
   lead holds the refresh to its issue clock (`refresh_halt=status`,
   `refresh_lead=closed`, 310 prefix-matched requests); the offsets
   read as +3 and +8/+10 were 88 runs where a refresh beats the fetch
   the END's `MOV DW` take sync counts and the EU runs 2 clocks ahead of
   the bus after it (`refresh_sync=run`), and a request beaten after
   HALT has started is dropped (`halt_refresh=run_drop`). The 37 rows
   with a third back-to-back fetch in HALT after such a take were
   closed by the twenty-sixth fit: the I/O's uncounted clocks owed to
   the early run are the clocks 2 earlier, the wait states moving with
   the issues (`dw_view=eu`, 64 runs); a flip of `refresh_lead` now
   gains 1. Four refresh-on runs first diverge in the END block:
   `F13-r-rfm-f3-pO-w2` (a fetch a clock early in the model) and three
   W FDh runs (a refresh 2 off at the RFT switch). (d) Closed by the
   twenty-sixth fit: the F13 S runs where silicon fetches at H+2 (68 in
   all) are a request lost to a refresh at the OUT's start (room 3, the
   second byte latched) that the model never evaluated again until the
   queue changed; it is evaluated again on the next instruction start
   (`refresh_lost=start`), and at HALT goes after the status's two
   clocks ahead of the I/O. The third back-to-back fetch after a
   refresh in some END blocks (`F17-d-n0-shlcl16-pE-w0` F240) is the
   early run's. (e) 16 W ECh refresh-off misses:
   `NOP^n` then the prefixed SFR store, whose next fetch the model
   issues a clock early at 1–2 waits (the only refresh-off misses F17
   has), and 26 W FCh/FDh and P runs where the RFMON store's next fetch
   is 3 clocks off at 1–2 waits, read by the twenty-eighth fit as the
   same state as the ECh twins; closed by the twenty-ninth fit: the
   on-chip SFR store's setup counts through a fetch in flight, its
   write due on a fetch's last clock beating the back-to-back fetch
   (`sfr_setup=count`, +21, the 8 W ECh refresh-off misses among them;
   13 of the 26 exact, 13 diverging past the store). (f) A missing fetch at 0 waits after the first refresh behind
   the `ES: NOP` step (`F18-b-p-n4-shlcl4-pE-w0`); the twenty-sixth fit
   read it: at 0 waits a fetch on the delivery clock of a refresh-beaten
   fetch is late in silicon in every case where the instruction
   starting there follows a NOP (69 later, 59 with a refresh first,
   none on time; 46 `ES: NOP` runs refresh where the model fetches),
   while after a MOV imm or inside a unit it is on time (362 of 362): the
   NOP train runs a clock late from the refresh on, which the model's
   NOP hold does not give. Closed by the twenty-seventh fit: of 13,649
   prefix-matched refreshes, every instruction the model started inside
   a refresh's window started on the clock after its last, except after
   a NOP, where the NOP's empty operand take let the next start through
   on the last clock itself (771 cases); with that take no step
   (`refresh_take0=none`, +190) every NOP-then-start row matches at every
   wait but 16 memory-shift rows, and the `ES: NOP` series is the same
   clock at another phase. The marker OUT after the first LS at pE 0
   waits (19 runs) no longer diverges there: the wait for the shift's
   write-back is not a hold point (`refresh_wbsync=seam`, no exact run
   gained, 22 matched events); at 1–2 waits the cell's I/O issues at 110
   in silicon against the model's 105 and 106; the twenty-ninth fit
   counted a refresh's wait states before an I/O's count when the cycle
   started earlier (`refresh_io_pre=count`, the 15 w0 X-form runs
   reaching the second OUT) and read the rest: at pE silicon runs the
   beaten fetch and a second back to back before the I/O where the
   model's queue has room for one word, and at pE 1 wait silicon idles
   95–96 and refreshes on 97 where 2 waits refreshes on 95 with every
   model state identical; 63 runs open, no state found. The thirtieth fit found the fetch: a
   fetch a refresh beat while an IN or OUT's I/O has not issued is
   followed by a second fetch back to back whatever room the rule
   counts (`refresh_io_run=pair`, 477 of 477 prefix-matched beaten
   fetches, every other class 1,558 of 1,560 right already), and the
   pE 1-wait cell is item a (the first LS's exec a clock later in
   silicon, the refresh request on the same clock). Left: 49, the pE
   1-wait cell (19), the pO second OUT's count after the second fetch
   (8), the second OUT after a refresh at X's shift's end (7). (g) Closed by
   the twenty-ninth fit: `refresh_recent`'s window (18, 18, 19 by waits,
   16 under PUSH; an always-hold rule −81) was a stand-in for a fixed
   one-clock hold at the loop's entry (item b); it is no longer read,
   and no integer's best value now differs by any knob. (h)
   Closed by the twenty-fifth fit: the RFMON store under a refresh
   served on its displacement (`F17-p-n1-shlcl31-pO-w1`, the one run
   the eighteenth fit lost): the refresh leaves the address phase
   running and the write waits for the bus (`refresh_disp=free`, +3).
   F13's refresh-on first divergences after the twenty-sixth fit: 156
   exact, 126 in or before the first LS (the prelude's phase, item a),
   143 in X or the closing LS, 1 in the END block (after the
   twenty-fifth: 115, 262, 26, 23); no rule of the twentieth to
   twenty-fourth fits moves an F13 event, the S series never reaching
   them. Over the 2,142 refresh-on runs (the W ECh runs and the S0 and
   E controls aside): 947 exact, 232 first LS, 959
   middle, 4 END (702, 232, 1,068, 140 after the twenty-fifth fit);
   after the twenty-seventh fit 1,386 exact, 232, 520 and 4; after the
   twenty-eighth 1,513, 232, 393 and 4; after the twenty-ninth 1,739,
   208, 177 and 18 (the 14 new END runs the `MOV DW` take's
   back-to-back fetch after a request lost in the exec); after the
   thirtieth 1,754, 208, 162 and 18 (the END runs read: the model
   fetches at H−10 on the take of `MOV DW`'s last immediate byte with
   room 2 and the second byte latched where silicon does not, 12
   rows, while 14,040 refresh-off and 616 of 623 refresh-on rows in
   the same logged state are right; no rule); after the thirty-first
   fit 1,965 exact, 0, 154 and 23; after the thirty-third 1,967, 0, 152
   and 23 (the two F13 OUT runs whose I/O setup a fetch's wait state
   inside the pre had cost a clock).
9. **F12: closed (204/204, seventeenth fit); the OUT frame's remainder, now in F16:** the n=0 rows, OUT or `SHL AW,1` directly
   after the OUT marker (−1 to −5, 18 runs); the first fetch after the
   OUT marker at pE with n=1 (+3/+4, 6): silicon fetches at the start of
   the OUT, which needs the fetch request re-evaluated on an EU start,
   and `request_eval=on_change` is pinned the other way by F0's
   `MOV DW,imm16`; `SHL AW,4` marker-less at 1–2 waits (−14/−19, 6):
   silicon issues no fetch during the whole shift, as if the count byte
   kept its queue slot until the shift ends; F12 B PUSH at pE w0 (−1,
   2). The three series-A effects, the third-slot rule and the overfill
   of the eighth fit are closed (Model, ninth fit), and the tenth fit
   closed the pE n=1 fetch with `io_ir_hold` without touching
   `request_eval`; the eleventh added `io_busy_start` (a register form
   or prefix starts on the I/O's issue clock or after the cycle, +20,
   every F3 OUT prefix row). The twelfth fit closed `SHL AW,1` after the
   marker at pE (its exec waits for the I/O cycle's end, `io_exec`) and
   the marker-less shift's missing fetch (`count_latch`: the shift's own
   operand byte read on a delivery clock whose only room was the
   latched byte makes it hold the port to its end, F12 B 48/48, F16 S
   338/354; the same shift with its count in CL fetches). Still open
   after F16, all in the OUT frame at odd parity: when the register
   form starts on the I/O's issue clock and that clock is a word's
   delivery clock, the first fetch waits for the form's end and scales
   with its length (`SHL AW,1` F8 after the I/O, `SHL AW,CL` F(10 + 2n),
   `MULU AW` F32, `DIVU IX` F40, landing 2 or 5 clocks before the end)
   while the form keeps its pE length (about 85 F16 L runs and the
   matching F3, F14 and F15 OUT runs); the PUSH-twin `MULU AW` and the
   register divide at pE (+1/+2/+3 with the waits; the pipeline's
   `mul.pre` 1 / exec 29 basin gains 27 of them and loses 40 elsewhere);
   `SHL AW,CL` after `MOV CL` in the PUSH twin at pE; and in S,
   `MOV CL,m ; NOP^n ; SHL AW,CL` at pO n = 2 (12 runs) and
   `NOP^n ; MOV CL,4` alone (4 runs, −1). The thirteenth fit closed the
   odd-parity deferral and the pE PUSH-twin MULU/DIVU and `SHL AW,CL`
   rows as one mechanism (Facts, the OUT frame's remainder: the request
   raised on a latched-delivery I/O issue clock is dropped and re-raised
   at the unit's loop exit; at pE the fetch runs and holds the unit's
   exec at its micro-boundaries), with the register multiply's 31 clocks
   split 29 + 2 of write-back. The twenty-third fit closed the F16 S
   `MOV CL,m ; NOP ; SHL AW,CL` pO 0-wait rows (the aborted cycle's room
   test not counting a byte still latched behind a full queue, with the
   take's sync waiting for the cycle: `abort_latched`, 5 of 5) and
   `NOP^n ; MOV CL,4` (`latch_start`, item 6): F16 S 354/354; the
   twenty-fourth closed `NOP NOP ; MULU AW` after the marker (3): the
   twelfth fit's kept end clock for an aborted-start multiply was never
   observable in the 15 runs it was adopted on (the retry fetch in
   flight on the end, the next start waiting for it) and the 3 where
   it shows have the early end (`abort_reg_end=early`). F16 1014/1014.
   Open reading: the `imm_landed`
   sync holds only for an immediate byte; the same deferral on a ModR/M
   or a load's last byte loses 249, so the data latch is the only path
   the model knows that lands a clock behind the queue write. The
   seventeenth fit's `modrm_mate=imm` and `port_landed` are two more
   sightings of that path (an immediate or port byte lands a clock
   behind the queue write, a displacement does not), and its F12 B
   `ADD DW,imm16` rows closed F12.

10. **The EA path (F21, eighteenth fit): the classes closed, 675 F21
    misses left.** Base = base+index (420/420 cells), every d8 mode one
    class, every d16 mode without an index one class with the direct
    address, base+index+d16 its own at one clock more, the five
    consumers alike: all in the model now (item 1's head, item 5's
    direct POP, F4 413/456 from 406). The nineteenth fit re-read the
    675 misses by the queue count and the fetch in flight at the
    displacement's take and found three take states, not alignments:
    a d16 at 5 bytes with no fetch in flight (0/77 at 0 waits), a d8 at
    6 bytes with no fetch (0/16, 0/48 per wait) and a d8 at 5 bytes
    with a fetch issued at the start (0/72 per wait), while every cell
    at 3–4 bytes with a fetch in flight, the d16 at 6 and the d8 at 5
    was exact. In each the model's fetch existed only because the next
    opcode left the queue for the IR on the take clock, or the empty IR
    counted as room on the delivery clock: holding that opcode in the
    queue until the data cycle issues, with the late take as the
    decoder's rule, a two-clock floor from the take and the latched
    byte counted on the take clock, closed all three for the load, the
    store and ADD (+451 F21, +15 F4, +3 F14 T, nothing lost; F21
    3352/3576, F4 428/456). The twentieth fit read the 224 left at the
    clocks where a posted memory request, a free bus and a wanted fetch
    met: the immediate store's fetch inside its write's setup (about
    95), `POP r/m` at 7 stored (about 45) and the PUSH follower were
    one state, a fetch first requested on the delivery clock of the
    fetch that just ended held on the clock before the request's first
    fetch-free setup clock (110 cells, 0 fetched; 23 fetched where that
    fetch was a run's), not `hold_count=ahead`'s discount (PUSH's write
    at 3 bytes with nothing outstanding is held as the store's at 4
    with 2); the `ES: NOP` group (12 F21, 17 F20 runs) was a floor
    every mod 00 form already kept, the first data cycle at s + 5 in
    9,420 cycles, which the model had reached only through the aborted
    cycle; POP's base+index+d16 write at 1–2 waits took the take floor
    on a request posted before the take; the OUT follower was the OUT
    waiting out an older fetch at 2 stored, as `io_b2b` has it wait out
    a back-to-back one (+141 F21, +34 F19, +21 F20, +16 F5, +2 F15, +2
    F16, nothing lost; F21 3493/3576, marker-less 936/936, POP r/m
    648/648, the `ES: NOP` lead 702/702). Left (83 F21 runs): (a)
    base+index+d16 under the OUT frame at every wait and parity, under
    OUT n1 pE 0 waits and under PUSH l0 pE 0 waits, the four consumers
    and k = 2 alike (69, with the 28 F4 base+index+d16 loads in the
    same cells): the first fetch after the marker one clock later in
    silicon than in the model, everything after it moved with it
    (`F21-out-l0-ld-bw_ix_d16-pE-w1` I85 F89 R93 against F88 R92; the
    d16 twin F88 R92 exact), under PUSH the fetch on the take clock
    s + 4 where the model fetches on the delivery clock s + 3
    (`F21-push-l0-ld-bw_ix_d16-pE-w0` w78 F81 F85 R88 against F81 F84
    R87); (b) `ADD [BW+d16],AW` and `ADD [0C00h],AW` under OUT l0 pE at
    every wait, k = 1 and 2 (12): the write one clock earlier in
    silicon, 6 after the read where the d8 twin's is 5 and the model's
    7 (`F21-out-l0-add-bw_d16-pE-w0` R90 F93 W96 against W97;
    `-bw_d8-` R90 W95 exact); (c) item 1's k = 2 follower (2). The
    twenty-first fit logged every displacement take against every I/O
    issue clock and every clock a fetch was wanted only through the
    IR's slot: the base+index+d16 forms under the OUT frame are the one
    state in the corpus in which a displacement is taken on an I/O
    cycle's issue clock (their extra EA clock pushing the take onto it,
    78 takes), and silicon starts nothing on the clock after that I/O
    (the fetch a clock later in 78 of 78; the twins, taking a clock
    before the issue, exact in 195 of 195); under PUSH and OUT n1 the
    same forms are the IR counted as room inside the EA clocks before
    the take (0 of 18 fetching, every cell with the EA clocks done);
    the RMW's early write under OUT is its ALU clocks counting through
    a fetch, the write on the clock after it (15 of 15; XCH's routing
    clocks after the fetch, 3 of 3); the k = 2 follower is the
    immediate form starting with its operands not yet stored, waiting
    out the fetch its start raised (9 of 9; every other class starts
    beside it, 726 of 726). Four enums, +80 F21, +28 F4, +4 F19, +3
    F5, +3 F15, nothing lost: F21 3573/3576, F4 456/456. Left (3 F21
    runs): the second instance of a base+index+d16 store or immediate
    store at k = 2 (`F21-out-l0-st-bw_ix_d16-k2-pE-w0`, `-sti-` and
    `F21-push-l0-sti-bw_ix_d16-k2-pO-w0`), the model a clock early. The
    twenty-fourth fit closed them: they are the only base+index+d16
    starts beside a fetch issued on the start clock with 2 bytes stored
    (every first instance starts with 3 or more), so that fetch's last
    clock commits a back-to-back fetch into the third EA clock, where
    silicon never fetches (`ea_b2b`: 21 cells want one there, all 21
    fetch on the take clock); the two immediate stores then take the
    idle clock after a fetch committed back to back at the write's eve
    (`free_idle_b2b`, thin: those two cells only). F21 3576/3576.

Process findings. The seventh fit showed the yield per rule falling on
the fixed corpus (three rules for 350 runs in the sixth fit, six for 90 in
the seventh, two of them chosen on count with both alternatives wrong
somewhere). The eighth fit answered that with evidence instead: two
336-run families designed around the two untested state distinctions gave
one rule each, both with nothing lost, and both rules closed their
finding outright while the two hypotheses the seventh fit had named (a
register interlock, the fetch pattern) were refuted by controls in the
same family. The ninth fit took 204 runs designed around the OUT after a
register form and gave seven rules, five with nothing lost, that moved
F3, F6, F7 and F10 as much as F12 itself; the two knob-dependent integers
that every earlier fit had reported are closed by two of them. The
seeded pipeline is 85 runs behind the hand-steered fit (3713 against
3798) now that the enum sweep re-descends integers inside each flip; the
seedless pipeline reaches 1840, and every "from-scratch" figure before
2026-10-20 was in fact seeded (the fitter rewrote missing seed files
from the code). The seeds encode what the families cannot order: the
queue storage before the request and I/O rules are known, and the I/O
integers the END block scores all-or-nothing. The tenth fit's family
F14 was built as a ladder varying one format property per pair, and it
answered finding 2 directly: of width, register, direction bit and the
write, only the direction bit of a read-only form and the absence of an
ALU-op field change the timing. Six rules, nothing lost on F0–F12, the
largest gain since the sixth fit. The eleventh fit's F15 (840 runs)
confirmed that reading with the AND control, and its POP r/m rule (the
stack first, the reg field decoded after the read) is the first
template-order change since the fourth fit; seven rules, +84 −10. The
yield per family is holding (ninth +197, tenth +135, eleventh +84,
twelfth +42 on F0–F12, each from one designed family), and the misses
on F0–F12 are down to 303 of 4352. The twelfth fit's F16 (1,014 runs)
was the ladder the eleventh asked for, and it refuted the bit reading
outright: all eight D0/D1 reg values and both widths behave alike and
the one-pass ALU forms do not, so the split is by operation unit,
which the model already had as a class. Its four rules gained +349 with
nothing lost on any family, the first fit since the tenth with no loss,
and what is left on F0–F12 concentrates in the OUT frame at odd parity
and in refresh. The seeded pipeline from stage 3 reaches 3964 against
the hand fit's 4049: its stage 3 took `request_eval=every_clock` for the
first time and stage 5 paid for it in another integer basin. The
thirteenth fit took no new data: re-reading the OUT-frame misses of six
families at both parities found one mechanism where the twelfth fit's
findings listed two, and its eight rules gained +283 with nothing lost
(+81 on F0–F12), closing F12 A OUT, F14 G, F15 P OUT and F16 L OUT
outright; the misses on F0–F12 are down to 222, mostly the immediate
memory forms (item 1), the DW I/O forms after a register form (item 3)
and the F6 drains (items 4 and 7). The register divide had been left out
of the register-only classes by the twelfth fit, a class-membership
omission the OUT frame exposed at once. The fourteenth fit's F17 made
the one quantity the refresh model had been fitting per run into an
observable: by turning refresh on from inside the chain, with the
prelude refresh-free, the timer's phase at clock 0 was read off as a
constant of the prelude (the same over 250 runs per wait setting), the
timer itself as a free-running counter that the RFM write does not
restart, and the write's own cost and delay as integers; the per-run
alignment came out of the fit with nothing lost. Three corrections to
the design brief came back with the data (the DS1 prefix is 26h, the
assembler drops a leading `DS1:`, the SFR write makes no pin cycle),
which the record keeps as the kind of thing only the board decides. F17
also recorded refresh-on runs whose first LS is exact, so its EU rules
were fitted against known clocks for the first time; F13 S went from 0
to 16 exact. The fifteenth fit's F18 (1,164 runs) put the two
observables the fourteenth asked for in place: a marker closing the
prelude, which showed the first LS's start to be single-valued per
prelude cell, and a ladder on the unit forms' exec clocks, which gave
three rules (+65 −0 on the refresh-on families) and resolved the F17
split as the previous refresh's recency. Modelling the prelude's tail
from its register loads reproduced every refresh-off prelude cell with
no fill table, a derivation of the fill the record had declared an
input, but not the refresh-on cells, so the alternative stays in the
code unadopted and the start is observed, not derived. The refresh-on
families are now 572 of 2,472 exact; their misses concentrate in the
END block's HALT (about 350 runs) and the unobserved prelude. The
sixteenth fit's F19 (1,290 runs) began by re-reading the misses it was
sent after, and found the findings list stale: item 3 stood at 30 F10
runs when F10 had 2 misses, and item 1 named cells that were exact
(both corrected above; the counts in the list are now regenerated from
the scorecard, not carried). What was left was smaller and different,
and the ladder settled it: the immediate forms' data cycle is a count
from the start with the immediate's width in it and the displacement
free, and the DW forms do not use the port latch. Three rules, +18 on
F0–F12 and +214 on F19, nothing lost. The stage 5–7 descent from the
hand fit with F19 in its objective improved no stage and drifted on
ties into nine enums that cost 51 runs outside the stage families: the
stage objectives are now narrower than the corpus, which argues for a
guard over every family in the descent before the fitter is next
trusted to move an enum. The catalog's `out_dw_al` is EF, the word
form, so the END block's OUT has been a word I/O all along; the model
scored it exactly under either name, so nothing moves, but the record
is corrected. The seventeenth fit's F20 (3,594 runs, the largest
family) was the ladder finding 4 had asked for since the seventh fit,
and it took the four groups apart into three mechanisms with their
controls in the same family: the request flag (the F6 drains, 18/18),
the ModR/M's word-mate (the 4-byte form, with the base+d16 loads as the
displacement control) and the start on a back-to-back fetch below 3
stored bytes (the 8B forms and the `MOV AW,DW` pairs, 32 of 32 against
248 of 248). Five rules, +393 with nothing lost, F0–F12 at 97 %, and
the OUT-frame F6, F10 and F12 series exact. The agent reported that
its facts file was written while the rules were being prototyped on
the old corpus during the acquisition, not strictly before them; the
F20 data then moved the prototype from 1025 to 1149 of 1198 at 0 waits
before any F20-specific change, so the rules were not fitted to the
data they are evidenced by, but the order is recorded. The fitter got
the whole-corpus guard the sixteenth fit asked for, and it exposed a
second flaw at once: the guard measured against the current
configuration traps a descent at the seed's value, so the reference
is the stage's input. The repeats showed a harness field (`strobe`, 7
against 8) differing in 12 of 360 repeat rows with every timing field
identical; nothing reads it. The eighteenth fit's F21 (3,576 runs)
was the EA ladder the seventeenth asked for, and it found the address
path to have two costs and no others: a displacement costs the clock
it is taken in whatever its width (a d16's two bytes go together when
queued, so base, index and direct with d8 or d16 are one class and the
mod 00 forms one clock earlier), and base+index with a d16 one clock
more; the displacement is taken after the EA clocks for the immediate
forms as for the others. Seven rules and two refits, +409 with one run
lost, the first loss since the eleventh fit: a refresh-on F17 run whose
RFMON store, itself a direct-address immediate store, ends 2 clocks
late when a refresh is served inside the new head; its refresh-off
twins are exact, so the loss is recorded against the refresh machine
(item 8 h) and taken. Two process findings: `imm_head=split`, refuted
on F19 at −63, was right in the pair the ladder exposed (with
`sync_req=disp`), so a refutation is of a configuration and the
alternative stays listed; and three facts read off during the rule
work are in the facts file's addendum, marked as such, the facts above
them written before any rule. The `strobe` field differed again in 5 of
360 repeat rows. The nineteenth fit took no new data. Its agent was sent
after two groups read off the eighteenth's scorecard as "one alignment
per lead" and "every d8 at waits"; it tabulated the misses by the queue
count and the fetch in flight at the displacement's take first, and the
groups dissolved into three take states with no exact cell in any of
them and no missed cell outside them. The brief's first hypothesis (the
late take is the decoder's, not the immediate form's) was right but
changed nothing on its own, the loads' `late_read` already covering it;
it mattered only once the next opcode was held in the queue through
the address, which is the rule that carries the gain. Four rules, +469
with nothing lost, and the fitter's stage 5 moved nothing from the hand
fit. The `ES: NOP` group was read to its state (7 bytes stored at the
start, the aborted cycle not firing) but no structural rule was found;
the one alternative tried is recorded as refuted. The twentieth fit
took no new data either. Its agent was sent after item 10 a as
`hold_count=ahead`'s discount of the immediate bytes still to take; it
logged every clock on which a posted memory request, a free bus and a
wanted fetch met, with the request's setup phase, the queue count, the
bytes outstanding and the fetch's provenance, before touching the
simulator, and the discount was not the handle: PUSH's write at 3
bytes with nothing outstanding is held as the store's at 4 with 2. The
handle is the fetch's provenance (first requested on the delivery
clock of the fetch that just ended) and the request's phase (the eve
of its fetch-free clocks), and it carries POP r/m's stack read (10 b)
and the PUSH follower as well; the `ES: NOP` group (10 c) fell to a
floor the tabulation of 9,420 data cycles showed every mod 00 form
keeping. Five enums, +216 with nothing lost. `fit --stage 5` from its hand fit under the family guard ran the seven
grids and the sweep (9,216 structures, 10,387 s) and chose nothing
(6950/7200 on its families, guard 2565/2582, 656 of 697 descent moves
refused, one tie on exact runs, `odd_split`, resolved by the guard);
`fit.json` is byte-identical to `fit-wp29-hand.json`. The stage-5 seed
now carries this fit's enum values (the old seed is in `wp28b/seeds`). The twenty-first fit took no new
data either. Its agent tabulated the displacement takes against the
I/O issue clocks, the fetches wanted only through the IR's slot, the
RMW's read-to-write spacing against a fetch between and the immediate
forms' starts beside a fetch, before any rule; the base+index+d16
group was two states (the take on an I/O issue clock under the OUT
frame, the IR's room inside the EA clocks under PUSH), and the agent
recorded that its other candidate for the first, a fetch no earlier
than 4 clocks after any take, reads the same on this corpus because
the I/O is 3 clocks in every cell. Four enums, +118 with nothing lost.
`fit --stage 5` from its hand fit under the family guard ran the eight
grids and the sweep (9,216 structures, 10,792 s) and chose nothing in
any grid or in the sweep (7068/7200 on its families, guard 2565/2582,
one tie on exact runs, `odd_split`, resolved by the guard); `fit.json`
is byte-identical to `fit-wp30-hand.json`. The stage-5 seed carries
this fit's enum values (the old seed is in `wp29b/seeds`). The twenty-second fit took no new
data either. Its agent classified every left-out write's slot by room
and bus history and every TEST/CMP first data cycle against its ADD/AND
twin before any rule: the `CMP [BW],imm8` alignment split was the
slot's room rule, the TEST residuals three places of one fixed lookup,
and CMP r/m,reg's late end the tenth fit's refuted `slot` reading,
wrong then only for want of the slot rules that now exist; two of the
three long-standing knob dependences (`rmw_imm.istart`, `load_alu.fdisp`)
were these. Seven enums and three integers, +116 with nothing lost;
stage 5 ran nine grids and the sweep and chose nothing. The
twenty-third fit took no new data either. Its agent tabulated every 8B
register form's take state against the next instruction's start, every
reissued request against the NOP that started on its clock, and every
port-byte take against the bus on that clock, before any rule: the IR
load's clock is visible in exactly two states, and the one `reg.nx`
value that fits both needs the load a clock later after a take on an
I/O issue clock, which is the whole of the dependence the knob report
had carried since the ninth fit. Six enums and one integer, +42 with
nothing lost; the fitter's stage 4 (F3), whose grid was empty before, now carries it
with `reg.nx` in {1, 2} (288 structures), and a stage-6 grid after
`F20_REVISIT` carries it for F19 D and F20. `fit --stage 4` from the
hand fit under the corpus guard (847 s, 32 of 35 moves refused) chose
the two ties, `nop_hold=io` and `abort_latched=full` (+0 −0 over the
whole corpus), and the hand fit is kept as `fit.json`; stage 6 was not
run (its grids take hours) and is due when the fitter is next touched.
The seeds carry this fit's values (the old seeds are in `wp31b/seeds`). The
twenty-fourth fit took no new data either. Its agent read the four
groups left on the refresh-off corpus to their states before any rule
and closed three; the fourth it left open with the reason the corpus
gives (no cell separates a read from a write posted on a non-wait
clock), the two rules that would have closed it being fitted to the
three runs of one cell. One closure is a reversal: the twelfth fit's
kept end clock for an aborted-start multiply was adopted on runs where
a retry fetch hid it, and the three runs where it shows have the early
end. The agent disclosed running throwaway prototypes before writing
the facts file and reverting them; every tabulation is from the
unchanged model. Four enums, +14 with nothing lost; stage 5 chose a
tie. The twenty-fifth fit took no new data either and worked the
refresh side. Its agent tabulated every prefix-matched refresh request
in the END block against HALT's start before any rule, and the
forbidden offsets dissolved: the halt status holds the bus unit two
clocks and a posted I/O's lead two more, and the runs the record had
read as served three clocks late were the EU running two clocks ahead
of the bus after a refresh beat the fetch its take sync counted. One
of the five rules is not strictly dominant: flipping the refresh's
exclusion from an I/O's lead back gains 38 runs with a third fetch in
HALT and loses 116; the 38 are recorded as open with their reason.
The prelude under refresh and F13's first divergences produced facts
and no rule. Five enums, +441 with nothing lost; stage 8 offered a
trade the fifteenth fit had refuted and it was declined. The
twenty-sixth fit took no new data either. Its agent tabulated the END
I/O's setup count clock by clock with the reason each uncounted clock
is uncounted, the queue's flag and room at HALT for every refresh-on
run, and every loop eve with a request pending, before any rule: the
37 rows were the early fetch run as the count sees it (the wait states
moving with the issues, which the previous package's prototype had not
moved), the F13 runs were a request lost to a refresh and not
evaluated again until the queue changed, and the fifteenth fit's
loop-eve window had measured the hold of a refresh already on the
bus, not the acceptance of a pending request, which silicon takes at
the eve in 7 of 303 decisions. Three enums, +245 with nothing lost;
stage 8 chose no move. The twenty-seventh fit took no new data
either. Its agent tabulated every instruction start inside a refresh
cycle's window by the instruction before it, every refresh request
inside a register shift's and multiply's exec window by its offset,
and the multiply's retry after a refresh held in its exec, before any
rule: the NOP train's late clock was the NOP's empty operand take, a
step in the template with no counterpart in the machine, letting the
next start through where every other start waits; the multiply's and
the one-count shift's remaining requests were an exit the template did
not have; and two states found in the re-read, the aborted request
under a refresh and the I/O lead's first free clock, closed cells the
record had not named. Six enums and two integers, +439 with nothing
lost; stage 8 chose no move. The twenty-eighth fit took no new data
either. Its agent first grouped the 520 middle-phase runs by the
instruction at the first divergence, then tabulated every refresh
between a memory shift's read and its write, every refresh in its read
setup, every request raised while a take sync waits on an aborted
cycle, and the count-byte shift's start on a refresh, before any rule:
the memory shift's write setup has the register shift's shape
end-aligned to the issue, where the fifteenth fit had put even
distances; the aborted cycle's sync clocks are the EU's own; and two
states found in the re-read, the posted request's first clock and the
write-back sync, closed cells the record had not named, one of them on
matched events alone (no exact run gained; kept and marked, a tie in
stage 8). The multiply and divide windows are exact in 884 of 885
prefix-matched requests. Seven enums, +127 with nothing lost; stage 8
chose nothing. The twenty-ninth fit took no new data either. Its agent
tabulated every refresh served inside a register shift's exec or count
loop before any rule, and the loop's parity was not the loop's: every
refresh inside the loop costs the same wherever it lands, and the
parity comes from the exec's end, where a refresh on the boundary 4
clocks before the loop holds exactly one clock. The fifteenth fit's
`refresh_recent` window, which had carried a dependence by waits and
marker through fourteen fits, had held 0, 1 or 3 clocks there by the
previous refresh's age and was right only where it happened to give
1; it is no longer read, and the knob report is empty for the refresh
integers too. Three smaller states closed the SFR store's setup (the
only refresh-off runs gained since the twenty-fourth fit), the I/O's
count under an earlier refresh and a request lost inside a unit. Four
enums, +234 with nothing lost; stage 8 made no move. The thirtieth fit
took no new data either. Its agent regrouped the 195 refresh-on runs
left in the middle and the END block, read every refresh-beaten fetch
and every instruction start on a refresh's first clock, and closed two
states; it also measured the first LS's offset per refresh-on prelude
cell, found a constant per cell that would close about 154 runs, and
declined it as a per-cell alignment, which the record agrees with. Two
enums, +15 with nothing lost; stage 8 made no move. The harness
extension that followed (no fit change) kept the existing score
byte-identical for every run under the new normaliser before anything
in the model moved, read the pre window off every run, ran the tail
from the POP read with its counter read off rather than tabled, and
stopped at the gate: a candidate that gains 192 and loses 51 is
recorded with its losses named, not adopted. The thirty-first fit read
those 51 before any rule, each group to a state the chains also carry
(the port form's lead, 37 requests; the post under a refresh, 2,008
lost requests; the data-latch wait, 17; the beaten fetch's delivery at
0 waits, 1,201 rows), met the gate and adopted the tail: the two
stand-in tables leave the fit, and the per-cell offsets the thirtieth
fit had measured are now the model's own. A test the fitted
configuration runs on generated chains caught an overfill in the lead
rule's first version, which was fixed and the figures retaken before
the hand-back. Four enums and one counter entry, +211 with nothing
lost; stage 8 made no move. The thirty-second fit recorded F22 on the
board (660 chains and 66 repeats per wait setting, none failed or
differing) and read it as a ladder before any rule: the first table
compared every immediate RMW cell with its store twin and found no
difference through the first data cycle, which retired the "kind of
request" reading the twenty-fourth fit had left tied with the wait
state, and the three runs were a missing integer the store already
had. The kind mismatches the score reported were named first (an extra
fetch the store's state already holds, a read on a delivery clock, a
late displacement take) and each was one of the three findings. One
integer and two enums, +3 −0 on F0–F21 and +247 −1 on F22; stage 5
chose nothing. Stage 6 then ran every grid from the hand fit under the
family guard and gained nothing; its ties, scored one by one as flips
of the hand fit over every family, gave the thirty-third fit's one rule
(the I/O setup counted from the post, +2 −0) and showed that the
fitter's tie-break families, which then left out the refresh-on ones,
let it pick by enumeration order among alternatives that are not equal
on the whole corpus (every family is in the tie-break since 2026-10-27);
the hand fit, not the fitter's output, is the fit.
F13 (462 runs) settled the refresh facts (the RFM fields, the
length − 2 stall, the loop-boundary acceptance, MULU) in one family, but
its rule search ended in a per-run alignment, which this record keeps
out of the fit: the refresh-on families stay a facts result until the
fill phase is observable.

Decisions: PUSH is the reference marker; OUT-marked chains are in the
objective from the fifth fit on. Queue, decoder, release, memory-template,
I/O, data-latch, HALT-status, read-port, start-sync, latched-byte,
EA-class, displacement-take, free-clock-hold, I/O-issue-take,
left-out-write, register-form-load and group-clock-hold structure
are each settled on their families, and the refresh-off corpus is
exact outside F8, with F22 at 1314/1320; refresh has its bus side,
its stall rule, its timer (a free-running counter, its phase a constant
of the prelude) and the count loops' boundaries (shift, multiply,
divide and the memory shift, the loop's eve gated by the previous
refresh's recency), HALT's status clocks, the END block's count, the NOP's end under a
refresh, the unit forms' exits, the memory shift's boundaries and
the loop's entry and the prelude's tail settled, with no knob
dependence anywhere; no per-run alignment is in the fit or
reachable by stage 8. The stage seeds
and the counter at the POP read per RFM and WTC (`refresh.POP_COUNTER`)
are kept as declared inputs (storage, the I/O integers, the END-block
pair, the timer's state at the prelude's read) rather than searched for. Next:
the 153 refresh-on runs left in F8, F13, F17 and F18 (175 before the
thirty-sixth fit; the thirtieth fit's open states and the cells under 20 runs), read to
their states with no rule, when a state separates one of them; the
six F22 runs of `TEST [BW+200h],imm16` after the OUT marker (item 1)
when a state separates them from the chains' cells; the fitter's
stage objectives (the seeded pipeline's start file, its stage-3 `request_eval` choice
and its stage-5 basin, stage 6 and 7 under the corpus guard) when it is
next touched. From 2026-10-27 (the F25 forms and the thirty-fourth fit,
with the inert rules dropped, landed that day): F23's flush and refill in
the model as classes and templates fitted with the corpus guard; F25's 142
misses as state reads, the frame-state ones first (LDEA's queue room at pO
and its straddling d16, the immediate push under OUT, PUSH R's first write
at pO, the segment forms' parity clock, PREPARE's wait slope); F28's 268 and F29's 29
misses left by the thirty-seventh fit (the I/O a clock late under a refresh
on the post clock or beside the relatch, 51; the PUSH-frame END refreshes,
33; the beat train's fetch requested on D, 37; the 1-wait beat cells, 22;
F29's base+index+d16 DW cells and the gih n2 pO reads), each when a state
separates it;
F27's remaining misses and the three refresh-off controls; the `dio` pE
base+index+d16 read and a longer `port_issue`
ladder; F23's 105 and F25's 142 misses as state reads (the transfer's
fetch in flight and latch at its start by parity first); and the
cleaner-mechanism experiments in
the order the RTL phases need them (the latched byte's port and the
reissue, `alu_busy` and `unit_hold`, the posted request's window).
