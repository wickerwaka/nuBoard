`timescale 1ns/1ps
`include "v35_macros.svh"

// V35S core v2 (MX0): the microsequencer (docs/v35s-mechanisms.md sections 3.1, 4; README
// "MX0"). One microinstruction a CPU clock from a registered ROM word: the ROM (three 32-bit
// banks, v35_urom_b?.hex, assembled by validation/v35s/chains/uasm.py) is read at ce_a with the
// next microaddress computed in tick B, so the word a clock executes is a register from its
// first tick on. The microaddress is a register.
//
// The five stalls, each from registered state at tick A (a stalled word performs none of its
// acts and is read again):
//   q     the word pops a byte and there is none: an operand byte and the queue is empty, or
//         E's opcode and the staging register is empty
//   f     F: the requested datum has not arrived (the datapath's opr_rdy: req_done or the
//         datum latched)
//   slot  the word posts a request while the EU's one request is still outstanding
//   hold  E while a memory write is outstanding with RAMEN = 1
//   halt  halted
//   fetch (MX0c) the dispatch while the bus unit runs a fetch (and a ModR/M form's on a
//         back-to-back fetch's issue clock): V35_MX0C_DISPATCH
//
// The next microaddress (tick B): the same word (stalled), the next, a jump (on a registered
// condition), a call (one return register: the V20 ROM's FARJMP subroutines nest one level,
// V20UC.TXT 0000-04FF has no FARJMP from inside a FARJMP target), a return, a loop on the
// counter, or a dispatch from the decode registered at the end of tick A: DISP (the word after
// E) on the opcode the E word popped (v35_udec1 of the loader's opcode register), DISPM on the
// byte this word pops (v35_udec2 of the opcode register and the word register's byte). No
// queue byte reaches the address except through those registers.
// (MX1) The dispatch of a ModR/M memory cell is a call: the target is the EA head of the
// registered ModR/M byte's mode (the loader's dent), the return register loads the routine's
// entry (dret); the head pops the displacement and returns (ea.uasm). One level still: no
// memory routine calls (the heads' return frees the register).
//
// The loop counter (9 bits) is loaded by a word from port B's low byte (CL), the immediate,
// the operand's bit count or the trap's remaining byte count, and stepped by LOOP.
//
// Depth (by construction, the levelizer's run is the overseer's): tick A: the stall terms
// (a handful of registered bits, the word's fields) and the decode lookups (the opcode register
// and the word register's byte into the generated case tables: ROM-like LUT logic) into the
// ce_b registers; tick B: the next-address mux (eight sources by the word's seq field and the
// registered ex) into the ROM's read address. The ROM output is a register.
//
// Registered state (widths): upc 10, the ROM word 86 (96), retr 10, cnt 9, halted 1, at_entry
// 1; the ce_b copies ex_b 1, d1_b 10, d2_b 10, (MX1) dc_b 1, dr_b 10.
module v35_useq
    import v35_pkg::*;
