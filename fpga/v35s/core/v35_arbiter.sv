`timescale 1ns/1ps

// V35S arbiter (HDL plan, Phase C4), written from the frozen chain model
// (validation/v35s/chains/sim/frozen/arbiter.py: arbitrate, _choose, _fetch_first, _fetch_run,
// Request.counts/ready/holding; machine.py for the clock's phases) and the spec
// (docs/v35s-chain-rtl-spec.md, A2 "The request record", A3 "From the queue/decoder/EU/bus
// unit", "Writes the arbiter makes into the other machines (phase X)", "The arbiter as a
// decision table").
//
// The arbiter picks the bus cycle that starts on a model clock (phase X): a fetch, the EU's
// data or I/O cycle, the left-out write's slot, an aborted cycle, or nothing; before and after
// the choice it counts the waiting request's setup clocks. It reads the EU and the decoder after
// phase L (state_l of v35_eu.sv, with the requests posted in T/L), the queue before each of its
// own ops (the queue's per-op state, v35_queue.sv's state_op, and each op's read), and the bus
// unit before the choice. It writes the queue through its op chain (C2's V35_QOP_* codes:
// wants_fetch, room/counted, triple, issue, abort, the re-dating, io_ir_hold's release), the
// EU through C3's touches (V35_XOP_*: issue, the left-out write's slot, the fetch on a start
// clock, the abort's take sync, a request's free_need and not_before), and the bus unit
// through its request port (the start, its kind, address, width, the disp_io extension and
// the data latch's fill).
//
// State (v35_ast_t, rtl_vectors.ARFIELDS): the request record's arbiter-owned fields, by the
// EU's request positions (the slot and the two queued behind a detached I/O, shifting with
// them on a promotion): the setup count, the age of the post (t - posted, re-dated when a
// queued request moves into the slot), ready_since, lift_t, free_held and grp_held as flags
// for "== t" (the next clock reads "== t-1" from them); and the bus history the rules read:
// whether the last two cycles were fetches back to back (_fetch_run), and the age of the last
// I/O cycle's start (grp_io_hold). The record's other fields (setup, free_need, not_before,
// the flags) are the EU's (v35_req_t), which the arbiter reads and writes through its touches.
//
// Clocking. `ce` marks the END of a model clock. One clock is combinational: the clock's
// start (the ages move), the requests posted in T/L (their records start), the count before
// the choice, _choose, the count after it and the DW adjustments (arbitrate), then, for the
// end of the clock, the requests posted in P and those the EU retired.
//
// (C5) Refresh: with a refresh request pending (v35_refresh.sv, phase R) on a free bus,
// _refresh starts the refresh cycle unless the cycle that would otherwise start goes first
// (refresh_fetch=refresh, refresh_data=refresh: none does) or a rule keeps it off the bus: the
// halt status's second clock (refresh_halt=status), a posted I/O's lead (refresh_lead=closed,
// refresh_lead_port=last, refresh_step_lead=step), the relatched I/O's wait (refresh_relatch),
// the I/O's steps (refresh_io_step=own: io_step), the latch wait (refresh_wlatch), the EU's
// micro-boundaries (refresh_accept=boundary_bus: EU.refresh_ok, the boundary map of
// v35_eu_pkg). Starting it, the fetch request it beats is aborted (refresh_abort), kept
// (refresh_drop_post), lost (refresh_drop, refresh_drop_on=odd, refresh_drop_unit=unit,
// refresh_lost=start) or goes next (refresh_after=fetch_next, halt_refresh=run_drop); the
// EU's hold and the setup extensions (EU.refresh_cost: refresh_post=post_beat, refresh_grpcl,
// refresh_rmw_loop/_shape) go to the EU as touches, as does the halt status's deferral. The
// early fetch run (refresh_sync=run: bus.early, early_ok, early_n) is the arbiter's bus
// history, as are the cycles io_step and refresh_beat_t4/_b2b look back at; dw_view=eu's xeu
// is per request position. The C4 fetch-run flag is left unchanged on a refresh start.
module v35_arbiter
    import v35_decoder_pkg::*;
    import v35_eu_pkg::*;
    import v35_queue_pkg::*;
#(
    parameter int NXQ = 8,                  // the arbiter's queue ops per clock
    parameter int NXOP = 6,                 // its touches on the EU per clock (v35_eu.sv)
    parameter int STATE_W = 103,            // $bits(v35_ast_t), checked below
    parameter int ESTATE_W = 762,           // v35_eu.sv's STATE_W
    parameter int QSTATE_W = 180            // v35_queue.sv's STATE_W
) (
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce,                  // end of a model clock

    // the EU after phase L and the requests posted in T/L; at the end of the clock, the EU's
    // state and the requests posted in P
    input  wire [ESTATE_W-1:0] eu_l,
    input  wire [2:0]  fresh_l,
    input  wire [ESTATE_W-1:0] eu_e,
    input  wire [2:0]  fresh_p,

    // the queue before each of the arbiter's ops (qv[0]: after the EU's T/L ops) and each read
    input  wire [NXQ:0][QSTATE_W-1:0] qv,
    input  wire [NXQ-1:0][7:0] qrd,

    // the bus unit before the choice (the core shows the prelude's POP read on clock 0)
    input  wire        b_busy,
    input  wire        b_free,
    input  wire [2:0]  b_kind,              // the cycle on the bus (V35_K_NONE: idle) ...
    input  wire [2:0]  b_pos,               // ... t - its start ...
    input  wire [2:0]  b_len,               // ... its length
    input  wire        b_in_wait,
    input  wire        b_finf,
    input  wire        b_fprev,             // last_fetch_end == t-1
    input  wire        b_io_win,            // t <= last_io_end + io_recover
    input  wire        b_done,              // the cycle that ended on t-1 ...
    input  wire [2:0]  b_done_kind,         // ... its kind
    input  wire [15:0] wtc,                 // the bus unit's waits (a cycle's length)
    // (C5) the refresh controller after phase R
    input  wire        refresh_on,          // the chain runs the controller (refresh_any)
    input  wire        rf_pending,          // a refresh request is pending
    input  wire [2:0]  rf_len,              // the refresh cycle's length (bus.refresh_length)

    // the queue ops of phase X (v35_qop words: code, a, b, val, snap), in order
    output logic [NXQ-1:0][32:0] qop,
    output logic [3:0]  n_q,
    // the touches on the EU ({V35_XOP_*, val}) and the cycle the EU's phase P reads
    output logic [NXOP-1:0][V35_XOP_W-1:0] xop,
    output logic        x_valid,
    output logic [2:0]  x_kind,
    output logic        x_eu,               // the cycle is the EU's (eu.issue)
    // the setup counts by request position: at the clock's start (T) and after X (P)
    output logic [2:0][6:0] counts_t,
    output logic [2:0][6:0] counts_p,
    // the bus unit's request
    output logic        req_start,
    output logic        req_fetch,          // ... a fetch (the queue's address, the image's word)
    output logic        req_eu,             // ... the EU's data or I/O cycle
    output logic [2:0]  req_kind,
    output logic [19:0] req_addr,           // (the EU's cycle; a fetch's is the queue's)
    output logic [1:0]  req_width,
    output logic [2:0]  req_len,            // its length (the touch's val)
    output logic        req_ext,            // disp_io=extend
    output logic        req_latch,          // an EU read: its datum fills the data latch
    // (C5) the RFM store issued (the controller's write) and the early fetch run the EU reads
    // before the choice (T) and after it (P) (v35_early_t)
    output logic        sfr_wr,
    output logic [7:0]  sfr_value,
    output logic [4:0]  early_t,
    output logic [4:0]  early_p,
    output reg          error,              // sticky: a case the RTL does not cover
    output logic [7:0]  err_code,           // this clock's (0: none)
    output wire [STATE_W-1:0] state_x       // after X (the end of the clock: state_e)
`ifdef V35S_STATE_DUMP
    ,
    output wire [STATE_W-1:0] state_e,
    output wire [STATE_W-1:0] state_dump,   // as registered at the last ce
    input  wire [3:0]  mutate               // the bench's mutation tests (0: none)
