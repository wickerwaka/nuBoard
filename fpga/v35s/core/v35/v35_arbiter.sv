`timescale 1ns/1ps

// V35S core v2: the arbiter, the full request path (docs/v35s-core-v2.md, "Modules and the state
// they own"; Appendix B §1 "Request records", §2 S4; stage S4). It holds the bus unit's request
// positions and picks the clock's bus cycle as one priority tree evaluated once: the slot's
// cycle (or the left-out write's slot), the aborted fetch cycle, or a fetch. The rules are the
// model's (validation/v35s/chains/sim/arbiter.py: Request.counts 137, arbitrate 180, _winner
// 301, _fetch_first 429, _choose 507; eu.py _submit 1736, _promote 1856, _port_take 1868,
// issue_nowrite 1970, issue 1995) under fit 62:
//
//   positions     the slot and two queued (io_release=post: a request posted while the slot
//                 holds a detached I/O, or while one is queued, goes behind; it moves into the
//                 slot, counting from that clock, when the request ahead issues: _promote,
//                 moved, dw_moved). The positions shift as registers; `own` names the EU's.
//   counting      data_while_fetch=wait_before (counted before the choice; a request moved in
//                 on the choice counts as posted before it), io_count=nowait, setup_free,
//                 rmw_alu=through, grp_free_bus (with grp_disp's), dw_count=bus, dw_count_b2b
//   the window    free_run=run (call_far_post's restart), free_hold=delivery, free_idle (and
//                 free_idle_b2b), grp_io_hold (grp_io_any=free, grp_io_lift=end), slot_fetch=
//                 slot, grp_disp=hold (gdisp_until, the read's gdisp), ea_b2b, sreg_store=own,
//                 sreg_io=hold
//   fetch holds   hold_fetch=le_q (hold_count=ahead, whole), floor_hold (disp_floor=posted),
//                 io_hold=posted_b2b, the I/O lead (lift, dw_lift=moved, dw_slot=behind),
//                 io_recover 2, wb_fetch=hold, wlatch_hold, io_ir_hold (the queue's io_held)
//   choice        the atomic odd-word pair's second half first; arbiter=b2b (_fetch_first:
//                 b2b_at, or became-issuable and requested on the same clock; imm1_first=hold),
//                 the nowrite slot (grp_read=rmw_slot_any, slot_room=word, slot_idle=eu,
//                 slot_latch: the fetch that runs in it), the aborted cycle (abort_fetch=retry,
//                 abort_latched=any), request_reissue=no_mem, port_latch=relatch with
//                 port_ready=issue / port_ready_count=count and port_issue (not_before)
//   (S5b) the 0F page: page_mem=fixed / bf_read=fixed (Request.page_free: a fetch on the bus
//                 not committed back to back after the read's post restarts its count;
//                 page_commit=post), page_run (run_wait: a committed fetch's wait clocks not
//                 counted; a back-to-back fetch not held while a 0F read waits), page_cl=thru
//                 (pthru: a fetch requested after the read's post, or the d16 take's, waits out
//                 the read's fetch-free clocks then runs in its CL clocks, Cycle.thru;
//                 _page_take_ask), ftail (a bit field's read after ftail fetch-free clocks),
//                 page_imm_run=delivery (_page_imm_run: Cycle.b2b), bcd_fetch=hold's setup
//   not built     refresh (no refresh-on family is gated), io_ext (disp_io_wait, a candidate)
//
// Registered state (widths) and the model variables it replaces, per position (slot, q0, q1;
// arbiter.Request; `posted` survives only as the order flags and the moved bits):
//   v 1, d (req_t: kind 3, nowrite 1, addr 20, width 2, data 16, setup 7, fn_v 1, fn 7,
//   lead 2, port 1, detached 1, grp 1, through 7, imm1 1, gdisp 1, sreg 1, whole 1, restart 1,
//   nb 4, rl 2, alive 1, aoff 3, dlive 1)           cycles[0], the EU's descriptor as posted
//   count 7                                         count
//   fn_v 1, fn 7, fo 7                              free_need (None: fn_v 0), free_orig
//   iss 1, h2 1                                     issued (non-empty), the odd pair's second
//                                                   half issued (atomic: it goes next)
//   two 1                                           ... the request is such a pair (as its
//                                                   address stood at the last clock's end)
//   dne 1                                           done_at reached (its last cycle delivered)
//   nwd 1, dn 3                                     the nowrite slot ran (issue_nowrite),
//                                                   done_at - t
//   nb 4                                            not_before - t (a countdown)
//   fhold 1                                         floor_hold
//   rs 1                                            ready_since is set
//   lift 1                                          lift_t is set
//   fhp 1, ghp 1                                    free_held == t-1, grp_held == t-1
//   moved 1, dwm 1                                  moved, dw_moved
//   rq_le 1, rq_lt 1                                the queue's requested_at <= / < posted
//   shl 1, sok 1, sat 1                             sreg_held, sreg_ok is set, sreg_at is set
// and for the arbiter:
//   own 2                                           eu.own's position (3: none)
//   rq_aio 1, io_seen 1                             requested_at >= ios[-1].start; an I/O ran
//   (S5b) tkq 1, tkr 1                              requested_at == queue.take_t (the request
//                                                   dated on the last take's clock); ... and
//                                                   b2b_at != take_t (_page_take_ask)
module v35_arbiter
    import v35_front_pkg::*;
(
    input  wire        clock,
    input  wire        reset_n,
    input  wire        ce,

    // the EU's posts (S2 T; S5 P) and retires
    input  wire        post_t,
    input  req_t       rq_t,
    input  wire        post_p,
    input  req_t       rq_p,
    input  wire        retire_t,        // the EU retired its own request (T)
    input  wire        retire_p,        // ... in the P pass
    // port_latch=relatch: a port byte taken now (T) holds the waiting detached I/Os
    input  wire        relatch,
    input  wire        relatch_late,    // port_landed: a clock later
    // disp_floor=posted: the displacement's take floors the slot's waiting memory request
    input  wire        floor_set,
    input  wire [3:0]  floor_nb,        // not_before - t
    // sreg_io=hold: a MOV sreg,r/m decoded while the slot's OUT waits
    input  wire        sreg_hold_set,
    // the EU
    input  wire        halting,         // halt_status: HALT started on this clock
    input  wire        halted,
    input  wire [2:0]  need,            // decoder.need (hold_count=ahead)
    input  wire        wb_hold,         // wb_fetch=hold
    input  wire        latch_wait,      // wlatch_hold
    input  wire        gdisp_act,       // grp_disp=hold: t < gdisp_until
    input  wire        ea_b2b_act,      // ea_b2b: a displaced memory form's EA clocks (t < ea_end)
    input  wire        take_now,        // an operand take on this clock (take_t == t)
    input  wire [19:0] ea_live,         // the running form's memory operand address
    input  wire [15:0] ea_lo,           // (S6) ... its offset (the segment's wrap)
    input  wire [15:0] wd_live,         // ... and its write datum (an RMW's result, POP's)
    input  wire        wd_rdy,          // (S6) ... computed (else the bus takes it at B2: g_dsel)
    input  wire [2:0]  sidle,           // the running class's sidle (slot_idle=eu)
    // the queue
    input  wire        want_x,
    input  wire        rq_v_x,
    input  wire        rq_now_x,
    input  wire        rq_v_end,        // requested_at is set at the clock's end
    input  wire        rq_now_end,      // ... dated on this clock (X, or S5's io_ir_hold)
    input  wire        rq_old_c,        // requested_at is set before this clock (< t)
    input  wire        b2b_now,
    input  wire signed [4:0] room_x,
    input  wire        inflight_c,
    input  wire        triple_x,
    input  wire        lat_x,
    input  wire        arrived_now,
    input  wire        io_hold_x,
    input  wire        xfer_x,          // (S5a) the running form is a transfer class (xfer_abort)
    // the bus (S0)
    input  wire        free,
    input  wire        busy,
    input  wire        cur_io,          // an I/O cycle runs on t
    input  wire [2:0]  cur_kind,        // (S5a) the cycle that runs on t
    input  wire        mf_old,          // (S5a) ... a fetch issued before mul_from (the sequencer's)
    input  wire        fetch_inflight,
    input  wire        in_wait,
    input  wire        fetch_end_prev,
    input  wire        fetch_run_prev,
    input  wire        io_win,
    input  wire [2:0]  fetch_len,
    input  wire [19:0] fetch_addr,
    input  wire        dlv_eu,          // an EU cycle ended on t-1 (its delivery)
    // (S5b) the 0F page
    input  wire        p_take,          // an operand take in the P pass (take_t == t)
    input  wire        t_start,         // a form started in the T pass (start_clock == t)
    input  wire        pfs_x,           // a 0F memory form's read not yet posted (page_fixed)
    input  wire        pimm_x,          // ... with an immediate bit index (page_imm_run)
    input  wire        pcl_x,           // the running form is a CL-index 0F memory form with a d16
    input  wire [2:0]  pcl_fs,          // ... its class's fsetup
    input  wire [3:0]  fetch_since,     // t - last_fetch_end (0 while a fetch runs)
    input  wire        cur_b2b_pfa,     // the fetch on the bus: committed b2b after the read's post
    input  wire        cur_thru,        // ... issued in a 0F read's cl clocks
    input  wire        prev_imm,        // the fetch that ended on t-1: after the start, no take since
    input  wire        bcd_idle,        // bcd_fetch=hold: the own read's setup a clock longer
    output wire        g_thru,          // the fetch issued now runs in the read's cl clocks
    output wire        g_pfa,           // ... it issued while a 0F read waits (after its post)
    output wire        slot_pf_e,       // the slot's 0F read waits unissued at the clock's end

    // S4: the grant
    output wire        g_start,
    output wire [2:0]  g_kind,
    output wire [19:0] g_addr,
    output wire [1:0]  g_width,
    output wire [15:0] g_data,
    output wire        g_fetch,         // a fetch issued (the queue's: a slot fetch included)
    output wire        g_eu,            // an EU cycle issued
    output wire        g_slot,          // the left-out write's slot ran (slot_latch)
    output wire        g_slot_fetch,    // ... with a fetch in it (queue.slot_fetch)
    output wire        g_wl_io,         // (S5a) a string form's I/O write issued (its datum latched)
    output wire        own_h2,          // (S5a) the own request's odd pair's second half issued
    output wire        g_abort,
    output wire        g_abort_lat,     // ... answered for the latched byte (abort_latched)
    output wire        g_mem_waiting,
    output wire        g_b2b,
    output wire        rq_set_x,        // the arbiter dates the request now (free_hold, grp_io_hold)
    output wire        retick,          // the EU's second pass (S5): a detached I/O, or the own
                                        // I/O write, issued (done_at == t)
    output wire        eu_issue,        // an EU cycle issued (ir_load=disp_data's release)
    output wire        g_ext,           // disp_io=extend: the I/O issued now runs a clock longer
    output wire [1:0]  g_dsel,          // the write datum at B2: 0 as granted; the immediate
                                        // (store_imm): 1 as is, 2 the pair's first half, 3 its second
    input  wire        disp_ext,        // ... the running memory form took its displacement now
    // the positions, as the EU reads them
    output wire        slot_wait_c,     // the slot holds a request with cycles left (before S4)
    output wire        slot_wait_p,     // ... after S4
    output wire        slot_det_c,      // ... a detached I/O write waits unissued
    output wire        slot_det_p,
    output wire        post_ok_c,       // a T post finds a position (_submit)
    output wire        post_ok_p,       // ... a P post
    output wire        slot_memw_c,     // the slot's request is a waiting memory one (_floor)
    output wire        dwq_c,           // dw_port: a DW-form I/O request waits queued ...
    output wire        dws_c,           // ... or in the slot
    output wire        own_issued,      // the own request is on the bus (ISSUED rows)
    output wire        own_done,        // its cycle ended on t-1 (T), or its I/O write issued (P)
    output wire        own_done_p,
    output wire        own_dlv,         // the own request's last cycle ended on t-1 (its datum)
    output wire        own_two,         // the own read was an odd word's pair (the datum's halves)
    output wire [1:0]  own_pos,         // the trace
    // the trace
    output wire [6:0]  count_o,
    output wire        ready_o,
    output wire [3:0]  why_o            // the fetch's hold reason (0: none)
);
    typedef struct packed {
        logic        v;
        req_t        d;
        logic [6:0]  count;
        logic        fn_v;
        logic [6:0]  fn;
        logic [6:0]  fo;
        logic        iss;
        logic        h2;
        logic        two;
        logic        dne;
        logic        nwd;
        logic [2:0]  dn;
        logic [3:0]  nb;
        logic        fhold;
        logic        rs;
        logic        lift;
        logic        fhp;
        logic        ghp;
        logic        moved;
        logic        dwm;
        logic        rq_le;
        logic        rq_lt;
        logic        shl;
        logic        sok;
        logic        sat;
    } rec_t;

    // ------------------------------------------------------------ registered state
    rec_t      r0 = '0, r1 = '0, r2 = '0;
    reg [1:0]  own = 2'd3;
    reg        rq_aio = 1'b0;
    reg        io_seen = 1'b0;
    reg        tkq = 1'b0;              // (S5b) requested_at == take_t
    reg        tkr = 1'b0;              // ... and b2b_at != take_t

    /* verilator lint_off UNUSEDSIGNAL */
    function automatic logic f_io(input rec_t r);
        f_io = k_io(r.d.kind);
    endfunction
    // a record as posted (the count 0, free_orig = min(free_need, setup) when set)
    function automatic rec_t mk(input req_t q);
        rec_t r;
        r = '0;
        r.v = 1'b1;
        r.d = q;
        r.fn_v = q.fn_v;
        r.fn = q.fn;
        r.fo = !q.fn_v ? 7'd0 : (q.fn < q.setup ? q.fn : q.setup);
        r.nb = q.nb;
        r.fhold = q.fhd;                // (S5a) str_single_start=write's floor holds fetches
        r.count = 7'(q.c0);             // (S5a) mul_imm_count=sync: the clean clocks back to mul_from
        r.rq_le = 1'b1;                 // requested_at <= posted (valid while it is set)
        r.rq_lt = rq_old_c;             // ... < posted: raised before the post's clock
        return r;
    endfunction
    // the record's address as it issues (a live EA: posted before the displacement; (S6) its
    // offset + 2 * aoff wraps in the segment)
    function automatic logic [16:0] rlo(input rec_t r);
        rlo = {1'b0, ea_lo} + {13'd0, r.d.aoff, 1'b0};
    endfunction
    function automatic logic [19:0] raddr(input rec_t r);
        logic [16:0] o;
        o = rlo(r);
        raddr = r.d.alive ? ea_live + {16'd0, r.d.aoff, 1'b0} - {3'd0, o[16], 16'd0} : r.d.addr;
    endfunction
    // (S6) an odd pair's second half: offset + 1 in the segment (FFFFh wraps to 0)
    function automatic logic [19:0] raddr2(input rec_t r);
        logic [16:0] o;
        o = rlo(r);
        raddr2 = raddr(r) + ((r.d.alive ? o[15:0] == 16'hFFFF : r.d.w16) ? 20'hF0001 : 20'd1);
    endfunction
    function automatic logic [15:0] rdata(input rec_t r);
        rdata = !r.d.dlive ? r.d.data : (r.d.width == BW_WORD ? wd_live
                                                             : {wd_live[7:0], wd_live[7:0]});
    endfunction
    // the atomic odd-word pair: a memory word at an odd address runs two cycles (hi, then lo)
    function automatic logic f_two(input rec_t r);
        logic [19:0] a;
        a = raddr(r);
        f_two = r.d.width == BW_WORD && a[0] && !k_io(r.d.kind) && !r.d.nowrite;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */

    // ------------------------------------------------------------ S2 (T): retire, post
    // the slot after T: the own request retired (its slot freed), a T post placed (_submit:
    // into the slot when it is free, behind a detached I/O or a queued request otherwise)
    wire       own0 = own == 2'd0;
    wire       slot_free_c = !r0.v || (own0 && retire_t);
    wire       det_wait_c = r0.v && r0.d.detached && !r0.iss;
    assign post_ok_c = !r0.v || own0 || ((det_wait_c || r1.v) && !r2.v);
    rec_t a0, a1, a2;
    logic [1:0] own_a, pos_t;
    always_comb begin
        pos_t = 2'd3;
        a0 = r0;
        a1 = r1;
        a2 = r2;
        own_a = own;
        if (retire_t && own0) begin
            a0 = '0;
            own_a = 2'd3;
        end else if (retire_t)
            own_a = 2'd3;
        if (post_t) begin
            if (slot_free_c) begin
                a0 = mk(rq_t);
                pos_t = 2'd0;
            end else if (!r1.v) begin
                a1 = mk(rq_t);
                pos_t = 2'd1;
            end else begin
                a2 = mk(rq_t);
                pos_t = 2'd2;
            end
            if (!rq_t.detached) own_a = pos_t;
        end
    end
    wire       pn = post_t && slot_free_c;        // the slot's request was posted on this clock

    assign slot_wait_c = r0.v && (!r0.iss || (r0.two && !r0.h2)) && !r0.nwd;
    assign slot_det_c = det_wait_c && r0.d.kind == K_IO_WRITE;
    assign slot_memw_c = r0.v && !r0.iss && !r0.nwd && !r0.d.detached && !f_io(r0);
    // dw_port=hold: a DW-form I/O request (no port byte) waits behind another, or in the slot
    assign dwq_c = (r1.v && f_io(r1) && !r1.d.port) || (r2.v && f_io(r2) && !r2.d.port);
    assign dws_c = r0.v && !r0.iss && f_io(r0) && !r0.d.port;

    // port_latch=relatch (eu._port_take): every waiting detached request is held to relatch
    // clocks after the port take, unless it issues on this clock (port_ready=issue: ready, or a
    // nowait count that counts out now; past its floor, the bus idle)
    // (the request the port take itself posts is not one of them)
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic logic rl_hit(input rec_t r, input logic newp);
        logic skip;
        skip = (r.count >= r.d.setup || (f_io(r) && r.count + 7'd1 >= r.d.setup))
               && r.nb == 4'd0 && !busy;
        rl_hit = relatch && r.v && !r.iss && r.d.detached && !skip && !newp;
    endfunction
    function automatic logic [3:0] rl_nb(input rec_t r, input logic hit);
        logic [3:0] d;
        d = 4'(r.d.rl) + (relatch_late ? 4'd1 : 4'd0);
        rl_nb = (hit && d > r.nb) ? d : r.nb;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    wire       h0 = rl_hit(a0, pos_t == 2'd0), h1 = rl_hit(a1, pos_t == 2'd1);
    wire       h2 = rl_hit(a2, pos_t == 2'd2);
    rec_t b0, b1, b2;               // after the relatch and the floor: S4 reads b0
    always_comb begin
        b0 = a0;
        b1 = a1;
        b2 = a2;
        b0.nb = rl_nb(a0, h0);
        b1.nb = rl_nb(a1, h1);
        b2.nb = rl_nb(a2, h2);
        // disp_floor=posted (eu._floor): the waiting memory request floored at once, its floor
        // holding fetches as its setup does
        if (floor_set && b0.v && !b0.iss && !b0.nwd && !b0.d.detached && !f_io(b0)) begin
            if (floor_nb > b0.nb)
                b0.nb = floor_nb;
            b0.fhold = 1'b1;
        end
        // sreg_io=hold: the slot's waiting OUT is held a clock past its count's end
        if (sreg_hold_set && b0.v && b0.d.detached && !b0.iss && b0.d.kind == K_IO_WRITE)
            b0.shl = 1'b1;
    end

    // ------------------------------------------------------------ S4: counting (arbitrate)
    wire       s_io = f_io(b0);
    wire       pending = b0.v && !b0.iss && !b0.nwd;
    wire [6:0] need_free = b0.fn_v ? (7'(b0.fn) < b0.d.setup ? 7'(b0.fn) : b0.d.setup)
                                   : b0.d.setup;
    wire [6:0] free_lo = b0.d.setup - need_free;
    wire [6:0] thru_lo = free_lo > b0.d.through ? free_lo : b0.d.through;
    // grp_free_bus: none on an I/O cycle or its recovery (grp_disp: those only), the free ones
    // on an idle bus
    wire counts_grp = !io_win && (b0.d.gdisp || !busy || b0.count < free_lo);
    wire counts_mem = !fetch_inflight || b0.count < thru_lo;
    // (S5a) io_count=nowait: an I/O request's, and a dwlike one's (str_count / burst_count =
    // dw), every clock not a wait state
    // (S5a) mul_imm_count=sync (Request.mul_free): a cycle that is not a fetch, or a fetch
    // issued before mul_from, restarts the count
    wire mf_blk = b0.d.mfr && busy && (cur_kind != K_FETCH || mf_old);
    // (S5b) page_mem=fixed / bf_read=fixed (Request.page_free): a fetch on the bus restarts the
    // read's count unless the bus unit committed it back to back after the read's post (or,
    // page_cl=thru, it runs in the read's CL clocks); page_run: a committed fetch's wait clock
    // does not count
    wire pf_blk = b0.d.pfv && busy && cur_kind == K_FETCH && !cur_b2b_pfa
                  && !(b0.d.pth != 2'd0 && cur_thru);
    wire pf_rw = b0.d.pfv && b0.d.prw && busy && cur_kind == K_FETCH && in_wait;
    wire counts = b0.d.pfv ? (!pf_blk && !pf_rw)
                : b0.d.mfr ? !mf_blk
                : b0.d.nwt ? !in_wait : (b0.d.grp ? counts_grp : counts_mem);
    wire [6:0] count_b = (pending && (mf_blk || pf_blk)) ? 7'd0 : b0.count;
    wire cnt_inc = !halting && pending && count_b < b0.d.setup && counts;
    wire [6:0] count_x = count_b + (cnt_inc ? 7'd1 : 7'd0);
    wire ready_x = count_x >= b0.d.setup;
    wire holding_x = {1'b0, count_x} < {1'b0, b0.d.setup} - 8'(b0.d.lead);

    // ------------------------------------------------------------ S4: the choice (_choose)
    wire fw0 = want_x && !halted;
    wire recovering = pending && !s_io && io_win;
    // free_run=run: a request counting its fetch-free clocks lets the delivery-clock fetch run
    // (its free clocks count through it; call_far_post=take: they start again after it)
    wire free_run = pending && !s_io && b0.fn_v && {1'b0, count_x} > {1'b0, b0.d.setup} - 8'(b0.fn)
                    && fetch_end_prev && (!rq_v_x || rq_now_x);
    wire frun = free_run && fw0;
    wire [6:0] fr_lo = b0.d.setup - 7'(b0.fn);
    wire [6:0] count_r = (frun && b0.d.restart && count_x > fr_lo) ? fr_lo : count_x;
    wire [6:0] fn_r = (frun && !b0.d.restart) ? 7'd0 : b0.fn;
    // free_hold=delivery
    wire fh_cand = pending && fw0 && !s_io;
    wire fh_date = fh_cand && b0.fhp;
    wire [6:0] fn_h = (fh_date && fn_r != 7'd0) ? 7'd0 : fn_r;
    wire fh_hold = fh_cand && !b0.fhp && fn_r != 7'd0 && b0.fn_v
                   && count_r == b0.d.setup - 7'(fn_r) && fetch_end_prev && rq_now_x && !b2b_now
                   && !fetch_run_prev;
    wire fw1 = fw0 && !fh_hold;
    // grp_io_hold (grp_io_any=free, grp_io_lift=end): a group request's next clock a bus-free
    // group clock while an I/O cycle or its recovery holds it: a fetch requested on or after
    // that I/O's issue waits; the held fetch dates from the clock the hold ends
    wire rq_aio_x = fh_date || (rq_now_x ? io_seen : (rq_aio && rq_v_x));
    wire gio_cand = pending && b0.d.grp && b0.fn_v && fn_h != 0 && fw1 && !s_io
                    && count_r >= b0.d.setup - 7'(fn_h);
    wire gio_hold = gio_cand && io_win && rq_v_x && rq_aio_x;
    wire gio_date = gio_cand && !gio_hold && b0.ghp;
    wire fw2 = fw1 && !gio_hold;
    wire rq_dated = fh_date || gio_date;  // requested_at = t (a later request than the post)
    assign rq_set_x = rq_dated;
    wire rq_now = rq_now_x || rq_dated;
    wire rq_v_a = rq_v_x || rq_dated;
    wire rq_lt_x = b0.rq_lt && !rq_now;
    // slot_fetch=slot: a request moved into the slot when the I/O ahead issued holds a fetch
    // requested before that until its fetch-free clocks start, then counts through it
    wire sf_cand = pending && b0.moved && fw2 && b0.fn_v && fn_h != 7'd0 && !b0.d.grp && !ready_x
                   && rq_v_a && rq_lt_x;
    wire sf_hold = sf_cand && count_r <= b0.d.setup - 7'(fn_h);
    wire [6:0] fn_s = (sf_cand && !sf_hold) ? 7'd0 : fn_h;
    wire fw3 = fw2 && !sf_hold;
    // grp_disp=hold: no fetch on the group RMW form's displacement take clock or the grp_free
    // clocks after it (one committed back to back goes; on the take clock itself one with room
    // for two words left goes); its read holds a fetch no older than it until its fetch-free
    // group clocks have begun
    wire gd_hold = fw3 && !b2b_now && gdisp_act && (!take_now || room_x < 5'sd4);
    wire gr_hold = pending && b0.d.gdisp && fw3 && !b2b_now && count_r <= b0.d.setup - 7'(b0.fo)
                   && (!rq_v_a || !rq_lt_x);
    wire fw4 = fw3 && !gd_hold && !gr_hold;
    // ea_b2b: no back-to-back fetch on an EA clock before the displacement's take
    wire eb_hold = fw4 && b2b_now && ea_b2b_act;
    wire fw5 = fw4 && !eb_hold;
    // sreg_store=own: MOV r/m,sreg's write issues only after a clock it was issuable but for a
    // fetch (holding fetches on that clock)
    wire nb_ok = b0.nb == 4'd0;
    wire sr_cond = ready_x && nb_ok && !recovering && (free || fetch_inflight);
    wire sr_on = pending && b0.d.sreg;
    wire sok_now = sr_on && sr_cond && !b0.sok;
    wire sreg_wait = sr_on && (!sr_cond || sok_now);
    wire fw6 = fw5 && !sok_now;
    // the order flags (requested_at against the slot request's post)
    wire rq_le_x = pn ? 1'b1 : (b0.rq_le && !rq_now);
    wire rq_eq_x = rq_le_x && !rq_lt_x;
    // (S5b) requested_at == take_t: dated on the last take's clock (this clock's take: T's),
    // and not on a back-to-back commitment's clock (_page_take_ask)
    wire tkq_now = take_now ? rq_now : (tkq && rq_v_a && !rq_now);
    wire tkr_now = take_now ? (rq_now && !b2b_now) : (tkr && rq_v_a && !rq_now);
    wire take_ask = pcl_x && need == 3'd0 && tkr_now;
    // (S5b) page_cl=thru: a fetch requested after the 0F read's post (or on its post's clock,
    // the last take's; or the d16 take's request) waits out the read's fetch-free clocks
    // (fsetup), then runs inside its CL clocks (thru)
    wire pth_cand = pending && b0.d.pfv && b0.d.pth != 2'd0 && fw6 && rq_v_a
                    && ((!b2b_now && (!rq_le_x || (rq_eq_x && tkq_now))) || take_ask);
    wire pth_hold = pth_cand && count_r <= b0.d.setup - 7'(b0.d.pth);
    // ... the fetch the d16 take asks for before the read's post: no earlier than fsetup
    // clocks after the last fetch's end
    wire ptk_cand = pfs_x && pcl_x && fw6 && !pth_hold && take_ask;
    wire ptk_hold = ptk_cand && fetch_since <= {1'b0, pcl_fs};
    wire thru = (pth_cand && !pth_hold) || (ptk_cand && !ptk_hold);
    wire fw6b = fw6 && !pth_hold && !ptk_hold;
    // (S5b) page_run: the 0F read not yet issued (eu.page_active, the form's read posted or not)
    wire pg_act_x = pfs_x || (pending && b0.d.pfv);
    // hold_fetch=le_q (hold_count=ahead, whole), floor_hold, io_hold=posted_b2b
    wire signed [5:0] counted = 6'sd6 - 6'(room_x);
    wire hold_le = counted - (b0.d.whole ? 6'sd0 : $signed({3'd0, need})) > 6'(FIT_HOLD_Q);
    wire hf_on = pending && (holding_x || recovering || (b0.fhold && !nb_ok)) && !free_run;
    // (S5b) page_run: a back-to-back fetch beside a waiting 0F read goes; page_cl=thru: a thru
    // fetch on a delivery clock, or requested on the last take's clock, or the take's ask
    wire hf_pass = (s_io && b2b_now) || (b2b_now && pg_act_x)
                   || (thru && (fetch_end_prev || tkq_now || take_ask));
    wire hf_block = hf_on && !hf_pass && ((s_io && !pn) || hold_le);
    wire fw7 = fw6b && !hf_block;
    // wb_fetch=hold
    wire wb_block = wb_hold && !b2b_now && rq_v_a && (!rq_now || arrived_now);
    wire fw8 = fw7 && !wb_block;
    // io_ir_hold, wlatch_hold
    wire fw9 = fw8 && !io_hold_x && !latch_wait;
    // the I/O lead: committed to the request; a fetch requested no later than its post, on the
    // clock the hold lifts, runs first (dw_lift=moved: not one requested on a DW request's
    // move-in clock); dw_slot=behind: with a request queued behind it, the I/O first unless the
    // queue counts hold_q bytes or fewer
    wire lead_on = pending && b0.d.lead != 2'd0 && !holding_x;
    wire lift_now = lead_on && !b0.lift;
    wire lead_block = lead_on && (!lift_now || !rq_v_a || !rq_le_x || (b0.dwm && rq_eq_x)
                                  || (b0.dwm && b1.v && counted > 6'(FIT_HOLD_Q)));
    wire fetch_want = fw9 && !lead_block;
    // sreg_io=hold: the OUT's I/O one clock past the clock its setup counts out
    wire sat_now = pending && !b0.sat && ready_x;
    wire sat_hold = sat_now && b0.shl;
    // the slot's issuable request
    // (S5b) ftail: a bit field's read issues only once ftl clocks passed since the last fetch
    wire ftl_hold = b0.d.pfv && b0.d.ftl != 3'd0 && fetch_since <= {1'b0, b0.d.ftl};
    wire issuable = pending && ready_x && nb_ok && !recovering && !sreg_wait && !sat_hold
                    && !ftl_hold;
    wire rs_now = issuable && !b0.rs;
    wire s_two = f_two(b0);
    wire second = b0.v && b0.iss && s_two && !b0.h2;   // the odd pair's second half: next
    // _fetch_first (arbiter=b2b; imm1_first=hold)
    wire imm1_go = b0.d.imm1 && !b2b_now && fetch_end_prev && !fetch_run_prev
                   && counted > 6'(FIT_HOLD_Q);
    wire fetch_first = !imm1_go && (b2b_now || (rs_now && rq_now));
    wire take_slot = free && (second || (issuable && !(fetch_want && fetch_first)));
    wire nw_go = take_slot && !second && b0.d.nowrite;
    wire eu_go = take_slot && !nw_go;
    // the left-out write's slot (issue_nowrite): a fetch runs in it when the queue wants one
    // (grp_read=rmw_slot_any: or has room for a word, slot_room=word: a word delivered now not
    // counted)
    wire signed [4:0] room_sl = room_x + (arrived_now ? 5'sd2 : 5'sd0);
    wire sl_fetch = nw_go && (fetch_want || (!inflight_c && !halted && room_sl >= 5'sd2));
    wire latched_abort = !fetch_want && triple_x && lat_x && !arrived_now && !inflight_c
                         && room_x + 5'sd1 == 5'sd2 && !halted;
    // (xfer_abort=word: a transfer's start, displacement take and IR load see 2 or 3 bytes)
    wire abort_go = free && !take_slot && ((fetch_want && triple_x
                                            && (room_x == 5'sd2 || (xfer_x && room_x == 5'sd3)))
                                           || latched_abort);
    wire fetch_go = free && !take_slot && !abort_go && fetch_want;
    // the grant
    wire mem_wait = pending && !s_io;
    wire [19:0] s_addr = raddr(b0);
    wire [15:0] s_data = rdata(b0);
    wire        eu_last = second || !s_two;          // the request's last cycle issues
    assign g_eu = eu_go;
    assign g_slot = nw_go;
    assign g_slot_fetch = sl_fetch;
    assign g_wl_io = eu_go && b0.d.strc && b0.d.kind == K_IO_WRITE;
    assign g_fetch = fetch_go || sl_fetch;
    assign g_abort = abort_go;
    assign g_abort_lat = abort_go && latched_abort;
    assign g_start = eu_go || g_fetch;
    assign g_kind = eu_go ? b0.d.kind : K_FETCH;
    assign g_addr = !eu_go ? fetch_addr : (second ? raddr2(b0) : s_addr);
    assign g_width = !eu_go ? BW_WORD : second ? BW_LO : s_two ? BW_HI
                   : (b0.d.width == BW_WORD || k_io(b0.d.kind)) ? b0.d.width
                   : (s_addr[0] ? BW_HI : BW_LO);
    assign g_data = !eu_go ? 16'd0 : (second ? {8'd0, s_data[15:8]}
                                     : (s_two ? {s_data[7:0], 8'd0} : s_data));
    assign g_mem_waiting = mem_wait && !nw_go;
    assign g_dsel = !(eu_go && (b0.d.dimm || (b0.d.dlive && !wd_rdy))) ? 2'd0  // ((S6) late)
                  : second ? 2'd3 : s_two ? 2'd2 : 2'd1;
    // (S5b) page_imm_run=delivery (_page_imm_run): a fetch issued on the clock after a fetch's
    // last clock, that fetch issued after a 0F memory form with an immediate index took its
    // head (no take since) and after its start, the read not yet issued: committed back to back
    // as far as the read's count is concerned (Cycle.b2b)
    wire imm_run = pimm_x && prev_imm && !take_now && !t_start && pg_act_x;
    assign g_b2b = fetch_go && (b2b_now || imm_run);
    assign g_thru = fetch_go && thru;
    assign g_pfa = fetch_go && pending && b0.d.pfv;
    assign eu_issue = eu_go;
    wire        det_go = eu_go && eu_last && b0.d.detached;
    wire        own_io_go = eu_go && eu_last && own_a == 2'd0 && b0.d.kind == K_IO_WRITE;
    assign retick = det_go || own_io_go;
    // disp_io=extend: the running memory form took its displacement on this I/O issue clock
    assign g_ext = eu_go && k_io(b0.d.kind) && disp_ext;
    // free_idle (free_idle_b2b): the request's fetch-free clock taken by a run's delivery-clock
    // fetch (or a b2b one): an idle clock after it, the request no earlier than the next
    wire fresh = rq_now && fetch_end_prev;
    wire free_idle = fetch_go && mem_wait && b0.fo != 7'd0 && !b0.fhp
                     && count_r == b0.d.setup - 7'(b0.fo) && ((fresh && fetch_run_prev) || b2b_now);
    // dw_count=bus, dw_count_b2b: a DW-form I/O request's clock taken by a cycle starting
    wire s_dw = s_io || b0.d.dwl;
    wire dw1 = fetch_go && pn && s_dw && !b0.d.port && count_r != 7'd0;
    wire dw2 = fetch_go && !pn && s_dw && !b0.d.port && pending && cnt_inc && b2b_now && !b0.dwm;
    wire [6:0] count_e = count_r - ((dw1 || dw2) ? 7'd1 : 7'd0);
    assign count_o = count_x;
    assign ready_o = ready_x;
    assign why_o = !want_x ? 4'd0 : fh_hold ? 4'd1 : gio_hold ? 4'd2 : sf_hold ? 4'd3
                 : (gd_hold || gr_hold) ? 4'd4 : eb_hold ? 4'd5 : sok_now ? 4'd6
                 : hf_block ? 4'd7 : wb_block ? 4'd8 : (io_hold_x || latch_wait) ? 4'd9
                 : lead_block ? 4'd10 : 4'd0;

    // ------------------------------------------------------------ S4: the slot after the choice
    // port_issue (machine.py:212-218): a fetch issued on the port take's clock relatches a
    // clock later
    /* verilator lint_off UNUSEDSIGNAL */
    function automatic logic [3:0] pi_nb(input rec_t r, input logic hit);
        logic [3:0] d;
        d = 4'(r.d.rl) + 4'd1;
        pi_nb = (hit && fetch_go && d > r.nb) ? d : r.nb;
    endfunction
    /* verilator lint_on UNUSEDSIGNAL */
    // a request moving into the slot on this clock (_promote): counted as posted before the
    // choice (counts(False): an I/O's nowait every clock, a memory one unless a group's: the
    // I/O just issued is on the bus), then dw_count (the I/O took its first clock)
    function automatic rec_t promote(input rec_t r);
        rec_t p;
        logic c;
        p = r;
        p.moved = !f_io(r);
        p.dwm = f_io(r) && !r.d.port;
        c = r.d.nwt ? !in_wait : !r.d.grp;
        if (!halting && r.count < r.d.setup && c)
            p.count = r.count + 7'd1;
        if ((f_io(r) || r.d.dwl) && !r.d.port && p.count != 7'd0)
            p.count = p.count - 7'd1;
        p.rq_le = rq_v_x;
        p.rq_lt = rq_v_x && !rq_now_x;
        p.rs = 1'b0;
        p.lift = 1'b0;
        return p;
    endfunction
    rec_t c0, c1, c2;
    logic [1:0] own_c;
    always_comb begin
        c0 = b0;
        c1 = b1;
        c2 = b2;
        c0.nb = pi_nb(b0, h0);
        c1.nb = pi_nb(b1, h1);
        c2.nb = pi_nb(b2, h2);
        own_c = own_a;
        c0.count = count_e;
        c0.fn = fn_s;
        c0.fhp = fh_hold;
        c0.ghp = gio_hold;
        c0.rs = b0.rs || issuable;
        c0.lift = b0.lift || lift_now;
        c0.rq_le = rq_le_x;
        c0.rq_lt = rq_lt_x;
        if (sok_now)
            c0.sok = 1'b1;
        else if (sr_on && !sr_cond)
            c0.sok = 1'b0;
        if (sat_now) begin
            c0.sat = 1'b1;
            if (b0.shl && c0.nb == 4'd0)
                c0.nb = 4'd1;
        end
        // not_before = the fetch's end + 2 (this clock's value: its length + 1)
        if (free_idle && 4'(fetch_len) + 4'd1 > c0.nb)
            c0.nb = 4'(fetch_len) + 4'd1;
        if (eu_go) begin
            c0.iss = 1'b1;
            if (second)
                c0.h2 = 1'b1;
        end
        // done: the own read's / write's last cycle delivered (done_at <= t from then on)
        if (b0.iss && (!s_two || b0.h2) && dlv_eu)
            c0.dne = 1'b1;
        if (nw_go) begin
            // done_at: sidle clocks after the slot clock (no cycle in it), else the end of the
            // fetch in it + 1; dn = done_at - (t + 1)
            c0.nwd = 1'b1;
            // (dn = done_at - t here; the edge counts it down)
            c0.dn = sl_fetch ? fetch_len : sidle;
        end
        if (det_go) begin
            // the detached I/O issued: the slot moves on (_promote)
            c0 = c1.v ? promote(c1) : '0;
            c1 = c2;
            c2 = '0;
            own_c = own_a == 2'd3 ? 2'd3 : own_a - 2'd1;
        end
    end
    // the own request's state as the EU reads it: issued (its first cycle on the bus), done (a
    // read's or write's last cycle ended on t-1; the slot's run: done_at reached)
    wire   r0_last = r0.iss && (!r0.two || r0.h2);
    assign own_dlv = own0 && r0_last && dlv_eu;
    assign own_issued = own0 && r0.iss;
    assign own_done = own0 && (own_dlv || r0.dne || (r0_last && r0.d.kind == K_IO_WRITE)
                               || (r0.nwd && r0.dn == 3'd0));
    assign own_done_p = own_io_go;
    assign own_two = r0.two;
    assign own_h2 = eu_go && second && own0;
    assign own_pos = own;
    assign slot_wait_p = c0.v && (!c0.iss || (f_two(c0) && !c0.h2)) && !c0.nwd;
    wire   c_det_wait = c0.v && c0.d.detached && !c0.iss;
    assign slot_det_p = c_det_wait && c0.d.kind == K_IO_WRITE;
    wire   own_c0 = own_c == 2'd0;
    assign post_ok_p = !c0.v || own_c0 || ((c_det_wait || c1.v) && !c2.v);

    // ------------------------------------------------------------ S5 (P): retire, post
    rec_t e0, e1, e2;
    logic [1:0] own_e;
    always_comb begin
        e0 = c0;
        e1 = c1;
        e2 = c2;
        own_e = own_c;
        if (retire_p) begin
            if (own_c0) e0 = '0;
            own_e = 2'd3;
        end
        if (post_p) begin
            if (!e0.v) begin
                e0 = mk(rq_p);
                if (!rq_p.detached) own_e = 2'd0;
            end else if (!e1.v) begin
                e1 = mk(rq_p);
                if (!rq_p.detached) own_e = 2'd1;
            end else begin
                e2 = mk(rq_p);
                if (!rq_p.detached) own_e = 2'd2;
            end
        end
        // (S5b) bcd_fetch=hold (machine.py): a BCD string started on an idle bus: its first
        // read, posted there, counts its setup a clock later
        if (bcd_idle) begin
            if (own_e == 2'd0)
                e0.d.setup = e0.d.setup + 7'd1;
            else if (own_e == 2'd1)
                e1.d.setup = e1.d.setup + 7'd1;
        end
    end
    assign slot_pf_e = e0.v && e0.d.pfv && !e0.iss;

    // ------------------------------------------------------------ S6: the next state
    function automatic rec_t tick(input rec_t r);
        rec_t n;
        n = r;
        n.two = f_two(r);
        if (n.nb != 4'd0)
            n.nb = n.nb - 4'd1;
        if (n.nwd && n.dn != 3'd0)
            n.dn = n.dn - 3'd1;
        return n;
    endfunction
    // the order flags at the clock's end: requested_at cleared, or dated on this clock (after
    // a post on an earlier clock: later than the post; on the post's clock: equal to it)
    function automatic rec_t redate(input rec_t r, input logic posted_now);
        rec_t n;
        n = r;
        n.rq_lt = r.rq_lt && rq_v_end && !rq_now_end;
        n.rq_le = r.rq_le && rq_v_end && (!rq_now_end || posted_now);
        return n;
    endfunction
    // the slot's flags at the clock's end: a request dated on this clock after a post earlier
    // on it is still no younger than the post (rq_le); one dated later is
    always @(posedge clock) begin
        if (!reset_n) begin
            r0 <= '0;
            r1 <= '0;
            r2 <= '0;
            own <= 2'd3;
            rq_aio <= 1'b0;
            io_seen <= 1'b0;
            tkq <= 1'b0;
            tkr <= 1'b0;
        end else if (ce) begin
            r0 <= tick(redate(e0, pn || det_go || (post_p && !c0.v)));
            r1 <= tick(e1);
            r2 <= tick(e2);
            own <= own_e;
            // (S5b) requested_at == take_t (and b2b_at != take_t) at the clock's end
            if (take_now || p_take) begin
                tkq <= rq_v_end && rq_now_end;
                tkr <= rq_v_end && rq_now_end && !b2b_now;
            end else begin
                tkq <= tkq && rq_v_end && !rq_now_end;
                tkr <= tkr && rq_v_end && !rq_now_end;
            end
            if (eu_go && k_io(b0.d.kind)) begin
                io_seen <= 1'b1;
                rq_aio <= rq_now_end;
            end else if (rq_now_end)
                rq_aio <= io_seen;
            else if (!rq_v_end)
                rq_aio <= 1'b0;
        end
    end

    wire unused = &{1'b0, fetch_first, rq_set_x, r0.d.lead, cur_io};
endmodule
