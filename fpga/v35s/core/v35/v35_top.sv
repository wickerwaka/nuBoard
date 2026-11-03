`timescale 1ns/1ps

// V35S core v2: the slot module (docs/v35s-core-v2.md, "Architecture"), stage S3: the front
// end (bus unit, prefetch queue, loader, a fetch + single-slot arbiter) and the execution unit
// (the microcode sequencer v35_ucode, the datapath v35_eu, the register RAM v35_regram).
// Ports are v35s_model.sv's (25-43); the harness instantiates it as `model` under
// V35S_CORE_V35 (fpga/v35s/v35s_harness.sv, fpga/v35s/build_sim.sh direct v35).
//
// From v35s_chain_model.sv (the chain-model core's slot wrapper), as it does them: the CPU
// clock (one CPU clock per CLKOUT = X1/2, 4 or 8 by PRC.PCK, X1/8 at reset, a PCK change at the
// next state boundary: 89-108), the reset exit (the measured A3 figures: the reset refresh's
// B1 in state 15, the first fetch's in state 25; the core held in reset until the state before
// it: 110-151), the SFR block (v35_sfr.sv) written by the core's on-chip SFR stores at their
// cycle's end (274-291), the pins forced idle (bar the reset refresh) until the core runs
// (293-316). Nothing is scripted: the core fetches the reset vector and runs the image's
// prelude itself.
//
// The refresh controller (v35_refresh.sv, reused as is) is instantiated, its request ignored
// (no refresh-on family is in the gates; the prelude's refreshes before its RFM store are not
// run, so the pre-window differs from silicon there).
//
// The six stages of a CPU clock (one registered update at `ce`, feed-forward inside it):
//   S0  every module's registers                         (bus: busy, delivery, abort, ...)
//   S1  v35_queue: arrival, retry_after, room_c          (C, A)
//   S2  v35_ucode pass T, v35_loader take/start, v35_eu (the start's form, the takes'
//       bytes, the exec's function, the T post's request)  (T)
//   S3  v35_loader IR load; v35_queue room_x, wants_fetch (L)
//   S4  v35_arbiter: counting and the grant              (X)
//   S5  v35_ucode pass P, v35_loader P, v35_queue P, v35_eu (the P post's request)  (P)
//   S6  every module's next state; v35_queue check / b2b; the decode ahead (v35_loader) and
//       the next clock's ROM window (v35_ucode) and register RAM addresses (v35_eu)   (E)
module v35_top
    import v35_front_pkg::*;
    import v35_pkg::*;
#(
    parameter int RESET_REFRESH_STATE = 15,     // A3: first refresh 118-128 X1 (/REFRQ mid-B1)
    parameter int RESET_FETCH_STATE = 25        // A3: first fetch 198-208 X1 (/MREQ mid-B1)
) (
    input  wire        clock,
    input  wire        x_rise,
    input  wire        x_fall,
    input  wire        reset_n,
    input  wire        ready,
    input  wire [15:0] data_in,
    input  wire [15:0] input_levels,
    output reg         a0,
    output reg         a19,
    output reg         a18_ube,
    output reg  [8:0]  mux_address,
    output reg  [15:0] data_out,
    output reg         mreq_n,
    output reg         mstb_n,
    output reg         iostb_n,
    output reg         read_write,
    output reg         refrq_n
);
    // ---------------------------------------------------------------- SFRs
    wire [7:0] prc, rfm, idb;
    wire [15:0] wtc;
    reg sfr_wr = 1'b0;
    reg [19:0] sfr_a = 20'd0;
    reg [1:0] sfr_w = 2'd0;
    reg [15:0] sfr_d = 16'd0;
    v35_sfr sfr (.clock, .reset_n, .wr(sfr_wr), .addr(sfr_a), .width(sfr_w), .data(sfr_d),
                 .prc, .wtc, .rfm, .idb);

    // ---------------------------------------------------------------- CPU clock
    reg [2:0] x_count = 3'd0;
    reg [1:0] pck = 2'd2;
    wire [2:0] x_last = pck == 2'd0 ? 3'd1 : pck == 2'd1 ? 3'd3 : 3'd7;
    wire [2:0] x_mid = pck == 2'd0 ? 3'd1 : pck == 2'd1 ? 3'd2 : 3'd4;
    wire state_start = reset_n && x_rise && x_count == 3'd0;
    wire state_mid = reset_n && x_rise && x_count == x_mid;
    always @(posedge clock) begin
        if (!reset_n) begin
            x_count <= 3'd0;
            pck <= 2'd2;
        end else if (x_rise) begin
            if (x_count == x_last)
                x_count <= 3'd0;
            else
                x_count <= x_count + 1'b1;
            if (x_count == 3'd0)
                pck <= prc[1:0];
        end
    end

    // ---------------------------------------------------------------- the reset exit
    reg [5:0] state_n = 6'd0;
    reg started = 1'b0;
    always @(posedge clock) begin
        if (!reset_n) begin
            state_n <= 6'd0;
            started <= 1'b0;
        end else if (state_start) begin
            started <= 1'b1;
            if (started && state_n != 6'd63)
                state_n <= state_n + 1'b1;
        end
    end
    wire [5:0] state_now = started ? state_n : 6'd0;
    reg core_run = 1'b0;
    always @(posedge clock) begin
        if (!reset_n)
            core_run <= 1'b0;
        else if (state_start && started && state_n + 6'd1 == 6'(RESET_FETCH_STATE - 1))
            core_run <= 1'b1;
    end
    wire core_reset_n = reset_n && core_run;
    localparam int RX_LEN = 5;      // RFM FCh: RFW 2 waits, 5 states
    reg rx_refrq_n = 1'b1;
    always @(posedge clock) begin
        if (!reset_n)
            rx_refrq_n <= 1'b1;
        else if (state_mid && !core_run) begin
            if (state_now == 6'(RESET_REFRESH_STATE))
                rx_refrq_n <= 1'b0;
            else if (state_now == 6'(RESET_REFRESH_STATE + RX_LEN - 1))
                rx_refrq_n <= 1'b1;
        end
    end
    localparam int INIT_COUNTER = (8 + (RESET_FETCH_STATE - 1) - (RESET_REFRESH_STATE - 1)) % 128;

    wire ce = state_start && core_run;
    wire ce_mid = state_mid;

    // ---------------------------------------------------------------- the nets between stages
    // bus (S0)
    wire        b_busy, b_free, b_in_wait, b_fetch_inflight, b_fetch_past_b2, b_fetch_end_prev;
    wire        b_fetch_run_prev, b_io_win, b_wl_busy, b_wl_busy_x, b_dlv_v, b_abort_busy;
    wire        b_abort_last, b_abort_done, b_cur_on_start, b_error, b_cpu_end_prev;
    wire [2:0]  b_cur_kind, b_cur_pos, b_cur_left, b_dlv_kind, b_fetch_len, b_grant_len;
    wire [3:0]  b_fetch_since;
    wire [19:0] b_dlv_addr;
    wire [1:0]  b_dlv_width;
    wire [15:0] b_done_data;
    // arbiter (S4)
    wire        g_start, g_fetch, g_eu, g_abort, g_mem_waiting, g_b2b, rq_set_x, retick;
    wire        g_abort_lat, g_slot, g_slot_fetch, eu_issue, g_ext, own_done_p, own_dlv;
    wire        own_two, post_ok_c, post_ok_p, slot_memw_c, dwq_c, dws_c;
    wire [1:0]  own_pos;
    wire [3:0]  a_why;
    wire [2:0]  g_kind;
    wire [19:0] g_addr;
    wire [1:0]  g_width;
    wire [15:0] g_data;
    wire        slot_wait_c, slot_wait_p, slot_det_c, slot_det_p, own_issued, own_done;
    wire [6:0]  a_count;
    wire        a_ready;
    // queue
    wire [7:0]  vb0, vb1, vb2, vb3, vb4;
    wire [19:0] head_addr, q_fetch_addr;
    wire [3:0]  avail_c, stored_c, stored_l;
    wire        arrived_now, inflight_c, inflight_x, completed_now, lat_c, lat_x;
    wire        want_c, nb_now, dec_inf;
    wire [3:0]  dec_since;
    // (S5a) the transfers' holds
    wire        xs_start, fh_set, ox_set, nt_set, nt_dbnz, ou_set, xs_done, ff_set, ntb_ok, xfer_x;
    wire        ff_t, ff_t0;
    // (S5a) the strings
    wire        edone, edone_t, povr_t, povr_p, str_last, str_exit, own_h2, g_wl_io, w3_v;
    wire signed [4:0] w3_rel;
    wire [4:0]  fh_n;
    wire [2:0]  ou_n, ff_n;
    wire [2:0]  xk_c, xk_t, xk_p;
    wire        p_flush;
    wire        lea_xk_c, lea_xk_t, lea_xk_p, mf_old, th_arm_t, th_arm_p, th_cvt, th_lift_t, th_lift_p;
    wire        asked_d, asked_t, asked_p, flag_x, want_x, rq_v_x, rq_now_x, rq_old_c, rq_old_p;
    wire        rq_clr_p, b2b_now, triple_x, q_retry, q_retry_loop, io_held, nop_held;
    wire        io_hold_x, latch_start_now, rq_ir_hold, b2b_next, flag_e, q_overflow;
    wire        shift_latch, rq_v_e, io_unit_drop;
    wire signed [4:0] room_c0;
    wire signed [4:0] room_c, room_x, room_p0, room_e;
    // (S5b) the 0F page
    wire        b_cur_thru, b_cur_b2b_pfa, b_cf_tn, b_cf_irb, b_prev_imm;
    wire        g_thru, g_pfa, slot_pf_e;
    wire        irh_pg_t, irh_pg_p, fl_c, fl_t, fl_p, fl_end_t, fl_end_t2, fl_end_p, pfs_x, pfs_e;
    wire        pimm_x, pcl_x, pgb2b_e, res0_e, bcd_idle, bf_cross, bf_ok;
    wire [3:0]  mt_sub_t, mt_sub_p;
    wire [2:0]  pcl_fs;
    wire [10:0] bfcost;
    // loader
    wire        ir_v_c, ir_v_t, ir_v_l, ir_v_p, l_pop, p_ir, l_ir_hold;
    wire        ld_t_commit1, ld_t_mate, ld_p_commit1, ld_p_mate;
    wire        ld_stopped, nf_v, ir_hold_t, ir_hold_p, ir_rel, fresh_c, fresh_t, fresh_p;
    wire [7:0]  ir_c, ir_l, nf_op;
    wire [19:0] ir_addr_c, ir_addr_l, nf_addr;
    wire [2:0]  need_c, need_t, need_p;
    v35_fmt_t   fmt_c, fmt_l, nf_fmt, fmt_mt, fmt_mp;
    v35_cls_t   cls_c, cls_l;
    // the sequencer
    wire        t_start, t_done, t_flush, t_halt, ask_d, ask_t, rt_set, cnt_take, sh_set;
    wire        imm16_c, imm16_t, imm16_p, nop_cand, abort_loop, halting, halted, wb_hold;
    wire        latch_wait, relatch, relatch_late, retire, post_t, post_p, lx_hold, idle_adj;
    wire        p_start, p_k, p_done, p_io_nx, ask_p, run_e, aim_next, dec_miss, io_drop;
    wire        io_drop_loop;
    wire        wl_fill_t, wl_fill_p, start_any;
    wire        retire_p, floor_set, sreg_hold_set, gdisp_act, ea_act_c, ea_act_x, disp_t;
    wire        disp_p, disp_ext, irh_set_t, irh_set_p, irh_clr_t, irh_clr_p, take_now, unit_md;
    wire [3:0]  floor_nb;
    wire [2:0]  sidle;
    req_t       ptm_t, ptm_p;
    wire [1:0]  t_k, relatch_n;
    wire        t_sth, t_sth_inf, p_sth, p_sth_inf, rs_set;
    wire [5:0]  t_sth_n, p_sth_n;
    wire [3:0]  rs_n;
    wire [9:0]  sh_n;
    wire signed [9:0] rt_n;
    uc_row_t    prow_t, prow_p;
    wire [6:0]  psetup_t, psetup_p;
    wire        pfnv_t, pfnv_p;
    wire [6:0]  pfn_t, pfn_p;
    wire [1:0]  plead_t, plead_p;
    v35_fmt_t   fmt_e;
    wire [4:0]  eu_wait;
    wire [10:0] eu_res;
    // the datapath
    req_t       rq_t, rq_p;
    wire [19:0] t_flush_addr, eu_pc, ea_live;
    wire [15:0] wd_live, wd_imm;
    wire [1:0]  g_dsel;
    wire [15:0] sfr_data;
    wire [8:0]  cnt;
    wire [7:0]  cl_c, cl_e;
    wire [15:0] psw_c, psw_e, cw_c, cw_e;
    wire [3:0]  mneg;
    wire        eu_miss;
    wire [6:0]  ra_next, rb_next, wa_addr;
    wire        wa_en;
    wire [1:0]  wa_be;
    wire [15:0] wa_data, ra_data, rb_data;

    // ---------------------------------------------------------------- the bus unit
    wire c_a0, c_a19, c_a18_ube, c_mreq_n, c_mstb_n, c_iostb_n, c_read_write, c_refrq_n;
    wire [8:0] c_mux_address;
    wire [15:0] c_data_out;
    v35_bus bus (
        .clock, .reset_n(core_reset_n), .ce, .ce_mid, .wtc, .rfm,
        .g_start, .g_kind, .g_addr, .g_width, .g_data, .g_ext, .g_b2b,
        .g_thru, .g_after_post(g_pfa), .g_lea_start(1'b0),
        .g_disp_in_flight(1'b0), .g_ir_before(ir_v_p && !t_flush), .g_take_near(1'b0), .g_abort,
        .g_slot, .g_wl_io, .g_dsel, .wd_imm, .disp_take(disp_t),
        .take_any(t_k != 2'd0 || p_k), .flush_now(t_flush), .start_any, .wl_fill_t, .wl_fill_p,
        .busy(b_busy), .free(b_free), .cur_kind(b_cur_kind), .cur_pos(b_cur_pos),
        .cur_left(b_cur_left), .cur_on_start(b_cur_on_start), .in_wait(b_in_wait),
        .fetch_inflight(b_fetch_inflight), .fetch_past_b2(b_fetch_past_b2),
        .fetch_end_prev(b_fetch_end_prev), .cpu_end_prev(b_cpu_end_prev),
        .fetch_since(b_fetch_since),
        .fetch_run_prev(b_fetch_run_prev), .io_win(b_io_win), .wl_busy(b_wl_busy),
        .wl_busy_x(b_wl_busy_x), .dlv_v(b_dlv_v), .dlv_kind(b_dlv_kind), .dlv_addr(b_dlv_addr),
        .dlv_width(b_dlv_width), .done_data(b_done_data), .abort_busy(b_abort_busy),
        .abort_last(b_abort_last), .abort_done(b_abort_done), .fetch_len(b_fetch_len),
        .grant_len(b_grant_len), .error(b_error), .w3_v, .w3_rel,
        .cur_thru(b_cur_thru), .cur_b2b_pfa(b_cur_b2b_pfa), .cf_tn(b_cf_tn), .cf_irb(b_cf_irb),
        .prev_imm(b_prev_imm),
        .a0(c_a0), .a19(c_a19), .a18_ube(c_a18_ube), .mux_address(c_mux_address),
        .data_out(c_data_out), .mreq_n(c_mreq_n), .mstb_n(c_mstb_n), .iostb_n(c_iostb_n),
        .read_write(c_read_write), .refrq_n(c_refrq_n), .data_in
    );
    wire dlv_fetch = b_dlv_v && b_dlv_kind == K_FETCH;
    wire dlv_other = b_cpu_end_prev;
    wire fetch_last = b_busy && b_cur_kind == K_FETCH && b_cur_left == 3'd1;

    // ---------------------------------------------------------------- the queue
    v35_queue queue (
        .clock, .reset_n(core_reset_n), .ce, .reset_addr(20'hFFFF0),
        .dlv_fetch, .dlv_other, .dlv_addr(b_dlv_addr), .dlv_data(b_done_data),
        .abort_done(b_abort_done), .abort_busy(b_abort_busy), .fetch_last,
        .fetch_inflight_c(b_fetch_inflight), .fetch_since_c(b_fetch_since),
        .xs_start, .fh_set, .fh_n, .ox_set, .nt_set, .nt_dbnz, .ou_set, .ou_n, .xs_done,
        .ff_set, .ff_n, .ff_t, .ff_t0, .ntb_ok, .xfer_x, .nb_now, .dec_inf, .dec_since, .xk_c, .xk_t, .xk_p, .lea_xk_c, .lea_xk_t, .lea_xk_p, .th_arm_t, .th_arm_p, .th_cvt, .th_lift_t, .th_lift_p,
        .fl_c, .fl_t, .fl_p, .fl_end_t, .fl_end_t2, .fl_end_p, .pgb2b_e, .halted, .res0_e,
        .pg_act_e(pfs_e || slot_pf_e), .cf_tn(b_cf_tn), .cf_irb(b_cf_irb), .start_any,
        .t_pops(t_k), .t_commit(t_done), .t_commit1(ld_t_commit1), .t_take(t_k != 2'd0),
        .t_mate(ld_t_mate), .t_disp(disp_t), .p_disp(disp_p), .t_start, .t_flush, .t_flush_addr, .t_sth, .t_sth_inf, .t_sth_n, .p_sth, .p_sth_inf, .p_sth_n, .rs_set, .rs_n,
        .cnt_take, .sh_set, .sh_n,
        .ask_d, .ask_t, .rt_set, .rt_n,
        .need_c, .ir_v_c, .imm16_c, .need_t, .ir_v_t, .imm16_t, .ir_hold(l_ir_hold),
        .ir_hold_t, .ir_hold_p, .ir_rel, .ea_act_c, .ea_act_x, .fresh_c, .fresh_t, .fresh_p,
        .l_pop, .need_l(need_t),
        .g_fetch, .g_abort, .g_mem_waiting, .abort_loop, .rq_set_x, .g_slot_fetch,
        .g_io(g_eu && k_io(g_kind)), .unit_md,
        .p_run(retick && k_io(g_kind)), .p_pops({1'b0, p_k}), .p_commit(p_done),
        .p_commit1(ld_p_commit1), .p_take(p_k), .p_ir, .p_start, .ask_p, .ir_v_p, .need_p,
        .imm16_p, .nop_cand, .io_drop, .io_drop_loop,
        .vb0, .vb1, .vb2, .vb3, .vb4, .head_addr, .avail_c, .arrived_now, .inflight_c,
        .inflight_x, .completed_now, .room_c, .room_x, .room_p0, .stored_c, .stored_l,
        .lat_c, .lat_x, .asked_d, .asked_t, .asked_p, .flag_x, .want_x, .want_c, .rq_v_x,
        .rq_now_x, .rq_old_c, .rq_old_p, .rq_clr_p, .b2b_now, .triple_x, .retry_o(q_retry),
        .retry_loop_o(q_retry_loop), .fetch_addr_o(q_fetch_addr), .io_held_o(io_held),
        .io_hold_x, .latch_start_now, .nop_held_o(nop_held), .shift_latch, .rq_ir_hold,
        .b2b_next, .room_e, .flag_e, .rq_v_e, .io_unit_drop, .room_c0, .overflow(q_overflow)
    );

    // ---------------------------------------------------------------- the loader
    v35_loader loader (
        .clock, .reset_n(core_reset_n), .ce,
        .vb0, .vb1, .vb2, .vb3, .vb4, .head_addr, .avail_c,
        .t_start, .t_k_in(t_k), .t_flush, .t_halt, .lx_hold, .idle_adj,
        .p_start, .p_k_in(p_k), .p_io_nx,
        .irh_set_t, .irh_clr_t, .eu_issue, .irh_set_p, .irh_clr_p,
        .irh_pg_t, .irh_pg_p, .mt_sub_t, .mt_sub_p,
        .ir_v_c, .ir_c, .ir_addr_c, .fmt_c, .cls_c, .fmt_mt, .need_c,
        .t_commit1(ld_t_commit1), .t_mate(ld_t_mate), .need_t, .ir_v_t,
        .l_pop, .ir_l, .ir_addr_l, .fmt_l, .cls_l, .ir_v_l,
        .p_commit1(ld_p_commit1), .fmt_mp, .p_mate(ld_p_mate), .p_ir, .need_p, .ir_v_p,
        .ir_hold(l_ir_hold), .ir_hold_t, .ir_hold_p, .ir_rel, .fresh_c, .fresh_t, .fresh_p,
        .stopped_o(ld_stopped),
        .nf_v, .nf_fmt, .nf_op, .nf_addr
    );

    // ---------------------------------------------------------------- the microcode sequencer
    v35_ucode ucode (
        .clock, .reset_n(core_reset_n), .ce,
        .ir_v_c, .fmt_c, .cls_c, .cls_l, .fmt_mt, .fmt_mp, .ir_c, .ir_v_l, .fmt_l, .ir_l,
        .ir_addr_c, .ir_addr_l, .vb0, .vb1, .vb2, .vb3, .avail_c, .l_pop, .arrived_now,
        .lat_c, .lat_x, .inflight_c, .inflight_x, .completed_now, .room_c, .room_p0,
        .stored_c, .stored_l, .rq_old_c, .rq_old_p, .b2b_now, .asked_d, .asked_t, .asked_p,
        .retry(q_retry), .retry_loop(q_retry_loop), .latch_start_now, .shift_latch, .room_e,
        .nf_v, .nf_fmt, .nf_addr,
        .bus_free(b_free), .busy(b_busy), .cur_kind(b_cur_kind), .cur_left(b_cur_left),
        .cur_on_start(b_cur_on_start), .fetch_inflight(b_fetch_inflight),
        .fetch_past_b2(b_fetch_past_b2), .fetch_since(b_fetch_since), .in_wait(b_in_wait),
        .abort_busy(b_abort_busy), .abort_last(b_abort_last), .wl_busy(b_wl_busy),
        .wl_busy_x(b_wl_busy_x), .grant_len(b_grant_len),
        .own_two, .own_h2, .w3_v, .w3_rel, .fetch_last_c(fetch_last), .str_last, .str_exit,
        .edone, .edone_t, .povr_t, .povr_p,
        .slot_wait_c, .slot_wait_p, .slot_det_c, .slot_det_p, .post_ok_c, .post_ok_p,
        .slot_memw_c, .dw_blk_c(dwq_c || (dws_c && b_busy && k_io(b_cur_kind))),
        .dw_blk_p(dwq_c || dws_c), .own_issued, .own_done, .own_done_p,
        .room_c0, .fetch_end_prev(b_fetch_end_prev), .io_unit_drop, .want_c, .fetch_len(b_fetch_len),
        .dec_inf, .dec_since, .abort_done(b_abort_done), .head_odd(head_addr[0]),
        .xs_start, .fh_set, .fh_n, .ox_set, .nt_set, .nt_dbnz, .ou_set, .ou_n, .xs_done,
        .ff_set, .ff_n, .ff_t, .ff_t0, .ntb_ok, .xfer_x, .xk_c, .xk_t, .xk_p, .lea_xk_c, .lea_xk_t, .lea_xk_p, .th_arm_t, .th_arm_p, .th_cvt, .th_lift_t, .th_lift_p, .mf_old,
        .g_fetch, .g_abort, .g_abort_lat, .retick, .g_io(g_eu && k_io(g_kind)),
        .cnt, .cl_c, .cl_e, .psw_c, .psw_e, .cw_c, .cw_e, .mneg, .bf_cross, .bfcost, .bf_ok,
        .g_eu, .g_thru, .cur_thru(b_cur_thru), .irh_pg_t, .irh_pg_p, .mt_sub_t, .mt_sub_p,
        .fl_c, .fl_t, .fl_p, .fl_end_t, .fl_end_t2, .fl_end_p, .pfs_x, .pfs_e, .pimm_x, .pcl_x,
        .pcl_fs,
        .pgb2b_e, .res0_e, .bcd_idle,
        .t_start, .t_k, .t_done, .t_flush, .t_halt, .ask_d, .ask_t, .cnt_take,
        .t_sth, .t_sth_inf, .t_sth_n, .p_sth, .p_sth_inf, .p_sth_n, .rs_set, .rs_n,
        .rt_set, .rt_n, .sh_set, .sh_n, .imm16_c, .imm16_t, .nop_cand, .abort_loop, .halting,
        .halted_o(halted), .wb_hold, .latch_wait, .relatch, .relatch_late, .relatch_n, .retire,
        .retire_p, .floor_set, .floor_nb, .sreg_hold_set, .gdisp_act, .ea_act_c, .ea_act_x,
        .disp_t, .disp_p, .disp_ext, .irh_set_t, .irh_set_p, .irh_clr_t, .irh_clr_p, .take_now,
        .sidle_o(sidle), .unit_md,
        .lx_hold, .idle_adj,
        .post_t, .prow_t, .psetup_t, .pfnv_t, .pfn_t, .plead_t, .ptm_t, .ptm_p,
        .post_p, .prow_p, .psetup_p, .pfnv_p, .pfn_p, .plead_p,
        .p_start, .p_k, .p_done, .p_io_nx, .ask_p, .io_drop, .io_drop_loop, .imm16_p,
        .wl_fill_t, .wl_fill_p,
        .start_any, .run_e, .aim_next, .fmt_e,
        .wait_o(eu_wait), .res_o(eu_res), .dec_miss, .p_flush
    );

    // ---------------------------------------------------------------- the datapath
    v35_eu eu (
        .clock, .reset_n(core_reset_n), .ce,
        .t_start, .p_start, .fmt_c, .ir_c, .ir_addr_c, .fmt_l, .fmt_mt, .fmt_mp, .ir_l,
        .ir_addr_l, .vb0, .vb1, .vb2, .vb3, .t_k, .l_pop, .p_k,
        .run_e, .aim_next, .fmt_e, .t_flush, .nf_v, .nf_fmt, .nf_op,
        .post_t, .prow_t, .psetup_t, .pfnv_t, .pfn_t, .plead_t,
        .post_p, .prow_p, .psetup_p, .pfnv_p, .pfn_p, .plead_p, .ptm_t, .ptm_p,
        .own_done(own_dlv), .own_two, .dlv_kind(b_dlv_kind), .dlv_addr(b_dlv_addr), .dlv_width(b_dlv_width),
        .dlv_data(b_done_data),
        .ra_next, .wa_en, .wa_addr, .wa_be, .wa_data, .ra_data, .rb_next, .rb_data,
        .rq_t, .rq_p, .ea_live, .wd_live, .wd_imm, .cnt, .cl_c, .cl_e, .psw_c, .psw_e, .cw_c, .cw_e, .mneg, .t_flush_addr, .sfr_data,
        .edone, .edone_t, .povr_t, .povr_p, .str_last, .str_exit,
        .f_end(xs_done), .bf_cross, .bfcost, .bf_ok,
        .pc_o(eu_pc), .miss_o(eu_miss)
    );

    // ---------------------------------------------------------------- the register RAM
    v35_regram regram (
        .clock, .ce, .ra_next, .wa_en, .wa_addr, .wa_be, .wa_data, .ra_data, .rb_next, .rb_data
    );

    // ---------------------------------------------------------------- the arbiter
    v35_arbiter arbiter (
        .clock, .reset_n(core_reset_n), .ce,
        .post_t, .rq_t, .post_p, .rq_p, .retire_t(retire), .retire_p,
        .relatch, .relatch_late, .floor_set, .floor_nb, .sreg_hold_set,
        .halting, .halted, .need(need_t), .wb_hold, .latch_wait, .gdisp_act,
        .ea_b2b_act(ea_act_x), .take_now, .ea_live, .wd_live, .sidle,
        .want_x, .rq_v_x, .rq_now_x, .rq_v_end(rq_v_e),
        .rq_now_end(rq_now_x || rq_set_x || rq_ir_hold), .rq_old_c, .b2b_now, .room_x,
        .inflight_c, .triple_x, .lat_x, .arrived_now, .io_hold_x, .xfer_x,
        .free(b_free), .busy(b_busy), .cur_io(b_busy && k_io(b_cur_kind)), .cur_kind(b_cur_kind), .mf_old,
        .fetch_inflight(b_fetch_inflight), .in_wait(b_in_wait),
        .fetch_end_prev(b_fetch_end_prev), .fetch_run_prev(b_fetch_run_prev),
        .io_win(b_io_win), .fetch_len(b_fetch_len), .fetch_addr(q_fetch_addr),
        .dlv_eu(dlv_other),
        .p_take(p_k), .t_start, .pfs_x, .pimm_x, .pcl_x, .pcl_fs, .fetch_since(b_fetch_since),
        .cur_b2b_pfa(b_cur_b2b_pfa), .cur_thru(b_cur_thru), .prev_imm(b_prev_imm), .bcd_idle,
        .g_thru, .g_pfa, .slot_pf_e,
        .g_start, .g_kind, .g_addr, .g_width, .g_data, .g_fetch, .g_eu, .g_slot, .g_slot_fetch,
        .g_abort, .g_abort_lat, .g_mem_waiting, .g_b2b, .rq_set_x, .retick, .eu_issue, .g_ext,
        .g_dsel,
        .disp_ext, .slot_wait_c, .slot_wait_p, .slot_det_c, .slot_det_p, .post_ok_c,
        .post_ok_p, .slot_memw_c, .dwq_c, .dws_c, .own_issued, .own_done, .own_done_p,
        .own_dlv, .own_two, .own_h2, .g_wl_io, .own_pos, .count_o(a_count), .ready_o(a_ready), .why_o(a_why)
    );

    // ---------------------------------------------------------------- refresh (not served)
    wire rf_pending, rf_load;
    wire [7:0] rf_value;
    wire [23:0] rf_state_r, rf_state_e;
    v35_refresh #(.STATE_W(24)) refresh (
        .clock, .reset_n(core_reset_n), .ce, .en(1'b1), .rfm, .init_counter(7'(INIT_COUNTER)),
        .start(1'b0), .wr(1'b0), .wr_value(8'd0),
        .pending(rf_pending), .rfm_load(rf_load), .rfm_value(rf_value),
        .state_r(rf_state_r), .state_e(rf_state_e)
    );

    // ---------------------------------------------------------------- the SFR store
    // captured at its issue, written at its cycle's end with the EU's datum then (a store_imm
    // takes its immediate after the store issued)
    reg sfr_open = 1'b0;
    always @(posedge clock) begin
        sfr_wr <= 1'b0;
        if (!core_reset_n) begin
            sfr_open <= 1'b0;
        end else if (ce) begin
            if (g_start && g_kind == K_WRITE && g_addr >= SFR_PAGE) begin
                sfr_open <= 1'b1;
                sfr_a <= g_addr;
                sfr_w <= g_width;
            end else if (sfr_open && dlv_other) begin
                sfr_open <= 1'b0;
                sfr_wr <= 1'b1;
                sfr_d <= sfr_data;
            end
        end
    end

    // ---------------------------------------------------------------- pins
    always @* begin
        a0 = c_a0;
        a19 = c_a19;
        a18_ube = c_a18_ube;
        mux_address = c_mux_address;
        data_out = c_data_out;
        mreq_n = c_mreq_n;
        mstb_n = c_mstb_n;
        iostb_n = c_iostb_n;
        read_write = c_read_write;
        refrq_n = c_refrq_n;
        if (!core_run) begin
            a0 = 1'b0;
            a19 = 1'b0;
            a18_ube = 1'b0;
            mux_address = 9'd0;
            mreq_n = 1'b1;
            mstb_n = 1'b1;
            iostb_n = 1'b1;
            read_write = 1'b1;
            refrq_n = rx_refrq_n;
        end
    end

`ifdef V35S_CORE_V35
    // ---------------------------------------------------------------- the trace hook
    v35_trace trace (
        .clock, .reset_n(core_reset_n), .ce,
        .g_start, .g_kind, .g_addr, .g_width, .g_len(b_grant_len),
        .start_t(t_start), .start_p(p_start), .scls_t(fmt_c.cls), .scls_p(fmt_l.cls),
        .pc_t(ir_addr_c), .pc_p(ir_addr_l),
        .takes({1'b0, t_k} + {2'd0, p_k}), .loads({1'b0, l_pop} + {1'b0, p_ir}),
        .post(post_t || post_p), .post_kind(post_t ? rq_t.kind : rq_p.kind), .issue(g_eu), .b2b(b2b_next), .abort(g_abort),
        .room(room_e), .flag(flag_e), .why(eu_wait), .hold(a_why), .dec_miss, .wlost(eu_miss)
    );

    // diagnostics (+v35_diag): bus and queue errors on stderr; the decode-ahead misses (a
    // start a clock late) and lost register writes counted
    reg diag = 1'b0;
    reg err_seen = 1'b0;
    integer n_dec = 0;
    initial diag = $test$plusargs("v35_diag");
    always @(posedge clock) begin
        if (!core_reset_n)
            err_seen <= 1'b0;
        else if (ce) begin
            if ((b_error || q_overflow || eu_miss) && !err_seen) begin
                err_seen <= 1'b1;
                if (diag)
                    $display("v35: %s", b_error ? "a bus start on a busy bus"
                                        : q_overflow ? "queue overflow" : "a register write lost");
            end
            if (p_flush && diag)
                $display("v35: a FLUSH row in the P pass (not acted on: the S5 budget)");
            if (dec_miss) begin
                n_dec <= n_dec + 1;
                if (diag)
                    $display("v35: decode-ahead miss %0d", n_dec + 1);
            end
        end
    end
`endif

    wire unused = &{1'b0, ready, x_fall, input_levels, idb, prc[7:2], ld_p_mate, ld_stopped,
                    b_cur_pos, b_dlv_width, lat_c, rq_clr_p, io_held, nop_held, a_count, own_pos,
                    a_ready, rf_pending, rf_load, rf_value, rf_state_r, rf_state_e, eu_pc,
                    eu_res, flag_x, b_in_wait, b_fetch_since, b_error, b2b_next, flag_e,
                    q_overflow, room_e, eu_wait, dec_miss, eu_miss, relatch_n, a_why, nb_now, p_flush};
endmodule
