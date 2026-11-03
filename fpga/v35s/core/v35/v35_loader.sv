`timescale 1ns/1ps

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
//   mate_arm 1                    modrm_addr + imm_reg: the next byte is the ModR/M's word-mate
//   imm_reg 1                     decoder.imm_reg
//   stopped 1                     decoder.stopped (HALT)
//   ir_hold 1                     decoder.ir_hold (ir_load=disp_data: set at a displaced memory
//                                 form's start, cleared by its displacement's take on a delivery
//                                 clock or its first data cycle's issue; S4)
//   fresh 1                       decoder.fresh (room_ir_pre=modrm: no operand byte of the
//                                 running TEST r,r / INC-DEC r8 taken yet; S4)
//   (ea_end: the sequencer's countdown; lea_wait, modrm_skip: S5)
module v35_loader
    import v35_front_pkg::*;
    import v35_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce,

    // the queue's head window (S1) and its address
    input  wire [7:0]  vb0, vb1, vb2, vb3, vb4,
    input  wire [19:0] head_addr,
    input  wire [3:0]  avail_c,

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
    input  wire        eu_issue,
    input  wire        irh_set_p,
    input  wire        irh_clr_p,

    // the IR (before S2)
    output wire        ir_v_c,
    output wire [7:0]  ir_c,
    output wire [19:0] ir_addr_c,
    output v35_fmt_t   fmt_c,           // the IR's format (its ModR/M byte the head byte)
    output v35_cls_t   cls_c,           // ... its class constants
    output v35_fmt_t   fmt_mt,          // the running form (started before this clock)
                                        // re-decoded at a T ModR/M take (the head byte)
    output wire [2:0]  need_c,
    // S2
    output wire        t_commit1,
    output wire        t_mate,
    output wire [2:0]  need_t,
    output wire        ir_v_t,
    // S3
    output wire        l_pop,
    output wire [7:0]  ir_l,
    output wire [19:0] ir_addr_l,
    output v35_fmt_t   fmt_l,
    output v35_cls_t   cls_l,
    output wire        ir_v_l,
    // S5
    output wire        p_commit1,
    output v35_fmt_t   fmt_mp,          // the form running after T re-decoded at a P take
    output wire        p_mate,
    output wire        p_ir,
    output wire [2:0]  need_p,
    output wire        ir_v_p,
    output wire        ir_hold,         // before T (registered)
    output wire        ir_hold_t,       // after T
    output wire        ir_hold_p,       // after S5
    output wire        ir_rel,          // the hold released by an EU cycle's issue: an IR load in P
    output wire        fresh_c,         // room_ir_pre: before T
    output wire        fresh_t,         // ... after T
    output wire        fresh_p,         // ... after S5
    output wire        stopped_o,
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
    reg        mate_arm = 1'b0;
    reg        imm_reg = 1'b0;
    reg        stopped = 1'b0;
    reg        irh = 1'b0;
    reg        fresh = 1'b0;

    assign ir_hold = irh;
    assign stopped_o = stopped;
    assign ir_v_c = ir_v;
    assign ir_c = ir;
    assign ir_addr_c = ir_addr;
    assign fmt_c = v35_fmt_of(ir, 2'd0, vb0);
    assign need_c = need;
    v35_cls_t c_cls;
    assign c_cls = v35_cls_const(fmt_c.cls);
    assign cls_c = c_cls;

    function automatic logic [7:0] vb(input logic [2:0] k);
        case (k)
            3'd0: vb = vb0;
            3'd1: vb = vb1;
            3'd2: vb = vb2;
            3'd3: vb = vb3;
            default: vb = vb4;
        endcase
    endfunction

    // ------------------------------------------------------------ S2 (T)
    // the start: decoder.start (the IR consumed; need, nx, ModR/M; ready_at = t + nx0)
    wire [2:0] need_s = t_start ? fmt_c.len - 3'd1 : need;
    wire [2:0] nx_s = t_start ? c_cls.nx : nx;
    wire       mn_s = t_start ? fmt_c.has_modrm : modrm_next;
    wire       ma_s = t_start ? 1'b0 : mate_arm;
    wire       ir_s = t_start ? 1'b0 : ir_v;
    wire [7:0] op_s = t_start ? ir : opc;
    wire       ra_ld_s = t_start;
    wire [4:0] ra_v_s = (fmt_c.len == 3'd1) ? c_cls.nx0 : 5'd0;
    // the take (the EU's)
    wire [2:0] k_t = {1'b0, t_k_in};
    wire modrm_tk = k_t != 3'd0 && mn_s;
    assign t_commit1 = modrm_tk;
    assign t_mate = k_t != 3'd0 && ma_s && need_s > k_t;
    // the ModR/M byte taken: the form's length as it decodes
    v35_fmt_t fm_r, fm_t;
    assign fm_r = v35_fmt_of(opc, 2'd0, vb0);
    assign fmt_mt = fm_r;
    assign fm_t = t_start ? fmt_c : fm_r;
    wire [2:0] need_t_w = modrm_tk ? fm_t.len - 3'd1 - k_t : need_s - k_t;
    assign need_t = need_t_w;
    assign ir_v_t = ir_s;
    // ready_at: t + nx at the last operand take
    wire ra_ld_t = (k_t != 3'd0 && need_t_w == 3'd0) || ra_ld_s;
    wire [4:0] ra_v_t = (k_t != 3'd0 && need_t_w == 3'd0) ? {2'd0, nx_s} : ra_v_s;
    wire ready_t = ra_ld_t ? ra_v_t == 5'd0 : ra == 5'd0;
    wire mn_t = modrm_tk ? 1'b0 : mn_s;
    wire ma_t = k_t != 3'd0 ? (modrm_tk && !head_addr[0] && (t_start ? fmt_c.immb != 2'd0
                                                             && !fmt_c.mem : imm_reg)) : ma_s;
    wire im_t = t_start ? (fmt_c.immb != 2'd0 && !fmt_c.mem) : imm_reg;
    wire stop_t = stopped || t_halt;
    wire irh_t = t_start ? irh_set_t : (irh && !irh_clr_t);
    assign ir_hold_t = irh_t;
    // room_ir_pre=modrm: fresh from the start of a form with operand bytes to its first take
    wire fr_t = k_t != 3'd0 ? 1'b0 : (t_start ? fmt_c.modrm_pre && fmt_c.len != 3'd1 : fresh);
    assign fresh_c = fresh;
    assign fresh_t = fr_t;

    // ------------------------------------------------------------ S3 (L): load_ir
    wire [3:0] av_l = avail_c - 4'(k_t);
    assign l_pop = !ir_s && need_t_w == 3'd0 && ready_t && !stop_t && av_l != 4'd0 && !t_flush
                   && !irh_t;
    wire [7:0] ir_l_w = l_pop ? vb(k_t) : ir;
    assign ir_l = ir_l_w;
    assign ir_addr_l = l_pop ? head_addr + 20'(k_t) : ir_addr;
    assign ir_v_l = ir_s || l_pop;
    // the IR's ModR/M byte: the byte after it
    wire [2:0] pos_p = k_t + (l_pop ? 3'd1 : 3'd0);
    assign fmt_l = v35_fmt_of(ir_l_w, 2'd0, vb(pos_p));
    v35_cls_t l_cls;
    assign l_cls = v35_cls_const(fmt_l.cls);
    assign cls_l = l_cls;

    // ------------------------------------------------------------ S5 (P)
    wire [2:0] need_ps = p_start ? fmt_l.len - 3'd1 : need_t_w;
    wire [2:0] nx_ps = p_start ? l_cls.nx : nx_s;
    wire       mn_ps = p_start ? fmt_l.has_modrm : mn_t;
    wire       ma_ps = p_start ? 1'b0 : ma_t;
    wire       ir_ps = p_start ? 1'b0 : ir_v_l;
    wire [7:0] op_ps = p_start ? ir_l_w : op_s;
    wire [4:0] ra_v_ps = (fmt_l.len == 3'd1) ? l_cls.nx0 : 5'd0;
    wire [3:0] av_p = av_l - (l_pop ? 4'd1 : 4'd0);
    wire k_p_w = p_k_in && av_p != 4'd0;
    wire modrm_p = k_p_w && mn_ps;
    assign p_commit1 = modrm_p;
    assign p_mate = k_p_w && ma_ps && need_ps > 3'd1;
    v35_fmt_t fm_q, fm_p;
    assign fm_q = v35_fmt_of(op_s, 2'd0, vb(pos_p));
    assign fmt_mp = fm_q;
    assign fm_p = p_start ? fmt_l : fm_q;
    wire [2:0] need_p_w = modrm_p ? fm_p.len - 3'd2 : need_ps - (k_p_w ? 3'd1 : 3'd0);
    assign need_p = need_p_w;
    wire ra_ld_pk = k_p_w && need_p_w == 3'd0;
    wire ra_ld_p = ra_ld_pk || p_start || ra_ld_t;
    wire [4:0] ra_v_p = ra_ld_pk ? {2'd0, nx_ps} + (p_io_nx ? 5'd1 : 5'd0) :
                        p_start ? ra_v_ps : ra_v_t;
    wire ready_p = ra_ld_p ? ra_v_p == 5'd0 : ra == 5'd0;
    wire [3:0] av_pi = av_p - (k_p_w ? 4'd1 : 4'd0);
    // ir_load: the EU's data cycle issued: the hold released, the IR loads again (machine.py)
    wire irh_x = irh_t && !eu_issue;
    assign ir_rel = irh_t && eu_issue;
    wire irh_p = p_start ? irh_set_p : (irh_x && !irh_clr_p);
    assign ir_hold_p = irh_p;
    assign p_ir = !ir_ps && need_p_w == 3'd0 && ready_p && !stop_t && av_pi != 4'd0
                  && (p_start || k_p_w || ir_rel) && !irh_p;
    wire fr_p = k_p_w ? 1'b0 : (p_start ? fmt_l.modrm_pre && fmt_l.len != 3'd1 : fr_t);
    assign fresh_p = fr_p;
    assign ir_v_p = ir_ps || p_ir;
    wire mn_p = modrm_p ? 1'b0 : mn_ps;
    wire ma_p = k_p_w ? (modrm_p && !(head_addr[0] ^ pos_p[0])
                         && (p_start ? fmt_l.immb != 2'd0 && !fmt_l.mem : im_t)) : ma_ps;
    wire im_p = p_start ? (fmt_l.immb != 2'd0 && !fmt_l.mem) : im_t;

    // ------------------------------------------------------------ S6: the decode ahead
    // the bytes this clock leaves at the queue's head (this clock's delivery included)
    wire [2:0] pops = pos_p + (k_p_w ? 3'd1 : 3'd0) + (p_ir ? 3'd1 : 3'd0);
    wire [7:0] ir_e = p_ir ? vb(pos_p + (k_p_w ? 3'd1 : 3'd0)) : ir_l_w;
    wire [19:0] ira_e = p_ir ? head_addr + 20'(pos_p) + (k_p_w ? 20'd1 : 20'd0) : ir_addr_l;
    wire       irv_e = ir_v_p && !t_flush;
    wire       h0 = !t_flush && {1'b0, pops} < avail_c && pops <= 3'd4;
    wire       h1 = !t_flush && {1'b0, pops} + 4'd1 < avail_c && pops <= 3'd3;
    assign nf_v = irv_e || h0;
    assign nf_op = irv_e ? ir_e : vb(pops);
    assign nf_addr = irv_e ? ira_e : head_addr + 20'(pops);
    assign nf_fmt = v35_fmt_of(nf_op, 2'd0, irv_e ? (h0 ? vb(pops) : 8'h00)
                                                  : (h1 ? vb(pops + 3'd1) : 8'h00));

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
            mate_arm <= 1'b0;
            imm_reg <= 1'b0;
            stopped <= 1'b0;
            irh <= 1'b0;
            fresh <= 1'b0;
        end else if (ce) begin
            ir_v <= ir_v_p && !t_flush;
            if (p_ir) begin
                ir <= ir_e;
                ir_addr <= ira_e;
            end else if (l_pop) begin
                ir <= ir_l_w;
                ir_addr <= ir_addr_l;
            end
            opc <= op_ps;
            need <= t_flush ? 3'd0 : need_p_w;
            nx <= nx_ps;
            ra <= ra_a == 5'd0 ? 5'd0 : ra_a - 5'd1;
            modrm_next <= mn_p;
            mate_arm <= ma_p;
            imm_reg <= im_p;
            stopped <= stop_t;
            irh <= irh_p && !t_flush;
            fresh <= fr_p;
        end
    end

    wire unused = &{1'b0, c_cls, l_cls, av_p, fm_t, fm_p, h1};
endmodule
