`timescale 1ns/1ps

// V35S core v2 (MX0): the microinstruction word and the decode's types (docs/v35s-mechanisms.md
// section 4; fpga/v35s/core/v35/README.md "MX0"). Hand-written: this file is the single source
// of the word's layout; the microprogram assembler (validation/v35s/chains/uasm.py) reads the
// enums and the struct below to pack the ROM banks, and generates the decode table included at
// the end (v35_udecode_tbl.svh: the opcode byte, the 0F second byte and the group opcodes'
// ModR/M -> the routine's entry and the format bits).
//
// One word is one CPU clock. No field carries a count of clocks, a class, a format attribute of
// another instruction or a bus-unit attribute: a word names registers, an ALU operation, an EA
// step, a bus request on the A1 port, a queue pop, the F wait, the E end, the sequencing and a
// loop-counter load (from CL, an immediate, the operand width's bit count, or the instruction's
// remaining byte count for the trap routine).
package v35_pkg;

    // ---- register selectors: the register RAM's read ports A / B and its write port ----
    // REG / RM the ModR/M fields, OPR the opcode's bits 2:0, DST / SRC by the format's direction
    // bit, the eight word registers by name (BYTE width: the low half, HIGH: the high half),
    // SREG the ModR/M reg field's segment, SOPR the opcode's bits 4:3 segment, the four segments
    // by name, PSW (write only: POP PSW's bits 11:0), BASE / INDEX the ModR/M mode's EA registers
    typedef enum logic [4:0] {
        RS_NONE = 5'd0, RS_REG = 5'd1, RS_RM = 5'd2, RS_OPR = 5'd3, RS_DST = 5'd4,
        RS_SRC = 5'd5, RS_AW = 5'd6, RS_CW = 5'd7, RS_DW = 5'd8, RS_BW = 5'd9, RS_SP = 5'd10,
        RS_BP = 5'd11, RS_IX = 5'd12, RS_IY = 5'd13, RS_SREG = 5'd14, RS_SOPR = 5'd15,
        RS_PS = 5'd16, RS_SS = 5'd17, RS_DS0 = 5'd18, RS_DS1 = 5'd19, RS_PSW = 5'd20,
        RS_BASE = 5'd21, RS_INDEX = 5'd22
    } v35_rsel_e;

    // ---- the width of this word's register accesses and ALU operation ----
    typedef enum logic [1:0] {
        WD_FMT = 2'd0, WD_BYTE = 2'd1, WD_WORD = 2'd2, WD_HIGH = 2'd3
    } v35_wid_e;

    // ---- sources: the moves', the ALU operands' and the write port's ----
    // RA / RB the RAM ports' data (this clock's read), TA TB TC the temporaries, SIG the last
    // ALU result (SIGMA), IMM the popped immediate by the format (a word, or a byte sign- or
    // zero-extended), IMM8 the first immediate byte zero-extended (a port number), OPR the bus
    // datum (the F word's), DISP the popped displacement / far segment, ADDR the address register;
    // (MX2) PC the instruction pointer: the offset of the byte after the last the routine popped
    // (the loader's: the staged opcode's, else the next queue byte's), VEC a break's vector
    // address in the table (4n: n the popped type byte, or the format's for BRK 3 / BRKV; it
    // replaces ONES, which no word read), ONE 1
    typedef enum logic [3:0] {
        SR_ZERO = 4'd0, SR_RA = 4'd1, SR_RB = 4'd2, SR_TA = 4'd3, SR_TB = 4'd4, SR_TC = 4'd5,
        SR_SIG = 4'd6, SR_IMM = 4'd7, SR_IMM8 = 4'd8, SR_OPR = 4'd9, SR_PSW = 4'd10,
        SR_VEC = 4'd11, SR_DISP = 4'd12, SR_ADDR = 4'd13, SR_ONE = 4'd14, SR_PC = 4'd15
    } v35_src_e;

    // ---- move destinations (two moves a word) ----
    typedef enum logic [2:0] {
        MD_NONE = 3'd0, MD_TA = 3'd1, MD_TB = 3'd2, MD_TC = 3'd3, MD_ADDR = 3'd4,
        MD_OPRW = 3'd5
    } v35_mvd_e;

    // ---- the ALU (SIGMA <= f(x, y); the flags when wf) ----
    // GRP the format's 3-bit operation (the 00-3F block, the 80-83 group), SHI / SH1 / SHF the
    // shifter's loop (load, one step under the counter, the flags), MULI / MULS / MULF and
    // DIVI / DIVS / DIVF the multiply and the restoring divide (one bit a word), FLAG the
    // format's flag operation, PSWL the PSW's low byte from x's high byte (SAHF), (MX1) ADD the
    // 16-bit sum x + y, no flags (TRANS's table address, PREPARE's frame), (MX2) CITF the PSW's
    // IE and BRK flags cleared (a break's: the V20 ROM's CITF on its PSW push), (MX3b) ADJ the
    // adjust of AW by the format's operation (ADJ4A / ADJ4S / ADJBA / ADJBS: op3 1:0), CVBI / CVBF
    // CVTBD's divide (the restoring divide's state from AL and y, the byte divisor; the finish
    // {quotient, remainder} into SIGMA, AH FFh and AL kept by a zero divisor, S Z P of AL), CVDI /
    // CVDF CVTDB's multiply (the multiply's state from AH and ten; the finish: the product's low
    // byte plus AL into SIGMA's low byte, AH zero, the add's flags); (MX3c, the field widened
    // to six bits: 30 of 32 were used) the 0F page: BIT the bit operation of op3 1:0 (TEST1
    // CLR1 SET1 NOT1) on x at the bit y names (modulo the width; TEST1's S Z P of the masked
    // value, CY AC V cleared), BCDI the BCD string's carry cleared and its zero term set, BCDS
    // one packed-BCD byte step (x the destination byte, y the source byte, op3 0 the add, else
    // the subtract, the carry / borrow in and out on the step latch, the zero term
    // accumulated), BCDF the string's flags from the two latches, R4 the digit rotate of op3 0
    // (ROL4: the operand's low digit to its high, AL's low digit in; ROR4 the reverse) on the
    // byte x with AL from y (the new operand byte to SIGMA, the new AL to tmpc)
    typedef enum logic [5:0] {
        AL_NONE = 6'd0, AL_PASS = 6'd1, AL_GRP = 6'd2, AL_AND = 6'd3, AL_INC = 6'd4,
        AL_DEC = 6'd5, AL_NOT = 6'd6, AL_NEG = 6'd7, AL_INC2 = 6'd8, AL_DEC2 = 6'd9,
        AL_SEXT = 6'd10, AL_SIGNW = 6'd11, AL_SHI = 6'd12, AL_SH1 = 6'd13, AL_SHF = 6'd14,
        AL_MULI = 6'd15, AL_MULS = 6'd16, AL_MULF = 6'd17, AL_DIVI = 6'd18, AL_DIVS = 6'd19,
        AL_DIVF = 6'd20, AL_FLAG = 6'd21, AL_PSWL = 6'd22, AL_ADD = 6'd23, AL_CITF = 6'd24,
        AL_ADJ = 6'd25, AL_CVBI = 6'd26, AL_CVBF = 6'd27, AL_CVDI = 6'd28, AL_CVDF = 6'd29,
        AL_BIT = 6'd30, AL_BCDI = 6'd31, AL_BCDS = 6'd32, AL_BCDF = 6'd33, AL_R4 = 6'd34
    } v35_alu_e;

    // ---- the EA step: the address register from the popped displacement (DISP), or base +
    // index + displacement of the ModR/M mode (BI: base on port A, index on port B) ----
    typedef enum logic [1:0] {
        EA_NONE = 2'd0, EA_DISP = 2'd1, EA_BI = 2'd2
    } v35_ea_e;

    // ---- a bus request posted on the A1 port (the address register, the write datum OPRW) ----
    typedef enum logic [2:0] {
        BQ_NONE = 3'd0, BQ_MEMR = 3'd1, BQ_MEMW = 3'd2, BQ_IOR = 3'd3, BQ_IOW = 3'd4
    } v35_bus_e;

    // ---- the request's segment: the default (a prefix's, else SS for a BP mode, else DS0),
    // SS (the stack: no override), DS1, (MX1) DSP a prefix's, else DS0 (an address the routine
    // formed without an EA mode: TRANS's table), (MX2) ZERO the segment 0 (a break's vector
    // table) ----
    typedef enum logic [2:0] {
        SG_DEF = 3'd0, SG_SS = 3'd1, SG_DS1 = 3'd2, SG_DSP = 3'd3, SG_ZERO = 3'd4
    } v35_seg_e;

    // ---- a queue pop (one byte from the word register) into a popped-byte register ----
    typedef enum logic [2:0] {
        PP_NONE = 3'd0, PP_MODRM = 3'd1, PP_IL = 3'd2, PP_IH = 3'd3, PP_DL = 3'd4, PP_DH = 3'd5,
        PP_PORT = 3'd6      // (MX1c) the port number (into IL: no take sync, the model's port_sync)
    } v35_pop_e;

    // ---- the loop counter's load ----
    // RB port B's low byte (CL), IL the first immediate byte, BITS the operand's bit count (8 or
    // 16 by the format's width), LEN the instruction's bytes still to pop (the trap routine),
    // (MX3c) CLH (CL + 1) / 2 from port B's low byte: CL shifted right by one with its low bit
    // as the carry-in (the BCD strings' byte pairs: CL digits)
    typedef enum logic [2:0] {
        CN_NONE = 3'd0, CN_RB = 3'd1, CN_IL = 3'd2, CN_BITS = 3'd3, CN_LEN = 3'd4, CN_CLH = 3'd5
    } v35_cnt_e;

    // ---- sequencing ----
    // JC / JNC on a condition, LOOP: the counter decremented, jump while it is not zero, DISPM
    // the dispatch on the byte this word pops (the ModR/M byte, the 0F page's second byte),
    // DISP the dispatch on the opcode the E word popped (the word after E only), (MX3c) EAC a
    // 0F form's ModR/M byte popped by this word: its mode decides the next word (register mode:
    // the target, the register form's path; a memory mode: the EA head of the byte's mode
    // called, returning to the next word, the memory path's add; mod 00 without a head: the
    // next word)
    typedef enum logic [3:0] {
        SQ_NEXT = 4'd0, SQ_JMP = 4'd1, SQ_JC = 4'd2, SQ_JNC = 4'd3, SQ_CALL = 4'd4,
        SQ_RET = 4'd5, SQ_LOOP = 4'd6, SQ_DISPM = 4'd7, SQ_DISP = 4'd8, SQ_EAC = 4'd9
    } v35_seq_e;

    // ---- jump conditions (registered state only) ----
    // CNTZ the loop counter is zero, SGN SIGMA's sign (by the width), DTRAP the divide error,
    // WORD the format's width is a word, (MX2) XC the transfer's condition by the format (`xc`:
    // the sixteen conditions on the PSW of 70-7F, BRKV's V, DBNZE / DBNZNE's Z test, DBNZ's and
    // BCWZ's counter test on SIGMA: the decremented CW, or CW), SNZ SIGMA is not zero, (MX3b) SGD F1,
    // the units' sign latch (MULI: the operands' signs differ; DIVI: the quotient's sign), DN the
    // divide unit's dividend negative (DIVI's)
    typedef enum logic [2:0] {
        CD_CNTZ = 3'd0, CD_SGN = 3'd1, CD_DTRAP = 3'd2, CD_WORD = 3'd3, CD_XC = 3'd4,
        CD_SNZ = 3'd5, CD_SGD = 3'd6, CD_DN = 3'd7
    } v35_cond_e;

    localparam int UADDR_W = 11;      // (MX1b) 2,048 words: the ROM passed 1,024

    // ---- the microinstruction (MSB first) ----
    typedef struct packed {
        v35_rsel_e  ra;         // RAM port A's register (read)
        v35_rsel_e  rb;         // RAM port B's register (read)
        v35_rsel_e  wr;         // the write port's register
        v35_src_e   ws;         // ... its data
        v35_wid_e   wid;        // the width of this word's register accesses and ALU op
        v35_mvd_e   d1;         // move 1: d1 <= s1
        v35_src_e   s1;
        v35_mvd_e   d2;         // move 2: d2 <= s2
        v35_src_e   s2;
        v35_alu_e   alu;        // SIGMA <= alu(ax, ay)
        v35_src_e   ax;
        v35_src_e   ay;
        logic       wf;         // W: the ALU's flags written
        v35_ea_e    ea;         // the EA step into the address register
        v35_bus_e   bus;        // a bus request posted
        v35_seg_e   seg;        // ... its segment
        logic       resv;       // the reservation raised (the routine will post)
        v35_pop_e   pop;        // a queue byte popped
        logic       e;          // E: the next opcode popped (one word follows)
        logic       wb;         // (MX1f) on an E word: the result's write-back holds the register
                                //   file's write port through this clock and the next
        logic       wp;         // (MX3) on an E word: the post-E word writes the register file
                                //   (the assembler sets it: the result's write after E holds the
                                //   write port on the clock after this one)
        logic       f;          // F: wait for the requested datum
        v35_cnt_e   cnt;        // the loop counter's load
        v35_seq_e   seq;
        v35_cond_e  cond;
        logic [UADDR_W-1:0] tgt;    // the jump / call / loop target
        logic       pfx;        // the segment prefix set (the format's)
        logic       susp;       // (MX2) SUSP: prefetching suspended from this word to the FLUSH,
                                //   the word waiting while a fetch cycle runs (the V20 ROM's SUSP)
        logic       fw;         // (MX2) the word waits while a fetch cycle runs or delivers its
                                //   word (a short transfer's decide: the frozen model's untaken)
        logic       flush;      // the queue flushed, the stream from SIGMA in PS
        logic       halt;       // halted
        logic       trap;       // the divide error raised
    } v35_uword_t;

    localparam int UWORD_BITS = $bits(v35_uword_t);
    localparam int UROM_BANKS = 3;          // 32-bit slices, bank 0 the low bits

    // ---- the decode (generated tables in v35_udecode_tbl.svh) ----
    // the opcode's entry and format bits (the first level, from the E pop's opcode register)
    typedef struct packed {
        logic [UADDR_W-1:0] entry;
        logic       trap;       // no routine (the trap routine pops the instruction's bytes)
        logic       has_modrm;
        logic       w;          // the operand width
        logic       d;          // the direction (DST = d ? REG : RM)
        logic       immw;       // the immediate is a word
        logic       sx;         // a byte immediate is sign-extended
        logic [2:0] op3;        // the format's operation (00-3F: bits 5:3; the flag op; (MX2) the
                                //   vector number of BRK 3 and BRKV)
        logic [2:0] seg;        // a segment prefix: {1, sreg} (0: none)
        logic [2:0] len;        // the bytes after the opcode (no ModR/M form; the trap's)
        logic       rq;         // the routine posts a request: the reservation rises when the
                                //   E word pops the opcode (the routine knows it will post)
        logic       wbs;        // (MX1f) the routine's first act reads the accumulator: the E word
                                //   that pops the opcode waits for the running write-back
        logic       e2;         // (MX2) the E word pops the opcode's second byte with it (a short
                                //   transfer's displacement, into IL)
        logic [4:0] xc;         // (MX2) the transfer's condition (CD_XC): 0-15 the PSW condition
                                //   of the encoding's low nibble (70-7F; BRKV's V; DBNZNE's NZ and
                                //   DBNZE's Z, the loop's continuing), 16 SIGMA != 0, 17 SIGMA == 0
        logic       pg;         // (MX3c) the 0F page: the E word pops the second opcode byte with
                                //   the opcode (into the ModR/M register mp); the dispatch reads
                                //   the second level on it
    } v35_udec_t;

    // the second level, on the popped ModR/M byte (or the 0F page's second byte)
    typedef struct packed {
        logic [UADDR_W-1:0] entry;
        logic       trap;
        logic [2:0] op3;        // the group's operation (the reg field), or the block's
        logic       ea;         // (MX1) a memory cell: the dispatch calls the EA head of the
                                //   ModR/M byte's mode, the routine's entry (its add) the return
        logic       eab;        // ... the book's EA heads (ea=book); else the pops alone
        logic       w;          // (MX3c) the 0F page's operand width (the second byte's bit 0 for
                                //   the bit operations; the bit fields' word)
    } v35_udecm_t;

    `include "v35_udecode_tbl.svh"

endpackage
