`timescale 1ns/1ps

// V35S core v2: the slot module (docs/v35s-core-v2.md, "Architecture"), stage S3: the front
// end (bus unit, prefetch queue, loader, (A1) the grant in the bus unit) and the execution unit
// ((MX0) the microsequencer v35_useq on a registered ROM word, the datapath v35_eu, the register
// RAM v35_regram).
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
// (MX0) The CPU clock's two ticks (S7b; the enables `ce_a` / `ce_b` below):
//   tick A  every module's registers; the queue's delivery and window; the microinstruction (a
//           register) decides its stalls, its pops (the loader: the queue's reads and the
//           staging load, the request line), its RAM read addresses; the decode lookups from
//           the opcode / ModR/M / staging registers; the bus unit's grant on the request
//           register and the queue's line
//   tick B  the RAM's data, the sources, the ALU, the EA step, the write port, the request's
//           next state, the next microaddress (the ROM read at ce_a)
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
    wire        b_fetch_run_prev, b_io_win, b_dlv_v, b_abort_busy;
    wire        b_abort_last, b_abort_done, b_error, b_cpu_end_prev;
    wire [2:0]  b_cur_kind, b_cur_pos, b_cur_left, b_dlv_kind, b_fetch_len, b_grant_len;
    wire [3:0]  b_fetch_since;
    wire [19:0] b_dlv_addr;
    wire [1:0]  b_dlv_width;
    wire [15:0] b_done_data;
    wire        w3_v;
    wire signed [4:0] w3_rel;
    // (A1) the grant (S4) and the EU request port
    wire        g_start, g_fetch, g_eu, g_abort, g_b2b;
    wire [2:0]  g_kind;
    wire [19:0] g_addr;
    wire [1:0]  g_width;
    wire        req_v, req_width, req_resv, req_ack, req_done;
    wire [1:0]  req_cyc;
    wire [19:0] req_addr;
    wire [15:0] req_data;
    // queue (Q1: the simple machine)
    wire [7:0]  qv0, qv1, qv2, qv3;
    wire [2:0]  ld_rd, ld_rel;
    wire        ld_stg;
    wire [19:0] q_fetch_addr;
    wire [2:0]  q_avail, q_stored;
    wire        q_fetch_req, q_low, b_b2b_now;
    wire        q_word;                 // (Q2)
    // (MX0) the loader: the word register, the popped bytes, the decode
    wire        q_stall, dtrap, resv_e, s_modrm, dcall;
    wire [UADDR_W-1:0] dent, dret;
    wire [7:0]  ld_op, ld_opc, ld_modrm, ld_il, ld_ih, ld_dl, ld_dh;
    wire [19:0] op_a;
    wire [2:0]  ld_op3, ld_len;
    wire        ld_load;
    v35_udec_t  fmt, dec1;
    v35_udecm_t dec2;
    // (MX0) the sequencer
    v35_uword_t word;
    wire        ex, ex_pop, ex_b, start, start_trap, halted;
    wire [4:0]  why;
    wire [UADDR_W-1:0] upc;
    // (MX0) the datapath
    wire        opr_rdy, rq_busy, wr_hold, c_sgn, c_dtrap, div_trap;
    wire [7:0]  rb_lo;
    wire [15:0] flush_off;
    wire [19:0] flush_lin, ps_base;
    wire [15:0] sfr_data;
    wire [6:0]  ra_next, rb_next, wa_addr;
    wire        wa_en;
    wire [1:0]  wa_be;
    wire [15:0] wa_data, ra_data, rb_data;

    // the instruction's start and its address (the trace, the function bench, Q2's strobes)
    // (MX0f) Q2's start is the opcode's read from the queue: the E word's pop, not the routine's
    // entry word (the frozen model's start is that pop; the entry follows the post-E dispatch)
    wire        e_popped;
    wire        t_start = `V35_MX0F_QSTART ? e_popped : start;
    wire [19:0] ir_addr_c = op_a;
    wire        t_flush = ex_pop && word.flush;            // tick A: a FLUSH word executes
    wire        take_now;                              // tick A: an operand byte popped
    wire        ramen = prc[6];

    // (S7b) the slot's own ce_b registers: tick A's strobes that the nets between the modules
    // combine for tick B
    reg         g_start_b = 1'b0;
    reg  [2:0]  g_kind_b = K_NONE;
    reg  [19:0] g_addr_b = 20'd0;
    reg  [1:0]  g_width_b = BW_WORD;
    always @(posedge clock) begin
        if (ce_b) begin
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
        .req_v, .req_cyc, .req_addr, .req_width, .req_data, .req_resv, .req_ack, .req_done,
        .fetch_req(q_fetch_req), .q_low, .q_word, .fetch_addr(q_fetch_addr),
        .t_start, .take_now, .l_pop(ld_load),
        .g_start, .g_kind, .g_addr, .g_width, .g_fetch, .g_eu, .g_abort, .g_b2b,
        .b2b_now(b_b2b_now),
        .busy(b_busy), .free(b_free), .cur_kind(b_cur_kind), .cur_pos(b_cur_pos),
        .cur_left(b_cur_left), .in_wait(b_in_wait),
        .fetch_inflight(b_fetch_inflight), .fetch_past_b2(b_fetch_past_b2),
        .fetch_end_prev(b_fetch_end_prev), .cpu_end_prev(b_cpu_end_prev),
        .fetch_since(b_fetch_since),
        .fetch_run_prev(b_fetch_run_prev), .io_win(b_io_win),
        .dlv_v(b_dlv_v), .dlv_kind(b_dlv_kind), .dlv_addr(b_dlv_addr),
        .dlv_width(b_dlv_width), .done_data(b_done_data), .abort_busy(b_abort_busy),
        .abort_last(b_abort_last), .abort_done(b_abort_done), .fetch_len(b_fetch_len),
        .grant_len(b_grant_len), .error(b_error), .w3_v, .w3_rel,
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
    wire [15:0] q_flush_addr = core_reset_n ? flush_off : tb_reset_ip;
    // (Q1) the variant: B (a byte port and a latch) unless V35_QUEUE_A (a word write port)
