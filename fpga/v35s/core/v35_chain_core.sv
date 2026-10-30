`timescale 1ns/1ps

// V35S chain-model core (HDL plan, Phase C4): the five timing machines of the frozen chain model
// (validation/v35s/chains/sim/frozen/machine.py's Machine) run together, the arbiter's decisions
// in RTL: the bus unit (v35_biu.sv, C1), the queue (v35_queue.sv, C2), the decoder and the EU
// (v35_eu.sv with v35_decoder.sv, C3) and the arbiter (v35_arbiter.sv, C4).
//
// One model clock, in Machine.run's order: C (the bus unit's delivery into the queue and the EU),
// T (the EU's tick), L (the decoder's IR load), X (the arbiter's choice), P (the post-issue pass:
// the second tick and IR load, io_ir_hold, io_take=unit, port_issue, nop_hold), E (the queue's
// end_clock, latch_start). Inside a clock the machines call each other in an order the model
// fixes: the EU's and the decoder's queue ops (T, L), the arbiter's (X) and the EU's again (P) are
// one chain of op stages in the queue (JSLOT), each reading the queue's state left by the ones
// before it. The machines are combinational over the clock; what one reads of another that the
// other computes later in the same chain (the queue's state before each op and each op's read, for
// the EU and for the arbiter; the arbiter's touches on the EU and its cycle, for phase P; the bus
// unit after the choice; the queue's phase E for latch_start) passes through settle registers:
// every `clock` edge between two model clocks re-evaluates the chain from them, and the model clock
// has settled when they no longer change (`settled`). The chain is causal (an op's view depends
// only on the ops before it), so the fixpoint is the model's and is reached in at most as many
// iterations as the chain's depth; `run` then ends the model clock on the next edge, the machines'
// state registers taking the end-of-clock values (their `ce`).
//
// Inputs besides the configuration: the start state (Machine.__init__'s: the EU's, the register
// file's presets among it, and the queue's; the prelude's POP PSW read on clock 0,
// prelude_anchor=pop). (D1) The register file and the EA adder are the EU's (v35_eu.sv): it
// computes each start's operand record and applies the instruction's register effects; (D2) the
// function is nuV30's: the delivered word reaches the EU (`c_data`, done_data), an EU cycle's
// datum is the EU's (x_data), the code's base is PS's + code_org. The memory is outside: `code_addr` / `code_win` for the
// bytes the EU decodes a start from (the model decodes from the image), `fetch_addr` /
// `fetch_data` for a fetch's word, `data_in` for the delivered word (the bus unit latches it
// mid-B3).
// (C5) The refresh controller (v35_refresh.sv) runs in phase R, between L and X (Machine.run:
// refresh.raise_ before arbitrate): its pending request goes to the arbiter, an RFM write taking
// effect goes to the bus unit (rfm_load/rfm_value: the refresh cycle's length); in X the arbiter's
// refresh start clears the request and the EU's RFM store (the arbiter's sfr_wr, eu.sfr) arms the
// write. `refresh_on` is whether the chain runs the controller at all (frozen machine.py builds it
// for refresh_any chains only: the EU then runs the refresh templates and rules), `init_counter`
// the counter's value at clock 0 (refresh.POP_COUNTER for the run's prelude).
// Not modelled here: the prelude's tail before the POP PSW read and the reset (C6).
// Build: fpga/v35s/build_core_tb.sh (bench fpga/v35s/v35_core_tb.sv, .cpp).
module v35_chain_core
    import v35_decoder_pkg::*;
    import v35_eu_pkg::*;
    import v35_queue_pkg::*;
#(
    parameter int NQ = 16,                  // the EU's queue ops per phase (T/L; P)
    parameter int NXOP = 6,                 // the arbiter's touches on the EU per clock
    parameter int NXQ = 8,                  // the arbiter's queue ops per clock
    parameter int JSLOT = 40,               // the queue's op stages (T, L, X and P ops)
    parameter int STATE_W = 879,            // v35_eu.sv
    parameter int QSTATE_W = 180,           // v35_queue.sv
    parameter int ASTATE_W = 103,           // v35_arbiter.sv
    parameter int RSTATE_W = 24             // v35_refresh.sv
) (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        run,                 // end the model clock once it has settled
    input  wire        ce_mid,              // the middle of the CPU clock (strobes, read latch)

    // the start (Machine.__init__): the EU's state at the end of clock -1, the queue's preload
    input  wire [STATE_W-1:0] init_state,
    input  wire [15:0] code_org,            // (D2) the IP of the code's offset 0 (PS: its base)
    input  wire [3:0]  init_count,
    input  wire [63:0] init_data,
    input  wire [19:0] init_fetch_addr,
    // the SFR block
    input  wire [15:0] wtc,
    input  wire [7:0]  rfm,
    // (C5) the refresh controller: the chain runs it (refresh_any), its counter at clock 0
    input  wire        refresh_on,
    input  wire [6:0]  init_counter,

    // memory: (D1) the code window the EU decodes its starts from (the twelve bytes from
    // code_addr), a fetch's word, the delivered word
    output wire [19:0] code_addr,
    input  wire [95:0] code_win,
    output wire [19:0] fetch_addr,          // a fetch starting this clock: its address ...
    input  wire [15:0] fetch_data,          // ... and the word there
    input  wire [15:0] data_in,             // the bus's data (latched mid-B3)

    output wire        settled,             // the model clock's chain has settled
    output wire [1:0]  n_start,             // instructions started this clock
    output wire        done,                // the cycle that ended on the previous clock ...
    output wire [2:0]  done_kind,
    output wire [19:0] done_addr,
    output reg         error,               // sticky: a machine's error or a core check
    output wire [7:0]  err_code,            // this clock's, {core, arbiter, EU} (0: none)

    // pins (v35_biu.sv)
    output wire        a0,
    output wire        a19,
    output wire        a18_ube,
    output wire [8:0]  mux_address,
    output wire [15:0] data_out,
    output wire        mreq_n,
    output wire        mstb_n,
    output wire        iostb_n,
    output wire        read_write,
    output wire        refrq_n
`ifdef V35S_STATE_DUMP
    ,
    input  wire [3:0]  mutate,              // the mutation tests (1..7 the arbiter's, 8..10 the EU's)
    // (D1) the operand record of the clock's first and second start and the register file
    // before each one's execute; (D2) the EU cycle's datum (the EU's)
    output wire [196:0] opr_a,
    output wire [196:0] opr_b,
    output wire [210:0] rfx_a,
    output wire [210:0] rfx_b,
    output wire [15:0] x_data,
    // B3: every machine's state after every phase (the EU's, the queue's after each op stage,
    // the arbiter's after X and at the end), the registered ones, the clock's ops and cycle
    output wire [STATE_W-1:0] eu_c,
    output wire [STATE_W-1:0] eu_t,
    output wire [STATE_W-1:0] eu_l,
    output wire [STATE_W-1:0] eu_x,
    output wire [STATE_W-1:0] eu_p,
    output wire [STATE_W-1:0] eu_e,
    output wire [STATE_W-1:0] eu_dump,
    output wire [QSTATE_W-1:0] q_c,
    output wire [JSLOT-1:0][QSTATE_W-1:0] q_ops,
    output wire [QSTATE_W-1:0] q_e,
    output wire [QSTATE_W-1:0] q_dump,
    output wire [ASTATE_W-1:0] a_x,
    output wire [ASTATE_W-1:0] a_e,
    output wire [ASTATE_W-1:0] a_dump,
    output wire [RSTATE_W-1:0] r_r,         // the refresh controller after R, at the end, registered
    output wire [RSTATE_W-1:0] r_e,
    output wire [RSTATE_W-1:0] r_dump,
    output wire [63:0] biu_dump,
    output wire [JSLOT-1:0][32:0] slots,    // the clock's queue ops, in chain order
    output wire [JSLOT-1:0][7:0] slot_rd,
    output wire [4:0]  n_tl,
    output wire [4:0]  n_t,
    output wire [3:0]  n_x,
    output wire [4:0]  n_p,
    output wire [NXOP-1:0][V35_XOP_W-1:0] xops,
    output wire        x_cyc,
    output wire [2:0]  x_cyc_kind,
    output wire [19:0] x_cyc_addr,
    output wire [1:0]  x_cyc_width,
    output wire        req_start,
    output wire        req_ext,
    output wire        b_busy,
    output wire        b_free,
    output wire        b_finf,
    output wire        b_busy_x,
    output wire        b_free_x,
    output wire        b_wl_x
