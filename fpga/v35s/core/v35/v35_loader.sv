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
    input  wire [7:0]  qv2,             // (MX1e) the window's third and fourth bytes (WR 3's refill)
    input  wire [7:0]  qv3,
    input  wire [2:0]  q_avail,
    input  wire [2:0]  q_stored,        // (MX0b) the queue's stored bytes (the load's source)
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
    output wire        s_wbs,           // (MX1f) the staged opcode's routine reads the accumulator first
    output wire        e_rmodrm,        // tick A: (MX1c) the E word pops a register-mode ModR/M
    // (MX3c) the EAC word (a 0F form's ModR/M byte popped by a routine word): the byte's mode
    // (tick A, from the byte popped): register mode (the routine's register path), and for a
    // memory mode the EA head to call (the routine's ea=book / bare by the second level's eab)
    output wire        ec_reg,
    output wire        ec_call,
    output wire [UADDR_W-1:0] ec_head,
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
    wire       arr = (`V35_MX1D_ARRIVE && `V35_MX0B_WR != 0 && wn == 2'd0 && q_stored == 3'd0
                      && q_avail != 3'd0)
                     && `V35_MX0B_WR != 3;
    wire [2:0] win = `V35_MX1D_ARRIVE ? q_avail : q_stored;
    // (MX1e) WR 3: the byte source is the word register's bytes followed by the queue's window
    // (a FIFO: the word register first, the stored head, with the bypass the arriving word)
    wire       wr3 = `V35_MX0B_WR == 3;
    wire [2:0] tot3 = {1'b0, wn} + win;
    wire [7:0] sb0 = wr3 ? (wn != 2'd0 ? w0 : qv0)
                   : (`V35_MX0B_WR == 0 || arr) ? qv0 : w0;
    wire [7:0] sb1 = wr3 ? (wn == 2'd2 ? w1 : wn == 2'd1 ? qv0 : qv1)
                   : (`V35_MX0B_WR == 0 || arr) ? qv1 : w1;
    wire [1:0] sn = wr3 ? (tot3 >= 3'd2 ? 2'd2 : 2'(tot3))
                  : (`V35_MX0B_WR == 0 || arr) ? (win >= 3'd2 ? 2'd2 : 2'(win)) : wn;
    // the E word pops the staging register's opcode and, when the opcode has one, its ModR/M
    // byte from the queue's head (the opcode's decode from the staging register)
    // (MX5) the staging register's decode is a register beside it (`ds`: v35_udec1 of the byte
    // loaded into s_b, decoded in tick B from the ce_b registers and loaded with s_b at ce_a;
    // in reset with s_b, which a reset does not change): ds is v35_udec1(s_b) whenever s_v
    // (`+v35_chk`), and nothing reads it without s_v (the E pop stalls on an empty slot)
    v35_udec_t ds = '0;
    // (MX2) the E word pops the opcode's second byte with it: a ModR/M byte, or (the decode's e2)
    // a short transfer's displacement (into IL; the frozen model's take on the start clock)
    wire       ds2 = ds.has_modrm || ds.e2 || ds.pg;   // (MX3c) the 0F page's second byte
    assign q_stall = (wants_op && sn == 2'd0)
                     || (e_pop && (!s_v || (ds2 && sn == 2'd0)));
    // the lookups the function reads (registers and the queue's head byte: early in tick A)
    wire [2:0] umr_s = v35_umodrm(s_b, sb0);
    wire [2:0] umr_o = v35_umodrm(op, sb0);
    wire [2:0] upg_s = v35_upage(sb0);
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
    // (MX5) z: the bytes still owed after this clock are none (need_n == 0), passed in so that
    // the queue head's decode (the one late input of the function's ex = 1 case) selects between
    // two outcomes formed early; the callers pass the true value (`z1`, `+v35_chk`)
    function automatic v35_lta_t ta(input logic x, input logic fl, input logic z);
        logic [2:0] add, w_left;
        logic [1:0] tk_w, wk_w, wk_d;
        logic       s_left, irl_w, pcq_odd, wload_w;
        ta.opop = x && wants_op && !fl;
        ta.epop = x && e_pop;
        ta.mpop = ta.epop && ds2;               // ... and its second byte
        ta.resv_e = ta.epop && ds.rq;
        // (MX2) V35_MX2_TSM: a memory form's ModR/M pop arms the take sync as a register form's
        // does (the frozen model's take sync on the ModR/M take of every form: the EA clocks wait
        // for the word the pop's room asked for, F4-push-ld_bw_ix-k1-pO-w0..w2: the EA clocks
        // from the delivery at S + 3 + waits); in a memory form the sync gates the EA's add only
        // (v35_useq). (MX2) a short transfer's displacement popped by E arms it as a register
        // form's operand byte does (the frozen model's take sync on the displacement's take at
        // the start). (MX3c) the 0F page's second byte popped by E does not arm it (the frozen
        // model's chained take: the page's operand bytes follow, page_take=own); the ModR/M
        // byte's pop does (v35_useq)
        ta.e_rmodrm = ta.mpop && !ds.pg && (sb0[7:6] == 2'd3 || `V35_MX2_TSM || ds.e2);
        add = (ta.mpop && ds.e2) ? ds.len - 3'd1
            : (ta.mpop && ds.pg) ? upg_s        // (MX3c) the second byte's ModR/M and immediate
            : ta.mpop ? ds.len + umr_s
            : ta.epop ? ds.len
            : (ta.opop && pop == PP_MODRM) ? umr_o
            : (ta.opop && dispm && !dec1.has_modrm) ? upg_s : 3'd0;
        ta.need_n = fl ? 3'd0 : need + add - (ta.opop ? 3'd1 : 3'd0);
        s_left = s_v && !ta.epop;
        // (MX3) V35_MX3_IRL: the staging load waits a clock after the E word's ModR/M pop (the
        // frozen model's IR load a clock after a register form's ModR/M take, nx 1): 1 a
        // register-mode ModR/M, 2 any ModR/M or the E word's second byte (e2); 0 on the pop's
        // clock (MX2)
        irl_w = (`V35_MX3_IRL == 1 && ta.mpop && !ds.e2 && sb0[7:6] == 2'd3)
                || (`V35_MX3_IRL == 2 && ta.mpop);
        ta.sload = !fl && !s_left && z && !irl_w
                   && sn > ((ta.opop || ta.mpop) ? 2'd1 : 2'd0);
        // the bytes popped this clock (an operand or the E word's ModR/M byte, the staging load)
        ta.np = ((ta.opop || ta.mpop) ? 2'd1 : 2'd0) + (ta.sload ? 2'd1 : 2'd0);
        // (WR 3) the bytes taken from the word register and from the window
        tk_w = ta.np > wn ? wn : ta.np;
        ta.tk_q = ta.np - tk_w;
        ta.wn_left = wr3 ? wn - tk_w : arr ? 2'd0 : wn - ta.np;
        // (MX0b) the word register's load: the queue head's aligned word (one byte from an odd
        // address), from the stored bytes, one load a clock
        pcq_odd = pc[0] ^ ta.np[0] ^ ta.wn_left[0];     // the queue head's address parity
        wload_w = `V35_MX0B_WR != 0 && !wr3 && !fl && q_stored != 3'd0 && !arr
                  && (`V35_MX0B_WR != 2 ? ta.wn_left == 2'd0 : wn == 2'd0);
        wk_w = (pcq_odd || q_stored == 3'd1) ? 2'd1 : 2'd2;
        // (MX1e) WR 3's refill on a direct clock: the window's bytes after the np taken
        w_left = win - {1'b0, ta.tk_q};
        ta.wload_d = wr3 && ta.wn_left == 2'd0 && !fl && win > {1'b0, ta.tk_q};
        wk_d = (pcq_odd || w_left == 3'd1) ? 2'd1 : 2'd2;
        ta.wload = wload_w || ta.wload_d;
        ta.wk = ta.wload_d ? wk_d : wk_w;
        ta.l_load = `V35_MX0B_WR == 0 ? ta.sload : wr3 ? ta.wload
                  : (arr && !ta.wload_d) ? ta.sload : ta.wload;
        // the queue's port: the bytes leaving its storage (rd) and leaving the EU's room (rel);
        // the word register's bytes stay counted (unreleased) until popped
        ta.rd = `V35_MX0B_WR == 0 ? {1'b0, ta.np}
              : wr3 ? {1'b0, ta.tk_q} + (ta.wload_d ? {1'b0, wk_d} : 3'd0)
              : arr ? {1'b0, ta.np} + (ta.wload_d ? {1'b0, wk_d} : 3'd0)
              : (ta.wload ? {1'b0, ta.wk} : 3'd0);
        // (MX1f) V35_MX1C_ROOM 3: a take step's bytes released at the step's end (the frozen
        // model's take_commit=at_end: an immediate or a displacement word is one take step, its
        // low byte counted by the room until its high byte is popped). A low byte popped with
        // bytes still owed (IL; DL unless the ModR/M's mode is 01, the one-byte displacement) is
        // held; the next pop (or the E pop) releases it with its own
        ta.hold_n = `V35_MX1C_ROOM == 3 && ta.opop
                    && ((pop == PP_IL && !z)
                        || (pop == PP_DL && !z
                            && !(fmt.has_modrm && modrm[7:6] == 2'd1)));
        ta.hold_r = hold && (ta.opop || ta.mpop || ta.sload);
        // (MX2) V35_MX2_E2H: the E word's displacement byte (e2) stays counted on its pop's
        // clock and is released on the next (the take step's end)
        ta.hold2_n = `V35_MX2_E2H && ta.mpop && ds.e2;
        ta.rel = {1'b0, ta.np} - (ta.hold_n ? 3'd1 : 3'd0) + (ta.hold_r ? 3'd1 : 3'd0)
                 - (ta.hold2_n ? 3'd1 : 3'd0) + ((hold2 && !fl) ? 3'd1 : 3'd0);
        // (MX1c) V35_MX1C_ROOM: the staging slot while the running instruction owes bytes: 0
        // counted (MX0), 1 free on a word's arrival clock when the slot is empty (the frozen
        // model's room_ir=arrival_idle: the IR a seventh slot on an arrival clock), 2 free
        // whenever empty
        ta.stg = s_left || ta.sload || (!z && !stg_free);
    endfunction
    v35_lta_t lt0, lt1, ltx;
    // (MX5) z for ex = 1: need + add - opop == 0 (3 bits) is add == opop - need, each case's add
    // compared with that early target (the head byte's lookups compared, not summed)
    wire       o1 = wants_op && !flush_w;
    wire       m1 = e_pop && ds2;
    wire [2:0] t1 = (o1 ? 3'd1 : 3'd0) - need;
    wire       z1 = flush_w
                    || ((m1 && ds.e2) ? ds.len - 3'd1 == t1
                      : (m1 && ds.pg) ? upg_s == t1
                      : m1 ? umr_s == t1 - ds.len
                      : e_pop ? ds.len == t1
                      : (o1 && pop == PP_MODRM) ? umr_o == t1
                      : (o1 && dispm && !dec1.has_modrm) ? upg_s == t1 : t1 == 3'd0);
    assign lt0 = ta(1'b0, 1'b0, need == 3'd0);
    assign lt1 = z1 ? ta(1'b1, flush_w, 1'b1) : ta(1'b1, flush_w, 1'b0);
    assign ltx = ex ? lt1 : lt0;
    wire       opop = ltx.opop;
    wire       epop = ltx.epop;
    wire       mpop = ltx.mpop;
    assign o_pop = opop || mpop;
    assign o_epop = epop;
    assign resv_e = ltx.resv_e;
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
    assign l_load = ltx.l_load;
    assign rd = ltx.rd;
    wire       hold_n = ltx.hold_n;
    wire       hold_r = ltx.hold_r;
    wire       hold2_n = ltx.hold2_n;
    assign rel = ltx.rel;
    assign stg = ltx.stg;
    assign len = need_n;
    // (MX2) the instruction pointer: the staged opcode's offset, else the next queue byte's (a
    // routine reads it after its last pop: the bytes owed are none)
    assign ip = s_v ? s_ip : ipo;
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
    wire       d2l = dec1.has_modrm || dec1.pg;    // (MX3c) the dispatch reads the second level
    // (MX5) the dispatch's facts are a function of op and mp alone (`dsp_f`), held in a register
    // beside them (`df`: loaded at ce_a from the values op and mp load, in reset from op and mp):
    // df is dsp_f(op, mp) on every clock (`+v35_chk`), so the next address reads a register
    typedef struct packed {
        logic [UADDR_W-1:0] ent, ret;
        logic               call, trap, eab;
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
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    v35_dsp_t df = '0;
    assign dcall = df.call;
    assign dret = df.ret;
    assign dent = df.ent;
    assign dtrap = df.trap;
    // (MX3c) the EAC word: the mode of the byte it pops (sb0) picks the register path or the EA
    // head of that mode, as `head` above does for the registered ModR/M (the mode's bits and the
    // routine's eab only)
    wire       e_dir = sb0[7:6] == 2'd0 && sb0[2:0] == 3'd6;
    assign ec_reg = sb0[7:6] == 2'd3;
    assign ec_call = !ec_reg && (sb0[7:6] != 2'd0 || e_dir || df.eab);
    assign ec_head = sb0[7:6] == 2'd1 ? (df.eab ? UROM_EAB8 : UROM_EA8)
                   : (sb0[7:6] == 2'd2 && df.eab) ? UROM_EAB16
                   : (sb0[7:6] == 2'd2 || e_dir) ? UROM_EAD
                   : UROM_EAB0;

    // ------------------------------------------------------------ (S7b) the ce_b registers
    reg        e2_b = 1'b0;
    reg [15:0] foff_b = 16'd0;
    reg        mpop_b = 1'b0, opop_b = 1'b0, epop_b = 1'b0, sload_b = 1'b0, flush_b = 1'b0, disp_b = 1'b0;
    reg        dispm_b = 1'b0;
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
    // (MX5) the values op and mp load at ce_a (the dispatch facts' register reads them)
    wire [7:0] op_nx = epop_b ? s_b : op;
    wire [7:0] mp_nx = (mpop_b && !e2_b) ? sb0_b : mp;
    always_ff @(posedge clock) begin
        if (!reset_n)
            df <= dsp_f(op, mp);
        else if (ce_a)
            df <= dsp_f(op_nx, mp_nx);
    end
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            ds <= v35_udec1(s_b);
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
                    ds <= v35_udec1(s_nb);
                    s_a <= pc + ((opop_b || mpop_b) ? 20'd1 : 20'd0);
                    s_ip <= ipo + ((opop_b || mpop_b) ? 16'd1 : 16'd0);
                end else if (epop_b)
                    s_v <= 1'b0;
            end
            if (epop_b) begin
                op <= s_b;
                op_a <= s_a;
            end
            if (mpop_b && !e2_b)
                mp <= sb0_b;
            if (mpop_b && e2_b)
                il <= sb0_b;            // (MX2) the short transfer's displacement
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
                if (dec1_b.pg)
                    fmt.w <= dmw_b;     // (MX3c) the 0F form's width (the second level's)
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
            if ((s_v && ds !== v35_udec1(s_b)) || flush !== (ex && flush_w) || df !== dsp_f(op, mp)
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
