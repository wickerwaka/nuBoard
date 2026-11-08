`timescale 1ns/1ps
`include "v35_macros.svh"

// V35S core v2: the loader (docs/v35s-core-v2.md, "Modules and the state they own"; Appendix B
// §1 "Loader / IR"): the opcode register (IR, a seventh byte outside the queue), the format
// lookup (the generated decode table: v35_pkg::v35_fmt_of, the ModR/M byte the next queue
// byte), the operand-take handshake with the queue (one byte per clock, two for a word
// displacement), `need`, the ready countdown for the next IR load, the ModR/M commit strobe and
// the word-mate strobe, and the decode a clock ahead: the format of the form the next clock
// may start (its IR, or the queue's head byte when the IR is empty, with the ModR/M byte that
// will be stored behind it), which the sequencer's ROM window and the datapath's register
// ports are addressed from. The take decisions are the EU's (it asks for its bytes now); the
// loader grants them.
//
// Stage map:
//   S2  T: the start (the IR consumed, need/nx/ModR/M loaded), the EU's take
//   S3  L: the IR load (load_ir: no operand bytes outstanding, the class's nx clocks passed)
//   S5  P: the second pass's start, take (one byte at most) and IR load
//   S6  the next state; the decode ahead
//
// Registered state (widths) and the model variables it replaces:
//   ir_v 1, ir 8, ir_addr 20      decoder.ir (the opcode and, for the trace, its address)
//   opc 8                         the running form's opcode (the ModR/M take's re-decode)
//   need 3                        decoder.need
//   nx 3                          decoder.nx (the running form's class integer)
//   ra 5                          decoder.ready_at as a countdown (ready_at - t at the next clock)
//   modrm_next 1                  decoder.modrm_next
//   stopped 1                     decoder.stopped (HALT)
//   ir_hold 1                     decoder.ir_hold (ir_load=disp_data: set at a displaced memory
//                                 form's start, cleared by its displacement's take on a delivery
//                                 clock or its first data cycle's issue; S4)
//   (S5b) pg 1, mskip 1           the running form is a 0F-page form (opc then holds its second
//                                 byte: the ModR/M take's re-decode on page 1);
//                                 decoder.modrm_skip (its second opcode byte not yet taken: the
//                                 next take is not the ModR/M byte)
//   (ea_end: the sequencer's countdown; lea_wait: S5a's lea_xk)
//
// (S5b) The 0F page. An escape byte 0F in the IR is the page's first byte: the form's format is
// v35_fmt_of(the queue's head byte, page 1, the byte behind it as the ModR/M byte) (the IR
// after L likewise with the bytes after its own; the decode ahead with the bytes after the IR,
// or after the head byte when the IR is empty and loads next clock). The second opcode byte is
// the form's first operand take (page_take=own: a chained take on its start clock); the
// ModR/M byte is the take after it (modrm_skip), its re-decode v35_fmt_of(the second byte, page
// 1, the ModR/M byte). A start whose bytes are not stored yet decodes what the window holds;
// its ModR/M take re-decodes the form (the template stays the start's: Divergence 2's way);
// the decode ahead aims the ROM window and the register ports at the template of the bytes
// stored (or delivered) by the clock's end, and a start whose decode was not known a clock
// ahead waits (W_DEC, counted by +v35_diag).
module v35_loader
    import v35_front_pkg::*;
    import v35_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce_a,
    input  wire        ce_b,          // (S7b) the CPU clock's second tick (the pipeline registers)

    // the queue's head window (S1) and its address
    // the queue's head window and count (S1: this clock's delivery bypassed)
    input  wire [7:0]  qv0, qv1, qv2, qv3,
    input  wire [2:0]  q_avail,
    // (Q1) the queue's read / release split: the bytes the EU reads leave the queue's storage
    // at once (`rd`), and stop counting for its room when released (`rel`): a take step's bytes
    // when it ends (take_commit=at_end, as a uniform loader rule), a ModR/M byte and the opcode
    // when read (modrm_commit=byte, the IR load); the IR is the queue's staging byte (`stg`)
    input  wire        t_done,          // the T pass's take step ended (its bytes committed)
    input  wire        p_done,          // ... the P pass's
    input  wire        dlv,             // a fetch's word delivered now (the bus unit's)
    output wire [2:0]  rd,              // the bytes read: tick A (T, L), tick B (P)
    output wire [2:0]  rd_b,
    output wire [2:0]  rel,             // the bytes released (tick A; the P pass's a clock later)
    output wire        stg,             // the IR (the staging byte) holds an opcode after L
    output wire [7:0]  ev0, ev1, ev2, ev3,  // the EU's window (the queue's)
    output wire [2:0]  e_avail,         // ... its bytes
    // (Q1) the PC of the queue's head byte is the loader's: the reset's first fetch address, a
    // flush's target, then counted up by the bytes taken
    input  wire [19:0] reset_addr,
    input  wire [19:0] t_flush_addr,

    // S2 (T) from the EU
    input  wire        t_start,
    input  wire [1:0]  t_k_in,          // the bytes the EU takes now (it asked: min(left, ...))
    input  wire        t_flush,
    input  wire        t_halt,
    input  wire        lx_hold,         // long_exec: the ready countdown holds a clock
    input  wire        idle_adj,        // one_idle: the ready countdown a clock less
    // S5 (P) from the EU
    input  wire        p_start,
    input  wire        p_k_in,
    input  wire        p_io_nx,         // io_take_nx: the IR load a clock later
    // ir_load=disp_data (S4): set at a displaced memory form's start (T, P), cleared by its
    // displacement's take on a delivery clock (T, P) or its data cycle's issue (S4)
    input  wire        irh_set_t,
    input  wire        irh_clr_t,
    input  wire        disp_tk,         // (R3) a memory form's displacement (last byte) taken (T)
    input  wire        lea_room,        // (R3) LDEA's EA clocks after its last operand byte (T)
    input  wire        mate,            // (R3) the ModR/M byte's word-mate taken on its delivery (T)
    input  wire        eu_issue,
    input  wire        irh_set_p,
    input  wire        irh_clr_p,
    // (S5b) page_ir=delivery: a 0F memory form's last operand byte taken on a word's delivery
    // clock: its successor stays out of the IR until the read issues (T, P)
    input  wire        irh_pg_t,
    input  wire        irh_pg_p,
    // (S5b) page_mtake=eu: the ModR/M take waited this many clocks: the ready countdown the
    // last operand take loads is that much shorter (decoder.ready_at -= page_mt - page_mt_d)
    input  wire [3:0]  mt_sub_t,
    input  wire [3:0]  mt_sub_p,

    // the IR (before S2)
    output wire        ir_v_c,
    output wire [7:0]  ir_c,
    output wire [19:0] ir_addr_c,
    output v35_fmt_t   fmt_c,           // the IR's format (its ModR/M byte the head byte)
    output wire        ok_c,            // (S7) ... known (the opcode's table entry decoded a
                                        //   clock ahead: the start waits a clock if not)
    output v35_cls_t   cls_c,           // ... its class constants
    output v35_fmt_t   fmt_mt,          // the running form (started before this clock)
                                        // re-decoded at a T ModR/M take (the head byte)
    // S2
    // S3
    output wire        l_pop,           // (Q1) the IR's byte left the window in L (popped)
    output wire        l_load,          // (Q1) the IR loaded in L (decoder.load_ir)
    output wire [7:0]  ir_l,
    output wire [19:0] ir_addr_l,
    output v35_fmt_t   fmt_l,
    output wire        ok_l,            // (S7) ... known
    output wire        ir_v_l,
    // S5
    output v35_fmt_t   fmt_mp,          // the form running after T re-decoded at a P take
                                        //   ((S7) not built: the T re-decode's; see p_mmiss)
    output wire        p_mmiss,         // (S7) a P take of a running form's ModR/M byte: none
                                        //   on the corpus (+v35_diag reports one)
    output wire        p_ir,            // (Q1) the IR's byte left the window in P (popped)
    output wire        p_load,          // (Q1) the IR loaded in P
    output wire        ir_v_p,
    output wire        stopped_o,
    output wire        head_odd,
    output wire [2:0]  need_t,          // (Q1) the operand bytes still to take after T (susp)        // (Q1) the head byte is at an odd address (the PC's bit 0)
    // S6: the decode ahead (the next clock's IR, or head byte, and its format)
    output wire        nf_v,
    output v35_fmt_t   nf_fmt,
    output wire [7:0]  nf_op,
    output wire [19:0] nf_addr
);
    // ------------------------------------------------------------ registered state
    reg        ir_v = 1'b0;
    reg [7:0]  ir = 8'h00;
    reg [19:0] ir_addr = 20'd0;
    reg [7:0]  opc = 8'h00;
    reg [2:0]  need = 3'd0;
    reg [2:0]  nx = 3'd0;
    reg [4:0]  ra = 5'd0;
    reg        modrm_next = 1'b0;
    reg        stopped = 1'b0;
    reg        irh = 1'b0;
    reg [19:0] pc = 20'd0;             // (Q1) the next byte's address (the EU's read position)
    reg [1:0]  unc = 2'd0;             // (Q1) bytes read by a take step not yet ended (released)
    reg [2:0]  relc = 3'd0;            // (Q1) the P pass's released bytes, for the next clock
    wire [19:0] head_addr = pc;
    wire [7:0] vb0 = qv0, vb1 = qv1, vb2 = qv2, vb3 = qv3;
    wire [2:0] avail_c = q_avail;
    wire [3:0] avail4 = {1'b0, avail_c};
    assign ev0 = vb0;
    assign ev1 = vb1;
    assign ev2 = vb2;
    assign ev3 = vb3;
    assign e_avail = avail_c;
    reg        pg = 1'b0;               // (S5b) the running form is on the 0F page
    reg        mskip = 1'b0;            // (S5b) its second opcode byte is still to take

    assign stopped_o = stopped;
    assign head_odd = pc[0];
    assign need_t = need_t_w;
    assign ir_v_c = ir_v;
    assign ir_c = ir;
    assign ir_addr_c = ir_addr;
    // (S5a) a REP prefix (escape 2) in the IR: the form is the string opcode behind it (page 2,
    // the opcode the next byte), its repc the prefix's; (S5b) the 0F escape (escape 1): the
    // 0F page's form of the next byte (page 1), the byte after it its ModR/M byte.
    // (S7) The decode tables are read once a clock, by the decode ahead (S6): the opcode's
    // table entry (v35_dec_native, v35_dec_ext on the 0F page, a REP prefix's string opcode's)
    // is registered with the opcode, the page and the prefix's repc (`pd_*`) for the form the
    // next clock holds (its IR, or the queue's head byte when the IR is empty); the format of
    // the IR (`fmt_c`, and `fmt_l`, the IR after L) is assembled from that entry and the
    // ModR/M byte as it stands (v35_fmt_asm: the group table and the ModR/M fields), the
    // running form's re-decodes at its ModR/M take from the entry registered at its start
    // (`d_run`). A format whose entry was not decoded a clock ahead (an escape whose second
    // byte had not arrived; an IR loaded after T's takes) is not known (`ok_c`, `ok_l`): its
    // start waits (W_DEC, counted by +v35_diag).
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic v35_fmt_t dec_asm(input logic [7:0] o, input logic [1:0] page,
                                         input v35_dec_t d, input logic [1:0] rc,
                                         input logic [7:0] modrm);
        v35_fmt_t f;
        f = v35_fmt_asm(o, page, d, page == 2'd2 ? 8'h00 : modrm);
        if (page == 2'd2)
            f.repc = rc;
        return f;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    // the decode ahead's registers: the next clock's form's opcode table entry
    reg        pd_v = 1'b0;             // the opcode (and an escape's second byte) known
    reg [1:0]  pd_pg = 2'd0;            // its page
    reg [7:0]  pd_op = 8'h00;           // the opcode the entry is of (an escape's second byte)
    reg [1:0]  pd_rc = 2'd0;            // a REP prefix's repc
    v35_dec_t  pd_d = '0;               // the entry
    v35_dec_t  d_run = '0;              // the running form's entry (from its start)
    // the IR's form (or the head byte's when the IR is empty and L loads it before any take)
    wire [7:0] a1_modrm = pd_pg == 2'd1 ? (ir_v ? vb1 : vb2) : (ir_v ? vb0 : vb1);
    v35_fmt_t a1;
    assign a1 = dec_asm(pd_op, pd_pg, pd_d, pd_rc, a1_modrm);
    assign fmt_c = a1;
    assign ok_c = pd_v;
    v35_cls_t c_cls;
    assign c_cls = v35_cls_const(a1.cls);
    assign cls_c = c_cls;

    function automatic logic [7:0] vb(input logic [2:0] k);
        case (k)
            3'd0: vb = vb0;
            3'd1: vb = vb1;
            3'd2: vb = vb2;
            default: vb = vb3;
        endcase
    endfunction

    // ------------------------------------------------------------ S2 (T)
    // the start: decoder.start (the IR consumed; need, nx, ModR/M; ready_at = t + nx0)
    wire [2:0] need_s = t_start ? fmt_c.len - 3'd1 : need;
    wire [2:0] nx_s = t_start ? c_cls.nx : nx;
    wire       mn_s = t_start ? fmt_c.has_modrm : modrm_next;
    // (S5b) the 0F page: the second opcode byte is taken before the ModR/M byte
    wire       pg_s = t_start ? fmt_c.page == 2'd1 : pg;
    wire       ms_s = t_start ? (fmt_c.page == 2'd1 && fmt_c.has_modrm) : mskip;
    wire       ir_s = (t_start || t_flush) ? 1'b0 : ir_v;    // (S5a) a flush empties the IR
    wire [7:0] op_s = t_start ? ir : opc;
    wire       ra_ld_s = t_start;
    wire [4:0] ra_v_s = (fmt_c.len == 3'd1) ? c_cls.nx0 : 5'd0;
    // the take (the EU's)
    wire [2:0] k_t = {1'b0, t_k_in};
    wire modrm_tk = k_t != 3'd0 && mn_s && !ms_s;
    wire ms_t = ms_s && k_t == 3'd0;
    // (Q1) tick A's pops: a take step's bytes at its end, a ModR/M byte at once, the IR load
    // (the held byte, read first, was popped already)
    wire [2:0] unc_t = t_flush ? 3'd0 : (t_done ? 3'd0 : 3'(unc) + k_t - (modrm_tk ? 3'd1 : 3'd0));
    wire [2:0] rel_t0 = t_done ? 3'(unc) + k_t : (modrm_tk ? 3'd1 : 3'd0);
    // (S5b) the 0F page's second opcode byte taken now: the opcode the ModR/M take re-decodes
    wire [7:0] opc_t = (k_t != 3'd0 && ms_s) ? vb0 : op_s;
    // the ModR/M byte taken: the form's length as it decodes ((S5b) a 0F form's second opcode
    // byte was taken before it: less that byte too)
    v35_fmt_t fm_r, fm_t;
    assign fm_r = v35_fmt_asm(opc, {1'b0, pg}, d_run, vb0);
    assign fmt_mt = fm_r;
    assign fm_t = t_start ? fmt_c : fm_r;
    wire [2:0] need_t_w = modrm_tk ? fm_t.len - 3'd1 - k_t - (pg_s ? 3'd1 : 3'd0)
                                   : need_s - k_t;
    // ready_at: t + nx at the last operand take
    wire ra_ld_t = (k_t != 3'd0 && need_t_w == 3'd0) || ra_ld_s;
    // (S5b) page_mtake=eu: less the clocks the ModR/M take waited
    wire [4:0] ra_v_t = (k_t != 3'd0 && need_t_w == 3'd0)
                        ? ({2'd0, nx_s} > {1'b0, mt_sub_t} ? {2'd0, nx_s} - {1'b0, mt_sub_t}
                                                            : 5'd0)
                        : ra_v_s;
    wire ready_t = ra_ld_t ? ra_v_t == 5'd0 : ra == 5'd0;
    wire mn_t = modrm_tk ? 1'b0 : mn_s;
    wire stop_t = stopped || t_halt;
    wire irh_t = t_start ? irh_set_t : ((irh && !irh_clr_t) || irh_pg_t);

    // ------------------------------------------------------------ S3 (L): load_ir
    wire [3:0] av_l = avail4 - 4'(k_t);
    assign l_pop = !ir_s && need_t_w == 3'd0 && ready_t && !stop_t && av_l != 4'd0 && !t_flush
                   && !irh_t;
    assign l_load = l_pop;
    // (R3) xfer_abort=word: a transfer's displacement byte is the bus unit's (its target
    // adder's), not the EU's: its room is released a clock after the take step ends (relc)
    // (R3) latch_disp: a memory form's displacement byte goes to the EA adder likewise: on a
    // word's delivery clock with the IR load (V35_R3_DREL 1; 2: without it too) its room is
    // released a clock late
    wire       xl_t = ((`V35_R3_XREL != 0) && fm_t.xfer && (`V35_R3_XREL == 2 || t_start)
                       || (`V35_R3_DREL != 0) && disp_tk && dlv && (`V35_R3_DREL == 2 || l_pop))
                      && t_done && !modrm_tk && (3'(unc) + k_t) != 3'd0;
    wire [2:0] rel_t = rel_t0 - (xl_t ? 3'd1 : 3'd0);
    assign rd = k_t + (l_pop ? 3'd1 : 3'd0);
    assign rel = rel_t + (l_pop ? 3'd1 : 3'd0) + relc;
    // the staging byte (the IR, the queue's seventh slot) is occupied while it holds an opcode,
    // and unavailable while the running form has operand bytes outstanding but on a word's
    // delivery clock (room_ir=arrival_idle, from the loader's side)
    // (R1) ea_ir_room / ir_load: nor is the empty IR a free slot while its load is held for the
    // form's data cycle (ir_hold) with no operand byte left to take
    // (R3) lea_room=ir: while LDEA runs its EA clocks after its last operand byte its successor's
    // opcode, loaded into the IR, is decoded beside the address adder: the IR no slot taken
    // (R3) modrm_mate=imm: the word whose first byte was the ModR/M byte is not free on its
    // delivery clock while its second byte (an immediate's first) is taken: the staging byte stays
    assign stg = ((ir_s || l_pop) && !(`V35_R3_LEAR && lea_room))
                 || (need_t_w != 3'd0 && (!dlv || (`V35_R3_MATE && mate)))
                 || (`V35_R1_IRH && irh_t && need_t_w == 3'd0);
    wire [7:0] ir_l_w = l_pop ? vb(k_t) : ir;
    assign ir_l = ir_l_w;
    assign ir_addr_l = l_pop ? head_addr + 20'(k_t) : ir_addr;
    assign ir_v_l = ir_s || l_load;
    // the IR's ModR/M byte: the byte after it
    wire [2:0] pos_p = k_t + (l_pop ? 3'd1 : 3'd0);
    // (S7) the IR after L: the IR's (its form the same), or the head byte's loaded before any
    // take (the decode ahead's when the IR was empty); else not known
    assign fmt_l = a1;
    assign ok_l = pd_v && (ir_s || (l_pop && !ir_v && k_t == 3'd0));


    // ------------------------------------------------------------ (S7b) the ce_b registers
    // Tick A (S1-S4: the T pass's take and start, the IR load) ends at ce_b; tick B (S5, S6:
    // the P pass, the decode ahead, the next state) reads its results from these registers
    // only (and the architectural registers), never tick A's logic.
    reg  [7:0]  vb0_b = 8'h00, vb1_b = 8'h00, vb2_b = 8'h00, vb3_b = 8'h00;
    reg  [19:0] ir_addr_l_b = 20'd0, t_flush_addr_b = 20'd0;
    reg  [3:0]  av_l_b = 4'd0;
    reg  [1:0]  k_t_b = 2'd0;
    reg  [2:0]  unc_t_b = 3'd0;

    v35_fmt_t   fmt_l_b = '0, fm_r_b = '0;
    v35_cls_t   c_cls_b = '0;
    reg  [2:0]  need_t_w_b = 3'd0, nx_s_b = 3'd0, pos_p_b = 3'd0;
    reg         mn_t_b = 1'b0, pg_s_b = 1'b0, ms_t_b = 1'b0, ir_v_l_b = 1'b0;
    reg  [7:0]  ir_l_w_b = 8'h00, opc_t_b = 8'h00;
    reg         l_pop_b = 1'b0, ra_ld_t_b = 1'b0, irh_t_b = 1'b0, eu_issue_b = 1'b0;
    reg  [4:0]  ra_v_t_b = 5'd0;
    reg         t_flush_b = 1'b0, stop_t_b = 1'b0, t_start_b = 1'b0;
    reg         xl_t_b = 1'b0;          // (R3) the displacement's late-released byte (relc)
    always_ff @(posedge clock) begin
        if (ce_b) begin
            vb0_b <= vb0;
            vb1_b <= vb1;
            vb2_b <= vb2;
            vb3_b <= vb3;
            t_flush_addr_b <= t_flush_addr;
            k_t_b <= t_k_in;
            unc_t_b <= unc_t;
            ir_addr_l_b <= ir_addr_l;
            av_l_b <= av_l;
            fmt_l_b <= fmt_l;
            fm_r_b <= fm_r;
            c_cls_b <= c_cls;
            need_t_w_b <= need_t_w;
            nx_s_b <= nx_s;
            pos_p_b <= pos_p;
            mn_t_b <= mn_t;
            pg_s_b <= pg_s;
            ms_t_b <= ms_t;
            ir_v_l_b <= ir_v_l;
            ir_l_w_b <= ir_l_w;
            opc_t_b <= opc_t;
            l_pop_b <= l_pop;
            ra_ld_t_b <= ra_ld_t;
            irh_t_b <= irh_t;
            eu_issue_b <= eu_issue;
            ra_v_t_b <= ra_v_t;
            t_flush_b <= t_flush;
            stop_t_b <= stop_t;
            t_start_b <= t_start;
            xl_t_b <= xl_t;
        end
    end
    function automatic logic [7:0] vb_b(input logic [2:0] k);
        case (k)
            3'd0: vb_b = vb0_b;
            3'd1: vb_b = vb1_b;
            3'd2: vb_b = vb2_b;
            default: vb_b = vb3_b;
        endcase
    endfunction

    // ------------------------------------------------------------ S5 (P)
    wire [2:0] need_ps = p_start ? fmt_l_b.len - 3'd1 : need_t_w_b;
    wire [2:0] nx_ps = p_start ? c_cls_b.nx : nx_s_b;
    wire       mn_ps = p_start ? fmt_l_b.has_modrm : mn_t_b;
    wire       pg_ps = p_start ? fmt_l_b.page == 2'd1 : pg_s_b;
    wire       ms_ps = p_start ? (fmt_l_b.page == 2'd1 && fmt_l_b.has_modrm) : ms_t_b;
    wire       ir_ps = p_start ? 1'b0 : ir_v_l_b;
    wire [7:0] op_ps = p_start ? ir_l_w_b : opc_t_b;
    wire [4:0] ra_v_ps = (fmt_l_b.len == 3'd1) ? c_cls_b.nx0 : 5'd0;
    wire [3:0] av_p = av_l_b - (l_pop_b ? 4'd1 : 4'd0);
    wire k_p_w = p_k_in && av_p != 4'd0;
    wire modrm_p = k_p_w && mn_ps && !ms_ps;
    wire ms_p = ms_ps && !k_p_w;
    // (Q1) tick B's pops: the P take step's bytes at its end, a ModR/M byte at once, the IR load
    // (the held byte, if any, is the P pass's first)
    wire [2:0] unc_e = t_flush_b ? 3'd0 : (p_done ? 3'd0 : unc_t_b + (k_p_w ? 3'd1 : 3'd0)
                                                             - (modrm_p ? 3'd1 : 3'd0));
    assign rd_b = (k_p_w ? 3'd1 : 3'd0) + (p_ir ? 3'd1 : 3'd0);
    wire [2:0] rel_p = (p_done ? unc_t_b + (k_p_w ? 3'd1 : 3'd0) : (modrm_p ? 3'd1 : 3'd0))
                       + (p_ir ? 3'd1 : 3'd0);
    wire [7:0] opc_p = (k_p_w && ms_ps) ? vb_b(pos_p_b) : op_ps;
    v35_fmt_t fm_q, fm_p;
    // (no P start: the form after T.) (S7) A running form takes its ModR/M byte in the P pass
    // only after a P start (the start's format, fmt_l): a P take of a form started before is
    // not on the corpus, its re-decode not built (p_mmiss reports one)
    assign fm_q = fm_r_b;
    assign p_mmiss = modrm_p && !p_start;
    assign fmt_mp = fm_q;
    assign fm_p = p_start ? fmt_l_b : fm_q;
    wire [2:0] need_p_w = modrm_p ? fm_p.len - 3'd2 - (pg_ps ? 3'd1 : 3'd0)
                                  : need_ps - (k_p_w ? 3'd1 : 3'd0);
    wire ra_ld_pk = k_p_w && need_p_w == 3'd0;
    wire ra_ld_p = ra_ld_pk || p_start || ra_ld_t_b;
    wire [4:0] ra_pk = {2'd0, nx_ps} + (p_io_nx ? 5'd1 : 5'd0);
    wire [4:0] ra_v_p = ra_ld_pk ? (ra_pk > {1'b0, mt_sub_p} ? ra_pk - {1'b0, mt_sub_p} : 5'd0) :
                        p_start ? ra_v_ps : ra_v_t_b;
    wire ready_p = ra_ld_p ? ra_v_p == 5'd0 : ra == 5'd0;
    wire [3:0] av_pi = av_p - (k_p_w ? 4'd1 : 4'd0);
    // ir_load: the EU's data cycle issued: the hold released, the IR loads again (machine.py)
    wire irh_x = irh_t_b && !eu_issue_b;
    wire ir_rel = irh_t_b && eu_issue_b;
    wire irh_p = p_start ? irh_set_p : ((irh_x && !irh_clr_p) || irh_pg_p);
    assign p_ir = !ir_ps && need_p_w == 3'd0 && ready_p && !stop_t_b && av_pi != 4'd0
                  && (p_start || k_p_w || ir_rel) && !irh_p;
    assign p_load = p_ir;
    assign ir_v_p = ir_ps || p_ir;
    wire mn_p = modrm_p ? 1'b0 : mn_ps;

    // ------------------------------------------------------------ S6: the decode ahead
    // the bytes this clock leaves at the queue's head (this clock's delivery included)
    wire [2:0] pops = pos_p_b + (k_p_w ? 3'd1 : 3'd0) + (p_ir ? 3'd1 : 3'd0);
    wire [19:0] pc_e = t_flush_b ? t_flush_addr_b + 20'(pops) - 20'(k_t_b) : pc + 20'(pops);
    wire [7:0] ir_e = p_ir ? vb_b(pos_p_b + (k_p_w ? 3'd1 : 3'd0)) : ir_l_w_b;
    wire [19:0] ira_e = p_ir ? pc + 20'(pos_p_b) + (k_p_w ? 20'd1 : 20'd0) : ir_addr_l_b;
    wire       irv_e = ir_v_p && !t_flush_b;
    // ((Q1) the window is four bytes: vb0..vb3)
    wire       h0 = !t_flush_b && {1'b0, pops} < avail4 && pops <= 3'd3;
    wire       h1 = !t_flush_b && {1'b0, pops} + 4'd1 < avail4 && pops <= 3'd2;
    // (S5b) the byte after those (a 0F form's ModR/M byte behind its second opcode byte)
    wire       h2 = !t_flush_b && {1'b0, pops} + 4'd2 < avail4 && pops <= 3'd1;
    assign nf_v = irv_e || h0;
    assign nf_op = irv_e ? ir_e : vb_b(pops);
    assign nf_addr = irv_e ? ira_e : pc_e;
    // the decode ahead: the opcode's escape, the table entry of the opcode or the byte behind
    // an escape (the only table reads of the clock), the format with the ModR/M byte
    wire [7:0] nf_b1 = irv_e ? (h0 ? vb_b(pops) : 8'h00) : (h1 ? vb_b(pops + 3'd1) : 8'h00);
    wire [7:0] nf_b2 = irv_e ? (h1 ? vb_b(pops + 3'd1) : 8'h00) : (h2 ? vb_b(pops + 3'd2) : 8'h00);
    wire       nf_b1v = irv_e ? h0 : h1;
    v35_dec_t  nf_d1, nf_d;
    assign nf_d1 = v35_dec_native(nf_op);
    wire [1:0] nf_pg = nf_d1.esc == 2'd1 ? 2'd1 : (nf_d1.esc == 2'd2 ? 2'd2 : 2'd0);
    wire [7:0] nf_aop = nf_pg != 2'd0 ? nf_b1 : nf_op;
    // (nf_d1: only its escape and repc are read; one native table read for the entry)
    assign nf_d = nf_pg == 2'd1 ? v35_dec_ext(nf_aop) : v35_dec_native(nf_aop);
    assign nf_fmt = dec_asm(nf_aop, nf_pg, nf_d, nf_d1.repc, nf_pg == 2'd1 ? nf_b2 : nf_b1);

    // ------------------------------------------------------------ S6: next state
    // the ready countdown: one_idle a clock less, long_exec a wait clock more
    wire [4:0] ra_n = ra_ld_p ? ra_v_p : ra;
    wire [4:0] ra_a = (idle_adj && ra_n != 5'd0) ? ra_n - 5'd1
                    : ((lx_hold && ra_n != 5'd0) ? ra_n + 5'd1 : ra_n);
    always_ff @(posedge clock) begin
        if (!reset_n) begin
            ir_v <= 1'b0;
            ir <= 8'h00;
            ir_addr <= 20'd0;
            opc <= 8'h00;
            need <= 3'd0;
            nx <= 3'd0;
            ra <= 5'd0;
            modrm_next <= 1'b0;
            stopped <= 1'b0;
            irh <= 1'b0;
            pc <= reset_addr;
            relc <= 3'd0;
            unc <= 2'd0;
            pg <= 1'b0;
            mskip <= 1'b0;
            pd_v <= 1'b0;
            pd_pg <= 2'd0;
            pd_op <= 8'h00;
            pd_rc <= 2'd0;
            pd_d <= '0;
            d_run <= '0;
        end else if (ce_a) begin
            pd_v <= nf_v && (nf_pg == 2'd0 || nf_b1v);
            pd_pg <= nf_pg;
            pd_op <= nf_aop;
            pd_rc <= nf_d1.repc;
            pd_d <= nf_d;
            if (t_start_b || p_start)
                d_run <= pd_d;
            ir_v <= ir_v_p && !t_flush_b;
            relc <= t_flush_b ? 3'd0 : rel_p + (xl_t_b ? 3'd1 : 3'd0);
            if (p_ir) begin
                ir <= ir_e;
                ir_addr <= ira_e;
            end else if (l_pop_b) begin
                ir <= ir_l_w_b;
                ir_addr <= ir_addr_l_b;
            end
            opc <= opc_p;
            pg <= pg_ps;
            mskip <= ms_p;
            need <= t_flush_b ? 3'd0 : need_p_w;
            nx <= nx_ps;
            ra <= ra_a == 5'd0 ? 5'd0 : ra_a - 5'd1;
            modrm_next <= mn_p;
            stopped <= stop_t_b;
            irh <= irh_p && !t_flush_b;
            pc <= pc_e;
            unc <= unc_e[1:0];
        end
    end

    // (S7b) chk begin (generated: the ce_b registers against their sources at ce_a)
`ifndef SYNTHESIS
    /* verilator lint_off BLKSEQ */
    reg chk_on = 1'b0;
    integer chk_n = 0;
    initial chk_on = $test$plusargs("v35_chk");
    always @(posedge clock) begin
        if (chk_on && reset_n && ce_a) begin
            if (vb0_b !== vb0) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.vb0 changed in tick B: %h -> %h at %0t",
                             vb0_b, vb0, $time);
            end
            if (vb1_b !== vb1) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.vb1 changed in tick B: %h -> %h at %0t",
                             vb1_b, vb1, $time);
            end
            if (vb2_b !== vb2) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.vb2 changed in tick B: %h -> %h at %0t",
                             vb2_b, vb2, $time);
            end
            if (vb3_b !== vb3) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.vb3 changed in tick B: %h -> %h at %0t",
                             vb3_b, vb3, $time);
            end
            if (t_flush_addr_b !== t_flush_addr) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.t_flush_addr changed in tick B: %h -> %h at %0t",
                             t_flush_addr_b, t_flush_addr, $time);
            end
            if (k_t_b !== t_k_in) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.t_k_in changed in tick B: %h -> %h at %0t",
                             k_t_b, t_k_in, $time);
            end
            if (unc_t_b !== unc_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.unc_t changed in tick B: %h -> %h at %0t",
                             unc_t_b, unc_t, $time);
            end
            if (ir_addr_l_b !== ir_addr_l) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.ir_addr_l changed in tick B: %h -> %h at %0t",
                             ir_addr_l_b, ir_addr_l, $time);
            end
            if (av_l_b !== av_l) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.av_l changed in tick B: %h -> %h at %0t",
                             av_l_b, av_l, $time);
            end
            if (fmt_l_b !== fmt_l) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.fmt_l changed in tick B: %h -> %h at %0t",
                             fmt_l_b, fmt_l, $time);
            end
            if (fm_r_b !== fm_r) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.fm_r changed in tick B: %h -> %h at %0t",
                             fm_r_b, fm_r, $time);
            end
            if (c_cls_b !== c_cls) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.c_cls changed in tick B: %h -> %h at %0t",
                             c_cls_b, c_cls, $time);
            end
            if (need_t_w_b !== need_t_w) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.need_t_w changed in tick B: %h -> %h at %0t",
                             need_t_w_b, need_t_w, $time);
            end
            if (nx_s_b !== nx_s) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.nx_s changed in tick B: %h -> %h at %0t",
                             nx_s_b, nx_s, $time);
            end
            if (pos_p_b !== pos_p) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.pos_p changed in tick B: %h -> %h at %0t",
                             pos_p_b, pos_p, $time);
            end
            if (mn_t_b !== mn_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.mn_t changed in tick B: %h -> %h at %0t",
                             mn_t_b, mn_t, $time);
            end
            if (pg_s_b !== pg_s) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.pg_s changed in tick B: %h -> %h at %0t",
                             pg_s_b, pg_s, $time);
            end
            if (ms_t_b !== ms_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.ms_t changed in tick B: %h -> %h at %0t",
                             ms_t_b, ms_t, $time);
            end
            if (ir_v_l_b !== ir_v_l) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.ir_v_l changed in tick B: %h -> %h at %0t",
                             ir_v_l_b, ir_v_l, $time);
            end
            if (ir_l_w_b !== ir_l_w) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.ir_l_w changed in tick B: %h -> %h at %0t",
                             ir_l_w_b, ir_l_w, $time);
            end
            if (opc_t_b !== opc_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.opc_t changed in tick B: %h -> %h at %0t",
                             opc_t_b, opc_t, $time);
            end
            if (l_pop_b !== l_pop) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.l_pop changed in tick B: %h -> %h at %0t",
                             l_pop_b, l_pop, $time);
            end
            if (ra_ld_t_b !== ra_ld_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.ra_ld_t changed in tick B: %h -> %h at %0t",
                             ra_ld_t_b, ra_ld_t, $time);
            end
            if (irh_t_b !== irh_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.irh_t changed in tick B: %h -> %h at %0t",
                             irh_t_b, irh_t, $time);
            end
            if (eu_issue_b !== eu_issue) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.eu_issue changed in tick B: %h -> %h at %0t",
                             eu_issue_b, eu_issue, $time);
            end
            if (ra_v_t_b !== ra_v_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.ra_v_t changed in tick B: %h -> %h at %0t",
                             ra_v_t_b, ra_v_t, $time);
            end
            if (t_flush_b !== t_flush) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.t_flush changed in tick B: %h -> %h at %0t",
                             t_flush_b, t_flush, $time);
            end
            if (stop_t_b !== stop_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.stop_t changed in tick B: %h -> %h at %0t",
                             stop_t_b, stop_t, $time);
            end
            if (t_start_b !== t_start) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.t_start changed in tick B: %h -> %h at %0t",
                             t_start_b, t_start, $time);
            end
            if (xl_t_b !== xl_t) begin
                chk_n = chk_n + 1;
                if (chk_n <= 20)
                    $display("v35 chk: loader.xl_t changed in tick B: %h -> %h at %0t",
                             xl_t_b, xl_t, $time);
            end
        end
    end
    final if (chk_on && chk_n != 0)
        $display("v35 chk: loader: %0d changes in tick B", chk_n);
    /* verilator lint_on BLKSEQ */
`endif
    // (S7b) chk end

    wire unused = &{1'b0, ce_b, c_cls_b, av_p, fm_t, fm_p, h1, nf_d1, unc_e[2]};
endmodule