#(
    parameter string UROM_DIR = "fpga/v35s/core/v35/"
) (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        ce_b,
    // the loader (tick A: registers)
    input  wire        q_stall,         // the word's pop finds no byte (the loader's)
    input  v35_udec_t  dec1,            // v35_udec1(the opcode register)
    input  wire [UADDR_W-1:0] dent,     // the DISP word's target (the loader's)
    input  wire        dcall,           // (MX1) ... an EA head, called (the return register <- dret)
    input  wire [UADDR_W-1:0] dret,     // ... the routine's entry (the head's return)
    input  wire        dtrap,           // ... the instruction has no routine
    input  v35_udecm_t dec2,            // v35_udec2(the opcode register, the word register's byte)
    input  wire [2:0]  len,             // the instruction's bytes still to pop (the trap's LEN)
    input  wire [7:0]  il,              // the first immediate byte
    input  wire        fmt_w,           // the running form's width
    // the datapath (tick A: registers; rb_lo: tick B)
    input  wire        opr_rdy,         // F's datum is here
    input  wire        rq_busy,         // the request slot is taken
    input  wire        wr_hold,         // an outstanding write holds E
    input  wire        c_sgn,           // SIGMA's sign
    input  wire        c_dtrap,         // the divide error
    // (MX0c) the bus unit's registered facts the dispatch reads: a fetch cycle granted on an
    // earlier clock runs on this one (its clocks after the issue through its last), and a
    // back-to-back fetch issues on this clock
    input  wire        fetch_run,
    input  wire        b2b_now,
    input  wire        s_modrm,         // the staged opcode has a ModR/M byte (the loader's decode)
    input  wire [7:0]  rb_lo,           // port B's low byte (tick B)
    // the word and its execution
    output v35_uword_t word,            // the current microinstruction (a register)
    output wire        ex,              // the word executes this clock (tick A)
    output wire        ex_pop,          // ... but for the dispatch's fetch stall (the pops' view)
    output reg         ex_b,            // ... registered at ce_b (tick B, ce_a)
    output wire        start,           // a routine's entry word executes (an instruction starts)
    output wire        start_trap,      // ... and it is a trap (no routine)
    output wire [4:0]  why,             // the stall's reason (the trace): 0 none, 1 q, 2 f, 3 slot, 4 hold, 5 halt
    output reg         halted,
    output wire [UADDR_W-1:0] upc_o
);
    localparam int ROM_N = 1 << UADDR_W;

    // ------------------------------------------------------------ the ROM
    reg [31:0] rom0 [0:ROM_N-1];
    reg [31:0] rom1 [0:ROM_N-1];
    reg [31:0] rom2 [0:ROM_N-1];
    integer i;
    initial begin
        for (i = 0; i < ROM_N; i = i + 1) begin
            rom0[i] = 32'd0;
            rom1[i] = 32'd0;
            rom2[i] = 32'd0;
        end
        $readmemh({UROM_DIR, "v35_urom_b0.hex"}, rom0, 0, UROM_WORDS - 1);
        $readmemh({UROM_DIR, "v35_urom_b1.hex"}, rom1, 0, UROM_WORDS - 1);
        $readmemh({UROM_DIR, "v35_urom_b2.hex"}, rom2, 0, UROM_WORDS - 1);
    end

    reg [UADDR_W-1:0] upc = UROM_RESET;
    reg [31:0] q0 = 32'd0, q1 = 32'd0, q2 = 32'd0;
    wire [95:0] qw = {q2, q1, q0};
    assign word = v35_uword_t'(qw[UWORD_BITS-1:0]);
    assign upc_o = upc;

    reg [UADDR_W-1:0] retr = '0;
    reg [8:0]  cnt = 9'd0;
    reg        at_entry = 1'b0;     // the current word is a routine's entry, not yet executed
    initial halted = 1'b0;

    // ------------------------------------------------------------ tick A: the stalls
    wire st_q   = q_stall;
    wire st_f   = word.f && !opr_rdy;
    wire st_slt = word.bus != BQ_NONE && rq_busy;
    wire st_hld = word.e && wr_hold;
    // (MX0c) the dispatch (the word after E: the staged opcode's decode into its routine's
    // entry) waits while the bus unit runs a fetch cycle (V35_MX0C_DISPATCH >= 1), and a form
    // with a ModR/M byte also on the clock a back-to-back fetch issues (2). The dispatch and
    // the fetch exclude each other: one shared step (the decode's read and the queue's write)
    // (3: the same law on the E word, the staged opcode's pop into the opcode register: the
    // frozen model's start is that pop, its staging load (the IR load) stays free)
    wire st_fch = `V35_MX0C_DISPATCH >= 3
                  ? word.e && (fetch_run || (s_modrm && b2b_now))
                  : word.seq == SQ_DISP
                    && ((`V35_MX0C_DISPATCH >= 1 && fetch_run)
                        || (`V35_MX0C_DISPATCH == 2 && dec1.has_modrm && b2b_now));
    // the stalls a popping word can meet (the loader's pops read this: a DISP word never pops;
    // with the stall on the E word (3) it is the E word's too)
    wire base = !halted && !st_q && !st_f && !st_slt && !st_hld;
    assign ex_pop = base && !(`V35_MX0C_DISPATCH >= 3 && st_fch);
    assign ex = base && !st_fch;
    assign why = halted ? 5'd5 : st_q ? 5'd1 : st_f ? 5'd2 : st_slt ? 5'd3 : st_hld ? 5'd4
               : st_fch ? 5'd6 : 5'd0;
    assign start = at_entry && ex_pop;     // (an entry word is never the dispatch word; with
                                           //  3 an entry word that is an E word: ex_pop is ex)
    // the instruction is a trap: its opcode has no routine, or (the ModR/M / 0F head) its
    // second-level cell has none
    assign start_trap = dtrap || (word.seq == SQ_DISPM && dec2.trap);

    // ------------------------------------------------------------ (S7b) the ce_b registers
    reg [UADDR_W-1:0] d1_b = '0, d2_b = '0, dr_b = '0;
    reg        dc_b = 1'b0;
    reg [2:0]  len_b = 3'd0;
    reg [7:0]  il_b = 8'd0;
    reg        w_b = 1'b0;
    always_ff @(posedge clock) begin
        if (ce_b) begin
            ex_b <= ex;
            d1_b <= dent;
            dc_b <= dcall;
            dr_b <= dret;
            d2_b <= dec2.entry;
            len_b <= len;
            il_b <= il;
            w_b <= fmt_w;
        end
    end

    // ------------------------------------------------------------ tick B: the next address
    logic cond_v;
    always_comb begin
        case (word.cond)
            CD_CNTZ: cond_v = cnt == 9'd0;
            CD_SGN: cond_v = c_sgn;
            CD_DTRAP: cond_v = c_dtrap;
            CD_WORD: cond_v = w_b;
            default: cond_v = 1'b0;
        endcase
    end
    wire [UADDR_W-1:0] inc = upc + 1'b1;
    logic [UADDR_W-1:0] upc_n;
    always_comb begin
        if (!ex_b)
            upc_n = upc;
        else begin
            case (word.seq)
                SQ_JMP: upc_n = word.tgt;
                SQ_JC: upc_n = cond_v ? word.tgt : inc;
                SQ_JNC: upc_n = cond_v ? inc : word.tgt;
                SQ_CALL: upc_n = word.tgt;
                SQ_RET: upc_n = retr;
                SQ_LOOP: upc_n = cnt != 9'd1 ? word.tgt : inc;
                SQ_DISPM: upc_n = d2_b;
                SQ_DISP: upc_n = d1_b;
                default: upc_n = inc;
            endcase
        end
    end
    logic [8:0] cnt_n;
    always_comb begin
        cnt_n = cnt;
        if (ex_b) begin
            case (word.cnt)
                CN_RB: cnt_n = {1'b0, rb_lo};
                CN_IL: cnt_n = {1'b0, il_b};
                CN_BITS: cnt_n = w_b ? 9'd16 : 9'd8;
                CN_LEN: cnt_n = {6'd0, len_b};
                default: cnt_n = word.seq == SQ_LOOP ? cnt - 9'd1 : cnt;
            endcase
        end
    end

    // ------------------------------------------------------------ the end of the clock (ce_a)
    wire [UADDR_W-1:0] raddr = !reset_n ? UROM_RESET : upc_n;
    always_ff @(posedge clock) begin
        if (!reset_n || ce_a) begin
            q0 <= rom0[raddr];
            q1 <= rom1[raddr];
            q2 <= rom2[raddr];
        end
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            upc <= UROM_RESET;
            retr <= '0;
            cnt <= 9'd0;
            halted <= 1'b0;
            at_entry <= 1'b0;
        end else if (ce_a) begin
            upc <= upc_n;
            cnt <= cnt_n;
            if (ex_b && word.seq == SQ_CALL)
                retr <= inc;
            else if (ex_b && word.seq == SQ_DISP && dc_b)
                retr <= dr_b;      // (MX1) the dispatch's call of an EA head
            if (ex_b && word.halt)
                halted <= 1'b1;
            if (ex_b)
                at_entry <= word.seq == SQ_DISP;
        end
    end

    wire unused = &{1'b0, dec1, dec2, qw[95:UWORD_BITS]};

`ifndef SYNTHESIS
    // (S7b) chk: the ce_b registers against their sources at ce_a
    /* verilator lint_off BLKSEQ */
    reg chk_on = 1'b0;
    integer chk_n = 0;
    initial chk_on = $test$plusargs("v35_chk");
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            if (ex_b !== ex || d1_b !== dent || d2_b !== dec2.entry || len_b !== len
                || dc_b !== dcall || dr_b !== dret
                || il_b !== il || w_b !== fmt_w) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: useq: a tick A source changed in tick B at %0t", $time);
            end
        end
    end
    final if (chk_on && chk_n != 0)
        $display("v35 chk: useq: %0d changes in tick B", chk_n);
    /* verilator lint_on BLKSEQ */
`endif
endmodule