`endif
);

    localparam int QVW = $bits(v35_qview_t);
    localparam int BVW = $bits(v35_bview_t);

    // the core's own checks (err_code[7:6] with the arbiter's [5:3] and the EU's [2:0] codes
    // folded: the first of each)
    localparam logic [1:0] V35_CE_SLOTS = 2'd1;    // more ops in a clock than the chain holds
    localparam logic [1:0] V35_CE_CYCLE = 2'd2;    // the arbiter's cycle is not the EU's / queue's
    localparam logic [1:0] V35_CE_LEN = 2'd3;      // the arbiter's length is not the bus unit's

    // the queue's state as the EU and the decoder read it (v35_qview_t)
    function automatic v35_qview_t qview(input v35_qstate_t s);
        v35_qview_t v;
        v.count = s.count;
        v.latched = s.latched;
        v.flag = s.flag;
        v.rq_valid = s.rq_valid;
        v.rq_age = s.rq_age;
        v.inflight = s.inflight;
        v.ab_valid = s.ab_valid;
        v.ab_left = s.ab_left;
        v.ab_this = s.ab_this;
        v.retry = s.retry;
        v.retry_loop = s.retry_loop;
        v.rt_valid = s.rt_valid;
        v.rt_off = s.rt_off;
        v.shift_held = s.shift_held;
        v.sh_valid = s.sh_valid;
        v.sh_off = s.sh_off;
        v.dropped = s.dropped;
        v.drop_hold = s.drop_hold;
        v.b2b_now = s.b2b_now;
        v.arrived_now = s.arrived_now;
        v.take_now = s.take_now;
        v.take_prev = s.take_prev;
        v.ir_now = s.ir_now;
        v.latch_in_now = s.latch_in_now;
        qview = v;
    endfunction

    // ------------------------------------------------ the settle registers
    typedef struct packed {
        logic [NQ:0][QVW-1:0]      qv_tl;   // the queue before each T/L op of the EU (and after)
        logic [NQ-1:0][7:0]        rd_tl;
        logic [NQ:0][QVW-1:0]      qv_p;    // ... each P op
        logic [NQ-1:0][7:0]        rd_p;
        logic [NXQ:0][QSTATE_W-1:0] aqv;    // ... each X op of the arbiter
        logic [NXQ-1:0][7:0]       ard;
        logic                      x_valid; // the arbiter's cycle, touches, counts after X
        logic [2:0]                x_kind;
        logic                      x_eu;
        logic [NXOP-1:0][V35_XOP_W-1:0] xop;
        logic [2:0][6:0]           counts_p;
        logic [4:0]                early_p; // (C5) the early fetch run after X
        logic [BVW-1:0]            bus_p;   // the bus unit after the choice
        logic                      latch_in;// the queue's phase E: latch_in_t == t
    } v35_settle_t;

    v35_settle_t sr, sn;
    wire commit = run && settled;
    assign settled = sn == sr;

    reg first;                              // the model's clock 0 (the POP PSW read)
    reg eu_owner;                           // the cycle on the bus is the EU's

    // ------------------------------------------------ the bus unit
    wire        b_req_start, b_req_ext, b_req_latch;
    wire [2:0]  b_req_kind;
    wire [19:0] b_req_addr;
    wire [1:0]  b_req_width;
    wire [15:0] b_req_data;
    wire        wl_fill_t, wl_fill_x, wl_fill_p;
    wire        busy, free, fetch_inflight, in_wait, fetch_end_prev, io_win, wlatch_busy;
    wire        busy_x, free_x, fetch_inflight_x, in_wait_x, fetch_end_prev_x, io_win_x,
                wlatch_busy_x;
    wire [2:0]  fetch_since, fetch_since_x, cur_kind, cur_pos, cur_len, cur_kind_x, cur_pos_x,
                cur_len_x, start_len, fetch_len;
    wire [1:0]  done_width;
    wire [15:0] done_data;
    wire        biu_error;
    wire [2:0]  refresh_len_now;
    wire        rf_load;
    wire [7:0]  rf_value;
`ifdef V35S_STATE_DUMP
    wire [63:0] biu_state;
