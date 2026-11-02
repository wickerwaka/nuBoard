`timescale 1ns/1ps

// V35S core v2: the arbiter, S2 scope (docs/v35s-core-v2.md, "Modules and the state they own";
// Appendix B §1 "Request records", §2 S4). It holds the bus unit's one request slot (the EU's
// data or I/O request: a scripted record in S2) and picks the clock's bus cycle as one priority
// tree: the slot's cycle, the aborted fetch cycle, or a fetch. The rules are the model's
// (validation/v35s/chains/sim/arbiter.py: Request.counts 137, arbitrate 180, _fetch_first 429,
// _choose 507) under fit 62, the ones the S2 families read:
//
//   counting      data_while_fetch=wait_before (counted before the choice), io_count=nowait,
//                 setup_free (the last free_need clocks fetch-free), grp_free_bus (the prelude's
//                 group stores), dw_count=bus, dw_count_b2b
//   fetch holds   hold_fetch=le_q (hold_count=ahead, hold_q 3), io_hold=posted_b2b, the I/O
//                 lead (lift), io_recover 2, free_run=run, free_hold=delivery, wb_fetch=hold,
//                 wlatch_hold, io_ir_hold (the queue's io_held)
//   choice        arbiter=b2b (_fetch_first: b2b_at, or became-issuable and requested on the
//                 same clock), the aborted cycle (abort_fetch=retry, abort_latched=any),
//                 request_reissue=no_mem (mem_waiting), free_idle / free_idle_b2b, port_latch=
//                 relatch with port_ready=issue and port_issue (not_before)
//   not built     (TODO S4, named zero inputs or absent): the window FSM (grp_io_hold,
//                 slot_fetch, the nowrite slot, sreg_*), the queued requests behind a detached
//                 one, the odd-word pair, disp_io, imm1_first, alu_busy, refresh
//
// Registered state (widths) and the model variables it replaces (the slot's Request):
//   v 1, kind 3, addr 20, width 2, data 16       Request.cycles[0], the EU's datum
//   setup 7, count 7                             setup, count
//   fn_v 1, fn 3, fo 3                           free_need (None: fn_v 0), free_orig
//   lead 2, nowait 1, port 1, detached 1, grp 1  lead, nowait, port, detached, free_bus
//   issued 1                                     issued (its one cycle)
//   nb 4                                         not_before - t (a countdown; 0: no floor)
//   rs_v 1                                       ready_since is set (ready_since == t: rs_now)
//   lift_v 1                                     lift_t is set (t == lift_t: lift_now)
//   fh_prev 1                                    free_held == t-1
//   rq_le 1                                      the queue's requested_at <= posted
//   held 1                                       port_held (relatched by the port take on t)
module v35_arbiter
    import v35_front_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce,

    // the EU's post (S2, or S5 after an I/O issue)
    input  wire        post_t,
    input  req_t       rq_t,
    input  wire        post_p,
    input  req_t       rq_p,
    input  wire        retire,          // the EU retired its request (its cycle ended)
    // port_latch=relatch: a port byte taken now (T) holds a waiting I/O relatch clocks
    input  wire        relatch,
    input  wire        relatch_late,    // port_landed: a clock later
    input  wire [1:0]  relatch_n,       // the slot request's class relatch
    // the EU (S2)
    input  wire        halting,         // halt_status: HALT started on this clock
    input  wire        halted,
    input  wire [2:0]  need,            // decoder.need (hold_count=ahead)
    input  wire        wb_hold,         // wb_fetch=hold: a wbsync form started, its wait on
    input  wire        latch_wait,      // wlatch_hold: an I/O form waits for the data latch
    // the queue (S3)
    input  wire        want_x,
    input  wire        rq_v_x,
    input  wire        rq_now_x,
    input  wire        rq_v_end,        // requested_at is set at the clock's end (rq_le)
    input  wire        b2b_now,
    input  wire signed [4:0] room_x,
    input  wire        inflight_c,
    input  wire        triple_x,
    input  wire        lat_x,
    input  wire        arrived_now,
    input  wire        io_hold_x,
    // S4 (TODO, named zero inputs in S2): the request window FSM's hold, the nowrite slot's
    // request, the ALU's busy clocks
    input  wire        win_hold,
    input  wire        nowrite_slot,
    input  wire        alu_busy,
    // the bus (S0)
    input  wire        free,
    input  wire        busy,
    input  wire        fetch_inflight,
    input  wire        in_wait,
    input  wire        fetch_end_prev,
    input  wire        fetch_run_prev,
    input  wire        io_win,
    input  wire [2:0]  fetch_len,
    input  wire [19:0] fetch_addr,
    input  wire        dlv_eu,          // the slot's cycle ended on t-1 (its delivery)

    // S4: the grant
    output wire        g_start,
    output wire [2:0]  g_kind,
    output wire [19:0] g_addr,
    output wire [1:0]  g_width,
    output wire [15:0] g_data,
    output wire        g_fetch,
    output wire        g_eu,            // the slot's cycle
    output wire        g_abort,
    output wire        g_mem_waiting,
    output wire        g_b2b,
    output wire        rq_set_x,        // free_hold: the held fetch dates from now
    output wire        retick,          // a detached I/O issued: the EU's second pass (S5)
    // the slot, as the EU reads it
    output wire        slot_v,
    output wire        slot_wait_c,     // a request waits unissued (before S4)
    output wire        slot_wait_p,     // ... after S4
    output wire        slot_det_c,      // ... and is a detached I/O write (io_interlock)
    output wire        slot_det_p,
    output wire        own_issued,      // the EU's own request is on the bus (ISSUED rows)
    output wire        own_done,        // its cycle ended on t-1 (data_ready 0; write_wait=mem_end)
    // the trace
    output wire [6:0]  count_o,
    output wire        ready_o
);
    // ------------------------------------------------------------ registered state
    reg        v = 1'b0;
    reg [2:0]  kind = K_NONE;
    reg [19:0] addr = 20'd0;
    reg [1:0]  width = BW_WORD;
    reg [15:0] data = 16'd0;
    reg [6:0]  setup = 7'd0;
    reg [6:0]  count = 7'd0;
    reg        fn_v = 1'b0;
    reg [2:0]  fn = 3'd0;
    reg [2:0]  fo = 3'd0;
    reg [1:0]  lead = 2'd0;
    reg        nowait = 1'b0;
    reg        port = 1'b0;
    reg        detached = 1'b0;
    reg        grp = 1'b0;
    reg        issued = 1'b0;
    reg [3:0]  nb = 4'd0;
    reg        rs_v = 1'b0;
    reg        lift_v = 1'b0;
    reg        fh_prev = 1'b0;
    reg        rq_le = 1'b0;

    // the slot as S2 sees it: a T post lands in it (the arbiter counts it on this clock)
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic logic [2:0] f_orig(input req_t r);    // free_orig
        f_orig = !r.fn_v ? 3'd0 : (7'(r.fn) < r.setup ? r.fn : 3'(r.setup));
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    wire       s_v = post_t ? 1'b1 : (retire ? 1'b0 : v);
    wire [2:0] s_kind = post_t ? rq_t.kind : kind;
    wire [19:0] s_addr = post_t ? rq_t.addr : addr;
    wire [1:0] s_width = post_t ? rq_t.width : width;
    wire [15:0] s_data = post_t ? rq_t.data : data;
    wire [6:0] s_setup = post_t ? rq_t.setup : setup;
    wire [6:0] s_count = post_t ? 7'd0 : count;
    wire       s_fn_v = post_t ? rq_t.fn_v : fn_v;
    wire [2:0] s_fn = post_t ? rq_t.fn : fn;
    wire [2:0] s_fo = post_t ? f_orig(rq_t) : fo;
    wire [1:0] s_lead = post_t ? rq_t.lead : lead;
    wire       s_nowait = post_t ? k_io(rq_t.kind) : nowait;
    wire       s_port = post_t ? rq_t.port : port;
    wire       s_det = post_t ? rq_t.detached : detached;
    wire       s_grp = post_t ? rq_t.grp : grp;
    wire       s_issued = post_t ? 1'b0 : issued;
    wire       s_rs = post_t ? 1'b0 : rs_v;
    wire       s_lift = post_t ? 1'b0 : lift_v;
    wire       s_fh = post_t ? 1'b0 : fh_prev;
    wire       s_io = k_io(s_kind);
    wire       pending = s_v && !s_issued;

    assign slot_v = v;
    assign slot_wait_c = v && !issued;
    assign slot_det_c = v && !issued && detached && kind == K_IO_WRITE;
    assign own_issued = v && issued && !detached;
    assign own_done = v && issued && !detached && dlv_eu;

    // port_latch=relatch (eu._port_take): the waiting detached I/O is held to relatch clocks
    // after the port take, unless it issues on this clock (port_ready=issue: ready, or a nowait
    // count that counts out now, port_ready_count=count; past its floor, the bus idle)
    wire       rl_skip = (count >= setup || (nowait && count + 7'd1 >= setup)) && nb == 4'd0
                         && !busy;
    wire       rl_hit = relatch && v && !issued && detached && !rl_skip;
    wire [3:0] rl_d = 4'(relatch_n) + (relatch_late ? 4'd1 : 4'd0);
    wire [3:0] nb_t = rl_hit && rl_d > nb ? rl_d : nb;     // not_before - t, this clock

    // ------------------------------------------------------------ S4: counting
    wire [6:0] need_free = s_fn_v ? (7'(s_fn) < s_setup ? 7'(s_fn) : s_setup) : s_setup;
    wire counts_grp = !io_win && (!busy || s_count < s_setup - need_free);
    wire counts_mem = !fetch_inflight || s_count < s_setup - need_free;
    wire counts = s_nowait ? !in_wait : (s_grp ? counts_grp : counts_mem);
    wire cnt_inc = !halting && pending && s_count < s_setup && counts;
    wire [6:0] count_x = s_count + (cnt_inc ? 7'd1 : 7'd0);
    wire ready_x = count_x >= s_setup;
    wire holding_x = {1'b0, count_x} < {1'b0, s_setup} - 8'(s_lead);

    // ------------------------------------------------------------ S4: the choice (_choose)
    wire fw0 = want_x && !halted;
    wire recovering = pending && !s_io && io_win;
    // free_run=run: a request counting its fetch-free clocks lets the delivery-clock fetch run
    wire free_run = pending && !s_io && s_fn_v && {1'b0, count_x} > {1'b0, s_setup} - 8'(s_fn)
                    && fetch_end_prev && (!rq_v_x || rq_now_x);
    wire [2:0] fn_r = (free_run && fw0) ? 3'd0 : s_fn;
    // free_hold=delivery
    wire fh_cand = pending && fw0 && !s_io;
    wire fh_date = fh_cand && s_fh;
    wire [2:0] fn_h = (fh_date && fn_r != 3'd0) ? 3'd0 : fn_r;
    wire fh_hold = fh_cand && !s_fh && s_fn_v && fn_r != 3'd0
                   && count_x == s_setup - 7'(fn_r) && fetch_end_prev && rq_now_x && !b2b_now
                   && !fetch_run_prev;
    assign rq_set_x = fh_date;
    wire rq_now = rq_now_x || fh_date;
    wire fw1 = fw0 && !fh_hold;
    // hold_fetch=le_q (hold_count=ahead), io_hold=posted_b2b
    wire signed [5:0] counted = 6'sd6 - 6'(room_x);
    wire hold_le = counted - $signed({3'd0, need}) > 6'(FIT_HOLD_Q);
    wire hf_on = pending && (holding_x || recovering) && !free_run;
    wire hf_pass = s_io && b2b_now;
    wire hf_block = hf_on && !hf_pass && ((s_io && !post_t) || hold_le);
    wire fw2 = fw1 && !hf_block;
    // wb_fetch=hold
    wire fw3 = fw2 && !(wb_hold && !b2b_now && rq_v_x && (!rq_now || arrived_now));
    // io_ir_hold, wlatch_hold
    wire fw4 = fw3 && !io_hold_x && !latch_wait;
    // the I/O lead: committed to the request; a fetch requested no later than its post, on the
    // clock the hold lifts, runs first
    wire lead_on = pending && s_lead != 2'd0 && !holding_x;
    wire lift_now = lead_on && !s_lift;
    wire rq_le_now = post_t ? 1'b1 : (rq_le && !rq_now);
    wire lead_block = lead_on && (!lift_now || !rq_v_x || !rq_le_now);
    wire fetch_want = fw4 && !lead_block;
    wire unused_s4 = &{1'b0, win_hold, nowrite_slot, alu_busy};
    // the slot's issuable request
    wire issuable = pending && ready_x && nb_t == 4'd0 && !recovering;
    wire rs_now = issuable && !s_rs;
    wire fetch_first = !s_issued && (b2b_now || (rs_now && rq_now));
    wire eu_go = free && issuable && !(fetch_want && fetch_first);
    wire latched_abort = !fetch_want && triple_x && lat_x && !arrived_now && !inflight_c
                         && room_x + 5'sd1 == 5'sd2 && !halted;
    wire abort_go = free && !eu_go && ((fetch_want && triple_x && room_x == 5'sd2)
                                       || latched_abort);
    wire fetch_go = free && !eu_go && !abort_go && fetch_want;
    // the grant
    wire mem_wait = pending && !s_io;
    assign g_eu = eu_go;
    assign g_fetch = fetch_go;
    assign g_abort = abort_go;
    assign g_start = eu_go || fetch_go;
    assign g_kind = eu_go ? s_kind : K_FETCH;
    assign g_addr = eu_go ? s_addr : fetch_addr;
    assign g_width = eu_go ? s_width : BW_WORD;
    assign g_data = eu_go ? s_data : 16'd0;
    assign g_mem_waiting = mem_wait;
    assign g_b2b = fetch_go && b2b_now;
    assign retick = eu_go && s_det;
    assign slot_wait_p = s_v && !s_issued && !(eu_go && s_det) && !eu_go;
    assign slot_det_p = slot_wait_p && s_det && s_kind == K_IO_WRITE;
    // free_idle (free_idle_b2b): the request's fetch-free clock taken by a run's delivery-clock
    // fetch (or a b2b one): an idle clock after it, the request no earlier than the next
    wire fresh = rq_now && fetch_end_prev;
    wire free_idle = fetch_go && mem_wait && s_fo != 3'd0 && !s_fh
                     && count_x == s_setup - 7'(s_fo) && ((fresh && fetch_run_prev) || b2b_now);
    // dw_count=bus, dw_count_b2b: a DW-form I/O request's clock taken by a cycle starting
    wire dw1 = fetch_go && s_v && s_io && !s_port && !s_issued && post_t
               && count_x != 7'd0;
    wire dw2 = fetch_go && s_v && s_io && !s_port && !s_issued && !post_t && cnt_inc && b2b_now;
    wire [6:0] count_e = count_x - ((dw1 || dw2) ? 7'd1 : 7'd0);
    assign count_o = count_x;
    assign ready_o = ready_x;

    // ------------------------------------------------------------ S6: the next state
    // port_issue (machine.py:197-203): a fetch issued on the port take's clock relatches a clock
    // later; free_idle's floor
    wire [3:0] nb_e0 = nb_t == 4'd0 ? 4'd0 : nb_t - 4'd1;
    wire [3:0] nb_pi = (rl_hit && fetch_go) ? 4'(relatch_n) : 4'd0;
    wire [3:0] nb_fi = free_idle ? 4'(fetch_len) : 4'd0;
    wire [3:0] nb_e1 = nb_pi > nb_e0 ? nb_pi : nb_e0;
    wire [3:0] nb_e = nb_fi > nb_e1 ? nb_fi : nb_e1;
    always @(posedge clock) begin
        if (!reset_n) begin
            v <= 1'b0;
            issued <= 1'b0;
            count <= 7'd0;
            nb <= 4'd0;
            rs_v <= 1'b0;
            lift_v <= 1'b0;
            fh_prev <= 1'b0;
            rq_le <= 1'b0;
        end else if (ce) begin
            if (post_p) begin
                v <= 1'b1;
                kind <= rq_p.kind;
                addr <= rq_p.addr;
                width <= rq_p.width;
                data <= rq_p.data;
                setup <= rq_p.setup;
                count <= 7'd0;
                fn_v <= rq_p.fn_v;
                fn <= rq_p.fn;
                fo <= f_orig(rq_p);
                lead <= rq_p.lead;
                nowait <= k_io(rq_p.kind);
                port <= rq_p.port;
                detached <= rq_p.detached;
                grp <= rq_p.grp;
                issued <= 1'b0;
                nb <= 4'd0;
                rs_v <= 1'b0;
                lift_v <= 1'b0;
                fh_prev <= 1'b0;
                rq_le <= rq_v_end;
            end else begin
                v <= s_v && !(eu_go && s_det);      // a detached I/O issued: the slot moves on
                kind <= s_kind;
                addr <= s_addr;
                width <= s_width;
                data <= s_data;
                setup <= s_setup;
                count <= count_e;
                fn_v <= s_fn_v;
                fn <= fn_h;
                fo <= s_fo;
                lead <= s_lead;
                nowait <= s_nowait;
                port <= s_port;
                detached <= s_det;
                grp <= s_grp;
                issued <= s_issued || eu_go;
                nb <= nb_e;
                rs_v <= s_rs || issuable;
                lift_v <= s_lift || lift_now;
                fh_prev <= fh_hold;
                rq_le <= rq_le_now && rq_v_end;
            end
        end
    end
endmodule
