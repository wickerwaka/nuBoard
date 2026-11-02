`timescale 1ns/1ps

// V35S core v2: the slot module (docs/v35s-core-v2.md, "Architecture"), stage S2: the front
// end (bus unit, prefetch queue, loader, a fetch + scripted-request arbiter) driven by a
// scripted EU (v35_eu_script.sv, replaced by the microcode sequencer and datapath in S3).
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
// in S2 (no refresh-on family is in the S2 gate; the prelude's refreshes before its RFM store
// are not run, so the pre-window differs from silicon there).
//
// The six stages of a CPU clock (one registered update at `ce`, feed-forward inside it):
//   S0  every module's registers                         (bus: busy, delivery, abort, ...)
//   S1  v35_queue: arrival, retry_after, room_c          (C, A)
//   S2  v35_eu_script pass t, v35_loader take/start      (T)
//   S3  v35_loader IR load; v35_queue room_x, wants_fetch (L)
//   S4  v35_arbiter: counting and the grant              (X)
//   S5  v35_eu_script pass p, v35_loader P, v35_queue P  (P)
//   S6  every module's next state; v35_queue check / b2b (E)
module v35_top
    import v35_front_pkg::*;
    import v35_stub_pkg::*;
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
    wire [2:0]  g_kind;
    wire [19:0] g_addr;
    wire [1:0]  g_width;
    wire [15:0] g_data;
    wire        slot_v, slot_wait_c, slot_wait_p, slot_det_c, slot_det_p, own_issued, own_done;
    wire [6:0]  a_count;
    wire        a_ready;
    // queue
    wire [7:0]  vb0, vb1, vb2, vb3, vb4;
    wire [19:0] head_addr, q_fetch_addr;
    wire [3:0]  avail_c, stored_c, stored_l;
    wire        arrived_now, inflight_c, inflight_x, completed_now, lat_c, lat_x;
    wire        asked_d, asked_t, asked_p, flag_x, want_x, rq_v_x, rq_now_x, rq_old_c, rq_old_p;
    wire        rq_clr_p, b2b_now, triple_x, q_retry, q_retry_loop, io_held, nop_held;
    wire        io_hold_x, latch_start_now, rq_ir_hold, b2b_next, flag_e, q_overflow;
    wire signed [4:0] room_c, room_x, room_p0, room_e;
    // loader
    wire        ir_v_c, ir_v_t, ir_v_l, ir_v_p, l_pop, p_ir, l_ir_hold;
    wire        ld_t_done, ld_t_commit1, ld_t_mate, ld_p_k, ld_p_done, ld_p_commit1, ld_p_mate;
    wire        ld_stopped;
    wire [7:0]  ir_c, ld_t_b0, ld_t_b1, ld_p_b0;
    wire [19:0] ir_addr_c, ir_addr_l;
    wire [2:0]  need_c, need_t, need_p;
    wire [1:0]  ld_t_k;
    fmt_t       fmt_c, fmt_l;
    // EU
    wire        t_start, t_done, t_wide, t_flush, t_halt, t_fhold, ask_d, ask_t, rt_set;
    wire        imm16_c, imm16_t, imm16_p, nop_cand, abort_loop, halting, halted, wb_hold;
    wire        latch_wait, relatch, relatch_late, retire, post_t, post_p;
    wire        p_start, p_k, p_done, p_io_nx, ask_p;
    wire        wl_fill_t, wl_fill_p, start_any;
    wire [1:0]  t_k, relatch_n;
    wire [19:0] t_flush_addr, eu_pc;
    wire signed [9:0] rt_n;
    req_t       rq_t, rq_p;
    wire [15:0] sfr_data;
    wire [6:0]  eu_cls;
    wire [3:0]  eu_wait;
    wire [10:0] eu_res;

    // ---------------------------------------------------------------- the bus unit
    wire c_a0, c_a19, c_a18_ube, c_mreq_n, c_mstb_n, c_iostb_n, c_read_write, c_refrq_n;
    wire [8:0] c_mux_address;
    wire [15:0] c_data_out;
    v35_bus bus (
        .clock, .reset_n(core_reset_n), .ce, .ce_mid, .wtc, .rfm,
        .g_start, .g_kind, .g_addr, .g_width, .g_data, .g_ext(1'b0), .g_b2b,
        .g_thru(1'b0), .g_after_post(1'b0), .g_lea_start(1'b0),
        .g_disp_in_flight(1'b0), .g_ir_before(1'b0), .g_take_near(1'b0), .g_abort, .start_any, .wl_fill_t, .wl_fill_p,
        .busy(b_busy), .free(b_free), .cur_kind(b_cur_kind), .cur_pos(b_cur_pos),
        .cur_left(b_cur_left), .cur_on_start(b_cur_on_start), .in_wait(b_in_wait),
        .fetch_inflight(b_fetch_inflight), .fetch_past_b2(b_fetch_past_b2),
        .fetch_end_prev(b_fetch_end_prev), .cpu_end_prev(b_cpu_end_prev),
        .fetch_since(b_fetch_since),
        .fetch_run_prev(b_fetch_run_prev), .io_win(b_io_win), .wl_busy(b_wl_busy),
        .wl_busy_x(b_wl_busy_x), .dlv_v(b_dlv_v), .dlv_kind(b_dlv_kind), .dlv_addr(b_dlv_addr),
        .dlv_width(b_dlv_width), .done_data(b_done_data), .abort_busy(b_abort_busy),
        .abort_last(b_abort_last), .abort_done(b_abort_done), .fetch_len(b_fetch_len),
        .grant_len(b_grant_len), .error(b_error),
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
        .t_pops(t_k), .t_commit(t_done), .t_commit1(ld_t_commit1), .t_take(t_k != 2'd0),
        .t_mate(ld_t_mate), .t_disp(1'b0), .t_start, .t_flush, .t_flush_addr, .t_fhold,
        .ask_d, .ask_t, .rt_set, .rt_n,
        .need_c, .ir_v_c, .imm16_c, .need_t, .ir_v_t, .imm16_t, .ir_hold(l_ir_hold),
        .l_pop, .need_l(need_t),
        .g_fetch, .g_abort, .g_mem_waiting, .abort_loop, .rq_set_x,
        .p_run(retick && k_io(g_kind)), .p_pops({1'b0, p_k}), .p_commit(p_done),
        .p_commit1(ld_p_commit1), .p_take(p_k), .p_ir, .p_start, .ask_p, .ir_v_p, .need_p,
        .imm16_p, .nop_cand,
        .vb0, .vb1, .vb2, .vb3, .vb4, .head_addr, .avail_c, .arrived_now, .inflight_c,
        .inflight_x, .completed_now, .room_c, .room_x, .room_p0, .stored_c, .stored_l,
        .lat_c, .lat_x, .asked_d, .asked_t, .asked_p, .flag_x, .want_x, .rq_v_x,
        .rq_now_x, .rq_old_c, .rq_old_p, .rq_clr_p, .b2b_now, .triple_x, .retry_o(q_retry),
        .retry_loop_o(q_retry_loop), .fetch_addr_o(q_fetch_addr), .io_held_o(io_held),
        .io_hold_x, .latch_start_now, .nop_held_o(nop_held), .rq_ir_hold, .b2b_next,
        .room_e, .flag_e, .overflow(q_overflow)
    );

    // ---------------------------------------------------------------- the loader
    v35_loader loader (
        .clock, .reset_n(core_reset_n), .ce,
        .vb0, .vb1, .vb2, .vb3, .vb4, .head_addr, .avail_c,
        .t_start, .t_tk_go(t_k != 2'd0), .t_tk_left({1'b0, t_k}), .t_tk_wide(1'b1), .t_flush,
        .t_halt, .p_start, .p_tk_go(p_k), .p_tk_left(3'd1), .p_io_nx,
        .ir_v_c, .ir_c, .ir_addr_c, .fmt_c, .need_c,
        .t_k(ld_t_k), .t_done(ld_t_done), .t_b0(ld_t_b0), .t_b1(ld_t_b1),
        .t_commit1(ld_t_commit1), .t_mate(ld_t_mate), .need_t, .ir_v_t,
        .l_pop, .ir_addr_l, .fmt_l, .ir_v_l,
        .p_k(ld_p_k), .p_done(ld_p_done), .p_b0(ld_p_b0), .p_commit1(ld_p_commit1),
        .p_mate(ld_p_mate), .p_ir, .need_p, .ir_v_p, .ir_hold(l_ir_hold),
        .stopped_o(ld_stopped)
    );

    // ---------------------------------------------------------------- the EU (scripted, S2)
    v35_eu_script eu (
        .clock, .reset_n(core_reset_n), .ce,
        .ir_v_c, .fmt_c, .ir_addr_c, .ir_v_l, .fmt_l, .ir_addr_l,
        .vb0, .vb1, .vb2, .vb3, .avail_c, .l_pop, .arrived_now,
        .lat_c, .lat_x, .inflight_c, .inflight_x, .completed_now, .room_c, .room_p0,
        .stored_c, .stored_l, .rq_old_c, .rq_old_p, .b2b_now, .asked_d, .asked_t, .asked_p,
        .retry(q_retry), .retry_loop(q_retry_loop), .latch_start_now,
        .bus_free(b_free), .busy(b_busy), .cur_kind(b_cur_kind), .cur_left(b_cur_left),
        .cur_on_start(b_cur_on_start), .fetch_inflight(b_fetch_inflight),
        .fetch_past_b2(b_fetch_past_b2), .fetch_since(b_fetch_since),
        .abort_busy(b_abort_busy), .abort_last(b_abort_last), .wl_busy(b_wl_busy),
        .wl_busy_x(b_wl_busy_x), .grant_len(b_grant_len),
        .slot_wait_c, .slot_wait_p, .slot_det_c, .slot_det_p, .own_issued, .own_done,
        .g_fetch, .g_abort, .retick, .g_io(g_eu && k_io(g_kind)),
        .t_start, .t_k, .t_done, .t_wide, .t_flush, .t_flush_addr, .t_halt, .t_fhold, .ask_d,
        .ask_t, .rt_set, .rt_n, .imm16_c, .imm16_t, .nop_cand, .abort_loop, .halting,
        .halted_o(halted), .wb_hold, .latch_wait, .relatch, .relatch_late, .relatch_n, .retire,
        .post_t, .rq_t, .post_p, .rq_p,
        .p_start, .p_k, .p_done, .p_io_nx, .ask_p, .imm16_p, .wl_fill_t, .wl_fill_p,
        .start_any, .sfr_data,
        .pc_o(eu_pc), .cls_o(eu_cls), .wait_o(eu_wait), .res_o(eu_res)
    );

    // ---------------------------------------------------------------- the arbiter
    v35_arbiter arbiter (
        .clock, .reset_n(core_reset_n), .ce,
        .post_t, .rq_t, .post_p, .rq_p, .retire,
        .relatch, .relatch_late, .relatch_n,
        .halting, .halted, .need(need_t), .wb_hold, .latch_wait,
        .want_x, .rq_v_x, .rq_now_x, .rq_v_end(rq_v_x || rq_ir_hold), .b2b_now, .room_x,
        .inflight_c, .triple_x, .lat_x, .arrived_now, .io_hold_x,
        .free(b_free), .busy(b_busy), .fetch_inflight(b_fetch_inflight), .in_wait(b_in_wait),
        .fetch_end_prev(b_fetch_end_prev), .fetch_run_prev(b_fetch_run_prev),
        .io_win(b_io_win), .fetch_len(b_fetch_len), .fetch_addr(q_fetch_addr),
        .win_hold(1'b0), .nowrite_slot(1'b0), .alu_busy(1'b0),
        .dlv_eu(dlv_other),
        .g_start, .g_kind, .g_addr, .g_width, .g_data, .g_fetch, .g_eu, .g_abort,
        .g_mem_waiting, .g_b2b, .rq_set_x, .retick,
        .slot_v, .slot_wait_c, .slot_wait_p, .slot_det_c, .slot_det_p, .own_issued, .own_done,
        .count_o(a_count), .ready_o(a_ready)
    );

    // ---------------------------------------------------------------- refresh (not served in S2)
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
        .room(room_e), .flag(flag_e), .why(eu_wait)
    );

    // diagnostics (+v35_diag): bus and queue errors on stderr
    reg diag = 1'b0;
    reg err_seen = 1'b0;
    initial diag = $test$plusargs("v35_diag");
    always @(posedge clock) begin
        if (!core_reset_n)
            err_seen <= 1'b0;
        else if (ce && (b_error || q_overflow) && !err_seen) begin
            err_seen <= 1'b1;
            if (diag)
                $display("v35: %s", b_error ? "a bus start on a busy bus" : "queue overflow");
        end
    end
`endif

    wire unused = &{1'b0, ready, x_fall, input_levels, idb, prc[7:2], ld_t_done, ld_t_b0, ld_t_b1,
                    ld_t_k, ld_p_k, ld_p_done, ld_p_b0, ld_p_mate, ld_stopped, ir_c, b_cur_pos,
                    b_dlv_width, lat_c, rq_clr_p, io_held, nop_held, slot_v, a_count, a_ready,
                    rf_pending, rf_load, rf_value, rf_state_r, rf_state_e, t_wide, eu_pc,
                    eu_cls, eu_res, flag_x, b_in_wait, b_fetch_since, b_error, b2b_next, flag_e,
                    q_overflow, room_e, eu_wait};     // (the trace hook's, V35S_CORE_V35)
endmodule