`endif
    v35_biu biu (
        .clock, .reset_n, .ce(commit), .ce_mid, .wtc, .rfm, .rfm_load(rf_load), .rfm_value(rf_value),
        .req_start(b_req_start), .req_kind(b_req_kind), .req_addr(b_req_addr),
        .req_width(b_req_width), .req_data(b_req_data), .req_ext(b_req_ext),
        .req_latch(b_req_latch), .wlatch_fill(wl_fill_t || wl_fill_x || wl_fill_p),
        .done, .done_kind, .done_addr, .done_width, .done_data,
        .busy, .free, .fetch_inflight, .in_wait, .fetch_end_prev, .fetch_since, .io_win,
        .wlatch_busy, .cur_kind, .cur_pos, .cur_len,
        .busy_x, .free_x, .fetch_inflight_x, .in_wait_x, .fetch_end_prev_x, .fetch_since_x,
        .io_win_x, .wlatch_busy_x, .cur_kind_x, .cur_pos_x, .cur_len_x, .start_len, .fetch_len,
        .refresh_len_now, .error(biu_error), .a0, .a19, .a18_ube, .mux_address, .data_out, .mreq_n, .mstb_n,
        .iostb_n, .read_write, .refrq_n, .data_in
`ifdef V35S_STATE_DUMP
        , .state_dump(biu_state)
