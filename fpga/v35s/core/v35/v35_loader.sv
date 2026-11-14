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
// the queue's head bytes through the ce_b registers. (MX5c) The outcomes on the queue's port
// and the bus unit's strobes are registers selected by the registered stall outcome and the
// head byte's z1; the head byte enters through its tag (stored by the queue beside the byte)
// or, for the delivered word, through its decode in tick A (README "MX5" round 3).
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
    input  wire [7:0]  qv2,             // (MX1e) the window's third and fourth bytes (WR 3's refill)
    input  wire [7:0]  qv3,
    input  wire [2:0]  q_avail,
    input  wire [2:0]  q_stored,        // (MX0b) the queue's stored bytes (the load's source)
    // (MX5b) the queue's own registered facts for the head byte's decode: its first stored byte,
    // the latched byte and the latch's bit, the in-flight word's parity; with the delivered word
    // (the bus unit's datum register) they are the head byte's candidates, q_stored and the
    // latch's bit its select
    input  wire [7:0]  h_q0,
    input  wire [7:0]  h_lat,
    input  wire        h_latv,
    input  wire        h_odd,
    input  wire [15:0] h_dlv,
    input  wire [15:0] h_dlv_nx,        // (F5t) tick B: h_dlv's next value and its load (the bus
    input  wire        h_dlv_ld,        //   unit's datum register's D and enable)
    // (MX5c) the byte tags (`bt_f`, below): the queue's stored ones of its first stored byte and
    // its latched byte; the delivered word's, formed here on the delivery clock and stored by the
    // queue beside the bytes (high byte's, low byte's)
    input  wire [QTAG_W-1:0] h_q0t,
    input  wire [QTAG_W-1:0] h_latt,
    output wire [2*QTAG_W-1:0] dlv_tag,
    input  wire        q_arrive,        // (MX1c) a fetched word is delivered on this clock
    output wire [2:0]  rd,              // the bytes read (tick A): an operand pop, the staging load
    output wire [2:0]  rel,             // the bytes released (tick A)
    output wire        stg,             // the staging slot is taken after this clock
    // the stream's address: the reset's first byte, a flush's target
    input  wire [19:0] reset_addr,
    input  wire [15:0] reset_ip,        // (MX2) ... its offset in PS
    input  wire        flush,           // tick A: a FLUSH word executes
    input  wire        flush_w,         // (MX5) the word's FLUSH (a register: flush = ex && flush_w)
    input  wire [19:0] flush_lin,       // ... the new stream's linear address
    input  wire [15:0] flush_off,       // (MX2) ... its offset in PS
    // the sequencer (tick A)
    input  wire        ex,
    input  v35_pop_e   pop,
    input  wire        e_pop,           // the word is an E word
    input  wire        disp,            // a DISP word executes (the format loads)
    input  wire        dispm,           // the word is a DISPM word
    input  wire        e_rep,           // (F5d) the E word re-enters the REP page (ea=REP; a register)
    input  wire        e_rep_nx,        // ... the next word's (tick B)
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
    // (MX5b) tick B: the values opc, modrm and fmt load at the coming ce_a (the datapath's early
    // register read forms the next word's read address from them)
    output wire [7:0]  opc_nx,
    output wire [7:0]  modrm_nx,
    output v35_udec_t  fmt_nx,
    output reg  [2:0]  op3,
    output v35_udec_t  dec1,            // tick A: v35_udec1(op) ((MX5b) a register beside op)
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
    output wire        s_wbs,           // (MX1f) the staged opcode's routine reads the accumulator first
    output wire        e_rmodrm,        // tick A: (MX1c) the E word pops a register-mode ModR/M
    // (MX3c) the EAC word (a 0F form's ModR/M byte popped by a routine word): the byte's mode
    // (tick A, from the byte popped): register mode (the routine's register path), and for a
    // memory mode the EA head to call (the routine's ea=book / bare by the second level's eab)
    output wire        ec_reg,
    output wire        ec_call,
    output wire [UADDR_W-1:0] ec_head,
    // (MX5c) tick B: the next values of the stall's loader facts (the sequencer's registered
    // stall outcome), from the next word's pop fields, the queue's and the bus unit's next state
    input  v35_pop_e   pop_nx,
    input  wire        e_pop_nx,
    input  wire [2:0]  q_stored_nx,
    input  wire        q_latv_nx,
    input  wire        q_odd_nx,
    input  wire        q_discard_nx,
    input  wire        q_dlv_nx,        // a fetched word is delivered on the next clock
    input  wire        flush_w_nx,      // the next word's FLUSH, its DISPM
    input  wire        dispm_nx,
    output wire        q_stall_nx,
    output wire        s_modrm_nx,
    output wire        s_wbs_nx,
    output wire        d1_wbs_nx,       // the next v35_udec1(op)'s wbs and has_modrm
    output wire        d1_hm_nx,
    input  wire        brki,            // (F2b) PSW.BRKI (the EU's register): the I/O trap's dispatch
    output reg  [15:0] ins_ip,          // (F2b) the instruction's start: the offset of the opcode the
                                        //   E word popped, kept through a segment prefix (its first
                                        //   prefix's offset: the I/O and FPO traps push it)
    output wire [15:0] ip               // (MX2) the instruction pointer (registers): the offset of
                                        //   the byte after the last the routine popped
);
    reg        s_v = 1'b0;
    reg [7:0]  s_b = 8'h00;
    reg [19:0] s_a = 20'd0;
    reg [19:0] pc = 20'hFFFF0;
    // (MX2) the offsets in PS of the next queue byte (`pc`'s) and of the staged opcode (`s_a`'s):
    // the instruction pointer a transfer reads (SR_PC), counted as pc is, loaded by a flush
    reg [15:0] ipo = 16'd0, s_ip = 16'd0;
    reg [2:0]  need = 3'd0;
    reg        hold = 1'b0;             // (MX1f) a word operand's low byte popped, not yet released
    reg        hold2 = 1'b0;            // (MX2) a short transfer's displacement, released a clock late
    reg [7:0]  mp = 8'h00;
    // (MX0b) the word register: the EU's byte source, up to two bytes of one aligned word
    reg [7:0]  w0 = 8'h00, w1 = 8'h00;
    reg [1:0]  wn = 2'd0;              // the ModR/M byte the E word popped (the next instruction's)
    initial begin
        op = 8'h00;
        op_a = 20'd0;
        ins_ip = 16'd0;
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
    // (MX1d) V35_MX1D_ARRIVE 1: a delivered word's bytes are usable on its delivery clock (the
    // frozen model's queue.arrive(addr, t, t): usable <= t). WR 0: the pops read the queue's
    // window (`avail`, this clock's delivery bypassed); WR 1: with the word register empty and
    // nothing stored, the pops read the arriving word directly (`arr`: the word register is
    // not loaded that clock), else the word register as before
    // (MX1e) V35_MX0B_WR 3: the word register empty, the pops and the staging load read the
    // queue's window directly (the stored head, and with the bypass the arriving word), and the
    // word register refills from the window's bytes left after them on the same clock
    // (MX5c) the bytes the pops can take (sn below) as a function of the word register's count,
    // the stored count and the window's: the same expression for this clock and the next
    function automatic logic [1:0] sn_f(input logic [1:0] w_n, input logic [2:0] st,
                                        input logic [2:0] av);
        logic       a;
        logic [2:0] wi, tt;
        a = (`V35_MX1D_ARRIVE && `V35_MX0B_WR != 0 && w_n == 2'd0 && st == 3'd0 && av != 3'd0)
            && `V35_MX0B_WR != 3;
        wi = `V35_MX1D_ARRIVE ? av : st;
        tt = {1'b0, w_n} + wi;
        sn_f = `V35_MX0B_WR == 3 ? (tt >= 3'd2 ? 2'd2 : 2'(tt))
             : (`V35_MX0B_WR == 0 || a) ? (wi >= 3'd2 ? 2'd2 : 2'(wi)) : w_n;
    endfunction
    wire       arr = (`V35_MX1D_ARRIVE && `V35_MX0B_WR != 0 && wn == 2'd0 && q_stored == 3'd0
                      && q_avail != 3'd0)
                     && `V35_MX0B_WR != 3;
    wire [2:0] win = `V35_MX1D_ARRIVE ? q_avail : q_stored;
    // (MX1e) WR 3: the byte source is the word register's bytes followed by the queue's window
    // (a FIFO: the word register first, the stored head, with the bypass the arriving word)
    wire       wr3 = `V35_MX0B_WR == 3;
    wire [7:0] sb0 = wr3 ? (wn != 2'd0 ? w0 : qv0)
                   : (`V35_MX0B_WR == 0 || arr) ? qv0 : w0;
    wire [7:0] sb1 = wr3 ? (wn == 2'd2 ? w1 : wn == 2'd1 ? qv0 : qv1)
                   : (`V35_MX0B_WR == 0 || arr) ? qv1 : w1;
    wire [1:0] sn = sn_f(wn, q_stored, q_avail);
    // the E word pops the staging register's opcode and, when the opcode has one, its ModR/M
    // byte from the queue's head (the opcode's decode from the staging register)
    // (MX5) the staging register's decode is a register beside it (`ds`: v35_udec1 of the byte
    // loaded into s_b, decoded in tick B from the ce_b registers and loaded with s_b at ce_a;
    // in reset with s_b, which a reset does not change): ds is v35_udec1(s_b) whenever s_v
    // (`+v35_chk`), and nothing reads it without s_v (the E pop stalls on an empty slot)
    v35_udec_t ds = '0;
    // (MX2) the E word pops the opcode's second byte with it: a ModR/M byte, or (the decode's e2)
    // a short transfer's displacement (into IL; the frozen model's take on the start clock)
    // (F5d) an E word with ea=REP pops the staged opcode alone (the REP page's second byte: its
    // ModR/M byte, displacement or 0F second byte stay in the queue for the cell's routine;
    // rep_nx refetches from the opcode); e_rep is the sequencer's registered word fact
    wire       ds2 = (ds.has_modrm || ds.e2 || ds.pg) && !e_rep;   // (MX3c) the 0F page's second byte
    assign q_stall = (wants_op && sn == 2'd0)
                     || (e_pop && (!s_v || (ds2 && sn == 2'd0)));
    // the lookups the function reads (registers and the queue's head byte: early in tick A)
    wire       o1 = wants_op && !flush_w;
    wire       m1 = e_pop && ds2;
    wire [2:0] t1 = (o1 ? 3'd1 : 3'd0) - need;
    function automatic logic z1_f(input logic [2:0] us, input logic [2:0] uo, input logic [2:0] ug);
        z1_f = flush_w
               || ((m1 && ds.e2) ? ds.len - 3'd1 == t1
                 : (m1 && ds.pg) ? ug == t1
                 : m1 ? us == t1 - ds.len
                 : e_pop ? ds.len == t1
                 : (o1 && pop == PP_MODRM) ? uo == t1
                 : (o1 && dispm && !dec1.has_modrm) ? ug == t1 : t1 == 3'd0);
    endfunction
    // (MX5b) the head byte's lookups formed per candidate source before the head select: `hd_f`
    // of each candidate (the queue's first stored byte, its latch, the delivered word's two
    // bytes, the word register's first byte), selected by the registered facts that select the
    // byte itself (the queue's seqb(0) and the loader's sb0 choice). The selected lookups are
    // hd_f(sb0) on every clock (`+v35_chk`); no lookup sits behind the select (README "MX5")
    typedef struct packed {
        logic [2:0] umr_s, umr_o, upg;
        logic [1:0] m76;
        logic       ecr, ecc;
        logic [UADDR_W-1:0] ech;
        logic       z;              // z1's compare for this byte (below)
    } v35_hd_t;
    // (MX5c) the head byte's facts of the byte alone are its tag (`bt_f`): the ModR/M byte's
    // displacement bytes (v35_umdsp), its reg field being 0 or 1 (mb[5:4] == 0), the 0F page's
    // second byte's added bytes (v35_upage) and the direct form (mod 00 rm 110). The tag is
    // formed on the delivered word (h_dlv, the bus unit's datum register) on its delivery clock
    // and stored by the queue beside each byte, through its storage and its latch (opaque bits
    // to the queue: dlv_tag, h_q0t, h_latt). The opcode's share of v35_umodrm (the form's
    // immediate bytes, v35_umimm of the opcode and r01) is a register beside s_b (`ims`) and
    // beside op (`imo`), loaded with them (as ds and d1r are). So umodrm(s_b, b) is
    // dsp(tag) + ims[r01(tag)] and no decode table sits between a stored candidate and z; the
    // delivered word's two bytes are decoded in tick A, the only content-dependent decode left
    // there. `+v35_chk` compares the head facts with the tables' and each stored tag with its
    // byte's. README "MX5" round 3
    typedef struct packed {
        logic [1:0] dsp;
        logic       r01;
        logic [1:0] upg;
        logic       edir;
    } v35_btag_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_btag_t bt_f(input logic [7:0] b);
        logic [2:0] d, g;
        d = v35_umdsp(b);
        g = v35_upage(b);
        bt_f.dsp = d[1:0];
        bt_f.r01 = b[5:4] == 2'd0;
        bt_f.upg = g[1:0];
        bt_f.edir = b[7:6] == 2'd0 && b[2:0] == 3'd6;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    // the opcode's share: {v35_umimm(o, 1), v35_umimm(o, 0)}
    function automatic logic [5:0] im_f(input logic [7:0] o);
        im_f = {v35_umimm(o, 1'b1), v35_umimm(o, 1'b0)};
    endfunction
    reg [5:0]  ims = 6'd0, imo = 6'd0;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_hd_t hd_f(input logic [7:0] b, input v35_btag_t t, input logic eab);
        hd_f.umr_s = {1'b0, t.dsp} + (t.r01 ? ims[5:3] : ims[2:0]);
        hd_f.umr_o = {1'b0, t.dsp} + (t.r01 ? imo[5:3] : imo[2:0]);
        hd_f.upg = {1'b0, t.upg};
        hd_f.m76 = b[7:6];
        hd_f.ecr = b[7:6] == 2'd3;
        hd_f.ecc = !hd_f.ecr && (b[7:6] != 2'd0 || t.edir || eab);
        hd_f.ech = b[7:6] == 2'd1 ? (eab ? UROM_EAB8 : UROM_EA8)
                 : (b[7:6] == 2'd2 && eab) ? UROM_EAB16
                 : (b[7:6] == 2'd2 || t.edir) ? UROM_EAD
                 : UROM_EAB0;
        hd_f.z = z1_f(hd_f.umr_s, hd_f.umr_o, hd_f.upg);
    endfunction
`ifndef SYNTHESIS
    // the reference (`+v35_chk`): the facts from the tables on the byte itself
    function automatic v35_hd_t hd_ref(input logic [7:0] b, input logic eab);
        logic edir;
        hd_ref.umr_s = v35_umodrm(s_b, b);
        hd_ref.umr_o = v35_umodrm(op, b);
        hd_ref.upg = v35_upage(b);
        hd_ref.m76 = b[7:6];
        edir = b[7:6] == 2'd0 && b[2:0] == 3'd6;
        hd_ref.ecr = b[7:6] == 2'd3;
        hd_ref.ecc = !hd_ref.ecr && (b[7:6] != 2'd0 || edir || eab);
        hd_ref.ech = b[7:6] == 2'd1 ? (eab ? UROM_EAB8 : UROM_EA8)
                   : (b[7:6] == 2'd2 && eab) ? UROM_EAB16
                   : (b[7:6] == 2'd2 || edir) ? UROM_EAD
                   : UROM_EAB0;
        hd_ref.z = z1_f(hd_ref.umr_s, hd_ref.umr_o, hd_ref.upg);
    endfunction
`endif
    /* verilator lint_on UNUSEDSIGNAL */
    // (F5t) the delivered word's tags are a register beside the bus unit's datum register,
    // loaded with the same enable from the same next value (tick B: the pins' sampled datum or
    // the on-chip read register), so no decode table sits between the delivered word and z1:
    // tg_lo / tg_hi are bt_f(h_dlv) on every clock (`+v35_chk`; the datum register starts at
    // FFFFh, bt_f(FFh) = 6'b000010). The datum register's twin: its enable is the CPU clock's
    // middle at a read's B3 (ce_mid, the edge ce_a shares), written as the datum register's
    // own block is. README "F5t"
    v35_btag_t tg_lo = v35_btag_t'(6'b000010), tg_hi = v35_btag_t'(6'b000010);
    always @(posedge clock) begin
        if (h_dlv_ld) begin
            tg_lo <= bt_f(h_dlv_nx[7:0]);
            tg_hi <= bt_f(h_dlv_nx[15:8]);
        end
    end
    assign dlv_tag = {tg_hi, tg_lo};
    // the head byte's source: 0 the queue's first stored byte, 1 its latch, 2 / 3 the delivered
    // word's low / high byte (seqb(0): stored bytes first, then the latch, then the arrival at
    // its parity), 4 the word register's first byte (sb0's choice above)
    wire [2:0] q_hs = q_stored != 3'd0 ? 3'd0 : h_latv ? 3'd1 : h_odd ? 3'd3 : 3'd2;
    wire [2:0] hs = wr3 ? (wn != 2'd0 ? 3'd4 : q_hs)
                  : (`V35_MX0B_WR == 0 || arr) ? q_hs : 3'd4;
    v35_hd_t hd0, hd1, hd2, hd3, hd4, hh;
    assign hh = hs == 3'd0 ? hd0 : hs == 3'd1 ? hd1 : hs == 3'd2 ? hd2 : hs == 3'd3 ? hd3 : hd4;
    wire [2:0] umr_s = hh.umr_s;
    wire [2:0] umr_o = hh.umr_o;
    wire [2:0] upg_s = hh.upg;
    wire   stg_free = `V35_MX1C_ROOM == 2 || (`V35_MX1C_ROOM != 0 && q_arrive);
    // (MX5) tick A's pops, the staging load and the room facts, as a function of the
    // sequencer's late bit `ex` (and the FLUSH it gates): `ta(x, fl)` is the code below with
    // ex = x and flush = fl, every other input a register or a register's lookup; the outputs
    // are `ex ? ta(1, flush_w) : ta(0, 0)` (Shannon's expansion on ex: the same function, the
    // late bit selecting last; flush is ex && the word's FLUSH, `+v35_chk`). README "MX5"
    typedef struct packed {
        logic       opop, epop, mpop, sload, wload, wload_d, hold_n, hold_r, hold2_n, stg, l_load;
        logic       e_rmodrm, resv_e;
        logic [1:0] np, wn_left, wk, tk_q;
        logic [2:0] need_n, rd, rel;
    } v35_lta_t;
    // (MX5c) the function's register inputs (and the head byte's lookups, read by need_n,
    // e_rmodrm and V35_MX3_IRL's wait only) as a struct: `ln` the facts as they stand, `lx`
    // their next values (tick B), for the registered outcomes below
    typedef struct packed {
        logic       wants_op, e_pop, dispm, d1hm, ds2;
        v35_pop_e   pop;
        v35_udec_t  ds;
        logic [2:0] need, q_stored, win, umr_s, umr_o, upg_s;
        logic       s_v, hold, hold2, arr, pc0, fhm, stg_free;
        logic [1:0] sn, wn, mr76, m76;
    } v35_lin_t;
    // (MX5) z: the bytes still owed after this clock are none (need_n == 0), passed in so that
    // the queue head's decode (the one late input of the function's ex = 1 case) selects between
    // two outcomes formed early; the callers pass the true value (`z1`, `+v35_chk`)
    function automatic v35_lta_t ta(input logic x, input logic fl, input logic z,
                                    input v35_lin_t L);
        logic [2:0] add, w_left;
        logic [1:0] tk_w, wk_w, wk_d;
        logic       s_left, irl_w, pcq_odd, wload_w;
        ta.opop = x && L.wants_op && !fl;
        ta.epop = x && L.e_pop;
        ta.mpop = ta.epop && L.ds2;               // ... and its second byte
        ta.resv_e = ta.epop && L.ds.rq;
        // (MX2) V35_MX2_TSM: a memory form's ModR/M pop arms the take sync as a register form's
        // does (the frozen model's take sync on the ModR/M take of every form: the EA clocks wait
        // for the word the pop's room asked for, F4-push-ld_bw_ix-k1-pO-w0..w2: the EA clocks
        // from the delivery at S + 3 + waits); in a memory form the sync gates the EA's add only
        // (v35_useq). (MX2) a short transfer's displacement popped by E arms it as a register
        // form's operand byte does (the frozen model's take sync on the displacement's take at
        // the start). (MX3c) the 0F page's second byte popped by E does not arm it (the frozen
        // model's chained take: the page's operand bytes follow, page_take=own); the ModR/M
        // byte's pop does (v35_useq)
        ta.e_rmodrm = ta.mpop && !L.ds.pg && (L.m76 == 2'd3 || `V35_MX2_TSM || L.ds.e2);
        add = (ta.mpop && L.ds.e2) ? L.ds.len - 3'd1
            : (ta.mpop && L.ds.pg) ? L.upg_s        // (MX3c) the second byte's ModR/M and immediate
            : ta.mpop ? L.ds.len + L.umr_s
            : ta.epop ? L.ds.len
            : (ta.opop && L.pop == PP_MODRM) ? L.umr_o
            : (ta.opop && L.dispm && !L.d1hm) ? L.upg_s : 3'd0;
        ta.need_n = fl ? 3'd0 : L.need + add - (ta.opop ? 3'd1 : 3'd0);
        s_left = L.s_v && !ta.epop;
        // (MX3) V35_MX3_IRL: the staging load waits a clock after the E word's ModR/M pop (the
        // frozen model's IR load a clock after a register form's ModR/M take, nx 1): 1 a
        // register-mode ModR/M, 2 any ModR/M or the E word's second byte (e2); 0 on the pop's
        // clock (MX2)
        irl_w = (`V35_MX3_IRL == 1 && ta.mpop && !L.ds.e2 && L.m76 == 2'd3)
                || (`V35_MX3_IRL == 2 && ta.mpop);
        ta.sload = !fl && !s_left && z && !irl_w
                   && L.sn > ((ta.opop || ta.mpop) ? 2'd1 : 2'd0);
        // the bytes popped this clock (an operand or the E word's ModR/M byte, the staging load)
        ta.np = ((ta.opop || ta.mpop) ? 2'd1 : 2'd0) + (ta.sload ? 2'd1 : 2'd0);
        // (WR 3) the bytes taken from the word register and from the window
        tk_w = ta.np > L.wn ? L.wn : ta.np;
        ta.tk_q = ta.np - tk_w;
        ta.wn_left = wr3 ? L.wn - tk_w : L.arr ? 2'd0 : L.wn - ta.np;
        // (MX0b) the word register's load: the queue head's aligned word (one byte from an odd
        // address), from the stored bytes, one load a clock
        pcq_odd = L.pc0 ^ ta.np[0] ^ ta.wn_left[0];     // the queue head's address parity
        wload_w = `V35_MX0B_WR != 0 && !wr3 && !fl && L.q_stored != 3'd0 && !L.arr
                  && (`V35_MX0B_WR != 2 ? ta.wn_left == 2'd0 : L.wn == 2'd0);
        wk_w = (pcq_odd || L.q_stored == 3'd1) ? 2'd1 : 2'd2;
        // (MX1e) WR 3's refill on a direct clock: the window's bytes after the np taken
        w_left = L.win - {1'b0, ta.tk_q};
        ta.wload_d = wr3 && ta.wn_left == 2'd0 && !fl && L.win > {1'b0, ta.tk_q};
        wk_d = (pcq_odd || w_left == 3'd1) ? 2'd1 : 2'd2;
        ta.wload = wload_w || ta.wload_d;
        ta.wk = ta.wload_d ? wk_d : wk_w;
        ta.l_load = `V35_MX0B_WR == 0 ? ta.sload : wr3 ? ta.wload
                  : (L.arr && !ta.wload_d) ? ta.sload : ta.wload;
        // the queue's port: the bytes leaving its storage (rd) and leaving the EU's room (rel);
        // the word register's bytes stay counted (unreleased) until popped
        ta.rd = `V35_MX0B_WR == 0 ? {1'b0, ta.np}
              : wr3 ? {1'b0, ta.tk_q} + (ta.wload_d ? {1'b0, wk_d} : 3'd0)
              : L.arr ? {1'b0, ta.np} + (ta.wload_d ? {1'b0, wk_d} : 3'd0)
              : (ta.wload ? {1'b0, ta.wk} : 3'd0);
        // (MX1f) V35_MX1C_ROOM 3: a take step's bytes released at the step's end (the frozen
        // model's take_commit=at_end: an immediate or a displacement word is one take step, its
        // low byte counted by the room until its high byte is popped). A low byte popped with
        // bytes still owed (IL; DL unless the ModR/M's mode is 01, the one-byte displacement) is
        // held; the next pop (or the E pop) releases it with its own
        ta.hold_n = `V35_MX1C_ROOM == 3 && ta.opop
                    && ((L.pop == PP_IL && !z)
                        || (L.pop == PP_DL && !z
                            && !(L.fhm && L.mr76 == 2'd1)));
        ta.hold_r = L.hold && (ta.opop || ta.mpop || ta.sload);
        // (MX2) V35_MX2_E2H: the E word's displacement byte (e2) stays counted on its pop's
        // clock and is released on the next (the take step's end)
        ta.hold2_n = `V35_MX2_E2H && ta.mpop && L.ds.e2;
        ta.rel = {1'b0, ta.np} - (ta.hold_n ? 3'd1 : 3'd0) + (ta.hold_r ? 3'd1 : 3'd0)
                 - (ta.hold2_n ? 3'd1 : 3'd0) + ((L.hold2 && !fl) ? 3'd1 : 3'd0);
        // (MX1c) V35_MX1C_ROOM: the staging slot while the running instruction owes bytes: 0
        // counted (MX0), 1 free on a word's arrival clock when the slot is empty (the frozen
        // model's room_ir=arrival_idle: the IR a seventh slot on an arrival clock), 2 free
        // whenever empty
        ta.stg = s_left || ta.sload || (!z && !L.stg_free);
    endfunction
    v35_lta_t lt0, lt1, ltx;
    // (MX5) z for ex = 1: need + add - opop == 0 (3 bits) is add == opop - need, each case's add
    // compared with that early target (the head byte's lookups compared, not summed)
    wire       z1 = hh.z;
    v35_lin_t  ln;
    always_comb begin
        ln.wants_op = wants_op;
        ln.e_pop = e_pop;
        ln.dispm = dispm;
        ln.d1hm = dec1.has_modrm;
        ln.ds2 = ds2;
        ln.pop = pop;
        ln.ds = ds;
        ln.need = need;
        ln.q_stored = q_stored;
        ln.win = win;
        ln.umr_s = umr_s;
        ln.umr_o = umr_o;
        ln.upg_s = upg_s;
        ln.s_v = s_v;
        ln.hold = hold;
        ln.hold2 = hold2;
        ln.arr = arr;
        ln.pc0 = pc[0];
        ln.fhm = fmt.has_modrm;
        ln.stg_free = stg_free;
        ln.sn = sn;
        ln.wn = wn;
        ln.mr76 = modrm[7:6];
        ln.m76 = hh.m76;
    end
    assign lt0 = ta(1'b0, 1'b0, need == 3'd0, ln);
    assign lt1 = z1 ? ta(1'b1, flush_w, 1'b1, ln) : ta(1'b1, flush_w, 1'b0, ln);
    assign ltx = ex ? lt1 : lt0;
    // (MX5c) the outcomes the queue's port, the bus unit's three strobes and the reservation
    // read, from registers: each of ta(1, flush_w, 1), ta(1, flush_w, 0) and ta(0, 0, need == 0)
    // reads registered state only (the head byte's lookups enter need_n, e_rmodrm and IRL's
    // wait, none of these), so each is a ce_a register loaded with ta of the facts' next values
    // (`lx`, tick B), in reset with ta of the facts as they stand. Tick A selects them by the
    // registered stall outcome (ex) and z1 (the head byte's compare, the one content-dependent
    // input): `ex ? (z1 ? lr1 : lr0) : lrx` is ltx's on every clock (`+v35_chk`). With
    // V35_MX3_IRL != 0 the staging load reads the head byte's mode: the outcomes are ltx's
    typedef struct packed {
        logic [2:0] rd, rel;
        logic       stg, l_load, opop, mpop, epop, resv_e;
    } v35_lrg_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_lrg_t lrg_f(input v35_lta_t t);
        lrg_f.rd = t.rd;
        lrg_f.rel = t.rel;
        lrg_f.stg = t.stg;
        lrg_f.l_load = t.l_load;
        lrg_f.opop = t.opop;
        lrg_f.mpop = t.mpop;
        lrg_f.epop = t.epop;
        lrg_f.resv_e = t.resv_e;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    localparam bit LRG = `V35_MX3_IRL == 0;
    v35_lrg_t  lr1 = '0, lr0 = '0, lrx = '0;
    v35_lrg_t  lrs, lrv;
    // (MX5c) z1 for these selects: z1_f's cases and targets read registered state only (the
    // word's pop fields and FLUSH, the staged opcode's decode, need, the opcode shares), so they
    // are a register (`zc`, loaded with zc_f of the next values, in reset of the values as they
    // stand); the head byte enters only through its tag (dsp, r01, upg): z1 is
    //   k || dsp == (r01 ? a1 : a0) || upg == g   (a1, a0, g: 3 when nothing matches)
    // `zt_f` is that compare for one candidate. The stored candidates' tags are registers (the
    // queue's); the delivered word's two bytes are decoded here, each compared, the head select
    // last. z1f is hh.z on every clock (`+v35_chk`)
    typedef struct packed {
        logic       k;
        logic [1:0] a1, a0;         // the dsp value that matches for r01 = 1 / 0 (3: none)
        logic [1:0] g;              // the upg value that matches (3 with t1 = 3; gv: any)
        logic       gv;
    } v35_zc_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_zc_t zc_f(input v35_lin_t l, input logic fw, input logic [5:0] s6,
                                     input logic [5:0] o6);
        logic       zo1, zm1, ce2, cpg, cus, cep, cuo, cug, cu;
        logic [2:0] zt1, ts, i1, i0, za1, za0;
        zo1 = l.wants_op && !fw;
        zm1 = l.e_pop && l.ds2;
        zt1 = (zo1 ? 3'd1 : 3'd0) - l.need;
        ce2 = zm1 && l.ds.e2;
        cpg = zm1 && !l.ds.e2 && l.ds.pg;
        cus = zm1 && !l.ds.e2 && !l.ds.pg;
        cep = !zm1 && l.e_pop;
        cuo = !zm1 && !l.e_pop && zo1 && l.pop == PP_MODRM;
        cug = !zm1 && !l.e_pop && !(zo1 && l.pop == PP_MODRM) && zo1 && l.dispm && !l.d1hm;
        zc_f.k = fw || (ce2 && l.ds.len - 3'd1 == zt1) || (cep && l.ds.len == zt1)
                 || (!zm1 && !l.e_pop && !(zo1 && l.pop == PP_MODRM)
                     && !(zo1 && l.dispm && !l.d1hm) && zt1 == 3'd0);
        cu = !fw && (cus || cuo);
        ts = cus ? zt1 - l.ds.len : zt1;
        i1 = cus ? s6[5:3] : o6[5:3];
        i0 = cus ? s6[2:0] : o6[2:0];
        za1 = ts - i1;
        za0 = ts - i0;
        zc_f.a1 = (cu && za1 <= 3'd2) ? za1[1:0] : 2'd3;
        zc_f.a0 = (cu && za0 <= 3'd2) ? za0[1:0] : 2'd3;
        zc_f.gv = !fw && (cpg || cug) && zt1 <= 3'd3;
        zc_f.g = zt1[1:0];
    endfunction
    function automatic logic zt_f(input v35_zc_t c, input v35_btag_t t);
        zt_f = c.k || (t.dsp == (t.r01 ? c.a1 : c.a0)) || (c.gv && t.upg == c.g);
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    v35_zc_t   zc = '0;
    // the head byte's candidates (hs, above): the stored ones' compares from their tags, each of
    // the delivered word's bytes decoded and compared, the head select last
    wire       z_st = hs == 3'd0 ? zt_f(zc, v35_btag_t'(h_q0t))
                    : hs == 3'd1 ? zt_f(zc, v35_btag_t'(h_latt)) : zt_f(zc, bt_f(w0));
    wire       z_lo = zt_f(zc, tg_lo);
    wire       z_hi = zt_f(zc, tg_hi);
    (* syn_keep = "true" *) wire z1f = hs == 3'd3 ? z_hi : hs == 3'd2 ? z_lo : z_st;
    // (ex, a register, selects first: the head byte's z1 last)
    (* syn_keep = "true" *) v35_lrg_t lrq1;
    (* syn_keep = "true" *) v35_lrg_t lrq0;
    assign lrq1 = ex ? lr1 : lrx;
    assign lrq0 = ex ? lr0 : lrx;
    assign lrs = z1f ? lrq1 : lrq0;
    assign lrv = LRG ? lrs : lrg_f(ltx);
    wire       opop = lrv.opop;
    wire       epop = lrv.epop;
    wire       mpop = lrv.mpop;
    assign o_pop = opop || mpop;
    assign o_epop = epop;
    assign resv_e = lrv.resv_e;
    assign s_modrm = s_v && ds.has_modrm;
    assign s_wbs = s_v && ds.wbs;
    assign e_rmodrm = ltx.e_rmodrm;
    wire unused = &{1'b0, ds, dm, q_avail, ltx.np};
    wire [2:0] need_n = ltx.need_n;
    wire       sload = ltx.sload;
    wire [1:0] wn_left = ltx.wn_left;
    wire [1:0] tk_q = ltx.tk_q;
    wire       wload_d = ltx.wload_d;
    wire       wload = ltx.wload;
    wire [1:0] wk = ltx.wk;
    wire [7:0] wl0 = !wload_d ? qv0 : tk_q == 2'd0 ? qv0 : tk_q == 2'd1 ? qv1 : qv2;
    wire [7:0] wl1 = !wload_d ? qv1 : tk_q == 2'd0 ? qv1 : tk_q == 2'd1 ? qv2 : qv3;
    assign l_load = lrv.l_load;
    assign rd = lrv.rd;
    wire       hold_n = ltx.hold_n;
    wire       hold_r = ltx.hold_r;
    wire       hold2_n = ltx.hold2_n;
    assign rel = lrv.rel;
    assign stg = lrv.stg;
    assign len = need_n;
    // (MX2) the instruction pointer: the staged opcode's offset, else the next queue byte's (a
    // routine reads it after its last pop: the bytes owed are none)
    assign ip = s_v ? s_ip : ipo;
    // (MX5b) the opcode register's decode is a register beside it, loaded with op's next value
    // at ce_a (in reset from op): dec1 is v35_udec1(op) on every clock (`+v35_chk`)
    v35_udec_t d1r = '0;
    assign dec1 = d1r;
    // (the second level's lookup stays behind the head select: replicated per candidate it maps
    // into 72 more RAM blocks; its reader is the DISPM target, README "MX5" round 2)
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
    wire       d2l = dec1.has_modrm || dec1.pg;    // (MX3c) the dispatch reads the second level
    // (MX5) the dispatch's facts are a function of op and mp alone (`dsp_f`), held in a register
    // beside them (`df`: loaded at ce_a from the values op and mp load, in reset from op and mp):
    // df is dsp_f(op, mp) on every clock (`+v35_chk`), so the next address reads a register
    typedef struct packed {
        logic [UADDR_W-1:0] ent, ret;
        logic               call, trap, eab, io;
    } v35_dsp_t;
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_dsp_t dsp_f(input logic [7:0] o, input logic [7:0] m);
        v35_udec_t  d1;
        v35_udecm_t d2;
        logic       mdir, mea, l2;
        logic [UADDR_W-1:0] hd;
        d1 = v35_udec1(o);
        d2 = v35_udec2(o, m);
        mdir = m[7:6] == 2'd0 && m[2:0] == 3'd6;
        mea = d1.has_modrm && d2.ea;
        l2 = d1.has_modrm || d1.pg;
        hd = m[7:6] == 2'd1 ? (d2.eab ? UROM_EAB8 : UROM_EA8)
           : (m[7:6] == 2'd2 && d2.eab) ? UROM_EAB16
           : (m[7:6] == 2'd2 || mdir) ? UROM_EAD
           : UROM_EAB0;
        dsp_f.call = mea && (m[7:6] != 2'd0 || mdir || d2.eab);
        dsp_f.ret = d2.entry;
        dsp_f.ent = !l2 ? d1.entry : dsp_f.call ? hd : d2.entry;
        dsp_f.trap = l2 ? d2.trap : d1.trap;
        dsp_f.eab = d2.eab;             // (the EAC word's head choice: dm.eab)
        dsp_f.io = l2 ? d2.io : d1.io;     // (F2b) an I/O form (no ModR/M: never a call)
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    v35_dsp_t df = '0;
    assign dcall = df.call;
    assign hd0 = hd_f(h_q0, v35_btag_t'(h_q0t), df.eab);
    assign hd1 = hd_f(h_lat, v35_btag_t'(h_latt), df.eab);
    assign hd2 = hd_f(h_dlv[7:0], tg_lo, df.eab);
    assign hd3 = hd_f(h_dlv[15:8], tg_hi, df.eab);
    assign hd4 = hd_f(w0, bt_f(w0), df.eab);
    assign dret = df.ret;
    // (F2b) the I/O trap: an I/O form (the decode's io: IN, OUT, INM, OUTM, the REP I/O strings)
    // with PSW.BRKI 0 dispatches to the trap's routine instead of its own: BRKI as the PSW
    // register stands while the dispatch word runs (after the previous instruction's E word's
    // writes: POP PSW's BRKI acts at once, f2_iot); a 2:1 select on two register bits
    assign dent = (df.io && !brki) ? UROM_IOT : df.ent;
    assign dtrap = df.trap;
    // (MX3c) the EAC word: the mode of the byte it pops (sb0) picks the register path or the EA
    // head of that mode, as `head` above does for the registered ModR/M (the mode's bits and the
    // routine's eab only)
    assign ec_reg = hh.ecr;
    assign ec_call = hh.ecc;
    assign ec_head = hh.ech;

    // ------------------------------------------------------------ (S7b) the ce_b registers
    reg        e2_b = 1'b0;
    reg [15:0] foff_b = 16'd0;
    reg        mpop_b = 1'b0, opop_b = 1'b0, epop_b = 1'b0, sload_b = 1'b0, flush_b = 1'b0, disp_b = 1'b0;
    reg        dispm_b = 1'b0;
    reg        erep_b = 1'b0;           // (F5d) the E pop re-enters the REP page
    v35_pop_e  pop_b = PP_NONE;
    reg [7:0]  qv0_b = 8'h00, qv1_b = 8'h00, sb0_b = 8'h00, sb1_b = 8'h00;
    reg        wload_b = 1'b0;
    reg [1:0]  wk_b = 2'd0, wn_left_b = 2'd0;
    reg [2:0]  need_b = 3'd0;
    reg        hold_nb = 1'b0, hold_rb = 1'b0;
    reg        hold2_b = 1'b0;
    reg [19:0] flin_b = 20'd0;
    v35_udec_t dec1_b = '0;
    reg [2:0]  op3m_b = 3'd0;
    reg        dmw_b = 1'b0;
    always_ff @(posedge clock) begin
        if (ce_b) begin
            opop_b <= opop;
            mpop_b <= mpop;
            e2_b <= ds.e2;
            foff_b <= flush_off;
            epop_b <= epop;
            erep_b <= epop && e_rep;
            sload_b <= sload;
            flush_b <= flush;
            disp_b <= disp;
            dispm_b <= ex && dispm;
            pop_b <= pop;
            qv0_b <= wl0;
            qv1_b <= wl1;
            sb0_b <= sb0;
            sb1_b <= sb1;
            wload_b <= wload;
            wk_b <= wk;
            wn_left_b <= wn_left;
            need_b <= need_n;
            hold_nb <= hold_n;
            hold_rb <= hold_r;
            hold2_b <= hold2_n;
            flin_b <= flush_lin;
            dec1_b <= dec1;
            op3m_b <= dispm ? dec2.op3 : d2l ? dm.op3 : dec1.op3;
            dmw_b <= dm.w;
        end
    end

    // ------------------------------------------------------------ the end of the clock (ce_a)
    wire [7:0] s_nb = (opop_b || mpop_b) ? sb1_b : sb0_b;     // the staging load's byte
    // (MX5c) the next values the sequencer's registered stall reads (tick B; the block below
    // loads s_v, ds, wn and d1r with exactly these): q_stall, s_modrm, s_wbs and the opcode
    // register's decode bits as they stand after the coming ce_a
    wire       s_v_nx = flush_b ? 1'b0 : sload_b ? 1'b1 : epop_b ? 1'b0 : s_v;
    v35_udec_t ds_nx;
    assign ds_nx = (!flush_b && sload_b) ? v35_udec1(s_nb) : ds;
    wire [1:0] wn_nx = flush_b ? 2'd0 : wload_b ? wk_b : wn_left_b;
    wire       arrive_nx = q_dlv_nx && !q_discard_nx;
    wire [3:0] av_w_nx = {1'b0, q_stored_nx} + {3'd0, q_latv_nx}
                         + (!arrive_nx ? 4'd0 : q_odd_nx ? 4'd1 : 4'd2);
    wire [2:0] av_nx = av_w_nx > 4'd7 ? 3'd7 : av_w_nx[2:0];
    wire [1:0] sn_nx = sn_f(wn_nx, q_stored_nx, av_nx);
    wire       ds2_nx = (ds_nx.has_modrm || ds_nx.e2 || ds_nx.pg) && !e_rep_nx;
    assign q_stall_nx = (pop_nx != PP_NONE && sn_nx == 2'd0)
                        || (e_pop_nx && (!s_v_nx || (ds2_nx && sn_nx == 2'd0)));
    assign s_modrm_nx = s_v_nx && ds_nx.has_modrm;
    assign s_wbs_nx = s_v_nx && ds_nx.wbs;
    // (MX5) the values op and mp load at ce_a (the dispatch facts' register reads them)
    // (F5d) an E word with ea=REP (a REP-page prefix cell's: REP seg / REP BUSLOCK) pops the
    // staged opcode into the ModR/M register and keeps the opcode register (the REP byte): the
    // dispatch reads the REP page's cell of the popped opcode (silicon, f5r repsegstr: REP
    // then segment prefixes and BUSLOCK, then a string opcode, repeats the string)
    wire [7:0] op_nx = (epop_b && !erep_b) ? s_b : op;
    wire [7:0] mp_nx = (mpop_b && !e2_b) ? sb0_b : erep_b ? s_b : mp;   // (exclusive: ds2 is 0 on erep)
    // (MX5b) opc, modrm and fmt load exactly these at ce_a (the block below assigns them)
    assign opc_nx = disp_b ? op : opc;
    assign modrm_nx = disp_b ? mp : (opop_b && pop_b == PP_MODRM) ? sb0_b : modrm;
    always_comb begin
        fmt_nx = fmt;
        if (disp_b) begin
            fmt_nx = dec1_b;
            if (dec1_b.pg)
                fmt_nx.w = dmw_b;   // (MX3c) the 0F form's width (the second level's)
        end
    end
    v35_udec_t d1_nx;
    assign d1_nx = v35_udec1(op_nx);
    assign d1_wbs_nx = d1_nx.wbs;
    assign d1_hm_nx = d1_nx.has_modrm;
    // the function's facts after the coming ce_a (the block below loads these)
    v35_lin_t  lx;
    always_comb begin
        lx = '0;                        // (the head byte's lookups: not read by lrg_f's fields)
        lx.wants_op = pop_nx != PP_NONE;
        lx.e_pop = e_pop_nx;
        lx.dispm = dispm_nx;
        lx.d1hm = d1_nx.has_modrm;
        lx.ds2 = ds2_nx;
        lx.pop = pop_nx;
        lx.ds = ds_nx;
        lx.need = need_b;
        lx.q_stored = q_stored_nx;
        lx.win = `V35_MX1D_ARRIVE ? av_nx : q_stored_nx;
        lx.s_v = s_v_nx;
        lx.hold = flush_b ? 1'b0 : hold_nb ? 1'b1 : hold_rb ? 1'b0 : hold;
        lx.hold2 = hold2_b && !flush_b;
        lx.arr = (`V35_MX1D_ARRIVE && `V35_MX0B_WR != 0 && wn_nx == 2'd0 && q_stored_nx == 3'd0
                  && av_nx != 3'd0) && `V35_MX0B_WR != 3;
        lx.pc0 = flush_b ? flin_b[0] : pc[0] ^ (opop_b || mpop_b) ^ sload_b;
        lx.fhm = fmt_nx.has_modrm;
        lx.stg_free = `V35_MX1C_ROOM == 2 || (`V35_MX1C_ROOM != 0 && q_dlv_nx);
        lx.sn = sn_nx;
        lx.wn = wn_nx;
        lx.mr76 = modrm_nx[7:6];
    end
    wire [5:0] ims_nx = (!flush_b && sload_b) ? im_f(s_nb) : ims;
    wire [5:0] imo_nx = im_f(op_nx);
    always_ff @(posedge clock) begin
        if (!reset_n)
            zc <= zc_f(ln, flush_w, ims, imo);
        else if (ce_a)
            zc <= zc_f(lx, flush_w_nx, ims_nx, imo_nx);
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            lr1 <= lrg_f(ta(1'b1, flush_w, 1'b1, ln));
            lr0 <= lrg_f(ta(1'b1, flush_w, 1'b0, ln));
            lrx <= lrg_f(ta(1'b0, 1'b0, need == 3'd0, ln));
        end else if (ce_a) begin
            lr1 <= lrg_f(ta(1'b1, flush_w_nx, 1'b1, lx));
            lr0 <= lrg_f(ta(1'b1, flush_w_nx, 1'b0, lx));
            lrx <= lrg_f(ta(1'b0, 1'b0, need_b == 3'd0, lx));
        end
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            df <= dsp_f(op, mp);
            d1r <= v35_udec1(op);
            imo <= im_f(op);
        end else if (ce_a) begin
            df <= dsp_f(op_nx, mp_nx);
            d1r <= d1_nx;
            imo <= imo_nx;
        end
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            ds <= v35_udec1(s_b);
            ims <= im_f(s_b);
            s_v <= 1'b0;
            pc <= reset_addr;
            s_a <= reset_addr;
            ipo <= reset_ip;
            s_ip <= reset_ip;
            need <= 3'd0;
            wn <= 2'd0;
            hold <= 1'b0;
            hold2 <= 1'b0;
        end else if (ce_a) begin
            fmt <= fmt_nx;
            opc <= opc_nx;
            modrm <= modrm_nx;
            hold2 <= hold2_b && !flush_b;
            need <= need_b;
            if (flush_b)
                hold <= 1'b0;
            else if (hold_nb)
                hold <= 1'b1;
            else if (hold_rb)
                hold <= 1'b0;
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
                ipo <= foff_b;
            end else begin
                pc <= pc + ((opop_b || mpop_b) ? 20'd1 : 20'd0) + (sload_b ? 20'd1 : 20'd0);
                ipo <= ipo + ((opop_b || mpop_b) ? 16'd1 : 16'd0) + (sload_b ? 16'd1 : 16'd0);
                if (sload_b) begin
                    s_v <= 1'b1;
                    s_b <= s_nb;
                    ds <= ds_nx;
                    ims <= ims_nx;
                    s_a <= pc + ((opop_b || mpop_b) ? 20'd1 : 20'd0);
                    s_ip <= ipo + ((opop_b || mpop_b) ? 16'd1 : 16'd0);
                end else if (epop_b)
                    s_v <= 1'b0;
            end
            if (epop_b && !erep_b) begin
                op <= s_b;
                op_a <= s_a;
                if (!fmt.seg[2])
                    ins_ip <= s_ip;
            end
            if (mpop_b && !e2_b)
                mp <= sb0_b;
            else if (erep_b)
                mp <= s_b;              // (F5d) the REP page's second byte (op_nx, mp_nx above)
            if (mpop_b && e2_b)
                il <= sb0_b;            // (MX2) the short transfer's displacement
            if (opop_b) begin
                case (pop_b)
                    PP_MODRM: ;                 // (modrm_nx)
                    PP_IL, PP_PORT: il <= sb0_b;
                    PP_IH: ih <= sb0_b;
                    PP_DL: dl <= sb0_b;
                    PP_DH: dh <= sb0_b;
                    default: ;
                endcase
            end
            if (disp_b) begin
                // (MX5b) fmt, opc and modrm: their next values (above)
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
            if ((s_v && ds !== v35_udec1(s_b)) || flush !== (ex && flush_w) || df !== dsp_f(op, mp) || hh !== hd_ref(sb0, df.eab) || d1r !== v35_udec1(op)
                || imo !== im_f(op) || (s_v && ims !== im_f(s_b))
                || (q_stored != 3'd0 && h_q0t !== bt_f(h_q0)) || (h_latv && h_latt !== bt_f(h_lat))
                || (ex ? z1 : need == 3'd0) !== (need_n == 3'd0)
                || opop_b !== opop || mpop_b !== mpop || e2_b !== ds.e2 || foff_b !== flush_off || epop_b !== epop || sload_b !== sload || flush_b !== flush
                || disp_b !== disp || dispm_b !== (ex && dispm) || pop_b !== pop
                || qv0_b !== wl0 || qv1_b !== wl1 || sb0_b !== sb0 || sb1_b !== sb1
                || wload_b !== wload || wk_b !== wk || wn_left_b !== wn_left || need_b !== need_n || hold_nb !== hold_n || hold_rb !== hold_r || hold2_b !== hold2_n || flin_b !== flush_lin
                || dec1_b !== dec1 || dmw_b !== dm.w) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader: a tick A source changed in tick B at %0t", $time);
            end
        end
    end
    // (MX5c) every clock: the registered outcomes against the function's
    always @(posedge clock) begin
        if (chk_on && reset_n && ((LRG && lrs !== lrg_f(ltx)) || z1f !== z1
                                  || tg_lo !== bt_f(h_dlv[7:0]) || tg_hi !== bt_f(h_dlv[15:8])
                                  || zc !== zc_f(ln, flush_w, ims, imo))) begin
            chk_n = chk_n + 1;
            if (chk_n <= 20)
                $display("v35 chk: loader: the registered outcomes differ at %0t", $time);
        end
    end
    final if (chk_on && chk_n != 0)
        $display("v35 chk: loader: %0d changes in tick B", chk_n);
    // +v35_ldbg=FILE: the loader's room facts each clock (bring-up; clock as the queue's qdbg)
    integer lfd = 0;
    string lfn;
    integer lt = 0;
    initial if ($value$plusargs("v35_ldbg=%s", lfn)) lfd = $fopen(lfn, "w");
    always @(posedge clock) begin
        if (lfd != 0 && reset_n && ce_a) begin
            $fdisplay(lfd, "l %0d wn %0d s_v %0d need %0d need_n %0d epop %0d opop %0d mpop %0d sload %0d np %0d rd %0d rel %0d stg %0d arrive %0d win %0d",
                      lt, wn, s_v, need, need_n, epop, opop, mpop, sload, ltx.np, rd, rel, stg, q_arrive, win);
            lt <= lt + 1;
        end
    end
    /* verilator lint_on BLKSEQ */
`endif
endmodule
