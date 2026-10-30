`timescale 1ns/1ps

// The Verilator bench top for the queue (HDL plan, C2): v35_queue with its state bundle
// (V35S_STATE_DUMP), driven and read by v35_queue_tb.cpp from the frozen model's queue
// vectors (validation/v35s/chains/rtl_vectors.py, V35QUEUE-1). With `joint` the bus unit
// (v35_biu, C1) runs beside it: the queue's delivery is the bus unit's (done, its address
// and data), and the bus unit's fetch requests are the queue's issues (the address from the
// queue's fetch pointer, gated by the bench with the queue's own request), the other
// cycles scripted from the bus unit's vectors (V35BIU-1) as in C1.
// Build: fpga/v35s/build_queue_tb.sh (binary in build/fpga/v35s/queue-tb/).
module v35_queue_tb #(
    parameter int NSLOT = 16,
    parameter int STATE_W = 197
) (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce,
    input  wire        ce_mid,
    input  wire        joint,
    // the queue
    input  wire [3:0]  init_count,
    input  wire [63:0] init_data,
    input  wire [19:0] init_fetch_addr,
    input  wire        c_done,
    input  wire        c_fetch,
    input  wire        c_refresh,
    input  wire        c_odd,
    input  wire [15:0] c_data,
    input  wire [4:0]  c_snap,
    input  wire [NSLOT-1:0][32:0] op,
    input  wire        e_fetch_end,
    input  wire        e_io,
    input  wire        e_out,
    input  wire [4:0]  e_snap,
    output wire [NSLOT-1:0][7:0] rd,
    output wire        fetch_issue,
    output wire [19:0] fetch_issue_addr,
    output wire        fetch_done,
    output wire        q_error,
    output wire [STATE_W-1:0] state_c,
    output wire [NSLOT-1:0][STATE_W-1:0] state_op,
    output wire [STATE_W-1:0] state_e,
    output wire [STATE_W-1:0] state_dump,
    // the bus unit (joint): its scripted requests, the fetch's gate and data
    input  wire        fetch_gate,          // the queue's issue goes to the bus unit
    input  wire [15:0] fetch_data,          // the fetched word (the request's data)
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
    output wire        biu_error,
    output wire [64:0] biu_state
);
`include "v35_chain_params.svh"

    // the queue's delivery: scripted, or the bus unit's (joint)
    wire        qc_done = joint ? done : c_done;
    wire        qc_fetch = joint ? done_kind == V35_K_FETCH : c_fetch;
    wire        qc_refresh = joint ? done_kind == V35_K_REFRESH : c_refresh;
    wire        qc_odd = joint ? done_addr[0] : c_odd;
    wire [15:0] qc_data = joint ? done_data : c_data;
    // phase E's fetch on its last clock: scripted, or the bus unit's after the choice
    wire        qe_fetch_end = joint ? (cur_kind_x == V35_K_FETCH && cur_pos_x == cur_len_x - 3'd1)
                                     : e_fetch_end;

    v35_queue #(.NSLOT(NSLOT), .STATE_W(STATE_W)) queue (
        .clock, .reset_n, .ce, .init_count, .init_data, .init_fetch_addr,
        .c_done(qc_done), .c_fetch(qc_fetch), .c_refresh(qc_refresh), .c_odd(qc_odd),
        .c_data(qc_data), .c_snap, .op, .e_fetch_end(qe_fetch_end), .e_io, .e_out, .e_snap,
        .rd, .fetch_issue, .fetch_issue_addr, .fetch_done, .error(q_error),
        .state_c, .state_op, .state_e, .state_dump);

    // the bus unit's request: the queue's fetch (joint), else the script
    wire        q_fetch = joint && fetch_issue && fetch_gate;
    wire        b_start = q_fetch || req_start;
    wire [2:0]  b_kind = q_fetch ? V35_K_FETCH : req_kind;
    wire [19:0] b_addr = q_fetch ? fetch_issue_addr : req_addr;
    wire [1:0]  b_width = q_fetch ? V35_BW_WORD : req_width;
    wire [15:0] b_data = q_fetch ? fetch_data : req_data;
    wire        b_ext = q_fetch ? 1'b0 : req_ext;
    wire        b_latch = q_fetch ? 1'b0 : req_latch;

    wire [1:0] done_width;
    wire [2:0] cur_kind, cur_pos, cur_len, start_len, fetch_len, refresh_len_now;
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
        .io_win_x, .wlatch_busy_x, .cur_kind_x, .cur_pos_x, .cur_len_x, .start_len, .fetch_len,
        .refresh_len_now,
        .error(biu_error), .a0, .a19, .a18_ube, .mux_address, .data_out, .mreq_n, .mstb_n,
        .iostb_n, .read_write, .refrq_n, .data_in, .state_dump(biu_state));
endmodule