`endif
        );

    // the bus unit before the choice as the EU and the arbiter read it: on clock 0 the
    // prelude's POP PSW read, which Machine.__init__ starts before the clock's phases
    wire [2:0] pop_len = 3'(V35_BUS_BASE) + {1'b0, wtc[V35_WTC_MEM_LSB +: 2]};
    wire        v_busy = first ? 1'b1 : busy;
    wire        v_free = first ? 1'b0 : free;
    wire [2:0]  v_kind = first ? V35_K_READ : cur_kind;
    wire [2:0]  v_pos = first ? 3'd0 : cur_pos;
    wire [2:0]  v_len = first ? pop_len : cur_len;
    wire        f3 = fetch_len == 3'd3;
    // (two processes: bus_p depends on the arbiter's choice, which depends on the EU's T)
    v35_bview_t bus_t, bus_p;
    always_comb
        bus_t = '{kind: v_kind, pos: v_pos, len: v_len, free: v_free, finf: fetch_inflight,
                  in_wait: in_wait, fprev: fetch_end_prev, wl: wlatch_busy, fsince: fetch_since,
                  flen3: f3};
    always_comb
        bus_p = '{kind: cur_kind_x, pos: cur_pos_x, len: cur_len_x, free: free_x,
                  finf: fetch_inflight_x, in_wait: in_wait_x, fprev: fetch_end_prev_x,
                  wl: wlatch_busy_x, fsince: fetch_since_x, flen3: f3};

    // ------------------------------------------------ the EU and the decoder
    wire [NQ-1:0][32:0] op_tl, op_p;
    wire [4:0]  eu_n_tl, eu_n_t, eu_n_p;
    wire        e_x_cyc;
    wire [2:0]  e_x_cyc_kind;
    wire [19:0] e_x_cyc_addr;
    wire [1:0]  e_x_cyc_width;
    wire [4:0]  qsnap_c, qsnap_e;
    wire        e_io, e_out, eu_error;
    wire [7:0]  eu_err;
    wire [STATE_W-1:0] eu_state_l, eu_state_e;
    wire [2:0]  fresh_l, fresh_p;
    wire        q_fetch_done;
    wire [2:0][6:0] counts_t;
    wire        c_eu = done && eu_owner && !first;
    wire        c_read = c_eu && (done_kind == V35_K_READ || done_kind == V35_K_IO_READ);
    wire [4:0]  a_early_t, a_early_p;
    wire [15:0] eu_xd;                      // (D2) the EU cycle's datum (the EU's, at phase X)
    v35_eu #(.NQ(NQ), .NXOP(NXOP), .STATE_W(STATE_W)) eu (
        .clock, .reset_n, .ce(commit), .init_state, .code_org, .refresh_on, .c_eu, .c_read,
        .c_data(done_data),
        .fetch_done(q_fetch_done), .bus_t, .bus_p(v35_bview_t'(sr.bus_p)),
        .early_t(a_early_t), .early_p(sr.early_p), .code_addr, .code_win,
        .qv_tl(sr.qv_tl), .rd_tl(sr.rd_tl), .qv_p(sr.qv_p), .rd_p(sr.rd_p),
        .x_valid(sr.x_valid), .x_kind(sr.x_kind), .x_eu(sr.x_eu), .xop(sr.xop),
        .counts_t, .counts_p(sr.counts_p), .q_latch_in(sr.latch_in),
        .op_tl, .n_tl(eu_n_tl), .n_t(eu_n_t), .op_p, .n_p(eu_n_p), .n_start,
        .wl_fill_t, .wl_fill_x, .wl_fill_p, .x_cyc(e_x_cyc), .x_cyc_kind(e_x_cyc_kind),
        .x_cyc_addr(e_x_cyc_addr), .x_cyc_width(e_x_cyc_width), .qsnap_c, .qsnap_e, .e_io, .e_out,
        .error(eu_error), .err_code(eu_err), .state_l(eu_state_l), .state_e(eu_state_e),
        .fresh_l, .fresh_p, .x_data(eu_xd)
`ifdef V35S_STATE_DUMP
        , .mutate, .opr_a, .opr_b, .rfx_a, .rfx_b
        , .state_c(eu_c), .state_t(eu_t), .state_x(eu_x), .state_p(eu_p), .state_dump(eu_dump)
