`timescale 1ns/1ps

// The Verilator bench top for the decoder and the EU (HDL plan, C3): v35_eu with its state
// bundle (V35S_STATE_DUMP), driven and read by v35_eu_tb.cpp from the frozen model's EU
// vectors (validation/v35s/chains/rtl_vectors.py, V35EU-3). Beside it the RTL queue (C2,
// JSLOT op stages: the EU's T and L ops, the arbiter's scripted X ops, the EU's P ops) and
// the RTL bus unit (C1) for the joint bench (rtl_vectors --joint3): the bench connects them
// through its ports (the EU's ops into the queue's chain, the queue's state before each op
// and its reads back into the EU, the bus unit's state into the EU's bus views, the EU's
// data cycle and the queue's fetch into the bus unit), evaluating until the clock settles;
// in the EU-alone bench (--eu) the queue and the bus unit are idle and the EU's views of
// them are the model's.
// Build: fpga/v35s/build_eu_tb.sh (binary in build/fpga/v35s/eu-tb/).
module v35_eu_tb #(
    parameter int NQ = 16,
    parameter int NXOP = 6,
    parameter int STATE_W = 958,
    parameter int JSLOT = 40,
    parameter int QSTATE_W = 187
) (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce,
    input  wire        ce_mid,
    // the EU
    input  wire [STATE_W-1:0] init_state,
    input  wire [15:0] code_org,            // (D2) the IP of the code's offset 0
    input  wire        c_eu,
    input  wire        c_read,
    input  wire [15:0] c_data_in,           // (D2) alone: the delivered word (joint: the bus
                                            // unit's)
    input  wire        fetch_done,
    input  wire [18:0] bus_t,
    input  wire [18:0] bus_p,
    output wire [19:0] code_addr,           // (D1) the code window: the twelve bytes from here
    input  wire [95:0] code_win,
    input  wire [4:0]  mutate,
    output wire [15:0] x_data,              // (D2) the EU cycle's datum (the EU's)
    output wire [196:0] opr_a,              // (D1) the starts' operand records and the
    output wire [196:0] opr_b,              // register file before each
    output wire [210:0] rfx_a,
    output wire [210:0] rfx_b,
    input  wire [NQ:0][51:0] qv_tl,
    input  wire [NQ-1:0][7:0] rd_tl,
    input  wire [NQ:0][51:0] qv_p,
    input  wire [NQ-1:0][7:0] rd_p,
    input  wire        x_valid,
    input  wire [2:0]  x_kind,
    input  wire        x_eu,
    input  wire [NXOP-1:0][11:0] xop,
    input  wire [2:0][6:0] counts_t,
    input  wire [2:0][6:0] counts_p,
    input  wire        q_latch_in,
    output wire [NQ-1:0][32:0] op_tl,
    output wire [4:0]  n_tl,
    output wire [4:0]  n_t,
    output wire [NQ-1:0][32:0] op_p,
    output wire [4:0]  n_p,
    output wire [1:0]  n_start,
    output wire        wl_fill_t,
    output wire        wl_fill_x,
    output wire        wl_fill_p,
    output wire        x_cyc,
    output wire [2:0]  x_cyc_kind,
    output wire [19:0] x_cyc_addr,
    output wire [1:0]  x_cyc_width,
    output wire [4:0]  qsnap_c,
    output wire [4:0]  qsnap_e,
    output wire        e_io,
    output wire        e_out,
    output wire        eu_error,
    output wire [7:0]  err_code,
    output wire [STATE_W-1:0] state_c,
    output wire [STATE_W-1:0] state_t,
    output wire [STATE_W-1:0] state_l,
    output wire [STATE_W-1:0] state_x,
    output wire [STATE_W-1:0] state_p,
    output wire [STATE_W-1:0] state_e,
    output wire [STATE_W-1:0] state_dump,
    // the queue (joint)
    input  wire [3:0]  init_count,
    input  wire [63:0] init_data,
    input  wire [19:0] init_fetch_addr,
    input  wire [JSLOT-1:0][32:0] qops,
    output wire [JSLOT-1:0][7:0] q_rd,
    output wire        fetch_issue,
    output wire [19:0] fetch_issue_addr,
    output wire        q_fetch_done,
    output wire        q_error,
    output wire [QSTATE_W-1:0] q_state_c,
    output wire [JSLOT-1:0][QSTATE_W-1:0] q_state_op,
    output wire [QSTATE_W-1:0] q_state_e,
    output wire [QSTATE_W-1:0] q_state_dump,
    // the bus unit (joint): the scripted cycles, the fetch's gate and data, the EU's cycle
    input  wire        fetch_gate,
    input  wire [15:0] fetch_data,
    input  wire        data_gate,           // the EU's data cycle goes to the bus unit (its
                                            // datum the EU's, x_data)
    input  wire [15:0] wtc,
    input  wire [7:0]  rfm,
    input  wire        rfm_load,
    input  wire [7:0]  rfm_value,
    input  wire        req_start,
    input  wire [2:0]  req_kind,
    input  wire [19:0] req_addr,
    input  wire [1:0]  req_width,
    input  wire [15:0] req_data,
    input  wire        req_ext,
    input  wire        req_latch,
    input  wire        wlatch_fill,
    input  wire [15:0] data_in,
    output wire        done,
    output wire [2:0]  done_kind,
    output wire [19:0] done_addr,
    output wire [15:0] done_data,
    output wire        busy,
    output wire        free,
    output wire        fetch_inflight,
    output wire        in_wait,
    output wire        fetch_end_prev,
    output wire [3:0]  fetch_since,
    output wire        io_win,
    output wire        wlatch_busy,
    output wire [2:0]  cur_kind,
    output wire [2:0]  cur_pos,
    output wire [2:0]  cur_len,
    output wire        busy_x,
    output wire        free_x,
    output wire        fetch_inflight_x,
    output wire        in_wait_x,
    output wire        fetch_end_prev_x,
    output wire [3:0]  fetch_since_x,
    output wire        io_win_x,
    output wire        wlatch_busy_x,
    output wire [2:0]  cur_kind_x,
    output wire [2:0]  cur_pos_x,
    output wire [2:0]  cur_len_x,
    output wire [2:0]  fetch_len,
    output wire [2:0]  refresh_len_now,
    output wire        biu_error,
    output wire [64:0] biu_state,
    // the queue's phase C and E inputs (joint): the bus unit's delivery, the EU's
    input  wire        q_joint
);
`include "v35_chain_params.svh"

    wire [2:0] fresh_l, fresh_p;            // the arbiter's (C4); unread here
    // (C5) the refresh: this bench runs refresh-off chains only (rtl_vectors --eu/--joint3;
    // --core models refresh): no controller, no early fetch run
    v35_eu #(.NQ(NQ), .NXOP(NXOP), .STATE_W(STATE_W)) eu (
        .clock, .reset_n, .ce, .init_state, .code_org, .refresh_on(1'b0), .c_eu, .c_read,
        .c_data(q_joint ? done_data : c_data_in),
        .fetch_done, .bus_t, .bus_p, .early_t(5'd0), .early_p(5'd0),
        .code_addr, .code_win, .qv_tl, .rd_tl, .qv_p, .rd_p, .x_valid, .x_kind, .x_eu, .xop,
        .counts_t, .counts_p, .q_latch_in, .op_tl, .n_tl, .n_t, .op_p, .n_p, .n_start,
        .wl_fill_t, .wl_fill_x, .wl_fill_p, .x_cyc, .x_cyc_kind, .x_cyc_addr, .x_cyc_width,
        .qsnap_c, .qsnap_e, .e_io, .e_out, .error(eu_error), .err_code, .fresh_l, .fresh_p,
        .x_data, .mutate, .opr_a, .opr_b, .rfx_a, .rfx_b, .state_c, .state_t, .state_l, .state_x, .state_p, .state_e, .state_dump);

    // the queue: its delivery the bus unit's, its phase E the bus unit's fetch end and the EU's
    wire        qe_fetch_end = cur_kind_x == V35_K_FETCH && cur_pos_x == cur_len_x - 3'd1;
    wire        qc_done = q_joint && done;
    v35_queue #(.NSLOT(JSLOT), .STATE_W(QSTATE_W)) queue (
        .clock, .reset_n, .ce, .init_count, .init_data, .init_fetch_addr,
        .c_done(qc_done), .c_fetch(done_kind == V35_K_FETCH),
        .c_refresh(done_kind == V35_K_REFRESH), .c_odd(done_addr[0]), .c_data(done_data),
        .c_snap(qsnap_c), .op(qops), .e_fetch_end(qe_fetch_end), .e_io, .e_out,
        .e_snap(qsnap_e), .rd(q_rd), .fetch_issue, .fetch_issue_addr, .fetch_done(q_fetch_done),
        .error(q_error), .state_c(q_state_c), .state_op(q_state_op), .state_e(q_state_e),
        .state_dump(q_state_dump));

    // the bus unit's request: the queue's fetch, the EU's data cycle, else the script
    wire        q_fetch = fetch_issue && fetch_gate;
    wire        e_data = x_cyc && data_gate;
    wire        b_start = q_fetch || e_data || req_start;
    wire [2:0]  b_kind = q_fetch ? V35_K_FETCH : e_data ? x_cyc_kind : req_kind;
    wire [19:0] b_addr = q_fetch ? fetch_issue_addr : e_data ? x_cyc_addr : req_addr;
    wire [1:0]  b_width = q_fetch ? V35_BW_WORD : e_data ? x_cyc_width : req_width;
    wire [15:0] b_data = q_fetch ? fetch_data : e_data ? x_data : req_data;
    wire        b_ext = q_fetch ? 1'b0 : req_ext;   // disp_io=extend: the arbiter's (scripted)
    wire        b_latch = q_fetch ? 1'b0 : e_data ? (x_cyc_kind == V35_K_READ
                                                     || x_cyc_kind == V35_K_IO_READ) : req_latch;

    wire [1:0] done_width;
    wire [2:0] start_len;
    wire a0, a19, a18_ube, mreq_n, mstb_n, iostb_n, read_write, refrq_n;
    wire [8:0] mux_address;
    wire [15:0] data_out;
    v35_biu biu (
        .clock, .reset_n, .ce, .ce_mid, .wtc, .rfm, .rfm_load, .rfm_value,
        .req_start(b_start), .req_kind(b_kind), .req_addr(b_addr), .req_width(b_width),
        .req_data(b_data), .req_ext(b_ext), .req_latch(b_latch), .wlatch_fill,
        .done, .done_kind, .done_addr, .done_width, .done_data,
        .busy, .free, .fetch_inflight, .in_wait, .fetch_end_prev, .fetch_since, .io_win,
        .wlatch_busy, .cur_kind, .cur_pos, .cur_len,
        .busy_x, .free_x, .fetch_inflight_x, .in_wait_x, .fetch_end_prev_x, .fetch_since_x,
        .io_win_x, .wlatch_busy_x, .cur_kind_x, .cur_pos_x, .cur_len_x, .start_len, .fetch_len, .refresh_len_now,
        .error(biu_error), .a0, .a19, .a18_ube, .mux_address, .data_out, .mreq_n, .mstb_n,
        .iostb_n, .read_write, .refrq_n, .data_in, .state_dump(biu_state));
endmodule