`ifdef V35_QUEUE_A
    localparam bit Q1_VARIANT_B = 1'b0;
`else
    localparam bit Q1_VARIANT_B = 1'b1;
`endif
    // (MX0) no suspend: the V20 ROM's SUSP precedes FLUSH only, and MX0's one flush (BR far)
    // needs none
    v35_queue #(.VARIANT_B(Q1_VARIANT_B)) queue (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .fetch_req(q_fetch_req), .fetch_addr(q_fetch_addr), .q_low, .q_word,
        .fetch_go(g_fetch), .dlv_v(dlv_fetch), .dlv_data(b_done_data), .abort_go(b_abort_busy),
        .vb0(qv0), .vb1(qv1), .vb2(qv2), .vb3(qv3), .avail(q_avail), .stored(q_stored), .rd(ld_rd), .rd_b(3'd0),
        .rel(ld_rel), .stg(ld_stg),
        .flush(t_flush), .flush_addr(q_flush_addr), .susp(1'b0), .ps_base
    );
    wire q_infl_c = b_fetch_inflight || b_abort_busy;

    // ---------------------------------------------------------------- the loader
    v35_loader loader (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .qv0, .qv1, .q_avail, .q_stored, .rd(ld_rd), .rel(ld_rel), .stg(ld_stg),
        .reset_addr(tb_reset_addr), .flush(t_flush), .flush_lin,
        .ex(ex_pop), .pop(word.pop), .e_pop(word.e), .disp(ex && word.seq == SQ_DISP),
        .dispm(word.seq == SQ_DISPM), .q_stall, .op(ld_op), .op_a, .opc(ld_opc), .modrm(ld_modrm), .il(ld_il), .ih(ld_ih),
        .dl(ld_dl), .dh(ld_dh), .fmt, .op3(ld_op3), .dec1, .dec2, .len(ld_len),
        .l_load(ld_load), .o_pop(take_now), .o_epop(e_popped), .dent, .dcall, .dret, .dtrap,
        .resv_e, .s_modrm
    );

    // ---------------------------------------------------------------- the microsequencer
    v35_useq useq (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .q_stall, .dec1, .dent, .dcall, .dret, .dtrap, .dec2, .len(ld_len), .il(ld_il), .fmt_w(fmt.w),
        .opr_rdy, .rq_busy, .wr_hold, .c_sgn, .c_dtrap, .rb_lo,
        .fetch_run(b_fetch_inflight), .b2b_now(b_b2b_now), .s_modrm,
        .word, .ex, .ex_pop, .ex_b, .start, .start_trap, .why, .halted, .upc_o(upc)
    );

    // ---------------------------------------------------------------- the datapath
    v35_eu eu (
        .clock, .reset_n(core_reset_n), .ce_a, .ce_b,
        .word, .ex, .ex_b, .resv_e,
        .fmt, .op3(ld_op3), .op(ld_opc), .modrm(ld_modrm), .il(ld_il), .ih(ld_ih), .dl(ld_dl),
        .dh(ld_dh),
        .ra_next, .rb_next, .ra_data, .rb_data, .wa_en, .wa_addr, .wa_be, .wa_data,
        .req_v, .req_cyc, .req_addr, .req_width, .req_data, .req_resv, .req_ack, .req_done,
        .done_data(b_done_data), .cpu_end_prev(b_cpu_end_prev), .ramen,
        .opr_rdy, .rq_busy, .wr_hold, .c_sgn, .c_dtrap, .rb_lo,
        .flush_off, .flush_lin, .ps_base, .sfr_data, .trap_o(div_trap)
    );

    // ---------------------------------------------------------------- the register RAM
    v35_regram regram (
        .clock, .ce_a, .ce_b, .ra_next, .wa_en, .wa_addr, .wa_be, .wa_data, .ra_data, .rb_next, .rb_data
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
        .start, .epop(e_popped), .start_trap, .entry(upc), .pc(op_a),
        .take(take_now), .load(ld_load),
        .post(ex_pop && word.bus != BQ_NONE), .post_kind(word.bus == BQ_MEMR ? K_READ
                                           : word.bus == BQ_MEMW ? K_WRITE
                                           : word.bus == BQ_IOR ? K_IO_READ : K_IO_WRITE),
        .issue(g_eu), .b2b(fetch_last && q_fetch_req), .abort(g_abort),
        .room(5'sd6 - 5'({2'd0, q_avail} - {2'd0, ld_rd}) - (q_infl_c ? 5'sd2 : 5'sd0)),
        .flag(q_fetch_req), .why, .upc
    );

`ifndef SYNTHESIS
    // diagnostics (+v35_diag): a bus start on a busy bus on stderr
    reg diag = 1'b0;
    reg err_seen = 1'b0;
    initial diag = $test$plusargs("v35_diag");
    always @(posedge clock) begin
        if (!core_reset_n)
            err_seen <= 1'b0;
        else if (ce_a) begin
            if (b_error && !err_seen) begin
                err_seen <= 1'b1;
                if (diag)
                    $display("v35: a bus start on a busy bus");
            end
        end
    end
`endif
`endif

    wire unused = &{1'b0, ready, ce, x_fall, input_levels, idb, prc[7], prc[5:2], qv1, qv2, qv3,
                    b_cur_pos, b_dlv_width, rf_pending, rf_load, rf_value, rf_state_r, rf_state_e,
                    b_in_wait, b_fetch_since, b_error, b_fetch_past_b2, b_fetch_end_prev,
                    b_fetch_run_prev, b_io_win, b_abort_last, b_abort_done, b_fetch_len,
                    b_dlv_addr, w3_v, w3_rel, g_fetch, g_b2b, dlv_other, b_free, ld_len,
                    ex_b, why, upc, start_trap, halted, div_trap, ir_addr_c, dec2,
                    fetch_last, q_infl_c, ld_op3, ld_op, b_grant_len, g_eu, g_abort};
endmodule