`endif
        );

    // ------------------------------------------------ the arbiter
    wire [NXQ-1:0][32:0] a_qop;
    wire [3:0]  a_n_q;
    wire [NXOP-1:0][V35_XOP_W-1:0] a_xop;
    wire        a_x_valid, a_x_eu, a_req_start, a_req_fetch, a_req_eu, a_req_ext, a_req_latch;
    wire [2:0]  a_x_kind, a_req_kind, a_req_len;
    wire [19:0] a_req_addr;
    wire [1:0]  a_req_width;
    wire [2:0][6:0] a_counts_p;
    wire        arb_error;
    wire [7:0]  arb_err;
    wire [ASTATE_W-1:0] a_state_x;
    wire        a_sfr_wr, rf_pending;
    wire [7:0]  a_sfr_value;
    v35_arbiter #(.NXQ(NXQ), .NXOP(NXOP), .STATE_W(ASTATE_W), .ESTATE_W(STATE_W),
                  .QSTATE_W(QSTATE_W)) arbiter (
        .clock, .reset_n, .ce(commit), .eu_l(eu_state_l), .fresh_l, .eu_e(eu_state_e), .fresh_p,
        .qv(sr.aqv), .qrd(sr.ard), .b_busy(v_busy), .b_free(v_free), .b_kind(v_kind),
        .b_pos(v_pos), .b_len(v_len),
        .b_in_wait(in_wait), .b_finf(fetch_inflight), .b_fprev(fetch_end_prev),
        .b_io_win(io_win), .b_done(done), .b_done_kind(done_kind), .wtc,
        .refresh_on, .rf_pending, .rf_len(refresh_len_now),
        .qop(a_qop), .n_q(a_n_q), .xop(a_xop), .x_valid(a_x_valid), .x_kind(a_x_kind),
        .x_eu(a_x_eu), .counts_t, .counts_p(a_counts_p), .req_start(a_req_start),
        .req_fetch(a_req_fetch), .req_eu(a_req_eu), .req_kind(a_req_kind),
        .req_addr(a_req_addr), .req_width(a_req_width), .req_len(a_req_len),
        .req_ext(a_req_ext), .req_latch(a_req_latch), .sfr_wr(a_sfr_wr), .sfr_value(a_sfr_value),
        .early_t(a_early_t), .early_p(a_early_p), .error(arb_error), .err_code(arb_err),
        .state_x(a_state_x)
`ifdef V35S_STATE_DUMP
        , .state_e(a_e), .state_dump(a_dump), .mutate
