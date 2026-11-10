`timescale 1ns/1ps
`include "v35_macros.svh"

// (MX0b) The byte path: every pop takes the word register's next byte (`w0`, `w1`, `wn`: up
// to two bytes of one aligned word), loaded from the queue's stored bytes (`q_stored`: never the
// arriving word or the latch), one load a clock; the queue's `rd` is the load, `rel` the pops.
// V35_MX0B_WR picks the law (0 the stored bytes directly, 1 this word register, 2 its load a
// clock of its own); README "MX0b" has the three measured.
//
// V35S core v2 (MX0): the loader, shrunk to the opcode's staging register, the pop port and the
// decode (docs/v35s-mechanisms.md sections 3.1, 3.2, 4; README "MX0").
//
// The pop port. A microinstruction that pops an operand byte (the ModR/M byte, an immediate, a
// displacement, a port number: one a word) takes the queue's head byte into its register at
// the word's end; with no byte in the queue the word stalls (the sequencer's stall q). The E
// word pops the next opcode from the staging register `s` (the queue's seventh slot, variant
// B's staging byte) into the opcode register; with the staging register empty it stalls.
//
// The staging register is loaded from the queue's head when it is empty and the running
// instruction has no byte left to pop (`need` = 0): the byte after the instruction's last is
// the next opcode. `need` is the instruction's bytes still to pop, from its format: loaded at
// the E pop from the popped opcode's decode (v35_udec1 of the staging register: its ModR/M
// byte and its immediate or displacement bytes), extended at the ModR/M byte's pop by its
// displacement and the group's immediate (v35_umodrm) and at the 0F page's second byte's pop
// (v35_upage), counted down by each pop. While an instruction still owes bytes the staging slot
// stays counted by the queue (`stg`): the slot is the next opcode's.
//
// (MX1) The dispatch's target for a ModR/M memory cell (the decode's ea bit) is the EA head of
// the registered ModR/M byte's mode, called with the routine's entry as the return (dcall,
// dret): mod 01 one displacement pop, mod 10 and the direct form two, the book's heads (eab)
// with the book's EA clock as an OPEN word, mod 00 too (ea.uasm). The choice reads the mode's
// bits and the cell's two decode bits only.
//
// The decode's inputs are registers and the popped byte: v35_udec1 of the opcode register
// (registered into `fmt` at the dispatch, DISP), v35_udec2 of the opcode register and the byte
// a DISPM word pops (the group's reg field: `op3`). No byte is read that the routine does not
// pop.
//
// Two ticks: tick A decides the pops and the load (`rd`, `rel`, `stg` on the queue's port)
// from registers and the sequencer's tick-A word; the ce_a update reads tick A's decisions and
// the queue's head bytes through the ce_b registers.
//
// Registered state (widths): s_v 1, s_b 8, s_a 20, pc 20 (the next queue byte's address), need
// 3, op 8, op_a 20, opc 8 (the running instruction's opcode: the word after E still runs the
// last one's acts while `op` holds the next), modrm 8, il ih dl dh 4x8, fmt (v35_udec_t), op3 3;
// mp 8 (the ModR/M byte the E word popped: `modrm`, the running instruction's, loads from it
// at the dispatch, as fmt and opc do); the ce_b copies.
module v35_loader
    import v35_front_pkg::*;
    import v35_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        ce_b,
    // the queue's port (Q1, unchanged)
    input  wire [7:0]  qv0,
    input  wire [7:0]  qv1,
    input  wire [2:0]  q_avail,
    input  wire [2:0]  q_stored,        // (MX0b) the queue's stored bytes (the load's source)
    input  wire        q_arrive,        // (MX1c) a fetched word is delivered on this clock
    output wire [2:0]  rd,              // the bytes read (tick A): an operand pop, the staging load
    output wire [2:0]  rel,             // the bytes released (tick A)
    output wire        stg,             // the staging slot is taken after this clock
    // the stream's address: the reset's first byte, a flush's target
    input  wire [19:0] reset_addr,
    input  wire        flush,           // tick A: a FLUSH word executes
    input  wire [19:0] flush_lin,       // ... the new stream's linear address
    // the sequencer (tick A)
    input  wire        ex,
    input  v35_pop_e   pop,
    input  wire        e_pop,           // the word is an E word
    input  wire        disp,            // a DISP word executes (the format loads)
    input  wire        dispm,           // the word is a DISPM word
    output wire        q_stall,         // the word's pop finds no byte (stall q)
    // the registers
    output reg  [7:0]  op,              // the opcode the E word popped (the decode's input)
    output reg  [19:0] op_a,
    output reg  [7:0]  opc,             // the running instruction's opcode (loaded with fmt)
    output reg  [7:0]  modrm,
    output reg  [7:0]  il,
    output reg  [7:0]  ih,
    output reg  [7:0]  dl,
    output reg  [7:0]  dh,
    output v35_udec_t  fmt,             // the running instruction's format (registered)
    output reg  [2:0]  op3,
    output v35_udec_t  dec1,            // tick A: v35_udec1(op)
    output v35_udecm_t dec2,            // tick A: v35_udec2(op, the byte this word pops)
    output wire [2:0]  len,             // tick A: the bytes still to pop after this clock (LEN)
    output wire        l_load,          // tick A: the staging register loads (the trace, Q2's l_pop)
    output wire        o_pop,           // tick A: an operand byte popped
    output wire        o_epop,          // tick A: the E word pops the next opcode (Q2's start)
    output wire [UADDR_W-1:0] dent,     // tick A: the DISP word's target
    output wire        dcall,           // tick A: (MX1) ... an EA head, called: the return is dret
    output wire [UADDR_W-1:0] dret,     // tick A: ... the routine's entry (the head's return)
    output wire        dtrap,           // tick A: the instruction (op, modrm) has no routine
    output wire        resv_e,          // tick A: the E word pops an opcode whose routine posts
    output wire        s_modrm,         // the staged opcode has a ModR/M byte (registers)
    output wire        e_rmodrm         // tick A: (MX1c) the E word pops a register-mode ModR/M
);
    reg        s_v = 1'b0;
    reg [7:0]  s_b = 8'h00;
    reg [19:0] s_a = 20'd0;
    reg [19:0] pc = 20'hFFFF0;
    reg [2:0]  need = 3'd0;
    reg [7:0]  mp = 8'h00;
    // (MX0b) the word register: the EU's byte source, up to two bytes of one aligned word
    reg [7:0]  w0 = 8'h00, w1 = 8'h00;
    reg [1:0]  wn = 2'd0;              // the ModR/M byte the E word popped (the next instruction's)
    initial begin
        op = 8'h00;
        op_a = 20'd0;
        opc = 8'h00;
        modrm = 8'h00;
        il = 8'h00;
        ih = 8'h00;
        dl = 8'h00;
        dh = 8'h00;
        fmt = '0;
        op3 = 3'd0;
    end

    // ------------------------------------------------------------ tick A
    wire       wants_op = pop != PP_NONE;
    // (MX0b) the byte source the pops take from. V35_MX0B_WR 0: the queue's stored bytes
    // (ripeness: a byte is poppable the clock after it is stored, never on its arriving clock);
    // 1: the word register, loaded at the end of a clock that leaves it empty; 2: the word
    // register, loaded only on a clock that starts with it empty (its load a clock of its own)
    wire [7:0] sb0 = `V35_MX0B_WR == 0 ? qv0 : w0;
    wire [7:0] sb1 = `V35_MX0B_WR == 0 ? qv1 : w1;
    wire [1:0] sn = `V35_MX0B_WR == 0 ? (q_stored >= 3'd2 ? 2'd2 : 2'(q_stored)) : wn;
    // the E word pops the staging register's opcode and, when the opcode has one, its ModR/M
    // byte from the queue's head (the opcode's decode from the staging register)
    v35_udec_t ds;
    assign ds = v35_udec1(s_b);         // the staging register's opcode (popped by E)
    assign q_stall = (wants_op && sn == 2'd0)
                     || (e_pop && (!s_v || (ds.has_modrm && sn == 2'd0)));
    wire       opop = ex && wants_op && !flush;
    wire       epop = ex && e_pop;
    wire       mpop = epop && ds.has_modrm;     // ... and its ModR/M byte
    assign o_pop = opop || mpop;
    assign o_epop = epop;
    assign resv_e = epop && ds.rq;
    assign s_modrm = s_v && ds.has_modrm;
    assign e_rmodrm = mpop && sb0[7:6] == 2'd3;
    wire unused = &{1'b0, ds, dm, q_avail};
    wire [2:0] add = mpop ? ds.len + v35_umodrm(s_b, sb0)
                   : epop ? ds.len
                   : (opop && pop == PP_MODRM) ? v35_umodrm(op, sb0)
                   : (opop && dispm && !dec1.has_modrm) ? v35_upage(sb0) : 3'd0;
    wire [2:0] need_n = flush ? 3'd0 : need + add - (opop ? 3'd1 : 3'd0);
    wire       s_left = s_v && !epop;
    wire       sload = !flush && !s_left && need_n == 3'd0
                       && sn > ((opop || mpop) ? 2'd1 : 2'd0);
    // the bytes popped this clock (an operand or the E word's ModR/M byte, the staging load)
    wire [1:0] np = ((opop || mpop) ? 2'd1 : 2'd0) + (sload ? 2'd1 : 2'd0);
    wire [1:0] wn_left = wn - np;
    // (MX0b) the word register's load: the queue head's aligned word (one byte from an odd
    // address), from the stored bytes, one load a clock
    wire       pcq_odd = pc[0] ^ np[0] ^ wn_left[0];      // the queue head's address parity
    wire       wload = `V35_MX0B_WR != 0 && !flush && q_stored != 3'd0
                       && (`V35_MX0B_WR == 1 ? wn_left == 2'd0 : wn == 2'd0);
    wire [1:0] wk = (pcq_odd || q_stored == 3'd1) ? 2'd1 : 2'd2;
    assign l_load = `V35_MX0B_WR == 0 ? sload : wload;
    // the queue's port: the bytes leaving its storage (rd) and leaving the EU's room (rel);
    // the word register's bytes stay counted (unreleased) until popped
    assign rd = `V35_MX0B_WR == 0 ? {1'b0, np} : (wload ? {1'b0, wk} : 3'd0);
    assign rel = {1'b0, np};
    // (MX1c) V35_MX1C_ROOM: the staging slot while the running instruction owes bytes: 0
    // counted (MX0), 1 free on a word's arrival clock when the slot is empty (the frozen model's
    // room_ir=arrival_idle: the IR a seventh slot on an arrival clock), 2 free whenever empty
    wire   stg_free = `V35_MX1C_ROOM == 2 || (`V35_MX1C_ROOM == 1 && q_arrive);
    assign stg = s_left || sload || (need_n != 3'd0 && !stg_free);
    assign len = need_n;
    assign dec1 = v35_udec1(op);
    assign dec2 = v35_udec2(op, sb0);
    // the dispatch's (DISP) entry: the second level on the registered ModR/M byte for an
    // opcode with one, else the first
    v35_udecm_t dm;
    assign dm = v35_udec2(op, mp);
    // (MX1) a memory cell (dm.ea) dispatches to the EA head of the registered ModR/M byte's
    // mode and returns to the routine's entry (its add): mod 01 one displacement pop, mod 10 and
    // the direct form (mod 00 rm 110) two; with the book's heads (dm.eab) each head ends with
    // the book's EA clock its pops and the add do not fill (OPEN), mod 00 included. A mode
    // without a head (mod 00, ea=bare) enters the routine directly. The mode's bits only: no
    // opcode reaches the choice (the cell's two bits are the decode table's)
    wire       m_dir = mp[7:6] == 2'd0 && mp[2:0] == 3'd6;
    wire       m_ea = dec1.has_modrm && dm.ea;
    wire [UADDR_W-1:0] head = mp[7:6] == 2'd1 ? (dm.eab ? UROM_EAB8 : UROM_EA8)
                            : (mp[7:6] == 2'd2 && dm.eab) ? UROM_EAB16
                            : (mp[7:6] == 2'd2 || m_dir) ? UROM_EAD
                            : UROM_EAB0;
    assign dcall = m_ea && (mp[7:6] != 2'd0 || m_dir || dm.eab);
    assign dret = dm.entry;
    assign dent = !dec1.has_modrm ? dec1.entry : dcall ? head : dm.entry;
    assign dtrap = dec1.has_modrm ? dm.trap : dec1.trap;

    // ------------------------------------------------------------ (S7b) the ce_b registers
    reg        mpop_b = 1'b0, opop_b = 1'b0, epop_b = 1'b0, sload_b = 1'b0, flush_b = 1'b0, disp_b = 1'b0;
    reg        dispm_b = 1'b0;
    v35_pop_e  pop_b = PP_NONE;
    reg [7:0]  qv0_b = 8'h00, qv1_b = 8'h00, sb0_b = 8'h00, sb1_b = 8'h00;
    reg        wload_b = 1'b0;
    reg [1:0]  wk_b = 2'd0, wn_left_b = 2'd0;
    reg [2:0]  need_b = 3'd0;
    reg [19:0] flin_b = 20'd0;
    v35_udec_t dec1_b = '0;
    reg [2:0]  op3m_b = 3'd0;
    always_ff @(posedge clock) begin
        if (ce_b) begin
            opop_b <= opop;
            mpop_b <= mpop;
            epop_b <= epop;
            sload_b <= sload;
            flush_b <= flush;
            disp_b <= disp;
            dispm_b <= ex && dispm;
            pop_b <= pop;
            qv0_b <= qv0;
            qv1_b <= qv1;
            sb0_b <= sb0;
            sb1_b <= sb1;
            wload_b <= wload;
            wk_b <= wk;
            wn_left_b <= wn_left;
            need_b <= need_n;
            flin_b <= flush_lin;
            dec1_b <= dec1;
            op3m_b <= dispm ? dec2.op3 : dec1.has_modrm ? dm.op3 : dec1.op3;
        end
    end

    // ------------------------------------------------------------ the end of the clock (ce_a)
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            s_v <= 1'b0;
            pc <= reset_addr;
            s_a <= reset_addr;
            need <= 3'd0;
            wn <= 2'd0;
        end else if (ce_a) begin
            need <= need_b;
            // (MX0b) the word register: its bytes left after the pops, then the load
            if (flush_b)
                wn <= 2'd0;
            else if (wload_b) begin
                w0 <= qv0_b;
                w1 <= qv1_b;
                wn <= wk_b;
            end else begin
                wn <= wn_left_b;
                if (wn_left_b != 2'd0 && wn != wn_left_b)
                    w0 <= w1;
            end
            if (flush_b) begin
                s_v <= 1'b0;
                pc <= flin_b;
            end else begin
                pc <= pc + ((opop_b || mpop_b) ? 20'd1 : 20'd0) + (sload_b ? 20'd1 : 20'd0);
                if (sload_b) begin
                    s_v <= 1'b1;
                    s_b <= (opop_b || mpop_b) ? sb1_b : sb0_b;
                    s_a <= pc + ((opop_b || mpop_b) ? 20'd1 : 20'd0);
                end else if (epop_b)
                    s_v <= 1'b0;
            end
            if (epop_b) begin
                op <= s_b;
                op_a <= s_a;
            end
            if (mpop_b)
                mp <= sb0_b;
            if (opop_b) begin
                case (pop_b)
                    PP_MODRM: modrm <= sb0_b;
                    PP_IL, PP_PORT: il <= sb0_b;
                    PP_IH: ih <= sb0_b;
                    PP_DL: dl <= sb0_b;
                    PP_DH: dh <= sb0_b;
                    default: ;
                endcase
            end
            if (disp_b) begin
                fmt <= dec1_b;
                opc <= op;
                modrm <= mp;
                op3 <= op3m_b;
            end
            if (dispm_b)
                op3 <= op3m_b;
        end
    end

`ifndef SYNTHESIS
    /* verilator lint_off BLKSEQ */
    reg chk_on = 1'b0;
    integer chk_n = 0;
    initial chk_on = $test$plusargs("v35_chk");
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            if (opop_b !== opop || mpop_b !== mpop || epop_b !== epop || sload_b !== sload || flush_b !== flush
                || disp_b !== disp || dispm_b !== (ex && dispm) || pop_b !== pop
                || qv0_b !== qv0 || qv1_b !== qv1 || sb0_b !== sb0 || sb1_b !== sb1
                || wload_b !== wload || wk_b !== wk || wn_left_b !== wn_left || need_b !== need_n || flin_b !== flush_lin
                || dec1_b !== dec1) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader: a tick A source changed in tick B at %0t", $time);
            end
        end
    end
    final if (chk_on && chk_n != 0)
        $display("v35 chk: loader: %0d changes in tick B", chk_n);
    /* verilator lint_on BLKSEQ */
`endif
endmodule