`endif
);

    // ---- error codes (err_code)
    localparam logic [7:0] V35_AE_OPS = 8'd1;          // more than NXQ queue ops in a clock
    localparam logic [7:0] V35_AE_XOPS = 8'd2;         // more than NXOP touches on the EU
    localparam logic [7:0] V35_AE_SAT = 8'd3;          // a stamp order past a saturated age

    // ---- the state (rtl_vectors.ARFIELDS, MSB first)
    typedef struct packed {
        logic [6:0] count;          // setup clocks counted
        logic [7:0] p_age;          // t - posted (saturating at 255)
        logic       rs_v;           // ready_since is set ...
        logic       rs_now;         // ... == t
        logic       lift_v;         // lift_t is set ...
        logic       lift_now;       // ... == t
        logic       fh_now;         // free_held == t (free_hold)
        logic       gh_now;         // grp_held == t (grp_io_hold)
        logic [2:0] xeu;            // (C5) dw_view=eu: t, t-1, t-2 in xeu (bit 0: t)
    } v35_arq_t;

    typedef struct packed {
        v35_arq_t [2:0] q;          // by request position: q[0] the slot, q[1], q[2] queued
        logic       run;            // the last two cycles were fetches back to back
        logic       io_v;           // an I/O cycle has started ...
        logic [3:0] io_age;         // ... t - its start (saturating at 15)
        // (C5) the bus history the refresh's rules read
        logic       early_on;       // refresh_sync=run: the cycle last started is bus.early
        logic       early_ok;       // the last refresh beat a fetch the take sync counted
        logic [2:0] early_n;        // fetches in the early run (saturating at 7)
        logic       after_ref;      // the cycle last started began right after a refresh's end
        logic [7:0] lc_age;         // t - the last cycle's end (0 while it covers t; sat 255)
        logic       rf_v;           // a refresh has started ...
        logic [1:0] rf_n;           // ... cycles started after the last one (saturating at 3)
        logic [7:0] rf_age;         // ... t - its end (0 while it covers t; saturating at 255)
    } v35_ast_t;

    if ($bits(v35_ast_t) != STATE_W) begin : g_state_width
        $error("v35_arbiter: the state is %0d bits, STATE_W %0d", $bits(v35_ast_t), STATE_W);
    end
    if ($bits(v35_st_t) != ESTATE_W || $bits(v35_qstate_t) != QSTATE_W) begin : g_port_widths
        $error("v35_arbiter: the EU or queue state widths no longer match");
    end

    // the clock's work: the ops, the touches, the cycle
    typedef struct packed {
        logic [NXQ-1:0][32:0] ops;
        logic [3:0]  n;
        logic [NXOP-1:0][V35_XOP_W-1:0] xo;
        logic [3:0]  nx;
        logic        start;
        logic        fetch;
        logic        eu;
        logic [2:0]  kind;
        logic [19:0] addr;
        logic [1:0]  width;
        logic [2:0]  len;
        logic        ext;
        logic        promoted;      // the issue moved the next queued request into the slot
        logic        early_set;     // (C5) the fetch started is bus.early
        logic        sfr;           // (C5) the cycle is the RFM store
        logic [7:0]  err;
    } v35_actx_t;

    // the bus unit as a rule reads it (before the choice, or on the clock a cycle starts)
    typedef struct packed {
        logic       busy;
        logic [2:0] kind;
        logic [2:0] pos;
        logic [2:0] len;
        logic       in_wait;
        logic       finf;
        logic       io_win;
    } v35_abus_t;

    // ------------------------------------------------ helpers

    function automatic logic is_cls(input logic [5:0] cls, input int c);
        is_cls = int'(cls) == c;
    endfunction

    function automatic logic rk_io(input logic [2:0] rk);
        rk_io = int'(rk) == V35_RK_IO_READ || int'(rk) == V35_RK_IO_WRITE;
    endfunction

    function automatic logic k_io(input logic [2:0] k);
        k_io = k == V35_K_IO_READ || k == V35_K_IO_WRITE;
    endfunction

    function automatic void fail(inout v35_actx_t c, input logic [7:0] code);
        if (c.err == 8'd0)
            c.err = code;
    endfunction

    // bus.length(kind), the SFR store's I/O waits (sfr_cycle=io; v35_biu.sv's start_len)
    function automatic logic [2:0] cyc_len(input logic [2:0] kind, input logic [19:0] addr);
        logic [1:0] w;
        if (k_io(kind) || (kind == V35_K_WRITE && addr >= V35_SFR_PAGE))
            w = wtc[V35_WTC_IO_LSB +: 2];
        else
            w = wtc[V35_WTC_MEM_LSB +: 2];
        cyc_len = 3'(V35_BUS_BASE) + {1'b0, w};
    endfunction

    // the queue's state before the arbiter's next op
    function automatic v35_qstate_t qs(input v35_actx_t c);
        qs = v35_qstate_t'(qv[c.n]);
    endfunction

    // one queue op (snap: the decoder's and the EU's state after L); returns its read
    function automatic logic [7:0] q_opv(inout v35_actx_t c, input logic [4:0] snap,
                                         input logic [5:0] code, input logic a, input logic b,
                                         input int val);
        q_opv = 8'd0;
        if (int'(c.n) >= NXQ) begin
            fail(c, V35_AE_OPS);
        end else begin
            c.ops[c.n] = {code, a, b, 20'(val), snap};
            q_opv = qrd[c.n];
            c.n = c.n + 4'd1;
        end
    endfunction

    function automatic logic [7:0] q_op(inout v35_actx_t c, input logic [4:0] snap,
                                        input logic [5:0] code, input logic a, input logic b);
        q_op = q_opv(c, snap, code, a, b, 0);
    endfunction

    // queue.counted(t): 6 - room (a room op)
    function automatic int q_counted(inout v35_actx_t c, input logic [4:0] snap);
        q_counted = V35_QUEUE_BYTES - int'($signed(q_op(c, snap, V35_QOP_ROOM, 1'b0, 1'b0)));
    endfunction

    function automatic void x_op(inout v35_actx_t c, input logic [3:0] code, input int val);
        if (int'(c.nx) >= NXOP) begin
            fail(c, V35_AE_XOPS);
        end else begin
            c.xo[c.nx] = {code, 8'(val)};
            c.nx = c.nx + 4'd1;
        end
    endfunction

    // the order of queue.requested_at and req.posted from their ages: -1 earlier, 0 the same
    // clock, 1 later (requested_at must be set); a saturated age that leaves it open fails
    function automatic int rq_vs_posted(inout v35_actx_t c, input v35_qstate_t q,
                                        input logic [7:0] p_age);
        int rq, pa;
        rq = int'(q.rq_age);
        pa = int'(p_age);
        if ((rq == (1 << V35_W_Q_AGE) - 1 && pa >= rq) || (pa == 255 && rq >= pa))
            fail(c, V35_AE_SAT);
        rq_vs_posted = rq > pa ? -1 : rq == pa ? 0 : 1;
    endfunction

    // ------------------------------------------------ Request's methods
    // (the EU's record r, the arbiter's fields a; with free_need as the clock has it so far)

    function automatic logic req_ready(input v35_req_t r, input v35_arq_t a);
        req_ready = a.count >= r.setup;
    endfunction

    function automatic logic req_holding(input v35_req_t r, input v35_arq_t a);
        req_holding = int'(a.count) < int'(r.setup) - int'(r.lead);
    endfunction

    // Request.counts(fetch_inflight, mode="wait", bus, t); eh: the record's eu_halted (the EU's
    // HALT state for the slot's request, stored every clock; False for one just moved in)
    function automatic logic req_counts(input v35_req_t r, input v35_arq_t a, input v35_abus_t b,
                                        input logic eh);
        int need, setup, cnt, th;
        logic io;
        setup = int'(r.setup);
        cnt = int'(a.count);
        if (r.nowait) begin                     // io_count=nowait
            // refresh_io_stall=step (io_stall: an I/O request with refresh on): nor the
            // refresh's last clock when that would end on one of the I/O's steps
            if (refresh_on && !eh && b.busy && b.kind == V35_K_REFRESH && b.pos == b.len - 3'd1
                    && (setup - cnt - 1) % 2 == 0)
                return 1'b0;
            return !b.in_wait;
        end
        need = setup;
        if (r.free_v && int'(r.free) < setup)
            need = int'(r.free);
        io = (b.busy && k_io(b.kind)) || b.io_win;
        if (r.free_bus) begin                   // grp_free_bus
            if (r.gdisp)                        // grp_disp=hold: through a fetch
                return !io;
            if (io)
                return 1'b0;
            if (r.grpcl != '0 && b.busy && b.kind == V35_K_REFRESH)
                return {5'd0, b.pos} <= a.p_age;   // refresh_grpcl: a refresh is not a fetch
            return !b.busy || cnt < setup - need;
        end
        if (!b.finf)
            return 1'b1;
        th = int'(r.through);
        return cnt < (setup - need > th ? setup - need : th);
    endfunction

    // _fetch_run(bus, t): the fetch that ended at t-1 followed an earlier fetch back to back
    // (with prev, the fetch just started on t not counted: the same history)
    function automatic logic fetch_run(input v35_ast_t a);
        fetch_run = b_fprev && a.run;
    endfunction

    // ------------------------------------------------ (C5) the refresh's helpers

    // io_stepped: an I/O request still to issue, posted while the EU runs (not in HALT)
    function automatic logic io_stepped(input v35_req_t r, input v35_st_t e);
        io_stepped = r.valid && r.ncyc != '0 && r.issued == '0 && rk_io(r.kind) && !e.e.halted;
    endfunction

    // io_step (refresh_io_step=own, io_step_issue=step): t is one of the clocks a posted I/O
    // request's sequencer is at a step on, every second clock back from the issue its setup
    // gives (from setup - 5 after the post), restarted on the clock after a bus cycle that ran
    // during the setup; the post clock is one (not with issue). With issue: only after a refresh
    // in the setup (the model looks for one among the last three cycles, ended at or after the
    // post: the history's rf_n, rf_age). Called before the clock's choice only (the last cycle
    // started before t).
    function automatic logic io_step(inout v35_actx_t c, input v35_req_t r, input v35_arq_t aq,
                                     input v35_ast_t a, input logic issue);
        int pa, base, d1, e_, d;
        logic rs;
        pa = int'(aq.p_age);
        if (!issue && pa == 0)
            return 1'b1;
        if (pa == 255)
            fail(c, V35_AE_SAT);
        if (issue) begin
            rs = a.rf_v && a.rf_n <= 2'd2 && ((a.rf_n == 2'd0 && b_busy) || int'(a.rf_age) <= pa);
            if (a.rf_v && a.rf_n <= 2'd2 && !(a.rf_n == 2'd0 && b_busy) && a.rf_age == 8'd255)
                fail(c, V35_AE_SAT);
            if (!rs)
                return 1'b1;                    // no refresh in the setup: the count alone
        end
        base = int'(r.setup) - 5 > 0 ? int'(r.setup) - 5 : 0;
        d1 = pa - base;                         // t - (posted + max(0, setup - 5))
        // the last cycle: t - its end (negative while it runs)
        e_ = b_busy ? int'(b_pos) + 1 - int'(b_len) : int'(a.lc_age);
        if (!b_busy && a.lc_age == 8'd255)
            fail(c, V35_AE_SAT);
        d = d1;
        if (e_ <= pa && e_ - 1 < d1)            // it ended at or after the post: from its end + 1
            d = e_ - 1;
        return d >= 0 && d % 2 == 0;
    endfunction

    // the history's view of bus.early etc. as the EU reads it (v35_early_t)
    function automatic logic [4:0] early_view(input logic cur, input logic ep, input logic [2:0] n);
        early_view = {cur, ep, n};
    endfunction

    // EU.refresh_ok (refresh_accept=boundary_bus): whether a pending refresh may be taken on t;
    // w: the cycle the bus unit would otherwise start (_winner) is not None
    function automatic logic refresh_ok(inout v35_actx_t c, input v35_req_t r0, input v35_ast_t a,
                                        input v35_st_t e, input logic w);
        v35_qstate_t q;
        v35_stp_t st;
        int k, n, d, setup, cnt, need;
        q = qs(c);
        k = int'(e.e.k);
        n = eu_nsteps(e.e);
        st = k < n ? eu_step(e.e, k) : '0;
        setup = int'(r0.setup);
        cnt = int'(a.q[0].count);
        d = setup - cnt;
        if (k < n && int'(st.op) == V35_SOP_WBSYNC && e.e.wbu != '0)
            return 1'b0;                        // refresh_wb=free_wait: waiting for the write-back
        if (e.e.sync == SYNC_COUNT && q.ab_valid && k < n)
            return 1'b0;                        // refresh_abort_wait=run: the EU runs
        if (k < n && int'(st.op) == V35_SOP_TAKE && e.e.left != '0 && e.e.res == '0)
            return 1'b0;                        // refresh_take=last: mid-take
        if (eu_rmw_loop(e.e) != 0 && r0.valid && r0.ncyc != '0 && r0.issued == '0
                && int'(r0.kind) == V35_RK_WRITE && d > 0 && d <= eu_rmw_loop(e.e))
            return eu_rmw_bound(e.e, d, setup);  // refresh_rmw_loop=loop
        if (eu_inside(e.e)) begin
            if (e.e.clk_tag == CT_LOOP && e.e.cs_now)
                return 1'b1;                    // refresh_loop_entry=open
            return eu_boundary(e.e, q.take_now || q.take_prev,
                               q.latched && int'(q.count) > V35_QUEUE_BYTES, 1'b0);
        end
        if (w)
            return 1'b1;
        if (r0.valid && r0.ncyc != '0 && r0.issued == '0 && !r0.detached) begin
            need = (r0.free_v && int'(r0.free) < setup) ? int'(r0.free) : setup;
            if (r0.free_orig != '0)
                need = int'(r0.free_orig);      // refresh_window=posted
            if (r0.grpcl != '0 && d == int'(r0.grpcl) - 1)
                return 1'b1;                    // refresh_grpcl: the CL clocks' first
            if (a.q[0].p_age == '0 && (int'(r0.kind) == V35_RK_READ
                                       || int'(r0.kind) == V35_RK_WRITE))
                return 1'b1;                    // refresh_post: the post's first clock
            if (io_stepped(r0, e) && io_step(c, r0, a.q[0], a, 1'b0))
                return 1'b1;                    // refresh_io_step: the IN's I/O on a step
            return cnt == setup - need + 1;
        end
        return 1'b1;
    endfunction

    // EU.refresh_cost: a refresh of len clocks starts; the touches it makes (the setup
    // extensions of a memory shift's write and read, refresh_post's hold and beat_ext, the
    // EU's hold: V35_XOP_REFRESH's val[3])
    function automatic void refresh_cost(inout v35_actx_t c, inout v35_req_t r0,
                                         input v35_ast_t a, input v35_st_t e,
                                         input logic [2:0] len, input logic beat);
        int d, b, m, ext, need, setup;
        logic hold;
        setup = int'(r0.setup);
        d = setup - int'(a.q[0].count);
        hold = 1'b1;
        if (eu_rmw_loop(e.e) != 0 && r0.valid && r0.ncyc != '0 && r0.issued == '0
                && int'(r0.kind) == V35_RK_WRITE && d > 0 && d <= eu_rmw_loop(e.e)) begin
            // refresh_rmw_shape=shift: the hold to the next boundary below d
            b = 0;
            if (d - 1 >= FIT_REFRESH_TAIL_BOUND) b = FIT_REFRESH_TAIL_BOUND;
            m = d - 1 < eu_rmw_top(e.e) ? d - 1 : eu_rmw_top(e.e);
            if (m >= FIT_SHIFT_TAIL + 2) begin
                if ((m - FIT_SHIFT_TAIL) % 2 != 0) m = m - 1;
                if (m >= FIT_SHIFT_TAIL + 2 && m > b) b = m;
            end
            if (setup - 1 <= d - 1 && setup - 1 >= 0 && setup - 1 > b) b = setup - 1;
            ext = int'(len) - (d - b) > 0 ? int'(len) - (d - b) : 0;
            if (ext != 0) begin
                x_op(c, V35_XOP_SETUP, ext);
                r0.setup = r0.setup + 7'(ext);
            end
            hold = 1'b0;
        end else if (r0.valid && r0.grpcl != '0 && r0.ncyc != '0 && r0.issued == '0 && d > 0) begin
            // refresh_grpcl: the read's setup counts through the cycle
            b = d > int'(r0.grpcl) - 1 ? int'(r0.grpcl) - 1 : 0;
            ext = int'(len) - (d - b) > 0 ? int'(len) - (d - b) : 0;
            if (ext != 0) begin
                x_op(c, V35_XOP_SETUP, ext);
                r0.setup = r0.setup + 7'(ext);
            end
            hold = 1'b0;
        end else if (r0.valid && r0.ncyc != '0 && r0.issued == '0 && !r0.detached
                     && (int'(r0.kind) == V35_RK_READ || int'(r0.kind) == V35_RK_WRITE)
                     && d > 0 && !eu_inside(e.e)) begin
            // refresh_post=post_beat: the setup counts through the cycle; the EU holds at the
            // next boundary; beside a beaten fetch the hold given back if it runs first
            need = (r0.free_v && int'(r0.free) < setup) ? int'(r0.free) : setup;
            b = d > need - 1 ? need - 1 : 0;
            ext = int'(len) - (d - b) > 0 ? int'(len) - (d - b) : 0;
            if (ext != 0) begin
                x_op(c, V35_XOP_SETUP, ext);
                r0.setup = r0.setup + 7'(ext);
            end
            if (beat && 3'(ext) != r0.beat_ext) begin
                x_op(c, V35_XOP_BEAT, ext);
                r0.beat_ext = 3'(ext);
            end
        end
        x_op(c, V35_XOP_REFRESH, {28'd0, hold, len});
    endfunction

    // _beat_late (refresh_beat_b2b=imm): the decoder's state on the beaten fetch's delivery
    // clock that delays the fetch committed back to back
    function automatic logic beat_late(input v35_qstate_t q, input v35_st_t e);
        if (q.take_now)
            return 1'b1;
        if (e.e.start_age == '0)
            return is_cls(e.e.prev_cls, V35_CLS_IMM) && !is_cls(e.e.cls, V35_CLS_IMM);
        return is_cls(e.e.cls, V35_CLS_IMM) && e.d.need != '0;
    endfunction

    // the slot's next cycle (eu.issue's pop; odd_split=atomic)
    function automatic void slot_cycle(input v35_req_t r, output logic [2:0] kind,
                                       output logic [19:0] addr, output logic [1:0] width);
        case (int'(r.kind))
            V35_RK_READ: kind = V35_K_READ;
            V35_RK_WRITE: kind = V35_K_WRITE;
            V35_RK_IO_READ: kind = V35_K_IO_READ;
            V35_RK_IO_WRITE: kind = V35_K_IO_WRITE;
            default: kind = V35_K_NONE;
        endcase
        addr = r.addr;
        if (r.w2 && r.addr[0] && !rk_io(r.kind)) begin
            if (r.ncyc == 2'd2) begin
                width = V35_BW_HI;
            end else begin
                addr = r.addr + 20'd1;
                width = V35_BW_LO;
            end
        end else if (r.w2) begin
            width = V35_BW_WORD;
        end else begin
            width = r.addr[0] ? V35_BW_HI : V35_BW_LO;
        end
    endfunction

    // eu.issue: the slot's next cycle starts (a detached request issued whole: the next queued
    // request moves into the slot, eu._promote)
    function automatic void eu_issue(inout v35_actx_t c, inout v35_req_t r0, inout v35_ast_t a,
                                     input v35_st_t e);
        logic [2:0] kind;
        logic [19:0] addr;
        logic [1:0] width;
        slot_cycle(r0, kind, addr, width);
        c.start = 1'b1;
        c.eu = 1'b1;
        c.kind = kind;
        c.addr = addr;
        c.width = width;
        c.len = cyc_len(kind, addr);
        x_op(c, V35_XOP_ISSUE, int'(c.len));
        r0.ncyc = r0.ncyc - 2'd1;
        r0.issued = r0.issued + 2'd1;
        if (r0.ncyc == 2'd0 && r0.detached) begin
            c.promoted = 1'b1;
            a.q[0] = a.q[1];
            a.q[0].p_age = 8'd0;                // it counts its setup from this clock
            a.q[1] = a.q[2];
            a.q[2] = '0;
            r0 = e.r[1];
            if (r0.valid) begin
                if (!rk_io(r0.kind))
                    r0.moved = 1'b1;            // slot_fetch
                else if (!r0.port)
                    r0.dw_moved = 1'b1;         // dw_slot=behind
            end
        end
    endfunction

    // a fetch starts (queue.issue: the queue's address; the image's word)
    function automatic void start_fetch(inout v35_actx_t c, input logic [2:0] flen);
        c.start = 1'b1;
        c.fetch = 1'b1;
        c.kind = V35_K_FETCH;
        c.width = V35_BW_WORD;
        c.len = flen;
    endfunction

    // ------------------------------------------------ _fetch_first

    function automatic logic fetch_first(inout v35_actx_t c, input v35_req_t r0,
                                         input v35_ast_t a, input logic [4:0] snap,
                                         input logic [3:0] mut);
        v35_qstate_t q;
        logic ff;
        q = qs(c);
        // imm1_first=hold: a one-byte-immediate form's first data request on a non-run
        // delivery clock with more than hold_q bytes counted goes first
        if (r0.imm1 && !q.b2b_now && b_fprev && !fetch_run(a)
                && q_counted(c, snap) > FIT_HOLD_Q)
            return 1'b0;
        ff = r0.issued == 2'd0
             && (q.b2b_now || (a.q[0].rs_now && q.rq_valid && q.rq_age == '0));   // arbiter=b2b
        return mut == 4'd1 ? !ff : ff;
    endfunction

    // ------------------------------------------------ _choose

    function automatic void choose(inout v35_actx_t c, inout v35_req_t r0, inout v35_ast_t a,
                                   input v35_st_t e, input logic [2:0] flen,
                                   input logic [1:0] fhp, input logic [1:0] ghp,
                                   input logic [3:0] mut);
        // fhp/ghp: the slot's free_held / grp_held == t-1 (bit 0; bit 1 unused)
        v35_qstate_t q;
        v35_abus_t bb;
        logic [4:0] snap;
        logic rq, want, io, recovering, free_run, slot_fetch, latched_abort, mem, fresh, b2b,
              retry_loop, unit_md, go, step_lead, wr, drop_hold, odd;
        logic [7:0] rd;
        int setup, cnt, fr, room;
        snap = dec_snap(e.d, is_cls(e.e.cls, V35_CLS_IMM) && e.e.imm_bytes == 2'd2);
        bb = '{busy: b_busy, kind: b_kind, pos: b_pos, len: b_len, in_wait: b_in_wait,
               finf: b_finf, io_win: b_io_win};
        rq = r0.valid && r0.ncyc != 2'd0;      // req: the slot's request with cycles left
        io = rk_io(r0.kind);
        setup = int'(r0.setup);
        cnt = int'(a.q[0].count);
        // refresh_lost=start: a request lost to a refresh outside a count loop is evaluated again
        // on the next instruction's start; HALT's start leaves it to the halt status's clocks
        q = qs(c);
        if (q.lost_start && e.e.start_age == '0) begin
            if (e.e.halted && e.e.halt_now && !e.e.hd_v)
                void'(q_opv(c, snap, V35_QOP_LOST_HALT, 1'b0, 1'b0, 2));
            else
                void'(q_op(c, snap, V35_QOP_LOST_EVAL, 1'b0, 1'b0));
        end
        q = qs(c);
        if (q.la_valid && q.la_off == '0)
            void'(q_op(c, snap, V35_QOP_LOST_AFTER, 1'b0, 1'b0));
        rd = q_op(c, snap, V35_QOP_WANT, 1'b0, 1'b0);
        want = rd[0] && !e.e.halted;           // no prefetch in the HALT state
        // halt_refresh=run_drop: the fetches a refresh held off the bus before HALT started still
        // run once it has ended, as the queue requests them
        q = qs(c);
        if (e.e.halted && q.refresh_beaten) begin
            rd = q_op(c, snap, V35_QOP_WANT, 1'b0, 1'b0);
            if (rd[0])
                want = 1'b1;
        end
        recovering = rq && r0.issued == 2'd0 && !io && b_io_win;   // io_recover
        q = qs(c);
        free_run = rq && r0.issued == 2'd0 && !io && r0.free_v
                   && cnt > setup - int'(r0.free) && b_fprev
                   && (!q.rq_valid || q.rq_age == '0);              // free_run=run
        if (free_run && want) begin
            x_op(c, V35_XOP_FREE0, 0);
            r0.free_v = 1'b1;
            r0.free = '0;
        end
        // free_hold=delivery
        if (rq && r0.issued == 2'd0 && want && !io) begin
            fr = int'(r0.free);
            q = qs(c);
            if (fhp[0]) begin
                void'(q_op(c, snap, V35_QOP_REDATE, 1'b0, 1'b0));   // the held fetch dated t
                if (r0.free_v && r0.free != '0) begin
                    x_op(c, V35_XOP_FREE0, 0);
                    r0.free = '0;
                end
            end else if (r0.free_v && fr != 0 && cnt == setup - fr && b_fprev && q.rq_valid
                         && q.rq_age == '0 && !q.b2b_now && !fetch_run(a)) begin
                want = 1'b0;                    // held at the free clocks' eve
                a.q[0].fh_now = 1'b1;
            end
        end
        // grp_io_hold
        if (rq && r0.issued == 2'd0 && r0.free_bus && r0.free_v && r0.free != '0
                && cnt >= setup - int'(r0.free) && want && !io) begin
            q = qs(c);
            if (b_io_win && a.io_v && q.rq_valid && a.io_age == 4'd15)
                fail(c, V35_AE_SAT);            // inside the recovery: the I/O is recent
            if (b_io_win && a.io_v && q.rq_valid && q.rq_age <= V35_W_Q_AGE'(a.io_age)) begin
                want = 1'b0;
                a.q[0].gh_now = 1'b1;
            end else if (ghp[0]) begin
                void'(q_op(c, snap, V35_QOP_REDATE, 1'b0, 1'b0));
            end
        end
        // slot_fetch=slot
        q = qs(c);
        if (rq && r0.issued == 2'd0 && r0.moved && want && r0.free_v && r0.free != '0
                && !r0.free_bus && !req_ready(r0, a.q[0]) && q.rq_valid
                && rq_vs_posted(c, q, a.q[0].p_age) < 0) begin
            if (cnt <= setup - int'(r0.free)) begin
                want = 1'b0;
            end else begin
                x_op(c, V35_XOP_FREE0, 0);
                r0.free = '0;
            end
        end
        // grp_disp=hold: the queue's clocks, then the read's
        q = qs(c);
        if (want && !q.b2b_now && q.gd_valid && q.gd_off != '0) begin
            if (!q.take_now)
                want = 1'b0;
            else if ($signed(q_op(c, snap, V35_QOP_ROOM, 1'b0, 1'b0)) < 8'sd4)
                want = 1'b0;
        end
        q = qs(c);
        if (rq && r0.gdisp && r0.issued == 2'd0 && want && !q.b2b_now
                && cnt <= setup - int'(r0.free_orig)
                && (!q.rq_valid || rq_vs_posted(c, q, a.q[0].p_age) >= 0))
            want = 1'b0;
        // ea_b2b
        q = qs(c);
        if (want && q.b2b_now && e.e.mem && e.e.disp != '0 && e.d.ea_off != '0)
            want = 1'b0;
        // hold_fetch=le_q (hold_count=ahead, hold_q, io_hold=posted_b2b, io_recover,
        // disp_floor=posted)
        if (rq && r0.issued == 2'd0
                && (req_holding(r0, a.q[0]) || recovering || (r0.floor_hold && r0.nb_off != '0))
                && !free_run) begin
            q = qs(c);
            if (io && q.b2b_now) begin
                // a back-to-back fetch the bus unit committed to goes
            end else if (io && a.q[0].p_age != '0) begin
                want = 1'b0;
            end else if (q_counted(c, snap) - (r0.whole ? 0 : int'(e.d.need))
                         > (mut == 4'd2 ? FIT_HOLD_Q - 1 : FIT_HOLD_Q)) begin
                want = 1'b0;
            end
        end
        // io_ir_hold: released by the next start
        q = qs(c);
        if (q.io_held) begin
            if (q.io_started || !q.flag || q.inflight)
                void'(q_op(c, snap, V35_QOP_IO_HELD_CLR, 1'b0, 1'b0));
            else
                want = 1'b0;
        end
        // wlatch_hold
        if (e.e.latch_wait_now && want)
            want = 1'b0;
        // the lead: the bus unit committed to the I/O (io_hold=posted_b2b, dw_lift=moved,
        // dw_slot=behind)
        if (rq && r0.issued == 2'd0 && r0.lead != '0 && !req_holding(r0, a.q[0])) begin
            if (!a.q[0].lift_v && !(b_busy && b_kind == V35_K_REFRESH)) begin
                a.q[0].lift_v = 1'b1;           // refresh_lift=free: not on a refresh's clock
                a.q[0].lift_now = 1'b1;
            end
            q = qs(c);
            if (e.e.halted && q.refresh_beaten && q.b2b_now) begin
                // halt_refresh=run_drop: the committed run goes on
            end else if (q.io_run_now) begin
                // refresh_io_run=pair_out: the committed fetch goes
            end else if (!a.q[0].lift_now || !q.rq_valid
                         || rq_vs_posted(c, q, a.q[0].p_age) > 0
                         || (r0.dw_moved && rq_vs_posted(c, q, a.q[0].p_age) == 0)) begin
                want = 1'b0;
            end else if (r0.dw_moved && e.r[1].valid && q_counted(c, snap) > FIT_HOLD_Q) begin
                want = 1'b0;
            end
        end
        // refresh_after=fetch_next: a fetch request a refresh beat goes on the clock after the
        // refresh, ahead of a posted I/O request and its hold (a memory request keeps its turn)
        q = qs(c);
        if (q.ar_pend && q.ar_off == '0 && mut != 4'd6) begin
            rd = q_op(c, snap, V35_QOP_WANT, 1'b0, 1'b0);
            if (rd[0] && (!rq || r0.issued != 2'd0 || io)) begin
                want = 1'b1;
                if (rq && r0.issued == 2'd0)
                    rq = 1'b0;
            end
        end
        if (rq && r0.issued == 2'd0 && (!req_ready(r0, a.q[0]) || r0.nb_off != '0))
            rq = 1'b0;
        // io_step_issue=step: an IN's I/O after a refresh in its setup issues on one of its steps
        if (rq && refresh_on && io_stepped(r0, e) && !r0.detached
                && !io_step(c, r0, a.q[0], a, 1'b1))
            rq = 1'b0;
        if (recovering)
            rq = 1'b0;                          // no data cycle right after an I/O cycle
        if (rq && !a.q[0].rs_v) begin
            a.q[0].rs_v = 1'b1;
            a.q[0].rs_now = 1'b1;
        end
        if (!b_free)
            return;
        if (rq && r0.issued != 2'd0) begin      // the second half of an odd-word pair
            eu_issue(c, r0, a, e);
            return;
        end
        // a pending refresh (_refresh)
        if (refresh_on && rf_pending) begin
            // _winner: whether a cycle would otherwise start (its _fetch_first's ops)
            if (rq && want)
                void'(fetch_first(c, r0, a, snap, mut));
            go = 1'b1;
            if (e.e.halted && e.e.halt_prev && !e.e.hd_v)
                go = 1'b0;                      // refresh_halt=status: the status's second clock
            // refresh_step_lead=step: a port lead's step takes the refresh over the older fetch
            step_lead = go && r0.valid && r0.port && r0.detached && r0.lead != '0
                        && cnt == setup - int'(r0.lead) && want && io_stepped(r0, e)
                        && io_step(c, r0, a.q[0], a, 1'b0);
            if (go && r0.valid && r0.ncyc != '0 && r0.issued == '0 && io && r0.lead != '0
                    && setup - int'(r0.lead) <= cnt && cnt < setup
                    && !(r0.port && cnt < setup - 1 && !want) && !step_lead && mut != 4'd5)
                go = 1'b0;                      // refresh_lead=closed, refresh_lead_port=last
            if (go && r0.valid && r0.ncyc != '0 && r0.issued == '0 && io && cnt >= setup
                    && r0.nb_off != '0)
                go = 1'b0;                      // refresh_relatch=issue
            if (go && io_stepped(r0, e) && cnt < setup && !io_step(c, r0, a.q[0], a, 1'b0))
                go = 1'b0;                      // refresh_io_step=own
            if (go && e.e.latch_wait_now)
                go = 1'b0;                      // refresh_wlatch=hold
            if (go && !(io_stepped(r0, e) && cnt < setup && r0.detached)
                    && !refresh_ok(c, r0, a, e, rq || want))
                go = 1'b0;                      // refresh_accept=boundary_bus
            if (go) begin
                wr = want && !step_lead;
                if (wr) begin                   // refresh_abort=abort
                    rd = q_op(c, snap, V35_QOP_TRIPLE, 1'b0, 1'b0);
                    if (rd[0]) begin
                        rd = q_op(c, snap, V35_QOP_ROOM, 1'b0, 1'b0);
                        q = qs(c);
                        if ($signed(rd) == 8'sd2 && !q.inflight) begin
                            unit_md = is_cls(e.e.cls, V35_CLS_MUL) || is_cls(e.e.cls, V35_CLS_DIV);
                            retry_loop = e.e.start_age == '0
                                         && ((e.e.unit && unit_md)
                                             || ((is_cls(e.e.cls, V35_CLS_SHIFT_CL)
                                                  || is_cls(e.e.cls, V35_CLS_SHIFT_IMM))
                                                 && !e.e.mem)
                                             || (unit_md && !e.e.mem));
                            void'(q_op(c, snap, V35_QOP_ABORT, retry_loop, 1'b1));
                            wr = 1'b0;
                        end
                    end
                end
                q = qs(c);
                if (wr && r0.valid && r0.ncyc != '0 && r0.issued == '0 && io
                        && a.q[0].p_age == '0 && e.e.start_age != '0 && q.rq_valid
                        && q.rq_age == '0 && q.latched) begin
                    rd = q_op(c, snap, V35_QOP_ROOM, 1'b0, 1'b0);
                    if (rd[0])
                        wr = 1'b0;              // refresh_drop_post=hold
                end
                // refresh_drop, refresh_drop_on=odd, refresh_drop_unit=unit
                q = qs(c);
                if (wr && q.rq_valid && q.rq_age == '0 && q.arrived_now) begin
                    odd = 1'b0;
                    if (q.latched) begin
                        rd = q_op(c, snap, V35_QOP_ROOM, 1'b0, 1'b0);
                        odd = rd[0];
                    end
                    if (!odd) begin
                        rd = q_op(c, snap, V35_QOP_ROOM, 1'b0, 1'b0);
                        odd = $signed(rd) == 8'sd2 && eu_in_loop(e.e) && eu_inside(e.e);
                    end
                    if (odd) begin
                        // refresh_reraise=unit: only a count loop holds it to its exit (not one
                        // lost in a shift's exec); refresh_lost=start otherwise
                        drop_hold = eu_in_loop(e.e) && !(e.e.clk_tag == CT_EXEC && eu_inside(e.e));
                        void'(q_op(c, snap, V35_QOP_DROP, drop_hold, 1'b0));
                    end
                end
                c.start = 1'b1;
                c.kind = V35_K_REFRESH;
                c.addr = 20'd0;
                c.width = V35_BW_WORD;
                c.len = rf_len;
                q = qs(c);
                // refresh_sync=run: the beaten fetch is the one the EU's take sync counts
                a.early_ok = wr && !q.dropped && e.e.sync == SYNC_COUNT
                             && int'(e.e.owed) > int'(q.inflight);
                if (wr && !q.dropped)           // refresh_after=fetch_next, halt_refresh=run_drop
                    void'(q_opv(c, snap, V35_QOP_BEAT, e.e.halted, 1'b0, int'(rf_len)));
                refresh_cost(c, r0, a, e, rf_len, wr);   // refresh_post: eu.refresh_beat
                if (e.e.halted && e.e.halt_now)
                    x_op(c, V35_XOP_HALT_DEFER, int'(rf_len));   // refresh_halt=status
                return;
            end
        end
        if (rq && want && fetch_first(c, r0, a, snap, mut))
            rq = 1'b0;
        if (rq) begin
            if (int'(r0.kind) == V35_RK_NOWRITE) begin
                // grp_read=rmw_slot_any, slot_room=word: the left-out write's slot
                q = qs(c);
                room = int'($signed(q_op(c, snap, V35_QOP_ROOM, 1'b0, 1'b0)))
                       + (q.arrived_now ? 2 : 0);
                slot_fetch = want || (!q.inflight && !e.e.halted && room >= 2);
                r0.ncyc = r0.ncyc - 2'd1;
                if (slot_fetch) begin
                    void'(q_op(c, snap, V35_QOP_ISSUE, 1'b0, 1'b1));
                    start_fetch(c, flen);
                    x_op(c, V35_XOP_NOWRITE, int'(flen));
                end else begin
                    x_op(c, V35_XOP_NOWRITE, 0);
                end
                return;
            end
            eu_issue(c, r0, a, e);
            return;
        end
        // abort_fetch=retry, abort_latched=any
        latched_abort = 1'b0;
        if (!want) begin
            rd = q_op(c, snap, V35_QOP_TRIPLE, 1'b0, 1'b0);
            q = qs(c);
            if (rd[0] && q.latched && !q.arrived_now && !q.inflight)
                latched_abort = int'($signed(q_op(c, snap, V35_QOP_ROOM, 1'b0, 1'b0)))
                                + int'(q.latched) == 2 && !e.e.halted;
        end
        rd = 8'd0;
        if (want) begin
            rd = q_op(c, snap, V35_QOP_TRIPLE, 1'b0, 1'b0);
            if (rd[0])
                rd = {7'd0, $signed(q_op(c, snap, V35_QOP_ROOM, 1'b0, 1'b0)) == 8'sd2};
        end
        if ((want && rd[0]) || latched_abort) begin
            if (latched_abort && e.e.sync == SYNC_COUNT && e.e.owed == '0)
                x_op(c, V35_XOP_SYNC_ONE, 0);   // the take's sync waits for the cycle
            // abort_unit=loop, abort_reg: a unit form started on it retries at its loop's exit
            unit_md = is_cls(e.e.cls, V35_CLS_MUL) || is_cls(e.e.cls, V35_CLS_DIV);
            retry_loop = e.e.start_age == '0
                         && ((e.e.unit && unit_md)
                             || ((is_cls(e.e.cls, V35_CLS_SHIFT_CL)
                                  || is_cls(e.e.cls, V35_CLS_SHIFT_IMM)) && !e.e.mem)
                             || (unit_md && !e.e.mem));
            void'(q_op(c, snap, V35_QOP_ABORT, retry_loop, 1'b0));
            return;
        end
        // refresh_beat_t4=t4: on the delivery clock of a 3-clock fetch a refresh beat, the fetch
        // requested there is committed and starts on t+1; refresh_beat_b2b=imm: the fetch
        // committed back to back there waits a clock in _beat_late's states
        q = qs(c);
        if (want && refresh_on && q.arrived_now && !q.ir_now && b_done && b_done_kind == V35_K_FETCH
                && flen == 3'd3 && a.after_ref && q.ar_fetch
                && ((!q.b2b_now && q.latched && !q.take_now) || (q.b2b_now && beat_late(q, e)))) begin
            void'(q_op(c, snap, V35_QOP_T4, 1'b0, 1'b0));
            return;
        end
        if (want) begin
            q = qs(c);
            mem = r0.valid && r0.ncyc != 2'd0 && r0.issued == 2'd0 && !io;
            fresh = q.rq_valid && q.rq_age == '0 && b_fprev;
            b2b = q.b2b_now;
            if (mem && r0.beat_ext != '0 && q.ar_pend && q.ar_off == '0) begin
                // refresh_post=post_beat: the beaten fetch runs first, the hold is the window's
                x_op(c, V35_XOP_SETUP, -int'(r0.beat_ext));
                x_op(c, V35_XOP_BEAT, 0);
                r0.setup = r0.setup - 7'(r0.beat_ext);
                r0.beat_ext = '0;
                setup = int'(r0.setup);
            end
            void'(q_op(c, snap, V35_QOP_ISSUE, mem, 1'b0));   // request_reissue=no_mem
            start_fetch(c, flen);
            // refresh_sync=run: the beaten fetch the take sync counts, and the fetches back to
            // back behind it, run 2 clocks earlier for the EU (bus.early)
            q = qs(c);
            if (refresh_on && q.ar_pend && q.ar_off == '0 && a.early_ok) begin
                c.early_set = 1'b1;
                a.early_n = 3'd1;
            end else if (refresh_on && a.early_on && b_done) begin
                c.early_set = 1'b1;
                if (a.early_n != 3'd7) a.early_n = a.early_n + 3'd1;
            end
            // free_idle, free_idle_b2b: an idle clock after a run's delivery-clock fetch
            if (mem && r0.free_orig != '0 && !fhp[0] && cnt == setup - int'(r0.free_orig)
                    && ((fresh && fetch_run(a)) || b2b))
                x_op(c, V35_XOP_NOT_BEFORE, int'(r0.nb_off) > int'(flen) + 1 ? int'(r0.nb_off)
                                                                           : int'(flen) + 1);
        end
    endfunction

    // ------------------------------------------------ arbitrate and the clock's records

    v35_ast_t ra;                           // the end of the last model clock
    v35_ast_t a_x, a_e;
    v35_actx_t cx;
    logic [3:0] mut;

`ifdef V35S_STATE_DUMP
    assign mut = mutate;