`endif
        );

    // ------------------------------------------------ (C5) the refresh controller
    wire [RSTATE_W-1:0] rf_state_r, rf_state_e;
    v35_refresh #(.STATE_W(RSTATE_W)) refresh (
        .clock, .reset_n, .ce(commit), .en(refresh_on), .rfm, .init_counter,
        .start(!first && a_req_start && a_req_kind == V35_K_REFRESH),
        .wr(!first && a_sfr_wr), .wr_value(a_sfr_value),
        .pending(rf_pending), .rfm_load(rf_load), .rfm_value(rf_value),
        .state_r(rf_state_r), .state_e(rf_state_e)
`ifdef V35S_STATE_DUMP
        , .state_dump(r_dump)
`endif
        );

    // ------------------------------------------------ the queue and its op chain
    logic [JSLOT-1:0][32:0] qops;
    wire [JSLOT-1:0][7:0] q_rd;
    wire        q_fetch_issue, q_error;
    wire [19:0] q_fetch_issue_addr;
    wire [QSTATE_W-1:0] q_state_c, q_state_e;
    wire [JSLOT-1:0][QSTATE_W-1:0] q_state_op;
    int         p0, nall;
    always_comb begin
        int ntl, nx, np;
        ntl = int'(eu_n_tl);
        nx = int'(a_n_q);
        np = int'(eu_n_p);
        p0 = ntl + nx;
        nall = ntl + nx + np;
        for (int k = 0; k < JSLOT; k++) begin
            if (k < ntl)
                qops[k] = op_tl[k];
            else if (k < p0)
                qops[k] = a_qop[k - ntl];
            else if (k < nall)
                qops[k] = op_p[k - p0];
            else
                qops[k] = '0;
        end
    end
    wire e_fetch_end = cur_kind_x == V35_K_FETCH && cur_pos_x == cur_len_x - 3'd1;
    v35_queue #(.NSLOT(JSLOT), .STATE_W(QSTATE_W)) queue (
        .clock, .reset_n, .ce(commit), .init_count, .init_data, .init_fetch_addr,
        .c_done(done), .c_fetch(done_kind == V35_K_FETCH), .c_refresh(done_kind == V35_K_REFRESH),
        .c_odd(done_addr[0]), .c_data(done_data), .c_snap(qsnap_c), .op(qops),
        .e_fetch_end, .e_io, .e_out, .e_snap(qsnap_e), .rd(q_rd), .fetch_issue(q_fetch_issue),
        .fetch_issue_addr(q_fetch_issue_addr), .fetch_done(q_fetch_done), .error(q_error),
        .state_c(q_state_c), .state_op(q_state_op), .state_e(q_state_e)
`ifdef V35S_STATE_DUMP
        , .state_dump(q_dump)
