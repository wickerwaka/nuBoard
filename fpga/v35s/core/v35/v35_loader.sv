`timescale 1ns/1ps

// V35S core v2: the loader (docs/v35s-core-v2.md, "Modules and the state they own"; Appendix B
// §1 "Loader / IR"): the opcode register (IR, a seventh byte outside the queue), the format
// lookup (S2: the hand-written stub table, v35_decode_stub.svh), the operand-take handshake
// with the queue (one byte per clock, two for a word displacement), `need`, the ready countdown
// for the next IR load, the ModR/M commit strobe and the word-mate strobe. The take decisions
// are the EU's (it asks for `left` bytes now); the loader grants min(left, width, available).
//
// Stage map:
//   S2  T: the start (the IR consumed, need/nx/ModR/M loaded), the EU's take
//   S3  L: the IR load (load_ir: no operand bytes outstanding, the class's nx clocks passed)
//   S5  P: the second pass's start, take (one byte at most) and IR load
//   S6  the next state
//
// Registered state (widths) and the model variables it replaces:
//   ir_v 1, ir 8, ir_addr 20      decoder.ir (the opcode and, for the trace, its address)
//   need 3                        decoder.need (the displacement added on the ModR/M take)
//   nx 3                          decoder.nx (the running form's class integer)
//   ra 3                          decoder.ready_at as a countdown (ready_at - t at the next clock)
//   modrm_next 1                  decoder.modrm_next
//   mate_arm 1                    modrm_addr + imm_reg: the next byte is the ModR/M's word-mate
//   imm_reg 1                     decoder.imm_reg
//   stopped 1                     decoder.stopped (HALT)
//   (ir_hold, ea_end, lea_wait, fresh, modrm_skip: S4/S5, not built; ir_hold is a zero output)
module v35_loader
    import v35_front_pkg::*;
    import v35_stub_pkg::*;
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
    input  wire        t_tk_go,         // a take step asks now ...
    input  wire [2:0]  t_tk_left,       // ... for its bytes left
    input  wire        t_tk_wide,       // two bytes on one clock (disp16=word)
    input  wire        t_flush,
    input  wire        t_halt,
    // S5 (P) from the EU
    input  wire        p_start,
    input  wire        p_tk_go,
    input  wire [2:0]  p_tk_left,
    input  wire        p_io_nx,         // io_take_nx: the IR load a clock later

    // the IR (before S2)
    output wire        ir_v_c,
    output wire [7:0]  ir_c,
    output wire [19:0] ir_addr_c,
    output fmt_t       fmt_c,           // the IR's format
    output wire [2:0]  need_c,
    // S2
    output wire [1:0]  t_k,             // bytes taken
    output wire        t_done,          // the take step's last byte taken: it commits
    output wire [7:0]  t_b0, t_b1,
    output wire        t_commit1,
    output wire        t_mate,
    output wire [2:0]  need_t,
    output wire        ir_v_t,
    // S3
    output wire        l_pop,
    output wire [19:0] ir_addr_l,
    output fmt_t       fmt_l,
    output wire        ir_v_l,
    // S5
    output wire        p_k,
    output wire        p_done,
    output wire [7:0]  p_b0,
    output wire        p_commit1,
    output wire        p_mate,
    output wire        p_ir,
    output wire [2:0]  need_p,
    output wire        ir_v_p,
    output wire        ir_hold,
    output wire        stopped_o
);
    // ------------------------------------------------------------ registered state
    reg        ir_v = 1'b0;
    reg [7:0]  ir = 8'h00;
    reg [19:0] ir_addr = 20'd0;
    reg [2:0]  need = 3'd0;
    reg [2:0]  nx = 3'd0;
    reg [2:0]  ra = 3'd0;
    reg        modrm_next = 1'b0;
    reg        mate_arm = 1'b0;
    reg        imm_reg = 1'b0;
    reg        stopped = 1'b0;

    assign ir_hold = 1'b0;
    assign stopped_o = stopped;
    assign ir_v_c = ir_v;
    assign ir_c = ir;
    assign ir_addr_c = ir_addr;
    assign fmt_c = v35_decode(ir);
    assign need_c = need;
    wire cls_t c_cls = v35_class_stub(fmt_c.cls);

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
    wire       mn_s = t_start ? fmt_c.modrm : modrm_next;
    wire       ma_s = t_start ? 1'b0 : mate_arm;
    wire       ir_s = t_start ? 1'b0 : ir_v;
    wire       ra_ld_s = t_start;
    wire [2:0] ra_v_s = (fmt_c.len == 3'd1) ? c_cls.nx0 : 3'd0;
    // the take: min(left, 1 or 2, available)
    wire [2:0] cap_t = t_tk_wide ? 3'd2 : 3'd1;
    wire [2:0] lim_t = t_tk_left < cap_t ? t_tk_left : cap_t;
    wire [2:0] k_t = !t_tk_go ? 3'd0 : (avail_c >= {1'b0, lim_t} ? lim_t : 3'(avail_c));
    assign t_k = 2'(k_t);
    assign t_done = t_tk_go && k_t == t_tk_left;
    assign t_b0 = vb0;
    assign t_b1 = vb1;
    wire modrm_tk = k_t != 3'd0 && mn_s;
    assign t_commit1 = modrm_tk;
    assign t_mate = k_t != 3'd0 && ma_s && need_s > k_t;
    wire [1:0] disp_t = modrm_tk ? v35_modrm_disp(vb0) : 2'd0;
    wire [2:0] need_t_w = need_s - k_t + 3'(disp_t);
    assign need_t = need_t_w;
    assign ir_v_t = ir_s;
    // ready_at: t + nx at the last operand take
    wire ra_ld_t = (k_t != 3'd0 && need_t_w == 3'd0) || ra_ld_s;
    wire [2:0] ra_v_t = (k_t != 3'd0 && need_t_w == 3'd0) ? nx_s : ra_v_s;
    wire ready_t = ra_ld_t ? ra_v_t == 3'd0 : ra == 3'd0;
    wire mn_t = modrm_tk ? 1'b0 : mn_s;
    wire ma_t = k_t != 3'd0 ? (modrm_tk && !head_addr[0] && (t_start ? fmt_c.imm != 2'd0
                                                             && !fmt_c.mem : imm_reg)) : ma_s;
    wire im_t = t_start ? (fmt_c.imm != 2'd0 && !fmt_c.mem) : imm_reg;
    wire stop_t = stopped || t_halt;

    // ------------------------------------------------------------ S3 (L): load_ir
    wire [3:0] av_l = avail_c - 4'(k_t);
    assign l_pop = !ir_s && need_t_w == 3'd0 && ready_t && !stop_t && av_l != 4'd0 && !t_flush;
    wire [7:0] ir_l = l_pop ? vb(k_t) : ir;
    assign ir_addr_l = l_pop ? head_addr + 20'(k_t) : ir_addr;
    assign ir_v_l = ir_s || l_pop;
    assign fmt_l = v35_decode(ir_l);
    wire cls_t l_cls = v35_class_stub(fmt_l.cls);

    // ------------------------------------------------------------ S5 (P)
    wire [2:0] pos_p = k_t + (l_pop ? 3'd1 : 3'd0);
    wire [2:0] need_ps = p_start ? fmt_l.len - 3'd1 : need_t_w;
    wire [2:0] nx_ps = p_start ? l_cls.nx : nx_s;
    wire       mn_ps = p_start ? fmt_l.modrm : mn_t;
    wire       ma_ps = p_start ? 1'b0 : ma_t;
    wire       ir_ps = p_start ? 1'b0 : ir_v_l;
    wire [2:0] ra_v_ps = (fmt_l.len == 3'd1) ? l_cls.nx0 : 3'd0;
    wire [3:0] av_p = av_l - (l_pop ? 4'd1 : 4'd0);
    wire k_p_w = p_tk_go && p_tk_left != 3'd0 && av_p != 4'd0;
    assign p_k = k_p_w;
    assign p_done = p_tk_go && k_p_w && p_tk_left == 3'd1;
    assign p_b0 = vb(pos_p);
    wire modrm_p = k_p_w && mn_ps;
    assign p_commit1 = modrm_p;
    assign p_mate = k_p_w && ma_ps && need_ps > 3'd1;
    wire [1:0] disp_p = modrm_p ? v35_modrm_disp(vb(pos_p)) : 2'd0;
    wire [2:0] need_p_w = need_ps - (k_p_w ? 3'd1 : 3'd0) + 3'(disp_p);
    assign need_p = need_p_w;
    wire ra_ld_pk = k_p_w && need_p_w == 3'd0;
    wire ra_ld_p = ra_ld_pk || p_start || ra_ld_t;
    wire [2:0] ra_v_p = ra_ld_pk ? nx_ps + (p_io_nx ? 3'd1 : 3'd0) :
                        p_start ? ra_v_ps : ra_v_t;
    wire ready_p = ra_ld_p ? ra_v_p == 3'd0 : ra == 3'd0;
    wire [3:0] av_pi = av_p - (k_p_w ? 4'd1 : 4'd0);
    assign p_ir = !ir_ps && need_p_w == 3'd0 && ready_p && !stop_t && av_pi != 4'd0
                  && (p_start || k_p_w);
    assign ir_v_p = ir_ps || p_ir;
    wire mn_p = modrm_p ? 1'b0 : mn_ps;
    wire ma_p = k_p_w ? (modrm_p && !(head_addr[0] ^ pos_p[0])
                         && (p_start ? fmt_l.imm != 2'd0 && !fmt_l.mem : im_t)) : ma_ps;
    wire im_p = p_start ? (fmt_l.imm != 2'd0 && !fmt_l.mem) : im_t;

    // ------------------------------------------------------------ S6: next state
    always @(posedge clock) begin
        if (!reset_n) begin
            ir_v <= 1'b0;
            ir <= 8'h00;
            ir_addr <= 20'd0;
            need <= 3'd0;
            nx <= 3'd0;
            ra <= 3'd0;
            modrm_next <= 1'b0;
            mate_arm <= 1'b0;
            imm_reg <= 1'b0;
            stopped <= 1'b0;
        end else if (ce) begin
            ir_v <= ir_v_p && !t_flush;
            if (p_ir) begin
                ir <= vb(pos_p + (k_p_w ? 3'd1 : 3'd0));
                ir_addr <= head_addr + 20'(pos_p) + (k_p_w ? 20'd1 : 20'd0);
            end else if (l_pop) begin
                ir <= ir_l;
                ir_addr <= ir_addr_l;
            end
            need <= t_flush ? 3'd0 : need_p_w;
            nx <= nx_ps;
            ra <= ra_ld_p ? (ra_v_p == 3'd0 ? 3'd0 : ra_v_p - 3'd1)
                          : (ra == 3'd0 ? 3'd0 : ra - 3'd1);
            modrm_next <= mn_p;
            mate_arm <= ma_p;
            imm_reg <= im_p;
            stopped <= stop_t;
        end
    end

    wire unused = &{1'b0, c_cls.wb, c_cls.hphase, c_cls.lead, c_cls.relatch, l_cls.wb,
                    l_cls.hphase, l_cls.lead, l_cls.relatch, av_p};
endmodule