`else
    assign mut = 4'd0;
`endif

    always_comb begin
        v35_st_t e, ee;
        v35_ast_t a;
        v35_actx_t c;
        v35_req_t r0, nw;
        v35_arq_t na;
        v35_abus_t bb, ba;
        logic halting, counted, rq, run_;
        logic [1:0] fhp, ghp;
        logic [2:0] flen;
        logic [6:0] base;
        int added;
        v35_qstate_t q0;
        e = v35_st_t'(eu_l);
        ee = v35_st_t'(eu_e);
        c = '0;
        run_ = 1'b0;
        added = 0;
        flen = cyc_len(V35_K_FETCH, 20'd0);
        // the clock's start: ages move, the "== t" flags become "== t-1"
        a = ra;
        fhp = {1'b0, ra.q[0].fh_now};
        ghp = {1'b0, ra.q[0].gh_now};
        for (int i = 0; i < 3; i++) begin
            if (a.q[i].p_age != 8'd255) a.q[i].p_age = a.q[i].p_age + 8'd1;
            a.q[i].rs_now = 1'b0;
            a.q[i].lift_now = 1'b0;
            a.q[i].fh_now = 1'b0;
            a.q[i].gh_now = 1'b0;
            a.q[i].xeu = {ra.q[i].xeu[1:0], 1'b0};   // t-1, t-2 from t, t-1
        end
        if (a.io_v && a.io_age != 4'd15) a.io_age = a.io_age + 4'd1;
        // the last cycle's and the last refresh's end, as ages (0 while it covers t)
        a.lc_age = b_busy ? 8'd0 : (ra.lc_age == 8'd255 ? 8'd255 : ra.lc_age + 8'd1);
        if (ra.rf_v)
            a.rf_age = (ra.rf_n == 2'd0 && b_busy) ? 8'd0
                       : (ra.rf_age == 8'd255 ? 8'd255 : ra.rf_age + 8'd1);
        // the requests the EU posted in T/L start their records; retired ones are gone
        for (int i = 0; i < 3; i++) begin
            if (fresh_l[i]) begin
                a.q[i] = '0;
                if (i == 0) begin fhp = '0; ghp = '0; end
            end else if (!e.r[i].valid) begin
                a.q[i] = '0;
                if (i == 0) begin fhp = '0; ghp = '0; end
            end
        end
        // arbitrate: the count before the choice (data_while_fetch=wait_before; halt_status)
        r0 = e.r[0];
        bb = '{busy: b_busy, kind: b_kind, pos: b_pos, len: b_len, in_wait: b_in_wait,
               finf: b_finf, io_win: b_io_win};
        // halt_status: HALT's clock (or the deferred status after a refresh, refresh_halt)
        halting = e.e.halt_now || (e.e.hd_v && !e.e.hd_past && e.e.hd_off == '0);
        counted = 1'b0;
        base = a.q[0].count;                    // dw_view's base: the count before this clock's
        rq = r0.valid && r0.ncyc != 2'd0;
        if (!halting && rq && r0.issued == 2'd0 && !req_ready(r0, a.q[0])
                && req_counts(r0, a.q[0], bb, e.e.halted)) begin
            a.q[0].count = a.q[0].count + 7'd1;
            counted = 1'b1;
        end
        choose(c, r0, a, e, flen, fhp, ghp, mut);
        // the request handed the slot by this clock's issue counts the clock as posted
        // before it (on the bus as the cycle starts: B1, its I/O recovery from the start)
        nw = r0;
        na = a.q[0];
        ba = '{busy: 1'b1, kind: c.kind, pos: 3'd0, len: c.len, in_wait: 1'b0, finf: 1'b0,
               io_win: b_io_win || k_io(c.kind)};
        if (!halting && c.promoted && nw.valid && nw.ncyc != 2'd0 && nw.issued == 2'd0
                && !req_ready(nw, na) && req_counts(nw, na, ba, 1'b0)) begin
            na.count = na.count + 7'd1;
        end
        // disp_io=extend: the form took its displacement on this I/O issue clock
        q0 = qs(c);
        c.ext = c.start && k_io(c.kind) && q0.disp_now && e.e.mem && e.e.disp != '0
                && mut != 4'd3;
        // dw_count=bus, dw_count_b2b
        if (c.start) begin
            if (c.kind == V35_K_FETCH && e.e.start_age == '0)
                x_op(c, V35_XOP_FETCH_START, 0);
            if (nw.valid && nw.ncyc != 2'd0 && rk_io(nw.kind) && !nw.port && nw.issued == 2'd0
                    && na.p_age == 8'd0 && na.count != '0 && mut != 4'd4) begin
                na.count = na.count - 7'd1;     // a DW form's first clock taken by the cycle
            end else if (c.kind == V35_K_FETCH && !c.promoted && nw.valid && nw.ncyc != 2'd0
                         && rk_io(nw.kind) && !nw.port && nw.issued == 2'd0
                         && na.p_age != 8'd0 && counted && !nw.dw_moved && q0.b2b_now) begin
                na.count = na.count - 7'd1;     // a back-to-back fetch starting
            end
        end
        // dw_view=eu: refresh_sync=run's early fetch run is 2 clocks earlier for the EU, and so
        // for the count of an I/O request it posted: a setup clock a fetch of the run keeps from
        // counting is the clock 2 earlier as the EU counts (_eu_view)
        if (refresh_on && nw.valid && nw.ncyc != 2'd0 && nw.issued == 2'd0 && rk_io(nw.kind)
                && nw.nowait && !(na.count > (c.promoted ? 7'd0 : base) || na.count >= nw.setup)) begin
            run_ = c.start ? (c.kind == V35_K_FETCH && c.early_set)
                           : (ra.early_on && b_busy && b_kind == V35_K_FETCH && b_in_wait);
            if (!run_) begin
                na.xeu[0] = 1'b1;
            end else begin
                added = 0;
                if (halting) begin
                    na.xeu[0] = 1'b1;
                    added = added + 1;
                end
                if (na.p_age >= 8'd2 && !na.xeu[2] && mut != 4'd7) begin
                    na.xeu[2] = 1'b1;
                    added = added + 1;
                end
                na.count = na.count + 7'(1 - added);
            end
        end
        a.q[0] = na;
        // the bus history: a fetch back to back behind a fetch (C4: unchanged on a refresh
        // start); the last I/O cycle's start; (C5) the early run, the last cycle's end, the
        // last refresh, a cycle right after a refresh's end
        if (c.start) begin
            if (c.kind != V35_K_REFRESH)
                a.run = c.kind == V35_K_FETCH && b_done && b_done_kind == V35_K_FETCH;
            if (k_io(c.kind)) begin
                a.io_v = 1'b1;
                a.io_age = 4'd0;
            end
            a.early_on = c.early_set;
            a.after_ref = b_done && b_done_kind == V35_K_REFRESH;
            a.lc_age = 8'd0;
            if (c.kind == V35_K_REFRESH) begin
                a.rf_v = 1'b1;
                a.rf_n = 2'd0;
                a.rf_age = 8'd0;
            end else if (a.rf_v && a.rf_n != 2'd3) begin
                a.rf_n = a.rf_n + 2'd1;
            end
        end
        a_x = a;
        // the end of the clock: the requests posted in P start their records; retired ones go
        for (int i = 0; i < 3; i++) begin
            if (fresh_p[i] || !ee.r[i].valid)
                a.q[i] = '0;
        end
        a_e = a;
        cx = c;
    end

    assign qop = cx.ops;
    assign n_q = cx.n;
    assign xop = cx.xo;
    assign x_valid = cx.start;
    assign x_kind = cx.kind;
    assign x_eu = cx.eu;
    assign req_start = cx.start;
    assign req_fetch = cx.fetch;
    assign req_eu = cx.eu;
    assign req_kind = cx.kind;
    assign req_addr = cx.addr;
    assign req_width = cx.width;
    assign req_len = cx.len;
    assign req_ext = cx.ext;
    assign req_latch = cx.eu && (cx.kind == V35_K_READ || cx.kind == V35_K_IO_READ);
    assign sfr_wr = cx.eu && cx.kind == V35_K_WRITE && cx.addr >= V35_SFR_PAGE;
    v35_st_t el;
    assign el = v35_st_t'(eu_l);
    assign sfr_value = el.e.sfr;
    // the early run as the EU reads it: bus.early is the cycle last started (cur), it ended on
    // t - 1 (ep: before the choice; after it, unless a fetch of the run started on t), early_n
    assign early_t = early_view(ra.early_on, ra.early_on && b_done, ra.early_n);
    assign early_p = early_view(a_x.early_on, ra.early_on && b_done && !cx.early_set, a_x.early_n);
    assign err_code = cx.err;
    for (genvar i = 0; i < 3; i++) begin : g_counts
        assign counts_t[i] = ra.q[i].count;
        assign counts_p[i] = a_x.q[i].count;
    end
    assign state_x = a_x;

    always @(posedge clock) begin
        if (!reset_n) begin
            ra <= '0;
            error <= 1'b0;
        end else if (ce) begin
            ra <= a_e;
            if (cx.err != 8'd0)
                error <= 1'b1;
        end
    end

`ifdef V35S_STATE_DUMP
    assign state_e = a_e;
    assign state_dump = ra;
`endif
endmodule
