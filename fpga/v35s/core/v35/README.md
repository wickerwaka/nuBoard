# V35S core v2 (`fpga/v35s/core/v35/`)

Design record: `docs/v35s-core-v2.md`. This README holds the per-directory notes.

## MX0: the microprogram, the registered-ROM sequencer, the register-form routines

Design: `docs/v35s-mechanisms.md` (sections 3, 4, 7, 8). MX0 replaces the fitted sequencer
(`v35_ucode.sv`, 4,916 lines, its generator `ucgen.py`, the class, template and EA tables) with a
microprogram: a ROM of microinstructions, one a CPU clock, written by hand in
`urom/*.uasm` and assembled by `validation/v35s/chains/uasm.py`. Everything below "MX0" in this
README describing rows, classes, templates, counts and the T / P passes is the record of the
retired sequencer; the module table's `v35_ucode` / loader / EU rows are superseded by this
section.

### The microinstruction (`v35_pkg::v35_uword_t`, 86 bits, MSB first)

| Field | Bits | Meaning |
| --- | --- | --- |
| `ra`, `rb` | 5, 5 | the register RAM's read ports A and B: a register selector (`RS_REG` / `RS_RM` the ModR/M fields, `RS_OPR` the opcode's bits 2:0, `RS_DST` / `RS_SRC` by the direction bit, the eight word registers by name, `RS_SREG` / `RS_SOPR` a segment by the ModR/M reg field or the opcode's bits 4:3, the four segments, `RS_BASE` / `RS_INDEX` the ModR/M mode's EA registers) |
| `wr`, `ws` | 5, 4 | the write port's register (and `RS_PSW`: POP PSW's bits 11:0) and its data source |
| `wid` | 2 | the width of the word's register accesses and ALU op: the format's, byte, word, the high half |
| `d1 s1`, `d2 s2` | 3+4, 3+4 | two moves into tmpa / tmpb / tmpc, the address register, the write datum OPRW, from a source (`SR_*`: RA RB TA TB TC SIG IMM IMM8 OPR PSW ONES DISP ADDR ONE ZERO) |
| `alu`, `ax`, `ay`, `wf` | 5, 4, 4, 1 | the ALU operation into SIGMA and its operands; W (the flags written). The format's group op, AND, INC DEC NOT NEG, INC2 DEC2, the sign extensions, the shifter's load / one step / flags, the multiply's and the divide's init / one bit / finish, the flag operations, SAHF |
| `ea` | 2 | the EA step into the address register: the popped displacement, or base + index + displacement |
| `bus`, `seg`, `resv` | 3, 2, 1 | a request posted on the A1 port (memory read / write, I/O read / write), its segment (the default: a prefix's, else SS for a BP mode, else DS0; SS; DS1), the reservation raised |
| `pop` | 3 | a queue byte popped into the ModR/M, immediate (IL IH) or displacement (DL DH) register |
| `e`, `f` | 1, 1 | E (the next opcode popped; exactly one word follows, the dispatch) and F (wait for the datum) |
| `cnt` | 3 | the loop counter's load: port B's low byte (CL), the first immediate byte, the operand's bit count (8 / 16), the instruction's bytes still to pop (the trap routines) |
| `seq`, `cond`, `tgt` | 4, 3, 10 | next, jump, jump on a condition (counter zero, SIGMA's sign, the divide error, a word format), call, return, loop (counter step, jump while not zero), DISPM (dispatch on the byte this word pops: the 0F page), DISP (the word after E: dispatch on the decode) |
| `pfx`, `flush`, `halt`, `trap` | 1 each | the segment prefix set; the queue flushed to the immediate in PS; halted; the divide error raised |

No field is a count of clocks, a class, an attribute of another instruction or of the bus unit
(`test_uasm.NoCounts`, `test_v35_struct.MX0`). The ROM is three 32-bit banks
(`v35_urom_b0..b2.hex`, bank k the word's bits 32k+31..32k). 411 words, 69 routines.

### The assembler (`validation/v35s/chains/uasm.py`)

`python -m validation.v35s.chains uasm [--check] [--list] [--book]`. One file per routine family
(`core` the reset, the 0F head, the traps, the prefixes, HALT; `reg` the register forms; `loop`
the shifts, MUL, DIV; `bus` the stack, the direct stores and loads, I/O, the far branch). A
routine's header names its opcodes (and the ModR/M `mod` / `reg` / `rm` cells it takes), the
data book form (`book=`), the declared difference (`diff=`) and its reason (`why=`), the measured
V35S cost (`measured=`); `resv=e` makes the decode raise the reservation at the opcode's E pop.
Every word carries a comment naming its act. The word layout is read from `v35_pkg.sv` (the
single source). Outputs: the ROM banks and `v35_udecode_tbl.svh` (`v35_udec1`: the opcode -> the
entry and the format bits w, d, immw, sx, op3, seg, len, rq; `v35_udec2`: the opcode and the
ModR/M byte, or the 0F second byte -> the entry and the group's op; `v35_umodrm` / `v35_upage`:
the bytes a ModR/M or 0F second byte adds to the instruction's bytes still to pop). The format
bits are the encoding's (`uasm.fmt_of`); every cell without a routine decodes to a trap routine
that pops the instruction's bytes (counter from the loader's count) and ends (reported, not
executed; the function bench counts it `trap_nop`).

**The book check** (`test_uasm.BookCheck`): the routine's length, run by `uasm.length` from its
entry at EA = 3, W = 0 with no queue stall (a request granted the clock after its post, a bus
cycle 3 clocks, F and a write's E hold waiting for its end), equals the book's value plus the
declared difference. All 55 routines with a book form pass; the differences are the measured
V35S costs (classes.md, v35s-eu-timing.md, v35s-chains.md F1/F3/F5).

**OPEN words.** A word the measured cost needs whose act the sources do not name is written
`open` and its comment starts `OPEN`; its routine's `why` says so (`test_uasm` enforces both).
There are 54 in 15 routines: the acc / register immediate forms 1 each (before the pops: the
immediate leaves the queue three clocks after its opcode in the fitted model's take times;
mechanisms 3.2's "word load under the pops" is the candidate, not built), the shifts 6 / 5 / 4
(CL, imm8, by one; the V35's iteration is two words, built; the fixed part's extra clocks are
open), MULU 11 / 12 (r16, r8), OUT imm8 5 and OUT DW 3 (the I/O write is posted on the E word and
not waited for: the markers show it leaving 3-4 clocks after a post following the datum; the
clocks before it are open). They are the agenda the user's rule puts on MX0: each is a clock with no machine
explanation yet. Routines not in the gate families (DIVU, DIV, MUL, CVTWL, IN, POP, PUSH imm,
the far branch, DI / EI) carry their natural shape and are short of silicon by the declared
amount (`why` OPEN), not padded.

### The sequencer (`v35_useq.sv`, 225 lines, 26 ports; `v35_ucode.sv` and its 4,916 lines are gone)

The ROM word is a register (read at `ce_a` with the next address computed in tick B); the
microaddress is a register. The five stalls, each from registered state in tick A, a stalled
word performing none of its acts: q (an operand pop with the queue empty, or E with the staging
register empty), f (F and the datum not here), slot (a post while the EU's one request is
outstanding), hold (E while a memory write is outstanding with RAMEN = 1; an I/O write is posted
and not waited for), halt. Next address: the same word (stalled), next, jump, conditional jump, call (one
return register: the V20 ROM's FARJMP subroutines nest one level, V20UC.TXT 0000-04FF has no
FARJMP inside a FARJMP target), return, loop, DISPM (the 0F second byte), DISP (the decode of the
registered opcode and ModR/M). The loop counter is 9 bits. The decode's entries are registered
at `ce_b`; no queue byte reaches the address except through a register (the 0F page head's
popped byte is the one byte decoded as it is popped, by the word that pops it).

### The loader (`v35_loader.sv`, 234 lines, 37 ports; it was 704)

The staging register `s` (the queue's seventh slot, variant B's staging byte, `stg`) holds the
next opcode: it loads from the queue's head when it is empty and the running instruction has no
byte left to pop (`need`, the instruction's bytes still to pop: set at the E pop from the
decode of the staged opcode, extended at the ModR/M / 0F second byte, counted down by each pop;
while bytes are owed the staging slot stays counted). The E word pops the staged opcode into the
opcode register and, for an opcode with a ModR/M byte, the ModR/M byte from the queue's head on
the same clock (two bytes: the fitted model's starts take the opcode and the ModR/M together); a
routine's pop takes the queue's head. `fmt`, `opc` and `modrm` (the running instruction's) load
at the dispatch: the word after E still runs the last instruction's acts while the opcode
register holds the next. The queue's port is unchanged (`rd`, `rel`, `stg`; Q2's strobes:
`t_start` a routine's entry word executing, `take_now` an operand pop, `l_pop` the staging load).

### The datapath (`v35_eu.sv`, 471 lines, 46 ports; it was 1,870)

The register RAM's two read ports (addresses latched at `ce_b` now, `v35_regram`: a word reads
what the words before it wrote, no forwarding), the write port, tmpa / tmpb / tmpc, SIGMA, the
PSW and the segment flops (beside their RAM words), the address register (`v35_ea`: the EA step),
the write datum OPRW, the A1 request register (address = segment + the address register as the
posting word leaves it; an odd word's second half's address after the acknowledge; a read's
datum latched at `req_done`, an odd word's first byte at its own end), the reservation (a
request standing, a word's `resv` until the acknowledge, and the E clock that pops the opcode of
a routine marked `resv=e`). The
shifter runs one step a word (`v35_shift1`, the flags at the end `v35_shift_fl`), the multiplier
one bit a word (`v35_mul_init / step / fin`), the divider one restoring step a word
(`v35_div_init / step / fin`); `v35_shift`, `v35_mul`, `v35_div` stay in `v35_fn_pkg` for the
function bench.

### Depth (by construction; the levelizer and the routed timing are the overseer's runs)

Tick A: the ROM word's selectors into the RAM's read address (a 23-way register selector into
7 bits: about 5 levels); the stall terms (a few registered bits); the decode lookups (the
opcode / ModR/M / staging registers into the generated case tables, 256-entry LUT logic: about
6-8 levels) into ce_b registers; the bus unit's grant on the request register (A1's four
levels). Tick B, the deepest: the RAM's read data -> the lane select -> the source mux (15-way)
-> the ALU (`v35_alu`'s 17-bit add / subtract and the flags) -> SIGMA / the PSW: the ALU path,
estimated 12-14 levels with the carry chain; the divider's init (`v35_div_init`: a 32-bit
negate and a 16-bit compare on the RAM data) is the longest single path, estimated 15-18 levels,
and is the first candidate for a split (its operands are temporaries a word earlier, so a
register on its input costs no clock); the next-address mux (9 sources on the word's `seq` and
registered conditions: about 4 levels) into the ROM address; the request address (the segment
+ the address register: a 20-bit add, about 8 levels).

### MX0b: the word register

The EU's byte source is now a registered word (`v35_loader`: `w0`, `w1`, `wn`), loaded from the
queue's stored bytes only (the queue gained one read port, `stored` = its stored count: never
this clock's arriving word, never the variant-B latch), one load a clock: the queue head's aligned
word (one byte from an odd address, or the one stored byte). Every pop (the staging load, an
operand, the E word's ModR/M) takes the word register's next byte; a pop with it empty stalls
(stall q) and the load happens at the clock's end. The queue's `rd` is the load, `rel` the pops:
the word register's bytes stay counted (unreleased) until popped. `V35_MX0B_WR` selects the law
(`v35_macros.svh`); the three candidates were measured on the gate families at both waits:

| Law | exact (gate, +v35_chk) | restart fetch vs silicon, mean dt at 0 / 1 / 2 waits |
| --- | --- | --- |
| 0: ripeness (pop the stored bytes directly) | 128 | -0.48 / -2.95 / -9.88 |
| 1: the word register, loaded at the end of a clock that empties it (kept) | 128 | -0.48 / -2.95 / -8.88 |
| 2: the word register, its load a clock of its own | 124 | -1.67 / -3.67 / -9.67 |

None closes the wait-dependent gap: silicon's EU consumes the prelude's MOV r16,imm16 stream
slower than the fetch rate at 2 waits with its queue full, which no byte-path law here produces.
Removing the eight OPEN words placed before the immediate pops (the word register was to
explain them) gives 0 exact under every law: they stay, OPEN. OUT imm8's early reservation is
removed (an I/O reservation stops the fetch silicon makes before the write; the post is on the
E word).

### MX0c: the dispatch and the fetch

The frozen model does not start an instruction while the bus unit runs a fetch cycle
(`sim/frozen/eu.py` _start, `bus.fetch_inflight`), nor a ModR/M form on the clock a
back-to-back fetch issues (`queue.b2b_at`). Built as a sequencer stall on the dispatch word
only (the word after E: the staged opcode into its routine's entry; trace `W:fetch`), from the
bus unit's existing registered outputs (`fetch_inflight`: a fetch granted on an earlier clock
runs on this one, through its last clock; `b2b_now`: a back-to-back fetch issues now) and the
decode's `has_modrm`; no output added. The loader's pops read `ex_pop` (the stalls a popping
word can meet: a dispatch word never pops). `V35_MX0C_DISPATCH`: 0 none, 1 the fetch stall,
2 and the ModR/M rule. Measured on the gate families, both spacings, `+v35_chk` (tables
identical at both):

| | exact | restart fetch vs silicon, mean dt at 0 / 1 / 2 waits |
| --- | --- | --- |
| A (0, MX0b; the default) | 128 | -0.48 / -2.95 / -8.88 |
| B (1, the fetch stall) | 0 | +0.79 / -3.21 / -4.20 |
| C (2, and the ModR/M b2b rule) | 0 | +0.79 / +0.79 / +0.80 |

C removes the wait dependence entirely (the restart's offset is the same at every wait setting),
which is the evidence that the law is silicon's: the starved queue's slower consumption is the
dispatch waiting for the fetch in flight. It loses every exact run because the routines' lengths
were set to the standalone measured costs with no dispatch stall in them: a NOP train (4, no
OPEN word) now pays the stall on top, and the restart sits a uniform 1-3 clocks late. Removing
the OPEN words before the immediate pops and two of the shift's common OPEN words moves the
offsets (F9's mean prefix 0.12 -> 0.21) but no run becomes exact. The routines need re-deriving
with the stall in place (their measured costs include it where the fill is running); that is
the next step, not taken here, so the default stays A.

### MX0d: C the default, the routines from the data book

`V35_MX0C_DISPATCH` defaults to 2 (C). Every routine's length at EA = 3, W = 0 is the data
book's formula: all 55 book rows pass `test_uasm` with no declared difference. The measured
V35S costs are no longer a reason for a word (the a6 sweep timed each form between I/O markers;
the form's pops make room, the room issues a fetch, the next marker's dispatch waits inside it:
measured = book + the dispatch's stall). The OPEN words placed to reach measured costs are gone
(54 -> 0); a book clock with no act is OPEN with the book as its reason: 135 such words in 21
routines (PUSH r 4, PUSH imm 2 / 2, POP r 5, POP PSW 7, MOV acc,[d16] 1, OUT imm8 6, OUT DW 4,
IN DW 11, IN imm8 11, BR far 7, SHL CL 5, SHL imm8 2, SHL 1 2, MULU 9 / 10, DIVU 14 / 16, DI 2,
EI 10, CVTWL 5). Shapes that combined acts to meet the book: the two-operand register forms read,
compute and pop on the E word (2), TEST reg,reg (4), the unary group (5), MOV sreg,r (4), the
prefix's register on its E word (2), MOV [d16],acc's EA step, datum and post on one word (8).

A fourth placement was measured: the stall on the E word (the staged opcode's pop, `3`): the
restart offset becomes wait-dependent again (-1.1 / -2.1 / -3.1), so the dispatch word stays.

Gate families, `+v35_chk`, both spacings: 0 exact (A 128, C-as-built 0). The restart's offset
is flat across the waits in every family (mean dt at 0 / 1 / 2 waits): F0 +0.67 / +1.00 / +0.67,
F1 +1.0 / +1.0 / +1.0, F2 +0.93 / +1.02 / +0.93, F3 +1.0 / +1.0 / +1.0 (|dt| 4), F9 +0.95 / +1.07 /
+0.95, F11 +0.91 / +0.95 / +0.91, F12 +0.29 / +0.29 / +0.29 (|dt| 3.1); F0w -3. The offsets by
routine: PUSH r (the markers; book 13 against the measured 9: the write 5 late), OUT imm8 (the
fetch 2-4 early: the port byte popped on the routine's first word), NOP (+1: book 4, silicon's
NOP train 4 including the stall), OUT DW (END's write 3 late: book 8), MOV [d16],acc (+1).

### MX0e: the book shortened by silicon's direct measurement

The rule: a routine never carries a clock without an explanation; a clock may be removed on
silicon's direct measurement (the a6 sweep's cost, docs/v35s-eu-timing.md, the chain families'
per-form costs, less the dispatch's stall where the a6 method put a fetch under the marker's
dispatch); a clock is added only as a named act or as a book clock marked OPEN. A clock the book
charges and silicon does not spend is a book error. Declared differences (all shorter than the
book, each naming its measurement; `test_uasm`): PUSH r16 -5 (13 -> 8: a6 9 less the stall, the
acts merged: SP, the address and the datum on one word), PUSH PSW -1, PUSH imm16 / imm8 -1 / -1,
OUT imm8 -2 (11 -> 9), OUT DW -3 (8 -> 5: END's write 3 early in MX0d), IN DW -3, IN imm8 -1,
XCH reg,reg -1, MOV reg16,sreg -1, MOV sreg,reg16 -2, XCH AW,r / NOP -1 (4 -> 3), CVTBW -1. SHL
r,CL keeps the book's 11 + 2n with one of its five OPEN words moved onto the loop's path (n = 0:
silicon 10 less the stall, 9). MOV [d16],acc stays at the book's 8: its acts allow no shorter
routine (silicon's marker is one earlier: a residual). OUT imm8's OPEN words sit before the
port's pop (the restart fetch was early). OPEN words 135 -> 122.

### MX0f: the three residuals in every chain

Each traced on the side-by-side event trace (frozen model | RTL, clocks from the fill's end).

1. **Q2's start is the opcode's read** (built, `V35_MX0F_QSTART` 1; 0 is MX0e). Q2's triple
   clock (the aborted fetch) is three queue reads on one clock: the start's opcode, an operand
   take and the IR load. MX0e drove the bus unit's `t_start` from the routine's entry word; the
   opcode leaves the queue on the E word, one dispatch earlier, so a routine whose first word
   pops an immediate (MOV r8,imm8, `pop=il` at its entry) made a false triple clock. F3-push-nop-k1-pE-w0:
   `+98 S:u354 T:1 L:1 A` (the entry, the immediate's pop and the load: the fetch aborted), the
   fetch at +101 against silicon's +97. `t_start` is now the loader's E pop (`o_epop`); the
   fetch goes at +98 and the run's second fetch is +1 (item 2's offset), not +4. The function
   bench reads the routine's entry (`dut.start`), no longer `t_start`.
2. **The instruction after the shift is +1** (open). F9-push-nop1-pE-w0: the model's MOV CL,imm
   starts (its opcode leaves) at -7 and SHL's at -3, the immediate's take at -4; the RTL pops
   MOV CL's opcode at -7 too, the immediate at -5 and SHL's opcode at -2, on the clock the fill's
   fetch 10050 is granted. `fetch_inflight` is low on the grant's clock and high through its
   last clock (-1, 0), as the model's busy(t); the DISP word waits -1, 0 and dispatches at +1,
   the entry at +2. So the stall is applied by the model's law; what puts it there is MOV
   r8,imm8 running five clocks opcode-to-opcode (the book's 5) where the model's events show
   four. Tried (not kept): MOV r8,imm8 as pop, tmpb, the write from tmpb on E (four clocks, no
   ALU pass): SHL's opcode then leaves at -3 with the model's take and pop exactly, but the DISP
   still waits -2 (the ModR/M form's back-to-back rule: the fill's fetch is committed back to
   back at -3), -1 and 0, and NOP's fetch stays at +73 against +72; the gate families did not
   move (F9 7 exact either way). SHL r,CL's OPEN words were sized in MX0e with this stall under
   them, so the two lengths and the stall are not separable on these chains: open.
3. **F3-push-nop-k1-pE's second fetch +4**: item 1's false triple clock (the MOV CL,imm8 of
   the k1 form, +98 `A`); +1 after it.
4. **OUT imm8's port byte by parity** (open; not the word register). F3-out-empty-pE/pO-w0:
   the port's take is the opcode's pop + 5 at both parities in the model (+72 / +77) and the RTL
   (+74 / +79), the word register's load on the take's clock at both parities in both. The
   parity is in the fetch: the model posts the I/O write on the take (`P:io_write` +77) and
   issues it at +86 (pop + 14) at both parities; at pE the fetch goes on the take's clock (+77),
   at pO the line rises on the take's clock and the fetch waits under the posted I/O request
   until +82 (the model's io_hold=posted / lead: a fetch requested when the I/O was posted runs
   on the lead's first clock), ending a clock before the write. The RTL posts on the E word
   (pop + 8), the write at pop + 9, and grants the fetch on the take at both parities (+2 at pE
   from the shift's late pop, -3 at pO). The write five clocks after the next opcode's pop and
   the pO fetch's hold are the model's I/O setup and lead counts; no act in the OUT routine
   reaches past its E word, so neither is built: open (the note's §3.2 alignment cost is not
   what moves this form).

Measured (refresh-off corpus, `+v35_chk` silent, the two spacings' tables identical): 19 of
30,536 runs exact (MX0e 16, A1 28,059), the gate families 9 of 1,796 (MX0e 6: F0 2, F9 7);
the first divergence (i) 24,907, (ii) 0, (iii) 5,610 (MX0e 24,337 / 0 / 6,183). The restart's
first event dt, mean at 0 / 1 / 2 waits (flat in every family): F0 -0.17, F1 +0.17, F2 +0.82,
F3 -0.25, F9 +0.84, F11 +0.70, F12 -0.12, F20 -0.13; F0w -0.50 (MX0e F0 +0.50, F2 +0.62,
F9 +0.61, F11 +0.50, the rest unchanged). The write data 64,664 / 106,824 (the gate families 0
differing), the register vectors 0 bad (12,338 pass), the function vectors 0 bad, lint clean in
five configurations and at `V35_MX0C_DISPATCH` 0 / 1 / 3 and `V35_MX0F_QSTART` 0, 35 tests.

### Measured (`replay --core v35 --score`, refresh-off corpus, both spacings)

The function gates pass: the write data agree on every gate family (F0 F0w F1 F2 F3 F9 F11 F12:
0 runs differing; the corpus 64,682 / 106,824, the rest the memory forms' traps), the register
vectors 0 bad (`--regfile`, the gate families), the function vectors 0 bad (`--fn`), lint clean
in five configurations, `+v35_chk` silent at both spacings, the two spacings' tables identical.
The timing gate does not: 358 of 30,536 runs exact (A1: 28,059), the gate families 128 of 1,796
(A1 1,691), 1 run gained, 27,702 lost. The first divergence is in nearly every run the restart
fetch after the fence (event 1) or the first marker's cycle: at 0 waits the next instruction's
bytes leave the queue 1-3 clocks before silicon's takes; at 1 and 2 waits the gap widens to
5-12 (the starved queue's refill law; the routines run ahead of the fetch stream); a PUSH
marker's write is preceded on silicon by no fetch (the reservation on the E clock does not hold
the restart fetch). The per-run classification is the hand-back's (scratchpad `mx0/`).

### Build, replay, trace (MX0)

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains uasm --book   # assemble, the book table
    fpga/v35s/build_sim.sh direct v35
    V35_PLUSARGS="+v35_chk" PYTHONPATH=host/src:. python3 -m validation.v35s.chains replay \
        --core v35 --family F0 F0w F1 F2 F3 F9 F11 F12 --jobs 8
    # the trace: X S T L P W and M (the microaddress); W the stall (q f slot hold halt)
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains evtrace --id F2-push-nop-pE-w0 \
        --rtl F2.trace --run --keys X

## MX1: the memory forms (the EA, loads, stores, read-modify-write, the group forms, LDEA)

Design: `docs/v35s-mechanisms.md` sections 3.3, 3.5, 3.6, 8 and "Corrections from MX0" (the
dispatch stall is law; the first draft's rule). The routines are `urom/ea.uasm` (the EA's
heads), `urom/mem.uasm` (every ModR/M memory form the gate families run) and `urom/stack.uasm`
(PUSH / POP sreg, PUSH R / POP R, TRANS, PREPARE level 0, DISPOSE); `bus.uasm`'s direct
MOV [d16],imm is gone into mem.uasm's general form. 121 routines, 1,005 words (MX0 411): the
ROM is 19 words under its 1,024 (UADDR_W 10); MX2 widens it or OPEN words leave.

### The EA

The ROM has no EA routine (mechanisms 3.5, the V20's loader): the EA is the displacement's pops
and one add. A memory routine's first word is the add, `ea=BI ra=BASE rb=INDEX` (the ModR/M
mode's base on RAM port A, its index on port B, the popped displacement sign-extended by the
mode, into the address register; SS the default for a BP mode); the pops are the EA heads,
entered from the dispatch. The word after E of a ModR/M memory cell (the decode's new `ea` bit)
is a call: its target is the head of the registered ModR/M byte's mode, the return register
loads the routine's entry (the loader's `dcall` / `dret`, the sequencer's `retr` at DISP). The
head pops and returns (`ret` on its last pop). This is the V20 loader's mode branch (S_MODRM,
S_D8, S_D16 before the routine's first row) written as ROM words: a subroutine shared by every
memory routine, because the pops are the same for all of them and the add is the routine's own
first act (it can carry the reservation). The mode is decoded in the dispatch's target (the
mode's bits and the cell's two decode bits only: `test_v35_struct.MX1`), so no word tests a
condition to skip a pop: the EA's clocks are the pops and the add and nothing else. Two head
sets, by the routine's header (the decode's `eab` bit):

| Head | mod 00 [reg] | mod 01 d8 | mod 10 d16 | direct [d16] |
| --- | --- | --- | --- | --- |
| `ea=book` (eab0 eab8 eab16 ead) | OPEN, add: 2 | pop, OPEN, add: 3 | pop, pop, OPEN, add: 4 | pop, pop, add: 3 |
| `ea=bare` (ea8 ead) | add: 1 | pop, add: 2 | pop, pop, add: 3 | pop, pop, add: 3 |
| the book's EA | 3 | 3 | 4 | 3 |

`ea=book`: each mode's pops and the add, and the book's EA clock they do not fill as an OPEN
word; at mod 00 one OPEN word, the second book clock a book error (docs/v35s-eu-timing.md M4:
[reg] and [base+index] +0, every d8 form +1, where the book charges EA 3 for both; the head's
`diff=m00:-1` carries it into every routine's mod 00 path). `ea=bare`: the pops alone, for the
routines whose own acts after the EA already exceed the book (the store's datum read a word
after the add, both RAM read ports being the add's; the read-modify-write's write post), so
that no path carries an OPEN word over the book (the amended test). The add is one tick-B path
(the RAM's read data -> the 3-input 16-bit sum -> the address register); the request reads the
address register a word later (the assembler rejects `ea=BI` on a posting word, and the request
address in v35_eu no longer reads the EA's sum: `addr_q`), so the sum never reaches the 20-bit
request address in the same tick.

### The routines (lengths per path against the book, EA = 3 / 3 / 4 / 3, W = 0)

| Routine (opcodes) | heads | m00 | d8 | d16 | dir | book | OPEN | shape |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ld (8A 8B) | book | 9 | 10 | 11 | 10 | EA+7 | 0 | add, post, F: tmpa, E: reg <- tmpa (V20 MOV_RM) |
| ld_alu (02 03 0A 0B ... 32 33) | book | 9 | 10 | 11 | 10 | EA+7 | 0 | add, post, F with the ALU (V20 ALU_RM 0000), E: the write |
| cmp_rm (3A 3B), cmp_mr (38 39) | book | 9 | 10 | 11 | 10 | EA+7 | 0 | as ld_alu, the write suppressed |
| rmw (00 01 08 09 ... 30 31) | bare | 12 | 13 | 14 | 14 | EA+10 | 0 | add, read, F with the ALU, write post, E held (5 clocks read to write) |
| test_m8 (84) / test_m16 (85) | book | 14 / 12 | 15 / 13 | 16 / 14 | 15 / 13 | EA+12 / EA+11 | 5 / 3 | add, OPEN, read, F with AND, E |
| xch_m (86 87) | book | 14 | 15 | 16 | 15 | EA+12 | 1 | add, read, F (both registers), OPEN, write post, E held |
| st (88 89) | bare | 7 | 8 | 9 | 9 | EA+5 | 0 | add, the register's read with the post, E held |
| st_imm8 (C6 /0) / st_imm16 (C7 /0) | bare | 8 / 9 | 9 / 10 | 10 / 11 | 10 / 11 | EA+6 | 0 | add, the immediate's pops, the datum with the post, E held |
| st_sr (8C) / ld_sr (8E) | book | 8 / 10 | 9 / 11 | 10 / 12 | 9 / 11 | EA+6 / EA+9 | 0 / 2 | the segment's read with the post / F: the segment |
| les (C4) / lds (C5) | book | 19 | 20 | 21 | 20 | EA+17 | 6 | add, OPEN, read, INC2, F: reg, read, F: DS1 / DS0 (V20 LES / LDS) |
| ldea (8D) | book | 4 | 5 | 6 | 5 | EA+2 | 0 | add, E: reg <- the address register (V20 LEA) |
| grp1_mb (80 82 /0-6) / grp1_mw8 (83) / grp1_mw (81) | bare | 13 / 13 / 14 | 14 / 14 / 15 | 15 / 15 / 16 | 15 / 15 / 16 | EA+11 / EA+9 / EA+12 | 0 | add, the immediate's pops, read, F with the group's op, write post, E held (V20 GRP1) |
| grp1_mcb / mcw8 / mcw (80 82 / 83 / 81 /7) | book | 10 / 11 / 11 | 11 / 12 / 12 | 12 / 13 / 13 | 11 / 12 / 12 | EA+8 / EA+9 / EA+9 | 0 / 1 / 0 | add, pops, read, F with CMP, E |
| inc_m dec_m not_m neg_m (FE FF /0 /1, F6 F7 /2 /3) | book | 15 | 16 | 17 | 16 | EA+13 | 2 | add, read, F with the op, OPEN, write post, E held |
| test_mib / test_miw (F6 / F7 /0 /1) | book | - | - | - | - | none | 0 | add, pops, read, F with AND, E |
| mulu_m16 / mulu_m8 (F7 / F6 /4) | book | 35 / 29 | 36 / 30 | 37 / 31 | 36 / 30 | EA+33 / EA+27 | 8 / 11 | add, read, AW, F with the multiplier's load, OPEN, loop.uasm's loop by a jump |
| mul_m16 / mul_m8 (/5), div_m16 / div_m8 (/7) | book | - | - | - | - | a range | 0 | the natural shape into loop.uasm's loops |
| divu_m16 / divu_m8 (F7 / F6 /6) | book | 45 / 36 | 46 / 37 | 47 / 38 | 46 / 37 | EA+43 / EA+34 | 16 / 16 | add, read, (DW), F with DIVI, the trap test, OPEN, the loop |
| shm_1 (D0 D1) | book | 18 | 19 | 20 | 19 | EA+16 | 4 | add, read, F: the shifter's load, OPEN, one step, write post with the flags, E held |
| shm_cl (D2 D3), n = 4 | book | 29 | 30 | 31 | 30 | EA+19+2n | 7 | add, read, CL, F, OPEN, the zero test, the two-word iteration, write (count 0: the datum back) |
| shm_imm (C0 C1), n = 4 | book | 25 | 26 | 27 | 26 | EA+15+2n (its note) | 3 | add, read, the count's pop and load, F, OPEN, the loop, write |
| push_m (FF /6) | book | 18 | 19 | 20 | 19 | EA+16 | 5 | add, read, SP - 2 and the address, F: the datum, OPEN, write at SS:SP, E held |
| pop_m (8F /0) | book | 16 | 17 | 18 | 17 | EA+14 | 3 | add, the EA kept in tmpc with the stack read, SP + 2, F, the EA back, OPEN, write, E held (V20 POP_RM) |
| push_sr (06 0E 16 1E) / pop_sr (07 17 1F) | - | 9 / 11 | | | | 10 / 12 | 1 / 5 | PUSH / POP r16's acts on the segment (book error -1 each: a6 less the stall) |
| push_all (60) / pop_all (61) | - | 74 / 74 | | | | 74 | 60 / 63 | one word a register (the read with the post, or F with the next read: V20 PUSHA / POPA), eight OPEN between |
| trans (D7) | - | 11 | | | | 11 | 3 | AL, BW + AL, OPEN, the byte read (DS0 or the prefix: `seg=DSP`), F: AL |
| dispose (C9) / prepare (C8, level 0) | - | 11 / 26 | | | | 11 / 26 | 5 / 16 | V20 LEAVE; the frame's three pops, BP's push, BP, SP (the level's loop: MX4) |

The declared differences (`test_uasm`, every one per path): the mod 00 path -1 from the book
head (M4) on every `ea=book` routine; the routines' own: rmw / st / grp1_mb / grp1_mw / st_imm8
m00 -1 (a6 or F5 / F19 / F38 less the dispatch's stall) and dir +1 (the two pops the book's EA 3
does not resolve); st_imm16 d8 +1, d16 +1, dir +2 and grp1_mw8 +1 / +2 / +2 / +3 (the pops;
the 83 form's read after its immediate's pop, F19); test_m16 and ld_sr -1 on every path (a6);
push_sr, pop_sr -1 (a6). A positive difference is on a path with no OPEN word (the bare heads
and bodies without OPEN words); the test rejects one that carries an OPEN word.

OPEN words: 383 in 50 routines (MX0 122): the new ones are the memory forms' book clocks no act
names, chiefly PUSH R 60 and POP R 63 (silicon's 9.25 a word against the routine's four), PREPARE
16, DIVU mem 16 + 16, MULU mem 8 + 11, LES / LDS 6 + 6, SHL mem 4 / 7 / 3, TEST mem 5 / 3, the
three EA heads' 3.

Shared tails: MULU / MUL / DIVU / DIV mem jump into loop.uasm's loops (mu16_l, mu8_l, mi16_l,
mi8_l, dv16_l, dv8_l, di16_l, di8_l) and the divide error words (dv16_t, dv8_t, di16_t, di8_t):
the acts after the operand's load are the register form's. The register forms' routines are not
rewritten. PUSH r16 (bus.uasm) reads its register on the posting word (after SP's write): PUSH SP
pushes SP - 2 (F36's stack series; the length is unchanged).

### The datapath and the sequencer

- The dispatch's call (v35_loader: `dcall`, `dret`, `dmem`; v35_useq: `dc_b`, `dr_b`, the return
  register loaded at DISP). One level: the heads return before a routine could call.
- The request slot frees on the cycle's end (`rq_busy = rq_v || (rq_out && !req_done)`): a post
  on the end's clock stands from the next (the book check's machine: a post waits for the last
  request's end, not one more clock); a read's datum is latched at its end also when the clock
  posts the next request (POP R's F word with the next read; XCH's, the RMWs' write after F).
- `AL_ADD` (x + y, no flags: TRANS's table address, PREPARE's frame); `SG_DSP` (the prefix's
  segment, else DS0: an address formed without an EA mode, TRANS).
- The request's address `addr_q`: the address register as the posting word leaves it by a move,
  or the direct displacement (`ea=DISP`), never the EA's sum.
- No port of v35_bus.sv or v35_queue.sv changed; neither file is edited.

### Depth (by construction; the levelizer and the routed timing are the overseer's)

- The EA add (tick B): the RAM's read data -> the base + index + displacement (two 16-bit carry
  chains; the displacement's sign extension from registered dl / dh) -> the step mux -> the
  address register: about 10 levels. It no longer feeds the request address (above).
- The read datum's lanes into the ALU (tick B, the deepest new path): the bus unit's registered
  datum -> the byte lane / pair select (`dnow`, 2 levels) -> the latched-or-live mux (1) -> the
  source mux (SR_OPR, about 3) -> the ALU (12-14 with the carry) -> SIGMA: an F word that runs
  its ALU op on the datum arriving that clock (ld_alu, rmw, the group forms). The split, if the
  routed timing needs one: the F word takes the latched datum only (`opr`, the clock after the
  end) or moves it into tmpb and the ALU runs a word later (one clock, the V20's M -> tmpb).
- The dispatch's head choice (tick A, into the ce_b register `d1_b`): the decode table's lookup
  (MX0's 6-8 levels) and a 6-way mux on three registered mode bits and the cell's two bits (2
  levels). No new condition reaches the next-address mux; the return register's load is one
  more source on `retr`.
- The slot's stall term gains `req_done` (a registered bus output): one level.

### Measured (`replay --core v35 --score`, both spacings, `+v35_chk` silent, tables identical)

The gate families F4 F5 F6 F7 F10 F14 F15 F16 F19 F21 F22 F25 F26 F36 F38: 10 of 14,388 exact
(A1 13,332; MX0 10, all F16): 0 lost, 0 gained; the first divergence (i) 12,378, (ii) 0, (iii)
2,000. The MX0 gate families F0 F0w F1 F2 F3 F9 F11 F12 F20: 9 exact (F0 2, F9 7), unchanged.
The whole refresh-off corpus: 19 of 30,536 (MX0 19, A1 28,059); (i) 26,946, (ii) 0, (iii)
3,571. The restart fetch's mean dt is flat across 0 / 1 / 2 waits in every gate family
(F4 +0.13 / +0.13 / +0.13, F21 +0.16 / +0.14 / +0.13) but F15 (-0.45 / -0.54 / -0.62) and F25
(-0.70 / -0.79 / -0.87), whose drift is the stack forms' PUSH frames.

The first divergence is the memory form's own cycle in few runs: by event index (the gate families), 1 (the restart
fetch) in 52 %, 2-3 (the M0 marker's cycle and the fetches round it) in 40 %, the X form's first
cycle in the rest. The markers' residuals are MX0's (MX0f items 2 and 4: the instruction after
the shift +1, OUT imm8's write; PUSH r16's write a clock late after a PUSH: F4-push-empty-pE-w0
event 3, the closing PUSH's write +1). The routines' own lengths, free of the markers (the
clocks from X1's first cycle to X2's in the `X ; X` runs at 0 waits, `k2.py`): loads, load-ALU,
CMP, stores, TEST, XCH, INC / NOT, PUSH / POP mem, POP r16 within one clock of silicon on average
over the two parities (pE +1, pO -1: the parity's fetch); SHL mem,1 -2 to -3 and MULU mem -3 to
-4 (the book is short of silicon there: 19 against 22, 36 against 40); CMP [BW],imm16 -2; the
immediate store k2 +2 to +5 (the second instance's bytes behind the first's write: a queue
interaction, open).

The memory form's first divergence, traced (`+v35_trace`, F4-push-ld_bw-k1-pE-w0, clocks from
t_fill): PUSH AW's write 78-80 holds its E (W:hold), the E pops X's opcode and ModR/M at 81 with
the fetch 10052 issued, a back-to-back fetch 10054 at 84; the dispatch waits 82-87 (W:fetch,
the dispatch law), the head's OPEN word 88, the add 89, the post 90, the read 91. Silicon's read
is at 87, the clock the second fetch ends: silicon's EA and its read's post ran under the
fetches the dispatch waited for. The same in F6, F7, F14 (`add_bw_aw` +3: the bare head), F16
(+2), F21 (+4), F25 (LDEA: M1's write +2). With the dispatch stall lifted for a memory cell
(`V35_MX1_EAFREE` 1: measured, not kept; the law stays) the PUSH frame's X first-cycle dt moves
from a mode of +2 to 0 (gate families, 0 waits), the exact count does not move (the markers
come first). F19 / F22 (the immediate forms): the first divergence is the fetch after X's
pops (+1 to +3): the dispatch's wait puts the immediate's pops after silicon's takes.

Write data: 93,540 / 106,824 (MX0 64,664): every gate family agrees (0 runs differing); the
rest are the later packages' forms: the strings (F24 F30 F31, MX4), the bit and field forms
and the 0F page (F32 F34 F39 F40, MX3), MUL imm (F33, MX3), the transfers (F23 F35 F37, MX2).

Function: `rtl_vectors --regfile` on the 36 families 78,965 vectors, 0 bad (pass 70,124,
trap_nop 7,968 (7,668 and 300 of the old V35_EE_FUNC encodings), trap 316, the divergences 34: 33 MOV PS,r/m and one random vector whose operand
read covers the prefix byte the bench inserts, which the reference holds as state, not as a
byte: counted apart, `rtl_vectors.PFX_OVERLAP`); `--fn` 19,752, 0 bad; SingleStepTests through
the whole-core bench (test_rtl_vectors): 01 2B 81.3 C1.2 D3.7 F6.5 F7.6 F7.7 8F 61 at the
1,900-pass bar, pass alone (9,992 / 9,998 / 9,994 / 4,997 / 4,999 / 9,999 / 4,936 / 2,263 /
9,990 / 9,997); the files whose forms are MX2's and MX3's (C3 7C, the 0F page, 27 3F D4 D5 6B)
listed apart, all trap_nop, none failing.

### Build, replay, trace (MX1)

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.uasm --book   # every path's row
    fpga/v35s/build_sim.sh direct v35
    V35_PLUSARGS="+v35_chk" PYTHONPATH=host/src:. python3 -m validation.v35s.chains replay \
        --core v35 --family F4 F5 F6 F7 F10 F14 F15 F16 F19 F21 F22 F25 F26 F36 F38 --jobs 8
    V35_SIM_DEFINES="-DV35_MX1_EAFREE=1" fpga/v35s/build_sim.sh direct v35   # the alternative

### Open (MX1)

1. The EA under the dispatch stall: silicon's operand read leaves on the clock the fetch run
   ends, before the routine could have dispatched, added and posted under the law (above). Is
   the V35's EA and operand read ahead of the dispatch (the V20's loader EA and pre-read), with
   the stall on the routine's first word after them?
2. [reg+d16] and the direct address: silicon +1 over [reg] (M4), the routine's two pops +2.
3. The immediate memory forms' write at s + 7 whatever the mode (F19: C7 07, 47, 87 alike): the
   displacement's pops do not delay it on silicon.
4. CMP mem pays most of the RAMEN write penalty with no write (eu-timing): CMP mem,reg 12 and
   CMP mem,imm 15 against the book's 10 / 12; the routines keep the book.
5. The ROM is 1,005 of 1,024 words; 383 OPEN words, 123 of them PUSH R / POP R's.

## MX1b: the dispatch law on the E word, the routines on the frozen model's positions

The coordinator's trace (main, the frozen model exact on every run it read): the model's start S
of an instruction is the clock its opcode (and its ModR/M byte) leaves the queue, the RTL's E
word; the fetch that pop's room triggers is issued on that clock and never blocks it. MX0's
dispatch stall sat on the word after E, one clock late, where the fetch the E's own pops
triggered is in flight: every instruction that made room paid it.

### 1. The law moves to the E word (`V35_MX0C_DISPATCH` 4, the default)

The E word (the opcode's pop with its ModR/M) does not execute while a fetch granted on an
earlier clock is in flight (through its last clock), and a ModR/M form's E not on a
back-to-back fetch's issue clock; a fetch granted on the E clock never blocks it; the dispatch
and the routine's words never stall on a fetch (operand pops are free). The gate is 3's (MX0d
measured that placement with the book's routines); 4 names it with the routines below. The
machine explanation on record stays the confirmed one: the opcode's read from the queue and a
fetch in flight exclude each other through one shared resource. It is the pop, not the
dispatch, that the law gates. `V35_MX1_EAFREE` (MX1's experiment) is moot and removed.
Measured alone (the MX0 routines, F0 F0w F1 F2 F3 F9 F11 F12, both spacings): 0 exact (the
routines were sized for the stall a clock later), the restart dt -2.2 to -1.2 at 0 waits.
Also measured and not kept: the stall ending a clock before the fetch's last (`5`, worse:
-3 / -6 / -10 at 0 / 1 / 2 waits) and the staging slot freed at the E pop (the loader's `stg`:
0 exact). The trace gained an `E` item (the E word's pop) for the side-by-side view.

### 2. The register forms on the model's starts and takes

Each routine's E-to-E (the routine's length: E at S, the dispatch S+1, the entry S+2) and its
pop clocks set to the model's S-to-S and take clocks on an exact k1 / k4 run (cited in each
`why=`), named acts first, OPEN words for book clocks no act names, book errors declared where
silicon is shorter; where silicon is longer than the book a named act is declared (`beyond
the book: a named act`):

| Routine | S-to-S (book) | pops | evidence |
| --- | --- | --- | --- |
| ADD / CMP / MOV reg,reg | 3 (2): the registers' RAM read a word of its own, the ALU on E, the write after | ModR/M at S | F3-push-add_aw_dw-k4, mov_aw_dw-k4 |
| NOP / XCH AW,r | 4 (4): one OPEN word | - | F3-push-nop-k4, xch_aw_dw-k4 |
| MOV r8,imm8, ALU acc,imm8, 80/82/83 reg,imm8, TEST | 4 (5) | S+3 | F3-push-mov_cl_imm-k4 |
| MOV r16,imm16, ALU acc,imm16, 81 reg,imm16 | 5 (6) | S+3 S+4 | F3-push-mov_aw_imm-k4, add_aw_imm-k4, add_dw_imm-k4 |
| PUSH r16 | 9 (13): the post at S+5, the write at S+6, E at its end | - | F3-push-nop-k4 |
| MOV [d16],acc | 9 (8): the post a word after the address register's load (named) | S+2 S+3 | F1-store-m2 |
| SHL r,CL | 12+2n (11+2n): the shifter's load a word of its own (named) | ModR/M at S | F3-push-shl_cl4-k4, shl_cl0-k4 |
| SHL r,imm8 | 11+2n (9+2n): the same; silicon 12+2n, one clock open | S+3 | F3-push-shl_imm4-k4 |
| SHL r,1 | 9 (8): the iteration's second word (named); silicon 10, one clock open | - | F3-push-shl1-k4 |
| OUT imm8 | 10 (11): the post at S+9, the write at S+10 = the next S | S+3 | F3-out-nop-k2 |
| OUT DW | 7 (8): the post on E at S+7, the write at S+8 | - | F0-ls |
| POP r16 | 11 (11): the post at S+5 | - | F5-push-pop_aw-k2 |
| IN acc,DW / IN acc,imm8 | 12 (14) / 16 (15) | - / S+3 | F5-push-in_al_dw-k2, in_al_imm-k2 |

The three clocks before an immediate's first pop (S, S+1, and one OPEN word at the entry) are
the same in every immediate form (MOV r,imm, ALU imm, 80-83, TEST reg,imm, OUT / IN imm8,
PUSH imm, the shifts by imm8; the displacement of a d8 memory form is taken at S+3 too): one
open mechanism they suggest, an operand-byte path latency the opcode / ModR/M path (popped by
E itself) does not have. The OPEN word sits before the pop until the act is found.

MULU r16 34 (book 32) and the shifts' remaining clocks stay short of silicon: a clock beyond
the book is added only as a named act, and none is known.

### 3. The memory forms on the model's k2 runs

The second instance of each `X ; X` run (the bus free): [BW] posts its read at S+4 so that it
issues at S+5 (the model's P:read, F4-push-ld_bw-k2: S 92, the read 97), a displacement form
at S+6 (the displacement taken at S+3: the book head's OPEN word now before the d8 pop; the
d16 head's OPEN word dropped, a book error of one at mod 10, `eab16 diff=d16:-1`), the write of
a read-modify-write two clocks after the datum, E held to its end; the loads' E at the model's
next S whether the datum lands at S+8 or S+9 (the OPEN words under the cycle, F on the clock
before E). Lengths at mod 00 (book): MOV / ADD / CMP reg,mem 11 (10), ADD mem,reg 13 (13),
TEST mem,reg 13 (15 / 14), XCH 16 (15), MOV mem,reg 8 (8), ADD mem,imm 14 / 14 / 15 (14 / 12 /
15: the immediate popped after the datum, the model's takes), CMP mem,imm 14 / 14 / 15 (11 /
12 / 12: the left-out write's four clocks), INC / DEC / NOT / NEG mem 13 (16: the write two
clocks after the datum), SHL mem,1 19 (19: the write eight after), PUSH mem 17 (19), MULU mem16
40 (36). Where silicon is longer than the book the reason says so and names the run (`silicon
longer than the book`, the frozen model exact on it): `test_uasm` accepts a positive difference
with OPEN words on its path only with that declaration or a named act (the MX1 rule, amended
for the coordinator's direction; the overseer's to confirm). The immediate store's datum stays
before its write (the model pops it after the write issues: a datum the bus takes later than
B2 is not built). The ROM is 1,042 words: `UADDR_W` 11.

### Measured (MX1b; `replay --core v35 --score`, both spacings, `+v35_chk` silent, tables identical)

| Step | MX0 gate families (1,796) | MX1 gate families (14,388) | corpus (30,536) |
| --- | --- | --- | --- |
| MX1 (the stall on the dispatch) | 9 | 10 | 19 |
| 1: the stall on the E word, MX0's routines | 0 | - | - |
| 2: the register forms re-derived | 118 | 231 | - |
| 3: the memory forms re-derived (MX1b) | 118 | 232 | 479 |

The corpus at MX1b: 479 exact (MX1 19, A1 28,059), 0 lost against MX1; the first divergence
(i) 14,153, (ii) 0, (iii) 15,904 (the classifier's (iii) is the wait-dependent fetch offset,
below). The PUSH frame's first events now agree in most gate-family runs (F4-push-ld_bw-k1-pE-
w0: the PUSH's write 78, the fetches 81 84, the load's read 87 exactly as silicon, M1's write
+1 at 99); the per-family table and the per-run tables are the hand-back's (mx1b-table.md,
mx1b-runs-t1.txt).

Open (MX1b):
1. The restart fetch's offset grows by one clock a wait (every family: about -2 at 0 waits,
   -3 at 1, -4 at 2). Traced (F3-push-nop-k4-pE-w1, the frozen model exact): in the prelude's
   MOV r16,imm16 stream the model issues its fetch on the instruction's start S (10044 at -36),
   the RTL three clocks later on the immediate's pop (-33): its room counts the staging slot
   while the instruction still owes bytes (`stg`) and the word register's bytes; the fetch
   stream lags by a word from there, and at the LS's MOV CL / SHL the E then waits on that
   later fetch (W:fetch) while the model's start does not. Freeing the staging slot at the E
   pop was measured (0 exact): the queue's count of the word register against the model's
   six bytes is the question (a bus-unit / queue law, (ii) when measured; not edited).
2. The OUT marker after the LS's shift: the model takes OUT's port byte at S+5 there and at S+3
   after every other form (F3-out-nop-k2-pE-w0: OUT S 72, T 77, the restart fetch 77; RTL 75):
   the shift's tail (MX0f item 2) on the following routine's operand byte, no act known.
3. The immediate memory store pops its immediate after its write issues in the model (F5-push-
   st_imm_bw-k2: P:write S+5, the takes S+8 S+9): a datum taken by the bus after B2 is not
   built, so the RTL pops it first.
4. Silicon longer than the book where no act is named: MULU r16 34 (32), SHL r,imm8 12+2n
   (11+2n built), SHL r,1 10 (9 built); the memory forms' extra clocks are declared `silicon
   longer than the book` with their run (the amended test; the overseer's to confirm).
5. OPEN words 439 in 67 routines; the ROM 1,042 words (UADDR_W 11).

## MX1c: the shift's head under the fill fetch (the take sync) and the staging slot's room

### What the model does on the runs the overseer named (the frozen model exact on each)

The LS's SHL AW,CL (n = 31) runs 75 / 76 / 77 clocks at 0 / 1 / 2 waits from the model's S
(F3-push-nop-k4-pE-w0 / w1 / w2), the RTL's 74 at every wait. Read in the model
(`an/probe2.py`: its `_unit_hold` and `_start` wrapped): `unit_hold` never holds on these runs
(no fetch past its second clock during the shift's exec; it holds once on MULU's runs, F16-l-
push-mulu_dw-pE-w1, F3-push-mulu_dw-k4-pE-w2). What moves the shift is the take sync
(`take_sync=pending`, eu.py 1164-1219): the shift's exec starts at S + 4 / 5 / 6 (`exec_t`),
after the ModR/M take at S, once the fetch in flight or requested on the take's clock has
delivered its word. So the unit hold is not built (it is rare on the corpus; its law is in the
note's corrections below); the take sync is.

### The take sync (`V35_MX1C_TSYNC`; built, measured, default 0)

After an operand byte's pop (a register form's ModR/M on its E word, an immediate byte of a
register form; not a displacement, not a port number (the new pop target `port`: the model's
port_sync=none), not a memory form's byte), the routine's next words that pop nothing (not E,
not the dispatch) wait until the fetched words in flight or requested on the pop's clock have
been delivered; the delivery's own clock frees them; a request the EU's own reservation holds
back is not counted (the model's take sync counts no request a posted request holds), and a
request that lapses ends the wait. In the sequencer: `tw`, the deliveries owed (two at most:
the fetch on the bus and the one the request line asks for), stall `sync` (trace `W:sync`). The
machine explanation (the overseer's hypothesis): the operand byte's path from the queue and
the fetched word's write into it share the queue's port. Measured:
- the LS's shift 75 / 76 / 77 at 0 / 1 / 2 waits (F3-push-nop-k4-pE-w0..w2), the model's;
- the restart fetch's dt flat across the waits in every family (F0 F1 F2 F3 F9 F12: +0.83,
  -0.50, +0.97, -1.21, +1.25, -1.03 at 0, 1 and 2 waits alike; MX1b's grew by one a wait) and
  the unexplained bucket from 783 to 124 (the six families);
- but a uniform clock off in every frame (the PUSH frame +1, the OUT frame -1): the exact count
  0 (corpus 0 of 30,536; MX1b 479). The +1, traced (F3-push-nop-k4-pE-w0 -4 .. -2): MOV CL,imm8's
  pop and the word register's load of D3 E0 at -4, the staging load at -3, SHL's E at -2; the
  model takes the immediate and loads its IR from the queue on one clock (-4) and starts SHL at
  -3. The staging load waits a clock behind the word register (MX0b's law); `V35_MX0B_WR` 0
  (the stored bytes direct) measured the same. Until that clock is found the take sync stays
  behind its macro, off.

### The staging slot's room (`V35_MX1C_ROOM` 1, the default)

The loader's `stg` (the staging slot counted occupied by the queue's request rule): MX0
counted it while the running instruction owed bytes. The model (queue.py `room`,
room_ir=arrival_idle): the IR is a seventh slot, counted only by what it holds, on a word's
arrival clock or with the decoder idle. Built: the slot is free on a word's arrival clock when
it is empty (`q_arrive`, the bus unit's delivery into the loader; no queue or bus port changed).
Measured: the prelude's MOV r16,imm16 stream at 1 wait now matches the model's starts and takes
clock for clock (F3-push-nop-k4-pE-w1 -36 .. -12: S -36 -28 -20, takes +3 +4); the corpus 485
(MX1b 479); variant 2 (free whenever empty) 0 exact on the MX0 gate families; variant 0 is
MX1b.

### Measured (MX1c; both spacings, `+v35_chk` silent, tables identical, the defaults TSYNC 0, ROOM 1)

| | MX0 gate families (1,796) | MX1 gate families (14,388) | corpus (30,536) |
| --- | --- | --- | --- |
| MX1b | 118 | 232 | 479 |
| the room law (MX1c, default) | 120 | 232 | 485 |
| and the take sync (`V35_MX1C_TSYNC` 1) | 0 (restart dt flat) | - | 0 |

The corpus: 485 exact, 0 lost against MX1b (F3 +2, F40 +4); the first divergence (i) 14,224,
(ii) 0, (iii) 15,827. Write data 93,540 / 106,824 (every gate family agreeing). OPEN words: 421
book clocks no act names, 18 beyond the book (silicon longer than the book, measured: ld,
ld_alu, cmp_rm, cmp_mr, xch_m, the group-1 CMP mem,imm forms, MULU mem16, IN imm8), and 9
named acts beyond the book (the reg,reg forms' RAM read, MOV [d16],acc's post, the shifts'
loads and iteration word, 83 mem's read after its pop).

Open (MX1c):
1. The staging load's clock (the take sync's uniform offset): the model loads its IR from the
   queue on the clock it takes the operand before it (F3-push-nop-k4-pE-w0 -4); the RTL loads
   the word register then the staging register a clock later. Found, the take sync goes on.
2. The unit hold (`_unit_hold`): rare on the corpus (no hold on the LS's shift at any wait; one
   on MULU's runs), not built; its law is the note's proposal below.
3. MX1b's items 2-4 stand.

## Generated data

Ten files here are generated by `validation/v35s/chains/ucgen.py` from the tracked fit
(`validation/v35s/chains/fit.json`, `Config.fitted()`) and the live model
(`validation/v35s/chains/sim/templates.py`: `decode`, `steps`). Do not edit them; every header
names the fit's md5 and the invocation.

| File | Contents |
| --- | --- |
| `v35_ucode.hex` | the microcode ROM: 1,140 rows x 64 bits (72,960 bits), one row per line, `$readmemh` format with `//` comments naming each template and decoding each row |
| `v35_ucode_b0.hex` .. `_b3.hex` | (S3) the same ROM as four banks by row address mod 4 (285 rows each): the banks `v35_ucode.sv` loads, one block RAM each |
| `v35_ucode_tbl.svh` | `v35_tmpl_base(id)` (231 templates) and `v35_tmpl_sel(fmt, run)`: class x format bits x start-time bits -> template |
| `v35_decode_tbl.svh` | `v35_dec_native(op)`, `v35_dec_ext(op)` (the 0F page's second byte), 256 entries each ((S5a) 203 bits, (S5b) 211), and `v35_dec_grp(gidx, reg)` (17 group opcodes x 8 reg fields) |
| `v35_class_tbl.svh` | `v35_cls_const(cls)`: 84 classes x 124 bits (50 columns; (S4) `dclk`, rmw_alu=through's routing clocks) |
| `v35_consts.svh` | the EA table, hold_q, io_b2b_q, wlatch, io_recover, per_shift_count, the cross-class integers, the generated widths; `v35_ea_mode(mod, rm)`, `v35_ea_clocks(mode)` |
| `v35_pkg.sv` | package `v35_pkg`: the row enums, `uc_row_t`, `v35_half_t` / `v35_dec_t` / `v35_grp_t`, `v35_fmt_t` ((S5a) 121 bits, (S5b) 125), `v35_run_t`, `v35_cls_t`, the class ids, (S3) the datapath's operations `V35_XOP_*` and operand roles `V35_ROLE_*`, (S5a) the sub-operations `V35_XK_*` (a transfer's target), `V35_RETK_*` (the returns), `V35_STR_*` (a string element's operation); includes the four .svh; `v35_fmt_of(opcode, page, modrm)`, `v35_tmpl_of(fmt, run)` |

Regenerate: `PYTHONPATH=host/src:. python3 -m validation.v35s.chains ucgen`; check without
writing: `... ucgen --check` (regenerates to a temporary directory and diffs, exit 1 on a
difference). `test_ucgen` runs the check, the inverse check, the decode check, the S5 budget,
the size bounds and the hex/struct round trip (about 30 s); `test_v35_struct` lints every
`*.sv` / `*.svh` here.

### Row format (`uc_row_t`, LSB first)

| Field | Bits | Meaning |
| --- | --- | --- |
| `op` | 5 | NOP, CLOCKS, NOWAIT, TAKE, DATA, POST, POST_IO, FLUSH, FLUSH_C (cfgap), DECIDE, HALT, FROM_START, SPLIT_FLOOR |
| `tdelay` | 1 | 1: the model returns after the action (the next row on a later clock); 0: it goes on on the clock the row completes (a post, a lead take, the last NOWAIT clock, a data step's done clock, a satisfied wait). A function of (op, tag), kept in the row |
| `last` | 1 | the template ends after this row (both rows of a final skip pair) |
| `skip` | 3 | NONE, COND / NCOND (a REP compare ended / did not end on its condition), NOHELD (no detached I/O held at the port take: the relatch row), CROSS / NCROSS (the bit field crosses / does not cross into the next word) |
| `wcond` | 3 | the wait folded in front of the action: NONE, OWN_DONE (`wait`), OWN_ISSUED (`issued`), SLOT (`slot`), WB (`wbsync`), QUIET (`quiet`) |
| `nsrc` | 3 | LIT (imm), EA (imm + EA table of the form's mode), CNT (imm + per_shift_count x count), UNIT (imm + MUL's sign clocks), BF (max(0, cost - imm)), STR (imm + first / loop1 / loop by element index) |
| `imm` | 9 | the count, setup, or SPLIT_FLOOR / FROM_START clocks |
| `tag` | 3 | NONE, EA, MEXEC (clocks); LEAD, CHAIN, WORD, CHAIN_WORD, PORT (take) |
| `ltop`, `loop` | 1+1 | the element loop's first and last body row (the body runs n times) |
| `lastadd` | 1 | + the class's `last` on the final element (not after a compare's condition exit) |
| `rkind` | 3 | NONE, READ, WRITE, IO_READ, IO_WRITE, NOWRITE |
| `asrc`, `aidx` | 4+3 | EA, SPW (SP-2-2i), SPR (SP+2i), BP, PORT_IMM, PORT_DW, IX, IY, VEC (+2i), STR_IX / STR_IY (+ element x width); `aidx` is a TAKE row's byte count |
| `wsel` | 2 | FMT (the form's width), BYTE, WORD |
| `i2m`, `x` | 2+7 | the request's fetch-free clocks: x, or setup - x; `x` is also FROM_START's second count and an arm's count |
| `grp`, `whole`, `restart`, `detached` | 4 | the request flags (`_post`'s grp / whole / restart; a detached I/O) |
| `arm`, `apos` | 4+2 | the folded side effect: HOLD, HOLD_ROOM, HOLD_TAKE, HOLD_TAKE_DLV, HOLD_LONG (element 0 only), REL, REL_FOREVER, REL_RAISE, FLUSH_FROM, HELD; applied on ENTRY (before the wait), PRE_OP (after it) or EXIT (as the row is left, every loop pass) |
| `wb` | 2 | on a last row: the write-back clocks owed to the successor (mwb / rwb / uwb / xwb / wb by the form, as `eu._start` picks them) |

Rows: 377 TAKE, 374 CLOCKS, 250 DATA, 63 POST, 31 FLUSH, 18 NOP, 14 NOWAIT, 5 SPLIT_FLOOR,
4 DECIDE, 2 POST_IO, 1 FLUSH_C, 1 HALT; the longest template is 11 rows.

### Counts

- 45,819 forms enumerated (opcode x second byte x 0F third byte through the live decoder
  `sim/templates.decode`, under the flag / CW states that give every transfer both outcomes); 45,531 with a template, 288 register forms the decoder accepts that no template
  runs (trap_nop halves, below).
- 1,140 rows, 231 templates (template 0 is trap_nop's: CLOCKS 2; the prefix class shares it),
  84 classes (class 0 trap_nop + the fit's 83).
- `v35_tmpl_sel`: 52 classes select by format / start-time bits (221 selections), 31 have
  one template, trap_nop none (the default, template 0). The start-time bits (`v35_run_t`): taken / zfail (the transfer's
  decision: flags, CW), cnt0 (shift_cl only: CL = 0), half (the last operand byte is the even
  half of its word: PC parity; bf_ext / bf_ins / mul_imm / convert / convert_d / ret_imm /
  ret_far_imm),
  n0 (a REP or BCD string with no element: CW / CL).
- Inverse check: 108,302 expansions (every form under its run variants) equal the model's
  step lists. S5 budget: 63 (class, template) starts of register-only interlocked forms, all
  within {one take of a byte or a lead take, one post, one clocks load}.
- Verified outside the tests with Verilator 5.032 (lint clean, and a bench comparing
  `v35_fmt_of` / `v35_tmpl_of` with the Python mirror on 304,200 vectors and the ROM read by
  `$readmemh`: no difference).

### trap_nop

Native opcodes with no form: 62 63 66 67 9B CE D6 D8-DF (FPO), F1. 0F page: everything but
10-1F, 20 22 26, 28 2A, 31 33 39 3B. Escapes report `esc` with class trap_nop: 0F (page 1) and
F2 F3 64 65 (page 2: the next byte is the string opcode; a REP prefix before a non-string byte
is trap_nop). Halves the decoder rejects or no template runs: 8D reg, 8F /0-7 reg, C4 / C5
reg, C6 / C7 /0-7 reg, F6 /0 (both), F6 /1-3 reg, F7 /1-3 reg, FE /2-7, FF /0 /1 /3 /5 /6 /7
reg, 0F 31 33 39 3B mem. A trap half keeps the decoder's length (the loader takes its bytes).

### Decode attributes emitted (per table half, copied into `v35_fmt_t`)

Template format bits: `sgn`, `grp`, `fixed_alu`, `shift`, `cl_shift`, `nowrite`, `swap`,
`dbit_v`/`dbit`, `cond`, `count_byte`, `cl_count`, `modrm_op`, `bus`, `port` (byte / DW),
`sreg`. Decode attributes (docs/v35s-core-v2.md, Rule disposition (d)): `interlock`,
`regonly` (register-only class), `port_io` (port-form IN/OUT), `one_reg` (one-byte register
form), `long1` (long one-byte form), `unit_reg` / `unit_mem` (shift / MUL / DIV unit),
`fixed_grp` (fixed-lookup group form), `imm16_reg` (two-byte-immediate register form),
`modrm_pre` (ModR/M latched at start: TEST r,r, INC/DEC r8), `far_xfer`, `xfer_mem`,
`imm1_mem`, `grp_rmw`, `page_reg` (0F register form / bit field), `page_mem`, `test1m`,
`mul_imm`, `lea`, `dbnz`, `dbnz_z`, `xfer` (transfer class), `dw_count`, `strop`, `bcd`, `bf`,
`ro`, `rmw`; (S3) `breg` (base class reg: io_take_nx), `idle1` (one_idle's one-byte forms); (S5a)
`tsel` (a transfer's start-time decision: 0 always, 1 the condition field, 2 DBNZ's CW - 1 != 0,
3 BCWZ's CW = 0), `zpol` (DBNZE's Z test), `xshort` (a short transfer: base class branch_short or
dbnz: xfer_odd, xfer_nt), `rot4r` (ROL4 / ROR4 on a register: rot4_exec); (S5b) `bit1r` (a
register bit op, class bit1: page_ir_room=end's full latch, page_imm_sync's even half), `pmt`
(page_mtake's forms: a register bit op or bit field, TEST1 [m] under page_mtest=wait), `pgb2b`
(page_b2b=reg's form: a 0F register form of base class reg), `pcl` (page_cl=thru's form: a 0F
memory form with its bit index in CL and the class's cl clocks); (S3)
the datapath's (ucgen XOP_ATTRS, from the encoding: the opcode and a group's reg field) `xop`
((S5a) 6 bits; the operation: ALU MOV XCH SHIFT MUL DIV MULI INC DEC NOT NEG LDEA SRLD SRST PUSH
POP PUSHF POPF PUSHR POPR CVTBW CVTWL FLAG ADJ CVTBD CVTDB LAHF SAHF IN OUT XLAT, (S5a) JMP CALL
LOOP RET BRK STR PREP DISP LPTR BCD, (S5b) BIT1 ROT4 BF), `aop` (its sub-operation: the ALU op, the shift, the flag
form, the adjust; (S5a) a transfer's target kind, a return's kind, BRK's fixed vector type (0: the
operand byte's), a string's element operation, LES / LDS's segment, a BCD string's operation),
`opa` / `opb` (the destination / source roles: RF
RM OPR ACC IMM ONE CL SRF SOP), `wd` (a word operation), `nwr` (flags only), `sx` (a sign-extended
immediate byte), `stk` (the stack forms); computed in `v35_fmt_of` from the ModR/M byte: `ea_mode`, `bix16`
(base+index+d16), `disp`, `len`, `ccode`. Left to the RTL (start-time conditions, not decode):
full-queue-plus-latch start, even-half operand byte (`v35_run_t.half` is its template side).
The data book cross-check (instructions.json) finds no trailing-byte disagreement; 66 cells
(opcode / reg / half) have no data-book record (undocumented aliases: 00-39 d=0 register forms, 88 / 89 register
forms, 82 / 83 /1 /4 /6, C0 / C1 / D0-D3 /6, 8F / C6 / C7 /1-7, F6 / F7 /1 mem, FF /7 mem).

### What the rows do not express (divergences and notes for S3-S5)

- **Canonical form.** `("take", 0)` and every `("clocks", 0[, tag])` produce no row (no-ops in
  `eu.tick`); a request step's trailing default arguments are dropped. A CNT / BF / UNIT row
  whose count evaluates to 0 (a shift by 0 of `shift_imm`, a bit field with cost <= span) is a
  0-clock row: the sequencer passes it as the model passes `("clocks", 0)`.
  (S4) One exception: a take that leaves the take sync pending (no chain / lead / port tag)
  followed in the model only by such no-op steps is followed by a NOP row (`last`): `eu.tick`
  checks the sync before every step, so the trailing no-op holds the form's end (and the next
  start) until the sync is met, where a take that is the template's last step ends the form at
  once (the register ALU forms with a ModR/M byte, imm, LDEA with a displacement: 7 rows; found
  on F19-d-push-adddwi_nop: ADD DW,imm16's deferred take sync).
- **Step indices.** Rules that read the model's step index (`eu.k == 1 and steps[0][0] ==
  "clocks"`: latch_start, one_idle, long_exec; `k == len(steps)`: abort_unit=loop, rot4_exec,
  count_latch; `steps[k-1] == "slot"`; `_mem_unit_hold`'s scan for data / wait steps;
  `ir_waits_latch`'s sum of the clocks steps left) become row predicates: row 0 is the first
  row of the template (wbsync is its `wcond`, not a row: "row 0 is CLOCKS with wcond NONE");
  the last CLOCKS row of the template; the relatch row; "a DATA row or OWN_DONE wait passed".
- **Skip runs.** A skipped row passes in no time. The bit fields' crossing alternatives skip
  up to 6 consecutive rows (bf_ins); a REP compare's exit 1. (S5a) The sequencer evaluates the
  row after a skipped one in its place (`sk`), so a skip costs no row of a pass (no jump field).
- **Not generated (out of scope of the first delivery):** `refresh_hold_steps` (refresh-on:
  no `boundary` bit, no exec / loop / tail / loop_odd / mexit tags), `burst_wait=issue`'s
  `sent` (unused under the fit). PREPARE with a level byte other than 0 runs the level-0
  template (the model does not decode it).
- **Fields adjusted from the plan's 48-bit row:** 64 bits; `sync` dropped (a TAKE with tag NONE
  or WORD sets the take sync); `wsrc` dropped (the templates carry no datum: S6's function
  path); `asrc` 4 bits + `aidx` 3; `skip` 3 with the conditions above; `wait` named `wcond`
  (`wait` is an SV keyword); the relatch insertion is one row (the slot wait folded) not two;
  `v35_fmt_of`'s `page` is 2 bits (2: a REP prefix's string form; the loader merges `repc` from
  the prefix's `v35_dec_native` entry).
- **Model k-dependent `wb` additions** (lea_wb=fetch's `fwb`, page_fl_end's `flwb`) stay
  run-time rules: class table columns.


The design record is `docs/v35s-core-v2.md` (the plan, Appendix A §1, Appendix B §1-3). This
directory holds stages S2, S3, S4 and S5a: the bus unit, the prefetch queue, the loader and the
slot module (S2), the execution unit (S3): the microcode sequencer `v35_ucode` running the
generated ROM, the datapath `v35_eu` on the register RAM `v35_regram`, the function package
`v35_fn_pkg`; (S4) the memory classes: the arbiter's full request path (the slot and two queued
positions, the request window, the nowrite slot, the odd-word pair), the EA unit `v35_ea`, the
memory forms' timers and strobes in the sequencer, the loader's `ir_hold` and `fresh`, the bus's
start flags; and (S5a) the transfers (the start-time run bits, the flush and decide rows, the
transfer holds, the targets and the PC / PS / PSW writes, CALL's and BRK's pushes), the strings
and the REP element loop (the REP prefix's decode, the string unit's IX / IY / CW, the compare
exits, the overrun, the fetch holds and releases, the split floor), LDEA's rules and the stack
frame (PUSH R / POP R, PREPARE / DISPOSE), LES / LDS, the register miscellany's rules (the take
hold of the conversions, mul_imm_count=sync, rot4_exec) and the BCD strings' datapath; and (S5b)
the 0F page: the escape's decode (the second opcode byte and the ModR/M byte behind it, the
decode a clock ahead over three bytes), the `page_*` rules as flags and timers (below), the bit
ops, the digit rotates, the bit fields and the BCD strings running; and (S6) the function path:
the whole-core function bench (`fpga/v35s/v35_core2_tb.*`), SingleStepTests and `--regfile`
through it, the write-data score on the corpus, and the datapath fixes they found (see
"Function (S6)").

Gates: S2 `replay --core v35 --score` on F0, F0w, F1, F2; S3 on F0, F0w, F1, F2, F3, F9, F11,
F12, F20; S4 on those and F4, F5, F6, F7, F10, F14, F15, F16, F19, F21, F22: RTL-exact ≥
model-exact. (S4: every one of the 16,670 runs RTL = model, so RTL-exact = model-exact in every
family, F22's six model misses shared.) S5a on those and F23, F24, F25, F26, F29, F30, F31,
F33, F35, F36, F37, F38 (32 families, the refresh-off corpus but the 0F page's F32, F34, F39,
F40): see "Gate (S5a)" below. S5b on the whole refresh-off corpus (36 families): see "Gate
(S5b)".

## Modules

| File | Module | Role |
| --- | --- | --- |
| `v35_front_pkg.sv` | package `v35_front_pkg` | cycle kinds/widths, the fit integers the front end reads, `req_t` (a posted request) |
| `v35_pkg.sv` + `.svh` (generated) | package `v35_pkg` | the row format, the format word, the decode / class / template tables (above) |
| `v35_fn_pkg.sv` | package `v35_fn_pkg` | the pure functions: ALU, S Z P, shifter, multiplier, the restoring divider's init / step / finish, conditions, adjusts, BCD byte, bit ops, digit rotate, the EA offset and its registers |
| `v35_bus.sv` | `v35_bus` | (A1) the grant (one fixed priority over the EU request port and the queue's line, "A1"); one cycle at a time, pin timing verbatim from `../v35_biu.sv`, the delivery registers, the I/O recovery window, the data latch (`wlatch`), the 3-clock aborted fetch cycle, the fetch-run flag; (Q1) the request line's sample at a fetch's last clock (`b2b_now`, held while a memory request waits in the slot) |
| `v35_queue.sv` | `v35_queue` | (Q1) the simple machine: six bytes, the stored and unreleased counts, the prefetch pointer, the request line (`fetch_req`, `q_low`), the IR staging byte counted as the seventh slot (variant B), the byte-wide write port and its one-byte latch (variant B, `V35_QUEUE_B`). See "Queue (Q1)" |
| `v35_loader.sv` | `v35_loader` | IR, the format lookup (`v35_fmt_of`, the ModR/M byte the next queue byte; re-decoded at the ModR/M take; (S5a) a REP prefix's form the string opcode behind it, page 2 with the prefix's repc), `need`, the ready countdown (`ready_at`, with one_idle's and long_exec's moves), the IR load in L and P, the decode a clock ahead; (S5a) a flush empties the IR; (Q1) the PC of the next byte (`pc`), the queue's reads and releases (`rd`, `rd_b`, `rel`: a take step's bytes released at its end, `unc`, `relc`), the staging byte's occupancy (`stg`) |
| ~~`v35_arbiter.sv`~~ | | (A1) removed: the grant is the bus unit's, the request attributes the sequencer's ("A1" below) |
| `v35_ucode.sv` | `v35_ucode` | the microcode sequencer ((A1) and the EU's bus interface: the request register, the entry behind it, the counts and the reservation, "A1"): the ROM (four banks, a window of four rows), the T and P passes over the rows, the take sync, the start gate, unit_hold, the write-back countdown, the latch holds, the loop counters, the request descriptors; (S5a) the start-time run bits (`taken`, `zfail`, `n0`), FLUSH / FLUSH_C / DECIDE, the REP element loop's exits, the skip-ahead, the fetch-hold arms, SPLIT_FLOOR / FROM_START, the transfers' and strings' start rules, LDEA's rules, mul_imm_count=sync's `mul_from`, rot4_exec |
| `v35_eu.sv` | `v35_eu` | the datapath: the register ports' schedule, the exec (the register function), the read datum (an odd word's two halves), the divider, the request records' address / datum / width (a live EA and result for the running form's own request), the segment registers, CW, the PSW; (S5a) the transfers' targets and PC / PS / PSW writes, the return address pushes, SP at every stack post, the string unit (IX / IY / CW flops, the element steps, the compares), LDEA, LES / LDS, PUSH R / POP R, PREPARE / DISPOSE, the adjusts and conversions, the BCD strings' pairs |
| `v35_ea.sv` | `v35_ea` | (S4) the EA unit inside `v35_eu`: the mode from the format word, the base (port B) and index (port A) latched as `ea_bi`, the displacement from the operand bytes, the segment (prefix / SS for a BP mode / DS0), the physical address |
| `v35_regram.sv` | `v35_regram` | the register banks in RAM: 256 bytes, even / odd halves, port A read + write, port B read, read addresses registered at `ce` |
| `v35_trace.sv` | `v35_trace` | `ifndef SYNTHESIS`: one line per CPU clock to `+v35_trace=FILE` (the generated class names) |
| `v35_top.sv` | `v35_top` | the slot (ports of `../v35s_model.sv`), the CPU clock and reset exit (from `../v35s_chain_model.sv`), `../v35_sfr.sv`, `../v35_refresh.sv` (instantiated, not served), the SFR-store latch, the pins, the trace hook |
| `v35_lint.vlt` | | lint waivers for the reused old files and the generated package only |

The S2 stub (`v35_stub_pkg.sv`, `v35_decode_stub.svh`) and the scripted EU (`v35_eu_script.sv`)
are gone.

## Interfaces (the nets in `v35_top.sv`)

- bus → all (S0, registers only): `busy, free, cur_kind, cur_pos, cur_left, cur_on_start,
  in_wait, fetch_inflight, fetch_past_b2, fetch_end_prev, fetch_since, fetch_run_prev, io_win,
  wl_busy (wl_busy_x after this clock's T and X fills), dlv_v/kind/addr/width, done_data,
  abort_busy, abort_last, abort_done, fetch_len, grant_len`.
- (Q1) queue ↔ loader: the head window `vb0..vb3` (this clock's delivery bypassed) and its
  count `avail`; the loader's `rd` (tick A: T's takes, the IR load), `rd_b` (tick B: P's),
  `rel` (the releases: a take step's end, a ModR/M byte, the IR load; P's a clock later),
  `stg` (the staging byte: the IR full, or the running form's operand bytes outstanding off a
  delivery clock).
- (Q1) queue ↔ bus unit / arbiter: `fetch_req` (the line), `fetch_addr`, `q_low`; `fetch_go`
  (g_fetch), `dlv_v` / `dlv_data` (a fetch's word), `abort_go` (the aborted cycle running);
  bus unit → arbiter / sequencer `b2b_now` (the line sampled high at a fetch's last clock);
  arbiter → bus unit `mem_wait_o` (no back-to-back commitment while a memory request waits).
- (Q1) sequencer → queue: `susp` (the suspend windows, below), `flush` / `flush_addr` (t_flush,
  t_flush_off: the target's offset in the new PS), `ps_base` (the datapath's).
- loader → sequencer / datapath: `ir_v_c, ir_c, ir_addr_c, fmt_c, cls_c` (the IR, its format with
  the head byte as its ModR/M byte, its class constants), the same after L (`*_l`),
  `fmt_mt / fmt_mp` (the running form re-decoded with this clock's ModR/M byte, T / P), the
  decode ahead `nf_v, nf_op, nf_fmt, nf_addr`.
- sequencer → loader: `t_k, p_k, t_halt, lx_hold, idle_adj, p_io_nx`.
- sequencer → arbiter: `post_t/post_p` (the arbiter's records `rq_t/rq_p` are the datapath's,
  their window fields `ptm_t/ptm_p` the sequencer's: through, imm1, gdisp, sreg, whole,
  restart, the floors as `nb`, the poster's relatch), `retire / retire_p`, `relatch,
  relatch_late`, (S4) `floor_set, floor_nb` (disp_floor=posted), `sreg_hold_set`, `gdisp_act`
  (grp_disp), `ea_act_x` (ea_b2b), `take_now`, `disp_ext` (disp_io), `sidle`, `halting, halted,
  wb_hold, latch_wait`.
- (S4) sequencer → loader: `irh_set_t/p, irh_clr_t/p` (ir_load=disp_data).
- (S4) datapath → arbiter: `ea_live, wd_live` (the running form's memory operand address and
  result, read as its own request issues).
- (S5a) datapath → sequencer: `psw_c / psw_e, cw_c / cw_e` (the PSW and CW now and after this
  clock: the run bits of a start now and of the decode ahead), `str_last` (the REP loop's last
  element by count, a BCD string's last pair), `str_exit` (a REP compare's exit on its
  condition, at its read's delivery); sequencer → datapath: `edone` (an element's last row done:
  CW counted down), `povr_t / povr_p` (a post after the loop: the overrun read).
- (S5a) loader → sequencer: `head_odd` (the next byte's address parity); (Q1) `need_t` (the
  suspend windows' operand-bytes test), `p_load`.
- (S5a) bus → sequencer: `w3_v / w3_rel` (the last memory write among the last three cycles);
  arbiter → sequencer: `own_h2` (the own pair's second half issued: str_split), arbiter → bus:
  `g_wl_io` (a string form's I/O write: str_io_latch); sequencer → arbiter: `mf_old`
  (mul_imm_count=sync: the fetch on the bus is older than mul_from).
- (S5b) the 0F page: sequencer → loader `irh_pg_t / p` (page_ir=delivery), `mt_sub_t / p`
  (page_mtake=eu's ready move); sequencer → arbiter `pfs_x` (a 0F memory form's read not yet
  posted), `pimm_x`, `bcd_idle`; bus → arbiter `cur_b2b_pfa,
  cur_thru, prev_imm`; arbiter → bus `g_thru, g_pfa`, `g_b2b` (b2b or page_imm_run); bus ↔
  sequencer `cur_thru, g_thru` (pf_cnt); datapath → sequencer `bf_cross, bfcost, bf_ok`;
  sequencer → datapath `f_end` (the form's end: the bit field's pointer step), `edone_t`.
- sequencer → datapath: the posting row and its setup / free_need / lead (`prow_*, psetup_*,
  pfnv_*, pfn_*, plead_*`), `run_e, aim_next, fmt_e` (the next clock's form and whether it still
  reads its registers); datapath → sequencer: `cnt` (the shift count), `cl_c / cl_e` (CL now / after
  this clock: cnt0), `mneg` (MUL's sign clocks).
- datapath ↔ register RAM: `ra_next, rb_next` (the next clock's read addresses), `wa_en, wa_addr,
  wa_be, wa_data` (the write at `ce`), `ra_data, rb_data`.
- arbiter → bus/queue/EU (S4): `g_start, g_kind, g_addr, g_width, g_data, g_fetch, g_eu,
  g_slot, g_slot_fetch, g_abort, g_abort_lat, g_mem_waiting, g_b2b, g_ext, rq_set_x, retick,
  eu_issue`; the positions as the EU reads them (`slot_wait_c/p, slot_det_c/p, post_ok_c/p,
  slot_memw_c, dwq_c, dws_c, own_issued, own_done, own_done_p, own_dlv, own_two`), the fetch's
  hold reason `why_o` (the trace).

## The six stages in the code

One registered update per CPU clock at `ce` (`state_start && core_run`); everything else is
combinational, feed-forward, in this order (no settle registers, no iteration, no block reading
its own outputs; Verilator reports no `UNOPTFLAT`):

| Stage | Model phase | Where |
| --- | --- | --- |
| S0 | — | every module's registers; `v35_bus` S0 assigns; the ROM window (`q0..q3`, read at the last `ce`) and the register RAM's ports (`ra_data, rb_data`) |
| S1 | C, A | `v35_queue` "S1: arrival" (the delivered word, `lat`, `inflight_c`, `completed_now`), `retry_c` (retry_after), `room_c`; `v35_bus` `abort_done` |
| S2 | T | `v35_ucode` T pass (the `always_comb` building `s0..s4`: (A) the resume countdown and `unit_hold`, the form's end (done, write-back) and the start gate + the template's first row in the window, (B) the take sync, (C) the cursor's row, (D) one more row when it completed with `cont` (or the form ended and the next one starts), (E) a third row after an end and a start (a LEAD take's clocks)); `v35_loader` "S2 (T)"; `v35_eu` the T form (`f_t`, `ob_t`), the exec, `rq_t`; `v35_queue` `flag_s/flag_t0/flag_d/flag_r/flag_t`, `room_t`, `asked_d/t`, `sh_latch`; (S4) in `do_row` the memory forms' strobes and timers (the displacement's take: `disp`, `irclr`, disp_floor's `flset` / `dfl`, grp_disp's `gd`; the EA clocks' `easet`; mexec's retry_at; lookup_start; a post's window fields and the floors' consumption, abort_unit's setup − 1), the gate's dw_port and imm_start; `v35_loader` `irh_t`, `fr_t`; `v35_arbiter` "S2 (T): retire, post" (`a0..a2`, `pos_t`), the relatch and the floor (`b0..b2`); `v35_ea` the address of the form after T (`off`, `seg`, `phys`) |
| S3 | L | `v35_loader` "S3 (L): load_ir"; `v35_queue` `room_x`, `raw_x` (requesting), `want_w` (wants_fetch: (S5a) with `fh_act`, `odd_held`, `th_held`, `str_held`, str_raise's `flag_rs`, io_run_at's `ira`), the dating |
| S4 | X | `v35_arbiter` "S4: counting" (`counts`, `count_x`), "S4: the choice" (`fw0` .. `fw9`, `fetch_want`, `issuable`, `take_slot`, `nw_go`, `sl_fetch`, `abort_go`, `fetch_go`: one priority tree, evaluated once), "S4: the slot after the choice" (`c0..c2`: the counts, the window flags, `_promote`); `v35_queue` `flag_g`, `rq_g`, `inflight_x` |
| S5 | P | `v35_ucode` P pass (`p0..p4`, run only on `retick`: a detached I/O's issue or the own I/O write's: the start gate, one byte's take at most, the rows that follow without a take); `v35_loader` "S5 (P)" (with `ir_rel`'s IR load: ir_load=disp_data released by an EU cycle's issue); `v35_eu` the P form (`f_now`), `rq_p`; `v35_queue` `asked_p`, io_take's drop, (S4) `flag_ir`, io_take=unit's `iud`, io_ir_hold (`iih`), `nop_set`; `v35_arbiter` "S5 (P): retire, post" (`e0..e2`) |
| S6 | E | `v35_queue` "S6: check, b2b" (`latch_in`, `b2b_next`, (S5a) xfer_nt_b2b's `nb_go`, the decide row's old fetch `od_*`) and every `always_ff` / `always @(posedge clock)` block (`ce`); `v35_ucode` `ls_adj` (latch_start), `oi_adj` (one_idle), `lx_now` (long_exec), (S5a) `r4_now` (rot4_exec), `res_e`, the next cursor's row and the window's address (`wa_e`: the cursor's successors, the element loop's top, or the decode ahead's template base, its run bits from the PSW and CW after this clock), (S5a) the transfers' holds and the lea / mul_from / take-hold timers; `v35_loader` the decode ahead (`nf_*`); `v35_eu` the writes and the next clock's register addresses (POP r/m: SP before its stack read, the EA after; (S5a) PUSH R its next word's register), (S5a) the string unit's steps and its write-through; `v35_ea` the `ea_bi` latch; `v35_arbiter` `tick` / `redate` (the countdowns, the pair flag from the live address, the order flags) |

(Q1) The queue in the stages above is now: S1 the delivery and the window, S3 the request line
from the counts after tick A's reads and releases, S6 its next state (the reads, the latch); its
other S2–S6 entries (the room, the flag, the dating, b2b, the holds) are gone or moved (see "Queue
(Q1)"); the bus unit samples the line in S6 (`b2b`), the arbiter's `lup` / `lup_p` in S4 and S6.

## Registered state

| Module | State (widths) | Replaces |
| --- | --- | --- |
| `v35_bus` | `c_valid 1, c_kind 3, c_pos 3, c_len 3, c_addr 20, c_width 2, c_data 16, c_internal 1, c_ext 1`; `c_b2b 1, c_commit 1, c_on_start 1, c_run 1`; `d_v 1, d_kind 3, d_addr 20, d_width 2, done_data 16`; `gap 1, f_since 4, io_tail 2, wl 3, ab_v 1, ab_pos 2`; (S4) `c_after_post 1, c_disp_in_flight 1, c_ir_before 1`; (S5a) `w_v 1, w_ncyc 2, w_rel 5`; (S5b) `c_thru 1, c_pfa 1, c_tn 1, c_tkin 1, tk_prev 1, c_as 1, c_nt 1` (`c_ir_before` kept up after the issue); pins + `refresh_row 9` | `bus.current`, `Cycle.b2b/commit`, (S4) the fetch's start flags S5's page rules read (`x.start > pfree`, `_disp_in_flight`, `ir_t <= bus_start`), disp_io's `last_io_end = c.end + 1` (`c_ext` holds `io_tail`), `cur.start == start_clock`, `_fetch_run`, `bus.completed`, `last_end/last_fetch_end/last_io_end`, `wlatch_until`, `abort_end`; (S5a) str_single_start=write's `max(c.end for c in cycles[-3:] if c.kind == "write")`; (S5b) `Cycle.thru`, `x.b2b and x.start > pfree`, `_page_b2b`'s `take_t >= bus_start - 1` and page_b2b_win=run's `_after_take_fetch` (the plan's `take_near`, carried from the fetch before), `_page_imm_run`'s `prev.start > start_clock` / `> take_t` |
| `v35_queue` | (Q1) `q 6×8, cnt 3, unrel 3, pfp 16, inflight 1, discard 1, odd 1`; variant B `lat 1, lat_byte 8` | `bytes`, the uncommitted bytes' count, `fetch_addr`, `inflight`, `discard`; B `latched` (word_latch=byte_d) |
| `v35_loader` | `ir_v 1, ir 8, ir_addr 20, opc 8, need 3, nx 3, ra 5, modrm_next 1, stopped 1`; (S4) `irh 1`; (S5b) `pg 1, mskip 1`; (Q1) `pc 20, unc 2, relc 3` | `decoder.ir, need, nx, ready_at, modrm_next, modrm_addr/imm_reg, stopped`; (S4) `decoder.ir_hold, fresh` ((S5a) xfer_mem_ir's too, (S5b) page_ir's); (S5b) the 0F page's second byte as the re-decode's opcode, `decoder.modrm_skip` |
| `v35_arbiter` | (S4) three positions `r0` (the slot), `r1, r2` (queued), each: `v 1`, the posted `req_t` (`kind 3, nowrite 1, addr 20, width 2, data 16, setup 7, fn_v 1, fn 7 ((S5a) was 3), lead 2, port 1, detached 1, grp 1, through 7, imm1 1, gdisp 1, sreg 1, whole 1, restart 1, nb 4, rl 2, alive 1, aoff 3, dlive 1, dimm 1`, (S5a) `nwt 1, dwl 1, memc 1, fhd 1, strc 1, mfr 1, c0 4`, (S5b) `pfv 1, prw 1, pth 2, ftl 3`), `count 7, fn_v 1, fn 7, fo 7, iss 1, h2 1, two 1, dne 1, nwd 1, dn 3, nb 4, fhold 1, rs 1, lift 1, fhp 1, ghp 1, moved 1, dwm 1, rq_le 1, rq_lt 1, shl 1, sok 1, sat 1` (≈ 175 b); `own 2, rq_aio 1, io_seen 1`; (S5b) `tkq 1, tkr 1` | `Request` (`cycles`, `free_need`, `free_orig`, `issued`, the atomic pair, `done_at`, `not_before`, `floor_hold`, `ready_since`, `lift_t`, `free_held`, `grp_held`, `moved`, `dw_moved`, `requested_at` vs `posted`, `sreg_held/ok/at`; (S5a) `nowait`, `dwlike`, `mfrom`; (S5b) `pfree`, `run_wait`, `pthru`, `ftail`), `eu.req`, `eu.queued`, `eu.own`, `requested_at >= ios[-1].start`; (S5b) `requested_at == take_t` and `b2b_at != take_t` (`_page_take_ask`) |
| `v35_ucode` | `run 1, upc 11, row_c 64, rc_v 1, base 11, wa 11, q0..q3 4×64` (the ROM banks' read registers), `arm_done 1, wpass 1, res 11, left 3, taken 3, oplen 3, sync_v 1, sync_def 1, owed 2, held 1, own_v 1, dpass 1, exec_v 1, ex_age 2, ex_par 1, hold_done 1, abort_start 1, done_m 1, wbu 2, wbc 2, wbx 1, lu_inf 1, lu 3, halted 1, refill 1, nw_v 1, nw 4, first_clk 1, lx 1, elem 2 ((S5a) saturating: 0, 1, more), ltop 11, fmt 121, cc 124 (class constants), op 8, shift_held_r 1, slot_rl 2`; (S4) `fl_v 1, fl 4, dfl_v 1, dfl 3, uearly 1, gdc 2, eac 3, st_prev 1, fst 1`; (S5a) `tkn 1, zf 1, oddpc 1, ont 1, dab 1, dabs 4, lxt 1, scond 1, sfl_v 1, sfl 4, ls2 1, sfage 4, single 1, nwf 1, nwu 1, tha 1, thd 1, cva 1, sage 4, r4 1, lrc 4, lsp 1, lw_v 1, lw_rel 4, lw_fwb 3, lwc 3, mfw_v 1, mfw 4, mf_on 1, mf_cnt 4, mf_o 1`; (S5b) `flt 1, pfs 1, pfb 1, pm_a 1, pm_on 1, pm_c 4, pm_dv 1, pm_w 4, mtf_v 1, mtf 3, mrh 1, mr_v 1, mro 2, pfc 4, tlr 1, tlwb 2` (`fmt` 125, `cc` 124) | (S4) `floor_n` (imm_count=start), `dfloor_at` (disp_floor), `unit_early`, `queue.gdisp_until`, `decoder.ea_end`, `start_clock + 1`, `fetch_start`; `eu.steps/k, resume, left, taken, op_len, sync, port_take's ("slot",) insertion, own, _mem_unit_hold's data-step scan, exec_t, hold_done, abort_t == start_clock, done_t, wb, wb_until, one_idle's wb + 1, latch_until, halted, refill, left_nw, k == 1 (latch_start, one_idle), rot4_from/long_from, the string element index, shift_latched, the held I/O's class`; (S5a) `op.target` / `op.zfail` at the start, the opcode's parity (xfer_odd), `odd_until` not yet set, `abort_t >= start_clock` and the aborted cycle's end (decide_abort), the loop's exit and `op.cond`, `str_floor`, `last_issued` and `cyc[-1].start` (str_split), `str_single`, `nw_t / nw_run` (str_io_setup), the take hold's `take_hold / hold_dlv / cvt_armed`, `t - start_clock` (cvt_from), `rot4_from`, `queue.lea_ea`, `lea_split`, `lea_fend` and its fetch's end, `mul_from` and the back-count; (S5b) `full_latch`, `page_fixed`, `page_mt` / `page_mt_d`, `mt_floor`, `imm_half` / `mr_sync`, the at-post back-count of page_mem=fixed (`pf_cnt`), the step list's tail of skipped crossing alternatives |
| `v35_eu` | `fmt 121, op 8, pc 20, pfx 3, seg_o 3, ob 48, nob 3, exec_done 1, exec_pend 1, aim_ea 1, (S4) rd_lo 8, sp_done 1, pa_r 4, pb_r 4, rd 16, res 16, psw 16, ds1/ds0/ss/ps 4×16, cw 16, w2_v 1, w2_a 7, w2_be 2, w2_d 16, dv 1, ds 75 (divider), dvp 1, dv_d 16, dv_lo 16, miss 1`; (S5a) `rq0 / rq1 / rq2 3×16, nrd 4, tgt 16, nsp 3, ix 16, iy 16, dcw 1, dix 1, diy 1, srd_iy 1, srd_ovr 1, sdst 16, bi 8, bcy 1, bz 1, bres 8`; (S5b) `bfo 8, bfw 8` | the model's `regs` (registers, PSW, segments), `seg_prefix`, `templates.decode`'s operands, `v35_execute / v35_deliver / v35_wdata`'s context; (S5a) the transfers' `op.target` (the reads' words, the register), the string walk's IX / IY / CW, its compare's operands, ADD4S's carry and zero term; (S5b) `op.bf` (the bit field's offset and width registers at its exec) |
| `v35_ea` | (S4) `ea_bi 16, ea_done 1` | `v35_ea_off`'s base + index (the model's start-time `op.ea`) |
| `v35_regram` | `4 × 128 × 8` RAM, `ra_q 7, rb_q 7` | the register banks |

No clock stamps anywhere: every `x_t == t` is a strobe of the stage that produces it,
`== t-1` a registered copy (`fetch_end_prev`, `fh_prev`), an order a flag (`rq_le`), a "no
earlier than" a countdown (`res`, `ra`, `nb`, `rt_cnt`, `sh_cnt`, `lu`, `wbu`, `wl`, `io_tail`).

## The sequencer (`v35_ucode.sv`)

- **(S7a)** The passes' slots evaluate their measured vocabularies (`voc_t`, Divergence 27); a
  start reads its template from the window when its key matches the decode ahead's (`ka_v`,
  `ka_key`, Divergence 28); each row evaluator advances once (`do_row` / `do_row_b`) and the skip
  run is a table over the window computed once a clock. See "Synthesis (S7a)".
- **The ROM.** Four banks (row address mod 4: `v35_ucode_b0..3.hex`), each one block RAM with one
  read port whose read is registered at `ce`. A clock reads a window of four consecutive rows
  (`wa .. wa + 3`); the current row is kept in `row_c`. While a form runs the window holds the
  rows after its cursor; when its next row is its template's last (or no form runs) the window
  holds the first rows of the template the next form will start, from the loader's decode a
  clock ahead (the IR, or the queue's head byte when the IR is empty, with the byte behind it as
  its ModR/M byte, as they stand at the clock's end; CL after the clock for cnt0, the last
  operand byte's parity for half). A start whose first row is not in the window waits a clock
  (`dec_miss`, the trace's `W:dec`): 0 on the 5,390 S3 gate runs' starts (every run's trace
  counted, F0 .. F20).
- **The passes.** The T pass evaluates at most three rows (a row and the ones its completion
  releases: `tdelay` 0, a satisfied wait, a skipped row; a form's end, the start gate and the next
  form's first rows; (S4) in a running form the third row too: pop_mem's read delivery, its
  write's post and its clocks row on one clock); the P pass (on `retick`) the same with one
  operand byte at most, the third row only after a start. A row is
  `[skip] [ENTRY arm] [wcond] [PRE_OP arm] [op] [EXIT arm]`. The form's end (done), the start and
  then the take sync, in `eu.tick`'s order: a start does not wait for the sync, the started
  form's first row does.
- **Row semantics** as `eu.tick`: CLOCKS (a 0 count passes; `io_exec`; the exec's first clock for
  unit_hold; `abort_unit=loop`'s `retry_at` on the last row; count_latch's `shift_until`; the
  first clock flag for latch_start / one_idle; long_exec's wait-clock count), NOWAIT, TAKE (by tag:
  LEAD goes on, CHAIN / CHAIN_WORD resume a clock later, PORT relatches (a held detached I/O arms
  the NOHELD row) or posts, NONE / WORD post on the take clock (post_on_take=nomodrm) or end with
  the take sync, imm_landed's defer, count_latch, sync_req=disp; imm_latch, late_read; the
  ModR/M take re-decodes the form; io_take_nx; io_take's drop; the wlatch fill), DATA / POST /
  POST_IO, FLUSH / FLUSH_C / DECIDE (the class's fgap / cfgap / nfgap), HALT; NOP; FROM_START and
  SPLIT_FLOOR pass in no time (S5). The waits OWN_DONE, OWN_ISSUED, SLOT (then latch_until), WB,
  QUIET (S5: the fetch on the bus only). The arm HOLD (fetch_hold n); the strings' and bit fields'
  arms are S5's (decoded, not acted on).
- **(S4) The memory forms.** A post (DATA / POST / POST_IO, a PORT take's own I/O: `own_v`) asks
  the arbiter for a position (`post_ok`, the trace's `W:post` when none is free: none in the
  gate); within a pass a request posted there is not the own one the arbiter's
  `own_done / own_issued` describe (`pnew`). The post carries the window fields (`ptm`):
  rmw_alu=through (`setup - dclk - 1` for an RMW's write, `dclk` a swap form's routing clocks),
  imm1_first, grp_disp's read, sreg_store, whole / restart from the row, the floors as
  `not_before - t`, the poster's relatch; abort_unit=loop (a unit or fixed group form started on
  an aborted cycle) takes a setup clock off its first group request (`uearly`). The timers:
  imm_count=start's floor (`fl`, istart + immediate bytes, + fgrp for fixed_floor) from the
  start, disp_floor's (`dfl`, dfloor) from the displacement's take (or the slot's waiting
  request floored at once: `floor_set`), grp_disp's `gdc` (dhold clocks from the d16 take; the
  take sync then counts the fetch in flight only), ea_end's `eac` (a displaced memory form's EA
  clocks: ea_ir_room, ea_b2b). The displacement's last byte (`disp`): latch_disp, the IR's
  release on a delivery clock (`irclr`), disp_io's I/O extension. sync_req=disp: the
  displacement waits while a fetch is past its second clock (`W:late_disp`). lookup_start: a
  NOWAIT row a clock after a start whose clock issued a fetch counts a clock more (`st_prev`,
  `fst`). mexec: io_take=unit and abort_unit=loop's retry_at mtail clocks before the exec's end
  (abort_unit_end=keep: the end a clock later). The gate: dw_port=hold (a DW-form I/O request
  queued, or in the slot with an I/O cycle on the bus), imm_start=wait (the queue's room with the
  IR counted empty, `room_c0`). io_take=unit on a memory multiply / divide (the P take's drop,
  and the queue's drop on the I/O's issue: `io_unit_drop` sets `abort_start`). sreg_io=hold's
  `sreg_hold_set`.
- **(S5a) The transfers.** A start's template is picked by `v35_tmpl_of(fmt, run)` with the
  run bits from the datapath (`run_of`): `taken` from `tsel` (the condition field through
  `v35_cond` on the PSW, DBNZ's CW - 1 != 0 and DBNZE / DBNZNE's Z test (`zfail`), BCWZ's
  CW = 0; every other transfer taken), `n0` a REP string with CW = 0 (a BCD string with CL = 0);
  the T and P starts read the PSW and CW as the clock began, the decode ahead (the window) the
  PSW and CW after this clock's writes. FLUSH / FLUSH_C wait for no fetch in flight and fgap /
  cfgap clocks since the last fetch's end; DECIDE for nfgap since the end of the fetch the
  queue tracks (`dec_inf`, `dec_since`: the last one, or the one before xfer_nt_b2b's
  commitment / odd_until) and since the end of an aborted cycle that started on or after the
  start (decide_abort=cycle: `dab`, `dabs`). refill_start=full_io: after a flush no start while
  a fetch is in flight or wanted (`want_c`) nor an IN / OUT on a 3-clock fetch's delivery clock.
  At a start the queue gets flush_hold=start's class hold (a taken transfer), xfer_odd=idle (a
  taken short transfer at an odd address, `oddpc`), xfer_nt=dbnz_z (a not-taken one at an odd
  address, DBNZE / DBNZNE at either: `ont` until its clocks after the operand take set
  odd_until, nhold / chold). The other rules: late_disp_word=split (`head_odd`), stack_wb=ret (a
  RET's stack read posted on its start clock under a write-back: setup + 1), xfer_mem_ir=hold
  (`irh`), far_room / xfer_mem_room (the room's `xk`), xfer_abort (the arbiter's abort test sees
  room 3 for a transfer class; the queue raises the request at the aborted cycle's end),
  ret_far_fetch=after (REL_FOREVER, REL, FLUSH_FROM).
- **(S5a) The element loop.** A REP string's body (its `ltop` .. `loop` rows) runs again unless
  CW runs out (`str_last`: CW = 1 before its decrement, the datapath's) or a compare ends it on
  its condition (`str_exit`, at the compare read's delivery: REPE not Z, REPNE Z, REPC not CY,
  REPNC CY); a loop pass's end is `edone` (CW counted down); the exit sets `lxt` (the reads that
  follow are the overrun: `povr`, nothing compared, IX / IY not stepped) and `scond` (the COND /
  NCOND rows). `lastadd` adds the class's `last` when `str_last`. The element index `elem`
  saturates at 2 (the STR count source: first, loop1, loop). A skipped row costs no pass row:
  `sk` evaluates the row after it in its place (a final skip pair's partner: the compare's exit).
  The fetch holds: HOLD (fetch_hold n; mul_imm_half=room's HOLD_ROOM none while the queue holds
  3 bytes or fewer), REL (str_held = t + n), REL_FOREVER (for ever), REL_RAISE (str_raise: CW = 0's
  aborted start request), HOLD_TAKE / HOLD_TAKE_DLV (the take hold: from the next operand take
  no request but one raised before it; dlv: none when that take is on a word's delivery clock;
  a later HOLD lifts it), FLUSH_FROM; SPLIT_FLOOR (the last data step an odd word's pair: `ls2`,
  its second half `sfage` clocks ago), FROM_START (cvt_from; no row under fit 62), QUIET (the
  fetch on the bus or `want_c`; no row under fit 62). The strings' start rules:
  str_single_start=write (an unprefixed form no earlier than ugap clocks after the last fetch's
  end; its first request floored ugap + setup clocks after the last memory write among the last
  three cycles, the floor holding fetches), str_single_wb=index (`swb`), str_start=skip (a REP
  form's sync met on the aborted cycle's last clock), str_io_setup=run (a REP INM / OUTM's
  NOWAIT counts the first wait clock of a fetch issued on its first clock back to back), and
  str_in_io=free (`memc`, ufree).
- **(S5a) LDEA and the stack frame.** io_exec with lea_io=recover (io_recover clocks more),
  lea_room=ir (`lrc`: the EA clocks after the last operand byte), lea_slot=ea (`xk[2]`: a
  displaced LDEA's EA clocks keep the IR out of the room), lea_disp=run (`lsp`: the successor
  does not start on a back-to-back fetch's clock unless the d16 was taken off a refill run),
  lea_wb=fetch (`lw_v`, `lw_rel`, `lwc`: the next form's write-back runs to fwb clocks after the
  fetch issued on LDEA's start clock); LDEA is no memory form for the timing rules (`mem && bus`).
  prepare_sync=run (`t_prs`).
- **(S5a) The miscellany.** mul_imm_count=sync (`mul_from` = start + 1 + the EA clocks; the
  clean clocks since counted forward, `mf_cnt`, the read's count at its post; the arbiter
  restarts the count on a cycle that is not a fetch or a fetch older than mul_from: `mf_old`),
  rot4_exec=wait (`r4`, as long_exec's wait clock without the IR load's move), cvt_hold (the
  take hold, dlv).
- **(S5b) The 0F page.** A 0F form starts from the loader's page-1 format (the second opcode
  byte's entry, the byte behind it the ModR/M byte); its first take is the second byte
  (page_take=own: TAKE CHAIN on the start clock), the ModR/M take the one after it (the
  re-decode at `taken == 1`). The start rules (`start_ps`): page_ir_room=end's full latch
  (`flt`: a register bit op started with six bytes stored, the delivered word's second byte
  latched, no fetch in flight: the queue counts no seventh slot for an empty IR while it runs,
  `fl_*`, and its steps' end evaluates the request, `fl_end_*`), page_fixed (`pfs` a 0F memory
  form, `pfb` a bit field: to the first read's post), page_mtake=eu (`pm_a`: an odd address and
  a word delivered on the start clock; the ModR/M take, tried while a fetch issued on the start
  clock runs, waits to its end + 2, `pm_c`, the wait `pm_w` taken off the loader's ready
  countdown at the last operand take, `mt_sub_*`), page_mt_end=exec (`mtf`: after such a take
  a CLOCKS row no earlier than t + 1 + mtx), page_imm_sync=lead (`mrh`: a register bit op whose
  index byte is the even half of its word: its ModR/M take records the fetches in flight or
  asked (`mro`), the index byte's take ends with that sync and goes on to the ALU clocks on the
  same clock when it owes nothing). At the takes: page_ir=delivery (a 0F memory form's last
  operand byte on a delivery clock holds the IR, `irh_pg_*`), page_cl=thru's take sync (the
  fetch on the bus only, `pcs`). At the first read's post: `pfree` (`pfv`), run_wait (`prw`),
  pthru (`pth`: the class's cl), ftail (`ftl`), no DW count, and a 0F memory form's count
  counted back to its start: `pf_cnt` (`pfc`), the fetch-free clocks since the start counted
  forward (a fetch on the bus or issued, but a thru fetch of a CL-index form, restarts it), the
  read's count min(pf_cnt, setup) at the post. page_dio=free (no disp_io extension for a 0F
  memory form). bcd_fetch=hold: HOLD_LONG (element 0 only) holds requests for ever, the 0-clock
  HOLD lifts it; a BCD string started on an idle bus posts its first read a setup clock longer
  (`bcd_idle`).
- **(S5b) Skipped tails.** The bit fields' crossing alternatives (CROSS / NCROSS) are decided
  once the field is known (`bf_ok`: the exec on an earlier clock; an undecided crossing row
  waits); a run of skipped crossing rows after a completed row (up to four, as far as the window holds
  them) passes in no time and a skipped last row ends the template (`skip_run`); the cursor's
  row being the last its form runs (its tail all skipped, or a decided crossing last row) aims
  the window at the next form's template, the knowledge held while the cursor stays (`tlr`,
  `tlwb`) since the window then no longer holds the tail.
- **Counters and holds**: `res` (resume), `owed` (the take sync: in flight + asked, the defer,
  the lapse, sync_io, a held detached I/O's request not counted, abort_reg's early exec,
  abort_latched's aborted cycle), unit_hold (`ex_age`, `ex_par`, `hold_done`; a memory MUL imm on
  any clock), `wbu` / `wbc` / `wbx` (wb_until, the last row's `wb`, one_idle's clock), `lu` /
  `lu_inf` (latch_until), `abort_start`, `shift_held_r`, the element loop (`elem`, `ltop`,
  `elems` from the datapath: S5), `nw` (NOWAIT).

- **(S7a) The loader's decode** reads the tables once a clock (the decode ahead) and registers
  the next form's table entry (`pd_*`); the IR's format and the T re-decode are assembled from
  registered entries (`v35_fmt_asm`; Divergences 29, 30).

## The datapath (`v35_eu.sv`, `v35_regram.sv`, `v35_fn_pkg.sv`)

- The format's `xop` / `aop` / `opa` / `opb` / `wd` / `nwr` / `sx` / `stk` (ucgen's XOP_ATTRS)
  select the function; the register operands (RF, RM, OPR, ACC) are read through the RAM's ports,
  which the datapath names a clock ahead: the running form's while it still reads them (its exec
  not done, a post not made, the divider's DW), else the next form's (the decode ahead). A memory
  operand's EA (`v35_ea.sv`): base on port B, index on port A until latched (`ea_bi`), then
  port A the data register; the segment by the prefix (`seg_o`), SS for a BP mode, else DS0; the
  direct d16 form, XLAT's BW + AL. A stack form: SP on port B (written at the post: SP ∓ 2);
  (S4) POP r/m: SP until its stack read posts, then the EA's registers. A DW-port form: DW on
  port B.
- The exec: a register form's on the clock its last operand byte is taken (its start for a
  one-byte form), a memory / POP / IN / XLAT form's at its read's delivery (`rd`); a clock later
  when its operands were not on the ports (`exec_pend`). One register write per clock (a second,
  MUL's DW / XCH's other register / a segment register / SP, the next clock: `w2_*`, forwarded to
  the ports while pending); CW and the segment registers are written through to flops.
- The divider: DIV's exec latches the divisor and AW, the next clock DW, then
  `v35_div_step` a clock (16 / 8 steps, inside the divide's exec clocks), `v35_div_fin` at the end.
- The requests: the address by `asrc` (EA + 2i, SS:SP − 2 − 2i, SS:SP + 2i, the port byte, DW),
  the width by `wsel`, the datum by `xop` (PUSH: the source operand; PUSH PSW; OUT: AW / AL;
  a store: the source register or the immediate; an RMW: its result at the read's delivery).
  The setup, free_need (the row's x / setup − x, else the class's setup_free) and an I/O
  request's lead are the sequencer's. (S4) The running form's own request takes, as it issues,
  the live EA (`ea_live`: pop_mem posts its write before its displacement is taken; a memory
  word at an odd address is the atomic pair, hi then lo) and the live result (`wd_live`: an RMW's
  result or POP r/m's datum, registered on the read's delivery clock, the post's); store_imm's
  write (posted before its immediate is taken) has the bus take the immediate at B2
  (`g_dsel`, `wd_imm`). An odd word's read assembles its two halves (`rd_lo`). The segment
  registers and CW live in the register RAM's bank slots (every write through the RAM's port A,
  the far transfer's PS included) with flop shadows for the fetch adder and the loops.
- (S5a) The transfers: the target of the form after T (`f_t`): the next instruction's offset in
  PS + the displacement (REL), the operand's offset and segment (FAR), the register latched at
  the operand take (`tgt`: BR / CALL r16), the reads' words in order (`rq0` .. `rq2`, `nrd`: the
  pointer's offset and segment, RET's return offset and segment, RETI's PSW, BRK's vector); a far
  target writes PS (flop and bank slot), RETI the PSW's flags, BRK clears IE and BRK, RET imm16
  raises SP by its immediate; CALL pushes the return offset (CALL far: PS first), BRK PSW, PS and
  the return offset; SP moves at every stack post (`sp_post`: the burst's words address SP as
  the earlier posts left it); DBNZ's family counts CW down at the displacement's take. The
  queue's fetch address is the flush's target; the loader empties the IR.
- (S5a) The string unit: IX, IY (and CW) are flops (`rget` reads them there), stepped by the
  width (DIR: down) at each element request's post (not an overrun read's), CW counted down per
  REP element (`edone`); their bank slots are written through on a clock nothing else writes
  (`dcw`, `dix`, `diy`). A string request's address is DS0:IX (a prefix's segment) or DS1:IY;
  the datum: STM AL / AW, MOVBK / INM / OUTM the element's read datum (live on its delivery
  clock); LDM loads AL / AW; CMPBK keeps [IY] (`sdst`) and compares [IX] - [IY], CMPM AW - [IY]
  (the PSW, and `str_exit`); `srd_iy` / `srd_ovr` say what the read in flight is. The BCD
  strings (ADD4S / SUB4S / CMP4S): [IX + i] then [IY + i] (`bi`, IX / IY stay), `v35_bcd8` with
  the carry `bcy` and zero term `bz`, the result (`bres`) written back, the PSW per pair, the
  pairs (CL + 1) / 2 (`str_last`); (S5b) the pair index a post reads counts an element ended
  earlier in the same pass (`bi_now`), the pair's write takes its datum at the post.
- (S5b) The 0F page (the format's `xop` BIT1 / ROT4 / BF): TEST1 / CLR1 / SET1 / NOT1
  (`v35_bit1`, the index CL or the immediate modulo the width; a register form's at its last
  operand take, a memory form's at its read's delivery, CLR1 / SET1 / NOT1's result the write's
  datum; TEST1 the flags only); ROL4 / ROR4 (`v35_rot4` with AL on port B beside a register
  operand, on port A for a memory one; AL written after the operand); EXT / INS: at the last
  operand take the offset and width registers latched (`bfo`, `bfw`: the crossing and the cost
  `bf_cost` the sequencer reads, registered), the offset register stepped to (offset + width +
  1) mod 16 and the PSW (SUB 15, offset + width (+ 1 INS) at byte width); EXT's field into AW at
  its last read's delivery (the two words' when it crosses; an offset in AL / AH stepped after),
  INS's words written back with AW's field (AW on port A after the step: funcref's order); the
  words at DS0:IX (EXT, a prefix's segment) / DS1:IY (INS), + 2 for the next; IX / IY + 2 at
  the form's end when the field ran past its word.
- (S5a) LDEA writes the EA unit's offset (`v35_ea.off`, `ok_t`) at its last operand byte (a
  register form's exec, not a delivery); LES / LDS the offset then the segment (DS1 / DS0); POP R
  the words IY IX BP (SP's skipped) BW DW CW AW; PUSH R reads the register of its next word on
  port A (`nsp`), SP's as it stood before the burst; PREPARE BP := SP, SP -= imm16 at its exec;
  DISPOSE BP := the word, SP := BP + 2; the adjusts (`v35_adjust`), CVTBD / CVTDB.
- The function bench: `fpga/v35s/v35_rf_tb.sv` / `.cpp` / `build_rf_tb.sh` (now on `v35_fn_pkg`,
  binary `build/fpga/v35s/fn-tb/Vv35_rf_tb`) with `rtl_vectors.py --fn` (format V35FN-1: the
  `--regfile` vectors that are one function application, the expected values the functional
  reference's; the V35RF-3 line, a whole register file before and after the old package's
  `v35_execute`, does not fit a pure-function bench). (S6) The whole core's function is the
  whole-core bench's (below, "Function (S6)"); `--fn` stays as the pure functions' unit check.

## Function (S6)

### The whole-core function bench

`fpga/v35s/v35_core2_tb.sv` / `.vlt` / `.cpp`, `fpga/v35s/build_core2_tb.sh` (binary
`build/fpga/v35s/core2-tb/Vv35_core2_tb`; `V35_CORE2_TB_DIR` builds elsewhere, `V35_CORE2_TB` points
the Python side at another binary). `v35_top`, the real slot module, runs one instruction (its
prefixes included) per test:

- **Preload, not a prelude.** The model's state after its first reset is kept in memory
  (Verilator `--savable`, an in-memory `VerilatedSerialize`) and restored before every test (the
  core's reset does not clear every register: "Not built"); then a reset with the test's first
  fetch address (`v35_top.tb_reset_addr`, the queue's `reset_addr`; FFFF0h in the harness build)
  and, through `verilator public_flat_rw` hooks (`v35_core2_tb.vlt`, no RTL edit), the reset exit
  skipped (`core_run`), PCK 0 and WTC 0 (X1/2, no wait states), the PSW, PS / SS / DS0 / DS1,
  CW / IX / IY (the EU's flops) and the register RAM's bank (both copies). About 1 ms of CPU a
  test.
- **Memory.** The test's bytes are served on the bus unit's current cycle (`data_in`, the aligned
  word); an unlisted byte reads 90h (an operand read of one is counted apart by the reference:
  "reference unlisted"); a fetch outside the instruction's own bytes, or after its flush, reads
  90h, so the next instruction is a NOP (its start writes nothing); I/O reads FFFFh. Writes are
  read off the pins at their last state (the address, the lanes); the writes posted and not yet
  run when the next instruction starts (a detached OUT) are drained (the arbiter's positions, the
  bus cycle running: `o_pend_w`).
- **The end.** The test ends at the start after its own (`t_start` / `p_start`): that clock's edge
  is taken (the last form's writes on it: an IN's AL at its read's delivery, a bit field's pointer
  step), then the register RAM (the pending second write applied), CW / IX / IY and the segment
  registers from the flops (their RAM copies checked), the PSW, IP (the next start's offset in the
  expected PS), every memory byte written (each must hold the expected value; a byte the test
  lists and does not expect written must be unchanged; a write to a byte it does not list fails)
  and the I/O writes in order are compared. A divide error: only the trap condition (the
  divider's: `dvp && ds_n.trap`, `dfin && dtrap`) is checked, the trap sequence is not built. A
  test whose instruction decodes as trap_nop (class 0) is reported as such and not compared. A
  lost register write (`miss_o`), a delivery whose exec could not run (its operands not on the
  ports) and an exec still pending at the next start fail the test.
- Format V35SST-1 (two lines a test; `v35_core2_tb.cpp`'s header), from
  `rtl_vectors.C2Test`.

### SingleStepTests and `--regfile`

    fpga/v35s/build_core2_tb.sh
    python3 tools/fetch_sst_v20.py              # RTL_FILES and S6_FILES (the suite's files)
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.sst --rtl [--files ...] [--show N]
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --regfile \
        --family F0 F0w F1 F2 F3 F4 F5 F6 F7 F8 F9 F10 F11 F12 F13 F14 F15 F16 F17 F18 F19 F20 \
                 F21 F22 F23 F24 F25 F26 F27 F28 F29 F30 F31 F32 F33

`sst.py --rtl` (`rtl_vectors.sst_file`, one bench process a file) runs RTL_FILES and S6_FILES
(the files the reference now models beyond the old core's: the AL / AW,imm rows, 80 / 82, C0 /
D2, PUSH / POP r16, XCH, A0 / A2, the string forms with and without REP, the far transfers, RET
imm16 / far, RETI, BRK, PUSH / POP PSW, SAHF / LAHF, LES / LDS, DBNZNE / DBNZE / BCWZ, F6 /0).
Each test is classified (`sst.classify(..., rtl=True)`: PREPARE with a level, the LOCK prefix),
run through the reference (`sst.reference_v35_or_v20`: the expected state the suite's; the V20
classes, ROL4 / ROR4's AL and POP PSW / RETI / SAHF's fixed bits, the V35 reference's state; a
divide error the trap condition; the reference's unlisted / on-chip page / not modelled counted
apart, a not-modelled test still run against the suite's state, its I/O not compared) and run on
the bench. `rtl_vectors --regfile` runs the 58,508 `--regfile` vectors (the same RNG and the
same lines as the old core's V35RF-3 file) as single-instruction tests (`c2_case`: a pending
segment prefix becomes the prefix byte before the instruction; the memory the reference's reads
delivered; the old core's V35_EE_FUNC forms run in full). The old core's unit bench stays
(`check_regfile_old`).

### Write data on the corpus

    PYTHONPATH=host/src:. python3 -m validation.v35s.chains replay --core v35 --score --data \
        --family F0 F0w F1 ... F40 [--show N]

`replay.score_data` compares every memory, stack and I/O write of the replays (the normaliser's
`data_write`, `stack_write`, `io_write` events in order: the address, the width, the datum on its
lanes) with the silicon record's: per family the runs, the writes compared, those agreeing, the
runs that differ and the first of them. The timing scorer (`--score`) compares no data.

### Fixed (S6): the mechanisms

The bench, the suite and the write-data score found these; each is fixed in the structure (no
per-opcode code; decode attributes from `ucgen.py` where the decode was wrong):

1. **LDEA's offset in the P pass** (`v35_ea.off_n`): LDEA's exec read the EA unit's offset of the
   form after T; LDEA started in the P pass (on a detached OUT's issue) read the OUT's (its port
   byte as a direct offset): AL = 20h after F25's `OUT 20h,AL; LDEA AW,[BW]; OUT 21h,AL`, F30's
   lea and F39's out-ctl-ldea likewise. The EA unit now also forms the offset of the form after
   P from its own bytes and registers (a second adder). The T latch is no longer reused by a form
   started in T (`t_new`).
2. **PUSH r/m's datum** is the read's, live on its delivery clock (the last read's `rd` was
   written: F14 / F15 / F16 push_m pushed 0002h, the prelude's POP PSW word); **PUSH SP** pushes
   SP - 2 (F36 push_sp).
3. **store_imm's immediate at B2** (`imm_ahead`): its bytes not yet taken are the queue's head
   after T's takes (F19 / F21 / F22 / F26 MOV [m],imm16 wrote 0034h for 1234h at no wait
   states); **an RMW write issued before its exec** (its read delivered on the clock after the
   issue: C1 / D3 r/m16 at an odd address, the pair's first half wrote 00h) takes the result at
   B2 too (`wd_rdy` 0: `g_dsel`, the exec's own clock forwarded).
4. **CVTBW / CVTWL / SAHF** read AW / AH (the format names no operand: AW and DW were cleared,
   F33's cvtbw OUT); **the adjusts and converts** write AW whole (ADJBA / ADJBS's AH, CVTBD's AH,
   CVTDB's AH := 0); CVTBD by 0 leaves AH FFh and AL (the V20 suite), its flags S Z P of AL with
   CY AC V cleared; CVTDB's base is 10 whatever the byte (the V20 suite: the data book's encoding
   is D5 0AH, the corpus's only byte 0AH), its flags the byte ADD's.
5. **A move's destination is not read**: a delivery's exec (IN, POP, MOV r,m, XLAT, LES / LDS,
   POP R, MUL imm) no longer needs its destination register on the ports (an IN or POP whose
   read delivered after the ports turned to the next form lost its write: AL after IN with a NOP
   behind it).
6. **The segment's wrap at FFFFh**: every request address is the segment's base + a 16-bit
   offset (+ 2 aidx, SP - 2; `q.w16` marks a word at FFFFh, its odd pair's second half at offset
   0: the arbiter's `raddr2`, with a live EA's offset `ea_lo`); the fetch address wraps in PS
   (the queue's `ps_base`). SP = 1's pushes, POP sreg at SP = FFFFh, words at EA FFFFh / FFFEh,
   code across PS:FFFFh went to the next 64 KiB.
7. **BCWZ's decision** (`ucgen` `tsel`: bcwz was matched by its base class dbnz first): BCWZ
   was taken on CW - 1 != 0 (CW = 0 and 1 happened to agree).
8. **C6 / C7 /1-/7** store the immediate too (`ucgen` XOP_ATTRS: only /0 had MOV's attributes;
   the aliases wrote the result register's stale value).
9. **A post on its form's start clock** takes the started form's segment prefix (`seg_t`,
   `seg_n`: `seg_o` was still the last form's; a cs movsb read DS0).
10. **RET imm16 / RET far imm16** raise SP from SP after the return address's read (`sp_ret`:
    at the flush SP was off the ports, SP := the immediate).
11. **PREPARE's imm16** (immb 3: the imm16 and the level byte) was read as a byte.
12. **The empty BCD string** (CL = 0) sets CY S AC V 0, Z P 1 (the V20 suite; the PSW was left).

The counted-apart table and the scores: "Gate (S6)".

## Not built (left out of the first delivery by design)

- **Refresh timing.** `v35_refresh` runs but its request is never served (no refresh-on family is
  in the gates; the refresh rules and `refresh_hold_steps` are not ported). The refresh cycles
  silicon runs in the prelude before its RFM store are therefore not on the RTL's bus; from the
  POP PSW read on (the pre window) the RTL still matches silicon.
- **Interrupts, bank switching** (BRKCS, TSKSW, MOVSPA / MOVSPB, RETRBI, FINT, BTCLR, STOP), POLL,
  CHKIND, BRKV, the FPO escapes, READY: not decoded (trap_nop). A register-bank switch would see
  the string unit's flops' write-through (Divergence 14) and the segment shadows.
- **The trap_nop list** (above): those opcodes and halves run template 0 (CLOCKS 2, no bus).
  (S6) What each class does today, in SingleStepTests terms (the counts: "Gate (S6)"): the
  register forms the model has no template for (F6 / F7 /1 /2 /3, C6 / C7, FF /0 /1 /6 /7, 8F
  r/m with a register) and TEST r/m8,imm8 (F6 /0, both halves) take the decoder's length, run two
  clocks, write nothing, and the next instruction starts after them; a REP prefix before a
  non-string byte (the suite has them only before IDIV, F6 /7 / F7 /7) decodes as page 2's
  trap_nop half and the same. A real trap would need: a trap template (BRK 6's: the PSW, PS and
  the return offset pushed, the vector read), its timing (no corpus family measures one), the
  decoder's lengths for the trapping halves as silicon counts them, and the data book's word on
  which forms trap (it lists none of these; the V20 executes all of them).
- (S6) **The decoder's forms for undocumented aliases** (the model's `templates.decode`, so the
  generated table): F6 / F7 /1 with a memory operand decode as the rmw class with no immediate
  (the V20: TEST's alias with its imm8 / imm16; the RTL reads, writes the read datum's register
  result back, and its length is one or two bytes short) and FF /7 with a memory operand as rmw
  (the V20 pushes it: PUSH r/m's alias). MOV PS,r/m (8E with the reg field's PS) loads PS; the
  queue is not redirected (no flush), the V20 fetches on at the new PS:IP; the data book does
  not define PS as MOV's destination. Counted as divergences (sst.py: DECODE_DIVERGENCE;
  `--regfile`: `code_divergence`).
- (S6, closed in S7b) **The reset is complete.** S7b added the registers S6 found outside the
  reset blocks (`v35_queue` fh_v fh_cnt ox_* ou_* od_* xa ira th_* pb_done pr_done, `v35_bus` the
  cycle's fields and flags, the delivery's, w_v w_ncyc w_rel tk_prev and the address / data pins,
  `v35_ucode` mfw_v mfw mf_on mf_cnt mf_o). The function bench still restores the post-reset
  snapshot by default; `V35_C2_BARE=1` runs it with the reset alone (test_sst_rtl passes so).
  The ce_b registers are not reset (each is written before it is read: ce_a waits for a ce_b
  after the reset), but `g_start_b` (the mid-clock strobes read it).
- Not in the ROM under fit 62 (built, not run): QUIET (str_take=sync), FROM_START (cvt_from=take),
  HELD (cvt_tail=none: passes as a NOP). The request record's `io_ext` (disp_io_wait, a WP124
  candidate at its default `none`) is not in the record.
- The WP125 candidates (`page_mwait`, `page_dcommit`, `page_fl_end`, `page_fl_eval`) stand at
  their defaults under fit 62 and are not built (`mw_from`, `_disp_in_flight`'s commitment,
  flwb, the full-latch take's late evaluation); page_disp=hold (`pdisp_until`) likewise. The
  bus's `c_lea_start` stays a named zero input (lea_wb=fetch is the sequencer's `lw_*`).

## Queue (Q1)

The prefetch queue rebuilt as a simple machine (docs/v35s-queue-strategy.md). It knows nothing of
forms, classes, rows or the EU's steps; its 24 ports are the bus unit's request line and fetch,
the EU's reads, releases, staging byte, flush and suspend, the window.

**The machine.** Six storage bytes (`q`), the stored count (`cnt`), the count read and not yet
released (`unrel`), the prefetch pointer (`pfp`, an offset in PS: the fetch address is
`{PS, 0} + pfp` with the 16-bit wrap; an odd target fetches its word and drops the low byte),
`inflight`, `discard` (a flushed stream's word), `odd`: 25 bits beyond the bytes. The request
line `fetch_req` is a level: `free >= 2` and not suspended, `free = CAP - cnt - unrel - stg -
2·(a word in flight or the bus unit's aborted cycle)`, and the word must find a physical place
(stored + latched + in flight ≤ 7); `q_low` (the bytes counted ≤ hold_q = 3) is the arbiter's
hint. Ports: clock, reset_n, ce_a, ce_b; to the bus unit `fetch_req, fetch_addr, q_low`, from it
`fetch_go, dlv_v, dlv_data, abort_go`; to the EU `vb0..vb3, avail`, from it `rd, rd_b, rel,
stg, flush, flush_addr, susp, ps_base` (24; at 909e471: 164).

**Variant B (the default; `V35_QUEUE_A` selects A).** A byte-wide write port shared with the EU
and a one-byte latch (`lat`, `lat_byte`: 34 bits beyond the bytes), the port's owner fixed: the
EU's (a clock that releases bytes) first, else the latched byte drains, else the delivered word's
second byte. On a delivery clock that releases, the word's second byte waits in the latch,
uncounted on that clock (word_latch=byte_d); a word issued on the staging byte's room leaves its
seventh byte there until storage frees. CAP is 7: the IR is the seventh slot (room_ir). Variant
A: a word write port, CAP 6, the staging byte not counted. B is the recommendation: 23,691
RTL-exact against A's 7,858; A cannot produce the latch's uncounted delivery byte, which is the
largest single shape on F0–F3 (401 of A's 640 misses there).

**The two structural knobs** (the read / release split and the staging byte): the EU's read frees
storage at once (`rd`), its release frees the room (`rel`: a take step's bytes when the step
ends, take_commit=at_end; a ModR/M byte and the opcode when read, modrm_commit=byte; the P pass's
releases a clock later, at the next sample of the line). The loader reports `stg`: the IR holds
an opcode, or the running form has operand bytes outstanding off a word's delivery clock
(room_ir=arrival_idle from the loader's side). latch_hold is not built: holding the line while a
latched byte waits breaks the take sync's count on the line (the model counts a request
latch_hold keeps off the bus; the line cannot carry "raised but held").

**Where the fitted queue features went.**
- The bus unit samples the line at a fetch's last clock (`b2b_now`, the bus unit's register: no
  commitment while a memory request waits in the slot, request_reissue=no_mem) and runs the
  3-clock aborted cycle when a committed fetch finds the line fallen (a suspend).
- The arbiter decides a fetch from `fetch_req`, `q_low`, `b2b_now`, its last sample of the line
  (`lup`: _fetch_first's "the line rose on the clock the slot's request became issuable") and one
  bit per request record (`lup_p`: the line was up when the request was posted and has stood
  since; the I/O lead holds a fetch requested after the post). No request dating: free_hold,
  grp_io_hold, slot_fetch, grp_disp's read, page_cl=thru and wb_fetch read the line as it stands;
  hold_fetch=le_q is `!q_low` (hold_count=ahead's operand bytes not subtracted).
- The sequencer drives `susp`, the OR of its windows (the generated attributes already carry
  them: no new ROM field, `test_ucgen` unchanged): str_hold / str_fetch (the rows' HOLD / REL /
  REL_FOREVER arms), flush_hold=start and flush_from (the class's `hold`, FLUSH_FROM), xfer_odd /
  xfer_nt (`xshort`, `dbnz_z`, `dbnz`, the opcode's parity, the bus unit's fetch at the start),
  bf_imm_hold / cvt_hold (HOLD_TAKE / HOLD_TAKE_DLV, unless the line stood before the take),
  count_latch (a register shift's count taken on a delivery clock with more than a word's room
  short, to the shift's last clock), io_take=unit's drop (to the next data / I/O cycle's end or
  the count loop's retry_at), nop_hold and io_ir_hold (to the next start or a flush).
- The EU's pacing (EU rules reading the bus unit, not the queue): start_sync (no start while a
  fetch is on the bus; ModR/M forms not on a back-to-back clock; io_b2b) and the take sync on the
  line (owed = a fetch on the bus + the line up at the take, decremented by the bus unit's
  delivery). `Q1_START_SYNC` / `Q1_TAKE_SYNC` (v35_ucode.sv) turn them off: build (1) below.
- The loader owns the PC of the next byte (`pc`), the release count (`unc`, `relc`) and `stg`.
- Not built: abort_fetch=retry / abort_latched / xfer_abort's triple-clock aborts (below),
  str_raise, refill_start, the one-shot commitments (page_b2b, page_run, xfer_nt_b2b), latch_hold
  and the situational latch rules (latch_midtake, latch_disp, latch_start, modrm_port,
  arrive_partial), modrm_mate, the seventh slot's per-form refinements (far_room, xfer_mem_room,
  lea_room, lea_slot, ea_ir_room, room_ir_pre, room_ir_imm, page_ir_room, imm_start=wait), the
  request dating everywhere; the decode ahead reads four bytes (`vb0..vb3`; a fifth: a start a
  clock later, W:dec).

**The tables** (the whole refresh-off corpus, `+v35_chk`, the default spacing; `+v35_ticks=2`
gives the same 23,691 RTL-exact run for run; chk silent, `--diag` silent, every run passing).
"loss" = runs fit 62 had exact and the RTL has not; `*` over the brief's budget (10 % in F6 F12
F16 F19–F21 F23 F25 F30 F32–F34 F39 F40, 2 % elsewhere).

| Family | runs | fit 62 | B exact | B loss | A exact | A loss |
| --- | --- | --- | --- | --- | --- | --- |
| F0 | 18 | 18 | 18 | 0 (0.0%) | 9 | 9 (50.0%*) |
| F0w | 20 | 20 | 20 | 0 (0.0%) | 10 | 10 (50.0%*) |
| F1 | 54 | 54 | 54 | 0 (0.0%) | 27 | 27 (50.0%*) |
| F2 | 120 | 120 | 120 | 0 (0.0%) | 31 | 89 (74.2%*) |
| F3 | 840 | 840 | 783 | 57 (6.8%*) | 248 | 592 (70.5%*) |
| F4 | 456 | 456 | 428 | 28 (6.1%*) | 192 | 264 (57.9%*) |
| F5 | 840 | 840 | 740 | 100 (11.9%*) | 282 | 558 (66.4%*) |
| F6 | 576 | 576 | 552 | 24 (4.2%) | 69 | 507 (88.0%*) |
| F7 | 432 | 432 | 403 | 29 (6.7%*) | 143 | 289 (66.9%*) |
| F9 | 408 | 408 | 340 | 68 (16.7%*) | 69 | 339 (83.1%*) |
| F10 | 204 | 204 | 198 | 6 (2.9%*) | 41 | 163 (79.9%*) |
| F11 | 132 | 132 | 66 | 66 (50.0%*) | 0 | 132 (100.0%*) |
| F12 | 204 | 204 | 164 | 40 (19.6%*) | 39 | 165 (80.9%*) |
| F14 | 732 | 732 | 608 | 124 (16.9%*) | 251 | 481 (65.7%*) |
| F15 | 840 | 840 | 706 | 134 (16.0%*) | 291 | 549 (65.4%*) |
| F16 | 1,014 | 1,014 | 762 | 252 (24.9%*) | 234 | 780 (76.9%*) |
| F19 | 1,290 | 1,290 | 1,129 | 161 (12.5%*) | 310 | 980 (76.0%*) |
| F20 | 3,594 | 3,594 | 3,160 | 434 (12.1%*) | 870 | 2,724 (75.8%*) |
| F21 | 3,576 | 3,576 | 2,731 | 845 (23.6%*) | 956 | 2,620 (73.3%*) |
| F22 | 1,320 | 1,314 | 1,072 | 242 (18.3%*) | 206 | 1,108 (83.9%*) |
| F23 | 360 | 360 | 57 | 303 (84.2%*) | 24 | 336 (93.3%*) |
| F24 | 912 | 902 | 902 | 0 (0.0%) | 420 | 482 (52.9%*) |
| F25 | 588 | 577 | 521 | 63 (10.7%*) | 211 | 373 (63.4%*) |
| F26 | 906 | 906 | 775 | 131 (14.5%*) | 274 | 632 (69.8%*) |
| F29 | 456 | 427 | 304 | 123 (27.0%*) | 76 | 351 (77.0%*) |
| F30 | 1,476 | 1,467 | 1,061 | 408 (27.6%*) | 465 | 1,003 (68.0%*) |
| F31 | 234 | 234 | 192 | 42 (17.9%*) | 81 | 153 (65.4%*) |
| F32 | 858 | 846 | 468 | 378 (44.1%*) | 134 | 713 (83.1%*) |
| F33 | 1,050 | 1,026 | 921 | 105 (10.0%) | 358 | 671 (63.9%*) |
| F34 | 1,596 | 1,547 | 998 | 549 (34.4%*) | 214 | 1,333 (83.5%*) |
| F35 | 1,044 | 1,038 | 396 | 642 (61.5%*) | 113 | 925 (88.6%*) |
| F36 | 750 | 750 | 726 | 24 (3.2%*) | 319 | 431 (57.5%*) |
| F37 | 432 | 432 | 132 | 300 (69.4%*) | 30 | 402 (93.1%*) |
| F38 | 864 | 864 | 801 | 63 (7.3%*) | 373 | 491 (56.8%*) |
| F39 | 1,320 | 1,318 | 797 | 522 (39.5%*) | 328 | 991 (75.1%*) |
| F40 | 1,020 | 1,003 | 586 | 417 (40.9%*) | 160 | 843 (82.6%*) |
| all | 30,536 | 30,361 | 23,691 | 6,680 (21.9%) | 7,858 | 22,516 (73.7%) |

Step by step (RTL-exact per family): `base` 909e471; `s2(1)` the step-2 queue and arbiter, no take
sync, no start_sync; `s2(3)` the same with start_sync and the take sync on the line (step 2's
three builds were all 0: step 3's windows and step 4's pop timing not yet in); `B0` B with the
eager IR pop and the deferred pop (19,533); `B1` with the read / release split, the staging byte
and latch_hold dropped (21,896); `B2` with the post's line sample (23,691, the final).

| Family | runs | fit 62 | base exact | base loss | s2(1) exact | s2(1) loss | s2(3) exact | s2(3) loss | B0 exact | B0 loss | B1 exact | B1 loss | B2 exact | B2 loss |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F0 | 18 | 18 | 18 | 0 (0.0%) | 0 | 18 (100.0%*) | 0 | 18 (100.0%*) | 18 | 0 (0.0%) | 18 | 0 (0.0%) | 18 | 0 (0.0%) |
| F0w | 20 | 20 | 20 | 0 (0.0%) | 0 | 20 (100.0%*) | 0 | 20 (100.0%*) | 20 | 0 (0.0%) | 20 | 0 (0.0%) | 20 | 0 (0.0%) |
| F1 | 54 | 54 | 54 | 0 (0.0%) | 0 | 54 (100.0%*) | 0 | 54 (100.0%*) | 54 | 0 (0.0%) | 54 | 0 (0.0%) | 54 | 0 (0.0%) |
| F2 | 120 | 120 | 120 | 0 (0.0%) | 0 | 120 (100.0%*) | 0 | 120 (100.0%*) | 98 | 22 (18.3%*) | 120 | 0 (0.0%) | 120 | 0 (0.0%) |
| F3 | 840 | 840 | 840 | 0 (0.0%) | 0 | 840 (100.0%*) | 0 | 840 (100.0%*) | 654 | 186 (22.1%*) | 783 | 57 (6.8%*) | 783 | 57 (6.8%*) |
| F4 | 456 | 456 | 456 | 0 (0.0%) | 0 | 456 (100.0%*) | 0 | 456 (100.0%*) | 329 | 127 (27.9%*) | 329 | 127 (27.9%*) | 428 | 28 (6.1%*) |
| F5 | 840 | 840 | 840 | 0 (0.0%) | 0 | 840 (100.0%*) | 0 | 840 (100.0%*) | 537 | 303 (36.1%*) | 584 | 256 (30.5%*) | 740 | 100 (11.9%*) |
| F6 | 576 | 576 | 576 | 0 (0.0%) | 0 | 576 (100.0%*) | 0 | 576 (100.0%*) | 197 | 379 (65.8%*) | 516 | 60 (10.4%*) | 552 | 24 (4.2%) |
| F7 | 432 | 432 | 432 | 0 (0.0%) | 0 | 432 (100.0%*) | 0 | 432 (100.0%*) | 278 | 154 (35.6%*) | 280 | 152 (35.2%*) | 403 | 29 (6.7%*) |
| F9 | 408 | 408 | 408 | 0 (0.0%) | 0 | 408 (100.0%*) | 0 | 408 (100.0%*) | 326 | 82 (20.1%*) | 340 | 68 (16.7%*) | 340 | 68 (16.7%*) |
| F10 | 204 | 204 | 204 | 0 (0.0%) | 0 | 204 (100.0%*) | 0 | 204 (100.0%*) | 157 | 47 (23.0%*) | 156 | 48 (23.5%*) | 198 | 6 (2.9%*) |
| F11 | 132 | 132 | 132 | 0 (0.0%) | 0 | 132 (100.0%*) | 0 | 132 (100.0%*) | 62 | 70 (53.0%*) | 66 | 66 (50.0%*) | 66 | 66 (50.0%*) |
| F12 | 204 | 204 | 204 | 0 (0.0%) | 0 | 204 (100.0%*) | 0 | 204 (100.0%*) | 152 | 52 (25.5%*) | 164 | 40 (19.6%*) | 164 | 40 (19.6%*) |
| F14 | 732 | 732 | 732 | 0 (0.0%) | 0 | 732 (100.0%*) | 0 | 732 (100.0%*) | 503 | 229 (31.3%*) | 524 | 208 (28.4%*) | 608 | 124 (16.9%*) |
| F15 | 840 | 840 | 840 | 0 (0.0%) | 0 | 840 (100.0%*) | 0 | 840 (100.0%*) | 608 | 232 (27.6%*) | 640 | 200 (23.8%*) | 706 | 134 (16.0%*) |
| F16 | 1,014 | 1,014 | 1,014 | 0 (0.0%) | 0 | 1,014 (100.0%*) | 0 | 1,014 (100.0%*) | 733 | 281 (27.7%*) | 756 | 258 (25.4%*) | 762 | 252 (24.9%*) |
| F19 | 1,290 | 1,290 | 1,290 | 0 (0.0%) | 0 | 1,290 (100.0%*) | 0 | 1,290 (100.0%*) | 948 | 342 (26.5%*) | 1,015 | 275 (21.3%*) | 1,129 | 161 (12.5%*) |
| F20 | 3,594 | 3,594 | 3,594 | 0 (0.0%) | 0 | 3,594 (100.0%*) | 0 | 3,594 (100.0%*) | 2,590 | 1,004 (27.9%*) | 2,940 | 654 (18.2%*) | 3,160 | 434 (12.1%*) |
| F21 | 3,576 | 3,576 | 3,576 | 0 (0.0%) | 0 | 3,576 (100.0%*) | 0 | 3,576 (100.0%*) | 2,410 | 1,166 (32.6%*) | 2,599 | 977 (27.3%*) | 2,731 | 845 (23.6%*) |
| F22 | 1,320 | 1,314 | 1,314 | 0 (0.0%) | 0 | 1,314 (99.5%*) | 0 | 1,314 (99.5%*) | 797 | 517 (39.2%*) | 1,064 | 250 (18.9%*) | 1,072 | 242 (18.3%*) |
| F23 | 360 | 360 | 360 | 0 (0.0%) | 0 | 360 (100.0%*) | 0 | 360 (100.0%*) | 57 | 303 (84.2%*) | 57 | 303 (84.2%*) | 57 | 303 (84.2%*) |
| F24 | 912 | 902 | 902 | 0 (0.0%) | 0 | 902 (98.9%*) | 0 | 902 (98.9%*) | 772 | 130 (14.3%*) | 822 | 80 (8.8%*) | 902 | 0 (0.0%) |
| F25 | 588 | 577 | 577 | 0 (0.0%) | 0 | 577 (98.1%*) | 0 | 577 (98.1%*) | 461 | 123 (20.9%*) | 491 | 93 (15.8%*) | 521 | 63 (10.7%*) |
| F26 | 906 | 906 | 906 | 0 (0.0%) | 0 | 906 (100.0%*) | 0 | 906 (100.0%*) | 585 | 321 (35.4%*) | 651 | 255 (28.1%*) | 775 | 131 (14.5%*) |
| F29 | 456 | 427 | 427 | 0 (0.0%) | 0 | 427 (93.6%*) | 0 | 427 (93.6%*) | 198 | 229 (50.2%*) | 220 | 207 (45.4%*) | 304 | 123 (27.0%*) |
| F30 | 1,476 | 1,467 | 1,467 | 0 (0.0%) | 0 | 1,467 (99.4%*) | 0 | 1,467 (99.4%*) | 974 | 494 (33.5%*) | 1,034 | 435 (29.5%*) | 1,061 | 408 (27.6%*) |
| F31 | 234 | 234 | 234 | 0 (0.0%) | 0 | 234 (100.0%*) | 0 | 234 (100.0%*) | 174 | 60 (25.6%*) | 192 | 42 (17.9%*) | 192 | 42 (17.9%*) |
| F32 | 858 | 846 | 846 | 0 (0.0%) | 0 | 846 (98.6%*) | 0 | 846 (98.6%*) | 414 | 433 (50.5%*) | 468 | 378 (44.1%*) | 468 | 378 (44.1%*) |
| F33 | 1,050 | 1,026 | 1,026 | 0 (0.0%) | 0 | 1,026 (97.7%*) | 0 | 1,026 (97.7%*) | 772 | 254 (24.2%*) | 894 | 132 (12.6%*) | 921 | 105 (10.0%) |
| F34 | 1,596 | 1,547 | 1,547 | 0 (0.0%) | 0 | 1,547 (96.9%*) | 0 | 1,547 (96.9%*) | 876 | 671 (42.0%*) | 998 | 549 (34.4%*) | 998 | 549 (34.4%*) |
| F35 | 1,044 | 1,038 | 1,038 | 0 (0.0%) | 0 | 1,038 (99.4%*) | 0 | 1,038 (99.4%*) | 380 | 658 (63.0%*) | 393 | 645 (61.8%*) | 396 | 642 (61.5%*) |
| F36 | 750 | 750 | 750 | 0 (0.0%) | 0 | 750 (100.0%*) | 0 | 750 (100.0%*) | 616 | 134 (17.9%*) | 672 | 78 (10.4%*) | 726 | 24 (3.2%*) |
| F37 | 432 | 432 | 432 | 0 (0.0%) | 0 | 432 (100.0%*) | 0 | 432 (100.0%*) | 60 | 372 (86.1%*) | 132 | 300 (69.4%*) | 132 | 300 (69.4%*) |
| F38 | 864 | 864 | 864 | 0 (0.0%) | 0 | 864 (100.0%*) | 0 | 864 (100.0%*) | 619 | 245 (28.4%*) | 705 | 159 (18.4%*) | 801 | 63 (7.3%*) |
| F39 | 1,320 | 1,318 | 1,318 | 0 (0.0%) | 0 | 1,318 (99.8%*) | 0 | 1,318 (99.8%*) | 667 | 652 (49.4%*) | 655 | 664 (50.3%*) | 797 | 522 (39.5%*) |
| F40 | 1,020 | 1,003 | 1,003 | 0 (0.0%) | 0 | 1,003 (98.3%*) | 0 | 1,003 (98.3%*) | 437 | 566 (55.5%*) | 544 | 459 (45.0%*) | 586 | 417 (40.9%*) |
| all | 30,536 | 30,361 | 30,361 | 0 (0.0%) | 0 | 30,361 (99.4%) | 0 | 30,361 (99.4%) | 19,533 | 10,838 (35.5%) | 21,896 | 8,475 (27.8%) | 23,691 | 6,680 (21.9%) |

**The classification** of B's 6,680 misses by their first divergent clock (evtrace, X S T L P I
A compared, the model's room and the line not): (a) an EU event first (a start, take, IR load,
post, issue) or a fetch the sequencer's suspend held: EU / microcode pacing; (b) a fetch issued
or held differently with the same request line: the bus unit's or the arbiter's sampling; (c) the
model's triple-clock aborted cycle, and the fetches where the line itself differs (the queue's
count against the model's room): listed run by run in the hand-back's q1-c-list.txt.

| Family | misses | (a) | (b) | (c) | example (a) | example (b) | example (c) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F3 | 57 | 12 | 15 | 30 | F3-push-mov_cl_imm-k4-pO-w0 | F3-push-pfx_mov_aw_dw-k2-pO-w0 | F3-push-shl1-k2-pE-w0 |
| F4 | 28 | 6 | 0 | 22 | F4-push-ld_dir-k2-pE-w0 |  | F4-push-ld_bw_ix_d16-k1-pE-w0 |
| F5 | 100 | 23 | 0 | 77 | F5-push-cmp_m_imm-k1-pO-w0 |  | F5-push-add_aw_m-k2-pE-w0 |
| F6 | 24 | 0 | 0 | 24 |  |  | F6-push-ld_bw-n2d4-pE-w0 |
| F7 | 29 | 2 | 0 | 27 | F7-out-mov_aw_dw-mov_aw_dw-pE-w1 |  | F7-push-ld_bw-ld_bw-pE-w0 |
| F9 | 68 | 0 | 29 | 39 |  | F9-none-movr_nop1-pO-w0 | F9-none-movr_nop0-pE-w0 |
| F10 | 6 | 4 | 0 | 2 | F10-push-adddwi-outdw-pE-w1 |  | F10-push-adddwi-outdw-pE-w0 |
| F11 | 66 | 0 | 8 | 58 |  | F11-none-n2-movr-pE-w1 | F11-none-n0-movr-pE-w0 |
| F12 | 40 | 6 | 10 | 24 | F12-b-push-n0-addi-pE-w1 | F12-a-out-n3-movr-pO-w1 | F12-a-out-n2-shl1-pO-w0 |
| F14 | 124 | 25 | 0 | 99 | F14-t-push-test_bw_imm-pO-w0 |  | F14-t-push-add_bw_aw-k2-pE-w0 |
| F15 | 134 | 24 | 0 | 110 | F15-a-push-test_bw_imm-pO-w0 |  | F15-p-push-push_bw-k2-pE-w0 |
| F16 | 252 | 30 | 20 | 202 | F16-r-push-test_imm-x_x-pO-w0 | F16-s-none-n2-shlcl1-pE-w1 | F16-r-push-rol-x_x-pE-w0 |
| F19 | 161 | 83 | 0 | 78 | F19-i-push-l0-cmpimm-pO-w0 |  | F19-i-push-l0-stimmd8-k2-pE-w0 |
| F20 | 434 | 12 | 112 | 310 | F20-r-push-l0-adddwi-outdw-pE-w1 | F20-r-push-l0-pfxnop-movr-pO-w1 | F20-r-push-l0-nop-ld-pO-w0 |
| F21 | 845 | 213 | 0 | 632 | F21-push-n1-ld-bw_d16-pO-w0 |  | F21-push-l0-ld-bw_ix_d16-pE-w0 |
| F22 | 242 | 166 | 0 | 76 | F22-push-l0-cmp_d16-pO-w0 |  | F22-push-l0-add_d16-pE-w0 |
| F23 | 303 | 264 | 9 | 30 | F23-push-be-n0-pE-w0 | F23-out-bne-n0-k1-pE-w0 | F23-push-br-n0-pO-w0 |
| F25 | 63 | 10 | 31 | 22 | F25-out-ldea-dir-pE-w1 | F25-push-ldea-bw_ix-pO-w0 | F25-push-ldea-bw_ix_d16-pE-w0 |
| F26 | 131 | 69 | 4 | 58 | F26-push-lks-testdir-n1-k1-pO-w0 | F26-push-pi-oo-movr-n3-pE-w1 | F26-push-fib-bixd16-n0-k1-pE-w0 |
| F29 | 123 | 20 | 73 | 30 | F29-out-ec-dio-stbwd16-n2-pO-w0 | F29-out-ec-dio-dw-stbwd8-n0-pO-w0 | F29-push-ec-pi-oo-adddwi-n0-pO-w0 |
| F30 | 408 | 183 | 48 | 177 | F30-out-str-inm-w-n0-sep-pE-w0 | F30-out-nt-bne-k1-n0-pE-w0 | F30-out-str-inm-w-n0-d4-pE-w0 |
| F31 | 42 | 0 | 0 | 42 |  |  | F31-out-alf-stm-n1-ld-pE-w0 |
| F32 | 378 | 164 | 58 | 156 | F32-out-test1_mb_cl-k1-pE-w0 | F32-out-test1_rb_imm-k2-pE-w0 | F32-out-test1_mb_imm-k1-pE-w0 |
| F33 | 105 | 2 | 15 | 88 | F33-push-mul_aw_cw_imm16-k1-pE-w1 | F33-out-inc_al-k2-pO-w0 | F33-out-adj4a-k1-pE-w0 |
| F34 | 549 | 307 | 94 | 148 | F34-out-bf-ext_bl_i7-l0-k1-fld-pE-w0 | F34-out-rbit-set1_rb_cl-nop2-k1-pO-w0 | F34-out-bf-ext_bl_dh-l0-k1-fld-pE-w0 |
| F35 | 642 | 444 | 72 | 126 | F35-out-cc-bv-t-n0-pO-w0 | F35-out-cc-bv-nt-n0-pE-w0 | F35-out-ctl-adddw-pE-w0 |
| F36 | 24 | 6 | 3 | 15 | F36-out-alu-cmpb_m_imm8_80-pO-w0 | F36-push-test-test_dl_al-pO-w0 | F36-out-shift-shlb_m_cl-pE-w0 |
| F37 | 300 | 96 | 120 | 84 | F37-out-indm-callbw-n0-pO-w0 | F37-out-indm-callm-n0-pE-w0 | F37-out-indm-callbw-n0-pE-w0 |
| F38 | 63 | 3 | 0 | 60 | F38-out-grp-cmpb_m_imm8_80-pO-w0 |  | F38-out-grp-addb_m_imm8_80-pE-w0 |
| F39 | 522 | 318 | 112 | 92 | F39-out-xfer-be-nop-pE-w0 | F39-out-xfer-bne-nop-pE-w0 | F39-out-ctl-extdl-bf-pE-w0 |
| F40 | 417 | 233 | 51 | 133 | F40-out-ctl-set1bix-pE-w0 | F40-out-reg-testdl-k2-pO-w0 | F40-out-ctl-dbnze-pE-w0 |
| all | 6680 | 2725 | 884 | 3071 | | | |

The shapes, largest first (one example each): 1,527 the model's aborted cycle on a triple clock,
RTL fetches (F3-push-shl1-k2-pE-w0, (c)); 793 RTL fetches late, the line down
(F5-push-st_imm_bw_d16-k1-pE-w0); 713 RTL fetches early, the line up
(F3-push-add_dw_imm-k1-pE-w0: a P-pass pop the model's on_change flag does not evaluate); 584
RTL late with the same line (F3-push-pfx_mov_aw_dw-k2-pO-w0, (b)); 547 OUT starts early
(F3-out-mov_aw_dw-k2-pE-w1, (a)); 375 RET starts early (F23-push-callret-pE-w0, (a)); 325 PUSH
starts early (F3-push-add_dw_imm-k1-pE-w1, (a)); 300 RTL early with the same line
(F9-none-movr_nop1-pO-w0, (b)); 219 a write posted where the model posts nowrite
(F5-push-cmp_m_imm-k1-pO-w0, (a)); 190 a read issued where the model fetches
(F5-out-add_m_imm_d16-k1-pE-w0, (a)).

**The recorded (c) gap: the triple-clock aborts** (1,527 runs whose first divergence is the
model's aborted cycle, 18 of them F3's, and 38 more with the same line). The model answers a
fetch request that sees exactly a word of room on a clock where the EU starts, takes an operand
byte and loads the IR (abort_fetch=retry) with a 3-clock aborted cycle. In the simple machine
the request line is a level of the counts after the clock's reads and releases; reads and
releases only ever add room, so on such a clock the line can only rise, and "the line fell after
the bus unit committed" (the bus unit's aborted cycle here) never happens there: a level line
cannot produce this abort. The one experiment (the abort test reading the room before the
clock's reads) aborted nearly every fetch (F0–F3: 0 / 1,032) and is not kept.

**Port and state counts** (the queue and the arbiter, before → after): the queue 168 → 24 (the declared names; the strategy counted 164), its state 71 registers → 25 bits beyond the six bytes (34 in B); the arbiter 108 → 90 ports (the request dating inputs, the room views and the abort's inputs gone; `mem_wait_o` added), its per-record order flags (`rq_le`, `rq_lt`) and `tkq`, `tkr`, `rq_aio`, `io_seen` gone, `lup` and a record's `lup_p` added; the sequencer 268 → 192 ports (its 76 hold and sync strobes to the queue now its own suspend windows, `susp` out).

**Area** (efx_map, T120F484, LUT4 / FF; synth/v35_map.sh one at a time): 

| Module | 909e471 LUT4 / ADD / FF | Q1 LUT4 / ADD / FF |
| --- | --- | --- |
| `v35_queue` | 1,108 / 277 / 315 | B 542 / 52 / 106; A 407 / 40 / 97 |
| `v35_arbiter` | 1,810 / 150 / 705 | 1,767 / 139 / 687 |
| `v35_ucode` (RAM_5K 28) | 10,797 / 739 / 1,234 | 10,916 / 809 / 1,281 |

The sequencer grew: the suspend windows (the old queue's hold registers, now its own) and the
take sync on the line; its dead strobes (the one-shot commitments, the seventh slot's per-form
refinements, the retries) are constant-pruned.

**Gates.** Builds (`build_sim.sh direct v35`, `build_core2_tb.sh`, `build_rf_tb.sh`, their output
directories removed first) clean; `verilator --lint-only -Wall` clean in the four macro
configurations for B (the default) and for A (`-DV35_QUEUE_A`); `test_v35_struct`, `test_ucgen`,
`test_chain_lane`, `test_sst_rtl` 30 tests OK; the nine offline modules 941 tests, the four known
failures (test_sim TrackedFit ×3, test_freeze). Function, unmoved: `replay --score --data` on
B's replays 106,824 / 106,824 writes agreeing, 0 runs differing; `sst.py --rtl --all` 2,849,080
pass / 0 fail; `rtl_vectors --regfile` over the 35 lists F0 .. F33 69,099 vectors 0 bad, over
F34–F40 38,760 vectors 0 bad; `rtl_vectors --fn` over the 36 refresh-off families 22,455
vectors 0 bad. Timing: `+v35_chk` silent at both spacings, `--diag` silent, every run passing.

`+v35_qdbg=FILE` (simulation only) writes the queue's counts each clock. The trace's `R:` is now
the free bytes (approximate: the room without the staging byte and the latch) and the line, and
` U` marks a clock the sequencer suspends; `evtrace --keys X S T L P I A` compares without them.

### Q2: the triple-clock aborted fetch

The 1,565 misses Q1 classed as "the triple-clock aborted fetch a level line cannot produce" are one
shape (1,565 of 1,565): the start of a form, the take of its one operand byte and the IR load on
one clock (`S T:1 L:1`), the queue full before it (6 bytes and the IR, or 5 and the word delivering),
the line RISING on that clock from the clock's own two reads to exactly a word's room, on a free
bus; the chip begins the fetch and abandons it. The same two reads without the start (F9 clock 185
against 188: the queue's counts, the line and the bus identical) fetch normally, and so does a
triple that leaves a word plus one. The model never takes two operand bytes on one clock, so the
start clock is the only clock the EU consumes two queue bytes (the opcode it starts on and the
first operand byte; the IR load is the look-ahead copy of the new head). The reading: the fit's
`bytes_per_clock=1`: the BIU's count moves one byte a clock on the EU side; the request comparator
commits on the pointers' room (a word), the count is a byte behind for that clock and at the point
the cycle confirms the request (where Q1's fallen back-to-back line already aborts, `abort_go`) it
shows a word less one; with a word plus one it still shows a word and the fetch proceeds. The
request is re-evaluated at cycle ends and the EU's pops: the loop forms (register shifts, MUL / DIV)
pop nothing until their loop exits.

Built (macro `V35_Q2_TRI`, v35_front_pkg.sv; 0 restores Q1): the queue exports `q_word` (the line
up with free == 2); the arbiter aborts (`abort_tri`, the existing 3-clock aborted cycle) a fetch it
would issue on a free bus when `t_start && take_now && l_pop && q_word`; the sequencer's drop
window (`dr_v`, io_take=unit's) opens on an abort on a start clock and holds `susp` until the next
data / I/O cycle ends, the count loop's exit (`rt_fire`: unit_reg forms and memory MUL / DIV /
MULI, as `io_drop_loop`), the aborted cycle's end for a transfer (branch_short / near, dbnz, dbnz_z,
call, ret: `dr_xfer`, xfer_abort=word) or a flush. Not built: `abort_latched` (five F16-s shlcl
runs, the latched byte counted as room for the abort test).

Measured on F3 F9 F11 F14 F16 (3,126 runs, Q1 2,559 exact, 386 of the aborts): the rule 2,946
exact, 381 aborts recovered, 0 newly broken; without the start strobe 1,265 (1,473 broken: the
prelude's doubles fetch in silicon); without "exactly a word" 0; with the hold in the bus unit and
no loop exit the register-only chains starve. Whole refresh-off corpus: 24,920 RTL-exact against
23,691 (1,223 of the 1,565 aborts), no family below its Q1 count, write data 106,824 / 106,824,
lint clean with and without the macro.


### Q3: the aborted fetch as a count-path lag (measured; Q2 kept)

The question: does Q2's three-strobe abort (`t_start && take_now && l_pop` with the line up for
exactly a word on a free bus) fall out of a queue count path that moves one byte a clock (the
fit's `bytes_per_clock=1`)? Built in a side build (an Opus agent's worktree from 4f70754; the code is
not landed, see the end of this subsection): the loader reports the bytes the EU consumes on the clock (`cons`, tick A); the queue applies one of
them on the clock and the rest a clock later, and exports the line as that lagging count shows
it (`q_cnt` = the line up and `occ + (cons - 1)` still a word's room); the arbiter abandons a
fetch committed on a free bus whose request the lagging count does not confirm (`abort_lag`,
into Q1's `abort_go` and the existing 3-clock aborted cycle; no start / take / IR-load strobe in
the arbiter). The drop window in the sequencer is Q2's, unchanged.

**What "consumed" must mean.** Four kinds of clock in the corpus, the queue's counts identical
in pairs (qdbg: `rd`, `rel`, `stg`, `occ`, the line, the bus):

| clock | events | queue (rd / rel / stg) | silicon | example |
| --- | --- | --- | --- | --- |
| A | start, ModR/M or operand take, IR load | 2 / 2 / 1 -> 1 | aborts | F9-none-movr_nop0 model 188 |
| B | operand take, IR load, no start | 2 / 2 / 1 -> 1 (identical to A) | fetches | F9-none-movr_nop0 model 185 |
| C | start, ModR/M take, operand bytes left (reservation) | 1 / 1 / 1 -> 1 | fetches | F3-push-shl_imm4 (store_imm prelude) |
| D | start, ModR/M take, no IR load (the form not yet ready) | 1 / 1 / 1 -> 0 (room +2) | fetches | F9-push-movr_nop0-pO model 176 (`S:reg T:1`) |
| E | two operand bytes on one clock (`T:2`, a wide take), no start | 2 / 2 / - | fetches | F22-none-es-add8_d16-k2 model +82 |

A and B are identical in every queue count (storage pops 2, releases 2, the staging byte full
before and after); only the start tells them apart. So the count must take the opcode the start
consumes as one of the clock's bytes and must not take the IR load's move (B: one byte). C says
the start's opcode is not consumed while its form leaves operand bytes outstanding (the slot
passes to them: room_ir=arrival_idle). That gives the seven-slot definition (the build's CONS=1):
**an operand byte read, plus the opcode when a start consumes it from the IR with no operand
byte of its form outstanding; the IR load is a move between two slots, not a consumption.**
A = 2 (lag), B = 1, C = 1. But D is also 2 under it (the ModR/M and the opcode leave, the IR is
not refilled: the room rises by two to exactly a word) and silicon fetches there, and E is 2
(two operand bytes) and silicon fetches. No one-byte-a-clock count separates A from B, D and E:
with the storage pops (`rd`), B and E lag; with the seven slots, D and E lag; with the start and
the IR load as the two counted bytes, a one-byte form's start (S L, no take) lags. The only count
that reproduces A alone is "an operand byte, plus the opcode when the IR is reloaded on its
start's clock" (CONS=3), and it still lags on E; capping the take at one byte would make
it the three strobes again.

**Measured** (five families F3 F9 F11 F14 F16: Q1 2,559, Q2 2,946 exact; aborts recovered of the
386 / newly broken against Q1 / against Q2 / runs hanging):

| count (`cons`) | exact | aborts | broken vs Q1 | broken vs Q2 | hangs |
| --- | --- | --- | --- | --- | --- |
| releases − IR load + any start's opcode | 2,658 | 361 | 268 | 288 | 66 |
| operand reads + any start's opcode | 2,747 | 361 | 179 | 199 | 66 |
| releases − IR load + opcode (nothing outstanding) | 2,799 | 381 | 147 | 147 | 40 |
| **operand reads + opcode (nothing outstanding)** (CONS=1) | 2,888 | 381 | 58 | 58 | 40 |
| storage pops (`rd`: the take and the IR load) | 1,294 | 209 | 1,480 | 1,652 | 0 |
| start's opcode + IR load | 1,067 | 48 | 1,540 | 1,879 | 515 |
| operand reads + opcode when the IR reloads (CONS=3) | 2,946 | 381 | 0 | 0 | 0 |

The CONS=1 breaks are all D clocks (F9 37, F11 20, F14 1; 37 of the 58 hang: the abort on a
register form opens the drop window, which waits for a data cycle's end a register-only chain
never produces). The whole refresh-off corpus (`+v35_chk`): CONS=1 24,448 RTL-exact against
Q2's 24,920 (0 gained, 472 lost: F20 149, F22 76, F21 53, F9 37, F19 30, F11 20, F30 22, F39 19,
F31 18, F15 13, F12 12, F7 9, F2 6, F26 5, F34 2, F14 1; F2 below Q1), 1,223 of the 1,565 aborts
(the same as Q2), 63 runs hanging, write data 106,761 / 106,824 (63 runs differing); CONS=3
24,777 (0 gained, 143 lost: F22 76, F21 53, F19 12, F26 1, F30 1, all E clocks: `T:2 A` where
silicon fetches), 1,223 aborts, 0 hangs, write data 106,824 / 106,824.

**Kept: Q2.** The lag form cannot see the discriminator: A and B differ only by
the start, A and D only by the IR load, A and E only by the start and the IR load; a count of
bytes per clock is the same on A as on one of them. What remains of the reading: the abort is the
coincidence of the start's opcode leaving, an operand byte leaving and the IR being reloaded on
one clock, which Q2's three strobes state directly. The side build with its macro off reproduced Q2 run
for run (the five families 2,946 identical; the corpus 24,920 at both spacings, the function gates and lint
unmoved), so nothing of the measurement is in doubt; its code (a `cons` output on the loader, a `q_cnt`
output on the queue, an `abort_lag` in the arbiter: 125 lines, two ports on the queue) is not landed, since
it is a rejected mechanism and the queue is to stay the simple machine of Q1. The patch and the per-run
tables are in the session's scratchpad (v2/q3/) and the Record entry of 2026-11-07 in docs/v35s-core-v2.md.

### R1: the EU / microcode misses the simple queue left (class (a))

Six fitted rules that the old queue applied through its situation ports, re-expressed on EU facts
(format bits, the loader's `need` and IR hold) and bus-unit facts (the fetch on the bus, the line
as last sampled, the slot's waiting request); the queue is untouched (no new port, no new state,
no input naming a form). One macro each in v35_front_pkg.sv (1: built; 0: the 541d91e core).

| Macro | Fitted rule | Where it lives | Facts it reads | Corpus gained / lost |
| --- | --- | --- | --- | --- |
| `V35_R1_REFILL` | refill_start=full_io (eu._start) | the start gate (`rfb_c`, the sequencer's `Q1_REFILL`): after a flush no start while a fetch is on the bus or the line stood at the last clock | `refill` (set by the FLUSH, cleared by the start), `inflight_c`, `rfl` (a new 1-bit register: the line at the last clock, ce_a from `fetch_req_b`) | +1,143 / 0 (F35 378, F23 258, F39 168, F30 105, F40 100, F37 78, F34 56) |
| `V35_R1_PGRUN` | page_run=field (queue.end_clock) | the arbiter: while a 0F memory form's read is unissued (`pg_act_x`) the waiting read does not hold the bus unit's back-to-back sample (`mem_wait_o` low), once per form | `pfs_x`, the slot's `pfv`, `b2b_now`, `t_start`; `pr_used` (1 bit) | +177 / 0 (F32 96, F34 54, F39 27) |
| `V35_R1_NEED` | hold_count=ahead (arbiter hold_fetch=le_q) | the arbiter's `hold_le`: the bytes counted less the running form's operand bytes still to take; with one or more outstanding the hold lapses whenever the line stands (counted ≤ hold_q + 1 is the line itself) | `q_low`, the line, the loader's `need_t` (a new arbiter input), the request's `whole` bit | +651 / 0 (F21 178, F32 96, F22 76, F38 60, F34 44, F40 36, F19 34, F15 27, F5 23, F35 18, F16 / F33 / F36 12, F26 8, F25 / F39 6, F14 3) |
| `V35_R1_IRH` | ea_ir_room under ir_load=disp_data (queue.room) | the loader's `stg`: the empty IR is no free seventh slot while its load is held for the form's data cycle and no operand byte is left | `irh_t`, `need_t` | +418 / 0 (F21 302, F26 43, F37 36, F34 17, F29 8, F4 6, F14 6) |
| `V35_R1_NOMEM` | request_reissue=no_mem (queue.issue) | the arbiter: a fetch issued beside a waiting memory request leaves the bus unit's view of the line down (no fetch wanted, `lup` low) until the queue next changes | `g_fetch`, `mem_wait`, `fetch_end_prev`, `take_now`, `l_pop`; `nm` (1 bit) | +26 / 0 on F5 F19 F21 F22 F26 F32 F34 |
| `V35_R1_FHDATE` | free_hold=delivery's dating (arbiter) | the arbiter's `fetch_first`: the fetch free_hold held goes before a request that became issuable on the clock the hold ends | `fh_date` (the record's `fhp`), `rs_now` | +21 / 0 on the same seven (NOMEM + FHDATE on the corpus: +47 / 0, F22 18, F21 11, F5 10, F19 4, F26 4) |

Each rule was measured alone on the families it touches against the previous step's per-run set,
then on the whole refresh-off corpus (cumulative, in the order of the table): no run lost at any
step, no family below 541d91e. The whole refresh-off corpus goes from 24,920 to **27,356 RTL-exact**
(27,346 of fit 62's 30,361), identical run for run at `+v35_chk` and `+v35_ticks=2 +v35_chk`,
chk silent, `--diag` silent, no run failing; write data 106,824 / 106,824.

**The classification** (re-built: the hand-back's classify.py; evtrace's keys X S T L P I A, the
first divergent clock; the model's `P:nowrite` compares equal to the RTL's `P:write`, which the
trace has no other name for: 213 of Q1's 262 "P" misses were that naming and diverge later).
(a) 2,574 → 762, (b) 1,135 → 1,173, (c) 1,742 → 1,080 (the hold_count and IR-hold rules also
removed most of the "line differs" misses). Per family (exact = RTL-exact and fit-62-exact):

| Family | runs | fit 62 | 541d91e exact | (a) | (b) | (c) | R1 exact | (a) | (b) | (c) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F0 | 18 | 18 | 18 | 0 | 0 | 0 | 18 | 0 | 0 | 0 |
| F0w | 20 | 20 | 20 | 0 | 0 | 0 | 20 | 0 | 0 | 0 |
| F1 | 54 | 54 | 54 | 0 | 0 | 0 | 54 | 0 | 0 | 0 |
| F2 | 120 | 120 | 120 | 0 | 0 | 0 | 120 | 0 | 0 | 0 |
| F3 | 840 | 840 | 801 | 12 | 15 | 12 | 801 | 12 | 15 | 12 |
| F4 | 456 | 456 | 437 | 6 | 0 | 13 | 443 | 0 | 0 | 13 |
| F5 | 840 | 840 | 776 | 14 | 9 | 41 | 809 | 4 | 18 | 9 |
| F6 | 576 | 576 | 552 | 0 | 0 | 24 | 552 | 0 | 0 | 24 |
| F7 | 432 | 432 | 430 | 2 | 0 | 0 | 430 | 2 | 0 | 0 |
| F9 | 408 | 408 | 379 | 0 | 29 | 0 | 379 | 0 | 29 | 0 |
| F10 | 204 | 204 | 198 | 4 | 0 | 2 | 198 | 4 | 0 | 2 |
| F11 | 132 | 132 | 124 | 0 | 8 | 0 | 124 | 0 | 8 | 0 |
| F12 | 204 | 204 | 186 | 6 | 10 | 2 | 186 | 6 | 10 | 2 |
| F14 | 732 | 732 | 695 | 13 | 6 | 18 | 704 | 7 | 9 | 12 |
| F15 | 840 | 840 | 783 | 12 | 12 | 33 | 810 | 12 | 18 | 0 |
| F16 | 1014 | 1014 | 947 | 24 | 31 | 12 | 959 | 24 | 31 | 0 |
| F19 | 1290 | 1290 | 1135 | 24 | 59 | 72 | 1173 | 20 | 65 | 32 |
| F20 | 3594 | 3594 | 3420 | 12 | 133 | 29 | 3420 | 12 | 133 | 29 |
| F21 | 3576 | 3576 | 2893 | 213 | 12 | 458 | 3384 | 12 | 12 | 168 |
| F22 | 1320 | 1314 | 1072 | 54 | 112 | 76 | 1166 | 30 | 118 | 0 |
| F23 | 360 | 360 | 57 | 264 | 9 | 30 | 315 | 0 | 9 | 36 |
| F24 | 912 | 902 | 902 | 0 | 0 | 0 | 902 | 0 | 0 | 0 |
| F25 | 588 | 577 | 514 | 10 | 31 | 22 | 520 | 10 | 31 | 16 |
| F26 | 906 | 906 | 788 | 69 | 4 | 45 | 843 | 38 | 4 | 21 |
| F29 | 456 | 427 | 304 | 20 | 73 | 30 | 312 | 14 | 73 | 28 |
| F30 | 1476 | 1467 | 1125 | 223 | 48 | 71 | 1230 | 88 | 48 | 101 |
| F31 | 234 | 234 | 234 | 0 | 0 | 0 | 234 | 0 | 0 | 0 |
| F32 | 858 | 846 | 468 | 164 | 58 | 156 | 660 | 124 | 62 | 0 |
| F33 | 1050 | 1026 | 933 | 2 | 15 | 76 | 945 | 2 | 15 | 64 |
| F34 | 1596 | 1547 | 998 | 307 | 94 | 148 | 1169 | 189 | 98 | 91 |
| F35 | 1044 | 1038 | 396 | 446 | 72 | 124 | 792 | 18 | 72 | 156 |
| F36 | 750 | 750 | 726 | 0 | 9 | 15 | 738 | 0 | 9 | 3 |
| F37 | 432 | 432 | 132 | 110 | 120 | 70 | 246 | 0 | 120 | 66 |
| F38 | 864 | 864 | 801 | 0 | 3 | 60 | 861 | 0 | 3 | 0 |
| F39 | 1320 | 1318 | 852 | 318 | 112 | 36 | 1053 | 69 | 112 | 84 |
| F40 | 1020 | 1003 | 640 | 245 | 51 | 67 | 776 | 65 | 51 | 111 |
| all | 30536 | 30361 | 24910 | 2574 | 1135 | 1742 | 27346 | 762 | 1173 | 1080 |

**The (a) sub-kinds before → after:** the start holds (S, L+P+S, L+S, L+S+T, P+S, S+T) 1,670 → 216;
I / I+L 718 → 356; P 43 → 43; L+T / T 28 → 28; the suspend windows (`fetch_late` with `U`) 115 → 119.

**Not recovered (recorded):**
- *The suspend misses are line misses* (119; F30 54, F34 34, F16 20). F30-out-str-inm-w-n0-sep-pE-w0
  t+94 and F12-b-none-n2-shli-pO-w1 t+80: a count-byte shift starts on a word's delivery clock;
  the model fetches on its request raised before (room 0 at the clock's end, -1 after), the RTL's
  line is down (free 1) as well as its count_latch window: the queue would have to count the
  delivered word's latched byte as the model's latch rules do. A (c) gap.
- *The 0F read's setup count* (I, F32 114 / F34 72 / F39 30 / F40 30): F32-out-test1_mb_cl-k1-pO-w0
  t+91 and F14-t-out-test_dir_aw-pO-w0 t+91: the read posted on an OUT's issue clock issues five
  clocks before the model's (page_mem=fixed, run_wait), or before the model's fetch: the request
  record's count in the arbiter, not a queue count. Open.
- *Starts and IR loads beside a 4-clock fetch* (S / L+P+S / L+S, F10 F12 F14 F15 F19 F20, w1):
  F14-o-out-movr2-pE-w1 t+92 and F10-push-adddwi-outdw-pE-w1 t+90: the RTL starts on a fetch's
  issue clock with its line up (free 3) where the model's room is 0-1 and its line down: the
  counts differ before the start. A (c) gap.
- *A start a clock early after a 0F register bit form* (S / S+T, F34 rbit, F39 page-set1):
  F34-out-rbit-set1_rb_cl-nop-k1-pO-w0 t+96 and F39-push-page-set1-movr-pO-w0 t+88. Open (the
  page form's last clocks or page_b2b's commitment, not built).
- *P* (43: the RTL posts a bit field's read on its IR-load clock, F34-out-bf-ext_bl_dh-nop-k1-pO-w0
  t+92), *L+T* (22: F3-push-mov_cl_imm-k4-pO-w0 t+100, an IR load and take a clock early with the
  line up where the model's is down), *T* (6), *L+S+T* on not-taken branches (xfer_nt's aborted
  cycle, F30-out-nt-bne-k3-n0-pO-w0 t+105, the model's `A`): open.

**Gates.** `verilator --lint-only -Wall` clean in the four configurations, with `-DV35_QUEUE_A` and
with every R1 macro 0; the six macros at 0 reproduce 541d91e run for run (F21 F22 F23 F32 F35);
`test_v35_struct`, `test_ucgen`, `test_chain_lane`, `test_sst_rtl`, `test_rtl_vectors` OK (ucgen
untouched: no row or decode attribute changed); `sst.py --rtl --all` 2,849,080 pass / 0 fail;
`--regfile` F0..F33 69,099 and F34–F40 38,760 vectors 0 bad; `--fn` over the 36 refresh-off
families 22,455 vectors 0 bad. Timing guidance: `rfl`, `pr_used`, `nm` are registers (one bit each, ce_a
from their ce_b copies); the start gate gains one registered term; the arbiter's fetch-hold tree
gains the loader's `need_t` (a tick-A output it already feeds the sequencer) and `nm`'s three
strobes (take_now, l_pop, fetch_end_prev: inputs the arbiter already reads).

### R2: the bus unit's and the arbiter's sampling of the request line (class (b))

The (b) misses (the request line the same on both sides on the first divergent clock, the fetch
issued or held differently) re-read against the frozen model run instrumented at that clock (which
fitted rule issued or held the model's fetch: the hand-back's an/why.py). Three rules are built
as bus-unit / arbiter samples on facts the arbiter already reads; the queue is untouched (no port,
no state), no input names a form, class, row or EU step, no request is dated. One macro each in
v35_front_pkg.sv (1: built; 0: the 0a696bc core).

| Macro | Fitted rule | Sampling point / clearing event | Facts it reads | Corpus gained / lost |
| --- | --- | --- | --- | --- |
| `V35_R2_SLOT` | slot_room=word (grp_read=rmw_slot_any; arbiter.py _choose's nowrite slot) | the left-out write's slot chosen on a word's delivery clock runs a fetch: the bus unit chose the slot's cycle at the fetch's last clock, before the word was written, so the delivered word is room (`sl_dlv`; no state: the decision point is the delivery clock itself) | `fetch_end_prev`, `fetch_inflight`, `nw_go` | +186 / 0 (F22 78, F19 51, F5 18, F15 15, F14 9, F16 6, F36 6, F38 3) |
| `V35_R2_GDLUP` | grp_disp=hold's take-clock exemption (room for two words after the take) | on the group form's displacement take clock a fetch goes only if the line stood before the take (`lup`, the bus unit's sample at the last clock, cleared by a fetch or the aborted cycle issued on it) or the bus unit is in its fetch run (a fetch ended on t-1); the room the take itself frees is not counted (`gd_go`) | `q_low`, `lup`, `fetch_end_prev`, `take_now`, `gdisp_act` | +46 / 0 (F37 42, F29 4) |
| `V35_R2_DWLUP` | dw_lift=moved (the I/O lead; arbiter.py _choose) | a DW-form I/O request (no port byte) moving into the slot takes as its post's sample (`lup_p`) the bus unit's sample from before the move-in clock (`lup`, and no fetch ending then), not the line on the move-in clock: a fetch the move-in clock raised goes after the I/O; cleared as `lup_p` is (a fetch or the aborted cycle issued, the line falling) | `lup`, `fetch_end_prev`, the record's kind and port bit | +18 / 0 (F29 18) |

Measured one at a time on their families against the previous step's per-run set, then the whole
refresh-off corpus cumulatively: +250 / 0, no family below 0a696bc. The whole refresh-off corpus goes
from 27,356 to **27,606 RTL-exact** (27,596 of fit 62's 30,361), identical run for run at `+v35_chk`
and `+v35_ticks=2 +v35_chk`, chk silent, `--diag` silent, no run failing; write data 106,824 / 106,824.

**The classifier's reading of the model's line.** The model's `R:room:flag` is the clock's end: on a
clock it fetches, the issue has reserved the word (room − 2) and cleared the flag. Q1's / R1's
classify.py compares that flag with the RTL's line, so every model fetch reads as "line down": 277
of the 1,173 (b) misses at 0a696bc (161 on `S T:1` clocks, 85 on free clocks, 31 on `S` clocks:
F11-none-n2-movr-pE-w1 t+80, F25-push-ldea-bw_ix-pO-w0 t+84, F33-out-inc_al-k2-pO-w0 t+91) are model fetches with room + 2 >= 2 before the issue (the line UP) against the RTL's
line down (free 0 / 1: the queue's count, e.g. phys_ok or the seventh slot): class (c). classify2.py
(the hand-back) reads the model's line before its own fetch (room >= 0 at the clock's end);
recls.py applies it to an existing jsonl. At 0a696bc: (a) 762, (b) 1,173 → 896, (c) 1,080 → 1,357.

**The shapes** (0a696bc, (b) by the corrected reading, 896): 243 the nowrite slot on a delivery
clock (SLOT); 140 xfer_nt_b2b=decide and 167 page_b2b=reg (the model's one-shot back-to-back
commitments with a byte of room); 180 + 34 grp_disp=hold's take clock (GDLUP, then the room
count below); 45 + 38 latch_hold / abort_latched (the latched byte); 39 dw_lift=moved and the I/O
lead (DWLUP and later divergences); 10 F32 / F34 0F memory bit forms. The brief's reading of the
largest shape ("a request that stood earlier and has since fallen": request_hold=lapse) is not
the mechanism: request_hold=lapse never honours a fallen request; every `R:-1:0` model fetch is
the nowrite slot on a delivery clock (243) or a one-shot commitment (307).

**Not recovered (recorded):**
- *xfer_nt_b2b=decide* (140; F35 72, F39 23, F30 21): F23-out-bne-n0-k1-pE-w0 t+93 and
  F23-out-bne-n2-pE-w0 t+93: at a fetch's last clock, while a not-taken short branch is at its
  decide step, the model commits back to back with a byte of room (room 1, line down), nothing
  latched, once per form. It needs a count the queue does not export (room >= 1, the latch empty)
  and the decide row's strobe (`ntb_ok`, which exists in the sequencer, unused): (c), and an input
  naming an EU step.
- *page_b2b=reg* (167; F34 77, F32 58, F39 24): F32-out-test1_rb_imm-k2-pE-w0 t+99 and
  F32-out-test1_rw_imm-k2-pE-w0 t+99 (the `R:-1:0 / R:1:0` form: F32-out-test1_rb_cl-k1-pO-w1 t+93):
  the 0F register form's commitment with a byte of room; the same two counts and the format's
  `page_reg`: (c).
  A generic form was measured and rejected: the bus unit committing at a fetch's last clock on the
  line OR `q_low` sampled at that fetch's issue (a byte of room left after the reservation, no form
  input): 706 of the first ~1,400 runs of F9 F14 F23 F32 failed (stalls) before the replay was stopped.
- *grp_disp=hold's take clock, the room after the reads* (126; F37 66, F29 30, F39 18, F40 12):
  F29-out-ec-gih-incd16-n1-pO-w0 t+92 (delivery clock, `T:2 L:1`, room 3 after the reads: the
  model holds) against F29-out-ec-gih-incd16-n1-pE-w0 t+91 (the same strobes, room 4: the model
  fetches): the line, `lup` (down: the word in flight at t-1), `q_low` and every strobe are
  identical; only the room after this clock's reads (>= 4) separates them. `lup` alone recovers 142
  but loses these 5 (+137 / −5 on F5 F29 F32 F34 F36 F37 F38), so the fetch run exempts the
  delivery clock and the 96 room-3 delivery-clock runs stay: (c).
- *latch_hold* (102; F22 40, F9 25, F16 20, F19 14): F15-a-none-test_bw_imm-pE-w0 t+95 and
  F15-a-none-test_bw_imm-pE-w1 t+99: a register shift's start + take + IR load with the line up
  (room 3) while a byte delivered earlier is still latched and cannot go in: the model holds the
  fetch. The queue's latched byte is not exported (Q1 left latch_hold out): (c).
- *abort_latched* (38; F20 21, F21 12, F16 5): F16-s-none-cl1-n1-shlcl-pO-w0 t+82 and
  F16-s-none-cl2-n1-shlcl-pO-w0 t+82: Q2's triple-clock abort with the latched byte counted as
  room: the latched byte again: (c).
- *0F memory bit forms* (10; F32 set1_mw 8, F34 mbit 2): F32-out-set1_mw_cl_bw_d16-k1-pO-w1 t+93
  and F32-out-set1_mw_cl_dir-k1-pO-w1 t+93: the RTL's back-to-back commitment beside the 0F read
  that page_run=field's once-per-form rule had already spent in the model (its commitment on the
  clock before the read's P-pass post: the arbiter's `pg_act_x` is low on the clock between,
  neither unposted after T nor yet in the slot). Counting that clock (`slot_pf_e` in tick B) was
  measured: 0 / 0 on F32 F34 F39 F40 (the run then diverges on the read's page count); not kept, open.

**Gates.** `verilator --lint-only -Wall` clean in the four configurations, with `-DV35_QUEUE_A` (four) and with
the three R2 macros 0; the macros at 0 reproduce 0a696bc run for run (F5 F19 F22 F29 F37, 4,338 runs);
`test_v35_struct`, `test_ucgen`, `test_chain_lane`, `test_sst_rtl`, `test_rtl_vectors` OK (ucgen untouched);
`sst.py --rtl --all` 2,849,080 pass; `--regfile` F0..F33 69,099 and F34–F40 38,760 vectors 0 bad; `--fn`
over the 28-family list 19,752 vectors 0 bad. Timing guidance: no new register (SLOT reads the delivery
clock, GDLUP the existing `lup` and `fetch_end_prev`, DWLUP sets the record's existing `lup_p` from `lup`
at the promotion); each adds one AND / OR term on registered facts to the fetch-hold tree or the slot's
fetch, no comparator. `+v35_chk` silent at both spacings.

**The classification at the end** (classify2's reading; exact = RTL-exact and fit-62-exact; classify.py's
own reading: (b) 1,173 → 860, (c) 1,080 → 1,143; the 63 more (c) are runs whose first divergence moved
past a recovered (b) clock to a count clock):

| Family | runs | fit 62 | 0a696bc exact | (a) | (b) | (c) | R2 exact | (a) | (b) | (c) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F0 | 18 | 18 | 18 | 0 | 0 | 0 | 18 | 0 | 0 | 0 |
| F0w | 20 | 20 | 20 | 0 | 0 | 0 | 20 | 0 | 0 | 0 |
| F1 | 54 | 54 | 54 | 0 | 0 | 0 | 54 | 0 | 0 | 0 |
| F2 | 120 | 120 | 120 | 0 | 0 | 0 | 120 | 0 | 0 | 0 |
| F3 | 840 | 840 | 801 | 12 | 0 | 27 | 801 | 12 | 0 | 27 |
| F4 | 456 | 456 | 443 | 0 | 0 | 13 | 443 | 0 | 0 | 13 |
| F5 | 840 | 840 | 809 | 4 | 18 | 9 | 827 | 4 | 0 | 9 |
| F6 | 576 | 576 | 552 | 0 | 0 | 24 | 552 | 0 | 0 | 24 |
| F7 | 432 | 432 | 430 | 2 | 0 | 0 | 430 | 2 | 0 | 0 |
| F9 | 408 | 408 | 379 | 0 | 25 | 4 | 379 | 0 | 25 | 4 |
| F10 | 204 | 204 | 198 | 4 | 0 | 2 | 198 | 4 | 0 | 2 |
| F11 | 132 | 132 | 124 | 0 | 0 | 8 | 124 | 0 | 0 | 8 |
| F12 | 204 | 204 | 186 | 6 | 0 | 12 | 186 | 6 | 0 | 12 |
| F14 | 732 | 732 | 704 | 7 | 9 | 12 | 713 | 7 | 0 | 12 |
| F15 | 840 | 840 | 810 | 12 | 18 | 0 | 825 | 12 | 3 | 0 |
| F16 | 1014 | 1014 | 959 | 24 | 31 | 0 | 965 | 24 | 25 | 0 |
| F19 | 1290 | 1290 | 1173 | 20 | 65 | 32 | 1224 | 20 | 14 | 32 |
| F20 | 3594 | 3594 | 3420 | 12 | 21 | 141 | 3420 | 12 | 21 | 141 |
| F21 | 3576 | 3576 | 3384 | 12 | 12 | 168 | 3384 | 12 | 12 | 168 |
| F22 | 1320 | 1314 | 1166 | 30 | 118 | 0 | 1244 | 30 | 40 | 0 |
| F23 | 360 | 360 | 315 | 0 | 9 | 36 | 315 | 0 | 9 | 36 |
| F24 | 912 | 902 | 902 | 0 | 0 | 0 | 902 | 0 | 0 | 0 |
| F25 | 588 | 577 | 520 | 10 | 0 | 47 | 520 | 10 | 0 | 47 |
| F26 | 906 | 906 | 843 | 38 | 0 | 25 | 843 | 38 | 0 | 25 |
| F29 | 456 | 427 | 312 | 14 | 73 | 28 | 334 | 14 | 30 | 49 |
| F30 | 1476 | 1467 | 1230 | 88 | 21 | 128 | 1230 | 88 | 21 | 128 |
| F31 | 234 | 234 | 234 | 0 | 0 | 0 | 234 | 0 | 0 | 0 |
| F32 | 858 | 846 | 660 | 124 | 62 | 0 | 660 | 124 | 62 | 0 |
| F33 | 1050 | 1026 | 945 | 2 | 0 | 79 | 945 | 2 | 0 | 79 |
| F34 | 1596 | 1547 | 1169 | 189 | 92 | 97 | 1169 | 189 | 92 | 97 |
| F35 | 1044 | 1038 | 792 | 18 | 72 | 156 | 792 | 18 | 72 | 156 |
| F36 | 750 | 750 | 738 | 0 | 6 | 6 | 744 | 0 | 0 | 6 |
| F37 | 432 | 432 | 246 | 0 | 120 | 66 | 288 | 0 | 66 | 78 |
| F38 | 864 | 864 | 861 | 0 | 3 | 0 | 864 | 0 | 0 | 0 |
| F39 | 1320 | 1318 | 1053 | 69 | 83 | 113 | 1053 | 69 | 65 | 131 |
| F40 | 1020 | 1003 | 776 | 65 | 38 | 124 | 776 | 65 | 26 | 136 |
| all | 30536 | 30361 | 27346 | 762 | 896 | 1357 | 27596 | 762 | 583 | 1420 |

### R3: the loader's release timing and the remaining aborted fetches (class (c))

The (c) misses (the request line differs on the first divergent clock: the queue's count against the
model's room) by shape, re-read against the frozen model instrumented at that clock (the hand-back's
an/rows.py, an/room.py: the model's room() pieces, its request evaluation). Six rules are built, each
behind a macro in v35_front_pkg.sv (1: built; 0: the 8d0547e core). They are loader release / staging-byte
timing on format bits and the sequencer's existing strobes, and one term on the queue's existing `q_word`
output (`q_short`); no new queue input, no queue state, no input naming a form, no request dating.

| Macro | Fitted rule | Where it lives | Facts it reads | Gained / lost |
| --- | --- | --- | --- | --- |
| `V35_R3_XREL` | xfer_abort=word (arbiter.py `_one_word`: room 2 or 3 on a transfer's triple clock) | the loader: on a transfer's start clock (`fmt.xfer`: branch_short / near, dbnz, dbnz_z, call, ret) the displacement take's room is released a clock late (`xl_t`, into `relc`): the byte goes to the bus unit's target adder, not the EU. Model room 3 then shows exactly a word and Q2's abort fires as it stands; the request comes back with the drop window's `dr_xfer` lift | `fmt.xfer`, `t_start`, `t_done`, the take | F23 F30 F35 F39: +273 / −7 (the 7: model room 2, below) |
| `V35_R3_XRW` | xfer_abort=word's room 2 | the queue's `q_word` also up when the line is a byte short of a word by exactly one byte read and not released (`q_short`: `occ == CAP − 1 && unrel_a == 1`); the arbiter's `abort_tri` takes it with the line down; the take sync counts the triple clock's aborted cycle as asked (`asked_t`, as the model's abort counts for the sync) | `unrel_a`, `phys_ok`, `susp`; `g_abort_b`, `t_start_b` | with XREL: +273 / 0 on the four; corpus XREL + XRW +474 / 0 (F40 98, F39 96, F35 90, F37 60, F30 57, F34 43, F23 30) |
| `V35_R3_DREL` | latch_disp (queue.room: the delivered word's latched byte counted on the displacement's take clock) | the loader: a memory form's displacement (last byte, the sequencer's `disp_t`) taken on a word's delivery clock together with the IR load is released a clock late: the IR load still owns the write port (the second byte latched, uncounted), the displacement's byte counts: one byte less room, as the model's | `disp_t`, `dlv`, `l_pop`, `t_done` | F4 F6 F7 F20 F21 F22 F26: +167 / 0; corpus +171 / 0 (F21 150, F4 9, F26 8, F29 4) |
| `V35_R3_LEAR` | lea_room=ir (queue.room) | the loader's `stg`: while LDEA runs its EA clocks after its last operand byte (the sequencer's existing `lrc` window, `lea_xk_t`, unused since Q1) the IR's opcode is no slot taken | `lea_room_t` (new loader input from the sequencer) | F21 F25 F26: +29 / 0 |
| `V35_R3_MATE` | modrm_mate=imm (queue.room: the ModR/M byte's word not free on its delivery clock) | the loader's `stg`: on a word's delivery clock a register form's first immediate byte, the odd word-mate of its ModR/M byte, taken with operand bytes to come: the staging byte stays counted | `mate_t` (the sequencer's take: `!fmt.mem`, ModR/M, page 0, `taken == 1`, one byte, `head_odd`, `arrived_now`, bytes to come) | F3 F4 F10 F14 F19 F20: +24 / 0 |
| `V35_R3_ALAT` | abort_latched=any (arbiter.py `latched_abort`) | `q_short`'s second term: the line a byte short of a word by a byte latched on an earlier clock (`lat`, no delivery now) is room for the abort test only; the abort and the sync as XRW's | `lat_v`, `arrive`, `susp` | F3 F9 F14 F16 F20 F21: +38 / 0; corpus +38 / 0 (F20 21, F21 12, F16 5) |

Corpus, cumulative in the order of the table (against 8d0547e's per-run set; no run lost at any step but
XREL alone's 7, which XRW wins back; no family below 8d0547e at any step): XREL alone 28,073 (+474 / −7: the 7 the room-2 aborts, F35 6, F30 1); + XRW 28,080 (the 7 back: +474 / 0 against 8d0547e); + DREL 28,251 (+171 / 0); + LEAR + MATE
28,370 (+128 / 0: F25 29, F30 28, F39 27, F20 11, F35 9, F19 8, F6 6, F3 3, F10 2, F12 2, F29 2, F33 1); + ALAT **28,408** (+811 / 0 against 27,606: F21 162, F39 123, F35 99, F40 98, F30 85, F37 60,
F34 43, F20 32, F23 30, F25 29, F4 9, F19 8, F26 8, F6 6, F29 6, F16 5, F3 3, F10 2, F12 2, F33 1).

**The transfer's displacement** (xfer_abort=word). The model's "room 2 or 3" is one byte: the transfer's
displacement goes to the bus unit's target adder, so its slot is released a clock after the take. On the
start clock with the late byte, model room 3 is the RTL's exactly-a-word (Q2's abort as it stands), model
room 4 (pE in F23-push-br: 4 bytes of room) still fetches on both (F23-push-br-n0-pE-w0 exact before and
after, -pO-w0 gained), and model room 2 is the line down a byte short, which only XRW's `q_short` catches
(F30-store-br-short-n0-nop-pO-w0 t+85, F35-out-loop-dbnz-nop-pO-w0 t+96: the 7 XREL loses; without the
take sync's count of that abort, 3 of them still differ: the EU's take sync ran two clocks early). Late
release on every take of a transfer (not only the start clock): +273 / −117 (F39 50, F35 34, F30 25, F23
8): the displacement byte of a later take is the EU's like any operand byte.

**Release timing at the take (the brief's next three shapes): not one rule.** The F21 d8 shape is
latch_disp (DREL); the F19 / F10 shapes are two different things; F11 is the physical check:
- *d8 displacement + IR load on a delivery clock* (171 at 8d0547e, F21 150 recovered by DREL): the model
  counts the latched byte on the displacement's take clock. Released late on every delivery-clock
  displacement take (DREL=2): +167 / −165 (F22 add_d8 106, F21 sti 56: a displacement with an immediate
  after it, where the release is the take's only one; the port then goes to the latched byte, which is
  counted, and the late byte is counted too: two bytes where the model has one). With the IR load on the
  clock the port stays the EU's and the count is the model's: kept.
- *a take on an immediate form with the model's line down at room 2* (162: F35 51, F30 30, F19 24, F20 18,
  F6 18; F19-d-out-adddwi-outb-pE-w0 t+87, F30-out-str-outm-w-n1-d4-pE-w2 t+89): not a count. The rooms are
  equal (qdbg occ 5, model room 2); the model's request flag (request_eval=on_change) is down because the
  room rose on a P-pass take whose removal the model records after that clock's sample, and no later
  change re-evaluates it until the take step ends. Built as a release rule (the P pass's released bytes
  reach the room only at the queue's next tick-A change, `relc` held): +42 / −168 on F3 F6 F19 F20 F30
  F35 (F20 63, F3 51, F30 30, F19 24 lost): rejected. It needs the line to keep a "not re-evaluated" state
  (a request sample the queue does not have): (c), or a sampling rule for the bus unit (b).
- *a register form's start + take with the model's line up, the RTL's down* (161: F20 112, F3 15, F12 10,
  F11 8; F11-none-n2-movr-pE-w1 t+80, F20-r-push-n1-pfxmovr-outdw-pO-w2 t+93): the RTL's physical check
  (`phys_ok`: six stored and latched, a word delivering) holds the line where the model, which has no
  physical bound, fetches. Counting the empty IR as a physical place: +12 / −35 on F9 F11 F12 F16 F25 F33
  with 4 runs hanging (F16 pop_bw_d8: the queue overflows): rejected, (c): a phys_ok the model does not
  have, needing the decoder's IR load ahead of the delivery.
- *LDEA* (85 at 8d0547e; LEAR recovers 29) and *the OUT DW / immediate forms' take* (55; MATE recovers the
  word-mate cases) are the seventh slot's per-form refinements (lea_room, modrm_mate) that Q1 dropped.

**abort_latched**: kept (ALAT, +38 / 0, no family lower).

**The classification** (classify2's reading, the hand-back's r3-misses-0 / r3-misses-1; at 8d0547e it gives
(a) 762, (b) 635, (c) 1,368: R2's r2-misses-1c listed 52 more as (c), runs classify.py had called "line
differs" where the model's line before its own fetch is up as the RTL's is: classify2 calls them (b)):

| Family | runs | fit 62 | 8d0547e exact | (a) | (b) | (c) | R3 exact | (a) | (b) | (c) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F0 | 18 | 18 | 18 | 0 | 0 | 0 | 18 | 0 | 0 | 0 |
| F0w | 20 | 20 | 20 | 0 | 0 | 0 | 20 | 0 | 0 | 0 |
| F1 | 54 | 54 | 54 | 0 | 0 | 0 | 54 | 0 | 0 | 0 |
| F2 | 120 | 120 | 120 | 0 | 0 | 0 | 120 | 0 | 0 | 0 |
| F3 | 840 | 840 | 801 | 12 | 0 | 27 | 804 | 12 | 0 | 24 |
| F4 | 456 | 456 | 443 | 0 | 0 | 13 | 452 | 0 | 0 | 4 |
| F5 | 840 | 840 | 827 | 4 | 0 | 9 | 827 | 4 | 0 | 9 |
| F6 | 576 | 576 | 552 | 0 | 0 | 24 | 558 | 0 | 0 | 18 |
| F7 | 432 | 432 | 430 | 2 | 0 | 0 | 430 | 2 | 0 | 0 |
| F9 | 408 | 408 | 379 | 0 | 25 | 4 | 379 | 0 | 25 | 4 |
| F10 | 204 | 204 | 198 | 4 | 0 | 2 | 200 | 4 | 0 | 0 |
| F11 | 132 | 132 | 124 | 0 | 0 | 8 | 124 | 0 | 0 | 8 |
| F12 | 204 | 204 | 186 | 6 | 0 | 12 | 188 | 6 | 0 | 10 |
| F14 | 732 | 732 | 713 | 7 | 3 | 9 | 713 | 7 | 3 | 9 |
| F15 | 840 | 840 | 825 | 12 | 3 | 0 | 825 | 12 | 3 | 0 |
| F16 | 1014 | 1014 | 965 | 24 | 25 | 0 | 970 | 24 | 20 | 0 |
| F19 | 1290 | 1290 | 1224 | 20 | 14 | 32 | 1232 | 20 | 14 | 24 |
| F20 | 3594 | 3594 | 3420 | 12 | 21 | 141 | 3452 | 12 | 0 | 130 |
| F21 | 3576 | 3576 | 3384 | 12 | 14 | 166 | 3546 | 12 | 2 | 16 |
| F22 | 1320 | 1314 | 1244 | 30 | 40 | 0 | 1244 | 30 | 40 | 0 |
| F23 | 360 | 360 | 315 | 0 | 9 | 36 | 345 | 6 | 9 | 0 |
| F24 | 912 | 902 | 902 | 0 | 0 | 0 | 902 | 0 | 0 | 0 |
| F25 | 588 | 577 | 520 | 10 | 0 | 47 | 549 | 12 | 0 | 16 |
| F26 | 906 | 906 | 843 | 38 | 8 | 17 | 851 | 38 | 8 | 9 |
| F29 | 456 | 427 | 334 | 14 | 66 | 13 | 340 | 14 | 66 | 7 |
| F30 | 1476 | 1467 | 1230 | 88 | 21 | 128 | 1315 | 88 | 30 | 34 |
| F31 | 234 | 234 | 234 | 0 | 0 | 0 | 234 | 0 | 0 | 0 |
| F32 | 858 | 846 | 660 | 124 | 62 | 0 | 660 | 124 | 62 | 0 |
| F33 | 1050 | 1026 | 945 | 2 | 0 | 79 | 946 | 2 | 0 | 78 |
| F34 | 1596 | 1547 | 1169 | 189 | 92 | 97 | 1212 | 228 | 92 | 15 |
| F35 | 1044 | 1038 | 792 | 18 | 72 | 156 | 891 | 18 | 72 | 57 |
| F36 | 750 | 750 | 744 | 0 | 3 | 3 | 744 | 0 | 3 | 3 |
| F37 | 432 | 432 | 288 | 0 | 66 | 78 | 348 | 18 | 66 | 0 |
| F38 | 864 | 864 | 864 | 0 | 0 | 0 | 864 | 0 | 0 | 0 |
| F39 | 1320 | 1318 | 1053 | 69 | 65 | 131 | 1176 | 75 | 65 | 2 |
| F40 | 1020 | 1003 | 776 | 65 | 26 | 136 | 874 | 65 | 44 | 20 |
| all | 30536 | 30361 | 27596 | 762 | 635 | 1368 | 28407 | 833 | 624 | 497 |

The (c) left (497): 162 the on_change flag (above), 161 the physical check (above), 36 + 33 + 21 + 31 the
model idle with its line down at room 1–2 where the RTL's is up and no EU event (F14-g-out-mulu_bw-pO-w0
t+96, F33-out-adj4a-k1-pE-w0 t+87, F21-push-l0-ld-bw_ix_d16-pE-w0 t+84: the same on_change flag, not
examined further), 18 + 13 F33 inc_al starts (phys_ok), 10 F35 far call takes, 12 F34 bit-memory forms.
The (a) count rose by 71 (762 → 833): runs whose first divergence moved past a recovered (c) clock to an EU
event (F34 39, F37 18, F23 6, F39 6, F25 2).

**Gates.** `verilator --lint-only -Wall` clean in the four configurations, with `-DV35_QUEUE_A` (four) and
with the six R3 macros 0; the macros at 0 reproduce 8d0547e run for run (F10 F16 F20 F21 F23 F25 F35, 10,380 runs, every per-run line identical); `test_v35_struct`, `test_ucgen`, `test_chain_lane`, `test_sst_rtl`,
`test_rtl_vectors` OK (ucgen untouched: no row or decode attribute changed); `sst.py --rtl --all` 2,849,080
pass; `--regfile` F0..F33 69,099 and F34–F40 38,760 vectors 0 bad; `--fn` over the 28-family list 19,752
vectors 0 bad; the whole refresh-off corpus identical run for run at `+v35_chk` and `+v35_ticks=2 +v35_chk`,
chk silent, `--diag` silent, no run failing, write data 106,824 / 106,824.
Timing guidance: one new loader register (`xl_t_b`, the ce_b copy of the late byte, ce_a into the existing
`relc`; `+v35_chk` silent); `q_short` is one comparator (occ == CAP − 1) beside q_word's existing one, ANDed
with registered state (`lat`) and the counts the line already forms; the arbiter's abort gains an OR term;
the loader's `stg` gains two AND terms on the sequencer's tick-A strobes (`lea_room_t`, `mate_t`, both
from existing take logic and the existing `lrc` register).

### R4: the remaining EU misses (class (a)) and the bus-unit holds (class (b))

The (a) misses at 08a2c58 (833) re-read against the frozen model instrumented at the first divergent clock
(the hand-back's an/req.py: the model's request record per clock; an/why_start.py: the line of `EU._start`
that held a start; an/setlog.py: every assignment of an EU attribute with its clock and source line). Ten
rules are built, each behind a macro in v35_front_pkg.sv (1: built; 0: the 08a2c58 core). None touches
v35_queue.sv; no input names a form, class, row or EU step to the queue or the bus unit; no request is dated.
Most are the fitted rule the Q1 rebuild approximated with a plain bus fact where the model reads a slightly
different one (the request record's post sample instead of none, the fetch's issue instead of its last
clock, the delivery clock's latched byte).

| Macro | Fitted rule | Where it lives | Facts it reads | Alone (its families) | Corpus step |
| --- | --- | --- | --- | --- | --- |
| `V35_R4_PTHRU` | page_cl=thru's order (arbiter.py _choose: `requested_at > req.posted`) | the arbiter's `pth_cand` | the record's post sample `lup_p` | F32 F34 F39 F40: +250 / 0 (F32 116, F34 74, F39 30, F40 30) | with NMB: +340 / 0 |
| `V35_R4_NMB` | request_reissue=no_mem at the issue (queue.issue's `mem_waiting`) | the arbiter's new output `b2b_hold_o` (the bus unit's back-to-back sample held only by a memory request that waited at the fetch's issue, queue unchanged since); free_run's `!b2b_now` exempts such a commitment (`nmb`) | `nm`, `fetch_end_prev`, `take_now`, `l_pop`, `mem_wait_o`; `nmb` (1 bit) | F5 F19 F21 F22 F26 F29 F39 F40: +90 / 0 (F22 30, F26 28, F21 14, F29 10, F5 4, F19 4) | (above) |
| `V35_R4_IOST` | io_b2b's `stored() < io_b2b_q` (the delivered word's latched byte not stored) | the start gate's io_b2b term: threshold + 1 on a delivery clock | `stored_c`, `b2b_now`, `fetch_end_prev` | +44 / 0 (F30 16, F25 10, F3 4, F20 4, F7 2, F14 2, F15 2, F34 2, F40 2) | +44 / 0 |
| `V35_R4_CLAT` | count_latch's room (eu.py: `room - (latched if need == 0)`) | the sequencer's `shift_latch` | `stored_l`, `need_l`, `arrived_now`, `inflight_c` | F12 F14 F15 F16 F30 F34: +98 / 0 | with SRZ: +119 / 0 |
| `V35_R4_SRZ` | str_raise (str_fetch=hold, CW = 0: queue.str_raise) | the drop window's end: the REL_RAISE row's countdown (`rz_v`, `rz_cnt`) | `rs_set`, `rs_n` (existing row attribute, unread since S5a) | F30: +21 / 0 | (above) |
| `V35_R4_DASK` | imm_landed's deferred sync (`completed + inflight + asked` on the clock after the take) | the take sync's owed count in tick B | `asked_p` (the line, `fetch_req_b`) | +50 / 0 (F19 16, F35 10, F20 8, F10 4, F12 4, F29 4, F3 2, F33 2) | with LAPS: +172 / 0 |
| `V35_R4_LAPS` | the take sync's lapse (`room(t) < 2`, the latched byte uncounted on its delivery clock) | `t_lapse` | `room_c`, `arrived_now` | F32 F34 F39: +120 / 0 (F34 67, F39 45, F32 8) | (above) |
| `V35_R4_DRX` | xfer_abort=word's retry for TRANSFERS by base class | the drop window's `dr_xfer` | the format's `xfer` bit | F37: +18 / 0 | with XNT + GIOD: +125 / 0 |
| `V35_R4_XNT` | xfer_nt=odd's decide (eu.py decide: only fetches started before `odd_until`) | the decide row's `dec_inf` / `dec_since` (`xo`, `xo_s`) | `ox_nt`, `ou_v`, `ou_cnt`, `g_fetch_b`, `fetch_since` | F23 F30 F35: +24 / 0 (F30 18, F23 6) | (above) |
| `V35_R4_GIOD` | grp_io_hold's dating (`requested_at = t` when the hold ends) | the arbiter's `fetch_first` | the record's `ghp`, `gio_hold`, `fw0` | F14 F15: +6 / 0 | (above) |

Corpus, cumulative in the order of the table (each step against the previous step's per-run set; no run lost
at any step, no family below 08a2c58): PTHRU + NMB 28,748 (+340), + IOST 28,792 (+44), + CLAT + SRZ 28,911
(+119), + DASK + LAPS 29,083 (+172), + DRX + XNT + GIOD **29,208** (+125): +800 / −0 against 28,408 (F34 216,
F32 124, F30 88, F39 75, F26 46, F40 46, F22 30, F16 20, F19 20, F35 18, F37 18, F21 14, F29 14, F15 12,
F20 12, F25 10, F14 7, F3 6, F12 6, F23 6, F5 4, F10 4, F7 2, F33 2). The rules alone sum to +721; the
other 79 (F34 39, F26 18, F40 12, F35 8, F30 2) need two of them together (they were gained at the last step)..

**The `I` shape** (350 at 08a2c58): two rules, neither a setup count. *page_cl=thru's order* (228 + 6, F32 F34
F39 F40): the model lets a fetch run inside a CL-index 0F read's CL clocks only when it was requested after
the read's post (`queue.requested_at > req.posted`); a request standing at the post is an ordinary fetch that
restarts the read's fetch-free count (Request.page_free). Q1 left the order out ("undated"), so the RTL ran
the standing fetch thru and issued the read 2 clocks early (F32-out-test1_mb_cl-k1-pE-w0: post +85, fetch
+87, model read +95, RTL +93). The record's post sample `lup_p` (the line up at the post and standing since,
R1/Q1's bit) is exactly "requested no later than the post": PTHRU = `pth_cand && !lup_p`. *request_reissue=
no_mem at the issue* (F22 F21 F19 F26 F29 F5 stores, F39 F40 transfers: model fetch, RTL write): the model
leaves the flag down after a fetch issued *while* a memory request waits (queue.issue's mem_waiting); Q1's
bus unit instead withheld its back-to-back sample whenever a memory request waited at the fetch's last clock,
so a write posted during the flight beat the fetch the model commits back to back (F22-none-l0-sti_d16-k2-
pE-w1 t+92). NMB: the waiting request holds the sample only when it already waited at the issue and the
queue has not changed since (the arbiter's existing `nm`, a new output `b2b_hold_o`); free_run's
"not standing since the last clock" (`!b2b_now`) does not count a commitment NMB let through (`nmb`, one
register: 13 F29 / F40 runs lost without it, the group / stack request's fetch-free clocks counting through
the committed fetch as the model's undated request does).

**The start holds** (269 at 08a2c58): the counts before the start are equal on every example examined (R1's
"counts differ" reading came from the RTL's trace field after its own start); three EU rules on bus facts
and one row attribute: *io_b2b's shallow queue* (IOST): the model's `stored()` excludes the delivered word's
second byte on its delivery clock (word_latch=byte_d: in the write-port latch for the clock) and io_b2b's
clock is always a delivery clock (a back-to-back fetch follows the fetch that ended on t-1); *imm_landed's
deferred count* (DASK): the RTL's deferred take sync counted only the fetch in flight (`asked_d` tied 0);
the model counts `queue.asked` on the clock after the take, which is the line (`fetch_req_b`, tick A's end,
before the grant) — F10-push-adddwi-outdw-pE-w1, F14-o-out-movr2-pE-w1, F19 / F20 OUT forms behind
ADD DW,imm16; *the take sync's lapse* (LAPS): on a delivery clock the RTL's room counted the arriving
second byte and lapsed the sync of a 0F register bit op one fetch early (F34-out-rbit-set1_rb_cl-nop-k1-
pO-w0, F39-push-page-set1-movr-pO-w0: the "start a clock early after a 0F register bit form"); *xfer_nt=
odd's decide* (XNT): a not-taken transfer's test waits only for the fetches issued before its odd hold's
lift (`odd_until`), not for the one its release raised (F23-out-bne-n0-k2-pO-w0, F30-out-nt-bne-*-pO);
the decide row read the plain bus facts (`fetch_inflight`, `fetch_since`). *xfer_abort=word's retry*
(DRX): BRK is a call by base class (the format's `xfer` bit, which XREL already uses) and its aborted
start's request comes back at the aborted cycle's end (F37-out-brk-brk5-pE-w0). *grp_io_hold's dating*
(GIOD, F14 / F15 test_dir_aw): the fetch grp_io_hold held dates from the clock the hold ends and goes
before a group read that became issuable there (as R1's FHDATE for free_hold; the record's existing `ghp`).

**The `susp` shape** (137): not the latched byte. *count_latch's room* (CLAT, 98 alone: F16 F12 F14 F15 shifts,
F30 / F34 string and bit forms' SHL by an immediate): the model's room for the rule subtracts the delivered
word's latched byte only when the form has taken its last operand byte (`room - (latched if need == 0)`);
the RTL counted it always. The loader's `need_l` (after T) carries the condition; R3's `lat_v` is not
needed. *str_raise* (SRZ, 21 alone: F30 str_inm / outm / stm CW = 0 after a NOP): the REL_RAISE row (the row
attribute already in the ROM, unread since S5a) ends the aborted start's drop window `rs_n` clocks into
the exit (a 4-bit countdown `rz_cnt`), where the model raises the request again.

**Not recovered (recorded):**
- *latch_start* (22 (a): F40 movdl / addi8 k4 12, F3 mov_cl_imm k4 6, F16 movcl 4): F16-s-none-n2-movcl-pE-w1
  t+87, F3-push-mov_cl_imm-k4-pO-w0 t+100: the form starts on the clock a byte latched behind a full queue
  goes into the queue, so its first EU clocks run a clock later (eu.py latch_start; the sequencer's
  `latch_start_now` is tied 0). Needs the queue's latch draining on this clock (`lat_v` and the room it
  goes into): a queue fact not exported. (c).
- *the one-shot commitments* (332 (b): xfer_nt_b2b=decide 297, F35 cc 72, F34 rbit 81, F30 nt 30, F39 ..., and
  page_b2b=reg 35 more): F23-out-bne-n0-k1-pE-w0 t+93, F32-out-test1_rb_imm-k2-pE-w0 t+99. At a fetch's last
  clock the model commits back to back with room >= 1 (line down), nothing latched, the word able to fit.
  Needs the queue's free count >= 1 (exported only as >= 2 / == 2 / q_short) and `lat_v`; xfer_nt_b2b
  also the DECIDE row's strobe (`ntb_ok`), an EU-step input to the bus unit the rules forbid. A one-bit
  sample does not give it: "line up and not exactly a word at the issue" implies room >= 1 at the last
  clock but misses a byte released in the flight (R2's line-or-q_low form stalled 706 runs). (c).
- *grp_disp=hold's take clock, the room after the reads* (138 (b), F29 F37 F39 F40): F29-out-ec-gih-incd16-
  n1-pO-w0 t+92 (room 3 after the reads: hold) against -pE-w0 t+91 (room 4: fetch), every other fact equal
  (R2's finding stands). Needs the room after this clock's reads. (c).
- *grp_disp=hold's read, the fetch no older than it* (36 (b), F29 gih-*-n0): F29-out-ec-gih-incd16-n0-pE-w0
  t+87, F29-out-ec-gih-dw-incd16-n0-pO-w0 t+95: the model lets a fetch requested before the read's post go.
  Candidate measured, NOT in the patch: `gr_hold && !lup_p` (GRLP): F5 F29 F32 F34 F36 F37 F38 F39 F40 +30 / −30
  (gains the F29 n0 -pE runs; loses the F29 n0 pO runs, RTL fetch at +88 against
  silicon +91: their request was raised on the post clock itself, which `lup_p` (sampled after the clock's
  reads) counts as standing, while the model's `requested_at >= posted` holds it). Needs the post sample
  taken before the clock's reads (`lup` instead of the line); not measured.
- *latch_hold* (102 (b), F22 40, F9 25, F16 20, F15): F15-a-none-test_bw_imm-pE-w0 t+95, -pE-w1 t+99: no fetch
  while a byte delivered on an earlier clock is still latched and the decoder holds the port. Needs `lat_v`
  (with `!arrive`) at the arbiter: a queue output the strategy reserves. (c).
- *grp_io_hold's order* (6 (b), F14-g-out-shl_bw_cl-pE-w0/w1/w2 t+87): the model holds only a fetch requested
  on or after the I/O's issue. Candidate measured, NOT in the patch: `iol` (the line stood at the clock before
  the I/O issue and since: a one-bit sample set from `lup` at the I/O issue, cleared as `lup_p`), `gio_hold &&
  !iol` (IOL): F5 F9 F14 F15 F19 F22 F26 F29 F36 F37 +12 / 0 (F29 6, F14 3, F36 3) on top of the ten rules; not
  measured on the corpus or at the second spacing, so left out.
- *small (a) left* (10): F34-out-mbit-set1_mw_cl_bw_d16-d-k1-pE-w0 t+103 / -dir-d-k1 (6: the 0F memory read a
  clock later in the RTL), F34-out-mbit-set1_mw_cl_bw_d8-nop-k1-pE-w1 t+96 (2), F25-out-ldea-bw_ix-k2-pE-w1 t+92
  (2: the RTL's aborted cycle where the model fetches). Open, not examined.
- (b) also 8 F32 set1_mw_cl d16 (R2's page_run beside the 0F read) and 2 F34 mbit: as R2 recorded.

**Gates.** `verilator --lint-only -Wall` clean in the four configurations, with `-DV35_QUEUE_A` (four) and with the
ten R4 macros 0; the macros at 0 reproduce 08a2c58 run for run (F14 F19 F22 F23 F26 F30 F32 F34 F37, 8,970
runs, every per-run line identical); `test_v35_struct`, `test_ucgen` (ucgen untouched: no row or decode
attribute changed), `test_chain_lane`, `test_sst_rtl`, `test_rtl_vectors` OK; `sst.py --rtl --all` 2,849,080
pass; `--regfile` F0..F33 69,099 and F34–F40 38,760 vectors 0 bad; `--fn` over the 28-family list 19,752
vectors 0 bad; the whole refresh-off corpus 29,208 RTL-exact, identical run for run at `+v35_chk` and
`+v35_ticks=2 +v35_chk`, chk silent, `--diag` silent, no run failing, write data 106,824 / 106,824.
The classification at the end (classify2's reading; the hand-back's r4-misses-0 / r4-misses-1): (a) 833 → 32,
(b) 624 → 624 (the composition moved: F21 / F26 down 10, F34 / F40 up 10 from runs whose first divergence
moved past a recovered (a) clock), (c) 497 → 498.

| Family | runs | fit 62 | 08a2c58 exact | (a) | (b) | (c) | R4 exact | (a) | (b) | (c) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F0 | 18 | 18 | 18 | 0 | 0 | 0 | 18 | 0 | 0 | 0 |
| F0w | 20 | 20 | 20 | 0 | 0 | 0 | 20 | 0 | 0 | 0 |
| F1 | 54 | 54 | 54 | 0 | 0 | 0 | 54 | 0 | 0 | 0 |
| F2 | 120 | 120 | 120 | 0 | 0 | 0 | 120 | 0 | 0 | 0 |
| F3 | 840 | 840 | 804 | 12 | 0 | 24 | 810 | 6 | 0 | 24 |
| F4 | 456 | 456 | 452 | 0 | 0 | 4 | 452 | 0 | 0 | 4 |
| F5 | 840 | 840 | 827 | 4 | 0 | 9 | 831 | 0 | 0 | 9 |
| F6 | 576 | 576 | 558 | 0 | 0 | 18 | 558 | 0 | 0 | 18 |
| F7 | 432 | 432 | 430 | 2 | 0 | 0 | 432 | 0 | 0 | 0 |
| F9 | 408 | 408 | 379 | 0 | 25 | 4 | 379 | 0 | 25 | 4 |
| F10 | 204 | 204 | 200 | 4 | 0 | 0 | 204 | 0 | 0 | 0 |
| F11 | 132 | 132 | 124 | 0 | 0 | 8 | 124 | 0 | 0 | 8 |
| F12 | 204 | 204 | 188 | 6 | 0 | 10 | 194 | 0 | 0 | 10 |
| F14 | 732 | 732 | 713 | 7 | 3 | 9 | 720 | 0 | 3 | 9 |
| F15 | 840 | 840 | 825 | 12 | 3 | 0 | 837 | 0 | 3 | 0 |
| F16 | 1014 | 1014 | 970 | 24 | 20 | 0 | 990 | 4 | 20 | 0 |
| F19 | 1290 | 1290 | 1232 | 20 | 14 | 24 | 1252 | 0 | 14 | 24 |
| F20 | 3594 | 3594 | 3452 | 12 | 0 | 130 | 3464 | 0 | 0 | 130 |
| F21 | 3576 | 3576 | 3546 | 12 | 2 | 16 | 3560 | 0 | 0 | 16 |
| F22 | 1320 | 1314 | 1244 | 30 | 40 | 0 | 1274 | 0 | 40 | 0 |
| F23 | 360 | 360 | 345 | 6 | 9 | 0 | 351 | 0 | 9 | 0 |
| F24 | 912 | 902 | 902 | 0 | 0 | 0 | 902 | 0 | 0 | 0 |
| F25 | 588 | 577 | 549 | 12 | 0 | 16 | 559 | 2 | 0 | 16 |
| F26 | 906 | 906 | 851 | 38 | 8 | 9 | 897 | 0 | 0 | 9 |
| F29 | 456 | 427 | 340 | 14 | 66 | 7 | 354 | 0 | 66 | 7 |
| F30 | 1476 | 1467 | 1315 | 88 | 30 | 34 | 1403 | 0 | 30 | 34 |
| F31 | 234 | 234 | 234 | 0 | 0 | 0 | 234 | 0 | 0 | 0 |
| F32 | 858 | 846 | 660 | 124 | 62 | 0 | 784 | 0 | 62 | 0 |
| F33 | 1050 | 1026 | 946 | 2 | 0 | 78 | 948 | 0 | 0 | 78 |
| F34 | 1596 | 1547 | 1212 | 228 | 92 | 15 | 1428 | 8 | 96 | 15 |
| F35 | 1044 | 1038 | 891 | 18 | 72 | 57 | 909 | 0 | 72 | 57 |
| F36 | 750 | 750 | 744 | 0 | 3 | 3 | 744 | 0 | 3 | 3 |
| F37 | 432 | 432 | 348 | 18 | 66 | 0 | 366 | 0 | 66 | 0 |
| F38 | 864 | 864 | 864 | 0 | 0 | 0 | 864 | 0 | 0 | 0 |
| F39 | 1320 | 1318 | 1176 | 75 | 65 | 2 | 1251 | 0 | 65 | 2 |
| F40 | 1020 | 1003 | 874 | 65 | 44 | 20 | 920 | 12 | 50 | 21 |
| all | 30536 | 30361 | 28407 | 833 | 624 | 497 | 29207 | 32 | 624 | 498 |


Timing guidance: new registers `nmb` (arbiter, ce_b copy `nmb_b`, ce_a), `rz_v` / `rz_cnt` and `xo` / `xo_s`
(the sequencer's windows, ce_a from tick-B facts, read in tick A); the arbiter's choice tree gains an AND
of the record's `lup_p` (PTHRU) and an OR term of the record's `ghp` (GIOD), the bus unit's sample input
an AND of `nm` and three strobes it already had (NMB); the start gate's io_b2b compare takes a constant 3
or 4 on `fetch_end_prev` (IOST); count_latch's and the lapse's sums gain a one-bit term (CLAT, LAPS); the
deferred owed count an increment in tick B (DASK); the decide row a 2:1 mux from registers (XNT). No
comparator against a count is added to the arbiter. `+v35_adbg=FILE` (the arbiter's slot and choice) and
`+v35_sdbg=FILE` (the take sync and the suspend windows) are bring-up prints under `ifndef SYNTHESIS`.

### A1: the arbiter removed; the bus unit's grant over an EU request port

docs/v35s-arbiter-strategy.md. `v35_arbiter.sv` (904 lines, 108 ports, three request positions of a 130-bit
record, a 39-level choice tree) is deleted. The bus unit grants its own cycles from two request ports, the
queue's and the EU's; everything that names the operation (the setup counts and their counting modes, the
fetch-free tails, the I/O lead, the floors, the holds, the detached I/O, the request positions) is the
sequencer's, in its section "the EU's bus interface" (v35_ucode.sv). No signal crossing into v35_bus.sv or
v35_queue.sv carries a class, format, row, step, count mode or kind of instruction (test_v35_struct's
`Ports` tests: the bus unit's inputs are its clocking, the EU request port, the queue's port and the three
read strobes of the aborted fetch; no port name or type names an instruction; the old bus unit fails the
test on 8 ports).

**The EU request port** (v35_bus.sv), exactly the strategy's nine signals:

| Signal | Dir | Width | Meaning |
| --- | --- | --- | --- |
| `req_v` | EU → bus | 1 | the slot's request is issuable (a level, until `req_ack`) |
| `req_cyc` | EU → bus | 2 | RQ_MEMR, RQ_MEMW, RQ_IOR, RQ_IOW (an empty slot presents RQ_MEMR) |
| `req_addr` | EU → bus | 20 | the cycle's address; after `req_ack` of an odd memory word, its second half's (offset + 1 in the segment, the EU's) |
| `req_width` | EU → bus | 1 | a word (at an odd memory address: the bus unit's pair, hi then lo) |
| `req_data` | EU → bus | 16 | a write's datum, taken at mid-B2 (the EU holds the issued datum in `bq_b2d_b`, or presents the late result / immediate `wd_imm`); the bus unit places the pair's bytes |
| `req_resv` | EU → bus | 1 | the reservation |
| `req_ack` | bus → EU | 1 | the request's first cycle issued now |
| `req_done` | bus → EU | 1 | its last cycle ended on t-1 |
| `done_data` | bus → EU | 16 | the read datum |

The bus unit's other inputs: `fetch_req`, `q_low`, `q_word`, `fetch_addr` (the queue) and `t_start`,
`take_now`, `l_pop` (Q2's aborted fetch only). Its status outputs (S0) are as before less the EU-state
flags; the grant's outputs `g_start/g_kind/g_addr/g_width/g_fetch/g_eu/g_abort/g_b2b`, `b2b_now`.

**The grant** (one priority, evaluated once on a free bus; about four levels of logic on registered facts
and the two request lines, no comparator against a count):

0. the odd pair's second half (`p2_v`); the aborted fetch: Q2's triple clock (`ab_tri`, as built) or a
   back-to-back commitment whose line fell with no EU request standing;
1. the fetch committed back to back: the line up at the last clock of the fetch that just ended, with no
   `req_v` and no `req_resv` standing then (A1_B2BH = 1; at a fetch's last clock the EU's reservation is
   its waiting memory request if it waited at the fetch's issue, the EA clocks running on, and the I/O
   lead's block, a 0F form's waiting read exempt once per form);
2. the EU's request, `req_v` (a memory cycle not within io_recover clocks of an I/O cycle: the turnaround
   is the bus unit's, `io_win`, A1_IOREC = 1);
3. the queue's fetch: `fetch_req && (!req_resv || (q_low && req_cyc is a memory cycle))`: a memory
   cycle's reservation yields to a starved queue, an I/O cycle's is absolute (A1_IOQL = 1);
4. nothing.

Rules 1 and 3 are the coordinator's decision after the step-2 measurement (below): the strategy's first
wording (rule 1 held by `req_v` only, rule 3's `q_low` over any reservation) is A1_B2BH = 0, A1_IOQL = 0,
the step-2 record.

**The EU's bus interface** (v35_ucode.sv; registers ce_a unless noted, tick-B copies `bc0_b`, `bc1_b`, ...
at ce_b, checked by `+v35_chk`): `bq0` (the request register: the cycle as the datapath builds it, `req_t`,
and the row's counts: setup 7, fn 7, fo 7, lead 2, through 7, the count mode bits, the floor `nb` 4, the
state bits iss / h2 / two / dne / nwd / dn / fhold / rs / lift / fhp / ghp / moved / dwm / shl / sok / sat
/ lup_p), `bq1` (the entry behind it: the write buffer's other half; a request posted behind a detached
I/O counts from the clock that I/O issues), `bq_own` 2, `bq_os` (the cycle on the bus started on a form's
start clock: io_exec, page_mtake), `bq_wl` 3 (the data latch, moved from the bus unit), `bq_th`, `bq_pa`,
`bq_fas`, `bq_fnt` (the 0F page's views of the fetch on the bus, moved from the bus unit's cycle flags),
`bq_nm` (a memory request waited at the issue of the fetch on the bus: R4's NMB), `bq_b2l_b` / `bq_b2d_b`
(ce_b: the B2 datum). `req_v` = the slot's request pending, its setup counted, its floors past, not the
left-out write; `req_resv` = the setup hold (the setup clocks before the lead, the I/O recovery, a fetch-
holding floor; R1's need lapse for a memory request) OR the windows (wb_hold, latch_wait, gdisp_act, and
the recovered rules' holds); at a fetch's last clock (no fetch can start then) it is the waiting memory
request (if it waited at that fetch's issue) or the EA clocks running on (ea_b2b), which is what rule 1
samples. The left-out write's slot posts no cycle: on its slot clock the reservation is down and a fetch
runs by rule 3 if the line is up; its done_at is the fetch's end or `sidle` clocks on. HALT suspends the
queue's line (`susp`).

**Step 2: the strategy's literal grant** (rule 1 held by `req_v` only, rule 3's `q_low` over any
reservation; the EU interface with the plain counts: every clock / nowait / the group forms' pauses /
dw_count, through clocks, the fetch-free tail, the floors, the windows as the reservation, the I/O lead as
the reservation dropped; no recovered rule): **20,943** of 5a43654's 29,207 (−8,264, 28.3 %), 0 failing, chk
silent, write data 106,824 / 106,824. Every miss was classified (`cls_a1.py`, the scratchpad's v2/a1/:
both RTLs re-run, the old arbiter's grant inputs and choice (`+v35_adbg`) against the new bus unit's
(`+v35_gdbg`) and the EU slot (`+v35_bdbg`) at the first divergent clock; the old choice tested against the
four rules with the old clock's line, `q_low` and `b2b` and any `req_v` / `req_resv`): (a) 2,386 (the EU
presented other inputs: v_early 974, resv_down 798, v_late 548, EU items 63), (b) 5,213 (rule 3, `q_low`
over an I/O cycle's reservation that silicon holds absolutely: 4,320 setup hold + 697 I/O lead; rule 1's
sample 196), (c) 665 (wlatch_hold absolute 184 / against a b2b fetch 169, the I/O lead against a b2b fetch
143, the nowrite slot's fetch with the line down 138, free_hold 20, ea_b2b 7, grp_disp 4). This is the
baseline record (the arbiter is gone, so no "macros at 0" build reproduces 5a43654):

| Family | runs | fit 62 | 5a43654 | A1 | lost | gained | loss % | (a) | (b) | (c) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F0 | 18 | 18 | 18 | 18 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| F0w | 20 | 20 | 20 | 20 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| F1 | 54 | 54 | 54 | 28 | 26 | 0 | 48.1 | 18 | 6 | 2 |
| F2 | 120 | 120 | 120 | 118 | 2 | 0 | 1.7 | 0 | 0 | 2 |
| F3 | 840 | 840 | 810 | 789 | 21 | 0 | 2.6 | 0 | 3 | 18 |
| F4 | 456 | 456 | 452 | 223 | 229 | 0 | 50.7 | 6 | 222 | 1 |
| F5 | 840 | 840 | 831 | 354 | 477 | 0 | 57.4 | 50 | 409 | 18 |
| F6 | 576 | 576 | 558 | 456 | 102 | 0 | 18.3 | 16 | 73 | 13 |
| F7 | 432 | 432 | 432 | 190 | 242 | 0 | 56.0 | 12 | 218 | 12 |
| F9 | 408 | 408 | 379 | 379 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| F10 | 204 | 204 | 204 | 146 | 58 | 0 | 28.4 | 20 | 38 | 0 |
| F11 | 132 | 132 | 124 | 124 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| F12 | 204 | 204 | 194 | 181 | 13 | 0 | 6.7 | 0 | 3 | 10 |
| F14 | 732 | 732 | 720 | 516 | 204 | 0 | 28.3 | 4 | 182 | 18 |
| F15 | 840 | 840 | 837 | 605 | 232 | 0 | 27.7 | 29 | 193 | 10 |
| F16 | 1014 | 1014 | 990 | 953 | 37 | 0 | 3.7 | 13 | 17 | 7 |
| F19 | 1290 | 1290 | 1252 | 755 | 497 | 0 | 39.7 | 146 | 280 | 71 |
| F20 | 3594 | 3594 | 3464 | 2611 | 853 | 0 | 24.6 | 306 | 460 | 87 |
| F21 | 3576 | 3576 | 3560 | 2860 | 700 | 0 | 19.7 | 232 | 423 | 45 |
| F22 | 1320 | 1314 | 1274 | 644 | 630 | 0 | 49.5 | 414 | 112 | 104 |
| F23 | 360 | 360 | 351 | 332 | 19 | 0 | 5.4 | 8 | 7 | 4 |
| F24 | 912 | 902 | 902 | 729 | 173 | 0 | 19.2 | 48 | 116 | 9 |
| F25 | 588 | 577 | 559 | 446 | 113 | 0 | 20.2 | 15 | 69 | 29 |
| F26 | 906 | 906 | 897 | 450 | 447 | 0 | 49.8 | 93 | 309 | 45 |
| F29 | 456 | 427 | 354 | 109 | 245 | 0 | 69.2 | 24 | 190 | 31 |
| F30 | 1476 | 1467 | 1403 | 1209 | 194 | 0 | 13.8 | 90 | 69 | 35 |
| F31 | 234 | 234 | 234 | 230 | 4 | 0 | 1.7 | 0 | 3 | 1 |
| F32 | 858 | 846 | 784 | 332 | 452 | 0 | 57.7 | 44 | 407 | 1 |
| F33 | 1050 | 1026 | 948 | 853 | 95 | 0 | 10.0 | 0 | 84 | 11 |
| F34 | 1596 | 1547 | 1428 | 945 | 483 | 0 | 33.8 | 208 | 271 | 4 |
| F35 | 1044 | 1038 | 909 | 853 | 56 | 0 | 6.2 | 20 | 25 | 11 |
| F36 | 750 | 750 | 744 | 553 | 191 | 0 | 25.7 | 12 | 144 | 35 |
| F37 | 432 | 432 | 366 | 8 | 358 | 0 | 97.8 | 354 | 3 | 1 |
| F38 | 864 | 864 | 864 | 541 | 323 | 0 | 37.4 | 0 | 315 | 8 |
| F39 | 1320 | 1318 | 1251 | 699 | 552 | 0 | 44.1 | 144 | 389 | 19 |
| F40 | 1020 | 1003 | 920 | 684 | 236 | 0 | 25.7 | 60 | 173 | 3 |
| all | 30536 | 30361 | 29207 | 20943 | 8264 | 0 | 28.3 | 2386 | 5213 | 665 |

**The steps** (whole corpus at the default spacing, each against the previous step's per-run table):

| Step | RTL-exact (fit 62) | Gained / lost | Notes |
| --- | --- | --- | --- |
| step 2, literal grant | 20,943 | | |
| rule 3: `q_low` over a memory cycle's reservation only (A1_IOQL) | 22,413 | +1,470 / −0 | measured first with an empty slot presenting RQ_IOW: −10 F29 (gih d16 forms: the grp_disp window, a reservation with no request, read as an I/O reservation and held absolutely at the take clock; silicon fetches there): a rule mistake, fixed (an empty slot presents RQ_MEMR) |
| rule 1: the sample held by `req_v` or `req_resv`; at a fetch's last clock the EU reserves for its waiting memory request (R4's NMB: only if it waited at the fetch's issue) and the EA clocks running on (A1_B2BH) | 22,674 | +261 / −0 | measured first as `req_v \|\| req_resv` with the ordinary reservation: −12 F19 (d-out-mov..-inb/inw: an IN's setup hold held the sample, silicon commits the back-to-back fetch past a waiting I/O read), then memory-typed: −994 (an I/O request standing at the last clock must hold), then `req_v \|\| memory reservation`: −32 (F22 sti_d16 / F26 fib bixd16: a store posted during the fetch's flight does not hold the sample, R4's NMB; F29 gih) — fixed by the EU's own last-clock reservation |
| + FFD (the fetch-first dating, imm1_first's exemption) + LEAD (the I/O lead) | 25,242 | +2,568 / −0 | (measured before the last-clock lead hold below) |
| + FRUN + FHOLD | 25,863 | +621 / −0 | |
| + SREG + MFR + PAGE + BCD | 26,662 | +805 / −6 | the 6 (F32 / F34 set1_mw_cl d8, pE) are page_run=field's once-per-form exemption of the b2b sample, added to PAGE (`bq_pru`, R1's PGRUN): with it +1,048 / −0 against the previous step on the 6,800 runs the steps move |
| + SF + RL (port_latch=relatch) | | +1,147 / −0 on those runs | RL first lost 131 (F31 / F5 / F6 out-empty ...: a b2b fetch committed at the fetch's last clock where the old I/O lead's block held it): the lead's block joined the last-clock reservation |
| **the final core** (source defaults) | **28,058** | **+5,384 / −0 against rule 1's step** | both spacings identical |

Each rule alone, on top of rule 1's step (bin t2d), on the 6,517 runs the steps move (gained / lost):
FFD +695 / 0, LEAD +1,849 / 0, FRUN +456 / 0, FHOLD +157 / 0, SREG +48 / 0, MFR +93 / 0, PAGE +483 / 0,
BCD +33 / 0, SF 0 (+36 / 0 with the others), RL 0 (+931 / −131 with the others before the lead fix), GIO 0,
GDR 0 (both left at 0: no effect alone or with the others).

**The recovered rules** (v35_macros.svh, default 1; all in the sequencer's bus interface, on bus facts and
the sequencer's own state; none reaches the bus unit): A1_FFD (_fetch_first's dating: a request that became
issuable on the clock the line rose waits a clock, the fetch first, as do free_hold's / grp_io_hold's dated
fetches; not a one-byte-immediate memory form's first request on a delivery clock off a run, imm1_first),
A1_LEAD (in the I/O lead clocks only a fetch standing since the post goes, on the clock the hold lifts;
dw_slot=behind; the block also holds the back-to-back sample), A1_FRUN (free_run=run, call_far_post's
restart), A1_FHOLD (free_hold=delivery), A1_SF (slot_fetch=slot), A1_SREG (sreg_store=own), A1_RL
(port_latch=relatch, port_issue), A1_MFR (mul_imm_count=sync), A1_PAGE (page_free's restart on a fetch not
committed back to back after the post, run_wait, pthru, ftail, page_imm_run, page_run=field), A1_BCD
(bcd_fetch=hold's setup). Not built: GIO (grp_io_hold), GDR (grp_disp's read hold), disp_io=extend (the bus
unit sees no form), the nowrite slot's slot_room=word, free_idle, request_reissue=no_mem beyond the sample.

**The final core against 5a43654** (both spacings identical, 0 failing, chk silent, write data 106,824 /
106,824): 28,058 (−1,175 / +26; 4.0 %). Over the budget: F22 18.9 %, F29 18.4 %, F37 14.8 %; F19 −109 (8.7 %),
F21 −162 (4.6 %). Per family, with the classification of every miss:

| Family | runs | fit 62 | 5a43654 | A1 | lost | gained | loss % | (a) | (b) | (c) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F0 | 18 | 18 | 18 | 18 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| F0w | 20 | 20 | 20 | 20 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| F1 | 54 | 54 | 54 | 54 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| F2 | 120 | 120 | 120 | 118 | 2 | 0 | 1.7 | 0 | 0 | 2 |
| F3 | 840 | 840 | 810 | 793 | 17 | 0 | 2.1 | 0 | 0 | 17 |
| F4 | 456 | 456 | 452 | 428 | 24 | 0 | 5.3 | 0 | 0 | 24 |
| F5 | 840 | 840 | 831 | 776 | 55 | 0 | 6.6 | 18 | 0 | 37 |
| F6 | 576 | 576 | 558 | 553 | 5 | 0 | 0.9 | 0 | 0 | 5 |
| F7 | 432 | 432 | 432 | 420 | 12 | 0 | 2.8 | 0 | 0 | 12 |
| F9 | 408 | 408 | 379 | 379 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| F10 | 204 | 204 | 204 | 204 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| F11 | 132 | 132 | 124 | 124 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| F12 | 204 | 204 | 194 | 185 | 9 | 0 | 4.6 | 0 | 0 | 9 |
| F14 | 732 | 732 | 720 | 695 | 28 | 3 | 3.9 | 0 | 0 | 28 |
| F15 | 840 | 840 | 837 | 798 | 39 | 0 | 4.7 | 0 | 0 | 39 |
| F16 | 1014 | 1014 | 990 | 981 | 9 | 0 | 0.9 | 0 | 0 | 9 |
| F19 | 1290 | 1290 | 1252 | 1143 | 109 | 0 | 8.7 | 18 | 0 | 91 |
| F20 | 3594 | 3594 | 3464 | 3407 | 57 | 0 | 1.6 | 4 | 0 | 53 |
| F21 | 3576 | 3576 | 3560 | 3398 | 162 | 0 | 4.6 | 20 | 0 | 142 |
| F22 | 1320 | 1314 | 1274 | 1033 | 241 | 0 | 18.9 | 105 | 0 | 136 |
| F23 | 360 | 360 | 351 | 348 | 3 | 0 | 0.9 | 0 | 0 | 3 |
| F24 | 912 | 902 | 902 | 895 | 7 | 0 | 0.8 | 0 | 0 | 7 |
| F25 | 588 | 577 | 559 | 531 | 28 | 0 | 5.0 | 0 | 0 | 28 |
| F26 | 906 | 906 | 897 | 811 | 86 | 0 | 9.6 | 6 | 0 | 80 |
| F29 | 456 | 427 | 354 | 309 | 65 | 20 | 18.4 | 0 | 5 | 60 |
| F30 | 1476 | 1467 | 1403 | 1369 | 34 | 0 | 2.4 | 0 | 0 | 34 |
| F31 | 234 | 234 | 234 | 234 | 0 | 0 | 0.0 | 0 | 0 | 0 |
| F32 | 858 | 846 | 784 | 779 | 5 | 0 | 0.6 | 0 | 3 | 2 |
| F33 | 1050 | 1026 | 948 | 940 | 8 | 0 | 0.8 | 0 | 0 | 8 |
| F34 | 1596 | 1547 | 1428 | 1419 | 9 | 0 | 0.6 | 0 | 3 | 6 |
| F35 | 1044 | 1038 | 909 | 887 | 22 | 0 | 2.4 | 12 | 0 | 10 |
| F36 | 750 | 750 | 744 | 707 | 40 | 3 | 5.4 | 0 | 0 | 40 |
| F37 | 432 | 432 | 366 | 312 | 54 | 0 | 14.8 | 0 | 0 | 54 |
| F38 | 864 | 864 | 864 | 854 | 10 | 0 | 1.2 | 0 | 0 | 10 |
| F39 | 1320 | 1318 | 1251 | 1226 | 25 | 0 | 2.0 | 0 | 0 | 25 |
| F40 | 1020 | 1003 | 920 | 910 | 10 | 0 | 1.1 | 8 | 0 | 2 |
| all | 30536 | 30361 | 29207 | 28058 | 1175 | 26 | 4.0 | 191 | 11 | 973 |

**The recovery agenda** (the final core's 1,175 misses by shape; the classifier's class, then the reading):

| Shape | Runs | Families | Example (t_fill +) | Class | Reading |
| --- | --- | --- | --- | --- | --- |
| a memory-typed window reservation yielding to `q_low` where silicon holds absolutely: wlatch_hold | 254 | F21 57, F22 41, F19 29, F26 21, F30 21, F36 21 | F12-a-out-n0-movr-pE-w0 +87 | (c) → (a) | the window is an I/O form's start waiting for the data latch: the EU can reserve with the cycle type of the I/O it waits to post (req_cyc = IOR / IOW while latch_wait), making it absolute under rule 3 |
| wlatch_hold against a back-to-back fetch | 183 | F20 44, F25 22, F29 16, F30 13, F36 13 | F12-a-out-n1-movr-pE-w0 +91 | (c) → (a) | latch_wait joins the EU's last-clock reservation (rule 1's sample) |
| the left-out write's slot runs a fetch with the line down (slot_room=word) | 180 | F22 72, F19 51, F5 18, F15 15 | F14-t-push-test_bw_imm-pO-w0 +97 | (c) | the bus unit would need "a slot" on the port (an attribute); not built |
| req_v a clock early | 175 | F22 105, F21 20, F5 14, F35 12 | F19-i-push-l0-stimmd8-k2-pE-w0 +100 | (a) | the store's count / floor in the sequencer (imm_count, a floor not set on this path) |
| no fetch on a free clock with the line up and `q_low`, no hold named | 110 | F21 52, F26 24, F4 24 | F21-out-l0-ld-bw_ix_d16-pE-w0 +87 | (c) | disp_io=extend: the I/O issued on a displacement's take clock runs a clock longer (the bus unit's gap clock); the bus would need the take (an attribute) or the EU a cycle-length request |
| grp_disp's window yielding to `q_low` | 106 | F37 54, F29 34, F39 18 | F29-out-ec-gih-incd16-n0-pO-w0 +88 | (b) rule 3 | a memory reservation that silicon holds absolutely; rule 3 lets `q_low` override every memory reservation |
| free_hold / slot_fetch / grp_io_hold yielding to `q_low` | 67 + 42 + 24 | F21, F22, F19 / F15, F5, F14 / F26 | F19-i-push-n1-stimm-pO-w0 +98 | (b) rule 3 | as above (absolute memory-request holds) |
| a start one clock early after an OUT | 16 | F19 8, F20 4, F5 4 | F19-d-out-none-outb-pE-w0 +84 | (a) | the start gate's view of the detached OUT (`slot_det`): the write buffer's I/O issued earlier than the old slot let it |
| rule 1's sample differs | 11 | F29 5, F32 3, F34 3 | F29-out-ec-gih-incd16-n1-pE-w2 +100 | (b) rule 1 | the EU's last-clock reservation for a request posted in the fetch's flight |
| ea_b2b against a back-to-back fetch | 7 | F26 6, F21 1 | F21-push-l0-sti-bw_ix_d16-k2-pO-w0 +95 | (a) | the EA clocks' end seen a clock early at the sample |

**Sizes.** v35_arbiter.sv gone (904 lines, 108 ports). v35_bus.sv 577 lines (703), 69 ports (81): 22
inputs (clocking 8, the EU port 6, the queue 4, the Q2 strobes 3, data_in 1) and 47 outputs (the grant 9,
the EU port's 3, S0 status, the pins). v35_ucode.sv 4,916 lines (4,350), 134 ports (166): the bus
interface adds about 560 lines; 40 arbiter-facing ports went, 22 came (the port, the bus facts it reads,
the datapath's request). v35_queue.sv unchanged (25 ports). The grant is about four levels of logic on
registered facts and the two request lines; the sequencer's new registers are tick-A registers written
from tick-B copies (`bc0_b`, `bq_nm_b`, `bq_pru_b`, ...) checked by `+v35_chk`.

**Gates (the exact final source, its defaults).** Whole refresh-off corpus 28,058 / 30,361 RTL-exact of fit
62's (28,059 of 30,536 in all) at `+v35_chk` and at `+v35_ticks=2 +v35_chk`, per-family `--score` tables
identical and run for run identical, 0 failing, `+v35_chk` silent; `--score --data` 106,824 / 106,824 at
both. `sst.py --rtl --all` 2,849,080 pass (the categories as R4's); `rtl_vectors --regfile` F0..F33
69,099 vectors 0 bad, F34–F40 38,760 0 bad; `--fn` 19,752 0 bad. test_v35_struct (8, with the two
port tests), test_ucgen (12), test_chain_lane, test_sst_rtl, test_rtl_vectors OK; build_core2_tb.sh and
build_rf_tb.sh build (v35_core2_tb.sv reads the bus interface's `bq0 / bq1` and the sequencer's `halted`).
Lint clean in the five configurations (and the QUEUE_A ones). The rule 1 / rule 3 first wordings remain
as macro values for the record (A1_B2BH = 0, A1_IOQL = 0: the step-2 core); GIO and GDR at 0. The
two bring-up prints `+v35_gdbg=FILE` (the grant's inputs and choice per clock) and `+v35_bdbg=FILE` (the
EU slot) replace `+v35_adbg`.

## Divergences (behaviour not expressed in the structure)

(Q1) The queue's divergences from the fit (the features it no longer carries and where they
went, the triple-clock aborts it cannot produce) are listed in "Queue (Q1)" above.

1. **The decode a clock ahead.** The ROM window and the register ports are addressed at the
   clock before a start from the loader's decode of the next form; a start whose decode was not
   known then (its ModR/M byte delivered on the start clock, an IR loaded in L on a P start's
   clock with its byte not stored) waits a clock. None of the S3 gate's starts did.
2. **The start-time oracle decode.** The model decodes the whole form at its start; the RTL's
   start decodes the IR with the queue's head byte as its ModR/M byte and re-decodes the form
   when its ModR/M byte is taken (the template stays the start's). A form started before its
   ModR/M byte arrived runs the template of whatever byte was there (none in the gate).
3. A pass evaluates at most three rows (T) / two after one take (P). Every gate form fits ((S4) the
   T pass's third row in a running form is needed by pop_mem: its read's delivery, its write's
   post and its clocks row on one clock, F21 / F15 / F16).
4. (S5a: closed) The prelude's BR far now runs the real rows: refill_start=full_io (no word in
   flight or wanted, `want_c`; an IN / OUT not on a 3-clock fetch's delivery clock) and
   flush_hold=start (branch_far.hold 16). The pre window stays exact on every gate run.
5. An on-chip SFR store (`MOV [d16],imm` with DS0 F000h) takes its datum from the EU at the
   store cycle's end: store_imm posts its write before it takes its immediate.
6. imm_landed's deferred take sync is counted on the clock after the take with `asked_d` (the
   room before this clock's start), not after a start on that clock as `eu.tick` would.
7. POP PSW loads the flags (PSW[11:0]); MD and RB stay (the chain prelude's POP leaves RB 7, as the
   chain wrapper's init_s has it).
8. Register writes: one a clock; a third write on one clock is dropped (`miss_o`, `+v35_diag`):
   none in the gate.
9. (S4) **Three request positions.** The model's `eu.queued` is a list; the RTL has the slot and
   two queued positions: a post that finds all three taken waits (`W:post`). None in the gate.
10. (S4) **The live address and result.** The running form's own memory request takes its EA and
   its result as it issues, from the datapath's registers (a request posted before its
   displacement was taken, pop_mem's write; an RMW's result registered on its read's delivery
   clock, the post's). The odd-word pair flag the S0 outputs read (`two`) is the address's as it
   stood at the last clock's end. store_imm's write (posted before its immediate is taken) has
   the bus take the immediate at B2: an immediate taken later than that clock would leave the
   datum stale (data only; the cycle's timing is the model's).
11. (S4) The P pass's environment is the T pass's where the model's retick sees a changed one: a
   displacement taken in the P pass does not floor a waiting memory request at once
   (`ep.memw` 0: its floor goes to the next request), dw_port's gate in P reads the positions as
   they stood before the choice, and the request flag's re-evaluation after the P IR load
   (ir_load=disp_data's release) reads the room after the whole P pass. sreg_io=hold's
   `sreg_held` is set by a MOV sreg,r/m reaching the start gate while an OUT's I/O waits (the
   model: decoded, started or held at the interlock). None changes a gate run.
12. (S4) The plan's `alu_busy` is the record's `through` (rmw_alu=through: the RMW write's ALU
   clocks count through a fetch); there is no separate busy signal.
13. (S5a) **The REP prefix's form.** A REP prefix in the IR is decoded with the queue's head
   byte as its string opcode (Divergence 2's way with a ModR/M byte): a REP form started before
   its string byte arrived would run the template of whatever byte was there. No gate run shows
   it (all 25,742 RTL = model).
14. (S5a) **The string unit's registers.** IX and IY (and CW) are flops; the register RAM's
   copies are written through on a clock no other write uses the port (`dcw`, `dix`, `diy`),
   and the datapath reads CW, IX and IY from the flops only. A register-bank switch (out of
   scope) would see a stale RAM copy for a few clocks.
15. (S5a) **A pass's rows.** A skipped row is no row of the pass (the row after it is evaluated
   in its place: a REP compare's exit pair); the P pass evaluates a third row in a running form
   too (S4: only after a start; a REP OUTM's I/O write done, its split floor, its exit clocks).
   A FLUSH row reached in the P pass is not acted on (the S5 budget; `+v35_diag` reports it):
   a lost flush would send the run astray; every gate run is RTL = model.
16. (S5a) **The element loop's exits** are the datapath's at the loop row: CW = 1 before the
   element's decrement, the compare's result at its read's delivery. The model's walk
   (normalize.string_elements) gives the same elements, `op.cond` included when CW runs out on
   the exiting element (`scond` is the compare's exit either way).
17. (S5a) **History as counters.** str_single_start=write's last memory write among the last
   three bus cycles is the bus's `w_v / w_ncyc / w_rel` (the on-chip SFR store counts as a
   write, as `bus.cycles` holds it); mul_imm_count=sync's back-count at the post is counted
   forward from mul_from (`mf_cnt`); decide_abort's aborted cycle and xfer_nt_b2b / odd_until's
   "fetches issued before" are the queue's old-fetch tracker (`od_*`) and the sequencer's `dab`.
   flush_hold=start's hold is never 0 (every transfer class's hold is 1 or more), so a start's
   own clock is never held (the immediate case is not built).
18. (S5a) **QUIET** (no row under fit 62) waits on the fetch on the bus or `want_c`, the request
   as the clock began, where `eu.tick` asks wants_fetch at the row.

19. (S5b) **The 0F decode a clock ahead.** A 0F form's format needs the two bytes after the
   escape (the second opcode byte, the ModR/M byte). The start decodes the IR's 0F with the
   queue's head byte and the byte behind it (the delivery bypassed), the decode ahead with the
   bytes after the IR, or, when the IR is empty and the head byte is the escape, the two after
   it (as far as the window holds them by the clock's end). A form started before those bytes
   are there runs the template of what the window held and is re-decoded at its ModR/M take
   (Divergence 2's way); a start whose template was not in the window waits a clock (W_DEC,
   +v35_diag counts it). The second opcode byte's take is the start clock's chained take
   (page_take=own), so a start without its second byte stored waits at that take as the model's
   does. No gate run shows a W_DEC (diag silent on all 30,536 runs) and all are RTL = model.
20. (S5b) **page_b2b_win=run's look-back** (the plan's documented third divergence) is the bus
   unit's `take_near` flag (`c_tn`): a take on the clock before the fetch's issue or during its
   flight, or carried at the issue from a back-to-back predecessor that took one after its
   issue clock (`c_tkin`). Equivalent whenever the fetch before the current one is the one the
   take landed in; F34 rbit / F32 k=2 cells pass (RTL = model throughout).
21. (S5b) **pf_cnt** replaces page_mem=fixed's at-post back-count (`eu._submit`): the fetch-free
   clocks since the start counted forward (a fetch issued or on the bus restarts it, but a
   CL-index form's thru fetch); `x.b2b and x.start > pfree` cannot hold before the post under
   page_commit=post, so the count needs no committed-fetch exception. The read posts with
   min(pf_cnt, setup).
22. (S5b) **The skipped tail.** The bit fields' crossing alternatives leave up to four skipped
   rows after the row that runs; a run of skipped crossing rows passes in no time as far as the window holds the
   rows, and the cursor's row being the last its form runs is held as a flag (`tlr`) once seen
   (the window then aims at the next form's template, which the start needs). A crossing row
   waits until the field is known (`bf_ok`: the exec a clock or more before): a field exec
   delayed a clock (its registers not on the ports) delays the crossing decision a clock. None
   in the gate.
23. (S5b) **page_imm_sync=lead's same-clock go-on.** The index byte's take goes on to the ALU
   clocks on its own clock when the ModR/M take's sync owes nothing; the model's same-clock
   lapse of a sync still owed (no room, nothing in flight) is applied by the next clock's sync
   check instead.
24. (S5b) **page_ir_room=end's end evaluation** reads the room before the clock's takes in the T
   pass (`room_cf`); an end in the P pass reads the room after the P pass. None differs in the
   gate.
25. (S5b) **The bit fields' register updates** are spread over the form (the model applies them
   at its start): the offset register stepped and the PSW at the last operand take, EXT's AW at
   its last read's delivery (an offset in AL / AH stepped again after it), INS's datum from AW
   read after the step, IX / IY + 2 at the form's end; the words' addresses from IX / IY as
   they stood at the start. A register write lands before any later form reads it.
26. (S5b) **The EA latch's mode.** `v35_ea` keeps the (md, rm) its base + index were latched for:
   a form started before its ModR/M byte arrived latched the decode ahead's registers (an
   assumed ModR/M of 00); its re-decode at the ModR/M take now reads the ports again (this was
   S5a's: LDEA [BW] after such a start wrote BW + IX; timing never depended on it).
27. (S6) **A write's datum at B2.** store_imm's immediate and the result of an RMW whose write
   issued before its exec ran (`wd_rdy` 0 at the issue) are taken by the bus at B2 (`g_dsel`):
   the immediate's bytes not yet taken from the queue's head after T's takes (`imm_ahead`), the
   result with the exec's own clock forwarded (`res_f`). A datum not ready at B2 would leave the
   cycle's data stale; none in SingleStepTests or the corpus (the write-data score agrees).
28. (S6) **The V20's semantics where the corpus says nothing** (the reference's, funcref.py, from
   the V20 suite; the data book does not define them): CVTDB's base is 10 whatever its byte,
   CVTBD by 0 leaves AH FFh and AL, an empty BCD string (CL = 0) sets CY S AC V 0 and Z P 1, the
   C6 / C7 /1-/7 aliases store their immediate. ROL4 / ROR4's AL and POP PSW / RETI / SAHF's
   bits 1, 3, 5 stay the V35's (F32's silicon; the PSW's BRKI / F0 / F1 are the V35's), counted
   apart as the V20 classes.
29. (S6) **The segment arithmetic.** A request's address is its segment's base + a 16-bit offset
   (the second half of an odd word at offset FFFFh at offset 0); the fetch address wraps in PS
   with the PS after the clock's flush. The IR's address the loader keeps stays linear (its
   offset in PS, IP, is taken modulo 64 KiB wherever it is used: the return addresses, the
   relative targets).

## Gate (S6)

**Timing, unchanged:** `build_sim.sh direct v35`, a fresh output directory, `replay --core v35
--diag --jobs 8` and `--score` over the 36 refresh-off families: every one of the 30,536 runs RTL =
model, RTL-exact = model-exact 30,361 (each family as "Gate (S5b)"), the pre window exact on every
run, `--diag` silent.

**Write data** (`replay --score --data`, the same replays): 106,824 memory, stack and I/O writes,
every one agreeing with silicon's, in all 36 families (at cc0704f: 104,574 agreeing, 1,776 runs
differing: F14 F15 F16 push_m, F19 F21 F22 F26 store_imm, F25 F30 F39 LDEA -> OUT, F33 cvtbw, F36
push_sp).

**SingleStepTests** (`sst.py --rtl`, RTL_FILES and S6_FILES, 2,985,000 tests): **0 failures**.
Against the old core's table (RTL_FILES only, its rf bench):

| Class | old core (RTL_FILES) | S6, RTL_FILES | S6, S6_FILES |
| --- | --- | --- | --- |
| pass | 1,651,237 | 2,041,643 | 807,437 |
| fail | 0 | 0 | 0 |
| trap (the divide error's trap condition agreed) | 24,387 | 24,387 | - |
| V35_EE_FUNC (the old core's unbuilt forms) | 92,647 | run: see below | - |
| on-chip page (FFE00h-FFFFFh) | 448 | 601 | 286 |
| REP before a non-string form | 1,340 | 1,340 trap_nop (all before IDIV) | - |
| PREPARE with a level | 1,941 | 1,941 | - |
| V20's ROL4 / ROR4 AL (RTL = the V35 reference) | (reference) | 18,368 | - |
| V20's fixed PSW bits (RTL = the V35 reference) | - | - | 26,281 |
| reference unlisted | (reference) | 82 | 0 |
| trap_nop, register halves with no template | (in V35_EE_FUNC) | 30,107 | - |
| trap_nop, F6 /0 (TEST r/m8,imm8) | - | - | 9,996 |
| divergence: F6 / F7 /1 mem, FF /7 mem decoded rmw | (in V35_EE_FUNC) | 22,531 | - |

The old core's V35_EE_FUNC forms now all run: FF /2 /3 /4 /5 pass (memory, and /2 /4 on a
register); F6 / F7 /1 /2 /3, C6 / C7, FF /0 /1 /6 /7 on a register are trap_nop (F7 /3 2,575, FF /0
2,543, C7 2,539, C6 2,537, F6 /3 2,524, F7 /2 2,515, FF /6 2,509, F6 /1 2,499, FF /1 2,499, F7 /1
2,484, FF /7 2,477, F6 /2 2,406); F6 / F7 /1 and FF /7 on memory are the decode divergences
("Not built"). The on-chip page and unlisted counts are the reference's (the old flow counted
the rep-prefix and V35_EE_FUNC tests apart before running the reference, so fewer reached it).
"V20's" classes ran on the bench against the V35 reference's state and passed.

**`--regfile`** (the whole-core bench): over the 35 lists F0, F0w, F1 .. F33, 69,099 vectors (walk
29,487, random 19,116, modes 912, alu 19,584: today's generator over today's corpus; the 58,508 of
docs/v35s-hdl-plan.md were WP75's, before WP79's 0F / miscellany ALU codes and the later lists),
**0 bad**: pass 68,078, trap 319, on-chip page 89, trap_nop 512 (the old V35_EE_FUNC register
halves), divergence 101 (F7 /1 mem 64, MOV PS 37); over F34-F40, 38,760 vectors, 0 bad (pass
37,837 with the old V35_EE_FUNC forms' 300, trap 310, on-chip 13, trap_nop 512, divergence 88).

**The reference** (`sst.py`, funcref): RTL_FILES 2,084,281 pass, 0 fail (the old count
1,693,875); S6_FILES 817,433 pass, 0 fail, 26,281 V20's fixed PSW bits; funcref over F35, F36,
F37, F39, F40 (`funcref --family ... --silicon`): every start agreeing with the frozen model,
22,890 / 22,890 data cycles matching silicon.

## Synthesis trial (S6)

`efx_map` of `v35_eu` + `v35_ea` (S5b's script, `v2/s6/syn/build_s6_syn.sh`, a memory-capped
scope), the base cc0704f's files and the S6 tree: LUT4 8,589 -> 9,123 (+534, +6 %), FF 590 -> 605,
RAM_5K 0 -> 0, MULT 9 -> 8 (CVTDB's x 10 a constant), ADD 1,041 -> 910. The growth: the second EA
offset (the form after P, LDEA's: an adder and its displacement mux), the store_imm / RMW datum at
B2 (the queue-head immediate, the forwarded result), the segment-relative request addresses (one
base + 16-bit offset add and the w16 compare in each of `mkreq`'s two instances), the start
clock's prefix segment, `sp_ret` (16 FF), the adjusts' and converts' word writes and CVTBD by 0.
The other modules' edits are a few lines each (the arbiter's `raddr2` / `rlo` and late `g_dsel`,
the queue's PS-relative fetch increment).

27. (S7a) **The pass slots' vocabularies.** T2, T3 and the P pass's rows evaluate only the row
   features measured on the corpus for their slot (the struct `voc_t`); a row outside it stops
   the pass there (`voc_miss`, +v35_diag). None on the corpus. The P pass has no second start
   (a form ending in P after its first row is reported).
28. (S7a) **A start's template is the decode ahead's.** A start whose form's template inputs
   (`tkey`) differ from the ones the window was aimed with, or whose window was not aimed at a
   template (`ka_v`), waits a clock (W_DEC); before S7a a template found elsewhere in the window
   started. None on the corpus (diag silent).
29. (S7a) **The loader's formats from the registered table entry.** The IR's format needs its
   opcode's (and an escape's second byte's) table entry decoded a clock ahead; an IR loaded by L
   after T's takes in the same clock, or an escape whose second byte arrived on the clock, has
   no format (`ok_c` / `ok_l` 0): a start or a P start waits (W_DEC); a start try with the
   gate's format-free tests passing is counted. None on the corpus.
30. (S7a) **No P re-decode of a running form.** A running form taking its ModR/M byte in the P
   pass is reported (`p_mmiss`); its format would be the T re-decode's. None on the corpus.
31. (S7b) **The write datum at mid-B2 (a pin change).** The core's clock sits half a CPU clock
   after the model's convention (ce_a at the CPU clock's middle, where the read datum is sampled;
   ce_b at its edge: "Two ticks (S7b)"), so a clock's S5 / S6 results, the exec's among them,
   exist half a CPU clock after the edge that ends the model's clock. The one such result that
   reaches a pin is a write cycle's datum taken at B2 (the store_imm immediate, an RMW's result
   forwarded from the exec: S6's Divergence 27). Every write's datum is therefore driven on the data
   pins at mid-B2 (one register, written at ce_a), where v35_biu (and the model lane before S7b)
   drove it at the start of B2. The pins' address, R/W and strobe timing is unchanged. The V35's
   write strobe falls no earlier than mid-B2 (/IOSTB mid-B2, a memory write's /MSTB mid-way
   through the state before B3) and the data are sampled while it is low or as it rises (the
   harness lane, v35s_lane.sv, keeps the last sample before the strobe rises, as it does for the
   silicon lane), so the datum is valid wherever it is used; a device latching data at B2's
   start would not see it. The write-data gate compares the same lane samples as before.
32. (S7b) **The P step's cases.** The P pass evaluates its first row with the evaluator of its case
   (a data step, `VOC_P1D`, or any other row, `VOC_P1E`) and the rows after it on the same clock
   only where the corpus has them: after a data step done, P2 then P3 (`VOC_P2D`, `VOC_P3`); after
   a lead take, its clocks (`VOC_P2E`). Any other follow-on is reported (`voc_miss`) and not acted
   on. None on the corpus.

## Gate (S5b)

`fpga/v35s/build_sim.sh direct v35`, `replay --core v35 --diag --jobs 8` into a fresh output
directory, then `--score`, over the whole refresh-off corpus (36 families: F0 F0w F1 F2 F3 F4 F5
F6 F7 F9 F10 F11 F12 F14 F15 F16 F19 F20 F21 F22 F23 F24 F25 F26 F29 F30 F31 F32 F33 F34 F35
F36 F37 F38 F39 F40): **every one of the 30,536 runs RTL = model** (from t_fill, the pre window
exact on every run), so RTL-exact = model-exact in every family: 30,361 of 30,536 (fit 62's
refresh-off number), the 175 misses all the model's own and shared. `--diag` reports nothing (no
lost FLUSH, no bus start on a busy bus, no queue overflow, no lost register write, no
decode-ahead miss).

| Family | runs | model-exact | RTL-exact | RTL = model |
| --- | --- | --- | --- | --- |
| F0 | 18 | 18 | 18 | 18 |
| F0w | 20 | 20 | 20 | 20 |
| F1 | 54 | 54 | 54 | 54 |
| F2 | 120 | 120 | 120 | 120 |
| F3 | 840 | 840 | 840 | 840 |
| F4 | 456 | 456 | 456 | 456 |
| F5 | 840 | 840 | 840 | 840 |
| F6 | 576 | 576 | 576 | 576 |
| F7 | 432 | 432 | 432 | 432 |
| F9 | 408 | 408 | 408 | 408 |
| F10 | 204 | 204 | 204 | 204 |
| F11 | 132 | 132 | 132 | 132 |
| F12 | 204 | 204 | 204 | 204 |
| F14 | 732 | 732 | 732 | 732 |
| F15 | 840 | 840 | 840 | 840 |
| F16 | 1,014 | 1,014 | 1,014 | 1,014 |
| F19 | 1,290 | 1,290 | 1,290 | 1,290 |
| F20 | 3,594 | 3,594 | 3,594 | 3,594 |
| F21 | 3,576 | 3,576 | 3,576 | 3,576 |
| F22 | 1,320 | 1,314 | 1,314 | 1,320 |
| F23 | 360 | 360 | 360 | 360 |
| F24 | 912 | 902 | 902 | 912 |
| F25 | 588 | 577 | 577 | 588 |
| F26 | 906 | 906 | 906 | 906 |
| F29 | 456 | 427 | 427 | 456 |
| F30 | 1,476 | 1,467 | 1,467 | 1,476 |
| F31 | 234 | 234 | 234 | 234 |
| F32 | 858 | 846 | 846 | 858 |
| F33 | 1,050 | 1,026 | 1,026 | 1,050 |
| F34 | 1,596 | 1,547 | 1,547 | 1,596 |
| F35 | 1,044 | 1,038 | 1,038 | 1,044 |
| F36 | 750 | 750 | 750 | 750 |
| F37 | 432 | 432 | 432 | 432 |
| F38 | 864 | 864 | 864 | 864 |
| F39 | 1,320 | 1,318 | 1,318 | 1,320 |
| F40 | 1,020 | 1,003 | 1,003 | 1,020 |
| all | 30,536 | 30,361 | 30,361 | 30,536 |

Write data (the scorer compares timing only): the data of every memory, stack and I/O write of
the RTL's replays against the silicon corpus's: F32, F34, F39, F40 agree on every run but the
LDEA → OUT AL cells (F25's six chains of `ldea_bw*` with the OUT marker and F39's
`out-ctl-ldea-s`: AL after LDEA reads 20h; S5a's, timing unaffected). The BCD strings' write
datum (the pair's result, taken at the post) and their pair index (an element ended in the
same pass) were S5a's, built not run; fixed here.

## Gate (S5a)

`replay --core v35 --score` over the 32 refresh-off families with no 0F form: **every one of
the 25,742 runs RTL = model** (from t_fill, and the pre window exact on every run), so RTL-exact
= model-exact in every family: F0-F22 as S4 (F22 1,314 / 1,320 sharing the model's six), F23
360 / 360, F24 902 / 912, F25 577 / 588, F26 906 / 906, F29 427 / 456, F30 1,467 / 1,476, F31
234 / 234, F33 1,026 / 1,050, F35 1,038 / 1,044, F36 750 / 750, F37 432 / 432, F38 864 / 864
(the misses all the model's own). Not gated: F32, F34, F39, F40 (the 0F page, S5b) and the
refresh-on lists F8 F13 F17 F18 F27 F28.

## Two ticks (S7b)

The CPU clock is two fabric ticks at the target (a 64 MHz fabric clock, a 32 MHz CPU clock; no
multicycle or other timing exception anywhere). `v35_top` makes the two enables:

- `ce_a`: the CPU clock's middle (`ce_mid`, the strobe edge): every architectural register and the
  bus unit's read-datum register (mid-B3, where the V35 samples the datum). Tick A starts there:
  S1 (arrival, from the registered datum) through S4 (the grant).
- `ce_b`: the CPU clock's edge: the pipeline registers that hold tick A's results (each module's
  `(S7b) the ce_b registers` block). Tick B starts there: S5 (the P pass) and S6 (the next state,
  the decode ahead, the ROM window's address), ending at the next `ce_a`.

Tick B and the `ce_a` blocks read tick A's results only through the ce_b registers (never tick
A's logic); tick A reads only architectural registers. The pins keep the model's timing: B1 / B2
at the edge (`ce_e`) from the grant tick A has just decided, the strobes and the read latch at the
middle from the cycle's next state; the write datum at mid-B2 (Divergence 31). The core's state is
half a CPU clock later than the model's convention; nothing else changes. After a reset `ce_a`
waits for a `ce_b`.

Simulation: the core's registers update on `ce_a` and `ce_b` only, so the default (ce_b at the
edge) runs exactly as at the target while the harness keeps its eight-tick clock and 30 ns
recording (`+v35_ticks=2` names that variant); `+v35_ceb=K` puts `ce_b` K ticks after `ce_a`
(K = 1..3 in the eight-tick clock; the pins' edge stays at the edge). `+v35_chk` compares every
ce_b register with its tick-A source at `ce_a` (a source that changed in tick B is reported):
silent on the whole corpus at both spacings. `V35_PLUSARGS` (acquire.py) passes plusargs to the
replays; `V35_SIM_DIR` / `V35_SIM_BINARY` build and run a second simulation binary.

The T pass is one row decision by cases: the cursor's row (or, when no form runs, the started
form's row 0 from the window) has its evaluator (`do_row`); beside it `fol` gives the state the row
leaves when it completes with `cont` (from the row's fields, the pass state and S1's values), and
the second row (case E: the form ended, the start and the next form's row 0, already in the window;
case R: the form's next row) and the third are evaluated from those states, not after an evaluator
(`t_fmiss` in `voc_miss` reports a row whose follow-on `fol` does not model; `+v35_chk` compares
`fol`'s state with the evaluator's field by field: silent on the corpus). A CLOCKS row's zero count
is tested without its add (`nz`). The P pass is one step of a small state machine (Divergence 32); the ROM window is read by
offsets tracked through a pass (`dw`, `du`: the row's offset from the window and from the cursor)
instead of address subtractions. Bring-up probes (simulation only): `+v35_stats` (each T pass that evaluated a second row and each
P pass on a retick, one line each), `+v35_wdec` (a start whose format differs from the decode
ahead's registered one, once a run: none on the corpus). Timing: `fpga/v35s/synth/v35_timing.sh MODULE` (the module in
the timing wrapper `v35_tw.sv` / `v35_tw.py`, efx_run compile at 15.625 ns, one create_clock).

## Synthesis (S7a)

Build and scripts:

    V35S_CORE=v35 fpga/v35s/build.sh       # the harness image with this core as the model lane
    fpga/v35s/synth/v35_harness.sh         # the same in a memory-capped scope, stage times and
                                           # the resource / timing summary (V35S_PNR_EFFORT=n)
    fpga/v35s/synth/v35_map.sh ucode loader arbiter queue bus regram eu top
                                           # efx_map of one module (or v35_top) as the top

`build.sh`'s `V35S_CORE=v35` branch copies the core (core/v35, `v35_sfr.sv`, `v35_refresh.sv`
and its `v35_chain_params.svh`), puts the ROM banks where `UCODE_DIR` names them under the
project, defines `SYNTHESIS` and `V35S_CORE_V35` as `efx:defmacro` elements (efx_map takes one
name from the `verilog-macros` param: two macros need two defmacros), appends
`core/model_v35.sdc` (no exceptions: see below) and runs the same timing check as the other
lanes; it now also fails when the place-and-route log reports an SDC line it could not apply.
`v35_top`'s sim-only diagnostics are under `ifndef SYNTHESIS`.

Per-module `efx_map` (Efinity 2026.1, T120F484, each module as the top, `SYNTHESIS` defined, in
a `MemoryMax=20G` scope), before (cc0704f, S5b's numbers reproduced) and after:

| Module | LUT4 before | after | ADD | FF before / after | RAM_5K before / after | map |
| --- | --- | --- | --- | --- | --- | --- |
| `v35_ucode` | 16,370 | 8,832 | 820 | 462 / 498 | 28 / 28 | 120 s |
| `v35_loader` | 4,768 | 2,318 | 76 | 56 / 291 | 23 / 0 | 36 s |
| `v35_arbiter` | 1,738 | 1,703 | 115 | 372 / 358 | 0 / 0 | 16 s |
| `v35_queue` | 1,053 | 1,053 | 260 | 192 | 0 | 9 s |
| `v35_bus` | 259 | 259 | 14 | 169 | 0 | 4 s |
| `v35_regram` | 16 | 16 | 0 | 14 | 4 | 2 s |
| `v35_eu` + `v35_ea` (S6's) | 8,589 | 8,589 | 1,041 | 590 | 0 | 76 s |
| sum | 32,793 | 22,770 | | 1,855 / 2,112 | 55 / 32 | |

The whole core (`v35_top`, every module, the SFR block and the refresh controller, the slot's
ports the only pins): **before 31,260 LUT4, 2,663 ADD, 1,803 FF, 54 RAM_5K, 9 MULT (map 820 s);
after 21,894 LUT4, 2,274 ADD, 2,000 FF, 32 RAM_5K, 9 MULT (map 491 s)**; in-context per module
after: ucode 7,036, eu 7,539 (+ ea 213), arbiter 4,300 (Efinity groups the request descriptor's
logic there), loader 1,561, queue 984, bus 264, regram 89, sfr 71. In the harness image (map
443 s, an intermediate S7a tree): the core 24,315 LUT4 of the harness's 28,798, the device's
block RAMs 952 / 1,056 used (the harness's buffers 920).

Not reached: the plan's targets (core 9,000 LUT4, the sequencer 5,000, the loader 1,500, the
arbiter 1,200) and timing. The eu (S6's file) is 8,589 alone. Timing: the place-and-route was
stopped (see the S7a hand-back's timing reading): the core is one feed-forward CPU clock whose
longest register-to-register path the placer estimated at 205-211 ns; the target since
2026-11-03 is a 64 MHz fabric clock with two ticks a CPU clock and no timing exceptions, which
needs the pipelined structure the reading proposes (S7b), not constraints. `core/model_v35.sdc`
therefore holds no multicycle.

What changed (all behaviour-preserving; the whole-corpus gate after each step, RTL = model on
every run, `--diag` silent):

- **The sequencer's pass slots have vocabularies (`voc_t`, `vmask`).** Each `do_row` instance
  implements only the row features its slot meets on the corpus (measured: the rows each of
  T1/T2/T3/P1/P2/P3 evaluated over all 30,536 runs); a row outside it is not acted on and is
  reported (`voc_miss`, +v35_diag). T1 (the cursor's row) keeps every feature. 16,370 -> ~10,600.
- **The start's template by key.** The window holds the decode ahead's template (`ka_v`, the key
  `tkey` = the class, the format bits and run bits `v35_tmpl_sel` reads, registered); a start
  hits when its form's key equals it, else it waits (W_DEC, counted). Three `tbase` lookups and
  four start-time window reads become one lookup (the decode ahead's) and two compares.
- **One advance and one arm instance a row** (`do_row` wraps `do_row_b`: the cursor's advance
  with the skip run, a halt, a take's exit arm after the body; the ENTRY / PRE_OP arm after the
  wait's evaluation); **the skip run as a per-window-position table** computed once a clock.
- **No second start in the P pass** (none on the corpus; reported).
- **The loader reads the decode tables once a clock**: the decode ahead reads the native / 0F
  table entry of the next form's opcode (or the byte behind an escape) and registers it with its
  page, opcode and the prefix's repc (`pd_*`); the IR's format (`fmt_c`, and `fmt_l`: the same
  form) is assembled from that entry and the live ModR/M byte (`v35_fmt_asm`, now emitted by
  ucgen with `v35_fmt_of` calling it); the running form's ModR/M re-decode from its start's entry
  (`d_run`). A format not decoded a clock ahead is flagged (`ok_c`, `ok_l`): its start waits.
  The P pass's re-decode of a running form (`fmt_mp`) is not built (no P take of a running
  form's ModR/M byte on the corpus; `p_mmiss` reports one). 4,768 LUT4 / 23 RAM_5K -> 2,318 / 0.
- **The arbiter's queued positions** keep only the request, its pair flag and its not_before
  count (`qtrim`): their counts start at the promotion (`mk`). Small (1,738 -> 1,703): Efinity
  had already found most of those registers constant. Three positions stay (the third is used on
  the corpus).

Cut readings that guided this (ucode, current tree): the P pass costs ~3,000 LUT4 of which its
first evaluator ~700 and P2/P3 ~1,250; the T pass's third row ~1,400; the second row ~2,100
(its vocabulary ~1,300); the template lookup of the decode ahead ~700; the base without P, T2
and T3 ~4,000. Loader: the group table ~190 LUT4 per format assembly (three remain: the decode
ahead, the IR, the T re-decode).

## Synthesis trial (S5b)

S5a's per-module `efx_map` (Efinity 2026.1, T120F484, one module as the top, `SYNTHESIS`
defined, each in a `systemd-run --user --scope -p MemoryMax=20G` scope; scratchpad
`v2/s5b/syn/build_s5b_syn.sh`, S5a's script), against S5a's table:

| Module | LUT4 | ADD | FF | RAM_5K | MULT | map | S5a LUT4 / FF / RAM |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `v35_arbiter` | 1,738 | 120 | 372 | 0 | 0 | 10 s | 1,615 / 335 / 0 |
| `v35_ucode` | 16,370 | 1,195 | 462 | 28 | 0 | 219 s | 13,091 / 426 / 28 |
| `v35_eu` + `v35_ea` | 8,589 | 1,041 | 590 | 0 | 9 | 47 s | 7,679 / 569 / 0 |
| `v35_regram` | 16 | 0 | 14 | 4 | 0 | 1 s | 16 / 14 / 4 |
| `v35_queue` | 1,053 | 260 | 192 | 0 | 0 | 6 s | 1,030 / 190 / 0 |
| `v35_bus` | 259 | 14 | 169 | 0 | 0 | 2 s | 248 / 160 / 0 |
| `v35_loader` | 4,768 | 76 | 56 | 23 | 0 | 48 s | 3,962 / 54 / 12 |
| sum | 32,793 | 2,706 | 1,855 | 55 | 9 | | 27,641 / 1,748 / 44 |

Where the growth is (no second copy of `do_row`, `mkreq`, `v35_fmt_of` or `run_of` added):
`v35_ucode` +3,279 LUT4 is the 0F page's rules inside the six `do_row` copies (page_mtake's wait,
mt_floor, mr_sync, page_ir, the post's pfree fields, the crossing rows' wait), the pass state's
new fields riding along (`ps_t` +23 bits), the skip run (one 4-bit window summary a clock,
`wxs`, read by each copy) and the tail flag's window aim; a first version of the skip run that
read the window's rows in every copy cost 23,233 LUT4 (+10,142): the summary vector is the
form kept. `v35_eu` +910 the bit ops / digit rotates / bit fields in `exec()`, the field
extract and insert, `bf_cost` and the INS datum. `v35_loader` +806 LUT4 and 11 RAM_5K: the
escape's page-1 decode (`dec` now reads a third byte, v35_fmt_of on the 0F half) in the IR's,
the IR-after-L and the decode-ahead lookups, and the page-1 re-decodes. `v35_arbiter` +123 the
pfree count, pthru / take_ask, ftail, page_imm_run.

## Synthesis trial (S5a)

S4's per-module `efx_map` (Efinity 2026.1, T120F484, one module as the top, `SYNTHESIS`
defined, each in a `systemd-run --user --scope -p MemoryMax=20G` scope; scratchpad
`v2/s5a/syn/build_s5a_syn.sh`, S4's script), against S4's table:

| Module | LUT4 | ADD | FF | RAM_5K | MULT | map | S4 LUT4 / FF / RAM |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `v35_arbiter` | 1,615 | 100 | 335 | 0 | 0 | 9 s | 1,427 / 289 / 0 |
| `v35_ucode` | 13,091 | 1,036 | 426 | 28 | 0 | 154 s | 10,594 / 360 / 28 |
| `v35_eu` + `v35_ea` | 7,679 | 846 | 569 | 0 | 9 | 40 s | 5,785 / 422 / 0 |
| `v35_regram` | 16 | 0 | 14 | 4 | 0 | 1 s | 16 / 14 / 4 |
| `v35_queue` | 1,030 | 254 | 190 | 0 | 0 | 6 s | 858 / 154 / 0 |
| `v35_bus` | 248 | 14 | 160 | 0 | 0 | 2 s | 230 / 152 / 0 |
| `v35_loader` | 3,962 | 67 | 54 | 12 | 0 | 37 s | 3,469 / 54 / 20 |
| sum | 27,641 | 2,317 | 1,748 | 44 | 9 | | 22,379 / 1,445 / 52 |

Where the growth is (not restructured: S7's job; no second copy of `do_row`, `mkreq` or
`v35_fmt_of` was added): `v35_ucode` +2,497 LUT4 is the six `do_row` copies' new row semantics
(DECIDE's old-fetch and abort tests, the fetch-hold arms, SPLIT_FLOOR / FROM_START, the element
loop's exits, the post's new window fields), the skip-ahead's six `sk` selections (one more
window read each), the start-time run bits (`run_of` three times: T, P, the decode ahead) and the
S5a timers; `v35_eu` +1,894 the transfers' target mux, the string unit (IX / IY flops, their
steps, the write-through, the compare), the reads' capture and the new exec operations (LDEA's
EA, PREPARE / DISPOSE, the adjusts, CVTDB's AH x imm (likely the ninth MULT), CVTBD's divide by
an immediate (much of the ADD growth)); `v35_loader` +493 LUT4 and 8 fewer RAM_5K: the REP prefix's decode (`dec`:
the escape and repc bits of the IR's entry beside the lookup) changed how Efinity mapped the
decode tables. The 0F page (S5b) is not in these numbers.

## Synthesis trial (S4)

`efx_map` (Efinity 2026.1, Trion T120F484), one module as the top (its ports the wrapper's: every
other net a pin), `SYNTHESIS` defined, each in a `systemd-run --user --scope -p MemoryMax=20G`
scope (scratchpad `v2/s4/syn/build_s4_syn.sh`):

| Module | LUT4 | ADD | FF | RAM_5K | MULT | map |
| --- | --- | --- | --- | --- | --- | --- |
| `v35_arbiter` | 1,427 | 95 | 289 | 0 | 0 | 8 s |
| `v35_ucode` | 10,594 | 766 | 360 | 28 | 0 | 190 s |
| `v35_eu` + `v35_ea` | 5,785 (`v35_ea` 204) | 501 | 422 | 0 | 8 | 30 s |
| `v35_regram` | 16 | 0 | 14 | 4 | 0 | 2 s |
| `v35_queue` | 858 | 221 | 154 | 0 | 0 | 8 s |
| `v35_bus` | 230 | 8 | 152 | 0 | 0 | 3 s |
| `v35_loader` | 3,469 | 67 | 54 | 20 | 0 | 50 s |
| sum | 22,379 | 1,658 | 1,445 | 52 | 8 | |

Where `v35_ucode` and `v35_eu` spend their LUTs (a reading for S7, from these runs and three
variants of `v35_ucode` with parts cut, not a redesign):

- `v35_ucode`: the P pass is about 4,300 LUT4 (10,594 → 6,289 with the pass cut), the T pass's
  third row about 1,150 (→ 9,449; both cut: 4,906). Each `do_row` is one copy of the whole row
  decoder, the take / post / wait logic and the pass state (`ps_t`, 348 bits: the 115-bit format
  word and the 124-bit class constants ride along so a start can replace them mid-pass): six
  copies (T 3, P 3), four start points (`start_ps` in s1, s3, p1, p3) each a 239-bit 2:1 mux,
  fourteen `rowat` window muxes (64 bits, 5:1), three `tbase` template lookups (`v35_tmpl_of`'s
  case table) and the gate twice per pass. The 11-bit counters (`res`, `hold_res`, `res_e`, the
  `nval` sources) are most of the 766 ADD, not of the LUTs. The ROM is 28 RAM_5K (four banks of
  7). The cheapest cuts for S7: one `do_row` instance with the pass state narrowed to the fields
  a row reads (the format word and class constants as registered sideband, not pass state), the
  P pass as a restricted second evaluation of that instance's outputs.
- `v35_eu`: the exec function (`exec()`: the ALU, shifter, flags, the register-role muxes
  `opnd` x2 over the ports, `rget` forwarding) is evaluated once per clock for `f_now`, but the
  request builder `mkreq` is instantiated twice (T, P) with its own `opnd` / `wdatum` muxes, and
  `v35_ea` 204. The 8 MULT: 7 for the exec's multiplies (`v35_mul` for MUL / IMUL, MUL imm), 1
  for MUL's sign-clock product (`mneg`; 143 LUT4 with it). The divider steps one restoring
  iteration a clock (no MULT).
- `v35_loader` (3,469 LUT4, 20 RAM_5K): `v35_fmt_of` is evaluated six times a clock (the IR, the
  re-decodes at a T and a P ModR/M take, the IR after L, the decode ahead) and `v35_cls_const`
  twice: the decode tables as ROMs (RAM_5K) and their muxes.

## Synthesis trial (S3)

`efx_map` (Efinity 2026.1, Trion T120F484, in a `systemd-run --user --scope -p MemoryMax=20G`
scope) of a wrapper holding `v35_ucode`, `v35_eu` and `v35_regram` with every other input a
port, `SYNTHESIS` defined: map passes in 200 s; 13,296 LUT4, 1,127 ADD, 631 FF, 32 RAM_5K (the
ROM's four banks 7 each, the register RAM's four halves 1 each), 8 MULT. The banks are plain
64-bit vectors read into a register at `ce` (an array of the packed `uc_row_t` initialised by
`$readmemh` was folded into LUTs). Not a timing result: the wrapper is not placed or routed.

## Build, replay, trace

    fpga/v35s/build_sim.sh direct v35        # build/fpga/v35s/verilator-direct-v35/Vv35s_harness
    rm -rf build/validation/v35s/chains-sim-v35
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains replay --core v35 --diag \
        --family F0 F0w F1 F2 F3 F4 F5 F6 F7 F9 F10 F11 F12 F14 F15 F16 F19 F20 F21 F22 \
                 F23 F24 F25 F26 F29 F30 F31 F32 F33 F34 F35 F36 F37 F38 F39 F40 --jobs 8
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains replay --core v35 --score \
        --family F0 F0w F1 F2 F3 F4 F5 F6 F7 F9 F10 F11 F12 F14 F15 F16 F19 F20 F21 F22 \
                 F23 F24 F25 F26 F29 F30 F31 F32 F33 F34 F35 F36 F37 F38 F39 F40 [--show N]
    # one chain, the RTL event trace against the frozen model from t_fill (W:dec a start that
    # waited for its decode, W:lost a register write dropped; W:<reason>/<hold> the arbiter's
    # fetch hold, e.g. /hold_fetch, /lead, /free_hold):
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains evtrace --id F1-out-m4-pO-w1 \
        --rtl F1-out-m4-pO-w1.trace --run
    # (S5a) more plusargs for the evtrace run (the sequencer's state per clock; the RTL side's
    # class names are mapped to their base classes as the model side's are):
    V35_PLUSARGS="+v35_dbg=F1.dbg" PYTHONPATH=host/src:. python3 -m validation.v35s.chains \
        evtrace --id F1-out-m4-pO-w1 --rtl F1-out-m4-pO-w1.trace --run
    # the function bench (v35_fn_pkg):
    fpga/v35s/build_rf_tb.sh
    PYTHONPATH=host/src:. python3 -m validation.v35s.chains.rtl_vectors --fn --family F0 F3 F23
    # lint (clean with and without V35S_CORE_V35 / SYNTHESIS):
    cd fpga/v35s/core && verilator --lint-only -Wall -DV35S_CORE_V35 -I. -Iv35 v35/v35_lint.vlt \
        v35/v35_front_pkg.sv v35/v35_pkg.sv v35/v35_fn_pkg.sv v35/v35_bus.sv v35/v35_queue.sv \
        v35/v35_loader.sv v35/v35_useq.sv v35/v35_ea.sv v35/v35_eu.sv \
        v35/v35_regram.sv v35/v35_trace.sv v35_sfr.sv v35_refresh.sv v35/v35_top.sv \
        --top-module v35_top

`--diag` on replay passes `+v35_diag` (a bus start on a busy bus, a queue overflow, a lost
register write, a FLUSH row in the P pass, a decode-ahead miss). `+v35_dbg=FILE` writes the sequencer's state per clock (bring-up only,
`ifndef SYNTHESIS`). The ROM's banks load from `fpga/v35s/core/v35/` relative to the working
directory (the repository root; `v35_ucode`'s `UCODE_DIR` parameter).