`endif
        );

    // the queue's state before chain stage k (after the k ops before it)
    function automatic v35_qstate_t q_before(input int k);
        if (k <= 0)
            q_before = v35_qstate_t'(q_state_c);
        else if (k >= JSLOT)
            q_before = v35_qstate_t'(q_state_op[JSLOT - 1]);
        else
            q_before = v35_qstate_t'(q_state_op[k - 1]);
    endfunction

    function automatic logic [7:0] q_read(input int k);
        q_read = (k >= 0 && k < JSLOT) ? q_rd[k] : 8'd0;
    endfunction

    // the next values of the settle registers
    always_comb begin
        int ntl, nx, np, k;
        v35_qstate_t qe;
        ntl = int'(eu_n_tl);
        nx = int'(a_n_q);
        np = int'(eu_n_p);
        sn = '0;
        for (int i = 0; i <= NQ; i++) begin
            k = i < ntl ? i : ntl;
            sn.qv_tl[i] = qview(q_before(k));
            k = i < np ? i : np;
            sn.qv_p[i] = qview(q_before(p0 + k));
        end
        for (int i = 0; i < NQ; i++) begin
            sn.rd_tl[i] = i < ntl ? q_read(i) : 8'd0;
            sn.rd_p[i] = i < np ? q_read(p0 + i) : 8'd0;
        end
        for (int j = 0; j <= NXQ; j++) begin
            k = j < nx ? j : nx;
            sn.aqv[j] = q_before(ntl + k);
        end
        for (int j = 0; j < NXQ; j++)
            sn.ard[j] = j < nx ? q_read(ntl + j) : 8'd0;
        sn.x_valid = a_x_valid;
        sn.x_kind = a_x_kind;
        sn.x_eu = a_x_eu;
        sn.xop = a_xop;
        sn.counts_p = a_counts_p;
        sn.early_p = a_early_p;
        sn.bus_p = bus_p;
        qe = v35_qstate_t'(q_state_e);
        sn.latch_in = qe.latch_in_now;
    end

    always @(posedge clock) begin
        if (!reset_n)
            sr <= '0;
        else if (!commit)
            sr <= sn;                       // one more iteration of the clock's chain
    end

    // ------------------------------------------------ the bus unit's request
    assign b_req_start = first || a_req_start;
    assign b_req_kind = first ? V35_K_READ : a_req_kind;
    assign b_req_addr = first ? V35_PRELUDE_POP_ADDR : a_req_fetch ? q_fetch_issue_addr : a_req_addr;
    assign b_req_width = first ? V35_BW_WORD : a_req_width;
    assign b_req_data = first ? V35_PRELUDE_PSW : a_req_fetch ? fetch_data
                        : a_req_eu ? eu_xd : 16'd0;     // (D2) the EU's; a refresh: none
    assign b_req_ext = !first && a_req_ext;
    assign b_req_latch = !first && a_req_latch;  // the POP PSW read's datum: no latch (C1, 7)
    assign fetch_addr = q_fetch_issue_addr;

    // the core's checks: the chain's length; the arbiter's cycle the queue's fetch or the EU's
    // data cycle, with the bus unit's length
    logic [1:0] core_err;
    always_comb begin
        core_err = 2'd0;
        if (nall > JSLOT)
            core_err = V35_CE_SLOTS;
        else if (!first && ((a_req_fetch != q_fetch_issue) || (a_req_eu != e_x_cyc)
                 || (a_req_eu && (a_req_kind != e_x_cyc_kind || a_req_addr != e_x_cyc_addr
                                  || a_req_width != e_x_cyc_width))))
            core_err = V35_CE_CYCLE;
        else if (b_req_start && !first && a_req_len != start_len)
            core_err = V35_CE_LEN;
    end
    assign err_code = {core_err, arb_err[2:0], eu_err[2:0]};

    always @(posedge clock) begin
        if (!reset_n) begin
            first <= 1'b1;
            eu_owner <= 1'b0;
            error <= 1'b0;
        end else if (commit) begin
            first <= 1'b0;
            if (b_req_start)
                eu_owner <= !first && a_req_eu;
            if (core_err != 2'd0 || arb_err != 8'd0 || eu_err != 8'd0)
                error <= 1'b1;
        end
        if (reset_n && (biu_error || q_error || eu_error || arb_error))
            error <= 1'b1;
    end

`ifdef V35S_STATE_DUMP
    assign eu_l = eu_state_l;
    assign eu_e = eu_state_e;
    assign q_c = q_state_c;
    assign q_ops = q_state_op;
    assign q_e = q_state_e;
    assign a_x = a_state_x;
    assign r_r = rf_state_r;
    assign r_e = rf_state_e;
    assign biu_dump = biu_state;
    assign slots = qops;
    assign slot_rd = q_rd;
    assign n_tl = eu_n_tl;
    assign n_t = eu_n_t;
    assign n_x = a_n_q;
    assign n_p = eu_n_p;
    assign xops = a_xop;
    assign x_cyc = e_x_cyc;
    assign x_cyc_kind = e_x_cyc_kind;
    assign x_cyc_addr = e_x_cyc_addr;
    assign x_cyc_width = e_x_cyc_width;
    assign req_start = b_req_start;
    assign req_ext = b_req_ext;
    assign b_busy = busy;
    assign b_free = free;
    assign b_finf = fetch_inflight;
    assign b_busy_x = busy_x;
    assign b_free_x = free_x;
    assign b_wl_x = wlatch_busy_x;
    assign x_data = eu_xd;
`endif
endmodule
