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
// The six stages of a CPU clock (one registered update at `ce_a`, feed-forward inside it; (S7b) the
// enables `ce_a` / `ce_b` below):
//   S0  every module's registers                         (bus: busy, delivery, abort, ...)
//   S1  v35_queue: the delivery, the window and the count  (C, A)
//   S2  v35_ucode pass T, v35_loader take/start, v35_eu (the start's form, the takes'
//       bytes, the exec's function, the T post's request)  (T)
//   S3  v35_loader IR load; v35_queue the request line   (L)
//   S4  v35_arbiter: counting and the grant              (X)
//   S5  v35_ucode pass P, v35_loader P, v35_eu (the P post's request)  (P)
//   S6  every module's next state (the queue's pops, the bus unit's back-to-back sample);
//       the decode ahead (v35_loader) and
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
    wire sfr_wr;                        // ((S7b) at ce_a itself: tick A sees the new value)
    reg [19:0] sfr_a = 20'd0;
    reg [1:0] sfr_w = 2'd0;
    wire [15:0] sfr_d;
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

    // (S7b) the two enables of a CPU clock. The pins' timing is the model's (v35_biu's): a cycle
    // granted on a clock shows B1 from the CPU clock's edge after it, the strobes move at the
    // clock's middle, and a read's datum is on the pins at mid-B3, where the V35 samples it.
    // The core's clock is placed half a CPU clock later than that convention so that its first
    // tick starts from the sampled datum:
    //   ce_a  the CPU clock's middle (ce_mid): every architectural register, and the bus
    //         unit's datum register (the read latch). Tick A runs from here: S1 (arrival, from
    //         the registered datum) through S4 (the grant).
    //   ce_b  the CPU clock's edge: the pipeline registers that hold tick A's results; the
    //         pins' edge (B1's address, B2's column) takes the grant there. Tick B runs from
    //         here: S5, S6, ending at the next ce_a.
    // A clock's S5 / S6 results reach the pins half a CPU clock after the edge that ends the
    // model's clock: the write datum is driven at mid-B2 (README, Divergence 31); nothing else
    // on the pins depends on them. No input reaches logic without first landing in a register.
    // Simulation only: +v35_ceb=K puts ce_b K fabric ticks after ce_a (K = 1..3 in the harness's
    // eight-tick clock; the default is the edge, the target's second tick); the pins' edge
    // stays at the CPU clock's edge. The core's registers update on ce_a and ce_b only, so the
    // default runs exactly as at the target, two ticks a CPU clock, while the harness's pins
    // and its recording at 30 ns ticks are unchanged (+v35_ticks=2 names that variant).
    // ce_a waits for a ce_b since the core left reset (the ce_b registers then hold tick A's
    // results of the state the ce_a ends: the first clock after the reset exit included).
    wire ce_mid = state_mid;
    wire ce_e = state_start && core_run;            // the pins' edge
    reg  [2:0] ceb_age = 3'd7;          // fabric ticks since the CPU clock's middle (sat 7)
    reg        b_seen = 1'b0;
    wire       ce_b;
    always @(posedge clock) begin
        if (!reset_n)
            ceb_age <= 3'd7;
        else if (state_mid)
            ceb_age <= 3'd1;
        else if (ceb_age != 3'd7)
            ceb_age <= ceb_age + 3'd1;
        if (!core_reset_n)
            b_seen <= 1'b0;
        else if (ce_b)
            b_seen <= 1'b1;
    end
    wire ce_a = state_mid && core_run && b_seen;
`ifndef SYNTHESIS
    reg  [2:0] ceb_k = 3'd0;
    integer    ceb_arg = 0;
    initial begin
        if ($value$plusargs("v35_ceb=%d", ceb_arg) && ceb_arg >= 0 && ceb_arg <= 3
            && !$test$plusargs("v35_ticks=2"))
            ceb_k = 3'(ceb_arg);
    end
    assign ce_b = core_run && !state_mid && (ceb_k == 3'd0 ? state_start : ceb_age == ceb_k);
`else
    assign ce_b = core_run && state_start;
`endif
    wire ce = ce_a;                     // (the function bench's hook: o_ce)

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
    wire        g_start, g_fetch, g_eu, g_abort, g_b2b, retick;
    wire        g_slot, eu_issue, g_ext, own_done_p, own_dlv, a_mem_wait;
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
    // queue (Q1: the simple machine)
    wire [7:0]  qv0, qv1, qv2, qv3, vb0, vb1, vb2, vb3;
    wire [2:0]  ld_rd, ld_rd_b, ld_rel, e_avail, ld_need_t;
    wire        ld_stg;
    wire [19:0] q_fetch_addr;
    wire [2:0]  q_avail;
    wire        q_fetch_req, q_low, q_susp, b_b2b_now, head_odd;
    wire        q_word;                 // (Q2)
    wire        ld_l_load, ld_p_load;
    // (S5a) the transfers' holds
    wire        xs_done;
    // (S5a) the strings
    wire        edone, edone_t, povr_t, povr_p, str_last, str_exit, own_h2, g_wl_io, w3_v;
    wire signed [4:0] w3_rel;
    wire        p_flush, voc_miss;
    wire        mf_old;
    // (S5b) the 0F page
    wire        b_cur_thru, b_cur_b2b_pfa, b_cf_tn, b_cf_irb, b_prev_imm;
    wire        g_thru, g_pfa, slot_pf_e;
    wire        irh_pg_t, irh_pg_p, pfs_x, pfs_e;
    wire        pimm_x, bcd_idle, bf_cross, bf_ok;
    wire [3:0]  mt_sub_t, mt_sub_p;
    wire [10:0] bfcost;
    // loader
    wire        ir_v_c, ir_v_l, ir_v_p, l_pop, p_ir;
    wire        ld_stopped, nf_v;
    wire [7:0]  ir_c, ir_l, nf_op;
    wire [19:0] ir_addr_c, ir_addr_l, nf_addr;
    v35_fmt_t   fmt_c, fmt_l, nf_fmt, fmt_mt, fmt_mp;
    wire        ok_c, ok_l, ld_p_mmiss;
    v35_cls_t   cls_c;
    // the sequencer
    wire        t_start, t_done, t_flush, t_halt;
    wire        halting, halted, wb_hold;
    wire        latch_wait, relatch, relatch_late, retire, post_t, post_p, lx_hold, idle_adj;
    wire        p_start, p_k, p_done, p_io_nx, run_e, aim_next, dec_miss;
    wire        wl_fill_t, wl_fill_p, start_any;
    wire        retire_p, floor_set, sreg_hold_set, gdisp_act, ea_act_x, disp_t, lea_room_t, mate_t;
    wire        disp_ext, irh_set_t, irh_set_p, irh_clr_t, irh_clr_p, take_now;
    wire [3:0]  floor_nb;
    wire [2:0]  sidle;
    req_t       ptm_t, ptm_p;
    wire [1:0]  t_k, relatch_n;
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
    wire [19:0] t_flush_addr, eu_pc, ea_live, ps_base;
    wire [15:0] t_flush_off;
    wire [15:0] ea_lo;
    wire [15:0] wd_live, wd_imm;
    wire        wd_rdy;
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

    // (S7b) the slot's own ce_b registers: tick A's strobes that the nets between the modules
    // combine for tick B
    reg         t_flush_b = 1'b0, g_start_b = 1'b0;
    reg  [2:0]  g_kind_b = K_NONE;
    reg  [19:0] g_addr_b = 20'd0;
    reg  [1:0]  g_width_b = BW_WORD;
    always @(posedge clock) begin
        if (ce_b) begin
            t_flush_b <= t_flush;
            g_start_b <= g_start;
            g_kind_b <= g_kind;
            g_addr_b <= g_addr;
            g_width_b <= g_width;
        end
    end

    // ---------------------------------------------------------------- the bus unit
    wire c_a0, c_a19, c_a18_ube, c_mreq_n, c_mstb_n, c_iostb_n, c_read_write, c_refrq_n;
    wire [8:0] c_mux_address;
    wire [15:0] c_data_out;
    v35_bus bus (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b, .ce_e, .ce_mid, .wtc, .rfm,
        .g_start, .g_kind, .g_addr, .g_width, .g_data, .g_ext, .g_b2b,
        .g_thru, .g_after_post(g_pfa), .g_lea_start(1'b0),
        .g_disp_in_flight(1'b0), .g_ir_before(ir_v_p && !t_flush_b), .g_take_near(1'b0), .g_abort,
        .g_slot, .g_wl_io, .g_dsel, .wd_imm, .disp_take(disp_t),
        .take_t(t_k != 2'd0), .take_p(p_k), .flush_now(t_flush), .start_any, .wl_fill_t, .wl_fill_p,
        .fetch_req(q_fetch_req), .b2b_now(b_b2b_now), .b2b_hold(a_mem_wait),
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
    // (S6) the first fetch's address: FFFF0h (PS FFFFh, IP 0); the function bench
    // (fpga/v35s/v35_core2_tb.sv) sets a test's PS:IP here through `verilator public` hooks
    // (observability and preload only: the harness build keeps the constants). (Q1) The
    // queue's prefetch pointer is an offset in PS: in reset it loads tb_reset_ip, the loader's
    // PC the address.
`ifndef SYNTHESIS
    reg [19:0] tb_reset_addr = 20'hFFFF0;
    reg [15:0] tb_reset_ip = 16'h0000;
`else
    wire [19:0] tb_reset_addr = 20'hFFFF0;
    wire [15:0] tb_reset_ip = 16'h0000;
`endif
    // (Q1) the queue is a simple machine (docs/v35s-queue-strategy.md): the EU pops the bytes
    // it takes (tick A: the T pass's takes and the IR load; tick B: the P pass's), flushes it
    // and suspends prefetching; the bus unit starts its fetches and delivers their words
    wire [15:0] q_flush_addr = core_reset_n ? t_flush_off : tb_reset_ip;
    // (Q1) the variant: B (a byte port and a latch) unless V35_QUEUE_A (a word write port)
`ifdef V35_QUEUE_A
    localparam bit Q1_VARIANT_B = 1'b0;
`else
    localparam bit Q1_VARIANT_B = 1'b1;
`endif
    v35_queue #(.VARIANT_B(Q1_VARIANT_B)) queue (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .fetch_req(q_fetch_req), .fetch_addr(q_fetch_addr), .q_low, .q_word,
        .fetch_go(g_fetch), .dlv_v(dlv_fetch), .dlv_data(b_done_data), .abort_go(b_abort_busy),
        .vb0(qv0), .vb1(qv1), .vb2(qv2), .vb3(qv3), .avail(q_avail), .rd(ld_rd), .rd_b(ld_rd_b), .rel(ld_rel), .stg(ld_stg),
        .flush(t_flush), .flush_addr(q_flush_addr), .susp(q_susp), .ps_base
    );
    // the EU's views: a fetch (or the aborted cycle) on the bus, the bytes stored
    wire        q_infl_c = b_fetch_inflight || b_abort_busy;
    wire        q_infl_x = q_infl_c || g_fetch || g_abort;
    wire [3:0]  q_stored_c = {1'b0, q_avail};
    wire [3:0]  q_stored_l = q_stored_c - {1'b0, ld_rd};

    // ---------------------------------------------------------------- the loader
    v35_loader loader (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .qv0, .qv1, .qv2, .qv3, .q_avail, .t_done, .p_done, .dlv(dlv_fetch), .rd(ld_rd), .rd_b(ld_rd_b), .rel(ld_rel), .stg(ld_stg),
        .ev0(vb0), .ev1(vb1), .ev2(vb2), .ev3(vb3), .e_avail, .reset_addr(tb_reset_addr), .t_flush_addr,
        .t_start, .t_k_in(t_k), .t_flush, .t_halt, .lx_hold, .idle_adj,
        .p_start, .p_k_in(p_k), .p_io_nx,
        .irh_set_t, .irh_clr_t, .disp_tk(disp_t), .lea_room(lea_room_t), .mate(mate_t), .eu_issue, .irh_set_p, .irh_clr_p,
        .irh_pg_t, .irh_pg_p, .mt_sub_t, .mt_sub_p,
        .ir_v_c, .ir_c, .ir_addr_c, .fmt_c, .ok_c, .cls_c, .fmt_mt,
        .l_pop, .l_load(ld_l_load), .ir_l, .ir_addr_l, .fmt_l, .ok_l, .ir_v_l,
        .fmt_mp, .p_mmiss(ld_p_mmiss), .p_ir, .p_load(ld_p_load), .ir_v_p,
        .stopped_o(ld_stopped), .head_odd, .need_t(ld_need_t),
        .nf_v, .nf_fmt, .nf_op, .nf_addr
    );

    // ---------------------------------------------------------------- the microcode sequencer
    v35_ucode ucode (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .ir_v_c, .fmt_c, .ok_c, .ok_l, .cls_c, .fmt_mt, .fmt_mp, .ir_c, .ir_v_l, .ir_l,
        .ir_addr_c, .ir_addr_l, .vb0, .vb1, .vb2, .vb3, .avail_c({1'b0, e_avail}), .l_pop,
        .arrived_now(dlv_fetch), .inflight_c(q_infl_c), .inflight_x(q_infl_x),
        .stored_c(q_stored_c), .stored_l(q_stored_l), .fetch_req(q_fetch_req), .b2b_now(b_b2b_now),
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
        .fetch_end_prev(b_fetch_end_prev), .fetch_len(b_fetch_len),
        .abort_done(b_abort_done), .head_odd, .need_l(ld_need_t), .p_ir(ld_p_load), .cpu_end(dlv_other), .mem_wait(a_mem_wait), .susp(q_susp),
        .xs_done,
        .mf_old,
        .g_fetch, .g_abort, .retick, .g_io(g_eu && k_io(g_kind)),
        .cnt, .cl_c, .cl_e, .psw_c, .psw_e, .cw_c, .cw_e, .mneg, .bf_cross, .bfcost, .bf_ok,
        .g_eu, .g_thru, .cur_thru(b_cur_thru), .irh_pg_t, .irh_pg_p, .mt_sub_t, .mt_sub_p,
        .pfs_x, .pfs_e, .pimm_x, .bcd_idle,
        .t_start, .t_k, .t_done, .t_flush, .t_halt, .halting,
        .halted_o(halted), .wb_hold, .latch_wait, .relatch, .relatch_late, .relatch_n, .retire,
        .retire_p, .floor_set, .floor_nb, .sreg_hold_set, .gdisp_act, .ea_act_x,
        .disp_t, .lea_room_t, .mate_t, .disp_ext, .irh_set_t, .irh_set_p, .irh_clr_t, .irh_clr_p, .take_now,
        .sidle_o(sidle), .lx_hold, .idle_adj,
        .post_t, .prow_t, .psetup_t, .pfnv_t, .pfn_t, .plead_t, .ptm_t, .ptm_p,
        .post_p, .prow_p, .psetup_p, .pfnv_p, .pfn_p, .plead_p,
        .p_start, .p_k, .p_done, .p_io_nx, .wl_fill_t, .wl_fill_p,
        .start_any, .run_e, .aim_next, .fmt_e,
        .wait_o(eu_wait), .res_o(eu_res), .dec_miss, .p_flush, .voc_miss
    );

    // ---------------------------------------------------------------- the datapath
    v35_eu eu (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .t_start, .p_start, .fmt_c, .ir_c, .ir_addr_c, .fmt_l, .fmt_mt, .fmt_mp, .ir_l,
        .ir_addr_l, .vb0, .vb1, .vb2, .vb3, .t_k, .l_pop, .p_k,
        .run_e, .aim_next, .fmt_e, .t_flush, .nf_v, .nf_fmt, .nf_op,
        .post_t, .prow_t, .psetup_t, .pfnv_t, .pfn_t, .plead_t,
        .post_p, .prow_p, .psetup_p, .pfnv_p, .pfn_p, .plead_p, .ptm_t, .ptm_p,
        .own_done(own_dlv), .own_two, .dlv_kind(b_dlv_kind), .dlv_addr(b_dlv_addr), .dlv_width(b_dlv_width),
        .dlv_data(b_done_data),
        .ra_next, .wa_en, .wa_addr, .wa_be, .wa_data, .ra_data, .rb_next, .rb_data,
        .rq_t, .rq_p, .ea_live, .ea_lo, .ps_base, .wd_live, .wd_imm, .wd_rdy, .cnt, .cl_c, .cl_e, .psw_c, .psw_e, .cw_c, .cw_e, .mneg, .t_flush_addr, .t_flush_off, .sfr_data,
        .edone, .edone_t, .povr_t, .povr_p, .str_last, .str_exit,
        .f_end(xs_done), .bf_cross, .bfcost, .bf_ok,
        .pc_o(eu_pc), .miss_o(eu_miss)
    );

    // ---------------------------------------------------------------- the register RAM
    v35_regram regram (
        .clock, .ce_a, .ce_b, .ra_next, .wa_en, .wa_addr, .wa_be, .wa_data, .ra_data, .rb_next, .rb_data
    );

    // ---------------------------------------------------------------- the arbiter
    v35_arbiter arbiter (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .post_t, .rq_t, .post_p, .rq_p, .retire_t(retire), .retire_p,
        .relatch, .relatch_late, .floor_set, .floor_nb, .sreg_hold_set,
        .halting, .halted, .wb_hold, .latch_wait, .gdisp_act,
        .ea_b2b_act(ea_act_x), .take_now, .ea_live, .ea_lo, .wd_live, .wd_rdy, .sidle,
        .fetch_req(q_fetch_req), .q_low, .q_word, .l_pop,
        .b2b_now(b_b2b_now), .need_t(ld_need_t),
        .free(b_free), .busy(b_busy), .cur_io(b_busy && k_io(b_cur_kind)), .cur_kind(b_cur_kind), .mf_old,
        .fetch_inflight(b_fetch_inflight), .in_wait(b_in_wait),
        .fetch_end_prev(b_fetch_end_prev), .fetch_run_prev(b_fetch_run_prev),
        .io_win(b_io_win), .fetch_len(b_fetch_len), .fetch_addr(q_fetch_addr),
        .dlv_eu(dlv_other),
        .t_start, .pfs_x, .pimm_x, .fetch_since(b_fetch_since),
        .cur_b2b_pfa(b_cur_b2b_pfa), .cur_thru(b_cur_thru), .prev_imm(b_prev_imm), .bcd_idle,
        .g_thru, .g_pfa, .slot_pf_e,
        .g_start, .g_kind, .g_addr, .g_width, .g_data, .g_fetch, .g_eu, .g_slot,
        .g_abort, .g_b2b, .retick, .eu_issue, .g_ext, .mem_wait_o(a_mem_wait),
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
        .clock, .reset_n(core_reset_n), .ce(ce_a), .en(1'b1), .rfm, .init_counter(7'(INIT_COUNTER)),
        .start(1'b0), .wr(1'b0), .wr_value(8'd0),
        .pending(rf_pending), .rfm_load(rf_load), .rfm_value(rf_value),
        .state_r(rf_state_r), .state_e(rf_state_e)
    );

    // ---------------------------------------------------------------- the SFR store
    // captured at its issue, written at its cycle's end with the EU's datum then (a store_imm
    // takes its immediate after the store issued)
    reg sfr_open = 1'b0;
    assign sfr_wr = ce_a && sfr_open && dlv_other;
    assign sfr_d = sfr_data;
    always @(posedge clock) begin
        if (!core_reset_n) begin
            sfr_open <= 1'b0;
        end else if (ce_a) begin
            if (g_start_b && g_kind_b == K_WRITE && g_addr_b >= SFR_PAGE) begin
                sfr_open <= 1'b1;
                sfr_a <= g_addr_b;
                sfr_w <= g_width_b;
            end else if (sfr_open && dlv_other) begin
                sfr_open <= 1'b0;
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
        .clock, .reset_n(core_reset_n), .ce_a,
        .g_start, .g_kind, .g_addr, .g_width, .g_len(b_grant_len),
        .start_t(t_start), .start_p(p_start), .scls_t(fmt_c.cls), .scls_p(fmt_l.cls),
        .pc_t(ir_addr_c), .pc_p(ir_addr_l),
        .takes({1'b0, t_k} + {2'd0, p_k}), .loads({1'b0, ld_l_load} + {1'b0, ld_p_load}),
        .post(post_t || post_p), .post_kind(post_t ? rq_t.kind : rq_p.kind), .issue(g_eu),
        .b2b(fetch_last && q_fetch_req), .abort(g_abort),
        .room(5'sd6 - 5'({2'd0, q_avail} - {2'd0, ld_rd}) - (q_infl_c ? 5'sd2 : 5'sd0)),
        .flag(q_fetch_req), .susp(q_susp), .why(eu_wait), .hold(a_why), .dec_miss,
        .wlost(eu_miss)
    );

`ifndef SYNTHESIS
    // diagnostics (+v35_diag): bus and queue errors on stderr; the decode-ahead misses (a
    // start a clock late) and lost register writes counted
    reg diag = 1'b0;
    reg err_seen = 1'b0;
    integer n_dec = 0;
    initial diag = $test$plusargs("v35_diag");
    always @(posedge clock) begin
        if (!core_reset_n)
            err_seen <= 1'b0;
        else if (ce_a) begin
            if ((b_error || eu_miss) && !err_seen) begin
                err_seen <= 1'b1;
                if (diag)
                    $display("v35: %s", b_error ? "a bus start on a busy bus"
                                                : "a register write lost");
            end
            if ((voc_miss || ld_p_mmiss) && diag)
                $display("v35: a row outside its pass slot's vocabulary (not acted on)");
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
`endif

    // (Q1) the nets the old queue read that nothing reads now
    wire q1_unused = &{1'b0, slot_pf_e, pfs_e, b_cf_tn, b_cf_irb, halted, p_ir, ld_l_load};
    wire unused = &{1'b0, ready, ce, x_fall, input_levels, idb, prc[7:2], ld_stopped,
                    b_cur_pos, b_dlv_width, a_count, own_pos, q1_unused,
                    a_ready, rf_pending, rf_load, rf_value, rf_state_r, rf_state_e, eu_pc,
                    eu_res, b_in_wait, b_fetch_since, b_error,
                    eu_wait, dec_miss, eu_miss, relatch_n, a_why, p_flush, voc_miss, ld_p_mmiss};
endmodule
